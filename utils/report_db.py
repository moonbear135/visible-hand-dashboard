# utils/report_db.py
"""
📈 "리포트" 모듈 — 데이터 계층 단일 출처 (스냅샷 적재 배치 + 기간 집계 조회)

REPORT_WORK_ORDER.md 에 따라 만든 모듈입니다. 화면(`views/report_view.py`)과 배치
(`.github/workflows/scrape_report_snapshots.yml`)는 Supabase 호출과 기간 계산을 직접 하지
않고 **전부 이 모듈을 통해서만** 합니다("내 성적표"의 `utils/scorecard_db.py` 와 같은 계층 분리).

이 파일은 다섯 부분으로 나뉩니다.
    A. 기간(일/주/월/분기/반기/연) 경계 계산   — 순수 함수, 네트워크·DB 불필요
    B. 스냅샷 1행 만들기 / 기간 집계·판정      — 순수 함수, 네트워크·DB 불필요
    C. 벤치마크 조회 (코스피 CSV · 미국 지수 JSON) — **읽기 전용** 파일 접근
    D. Supabase 접근 (배치 쓰기 / 화면 읽기)
    E. 배치 진입점 (`python -m utils.report_db snapshot`)

-------------------------------------------------------------------------------
🔴 이 파일만 `service_role` 키를 씁니다 — 왜 그런지 반드시 읽고 복사하지 마세요
-------------------------------------------------------------------------------
"내 성적표"(`utils/scorecard_db.py`)는 **anon key + RLS** 만 씁니다. 사용자가 브라우저로
접속해 자기 데이터를 읽고 쓰는 구조라 그게 맞고, 그게 이 기능의 핵심 안전장치입니다.

리포트의 스냅샷 적재는 성격이 다릅니다. 사용자가 앱을 열지 않아도 **가입한 모든 사용자**의
그날 평가금액을 계산해 저장해야 합니다("어제보다 얼마 올랐나"를 나중에 보여주려면 과거
시점의 값이 실제로 저장돼 있어야 하니까요). RLS 는 설계상 "로그인한 그 사용자 본인" 행만
허용하므로 anon key 로는 이 일을 할 수 없습니다. 그래서 이 파일의 배치 함수만
`service_role` 키를 씁니다. 지켜야 할 것:

  · 키는 **GitHub Actions Secrets 에만** 등록합니다(`SUPABASE_SERVICE_ROLE_KEY`).
    **Streamlit Cloud Secrets(앱)에는 절대 넣지 않습니다** — 앱에 들어가는 순간 RLS 가
    통째로 무력화됩니다.
  · 그래서 이 파일은 키를 `st.secrets` 가 아니라 **환경변수에서만** 읽습니다
    (`_read_service_env()` — streamlit 을 아예 import 하지 않습니다).
  · 읽기는 전체 사용자 `holdings` 를 조회하지만, **쓰기는 스냅샷 테이블 한 곳뿐**입니다.
    이 파일에는 holdings/profiles 를 insert·update·delete 하는 코드가 없습니다.
  · 화면 쪽 조회(`fetch_user_snapshots`)는 기존과 똑같이 **anon key + 로그인 세션**을 쓰는
    클라이언트를 그대로 받아서 씁니다(이 파일이 화면용 클라이언트를 새로 만들지 않습니다).

-------------------------------------------------------------------------------
🧾 저장하는 표는 두 개이고, 둘은 같은 계산에서 나옵니다 (2026-08-13 오너 결정)
-------------------------------------------------------------------------------
  · `portfolio_daily_snapshots`   : 사용자 × 시장 × 거래일 = 1행 (그날 **합계**)
  · `portfolio_holding_snapshots` : 사용자 × 시장 × **종목** × 거래일 = 1행 (그날 **상세**)

오너 요청은 "종목별 일일 스냅샷까지 저장" + "데이터 품질관리 · 들쑥날쑥하면 안 됨" 이었습니다.
그래서 합계 표를 갈아엎지 않고 **덧붙였고**, 두 표가 어긋날 수 없게 계산 소스를 하나로
못 박았습니다 — `build_snapshot_rows_with_holdings()` 가 종목별 행을 먼저 만들고 **그 행들을
그대로 더해서** 합계 행을 만듭니다(합계를 따로 계산하는 코드가 이 파일에 없습니다).
기간 집계(`compute_period_report()`)는 예전 그대로 합계 표만 봅니다 — 기존 기능 무손상.

-------------------------------------------------------------------------------
⚠️ 지어내지 않기 (ENGINEERING_SPEC §0-1)
-------------------------------------------------------------------------------
  · 과거분을 소급 계산하지 않습니다. 기능을 켠 날부터 스냅샷이 쌓이고, 그 이전 구간은
    화면에서 "데이터 부족"으로 **정직하게, 주 컨텐츠로** 표시합니다(작업지시서 §3).
  · 현재가를 모르는 종목은 합계에 넣지 않고 몇 개가 빠졌는지를 함께 저장합니다
    (`priced_count` / `unpriced_count`). 0원으로 치지 않습니다.
  · 벤치마크가 없는 날은 NULL 로 두고 전날 값을 복사하지 않습니다(보간 금지).
  · 원화와 달러는 끝까지 분리합니다. 이 파일 어디에도 환율을 곱하는 코드가 없습니다.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

# ⚠️ "내 성적표" 데이터 계층의 **읽기 전용 재사용**입니다(작업지시서 §7 — 기존 파일을 고치지
#    않되 import 는 권장). 시장/통화 상수, 종목 평가, 가격 조회 함수를 그대로 씁니다:
#    스냅샷의 평가금액이 화면("내 성적표")에서 보이는 숫자와 **같은 계산**으로 나와야 하기
#    때문입니다(다른 함수로 두 번 구현하면 언젠가 반드시 어긋납니다).
from utils.scorecard_db import (
    MARKET_KR,
    MARKET_US,
    MARKETS,
    ScorecardError,
    currency_for_market,
    default_data_dir,
    evaluate_holding,
    load_kr_all_market_prices,
    load_snapshot_payload,
    load_universe_index,
    load_us_all_etf_prices,
    load_us_all_market_prices,
    make_price_lookup,
    normalize_market,
)


class ReportError(RuntimeError):
    """리포트 데이터 계층에서 사용자/로그에 그대로 보여줄 오류(조용히 삼키지 않습니다)."""


SNAPSHOTS_TABLE = "portfolio_daily_snapshots"
HOLDINGS_TABLE = "holdings"

# 🆕 종목별 일일 스냅샷 테이블 (2026-08-13 오너 결정 — sql/report_schema.sql §8).
#    합계 표(SNAPSHOTS_TABLE)를 대체하는 게 아니라 **나란히 덧붙인** 표입니다. 두 표는
#    `build_snapshot_rows_with_holdings()` 안에서 **같은 평가 결과 하나**로부터 함께
#    만들어지므로 서로 어긋날 수 없습니다(아래 그 함수의 주석 참고).
HOLDING_SNAPSHOTS_TABLE = "portfolio_holding_snapshots"

# 테이블이 아직 없는 DB(= 오너가 sql/report_schema.sql §8 을 실행하기 전)에서 배치가 통째로
# 죽지 않게 하려고 쓰는 표식. PostgREST 는 없는 테이블을 PGRST205 로 알려 주고, 메시지에
# 테이블 이름과 "schema cache" 를 그대로 실어 보냅니다.
#  ⚠️ 여기에 실행할 SQL 전문을 적어 두지 않았습니다 — 40줄짜리 CREATE TABLE 을 파이썬
#     문자열로 복사해 두면 sql/report_schema.sql 과 언젠가 어긋나고, 그 순간 오너는 서로
#     다른 두 개의 "정답"을 갖게 됩니다. 단일 출처는 .sql 파일 하나입니다.
HOLDING_TABLE_MISSING_MARKERS = (
    "pgrst205",
    "could not find the table",
    "schema cache",
    "does not exist",
    "relation",
)
# 🔬 "합계 = 종목별 합" 을 대조할 때 쓰는 허용오차 (원 / 달러 단위).
#    왜 0 이 아닌가 — 아래 `_sum_money()` 주석에 실측과 함께 적어 뒀습니다. 요약하면:
#    저장값은 소수점 6자리 십진수인데 파이썬은 그걸 2진 부동소수점(배정밀도)으로 다루고,
#    유효자릿수(15~17자리)를 넘는 큰 합계에서는 마지막 자리가 표현되지 않습니다(실측 최대
#    0.00005원 수준). 0.01(1원·1센트의 100분의 1)은 화면 표기 단위(원=정수, 달러=소수 2자리)
#    보다 훨씬 작아 **의미 있는 불일치는 전부 잡고**, 존재하지 않는 문제를 쫓지는 않습니다.
TOTAL_MATCH_TOLERANCE = 0.01

HOLDING_TABLE_SETUP_HINT = (
    "Supabase SQL Editor 에서 `sql/report_schema.sql` 전체를 다시 실행하세요 "
    "(§8 블록이 이 테이블을 만듭니다 — 여러 번 실행해도 안전하고, 기존 표·데이터는 "
    "건드리지 않습니다)."
)

# 🕐 "이 행의 가격은 몇 시 몇 분에 수집된 값인가"를 담는 컬럼 이름 (2026-08-13 오너 요청).
#    한국장(오후)과 미국장(한국시간 새벽)의 수집 시각이 달라서, 거래일(날짜)만으로는 리포트가
#    언제 시점의 종가로 만들어졌는지 알 수 없다는 피드백에서 나왔습니다.
#    값은 **수집기가 이미 적어 둔 한국시간 문자열을 그대로** 씁니다(앱이 시차를 직접 계산하지
#    않습니다). 문자열 하나로 충분한 이유: 스냅샷 행은 이미 `market` 으로 KR/US 가 나뉘어
#    있어서, 시장별 컬럼을 따로 둘 필요가 없습니다.
PRICE_STAMP_FIELD = "price_as_of_kst"

# 컬럼이 아직 없는 DB(= 오너가 ALTER 문을 실행하기 전)에서 배치가 통째로 죽지 않게 하려고
# 쓰는 표식. PostgREST 는 없는 컬럼을 보내면 PGRST204 와 함께 컬럼 이름을 그대로 알려 줍니다.
PRICE_STAMP_ALTER_SQL = (
    "alter table public.portfolio_daily_snapshots "
    f"add column if not exists {PRICE_STAMP_FIELD} text;"
)

# 화면에 상시 노출할 고지. "내 성적표"의 NO_FX_CONVERSION_NOTICE / NO_FEES_TAXES_NOTICE 와
# 같은 목적이며, 리포트 고유의 한계를 추가로 알립니다.
#
# ⚠️ 2026-08-13 (#114) — 두 문구를 **한 줄로 줄였습니다.** 오너 지적: "글자가 너무 많고
#    나하고 너하고 말하는 용어로 설명이 되어있고 다른 사람들이 이것을 볼 때 필요없는 내용이
#    너무 많은거 같아". 줄이면서 **뜻은 하나도 버리지 않았습니다** — 지운 것은 "v1 범위 밖"
#    같은 개발 로드맵 이야기와 "안내 문구가 함께 표시됩니다" 같은 화면 사용법 설명뿐이고,
#    숫자를 오해하게 둘 정보(단순 비교라는 점 / 매매가 섞인다는 점 / 역산하지 않는다는 점)는
#    그대로 남겼습니다(§0-1).
REPORT_SIMPLE_RETURN_NOTICE = (
    "⚠️ 수익률은 기간 시작·종료 두 시점의 **단순 비교**입니다 — 기간 중 매매가 있었다면 "
    "그 영향이 함께 섞여 있습니다."
)
REPORT_NO_BACKFILL_NOTICE = (
    "기록은 이 기능을 켠 날부터 쌓입니다 — 그 이전 기간은 과거 시세로 역산하지 않습니다."
)


# =============================================================================
# A. 기간 경계 계산 (순수 함수)
# =============================================================================
#  주간/월간/분기/반기/연간 리포트는 **별도 테이블이 아니라 이 경계 계산 + 날짜 범위 쿼리**로
#  만듭니다(작업지시서 §2). 그래서 이 함수들이 리포트의 뼈대입니다.
# =============================================================================
PERIOD_DAILY = "DAILY"
PERIOD_WEEKLY = "WEEKLY"
PERIOD_MONTHLY = "MONTHLY"
PERIOD_QUARTERLY = "QUARTERLY"
PERIOD_HALF = "HALF"
PERIOD_YEARLY = "YEARLY"

# (코드, 화면 표기) — 화면 selectbox 옵션도 이 목록에서 그대로 뽑습니다(문자열 이중 관리 금지).
PERIOD_OPTIONS = (
    (PERIOD_DAILY, "일간"),
    (PERIOD_WEEKLY, "주간"),
    (PERIOD_MONTHLY, "월간"),
    (PERIOD_QUARTERLY, "분기"),
    (PERIOD_HALF, "반기"),
    (PERIOD_YEARLY, "연간"),
)
PERIOD_LABELS = dict(PERIOD_OPTIONS)
PERIODS = tuple(code for code, _ in PERIOD_OPTIONS)

_WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")


def to_date(value):
    """'YYYY-MM-DD' 문자열 / date / datetime → date. 모르는 값은 지어내지 않고 예외."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("날짜가 비어 있습니다.")
    # Supabase 가 'YYYY-MM-DD' 또는 ISO 타임스탬프를 줄 수 있어 앞 10자만 씁니다.
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"날짜 형식을 알 수 없습니다: {value!r}") from exc


