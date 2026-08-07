"""
collector_us_stocks.py
🇺🇸 미국주식("미국 주식은 이가격") 수집기 — 기초틀 (2026-08-06 착수)

2026-08-07 확장: 550종목 **전수 수집(collect)** + 2차 패스 스코어링 + 상단 지수 3종 수집 추가.
   (스코어링은 `utils/scoring_us.py`, 한글 표기는 `utils/company_names_kr.py`,
    화면은 `views/us_stocks_view.py` 로 분리되어 있습니다.)

2026-08-07 오후 추가 수정(오너 로컬 실측 2회차에서 드러난 문제 대응):
  - 지수 3종 소스를 Stooq(HTTP 404 확인됨) → stockanalysis.com ETF 프록시(SPY/ONEQ/DIA)로 교체.
  - "Index Tracked" 라벨이 표(<table>)가 아니라 표 밖 "About" 섹션에 있어 못 찾던 문제 수정.
  - 550종목 수집이 HTTP 429로 중간에 끊기는 문제 — 배치 휴지기(60→40종목마다, 90→120초)를
    보강했지만 여전히 재발할 수 있어, **끊기면 진행상황을 저장하고 다음 실행이 이어서 진행**하는
    체크포인트(`data/us_collect_checkpoint.json`)를 추가(같은 세션 날짜에서만 재사용, §0-1).

⚠️ 기존 코스피 파이프라인(`collector_kospi200.py`, `views/pegy_view.py`,
   `utils/scoring.py`, `utils/constants.py`)은 이 파일에서 import 하지도, 수정하지도
   않습니다 (ENGINEERING_SPEC §0-3-6 신규 기능 모듈 분리 원칙).

지켜야 할 원칙 요약
  - §0-1 지어내지 않기: 파싱 실패/미제공은 전부 None + 사유 기록. 0 이나 평균값으로 메우지 않음.
  - §0-3-1 후행지표 전용: 프리마켓/애프터마켓 시세는 절대 쓰지 않고 '장마감 종가'만 사용.
  - §0-3-2 크롤링 매너: 종목당 2~3초 랜덤 슬립, 차단(403/429) 시 재시도 반복 없이 중단.
  - §0-3-3 다중 출처 + raw/가공 분리 보관: 유니버스 CSV ↔ 통계 페이지 시총 교차검증,
    raw(label-value 원문)와 가공 결과를 별도 파일로 저장.
  - §2-1 위치 인덱스 파싱 금지: 표에서 "N번째 열"을 집지 않고, 각 행의 **라벨 텍스트**를
    키워드로 매칭해 값을 가져옵니다.

CLI
  python collector_us_stocks.py schedule            # ET/KST/UTC 수집 시점 계산 결과 출력
  python collector_us_stocks.py universe            # 유니버스 CSV 수집 + 필터 + 저장
  python collector_us_stocks.py sample --count 12   # 샘플 종목 수집 프로토타입(소요시간 실측)
  python collector_us_stocks.py sample --tickers BRK.B,JPM,CAVA
  python collector_us_stocks.py indices             # 상단 지수 3종 소스 점검 (⚠️ 실측 미검증 소스)
  python collector_us_stocks.py collect --limit 5   # 전수 수집 경로 동작 확인(5종목만)
  python collector_us_stocks.py collect             # 🇺🇸 550종목 전수 수집 (약 40~56분, 배치 휴지기 포함)
  python collector_us_stocks.py collect --skip-if-not-ready
                                                    # 무인 자동화(GitHub Actions) 전용 — 아직 수집
                                                    # 시점이 아니거나 이미 그 거래일을 수집했으면
                                                    # 아무것도 안 하고 정상 종료(exit 0)
"""

import argparse
import csv
import io
import json
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from utils.constants_us import (
    US_UNIVERSE_CSV_URL,
    US_STATISTICS_URL_TEMPLATE,
    US_UNIVERSE_REQUIRED_COLUMNS,
    US_TARGET_UNIVERSE_SIZE,
    US_HYSTERESIS_ENTRY_RANK,
    US_HYSTERESIS_EXIT_RANK,
    US_UNIVERSE_MIN_RAW_ROWS,
    US_CRAWL_DELAY_MIN_SEC,
    US_CRAWL_DELAY_MAX_SEC,
    US_CRAWL_BATCH_SIZE,
    US_CRAWL_BATCH_COOLDOWN_SEC,
    US_COLLECT_CHECKPOINT_FILENAME,
    US_REQUEST_TIMEOUT_SEC,
    US_MAX_RETRIES,
    US_RETRY_BASE_DELAY_SEC,
    US_BLOCK_STATUS_CODES,
    US_USER_AGENT,
    US_MARKET_TIMEZONE,
    US_MARKET_CLOSE_HOUR,
    US_MARKET_CLOSE_MINUTE,
    US_COLLECT_AFTER_CLOSE_MINUTES,
    US_MARKETCAP_CROSSCHECK_TOLERANCE,
    US_UNIVERSE_FILENAME,
    US_SAMPLE_DIRNAME,
    US_SNAPSHOT_FILENAME,
    US_RAW_SNAPSHOT_FILENAME,
    US_SUMMARY_HISTORY_FILENAME,
    US_VALID_RATIO_SUCCESS,
    US_VALID_RATIO_DEGRADED,
    US_INDEX_PROXY_URL_TEMPLATE,
    US_INDEX_DEFINITIONS,
)
from utils.scoring_us import derive_valuation, apply_us_guardrail, score_all
from utils.company_names_kr import resolve_korean_name

# =============================================================================
# 0. 타임존 헬퍼 (US_STOCKS_WORK_ORDER.md §5-2 — 이번 작업 최대 함정)
#
# 오늘(2026-08-06) 코스피 쪽에서 naive `datetime.now()` 가 GitHub Actions(UTC)에서
# 9시간 어긋나는 버그를 겪었습니다. 미국장은 서머타임까지 겹쳐 더 위험하므로
# **처음부터** ZoneInfo 를 명시합니다. KST 는 화면 표시용으로만 씁니다.
# =============================================================================
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo(US_MARKET_TIMEZONE)
    KST = ZoneInfo("Asia/Seoul")
    UTC = ZoneInfo("UTC")
except Exception:  # Python 3.8 이하 등 zoneinfo 미지원 환경
    ET = None
    KST = None
    UTC = None


def _now_et():
    """미국 동부시간(America/New_York) 현재 시각. 서머타임(EDT/EST)은 자동 반영됩니다."""
    if ET is None:
        raise RuntimeError(
            "zoneinfo 를 사용할 수 없어 ET 시각을 계산할 수 없습니다 — "
            "타임존을 추측해서 진행하지 않고 중단합니다(ENGINEERING_SPEC §0-1)."
        )
    return datetime.now(ET)


def _now_kst():
    """화면 표시용 KST 현재 시각 (수집 로직 판단에는 절대 쓰지 말 것)."""
    if KST is None:
        raise RuntimeError("zoneinfo 를 사용할 수 없어 KST 시각을 계산할 수 없습니다.")
    return datetime.now(KST)


def us_regular_close_et(day):
    """주어진 날짜(date)의 미국 정규장 마감 시각(ET, tz-aware)."""
    return datetime(
        day.year, day.month, day.day,
        US_MARKET_CLOSE_HOUR, US_MARKET_CLOSE_MINUTE, tzinfo=ET
    )


def resolve_collection_session_et(now_et=None):
    """
    "지금 수집한다면 어느 거래일(session)의 장마감 데이터를 담게 되는가"를 ET 기준으로 계산합니다.

    규칙: 마감(16:00 ET) + US_COLLECT_AFTER_CLOSE_MINUTES(30분) 이 지난 가장 최근 평일.

    ⚠️ 미국 증시 휴장일(추수감사절·독립기념일 등)은 여기서 판정하지 않습니다.
       공휴일 캘린더를 코드에 하드코딩하면 매년 틀리고(§0-1 지어내기), 무료 공개
       캘린더 소스는 아직 조사 전이기 때문입니다. 대신 **실제 세션 날짜는 수집한
       페이지 자체의 "At close: ..." 타임스탬프에서 읽어와**(parse_close_timestamp)
       이 계산값과 다르면 그 사실을 기록합니다. 즉 이 함수의 결과는 '스케줄 힌트'이고,
       확정 세션 날짜의 출처는 언제나 원본 페이지입니다.

    반환: dict
      session_date          : 예상 대상 거래일 (YYYY-MM-DD, ET 기준)
      close_at_et           : 그 거래일의 마감 시각(ET)
      collect_ready_at_et   : 수집 가능 시각(마감+30분, ET)
      is_ready_now          : 지금이 그 시각을 지났는가
      holiday_calendar_applied : False 고정 (위 주의사항 참고)
    """
    now = now_et or _now_et()
    probe = now.date()
    # 오늘 마감+30분이 아직 안 지났으면 어제부터 거슬러 올라갑니다.
    while True:
        close_at = us_regular_close_et(probe)
        ready_at = close_at + timedelta(minutes=US_COLLECT_AFTER_CLOSE_MINUTES)
        is_weekday = probe.weekday() < 5   # 월(0)~금(4)
        if is_weekday and now >= ready_at:
            break
        probe = probe - timedelta(days=1)

    return {
        "session_date": probe.isoformat(),
        "close_at_et": close_at.isoformat(),
        "collect_ready_at_et": ready_at.isoformat(),
        "collect_ready_at_kst": ready_at.astimezone(KST).isoformat() if KST else None,
        "collect_ready_at_utc": ready_at.astimezone(UTC).isoformat() if UTC else None,
        "is_ready_now": now >= ready_at,
        "now_et": now.isoformat(),
        "now_kst": now.astimezone(KST).isoformat() if KST else None,
        "tz_abbrev": now.tzname(),          # EDT(서머타임) / EST(표준시)
        "holiday_calendar_applied": False,
    }


def describe_collection_schedule(now_et=None):
    """
    GitHub Actions cron(UTC 고정) 설계를 위한 참고 정보를 계산합니다.
    ⚠️ 서머타임 때문에 "마감+30분"의 UTC 시각이 1년에 두 번 바뀝니다 —
       cron 을 한 줄로 고정하면 반년 동안 30분~1시간 어긋납니다.
    """
    now = now_et or _now_et()
    session = resolve_collection_session_et(now)
    ready_et = datetime.fromisoformat(session["collect_ready_at_et"])
    ready_utc = ready_et.astimezone(UTC)
    ready_kst = ready_et.astimezone(KST)
    return {
        **session,
        "cron_hint_utc": f"{ready_utc.minute} {ready_utc.hour} * * 1-5",
        "cron_note": (
            f"현재 미국 동부는 {now.tzname()} 입니다. 마감+30분 = "
            f"{ready_et.strftime('%H:%M')} ET = {ready_utc.strftime('%H:%M')} UTC = "
            f"{ready_kst.strftime('%H:%M')} KST(다음날 새벽). 서머타임이 바뀌면 UTC 시각이 "
            "1시간 이동하므로, cron 을 두 개 걸어두고 스크립트 안에서 ET 기준으로 "
            "'아직 마감+30분 전이면 아무것도 하지 않고 종료' 하도록 방어하는 방식을 권장합니다."
        ),
    }


