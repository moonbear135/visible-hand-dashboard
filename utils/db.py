"""
매크로 방공망 누적 이력(market_history.csv) 저장·복구 계층.

⚠️ 2026-08-17 (NiceGUI 이전 6단계) — **streamlit 의존을 제거했습니다.**
   예전에는 이 파일이 `st.warning / st.write / st.error / st.session_state` 를 직접 불러
   화면을 그렸습니다(7곳). 그러면 데이터 계층이 특정 UI 프레임워크에 묶여, 같은 함수를
   NiceGUI 화면에서 부를 수 없습니다(NICEGUI_MIGRATION_PLAN.md §1-2 · §4-2 6번 행).

   대신 **알림 콜백**을 인자로 받습니다.
     · 기본값(콜백 미지정)  → `logging`으로 서버 로그에 남기고, **Streamlit 스크립트
                              실행 중일 때만**(듀얼런 중인 `views/macro_view.py` 호환용)
                              `st.warning`/`st.error`로도 띄웁니다. NiceGUI 요청에는
                              해당 없습니다(아래 `_notify` 참고).
     · 화면을 가진 호출자   → `on_warning=...` / `on_error=...` / `on_admin_note=...` 에
                              배너·notify 를 그리는 함수를 넘겨, 실패 사실이 **사용자
                              화면까지 도달**하게 합니다 (ENGINEERING_SPEC.md §0-1).
     · 관리자 여부도 전역(`st.session_state`)에서 추측하지 않고 `is_admin=` 로 명시적으로
       받습니다 — 한 프로세스가 여러 접속자를 처리하는 NiceGUI 에서 전역 추측은 그 자체가
       사고 경로입니다(§0-3-8 "호출하는 쪽이 명시적으로 넘겨야만 동작").

   ⚠️ **계산·저장 로직과 수치는 한 줄도 바뀌지 않았습니다.** 바뀐 것은 "메시지를 어디로
      보내는가" 뿐입니다.
   ⚠️ 콜백에 넘기는 문구에는 예외 원문·경로·트레이스백을 넣지 않습니다(§0-3-4).
      상세 원인은 `print()`/로거로 서버 쪽에만 남깁니다.
"""

import logging
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

_LOGGER = logging.getLogger(__name__)

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


def _notify(callback, message, level=logging.WARNING):
    """사용자에게 보여줄 **한국어 한 문장**을 알림 경로로 내보냅니다.

    화면을 가진 호출자(NiceGUI 의 `web/pages/macro_page.py`)는 배너를 그리는 함수를
    넘겨, 실패 사실이 사용자 화면까지 도달하게 합니다 (ENGINEERING_SPEC.md §0-1).

    ⚠️ 콜백 미지정(callback=None)일 때는 `logging`만으로 끝내지 않습니다. 이 함수는
       아직 살아있는 `views/macro_view.py`(Streamlit, 듀얼런 중)도 호출하는데, 그 파일은
       콜백을 넘기지 않으므로 로그로만 남기면 화면에 뜨던 실패 배너(옛 `st.warning`/
       `st.error`)가 조용히 사라지는 **§0-1 회귀**가 됩니다. 그래서 streamlit이 설치돼
       있고 지금 실제로 Streamlit 스크립트 실행 중일 때만 그 자리에서 st.warning/error로
       대체합니다. NiceGUI 쪽 요청에는 이 조건이 항상 거짓이라 영향이 없고, 컷오버 후
       `views/`가 없어지면 이 폴백도 자연히 죽은 코드가 됩니다.

    ⚠️ `message` 에는 예외 원문·파일 경로를 넣지 마세요 (§0-3-4). 상세는 호출부의
       `print()` 로 서버 쪽에만 남깁니다.
    """
    _LOGGER.log(level, message)
    if callback is not None:
        try:
            callback(message)
        except Exception as exc:                  # noqa: BLE001 — 알림 실패가 저장을 막지 않도록
            _LOGGER.warning("알림 콜백 실행 실패: %s", exc)
        return
    try:
        import streamlit as st                    # noqa: PLC0415 — 듀얼런 하위호환 전용 지연 import
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            (st.error if level >= logging.ERROR else st.warning)(message)
    except Exception:                              # noqa: BLE001 — streamlit 미설치·비실행 컨텍스트 등
        pass


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

