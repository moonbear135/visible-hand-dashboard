"""
tests/test_scoring_coverage.py
`utils/scoring.py` · `utils/guardrail.py` — **화면에 뜨는 퀀트 점수·배지를 만드는 경로**의
오프라인 회귀 테스트.

⚠️ 왜 이 파일이 생겼나 (2026-08-30, 커버리지 실측)
   `coverage run -m pytest` 로 재보니 이 두 파일이 핵심 계산 계층에서 가장 낮았습니다
   (scoring.py 62% / guardrail.py 68%). 기존 방어선인 `tests/test_quant.py` 는 §0-1
   회귀(없는 값을 지어내지 않는가)만 8건 보고 있어서, **점수 상한(cap)·배지 분기·
   정합성 모순 감지처럼 "실제로 화면에 찍히는 숫자와 문구를 결정하는 코드"가 통째로
   한 번도 실행되지 않고 있었습니다.** 구체적으로 아래가 전부 미검증이었습니다.

     · PER 이상치 상한(0~300 초과분 → 12%~2% 윈저라이즈)
     · 역성장/적자 상한(횡단면 z-score → 25%~5%)
     · 목표가 초과 상한(overshoot 0~100% → 60%~20%)
     · 극단적 고평가 상한(PEGY z-score → 20%~5%)
     · 5개 배지 분기 전부 + PEGY 밴드 경계 4개
     · guardrail 의 정합성 모순 6종(①~⑥)과 그 승격 규칙
       (2026-09-03: ①②④는 같은 기간(TTM) 지표끼리 비교하는 ①'②'④'로 교체 — 연간 ROE 대 TTM 비교는 '주의'로 강등)

   테스트가 "있다"와 "실제로 뭔가를 검증한다"는 다른 주장이므로(§0-1의 정신), 여기서는
   기대값을 코드 출력에서 베끼지 않고 **명세(SPEC §5)와 상수에서 손으로 계산해** 적었습니다.

관례: `tests/test_data_sanity.py` 와 같이 `check()`/`FAILURES` 하네스 없이 순수 `assert`
만 씁니다(§0-3-10 — 승격 장치를 파일마다 복사하지 않음). 네트워크·DB·NiceGUI 불필요.

실행: python -m pytest tests/test_scoring_coverage.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import constants as C
from utils import guardrail as G
from utils import scoring as S
from utils.guardrail import apply_valuation_guardrail
from utils.scoring import calculate_quant_score


# =====================================================================================
# 공통 입력 — "모든 항목이 수집된 평범한 우량주" 하나를 기준점으로 두고 필요한 값만 바꿉니다.
#   이 기준점의 점수는 아래 test_normal_stock_scores_add_up_by_hand 에서 손으로 검산합니다.
# =====================================================================================
def base_inputs(**overrides):
    values = dict(
        f_pegy=0.5, f_roe=14.0, roic=11.0, sh_return=2.0, t_roe=12.0,
        f_per=9.0, price=50_000, f_target=70_000, growth=18.0, vol_std=1.0,
    )
    values.update(overrides)
    return values


def score(**overrides):
    return calculate_quant_score(**base_inputs(**overrides))


def base_stock(**overrides):
    """guardrail 이 통과시키는 정상 종목 1건."""
    values = dict(
        name="정상주", price=50_000, f_per=10.0, f_eps=5_000, growth=15.0,
        sh_return=5.0, g_eff=20.0, outstanding_shares=50_000_000, dps=2_500,
        t_roe=12.0, t_per=10.0, t_eps=5_000,
    )
    values.update(overrides)
    return values


# =====================================================================================
# 1. 배점 헬퍼 — 선형 보간 / z-score / 윈저라이즈
#    (매크로 점수도 이 두 함수를 그대로 재사용하므로 여기서 못 박아 두면 두 화면이 같이 지켜집니다)
# =====================================================================================
def test_piecewise_linear_interpolates_between_anchors_and_winsorizes_outside():
    knots = [(0.0, 0.0), (10.0, 10.0), (15.0, 15.0)]
    assert S._piecewise_linear(None, knots) is None      # 미수집은 0 점이 아니라 '없음'
    assert S._piecewise_linear(-3.0, knots) == 0.0       # 아래쪽 윈저라이즈
    assert S._piecewise_linear(0.0, knots) == 0.0
    assert S._piecewise_linear(5.0, knots) == 5.0        # 첫 구간 한가운데
    assert S._piecewise_linear(12.5, knots) == 12.5      # 두 번째 구간 한가운데
    assert S._piecewise_linear(15.0, knots) == 15.0
    assert S._piecewise_linear(99.0, knots) == 15.0      # 위쪽 윈저라이즈


def test_piecewise_linear_has_no_step_cliff_at_the_old_thresholds():
    """2026-08-06 2차 감사 2-3의 취지: ROE 9.9%와 10.0%가 6점 차이 나던 절벽이 없어야 합니다."""
    knots = S.FORWARD_ROE_SCORE_KNOTS
    assert abs(S._piecewise_linear(10.0, knots) - S._piecewise_linear(9.9, knots)) < 0.2
    # 그러면서도 '정도'는 반영돼야 합니다 — ROE 40% 와 15% 가 동점이면 안 됩니다는 반대 방향
    # (앵커 밖은 윈저라이즈라 동점이 맞습니다). 앵커 안에서는 단조 증가여야 합니다.
    values = [S._piecewise_linear(x, knots) for x in (0.0, 3.0, 7.0, 10.0, 13.0, 15.0)]
    assert values == sorted(values) and values[0] < values[-1]


def test_population_zscore_returns_none_when_it_cannot_compare():
    assert S._population_zscore(5.0, None) is None       # population 통계 없음
    assert S._population_zscore(None, (1.0, 1.0)) is None
    assert S._population_zscore(5.0, (1.0, 0.0)) is None  # 표준편차 0 → 비교 불가
    assert S._population_zscore(5.0, (1.0, 2.0)) == 2.0


def test_winsorized_scale_covers_both_directions_and_the_no_data_midpoint():
    # 오름차순(z 가 클수록 나쁨) — 극단 고평가 상한이 쓰는 방향
    assert S._winsorized_scale(-1.0, 0.0, 3.0, 20.0, 5.0) == 20.0
    assert S._winsorized_scale(3.0, 0.0, 3.0, 20.0, 5.0) == 5.0
    assert S._winsorized_scale(1.5, 0.0, 3.0, 20.0, 5.0) == 12.5
    # 내림차순(z 가 작을수록 나쁨) — 역성장 상한이 쓰는 방향
    assert S._winsorized_scale(1.0, 0.0, -3.0, 25.0, 5.0) == 25.0
    assert S._winsorized_scale(-3.0, 0.0, -3.0, 25.0, 5.0) == 5.0
    assert S._winsorized_scale(-1.5, 0.0, -3.0, 25.0, 5.0) == 15.0
    # 비교할 데이터가 없으면 최악도 최선도 주지 않고 중간값(§0-1)
    assert S._winsorized_scale(None, 0.0, -3.0, 25.0, 5.0) == 15.0
    assert S._winsorized_scale(None, 0.0, 3.0, 20.0, 5.0) == 12.5


# =====================================================================================
# 2. 고성장(기저효과) 보수화 — f_pegy 값 자체는 절대 건드리지 않고 '점수만' 깎는 장치
# =====================================================================================
def test_growth_pegy_score_ratio_is_flat_below_the_threshold_and_winsorized_above():
    assert S._growth_pegy_score_ratio(None) == S.GROWTH_ADJ_SCORE_RATIO_MAX
    assert S._growth_pegy_score_ratio(0.0) == S.GROWTH_ADJ_SCORE_RATIO_MAX
    assert S._growth_pegy_score_ratio(99.9) == S.GROWTH_ADJ_SCORE_RATIO_MAX
    assert S._growth_pegy_score_ratio(100.0) == S.GROWTH_ADJ_SCORE_RATIO_MAX  # 경계는 무보정
    # 기준선 +150%p → 심각도 캡(200%p)의 75% → 1.0 - 0.75×0.8 = 0.4
    assert S._growth_pegy_score_ratio(250.0) == pytest.approx(0.4)
    # 캡 밖은 전부 최저 배율(윈저라이즈)
    assert S._growth_pegy_score_ratio(300.0) == pytest.approx(S.GROWTH_ADJ_SCORE_RATIO_MIN)
    assert S._growth_pegy_score_ratio(4000.0) == pytest.approx(S.GROWTH_ADJ_SCORE_RATIO_MIN)


def test_extreme_growth_caps_the_pegy_score_but_never_the_pegy_value_itself():
    """
    2026-08-06 자기모순 버그(배지는 '고평가'인데 목표가는 '+150% 상승여력') 재발 방지선.
    f_pegy=0.5 는 '강력 저평가' 밴드 그대로 두고, PEGY 점수만 35 → 14 점으로 줄어야 합니다.
    """
    normal = score(growth=18.0)
    capped = score(growth=250.0)
    assert normal["growth_score_capped"] is False
    assert capped["growth_score_capped"] is True
    assert capped["badge"] == normal["badge"] == "🟢 강력 저평가"   # 배지는 그대로
    assert capped["score_max"] == normal["score_max"] == 100
    # 35 × 0.4 = 14 점 → 정상 대비 21 점 감소
    assert normal["quant_score"] - capped["quant_score"] == 21


# =====================================================================================
# 3. 정상 채점 — 손으로 검산한 합계와 정확히 같아야 합니다
# =====================================================================================
def test_normal_stock_scores_add_up_by_hand():
    """
    PEGY 0.5(<0.65)       → 35
    Forward ROE 14%       → 10 + (14-10)/5×5      = 14
    ROIC 11%              → 10 + (11-8)/4×5       = 13.75
    주주환원 2%           →  8 + (2-1)/2×6        = 11
    Trailing ROE 12%(>10) → 10
    변동성 1.0%(<2.0)     →  5
    합계 88.75 → 반올림 89 / 만점 100
    """
    result = score()
    assert result["raw_score"] == 89
    assert result["quant_score"] == 89
    assert result["score_max"] == 100
    assert result["excluded_items"] == []
    assert result["is_cutoff"] is False
    assert result["forward_available"] is True
    assert result["pegy_scoring_available"] is True
    assert result["badge"] == "🟢 강력 저평가"


@pytest.mark.parametrize("f_pegy, badge, expected_score", [
    (0.649, "🟢 강력 저평가", 89),   # 35점 구간
    (0.65, "🟢 저평가", 82),         # 28점 구간 (89 - 7)
    (0.949, "🟢 저평가", 82),
    (0.95, "🟡 적정가 형성", 74),    # 20점 구간
    (1.349, "🟡 적정가 형성", 74),
    (1.35, "🔴 고평가 관망", 62),    # 8점 구간
])
def test_pegy_bands_drive_badge_and_score_from_the_same_boundaries(f_pegy, badge, expected_score):
    """
    2026-08-06 2차 감사 2-2: 배지 구간과 점수 구간이 서로 다른 사전에 있어서 f_pegy=0.90 이
    '🟢 저평가' 배지인데 점수는 한 단계 아래를 받던 버그의 회귀 방지선입니다.
    """
    result = score(f_pegy=f_pegy, f_target=None)
    assert result["badge"] == badge
    assert result["quant_score"] == expected_score


def test_score_band_boundaries_come_from_the_badge_band_constants():
    """점수 구간표가 배지 경계 상수 그 자체를 참조하는지(숫자를 두 번 적지 않았는지)."""
    assert [boundary for boundary, _ in S.PEGY_SCORE_BANDS] == [
        S.PEGY_BAND_STRONG_UNDER, S.PEGY_BAND_UNDER,
        S.PEGY_BAND_FAIR, C.PEGY_EXTREME_OVERVALUED,
    ]


# =====================================================================================
# 4. 배점 제외 — 수집 못 한 항목은 '중립값'이 아니라 만점에서 빠집니다 (§0-1)
# =====================================================================================
def test_missing_dividend_is_excluded_from_the_denominator_not_scored_as_zero():
    result = score(sh_return=None)
    assert result["score_max"] == 80
    assert result["quant_score"] == 78            # 89 - 11(배당 획득분)
    assert result["excluded_items"] == ["배당수익률 20점 (데이터 없음 — 무배당과 구분)"]


def test_confirmed_zero_dividend_is_scored_zero_not_excluded():
    """미수집(None)과 '무배당 확정(0%)'은 다릅니다 — 0% 는 배점에 들어가고 0 점입니다."""
    result = score(sh_return=0.0)
    assert result["score_max"] == 100
    assert result["excluded_items"] == []
    assert result["quant_score"] == 78            # 89 - 11


def test_volatility_is_not_counted_twice_when_the_collector_already_penalised_growth():
    result = score(vol_penalty=1.18, vol_std=5.0)
    assert result["score_max"] == 95
    assert result["quant_score"] == 84            # 89 - 5(변동성 만점분)
    assert result["excluded_items"] == [
        "변동성 5점 (실효성장률에 이미 변동성 벌점 반영됨 — 이중 계상 방지로 제외)"
    ]


def test_legacy_volatility_string_is_only_used_when_there_is_no_measured_value():
    assert score(vol_std=None, vol="🟢 정상 (1.2%)")["quant_score"] == 89
    assert score(vol_std=None, vol="⚡ 변동성 확대")["quant_score"] == 85   # 5점 → 1점
    missing = score(vol_std=None, vol="❔ 변동성 데이터 없음")
    assert missing["score_max"] == 95
    assert missing["excluded_items"] == ["변동성 5점 (데이터 없음)"]


def test_measured_volatility_is_scored_on_the_real_number_not_the_display_string():
    """2026-08-06 2차 감사 2-4: 화면 문구만 바꿔도 점수가 바뀌던 구조를 막습니다."""
    assert score(vol_std=2.0)["quant_score"] == 89        # 기준선 이하 = 만점
    assert score(vol_std=7.0)["quant_score"] == 87        # 5 → 3 점 (88.75 - 2 = 86.75)
    assert score(vol_std=12.0)["quant_score"] == 85       # 최저 1 점
    assert score(vol_std=99.0)["quant_score"] == 85       # 윈저라이즈


# =====================================================================================
# 5. Guardrail 0 — 진짜 측정 불가는 숫자를 만들지 않고 None
# =====================================================================================
@pytest.mark.parametrize("overrides", [
    {"price": 0},
    {"price": None},
    {"price": -1},
    {"t_roe": None},
])
def test_missing_trailing_basics_return_none_instead_of_a_fabricated_score(overrides):
    result = score(**overrides)
    assert result["quant_score"] is None
    assert result["raw_score"] is None
    assert result["score_max"] is None
    assert result["is_cutoff"] is True
    assert result["forward_available"] is False
    assert result["badge"] == "🔴 데이터 없음 (측정 불가)"
    assert result["excluded_items"] == ["전 항목 (Trailing 기초 데이터 없음)"]


# =====================================================================================
# 6. PER 이상치 상한 — 오염 정도에 비례해서 12%~2% 로 윈저라이즈
# =====================================================================================
def test_per_extreme_caps_the_score_in_proportion_to_how_polluted_the_per_is():
    """
    f_per = 400 → 300 초과분 100 → cap% = 12 - (100/300)×10 = 8.667%
    PEGY 35점이 빠져 만점 65 → 상한 round(8.667×65/100) = 6 점
    """
    result = score(f_per=400.0)
    assert result["forward_available"] is False
    assert result["score_max"] == 65
    assert result["raw_score"] == 54
    assert result["quant_score"] == 6
    assert result["is_cutoff"] is True
    assert result["badge"] == "🔴 데이터 이상/극단고평가 (PER 검증 실패)"
    assert result["excluded_items"] == [
        "PEGY 밸류에이션 35점 (Forward PER 범위 초과 — 데이터 오염 의심)"
    ]


def test_non_positive_per_is_treated_as_maximum_pollution():
    """PER<=0 은 '얼마나 벗어났는지'를 잴 수 없으므로 최대 심각도(=최저 상한 2%)."""
    result = score(f_per=-1.0)
    assert result["quant_score"] == 1            # round(2 × 65/100)
    assert result["is_cutoff"] is True


def test_worse_per_pollution_never_scores_higher_than_milder_pollution():
    scores = [score(f_per=p)["quant_score"] for p in (301.0, 400.0, 600.0, 900.0)]
    assert scores == sorted(scores, reverse=True)


# =====================================================================================
# 7. 역성장/적자 상한 — 횡단면(z-score) 대비 심각도로 25%~5%
# =====================================================================================
def test_negative_growth_excludes_pegy_and_caps_by_cross_sectional_severity():
    """성장률 -5%(평균 10 / 표준편차 5 → z=-3.0, 최악 구간) → 상한 5% × 만점 65 = 3점."""
    result = score(growth=-5.0, f_pegy=1.0, t_roe=5.0,
                   growth_pop_stats=(10.0, 5.0), roe_pop_stats=(10.0, 5.0))
    assert result["forward_available"] is True          # 컨센서스는 존재함
    assert result["pegy_scoring_available"] is False    # 다만 PEGY 로 채점은 불가
    assert result["score_max"] == 65
    assert result["quant_score"] == 3
    assert result["is_cutoff"] is True
    assert result["badge"] == "🔴 실적 역성장/적자 (위험)"
    assert result["excluded_items"] == [
        "PEGY 밸류에이션 35점 (역성장/적자 상태 — PEGY 공식 성립 불가)"
    ]


def test_negative_growth_without_population_stats_falls_back_to_the_midpoint_cap():
    """표본이 없으면 최악(5%)도 최선(25%)도 주지 않고 중간 15% — 예전 flat 15점의 안전망."""
    result = score(growth=-5.0, f_pegy=1.0, t_roe=5.0)
    assert result["quant_score"] == 10                  # round(15 × 65/100)
    assert result["is_cutoff"] is True


def test_trailing_only_deficit_uses_the_trailing_specific_badge():
    """Forward 컨센서스가 아예 없으면 t_roe 만으로 판단하고 전용 배지를 씁니다."""
    result = score(f_per=None, growth=None, f_pegy=None, t_roe=-3.0,
                   roe_pop_stats=(10.0, 5.0))
    assert result["forward_available"] is False
    assert result["badge"] == "🔴 Trailing 실적 역성장/적자 (위험)"
    assert result["quant_score"] == 5                   # z=-2.6 → 7.667% × 65
    assert result["excluded_items"] == [
        "PEGY 밸류에이션 35점 (Forward 데이터 없음 — 애널리스트 컨센서스 미제공)"
    ]


def test_forward_missing_but_healthy_trailing_gets_the_neutral_blue_badge():
    """
    2026-08-06 버그 수정 회귀선: 컨센서스가 없다는 것과 실적이 나쁘다는 것은 다릅니다.
    Trailing 이 멀쩡하면 컷오프가 아니라 '🔵 Trailing만 검증됨' 중립 배지입니다.
    """
    result = score(f_per=None, growth=None, f_pegy=None, t_roe=8.0)
    assert result["badge"] == "🔵 Trailing만 검증됨 (Forward 데이터 없음)"
    assert result["is_cutoff"] is False
    assert result["score_max"] == 65
    assert result["quant_score"] == 52


# =====================================================================================
# 8. 목표주가 교차검증 — 현재가가 목표가를 넘었으면 저평가 배지 금지
# =====================================================================================
def test_price_above_target_caps_the_score_in_proportion_to_the_overshoot():
    """현재가 50,000 / 목표가 40,000 → overshoot 25% → cap 60 - 0.25×40 = 50%."""
    result = score(f_target=40_000)
    assert result["quant_score"] == 50
    assert result["badge"] == "🔴 목표가 초과 (고평가 관망)"
    assert result["is_cutoff"] is False        # 컷오프가 아니라 상한만 적용


def test_target_reached_but_below_15pct_gets_the_amber_reached_badge():
    result = score(f_target=48_000)            # overshoot 4.17% → cap 58.33%
    assert result["quant_score"] == 58
    assert result["badge"] == "🟡 목표가 달성 (적정가)"


def test_bigger_overshoot_never_scores_higher_than_a_smaller_one():
    scores = [score(f_target=t)["quant_score"] for t in (49_000, 40_000, 30_000, 20_000)]
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] == 20                    # 목표가의 2배 초과분은 전부 20% 상한


def test_capped_target_price_skips_the_cross_check_entirely():
    """
    2차 감사 1-3: 목표가가 '현재가×2.5' 캡 상수면 현재가와 비교해봐야 동어반복이라
    비교 자체를 건너뜁니다(캡 종목이 조용히 감점당하지 않아야 합니다).
    """
    capped = score(f_target=40_000, f_target_capped=True)
    assert capped["quant_score"] == 89
    assert capped["badge"] == "🟢 강력 저평가"


# =====================================================================================
# 9. 극단적 고평가 하드컷오프
# =====================================================================================
def test_extreme_overvaluation_caps_by_population_zscore_of_pegy():
    """f_pegy 2.5 (평균 1.0 / 표준편차 0.5 → z=3.0, 최악) → 상한 5% × 만점 100 = 5점."""
    result = score(f_pegy=2.5, f_per=30.0, pegy_pop_stats=(1.0, 0.5))
    assert result["quant_score"] == 5
    assert result["is_cutoff"] is True
    assert result["badge"] == "🔴 극단적 고평가 (위험)"


def test_extreme_overvaluation_without_population_stats_uses_the_midpoint_cap():
    result = score(f_pegy=2.5, f_per=30.0)
    assert result["quant_score"] == 12         # (20+5)/2 = 12.5% × 100
    assert result["is_cutoff"] is True


def test_high_forward_per_alone_triggers_the_hard_cutoff_even_if_pegy_looks_cheap():
    """PEGY 가 싸 보여도 Forward PER 70배 이상이면 하드컷오프입니다(둘 중 하나면 발동)."""
    ok = score(f_per=C.FPER_EXTREME_OVERVALUED - 0.1)
    hit = score(f_per=C.FPER_EXTREME_OVERVALUED)
    assert ok["badge"] == "🟢 강력 저평가" and ok["is_cutoff"] is False
    assert hit["badge"] == "🔴 극단적 고평가 (위험)" and hit["is_cutoff"] is True


def test_pegy_extreme_boundary_is_inclusive():
    assert score(f_pegy=C.PEGY_EXTREME_OVERVALUED - 0.01, f_per=30.0)["is_cutoff"] is False
    assert score(f_pegy=C.PEGY_EXTREME_OVERVALUED, f_per=30.0)["is_cutoff"] is True


# =====================================================================================
# 10. guardrail — 정합성 모순 크로스체크 (2026-08-06 2차 감사 6-2)
# =====================================================================================
def test_annual_roe_deficit_with_ttm_profit_is_a_period_mismatch_note_not_a_contradiction():
    """
    2026-09-03 — 옛 ①②④는 t_roe(시가총액표 ROE = 연간 결산 기준)와 t_per/t_eps(aside
    'PER|EPS(YYYY.MM)' = 최근 4분기 TTM)를 같은 기간처럼 비교해, 흑자 전환 종목 20개
    (삼성SDI·에코프로·펄어비스 등, 2026-09-03 실제 스냅샷)를 "부호 유실 모순"으로
    오탐하고 검증 미통과(is_unverified)로 승격시켰습니다. 기간이 다른 지표끼리는
    '주의(기간 불일치)'로 기록만 하고 승격하지 않아야 합니다.
    """
    result = apply_valuation_guardrail(
        base_stock(t_roe=-3.15, t_per=1176.86, t_per_measured=1176.86, t_eps=458, graham_target=56_338))
    notes = result["consistency_warnings"]
    assert len(notes) == 1 and notes[0].startswith("주의(기간 불일치)")
    assert "연간" in notes[0] and "TTM" in notes[0] and "직접 비교 불가" in notes[0]
    assert "PER 1176.86배" in notes[0] and "EPS 458원" in notes[0] and "56,338원" in notes[0]
    assert not any(w.startswith("모순") for w in notes)
    assert result["is_unverified"] is False          # 승격 없음 — 퀀트 풀·Forward 카드 유지
    assert result["is_valid"] is True
    assert result.get("unverified_reason") is None
    assert result["consistency_warnings"] == result["data_issues"]   # 기록은 남김(감사 추적)


def test_period_mismatch_note_falls_back_to_t_per_when_measured_value_is_absent():
    # t_per_measured 가 없는 옛 스냅샷/합성 입력도 같은 판정(부호 판정에 t_per 를 대신 사용)
    result = apply_valuation_guardrail(base_stock(t_roe=-5.0, t_per=10.0, t_eps=None))
    assert any(w.startswith("주의(기간 불일치)") and "PER 10.0배" in w for w in result["consistency_warnings"])
    assert result["is_unverified"] is False


def test_period_mismatch_note_ignores_calculated_eps_and_needs_a_positive_ttm_value():
    # 🧮 계산값(price ÷ PER 역산)은 실측이 아니라 근거로 쓰지 않습니다
    calculated = apply_valuation_guardrail(
        base_stock(t_roe=-5.0, t_per=None, t_eps=5_000, t_eps_calculated=True))
    assert calculated.get("consistency_warnings") is None
    assert calculated["is_unverified"] is False
    # 진짜 적자(연간 ROE<0 · TTM PER<0 · TTM EPS 없음)는 기간 불일치가 아니므로 아무 경고도 없음
    genuine_loss = apply_valuation_guardrail(
        base_stock(t_roe=-5.19, t_per=None, t_per_measured=-50.81, t_eps=None))
    assert genuine_loss.get("consistency_warnings") is None


def test_same_period_per_sign_disagreement_between_sources_is_a_contradiction():
    """①' — 같은 기간(TTM)인 상세 페이지 PER 과 시가총액표 PER 의 부호가 다르면 진짜 부호 유실 신호."""
    result = apply_valuation_guardrail(
        base_stock(t_roe=12.0, t_per=10.0, t_per_measured=10.0, t_per_primary=10.0, t_per_secondary=-10.2))
    assert any(w.startswith("모순") and "출처 간 불일치" in w and "PER 부호 유실" in w
               for w in result["consistency_warnings"])
    assert result["is_unverified"] is True          # 모순은 검증 미통과로 승격
    assert result["is_valid"] is True               # 다만 종목 전체를 차단하지는 않음
    assert "데이터 정합성 모순" in result["unverified_reason"]
    # 두 출처가 같은 부호(정상)면 경고 없음 — 값 차이는 3단계 교차검증(3%)의 몫
    ok = apply_valuation_guardrail(
        base_stock(t_per=10.0, t_per_measured=10.0, t_per_primary=10.0, t_per_secondary=10.2))
    assert ok.get("consistency_warnings") is None
    # 한쪽이 없으면(옛 스냅샷·aside 파싱 실패) 판정하지 않음 — 없는 값으로 지어내지 않음(§0-1)
    partial = apply_valuation_guardrail(base_stock(t_per_measured=-10.0, t_per=None, t_eps=None, t_per_secondary=-10.0))
    assert partial.get("consistency_warnings") is None