# =============================================================================
# 1. 종목 유니버스 — CSV 수집 + 상품유형 분류 + 필터
# =============================================================================
class USSourceBlockedError(RuntimeError):
    """상대 서버가 우리를 차단(403/429 등)했을 때. 재시도를 반복하지 않고 즉시 중단합니다."""


def _polite_sleep():
    time.sleep(random.uniform(US_CRAWL_DELAY_MIN_SEC, US_CRAWL_DELAY_MAX_SEC))


def _polite_sleep_with_batch_cooldown(request_index):
    """
    2026-08-07 추가: 550종목 전수수집 실측에서 187종목째(약 11분)에 HTTP 429 차단을
    겪은 뒤 도입한 완화책. 종목당 슬립은 그대로 두고, US_CRAWL_BATCH_SIZE개마다 한 번
    더 긴 휴지기를 얹어 총 요청 '밀도'를 낮춥니다(§0-3-2 정중한 크롤링 정신 연장 —
    차단된 요청을 재시도하는 게 아니라, 애초에 차단당할 확률 자체를 낮추는 예방책).
    """
    _polite_sleep()
    if request_index % US_CRAWL_BATCH_SIZE == 0:
        print(f"  💤 배치 휴지기: {request_index}종목 처리 후 {US_CRAWL_BATCH_COOLDOWN_SEC}초 추가 대기")
        time.sleep(US_CRAWL_BATCH_COOLDOWN_SEC)


