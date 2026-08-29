"""
tests/test_dividend_payment_collector.py
배당 **지급일정** 수집기(collector_dividend_payment_kr.py) 오프라인 검증 (네트워크 불필요 · pytest)

실행: python -m pytest -q tests/test_dividend_payment_collector.py

────────────────────────────────────────────────────────────────────────────────
📌 여기 쓰는 데이터는 두 종류뿐입니다 (tests/test_dividend_collector.py 와 같은 규칙)
   ① **실제 DART 응답 원문**
      · report_nm 6종 — 2026-08 list.json(pblntf_ty="I") 3일치 표본에서 관찰된 표기 그대로.
      · 공시 원문 HTML — 롯데케미칼 rcept_no=20260820800655 (2026-08-20 접수) 실측 원문을
        tests/fixtures/dividend_payment_decision_lotte_chemical_20260820800655.html 에
        파일로 저장해 두고 **그 파일을 읽어서** 검증합니다(테스트 안에서 지어내지 않음).
        정답(오너가 DART 화면에서 직접 확인한 값): 1주당 배당금 500원, 배당기준일 2026-09-03,
        배당금지급 예정일자 2026-09-18, 배당금총액 21,074,903,000원, 시가배당률 0.89%.
   ② 합성 fake 응답 — 라벨이 빠진 문서, zip 이 아닌 응답, zip 안 파일이 여러 개인 경우처럼
      실데이터로 만들 수 없는 실패 시나리오에만 씁니다. 합성인 것을 각 상수/함수에 밝혔습니다.

📌 네트워크 함수(_http_get_json / _http_get_bytes)는 monkeypatch 로 갈아끼워 배선만
   확인하고, 실제 소켓은 절대 열지 않습니다.

⚠️ 이 테스트가 전부 통과해도 "DART 실서버와 잘 통신한다"는 뜻은 아닙니다.
   실통신 검증은 GitHub Actions 첫 실행 로그로만 가능합니다.

⚠️ 이 파일은 기존 tests/test_dividend_collector.py 와 **완전히 별개**입니다. 그쪽 파일은
   한 줄도 건드리지 않았습니다(기존 배당 데이터와 이 데이터가 섞이지 않게 하는 것이
   이번 작업의 최우선 지시사항입니다).
"""
import copy
import io
import json
import os
import re
import sys
import zipfile
from datetime import date

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import collector_dividend_payment_kr as cp                # noqa: E402


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures",
    "dividend_payment_decision_lotte_chemical_20260820800655.html")


# =============================================================================
# 실측 표본 ① — list.json(pblntf_ty="I") 3일치에서 관찰된 "배당" 포함 report_nm 6종.
# 원문 그대로입니다(가운데점은 "ㆍ" U+318D, 앞뒤·중간 공백 포함).
# =============================================================================
REAL_REPORT_NM_SAMPLES = (
    "[기재정정]현금ㆍ현물배당결정              (분기배당)",
    "부동산투자회사금전배당결정",
    "현금ㆍ현물배당결정",
    "현금ㆍ현물배당결정(자회사의 주요경영사항)",
    "현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정",
    "현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정(자회사의 주요경영사항)",
)


@pytest.fixture(scope="module")
def real_document_html():
    """실측 원문 HTML(파일에서 읽습니다 — 테스트 안에서 만들어 내지 않습니다)."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# =============================================================================
# 합성 도우미 (② 합성 fake — 실패 시나리오 재현용)
# =============================================================================
class _FakeResponse:
    def __init__(self, status_code=200, payload=None, content=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("JSON 아님")
        return self._payload


def _make_zip(files):
    """{이름: bytes} → zip 바이트. (합성)"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _list_payload(rows, total_page=1, status="000"):
    """list.json 응답 형태(합성 — 필드 구성은 실측 응답과 같습니다)."""
    payload = {"status": status, "message": "정상", "page_no": 1,
               "page_count": 100, "total_count": len(rows), "total_page": total_page}
    if status == "000":
        payload["list"] = rows
    return payload


def _row(report_nm, rcept_no, stock_code="011170", corp_name="롯데케미칼",
         corp_code="00164742", rcept_dt="20260820"):
    """list.json 의 한 행(합성 — 실측 응답과 같은 키 구성)."""
    return {"corp_cls": "Y", "corp_code": corp_code, "corp_name": corp_name,
            "stock_code": stock_code, "report_nm": report_nm, "rcept_no": rcept_no,
            "flr_nm": corp_name, "rcept_dt": rcept_dt, "rm": ""}


def _drop_row(html, label):
    """픽스처에서 특정 라벨이 들어 있는 <tr> 블록 하나를 통째로 삭제합니다(합성 변형)."""
    blocks = re.findall(r"<tr>.*?</tr>", html, flags=re.S)
    for block in blocks:
        if label in block:
            return html.replace(block, "", 1)
    raise AssertionError(f"픽스처에서 '{label}' 행을 찾지 못했습니다 — 픽스처가 바뀌었나요?")


@pytest.fixture
def no_sleep(monkeypatch):
    """§0-3-2 딜레이는 실제로 자지 않게 합니다(테스트 속도)."""
    calls = []
    monkeypatch.setattr(cp, "polite_sleep", lambda rng=None: calls.append(1) or 0.0)
    monkeypatch.setattr(cp.time, "sleep", lambda *_: None)
    return calls


# =============================================================================
# 1. report_nm 판정 규칙 — 실측 표본 6종
# =============================================================================
def test_araea_character_is_u318d_not_middle_dot():
    """
    "현금ㆍ현물" 의 가운데점은 U+318D(HANGUL LETTER ARAEA)입니다. 비슷하게 생긴
    U+00B7(·)로 바꿔치기되면 매칭이 통째로 깨지므로 코드포인트로 못 박아 둡니다.
    """
    assert "ㆍ" in cp.CASH_PROPERTY_DIVIDEND_PREFIX
    assert "·" not in cp.CASH_PROPERTY_DIVIDEND_PREFIX
    assert cp.CASH_PROPERTY_DIVIDEND_PREFIX == "현금ㆍ현물배당결정"


@pytest.mark.parametrize("report_nm, expected_kind", [
    (REAL_REPORT_NM_SAMPLES[0], cp.KIND_DIVIDEND_DECISION),
    (REAL_REPORT_NM_SAMPLES[1], cp.KIND_DIVIDEND_DECISION),
    (REAL_REPORT_NM_SAMPLES[2], cp.KIND_DIVIDEND_DECISION),
    (REAL_REPORT_NM_SAMPLES[3], cp.KIND_DIVIDEND_DECISION),
    (REAL_REPORT_NM_SAMPLES[4], cp.KIND_SHAREHOLDER_REGISTER_CLOSE),
    (REAL_REPORT_NM_SAMPLES[5], cp.KIND_SHAREHOLDER_REGISTER_CLOSE),
])
def test_classify_report_nm_matches_measured_samples(report_nm, expected_kind):
    assert cp.classify_report_nm(report_nm)["kind"] == expected_kind


def test_classify_plain_cash_property_decision():
    verdict = cp.classify_report_nm("현금ㆍ현물배당결정")
    assert verdict["kind"] == cp.KIND_DIVIDEND_DECISION
    assert verdict["is_correction"] is False
    assert verdict["is_subsidiary_notice"] is False
    assert verdict["report_nm_extra"] is None
    assert verdict["matched_prefix"] == cp.CASH_PROPERTY_DIVIDEND_PREFIX


