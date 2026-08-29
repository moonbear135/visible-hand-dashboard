"""
dividend_module/test_dividend_collector.py
배당 수집기 오프라인 검증 (네트워크 불필요 · pytest)

실행: pytest -q dividend_module/build/test_dividend_collector.py

────────────────────────────────────────────────────────────────────────────────
📌 여기 쓰는 데이터는 두 종류뿐입니다 (tests/test_stock_history.py 와 같은 규칙)
   ① **실제 DART 응답 원문** — 2026-08-23 개발 세션에서 삼성전자(00126380)로 직접 호출해
      받은 것을 그대로 붙여 넣었습니다. 지어낸 값이 아닙니다.
   ② 합성 fake 응답 — 우선주 2종 회사, 라벨 변경, 오류 상태처럼 실데이터로 만들 수 없는
      실패 시나리오에만 씁니다. 합성인 것을 각 상수 주석에 명시했습니다.

📌 이 파일이 검증하는 것 = **순수 함수 전부**. 네트워크 함수(_http_get_json /
   _http_get_bytes)는 monkeypatch 로 갈아끼워 배선만 확인하고, 실제 소켓은 절대 열지
   않습니다.

⚠️ 이 테스트가 전부 통과해도 "DART 실서버와 잘 통신한다"는 뜻은 아닙니다.
   실통신 검증은 GitHub Actions 첫 실행 로그로만 가능합니다.
"""
import io
import json
import os
import sys
import time
import zipfile

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pathlib import Path                             # noqa: E402
import corp_code_mapper as ccm                       # noqa: E402
import collector_dividend_kr as cdk                  # noqa: E402


# =============================================================================
# 실제 응답 원문 (① 실데이터)
# 삼성전자 corp_code=00126380 / bsns_year=2026 / reprt_code=11013 (1분기보고서)
# 2026-08-23 취득. 값을 한 글자도 고치지 않았습니다.
# =============================================================================
REAL_SAMSUNG_2026_Q1 = {
    "status": "000",
    "message": "정상",
    "list": [
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당액면가액(원)", "stock_knd": "-",
         "thstrm": "100", "frmtrm": "100", "lwfr": "100", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "(연결)당기순이익(백만원)", "stock_knd": "-",
         "thstrm": "47,101,190", "frmtrm": "44,260,956", "lwfr": "33,621,363",
         "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "(별도)당기순이익(백만원)", "stock_knd": "-",
         "thstrm": "39,924,263", "frmtrm": "33,686,601", "lwfr": "23,582,565",
         "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "(연결)주당순이익(원)", "stock_knd": "-",
         "thstrm": "7,123", "frmtrm": "6,605", "lwfr": "4,950", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "현금배당금총액(백만원)", "stock_knd": "-",
         "thstrm": "2,453,316", "frmtrm": "11,107,906", "lwfr": "9,810,767",
         "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주식배당금총액(백만원)", "stock_knd": "-",
         "thstrm": "-", "frmtrm": "-", "lwfr": "-", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "(연결)현금배당성향(%)", "stock_knd": "-",
         "thstrm": "5.20", "frmtrm": "25.10", "lwfr": "29.20", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "현금배당수익률(%)", "stock_knd": "보통주",
         "thstrm": "0.20", "frmtrm": "1.50", "lwfr": "2.70", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "현금배당수익률(%)", "stock_knd": "우선주",
         "thstrm": "0.30", "frmtrm": "1.90", "lwfr": "3.30", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주식배당수익률(%)", "stock_knd": "보통주",
         "thstrm": "-", "frmtrm": "-", "lwfr": "-", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주식배당수익률(%)", "stock_knd": "우선주",
         "thstrm": "-", "frmtrm": "-", "lwfr": "-", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 현금배당금(원)", "stock_knd": "보통주",
         "thstrm": "372", "frmtrm": "1,668", "lwfr": "1,446", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 현금배당금(원)", "stock_knd": "우선주",
         "thstrm": "372", "frmtrm": "1,669", "lwfr": "1,447", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 주식배당(주)", "stock_knd": "보통주",
         "thstrm": "-", "frmtrm": "-", "lwfr": "-", "stlm_dt": "2026-03-31"},
        {"rcept_no": "20260515002181", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 주식배당(주)", "stock_knd": "우선주",
         "thstrm": "-", "frmtrm": "-", "lwfr": "-", "stlm_dt": "2026-03-31"},
    ],
}

# 실제 응답 원문 — 삼성전자 2026 반기보고서(11012)에서 확인한 배당 관련 4행.
# ⚠️ 주당현금배당금은 372 → 746 으로 누적됐는데 현금배당수익률은 0.20% 그대로입니다.
#    이 "원자료의 이상"을 우리가 보정하지 않는다는 것을 테스트로 못 박습니다.
REAL_SAMSUNG_2026_H1_PARTIAL = {
    "status": "000",
    "message": "정상",
    "list": [
        {"rcept_no": "20260814003699", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "현금배당수익률(%)", "stock_knd": "보통주",
         "thstrm": "0.20", "frmtrm": "1.50", "lwfr": "2.70", "stlm_dt": "2026-06-30"},
        {"rcept_no": "20260814003699", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "현금배당수익률(%)", "stock_knd": "우선주",
         "thstrm": "0.30", "frmtrm": "1.90", "lwfr": "3.30", "stlm_dt": "2026-06-30"},
        {"rcept_no": "20260814003699", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 현금배당금(원)", "stock_knd": "보통주",
         "thstrm": "746", "frmtrm": "1,668", "lwfr": "1,446", "stlm_dt": "2026-06-30"},
        {"rcept_no": "20260814003699", "corp_cls": "Y", "corp_code": "00126380",
         "corp_name": "삼성전자", "se": "주당 현금배당금(원)", "stock_knd": "우선주",
         "thstrm": "746", "frmtrm": "1,669", "lwfr": "1,447", "stlm_dt": "2026-06-30"},
    ],
}

# 실제 응답 원문 — 3분기보고서 미제출 시점 / 존재하지 않는 corp_code 둘 다 이것입니다.
REAL_NO_DATA = {"status": "013", "message": "조회된 데이타가 없습니다."}
# 실제 응답 원문 — 잘못된 인증키
REAL_BAD_KEY = {"status": "010", "message": "등록되지 않은 인증키입니다."}


# =============================================================================
# 1. 숫자 정규화 (to_number)
# =============================================================================
def test_to_number_removes_thousand_separator():
    """콤마가 섞인 문자열이 실수로 변환되어야 합니다."""
    assert cdk.to_number("11,107,906") == 11107906.0


def test_to_number_treats_dash_as_missing_not_zero():
    """DART 의 '-'(해당없음)는 0 이 아니라 None 이어야 합니다 (§0-1: 없음≠0)."""
    assert cdk.to_number("-") is None


def test_to_number_keeps_real_zero():
    """진짜 '0'은 None 이 아니라 0.0 이어야 합니다 — 무배당과 0원 결의는 다른 사실입니다."""
    assert cdk.to_number("0") == 0.0


def test_to_number_parses_decimal_percent():
    """'25.10' 같은 퍼센트 값이 그대로 실수여야 합니다."""
    assert cdk.to_number("25.10") == 25.1


def test_to_number_handles_accounting_negative_sign():
    """한국 회계자료의 음수 표기(△)를 음수로 읽어야 합니다."""
    assert cdk.to_number("△1,234") == -1234.0


def test_to_number_rejects_non_numeric_text():
    """숫자로 볼 수 없는 문자열은 지어내지 말고 None 이어야 합니다."""
    assert cdk.to_number("해당사항없음") is None


def test_to_number_rejects_none_and_bool():
    """None 과 bool 은 숫자로 취급하지 않아야 합니다(True==1 사고 방지)."""
    assert cdk.to_number(None) is None
    assert cdk.to_number(True) is None


# =============================================================================
# 2. 라벨/주식종류 분류 (classify_se · classify_stock_kind)
# =============================================================================
def test_classify_se_distinguishes_dps_from_total():
    """'주당 현금배당금'과 '현금배당금총액'이 섞이면 안 됩니다(둘 다 '현금배당금'을 포함)."""
    assert cdk.classify_se("주당 현금배당금(원)") == ("dps_cash", None)
    assert cdk.classify_se("현금배당금총액(백만원)") == ("cash_total", None)


def test_classify_se_reads_consolidated_basis():
    """(연결)/(별도) 접두어에서 산출기준을 읽어내야 합니다."""
    assert cdk.classify_se("(연결)현금배당성향(%)") == ("payout_ratio", "연결")
    assert cdk.classify_se("(별도)현금배당성향(%)") == ("payout_ratio", "별도")


def test_classify_se_returns_none_for_unknown_label():
    """모르는 라벨은 억지로 끼워 맞추지 말고 None 이어야 합니다(리포트로 올라갑니다)."""
    assert cdk.classify_se("우리가 처음 보는 새 항목(개)") == (None, None)


def test_classify_stock_kind_handles_multiple_preferred_classes():
    """'2우선주B' 같은 표기도 우선주로 잡혀야 합니다(정확일치 아닌 포함 검사)."""
    assert cdk.classify_stock_kind("보통주") == "common"
    assert cdk.classify_stock_kind("2우선주B") == "preferred"
    assert cdk.classify_stock_kind("-") == "none"
    assert cdk.classify_stock_kind("전환사채").startswith("other:")


# =============================================================================
# 3. 응답 사용 가능성 판정 (is_usable_alot_response)
# =============================================================================
def test_usable_response_accepts_real_samsung_q1():
    """실제 1분기 응답은 사용 가능으로 판정돼야 합니다."""
    ok, why = cdk.is_usable_alot_response(REAL_SAMSUNG_2026_Q1)
    assert ok is True, why


def test_usable_response_rejects_status_013():
    """status 013(조회결과 없음)은 사용 불가여야 합니다."""
    ok, why = cdk.is_usable_alot_response(REAL_NO_DATA)
    assert ok is False and "013" in why


def test_usable_response_rejects_empty_list_with_status_000():
    """status 000 이어도 list 가 비면 '수집 성공'으로 보면 안 됩니다(빈 껍데기 방지)."""
    ok, why = cdk.is_usable_alot_response({"status": "000", "message": "정상", "list": []})
    assert ok is False and "비어" in why


def test_usable_response_rejects_when_no_dividend_labels():
    """(합성) 배당 항목이 하나도 없는 응답은 규격 변경 신호이므로 사용 불가여야 합니다."""
    payload = {"status": "000", "list": [{"se": "주당액면가액(원)", "thstrm": "100"}]}
    ok, why = cdk.is_usable_alot_response(payload)
    assert ok is False and "배당 관련" in why


# =============================================================================
# 4. 보고서 선택 로직 (select_report_from_probes · plausible_reprt_codes)
# =============================================================================
def test_select_report_prefers_q3_over_half_year():
    """3분기가 있으면 반기·1분기보다 3분기를 골라야 합니다(누적 기간이 더 김)."""
    probes = {"11011": REAL_NO_DATA,
              "11014": REAL_SAMSUNG_2026_Q1,     # 내용은 실데이터, 자리만 3분기로 둔 시나리오
              "11012": REAL_SAMSUNG_2026_H1_PARTIAL,
              "11013": REAL_SAMSUNG_2026_Q1}
    code, why = cdk.select_report_from_probes(probes)
    assert code == "11014", why


def test_select_report_falls_back_to_half_year_when_q3_missing():
    """3분기가 013 이면 반기로 내려가야 합니다 — 실제 2026-08 시점의 삼성전자 상황."""
    probes = {"11011": REAL_NO_DATA, "11014": REAL_NO_DATA,
              "11012": REAL_SAMSUNG_2026_H1_PARTIAL, "11013": REAL_SAMSUNG_2026_Q1}
    code, why = cdk.select_report_from_probes(probes)
    assert code == "11012", why


def test_select_report_falls_back_to_q1_when_only_q1_exists():
    """반기까지 없으면 1분기를 써야 합니다."""
    probes = {"11011": REAL_NO_DATA, "11014": REAL_NO_DATA,
              "11012": REAL_NO_DATA, "11013": REAL_SAMSUNG_2026_Q1}
    code, _ = cdk.select_report_from_probes(probes)
    assert code == "11013"


def test_select_report_returns_none_with_reason_when_nothing_usable():
    """전부 013 이면 아무거나 고르지 말고 None + 사람이 읽을 사유여야 합니다(§0-1)."""
    probes = {c: REAL_NO_DATA for c in cdk.REPRT_CODE_PRIORITY}
    code, why = cdk.select_report_from_probes(probes)
    assert code is None
    assert "사용 가능한 보고서가 없습니다" in why and "013" in why


def test_select_report_owner_order_ignores_annual_report():
    """오너 지시 순서(--owner-order)에서는 사업보고서가 있어도 3분기부터 봐야 합니다."""
    probes = {"11011": REAL_SAMSUNG_2026_Q1, "11014": REAL_SAMSUNG_2026_H1_PARTIAL}
    code, _ = cdk.select_report_from_probes(
        probes, priority=cdk.REPRT_CODE_PRIORITY_OWNER_ORDER)
    assert code == "11014"


def test_select_report_default_priority_prefers_annual_report():
    """기본 순서에서는 사업보고서(연간 확정)가 최우선이어야 합니다."""
    probes = {"11011": REAL_SAMSUNG_2026_Q1, "11014": REAL_SAMSUNG_2026_H1_PARTIAL}
    code, _ = cdk.select_report_from_probes(probes)
    assert code == "11011"


def test_plausible_reprt_codes_drops_reports_not_yet_due():
    """2026-08-23 시점에는 1분기·반기만 제출기한이 지났어야 합니다(12월 결산법인 전제)."""
    from datetime import date
    kept = cdk.plausible_reprt_codes(2026, today=date(2026, 8, 23))
    assert set(kept) == {"11012", "11013"}


def test_plausible_reprt_codes_keeps_everything_for_past_year():
    """이미 끝난 연도(2024)는 네 보고서 모두 기한이 지났어야 합니다."""
    from datetime import date
    kept = cdk.plausible_reprt_codes(2024, today=date(2026, 8, 23))
    assert set(kept) == set(cdk.REPRT_CODE_PRIORITY)


# =============================================================================
# 5. 배당 표 파싱 (parse_alot_rows) — 실데이터 기준
# =============================================================================
def test_parse_extracts_common_and_preferred_dps():
    """보통주/우선주 주당현금배당금이 각각 제자리에 들어가야 합니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="thstrm")
    assert parsed["dps_cash_common"] == 372.0
    assert parsed["dps_cash_preferred"] == 372.0


def test_parse_extracts_yield_separately_for_share_classes():
    """현금배당수익률은 보통주 0.20 / 우선주 0.30 으로 갈라져야 합니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    assert parsed["cash_yield_common"] == 0.20
    assert parsed["cash_yield_preferred"] == 0.30


def test_parse_uses_consolidated_payout_ratio_and_records_basis():
    """배당성향은 연결 기준을 쓰되, 어느 기준을 썼는지 반드시 남겨야 합니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    assert parsed["payout_ratio"] == 5.20
    assert parsed["payout_ratio_basis"] == "연결"


def test_parse_falls_back_to_separate_basis_when_no_consolidated():
    """(합성) 연결이 없고 별도만 있으면 별도를 쓰고 basis 에 '별도'가 찍혀야 합니다."""
    rows = [{"se": "(별도)현금배당성향(%)", "stock_knd": "-", "thstrm": "12.30"},
            {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "500"}]
    parsed = cdk.parse_alot_rows(rows)
    assert parsed["payout_ratio"] == 12.30
    assert parsed["payout_ratio_basis"] == "별도"


def test_parse_returns_none_for_dash_stock_dividend():
    """'주당 주식배당(주)'이 '-' 면 0 이 아니라 None 이어야 합니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    assert parsed["dps_stock_common"] is None
    assert parsed["stock_total_mkrw"] is None


def test_parse_reads_previous_terms_for_cross_check():
    """전기(frmtrm)·전전기(lwfr)도 같은 파서로 뽑혀야 합니다 — 보유 데이터 교차검증용."""
    prev = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="frmtrm")
    prev2 = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="lwfr")
    assert prev["dps_cash_common"] == 1668.0
    assert prev2["dps_cash_common"] == 1446.0


