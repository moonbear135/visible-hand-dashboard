import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('scrape_daily.py', 'r', encoding='utf-8') as f:
    code = f.read()

old_block = '''    if FDR_AVAILABLE:
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
        except Exception as e:'''

new_block = '''    if FDR_AVAILABLE:
        try:
            kospi_data = fdr.DataReader('^KS11')
            usd_data = fdr.DataReader('USDKRW=X')
            
            if not kospi_data.empty and not usd_data.empty:
                # 💡 [CRITICAL BUG FIX]: target_date 이후의 데이터는 무시하고, target_date 이전의 가장 최신 데이터를 가져옴
                target_dt = pd.to_datetime(date_key)
                kospi_data.index = kospi_data.index.tz_localize(None)
                usd_data.index = usd_data.index.tz_localize(None)
                
                valid_kospi = kospi_data[kospi_data.index <= target_dt]
                valid_usd = usd_data[usd_data.index <= target_dt]
                
                if not valid_kospi.empty and not valid_usd.empty:
                    latest_kospi = valid_kospi.iloc[-1]
                    kospi_close = float(latest_kospi['Close'])
                    # 변화율 계산
                    idx_k = valid_kospi.index.get_loc(valid_kospi.index[-1])
                    if idx_k >= 1:
                        kospi_prev = float(valid_kospi.iloc[idx_k-1]['Close'])
                        kospi_change = (kospi_close - kospi_prev) / kospi_prev
                        # 최근 10 영업일 표준편차 변동성 계산
                        returns = valid_kospi['Close'].pct_change().dropna()
                        volatility = float(returns.tail(10).std()) * 100
                    
                    # 52주 고점 계산
                    high_52w = float(kospi_data['Close'].tail(252).max()) # 전체 범위 유지
                    dist_from_high = (high_52w - kospi_close) / high_52w
                    
                    latest_usd = valid_usd.iloc[-1]
                    usd_close = float(latest_usd['Close'])
                    idx_u = valid_usd.index.get_loc(valid_usd.index[-1])
                    if idx_u >= 1:
                        usd_prev = float(valid_usd.iloc[idx_u-1]['Close'])
                        usd_change = (usd_close - usd_prev) / usd_prev
                    
                    # 5일 낙폭 모멘텀 계산
                    if len(valid_kospi) >= 6:
                        k_5d_ago = float(valid_kospi.iloc[-6]['Close'])
                        kospi_5d_return = (kospi_close - k_5d_ago) / k_5d_ago
                    else:
                        kospi_5d_return = 0.0
                    kospi_5d_base = 0.5 - 2.5 * kospi_5d_return
                    
                    print(f"✅ 야후 파이낸스(FDR) 시장 데이터 조회 성공 ({date_key}) KOSPI={kospi_close:.2f}")
                else:
                    raise ValueError(f"{date_key} 이전의 데이터를 찾을 수 없습니다.")
        except Exception as e:'''

if old_block in code:
    code = code.replace(old_block, new_block)
    with open('scrape_daily.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print('SUCCESS')
else:
    print('FAILED TO FIND BLOCK')
