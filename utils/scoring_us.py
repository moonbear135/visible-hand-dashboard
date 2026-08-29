"""
utils/scoring_us.py
🇺🇸 미국주식("미국 주식은 이가격") 전용 퀀트 스코어링 & 밸류에이션 산출 엔진

⚠️ 왜 utils/scoring.py 를 재사용하지 않고 새로 만들었나
   구조(2차 패스 population z-score, 윈저라이즈, 앵커점 선형보간, "수집 못 한 항목은
   배점에서 제외")는 그대로 물려받았지만, **입력 필드와 상수가 다릅니다.**
   - 코스피: 네이버 컨센서스 기반 f_per/f_eps/growth(=추정EPS 증감률)/Trailing ROE/DPS
   - 미국  : stockanalysis.com 의 PE/Forward PE/PEG/ROE/ROIC/EPS/BPS/Shareholder Yield/
            EPS Growth Forecast(3Y)/Price Target/Piotroski F-Score/Beta …
   또 코스피 상수(ROE 12%, 목표 PER 25배 등)를 미국 종목에 그대로 쓰면 전 종목이 한쪽으로
   쏠리기 때문에, 이 파일은 **utils/constants_us.py 의 값만** 사용합니다
   (utils/constants.py 는 import 하지 않습니다 — 기존 코스피 파이프라인 무수정 원칙).

지켜지는 원칙
  §0-1  수집 못 한 지표는 0/평균값으로 채우지 않고 배점에서 제외(score_max 가 종목마다 다름).
        계산 불가 지표는 None + 사유. 캡(상한)에 걸린 값은 반드시 *_capped 플래그로 마킹.
  §0-3-1 후행지표 전용 — 여기서 미래를 예측하는 값을 새로 만들지 않습니다. 성장률은
        소스가 제공하는 애널리스트 컨센서스(EPS Growth Forecast 3Y) 실측값만 씁니다.
  §2-2  개별 종목 예외 코드 금지 — 업종 판정은 전부 industry 문자열 키워드 매칭입니다.
  §5-3(작업지시서) 고정 임계값 대신 절대거리/z-score 비례 스케일링 + 윈저라이즈.

카테고리 배점 (이론상 100점, 실제 만점은 종목마다 다름)
  ① PEGY 밸류에이션      35점  f_pegy = Forward PER ÷ 실효성장률
  ② 자본효율성           30점  Trailing ROE 15 + ROIC 15   (은행류는 ROIC n/a → 15점 제외)
  ③ 주주환원             20점  Shareholder Yield(배당+자사주, 소스 실측)
  ④ 재무 건전성          10점  Piotroski F-Score (0~9 실측)  ※ 코스피는 여기에 Trailing ROE를
                              썼지만 미국은 ②에서 이미 ROE를 쓰므로 이중 계상이 됩니다.
  ⑤ 변동성(베타)          5점  Beta(5Y) 실측
"""

import math
import statistics

from utils.constants_us import (
    US_PER_EXTREME_MAX,
    US_PEGY_EXTREME_OVERVALUED,
    US_FPER_EXTREME_OVERVALUED,
    US_TARGET_PER_CAP,
    US_TARGET_PRICE_CAP_MULTIPLE,
    US_ROE_PREMIUM_BASELINE_PCT,
    US_ROIC_PREMIUM_BASELINE_PCT,
    US_VALUE_TRAP_ROE_PCT,
    US_VALUE_TRAP_ROIC_PCT,
    US_PEGY_BAND_STRONG_UNDER,
    US_PEGY_BAND_UNDER,
    US_PEGY_BAND_FAIR,
    US_GROWTH_CAP_PCT,
    US_SH_RETURN_CAP_PCT,
    US_GEFF_TOTAL_CAP_PCT,
    US_PEGY_MIN_DENOMINATOR_PCT,
    US_GROWTH_ADJ_THRESHOLD_PCT,
    US_GROWTH_ADJ_SEVERITY_CAP_PCT,
    US_GROWTH_ADJ_SCORE_RATIO_MIN,
    US_GROWTH_ADJ_SCORE_RATIO_MAX,
    US_BETA_NEUTRAL,
    US_BETA_SEVERITY_CAP,
    US_PIOTROSKI_MAX_SCORE,
    US_FINANCIAL_INDUSTRY_KEYWORDS,
    US_REIT_INDUSTRY_KEYWORDS,
)

# =============================================================================
# 0. 공용 수학 유틸 (utils/scoring.py 와 동일한 개념 — 코스피 파일을 import 하지 않고
#    같은 로직을 미국 모듈 안에 독립적으로 둡니다. 신규 기능 모듈 분리 원칙 §0-3-6)
# =============================================================================
def _piecewise_linear(x, knots):
    """(x, y) 앵커점 사이를 선형 보간하고 양 끝 밖은 윈저라이즈(clip). 계단식 절벽 제거용."""
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
    """횡단면 population(mean, std) 대비 z-score. 표본이 없으면 None(=비교 불가)."""
    if value is None or pop_stats is None:
        return None
    mean, std = pop_stats
    if not std or std <= 0:
        return None
    return (value - mean) / std


def _winsorized_scale(z, best_z, worst_z, pct_best, pct_worst):
    """z-score를 pct_best~pct_worst 로 선형 매핑 + 양끝 윈저라이즈. z가 None이면 중간값."""
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


def _linear_premium(value, baseline, up_range, down_range, prem_max, prem_min):
    """
    기준선 대비 절대거리에 비례한 프리미엄/디스카운트(윈저라이즈).
    ⚠️ `if roe >= 15: +0.15 else: -0.10` 같은 절벽(플랫 하드코딩) 대신 쓰는 함수입니다.
    값이 없으면 0.0 — 프리미엄도 디스카운트도 주지 않습니다(§0-1: 모르면 가점/감점 없음).
    """
    if value is None:
        return 0.0
    if value >= baseline:
        ratio = min((value - baseline) / up_range, 1.0) if up_range > 0 else 1.0
        return round(prem_max * ratio, 4)
    ratio = min((baseline - value) / down_range, 1.0) if down_range > 0 else 1.0
    return round(prem_min * ratio, 4)


