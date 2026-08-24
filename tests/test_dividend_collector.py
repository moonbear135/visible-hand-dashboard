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

    def counting(url, params, timeout, session):
        calls["n"] += 1
        return inner(url, params, timeout, session)

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