def test_same_period_per_and_eps_sign_disagreement_is_a_contradiction():
    """②' — 같은 줄(aside, TTM)에서 읽은 PER 과 EPS 의 부호가 다르면 정규식이 한쪽 부호만 잃은 것."""
    result = apply_valuation_guardrail(base_stock(t_per=10.0, t_per_measured=10.0, t_eps=-5_000))
    assert any(w.startswith("모순") and "부호가 다름" in w for w in result["consistency_warnings"])
    assert result["is_unverified"] is True
    # 계산값 EPS 는 판정 대상이 아님
    calc = apply_valuation_guardrail(base_stock(t_per=10.0, t_per_measured=10.0, t_eps=-5_000, t_eps_calculated=True))
    assert not any(w.startswith("모순") for w in (calc.get("consistency_warnings") or []))


def test_dps_without_dividend_yield_is_flagged_as_a_conversion_miss():
    result = apply_valuation_guardrail(base_stock(dps=2_500, sh_return=0.0))
    assert any("배당수익률 환산 누락" in w for w in result["consistency_warnings"])
    assert result["is_unverified"] is True


def test_graham_number_with_non_positive_ttm_eps_is_flagged():
    """④' — 그레이엄 넘버는 'TTM EPS>0 일 때만 산출'이 규칙이므로, EPS≤0 인데 값이 있으면 수집 로직 오류."""
    result = apply_valuation_guardrail(
        base_stock(t_roe=-5.0, t_per=None, t_eps=-1_000, graham_target=30_000))
    assert any("그레이엄" in w and w.startswith("모순") for w in result["consistency_warnings"])
    assert result["is_unverified"] is True
    # 연간 ROE 만 적자이고 TTM EPS 는 흑자면 산출 규칙 위반이 아님 → '주의(기간 불일치)'에만 언급
    turnaround = apply_valuation_guardrail(
        base_stock(t_roe=-5.0, t_per=12.0, t_per_measured=12.0, t_eps=4_000, graham_target=30_000))
    assert not any(w.startswith("모순") for w in turnaround["consistency_warnings"])
    assert any("그레이엄 넘버 30,000원은 TTM EPS 기준 산출값" in w for w in turnaround["consistency_warnings"])
    assert turnaround["is_unverified"] is False