# =============================================================================
# 1. 배점 앵커 (미국 시장 기준으로 새로 잡은 값 — 코스피 값을 베끼지 않았습니다)
#    ✅ 2026-08-07: 앵커가 참조하는 `utils/constants_us.py` §5 기준선들이 실측 548종목 분포로
#       확정되면서 이 배점 곡선도 함께 확정됐습니다(값은 전부 constants_us.py 단일 출처에서 옵니다).
# =============================================================================
# Trailing ROE 15점: 0%(손익분기)=0점, 미국 자기자본비용 하단(9%)=10점,
#   실측 중앙값 수준(US_ROE_PREMIUM_BASELINE_PCT=16%) 이상=만점.
US_ROE_SCORE_KNOTS = [(0.0, 0.0), (US_VALUE_TRAP_ROE_PCT, 10.0), (US_ROE_PREMIUM_BASELINE_PCT, 15.0)]
# ROIC 15점: 0%=0점, 착시 저평가 기준선(US_VALUE_TRAP_ROIC_PCT=6.5%, 2026-08-29 재감사 L2 —
#   이전 "WACC 하단(8%)" 주석은 실측 확정 전 잠정값(8.0) 시절의 잔재)=10점, 상단(12%) 이상=만점.
US_ROIC_SCORE_KNOTS = [(0.0, 0.0), (US_VALUE_TRAP_ROIC_PCT, 10.0), (US_ROIC_PREMIUM_BASELINE_PCT, 15.0)]
# 주주환원 20점: 미국은 배당보다 자사주 매입 비중이 커 Shareholder Yield(배당+자사주)를 씁니다.
#   ⚠️ 이 값은 **음수가 될 수 있습니다**(증자·주식보상으로 주식수가 늘면 희석). 실제 12종목
#      샘플에서도 GLW -0.09%, INCY -3.09% 로 음수가 관측됐습니다 — 0으로 잘라내지 않고
#      희석 구간을 그대로 0점으로 반영합니다.
US_SHAREHOLDER_YIELD_SCORE_KNOTS = [(-3.0, 0.0), (0.0, 3.0), (2.0, 10.0), (4.0, 15.0), (7.0, 20.0)]
# 재무 건전성 10점: 피오트로스키 F-Score 0~9 를 그대로 선형 매핑(0점=0, 9점=만점).
US_PIOTROSKI_SCORE_KNOTS = [(0.0, 0.0), (float(US_PIOTROSKI_MAX_SCORE), 10.0)]
# 변동성(베타) 5점: 베타 1.0 이하(시장 이하 변동)=만점, 2.0 이상=최저 1점.
US_BETA_SCORE_KNOTS = [(US_BETA_NEUTRAL, 5.0), (US_BETA_SEVERITY_CAP, 1.0)]

US_PEGY_SCORE_MAX = 35
US_PEGY_SCORE_BANDS = [
    (US_PEGY_BAND_STRONG_UNDER, 35),      # < 0.65
    (US_PEGY_BAND_UNDER, 28),             # < 0.95
    (US_PEGY_BAND_FAIR, 20),              # < 1.35
    (US_PEGY_EXTREME_OVERVALUED, 8),      # < US_PEGY_EXTREME_OVERVALUED(=3.0, 2026-08-07 조정)
]
US_PEGY_SCORE_WORST = 0                   # >= US_PEGY_EXTREME_OVERVALUED(=3.0)
# (2026-08-29 재감사 L1: 위 두 주석의 "2.00"은 2026-08-07에 3.0으로 조정되기 전 값의 잔재였습니다.)

# 목표주가 교차검증 상한 — 현재가가 목표가를 얼마나 초과했는지(overshoot)에 비례.
US_TARGET_OVERSHOOT_CAP_BEST_PCT = 60.0
US_TARGET_OVERSHOOT_CAP_WORST_PCT = 20.0
US_TARGET_OVERSHOOT_SEVERITY_CAP = 1.0    # 현재가가 목표가의 2배를 넘으면 그 이상은 동일 취급


def _growth_pegy_score_ratio(growth):
    """
    성장률이 기준선(100%)을 넘으면 기저효과 왜곡 가능성을 의심해 PEGY '점수'만 0.2~1.0배로
    보수화합니다. **f_pegy 값 자체는 절대 건드리지 않습니다** — 2026-08-06 코스피에서
    "배지는 고평가인데 화면 목표가는 +150% 상승여력"이라는 자기모순을 만든 원인이 바로
    f_pegy 덮어쓰기였습니다(TASK_HISTORY #39). 같은 실수를 미국 쪽에서 반복하지 않습니다.
    """
    if growth is None or growth < US_GROWTH_ADJ_THRESHOLD_PCT:
        return US_GROWTH_ADJ_SCORE_RATIO_MAX
    excess = min(growth - US_GROWTH_ADJ_THRESHOLD_PCT, US_GROWTH_ADJ_SEVERITY_CAP_PCT)
    ratio = excess / US_GROWTH_ADJ_SEVERITY_CAP_PCT
    return US_GROWTH_ADJ_SCORE_RATIO_MAX - ratio * (
        US_GROWTH_ADJ_SCORE_RATIO_MAX - US_GROWTH_ADJ_SCORE_RATIO_MIN
    )


# =============================================================================
# 2. 업종 판정 (SPEC §2-2 — 티커 하드코딩 금지, industry 문자열 키워드만 사용)
# =============================================================================
def classify_sector_flags(stock):
    """
    업종 특성 플래그를 만듭니다. 값이 없으면 판정하지 않고 False + 사유를 남깁니다.
      is_financial : 은행/보험/자산운용 등 (그레이엄 넘버 전제가 안 맞음, ROIC 미제공 흔함)
      is_reit      : 리츠 (소스가 PER 대신 Price/FFO 를 제공)
    """
    industry = (stock.get("industry") or "").lower()
    price_ffo = stock.get("price_ffo")
    is_reit = bool(price_ffo is not None) or any(k in industry for k in US_REIT_INDUSTRY_KEYWORDS)
    is_financial = any(k in industry for k in US_FINANCIAL_INDUSTRY_KEYWORDS)
    return {
        "is_financial_sector": is_financial,
        "is_reit": is_reit,
        "sector_basis": (
            f"industry='{stock.get('industry')}'" if stock.get("industry")
            else "industry 미수집 — 업종 판정 불가(리츠는 Price/FFO 존재 여부로만 판정)"
        ),
    }


