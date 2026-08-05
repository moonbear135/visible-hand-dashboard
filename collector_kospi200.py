import os
import sys
import time
import json
import random
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pandas as pd
import re

from utils.scoring import calculate_quant_score

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

try:
    import FinanceDataReader as fdr
    HAS_FDR = True
except ImportError:
    HAS_FDR = False

from utils.data_validator import DataValidator, PERIOD_KEYWORDS, INDICATOR_TARGET_RULES

# =============================================================================
# 데이터 무결성 상수 (ENGINEERING_SPEC §0-1 "하드코딩 및 더미 데이터 금지" 준수)
# - 아래 값들은 "실데이터가 맞는지 판별하기 위한 검증 임계치"이며,
#   실데이터를 대체하는 기본값(더미)이 아닙니다.
# =============================================================================
MIN_OUTSTANDING_SHARES = 1_000_000   # 상장주식수 파싱 결과 sanity range check 하한
VOL_WINDOW = 20                      # 변동성 산출 기간(영업일)
VOL_THRESHOLD_PCT = 2.0              # 일간수익률 표준편차(%) 기준 '변동성 확대' 판정선
VOL_PENALTY = 1.18                   # 변동성 확대 시 실효성장률 벌점 배수


def fetch_recent_volatility(code):
    """
    최근 VOL_WINDOW 영업일 일간수익률 표준편차(%)를 '실제 주가 시계열'로 산출합니다.
    조회/계산이 불가능하면 절대 임의값을 만들지 않고 None 을 반환합니다.
    (구 버전의 `code_hash % 3` 가짜 변동성 판정 로직을 완전히 대체)
    """
    if not HAS_FDR:
        return None
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=120)
        df = fdr.DataReader(code, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'))
        if df is None or df.empty or 'Close' not in df.columns:
            return None
        returns = df['Close'].pct_change().dropna()
        if len(returns) < VOL_WINDOW:
            return None
        return round(float(returns.tail(VOL_WINDOW).std()) * 100.0, 2)
    except Exception as e:
        print(f"  [변동성 조회 실패] {code}: {e}")
        return None


def _load_outstanding_shares_lookup():
    """
    FinanceDataReader의 KRX 상장종목 리스트(구조화 데이터)에서 상장주식수를 조회합니다.
    네이버 종목 상세페이지의 자유 텍스트를 정규식으로 파싱하는 기존 방식은 페이지 문구/구조가
    조금만 바뀌어도 다른 필드(예: 외국인소진율 %)를 상장주식수로 오인할 위험이 있어,
    구조화된 표(컬럼 이름이 명확한 DataFrame)를 1차 출처로 우선 사용합니다.
    조회에 실패하면 빈 dict 를 반환하며, 이 경우 기존 네이버 파싱 값(자체 sanity check 포함)만 사용합니다.
    """
    if not HAS_FDR:
        return {}
    try:
        df = fdr.StockListing('KRX')
        shares_col = None
        for candidate_col in ('Stocks', 'Shares', 'ListedStockCnt', 'ListedShares'):
            if candidate_col in df.columns:
                shares_col = candidate_col
                break
        if shares_col is None or 'Code' not in df.columns:
            print(f"⚠️ [상장주식수 구조화 조회] fdr.StockListing('KRX') 컬럼 구조가 예상과 다릅니다: {list(df.columns)}")
            return {}
        lookup = {}
        for _, row in df[['Code', shares_col]].dropna().iterrows():
            try:
                lookup[str(row['Code'])] = int(row[shares_col])
            except (ValueError, TypeError):
                continue
        print(f"  [상장주식수 구조화 조회 성공] {len(lookup)}개 종목 매핑 완료 (컬럼={shares_col})")
        return lookup
    except Exception as e:
        print(f"⚠️ [상장주식수 구조화 조회 실패] {e}")
        return {}


def _empty_item_info(error_msg):
    """종목 상세 수집 실패 시 반환 구조 (모든 수치는 None = '데이터 없음')"""
    return {
        "t_per": None, "t_eps": None, "f_per": None, "f_eps": None,
        "div_yield": None, "dps": None, "outstanding_shares": None,
        "t_pbr": None, "ev_ebitda": None, "raw_period": None,
        "errors": [error_msg]
    }


def fetch_naver_item_dps_and_eps(code):
    """
    네이버 증권 종목 상세 페이지(item/main.naver)의 우측 Investment Info 스냅샷 및
    주요 재무제표 표에서 TIMEFRAME_KEYWORDS 사전을 기반으로 동적 키워드 헤더 타겟팅을 적용합니다.
    (위치 고정 인덱스 iloc[:, 2] 전면 금지, 100% 범용 동적 수집)

    반환: dict — 파싱하지 못한 항목은 반드시 None 이며, 실패 사유는 errors 리스트에 누적됩니다.
    """
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    max_retries = 3
    base_delay = 1.0
    res = None
    
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                break
            else:
                time.sleep(base_delay * (2 ** attempt) + random.uniform(0.1, 0.5))
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                print(f"Error fetching {code}: {e}")
                return _empty_item_info(f"종목 상세 페이지 요청 실패: {e}")
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0.1, 0.5))

    if not res or res.status_code != 200:
        return _empty_item_info(f"종목 상세 페이지 응답 코드 이상: {getattr(res, 'status_code', 'NO_RESPONSE')}")

    try:
        soup = BeautifulSoup(res.text, 'html.parser')

        t_per, t_eps, f_per, f_eps, div_yield = None, None, None, None, None
        t_pbr, ev_ebitda = None, None
        raw_period = None          # 실제 파싱한 헤더에서 판정한 수집 기간 (검증 1단계 입력)
        errors = []

        # 1. 1차 출처: 우측 Investment Info 공식 스냅샷
        aside = soup.select_one('div.aside_invest_info')
        outstanding_shares = None
        if aside:
            for tr in aside.find_all('tr'):
                text = tr.text.strip().replace('\n', ' ')
                if 'PERlEPS' in text and '추정' not in text and '동일업종' not in text:
                    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)
                    if per_match:
                        t_per = float(per_match.group(1).replace(',', ''))
                        t_eps = int(per_match.group(2).replace(',', ''))
                        # 실제 헤더 라벨에서 기간을 판정 (하드코딩 "TTM" 전달 금지)
                        label_match = re.match(r'^(.*?)\s*[\d\.,]+배', text)
                        raw_label = label_match.group(1).strip() if label_match else text
                        if re.search(r'\(\d{4}\.\d{2}\)', raw_label):
                            # 네이버의 'PER|EPS(YYYY.MM)' 는 해당 분기까지의 최근 4분기 합산(TTM) 지표
                            raw_period = "TTM"
                        else:
                            raw_period = DataValidator.classify_header_timeframe(raw_label)
                elif '추정PERlEPS' in text:
                    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)
                    if per_match:
                        f_per = float(per_match.group(1).replace(',', ''))
                        f_eps = int(per_match.group(2).replace(',', ''))
                elif 'PBRlBPS' in text:
                    pbr_match = re.search(r'([\d\.,]+)배', text)
                    if pbr_match:
                        t_pbr = pbr_match.group(1).replace(',', '')
                elif '배당수익률' in text:
                    yield_match = re.search(r'([\d\.,]+)%', text)
                    if yield_match:
                        div_yield = float(yield_match.group(1).replace(',', ''))
                elif '상장주식수' in text:
                    # 파싱 sanity range check: 상장주식수는 최소 100만 주 이상이어야 함.
                    # (구 버전은 첫 번째 숫자를 그대로 집어 외국인소진율 등 다른 필드를
                    #  상장주식수로 오인했고, 200종목 중 197종목이 조용히 오염되었음)
                    shares_text = text.split('상장주식수')[-1].strip()
                    candidates = []
                    for raw_num in re.findall(r'\d[\d,]*', shares_text):
                        try:
                            candidates.append(int(raw_num.replace(',', '')))
                        except ValueError:
                            continue
                    plausible = [c for c in candidates if c >= MIN_OUTSTANDING_SHARES]
                    if plausible:
                        outstanding_shares = max(plausible)
                    else:
                        outstanding_shares = None
                        errors.append(f"상장주식수 파싱 실패 (후보값={candidates})")

        # 2. 2차 출처: 주요 재무제표 동적 키워드 타겟팅 (하드코딩 및 iloc 인덱스 금지)
        dfs = pd.read_html(res.text, encoding='euc-kr')
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
                # SPEC §2-1 위치 인덱스(iloc) 폴백 절대 금지.
                # 연간 컬럼을 키워드로 특정하지 못하면 분기 데이터를 연간으로 오인할 수 있으므로
                # 추정하지 않고 DPS 미수집(None)으로 남깁니다.
                errors.append("재무제표 연간 컬럼 헤더 분류 실패 → DPS 수집 생략")

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
                        except (ValueError, TypeError, IndexError) as e:
                            errors.append(f"DPS 셀 파싱 실패(col={col_i}): {e}")

        # EV/EBITDA (Naver WiseReport) 추가 스크래핑
        time.sleep(1.5) # 서버 부하 방지
        try:
            res_ev = requests.get(f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}", timeout=10)
            if res_ev.status_code == 200:
                ev_dfs = pd.read_html(res_ev.text)
                for df in ev_dfs:
                    if 'EV/EBITDA' in str(df):
                        for row_idx in range(len(df)):
                            if 'EV/EBITDA' in str(df.iloc[row_idx, 0]):
                                val = str(df.iloc[row_idx, 1])
                                if pd.notna(df.iloc[row_idx, 1]) and val != 'nan':
                                    ev_ebitda = val
                                break
        except Exception as e:
            print("EV_EBITDA FETCH_ERROR:", e)
            errors.append(f"EV/EBITDA 수집 실패: {e}")

        # 우선주 (Preferred Shares e.g. 00680K 미래에셋증권2우B) 배당금 보정
        if (parsed_dps is None or parsed_dps == 0) and code.endswith('K'):
            parent_code = code[:-1] + '0'
            parent_info = fetch_naver_item_dps_and_eps(parent_code)
            p_dps = parent_info.get("dps")
            if p_dps and p_dps > 0:
                parsed_dps = p_dps

        return {
            "t_per": t_per, "t_eps": t_eps, "f_per": f_per, "f_eps": f_eps,
            "div_yield": div_yield, "dps": parsed_dps,
            "outstanding_shares": outstanding_shares,
            "t_pbr": t_pbr, "ev_ebitda": ev_ebitda,
            "raw_period": raw_period, "errors": errors
        }
    except Exception as e:
        print("FETCH_ERROR:", e)
        import traceback
        traceback.print_exc()
        return _empty_item_info(f"종목 상세 파싱 예외: {e}")

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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
                    
                # 시총 리스트의 PER/ROE 는 파싱 실패 시 임의 대체값을 넣지 않고 None 으로 둡니다.
                try:
                    t_per = float(cols[10].text.strip().replace(',', ''))
                except ValueError:
                    t_per = None

                try:
                    t_roe = float(cols[11].text.strip().replace(',', ''))
                except ValueError:
                    t_roe = None

                if price <= 0 or not code:
                    continue

                stocks_raw.append({
                    "name": name,
                    "code": code,
                    "price": price,
                    "t_per": abs(t_per) if (t_per is not None and t_per != 0) else None,
                    "t_roe": t_roe
                })
                
                # 시총 순위 변동 여유분 확보: 210개 수집 후 순수 개별주식 200개 선별
                if len(stocks_raw) >= 210:
                    break
            if len(stocks_raw) >= 210:
                break
        except Exception as e:
            print(f"Error scraping page {page}: {e}")
            
        time.sleep(random.uniform(2.0, 3.0)) # 매너 있는 크롤링을 위한 여유 있는 딜레이 (Polite Scraping)
        
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

    # 상장주식수 1차 출처: FinanceDataReader 구조화 데이터 (한 번만 조회, 종목별 재조회 안 함)
    outstanding_shares_lookup = _load_outstanding_shares_lookup()

    # =========================================================
    # 우선주 ROE 상속 전처리: 보통주(코드 끝 0) ROE 룩업 테이블 구축
    # 우선주(코드 끝 5/K/L)는 네이버 시총 테이블에서 ROE를 0으로 주므로
    # 같은 회사 보통주의 ROE를 상속받아야 함 (범용 로직, 하드코딩 금지)
    # =========================================================
    common_roe_lookup = {}
    for s in stocks_raw:
        c = s["code"]
        # 보통주(끝자리 0)이고 ROE가 유효한 종목만 등록
        if c[-1] == '0' and s.get("t_roe") not in (None, 0):
            # 코드 앞 5자리를 키로 사용 (005930 → 00593, 005935 → 00593)
            common_roe_lookup[c[:5]] = s["t_roe"]

    for idx, s in enumerate(stocks_raw):
        code = s["code"]
        name = s["name"]
        price = s["price"]
        raw_per = s["t_per"]
        t_roe = s["t_roe"]
        data_issues = []   # 이 종목에서 수집하지 못한 항목 (JSON/UI에 그대로 노출)

        # 우선주 ROE 상속: ROE=0이고 우선주로 판별되면 보통주 ROE 사용
        # 우선주 판별 기준: 코드 끝자리 5(1우), 7(2우B), K, L 또는 종목명에 '우' 포함
        is_preferred = code[-1] in ('5', '7', 'K', 'L') or ('우' in name and name != code)
        if (t_roe is None or t_roe == 0) and is_preferred:
            parent_key = code[:5]
            inherited_roe = common_roe_lookup.get(parent_key)
            if inherited_roe:
                t_roe = inherited_roe
                print(f"  [우선주 ROE 상속] {name}({code}): 보통주 ROE {inherited_roe}% 적용")

        # 1. 네이버 종목 상세 우측 Investment Info 공식 실데이터 전면 우선 적용
        item = fetch_naver_item_dps_and_eps(code)
        n_t_per = item["t_per"]
        n_t_eps = item["t_eps"]
        n_f_per = item["f_per"]
        n_f_eps = item["f_eps"]
        n_div_yield = item["div_yield"]
        real_dps = item["dps"]
        outstanding_shares = item["outstanding_shares"]

        # 상장주식수 최종 판정: FDR 구조화 데이터(1차, 컬럼 명확) 우선,
        # 네이버 텍스트 파싱 값(2차, 이미 자체 sanity check 통과)은 백업으로만 사용.
        # 두 출처 모두 실패/미달이면 지어내지 않고 None 처리 (guardrail 이 최종 차단).
        fdr_shares = outstanding_shares_lookup.get(code)
        if fdr_shares and fdr_shares >= MIN_OUTSTANDING_SHARES:
            outstanding_shares = fdr_shares
        elif outstanding_shares and outstanding_shares >= MIN_OUTSTANDING_SHARES:
            pass  # 네이버 파싱 값 유지 (fetch_naver_item_dps_and_eps 에서 이미 검증됨)
        else:
            if outstanding_shares:
                data_issues.append(f"상장주식수 파싱 오류 의심 (네이버={outstanding_shares}, FDR={fdr_shares})")
            outstanding_shares = None

        t_pbr = item["t_pbr"]
        ev_ebitda = item["ev_ebitda"]
        raw_period = item["raw_period"]
        data_issues.extend(item.get("errors", []))

        # =========================================================
        # Trailing PER / EPS
        # 실측값이 없으면 절대 임의값(12.5 등)이나 역산값(주가/PER)을 만들지 않습니다.
        # None 으로 두면 아래 검증 단계에서 걸러져 '측정 불가' 카드로 노출됩니다.
        # =========================================================
        if n_t_per and n_t_per > 0:
            t_per = n_t_per
        elif raw_per and raw_per > 0:
            t_per = raw_per
        else:
            t_per = None
            data_issues.append("Trailing PER 수집 실패")

        t_eps = n_t_eps if (n_t_eps and n_t_eps > 0) else None
        if t_eps is None:
            data_issues.append("Trailing EPS 수집 실패")

        # Forward PER / EPS — 네이버 '추정PER|EPS' (실제 컨센서스) 만 사용
        f_per = n_f_per if (n_f_per and n_f_per > 0) else None
        f_eps = n_f_eps if (n_f_eps and n_f_eps > 0) else None
        if f_per is None or f_eps is None:
            data_issues.append("Forward 컨센서스(추정 PER/EPS) 미제공")

        # 2. 배당금(DPS): 공시 실측값이 없고 배당수익률만 있으면 그 값으로 환산 (출처 기록)
        dps_source = None
        if real_dps and real_dps > 0:
            dps = real_dps
            dps_source = "naver_financial_statement"
        elif n_div_yield and n_div_yield > 0 and price > 0:
            dps = int(price * (n_div_yield / 100.0))
            dps_source = "derived_from_div_yield"
        else:
            dps = 0
            dps_source = "no_dividend_or_not_collected"

        # 배당수익률 (%) — 실측 우선
        div_yield = n_div_yield if (n_div_yield is not None and n_div_yield > 0) else ((dps / price * 100.0) if (price > 0 and dps > 0) else 0.0)

        # =========================================================
        # 주주환원율: 자사주 매입 공시를 수집하지 않으므로 '배당수익률'만 사용합니다.
        # (구 버전은 ROE 10% 이상이면 자사주 2.5%를 임의로 가산했고, 주가의 0.3%를
        #  자사주 매입액으로 가정해 총액을 부풀렸습니다 → 전부 제거)
        # =========================================================
        sh_yield = round(div_yield, 2)
        sh_return_basis = "배당수익률만 반영 (자사주 매입 공시 미수집)"

        # 총 배당 규모: 상장주식수가 검증을 통과했을 때만 산출. 실패 시 None + '데이터 없음'
        if outstanding_shares and outstanding_shares >= MIN_OUTSTANDING_SHARES and dps > 0:
            tot_dividend_krw = int(dps * outstanding_shares)
            tot_return_krw = int(tot_dividend_krw / 100000000)
            tot_amt = f"총 {tot_return_krw:,}억원 (배당 기준)"
        elif dps <= 0 and div_yield <= 0:
            tot_dividend_krw = 0
            tot_amt = "무배당 (배당 공시 없음)"
        else:
            tot_dividend_krw = None
            tot_amt = "데이터 없음 (상장주식수 미확보)"

        # =========================================================
        # Forward ROE / ROIC
        # 별도 컨센서스 출처를 수집하지 않으므로 지어내지 않고 None 으로 둡니다.
        # (구 버전: f_roe = t_roe × 1.12, roic = t_roe × 0.88, 실패 시 8.5 / 6.8 상수)
        # TODO(오너): 실제 컨센서스(예: FnGuide/WiseReport 추정 ROE) 수집기를 붙이면
        #             이 자리에 실측값을 넣고 UI의 '데이터 없음' 표기가 자동으로 사라집니다.
        # =========================================================
        f_roe = None
        roic = None
        data_issues.append("Forward ROE/ROIC 컨센서스 미수집 (스코어링 제외)")

        # =========================================================
        # 성장률(growth): 네이버 실측 '추정 EPS' 와 'TTM EPS' 의 실제 증감률로 산출합니다.
        # (구 버전: t_roe × 1.3 이라는 근거 없는 변환값)
        # =========================================================
        if t_eps and f_eps and t_eps > 0:
            growth = round((f_eps - t_eps) / t_eps * 100.0, 1)
            growth_source = "consensus_eps_vs_ttm_eps"
        else:
            growth = None
            growth_source = None
            data_issues.append("성장률 산출 불가 (TTM EPS 또는 추정 EPS 없음)")

        # =========================================================
        # 변동성: 실제 주가 시계열 표준편차로 판정. 산출 불가 시 벌점 없음.
        # =========================================================
        vol_std = fetch_recent_volatility(code)
        if vol_std is None:
            vol = "❔ 변동성 데이터 없음"
            vol_penalty = 1.0
            data_issues.append("변동성 시계열 조회 실패 (벌점/가점 미적용)")
        elif vol_std >= VOL_THRESHOLD_PCT:
            vol = f"⚡ 변동성 확대 ({vol_std}%)"
            vol_penalty = VOL_PENALTY
        else:
            vol = f"🟢 정상 ({vol_std}%)"
            vol_penalty = 1.0

        # yfinance 오차 교차검증 — 검증 미수행과 '이상 없음'을 구분 (None = 검증 불가)
        per_discrepancy = None
        if idx < 15 and HAS_YFINANCE and f_per:
            try:
                ticker = yf.Ticker(f"{code}.KS")
                info = ticker.info
                y_f_pe = info.get("forwardPE")
                if y_f_pe and f_per > 0:
                    per_discrepancy = bool(abs(y_f_pe - f_per) / f_per > 0.15)
            except Exception as e:
                print(f"  [yfinance 교차검증 실패] {code}: {e}")
                per_discrepancy = None
            time.sleep(0.1)

        # =========================================================
        # 실효성장률(g_eff) 및 PEGY — 입력이 하나라도 없으면 산출하지 않습니다.
        # =========================================================
        if growth is not None:
            geff = growth + sh_yield
            growth_eff = geff / vol_penalty
        else:
            geff = None
            growth_eff = None

        f_pegy = round(f_per / max(growth_eff, 0.1), 2) if (f_per and growth_eff and growth_eff > 0) else None
        t_pegy = round(t_per / max(geff, 0.1), 2) if (t_per and geff and geff > 0) else None

        # =========================================================
        # 목표주가(f_target) — ENGINEERING_SPEC §5-2 와 동일하게 캡 적용.
        # f_roe / roic 가 None 이면 품질 프리미엄을 적용할 근거가 없으므로 0으로 둡니다.
        # =========================================================
        roe_prem = 0.0 if f_roe is None else (0.15 if f_roe >= 12.0 else -0.10)
        roic_prem = 0.0 if roic is None else (0.10 if roic >= 10.0 else -0.05)

        if f_eps and growth_eff and growth_eff > 0:
            target_pegy = 1.0 * (1.0 + roe_prem + roic_prem)
            target_per = min(target_pegy * growth_eff, 25.0)          # SPEC §5-2: 25배 Cap
            f_target = int(min(f_eps * target_per, price * 2.5))      # SPEC §5-2: 현재가 2.5배 Cap
        else:
            target_per = None
            f_target = None

        if t_eps and geff and geff > 0:
            t_fair = int(min(t_eps * min(geff, 25.0), price * 2.5))
        else:
            t_fair = None

        # 착시 저평가(value trap): ROIC 미수집 상태이므로 t_roe 기준으로만 판정
        value_trap = (t_roe is not None and t_roe < 8.0)

        # =========================================================
        # 3단계 데이터 검증 하네스 파이프라인 (DataValidator) 수행
        # raw_period 는 실제 파싱한 헤더에서 판정한 값을 넘깁니다 (하드코딩 "TTM" 금지).
        # =========================================================
        stock_raw_info = {"raw_eps": n_t_eps, "raw_period": raw_period}
        stock_proc_info = {"code": code, "name": name, "price": price, "t_per": t_per, "t_eps": t_eps, "indicator_type": "PER"}
        sec_info = {"t_per": raw_per} if raw_per else None

        valid_pass, v_logs = DataValidator.run_pipeline(stock_raw_info, stock_proc_info, sec_info)
        is_valid = valid_pass
        validation_error = None if valid_pass else v_logs[-1]

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
            "dps_source": dps_source,
            "outstanding_shares": outstanding_shares,
            "total_dividend_krw": tot_dividend_krw,
            "return_total": tot_amt,
            "t_per": t_per,
            "t_eps": t_eps,
            "sh_return": sh_yield,
            "sh_return_basis": sh_return_basis,
            "t_pegy": t_pegy,
            "t_fair": t_fair,
            "f_per": f_per,
            "f_eps": f_eps,
            "growth": growth,
            "growth_source": growth_source,
            "f_pegy": f_pegy,
            "f_target": f_target,
            "vol": vol,
            "vol_std": vol_std,
            "value_trap": value_trap,
            "per_discrepancy": per_discrepancy,
            "cross_validated": bool(sec_info),
            "t_pbr": t_pbr,
            "ev_ebitda": ev_ebitda,
            "g_eff": round(growth_eff, 1) if growth_eff is not None else None,
            "is_valid": is_valid,
            "validation_error": validation_error,
            "data_issues": data_issues
        }

        # 전체 종목 방공망 모듈 (utils/guardrail.py) 검증 적용
        from utils.guardrail import apply_valuation_guardrail
        stock_dict = apply_valuation_guardrail(stock_dict)

        # 초기화: 점수를 산출할 수 없는 종목은 0점이 아니라 None(= '측정 불가')
        quant_score = None
        score_max = None
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
        if stock_dict.get('is_valid', False) and not stock_dict.get('is_unverified', False):
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
            score_max = score_res["score_max"]
            badge = score_res["badge"]
            badge_bg = score_res["badge_bg"]
            badge_fg = score_res["badge_fg"]
            stock_dict["score_excluded_items"] = score_res.get("excluded_items", [])

        stock_dict["quant_score"] = quant_score
        stock_dict["score_max"] = score_max
        stock_dict["badge"] = badge
        stock_dict["badge_bg"] = badge_bg
        stock_dict["badge_fg"] = badge_fg

        enriched_stocks.append(stock_dict)
        
        # Polite Scraping: 대상 서버(네이버)에 부하를 주지 않기 위해 종목별 크롤링 간격 부여
        time.sleep(random.uniform(2.0, 3.0))

    return enriched_stocks

