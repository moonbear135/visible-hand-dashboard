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


def calculate_quant_score(f_pegy, f_roe, roic, sh_return, t_roe, vol, f_per=None, price=0.0, f_target=None, growth=None,
                           growth_pop_stats=None, roe_pop_stats=None, pegy_pop_stats=None):
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
    per_extreme = f_per is not None and (f_per > 300.0 or f_per <= 0.0)

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
    forward_available = (f_per is not None and growth is not None) and not per_extreme
    original_forward_available = forward_available  # 역성장 배지 문구 판정용 (아래에서 forward_available을 덮어쓰기 때문)

    excluded_items = []
    if not forward_available:
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
    if forward_available:
        is_decline = (growth <= 0.0 or t_roe <= 0.0 or (f_pegy is not None and f_pegy <= 0.0))
    else:
        is_decline = (t_roe <= 0.0)

    if is_decline:
        # PEGY는 역성장/적자 상태에서 공식이 성립하지 않으므로 배점에서 제외합니다.
        if forward_available:
            excluded_items.append("PEGY 밸류에이션 35점 (역성장/적자 상태 — PEGY 공식 성립 불가)")
        forward_available = False
        f_pegy = None

    earned = 0
    possible = 0

    # 1. PEGY 점수 (35점) — Forward 데이터가 있고 역성장/오염이 아닐 때만 배점
    #    ⚠️ Guardrail 1-2(비정상적 고성장률/기저효과 왜곡 방어)는 아래에서 "점수만" 보수적으로
    #    캡합니다 — f_pegy 자체는 건드리지 않아 배지·목표가 표시와 항상 일관됩니다(위
    #    _growth_pegy_score_ratio() 설명 참고).
    growth_score_capped = False
    if forward_available and f_pegy is not None:
        if f_pegy < 0.65:
            s_pegy = 35
        elif f_pegy < 0.85:
            s_pegy = 28
        elif f_pegy < 1.0:
            s_pegy = 20
        elif f_pegy < 1.35:
            s_pegy = 12
        elif f_pegy < 2.0:
            s_pegy = 5
        else:
            s_pegy = 0

        growth_score_ratio = _growth_pegy_score_ratio(growth)
        capped_s_pegy = int(round(35 * growth_score_ratio))
        if capped_s_pegy < s_pegy:
            growth_score_capped = True
            s_pegy = capped_s_pegy

        earned += s_pegy
        possible += 35

    # 2. Quality 점수 (30점) — f_roe / roic 는 실측 컨센서스가 없으면 배점에서 제외
    if f_roe is not None:
        earned += 15 if f_roe >= 15.0 else (10 if f_roe >= 10.0 else 4)
        possible += 15
    else:
        excluded_items.append("Forward ROE 15점 (데이터 없음)")
    if roic is not None:
        earned += 15 if roic >= 12.0 else (10 if roic >= 8.0 else 4)
        possible += 15
    else:
        excluded_items.append("ROIC 15점 (데이터 없음)")

    # 3. 배당수익률(주주환원) 점수 (20점)
    if sh_return is not None:
        if sh_return >= 5.0:
            earned += 20
        elif sh_return >= 3.0:
            earned += 14
        elif sh_return >= 1.0:
            earned += 8
        else:
            earned += 3
        possible += 20
    else:
        excluded_items.append("배당수익률 20점 (데이터 없음)")

    # 4. Trailing 실적 점수 (10점) — t_roe는 Guardrail 0에서 이미 존재 보장됨
    if t_roe >= 10.0:
        earned += 10
    elif t_roe >= 6.0:
        earned += 6
    else:
        earned += 2
    possible += 10

    # 5. 변동성 보정 점수 (5점) — 실측 변동성이 없으면 가점도 감점도 하지 않고 배점 제외
    vol_text = vol or ""
    if "데이터 없음" in vol_text:
        excluded_items.append("변동성 5점 (데이터 없음)")
    else:
        earned += 5 if "정상" in vol_text else 1
        possible += 5

    # Raw 합산 점수 (획득 점수 / 산출 가능 만점) — 하드컷오프 경로도 이 값을 그대로 씁니다.
    raw_score = int(earned)
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
        severity = (f_per - 300.0) if f_per > 0 else 300.0
        severity = max(0.0, min(severity, 300.0))
        cap_pct = 12.0 - (severity / 300.0) * (12.0 - 2.0)
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
        z_growth = _population_zscore(growth, growth_pop_stats) if (growth is not None and original_forward_available) else None
        z_roe = _population_zscore(t_roe, roe_pop_stats)
        candidates = [z for z in (z_growth, z_roe) if z is not None]
        severity_z = min(candidates) if candidates else None  # 더 나쁜(더 낮은) 쪽을 기준으로 삼음
        cap_pct = _winsorized_scale(severity_z, best_z=0.0, worst_z=-3.0, pct_best=25.0, pct_worst=5.0)
        quant_score = min(quant_score, _cap(cap_pct))
        is_cutoff = True
        if original_forward_available:
            badge = "🔴 실적 역성장/적자 (위험)"
        else:
            badge = "🔴 Trailing 실적 역성장/적자 (위험)"
        badge_bg = "#7f1d1d"
        badge_fg = "#fca5a5"

    else:
        # 기본 PEGY 기반 배지 판정 — Forward 데이터가 없으면 PEGY로 판정할 수 없으므로
        # 전용 '중립' 배지를 부여합니다 (저평가/고평가 어느 쪽도 아님, 미확인 상태).
        if not forward_available:
            badge = "🔵 Trailing만 검증됨 (Forward 데이터 없음)"
            badge_bg = "#1e3a5f"
            badge_fg = "#93c5fd"
        elif f_pegy < 0.65:
            badge = "🟢 강력 저평가"
            badge_bg = "#14532d"
            badge_fg = "#4ade80"
        elif f_pegy < 0.95:
            badge = "🟢 저평가"
            badge_bg = "#166534"
            badge_fg = "#86efac"
        elif f_pegy < 1.35:
            badge = "🟡 적정가 형성"
            badge_bg = "#78350f"
            badge_fg = "#fde047"
        else:
            badge = "🔴 고평가 관망"
            badge_bg = "#7f1d1d"
            badge_fg = "#fca5a5"

        # Forward 데이터가 없으면 목표주가/PEGY 기반 교차검증 자체를 할 수 없으므로 아래 두 블록은 건너뜁니다.
        if forward_available:
            # =========================================================
            # 교차 검증 1: 목표주가(f_target) 초과/달성 여부 정합성 체크
            # 현재가가 목표가를 넘었거나 달성했다면 저평가 배지 절대 부여 금지!
            # =========================================================
            if f_target and price > 0:
                if price >= f_target * 1.15:
                    # 목표가 15% 이상 초과 고평가
                    badge = "🔴 목표가 초과 (고평가 관망)"
                    badge_bg = "#7f1d1d"
                    badge_fg = "#fca5a5"
                    quant_score = min(quant_score, _cap(45))
                elif price >= f_target:
                    # 목표주가 달성 및 도달
                    badge = "🟡 목표가 달성 (적정가)"
                    badge_bg = "#78350f"
                    badge_fg = "#fde047"
                    quant_score = min(quant_score, _cap(60))

            # =========================================================
            # 교차 검증 2: 하드 컷오프 (Hard Cut-off / Killer Logic)
            # Forward PEGY >= 2.0 이거나 Forward PER >= 70.0 인 극단적 고평가 감지 시.
            # 2026-08-06 개편: 상한을 flat 20%가 아니라, 오늘 f_pegy가 산출된 종목들
            # 전체 분포 대비 f_pegy가 몇 표준편차 위(더 고평가)인지로 20%(경계선 수준)~5%
            # (3표준편차 이상 극단적 고평가) 사이로 윈저라이즈합니다.
            # =========================================================
            is_extreme_overvalued = (f_pegy >= 2.0 or (f_per is not None and f_per >= 70.0))
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
        "forward_available": forward_available,
        "badge": badge,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
        "growth_score_capped": growth_score_capped
    }