# =============================================================================
# 3. 파생 밸류에이션 산출 (수집 1차 패스에서 종목별로 호출)
# =============================================================================
def derive_valuation(stock):
    """
    수집된 원시 필드에서 PEGY·목표주가·적정가·그레이엄 넘버 등을 산출합니다.
    ⚠️ 순수 함수입니다(네트워크·전역상태 없음) — 유닛 테스트로 그대로 검증 가능합니다.
    ⚠️ 입력이 하나라도 없으면 값을 지어내지 않고 None + data_issues 사유를 남깁니다.

    반환: dict (stock 에 merge 할 파생 필드들)
    """
    out = {}
    issues = list(stock.get("data_issues") or [])

    price = stock.get("price")
    t_per = stock.get("t_per")
    f_per = stock.get("f_per")
    t_eps = stock.get("t_eps")
    bps = stock.get("bps")
    t_roe = stock.get("t_roe")
    roic = stock.get("roic")
    growth = stock.get("growth")            # = growth_eps_3y (소스 실측 컨센서스)
    sh_return = stock.get("sh_return")      # = shareholder_yield (배당+자사주, 실측)
    beta = stock.get("beta")

    out.update(classify_sector_flags(stock))

    # -------------------------------------------------------------------------
    # 적자 판정 — 소스는 적자 기업의 PER 을 음수로 주지 않고 n/a 로 주며, EPS 라벨이
    # "Earnings Per Share (EPS)" → "Loss Per Share" 로 바뀌면서 값이 음수가 됩니다
    # (TASK_HISTORY #46 실측 확인). 그래서 PER 부호가 아니라 EPS·순이익 부호로 판정합니다.
    #
    # ⚠️ 2026-08-29 재감사 H2: 예전에는 ROE 음수도 적자 증거로 넣었는데, ROE = 순이익÷
    # 자기자본이라 **자사주 매입을 오래 한 미국 대형 우량주**(맥도날드·홈디포·스타벅스 등)는
    # 순이익이 크게 흑자여도 자기자본이 음수라 ROE 가 음수로 나옵니다. 이 경우를 "적자"로
    # 오판정하지 않도록 ROE 부호는 적자 판정에서 뺐습니다 — 진짜 적자는 EPS/순이익이
    # 이미 잡습니다. ROE 는 자본효율성 점수(US_ROE_SCORE_KNOTS)에서만 반영합니다.
    # -------------------------------------------------------------------------
    loss_evidence = []
    if t_eps is not None and t_eps <= 0:
        loss_evidence.append(f"Trailing EPS {t_eps}")
    if stock.get("net_income") is not None and stock["net_income"] < 0:
        loss_evidence.append("순이익(TTM) 적자")
    out["is_trailing_loss"] = bool(loss_evidence)
    out["loss_evidence"] = loss_evidence

    # 자기자본(장부가) 음수 — 자사주 매입 누적 등으로 흔히 발생하는 정상적인 재무 상태입니다.
    # ROE 해석이 왜곡되는 원인을 화면에 알려주기 위한 정보성 플래그입니다(적자 판정과 무관).
    out["negative_equity"] = bool(bps is not None and bps < 0)
    if out["negative_equity"] and t_roe is not None and t_roe < 0 and not out["is_trailing_loss"]:
        issues.append(
            f"Trailing ROE {t_roe}% (자기자본이 음수 — 자사주 매입 누적 등으로 ROE 해석이 "
            "왜곡될 수 있습니다. 적자 판정에는 반영하지 않음)"
        )

    if t_per is None and out["is_reit"]:
        issues.append("PER 미제공 — 리츠는 소스가 PER 대신 Price/FFO 를 제공합니다(정상)")
    elif t_per is None and out["is_trailing_loss"]:
        issues.append("PER 미제공 — 적자 기업이라 소스가 n/a 로 표기(정상, 0으로 채우지 않음)")
    if roic is None:
        issues.append("ROIC 미제공 — 은행/보험 등은 투하자본 개념이 달라 소스가 n/a 로 표기")

    # -------------------------------------------------------------------------
    # Forward EPS — 소스는 Forward EPS 를 직접 주지 않고 Forward PER 만 줍니다.
    # ⚠️ ENGINEERING_SPEC §0-1 예시2-보충(대수적 역산 허용 예외) 4개 조건을 전부 만족합니다:
    #    ① 다른 출처로 Forward EPS 를 실측할 수 없음, ② 미래를 새로 추정하는 게 아니라
    #    이미 확정된 실측값 2개(장마감 종가, 소스가 제공한 Forward PER 컨센서스)의
    #    순수 나눗셈, ③ 입력 둘 다 실측값, ④ 아래처럼 계산값 플래그·출처를 남기고
    #    화면에도 "🧮 계산값" 배지를 붙입니다.
    # -------------------------------------------------------------------------
    if price and f_per and f_per > 0:
        out["f_eps"] = round(price / f_per, 4)
        out["f_eps_calculated"] = True
        out["f_eps_source"] = "calculated_price_div_forward_per"
    else:
        out["f_eps"] = None
        out["f_eps_calculated"] = False
        out["f_eps_source"] = None

    # -------------------------------------------------------------------------
    # 실효성장률(g_eff) — SPEC §5-1 2중 Cap.
    # ⚠️ 주주환원율을 '모르는' 종목(None)에 0을 대입하면 "무배당·무자사주라고 단정"하는
    #    것과 같으므로 산출하지 않습니다(§0-1).
    # ⚠️ 코스피와 달리 변동성 벌점 배수를 곱하지 않습니다 — 근거는 constants_us.py §5-2 주석.
    # -------------------------------------------------------------------------
    if growth is not None and sh_return is not None:
        capped_growth = min(growth, US_GROWTH_CAP_PCT)
        capped_sh = min(sh_return, US_SH_RETURN_CAP_PCT)
        geff_raw = capped_growth + capped_sh
        geff = min(geff_raw, US_GEFF_TOTAL_CAP_PCT)
        out["g_eff"] = round(geff, 2)
        out["g_eff_capped"] = bool(
            growth > US_GROWTH_CAP_PCT or sh_return > US_SH_RETURN_CAP_PCT
            or geff_raw > US_GEFF_TOTAL_CAP_PCT
        )
        out["g_eff_uncapped"] = round((growth or 0.0) + (sh_return or 0.0), 2)
    else:
        geff = None
        out["g_eff"] = None
        out["g_eff_capped"] = False
        out["g_eff_uncapped"] = None
        if growth is None:
            issues.append("실효성장률(g_eff) 산출 불가 — EPS 성장 전망(3Y) 컨센서스 미제공")
        else:
            issues.append("실효성장률(g_eff) 산출 불가 — 주주환원율(Shareholder Yield) 미수집")

    # -------------------------------------------------------------------------
    # PEGY — 분모(실효성장률)가 0.5%p 미만이면 값이 수백~수천으로 무의미해지므로
    # 코스피와 동일하게 산출을 생략합니다(0.1 같은 근거 없는 바닥값을 쓰지 않음).
    # -------------------------------------------------------------------------
    if f_per and f_per > 0 and geff is not None and geff >= US_PEGY_MIN_DENOMINATOR_PCT:
        out["f_pegy"] = round(f_per / geff, 2)
    else:
        out["f_pegy"] = None
        if f_per and geff is not None and 0 < geff < US_PEGY_MIN_DENOMINATOR_PCT:
            issues.append(
                f"Forward PEGY 산출 생략 (실효성장률 {geff:.2f}%p < "
                f"{US_PEGY_MIN_DENOMINATOR_PCT}%p — 사실상 무성장)"
            )
    if t_per and t_per > 0 and geff is not None and geff >= US_PEGY_MIN_DENOMINATOR_PCT:
        out["t_pegy"] = round(t_per / geff, 2)
    else:
        out["t_pegy"] = None

    # PBR 바닥가 (현재가 ÷ PBR = 주당순자산) — 순수 사칙연산.
    # ⚠️ f_target/t_fair 산출보다 먼저 계산합니다 — 아래에서 "장부가 기준 참고 바닥값"으로
    # 사용하기 위함 (2026-08-07 owner 결정: PEGY 역산 목표가가 BPS보다 낮게 나오는
    # 자산집약형/저성장 종목은 BPS를 참고 하한으로 삼는다).
    # ⚠️ 진짜 청산가치(재고 감가상각 방식, 무형자산 손상 여부, 부채 시가평가 등)를 따진 게
    # 아니라 장부가 그대로를 쓰는 것이므로, "청산가치"라는 확정적 표현은 쓰지 않습니다(§0-1).
    t_pbr = stock.get("t_pbr")
    out["floor_price"] = round(price / t_pbr, 2) if (price and t_pbr and t_pbr > 0) else None

    # -------------------------------------------------------------------------
    # 착시 저평가(value trap) — 코스피와 달리 ROIC 도 실측되므로 두 지표 모두 사용합니다.
    # ⚠️ f_target/t_fair 의 BPS 바닥값 적용 여부를 가르는 "우량 게이트"로도 재사용합니다
    # (아래 참고) — 여기로 순서를 당겨온 이유입니다.
    # -------------------------------------------------------------------------
    trap_reasons = []
    if t_roe is not None and t_roe < US_VALUE_TRAP_ROE_PCT:
        trap_reasons.append(f"Trailing ROE {t_roe}% < 기준선 {US_VALUE_TRAP_ROE_PCT}%")
    if roic is not None and roic < US_VALUE_TRAP_ROIC_PCT:
        trap_reasons.append(f"ROIC {roic}% < 기준선 {US_VALUE_TRAP_ROIC_PCT}%")
    if t_roe is None and roic is None:
        out["value_trap"] = False
        out["value_trap_basis"] = "판정 불가 (ROE·ROIC 모두 미수집)"
    else:
        out["value_trap"] = bool(trap_reasons)
        out["value_trap_basis"] = (
            " · ".join(trap_reasons) if trap_reasons
            else "ROE·ROIC 모두 기준선 이상 (착시 저평가 아님)"
        )
    # BPS 바닥값 적용 자격 — "장부가가 실제 청산가치를 반영한다"는 전제가 성립하려면
    # 최소한 ROE·ROIC 둘 다 실측되고 value trap 판정을 통과해야 합니다(2026-08-07 owner 결정).
    # ROE·ROIC 가 하나라도 미수집이면(=판정 불가) 우량 여부를 지어내지 않고 바닥값도 적용하지 않습니다.
    floor_price_eligible = (
        t_roe is not None and roic is not None and not out["value_trap"]
    )
    out["floor_price_eligible"] = floor_price_eligible

    # -------------------------------------------------------------------------
    # 목표주가(f_target) — PEGY 역산. SPEC §5-2 와 같은 2중 캡을 적용하고,
    # 캡에 걸리면 반드시 흔적(*_capped / 사유 / 캡 미적용 원값)을 남깁니다.
    # -------------------------------------------------------------------------
    roe_prem = _linear_premium(t_roe, US_ROE_PREMIUM_BASELINE_PCT,
                               up_range=15.0, down_range=15.0, prem_max=0.15, prem_min=-0.10)
    roic_prem = _linear_premium(roic, US_ROIC_PREMIUM_BASELINE_PCT,
                                up_range=12.0, down_range=12.0, prem_max=0.10, prem_min=-0.05)
    out["roe_premium"] = roe_prem
    out["roic_premium"] = roic_prem

    f_target = None
    f_target_capped = False
    target_per_capped = False
    f_target_cap_reason = None
    f_target_uncapped = None
    target_per = None
    f_eps = out["f_eps"]
    if f_eps and geff and geff > 0 and price and price > 0:
        target_pegy = 1.0 * (1.0 + roe_prem + roic_prem)
        raw_target_per = target_pegy * geff
        target_per = min(raw_target_per, US_TARGET_PER_CAP)
        target_per_capped = raw_target_per > US_TARGET_PER_CAP
        raw_target = f_eps * target_per
        price_cap_value = price * US_TARGET_PRICE_CAP_MULTIPLE
        f_target_uncapped = round(raw_target, 2)
        if raw_target > price_cap_value:
            f_target = round(price_cap_value, 2)
            f_target_capped = True
            f_target_cap_reason = (
                f"현재가 {US_TARGET_PRICE_CAP_MULTIPLE}배 상한에 도달 "
                f"(캡 미적용 산출값 ${raw_target:,.2f}) — 추정 신뢰구간 밖이라 상한값으로 절단"
            )
        else:
            f_target = round(raw_target, 2)
        if target_per_capped:
            f_target_cap_reason = ((f_target_cap_reason + " / ") if f_target_cap_reason else "") + (
                f"목표 PER {US_TARGET_PER_CAP}배 상한 적용 (캡 미적용 {raw_target_per:.1f}배)"
            )
        if f_target_capped or target_per_capped:
            issues.append(f"목표주가 캡 적용: {f_target_cap_reason}")
    # BPS 바닥값 적용 — 우량 게이트(floor_price_eligible) 통과 종목만.
    # PEGY 역산 공식이 저성장 자본집약형(보험/지주/유틸리티 등) 우량주에서 구조적으로
    # 낮은 목표가를 내는 문제의 보정 — 2026-08-07 owner 결정, US 만 적용(§0-1 시장별 분리 원칙).
    f_target_floored = False
    if (
        f_target is not None and floor_price_eligible
        and out["floor_price"] is not None and out["floor_price"] > f_target
    ):
        pre_floor_target = f_target
        f_target = out["floor_price"]
        f_target_floored = True
        floor_note = (
            f"장부가(BPS) 참고 바닥값 ${out['floor_price']:,.2f} 적용 "
            f"(PEGY 역산값 ${pre_floor_target:,.2f} 미만 — 저성장 자본집약 우량주 보정, "
            f"실제 청산가치 실사 아님)"
        )
        f_target_cap_reason = ((f_target_cap_reason + " / ") if f_target_cap_reason else "") + floor_note
        issues.append(f"목표주가 바닥값 적용: {floor_note}")
        # 2026-08-29(오푸스 감사 Top-5 #2-A2): 바닥값 자체가 2.5배 폭주 방지 캡을 넘으면
        # 캡도 그대로 적용합니다 — 캡은 "이 목표가가 신뢰구간 안에 있는가"를 보는 것이지
        # 산출 경로(PEGY 역산 vs BPS 바닥값)를 가리지 않습니다(§0-1, 근거 없는 큰 수를
        # 검증 없이 그대로 내보내지 않음). price_cap_value 는 위 블록에서 이미 계산됨
        # (f_target 이 None 이 아니려면 그 블록이 실행됐어야 하므로 안전하게 재사용 가능).
        if f_target > price_cap_value:
            f_target = round(price_cap_value, 2)
            f_target_capped = True
            floor_cap_note = (
                f"장부가 바닥값(${out['floor_price']:,.2f})도 현재가 "
                f"{US_TARGET_PRICE_CAP_MULTIPLE}배 상한을 초과해 상한값으로 절단"
            )
            f_target_cap_reason = f_target_cap_reason + " / " + floor_cap_note
            issues.append(f"목표주가 캡 적용: {floor_cap_note}")
    out["f_target"] = f_target
    out["f_target_capped"] = f_target_capped
    out["f_target_floored"] = f_target_floored
    out["f_target_cap_reason"] = f_target_cap_reason
    out["f_target_uncapped"] = f_target_uncapped
    out["target_per"] = round(target_per, 2) if target_per is not None else None
    out["target_per_capped"] = target_per_capped

    # Trailing 적정가(t_fair) — 적자 기업은 산출하지 않습니다.
    t_fair = None
    t_fair_capped = False
    t_fair_uncapped = None
    if t_eps and t_eps > 0 and geff and geff > 0 and price and price > 0:
        raw_t_fair = t_eps * min(geff, US_TARGET_PER_CAP)
        price_cap_value = price * US_TARGET_PRICE_CAP_MULTIPLE
        t_fair_uncapped = round(raw_t_fair, 2)
        if raw_t_fair > price_cap_value:
            t_fair = round(price_cap_value, 2)
            t_fair_capped = True
        else:
            t_fair = round(raw_t_fair, 2)
    t_fair_floored = False
    if (
        t_fair is not None and floor_price_eligible
        and out["floor_price"] is not None and out["floor_price"] > t_fair
    ):
        t_fair = out["floor_price"]
        t_fair_floored = True
        # 2026-08-29(오푸스 감사 Top-5 #2-A2): f_target 과 동일하게, 바닥값이 캡을 넘으면
        # 캡도 적용합니다(위 if 블록이 이미 실행됐으므로 price_cap_value 재사용 가능).
        if t_fair > price_cap_value:
            t_fair = round(price_cap_value, 2)
            t_fair_capped = True
    out["t_fair"] = t_fair
    out["t_fair_capped"] = t_fair_capped
    out["t_fair_floored"] = t_fair_floored
    out["t_fair_uncapped"] = t_fair_uncapped

    # -------------------------------------------------------------------------
    # 그레이엄 넘버 √(22.5 × EPS × BPS) — 성장률 추정이 필요 없는 순수 Trailing 공식.
    # 적자(EPS ≤ 0)면 제곱근 안이 음수라 수학적으로 산출 불가 → None + 사유.
    # 금융업종은 값은 내되 화면에서 강한 경고 배지를 함께 표시합니다(코스피와 동일 방침).
    # -------------------------------------------------------------------------
    if t_eps is not None and bps is not None and t_eps > 0 and bps > 0:
        out["graham_target"] = round(math.sqrt(22.5 * t_eps * bps), 2)
    else:
        out["graham_target"] = None
        if t_eps is not None and t_eps <= 0:
            issues.append("그레이엄 넘버 산출 불가 — 적자(EPS ≤ 0)라 제곱근 안이 음수")
    out["graham_is_financial_sector"] = out["is_financial_sector"]

    # (참고) 착시 저평가(value trap) 판정은 위쪽 floor_price_eligible 게이트 계산부로 이동했습니다.

    # 베타는 값만 통과시키고, 없으면 벌점/가점 어느 쪽도 주지 않습니다.
    if beta is None:
        issues.append("베타(5Y) 미제공 — 변동성 5점은 배점에서 제외")

    # Forward 섹션 가용 여부 (§5-5: 없으면 그 섹션만 마스킹)
    out["forward_available"] = bool(f_per is not None and growth is not None)
    out["forward_missing_fields"] = [
        k for k, v in (("f_per", f_per), ("growth", growth)) if v is None
    ]
    out["forward_data_missing"] = bool(out["forward_missing_fields"])

    out["data_issues"] = issues
    return out


