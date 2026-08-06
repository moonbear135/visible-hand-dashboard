import os
import sys
import time
import json
import random
import statistics
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
# =========================================================
# 2026-08-06 개편(오너 지적): 예전엔 기준선(2.0%)만 넘으면 표준편차가 2.01%든 15%든 상관없이
# 무조건 고정 1.18배를 곱했습니다 — 이건 "하드컷오프"가 아니라 그냥 단순 하드코딩이었습니다.
# 지금은 기준선 초과분(%p)에 비례해 VOL_PENALTY_MIN~VOL_PENALTY_MAX 사이로 선형 스케일링하고,
# 초과분이 VOL_PENALTY_SEVERITY_CAP_PCT를 넘으면 그 이상은 최대 벌점으로 윈저라이즈합니다.
# (utils/scoring.py의 PER 이상치 상한과 동일한 "절대거리 기반 스케일링" 패턴 — 이 값은 전
# 종목 횡단면 분포가 아니라 PEGY·목표가 계산에 바로 들어가는 입력값이라, 스코어링 하드컷오프처럼
# 2차 패스로 미룰 수 없어 population z-score 대신 절대거리 기반을 그대로 씁니다.)
# =========================================================
VOL_PENALTY_MIN = 1.05               # 기준선을 살짝 넘었을 때 최소 벌점 배수
VOL_PENALTY_MAX = 1.40               # 변동성이 매우 큰 경우 최대 벌점 배수(상한)
VOL_PENALTY_SEVERITY_CAP_PCT = 10.0  # 기준선 대비 +10%p 초과분부터는 최대 벌점으로 고정(윈저라이즈)


def compute_vol_penalty(vol_std):
    """
    측정된 변동성(표준편차 %)이 기준선을 얼마나 초과했는지에 비례해 1.0~VOL_PENALTY_MAX
    사이의 벌점 배수를 반환합니다. 기준선 미만이거나 측정 불가(None)면 1.0(벌점 없음).
    """
    if vol_std is None or vol_std < VOL_THRESHOLD_PCT:
        return 1.0
    excess = min(vol_std - VOL_THRESHOLD_PCT, VOL_PENALTY_SEVERITY_CAP_PCT)
    ratio = excess / VOL_PENALTY_SEVERITY_CAP_PCT
    return round(VOL_PENALTY_MIN + ratio * (VOL_PENALTY_MAX - VOL_PENALTY_MIN), 3)


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
        "t_pbr": None, "ev_ebitda": None, "f_roe": None, "raw_period": None,
        "errors": [error_msg]
    }