def test_parse_captures_meta_rcept_and_stlm_dt():
    """rcept_no / stlm_dt / corp_cls 가 메타로 잡혀야 공시 링크와 기준일을 만들 수 있습니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    assert parsed["meta"]["rcept_no"] == "20260515002181"
    assert parsed["meta"]["stlm_dt"] == "2026-03-31"
    assert parsed["meta"]["corp_cls"] == "Y"


def test_parse_collects_unknown_se_labels_instead_of_dropping():
    """(합성) 처음 보는 se 라벨은 조용히 버리지 않고 목록에 남아야 합니다(§0-1)."""
    rows = list(REAL_SAMSUNG_2026_Q1["list"]) + [
        {"se": "분기별 특별배당 가산율(%)", "stock_knd": "-", "thstrm": "1.5"}]
    parsed = cdk.parse_alot_rows(rows)
    assert "분기별 특별배당 가산율(%)" in parsed["unknown_se_labels"]


def test_parse_refuses_to_pick_when_preferred_classes_disagree():
    """
    (합성) 우선주가 2종이고 배당금이 서로 다르면 **첫 값을 임의로 고르지 않고** None +
    사유를 남기며, 후보값은 잃지 않아야 합니다(§0-1).
    """
    rows = [
        {"se": "주당 현금배당금(원)", "stock_knd": "1우선주", "thstrm": "1,700"},
        {"se": "주당 현금배당금(원)", "stock_knd": "2우선주B", "thstrm": "1,750"},
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,668"},
    ]
    parsed = cdk.parse_alot_rows(rows)
    assert parsed["dps_cash_common"] == 1668.0
    assert parsed["dps_cash_preferred"] is None
    assert sorted(parsed["dps_cash_preferred_all"]) == [1700.0, 1750.0]
    assert any("특정하지" in n for n in parsed["notes"])


def test_parse_accepts_identical_duplicates_without_complaint():
    """(합성) 같은 값이 두 번 오면(우선주 2종이 동액) 대표값을 그대로 써도 됩니다."""
    rows = [{"se": "주당 현금배당금(원)", "stock_knd": "1우선주", "thstrm": "1,700"},
            {"se": "주당 현금배당금(원)", "stock_knd": "2우선주B", "thstrm": "1,700"}]
    parsed = cdk.parse_alot_rows(rows)
    assert parsed["dps_cash_preferred"] == 1700.0
    assert parsed["notes"] == []


def test_parse_flags_conflicting_metadata_instead_of_guessing():
    """(합성) 한 응답 안에서 stlm_dt 가 갈리면 대표값을 두지 말고 사유를 남겨야 합니다."""
    rows = [{"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "100",
             "stlm_dt": "2026-03-31", "rcept_no": "1"},
            {"se": "현금배당수익률(%)", "stock_knd": "보통주", "thstrm": "1.0",
             "stlm_dt": "2026-06-30", "rcept_no": "1"}]
    parsed = cdk.parse_alot_rows(rows)
    assert parsed["meta"]["stlm_dt"] is None
    assert any("stlm_dt" in n for n in parsed["notes"])


def test_parse_preserves_uncorrected_interim_yield_anomaly():
    """
    반기 원문의 '주당배당금은 누적됐는데 수익률은 그대로'인 이상을 **우리가 고치지 않고**
    그대로 보존하는지 확인합니다. (원자료 보정 = 지어내기이므로 금지)
    """
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_H1_PARTIAL["list"])
    assert parsed["dps_cash_common"] == 746.0
    assert parsed["cash_yield_common"] == 0.20      # 계산하면 0.4x 여야 하지만 원문 그대로


# =============================================================================
# 6. 출력 레코드 조립 (build_dividend_record · summarize_results)
# =============================================================================
def test_build_record_creates_dart_document_link():
    """rcept_no 로 DART 원문 링크가 만들어져야 사용자가 숫자를 대조할 수 있습니다."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    rec = cdk.build_dividend_record("005930", {"corp_code": "00126380"}, "2026", "11013",
                                    REAL_SAMSUNG_2026_Q1, parsed_now=parsed)
    assert rec["dart_url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260515002181"
    assert rec["reprt_name"] == "1분기보고서"
    assert rec["market"] == "유가증권시장(KOSPI)"


def test_build_record_has_no_link_when_rcept_missing():
    """rcept_no 가 없으면 빈 링크를 만들지 말고 None 이어야 합니다."""
    rec = cdk.build_dividend_record("005930", None, "2026", None, None,
                                    status="NO_DATA", status_reason="없음")
    assert rec["dart_url"] is None
    assert rec["status"] == "NO_DATA"


def test_build_record_warns_about_interim_yield():
    """분기·반기 기준 레코드에는 수익률 신뢰도 경고가 반드시 붙어야 합니다."""
    rec = cdk.build_dividend_record("005930", None, "2026", "11012", None)
    assert "누적 정합" in rec["yield_reliability_note"]
    annual = cdk.build_dividend_record("005930", None, "2025", "11011", None)
    assert "사업보고서" in annual["yield_reliability_note"]


def test_summary_counts_every_status_not_just_success():
    """리포트는 성공만 세면 안 됩니다 — NO_DATA/ERROR/UNMAPPED 가 전부 집계돼야 합니다."""
    records = [
        cdk.build_dividend_record("000001", None, "2026", "11012", None, status="OK"),
        cdk.build_dividend_record("000002", None, "2026", None, None, status="NO_DATA"),
        cdk.build_dividend_record("000003", None, "2026", None, None, status="ERROR"),
        cdk.build_dividend_record("000004", None, "2026", None, None, status="UNMAPPED"),
    ]
    summary = cdk.summarize_results(records, unmapped=[{"stock_code": "000004"}])
    assert summary["by_status"] == {"OK": 1, "NO_DATA": 1, "ERROR": 1, "UNMAPPED": 1}
    assert summary["unmapped_stock_codes"] == 1
    assert any("013" in s for s in summary["known_limitations"])


# =============================================================================
# 7. corp_code 매핑 (corp_code_mapper) — ZIP/XML 을 메모리에서 만들어 검증
# =============================================================================
def _make_corpcode_zip(entries_xml, inner_name="CORPCODE.xml"):
    """(합성) DART 가 준다고 문서화된 형태의 ZIP 을 메모리에 만듭니다."""
    xml = ("<?xml version='1.0' encoding='UTF-8'?><result>" + entries_xml + "</result>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner_name, xml.encode("utf-8"))
    return buf.getvalue()


SAMPLE_XML = """
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
 <corp_eng_name>SAMSUNG ELECTRONICS CO,.LTD</corp_eng_name>
 <stock_code>005930</stock_code><modify_date>20260401</modify_date></list>
<list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
 <corp_eng_name>SK hynix Inc.</corp_eng_name>
 <stock_code>000660</stock_code><modify_date>20260320</modify_date></list>
<list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>
 <corp_eng_name>UNLISTED CO</corp_eng_name>
 <stock_code> </stock_code><modify_date>20250101</modify_date></list>
"""


def test_parse_corpcode_zip_reads_entries_by_tag_name():
    """태그 이름 기반 파싱으로 corp_code/stock_code 가 정확히 나와야 합니다."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML))
    by_code = {e["corp_code"]: e for e in entries}
    assert by_code["00126380"]["stock_code"] == "005930"
    assert by_code["00126380"]["corp_eng_name"].startswith("SAMSUNG")
    assert by_code["00999999"]["stock_code"] is None      # 비상장 = 종목코드 없음


def test_parse_corpcode_zip_does_not_hardcode_inner_filename():
    """안쪽 XML 파일 이름이 달라도(실물 미확인) 파싱돼야 합니다."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML, inner_name="corp_list.xml"))
    assert len(entries) == 3


def test_parse_corpcode_zip_raises_on_multiple_xml_members():
    """.xml 이 둘 이상이면 임의로 고르지 말고 실패해야 합니다(§0-1)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.xml", "<result></result>")
        z.writestr("b.xml", "<result></result>")
    with pytest.raises(ccm.DartCorpCodeError, match="하나로 특정할 수 없습니다"):
        ccm.parse_corpcode_zip(buf.getvalue())


def test_parse_corpcode_zip_surfaces_dart_error_xml():
    """ZIP 이 아니라 오류 XML 이 오면 status/message 를 사람이 읽게 드러내야 합니다."""
    body = "<result><status>010</status><message>등록되지 않은 키입니다.</message></result>"
    with pytest.raises(ccm.DartCorpCodeError, match="010"):
        ccm.parse_corpcode_zip(body.encode("utf-8"))


def test_parse_corpcode_zip_raises_on_empty_body():
    """빈 응답을 빈 목록으로 넘기면 'DART 에 회사가 없다'가 되어버립니다 — 예외여야 합니다."""
    with pytest.raises(ccm.DartCorpCodeError):
        ccm.parse_corpcode_zip(b"")


def test_normalize_stock_code_restores_lost_leading_zeros():
    """엑셀을 거쳐 5930 이 된 종목코드를 005930 으로 복원해야 합니다."""
    assert ccm.normalize_stock_code(5930) == "005930"
    assert ccm.normalize_stock_code("005930") == "005930"


def test_normalize_stock_code_rejects_malformed_input():
    """7자리 이상이나 문자 섞인 값은 잘라내지 말고 None 이어야 합니다."""
    assert ccm.normalize_stock_code("1234567") is None
    assert ccm.normalize_stock_code("A005930") is None
    assert ccm.normalize_stock_code("") is None


def test_build_index_records_duplicate_stock_codes_instead_of_silently_picking():
    """(합성) 한 종목코드에 corp_code 가 둘이면 최신 modify_date 를 쓰되 기록이 남아야 합니다."""
    dup_xml = """
    <list><corp_code>00000001</corp_code><corp_name>옛회사</corp_name>
     <stock_code>123456</stock_code><modify_date>20200101</modify_date></list>
    <list><corp_code>00000002</corp_code><corp_name>새회사</corp_name>
     <stock_code>123456</stock_code><modify_date>20260101</modify_date></list>
    """
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(dup_xml))
    index, stats = ccm.build_stock_code_index(entries)
    assert index["123456"]["corp_code"] == "00000002"
    assert len(stats["duplicates"]) == 1
    assert stats["duplicates"][0]["dropped"][0]["corp_code"] == "00000001"


def test_build_index_counts_unlisted_entries():
    """비상장 항목은 색인에서 빠지되 개수는 세어져야 합니다."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML))
    index, stats = ccm.build_stock_code_index(entries)
    assert set(index) == {"005930", "000660"}
    assert stats["unlisted_entries"] == 1
    assert stats["listed_entries"] == 2


def test_map_stock_codes_returns_unmapped_with_reason():
    """매핑 실패 종목은 조용히 사라지지 않고 사유와 함께 반환돼야 합니다(§0-1 핵심)."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML))
    index, _ = ccm.build_stock_code_index(entries)
    mapping, unmapped = ccm.map_stock_codes(["005930", "000660", "999999", "bad!"], index)
    assert set(mapping) == {"005930", "000660"}
    reasons = {u["stock_code"]: u["reason"] for u in unmapped}
    assert "999999" in reasons and "corpCode.xml" in reasons["999999"]
    assert None in reasons and "정규화" in reasons[None]


def test_map_stock_codes_normalizes_before_lookup():
    """정수로 뭉개진 종목코드도 매핑돼야 합니다."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML))
    index, _ = ccm.build_stock_code_index(entries)
    mapping, unmapped = ccm.map_stock_codes([5930], index)
    assert mapping["005930"]["corp_code"] == "00126380"
    assert unmapped == []


# =============================================================================
# 8. 유니버스 입력 (load_universe) — 경로 하드코딩 없이 여러 형태 수용
# =============================================================================
def test_load_universe_accepts_plain_list(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    assert cdk.load_universe(str(path)) == ["005930", "000660"]


def test_load_universe_accepts_list_of_dicts(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps([{"종목코드": "005930", "이름": "삼성전자"}]), encoding="utf-8")
    assert cdk.load_universe(str(path)) == ["005930"]


def test_load_universe_accepts_market_keyed_dict(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps({"KOSPI": ["005930"], "KOSDAQ": ["000660"]}), encoding="utf-8")
    assert sorted(cdk.load_universe(str(path))) == ["000660", "005930"]


def test_load_universe_deduplicates_preserving_order(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps(["005930", "000660", "005930"]), encoding="utf-8")
    assert cdk.load_universe(str(path)) == ["005930", "000660"]


def test_load_universe_raises_on_unknown_shape(tmp_path):
    """형태를 모르면 추측하지 말고 예외여야 합니다(§0-1)."""
    path = tmp_path / "u.json"
    path.write_text(json.dumps([{"name": "삼성전자"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="종목코드 키를 찾지 못했습니다"):
        cdk.load_universe(str(path))


# =============================================================================
# 9. 배선 검증 — 네트워크 함수만 가짜로 바꿔 end-to-end (소켓은 열지 않습니다)
# =============================================================================
def test_collect_one_stops_at_first_usable_report(monkeypatch):
    """
    3분기가 013 이면 반기로 내려가고, 반기가 나오면 **1분기는 부르지 않아야** 합니다
    (§0-3-2: 필요 없는 요청을 안 보내는 것도 매너).
    """
    calls = []

    def fake_get(url, params, timeout, session, request_counter=None):
        calls.append(params["reprt_code"])
        if params["reprt_code"] in ("11011", "11014"):
            return 200, REAL_NO_DATA
        if params["reprt_code"] == "11012":
            return 200, REAL_SAMSUNG_2026_H1_PARTIAL
        raise AssertionError("1분기를 부르면 안 됩니다")

    monkeypatch.setattr(cdk, "_http_get_json", fake_get)
    rec, probes = cdk.collect_one("005930", {"corp_code": "00126380"}, "2026", "KEY",
                                  sleep_fn=lambda: None)
    assert calls == ["11011", "11014", "11012"]
    assert rec["status"] == "OK"
    assert rec["reprt_code"] == "11012"
    assert rec["dps_cash_common"] == 746.0
    assert len(probes) == 3


def test_collect_one_records_no_data_when_all_reports_missing(monkeypatch):
    """전부 013 이면 조용히 스킵하지 말고 NO_DATA 레코드를 남겨야 합니다."""
    monkeypatch.setattr(cdk, "_http_get_json", lambda *a, **k: (200, REAL_NO_DATA))
    rec, _ = cdk.collect_one("123456", {"corp_code": "00000001"}, "2026", "KEY",
                             sleep_fn=lambda: None)
    assert rec["status"] == "NO_DATA"
    assert "013" in rec["status_reason"]
    assert "corp_code 오류" in rec["status_reason"]      # 구분 불가 한계를 명시


def test_collect_one_marks_error_not_no_data_on_transport_failure(monkeypatch):
    """
    진짜 에러(HTTP 400 등)를 '데이터 없음'으로 뭉개면 안 됩니다 — 무배당으로 오해됩니다.
    """
    monkeypatch.setattr(cdk, "_http_get_json", lambda *a, **k: (400, None))
    rec, _ = cdk.collect_one("123456", {"corp_code": "00000001"}, "2026", "KEY",
                             sleep_fn=lambda: None)
    assert rec["status"] == "ERROR"
    assert "400" in rec["status_reason"]


def test_fetch_raises_fatal_on_bad_key(monkeypatch):
    """status 010(키 오류)은 종목 실패가 아니라 실행 전체 중단이어야 합니다."""
    monkeypatch.setattr(cdk, "_http_get_json", lambda *a, **k: (200, REAL_BAD_KEY))
    with pytest.raises(cdk.DartFatalError, match="010"):
        cdk.fetch_alot_matter("00126380", "2026", "11013", "BAD")


def test_fetch_raises_fatal_on_rate_limit_status(monkeypatch):
    """status 020(요청 제한 초과)에서 계속 두드리면 §0-3-2 위반 — 즉시 중단이어야 합니다."""
    monkeypatch.setattr(cdk, "_http_get_json",
                        lambda *a, **k: (200, {"status": "020", "message": "요청 제한 초과"}))
    with pytest.raises(cdk.DartFatalError, match="020"):
        cdk.fetch_alot_matter("00126380", "2026", "11013", "KEY")


def test_fetch_raises_fatal_on_http_429(monkeypatch):
    """HTTP 429 차단 시에도 재시도하지 않고 중단해야 합니다."""
    monkeypatch.setattr(cdk, "_http_get_json", lambda *a, **k: (429, None))
    with pytest.raises(cdk.DartFatalError, match="429"):
        cdk.fetch_alot_matter("00126380", "2026", "11013", "KEY")


def test_fetch_retries_once_on_server_error_then_fails(monkeypatch):
    """5xx 는 1회만 재시도하고 그 뒤엔 포기해야 합니다(무한 재시도 금지)."""
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return 503, None

    monkeypatch.setattr(cdk, "_http_get_json", fake_get)
    monkeypatch.setattr(cdk.time, "sleep", lambda *_: None)
    with pytest.raises(cdk.DartApiError):
        cdk.fetch_alot_matter("00126380", "2026", "11013", "KEY")
    assert calls["n"] == cdk.DART_NETWORK_RETRY + 1


def test_fetch_never_leaks_api_key_in_error_message(monkeypatch):
    """예외 메시지에 인증키가 절대 실리면 안 됩니다."""
    secret = "SECRET-KEY-DO-NOT-LEAK"
    monkeypatch.setattr(cdk, "_http_get_json", lambda *a, **k: (200, REAL_BAD_KEY))
    with pytest.raises(cdk.DartFatalError) as excinfo:
        cdk.fetch_alot_matter("00126380", "2026", "11013", secret)
    assert secret not in str(excinfo.value)


def test_raw_response_is_written_separately_from_processed(tmp_path, monkeypatch):
    """§0-3-3: 원본 응답이 손대지 않은 상태로 별도 파일에 남아야 합니다."""
    monkeypatch.setattr(cdk, "_http_get_json",
                        lambda url, params, timeout, session, request_counter=None:
                        (200, REAL_SAMSUNG_2026_Q1 if params["reprt_code"] == "11013"
                         else REAL_NO_DATA))
    raw_path = tmp_path / "raw.jsonl"
    rec, _ = cdk.collect_one("005930", {"corp_code": "00126380"}, "2026", "KEY",
                             raw_path=str(raw_path), sleep_fn=lambda: None)
    lines = [json.loads(l) for l in raw_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4                                  # 우선순위 4개 전부 기록
    saved = [l for l in lines if l["reprt_code"] == "11013"][0]
    assert saved["response"] == REAL_SAMSUNG_2026_Q1        # 원본 그대로
    assert rec["dps_cash_common"] == 372.0


# =============================================================================
# 10. 전체 실행 오케스트레이션 (run_collection) — 여전히 소켓은 열지 않습니다
# =============================================================================
def _fake_alot_matter_response(url, params, timeout, session, request_counter=None):
    """`faked_network`/`faked_network_widened` 공용 alotMatter 가짜 응답.

    🔴 M15(2026-08-29) — 이 가짜가 `request_counter`를 그냥 받기만 하고 안 세면(예:
    `lambda ...: None`처럼 무시), `run_collection()`이 실제로 몇 번 요청했는지 세는
    회귀 테스트(`requests_used` 검증)들이 전부 0을 보게 됩니다 — `_http_get_json()`이
    통째로 갈아끼워졌으니까요. 진짜 `_http_get_json()`과 같은 자리에서 같은 방식으로
    셉니다(이 가짜는 재시도를 흉내 내지 않으므로 호출 횟수 = 실제 요청 수).
    """
    if request_counter is not None:
        request_counter["count"] += 1
    return (200, REAL_SAMSUNG_2026_Q1 if params["reprt_code"] == "11013" else REAL_NO_DATA)


@pytest.fixture
def faked_network(monkeypatch):
    """corpCode ZIP 과 alotMatter 응답을 전부 가짜로 갈아끼웁니다(딜레이도 0으로)."""
    zip_bytes = _make_corpcode_zip(SAMPLE_XML)
    monkeypatch.setattr(ccm, "_http_get_bytes",
                        lambda url, params, timeout, session: (200, zip_bytes))
    monkeypatch.setattr(cdk, "_http_get_json", _fake_alot_matter_response)
    monkeypatch.setattr(cdk, "polite_sleep", lambda rng=None: 0.0)
    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")


def test_run_collection_separates_raw_and_processed_outputs(tmp_path, faked_network):
    """§0-3-3: 가공본 JSON 과 raw JSONL 이 서로 다른 파일로 남아야 합니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=lambda *a: None)
    processed = json.loads((tmp_path / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))
    assert processed["summary"]["by_status"] == {"OK": 2}
    assert (tmp_path / "dividend_kr_2026_raw.jsonl").exists()
    assert summary["requests_used"] == 8            # 2종목 × 우선순위 4단계


def test_run_collection_keeps_unmapped_stocks_as_records(tmp_path, faked_network):
    """매핑 안 된 종목이 결과에서 사라지면 안 됩니다 — UNMAPPED 레코드로 남아야 합니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "999999"]), encoding="utf-8")
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=lambda *a: None)
    assert summary["by_status"] == {"UNMAPPED": 1, "OK": 1}
    assert summary["unmapped_stock_codes"] == 1
    assert {r["stock_code"] for r in records} == {"005930", "999999"}


def test_run_collection_stops_on_request_budget_and_can_resume(tmp_path, faked_network):
    """
    요청 예산을 넘기면 조용히 잘리는 게 아니라 completed=False + 사유가 남고, 체크포인트가
    저장돼 다음 실행이 이어받아야 합니다.
    """
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    universe = cdk.load_universe(str(uni))

    _, first = cdk.run_collection(universe, "2026", str(tmp_path),
                                  max_requests=4, log=lambda *a: None)
    assert first["completed"] is False
    assert "요청 예산" in first["stopped_reason"]
    assert (tmp_path / "dividend_kr_2026_checkpoint.json").exists()

    _, second = cdk.run_collection(universe, "2026", str(tmp_path),
                                   max_requests=100, log=lambda *a: None)
    assert second["completed"] is True
    assert second["by_status"] == {"OK": 2}
    # 이어받았으므로 두 번째 실행의 추가 요청은 4건뿐이어야 합니다(중복 수집 금지).
    assert second["requests_used"] == 8


def test_run_collection_refuses_to_start_without_api_key(tmp_path, monkeypatch):
    """키가 없으면 조용히 빈 결과를 만들지 말고 명확히 중단해야 합니다."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(cdk.DartFatalError, match="DART_API_KEY"):
        cdk.run_collection(["005930"], "2026", str(tmp_path), log=lambda *a: None)


def test_run_collection_records_that_a_limit_was_applied(tmp_path, faked_network):
    """--limit 로 일부만 돌렸다는 사실이 리포트에 남아야 전수 수집으로 오해되지 않습니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    _, summary = cdk.run_collection(cdk.load_universe(str(uni)), "2026", str(tmp_path),
                                    limit=1, log=lambda *a: None)
    assert summary["limit_applied"] == 1
    assert summary["universe_size_input"] == 2      # 파일에는 2종목이 있었고
    assert summary["universe_size"] == 1            # 실제로 돈 것은 1종목


# =============================================================================
# 10. 단위 토큰 검증 (§2-4 "단위 변환 임의 적용 금지")
#
# 배경: `classify_se` 는 키워드만 보고 지표를 정하는데 출력 필드명(`cash_total_mkrw` 등)은
#       단위를 이미 확정합니다. 라벨의 단위 토큰을 확인하지 않으면 회사가 "천원" 으로 적어
#       보냈을 때 1000배 틀린 값이 조용히 정상값으로 저장됩니다.
# 이 절의 테스트는 **감지**만 검증합니다. 우리는 값을 변환·보정하지 않습니다(§0-1).
# =============================================================================
REAL_RAW_JSONL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "dividend_kr_2026_raw.jsonl")


def test_extract_unit_token_reads_trailing_parenthesis():
    """단위는 라벨 **맨 끝** 괄호에서만 뽑습니다 (실데이터에서 관측된 형태 전부)."""
    assert cdk.extract_unit_token("현금배당금총액(백만원)") == "백만원"
    assert cdk.extract_unit_token("주식배당금총액(백만원)") == "백만원"
    assert cdk.extract_unit_token("주당 현금배당금(원)") == "원"
    assert cdk.extract_unit_token("주당 주식배당(주)") == "주"
    assert cdk.extract_unit_token("주당액면가액(원)") == "원"
    assert cdk.extract_unit_token("현금배당수익률(%)") == "%"


def test_extract_unit_token_ignores_leading_basis_parenthesis():
    """
    실제 라벨은 "(연결)당기순이익(백만원)" 처럼 기준과 단위가 **둘 다** 괄호입니다.
    앞의 "(연결)"/"(별도)" 를 단위로 잘못 읽으면 안 됩니다.
    """
    assert cdk.extract_unit_token("(연결)당기순이익(백만원)") == "백만원"
    assert cdk.extract_unit_token("(별도)당기순이익(백만원)") == "백만원"
    assert cdk.extract_unit_token("(연결)주당순이익(원)") == "원"
    assert cdk.extract_unit_token("(연결)현금배당성향(%)") == "%"


def test_extract_unit_token_returns_none_when_not_determinable():
    """(합성) 단위를 못 뽑으면 지어내지 말고 None(=확인 불가) 이어야 합니다."""
    assert cdk.extract_unit_token("(연결)당기순이익") is None      # 단위 표기 자체가 없음
    assert cdk.extract_unit_token("현금배당금총액 백만원") is None  # 괄호 형식이 아님
    assert cdk.extract_unit_token("현금배당금총액(백만원) 주석") is None  # 끝이 괄호가 아님
    assert cdk.extract_unit_token("당기순이익(연결)") is None      # 끝 괄호가 기준 표기뿐
    assert cdk.extract_unit_token("당기순이익()") is None
    assert cdk.extract_unit_token(None) is None


def test_expected_unit_table_matches_units_observed_in_real_corpus():
    """
    기대 단위 표는 지어낸 게 아니라 실제 원본에서 관측된 토큰이어야 합니다.
    (표를 손댈 때 실데이터 근거 없이 바꾸는 것을 막는 잠금장치)
    """
    assert cdk.EXPECTED_UNIT_TOKENS == {
        "dps_cash": "원", "dps_stock": "주",
        "cash_total": "백만원", "stock_total": "백만원",
        "eps": "원", "net_income": "백만원", "par_value": "원",
    }


def test_parse_flags_unit_mismatch_instead_of_silently_converting():
    """
    (합성) "현금배당금총액(천원)" 처럼 기대와 다른 단위가 오면 조용히 넘기지 말고
    `unit_mismatch_notes` 에 남겨야 합니다. **값은 변환하지 않고 원문 그대로** 둡니다.
    """
    rows = [{"se": "현금배당금총액(천원)", "stock_knd": "-", "thstrm": "2,453,316"},
            {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "500"}]
    parsed = cdk.parse_alot_rows(rows)

    assert len(parsed["unit_mismatch_notes"]) == 1
    note = parsed["unit_mismatch_notes"][0]
    assert "천원" in note and "백만원" in note and "현금배당금총액(천원)" in note

    # 값은 우리가 손대지 않습니다(÷1000 같은 자동 보정 금지 — §0-1).
    assert parsed["cash_total_mkrw"] == 2453316.0
    # 단위가 맞는 다른 지표는 영향을 받지 않습니다.
    assert parsed["dps_cash_common"] == 500.0
    # 기존 필드의 의미를 바꾸지 않습니다 — 단위 문제는 notes 가 아닌 전용 리스트로만.
    assert parsed["notes"] == []


def test_parse_flags_undeterminable_unit_as_unverified():
    """(합성) 단위를 뽑을 수 없는 라벨도 '확인 불가'로 남겨야 합니다(조용한 통과 금지 §0-1)."""
    rows = [{"se": "주당 현금배당금", "stock_knd": "보통주", "thstrm": "500"},
            {"se": "현금배당금총액 백만원", "stock_knd": "-", "thstrm": "1,000"}]
    parsed = cdk.parse_alot_rows(rows)

    assert len(parsed["unit_mismatch_notes"]) == 2
    assert all("확인 불가" in n for n in parsed["unit_mismatch_notes"])
    assert any("주당 현금배당금" in n for n in parsed["unit_mismatch_notes"])
    # 분류 자체는 성공했으므로 unknown_se_labels 로 새지 않아야 합니다.
    assert parsed["unknown_se_labels"] == []
    assert parsed["dps_cash_common"] == 500.0


def test_parse_reports_each_mismatched_label_once_even_across_stock_kinds():
    """(합성) 같은 라벨이 보통주/우선주로 두 줄 와도 사유는 한 번만 적습니다(가독성)."""
    rows = [{"se": "주당 현금배당금(천원)", "stock_knd": "보통주", "thstrm": "1"},
            {"se": "주당 현금배당금(천원)", "stock_knd": "우선주", "thstrm": "2"}]
    parsed = cdk.parse_alot_rows(rows)
    assert len(parsed["unit_mismatch_notes"]) == 1


def test_parse_accepts_real_samsung_response_with_no_unit_complaints():
    """실제 DART 응답(삼성전자 2026 1분기)은 단위 검증을 전부 통과해야 합니다."""
    for period in ("thstrm", "frmtrm", "lwfr"):
        parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period=period)
        assert parsed["unit_mismatch_notes"] == []
    # 같은 응답에서 기준(연결)과 단위(백만원)가 각각 옳게 뽑혔는지도 함께 확인합니다.
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    assert parsed["net_income_mkrw_basis"] == "연결"
    assert parsed["net_income_mkrw"] == 47101190.0
    assert parsed["eps_basis"] == "연결"


def test_build_record_carries_unit_mismatch_notes_into_output():
    """(합성) 단위 경고는 최종 레코드에도 실려야 파일만 보고도 알 수 있습니다."""
    rows = [{"se": "현금배당금총액(천원)", "stock_knd": "-", "thstrm": "1,000",
             "rcept_no": "20260515002181"}]
    parsed = cdk.parse_alot_rows(rows)
    rec = cdk.build_dividend_record("005930", {"corp_code": "00126380"}, "2026", "11013",
                                    {"status": "000", "list": rows}, parsed_now=parsed)
    assert rec["unit_mismatch_notes"] == parsed["unit_mismatch_notes"]
    assert len(rec["unit_mismatch_notes"]) == 1
    # 기존 필드는 그대로 있어야 합니다(§0-3-10 최소 변경).
    assert rec["parse_notes"] == [] and rec["unknown_se_labels"] == []


def test_build_record_has_empty_unit_notes_for_clean_response():
    """정상 응답에서는 빈 리스트여야 합니다(필드가 항상 존재 = 화면이 분기하기 쉬움)."""
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    rec = cdk.build_dividend_record("005930", {"corp_code": "00126380"}, "2026", "11013",
                                    REAL_SAMSUNG_2026_Q1, parsed_now=parsed)
    assert rec["unit_mismatch_notes"] == []


def test_real_raw_corpus_has_no_unit_mismatch_anywhere():
    """
    **실제 수집 원본 전수 회귀 테스트** (네트워크 불필요 — 저장된 raw jsonl 만 읽습니다).

    2026-08-24 기준 data/dividend_kr_2026_raw.jsonl 5,484응답(배당표 34,903행)을 전부
    돌려 단위 불일치가 **0건**임을 확인했습니다. 이 값이 0이 아니게 되면 둘 중 하나입니다:
      ① DART 가 실제로 다른 단위 라벨을 쓰기 시작했다 → 사람이 확인해야 합니다.
      ② 우리 단위 검증 로직이 정상 라벨을 오탐하고 있다 → 로직을 고쳐야 합니다.
    어느 쪽이든 조용히 지나가면 안 되므로 여기서 잡습니다.
    """
    if not os.path.exists(REAL_RAW_JSONL):
        pytest.skip(f"실제 수집 원본이 없습니다: {REAL_RAW_JSONL} (수집 후에만 검증 가능)")

    lines = mismatched = parsed_responses = rows_seen = 0
    offenders = []
    with open(REAL_RAW_JSONL, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            lines += 1
            entry = json.loads(line)
            rows = (entry.get("response") or {}).get("list")
            if not isinstance(rows, list):
                continue
            parsed_responses += 1
            rows_seen += len(rows)
            parsed = cdk.parse_alot_rows(rows)
            if parsed["unit_mismatch_notes"]:
                mismatched += 1
                if len(offenders) < 5:
                    offenders.append((entry.get("stock_code"),
                                      parsed["unit_mismatch_notes"][0]))

    # 파일이 비어 있는데 "0건 통과"로 착각하지 않도록 규모부터 확인합니다(§0-1).
    assert lines >= 5000, f"원본이 예상보다 작습니다({lines}줄) — 잘린 파일일 수 있습니다."
    assert parsed_responses >= 2500 and rows_seen >= 30000
    assert mismatched == 0, f"단위 불일치 {mismatched}건 발생: {offenders}"


def test_real_raw_corpus_classifies_every_se_label():
    """
    같은 전수 원본에서 `unknown_se_labels` 도 0건임을 함께 고정합니다.
    (단위 검증을 넣다가 분류 로직을 건드려 라벨이 새는 회귀를 잡기 위한 짝 테스트)
    """
    if not os.path.exists(REAL_RAW_JSONL):
        pytest.skip(f"실제 수집 원본이 없습니다: {REAL_RAW_JSONL} (수집 후에만 검증 가능)")

    unknown = set()
    with open(REAL_RAW_JSONL, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows = (json.loads(line).get("response") or {}).get("list")
            if isinstance(rows, list):
                unknown.update(cdk.parse_alot_rows(rows)["unknown_se_labels"])
    assert unknown == set(), f"분류하지 못한 se 라벨: {sorted(unknown)}"


# =============================================================================
# 11. 체크포인트 run_key — "다음 날 이어하기"가 되어야 합니다 (§0-3-2)
#
# 배경(고쳐진 버그): run_key 에 `_now_kst().strftime('%Y-%m-%d')` 이 들어 있어서,
#   점심시간·야간 중단·GitHub Actions 타임아웃 등으로 **날이 바뀐 뒤 재개**하면 키가 달라져
#   체크포인트 전체가 버려지고 수천 건을 DART 에 다시 요청했습니다. 이 절은 그 회귀를 막습니다.
#   날짜를 뺀 대신 `saved_at_kst` 기반 신선도 검사(max_age_days)가 '아주 오래된 잔재'를 거릅니다.
# =============================================================================
def _write_checkpoint_file(path, run_key, saved_at, done_codes=("005930",),
                           request_count=4):
    """테스트용 체크포인트 파일 직접 작성(저장 시각을 마음대로 정하기 위함)."""
    payload = {"run_key": run_key,
               "records": [{"stock_code": c, "status": "OK"} for c in done_codes],
               "done_codes": list(done_codes),
               "request_count": request_count}
    if saved_at is not _NO_FIELD:
        payload["saved_at_kst"] = saved_at
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


_NO_FIELD = object()      # "그 키 자체가 없음"을 None 과 구분하기 위한 표식


def _iso_days_ago(days, hours=0):
    from datetime import timedelta
    return (ccm._now_kst() - timedelta(days=days, hours=hours)).isoformat()


def test_build_run_key_is_identical_on_different_days(monkeypatch):
    """
    ⭐ 이 파일의 핵심 회귀 테스트.
    같은 (사업연도, 유니버스 크기, 보고서 우선순위)면 **실행 날짜가 달라도 run_key 는 같아야**
    합니다. 달라지면 다음 날 재개가 전량 재수집이 됩니다(§0-3-2 위반).
    """
    from datetime import datetime

    def _fixed(dt):
        return lambda: dt

    monkeypatch.setattr(cdk, "_now_kst", _fixed(datetime(2026, 8, 24, 23, 50, tzinfo=ccm.KST)))
    day1 = cdk.build_run_key("2026", 2734, cdk.REPRT_CODE_PRIORITY)

    monkeypatch.setattr(cdk, "_now_kst", _fixed(datetime(2026, 8, 25, 0, 10, tzinfo=ccm.KST)))
    day2 = cdk.build_run_key("2026", 2734, cdk.REPRT_CODE_PRIORITY)

    monkeypatch.setattr(cdk, "_now_kst", _fixed(datetime(2026, 12, 31, 9, 0, tzinfo=ccm.KST)))
    much_later = cdk.build_run_key("2026", 2734, cdk.REPRT_CODE_PRIORITY)

    assert day1 == day2 == much_later
    # 날짜 조각이 키에 남아 있지 않은지 문자열로도 못 박습니다.
    assert "2026-08-24" not in day1 and "2026-08-25" not in day1
    assert day1 == "2026|2734|11011,11014,11012,11013"


def test_build_run_key_still_separates_genuinely_different_runs():
    """날짜를 뺐다고 해서 '다른 실행'까지 같아지면 안 됩니다(섞이면 §0-1 위반)."""
    base = cdk.build_run_key("2026", 2734, cdk.REPRT_CODE_PRIORITY)
    assert base != cdk.build_run_key("2025", 2734, cdk.REPRT_CODE_PRIORITY)       # 연도 다름
    assert base != cdk.build_run_key("2026", 100, cdk.REPRT_CODE_PRIORITY)        # 크기 다름
    assert base != cdk.build_run_key("2026", 2734,
                                     cdk.REPRT_CODE_PRIORITY_OWNER_ORDER)         # 우선순위 다름


def test_load_checkpoint_resumes_recent_checkpoint(tmp_path):
    """(회귀) 조건이 같고 최근에 저장된 체크포인트는 지금까지처럼 그대로 이어받아야 합니다."""
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    path = _write_checkpoint_file(tmp_path / "ckpt.json", run_key, _iso_days_ago(0, hours=1))

    ckpt = cdk.load_checkpoint(str(path), run_key)
    assert ckpt["done_codes"] == ["005930"]
    assert ckpt["request_count"] == 4
    assert len(ckpt["records"]) == 1


def test_load_checkpoint_resumes_after_a_multi_day_pause(tmp_path):
    """
    ⭐ 버그의 실제 시나리오: 어제(또는 사흘 전) 저장된 체크포인트를 오늘 이어받을 수 있어야
    합니다. 기본 신선도 기준(14일) 안이므로 버려지면 안 됩니다.
    """
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    for days in (1, 3, 13):
        path = _write_checkpoint_file(tmp_path / f"ckpt_{days}.json", run_key,
                                      _iso_days_ago(days))
        ckpt = cdk.load_checkpoint(str(path), run_key)
        assert ckpt["done_codes"] == ["005930"], f"{days}일 전 체크포인트가 버려졌습니다"


def test_load_checkpoint_discards_stale_checkpoint(tmp_path, capsys):
    """30일 전 체크포인트는 조건이 같아도 '너무 오래됨'으로 버리고 사유를 출력해야 합니다."""
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    path = _write_checkpoint_file(tmp_path / "ckpt.json", run_key, _iso_days_ago(30))

    ckpt = cdk.load_checkpoint(str(path), run_key)
    assert ckpt == {"run_key": run_key, "records": [], "done_codes": [], "request_count": 0}
    out = capsys.readouterr().out
    assert "오래" in out and "14" in out          # 왜 버렸는지 사람이 읽을 수 있어야 합니다


def test_load_checkpoint_max_age_is_configurable(tmp_path):
    """기준일수는 인자로 조절 가능해야 하고, None 이면 신선도 검사를 하지 않습니다."""
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    path = _write_checkpoint_file(tmp_path / "ckpt.json", run_key, _iso_days_ago(30))

    assert cdk.load_checkpoint(str(path), run_key, max_age_days=60)["done_codes"] == ["005930"]
    assert cdk.load_checkpoint(str(path), run_key, max_age_days=None)["done_codes"] == ["005930"]
    assert cdk.load_checkpoint(str(path), run_key, max_age_days=1)["done_codes"] == []


def test_load_checkpoint_discards_when_saved_at_is_missing(tmp_path, capsys):
    """
    이 수정 이전에 만들어진 체크포인트에는 검증이 적용된 적이 없습니다.
    `saved_at_kst` 가 아예 없으면 **나이를 확인할 수 없으므로** 크래시 없이 버려야 합니다
    (§0-1: 확인 못 한 것을 '괜찮다'고 넘겨짚지 않습니다).
    """
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    path = _write_checkpoint_file(tmp_path / "ckpt.json", run_key, _NO_FIELD)

    ckpt = cdk.load_checkpoint(str(path), run_key)
    assert ckpt["done_codes"] == [] and ckpt["records"] == []
    assert "확인할 수 없" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["", "어제", "2026-13-45T99:99", 12345, None, [], {"a": 1}])
def test_load_checkpoint_survives_malformed_saved_at(tmp_path, bad):
    """저장 시각이 망가져 있어도 예외로 죽지 않고 '버리고 새로 시작'이어야 합니다."""
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    path = _write_checkpoint_file(tmp_path / "ckpt.json", run_key, bad)
    ckpt = cdk.load_checkpoint(str(path), run_key)
    assert ckpt == {"run_key": run_key, "records": [], "done_codes": [], "request_count": 0}


def test_load_checkpoint_still_rejects_different_run_key(tmp_path, capsys):
    """(회귀) 실행조건이 다른 체크포인트를 재사용하지 않는 기존 보호장치는 그대로여야 합니다."""
    path = _write_checkpoint_file(tmp_path / "ckpt.json",
                                  cdk.build_run_key("2025", 2, cdk.REPRT_CODE_PRIORITY),
                                  _iso_days_ago(0))
    wanted = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    ckpt = cdk.load_checkpoint(str(path), wanted)
    assert ckpt["done_codes"] == []
    assert "다른 실행조건" in capsys.readouterr().out


def test_load_checkpoint_returns_empty_when_file_absent(tmp_path):
    """파일이 없으면 (예외가 아니라) 빈 체크포인트 형태여야 합니다."""
    run_key = cdk.build_run_key("2026", 2, cdk.REPRT_CODE_PRIORITY)
    ckpt = cdk.load_checkpoint(str(tmp_path / "nope.json"), run_key)
    assert ckpt == {"run_key": run_key, "records": [], "done_codes": [], "request_count": 0}


def _counting_alot_calls(monkeypatch):
    """
    faked_network 위에 얹어 **실제로 나간 alotMatter 요청 수**를 셉니다.
    (`requests_used` 는 체크포인트에서 이어받은 누적값이라, 재수집 여부를 구분하지 못합니다.
     "DART 를 몇 번 더 두드렸는가"가 이 버그의 본질이므로 그 숫자를 직접 셉니다.)
    """
    calls = {"n": 0}
    inner = cdk._http_get_json

    def counting(url, params, timeout, session, request_counter=None):
        calls["n"] += 1
        return inner(url, params, timeout, session, request_counter=request_counter)

    monkeypatch.setattr(cdk, "_http_get_json", counting)
    return calls


def test_run_collection_resumes_when_the_date_changes_midrun(tmp_path, faked_network,
                                                             monkeypatch):
    """
    ⭐ 실제 코드 경로로 확인하는 버그 회귀 테스트.
    1일차에 요청 예산으로 중단 → **날짜를 하루 넘긴 뒤** 재개했을 때 체크포인트를 이어받아
    **이미 끝낸 종목을 다시 요청하지 않아야** 합니다.
    (예전 run_key 였다면 날짜가 달라 체크포인트가 통째로 버려지고 전량 재수집됐습니다 —
     실운영 2,700종목 기준으로 수천 건의 불필요한 DART 요청입니다. §0-3-2)
    """
    from datetime import datetime, timedelta

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    universe = cdk.load_universe(str(uni))

    day1 = datetime(2026, 8, 24, 23, 40, tzinfo=ccm.KST)
    monkeypatch.setattr(cdk, "_now_kst", lambda: day1)
    _, first = cdk.run_collection(universe, "2026", str(tmp_path),
                                  max_requests=4, log=lambda *a: None)
    assert first["completed"] is False
    assert (tmp_path / "dividend_kr_2026_checkpoint.json").exists()

    # ── 하루가 지났습니다(그리고 다음 날 아침에 재개) ──
    calls = _counting_alot_calls(monkeypatch)
    monkeypatch.setattr(cdk, "_now_kst", lambda: day1 + timedelta(hours=9))
    _, second = cdk.run_collection(universe, "2026", str(tmp_path),
                                   max_requests=100, log=lambda *a: None)

    assert second["completed"] is True
    assert second["by_status"] == {"OK": 2}
    # 남은 1종목 × 우선순위 4단계 = 4건만 나갔어야 합니다. 8건이면 전량 재수집(=버그 재발).
    assert calls["n"] == 4, f"재개 시 요청이 {calls['n']}건 나갔습니다 — 체크포인트를 못 이어받았습니다."
    assert second["requests_used"] == 8      # 누적(1일차 4 + 2일차 4)


def test_run_collection_ignores_a_months_old_checkpoint(tmp_path, faked_network, monkeypatch):
    """
    날짜를 run_key 에서 뺀 대가로 생긴 위험(몇 달 전 잔재가 조건만 같아 되살아남)을
    신선도 검사가 막는지 실제 경로로 확인합니다 — 이어받지 않고 처음부터 다시 돌아야 합니다.
    """
    from datetime import datetime, timedelta

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    universe = cdk.load_universe(str(uni))

    long_ago = datetime(2026, 1, 5, 10, 0, tzinfo=ccm.KST)
    monkeypatch.setattr(cdk, "_now_kst", lambda: long_ago)
    cdk.run_collection(universe, "2026", str(tmp_path), max_requests=4, log=lambda *a: None)

    calls = _counting_alot_calls(monkeypatch)
    monkeypatch.setattr(cdk, "_now_kst", lambda: long_ago + timedelta(days=120))
    _, second = cdk.run_collection(universe, "2026", str(tmp_path),
                                   max_requests=100, log=lambda *a: None)

    assert second["completed"] is True
    assert second["by_status"] == {"OK": 2}
    # 120일 전 체크포인트는 버려졌으므로 2종목 × 4단계 = 8건이 다시 나갑니다.
    assert calls["n"] == 8
    assert second["requests_used"] == 8       # 이어받은 누적이 없으므로 8에서 시작


# =============================================================================
# 12. 2개 출처 교차검증 (§0-3-3) — DART 전기·전전기 ↔ KIND 2023~2025 기준선
#
# 배경: DART 응답에는 당기 말고도 전기(frmtrm)·전전기(lwfr)가 공짜로 실려 오고, 우리는 이미
#       `prev_*`/`prev2_*` 로 저장해 왔지만 **아무 데도 대조하지 않았습니다**. 한편 프로젝트에는
#       KIND 출처의 독립적인 2023~2025 연간 배당 집계가 이미 있습니다. 둘을 맞대보면 요청 한 건
#       더 쓰지 않고 2개 출처 교차검증이 됩니다.
#
# ⚠️ `unit_mismatch_notes` 와 같은 **감지 전용** 기능입니다. 이 절의 테스트는
#    "불일치를 기록하는가"만 검증하며, 어느 쪽이 옳은지 판정하거나 값을 고치지 않습니다(§0-1).
# =============================================================================
REAL_LATEST_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "dividend_kr_2026_latest.json")
REAL_HISTORY_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "dividend_history_kr_2023_2025.json")

