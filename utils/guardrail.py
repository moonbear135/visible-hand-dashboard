"""
utils/guardrail.py
KOSPI 200 및 글로벌 종목 전용 데이터 방공망 (Valuation Guardrail)

⚠️ ENGINEERING_SPEC §0-1 (하드코딩·더미 데이터 금지) 준수 규칙
   - 이 모듈은 상위 단계(DataValidator)의 검증 결과를 **절대 상향(False → True)하지 않습니다.**
   - 검증 결과는 AND 로만 결합합니다. 즉 어느 한 단계라도 실패하면 최종 is_valid 는 False 입니다.
"""

MIN_OUTSTANDING_SHARES = 1_000_000  # 상장주식수 sanity range check 하한 (collector 와 동일 기준)


def apply_valuation_guardrail(stock_data: dict) -> dict:
    """
    KOSPI 200 및 글로벌 종목 전용 데이터 검증 & 하드 컷오프 모듈
    - PER / 주가 스케일 오류 검증
    - 상장주식수 sanity range check (파싱 오염 탐지)
    - g_eff <= 0 역성장 표시
    - 주주환원율(DPS/자사주) 공시 데이터 미확정 및 신뢰 불가 종목 차단 마스크 부여
    """
    cleaned = stock_data.copy()

    # 상위 단계(DataValidator)의 판정을 그대로 승계 — 여기서 True 로 덮어쓰지 않습니다.
    inherited_valid = bool(cleaned.get('is_valid', True))
    inherited_unverified = bool(cleaned.get('is_unverified', False))
    validation_error = cleaned.get('validation_error')

    price = cleaned.get('price') or 0
    f_per = cleaned.get('f_per')
    sh_return = cleaned.get('sh_return') or 0  # 배당수익률(%) 기준
    dps = cleaned.get('dps') or 0
    name = cleaned.get('name', '')
    outstanding_shares = cleaned.get('outstanding_shares') or 0

    def _finish(is_valid, is_unverified, reject_reason=None, unverified_reason=None):
        """검증 결과 결합: 상위 판정과 AND 로만 합칩니다."""
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

    # 0. 필수 수치 결측 (수집 실패) — 지어내지 않고 즉시 마스킹
    missing = [k for k in ("price", "f_per", "growth", "f_eps") if cleaned.get(k) is None]
    if missing or price <= 0:
        return _finish(False, True, reject_reason=f"필수 지표 수집 실패 ({', '.join(missing) if missing else 'price'})")

    # 1. Price & PER Sanity Check (스케일 오류 및 음수/무한대 PER 차단)
    if f_per <= 0 or f_per > 300:
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

    # 3. 실효성장률(g_eff) — 역성장/무성장은 차단이 아니라 '위험' 표시 대상
    g_eff = cleaned.get('g_eff')
    if g_eff is None:
        return _finish(False, True, reject_reason="실효성장률(g_eff) 산출 불가")

    if g_eff <= 0:
        # 역성장 종목: 데이터는 정상이므로 차단하지 않되, 스코어링의 역성장 컷오프에서 처리됩니다.
        cleaned['is_negative_growth'] = True
        return _finish(True, False)

    # 4. 주주환원 공시 미확정 / 배당 필수 업종(리츠/인프라/금융) 데이터 무결성 검증
    is_high_dividend_sector = any(kw in name for kw in ['리츠', '인프라', '금융지주', '우B'])
    if is_high_dividend_sector and dps <= 0 and sh_return <= 0:
        return _finish(True, True, unverified_reason="⚠️ 데이터 검증 필요 (주주환원/배당 공시 미확정)")

    return _finish(True, False)
