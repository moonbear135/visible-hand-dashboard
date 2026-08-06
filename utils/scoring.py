"""
utils/scoring.py
보이는 손 퀀트 종합 스코어링 엔진 (Hard Cut-off 킬러 로직 & 상황 검증 Guardrail 반영)

⚠️ 2026-08-06 개편 (오너 지적 반영):
   예전엔 "역성장/적자"·"PER 극단치" 같은 하드컷오프에 걸리면 15점/10점처럼 고정된 숫자를
   그냥 리턴했습니다. 이러면 종목이 얼마나 심각하게 나쁜지(ROE -1% vs -50%)가 점수에
   전혀 반영이 안 되고, 게다가 그 경로만 만점(score_max)을 100으로 하드코딩해서 다른
   경로(정상 스코어링, 예: 35점 만점)와 비교 자체가 안 되는 문제가 있었습니다.

   개선 방향(오너 요청: "랜덤한 가중치 말고 금융공학적 표준"):
   - 만점(score_max)은 모든 경로에서 동일하게 "오늘 이 종목에서 실제 산출 가능한 항목"만
     합산합니다(§0-1 원칙 그대로 유지, 하드컷오프 경로도 예외 없음).
   - 하드컷오프에 걸린 종목의 점수 상한(cap)은 절대적인 매직넘버가 아니라, **오늘 수집된
     종목 전체(횡단면, cross-section) 분포 대비 z-score로 얼마나 벗어나 있는지**를 재서
     정합니다. 이는 Barra/Fama-French류 퀀트 팩터 모델, CFA 커리큘럼에서 표준으로 쓰는
     "횡단면 정규화(cross-sectional normalization) + 윈저라이즈(winsorize)" 기법입니다.
     (예: 성장률이 오늘 전체 종목 평균보다 3표준편차 이상 나쁘면 최저 구간, 평균 수준이면
     그나마 나은 구간으로 배정)
   - population 통계(평균/표준편차)가 없으면(표본 부족, 유닛테스트 등) 중간값으로 안전하게
     대체합니다 — 절대 크래시하거나 지어낸 값을 쓰지 않습니다.
"""


from utils.constants import (
    PER_EXTREME_MAX,
    PEGY_EXTREME_OVERVALUED,
    FPER_EXTREME_OVERVALUED,
)

# =========================================================
# PEGY 구간 경계 — 2026-08-06 2차 감사 2-2.
# 예전엔 "점수 구간"(0.65 / 0.85 / 1.0 / 1.35 / 2.0)과 "배지 구간"(0.65 / 0.95 / 1.35)이
# 서로 다른 사전에 따로 하드코딩돼 있어서, 예컨대 f_pegy=0.90인 종목은 배지가 '🟢 저평가'인데
# 점수는 '1.0 미만 구간'(20점, 만점의 57%)만 받는 식으로 화면 설명과 점수가 어긋났습니다.
# 이제 경계값을 여기 한 곳에서만 정의하고 점수·배지가 동일한 사전을 참조합니다.
#
# 경계 근거(PEGY = PER ÷ (성장률 + 주주환원율), 피터 린치의 PEG 해석을 PEGY로 확장):
#   1.0  = 성장률만큼 PER을 주는 '이론적 적정가' (린치의 기준선)
#   0.65 = 적정가 대비 35% 이상 할인 → 강력 저평가
#   1.35 = 적정가 대비 35% 이상 할증 → 고평가 관망
#   2.0  = 성장으로 도저히 정당화 불가 → 극단적 고평가 하드컷오프
# =========================================================
PEGY_BAND_STRONG_UNDER = 0.65   # 미만: 강력 저평가
PEGY_BAND_UNDER = 0.95          # 미만: 저평가
PEGY_BAND_FAIR = 1.35           # 미만: 적정가 형성 / 이상: 고평가 관망

# PEGY 밸류에이션 카테고리 총점(35점) 및 구간별 획득 점수.
# 구간 자체는 위 밴드 경계와 1:1로 대응하며, 별도 숫자를 새로 만들지 않습니다.
PEGY_SCORE_MAX = 35
PEGY_SCORE_BANDS = [
    (PEGY_BAND_STRONG_UNDER, 35),   # < 0.65
    (PEGY_BAND_UNDER, 28),          # < 0.95
    (PEGY_BAND_FAIR, 20),           # < 1.35
    (PEGY_EXTREME_OVERVALUED, 8),   # < 2.00
]
PEGY_SCORE_WORST = 0                # >= 2.00 (극단적 고평가 하드컷오프도 별도 적용됨)