def test_classify_reit_uses_its_own_prefix():
    """리츠는 '현금ㆍ현물배당결정' 표기를 쓰지 않습니다(롯데리츠 실측)."""
    verdict = cp.classify_report_nm("부동산투자회사금전배당결정")
    assert verdict["kind"] == cp.KIND_DIVIDEND_DECISION
    assert verdict["matched_prefix"] == cp.REIT_CASH_DIVIDEND_PREFIX


def test_classify_correction_prefix_is_flagged_and_extra_is_kept():
    verdict = cp.classify_report_nm(REAL_REPORT_NM_SAMPLES[0])
    assert verdict["kind"] == cp.KIND_DIVIDEND_DECISION
    assert verdict["is_correction"] is True
    # 괄호 부가정보는 버리지 않고 원문 그대로 보존합니다.
    assert verdict["report_nm_extra"] == "(분기배당)"


def test_classify_subsidiary_notice_is_flagged_but_not_remapped():
    verdict = cp.classify_report_nm("현금ㆍ현물배당결정(자회사의 주요경영사항)")
    assert verdict["kind"] == cp.KIND_DIVIDEND_DECISION
    assert verdict["is_subsidiary_notice"] is True
    assert verdict["report_nm_extra"] == "(자회사의 주요경영사항)"


def test_classify_shareholder_register_close_is_not_a_decision():
    for sample in (REAL_REPORT_NM_SAMPLES[4], REAL_REPORT_NM_SAMPLES[5]):
        verdict = cp.classify_report_nm(sample)
        assert verdict["kind"] == cp.KIND_SHAREHOLDER_REGISTER_CLOSE
        assert verdict["matched_prefix"] is None


def test_classify_unknown_dividend_title_is_unrecognized_not_guessed():
    """
    실측 표본 6종 밖의 '배당' 표기는 **추측해서 인식하지 않습니다.**
    (합성 예시 — 실제로 관찰된 적 없는 표기입니다)
    """
    verdict = cp.classify_report_nm("주식배당결정")
    assert verdict["kind"] == cp.KIND_UNRECOGNIZED
    assert verdict["matched_prefix"] is None


def test_classify_ignores_titles_without_dividend_keyword():
    assert cp.classify_report_nm("유상증자결정")["kind"] == cp.KIND_NOT_DIVIDEND
    assert cp.classify_report_nm("")["kind"] == cp.KIND_NOT_DIVIDEND
    assert cp.classify_report_nm(None)["kind"] == cp.KIND_NOT_DIVIDEND


def test_classify_strips_surrounding_whitespace():
    verdict = cp.classify_report_nm("   현금ㆍ현물배당결정   ")
    assert verdict["kind"] == cp.KIND_DIVIDEND_DECISION
    assert verdict["report_nm_extra"] is None


def test_classify_correction_of_shareholder_register_close_is_still_excluded():
    verdict = cp.classify_report_nm("[기재정정]현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정")
    assert verdict["kind"] == cp.KIND_SHAREHOLDER_REGISTER_CLOSE
    assert verdict["is_correction"] is True


# =============================================================================
# 2. 원문 파싱 — 실측 HTML 로 값 검증
# =============================================================================
def test_parses_every_field_from_the_real_document(real_document_html):
    parsed = cp.parse_dividend_decision_document(real_document_html)
    assert parsed["parse_status"] == cp.PARSE_OK
    assert parsed["missing_labels"] == []
    assert parsed["unparsed_values"] == []
    assert parsed["dividend_class"] == "중간배당"
    assert parsed["dividend_type"] == "현금배당"
    assert parsed["dps_common"] == 500
    assert parsed["dps_preferred"] is None          # 원문 "-" → 0 이 아니라 None
    assert parsed["yield_common"] == 0.89
    assert parsed["yield_preferred"] is None
    assert parsed["total_amount"] == 21074903000    # 콤마 제거 후 정수
    assert parsed["record_date"] == "2026-09-03"    # 오너가 화면에서 확인한 값
    assert parsed["pay_date_expected"] == "2026-09-18"
    assert parsed["board_resolution_date"] == "2026-08-20"


def test_rowspan_label_is_tracked_across_rows(real_document_html):
    """
    '3. 1주당 배당금(원)' 라벨 셀은 rowspan=2 라 두 번째 행에는 라벨이 없습니다.
    격자로 펼치지 않으면 '종류주식' 값을 어느 항목의 값인지 몰라 조용히 놓칩니다.
    """
    parsed = cp.parse_dividend_decision_document(real_document_html)
    # 보통주식/종류주식이 각각 제자리에 들어갔는지(둘 다 채워졌는지) 확인.
    assert parsed["dps_common"] == 500 and parsed["dps_preferred"] is None
    assert parsed["yield_common"] == 0.89 and parsed["yield_preferred"] is None
    assert parsed["parse_notes"] == []


def test_notes_keep_line_breaks_and_contain_no_tags(real_document_html):
    parsed = cp.parse_dividend_decision_document(real_document_html)
    notes = parsed["notes"]
    assert notes.startswith("1. 상기")
    assert "\n" in notes                     # <br> 이 줄바꿈으로 바뀌었는가
    assert "<br" not in notes and "<span" not in notes
    assert "42,775,419주" in notes            # 원문 숫자 표기를 건드리지 않았는가


def test_namespaced_br_tag_is_handled(real_document_html):
    """실제 원문에는 `<br xmlns:java="...">` 형태의 변형 태그가 들어 있습니다."""
    variant = real_document_html.replace(
        "<br>", '<br xmlns:java="http://xml.apache.org/xalan/java">')
    parsed = cp.parse_dividend_decision_document(variant)
    assert parsed["parse_status"] == cp.PARSE_OK
    assert "<br" not in parsed["notes"]
    assert "xmlns" not in parsed["notes"]
    assert "\n" in parsed["notes"]


def test_missing_one_label_is_partial_and_named(real_document_html):
    broken = _drop_row(real_document_html, "1. 배당구분")
    parsed = cp.parse_dividend_decision_document(broken)
    assert parsed["parse_status"] == cp.PARSE_PARTIAL
    assert "1. 배당구분" in parsed["missing_labels"]
    # 못 찾은 필드를 빈 문자열/0 으로 채우지 않습니다.
    assert parsed["dividend_class"] is None
    # 나머지 값은 그대로 살아 있어야 합니다.
    assert parsed["record_date"] == "2026-09-03"


def test_missing_both_core_labels_is_failed(real_document_html):
    broken = _drop_row(real_document_html, "6. 배당기준일")
    broken = _drop_row(broken, "7. 배당금지급 예정일자")
    parsed = cp.parse_dividend_decision_document(broken)
    assert parsed["parse_status"] == cp.PARSE_FAILED
    assert parsed["record_date"] is None
    assert parsed["pay_date_expected"] is None
    assert "6. 배당기준일" in parsed["missing_labels"]
    assert "7. 배당금지급 예정일자" in parsed["missing_labels"]


def test_missing_only_one_core_label_is_partial_not_failed(real_document_html):
    broken = _drop_row(real_document_html, "6. 배당기준일")
    parsed = cp.parse_dividend_decision_document(broken)
    assert parsed["parse_status"] == cp.PARSE_PARTIAL
    assert parsed["pay_date_expected"] == "2026-09-18"


def test_unexpected_date_format_is_not_converted(real_document_html):
    """
    'YYYY-MM-DD' 가 아닌 표기를 만나면 **우리가 형식을 추측해 변환하지 않습니다.**
    값은 None 이 되고 원문이 unparsed_values 에 남습니다(§0-1).
    """
    weird = real_document_html.replace("2026-09-03", "2026.09.03")
    parsed = cp.parse_dividend_decision_document(weird)
    assert parsed["record_date"] is None
    assert parsed["parse_status"] == cp.PARSE_PARTIAL
    assert {"label": "6. 배당기준일", "raw": "2026.09.03"} in parsed["unparsed_values"]