# =============================================================================
# 4. 횡단면 population 통계 (2차 패스용)
# =============================================================================
def compute_population_stats(stocks, min_samples=5):
    """
    오늘 수집된 종목 전체(횡단면)의 분포를 계산합니다.
    표본이 min_samples 미만이거나 표준편차가 0이면 None → scoring 이 중간값 캡으로 안전 대체.
    """
    def _stats(values):
        vals = [v for v in values if v is not None]
        if len(vals) < min_samples:
            return None
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals)
        return (mean, std) if std > 0 else None

    return {
        "growth": _stats([s.get("growth") for s in stocks]),
        "roe": _stats([s.get("t_roe") for s in stocks]),
        # PEGY 는 극단치가 평균/표준편차를 통째로 망가뜨리므로 상식적 범위만 모집단에 넣습니다.
        "pegy": _stats([
            s.get("f_pegy") for s in stocks
            if s.get("f_pegy") is not None and 0 < s["f_pegy"] < 50.0
        ]),
    }


# =============================================================================
# 5. 퀀트 스코어
# =============================================================================
def calculate_us_quant_score(
    f_pegy=None, t_roe=None, roic=None, sh_return=None, piotroski=None, beta=None,
    f_per=None, price=None, f_target=None, growth=None, f_target_capped=False,
    f_target_floored=False, f_target_uncapped=None, is_trailing_loss=False,
    growth_pop_stats=None, roe_pop_stats=None, pegy_pop_stats=None,
):
    """
    미국 종목 퀀트 스코어 + 상태 배지.

    ⚠️ §0-1: 수집하지 못한 지표는 '중립값'을 대입하지 않고 배점에서 제외합니다.
       따라서 만점(score_max)은 종목마다 다르며, UI 는 "x점 / y점 (z%)" 로 표기해야 합니다.

    Args:
        growth_pop_stats / roe_pop_stats / pegy_pop_stats:
            (mean, std). 오늘 수집분 횡단면 분포. 하드컷오프 심각도(z-score) 계산용.
            None 이면 중간값 캡으로 안전 대체합니다(크래시·임의값 없음).
    """
    # -------------------------------------------------------------------------
    # Guardrail 0: 진짜 측정 불가 — 가격이 없으면 아무것도 계산할 수 없습니다.
    # (코스피는 여기서 t_roe 도 필수로 요구했지만, 미국은 리츠·적자기업 등에서 ROE 만
    #  없고 나머지가 멀쩡한 경우가 실제로 있어 가격만 하드 요건으로 둡니다.)
    # -------------------------------------------------------------------------
    if price is None or price <= 0:
        return {
            "quant_score": None, "raw_score": None, "score_max": None,
            "excluded_items": ["전 항목 (장마감 종가 없음)"],
            "is_cutoff": True, "forward_available": False, "pegy_scoring_available": False,
            "badge": "🔴 데이터 없음 (측정 불가)", "badge_bg": "#7f1d1d", "badge_fg": "#fca5a5",
            "growth_score_capped": False,
        }

    per_extreme = f_per is not None and (f_per > US_PER_EXTREME_MAX or f_per <= 0.0)
    forward_available = (f_per is not None and growth is not None) and not per_extreme
    pegy_scoring_available = forward_available and f_pegy is not None

    excluded_items = []
    if not forward_available:
        if per_extreme:
            excluded_items.append("PEGY 밸류에이션 35점 (Forward PER 범위 초과 — 데이터 오염 의심)")
        else:
            excluded_items.append("PEGY 밸류에이션 35점 (Forward 데이터 없음 — 애널리스트 컨센서스 미제공)")
    elif not pegy_scoring_available:
        # f_pegy 가 없는 이유를 뭉뚱그리지 않고 구분해서 남깁니다(역성장 vs 분모 결측).
        if growth is not None and growth <= 0.0:
            excluded_items.append("PEGY 밸류에이션 35점 (역성장/무성장 — PEGY 공식 성립 불가)")
        else:
            excluded_items.append("PEGY 밸류에이션 35점 (실효성장률 미산출 — 주주환원율 미수집 등)")

    # -------------------------------------------------------------------------
    # Guardrail 1: 역성장/적자
    # -------------------------------------------------------------------------
    # 2026-08-29 재감사 H2: 예전에는 t_roe <= 0.0 을 역성장/적자 증거로 썼는데, 자기자본이
    # 음수인 우량주(자사주 매입 누적)는 ROE 가 음수여도 실적은 흑자입니다. 이미 EPS/순이익
    # 기준으로 판정된 is_trailing_loss(derive_valuation) 를 대신 씁니다 — ROE 는 자본효율성
    # 점수(위 ROE knots)에서만 반영됩니다(음수 ROE 는 knots 상 이미 0점).
    if forward_available:
        is_decline = (growth <= 0.0) or is_trailing_loss
    else:
        is_decline = is_trailing_loss

    if is_decline and pegy_scoring_available:
        excluded_items.append("PEGY 밸류에이션 35점 (역성장/적자 상태 — PEGY 공식 성립 불가)")
        pegy_scoring_available = False
        f_pegy = None

    earned = 0.0
    possible = 0.0

    # ① PEGY 35점
    growth_score_capped = False
    if pegy_scoring_available and f_pegy is not None:
        s_pegy = US_PEGY_SCORE_WORST
        for boundary, band_score in US_PEGY_SCORE_BANDS:
            if f_pegy < boundary:
                s_pegy = band_score
                break
        capped = int(round(US_PEGY_SCORE_MAX * _growth_pegy_score_ratio(growth)))
        if capped < s_pegy:
            growth_score_capped = True
            s_pegy = capped
        earned += s_pegy
        possible += US_PEGY_SCORE_MAX

    # ② 자본효율성 30점 (ROE 15 + ROIC 15)
    if t_roe is not None:
        earned += _piecewise_linear(t_roe, US_ROE_SCORE_KNOTS)
        possible += 15
    else:
        excluded_items.append("Trailing ROE 15점 (데이터 없음)")
    if roic is not None:
        earned += _piecewise_linear(roic, US_ROIC_SCORE_KNOTS)
        possible += 15
    else:
        excluded_items.append("ROIC 15점 (데이터 없음 — 은행/보험 등은 소스가 n/a 로 제공)")

    # ③ 주주환원 20점 (배당 + 자사주)
    if sh_return is not None:
        earned += _piecewise_linear(sh_return, US_SHAREHOLDER_YIELD_SCORE_KNOTS)
        possible += 20
    else:
        excluded_items.append("주주환원 20점 (데이터 없음 — '무배당 확정'과 구분)")

    # ④ 재무 건전성 10점 (피오트로스키 F-Score)
    if piotroski is not None:
        earned += _piecewise_linear(float(piotroski), US_PIOTROSKI_SCORE_KNOTS)
        possible += 10
    else:
        excluded_items.append("재무 건전성 10점 (피오트로스키 F-Score 데이터 없음)")

    # ⑤ 변동성(베타) 5점
    if beta is not None:
        earned += _piecewise_linear(beta, US_BETA_SCORE_KNOTS)
        possible += 5
    else:
        excluded_items.append("변동성(베타) 5점 (데이터 없음)")

    raw_score = int(round(earned))
    score_max = int(possible)

    def _cap(pct_of_100):
        return int(round(pct_of_100 * score_max / 100.0)) if score_max else 0

    if score_max == 0:
        # 채점 가능한 항목이 하나도 없으면 0점을 '성적'인 것처럼 보여주지 않습니다.
        return {
            "quant_score": None, "raw_score": None, "score_max": None,
            "excluded_items": excluded_items, "is_cutoff": True,
            "forward_available": forward_available, "pegy_scoring_available": False,
            "badge": "🔴 데이터 없음 (측정 불가)", "badge_bg": "#7f1d1d", "badge_fg": "#fca5a5",
            "growth_score_capped": False,
        }

    quant_score = raw_score
    is_cutoff = False

    if per_extreme:
        # 데이터 오염 의심 정도(기준 초과분)에 비례해 12%~2% 로 윈저라이즈.
        # (횡단면 z-score 대신 절대 기준 — "동종업계 대비 밸류"가 아니라 "데이터가 깨졌나"를 보는 것)
        severity = (f_per - US_PER_EXTREME_MAX) if f_per > 0 else US_PER_EXTREME_MAX
        severity = max(0.0, min(severity, US_PER_EXTREME_MAX))
        cap_pct = 12.0 - (severity / US_PER_EXTREME_MAX) * (12.0 - 2.0)
        quant_score = min(quant_score, _cap(cap_pct))
        is_cutoff = True
        badge, badge_bg, badge_fg = "🔴 데이터 이상/극단고평가 (PER 검증 실패)", "#7f1d1d", "#fca5a5"

    elif is_decline:
        # 오늘 수집분 전체 대비 성장률·ROE 가 몇 표준편차 아래인지로 25%~5% 캡.
        z_growth = _population_zscore(growth, growth_pop_stats) if (growth is not None and forward_available) else None
        z_roe = _population_zscore(t_roe, roe_pop_stats)
        candidates = [z for z in (z_growth, z_roe) if z is not None]
        severity_z = min(candidates) if candidates else None
        cap_pct = _winsorized_scale(severity_z, best_z=0.0, worst_z=-3.0, pct_best=25.0, pct_worst=5.0)
        quant_score = min(quant_score, _cap(cap_pct))
        is_cutoff = True
        badge = "🔴 실적 역성장/적자 (위험)" if forward_available else "🔴 Trailing 실적 역성장/적자 (위험)"
        badge_bg, badge_fg = "#7f1d1d", "#fca5a5"

    else:
        if not pegy_scoring_available:
            badge, badge_bg, badge_fg = "🔵 Trailing만 검증됨 (Forward 데이터 없음)", "#1e3a5f", "#93c5fd"
        elif f_pegy < US_PEGY_BAND_STRONG_UNDER:
            badge, badge_bg, badge_fg = "🟢 강력 저평가", "#14532d", "#4ade80"
        elif f_pegy < US_PEGY_BAND_UNDER:
            badge, badge_bg, badge_fg = "🟢 저평가", "#166534", "#86efac"
        elif f_pegy < US_PEGY_BAND_FAIR:
            badge, badge_bg, badge_fg = "🟡 적정가 형성", "#78350f", "#fde047"
        else:
            badge, badge_bg, badge_fg = "🔴 고평가 관망", "#7f1d1d", "#fca5a5"

        if pegy_scoring_available:
            # 교차검증 1: 현재가가 이미 목표가를 넘었는데 저평가 배지를 주면 안 됩니다.
            # ⚠️ 목표가가 '캡 상수'이거나 BPS 바닥값으로 대체된 종목은 f_target 자체가
            # price/t_pbr 의 재진술이라 f_target 과 직접 비교하면 동어반복이 됩니다
            # (2026-08-29 오푸스 감사 Top-5 #2-A1 이 처음 발견).
            # ⚠️ 2026-08-29 재감사 H6: 그렇다고 검증을 통째로 건너뛰면, 캡/바닥값 적용 전
            # PEGY 역산 원값(f_target_uncapped) 대비 진짜 초과분이라는 신호까지 함께
            # 사라집니다(바닥값이 걸렸다는 건 정의상 pre_floor_target < floor_price 이므로,
            # 현재가가 바닥값보다 높으면 PEGY 목표가보다는 훨씬 더 높다는 뜻 — 오히려 더
            # 강하게 경고해야 할 구간). f_target 대신 f_target_uncapped 를 기준으로 검증합니다
            # (캡 경로는 uncapped 값이 price 보다 커서 overshoot 이 자연히 음수가 되므로
            # 동어반복 없이 그대로 둬도 안전합니다).
            cross_check_target = f_target_uncapped if (f_target_capped or f_target_floored) else f_target
            if cross_check_target and price > 0:
                overshoot = (price / cross_check_target) - 1.0
                if overshoot >= 0.0:
                    severity = min(max(overshoot, 0.0), US_TARGET_OVERSHOOT_SEVERITY_CAP)
                    ratio = severity / US_TARGET_OVERSHOOT_SEVERITY_CAP
                    cap_pct = US_TARGET_OVERSHOOT_CAP_BEST_PCT - ratio * (
                        US_TARGET_OVERSHOOT_CAP_BEST_PCT - US_TARGET_OVERSHOOT_CAP_WORST_PCT
                    )
                    quant_score = min(quant_score, _cap(cap_pct))
                    if overshoot >= 0.15:
                        badge, badge_bg, badge_fg = "🔴 목표가 초과 (고평가 관망)", "#7f1d1d", "#fca5a5"
                    else:
                        badge, badge_bg, badge_fg = "🟡 목표가 달성 (적정가)", "#78350f", "#fde047"

            # 교차검증 2: 극단적 고평가 하드컷오프
            if f_pegy >= US_PEGY_EXTREME_OVERVALUED or (
                f_per is not None and f_per >= US_FPER_EXTREME_OVERVALUED
            ):
                z_pegy = _population_zscore(f_pegy, pegy_pop_stats)
                cap_pct = _winsorized_scale(z_pegy, best_z=0.0, worst_z=3.0, pct_best=20.0, pct_worst=5.0)
                quant_score = min(quant_score, _cap(cap_pct))
                is_cutoff = True
                badge, badge_bg, badge_fg = "🔴 극단적 고평가 (위험)", "#7f1d1d", "#fca5a5"

    return {
        "quant_score": quant_score,
        "raw_score": raw_score,
        "score_max": score_max,
        "excluded_items": excluded_items,
        "is_cutoff": is_cutoff,
        "forward_available": forward_available,
        "pegy_scoring_available": pegy_scoring_available,
        "badge": badge,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
        "growth_score_capped": growth_score_capped,
    }


