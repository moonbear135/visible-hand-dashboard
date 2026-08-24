"""
tests/test_indicators.py
「여기서부터는 신앙입니다」(보조지표 모듈) 계산 엔진 오프라인 단위테스트.

네트워크 불필요 — 전부 합성(synthetic) 종가 시계열로 검증합니다.
단독 실행 시 ModuleNotFoundError가 나지 않도록 sys.path를 보정합니다
(§ 배당 모듈 검토 때 지적된 것과 같은 관례).

실행: python -m pytest tests/test_indicators.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_bollinger,
    combine_verdict,
)
from utils.constants import (
    RSI_MIN_BARS, RSI_STABLE_BARS,
    MACD_MIN_BARS, MACD_STABLE_BARS,
    BB_MIN_BARS, BB_STABLE_BARS,
)


# ---------------------------------------------------------------------------
# 합성 시계열 헬퍼
# ---------------------------------------------------------------------------

def _rising(n, start=10000, step=100):
    return [start + step * i for i in range(n)]


def _falling(n, start=10000, step=100):
    return [start - step * i for i in range(n)]


def _flat(n, price=10000):
    return [price] * n


def _rising_then_crash(n_up, n_down, start=10000, up_step=150, down_step=400):
    up = _rising(n_up, start=start, step=up_step)
    peak = up[-1]
    down = [peak - down_step * i for i in range(1, n_down + 1)]
    return up + down


# ---------------------------------------------------------------------------
# 데이터 부족 — §0-1: 중립값으로 채우지 않고 None + 사유
# ---------------------------------------------------------------------------

def test_rsi_insufficient_data_returns_none_with_reason():
    result = calculate_rsi(_rising(5))
    assert result["available"] is False
    assert result["rsi"] is None
    assert "산출 불가" in result["reason"]
    assert str(RSI_MIN_BARS) in result["reason"] or "15" in result["reason"]


def test_macd_insufficient_data_returns_none_with_reason():
    result = calculate_macd(_rising(20))
    assert result["available"] is False
    assert result["macd"] is None
    assert result["signal_line"] is None
    assert result["histogram"] is None
    assert "산출 불가" in result["reason"]


def test_bollinger_insufficient_data_returns_none_with_reason():
    result = calculate_bollinger(_rising(10))
    assert result["available"] is False
    assert result["upper"] is None
    assert result["lower"] is None
    assert "산출 불가" in result["reason"]


def test_empty_input_does_not_crash():
    for fn in (calculate_rsi, calculate_macd, calculate_bollinger):
        result = fn([])
        assert result["available"] is False
        assert result["bars_used"] == 0


def test_none_and_negative_values_are_dropped_not_fabricated():
    # 결측(None)·비양수 종가가 섞여 있어도 조용히 지어내지 않고 정제 후 실제 봉 수만 사용
    closes = [10000, None, 10100, -5, 10200] + _rising(20, start=10300)
    result = calculate_rsi(closes)
    # None/음수 2개를 제외한 23봉만 유효
    assert result["bars_used"] == 23


# ---------------------------------------------------------------------------
# 워밍업 부족 표시 — 산출은 되지만 신뢰도 낮음을 숨기지 않음
# ---------------------------------------------------------------------------

def test_rsi_warmup_insufficient_flag():
    just_enough = calculate_rsi(_rising(RSI_MIN_BARS))
    assert just_enough["available"] is True
    assert just_enough["warmup_insufficient"] is True

    plenty = calculate_rsi(_rising(RSI_STABLE_BARS + 10))
    assert plenty["available"] is True
    assert plenty["warmup_insufficient"] is False


def test_macd_warmup_insufficient_flag():
    just_enough = calculate_macd(_rising(MACD_MIN_BARS))
    assert just_enough["available"] is True
    assert just_enough["warmup_insufficient"] is True

    plenty = calculate_macd(_rising(MACD_STABLE_BARS + 10))
    assert plenty["available"] is True
    assert plenty["warmup_insufficient"] is False


def test_bollinger_warmup_insufficient_flag():
    just_enough = calculate_bollinger(_flat(BB_MIN_BARS))
    assert just_enough["available"] is True
    assert just_enough["warmup_insufficient"] is True

    plenty = calculate_bollinger(_flat(BB_STABLE_BARS + 10))
    assert plenty["available"] is True
    assert plenty["warmup_insufficient"] is False


# ---------------------------------------------------------------------------
# 방향성 — 단조 상승/하락/횡보 시나리오
# ---------------------------------------------------------------------------

def test_rsi_monotonic_rise_is_overbought():
    result = calculate_rsi(_rising(60))
    assert result["available"] is True
    assert result["signal"] == "overbought"
    assert result["rsi"] > 70


def test_rsi_monotonic_fall_is_oversold():
    result = calculate_rsi(_falling(60))
    assert result["available"] is True
    assert result["signal"] == "oversold"
    assert result["rsi"] < 30


def test_rsi_flat_price_no_gain_no_loss_returns_neutral_50():
    result = calculate_rsi(_flat(60))
    assert result["available"] is True
    # 상승도 하락도 없으면 손실평균이 0 → 상승도 0이므로 중립 50.0 분기
    assert result["rsi"] == 50.0
    assert result["signal"] == "neutral"


def test_macd_monotonic_rise_is_positive():
    result = calculate_macd(_rising(80))
    assert result["available"] is True
    assert result["macd"] > 0
    assert result["histogram"] is not None


def test_macd_monotonic_fall_is_negative():
    result = calculate_macd(_falling(80))
    assert result["available"] is True
    assert result["macd"] < 0


def test_macd_flat_price_is_zero():
    result = calculate_macd(_flat(80))
    assert result["available"] is True
    assert result["macd"] == 0.0
    assert result["histogram"] == 0.0
    assert result["cross"] is None


def test_macd_detects_dead_cross_after_crash():
    # 충분히 상승(양의 히스토그램)한 뒤 마지막 봉에서 급락하면 그 봉에서 데드크로스가 잡혀야 함.
    # cross는 "직전 봉 대비 부호 전환"만 보므로, 하락을 여러 봉에 걸쳐 나눠주면(완만한 크로스는
    # 이미 며칠 전에 지나가버려) 오늘 봉에서는 안 잡힌다 — 그래서 마지막 1봉에 급락을 몰아준다.
    closes = _rising_then_crash(n_up=90, n_down=1, down_step=400)
    result = calculate_macd(closes)
    assert result["available"] is True
    assert result["cross"] == "dead"
    assert result["histogram"] < 0


def test_bollinger_rising_price_touches_upper_or_inside():
    result = calculate_bollinger(_rising(60))
    assert result["available"] is True
    assert result["position"] in ("above_upper", "inside")
    assert result["percent_b"] > 0.5


def test_bollinger_flat_price_zero_stdev_is_midline():
    result = calculate_bollinger(_flat(60))
    assert result["available"] is True
    assert result["upper"] == result["lower"] == result["mid"]
    assert result["percent_b"] == 0.5
    assert result["position"] == "inside"


def test_bollinger_percent_b_is_unit_free_0_to_1_ish():
    # %B는 무차원이라 종목 간 비교가 가능하다는 전제(MACD와 대비되는 성질)를 확인
    cheap_stock = calculate_bollinger(_rising(60, start=3000, step=20))
    expensive_stock = calculate_bollinger(_rising(60, start=300000, step=2000))
    assert cheap_stock["available"] and expensive_stock["available"]
    # 서로 다른 가격대라도 %B는 같은 스케일(대략 0~1 근방)에 있어야 함
    assert cheap_stock["position"] == expensive_stock["position"]


# ---------------------------------------------------------------------------
# 종합 판정 — 결정론적 가중합산, AI 미사용
# ---------------------------------------------------------------------------

def test_combine_verdict_all_bullish_signals_yields_buy_bias():
    rsi = {"available": True, "signal": "oversold"}
    macd = {"available": True, "cross": "golden"}
    bb = {"available": True, "position": "below_lower"}
    result = combine_verdict(rsi, macd, bb)
    assert result["score"] == 3
    assert result["label"] == "매수 우위"
    assert result["skipped"] == []


def test_combine_verdict_all_bearish_signals_yields_sell_bias():
    rsi = {"available": True, "signal": "overbought"}
    macd = {"available": True, "cross": "dead"}
    bb = {"available": True, "position": "above_upper"}
    result = combine_verdict(rsi, macd, bb)
    assert result["score"] == -3
    assert result["label"] == "매도 우위"


def test_combine_verdict_mixed_signals_yields_neutral():
    rsi = {"available": True, "signal": "neutral"}
    macd = {"available": True, "cross": None}
    bb = {"available": True, "position": "inside"}
    result = combine_verdict(rsi, macd, bb)
    assert result["score"] == 0
    assert result["label"] == "중립"


def test_combine_verdict_skips_unavailable_indicator_instead_of_treating_as_neutral():
    # §0-1: 산출 안 되는 지표를 0점(중립)으로 슬쩍 섞으면 안 됨 — skipped에 남고 합산에서 제외
    rsi = {"available": False, "reason": "산출 불가 — 종가 5봉 보유, 최소 15봉 필요"}
    macd = {"available": True, "cross": "golden"}
    bb = {"available": True, "position": "below_lower"}
    result = combine_verdict(rsi, macd, bb)
    assert result["score"] == 2  # RSI 제외, MACD+Bollinger만 합산
    assert len(result["skipped"]) == 1
    assert result["skipped"][0][0] == "RSI"


def test_combine_verdict_all_unavailable_returns_no_score():
    unavailable = {"available": False, "reason": "산출 불가 — 종가 3봉 보유, 최소 15봉 필요"}
    result = combine_verdict(unavailable, unavailable, unavailable)
    assert result["score"] is None
    assert result["label"] == "산출 불가"
    assert len(result["skipped"]) == 3
