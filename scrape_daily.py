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
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)"
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
    kospi_close = 2500.0
    kospi_change = 0.0
    usd_close = 1350.0
    usd_change = 0.0
    volatility = 1.2
    dist_from_high = 0.08
    
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
                print(f"✅ 시세 수집 완료. KOSPI: {kospi_close:.2f}, 환율: {usd_close:.2f}")
        except Exception as e:
            print(f"⚠️ FinanceDataReader 수집 실패: {str(e)}")

    # 3. 네이버 금융 외국인/기관 수급 데이터 크롤링
    retail_flow = 0
    foreigner_flow = 0
    institution_flow = 0
    try:
        url = "https://finance.naver.com/sise/sise_trans_style.naver"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "lxml")
        
        table = soup.find("table", {"class": "type_2"})
        if table:
            rows = table.find_all("tr")
            for r in rows:
                cols = r.find_all("td")
                if len(cols) >= 4:
                    label = cols[0].text.strip()
                    # 순매수 금액 파싱 (단위: 억원)
                    val = int(cols[1].text.replace(",", "").replace("+", "").strip())
                    if "개인" in label:
                        retail_flow = val
                    elif "외국인" in label:
                        foreigner_flow = val
                    elif "기관" in label:
                        institution_flow = val
            print(f"✅ 네이버 수급 수집 완료. 외인: {foreigner_flow}, 기관: {institution_flow}")
    except Exception as e:
        print(f"⚠️ 네이버 수급 수집 실패: {str(e)}")

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
        "FX_Swap_Point": 12, "Put_OTM_OI": 10, "Short_Ratio": 8, "ELS_KnockIn": 7,
        "VKOSPI_Skew": 7, "Synthetic_Futures": 12, "NDF_Night_Rate": 12, "Futures_Net_Sell": 8,
        "Non_Arbitrage_Ratio": 7, "Foreign_Broker_Dump": 7, "Stock_Short_Balance": 4,
        "Put_Buy_Simple": 4, "Stock_Net_Sell": 4
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
        }
    }

    # 최종 점수 연산
    calc_score = 0.0
    metrics_dict = {}
    for item, w in weights.items():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        calc_score += w * weighted_risk
        metrics_dict[item] = weighted_risk
        
    score = round(calc_score, 1)
    print(f"📊 당일 계산된 종합 스코어: {score}")

    # 5. 새 데이터 생성 및 기존 데이터에 병합하여 CSV 저장
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

if __name__ == "__main__":
    scrape_and_update()
