"""
tests/test_portfolio_money_coverage.py
**사용자의 실제 자산 숫자를 화면 문자열로 바꾸거나, 그 숫자를 만들기 전에 입력을 막아서는
"마지막 방어선" 함수들**의 오프라인 회귀 테스트.

⚠️ 왜 이 파일이 생겼나 (2026-08-30, 커버리지 실측)
   `coverage run -m pytest` 로 재보니, 아래 함수들은 **정상 경로만 실행되고 방어 분기는
   한 번도 실행되지 않고 있었습니다.** 전부 "값이 이상할 때 조용히 그럴듯한 숫자를 만들지
   않기"(§0-1)를 담당하는 코드라, 안 도는 방어선은 없는 방어선과 같습니다.

     · `utils/scorecard_db.py`  format_amount(소수 자릿수 지정) · `_positive_number`의
                                유한성 검사 · weighted_average_price/merge 의 거절 경로
     · `utils/report_db.py`     benchmark_period_return(시작 종가 0 이하) ·
                                compare_holding_total(숫자 아님) · 비중 분모 없음
     · `utils/duel_rules.py`    `_require_number`/`_require_int`/`_to_date`/`_to_kst` 의
                                거절 경로(= "없는 값을 0 으로 메우지 않는다"의 실체)
     · `utils/duel_batch.py`    judge_crawl_freshness 의 입력 가드 2종
     · `utils/expiry_alarms.py` 경고 본문 전체(만료가 아직 멀어 한 번도 안 찍힘)

관례: `tests/test_data_sanity.py` 와 같이 순수 `assert` 만 씁니다. 네트워크·Supabase 불필요이고
저장소 파일도 읽기만 합니다.

실행: python -m pytest tests/test_portfolio_money_coverage.py -v
"""
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import constants as C
from utils import duel_batch
from utils import duel_rules
from utils import expiry_alarms
from utils import report_db as R
from utils import scorecard_db as SC


# =====================================================================================
# 1. 금액 표기 — 화면에 찍히는 문자열 그 자체
# =====================================================================================
def test_krw_amount_matches_the_owners_worked_example():
    """
    오너 마인드맵 예시: 10주 100만원 + 3주 21만원 → 13주 1,210,000원 → 평균 93,076.923…원.
    화면 표기는 **내림**이라 93,076원이어야 합니다(계산은 전체 정밀도로, 내림은 표시에서만).
    """
    lots = [SC.make_lot("KR", "005930", 10, 100_000), SC.make_lot("KR", "005930", 3, 70_000)]
    total_qty, avg_price, total_cost = SC.weighted_average_price(lots)
    assert (total_qty, total_cost) == (13.0, 1_210_000.0)
    assert avg_price == pytest.approx(1_210_000 / 13)
    assert SC.format_amount(avg_price, "KRW") == "93,076원"


def test_krw_rounds_down_toward_zero_on_both_signs():
    assert SC.format_amount(93_076.923, "KRW") == "93,076원"
    assert SC.format_amount(-93_076.923, "KRW") == "-93,076원"   # -93,077 로 더 깎지 않음
    assert SC.format_amount(0, "KRW") == "0원"


def test_krw_with_explicit_decimals_keeps_the_fraction_instead_of_flooring():
    assert SC.format_amount(93_076.923, "KRW", decimals=2) == "93,076.92원"
    assert SC.format_amount(1_210_000 / 13, "KRW", decimals=4) == "93,076.9231원"


def test_usd_defaults_to_two_decimals_and_honours_an_override():
    assert SC.format_amount(1_234.567, "USD") == "$1,234.57"
    assert SC.format_amount(1_234.567, "USD", decimals=4) == "$1,234.5670"


def test_unreadable_amounts_render_as_a_dash_not_as_zero():
    """§0-1: 값을 못 읽었으면 '0원'이 아니라 '—' 여야 합니다(0원은 거짓말입니다)."""
    assert SC.format_amount(None, "KRW") == "—"
    assert SC.format_amount("", "KRW") == "—"
    assert SC.format_amount("숫자아님", "USD") == "—"
    assert SC.format_amount([1, 2], "KRW") == "—"