def repair_missing_supply_data(df, on_warning=None):
    """
    CSV 로드 시 수급 데이터가 0으로 고착된 행(결손 데이터)이 발견되면,
    네이버 스크래퍼를 가동하여 실제 수급 데이터로 덮어쓰고 저장합니다.

    :param on_warning: 실패 사실을 화면에 띄우는 콜백(`Callable[[str], None]`).
        미지정이면 `logging` + (Streamlit 실행 중이면) `st.warning` 으로 남습니다
        (§0-1 — NiceGUI 등 화면이 있는 새 호출자는 반드시 넘기세요, `_notify` 참고).
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
        # 화면 문구에는 예외 원문을 넣지 않습니다 (§0-3-4). 원인은 위 print 로 서버 로그에만.
        _notify(
            on_warning,
            "⚠️ 과거 수급 결손 데이터 보정에 실패했습니다. 해당 날짜의 수급은 0으로 표시됩니다.",
        )
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

def save_and_load_history(date_key, score, kospi_close, usd_close, retail, foreigner, institution,
                          metrics_dict=None, is_admin=False,
                          on_admin_note=None, on_warning=None, on_error=None):
    """
    로컬 CSV 파일에 매일의 데이터를 누적 저장하고 불러옵니다.

    :param is_admin: 관리자 화면에서 호출됐는지. **전역 상태에서 추측하지 않고 호출부가
        명시적으로 넘깁니다** (§0-3-8). True 일 때만 진행 상황 메모(`on_admin_note`)를 냅니다.
    :param on_admin_note: 관리자용 진행 메모 콜백. 미지정이면 `logging` 으로만 남습니다
        (진행 메모는 실패 알림이 아니므로 Streamlit 폴백 대상이 아닙니다).
    :param on_warning: 수급 결손 보정 실패 등 경고 콜백 (`repair_missing_supply_data` 에 전달).
        미지정이면 `_notify` 의 Streamlit 폴백이 적용됩니다.
    :param on_error: 이력 파일 읽기/쓰기 실패 콜백 — **반드시 화면까지 도달해야 하는 실패**입니다(§0-1).
        미지정이면 `_notify` 의 Streamlit 폴백이 적용됩니다.
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

    def _admin_note(message):
        """관리자에게만 보이는 진행 메모 (원본의 `st.write(...)` 자리)."""
        if is_admin:
            _notify(on_admin_note, message, level=logging.INFO)

    if os.path.exists(HISTORY_FILE):
        try:
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)

            history_df = ensure_metric_columns(history_df)
            history_df = repair_missing_supply_data(history_df, on_warning=on_warning)

            _admin_note(f"📝 [관리자] 기존 파일 로드 및 정규화 마이그레이션 성공. 행 개수: {len(history_df)}개")

            if str(date_key) not in history_df["Date"].values:
                _admin_note(f"💡 [관리자] 신규 날짜 {date_key} 추가 결합 진행")
                history_df = pd.concat([history_df, new_df], ignore_index=True)
            else:
                _admin_note(f"💡 [관리자] 기존 날짜 {date_key} 데이터 업데이트 진행")
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
            # 2026-08-17: 예전에는 이 문구 끝에 `오류: {e}` 로 **예외 원문을 화면에 그대로**
            # 붙이고 있었습니다 — ENGINEERING_SPEC.md §0-3-4(사용자 화면에 코드/내부 에러
            # 노출 금지) 위반이라 제거했습니다. 원인은 바로 위 print 로 서버 로그에 남습니다.
            _notify(
                on_error,
                "🚨 누적 이력 파일을 읽거나 저장하지 못했습니다. "
                "데이터 보호를 위해 아무것도 저장하지 않았습니다. 화면의 이력이 불완전할 수 있습니다.",
                level=logging.ERROR,
            )
            # 원본 파일을 그대로 다시 읽어 최대한 살려서 반환 (실패하면 빈 DataFrame)
            try:
                history_df = pd.read_csv(HISTORY_FILE).rename(columns={v: k for k, v in COL_MAP.items()})
                history_df["Date"] = history_df["Date"].astype(str)
            except Exception:
                history_df = pd.DataFrame()
    else:
        _admin_note("📝 [관리자] 기존 파일 없음. 신규 파일 작성")
        _safe_write_history(new_df)
        history_df = new_df

    return history_df