def test_impossible_date_is_rejected(real_document_html):
    weird = real_document_html.replace("2026-09-18", "2026-13-45")
    parsed = cp.parse_dividend_decision_document(weird)
    assert parsed["pay_date_expected"] is None
    assert parsed["parse_status"] == cp.PARSE_PARTIAL


def test_empty_or_garbage_document_is_failed_not_silently_empty():
    # 2026-08-29 재감사 L15: 기대치를 LABEL_SPECS **행 수**가 아니라 **필드 수**로 고칩니다.
    # LABEL_SPECS 에는 pay_date_expected 의 별칭 두 줄이 들어 있어, 예전 코드는 그 필드
    # 하나를 못 찾았을 때 missing_labels 에 두 번 실었습니다(= 결측 항목이 실제보다 많아
    # 보임). 이제 필드당 대표 표기 하나만 보고하므로 distinct 필드 수와 같아야 합니다.
    distinct_fields = {field for field, _key, _display in cp.LABEL_SPECS}
    for text in ("", "<html><body>표가 없습니다</body></html>"):
        parsed = cp.parse_dividend_decision_document(text)
        assert parsed["parse_status"] == cp.PARSE_FAILED
        assert len(parsed["missing_labels"]) == len(distinct_fields)
        # 중복 보고가 없어야 합니다(같은 필드가 두 번 실리면 안 됨)
        assert len(parsed["missing_labels"]) == len(set(parsed["missing_labels"]))


def test_reaudit_missing_labels_reports_each_field_only_once():
    """
    L15: 별칭이 두 개인 필드(pay_date_expected)를 못 찾았을 때 missing_labels 에 두 번
    실리면 안 됩니다. 결측 항목 수가 실제보다 많아 보여, 파싱 품질 판정이 왜곡됩니다.
    """
    # pay_date_expected 만 없고 나머지는 다 있는 문서를 만들어도, 그 필드는 한 번만 보고
    parsed = cp.parse_dividend_decision_document("")
    dup = [lbl for lbl in parsed["missing_labels"]
           if lbl in ("7. 배당금지급 예정일자", "5. 배당금지급 예정일")]
    assert len(dup) == 1, f"pay_date_expected 는 한 번만 보고되어야 합니다: {dup}"
    # 전체적으로도 중복이 없어야 합니다
    assert len(parsed["missing_labels"]) == len(set(parsed["missing_labels"]))
    # 보고된 표기는 전부 대표 표기(LABEL_SPECS 의 첫 항목)여야 합니다
    first_display = {}
    for field, _key, display in cp.LABEL_SPECS:
        first_display.setdefault(field, display)
    assert set(parsed["missing_labels"]) <= set(first_display.values())


def test_rowspan_label_without_stock_kind_sublabel_leaves_a_note():
    """
    합성 — '1주당 배당금(원)' 옆에 보통주식/종류주식 구분이 없는 표. 값을 아무 쪽에나
    넣어 버리면 안 되므로, 값은 비우고 왜 못 넣었는지 parse_notes 에 남깁니다.
    """
    html = ("<html><body><table><tr>"
            "<td>3. 1주당 배당금(원)</td><td>500</td></tr>"
            "<tr><td>6. 배당기준일</td><td>2026-09-03</td></tr>"
            "<tr><td>7. 배당금지급 예정일자</td><td>2026-09-18</td></tr>"
            "</table></body></html>")
    parsed = cp.parse_dividend_decision_document(html)
    assert parsed["dps_common"] is None and parsed["dps_preferred"] is None
    assert any("보통주식" in note for note in parsed["parse_notes"])
    assert parsed["parse_status"] == cp.PARSE_PARTIAL
    # 라벨 자체는 찾았으므로 missing_labels 에는 들어가지 않습니다(사실을 정확히 구분).
    assert "3. 1주당 배당금(원)" not in parsed["missing_labels"]


def test_label_matching_ignores_numbering_and_spacing():
    """라벨은 위치가 아니라 키워드로 찾습니다 — 번호·공백 표기가 달라도 잡혀야 합니다."""
    html = ("<html><body><table>"
            "<tr><td> 배당기준일 </td><td>2026-09-03</td></tr>"
            "<tr><td>7.배당금지급  예정일자</td><td>2026-09-18</td></tr>"
            "</table></body></html>")
    parsed = cp.parse_dividend_decision_document(html)
    assert parsed["record_date"] == "2026-09-03"
    assert parsed["pay_date_expected"] == "2026-09-18"


# =============================================================================
# 3. 원문 문서 취득(document.xml) — zip·인코딩 방어
# =============================================================================
def _patch_document_bytes(monkeypatch, body, status_code=200, content_type=None):
    seen = {}

    def fake_get(url, params, timeout, session):
        seen["url"] = url
        seen["params"] = params
        return status_code, body, content_type

    monkeypatch.setattr(cp, "_http_get_bytes", fake_get)
    return seen


def test_fetch_document_unzips_and_decodes_utf8(monkeypatch, real_document_html):
    body = _make_zip({"20260820800655.xml": real_document_html.encode("utf-8")})
    seen = _patch_document_bytes(monkeypatch, body,
                                 content_type="application/x-msdownload;charset=UTF-8")
    text = cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=lambda *_: None)
    assert "6. 배당기준일" in text
    assert seen["params"]["rcept_no"] == "20260820800655"


def test_fetch_document_falls_back_to_euckr(monkeypatch):
    """
    실측 원문은 meta 가 euc-kr 이라 주장했지만 실제로는 utf-8 이었습니다. 그래서 utf-8 을
    먼저 시도하되, 진짜 euc-kr 바이트가 오면 폴백해야 합니다(합성 — euc-kr 로 인코딩한 문서).
    """
    html = "<html><body><table><tr><td>6. 배당기준일</td><td>2026-09-03</td></tr></table></body></html>"
    raw = html.encode("euc-kr")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")            # 전제 확인: utf-8 로는 못 읽는 바이트
    body = _make_zip({"20260820800655.xml": raw})
    _patch_document_bytes(monkeypatch, body)
    messages = []
    text = cp.fetch_disclosure_document("20260820800655", "FAKE-KEY",
                                        log=messages.append)
    assert "배당기준일" in text
    # 조용히 넘어가지 않고 "utf-8 이 아니었다"는 사실을 남깁니다.
    assert any("euc-kr" in message for message in messages)


def test_fetch_document_rejects_non_zip_body(monkeypatch):
    """zip 이 아니면(예: 200 으로 온 JSON 오류) 파싱을 시도하지 않고 실패로 남깁니다."""
    body = json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."}).encode("utf-8")
    _patch_document_bytes(monkeypatch, body, content_type="application/json")
    with pytest.raises(cp.DartPaymentApiError) as exc:
        cp.fetch_disclosure_document("99999999999999", "FAKE-KEY", log=lambda *_: None)
    assert "zip" in str(exc.value)
    assert "013" in str(exc.value)


def test_fetch_document_error_never_leaks_api_key(monkeypatch):
    _patch_document_bytes(monkeypatch, b"not a zip at all")
    with pytest.raises(cp.DartPaymentApiError) as exc:
        cp.fetch_disclosure_document("20260820800655", "SUPER-SECRET-KEY",
                                     log=lambda *_: None)
    assert "SUPER-SECRET-KEY" not in str(exc.value)


