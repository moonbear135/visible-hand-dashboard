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
REPORT_SIMPLE_RETURN_NOTICE = (
    "⚠️ 이 리포트의 수익률은 **구간 시작 스냅샷과 종료 스냅샷의 단순 비교**입니다. "
    "중간에 종목을 사고팔면 그 영향이 수익률에 섞입니다(시간가중수익률(TWR) 같은 정교한 "
    "계산은 v1 범위 밖입니다). 구성이 바뀐 구간에는 안내 문구가 함께 표시됩니다."
)
REPORT_NO_BACKFILL_NOTICE = (
    "⚠️ 스냅샷은 이 기능을 켠 날부터 쌓입니다 — 그 전 기간은 과거 시세로 역산하지 않고 "
    "'데이터 부족'으로 표시합니다(없는 기록을 만들어내지 않습니다)."
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
def build_snapshot_rows(user_id, holdings, price_lookup,
                        session_date_by_market, benchmark_by_market=None,
                        price_stamp_by_market=None):
    """
    사용자 1명의 보유 종목 → 그날 저장할 스냅샷 행 목록(시장별 최대 1행).

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

    반환: (rows, skipped)
      rows    : Supabase 에 그대로 넣을 dict 목록
      skipped : [{"market":..., "reason":...}] — 왜 안 만들었는지(§0-1, 조용히 넘기지 않음)

    ⚠️ 총평가금액·총매입원가는 **그날 현재가를 아는 종목만** 합산합니다. 값을 모르는 종목을
       0원으로 넣으면 그 자체가 지어낸 숫자이고, 다음 날 그 종목 가격이 들어오는 순간
       "하루 만에 수천만원 상승"처럼 보이는 가짜 수익률이 생깁니다.
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

    rows, skipped = [], []
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
                # 않고 사유를 남깁니다(§0-1 — 조용히 사라지면 안 됨).
                skipped.append({
                    "market": market,
                    "reason": f"보유 행을 평가할 수 없어 제외: {holding.get('ticker')!r} ({exc})",
                })

        priced = [row for row in evaluated if row["price_available"]]
        if not priced:
            skipped.append({
                "market": market,
                "reason": (f"{len(evaluated)}개 종목 모두 그날 현재가를 알 수 없어 스냅샷을 "
                           "만들지 않았습니다(0원으로 기록하지 않습니다)."),
            })
            continue

        symbol, value = benchmark_by_market.get(market, (None, None))
        rows.append({
            "user_id": user_id,
            "market": market,
            "snapshot_date": to_date(session_date).isoformat(),
            "total_value": round(sum(r["market_value"] for r in priced), 6),
            "total_cost": round(sum(r["cost"] for r in priced), 6),
            "currency": currency_for_market(market),
            "holdings_count": len(evaluated),
            "priced_count": len(priced),
            "unpriced_count": len(evaluated) - len(priced),
            "benchmark_symbol": symbol,
            "benchmark_value": (round(float(value), 6) if value is not None else None),
            # 시:분을 모르면 None(=NULL). 오늘 시각이나 장 마감 시각으로 메우지 않습니다(§0-1).
            PRICE_STAMP_FIELD: normalize_price_stamp(price_stamp_by_market.get(market)),
        })
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
        result["status_message"] = (
            f"{result['period_title']}은(는) 아직 진행 중입니다 — "
            f"{result['covered_to'].isoformat()} 까지의 중간 집계이며, "
            "정식 리포트는 기간이 끝난 뒤에 확정됩니다."
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
      4) 사용자별·시장별 스냅샷 행 생성 (순수 함수)
      5) upsert (같은 날 두 번 돌려도 행이 늘지 않음)

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

    all_rows, all_skips = [], []
    for user_id, user_holdings in grouped.items():
        rows, skips = build_snapshot_rows(
            user_id, user_holdings, price_lookup, session_dates, benchmarks,
            price_stamp_by_market=price_stamps,
        )
        all_rows.extend(rows)
        all_skips.extend(skips)

    for skip in all_skips:
        print(f"  ⚠️ [{skip['market']}] 기록하지 않음 — {skip['reason']}")

    saved = 0
    if dry_run:
        print(f"  · (dry-run) 저장하지 않고 계산만 했습니다 — 대상 {len(all_rows)}행")
    else:
        saved = upsert_snapshots(service_client, all_rows)
        print(f"  ✅ 스냅샷 {saved}행 저장(갱신 포함)")

    print("=" * 70)
    return {
        "session_dates": session_dates,
        "price_stamps": price_stamps,
        "benchmarks": {m: {"symbol": s, "value": v} for m, (s, v) in benchmarks.items()},
        "user_count": len(grouped),
        "holdings_count": len(holdings),
        "rows": all_rows,
        "saved": saved,
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
