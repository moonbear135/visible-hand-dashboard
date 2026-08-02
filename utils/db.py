import os
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")

# 한글 파일 보관용 컬럼 매핑 딕셔너리 정의
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
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)",
    "KOSPI_5D_Return": "KOSPI 5일 낙폭 모멘텀 (지수 폭락 감지용 직접 지표)"
}

def backfill_missing_metrics(df):
    """
    구형 CSV 파일에 14가지 세부 지표 위험도가 누적 저장되어 있지 않은 경우,
    역사적 수치(KOSPI, 환율, 수급 등)를 기반으로 금융공학 역산 모델을 돌려 백필(마이그레이션)합니다.
    """
    if "FX_Swap_Point" in df.columns and "KOSPI_5D_Return" in df.columns:
        return df
        
    df = df.sort_values(by="Date").reset_index(drop=True)
    df["KOSPI_pct"] = df["KOSPI"].pct_change().fillna(0)
    df["USD_pct"] = df["USD_KRW"].pct_change().fillna(0)
    df["KOSPI_5d_prev"] = df["KOSPI"].shift(5)
    df["KOSPI_5d_return"] = ((df["KOSPI"] - df["KOSPI_5d_prev"]) / df["KOSPI_5d_prev"]).fillna(0.0)
    
    # 변동성 및 고점 하락률 계산
    df["vol"] = df["KOSPI_pct"].rolling(10, min_periods=1).std().fillna(0.012) * 100
    df["high_52w"] = df["KOSPI"].cummax()
    df["dist_high"] = (df["high_52w"] - df["KOSPI"]) / df["high_52w"]
    
    # 14가지 세부 지표 컬럼 추가
    metrics_cols = [
        "FX_Swap_Point", "Put_OTM_OI", "Short_Ratio", "ELS_KnockIn",
        "VKOSPI_Skew", "Synthetic_Futures", "NDF_Night_Rate", "Futures_Net_Sell",
        "Non_Arbitrage_Ratio", "Foreign_Broker_Dump", "Stock_Short_Balance",
        "Put_Buy_Simple", "Stock_Net_Sell", "KOSPI_5D_Return"
    ]
    for col in metrics_cols:
        df[col] = 0.5
        
    for i in range(len(df)):
        row = df.iloc[i]
        k_change = float(row["KOSPI_pct"])
        u_close = float(row["USD_KRW"])
        u_change = float(row["USD_pct"])
        vol = float(row["vol"])
        dist = float(row["dist_high"])
        ret = int(row["Retail"])
        fore = int(row["Foreigner"])
        inst = int(row["Institution"])
        k_5d_ret = float(row["KOSPI_5d_return"])
        
        fx_base = 0.5 + 0.3 * (u_close - 1200) / 300
        put_base = 0.5 - 0.4 * k_change
        short_base = 0.4 + 0.4 * (vol / 5.0)
        els_base = 0.1 + 0.7 * dist
        skew_base = 0.4 + 0.4 * (vol / 5.0) - 0.2 * k_change
        synth_base = 0.5 + 0.3 * (u_close - 1300) / 200
        ndf_base = 0.4 + 0.5 * u_change
        fut_base = 0.5 - 0.3 * k_change
        non_base = 0.5 + (0.2 if inst < 0 else -0.1)
        dump_base = 0.5 + (0.3 if fore < 0 else -0.2)
        bal_base = 0.5 + 0.3 * dist
        put_buy_base = 0.4 - 0.3 * k_change
        stock_net_base = 0.5
        kospi_5d_base = 0.5 - 2.5 * k_5d_ret
        
        def clip(val):
            return min(1.0, max(0.0, val))
            
        df.at[i, "FX_Swap_Point"] = round(clip(fx_base + 0.1 * u_change) * 0.55 + clip(fx_base) * 0.37 + clip(fx_base - 0.2) * 0.08, 3)
        df.at[i, "Put_OTM_OI"] = round(clip(put_base + (0.1 if fore < 0 else -0.1)) * 0.55 + clip(put_base + (0.05 if inst < 0 else -0.05)) * 0.37 + clip(put_base + (0.15 if ret > 0 else -0.1)) * 0.08, 3)
        df.at[i, "Short_Ratio"] = round(clip(short_base + (0.1 if fore < 0 else -0.05)) * 0.55 + clip(short_base + (0.05 if inst < 0 else -0.05)) * 0.37 + clip(short_base - 0.2) * 0.08, 3)
        df.at[i, "ELS_KnockIn"] = round(clip(els_base) * 0.55 + clip(els_base + 0.1) * 0.37 + clip(els_base - 0.1) * 0.08, 3)
        df.at[i, "VKOSPI_Skew"] = round(clip(skew_base + 0.05) * 0.55 + clip(skew_base) * 0.37 + clip(skew_base - 0.2) * 0.08, 3)
        df.at[i, "Synthetic_Futures"] = round(clip(synth_base + (0.15 if fore < 0 else -0.1)) * 0.55 + clip(synth_base) * 0.37 + clip(synth_base + (0.05 if ret > 0 else -0.05)) * 0.08, 3)
        df.at[i, "NDF_Night_Rate"] = round(clip(ndf_base + 0.1) * 0.55 + clip(ndf_base) * 0.37 + clip(ndf_base - 0.2) * 0.08, 3)
        df.at[i, "Futures_Net_Sell"] = round(clip(fut_base + (0.2 if fore < 0 else -0.15)) * 0.55 + clip(fut_base + (0.1 if inst < 0 else -0.1)) * 0.37 + clip(fut_base + (0.15 if ret > 0 else -0.1)) * 0.08, 3)
        df.at[i, "Non_Arbitrage_Ratio"] = round(clip(non_base + 0.05) * 0.55 + clip(non_base + 0.1) * 0.37 + clip(non_base - 0.2) * 0.08, 3)
        df.at[i, "Foreign_Broker_Dump"] = round(clip(dump_base + 0.15) * 0.55 + clip(dump_base - 0.1) * 0.37 + clip(dump_base - 0.3) * 0.08, 3)
        df.at[i, "Stock_Short_Balance"] = round(clip(bal_base + 0.05) * 0.55 + clip(bal_base + 0.05) * 0.37 + clip(bal_base - 0.2) * 0.08, 3)
        df.at[i, "Put_Buy_Simple"] = round(clip(put_buy_base + (0.05 if fore < 0 else -0.05)) * 0.55 + clip(put_buy_base) * 0.37 + clip(put_buy_base + (0.1 if ret > 0 else -0.1)) * 0.08, 3)
        df.at[i, "Stock_Net_Sell"] = round(clip(stock_net_base + (0.3 if fore < 0 else -0.3)) * 0.55 + clip(stock_net_base + (0.2 if inst < 0 else -0.2)) * 0.37 + clip(stock_net_base + (0.3 if ret < 0 else -0.3)) * 0.08, 3)
        df.at[i, "KOSPI_5D_Return"] = round(clip(kospi_5d_base), 3)
        
    df = df.drop(columns=["KOSPI_pct", "USD_pct", "vol", "high_52w", "dist_high", "KOSPI_5d_prev", "KOSPI_5d_return"])
    return df