def _http_get(url, timeout=None):
    """
    정중한 GET. 일시적 오류는 지수 백오프로 재시도하지만, '차단' 신호(403/429 등)는
    재시도하지 않고 USSourceBlockedError 로 즉시 중단합니다 (§0-3-2).
    반환: requests.Response
    """
    headers = {"User-Agent": US_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    last_error = None
    for attempt in range(US_MAX_RETRIES):
        try:
            res = requests.get(url, headers=headers, timeout=timeout or US_REQUEST_TIMEOUT_SEC)
            if res.status_code in US_BLOCK_STATUS_CODES:
                raise USSourceBlockedError(
                    f"소스가 요청을 차단했습니다 (HTTP {res.status_code}) — {url}\n"
                    "재시도를 반복하지 않고 중단합니다(ENGINEERING_SPEC §0-3-2). "
                    "차단 사유를 확인한 뒤 수집 주기를 늘리거나 대체 소스를 검토하세요."
                )
            if res.status_code == 200:
                return res
            last_error = f"HTTP {res.status_code}"
        except USSourceBlockedError:
            raise
        except requests.exceptions.RequestException as e:
            last_error = str(e)
        time.sleep(US_RETRY_BASE_DELAY_SEC * (2 ** attempt) + random.uniform(0.1, 0.5))
    raise RuntimeError(f"요청 실패({last_error}) — {url}")


# -----------------------------------------------------------------------------
# 상품 유형 분류 (SPEC §2-2: 개별 종목 코드 하드코딩 금지 — 전부 이름 키워드 규칙)
# -----------------------------------------------------------------------------
# ① 채권/노트류: 이자율(%)과 Notes/Debentures/Bonds 가 함께 등장 (오너 확정 규칙)
_BOND_KEYWORDS = ("notes", "debenture", "debentures", "bond", "bonds")
# ② 미국식 우선주: 이름에 "Preferred Stock/Shares" 가 명시 (오너 확정 규칙)
#    ⚠️ 회사명에 'Preferred' 가 들어가는 보통주(예: Preferred Bank)를 잡지 않도록
#       반드시 '구(phrase)' 로 매칭합니다.
_PREFERRED_PATTERNS = (r"preferred\s+stock", r"preferred\s+shares?")
# ③ ETF/펀드류 (오너 원안: ETF 제외). CSV 자체가 주식 스크리너 기반이라 거의 없지만 방어적으로.
_FUND_PATTERNS = (r"\betf\b", r"\betn\b", r"exchange[- ]traded", r"index\s+fund")
# ④ 보통주가 아닌 파생·하이브리드 상품 (🚩 오너 확정 규칙에는 없는 추가 분류 — §7 확인 필요)
_NON_COMMON_PATTERNS = (
    (r"\bwarrants?\b", "warrant"),
    (r"\brights\b", "rights"),
    (r"\b(corporate|equity)\s+units\b", "hybrid_units"),
    (r"\bstrats\b", "structured_trust"),
    (r"structured\s+products?", "structured_trust"),
    (r"\btrust\s+for\b", "structured_trust"),
)


def classify_instrument(name):
    """
    종목명(영문)으로 상품 유형을 분류합니다. 반환값:
      "common"          — 보통주(또는 ADR/MLP 보통유닛). 유니버스에 포함.
      "bond_note"       — 채권/노트/사채. 제외 (오너 확정).
      "preferred"       — 미국식 우선주. 제외 (오너 확정).
      "fund"            — ETF/ETN/인덱스펀드. 제외 (오너 원안).
      "warrant" / "rights" / "hybrid_units" / "structured_trust"
                        — 보통주가 아닌 파생·하이브리드 상품. 🚩 오너 확인 대기 항목.

    ⚠️ 복수 보통주 클래스(GOOGL/GOOG, BRK/A·BRK/B)는 의결권만 다른 보통주이므로
       여기서 걸러지지 않으며, 오너 확정대로 **전부 포함**됩니다(중복 제거 안 함).
    """
    if not name:
        return "common"
    low = " ".join(str(name).lower().split())

    # ① 채권/노트: 이자율 표기(%)와 채권 키워드가 함께 있을 때만 (오너 확정 문구 그대로)
    if "%" in low and any(kw in low for kw in _BOND_KEYWORDS):
        return "bond_note"
    # 이자율 표기가 없는 채권 이름도 실재합니다(예: "First Mortgage Bonds ... Series").
    # 다만 이 경우도 '보통주'라는 단어가 함께 오지는 않으므로 안전하게 함께 처리합니다.
    if re.search(r"\b(first\s+mortgage\s+bonds?|subordinated\s+(notes?|debentures?))\b", low):
        return "bond_note"

    # ② 미국식 우선주
    if any(re.search(p, low) for p in _PREFERRED_PATTERNS):
        return "preferred"

    # ③ ETF/펀드류
    if any(re.search(p, low) for p in _FUND_PATTERNS):
        return "fund"

    # ④ 보통주가 아닌 파생/하이브리드 상품
    for pattern, kind in _NON_COMMON_PATTERNS:
        if re.search(pattern, low):
            return kind

    return "common"


def parse_universe_csv(csv_text):
    """
    유니버스 CSV(text)를 파싱합니다. 컬럼 구조가 예상과 다르면(소스 변경) 즉시 중단합니다.
    반환: list[dict] — symbol / name / price / market_cap / volume / industry
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    missing = [c for c in US_UNIVERSE_REQUIRED_COLUMNS if c not in header]
    if missing:
        raise RuntimeError(
            f"유니버스 CSV 컬럼 구조가 예상과 다릅니다(누락: {missing}, 실제: {header}) — "
            "소스 구조 변경 가능성이 있어 수집을 중단합니다(기존 데이터 유지)."
        )

    rows = []
    malformed = 0
    for r in reader:
        symbol = (r.get("symbol") or "").strip()
        name = (r.get("name") or "").strip()
        if not symbol:
            malformed += 1
            continue
        try:
            market_cap = float(r["marketCap"]) if r.get("marketCap") else None
        except (TypeError, ValueError):
            market_cap = None
        try:
            price = float(r["price"]) if r.get("price") else None
        except (TypeError, ValueError):
            price = None
        if market_cap is None or market_cap <= 0:
            # 시가총액이 없으면 순위를 매길 수 없습니다 — 지어내지 않고 제외 + 기록.
            malformed += 1
            continue
        rows.append({
            "symbol": symbol,
            "name": name,
            "csv_price": price,
            "csv_market_cap": market_cap,
            "industry": (r.get("industry") or "").strip() or None,
        })
    if malformed:
        print(f"  [유니버스 CSV] 파싱 불가/시총 결측 행 {malformed}개 제외")
    return rows


def fetch_universe_rows(url=None):
    """유니버스 CSV 를 내려받아 파싱합니다."""
    url = url or US_UNIVERSE_CSV_URL
    print(f"[유니버스] CSV 수집: {url}")
    res = _http_get(url)
    rows = parse_universe_csv(res.text)
    print(f"[유니버스] 원본 {len(rows)}행 파싱 완료")
    return rows


def filter_universe(rows, target_size=None, exclude_non_common=True):
    """
    US_STOCKS_WORK_ORDER.md §3-2 필터를 적용해 상위 target_size 개 종목을 고릅니다.

    - 정렬: 시가총액 내림차순(소스가 이미 정렬돼 있지만 신뢰하지 않고 직접 확인·재정렬).
    - 제외: 채권/노트, 미국식 우선주, ETF/펀드 (+ exclude_non_common 이면 워런트·라이츠·
      하이브리드 유닛·구조화신탁 — 🚩 오너 확정 규칙 밖의 추가 분류)
    - 복수 보통주 클래스(GOOGL/GOOG 등)는 중복 제거하지 않고 전부 포함(오너 확정).

    반환: (selected, stats)
    """
    target_size = target_size or US_TARGET_UNIVERSE_SIZE

    if len(rows) < US_UNIVERSE_MIN_RAW_ROWS:
        raise RuntimeError(
            f"유니버스 CSV 행 수가 비정상적으로 적습니다({len(rows)} < {US_UNIVERSE_MIN_RAW_ROWS}) — "
            "소스 갱신 중단/파일 손상 가능성이 있어 수집을 중단하고 기존 데이터를 유지합니다."
        )

    caps = [r["csv_market_cap"] for r in rows]
    already_sorted = all(caps[i] >= caps[i + 1] for i in range(len(caps) - 1))
    if not already_sorted:
        print("  ⚠️ [유니버스] CSV가 시가총액 내림차순이 아니어서 직접 재정렬합니다.")
        rows = sorted(rows, key=lambda r: r["csv_market_cap"], reverse=True)

    excluded_kinds = {"bond_note", "preferred", "fund"}
    if exclude_non_common:
        excluded_kinds |= {"warrant", "rights", "hybrid_units", "structured_trust"}

    selected = []
    counts = {}
    examples = {}
    for r in rows:
        kind = classify_instrument(r["name"])
        counts[kind] = counts.get(kind, 0) + 1
        if kind in excluded_kinds:
            examples.setdefault(kind, []).append(f"{r['symbol']} — {r['name'][:80]}")
            continue
        if len(selected) >= target_size:
            continue
        r = dict(r)
        r["rank"] = len(selected) + 1
        r["instrument_kind"] = kind
        selected.append(r)

    # 목표 개수를 못 채웠으면 조용히 넘어가지 않고 명확히 남깁니다.
    shortfall = target_size - len(selected)

    stats = {
        "raw_rows": len(rows),
        "target_size": target_size,
        "final_count": len(selected),
        "shortfall": shortfall if shortfall > 0 else 0,
        "excluded_bond_note": counts.get("bond_note", 0),
        "excluded_preferred": counts.get("preferred", 0),
        "excluded_fund": counts.get("fund", 0),
        "excluded_warrant": counts.get("warrant", 0),
        "excluded_rights": counts.get("rights", 0),
        "excluded_hybrid_units": counts.get("hybrid_units", 0),
        "excluded_structured_trust": counts.get("structured_trust", 0),
        "exclude_non_common_applied": exclude_non_common,
        "market_cap_floor": selected[-1]["csv_market_cap"] if selected else None,
        "market_cap_top": selected[0]["csv_market_cap"] if selected else None,
        "excluded_examples": {k: v[:10] for k, v in examples.items()},
        "resorted": not already_sorted,
    }
    return selected, stats


def print_universe_stats(stats):
    print("=" * 70)
    print("[유니버스 필터 결과]")
    print(f"  원본 행 수                : {stats['raw_rows']}")
    print(f"  제외 — 채권/노트          : {stats['excluded_bond_note']}")
    print(f"  제외 — 미국식 우선주      : {stats['excluded_preferred']}")
    print(f"  제외 — ETF/펀드           : {stats['excluded_fund']}")
    print(f"  제외 — 워런트             : {stats['excluded_warrant']}  🚩오너 확인 대기")
    print(f"  제외 — 라이츠             : {stats['excluded_rights']}  🚩오너 확인 대기")
    print(f"  제외 — 하이브리드 유닛    : {stats['excluded_hybrid_units']}  🚩오너 확인 대기")
    print(f"  제외 — 구조화 신탁/STRATS : {stats['excluded_structured_trust']}  🚩오너 확인 대기")
    print(f"  최종 종목 수              : {stats['final_count']} (목표 {stats['target_size']})")
    if stats["shortfall"]:
        print(f"  ⚠️ 목표 대비 부족          : {stats['shortfall']}개 — 소스 행 수 부족")
    if stats["market_cap_floor"]:
        print(f"  시가총액 컷오프           : ${stats['market_cap_floor']/1e9:,.2f}B "
              f"(1위 ${stats['market_cap_top']/1e12:,.2f}T)")
    for kind, samples in stats["excluded_examples"].items():
        print(f"  · 제외 예시({kind}): {samples[0] if samples else '-'}")
    print("=" * 70)


# -----------------------------------------------------------------------------
# 히스테리시스 버퍼 (collector_kospi200.apply_hysteresis_buffer 패턴 재사용)
# -----------------------------------------------------------------------------
def load_previously_tracked_symbols(json_path):
    """직전 회차에 추적 중이던 티커 집합. 파일이 없거나 깨졌으면 빈 집합(=단순 컷과 동일)."""
    try:
        if not os.path.exists(json_path):
            return set()
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return {s["symbol"] for s in payload.get("stocks", []) if s.get("symbol")}
    except Exception as e:
        print(f"⚠️ 직전 추적 목록 로드 실패(빈 목록으로 진행): {e}")
        return set()


def apply_us_hysteresis_buffer(candidates, previous_symbols,
                               entry_rank=None, exit_rank=None):
    """
    진입 entry_rank(550위) / 이탈 exit_rank(600위) 히스테리시스.
    화면 노출은 항상 entry_rank 개까지만(is_visible), 버퍼 구간은 수집만 하고 숨깁니다.
    (코스피 200/230 로직과 동일한 규칙 — 상수만 미국용으로 교체)
    """
    entry_rank = entry_rank or US_HYSTERESIS_ENTRY_RANK
    exit_rank = exit_rank or US_HYSTERESIS_EXIT_RANK

    tracked = []
    for idx, c in enumerate(candidates):
        rank = idx + 1
        if rank <= entry_rank:
            keep = True
        elif c.get("symbol") in previous_symbols and rank <= exit_rank:
            keep = True
        else:
            keep = False
        if keep:
            c = dict(c)
            c["rank"] = rank
            c["is_visible"] = rank <= entry_rank
            tracked.append(c)

    buffer_count = sum(1 for c in tracked if not c["is_visible"])
    if buffer_count:
        print(f"📎 히스테리시스 버퍼: {entry_rank}위 밖 {buffer_count}개 종목을 화면 비노출로 계속 추적")
    return tracked


# =============================================================================
# 2. 펀더멘털 페이지 파싱 (stockanalysis.com /statistics/)
# =============================================================================
def build_statistics_url(symbol):
    """
    티커를 통계 페이지 URL 로 변환합니다.
    ⚠️ 유니버스 CSV 는 클래스 구분에 슬래시를 씁니다(BRK/A, BRK/B). stockanalysis.com 은
       점(BRK.A, BRK.B)을 쓰므로 변환이 필요합니다(2026-08-06 BRK.B 로 실측 확인).
    """
    ticker = str(symbol).strip().upper().replace("/", ".")
    return US_STATISTICS_URL_TEMPLATE.format(ticker=ticker)


_NA_TOKENS = {"n/a", "na", "-", "--", "—", "–", ""}
_PAYWALL_TOKENS = {"upgrade", "unlock", "pro"}


def _normalize_label(text):
    """라벨 텍스트 정규화(소문자·공백 축약). 표의 '위치'가 아니라 이 라벨로만 값을 찾습니다."""
    return " ".join(str(text).replace("\xa0", " ").split()).strip().lower()


def extract_label_value_pairs(html):
    """
    페이지의 모든 2열 이상 표에서 (라벨, 값) 쌍을 추출합니다.
    ⚠️ SPEC §2-1: 열 번호(iloc)를 고정하지 않습니다. 각 행의 **첫 셀 = 라벨, 마지막 셀 = 값**
       이라는 key-value 표 구조만 사용하며, 어떤 지표를 쓸지는 라벨 키워드로 결정합니다.
    같은 라벨이 여러 번 나오면 처음 것만 사용합니다(중복 표 방어).
    """
    soup = BeautifulSoup(html, "html.parser")
    pairs = []
    seen = set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = _normalize_label(cells[0].get_text(" ", strip=True))
            value = " ".join(cells[-1].get_text(" ", strip=True).split())
            if not label or label in seen:
                continue
            seen.add(label)
            pairs.append((label, value))
    return pairs


def _value_state(raw):
    """값 문자열의 상태를 판정합니다: ('ok'|'na'|'paywall', 정리된 문자열)"""
    if raw is None:
        return "na", ""
    s = " ".join(str(raw).split())
    low = s.lower()
    if low in _NA_TOKENS:
        return "na", s
    if low in _PAYWALL_TOKENS:
        return "paywall", s
    return "ok", s


_SCALE_SUFFIX = {"t": 1e12, "b": 1e9, "m": 1e6, "k": 1e3}


def parse_scaled_number(raw):
    """'1.12T' / '-1,793.09B' / '846,430' / '$5.52' / '+26.61%' → float. 실패하면 None."""
    state, s = _value_state(raw)
    if state != "ok":
        return None
    s = s.replace("$", "").replace(",", "").replace("%", "").replace("+", "").strip()
    if not s:
        return None
    mult = 1.0
    if s[-1].lower() in _SCALE_SUFFIX:
        mult = _SCALE_SUFFIX[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_int(raw):
    v = parse_scaled_number(raw)
    return int(round(v)) if v is not None else None


def parse_text(raw):
    state, s = _value_state(raw)
    return s if state == "ok" else None


# -----------------------------------------------------------------------------
# 라벨 → 우리 필드 매핑 (키워드 기반 동적 타겟팅)
#   kind: number(비율/배수) / percent(%) / money(통화·스케일) / int / text
#   ⚠️ 값이 없으면 반드시 None. 0 이나 평균값으로 채우지 않습니다(§0-1).
# -----------------------------------------------------------------------------
FIELD_SPECS = [
    # (라벨, 필드명, 종류, 설명)
    ("market cap",                          "market_cap",        "money",   "시가총액"),
    ("enterprise value",                    "enterprise_value",  "money",   "기업가치(EV)"),
    ("shares outstanding",                  "outstanding_shares", "money",  "발행주식수(스케일 표기)"),
    ("shares change (yoy)",                 "shares_change_yoy", "percent", "발행주식수 증감(YoY)"),
    ("pe ratio",                            "t_per",             "number",  "Trailing PER"),
    ("forward pe",                          "f_per",             "number",  "Forward PER"),
    ("peg ratio",                           "peg",               "number",  "PEG(사이트 제공값)"),
    ("pb ratio",                            "t_pbr",             "number",  "PBR"),
    ("ps ratio",                            "ps",                "number",  "PSR"),
    ("forward ps",                          "forward_ps",        "number",  "Forward PSR"),
    ("price/ffo ratio",                     "price_ffo",         "number",  "P/FFO (리츠 전용)"),
    ("ev / ebitda",                         "ev_ebitda",         "number",  "EV/EBITDA"),
    ("return on equity (roe)",              "t_roe",             "percent", "Trailing ROE"),
    ("return on invested capital (roic)",   "roic",              "percent", "ROIC"),
    ("return on assets (roa)",              "roa",               "percent", "ROA"),
    ("weighted average cost of capital (wacc)", "wacc",          "percent", "WACC"),
    ("beta (5y)",                           "beta",              "number",  "베타(5년)"),
    ("52-week price change",                "price_change_52w",  "percent", "52주 주가 변동률"),
    ("earnings per share (eps)",            "t_eps",             "money",   "Trailing EPS(흑자 기업)"),
    ("loss per share",                      "t_eps",             "money",   "Trailing EPS(적자 기업, 음수)"),
    ("revenue",                             "revenue",           "money",   "매출(TTM)"),
    ("net income",                          "net_income",        "money",   "순이익(TTM)"),
    ("ebitda",                              "ebitda",            "money",   "EBITDA(TTM)"),
    ("book value per share",                "bps",               "money",   "주당순자산(BPS)"),
    ("equity (book value)",                 "equity_book_value", "money",   "자본총계"),
    ("total debt",                          "total_debt",        "money",   "총부채"),
    ("dividend per share",                  "dps",               "money",   "주당배당금"),
    ("dividend yield",                      "div_yield",         "percent", "배당수익률"),
    ("payout ratio",                        "payout_ratio",      "percent", "배당성향"),
    ("buyback yield",                       "buyback_yield",     "percent", "자사주 매입 수익률"),
    ("shareholder yield",                   "shareholder_yield", "percent", "주주환원율(배당+자사주)"),
    ("price target",                        "analyst_target",    "money",   "애널리스트 목표주가"),
    ("price target difference",             "analyst_target_diff", "percent", "목표주가 괴리율"),
    ("analyst consensus",                   "analyst_consensus", "text",    "컨센서스 등급"),
    ("analyst count",                       "analyst_count",     "int",     "커버 애널리스트 수"),
    ("revenue growth forecast (3y)",        "growth_rev_3y",     "percent", "3년 매출성장 전망"),
    ("eps growth forecast (3y)",            "growth_eps_3y",     "percent", "3년 EPS 성장 전망"),
    ("altman z-score",                      "altman_z",          "number",  "알트만 Z-스코어"),
    ("piotroski f-score",                   "piotroski_f",       "int",     "피오트로스키 F-스코어"),
    ("earnings date",                       "earnings_date",     "text",    "최근/예정 실적발표일"),
    ("ex-dividend date",                    "ex_dividend_date",  "text",    "배당락일"),
]

_PARSERS = {
    "money": parse_scaled_number,
    "number": parse_scaled_number,
    "percent": parse_scaled_number,   # '%'는 parse_scaled_number 가 제거하고 숫자만 반환
    "int": parse_int,
    "text": parse_text,
}


def map_pairs_to_fields(pairs):
    """
    (라벨, 값) 쌍 → 우리 필드 dict. 순수 함수라 네트워크 없이 단위 테스트가 가능합니다.

    반환: (fields, meta)
      fields : {field_name: value or None}
      meta   : {"missing": {field: 사유}, "paywalled": [...], "labels_found": n}
    """
    by_label = dict(pairs)
    fields = {}
    missing = {}
    paywalled = []

    for label, field, kind, _desc in FIELD_SPECS:
        if label not in by_label:
            # 이미 다른 라벨(예: loss per share ↔ earnings per share)로 채워졌으면 유지
            if field not in fields:
                missing.setdefault(field, "라벨 없음(페이지에 항목 자체가 없음)")
            continue
        state, raw = _value_state(by_label[label])
        if state == "na":
            if fields.get(field) is None:
                fields.setdefault(field, None)
                missing[field] = "소스가 n/a 로 명시(값 미제공)"
            continue
        if state == "paywall":
            fields.setdefault(field, None)
            missing[field] = "유료(Pro) 전용 항목 — 무료 페이지에서 확인 불가"
            paywalled.append(field)
            continue
        value = _PARSERS[kind](raw)
        if value is None:
            missing[field] = f"값 파싱 실패(원문='{raw}')"
            fields.setdefault(field, None)
        else:
            fields[field] = value
            missing.pop(field, None)

    for _label, field, _kind, _desc in FIELD_SPECS:
        fields.setdefault(field, None)

    return fields, {
        "missing": missing,
        "paywalled": sorted(set(paywalled)),
        "labels_found": len(by_label),
    }


# -----------------------------------------------------------------------------
# 장마감 종가 블록 파싱 (§0-3-1 후행지표 전용 — 프리마켓/애프터마켓 절대 사용 금지)
# -----------------------------------------------------------------------------
_CLOSE_ANCHOR_PATTERNS = (
    re.compile(r"^at close:?\s*(.*)$", re.I),
    re.compile(r"^(.+?)\s*[-–]\s*market closed$", re.I),
)
_ET_TIMESTAMP_RE = re.compile(
    r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}),?\s*(\d{1,2}:\d{2}\s*[AP]M)\s*(E[DS]T)", re.I
)


def extract_close_price(html):
    """
    '장마감 종가'와 그 기준 시각을 뽑습니다.

    페이지 상단에는 종가 블록 다음에(장중 애프터마켓 거래가 있었으면) 애프터마켓 블록이
    이어집니다. **가장 먼저 등장하는 종가 마커("At close: ..." 또는 "... - Market closed")**
    만 보고, 그 직전의 순수 숫자 줄을 종가로 취합니다(등락 줄에는 '%'가 있어 자동 배제됨).

    ⚠️ 2026-08-07 수정: 오너가 로컬에서 실측(미국 장마감 후, 애프터마켓 거래 있는 종목 11/12에서
    실패)한 결과 발견 — "At close:"와 그 뒤의 날짜/시각이 **서로 다른 텍스트 노드**(label span과
    value span)로 나뉘어 있어, BeautifulSoup의 get_text("\\n")를 거치면 같은 줄에 안 붙고
    "At close:"만 있는 줄 / "Aug 6, 2026, 4:00 PM EDT"만 있는 줄로 쪼개지는 경우가 있었습니다
    (애프터마켓 거래가 없는 종목은 우연히 한 줄로 붙어있어 기존 로직이 통과했던 것 — THC만 성공한
    이유). 이제 마커가 있는 줄 자체에 타임스탬프가 없으면, 그 뒤 몇 줄 안에서
    ET 타임스탬프 패턴을 별도로 찾습니다(라벨과 값이 분리된 경우 대응). "Market closed"는 여전히
    대체 마커로 유지(애프터마켓 거래가 아예 없었던 종목의 단순 포맷 대응).

    찾지 못하면 값을 지어내지 않고 (None, None, 사유) 를 반환합니다.

    반환: (price, asof_text, error)
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]

    for i, line in enumerate(lines):
        matched = None
        for pat in _CLOSE_ANCHOR_PATTERNS:
            m = pat.match(line)
            if m:
                matched = m.group(1).strip()
                break
        if matched is None:
            continue

        # 마커 줄 자체에 ET 타임스탬프가 있으면 그대로 사용, 없으면(라벨/값이 분리된 경우)
        # 뒤따르는 최대 3줄 안에서 타임스탬프를 찾습니다.
        asof_text = matched if _ET_TIMESTAMP_RE.search(matched) else None
        if asof_text is None:
            for k in range(i + 1, min(len(lines), i + 4)):
                if _ET_TIMESTAMP_RE.search(lines[k]):
                    asof_text = lines[k]
                    break
        if asof_text is None:
            # 타임스탬프를 아예 못 찾으면 이 마커는 버리고 다음 후보를 계속 찾습니다
            # (지어내지 않기 — §0-1).
            continue

        for j in range(i - 1, max(-1, i - 6), -1):
            cand = lines[j]
            if "%" in cand or cand.startswith(("+", "-")):
                continue
            value = parse_scaled_number(cand)
            if value is not None and value > 0 and re.fullmatch(r"[\d,]+(\.\d+)?", cand):
                return value, asof_text, None
        return None, asof_text, "종가 마커는 찾았지만 그 앞에서 종가 숫자를 찾지 못함"
    return None, None, "장마감 종가 블록('At close:' / 'Market closed')을 찾지 못함"