# =============================================================================
# 6. 2차 패스 드라이버 — 수집이 다 끝난 뒤 한 번에 호출
# =============================================================================
def score_all(stocks):
    """
    ⚠️ 반드시 **모든 종목 수집이 끝난 뒤** 호출하세요.
       하드컷오프의 점수 상한을 "오늘 수집된 종목 전체 분포 대비 z-score"로 정하려면
       평균/표준편차를 먼저 구해야 하고, 그러려면 모든 종목의 raw 지표가 모여 있어야 합니다
       (Barra/Fama-French 류 횡단면 정규화 — collector_kospi200.py 2차 패스와 같은 구조).

    stocks 를 제자리(in-place)에서 갱신하고, 사용한 population 통계를 반환합니다.
    """
    pool = [s for s in stocks if s.get("is_valid", True) and not s.get("is_unverified", False)]
    pop = compute_population_stats(pool)
    # dict 는 값 비교라 `s in pool` 을 쓰면 내용이 같은 다른 종목까지 걸립니다 — 항등성(id)으로 판정.
    pool_ids = {id(s) for s in pool}

    for s in stocks:
        if id(s) not in pool_ids:
            # 검증 미통과 종목은 점수를 0점으로 주지 않고 '측정 불가'로 남깁니다.
            # 2026-08-29 재감사 L12: 배지만 있고 사유가 어디에도 안 넘어갔습니다 —
            # unverified_reason/reject_reason 을 score_excluded_items 에 실어
            # 화면 툴팁(quant_score_badge 의 tooltip_extra)에 자동 노출되게 합니다.
            reason = s.get("unverified_reason") or s.get("reject_reason")
            s.setdefault("quant_score", None)
            s.setdefault("score_max", None)
            s.setdefault("badge", "⚠️ 데이터 검증 필요")
            s.setdefault("badge_bg", "#78350f")
            s.setdefault("badge_fg", "#facc15")
            s.setdefault("score_excluded_items", [f"전 항목 ({reason})"] if reason else [])
            continue
        res = calculate_us_quant_score(
            f_pegy=s.get("f_pegy"),
            t_roe=s.get("t_roe"),
            roic=s.get("roic"),
            sh_return=s.get("sh_return"),
            piotroski=s.get("piotroski_f"),
            beta=s.get("beta"),
            f_per=s.get("f_per"),
            price=s.get("price"),
            f_target=s.get("f_target"),
            f_target_capped=s.get("f_target_capped", False),
            f_target_floored=s.get("f_target_floored", False),
            f_target_uncapped=s.get("f_target_uncapped"),
            is_trailing_loss=s.get("is_trailing_loss", False),
            growth=s.get("growth"),
            growth_pop_stats=pop["growth"],
            roe_pop_stats=pop["roe"],
            pegy_pop_stats=pop["pegy"],
        )
        s["quant_score"] = res["quant_score"]
        s["raw_score"] = res["raw_score"]
        s["score_max"] = res["score_max"]
        s["badge"] = res["badge"]
        s["badge_bg"] = res["badge_bg"]
        s["badge_fg"] = res["badge_fg"]
        s["score_excluded_items"] = res["excluded_items"]
        s["growth_score_capped"] = res["growth_score_capped"]
        s["is_cutoff"] = res["is_cutoff"]
        s["pegy_scoring_available"] = res["pegy_scoring_available"]
        s["forward_available"] = res["forward_available"]

    return {
        "population_stats": {
            k: ({"mean": round(v[0], 4), "std": round(v[1], 4)} if v else None)
            for k, v in pop.items()
        },
        "population_sample_size": len(pool),
    }