def _piecewise_linear(x, knots):
    """
    (x, y) 앵커점 목록 사이를 선형 보간하고, 양 끝 밖은 윈저라이즈(clip)합니다.

    ⚠️ 2026-08-06 2차 감사 2-3: 이 함수가 필요한 이유
       예전 배점은 `15 if roe >= 15 else (10 if roe >= 10 else 4)` 같은 계단식이라
       ROE 9.9%와 10.0%가 6점이나 차이 나고, ROE 40%와 15%는 완전히 동점이었습니다
       ("심각도/우수함의 정도"가 점수에 전혀 반영되지 않음). 앵커점(=예전 임계값)은
       그대로 두고 그 사이만 선형으로 이어 계단을 없앱니다 — 즉 기존 캘리브레이션을
       유지하면서 절벽만 제거합니다.
    """
    if x is None:
        return None
    if x <= knots[0][0]:
        return float(knots[0][1])
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            if x1 == x0:
                return float(y1)
            ratio = (x - x0) / (x1 - x0)
            return float(y0 + ratio * (y1 - y0))
    return float(knots[-1][1])


def _population_zscore(value, pop_stats):
    """
    value를 population_stats=(mean, std)로 표준화한 z-score를 반환합니다.
    population_stats가 없거나(표본 부족) std가 0이면 None(=비교 불가)을 반환합니다.
    """
    if value is None or pop_stats is None:
        return None
    mean, std = pop_stats
    if not std or std <= 0:
        return None
    return (value - mean) / std


# 성장률 기반 PEGY 점수 보수화 (기저효과 왜곡 방어) 파라미터
GROWTH_ADJ_THRESHOLD_PCT = 100.0     # 성장률이 이 값을 넘으면 기저효과 왜곡 가능성 보정 시작
GROWTH_ADJ_SEVERITY_CAP_PCT = 200.0  # 기준선 대비 +200%p 초과분부터는 최대 보정(20%)으로 고정(윈저라이즈)
GROWTH_ADJ_SCORE_RATIO_MIN = 0.20    # 성장률이 매우 극단적인 경우 PEGY 점수를 만점의 20%까지만 인정
GROWTH_ADJ_SCORE_RATIO_MAX = 1.00    # 기준선을 막 넘었을 때는 사실상 무보정(100%)


def _growth_pegy_score_ratio(growth):
    """
    성장률(growth, %)이 100%를 넘으면 애널리스트 컨센서스가 기저효과(base effect)로
    왜곡됐을 가능성을 의심해 PEGY '점수'만 보수적으로 깎습니다(0.2~1.0 배율).

    ⚠️ 2026-08-06 설계 변경 (오너 지적: "1.5로 고정하는 건 그냥 하드코딩이잖아").
    예전엔 growth>=100%면 f_pegy 자체를 max(f_pegy*2, 1.5)로 강제로 덮어썼습니다. 그 결과
    화면에 보이는 목표가·적정가 갭(원래 f_pegy 기준으로 계산)과 배지(덮어써진 f_pegy 기준)가
    서로 반대 방향을 가리키는 자기모순이 생겼습니다(예: "+150% 상승여력"인데 배지는
    "고평가 관망"). 이제는 f_pegy 자체는 절대 건드리지 않아 배지·목표가 표시가 항상 서로
    일관되게 유지되고, 대신 PEGY 카테고리 "점수"만 성장률이 기준선을 얼마나 초과했는지에
    비례해 절대거리 기준으로 윈저라이즈합니다(population z-score가 아니라 절대 기준을 쓰는
    이유는 per_extreme·VOL_PENALTY와 동일 — "동종업계 대비 밸류에이션"이 아니라 "이 성장률
    숫자 자체를 얼마나 신뢰할 수 있는가"를 보는 것이라 다른 종목과 상대비교하는 게 개념적으로
    안 맞기 때문입니다).
    """
    if growth is None or growth < GROWTH_ADJ_THRESHOLD_PCT:
        return GROWTH_ADJ_SCORE_RATIO_MAX
    excess = min(growth - GROWTH_ADJ_THRESHOLD_PCT, GROWTH_ADJ_SEVERITY_CAP_PCT)
    ratio = excess / GROWTH_ADJ_SEVERITY_CAP_PCT
    return GROWTH_ADJ_SCORE_RATIO_MAX - ratio * (GROWTH_ADJ_SCORE_RATIO_MAX - GROWTH_ADJ_SCORE_RATIO_MIN)


