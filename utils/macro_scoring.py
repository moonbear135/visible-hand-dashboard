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

from utils.constants import RISK_WEIGHTS, INVESTOR_WEIGHTS

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
SHOCK_AMPLIFIER_START_RATIO = 3.0 / 14.0   # 예전 '3개 이상' 기준을 증폭 시작점으로 유지
SHOCK_AMPLIFIER_MAX_RATIO = 8.0 / 14.0     # 14개 중 8개 이상 극단이면 최대 증폭으로 고정
SHOCK_AMPLIFIER_MAX = 1.3                  # 예전 최댓값(1.3)을 상한으로 유지


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
