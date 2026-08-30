"""
tests/test_macro_scoring_coverage.py
`utils/macro_scoring.py` — **매크로 화면 상단의 "종합 위험 지수"를 실제로 만들어 내는
마지막 4단계**(과거 기준선 → z-score 정규화 → 시그모이드 0~100 → 가중평균 + 동시충격
증폭기)의 오프라인 회귀 테스트.

⚠️ 왜 이 파일이 생겼나 (2026-08-30, 커버리지 실측)
   `tests/test_macro_scoring.py` 는 **입력 쪽**(실측값 → 0~1 위험도 정규화, #68/#70)과
   가중치 재분배 산수(#69/#72)를 촘촘히 보고 있었지만, 그 뒤에 오는 **출력 쪽 4개 함수는
   한 줄도 실행되지 않고 있었습니다**:

     · `compute_shock_amplifier()`   (전체 미실행)
     · `compute_historical_stats()`  (전체 미실행)
     · `compute_sub_scores()`        (전체 미실행)
     · `compute_final_score()`       (전체 미실행)

   즉 "화면에 뜨는 종합 위험 지수 숫자 그 자체"를 계산하는 코드에 회귀 방지선이 없었습니다.
   이 모듈은 `scrape_daily.py`(저장 시점)와 `web/pages/macro_page.py`(미리보기)가 **같은
   척도를 쓰게 만드는 단일 출처**(2차 감사 5-2)라, 여기가 조용히 바뀌면 두 화면이 동시에
   틀립니다.

기대값은 코드 출력에서 베끼지 않고 상수(SIGMOID_K, SHOCK_AMPLIFIER_*)에서 손으로
계산했습니다. 네트워크·DB 불필요.

실행: python -m pytest tests/test_macro_scoring_coverage.py -v
"""
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import macro_scoring as M
from utils.constants import RISK_WEIGHTS


# =====================================================================================
# 1. 동시 충격 증폭기 — 개수가 아니라 '비율' 기준 (2차 감사 4-1)
# =====================================================================================
def test_shock_amplifier_is_neutral_when_nothing_is_measurable():
    """산출 가능한 지표가 0개면 증폭도 감쇠도 하지 않습니다(0 나눗셈 금지)."""
    assert M.compute_shock_amplifier(0, 0) == 1.0
    assert M.compute_shock_amplifier(3, None) == 1.0


def test_shock_amplifier_stays_flat_up_to_the_start_ratio():
    # 시작 기준은 3/14 — 그 이하는 증폭 없음(경계 포함)
    assert M.compute_shock_amplifier(3, 14) == 1.0
    assert M.compute_shock_amplifier(1, 6) == 1.0
    assert M.compute_shock_amplifier(0, 6) == 1.0


def test_shock_amplifier_is_winsorized_at_the_max_ratio():
    assert M.compute_shock_amplifier(8, 14) == M.SHOCK_AMPLIFIER_MAX
    assert M.compute_shock_amplifier(6, 6) == M.SHOCK_AMPLIFIER_MAX
    assert M.SHOCK_AMPLIFIER_MAX == 1.3


def test_shock_amplifier_interpolates_linearly_between_the_two_ratios():
    """
    지표 6개 중 2개 극단 = 33.33%.
      진행도 = (0.3333 - 3/14) ÷ (8/14 - 3/14) = 0.11905 ÷ 0.35714 = 1/3
      배율    = 1.0 + (1/3) × 0.3 = 1.1
    (#69 주석이 적어둔 "지표 수가 줄면 같은 2개도 증폭이 시작된다"는 사실의 회귀선)
    """
    assert M.compute_shock_amplifier(2, 6) == pytest.approx(1.1)
    assert M.compute_shock_amplifier(3, 6) == pytest.approx(1.24)
    assert M.compute_shock_amplifier(2, 14) == 1.0     # 같은 2개라도 14개 시절엔 증폭 없음


def test_shock_amplifier_is_monotonic_in_the_extreme_ratio():
    values = [M.compute_shock_amplifier(k, 8) for k in range(0, 9)]
    assert values == sorted(values)
    assert values[0] == 1.0 and values[-1] == M.SHOCK_AMPLIFIER_MAX


