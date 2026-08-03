"""
utils/guardrail.py
KOSPI 200 및 글로벌 종목 전용 데이터 방공망 (Valuation Guardrail)
"""

import pandas as pd
import numpy as np

def apply_valuation_guardrail(stock_data: dict) -> dict:
    """
    KOSPI 200 및 글로벌 종목 전용 데이터 검증 & 하드 컷오프 모듈
    - PER / 주가 스케일 오류 검증
    - g_eff <= 0 역성장 하드 컷오프
    - 주주환원율(DPS/자사주) 공시 데이터 미확정 및 신뢰 불가 종목 차단 마스크 부여
    """
    cleaned = stock_data.copy()
    
    price = cleaned.get('price', 0)
    f_per = cleaned.get('f_per', 0)
    growth = cleaned.get('growth', 0)
    sh_return = cleaned.get('sh_return', 0) # 주주환원율(%)
    dps = cleaned.get('dps', 0)
    name = cleaned.get('name', '')
    
    # 1. Price & PER Sanity Check (스케일 오류 및 음수/무한대 PER 차단)
    if price <= 0 or f_per <= 0 or f_per > 300:
        cleaned['is_valid'] = False
        cleaned['is_unverified'] = True
        cleaned['reject_reason'] = "PER/주가 산출 범위 초과 또는 데이터 오염"
        return cleaned

    # 2. 실효성장률(g_eff)
    g_eff = cleaned.get('g_eff', 0)
    
    # 3. 역성장/무성장 기업 (g_eff <= 0) 하드 컷오프
    if g_eff <= 0:
        cleaned['is_valid'] = True
        cleaned['is_unverified'] = False
        return cleaned

    # 4. 주주환원 공시 미확정 / 배당 필수 종목(리츠/인프라/금융) 데이터 무결성 검증
    # 고배당 필수 업종인데 DPS가 0원으로 집계된 경우 PEGY 수치 왜곡 방지를 위해 검증 대기 마스크 차단
    is_high_dividend_sector = any(kw in name for kw in ['리츠', '인프라', '금융지주', '우B'])
    if is_high_dividend_sector and dps <= 0 and sh_return <= 0:
        cleaned['is_valid'] = True
        cleaned['is_unverified'] = True
        cleaned['unverified_reason'] = "⚠️ 데이터 검증 필요 (주주환원/배당 공시 미확정)"
        return cleaned

    cleaned['is_valid'] = True
    cleaned['is_unverified'] = False
    return cleaned
