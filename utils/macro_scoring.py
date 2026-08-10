"""
utils/macro_scoring.py
매크로(시장 위험 점수) 종합점수 계산 로직의 단일 출처.

⚠️ 왜 이 파일이 생겼나 (2026-08-06 2차 감사 5-1 / 5-2)
   scrape_daily.py(실제 수집·CSV 저장)와 views/macro_view.py(화면 표시)가 같은 개념을
   각자 따로 구현하고 있었습니다:
   - 가중치 사전이 서로 달랐음(5-1) → utils/constants.py의 RISK_WEIGHTS/INVESTOR_WEIGHTS로 통일.
   - 지표별 "위험도" 척도가 서로 달랐음(5-2): scrape_daily는 원시 가중위험(0~1)을 과거 이력
     대비 z-score로 정규화한 뒤 시그모이드(k=1.1)로 0~100점 변환해서 저장하는데, macro_view는
     저장된 원시값(0~1)을 그냥 ×100 해서 보여줬습니다. 두 숫자는 척도 자체가 달라 화면 표의
     기여점수를 다 더해도 위에 뜬 종합 위험 지수가 절대 안 나왔습니다.
   - 극단 신호 판정 기준도 서로 달랐음(sub_score>=85/<=15 vs weighted_risk>=0.75).

   이 모듈은 위 세 가지를 한 곳에 모아 두 파일이 동일한 함수를 호출하게 합니다.
   ⚠️ 단, 이미 수집된 과거 날짜를 화면에 보여줄 때는 이 모듈로 "재계산"하지 말고 그날
   실제로 저장된 SubScore_*/Multiplier 컬럼을 그대로 읽으세요 — 과거 시점의 historical_stats
   (그 시점까지의 이력 평균/표준편차)를 지금 다시 재현할 수 없어서, 재계산하면 그날 실제로
   나왔던 점수와 달라질 수 있습니다. 이 모듈은 "수집 시점 저장"과 "아직 수집 전 미리보기"
   양쪽에만 씁니다.
"""
import math
import statistics

from utils.constants import RISK_WEIGHTS, INVESTOR_WEIGHTS
# 2026-08-10 (#68): "실측값을 0~1 위험도로 바꾸는" 방법론을 새로 발명하지 않고, 이 프로젝트가
# 이미 종목 스코어링에서 쓰고 있는 population z-score + 윈저라이즈 패턴을 그대로 재사용합니다.
# (utils/scoring.py 상단 주석 참고 — Barra/Fama-French류 정규화 + winsorize)
from utils.scoring import _population_zscore, _winsorized_scale

# 시그모이드 변환 민감도. z-score 1 단위당 곡선이 얼마나 가파르게 0~100으로 펼쳐지는지를
# 정합니다(과거 "50점대 지표가 계속 애매하게 몰리는" 문제 완화를 위해 v1.4.0에서 도입).
SIGMOID_K = 1.1

# 극단 국면(Regime Switch) 판정 — 시그모이드 변환 후 점수가 이 범위를 벗어나면 "극단"으로 셈
EXTREME_SUB_SCORE_HIGH = 85.0
EXTREME_SUB_SCORE_LOW = 15.0

# =============================================================================
# 동시 충격 증폭기 (2차 감사 4-1: 예전엔 extreme_signal_count>=5면 무조건 1.3배,
# >=3이면 무조건 1.15배 — 5개든 14개 전부든 동일 1.3배였음)
# =============================================================================
# 이제 "산출 가능한 지표 중 몇 %가 극단인지" 비율에 비례해 1.0~SHOCK_AMPLIFIER_MAX 사이로
# 윈저라이즈된 배율을 씁니다(절대거리 기준 — VOL_PENALTY와 동일한 이유로, "오늘 다른 종목과
# 비교"가 아니라 "시장 전체가 얼마나 동시에 흔들리는가"를 보는 것이라 population 비교가
# 아닌 절대 비율 기준을 씁니다).
SHOCK_AMPLIFIER_START_RATIO = 3.0 / 14.0   # ≈21.4%. 지표 14개 시절의 '3개 이상' 기준을 비율로 환산
SHOCK_AMPLIFIER_MAX_RATIO = 8.0 / 14.0     # ≈57.1%. 그 시절의 '8개 이상' 기준을 비율로 환산
SHOCK_AMPLIFIER_MAX = 1.3                  # 예전 최댓값(1.3)을 상한으로 유지
# ⚠️ 2026-08-10 (#69) 지표가 14개 → 8개로 줄면서 생기는 부수효과를 정직하게 적어둡니다.
#    이 배율은 개수가 아니라 **비율**(극단 신호 수 ÷ 그날 산출 가능한 지표 수)로 계산되므로
#    지표 수가 바뀌어도 코드는 그대로 동작합니다. 다만 같은 "2개 극단"이라도
#    예전엔 2/14 ≈ 14.3%(증폭 없음), 지금은 2/8 = 25%(약한 증폭 시작)로 판정됩니다.
#    이 상수들을 지표 수에 맞춰 다시 손대면 그것 자체가 근거 없는 재튜닝이 되므로,
#    "비율 기준"이라는 원래 설계를 그대로 유지하고 변화 사실만 기록해 둡니다.