def test_real_snapshot_turnaround_stocks_are_not_promoted_to_unverified():
    """
    실데이터 회귀 가드 — 2026-09-03 스냅샷에서 연간 ROE<0 · TTM PER/EPS>0 인 종목 20개
    (삼성SDI 006400 등)가 검증 미통과로 승격되지 않아야 합니다. 스냅샷이 갱신돼 그런 종목이
    하나도 없으면 skip (없는 데이터를 지어내서 검증하지 않음, §0-1).
    """
    import copy
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "kospi200_pegy_latest.json")
    if not os.path.exists(path):
        pytest.skip("실제 스냅샷 없음")
    with open(path, encoding="utf-8") as f:
        stocks = json.load(f).get("stocks") or []
    targets = [
        s for s in stocks
        if s.get("t_roe") is not None and s["t_roe"] < 0
        and s.get("t_eps") is not None and s["t_eps"] > 0 and not s.get("t_eps_calculated")
        and s.get("t_per_measured") is not None and s["t_per_measured"] > 0
    ]
    if not targets:
        pytest.skip("현재 스냅샷에 연간 ROE 적자 · TTM 흑자 조합 종목이 없음")
    guard_set = ("consistency_warnings", "is_unverified", "unverified_reason", "reject_reason",
                 "forward_data_missing", "forward_missing_fields", "is_negative_growth",
                 "dividend_data_unverified", "dividend_unverified_reason")
    for s in targets:
        pre = copy.deepcopy(s)
        old_warnings = set(pre.get("consistency_warnings") or [])
        pre["data_issues"] = [i for i in (pre.get("data_issues") or []) if i not in old_warnings]
        for k in guard_set:
            pre.pop(k, None)
        pre["is_valid"] = pre.get("validation_error") is None    # 3단계 하네스 판정만 승계
        result = apply_valuation_guardrail(pre)
        contradictions = [w for w in (result.get("consistency_warnings") or []) if w.startswith("모순")]
        assert not contradictions, f"{s['name']}({s['code']}): {contradictions}"
        assert any(w.startswith("주의(기간 불일치)") for w in result["consistency_warnings"]), s["name"]
        assert result["is_unverified"] is False, s["name"]