def fetch_naver_item_dps_and_eps(code):
    """
    네이버 증권 종목 상세 페이지(item/main.naver)의 우측 Investment Info 스냅샷 및
    주요 재무제표 표에서 TIMEFRAME_KEYWORDS 사전을 기반으로 동적 키워드 헤더 타겟팅을 적용합니다.
    (위치 고정 인덱스 iloc[:, 2] 전면 금지, 100% 범용 동적 수집)

    반환: dict — 파싱하지 못한 항목은 반드시 None 이며, 실패 사유는 errors 리스트에 누적됩니다.
    f_roe: "주요재무제표" 표의 연간 추정(E) 컬럼(예: 2026.12(E))에서 뽑은 Forward ROE 컨센서스.
    (2026-08-06 추가 — 진단 로그로 존재 확인 후 실제 추출 로직으로 전환. 추가 크롤링 요청 없음.)
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
        t_pbr, ev_ebitda, f_roe = None, None, None
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

            # =========================================================
            # 2026-08-06 추가: Forward ROE 컨센서스 — 진단 로그(2026-08-06 밤)로 이 표에
            # "2026.12(E)" 같은 연간 추정 컬럼 + "ROE(지배주주)" 행이 함께 존재함을 확인했습니다.
            # 이미 fetch 중인 페이지에서 그대로 뽑아내는 것이라 추가 크롤링 요청이 없습니다.
            # DataValidator.classify_header_timeframe()이 반환하는 "ANNUAL_EST"(연간+추정)
            # 컬럼만 동적으로 골라 쓰며(iloc 위치 고정 금지, 기존 원칙 그대로), 분기 추정치
            # (예: 2026.06(E))는 여기 안 들어가도록 명확히 구분됩니다.
            # =========================================================
            annual_est_cols = []
            for idx, col in enumerate(fin_df.columns):
                if DataValidator.classify_header_timeframe(col) == "ANNUAL_EST":
                    annual_est_cols.append(idx)

            f_roe = None
            for _di in range(len(fin_df)):
                _row_label = str(fin_df.iloc[_di, 0])
                if 'ROE' in _row_label.upper():
                    for col_i in annual_est_cols:
                        try:
                            v_str = str(fin_df.iloc[_di, col_i]).replace(',', '').strip()
                            if v_str in ('', 'nan', '-', 'ㅡ', '−'):
                                continue
                            v = float(v_str)
                            # 반도체 등 경기순환 업종은 실제로 극단적인 추정 ROE가 나올 수 있어
                            # 값 자체를 지우지 않되, 상식 밖 범위(±300% 초과)만 데이터 오염
                            # 의심으로 제외합니다(PER 이상치 가드레일과 동일한 취지).
                            if abs(v) > 300.0:
                                errors.append(f"Forward ROE 컨센서스 이상치 의심(범위 초과, {v}%) — 제외")
                                continue
                            f_roe = v
                            break
                        except (ValueError, TypeError, IndexError):
                            continue
                    break
            if f_roe is None:
                errors.append("Forward ROE 컨센서스 미제공(애널리스트 커버리지 없음 또는 값 없음)")

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
                            # 네이버는 배당이 없는 해에 셀을 '-'로 표시합니다. 이건 파싱 실패가
                            # 아니라 "배당 없음"이라는 뜻이므로, 에러로 기록하지 않고 조용히 건너뜁니다.
                            if v_str in ('', 'nan', '-', 'ㅡ', '−'):
                                continue
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
            "t_pbr": t_pbr, "ev_ebitda": ev_ebitda, "f_roe": f_roe,
            "raw_period": raw_period, "errors": errors
        }
    except Exception as e:
        print("FETCH_ERROR:", e)
        import traceback
        traceback.print_exc()
        return _empty_item_info(f"종목 상세 파싱 예외: {e}")

def fetch_kospi200_real_market_data():
    """
    네이버 증권 코스피 시가총액 순위 목록(item/main.naver)을 실행 시점 기준으로 스크래핑하여
    코스피 시가총액 상위 종목 시세 데이터(종목코드, 종목명, 현재가, PER, ROE) 200개를 수집합니다.
    ⚠️ 주의: KRX가 공식 발표하는 "코스피 200 지수" 편입종목과는 다릅니다(공식 지수는 유동주식 시총·업종
    안배·유동성 심사를 거쳐 연 2회만 리밸런싱됨). 이 프로젝트는 단순 시가총액 순위 기준입니다.
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
                
                # 히스테리시스 버퍼(진입 200위/이탈 230위) 판정에 필요한 여유분까지 확보.
                # 230위 판정 + ETF 필터링/파싱 실패 여유분까지 감안해 250개 순수 개별주식 확보.
                if len(stocks_raw) >= 250:
                    break
            if len(stocks_raw) >= 250:
                break
        except Exception as e:
            print(f"Error scraping page {page}: {e}")

        time.sleep(random.uniform(2.0, 3.0)) # 매너 있는 크롤링을 위한 여유 있는 딜레이 (Polite Scraping)

    # 여기서는 200개로 자르지 않습니다 — 히스테리시스 버퍼 판정(apply_hysteresis_buffer)이
    # 순위 1~250위 전체를 보고 "화면 노출 200개 + 버퍼 구간 최대 230위까지 추적"을 결정합니다.
    print(f"Successfully retrieved {len(stocks_raw)} real KOSPI candidates (rank order, up to 250).")
    return stocks_raw


def _load_previously_tracked_codes(json_path):
    """
    직전 수집분(data/kospi200_pegy_latest.json)에 실려있던 종목 코드 전체(화면에 보이던 200개 +
    버퍼 구간에서 조용히 추적만 되던 종목까지 전부)를 히스테리시스 판정용으로 불러옵니다.

    ⚠️ 파일이 없거나 깨졌으면 빈 집합(set())을 반환합니다 — 이 경우 오늘 수집은 그냥
       "진입 기준 200위 단순 컷"과 동일하게 동작합니다(첫 실행이거나 복구 불능 상황에서도
       안전하게 진행 가능, 지어내지 않음).
    """
    try:
        if not os.path.exists(json_path):
            return set()
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return {s["code"] for s in payload.get("stocks", []) if s.get("code")}
    except Exception as e:
        print(f"⚠️ 히스테리시스 버퍼용 직전 추적 종목 목록 로드 실패(빈 목록으로 진행): {e}")
        return set()