# =====================================================================================
# 2. 과거 기준선(historical_stats) — 표본이 없으면 '기준선'만 안전 대체
# =====================================================================================
def test_historical_stats_falls_back_to_the_neutral_baseline_when_there_is_no_sample():
    for frame in (pd.DataFrame(),
                  pd.DataFrame({"OTHER": [0.1, 0.2]}),
                  pd.DataFrame({"A": [0.3]})):                 # 1행뿐 → 표준편차 불가
        stats = M.compute_historical_stats(frame, ["A"])
        assert stats["A"] == {"mean": 0.5, "std": 0.15}


def test_historical_stats_replaces_a_zero_or_nan_std_with_the_default_spread():
    stats = M.compute_historical_stats(pd.DataFrame({"A": [0.3, 0.3, 0.3]}), ["A"])
    assert stats["A"]["mean"] == pytest.approx(0.3)
    assert stats["A"]["std"] == 0.15


def test_historical_stats_floors_a_tiny_std_to_stop_zscore_blowups():
    stats = M.compute_historical_stats(pd.DataFrame({"A": [0.300, 0.301, 0.300]}), ["A"])
    assert stats["A"]["std"] == 0.02        # Z-Score 폭주 방지 Floor


def test_historical_stats_uses_the_real_distribution_when_the_sample_is_usable():
    stats = M.compute_historical_stats(pd.DataFrame({"A": [0.1, 0.5, 0.9]}), ["A"])
    assert stats["A"]["mean"] == pytest.approx(0.5)
    assert stats["A"]["std"] == pytest.approx(0.4)   # 표본표준편차(ddof=1)


def test_historical_stats_covers_every_requested_key():
    stats = M.compute_historical_stats(pd.DataFrame({"A": [0.1, 0.9]}), list(RISK_WEIGHTS))
    assert set(stats) == set(RISK_WEIGHTS)


# =====================================================================================
# 3. 원시 가중위험(0~1) → 0~100 점 (시그모이드)
# =====================================================================================
def test_sub_score_is_exactly_50_at_the_historical_mean():
    assert M.compute_sub_scores({"A": 0.5}, {"A": {"mean": 0.5, "std": 0.15}}) == {"A": 50.0}


def test_sub_score_uses_the_neutral_baseline_for_an_unknown_indicator():
    """historical_stats 에 없는 지표는 크래시하지 않고 0.5/0.15 기준선을 씁니다."""
    assert M.compute_sub_scores({"A": 0.5}, {}) == {"A": 50.0}


def test_sub_score_follows_the_documented_sigmoid_with_k():
    """+1 표준편차 → 100 / (1 + e^(-1.1)) = 75.026 → 소수 둘째 자리 반올림."""
    expected = round(100 / (1 + math.exp(-M.SIGMOID_K)), 2)
    assert M.compute_sub_scores({"A": 0.65}, {"A": {"mean": 0.5, "std": 0.15}}) == {"A": expected}
    assert expected == 75.03


def test_sub_score_clamps_the_zscore_so_the_exponential_cannot_overflow():
    stats = {"A": {"mean": 0.5, "std": 0.15}}
    assert M.compute_sub_scores({"A": 1e9}, stats) == {"A": 100.0}
    assert M.compute_sub_scores({"A": -1e9}, stats) == {"A": 0.0}


def test_sub_scores_are_monotonic_in_the_raw_weighted_risk():
    stats = {"A": {"mean": 0.5, "std": 0.15}}
    values = [M.compute_sub_scores({"A": v}, stats)["A"] for v in (0.1, 0.3, 0.5, 0.7, 0.9)]
    assert values == sorted(values)


# =====================================================================================
# 4. 종합 점수 — 가중평균 → 동시 충격 증폭 → 0~100 클램프
# =====================================================================================
def test_final_score_is_the_weighted_average_amplified_by_the_shock_multiplier():
    """
    A=90(극단 고위험) / B=40, 가중치 50:50
      base = 65.0, 극단 1/2 = 50% → 배율 1.24
      score = 50 + (65 - 50) × 1.24 = 68.6
    """
    score, base, multiplier, extremes, available = M.compute_final_score(
        {"A": 90.0, "B": 40.0}, {"A": 50.0, "B": 50.0})
    assert (score, base, multiplier, extremes, available) == (68.6, 65.0, 1.24, 1, 2)