def parse_close_timestamp(asof_text):
    """
    'Aug 5, 2026, 4:00 PM EDT' → tz-aware datetime(ET). 실패하면 None.
    ⚠️ 우리가 계산한 세션 날짜가 아니라 **소스가 알려준 날짜**가 언제나 우선입니다.
    """
    if not asof_text or ET is None:
        return None
    m = _ET_TIMESTAMP_RE.search(asof_text)
    if not m:
        return None
    try:
        naive = datetime.strptime(f"{m.group(1)} {m.group(2).upper().replace(' ', '')}",
                                  "%b %d, %Y %I:%M%p")
        return naive.replace(tzinfo=ET)
    except ValueError:
        return None


_NO_DIVIDEND_RE = re.compile(r"does not appear to pay any dividends", re.I)


def detect_dividend_statement(html_text):
    """
    '무배당 확정'과 '수집 실패'를 구분하기 위한 문장 탐지 (§0-1, 코스피 dps_status 와 같은 취지).
    반환: "confirmed_none" | "unknown"
    """
    return "confirmed_none" if _NO_DIVIDEND_RE.search(html_text or "") else "unknown"


def derive_fields(fields, universe_row=None):
    """
    수집한 원시 필드에서 파생 정보를 만듭니다. **계산은 순수 사칙연산만** 하고,
    미래를 추정하는 값은 만들지 않습니다(§0-1 예시2-보충).
    """
    derived = {}

    # 성장률: 애널리스트 3년 EPS 성장 전망(실측 컨센서스)을 그대로 씁니다.
    derived["growth"] = fields.get("growth_eps_3y")
    derived["growth_source"] = (
        "stockanalysis_eps_growth_forecast_3y" if fields.get("growth_eps_3y") is not None else None
    )

    # Forward 섹션 가용 여부 (§5-5: 없으면 섹션만 마스킹)
    derived["forward_available"] = (
        fields.get("f_per") is not None and derived["growth"] is not None
    )

    # 주주환원율: 사이트가 배당+자사주를 합쳐 제공(Shareholder Yield). 없으면 None.
    derived["sh_return"] = fields.get("shareholder_yield")

    # 교차검증(§0-3-3): 유니버스 CSV 시총 vs 통계 페이지 시총
    if universe_row and fields.get("market_cap") and universe_row.get("csv_market_cap"):
        a = float(fields["market_cap"])
        b = float(universe_row["csv_market_cap"])
        diff = abs(a - b) / max(b, 1.0)
        derived["market_cap_discrepancy"] = round(diff, 4)
        derived["market_cap_cross_validated"] = diff <= US_MARKETCAP_CROSSCHECK_TOLERANCE
    else:
        derived["market_cap_discrepancy"] = None
        derived["market_cap_cross_validated"] = False

    return derived


def collect_one(symbol, universe_row=None, session=None):
    """
    한 종목의 통계 페이지를 수집·파싱합니다. 실패해도 예외를 삼키지 않고 사유를 남깁니다.
    반환: dict(raw / processed / errors / timing)
    """
    url = build_statistics_url(symbol)
    result = {
        "symbol": symbol,
        "url": url,
        "collected_at_et": _now_et().isoformat(),
        "errors": [],
    }

    t0 = time.perf_counter()
    try:
        res = _http_get(url)
        html = res.text
    except USSourceBlockedError:
        raise
    except Exception as e:
        result["errors"].append(f"페이지 요청 실패: {e}")
        result["fetch_seconds"] = round(time.perf_counter() - t0, 3)
        result["ok"] = False
        return result
    fetch_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    pairs = extract_label_value_pairs(html)
    fields, meta = map_pairs_to_fields(pairs)
    price, asof_text, price_error = extract_close_price(html)
    asof_dt = parse_close_timestamp(asof_text)
    dividend_statement = detect_dividend_statement(BeautifulSoup(html, "html.parser").get_text(" "))
    parse_seconds = time.perf_counter() - t1

    # 종가를 못 읽었으면 시총÷주식수로 역산(§0-1 예시2-보충 '계산값' 예외:
    # 입력 둘 다 실측값 + 순수 사칙연산). 반드시 계산값으로 마킹합니다.
    price_source = "close_block"
    price_calculated = False
    if price is None and fields.get("market_cap") and fields.get("outstanding_shares"):
        try:
            price = float(fields["market_cap"]) / float(fields["outstanding_shares"])
            price_source = "calculated_marketcap_div_shares"
            price_calculated = True
            result["errors"].append(f"종가 직접 파싱 실패({price_error}) → 시총÷주식수 계산값 사용")
        except (TypeError, ValueError, ZeroDivisionError):
            price = None
    elif price is None:
        result["errors"].append(f"종가 수집 실패: {price_error}")
        price_source = None

    # 배당: 값이 없을 때 '무배당 확정'과 '수집 실패'를 구분해서 기록 (0으로 채우지 않음)
    if fields.get("dps") is None and fields.get("div_yield") is None:
        dividend_status = "confirmed_none" if dividend_statement == "confirmed_none" else "not_collected"
    else:
        dividend_status = "collected"

    derived = derive_fields(fields, universe_row)

    processed = {
        "symbol": symbol,
        "name": (universe_row or {}).get("name"),
        "rank": (universe_row or {}).get("rank"),
        "price": round(price, 4) if price is not None else None,
        "price_source": price_source,
        "price_calculated": price_calculated,
        "price_asof_text": asof_text,
        "price_asof_et": asof_dt.isoformat() if asof_dt else None,
        "session_date_from_source": asof_dt.date().isoformat() if asof_dt else None,
        "dividend_status": dividend_status,
        **fields,
        **derived,
    }

    result.update({
        "ok": True,
        "fetch_seconds": round(fetch_seconds, 3),
        "parse_seconds": round(parse_seconds, 3),
        "raw_pairs": pairs,                # §0-3-3 raw 원문 보관
        "processed": processed,            # 가공 결과
        "missing": meta["missing"],
        "paywalled": meta["paywalled"],
        "labels_found": meta["labels_found"],
    })
    if session and asof_dt and asof_dt.date().isoformat() != session.get("session_date"):
        result["errors"].append(
            f"세션 날짜 불일치: 계산값 {session.get('session_date')} vs 소스 {asof_dt.date().isoformat()} "
            "(휴장일 가능성 — 소스 값을 신뢰)"
        )
    return result