# =============================================================================
# 7. 가드레일 — 수집 직후 종목 단위 검증 (utils/guardrail.py 의 미국판)
#    ⚠️ 상위 판정을 True 로 덮어쓰지 않습니다(AND 결합만).
# =============================================================================
def apply_us_guardrail(stock):
    """
    미국 종목 데이터 방공망. 값을 조용히 고치지 않고, 문제를 플래그·사유로 노출합니다.
    카드 자체를 못 그리는 경우만 하드 블록하고, 나머지는 Forward 섹션만 마스킹됩니다.
    """
    from utils.constants_us import US_MIN_OUTSTANDING_SHARES

    s = dict(stock)
    issues = list(s.get("data_issues") or [])
    warnings = []

    price = s.get("price")
    t_per = s.get("t_per")
    t_eps = s.get("t_eps")
    t_roe = s.get("t_roe")
    f_per = s.get("f_per")
    bps = s.get("bps")
    shares = s.get("outstanding_shares")

    # 정합성 크로스체크 (값을 고치지 않고 그대로 노출 — 회귀 가드)
    # 2026-08-29 재감사 H2: 자기자본(bps)이 음수로 확인된 종목은 ROE<0 + PER/EPS>0 이
    # 부호 유실이 아니라 정상 상태입니다(자사주 매입 누적). bps 를 모르거나 양수일 때만
    # "모순"으로 판정합니다.
    negative_equity_known = bps is not None and bps < 0
    if t_roe is not None and t_roe < 0 and t_per is not None and t_per > 0 and not negative_equity_known:
        warnings.append(f"모순: Trailing ROE {t_roe}%(적자)인데 Trailing PER {t_per}배(양수) — 부호 유실 의심")
    if t_roe is not None and t_roe < 0 and t_eps is not None and t_eps > 0 and not negative_equity_known:
        warnings.append(f"모순: Trailing ROE {t_roe}%(적자)인데 Trailing EPS ${t_eps}(양수) — 부호 유실 의심")
    if s.get("graham_target") and s.get("is_trailing_loss"):
        warnings.append("모순: 적자 종목인데 그레이엄 넘버가 산출됨 — 표시 금지 대상")
    if s.get("market_cap_cross_validated") is False and s.get("market_cap_discrepancy") is not None:
        warnings.append(
            f"주의: 두 출처 시가총액 괴리 {s['market_cap_discrepancy'] * 100:.1f}% "
            "(유니버스 CSV ↔ 통계 페이지 — 갱신 시점 차이일 수 있음)"
        )
    if s.get("price_calculated"):
        warnings.append("주의: 장마감 종가를 직접 파싱하지 못해 시가총액÷발행주식수 계산값을 사용")

    if warnings:
        s["consistency_warnings"] = warnings
        for w in warnings:
            if w not in issues:
                issues.append(w)
    s["data_issues"] = issues

    critical = [w for w in warnings if w.startswith("모순")]

    def _finish(is_valid, is_unverified, reject_reason=None, unverified_reason=None):
        if critical:
            is_unverified = True
            unverified_reason = unverified_reason or ("⚠️ 데이터 정합성 모순 감지: " + " / ".join(critical))
        s["is_valid"] = bool(is_valid)
        s["is_unverified"] = bool(is_unverified)
        if reject_reason:
            s["reject_reason"] = reject_reason
        if unverified_reason:
            s["unverified_reason"] = unverified_reason
        return s

    # 하드 블록 ①: 장마감 종가가 없으면 카드를 그릴 수 없습니다.
    if not price or price <= 0:
        return _finish(False, True, reject_reason="필수 지표 수집 실패 (장마감 종가)")

    # 하드 블록 ②: 발행주식수 파싱 오염 의심 (시총·주당지표가 통째로 오염될 수 있음)
    if shares is not None and 0 < shares < US_MIN_OUTSTANDING_SHARES:
        return _finish(
            False, True,
            reject_reason=f"발행주식수 파싱 오류 의심 ({shares:,.0f}주 < {US_MIN_OUTSTANDING_SHARES:,}주)"
        )

    # Forward PER 오염: 종목 전체가 아니라 Forward 섹션만 막습니다(Trailing 은 정상 노출).
    if f_per is not None and (f_per <= 0 or f_per > US_PER_EXTREME_MAX):
        s["forward_per_extreme"] = True

    # 배당/주주환원 미수집과 '무배당 확정'을 구분해 표시합니다.
    if s.get("dividend_status") == "not_collected" or s.get("sh_return") is None:
        s["dividend_data_unverified"] = True
        # 2026-08-29 재감사 M8: 여기(수집/검증 계층)는 HTML 을 만들지 않습니다 — 화면(표현
        # 계층)이 esc() 로 이스케이프한 뒤 줄바꿈만 <br> 로 변환합니다. 예전에는 이 문자열에
        # 리터럴 "<br>"이 박혀 있어, esc() 를 거치면 "&lt;br&gt;"로 글자 그대로 노출됐습니다.
        s["dividend_unverified_reason"] = (
            "이 종목의 주주환원 데이터(배당·자사주 수익률)를 수집하지 못했습니다.\n"
            "'환원이 없다'는 뜻이 아니라 '값을 확인하지 못했다'는 뜻이며, 주주환원 점수는 배점에서 제외됩니다."
        )

    return _finish(True, False)
