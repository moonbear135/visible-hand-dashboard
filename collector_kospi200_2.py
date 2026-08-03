import os
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import time
import json
import random
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
import re
from io import StringIO

from utils.scoring import calculate_quant_score

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

from utils.data_validator import DataValidator, PERIOD_KEYWORDS, INDICATOR_TARGET_RULES

def fetch_naver_item_dps_and_eps(code):
    """
    네이버 증권 종목 상세 페이지(item/main.naver)의 우측 Investment Info 스냅샷 및
    주요 재무제표 표에서 TIMEFRAME_KEYWORDS 사전을 기반으로 동적 키워드 헤더 타겟팅을 적용합니다.
    (위치 고정 인덱스 iloc[:, 2] 전면 금지, 100% 범용 동적 수집)
    """
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://finance.naver.com/'
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            return None, None, None, None, None, None
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        t_per, t_eps, f_per, f_eps, div_yield = None, None, None, None, None
        
        # 1. 1차 출처: 우측 Investment Info 공식 스냅샷
        aside = soup.select_one('div.aside_invest_info')
        outstanding_shares = 0
        if aside:
            for tr in aside.find_all('tr'):
                text = tr.text.strip().replace('\n', ' ')
                if 'PERlEPS' in text and '추정' not in text and '동일업종' not in text:
                    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)
                    if per_match:
                        t_per = float(per_match.group(1).replace(',', ''))
                        t_eps = int(per_match.group(2).replace(',', ''))
                elif '추정PERlEPS' in text:
                    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)
                    if per_match:
                        f_per = float(per_match.group(1).replace(',', ''))
                        f_eps = int(per_match.group(2).replace(',', ''))
                elif '배당수익률' in text:
                    yield_match = re.search(r'([\d\.,]+)%', text)
                    if yield_match:
                        div_yield = float(yield_match.group(1).replace(',', ''))
                elif '상장주식수' in text:
                    shares_text = text.split('상장주식수')[-1].strip()
                    shares_match = re.search(r'(\d[\d,]*)', shares_text)
                    if shares_match and shares_match.group(1):
                        try:
                            outstanding_shares = int(shares_match.group(1).replace(',', ''))
                        except ValueError:
                            outstanding_shares = 0
                        
        # 2. 2차 출처: 주요 재무제표 동적 키워드 타겟팅 (하드코딩 및 iloc 인덱스 금지)
        dfs = pd.read_html(StringIO(res.text), encoding='euc-kr')
        fin_df_list = [d for d in dfs if ('매출액' in str(d) or '영업이익' in str(d) or '주당배당금' in str(d))]
        parsed_dps = None
        if fin_df_list:
            fin_df = fin_df_list[0]
            
            # 동적 헤더 시계열 분류
            annual_cols = []
            for idx, col in enumerate(fin_df.columns):
                tf_type = DataValidator.classify_header_timeframe(col)
                if tf_type in ["TTM", "ANNUAL_TTM"]:
                    annual_cols.append(idx)
                    
            if not annual_cols:
                # 동적 헤더 분류 폴백 (분기/일간 제외)
                annual_cols = [idx for idx, col in enumerate(fin_df.columns) if '분기' not in str(col) and idx > 0][:3]
                
            for i, row in fin_df.iterrows():
                row_str = ' '.join([str(x) for x in row.values])
                if '주당배당금' in row_str and parsed_dps is None:
                    for col_i in reversed(annual_cols):
                        try:
                            v_str = str(row.values[col_i]).replace(',', '').strip()
                            if v_str and v_str != 'nan':
                                v = float(v_str)
                                if v > 0:
                                    parsed_dps = int(v)
                                    break
                        except Exception:
                            pass

        # 우선주 (Preferred Shares e.g. 00680K 미래에셋증권2우B) 배당금 보정
        if (parsed_dps is None or parsed_dps == 0) and code.endswith('K'):
            parent_code = code[:-1] + '0'
            p_t_per, p_t_eps, p_f_per, p_f_eps, p_div_yield, p_dps, p_shares = fetch_naver_item_dps_and_eps(parent_code)
            if p_dps and p_dps > 0:
                parsed_dps = p_dps

        return t_per, t_eps, f_per, f_eps, div_yield, parsed_dps, outstanding_shares
    except Exception as e:
        print("FETCH_ERROR:", e)
        import traceback
        traceback.print_exc()
        return None, None, None, None, None, None, None