# =============================================================================
# 3. 샘플 수집 프로토타입 (US_STOCKS_WORK_ORDER.md §6-2)
# =============================================================================
# 550종목 전체 소요시간 추정에 쓰는 핵심 필드 — 이게 비면 종목 카드를 못 그립니다.
CORE_FIELDS = ("t_per", "t_eps", "t_roe", "roic", "market_cap", "outstanding_shares", "bps")
FORWARD_FIELDS = ("f_per", "growth_eps_3y", "analyst_target")


def pick_sample_symbols(selected, count=12):
    """대형/중형/소형이 골고루 섞이도록 순위 구간에서 균등 추출합니다(랜덤 아님, 재현 가능)."""
    if not selected:
        return []
    count = min(count, len(selected))
    step = max(1, len(selected) // count)
    picked = [selected[min(i * step, len(selected) - 1)]["symbol"] for i in range(count)]
    # 마지막 순위(가장 작은 종목)도 반드시 포함
    if selected[-1]["symbol"] not in picked:
        picked[-1] = selected[-1]["symbol"]
    return picked


def run_sample_prototype(symbols, universe_by_symbol=None, out_dir=None, delay=True):
    """
    샘플 종목을 정중하게 순회하며 ① 필드 추출 성공 여부 ② 종목당 소요시간을 실측하고,
    550종목 전체 소요시간을 재추정합니다. raw/가공 결과는 각각 별도 파일로 저장합니다.
    """
    universe_by_symbol = universe_by_symbol or {}
    session = resolve_collection_session_et()
    print(f"[샘플 수집] 대상 {len(symbols)}종목 | 대상 세션(계산값) {session['session_date']} "
          f"| 현재 ET {session['now_et']}")

    results = []
    blocked = None
    for i, sym in enumerate(symbols, start=1):
        try:
            r = collect_one(sym, universe_by_symbol.get(sym), session)
        except USSourceBlockedError as e:
            blocked = str(e)
            print(f"🚨 {e}")
            break
        results.append(r)
        p = r.get("processed", {})
        core_ok = sum(1 for f in CORE_FIELDS if p.get(f) is not None)
        fwd_ok = sum(1 for f in FORWARD_FIELDS if p.get(f) is not None)
        print(f"  [{i:>2}/{len(symbols)}] {sym:<8} "
              f"fetch {r.get('fetch_seconds', 0):>5.2f}s parse {r.get('parse_seconds', 0):>5.2f}s "
              f"| price={p.get('price')} PER={p.get('t_per')} fPER={p.get('f_per')} "
              f"ROE={p.get('t_roe')} | core {core_ok}/{len(CORE_FIELDS)} fwd {fwd_ok}/{len(FORWARD_FIELDS)}"
              + (f" | ⚠️ {r['errors'][0]}" if r.get("errors") else ""))
        if delay and i < len(symbols):
            _polite_sleep()

    ok_results = [r for r in results if r.get("ok")]
    fetch_times = [r["fetch_seconds"] for r in ok_results]
    summary = {
        "sampled": len(results),
        "succeeded": len(ok_results),
        "failed": len(results) - len(ok_results),
        "blocked": blocked,
        "fetch_seconds_mean": round(statistics.mean(fetch_times), 3) if fetch_times else None,
        "fetch_seconds_median": round(statistics.median(fetch_times), 3) if fetch_times else None,
        "fetch_seconds_max": round(max(fetch_times), 3) if fetch_times else None,
        "polite_delay_mean_sec": (US_CRAWL_DELAY_MIN_SEC + US_CRAWL_DELAY_MAX_SEC) / 2.0,
    }
    if fetch_times:
        per_stock = summary["fetch_seconds_mean"] + summary["polite_delay_mean_sec"]
        summary["estimated_seconds_per_stock"] = round(per_stock, 2)
        summary["estimated_total_minutes_550"] = round(per_stock * US_TARGET_UNIVERSE_SIZE / 60.0, 1)

    # 필드 커버리지 (어떤 지표가 몇 %의 종목에서 실제로 나왔는가)
    coverage = {}
    for _label, field, _kind, _desc in FIELD_SPECS:
        got = sum(1 for r in ok_results if r["processed"].get(field) is not None)
        coverage[field] = f"{got}/{len(ok_results)}" if ok_results else "0/0"
    summary["field_coverage"] = coverage

    print("-" * 70)
    print(f"[샘플 결과] 성공 {summary['succeeded']} / 실패 {summary['failed']}")
    if fetch_times:
        print(f"  종목당 요청 시간   : 평균 {summary['fetch_seconds_mean']}s "
              f"(중앙값 {summary['fetch_seconds_median']}s, 최대 {summary['fetch_seconds_max']}s)")
        print(f"  정중한 슬립 포함   : 종목당 약 {summary['estimated_seconds_per_stock']}s")
        print(f"  ▶ 550종목 재추정   : 약 {summary['estimated_total_minutes_550']}분")
    print("  핵심 필드 커버리지 : " + ", ".join(
        f"{f}={coverage[f]}" for f in CORE_FIELDS + FORWARD_FIELDS))
    print("-" * 70)

    # raw / 가공 분리 저장 (§0-3-3)
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", US_SAMPLE_DIRNAME)
    os.makedirs(out_dir, exist_ok=True)
    stamp = _now_et().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(out_dir, f"sample_raw_{stamp}.json")
    proc_path = os.path.join(out_dir, f"sample_processed_{stamp}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary,
                   "items": [{"symbol": r["symbol"], "url": r["url"],
                              "raw_pairs": r.get("raw_pairs", []), "errors": r.get("errors", [])}
                             for r in results]}, f, ensure_ascii=False, indent=2)
    with open(proc_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary,
                   "items": [r.get("processed", {"symbol": r["symbol"]}) for r in results],
                   "missing": {r["symbol"]: r.get("missing", {}) for r in results}},
                  f, ensure_ascii=False, indent=2)
    print(f"  raw  → {raw_path}")
    print(f"  가공 → {proc_path}")
    return results, summary


# =============================================================================
# 3-1. 상단 지수 3종 수집 (오너 확정: S&P500 / 나스닥종합 / 다우존스)
#
# 2026-08-07 교체: 최초 시도했던 Stooq CSV 소스(^spx 등)가 오너 로컬 실행에서 3종 전부
# HTTP 404 — 무료·무인증이라 골랐지만 실제로는 살아있는 엔드포인트가 아니었습니다.
# **ETF 프록시** 방식으로 교체합니다: stockanalysis.com 의 ETF 페이지(/etf/{ticker}/)는
# 개별 종목 통계 페이지와 완전히 동일한 "At close: ..." 종가 블록 구조를 씁니다 — 그래서
# 이미 검증된 extract_close_price() / extract_label_value_pairs() 를 그대로 재사용합니다
# (실측 확인: /etf/spy/, /etf/oneq/ 라이브 응답에서 동일 구조 확인, 2026-08-07).
#
# ⚠️ 절대가(ETF 주가, 예: SPY $768)는 실제 지수 포인트값(S&P500 ≈ 6,598)과 숫자가 다른
#    별개 값이라 화면에 노출하지 않고, "당일 등락률(%)"만 계산해 반환합니다(오너 확정
#    2026-08-07, §0-1 정직 표기). 등락률 = (오늘 종가 − 전일 종가) / 전일 종가 — 두 값
#    모두 페이지에서 그대로 읽은 실측값이므로 사칙연산만 하는 '계산값' 예외(§0-1
#    예시2-보충)에 해당하며, change_calculated=True 로 표시합니다.
# ⚠️ 나스닥종합은 QQQ(나스닥100 추종)로는 정확히 대응되지 않아 ONEQ(Fidelity Nasdaq
#    Composite Index ETF)를 씁니다. 소스가 나중에 바뀌어도 조용히 틀린 지수를 보여주지
#    않도록, 페이지의 "Index Tracked" 라벨이 기대 문구를 포함하는지 매번 재확인합니다
#    (tracked_index_verified).
# =============================================================================
def build_index_proxy_url(proxy_symbol):
    return US_INDEX_PROXY_URL_TEMPLATE.format(symbol=proxy_symbol)


def _scan_line_label(html, label_text):
    """
    2026-08-07 2차 실측 수정: "Index Tracked"는 종가/Previous Close 가 들어있는 <table> 통계
    박스가 아니라, 그 아래 "About {ETF명}" 서술 섹션에 있어 `extract_label_value_pairs()`
    (표 전용)로는 못 찾는다는 걸 오너 로컬 실행 로그로 확인했습니다(등락률은 정상 계산됐지만
    'Index Tracked' 라벨을 계속 못 찾아 검증 경고가 매번 뜸). 표가 아닌 곳의 "라벨 (+ 값)"을
    찾기 위한 별도 스캐너 — 라벨과 값이 같은 줄에 붙어있는 경우("Index Tracked NASDAQ
    Composite Index")와, 서로 다른 줄로 분리된 경우(표 파서가 이미 겪은 것과 같은 패턴) 둘 다
    지원합니다. 못 찾으면 지어내지 않고 None(§0-1).
    """
    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
    pattern = re.compile(r"^" + re.escape(label_text) + r"\s*:?\s*(.*)$", re.I)
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        same_line_value = m.group(1).strip()
        if same_line_value:
            return same_line_value
        if i + 1 < len(lines):
            return lines[i + 1]
    return None