# (합성) KIND 파일과 같은 모양의 최소 페이로드. 실파일의 행 구조를 그대로 본떴습니다.
SYNTHETIC_HISTORY = {
    "source": "KIND_annual_dividend_summary",
    "record_count": 3,
    "records": [
        {"stock_code": "005930", "company_name": "삼성전자", "fiscal_year": 2025,
         "dps_krw": 1668, "payout_ratio_pct": 25.10},
        {"stock_code": "005930", "company_name": "삼성전자", "fiscal_year": 2024,
         "dps_krw": 1446, "payout_ratio_pct": 29.20},
        {"stock_code": "000660", "company_name": "SK하이닉스", "fiscal_year": 2025,
         "dps_krw": 1500, "payout_ratio_pct": None},
    ],
}


def test_build_kind_baseline_index_keys_by_code_and_year():
    """(종목코드, 사업연도int) → {dps_krw, payout_ratio_pct} 색인이 나와야 합니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    assert set(idx) == {("005930", 2025), ("005930", 2024), ("000660", 2025)}
    assert idx[("005930", 2025)] == {"dps_krw": 1668, "payout_ratio_pct": 25.10}
    # 값이 없는 칸은 지어내지 않고 None 그대로 둡니다.
    assert idx[("000660", 2025)]["payout_ratio_pct"] is None


def test_build_kind_baseline_index_skips_malformed_rows_without_crashing():
    """(합성) 못 쓰는 행 하나 때문에 색인 전체가 죽으면 안 됩니다."""
    payload = {"records": [
        {"stock_code": "005930", "fiscal_year": 2025, "dps_krw": 1668},   # 정상
        {"fiscal_year": 2025, "dps_krw": 100},                            # 종목코드 없음
        {"stock_code": "000660", "dps_krw": 100},                         # 연도 없음
        {"stock_code": "000700", "fiscal_year": "연도미상", "dps_krw": 1},  # 연도가 숫자가 아님
        {"stock_code": "", "fiscal_year": 2025},                          # 빈 종목코드
        "이건 dict 도 아님",
        None,
    ]}
    idx = cdk.build_kind_baseline_index(payload)
    assert set(idx) == {("005930", 2025)}


def test_build_kind_baseline_index_handles_odd_top_level_input():
    """records 가 없거나 최상위가 dict 가 아니어도 빈 색인이지 예외가 아닙니다."""
    assert cdk.build_kind_baseline_index({}) == {}
    assert cdk.build_kind_baseline_index({"records": None}) == {}
    assert cdk.build_kind_baseline_index([]) == {}
    assert cdk.build_kind_baseline_index(None) == {}


def test_build_kind_baseline_index_keeps_first_on_duplicate_key():
    """(합성·방어) 같은 (종목, 연도)가 두 번 오면 먼저 나온 값을 유지합니다."""
    payload = {"records": [
        {"stock_code": "005930", "fiscal_year": 2025, "dps_krw": 1668},
        {"stock_code": "005930", "fiscal_year": 2025, "dps_krw": 9999},
    ]}
    assert cdk.build_kind_baseline_index(payload)[("005930", 2025)]["dps_krw"] == 1668


def test_build_kind_baseline_index_accepts_string_years_from_real_file_shape():
    """연도가 문자열 "2025" 로 와도 int 키로 정규화돼야 합니다(파일 형식 변화 방어)."""
    idx = cdk.build_kind_baseline_index(
        {"records": [{"stock_code": "005930", "fiscal_year": "2025", "dps_krw": 1668}]})
    assert idx[("005930", 2025)]["dps_krw"] == 1668


# ── check_cross_source ────────────────────────────────────────────────────────
def test_check_cross_source_says_nothing_when_two_sources_agree():
    """
    실데이터 기반: 삼성전자 2026 1분기 응답의 전기/전전기 주당현금배당금은 1,668 / 1,446 이고
    같은 값이 KIND 기준선에도 있습니다 → 불일치 note 는 하나도 없어야 합니다.
    """
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    prev = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="frmtrm")
    prev2 = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="lwfr")
    notes = cdk.check_cross_source(
        "005930", "2026",
        prev["dps_cash_common"], prev2["dps_cash_common"],
        prev["payout_ratio"], prev2["payout_ratio"], idx)
    assert notes == []


def test_check_cross_source_flags_dps_mismatch_with_both_numbers():
    """(합성) 주당배당금이 다르면 두 숫자와 두 연도가 모두 담긴 사유가 나와야 합니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    notes = cdk.check_cross_source("005930", "2026",
                                   1500.0, None,      # DART 전기 1,500 (기준선은 1,668)
                                   None, None, idx)
    assert len(notes) == 1
    note = notes[0]
    assert "005930" in note and "2025" in note and "전기" in note
    assert "1,500" in note and "1,668" in note
    assert "고치지 않" in note                      # 감지 전용임이 문장에 드러나야 합니다


def test_check_cross_source_checks_the_year_before_last_too():
    """전전기(=사업연도-2)도 함께 대조해야 합니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    notes = cdk.check_cross_source("005930", "2026",
                                   1668.0, 999.0,     # 전기는 일치, 전전기만 불일치
                                   None, None, idx)
    assert len(notes) == 1
    assert "2024" in notes[0] and "전전기" in notes[0] and "1,446" in notes[0]


def test_check_cross_source_flags_payout_ratio_mismatch():
    """(합성) 현금배당성향도 대조 대상입니다 — 허용 오차를 넘으면 사유를 남깁니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    notes = cdk.check_cross_source("005930", "2026",
                                   1668.0, 1446.0,    # 주당배당금은 일치
                                   30.0, None, idx)   # 성향만 25.10 → 30.0
    assert len(notes) == 1
    assert "현금배당성향" in notes[0] and "30.000" in notes[0] and "25.100" in notes[0]


def test_check_cross_source_tolerates_payout_rounding_difference():
    """
    성향은 계산된 백분율이라 출처마다 반올림 자리가 다릅니다.
    허용 오차(0.05%p) 이내면 불일치로 부풀리지 않습니다.
    """
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    assert cdk.CROSS_SOURCE_PAYOUT_TOLERANCE_PCT == 0.05
    assert cdk.check_cross_source("005930", "2026", 1668.0, 1446.0,
                                  25.13, 29.20, idx) == []      # 25.10 과 0.03%p 차이
    assert cdk.check_cross_source("005930", "2026", 1668.0, 1446.0,
                                  25.30, 29.20, idx) != []      # 0.20%p 차이 → 불일치


def test_check_cross_source_is_silent_when_baseline_has_no_such_row():
    """
    ⭐ '기준선에 그 종목·연도가 없음'은 불일치가 **아닙니다**.
    (무배당·신규상장 종목이 전부 경고로 뜨면 경고가 무의미해집니다 — §0-1 은 지어내지 말라는
     것이지, 모르는 것을 문제로 만들라는 것이 아닙니다.)
    """
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    assert cdk.check_cross_source("999999", "2026", 500.0, 500.0, 10.0, 10.0, idx) == []
    # 기준선이 2023~2025 뿐이라 2030년 실행의 전기(2029)는 대조할 짝이 없습니다.
    assert cdk.check_cross_source("005930", "2030", 500.0, 500.0, 10.0, 10.0, idx) == []


def test_check_cross_source_is_silent_when_dart_value_is_missing():
    """DART 쪽 값이 None 이면(무배당·미기재) 대조 대상이 아니라 불일치가 아닙니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    assert cdk.check_cross_source("005930", "2026", None, None, None, None, idx) == []


def test_check_cross_source_is_silent_when_baseline_value_is_missing():
    """기준선 행은 있지만 그 칸이 None 인 경우도 대조 불가 → note 없음."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    # 000660 의 2025 payout_ratio_pct 는 None 입니다. DART 가 값을 줘도 비교하지 않습니다.
    notes = cdk.check_cross_source("000660", "2026", 1500.0, None, 33.3, None, idx)
    assert notes == []


def test_check_cross_source_never_raises_on_bad_inputs():
    """순수 함수이므로 어떤 쓰레기 입력에도 예외 대신 빈 리스트여야 합니다."""
    idx = cdk.build_kind_baseline_index(SYNTHETIC_HISTORY)
    assert cdk.check_cross_source("005930", "연도미상", 1, 1, 1, 1, idx) == []
    assert cdk.check_cross_source(None, "2026", 1, 1, 1, 1, idx) == []
    assert cdk.check_cross_source("005930", "2026", 1, 1, 1, 1, None) == []
    assert cdk.check_cross_source("005930", "2026", 1, 1, 1, 1, {}) == []
    assert cdk.check_cross_source("005930", "2026", "값없음", "-", None, None, idx) == []


# ── build_dividend_record 배선 ────────────────────────────────────────────────
def test_build_record_cross_source_notes_are_empty_without_baseline():
    """
    ⭐ 하위호환 회귀 테스트. 새 인자를 넘기지 않는 기존 호출부는 **동작이 달라지면 안 되고**,
    `cross_source_notes` 는 항상 존재하되 빈 리스트여야 합니다(화면이 분기하기 쉽도록).
    """
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    prev = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="frmtrm")
    prev2 = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="lwfr")
    rec = cdk.build_dividend_record("005930", {"corp_code": "00126380"}, "2026", "11013",
                                    REAL_SAMSUNG_2026_Q1, parsed_now=parsed,
                                    parsed_prev=prev, parsed_prev2=prev2)
    assert rec["cross_source_notes"] == []
    # 실패 레코드도 같은 스키마여야 합니다.
    fail = cdk.build_dividend_record("005930", None, "2026", None, None, status="NO_DATA")
    assert fail["cross_source_notes"] == []
    # 기존 전기·전전기 필드가 그대로인지도 함께 못 박습니다(필드 삭제·개명 방지).
    assert rec["prev_dps_cash_common"] == 1668.0
    assert rec["prev2_dps_cash_common"] == 1446.0
    assert rec["prev_payout_ratio"] == 25.10


def test_build_record_populates_cross_source_notes_when_baseline_given():
    """(합성) 어긋나는 기준선을 넘기면 레코드에 사유가 실려야 합니다."""
    mismatching = cdk.build_kind_baseline_index({"records": [
        {"stock_code": "005930", "fiscal_year": 2025, "dps_krw": 1, "payout_ratio_pct": 1.0},
    ]})
    parsed = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"])
    prev = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="frmtrm")
    prev2 = cdk.parse_alot_rows(REAL_SAMSUNG_2026_Q1["list"], period="lwfr")
    rec = cdk.build_dividend_record("005930", {"corp_code": "00126380"}, "2026", "11013",
                                    REAL_SAMSUNG_2026_Q1, parsed_now=parsed,
                                    parsed_prev=prev, parsed_prev2=prev2,
                                    kind_baseline_index=mismatching)
    assert len(rec["cross_source_notes"]) == 2       # 주당배당금 + 배당성향
    assert any("1,668" in n for n in rec["cross_source_notes"])
    # ⭐ 감지만 합니다 — 저장된 값은 DART 원문 그대로여야 합니다(자동 보정 금지, §0-1).
    assert rec["prev_dps_cash_common"] == 1668.0
    assert rec["prev_payout_ratio"] == 25.10
    assert rec["dps_cash_common"] == 372.0
    # 다른 사유 리스트로 새지 않아야 합니다(각 관심사는 전용 필드에만).
    assert rec["parse_notes"] == [] and rec["unit_mismatch_notes"] == []


# ── summarize_results 집계 ────────────────────────────────────────────────────
def test_summary_aggregates_unit_and_cross_source_mismatches():
    """
    레코드마다 흩어진 감지 결과를 리포트에서 한눈에 볼 수 있어야 합니다
    (없으면 2,700종목 파일을 손으로 grep 해야만 알 수 있습니다).
    """
    clean = cdk.build_dividend_record("000001", None, "2026", "11012", None, status="OK")
    unit_bad = cdk.build_dividend_record(
        "000002", None, "2026", "11012", None, status="OK",
        parsed_now={"unit_mismatch_notes": ["단위 불일치: …"]})
    cross_bad = cdk.build_dividend_record(
        "000003", None, "2026", "11012", None, status="OK",
        parsed_prev={"dps_cash_common": 500.0},
        kind_baseline_index={("000003", 2025): {"dps_krw": 100, "payout_ratio_pct": None}})
    both_bad = cdk.build_dividend_record(
        "000004", None, "2026", "11012", None, status="OK",
        parsed_now={"unit_mismatch_notes": ["단위 확인 불가: …"]},
        parsed_prev={"dps_cash_common": 700.0},
        kind_baseline_index={("000004", 2025): {"dps_krw": 100, "payout_ratio_pct": None}})

    summary = cdk.summarize_results([clean, unit_bad, cross_bad, both_bad], unmapped=[])
    assert summary["records_with_unit_mismatch"] == 2
    assert summary["stock_codes_with_unit_mismatch"] == ["000002", "000004"]
    assert summary["records_with_cross_source_mismatch"] == 2
    assert summary["stock_codes_with_cross_source_mismatch"] == ["000003", "000004"]
    # 기존 집계는 그대로 있어야 합니다.
    assert summary["by_status"] == {"OK": 4}
    assert summary["total_records"] == 4


def test_summary_reports_zero_when_nothing_was_detected():
    """검출 0건도 필드가 존재해야 합니다(키가 없는 것과 0건은 다른 사실입니다)."""
    summary = cdk.summarize_results([], unmapped=[])
    assert summary["records_with_unit_mismatch"] == 0
    assert summary["stock_codes_with_unit_mismatch"] == []
    assert summary["records_with_cross_source_mismatch"] == 0
    assert summary["stock_codes_with_cross_source_mismatch"] == []


# ── run_collection 배선 ───────────────────────────────────────────────────────
def test_run_collection_does_not_cross_check_by_default(tmp_path, faked_network):
    """
    ⭐ 하위호환: 현재 GitHub Actions 워크플로는 이 옵션을 모릅니다.
    옵션 없이 돌리면 예전과 똑같이 동작하고, "대조하지 않았다"는 사실이 리포트에 남아야 합니다.
    """
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=lambda *a: None)
    assert summary["cross_source_checked"] is False
    assert summary["cross_source_baseline_path"] is None
    assert summary["records_with_cross_source_mismatch"] == 0
    assert all(r["cross_source_notes"] == [] for r in records)


def test_run_collection_cross_checks_when_baseline_path_given(tmp_path, faked_network):
    """(합성 기준선) 경로를 주면 레코드와 리포트에 불일치가 실려야 합니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    baseline = tmp_path / "history.json"
    baseline.write_text(json.dumps({"records": [
        {"stock_code": "005930", "fiscal_year": 2025, "dps_krw": 1, "payout_ratio_pct": 1.0},
    ]}), encoding="utf-8")

    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path),
        history_baseline_path=str(baseline), log=lambda *a: None)

    assert summary["cross_source_checked"] is True
    assert summary["cross_source_baseline_entries"] == 1
    assert summary["records_with_cross_source_mismatch"] == 1
    assert summary["stock_codes_with_cross_source_mismatch"] == ["005930"]
    assert records[0]["cross_source_notes"]
    # 값은 그대로 — 교차검증은 절대 데이터를 고치지 않습니다.
    assert records[0]["prev_dps_cash_common"] == 1668.0
    # 파일로도 남아야 사람이 나중에 볼 수 있습니다.
    saved = json.loads((tmp_path / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))
    assert saved["records"][0]["cross_source_notes"]


def test_run_collection_refuses_to_proceed_when_baseline_unreadable(tmp_path, faked_network):
    """
    §0-1: 교차검증을 **해달라고 명시한** 실행에서 파일을 못 읽었다면, 조용히 검증 없이
    진행해선 안 됩니다(그러면 '불일치 0건'이 '검증 통과'처럼 보입니다). 크게 실패해야 합니다.
    """
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    universe = cdk.load_universe(str(uni))

    with pytest.raises(cdk.DartFatalError, match="기준선"):
        cdk.run_collection(universe, "2026", str(tmp_path),
                           history_baseline_path=str(tmp_path / "없는파일.json"),
                           log=lambda *a: None)

    broken = tmp_path / "broken.json"
    broken.write_text("{이건 JSON 이 아닙니다", encoding="utf-8")
    with pytest.raises(cdk.DartFatalError, match="기준선"):
        cdk.run_collection(universe, "2026", str(tmp_path),
                           history_baseline_path=str(broken), log=lambda *a: None)

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(cdk.DartFatalError, match="하나도"):
        cdk.run_collection(universe, "2026", str(tmp_path),
                           history_baseline_path=str(empty), log=lambda *a: None)


def test_cli_exposes_new_optional_flags_without_breaking_existing_usage(tmp_path, monkeypatch):
    """
    새 플래그는 **선택**이어야 합니다 — 기존 워크플로 YAML 은 이 옵션들을 모릅니다.
    (run_collection 을 가짜로 갈아끼워 argparse 배선만 확인합니다)
    """
    seen = {}

    def fake_run(universe, year, out_dir, **kwargs):
        seen.update(kwargs)
        return [], {}

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    monkeypatch.setattr(cdk, "run_collection", fake_run)

    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 0
    assert seen["history_baseline_path"] is None            # 기본은 교차검증 안 함
    assert seen["checkpoint_max_age_days"] == cdk.DEFAULT_CHECKPOINT_MAX_AGE_DAYS == 14

    seen.clear()
    assert cdk.main(["--universe", str(uni), "--year", "2026", "--out-dir", str(tmp_path),
                     "--history-baseline", "data/history.json",
                     "--checkpoint-max-age-days", "3"]) == 0
    assert seen["history_baseline_path"] == "data/history.json"
    assert seen["checkpoint_max_age_days"] == 3


# ── 실데이터 전수 교차검증 ────────────────────────────────────────────────────
def test_real_production_records_cross_check_against_real_kind_baseline():
    """
    **실제 산출물 전수 교차검증** (네트워크 불필요 — 저장된 두 파일만 읽습니다).

    data/dividend_kr_2026_latest.json (DART 수집 결과 2,734레코드)의 전기·전전기 값을
    data/dividend_history_kr_2023_2025.json (KIND, 독립 출처 8,202행)과 맞대봅니다.

    ⚠️ 단위 검증과 달리 **여기서 불일치 0건을 기대할 이유가 없습니다.** 두 출처는 산정 방식이
       다르고(연결/별도 기준, 순이익 분모), 액면분할·재작성도 있습니다. 그래서 정확한 기대
       건수를 못 박지 않고, **① 전 레코드에서 함수가 예외 없이 돌 것 ② 불일치가 전체의
       절반을 넘지 않을 것**만 확인합니다. ②는 "모든 레코드가 다 불일치로 뜨는 체계적 버그"를
       잡기 위한 하한선이지, 데이터 품질 기준이 아닙니다.

    [2026-08-24 실측 관측치 — 참고용, 단정적 기대값이 아닙니다]
      · 대조할 짝이 하나라도 있는 레코드 971건 중 불일치 522건
      · 주당현금배당금 쌍 1,790건 중 어긋난 것 70건(53종목) — 대부분 액면분할·중간배당 차이로
        보이나 **와이엔텍(067900)** 처럼 DART 원문의 '주당 현금배당금(원)'에 배당총액
        (1,809,965,900원)이 적혀 있는 회사 기재 오류도 잡혔습니다(단위 라벨은 '(원)'이라
        단위 검증으로는 절대 잡히지 않는 종류의 오류입니다 — 교차검증만이 잡습니다).
      · 현금배당성향 쌍 1,663건 중 어긋난 것 943건. 차이가 매우 커(중앙값 0.14%p, 상위 10%는
        16%p 이상) 단순 반올림 문제가 아니라 **두 출처의 산정 기준 자체가 다를 가능성**이
        큽니다 — 사람(오너) 판단이 필요한 사안이라 여기서 단정하지 않습니다.
    """
    for path in (REAL_LATEST_JSON, REAL_HISTORY_JSON):
        if not os.path.exists(path):
            pytest.skip(f"실데이터가 없습니다: {path} (수집 후에만 검증 가능)")

    with open(REAL_HISTORY_JSON, encoding="utf-8") as fh:
        history = json.load(fh)
    with open(REAL_LATEST_JSON, encoding="utf-8") as fh:
        latest = json.load(fh)

    index = cdk.build_kind_baseline_index(history)
    records = latest.get("records") or []

    # 파일이 잘려 있는데 "0건 통과"로 착각하지 않도록 규모부터 확인합니다(§0-1).
    assert len(index) >= 8000, f"기준선 색인이 예상보다 작습니다({len(index)}건)."
    assert len(records) >= 2500, f"산출물이 예상보다 작습니다({len(records)}건)."

    comparable = mismatched = 0
    examples = []
    for rec in records:
        prev_dps = rec.get("prev_dps_cash_common")
        prev2_dps = rec.get("prev2_dps_cash_common")
        if prev_dps is None and prev2_dps is None:
            continue
        comparable += 1
        notes = cdk.check_cross_source(          # 예외 없이 전 레코드를 통과해야 합니다
            rec.get("stock_code"), rec.get("bsns_year"),
            prev_dps, prev2_dps,
            rec.get("prev_payout_ratio"), rec.get("prev2_payout_ratio"), index)
        assert isinstance(notes, list)
        assert all(isinstance(n, str) and n for n in notes)
        if notes:
            mismatched += 1
            if len(examples) < 5:
                examples.append((rec.get("stock_code"), notes[0]))

    assert comparable >= 500, f"대조 가능한 레코드가 {comparable}건뿐입니다 — 배선이 끊겼을 수 있습니다."
    # 체계적 버그(전 레코드가 다 불일치)에 대한 하한선. 품질 기준이 아닙니다.
    assert mismatched < len(records) / 2, (
        f"불일치가 {mismatched}/{len(records)}건으로 지나치게 많습니다 — 우리 대조 로직이 "
        f"정상값을 오탐하고 있을 가능성이 큽니다. 예시: {examples}")


def test_real_production_dps_mismatches_are_the_rare_case():
    """
    같은 실데이터에서 **주당현금배당금만** 따로 봅니다.
    성향(%)은 산정 기준 차이로 많이 어긋나지만, 주당배당금은 원 단위 사실값이라 대부분
    일치해야 정상입니다(2026-08-24 실측: 대조쌍 1,790건 중 불일치 70건 ≈ 3.9%).
    비율이 크게 튀면 우리 대조 로직이나 어느 한쪽 출처가 망가진 것입니다.
    """
    for path in (REAL_LATEST_JSON, REAL_HISTORY_JSON):
        if not os.path.exists(path):
            pytest.skip(f"실데이터가 없습니다: {path} (수집 후에만 검증 가능)")

    with open(REAL_HISTORY_JSON, encoding="utf-8") as fh:
        index = cdk.build_kind_baseline_index(json.load(fh))
    with open(REAL_LATEST_JSON, encoding="utf-8") as fh:
        records = json.load(fh).get("records") or []

    pairs = mismatched = 0
    for rec in records:
        year = int(rec["bsns_year"])
        for offset, dart_dps in ((1, rec.get("prev_dps_cash_common")),
                                 (2, rec.get("prev2_dps_cash_common"))):
            base = index.get((rec.get("stock_code"), year - offset))
            if not base or base.get("dps_krw") is None or dart_dps is None:
                continue
            pairs += 1
            if abs(float(dart_dps) - float(base["dps_krw"])) >= 1:
                mismatched += 1

    assert pairs >= 1000, f"대조쌍이 {pairs}건뿐입니다 — 배선이 끊겼을 수 있습니다."
    assert mismatched / pairs < 0.25, (
        f"주당배당금 불일치율이 {mismatched}/{pairs} 로 지나치게 높습니다 — "
        "대조 로직이나 한쪽 출처를 확인해야 합니다.")


# =============================================================================
# 13. 델타 실행 결과 병합 (merge_delta_output)
#
# 배경: 2026 전수 수집은 "2023~2025 중 한 번이라도 배당한 2,734종목" 유니버스로 돌았고,
#       그 뒤에 생긴 신규 상장·신규 배당 종목은 통째로 빠져 있습니다. 나중에 신규 종목만
#       따로 돌린 뒤(= 델타 수집) 같은 out_dir 로 저장하면 기존 2,734종목이 조용히
#       사라집니다 — 그래서 델타는 별도 out_dir 로 돌리고 여기서 합칩니다.
#
# 여기 테스트가 못 박는 것:
#   · 겹치면 합치지 않고 크게 실패한다(자동 해소·중복 저장 금지).
#   · **실패한 병합은 단 한 바이트도 쓰지 않는다** — 입력 두 파일이 그대로 남아야 합니다.
#   · 원래 두 실행의 리포트가 merged_from 에 원문 그대로 살아 있다.
#   · 리포트 숫자는 손으로 더하지 않고 summarize_results() 가 다시 계산한다.
#
# ⚠️ 실산출물(6.8MB/9.4MB)은 쓰지 않습니다 — tmp_path 에 같은 스키마의 작은 파일을 만듭니다.
# =============================================================================
def _merge_fake_record(code, status="OK", dps=100):
    """병합 테스트용 최소 레코드. 실제 스키마의 부분집합입니다."""
    return {
        "stock_code": code,
        "corp_name": f"테스트{code}",
        "bsns_year": "2026",
        "reprt_name": "반기보고서" if status == "OK" else None,
        "dps_cash_common": dps if status == "OK" else None,
        "status": status,
        "status_reason": "" if status == "OK" else "데이터 없음",
        "parse_notes": [],
        "unknown_se_labels": [],
        "unit_mismatch_notes": [],
        "cross_source_notes": [],
    }


def _merge_raw_entry(code, reprt_code="11012"):
    """병합 테스트용 raw JSONL 한 줄(실제 raw 파일과 같은 키 구성)."""
    return {"stock_code": code, "corp_code": "00" + code, "bsns_year": "2026",
            "reprt_code": reprt_code, "fetched_at_kst": "2026-08-23T23:27:33+09:00",
            "response": {"status": "000", "message": "정상", "list": []}}


def _write_run_output(out_dir, records, unmapped=None, *, year="2026",
                      completed=True, stopped_reason=None, requests_used=4,
                      elapsed_sec=10.0, raw_entries=None, corpcode_source=None):
    """한 실행의 산출물(latest.json [+ raw.jsonl])을 실제와 같은 형태로 만듭니다."""
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    summary = cdk.summarize_results(records, unmapped or [], extra={
        "bsns_year": year,
        "universe_size_input": len(records),
        "universe_size": len(records),
        "requests_used": requests_used,
        "elapsed_sec": elapsed_sec,
        "completed": completed,
        "stopped_reason": stopped_reason,
        "corpcode_source": corpcode_source,
        "corpcode_stats": {"total": len(records)} if corpcode_source else None,
    })
    path = os.path.join(out_dir, f"dividend_kr_{year}_latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, ensure_ascii=False, indent=2)
    if raw_entries is not None:
        raw_path = os.path.join(out_dir, f"dividend_kr_{year}_raw.jsonl")
        with open(raw_path, "w", encoding="utf-8") as f:
            for entry in raw_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def _snapshot(*paths):
    """파일들의 바이트 스냅샷. 실패한 병합이 '아무것도 안 건드렸는지' 확인용."""
    return {p: (open(p, "rb").read() if os.path.exists(p) else None) for p in paths}


@pytest.fixture
def merge_dirs(tmp_path):
    """기존 전체 결과(2종목) + 델타 결과(1종목, 겹치지 않음) 한 쌍을 만들어 줍니다."""
    main_dir = tmp_path / "main"
    delta_dir = tmp_path / "delta"
    _write_run_output(main_dir,
                      [_merge_fake_record("005930"), _merge_fake_record("000660", "NO_DATA")],
                      unmapped=[{"stock_code_input": "AAA", "stock_code": None,
                                 "reason": "형식 오류"}],
                      requests_used=8, elapsed_sec=100.0, corpcode_source="cache",
                      raw_entries=[_merge_raw_entry("005930"), _merge_raw_entry("000660")])
    _write_run_output(delta_dir, [_merge_fake_record("123456", dps=50)],
                      requests_used=2, elapsed_sec=5.0, corpcode_source="network",
                      raw_entries=[_merge_raw_entry("123456")])
    return main_dir, delta_dir


def test_merge_delta_combines_records_and_recomputes_summary(merge_dirs):
    """행복 경로: 2 + 1 → 3레코드, 리포트는 summarize_results 가 다시 계산합니다."""
    main_dir, delta_dir = merge_dirs
    records, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)

    assert [r["stock_code"] for r in records] == ["005930", "000660", "123456"]
    assert summary["total_records"] == 3
    assert summary["by_status"] == {"OK": 2, "NO_DATA": 1}
    # 손으로 더한 숫자가 아니라 재계산된 값이어야 합니다.
    assert summary["requests_used"] == 10
    assert summary["elapsed_sec"] == 105.0
    assert summary["universe_size"] == 3
    assert summary["universe_size_input"] == 3
    assert summary["bsns_year"] == "2026"
    assert "병합" in summary["verification_status"]
    assert summary["merge_performed_at_kst"]
    # 최신 corp_code 캐시 상태는 나중에 돈 델타 쪽을 따릅니다.
    assert summary["corpcode_source"] == "network"

    # 디스크에도 그대로 있어야 합니다.
    on_disk = json.loads((main_dir / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))
    assert len(on_disk["records"]) == 3
    assert on_disk["summary"]["total_records"] == 3


def test_merge_delta_keeps_both_original_summaries_verbatim(merge_dirs):
    """§0-1: 두 실행을 하나인 척 뭉개면 어느 쪽이 언제 돌았는지가 사라집니다."""
    main_dir, delta_dir = merge_dirs
    before_main = json.loads(
        (main_dir / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))["summary"]
    before_delta = json.loads(
        (delta_dir / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))["summary"]

    _, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["merged_from"] == [before_main, before_delta]


def test_merge_delta_carries_over_unmapped_detail_from_both_runs(tmp_path):
    """매핑 실패 목록도 합쳐져야 합니다 — 한쪽 것이 조용히 사라지면 안 됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")],
                      unmapped=[{"stock_code_input": "AAA", "reason": "형식 오류"}],
                      raw_entries=[])
    _write_run_output(delta_dir, [_merge_fake_record("123456")],
                      unmapped=[{"stock_code_input": "BBB", "reason": "corp_code 없음"}],
                      raw_entries=[])
    _, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["unmapped_stock_codes"] == 2
    assert [u["stock_code_input"] for u in summary["unmapped_detail"]] == ["AAA", "BBB"]