def apply_hysteresis_buffer(candidates, previous_codes, entry_rank=200, exit_rank=230):
    """
    시가총액 순위 경계선에서 하루만 왔다갔다 해도 종목이 사라졌다 재등장하며
    히스토리 연속성이 깨지는 문제를 막기 위한 히스테리시스 버퍼.

    규칙(오너 확정, 2026-08-06):
    - 진입: 순위가 entry_rank(200위) 이내로 처음 들어오면 추적 시작.
    - 유지: 어제 이미 추적 중이었던 종목은 exit_rank(230위) 밖으로 완전히 밀려나야 추적 중단.
    - 화면 노출은 항상 정확히 entry_rank(200개)만: 버퍼 구간(201~230위)에 걸린 종목은
      계속 수집·보강은 하되(요약 이력이 끊기지 않도록) `is_visible=False`로 표시해 화면에서는 숨김.

    candidates: fetch_kospi200_real_market_data()가 반환한 순위 1위부터의 후보 리스트(최대 250개).
    previous_codes: 직전 수집분에 있었던 종목 코드 집합(_load_previously_tracked_codes 결과).
    반환: 실제로 이번 회차에 수집/보강할 종목 리스트(200~230개 사이, rank/is_visible 필드 포함).
    """
    tracked = []
    for idx, c in enumerate(candidates):
        rank = idx + 1
        if rank <= entry_rank:
            keep = True
        elif c.get("code") in previous_codes and rank <= exit_rank:
            keep = True  # 히스테리시스: 어제부터 추적 중이었고 아직 230위 안쪽 → 유지
        else:
            keep = False
        if keep:
            c["rank"] = rank
            c["is_visible"] = rank <= entry_rank
            tracked.append(c)

    buffer_count = sum(1 for c in tracked if not c["is_visible"])
    if buffer_count:
        print(f"📎 히스테리시스 버퍼: {entry_rank}위 밖 {buffer_count}개 종목을 화면 비노출 상태로 계속 추적합니다.")

    return tracked


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
        t_eps_calculated = False
        t_eps_source = "naver_실측" if t_eps is not None else None
        if t_eps is None:
            data_issues.append("Trailing EPS 수집 실패")
            # 2026-08-05 추가: 대수적 역산 허용 예외 (ENGINEERING_SPEC.md §0-1 예시2-보충)
            # 조건: 실측 EPS를 어디서도 못 구했고, t_per·price 둘 다 실측값일 때만
            # EPS = 가격 ÷ PER 로 역산합니다. 반드시 계산값으로 마킹해서 실측값과 섞지 않습니다.
            if t_per and t_per > 0 and price and price > 0:
                t_eps = round(price / t_per)
                t_eps_calculated = True
                t_eps_source = "calculated_price_div_per"
                data_issues.append(f"Trailing EPS 계산값 사용 (실측 없음, 가격÷PER = {t_eps})")

        # =========================================================
        # 2026-08-05 추가: 그레이엄 넘버(Graham Number) — Forward 데이터가 없어도 쓸 수 있는
        # Trailing 전용 참고 목표가. 벤저민 그레이엄의 원전 공식(PER 15배 × PBR 1.5배 = 22.5)을
        # 그대로 사용하며, 성장률 등 미래 추정치를 전혀 쓰지 않습니다 (ENGINEERING_SPEC §0-1 예시2-보충2).
        # 공식: √(22.5 × Trailing EPS × BPS), BPS = 현재가 ÷ Trailing PBR
        #
        # 한계 (반드시 배지로 경고):
        # - 적자 기업(EPS ≤ 0)은 제곱근 안이 음수가 되어 수학적으로 산출 자체가 불가능합니다
        #   (지어내지 않고 None으로 둡니다 — 오너 요청으로 적자 종목이라고 표에서 빼지는 않습니다).
        # - 은행/보험/증권 등 금융업종은 장부가(BPS)의 의미가 제조업과 달라 그레이엄 넘버의
        #   전제가 잘 안 맞습니다. 계산 자체는 하되 화면에 강한 경고 배지를 붙입니다.
        # =========================================================
        graham_target = None
        graham_is_financial_sector = any(kw in name for kw in ['은행', '금융지주', '보험', '증권', '캐피탈'])
        try:
            t_pbr_val = float(t_pbr) if t_pbr not in (None, '') else None
        except (ValueError, TypeError):
            t_pbr_val = None
        if t_eps is not None and t_eps > 0 and t_pbr_val and t_pbr_val > 0 and price > 0:
            bps = price / t_pbr_val
            graham_target = round((22.5 * t_eps * bps) ** 0.5)
        elif t_eps is not None and t_eps <= 0:
            data_issues.append("그레이엄 넘버 산출 불가 (적자 기업, EPS ≤ 0)")

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
        # 2026-08-06: Forward ROE는 네이버 "주요재무제표" 표의 연간 추정(E) 컬럼에서 실측
        # (fetch_naver_item_dps_and_eps 에서 이미 파싱 — 추가 크롤링 요청 없음). 컨센서스
        # 커버리지가 없는 종목은 그대로 None → '데이터 없음' 유지(지어내지 않음).
        # ROIC는 영업이익/투하자본 별도 계산이 필요한 원천 데이터를 수집하지 않으므로 계속 None.
        # (구 버전: f_roe = t_roe × 1.12, roic = t_roe × 0.88, 실패 시 8.5 / 6.8 상수 — 전부 제거됨)
        # =========================================================
        f_roe = item.get("f_roe")
        if f_roe is None:
            data_issues.append("Forward ROE 컨센서스 미제공 (애널리스트 커버리지 없음)")
        roic = None
        data_issues.append("ROIC 컨센서스 미수집 (원천 데이터 없음, 스코어링 제외)")

        # =========================================================
        # 성장률(growth): 네이버 실측 '추정 EPS' 와 'TTM EPS' 의 실제 증감률로 산출합니다.
        # (구 버전: t_roe × 1.3 이라는 근거 없는 변환값)
        # =========================================================
        if t_eps and f_eps and t_eps > 0:
            growth = round((f_eps - t_eps) / t_eps * 100.0, 1)
            # Trailing EPS가 계산값(가격÷PER)이면 성장률도 그 영향을 그대로 받으므로 함께 마킹합니다.
            growth_source = "consensus_eps_vs_ttm_eps_calculated" if t_eps_calculated else "consensus_eps_vs_ttm_eps"
        else:
            growth = None
            growth_source = None
            data_issues.append("성장률 산출 불가 (TTM EPS 또는 추정 EPS 없음)")

        # =========================================================
        # 변동성: 실제 주가 시계열 표준편차로 판정. 산출 불가 시 벌점 없음.
        # =========================================================
        vol_std = fetch_recent_volatility(code)
        vol_penalty = compute_vol_penalty(vol_std)
        if vol_std is None:
            vol = "❔ 변동성 데이터 없음"
            data_issues.append("변동성 시계열 조회 실패 (벌점/가점 미적용)")
        elif vol_std >= VOL_THRESHOLD_PCT:
            vol = f"⚡ 변동성 확대 ({vol_std}%, 벌점 {vol_penalty}x)"
        else:
            vol = f"🟢 정상 ({vol_std}%)"

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
            # 히스테리시스 버퍼 적용 시 apply_hysteresis_buffer()가 매긴 실제 시가총액 순위를 그대로 쓰고,
            # (버퍼 미적용 구snapshot 등) rank 필드가 없으면 기존처럼 리스트 순서(idx+1)로 대체합니다.
            "rank": s.get("rank", idx + 1),
            # 화면(공개 페이지)에 보여줄지 여부. 200위 이내면 True, 히스테리시스 버퍼 구간(201~230위)에서
            # "이탈 확정 전까지 계속 수집만 하고 화면에는 숨김" 상태면 False.
            "is_visible": s.get("is_visible", True),
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
            "t_eps_calculated": t_eps_calculated,
            "t_eps_source": t_eps_source,
            "graham_target": graham_target,
            "graham_is_financial_sector": graham_is_financial_sector,
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
        # ⚠️ 2026-08-06: 실제 스코어링(calculate_quant_score)은 이 루프가 다 끝난 뒤
        # 2차 패스에서 일괄 수행합니다 — 역성장/적자·극단고평가 하드컷오프의 점수 상한을
        # "오늘 수집된 종목 전체 분포 대비 z-score"로 매기려면 모든 종목의 raw 지표가
        # 먼저 다 모여야 평균/표준편차를 구할 수 있기 때문입니다(아래 루프 이후 코드 참고).
        stock_dict["quant_score"] = None
        stock_dict["score_max"] = None
        stock_dict["badge"] = "🔴 검증 불가"
        stock_dict["badge_bg"] = "#451a03"
        stock_dict["badge_fg"] = "#f97316"
        stock_dict["score_excluded_items"] = []

        if stock_dict.get('reject_reason'):
            stock_dict["badge"] = "🔴 측정 불가 (데이터 오류)"
            stock_dict["badge_bg"] = "#451a03"
            stock_dict["badge_fg"] = "#f97316"
        elif stock_dict.get('unverified_reason'):
            stock_dict["badge"] = "⚠️ 데이터 검증 필요"
            stock_dict["badge_bg"] = "#78350f"
            stock_dict["badge_fg"] = "#facc15"

        enriched_stocks.append(stock_dict)

        # Polite Scraping: 대상 서버(네이버)에 부하를 주지 않기 위해 종목별 크롤링 간격 부여
        time.sleep(random.uniform(2.0, 3.0))

    # =========================================================
    # 2026-08-06 추가: 퀀트 스코어링 2차 패스 (횡단면 population 통계 계산 후 일괄 적용)
    # utils/scoring.py의 하드컷오프(역성장/적자, 극단고평가) 점수 상한은 "오늘 수집된 종목
    # 전체 분포 대비 몇 표준편차 벗어났는지(z-score)"로 정합니다 — Barra/Fama-French류
    # 퀀트 팩터 모델에서 쓰는 표준 횡단면 정규화 기법(오너 요청: "랜덤한 가중치 말고
    # 금융공학적 표준"). 표본이 5개 미만이면 population 통계 없이 진행하며, 이 경우
    # scoring.py가 자동으로 중간값 캡으로 안전하게 대체합니다(크래시·임의값 없음).
    # =========================================================
    _score_pool = [st for st in enriched_stocks if st.get('is_valid', False) and not st.get('is_unverified', False)]

    def _pop_stats(values):
        vals = [v for v in values if v is not None]
        if len(vals) < 5:
            return None
        mean = statistics.mean(vals)
        std = statistics.pstdev(vals)
        return (mean, std) if std > 0 else None

    growth_pop_stats = _pop_stats([st.get('growth') for st in _score_pool])
    roe_pop_stats = _pop_stats([st.get('t_roe') for st in _score_pool])
    pegy_pop_stats = _pop_stats([
        st.get('f_pegy') for st in _score_pool
        if st.get('f_pegy') is not None and 0 < st['f_pegy'] < 50.0
    ])

    for stock_dict in _score_pool:
        score_res = calculate_quant_score(
            f_pegy=stock_dict.get('f_pegy'),
            f_roe=stock_dict.get('f_roe'),
            roic=stock_dict.get('roic'),
            sh_return=stock_dict.get('sh_return'),
            t_roe=stock_dict.get('t_roe'),
            vol=stock_dict.get('vol'),
            f_per=stock_dict.get('f_per'),
            price=stock_dict.get('price'),
            f_target=stock_dict.get('f_target'),
            growth=stock_dict.get('growth'),
            growth_pop_stats=growth_pop_stats,
            roe_pop_stats=roe_pop_stats,
            pegy_pop_stats=pegy_pop_stats
        )
        stock_dict["quant_score"] = score_res["quant_score"]
        stock_dict["score_max"] = score_res["score_max"]
        stock_dict["badge"] = score_res["badge"]
        stock_dict["badge_bg"] = score_res["badge_bg"]
        stock_dict["badge_fg"] = score_res["badge_fg"]
        stock_dict["score_excluded_items"] = score_res.get("excluded_items", [])

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
    """코스피 시가총액 상위 200 real 데이터 배치 수집 및 data/kospi200_pegy_latest.json 저장"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 코스피 시가총액 상위 200 100% 실데이터 수집 시작...")
    
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")

    # 히스테리시스 버퍼 판정을 위해 "어제 뭘 추적 중이었는지"를 오늘 파일을 덮어쓰기 전에 먼저 읽어둡니다.
    previous_codes = _load_previously_tracked_codes(json_path)

    candidates = fetch_kospi200_real_market_data()
    if not candidates:
        # 종목 목록조차 못 가져오면 기존 스냅샷을 건드리지 않고 명확히 실패시킵니다.
        raise RuntimeError("KOSPI 시가총액 목록 스크래핑 실패 — 수집을 중단합니다 (기존 스냅샷 유지)")

    # 히스테리시스 버퍼 적용: 진입 200위 / 이탈 230위. 화면 노출은 여전히 상위 200개만이고,
    # 201~230위 버퍼 구간 종목은 어제도 추적 중이었을 때만 "화면 비노출로 계속 수집"됩니다.
    tracked_stocks = apply_hysteresis_buffer(candidates, previous_codes)
    if not tracked_stocks:
        raise RuntimeError("히스테리시스 버퍼 적용 후 추적 대상 종목이 0개입니다 — 수집을 중단합니다 (기존 스냅샷 유지)")

    enriched_stocks = enrich_quant_metrics(tracked_stocks)

    # 공개 화면에는 is_visible(순위 200위 이내)인 종목만 노출됩니다. 품질 지표(검증 통과율 등)도
    # "화면에 실제로 보이는 200개" 기준으로 집계해야 배너 숫자가 사용자에게 의미가 있습니다.
    visible_stocks = [s for s in enriched_stocks if s.get("is_visible", True)]
    total_count = len(visible_stocks)
    tracked_count = len(enriched_stocks)
    hidden_buffer_count = tracked_count - total_count
    valid_stocks = [s for s in visible_stocks if s.get("is_valid") and not s.get("is_unverified")]
    failed_codes = [s["code"] for s in visible_stocks if not (s.get("is_valid") and not s.get("is_unverified"))]
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
            # 히스테리시스 버퍼 관련 필드(2026-08-06 신설). tracked_count는 화면 비노출 버퍼 구간까지
            # 포함한 실제 수집 종목 수, hidden_buffer_count는 그중 화면에 안 보이는 개수입니다.
            "tracked_count": tracked_count,
            "hidden_buffer_count": hidden_buffer_count,
            "description": (
                f"코스피 시가총액 상위 1위~{total_count}위 퀀트 스냅샷 "
                f"(검증 통과 {len(valid_stocks)}/{total_count} 종목, 상태={status})"
                + (f" + 히스테리시스 버퍼 비노출 {hidden_buffer_count}종목" if hidden_buffer_count else "")
            )
        },
        # ⚠️ 버퍼 구간(is_visible=False) 종목도 그대로 포함합니다 — 화면 필터링은 views/pegy_view.py에서
        # is_visible 기준으로 하고, 여기서는 요약 이력이 끊기지 않도록 전부 저장합니다.
        "stocks": enriched_stocks
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    if status != "SUCCESS":
        print(f"⚠️ 수집 품질 저하(status={status}): 검증 통과 {len(valid_stocks)}/{total_count} 종목. 실패 종목: {failed_codes[:20]}{' ...' if len(failed_codes) > 20 else ''}")

    # 상단 요약 지표(PER/성장률/PEGY 중앙값) 수치 누적 기록 저장.
    # ⚠️ 여기는 visible_stocks(화면에 실제 보이는 200개)만 넘깁니다 — views/pegy_view.py가
    # "이전 동기화 대비" 델타를 계산할 때도 화면에 보이는 종목만으로 오늘자 중앙값을 구하므로,
    # 기준이 어긋나지 않게 맞춰야 합니다. 버퍼 구간 종목의 이력 연속성은 kospi200_pegy_latest.json
    # 쪽(위 stocks 배열에 그대로 포함)에서 이미 보장됩니다.
    update_pegy_summary_history(now_str, visible_stocks)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 코스피 시가총액 순 {total_count}개(+버퍼 {hidden_buffer_count}개) 실데이터 저장 완료! -> {json_path}")
    return json_path

if __name__ == "__main__":
    run_kospi200_collector()
