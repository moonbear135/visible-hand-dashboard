"""
utils/guardrail.py
KOSPI 200 및 글로벌 종목 전용 데이터 방공망 (Valuation Guardrail)
"""

import pandas as pd
import numpy as np

def apply_valuation_guardrail(stock_data: dict) -> dict:
    """
    KOSPI 200 및 글로벌 종목 전용 데이터 검증 & 하드 컷오프 모듈
    """
    cleaned = stock_data.copy()
    
    price = cleaned.get('price', 0)
    f_per = cleaned.get('f_per', 0)
    growth = cleaned.get('growth', 0)
    sh_return = cleaned.get('sh_return', 0) # 주주환원율(%)
    
    # 1. Price & PER Sanity Check (스케일 오류 및 음수/무한대 PER 차단)
    if price <= 0 or f_per <= 0 or f_per > 300:
        cleaned['is_valid'] = False
        cleaned['reject_reason'] = "PER/주가 산출 범위 초과 또는 데이터 오염"
        cleaned['quant_score'] = 0
        cleaned['badge'] = "🔴 측정 불가 (데이터 오류)"
        cleaned['badge_bg'] = "#451a03"
        cleaned['badge_fg'] = "#f97316"
        return cleaned

    # 2. 실효성장률(g_eff) Cap 및 Hard Cut-off
    growth_capped = min(growth, 35.0) # 성장률 35% 상한 적용
    g_eff = growth_capped + sh_return
    
    cleaned['g_eff'] = round(g_eff, 2)
    
    # 3. 역성장/무성장 기업 (g_eff <= 0) 하드 컷오프
    if g_eff <= 0:
        cleaned['is_valid'] = True
        cleaned['f_pegy'] = 99.0 # 음수 PEGY 착시 방지를 위한 고평가 페널티 지정
        cleaned['quant_score'] = max(0, cleaned.get('quant_score', 50) - 40) # 40점 강제 감점
        cleaned['badge'] = "🔴 역성장/무성장 (가치 훼손)"
        cleaned['badge_bg'] = "#7f1d1d"
        cleaned['badge_fg'] = "#fca5a5"
        # 목표주가 삭감 (현재가 이하 하방 페널티)
        cleaned['f_target'] = round(price * 0.7, 0)
        return cleaned

    cleaned['is_valid'] = True
    return cleaned
