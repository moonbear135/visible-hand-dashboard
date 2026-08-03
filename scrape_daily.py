import os
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# FinanceDataReader 임포트
try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False

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
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)",
    "KOSPI_5D_Return": "KOSPI 5일 낙폭 모멘텀 (지수 폭락 감지용 직접 지표)"
}

# 지표별 기간 키워드 사전 (Period Keywords Dictionary)
PERIOD_KEYWORDS = {
    "TTM": ["연간", "TTM", "최근 12개월", "최근 연간 실적"],
    "QUARTERLY": ["분기", "1Q", "2Q", "3Q", "4Q", "3개월"],
    "DAILY": ["일별", "당일", "D", "일간"]
}

def clip(val):
    return min(1.0, max(0.0, val))

def scrape_and_update():
    target_date = datetime.today()
    # 주말일 경우 직전 금요일로 조정
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)
        
    date_key = target_date.strftime("%Y-%m-%d")
    print(f"🚀 자동 수집 시작 대상 영업일: {date_key}")
    
    # 1. 기존 데이터 로드 및 중복 검사
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
            
            if date_key in history_df["Date"].values:
                print(f"ℹ️ {date_key} 데이터가 이미 존재합니다. 작업을 종료합니다.")
                return
        except Exception as e:
            print(f"❌ 기존 파일 읽기 오류: {str(e)}")
            history_df = pd.DataFrame()
    else:
        history_df = pd.DataFrame()

    # 2. 크롤링 기초 데이터 수집
    kospi_close = None
    usd_close = None
    kospi_change = 0.0
    usd_change = 0.0
    volatility = 1.2
    dist_from_high = 0.08
    kospi_5d_base = 0.5
    
    # KOSPI & USD_KRW 조회
    if FDR_AVAILABLE:
        try:
            kospi_data = fdr.DataReader('^KS11')
            usd_data = fdr.DataReader('USDKRW=X')
            
            if not kospi_data.empty and not usd_data.empty:
                latest_kospi = kospi_data.iloc[-1]
                kospi_close = float(latest_kospi['Close'])
                # 변화율 계산
                if len(kospi_data) >= 2:
                    kospi_change = (kospi_close - float(kospi_data.iloc[-2]['Close'])) / float(kospi_data.iloc[-2]['Close'])
                    # 최근 10 영업일 표준편차 변동성 계산
                    returns = kospi_data['Close'].pct_change().dropna()
                    volatility = float(returns.tail(10).std()) * 100
                
                # 52주 고점 계산
                high_52w = float(kospi_data['Close'].tail(252).max())
                dist_from_high = (high_52w - kospi_close) / high_52w
                
                latest_usd = usd_data.iloc[-1]
                usd_close = float(latest_usd['Close'])
                if len(usd_data) >= 2:
                    usd_change = (usd_close - float(usd_data.iloc[-2]['Close'])) / float(usd_data.iloc[-2]['Close'])
                
                # 5일 낙폭 모멘텀 계산
                if len(kospi_data) >= 6:
                    kospi_5d_prev = float(kospi_data.iloc[-6]['Close'])
                    kospi_5d_return = (kospi_close - kospi_5d_prev) / kospi_5d_prev
                else:
                    kospi_5d_return = 0.0
                kospi_5d_base = 0.5 - 2.5 * kospi_5d_return
                
                print(f"✅ 시세 수집 완료. KOSPI: {kospi_close:.2f}, 환율: {usd_close:.2f}")
        except Exception as e:
            print(f"⚠️ FinanceDataReader 수집 실패: {str(e)}")

    if kospi_close is None or usd_close is None:
        print("🚨 [에러] 지수 혹은 환율 데이터 연동에 실패하여 수집을 차단(Reject)하고 종료합니다.")
        return

    # 3. 네이버 금융 외국인/기관 수급 데이터 크롤링
    retail_flow = None
    foreigner_flow = None
    institution_flow = None
    sugeub_fetched = False
    
    # Naver Finance 1~5페이지 날짜 매칭 방식 적용
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
                            sugeub_fetched = True
                            found = True
                            break
                if found:
                    break
        if sugeub_fetched:
            print(f"✅ 네이버 수급 수집 완료 (매칭 성공). 외인: {foreigner_flow}, 기관: {institution_flow}")
    except Exception as e:
        print(f"⚠️ 네이버 수급 스크래핑 실패: {str(e)}")

    if not sugeub_fetched:
        print("🚨 [에러] 수급 데이터 매칭 및 스크래핑에 실패하여 수집을 차단(Reject)하고 종료합니다.")
        return

    # 4. 리스크 지표 연산
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

    # 가중 위험 지표 계산 및 합산
    investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}
    weights = {
        "FX_Swap_Point": round(12 * 100 / 102, 4), "Put_OTM_OI": round(8 * 100 / 102, 4),
        "Short_Ratio": round(6 * 100 / 102, 4), "ELS_KnockIn": round(7 * 100 / 102, 4),
        "VKOSPI_Skew": round(6 * 100 / 102, 4), "Synthetic_Futures": round(12 * 100 / 102, 4),
        "NDF_Night_Rate": round(12 * 100 / 102, 4), "Futures_Net_Sell": round(6 * 100 / 102, 4),
        "Non_Arbitrage_Ratio": round(6 * 100 / 102, 4), "Foreign_Broker_Dump": round(6 * 100 / 102, 4),
        "Stock_Short_Balance": round(3 * 100 / 102, 4), "Put_Buy_Simple": round(3 * 100 / 102, 4),
        "Stock_Net_Sell": round(3 * 100 / 102, 4), "KOSPI_5D_Return": round(12 * 100 / 102, 4)
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

    # 1. 50점대 둔감성 해결을 위한 비선형 점수 계산용 역사적 통계(평균/표준편차) 산출
    import math
    historical_stats = {}
    
    # 각 지표별 과거 통계값 산출
    for item in weights.keys():
        if not history_df.empty and item in history_df.columns and len(history_df) >= 2:
            mean_val = history_df[item].mean()
            std_val = history_df[item].std()
            if pd.isna(std_val) or std_val == 0:
                std_val = 0.15
            else:
                # Z-Score 폭주 방지를 위해 최소 표준편차 한계선(Floor) 0.02 적용
                std_val = max(0.02, std_val)
        else:
            mean_val = 0.5
            std_val = 0.15
        historical_stats[item] = {"mean": mean_val, "std": std_val}

    # 2. 개별 지표별 가중 수급 리스크(0~1) 계산 및 저장용 metrics_dict 생성
    current_weighted_risks = {}
    metrics_dict = {}
    for item in weights.keys():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        current_weighted_risks[item] = weighted_risk
        metrics_dict[item] = weighted_risk

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
        
        
    score = 50.0 + (base_score - 50.0) * multiplier
    score = round(max(0.0, min(100.0, score)), 1)
    print(f"📊 당일 계산된 종합 스코어: {score}")

    # 6. 새 데이터 생성 및 기존 데이터에 병합하여 CSV 저장
    new_data = {
        "Date": [date_key],
        "Score": [score],
        "KOSPI": [round(kospi_close, 2)],
        "USD_KRW": [round(usd_close, 2)],
        "Retail": [retail_flow],
        "Foreigner": [foreigner_flow],
        "Institution": [institution_flow]
    }
    
    for k, v in metrics_dict.items():
        new_data[k] = [round(v, 3)]
        
    new_df = pd.DataFrame(new_data)
    
    if not history_df.empty:
        history_df = pd.concat([history_df, new_df], ignore_index=True)
    else:
        history_df = new_df
        
    # 한글 컬럼명으로 변환하여 저장
    history_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
    print("💾 market_history.csv 파일 누적 갱신 성공!")

    # 7. 데이터 수집 완료 후 구글 드라이브 자동 백업 실행
    TARGET_FOLDER_ID = "1wTMFTI2txGvnzYACkbhWbJZuanxseki7"
    try:
        from utils.gdrive_helper import upload_file
        print("☁️ 구글 드라이브 자동 백업 시작...")
        upload_file(HISTORY_FILE, folder_id=TARGET_FOLDER_ID)
    except Exception as e:
        print(f"⚠️ 구글 드라이브 자동 백업 건너뜀: {e}")

if __name__ == "__main__":
    scrape_and_update()