def test_merge_delta_appends_raw_jsonl_in_order(merge_dirs):
    """raw 는 append-only 입니다 — 기존 줄 뒤에 델타 줄이 순서 그대로 붙어야 합니다."""
    main_dir, delta_dir = merge_dirs
    raw_path = main_dir / "dividend_kr_2026_raw.jsonl"
    before = raw_path.read_text(encoding="utf-8").splitlines()
    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    after = raw_path.read_text(encoding="utf-8").splitlines()
    assert len(after) == len(before) + 1 == 3
    assert after[:2] == before                       # 기존 줄은 손대지 않습니다
    assert json.loads(after[-1])["stock_code"] == "123456"
    # 마지막 줄에도 개행이 있어야 다음 델타가 이어붙어도 줄이 뭉치지 않습니다.
    assert raw_path.read_text(encoding="utf-8").endswith("\n")


def test_merge_delta_writes_merge_log_manifest(merge_dirs):
    """감사 로그: 무엇을 언제 합쳤는지 남아야 두 번 합치는 사고를 잡을 수 있습니다."""
    main_dir, delta_dir = merge_dirs
    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    log_path = main_dir / "dividend_kr_2026_merge_log.json"
    assert log_path.exists()
    entries = json.loads(log_path.read_text(encoding="utf-8"))["merges"]
    assert len(entries) == 1
    assert entries[0]["delta_out_dir"] == str(delta_dir)
    assert entries[0]["delta_stock_codes"] == ["123456"]
    assert entries[0]["delta_record_count"] == 1
    assert entries[0]["merged_at_kst"]


# ── 실패 경로 — 실패한 병합은 단 한 바이트도 쓰지 않아야 합니다 ─────────────────
def test_merge_delta_refuses_when_stock_codes_overlap(tmp_path):
    """
    §0-1: 겹치는 종목이 있으면 이건 '델타'가 아닙니다. 중복 저장도, 한쪽 임의 폐기도
    하지 않고 겹친 코드를 알려 주며 크게 실패해야 합니다.
    """
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930"), _merge_fake_record("000660")],
                      raw_entries=[_merge_raw_entry("005930")])
    _write_run_output(delta_dir, [_merge_fake_record("000660"), _merge_fake_record("123456")],
                      raw_entries=[_merge_raw_entry("000660")])

    watched = _snapshot(str(main_dir / "dividend_kr_2026_latest.json"),
                        str(main_dir / "dividend_kr_2026_raw.jsonl"),
                        str(delta_dir / "dividend_kr_2026_latest.json"),
                        str(delta_dir / "dividend_kr_2026_raw.jsonl"),
                        str(main_dir / "dividend_kr_2026_merge_log.json"))
    before = _snapshot(*watched)

    with pytest.raises(ValueError, match="겹칩니다"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    assert _snapshot(*watched) == before, "실패한 병합이 파일을 건드렸습니다"


def test_merge_delta_overlap_message_lists_codes_but_caps_the_list(tmp_path):
    """겹친 종목이 수백 건이어도 메시지가 터미널을 도배하면 안 됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    codes = [f"{i:06d}" for i in range(50)]
    _write_run_output(main_dir, [_merge_fake_record(c) for c in codes], raw_entries=[])
    _write_run_output(delta_dir, [_merge_fake_record(c) for c in codes], raw_entries=[])

    with pytest.raises(ValueError) as exc:
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    msg = str(exc.value)
    assert "50건 겹칩니다" in msg
    assert "외 30건" in msg              # 앞 20개만 보여주고 나머지는 건수로
    assert "000049" not in msg


def test_merge_delta_errors_clearly_when_main_output_missing(tmp_path):
    """전수 수집을 아직 안 한 디렉터리에 병합하려 하면 사람이 읽을 문장으로 막아야 합니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    os.makedirs(str(main_dir))
    _write_run_output(delta_dir, [_merge_fake_record("123456")], raw_entries=[])

    with pytest.raises(FileNotFoundError) as exc:
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    assert "기존 전체 결과" in str(exc.value)
    assert "전수 수집" in str(exc.value)
    assert not (main_dir / "dividend_kr_2026_merge_log.json").exists()


def test_merge_delta_errors_clearly_when_delta_output_missing(tmp_path):
    """델타 out_dir 을 잘못 짚었을 때도 마찬가지입니다 — 조용히 성공하면 안 됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")], raw_entries=[])
    os.makedirs(str(delta_dir))
    before = _snapshot(str(main_dir / "dividend_kr_2026_latest.json"))

    with pytest.raises(FileNotFoundError) as exc:
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    assert "델타 실행 결과" in str(exc.value)
    assert _snapshot(str(main_dir / "dividend_kr_2026_latest.json")) == before


def test_merge_delta_errors_on_malformed_main_output(tmp_path):
    """깨진 JSON 을 만나면 혼란스러운 트레이스백 대신 어떤 파일이 문제인지 말해야 합니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    os.makedirs(str(main_dir))
    (main_dir / "dividend_kr_2026_latest.json").write_text("{이건 JSON 이", encoding="utf-8")
    _write_run_output(delta_dir, [_merge_fake_record("123456")], raw_entries=[])

    with pytest.raises(ValueError, match="읽지 못했습니다"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)


# ── 두 번 합치기 방지 ────────────────────────────────────────────────────────
def test_merge_delta_rejects_merging_the_same_delta_twice(merge_dirs):
    """같은 델타를 두 번 합치면 레코드가 중복됩니다 — 이력을 보고 막아야 합니다."""
    main_dir, delta_dir = merge_dirs
    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    after_first = _snapshot(str(main_dir / "dividend_kr_2026_latest.json"),
                            str(main_dir / "dividend_kr_2026_raw.jsonl"))
    with pytest.raises(ValueError, match="이미 병합된 델타"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    assert _snapshot(*after_first) == after_first, "거부된 재병합이 파일을 건드렸습니다"

    entries = json.loads(
        (main_dir / "dividend_kr_2026_merge_log.json").read_text(encoding="utf-8"))["merges"]
    assert len(entries) == 1, "거부된 병합이 이력에 남으면 안 됩니다"


def test_merge_delta_matches_the_manifest_by_code_set_not_by_path(tmp_path):
    """
    운영 편의상 델타마다 같은 임시 디렉터리를 재사용하는 경우가 있습니다.
    경로만 보고 막으면 **정당한 새 델타**까지 거부됩니다 — 종목 구성으로 판단해야 합니다.
    """
    main_dir, scratch = tmp_path / "m", tmp_path / "scratch"
    _write_run_output(main_dir, [_merge_fake_record("005930")],
                      raw_entries=[_merge_raw_entry("005930")])

    _write_run_output(scratch, [_merge_fake_record("111111")],
                      raw_entries=[_merge_raw_entry("111111")])
    cdk.merge_delta_output(str(main_dir), str(scratch), "2026", log=lambda *a: None)

    # 같은 경로를 재사용하지만 **내용이 다른** 2차 델타 → 막히면 안 됩니다.
    _write_run_output(scratch, [_merge_fake_record("222222")],
                      raw_entries=[_merge_raw_entry("222222")])
    records, summary = cdk.merge_delta_output(str(main_dir), str(scratch), "2026",
                                              log=lambda *a: None)
    assert [r["stock_code"] for r in records] == ["005930", "111111", "222222"]
    assert summary["total_records"] == 3

    entries = json.loads(
        (main_dir / "dividend_kr_2026_merge_log.json").read_text(encoding="utf-8"))["merges"]
    assert [e["delta_stock_codes"] for e in entries] == [["111111"], ["222222"]]
    # raw 도 두 번 모두 이어붙었어야 합니다.
    raw = (main_dir / "dividend_kr_2026_raw.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["stock_code"] for l in raw] == ["005930", "111111", "222222"]


def test_merge_delta_force_overrides_the_manifest_guard(merge_dirs):
    """
    force=True 는 **이력 가드만** 무르는 탈출구입니다.
    (기존 결과를 백업본으로 되돌린 뒤 이력만 남아 있는 상황을 재현합니다)
    """
    main_dir, delta_dir = merge_dirs
    main_latest = main_dir / "dividend_kr_2026_latest.json"
    backup = main_latest.read_bytes()

    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    main_latest.write_bytes(backup)              # 가공본만 롤백 — 이력은 그대로 남습니다

    with pytest.raises(ValueError, match="이미 병합된 델타"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    lines = []
    records, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                              force=True, log=lines.append)
    assert summary["total_records"] == 3
    assert any("강제 재병합" in l for l in lines), "강제 재병합은 조용히 지나가면 안 됩니다"

    entries = json.loads(
        (main_dir / "dividend_kr_2026_merge_log.json").read_text(encoding="utf-8"))["merges"]
    assert len(entries) == 2
    assert entries[1]["forced"] is True


def test_merge_delta_force_does_not_override_the_overlap_guard(merge_dirs):
    """
    force 로도 겹침은 통과하지 못합니다 — 어느 쪽 값이 맞는지 우리가 판정할 수 없으므로
    자동 해소하면 반드시 한쪽을 조용히 버리게 됩니다(§0-1).
    """
    main_dir, delta_dir = merge_dirs
    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    with pytest.raises(ValueError, match="겹칩니다"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                               force=True, log=lambda *a: None)


# ── raw 없는 델타 ────────────────────────────────────────────────────────────
def test_merge_delta_survives_a_delta_run_with_no_raw_file(tmp_path):
    """
    델타 종목이 전부 UNMAPPED 였다면 요청이 0건이라 raw 파일이 아예 없습니다.
    그건 오류가 아니라 정상 시나리오입니다 — 경고만 남기고 병합은 성공해야 합니다.
    """
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")],
                      raw_entries=[_merge_raw_entry("005930")])
    _write_run_output(delta_dir, [_merge_fake_record("123456", "UNMAPPED")],
                      unmapped=[{"stock_code_input": "123456", "reason": "corp_code 없음"}],
                      requests_used=0, raw_entries=None)          # raw 파일을 만들지 않음
    raw_path = main_dir / "dividend_kr_2026_raw.jsonl"
    before = raw_path.read_bytes()

    lines = []
    records, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                              log=lines.append)
    assert summary["total_records"] == 2
    assert summary["by_status"] == {"OK": 1, "UNMAPPED": 1}
    assert raw_path.read_bytes() == before, "기존 raw 가 손상됐습니다"
    assert any("델타 raw 파일이 없습니다" in l for l in lines)

    entries = json.loads(
        (main_dir / "dividend_kr_2026_merge_log.json").read_text(encoding="utf-8"))["merges"]
    assert entries[0]["delta_raw_lines_appended"] == 0


def test_merge_delta_creates_main_raw_when_it_does_not_exist(tmp_path):
    """기존 raw 가 없더라도(비정상이지만 가능) 델타 raw 를 잃어버리면 안 됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")], raw_entries=None)
    _write_run_output(delta_dir, [_merge_fake_record("123456")],
                      raw_entries=[_merge_raw_entry("123456")])

    cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    raw = (main_dir / "dividend_kr_2026_raw.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["stock_code"] for l in raw] == ["123456"]


def test_merge_delta_refuses_a_corrupted_delta_raw_file(tmp_path):
    """깨진 raw 를 그대로 이어붙이면 원본 보관 파일 전체가 오염됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")],
                      raw_entries=[_merge_raw_entry("005930")])
    _write_run_output(delta_dir, [_merge_fake_record("123456")],
                      raw_entries=[_merge_raw_entry("123456")])
    with open(delta_dir / "dividend_kr_2026_raw.jsonl", "a", encoding="utf-8") as f:
        f.write("이건 JSON 이 아닙니다\n")

    watched = (str(main_dir / "dividend_kr_2026_latest.json"),
               str(main_dir / "dividend_kr_2026_raw.jsonl"))
    before = _snapshot(*watched)
    with pytest.raises(ValueError, match="2번째 줄"):
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    assert _snapshot(*watched) == before


# ── completed / stopped_reason 조합 ──────────────────────────────────────────
def test_merge_delta_reports_completed_only_when_both_runs_completed(merge_dirs):
    """둘 다 전수 완료여야 완료입니다."""
    main_dir, delta_dir = merge_dirs
    _, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["completed"] is True
    assert summary["stopped_reason"] is None


@pytest.mark.parametrize("main_ok,delta_ok,expect_in_reason", [
    (True, False, ["델타 실행 미완료"]),
    (False, True, ["기존 실행 미완료"]),
    (False, False, ["기존 실행 미완료", "델타 실행 미완료"]),
])
def test_merge_delta_combines_incomplete_reasons(tmp_path, main_ok, delta_ok, expect_in_reason):
    """
    §0-1: 한쪽이라도 중단됐으면 병합본을 '완료'라고 말하면 안 되고, **어느 쪽이 왜**
    중단됐는지가 사유에 남아야 합니다.
    """
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_merge_fake_record("005930")], raw_entries=[],
                      completed=main_ok,
                      stopped_reason=None if main_ok else "요청 예산 소진")
    _write_run_output(delta_dir, [_merge_fake_record("123456")], raw_entries=[],
                      completed=delta_ok,
                      stopped_reason=None if delta_ok else "실행시간 예산 소진")

    _, summary = cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["completed"] is False
    for fragment in expect_in_reason:
        assert fragment in summary["stopped_reason"]
    if not main_ok:
        assert "요청 예산 소진" in summary["stopped_reason"]
    if not delta_ok:
        assert "실행시간 예산 소진" in summary["stopped_reason"]


# ── CLI 배선 ────────────────────────────────────────────────────────────────
def test_cli_merge_delta_mode_does_not_require_universe(tmp_path, monkeypatch):
    """--merge-delta 는 수집을 하지 않으므로 --universe 가 필요 없어야 합니다."""
    seen = {}

    def fake_merge(main_out_dir, delta_out_dir, bsns_year, force=False, log=print):
        seen.update(dict(main_out_dir=main_out_dir, delta_out_dir=delta_out_dir,
                         bsns_year=bsns_year, force=force))
        return [], {}

    def must_not_run(*a, **kw):                    # 병합 모드가 수집으로 흘러들면 실패
        raise AssertionError("병합 모드에서 run_collection 이 호출됐습니다")

    monkeypatch.setattr(cdk, "merge_delta_output", fake_merge)
    monkeypatch.setattr(cdk, "run_collection", must_not_run)

    assert cdk.main(["--year", "2026", "--out-dir", str(tmp_path),
                     "--merge-delta", str(tmp_path / "delta")]) == 0
    assert seen == {"main_out_dir": str(tmp_path), "delta_out_dir": str(tmp_path / "delta"),
                    "bsns_year": "2026", "force": False}

    seen.clear()
    assert cdk.main(["--year", "2026", "--out-dir", str(tmp_path),
                     "--merge-delta", str(tmp_path / "delta"), "--force-merge"]) == 0
    assert seen["force"] is True


def test_cli_still_requires_universe_for_a_collection_run(tmp_path, monkeypatch):
    """반대로 수집 모드에서 --universe 가 빠지면 분명히 막아야 합니다."""
    monkeypatch.setattr(cdk, "run_collection",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("유니버스 없이 수집이 시작됐습니다")))
    with pytest.raises(SystemExit):
        cdk.main(["--year", "2026", "--out-dir", str(tmp_path)])


def test_cli_rejects_force_merge_without_merge_delta(tmp_path, monkeypatch):
    """--force-merge 만 단독으로 주면 아무 효과 없이 수집이 돌아가선 안 됩니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    monkeypatch.setattr(cdk, "run_collection",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("--force-merge 가 조용히 무시됐습니다")))
    with pytest.raises(SystemExit):
        cdk.main(["--universe", str(uni), "--year", "2026",
                  "--out-dir", str(tmp_path), "--force-merge"])


def test_cli_merge_failure_exits_nonzero_without_traceback(tmp_path, capsys):
    """§0-3-4: 병합 실패는 트레이스백이 아니라 사람이 읽을 문장 + 종료코드 2 로 끝납니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    os.makedirs(str(main_dir))
    _write_run_output(delta_dir, [_merge_fake_record("123456")], raw_entries=[])

    assert cdk.main(["--year", "2026", "--out-dir", str(main_dir),
                     "--merge-delta", str(delta_dir)]) == 2
    out = capsys.readouterr().out
    assert "병합하지 않았습니다" in out
    assert "Traceback" not in out


# =============================================================================
# 13. 기존 산출물 덮어쓰기 방지 (run_collection 의 allow_overwrite 가드)
#
# 배경: run_collection() 은 마지막에 {out_dir}/dividend_kr_{year}_latest.json 을 통째로
#       새로 씁니다. 실서비스 data/ 를 --out-dir 로 준 채 작은 델타 유니버스로 한 번 더
#       돌리면 기존 2,700여 건이 조용히 사라지고 새 실행의 몇 건만 남습니다
#       (merge_delta_output() 이 반대 방향에서 막던 바로 그 사고).
#
# 이어하기와 다른 실행을 가르는 신호 = **체크포인트에 적힌 run_key**.
#   · 같은 run_key  → 같은 실행을 이어서/다시 도는 것 → 가드 없음(기존 동작 그대로).
#   · 없음/깨짐/다름 → 이 산출물을 만든 실행이라고 확인할 수 없음 → 요청 0건으로 중단.
#
# 여기 테스트가 못 박는 것:
#   · **막힌 실행은 단 한 바이트도 쓰지 않고, 요청도 한 건 나가지 않는다.**
#   · 진짜 이어하기(같은 run_key)는 이 변경으로 조금도 달라지지 않는다(하위호환 회귀).
# =============================================================================
def _forbid_all_network(monkeypatch):
    """
    DART 로 나가는 모든 통로(alotMatter JSON · corpCode ZIP)를 '부르면 실패'로 막습니다.
    가드가 **요청을 한 건이라도 쓰기 전에** 멈추는지 확인하는 용도입니다.
    """
    def boom(*a, **kw):
        raise AssertionError("가드가 막았어야 할 실행에서 DART 요청이 나갔습니다")

    monkeypatch.setattr(cdk, "_http_get_json", boom)
    monkeypatch.setattr(ccm, "_http_get_bytes", boom)


def _guard_paths(tmp_path, year="2026"):
    """가드가 지켜야 할 파일 3종의 경로(가공본 · raw · 체크포인트)."""
    return [str(tmp_path / f"dividend_kr_{year}_latest.json"),
            str(tmp_path / f"dividend_kr_{year}_raw.jsonl"),
            str(tmp_path / f"dividend_kr_{year}_checkpoint.json")]


@pytest.mark.parametrize("allow_overwrite", [False, True])
def test_run_collection_first_run_into_a_fresh_dir_is_never_guarded(
        tmp_path, faked_network, allow_overwrite):
    """
    산출물이 아직 없으면 덮어쓸 것도 없습니다 — allow_overwrite 와 무관하게 그냥 돌아야 합니다.
    (가드가 '처음 수집'까지 막으면 그게 더 큰 사고입니다.)
    """
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")

    _, summary = cdk.run_collection(cdk.load_universe(str(uni)), "2026", str(tmp_path),
                                    allow_overwrite=allow_overwrite, log=lambda *a: None)

    assert summary["completed"] is True
    assert summary["by_status"] == {"OK": 2}
    assert (tmp_path / "dividend_kr_2026_latest.json").exists()


def test_run_collection_genuine_resume_is_not_guarded(tmp_path, faked_network, monkeypatch):
    """
    ⭐ 하위호환 회귀. 실운영 워크플로는 --allow-overwrite 를 **모릅니다**: 같은 유니버스로
    같은 data/ 에 이어 돌 뿐입니다. 1차 실행이 남긴 latest.json 이 있어도, run_key 가 같은
    이어하기라면 가드가 걸리지 않고 예전과 똑같이 이어받아야 합니다.
    """
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    universe = cdk.load_universe(str(uni))

    _, first = cdk.run_collection(universe, "2026", str(tmp_path),
                                  max_requests=4, log=lambda *a: None)
    assert first["completed"] is False
    # 1차 실행이 이미 산출물과 체크포인트를 남겼습니다 — 2차 실행이 마주칠 상황.
    assert (tmp_path / "dividend_kr_2026_latest.json").exists()
    assert (tmp_path / "dividend_kr_2026_checkpoint.json").exists()

    calls = _counting_alot_calls(monkeypatch)
    _, second = cdk.run_collection(universe, "2026", str(tmp_path),      # allow_overwrite 기본 False
                                   max_requests=100, log=lambda *a: None)

    assert second["completed"] is True
    assert second["by_status"] == {"OK": 2}
    # 남은 1종목 × 4단계 = 4건. 가드 도입 전과 완전히 같은 숫자입니다.
    assert calls["n"] == 4
    assert second["requests_used"] == 8


def test_run_collection_refuses_to_overwrite_another_runs_output(tmp_path, monkeypatch):
    """
    ⭐ 이 변경의 핵심 회귀 테스트.
    체크포인트가 아예 없는 디렉터리에 남의 산출물만 있는 상황(= 예전 실행이 전수 완료돼
    체크포인트가 지워진 실서비스 data/ 가 딱 이 모양입니다)에서 새 실행을 걸면,
    **요청 0건 · 디스크 0바이트 변경**으로 멈춰야 합니다.
    """
    _write_run_output(tmp_path,
                      [_merge_fake_record("005930"), _merge_fake_record("000660")],
                      raw_entries=[_merge_raw_entry("005930"), _merge_raw_entry("000660")])
    assert not (tmp_path / "dividend_kr_2026_checkpoint.json").exists()

    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")
    monkeypatch.setattr(cdk, "polite_sleep", lambda rng=None: 0.0)
    _forbid_all_network(monkeypatch)

    before = _snapshot(*_guard_paths(tmp_path))
    with pytest.raises(cdk.DartFatalError) as excinfo:
        cdk.run_collection(["123456"], "2026", str(tmp_path), log=lambda *a: None)
    after = _snapshot(*_guard_paths(tmp_path))

    msg = str(excinfo.value)
    assert "dividend_kr_2026_latest.json" in msg          # 어떤 파일이 걸렸는지
    assert "--allow-overwrite" in msg                     # 정말 덮어쓰려면 어떻게 하는지
    assert "--merge-delta" in msg                         # 델타라면 어떻게 해야 하는지
    assert "덮어써" in msg
    # 한 바이트도 건드리지 않았어야 합니다(가장 중요한 단언).
    assert after == before
    assert after[_guard_paths(tmp_path)[0]] is not None    # 기존 파일은 그대로 남아 있고
    assert after[_guard_paths(tmp_path)[2]] is None        # 체크포인트를 새로 만들지도 않았습니다