def test_fetch_document_with_multiple_files_picks_rcept_no_and_says_so(monkeypatch):
    """실측은 파일 1개였지만, 여러 개여도 조용히 첫 번째를 쓰지 않습니다."""
    body = _make_zip({
        "attachment.xml": b"<html><body>attachment</body></html>",
        "20260820800655.xml": "<html><body><table><tr><td>6. 배당기준일</td>"
                              "<td>2026-09-03</td></tr></table></body></html>".encode("utf-8"),
    })
    _patch_document_bytes(monkeypatch, body)
    messages = []
    text = cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=messages.append)
    assert "배당기준일" in text
    joined = "\n".join(messages)
    assert "20260820800655.xml" in joined and "2개" in joined


def test_fetch_document_multiple_files_without_expected_name_logs_choice(monkeypatch):
    body = _make_zip({"a.xml": b"<html>a</html>", "b.xml": b"<html>b</html>"})
    _patch_document_bytes(monkeypatch, body)
    messages = []
    cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=messages.append)
    joined = "\n".join(messages)
    assert "a.xml" in joined and "b.xml" in joined      # 어떤 후보가 있었는지
    assert "첫 번째" in joined                          # 무엇을 왜 골랐는지


def test_fetch_document_empty_zip_fails_loudly(monkeypatch):
    _patch_document_bytes(monkeypatch, _make_zip({}))
    with pytest.raises(cp.DartPaymentApiError):
        cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=lambda *_: None)


def test_fetch_document_stops_everything_on_http_429(monkeypatch):
    _patch_document_bytes(monkeypatch, b"", status_code=429)
    with pytest.raises(cp.DartPaymentFatalError):
        cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=lambda *_: None)


def test_fetch_document_refuses_oversized_body(monkeypatch):
    _patch_document_bytes(monkeypatch, b"PK" + b"0" * (cp.MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(cp.DartPaymentApiError) as exc:
        cp.fetch_disclosure_document("20260820800655", "FAKE-KEY", log=lambda *_: None)
    assert "상한" in str(exc.value)


# =============================================================================
# 4. 공시목록 조회(list.json) — 페이지네이션·판정·건너뛴 것 세기
# =============================================================================
def _patch_list_pages(monkeypatch, pages):
    """pages: [payload, payload, ...] 를 page_no 순서대로 돌려주는 가짜 list.json."""
    calls = []

    def fake_get(url, params, timeout, session):
        calls.append(dict(params))
        index = int(params["page_no"]) - 1
        return 200, pages[index]

    monkeypatch.setattr(cp, "_http_get_json", fake_get)
    return calls


def test_fetch_disclosures_reads_every_page(monkeypatch, no_sleep):
    """
    실측한 3일 전부 total_page=2 였습니다. 1페이지만 읽으면 그날의 절반 가까이를 놓칩니다.
    """
    page1 = _list_payload([_row("현금ㆍ현물배당결정", "20260820800655")], total_page=2)
    page2 = _list_payload([_row("부동산투자회사금전배당결정", "20260820900001",
                                stock_code="330590", corp_name="롯데리츠")], total_page=2)
    calls = _patch_list_pages(monkeypatch, [page1, page2])

    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=lambda *_: None, stats=stats)

    assert [call["page_no"] for call in calls] == ["1", "2"]
    assert [call["pblntf_ty"] for call in calls] == ["I", "I"]
    assert len(events) == 2
    assert stats["pages"] == 2
    # §0-3-2 — 페이지 사이에 딜레이를 둡니다(첫 요청 앞에서는 기다리지 않습니다).
    assert len(no_sleep) == 1


def test_fetch_disclosures_status_013_is_zero_not_an_error(monkeypatch, no_sleep):
    _patch_list_pages(monkeypatch, [_list_payload([], status="013")])
    messages = []
    events = cp.fetch_dividend_decision_disclosures(
        "20260823", "20260823", "FAKE-KEY", log=messages.append)
    assert events == []
    assert any("0건" in message for message in messages)


def test_fetch_disclosures_refuses_to_guess_when_total_page_missing(monkeypatch, no_sleep):
    payload = _list_payload([_row("현금ㆍ현물배당결정", "20260820800655")])
    payload.pop("total_page")
    _patch_list_pages(monkeypatch, [payload])
    with pytest.raises(cp.DartPaymentApiError) as exc:
        cp.fetch_dividend_decision_disclosures("20260820", "20260820", "FAKE-KEY",
                                               log=lambda *_: None)
    assert "total_page" in str(exc.value)


def test_fetch_disclosures_excludes_shareholder_register_close_but_counts_it(
        monkeypatch, no_sleep):
    rows = [
        _row("현금ㆍ현물배당결정", "20260820800655"),
        _row("현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정", "20260820800700"),
        _row("현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정(자회사의 주요경영사항)",
             "20260820800701"),
    ]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    messages = []
    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=messages.append, stats=stats)
    assert [event["rcept_no"] for event in events] == ["20260820800655"]
    assert stats["shareholder_register_close"] == 2
    # 조용히 사라지지 않고 몇 건을 왜 건너뛰었는지 로그에 남습니다.
    assert any("주주명부폐쇄" in message for message in messages)


def test_fetch_disclosures_records_unrecognized_titles_for_humans(monkeypatch, no_sleep):
    """
    실측 표본 밖의 '배당' 표기는 이벤트로 만들지 않되, **표본을 남겨** 사람이 규칙을
    넓힐 수 있게 합니다(합성 표기 — 아직 관찰된 적 없습니다).
    """
    rows = [_row("주식배당결정", "20260820800999", corp_name="가상회사")]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    messages = []
    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=messages.append, stats=stats)
    assert events == []
    assert stats["unrecognized"] == 1
    sample = stats["unrecognized_samples"][0]
    assert sample["report_nm"] == "주식배당결정"
    assert sample["parse_status"] == cp.KIND_UNRECOGNIZED
    joined = "\n".join(messages)
    assert cp.KIND_UNRECOGNIZED in joined and "주식배당결정" in joined


def test_fetch_disclosures_skips_rows_without_stock_code(monkeypatch, no_sleep):
    rows = [
        _row("현금ㆍ현물배당결정", "20260820800655"),
        _row("현금ㆍ현물배당결정", "20260820800656", stock_code="", corp_name="비상장㈜"),
    ]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    messages = []
    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=messages.append, stats=stats)
    assert len(events) == 1
    assert stats["skipped_no_stock_code"] == 1
    assert any("종목코드가 없는" in message for message in messages)


def test_fetch_disclosures_keeps_unnormalizable_code_as_none_and_warns(
        monkeypatch, no_sleep):
    # 8자리 숫자는 종목코드가 아닙니다(normalize_stock_code 가 None 을 돌려줍니다).
    rows = [_row("현금ㆍ현물배당결정", "20260820800655", stock_code="12345678")]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    messages = []
    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=messages.append, stats=stats)
    # 배당결정 이벤트 자체는 버리지 않되, 종목코드를 지어내지도 않습니다(§0-1).
    assert len(events) == 1
    assert events[0]["stock_code"] is None
    assert events[0]["stock_code_raw"] == "12345678"
    assert stats["kept_with_unnormalized_stock_code"] == 1  # L3(2026-08-29): 이름 변경(버리지 않음)
    assert any("정규화하지 못했습니다" in message for message in messages)


def test_fetch_disclosures_counts_missing_rcept_no_without_deduping_them_together(
        monkeypatch, no_sleep):
    """🟡 L10(2026-08-29) — 접수번호(rcept_no)가 없는 행끼리 "같은 접수번호(None)"로
    취급해 서로를 중복이라고 버리면 안 됩니다(둘 다 진짜 별개의 공시일 수 있습니다).
    대신 몇 건이 없었는지 세어 둡니다."""
    rows = [
        _row("현금ㆍ현물배당결정", "", stock_code="011170", corp_name="롯데케미칼"),
        _row("현금ㆍ현물배당결정", "", stock_code="004990", corp_name="롯데지주"),
    ]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    messages = []
    stats = {}
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=messages.append, stats=stats)
    assert len(events) == 2                          # 둘 다 살아남아야 함(서로를 중복 취급 안 함)
    assert stats["missing_rcept_no"] == 2
    assert any("접수번호" in message for message in messages)