def _winsorized_scale(z, best_z, worst_z, pct_best, pct_worst):
    """
    횡단면 z-score를 pct_best~pct_worst 사이로 선형 매핑합니다.
    worst_z를 벗어나는 극단치는 pct_worst로, best_z를 벗어나면 pct_best로 윈저라이즈(clip)합니다.
    best_z > worst_z(내림차순, 예: 고평가일수록 나쁨)인 경우도 자동으로 처리합니다.

    z가 None이면(비교할 population 데이터가 부족) 두 값의 중간값을 반환합니다 — 데이터가
    없다고 임의로 최악/최선을 주지 않고 중립적으로 처리합니다.
    """
    if z is None:
        return (pct_best + pct_worst) / 2.0
    if best_z <= worst_z:
        if z <= best_z:
            return pct_best
        if z >= worst_z:
            return pct_worst
        ratio = (z - best_z) / (worst_z - best_z)
    else:
        if z >= best_z:
            return pct_best
        if z <= worst_z:
            return pct_worst
        ratio = (best_z - z) / (best_z - worst_z)
    return pct_best - ratio * (pct_best - pct_worst)


# =========================================================
# 카테고리별 배점 앵커 (2026-08-06 2차 감사 2-3에서 계단식 → 선형 보간으로 전환)
# 앵커 x값은 전부 예전 계단식 배점의 임계값을 그대로 가져온 것이라 캘리브레이션이 바뀌지 않습니다.
# =========================================================
# Forward ROE 15점: ROE 0%(손익분기)=0점, 10%=10점, 15% 이상=만점.
#   10/15%는 각각 예전 임계값이며, 자기자본비용(COE, 10~12%) 부근이 만점의 2/3가 되도록 배치.
FORWARD_ROE_SCORE_KNOTS = [(0.0, 0.0), (10.0, 10.0), (15.0, 15.0)]
# ROIC 15점: 0%=0점, 8%=10점, 12% 이상=만점 (8/12%는 예전 임계값, WACC 8~10% 기준).
ROIC_SCORE_KNOTS = [(0.0, 0.0), (8.0, 10.0), (12.0, 15.0)]
# 배당수익률 20점: 0%=0점, 1%=8점, 3%=14점, 5% 이상=만점 (전부 예전 임계값).
#   ⚠️ 0%는 '무배당이 확인된 경우'에만 도달합니다. 미수집(None)은 배점에서 통째로 제외됩니다.
DIVIDEND_SCORE_KNOTS = [(0.0, 0.0), (1.0, 8.0), (3.0, 14.0), (5.0, 20.0)]
# Trailing ROE 10점: 0%=0점, 6%=6점, 10% 이상=만점 (6/10%는 예전 임계값).
TRAILING_ROE_SCORE_KNOTS = [(0.0, 0.0), (6.0, 6.0), (10.0, 10.0)]

# 변동성 5점: 기준선(2.0%) 이하면 만점, 기준선 대비 +10%p 초과분부터는 최소점(1점)으로 윈저라이즈.
# (collector_kospi200.py의 VOL_THRESHOLD_PCT / VOL_PENALTY_SEVERITY_CAP_PCT와 같은 기준선·범위를
#  씁니다 — 같은 개념을 두 파일이 다르게 정의하지 않도록 값과 근거를 여기에 명시)
VOL_SCORE_MAX = 5
VOL_SCORE_KNOTS = [(2.0, 5.0), (12.0, 1.0)]

# 목표주가 교차검증 상한(2차 감사 2-1). overshoot = 현재가/목표가 - 1.0
# 0%(목표가 도달)에서 60%, +100%(목표가의 2배)부터는 20%로 윈저라이즈.
# 60/20%는 예전 플랫 캡 값(60/45%)의 상·하단을 그대로 이어받은 것이며, 달라진 점은
# "1.16배 초과와 5배 초과가 똑같이 45%"였던 절벽이 사라졌다는 것뿐입니다.
TARGET_OVERSHOOT_CAP_BEST_PCT = 60.0
TARGET_OVERSHOOT_CAP_WORST_PCT = 20.0
TARGET_OVERSHOOT_SEVERITY_CAP = 1.0   # 현재가가 목표가의 2배를 넘으면 그 이상은 동일 취급