def test_run_collection_refuses_when_checkpoint_belongs_to_other_parameters(
        tmp_path, monkeypatch):
    """
    체크포인트가 있어도 **다른 실행조건**(여기서는 유니버스 크기가 다름)이면 이어하기가
    아닙니다 — 처음부터 도는 다른 실행이므로 똑같이 막아야 합니다.
    """
    _write_run_output(tmp_path, [_merge_fake_record("005930")])
    other_key = cdk.build_run_key("2026", 2734, cdk.REPRT_CODE_PRIORITY)
    cdk.save_checkpoint(str(tmp_path / "dividend_kr_2026_checkpoint.json"),
                        other_key, [], ["005930"], 4)

    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")
    _forbid_all_network(monkeypatch)

    before = _snapshot(*_guard_paths(tmp_path))
    with pytest.raises(cdk.DartFatalError) as excinfo:
        cdk.run_collection(["123456"], "2026", str(tmp_path), log=lambda *a: None)

    assert other_key in str(excinfo.value)       # 어느 실행의 체크포인트였는지 그대로 보여 줍니다
    assert _snapshot(*_guard_paths(tmp_path)) == before


def test_run_collection_overwrites_when_the_operator_asks_for_it(tmp_path, faked_network):
    """
    allow_overwrite=True 는 '알고 덮어쓴다'는 명시적 선택입니다 — 막지 않고 진행해야 합니다.
    (이 경우 기존 레코드가 사라지는 것은 사고가 아니라 요청한 결과입니다.)
    """
    _write_run_output(tmp_path, [_merge_fake_record("123456")])

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    _, summary = cdk.run_collection(cdk.load_universe(str(uni)), "2026", str(tmp_path),
                                    allow_overwrite=True, log=lambda *a: None)

    assert summary["completed"] is True
    saved = json.loads((tmp_path / "dividend_kr_2026_latest.json").read_text(encoding="utf-8"))
    assert [r["stock_code"] for r in saved["records"]] == ["005930"]     # 새 실행 결과로 교체됨


# ── CLI 배선 ────────────────────────────────────────────────────────────────
def test_cli_allow_overwrite_is_optional_and_defaults_to_false(tmp_path, monkeypatch):
    """
    기존 워크플로 YAML 은 이 플래그를 모릅니다 — 빠지면 False 로 run_collection 에 가야 합니다.
    (run_collection 을 가짜로 갈아끼워 argparse 배선만 확인합니다)
    """
    seen = {}

    def fake_run(universe, year, out_dir, **kwargs):
        seen.update(kwargs)
        return [], {}

    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")
    monkeypatch.setattr(cdk, "run_collection", fake_run)

    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 0
    assert seen["allow_overwrite"] is False

    seen.clear()
    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path), "--allow-overwrite"]) == 0
    assert seen["allow_overwrite"] is True


def test_cli_overwrite_guard_exits_nonzero_without_traceback(tmp_path, capsys, monkeypatch):
    """§0-3-4: 가드에 막힌 실행도 트레이스백이 아니라 사람이 읽을 문장 + 종료코드 2 로 끝납니다."""
    _write_run_output(tmp_path, [_merge_fake_record("005930")])
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["123456"]), encoding="utf-8")

    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")
    _forbid_all_network(monkeypatch)

    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "수집을 중단했습니다" in out
    assert "--allow-overwrite" in out
    assert "Traceback" not in out


# =============================================================================
# 15. KRX 6자 영숫자 종목코드 대응 (normalize_stock_code 확대 + 회사명 2차 매칭)
#
# 배경(실물 확인 — 2026-08-24, data/kr_ticker_master.json 대조):
#   type=="STOCK" 2,873건 중 **79건**의 종목코드가 순수 숫자가 아니라 '0126Z0' / '00680K'
#   / '03473K' 처럼 대문자 알파벳이 하나 섞인 **6자 영숫자**입니다. 79건 전부 길이가
#   정확히 6자이고 실재하는 상장 증권입니다(KRX 가 한 발행사의 숫자 코드 공간이 소진되면
#   쓰는 실제 표기 — 우선주에서 특히 흔합니다). 깨진 데이터가 아닙니다.
#   확대 전 `normalize_stock_code()` 는 이 79건을 전부 None 으로 떨어뜨려, DART 에
#   물어보지도 못한 채 "형식 오류"로 버리고 있었습니다.
#
# 이 절이 지키는 선:
#   · 확대는 **딱 한 형태**(정확히 6자, ^[0-9A-Z]{6}$)만입니다. 5자·7자·기호·한글은 전과
#     똑같이 None 이어야 합니다.
#   · 기존 숫자 경로(0 패딩 복원 / 7자리 이상 거부)는 **한 글자도** 달라지면 안 됩니다.
#   · 회사명 2차 매칭은 **앞뒤 공백만 제거한 완전일치**뿐입니다. 유사·부분 일치 금지(§0-1).
# =============================================================================

# ── 15-1. normalize_stock_code() 확대 ────────────────────────────────────────
def test_normalize_stock_code_accepts_real_krx_alphanumeric_codes():
    """실재하는 KRX 6자 영숫자 코드는 패딩 없이 **그대로** 통과해야 합니다."""
    assert ccm.normalize_stock_code("0126Z0") == "0126Z0"      # 삼성에피스홀딩스
    assert ccm.normalize_stock_code("00680K") == "00680K"
    assert ccm.normalize_stock_code("03473K") == "03473K"      # SK우
    assert ccm.normalize_stock_code("0030R0") == "0030R0"      # 대신밸류리츠


def test_normalize_stock_code_uppercases_alphanumeric_input():
    """소문자로 들어와도 대문자로 올려 같은 코드로 봅니다(표기 복원 — 지어내기 아님)."""
    assert ccm.normalize_stock_code("0126z0") == "0126Z0"
    assert ccm.normalize_stock_code(" 03473k ") == "03473K"


def test_normalize_stock_code_still_rejects_wrong_length_alphanumerics():
    """확대는 '정확히 6자' 한 형태뿐입니다 — 5자·7자는 전과 똑같이 None 이어야 합니다."""
    assert ccm.normalize_stock_code("0126Z") is None           # 5자
    assert ccm.normalize_stock_code("0126Z00") is None         # 7자
    assert ccm.normalize_stock_code("A005930") is None         # 7자(기존 테스트와 같은 값)


def test_normalize_stock_code_still_rejects_non_alphanumeric_characters():
    """영숫자가 아닌 문자가 하나라도 섞이면 None 입니다 — 관대해진 게 아닙니다."""
    assert ccm.normalize_stock_code("0126Z-") is None
    assert ccm.normalize_stock_code("01 6Z0") is None
    assert ccm.normalize_stock_code("0126Z_") is None
    assert ccm.normalize_stock_code("삼성전자") is None
    assert ccm.normalize_stock_code("012_Z0") is None


def test_normalize_stock_code_digit_path_is_byte_for_byte_unchanged():
    """
    §확대의 전제: **기존 숫자 경로는 하나도 안 건드렸다.**
    지금까지 이 파일과 docstring 이 보장하던 예시를 전부 한자리에 모아 고정합니다.
    """
    # 0 패딩 복원 (엑셀이 뭉갠 정수 포함)
    assert ccm.normalize_stock_code(5930) == "005930"
    assert ccm.normalize_stock_code("005930") == "005930"
    assert ccm.normalize_stock_code("5930") == "005930"
    assert ccm.normalize_stock_code("660") == "000660"
    assert ccm.normalize_stock_code("000660") == "000660"
    assert ccm.normalize_stock_code("123456") == "123456"
    # 7자리 이상 숫자는 잘라내지 않고 거부
    assert ccm.normalize_stock_code("1234567") is None
    assert ccm.normalize_stock_code(1234567) is None
    # 빈 값 / None
    assert ccm.normalize_stock_code("") is None
    assert ccm.normalize_stock_code("   ") is None
    assert ccm.normalize_stock_code(None) is None


# ── 15-2. build_corp_name_index() ────────────────────────────────────────────
NAME_INDEX_XML = """
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
 <corp_eng_name>SAMSUNG ELECTRONICS CO,.LTD</corp_eng_name>
 <stock_code>005930</stock_code><modify_date>20260401</modify_date></list>
<list><corp_code>00777777</corp_code><corp_name>대신밸류리츠</corp_name>
 <corp_eng_name>DAISHIN VALUE REIT</corp_eng_name>
 <stock_code> </stock_code><modify_date>20260601</modify_date></list>
<list><corp_code>00888888</corp_code><corp_name> </corp_name>
 <corp_eng_name>NO NAME CO</corp_eng_name>
 <stock_code>111111</stock_code><modify_date>20250101</modify_date></list>
"""


def test_build_corp_name_index_builds_exact_name_lookup():
    """(합성) 회사명 → entry 색인이 정확일치로 만들어져야 합니다."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(NAME_INDEX_XML))
    name_index, stats = ccm.build_corp_name_index(entries)
    assert name_index["삼성전자"]["corp_code"] == "00126380"
    assert name_index["대신밸류리츠"]["corp_code"] == "00777777"
    # 비슷한 이름으로는 절대 찾히지 않아야 합니다(§0-1 부분일치 금지).
    assert name_index.get("삼성") is None
    assert name_index.get("삼성전자서비스") is None


def test_build_corp_name_index_counts_entries_without_a_name():
    """corp_name 이 없는 항목은 색인에서 빠지되 **개수는 세어져야** 합니다(조용히 증발 금지)."""
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(NAME_INDEX_XML))
    name_index, stats = ccm.build_corp_name_index(entries)
    assert stats["total_entries"] == 3
    assert stats["total_named_entries"] == 2
    assert stats["named_entries"] == len(name_index) == 2
    assert stats["unnamed_entries"] == 1          # corp_name 이 공백뿐이던 00888888
    assert "00888888" not in {e["corp_code"] for e in name_index.values()}


def test_build_corp_name_index_duplicate_tiebreak_matches_stock_code_index():
    """
    동명이인 회사의 중복 처리는 `build_stock_code_index()` 와 **완전히 같은 규칙·같은 모양**
    이어야 합니다. 두 색인을 나란히 만들어 직접 대조합니다.
    """
    dup_xml = """
    <list><corp_code>00000001</corp_code><corp_name>같은이름</corp_name>
     <stock_code>123456</stock_code><modify_date>20200101</modify_date></list>
    <list><corp_code>00000002</corp_code><corp_name>같은이름</corp_name>
     <stock_code>123456</stock_code><modify_date>20260101</modify_date></list>
    """
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(dup_xml))
    code_index, code_stats = ccm.build_stock_code_index(entries)
    name_index, name_stats = ccm.build_corp_name_index(entries)

    # ① 같은 항목을 골랐는가 (최신 modify_date)
    assert code_index["123456"]["corp_code"] == "00000002"
    assert name_index["같은이름"]["corp_code"] == "00000002"

    # ② 감사 흔적의 **모양**이 같은가 (키 이름만 stock_code ↔ corp_name)
    code_dup = code_stats["duplicates"][0]
    name_dup = name_stats["duplicate_names"][0]
    assert code_dup["chosen"] == name_dup["chosen"]
    assert code_dup["dropped"] == name_dup["dropped"]
    assert code_dup["note"] == name_dup["note"]
    assert name_dup["corp_name"] == "같은이름"
    assert name_dup["dropped"][0]["corp_code"] == "00000001"


def test_build_corp_name_index_flags_ambiguous_tiebreak_like_stock_code_index():
    """modify_date 로 우열을 못 가리면 그 사실이 note 에 남아야 합니다(양쪽 동일)."""
    tie_xml = """
    <list><corp_code>00000001</corp_code><corp_name>동률회사</corp_name>
     <stock_code>222222</stock_code><modify_date>20260101</modify_date></list>
    <list><corp_code>00000002</corp_code><corp_name>동률회사</corp_name>
     <stock_code>222222</stock_code><modify_date>20260101</modify_date></list>
    """
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(tie_xml))
    _, code_stats = ccm.build_stock_code_index(entries)
    _, name_stats = ccm.build_corp_name_index(entries)
    assert "사람이 확인해야 합니다" in code_stats["duplicates"][0]["note"]
    assert code_stats["duplicates"][0]["note"] == name_stats["duplicate_names"][0]["note"]


def test_build_corp_name_index_handles_empty_input():
    """빈 입력에도 터지지 않고 빈 색인 + 0 통계를 돌려줘야 합니다."""
    name_index, stats = ccm.build_corp_name_index([])
    assert name_index == {}
    assert stats["total_entries"] == 0
    assert stats["named_entries"] == 0
    assert stats["duplicate_names"] == []


# ── 15-3. map_stock_codes() 회사명 2차 매칭 ──────────────────────────────────
# (합성) 종목코드 직접매칭이 안 되는 상황을 만들기 위한 표:
#   · 005930 삼성전자      → 종목코드 있음 (직접매칭 성공 대상)
#   · 0126Z0 삼성에피스홀딩스 → 종목코드가 6자 영숫자 그대로 실려 있음 (확대의 성과)
#   · (종목코드 없음) 대신밸류리츠 → 이름으로만 찾을 수 있음 (2차 매칭 대상)
FALLBACK_XML = """
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
 <corp_eng_name>SAMSUNG ELECTRONICS CO,.LTD</corp_eng_name>
 <stock_code>005930</stock_code><modify_date>20260401</modify_date></list>
<list><corp_code>00555555</corp_code><corp_name>삼성에피스홀딩스</corp_name>
 <corp_eng_name>SAMSUNG EPIS HOLDINGS</corp_eng_name>
 <stock_code>0126Z0</stock_code><modify_date>20260701</modify_date></list>
<list><corp_code>00777777</corp_code><corp_name>대신밸류리츠</corp_name>
 <corp_eng_name>DAISHIN VALUE REIT</corp_eng_name>
 <stock_code> </stock_code><modify_date>20260601</modify_date></list>
"""


def _fallback_indexes():
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(FALLBACK_XML))
    index, _ = ccm.build_stock_code_index(entries)
    name_index, _ = ccm.build_corp_name_index(entries)
    return index, name_index


def test_map_stock_codes_default_args_behave_exactly_as_before():
    """
    (a) 새 인자를 **안 주면** 예전과 완전히 같아야 합니다.
    기존 필드·사유 문자열을 전부 리터럴로 고정합니다. 추가된 것은 `matched_via` 하나뿐이며,
    그것을 떼어내면 예전 dict 와 글자 단위로 같아야 합니다.
    """
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(SAMPLE_XML))
    index, _ = ccm.build_stock_code_index(entries)
    mapping, unmapped = ccm.map_stock_codes(["005930", "000660", "999999", "bad!"], index)

    assert set(mapping) == {"005930", "000660"}
    # `matched_via` 를 떼면 확대 전 스키마 그대로여야 합니다.
    assert {k: v for k, v in mapping["005930"].items() if k != "matched_via"} == {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "corp_eng_name": "SAMSUNG ELECTRONICS CO,.LTD",
        "modify_date": "20260401",
    }
    # 사유 문자열도 확대 전 그대로 — 이름을 시도조차 안 했으므로 덧붙는 문장이 없어야 합니다.
    assert unmapped == [
        {"stock_code_input": "999999", "stock_code": "999999",
         "reason": "DART 고유번호 표(corpCode.xml)에 이 종목코드가 없습니다 "
                   "(상장폐지·비상장 전환·표 갱신 지연 등 가능)."},
        {"stock_code_input": "bad!", "stock_code": None,
         "reason": "종목코드를 6자리로 정규화할 수 없습니다(형식 오류)."},
    ]
    assert all("회사명" not in u["reason"] for u in unmapped)


def test_map_stock_codes_name_fallback_needs_both_arguments():
    """한쪽만 주면 2차 매칭은 켜지지 않습니다(기존 동작 유지)."""
    index, name_index = _fallback_indexes()
    code_name_map = {"0030R0": "대신밸류리츠"}
    for kwargs in ({"name_index": name_index}, {"code_name_map": code_name_map}):
        mapping, unmapped = ccm.map_stock_codes(["0030R0"], index, **kwargs)
        assert mapping == {}
        assert len(unmapped) == 1
        assert "회사명" not in unmapped[0]["reason"]


def test_map_stock_codes_format_error_is_untouched_by_name_fallback():
    """
    (b) 정규화 자체가 실패한 값은 2차 매칭이 **건드리지 않습니다.**
    코드가 무엇인지도 모르는 상태에서 이름만 보고 회사를 정하는 것은 추측입니다(§0-1).
    """
    index, name_index = _fallback_indexes()
    # 이름은 표에 분명히 있지만, 코드가 7자라 정규화 단계에서 이미 탈락합니다.
    mapping, unmapped = ccm.map_stock_codes(
        ["0126Z00"], index,
        name_index=name_index, code_name_map={"0126Z00": "삼성에피스홀딩스"})
    assert mapping == {}
    assert unmapped[0]["stock_code"] is None
    assert unmapped[0]["reason"] == "종목코드를 6자리로 정규화할 수 없습니다(형식 오류)."
    assert "회사명" not in unmapped[0]["reason"]


def test_map_stock_codes_resolves_via_name_when_stock_code_missing():
    """(c) 코드는 정규화됐지만 표에 없고, 이름이 정확히 일치하면 2차 매칭으로 살아납니다."""
    index, name_index = _fallback_indexes()
    mapping, unmapped = ccm.map_stock_codes(
        ["0030R0"], index,
        name_index=name_index, code_name_map={"0030R0": "대신밸류리츠"})
    assert unmapped == []
    assert mapping["0030R0"] == {
        "corp_code": "00777777",
        "corp_name": "대신밸류리츠",
        "corp_eng_name": "DAISHIN VALUE REIT",
        "modify_date": "20260601",
        "matched_via": "name_fallback",
    }


def test_map_stock_codes_name_fallback_strips_whitespace_only():
    """이름 정규화는 앞뒤 공백 제거 **하나뿐**입니다(가운데 공백은 그대로 의미가 있습니다)."""
    index, name_index = _fallback_indexes()
    mapping, _ = ccm.map_stock_codes(
        ["0030R0"], index,
        name_index=name_index, code_name_map={"0030R0": "  대신밸류리츠  "})
    assert mapping["0030R0"]["corp_code"] == "00777777"


def test_map_stock_codes_name_fallback_refuses_partial_matches():
    """부분일치·접두사 일치로는 절대 매칭되면 안 됩니다(§0-1 회사 매칭 추측 금지)."""
    index, name_index = _fallback_indexes()
    for wrong in ("대신밸류", "대신밸류리츠제1호", "대신 밸류리츠"):
        mapping, unmapped = ccm.map_stock_codes(
            ["0030R0"], index,
            name_index=name_index, code_name_map={"0030R0": wrong})
        assert mapping == {}, f"{wrong!r} 로 매칭되면 안 됩니다"
        assert len(unmapped) == 1


def test_map_stock_codes_reports_that_both_paths_were_tried():
    """(d) 이름으로도 못 찾으면 **두 경로를 다 시도했다는 사실**이 사유에 남아야 합니다."""
    index, name_index = _fallback_indexes()
    mapping, unmapped = ccm.map_stock_codes(
        ["0999Z9"], index,
        name_index=name_index, code_name_map={"0999Z9": "표에없는회사"})
    assert mapping == {}
    reason = unmapped[0]["reason"]
    assert unmapped[0]["stock_code"] == "0999Z9"
    assert "corpCode.xml" in reason                    # 기존 문장 유지
    assert "표에없는회사" in reason                      # 무엇으로 찾아봤는지
    assert "완전일치" in reason                          # 어떻게 찾아봤는지
    # 왜 실패했는지는 알 수 없으므로 단정하지 않습니다 — '해본 것'만 적혀 있어야 합니다.
    assert "폐지되었습니다" not in reason


def test_map_stock_codes_without_a_name_for_that_code_keeps_original_reason():
    """이름 정보가 없는 종목이면(=키가 없음) 사유가 예전 문장 그대로여야 합니다."""
    index, name_index = _fallback_indexes()
    mapping, unmapped = ccm.map_stock_codes(
        ["0999Z9"], index,
        name_index=name_index, code_name_map={"0030R0": "대신밸류리츠"})
    assert mapping == {}
    assert unmapped[0]["reason"] == ("DART 고유번호 표(corpCode.xml)에 이 종목코드가 없습니다 "
                                     "(상장폐지·비상장 전환·표 갱신 지연 등 가능).")


def test_map_stock_codes_direct_match_never_consults_name_fallback():
    """
    (e) 종목코드로 바로 찾히면 2차 매칭은 **아예 보지 않습니다.**
    증명: 그 종목의 이름을 일부러 표에 없는 값으로 줘도 직접매칭으로 살아나야 합니다.
    """
    index, name_index = _fallback_indexes()
    mapping, unmapped = ccm.map_stock_codes(
        ["005930", "0126Z0"], index,
        name_index=name_index,
        code_name_map={"005930": "존재하지않는이름", "0126Z0": "이것도아님"})
    assert unmapped == []
    assert mapping["005930"]["corp_code"] == "00126380"
    assert mapping["005930"]["matched_via"] == "stock_code"
    # 6자 영숫자 코드가 DART 표에도 같은 코드로 있으면 **확대만으로** 직접매칭됩니다(Task 1 성과).
    assert mapping["0126Z0"]["corp_code"] == "00555555"
    assert mapping["0126Z0"]["matched_via"] == "stock_code"


def test_map_stock_codes_widened_code_flows_through_dart_side_too():
    """
    확대는 **양쪽에서** 효과를 냅니다: 우리 유니버스의 '0126Z0' 뿐 아니라, DART corpCode.xml
    이 같은 형식으로 실어 보낸 stock_code 도 이제 색인에 들어갑니다.
    """
    entries = ccm.parse_corpcode_zip(_make_corpcode_zip(FALLBACK_XML))
    by_corp = {e["corp_code"]: e for e in entries}
    assert by_corp["00555555"]["stock_code"] == "0126Z0"       # 파싱 단계에서 살아남음
    assert by_corp["00555555"]["stock_code_raw"] == "0126Z0"   # 원문도 보존(§0-3-3)
    index, stats = ccm.build_stock_code_index(entries)
    assert "0126Z0" in index
    assert "0126Z0" not in stats["malformed_stock_codes"]      # 더 이상 '형식오류'가 아님


# ── 15-4. load_universe_name_map() ───────────────────────────────────────────
def test_load_universe_name_map_reads_ticker_master_shape(tmp_path):
    """(합성) data/kr_ticker_master.json 모양 — 코드 키 "code", 이름 키 "name"."""
    path = tmp_path / "u.json"
    path.write_text(json.dumps({
        "metadata": {"note": "리스트가 아닌 값은 무시돼야 합니다"},
        "stocks": [
            {"code": "005930", "name": "삼성전자", "market": "KOSPI", "type": "STOCK"},
            {"code": "0126Z0", "name": "삼성에피스홀딩스", "market": "KOSPI", "type": "STOCK"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    assert cdk.load_universe_name_map(str(path)) == {
        "005930": "삼성전자", "0126Z0": "삼성에피스홀딩스"}


def test_load_universe_name_map_reads_dividend_history_shape(tmp_path):
    """(합성) data/dividend_history_kr_2023_2025.json 모양 — "stock_code" / "company_name"."""
    path = tmp_path / "u.json"
    path.write_text(json.dumps({
        "source": "KIND",
        "records": [
            {"stock_code": "095570", "company_name": "AJ네트웍스", "fiscal_year": 2023},
            {"stock_code": "006840", "company_name": "AK홀딩스", "fiscal_year": 2023},
            # 같은 종목이 연도별로 여러 줄 있는 실제 형태 — 앞선 항목을 유지해야 합니다.
            {"stock_code": "095570", "company_name": "AJ네트웍스", "fiscal_year": 2024},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    assert cdk.load_universe_name_map(str(path)) == {
        "095570": "AJ네트웍스", "006840": "AK홀딩스"}


def test_load_universe_name_map_returns_empty_for_plain_code_list(tmp_path):
    """이름이 아예 없는 유니버스는 **오류가 아니라 정상** — 빈 dict 여야 합니다."""
    path = tmp_path / "u.json"
    path.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    assert cdk.load_universe_name_map(str(path)) == {}


def test_load_universe_name_map_skips_entries_missing_code_or_name(tmp_path):
    """코드나 이름 한쪽이 없는 항목은 그 항목만 건너뜁니다(수집을 죽이지 않습니다)."""
    path = tmp_path / "u.json"
    path.write_text(json.dumps([
        {"code": "005930", "name": "삼성전자"},
        {"code": "000660"},                 # 이름 없음
        {"name": "이름만있음"},              # 코드 없음
    ], ensure_ascii=False), encoding="utf-8")
    assert cdk.load_universe_name_map(str(path)) == {"005930": "삼성전자"}


def test_load_universe_is_unchanged_alongside_the_new_name_map(tmp_path):
    """
    `load_universe()` 는 이 작업으로 **한 글자도 달라지지 않았습니다.**
    같은 파일을 두 함수로 읽어, load_universe 쪽 반환을 리터럴로 고정합니다.
    """
    path = tmp_path / "u.json"
    path.write_text(json.dumps({
        "stocks": [
            {"code": "005930", "name": "삼성전자"},
            {"code": "0126Z0", "name": "삼성에피스홀딩스"},
            {"code": "005930", "name": "삼성전자"},        # 중복 — 순서 유지 제거
        ],
    }, ensure_ascii=False), encoding="utf-8")
    assert cdk.load_universe(str(path)) == ["005930", "0126Z0"]     # 예전과 동일
    assert cdk.load_universe_name_map(str(path)) == {
        "005930": "삼성전자", "0126Z0": "삼성에피스홀딩스"}


def test_load_universe_name_map_does_not_raise_where_load_universe_does(tmp_path):
    """
    형태 검증은 `load_universe()` 담당입니다. 이름 맵은 보조 정보라, 같은 파일에서
    조용히 빈 dict 를 돌려줄 뿐 수집을 죽이지 않아야 합니다.
    """
    path = tmp_path / "u.json"
    path.write_text(json.dumps([{"name": "삼성전자"}], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="종목코드 키를 찾지 못했습니다"):
        cdk.load_universe(str(path))                     # 기존 가드는 그대로 살아 있고
    assert cdk.load_universe_name_map(str(path)) == {}   # 이름 맵은 그냥 비어 있습니다


# ── 15-5. run_collection() 전 구간 배선 ──────────────────────────────────────
# (합성) 네 가지 경우를 한 번에 담은 DART 표:
#   005930 삼성전자          → 6자리 숫자 + 직접매칭  (기존 경로가 그대로 도는지)
#   0126Z0 삼성에피스홀딩스   → 6자 영숫자 + 직접매칭  (Task 1 확대의 성과)
#   (코드없음) 대신밸류리츠   → 이름으로만 찾힘        (Task 2·3 2차 매칭의 성과)
#   0999Z9 표에없는회사       → 둘 다 실패 → UNMAPPED (조용히 사라지지 않는지)
E2E_XML = """
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
 <corp_eng_name>SAMSUNG ELECTRONICS CO,.LTD</corp_eng_name>
 <stock_code>005930</stock_code><modify_date>20260401</modify_date></list>
<list><corp_code>00555555</corp_code><corp_name>삼성에피스홀딩스</corp_name>
 <corp_eng_name>SAMSUNG EPIS HOLDINGS</corp_eng_name>
 <stock_code>0126Z0</stock_code><modify_date>20260701</modify_date></list>
<list><corp_code>00777777</corp_code><corp_name>대신밸류리츠</corp_name>
 <corp_eng_name>DAISHIN VALUE REIT</corp_eng_name>
 <stock_code> </stock_code><modify_date>20260601</modify_date></list>
