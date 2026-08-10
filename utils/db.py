import os
import shutil
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")
HISTORY_BACKUP_FILE = HISTORY_FILE + ".bak"

# 현재 살아있는 세부 위험 지표 컬럼 (누적 CSV 스키마)
# ⚠️ 2026-08-10 (#69): 14개 → 8개. utils/constants.py의 RISK_WEIGHTS와 항상 같은 목록이어야
#    하므로 직접 나열하지 않고 그 사전에서 가져옵니다(두 곳에 적어두면 언젠가 어긋납니다).
from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

METRIC_COLUMNS = list(RISK_WEIGHTS.keys())

# 점수 계산에서 제외된 옛 지표 컬럼 — **새로 만들지 않습니다.**
# 이미 CSV에 쌓여 있는 과거 값은 기록 보존을 위해 그대로 두고(삭제 금지), 아래 COL_MAP에도
# 한글 매핑을 남겨둡니다(과거 행을 다시 읽을 때 필요). 다만 신규 파일에 빈 컬럼을 만들지는
# 않으므로 ensure_metric_columns() 대상에서는 뺐습니다.
RETIRED_METRIC_COLUMNS = list(RETIRED_RISK_INDICATORS.keys())


def _safe_write_history(df):
    """
    누적 이력 CSV 저장 전에 항상 .bak 백업을 남깁니다.
    (예외 상황에서 이력이 통째로 날아가는 사고를 막기 위한 최소 안전장치)
    """
    try:
        if os.path.exists(HISTORY_FILE):
            shutil.copy2(HISTORY_FILE, HISTORY_BACKUP_FILE)
    except Exception as e:
        print(f"⚠️ 이력 백업(.bak) 생성 실패: {e}")
    df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)

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
    # ↓ 2026-08-10 (#69) 점수 계산에서 제외된 6개. 새로 기록되지는 않지만, 이미 저장된 과거
    #   행의 한글 컬럼을 영문으로 되돌리려면 이 매핑이 그대로 필요해 남겨둡니다.
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
    "KOSPI_5D_Return": "KOSPI 5일 낙폭 모멘텀 (지수 폭락 감지용 직접 지표)",
    # 2026-08-10 (#68): scrape_daily.py가 점수와 함께 저장하는 실측 원값 컬럼.
    # 여기에 같은 매핑을 두지 않으면 CSV를 다시 읽을 때 한글 컬럼명이 영문으로 복원되지 않습니다.
    "KOSPI_5D_Return_Pct": "KOSPI 5일 수익률 (%, 실측 원값)",
    # 2026-08-10 (#70): KRX OPEN API 실측 원값 + 그 값의 기준 거래일(as-of).
    # scrape_daily.py 의 COL_MAP 과 **글자 하나까지 같아야** 합니다 — 저장(scrape_daily)과
    # 읽기(이 파일/macro_view)가 서로 다른 한글 헤더를 쓰면 컬럼이 복원되지 않습니다.
    "VKOSPI_Level_Raw": "VKOSPI 지수값 (실측 원값, KRX OPEN API)",
    "VKOSPI_Level_AsOf": "VKOSPI 기준 거래일",
    "Futures_Basis_Raw": "선물 베이시스 (KOSPI200 선물 종가 − 지수 종가, 실측 원값)",
    "Futures_Basis_AsOf": "선물 베이시스 기준 거래일",
    # 2026-08-06: '동기화/업데이트' 표기를 파일 mtime(배포·재시작 시각) 대신
    # 실제 크롤링이 끝나고 이 행이 저장된 시각으로 통일하기 위해 추가.
    "Collected_At": "데이터 수집 완료 시각",
}

def ensure_metric_columns(df):
    """
    구형 CSV 에 현행 세부 지표 컬럼이 없을 때 '컬럼만' 추가하고 값은 결측(NaN)으로 둡니다.
    (2026-08-10 #69 이후 대상은 RISK_WEIGHTS의 8개. 제외된 6개는 새로 만들지 않습니다.)

    ⚠️ 과거 버전(`backfill_missing_metrics`)은 KOSPI·환율만 가지고 '외환 스왑포인트',
       '공매도 잔고' 같은 지표를 소급 생성해 CSV에 저장했고, 저장된 뒤에는 당일 실수집분과
       구분이 불가능했습니다. ENGINEERING_SPEC §0-1 에 따라 역산 생성 로직을 전면 제거합니다.
       수집되지 않은 날짜의 지표는 '데이터 없음(NaN)' 으로 남고 UI에서 N/A 로 표기됩니다.
    """
    for col in METRIC_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


