"""
utils/guardrail.py
코스피 시가총액 상위 200 및 글로벌 종목 전용 데이터 방공망 (Valuation Guardrail)

⚠️ ENGINEERING_SPEC §0-1 (하드코딩·더미 데이터 금지) 준수 규칙
   - 이 모듈은 상위 단계(DataValidator)의 검증 결과를 **절대 상향(False → True)하지 않습니다.**
   - 검증 결과는 AND 로만 결합합니다. 즉 어느 한 단계라도 실패하면 최종 is_valid 는 False 입니다.
"""

MIN_OUTSTANDING_SHARES = 1_000_000  # 상장주식수 sanity range check 하한 (collector 와 동일 기준)


def apply_valuation_guardrail(stock_data: dict) -> dict:
    """
    코스피 시가총액 상위 200 및 글로벌 종목 전용 데이터 검증 & 하드 컷오프 모듈
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
    if f_per is not None and (f_per <= 0 or f_per > 300):
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
    is_high_dividend_sector = any(kw in name for kw in ['리츠', '인프라', '금융지주', '우B'])
    if is_high_dividend_sector and dps <= 0 and sh_return <= 0:
        cleaned['dividend_data_unverified'] = True
        cleaned['dividend_unverified_reason'] = (
            "이 종목은 리츠·인프라·금융 등 배당 필수 업종인데 DPS(주당배당금)·배당수익률이 모두 0으로 수집되었습니다.<br>"
            "실제로 무배당일 수도 있고 공시 데이터가 아직 반영되지 않았을 수도 있습니다."
        )

    return _finish(True, False)