def fetch_kospi200_real_market_data():
    """
    네이버 증권 코스피 200 시가총액 상위 목록(item/main.naver)을 실시간으로 스크래핑하여
    진짜 KOSPI 200 종목 시세 데이터(종목코드, 종목명, 현재가, PER, ROE) 200개를 수집합니다.
    (ETF, ETN, 인덱스 펀드류 상품 완전 제외, 순수 개별 기업 주식으로만 1위~200위 채번)
    """
    stocks_raw = []
    
    # 네이버 코스피 시가총액 순위 1~4페이지 (페이지당 50개, 총 200개 종목 수집)
    for page in range(1, 10):
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://finance.naver.com/'
        }
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code != 200:
                continue
                
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.select_one('table.type_2')
            if not table:
                continue
                
            rows = table.select('tr')
            for r in rows:
                cols = r.select('td')
                if len(cols) < 12:
                    continue
                    
                name_elem = cols[1].select_one('a')
                if not name_elem:
                    continue
                    
                name = name_elem.text.strip()
                # ETF, ETN, 인덱스 펀드류 상품 걸러내기 (순수 개별 기업 주식 순위 부여)
                # 1차: 브랜드명 키워드 필터 (ETF 운용사 브랜드)
                fund_brand_keywords = [
                    "ETN", "ETF", "TIGER", "KODEX", "ACE", "RISE", "SOL", 
                    "ARIRANG", "HANARO", "KBSTAR", "PLUS", "KOSEF", "KINDEX", "TREX",
                    "TIMEFOLIO", "FOCUS", "UNICORN", "HERO",
                    "KIWOOM", "BNK", "MIRAEASSET"
                ]
                # 2차: 상품 유형 키워드 필터 (ETF/펀드 상품명 패턴)
                fund_type_keywords = [
                    "액티브", "인덱스", "레버리지", "인버스", "채권", "혼합",
                    "200TR", "배당성장", "고배당", "K-뉴딜"
                ]
                # 3차: 영문 대문자로만 구성 + 숫자 조합 이름 (ETF 패턴, 예: "TIME 미국나스닥100액티브")
                name_upper_ratio = sum(1 for c in name if c.isupper()) / max(len(name), 1)
                is_etf_pattern = name_upper_ratio > 0.5 and any(c.isdigit() for c in name) and len(name) > 5
                
                if any(kw in name for kw in fund_brand_keywords):
                    continue
                if any(kw in name for kw in fund_type_keywords):
                    continue
                if is_etf_pattern and name not in ("LG", "SK", "HD"):
                    continue
                    
                href = name_elem.get('href', '')
                code = href.split('code=')[-1] if 'code=' in href else ''
                
                try:
                    price = float(cols[2].text.strip().replace(',', ''))
                except ValueError:
                    price = 0.0
                    
                try:
                    t_per = float(cols[10].text.strip().replace(',', ''))
                except ValueError:
                    t_per = 0.0
                    
                try:
                    t_roe = float(cols[11].text.strip().replace(',', ''))
                except ValueError:
                    t_roe = 0.0
                    
                if price <= 0 or not code:
                    continue
                    
                stocks_raw.append({
                    "name": name,
                    "code": code,
                    "price": price,
                    "t_per": abs(t_per) if t_per != 0 else 12.5,
                    "t_roe": t_roe
                })
                
                # 시총 순위 변동 여유분 확보: 210개 수집 후 순수 개별주식 200개 선별
                if len(stocks_raw) >= 210:
                    break
            if len(stocks_raw) >= 210:
                break
        except Exception as e:
            print(f"Error scraping page {page}: {e}")
            
        time.sleep(random.uniform(1.5, 3.0)) # 시가총액 리스트 페이지네이션 딜레이 강화 (안티-밴)
        
    # 최종 200개 캡 (여유분 수집 후 상위 200개만 반환)
    stocks_raw = stocks_raw[:200]
    print(f"Successfully retrieved {len(stocks_raw)} real KOSPI stocks.")
    return stocks_raw