"""


@pytest.fixture
def faked_network_widened(monkeypatch):
    """`faked_network` 와 같은 방식이되 corpCode 표만 E2E_XML 로 갈아끼웁니다."""
    zip_bytes = _make_corpcode_zip(E2E_XML)
    monkeypatch.setattr(ccm, "_http_get_bytes",
                        lambda url, params, timeout, session: (200, zip_bytes))
    monkeypatch.setattr(cdk, "_http_get_json", _fake_alot_matter_response)
    monkeypatch.setattr(cdk, "polite_sleep", lambda rng=None: 0.0)
    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")


def _write_widened_universe(tmp_path):
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps({"stocks": [
        {"code": "005930", "name": "삼성전자"},              # (a) 숫자 + 직접매칭
        {"code": "0126Z0", "name": "삼성에피스홀딩스"},        # (b) 영숫자 + 직접매칭
        {"code": "0030R0", "name": "대신밸류리츠"},           # (c) 이름으로만 찾힘
        {"code": "0999Z9", "name": "표에없는회사"},           # (d) 둘 다 실패
    ]}, ensure_ascii=False), encoding="utf-8")
    return uni


def test_run_collection_resolves_widened_and_name_fallback_codes(tmp_path, faked_network_widened):
    """
    네 가지 경우가 각각 의도대로 끝나야 합니다 — 특히 (d) 가 **조용히 사라지지 않아야** 합니다.
    """
    uni = _write_widened_universe(tmp_path)
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path),
        universe_name_map=cdk.load_universe_name_map(str(uni)),
        log=lambda *a: None)

    by_code = {r["stock_code"]: r for r in records}
    assert set(by_code) == {"005930", "0126Z0", "0030R0", "0999Z9"}

    # (a)(b) 직접매칭 — 6자 영숫자도 확대만으로 그대로 수집됩니다.
    assert by_code["005930"]["corp_code"] == "00126380"
    assert by_code["005930"]["corp_code_matched_via"] == "stock_code"
    assert by_code["0126Z0"]["corp_code"] == "00555555"
    assert by_code["0126Z0"]["corp_code_matched_via"] == "stock_code"
    assert by_code["0126Z0"]["status"] == "OK"

    # (c) 회사명 2차 매칭
    assert by_code["0030R0"]["corp_code"] == "00777777"
    assert by_code["0030R0"]["corp_code_matched_via"] == "name_fallback"
    assert by_code["0030R0"]["status"] == "OK"

    # (d) 둘 다 실패 → UNMAPPED 로 **남아 있어야** 하고, 사유에 두 시도가 다 적혀야 합니다.
    assert by_code["0999Z9"]["status"] == "UNMAPPED"
    assert by_code["0999Z9"]["corp_code"] is None
    assert by_code["0999Z9"]["corp_code_matched_via"] is None
    detail = {u["stock_code"]: u["reason"] for u in summary["unmapped_detail"]}
    assert "0999Z9" in detail
    assert "corpCode.xml" in detail["0999Z9"] and "표에없는회사" in detail["0999Z9"]


def test_run_collection_reports_name_fallback_aggregates(tmp_path, faked_network_widened):
    """리포트에 2차 매칭 집계가 정확히 올라가야 합니다(unit_mismatch 집계와 같은 방식)."""
    uni = _write_widened_universe(tmp_path)
    _, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path),
        universe_name_map=cdk.load_universe_name_map(str(uni)),
        log=lambda *a: None)

    assert summary["mapped_via_name_fallback"] == 1
    assert summary["stock_codes_mapped_via_name_fallback"] == ["0030R0"]
    assert summary["name_fallback_attempted"] is True
    assert summary["name_fallback_universe_names"] == 4
    assert summary["name_fallback_index_stats"]["named_entries"] == 3
    assert summary["by_status"] == {"OK": 3, "UNMAPPED": 1}
    assert summary["unmapped_stock_codes"] == 1


def test_run_collection_targets_loop_picks_up_widened_codes_unchanged(tmp_path,
                                                                     faked_network_widened):
    """
    Task 1 의 값어치: `targets = [... normalize_stock_code(x) ... ]` 한 줄을 **건드리지 않고도**
    6자 영숫자 종목이 수집 대상에 자연스럽게 들어옵니다.
    """
    uni = _write_widened_universe(tmp_path)
    universe = cdk.load_universe(str(uni))
    records, _ = cdk.run_collection(
        universe, "2026", str(tmp_path),
        universe_name_map=cdk.load_universe_name_map(str(uni)),
        log=lambda *a: None)
    collected = {r["stock_code"] for r in records if r["status"] == "OK"}
    assert "0126Z0" in collected and "0030R0" in collected
    # run_collection 이 쓰는 그 표현식을 그대로 재현해도 같은 대상이 나와야 합니다.
    assert [c for c in (ccm.normalize_stock_code(x) for x in universe) if c] == [
        "005930", "0126Z0", "0030R0", "0999Z9"]


def test_run_collection_without_name_map_behaves_as_before(tmp_path, faked_network_widened):
    """
    이름 맵을 안 넘기면(기본) 2차 매칭은 아예 동작하지 않고, 그 사실이 리포트에 남아야
    합니다 — 0건이 '못 찾았다'로 오해되면 안 됩니다(§0-1).
    """
    uni = _write_widened_universe(tmp_path)
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=lambda *a: None)

    assert summary["name_fallback_attempted"] is False
    assert summary["mapped_via_name_fallback"] == 0
    assert summary["stock_codes_mapped_via_name_fallback"] == []
    assert summary["name_fallback_index_stats"] is None
    # 이름 없이도 확대(Task 1)만으로 0126Z0 은 여전히 직접매칭됩니다.
    by_code = {r["stock_code"]: r for r in records}
    assert by_code["0126Z0"]["status"] == "OK"
    # 반면 이름으로만 찾히던 0030R0 은 예전처럼 UNMAPPED 로 남습니다.
    assert by_code["0030R0"]["status"] == "UNMAPPED"
    assert by_code["0030R0"]["corp_code_matched_via"] is None
    assert summary["by_status"] == {"OK": 2, "UNMAPPED": 2}


def test_run_collection_logs_name_fallback_resolutions(tmp_path, faked_network_widened):
    """어느 종목이 어느 경로로 매핑됐는지 로그로 사람이 볼 수 있어야 합니다."""
    uni = _write_widened_universe(tmp_path)
    lines = []
    cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path),
        universe_name_map=cdk.load_universe_name_map(str(uni)),
        log=lines.append)
    blob = "\n".join(str(x) for x in lines)
    assert "종목코드 직접매칭" in blob
    assert "회사명" in blob and "0030R0" in blob


def test_cli_passes_universe_name_map_without_a_new_flag(tmp_path, monkeypatch):
    """
    Task 3 의 '무설정' 요구: 새 CLI 플래그 없이, 유니버스 파일에 이름이 있으면 그대로 켜집니다.
    """
    seen = {}

    def fake_run(universe, year, out_dir, **kwargs):
        seen.update(kwargs)
        return [], {}

    monkeypatch.setattr(cdk, "run_collection", fake_run)

    uni = _write_widened_universe(tmp_path)
    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 0
    assert seen["universe_name_map"]["0030R0"] == "대신밸류리츠"

    # 이름이 없는 유니버스면 빈 dict 가 넘어가고, 2차 매칭은 알아서 꺼집니다.
    seen.clear()
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(["005930"]), encoding="utf-8")
    assert cdk.main(["--universe", str(plain), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 0
    assert seen["universe_name_map"] == {}


# =============================================================================
# 16. 공시목록 감시 (list.json watch) — fetch_new_periodic_filings /
#     apply_watch_update / --watch-disclosures
#
# 배경(2026-08-24 실측): DART `list.json`("공시검색")으로 접수 몰림을 실제로 보니,
#   · 1분기보고서(3/31 기준) 접수 몰림 = 5/29
#   · 3분기보고서(9/30 기준) 접수 몰림 = 2025년 기준 11/28
# 이었습니다. 이 프로젝트가 앞서 가정한 "법정기한 = 마감 후 45일"(1분기 ~5/15) 과 실제
# 몰림 날짜 사이에 2주 가까운 차이가 있습니다(이유는 확인하지 못했고 여기서 추측하지
# 않습니다). 그래서 "마감일 근처에 전체를 다시 훑기" 대신 **매일 어제치만 가볍게 확인**
# 하는 경로를 더했습니다 — 날짜를 못 맞혀도 다음 날 잡힙니다.
#
# 여기 테스트가 못 박는 것:
#   · list.json 은 **전 페이지**를 다 돈다(정렬 순서에 기대지 않는다).
#   · status 013 은 오류가 아니라 "그 구간 0건"이다.
#   · 종목코드 없는 항목(채권만 발행한 비상장 법인 등)은 건너뛴다.
#   · 같은 종목이 여러 번 나오면 **가장 나중에 접수된(rcept_no 최대)** 것만 남긴다.
#   · apply_watch_update 는 merge_delta_output 과 **정반대로** 겹침을 교체한다 —
#     다만 조용히 덮어쓰지 않고 무엇이 무엇으로 바뀌었는지 한 줄씩 남긴다(§0-1).
#   · 실패하면 상태 파일을 갱신하지 않는다(= 그 구간을 다음 실행이 다시 확인한다).
# =============================================================================
from datetime import datetime as _dt      # noqa: E402

# 실측 응답 원문(2026-08-24, GitHub Actions 에서 실제 DART_API_KEY 로 호출).
# ⚠️ 결과가 없을 때는 `total_count` 필드 자체가 없습니다 — alotMatter 와 같은 013 관례.
REAL_LIST_NO_DATA = {"status": "013", "message": "조회된 데이타가 없습니다."}


def _filing_row(stock_code, rcept_no, report_nm="분기보고서 (2026.03)",
                corp_code="01267967", rcept_dt="20260529", corp_name="테스트회사"):
    """list.json `list` 항목 한 건(실측 응답과 같은 키 구성)."""
    return {"corp_cls": "K", "corp_name": corp_name, "corp_code": corp_code,
            "stock_code": stock_code, "report_nm": report_nm, "rcept_no": rcept_no,
            "flr_nm": corp_name, "rcept_dt": rcept_dt, "rm": ""}


def _list_page(rows, page_no=1, total_page=1, total_count=None):
    """list.json 한 페이지 응답(실측 형태 그대로)."""
    return {"status": "000", "message": "정상", "page_no": page_no,
            "page_count": 100,
            "total_count": len(rows) if total_count is None else total_count,
            "total_page": total_page, "list": list(rows)}


@pytest.fixture
def fake_list_api(monkeypatch):
    """
    list.json 만 가짜로 바꿉니다(소켓은 열지 않습니다). 반환: (calls, pages)

      pages[(detail_ty, page_no)] = 응답 dict  또는  (http_status, 응답)
      등록되지 않은 (detail_ty, page_no) 는 실측 013(0건) 응답을 돌려줍니다.
    """
    class _Calls(list):
        """호출 목록 + 딜레이 호출 횟수를 한 객체로 들고 다니기 위한 얇은 껍데기."""
        slept = None

    calls = _Calls()
    pages = {}

    def fake_get(url, params, timeout, session):
        assert url == cdk.DART_DISCLOSURE_LIST_URL
        calls.append(dict(params))
        key = (params.get("pblntf_detail_ty"), int(params.get("page_no")))
        payload = pages.get(key, REAL_LIST_NO_DATA)
        if isinstance(payload, tuple):
            return payload
        return 200, payload

    monkeypatch.setattr(cdk, "_http_get_json", fake_get)
    # §0-3-2 딜레이는 진짜로 자면 테스트가 느려지므로 호출 여부만 셉니다.
    slept = []
    monkeypatch.setattr(cdk, "polite_sleep", lambda *a, **k: slept.append(1) or 0.0)
    calls.slept = slept          # 테스트에서 같이 볼 수 있게 얹어 둡니다.
    return calls, pages


# ── 16-1. fetch_new_periodic_filings ─────────────────────────────────────────
def test_fetch_filings_reads_single_page(fake_list_api):
    """가장 단순한 경우: A003 한 페이지, 나머지 유형은 0건."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([
        _filing_row("305090", "20260529002369"),
        _filing_row("005930", "20260529002370", corp_code="00126380"),
    ])
    found = cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY",
                                           log=lambda *a: None)
    assert sorted(found) == ["005930", "305090"]
    assert found["305090"] == {"corp_code": "01267967",
                               "report_nm": "분기보고서 (2026.03)",
                               "rcept_no": "20260529002369",
                               "rcept_dt": "20260529"}


def test_fetch_filings_sends_documented_parameters(fake_list_api):
    """실측으로 확인한 파라미터를 그대로 보내야 합니다(pblntf_ty=A, page_count=100)."""
    calls, pages = fake_list_api
    cdk.fetch_new_periodic_filings("20260501", "20260531", "KEY", log=lambda *a: None)
    assert [c["pblntf_detail_ty"] for c in calls] == ["A001", "A002", "A003"]
    for call in calls:
        assert call["crtfc_key"] == "KEY"
        assert call["pblntf_ty"] == "A"
        assert call["bgn_de"] == "20260501"
        assert call["end_de"] == "20260531"
        assert call["page_count"] == "100"
        assert call["page_no"] == "1"


def test_fetch_filings_walks_every_page_not_just_the_first(fake_list_api):
    """
    ⚠️ 정렬 순서는 문서화돼 있지 않습니다 — 첫 페이지만 읽고 끝내면 조용히 놓칩니다.
    total_page 까지 page_no 를 올려가며 전부 돌아야 합니다.
    """
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("000001", "20260529000001")],
                                    page_no=1, total_page=3, total_count=3)
    pages[("A003", 2)] = _list_page([_filing_row("000002", "20260529000002")],
                                    page_no=2, total_page=3, total_count=3)
    pages[("A003", 3)] = _list_page([_filing_row("000003", "20260529000003")],
                                    page_no=3, total_page=3, total_count=3)

    found = cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY",
                                           log=lambda *a: None)
    assert sorted(found) == ["000001", "000002", "000003"]
    a003_pages = [int(c["page_no"]) for c in calls if c["pblntf_detail_ty"] == "A003"]
    assert a003_pages == [1, 2, 3]


def test_fetch_filings_treats_013_as_zero_results_not_an_error(fake_list_api):
    """013 은 실패가 아니라 '그 구간 0건' 입니다(alotMatter 와 같은 관례 — 실측)."""
    calls, pages = fake_list_api
    found = cdk.fetch_new_periodic_filings("20260101", "20260101", "KEY",
                                           log=lambda *a: None)
    assert found == {}
    # 013 이 온 유형은 다음 페이지를 더 묻지 않습니다(1페이지씩 3유형 = 3회).
    assert len(calls) == 3


def test_fetch_filings_keeps_going_after_one_detail_type_is_empty(fake_list_api):
    """한 유형이 0건이어도 나머지 유형은 계속 확인해야 합니다."""
    calls, pages = fake_list_api
    pages[("A002", 1)] = _list_page([_filing_row("005930", "20260814003699",
                                                 report_nm="반기보고서 (2026.06)")])
    found = cdk.fetch_new_periodic_filings("20260814", "20260814", "KEY",
                                           log=lambda *a: None)
    assert list(found) == ["005930"]
    assert found["005930"]["report_nm"] == "반기보고서 (2026.06)"


def test_fetch_filings_skips_rows_without_stock_code(fake_list_api):
    """
    실측: 일부 항목은 `stock_code` 가 빈 문자열입니다(채권만 발행한 비상장 법인 등).
    우리 유니버스에 있을 수 없는 회사이므로 건너뜁니다 — 지어내서 코드를 만들지 않습니다.
    """
    calls, pages = fake_list_api
    rows = [
        _filing_row("", "20260529000001", corp_name="비상장채권법인"),
        _filing_row("305090", "20260529000002"),
    ]
    rows.append({"corp_code": "00000001", "corp_name": "키자체가없음",
                 "report_nm": "분기보고서 (2026.03)", "rcept_no": "20260529000003",
                 "rcept_dt": "20260529"})            # stock_code 키 자체가 없는 경우
    pages[("A003", 1)] = _list_page(rows)

    found = cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY",
                                           log=lambda *a: None)
    assert list(found) == ["305090"]


def test_fetch_filings_reports_skipped_rows_instead_of_dropping_silently(fake_list_api):
    """§0-1: 건너뛴 건수를 로그로 남깁니다 — 조용히 사라지면 안 됩니다."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("", "20260529000001"),
                                     _filing_row("305090", "20260529000002")])
    lines = []
    cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lines.append)
    blob = "\n".join(lines)
    assert "종목코드가 없는 공시 1건" in blob


def test_fetch_filings_warns_on_unnormalizable_stock_code(fake_list_api):
    """정규화조차 안 되는 종목코드는 버리되 **크게 알립니다**(처음 보는 표기일 수 있음)."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("한글코드", "20260529000001"),
                                     _filing_row("305090", "20260529000002")])
    lines = []
    found = cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lines.append)
    assert list(found) == ["305090"]
    assert any("정규화하지 못한" in line and "한글코드" in line for line in lines)


def test_fetch_filings_keeps_latest_rcept_no_for_duplicate_stock(fake_list_api):
    """
    같은 종목이 여러 번 나오는 경우(예: "[기재정정]" 으로 같은 분기에 두 번 접수).
    DART rcept_no 는 접수순으로 증가하므로 **가장 큰 값**이 가장 최근 것입니다.
    """
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([
        _filing_row("305090", "20260529002369"),
        _filing_row("305090", "20260530001111", report_nm="[기재정정]분기보고서 (2026.03)"),
    ])
    found = cdk.fetch_new_periodic_filings("20260529", "20260531", "KEY",
                                           log=lambda *a: None)
    assert found["305090"]["rcept_no"] == "20260530001111"
    assert found["305090"]["report_nm"] == "[기재정정]분기보고서 (2026.03)"


def test_fetch_filings_dedupes_across_detail_types(fake_list_api):
    """같은 종목이 A002 와 A003 양쪽에 나와도 최신 rcept_no 하나만 남습니다."""
    calls, pages = fake_list_api
    pages[("A002", 1)] = _list_page([_filing_row("005930", "20260814003699",
                                                 report_nm="반기보고서 (2026.06)")])
    pages[("A003", 1)] = _list_page([_filing_row("005930", "20260515002181",
                                                 report_nm="분기보고서 (2026.03)")])
    found = cdk.fetch_new_periodic_filings("20260101", "20261231", "KEY",
                                           log=lambda *a: None)
    assert list(found) == ["005930"]
    assert found["005930"]["rcept_no"] == "20260814003699"


def test_fetch_filings_dedupes_across_pages(fake_list_api):
    """페이지가 갈려서 같은 종목이 두 번 나와도 최신 하나만 남습니다."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("305090", "20260529002369")],
                                    page_no=1, total_page=2, total_count=2)
    pages[("A003", 2)] = _list_page(
        [_filing_row("305090", "20260601009999", report_nm="[첨부추가]분기보고서 (2026.03)")],
        page_no=2, total_page=2, total_count=2)
    found = cdk.fetch_new_periodic_filings("20260529", "20260601", "KEY",
                                           log=lambda *a: None)
    assert found["305090"]["rcept_no"] == "20260601009999"


def test_fetch_filings_normalizes_stock_code_to_six_digits(fake_list_api):
    """유니버스 쪽과 같은 기준으로 비교할 수 있도록 6자리로 정규화해 담습니다."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("5930", "20260529000001"),
                                     _filing_row("03473k", "20260529000002")])
    found = cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY",
                                           log=lambda *a: None)
    assert sorted(found) == ["005930", "03473K"]


def test_fetch_filings_sleeps_between_requests_but_not_before_the_first(fake_list_api):
    """§0-3-2: 이 API 도 같은 DART 서버입니다 — 요청 사이에 딜레이를 둡니다."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("305090", "1")],
                                    page_no=1, total_page=2, total_count=2)
    pages[("A003", 2)] = _list_page([_filing_row("305091", "2")],
                                    page_no=2, total_page=2, total_count=2)
    cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    # 요청 4회(A001 1 + A002 1 + A003 2) → 딜레이는 그 사이 3회.
    assert len(calls) == 4
    assert len(calls.slept) == 3


def test_fetch_filings_raises_fatal_on_http_429(fake_list_api):
    """차단당하면 재시도하지 않고 실행 전체를 멈춥니다(§0-3-2)."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = (429, {"status": "020"})
    with pytest.raises(cdk.DartFatalError) as e:
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    assert "429" in str(e.value)


def test_fetch_filings_raises_fatal_on_http_403(fake_list_api):
    calls, pages = fake_list_api
    pages[("A001", 1)] = (403, None)
    with pytest.raises(cdk.DartFatalError):
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)


def test_fetch_filings_raises_fatal_on_bad_api_key(fake_list_api):
    """인증키 오류(010)는 종목 하나의 문제가 아니라 실행 전체가 못 도는 상태입니다."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = REAL_BAD_KEY
    with pytest.raises(cdk.DartFatalError) as e:
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    assert "010" in str(e.value)


def test_fetch_filings_never_leaks_api_key_in_error_message(fake_list_api):
    """§보안: 예외 메시지에 인증키가 섞이면 Actions 로그에 그대로 남습니다."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = (403, None)
    with pytest.raises(cdk.DartFatalError) as e:
        cdk.fetch_new_periodic_filings("20260529", "20260529",
                                       "SUPER-SECRET-KEY", log=lambda *a: None)
    assert "SUPER-SECRET-KEY" not in str(e.value)


def test_fetch_filings_raises_api_error_on_unknown_status(fake_list_api):
    """치명 목록에 없는 낯선 status 는 그 조회만 실패로 봅니다(조용히 0건으로 넘기지 않음)."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = {"status": "999", "message": "처음 보는 코드"}
    with pytest.raises(cdk.DartApiError) as e:
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    assert "999" in str(e.value)


def test_fetch_filings_refuses_to_guess_when_total_page_is_missing(fake_list_api):
    """
    §0-1: 몇 페이지인지 모르는 채로 1페이지만 읽고 '그 구간 다 봤다'고 기록하면
    그 구간을 영영 놓칩니다. 지어내지 않고 크게 실패합니다.
    """
    calls, pages = fake_list_api
    broken = _list_page([_filing_row("305090", "1")])
    broken.pop("total_page")
    pages[("A001", 1)] = broken
    with pytest.raises(cdk.DartApiError) as e:
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    assert "total_page" in str(e.value)


def test_fetch_filings_refuses_absurd_total_page(fake_list_api):
    """무한정 요청하지 않기 위한 상한(§0-3-2)."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = _list_page([_filing_row("305090", "1")],
                                    total_page=cdk.DART_LIST_MAX_PAGES + 1)
    with pytest.raises(cdk.DartApiError):
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)


def test_fetch_filings_raises_when_list_is_not_a_list(fake_list_api):
    """status 000 인데 list 가 리스트가 아니면 응답 규격이 바뀐 것입니다."""
    calls, pages = fake_list_api
    pages[("A001", 1)] = {"status": "000", "message": "정상", "total_page": 1,
                          "list": {"corp_code": "x"}}
    with pytest.raises(cdk.DartApiError):
        cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)


def test_fetch_filings_accepts_custom_detail_types(fake_list_api):
    """유형 목록은 인자로 좁힐 수 있습니다(기본은 A001/A002/A003)."""
    calls, pages = fake_list_api
    cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY",
                                   detail_types=("A003",), log=lambda *a: None)
    assert [c["pblntf_detail_ty"] for c in calls] == ["A003"]


def test_fetch_filings_writes_no_files(tmp_path, fake_list_api, monkeypatch):
    """순수 조회 함수입니다 — 파일을 하나도 만들지 않습니다."""
    calls, pages = fake_list_api
    pages[("A003", 1)] = _list_page([_filing_row("305090", "1")])
    monkeypatch.chdir(tmp_path)
    cdk.fetch_new_periodic_filings("20260529", "20260529", "KEY", log=lambda *a: None)
    assert list(tmp_path.iterdir()) == []


# ── 16-2. apply_watch_update ─────────────────────────────────────────────────
def _watch_record(code, reprt_code="11012", dps=100, stlm_dt="2026-06-30",
                  status="OK", corp_name=None):
    """감시 테스트용 레코드(실제 스키마의 부분집합 — 교체 판정에 쓰는 필드 포함)."""
    return {
        "stock_code": code,
        "corp_name": corp_name or f"테스트{code}",
        "bsns_year": "2026",
        "reprt_code": reprt_code,
        "reprt_name": cdk.REPRT_CODE_NAMES.get(reprt_code),
        "stlm_dt": stlm_dt,
        "dps_cash_common": dps if status == "OK" else None,
        "status": status,
        "status_reason": "" if status == "OK" else "데이터 없음",
        "parse_notes": [],
        "unknown_se_labels": [],
        "unit_mismatch_notes": [],
        "cross_source_notes": [],
    }


@pytest.fixture
def watch_dirs(tmp_path):
    """
    기존 전체 결과(2종목: 005930 반기 / 000660 1분기) + 감시 델타(005930 3분기) 한 쌍.
    ⚠️ merge_delta_output 이라면 '겹친다'며 거부할 구성입니다 — 여기서는 그게 정상입니다.
    """
    main_dir = tmp_path / "main"
    delta_dir = tmp_path / "delta"
    _write_run_output(
        main_dir,
        [_watch_record("005930", "11012", dps=746, stlm_dt="2026-06-30"),
         _watch_record("000660", "11013", dps=300, stlm_dt="2026-03-31")],
        requests_used=8, elapsed_sec=100.0, corpcode_source="cache",
        raw_entries=[_merge_raw_entry("005930"), _merge_raw_entry("000660")])
    _write_run_output(
        delta_dir,
        [_watch_record("005930", "11014", dps=1118, stlm_dt="2026-09-30")],
        requests_used=1, elapsed_sec=3.0, corpcode_source="network",
        raw_entries=[_merge_raw_entry("005930", reprt_code="11014")])
    return main_dir, delta_dir


def test_watch_update_replaces_existing_stock_instead_of_refusing(watch_dirs):
    """
    ⚠️ 여기가 merge_delta_output 과 정반대입니다: 겹치면 거부가 아니라 **교체**입니다.
    (델타는 언제나 '방금 새 보고서를 낸 회사'만 다시 돌린 결과라 늘 더 최신입니다.)
    """
    main_dir, delta_dir = watch_dirs
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)
    by_code = {r["stock_code"]: r for r in records}
    assert len(records) == 2                       # 늘지 않았습니다 — 교체입니다.
    assert by_code["005930"]["reprt_code"] == "11014"
    assert by_code["005930"]["dps_cash_common"] == 1118
    assert by_code["000660"]["dps_cash_common"] == 300     # 건드리지 않은 종목은 그대로
    assert summary["watch_replaced_stock_codes"] == ["005930"]
    assert summary["watch_added_stock_codes"] == []


def test_watch_update_same_input_would_be_refused_by_merge_delta_output(watch_dirs):
    """
    두 함수의 정책 차이를 한 테스트로 못 박습니다 — 같은 입력에 대해
    merge_delta_output 은 거부하고, apply_watch_update 는 교체합니다.
    """
    main_dir, delta_dir = watch_dirs
    with pytest.raises(ValueError) as e:
        cdk.merge_delta_output(str(main_dir), str(delta_dir), "2026",
                               force=True, log=lambda *a: None)
    assert "겹칩니다" in str(e.value)
    # 같은 입력을 감시 경로로 넣으면 정상 동작합니다.
    records, _ = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert len(records) == 2


def test_watch_update_logs_what_changed_into_what(watch_dirs):
    """§0-1: 조용히 덮어쓰지 않습니다 — 옛 보고서 → 새 보고서를 한 줄로 남깁니다."""
    main_dir, delta_dir = watch_dirs
    lines = []
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lines.append)
    blob = "\n".join(str(x) for x in lines)
    assert "종목코드 005930" in blob
    assert "반기보고서" in blob and "3분기보고서" in blob
    assert "2026-06-30" in blob and "2026-09-30" in blob
    assert "갱신" in blob


def test_watch_update_keeps_record_position_when_replacing(tmp_path):
    """교체는 **제자리에서** 일어납니다(순서가 뒤바뀌면 사람이 diff 를 못 봅니다)."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("111111"), _watch_record("222222"),
                                 _watch_record("333333")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("222222", "11014", dps=999)],
                      raw_entries=[])
    records, _ = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert [r["stock_code"] for r in records] == ["111111", "222222", "333333"]
    assert records[1]["dps_cash_common"] == 999


def test_watch_update_adds_stock_that_was_not_in_main(tmp_path):
    """유니버스에 없던 종목이 새 보고서를 냈다면 추가합니다(뒤에 붙습니다)."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("999999", "11014", dps=55)],
                      raw_entries=[])
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)
    assert [r["stock_code"] for r in records] == ["005930", "999999"]
    assert summary["watch_added_stock_codes"] == ["999999"]
    assert summary["watch_replaced_stock_codes"] == []


def test_watch_update_handles_mix_of_replaced_and_added(tmp_path):
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930"), _watch_record("000660")],
                      raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("000660", "11014", dps=777),
                                  _watch_record("123456", "11014", dps=11)],
                      raw_entries=[])
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)
    assert [r["stock_code"] for r in records] == ["005930", "000660", "123456"]
    assert summary["watch_replaced_stock_codes"] == ["000660"]
    assert summary["watch_added_stock_codes"] == ["123456"]
    assert summary["total_records"] == 3