def fetch_one_index_quote(key, label_ko, label_en, proxy_symbol, expected_tracked_phrase):
    """
    ETF 프록시 페이지 1개를 수집해 당일 등락률을 계산합니다. 실패해도 예외를 던지지 않고
    (사유가 담긴 entry dict) 를 반환합니다 — 다른 지수 수집을 막지 않기 위함입니다.
    (USSourceBlockedError 는 §0-3-2 원칙대로 그대로 위로 던져 즉시 중단시킵니다.)
    """
    entry = {
        "key": key, "label_ko": label_ko, "label_en": label_en,
        "proxy_symbol": proxy_symbol.upper(), "is_etf_proxy": True,
        "close": None, "previous_close": None, "session_date": None,
        "intraday_change_pct": None, "change_calculated": False,
        "tracked_index_label": None, "tracked_index_verified": False,
        "error": None, "source": build_index_proxy_url(proxy_symbol),
    }
    try:
        res = _http_get(build_index_proxy_url(proxy_symbol))
        html = res.text
    except USSourceBlockedError:
        raise
    except Exception as e:
        entry["error"] = f"페이지 요청 실패: {e}"
        return entry

    price, asof_text, price_error = extract_close_price(html)
    asof_dt = parse_close_timestamp(asof_text)
    by_label = dict(extract_label_value_pairs(html))

    # "Index Tracked"는 표(Previous Close 등이 있는 통계 박스)가 아니라 "About" 서술 섹션에
    # 있어(2026-08-07 실측 확인), 표 전용 추출이 실패하면 줄 단위 스캐너로 재시도합니다.
    tracked_raw = by_label.get("index tracked") or _scan_line_label(html, "Index Tracked")
    if tracked_raw:
        entry["tracked_index_label"] = tracked_raw
        entry["tracked_index_verified"] = expected_tracked_phrase in tracked_raw.lower()

    if price is None:
        entry["error"] = f"종가 수집 실패: {price_error}"
        return entry
    entry["close"] = price
    entry["session_date"] = asof_dt.date().isoformat() if asof_dt else None

    previous_close = parse_scaled_number(by_label.get("previous close"))
    if previous_close is None or previous_close <= 0:
        entry["error"] = "전일 종가(Previous Close) 값을 찾지 못해 등락률을 계산하지 못함"
        return entry
    entry["previous_close"] = previous_close
    entry["intraday_change_pct"] = round((price - previous_close) / previous_close * 100.0, 2)
    entry["change_calculated"] = True

    if not entry["tracked_index_verified"]:
        note = (
            f"⚠️ 'Index Tracked' 라벨이 기대 문구('{expected_tracked_phrase}')를 포함하지 않음"
            f"(실제: '{entry['tracked_index_label']}') — 소스가 바뀌었을 수 있어 확인 필요"
        )
        entry["error"] = (entry["error"] + " / " + note) if entry["error"] else note

    return entry


def fetch_index_quotes():
    """
    상단 지수 3종(S&P500 / 나스닥종합 / 다우존스)을 ETF 프록시로 수집합니다.
    개별 지수 수집에 실패해도 나머지는 계속 진행하고, 실패한 지수는 값 대신 사유를 남깁니다.
    """
    results = {}
    for key, label_ko, label_en, proxy_symbol, expected_phrase in US_INDEX_DEFINITIONS:
        entry = fetch_one_index_quote(key, label_ko, label_en, proxy_symbol, expected_phrase)
        results[key] = entry
        pct = entry.get("intraday_change_pct")
        pct_str = f"{pct:+.2f}%" if pct is not None else "-"
        print(f"  [지수] {label_ko:<10} 등락률={pct_str} ({entry.get('session_date') or '-'}) "
              f"{'⚠️ ' + entry['error'] if entry.get('error') else ''}")
        _polite_sleep()
    return results


# =============================================================================
# 3-2. 전수 수집 (550종목) — 오너 로컬 실행용 메인 경로
# =============================================================================
def _median(values):
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 4) if vals else None


def update_us_summary_history(snapshot_time_et, visible_stocks, path):
    """상단 요약 지표(중앙값 3종)를 누적 기록합니다. 표본이 없으면 값을 지어내지 않습니다."""
    history = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except Exception as e:
            print(f"⚠️ 요약 이력 로드 실패(새로 시작): {e}")
            history = []

    record = {
        "collected_at_et": snapshot_time_et,
        "f_per": _median([s.get("f_per") for s in visible_stocks]),
        "growth": _median([s.get("growth") for s in visible_stocks]),
        "pegy": _median([
            s.get("f_pegy") for s in visible_stocks
            if s.get("f_pegy") is not None and 0 < s["f_pegy"] < 50.0
        ]),
        "sample_count": len(visible_stocks),
    }
    history.append(record)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"  요약 이력 갱신: {record} -> {path}")


def load_collect_checkpoint(path, session_date):
    """
    2026-08-07 신설: 550종목 전수수집이 중간에 소스 차단(HTTP 429)으로 끊겼을 때, 다음 실행이
    처음부터 다시 하지 않고 이어서 하도록 진행상황을 불러옵니다. **오늘(session_date)과 날짜가
    다른 체크포인트는 절대 재사용하지 않습니다** — 어제 종가와 오늘 종가가 섞이면 §0-1(지어내기
    금지) 위반이 되기 때문입니다. 없거나 날짜가 다르거나 깨졌으면 빈 상태로 시작합니다.
    """
    empty = {"session_date": session_date, "enriched": [], "raw_items": [],
              "failed_tickers": [], "completed_symbols": []}
    if not os.path.exists(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("session_date") != session_date:
            print(f"  ℹ️ 체크포인트가 다른 세션 날짜({data.get('session_date')})라 재사용하지 않고 새로 시작합니다.")
            return empty
        return {
            "session_date": session_date,
            "enriched": data.get("enriched") or [],
            "raw_items": data.get("raw_items") or [],
            "failed_tickers": data.get("failed_tickers") or [],
            "completed_symbols": data.get("completed_symbols") or [],
        }
    except Exception as e:
        print(f"  ⚠️ 체크포인트 로드 실패(새로 시작): {e}")
        return empty


def save_collect_checkpoint(path, session_date, enriched, raw_items, failed_tickers, completed_symbols):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "session_date": session_date,
                "saved_at_et": _now_et().isoformat(),
                "enriched": enriched,
                "raw_items": raw_items,
                "failed_tickers": failed_tickers,
                "completed_symbols": completed_symbols,
            }, f, ensure_ascii=False)
    except Exception as e:
        print(f"  ⚠️ 체크포인트 저장 실패(진행은 계속합니다): {e}")


def clear_collect_checkpoint(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"  ⚠️ 체크포인트 정리 실패(전수 수집 완료엔 지장 없음): {e}")


# -----------------------------------------------------------------------------
# 무인 자동화(GitHub Actions) 전용 사전 점검 — 2026-08-07 신설
#
# 배경: GitHub Actions 의 cron 은 UTC 고정인데 미국 동부(ET)는 서머타임 때문에
#   "정규장 마감 16:00 + 30분 = 16:30 ET" 의 UTC 시각이 1년에 두 번 1시간 이동합니다.
#     · EDT(서머타임, 3~11월, UTC-4): 16:30 ET = 20:30 UTC
#     · EST(표준시,   11~3월, UTC-5): 16:30 ET = 21:30 UTC
#   위 두 값은 추측이 아니라 describe_collection_schedule() 을 2026-07-15(EDT)/
#   2026-01-15(EST) 시각으로 실제 호출해 얻은 `collect_ready_at_utc` 입니다(§0-1).
#   그래서 워크플로우(.github/workflows/scrape_us.yml)는 cron 을 두 줄 걸어 매일 두 번
#   트리거하고, 그중 "지금 돌면 안 되는 쪽"을 이 함수가 걸러냅니다.
#
# ⚠️ 왜 session["is_ready_now"] 만으로는 부족한가 (코드를 실제로 돌려 확인한 사실):
#   resolve_collection_session_et() 은 "마감+30분이 지난 가장 최근 평일"을 찾을 때까지
#   하루씩 거슬러 올라갑니다. 루프 탈출 조건 자체가 `now >= ready_at` 이므로 그 결과의
#   is_ready_now 는 **어떤 시각을 넣어도 항상 True** 입니다(장중 09:35 ET 로 호출해도
#   False 가 되지 않고 그냥 '어제 세션'을 가리킵니다). 즉 그 플래그로는 중복 실행을
#   막을 수 없습니다.
#   따라서 실제 판정 기준은 **"이번에 담게 될 거래일(session_date)을 기존 스냅샷이
#   이미 담고 있는가"** 입니다. 이미 담고 있으면 건너뛰고, 아니면 수집합니다.
#   이 방식은 부수적으로 두 가지를 더 해결합니다.
#     ① 첫 크론이 HTTP 429 로 중간에 끊겨 스냅샷이 갱신되지 않았으면, 두 번째 크론이
#        같은 날 자동으로 재시도합니다(체크포인트에서 이어받으므로 처음부터 하지 않음).
#     ② 오너가 로컬에서 이미 수집해 푸시해둔 날은 액션이 같은 데이터를 다시 크롤링하지
#        않습니다(§0-3-2 정중한 크롤링).
# -----------------------------------------------------------------------------
def snapshot_covered_session_dates(snapshot_path):
    """
    기존 스냅샷이 이미 담고 있는 거래일(세션) 날짜 집합을 읽어옵니다.

    - `metadata.session_dates_from_source`: 페이지의 "At close: …" 타임스탬프에서 읽은
      **실제** 세션 날짜(확정 출처). 이게 있으면 이걸 우선합니다.
    - `metadata.session_hint.session_date`: 수집 당시의 ET 기준 계산값(보조).
    - 파일이 없거나 깨졌거나 status 가 FAILED 면 **빈 집합**을 돌려줍니다 —
      "모르면 건너뛰기"가 아니라 "모르면 수집한다"가 안전한 방향이기 때문입니다
      (건너뛰면 데이터가 하루 통째로 비고, 수집하면 최악이라도 중복 크롤링 1회).
    """
    if not os.path.exists(snapshot_path):
        return set(), None
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            meta = (json.load(f) or {}).get("metadata") or {}
    except Exception as e:
        print(f"  ⚠️ 기존 스냅샷을 읽지 못했습니다({e}) — 이미 수집됐는지 알 수 없어 수집을 진행합니다.")
        return set(), None
    if meta.get("status") == "FAILED":
        # 실패한 수집 결과는 '이미 수집됨'으로 치지 않습니다(다음 크론이 재시도해야 함).
        return set(), meta.get("last_updated_at_et")
    covered = set((meta.get("session_dates_from_source") or {}).keys())
    hint_date = ((meta.get("session_hint") or {}).get("session_date"))
    if hint_date:
        covered.add(hint_date)
    return covered, meta.get("last_updated_at_et")