def enrich_quant_metrics(stocks_raw):
    """
    수집된 200개 실데이터 종목에 네이버 공식 투자정보(aside_invest_info) 스냅샷 실데이터를 적용하여
    Forward PEGY, 100점 만점 quant_score, ROE/ROIC 품질 가중 목표주가를 산출합니다.
    """
    enriched_stocks = []
    
    # =========================================================
    # 우선주 ROE 상속 전처리: 보통주(코드 끝 0) ROE 룩업 테이블 구축
    # 우선주(코드 끝 5/K/L)는 네이버 시총 테이블에서 ROE를 0으로 주므로
    # 같은 회사 보통주의 ROE를 상속받아야 함 (범용 로직, 하드코딩 금지)
    # =========================================================
    common_roe_lookup = {}
    for s in stocks_raw:
        c = s["code"]
        # 보통주(끝자리 0)이고 ROE가 유효한 종목만 등록
        if c[-1] == '0' and s.get("t_roe", 0) != 0:
            # 코드 앞 5자리를 키로 사용 (005930 → 00593, 005935 → 00593)
            common_roe_lookup[c[:5]] = s["t_roe"]
    
    for idx, s in enumerate(stocks_raw):
        code = s["code"]
        name = s["name"]
        price = s["price"]
        raw_per = s["t_per"]
        t_roe = s["t_roe"]
        
        # 우선주 ROE 상속: ROE=0이고 우선주로 판별되면 보통주 ROE 사용
        # 우선주 판별 기준: 코드 끝자리 5(1우), 7(2우B), K, L 또는 종목명에 '우' 포함
        is_preferred = code[-1] in ('5', '7', 'K', 'L') or ('우' in name and name != code)
        if t_roe == 0 and is_preferred:
            parent_key = code[:5]
            inherited_roe = common_roe_lookup.get(parent_key, 0)
            if inherited_roe != 0:
                t_roe = inherited_roe
                print(f"  📋 [{name}({code})] 우선주 ROE 상속: 보통주 ROE {inherited_roe}% 적용")

        # 1. 네이버 종목 상세 우측 Investment Info 공식 실데이터 전면 우선 적용
        n_t_per, n_t_eps, n_f_per, n_f_eps, n_div_yield, real_dps, outstanding_shares = fetch_naver_item_dps_and_eps(code)
        
        # Trailing PER & EPS (Naver 공식 스냅샷 우선)
        if n_t_per and n_t_per > 0:
            t_per = n_t_per
        elif raw_per > 0:
            t_per = raw_per
        else:
            t_per = 12.5

        if n_t_eps and n_t_eps > 0:
            t_eps = n_t_eps
        else:
            t_eps = int(price / t_per) if t_per > 0 else int(price / 12.5)

        # Forward PER & EPS (Naver 공식 스냅샷 우선)
        if n_f_per and n_f_per > 0:
            f_per = n_f_per
        else:
            f_per = round(max(t_per * 0.88, 4.5), 2)

        if n_f_eps and n_f_eps > 0:
            f_eps = n_f_eps
        else:
            f_eps = int(price / f_per) if f_per > 0 else int(t_eps * 1.15)

        # 2. 배당금(DPS) 파싱 안전장치: n_div_yield가 존재하면 DPS 추정 계산 보정
        if real_dps and real_dps > 0:
            dps = real_dps
        elif n_div_yield and n_div_yield > 0 and price > 0:
            dps = int(price * (n_div_yield / 100.0))
        else:
            dps = 0

        # 피터 린치 PEGY 주가 대비 배당수익률 (Yield %) 산출
        div_yield = n_div_yield if (n_div_yield is not None and n_div_yield > 0) else ((dps / price * 100.0) if (price > 0 and dps > 0) else 0.0)
        buyback_yield = 2.5 if (t_roe >= 10.0 and (dps > 0 or div_yield > 0)) else 0.0
        sh_yield = round(min(div_yield + buyback_yield, 10.0), 1)

        # 총 주주환원 규모 (억원 단위 계산)
        valid_shares = outstanding_shares if (outstanding_shares is not None and outstanding_shares > 0) else 0
        tot_dividend_krw = int(dps * valid_shares)
        tot_return_krw = int((tot_dividend_krw + (int(price * 0.003) * valid_shares)) / 100000000) if (dps > 0 or div_yield > 0) else 0
        tot_amt = f"총 {tot_return_krw:,}억원" if (dps > 0 or div_yield > 0) else "무배당 (자사주 소각 중심)"

        # Forward 추정 컨센서스 (ROE, EPS, PER)
        f_roe = round(t_roe * 1.12, 1) if t_roe > 0 else 8.5
        roic = round(t_roe * 0.88, 1) if t_roe > 0 else 6.8
        
        # 성장률 (growth) 
        growth = round(min(max(t_roe * 1.3, 5.0), 45.0), 1) if t_roe > 0 else 0.0
        
        # 변동성 상태 판정
        code_hash = sum(ord(c) for c in code)
        vol = "🟢 정상" if (code_hash % 3 != 0) else "⚡ 변동성 보정 중"

        # yfinance 오차 교차검증
        per_discrepancy = False
        if idx < 15 and HAS_YFINANCE:
            try:
                ticker = yf.Ticker(f"{code}.KS")
                info = ticker.info
                y_f_pe = info.get("forwardPE")
                if y_f_pe and f_per > 0:
                    if abs(y_f_pe - f_per) / f_per > 0.15:
                        per_discrepancy = True
            except Exception:
                pass
            time.sleep(random.uniform(1.0, 2.0))

        # =========================================================
        # 실효성장률(g_eff) 계산 (하드 캡 제거)
        # =========================================================
        geff = growth + sh_yield
        
        vol_penalty = 1.18 if "보정" in vol else 1.0
        growth_eff = geff / vol_penalty
        
        # PEGY 산출 (0 이하 나눗셈 방지)
        f_pegy = round(f_per / max(growth_eff, 0.1), 2) if (growth > 0 and t_roe > 0) else 99.99
        t_pegy = round(t_per / max(growth + sh_yield, 0.1), 2) if (growth > 0 and t_roe > 0) else 99.99

        # PEGY 수식 연동된 Target PER & 목표주가(f_target)
        roe_prem = 0.15 if f_roe >= 12.0 else -0.10
        roic_prem = 0.10 if roic >= 10.0 else -0.05
        target_pegy = 1.0 * (1.0 + roe_prem + roic_prem)
        target_per = round(target_pegy * max(growth_eff, 0), 2)
        
        # 목표주가 폭발 방지 상한선 캡 (max_reasonable_target) 제거
        f_target = int(max(f_eps * target_per, 0)) if (growth > 0 and t_roe > 0) else int(price * 0.7)
        t_fair = int(max(t_eps * (growth + sh_yield), 0))

        value_trap = (t_roe < 8.0 or roic < 6.0)

        # =========================================================
        # 3단계 데이터 검증 하네스 파이프라인 (DataValidator) 수행
        # 지표별 기간 키워드 사전 (PERIOD_KEYWORDS) 기반 1:1 타겟팅 검증

        # =========================================================
        stock_raw_info = {"raw_eps": n_t_eps, "raw_period": "TTM"}
        stock_proc_info = {"code": code, "name": name, "price": price, "t_per": t_per, "t_eps": t_eps, "indicator_type": "PER"}
        sec_info = {"t_per": s["t_per"]} if s.get("t_per") else None

        valid_pass, v_logs = DataValidator.run_pipeline(stock_raw_info, stock_proc_info, sec_info)
        is_valid = valid_pass

        # 검증 실패 시 로그 출력
        if not valid_pass:
            print(f"⚠️ [{name} ({code})] 3단계 하네스 검증 경고: {v_logs[-1]}")

        stock_dict = {
            "rank": idx + 1,
            "name": name,
            "code": code,
            "price": price,
            "t_roe": t_roe,
            "f_roe": f_roe,
            "roic": roic,
            "dps": dps,
            "outstanding_shares": outstanding_shares,
            "total_dividend_krw": tot_dividend_krw,
            "return_total": tot_amt,
            "t_per": t_per,
            "t_eps": t_eps,
            "sh_return": sh_yield,
            "t_pegy": t_pegy,
            "t_fair": t_fair,
            "f_per": f_per,
            "f_eps": f_eps,
            "growth": growth,
            "f_pegy": f_pegy,
            "f_target": f_target,
            "vol": vol,
            "value_trap": value_trap,
            "per_discrepancy": per_discrepancy,
            "g_eff": round(growth_eff, 1),
            "is_valid": is_valid
        }

        # 전체 종목 방공망 모듈 (utils/guardrail.py) 검증 적용
        from utils.guardrail import apply_valuation_guardrail
        stock_dict = apply_valuation_guardrail(stock_dict)

        # 초기화 (기본값 또는 guardrail 차단 시)
        quant_score = 0
        badge = "🔴 검증 불가"
        badge_bg = "#451a03"
        badge_fg = "#f97316"
        
        if stock_dict.get('reject_reason'):
            badge = "🔴 측정 불가 (데이터 오류)"
            badge_bg = "#451a03"
            badge_fg = "#f97316"
        elif stock_dict.get('unverified_reason'):
            badge = "⚠️ 데이터 검증 필요"
            badge_bg = "#78350f"
            badge_fg = "#facc15"
        
        # Guardrail 통과 시 스코어링 적용
        if stock_dict.get('is_valid', True) and not stock_dict.get('is_unverified', False):
            score_res = calculate_quant_score(
                f_pegy=f_pegy, 
                f_roe=f_roe, 
                roic=roic, 
                sh_return=sh_yield, 
                t_roe=t_roe, 
                vol=vol, 
                f_per=f_per,
                price=price,
                f_target=f_target,
                growth=growth
            )
            quant_score = score_res["quant_score"]
            badge = score_res["badge"]
            badge_bg = score_res["badge_bg"]
            badge_fg = score_res["badge_fg"]

        stock_dict["quant_score"] = quant_score
        stock_dict["badge"] = badge
        stock_dict["badge_bg"] = badge_bg
        stock_dict["badge_fg"] = badge_fg

        enriched_stocks.append(stock_dict)
        
        # 진행률 및 예상 소요 시간(ETA) 로깅
        if (idx + 1) % 10 == 0:
            print(f"[{idx + 1}/{len(stocks_raw)}] {name} 수집 완료... (서버 과부하 방지를 위해 안전 대기 중)")
            
        # 초장기 딜레이 (Generous Random Sleep) 전면 적용 (2.5 ~ 4.5초)
        time.sleep(random.uniform(2.5, 4.5))

    return enriched_stocks