# 'YYYY-MM-DD HH:MM' 또는 'YYYY-MM-DDTHH:MM(:SS…)' 앞부분만 인정합니다.
_PRICE_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})")


def normalize_price_stamp(value):
    """
    수집기 메타데이터의 타임스탬프 문자열 → 'YYYY-MM-DD HH:MM' (없거나 시:분이 없으면 None).

    ⚠️ 여기서 하는 일은 **자르기뿐**입니다(§0-1).
      · 날짜만 있고 시각이 없는 값('2026-08-12')은 00:00 을 붙이지 않고 **None** 입니다 —
        자정에 수집했다는 뜻이 되어 버립니다.
      · 타임존 변환을 하지 않습니다. 이 함수에 들어오는 값은 호출부에서 이미 **한국시간**
        이라고 확인된 필드뿐입니다(KR=last_updated_at, US=last_updated_at_kst).
      · 초는 원본에 있어도 버립니다. 화면 표기가 분 단위로 통일돼야 하고, 두 수집기 모두
        분 단위까지만 기록합니다(TASK_HISTORY #111 과 같은 판단).
    """
    text = str(value or "").strip()
    if not text:
        return None
    match = _PRICE_STAMP_RE.match(text)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)}:{match.group(3)}"


def normalize_period(period):
    value = str(period or "").strip().upper()
    if value in PERIODS:
        return value
    raise ValueError(f"알 수 없는 기간 코드입니다: {period!r} (허용: {', '.join(PERIODS)})")