def evaluate_collection_readiness(snapshot_path=None, now_et=None):
    """
    "지금 이 실행이 실제로 전수 수집을 해야 하는가"를 판정합니다(무인 자동화 전용).

    반환: dict
      should_collect        : 실제로 수집을 진행해야 하는가
      reason                : 사람이 읽을 판정 사유 (건너뛸 때 로그에 그대로 출력)
      target_session_date   : 지금 수집하면 담기게 될 거래일(ET 계산값)
      covered_session_dates : 기존 스냅샷이 이미 담고 있는 거래일 목록
      snapshot_updated_at_et: 기존 스냅샷의 마지막 갱신 시각(없으면 None)
      session               : resolve_collection_session_et() 원본 결과
    """
    session = resolve_collection_session_et(now_et)
    target = session["session_date"]
    path = snapshot_path or _data_path(US_SNAPSHOT_FILENAME)
    covered, updated_at = snapshot_covered_session_dates(path)

    if not session["is_ready_now"]:
        # 현재 resolve_collection_session_et() 구현상 여기에는 도달하지 않습니다(위 주석 참고).
        # 그 함수가 나중에 바뀌더라도 '마감 전 수집'을 막도록 남겨두는 2차 방어선입니다.
        should, reason = False, (
            f"아직 장마감+{US_COLLECT_AFTER_CLOSE_MINUTES}분 전입니다 "
            f"(수집 가능 시각 {session['collect_ready_at_et']} ET)"
        )
    elif target in covered:
        should, reason = False, (
            f"{target} 거래일은 이미 수집되어 스냅샷에 들어있습니다"
            f"{f' (마지막 갱신 {updated_at} ET)' if updated_at else ''}"
        )
    else:
        should, reason = True, (
            f"{target} 거래일 데이터가 아직 스냅샷에 없습니다 — 수집을 진행합니다"
        )

    return {
        "should_collect": should,
        "reason": reason,
        "target_session_date": target,
        "covered_session_dates": sorted(covered),
        "snapshot_updated_at_et": updated_at,
        "session": session,
    }


def run_us_collector(target_size=None, limit=None, delay=True, skip_indices=False):
    """
    미국주식 전수 수집 배치.

    흐름 (collector_kospi200.run_kospi200_collector 와 같은 순서)
      1) 직전 스냅샷에서 '어제 추적 중이던 티커' 로드 (히스테리시스 판정용)
      2) 유니버스 CSV 수집 → 필터 → 히스테리시스 버퍼 적용
      3) 상단 지수 3종 수집
      4) 종목별 통계 페이지 수집(1차 패스) → 파생 밸류에이션 산출 → 가드레일
      5) **2차 패스**: 오늘 수집분 횡단면 population 통계 계산 후 일괄 스코어링
      6) raw / 가공 스냅샷 분리 저장(§0-3-3) + 요약 이력 갱신

    ⚠️ 실패 종목은 조용히 건너뛰지 않고 `metadata.failed_tickers` 에 사유와 함께 남깁니다(§0-1).
    ⚠️ 소스가 우리를 차단하면 즉시 중단하고 **기존 스냅샷을 덮어쓰지 않습니다**(§0-3-2).
    """
    target_size = target_size or US_TARGET_UNIVERSE_SIZE
    started_at = time.perf_counter()
    session = resolve_collection_session_et()
    print("=" * 70)
    print(f"[미국주식 전수 수집 시작] 현재 ET {session['now_et']} ({session['tz_abbrev']})")
    print(f"  대상 세션(계산값): {session['session_date']} | 수집 가능 시각 {session['collect_ready_at_et']}")
    if not session["is_ready_now"]:
        # 장마감+30분 전에는 '오늘 종가'가 아직 없습니다. 중단하지는 않되(백필·테스트 목적
        # 실행이 있을 수 있음) 경고를 크게 남기고, 실제 세션 날짜는 페이지 타임스탬프로 확정합니다.
        print("  ⚠️ 아직 장마감+30분이 지나지 않았습니다 — 수집되는 종가는 직전 거래일 것입니다.")
    print("=" * 70)

    snapshot_path = _data_path(US_SNAPSHOT_FILENAME)
    raw_path = _data_path(US_RAW_SNAPSHOT_FILENAME)
    history_path = _data_path(US_SUMMARY_HISTORY_FILENAME)
    checkpoint_path = _data_path(US_COLLECT_CHECKPOINT_FILENAME)
    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)

    # 1) 히스테리시스 판정용 직전 추적 목록 (덮어쓰기 전에 먼저 읽습니다)
    previous_symbols = load_previously_tracked_symbols(snapshot_path)
    if previous_symbols:
        print(f"[히스테리시스] 직전 추적 티커 {len(previous_symbols)}개 로드")

    # 2) 유니버스
    rows = fetch_universe_rows()
    selected, uni_stats = filter_universe(rows, target_size=target_size)
    print_universe_stats(uni_stats)
    tracked = apply_us_hysteresis_buffer(selected, previous_symbols)
    if not tracked:
        raise RuntimeError("히스테리시스 적용 후 추적 대상이 0개입니다 — 수집을 중단합니다(기존 스냅샷 유지)")
    universe_by_symbol = {r["symbol"]: r for r in tracked}

    if limit:
        tracked = tracked[:limit]
        print(f"⚠️ --limit {limit} 적용: 상위 {len(tracked)}종목만 수집합니다(테스트 모드, 전수 아님)")

    # 2026-08-07: 이전 실행이 소스 차단(HTTP 429)으로 중간에 끊긴 적이 있으면 이어서 진행합니다.
    # (오늘과 다른 날짜의 체크포인트는 절대 재사용하지 않음 — load_collect_checkpoint 참고)
    checkpoint = load_collect_checkpoint(checkpoint_path, session["session_date"])
    enriched = checkpoint["enriched"]
    raw_items = checkpoint["raw_items"]
    failed_tickers = checkpoint["failed_tickers"]
    completed_symbols = set(checkpoint["completed_symbols"])
    if completed_symbols:
        remaining = [r for r in tracked if r["symbol"] not in completed_symbols]
        print(f"[이어하기] 체크포인트에서 {len(completed_symbols)}종목 완료 상태 로드 "
              f"— 남은 {len(remaining)}종목부터 계속합니다.")
        tracked = remaining

    # 3) 상단 지수 (재개 시에도 3건뿐이라 매번 새로 받습니다 — 어차피 오래된 등락률을 재사용하면 안 됨)
    indices = {}
    if not skip_indices:
        print("[지수] 상단 지수 3종 수집")
        indices = fetch_index_quotes()

    # 4) 1차 패스 — 종목별 수집
    blocked_error = None
    total = len(tracked)
    already_done = len(completed_symbols)
    grand_total = already_done + total
    CHECKPOINT_EVERY = 10  # 매 종목마다 저장하면 I/O가 아까워서, 이 개수마다만 저장(+차단 시엔 무조건 저장)
    for i, row in enumerate(tracked, start=1):
        symbol = row["symbol"]
        overall = already_done + i
        try:
            r = collect_one(symbol, universe_by_symbol.get(symbol), session)
        except USSourceBlockedError as e:
            blocked_error = str(e)
            print(f"🚨 {e}")
            break
        except Exception as e:                     # 예외를 삼키지 않고 사유를 남깁니다
            failed_tickers.append({"symbol": symbol, "reason": f"예외 발생: {e}"})
            completed_symbols.add(symbol)
            print(f"  [{overall:>3}/{grand_total}] {symbol:<8} ❌ 예외: {e}")
            if i % CHECKPOINT_EVERY == 0:
                save_collect_checkpoint(checkpoint_path, session["session_date"], enriched, raw_items,
                                         failed_tickers, sorted(completed_symbols))
            if delay and i < total:
                _polite_sleep_with_batch_cooldown(i)
            continue

        raw_items.append({
            "symbol": symbol, "url": r.get("url"),
            "raw_pairs": r.get("raw_pairs", []), "errors": r.get("errors", []),
        })

        if not r.get("ok"):
            failed_tickers.append({"symbol": symbol, "reason": "; ".join(r.get("errors") or ["원인 미상"])})
            completed_symbols.add(symbol)
            print(f"  [{overall:>3}/{grand_total}] {symbol:<8} ❌ 수집 실패: {r.get('errors')}")
            if i % CHECKPOINT_EVERY == 0:
                save_collect_checkpoint(checkpoint_path, session["session_date"], enriched, raw_items,
                                         failed_tickers, sorted(completed_symbols))
            if delay and i < total:
                _polite_sleep_with_batch_cooldown(i)
            continue

        stock = dict(r["processed"])
        stock["rank"] = row.get("rank")
        stock["is_visible"] = row.get("is_visible", True)
        stock["industry"] = row.get("industry")
        stock["instrument_kind"] = row.get("instrument_kind")
        stock["csv_market_cap"] = row.get("csv_market_cap")
        stock["url"] = r.get("url")
        stock["collect_errors"] = r.get("errors") or []
        stock["missing_fields"] = r.get("missing") or {}
        stock["paywalled_fields"] = r.get("paywalled") or []

        # 한글 표기 (정식 한글명 우선 → 없으면 규칙 기반 음역, §8-7-4 오너 확정)
        kr = resolve_korean_name(symbol, stock.get("name"))
        stock["name_kr"] = kr["korean_name"]
        stock["name_kr_source"] = kr["source"]
        stock["name_kr_is_transliterated"] = kr["is_transliterated"]
        stock["name_en_clean"] = kr["english_clean"]

        # 파생 밸류에이션 + 가드레일
        stock.update(derive_valuation(stock))
        stock = apply_us_guardrail(stock)

        enriched.append(stock)
        completed_symbols.add(symbol)
        flag = " ⚠️" if stock.get("collect_errors") else ""
        print(f"  [{overall:>3}/{grand_total}] {symbol:<8} px={stock.get('price')} PER={stock.get('t_per')} "
              f"fPER={stock.get('f_per')} PEGY={stock.get('f_pegy')}{flag}")

        if i % CHECKPOINT_EVERY == 0:
            save_collect_checkpoint(checkpoint_path, session["session_date"], enriched, raw_items,
                                     failed_tickers, sorted(completed_symbols))
        if delay and i < total:
            _polite_sleep_with_batch_cooldown(i)

    if blocked_error:
        # 2026-08-07: 차단돼도 지금까지 모은 건 체크포인트에 남겨서, 다음 실행이 처음부터
        # 다시 하지 않고 이어서 하도록 합니다(§0-3-2 — 차단된 요청을 재시도하는 게 아니라,
        # 다음 '실행'이 이미 성공한 요청을 반복하지 않게 하는 것뿐입니다).
        save_collect_checkpoint(checkpoint_path, session["session_date"], enriched, raw_items,
                                 failed_tickers, sorted(completed_symbols))
        raise USSourceBlockedError(
            f"{blocked_error}\n"
            f"→ {len(enriched)}종목까지 수집한 뒤 중단했습니다. 기존 스냅샷은 덮어쓰지 않았습니다.\n"
            f"→ 진행상황을 저장했습니다({checkpoint_path}) — 잠시 후 같은 명령을 다시 실행하면 "
            f"이어서 진행합니다(처음부터 다시 하지 않음)."
        )
    if not enriched:
        raise RuntimeError("수집 성공 종목이 0개입니다 — 기존 스냅샷을 유지하고 중단합니다")

    # 전수 수집이 끝까지 완주됐으므로 체크포인트는 더 이상 필요 없습니다(다음 실행은 새로 시작).
    clear_collect_checkpoint(checkpoint_path)

    # 5) 2차 패스 — 횡단면 population 통계 후 일괄 스코어링
    print("-" * 70)
    print(f"[2차 패스] 횡단면 population 통계 계산 후 {len(enriched)}종목 일괄 스코어링")
    scoring_meta = score_all(enriched)
    print(f"  population 표본 {scoring_meta['population_sample_size']}종목 / "
          f"통계 {scoring_meta['population_stats']}")

    # 6) 저장
    visible = [s for s in enriched if s.get("is_visible", True)]
    valid = [s for s in visible if s.get("is_valid") and not s.get("is_unverified")]
    valid_ratio = (len(valid) / len(visible)) if visible else 0.0
    if not visible:
        status = "FAILED"
    elif valid_ratio >= US_VALID_RATIO_SUCCESS:
        status = "SUCCESS"
    elif valid_ratio >= US_VALID_RATIO_DEGRADED:
        status = "DEGRADED"
    else:
        status = "FAILED"

    now_et = _now_et()
    elapsed_min = (time.perf_counter() - started_at) / 60.0
    # 실제 세션 날짜의 출처는 언제나 페이지의 "At close:" 타임스탬프입니다(계산값이 아님).
    source_session_dates = {}
    for s in enriched:
        d = s.get("session_date_from_source")
        if d:
            source_session_dates[d] = source_session_dates.get(d, 0) + 1

    metadata = {
        "last_updated_at_et": now_et.strftime("%Y-%m-%d %H:%M"),
        "last_updated_at_kst": _now_kst().strftime("%Y-%m-%d %H:%M"),
        "status": status,
        "elapsed_minutes": round(elapsed_min, 1),
        "total_count": len(visible),
        "valid_count": len(valid),
        "valid_ratio": round(valid_ratio, 3),
        "tracked_count": len(enriched),
        "hidden_buffer_count": len(enriched) - len(visible),
        "failed_tickers": failed_tickers,
        "failed_count": len(failed_tickers),
        "session_hint": session,
        "session_dates_from_source": source_session_dates,
        "universe_filter_stats": uni_stats,
        "scoring": scoring_meta,
        "indices": indices,
        "valid_ratio_thresholds": {
            "success": US_VALID_RATIO_SUCCESS, "degraded": US_VALID_RATIO_DEGRADED,
        },
        "currency": "USD",
        "description": (
            f"미국(나스닥+뉴욕) 시가총액 상위 1~{len(visible)}위 퀀트 스냅샷 "
            f"(검증 통과 {len(valid)}/{len(visible)} 종목, 상태={status}, 통화 USD)"
        ),
    }

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "stocks": enriched}, f, ensure_ascii=False, indent=2)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "collected_at_et": now_et.isoformat(),
                "note": "크롤링 직후 (라벨, 값) 원문. 가공 결과와 분리 보관 (ENGINEERING_SPEC §0-3-3)",
            },
            "items": raw_items,
        }, f, ensure_ascii=False, indent=2)
    update_us_summary_history(now_et.strftime("%Y-%m-%d %H:%M"), visible, history_path)

    print("=" * 70)
    print(f"[완료] {len(visible)}종목 노출 (+버퍼 {metadata['hidden_buffer_count']}) / "
          f"검증 통과 {len(valid)} ({valid_ratio*100:.1f}%) / 상태 {status} / 소요 {elapsed_min:.1f}분")
    if failed_tickers:
        print(f"⚠️ 수집 실패 {len(failed_tickers)}종목: "
              f"{[f['symbol'] for f in failed_tickers][:20]}{' ...' if len(failed_tickers) > 20 else ''}")
    print(f"  가공 → {snapshot_path}")
    print(f"  raw  → {raw_path}")
    print("=" * 70)
    return snapshot_path


