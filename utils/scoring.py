"""
utils/scoring.py
보이는 손 퀀트 종합 스코어링 엔진 (Hard Cut-off 킬러 로직 & 목표주가 달성 교차검증 반영)
"""

def calculate_quant_score(f_pegy, f_roe, roic, sh_return, t_roe, vol, f_per=0.0, price=0.0, f_target=0.0):
    """
    100점 만점 퀀트 스코어 계산 및 상태 배지 반환
    (목표주가 초과/달성 교차검증 & 고평가 하드 컷오프 Killer Logic 전면 반영)
    
    1. PEGY 밸류에이션 점수 (최대 35점)
    2. 자본효율성 Quality 점수 (최대 30점)
    3. 주주환원율 Yield 점수 (최대 20점)
    4. Trailing 안정성 점수 (최대 10점)
    5. 변동성 위험 보정 점수 (최대 5점)
    
    교차 검증 규칙 (Cross-Validation Rules):
    1. 목표가 달성/초과 검증 (price >= f_target):
       - 현재가가 퀀트 목표주가를 이미 초과하거나 달성한 경우, PEGY 수치와 관계없이
         '강력 저평가' / '저평가' 배지 부여를 엄격히 차단합니다.
       - price >= f_target * 1.15 (15% 초과): '🔴 목표가 초과 (고평가 관망)' & quant_score 상한 45점
       - f_target <= price < f_target * 1.15: '🟡 목표가 달성 (적정가)' & quant_score 상한 60점
    
    2. 하드 컷오프 (Hard Cut-off / Killer Logic):
       - Forward PEGY >= 2.0 또는 Forward PER >= 70.0 극단적 고평가 시:
         * quant_score = min(raw_score, 20) (최대 20점 이하 강제 상한 제한)
         * badge = '🔴 극단적 고평가 (위험)'
    """
    # 1. PEGY 점수 (35점)
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

    # 2. Quality 점수 (30점)
    s_f_roe = 15 if f_roe >= 15.0 else (10 if f_roe >= 10.0 else 4)
    s_roic = 15 if roic >= 12.0 else (10 if roic >= 8.0 else 4)
    s_quality = s_f_roe + s_roic

    # 3. 주주환원 점수 (20점)
    if sh_return >= 5.0:
        s_return = 20
    elif sh_return >= 3.0:
        s_return = 14
    elif sh_return >= 1.0:
        s_return = 8
    else:
        s_return = 3

    # 4. Trailing 실적 점수 (10점)
    if t_roe >= 10.0:
        s_trailing = 10
    elif t_roe >= 6.0:
        s_trailing = 6
    else:
        s_trailing = 2

    # 5. 변동성 보정 점수 (5점)
    s_vol = 5 if "정상" in vol else 1

    # Raw 합산 점수 (0 ~ 100점)
    raw_score = int(s_pegy + s_quality + s_return + s_trailing + s_vol)

    # 기본 PEGY 기반 배지 판정
    if f_pegy < 0.65:
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

    quant_score = raw_score

    # =========================================================
    # 교차 검증 1: 목표주가(f_target) 초과/달성 여부 정합성 체크
    # 현재가가 목표가를 넘었거나 달성했다면 저평가 배지 절대 부여 금지!
    # =========================================================
    if f_target > 0 and price > 0:
        if price >= f_target * 1.15:
            # 목표가 15% 이상 초과 고평가
            badge = "🔴 목표가 초과 (고평가 관망)"
            badge_bg = "#7f1d1d"
            badge_fg = "#fca5a5"
            quant_score = min(quant_score, 45)
        elif price >= f_target:
            # 목표주가 달성 및 도달
            badge = "🟡 목표가 달성 (적정가)"
            badge_bg = "#78350f"
            badge_fg = "#fde047"
            quant_score = min(quant_score, 60)

    # =========================================================
    # 교차 검증 2: 하드 컷오프 (Hard Cut-off / Killer Logic)
    # Forward PEGY >= 2.0 이거나 Forward PER >= 70.0 인 극단적 고평가 감지 시
    # =========================================================
    is_extreme_overvalued = (f_pegy >= 2.0 or (f_per is not None and f_per >= 70.0))
    if is_extreme_overvalued:
        quant_score = min(quant_score, 20) # 최대 20점 이하 강제 상한 제한
        badge = "🔴 극단적 고평가 (위험)"
        badge_bg = "#7f1d1d"
        badge_fg = "#fca5a5"

    return {
        "quant_score": quant_score,
        "raw_score": raw_score,
        "is_cutoff": is_extreme_overvalued,
        "badge": badge,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg
    }