def test_watch_update_recomputes_summary_instead_of_hand_editing(tmp_path):
    """리포트 숫자는 손으로 고치지 않고 summarize_results() 가 다시 계산합니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir,
                      [_watch_record("005930"), _watch_record("000660", status="NO_DATA")],
                      requests_used=8, elapsed_sec=100.0, raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("000660", "11014", dps=500)],
                      requests_used=2, elapsed_sec=5.0, raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    # NO_DATA 였던 종목이 OK 로 바뀌었으니 상태 집계가 실제로 다시 계산돼야 합니다.
    assert summary["by_status"] == {"OK": 2}
    assert summary["requests_used"] == 10
    assert summary["elapsed_sec"] == 105.0
    # 교체는 유니버스 크기를 바꾸지 않습니다(추가만 늘립니다).
    assert summary["universe_size"] == 2
    assert summary["bsns_year"] == "2026"
    assert summary["watch_update_performed_at_kst"]


def test_watch_update_universe_size_grows_only_by_added_stocks(tmp_path):
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930"), _watch_record("000660")],
                      raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", "11014"),
                                  _watch_record("999999", "11014")], raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["universe_size"] == 3            # 2 + 추가 1건(교체는 안 셉니다)
    assert summary["universe_size_input"] == 3


def test_watch_update_says_the_report_is_only_partially_refreshed(watch_dirs):
    """§0-1: 부분 갱신 결과를 전수 수집인 척하지 않습니다."""
    main_dir, delta_dir = watch_dirs
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert "부분 갱신" in summary["verification_status"]
    assert "watch" in summary["verification_status"]
    assert summary["watch_delta_summary"]["universe_size"] == 1


def test_watch_update_appends_raw_without_replacing_old_lines(watch_dirs):
    """raw.jsonl 은 append-only 감사 기록입니다 — 옛 응답도 그대로 남습니다."""
    main_dir, delta_dir = watch_dirs
    raw_path = main_dir / "dividend_kr_2026_raw.jsonl"
    before = raw_path.read_text(encoding="utf-8").splitlines()
    assert len(before) == 2

    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    after = raw_path.read_text(encoding="utf-8").splitlines()
    assert after[:2] == before                      # 기존 줄은 한 글자도 안 바뀝니다
    assert len(after) == 3
    assert json.loads(after[2])["reprt_code"] == "11014"


def test_watch_update_tolerates_missing_delta_raw_file(tmp_path):
    """요청이 0건이면 델타 raw 가 없을 수 있습니다 — 실패가 아니지만 로그엔 남깁니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", "11014")])   # raw 없음
    lines = []
    records, _ = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lines.append)
    assert records[0]["reprt_code"] == "11014"
    assert any("raw 파일이 없습니다" in str(x) for x in lines)


def test_watch_update_refuses_broken_delta_raw_and_writes_nothing(tmp_path):
    """검증이 끝나기 전엔 한 바이트도 쓰지 않습니다(merge_delta_output 과 같은 순서)."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")],
                      raw_entries=[_merge_raw_entry("005930")])
    _write_run_output(delta_dir, [_watch_record("005930", "11014")], raw_entries=[])
    (delta_dir / "dividend_kr_2026_raw.jsonl").write_text(
        "{이건 JSON 이 아닙니다\n", encoding="utf-8")

    before = _snapshot(str(main_dir / "dividend_kr_2026_latest.json"),
                       str(main_dir / "dividend_kr_2026_raw.jsonl"),
                       str(main_dir / "dividend_kr_2026_watch_log.json"))
    with pytest.raises(ValueError) as e:
        cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    assert "JSON 이 아닙니다" in str(e.value)
    assert _snapshot(*before) == before             # 아무것도 안 건드렸습니다


def test_watch_update_raises_when_delta_output_is_missing(tmp_path):
    """델타 산출물이 없으면 사람이 읽을 메시지로 실패합니다(호출부가 부르지 말았어야 함)."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    os.makedirs(delta_dir, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)


def test_watch_update_writes_atomically_via_tmp_then_replace(watch_dirs, monkeypatch):
    """tmp 파일에 쓰고 os.replace 로 바꿔치기합니다(중간에 깨진 파일이 남지 않도록)."""
    main_dir, delta_dir = watch_dirs
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(cdk.os, "replace", spy)
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)

    latest = str(main_dir / "dividend_kr_2026_latest.json")
    log_file = str(main_dir / "dividend_kr_2026_watch_log.json")
    assert (f"{latest}.tmp", latest) in seen
    assert (f"{log_file}.tmp", log_file) in seen
    # tmp 파일이 남아 있으면 안 됩니다.
    assert not [p for p in os.listdir(str(main_dir)) if p.endswith(".tmp")]


def test_watch_update_creates_watch_log_with_audit_fields(watch_dirs):
    """감사 로그 신설 — 언제 어느 구간을 확인해 무엇을 바꿨는지 남습니다."""
    main_dir, delta_dir = watch_dirs
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None,
                           date_range_checked="20260930~20261001",
                           matched_stock_codes=["005930"])
    log_file = main_dir / "dividend_kr_2026_watch_log.json"
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert len(data["watches"]) == 1
    entry = data["watches"][0]
    assert entry["checked_at_kst"]
    assert entry["date_range_checked"] == "20260930~20261001"
    assert entry["matched_stock_codes"] == ["005930"]
    assert entry["replaced_stock_codes"] == ["005930"]
    assert entry["added_stock_codes"] == []
    assert entry["delta_raw_lines_appended"] == 1


def test_watch_update_appends_to_existing_watch_log(watch_dirs):
    """두 번째 감시 실행은 기존 이력에 **이어붙입니다**(덮어쓰지 않습니다)."""
    main_dir, delta_dir = watch_dirs
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None,
                           date_range_checked="20261001~20261001")
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None,
                           date_range_checked="20261002~20261002")
    data = json.loads(
        (main_dir / "dividend_kr_2026_watch_log.json").read_text(encoding="utf-8"))
    assert [w["date_range_checked"] for w in data["watches"]] == [
        "20261001~20261001", "20261002~20261002"]


def test_watch_update_records_where_matched_codes_came_from(watch_dirs):
    """§0-1: 매칭 목록을 호출부가 줬는지, 델타로 대신 채웠는지 구분해 적습니다."""
    main_dir, delta_dir = watch_dirs
    cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026", log=lambda *a: None)
    entry = json.loads(
        (main_dir / "dividend_kr_2026_watch_log.json").read_text(encoding="utf-8")
    )["watches"][0]
    assert entry["matched_stock_codes"] == ["005930"]
    assert "델타 산출물" in entry["matched_stock_codes_source"]


def test_watch_update_does_not_block_an_older_report_but_shouts_about_it(tmp_path):
    """
    ⚠️ 이론상 없어야 하는 경우(새 보고서가 기존보다 더 과거).
    §0-1: 값을 임의로 지키지도 버리지도 않습니다 — **그대로 교체하되 크게 알립니다.**
    """
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir,
                      [_watch_record("005930", "11014", dps=1118, stlm_dt="2026-09-30")],
                      raw_entries=[])
    _write_run_output(delta_dir,
                      [_watch_record("005930", "11013", dps=372, stlm_dt="2026-03-31")],
                      raw_entries=[])
    lines = []
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lines.append)
    # 막지 않았습니다 — 교체는 그대로 일어납니다.
    assert records[0]["reprt_code"] == "11013"
    assert records[0]["dps_cash_common"] == 372
    assert summary["watch_replaced_stock_codes"] == ["005930"]
    # 그러나 조용히 넘어가지 않습니다.
    blob = "\n".join(str(x) for x in lines)
    assert "예상 밖" in blob and "005930" in blob and "원인 확인 필요" in blob
    assert len(summary["watch_unexpected_report_regressions"]) == 1
    entry = json.loads(
        (main_dir / "dividend_kr_2026_watch_log.json").read_text(encoding="utf-8")
    )["watches"][0]
    assert len(entry["unexpected_report_regressions"]) == 1


def test_watch_update_does_not_warn_on_normal_forward_replacement(watch_dirs):
    """정상 방향(1분기→3분기)의 교체에는 경고가 붙지 않아야 합니다(경고 인플레 방지)."""
    main_dir, delta_dir = watch_dirs
    lines = []
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lines.append)
    assert summary["watch_unexpected_report_regressions"] == []
    assert "예상 밖" not in "\n".join(str(x) for x in lines)


def test_watch_update_does_not_warn_when_report_code_is_unknown(tmp_path):
    """모르는 reprt_code 로는 앞뒤를 판정할 수 없습니다 — 넘겨짚어 경고하지 않습니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    main_rec = _watch_record("005930", "11014")
    delta_rec = _watch_record("005930", "11014")
    delta_rec["reprt_code"] = None                  # UNMAPPED/NO_DATA 레코드의 실제 모습
    _write_run_output(main_dir, [main_rec], raw_entries=[])
    _write_run_output(delta_dir, [delta_rec], raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["watch_unexpected_report_regressions"] == []


def test_watch_update_carries_over_unmapped_detail_from_both_runs(tmp_path):
    """매핑 실패 목록도 합쳐집니다 — 한쪽 것이 조용히 사라지면 안 됩니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")],
                      unmapped=[{"stock_code_input": "AAA", "reason": "형식 오류"}],
                      raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", "11014")],
                      unmapped=[{"stock_code_input": "BBB", "reason": "corp_code 없음"}],
                      raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["unmapped_stock_codes"] == 2
    assert {u["stock_code_input"] for u in summary["unmapped_detail"]} == {"AAA", "BBB"}


def test_watch_update_marks_run_incomplete_when_delta_was_cut_short(tmp_path):
    """델타가 예산 초과로 멈췄다면 그 사실이 리포트에 남아야 합니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", "11014")],
                      completed=False, stopped_reason="요청 예산 초과", raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["completed"] is False
    assert "요청 예산 초과" in summary["stopped_reason"]


def test_watch_update_keeps_delta_record_without_stock_code(tmp_path):
    """종목코드가 없는 델타 레코드는 교체 대상을 특정할 수 없습니다 — 버리지 않고 덧붙입니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    orphan = _watch_record("005930", "11014")
    orphan["stock_code"] = None
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [orphan], raw_entries=[])
    lines = []
    records, _ = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lines.append)
    assert len(records) == 2
    assert any("종목코드가 없는 레코드" in str(x) for x in lines)


# ── 16-3. --watch-disclosures CLI 모드 ───────────────────────────────────────
@pytest.fixture
def watch_cli(tmp_path, monkeypatch):
    """
    CLI 감시 모드를 소켓 없이 돌리기 위한 장치.

    반환 dict:
      universe / out_dir / cache_dir / state_path : 경로들
      filings   : fetch_new_periodic_filings 가 돌려줄 값(테스트가 채웁니다)
      run_calls / apply_calls / order : 어떤 함수가 어떤 순서로 불렸는지
    """
    monkeypatch.setenv("DART_API_KEY", "TEST-KEY")
    # 오늘을 2026-08-24(KST)로 고정합니다 — 어제는 2026-08-23.
    fixed_now = _dt(2026, 8, 24, 5, 0, 0, tzinfo=ccm.KST)
    monkeypatch.setattr(cdk, "_now_kst", lambda: fixed_now)

    out_dir = tmp_path / "data"
    cache_dir = tmp_path / "data" / "cache"
    os.makedirs(str(cache_dir), exist_ok=True)
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps(
        [{"stock_code": "005930", "company_name": "삼성전자"},
         {"stock_code": "000660", "company_name": "SK하이닉스"}]), encoding="utf-8")

    ctx = {
        "universe": str(universe),
        "out_dir": str(out_dir),
        "cache_dir": str(cache_dir),
        "state_path": str(cache_dir / "dividend_kr_2026_watch_state.json"),
        "filings": {},
        "fetch_calls": [],
        "run_calls": [],
        "apply_calls": [],
        "order": [],
        "today": fixed_now.date(),
        # 2026-08-29 재감사 H9: run_collection() 은 중단돼도 예외 없이 completed=False 인
        # summary 를 정상 반환합니다. 감시 모드 호출부가 그 값을 실제로 확인하는지 검증할 수
        # 있도록, 가짜 run_collection 이 돌려줄 summary 를 테스트가 갈아끼울 수 있게 둡니다.
        # 기본값은 '전수 완료'(예전 fake 가 돌려주던 빈 dict 는 completed 키 자체가 없어
        # 이제 '미완료'로 읽힙니다 — 성공 시나리오를 뜻하려면 명시해야 합니다).
        "run_summary": {"completed": True, "stopped_reason": None},
    }

    def fake_fetch(bgn_de, end_de, api_key, session=None, detail_types=None, log=print):
        ctx["fetch_calls"].append((bgn_de, end_de))
        ctx["order"].append("fetch")
        return dict(ctx["filings"])

    def fake_run(universe_codes, year, delta_out_dir, **kwargs):
        ctx["run_calls"].append({"universe": list(universe_codes), "year": year,
                                 "out_dir": delta_out_dir, "kwargs": kwargs})
        ctx["order"].append("run_collection")
        return [], dict(ctx["run_summary"])

    def fake_apply(main_out_dir, delta_out_dir, year, **kwargs):
        ctx["apply_calls"].append({"main": main_out_dir, "delta": delta_out_dir,
                                   "year": year, "kwargs": kwargs})
        ctx["order"].append("apply_watch_update")
        return [], {}

    monkeypatch.setattr(cdk, "fetch_new_periodic_filings", fake_fetch)
    monkeypatch.setattr(cdk, "run_collection", fake_run)
    monkeypatch.setattr(cdk, "apply_watch_update", fake_apply)
    return ctx


def _watch_argv(ctx, *extra):
    return ["--universe", ctx["universe"], "--year", "2026",
            "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
            "--watch-disclosures", *extra]


def test_cli_watch_uses_lookback_when_no_state_file(watch_cli):
    """최초 실행(상태 파일 없음) → 오늘-lookback ~ 어제 구간을 확인합니다."""
    ctx = watch_cli
    assert cdk.main(_watch_argv(ctx)) == 0
    # 기본 lookback 3일: 2026-08-21 ~ 2026-08-23(어제)
    assert ctx["fetch_calls"] == [("20260821", "20260823")]


def test_cli_watch_respects_custom_lookback_days(watch_cli):
    ctx = watch_cli
    assert cdk.main(_watch_argv(ctx, "--watch-lookback-days", "7")) == 0
    assert ctx["fetch_calls"] == [("20260817", "20260823")]


def test_cli_watch_never_includes_today(watch_cli):
    """오늘은 아직 하루가 안 끝났습니다 — 접수가 더 들어올 수 있어 제외합니다."""
    ctx = watch_cli
    cdk.main(_watch_argv(ctx))
    assert ctx["fetch_calls"][0][1] == "20260823"        # 어제까지


def test_cli_watch_continues_from_state_file(watch_cli):
    """상태 파일이 있으면 그 다음 날부터 이어서 확인합니다(같은 구간을 또 훑지 않음)."""
    ctx = watch_cli
    cdk._write_watch_state(ctx["state_path"], "20260820")
    assert cdk.main(_watch_argv(ctx)) == 0
    assert ctx["fetch_calls"] == [("20260821", "20260823")]


def test_cli_watch_skips_loudly_when_range_is_empty(watch_cli, capsys):
    """
    이미 어제까지 확인했다면 할 일이 없습니다. **조용히 끝내지 않고** 이유를 말합니다(§0-1).
    이때 상태 파일은 손대지 않습니다.
    """
    ctx = watch_cli
    cdk._write_watch_state(ctx["state_path"], "20260823")
    before = open(ctx["state_path"], "rb").read()

    assert cdk.main(_watch_argv(ctx)) == 0
    out = capsys.readouterr().out
    assert "확인할 새 구간이 없습니다" in out
    assert "20260823" in out
    assert ctx["fetch_calls"] == []                      # DART 를 부르지도 않았습니다
    assert open(ctx["state_path"], "rb").read() == before


def test_cli_watch_updates_state_even_when_nothing_matched(watch_cli, capsys):
    """
    매칭 0건이어도 '그 구간은 확인했다'는 사실은 남깁니다 — 안 그러면 다음 날 같은
    구간을 또 훑어 DART 에 헛요청을 반복합니다(§0-3-2).
    """
    ctx = watch_cli
    ctx["filings"] = {"999999": {"corp_code": "x", "report_nm": "분기보고서 (2026.06)",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    assert cdk.main(_watch_argv(ctx)) == 0
    out = capsys.readouterr().out
    assert "우리 유니버스에 해당하는 종목 없음" in out
    assert ctx["run_calls"] == []                        # 수집은 아예 안 돌립니다
    state = json.loads(open(ctx["state_path"], encoding="utf-8").read())
    assert state["last_checked_de"] == "20260823"
    assert state["updated_at_kst"]


def test_cli_watch_runs_collection_then_applies_update_in_that_order(watch_cli):
    """매칭이 있으면 run_collection → apply_watch_update 순서로 이어져야 합니다."""
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380",
                                 "report_nm": "반기보고서 (2026.06)",
                                 "rcept_no": "20260814003699", "rcept_dt": "20260814"}}
    assert cdk.main(_watch_argv(ctx)) == 0
    assert ctx["order"] == ["fetch", "run_collection", "apply_watch_update"]
    assert ctx["run_calls"][0]["universe"] == ["005930"]
    assert ctx["apply_calls"][0]["main"] == ctx["out_dir"]
    assert ctx["apply_calls"][0]["delta"] == ctx["run_calls"][0]["out_dir"]


def test_cli_watch_collects_only_matched_stocks_not_whole_universe(watch_cli):
    """이 모드의 존재 이유 — 전체 2,700종목을 다시 훑지 않습니다."""
    ctx = watch_cli
    ctx["filings"] = {"000660": {"corp_code": "00164779", "report_nm": "분기보고서",
                                 "rcept_no": "2", "rcept_dt": "20260823"},
                      "111111": {"corp_code": "z", "report_nm": "분기보고서",
                                 "rcept_no": "3", "rcept_dt": "20260823"}}
    cdk.main(_watch_argv(ctx))
    assert ctx["run_calls"][0]["universe"] == ["000660"]     # 유니버스 밖 111111 은 제외


def test_cli_watch_passes_owner_order_and_isolated_workspace(watch_cli):
    """
    오너 지시 순서(3분기→반기→1분기) 고정 + 임시 작업공간(watch_delta) + 덮어쓰기 허용.
    ⚠️ cache_dir 을 본 캐시와 분리하는 이유: 같은 폴더면 체크포인트 파일 이름이 겹쳐
       전수 수집이 남겨 둔 체크포인트를 감시 실행이 지워 버립니다(§0-3-2).
    """
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    cdk.main(_watch_argv(ctx))
    call = ctx["run_calls"][0]
    kwargs = call["kwargs"]
    assert kwargs["priority"] == cdk.REPRT_CODE_PRIORITY_OWNER_ORDER
    assert kwargs["allow_overwrite"] is True
    assert kwargs["history_baseline_path"] is None
    assert call["out_dir"] == os.path.join(ctx["cache_dir"], "watch_delta")
    assert kwargs["cache_dir"] == call["out_dir"]
    # 유니버스에 회사명이 있으면 2차 매칭도 그대로 켜집니다(새 플래그 없이).
    assert kwargs["universe_name_map"]["005930"] == "삼성전자"


def test_cli_watch_passes_universe_original_code_spelling(tmp_path, watch_cli):
    """
    유니버스 파일의 **원문 코드**를 그대로 넘겨야 회사명 2차 매칭(원문 코드 키)이 맞물립니다.
    비교만 6자리로 정규화합니다.
    """
    ctx = watch_cli
    uni = tmp_path / "int_universe.json"
    uni.write_text(json.dumps([{"stock_code": 5930, "name": "삼성전자"}]), encoding="utf-8")
    ctx["universe"] = str(uni)
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    cdk.main(_watch_argv(ctx))
    assert ctx["run_calls"][0]["universe"] == [5930]     # 정규화된 "005930" 이 아닙니다


def test_cli_watch_updates_state_after_success(watch_cli):
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    assert cdk.main(_watch_argv(ctx)) == 0
    state = json.loads(open(ctx["state_path"], encoding="utf-8").read())
    assert state["last_checked_de"] == "20260823"


def test_cli_watch_does_not_update_state_when_collection_fails(watch_cli, monkeypatch,
                                                               capsys):
    """
    §0-1: 실패했는데 '확인 끝'으로 기록하면 그 구간은 **영원히** 다시 확인되지 않습니다.
    """
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}

    def boom(*a, **k):
        raise cdk.DartFatalError("DART 가 HTTP 429 로 차단했습니다.")

    monkeypatch.setattr(cdk, "run_collection", boom)
    assert cdk.main(_watch_argv(ctx)) == 2
    assert "🛑" in capsys.readouterr().out
    assert not os.path.exists(ctx["state_path"])


def test_cli_watch_does_not_update_state_when_apply_fails(watch_cli, monkeypatch):
    """반영 단계에서 실패해도 마찬가지입니다."""
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}

    def boom(*a, **k):
        raise ValueError("델타 raw 파일이 깨졌습니다")

    monkeypatch.setattr(cdk, "apply_watch_update", boom)
    assert cdk.main(_watch_argv(ctx)) == 2
    assert not os.path.exists(ctx["state_path"])


def test_cli_watch_does_not_update_state_when_list_api_fails(watch_cli, monkeypatch):
    """공시목록 조회 자체가 실패한 경우에도 상태 파일은 그대로입니다."""
    ctx = watch_cli

    def boom(*a, **k):
        raise cdk.DartApiError("공시목록 조회 HTTP 400")

    monkeypatch.setattr(cdk, "fetch_new_periodic_filings", boom)
    assert cdk.main(_watch_argv(ctx)) == 2
    assert not os.path.exists(ctx["state_path"])


def test_cli_watch_stops_without_api_key(watch_cli, monkeypatch, capsys):
    ctx = watch_cli
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert cdk.main(_watch_argv(ctx)) == 2
    assert cdk.DART_API_KEY_ENV in capsys.readouterr().out
    assert not os.path.exists(ctx["state_path"])


def test_cli_watch_requires_universe(watch_cli):
    """watch 모드도 '우리 유니버스'를 알아야 걸러낼 수 있습니다."""
    ctx = watch_cli
    with pytest.raises(SystemExit) as e:
        cdk.main(["--year", "2026", "--out-dir", ctx["out_dir"],
                  "--watch-disclosures"])
    assert e.value.code == 2


def test_cli_watch_recovers_from_corrupt_state_file(watch_cli, capsys):
    """
    상태 파일이 깨져 '어디까지 확인했는지 모른다'면 확인한 셈 치지 않고 lookback 부터
    다시 봅니다(§0-1: 모르는 것을 안다고 넘겨짚지 않기).
    """
    ctx = watch_cli
    open(ctx["state_path"], "w", encoding="utf-8").write("{깨진 JSON")
    assert cdk.main(_watch_argv(ctx)) == 0
    assert ctx["fetch_calls"] == [("20260821", "20260823")]


def test_cli_watch_recovers_from_unparseable_last_checked_de(watch_cli, capsys):
    ctx = watch_cli
    with open(ctx["state_path"], "w", encoding="utf-8") as f:
        json.dump({"last_checked_de": "어제쯤"}, f, ensure_ascii=False)
    assert cdk.main(_watch_argv(ctx)) == 0
    assert ctx["fetch_calls"] == [("20260821", "20260823")]
    assert "날짜로 읽지 못했습니다" in capsys.readouterr().out


def test_cli_watch_never_falls_through_to_the_normal_collection_path(watch_cli):
    """
    ⚠️ 이 모드는 평소 수집 경로(유니버스 전체 run_collection)로 절대 흘러들면 안 됩니다.
    매칭 0건이면 run_collection 이 **한 번도** 불리지 않아야 합니다.
    """
    ctx = watch_cli
    assert cdk.main(_watch_argv(ctx)) == 0
    assert ctx["run_calls"] == []
    assert ctx["apply_calls"] == []


def test_cli_normal_collection_is_unaffected_by_the_new_flags(tmp_path, monkeypatch):
    """회귀: --watch-disclosures 를 안 주면 예전과 똑같이 수집 경로로 갑니다."""
    seen = {}

    def fake_run(universe, year, out_dir, **kwargs):
        seen["universe"] = list(universe)
        seen["kwargs"] = kwargs
        return [], {}

    monkeypatch.setattr(cdk, "run_collection", fake_run)
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930", "000660"]), encoding="utf-8")
    assert cdk.main(["--universe", str(uni), "--year", "2026",
                     "--out-dir", str(tmp_path)]) == 0
    assert seen["universe"] == ["005930", "000660"]
    assert "priority" in seen["kwargs"]


# ── 16-4. 감시 델타 작업공간 · 상태 파일 저수준 ───────────────────────────────
def test_watch_delta_workspace_is_reset_so_raw_is_not_double_counted(tmp_path):
    """
    ⚠️ run_collection 의 raw.jsonl 은 append 입니다. 임시 작업공간을 재사용하면서 지우지
    않으면 어제 델타의 원본 응답이 오늘 다시 본 파일에 이어붙어 **같은 응답이 두 번** 쌓입니다.
    """
    workspace = tmp_path / "watch_delta"
    os.makedirs(str(workspace))
    (workspace / "dividend_kr_2026_raw.jsonl").write_text("{}\n", encoding="utf-8")
    (workspace / "dividend_kr_2026_latest.json").write_text("{}", encoding="utf-8")
    (workspace / "dividend_kr_2026_checkpoint.json").write_text("{}", encoding="utf-8")
    (workspace / "dart_corpcode_cache.json").write_text("{}", encoding="utf-8")

    cdk._reset_watch_delta_workspace(str(workspace), str(workspace), "2026",
                                     log=lambda *a: None)
    left = sorted(p.name for p in workspace.iterdir())
    # corp_code 캐시는 남습니다(지우면 corpCode.xml 을 매일 다시 받게 됩니다 — §0-3-2).
    assert left == ["dart_corpcode_cache.json"]


def test_watch_delta_workspace_reset_is_fine_when_nothing_exists(tmp_path):
    workspace = tmp_path / "watch_delta"
    os.makedirs(str(workspace))
    cdk._reset_watch_delta_workspace(str(workspace), str(workspace), "2026",
                                     log=lambda *a: None)
    assert list(workspace.iterdir()) == []


def test_watch_delta_seeds_corpcode_cache_from_main_cache(tmp_path):
    """corpCode.xml 을 매일 다시 받지 않도록 캐시 파일만 복사합니다(읽기 전용 공유)."""
    main_cache = tmp_path / "cache"
    delta_cache = tmp_path / "cache" / "watch_delta"
    os.makedirs(str(main_cache))
    (main_cache / "dart_corpcode_cache.json").write_text('{"entries": []}',
                                                         encoding="utf-8")
    assert cdk._seed_watch_delta_corpcode_cache(str(main_cache), str(delta_cache),
                                                log=lambda *a: None) is True
    assert (delta_cache / "dart_corpcode_cache.json").read_text(
        encoding="utf-8") == '{"entries": []}'


def test_watch_delta_seed_is_a_no_op_without_a_main_cache(tmp_path):
    """캐시가 없으면 그냥 넘어갑니다(수집은 그대로 진행됩니다)."""
    main_cache = tmp_path / "cache"
    os.makedirs(str(main_cache))
    assert cdk._seed_watch_delta_corpcode_cache(
        str(main_cache), str(tmp_path / "wd"), log=lambda *a: None) is False


def test_watch_state_round_trips(tmp_path):
    path = str(tmp_path / "state.json")
    written = cdk._write_watch_state(path, "20260823")
    assert written["last_checked_de"] == "20260823"
    assert cdk._read_watch_state(path)["last_checked_de"] == "20260823"


