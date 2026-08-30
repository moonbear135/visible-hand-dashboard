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

# 2026-08-06 2차 감사 후속(오너 실데이터 검증 중 발견): GitHub Actions 러너는 기본 UTC라
# datetime.now()가 KST가 아닌 UTC를 반환합니다. JSON metadata의 last_updated_at이
# "08:09"처럼 찍혀 실제 KST 완료 시각(17:09)과 9시간 어긋나 있었습니다. scrape_daily.py와
# 동일한 방식으로 KST를 명시합니다.
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

def _now_kst():
    return datetime.now(KST) if KST else datetime.now()

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
# 임계값·캡 상수는 utils/constants.py 단일 출처에서만 가져옵니다 (2차 감사 6-3: 중복 제거).
from utils.constants import (
    PER_EXTREME_MAX,
    GROWTH_CAP_PCT,
    SH_RETURN_CAP_PCT,
    GEFF_TOTAL_CAP_PCT,
    TARGET_PER_CAP,
    TARGET_PRICE_CAP_MULTIPLE,
    ROE_PREMIUM_BASELINE_PCT,
    VALUE_TRAP_ROE_PCT,
)
# 2026-08-09 신설(TASK_HISTORY #64): 종목별 시계열 이력 누적. 필드 목록·라벨·저장 규칙의
# 단일 출처는 utils/stock_history.py 이며, 기존 수집 로직은 한 줄도 바뀌지 않았습니다
# (아래 run_kospi200_collector 맨 끝, 스냅샷 저장이 끝난 뒤에 '추가'로만 호출).
from utils.stock_history import (
    KOSPI_HISTORY_FIELDS,
    KOSPI_HISTORY_FILENAME,
    record_daily_history,
    stock_history_path,
)
from utils import data_sanity

# =============================================================================
# 데이터 무결성 상수 (ENGINEERING_SPEC §0-1 "하드코딩 및 더미 데이터 금지" 준수)
# - 아래 값들은 "실데이터가 맞는지 판별하기 위한 검증 임계치"이며,
#   실데이터를 대체하는 기본값(더미)이 아닙니다.
# =============================================================================
MIN_OUTSTANDING_SHARES = 1_000_000   # 상장주식수 파싱 결과 sanity range check 하한
VOL_WINDOW = 20                      # 변동성 산출 기간(영업일)
VOL_THRESHOLD_PCT = 2.0              # 일간수익률 표준편차(%) 기준 '변동성 확대' 판정선

# =========================================================
# 수집 품질 상태(status) 판정선 — 2026-08-06 2차 감사 1-10.
# 예전엔 0.95 하드코딩이었는데, 실제 통과율이 0.855라 매일 무조건 DEGRADED가 찍혀
# "품질 저하 경고"가 상시 점등 = 아무도 안 보는 경고가 되어 있었습니다.
# 근거: 코스피 상위 200종목 중 애널리스트 컨센서스(추정 PER/EPS) 커버리지가 없는
# 종목이 구조적으로 10~15% 존재합니다(중소형 지주사·우선주 등). 이건 수집 장애가
# 아니라 시장의 정상 상태이므로, 그보다 더 나빠질 때만 경고가 뜨도록 0.85로 잡고
# 0.70 미만은 진짜 수집 장애(FAILED 직전)로 구분합니다.
# =========================================================
# 🔴 2026-08-26 재검토 필요 플래그 — 코스피 상위 200(대형 우량주 위주) 기준으로 실측(0.855)한
# 값입니다. 이제 코스피+코스닥 통합 상위 500까지 넓어져 중소형·코스닥 종목 비중이 늘면
# 애널리스트 컨센서스 커버리지가 구조적으로 더 낮아질 가능성이 높습니다(중소형주는 대형주보다
# 커버하는 증권사가 적음). 근거 없이 숫자만 낮추는 건 §0-1 위반이라 지금은 값을 그대로
# 두었습니다 — 이번 merge 이후 실제 valid_ratio가 여기 얼마나 못 미치는지 첫 실행 로그로
# 확인한 뒤, 필요하면 그 실측값 근거로 재조정하세요(과거 0.95→0.85 조정과 같은 방식).
# =========================================================
VALID_RATIO_SUCCESS = 0.85   # 이 이상이면 SUCCESS (컨센서스 미커버 구조적 결측 감안, 코스피200 기준 실측값 — 위 플래그 참고)
VALID_RATIO_DEGRADED = 0.70  # 이 미만이면 수집 파이프라인 자체 이상 의심

# PEGY 분모(실효성장률) 최소 유효값(%p) — 2026-08-06 2차 감사 1-9.
# 이 미만이면 PEGY = PER/거의0 이라 수백~수천의 무의미한 값이 나오므로, 근거 없는
# 바닥값(구 버전의 max(g,0.1))으로 눌러 담지 않고 아예 산출하지 않습니다.
PEGY_MIN_DENOMINATOR_PCT = 0.5
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

# 2026-08-29 재감사 M5: yfinance PER 교차검증 표본 수(상단 N개 종목).
# 근거: 전 종목(500개) 교차검증은 외부 API 호출 비용·소요시간이 커서 감당이 안 되고,
# 이 검증의 목적은 "우리 파싱이 통째로 틀어졌는지"를 잡는 것이라 상위 표본이면 충분합니다.
# (예전엔 함수 안에 `idx < 15` 매직넘버로 박혀 있어 근거도 조정 지점도 없었습니다.)
YFINANCE_CROSS_CHECK_TOP_N = 15

# 2026-08-29 재감사 L13: 그레이엄 공식 제외 대상인 금융업종 판정 키워드.
# ⚠️ 업종 코드 데이터를 수집하지 않아 **종목명 키워드 기반 추정**입니다 — 오탐(이름에
# 키워드가 있는 비금융사)과 누락(키워드가 없는 금융사)이 모두 가능합니다. 로직 자체는
# 그대로 두고 매직 리터럴만 상수화한 것입니다(TASK_HISTORY 참고).
FINANCIAL_SECTOR_NAME_KEYWORDS = ['은행', '금융지주', '보험', '증권', '캐피탈']


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


# =========================================================
# 2026-08-06 2차 감사 1-2 개편: ROE/ROIC 품질 프리미엄의 '절벽(cliff)' 제거
#
# 예전 코드:
#   roe_prem  = 0.15 if f_roe >= 12.0 else -0.10
#   roic_prem = 0.10 if roic  >= 10.0 else -0.05
# → Forward ROE 11.9%면 목표가 -10%, 12.0%면 +15%. 0.1%p 차이로 25%p 점프하고,
#   ROE가 50%든 12%든 프리미엄이 똑같았습니다. compute_vol_penalty()·
#   _growth_pegy_score_ratio()와 완전히 같은 계열의 문제라 같은 방식으로 고칩니다.
#
# 새 방식: 기준선(자본비용 수준) 중심의 '절대거리 선형 스케일링 + 윈저라이즈'.
#   - 기준선(ROE 12% / ROIC 10%)에서 정확히 0.0
#   - 기준선 위로 UPSIDE_RANGE_PCT(+18%p)까지 선형 증가해 최대 +MAX
#   - 기준선 아래로 DOWNSIDE_RANGE_PCT(-12%p)까지 선형 감소해 최소 -MAX(하락 폭)
#   - 그 밖은 윈저라이즈(더 극단이어도 프리미엄이 무한정 커지지 않음)
# 최대/최소 프리미엄 폭(+0.15 / -0.10, +0.10 / -0.05)은 ENGINEERING_SPEC §5-2에
# 명시된 기존 값을 그대로 유지합니다 — 바뀌는 건 '절벽이냐 경사냐'뿐입니다.
#
# 상단 범위(+18%p → ROE 30%)의 근거: 국내 상장사 중 ROE 30%를 지속하는 기업은
# 극소수(상위 1~2%)라, 그 이상은 추가 프리미엄을 줘도 변별력이 없습니다.
# 하단 범위(-12%p → ROE 0%)의 근거: ROE 0%는 손익분기점으로, 그 아래(적자)는
# 어차피 별도의 적자 컷오프에서 처리되므로 프리미엄 스케일을 더 늘릴 이유가 없습니다.
# =========================================================
ROE_PREMIUM_MAX = 0.15            # SPEC §5-2 기존 상한 유지
ROE_PREMIUM_MIN = -0.10           # SPEC §5-2 기존 하한 유지
ROE_PREMIUM_UPSIDE_RANGE_PCT = 18.0    # 기준선 +18%p(=ROE 30%)에서 최대 프리미엄
ROE_PREMIUM_DOWNSIDE_RANGE_PCT = 12.0  # 기준선 -12%p(=ROE 0%)에서 최대 디스카운트

# 2026-08-29 재감사 M4: ROIC 프리미엄 상수/함수는 제거했습니다. 이 파일은 ROIC 원천
# 데이터(영업이익·투하자본)를 수집하지 않아 roic 가 코드 어디에서도 None 외의 값으로
# 대입된 적이 없고, compute_roic_premium() 은 항상 0.0 만 반환하는 죽은 경로였습니다.
# (미국 쪽은 실제로 ROIC를 수집하므로 utils/scoring_us.py 의 ROIC 프리미엄은 살아 있습니다.)


def _linear_premium(value, baseline, up_range, down_range, prem_max, prem_min):
    """
    value가 baseline에서 얼마나 떨어져 있는지에 '비례'해 prem_min~prem_max 사이의
    프리미엄을 선형 배분하고, 범위를 벗어나면 윈저라이즈(clip)합니다.
    value가 None이면(실측 없음) 0.0 — 프리미엄을 적용할 근거가 없으므로 중립.
    """
    if value is None:
        return 0.0
    diff = value - baseline
    if diff >= 0:
        ratio = min(diff / up_range, 1.0)
        return round(ratio * prem_max, 4)
    ratio = min(-diff / down_range, 1.0)
    return round(ratio * prem_min, 4)


def compute_roe_premium(f_roe):
    """Forward ROE(%) → 목표가 품질 프리미엄(-0.10 ~ +0.15). 실측 없으면 0.0(중립)."""
    return _linear_premium(
        f_roe, ROE_PREMIUM_BASELINE_PCT,
        ROE_PREMIUM_UPSIDE_RANGE_PCT, ROE_PREMIUM_DOWNSIDE_RANGE_PCT,
        ROE_PREMIUM_MAX, ROE_PREMIUM_MIN
    )


def fetch_recent_volatility(code):
    """
    최근 VOL_WINDOW 영업일 일간수익률 표준편차(%)를 '실제 주가 시계열'로 산출합니다.
    조회/계산이 불가능하면 절대 임의값을 만들지 않고 None 을 반환합니다.
    (구 버전의 `code_hash % 3` 가짜 변동성 판정 로직을 완전히 대체)
    """
    if not HAS_FDR:
        return None
    try:
        end_dt = _now_kst()
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


KR_TICKER_MASTER_FILENAME = "kr_ticker_master.json"