def test_fetch_disclosures_does_not_count_missing_rcept_no_when_all_present(
        monkeypatch, no_sleep):
    rows = [_row("현금ㆍ현물배당결정", "20260820800655")]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    stats = {}
    cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=lambda *_: None, stats=stats)
    assert stats["missing_rcept_no"] == 0


def test_fetch_disclosures_carries_flags_into_events(monkeypatch, no_sleep):
    rows = [
        _row("[기재정정]현금ㆍ현물배당결정              (분기배당)", "20260820800001"),
        _row("현금ㆍ현물배당결정(자회사의 주요경영사항)", "20260820800002"),
    ]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=lambda *_: None)
    by_id = {event["rcept_no"]: event for event in events}
    assert by_id["20260820800001"]["is_correction"] is True
    assert by_id["20260820800001"]["report_nm_extra"] == "(분기배당)"
    assert by_id["20260820800002"]["is_subsidiary_notice"] is True
    # report_nm 은 원문 그대로 보존합니다.
    assert by_id["20260820800001"]["report_nm"] == \
        "[기재정정]현금ㆍ현물배당결정              (분기배당)"


def test_fetch_disclosures_does_not_filter_by_universe(monkeypatch, no_sleep):
    """
    이 경로의 장점은 '기존 유니버스에 없는 신규 배당 회사도 잡힌다'는 것입니다.
    유니버스 파일을 아예 읽지 않는다는 사실을 못 박아 둡니다.
    """
    rows = [_row("현금ㆍ현물배당결정", "20260820800655", stock_code="999999",
                 corp_name="아무도 모르는 신규상장사")]
    _patch_list_pages(monkeypatch, [_list_payload(rows)])
    events = cp.fetch_dividend_decision_disclosures(
        "20260820", "20260820", "FAKE-KEY", log=lambda *_: None)
    assert [event["stock_code"] for event in events] == ["999999"]


def test_fetch_disclosures_stops_everything_on_http_403(monkeypatch, no_sleep):
    monkeypatch.setattr(cp, "_http_get_json", lambda *a, **k: (403, None))
    with pytest.raises(cp.DartPaymentFatalError):
        cp.fetch_dividend_decision_disclosures("20260820", "20260820", "FAKE-KEY",
                                               log=lambda *_: None)


def test_fetch_disclosures_stops_everything_on_fatal_dart_status(monkeypatch, no_sleep):
    monkeypatch.setattr(cp, "_http_get_json",
                        lambda *a, **k: (200, {"status": "020",
                                               "message": "요청 제한을 초과하였습니다."}))
    with pytest.raises(cp.DartPaymentFatalError):
        cp.fetch_dividend_decision_disclosures("20260820", "20260820", "FAKE-KEY",
                                               log=lambda *_: None)


# =============================================================================
# 5. 오케스트레이션 — append-only 정책 / 상태 파일
# =============================================================================
@pytest.fixture
def wired(monkeypatch, no_sleep, real_document_html):
    """
    list.json + document.xml 을 한꺼번에 가짜로 물려 주는 배선.
    `wired.rows` 를 바꾸면 그날 접수된 공시가 바뀌고, `wired.failures` 에 넣은 rcept_no 는
    원문 조회가 실패합니다.
    """
    class Wiring:
        def __init__(self):
            self.rows = []
            self.failures = set()
            self.document_calls = []
            self.list_params = []      # 어떤 접수일 구간으로 조회했는지(백필 검증용)
            self.html = real_document_html

    wiring = Wiring()
    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")

    def fake_json(url, params, timeout, session):
        wiring.list_params.append(dict(params))
        return 200, _list_payload(wiring.rows)

    def fake_bytes(url, params, timeout, session):
        rcept_no = params["rcept_no"]
        wiring.document_calls.append(rcept_no)
        if rcept_no in wiring.failures:
            return 404, b"", None
        return 200, _make_zip({f"{rcept_no}.xml": wiring.html.encode("utf-8")}), None

    monkeypatch.setattr(cp, "_http_get_json", fake_json)
    monkeypatch.setattr(cp, "_http_get_bytes", fake_bytes)
    return wiring


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_run_writes_three_separate_files(tmp_path, wired):
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"

    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       lookback_days=3, log=lambda *_: None,
                                       today=date(2026, 8, 21))
    assert code == 0

    events_path = out_dir / "dividend_kr_2026_payment_events.json"
    raw_path = out_dir / "dividend_kr_2026_payment_events_raw.jsonl"
    state_path = cache_dir / "dividend_kr_2026_payment_state.json"
    assert events_path.exists() and raw_path.exists() and state_path.exists()

    # 기존 배당 데이터 파일 이름과 하나도 겹치지 않습니다(오너 최우선 지시 — 데이터 분리).
    written = {path.name for path in out_dir.iterdir() if path.is_file()}
    assert "dividend_kr_2026_latest.json" not in written
    assert "dividend_kr_2026_raw.jsonl" not in written

    payload = _read_json(str(events_path))
    assert payload["summary"]["total_records"] == 1
    assert payload["summary"]["new_records_this_run"] == 1
    assert payload["summary"]["by_parse_status"] == {cp.PARSE_OK: 1}
    record = payload["records"][0]
    assert record["rcept_no"] == "20260820800655"
    assert record["record_date"] == "2026-09-03"
    assert record["pay_date_expected"] == "2026-09-18"
    assert record["dps_common"] == 500
    assert record["dart_document_url"].endswith("20260820800655")

    # §0-3-3 — 원본 HTML 은 가공본과 다른 파일에 그대로.
    raw_lines = raw_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(raw_lines) == 1
    raw_entry = json.loads(raw_lines[0])
    assert raw_entry["rcept_no"] == "20260820800655"
    assert "6. 배당기준일" in raw_entry["document_html"]
    assert "document_html" not in record        # 가공본에는 원문을 넣지 않습니다

    assert _read_json(str(state_path))["last_checked_de"] == "20260820"


def test_run_never_refetches_an_already_collected_rcept_no(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    assert wired.document_calls == ["20260820800655"]

    # 같은 공시가 다음 실행에서 또 목록에 잡혀도 원문을 다시 받지 않습니다(§0-3-2).
    (cache_dir / "dividend_kr_2026_payment_state.json").unlink()
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    assert wired.document_calls == ["20260820800655"]
    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    assert payload["summary"]["total_records"] == 1


def test_run_appends_new_records_and_keeps_old_ones_untouched(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    first = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))["records"][0]

    # 다음 날: [기재정정] 이 새 rcept_no 로 접수됨 → 원본을 지우지 않고 **추가**됩니다.
    wired.rows = [_row("[기재정정]현금ㆍ현물배당결정              (분기배당)",
                       "20260821800111", rcept_dt="20260821")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 22))

    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    records = payload["records"]
    assert [record["rcept_no"] for record in records] == ["20260820800655", "20260821800111"]
    assert records[0] == first                      # 기존 레코드는 한 글자도 안 바뀝니다
    assert records[1]["is_correction"] is True
    assert payload["summary"]["records_with_correction_flag"] == 1
    assert payload["summary"]["new_records_this_run"] == 1


