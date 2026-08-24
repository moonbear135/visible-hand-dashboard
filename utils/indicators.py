"""
utils/indicators.py
「여기서부터는 신앙입니다」(보조지표 모듈, 7번째 모듈) — RSI·MACD·볼린저밴드 계산 엔진

⚠️ 이 파일은 NiceGUI/Streamlit 어느 화면 프레임워크도 import하지 않습니다.
   `utils/stock_history.py`가 이미 지키고 있는 관례와 같은 이유입니다 — 배치(수집기)와
   화면이 같은 함수를 그대로 공유해야 하고, 네트워크·화면 없이 오프라인 단위테스트가
   가능해야 하기 때문입니다(§0-3-10 단일 출처).

⚠️ ENGINEERING_SPEC §0-1 (지어내지 않기):
   봉 수가 부족해 산출 자체가 불가능하면 절대 중립값(RSI=50 등)으로 채우지 않고
   `available=False` + `reason`(왜 안 되는지)을 그대로 돌려줍니다. 산출은 되지만
   워밍업(EMA 초기화) 편향이 남아있는 구간은 `warmup_insufficient=True`로 표시해
   신뢰도가 낮다는 사실 자체를 숨기지 않습니다.

⚠️ 입력은 종가(Close)만 씁니다 — OHLC 전체가 필요 없는 이유는
   `TECHNICAL_INDICATOR_WORK_ORDER.md` §2 참고.

작업 지시서: `TECHNICAL_INDICATOR_WORK_ORDER.md` (검토 완료, 2026-08-24)
"""

import pandas as pd

from utils.constants import (
    RSI_PERIOD, RSI_MIN_BARS, RSI_STABLE_BARS, RSI_OVERBOUGHT, RSI_OVERSOLD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL, MACD_MIN_BARS, MACD_STABLE_BARS,
    BB_PERIOD, BB_STD_MULTIPLIER, BB_MIN_BARS, BB_STABLE_BARS,
    VERDICT_LABELS,
)


def _clean_closes(closes):
    """
    입력을 정렬된(과거→최근) pandas Series로 정규화하고, 결측·비양수 종가를 제거합니다.
    §0-1: 비어있거나 이상한 입력을 조용히 통과시키지 않고, 정제 후 실제 사용 가능한
    봉 수(bars_used)를 그대로 반환합니다 — 이게 각 지표 함수의 "산출 가능 여부" 판단 기준입니다.
    """
    s = pd.Series(closes).dropna()
    s = s[s > 0]
    return s.reset_index(drop=True)


def calculate_rsi(closes, period=RSI_PERIOD):
    """
    RSI(상대강도지수)를 Wilder 평활 방식으로 계산합니다.

    반환:
      available=False 면 값이 전부 None 이고 reason에 사유가 담깁니다.
      available=True 여도 warmup_insufficient=True 면 초기화 편향이 남아있다는 뜻입니다.
    """
    s = _clean_closes(closes)
    bars = len(s)

    if bars < period + 1:
        return {
            "available": False,
            "bars_used": bars,
            "warmup_insufficient": None,
            "rsi": None,
            "signal": None,
            "reason": f"산출 불가 — 종가 {bars}봉 보유, 최소 {period + 1}봉 필요",
        }

    delta = s.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder 평활 = 지수이동평균의 특수형(alpha = 1/period, adjust=False)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]

    if last_loss == 0:
        rsi_value = 100.0 if last_gain > 0 else 50.0
    else:
        rs = last_gain / last_loss
        rsi_value = 100.0 - (100.0 / (1.0 + rs))

    if rsi_value >= RSI_OVERBOUGHT:
        signal = "overbought"
    elif rsi_value <= RSI_OVERSOLD:
        signal = "oversold"
    else:
        signal = "neutral"

    return {
        "available": True,
        "bars_used": bars,
        "warmup_insufficient": bars < RSI_STABLE_BARS,
        "rsi": round(float(rsi_value), 2),
        "signal": signal,
        "reason": None,
    }


