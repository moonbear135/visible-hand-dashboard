import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import os

HISTORY_FILE = "market_history.csv"

def init_backdata():
    print("Starting backdata initialization for June and July 2026...")
    
    # 1. Fetch KOSPI and USD/KRW history from Yahoo Finance via FDR
    print("Fetching historical KOSPI & USD/KRW data...")
    try:
        kospi_df = fdr.DataReader('^KS11', '2026-06-01', '2026-07-31')
        usd_df = fdr.DataReader('USDKRW=X', '2026-06-01', '2026-07-31')
    except Exception as e:
        print("FDR fetch failed:", e)
        return

    # Map dates to KOSPI and USD data
    market_data = {}
    
    # Process KOSPI data
    for idx, row in kospi_df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        # Calc daily change
        pos = kospi_df.index.get_loc(idx)
        change = 0.0
        if pos > 0:
            prev_close = kospi_df.iloc[pos-1]['Close']
            change = (row['Close'] - prev_close) / prev_close
            
        # Calc 10-day volatility
        vol = 1.2
        if pos >= 10:
            vol = kospi_df.iloc[pos-10:pos+1]['Close'].pct_change().std() * 100
            
        high_52w = kospi_df.iloc[max(0, pos-252):pos+1]['Close'].max()
        dist_high = (high_52w - row['Close']) / high_52w
        
        market_data[date_str] = {
            "KOSPI": row['Close'],
            "KOSPI_Change": change,
            "Volatility": vol,
            "Dist_High": dist_high
        }
        
    # Process USD data
    for idx, row in usd_df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        if date_str in market_data:
            pos = usd_df.index.get_loc(idx)
            change = 0.0
            if pos > 0:
                prev_close = usd_df.iloc[pos-1]['Close']
                change = (row['Close'] - prev_close) / prev_close
            market_data[date_str]["USD_KRW"] = row['Close']
            market_data[date_str]["USD_Change"] = change

    # 2. Fetch investor flow from Naver (5 pages covers ~50 trading days)
    print("Scraping investor flows from Naver (Pages 1 to 5)...")
    naver_flows = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for page in range(1, 6):
        url = f'https://finance.naver.com/sise/investorDealTrendDay.nhn?marketCd=KOSPI&page={page}'
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
                    date_key = "20" + cells[0].replace(".", "-")
                    retail = int(cells[1].replace(",", ""))
                    foreigner = int(cells[2].replace(",", ""))
                    institution = int(cells[3].replace(",", ""))
                    naver_flows[date_key] = {
                        "Retail": retail,
                        "Foreigner": foreigner,
                        "Institution": institution
                    }
        print(f"Page {page} scraped.")

    # 3. Merge and compute risk index scores for all June and July dates
    history_records = []
    
    # Sort dates chronologically
    sorted_dates = sorted(list(market_data.keys()))
    
    for d in sorted_dates:
        m = market_data[d]
        if "USD_KRW" not in m:
            continue # Skip dates without exchange rate
            
        # Get sugeub flow or default to 0
        flow = naver_flows.get(d, {"Retail": 0, "Foreigner": 0, "Institution": 0})
        
        # Exact same formula as app.py
        fx_base = 0.5 + 0.3 * (m["USD_KRW"] - 1200) / 300
        put_base = 0.5 - 0.4 * m["KOSPI_Change"]
        short_base = 0.4 + 0.4 * (m["Volatility"] / 5.0)
        els_base = 0.1 + 0.7 * m["Dist_High"]
        skew_base = 0.4 + 0.4 * (m["Volatility"] / 5.0) - 0.2 * m["KOSPI_Change"]
        synth_base = 0.5 + 0.3 * (m["USD_KRW"] - 1300) / 200
        ndf_base = 0.4 + 0.5 * m.get("USD_Change", 0.0)
        fut_base = 0.5 - 0.3 * m["KOSPI_Change"]
        non_base = 0.5 + (0.2 if flow["Institution"] < 0 else -0.1)
        dump_base = 0.5 + (0.3 if flow["Foreigner"] < 0 else -0.2)
        bal_base = 0.5 + 0.3 * m["Dist_High"]
        put_buy_base = 0.4 - 0.3 * m["KOSPI_Change"]
        stock_net_base = 0.5

        def clip(val):
            return min(1.0, max(0.0, val))

        weights = {
            "FX_Swap_Point": 10, "Put_OTM_OI": 10, "Short_Ratio": 8, "ELS_KnockIn": 7,
            "VKOSPI_Skew": 7, "Synthetic_Futures": 12, "NDF_Night_Rate": 12, "Futures_Net_Sell": 8,
            "Non_Arbitrage_Ratio": 7, "Foreign_Broker_Dump": 7, "Stock_Short_Balance": 4,
            "Put_Buy_Simple": 4, "Stock_Net_Sell": 4
        }

        market_scores = {
            "FX_Swap_Point": {
                "Foreigner": clip(fx_base + 0.1 * m.get("USD_Change", 0.0)), "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)
            },
            "Put_OTM_OI": {
                "Foreigner": clip(put_base + (0.1 if flow["Foreigner"] < 0 else -0.1)),
                "Institution": clip(put_base + (0.05 if flow["Institution"] < 0 else -0.05)),
                "Retail": clip(put_base + (0.15 if flow["Retail"] > 0 else -0.1))
            },
            "Short_Ratio": {
                "Foreigner": clip(short_base + (0.1 if flow["Foreigner"] < 0 else -0.05)),
                "Institution": clip(short_base + (0.05 if flow["Institution"] < 0 else -0.05)),
                "Retail": clip(short_base - 0.2)
            },
            "ELS_KnockIn": {
                "Foreigner": clip(els_base), "Institution": clip(els_base + 0.1), "Retail": clip(els_base - 0.1)
            },
            "VKOSPI_Skew": {
                "Foreigner": clip(skew_base + 0.05), "Institution": clip(skew_base), "Retail": clip(skew_base - 0.2)
            },
            "Synthetic_Futures": {
                "Foreigner": clip(synth_base + (0.15 if flow["Foreigner"] < 0 else -0.1)),
                "Institution": clip(synth_base),
                "Retail": clip(synth_base + (0.05 if flow["Retail"] > 0 else -0.05))
            },
            "NDF_Night_Rate": {
                "Foreigner": clip(ndf_base + 0.1), "Institution": clip(ndf_base), "Retail": clip(ndf_base - 0.2)
            },
            "Futures_Net_Sell": {
                "Foreigner": clip(fut_base + (0.2 if flow["Foreigner"] < 0 else -0.15)),
                "Institution": clip(fut_base + (0.1 if flow["Institution"] < 0 else -0.1)),
                "Retail": clip(fut_base + (0.15 if flow["Retail"] > 0 else -0.1))
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
                "Foreigner": clip(put_buy_base + (0.05 if flow["Foreigner"] < 0 else -0.05)),
                "Institution": clip(put_buy_base),
                "Retail": clip(put_buy_base + (0.1 if flow["Retail"] > 0 else -0.1))
            },
            "Stock_Net_Sell": {
                "Foreigner": clip(stock_net_base + (0.3 if flow["Foreigner"] < 0 else -0.3)),
                "Institution": clip(stock_net_base + (0.2 if flow["Institution"] < 0 else -0.2)),
                "Retail": clip(stock_net_base + (0.3 if flow["Retail"] < 0 else -0.3))
            }
        }

        calc_score = 0.0
        investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}
        for item, w in weights.items():
            risks = market_scores[item]
            weighted_risk = (
                (risks["Foreigner"] * investor_weights["Foreigner"])
                + (risks["Institution"] * investor_weights["Institution"])
                + (risks["Retail"] * investor_weights["Retail"])
            )
            calc_score += w * weighted_risk
            
        score = round(calc_score, 1)
        
        history_records.append({
            "Date": d,
            "Score": score,
            "KOSPI": round(m["KOSPI"], 2),
            "USD_KRW": round(m["USD_KRW"], 2),
            "Retail": flow["Retail"],
            "Foreigner": flow["Foreigner"],
            "Institution": flow["Institution"]
        })

    # Save to history file
    history_df = pd.DataFrame(history_records)
    history_df.to_csv(HISTORY_FILE, index=False)
    print(f"Backdata initialized successfully. Total {len(history_df)} days saved to {HISTORY_FILE}.")

if __name__ == '__main__':
    init_backdata()