# 하위 호환용 별칭 (외부에서 과거 이름으로 호출하더라도 더 이상 데이터를 생성하지 않음)
backfill_missing_metrics = ensure_metric_columns

def repair_missing_supply_data(df):
    """
    CSV 로드 시 수급 데이터가 0으로 고착된 행(결손 데이터)이 발견되면,
    네이버 스크래퍼를 가동하여 실제 수급 데이터로 덮어쓰고 저장합니다.
    """
    missing_mask = (df["Retail"] == 0) & (df["Foreigner"] == 0) & (df["Institution"] == 0)
    missing_dates = df[missing_mask]["Date"].tolist()
    if not missing_dates:
        return df

    scraped_data = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        for page in range(1, 6):
            # 구형 .nhn 엔드포인트는 폐기되었으므로 현행 .naver 로 교정
            url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?sosok=01&page={page}'
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
    except Exception as e:
        # 실패를 삼키지 않고 화면과 로그 양쪽에 남깁니다 (SPEC §0-1: 로그만 남기는 것은 조치가 아님)
        print(f"⚠️ 수급 결손 보정용 네이버 스크래핑 실패: {e}")
        try:
            st.warning(f"⚠️ 과거 수급 결손 데이터 보정에 실패했습니다. 해당 날짜의 수급은 0으로 표시됩니다. ({e})")
        except Exception:
            pass
        return df

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
        _safe_write_history(df)
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
        "Institution": [institution],
        # 이 행이 실제로 저장되는(= 수집이 끝나 반영되는) 시각. 화면의 "마지막 동기화" 표시는
        # 이 값을 기준으로 하며, 파일 수정시각(mtime)이나 페이지 로드 시각을 쓰지 않습니다.
        # 2026-08-06: KST 명시(서버가 UTC 러너일 때 9시간 어긋나는 문제 방지).
        "Collected_At": [(datetime.now(KST) if KST else datetime.now()).strftime("%Y-%m-%d %H:%M:%S")],
    }
    
    if metrics_dict:
        for k, v in metrics_dict.items():
            new_data[k] = [round(v, 3)]
            
    new_df = pd.DataFrame(new_data)
    is_admin = st.session_state.get("admin_mode", False)
    
    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
            
            history_df = ensure_metric_columns(history_df)
            history_df = repair_missing_supply_data(history_df)

            if is_admin:
                st.write(f"📝 [관리자] 기존 파일 로드 및 정규화 마이그레이션 성공. 행 개수: {len(history_df)}개")
            
            if str(date_key) not in history_df["Date"].values:
                if is_admin:
                    st.write(f"💡 [관리자] 신규 날짜 {date_key} 추가 결합 진행")
                history_df = pd.concat([history_df, new_df], ignore_index=True)
            else:
                if is_admin:
                    st.write(f"💡 [관리자] 기존 날짜 {date_key} 데이터 업데이트 진행")
                history_df.set_index("Date", inplace=True)
                new_df.set_index("Date", inplace=True)
                history_df.update(new_df)
                history_df.reset_index(inplace=True)
                
            _safe_write_history(history_df)
        except Exception as e:
            # ⚠️ 절대 금지: 예외 발생 시 오늘 1행짜리 DataFrame 으로 전체 이력을 덮어쓰는 것.
            #    (과거 버전이 그렇게 동작해 누적 이력이 통째로 사라질 수 있었습니다.)
            #    여기서는 아무것도 쓰지 않고, 실패 사실을 모든 사용자에게 보여준 뒤
            #    읽을 수 있었던 만큼만 반환합니다.
            print(f"❌ 이력 파일 읽기/쓰기 실패 (쓰기 중단): {e}")
            try:
                st.error(
                    f"🚨 누적 이력 파일을 읽거나 저장하지 못했습니다. "
                    f"데이터 보호를 위해 **아무것도 저장하지 않았습니다.** 화면의 이력이 불완전할 수 있습니다.\n\n오류: {e}"
                )
            except Exception:
                pass
            # 원본 파일을 그대로 다시 읽어 최대한 살려서 반환 (실패하면 빈 DataFrame)
            try:
                history_df = pd.read_csv(HISTORY_FILE).rename(columns={v: k for k, v in COL_MAP.items()})
                history_df["Date"] = history_df["Date"].astype(str)
            except Exception:
                history_df = pd.DataFrame()
    else:
        if is_admin:
            st.write("📝 [관리자] 기존 파일 없음. 신규 파일 작성")
        _safe_write_history(new_df)
        history_df = new_df

    return history_df