def calculate_quant_score(f_pegy, f_roe, roic, sh_return, t_roe, vol=None, f_per=None, price=0.0, f_target=None,
                           growth=None, growth_pop_stats=None, roe_pop_stats=None, pegy_pop_stats=None,
                           vol_std=None, vol_penalty=None, f_target_capped=False):
    """
    퀀트 스코어 계산 및 상태 배지 반환
    (역성장/적자 하드컷오프, 데이터 이상 Guardrail & 목표주가 달성 교차검증 전면 반영)

    ⚠️ ENGINEERING_SPEC §0-1: 수집하지 못한 지표는 '중립값'을 대입하지 않고 배점에서 제외합니다.
       따라서 만점(score_max)은 종목마다 달라질 수 있으며, 반환값 score_max / excluded_items 로
       UI가 "xx점 / yy점 (제외: ...)" 형태로 정직하게 표기해야 합니다. 하드컷오프 경로도 동일합니다.

    1. PEGY 밸류에이션 점수 (최대 35점) — f_pegy 필요
    2. 자본효율성 Quality 점수 (최대 30점) — f_roe / roic 필요
    3. 배당수익률(주주환원) 점수 (최대 20점) — sh_return 필요
    4. Trailing 안정성 점수 (최대 10점) — t_roe 필요
    5. 변동성 위험 보정 점수 (최대 5점) — 실측 변동성 필요

    Args:
        growth_pop_stats: (mean, std) 튜플. 오늘 수집된 유효 종목 전체의 성장률(growth) 분포.
            역성장/적자 하드컷오프의 심각도(z-score) 계산에 사용. None이면 중간값으로 대체.
        roe_pop_stats: (mean, std) 튜플. 오늘 수집된 유효 종목 전체의 Trailing ROE 분포.
        pegy_pop_stats: (mean, std) 튜플. 오늘 f_pegy가 산출된 종목들의 Forward PEGY 분포.
            극단적 고평가 하드컷오프의 심각도 계산에 사용.
        vol_std: 실측 20일 일간수익률 표준편차(%). 2026-08-06 2차 감사 2-4로 신설 —
            예전에는 UI 표시 문자열(vol)에 "정상"/"데이터 없음"이 들어있는지를 파싱해서
            점수를 매겼습니다(화면 문구만 바꿔도 점수가 바뀌는 구조였음).
        vol_penalty: collector가 실효성장률(g_eff)에 이미 적용한 변동성 벌점 배수.
            1.0보다 크면 변동성이 이미 PEGY 쪽에서 한 번 반영됐다는 뜻이라, 5점짜리
            변동성 카테고리에서 또 감점하지 않습니다(이중 계상 방지).
        vol: (레거시) UI 표시 문자열. vol_std가 없을 때만 하위호환용으로 참조합니다.
        f_target_capped: 목표주가가 '계산 결과'가 아니라 캡 상수(현재가×2.5)인 경우 True.
            이때는 현재가와 목표가를 비교하는 교차검증 자체가 무의미하므로 건너뜁니다.
    """
    # =========================================================
    # Guardrail 0: 진짜 측정 불가 (Trailing 최소 요건 결측) — price 또는 t_roe 자체가 없으면
    # 아무 것도 계산할 수 없으므로 여기서만 전체 차단합니다.
    # =========================================================
    if price is None or price <= 0 or t_roe is None:
        return {
            "quant_score": None,
            "raw_score": None,
            "score_max": None,
            "excluded_items": ["전 항목 (Trailing 기초 데이터 없음)"],
            "is_cutoff": True,
            "forward_available": False,
            "badge": "🔴 데이터 없음 (측정 불가)",
            "badge_bg": "#7f1d1d",
            "badge_fg": "#fca5a5"
        }

    # =========================================================
    # Guardrail 0-1: 데이터 오염 / PER 이상치 (PER > 300배 또는 PER <= 0)
    # 2026-08-06 개편: f_per 자체만 못 믿는 것이지 ROE·배당·변동성·Trailing까지 못 믿을
    # 이유는 없으므로, 더 이상 즉시 flat 10점을 리턴하지 않습니다. PEGY(35점)만 배점에서
    # 빼고 나머지는 아래 정상 채점 경로를 그대로 태운 뒤, 마지막에 오염 정도(300배 기준
    # 초과분)에 비례한 상한만 적용합니다.
    # =========================================================
    per_extreme = f_per is not None and (f_per > PER_EXTREME_MAX or f_per <= 0.0)

    # =========================================================
    # Forward(미래 추정) 데이터 가용 여부 — 2026-08-05 추가, 2026-08-06 정의 수정.
    # f_per가 오염 의심(per_extreme)이면 애초에 f_per를 신뢰할 수 없으므로 forward_available은
    # False로 취급합니다(성장률 계산에 f_per를 직접 쓰진 않지만, PEGY의 분자인 f_per 자체가
    # 오염됐으므로 PEGY 카테고리 전체를 배점에서 제외).
    #
    # ⚠️ 2026-08-06 버그 수정: 예전엔 f_pegy가 None이면(=성장률이 마이너스라 PEGY 계산식
    # 자체가 성립 안 하는 경우도 포함) forward_available을 False로 판정했습니다. 그 결과
    # 애널리스트 컨센서스(f_per/f_eps/growth)가 실제로는 다 있는데도 "🔵 Trailing만 검증됨
    # (Forward 데이터 없음)" 배지가 붙고, 정작 화면의 Forward 카드에는 그 실측값이 그대로
    # 표시되는 자기모순이 있었습니다(CJ대한통운 사례). "컨센서스 자체가 없는 것"과
    # "컨센서스는 있는데 성장률이 마이너스라 PEGY만 못 구하는 것"은 다른 상황이므로,
    # forward_available은 f_per/growth 존재 여부만으로 판정하고, 후자는 아래 Guardrail 1의
    # "역성장" 컷오프에서 별도로 처리합니다.
    # =========================================================
    #
    # ⚠️ 2026-08-06 2차 감사 2-5: 예전엔 아래에서 같은 이름의 `forward_available` 변수를
    # 역성장 판정 후에 False로 덮어써서, 함수 뒷부분에서 이 변수가 "컨센서스가 존재하는가"인지
    # "PEGY로 채점 가능한가"인지 읽는 사람이 알 수 없었습니다(당시엔 무해했지만 재발 함정).
    # → 의미가 다른 두 값을 이름부터 분리합니다.
    #    forward_available     : 애널리스트 컨센서스(f_per/growth)가 실제로 존재하는가 (불변)
    #    pegy_scoring_available: 그래서 PEGY 카테고리를 실제로 채점할 수 있는가 (역성장 시 False)
    # =========================================================
    forward_available = (f_per is not None and growth is not None) and not per_extreme
    pegy_scoring_available = forward_available

    excluded_items = []
    if not pegy_scoring_available:
        if per_extreme:
            excluded_items.append("PEGY 밸류에이션 35점 (Forward PER 범위 초과 — 데이터 오염 의심)")
        else:
            excluded_items.append("PEGY 밸류에이션 35점 (Forward 데이터 없음 — 애널리스트 컨센서스 미제공)")

    # =========================================================
    # Guardrail 1: 역성장 및 무성장 기업 (g_eff <= 0 또는 t_roe <= 0) 예외 처리
    # Forward 데이터가 없으면 growth/f_pegy 로는 판단할 수 없으니 t_roe 기준으로만 판단합니다.
    # per_extreme인 경우는 위에서 이미 forward_available=False로 처리됐으므로, 여기서는
    # t_roe 기준으로만 판단됩니다(중복 처리 방지, per_extreme 쪽 상한이 우선 적용됨).
    # =========================================================
    if pegy_scoring_available:
        is_decline = (growth <= 0.0 or t_roe <= 0.0 or (f_pegy is not None and f_pegy <= 0.0))
    else:
        is_decline = (t_roe <= 0.0)

    if is_decline:
        # PEGY는 역성장/적자 상태에서 공식이 성립하지 않으므로 배점에서 제외합니다.
        if pegy_scoring_available:
            excluded_items.append("PEGY 밸류에이션 35점 (역성장/적자 상태 — PEGY 공식 성립 불가)")
        pegy_scoring_available = False
        f_pegy = None

    earned = 0
    possible = 0

    # 1. PEGY 점수 (35점) — Forward 데이터가 있고 역성장/오염이 아닐 때만 배점
    #    ⚠️ Guardrail 1-2(비정상적 고성장률/기저효과 왜곡 방어)는 아래에서 "점수만" 보수적으로
    #    캡합니다 — f_pegy 자체는 건드리지 않아 배지·목표가 표시와 항상 일관됩니다(위
    #    _growth_pegy_score_ratio() 설명 참고).
    growth_score_capped = False
    if pegy_scoring_available and f_pegy is not None:
        # 2차 감사 2-2: 점수 구간을 배지 구간과 같은 상수(PEGY_SCORE_BANDS)에서 읽습니다.
        s_pegy = PEGY_SCORE_WORST
        for boundary, band_score in PEGY_SCORE_BANDS:
            if f_pegy < boundary:
                s_pegy = band_score
                break

        growth_score_ratio = _growth_pegy_score_ratio(growth)
        capped_s_pegy = int(round(PEGY_SCORE_MAX * growth_score_ratio))
        if capped_s_pegy < s_pegy:
            growth_score_capped = True
            s_pegy = capped_s_pegy

        earned += s_pegy
        possible += PEGY_SCORE_MAX

    # =========================================================
    # 2. Quality 점수 (30점) — f_roe / roic 는 실측 컨센서스가 없으면 배점에서 제외
    # 2026-08-06 2차 감사 2-3: 계단식(15/10/4) → 앵커점 선형 보간으로 교체.
    # =========================================================
    if f_roe is not None:
        earned += _piecewise_linear(f_roe, FORWARD_ROE_SCORE_KNOTS)
        possible += 15
    else:
        excluded_items.append("Forward ROE 15점 (데이터 없음)")
    if roic is not None:
        earned += _piecewise_linear(roic, ROIC_SCORE_KNOTS)
        possible += 15
    else:
        excluded_items.append("ROIC 15점 (데이터 없음)")

    # 3. 배당수익률(주주환원) 점수 (20점)
    #    sh_return이 None이면 '무배당'이 아니라 '수집 실패'이므로 배점에서 제외합니다
    #    (collector 1-4 수정과 짝을 이룹니다 — 예전엔 미수집 종목이 0%로 들어와 3점을 받았습니다).
    if sh_return is not None:
        earned += _piecewise_linear(sh_return, DIVIDEND_SCORE_KNOTS)
        possible += 20
    else:
        excluded_items.append("배당수익률 20점 (데이터 없음 — 무배당과 구분)")

    # 4. Trailing 실적 점수 (10점) — t_roe는 Guardrail 0에서 이미 존재 보장됨
    earned += _piecewise_linear(t_roe, TRAILING_ROE_SCORE_KNOTS)
    possible += 10

    # =========================================================
    # 5. 변동성 보정 점수 (5점)
    # 2026-08-06 2차 감사 2-4 개편 두 가지:
    #  ① UI 표시 문자열("정상"/"데이터 없음") 파싱을 그만두고 실측 vol_std를 직접 씁니다.
    #  ② 이중 계상 방지 — collector가 이미 변동성 벌점(vol_penalty)을 실효성장률에 곱해
    #     f_pegy를 악화시켰다면, 그 종목은 PEGY 카테고리에서 이미 변동성 만큼 감점된
    #     상태입니다. 거기에 이 5점 항목에서 또 깎으면 같은 위험을 두 번 세는 셈이라,
    #     PEGY가 실제로 채점된 경우에는 이 항목을 배점에서 제외합니다.
    # =========================================================
    vol_text = vol or ""
    if vol_std is None and "데이터 없음" not in vol_text and vol_text:
        # 레거시 호출(구 스냅샷/유닛테스트): 표시 문자열밖에 없을 때만 최소한의 하위호환 처리
        vol_std_effective = None
        legacy_vol_score = VOL_SCORE_MAX if "정상" in vol_text else 1
    else:
        vol_std_effective = vol_std
        legacy_vol_score = None

    if vol_std_effective is None and legacy_vol_score is None:
        excluded_items.append("변동성 5점 (데이터 없음)")
    elif pegy_scoring_available and vol_penalty is not None and vol_penalty > 1.0:
        excluded_items.append(
            "변동성 5점 (실효성장률에 이미 변동성 벌점 반영됨 — 이중 계상 방지로 제외)"
        )
    elif vol_std_effective is not None:
        earned += _piecewise_linear(vol_std_effective, VOL_SCORE_KNOTS)
        possible += VOL_SCORE_MAX
    else:
        earned += legacy_vol_score
        possible += VOL_SCORE_MAX

    # Raw 합산 점수 (획득 점수 / 산출 가능 만점) — 하드컷오프 경로도 이 값을 그대로 씁니다.
    # 선형 보간 배점(2-3)으로 소수점이 생기므로 버림이 아니라 반올림합니다.
    raw_score = int(round(earned))
    score_max = int(possible)

    def _cap(pct_of_100):
        return int(round(pct_of_100 * score_max / 100.0)) if score_max else 0

    quant_score = raw_score
    is_cutoff = False
    is_extreme_overvalued = False

    if per_extreme:
        # =========================================================
        # PER 이상치 상한: 데이터 오염 의심 정도(300배 기준 초과분, 또는 PER<=0이면 최대치)를
        # 0~300 범위로 보고 12%~2% 캡으로 윈저라이즈. (횡단면 z-score 대신 절대 기준 사용 —
        # 이건 "동종업계 대비 밸류에이션"이 아니라 "데이터 자체가 깨졌는지"를 보는 것이라
        # 다른 종목과 상대비교하는 게 개념적으로 안 맞기 때문입니다.)
        # =========================================================
        severity = (f_per - PER_EXTREME_MAX) if f_per > 0 else PER_EXTREME_MAX
        severity = max(0.0, min(severity, PER_EXTREME_MAX))
        cap_pct = 12.0 - (severity / PER_EXTREME_MAX) * (12.0 - 2.0)
        quant_score = min(quant_score, _cap(cap_pct))
        is_cutoff = True
        badge = "🔴 데이터 이상/극단고평가 (PER 검증 실패)"
        badge_bg = "#7f1d1d"
        badge_fg = "#fca5a5"

    elif is_decline:
        # =========================================================
        # 역성장/적자 상한: 오늘 수집된 유효 종목 전체(횡단면) 대비 성장률·ROE가 몇 표준편차
        # 아래에 있는지(z-score)로 심각도를 매겨 25%(평균 수준)~5%(3표준편차 이상 최악) 캡.
        # population 데이터가 부족하면(표본<5 등, 아래 collector에서 가드) 중간값(15%)으로
        # 안전하게 대체 — 예전 flat 15점과 사실상 동일한 안전망 역할을 합니다.
        # =========================================================
        z_growth = _population_zscore(growth, growth_pop_stats) if (growth is not None and forward_available) else None
        z_roe = _population_zscore(t_roe, roe_pop_stats)
        candidates = [z for z in (z_growth, z_roe) if z is not None]
        severity_z = min(candidates) if candidates else None  # 더 나쁜(더 낮은) 쪽을 기준으로 삼음
        cap_pct = _winsorized_scale(severity_z, best_z=0.0, worst_z=-3.0, pct_best=25.0, pct_worst=5.0)
        quant_score = min(quant_score, _cap(cap_pct))
        is_cutoff = True
        if forward_available:
            badge = "🔴 실적 역성장/적자 (위험)"
        else:
            badge = "🔴 Trailing 실적 역성장/적자 (위험)"
        badge_bg = "#7f1d1d"
        badge_fg = "#fca5a5"

    else:
        # 기본 PEGY 기반 배지 판정 — Forward 데이터가 없으면 PEGY로 판정할 수 없으므로
        # 전용 '중립' 배지를 부여합니다 (저평가/고평가 어느 쪽도 아님, 미확인 상태).
        # 2차 감사 2-2: 배지 경계값도 점수와 동일한 PEGY_BAND_* 상수만 참조합니다.
        if not pegy_scoring_available:
            badge = "🔵 Trailing만 검증됨 (Forward 데이터 없음)"
            badge_bg = "#1e3a5f"
            badge_fg = "#93c5fd"
        elif f_pegy < PEGY_BAND_STRONG_UNDER:
            badge = "🟢 강력 저평가"
            badge_bg = "#14532d"
            badge_fg = "#4ade80"
        elif f_pegy < PEGY_BAND_UNDER:
            badge = "🟢 저평가"
            badge_bg = "#166534"
            badge_fg = "#86efac"
        elif f_pegy < PEGY_BAND_FAIR:
            badge = "🟡 적정가 형성"
            badge_bg = "#78350f"
            badge_fg = "#fde047"
        else:
            badge = "🔴 고평가 관망"
            badge_bg = "#7f1d1d"
            badge_fg = "#fca5a5"

        # Forward 데이터가 없으면 목표주가/PEGY 기반 교차검증 자체를 할 수 없으므로 아래 두 블록은 건너뜁니다.
        if pegy_scoring_available:
            # =========================================================
            # 교차 검증 1: 목표주가(f_target) 초과/달성 여부 정합성 체크
            # 현재가가 목표가를 넘었거나 달성했다면 저평가 배지 절대 부여 금지!
            #
            # ⚠️ 2026-08-06 2차 감사 2-1 개편 (이 파일의 마지막 남은 플랫 하드컷오프)
            #   예전: price >= f_target*1.15 → 무조건 45% 캡 / price >= f_target → 60% 캡
            #   → 목표가를 1.16배 넘긴 종목과 5배 넘긴 종목이 완전히 동일한 45% 캡이었습니다.
            #   지금: 초과폭(overshoot = 현재가/목표가 - 1)에 비례해 60%→20%로 선형 윈저라이즈.
            #
            # ⚠️ 그리고 f_target_capped(=목표가가 계산값이 아니라 '현재가×2.5' 캡 상수)인
            #   종목은 이 블록을 통째로 건너뜁니다. 캡 상수와 현재가를 비교하면 "현재가는
            #   항상 캡의 40%"라는 동어반복이라 아무 정보가 없기 때문입니다(2차 감사 1-3).
            # =========================================================
            if f_target_capped:
                pass
            elif f_target and price > 0:
                overshoot = (price / f_target) - 1.0
                if overshoot >= 0.0:
                    severity = min(max(overshoot, 0.0), TARGET_OVERSHOOT_SEVERITY_CAP)
                    ratio = severity / TARGET_OVERSHOOT_SEVERITY_CAP
                    cap_pct = TARGET_OVERSHOOT_CAP_BEST_PCT - ratio * (
                        TARGET_OVERSHOOT_CAP_BEST_PCT - TARGET_OVERSHOOT_CAP_WORST_PCT
                    )
                    quant_score = min(quant_score, _cap(cap_pct))
                    if overshoot >= 0.15:
                        # 목표가 15% 이상 초과 고평가
                        badge = "🔴 목표가 초과 (고평가 관망)"
                        badge_bg = "#7f1d1d"
                        badge_fg = "#fca5a5"
                    else:
                        # 목표주가 달성 및 도달
                        badge = "🟡 목표가 달성 (적정가)"
                        badge_bg = "#78350f"
                        badge_fg = "#fde047"

            # =========================================================
            # 교차 검증 2: 하드 컷오프 (Hard Cut-off / Killer Logic)
            # Forward PEGY >= 2.0 이거나 Forward PER >= 70.0 인 극단적 고평가 감지 시.
            # 2026-08-06 개편: 상한을 flat 20%가 아니라, 오늘 f_pegy가 산출된 종목들
            # 전체 분포 대비 f_pegy가 몇 표준편차 위(더 고평가)인지로 20%(경계선 수준)~5%
            # (3표준편차 이상 극단적 고평가) 사이로 윈저라이즈합니다.
            # =========================================================
            is_extreme_overvalued = (
                f_pegy >= PEGY_EXTREME_OVERVALUED
                or (f_per is not None and f_per >= FPER_EXTREME_OVERVALUED)
            )
            if is_extreme_overvalued:
                z_pegy = _population_zscore(f_pegy, pegy_pop_stats)
                cap_pct = _winsorized_scale(z_pegy, best_z=0.0, worst_z=3.0, pct_best=20.0, pct_worst=5.0)
                quant_score = min(quant_score, _cap(cap_pct))
                is_cutoff = True
                badge = "🔴 극단적 고평가 (위험)"
                badge_bg = "#7f1d1d"
                badge_fg = "#fca5a5"

    return {
        "quant_score": quant_score,
        "raw_score": raw_score,
        "score_max": score_max,
        "excluded_items": excluded_items,
        "is_cutoff": is_cutoff,
        # forward_available: 애널리스트 컨센서스가 실제로 존재하는가 (역성장이어도 True)
        # pegy_scoring_available: PEGY 카테고리를 실제로 채점했는가 (2차 감사 2-5로 분리)
        "forward_available": forward_available,
        "pegy_scoring_available": pegy_scoring_available,
        "badge": badge,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
        "growth_score_capped": growth_score_capped
    }