# =============================================================================
# 4. CLI
# =============================================================================
def _data_path(filename):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", filename)


def cmd_schedule(_args):
    info = describe_collection_schedule()
    print("=" * 70)
    print("[ET 기준 수집 시점 계산]")
    for k in ("now_et", "now_kst", "tz_abbrev", "session_date", "close_at_et",
              "collect_ready_at_et", "collect_ready_at_kst", "collect_ready_at_utc",
              "is_ready_now", "holiday_calendar_applied", "cron_hint_utc"):
        print(f"  {k:<24}: {info[k]}")
    print(f"  note                    : {info['cron_note']}")
    print("=" * 70)


def cmd_universe(args):
    rows = fetch_universe_rows()
    selected, stats = filter_universe(rows, target_size=args.size)
    print_universe_stats(stats)

    path = _data_path(US_UNIVERSE_FILENAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    previous = load_previously_tracked_symbols(path)
    tracked = apply_us_hysteresis_buffer(selected, previous)

    payload = {
        "metadata": {
            "collected_at_et": _now_et().isoformat(),
            "collected_at_kst": _now_kst().isoformat(),
            "source": US_UNIVERSE_CSV_URL,
            "filter_stats": stats,
            "tracked_count": len(tracked),
            "visible_count": sum(1 for t in tracked if t.get("is_visible")),
        },
        "stocks": tracked,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[유니버스] 저장 완료 → {path}")


def cmd_sample(args):
    universe_by_symbol = {}
    if args.tickers:
        symbols = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        rows = fetch_universe_rows()
        selected, stats = filter_universe(rows, target_size=args.size)
        print_universe_stats(stats)
        universe_by_symbol = {r["symbol"]: r for r in selected}
        symbols = pick_sample_symbols(selected, args.count)
        print(f"[샘플 선정] 순위 균등 추출 {len(symbols)}종목: {', '.join(symbols)}")
    run_sample_prototype(symbols, universe_by_symbol, delay=not args.no_delay)


def cmd_collect(args):
    # 무인 자동화(GitHub Actions)에서만 켜는 사전 점검. 오너가 로컬에서 손으로 돌릴 때는
    # 이 옵션을 주지 않으므로 언제나 그대로 수집합니다(같은 날 재수집도 막지 않음).
    if getattr(args, "skip_if_not_ready", False):
        readiness = evaluate_collection_readiness()
        s = readiness["session"]
        print("=" * 70)
        print("[무인 자동화 사전 점검] --skip-if-not-ready")
        print(f"  현재 ET               : {s['now_et']} ({s['tz_abbrev']})")
        print(f"  이번에 담길 거래일     : {readiness['target_session_date']}")
        print(f"  수집 가능 시각(ET)     : {s['collect_ready_at_et']}")
        print(f"  스냅샷이 가진 거래일   : {readiness['covered_session_dates'] or '(없음)'}")
        print(f"  판정                  : {readiness['reason']}")
        print("=" * 70)
        if not readiness["should_collect"]:
            print("⏭️  이번 실행은 아무것도 하지 않고 정상 종료합니다 (오류 아님).")
            print("   서머타임(EDT/EST) 대응으로 cron 을 두 개 걸어 하루 두 번 트리거되지만,")
            print("   실제 수집은 이 점검 덕분에 하루 한 번만 일어납니다.")
            return
    run_us_collector(
        target_size=args.size,
        limit=args.limit,
        delay=not args.no_delay,
        skip_indices=args.skip_indices,
    )


def cmd_indices(_args):
    """
    상단 지수 3종만 따로 수집해 파싱이 실제로 되는지 확인합니다.
    (⚠️ 이 소스는 아직 실측 검증 전입니다 — constants_us.py §8 주석 참고)
    """
    print("=" * 70)
    print("[지수 소스 점검] S&P500 / 나스닥종합 / 다우존스")
    result = fetch_index_quotes()
    ok = [k for k, v in result.items() if v.get("close") is not None]
    print("-" * 70)
    print(f"  성공 {len(ok)}/{len(result)}")
    for k, v in result.items():
        print(f"  {v['label_ko']:<10} {v['source']}")
        print(f"      close={v['close']} session_date={v['session_date']} error={v['error']}")
    if len(ok) < len(result):
        print("  ⚠️ 실패한 지수는 화면에 '데이터 없음'으로 표시됩니다(값을 지어내지 않음, §0-1).")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="미국주식 수집기 기초틀 (착수 단계)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sched = sub.add_parser("schedule", help="ET 기준 수집 시점/크론 힌트 출력")
    p_sched.set_defaults(func=cmd_schedule)

    p_uni = sub.add_parser("universe", help="유니버스 CSV 수집 + 필터 + 저장")
    p_uni.add_argument("--size", type=int, default=US_TARGET_UNIVERSE_SIZE)
    p_uni.set_defaults(func=cmd_universe)

    p_sample = sub.add_parser("sample", help="샘플 종목 수집 프로토타입(소요시간 실측)")
    p_sample.add_argument("--count", type=int, default=12)
    p_sample.add_argument("--tickers", type=str, default=None, help="쉼표 구분 티커 목록(직접 지정)")
    p_sample.add_argument("--size", type=int, default=US_TARGET_UNIVERSE_SIZE)
    p_sample.add_argument("--no-delay", action="store_true",
                          help="⚠️ 크롤링 매너 위반 — 오프라인 테스트 외에는 쓰지 마세요")
    p_sample.set_defaults(func=cmd_sample)

    p_collect = sub.add_parser(
        "collect", help="550종목 전수 수집 + 스코어링 + 스냅샷 저장 "
                        "(약 40분 소요 — 2026-08-07 HTTP 429 차단 이후 배치 휴지기 추가)")
    p_collect.add_argument("--size", type=int, default=US_TARGET_UNIVERSE_SIZE)
    p_collect.add_argument("--limit", type=int, default=None,
                           help="상위 N종목만 수집(동작 확인용 — 전수 수집이 아님)")
    p_collect.add_argument("--skip-indices", action="store_true",
                           help="상단 지수 3종 수집을 건너뜁니다")
    p_collect.add_argument("--skip-if-not-ready", action="store_true",
                           help="무인 자동화(GitHub Actions) 전용. 아직 수집 시점이 아니거나 "
                                "이번에 담길 거래일이 이미 스냅샷에 있으면 아무것도 하지 않고 "
                                "정상 종료(exit 0)합니다. 서머타임 때문에 cron 2개를 걸어야 하는 "
                                "구조에서 하루 한 번만 실제 수집되도록 하는 방어 장치입니다.")
    p_collect.add_argument("--no-delay", action="store_true",
                           help="⚠️ 크롤링 매너 위반 — 오프라인 테스트 외에는 쓰지 마세요")
    p_collect.set_defaults(func=cmd_collect)

    p_idx = sub.add_parser("indices", help="상단 지수 3종 소스 점검(실측 미검증 소스 확인용)")
    p_idx.set_defaults(func=cmd_indices)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass
    main()
