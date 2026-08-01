import os
import math
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")

# 한글 파일 보관용 컬럼 매핑 딕셔너리
COL_MAP = {
    "Date": "날짜",
    "Score": "종합 위험 점수",
    "KOSPI": "코스피 종가",
    "USD_KRW": "원/달러 환율",
    "Retail": "개인 수급 (억원)",
    "Foreigner": "외국인 수급 (억원)",
    "Institution": "기관 수급 (억원)",
    "FX_Swap_Point": "외환 스왑포인트 (달러 유동성 부족 위험)",
    "Put_OTM_OI": "풋옵션 미결제약정 (시장 하락에 베팅한 대기자금)",
    "Short_Ratio": "공매도 거래 비중 (주가를 떨어뜨리려는 매도세)",
    "ELS_KnockIn": "ELS 낙인 위험 (대규모 원금손실 구간 진입 여부)",
    "VKOSPI_Skew": "공포지수 비대칭도 (투자자들의 불안 심리 강도)",
    "Synthetic_Futures": "합성선물 가격 차이 (외국인의 파생상품 하방 압력)",
    "NDF_Night_Rate": "야간 역외환율 변동 (원/달러 환율 급등 위험)",
    "Futures_Net_Sell": "선물 순매도 규모 (선물 지수 하락 압박 세기)",
    "Non_Arbitrage_Ratio": "비차익 프로그램 매도 비중 (컴퓨터 자동 매도량)",
    "Foreign_Broker_Dump": "외국계 증권사 매도세 (외국인 투자자 이탈 속도)",
    "Stock_Short_Balance": "주식 공매도 잔고 (공매도 세력이 아직 갚지 않은 주식수)",
    "Put_Buy_Simple": "풋옵션 매수 강도 (단기 주가 하락 대비 베팅 규모)",
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)"
}

weights = {
    "FX_Swap_Point": 12, "Put_OTM_OI": 10, "Short_Ratio": 8, "ELS_KnockIn": 7,
    "VKOSPI_Skew": 7, "Synthetic_Futures": 12, "NDF_Night_Rate": 12, "Futures_Net_Sell": 8,
    "Non_Arbitrage_Ratio": 7, "Foreign_Broker_Dump": 7, "Stock_Short_Balance": 4,
    "Put_Buy_Simple": 4, "Stock_Net_Sell": 4
}

def clip(val):
    return min(1.0, max(0.0, val))

def recalculate_historical_scores():
    if not os.path.exists(HISTORY_FILE):
        print("[Error] DB file not found.")
        return
        
    print("Starting historical score recalculation...")
    
    # 1. 기존 데이터 로딩
    df = pd.read_csv(HISTORY_FILE)
    
    # 내부 계산용 영문 헤더 변환
    df_eng = df.rename(columns={v: k for k, v in COL_MAP.items()})
    df_eng = df_eng.sort_values(by="Date").reset_index(drop=True)
    
    recalculated_scores = []
    investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}
    
    # 2. 순차적으로 각 일자별 Z-Score 및 비선형 스코어 역산 계산 (누적 윈도우 방식)
    for i in range(len(df_eng)):
        # i일 시점까지 쌓인 이전 데이터를 기준으로 평균/표준편차 구함 (역사적 실시간 계산 시뮬레이션)
        historical_stats = {}
        history_slice = df_eng.iloc[:i]  # 0일부터 i-1일까지의 데이터
        
        for item in weights.keys():
            if len(history_slice) >= 2 and item in history_slice.columns:
                mean_val = history_slice[item].mean()
                std_val = history_slice[item].std()
                if pd.isna(std_val) or std_val == 0:
                    std_val = 0.15
            else:
                # 역사가 짧은 초기 구간은 글로벌 기본 설정값 부여
                mean_val = 0.5
                std_val = 0.15
            historical_stats[item] = {"mean": mean_val, "std": std_val}
            
        # i일의 지표별 수급 가중치 계산
        row = df_eng.iloc[i]
        sub_scores = {}
        extreme_signal_count = 0
        
        for item in weights.keys():
            raw_val = row[item]
            mean = historical_stats[item]["mean"]
            std = historical_stats[item]["std"]
            
            z = (raw_val - mean) / std
            z_safe = max(-20.0, min(20.0, z))
            
            # 시그모이드 위험 점수 (0~100점)
            sub_score = 100 / (1 + math.exp(-1.8 * z_safe))
            sub_scores[item] = sub_score
            
            if sub_score >= 80 or sub_score <= 20:
                extreme_signal_count += 1
                
        # 1차 가중평균
        base_score = sum(sub_scores[k] * (weights[k] / 100.0) for k in weights)
        
        # 증폭기 작동
        multiplier = 1.0
        if extreme_signal_count >= 5:
            multiplier = 1.5
        elif extreme_signal_count >= 3:
            multiplier = 1.25
            
        final_score = 50.0 + (base_score - 50.0) * multiplier
        final_score = round(max(0.0, min(100.0, final_score)), 1)
        recalculated_scores.append(final_score)
        
    # 3. 새로운 비선형 스코어 주입 및 한글 변환 세이브
    df_eng["Score"] = recalculated_scores
    df_eng.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
    print("Recalculation complete. Saved updated database.")

if __name__ == "__main__":
    recalculate_historical_scores()
