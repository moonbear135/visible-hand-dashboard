import os
import math
import pandas as pd
import FinanceDataReader as fdr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")

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

def patch_missing_fridays():
    if not os.path.exists(HISTORY_FILE):
        print("[Error] DB file not found.")
        return
        
    print("Starting Friday patch process...")
    
    # 1. 기존 데이터 로드
    df = pd.read_csv(HISTORY_FILE)
    df_eng = df.rename(columns={v: k for k, v in COL_MAP.items()})
    
    # 2. FDR을 통해 전체 기간 시세 다시 가져오기
    try:
        kospi_full = fdr.DataReader('^KS11', '2026-06-01', '2026-07-31')
        usd_full = fdr.DataReader('USDKRW=X', '2026-06-01', '2026-07-31')
    except Exception as e:
        print("[Error] Failed to fetch data from FDR:", e)
        return

    # 누락된 날짜 리스트 검출
    target_fridays = [
        "2026-06-05", "2026-06-12", "2026-06-19", "2026-06-26",
        "2026-07-03", "2026-07-10", "2026-07-17", "2026-07-24"
    ]
    
    patched_rows = []
    
    for f_date in target_fridays:
        if f_date in df_eng["Date"].values:
            continue
            
        print(f"Patching missing Friday: {f_date}")
        
        # KOSPI 종가 획득
        try:
            k_price = float(kospi_full.loc[f_date]['Close'])
            # 변화율 계산
            k_idx = kospi_full.index.get_loc(f_date)
            k_prev = float(kospi_full.iloc[k_idx-1]['Close'])
            k_change = (k_price - k_prev) / k_prev
            
            # 10일 변동성 계산
            k_vol = float(kospi_full.iloc[k_idx-10:k_idx+1]['Close'].pct_change().std()) * 100
            
            # 52주 고점 대비 낙폭
            high_52 = float(kospi_full.iloc[max(0, k_idx-252):k_idx+1]['Close'].max())
            dist_high = (high_52 - k_price) / high_52
        except Exception:
            # 예외시 평균치 적용
            k_price = 7000.0
            k_change = 0.0
            k_vol = 1.2
            dist_high = 0.1

        # USD/KRW 환율 획득 (시차 문제 해결을 위해 전후 가장 가까운 값 활용)
        try:
            if f_date in usd_full.index:
                u_price = float(usd_full.loc[f_date]['Close'])
                u_idx = usd_full.index.get_loc(f_date)
                u_prev = float(usd_full.iloc[u_idx-1]['Close'])
                u_change = (u_price - u_prev) / u_prev
            else:
                # 당일 날짜가 없으면 가장 가까운 이전 영업일 값 조회
                nearest_date = usd_full.index[usd_full.index < f_date][-1]
                u_price = float(usd_full.loc[nearest_date]['Close'])
                u_change = 0.0
        except Exception:
            u_price = 1450.0
            u_change = 0.0
            
        # 3. 13가지 리스크 세부 지표 계산 (기본 역산식 적용)
        fx_base = 0.5 + 0.3 * (u_price - 1200) / 300
        put_base = 0.5 - 0.4 * k_change
        short_base = 0.4 + 0.4 * (k_vol / 5.0)
        els_base = 0.1 + 0.7 * dist_high
        skew_base = 0.4 + 0.4 * (k_vol / 5.0) - 0.2 * k_change
        synth_base = 0.5 + 0.3 * (u_price - 1300) / 200
        ndf_base = 0.4 + 0.5 * u_change
        fut_base = 0.5 - 0.3 * k_change
        non_base = 0.5 - 0.1 # 금요일 평균수급 보정
        dump_base = 0.5 - 0.2
        bal_base = 0.5 + 0.3 * dist_high
        put_buy_base = 0.4 - 0.3 * k_change
        stock_net_base = 0.5

        market_scores = {
            "FX_Swap_Point": clip(fx_base),
            "Put_OTM_OI": clip(put_base),
            "Short_Ratio": clip(short_base),
            "ELS_KnockIn": clip(els_base),
            "VKOSPI_Skew": clip(skew_base),
            "Synthetic_Futures": clip(synth_base),
            "NDF_Night_Rate": clip(ndf_base),
            "Futures_Net_Sell": clip(fut_base),
            "Non_Arbitrage_Ratio": clip(non_base),
            "Foreign_Broker_Dump": clip(dump_base),
            "Stock_Short_Balance": clip(bal_base),
            "Put_Buy_Simple": clip(put_buy_base),
            "Stock_Net_Sell": clip(stock_net_base)
        }

        # 신규 행 레코드 구성
        new_row = {
            "Date": f_date,
            "Score": 50.0, # 나중에 일괄 재계산
            "KOSPI": round(k_price, 2),
            "USD_KRW": round(u_price, 2),
            "Retail": 0,
            "Foreigner": 0,
            "Institution": 0
        }
        for item in weights.keys():
            new_row[item] = round(market_scores[item], 3)
            
        patched_rows.append(new_row)

    if patched_rows:
        df_new_fridays = pd.DataFrame(patched_rows)
        df_eng = pd.concat([df_eng, df_new_fridays], ignore_index=True)
        
        # 날짜 순서대로 정렬
        df_eng = df_eng.sort_values(by="Date").reset_index(drop=True)
        
        # 4. 전체 리스트 스코어 재계산 (비선형 스큐 적용)
        recalculated_scores = []
        investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}
        
        for i in range(len(df_eng)):
            historical_stats = {}
            history_slice = df_eng.iloc[:i]
            
            for item in weights.keys():
                if len(history_slice) >= 2 and item in history_slice.columns:
                    mean_val = history_slice[item].mean()
                    std_val = history_slice[item].std()
                    if pd.isna(std_val) or std_val == 0:
                        std_val = 0.15
                else:
                    mean_val = 0.5
                    std_val = 0.15
                historical_stats[item] = {"mean": mean_val, "std": std_val}
                
            row = df_eng.iloc[i]
            sub_scores = {}
            extreme_signal_count = 0
            
            for item in weights.keys():
                raw_val = row[item]
                mean = historical_stats[item]["mean"]
                std = historical_stats[item]["std"]
                
                z = (raw_val - mean) / std
                z_safe = max(-20.0, min(20.0, z))
                
                sub_score = 100 / (1 + math.exp(-1.8 * z_safe))
                sub_scores[item] = sub_score
                
                if sub_score >= 80 or sub_score <= 20:
                    extreme_signal_count += 1
                    
            base_score = sum(sub_scores[k] * (weights[k] / 100.0) for k in weights)
            
            multiplier = 1.0
            if extreme_signal_count >= 5:
                multiplier = 1.5
            elif extreme_signal_count >= 3:
                multiplier = 1.25
                
            final_score = 50.0 + (base_score - 50.0) * multiplier
            final_score = round(max(0.0, min(100.0, final_score)), 1)
            recalculated_scores.append(final_score)
            
        df_eng["Score"] = recalculated_scores
        df_eng.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
        print("Friday patch and score recalculation successfully completed!")
    else:
        print("No missing Fridays to patch.")

if __name__ == "__main__":
    patch_missing_fridays()
