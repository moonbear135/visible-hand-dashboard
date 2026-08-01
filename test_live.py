import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

def get_live_data():
    today = datetime.today()
    # 1. Fetch KOSPI and USD/KRW using FDR
    print("Fetching KOSPI data...")
    kospi_df = fdr.DataReader('^KS11')
    print("KOSPI fetched, rows:", len(kospi_df))
    
    print("Fetching USD/KRW data...")
    usd_df = fdr.DataReader('USDKRW=X')
    print("USD/KRW fetched, rows:", len(usd_df))
    
    # Get latest values
    latest_kospi = kospi_df.iloc[-1]
    prev_kospi = kospi_df.iloc[-2]
    kospi_close = latest_kospi['Close']
    kospi_change = (kospi_close - prev_kospi['Close']) / prev_kospi['Close']
    
    latest_usd = usd_df.iloc[-1]
    prev_usd = usd_df.iloc[-2]
    usd_close = latest_usd['Close']
    usd_change = (usd_close - prev_usd['Close']) / prev_usd['Close']
    
    # Calculate 10-day volatility
    kospi_returns = kospi_df['Close'].pct_change().dropna()
    volatility = kospi_returns.tail(10).std() * 100 # percentage scale
    
    # Calculate KOSPI 1-year low/high distance
    high_52w = kospi_df['Close'].tail(252).max()
    low_52w = kospi_df['Close'].tail(252).min()
    dist_from_high = (high_52w - kospi_close) / high_52w
    
    # 2. Fetch investor flows from Naver
    print("Fetching investor flows from Naver...")
    target_date_str = today.strftime("%Y%m%d")
    url = f'https://finance.naver.com/sise/investorDealTrendDay.nhn?bizdate={target_date_str}&sosok=&page=1'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    r = requests.get(url, headers=headers)
    r.encoding = 'euc-kr'
    soup = BeautifulSoup(r.text, 'html.parser')
    tb = soup.find('table', class_='type_1')
    
    foreigner_flow = 0
    institution_flow = 0
    retail_flow = 0
    trade_date = today.strftime("%Y-%m-%d")
    
    if tb:
        rows = tb.find_all('tr')
        # Find first data row (usually row 3)
        for tr in rows[2:]:
            cells = [td.text.strip().replace('\n', '').replace('\t', '') for td in tr.find_all(['td'])]
            cells = [c for c in cells if c]
            if cells and len(cells) >= 4:
                trade_date = "20" + cells[0].replace(".", "-")
                # values are in 100M KRW (억 원)
                retail_flow = int(cells[1].replace(",", ""))
                foreigner_flow = int(cells[2].replace(",", ""))
                institution_flow = int(cells[3].replace(",", ""))
                break
                
    print(f"Trade Date: {trade_date}")
    print(f"Retail: {retail_flow} 억, Foreigner: {foreigner_flow} 억, Institution: {institution_flow} 억")
    print(f"KOSPI Close: {kospi_close:.2f} ({kospi_change*100:+.2f}%)")
    print(f"USD/KRW Close: {usd_close:.2f} ({usd_change*100:+.2f}%)")
    print(f"Volatility (10d): {volatility:.3f}%")
    print(f"Dist from 52w High: {dist_from_high*100:.2f}%")

if __name__ == '__main__':
    get_live_data()