def test_watch_state_write_is_atomic(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    seen = []
    real_replace = os.replace
    monkeypatch.setattr(cdk.os, "replace",
                        lambda s, d: (seen.append((s, d)), real_replace(s, d))[1])
    cdk._write_watch_state(path, "20260823")
    assert seen == [(f"{path}.tmp", path)]
    assert not [p for p in os.listdir(str(tmp_path)) if p.endswith(".tmp")]


def test_parse_de_refuses_to_guess(tmp_path):
    assert cdk._parse_de("20260823") == _dt(2026, 8, 23).date()
    assert cdk._parse_de("2026-08-23") is None
    assert cdk._parse_de("") is None
    assert cdk._parse_de(None) is None


def test_reprt_priority_index_says_unknown_instead_of_guessing():
    """모르는 코드를 '맨 뒤'로 취급하면 있지도 않은 '더 과거' 경고가 생깁니다."""
    assert cdk._reprt_priority_index("11011") == 0
    assert cdk._reprt_priority_index("11013") == 3
    assert cdk._reprt_priority_index("99999") is None
    assert cdk._reprt_priority_index(None) is None


# ── 16-5. 배선 검증 — CLI 한 번 실행으로 실제 파일이 갱신되는가 ────────────────
#    (여기서만 `_http_get_json` 하나만 가짜로 두고 나머지는 전부 진짜 코드로 돕니다 —
#     list.json → 유니버스 필터 → run_collection → apply_watch_update → 상태 파일까지.)
@pytest.fixture
def watch_end_to_end(tmp_path, monkeypatch):
    """소켓만 막고 나머지는 실제 경로로 도는 감시 모드 한 판."""
    monkeypatch.setenv("DART_API_KEY", "FAKE-KEY-FOR-TEST")
    monkeypatch.setattr(cdk, "polite_sleep", lambda rng=None: 0.0)
    monkeypatch.setattr(ccm, "_http_get_bytes",
                        lambda url, params, timeout, session:
                        (200, _make_corpcode_zip(SAMPLE_XML)))
    fixed_now = _dt(2026, 8, 24, 5, 0, 0, tzinfo=ccm.KST)
    monkeypatch.setattr(cdk, "_now_kst", lambda: fixed_now)

    def fake_get(url, params, timeout, session, request_counter=None):
        # ⚠️ M15(2026-08-29) — 이 fake_get 은 list.json 뿐 아니라 alotMatter 경로도
        # 대신하므로(아래), fetch_alot_matter() 가 항상 넘기는 request_counter 키워드를
        # 받아야 합니다(안 받으면 TypeError로 재시도 경로를 계속 타 테스트가 느려집니다).
        if url == cdk.DART_DISCLOSURE_LIST_URL:
            if params["pblntf_detail_ty"] != "A002":
                return 200, REAL_LIST_NO_DATA
            return 200, _list_page([
                _filing_row("005930", "20260814003699", report_nm="반기보고서 (2026.06)",
                            corp_code="00126380", rcept_dt="20260814",
                            corp_name="삼성전자"),
                _filing_row("", "20260814000001", corp_name="채권만발행법인"),
                _filing_row("999999", "20260814000002", corp_name="유니버스밖회사"),
            ])
        # alotMatter — 반기보고서(11012)만 값이 있고 나머지는 013.
        return 200, (REAL_SAMSUNG_2026_H1_PARTIAL
                     if params.get("reprt_code") == "11012" else REAL_NO_DATA)

    monkeypatch.setattr(cdk, "_http_get_json", fake_get)

    out_dir = tmp_path / "data"
    cache_dir = out_dir / "cache"
    os.makedirs(str(cache_dir), exist_ok=True)
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps(
        [{"stock_code": "005930", "company_name": "삼성전자"},
         {"stock_code": "000660", "company_name": "SK하이닉스"}]), encoding="utf-8")

    # 직전 전수 수집 결과(005930 은 1분기 값, 000660 은 무배당)를 흉내 냅니다.
    _write_run_output(
        out_dir,
        [_watch_record("005930", "11013", dps=372, stlm_dt="2026-03-31",
                       corp_name="삼성전자"),
         _watch_record("000660", status="NO_DATA", corp_name="SK하이닉스")],
        requests_used=8, elapsed_sec=100.0,
        raw_entries=[_merge_raw_entry("005930", reprt_code="11013")])

    return {"universe": str(universe), "out_dir": str(out_dir),
            "cache_dir": str(cache_dir),
            "state_path": str(cache_dir / "dividend_kr_2026_watch_state.json")}


def test_watch_end_to_end_updates_only_the_stock_that_filed(watch_end_to_end):
    """
    행복 경로 전체: list.json 이 알려 준 삼성전자만 다시 수집돼 1분기 → 반기 값으로
    바뀌고, 나머지 종목(000660)은 손대지 않습니다.
    """
    ctx = watch_end_to_end
    assert cdk.main(["--universe", ctx["universe"], "--year", "2026",
                     "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
                     "--watch-disclosures"]) == 0

    payload = json.loads(
        open(os.path.join(ctx["out_dir"], "dividend_kr_2026_latest.json"),
             encoding="utf-8").read())
    by_code = {r["stock_code"]: r for r in payload["records"]}
    assert by_code["005930"]["reprt_code"] == "11012"
    assert by_code["005930"]["dps_cash_common"] == 746        # 372 → 746 (실측 누적값)
    assert by_code["000660"]["status"] == "NO_DATA"           # 건드리지 않았습니다
    summary = payload["summary"]
    assert summary["watch_replaced_stock_codes"] == ["005930"]
    assert summary["watch_added_stock_codes"] == []
    assert "부분 갱신" in summary["verification_status"]


def test_watch_end_to_end_leaves_an_audit_trail(watch_end_to_end):
    """감사 로그·상태 파일·raw 이어붙임이 모두 남아야 합니다."""
    ctx = watch_end_to_end
    cdk.main(["--universe", ctx["universe"], "--year", "2026",
              "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
              "--watch-disclosures"])

    watch_log = json.loads(
        open(os.path.join(ctx["out_dir"], "dividend_kr_2026_watch_log.json"),
             encoding="utf-8").read())
    entry = watch_log["watches"][0]
    assert entry["date_range_checked"] == "20260821~20260823"
    assert entry["matched_stock_codes"] == ["005930"]         # 999999 는 유니버스 밖
    assert entry["replaced_stock_codes"] == ["005930"]

    state = json.loads(open(ctx["state_path"], encoding="utf-8").read())
    assert state["last_checked_de"] == "20260823"

    raw_lines = open(os.path.join(ctx["out_dir"], "dividend_kr_2026_raw.jsonl"),
                     encoding="utf-8").read().splitlines()
    assert len(raw_lines) >= 2                                # 기존 1줄 + 이번 응답
    assert json.loads(raw_lines[0])["reprt_code"] == "11013"  # 옛 줄은 그대로 남습니다


def test_watch_end_to_end_does_not_commit_workspace_into_main_outputs(watch_end_to_end):
    """임시 작업공간은 cache_dir 밑에만 생깁니다(본 산출물 폴더를 어지럽히지 않습니다)."""
    ctx = watch_end_to_end
    cdk.main(["--universe", ctx["universe"], "--year", "2026",
              "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
              "--watch-disclosures"])
    assert os.path.isdir(os.path.join(ctx["cache_dir"], "watch_delta"))
    top = sorted(p for p in os.listdir(ctx["out_dir"]) if p != "cache")
    assert top == ["dividend_kr_2026_latest.json",
                   "dividend_kr_2026_raw.jsonl",
                   "dividend_kr_2026_watch_log.json"]


def test_watch_end_to_end_second_run_same_day_does_nothing(watch_end_to_end, capsys):
    """같은 날 두 번 돌아도 DART 를 두 번 훑지 않습니다(§0-3-2)."""
    ctx = watch_end_to_end
    argv = ["--universe", ctx["universe"], "--year", "2026",
            "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
            "--watch-disclosures"]
    assert cdk.main(argv) == 0
    first = open(os.path.join(ctx["out_dir"], "dividend_kr_2026_latest.json"), "rb").read()
    capsys.readouterr()

    assert cdk.main(argv) == 0
    assert "확인할 새 구간이 없습니다" in capsys.readouterr().out
    # 산출물도 한 바이트도 안 바뀝니다(감시 이력도 늘지 않습니다).
    assert open(os.path.join(ctx["out_dir"],
                             "dividend_kr_2026_latest.json"), "rb").read() == first
    watch_log = json.loads(
        open(os.path.join(ctx["out_dir"], "dividend_kr_2026_watch_log.json"),
             encoding="utf-8").read())
    assert len(watch_log["watches"]) == 1


def test_watch_end_to_end_does_not_disturb_the_main_checkpoint(watch_end_to_end):
    """
    ⚠️ 전수 수집이 중간에 멈춰 남겨 둔 체크포인트를 감시 실행이 지우면, 다음 전수 실행이
    수천 건을 처음부터 다시 요청합니다(§0-3-2). 그래서 cache_dir 을 분리했습니다.
    """
    ctx = watch_end_to_end
    main_ckpt = os.path.join(ctx["cache_dir"], "dividend_kr_2026_checkpoint.json")
    with open(main_ckpt, "w", encoding="utf-8") as f:
        json.dump({"run_key": "2026|2734|11011", "records": [], "done_codes": [],
                   "request_count": 4200}, f)
    before = open(main_ckpt, "rb").read()

    cdk.main(["--universe", ctx["universe"], "--year", "2026",
              "--out-dir", ctx["out_dir"], "--cache-dir", ctx["cache_dir"],
              "--watch-disclosures"])
    assert os.path.exists(main_ckpt)
    assert open(main_ckpt, "rb").read() == before


# =============================================================================
# 2026-08-29 재감사 회귀 테스트 (H9 / M9 / M10 / M12)
# =============================================================================

def test_watch_does_not_advance_watermark_when_delta_run_is_incomplete(watch_cli):
    """
    H9: 델타 수집이 전수 완료되지 않았으면 상태 파일(워터마크)을 전진시키면 안 됩니다.

    run_collection() 은 중단돼도 예외 없이 completed=False 인 summary 를 정상 반환합니다.
    예전 호출부는 그 반환값을 아예 받지 않아, 반영되지 않은 공시 구간이 "확인 끝"으로
    기록되고 다음 실행이 그 구간을 다시 보지 않았습니다.
    """
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    ctx["run_summary"] = {"completed": False, "stopped_reason": "요청 한도 초과"}

    rc = cdk.main(_watch_argv(ctx))

    assert rc == 2, "부분 실패는 조용히 성공(0)하면 안 됩니다"
    assert not os.path.exists(ctx["state_path"]), "워터마크를 전진시키지 않아야 합니다"
    # 델타 자체는 이미 반영합니다(부분 성공한 종목의 최신 값은 살립니다)
    assert ctx["order"] == ["fetch", "run_collection", "apply_watch_update"]


def test_watch_advances_watermark_only_when_delta_run_completed(watch_cli):
    """H9 반대편: 전수 완료면 예전처럼 워터마크가 전진해야 합니다(회귀 방지)."""
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}
    ctx["run_summary"] = {"completed": True, "stopped_reason": None}

    assert cdk.main(_watch_argv(ctx)) == 0
    assert os.path.exists(ctx["state_path"])


def test_reaudit_shared_helpers_replace_duplicated_blocks():
    """M9: merge/watch 의 순수 배관 4종이 공통 헬퍼로 뽑혀 있어야 합니다."""
    assert callable(cdk._read_json_log)
    assert callable(cdk._read_delta_raw_lines)
    assert callable(cdk._combine_completion)
    assert callable(cdk._num_add)
    # 정책 차이(교체 vs 거부)는 각 함수에 그대로 남아 있어야 합니다 — 헬퍼로 뽑지 않았음
    src = (Path(__file__).parent.parent / "collector_dividend_kr.py").read_text(encoding="utf-8")
    assert "def merge_delta_output(" in src and "def apply_watch_update(" in src


def test_reaudit_read_json_log_shares_one_implementation(tmp_path):
    """M9-4: 키 이름만 다른 두 함수가 하나의 구현을 쓰는지."""
    missing = str(tmp_path / "nope.json")
    assert cdk._read_merge_log(missing) == {"merges": []}
    assert cdk._read_watch_log(missing) == {"watches": []}
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert cdk._read_merge_log(str(broken)) == {"merges": []}
    assert cdk._read_watch_log(str(broken)) == {"watches": []}
    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('{"merges": "not a list"}', encoding="utf-8")
    assert cdk._read_merge_log(str(wrong_shape)) == {"merges": []}


def test_reaudit_num_add_is_a_single_shared_helper():
    """M9-2: _num()/_num_add() 중복 제거 — 동작은 그대로."""
    assert cdk._num_add(1, 2) == 3
    assert cdk._num_add(1.5, 2) == 3.5
    assert cdk._num_add(None, 2) is None
    assert cdk._num_add(True, 2) is None, "bool 은 더하지 않습니다"
    assert cdk._num_add(1, "x") is None


def test_reaudit_combine_completion_keeps_per_function_labels():
    """M9-3: 사유 문자열의 델타 라벨은 호출부가 정합니다(merge/watch 문구 유지)."""
    ok, reason = cdk._combine_completion({"completed": True}, {"completed": True}, "델타 실행")
    assert ok is True and reason is None
    ok, reason = cdk._combine_completion(
        {"completed": True}, {"completed": False, "stopped_reason": "차단"}, "감시 델타")
    assert ok is False and "감시 델타 미완료(차단)" in reason
    ok, reason = cdk._combine_completion(
        {"completed": False}, {"completed": False}, "델타 실행")
    assert "기존 실행 미완료(사유 미기록)" in reason and "델타 실행 미완료(사유 미기록)" in reason


def test_reaudit_all_kind_specific_unspecified_fields_reach_the_record():
    """M10: 4쌍 중 1개만 산출물에 실리던 것을 전부 싣습니다."""
    parsed = {f"{m}_unspecified": f"v-{m}" for m in cdk._KIND_SPECIFIC_METRICS}
    parsed.update({f"{m}_unspecified_all": [f"v-{m}"] for m in cdk._KIND_SPECIFIC_METRICS})
    record = cdk.build_dividend_record(
        stock_code="005930", corp_info={"corp_code": "00126380"}, bsns_year=2026,
        reprt_code="11012", payload={}, parsed_now=parsed,
        parsed_prev=None, parsed_prev2=None, status="OK", status_reason="")
    for metric in cdk._KIND_SPECIFIC_METRICS:
        assert record[f"{metric}_unspecified"] == f"v-{metric}", metric
        assert record[f"{metric}_unspecified_all"] == [f"v-{metric}"], metric


def test_reaudit_plausible_reprt_codes_uses_kst_not_utc(monkeypatch):
    """M12: 제출기한 판정 기준일이 KST 여야 합니다(UTC 러너에서 하루 밀림 방지)."""
    src = (Path(__file__).parent.parent / "collector_dividend_kr.py").read_text(encoding="utf-8")
    body = src[src.index("def plausible_reprt_codes("):]
    body = body[:body.index("\ndef ", 10)]
    # 주석에는 "예전엔 date.today() 였다"는 기록이 남아 있으므로 코드 줄만 봅니다.
    code_only = "\n".join(ln for ln in body.split("\n") if not ln.strip().startswith("#"))
    assert "date.today()" not in code_only
    assert "_now_kst().date()" in code_only

    # KST 로 계산되는지 실제 확인: _now_kst 를 갈아끼우면 결과가 바뀌어야 합니다.
    import datetime as _dt
    calls = {"n": 0}

    class _Fake:
        @staticmethod
        def date():
            calls["n"] += 1
            return _dt.date(2026, 1, 1)

    monkeypatch.setattr(cdk, "_now_kst", lambda: _Fake)
    cdk.plausible_reprt_codes(2026, priority=cdk.REPRT_CODE_PRIORITY)
    assert calls["n"] == 1, "_now_kst() 로 기준일을 받아야 합니다"


# =============================================================================
# 2026-08-29 재감사 회귀 테스트 — corp_code_mapper.py (L14)
# =============================================================================

def test_reaudit_parse_corpcode_zip_reports_invalid_entry_count():
    """L14: corp_code 가 없어 버린 항목 수를 통계로 돌려줍니다."""
    xml = ("<result>"
           "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
           "<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>"
           "<list><corp_name>코드없는회사</corp_name><stock_code>000000</stock_code></list>"
           "<list><corp_name>또다른코드없는회사</corp_name></list>"
           "</result>")
    zip_bytes = _make_corpcode_zip(xml)

    # 하위 호환: 기본 호출은 예전과 똑같이 리스트만 돌려줍니다.
    entries = ccm.parse_corpcode_zip(zip_bytes)
    assert isinstance(entries, list)
    assert len(entries) == 1

    entries2, stats = ccm.parse_corpcode_zip(zip_bytes, return_stats=True)
    assert entries2 == entries
    assert stats["total_list_nodes"] == 3
    assert stats["invalid_entries"] == 2, "버린 항목 수가 통계에 실려야 합니다"


def test_reaudit_invalid_entry_count_reaches_get_corp_code_index_stats(tmp_path, monkeypatch):
    """L14: 그 값이 get_corp_code_index() 의 info['stats'] 와 요약 로그까지 도달해야 합니다."""
    xml = ("<result>"
           "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
           "<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>"
           "<list><corp_name>코드없는회사</corp_name></list>"
           "</result>")
    zip_bytes = _make_corpcode_zip(xml)
    monkeypatch.setattr(ccm, "download_corpcode_zip", lambda **kw: zip_bytes)

    lines = []
    _index, info = ccm.get_corp_code_index(
        str(tmp_path / "cache.json"), api_key="K", force_refresh=True, log=lines.append)

    assert info["stats"]["invalid_entries"] == 1
    assert info["stats"]["total_list_nodes"] == 2
    assert any("corp_code 가 없어 제외한" in ln for ln in lines), "요약 로그에 한 줄 남아야 합니다"


# =============================================================================
# 2026-08-29 재감사 회귀 테스트 — probe_indicator_universe_timing.py (L1)
# =============================================================================

def test_reaudit_probe_dead_fail_codes_removed():
    """L1: 아무 데서도 쓰이지 않던 fail_codes 지역변수는 삭제되어야 합니다."""
    src = (Path(__file__).parent.parent
           / "probe_indicator_universe_timing.py").read_text(encoding="utf-8")
    code_only = "\n".join(ln for ln in src.split("\n") if not ln.strip().startswith("#"))
    assert "fail_codes" not in code_only


# =============================================================================
# 🔴 M8(2026-08-29) 회귀 테스트 — out_dir 배타 락 (동시 실행 방지)
# =============================================================================
def test_locked_output_dir_basic_acquire_and_release(tmp_path):
    lock_path = tmp_path / ".collector_dividend_kr.lock"
    with cdk._locked_output_dir(str(tmp_path)):
        assert lock_path.exists()
    assert not lock_path.exists()  # 정상 종료 시 락 파일을 지웁니다.


def test_locked_output_dir_rejects_concurrent_acquire(tmp_path):
    with cdk._locked_output_dir(str(tmp_path)):
        with pytest.raises(RuntimeError, match="다른 실행이 이미"):
            with cdk._locked_output_dir(str(tmp_path)):
                pass  # pragma: no cover — 여기 들어오면 락이 동작하지 않는 것


def test_locked_output_dir_releases_even_when_body_raises(tmp_path):
    lock_path = tmp_path / ".collector_dividend_kr.lock"

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with cdk._locked_output_dir(str(tmp_path)):
            raise _Boom("작업 중 실패")
    assert not lock_path.exists()  # 예외로 빠져나가도 락은 풀려야 다음 실행이 막히지 않음


def test_locked_output_dir_steals_stale_lock(tmp_path):
    lock_path = tmp_path / ".collector_dividend_kr.lock"
    lock_path.write_text("pid=99999 started=옛날\n", encoding="utf-8")
    stale_mtime = time.time() - cdk._STALE_LOCK_SECONDS - 60
    os.utime(str(lock_path), (stale_mtime, stale_mtime))
    with cdk._locked_output_dir(str(tmp_path)):
        assert lock_path.exists()  # 죽은 락을 지우고 자기 락을 새로 잡음


def test_locked_output_dir_does_not_steal_a_fresh_lock(tmp_path):
    with cdk._locked_output_dir(str(tmp_path)):
        with pytest.raises(RuntimeError):
            with cdk._locked_output_dir(str(tmp_path)):
                pass  # pragma: no cover


def test_main_exits_with_code_2_when_out_dir_is_already_locked(tmp_path):
    """🔴 main() CLI 진입점 통합 검증 — 락을 못 잡으면 실제 수집을 시도조차 하지 않고
    종료코드 2(§0-3-4 관례)로 끝나야 합니다."""
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(json.dumps(["005930"]), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with cdk._locked_output_dir(str(out_dir)):
        rc = cdk.main([
            "--universe", str(universe_path), "--year", "2026",
            "--out-dir", str(out_dir),
        ])
    assert rc == 2


# =============================================================================
# 🔴 2026-08-29 재감사 회귀 테스트 — 이번 세션이 고친 나머지 항목들
# (H1/L6/L7/M11/M12/M15 — 지금까지는 코드에만 반영되고 전용 테스트가 없었습니다)
# =============================================================================
def test_watch_update_skips_replacing_when_delta_status_is_not_ok(tmp_path):
    """🔴 H1(2026-08-29) — 델타가 OK 가 아니면(예: 일시적 DART 오류로 ERROR) 그 값으로
    기존 OK 레코드를 덮어쓰면 안 됩니다. 기존 값을 지키고, 건너뛴 사실을 남깁니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930", dps=746, stlm_dt="2026-06-30")],
                      raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", status="ERROR")], raw_entries=[])
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)
    by_code = {r["stock_code"]: r for r in records}
    assert by_code["005930"]["dps_cash_common"] == 746     # 기존 OK 값을 그대로 지킴
    assert by_code["005930"]["status"] == "OK"
    assert summary["watch_replaced_stock_codes"] == []
    assert summary["watch_skipped_replacements"] == [
        {"stock_code": "005930", "kept_status": "OK", "delta_status": "ERROR",
         "delta_status_reason": "데이터 없음"},
    ]


def test_watch_update_still_adds_a_brand_new_stock_even_if_its_status_is_error(tmp_path):
    """이전에 없던 종목이면 '교체'가 아니라 '추가'라 위 방어와는 다른 상황입니다 — 덮어쓸
    기존 레코드가 없으므로 그대로 추가되고, status=ERROR 라는 사실도 감춰지지 않습니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("999999", status="ERROR")], raw_entries=[])
    records, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                              log=lambda *a: None)
    by_code = {r["stock_code"]: r for r in records}
    assert by_code["999999"]["status"] == "ERROR"
    assert summary["watch_added_stock_codes"] == ["999999"]
    assert summary["watch_skipped_replacements"] == []


def test_cli_watch_does_not_advance_watermark_when_a_delta_record_is_error(
        watch_cli, monkeypatch, capsys):
    """🔴 H1(2026-08-29) — apply_watch_update() 가 ERROR 델타로 기존 값을 안 덮어써도,
    상태 파일(last_checked_de)이 전진해 버리면 다음 실행이 이 구간을 다시 안 보고 그
    종목은 영원히 재시도되지 않습니다. CLI 통합 레벨에서 이걸 막는지 확인합니다."""
    ctx = watch_cli
    ctx["filings"] = {"005930": {"corp_code": "00126380", "report_nm": "반기보고서",
                                 "rcept_no": "1", "rcept_dt": "20260823"}}

    def fake_run_with_error(universe_codes, year, delta_out_dir, **kwargs):
        return ([{"stock_code": "005930", "status": "ERROR"}],
                {"completed": True, "stopped_reason": None})

    monkeypatch.setattr(cdk, "run_collection", fake_run_with_error)
    rc = cdk.main(_watch_argv(ctx))
    assert rc == 2
    out = capsys.readouterr().out
    assert "005930" in out and "ERROR" in out
    assert not os.path.exists(ctx["state_path"])   # 워터마크가 전진하지 않았어야 함


def test_cli_watch_passes_outside_universe_codes_to_apply_watch_update(watch_cli):
    """🔴 M11(2026-08-29) — 유니버스 밖 종목(신규 배당회사 등)이 공시를 냈다는 사실도
    apply_watch_update 에 전달돼야 merged summary 에 남습니다."""
    ctx = watch_cli
    ctx["filings"] = {
        "000660": {"corp_code": "00164779", "report_nm": "분기보고서",
                  "rcept_no": "2", "rcept_dt": "20260823"},
        "999999": {"corp_code": "z", "report_nm": "분기보고서",
                  "rcept_no": "3", "rcept_dt": "20260823"},
    }
    cdk.main(_watch_argv(ctx))
    assert ctx["apply_calls"][0]["kwargs"]["outside_universe_codes"] == ["999999"]


def test_apply_watch_update_records_outside_universe_codes_in_summary(tmp_path):
    """🔴 M11(2026-08-29) — `apply_watch_update()` 자체(CLI 를 거치지 않고)가 이 인자를
    받아 summary 에 그대로 남기는지."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("005930")], raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("005930", "11014")], raw_entries=[])
    _, summary = cdk.apply_watch_update(
        str(main_dir), str(delta_dir), "2026", log=lambda *a: None,
        outside_universe_codes=["777777", "888888"])
    assert summary["watch_filings_outside_universe"] == ["777777", "888888"]


def test_watch_update_dedupes_unmapped_detail_when_same_code_appears_in_both(tmp_path):
    """🔴 M12(2026-08-29) — 감시 델타 유니버스는 기존 유니버스의 부분집합이라, 같은
    종목이 기존·델타 양쪽 unmapped_detail 에 함께 들어올 수 있습니다. dedupe 안 하면
    레코드는 1건(교체)인데 unmapped_detail 은 2건이 되어 숫자가 어긋납니다. 델타 쪽
    (최신)이 이겨야 합니다."""
    main_dir, delta_dir = tmp_path / "m", tmp_path / "d"
    _write_run_output(main_dir, [_watch_record("111111")],
                      unmapped=[{"stock_code": "999999", "stock_code_input": "999999",
                                 "reason": "기존: corp_code 없음"}],
                      raw_entries=[])
    _write_run_output(delta_dir, [_watch_record("111111", "11014")],
                      unmapped=[{"stock_code": "999999", "stock_code_input": "999999",
                                 "reason": "델타: 여전히 없음"}],
                      raw_entries=[])
    _, summary = cdk.apply_watch_update(str(main_dir), str(delta_dir), "2026",
                                        log=lambda *a: None)
    assert summary["unmapped_stock_codes"] == 1        # 2건이 아니라 1건으로 합쳐짐
    assert len(summary["unmapped_detail"]) == 1
    assert summary["unmapped_detail"][0]["reason"] == "델타: 여전히 없음"   # 델타가 이김


def test_request_counter_counts_every_http_attempt_including_retries(monkeypatch):
    """🔴 M15(2026-08-29) — 예산(request_counter)은 재시도까지 포함해 **실제 나간 HTTP
    요청 수**를 세야 합니다. 함수 호출 1회를 1건으로 세면(예전 방식) 재시도 시 실제
    트래픽을 과소집계해 max_requests 예산을 넘길 수 있습니다."""
    calls = {"n": 0}

    class _FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _FakeSession:
        def get(self, url, params, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(503, None)       # 첫 시도는 서버 오류
            return _FakeResponse(200, REAL_SAMSUNG_2026_Q1)   # 재시도는 성공

    monkeypatch.setattr(cdk.time, "sleep", lambda *_: None)
    counter = {"count": 0}
    cdk.fetch_alot_matter("00126380", "2026", "11013", "KEY",
                          session=_FakeSession(), request_counter=counter)
    assert calls["n"] == 2               # 실제 HTTP 요청 2건(실패 1 + 재시도 성공 1)
    assert counter["count"] == 2         # request_counter 가 재시도까지 포함해 세었는가


def test_run_collection_dedupes_universe_entries_that_normalize_to_same_code(
        tmp_path, faked_network, capsys):
    """🟡 L6(2026-08-29) — 유니버스에 "5930"과 "005930"이 함께 있으면 둘 다 같은 종목으로
    정규화되는데, dedupe 하지 않으면 같은 종목을 두 번 조회하고 레코드도 2건 남습니다."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["5930", "005930"]), encoding="utf-8")
    records, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=print)
    assert len([r for r in records if r["stock_code"] == "005930"]) == 1
    assert summary["requests_used"] == 4     # 1종목분(우선순위 4단계)만 — 2배가 아님
    out = capsys.readouterr().out
    assert "중복 등록" in out


def test_save_checkpoint_returns_false_and_counts_failure_on_write_error(tmp_path):
    """🟡 L7(2026-08-29) — 저장 실패는 로그 한 줄로 끝나면 안 되고, False 를 돌려주고
    failure_counter 에 세어져야 리포트(summary)에 반영될 수 있습니다."""
    counter = {"count": 0}
    # tmp_path(디렉터리) 자체를 파일 경로로 주면 os.replace() 단계에서 확실히 실패합니다.
    ok = cdk.save_checkpoint(str(tmp_path), "run1", [], [], 0, failure_counter=counter)
    assert ok is False
    assert counter["count"] == 1


def test_save_checkpoint_succeeds_and_returns_true_without_a_counter(tmp_path):
    """failure_counter 를 안 줘도(하위 호환) 정상 저장은 그대로 True 를 돌려줍니다."""
    path = tmp_path / "ckpt.json"
    assert cdk.save_checkpoint(str(path), "run1", [], [], 0) is True
    assert path.exists()


def test_append_raw_returns_false_and_counts_failure_on_write_error(tmp_path):
    counter = {"count": 0}
    ok = cdk.append_raw(str(tmp_path), {"a": 1}, failure_counter=counter)
    assert ok is False
    assert counter["count"] == 1


def test_append_raw_succeeds_and_returns_true_without_a_counter(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    assert cdk.append_raw(str(raw_path), {"a": 1}) is True
    assert raw_path.exists()


def test_run_collection_reports_write_failures_in_summary(tmp_path, faked_network, monkeypatch):
    """🟡 L7(2026-08-29) 통합 — run_collection() 전체를 통해서도 raw 쓰기 실패가
    summary 에 반영되는지(호출부가 실제로 raw_write_failure_counter 를 넘기고 있는지)."""
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps(["005930"]), encoding="utf-8")

    real_append_raw = cdk.append_raw

    def failing_append_raw(raw_path, entry, failure_counter=None):
        if failure_counter is not None:
            failure_counter["count"] += 1
        return False   # 실제로 쓰지는 않되, 실패로 표시만 함(다른 산출물은 그대로 진행)

    monkeypatch.setattr(cdk, "append_raw", failing_append_raw)
    _, summary = cdk.run_collection(
        cdk.load_universe(str(uni)), "2026", str(tmp_path), log=lambda *a: None)
    assert summary["raw_write_failures"] > 0