def test_run_does_not_rewrite_events_file_when_nothing_is_new(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    events_path = out_dir / "dividend_kr_2026_payment_events.json"
    before = events_path.read_text(encoding="utf-8")

    wired.rows = []
    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       log=lambda *_: None, today=date(2026, 8, 22))
    assert code == 0
    # 내용이 같은 큰 파일을 매일 다시 커밋하지 않습니다.
    assert events_path.read_text(encoding="utf-8") == before
    # 그래도 "확인했다"는 사실은 상태 파일에 남습니다.
    state = _read_json(str(cache_dir / "dividend_kr_2026_payment_state.json"))
    assert state["last_checked_de"] == "20260821"


def test_run_does_not_advance_state_when_the_first_day_fails(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    wired.failures = {"20260820800655"}

    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       lookback_days=1, log=lambda *_: None,
                                       today=date(2026, 8, 21))
    # 실패를 조용히 성공으로 넘기지 않습니다.
    assert code == 2
    # '확인 끝'으로 적히지 않았으므로 다음 실행이 같은 구간을 다시 확인합니다.
    assert not (cache_dir / "dividend_kr_2026_payment_state.json").exists()


def test_run_advances_state_only_up_to_the_day_before_the_failure(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [
        _row("현금ㆍ현물배당결정", "20260819800001", rcept_dt="20260819"),
        _row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820"),
    ]
    wired.failures = {"20260820800655"}

    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       lookback_days=3, log=lambda *_: None,
                                       today=date(2026, 8, 21))
    assert code == 2
    state = _read_json(str(cache_dir / "dividend_kr_2026_payment_state.json"))
    assert state["last_checked_de"] == "20260819"        # 실패한 날의 전날까지만

    # 성공한 건은 이미 저장돼 있고, 다음 실행은 실패한 건만 다시 받습니다.
    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    assert [record["rcept_no"] for record in payload["records"]] == ["20260819800001"]
    wired.failures = set()
    wired.document_calls.clear()
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    assert wired.document_calls == ["20260820800655"]


def test_run_reports_document_failures_in_the_summary(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [
        _row("현금ㆍ현물배당결정", "20260819800001", rcept_dt="20260819"),
        _row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820"),
    ]
    wired.failures = {"20260820800655"}
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                lookback_days=3, log=lambda *_: None,
                                today=date(2026, 8, 21))
    summary = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))["summary"]
    assert summary["documents_failed_this_run"] == 1
    assert summary["document_failures"][0]["rcept_no"] == "20260820800655"


def test_run_skips_when_the_range_is_already_checked(tmp_path, wired):
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260820")
    messages = []
    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       log=messages.append, today=date(2026, 8, 21))
    assert code == 0
    # 조용히 지나가지 않고 왜 아무 일도 안 했는지 남깁니다.
    assert any("확인할 새 구간이 없습니다" in message for message in messages)
    assert wired.document_calls == []


def test_run_updates_state_even_when_no_dividend_decision_was_filed(tmp_path, wired):
    """평소(배당 시즌이 아닌 날)에도 같은 구간을 매일 다시 훑지 않기 위함입니다(§0-3-2)."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("유상증자결정", "20260820800002")]
    code = cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                       log=lambda *_: None, today=date(2026, 8, 21))
    assert code == 0
    state = _read_json(str(cache_dir / "dividend_kr_2026_payment_state.json"))
    assert state["last_checked_de"] == "20260820"
    assert wired.document_calls == []


def test_run_refuses_to_start_without_api_key(tmp_path, monkeypatch, no_sleep):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(cp, "_http_get_json",
                        lambda *a, **k: pytest.fail("키도 없이 네트워크를 부르면 안 됩니다"))
    with pytest.raises(cp.DartPaymentFatalError):
        cp.run_watch_payment_events("2026", str(tmp_path / "data"),
                                    cache_dir=str(tmp_path / "cache"),
                                    log=lambda *_: None, today=date(2026, 8, 21))


def test_run_refuses_to_overwrite_a_corrupt_events_file(tmp_path, wired):
    """append-only 데이터라, 기존 내용을 못 읽은 채 새로 쓰면 통째로 사라집니다."""
    out_dir = tmp_path / "data"
    out_dir.mkdir(parents=True)
    broken = out_dir / "dividend_kr_2026_payment_events.json"
    broken.write_text("{이건 JSON 이 아닙니다", encoding="utf-8")
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    with pytest.raises(cp.DartPaymentFatalError):
        cp.run_watch_payment_events("2026", str(out_dir),
                                    cache_dir=str(out_dir / "cache"),
                                    log=lambda *_: None, today=date(2026, 8, 21))
    assert broken.read_text(encoding="utf-8") == "{이건 JSON 이 아닙니다"


def test_run_keeps_partial_and_failed_records_with_their_reasons(tmp_path, wired):
    """파싱이 덜 됐다고 버리지 않습니다 — 무엇을 못 찾았는지와 함께 남깁니다(§0-1)."""
    wired.html = _drop_row(wired.html, "1. 배당구분")
    out_dir = tmp_path / "data"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(out_dir / "cache"),
                                log=lambda *_: None, today=date(2026, 8, 21))
    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    record = payload["records"][0]
    assert record["parse_status"] == cp.PARSE_PARTIAL
    assert "1. 배당구분" in record["missing_labels"]
    assert payload["summary"]["missing_label_counts"]["1. 배당구분"] == 1


def test_run_puts_unrecognized_titles_into_the_summary(tmp_path, wired):
    out_dir = tmp_path / "data"
    wired.rows = [
        _row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820"),
        _row("주식배당결정", "20260820800999", rcept_dt="20260820"),
    ]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(out_dir / "cache"),
                                log=lambda *_: None, today=date(2026, 8, 21))
    summary = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))["summary"]
    assert summary["scan_stats"]["unrecognized"] == 1
    assert summary["scan_stats"]["unrecognized_samples"][0]["report_nm"] == "주식배당결정"
    # 이벤트 자체는 만들지 않았습니다(추측해서 규칙을 넓히지 않기).
    assert summary["total_records"] == 1


def test_summary_always_carries_its_known_limitations(tmp_path, wired):
    out_dir = tmp_path / "data"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(out_dir / "cache"),
                                log=lambda *_: None, today=date(2026, 8, 21))
    summary = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))["summary"]
    assert summary["known_limitations"]
    assert any("기재정정" in line for line in summary["known_limitations"])
    assert any("자회사" in line for line in summary["known_limitations"])


def test_run_delays_between_document_requests(tmp_path, wired, no_sleep):
    out_dir = tmp_path / "data"
    wired.rows = [
        _row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820"),
        _row("현금ㆍ현물배당결정", "20260820800656", rcept_dt="20260820"),
        _row("현금ㆍ현물배당결정", "20260820800657", rcept_dt="20260820"),
    ]
    before = len(no_sleep)
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(out_dir / "cache"),
                                log=lambda *_: None, today=date(2026, 8, 21))
    # 원문 3건 → 요청 사이 딜레이 2번(첫 요청 앞에서는 기다리지 않습니다).
    assert len(no_sleep) - before >= 2


def test_state_file_is_written_atomically(tmp_path):
    path = tmp_path / "cache" / "dividend_kr_2026_payment_state.json"
    cp.write_payment_state(str(path), "20260820")
    assert _read_json(str(path))["last_checked_de"] == "20260820"
    assert not (tmp_path / "cache" / "dividend_kr_2026_payment_state.json.tmp").exists()


def test_module_level_containers_do_not_accumulate_state(tmp_path, wired):
    """
    모듈 최상위에 실행 중 변하는 전역 상태가 없어야 합니다(요청·상태가 실행 간에 새는 것을
    막기 위함). 전체 실행을 한 번 돌린 뒤 모듈 전역 컨테이너가 그대로인지 확인합니다.
    """
    mutable_before = {name: copy.deepcopy(value) for name, value in vars(cp).items()
                      if isinstance(value, (dict, list, set))
                      and not name.startswith("__")}
    out_dir = tmp_path / "data"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(out_dir / "cache"),
                                log=lambda *_: None, today=date(2026, 8, 21))
    mutable_after = {name: value for name, value in vars(cp).items()
                     if isinstance(value, (dict, list, set)) and not name.startswith("__")}
    assert set(mutable_before) == set(mutable_after)
    for name, before in mutable_before.items():
        assert before == mutable_after[name], f"모듈 전역 {name} 이 실행 중에 바뀌었습니다"


# =============================================================================
# 5-2. 일회성 백필(--bgn-de/--end-de) — 🔴 상태 파일 안전성이 핵심
#
#   왜 있는가: 감시 모드는 "한 번 지나간 날짜는 다시 안 훑는" 구조라, 첫 실행의 lookback
#   창보다 앞서 접수된 공시(실제 사례: 2026-08-20 롯데케미칼 rcept_no=20260820800655)는
#   영영 들어오지 않습니다. 백필은 그 구간을 한 번 메우는 경로입니다.
#
#   🔴 여기서 가장 중요한 것은 "백필이 매일 도는 감시를 깨지 않는다"입니다 —
#      상태 파일의 last_checked_de 가 백필 때문에 **뒤로 가면** 다음 정기 실행이 이미
#      확인한 구간을 DART 에 다시 요청하게 됩니다(§0-3-2 위반).
# =============================================================================
def _state_of(cache_dir):
    return _read_json(str(cache_dir / "dividend_kr_2026_payment_state.json"))


def test_backfill_scans_exactly_the_requested_range_ignoring_the_state_file(tmp_path, wired):
    """상태 파일이 이미 08-24 까지 확인 표시돼 있어도, 백필은 지정한 구간을 그대로 훑습니다."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260824")

    wired.rows = [_row("현금ㆍ현물배당결정", "20260805800001", rcept_dt="20260805")]
    code = cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                          cache_dir=str(cache_dir), log=lambda *_: None,
                                          today=date(2026, 8, 25))
    assert code == 0
    # 감시 모드였다면 08-25(=state+1)부터 훑었을 구간을, 백필은 지정한 대로 훑습니다.
    assert [(params["bgn_de"], params["end_de"]) for params in wired.list_params] == [
        ("20260801", "20260819")]
    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    assert [record["rcept_no"] for record in payload["records"]] == ["20260805800001"]