def run_kr_ticker_master_collector(data_dir=None):
    """
    2026-08-11 오너 요청(TASK_HISTORY #83) — "내 성적표" 모듈에서 코스피 시가총액 상위 200
    **밖** 종목(코스닥 포함, ETF 포함)도 이름만으로 찾을 수 있게 하는 보조 조회용 전체
    상장종목 코드↔이름 목록을 만듭니다.

    ⚠️ 이 파일에는 **가격·밸류에이션이 전혀 없습니다** — 그건 여전히 위 run_kospi200_collector()가
    만드는 상위 200 스냅샷에만 있습니다. 이 목록은 오직 "이 이름이 실제로 어떤 종목코드인가"만
    정직하게 알려주는 용도이고(§0-1: 지어내지 않기 — 실제 상장사 목록만), 유니버스 밖 종목의
    현재가는 여전히 "현재가 없음"으로 정직하게 표시됩니다.

    코스피 200 수집(가격 크롤링 20~30분)과 완전히 분리된, FinanceDataReader의 **구조화 상장종목
    목록 1~2회 호출**뿐이라 훨씬 가볍습니다. 실패해도(FDR API 변경·일시 장애 등) 예외를 밖으로
    던지지 않고 그냥 건너뜁니다 — 이 보조 기능 하나 때문에 매일의 핵심 수집(코스피 200 밸류에이션)이
    막히면 안 되기 때문입니다.

    ⚠️ **미검증 주의**: 이 함수는 샌드박스에 네트워크가 없어 FinanceDataReader 실제 응답으로
    검증하지 못했습니다(코드는 `_load_outstanding_shares_lookup()`의 기존 방어적 컬럼 감지
    패턴을 그대로 따름). 처음 실행 후 GitHub Actions 로그에서 "[전체 상장종목 목록]" 줄로
    실제 컬럼명·건수를 확인해야 합니다(과거 `utils/krx_openapi.py`도 같은 방식으로 검증함).

    `data_dir`: 테스트에서 실제 저장소 data/ 폴더를 건드리지 않고 임시 폴더로 리다이렉트할 때만
    씁니다(운영 시에는 항상 None → 이 파일과 같은 경로의 data/, 기존 run_kospi200_collector()와
    동일한 기본 경로 규칙).
    """
    if not HAS_FDR:
        print("⚠️ [전체 상장종목 목록] FinanceDataReader 미설치 — 건너뜁니다(핵심 수집엔 영향 없음)")
        return None

    entries = {}

    def _ingest(df, source_label, type_label):
        if df is None or not hasattr(df, "columns"):
            print(f"⚠️ [전체 상장종목 목록] {source_label} 응답이 비어있거나 형식이 다릅니다")
            return 0
        code_col = next((c for c in ("Code", "Symbol", "Ticker") if c in df.columns), None)
        name_col = next((c for c in ("Name", "Name_KR") if c in df.columns), None)
        market_col = next((c for c in ("Market", "Dept") if c in df.columns), None)
        if code_col is None or name_col is None:
            print(f"⚠️ [전체 상장종목 목록] {source_label} 컬럼 구조가 예상과 다릅니다: {list(df.columns)}")
            return 0
        cols = [code_col, name_col] + ([market_col] if market_col else [])
        added = 0
        for _, row in df[cols].dropna(subset=[code_col, name_col]).iterrows():
            code = str(row[code_col]).strip()
            name = str(row[name_col]).strip()
            if not code or not name:
                continue
            market_value = str(row[market_col]).strip() if market_col and pd.notna(row.get(market_col)) else None
            # ⚠️ 여기서는 6자리 zfill 등 코드 정규화를 하지 않습니다 — 읽는 쪽(utils/scorecard_db.py의
            # build_universe_index → normalize_ticker)이 이미 그 정규화를 담당합니다(코스피 200
            # 스냅샷도 같은 방식). 수집기(공개 저장소 코드)가 "내 성적표" 모듈 내부 함수를 몰라도
            # 되도록 두 영역의 의존 방향을 한쪽으로만 유지하기 위함입니다.
            entries[code] = {"code": code, "name": name, "market": market_value, "type": type_label}
            added += 1
        print(f"  [전체 상장종목 목록] {source_label} {added}건 반영(컬럼: code={code_col}, name={name_col}, market={market_col})")
        return added

    try:
        _ingest(fdr.StockListing('KRX'), "StockListing('KRX') (코스피+코스닥 주식)", "STOCK")
    except Exception as e:
        print(f"⚠️ [전체 상장종목 목록] StockListing('KRX') 실패: {e}")

    try:
        _ingest(fdr.StockListing('ETF/KR'), "StockListing('ETF/KR') (국내 ETF)", "ETF")
    except Exception as e:
        print(f"⚠️ [전체 상장종목 목록] StockListing('ETF/KR') 실패: {e}")

    if not entries:
        print("⚠️ [전체 상장종목 목록] 수집된 종목이 0건이라 파일을 만들지 않습니다(기존 파일 유지)")
        return None

    resolved_data_dir = data_dir or os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(resolved_data_dir, exist_ok=True)
    json_path = os.path.join(resolved_data_dir, KR_TICKER_MASTER_FILENAME)
    payload = {
        "metadata": {
            "generated_at": _now_kst().strftime("%Y-%m-%d %H:%M"),
            "source": "FinanceDataReader StockListing('KRX') + StockListing('ETF/KR')",
            "count": len(entries),
            "description": "코스피+코스닥+국내ETF 전체 상장종목 코드↔이름 목록 — 가격/밸류에이션 없음, 이름 검색 보조용",
        },
        "stocks": list(entries.values()),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[전체 상장종목 목록] {len(entries)}건 저장 완료 -> {json_path}")
    return json_path


# =============================================================================
# 코스피+코스닥 전 종목 종가 수집기 (2026-08-11, "내 성적표" 유니버스 밖 종목 현재가 보조용)
# =============================================================================
KR_ALL_MARKET_PRICES_FILENAME = "kr_all_market_prices.json"


def _fetch_naver_market_sum_page(sosok, page):
    """
    네이버 금융 '시가총액 순위' 한 페이지(sosok=0 코스피/1 코스닥, 페이지당 최대 50종목)를
    받아 (코드, 이름, 종가) 튜플 리스트로 파싱합니다.

    ⚠️ fetch_kospi200_real_market_data()와 같은 페이지·같은 표 구조를 쓰지만, 여기는
    ETF/펀드 필터링을 하지 않고 순위 컷도 없습니다 — "전 종목(ETF 포함) 종가"가 목적이라
    코스피 200 랭킹용 필터링 로직과는 목적이 다릅니다.

    반환: (rows, error) — 성공하면 error=None, 실패(재시도 소진)하면 rows=[]와 에러 메시지.
    """
    url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    last_error = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.select_one('table.type_2')
            if table is None:
                last_error = "시가총액 표(table.type_2)를 찾지 못함"
                time.sleep(1.5 * (attempt + 1))
                continue

            rows = []
            for r in table.select('tr'):
                cols = r.select('td')
                if len(cols) < 3:
                    continue
                name_elem = cols[1].select_one('a')
                if not name_elem:
                    continue
                name = name_elem.text.strip()
                href = name_elem.get('href', '')
                code = href.split('code=')[-1] if 'code=' in href else ''
                try:
                    price = float(cols[2].text.strip().replace(',', ''))
                except ValueError:
                    price = 0.0
                if price <= 0 or not code:
                    continue
                rows.append((code, name, price))
            return rows, None
        except Exception as e:
            last_error = str(e)
            time.sleep(1.5 * (attempt + 1))
    return [], last_error


def run_kr_all_market_prices_collector(data_dir=None, max_pages_per_market=120):
    """
    코스피(sosok=0)+코스닥(sosok=1) 전 종목(ETF 포함)의 현재가만 네이버 금융 시가총액 순위
    페이지를 끝까지 페이지네이션하며 모아 `data/kr_all_market_prices.json`으로 저장합니다.

    ⚠️ §0-1: 이 파일은 "종목코드↔이름↔현재가"만 담습니다. PEGY/퀀트 밸류에이션은 여전히
    기존 상위 200 유니버스 안에서만 제공됩니다 — 이건 "내 성적표"에서 유니버스 밖 종목이
    계속 "현재가 없음"으로만 뜨던 걸 줄이기 위한 보조 목적입니다.

    ⚠️ `fetch_kospi200_real_market_data()`(코스피 200 랭킹용)와 달리 순위 무결성이 필요
    없으므로, 페이지 하나가 재시도 끝에 실패해도 그 페이지만 건너뛰고 계속 진행합니다
    (중간 50종목이 이번 회차에 빠질 뿐, 전체를 중단하지 않음 — 어차피 다음 실행 때 다시
    시도되고, 실패한 종목은 그냥 "이번엔 갱신 안 됨"일 뿐 잘못된 값이 저장되지 않습니다).
    정상 응답인데 종목이 0개인 페이지를 만나면 그 시장의 마지막 페이지로 보고 멈춥니다.
    `max_pages_per_market`은 그 판정이 실패했을 때(예: 응답 형식이 계속 바뀌는 경우)
    무한 루프를 막는 안전장치입니다.
    """
    entries = {}
    market_labels = {0: "KOSPI", 1: "KOSDAQ"}
    any_market_succeeded = False

    for sosok, market_label in market_labels.items():
        page = 1
        market_had_success = False
        failed_page_count = 0
        while page <= max_pages_per_market:
            rows, error = _fetch_naver_market_sum_page(sosok, page)
            if error is not None and not rows:
                failed_page_count += 1
                print(f"⚠️ [전 종목 종가] {market_label} {page}페이지 수집 실패({error}) — 이 페이지만 건너뜁니다")
                page += 1
                time.sleep(random.uniform(2.0, 3.0))
                continue
            if not rows:
                # 정상 응답인데 0건 = 이 시장의 마지막 페이지를 지났다고 판단하고 종료
                break
            for code, name, price in rows:
                entries[code] = {"code": code, "name": name, "price": price, "market": market_label}
            market_had_success = True
            page += 1
            time.sleep(random.uniform(2.0, 3.0))

        if market_had_success:
            any_market_succeeded = True
        print(f"[전 종목 종가] {market_label} 수집 완료(실패 페이지 {failed_page_count}건 건너뜀) — 누적 {len(entries)}건")

    if not any_market_succeeded:
        print("⚠️ [전 종목 종가] 코스피·코스닥 둘 다 수집 실패 — 파일을 만들지 않습니다(기존 파일 유지)")
        return None

    resolved_data_dir = data_dir or os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(resolved_data_dir, exist_ok=True)
    json_path = os.path.join(resolved_data_dir, KR_ALL_MARKET_PRICES_FILENAME)
    payload = {
        "metadata": {
            "generated_at": _now_kst().strftime("%Y-%m-%d %H:%M"),
            "source": "네이버 금융 시가총액 순위 페이지(finance.naver.com/sise/sise_market_sum.naver) 전체 페이지",
            "count": len(entries),
            "description": "코스피+코스닥 전 종목(ETF 포함) 현재가 — 밸류에이션 없음, 유니버스 밖 종목 현재가 표시 보조용",
        },
        "stocks": list(entries.values()),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[전 종목 종가] {len(entries)}건 저장 완료 -> {json_path}")
    return json_path


def _empty_item_info(error_msg):
    """종목 상세 수집 실패 시 반환 구조 (모든 수치는 None = '데이터 없음').

    ⚠️ 2026-08-29 재감사 H1: 이 dict의 키 집합은 정상 반환 dict와 **완전히 동일**해야 합니다.
    예전엔 `div_yield_row_found` 등이 빠져 있어, 소비부가 `item["div_yield_row_found"]` 처럼
    직접 접근하면 실패 경로에서만 KeyError가 났습니다. 이제 이 함수는 페이지 요청 자체가
    실패한 경우(응답 없음/상태코드 이상)에만 쓰이며, 파싱 도중 일부만 실패한 경우는
    fetch_naver_item_dps_and_eps() 가 이미 구한 값을 그대로 살려서 반환합니다.
    """
    return {
        "t_per": None, "t_eps": None, "f_per": None, "f_eps": None,
        "div_yield": None, "dps": None, "outstanding_shares": None,
        "t_pbr": None, "ev_ebitda": None, "f_roe": None, "raw_period": None,
        # 2026-08-06 2차 감사 1-4: '무배당 확정'과 '수집 실패'를 절대 같은 값으로 섞지 않습니다.
        "dps_status": "not_collected",
        "dps_inherited_from": None,
        "div_yield_row_found": False,
        "div_yield_row_explicit_na": False,
        "errors": [error_msg]
    }


# =============================================================================
# EV/EBITDA 서브 요청(navercomp.wisereport.co.kr) 서킷브레이커 — 2026-08-27 신설.
#
# 🔴 배경(오너 요청, 500종목 확대 첫 실전 실행에서 발견): 이 도메인은 finance.naver.com과
# 완전히 다른 사이트라 별도로 접속 상태가 나빠질 수 있는데, 재시도 로직이 없어 실패해도
# 종목당 정확히 한 번(최대 10초 타임아웃 + 1.5초 사전 대기 = 최대 11.5초)만 날립니다.
# 문제는 "한 번씩"이 500종목만큼 쌓인다는 것 — 2026-08-27 첫 500종목 실행에서 500개 중
# 333개(66.6%)가 연결 타임아웃으로 실패했고, 이게 전체 실행시간(1시간 44분)의 대부분을
# 차지한 것으로 추정됩니다.
#
# 해결: 재시도를 늘리는 게 아니라 반대로 "가망 없으면 빨리 포기하기"입니다. 연속
# _EV_EBITDA_FAILURE_THRESHOLD 번 실패하면, 이번 실행에서는 이 서브 요청 자체를 건너뛰고
# (=값을 지어내지 않고 그냥 None, §0-1) 상대 서버로 요청을 아예 안 보냅니다 — 남은 종목
# 전부에 시도했다면 나갔을 요청 수보다 훨씬 적게 나가므로, 상대 서버 입장에서는 부담이
# 늘어나는 게 아니라 줄어듭니다. 프로세스가 GitHub Actions 배치로 매번 새로 뜨므로
# 이 상태는 이번 실행 한 번에만 유효합니다(다음 날 실행은 처음부터 다시 시도).
# =============================================================================
_EV_EBITDA_FAILURE_THRESHOLD = 8
_ev_ebitda_circuit = {"consecutive_failures": 0, "open": False, "skipped_count": 0}


def fetch_naver_item_dps_and_eps(code, ticker_types=None):
    """
    네이버 증권 종목 상세 페이지(item/main.naver)의 우측 Investment Info 스냅샷 및
    주요 재무제표 표에서 TIMEFRAME_KEYWORDS 사전을 기반으로 동적 키워드 헤더 타겟팅을 적용합니다.
    (위치 고정 인덱스 iloc[:, 2] 전면 금지, 100% 범용 동적 수집)

    반환: dict — 파싱하지 못한 항목은 반드시 None 이며, 실패 사유는 errors 리스트에 누적됩니다.
    f_roe: "주요재무제표" 표의 연간 추정(E) 컬럼(예: 2026.12(E))에서 뽑은 Forward ROE 컨센서스.
    (2026-08-06 추가 — 진단 로그로 존재 확인 후 실제 추출 로직으로 전환. 추가 크롤링 요청 없음.)

    ticker_types: 2026-08-29 재감사 H12. 우선주 DPS를 보통주에서 상속할 때, 추측으로 만든
    부모 코드가 실제로 마스터 목록에 존재하는 보통주(type == "STOCK")인지 검증하는 데 씁니다.
    None이면 모듈 캐시(_get_ticker_types_cached())를 씁니다.

    ⚠️ 2026-08-29 재감사 H1: 파싱 구획(aside 스냅샷 / 재무제표 / EV/EBITDA / 우선주 상속)마다
    자기 try/except를 두어, 한 구획이 실패해도 나머지 구획이 이미 구한 값은 그대로 살립니다.
    예전엔 하나의 광역 try 가 전부를 감싸고 있어서, 재무제표 표 하나가 없으면 aside에서 이미
    정상적으로 읽은 PER/EPS/상장주식수까지 통째로 버려졌습니다(부분 성공 폐기).
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

    # =========================================================
    # 2026-08-29 재감사 H1: 반환용 변수를 전부 여기서 미리 초기화합니다.
    # 어느 파싱 구획에서 실패하든, 그 전까지 성공한 값은 자동으로 보존됩니다.
    # =========================================================
    t_per, t_eps, f_per, f_eps, div_yield = None, None, None, None, None
    t_pbr, ev_ebitda, f_roe = None, None, None
    raw_period = None          # 실제 파싱한 헤더에서 판정한 수집 기간 (검증 1단계 입력)
    outstanding_shares = None
    parsed_dps = None
    # 기본값은 항상 '수집 실패'입니다 — 아래에서 실제로 확인했을 때만 상태를 올립니다.
    dps_status = "not_collected"
    dps_inherited_from = None
    # 2026-08-06 2차 감사 1-4: 배당수익률 '행 자체가 있었는지'를 기록해 둡니다.
    # 행이 있는데 숫자가 없으면(N/A) '무배당'이고, 행 자체가 없으면 '수집 실패'입니다.
    div_yield_row_found = False
    # 2026-08-29 재감사 H3: '행이 있었다'와 '행이 있는데 값이 명시적으로 비어 있었다(N/A)'는
    # 전혀 다른 사실입니다. 무배당 확정 근거로 쓸 수 있는 건 후자뿐입니다.
    div_yield_row_explicit_na = False
    # 2026-08-29 재감사 H2: DPS 셀 파싱 오류가 한 번이라도 있었으면 '무배당 확정'으로
    # 승격하지 않습니다(파싱 실패를 '배당 없음'이라는 실측 사실로 둔갑시키지 않음).
    dps_cell_parse_error = False
    errors = []

    try:
        soup = BeautifulSoup(res.text, 'html.parser')

        # 1. 1차 출처: 우측 Investment Info 공식 스냅샷
        aside = soup.select_one('div.aside_invest_info')
        # =========================================================
        # 2026-08-06 2차 감사 1-1: 정규식에 `-?`를 추가해 마이너스 부호를 캡처합니다.
        # 네이버는 적자 기업의 PER·EPS를 음수로 표기하는데(예: "-49.26배 l -6,851원"),
        # 예전 정규식 r'([\d\.,]+)배...'는 앞의 '-'를 그냥 버려서 적자 기업 24종목이
        # 전부 흑자(양수 PER·EPS)로 둔갑했습니다. 산티체크(price/eps≈per)는 부호가
        # 양쪽 다 날아가 항상 통과했기 때문에 검증 하네스도 못 잡았습니다.
        # =========================================================
        per_eps_pattern = r'(-?[\d\.,]+)배\s*l\s*(-?[\d\.,]+)원'
        # -------------------------------------------------------------
        # 구획 A: aside 스냅샷 파싱 (2026-08-29 재감사 H1 — 자기 try/except)
        # 실패해도 이 구획이 만드는 값만 초기값(None/False)으로 남기고, 재무제표·
        # EV/EBITDA·우선주 상속 등 나머지 구획은 그대로 이어서 실행합니다.
        # -------------------------------------------------------------
        try:
            if aside:
                for tr in aside.find_all('tr'):
                    text = tr.text.strip().replace('\n', ' ')
                    if 'PERlEPS' in text and '추정' not in text and '동일업종' not in text:
                        per_match = re.search(per_eps_pattern, text)
                        if per_match:
                            t_per = float(per_match.group(1).replace(',', ''))
                            t_eps = int(float(per_match.group(2).replace(',', '')))
                            # 실제 헤더 라벨에서 기간을 판정 (하드코딩 "TTM" 전달 금지)
                            label_match = re.match(r'^(.*?)\s*-?[\d\.,]+배', text)
                            raw_label = label_match.group(1).strip() if label_match else text
                            if re.search(r'\(\d{4}\.\d{2}\)', raw_label):
                                # 네이버의 'PER|EPS(YYYY.MM)' 는 해당 분기까지의 최근 4분기 합산(TTM) 지표
                                raw_period = "TTM"
                            else:
                                raw_period = DataValidator.classify_header_timeframe(raw_label)
                    elif '추정PERlEPS' in text:
                        per_match = re.search(per_eps_pattern, text)
                        if per_match:
                            f_per = float(per_match.group(1).replace(',', ''))
                            f_eps = int(float(per_match.group(2).replace(',', '')))
                    elif 'PBRlBPS' in text:
                        # BPS(자본총계)가 음수인 자본잠식 기업은 PBR도 음수로 표기되므로 부호를 보존합니다.
                        pbr_match = re.search(r'(-?[\d\.,]+)배', text)
                        if pbr_match:
                            t_pbr = pbr_match.group(1).replace(',', '')
                    elif '배당수익률' in text:
                        div_yield_row_found = True
                        yield_match = re.search(r'([\d\.,]+)%', text)
                        if yield_match:
                            div_yield = float(yield_match.group(1).replace(',', ''))
                        else:
                            # 2026-08-29 재감사 H3: 행은 있는데 숫자가 없다(N/A 등)는
                            # '명시적으로 배당수익률이 비어 있다'는 뜻입니다. 행 존재
                            # 여부(div_yield_row_found)만으로는 이걸 구분할 수 없어,
                            # 무배당 확정 근거로 쓸 수 있는 플래그를 따로 둡니다.
                            div_yield_row_explicit_na = True
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
        except Exception as _aside_err:
            errors.append(f"aside 투자정보 스냅샷 파싱 실패: {_aside_err} — 이 구획 값만 미수집, 나머지는 계속 진행")

        # -------------------------------------------------------------
        # 구획 B: 주요재무제표 파싱 (2026-08-29 재감사 H1 — 자기 try/except)
        # pd.read_html() 은 표가 하나도 없으면 ValueError 를 던집니다. 예전엔 그게
        # 함수 전체의 광역 except 로 튀어올라 aside에서 이미 읽은 PER/EPS/PBR/
        # 상장주식수까지 통째로 버려졌습니다. 이제 이 구획이 만드는 값
        # (f_roe / dps / dps_status)만 미수집으로 남고 나머지는 계속 진행합니다.
        # -------------------------------------------------------------
        try:
            # 2. 2차 출처: 주요 재무제표 동적 키워드 타겟팅 (하드코딩 및 iloc 인덱스 금지)
            dfs = pd.read_html(res.text, encoding='euc-kr')
            fin_df_list = [d for d in dfs if ('매출액' in str(d) or '영업이익' in str(d) or '주당배당금' in str(d))]
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

                # =========================================================
                # 2026-08-06 2차 감사 1-4: 배당 수집 결과를 3가지 상태로 명확히 구분합니다.
                #   collected            : 재무제표에서 양수 DPS를 실제로 읽음
                #   no_dividend_confirmed: '주당배당금' 행을 찾았고 연간 컬럼이 전부 '-'/0 → 무배당 확정
                #   not_collected        : 행/연간컬럼 자체를 못 찾음 → 값을 모르는 상태
                # 예전에는 이 셋이 전부 dps=0 / "no_dividend_or_not_collected" 하나로 뭉개져서,
                # 수집 실패한 종목이 "실측된 저배당"으로 20점 만점 중 3점을 받고 있었습니다.
                # =========================================================
                dps_row_found = False
                dps_all_annual_cells_blank = True
                for i, row in fin_df.iterrows():
                    row_str = ' '.join([str(x) for x in row.values])
                    if '주당배당금' in row_str and parsed_dps is None:
                        dps_row_found = True
                        for col_i in reversed(annual_cols):
                            try:
                                v_str = str(row.values[col_i]).replace(',', '').strip()
                                # 네이버는 배당이 없는 해에 셀을 '-'로 표시합니다. 이건 파싱 실패가
                                # 아니라 "배당 없음"이라는 뜻이므로, 에러로 기록하지 않고 조용히 건너뜁니다.
                                if v_str in ('', 'nan', '-', 'ㅡ', '−'):
                                    continue
                                v = float(v_str)
                                dps_all_annual_cells_blank = False   # 숫자 셀을 실제로 읽었음
                                if v > 0:
                                    parsed_dps = int(v)
                                    break
                            except (ValueError, TypeError, IndexError) as e:
                                # 2026-08-29 재감사 H2: 여기서 예외가 나면 그 셀은 '읽지 못한'
                                # 것이지 '비어 있는' 것이 아닙니다. 예전엔 이 경우에도
                                # dps_all_annual_cells_blank 가 True 로 남아 파싱 실패가
                                # '무배당 확정'이라는 실측 사실로 승격됐습니다.
                                dps_cell_parse_error = True
                                errors.append(f"DPS 셀 파싱 실패(col={col_i}): {e}")

                if parsed_dps is not None and parsed_dps > 0:
                    dps_status = "collected"
                elif dps_cell_parse_error:
                    # 2026-08-29 재감사 H2: 셀 파싱 오류가 하나라도 있었으면 무배당 확정 불가.
                    dps_status = "not_collected"
                    errors.append("DPS 셀 파싱 오류가 있어 무배당 확정 불가 — 미수집(not_collected) 처리")
                elif dps_row_found and annual_cols and dps_all_annual_cells_blank:
                    # 연간 컬럼을 다 훑었는데 전부 '-' → 네이버 표기상 "배당 없음" 확정
                    dps_status = "no_dividend_confirmed"
                elif dps_row_found and annual_cols:
                    # 숫자는 있었는데 전부 0 이하 → 이것도 무배당 확정
                    dps_status = "no_dividend_confirmed"
                else:
                    dps_status = "not_collected"
                    errors.append("주당배당금(DPS) 행/연간 컬럼을 찾지 못했습니다 — 배당 미수집(무배당과 구분)")
        except Exception as _fin_err:
            errors.append(f"주요재무제표 파싱 실패: {_fin_err} — DPS/Forward ROE 미수집, 나머지는 계속 진행")

        # EV/EBITDA (Naver WiseReport) 추가 스크래핑
        # 2026-08-27 신설 — 서킷브레이커: 이 도메인이 연속으로 응답을 안 하면(연결 타임아웃 등)
        # 남은 종목은 요청 자체를 건너뜁니다. 값은 원래도 못 구한 것과 동일하게 None(§0-1)이고,
        # 재시도를 늘리는 게 아니라 "가망 없으면 빨리 포기"라 상대 서버 요청 수는 오히려 줄어듭니다
        # (모듈 상단 `_ev_ebitda_circuit` 주석 참고).
        if _ev_ebitda_circuit["open"]:
            _ev_ebitda_circuit["skipped_count"] += 1
        else:
            time.sleep(1.5) # 서버 부하 방지
            try:
                res_ev = requests.get(f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}", timeout=10)
                _ev_ebitda_circuit["consecutive_failures"] = 0  # 응답을 받았으면(표 파싱 결과와 무관) 연결 자체는 살아있는 것
                if res_ev.status_code == 200:
                    ev_dfs = pd.read_html(res_ev.text)
                    # =========================================================
                    # 2026-08-06 2차 감사 1-6: `iloc[row_idx, 1]` 고정 위치 인덱스 제거
                    # (SPEC §2-1 위반). 위레포트 표는 연도 컬럼 개수가 종목/시점마다 달라서
                    # "무조건 2번째 칸"이 최신 연도라는 보장이 없습니다. 이제 헤더를
                    # DataValidator.classify_header_timeframe()으로 분류해 '연간 실적' 컬럼만
                    # 고른 뒤 가장 최근 것을 쓰고, 헤더 분류에 실패하면 지어내지 않고
                    # 미수집(None)으로 남깁니다.
                    # =========================================================
                    for df in ev_dfs:
                        if 'EV/EBITDA' not in str(df):
                            continue
                        annual_ev_cols = [
                            i for i, col in enumerate(df.columns)
                            if DataValidator.classify_header_timeframe(col) in ("TTM", "ANNUAL_TTM", "ANNUAL_EST")
                        ]
                        if not annual_ev_cols:
                            errors.append("EV/EBITDA 표 헤더 기간 분류 실패 → 위치 인덱스 폴백 없이 미수집 처리")
                            break
                        for row_idx in range(len(df)):
                            if 'EV/EBITDA' not in str(df.iloc[row_idx, 0]):
                                continue
                            for col_i in reversed(annual_ev_cols):
                                try:
                                    cell = df.iloc[row_idx, col_i]
                                    val = str(cell).replace(',', '').strip()
                                    if pd.isna(cell) or val in ('', 'nan', '-', 'ㅡ', '−'):
                                        continue
                                    float(val)   # 숫자로 해석되는지만 확인 (문자열 원본 유지)
                                    ev_ebitda = val
                                    break
                                except (ValueError, TypeError, IndexError):
                                    continue
                            break
                        break
            except Exception as e:
                print("EV_EBITDA FETCH_ERROR:", e)
                errors.append(f"EV/EBITDA 수집 실패: {e}")
                _ev_ebitda_circuit["consecutive_failures"] += 1
                if _ev_ebitda_circuit["consecutive_failures"] >= _EV_EBITDA_FAILURE_THRESHOLD:
                    _ev_ebitda_circuit["open"] = True
                    print(
                        f"⚡ EV/EBITDA 데이터 소스(navercomp.wisereport.co.kr) 연속 "
                        f"{_EV_EBITDA_FAILURE_THRESHOLD}회 연결 실패 — 이번 실행에서는 남은 종목의 "
                        "EV/EBITDA 요청을 건너뜁니다(재시도 강화가 아니라 빨리 포기 — 상대 서버 "
                        "요청 수는 오히려 줄어듭니다)."
                    )

        # =========================================================
        # 우선주 (Preferred Shares e.g. 00680K 미래에셋증권2우B) 배당금 보정
        # ⚠️ 2026-08-06 2차 감사 1-7: 보통주에서 상속받은 값이라는 사실을 반드시
        # 마킹합니다. 예전엔 아무 표시 없이 parsed_dps에 그대로 넣어서, 화면에서는
        # "이 우선주의 실측 DPS"처럼 보였습니다(우선주는 보통주보다 배당이 높은 게
        # 일반적이라 실제로 과소평가되는 값입니다).
        # =========================================================
        # ⚠️ 2026-08-29 재감사 H12: 부모 코드는 `code[:-1] + '0'` 으로 **추측**한 값입니다.
        # 예전엔 이 추측 코드를 검증 없이 그대로 크롤링해 DPS를 상속했습니다 — 그 코드가
        # 실제로는 다른 회사이거나 ETF여도 알 길이 없었습니다. 이제 마스터 목록에서
        # type == "STOCK" 으로 확인된 경우에만 상속합니다(확인 못 하면 상속하지 않고
        # not_collected 유지 — 값을 지어내지 않음, §0-1).
        try:
            if (parsed_dps is None or parsed_dps == 0) and code.endswith('K'):
                parent_code = code[:-1] + '0'
                types = ticker_types if ticker_types is not None else _get_ticker_types_cached()
                if types.get(parent_code) == "STOCK":
                    parent_info = fetch_naver_item_dps_and_eps(parent_code, ticker_types=types)
                    p_dps = parent_info.get("dps")
                    if p_dps and p_dps > 0:
                        parsed_dps = p_dps
                        dps_status = "inherited_from_common"
                        dps_inherited_from = parent_code
                        errors.append(f"우선주 DPS를 보통주({parent_code})에서 상속 — 실측 아님(우선주 배당은 통상 더 높음)")
                else:
                    errors.append(
                        f"우선주 DPS 상속 보류 — 추정 부모 코드({parent_code})가 마스터 목록의 "
                        f"보통주(STOCK)로 확인되지 않음(type={types.get(parent_code)!r})"
                    )
        except Exception as _pref_err:
            errors.append(f"우선주 DPS 상속 처리 실패: {_pref_err}")

    except Exception as e:
        # 최후 방어선: 위 개별 구획 try 들이 잡지 못한 완전히 예상 밖의 예외.
        # 함수 진입부에서 반환용 변수를 전부 초기화해 두었으므로, 여기까지 왔더라도
        # 그 시점까지 성공적으로 파싱된 값은 아래 반환 dict에 그대로 살아 있습니다.
        print("FETCH_ERROR:", e)
        import traceback
        traceback.print_exc()
        errors.append(f"종목 상세 파싱 예외: {e}")

    return {
        "t_per": t_per, "t_eps": t_eps, "f_per": f_per, "f_eps": f_eps,
        "div_yield": div_yield, "dps": parsed_dps,
        "outstanding_shares": outstanding_shares,
        "t_pbr": t_pbr, "ev_ebitda": ev_ebitda, "f_roe": f_roe,
        "raw_period": raw_period,
        "dps_status": dps_status,
        "dps_inherited_from": dps_inherited_from,
        "div_yield_row_found": div_yield_row_found,
        "div_yield_row_explicit_na": div_yield_row_explicit_na,
        "errors": errors
    }

def load_ticker_types(path=None):
    """반환: {code: "STOCK"|"ETF"|...} (data/kr_ticker_master.json 기준).
    파일이 없거나 읽기 실패하면 빈 dict를 반환합니다 (→ 아래 필터에서 전부 걸러짐,
    안전한 쪽으로 — "무엇인지 확인 못 한 종목은 통과시키지 않는다").

    2026-08-29(오푸스 감사 Top-5 #1): collector_indicator_kr.py::load_ticker_types() 와
    완전히 동일한 규약입니다 — 정답 코드가 이미 이 저장소에 있어 그대로 재사용합니다
    (§0-3-10, 검증된 코드를 새로 짜지 않음).
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "data", KR_TICKER_MASTER_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ {path} 를 읽지 못했습니다: {e}")
        return {}
    return {s["code"]: s.get("type") for s in data.get("stocks", []) if s.get("code")}


# 2026-08-29 재감사 H12: 우선주 부모 코드 검증용 캐시.
# fetch_naver_item_dps_and_eps() 가 종목마다 호출되므로, 마스터 파일을 매번 다시 읽지
# 않도록 이번 실행 동안 한 번만 읽어 재사용합니다(호출부가 ticker_types를 넘겨주면 그걸 우선).
_ticker_types_cache = {"loaded": False, "value": {}}


def get_ticker_master_generated_date(path=None):
    """data/kr_ticker_master.json 의 metadata.generated_at 앞 10글자(YYYY-MM-DD)만 돌려줍니다.
    파일이 없거나 못 읽으면 None(경고를 못 찍을 뿐, 별도 에러로 취급하지 않음).
    collector_indicator_kr.py::get_price_list_generated_date() 와 같은 규약입니다."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "data", KR_TICKER_MASTER_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        generated_at = data.get("metadata", {}).get("generated_at", "")
        return generated_at[:10] if generated_at else None
    except Exception:
        return None


def _warn_ticker_master_staleness():
    """2026-08-29 재감사 H6: 마스터 목록이 오늘 자가 아니면 한 줄 경고를 남깁니다.
    차단하지는 않습니다 — 기존 파일이라도 있으면 ETF 판정은 되고, 없는 것보다 낫습니다."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    generated_date = get_ticker_master_generated_date()
    if generated_date is None:
        print(f"  ⚠️ data/{KR_TICKER_MASTER_FILENAME} 을 읽지 못했습니다 — ETF 판정·우선주 부모 "
              "검증에 쓸 종목 타입을 확인할 수 없어, 확인 못 한 후보는 전부 걸러집니다(안전한 쪽으로).")
    elif generated_date != today_str:
        print(f"  ⚠️ data/{KR_TICKER_MASTER_FILENAME} 이 {generated_date}자 스냅샷입니다(오늘 "
              f"{today_str}과 다름) — 오늘 신규 상장/폐지된 종목은 ETF 판정·우선주 부모 검증에 "
              "반영되지 않습니다.")


def _get_ticker_types_cached():
    if not _ticker_types_cache["loaded"]:
        _ticker_types_cache["value"] = load_ticker_types()
        _ticker_types_cache["loaded"] = True
    return _ticker_types_cache["value"]


def extract_market_sum_column_indices(table):
    """
    네이버 시가총액 순위표(table.type_2)의 헤더 행에서 '현재가'/'PER'/'ROE' 열의 위치를
    **라벨로** 찾아 {"price": i, "per": j, "roe": k} 형태로 돌려줍니다.

    ⚠️ 2026-08-29 재감사 H4: 예전엔 cols[2](현재가)·cols[10](PER)·cols[11](ROE)로 위치를
    고정 인덱싱했습니다. 네이버가 컬럼을 하나만 넣거나 빼도 조용히 다른 숫자를 가격·PER·
    ROE로 읽어 들이고, 그 값이 그대로 순위·PEGY·목표가에 들어갑니다(SPEC §2-1 위치 인덱스
    금지 위반). collector_us_stocks.py 의 라벨 기반 추출과 같은 원칙으로 헤더에서 찾습니다.

    라벨을 못 찾은 필드는 **키 자체를 넣지 않습니다** — 호출부는 값을 지어내지 말고
    미수집(None)으로 처리해야 합니다(위치 인덱스 폴백 금지).
    """
    header_cells = []
    thead = table.select_one('thead')
    if thead is not None:
        header_row = thead.select_one('tr')
        if header_row is not None:
            header_cells = header_row.select('th, td')
    if not header_cells:
        # thead 가 없는 마크업 대비: 헤더 역할을 하는 첫 <th> 행을 찾습니다.
        for r in table.select('tr'):
            th_cells = r.select('th')
            if th_cells:
                header_cells = th_cells
                break

    indices = {}
    for i, cell in enumerate(header_cells):
        label = cell.get_text(strip=True).replace(' ', '')
        if not label:
            continue
        upper = label.upper()
        if "price" not in indices and '현재가' in label:
            indices["price"] = i
        if "per" not in indices and 'PER' in upper:
            indices["per"] = i
        if "roe" not in indices and 'ROE' in upper:
            indices["roe"] = i
    return indices


def _cell_float(cols, idx):
    """cols[idx] 를 float 로 파싱. 인덱스가 없거나(라벨 미발견) 범위를 벗어나거나
    숫자가 아니면 None — 절대 다른 열의 값으로 대체하지 않습니다."""
    if idx is None or idx >= len(cols):
        return None
    try:
        return float(cols[idx].text.strip().replace(',', ''))
    except (ValueError, AttributeError):
        return None


def fetch_kospi200_real_market_data():
    """
    네이버 증권 시가총액 순위 목록(sise_market_sum.naver)을 코스피(sosok=0)+코스닥(sosok=1)
    양쪽 다 실행 시점 기준으로 스크래핑합니다.

    🔴 2026-08-26(오너 요청 — "재무제표 읽기" 코스피 상위 200 → 코스피+코스닥 통합 상위 500
       확대, TASK_HISTORY #150 참고). 원래는 코스피(sosok=0)만 긁었는데, 이제 두 시장을 각각
       독립적으로 페이지네이션해서 모읍니다. 여기서 반환하는 리스트는 아직 "시장별" 순서로만
       정렬돼 있습니다(코스피 후보 전부 다음 코스닥 후보 전부) — **진짜 통합 순위는 이 함수
       밖에서 실제 시가총액을 계산해 다시 정렬**합니다(`_rank_candidates_by_market_cap()`
       참고, 네이버 순위 페이지엔 시가총액 숫자 컬럼이 없어 여기선 계산할 수 없음). 종목별
       dict 에 `"market": "KOSPI"/"KOSDAQ"` 필드를 새로 추가했습니다.
       페이지 파싱·ETF 필터링·재시도·실패 시 RuntimeError 로 중단하는 로직은 원래 코스피
       하나에만 쓰던 걸 시장마다 그대로 재사용합니다(검증된 코드를 새로 짜지 않음, §0-3-10)
       — 이 파일 아래쪽의 "전 종목 종가" 보조 수집기가 이미 같은 URL 패턴을 sosok=0/1
       양쪽으로 매일 실전에서 쓰고 있어 코스닥 페이지 자체는 이미 검증된 경로.
       ⚠️ 다만 코스닥 페이지도 코스피와 **완전히 같은 12컬럼 표 구조**(PER=10번째, ROE=11번째
       컬럼)인지는 이 샌드박스가 네이버에 접근할 수 없어 사전 실측하지 못했습니다 — 같은
       URL 템플릿(`sise_market_sum.naver?sosok=`)에 시장 값만 다른 것뿐이라 그럴 가능성이
       높지만, 이번 merge 이후 첫 실제 실행 로그(GitHub Actions)에서 확인 필요(§0-1).

    ⚠️ 주의: KRX가 공식 발표하는 "코스피 200 지수"/"코스닥 150 지수" 편입종목과는 다릅니다
    (공식 지수는 유동주식 시총·업종 안배·유동성 심사를 거쳐 리밸런싱됨). 이 프로젝트는
    단순 시가총액 순위 기준입니다. (ETF, ETN, 인덱스 펀드류 상품 완전 제외, 순수 개별
    기업 주식만)
    """
    # =========================================================
    # 2026-08-06 2차 감사 1-5: 페이지 수집 실패를 `continue`로 삼키면 순위가 조용히 밀립니다.
    # → 실패한 페이지를 기록해 두고, 필요한 순위 구간을 다 못 채운 채 실패가 하나라도
    #    있으면 RuntimeError로 수집을 중단합니다(기존 스냅샷 그대로 유지). 네트워크 일시
    #    오류로 매일 중단되는 일을 막기 위해 페이지 단위 재시도를 먼저 겁니다.
    # =========================================================
    page_retries = 3   # 페이지 단위 재시도 횟수 (일시적 네트워크 오류 흡수)
    # 통합 이탈선(575위, apply_hysteresis_buffer 기본값)을 시장별로 안전하게 커버하기 위한
    # 여유치. 코스피/코스닥 실제 구성비를 몰라도 이 정도면 안전합니다 — 코스닥이 통합
    # top575에 700개나 기여하려면 산술적으로 코스피가 -125개를 기여해야 하는 모순이라,
    # 700은 어느 한쪽 시장이 낼 수 있는 최댓값보다도 넉넉한 상한선입니다. 실제 두 시장의
    # 진짜 구성비는 이번 merge 이후 첫 실행 로그에서 확인 필요(§0-1).
    target_candidates_per_market = 700
    max_pages_per_market = 25   # 700 / 50 = 14페이지 + ETF필터링·파싱실패 여유(안전 상한)

    # 2026-08-29(오푸스 감사 Top-5 #1): ETF/ETN 여부를 종목명 키워드로 "짐작"하지 않고
    # data/kr_ticker_master.json(FinanceDataReader 공식 상장종목 목록)로 확정합니다.
    # 시장 루프 밖에서 한 번만 로드(페이지마다 다시 읽지 않음).
    ticker_types = load_ticker_types()
    if not ticker_types:
        print("⚠️ data/kr_ticker_master.json 을 읽지 못해 ticker_types 가 비어 있습니다 "
              "— 이번 수집에서는 종목 타입을 확인할 수 없는 모든 후보가 걸러집니다(안전한 쪽으로).")

    all_stocks_raw = []
    all_failed_pages = []

    for market_label, sosok in (("KOSPI", 0), ("KOSDAQ", 1)):
        stocks_raw = []
        failed_pages = []

        for page in range(1, max_pages_per_market + 1):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            table = None
            last_error = None
            for attempt in range(page_retries):
                try:
                    res = requests.get(url, headers=headers, timeout=5)
                    if res.status_code != 200:
                        last_error = f"HTTP {res.status_code}"
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    table = soup.select_one('table.type_2')
                    if table is None:
                        last_error = "시가총액 표(table.type_2)를 찾지 못함"
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    break
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1.5 * (attempt + 1))

            if table is None:
                print(f"🚨 {market_label} 시가총액 {page}페이지 수집 실패({last_error}) — 순위 구간이 비어 순위가 밀릴 수 있습니다.")
                failed_pages.append({"market": market_label, "page": page, "error": last_error})
                time.sleep(random.uniform(2.0, 3.0))
                continue

            # 2026-08-29 재감사 H4: 헤더 라벨로 열 위치를 판정합니다. 표는 페이지마다 다시
            # 로드되므로 페이지마다 확인합니다(비용이 무시할 수준이고, 같은 시장 안에서
            # 구조가 달라지면 그것 자체가 이상 신호라 매번 보는 편이 안전합니다).
            col_idx = extract_market_sum_column_indices(table)
            if "price" not in col_idx:
                # 가격 열조차 라벨로 특정하지 못하면 이 페이지는 해석 불가입니다.
                # 위치 인덱스로 폴백해 엉뚱한 열을 가격으로 읽는 대신(§2-1) 페이지 실패로
                # 기록해, 아래 순위 무결성 검사가 "순위가 밀렸다"를 잡아내게 합니다.
                msg = "시가총액 표 헤더에서 '현재가' 열을 찾지 못함 — 위치 인덱스 폴백 금지"
                print(f"🚨 {market_label} 시가총액 {page}페이지 {msg}")
                failed_pages.append({"market": market_label, "page": page, "error": msg})
                time.sleep(random.uniform(2.0, 3.0))
                continue
            if "per" not in col_idx:
                print(f"⚠️ {market_label} {page}페이지: 헤더에서 'PER' 열을 찾지 못해 PER 미수집(None) 처리합니다.")
            if "roe" not in col_idx:
                print(f"⚠️ {market_label} {page}페이지: 헤더에서 'ROE' 열을 찾지 못해 ROE 미수집(None) 처리합니다.")

            try:
                rows = table.select('tr')
                for r in rows:
                    cols = r.select('td')
                    if len(cols) < 12:
                        continue

                    name_elem = cols[1].select_one('a')
                    if not name_elem:
                        continue

                    name = name_elem.text.strip()

                    href = name_elem.get('href', '')
                    code = href.split('code=')[-1] if 'code=' in href else ''

                    # ETF, ETN, 인덱스 펀드류 상품 걸러내기 (순수 개별 기업 주식만 순위 부여)
                    # 2026-08-29(오푸스 감사 Top-5 #1): 예전에는 종목명 키워드(브랜드명·상품유형
                    # 키워드·대문자+숫자 패턴)로 ETF 여부를 "짐작"했습니다. 이 방식은 "BNK금융지주"
                    # (순수 개별 기업 주식)를 "BNK" 키워드에 걸려 ETF로 오분류해 순위에서 빼버리는
                    # 등 오탐이 있었습니다. collector_indicator_kr.py / utils/indicator_universe.py
                    # 가 이미 data/kr_ticker_master.json(FinanceDataReader 공식 상장종목 목록,
                    # type="STOCK"/"ETF") 기반으로 이 문제를 정확히 해결해 둔 검증된 패턴이라
                    # 여기도 그대로 적용합니다(§0-3-10, 새 로직을 짜지 않음). ticker_types 에 없는
                    # (=STOCK 여부를 확인 못 한) 종목은 걸러집니다 — 안전한 쪽으로.
                    if ticker_types.get(code) != "STOCK":
                        continue

                    # 2026-08-29 재감사 H4: 전부 헤더 라벨로 찾은 인덱스를 씁니다.
                    parsed_price = _cell_float(cols, col_idx.get("price"))
                    price = parsed_price if parsed_price is not None else 0.0

                    # 시총 리스트의 PER/ROE 는 파싱 실패 시 임의 대체값을 넣지 않고 None 으로 둡니다.
                    t_per = _cell_float(cols, col_idx.get("per"))
                    t_roe = _cell_float(cols, col_idx.get("roe"))

                    if price <= 0 or not code:
                        continue

                    stocks_raw.append({
                        "name": name,
                        "code": code,
                        "price": price,
                        # 2026-08-06 2차 감사 1-1: abs() 제거 — 적자 기업의 마이너스 PER 부호를 보존합니다.
                        # (부호를 지우면 SKC 같은 적자 종목이 화면에 "PER 4.27배"로 표시돼 초저평가처럼 보입니다.)
                        "t_per": t_per if (t_per is not None and t_per != 0) else None,
                        "t_roe": t_roe,
                        # 2026-08-26 신설 — 통합 순위 계산·화면 표시용 시장 구분.
                        "market": market_label,
                    })

                    if len(stocks_raw) >= target_candidates_per_market:
                        break
                if len(stocks_raw) >= target_candidates_per_market:
                    break
            except Exception as e:
                print(f"🚨 {market_label} 시가총액 {page}페이지 파싱 중 예외: {e}")
                failed_pages.append({"market": market_label, "page": page, "error": f"파싱 예외: {e}"})

            time.sleep(random.uniform(2.0, 3.0))  # 매너 있는 크롤링을 위한 여유 있는 딜레이 (Polite Scraping)

        # =========================================================
        # 2026-08-06 2차 감사 1-5: 순위 무결성 검사(시장별로 그대로 적용).
        # 목표치만큼 채우지 못했는데 실패한 페이지가 있다면, "이 시장에 그만큼밖에 없다"가
        # 아니라 "중간 구간이 통째로 빈 채로 뒤가 당겨졌다"는 뜻이라 중단합니다.
        # =========================================================
        if failed_pages and len(stocks_raw) < target_candidates_per_market:
            detail = ", ".join(f"{fp['page']}페이지({fp['error']})" for fp in failed_pages)
            raise RuntimeError(
                f"{market_label} 시가총액 순위 페이지 수집 실패로 순위가 밀릴 수 있어 수집을 중단합니다 "
                f"(수집 {len(stocks_raw)}/{target_candidates_per_market}개, 실패: {detail}) — 기존 스냅샷 유지"
            )
        if failed_pages:
            print(f"⚠️ {market_label} 일부 페이지 수집 실패({len(failed_pages)}건)했으나 필요한 순위 구간은 모두 확보했습니다.")

        print(f"Successfully retrieved {len(stocks_raw)} real {market_label} candidates (market order, up to {target_candidates_per_market}).")
        all_stocks_raw.extend(stocks_raw)
        all_failed_pages.extend(failed_pages)

    # 여기서도 최종 컷을 하지 않습니다 — 아직 시장별 순서로만 합쳐진 상태이고, 실제 통합
    # 순위·히스테리시스 판정은 이 함수 밖(_rank_candidates_by_market_cap → apply_hysteresis_buffer)
    # 에서 정해집니다.
    return all_stocks_raw, all_failed_pages


def _rank_candidates_by_market_cap(candidates, shares_lookup):
    """
    코스피+코스닥이 합쳐진 후보 목록(아직 "시장별" 순서 — 코스피 후보 전부, 그다음 코스닥
    후보 전부)을 **실제 시가총액(현재가 × 상장주식수)** 기준 내림차순으로 다시 정렬합니다.

    🔴 2026-08-26 신설. 왜 이 계산이 필요한가: 네이버 '시가총액 순위' 페이지는 시장(코스피/
    코스닥) 안에서만 내림차순 정렬돼 있고 시가총액 숫자 자체는 이 페이지에서 긁어오지
    않습니다(PER·ROE만 긁음) — 그래서 두 시장 후보를 그냥 이어붙이면 "코스피 순서 +
    코스닥 순서"일 뿐 진짜 통합 순위가 아닙니다(예: 코스피 300위가 코스닥 50위보다 시가총액이
    작을 수 있음). 상장주식수는 `_load_outstanding_shares_lookup()`(FinanceDataReader
    구조화 데이터, 코스피+코스닥 전체 포함 — `utils/indicator_universe.py`도 같은 전제로
    이미 씀)로 이미 갖고 있으므로, 네이버에 없는 시가총액 컬럼을 새로 긁는 대신 이미 가진
    두 값(현재가·상장주식수)을 곱해 직접 계산합니다 — 이건 시가총액의 정의 그 자체라
    근사치가 아니라 정확한 값입니다.

    상장주식수를 못 찾은 종목(신규상장 직후 등 드문 경우)은 순위를 매길 근거가 없어 이번
    회차 통합 순위 계산에서 제외합니다 — 값을 지어내지 않습니다(§0-1). 종목 상세 수집 자체가
    막히는 게 아니라, 이번엔 그 종목만 통합 순위표에서 빠질 뿐입니다.

    candidates: fetch_kospi200_real_market_data()가 반환한, 아직 시장별 순서인 리스트.
    shares_lookup: _load_outstanding_shares_lookup()의 반환값({코드: 상장주식수}).
    반환: market_cap 내림차순으로 정렬된 새 리스트(각 dict에 "market_cap" 필드 추가).
    """
    ranked = []
    missing_shares = []
    for c in candidates:
        shares = shares_lookup.get(c["code"])
        if not shares or shares <= 0:
            missing_shares.append(c["code"])
            continue
        c["market_cap"] = c["price"] * shares
        ranked.append(c)

    if missing_shares:
        preview = ", ".join(missing_shares[:20])
        more = f" 외 {len(missing_shares) - 20}개" if len(missing_shares) > 20 else ""
        print(f"⚠️ 상장주식수를 찾지 못해 통합 순위 계산에서 제외된 종목 {len(missing_shares)}개: {preview}{more}")

    ranked.sort(key=lambda c: c["market_cap"], reverse=True)
    return ranked


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


def apply_hysteresis_buffer(candidates, previous_codes, entry_rank=500, exit_rank=575):
    """
    시가총액 순위 경계선에서 하루만 왔다갔다 해도 종목이 사라졌다 재등장하며
    히스토리 연속성이 깨지는 문제를 막기 위한 히스테리시스 버퍼.

    규칙(오너 확정, 2026-08-06 — 진입/이탈선 숫자만 2026-08-26에 200/230 → 500/575로 확대,
    비율은 그대로 유지: 이탈선 = 진입선 × 1.15):
    - 진입: 순위가 entry_rank(기본 500위) 이내로 처음 들어오면 추적 시작.
    - 유지: 어제 이미 추적 중이었던 종목은 exit_rank(기본 575위) 밖으로 완전히 밀려나야 추적 중단.
    - 화면 노출은 항상 정확히 entry_rank(기본 500개)만: 버퍼 구간(entry_rank+1~exit_rank위)에
      걸린 종목은 계속 수집·보강은 하되(요약 이력이 끊기지 않도록) `is_visible=False`로
      표시해 화면에서는 숨김.

    candidates: fetch_kospi200_real_market_data()가 반환하고 _rank_candidates_by_market_cap()이
    실제 시가총액(코스피+코스닥 통합) 내림차순으로 정렬한 순위 1위부터의 후보 리스트.
    previous_codes: 직전 수집분에 있었던 종목 코드 집합(_load_previously_tracked_codes 결과).
    반환: 실제로 이번 회차에 수집/보강할 종목 리스트(entry_rank~exit_rank개 사이,
    rank/is_visible 필드 포함).
    """
    tracked = []
    for idx, c in enumerate(candidates):
        rank = idx + 1
        if rank <= entry_rank:
            keep = True
        elif c.get("code") in previous_codes and rank <= exit_rank:
            keep = True  # 히스테리시스: 어제부터 추적 중이었고 아직 이탈선 안쪽 → 유지
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


def enrich_quant_metrics(stocks_raw, shares_lookup=None):
    """
    수집된(코스피+코스닥 통합, 최대 수백 개) 실데이터 종목에 네이버 공식 투자정보
    (aside_invest_info) 스냅샷 실데이터를 적용하여 Forward PEGY, 100점 만점 quant_score,
    ROE/ROIC 품질 가중 목표주가를 산출합니다.

    shares_lookup: 2026-08-26 신설. `run_kospi200_collector()`가 통합 순위 계산
    (`_rank_candidates_by_market_cap`) 때 이미 한 번 조회해둔 상장주식수 lookup을 그대로
    넘겨받아 FinanceDataReader를 중복 호출하지 않습니다. None이면(단독 호출·테스트 등)
    기존처럼 이 함수가 직접 조회합니다 — 하위 호환.
    """
    enriched_stocks = []

    # 상장주식수 1차 출처: FinanceDataReader 구조화 데이터 (한 번만 조회, 종목별 재조회 안 함)
    outstanding_shares_lookup = shares_lookup if shares_lookup is not None else _load_outstanding_shares_lookup()

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

        # =========================================================
        # 우선주 ROE 상속: ROE=0이고 우선주로 판별되면 보통주 ROE 사용
        # 우선주 판별 기준: 코드 끝자리 5(1우), 7(2우B), K, L
        # ⚠️ 2026-08-06 2차 감사 1-7: 상속받은 값은 '이 종목의 실측치'가 아니므로 반드시
        # 마킹합니다(예전엔 아무 흔적 없이 실측값처럼 저장·표시됐습니다).
        # =========================================================
        t_roe_inherited_from = None
        # ⚠️ 2026-08-29 재감사 L12: 이름 부분일치(`'우' in name`) 조건을 제거했습니다.
        # 한국 상장 종목코드 체계에서 우선주는 끝자리 5/7/K/L 로 판정하는 것이 표준이고,
        # 종목명에 '우'가 들어가는 보통주(예: '우리금융지주', '동우…')를 우선주로 오탐해
        # 엉뚱한 보통주 ROE를 상속시키는 부작용만 있었습니다.
        is_preferred = code[-1] in ('5', '7', 'K', 'L')
        if (t_roe is None or t_roe == 0) and is_preferred:
            parent_key = code[:5]
            inherited_roe = common_roe_lookup.get(parent_key)
            if inherited_roe:
                t_roe = inherited_roe
                t_roe_inherited_from = parent_key
                data_issues.append(
                    f"Trailing ROE를 같은 회사 보통주({parent_key}*)에서 상속 — 이 우선주의 실측치가 아님"
                )
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
        #
        # ⚠️ 2026-08-06 2차 감사 1-1: 이제 t_per / t_eps 에 마이너스 부호가 그대로 들어옵니다.
        # 적자 기업(PER<0 또는 EPS<0)은 "PER이 몇 배"라는 개념 자체가 성립하지 않으므로
        # (분모인 이익이 음수) Trailing 밸류에이션 계열(t_per / t_pegy / t_fair / 그레이엄)을
        # 전부 산출하지 않고 None으로 남깁니다. 값 자체는 is_trailing_loss·loss_evidence에
        # 사유와 함께 기록해 화면이 "적자 — 산출 불가"로 정직하게 표시할 수 있게 합니다.
        # =========================================================
        t_per_measured = n_t_per if n_t_per is not None else raw_per   # 부호 포함 원본
        loss_evidence = []
        if n_t_per is not None and n_t_per < 0:
            loss_evidence.append(f"Trailing PER {n_t_per}배(<0)")
        elif raw_per is not None and raw_per < 0:
            loss_evidence.append(f"Trailing PER {raw_per}배(<0)")
        if n_t_eps is not None and n_t_eps < 0:
            loss_evidence.append(f"Trailing EPS {n_t_eps:,}원(<0)")
        if t_roe is not None and t_roe < 0:
            loss_evidence.append(f"Trailing ROE {t_roe}%(<0)")
        is_trailing_loss = bool(loss_evidence)

        if t_per_measured is not None and t_per_measured > 0:
            t_per = t_per_measured
        elif is_trailing_loss:
            t_per = None
            data_issues.append(
                "적자 기업 — Trailing 밸류에이션(PER/PEGY/적정가/그레이엄) 산출 불가: "
                + ", ".join(loss_evidence)
            )
        else:
            t_per = None
            data_issues.append("Trailing PER 수집 실패")

        # Trailing EPS는 '실측값'이므로 음수라도 지우지 않고 그대로 보존합니다
        # (화면에는 마이너스 EPS가 그대로 보여야 적자 기업임을 알 수 있습니다).
        t_eps = n_t_eps if n_t_eps is not None else None
        t_eps_calculated = False
        t_eps_source = "naver_실측" if t_eps is not None else None
        if t_eps is None:
            data_issues.append("Trailing EPS 수집 실패")
            # 2026-08-05 추가: 대수적 역산 허용 예외 (ENGINEERING_SPEC.md §0-1 예시2-보충)
            # 조건: 실측 EPS를 어디서도 못 구했고, t_per·price 둘 다 실측값일 때만
            # EPS = 가격 ÷ PER 로 역산합니다. 반드시 계산값으로 마킹해서 실측값과 섞지 않습니다.
            # (적자 기업은 t_per 자체를 None으로 뒀으므로 여기서 역산되지 않습니다.)
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
        graham_is_financial_sector = any(kw in name for kw in FINANCIAL_SECTOR_NAME_KEYWORDS)
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

        # =========================================================
        # 2. 배당금(DPS)
        # ⚠️ 2026-08-06 2차 감사 1-4: 예전엔 "무배당"과 "수집 실패"를 둘 다 dps=0 /
        # dps_source="no_dividend_or_not_collected" 로 뭉갰습니다. 그 결과 배당 데이터를
        # 못 가져온 종목이 "실측된 저배당"으로 취급돼 주주환원 20점 만점 중 3점을 받았고,
        # sh_return=0 인 33종목 중 어느 것이 진짜 무배당인지 아무도 알 수 없었습니다.
        # 이제 상태를 명확히 분리합니다:
        #   naver_financial_statement / derived_from_div_yield / inherited_from_common
        #     → 값 있음(dps > 0)
        #   no_dividend_confirmed  → 실제로 배당이 없음이 확인됨 (dps=0, sh_return=0.0로 채점)
        #   not_collected          → 값을 모름 (dps=None, sh_return=None → 배점에서 자동 제외)
        # =========================================================
        item_dps_status = item.get("dps_status", "not_collected")
        div_yield_row_found = bool(item.get("div_yield_row_found"))
        div_yield_row_explicit_na = bool(item.get("div_yield_row_explicit_na"))
        dps_source = None
        dps_inherited_from = None
        if real_dps and real_dps > 0:
            dps = real_dps
            if item_dps_status == "inherited_from_common":
                dps_source = "inherited_from_common"
                dps_inherited_from = item.get("dps_inherited_from")
                data_issues.append(
                    f"DPS를 보통주({dps_inherited_from})에서 상속 — 이 우선주의 실측 배당금이 아님"
                )
            else:
                dps_source = "naver_financial_statement"
        elif n_div_yield and n_div_yield > 0 and price > 0:
            dps = int(price * (n_div_yield / 100.0))
            dps_source = "derived_from_div_yield"
        elif item_dps_status == "no_dividend_confirmed" and div_yield_row_explicit_na:
            # 재무제표 '주당배당금' 행을 실제로 확인했고 값이 없음 → 무배당 확정.
            # ⚠️ 2026-08-29 재감사 H3: 예전 조건은
            #   `item_dps_status == "no_dividend_confirmed" or div_yield_row_found`
            # 였습니다. div_yield_row_found 는 aside 표에 '배당수익률' 행이 **있기만 하면**
            # True 라(숫자가 있든 없든) 사실상 모든 종목에서 True 였고, or 로 묶여 있어
            # 재무제표를 못 읽은 종목까지 전부 '무배당 확정(dps=0)'으로 채점됐습니다.
            # 이제 ⓐ 재무제표에서 실제로 전부 비었음을 확인했고(H2 덕분에 파싱 오류가
            # 있으면 이 상태가 되지 않습니다) ⓑ 배당수익률 행도 명시적으로 비어 있을 때
            # (N/A) 두 근거가 모두 갖춰진 경우에만 무배당으로 확정합니다.
            dps = 0
            dps_source = "no_dividend_confirmed"
        else:
            dps = None
            dps_source = "not_collected"
            data_issues.append("배당(DPS·배당수익률) 미수집 — 무배당이 아니라 '값을 모름'이므로 배점에서 제외")

        # 배당수익률 (%) — 실측 우선. 수집 실패면 0%로 채우지 않고 None(=모름)으로 둡니다.
        if n_div_yield is not None and n_div_yield > 0:
            div_yield = n_div_yield
        elif dps is None:
            div_yield = None
        elif price > 0 and dps > 0:
            div_yield = dps / price * 100.0
        else:
            div_yield = 0.0

        # =========================================================
        # 주주환원율: 자사주 매입 공시를 수집하지 않으므로 '배당수익률'만 사용합니다.
        # (구 버전은 ROE 10% 이상이면 자사주 2.5%를 임의로 가산했고, 주가의 0.3%를
        #  자사주 매입액으로 가정해 총액을 부풀렸습니다 → 전부 제거)
        # =========================================================
        sh_yield = None if div_yield is None else round(div_yield, 2)
        if sh_yield is None:
            sh_return_basis = "배당 데이터 미수집 — 주주환원율 산출 불가 (0%로 간주하지 않음)"
        else:
            sh_return_basis = "배당수익률만 반영 (자사주 매입 공시 미수집)"

        # 총 배당 규모: 상장주식수가 검증을 통과했을 때만 산출. 실패 시 None + '데이터 없음'
        if dps is None:
            tot_dividend_krw = None
            tot_amt = "데이터 없음 (배당 정보 미수집)"
        elif outstanding_shares and outstanding_shares >= MIN_OUTSTANDING_SHARES and dps > 0:
            tot_dividend_krw = int(dps * outstanding_shares)
            tot_return_krw = int(tot_dividend_krw / 100000000)
            tot_amt = f"총 {tot_return_krw:,}억원 (배당 기준)"
        elif dps <= 0 and (div_yield or 0) <= 0:
            tot_dividend_krw = 0
            tot_amt = "무배당 (배당 공시 확인됨)"
        else:
            tot_dividend_krw = None
            tot_amt = "데이터 없음 (상장주식수 미확보)"

        # =========================================================
        # Forward ROE / ROIC
        # 2026-08-06: Forward ROE는 네이버 "주요재무제표" 표의 연간 추정(E) 컬럼에서 실측
        # (fetch_naver_item_dps_and_eps 에서 이미 파싱 — 추가 크롤링 요청 없음). 컨센서스
        # 커버리지가 없는 종목은 그대로 None → '데이터 없음' 유지(지어내지 않음).
        # (구 버전: f_roe = t_roe × 1.12, 실패 시 8.5 상수 — 전부 제거됨)
        # 2026-08-29 재감사 M4: ROIC는 원천 데이터(영업이익·투하자본)를 아예 수집하지 않아
        # 값이 항상 None 이었습니다. 항상 0을 반환하는 프리미엄 계산과, 모든 종목에 무조건
        # 붙던 "ROIC 컨센서스 미수집" data_issues 문자열(= 500종목 전부에 같은 문구)을
        # 함께 제거했습니다. 실제로 수집하게 되면 그때 다시 넣습니다(§0-1).
        # =========================================================
        f_roe = item.get("f_roe")
        if f_roe is None:
            data_issues.append("Forward ROE 컨센서스 미제공 (애널리스트 커버리지 없음)")

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
        if idx < YFINANCE_CROSS_CHECK_TOP_N and HAS_YFINANCE and f_per:
            # ⚠️ 2026-08-29 재감사 M5: 예전엔 접미사가 `.KS`(코스피)로 하드코딩돼 있었습니다.
            # 2026-08-26에 수집 대상이 코스닥까지 넓어졌는데, 코스닥 종목을 `.KS`로 조회하면
            # yfinance가 다른 종목을 주거나(동일 코드가 양쪽에 있을 경우) 빈 값을 줍니다.
            # market 이 없어 확실하지 않으면 원래 기본값이던 코스피(.KS)로 시도합니다.
            yf_suffix = ".KQ" if s.get("market") == "KOSDAQ" else ".KS"
            try:
                ticker = yf.Ticker(f"{code}{yf_suffix}")
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
        # g_eff = 성장률 + 주주환원율. 주주환원율을 '모르는' 종목(sh_yield=None)에 0을
        # 대입하면 그건 "무배당이라고 단정"하는 것과 같으므로(§0-1 위반), 산출하지 않습니다.
        if growth is not None and sh_yield is not None:
            # geff(트레일링용)는 캡을 걸지 않습니다 — SPEC §5-1의 t_pegy 공식이 원래도
            # `growth + sh_yield`를 그대로(캡 없이) 쓰도록 설계돼 있고, 실측 트레일링
            # 값이라 미래 추정처럼 완화할 근거가 없습니다(utils/constants.py 1-1 참고).
            geff = growth + sh_yield
            # 2026-08-30(TASK_HISTORY #175/#176) — Forward 쪽(growth_eff → f_pegy·목표가)
            # 에만 SPEC §5-1의 2중 캡을 적용합니다. 이전엔 이 캡이 코스피 경로에
            # 아예 빠져 있어(미국 경로엔 있었음) 고성장 종목의 실효성장률이 부풀려져
            # PEGY가 인위적으로 낮아지고(=저평가처럼 보임) 있었습니다 — 오너 확인
            # 결과 의도된 시장별 차이가 아니라 놓친 구현으로 확정, 이번에 반영합니다.
            growth_capped = min(growth, GROWTH_CAP_PCT)
            sh_return_capped = min(sh_yield, SH_RETURN_CAP_PCT)
            g_eff_capped_value = min(growth_capped + sh_return_capped, GEFF_TOTAL_CAP_PCT)
            g_eff_capped = bool(
                growth > GROWTH_CAP_PCT
                or sh_yield > SH_RETURN_CAP_PCT
                or (growth_capped + sh_return_capped) > GEFF_TOTAL_CAP_PCT
            )
            g_eff_uncapped = round(geff, 2)
            growth_eff = g_eff_capped_value / vol_penalty
        else:
            geff = None
            growth_eff = None
            g_eff_capped = False
            g_eff_uncapped = None
            if growth is not None and sh_yield is None:
                data_issues.append("실효성장률(g_eff) 산출 불가 — 주주환원율(배당) 미수집")

        # =========================================================
        # 2026-08-06 2차 감사 1-9: `max(growth_eff, 0.1)` 바닥값 제거.
        # 0.1은 근거 없는 상수였고, 실효성장률이 0.02%인 종목의 PEGY를 5배 낮게(=저평가처럼)
        # 만들어버렸습니다. 이제 분모가 PEGY_MIN_DENOMINATOR_PCT 미만이면 "PEGY 공식이
        # 성립하지 않는 구간"으로 보고 아예 산출하지 않습니다(지어내지 않음).
        # 0.5%p 근거: 실효성장률이 0.5%p 미만이면 PEGY = PER/0.005 이상이 되어 어떤 종목이든
        # 수백~수천의 무의미한 값이 나옵니다. 이 구간은 사실상 '무성장'이므로 역성장/무성장
        # 컷오프(scoring.py Guardrail 1)가 처리하는 게 맞습니다.
        # =========================================================
        f_pegy = round(f_per / growth_eff, 2) if (
            f_per and growth_eff and growth_eff >= PEGY_MIN_DENOMINATOR_PCT
        ) else None
        t_pegy = round(t_per / geff, 2) if (
            t_per and geff and geff >= PEGY_MIN_DENOMINATOR_PCT
        ) else None
        if f_per and growth_eff is not None and 0 < growth_eff < PEGY_MIN_DENOMINATOR_PCT:
            data_issues.append(
                f"Forward PEGY 산출 생략 (실효성장률 {growth_eff:.2f}%p < {PEGY_MIN_DENOMINATOR_PCT}%p — 사실상 무성장)"
            )

        # =========================================================
        # 목표주가(f_target) — ENGINEERING_SPEC §5-2 와 동일하게 캡 적용.
        # f_roe 가 None 이면 품질 프리미엄을 적용할 근거가 없으므로 0으로 둡니다.
        # 2026-08-06 2차 감사 1-2: 프리미엄을 절벽(if >= 12.0)이 아니라 기준선 대비
        # 절대거리 선형 스케일링으로 산출합니다(compute_roe_premium 주석 참고).
        # =========================================================
        roe_prem = compute_roe_premium(f_roe)

        # =========================================================
        # 2026-08-06 2차 감사 1-3: 캡에 걸렸다는 흔적을 반드시 남깁니다.
        # 예전엔 200종목 중 40종목의 f_target이 정확히 price×2.5였고, 화면에는 전부
        # 똑같은 "+150.0% 상승 여력"이 초록 바로 표시됐습니다. 그 숫자는 계산 결과가
        # 아니라 캡 상수 그 자체인데, 어디에도 그 사실이 남지 않아 아무도 알 수 없었습니다.
        # =========================================================
        f_target_capped = False
        f_target_cap_reason = None
        f_target_uncapped = None
        target_per_capped = False
        if f_eps and growth_eff and growth_eff > 0:
            target_pegy = 1.0 * (1.0 + roe_prem)
            raw_target_per = target_pegy * growth_eff
            target_per = min(raw_target_per, TARGET_PER_CAP)          # SPEC §5-2: 25배 Cap
            target_per_capped = raw_target_per > TARGET_PER_CAP
            raw_target = f_eps * target_per
            price_cap_value = price * TARGET_PRICE_CAP_MULTIPLE       # SPEC §5-2: 현재가 2.5배 Cap
            f_target_uncapped = int(raw_target)
            if raw_target > price_cap_value:
                f_target = int(price_cap_value)
                f_target_capped = True
                f_target_cap_reason = (
                    f"현재가 {TARGET_PRICE_CAP_MULTIPLE}배 상한에 도달 "
                    f"(캡 미적용 산출값 {int(raw_target):,}원) — 추정 신뢰구간 밖이라 상한값으로 절단"
                )
            else:
                f_target = int(raw_target)
            if target_per_capped:
                f_target_cap_reason = (
                    (f_target_cap_reason + " / ") if f_target_cap_reason else ""
                ) + f"목표 PER {TARGET_PER_CAP}배 상한 적용 (캡 미적용 {raw_target_per:.1f}배)"
            if f_target_capped or target_per_capped:
                data_issues.append(f"목표주가 캡 적용: {f_target_cap_reason}")
        else:
            target_per = None
            f_target = None

        # Trailing 적정가(t_fair) — 적자 기업(t_eps<=0)은 산출하지 않습니다.
        t_fair_capped = False
        t_fair_uncapped = None
        if t_eps and t_eps > 0 and geff and geff > 0:
            raw_t_fair = t_eps * min(geff, TARGET_PER_CAP)
            price_cap_value = price * TARGET_PRICE_CAP_MULTIPLE
            t_fair_uncapped = int(raw_t_fair)
            if raw_t_fair > price_cap_value:
                t_fair = int(price_cap_value)
                t_fair_capped = True
            else:
                t_fair = int(raw_t_fair)
        else:
            t_fair = None

        # =========================================================
        # 착시 저평가(value trap)
        # ⚠️ 2026-08-06 2차 감사 1-8: 예전엔 `t_roe < 8.0` 이진 판정이었고, 화면 설명은
        # "ROE<8% 또는 ROIC<6%"라고 적혀 있었는데 ROIC는 수집조차 하지 않았습니다.
        # → ① 기준값을 utils/constants.py 단일 출처로 옮기고 근거를 명시,
        #    ② 이진 플래그 대신 '얼마나 낮은지'를 함께 기록해 화면이 강도를 표시할 수 있게,
        #    ③ ROIC 미수집 사실을 판정 근거 문자열에 그대로 노출(화면 설명과 코드 일치).
        # =========================================================
        if t_roe is None:
            value_trap = False
            value_trap_basis = "판정 불가 (Trailing ROE 미수집)"
            value_trap_severity = None
        elif t_roe < VALUE_TRAP_ROE_PCT:
            value_trap = True
            value_trap_severity = round(VALUE_TRAP_ROE_PCT - t_roe, 2)   # 기준선 미달 폭(%p)
            value_trap_basis = (
                f"Trailing ROE {t_roe}% < 기준선 {VALUE_TRAP_ROE_PCT}% "
                f"(기준선 대비 {value_trap_severity}%p 미달) · ROIC는 원천 데이터 미수집으로 판정에서 제외"
            )
        else:
            value_trap = False
            value_trap_severity = 0.0
            value_trap_basis = (
                f"Trailing ROE {t_roe}% ≥ 기준선 {VALUE_TRAP_ROE_PCT}% "
                "· ROIC는 원천 데이터 미수집으로 판정에서 제외"
            )

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
            # 화면(공개 페이지)에 보여줄지 여부. 500위 이내면 True, 히스테리시스 버퍼 구간(501~575위)에서
            # "이탈 확정 전까지 계속 수집만 하고 화면에는 숨김" 상태면 False.
            "is_visible": s.get("is_visible", True),
            # 2026-08-26 신설: 코스피/코스닥 통합 500종목 확대(오너 요청)로 어느 시장 소속인지
            # 화면에 라벨로 보여달라는 후속 요청. fetch_kospi200_real_market_data()가 이미
            # 채워둔 값을 rank/is_visible과 같은 방식으로 그대로 이어받습니다(계산 없음, §0-1).
            # 구버전 스냅샷 등 이 필드가 없는 입력은 None(=알 수 없음)으로 정직하게 둡니다.
            "market": s.get("market"),
            "market_cap": s.get("market_cap"),
            "name": name,
            "code": code,
            "price": price,
            "t_roe": t_roe,
            # 우선주가 보통주 ROE를 상속받은 경우의 출처(실측 아님) — 2차 감사 1-7
            "t_roe_inherited_from": t_roe_inherited_from,
            "f_roe": f_roe,
            "dps": dps,
            "dps_source": dps_source,
            "dps_inherited_from": dps_inherited_from,
            "outstanding_shares": outstanding_shares,
            "total_dividend_krw": tot_dividend_krw,
            "return_total": tot_amt,
            "t_per": t_per,
            # 부호까지 보존한 원본 Trailing PER(적자면 음수). 화면에서 '적자 근거'로 노출합니다.
            "t_per_measured": t_per_measured,
            "is_trailing_loss": is_trailing_loss,
            "loss_evidence": loss_evidence,
            "t_eps": t_eps,
            "t_eps_calculated": t_eps_calculated,
            "t_eps_source": t_eps_source,
            "graham_target": graham_target,
            "graham_is_financial_sector": graham_is_financial_sector,
            "sh_return": sh_yield,
            "sh_return_basis": sh_return_basis,
            "t_pegy": t_pegy,
            "t_fair": t_fair,
            "t_fair_capped": t_fair_capped,
            "t_fair_uncapped": t_fair_uncapped,
            "f_per": f_per,
            "f_eps": f_eps,
            "growth": growth,
            "growth_source": growth_source,
            "f_pegy": f_pegy,
            # 2026-08-30(TASK_HISTORY #175/#176) — 실효성장률이 §5-1 2중 캡에 걸렸는지와
            # 캡을 적용하지 않은 원값. tests/test_stock_history.py의 FORBIDDEN_KEYS 정책이
            # 이미 이 두 필드명을 "카드가 실제로 읽는 필드"로 취급하고 있었습니다(2026-08-29
            # M-13, 미국 화면 기준) — 코스피 쪽만 이제 실제로 값을 채웁니다.
            "g_eff_capped": g_eff_capped,
            "g_eff_uncapped": g_eff_uncapped,
            "f_target": f_target,
            # 2차 감사 1-3: 목표가가 '계산 결과'가 아니라 '캡 상수'인지 여부와 그 사유
            "f_target_capped": f_target_capped,
            "f_target_cap_reason": f_target_cap_reason,
            "f_target_uncapped": f_target_uncapped,
            "target_per": round(target_per, 2) if target_per is not None else None,
            "target_per_capped": target_per_capped,
            "roe_premium": roe_prem,
            "vol": vol,
            "vol_std": vol_std,
            "vol_penalty": vol_penalty,
            "value_trap": value_trap,
            "value_trap_basis": value_trap_basis,
            "value_trap_severity": value_trap_severity,
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
            # 2차 감사 2-4: UI 표시 문자열("정상"/"데이터 없음") 파싱 대신 실측 수치를 그대로 넘깁니다.
            vol_std=stock_dict.get('vol_std'),
            vol_penalty=stock_dict.get('vol_penalty'),
            vol=stock_dict.get('vol'),
            f_per=stock_dict.get('f_per'),
            price=stock_dict.get('price'),
            f_target=stock_dict.get('f_target'),
            # 2차 감사 2-1: 캡 상수와 현재가를 비교하는 건 무의미하므로 교차검증 블록을 건너뜁니다.
            f_target_capped=stock_dict.get('f_target_capped', False),
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
        stock_dict["growth_score_capped"] = score_res.get("growth_score_capped", False)

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
        except Exception as e:
            # =========================================================
            # ⚠️ 2026-08-29 재감사 H5: 예전엔 `except Exception: history = []` 로 조용히
            # 넘어가 이 파일을 1행짜리 새 파일로 덮어썼습니다 — 누적 이력 전체가 로그
            # 한 줄 없이 사라지는 경로였습니다. 이제 손상된 파일을 백업해 두고 경고를
            # 남긴 뒤, 이번 실행에서는 **이력 갱신 자체를 건너뜁니다**. 스냅샷 저장은
            # 이 함수 호출 전에 이미 끝나 있으므로 핵심 수집 결과에는 영향이 없습니다.
            # (collector_dividend_payment_kr.py 의 read_payment_events() /
            #  DartPaymentFatalError 와 같은 원칙 — 못 읽은 채로 새로 쓰지 않는다.)
            # =========================================================
            backup_path = f"{history_path}.corrupt.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                os.replace(history_path, backup_path)
                moved = f" 손상 파일을 {backup_path} 로 백업했습니다."
            except Exception as be:
                moved = f" (손상 파일 백업도 실패: {be})"
            print(
                f"🚨 {history_path} 를 읽지 못했습니다({type(e).__name__}: {e})."
                f"{moved} 지금까지 쌓인 요약 이력을 덮어써 잃지 않도록 이번 실행에서는 "
                "이력 갱신을 건너뜁니다(스냅샷 저장은 이미 완료됨)."
            )
            return

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

    # =========================================================
    # 2026-08-29 재감사 M6: 중복 판정 입도를 **일 단위**로 맞춥니다.
    # meta_date 는 "YYYY-MM-DD HH:MM" 처럼 분 단위 문자열이라, 예전 비교
    # (`h.get("date") != meta_date`)는 같은 날 두 번 실행하면 서로 다른 값으로 보여
    # 하루에 여러 행이 쌓였습니다(종목별 시계열 이력 기록은 일 단위라 두 이력 파일의
    # 입도가 서로 달랐습니다). 과거 레코드가 분 단위 문자열로 저장돼 있어도 안전하도록
    # 비교할 때 양쪽 다 앞 10자리(YYYY-MM-DD)만 씁니다.
    # =========================================================
    def _day_key(value):
        return str(value)[:10] if value else ""

    new_record["collected_at"] = meta_date   # 분 단위 원본 타임스탬프는 별도 필드로 보존
    day = _day_key(meta_date)
    history = [h for h in history if _day_key(h.get("date")) != day]
    history.append(new_record)

    # 2026-08-29 재감사 H5: tmp → os.replace 원자적 교체.
    # (collector_dividend_payment_kr.py::_atomic_write_json() 와 같은 방식 —
    #  쓰다 만 파일이 남아 다음 실행에서 '손상 파일'이 되는 일을 막습니다.)
    tmp_path = f"{history_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, history_path)

    print(f"Updated PEGY summary history log: {new_record} -> {history_path}")

def run_kospi200_collector():
    """코스피+코스닥 통합 시가총액 상위 500 real 데이터 배치 수집 및 data/kospi200_pegy_latest.json 저장

    🔴 2026-08-26(오너 요청) — 코스피 단독 상위 200 → 코스피+코스닥 통합 상위 500으로 확대.
    파일명·JSON 키("kospi200_...")는 그대로 유지합니다(이 함수·파일을 참조하는 다른 모듈이
    20개 이상이라 이름 자체를 바꾸는 건 이번 범위에서 별도로 다루지 않음 — TASK_HISTORY #150
    참고). 실제 담기는 데이터만 코스피+코스닥 통합으로 바뀝니다.
    """
    print(f"[{_now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST] 코스피+코스닥 통합 시가총액 상위 500 100% 실데이터 수집 시작...")

    # 2026-08-29 재감사 L11: EV/EBITDA 서킷브레이커는 모듈 전역이라 같은 프로세스에서
    # 이 함수를 두 번 부르면 지난 실행의 열린 상태가 그대로 남습니다(테스트·배치 재실행).
    # 실행 단위로 초기 상태를 복원합니다.
    _ev_ebitda_circuit.clear()
    _ev_ebitda_circuit.update({"consecutive_failures": 0, "open": False, "skipped_count": 0})

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")

    # 히스테리시스 버퍼 판정을 위해 "어제 뭘 추적 중이었는지"를 오늘 파일을 덮어쓰기 전에 먼저 읽어둡니다.
    previous_codes = _load_previously_tracked_codes(json_path)

    # 2차 감사 1-5: 페이지 실패 정보를 함께 받아 메타데이터에 남깁니다.
    # (순위 구간이 비어 순위가 밀릴 수 있는 상황이면 여기까지 오지 못하고 RuntimeError로 중단됩니다.)
    candidates, failed_pages = fetch_kospi200_real_market_data()
    if not candidates:
        # 종목 목록조차 못 가져오면 기존 스냅샷을 건드리지 않고 명확히 실패시킵니다.
        raise RuntimeError("코스피+코스닥 시가총액 목록 스크래핑 실패 — 수집을 중단합니다 (기존 스냅샷 유지)")

    # 2026-08-26 신설 — 아직 "시장별" 순서로만 합쳐진 candidates를 실제 시가총액(현재가×
    # 상장주식수)으로 다시 정렬해 진짜 통합 순위를 만듭니다. 상장주식수 조회는 여기서 딱 한 번만
    # 하고(enrich_quant_metrics에도 그대로 넘겨써서 중복 조회 안 함), 코스피+코스닥 전체를
    # 커버하는 FinanceDataReader 구조화 데이터를 씁니다(_load_outstanding_shares_lookup 참고).
    shares_lookup = _load_outstanding_shares_lookup()
    candidates = _rank_candidates_by_market_cap(candidates, shares_lookup)
    if not candidates:
        raise RuntimeError("상장주식수 매칭 실패로 통합 순위를 계산할 종목이 0개입니다 — 수집을 중단합니다 (기존 스냅샷 유지)")

    # 히스테리시스 버퍼 적용: 진입 500위 / 이탈 575위. 화면 노출은 여전히 상위 500개만이고,
    # 501~575위 버퍼 구간 종목은 어제도 추적 중이었을 때만 "화면 비노출로 계속 수집"됩니다.
    tracked_stocks = apply_hysteresis_buffer(candidates, previous_codes)
    if not tracked_stocks:
        raise RuntimeError("히스테리시스 버퍼 적용 후 추적 대상 종목이 0개입니다 — 수집을 중단합니다 (기존 스냅샷 유지)")

    enriched_stocks = enrich_quant_metrics(tracked_stocks, shares_lookup=shares_lookup)

    # 공개 화면에는 is_visible(순위 500위 이내)인 종목만 노출됩니다. 품질 지표(검증 통과율 등)도
    # "화면에 실제로 보이는 500개" 기준으로 집계해야 배너 숫자가 사용자에게 의미가 있습니다.
    visible_stocks = [s for s in enriched_stocks if s.get("is_visible", True)]
    total_count = len(visible_stocks)
    tracked_count = len(enriched_stocks)
    hidden_buffer_count = tracked_count - total_count
    valid_stocks = [s for s in visible_stocks if s.get("is_valid") and not s.get("is_unverified")]
    failed_codes = [s["code"] for s in visible_stocks if not (s.get("is_valid") and not s.get("is_unverified"))]
    valid_ratio = (len(valid_stocks) / total_count) if total_count else 0.0

    # 2026-08-06 2차 감사 1-10: 0.95 하드코딩 → 근거 있는 상수(utils 상단 주석 참고)로 교체.
    # 실제 통과율이 구조적으로 0.85 안팎이라 예전 기준으로는 매일 무조건 DEGRADED였습니다.
    if total_count == 0:
        status = "FAILED"
    elif valid_ratio >= VALID_RATIO_SUCCESS:
        status = "SUCCESS"
    elif valid_ratio >= VALID_RATIO_DEGRADED:
        status = "DEGRADED"
    else:
        status = "FAILED"

    now_str = _now_kst().strftime("%Y-%m-%d %H:%M")
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
            # 2차 감사 1-5: 순위 출처가 불완전했는지 여부(뒤쪽 페이지 실패 등)를 그대로 남깁니다.
            "rank_source_incomplete": bool(failed_pages),
            "rank_source_failed_pages": failed_pages,
            # 2026-08-29 재감사 L11: 서킷브레이커가 열려 EV/EBITDA 요청을 건너뛴 종목 수.
            # 예전엔 이 카운터를 올리기만 하고 아무도 읽지 않아, "오늘 EV/EBITDA가 왜 이렇게
            # 많이 비었지?"를 사후에 확인할 방법이 없었습니다.
            "ev_ebitda_skipped_count": _ev_ebitda_circuit.get("skipped_count", 0),
            "ev_ebitda_circuit_open": bool(_ev_ebitda_circuit.get("open")),
            # 상태 판정에 쓴 임계값도 함께 저장해 나중에 "왜 DEGRADED였지?"를 추적할 수 있게 합니다.
            "valid_ratio_thresholds": {
                "success": VALID_RATIO_SUCCESS,
                "degraded": VALID_RATIO_DEGRADED
            },
            "description": (
                f"코스피+코스닥 통합 시가총액 상위 1위~{total_count}위 퀀트 스냅샷 "
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

    # ── 종목별 시계열 이력 누적 (2026-08-09 신설, TASK_HISTORY #64) ──────────────────
    # 여기까지 도달했다는 건 목록 스크래핑·히스테리시스·종목별 수집·스코어링·스냅샷 저장이
    # 예외 없이 끝났다는 뜻입니다(중간 실패는 위에서 RuntimeError 로 중단되어 이 줄에 오지
    # 못합니다). 그 위에 한 겹 더, status 가 FAILED 면 record_daily_history 가 스스로
    # 기록을 거부합니다 — 오염된 하루가 영구 이력에 박히면 되돌릴 수 없기 때문입니다(§0-1).
    #
    # ⚠️ 버퍼 구간(is_visible=False, 201~230위) 종목도 함께 기록합니다. 순위가 잠깐
    #    200위 밖으로 밀렸다고 그 종목의 시계열에 구멍이 나면 안 되기 때문입니다
    #    (몇 위였는지는 '시가총액 순위' 컬럼에 그대로 남습니다).
    #
    # ⚠️ 이력 기록이 실패해도 이미 저장된 스냅샷과 수집 결과는 건드리지 않습니다
    #    (수집 성공을 이력 파일 I/O 때문에 실패로 만들지 않음).
    try:
        history_result = record_daily_history(
            path=stock_history_path(KOSPI_HISTORY_FILENAME),
            stocks=enriched_stocks,
            date_str=_now_kst().strftime('%Y-%m-%d'),
            fields=KOSPI_HISTORY_FIELDS,
            status=status,
        )
        if history_result['recorded']:
            print(f"종목별 시계열 이력 누적: {history_result['reason']} -> {KOSPI_HISTORY_FILENAME}")
        else:
            print(f"⚠️ 종목별 시계열 이력 미기록: {history_result['reason']}")
    except Exception as e:
        print(f"⚠️ 종목별 시계열 이력 기록 실패(수집 결과에는 영향 없음): {e}")

    # ── 수집 결과 산티체크 (2026-08-30 신설, utils/data_sanity.py) ─────────────────
    # 위 저장이 **전부 끝난 뒤**에만 돕니다. 이 판정은 값을 하나도 고치거나 지우지 않고
    # "오늘 결과가 그럴듯한가"만 보고 data/kospi200_sanity.json 에 남깁니다(§0-1 —
    # 의심스러운 값도 그대로 두고 경고만 추가). 상태가 '의심/판정 오류'면
    # .github/workflows/watch_data_sanity.yml 이 디스코드로 알립니다.
    #
    # 핵심 컬럼으로 price·market_cap 만 고른 이유: 2026-08-29 자 스냅샷을 직접 세어 보니
    # 둘 다 결측 0.0%(507행 중 0건)였습니다. 반대로 t_per(19.3% 결측)·quant_score(24.7%)
    # 처럼 **정상적으로 자주 비는** 컬럼을 넣으면 매일 울려서 알람이 무의미해집니다.
    # 대상은 visible_stocks(정확히 500개로 고정)가 아니라 enriched_stocks 입니다 —
    # 고정된 수를 세면 '건수 급감'을 영영 못 잡습니다.
    data_sanity.check_dataset(
        "kospi200", enriched_stocks, ("price", "market_cap"),
        target_date=_now_kst().strftime('%Y-%m-%d'),
        level_fields=("price", "market_cap"),
        # 상태 파일은 이 실행이 스냅샷을 쓴 바로 그 디렉터리에 둡니다(위 data_dir).
        # 별도로 경로를 다시 계산하면 테스트가 임시 폴더로 우회시켰을 때 실제 data/ 를
        # 오염시키게 됩니다(§0-3-10 — 같은 경로를 두 곳에서 만들지 않기).
        data_dir=data_dir,
    )

    print(f"[{_now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST] 코스피+코스닥 통합 시가총액 순 {total_count}개(+버퍼 {hidden_buffer_count}개) 실데이터 저장 완료! -> {json_path}")
    return json_path

if __name__ == "__main__":
    # =========================================================
    # ⚠️ 2026-08-29 재감사 H6: 마스터 목록(kr_ticker_master.json)을 **먼저** 만듭니다.
    # 예전 순서는 코스피200 수집 → 마스터 목록 → 전 종목 종가 였습니다. 그런데 코스피200
    # 수집의 ETF 판정·우선주 부모 검증이 바로 그 마스터 파일을 읽으므로, 항상 '전날 파일'
    # 기준으로 판정하고 있었습니다(첫 실행에서는 파일이 아예 없어 전 종목이 걸러짐).
    # 이 보조 수집이 실패해도(FDR API 변경 등) 기존 파일이 있으면 그대로 쓰게 되므로
    # try/except 로 감싸 두는 기존 설계는 그대로 유지합니다(TASK_HISTORY #83).
    # =========================================================
    try:
        run_kr_ticker_master_collector()
    except Exception as e:
        print(f"⚠️ [전체 상장종목 목록] 수집 중 예외 발생(핵심 수집 결과에는 영향 없음): {e}")

    # 마스터 파일 신선도 확인 — 오늘 자가 아니면(생성 실패로 어제 파일이 남았거나 파일 없음)
    # ETF 판정·우선주 부모 검증이 낡은 목록 기준이라는 사실을 로그로 명시합니다
    # (collector_indicator_kr.py 의 유니버스 신선도 경고와 같은 취지).
    _warn_ticker_master_staleness()

    run_kospi200_collector()
    # 2026-08-11(TASK_HISTORY #84): 마찬가지로 핵심 수집과 완전히 독립 — 실패해도 위 두 단계
    # 결과는 그대로 유지됩니다. 페이지가 많아(코스피+코스닥 전체) 몇 분 더 걸립니다.
    try:
        run_kr_all_market_prices_collector()
    except Exception as e:
        print(f"⚠️ [전 종목 종가] 수집 중 예외 발생(핵심 수집 결과에는 영향 없음): {e}")