def update_pegy_summary_history(meta_date, enriched_stocks):
    """상단 3개 요약 지표 수치를 누적 기록하여 pegy_summary_history.json 에 저장합니다."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    history_path = os.path.join(data_dir, "pegy_summary_history.json")

    # 값이 없는 종목은 중앙값 계산에서 제외하며, 표본이 하나도 없으면
    # 임의 상수(10.4 / 14.2 / 0.73)를 기록하지 않고 None(= 데이터 없음)으로 남깁니다.
    f_per_list = [s['f_per'] for s in enriched_stocks if s.get('f_per')]
    growth_list = [s['growth'] for s in enriched_stocks if s.get('growth') is not None]
    pegy_list = [s['f_pegy'] for s in enriched_stocks if s.get('f_pegy') and 0 < s['f_pegy'] < 50.0]

    calc_f_per = round(float(pd.Series(f_per_list).median()), 1) if f_per_list else None
    calc_growth = round(float(pd.Series(growth_list).median()), 1) if growth_list else None  # 대표값 중앙값(Median)
    calc_pegy = round(float(pd.Series(pegy_list).median()), 2) if pegy_list else None

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
        "total_count": len(enriched_stocks),
        "f_per_sample_count": len(f_per_list),
        "growth_sample_count": len(growth_list),
        "pegy_sample_count": len(pegy_list)
    }

    # 동일 시각 중복 기록 방지 후 누적 저장을 위해 이력 추가
    history = [h for h in history if h.get("date") != meta_date]
    history.append(new_record)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Updated PEGY summary history log: {new_record} -> {history_path}")

def run_kospi200_collector():
    """KOSPI 200 시가총액 순 real 데이터 배치 수집 및 data/kospi200_pegy_latest.json 저장"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KOSPI 200 시가총액 순 100% 실시간 실데이터 수집 시작...")
    
    stocks_raw = fetch_kospi200_real_market_data()
    if not stocks_raw:
        # 종목 목록조차 못 가져오면 기존 스냅샷을 건드리지 않고 명확히 실패시킵니다.
        raise RuntimeError("KOSPI 시가총액 목록 스크래핑 실패 — 수집을 중단합니다 (기존 스냅샷 유지)")

    enriched_stocks = enrich_quant_metrics(stocks_raw)

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")

    # 수집 품질 집계: 조건 없는 "SUCCESS" 기록 금지
    total_count = len(enriched_stocks)
    valid_stocks = [s for s in enriched_stocks if s.get("is_valid") and not s.get("is_unverified")]
    failed_codes = [s["code"] for s in enriched_stocks if not (s.get("is_valid") and not s.get("is_unverified"))]
    valid_ratio = (len(valid_stocks) / total_count) if total_count else 0.0

    if total_count == 0:
        status = "FAILED"
    elif valid_ratio >= 0.95:
        status = "SUCCESS"
    else:
        status = "DEGRADED"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot_payload = {
        "metadata": {
            "last_updated_at": now_str,
            "status": status,
            "total_count": total_count,
            "valid_count": len(valid_stocks),
            "valid_ratio": round(valid_ratio, 3),
            "failed_codes": failed_codes,
            "description": (
                f"KOSPI 200 시가총액 상위 1위~{total_count}위 퀀트 스냅샷 "
                f"(검증 통과 {len(valid_stocks)}/{total_count} 종목, 상태={status})"
            )
        },
        "stocks": enriched_stocks
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    if status != "SUCCESS":
        print(f"⚠️ 수집 품질 저하(status={status}): 검증 통과 {len(valid_stocks)}/{total_count} 종목. 실패 종목: {failed_codes[:20]}{' ...' if len(failed_codes) > 20 else ''}")

    # 상단 요약 지표 수치 누적 기록 저장
    update_pegy_summary_history(now_str, enriched_stocks)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KOSPI 200 시총 순 {len(enriched_stocks)}개 실데이터 저장 완료! -> {json_path}")
    return json_path

if __name__ == "__main__":
    run_kospi200_collector()