def test_backfill_never_moves_the_state_file_backwards(tmp_path, wired):
    """
    🔴 이 파일에서 가장 중요한 테스트.
    기존 상태 08-24 → 08-01~08-19 백필 → 상태 파일은 **여전히 08-24** 여야 합니다.
    08-19 로 되돌아가면 다음 정기 실행이 08-20 부터 다시 훑어 이미 확인한 닷새치를
    DART 에 다시 요청합니다(§0-3-2 위반).
    """
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260824")

    wired.rows = [_row("현금ㆍ현물배당결정", "20260805800001", rcept_dt="20260805")]
    cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                   cache_dir=str(cache_dir), log=lambda *_: None,
                                   today=date(2026, 8, 25))
    assert _state_of(cache_dir)["last_checked_de"] == "20260824"

    # 그리고 다음 정기 실행은 여전히 08-25 부터 시작합니다(08-20 부터가 아니라).
    wired.list_params.clear()
    wired.rows = []
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 26))
    assert [(params["bgn_de"], params["end_de"]) for params in wired.list_params] == [
        ("20260825", "20260825")]


def test_backfill_writes_the_state_file_when_there_was_none(tmp_path, wired):
    """되돌릴 기존 값이 없으면(상태 파일 자체가 없으면) 이번 구간의 끝 날짜로 새로 씁니다."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260805800001", rcept_dt="20260805")]

    code = cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                          cache_dir=str(cache_dir), log=lambda *_: None,
                                          today=date(2026, 8, 25))
    assert code == 0
    assert _state_of(cache_dir)["last_checked_de"] == "20260819"


def test_backfill_advances_the_state_file_when_it_is_behind(tmp_path, wired):
    """기존 값보다 뒤면 전진합니다(max 규칙의 반대쪽 — 되돌리지만 않으면 됩니다)."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260805")
    wired.rows = []
    cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                   cache_dir=str(cache_dir), log=lambda *_: None,
                                   today=date(2026, 8, 25))
    assert _state_of(cache_dir)["last_checked_de"] == "20260819"


def test_backfill_does_not_refetch_documents_it_already_has(tmp_path, wired):
    """백필 구간이 이미 수집된 날짜와 겹쳐도 원문을 다시 받지 않습니다(§0-3-2)."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [_row("현금ㆍ현물배당결정", "20260820800655", rcept_dt="20260820")]
    cp.run_watch_payment_events("2026", str(out_dir), cache_dir=str(cache_dir),
                                log=lambda *_: None, today=date(2026, 8, 21))
    assert wired.document_calls == ["20260820800655"]

    # 같은 공시가 백필 구간에도 잡히지만 rcept_no 가 이미 파일에 있으므로 원문 재요청 없음.
    cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260820",
                                   cache_dir=str(cache_dir), log=lambda *_: None,
                                   today=date(2026, 8, 25))
    assert wired.document_calls == ["20260820800655"]
    payload = _read_json(str(out_dir / "dividend_kr_2026_payment_events.json"))
    assert payload["summary"]["total_records"] == 1


def test_backfill_keeps_the_old_state_when_documents_fail(tmp_path, wired):
    """원문 실패가 있어도 상태 파일이 뒤로 가지 않습니다(실패했다고 되돌리지도 않습니다)."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260824")
    wired.rows = [_row("현금ㆍ현물배당결정", "20260805800001", rcept_dt="20260805")]
    wired.failures = {"20260805800001"}

    code = cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                          cache_dir=str(cache_dir), log=lambda *_: None,
                                          today=date(2026, 8, 25))
    assert code == 2                                    # 조용히 성공하지 않습니다
    assert _state_of(cache_dir)["last_checked_de"] == "20260824"


def test_backfill_without_a_state_file_stops_before_the_failed_day(tmp_path, wired):
    """상태 파일이 없을 때는 '실패한 날의 전날'까지만 확인한 것으로 적습니다(§0-1)."""
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    wired.rows = [
        _row("현금ㆍ현물배당결정", "20260805800001", rcept_dt="20260805"),
        _row("현금ㆍ현물배당결정", "20260810800002", rcept_dt="20260810"),
    ]
    wired.failures = {"20260810800002"}

    code = cp.run_backfill_payment_events("2026", str(out_dir), "20260801", "20260819",
                                          cache_dir=str(cache_dir), log=lambda *_: None,
                                          today=date(2026, 8, 25))
    assert code == 2
    assert _state_of(cache_dir)["last_checked_de"] == "20260809"


def test_backfill_refuses_a_range_that_is_not_yyyymmdd(tmp_path, wired):
    with pytest.raises(cp.DartPaymentFatalError):
        cp.run_backfill_payment_events("2026", str(tmp_path / "data"), "2026-08-01",
                                       "20260819", cache_dir=str(tmp_path / "cache"),
                                       log=lambda *_: None, today=date(2026, 8, 25))
    assert wired.list_params == []      # 구간을 모르는 채 DART 를 부르지 않습니다


