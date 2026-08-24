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
   실통신 검증은 GitHub Actions 첫 실행 로그로만 가능합니다(README_상황보고.md 참고).
"""
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

    def fake_get(url, params, timeout, session):
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
                        lambda url, params, timeout, session:
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
@pytest.fixture
def faked_network(monkeypatch):
    """corpCode ZIP 과 alotMatter 응답을 전부 가짜로 갈아끼웁니다(딜레이도 0으로)."""
    zip_bytes = _make_corpcode_zip(SAMPLE_XML)
    monkeypatch.setattr(ccm, "_http_get_bytes",
                        lambda url, params, timeout, session: (200, zip_bytes))
    monkeypatch.setattr(cdk, "_http_get_json",
                        lambda url, params, timeout, session:
                        (200, REAL_SAMSUNG_2026_Q1 if params["reprt_code"] == "11013"
                         else REAL_NO_DATA))
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
