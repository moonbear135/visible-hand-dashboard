"""
utils/guardrail.py
코스피+코스닥 통합 시가총액 상위 500 및 글로벌 종목 전용 데이터 방공망 (Valuation Guardrail)

⚠️ ENGINEERING_SPEC §0-1 (하드코딩·더미 데이터 금지) 준수 규칙
   - 이 모듈은 상위 단계(DataValidator)의 검증 결과를 **절대 상향(False → True)하지 않습니다.**
   - 검증 결과는 AND 로만 결합합니다. 즉 어느 한 단계라도 실패하면 최종 is_valid 는 False 입니다.
"""

from utils.constants import PER_EXTREME_MAX, TARGET_PRICE_CAP_MULTIPLE

MIN_OUTSTANDING_SHARES = 1_000_000  # 상장주식수 sanity range check 하한 (collector 와 동일 기준)

# 배당 필수 업종 판정 키워드 — 2026-08-06 2차 감사 6-1.
# 예전 목록에는 '우B'(2우B 같은 우선주 표기)가 섞여 있었습니다. 우선주는 '업종'이 아니라
# 주식의 종류라서, 배당을 안 주는 일반 제조업 우선주까지 "배당 필수 업종인데 배당이 0"이라는
# 잘못된 경고를 받고 있었습니다. 업종 키워드만 남깁니다.
HIGH_DIVIDEND_SECTOR_KEYWORDS = ['리츠', '인프라', '금융지주', '은행', '보험', '증권']

# 그레이엄 넘버 이상치 판정 배수 — 현재가의 5배를 넘는 그레이엄 넘버는 EPS/PBR 파싱
# 오염(단위 오인)일 가능성이 높습니다. 목표주가 캡(2.5배)보다 훨씬 느슨하게 잡아
# "진짜 이상한 값"만 걸러냅니다.
GRAHAM_OUTLIER_MULTIPLE = 5.0