def repair_missing_supply_data(df):
    """
    CSV 로드 시 수급 데이터가 0으로 고착된 행(결손 데이터)이 발견되면,
    네이버 스크래퍼를 가동하여 실제 수급 데이터로 덮어쓰고 저장합니다.
    """
    missing_mask = (df["Retail"] == 0) & (df["Foreigner"] == 0) & (df["Institution"] == 0)
    missing_dates = df[missing_mask]["Date"].tolist()
    if not missing_dates:
        return df

    scraped_data = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        for page in range(1, 6):
            url = f'https://finance.naver.com/sise/investorDealTrendDay.nhn?sosok=01&page={page}'
            r = requests.get(url, headers=headers, timeout=10)
            r.encoding = 'euc-kr'
            soup = BeautifulSoup(r.text, 'html.parser')
            tb = soup.find('table', class_='type_1')
            if tb:
                rows = tb.find_all('tr')
                for tr in rows[2:]:
                    cells = [td.text.strip() for td in tr.find_all(['td'])]
                    cells = [c for c in cells if c]
                    if cells and len(cells) >= 4:
                        date_str = "20" + cells[0].replace(".", "-")
                        retail = int(cells[1].replace(",", ""))
                        foreigner = int(cells[2].replace(",", ""))
                        institution = int(cells[3].replace(",", ""))
                        if not (retail == 0 and foreigner == 0 and institution == 0):
                            scraped_data[date_str] = (retail, foreigner, institution)
    except Exception:
        pass

    repaired_count = 0
    for idx, row in df.iterrows():
        d = str(row["Date"])
        if d in missing_dates and d in scraped_data:
            ret, fore, inst = scraped_data[d]
            df.at[idx, "Retail"] = ret
            df.at[idx, "Foreigner"] = fore
            df.at[idx, "Institution"] = inst
            repaired_count += 1

    if repaired_count > 0:
        df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
    return df

def save_and_load_history(date_key, score, kospi_close, usd_close, retail, foreigner, institution, metrics_dict=None):
    """
    로컬 CSV 파일에 매일의 데이터를 누적 저장하고 불러옵니다.
    """
    new_data = {
        "Date": [date_key],
        "Score": [score],
        "KOSPI": [round(kospi_close, 2)],
        "USD_KRW": [round(usd_close, 2)],
        "Retail": [retail],
        "Foreigner": [foreigner],
        "Institution": [institution]
    }
    
    if metrics_dict:
        for k, v in metrics_dict.items():
            new_data[k] = [round(v, 3)]
            
    new_df = pd.DataFrame(new_data)
    is_admin = st.session_state.get("admin_mode", False)
    
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
            
            history_df = backfill_missing_metrics(history_df)
            history_df = repair_missing_supply_data(history_df)
            
            if is_admin:
                st.write(f"📝 [관리자] 기존 파일 로드 및 정규화 마이그레이션 성공. 행 개수: {len(history_df)}개")
            
            if str(date_key) not in history_df["Date"].values:
                if is_admin:
                    st.write(f"📝 [관리자] 신규 날짜 {date_key} 추가 결합 진행")
                history_df = pd.concat([history_df, new_df], ignore_index=True)
                
            history_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
        except Exception as e:
            if is_admin:
                st.error(f"❌ [관리자] 파일 읽기/쓰기 중 오류 발생: {str(e)}")
            new_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
            history_df = new_df
    else:
        if is_admin:
            st.write("📝 [관리자] 기존 파일 없음. 신규 파일 작성")
        new_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
        history_df = new_df
        
    return history_df
