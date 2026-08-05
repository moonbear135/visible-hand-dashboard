"""
utils/scoring.py
보이는 손 퀀트 종합 스코어링 엔진 (Hard Cut-off 킬러 로직 & 산황 검증 Guardrail 반영)
"""

def calculate_quant_score(f_pegy, f_roe, roic, sh_return, t_roe, vol, f_per=None, price=0.0, f_target=None, growth=None):
    """
    퀀트 스코어 계산 및 상태 배지 반환
    (역성장/적자 하드컷오프, 데이터 이상 Guardrail & 목표주가 달성 교차검증 전면 반영)

    ⚠️ ENGINEERING_SPEC §0-1: 수집하지 못한 지표는 '중립값'을 대입하지 않고 배점에서 제외합니다.
       따라서 만점(score_max)은 종목마다 달라질 수 있으며, 반환값 score_max / excluded_items 로
       UI가 "xx점 / yy점 (제외: ...)" 형태로 정직하게 표기해야 합니다.

    1. PEGY 밸류에이션 점수 (최대 35점) — f_pegy 필요
    2. 자본효율성 Quality 점수 (최대 30점) — f_roe / roic 필요
    3. 배당수익률(주주환원) 점수 (최대 20점) — sh_return 필요
    4. Trailing 안정성 점수 (최대 10점) — t_roe 필요
    5. 변동성 위험 보정 점수 (최대 5점) — 실측 변동성 필요
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
    # Guardrail 0-1: 데이터 오염 / PER 이상치 (PER > 300배 또는 PER <= 0) — f_per가 있을 때만 검사
    # =========================================================
    if f_per is not None and (f_per > 300.0 or f_per <= 0.0):
        return {
            "quant_score": 10,
            "raw_score": 10,
            "score_max": None,
            "excluded_items": ["전 항목 (Forward PER 범위 초과 — 데이터 오염 의심)"],
            "is_cutoff": True,
            "forward_available": False,
            "badge": "🔴 데이터 이상/극단고평가",
            "badge_bg": "#7f1d1d",
            "badge_fg": "#fca5a5"
        }

    # =========================================================
    # Forward(미래 추정) 데이터 가용 여부 — 2026-08-05 추가, 2026-08-06 정의 수정.
    # 네이버가 애널리스트 컨센서스(추정 PER/EPS/성장률)를 아예 안 주는 종목이 많아서,
    # 이것 때문에 Trailing 데이터까지 멀쩡한 종목 전체를 '측정 불가'로 묻어버리지 않습니다.
    # PEGY(35점)만 배점에서 빼고, 나머지(자본효율성/배당/Trailing안정성/변동성)는 정상 채점합니다.
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
    forward_available = (f_per is not None and growth is not None)

    excluded_items = []
    if not forward_available:
        excluded_items.append("PEGY 밸류에이션 35점 (Forward 데이터 없음 — 애널리스트 컨센서스 미제공)")

    # =========================================================
    # Guardrail 1: 역성장 및 무성장 기업 (g_eff <= 0 또는 t_roe <= 0) 예외 처리
    # Forward 데이터가 없으면 growth/f_pegy 로는 판단할 수 없으니 t_roe 기준으로만 판단합니다.
    # =========================================================
    if forward_available and (growth <= 0.0 or t_roe <= 0.0 or (f_pegy is not None and f_pegy <= 0.0)):
        return {
            "quant_score": 15,
            "raw_score": 15,
            "score_max": 100,
            "excluded_items": [],
            "is_cutoff": True,
            "forward_available": True,
            "badge": "🔴 실적 역성장/적자 (위험)",
            "badge_bg": "#7f1d1d",
            "badge_fg": "#fca5a5"
        }
    if not forward_available and t_roe <= 0.0:
        return {
            "quant_score": 15,
            "raw_score": 15,
            "score_max": 100,
            "excluded_items": excluded_items,
            "is_cutoff": True,
            "forward_available": False,
            "badge": "🔴 Trailing 실적 역성장/적자 (위험)",
            "badge_bg": "#7f1d1d",
            "badge_fg": "#fca5a5"
        }

    # =========================================================
    # Guardrail 1-2: 비정상적 고성장률(기저효과 왜곡 등) 패널티 (캡 제거에 따른 방어)
    # =========================================================
    if forward_available and growth >= 100.0 and f_pegy is not None:
        # 비정상적(100% 이상) 성장은 일시적 기저효과일 가능성이 크므로
        # PEGY 점수를 보수적으로 깎음(극단적 과대평가 방지)
        f_pegy = max(f_pegy * 2.0, 1.5) # PEGY를 강제로 악화시킴

    earned = 0
    possible = 0

    # 1. PEGY 점수 (35점) — Forward 데이터가 있을 때만 배점 (없으면 위에서 이미 excluded_items에 기록)
    # ⚠️ f_pegy is not None 방어: forward_available=True인데 f_pegy가 None인 경우는 위 Guardrail 1
    # (역성장 컷오프)에서 이미 걸러지지만, 부동소수점 경계 등 예외 상황에 대비한 안전장치입니다.
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

    # 4. Trailing 실적 점수 (10점)
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

    # Raw 합산 점수 (획득 점수 / 산출 가능 만점)
    raw_score = int(earned)
    score_max = int(possible)

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

    quant_score = raw_score

    # 배점이 제외된 종목은 상한(캡)도 만점 대비 같은 비율로 환산합니다.
    def _cap(pct_of_100):
        return int(round(pct_of_100 * score_max / 100.0)) if score_max else 0

    is_extreme_overvalued = False

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
        # Forward PEGY >= 2.0 이거나 Forward PER >= 70.0 인 극단적 고평가 감지 시
        # =========================================================
        is_extreme_overvalued = (f_pegy >= 2.0 or (f_per is not None and f_per >= 70.0))
        if is_extreme_overvalued:
            quant_score = min(quant_score, _cap(20))  # 만점 대비 20% 이하 강제 상한
            badge = "🔴 극단적 고평가 (위험)"
            badge_bg = "#7f1d1d"
            badge_fg = "#fca5a5"

    return {
        "quant_score": quant_score,
        "raw_score": raw_score,
        "score_max": score_max,
        "excluded_items": excluded_items,
        "is_cutoff": is_extreme_overvalued,
        "forward_available": forward_available,
        "badge": badge,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg
    }