def _last_day_of_month(year, month):
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def period_bounds(period, ref_date):
    """
    기준일이 속한 기간의 (시작일, 종료일)을 돌려줍니다. **달력 기준**입니다 — 거래일
    캘린더(휴장일)를 코드에 넣지 않습니다(§0-1: 공휴일을 하드코딩하면 매년 틀립니다).
    실제로 어떤 날짜의 스냅샷이 있었는지는 데이터가 알려줍니다.

      · 일간   : 그 날 하루
      · 주간   : 월요일 ~ 일요일 (ISO 기준)
      · 월간   : 1일 ~ 말일
      · 분기   : 1/4/7/10월 1일 ~ 분기 말일
      · 반기   : 1/1~6/30, 7/1~12/31
      · 연간   : 1/1 ~ 12/31
    """
    period = normalize_period(period)
    day = to_date(ref_date)

    if period == PERIOD_DAILY:
        return day, day
    if period == PERIOD_WEEKLY:
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if period == PERIOD_MONTHLY:
        return date(day.year, day.month, 1), _last_day_of_month(day.year, day.month)
    if period == PERIOD_QUARTERLY:
        first_month = 3 * ((day.month - 1) // 3) + 1
        return date(day.year, first_month, 1), _last_day_of_month(day.year, first_month + 2)
    if period == PERIOD_HALF:
        if day.month <= 6:
            return date(day.year, 1, 1), date(day.year, 6, 30)
        return date(day.year, 7, 1), date(day.year, 12, 31)
    return date(day.year, 1, 1), date(day.year, 12, 31)


def period_title(period, ref_date):
    """'2026년 8월', '2026년 3분기'처럼 사람이 읽는 기간 이름."""
    period = normalize_period(period)
    day = to_date(ref_date)
    if period == PERIOD_DAILY:
        return f"{day.isoformat()}({_WEEKDAY_KO[day.weekday()]})"
    if period == PERIOD_WEEKLY:
        start, end = period_bounds(period, day)
        return f"{start.isoformat()} ~ {end.isoformat()} 주"
    if period == PERIOD_MONTHLY:
        return f"{day.year}년 {day.month}월"
    if period == PERIOD_QUARTERLY:
        return f"{day.year}년 {(day.month - 1) // 3 + 1}분기"
    if period == PERIOD_HALF:
        return f"{day.year}년 {'상반기' if day.month <= 6 else '하반기'}"
    return f"{day.year}년"


def shift_period(period, ref_date, steps):
    """
    기간 단위로 앞/뒤 이동한 기준일을 돌려줍니다(화면의 '이전 기간 / 다음 기간' 버튼용).
    항상 그 기간의 **시작일**을 돌려주므로 월말/윤년 경계에서 날짜가 튀지 않습니다.
    """
    period = normalize_period(period)
    start, _ = period_bounds(period, ref_date)
    if steps == 0:
        return start

    if period == PERIOD_DAILY:
        return start + timedelta(days=steps)
    if period == PERIOD_WEEKLY:
        return start + timedelta(weeks=steps)

    months_per_step = {
        PERIOD_MONTHLY: 1, PERIOD_QUARTERLY: 3, PERIOD_HALF: 6, PERIOD_YEARLY: 12,
    }[period]
    total = (start.year * 12 + (start.month - 1)) + months_per_step * steps
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


# =============================================================================
# B. 스냅샷 1행 만들기 / 기간 집계·판정 (순수 함수)
# =============================================================================
def _round6(value):
    """
    소수점 6자리 반올림 — DB 컬럼이 전부 numeric(20,6) 이라 **여기서 반올림한 값이 곧
    저장되는 값**입니다. 이 함수를 거친 숫자만 행에 담아, 파이썬이 보는 값과 DB 에 들어가는
    값이 다를 여지를 없앱니다(합계와 종목별이 어긋나는 흔한 원인 중 하나가 '저장할 때 한 번
    더 반올림되는 것'입니다).
    """
    return round(float(value), 6)


def _sum_money(values):
    """
    돈을 더할 때 쓰는 합산 — **Decimal 로 정확히** 더한 뒤 float 로 돌려줍니다.

    왜 그냥 sum() 이 아닌가 (2026-08-13, 이번 작업에서 실측으로 확인)
      저장되는 종목별 값은 소수점 6자리로 딱 떨어지는 십진수인데, 그것들을 float 로 더하면
      2진 부동소수점 오차가 쌓입니다. DB(numeric)는 **십진수로 정확히** 더하므로, 금액이
      커지면 "종목별을 다 더한 값"과 "저장된 합계"가 마지막 자리에서 어긋날 수 있습니다.
      오너가 나중에 SQL 로 대조했을 때 딱 그게 "들쑥날쑥"으로 보입니다. 그래서 여기서도
      DB 와 **같은 방식(십진수)** 으로 더합니다.

    ⚠️ 남아 있는 한계는 정직하게 적어 둡니다(지어내지 않기 — 여기서 "완벽하다"고 쓰면
       그게 거짓말입니다): 십진수 정확 합을 float 로 되돌리는 마지막 단계는 IEEE-754
       배정밀도의 유효자릿수(약 15~17자리)에 갇힙니다. 그래서 **합계가 대략 10^10 을 넘으면서
       동시에 소수점 이하 금액까지 있는** 경우(예: 수백억원 규모 + 가중평균 매입단가처럼 무한
       소수인 단가)에는 마지막 자리가 어긋날 수 있습니다 — 무작위 2,000 포트폴리오로 실측한
       최대 오차가 **0.00005원**이었습니다. 정수 수량·정수 단가인 한국 주식이나 금액 규모가
       작은 미국 주식에서는 오차가 아예 0 입니다.
       그래서 대조는 0 이 아니라 `TOTAL_MATCH_TOLERANCE`(0.01) 로 봅니다. 화면 표기 단위보다
       훨씬 작은 값이라 **사람이 볼 수 있는 불일치는 전부 잡히고**, 있지도 않은 문제를 쫓지도
       않습니다.
    """
    total = Decimal("0")
    for value in values:
        total += Decimal(str(float(value)))
    return _round6(float(total))


def _holding_snapshot_row(user_id, market, snapshot_date, evaluated, price_stamp):
    """
    `evaluate_holding()` 결과 1건 → 종목별 스냅샷 테이블에 넣을 행 1개.

    ⚠️ 이익(profit)·수익률은 **저장하지 않습니다.** `market_value - cost` 로 언제든 정확히
       나오는 값이고, 저장하면 계산 경로가 하나 더 생겨서 나중에 서로 어긋날 여지가 됩니다
       (sql/report_schema.sql §8 의 같은 설명 참고).
    ⚠️ 통화는 보유 행의 값이 아니라 **시장에서 파생**시킵니다(합계 행과 완전히 동일한 규칙).
       보유 행에 잘못된 통화가 들어 있어도 이 표에 원·달러가 섞이지 않습니다.
    """
    priced = bool(evaluated.get("price_available"))
    raw_name = evaluated.get("stock_name")
    stock_name = str(raw_name).strip() if raw_name is not None else ""
    return {
        "user_id": user_id,
        "market": market,
        "ticker": evaluated["ticker"],
        "snapshot_date": snapshot_date,
        "stock_name": stock_name or None,
        "quantity": _round6(evaluated["quantity"]),
        "avg_purchase_price": _round6(evaluated["avg_purchase_price"]),
        "cost": _round6(evaluated["cost"]),
        # 가격을 몰랐으면 NULL. 0 으로 채우지 않습니다(§0-1) — DB CHECK 로도 강제됩니다.
        "current_price": _round6(evaluated["current_price"]) if priced else None,
        "market_value": _round6(evaluated["market_value"]) if priced else None,
        "currency": currency_for_market(market),
        "priced": priced,
        # 합계 행에 들어가는 것과 **완전히 같은 문자열**(같은 변수)을 넣습니다.
        PRICE_STAMP_FIELD: price_stamp,
    }


def build_snapshot_rows_with_holdings(user_id, holdings, price_lookup,
                                      session_date_by_market, benchmark_by_market=None,
                                      price_stamp_by_market=None):
    """
    사용자 1명의 보유 종목 → **합계 행(시장별 1행) + 종목별 행(종목당 1행)** 을 한 번에.

    반환: (rows, holding_rows, skipped)
      rows         : portfolio_daily_snapshots 에 넣을 dict 목록 (기존과 완전히 동일한 형태)
      holding_rows : portfolio_holding_snapshots 에 넣을 dict 목록 (2026-08-13 신설)
      skipped      : [{"market":..., "reason":...}] — 왜 안 만들었는지(§0-1, 조용히 넘기지 않음)

    =========================================================================
    🔴 이 함수가 "들쑥날쑥"(합계 ≠ 종목별 합)을 원천 차단하는 방식 — 가장 중요한 부분
    =========================================================================
    합계를 따로 계산하는 코드 경로가 **없습니다.**
      ① 보유 종목을 `evaluate_holding()` 으로 평가 (화면 '내 성적표'와 같은 함수)
      ② 그 결과를 곧바로 **종목별 행**으로 만들고(= 실제로 DB 에 저장될 그 숫자)
      ③ **그 종목별 행들을 그대로 더해서** 합계 행을 만듭니다.
    즉 합계는 종목별의 파생물입니다. 두 값이 서로 다른 입력·다른 반올림·다른 시점을 타지
    않으므로 어긋날 수가 없습니다.

    반올림도 한 번뿐입니다 — 종목별 행을 만들 때 소수점 6자리(=DB 컬럼 정밀도)로 맞추고,
    **그 맞춰진 값들을 더합니다.** (먼저 원본 정밀도로 더한 뒤 나중에 반올림하면, 저장된
    종목별 값들의 합과 저장된 합계가 마지막 자리에서 어긋날 수 있습니다.)

    이전 버전(2026-08-12)은 종목별 평가 결과를 합산한 뒤 **버렸습니다.** 이번 변경은 그것을
    버리지 않고 함께 저장하는 것뿐이고, 합계 쪽 숫자의 의미는 그대로입니다.
    =========================================================================

    나머지 인자 설명은 `build_snapshot_rows()` 와 같습니다(그 함수는 이 함수의 얇은 래퍼).
    """
    benchmark_by_market = benchmark_by_market or {}
    price_stamp_by_market = price_stamp_by_market or {}
    grouped = {}
    for holding in holdings or []:
        try:
            market = normalize_market(holding.get("market"))
        except ValueError:
            continue
        grouped.setdefault(market, []).append(holding)

    rows, holding_rows, skipped = [], [], []
    for market in MARKETS:
        items = grouped.get(market)
        if not items:
            continue

        session_date = session_date_by_market.get(market)
        if not session_date:
            skipped.append({"market": market,
                            "reason": "이 시장의 가격 스냅샷 거래일을 확인하지 못해 기록하지 않았습니다."})
            continue

        evaluated = []
        for holding in items:
            try:
                price = price_lookup(holding.get("market"), holding.get("ticker"))
                evaluated.append(evaluate_holding(holding, price))
            except (ValueError, KeyError, TypeError) as exc:
                # 한 종목이 깨져도 나머지는 살립니다. 대신 그 종목은 '가격 모름'으로도 세지
                # 않고 사유를 남깁니다(§0-1 — 조용히 사라지면 안 됨). 합계에서도 종목별
                # 표에서도 똑같이 빠지므로 두 표는 계속 일치합니다.
                skipped.append({
                    "market": market,
                    "reason": f"보유 행을 평가할 수 없어 제외: {holding.get('ticker')!r} ({exc})",
                })

        snapshot_date = to_date(session_date).isoformat()
        # 시:분을 모르면 None(=NULL). 오늘 시각이나 장 마감 시각으로 메우지 않습니다(§0-1).
        # 이 **하나의 값**을 합계 행과 종목별 행 양쪽에 그대로 넣습니다.
        price_stamp = normalize_price_stamp(price_stamp_by_market.get(market))

        # ② 종목별 행을 먼저 만듭니다 — 가격을 모르는 종목도 **행은 만듭니다**(값만 NULL +
        #    priced=false). 합계에서는 빠지지만 "그날 이 종목을 들고 있었고 가격을 몰랐다"는
        #    사실 자체가 기록으로 남아야 하기 때문입니다(빈칸으로 사라지면 안 됨).
        details = [_holding_snapshot_row(user_id, market, snapshot_date, row, price_stamp)
                   for row in evaluated]
        priced = [row for row in details if row["priced"]]
        if not priced:
            skipped.append({
                "market": market,
                "reason": (f"{len(details)}개 종목 모두 그날 현재가를 알 수 없어 스냅샷을 "
                           "만들지 않았습니다(0원으로 기록하지 않습니다)."),
            })
            # ⚠️ 이 경우 종목별 행도 만들지 않습니다. 합계 행이 없는 날짜에 종목별 행만
            #    남으면 두 표가 서로 다른 날짜 집합을 갖게 됩니다("종목별 표에는 있는데
            #    리포트에는 없는 날"). 두 표는 항상 같은 (사용자·시장·거래일)을 가집니다.
            continue

        # ③ 합계는 **위에서 만든 종목별 행들을 그대로 더한 값**입니다.
        symbol, value = benchmark_by_market.get(market, (None, None))
        rows.append({
            "user_id": user_id,
            "market": market,
            "snapshot_date": snapshot_date,
            # 🔴 종목별 행에 저장되는 바로 그 값들을, DB 와 같은 십진수 방식으로 더합니다.
            "total_value": _sum_money(row["market_value"] for row in priced),
            "total_cost": _sum_money(row["cost"] for row in priced),
            "currency": currency_for_market(market),
            "holdings_count": len(details),
            "priced_count": len(priced),
            "unpriced_count": len(details) - len(priced),
            "benchmark_symbol": symbol,
            "benchmark_value": (_round6(value) if value is not None else None),
            PRICE_STAMP_FIELD: price_stamp,
        })
        holding_rows.extend(details)
    return rows, holding_rows, skipped


def build_snapshot_rows(user_id, holdings, price_lookup,
                        session_date_by_market, benchmark_by_market=None,
                        price_stamp_by_market=None):
    """
    사용자 1명의 보유 종목 → 그날 저장할 **합계** 스냅샷 행 목록(시장별 최대 1행).

    price_lookup           : (market, ticker) -> 현재가 또는 None  (scorecard_db.make_price_lookup)
    session_date_by_market : {"KR": "2026-08-11", "US": "2026-08-11"} — 그 시장 가격이 실제로
                             속한 **거래일**. 배치가 도는 시각이 아니라 데이터가 말하는 날짜를
                             씁니다(§0-3-1 후행지표 전용, 아래 resolve_session_dates 참고).
    benchmark_by_market    : {"KR": ("KOSPI", 3210.5), "US": ("SP500_PROXY_SPY", 754.6)}
                             값이 없으면 (심볼, None) 로 넘기세요 — NULL 로 저장됩니다.
    price_stamp_by_market  : {"KR": "2026-08-12 17:50", "US": "2026-08-13 07:14"} — 그 시장
                             가격이 **한국시간 기준 몇 시 몇 분에 수집됐는지**(수집기 메타데이터
                             원문). 모르면 넣지 마세요 — NULL 로 저장되고 화면이 "시각 정보
                             없음"이라고 정직하게 표시합니다(추정 금지).

    반환: (rows, skipped)   ← 2026-08-12 부터의 시그니처를 그대로 유지합니다.

    ⚠️ 2026-08-13 — 실제 계산은 `build_snapshot_rows_with_holdings()` 로 옮겼습니다. 이 함수는
       그 결과에서 **합계 행만** 꺼내 주는 얇은 래퍼입니다. 이렇게 둔 이유:
         · 기존 호출부·테스트가 한 줄도 바뀌지 않습니다(회귀 위험 0).
         · 그럼에도 합계는 여전히 종목별 결과에서 파생됩니다 — 두 경로가 갈라지지 않습니다.
       (#112 에서 `resolve_session_dates()` 를 `resolve_session_info()` 의 래퍼로 남긴 것과
        같은 패턴입니다.)

    ⚠️ 총평가금액·총매입원가는 **그날 현재가를 아는 종목만** 합산합니다. 값을 모르는 종목을
       0원으로 넣으면 그 자체가 지어낸 숫자이고, 다음 날 그 종목 가격이 들어오는 순간
       "하루 만에 수천만원 상승"처럼 보이는 가짜 수익률이 생깁니다.
    """
    rows, _holding_rows, skipped = build_snapshot_rows_with_holdings(
        user_id, holdings, price_lookup, session_date_by_market,
        benchmark_by_market=benchmark_by_market,
        price_stamp_by_market=price_stamp_by_market,
    )
    return rows, skipped


def _normalize_snapshot(row):
    """DB/합성 데이터의 한 행을 계산하기 좋은 형태로 정규화(숫자는 float, 날짜는 date)."""
    item = dict(row)
    item["snapshot_date"] = to_date(item.get("snapshot_date"))
    for field in ("total_value", "total_cost", "benchmark_value"):
        raw = item.get(field)
        if raw is None or raw == "":
            item[field] = None
            continue
        try:
            item[field] = float(raw)
        except (TypeError, ValueError):
            raise ReportError(f"스냅샷 데이터가 손상됐습니다({field}={raw!r}).")
    for field in ("holdings_count", "priced_count", "unpriced_count"):
        raw = item.get(field)
        item[field] = int(raw) if raw is not None and raw != "" else None
    # 🕐 가격 수집 시각(KST). 컬럼이 없던 시절의 행이나 시각을 못 읽은 날은 None 그대로 둡니다
    #    — 화면이 "시각 정보 없음"으로 표시할 수 있게, 빈 문자열과 None 을 하나로 맞춰만 둡니다.
    stamp = item.get(PRICE_STAMP_FIELD)
    item[PRICE_STAMP_FIELD] = (str(stamp).strip() or None) if stamp is not None else None
    return item


def sort_snapshots(snapshots):
    """날짜 오름차순 정렬(원본 리스트는 건드리지 않습니다)."""
    return sorted((_normalize_snapshot(s) for s in snapshots),
                  key=lambda s: s["snapshot_date"])


def _normalize_holding_snapshot(row):
    """
    종목별 스냅샷 한 행을 계산·표시하기 좋은 형태로 정규화(숫자는 float, 날짜는 date).

    ⚠️ 가격을 몰랐던 행의 `current_price` / `market_value` 는 **None 그대로** 둡니다.
       0 으로 바꾸면 그 순간 화면과 집계가 거짓말을 시작합니다(§0-1). `priced` 플래그와
       값의 유무가 어긋나는 행(DB CHECK 를 우회한 손상 데이터)은 조용히 고치지 않고
       `priced` 를 **값이 실제로 있는지**로 다시 판정합니다 — 없는 값을 있는 척하지 않기.
    """
    item = dict(row)
    item["snapshot_date"] = to_date(item.get("snapshot_date"))
    for field in ("quantity", "avg_purchase_price", "cost", "current_price", "market_value"):
        raw = item.get(field)
        if raw is None or raw == "":
            item[field] = None
            continue
        try:
            item[field] = float(raw)
        except (TypeError, ValueError):
            raise ReportError(f"종목별 스냅샷 데이터가 손상됐습니다({field}={raw!r}).")
    item["priced"] = bool(item.get("priced")) and item.get("current_price") is not None \
        and item.get("market_value") is not None
    ticker = item.get("ticker")
    item["ticker"] = str(ticker).strip() if ticker is not None else ""
    name = item.get("stock_name")
    item["stock_name"] = (str(name).strip() or None) if name is not None else None
    stamp = item.get(PRICE_STAMP_FIELD)
    item[PRICE_STAMP_FIELD] = (str(stamp).strip() or None) if stamp is not None else None
    return item


def sort_holding_snapshots(rows):
    """거래일 오름차순 → 같은 날은 종목코드 순(원본 리스트는 건드리지 않습니다)."""
    return sorted((_normalize_holding_snapshot(r) for r in rows),
                  key=lambda r: (r["snapshot_date"], r["ticker"]))


def _with_derived_profit(row):
    """
    종목별 행에 이익·수익률을 **계산해서** 붙입니다(저장하지 않고 그때그때 계산하는 값).
    가격을 몰랐던 행은 둘 다 None — 0 이나 '변동 없음'으로 만들지 않습니다.
    """
    item = dict(row)
    if row.get("priced") and row.get("market_value") is not None and row.get("cost") is not None:
        item["profit"] = row["market_value"] - row["cost"]
        item["profit_pct"] = (item["profit"] / row["cost"] * 100.0) if row["cost"] else None
    else:
        item["profit"] = None
        item["profit_pct"] = None
    return item


# 판정 상태 — 화면은 이 값만 보고 "정상 리포트"와 "데이터 부족"을 가릅니다.
STATUS_COMPLETE = "COMPLETE"              # 기간이 끝났고, 시작 이전 스냅샷도 있어 전 구간을 담음
STATUS_IN_PROGRESS = "IN_PROGRESS"        # 시작 기준점은 있는데 기간이 아직 안 끝남
STATUS_INSUFFICIENT = "INSUFFICIENT"      # 기간 시작 전 스냅샷이 없어 구간 전체를 담지 못함
STATUS_NO_DATA = "NO_DATA"                # 이 기간에 스냅샷이 아예 없음


def compute_period_report(snapshots, period, ref_date, today=None):
    """
    스냅샷 목록(한 사용자 · 한 시장)에서 기간 리포트 하나를 계산합니다.
    **DB 도 네트워크도 필요 없습니다** — 합성 데이터로 그대로 테스트할 수 있게 분리했습니다.

    기준점(baseline)을 고르는 규칙 — 여기가 이 함수의 핵심입니다.
      · 원칙: "이번 달 수익률"은 **지난달 마지막 스냅샷 → 이번 달 마지막 스냅샷** 으로 재야
        기간 전체의 등락이 담깁니다. 그래서 baseline 은 기간 시작일 **이전**의 가장 최근
        스냅샷입니다(baseline_kind="prior_close").
      · 그런 스냅샷이 없으면(기능을 이 기간 도중에 켠 경우) 기간 안의 **첫 스냅샷**을
        기준으로 삼되, 상태를 INSUFFICIENT 로 내려 화면이 "이 기간은 완성된 리포트가
        아닙니다"라고 주 컨텐츠로 알리게 합니다(baseline_kind="first_in_window").
      · 어느 쪽이든 **실제로 비교한 두 날짜를 그대로 화면에 보여줍니다**(§0-1 — 무엇과
        무엇을 비교했는지 숨기지 않음).

    반환 dict 의 주요 키
        status / status_message / period / period_title
        window_start / window_end / is_window_ended
        baseline / latest (스냅샷 행) / baseline_kind
        snapshot_count / covered_from / covered_to / missing_days_before_start
        value_change / value_change_pct
        profit_start / profit_pct_start / profit_end / profit_pct_end
        composition_changed / composition_notes / coverage_note
    """
    period = normalize_period(period)
    window_start, window_end = period_bounds(period, ref_date)
    today = to_date(today) if today else date.today()

    rows = sort_snapshots(snapshots)
    in_window = [r for r in rows if window_start <= r["snapshot_date"] <= window_end]
    before = [r for r in rows if r["snapshot_date"] < window_start]

    result = {
        "period": period,
        "period_title": period_title(period, ref_date),
        "window_start": window_start,
        "window_end": window_end,
        "is_window_ended": today > window_end,
        "snapshot_count": len(in_window),
        "covered_from": in_window[0]["snapshot_date"] if in_window else None,
        "covered_to": in_window[-1]["snapshot_date"] if in_window else None,
        "baseline": None,
        "latest": None,
        "baseline_kind": None,
        "value_change": None,
        "value_change_pct": None,
        "profit_start": None,
        "profit_pct_start": None,
        "profit_end": None,
        "profit_pct_end": None,
        "composition_changed": False,
        "composition_notes": [],
        "coverage_note": None,
        "currency": (in_window[-1].get("currency") if in_window else None),
        "market": (in_window[-1].get("market") if in_window else None),
    }

    if not in_window:
        result["status"] = STATUS_NO_DATA
        result["status_message"] = (
            f"{result['period_title']} 구간에는 저장된 스냅샷이 하나도 없습니다. "
            "이 기능을 켜기 전 기간이거나, 그 기간에 보유 종목이 없었습니다 — "
            "과거 시세로 역산해서 만들어내지 않습니다."
        )
        return result

    latest = in_window[-1]
    if before:
        baseline = before[-1]
        baseline_kind = "prior_close"
    else:
        baseline = in_window[0]
        baseline_kind = "first_in_window"

    result["baseline"] = baseline
    result["latest"] = latest
    result["baseline_kind"] = baseline_kind

    # ---- 상태 판정 -----------------------------------------------------------
    if baseline_kind == "first_in_window":
        result["status"] = STATUS_INSUFFICIENT
        gap_days = (result["covered_from"] - window_start).days
        result["missing_days_before_start"] = gap_days
        result["status_message"] = (
            f"{result['period_title']} 전체를 담은 리포트가 아닙니다. "
            f"이 기간이 시작된 {window_start.isoformat()} 이전의 스냅샷이 없어, "
            f"실제로는 {result['covered_from'].isoformat()} 부터 "
            f"{result['covered_to'].isoformat()} 까지 {len(in_window)}일치만 비교했습니다"
            + (f"(기간 시작 이후 {gap_days}일치가 비어 있음)." if gap_days > 0 else ".")
        )
    elif not result["is_window_ended"]:
        result["status"] = STATUS_IN_PROGRESS
        result["missing_days_before_start"] = 0
        # 2026-08-13 (#114) 문구 축약 — "정식 리포트는 기간이 끝난 뒤에 확정됩니다"는
        # "아직 진행 중 / 중간 집계"와 같은 말이라 뺐습니다(뜻은 그대로).
        result["status_message"] = (
            f"{result['period_title']}은(는) 아직 진행 중 — "
            f"{result['covered_to'].isoformat()} 까지의 중간 집계입니다."
        )
    else:
        result["status"] = STATUS_COMPLETE
        result["missing_days_before_start"] = 0
        result["status_message"] = (
            f"{result['period_title']} 리포트 — "
            f"{baseline['snapshot_date'].isoformat()}(직전 기준) → "
            f"{latest['snapshot_date'].isoformat()} 비교."
        )

    # ---- 수치 계산 -----------------------------------------------------------
    #  §5(작업지시서): v1 은 구간 시작/종료 스냅샷의 단순 비교입니다. 대신 무엇을 비교했는지와
    #  구성이 바뀌었는지를 반드시 함께 보여줍니다.
    start_value, end_value = baseline.get("total_value"), latest.get("total_value")
    start_cost, end_cost = baseline.get("total_cost"), latest.get("total_cost")

    if start_value and end_value is not None and start_value > 0:
        result["value_change"] = end_value - start_value
        result["value_change_pct"] = (end_value - start_value) / start_value * 100.0

    if start_value is not None and start_cost:
        result["profit_start"] = start_value - start_cost
        result["profit_pct_start"] = (start_value - start_cost) / start_cost * 100.0
    if end_value is not None and end_cost:
        result["profit_end"] = end_value - end_cost
        result["profit_pct_end"] = (end_value - end_cost) / end_cost * 100.0

    # ---- 구성 변경 감지 (작업지시서 §5) --------------------------------------
    notes = []
    if baseline.get("holdings_count") is not None and latest.get("holdings_count") is not None \
            and baseline["holdings_count"] != latest["holdings_count"]:
        notes.append(
            f"보유 종목 수가 {baseline['holdings_count']}개 → {latest['holdings_count']}개로 "
            "달라졌습니다."
        )
    if start_cost is not None and end_cost is not None and abs(end_cost - start_cost) > 1e-6:
        notes.append("매입원가 합계가 달라졌습니다(추가 매수·매도·평균단가 수정이 있었습니다).")
    if notes:
        result["composition_changed"] = True
        notes.append(
            "이 기간 수익률에는 시세 변동뿐 아니라 **매매의 영향이 섞여 있습니다** — "
            "v1은 매매 효과만 따로 떼어내 계산하지 않습니다(지어내지 않기)."
        )
    result["composition_notes"] = notes

    # ---- 담긴 종목 수(가격을 아는 종목) 변화 안내 ----------------------------
    if baseline.get("priced_count") is not None and latest.get("priced_count") is not None \
            and baseline["priced_count"] != latest["priced_count"]:
        result["coverage_note"] = (
            f"합계에 담긴 종목 수가 {baseline['priced_count']}개 → {latest['priced_count']}개로 "
            "달라졌습니다(그날 현재가를 알 수 없던 종목이 있었습니다). 두 시점의 대상이 달라서 "
            "수익률을 그대로 비교하기 어렵습니다."
        )
    elif latest.get("unpriced_count"):
        result["coverage_note"] = (
            f"{latest['unpriced_count']}개 종목은 현재가를 알 수 없어 합계에서 빠져 있습니다."
        )

    return result


def benchmark_period_return(closes, baseline_date, end_date):
    """
    벤치마크(코스피 종가 / 미국 프록시 ETF 종가) 기간 수익률.

    ⚠️ 포트폴리오와 **정확히 같은 두 날짜**로만 계산합니다. 그 날짜의 종가가 없으면
    (휴장·수집 실패) 가까운 날로 밀어서 맞추지 않고 "없음"으로 돌려줍니다 — 보간·근사는
    §0-1 위반이고, 며칠씩 어긋난 비교는 사용자를 속이는 숫자가 됩니다.

    반환: {"available", "reason", "start_value", "end_value", "change_pct"}
    """
    result = {"available": False, "reason": None,
              "start_value": None, "end_value": None, "change_pct": None}
    if not closes:
        result["reason"] = "벤치마크 데이터가 아직 수집되지 않았습니다."
        return result

    start_key = to_date(baseline_date).isoformat()
    end_key = to_date(end_date).isoformat()
    start_value = closes.get(start_key)
    end_value = closes.get(end_key)

    missing = [key for key, value in ((start_key, start_value), (end_key, end_value))
               if value is None]
    if missing:
        result["reason"] = (
            "비교 기준일(" + ", ".join(missing) + ")의 벤치마크 종가가 없어 "
            "이 구간은 비교하지 않습니다(가까운 날짜로 대체하지 않습니다)."
        )
        return result

    try:
        start_value = float(start_value)
        end_value = float(end_value)
    except (TypeError, ValueError):
        result["reason"] = "벤치마크 종가를 숫자로 읽지 못했습니다."
        return result
    if start_value <= 0:
        result["reason"] = "벤치마크 시작 종가가 0 이하라 수익률을 계산할 수 없습니다."
        return result

    result.update({
        "available": True,
        "start_value": start_value,
        "end_value": end_value,
        "change_pct": (end_value - start_value) / start_value * 100.0,
    })
    return result


# -----------------------------------------------------------------------------
# B-2. 종목별 스냅샷 → 화면용 요약 (2026-08-13 신설, 순수 함수)
# -----------------------------------------------------------------------------
#  오너 요청: "가독성을 최대한 살린 한장으로 볼 수 있는 테이블을 잘 짜줘".
#  그래서 화면에 넘기기 전에 **여기서** 다음 형태로 정리합니다(계산은 화면이 아니라 이 모듈에
#  두는 기존 계층 분리 원칙 유지 — 화면은 그리기만 합니다):
#     · 기간 안의 **마지막 기록일 하루**를 기준으로 종목별 최신 상태 1행씩 (한눈에 보는 표)
#     · 그 종목의 기간 내 일별 추이는 따로 담아 두었다가 펼쳐 볼 때만 그림
#  ⚠️ 날짜를 섞지 않습니다 — "최신 상태" 표의 모든 행은 **같은 거래일**의 값입니다. 종목마다
#     각자의 마지막 날을 긁어 모으면 표의 합계가 그 어떤 날의 합계와도 같지 않게 됩니다
#     (오너가 말한 "들쑥날쑥"이 화면에서 생기는 전형적인 경로).
# -----------------------------------------------------------------------------
def build_holding_history(holding_rows, window_start=None, window_end=None):
    """
    **한 시장의** 종목별 스냅샷 행들 → 화면이 그대로 그릴 수 있는 구조.
    **DB·네트워크 불필요**(순수 함수). 시장·통화가 섞여 들어오면 합산하지 않고 예외입니다.

    반환 dict
        base_date        : 이 기간에 종목별 기록이 있는 **마지막 거래일**(없으면 None)
        first_date       : 기간 안 첫 기록일
        dates            : 기간 안에 기록이 있는 거래일 오름차순 목록
        rows             : base_date 하루의 종목별 행 목록(평가금액 큰 순, 가격 모름은 맨 뒤)
                           각 행에 profit / profit_pct / price_change_pct(기간 주가 등락) /
                           days_recorded / unpriced_days 가 계산되어 붙습니다.
        totals           : base_date 하루의 합계(가격을 아는 종목만) + 개수
        gone             : 기간 안에는 기록이 있었지만 base_date 에는 없는 종목(매도 등)
        daily_by_ticker  : {티커: [그 종목의 기간 내 일별 행(오름차순)]}

    ⚠️ price_change_pct 는 **주가(현재가) 등락률**입니다 — 평가금액 등락이 아닙니다.
       중간에 추가 매수하면 평가금액은 오르지만 그건 수익이 아니기 때문입니다. 기간 안에서
       가격을 처음 안 날의 현재가와 base_date 현재가를 비교하고, 비교할 두 값이 없으면
       None(화면은 "—")입니다. 가까운 날로 밀어서 맞추지 않습니다.
    """
    rows = sort_holding_snapshots(holding_rows or [])

    # 🔴 원화와 달러를 절대 한 숫자로 합치지 않는다 — 이 모듈 전체를 관통하는 원칙이라
    #    여기서도 방어합니다. 이 함수는 **한 시장의 행들만** 받습니다(화면이 시장별 블록으로
    #    나눠서 부릅니다). 섞여 들어오면 합계가 원+달러가 되므로 조용히 계산하지 않고 멈춥니다.
    currencies = {r.get("currency") for r in rows if r.get("currency")}
    markets = {r.get("market") for r in rows if r.get("market")}
    if len(currencies) > 1 or len(markets) > 1:
        raise ReportError(
            "종목별 기록에 서로 다른 시장·통화가 섞여 있습니다"
            f"(시장: {sorted(markets)}, 통화: {sorted(currencies)}) — "
            "환율 변환을 하지 않으므로 합산하지 않고 중단합니다."
        )

    if window_start is not None:
        start = to_date(window_start)
        rows = [r for r in rows if r["snapshot_date"] >= start]
    if window_end is not None:
        end = to_date(window_end)
        rows = [r for r in rows if r["snapshot_date"] <= end]

    result = {
        "base_date": None, "first_date": None, "dates": [],
        "rows": [], "gone": [], "daily_by_ticker": {},
        "totals": {"market_value": None, "cost": None, "cost_all": None,
                   "profit": None, "profit_pct": None,
                   "holdings_count": 0, "priced_count": 0, "unpriced_count": 0},
    }
    if not rows:
        return result

    dates = sorted({r["snapshot_date"] for r in rows})
    base_date = dates[-1]

    by_ticker = {}
    for row in rows:
        by_ticker.setdefault(row["ticker"], []).append(row)

    daily_by_ticker = {ticker: [_with_derived_profit(r) for r in history]
                       for ticker, history in by_ticker.items()}

    summary_rows = []
    for row in (r for r in rows if r["snapshot_date"] == base_date):
        history = by_ticker[row["ticker"]]
        item = _with_derived_profit(row)

        priced_history = [h for h in history if h["priced"]]
        first_priced = priced_history[0] if priced_history else None
        item["price_change_pct"] = None
        item["price_change_from"] = None
        item["price_change_from_price"] = None
        if row["priced"] and first_priced is not None \
                and first_priced["snapshot_date"] < base_date and first_priced["current_price"]:
            item["price_change_from"] = first_priced["snapshot_date"]
            item["price_change_from_price"] = first_priced["current_price"]
            item["price_change_pct"] = (
                (row["current_price"] - first_priced["current_price"])
                / first_priced["current_price"] * 100.0
            )

        item["days_recorded"] = len(history)
        item["unpriced_days"] = sum(1 for h in history if not h["priced"])
        summary_rows.append(item)

    # 평가금액이 큰 종목부터(= 내 자산에서 차지하는 비중이 큰 순서). 가격을 모르는 종목은
    # 금액으로 줄 세울 수 없으므로 0 으로 치지 않고 **맨 뒤로** 보냅니다.
    summary_rows.sort(key=lambda i: (0 if i["priced"] else 1,
                                     -(i["market_value"] or 0.0),
                                     i["ticker"]))

    priced_rows = [i for i in summary_rows if i["priced"]]
    total_value = _sum_money(i["market_value"] for i in priced_rows) if priced_rows else None
    total_cost = _sum_money(i["cost"] for i in priced_rows) if priced_rows else None
    totals = {
        "market_value": total_value,
        "cost": total_cost,
        # 가격을 모르는 종목까지 포함한 매입원가 — 위 total_cost 와 **다른 숫자**이고,
        # 합계 스냅샷과 비교할 때 쓰는 건 total_cost(가격을 아는 종목만) 쪽입니다.
        "cost_all": _sum_money(i["cost"] for i in summary_rows),
        "profit": (total_value - total_cost) if (total_value is not None and total_cost is not None) else None,
        "profit_pct": None,
        "holdings_count": len(summary_rows),
        "priced_count": len(priced_rows),
        "unpriced_count": len(summary_rows) - len(priced_rows),
    }
    if totals["profit"] is not None and total_cost:
        totals["profit_pct"] = totals["profit"] / total_cost * 100.0

    # 📊 비중(%) — 2026-08-13(#114) 추가. **기존 숫자는 하나도 바뀌지 않는 파생값**입니다
    #    (기준일 평가금액 ÷ 그날 평가금액 합계 × 100). 분모는 위 total_value, 즉 **그날 가격을
    #    아는 종목의 합계**이고 이것은 같은 날 합계 스냅샷의 total_value 와 같은 값입니다.
    #    가격을 몰랐던 종목은 비중을 0% 로 적지 않고 None(화면 "모름")입니다 — 자세한 근거는
    #    아래 `build_weight_comparison()` 주석에 적어 뒀습니다.
    for item in summary_rows:
        item["weight_pct"] = (
            item["market_value"] / total_value * 100.0
            if item["priced"] and total_value else None
        )

    base_tickers = {i["ticker"] for i in summary_rows}
    gone = []
    for ticker, history in by_ticker.items():
        if ticker in base_tickers:
            continue
        last = history[-1]
        gone.append({"ticker": ticker, "stock_name": last.get("stock_name"),
                     "last_date": last["snapshot_date"], "days_recorded": len(history)})
    gone.sort(key=lambda g: (g["last_date"], g["ticker"]))

    result.update({
        "base_date": base_date,
        "first_date": dates[0],
        "dates": dates,
        "rows": summary_rows,
        "totals": totals,
        "gone": gone,
        "daily_by_ticker": daily_by_ticker,
    })
    return result


def compare_holding_total(detail_total, summary_total, tolerance=TOTAL_MATCH_TOLERANCE):
    """
    "종목별 합"과 "합계 스냅샷"이 실제로 같은지 **화면에서도 매번 대조**하기 위한 함수.

    두 값은 같은 배치·같은 계산에서 나오므로 정상이라면 항상 일치합니다. 그럼에도 화면에서
    다시 확인하는 이유: 종목별 저장만 실패한 날(§D 의 부분 실패)이나 사람이 DB 를 손댄 경우를
    **숨기지 않고 드러내기 위해서**입니다. 어긋나면 화면이 그 사실을 그대로 말합니다(§0-1).

    반환: {"comparable", "matches", "diff", "message"}
    """
    result = {"comparable": False, "matches": None, "diff": None, "message": ""}
    if detail_total is None or summary_total is None:
        result["message"] = "대조할 값이 없어 확인하지 못했습니다."
        return result
    try:
        diff = float(detail_total) - float(summary_total)
    except (TypeError, ValueError):
        result["message"] = "대조할 값을 숫자로 읽지 못했습니다."
        return result
    result["comparable"] = True
    result["diff"] = diff
    result["matches"] = abs(diff) <= tolerance
    result["message"] = ("종목별 합계가 같은 날 합계 스냅샷과 일치합니다."
                         if result["matches"] else
                         f"종목별 합계와 합계 스냅샷이 {diff:+,.6f} 만큼 어긋납니다.")
    return result


# -----------------------------------------------------------------------------
# B-3. 📊 종목별 비중(%) · 기간 시작 대비 비중 변화 (2026-08-13 #114 신설, 순수 함수)
# -----------------------------------------------------------------------------
#  오너가 직접 수기로 관리해 온 표를 그대로 옮긴 기능입니다(오너 제공 자료
#  "2026년 수익률비교 - 문대호 한장 정리.csv"). 그 표는 두 덩어리였습니다.
#     · "26년 N월 종목 비율"        : 종목 | 현재금액 | 현재 금액 합 | 비율
#     · "구성종목 비율 변경"        : 종목 | 지난달 비중 | 이번달 비중 | 차이
#  둘 다 **이미 저장된 값만으로 계산됩니다** — `portfolio_holding_snapshots`(#113)에 그날
#  종목별 `market_value` 가 있으므로, 같은 날 합계로 나누면 비중이 나옵니다. 새 테이블도,
#  새 저장 로직도 필요 없어서 **조회 시점에 계산**합니다.
#
#  🔴 분모를 무엇으로 잡을 것인가 (판단 근거를 남깁니다 — §0-1)
#     분모 = **그날 가격을 아는 종목들의 평가금액 합**입니다. 즉 같은 날 합계 스냅샷의
#     `total_value` 와 같은 값이고, 그래서 이 화면의 비중 합은 항상 100% 가 됩니다.
#     가격을 몰랐던 종목은 두 선택지가 있었습니다.
#       ① 분자에 0 을 넣고 분모에는 포함  → 그 종목이 "0원짜리"라고 말하는 셈이라 거짓말.
#       ② 분모에서 빼고 비중을 "모름"으로 → 채택.
#     ②를 고른 이유: 그 종목의 평가금액은 **아무 데도 기록돼 있지 않습니다**(가격을 몰랐으니
#     계산 자체가 불가능). 없는 값을 0 으로 메우면 나머지 종목의 비중까지 전부 부풀려집니다.
#     대신 "몇 종목이 비중 계산에서 빠졌는지"를 함께 돌려줘 화면이 그 사실을 밝힙니다.
# -----------------------------------------------------------------------------
WEIGHT_OK = "ok"                # 그날 가격을 알아 비중을 계산함
WEIGHT_UNPRICED = "unpriced"    # 그날 보유했지만 가격을 몰라 비중을 모름(0% 아님)
WEIGHT_ABSENT = "absent"        # 그날은 이 종목 기록 자체가 없음(= 비중 0%)


def _weight_denominator(day_rows):
    """
    비중 계산의 분모 — 그날 **가격을 아는** 종목들의 평가금액 합.
    같은 날 합계 스냅샷의 `total_value` 와 같은 값입니다(합계도 가격을 아는 종목만 더하므로).
    가격을 아는 종목이 하나도 없으면 None — 0 으로 나누지도, 분모를 지어내지도 않습니다.
    """
    priced = [r for r in day_rows if r.get("priced") and r.get("market_value") is not None]
    if not priced:
        return None
    total = _sum_money(r["market_value"] for r in priced)
    return total if total > 0 else None


def _weight_of(row, denominator):
    """한 종목의 그날 비중 → (비중% 또는 None, 상태 문자열)."""
    if row is None:
        # 그날은 이 종목을 안 들고 있었습니다 → 비중 0%. 숨기지 않고 0.00% 로 드러냅니다
        # (매매로 종목이 새로 생기거나 없어진 것을 표에서 보이게 하는 게 이 표의 목적).
        return 0.0, WEIGHT_ABSENT
    if not row.get("priced") or row.get("market_value") is None or not denominator:
        return None, WEIGHT_UNPRICED
    return row["market_value"] / denominator * 100.0, WEIGHT_OK


def build_weight_comparison(history):
    """
    `build_holding_history()` 결과 → **기간 첫 기록일 vs 마지막 기록일**의 종목별 비중 비교.

    왜 history 를 받는가: 두 표가 같은 `base_date`(마지막 기록일)를 보게 못 박기 위해서입니다.
    날짜를 각자 다시 고르면 언젠가 서로 다른 날을 보게 되고, 그 순간 화면의 두 표가
    어긋납니다(오너가 말한 "들쑥날쑥"이 생기는 전형적인 경로).

    ⚠️ 비교 시작점은 "지난 기간"이 아니라 **이 기간 안의 첫 기록일**입니다. 화면은 두 날짜를
       그대로 표기해야 합니다 — 종목별 스냅샷은 보고 있는 기간만 조회하므로 기간 시작 이전의
       종목별 기록은 애초에 이 함수에 들어오지 않습니다(없는 값을 끌어오지 않습니다).

    반환 dict
        first_date / base_date : 비교한 두 거래일(같으면 comparable=False)
        comparable             : 비교할 날이 이틀 이상인가
        first_total / base_total : 각 날의 분모(가격을 아는 종목 평가금액 합)
        rows                   : [{ticker, stock_name,
                                   first_pct, first_state, base_pct, base_state,
                                   base_value, change_pp}]  — 기준일 비중 큰 순
        unpriced_base          : 기준일에 가격을 몰라 비중에서 빠진 티커 목록
        unpriced_first         : 첫 기록일에 같은 이유로 빠진 티커 목록
    """
    result = {
        "first_date": None, "base_date": None, "comparable": False,
        "first_total": None, "base_total": None,
        "rows": [], "unpriced_base": [], "unpriced_first": [],
    }
    daily = (history or {}).get("daily_by_ticker") or {}
    dates = (history or {}).get("dates") or []
    base_date = (history or {}).get("base_date")
    if not daily or not dates or base_date is None:
        return result

    first_date = dates[0]
    result["first_date"] = first_date
    result["base_date"] = base_date
    result["comparable"] = base_date != first_date

    on_first, on_base = {}, {}
    names = {}
    for ticker, rows_for_ticker in daily.items():
        for row in rows_for_ticker:
            if row.get("stock_name"):
                names[ticker] = row["stock_name"]
            if row["snapshot_date"] == first_date:
                on_first[ticker] = row
            if row["snapshot_date"] == base_date:
                on_base[ticker] = row

    result["first_total"] = _weight_denominator(on_first.values())
    result["base_total"] = _weight_denominator(on_base.values())

    rows = []
    for ticker in daily:
        first_pct, first_state = _weight_of(on_first.get(ticker), result["first_total"])
        base_pct, base_state = _weight_of(on_base.get(ticker), result["base_total"])
        if first_state == WEIGHT_UNPRICED:
            result["unpriced_first"].append(ticker)
        if base_state == WEIGHT_UNPRICED:
            result["unpriced_base"].append(ticker)
        rows.append({
            "ticker": ticker,
            "stock_name": names.get(ticker),
            "first_pct": first_pct,
            "first_state": first_state,
            "base_pct": base_pct,
            "base_state": base_state,
            "base_value": (on_base.get(ticker) or {}).get("market_value"),
            # 한쪽이라도 "모름"이면 변화량을 만들어내지 않습니다(0%p 로 적으면 거짓말).
            "change_pp": (base_pct - first_pct)
                         if (first_pct is not None and base_pct is not None) else None,
        })

    # 기준일 비중이 큰 종목부터. 비중을 모르는 종목은 금액으로 줄 세울 수 없어 맨 뒤로.
    rows.sort(key=lambda i: (0 if i["base_pct"] is not None else 1,
                             -(i["base_pct"] or 0.0), i["ticker"]))
    result["rows"] = rows
    result["unpriced_first"].sort()
    result["unpriced_base"].sort()
    return result


# =============================================================================
# C. 벤치마크 조회 (읽기 전용 파일 접근)
# =============================================================================
#  한국 : `market_history.csv` 의 "코스피 종가" 컬럼을 **읽기만** 합니다.
#         ⚠️ 이 파일은 매크로(§4) 파이프라인의 산출물이고, 오너의 2026-08-10 중단 지시가
#            걸려 있습니다. 이 모듈에는 이 파일을 여는 'w' 모드가 한 군데도 없습니다.
#  미국 : `data/us_index_history.json` (collector_us_indices.py 산출물).
#         ⚠️ 값은 지수 포인트가 아니라 **추종 ETF 종가**입니다 — 그래서 심볼 이름에
#            PROXY 가 들어갑니다. 자세한 조사 근거는 그 수집기 파일 상단 주석 참고.
# =============================================================================
MARKET_HISTORY_FILENAME = "market_history.csv"
MARKET_HISTORY_DATE_COLUMN = "날짜"
MARKET_HISTORY_KOSPI_COLUMN = "코스피 종가"

KOSPI_BENCHMARK_SYMBOL = "KOSPI"
KOSPI_BENCHMARK_LABEL = "코스피 지수"

# 미국 벤치마크 키/표기의 단일 출처는 `collector_us_indices.US_INDEX_BENCHMARKS` 입니다.
# 화면·배치가 수집기(requests/bs4 의존)를 import 하지 않고도 쓸 수 있도록 키만 여기에
# 옮겨 적되, 값이 어긋나면 테스트(tests/test_report.py)가 잡습니다.
US_PRIMARY_BENCHMARK = "SP500_PROXY_SPY"
US_BENCHMARK_KEYS = ("SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ")
US_INDEX_HISTORY_FILENAME = "us_index_history.json"


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_kospi_close_history(csv_path=None):
    """
    `market_history.csv` → {"YYYY-MM-DD": 코스피 종가}. **읽기 전용**입니다.
    파일이 없거나 컬럼 이름이 바뀌었으면 빈 dict — 벤치마크만 "없음"이 되고 리포트 나머지는
    정상 동작합니다(조용히 0으로 채우지 않습니다).
    """
    path = csv_path or os.path.join(repo_root(), MARKET_HISTORY_FILENAME)
    if not os.path.exists(path):
        return {}
    closes = {}
    # utf-8-sig: 엑셀에서 저장된 BOM 이 있어도 첫 컬럼명이 깨지지 않게(기존 다운로드 모듈과 동일 관례)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or MARKET_HISTORY_DATE_COLUMN not in reader.fieldnames \
                or MARKET_HISTORY_KOSPI_COLUMN not in reader.fieldnames:
            return {}
        for row in reader:
            raw_date = (row.get(MARKET_HISTORY_DATE_COLUMN) or "").strip()
            raw_close = (row.get(MARKET_HISTORY_KOSPI_COLUMN) or "").strip()
            if not raw_date or not raw_close:
                continue
            try:
                day = to_date(raw_date)
                close = float(raw_close.replace(",", ""))
            except (ValueError, TypeError):
                continue
            if close > 0:
                closes[day.isoformat()] = close
    return closes


def load_us_index_closes(data_dir=None):
    """
    `data/us_index_history.json` → {벤치마크키: {"label_ko":..., "closes": {날짜: 종가}, ...}}.
    파일이 없으면 빈 dict(아직 한 번도 수집하지 않은 상태 — 화면은 "벤치마크 없음").
    """
    path = os.path.join(data_dir or default_data_dir(), US_INDEX_HISTORY_FILENAME)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    indices = (payload or {}).get("indices")
    return indices if isinstance(indices, dict) else {}


def benchmark_closes_for_market(market, data_dir=None, csv_path=None):
    """
    시장별 벤치마크 목록을 통일된 형태로 돌려줍니다.
    반환: [{"symbol", "label", "closes", "is_proxy", "note"}]  (없으면 빈 목록)
    """
    market = normalize_market(market)
    if market == MARKET_KR:
        closes = load_kospi_close_history(csv_path)
        return [{
            "symbol": KOSPI_BENCHMARK_SYMBOL,
            "label": KOSPI_BENCHMARK_LABEL,
            "closes": closes,
            "is_proxy": False,
            "note": "코스피 지수 종가(매크로 파이프라인이 매일 수집하는 market_history.csv 재사용).",
        }] if closes else []

    result = []
    indices = load_us_index_closes(data_dir)
    for key in US_BENCHMARK_KEYS:
        entry = indices.get(key)
        if not entry:
            continue
        closes = entry.get("closes") or {}
        if not closes:
            continue
        result.append({
            "symbol": key,
            "label": entry.get("label_ko") or key,
            "closes": closes,
            "is_proxy": bool(entry.get("is_etf_proxy", True)),
            "note": (f"지수 포인트가 아니라 추종 ETF({entry.get('proxy_symbol')}) 종가 기준입니다 "
                     "— 기간 수익률 비교용 근사치."),
        })
    return result


def primary_benchmark_value(market, session_date, data_dir=None, csv_path=None):
    """
    스냅샷 행에 함께 저장할 **대표 벤치마크 1개**의 그날 종가.
    (미국은 S&P500 프록시. 나스닥까지 두 개를 DB 컬럼에 넣지 않는 이유: 벤치마크는 공개
     데이터라 `data/` 파일에 전부 있고, 화면은 그 파일에서 두 지수를 모두 계산합니다.
     DB 의 이 값은 "그날 배치가 실제로 본 값"을 남기는 감사 기록입니다.)

    반환: (symbol, value 또는 None) — 값이 없으면 None 그대로(전날 값 복사 금지).
    """
    market = normalize_market(market)
    day = to_date(session_date).isoformat()
    if market == MARKET_KR:
        return KOSPI_BENCHMARK_SYMBOL, load_kospi_close_history(csv_path).get(day)
    entry = load_us_index_closes(data_dir).get(US_PRIMARY_BENCHMARK) or {}
    return US_PRIMARY_BENCHMARK, (entry.get("closes") or {}).get(day)


# =============================================================================
# D. Supabase 접근
# =============================================================================
SERVICE_URL_ENV = "SUPABASE_URL"
SERVICE_ROLE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"


def _read_service_env(name):
    """
    **환경변수에서만** 읽습니다. `st.secrets` 는 일부러 보지 않습니다 — 이 파일이 다루는
    service_role 키가 Streamlit(앱) 쪽 설정에서 읽히는 경로 자체를 만들지 않기 위해서입니다.
    값은 어떤 로그·에러 메시지에도 넣지 않습니다.
    """
    value = os.environ.get(name)
    return value.strip() if value else None


def service_config_present():
    return bool(_read_service_env(SERVICE_URL_ENV) and _read_service_env(SERVICE_ROLE_KEY_ENV))


def create_service_client():
    """
    배치 전용 Supabase 클라이언트(service_role). **앱에서는 절대 호출하지 마세요.**
    설정이 없으면 조용히 넘어가지 않고 예외를 냅니다 — 배치는 실패해야 사람이 알아챕니다.
    """
    url = _read_service_env(SERVICE_URL_ENV)
    key = _read_service_env(SERVICE_ROLE_KEY_ENV)
    if not url or not key:
        missing = [n for n, v in ((SERVICE_URL_ENV, url), (SERVICE_ROLE_KEY_ENV, key)) if not v]
        raise ReportError(
            "배치용 Supabase 설정이 없습니다: " + ", ".join(missing)
            + " (GitHub Actions Secrets 에 등록하세요. ⚠️ Streamlit Cloud Secrets 가 아닙니다)"
        )
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - CI 에서는 requirements 로 설치됨
        raise ReportError(
            "`supabase` 파이썬 패키지가 설치돼 있지 않습니다(requirements.txt 확인)."
        ) from exc
    try:
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        raise ReportError(f"Supabase 클라이언트 생성 실패: {exc}") from exc


def _execute(query, action):
    """실패를 조용히 빈 값으로 넘기지 않습니다(§0-1) — scorecard_db 와 같은 규약."""
    try:
        response = query.execute()
    except Exception as exc:  # noqa: BLE001
        raise ReportError(f"{action} 실패: {exc}") from exc
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    return data if data is not None else []


def fetch_all_holdings(service_client):
    """
    (배치 전용) 가입한 **모든 사용자**의 보유 종목을 읽습니다. service_role 이라 RLS 를
    우회하므로 이게 가능합니다. 읽기만 합니다 — 이 파일에 holdings 를 수정하는 코드는 없습니다.
    """
    if service_client is None:
        raise ReportError("Supabase 클라이언트가 없습니다.")
    rows = _execute(
        service_client.table(HOLDINGS_TABLE).select(
            "id,user_id,market,ticker,stock_name,quantity,avg_purchase_price,currency"
        ),
        "전체 보유 종목 조회",
    )
    result = []
    for row in rows:
        item = dict(row)
        for numeric_field in ("quantity", "avg_purchase_price"):
            try:
                item[numeric_field] = float(item.get(numeric_field))
            except (TypeError, ValueError):
                raise ReportError(
                    f"보유 종목 데이터가 손상됐습니다({numeric_field}={item.get(numeric_field)!r})."
                )
        result.append(item)
    return result


def group_holdings_by_user(holdings):
    """[{user_id...}] → {user_id: [행, ...]} (user_id 가 없는 행은 버리고 세지 않습니다)."""
    grouped = {}
    for row in holdings or []:
        user_id = row.get("user_id")
        if not user_id:
            continue
        grouped.setdefault(user_id, []).append(row)
    return grouped


def _without_price_stamp(rows):
    """가격 수집 시각 필드만 뺀 사본(컬럼이 아직 없는 DB 로 보낼 때)."""
    return [{key: value for key, value in row.items() if key != PRICE_STAMP_FIELD}
            for row in rows]


def upsert_snapshots(service_client, rows, chunk_size=200):
    """
    (배치 전용) 스냅샷 행들을 저장합니다. 같은 (user_id, market, snapshot_date) 가 이미 있으면
    새로 만들지 않고 **갱신**합니다(배치를 두 번 돌려도 행이 늘지 않음).
    반환: 저장 시도한 행 수

    ⚠️ `price_as_of_kst` 컬럼이 아직 없는 DB 대비 (2026-08-13)
       이 컬럼은 나중에 추가된 것이라, 오너가 `sql/report_schema.sql` 의 alter 문을 실행하기
       전에는 DB 에 없습니다. 그 상태로 컬럼을 보내면 PostgREST 가 요청 전체를 거절해서
       **그날 스냅샷이 통째로 저장되지 않습니다.** 그래서 그 오류만 알아보고 **시각 필드를 빼고
       한 번 더** 저장한 뒤 크게 경고합니다(수치는 지키고, 무엇이 빠졌는지는 로그로 알림).
       — 다른 오류는 그대로 올립니다(조용히 삼키지 않음, §0-1).
    """
    if service_client is None:
        raise ReportError("Supabase 클라이언트가 없습니다.")
    if not rows:
        return 0

    saved = 0
    stamp_column_missing = False
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        payload = _without_price_stamp(chunk) if stamp_column_missing else chunk
        try:
            _execute(
                service_client.table(SNAPSHOTS_TABLE).upsert(
                    payload, on_conflict="user_id,market,snapshot_date"
                ),
                "스냅샷 저장",
            )
        except ReportError as exc:
            if stamp_column_missing or PRICE_STAMP_FIELD not in str(exc):
                raise
            stamp_column_missing = True
            print(
                f"  ⚠️ DB 에 `{PRICE_STAMP_FIELD}` 컬럼이 없어 **가격 수집 시각을 빼고** 저장합니다.\n"
                f"     오너 할 일 — Supabase SQL Editor 에서 아래 한 줄 실행:\n"
                f"       {PRICE_STAMP_ALTER_SQL}\n"
                "     (실행 전까지 저장되는 행은 리포트 화면에서 '시각 정보 없음'으로 보입니다.)"
            )
            _execute(
                service_client.table(SNAPSHOTS_TABLE).upsert(
                    _without_price_stamp(chunk), on_conflict="user_id,market,snapshot_date"
                ),
                "스냅샷 저장(가격 수집 시각 제외)",
            )
        saved += len(chunk)
    return saved


def _holding_row_key(row):
    return (row.get("user_id"), row.get("market"), row.get("ticker"), row.get("snapshot_date"))


def _assert_unique_holding_keys(rows):
    """
    같은 (사용자·시장·종목·거래일) 이 한 번의 저장 요청에 두 번 들어오면 미리 막습니다.

    왜 필요한가: PostgREST 의 upsert 는 한 요청 안에 같은 충돌 키가 두 번 있으면
    "ON CONFLICT DO UPDATE command cannot affect row a second time" 로 **요청 전체를**
    거절합니다. 그러면 그날 종목별 저장이 통째로 날아가는데, 원인이 로그에 잘 드러나지
    않습니다. 여기서 먼저 잡아 **어느 종목이 겹쳤는지**를 그대로 알립니다.

    ⚠️ 겹친 행을 임의로 합치거나 하나를 버리지 않습니다. 합치면 합계 표와 종목 수가
       어긋나고(holdings_count 는 겹친 두 행을 다 세었으므로), 버리면 그만큼 합계가 종목별
       합보다 커집니다 — 어느 쪽이든 오너가 말한 "들쑥날쑥"을 우리 손으로 만드는 셈입니다.
       `holdings` 테이블에 (user_id, market, ticker) 유니크 제약이 있어 정상 경로에서는
       일어날 수 없는 상황이고, 일어났다면 원본 데이터를 봐야 합니다.
    """
    seen = set()
    for row in rows:
        key = _holding_row_key(row)
        if key in seen:
            raise ReportError(
                "종목별 스냅샷에 같은 (사용자·시장·종목·거래일) 행이 두 번 들어 있습니다: "
                f"{key[1]} {key[2]} {key[3]} — 보유 종목 원본에 중복 행이 있는지 확인하세요"
                "(임의로 합치거나 버리지 않고 중단합니다)."
            )
        seen.add(key)


def upsert_holding_snapshots(service_client, rows, chunk_size=200):
    """
    (배치 전용) **종목별** 스냅샷 행들을 저장합니다. 같은
    (user_id, market, ticker, snapshot_date) 가 이미 있으면 갱신합니다(배치를 두 번 돌려도
    행이 늘지 않음). 반환: 저장 시도한 행 수.

    ⚠️ 실패를 삼키지 않습니다 — 어떤 오류든 그대로 ReportError 로 올립니다. "테이블이 아직
       없는 경우"만 배치가 따로 알아보고 건너뛰는데, 그 판단은 여기가 아니라
       `save_holding_snapshots()` 가 합니다(이 함수는 순수하게 저장만).
    """
    if service_client is None:
        raise ReportError("Supabase 클라이언트가 없습니다.")
    if not rows:
        return 0
    _assert_unique_holding_keys(rows)

    saved = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        _execute(
            service_client.table(HOLDING_SNAPSHOTS_TABLE).upsert(
                chunk, on_conflict="user_id,market,ticker,snapshot_date"
            ),
            "종목별 스냅샷 저장",
        )
        saved += len(chunk)
    return saved


def is_missing_holding_table_error(error):
    """
    "종목별 스냅샷 테이블이 아직 없다"(= 오너가 sql/report_schema.sql §8 을 아직 실행하지
    않았다)로 보이는 오류인지. 테이블 이름이 메시지에 있고, 동시에 '없다'는 취지의 표식이
    있을 때만 True 입니다 — 아무 오류나 이 경로로 새어 들어가면 진짜 사고가 조용히
    묻힙니다(§0-1).
    """
    text = str(error or "").lower()
    if HOLDING_SNAPSHOTS_TABLE not in text:
        return False
    return any(marker in text for marker in HOLDING_TABLE_MISSING_MARKERS)


def save_holding_snapshots(service_client, rows, summary_saved=None):
    """
    배치에서 **합계 저장이 끝난 뒤** 종목별 행을 저장하는 단계. 반환:
        {"saved": int, "skipped_reason": str 또는 None}

    =========================================================================
    두 표 중 한쪽만 성공하는 경우를 어떻게 다루는가 (Supabase REST 에는 여러 테이블에 걸친
    원자적 트랜잭션이 없습니다 — 그래서 '완벽한 원자성' 대신 아래 규칙을 씁니다)
    =========================================================================
    ① **순서: 합계 먼저, 종목별 나중.** 합계 표는 리포트 화면 전체가 의존하는 기존 기능이라
       어떤 경우에도 퇴화시키지 않습니다. 합계 저장이 실패하면 예외가 나서 이 단계까지
       오지도 않습니다 ⇒ **"종목별 행이 있는데 합계 행이 없는 날"은 생기지 않습니다.**
       (그 반대 — 합계는 있는데 종목별이 없는 날 — 은 생길 수 있고, 그건 안전한 쪽입니다:
        기존 리포트는 그대로 나오고 종목별 표만 "기록 없음"이 됩니다.)
    ② **테이블 자체가 없으면**(오너가 아직 SQL 을 안 돌린 상태) 배치를 죽이지 않고 이 단계만
       건너뜁니다. 그날 합계 스냅샷은 이미 저장돼 있고, 무엇을 해야 하는지 로그에 크게
       남깁니다(#112 의 '컬럼 없는 DB' 폴백과 같은 방침).
    ③ **그 밖의 실패는 삼키지 않고 그대로 올립니다** — 배치가 빨간 실패로 끝나 오너가 알아챕니다.
       이때도 합계는 이미 저장돼 있어 **잃는 데이터는 없고**, 저장은 upsert 라서 다음 실행이
       같은 날짜를 그대로 다시 채웁니다(재시도를 이 안에서 반복하지 않는 이유 — 같은 요청을
       즉시 되풀이해도 원인이 바뀌지 않고, 하루 한 번 도는 배치라 다음 실행이 곧 재시도입니다).
    ④ 청크(200행) 단위로 나눠 보내므로 중간에 실패하면 앞 청크만 들어간 상태가 될 수 있습니다.
       이것도 upsert 라 다음 실행에서 그대로 메워집니다. 그 사이에 화면이 어긋난 합계를 보여
       주지 않도록, 화면은 **매번 종목별 합과 합계 스냅샷을 대조해서**(compare_holding_total)
       어긋나면 그 사실을 표시합니다.
    =========================================================================
    """
    if not rows:
        return {"saved": 0, "skipped_reason": None}
    try:
        saved = upsert_holding_snapshots(service_client, rows)
    except ReportError as exc:
        if not is_missing_holding_table_error(exc):
            print(f"  ❌ 종목별 스냅샷 저장 실패 — {exc}")
            print(f"     (합계 스냅샷 {summary_saved if summary_saved is not None else '?'}행은 "
                  "이미 저장됐습니다. 잃은 수치는 없고, 다음 실행이 같은 날짜를 다시 채웁니다.)")
            raise
        reason = (f"DB 에 `{HOLDING_SNAPSHOTS_TABLE}` 테이블이 없어 종목별 스냅샷 "
                  f"{len(rows)}행을 저장하지 못했습니다.")
        print(f"  ⚠️ {reason}")
        print(f"     합계 스냅샷은 정상 저장됐습니다 — 기존 리포트 기능은 그대로 동작합니다.")
        print(f"     오너 할 일 — {HOLDING_TABLE_SETUP_HINT}")
        print("     (실행 전까지의 날짜는 종목별 표에서 '기록 없음'으로 남고, 소급해서 "
              "채우지 않습니다 — 그날 종목별 값은 어디에도 보관돼 있지 않습니다.)")
        return {"saved": 0, "skipped_reason": reason}
    return {"saved": saved, "skipped_reason": None}


def fetch_user_snapshots(client, user_id, market=None, start_date=None, end_date=None):
    """
    (화면용) 로그인한 사용자 **본인** 스냅샷 조회. 넘겨받는 client 는 "내 성적표"가 이미
    만들어 둔 anon key + 로그인 세션 클라이언트입니다(RLS 가 남의 행을 막아 줍니다 —
    그래도 앱에서도 user_id 필터를 겁니다, 이중 방어).
    """
    if client is None:
        raise ReportError("Supabase 연결이 준비되지 않았습니다.")
    if not user_id:
        raise ReportError("로그인 정보가 없어 리포트를 조회할 수 없습니다.")
    query = client.table(SNAPSHOTS_TABLE).select("*").eq("user_id", user_id)
    if market:
        query = query.eq("market", normalize_market(market))
    if start_date:
        query = query.gte("snapshot_date", to_date(start_date).isoformat())
    if end_date:
        query = query.lte("snapshot_date", to_date(end_date).isoformat())
    rows = _execute(query, "리포트 스냅샷 조회")
    return sort_snapshots(rows)


def fetch_user_holding_snapshots(client, user_id, market=None, start_date=None, end_date=None):
    """
    (화면용) 로그인한 사용자 **본인**의 종목별 스냅샷 조회. `fetch_user_snapshots()` 와 완전히
    같은 규약입니다(anon key + 로그인 세션 클라이언트를 받아 쓰고, RLS 위에 user_id 필터를
    한 번 더 겁니다 — 이중 방어).

    ⚠️ 이 표는 합계 표보다 행이 훨씬 많으므로(종목 수만큼), 화면은 **보고 있는 기간만**
       잘라서 부릅니다(start_date/end_date). 합계 쪽은 기간 시작 이전의 기준점 행이 필요해서
       전부 받지만, 종목별 표는 그 기간 안의 움직임만 보여주므로 기준점이 필요 없습니다.
    ⚠️ 테이블이 아직 없으면(오너가 sql/report_schema.sql §8 미실행) 여기서 ReportError 가
       납니다. 화면은 그 오류를 **삼키지 않고**, 다만 리포트의 나머지는 정상 표시되도록
       이 섹션만 안내 문구로 대체합니다(`is_missing_holding_table_error()` 로 구분).
    """
    if client is None:
        raise ReportError("Supabase 연결이 준비되지 않았습니다.")
    if not user_id:
        raise ReportError("로그인 정보가 없어 종목별 기록을 조회할 수 없습니다.")
    query = client.table(HOLDING_SNAPSHOTS_TABLE).select("*").eq("user_id", user_id)
    if market:
        query = query.eq("market", normalize_market(market))
    if start_date:
        query = query.gte("snapshot_date", to_date(start_date).isoformat())
    if end_date:
        query = query.lte("snapshot_date", to_date(end_date).isoformat())
    rows = _execute(query, "종목별 스냅샷 조회")
    return sort_holding_snapshots(rows)


# =============================================================================
# E. 배치 진입점
# =============================================================================
def resolve_session_info(data_dir=None):
    """
    "지금 저장하는 가격은 **어느 거래일** 것이고, **몇 시 몇 분에** 수집된 것인가"를 데이터
    스스로 말하게 합니다. 배치가 도는 시각(UTC)이 아니라 가격 스냅샷의 기준일을 쓰는 이유는,
    수집이 실패해 어제 파일이 그대로 남아 있을 때 그것을 '오늘 값'으로 둔갑시키지 않기
    위해서입니다(§0-1 · §0-3-1). 확인할 수 없으면 그 시장은 **기록하지 않습니다**(추측 금지).

    🕐 시:분(가격 수집 시각)에 대해 (2026-08-13 추가)
      · 원래 이 함수는 같은 메타데이터에서 **날짜만** 뽑고 시:분을 버렸습니다. 그런데 한국장은
        오후, 미국장은 한국시간 새벽에 수집돼서 "이 리포트가 언제 종가로 만들어졌나"가 리포트
        화면에 전혀 드러나지 않는다는 오너 피드백이 있었습니다(TASK_HISTORY #112).
      · KR : `last_updated_at` — 수집기가 이미 **한국시간**으로 적습니다.
      · US : `last_updated_at_kst` — 수집기가 이미 한국시간으로 **변환해 둔 값**을 그대로
             씁니다. ⚠️ `last_updated_at_et`(미국 동부시간)로 대체하지 않습니다 — 그건 KST 가
             아니어서, KST 라고 저장하는 순간 13~14시간 틀린 값을 사실처럼 보여주게 됩니다.
             ET 밖에 없으면 시각은 **없음(None)** 으로 둡니다(직접 시차 계산 금지 — 서머타임
             처리를 여기서 다시 구현하면 언젠가 반드시 틀립니다).
      · 시각을 못 읽어도 거래일만 확인되면 스냅샷은 **정상 저장**됩니다(시각만 NULL).

    반환: ({"KR": "2026-08-11", ...}, {"KR": "2026-08-11 17:50", ...}, [진단 문구, ...])
          — 두 번째 dict 는 값이 확인된 시장만 담습니다(빈 값을 넣지 않습니다).
    """
    notes = []
    dates = {}
    stamps = {}

    kr_meta = (load_snapshot_payload(MARKET_KR, data_dir=data_dir) or {}).get("metadata") or {}
    kr_stamp = kr_meta.get("last_updated_at")
    if kr_stamp:
        try:
            dates[MARKET_KR] = to_date(kr_stamp).isoformat()
            notes.append(f"KR 거래일 = {dates[MARKET_KR]} (kospi200_pegy_latest.json last_updated_at)")
        except ValueError:
            notes.append(f"KR 거래일 확인 실패: last_updated_at={kr_stamp!r}")
    else:
        notes.append("KR 거래일 확인 실패: 코스피 스냅샷(metadata.last_updated_at)이 없습니다.")

    kr_price_stamp = normalize_price_stamp(kr_stamp)
    if kr_price_stamp:
        stamps[MARKET_KR] = kr_price_stamp
        notes.append(f"KR 가격 수집 시각 = {kr_price_stamp} (KST, last_updated_at)")
    elif MARKET_KR in dates:
        notes.append(f"KR 가격 수집 시각 없음: last_updated_at={kr_stamp!r} 에 시:분이 없어 "
                     "시각은 비운 채(NULL) 저장합니다(추정하지 않음).")

    us_meta = (load_snapshot_payload(MARKET_US, data_dir=data_dir) or {}).get("metadata") or {}
    us_session = (us_meta.get("session_hint") or {}).get("session_date") \
        or us_meta.get("last_updated_at_et")
    if us_session:
        try:
            dates[MARKET_US] = to_date(us_session).isoformat()
            notes.append(f"US 거래일 = {dates[MARKET_US]} (us_stocks_latest.json session_hint)")
        except ValueError:
            notes.append(f"US 거래일 확인 실패: session_date={us_session!r}")
    else:
        notes.append("US 거래일 확인 실패: 미국 스냅샷(metadata.session_hint)이 없습니다.")

    us_price_stamp = normalize_price_stamp(us_meta.get("last_updated_at_kst"))
    if us_price_stamp:
        stamps[MARKET_US] = us_price_stamp
        notes.append(f"US 가격 수집 시각 = {us_price_stamp} (KST, last_updated_at_kst — "
                     "수집기가 변환해 둔 값 재사용)")
    elif MARKET_US in dates:
        notes.append("US 가격 수집 시각 없음: last_updated_at_kst 가 없어 시각은 비운 채(NULL) "
                     "저장합니다(ET 값을 KST 로 둔갑시키지 않습니다).")

    return dates, stamps, notes


def resolve_session_dates(data_dir=None):
    """
    `resolve_session_info()` 중 거래일만 필요한 호출부를 위한 얇은 래퍼(기존 시그니처 유지).
    반환: ({"KR": "2026-08-11", "US": "2026-08-11"}, [진단 문구, ...])
    """
    dates, _stamps, notes = resolve_session_info(data_dir=data_dir)
    return dates, notes


def build_price_lookup(data_dir=None):
    """
    "내 성적표" 화면과 **완전히 같은 방식**으로 현재가 조회 함수를 만듭니다
    (상위 200/550 유니버스 → 없으면 전 종목 가격 파일 → 미국은 ETF 목록까지 합침).
    화면과 스냅샷이 다른 가격을 쓰면 사용자가 본 숫자와 리포트가 어긋나기 때문입니다.
    """
    kr_index, _ = load_universe_index(MARKET_KR, data_dir=data_dir)
    us_index, _ = load_universe_index(MARKET_US, data_dir=data_dir)
    kr_all, _ = load_kr_all_market_prices(data_dir=data_dir)
    us_all, _ = load_us_all_market_prices(data_dir=data_dir)
    us_etf, _ = load_us_all_etf_prices(data_dir=data_dir)
    if us_etf:
        us_all = {**us_etf, **us_all}
    return make_price_lookup({MARKET_KR: kr_index, MARKET_US: us_index},
                             broad_kr_prices=kr_all, broad_us_prices=us_all)


def run_daily_snapshot_batch(service_client=None, data_dir=None, csv_path=None, dry_run=False):
    """
    매일 1회 도는 스냅샷 적재 배치의 본체.

      1) 가격 스냅샷 파일에서 시장별 거래일 + 가격 수집 시각(KST)을 확인 (resolve_session_info)
      2) 벤치마크 종가 확인 (코스피 CSV / 미국 지수 JSON) — 없으면 NULL 로 둡니다
      3) service_role 로 **모든 사용자** holdings 조회
      4) 사용자별·시장별 **합계 행 + 종목별 행**을 한 번에 생성 (순수 함수, 같은 계산 결과)
      5) upsert — **합계 먼저, 종목별 나중** (같은 날 두 번 돌려도 행이 늘지 않음)

    ⚠️ 저장 순서와 부분 실패 처리 (2026-08-13)
       두 표는 한 번의 트랜잭션으로 묶을 수 없습니다(Supabase REST 의 한계). 그래서 기존
       기능인 **합계를 먼저** 저장하고, 그 다음 종목별을 저장합니다. 근거와 각 실패 경우의
       동작은 `save_holding_snapshots()` 의 주석에 한곳으로 모아 적어 뒀습니다.

    dry_run=True 면 Supabase 에 쓰지 않고 계산 결과만 돌려줍니다(로컬 점검용).
    반환: 요약 dict (행 수, 사용자 수, 건너뛴 사유 등)
    """
    print("=" * 70)
    print("[리포트 스냅샷 배치] 시작")

    session_dates, price_stamps, notes = resolve_session_info(data_dir=data_dir)
    for note in notes:
        print(f"  · {note}")
    if not session_dates:
        raise ReportError(
            "어느 시장의 거래일도 확인하지 못했습니다 — 가격 스냅샷(data/*.json)이 없거나 "
            "형식이 바뀌었습니다. 값을 추측해서 저장하지 않고 중단합니다."
        )

    benchmarks = {}
    for market, session_date in session_dates.items():
        symbol, value = primary_benchmark_value(market, session_date,
                                                data_dir=data_dir, csv_path=csv_path)
        benchmarks[market] = (symbol, value)
        if value is None:
            print(f"  ⚠️ {market} 벤치마크({symbol}) {session_date} 종가가 없어 NULL 로 저장합니다"
                  "(전날 값을 복사하지 않습니다).")
        else:
            print(f"  · {market} 벤치마크 {symbol} {session_date} = {value}")

    price_lookup = build_price_lookup(data_dir=data_dir)

    if service_client is None and not dry_run:
        service_client = create_service_client()

    holdings = fetch_all_holdings(service_client) if service_client is not None else []
    grouped = group_holdings_by_user(holdings)
    print(f"  · 보유 종목 {len(holdings)}행 / 사용자 {len(grouped)}명")

    all_rows, all_holding_rows, all_skips = [], [], []
    for user_id, user_holdings in grouped.items():
        # 합계와 종목별을 **한 번의 계산**으로 함께 만듭니다(합계는 종목별의 합).
        rows, holding_rows, skips = build_snapshot_rows_with_holdings(
            user_id, user_holdings, price_lookup, session_dates, benchmarks,
            price_stamp_by_market=price_stamps,
        )
        all_rows.extend(rows)
        all_holding_rows.extend(holding_rows)
        all_skips.extend(skips)

    for skip in all_skips:
        print(f"  ⚠️ [{skip['market']}] 기록하지 않음 — {skip['reason']}")

    saved = 0
    holding_saved = 0
    holding_skipped_reason = None
    if dry_run:
        print(f"  · (dry-run) 저장하지 않고 계산만 했습니다 — 합계 {len(all_rows)}행 / "
              f"종목별 {len(all_holding_rows)}행")
    else:
        # ① 기존 기능(합계)이 먼저. 여기서 실패하면 예외가 나서 종목별은 시도조차 하지
        #    않습니다 — "종목별은 있는데 합계가 없는 날"을 만들지 않기 위해서입니다.
        saved = upsert_snapshots(service_client, all_rows)
        print(f"  ✅ 스냅샷 {saved}행 저장(갱신 포함)")

        # ② 종목별. 테이블이 아직 없으면 여기만 건너뛰고 배치는 정상 종료합니다.
        outcome = save_holding_snapshots(service_client, all_holding_rows, summary_saved=saved)
        holding_saved = outcome["saved"]
        holding_skipped_reason = outcome["skipped_reason"]
        if holding_saved:
            print(f"  ✅ 종목별 스냅샷 {holding_saved}행 저장(갱신 포함)")

    print("=" * 70)
    return {
        "session_dates": session_dates,
        "price_stamps": price_stamps,
        "benchmarks": {m: {"symbol": s, "value": v} for m, (s, v) in benchmarks.items()},
        "user_count": len(grouped),
        "holdings_count": len(holdings),
        "rows": all_rows,
        "holding_rows": all_holding_rows,
        "saved": saved,
        "holding_saved": holding_saved,
        "holding_skipped_reason": holding_skipped_reason,
        "skipped": all_skips,
        "dry_run": bool(dry_run),
        "notes": notes,
    }


def main(argv=None):
    """
    CLI — GitHub Actions 워크플로우가 부르는 진입점입니다.

        python -m utils.report_db snapshot            # 실제 적재
        python -m utils.report_db snapshot --dry-run  # Supabase 없이 계산만(로컬 점검)
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "snapshot"
    dry_run = "--dry-run" in argv

    if command != "snapshot":
        print("사용법: python -m utils.report_db snapshot [--dry-run]")
        return 2
    try:
        run_daily_snapshot_batch(dry_run=dry_run)
    except (ReportError, ScorecardError) as exc:
        # 배치는 조용히 성공한 척하면 안 됩니다 — 실패는 비정상 종료로 알립니다.
        print(f"❌ 리포트 스냅샷 배치 실패: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