def compute_shock_amplifier(extreme_signal_count, total_indicators):
    """극단 신호 비율에 비례한 1.0~SHOCK_AMPLIFIER_MAX 배율(절대거리 윈저라이즈)."""
    if not total_indicators:
        return 1.0
    ratio = extreme_signal_count / total_indicators
    if ratio <= SHOCK_AMPLIFIER_START_RATIO:
        return 1.0
    if ratio >= SHOCK_AMPLIFIER_MAX_RATIO:
        return SHOCK_AMPLIFIER_MAX
    span = SHOCK_AMPLIFIER_MAX_RATIO - SHOCK_AMPLIFIER_START_RATIO
    progress = (ratio - SHOCK_AMPLIFIER_START_RATIO) / span
    return round(1.0 + progress * (SHOCK_AMPLIFIER_MAX - 1.0), 4)


# =============================================================================
# 실측 지표(measured indicator) 정규화 — 2026-08-10 (#68)
# =============================================================================
# 왜 필요한가:
#   14개 위험 지표 중 `KOSPI_5D_Return`(코스피 5영업일 수익률)과 `Stock_Net_Sell`(외국인·기관·
#   개인 순매수 금액)은 **이미 매일 실제로 측정하고 있는 값**인데도, 나머지 12개 추정 프록시와
#   똑같이 `0.5 + 임의계수 × 값` 형태의 선형식에 넣고 clip(0~1)으로 잘라 쓰고 있었습니다.
#   특히 순매수는 `0.5 ± 0.3`(부호만 반영)이라 "1천억 순매도"와 "3조 순매도"가 완전히 동점이었고,
#   5일 수익률은 계수 2.5가 어디서 나온 숫자인지 근거가 없었습니다(= 크기 정보 폐기).
#
# 어떻게 고쳤나:
#   실측 원값을 **그 지표 자신의 과거 분포** 대비 z-score로 표준화한 뒤(_population_zscore),
#   ±MEASURED_WINSOR_Z 구간을 0~1 위험도로 선형 매핑하고 그 바깥은 윈저라이즈합니다
#   (_winsorized_scale). 두 함수 모두 utils/scoring.py에 이미 있던 것을 그대로 씁니다.
#   → 크기가 커질수록 점수도 단조적으로 커지고, 어떤 입력이 와도 결과는 항상 [0, 1]입니다.
#
# 표본이 부족하면(§0-1: 없는 데이터를 지어내지 않는다):
#   population 통계를 만들지 못하면 z=None이 되고, _winsorized_scale이 (0.0+1.0)/2 = 0.5
#   중립값을 돌려줍니다. 이는 utils/scoring.py가 이미 쓰는 "population 통계 없으면 중간값으로
#   안전 대체" 패턴과 동일합니다(크래시도, 임의 상수 대입도 하지 않음).
#
# ±3.0 표준편차: utils/scoring.py의 밸류에이션 z-score 윈저라이즈 경계(worst_z=±3.0)와 같은
#   기준을 씁니다 — "3표준편차를 벗어나면 그 이상은 정도를 더 구분하지 않는다".
MEASURED_WINSOR_Z = 3.0

# 순매수 금액 정규화에 필요한 최소 과거 표본(행). 이 파일을 쓰는 scrape_daily.py/macro_view.py가
# 이미 "누적 이력 20행 미만이면 정규화 표본 부족"이라고 경고하고 있어 같은 기준을 그대로 씁니다.
NET_FLOW_MIN_SAMPLE = 20

# 5일 수익률 분포 추정에 쓰는 과거 창(영업일)과 최소 표본.
#   252 = 약 1년(52주 고점 계산에 이미 쓰고 있는 창과 동일)
#   60  = 약 3개월. 이보다 짧으면 "평소 대비 얼마나 빠졌나"를 말할 만한 분포가 못 됩니다.
RETURN_POP_LOOKBACK = 252
RETURN_POP_MIN_SAMPLE = 60


def compute_population_stats(values, min_sample):
    """
    실측값 목록의 (평균, 표준편차)를 반환합니다. 표본이 min_sample 미만이거나 표준편차가
    0이면 None을 반환합니다 — 호출부는 None을 받으면 중립(0.5)으로 안전 대체해야 합니다.
    """
    clean = []
    for v in values or []:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        clean.append(f)
    if len(clean) < max(2, int(min_sample)):
        return None
    std = statistics.stdev(clean)
    if not std or std <= 0:
        return None
    return (statistics.fmean(clean), std)


def measured_downside_risk(value, pop_stats):
    """
    "값이 작을수록(더 마이너스일수록) 위험이 큰" 실측 지표를 0~1 위험도로 변환합니다.
    (코스피 5일 수익률, 주체별 순매수 금액이 모두 이 방향입니다 — 많이 빠질수록/많이 팔수록 위험)

    - value가 None → None (산출 불가. 호출부에서 배점 자체를 제외합니다)
    - pop_stats가 None(표본 부족) → 0.5 중립 (지어내지 않고 안전 대체)
    - 그 외 → z = (value - mean) / std 를 [+3σ → 0.0, -3σ → 1.0] 으로 선형 매핑 후 윈저라이즈
    """
    if value is None:
        return None
    z = _population_zscore(value, pop_stats)
    risk = _winsorized_scale(
        z, best_z=MEASURED_WINSOR_Z, worst_z=-MEASURED_WINSOR_Z, pct_best=0.0, pct_worst=1.0
    )
    return round(min(1.0, max(0.0, risk)), 4)