# =====================================================================================
# 2. 로트 입력 검증 — 잘못된 값 하나가 평균단가 전체를 오염시키지 않게
# =====================================================================================
def test_non_finite_quantities_and_prices_are_rejected():
    """NaN/무한대는 float() 를 통과하므로 별도 유한성 검사가 살아 있어야 합니다."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="유효한 숫자가 아닙니다"):
            SC.make_lot("KR", "005930", bad, 1_000)
        with pytest.raises(ValueError, match="유효한 숫자가 아닙니다"):
            SC.make_lot("KR", "005930", 10, bad)


def test_non_numeric_quantity_is_rejected_with_a_readable_message():
    with pytest.raises(ValueError, match="수량이\\(가\\) 숫자가 아닙니다"):
        SC.make_lot("KR", "005930", "열주", 1_000)


def test_zero_quantity_and_negative_price_are_rejected():
    with pytest.raises(ValueError, match="수량은 0보다 커야 합니다"):
        SC.make_lot("KR", "005930", 0, 1_000)
    with pytest.raises(ValueError, match="매입가는 0 이상이어야 합니다"):
        SC.make_lot("KR", "005930", 10, -1)


def test_ticker_normalisation_restores_leading_zeros_and_keeps_alphanumeric_codes():
    assert SC.make_lot("KR", "5930", 1, 100)["ticker"] == "005930"
    assert SC.make_lot("KR", "00680K", 1, 100)["ticker"] == "00680K"   # 신형우선주 실측 코드
    assert SC.make_lot("us", " brk.b ", 1, 100)["ticker"] == "BRK.B"
    with pytest.raises(ValueError, match="한국 종목코드는 6자리"):
        SC.make_lot("KR", "0059301", 1, 100)


def test_currency_is_derived_from_the_market_not_supplied_by_the_caller():
    assert SC.make_lot("KR", "005930", 1, 100)["currency"] == SC.CURRENCY_KRW
    assert SC.make_lot("US", "AAPL", 1, 100)["currency"] == "USD"
    with pytest.raises(ValueError, match="알 수 없는 시장 코드"):
        SC.make_lot("JP", "7203", 1, 100)


def test_weighted_average_refuses_to_mix_currencies_or_to_average_nothing():
    kr = SC.make_lot("KR", "005930", 1, 100)
    us = SC.make_lot("US", "AAPL", 1, 100)
    with pytest.raises(ValueError, match="환율 변환 금지"):
        SC.weighted_average_price([kr, us])
    with pytest.raises(ValueError, match="계산할 입력\\(로트\\)이 없습니다"):
        SC.weighted_average_price([])


def test_weighted_average_rejects_a_non_positive_quantity_inside_a_lot():
    """make_lot 을 거치지 않고 DB 에서 바로 온 손상 행도 여기서 막혀야 합니다."""
    broken = {"market": "KR", "ticker": "005930", "quantity": -1,
              "avg_purchase_price": 100, "currency": "KRW"}
    with pytest.raises(ValueError, match="수량은 0보다 커야 합니다"):
        SC.weighted_average_price([broken])


def test_merging_a_lot_keeps_the_existing_name_and_refuses_a_different_stock():
    existing = SC.make_lot("KR", "5930", 10, 100_000, "삼성전자")
    added = SC.make_lot("KR", "005930", 3, 70_000)
    merged = SC.merge_lot_into_holding(existing, added)
    assert merged["quantity"] == 13.0
    assert merged["avg_purchase_price"] == pytest.approx(1_210_000 / 13)
    assert merged["stock_name"] == "삼성전자"          # 기존 이름 유지
    assert SC.merge_lot_into_holding(None, added) == added   # 첫 행은 그대로
    with pytest.raises(ValueError, match="다른 종목끼리는 합칠 수 없습니다"):
        SC.merge_lot_into_holding(existing, SC.make_lot("KR", "000660", 1, 1_000))


# =====================================================================================
# 3. 벤치마크 비교 — 없는 날짜를 가까운 날로 밀어 맞추지 않기
# =====================================================================================
def test_benchmark_return_is_computed_only_on_the_exact_two_dates():
    result = R.benchmark_period_return(
        {"2026-01-02": 2_500.0, "2026-01-09": 2_600.0}, date(2026, 1, 2), date(2026, 1, 9))
    assert result["available"] is True
    assert result["change_pct"] == pytest.approx(4.0)
    assert (result["start_value"], result["end_value"]) == (2_500.0, 2_600.0)


def test_benchmark_return_says_why_it_could_not_compare():
    empty = R.benchmark_period_return({}, date(2026, 1, 2), date(2026, 1, 9))
    assert empty["available"] is False and "수집되지 않았습니다" in empty["reason"]

    missing = R.benchmark_period_return(
        {"2026-01-02": 2_500.0}, date(2026, 1, 2), date(2026, 1, 9))
    assert missing["available"] is False
    assert "2026-01-09" in missing["reason"] and "가까운 날짜로 대체하지 않습니다" in missing["reason"]

    unreadable = R.benchmark_period_return(
        {"2026-01-02": "종가없음", "2026-01-09": 2_600.0}, date(2026, 1, 2), date(2026, 1, 9))
    assert unreadable["available"] is False and "숫자로 읽지 못했습니다" in unreadable["reason"]


@pytest.mark.parametrize("start_close", [0.0, -1.0])
def test_benchmark_return_refuses_to_divide_by_a_non_positive_start_close(start_close):
    result = R.benchmark_period_return(
        {"2026-01-02": start_close, "2026-01-09": 2_600.0}, date(2026, 1, 2), date(2026, 1, 9))
    assert result["available"] is False
    assert "0 이하라 수익률을 계산할 수 없습니다" in result["reason"]
    assert result["change_pct"] is None


# =====================================================================================
# 4. "종목별 합 = 합계 스냅샷" 대조 — 어긋나면 숨기지 않고 말하기
# =====================================================================================
def test_holding_total_comparison_reports_a_match_within_tolerance():
    same = R.compare_holding_total(100.0, 100.0)
    assert (same["comparable"], same["matches"], same["diff"]) == (True, True, 0.0)
    assert "일치합니다" in same["message"]
    # 부동소수점 잔차는 허용 오차 안이라 '일치'로 봅니다
    near = R.compare_holding_total(100.0 + R.TOTAL_MATCH_TOLERANCE / 2, 100.0)
    assert near["matches"] is True


def test_holding_total_comparison_spells_out_the_gap_when_it_does_not_match():
    off = R.compare_holding_total(100.5, 100.0)
    assert off["matches"] is False
    assert off["diff"] == pytest.approx(0.5)
    assert "+0.500000 만큼 어긋납니다" in off["message"]


def test_holding_total_comparison_admits_when_it_cannot_compare():
    assert R.compare_holding_total(None, 1.0)["message"] == "대조할 값이 없어 확인하지 못했습니다."
    assert R.compare_holding_total(1.0, None)["comparable"] is False
    unreadable = R.compare_holding_total("숫자아님", 1.0)
    assert unreadable["comparable"] is False
    assert unreadable["message"] == "대조할 값을 숫자로 읽지 못했습니다."


# =====================================================================================
# 5. 종목별 비중(%) — 가격을 모르는 종목을 0% 로 적지 않기 (#114)
# =====================================================================================
def _holding_row(day, ticker, name, quantity, avg_price, close, priced=True):
    return {
        "snapshot_date": day, "market": "KR", "ticker": ticker, "stock_name": name,
        "quantity": quantity, "avg_purchase_price": avg_price,
        "cost": quantity * avg_price,
        "current_price": close if priced else None,
        "market_value": (quantity * close) if priced else None,
        "currency": "KRW", "priced": priced,
    }


def test_weight_comparison_reports_first_and_base_day_weights_and_the_change():
    rows = [
        _holding_row("2026-01-02", "005930", "삼성전자", 10, 50_000, 60_000),
        _holding_row("2026-01-02", "000660", "SK하이닉스", 5, 100_000, 80_000),
        _holding_row("2026-01-03", "005930", "삼성전자", 10, 50_000, 70_000),
        _holding_row("2026-01-03", "000660", "SK하이닉스", 5, 100_000, 60_000),
    ]
    result = R.build_weight_comparison(R.build_holding_history(rows))
    assert result["comparable"] is True
    assert (result["first_total"], result["base_total"]) == (1_000_000.0, 1_000_000.0)
    by_ticker = {row["ticker"]: row for row in result["rows"]}
    assert by_ticker["005930"]["first_pct"] == pytest.approx(60.0)
    assert by_ticker["005930"]["base_pct"] == pytest.approx(70.0)
    assert by_ticker["005930"]["change_pp"] == pytest.approx(10.0)
    assert by_ticker["000660"]["change_pp"] == pytest.approx(-10.0)
    # 비중의 합은 항상 100% (분모가 그날 가격을 아는 종목의 합이므로)
    assert sum(r["base_pct"] for r in result["rows"]) == pytest.approx(100.0)


def test_a_stock_absent_on_the_first_day_is_shown_as_0pct_not_as_unknown():
    rows = [
        _holding_row("2026-01-02", "005930", "삼성전자", 10, 50_000, 60_000),
        _holding_row("2026-01-03", "005930", "삼성전자", 10, 50_000, 60_000),
        _holding_row("2026-01-03", "000660", "SK하이닉스", 5, 100_000, 80_000),
    ]
    result = R.build_weight_comparison(R.build_holding_history(rows))
    new_stock = next(r for r in result["rows"] if r["ticker"] == "000660")
    assert (new_stock["first_pct"], new_stock["first_state"]) == (0.0, R.WEIGHT_ABSENT)
    assert new_stock["base_state"] == R.WEIGHT_OK
    assert new_stock["change_pp"] == pytest.approx(40.0)


def test_an_unpriced_day_has_no_denominator_and_reports_unknown_weight_not_zero():
    rows = [
        _holding_row("2026-01-02", "005930", "삼성전자", 10, 50_000, 60_000),
        _holding_row("2026-01-03", "005930", "삼성전자", 10, 50_000, 0, priced=False),
    ]
    result = R.build_weight_comparison(R.build_holding_history(rows))
    assert result["base_total"] is None            # 분모를 지어내지 않음
    assert result["unpriced_base"] == ["005930"]
    row = result["rows"][0]
    assert row["base_pct"] is None and row["base_state"] == R.WEIGHT_UNPRICED
    assert row["change_pp"] is None                # 비교 자체를 하지 않음


def test_weight_comparison_on_a_single_day_is_not_comparable_but_still_shows_weights():
    rows = [_holding_row("2026-01-02", "005930", "삼성전자", 10, 50_000, 60_000)]
    result = R.build_weight_comparison(R.build_holding_history(rows))
    assert result["comparable"] is False
    assert result["first_date"] == result["base_date"] == date(2026, 1, 2)
    assert result["rows"][0]["base_pct"] == pytest.approx(100.0)


def test_weight_comparison_on_empty_history_returns_an_empty_shell():
    for history in ({}, None, {"daily_by_ticker": {}, "dates": [], "base_date": None}):
        result = R.build_weight_comparison(history)
        assert result["rows"] == [] and result["comparable"] is False
        assert result["base_total"] is None


# =====================================================================================
# 6. 결투 체결 규칙 — "없는 값을 0 으로 메우지 않는다"의 실체
# =====================================================================================
def test_fill_rejects_missing_and_non_finite_money_inputs():
    with pytest.raises(duel_rules.DuelRuleError, match="0 으로 대체하지 않습니다"):
        duel_rules.calculate_fill(1, None, 1_000)
    with pytest.raises(duel_rules.DuelRuleError, match="유효한 숫자가 아닙니다"):
        duel_rules.calculate_fill(1, float("inf"), 1_000)
    with pytest.raises(duel_rules.DuelRuleError, match="유효한 숫자가 아닙니다"):
        duel_rules.calculate_fill(1, 100, float("nan"))
    with pytest.raises(duel_rules.DuelRuleError, match="0 이상이어야 합니다"):
        duel_rules.calculate_fill(1, -100, 1_000)


def test_fill_rejects_bool_and_fractional_share_counts():
    """`True == 1` 이라 bool 이 '1주'로 조용히 통과하던 함정을 막습니다."""
    with pytest.raises(duel_rules.DuelRuleError):
        duel_rules.calculate_fill(True, 100, 1_000)
    with pytest.raises(duel_rules.DuelRuleError, match="정수여야 합니다"):
        duel_rules.calculate_fill(1.5, 100, 1_000)
    with pytest.raises(duel_rules.DuelRuleError, match="정수가 아닙니다"):
        duel_rules.calculate_fill("세주", 100, 1_000)
    with pytest.raises(duel_rules.DuelRuleError, match="1 이상이어야 합니다"):
        duel_rules.calculate_fill(0, 100, 1_000)


def test_fill_math_is_unchanged_for_the_normal_and_partial_paths():
    full = duel_rules.calculate_fill(3, 100, 1_000)
    assert (full["filled_quantity"], full["filled_amount"], full["remaining_cash"]) == (3, 300.0, 700.0)
    partial = duel_rules.calculate_fill(30, 100, 1_000)
    assert partial["filled_quantity"] == 10 and partial["remaining_cash"] == 0.0
    assert "10주만 예수금 부족으로 체결" in partial["fail_reason"]


def test_date_inputs_are_never_guessed():
    for bad in (None, "", "   ", "2026-13-99", "어제"):
        with pytest.raises(duel_rules.DuelRuleError):
            duel_rules.season_start_for_date(bad)
    # 정상 입력 3종(문자열/date/datetime)은 같은 시즌 시작일로 수렴합니다
    assert duel_rules.season_start_for_date("2026-08-30") == date(2026, 3, 1)
    assert duel_rules.season_start_for_date(date(2026, 8, 30)) == date(2026, 3, 1)
    assert duel_rules.season_start_for_date(datetime(2026, 8, 30, 12, 0)) == date(2026, 3, 1)
    assert duel_rules.season_start_for_date("2026-02-28") == date(2025, 3, 1)


def test_timestamp_inputs_are_never_guessed():
    for bad in (None, "", "   ", 12_345, "어제 오후"):
        with pytest.raises(duel_rules.DuelRuleError):
            duel_rules.resolve_order_window(bad)
    window = duel_rules.resolve_order_window("2026-08-30T01:00:00Z")
    assert window["now_kst"].hour == 10          # naive 가 아니라 UTC → KST 변환


def test_bracket_assignment_refuses_a_missing_or_negative_principal():
    """값을 모른다고 최하위 체급으로 떨어뜨리면 그 사용자는 남의 체급에서 겨루게 됩니다."""
    with pytest.raises(duel_rules.DuelRuleError, match="0 으로 대체하지 않습니다"):
        duel_rules.assign_bracket(None)
    with pytest.raises(duel_rules.DuelRuleError, match="0 이상이어야 합니다"):
        duel_rules.assign_bracket(-1)
    with pytest.raises(duel_rules.DuelRuleError, match="알 수 없는 체급 식별자"):
        duel_rules.bracket_label("없는체급")


# =====================================================================================
# 7. 수집 신선도 판정 — 무엇이 지수인지 추측하지 않기
# =====================================================================================
@pytest.mark.parametrize("probe", [None, {}, {"values": {}}, {"values": None}])
def test_freshness_judgement_refuses_an_empty_probe(probe):
    with pytest.raises(duel_batch.DuelBatchError, match="점검표가 비어 있습니다"):
        duel_batch.judge_crawl_freshness(probe, None)


def test_freshness_judgement_refuses_a_probe_without_index_keys():
    with pytest.raises(duel_batch.DuelBatchError, match="무엇이 지수인지 추측하지 않습니다"):
        duel_batch.judge_crawl_freshness({"values": {"005930": 70_000}}, None)


def test_freshness_without_a_baseline_is_reported_not_raised():
    """첫 실행은 오류가 아니라 '판정 불가' 입니다(체결은 막습니다)."""
    verdict = duel_batch.judge_crawl_freshness(
        {"values": {"KOSPI": 2_500.0, "005930": 70_000}, "index_keys": ["KOSPI"]}, None)
    assert verdict["status"] == duel_batch.CRAWL_NO_BASELINE
    assert verdict["allows_fill"] is False
    assert verdict["baseline_date"] is None
    assert "판정할 수 없습니다" in verdict["reason"]


# =====================================================================================
# 8. 날짜표 만료 알람 — 조용히 지나가면 안 되는 자리
# =====================================================================================
def _freeze_today(monkeypatch, frozen):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return frozen
    monkeypatch.setattr(expiry_alarms, "date", _FixedDate)


def test_no_warning_while_the_table_is_still_comfortably_valid(monkeypatch, capsys):
    _freeze_today(monkeypatch, date(2026, 11, 1))          # 2027-01-01 까지 61일
    assert expiry_alarms.warn_if_expiring("KRX 휴장일 표", 2026) is False
    assert capsys.readouterr().out == ""


def test_warning_starts_exactly_at_the_lead_day_boundary(monkeypatch, capsys):
    _freeze_today(monkeypatch, date(2026, 11, 2))          # 정확히 60일
    assert expiry_alarms.warn_if_expiring("KRX 휴장일 표", 2026) is True
    out = capsys.readouterr().out
    assert "날짜표 만료 경고 — KRX 휴장일 표" in out
    assert "앞으로 60일 남았습니다" in out
    assert "2027-01-01" in out


def test_warning_gets_louder_inside_the_last_two_weeks(monkeypatch, capsys):
    _freeze_today(monkeypatch, date(2026, 12, 25))         # 7일
    assert expiry_alarms.warn_if_expiring("KRX 휴장일 표", 2026) is True
    assert "앞으로 7일밖에 안 남았습니다" in capsys.readouterr().out


def test_warning_says_how_long_it_has_already_been_overdue(monkeypatch, capsys):
    _freeze_today(monkeypatch, date(2027, 1, 11))          # 10일 지남
    assert expiry_alarms.warn_if_expiring("KRX 휴장일 표", 2026) is True
    out = capsys.readouterr().out
    assert "이미 10일 지났습니다" in out
    assert "예외를 던지고 있을 가능성이 높습니다" in out


def test_lead_days_is_configurable_by_the_caller(monkeypatch, capsys):
    _freeze_today(monkeypatch, date(2026, 12, 31))         # 1일 남음
    assert expiry_alarms.warn_if_expiring("표", 2026, lead_days=0) is False
    assert capsys.readouterr().out == ""
    assert expiry_alarms.warn_if_expiring("표", 2026, lead_days=1) is True


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_lines(relative_path):
    """주석·독스트링 설명문을 뺀 '실제로 실행되는 줄'만 (설명 속 옛 표기에 오탐하지 않게)."""
    source = open(os.path.join(REPO_ROOT, relative_path), encoding="utf-8").read()
    return [line for line in source.splitlines()
            if line.strip() and not line.strip().startswith(("#", "#:"))]


def test_verified_year_constant_is_shared_instead_of_mirrored_by_hand():
    """
    L5(2026-08-29): 이 숫자를 `collector_dividend_payment_kr.py` 가 손으로 미러링하다
    (§0-3-10 위반) 표를 갱신해도 알람 시점만 조용히 어긋났습니다. 두 호출부가 상수를
    그대로 참조하는지, 연도를 다시 손으로 적어두지 않았는지 확인합니다.
    """
    assert isinstance(expiry_alarms.KRX_VERIFIED_LAST_YEAR, int)
    for path in ("collector_dividend_payment_kr.py", os.path.join("web", "pages", "dividend_page.py")):
        lines = _code_lines(path)
        assert any("KRX_VERIFIED_LAST_YEAR" in line for line in lines), path
        hardcoded = [line for line in lines
                     if "last_verified_year" in line and "KRX_VERIFIED_LAST_YEAR" not in line]
        assert hardcoded == [], f"{path} 에 검증 연도 사본이 남아 있습니다: {hardcoded}"