def test_collector_emits_both_ttm_per_sources_for_the_same_period_sign_check():
    """①' 배선 — 수집기가 상세 페이지 PER(t_per_primary)·시가총액표 PER(t_per_secondary)을 따로 남겨야 합니다."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "collector_kospi200.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert '"t_per_primary": n_t_per' in src
    assert '"t_per_secondary": raw_per' in src


def test_graham_number_far_above_price_is_a_warning_but_not_a_contradiction():
    """'이상치'는 기록만 하고 검증 상태를 꺾지 않습니다 — 모순(①②④)과 등급이 다릅니다."""
    limit = G.GRAHAM_OUTLIER_MULTIPLE
    result = apply_valuation_guardrail(base_stock(graham_target=int(50_000 * limit) + 1))
    assert any(w.startswith("이상치") for w in result["consistency_warnings"])
    assert result["is_unverified"] is False
    assert result["is_valid"] is True


def test_capped_target_price_is_recorded_so_the_screen_can_say_it_is_not_a_calculation():
    result = apply_valuation_guardrail(base_stock(f_target_capped=True))
    assert any(w.startswith("주의") and "상한값" in w for w in result["consistency_warnings"])
    assert result["is_unverified"] is False


def test_a_clean_stock_gets_no_consistency_warnings_at_all():
    result = apply_valuation_guardrail(base_stock())
    assert result.get("consistency_warnings") is None
    assert result["is_valid"] is True and result["is_unverified"] is False


# =====================================================================================
# 11. guardrail — 차단 규칙 (SPEC §5-4)
# =====================================================================================
def test_missing_price_is_the_only_hard_block_for_trailing_data():
    result = apply_valuation_guardrail(base_stock(price=0))
    assert result["is_valid"] is False
    assert result["reject_reason"] == "필수 지표 수집 실패 (price)"


@pytest.mark.parametrize("f_per", [0.0, -1.0, 300.1, 5_000.0])
def test_polluted_per_is_blocked(f_per):
    result = apply_valuation_guardrail(base_stock(f_per=f_per))
    assert result["is_valid"] is False
    assert result["reject_reason"] == "PER/주가 산출 범위 초과 또는 데이터 오염"


def test_outstanding_shares_below_the_sanity_floor_is_blocked():
    result = apply_valuation_guardrail(base_stock(outstanding_shares=46))
    assert result["is_valid"] is False
    assert "상장주식수 파싱 오류 의심" in result["reject_reason"]
    assert f"{G.MIN_OUTSTANDING_SHARES:,}" in result["reject_reason"]


def test_missing_g_eff_is_blocked_only_when_forward_data_actually_exists():
    blocked = apply_valuation_guardrail(base_stock(g_eff=None))
    assert blocked["is_valid"] is False
    assert blocked["reject_reason"] == "실효성장률(g_eff) 산출 불가"
    # Forward 자체가 없는 종목은 g_eff 도 당연히 없으므로 이중 차단하지 않습니다
    forward_missing = apply_valuation_guardrail(
        base_stock(f_per=None, growth=None, f_eps=None, g_eff=None))
    assert forward_missing["is_valid"] is True
    assert forward_missing["forward_data_missing"] is True
    assert forward_missing["forward_missing_fields"] == ["f_per", "growth", "f_eps"]


def test_negative_effective_growth_is_marked_but_never_blocked():
    result = apply_valuation_guardrail(base_stock(g_eff=-3.0))
    assert result["is_negative_growth"] is True
    assert result["is_valid"] is True and result["is_unverified"] is False


def test_guardrail_never_upgrades_an_upstream_failure():
    """§0-1: 상위 판정은 AND 로만 결합합니다 — False 를 True 로 되돌리면 안 됩니다."""
    result = apply_valuation_guardrail(
        base_stock(is_valid=False, validation_error="2단계 산티 체크 실패"))
    assert result["is_valid"] is False
    assert result["is_unverified"] is True
    assert "2단계 산티 체크 실패" in result["unverified_reason"]


def test_upstream_unverified_flag_is_inherited_too():
    result = apply_valuation_guardrail(base_stock(is_unverified=True))
    assert result["is_unverified"] is True
    assert result["is_valid"] is True


# =====================================================================================
# 12. guardrail — 배당 데이터 판정 (미수집 vs 무배당 확정)
# =====================================================================================
def test_uncollected_dividend_is_marked_as_unverified_not_as_zero_dividend():
    result = apply_valuation_guardrail(base_stock(dps=None, sh_return=None))
    assert result["dividend_data_unverified"] is True
    assert "'배당이 없다'는 뜻이 아니라" in result["dividend_unverified_reason"]
    assert result["is_valid"] is True and result["is_unverified"] is False


def test_not_collected_source_marker_also_triggers_the_unverified_badge():
    result = apply_valuation_guardrail(base_stock(dps=0, sh_return=0.0,
                                                  dps_source="not_collected"))
    assert result["dividend_data_unverified"] is True
    assert "수집하지 못했습니다" in result["dividend_unverified_reason"]


@pytest.mark.parametrize("name", G.HIGH_DIVIDEND_SECTOR_KEYWORDS)
def test_high_dividend_sector_with_confirmed_zero_dividend_gets_the_amber_badge(name):
    result = apply_valuation_guardrail(base_stock(name=f"테스트{name}", dps=0, sh_return=0.0))
    assert result["dividend_data_unverified"] is True
    assert "배당 필수 업종" in result["dividend_unverified_reason"]
    # 2026-08-06 오너 지시: 이것만으로 종목 전체를 막지는 않습니다
    assert result["is_valid"] is True and result["is_unverified"] is False


def test_preferred_share_suffix_is_not_treated_as_a_high_dividend_sector():
    """2차 감사 6-1: '우B' 는 업종이 아니라 주식의 종류라 목록에서 빠졌습니다."""
    assert "우B" not in G.HIGH_DIVIDEND_SECTOR_KEYWORDS
    result = apply_valuation_guardrail(base_stock(name="삼성전자2우B", dps=0, sh_return=0.0))
    assert result.get("dividend_data_unverified") is None


# =====================================================================================
# 13. ENGINEERING_SPEC §5 대조 — 명세의 숫자와 코드의 숫자가 같은가
# =====================================================================================
def test_score_allocation_matches_spec_5_3_table():
    """
    SPEC §5-3 배점표: PEGY 35 / 자본효율성 30 / 주주환원 20 / Trailing 10 / 변동성 5 = 100
    (코드는 자본효율성 30 을 ROE 15 + ROIC 15 로 나눠 가지고 있습니다)
    """
    assert S.PEGY_SCORE_MAX == 35
    assert max(y for _, y in S.FORWARD_ROE_SCORE_KNOTS) == 15
    assert max(y for _, y in S.ROIC_SCORE_KNOTS) == 15
    assert max(y for _, y in S.DIVIDEND_SCORE_KNOTS) == 20
    assert max(y for _, y in S.TRAILING_ROE_SCORE_KNOTS) == 10
    assert S.VOL_SCORE_MAX == 5
    assert S.PEGY_SCORE_MAX + 15 + 15 + 20 + 10 + S.VOL_SCORE_MAX == 100
    # 실제 채점 경로에서도 만점이 100 이어야 합니다(상수만 맞고 배선이 어긋나면 무의미)
    assert score()["score_max"] == 100


def test_per_extreme_threshold_has_a_single_source_shared_by_guardrail_and_scoring():
    """
    2차 감사 6-3: 'PER 300배 = 오염' 판정이 세 파일에 각각 하드코딩돼 있던 것을 상수 한
    곳으로 모았습니다. 두 모듈이 **같은 경계에서 같은 방향으로** 판정하는지 확인합니다.
    """
    assert G.PER_EXTREME_MAX is C.PER_EXTREME_MAX
    assert S.PER_EXTREME_MAX is C.PER_EXTREME_MAX

    at_limit = C.PER_EXTREME_MAX
    over_limit = C.PER_EXTREME_MAX + 0.1
    assert apply_valuation_guardrail(base_stock(f_per=at_limit))["is_valid"] is True
    assert apply_valuation_guardrail(base_stock(f_per=over_limit))["is_valid"] is False
    assert score(f_per=at_limit)["forward_available"] is True
    assert score(f_per=over_limit)["forward_available"] is False


def test_target_price_cap_multiple_is_quoted_from_the_constant_in_the_warning_text():
    result = apply_valuation_guardrail(base_stock(f_target_capped=True))
    assert f"{C.TARGET_PRICE_CAP_MULTIPLE}배" in result["consistency_warnings"][0]