def apply_valuation_guardrail(stock_data: dict) -> dict:
    """
    코스피+코스닥 통합 시가총액 상위 500 및 글로벌 종목 전용 데이터 검증 & 하드 컷오프 모듈
    - PER / 주가 스케일 오류 검증
    - 상장주식수 sanity range check (파싱 오염 탐지)
    - g_eff <= 0 역성장 표시
    - 배당 필수 업종(리츠/인프라/금융)인데 DPS·배당수익률이 0인 경우 dividend_data_unverified 플래그 부여
      (2026-08-06부터 종목 전체 차단은 안 함 — Forward 카드 자리에만 확인-필요 배지 표시)
    """
    cleaned = stock_data.copy()

    # 상위 단계(DataValidator)의 판정을 그대로 승계 — 여기서 True 로 덮어쓰지 않습니다.
    inherited_valid = bool(cleaned.get('is_valid', True))
    inherited_unverified = bool(cleaned.get('is_unverified', False))
    validation_error = cleaned.get('validation_error')

    price = cleaned.get('price') or 0
    f_per = cleaned.get('f_per')
    sh_return = cleaned.get('sh_return')          # None = 미수집 (0% 와 구분, 2차 감사 1-4)
    dps = cleaned.get('dps')                      # None = 미수집
    name = cleaned.get('name', '')
    outstanding_shares = cleaned.get('outstanding_shares') or 0

    # =========================================================
    # 2026-08-06 2차 감사 6-2: 정합성 크로스체크(회귀 가드)
    # 이 검사가 없어서 "t_roe<0 인데 t_per>0"인 모순 상태가 24종목 규모로 방치됐습니다
    # (abs()가 부호를 지운 1-1 버그의 직접적 방치 원인). 값을 고치지는 않고 —
    # 여기서 조용히 보정하면 또 같은 일이 반복되므로 — 모순을 발견하면 목록에
    # 그대로 적어 화면·JSON에 노출하고, 심각한 것만 검증 실패로 승격시킵니다.
    # =========================================================
    consistency_warnings = []
    t_roe = cleaned.get('t_roe')
    t_per = cleaned.get('t_per')
    t_eps = cleaned.get('t_eps')
    graham_target = cleaned.get('graham_target')

    # ① 적자(ROE<0)인데 Trailing PER이 양수 → 부호 유실(정규식/abs) 재발 신호
    if t_roe is not None and t_roe < 0 and t_per is not None and t_per > 0:
        consistency_warnings.append(
            f"모순: Trailing ROE {t_roe}%(적자)인데 Trailing PER은 {t_per}배(양수) — PER 부호 유실 의심"
        )
    # ② 적자인데 Trailing EPS가 양수 → 같은 계열의 부호 유실
    if t_roe is not None and t_roe < 0 and t_eps is not None and t_eps > 0 and not cleaned.get('t_eps_calculated'):
        consistency_warnings.append(
            f"모순: Trailing ROE {t_roe}%(적자)인데 Trailing EPS는 {t_eps:,}원(양수) — EPS 부호 유실 의심"
        )
    # ③ DPS는 있는데 주주환원율이 0 → 배당수익률 환산 누락
    if dps is not None and dps > 0 and sh_return is not None and sh_return <= 0:
        consistency_warnings.append(
            f"모순: DPS {dps:,}원인데 배당수익률이 {sh_return}% — 배당수익률 환산 누락 의심"
        )
    # ④ 적자인데 그레이엄 넘버가 산출됨 → "적자는 산출 불가" 규칙 위반
    if t_roe is not None and t_roe < 0 and graham_target:
        consistency_warnings.append(
            f"모순: 적자(ROE {t_roe}%) 종목인데 그레이엄 넘버({graham_target:,}원)가 산출됨 — 표시 금지 대상"
        )
    # ⑤ 그레이엄 넘버가 현재가의 5배 초과 → EPS/PBR 파싱 오염 의심
    if graham_target and price > 0 and graham_target > price * GRAHAM_OUTLIER_MULTIPLE:
        consistency_warnings.append(
            f"이상치: 그레이엄 넘버 {graham_target:,}원이 현재가의 {GRAHAM_OUTLIER_MULTIPLE}배를 초과 — EPS/PBR 파싱 오염 의심"
        )
    # ⑥ 목표주가가 캡 상수 그 자체 → 화면 갭(%)이 계산 결과가 아님을 명시적으로 기록
    if cleaned.get('f_target_capped'):
        consistency_warnings.append(
            f"주의: 목표주가가 현재가 {TARGET_PRICE_CAP_MULTIPLE}배 상한에 도달 — 표시되는 상승여력은 계산값이 아니라 상한값"
        )

    if consistency_warnings:
        cleaned['consistency_warnings'] = consistency_warnings
        existing_issues = list(cleaned.get('data_issues') or [])
        for w in consistency_warnings:
            if w not in existing_issues:
                existing_issues.append(w)
        cleaned['data_issues'] = existing_issues

    # 위 ①②④(부호 유실 계열 모순)는 "값이 조금 이상하다"가 아니라 "수집 로직이 다시
    # 망가졌다"는 신호이므로, 종목을 완전히 차단하진 않되 검증 미통과로 승격시켜
    # 퀀트 점수 산출 대상에서 빼고 화면에 사유를 띄웁니다(회귀 가드).
    critical_contradictions = [w for w in consistency_warnings if w.startswith("모순")]

    def _finish(is_valid, is_unverified, reject_reason=None, unverified_reason=None):
        """검증 결과 결합: 상위 판정과 AND 로만 합칩니다."""
        if critical_contradictions:
            is_unverified = True
            if not unverified_reason:
                unverified_reason = "⚠️ 데이터 정합성 모순 감지: " + " / ".join(critical_contradictions)
        cleaned['is_valid'] = bool(inherited_valid and is_valid)
        cleaned['is_unverified'] = bool(inherited_unverified or is_unverified)
        if reject_reason:
            cleaned['reject_reason'] = reject_reason
        if unverified_reason:
            cleaned['unverified_reason'] = unverified_reason
        # 상위(3단계 하네스) 검증 실패도 반드시 화면에 사유로 노출되도록 승계
        if not inherited_valid:
            cleaned['is_unverified'] = True
            if not cleaned.get('unverified_reason') and not cleaned.get('reject_reason'):
                cleaned['unverified_reason'] = f"⚠️ 데이터 검증 실패: {validation_error or '3단계 하네스 검증 미통과'}"
        return cleaned

    # 0. 진짜 필수(Trailing 최소 요건): price 하나만 없으면 카드 자체를 못 그립니다 — 이것만 차단.
    if price <= 0:
        return _finish(False, True, reject_reason="필수 지표 수집 실패 (price)")

    # 0-1. Forward(미래 추정) 전용 데이터 결측 판정 — 2026-08-05 추가.
    #    f_per/f_eps/growth 는 네이버가 애널리스트 컨센서스를 아예 안 주는 종목이 많아
    #    (전체가 아니라 '일부 커버리지 없음'이 정상적으로 흔함) 이것 때문에
    #    Trailing 데이터까지 멀쩡한 종목 전체를 차단하는 건 낭비입니다.
    #    → 종목 전체를 막지 않고, "Forward 섹션만 데이터 없음"으로 표시합니다 (pegy_view에서 마스크 처리).
    forward_missing = [k for k in ("f_per", "growth", "f_eps") if cleaned.get(k) is None]
    cleaned['forward_data_missing'] = bool(forward_missing)
    if forward_missing:
        cleaned['forward_missing_fields'] = forward_missing

    # 1. Price & PER Sanity Check (스케일 오류 및 음수/무한대 PER 차단) — f_per가 있을 때만 검사
    # (2차 감사 6-3: 300 임계치는 utils/constants.py 단일 출처에서만 가져옵니다)
    if f_per is not None and (f_per <= 0 or f_per > PER_EXTREME_MAX):
        return _finish(False, True, reject_reason="PER/주가 산출 범위 초과 또는 데이터 오염")

    # 2. 상장주식수 sanity range check
    #    (구 버전은 total_dividend_krw 와 dps*주식수 를 비교했으나, 두 값이 같은 계산에서
    #     나온 동어반복이라 197종목의 파싱 오류를 단 한 건도 잡아내지 못했습니다.
    #     서로 다른 출처의 총배당금 공시를 수집하기 전까지는 범위 검증으로 대체합니다.)
    if outstanding_shares and outstanding_shares < MIN_OUTSTANDING_SHARES:
        return _finish(
            False, True,
            reject_reason=f"상장주식수 파싱 오류 의심 ({outstanding_shares:,}주 < {MIN_OUTSTANDING_SHARES:,}주)"
        )

    # 3. 실효성장률(g_eff) — Forward 데이터가 원래부터 없는 종목은 g_eff도 당연히 없으므로
    #    위 0-1에서 이미 "Forward 없음"으로 표시했습니다. 여기서 또 차단하면 이중 차단이라 생략합니다.
    #    Forward 데이터가 있는데도 g_eff만 유독 없다면, 그건 진짜 산출 이상이므로 그대로 차단합니다.
    g_eff = cleaned.get('g_eff')
    if not forward_missing:
        if g_eff is None:
            return _finish(False, True, reject_reason="실효성장률(g_eff) 산출 불가")

        if g_eff <= 0:
            # 역성장 종목: 데이터는 정상이므로 차단하지 않되, 스코어링의 역성장 컷오프에서 처리됩니다.
            cleaned['is_negative_growth'] = True
            return _finish(True, False)

    # 4. 배당 필수 업종(리츠/인프라/금융)인데 DPS·배당수익률이 모두 0으로 수집된 경우.
    #    ⚠️ 2026-08-06 변경: 예전엔 종목 전체를 차단(is_unverified=True)했습니다. 하지만 국내 상장사는
    #    아직 주주환원율이 높지 않고 실제로 배당을 전혀 안 주는 곳도 많아서(오너 지적), "배당필수업종인데
    #    DPS=0"이라는 것만으로 종목 전체의 Trailing 데이터까지 못 믿게 막는 건 과합니다.
    #    → 종목 전체는 차단하지 않고, Forward 카드 자리에만 확인-필요 배지를 띄웁니다
    #    (Trailing 지표·퀀트 점수는 수집된 값 그대로 정상 반영 — views/pegy_view.py에서 렌더링).
    #    ⚠️ 2026-08-06 2차 감사 6-1: 키워드 목록에서 '우B'(우선주 표기) 제거 — 업종이 아닙니다.
    #    ⚠️ 2026-08-06 2차 감사 1-4: 이제 dps/sh_return 은 None(미수집)과 0(무배당 확정)이
    #       구분되므로, 두 경우의 안내 문구도 분리합니다.
    is_high_dividend_sector = any(kw in name for kw in HIGH_DIVIDEND_SECTOR_KEYWORDS)
    dividend_not_collected = (dps is None or sh_return is None or cleaned.get('dps_source') == 'not_collected')
    if dividend_not_collected:
        cleaned['dividend_data_unverified'] = True
        cleaned['dividend_unverified_reason'] = (
            "이 종목의 배당 데이터(DPS·배당수익률)를 수집하지 못했습니다.<br>"
            "'배당이 없다'는 뜻이 아니라 '값을 확인하지 못했다'는 뜻이며, 주주환원 점수는 배점에서 제외됩니다."
        )
    elif is_high_dividend_sector and (dps or 0) <= 0 and (sh_return or 0) <= 0:
        cleaned['dividend_data_unverified'] = True
        cleaned['dividend_unverified_reason'] = (
            "이 종목은 리츠·인프라·금융 등 배당 필수 업종인데 DPS(주당배당금)·배당수익률이 모두 0으로 확인되었습니다.<br>"
            "실제로 무배당일 수도 있고 공시 데이터가 아직 반영되지 않았을 수도 있습니다."
        )

    return _finish(True, False)