def test_backfill_refuses_a_reversed_range(tmp_path, wired):
    with pytest.raises(cp.DartPaymentFatalError):
        cp.run_backfill_payment_events("2026", str(tmp_path / "data"), "20260819",
                                       "20260801", cache_dir=str(tmp_path / "cache"),
                                       log=lambda *_: None, today=date(2026, 8, 25))
    assert wired.list_params == []


def test_backfill_refuses_to_mark_today_as_checked(tmp_path, wired):
    """
    오늘은 아직 하루가 끝나지 않아 접수가 더 들어올 수 있습니다. 오늘을 '확인 끝'으로
    적으면 그날 나머지 공시를 영영 놓칩니다 — 감시 모드가 끝을 '어제'로 두는 이유와 같습니다.
    """
    with pytest.raises(cp.DartPaymentFatalError):
        cp.run_backfill_payment_events("2026", str(tmp_path / "data"), "20260801",
                                       "20260825", cache_dir=str(tmp_path / "cache"),
                                       log=lambda *_: None, today=date(2026, 8, 25))
    assert wired.list_params == []


def test_merge_last_checked_de_never_goes_backwards():
    """상태 병합 규칙 자체(순수 함수) — None 은 '상태 파일을 건드리지 않는다'는 뜻입니다."""
    assert cp.merge_last_checked_de("20260824", "20260819", log=lambda *_: None) is None
    assert cp.merge_last_checked_de("20260824", "20260824", log=lambda *_: None) is None
    assert cp.merge_last_checked_de("20260819", "20260824",
                                    log=lambda *_: None) == "20260824"
    assert cp.merge_last_checked_de(None, "20260819", log=lambda *_: None) == "20260819"
    # 기존 값을 못 읽으면 어느 쪽이 뒤인지 모릅니다 → 덮어쓰지 않습니다(§0-1).
    assert cp.merge_last_checked_de("2026-08-24", "20260819", log=lambda *_: None) is None


def test_backfill_warns_when_it_leaves_a_gap_behind(tmp_path, wired):
    """
    기존 상태(08-05) 다음 날 ~ 백필 시작일(08-10) 전날 구간은 아무도 확인하지 않았는데
    상태가 08-19 로 전진합니다 — 조용히 넘기지 않고 로그로 알립니다(§0-1).
    """
    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True)
    cp.write_payment_state(str(cache_dir / "dividend_kr_2026_payment_state.json"),
                           "20260805")
    wired.rows = []
    messages = []
    cp.run_backfill_payment_events("2026", str(out_dir), "20260810", "20260819",
                                   cache_dir=str(cache_dir), log=messages.append,
                                   today=date(2026, 8, 25))
    assert any("확인하지 않았습니다" in message for message in messages)


# =============================================================================
# 6. CLI
# =============================================================================
def test_cli_defaults_match_the_workflow(monkeypatch):
    captured = {}

    def fake_run(year, out_dir, cache_dir=None, lookback_days=3, api_key=None, log=print):
        captured.update({"year": year, "out_dir": out_dir, "cache_dir": cache_dir,
                         "lookback_days": lookback_days, "api_key": api_key})
        return 0

    monkeypatch.setattr(cp, "run_watch_payment_events", fake_run)
    assert cp.main(["--year", "2026"]) == 0
    assert captured["year"] == "2026"
    assert captured["out_dir"] == "data"
    assert captured["cache_dir"] == os.path.join("data", "cache")
    assert captured["lookback_days"] == 3
    assert captured["api_key"] is None


def test_cli_accepts_explicit_paths(monkeypatch):
    captured = {}
    monkeypatch.setattr(cp, "run_watch_payment_events",
                        lambda *a, **k: captured.update(k) or 0)
    cp.main(["--year", "2026", "--out-dir", "data", "--cache-dir", "data/cache",
             "--lookback-days", "7"])
    assert captured["cache_dir"] == "data/cache"
    assert captured["lookback_days"] == 7


def test_cli_requires_year(monkeypatch):
    monkeypatch.setattr(cp, "run_watch_payment_events",
                        lambda *a, **k: pytest.fail("--year 없이 실행되면 안 됩니다"))
    with pytest.raises(SystemExit):
        cp.main([])


def test_cli_has_no_universe_flag(monkeypatch):
    """
    유니버스로 사전 필터링하지 않는 것이 설계 의도입니다(기존 유니버스에 없는 신규 배당
    회사도 잡기 위함) — 옵션 자체가 없어야 실수로 켤 수 없습니다.
    """
    monkeypatch.setattr(cp, "run_watch_payment_events", lambda *a, **k: 0)
    with pytest.raises(SystemExit):
        cp.main(["--year", "2026", "--universe", "data/whatever.json"])


def test_cli_without_backfill_flags_still_runs_watch(monkeypatch):
    """회귀 방지 — 백필 옵션을 안 주면 기존 감시 모드 그대로입니다."""
    called = []
    monkeypatch.setattr(cp, "run_watch_payment_events",
                        lambda *a, **k: called.append("watch") or 0)
    monkeypatch.setattr(cp, "run_backfill_payment_events",
                        lambda *a, **k: pytest.fail("백필로 새면 안 됩니다"))
    assert cp.main(["--year", "2026"]) == 0
    assert called == ["watch"]


def test_cli_backfill_mode_passes_the_range_through(monkeypatch):
    captured = {}

    def fake_backfill(year, out_dir, bgn_de, end_de, cache_dir=None, api_key=None,
                      log=print):
        captured.update({"year": year, "out_dir": out_dir, "bgn_de": bgn_de,
                         "end_de": end_de, "cache_dir": cache_dir})
        return 0

    monkeypatch.setattr(cp, "run_backfill_payment_events", fake_backfill)
    monkeypatch.setattr(cp, "run_watch_payment_events",
                        lambda *a, **k: pytest.fail("백필 모드에서 감시가 돌면 안 됩니다"))
    assert cp.main(["--year", "2026", "--out-dir", "data", "--cache-dir", "data/cache",
                    "--bgn-de", "20260801", "--end-de", "20260824"]) == 0
    assert captured == {"year": "2026", "out_dir": "data", "bgn_de": "20260801",
                        "end_de": "20260824", "cache_dir": "data/cache"}


@pytest.mark.parametrize("argv", [
    ["--year", "2026", "--bgn-de", "20260801"],
    ["--year", "2026", "--end-de", "20260824"],
])
def test_cli_rejects_half_a_backfill_range(monkeypatch, capsys, argv):
    """
    한쪽만 주면 거의 확실히 실수입니다. 조용히 감시 모드로 돌면 사람이 의도한 구간이 아니라
    '어제까지 3일'만 훑고 끝나 버립니다 — 무엇이 잘못됐는지 말하고 멈춥니다(§0-1).
    """
    monkeypatch.setattr(cp, "run_watch_payment_events",
                        lambda *a, **k: pytest.fail("반쪽 구간으로 실행되면 안 됩니다"))
    monkeypatch.setattr(cp, "run_backfill_payment_events",
                        lambda *a, **k: pytest.fail("반쪽 구간으로 실행되면 안 됩니다"))
    with pytest.raises(SystemExit):
        cp.main(argv)
    message = capsys.readouterr().err
    assert "--bgn-de" in message and "--end-de" in message
    assert "둘 다" in message


def test_cli_returns_2_and_a_readable_message_on_fatal(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise cp.DartPaymentFatalError("DART status 020 — 요청 제한을 초과하였습니다.")

    monkeypatch.setattr(cp, "run_watch_payment_events", boom)
    assert cp.main(["--year", "2026"]) == 2
    printed = capsys.readouterr().out
    assert "중단했습니다" in printed
    assert "Traceback" not in printed
