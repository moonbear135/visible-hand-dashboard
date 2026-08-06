import os
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

# FinanceDataReader 임포트
try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False

# 2026-08-06 2차 감사 5-1/5-2/4-1: 가중치·정규화·증폭기 로직을 macro_view.py와 공유하는
# 단일 출처로 이전(utils/macro_scoring.py, utils/constants.py 참고).
from utils.constants import RISK_WEIGHTS, INVESTOR_WEIGHTS
from utils.macro_scoring import compute_historical_stats, compute_sub_scores, compute_final_score

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

# (SPEC §3: 개별 크롤러의 PERIOD_KEYWORDS 사본 하드코딩 금지.
#  이 파일에서는 실제로 사용되지 않으므로 utils/data_validator.py 의 사전을 단일 출처로 참조합니다.)
from utils.data_validator import PERIOD_KEYWORDS  # noqa: F401  (단일 출처 유지용)

def clip(val):
    return min(1.0, max(0.0, val))

def scrape_and_update(target_date_override=None):
    is_backfill = bool(target_date_override)

    if is_backfill:
        # 특정 과거 날짜를 지정해서 보정(백필)하는 모드
        target_date = datetime.strptime(target_date_override, "%Y-%m-%d")
        print(f"🩹 백필 모드: {target_date_override} 데이터를 보정합니다.")
    else:
        # 🐛 [버그 수정] datetime.today()는 실행 서버의 시스템 시간(깃허브 액션 서버는 UTC)을 반환합니다.
        # 아래 "15시 30분 장마감" 판단은 한국시간(KST) 기준이므로, UTC 그대로 비교하면
        # 날짜가 하루씩 밀리는 문제가 있었습니다. 반드시 한국시간으로 변환해서 판단합니다.
        target_date = datetime.now(KST) if KST else datetime.today()
        # 15시 30분(장 마감) 이전이라면, 수집 대상은 전날 데이터입니다.
        if target_date.hour < 15 or (target_date.hour == 15 and target_date.minute < 30):
            target_date -= timedelta(days=1)
        target_date = target_date.replace(tzinfo=None)

    # 주말일 경우 직전 금요일로 조정
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)

    date_key = target_date.strftime("%Y-%m-%d")
    print(f"🚀 자동 수집 시작 대상 영업일: {date_key}")
    
    # 1. 기존 데이터 로드 및 중복 검사 (중복 시 덮어쓰기 위해 기존 행 삭제)
    history_df = pd.DataFrame()
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
            
            # 기존에 동일한 날짜 데이터가 있다면 삭제 (새로운 최신 데이터로 덮어쓰기 위함)
            if date_key in history_df["Date"].values:
                print(f"ℹ️ {date_key} 데이터가 이미 존재합니다. 최신 데이터로 덮어씁니다.")
                history_df = history_df[history_df["Date"] != date_key]
        except Exception as e:
            print(f"❌ 기존 파일 읽기 오류: {str(e)}")
            history_df = pd.DataFrame()

    # 2. 크롤링 기초 데이터 수집
    #    ⚠️ 시드값(1.2 / 0.08 / 0.5)을 미리 넣어두면 FDR 조회가 실패해도 그 값이
    #       그대로 지표 계산에 흘러들어가 '정상적으로 보이는 점수'가 만들어집니다.
    #       따라서 전부 None 으로 두고, 없으면 아래에서 수집을 중단합니다.
    kospi_close = None
    usd_close = None
    # 2026-08-06 2차 감사 4-4: 전일 종가를 못 구해 변화율을 산출할 수 없는 경우 0.0(보합)으로
    # 채우면 실제 관측처럼 보이는 값이 6개 지표 공식에 그대로 흘러들어갑니다. None으로 두고
    # 아래에서 의존 지표를 배점 제외합니다.
    kospi_change = None
    usd_change = None
    volatility = None
    dist_from_high = None
    kospi_5d_base = None


    # KOSPI & USD_KRW 조회
    if FDR_AVAILABLE:
        try:
            kospi_data = fdr.DataReader('^KS11')
            usd_data = fdr.DataReader('USDKRW=X')
            
            if not kospi_data.empty and not usd_data.empty:
                # 💡 [CRITICAL BUG FIX]: target_date 이후의 데이터는 무시하고, target_date 이전의 가장 최신 데이터를 가져옴
                target_dt = pd.to_datetime(date_key)
                kospi_data.index = kospi_data.index.tz_localize(None)
                usd_data.index = usd_data.index.tz_localize(None)
                
                # .ffill() 제거: 휴장일이 아닌 '진짜 결측'까지 전일 값으로 조용히 메워지는 것을 방지
                valid_kospi = kospi_data[kospi_data.index <= target_dt].dropna(subset=['Close'])
                valid_usd = usd_data[usd_data.index <= target_dt].dropna(subset=['Close'])

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
                    # 2026-08-06 2차 감사 4-2: 5영업일 이력이 부족하면 0.0(변화 없음)으로
                    # 채우지 않고 None으로 둡니다 — 아래 죽어있던 가드(kospi_5d_base is None)가
                    # 실제로 작동해 이 지표를 배점에서 제외하게 됩니다.
                    if len(valid_kospi) >= 6:
                        k_5d_ago = float(valid_kospi.iloc[-6]['Close'])
                        kospi_5d_return = (kospi_close - k_5d_ago) / k_5d_ago
                        kospi_5d_base = 0.5 - 2.5 * kospi_5d_return
                    else:
                        kospi_5d_base = None
                    
                    print(f"✅ 야후 파이낸스(FDR) 시장 데이터 조회 성공 ({date_key}) KOSPI={kospi_close:.2f}")
                else:
                    raise ValueError(f"{date_key} 이전의 데이터를 찾을 수 없습니다.")
        except Exception as e:
            print(f"⚠️ FinanceDataReader 수집 실패: {str(e)}")

    # === [네이버 웹 스크래핑(Primary) 우회 수집 로직] ===
    # 주의: 이 블록은 "스크립트 실행 시점(장마감 직후)의 시세"를 가져오는 로직이라,
    # 과거 날짜를 보정(백필)하는 경우에는 건너뜁니다. (안 그러면 오늘 시세로 과거 데이터가 덮어써짐)
    # 2026-08-06 2차 감사 4-5: 네이버 현재가로 FDR 종가를 덮어쓰기 전에 괴리율을 검사합니다.
    # ⚠️ 여기서 "괴리가 크면 덮어쓰지 않는다"로 막지 않습니다 — 이 네이버 재조회 블록은
    # 원래 "FDR(야후 소스)가 하루 지연되는 경우가 있어 장마감 직후 실제 값으로 보정한다"는
    # 목적으로 존재하므로(정상적인 하루 지연 보정 시 몇 % 괴리는 흔하고 정상), 괴리를 이유로
    # 덮어쓰기를 막으면 이 블록의 존재 목적 자체가 무력화됩니다. 대신 큰 괴리가 있으면
    # kospi_change(전일 대비 변화율)도 네이버 종가 기준으로 재계산해, "저장된 종가"와
    # "점수 계산에 쓰인 변화율"이 서로 다른 시점 값이 되는 문제만 없앱니다(volatility·
    # dist_from_high는 장기 시계열 기반이라 하루 지연의 영향이 미미해 그대로 둡니다).
    NAVER_DEVIATION_WARN_THRESHOLD = 0.01  # 1% — 이 이상이면 "다른 시점 값일 수 있다"는 흔적을 남김
    kospi_close_fdr = kospi_close

    if not is_backfill:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

            # KOSPI 수집
            k_res = requests.get("https://finance.naver.com/sise/sise_index.naver?code=KOSPI", headers=headers, timeout=5)
            k_soup = BeautifulSoup(k_res.text, 'html.parser')
            k_now = k_soup.select_one('#now_value')
            if k_now:
                k_val_str = k_now.text.replace(',', '')
                if k_val_str.replace('.', '', 1).isdigit():
                    kospi_close_naver = float(k_val_str)
                    if kospi_close_fdr:
                        deviation = abs(kospi_close_naver - kospi_close_fdr) / kospi_close_fdr
                        if deviation > NAVER_DEVIATION_WARN_THRESHOLD and kospi_change is not None:
                            # FDR 종가 기준으로 이미 계산된 변화율을, 실제로 저장될 네이버 종가
                            # 기준으로 다시 맞춥니다(둘 다 "전일 대비"라는 의미는 동일하게 유지).
                            kospi_prev_est = kospi_close_fdr / (1 + kospi_change)
                            kospi_change = (kospi_close_naver - kospi_prev_est) / kospi_prev_est
                            print(f"⚠️ 네이버 KOSPI({kospi_close_naver})가 FDR 종가({kospi_close_fdr})와 "
                                  f"{deviation*100:.2f}% 괴리 — FDR이 지연된 것으로 보고 변화율을 "
                                  f"네이버 종가 기준으로 재계산했습니다.")
                    kospi_close = kospi_close_naver
                    print(f"✅ 네이버 금융 KOSPI 수집 성공: {kospi_close}")

            # USD/KRW 수집
            u_res = requests.get("https://finance.naver.com/marketindex/", headers=headers, timeout=5)
            u_soup = BeautifulSoup(u_res.text, 'html.parser')
            u_now = u_soup.select_one('#exchangeList > li.on > a.head.usd > div > span.value')
            if u_now:
                u_val_str = u_now.text.replace(',', '')
                if u_val_str.replace('.', '', 1).isdigit():
                    usd_close_naver = float(u_val_str)
                    usd_close = usd_close_naver
                    print(f"✅ 네이버 금융 환율 수집 성공: {usd_close}")

        except Exception as e:
            print(f"⚠️ 네이버 금융 스크래핑 실패 (FDR 값 유지): {e}")
    else:
        print(f"ℹ️ 백필 모드: 당일 시세 조회를 건너뛰고 {date_key} 기준 종가(FDR)를 사용합니다.")

    # === [백엔드 결측치 검증] ===
    # ⚠️ 과거 버전은 여기서 전일 종가를 '오늘 종가 자리에' 그대로 써넣고(Forward Fill)
    #    변화율을 0.0(보합)으로 기록했습니다. CSV에는 보정 흔적이 남지 않아
    #    대시보드가 실제 종가와 100% 동일하게 렌더링했습니다 → 전면 금지.
    if pd.isna(kospi_close) or pd.isna(usd_close) or kospi_close is None or usd_close is None:
        raise RuntimeError(
            f"{date_key} KOSPI/환율 종가 수집 실패 — 전일 값으로 메우지 않고 당일 수집을 중단합니다. "
            f"(KOSPI={kospi_close}, USD={usd_close})"
        )

    # 변동성·고점대비낙폭이 없으면 4개 지표(공매도 비중/ELS 낙인/공포지수/공매도 잔고)가
    # 시드 상수로 계산되어 버리므로, 아예 수집을 중단합니다.
    if volatility is None or dist_from_high is None:
        raise RuntimeError(
            f"{date_key} 변동성/고점대비낙폭 산출 실패 — 임의 상수(1.2 / 0.08)로 대체하지 않고 당일 수집을 중단합니다."
        )

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
    # 2026-08-06 2차 감사 4-4: kospi_change/usd_change가 None이면(전일 종가 비교 불가)
    # 그걸 입력으로 쓰는 지표들도 값을 지어내지 않고 None으로 둡니다(아래 market_scores
    # 구성 단계에서 자동으로 배점 제외됩니다).
    fx_base = 0.5 + 0.3 * (usd_close - 1200) / 300  # usd_close 자체는 위에서 이미 None 방어됨
    put_base = None if kospi_change is None else (0.5 - 0.4 * kospi_change)
    short_base = 0.4 + 0.4 * (volatility / 5.0)
    els_base = 0.1 + 0.7 * dist_from_high
    skew_base = None if kospi_change is None else (0.4 + 0.4 * (volatility / 5.0) - 0.2 * kospi_change)
    synth_base = 0.5 + 0.3 * (usd_close - 1300) / 200
    ndf_base = None if usd_change is None else (0.4 + 0.5 * usd_change)
    fut_base = None if kospi_change is None else (0.5 - 0.3 * kospi_change)
    non_base = 0.5 + (0.2 if institution_flow < 0 else -0.1)
    dump_base = 0.5 + (0.3 if foreigner_flow < 0 else -0.2)
    bal_base = 0.5 + 0.3 * dist_from_high
    put_buy_base = None if kospi_change is None else (0.4 - 0.3 * kospi_change)
    # 2026-08-06 2차 감사 4-3: 예전엔 순수 상수 0.5(방향성만 반영, 규모 미반영)였습니다.
    # 정확한 매매대금 대비 순매도 '비중' 데이터는 아직 수집하지 않아 완전한 규모화는
    # 어렵지만, 최소한 3주체 수급 규모 대비 개인 수급이 차지하는 상대적 비중만큼은
    # 반영해 "방향만 있고 크기는 무시"하는 문제를 완화합니다. 세 흐름이 전부 0이면(드묾)
    # 중립 0.5를 유지합니다.
    _flow_denom = abs(retail_flow) + abs(foreigner_flow) + abs(institution_flow)
    if _flow_denom > 0:
        _retail_share = abs(retail_flow) / _flow_denom  # 0~1: 개인 수급이 전체에서 차지하는 비중
        stock_net_base = 0.5 + (0.3 if retail_flow < 0 else -0.3) * _retail_share
    else:
        stock_net_base = 0.5

    # 가중 위험 지표 계산 및 합산 (2026-08-06 2차 감사 5-1: 가중치 단일 출처로 통일 —
    # scrape_daily.py/macro_view.py 양쪽 다 utils.constants.RISK_WEIGHTS만 참조합니다)
    investor_weights = dict(INVESTOR_WEIGHTS)
    weights = dict(RISK_WEIGHTS)

    # 2026-08-06 2차 감사 4-4 방어: usd_change가 None이면 FX_Swap_Point의 외국인 항목도
    # None으로 두어야 하므로, fx_base와 usd_change 보정을 분리해 None 전파를 명시적으로 처리.
    fx_foreigner = None if usd_change is None else clip(fx_base + 0.1 * usd_change)

    market_scores = {
        "FX_Swap_Point": None if fx_foreigner is None else {
            "Foreigner": fx_foreigner, "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)
        },
        "Put_OTM_OI": None if put_base is None else {
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
        "VKOSPI_Skew": None if skew_base is None else {
            "Foreigner": clip(skew_base + 0.05), "Institution": clip(skew_base), "Retail": clip(skew_base - 0.2)
        },
        "Synthetic_Futures": {
            "Foreigner": clip(synth_base + (0.15 if foreigner_flow < 0 else -0.1)),
            "Institution": clip(synth_base),
            "Retail": clip(synth_base + (0.05 if retail_flow > 0 else -0.05))
        },
        "NDF_Night_Rate": None if ndf_base is None else {
            "Foreigner": clip(ndf_base + 0.1), "Institution": clip(ndf_base), "Retail": clip(ndf_base - 0.2)
        },
        "Futures_Net_Sell": None if fut_base is None else {
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
        "Put_Buy_Simple": None if put_buy_base is None else {
            "Foreigner": clip(put_buy_base + (0.05 if foreigner_flow < 0 else -0.05)),
            "Institution": clip(put_buy_base),
            "Retail": clip(put_buy_base + (0.1 if retail_flow > 0 else -0.1))
        },
        "Stock_Net_Sell": {
            "Foreigner": clip(stock_net_base + (0.3 if foreigner_flow < 0 else -0.3)),
            "Institution": clip(stock_net_base + (0.2 if institution_flow < 0 else -0.2)),
            "Retail": clip(stock_net_base + (0.3 if retail_flow < 0 else -0.3))
        },
        "KOSPI_5D_Return": None if kospi_5d_base is None else {
            "Foreigner": clip(kospi_5d_base), "Institution": clip(kospi_5d_base), "Retail": clip(kospi_5d_base)
        }
    }

    # 산출 불가(None)로 남은 지표는 0.5(중립)로 채우지 않고 통째로 제외합니다(§0-1).
    unavailable_items = [k for k, v in market_scores.items() if v is None]
    if unavailable_items:
        print(f"⚠️ 산출 불가 지표 {len(unavailable_items)}건 제외: {', '.join(unavailable_items)}")
    weights = {k: w for k, w in weights.items() if market_scores.get(k) is not None}
    market_scores = {k: v for k, v in market_scores.items() if v is not None}

    # 1. 개별 지표별 가중 수급 리스크(0~1) 계산 및 저장용 metrics_dict 생성
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

    if len(history_df) < 20:
        print(f"⚠️ 정규화 표본 부족: 누적 이력 {len(history_df)}행 (권장 20행 이상). "
              f"Z-Score 기반 서브 점수가 극단으로 튈 수 있습니다.")

    # 2026-08-06 2차 감사 5-1/5-2/4-1: 과거 통계·시그모이드 변환·증폭기 로직을
    # macro_view.py와 공유하는 utils/macro_scoring.py로 이전(파일 상단 import 참고).
    # ⚠️ 이 파일이 "그날의 실제 점수"를 만드는 유일한 지점입니다 — 계산 직후 sub_scores/
    # multiplier를 CSV에 그대로 저장해(아래 6번), macro_view.py가 과거 날짜를 보여줄 때는
    # 재계산하지 않고 이 값을 그대로 읽게 합니다(그날의 historical_stats는 지금 재현 불가).
    historical_stats = compute_historical_stats(history_df, weights.keys())
    sub_scores = compute_sub_scores(current_weighted_risks, historical_stats)
    score, base_score, multiplier, extreme_signal_count, available_count = compute_final_score(sub_scores, weights)
    print(f"📊 당일 계산된 종합 스코어: {score} (기본점수 {base_score}, 증폭배율 {multiplier}x, "
          f"극단신호 {extreme_signal_count}/{available_count})")

    # 6. 새 데이터 생성 및 기존 데이터에 병합하여 CSV 저장
    new_data = {
        "Date": [date_key],
        "Score": [score],
        "KOSPI": [round(kospi_close, 2)],
        "USD_KRW": [round(usd_close, 2)],
        "Retail": [retail_flow],
        "Foreigner": [foreigner_flow],
        "Institution": [institution_flow],
        # 이 행이 실제로 저장되는(= 크롤링이 끝나 반영되는) 시각. 화면의 "마지막 동기화" 표시는
        # 파일 mtime이 아니라 이 값을 사용합니다.
        # 2026-08-06: 이 파일이 이미 KST를 정의해뒀는데 여기서는 안 쓰고 있어서 GitHub
        # Actions(UTC 러너)에서는 "마지막 동기화" 표시가 실제보다 9시간 이르게 찍히고
        # 있었습니다(오너가 collector_kospi200.py에서 같은 유형의 버그를 실데이터로 발견).
        "Collected_At": [(datetime.now(KST) if KST else datetime.now()).strftime("%Y-%m-%d %H:%M:%S")],
        # 2026-08-06 2차 감사 5-2: 그날 실제로 화면 점수를 만든 시그모이드 변환 후 서브점수·
        # 증폭배율을 함께 저장합니다. macro_view.py가 과거 날짜를 보여줄 때 이 값을 그대로
        # 읽으면(재계산 없이) 화면 표의 기여점수 합이 항상 위에 뜬 종합점수와 일치합니다.
        "Multiplier": [multiplier],
        "ExtremeSignalCount": [extreme_signal_count],
    }

    for k, v in metrics_dict.items():
        new_data[k] = [round(v, 3)]
    for k, v in sub_scores.items():
        new_data[f"SubScore_{k}"] = [v]


    new_df = pd.DataFrame(new_data)
    
    if not history_df.empty:
        history_df = pd.concat([history_df, new_df], ignore_index=True)
    else:
        history_df = new_df
        
    # 한글 컬럼명으로 변환하여 저장
    history_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)
    print("💾 market_history.csv 파일 누적 갱신 성공!")

    # 6.5. AI 젬민이 코멘트 생성 (14개 지표 개별 루프)
    try:
        from utils.macro_ai import generate_macro_commentary
        generate_macro_commentary(metrics_dict, score, kospi_close, usd_close)
    except Exception as e:
        print(f"⚠️ AI 코멘트 생성 중 에러 발생: {e}")

    # 7. 데이터 수집 완료 후 구글 드라이브 자동 백업 실행
    # 2026-08-06: 폴더 ID를 환경변수(GDRIVE_TARGET_FOLDER_ID)로 오버라이드 가능하게 전환.
    # 값을 안 넣으면 기존과 완전히 동일하게 동작(utils/gdrive_helper.py의 기본값 그대로 사용).
    try:
        from utils.gdrive_helper import upload_file
        print("☁️ 구글 드라이브 자동 백업 시작...")
        upload_file(HISTORY_FILE)
    except Exception as e:
        print(f"⚠️ 구글 드라이브 자동 백업 건너뜀: {e}")

if __name__ == "__main__":
    # 명령줄에 날짜(YYYY-MM-DD)를 넣으면 그 날짜 데이터를 보정(백필)합니다.
    # 예) python scrape_daily.py 2026-08-04
    override_arg = sys.argv[1].strip() if len(sys.argv) > 1 else None
    scrape_and_update(target_date_override=override_arg if override_arg else None)