def calculate_macd(closes, fast=MACD_FAST, slow=MACD_SLOW, signal_period=MACD_SIGNAL):
    """
    MACD(이동평균 수렴·확산)를 계산합니다.
    MACD선 = fast EMA - slow EMA / 시그널선 = MACD선의 signal_period EMA
    histogram = MACD선 - 시그널선. 직전 봉 대비 부호가 바뀌면 골든/데드크로스로 표시합니다.

    ⚠️ MACD 원값은 원(₩) 단위 절대값이라 종목 간 비교에 쓰지 않습니다
       (TECHNICAL_INDICATOR_WORK_ORDER.md §6-4, 오너 확정: 랭킹 기능 자체를 만들지 않음).
    """
    s = _clean_closes(closes)
    bars = len(s)
    min_bars = slow + signal_period

    if bars < min_bars:
        return {
            "available": False,
            "bars_used": bars,
            "warmup_insufficient": None,
            "macd": None,
            "signal_line": None,
            "histogram": None,
            "cross": None,
            "reason": f"산출 불가 — 종가 {bars}봉 보유, 최소 {min_bars}봉 필요",
        }

    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    cross = None
    if len(histogram) >= 2:
        prev_h, last_h = histogram.iloc[-2], histogram.iloc[-1]
        if prev_h <= 0 < last_h:
            cross = "golden"
        elif prev_h >= 0 > last_h:
            cross = "dead"

    return {
        "available": True,
        "bars_used": bars,
        "warmup_insufficient": bars < MACD_STABLE_BARS,
        "macd": round(float(macd_line.iloc[-1]), 2),
        "signal_line": round(float(signal_line.iloc[-1]), 2),
        "histogram": round(float(histogram.iloc[-1]), 2),
        "cross": cross,
        "reason": None,
    }


def calculate_bollinger(closes, period=BB_PERIOD, std_multiplier=BB_STD_MULTIPLIER):
    """
    볼린저밴드를 계산합니다. %B = (종가 - 하단) / (상단 - 하단), 0~1 범위(무차원이라
    종목 간 비교 가능 — MACD와 다른 점).
    """
    s = _clean_closes(closes)
    bars = len(s)

    if bars < period:
        return {
            "available": False,
            "bars_used": bars,
            "warmup_insufficient": None,
            "upper": None,
            "lower": None,
            "mid": None,
            "percent_b": None,
            "position": None,
            "reason": f"산출 불가 — 종가 {bars}봉 보유, 최소 {period}봉 필요",
        }

    window = s.tail(period)
    mid = window.mean()
    std = window.std()
    upper = mid + std_multiplier * std
    lower = mid - std_multiplier * std
    last_close = s.iloc[-1]

    band_width = upper - lower
    if band_width == 0:
        percent_b = 0.5
    else:
        percent_b = (last_close - lower) / band_width

    if last_close > upper:
        position = "above_upper"
    elif last_close < lower:
        position = "below_lower"
    else:
        position = "inside"

    return {
        "available": True,
        "bars_used": bars,
        "warmup_insufficient": bars < BB_STABLE_BARS,
        "upper": round(float(upper), 2),
        "lower": round(float(lower), 2),
        "mid": round(float(mid), 2),
        "percent_b": round(float(percent_b), 4),
        "position": position,
        "reason": None,
    }


def combine_verdict(rsi_result, macd_result, bb_result):
    """
    3개 지표의 개별 판독을 결정론적 가중합산으로 종합 판정합니다(AI 미사용).
    지표 하나라도 available=False 면 그 지표는 합산에서 빠지고 사유가 남습니다
    — 산출 안 되는 지표를 중립(0점) 취급해 슬쩍 섞지 않습니다(§0-1).

    반환: {"score": int|None, "label": str, "contributing": [...], "skipped": [...]}
    점수가 하나도 없으면(3개 다 산출 불가) label="산출 불가".
    """
    contributions = []
    skipped = []

    if rsi_result.get("available"):
        if rsi_result["signal"] == "oversold":
            contributions.append(("RSI", 1))
        elif rsi_result["signal"] == "overbought":
            contributions.append(("RSI", -1))
        else:
            contributions.append(("RSI", 0))
    else:
        skipped.append(("RSI", rsi_result.get("reason")))

    if macd_result.get("available"):
        if macd_result["cross"] == "golden":
            contributions.append(("MACD", 1))
        elif macd_result["cross"] == "dead":
            contributions.append(("MACD", -1))
        else:
            contributions.append(("MACD", 0))
    else:
        skipped.append(("MACD", macd_result.get("reason")))

    if bb_result.get("available"):
        if bb_result["position"] == "below_lower":
            contributions.append(("Bollinger", 1))
        elif bb_result["position"] == "above_upper":
            contributions.append(("Bollinger", -1))
        else:
            contributions.append(("Bollinger", 0))
    else:
        skipped.append(("Bollinger", bb_result.get("reason")))

    if not contributions:
        return {
            "score": None,
            "label": "산출 불가",
            "contributing": [],
            "skipped": skipped,
        }

    score = sum(v for _, v in contributions)

    if score <= -2:
        label = VERDICT_LABELS["sell_bias"]
    elif score >= 2:
        label = VERDICT_LABELS["buy_bias"]
    else:
        label = VERDICT_LABELS["neutral"]

    return {
        "score": score,
        "label": label,
        "contributing": contributions,
        "skipped": skipped,
    }