def rolling_return_population(closes, window=5, lookback=RETURN_POP_LOOKBACK,
                              min_sample=RETURN_POP_MIN_SAMPLE):
    """
    종가 시계열에서 겹치는 `window` 영업일 수익률 표본을 만들어 (평균, 표준편차)를 반환합니다.
    (5일 수익률을 "평소 5일 수익률 분포"와 비교하기 위한 기준선. 표본 부족 시 None)
    """
    clean = []
    for c in closes or []:
        try:
            f = float(c)
        except (TypeError, ValueError):
            continue
        if f != f or f <= 0:
            continue
        clean.append(f)
    if len(clean) <= window:
        return None
    rets = []
    for i in range(window, len(clean)):
        prev = clean[i - window]
        if prev > 0:
            rets.append((clean[i] - prev) / prev)
    if lookback:
        rets = rets[-int(lookback):]
    return compute_population_stats(rets, min_sample)


def net_flow_population(history_df, column, min_sample=NET_FLOW_MIN_SAMPLE):
    """
    누적 이력(market_history.csv)에서 특정 주체의 순매수 금액(억원) 과거 분포를 만듭니다.
    컬럼이 없거나 표본이 부족하면 None(→ 호출부에서 중립 0.5 처리).
    """
    try:
        if history_df is None or len(history_df) == 0 or column not in history_df.columns:
            return None
        values = list(history_df[column])
    except Exception:
        return None
    return compute_population_stats(values, min_sample)


def compute_historical_stats(history_df, weight_keys):
    """
    지표별 과거 평균/표준편차(z-score 정규화 기준선). 표본이 없거나 부족하면 0.5/0.15로
    안전 대체합니다 — 지표값 자체를 지어내는 게 아니라 "정규화 기준선"일 뿐이며, 호출부에서
    표본 부족 경고를 함께 표시해야 합니다.
    """
    import pandas as pd
    stats = {}
    for item in weight_keys:
        if not history_df.empty and item in history_df.columns and len(history_df) >= 2:
            mean_val = history_df[item].mean()
            std_val = history_df[item].std()
            if pd.isna(std_val) or std_val == 0:
                std_val = 0.15
            else:
                std_val = max(0.02, std_val)  # Z-Score 폭주 방지 최소 표준편차(Floor)
        else:
            mean_val = 0.5
            std_val = 0.15
        stats[item] = {"mean": mean_val, "std": std_val}
    return stats


def compute_sub_scores(current_weighted_risks, historical_stats):
    """
    원시 가중위험(0~1)을 과거 이력 대비 z-score로 정규화한 뒤 시그모이드로 0~100점
    변환합니다. scrape_daily.py(저장 시점)와 macro_view.py(미리보기)가 동일하게 호출해야
    두 화면의 척도가 항상 일치합니다(2차 감사 5-2).
    """
    sub_scores = {}
    for item, raw_val in current_weighted_risks.items():
        stat = historical_stats.get(item, {"mean": 0.5, "std": 0.15})
        z = (raw_val - stat["mean"]) / stat["std"]
        z_safe = max(-20.0, min(20.0, z))  # Overflow 방지
        sub_score = 100 / (1 + math.exp(-SIGMOID_K * z_safe))
        sub_scores[item] = round(sub_score, 2)
    return sub_scores


def compute_final_score(sub_scores, weights=None):
    """
    1차 가중평균(base_score) → 동시 충격 증폭기 적용까지의 최종 종합점수(0~100)를 계산합니다.
    weights를 넘기지 않으면 utils.constants.RISK_WEIGHTS를 씁니다. None인 sub_score(데이터
    없음)는 자동으로 가중평균·극단신호 카운트 양쪽에서 제외됩니다(중립값 대입 금지).

    반환: (score, base_score, multiplier, extreme_signal_count, available_count)
    """
    weights = weights or RISK_WEIGHTS
    available = {k: v for k, v in sub_scores.items() if v is not None and k in weights}
    total_weight = sum(weights[k] for k in available)
    if total_weight <= 0:
        raise RuntimeError("산출 가능한 위험 지표가 없어 종합 점수를 계산할 수 없습니다.")

    base_score = sum(available[k] * (weights[k] / total_weight) for k in available)
    extreme_signal_count = sum(
        1 for v in available.values() if v >= EXTREME_SUB_SCORE_HIGH or v <= EXTREME_SUB_SCORE_LOW
    )
    multiplier = compute_shock_amplifier(extreme_signal_count, len(available))
    score = 50.0 + (base_score - 50.0) * multiplier
    score = round(max(0.0, min(100.0, score)), 1)
    return score, round(base_score, 2), multiplier, extreme_signal_count, len(available)