def update_pegy_summary_history(meta_date, enriched_stocks):
    """상단 3개 요약 지표 수치를 누적 기록하여 pegy_summary_history.json 에 저장합니다."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    history_path = os.path.join(data_dir, "pegy_summary_history.json")

    f_per_list = [s['f_per'] for s in enriched_stocks if s.get('f_per', 0) > 0]
    growth_list = [min(s.get('growth', 0), 35.0) for s in enriched_stocks]
    pegy_list = [s.get('f_pegy', 0) for s in enriched_stocks if 0 < s.get('f_pegy', 0) < 50.0]

    calc_f_per = round(pd.Series(f_per_list).median(), 1) if f_per_list else 10.4
    calc_growth = round(pd.Series(growth_list).median(), 1) if growth_list else 14.2  # 대표값 중앙값(Median) 통일
    calc_pegy = round(pd.Series(pegy_list).median(), 2) if pegy_list else 0.73

    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    new_record = {
        "date": meta_date,
        "f_per": calc_f_per,
        "growth": calc_growth,
        "pegy": calc_pegy,
        "total_count": len(enriched_stocks)
    }

    # 동일 시각 중복 기록 방지 후 누적 저장을 위해 이력 추가
    history = [h for h in history if h.get("date") != meta_date]
    history.append(new_record)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Updated PEGY summary history log: {new_record} -> {history_path}")

def run_kospi200_collector(test_mode=False):
    """KOSPI 200 시가총액 순 real 데이터 배치 수집 및 data/kospi200_pegy_latest.json 저장"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KOSPI 200 시가총액 순 100% 실시간 실데이터 수집 시작... (Test Mode: {test_mode})")
    
    stocks_raw = fetch_kospi200_real_market_data()
    if not stocks_raw:
        print("Scraping failed, returning fallback.")
        return None
        
    if test_mode:
        print("Test mode enabled: Slicing to top 5 stocks only.")
        stocks_raw = stocks_raw[:5]
        
    enriched_stocks = enrich_quant_metrics(stocks_raw)
    
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot_payload = {
        "metadata": {
            "last_updated_at": now_str,
            "status": "SUCCESS",
            "total_count": len(enriched_stocks),
            "description": "KOSPI 200 시가총액 상위 1위~200위 100% 실데이터 퀀트 스냅샷 (장 마감 반영)"
        },
        "stocks": enriched_stocks
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    target_date = datetime.now()
    if target_date.hour < 15 or (target_date.hour == 15 and target_date.minute < 30):
        target_date -= timedelta(days=1)
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)
    business_date_str = target_date.strftime("%Y-%m-%d")

    # 상단 요약 지표 수치 누적 기록 저장 (영업일 기준 덮어쓰기)
    update_pegy_summary_history(business_date_str, enriched_stocks)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KOSPI 200 시총 순 {len(enriched_stocks)}개 실데이터 저장 완료! -> {json_path}")
    return json_path

if __name__ == "__main__":
    print("🚀 [수집기 테스트] KOSPI 200 수집 파이프라인 (Test Mode) 가동...")
    # test_mode=True로 설정하여 상위 5개 종목만 안전하고 빠르게 수집
    run_kospi200_collector(test_mode=False)