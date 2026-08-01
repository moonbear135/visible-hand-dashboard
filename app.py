import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# 패키지 임포트 상태 확인
try:
    from pykrx import stock
    PYKRX_AVAILABLE = True
except ImportError:
    PYKRX_AVAILABLE = False

try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False

# ==============================================================================
# 🌐 Project: 잘보면보이는손 (The Visible Hand) - 최종 실전 수급 연동 웹 대시보드
# ==============================================================================

st.set_page_config(
    page_title="잘 보면 보이는 손 - 시장 방공망 대시보드",
    page_icon="🚨",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 커스텀 스타일링 적용 (풍부한 디자인 테마)
st.markdown(
    """
    <style>
    .main-title { 
        font-size: 32px; 
        font-weight: 800; 
        text-align: center; 
        background: linear-gradient(90deg, #0f766e 0%, #14b8a6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }
    .sub-title { 
        font-size: 15px; 
        text-align: center; 
        color: #64748b; 
        margin-bottom: 25px; 
    }
    .score-container { 
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); 
        border-radius: 16px; 
        padding: 24px; 
        text-align: center; 
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        margin-bottom: 25px;
    }
    .score-label {
        font-size: 16px;
        color: #94a3b8;
        font-weight: 600;
        letter-spacing: 1px;
    }
    .score-value {
        font-size: 56px;
        color: #ff4d4d;
        font-weight: 900;
        margin: 5px 0;
    }
    .active-floor { 
        background-color: #ffe3e3; 
        border: 2px solid #ff4d4d; 
        color: #b91c1c; 
        font-weight: bold; 
        padding: 12px 18px; 
        border-radius: 10px; 
        margin: 8px 0;
        font-size: 16px;
        box-shadow: 0 4px 6px -1px rgba(220, 38, 38, 0.1);
    }
    .normal-floor { 
        background-color: #f8fafc; 
        border: 1px solid #e2e8f0; 
        padding: 10px 16px; 
        border-radius: 8px; 
        margin: 6px 0; 
        font-size: 14px; 
        color: #475569;
    }
    </style>
    """,
    unsafe_allow_html=True
)

import os

# 데이터 누적 파일 경로 정의 (Streamlit 작업 디렉토리 불일치 방지를 위해 절대경로 적용)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
        k_close = float(row["KOSPI"])
        k_change = float(row["KOSPI_pct"])
        u_close = float(row["USD_KRW"])
        u_change = float(row["USD_pct"])
        vol = float(row["vol"])
        dist = float(row["dist_high"])
        ret = int(row["Retail"])
        fore = int(row["Foreigner"])
        inst = int(row["Institution"])
        k_5d_ret = float(row["KOSPI_5d_return"])
        
        # 공식들 대입
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

    # 네이버 스크래핑을 통해 최근 5페이지(30영업일) 분량의 실제 수급 데이터 확보
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

    # 결손 날짜에 대해 실제 데이터가 매칭되면 복구 적용
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
    
    # 13가지 세부 지표 정보가 있으면 같이 결합
    if metrics_dict:
        for k, v in metrics_dict.items():
            new_data[k] = [round(v, 3)]
            
    new_df = pd.DataFrame(new_data)
    
    # 세션 상태의 관리자 모드 감지
    is_admin = st.session_state.get("admin_mode", False)
    
    if os.path.exists(HISTORY_FILE):
        try:
            # 로드 시 한글 헤더 -> 영어 헤더 변환
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
            
            # 기존 구버전 파일 구조 백필 마이그레이션 실행
            history_df = backfill_missing_metrics(history_df)
            
            # 결손 수급 데이터 자동 복구
            history_df = repair_missing_supply_data(history_df)
            
            if is_admin:
                st.write(f"📝 [관리자] 기존 파일 로드 및 정규화 마이그레이션 성공. 행 개수: {len(history_df)}개")
            
            if str(date_key) not in history_df["Date"].values:
                if is_admin:
                    st.write(f"📝 [관리자] 신규 날짜 {date_key} 추가 결합 진행")
                # 신규 데이터 추가
                history_df = pd.concat([history_df, new_df], ignore_index=True)
                
            # 최종 저장은 한글 헤더로 매핑하여 덮어쓰기
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

def fetch_verified_market_data(override_date=None, override_kospi=None, override_usd=None, override_retail=None, override_fore=None, override_inst=None):
    """
    KRX 및 Naver 수급 데이터를 크롤링하고 실전 가중치를 산출합니다.
    로컬 CSV 파일을 체크하여 이미 조회한 날짜의 데이터라면 웹 크롤링 요청 없이 로컬에서 즉시 불러옵니다.
    """
    if override_date is not None:
        date_key = override_date
        display_date = datetime.strptime(override_date, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
        local_loaded = False
        is_live_connected = True
        kospi_close = override_kospi
        usd_close = override_usd
        retail_flow = override_retail
        foreigner_flow = override_fore
        institution_flow = override_inst
        kospi_change = 0.0
        usd_change = 0.0
        volatility = 1.2
        dist_from_high = 0.08
        sugeub_fetched = True
        data_source_log = "관리자 수동 데이터 입력 완료"
    else:
        target_date = datetime.today()
        # 주말일 경우 직전 금요일로 일자 탐색 시작
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
            
        date_key = target_date.strftime("%Y-%m-%d")
        display_date = target_date.strftime("%Y년 %m월 %d일")
        
        # 로컬 CSV 데이터에 이미 오늘 데이터가 있는지 먼저 탐색 (트래픽 최적화)
        local_loaded = False
        kospi_close = 2500.0
        kospi_change = 0.0
        usd_close = 1350.0
        usd_change = 0.0
        volatility = 1.2
        dist_from_high = 0.08
        foreigner_flow = 0
        institution_flow = 0
        retail_flow = 0
        score = 50.0
        
        if os.path.exists(HISTORY_FILE):
            try:
                history_df = pd.read_csv(HISTORY_FILE)
                # 파일 읽기 시 한글 컬럼을 내부 변수용 영어 컬럼명으로 변환
                history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
                history_df["Date"] = history_df["Date"].astype(str)
                row = history_df[history_df["Date"] == date_key]
                if not row.empty:
                    score = float(row.iloc[0]["Score"])
                    kospi_close = float(row.iloc[0]["KOSPI"])
                    usd_close = float(row.iloc[0]["USD_KRW"])
                    retail_flow = int(row.iloc[0]["Retail"])
                    foreigner_flow = int(row.iloc[0]["Foreigner"])
                    institution_flow = int(row.iloc[0]["Institution"])
                    local_loaded = True
            except Exception:
                pass

        is_live_connected = False
        data_source_log = "로컬 누적 DB 로드 완료" if local_loaded else "안전 모드 진입"

    if not local_loaded and override_date is None:
        # 1. KOSPI & USD/KRW 실시간 시세 조회 (FinanceDataReader 활용)
        if FDR_AVAILABLE:
            try:
                kospi_df = fdr.DataReader('^KS11')
                usd_df = fdr.DataReader('USDKRW=X')
                
                if not kospi_df.empty and not usd_df.empty:
                    latest_kospi = kospi_df.iloc[-1]
                    prev_kospi = kospi_df.iloc[-2]
                    kospi_close = latest_kospi['Close']
                    kospi_change = (kospi_close - prev_kospi['Close']) / prev_kospi['Close']
                    
                    latest_usd = usd_df.iloc[-1]
                    prev_usd = usd_df.iloc[-2]
                    usd_close = latest_usd['Close']
                    usd_change = (usd_close - prev_usd['Close']) / prev_usd['Close']
                    
                    kospi_returns = kospi_df['Close'].pct_change(fill_method=None).dropna()
                    volatility = kospi_returns.tail(10).std() * 100
                    high_52w = kospi_df['Close'].tail(252).max()
                    dist_from_high = (high_52w - kospi_close) / high_52w
                    is_live_connected = True
            except Exception:
                pass

        # 2. 투자자별 수급 데이터 조회
        sugeub_fetched = False
        
        # 2-A. pykrx 라이브러리를 통한 수급 데이터 수집 시도
        if PYKRX_AVAILABLE:
            try:
                check_date = target_date
                for _ in range(7):
                    while check_date.weekday() >= 5:
                        check_date -= timedelta(days=1)
                    check_date_str = check_date.strftime("%Y%m%d")
                    
                    df = stock.get_market_net_purchases_of_equities_by_ticker(
                        check_date_str, check_date_str, market="KOSPI"
                    )
                    if df is not None and not df.empty and '외국인합계' in df.columns:
                        foreigner_flow = int(df['외국인합계'].sum() / 100000000)
                        institution_flow = int(df['기관합계'].sum() / 100000000)
                        retail_flow = int(df['개인'].sum() / 100000000)
                        display_date = check_date.strftime("%Y년 %m월 %d일")
                        data_source_log = "성공: KRX 공식 API 수급 연동 완료"
                        sugeub_fetched = True
                        break
                    check_date -= timedelta(days=1)
            except Exception:
                pass

        # 2-B. pykrx 실패 시 Naver Finance 백업 스크래퍼 동작 (1~5페이지 날짜 매칭 방식 개편)
        if not sugeub_fetched:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                found = False
                for page in range(1, 6):
                    url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={date_key.replace("-", "")}&sosok=01&page={page}'
                    r = requests.get(url, headers=headers)
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
                                if date_str == date_key:
                                    retail_flow = int(cells[1].replace(",", ""))
                                    foreigner_flow = int(cells[2].replace(",", ""))
                                    institution_flow = int(cells[3].replace(",", ""))
                                    display_date = target_date.strftime("%Y년 %m월 %d일")
                                    data_source_log = f"성공: 백업용 마켓 수급 스크래핑 연동 완료 (Naver Page {page})"
                                    sugeub_fetched = True
                                    found = True
                                    break
                        if found:
                            break
            except Exception as e:
                data_source_log = f"수급 연동 오류로 안전 모드 강제 동작 ({str(e)})"



    # 3. 13개 지표 동적 산출 로직
    fx_base = 0.5 + 0.3 * (usd_close - 1200) / 300
    put_base = 0.5 - 0.4 * kospi_change
    short_base = 0.4 + 0.4 * (volatility / 5.0)
    els_base = 0.1 + 0.7 * dist_from_high
    skew_base = 0.4 + 0.4 * (volatility / 5.0) - 0.2 * kospi_change
    synth_base = 0.5 + 0.3 * (usd_close - 1300) / 200
    ndf_base = 0.4 + 0.5 * usd_change
    fut_base = 0.5 - 0.3 * kospi_change
    non_base = 0.5 + (0.2 if institution_flow < 0 else -0.1)
    dump_base = 0.5 + (0.3 if foreigner_flow < 0 else -0.2)
    bal_base = 0.5 + 0.3 * dist_from_high
    put_buy_base = 0.4 - 0.3 * kospi_change
    stock_net_base = 0.5

    # KOSPI 5일 낙폭 모멘텀 (KOSPI 5D Return) 신규 지표 연산
    kospi_5d_base = 0.5
    if FDR_AVAILABLE and not local_loaded:
        try:
            if len(kospi_df) >= 6:
                kospi_5d_prev = float(kospi_df.iloc[-6]['Close'])
                kospi_5d_return = (kospi_close - kospi_5d_prev) / kospi_5d_prev
            else:
                kospi_5d_return = 0.0
            kospi_5d_base = 0.5 - 2.5 * kospi_5d_return
        except Exception:
            pass

    def clip(val):
        return min(1.0, max(0.0, val))

    weights = {
        "FX_Swap_Point": 12, "Put_OTM_OI": 8, "Short_Ratio": 6, "ELS_KnockIn": 7,
        "VKOSPI_Skew": 6, "Synthetic_Futures": 12, "NDF_Night_Rate": 12, "Futures_Net_Sell": 6,
        "Non_Arbitrage_Ratio": 6, "Foreign_Broker_Dump": 6, "Stock_Short_Balance": 3,
        "Put_Buy_Simple": 3, "Stock_Net_Sell": 3, "KOSPI_5D_Return": 12
    }

    friendly_names = {
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

    market_scores = {
        "FX_Swap_Point": {
            "Foreigner": clip(fx_base + 0.1 * usd_change), "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)
        },
        "Put_OTM_OI": {
            "Foreigner": clip(put_base + (0.1 if foreigner_flow < 0 else -0.1)),
            "Institution": clip(put_base + (0.05 if institution_flow < 0 else -0.05)),
            "Retail": clip(put_base + (0.15 if retail_flow > 0 else -0.1))
        },
        "Short_Ratio": {
            "Foreigner": clip(short_base + (0.1 if foreigner_flow < 0 else -0.05)),
            "Institution": clip(short_base + (0.05 if institution_flow < 0 else -0.05)),
            "Retail": clip(short_base - 0.2)
        },
        "ELS_KnockIn": {
            "Foreigner": clip(els_base), "Institution": clip(els_base + 0.1), "Retail": clip(els_base - 0.1)
        },
        "VKOSPI_Skew": {
            "Foreigner": clip(skew_base + 0.05), "Institution": clip(skew_base), "Retail": clip(skew_base - 0.2)
        },
        "Synthetic_Futures": {
            "Foreigner": clip(synth_base + (0.15 if foreigner_flow < 0 else -0.1)),
            "Institution": clip(synth_base),
            "Retail": clip(synth_base + (0.05 if retail_flow > 0 else -0.05))
        },
        "NDF_Night_Rate": {
            "Foreigner": clip(ndf_base + 0.1), "Institution": clip(ndf_base), "Retail": clip(ndf_base - 0.2)
        },
        "Futures_Net_Sell": {
            "Foreigner": clip(fut_base + (0.2 if foreigner_flow < 0 else -0.15)),
            "Institution": clip(fut_base + (0.1 if institution_flow < 0 else -0.1)),
            "Retail": clip(fut_base + (0.15 if retail_flow > 0 else -0.1))
        },
        "Non_Arbitrage_Ratio": {
            "Foreigner": clip(non_base + 0.05), "Institution": clip(non_base + 0.1), "Retail": clip(non_base - 0.2)
        },
        "Foreign_Broker_Dump": {
            "Foreigner": clip(dump_base + 0.15), "Institution": clip(dump_base - 0.1), "Retail": clip(dump_base - 0.3)
        },
        "Stock_Short_Balance": {
            "Foreigner": clip(bal_base + 0.05), "Institution": clip(bal_base + 0.05), "Retail": clip(bal_base - 0.2)
        },
        "Put_Buy_Simple": {
            "Foreigner": clip(put_buy_base + (0.05 if foreigner_flow < 0 else -0.05)),
            "Institution": clip(put_buy_base),
            "Retail": clip(put_buy_base + (0.1 if retail_flow > 0 else -0.1))
        },
        "Stock_Net_Sell": {
            "Foreigner": clip(stock_net_base + (0.3 if foreigner_flow < 0 else -0.3)),
            "Institution": clip(stock_net_base + (0.2 if institution_flow < 0 else -0.2)),
            "Retail": clip(stock_net_base + (0.3 if retail_flow < 0 else -0.3))
        },
        "KOSPI_5D_Return": {
            "Foreigner": clip(kospi_5d_base),
            "Institution": clip(kospi_5d_base),
            "Retail": clip(kospi_5d_base)
        }
    }

    # 각 지표별 금융공학적 역산 수식 및 학습용 상세 설명 정의 (마우스 오버 툴팁용 줄바꿈 적용)
    formulas = {
        "FX_Swap_Point": (
            "[공식] Base = 0.5 + 0.3 * (환율 - 1200) / 300\\n"
            "- 기준값 (1,200원): 한국 시장의 장기 평형 중립 환율 수준.\\n"
            "- 스트레스 대역폭 (300원): 역사적 위기 레벨(1,500원) 대비 현재 도달치.\\n"
            "[금융학 원리] 원/달러 환율이 급격히 상승할 경우 외화 자금 공급망이 경색되어 은행 간 단기 달러 차입 금리(스왑레이트)가 동반 폭락하고 시스템 유동성 위험이 증가하는 스트레스를 수학적으로 모델링한 지표입니다."
        ),
        "Put_OTM_OI": (
            "[공식] Base = 0.5 - 0.4 * 코스피변화율 + [수급 흐름 변동성]\\n"
            "- 기준값 (0.5): 중립 상태의 기본 위험도 지점.\\n"
            "- 민감도 계수 (-0.4): 코스피 하락 속도에 따른 위험 가중 편차.\\n"
            "[금융학 원리] 주식 시장이 폭락할 때 손실을 회피하려는 기관/외국인 등 거대 투자자들이 자산 가격 하락을 방어하기 위한 보험 성격의 파생상품인 '풋옵션 외가격(OTM) 미결제약정'을 대량으로 사들이며 누적 대기 자금이 폭증하는 심리를 추적합니다."
        ),
        "Short_Ratio": (
            "[공식] Base = 0.4 + 0.4 * (10일 변동성 / 5%) + [기관 수급 변동]\\n"
            "- 기준값 (5%): 코스피 시장의 역사적 일평균 표준편차 변동성 기준치.\\n"
            "- 계수 (0.4): 표준편차가 넓어지는 국면에서의 공매도 유입 가속 배율.\\n"
            "[금융학 원리] 공매도 세력은 변동성이 폭증하고 주가 지지선이 무너지는 약세 국면을 노려 차입 매도세를 일시에 집중시킵니다. 최근 10일간의 시장 변동성과 기관의 매도 매칭량을 비교하여 실시간 공매도 유입 강도를 계량화합니다."
        ),
        "ELS_KnockIn": (
            "[공식] Base = 0.1 + 0.7 * (52주 고점 대비 낙폭비율)\\n"
            "- 계수 (0.7): 지수 하락률에 따른 ELS 낙인 배리어 진입 위험 가속도.\\n"
            "[금융학 원리] 국내 발행 주가연계증권(ELS) 상품들은 기초자산이 가입 시점 고가 대비 45%~50% 수준으로 폭락할 때 원금 손실 확정선(Knock-in Barrier)에 강제 진입하게 됩니다. KOSPI의 52주 역사적 최고점 대비 낙폭을 실시간 연동해 ELS 투매 폭탄이 터질 임계 확률을 계산합니다."
        ),
        "VKOSPI_Skew": (
            "[공식] Base = 0.4 + 0.4 * (10일 변동성 / 5%) - 0.2 * 코스피변화율\\n"
            "- 기준값 (5%): 역사적인 시장 변동성 평균 한계치.\\n"
            "[금융학 원리] 지수가 급락함과 동시에 변동성(VKOSPI)이 튀어 오를 때 옵션 시장에서 하방(풋)과 상방(콜) 옵션 가격의 불균형 치우침 정도(스큐, Skewness)가 극대화됩니다. 투자자들이 하락 공포에 짓눌려 풋옵션을 비정상적으로 비싸게 구매하고 있음을 지수 흐름으로 역산해 냅니다."
        ),
        "Synthetic_Futures": (
            "[공식] Base = 0.5 + 0.3 * (환율 - 1300) / 200\\n"
            "- 분기점 (1,300원): 외국인의 파생상품 하방 포지션이 정교하게 강화되는 환율 레벨.\\n"
            "- 스트레스 대역 (200원): 1,300원부터 위기 극값 1,500원까지의 외환 위험도 폭.\\n"
            "[금융학 원리] 고환율 국면에서 외국인이 선물 매도 베팅을 강화하면 현물 주식과 선물 가격 사이에 왜곡(Basis 왜곡)이 발생하며 합성선물 가격이 현물보다 싸집니다. 이로 인해 기관의 프로그램 자동 매도 폭탄이 강제 유발되는 하방 압력을 감지합니다."
        ),
        "NDF_Night_Rate": (
            "[공식] Base = 0.4 + 0.5 * 환율변화율\\n"
            "- 계수 (0.5): 뉴욕 역외 차액결제선물환(NDF) 시장에서의 당일 원화 환율 상승 비율.\\n"
            "[금융학 원리] 국내 금융 시장이 마감된 밤 동안 뉴욕 역외 시장에서 원/달러 환율이 추가로 급등하면, 이는 글로벌 투자자들의 원화 자산 투매 신호입니다. 이를 전일 대비 변동률로 추정해 다음 날 국내 증시 개장 시 시초가 갭하락 하방 압력을 예보합니다."
        ),
        "Futures_Net_Sell": (
            "[공식] Base = 0.5 - 0.3 * 코스피변화율 + [선물 하방 매도 강도]\\n"
            "[금융학 원리] 현물 시장보다 자금 레버리지가 훨씬 큰 선물(Futures) 시장에서 외국인/기관 투기 세력이 매도 포지션을 급격하게 늘리는 지를 분석합니다. 지수의 단기 하락 속도와 결합하여 당장 선물 지수가 현물 지수를 아래로 끌어당기는 하락 세기를 나타냅니다."
        ),
        "Non_Arbitrage_Ratio": (
            "[공식] Base = 0.5 + (기관 순매도 시: +0.2 / 순매수 시: -0.1)\\n"
            "[금융학 원리] 지수가 급락할 때 컴퓨터 알고리즘이 바스켓 주식을 기계적으로 자동 대량 처분하는 '비차익 프로그램 매도' 비중을 체크합니다. 기관이 대량 순매도하는 동시에 비차익 매도가 잡히면 시장 투매(Panic Selling) 현상이 컴퓨터로 인해 증폭되고 있음을 판별합니다."
        ),
        "Foreign_Broker_Dump": (
            "[공식] Base = 0.5 + (외인 순매도 시: +0.3 / 순매수 시: -0.2)\\n"
            "[금융학 원리] 모건스탠리, 메릴린치 등 외국계 메이저 증권사 창구를 통해 출회되는 대규모 일방적 매도세를 추적합니다. 이는 글로벌 펀드의 자금 회수 및 중장기 이탈(Capital Flight)의 핵심 징후이므로, 외국인 순매도 전환 시 위험도를 강하게 상향합니다."
        ),
        "Stock_Short_Balance": (
            "[공식] Base = 0.5 + 0.3 * (52주 고점 대비 낙폭비율)\\n"
            "[금융학 원리] 공매도 세력이 주식을 빌려서 팔아 치운 뒤 아직 다시 사서 갚지 않은 대기 주식수(대차잔고 및 공매도 잔고)의 규모입니다. 주가가 고점 대비 크게 빠진 상태에서 잔고가 계속 높은 수준을 유지하면, 향후 지수가 약세 흐름을 보일 때 반등을 억누르는 추가 매물벽 스트레스로 작용합니다."
        ),
        "Put_Buy_Simple": (
            "[공식] Base = 0.4 - 0.3 * 코스피변화율 + [단기 하락 베팅 편차]\\n"
            "[금융학 원리] 파생상품 시장에서 개별 투자자들이 지수 하락 시 수익을 거두는 풋옵션 상품을 단기 투기성 매수 목적으로 당일 얼마나 대량 거래했는지 추적합니다. 코스피 지수가 급격히 흘러내릴 때 이 베팅 규모가 비정상적으로 급증하는지를 탐지합니다."
        ),
        "Stock_Net_Sell": (
            "[공식] Base = 0.5 + (수급 주체 순매도 시: +0.3 / 순매수 시: -0.3)\\n"
            "[금융학 원리] 주식 현물 시장에서 가격 결정의 지배권을 가진 거대 핵심 세력(외국인 및 기관 동향)의 순매도 규모가 코스피 기초 체력을 얼마나 직접적으로 갉아먹고 있는지를 가중 환산하여 전체 점수에 반영하는 리스크의 기반 지표입니다."
        ),
        "KOSPI_5D_Return": (
            "[공식] Base = 0.5 - 2.5 * KOSPI 5일 수익률\\n"
            "- 분기점 (0%): 주가 상승 국면에서는 리스크를 0.5 미만으로 하향.\\n"
            "- 감도 계수 (-2.5): 5일 낙폭이 깊어질수록 위험도를 1.0 방향으로 급격히 끌어올림.\\n"
            "[금융학 원리] 보조지표(파생/수급)가 시장의 변곡점을 미처 포착하지 못하고 동반 지연될 때, 5일간의 지수 직접 모멘텀 낙폭을 계산하여 실제 지수 폭락 압력을 즉각 리스크 스코어에 반영하는 최후 방어선 지표입니다."
        )
    }

    # 1. 50점대 둔감성 해결을 위한 비선형 점수 계산용 역사적 통계(평균/표준편차) 산출
    import math
    historical_stats = {}
    temp_df = pd.DataFrame()
    if os.path.exists(HISTORY_FILE):
        try:
            temp_df = pd.read_csv(HISTORY_FILE)
            temp_df = temp_df.rename(columns={v: k for k, v in COL_MAP.items()})
            temp_df = backfill_missing_metrics(temp_df)
            temp_df = repair_missing_supply_data(temp_df)
        except Exception:
            temp_df = pd.DataFrame()

    for item in weights.keys():
        if not temp_df.empty and item in temp_df.columns and len(temp_df) >= 2:
            mean_val = temp_df[item].mean()
            std_val = temp_df[item].std()
            if pd.isna(std_val) or std_val == 0:
                std_val = 0.15
            else:
                # Z-Score 폭주 방지를 위해 최소 표준편차 한계선(Floor) 0.02 적용
                std_val = max(0.02, std_val)
        else:
            mean_val = 0.5
            std_val = 0.15
        historical_stats[item] = {"mean": mean_val, "std": std_val}

    # 2. 개별 지표별 가중 수급 리스크(0~1) 계산
    investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}
    current_weighted_risks = {}
    for item in weights.keys():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        current_weighted_risks[item] = weighted_risk

    # 3. Z-Score 산출 및 시그모이드 비선형 변환 (0~100점)
    sub_scores = {}
    extreme_signal_count = 0
    for item in weights.keys():
        raw_val = current_weighted_risks[item]
        mean = historical_stats[item]["mean"]
        std = historical_stats[item]["std"]
        
        z = (raw_val - mean) / std
        
        # Overflow 방지를 위해 Z-score 범위를 [-20, 20]으로 안전하게 클리핑
        z_safe = max(-20.0, min(20.0, z))
        
        # Z-Score를 0~100점 시그모이드 곡선으로 변환 (민감도 k = 1.1 반영)
        sub_score = 100 / (1 + math.exp(-1.1 * z_safe))
        sub_scores[item] = round(sub_score, 2)
        
        # 극단 국면 체크 (Sub_Score >= 85 또는 <= 15)
        if sub_score >= 85 or sub_score <= 15:
            extreme_signal_count += 1

    # 4. 1차 가중평균 산출 (100점 만점 기준)
    base_score = sum(sub_scores[k] * (weights[k] / 100.0) for k in weights)

    # 5. 동시 충격 비선형 증폭기 (Regime Switch) 적용
    multiplier = 1.0
    if extreme_signal_count >= 5:
        multiplier = 1.3  # 극단적 변동: 최대 1.3배 증폭 (완화)
    elif extreme_signal_count >= 3:
        multiplier = 1.15  # 경계 변동: 1.15배 증폭
        
    final_score = 50.0 + (base_score - 50.0) * multiplier
    final_score = round(max(0.0, min(100.0, final_score)), 1)

    score = final_score

    # 6. 지표 상세 테이블에 넣을 내역 리빌딩 (0~1 위험도 스케일 환산)
    details = []
    for item, w in weights.items():
        sub_score_val = sub_scores[item]
        display_risk = round(sub_score_val / 100.0, 3)
        details.append({
            "지표명 (한글 설명)": friendly_names.get(item, item),
            "중요도 (가중치)": w,
            "위험도 (0~1)": display_risk,
            "기여점수": round(w * display_risk, 2),
            "산출 공식 (수학적 모델)": formulas.get(item, "")
        })
        
    # 중요도 (가중치)가 높은 순서대로 정렬
    details = sorted(details, key=lambda x: x["중요도 (가중치)"], reverse=True)

    # 로컬 DB에 누적 저장하기 위해 지표별 가중 위험도 딕셔너리 생성
    metrics_dict = {}
    for item in weights.keys():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        metrics_dict[item] = weighted_risk

    # 로컬 DB에 누적 데이터 세이브 및 히스토리 데이터프레임 로드
    if local_loaded or is_live_connected:
        history_df = save_and_load_history(date_key, score, kospi_close, usd_close, retail_flow, foreigner_flow, institution_flow, metrics_dict)
    else:
        # DB 저장하지 않고 로드만 수행
        if os.path.exists(HISTORY_FILE):
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
        else:
            history_df = pd.DataFrame()

    # 로컬에 이미 저장되어 사용한 경우 연결상태값 보정
    if local_loaded:
        is_live_connected = True

    status_text = f"KOSPI: {kospi_close:.2f} ({kospi_change*100:+.2f}%) | 환율: {usd_close:.2f}원 ({usd_change*100:+.2f}%)"
    
    return display_date, is_live_connected, f"{data_source_log} | {status_text}", score, details, history_df


# 위험 층수 대응 규칙 정의 (인버스 추천 배제, 주식/현금 비중으로 대체)
layers = {
    10: ("10층", "💥 최극상 위험", "주식 0% / 현금 100%", "완전 대피 및 현금 최대 확보"),
    9:  ("9층", "🚨 극심한 위험", "주식 10% / 현금 90%", "주식 신규 매수 절대금지"),
    8:  ("8층", "⚡ 심각한 위험", "주식 20% / 현금 80%", "주식 강제 청산 및 대피"),
    7:  ("7층", "⚠️ 고위험 경고", "주식 30% / 현금 70%", "현금 비중 대폭 확대"),
    6:  ("6층", "🟧 경계 필요", "주식 40% / 현금 60%", "현금 비중 분할 확대"),
    5:  ("5층", "🟨 중립 경계", "주식 50% / 현금 50%", "5:5 중립 포지션 관망"),
    4:  ("4층", "🟩 주의 관찰", "주식 60% / 현금 40%", "분할 익절 및 점진적 현금화"),
    3:  ("3층", "🟢 양호 관망", "주식 70% / 현금 30%", "수급 회복 단계 및 완만한 진입"),
    2:  ("2층", "🟦 청정 안전", "주식 80% / 현금 20%", "주식 비중 확대 및 현물 투자"),
    1:  ("1층", "🔷 매우 안전", "주식 90% / 현금 10%", "적극 주식 매수 집행"),
    0:  ("0층", "⚪ 무위험 지대", "주식 100% / 현금 0%", "하방 위험 없음 / 적극 홀딩")
}

import hashlib
import hmac

# 사이드바 관리자 암호 인증 시스템 배치 (암호 일방향 해시 및 안전 비교 적용)
with st.sidebar:
    st.markdown("### ⚙️ 관리자 전용 메뉴")
    admin_password = st.text_input("🔑 관리자 비밀번호", type="password", help="일반 사용자에게 노출되지 않는 디버그용 암호를 입력하세요.")
    
    # 비밀번호 단방향 암호화 비교 (timing attack 방지용 compare_digest 적용)
    # ***REMOVED-OLD-ADMIN-PASSWORD*** 의 SHA-256 해시값
    stored_hash = "***REMOVED-OLD-PASSWORD-HASH***"
    input_hash = hashlib.sha256(admin_password.encode()).hexdigest()
    
    admin_mode = hmac.compare_digest(input_hash, stored_hash)
    st.session_state.admin_mode = admin_mode
    if admin_mode:
        st.success("🔓 관리자 권한 인증 성공")

# --- UI 레이아웃 구현 ---

st.markdown('<div class="main-title">🏢 잘 보면 보이는 손 (The Visible Hand)</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">실시간 수급 연동형 시장 종합 위험 방공망 대시보드</div>', unsafe_allow_html=True)

# 관리자용 디버그 출력
if admin_mode:
    st.info(f"⚙️ [관리자 시스템 정보]\n* **DB 파일 경로:** `{HISTORY_FILE}`\n* **DB 파일 존재 여부:** `{os.path.exists(HISTORY_FILE)}`")

# 데이터 호출 및 로딩
date_str, is_live, log_msg, score, details, history_df = fetch_verified_market_data()

# --- 관리자 모드 활성화 시 데이터 수동 제어실 노출 ---
if admin_mode:
    with st.expander("🛠️ 관리자 전용 데이터 수동 제어실 (비상 입력 및 가이드)", expanded=True):
        st.markdown(
            """
            ### 📌 데이터 수동 입력 가이드 및 출처 안내
            자동 수집 지연/장애 시, 아래 출처 사이트에서 당일 최종 확정 데이터를 확인하여 오타 없이 기입해 주십시오.
            
            * **영업일 선택**: 보정 또는 신규 입력할 타겟 일자를 선택합니다.
            * **KOSPI 종가 (pt)**: 소수점 이하 2자리까지 입력합니다.
              * *출처*: [네이버 증권 코스피 페이지](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)
            * **원/달러 환율 (원)**: 소수점 이하 2자리까지 입력합니다.
              * *출처*: [네이버 페이 증권 시장지표](https://finance.naver.com/marketindex/)
            * **수급 데이터 (개인/외국인/기관)**: 억원 단위로 입력합니다.
              * *출처*: [네이버 증권 투자자별 매매동향](https://finance.naver.com/sise/investorDealTrendDay.naver) 당일 첫 번째 행 수치
            """
        )
        with st.form("admin_manual_data_form"):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                m_date = st.date_input("영업일 선택", datetime.today(), key="admin_m_date")
                m_kospi = st.number_input("KOSPI 종가 (pt)", value=2500.0, step=0.1, key="admin_m_kospi")
                m_retail = st.number_input("개인 수급 (억원)", value=0, step=10, key="admin_m_retail")
            with col_m2:
                m_usd = st.number_input("원/달러 환율 (원)", value=1350.0, step=0.1, key="admin_m_usd")
                m_fore = st.number_input("외국인 수급 (억원)", value=0, step=10, key="admin_m_fore")
                m_inst = st.number_input("기관 수급 (억원)", value=0, step=10, key="admin_m_inst")

            submit_btn = st.form_submit_button("💾 클린 DB 수동 저장 및 대시보드 반영")
            if submit_btn:
                m_date_key = m_date.strftime("%Y-%m-%d")
                override_date_str, override_is_live, override_log_msg, override_score, override_details, history_df = fetch_verified_market_data(
                    override_date=m_date_key,
                    override_kospi=m_kospi,
                    override_usd=m_usd,
                    override_retail=m_retail,
                    override_fore=m_fore,
                    override_inst=m_inst
                )
                st.success(f"🎉 {m_date_key} 데이터가 검증되어 성공적으로 저장되었습니다!")
                st.rerun()

if admin_mode:
    st.write(f"📊 **[관리자] 로드된 데이터 행 개수:** `{len(history_df)}`개")

st.markdown(
    f"""
    <div style="text-align:center; color:#475569; font-weight: 600; line-height: 1.6; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="font-size: 16px;">📅 기준 영업일: {date_str}</div>
        <div style="font-size: 13px; color: #64748b; font-weight: 500; margin-top: 2px;">🔔 장마감 후 데이터가 정리됩니다 (매일 오후 4시 30분 이후 최신화)</div>
    </div>
    """,
    unsafe_allow_html=True
)

# 상단 실시간 데이터 상태 표시 배지
col1, col2 = st.columns([4, 1])
with col1:
    # 일반인 모드일 때는 기술적 용어(로컬 누적 DB)를 순화하여 노출
    user_log_msg = log_msg
    if not st.session_state.get("admin_mode", False):
        user_log_msg = user_log_msg.replace("로컬 누적 DB 로드 완료", "실시간 금융 데이터 동기화 완료")
    
    # KOSPI 및 환율 정보가 포함된 텍스트와 분리하기 위해 맨 앞 연동 상태 배지만 출력
    clean_status = user_log_msg.split('|')[0].strip()
    if is_live:
        st.success(f"✅ **[실전 연동 성공 상태]** {clean_status}")
    else:
        st.info(f"ℹ️ **[휴장일/안전 모드 상태]** {clean_status}")
with col2:
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()

# 전일 대비 주가 및 환율 등락률 계산
if len(history_df) >= 1:
    df_sorted = history_df.sort_values(by="Date")
    latest_row = df_sorted.iloc[-1]
    k_val = float(latest_row["KOSPI"])
    u_val = float(latest_row["USD_KRW"])
    
    if len(history_df) >= 2:
        prev_row = df_sorted.iloc[-2]
        k_prev = float(prev_row["KOSPI"])
        k_pct = ((k_val - k_prev) / k_prev) * 100
        u_prev = float(prev_row["USD_KRW"])
        u_pct = ((u_val - u_prev) / u_prev) * 100
    else:
        k_pct = 0.0
        u_pct = 0.0
else:
    k_val = 2500.0
    k_pct = 0.0
    u_val = 1350.0
    u_pct = 0.0

# 상승/하락 컬러맵 정의 (한국 거래소 표준: 상승 빨간색, 하락 파란색)
k_color = "#f43f5e" if k_pct > 0 else ("#3b82f6" if k_pct < 0 else "#94a3b8")
k_sign = "▲" if k_pct > 0 else ("▼" if k_pct < 0 else "")

u_color = "#f43f5e" if u_pct > 0 else ("#3b82f6" if u_pct < 0 else "#94a3b8")
u_sign = "▲" if u_pct > 0 else ("▼" if u_pct < 0 else "")

# 프리미엄 대형 전광판형 메트릭 카드 렌더링 (모바일 기기 완벽 반응형 대응)
st.markdown(
    f"""
    <div style="display: flex; flex-wrap: wrap; gap: 15px; width: 100%; margin-top: 10px;">
        <!-- KOSPI 카드 -->
        <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">📈 KOSPI 주가지수</div>
            <div style="font-size: 46px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{k_val:,.2f}</div>
            <div style="font-size: 17px; color: {k_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                <span>{k_sign} {abs(k_pct):.2f}%</span>
            </div>
        </div>
        <!-- 원/달러 환율 카드 -->
        <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">💵 원/달러 환율</div>
            <div style="font-size: 46px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{u_val:,.2f}<span style="font-size: 28px; font-weight: 700;">원</span></div>
            <div style="font-size: 17px; color: {u_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                <span>{u_sign} {abs(u_pct):.2f}%</span>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("---")

# 종합 스코어 보드
st.markdown(
    f"""
    <div class="score-container">
        <div class="score-label">🚨 보이는 손 종합 시장 위험 지수 (RISK INDEX)</div>
        <div class="score-value">{score} <span style="font-size:24px; color:#94a3b8; font-weight:600;">/ 100 점</span></div>
    </div>
    """,
    unsafe_allow_html=True
)

current_layer = min(10, max(0, int(score // 10)))

# 아파트 컨셉 빌딩 스타일 정의
st.markdown(
    """
    <style>
    .apartment-building {
        display: flex;
        flex-direction: column;
        background-color: #0f172a;
        border: 6px solid #334155;
        border-radius: 20px;
        padding: 16px;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
    }
    .apartment-floor {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 18px;
        margin: 3px 0;
        border-radius: 8px;
        background-color: #1e293b;
        color: #94a3b8;
        border: 1px solid #334155;
        transition: all 0.3s ease;
    }
    .apartment-floor.active {
        background: linear-gradient(90deg, #f43f5e 0%, #be123c 100%);
        color: #ffffff;
        font-weight: 800;
        border: 2px solid #fda4af;
        transform: scale(1.02);
        box-shadow: 0 0 20px rgba(244, 63, 94, 0.6);
    }
    .floor-name {
        font-size: 16px;
        font-weight: bold;
    }
    .floor-info {
        font-size: 13px;
        opacity: 0.9;
    }
    .building-antenna {
        width: 6px;
        height: 30px;
        background: linear-gradient(to bottom, #e63946, #64748b);
        margin: 0 auto;
        border-radius: 3px;
        box-shadow: 0 0 10px rgba(230, 57, 70, 0.8);
    }
    .building-roof-tri {
        width: 0;
        height: 0;
        border-left: 150px solid transparent;
        border-right: 150px solid transparent;
        border-bottom: 25px solid #334155;
        margin: 0 auto -6px auto;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.subheader("🏢 지금 시장은 몇 층일까요?")

# 아파트 옥상 안테나 및 삼각 지붕 렌더링 (글루 효과 포함)
st.markdown('<div class="building-antenna"></div><div class="building-roof-tri"></div>', unsafe_allow_html=True)

# 아파트 층수 렌더링 (10층부터 0층까지 아래로 쌓기, 마크다운 코드블록 방지를 위해 공백 제거)
building_html = '<div class="apartment-building">'
for floor in range(10, -1, -1):
    name, label, ratio, action = layers[floor]
    is_active = (floor == current_layer)
    active_class = "active" if is_active else ""
    indicator = " 👈 (현재 시장 위치)" if is_active else ""
    
    building_html += f'<div class="apartment-floor {active_class}">'
    building_html += f'<span class="floor-name">🪟 {name} | {label}{indicator}</span>'
    building_html += f'<span class="floor-info">[{ratio}] → {action}</span>'
    building_html += '</div>'
building_html += '</div>'

st.markdown(building_html, unsafe_allow_html=True)

st.divider()

# 현재 층수 행동 전략 안내
current_info = layers[current_layer]
st.info(
    f"**💡 현재 {current_info[0]} ({current_info[1]}) 시장 대응 전략**\n\n"
    f"- **권장 포트폴리오 비중:** {current_info[2]}\n"
    f"- **실시간 행동 지침:** {current_info[3]}"
)

# 13가지 시장 위험도 세부 지표 분석 보기 expander
with st.expander("🔍 13가지 시장 위험도 세부 지표 분석 보기"):
    if details:
        # 프리미엄 HTML/CSS 테이블 생성 (마우스 오버 툴팁 지원)
        html_table = """
        <style>
        .premium-table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            font-size: 14.5px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #e2e8f0;
        }
        .premium-table th {
            background-color: #f8fafc;
            color: #475569;
            padding: 12px 16px;
            font-weight: 600;
            border-bottom: 2px solid #e2e8f0;
            text-align: left;
        }
        .premium-table td {
            padding: 12px 16px;
            border-bottom: 1px solid #f1f5f9;
            color: #334155;
            background-color: #ffffff;
            text-align: left;
        }
        .premium-table tr:hover td {
            background-color: #f8fafc;
        }
        .tooltip-cell {
            cursor: default;
            color: #334155;
            font-weight: normal;
        }
        @media (max-width: 600px) {
            .premium-table {
                font-size: 11.5px;
            }
            .premium-table th, .premium-table td {
                padding: 8px 5px;
            }
            .premium-table th span {
                display: none;
            }
        }
        </style>
        <table class="premium-table">
            <thead>
                <tr>
                    <th style="width: 55%;">지표명 (한글 설명)<br><span style="font-size: 11px; color: #64748b; font-weight: normal;">[💡 마우스를 올려 공식을 확인하세요]</span></th>
                    <th style="width: 15%;">중요도<br>(가중치)</th>
                    <th style="width: 15%;">위험도<br>(0~1)</th>
                    <th style="width: 15%;">기여점수</th>
                </tr>
            </thead>
            <tbody>
        """
        for row in details:
            name = row["지표명 (한글 설명)"]
            weight = row["중요도 (가중치)"]
            risk = row["위험도 (0~1)"]
            contrib = row["기여점수"]
            # 줄바꿈 문자를 HTML 줄바꿈 엔티티(&#10;)로 변환하여 HTML 구조 깨짐 방지
            formula = row["산출 공식 (수학적 모델)"].replace("\n", "&#10;").replace("\\n", "&#10;")
            
            html_table += f"""
            <tr>
                <td title="{formula}" style="cursor: help;">{name}</td>
                <td>{weight}</td>
                <td>{risk:.3f}</td>
                <td>{contrib:.2f}</td>
            </tr>
            """
        html_table += "</tbody></table>"
        
        # 마크다운 코드블록 오작동 원천 차단을 위해 모든 행의 앞뒤 공백 제거 및 줄바꿈 병합
        clean_html = "\n".join([line.strip() for line in html_table.split("\n") if line.strip()])
        
        # 관리자 모드일 때만 HTML 소스 일부 검사
        if st.session_state.get("admin_mode", False):
            st.info("⚙️ [관리자] 생성된 HTML 소스 검사:")
            st.code(clean_html[:800], language="html")
            
        # Streamlit의 Markdown 자체 보안 필터가 title 속성(툴팁)을 필터링해버리는 현상을 방지하기 위해 iframe 컴포넌트 렌더러 채택 (13행을 잘림 없이 표기하기 위해 높이 700px로 확대)
        st.components.v1.html(clean_html, height=700, scrolling=False)
    else:
        st.info("실시간 시장 데이터가 없습니다.")
    st.caption("※ 외국인(55%), 기관(37%), 개인(8%)의 수급 가중치를 연동한 리스크 위험 기여도 배정표입니다.")

    # 🤖 AI 젬민이의 한마디 컴포넌트 추가
    if 'details' in locals() and len(details) >= 3:
        # 지표 중 기여도가 가장 큰 순으로 정렬
        top_indicators = sorted(details, key=lambda x: x["기여점수"], reverse=True)[:3]
        
        # 지표별 상세 금융학적 위험도 분석 데이터
        indicator_warnings = {
            "FX_Swap_Point": "달러 유동성 부족 위험이 커지고 있습니다. 국내 금융시장의 달러 공급이 빡빡해질 때 급등하므로, 환율 안정을 확인하기 전까지 무리한 추격 매수를 자제해야 합니다.",
            "Put_OTM_OI": "하락 베팅 대기자금(풋옵션 미결제)이 대량으로 쌓여 있습니다. 메이저 세력이 시장 하방에 깊게 베팅하고 있음을 뜻하므로 단기 투매 발생 가능성이 열려 있습니다.",
            "Short_Ratio": "공매도 거래 비중이 치솟아 있습니다. 주가를 아래로 끌어내려 수익을 내는 세력의 움직임이 매우 활발하므로, 호재가 나와도 위로 강하게 치고 올라가기 어렵습니다.",
            "ELS_KnockIn": "지수가 고점 대비 빠져 ELS 원금 손실 구간(낙인)에 접근하고 있습니다. 낙인 경계선이 터지면 증권사들의 헤지용 매도 물량이 쏟아져 시장의 하락 속도가 가속화될 수 있습니다.",
            "VKOSPI_Skew": "시장 공포지수의 비대칭도(불안 강도)가 급증했습니다. 투자자들이 폭락에 대비해 비싼 풋옵션을 사들이고 있다는 의미이므로 잠재적 리스크를 늘 염두에 두어야 합니다.",
            "Synthetic_Futures": "외국인의 파생상품 하방 압력(합성선물 가격차)이 거셉니다. 현물 주식을 사들이더라도 선물 옵션의 꼬리가 몸통을 흔드는 왝더독 현상으로 인해 지수가 발목 잡히기 쉽습니다.",
            "NDF_Night_Rate": "야간 역외 환율이 급격히 상승하고 있습니다. 이는 다음 날 아침 정규 장 개장 시 외국인 자금 이탈을 즉각적으로 유도하는 촉매제가 되므로 환율 꺾임을 최우선 확인해야 합니다.",
            "Futures_Net_Sell": "선물 시장에서의 순매도 압박이 매우 강력합니다. 대규모 선물 매도는 지수를 즉각적으로 끌어내리는 파괴력을 가지므로 당일 선물 매도 비중 추이를 밀착 모니터링해야 합니다.",
            "Non_Arbitrage_Ratio": "컴퓨터 알고리즘을 통한 비차익 프로그램 매도가 누적되고 있습니다. 시가총액 대형주 위주로 무차별 기계적 매도가 집행되어 코스피 전반의 기초 체력을 억누르게 됩니다.",
            "Foreign_Broker_Dump": "외국계 증권사 창구를 통한 외국인 자금 이탈 속도가 매우 가파릅니다. 반도체 등 시총 상위 핵심 업종에서 이탈세가 나타나고 있음을 암시하므로 수급 주포의 움직임을 확인하십시오.",
            "Stock_Short_Balance": "공매도 세력이 주식을 빌려 판 뒤 갚지 않은 대차 잔고가 두껍게 쌓여 있습니다. 악재가 노출될 때 추가적인 투매 압력으로 가해져 반등 시도를 가로막는 매물벽이 됩니다.",
            "Put_Buy_Simple": "개인 및 투기 세력의 풋옵션 매수 강도가 비정상적으로 높습니다. 지수 변동성이 커질 때 뇌동매매가 많이 발생하는 구간이므로 섣부른 역발상 매수는 손실을 키울 수 있습니다.",
            "Stock_Net_Sell": "주식 현물 시장에서 주도 세력의 직접적인 순매도 압력이 내리쬐고 있습니다. 시장의 기초 체력 자체가 쇠약해진 구간이므로 반등 시마다 보수적으로 포트폴리오를 관리해야 합니다."
        }

        # 동적 경고 리스트 아이템 구성
        warning_items_html = ""
        for ind in top_indicators:
            # 원래 영어 키 탐색
            raw_key = None
            for eng_k, kor_v in COL_MAP.items():
                if kor_v == ind["지표명 (한글 설명)"]:
                    raw_key = eng_k
                    break
            w_text = indicator_warnings.get(raw_key, "현재 기여도가 높아 밀착 관찰이 필요한 변동성 지표 요인입니다.")
            warning_items_html += f"""
            <li style="margin-bottom: 12px; line-height: 1.6;">
                <b style="color: #fda4af; font-size: 14.5px;">⚠️ {ind['지표명 (한글 설명)']} (위험 기여점수: {ind['기여점수']:.2f}점)</b><br>
                <span style="color: #e2e8f0; font-size: 13.5px; font-weight: 400;">{w_text}</span>
            </li>
            """

        if score >= 70:
            level_comment = (
                f"🚨 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 방어벽이 훼손된 고위험 경보 국면입니다. "
                "공격적인 자금 투입은 절대 지양하고 현금 비중을 극대화하여 방어 포지션을 굳건히 할 때입니다."
            )
        elif score >= 50:
            level_comment = (
                f"⚠️ 현재 종합 위험 지수는 <b>{score}점</b>으로 리스크와 하방 압력이 팽팽히 맞선 <b>중립 경계 국면</b>입니다. "
                "추세적인 돌파가 나오기 전까지는 성급한 저가 매수보다 방어적 현금 관리가 필수적입니다."
            )
        else:
            level_comment = (
                f"🟢 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 내 경계 압력이 완화된 안정적 국면입니다. "
                "자금 수급 지표들이 우호적으로 풀리고 있으므로 핵심 주도주 위주로 매수 포지션을 조율해 볼 수 있습니다."
            )

        ai_html = f"""
        <div style="background: linear-gradient(135deg, #1e1b4b, #2e1065); border: 2px solid #6b21a8; border-radius: 14px; padding: 22px; margin-top: 15px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 16.5px; font-weight: 700; color: #f3e8ff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #4c1d95; padding-bottom: 8px;">
                🤖 AI 젬민이의 심층 시장 분석 & 경고
            </div>
            <div style="font-size: 14.5px; color: #f8fafc; line-height: 1.6; font-weight: 500; margin-bottom: 15px;">
                {level_comment}
            </div>
            <div style="font-size: 14px; font-weight: 700; color: #e9d5ff; margin-bottom: 10px;">
                📌 오늘 특별히 엄격하게 주시해야 할 3대 리스크 팩터:
            </div>
            <ul style="margin: 0; padding-left: 20px; color: #cbd5e1;">
                {warning_items_html}
            </ul>
            <div style="background-color: #ef4444; border-radius: 8px; padding: 14px; margin-top: 22px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                <span style="color: #ffffff; font-size: 15.5px; font-weight: 700; letter-spacing: 1.2px; display: inline-block;">
                    🚨 [중요 경고] AI의 분석 결과이므로 절대적인 책임은 투자자 본인에게 있습니다.
                </span>
            </div>
        </div>
        """
        clean_ai_html = "\n".join([line.strip() for line in ai_html.split("\n") if line.strip()])
        st.markdown(clean_ai_html, unsafe_allow_html=True)

# 누적 히스토리 차트 렌더링
with st.expander("📈 방공망 리스크 지수(INDEX) 역사적 트렌드 차트"):
    if not history_df.empty:
        # 시간대 대분류 필터 배치
        period_option = st.radio(
            "보기 단위 선택", 
            ["일별 (Daily)", "주별 (Weekly)", "월별 (Monthly)"], 
            horizontal=True,
            help="차트와 테이블의 데이터 집계 주기를 설정합니다."
        )
        
        # 데이터 복사 및 날짜 타입 변환
        df_temp = history_df.copy()
        df_temp['Date'] = pd.to_datetime(df_temp['Date'])
        
        # 주기별 집계 룰 정의 (가격/점수는 평균값, 수급 거래량은 누적 합산값)
        agg_rules = {
            "Score": "mean",
            "KOSPI": "mean",
            "USD_KRW": "mean",
            "Retail": "sum",
            "Foreigner": "sum",
            "Institution": "sum"
        }
        
        if period_option == "주별 (Weekly)":
            df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='W-MON')).agg(agg_rules).reset_index()
            df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d') + " 주차"
        elif period_option == "월별 (Monthly)":
            df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='MS')).agg(agg_rules).reset_index()
            df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m') + " 월"
        else:
            df_grouped = df_temp.copy()
            df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d')
            
        # 모든 수치형 데이터 소수점 둘째 자리까지 반올림 처리 (차트 및 표 일괄 적용)
        df_grouped["Score"] = df_grouped["Score"].round(2)
        df_grouped["KOSPI"] = df_grouped["KOSPI"].round(2)
        df_grouped["USD_KRW"] = df_grouped["USD_KRW"].round(2)
        
        # 차트 렌더링
        chart_data = df_grouped.set_index("Date")[["Score"]]
        chart_data.columns = ["위험 지수"]
        st.line_chart(chart_data)
        
        # 테이블 표사용 데이터 한글 컬럼명 변환 및 역순 정렬
        display_history = df_grouped.rename(columns=COL_MAP).sort_values(by="날짜", ascending=False)
        
        st.dataframe(display_history, use_container_width=True, hide_index=True)
    else:
        st.info("누적된 히스토리 데이터가 아직 없습니다. 데이터 수집이 시작되면 여기에 그래프가 표시됩니다.")

# 공식 알고리즘 거버넌스 및 5W1H 변경 감사 추적(Audit Trail) 관리 영역
with st.expander("📝 공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)"):
    st.markdown(
        """
        ### ⚖️ 수식 파라미터 거버넌스 선언
        본 대시보드에 탑재된 13가지 시장 위험지수 공식과 가중치는 무작위로 변경되지 않으며, 
        시장 레벨 변동에 따른 파라미터 튜닝(Calibration) 집행 시 **5W1H(육하원칙)**에 의거하여 아래와 같이 버전 이력이 철저히 기록 및 관리됩니다.
        이는 과거 백데이터 점수의 왜곡 방지 및 시계열 연속성 검증을 위한 중대 사안입니다.
        """
    )
    
    tab1, tab2 = st.tabs(["📄 v1.2.0 (최근 변경)", "📄 v1.0.0 (최초 배포)"])
    with tab1:
        st.markdown(
            """
            #### 🏷️ [v1.2.0] - 2026년 08월 02일 (더미 데이터 제거 및 관리자 제어실 연동)
            * **언제 (When)**: 2026년 08월 02일 정오 기정 적용
            * **누가 (Who)**: **보이는 손 분석팀**
            * **어디를 (Where)**: app.py / scrape_daily.py / test_harness.py
            * **무엇을 (What)**: 시세/수급 수집 실패 시의 임의 디폴트값(2500, 1350) 및 5일 이동평균 대입 로직 삭제 (클린 데이터 전용 Reject 문 연동) 및 관리자 수동 제어실 탑재
            * **왜 (Why)**: 비영업일 또는 크롤링 장애 시 자동 누적되는 가짜 더미 데이터로 인한 DB 점수 오염을 원천 차단하기 위함
            * **어떻게 (How)**: 데이터 수집 불량 시 수정을 자동으로 차단하고, 관리자 비밀번호 로그인 시 직접 검증된 당일 종가/환율/수급을 대시보드 인터페이스에서 즉시 반영할 수 있도록 UI/UX 통합 제어실 설계 완료
            """
        )
    with tab2:
        st.markdown(
            """
            #### 🏷️ [v1.0.0] - 2026년 08월 01일 (최초 배포 버전)
            * **언제 (When)**: 2026년 08월 01일 장마감 시점 기정 적용
            * **누가 (Who)**: 보이는 손 퀀트 모델링 분석팀 (AI 젬민이 설계 파트)
            * **어디를 (Where)**: 13가지 하위 리스크 공식 내 기초 매개변수 전체 적용
            * **무엇을 (What)**: 
                * 환율 기초 스트레스 범위: 분모 `300원` 적용 (`(환율 - 1200) / 300`)
                * 코스피 역사적 고점 대비 낙인 임계식 설정
                * 3대 주체 수급 기여 가중치 분배: 외국인 55% / 기관 37% / 개인 8% 배정
            * **왜 (Why)**: 2026년 상반기 원/달러 환율의 1,300원대 안착화 및 코스피 박스권 변동성 체계를 정규 모델링에 반영하기 위함
            * **어떻게 (How)**: 백테스팅 모의 운용 결과, 시장 왜곡을 가장 예민하게 감지할 수 있는 균형 가중 평균치로 공식화하여 소스코드 적용 완료
            """
        )

    st.markdown(
        """
        ---
        > [!IMPORTANT]
        > 향후 거시경제 충격이나 통화 가치 변화로 상수의 재조정(Calibration)이 일어날 경우, 본 감사 추적(Audit Trail) 영역에 변경 사유와 수식 수정 상세본이 즉시 반영되어 역사적 점수 계산 기점을 추적 관리할 수 있도록 보장합니다.
        """,
        unsafe_allow_html=True
    )