def test_missing_sub_scores_are_dropped_from_both_the_average_and_the_extreme_count():
    """§0-1: 데이터 없음(None)에 중립값 50 을 대입하지 않고 분모에서 뺍니다."""
    score, base, multiplier, extremes, available = M.compute_final_score(
        {"A": None, "B": 40.0}, {"A": 50.0, "B": 50.0})
    assert (score, base, multiplier, extremes, available) == (40.0, 40.0, 1.0, 0, 1)


def test_indicators_without_a_weight_are_ignored_rather_than_silently_weighted():
    score, base, _, _, available = M.compute_final_score(
        {"A": 50.0, "NOT_IN_WEIGHTS": 90.0}, {"A": 100.0})
    assert (score, base, available) == (50.0, 50.0, 1)


def test_final_score_is_clamped_to_the_0_100_range_after_amplification():
    assert M.compute_final_score({"A": 5.0}, {"A": 100.0})[0] == 0.0     # 50-58.5 → 0
    assert M.compute_final_score({"A": 95.0}, {"A": 100.0})[0] == 100.0  # 50+58.5 → 100


def test_final_score_refuses_to_invent_a_number_when_nothing_is_measurable():
    """§0-1: 산출할 수 있는 지표가 하나도 없으면 '50점'이 아니라 시끄럽게 실패합니다."""
    with pytest.raises(RuntimeError, match="산출 가능한 위험 지표가 없어"):
        M.compute_final_score({"A": None}, {"A": 100.0})
    with pytest.raises(RuntimeError):
        M.compute_final_score({}, {"A": 100.0})
    with pytest.raises(RuntimeError):
        M.compute_final_score({"UNKNOWN": 50.0}, {"A": 100.0})


def test_final_score_defaults_to_the_shared_risk_weights():
    """weights 를 안 넘기면 utils.constants.RISK_WEIGHTS 를 써야 합니다(단일 출처)."""
    sub_scores = {key: 50.0 for key in RISK_WEIGHTS}
    assert M.compute_final_score(sub_scores) == M.compute_final_score(sub_scores, RISK_WEIGHTS)
    assert M.compute_final_score(sub_scores)[4] == len(RISK_WEIGHTS)


def test_extreme_signal_count_uses_both_ends_of_the_scale():
    """공포(85 이상)와 과열/무풍(15 이하)은 둘 다 '극단'으로 셉니다."""
    weights = {"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0}
    _, _, _, extremes, _ = M.compute_final_score(
        {"A": M.EXTREME_SUB_SCORE_HIGH, "B": M.EXTREME_SUB_SCORE_LOW,
         "C": 50.0, "D": 60.0}, weights)
    assert extremes == 2      # 경계값은 포함(>= / <=)


def test_a_completely_average_market_scores_50_regardless_of_the_multiplier():
    """모든 지표가 정확히 평균이면 증폭기를 곱해도 50 에서 움직이지 않아야 합니다."""
    weights = {"A": 50.0, "B": 50.0}
    assert M.compute_final_score({"A": 50.0, "B": 50.0}, weights)[0] == 50.0


# =====================================================================================
# 5. 이력 컬럼 분포 — 읽을 수 없는 입력은 예외를 흘리지 않고 '표본 없음'
# =====================================================================================
class _BrokenFrame:
    """`columns` 접근 자체가 터지는 손상된 입력(§0-1 — 크래시 대신 '모름')."""
    def __len__(self):
        return 5

    @property
    def columns(self):
        raise RuntimeError("손상된 이력 프레임")


def test_history_column_population_returns_none_for_unreadable_input():
    assert M.history_column_population(None, "A") is None
    assert M.history_column_population(pd.DataFrame(), "A") is None
    assert M.history_column_population(pd.DataFrame({"B": [1, 2]}), "A") is None
    assert M.history_column_population(_BrokenFrame(), "A") is None


def test_net_flow_population_is_only_an_alias_and_must_not_diverge():
    """§0-3-10: 같은 판정을 두 번 구현하지 않았는지(이름만 다른 같은 함수인지)."""
    frame = pd.DataFrame({"Stock_Net_Sell_Raw": [float(i) for i in range(30)]})
    assert (M.net_flow_population(frame, "Stock_Net_Sell_Raw")
            == M.history_column_population(frame, "Stock_Net_Sell_Raw"))
