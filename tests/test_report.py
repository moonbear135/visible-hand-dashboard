# tests/test_report.py
"""
📈 "리포트" 모듈 오프라인 검증 (네트워크 불필요 · Supabase 접속 불필요)

REPORT_WORK_ORDER.md §9-4 / §9-7 에 따라, 이 세션에서는 **실제 Supabase 에 접속할 수 없고
외부 사이트도 부를 수 없다고 가정**하고 전부 합성 데이터·가짜 클라이언트로 검증합니다.

검증 대상
    ① 기간(일/주/월/분기/반기/연) 경계 계산과 이동 — 월말·분기말·윤년·연말 경계 포함
    ② 스냅샷 1행 만들기 — 가격을 모르는 종목을 0원으로 세지 않는지, 통화 분리, 벤치마크 NULL
    ③ 기간 집계·"데이터 부족" 판정 로직 (COMPLETE / IN_PROGRESS / INSUFFICIENT / NO_DATA)
    ④ 벤치마크 기간 수익률 — 날짜가 없으면 가까운 날로 대체하지 않고 "없음"인지
    ⑤ 벤치마크 파일 읽기 (market_history.csv 는 **읽기 전용**, 미국 지수 JSON)
    ⑥ 미국 지수 수집기의 순수 파싱 로직 (devalue 응답 구조 · 병합 시 기존 기록 보존)
    ⑦ 가짜 Supabase 클라이언트로 적재/조회 배선 검증 (upsert 충돌 키, user_id 필터)
    ⑦-1 🧾 종목별 일일 스냅샷(2026-08-13) — **합계 = 종목별 합** 불변식, 저장 순서와 부분 실패,
         테이블이 아직 없는 DB, 화면 표 문구
    ⑧ SQL 스키마 · 워크플로우 · 화면 배선 (기본 숨김, service_role 격리, 기존 파일 무손상)

⚠️ 저장소의 실제 데이터 파일(data/*.json, market_history.csv)은 **읽기만** 합니다.
   이 테스트는 어떤 저장소 파일도 수정하지 않습니다(쓰기는 tempfile 안에서만).

실행: python tests/test_report.py
"""

import contextlib
import io
import importlib
import json
import os
import random
import re
import sys
import tempfile
import types
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent))

import collector_us_indices as cui  # noqa: E402
from utils import report_db as rdb  # noqa: E402
from utils.report_db import (  # noqa: E402
    MARKET_KR,
    MARKET_US,
    PERIOD_DAILY,
    PERIOD_HALF,
    PERIOD_MONTHLY,
    PERIOD_QUARTERLY,
    PERIOD_WEEKLY,
    PERIOD_YEARLY,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_INSUFFICIENT,
    STATUS_NO_DATA,
    ReportError,
    benchmark_period_return,
    build_snapshot_rows,
    compute_period_report,
    fetch_user_snapshots,
    group_holdings_by_user,
    load_kospi_close_history,
    period_bounds,
    period_title,
    shift_period,
    to_date,
    upsert_snapshots,
)

REPO_ROOT = Path(__file__).parent.parent
FAILURES = []


def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


def expect_raises(fn, exc_types, label):
    try:
        fn()
    except exc_types:
        check(True, label)
    except Exception as other:  # noqa: BLE001
        check(False, label, f"(다른 예외: {type(other).__name__}: {other})")
    else:
        check(False, label, "(예외가 발생하지 않음)")


def approx(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


def python_code_only(src):
    """
    주석·독스트링을 걷어낸 파이썬 '실행되는 코드'만 남깁니다.
    (설명 주석에 `st.secrets` 같은 문구가 적혀 있다고 실제로 그 경로가 있는 건 아니므로,
     '코드에 없는지'를 볼 때는 반드시 이걸 통과시킨 문자열로 확인합니다.)
    """
    without_docstrings = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)
    return "\n".join(line for line in without_docstrings.splitlines()
                     if not line.strip().startswith("#"))


def sql_code_only(sql):
    """`--` 주석을 걷어낸 SQL 문만 남깁니다(위와 같은 이유)."""
    return "\n".join(line for line in sql.splitlines()
                     if not line.strip().startswith("--"))


def squeeze(text):
    """연속 공백을 하나로 — SQL 정렬용 공백 때문에 문자열 검사가 깨지지 않게."""
    return re.sub(r"[ \t]+", " ", text)


# =============================================================================
# 합성 데이터
# =============================================================================
def snap(day, value, cost, market=MARKET_KR, holdings_count=2, priced_count=2,
         benchmark_symbol="KOSPI", benchmark_value=3000.0):
    return {
        "snapshot_date": day,
        "market": market,
        "currency": "KRW" if market == MARKET_KR else "USD",
        "total_value": value,
        "total_cost": cost,
        "holdings_count": holdings_count,
        "priced_count": priced_count,
        "unpriced_count": holdings_count - priced_count,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_value": benchmark_value,
    }


def holding(market, ticker, quantity, price, name=None):
    return {
        "market": market, "ticker": ticker, "quantity": quantity,
        "avg_purchase_price": price, "stock_name": name,
        "currency": "KRW" if market == MARKET_KR else "USD",
    }


def price_lookup_factory(prices):
    """(market, ticker) -> 가격. 목록에 없으면 None(= 그날 현재가를 모름)."""
    def lookup(market, ticker):
        return prices.get((market, str(ticker)))
    return lookup


# =============================================================================
# 1. 기간 경계 계산
# =============================================================================
def test_period_bounds():
    print("\n[1] 기간 경계 계산 · 이동")

    check(period_bounds(PERIOD_DAILY, "2026-08-12") == (date(2026, 8, 12), date(2026, 8, 12)),
          "일간 = 그 날 하루")
    # 2026-08-12 는 수요일 → 주간은 08-10(월) ~ 08-16(일)
    check(period_bounds(PERIOD_WEEKLY, "2026-08-12") == (date(2026, 8, 10), date(2026, 8, 16)),
          "주간 = 월요일~일요일(ISO)")
    check(period_bounds(PERIOD_WEEKLY, "2026-08-10") == (date(2026, 8, 10), date(2026, 8, 16)),
          "주간: 월요일을 기준일로 줘도 같은 주")
    check(period_bounds(PERIOD_WEEKLY, "2026-08-16") == (date(2026, 8, 10), date(2026, 8, 16)),
          "주간: 일요일을 기준일로 줘도 같은 주(달 경계 아님)")
    check(period_bounds(PERIOD_MONTHLY, "2026-08-12") == (date(2026, 8, 1), date(2026, 8, 31)),
          "월간 = 1일~말일")
    check(period_bounds(PERIOD_MONTHLY, "2026-02-05") == (date(2026, 2, 1), date(2026, 2, 28)),
          "월간: 평년 2월 말일=28일")
    check(period_bounds(PERIOD_MONTHLY, "2028-02-05") == (date(2028, 2, 1), date(2028, 2, 29)),
          "월간: 윤년 2월 말일=29일(하드코딩 아님)")
    check(period_bounds(PERIOD_MONTHLY, "2026-12-31") == (date(2026, 12, 1), date(2026, 12, 31)),
          "월간: 12월 말일 경계")
    check(period_bounds(PERIOD_QUARTERLY, "2026-08-12") == (date(2026, 7, 1), date(2026, 9, 30)),
          "분기: 8월 → 3분기(7/1~9/30)")
    check(period_bounds(PERIOD_QUARTERLY, "2026-01-01") == (date(2026, 1, 1), date(2026, 3, 31)),
          "분기: 1월 → 1분기")
    check(period_bounds(PERIOD_QUARTERLY, "2026-12-15") == (date(2026, 10, 1), date(2026, 12, 31)),
          "분기: 12월 → 4분기")
    check(period_bounds(PERIOD_HALF, "2026-06-30") == (date(2026, 1, 1), date(2026, 6, 30)),
          "반기: 6/30 은 상반기 마지막날")
    check(period_bounds(PERIOD_HALF, "2026-07-01") == (date(2026, 7, 1), date(2026, 12, 31)),
          "반기: 7/1 부터 하반기")
    check(period_bounds(PERIOD_YEARLY, "2026-08-12") == (date(2026, 1, 1), date(2026, 12, 31)),
          "연간 = 1/1~12/31")

    check(period_title(PERIOD_MONTHLY, "2026-08-12") == "2026년 8월", "월간 제목 표기")
    check(period_title(PERIOD_QUARTERLY, "2026-08-12") == "2026년 3분기", "분기 제목 표기")
    check(period_title(PERIOD_HALF, "2026-08-12") == "2026년 하반기", "반기 제목 표기")
    check(period_title(PERIOD_YEARLY, "2026-08-12") == "2026년", "연간 제목 표기")
    check(period_title(PERIOD_DAILY, "2026-08-12").endswith("(수)"), "일간 제목에 요일 표기")

    check(shift_period(PERIOD_MONTHLY, "2026-01-15", -1) == date(2025, 12, 1),
          "월간 이전 이동: 연도 경계를 넘어감")
    check(shift_period(PERIOD_MONTHLY, "2026-12-15", 1) == date(2027, 1, 1),
          "월간 다음 이동: 연도 경계를 넘어감")
    check(shift_period(PERIOD_MONTHLY, "2026-03-31", -1) == date(2026, 2, 1),
          "월간 이동은 항상 그 달 1일 — 31일 기준일이 2월에서 튀지 않음")
    check(shift_period(PERIOD_QUARTERLY, "2026-08-12", -1) == date(2026, 4, 1),
          "분기 이전 이동")
    check(shift_period(PERIOD_HALF, "2026-08-12", 1) == date(2027, 1, 1), "반기 다음 이동")
    check(shift_period(PERIOD_YEARLY, "2026-08-12", -2) == date(2024, 1, 1), "연간 2년 전 이동")
    check(shift_period(PERIOD_WEEKLY, "2026-08-12", -1) == date(2026, 8, 3), "주간 이전 이동")
    check(shift_period(PERIOD_DAILY, "2026-08-12", 3) == date(2026, 8, 15), "일간 이동")
    check(shift_period(PERIOD_MONTHLY, "2026-08-12", 0) == date(2026, 8, 1),
          "0 이동은 그 기간 시작일")

    check(to_date("2026-08-12T00:00:00+09:00") == date(2026, 8, 12),
          "ISO 타임스탬프에서도 날짜만 안전하게 추출")
    expect_raises(lambda: to_date(""), ValueError, "빈 날짜는 예외(오늘로 대체하지 않음)")
    expect_raises(lambda: to_date("2026/08/12"), ValueError, "형식이 다른 날짜는 예외")
    expect_raises(lambda: period_bounds("HOURLY", "2026-08-12"), ValueError,
                  "모르는 기간 코드는 예외(임의 해석 금지)")


# =============================================================================
# 2. 스냅샷 1행 만들기
# =============================================================================
def test_build_snapshot_rows():
    print("\n[2] 스냅샷 행 생성 (순수 로직)")

    holdings = [
        holding(MARKET_KR, "005930", 10, 70000),
        holding(MARKET_KR, "000660", 2, 1000000),
        holding(MARKET_US, "AAPL", 3, 200.0),
    ]
    prices = {(MARKET_KR, "005930"): 80000.0,
              (MARKET_KR, "000660"): 1200000.0,
              (MARKET_US, "AAPL"): 250.0}
    session_dates = {MARKET_KR: "2026-08-11", MARKET_US: "2026-08-11"}
    benchmarks = {MARKET_KR: ("KOSPI", 6345.53),
                  MARKET_US: ("SP500_PROXY_SPY", 754.6)}

    rows, skipped = build_snapshot_rows("user-1", holdings, price_lookup_factory(prices),
                                        session_dates, benchmarks)
    check(len(rows) == 2 and not skipped, "시장별로 1행씩(KR/US) 생성되고 건너뛴 것 없음")
    kr = next(r for r in rows if r["market"] == MARKET_KR)
    us = next(r for r in rows if r["market"] == MARKET_US)

    check(approx(kr["total_value"], 10 * 80000 + 2 * 1200000), "KR 평가금액 = Σ(수량×현재가)")
    check(approx(kr["total_cost"], 10 * 70000 + 2 * 1000000), "KR 매입원가 = Σ(수량×평균매입가)")
    check(kr["currency"] == "KRW" and us["currency"] == "USD", "통화는 시장에서 파생(혼용 없음)")
    check(approx(us["total_value"], 750.0) and approx(us["total_cost"], 600.0),
          "US 합계는 달러 그대로(환율 변환 없음)")
    check(kr["holdings_count"] == 2 and kr["priced_count"] == 2 and kr["unpriced_count"] == 0,
          "종목 수·담긴 수·빠진 수 기록")
    check(kr["benchmark_symbol"] == "KOSPI" and approx(kr["benchmark_value"], 6345.53),
          "KR 벤치마크(코스피 종가) 저장")
    check(us["benchmark_symbol"] == "SP500_PROXY_SPY",
          "US 벤치마크 심볼에 PROXY 가 드러남(지수 자체가 아님을 이름으로 명시)")
    check(kr["snapshot_date"] == "2026-08-11" and us["snapshot_date"] == "2026-08-11",
          "스냅샷 날짜는 배치 실행 시각이 아니라 가격 스냅샷의 거래일")
    check(kr["user_id"] == "user-1", "user_id 가 행에 포함됨")

    # 가격을 모르는 종목 — 0원으로 세지 않고 빼되, 몇 개를 못 담았는지 남깁니다.
    partial_prices = {(MARKET_KR, "005930"): 80000.0}
    rows2, skipped2 = build_snapshot_rows("user-1", holdings, price_lookup_factory(partial_prices),
                                          session_dates, benchmarks)
    kr2 = next(r for r in rows2 if r["market"] == MARKET_KR)
    check(approx(kr2["total_value"], 800000.0) and approx(kr2["total_cost"], 700000.0),
          "가격을 아는 종목만 합산(모르는 종목을 0원으로 넣지 않음)")
    check(kr2["holdings_count"] == 2 and kr2["priced_count"] == 1 and kr2["unpriced_count"] == 1,
          "빠진 종목 수를 정직하게 기록")
    check(all(r["market"] != MARKET_US for r in rows2), "가격을 하나도 모르는 시장은 행을 만들지 않음")
    check(any(s["market"] == MARKET_US and "현재가를 알 수 없어" in s["reason"] for s in skipped2),
          "행을 안 만든 이유가 사유 목록에 남음(조용히 사라지지 않음)")

    # 거래일을 확인 못 한 시장은 기록하지 않습니다(오늘 날짜로 추측하지 않음).
    rows3, skipped3 = build_snapshot_rows("user-1", holdings, price_lookup_factory(prices),
                                          {MARKET_KR: "2026-08-11"}, benchmarks)
    check(len(rows3) == 1 and rows3[0]["market"] == MARKET_KR,
          "거래일을 모르는 시장(US)은 행을 만들지 않음")
    check(any("거래일" in s["reason"] for s in skipped3), "거래일 미확인 사유가 기록됨")

    # 벤치마크가 없는 날 → NULL (전날 값 복사 금지)
    rows4, _ = build_snapshot_rows("user-1", holdings, price_lookup_factory(prices),
                                   session_dates, {MARKET_KR: ("KOSPI", None)})
    kr4 = next(r for r in rows4 if r["market"] == MARKET_KR)
    check(kr4["benchmark_value"] is None and kr4["benchmark_symbol"] == "KOSPI",
          "벤치마크 값이 없으면 NULL 로 저장(보간·전날 값 복사 없음)")
    us4 = next(r for r in rows4 if r["market"] == MARKET_US)
    check(us4["benchmark_symbol"] is None and us4["benchmark_value"] is None,
          "벤치마크 정보를 안 넘긴 시장은 심볼도 값도 비움")

    check(build_snapshot_rows("user-1", [], price_lookup_factory(prices), session_dates)[0] == [],
          "보유 종목이 없으면 행도 없음")

    grouped = group_holdings_by_user([
        {"user_id": "a", "market": "KR", "ticker": "005930"},
        {"user_id": "b", "market": "US", "ticker": "AAPL"},
        {"user_id": "a", "market": "US", "ticker": "MSFT"},
        {"market": "KR", "ticker": "000660"},  # user_id 없음 → 버림
    ])
    check(set(grouped) == {"a", "b"} and len(grouped["a"]) == 2,
          "사용자별 그룹핑(user_id 없는 행은 버림)")


# =============================================================================
# 3. 기간 집계 · 데이터 부족 판정
# =============================================================================
def test_period_report_status():
    print("\n[3] 기간 집계 · '데이터 부족' 판정")

    # (가) 완전한 월간 — 7월 말 스냅샷(직전 기준점)이 있고 8월이 끝난 뒤
    rows = [
        snap("2026-07-31", 1000.0, 900.0),
        snap("2026-08-03", 1010.0, 900.0),
        snap("2026-08-31", 1100.0, 900.0),
    ]
    report = compute_period_report(rows, PERIOD_MONTHLY, "2026-08-15", today="2026-09-02")
    check(report["status"] == STATUS_COMPLETE, "직전 기준점 + 기간 종료 → COMPLETE")
    check(report["baseline"]["snapshot_date"] == date(2026, 7, 31),
          "기준점은 기간 시작 '이전'의 가장 최근 스냅샷(지난달 마지막 값)")
    check(report["baseline_kind"] == "prior_close", "기준점 종류가 prior_close 로 표시됨")
    check(report["latest"]["snapshot_date"] == date(2026, 8, 31), "종료 시점은 기간 안 마지막 스냅샷")
    check(approx(report["value_change"], 100.0), "평가금액 변화 = 1100 − 1000")
    check(approx(report["value_change_pct"], 10.0), "변화율 = +10.00%")
    check(approx(report["profit_pct_start"], (1000 - 900) / 900 * 100),
          "기간 시작 누적수익률")
    check(approx(report["profit_pct_end"], (1100 - 900) / 900 * 100), "기간 종료 누적수익률")
    check(report["snapshot_count"] == 2, "기간 안 스냅샷 수(기준점은 기간 밖이라 제외)")
    check(report["composition_changed"] is False, "구성 변경 없음")
    check("2026-07-31" in report["status_message"] and "2026-08-31" in report["status_message"],
          "무엇과 무엇을 비교했는지 상태 문구에 그대로 노출")

    # (나) 진행 중 — 기간이 아직 안 끝남
    in_progress = compute_period_report(rows, PERIOD_MONTHLY, "2026-08-15", today="2026-08-20")
    check(in_progress["status"] == STATUS_IN_PROGRESS, "기간이 안 끝났으면 IN_PROGRESS")
    check("진행 중" in in_progress["status_message"], "진행 중임을 문구로 알림")
    check(in_progress["is_window_ended"] is False, "is_window_ended=False")

    # (다) 데이터 부족 — 기간 시작 이전 스냅샷이 없음
    late_start = [snap("2026-08-10", 1000.0, 900.0), snap("2026-08-31", 1100.0, 900.0)]
    insufficient = compute_period_report(late_start, PERIOD_MONTHLY, "2026-08-15",
                                         today="2026-09-02")
    check(insufficient["status"] == STATUS_INSUFFICIENT,
          "기간 시작 전 스냅샷이 없으면 INSUFFICIENT(완성 리포트로 위장하지 않음)")
    check(insufficient["baseline_kind"] == "first_in_window",
          "그래도 계산은 하되 기준점이 '기간 안 첫 스냅샷'임을 표시")
    check(insufficient["missing_days_before_start"] == 9,
          "기간 시작 이후 며칠치가 비었는지 사실 그대로(8/1~8/9 = 9일)")
    check("2026-08-01" in insufficient["status_message"]
          and "2026-08-10" in insufficient["status_message"],
          "부족 안내에 기간 시작일과 실제 시작일이 둘 다 나옴")
    check("%" not in insufficient["status_message"],
          "몇 %가 아니라 사실(날짜·일수) 그대로 안내(작업지시서 §3)")

    # (라) 아예 없음
    none_report = compute_period_report(rows, PERIOD_MONTHLY, "2026-05-15", today="2026-09-02")
    check(none_report["status"] == STATUS_NO_DATA, "기간에 스냅샷이 하나도 없으면 NO_DATA")
    check(none_report["baseline"] is None and none_report["value_change_pct"] is None,
          "NO_DATA 면 숫자를 만들어내지 않음")
    check("역산" in none_report["status_message"], "과거를 역산하지 않는다는 사실을 문구로 명시")

    # (마) 일간 리포트 — 어제 → 오늘
    daily_rows = [snap("2026-08-10", 1000.0, 900.0), snap("2026-08-11", 1020.0, 900.0)]
    daily = compute_period_report(daily_rows, PERIOD_DAILY, "2026-08-11", today="2026-08-12")
    check(daily["status"] == STATUS_COMPLETE, "일간: 전일 스냅샷이 있으면 COMPLETE")
    check(daily["baseline"]["snapshot_date"] == date(2026, 8, 10)
          and approx(daily["value_change_pct"], 2.0),
          "일간 수익률은 전일 종가 스냅샷 대비로 계산됨")
    lonely = compute_period_report([snap("2026-08-11", 1020.0, 900.0)], PERIOD_DAILY,
                                   "2026-08-11", today="2026-08-12")
    check(lonely["status"] == STATUS_INSUFFICIENT,
          "일간: 전일 스냅샷이 없으면 0%가 아니라 데이터 부족")

    # (바) 분기/반기/연간도 같은 규칙
    q_rows = [snap("2026-06-30", 1000.0, 900.0), snap("2026-09-30", 1200.0, 900.0)]
    q_report = compute_period_report(q_rows, PERIOD_QUARTERLY, "2026-08-15", today="2026-10-01")
    check(q_report["status"] == STATUS_COMPLETE and approx(q_report["value_change_pct"], 20.0),
          "분기 리포트도 같은 기준점 규칙으로 계산")
    y_report = compute_period_report(q_rows, PERIOD_YEARLY, "2026-08-15", today="2026-10-01")
    check(y_report["status"] == STATUS_INSUFFICIENT,
          "연간: 작년 말 스냅샷이 없으면 데이터 부족(연간 리포트인 척하지 않음)")


def test_period_report_composition():
    print("\n[4] 구성 변경 · 가격 결측 안내")

    changed = [
        snap("2026-07-31", 1000.0, 900.0, holdings_count=2, priced_count=2),
        snap("2026-08-31", 2000.0, 1800.0, holdings_count=3, priced_count=3),
    ]
    report = compute_period_report(changed, PERIOD_MONTHLY, "2026-08-15", today="2026-09-02")
    check(report["composition_changed"] is True, "종목 수·매입원가가 바뀌면 구성 변경으로 감지")
    check(any("보유 종목 수가" in note for note in report["composition_notes"]),
          "종목 수 변화 안내 문구")
    check(any("매입원가 합계가" in note for note in report["composition_notes"]),
          "매입원가 변화(매매) 안내 문구")
    check(any("매매의 영향이 섞여" in note for note in report["composition_notes"]),
          "매매 영향이 섞였다는 경고를 반드시 붙임(작업지시서 §5)")
    check(all("매매 효과" not in note or "따로 떼어내" in note
              for note in report["composition_notes"]),
          "매매 순효과를 분리 계산했다고 주장하지 않음(v1 범위 밖)")

    # 종목 수는 같은데 매입원가만 바뀐 경우(추가 매수 후 일부 매도 등)도 감지
    cost_only = [snap("2026-07-31", 1000.0, 900.0), snap("2026-08-31", 1100.0, 950.0)]
    check(compute_period_report(cost_only, PERIOD_MONTHLY, "2026-08-15",
                                today="2026-09-02")["composition_changed"] is True,
          "종목 수가 같아도 매입원가가 달라지면 구성 변경으로 감지")

    same = [snap("2026-07-31", 1000.0, 900.0), snap("2026-08-31", 1100.0, 900.0)]
    check(compute_period_report(same, PERIOD_MONTHLY, "2026-08-15",
                                today="2026-09-02")["composition_changed"] is False,
          "시세만 움직였으면 구성 변경 아님(불필요한 경고를 띄우지 않음)")

    coverage = [
        snap("2026-07-31", 1000.0, 900.0, holdings_count=3, priced_count=3),
        snap("2026-08-31", 1100.0, 900.0, holdings_count=3, priced_count=2),
    ]
    cov_report = compute_period_report(coverage, PERIOD_MONTHLY, "2026-08-15", today="2026-09-02")
    check(cov_report["coverage_note"] and "담긴 종목 수가" in cov_report["coverage_note"],
          "두 시점에 담긴 종목 수가 다르면 비교 주의 문구")

    unpriced = [
        snap("2026-07-31", 1000.0, 900.0, holdings_count=3, priced_count=2),
        snap("2026-08-31", 1100.0, 900.0, holdings_count=3, priced_count=2),
    ]
    unp_report = compute_period_report(unpriced, PERIOD_MONTHLY, "2026-08-15", today="2026-09-02")
    check(unp_report["coverage_note"] and "1개 종목" in unp_report["coverage_note"],
          "합계에서 빠진 종목이 있으면 그 사실을 표시")

    broken = [snap("2026-07-31", "?", 900.0), snap("2026-08-31", 1100.0, 900.0)]
    expect_raises(lambda: compute_period_report(broken, PERIOD_MONTHLY, "2026-08-15"),
                  ReportError, "손상된 스냅샷 값은 조용히 0으로 바꾸지 않고 오류로 올림")


# =============================================================================
# 5. 벤치마크
# =============================================================================
def test_benchmark_returns():
    print("\n[5] 벤치마크 기간 수익률")

    closes = {"2026-07-31": 100.0, "2026-08-14": 105.0, "2026-08-31": 110.0}
    ok = benchmark_period_return(closes, "2026-07-31", "2026-08-31")
    check(ok["available"] and approx(ok["change_pct"], 10.0), "양 끝 날짜가 다 있으면 수익률 계산")
    check(approx(ok["start_value"], 100.0) and approx(ok["end_value"], 110.0),
          "비교에 쓴 두 종가를 그대로 돌려줌(화면에서 근거 노출용)")

    missing = benchmark_period_return(closes, "2026-08-01", "2026-08-31")
    check(missing["available"] is False, "시작일 종가가 없으면 비교하지 않음")
    check("2026-08-01" in missing["reason"] and "대체하지 않" in missing["reason"],
          "가까운 날짜로 밀어서 맞추지 않는다는 사실을 사유로 알림(보간 금지)")
    check(missing["change_pct"] is None, "비교 불가면 숫자를 만들어내지 않음")

    both_missing = benchmark_period_return(closes, "2026-01-01", "2026-01-31")
    check(both_missing["available"] is False and "2026-01-01" in both_missing["reason"]
          and "2026-01-31" in both_missing["reason"], "양쪽 다 없으면 둘 다 사유에 표시")

    empty = benchmark_period_return({}, "2026-07-31", "2026-08-31")
    check(empty["available"] is False and "수집되지 않" in empty["reason"],
          "벤치마크 파일 자체가 없으면 '아직 수집 안 됨'으로 안내")

    zero = benchmark_period_return({"2026-07-31": 0.0, "2026-08-31": 110.0},
                                   "2026-07-31", "2026-08-31")
    check(zero["available"] is False, "시작 종가가 0이면 나눗셈하지 않고 비교 불가")


def test_benchmark_files():
    print("\n[6] 벤치마크 파일 읽기 (읽기 전용)")

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "market_history.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("날짜,종합 위험 점수,코스피 종가,원/달러 환율\n")
            f.write("2026-08-10,44.5,6299.66,1417.6\n")
            f.write("2026-08-11,43.3,6345.53,1413.6\n")
            f.write("2026-08-12,,,1410.0\n")            # 코스피 종가 결측 행
            f.write("나쁜날짜,1,2,3\n")                   # 형식 오류 행
        closes = load_kospi_close_history(csv_path)
        check(closes == {"2026-08-10": 6299.66, "2026-08-11": 6345.53},
              "코스피 종가만 날짜별로 읽고, 결측·형식오류 행은 버림(0으로 채우지 않음)")

        empty_path = os.path.join(tmp, "no_such.csv")
        check(load_kospi_close_history(empty_path) == {},
              "파일이 없으면 빈 dict(에러 아님 — 벤치마크만 '없음'이 됨)")

        wrong_path = os.path.join(tmp, "wrong.csv")
        with open(wrong_path, "w", encoding="utf-8") as f:
            f.write("date,close\n2026-08-11,6345.53\n")
        check(load_kospi_close_history(wrong_path) == {},
              "컬럼 이름이 바뀌면 억지 해석하지 않고 빈 dict")

    # 저장소의 실제 market_history.csv — **읽기만** 합니다.
    real = load_kospi_close_history()
    check(len(real) > 5, f"실제 market_history.csv 에서 코스피 종가 이력을 읽음({len(real)}일)")
    check(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", key) for key in real),
          "키가 전부 YYYY-MM-DD 형식")
    check(all(value > 0 for value in real.values()), "종가가 전부 양수")
    before = (REPO_ROOT / "market_history.csv").read_bytes()
    load_kospi_close_history()
    check((REPO_ROOT / "market_history.csv").read_bytes() == before,
          "market_history.csv 는 읽기만 하고 절대 수정하지 않음(매크로 파일 보호)")

    # 미국 지수 이력 JSON (아직 수집 전이면 빈 dict — 그 자체가 정상)
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "metadata": {"is_etf_proxy": True},
            "indices": {
                "SP500_PROXY_SPY": {
                    "label_ko": "S&P 500 (SPY ETF 종가 기준)", "proxy_symbol": "SPY",
                    "is_etf_proxy": True, "closes": {"2026-08-11": 754.6},
                },
                "NASDAQ_PROXY_ONEQ": {
                    "label_ko": "나스닥 종합 (ONEQ ETF 종가 기준)", "proxy_symbol": "ONEQ",
                    "is_etf_proxy": True, "closes": {"2026-08-11": 104.16},
                },
            },
        }
        with open(os.path.join(tmp, "us_index_history.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        us_benchmarks = rdb.benchmark_closes_for_market(MARKET_US, data_dir=tmp)
        check(len(us_benchmarks) == 2, "미국은 벤치마크 2종(S&P500·나스닥)을 돌려줌")
        check(all(b["is_proxy"] for b in us_benchmarks), "둘 다 프록시임이 표시됨")
        check(all("ETF" in b["note"] for b in us_benchmarks),
              "프록시라는 사실이 화면에 붙일 설명 문구에 들어 있음")
        symbol, value = rdb.primary_benchmark_value(MARKET_US, "2026-08-11", data_dir=tmp)
        check(symbol == "SP500_PROXY_SPY" and approx(value, 754.6),
              "스냅샷에 함께 저장할 대표 벤치마크는 S&P500 프록시")
        symbol2, value2 = rdb.primary_benchmark_value(MARKET_US, "2026-08-12", data_dir=tmp)
        check(value2 is None, "그날 종가가 없으면 None(전날 값 복사 금지)")
        check(rdb.benchmark_closes_for_market(MARKET_US, data_dir=os.path.join(tmp, "nope")) == [],
              "미국 지수 파일이 아직 없으면 빈 목록(화면은 '벤치마크 없음'으로 안내)")

    check(set(rdb.US_BENCHMARK_KEYS) == {key for key, *_ in cui.US_INDEX_BENCHMARKS},
          "report_db 와 수집기의 벤치마크 키가 서로 어긋나지 않음")
    check(rdb.US_PRIMARY_BENCHMARK in rdb.US_BENCHMARK_KEYS, "대표 벤치마크가 목록 안에 있음")


# =============================================================================
# 7. 미국 지수 수집기 (순수 파싱 로직)
# =============================================================================
# 아래 두 픽스처는 2026-08-12 stockanalysis.com 과거주가 엔드포인트
# (`/etf/SPY/history/__data.json`, `/etf/ONEQ/history/__data.json`)에서 **실제로 받은 응답의
# 앞부분을 그대로 잘라낸 것**입니다(기존 스크리너 픽스처와 같은 관례). 값은 한 글자도 손대지
# 않았고 뒤쪽 116행·뉴스·화면 메타데이터만 잘라냈습니다 — 그래서 행 인덱스 목록은 실제 그대로
# 125개인데 살아 있는 행은 앞 9개뿐이고, 잘려나간 뒤쪽을 가리키는 인덱스는 None 으로
# 디코딩됩니다(응답이 잘려도 크래시 대신 결측 처리되는지까지 함께 확인).
#
# ⚠️ 왜 실제 원문으로 바꿨는가(2026-08-12 #96):
#    v1 의 합성 페이로드는 행 목록을 노드 **최상위 바로 아래**에 뒀는데, 실제 응답은 한 겹 더
#    안쪽이었습니다 — {"data": {"symbol":"SPY","source":"tiingo","data":[행…]}, "news":…}.
#    그래서 오프라인 테스트는 통과했는데 첫 자동 실행이
#    "응답에서 일별 시세 행을 찾지 못했습니다"로 실패했습니다. 같은 종류의 사고를 막으려면
#    파싱 검증은 **실응답 원문**으로 해야 합니다(§0-1).
def _history_fixture(symbol):
    """실제로 받은 과거주가 응답 원문(앞부분)을 읽어옵니다."""
    return (REPO_ROOT / "tests" / "fixtures"
            / f"us_index_history_{symbol.lower()}_data_json_head.json").read_text(encoding="utf-8")


def test_us_index_collector_parsing():
    print("\n[7] 미국 지수 수집기 파싱 로직 (2026-08-12 실제 응답 원문 · 네트워크 불필요)")

    nodes = cui.decode_sveltekit_data_json(_history_fixture("SPY"))
    check(len(nodes) == 1, "devalue 데이터 노드를 펼침(#92 디코더 재사용, skip 노드는 건너뜀)")

    rows, block = cui.extract_history_block(nodes)
    check(len(rows) == 125,
          "행 목록을 '행의 생김새'로 찾아냄 — 최상위가 아니라 **한 겹 안쪽**에 있어도 찾음(#96 회귀)")
    check(block.get("symbol") == "SPY",
          "행을 담고 있던 블록(심볼·공급자 메타데이터)까지 같이 돌려줌 — 종목 확인용")

    info = cui.extract_source_info(nodes, block)
    check(info["source_symbol"] == "SPY" and info["source_provider"] == "tiingo",
          "응답이 스스로 말하는 티커·공급자를 읽음")
    check(info["proxy_name"] is None,
          "이 엔드포인트에는 ETF 이름이 없음 — 지어내지 않고 None(확인 불가)")

    normalized = cui.normalize_history_rows(rows)
    check(len(normalized) == 9,
          "잘려나간 뒤쪽(None)은 버리고 살아 있는 9행만 정규화 — 응답이 잘려도 죽지 않음")
    check([r["date"] for r in normalized[-3:]] == ["2026-08-07", "2026-08-10", "2026-08-11"],
          "날짜 오름차순 정렬")
    check(approx(normalized[-1]["close"], 770.56), "SPY 최신 종가(2026-08-11 = 770.56)")

    oneq_nodes = cui.decode_sveltekit_data_json(_history_fixture("ONEQ"))
    oneq_rows, oneq_block = cui.extract_history_block(oneq_nodes)
    oneq_norm = cui.normalize_history_rows(oneq_rows)
    check(oneq_block.get("symbol") == "ONEQ" and oneq_block.get("source") == "spg",
          "⚠️ ONEQ 의 공급자는 tiingo 가 아니라 spg — 공급자 이름을 조건으로 걸면 안 됨(#96)")
    check(approx(oneq_norm[-1]["close"], 104.16), "ONEQ 최신 종가(2026-08-11 = 104.16)")
    check(approx(oneq_norm[-3]["close"], 105.184),
          "미조정 종가(c=105.184)를 씀 — 조정가(a=105.1844)가 아님")

    # ⚠️ #96 의 핵심: 같은 응답 안에는 c/h/l/o/v 로 **글자가 겹치는** '지금 시세(quote)'
    #    스키마가 함께 옵니다. 날짜(t)가 없으면 시세 행으로 인정하지 않습니다.
    quote_like = {"c": 1.2, "e": 0, "h": 774.61, "l": 769.2, "o": 774.53,
                  "p": 770.56, "u": 0, "v": 36740555, "cl": 770.56}
    check(cui.looks_like_history_rows([quote_like]) is False,
          "날짜(t) 없는 quote 스키마는 시세 행이 아님(키 글자가 겹쳐도 속지 않음)")
    check(cui.extract_history_rows([{
        "quote": [quote_like],
        "data": {"symbol": "SPY", "source": "tiingo",
                 "data": [{"t": "2026-08-11", "c": 770.56}]},
    }]) == [{"t": "2026-08-11", "c": 770.56}],
          "quote 블록과 이력 블록이 같이 와도 날짜가 있는 쪽을 고름")
    check(cui.extract_history_rows([{
        "decoy": [{"t": "1999-01-01", "c": 1.0}, {"t": "1999-01-02", "c": 2.0},
                  {"t": "1999-01-03", "c": 3.0}],
        "data": {"symbol": "SPY", "source": "tiingo", "updated": "…",
                 "data": [{"t": "2026-08-11", "c": 770.56}]},
    }]) == [{"t": "2026-08-11", "c": 770.56}],
          "메타데이터(심볼·공급자)가 붙은 블록을 더 긴 후보보다 우선(오탐 방어)")

    check(cui.looks_like_history_rows([{"t": "2026-08-11", "c": 1.0}]) is True,
          "행 판정: 날짜(t)+종가(c) 가 있으면 시세 행")
    check(cui.looks_like_history_rows([{"s": "NVDA", "price": 1.0}]) is False,
          "행 판정: 스크리너 행(티커/가격)은 시세 행이 아님")
    check(cui.looks_like_history_rows([{"t": "어제", "c": 1.0}]) is False,
          "행 판정: 날짜 형식이 아니면 거부")
    check(cui.looks_like_history_rows([]) is False and cui.looks_like_history_rows(None) is False,
          "행 판정: 빈 값/None 은 거부")
    check(cui.extract_history_rows([{"x": [{"t": "2026-08-11", "c": 1.0}],
                                     "y": [{"t": "2026-08-11", "c": 1.0},
                                           {"t": "2026-08-10", "c": 2.0}]}]) ==
          [{"t": "2026-08-11", "c": 1.0}, {"t": "2026-08-10", "c": 2.0}],
          "후보가 여럿이면 가장 긴 목록을 고름")

    dirty = cui.normalize_history_rows([
        {"t": "2026-08-11", "c": 104.16},
        {"t": "2026-08-11", "c": 999.0},      # 같은 날짜 중복 → 먼저 나온 값 유지
        {"t": "2026-08-10", "c": None},       # 숫자로 못 읽음 → 버림
        {"t": "bad", "c": 1.0},               # 날짜 형식 아님 → 버림
        {"t": "2026-08-07", "c": -3.0},       # 음수 종가 → 버림
        "행이 아님",
    ])
    check(len(dirty) == 1 and approx(dirty[0]["close"], 104.16),
          "깨진 행은 0이나 추정값으로 메우지 않고 버림(§0-1)")

    merged, added, conflicts = cui.merge_closes(
        {"2026-08-10": 104.79},
        [{"date": "2026-08-10", "close": 104.79}, {"date": "2026-08-11", "close": 104.16}],
    )
    check(added == 1 and merged["2026-08-11"] == 104.16, "새 날짜만 추가됨")
    check(not conflicts, "같은 값이면 충돌 아님")

    merged2, added2, conflicts2 = cui.merge_closes(
        {"2026-08-10": 104.79}, [{"date": "2026-08-10", "close": 200.0}],
    )
    check(added2 == 0 and merged2["2026-08-10"] == 104.79,
          "이미 기록된 날짜의 값은 덮어쓰지 않음(기록 개변 금지)")
    check(conflicts2 == [("2026-08-10", 104.79, 200.0)],
          "대신 충돌 사실을 그대로 돌려줘 파일·로그에 남기게 함")

    check(cui.build_history_url("SPY").endswith("/etf/spy/history/__data.json"),
          "히스토리 엔드포인트 URL 조립(소문자 티커)")
    check([key for key, *_ in cui.US_INDEX_BENCHMARKS] == ["SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ"],
          "벤치마크 키 이름에 프록시 ETF 티커가 그대로 들어감(지수 자체가 아님을 이름으로 명시)")


def test_us_index_collector_run():
    """
    수집기 본체를 **실제 응답 원문**(위 픽스처)으로 직접 호출해 파일 쓰기·병합·차단 경로까지
    확인합니다. 티커에 맞는 응답을 돌려줘, CI 가 실제로 밟는 경로를 그대로 재현합니다(#96).
    """
    print("\n[7-2] 미국 지수 수집기 실행 경로 (실제 응답 원문)")

    class _FakeResponse:
        def __init__(self, text):
            self.text = text

    def _respond(url, timeout=None):
        return _FakeResponse(_history_fixture("SPY" if "/spy/" in url else "ONEQ"))

    original_http_get = cui._http_get
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cui._http_get = _respond
            path = cui.run_us_index_history_collector(data_dir=tmp, delay=False)
            check(path and os.path.exists(path), "수집 결과 파일 생성")

            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            indices = payload["indices"]
            check(set(indices) == {"SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ"},
                  "두 벤치마크가 모두 저장됨")
            oneq = indices["NASDAQ_PROXY_ONEQ"]
            check(oneq["closes"] == {"2026-07-30": 98.8, "2026-07-31": 100.03,
                                     "2026-08-03": 102.07, "2026-08-04": 104.78,
                                     "2026-08-05": 103.88, "2026-08-06": 103.84,
                                     "2026-08-07": 105.184, "2026-08-10": 104.79,
                                     "2026-08-11": 104.16},
                  "날짜→종가 형태로 저장(미조정 종가)")
            check(oneq["last_date"] == "2026-08-11" and oneq["count"] == 9,
                  "최신 날짜·건수 메타데이터")
            spy = indices["SP500_PROXY_SPY"]
            check(approx(spy["closes"].get("2026-08-11"), 770.56) and spy["count"] == 9,
                  "실응답에서 SPY 종가가 실제로 추출됨(#96 회귀 — 예전엔 0행이라 수집 실패)")
            check(spy["proxy_symbol_verified"] is True
                  and oneq["proxy_symbol_verified"] is True,
                  "응답이 말하는 티커로 종목 확인(SPY/ONEQ)")
            check(spy["source_provider"] == "tiingo" and oneq["source_provider"] == "spg",
                  "공급자가 종목마다 다르다는 사실을 그대로 기록(조건으로 쓰지 않음)")
            check(payload["metadata"]["warnings"] == [],
                  "정상 응답에는 경고가 하나도 붙지 않음(거짓 경고 없음)")
            check(payload["metadata"]["is_etf_proxy"] is True
                  and payload["metadata"]["close_kind"] == "unadjusted_close",
                  "프록시·미조정 종가라는 사실이 파일에 명시됨")

            # 2회차 — 같은 날짜에 다른 값이 오면 덮어쓰지 않고 충돌로 기록
            conflicting = json.loads(_history_fixture("ONEQ"))
            conflicting["nodes"][2]["data"][9] = 999.0   # 2026-08-11 종가(104.16) 자리
            conflicting_text = json.dumps(conflicting)
            cui._http_get = lambda url, timeout=None: _FakeResponse(
                _history_fixture("SPY") if "/spy/" in url else conflicting_text)
            cui.run_us_index_history_collector(data_dir=tmp, delay=False)
            payload2 = json.loads(Path(path).read_text(encoding="utf-8"))
            oneq2 = payload2["indices"]["NASDAQ_PROXY_ONEQ"]
            check(oneq2["closes"]["2026-08-11"] == 104.16,
                  "이미 저장된 값은 재수집해도 바뀌지 않음(기록 개변 금지)")
            check(oneq2.get("value_conflicts"), "대신 충돌 사실을 파일에 남김")

            # 차단되면 즉시 중단하고 기존 파일을 망가뜨리지 않음
            def _blocked(url, timeout=None):
                raise cui.USSourceBlockedError("HTTP 429")
            cui._http_get = _blocked
            result = cui.run_us_index_history_collector(data_dir=tmp, delay=False)
            check(result is None, "전부 차단되면 파일을 다시 쓰지 않음(기존 값 보존)")
            payload3 = json.loads(Path(path).read_text(encoding="utf-8"))
            check(payload3["indices"]["NASDAQ_PROXY_ONEQ"]["closes"]["2026-08-11"] == 104.16,
                  "차단 이후에도 기존 데이터가 그대로 남아 있음")

            # 응답 구조가 깨졌을 때 — 값을 지어내지 않고 사유만 남김
            cui._http_get = lambda url, timeout=None: _FakeResponse('{"type":"data","nodes":[]}')
            result2 = cui.run_us_index_history_collector(data_dir=tmp, delay=False)
            check(result2 is None, "노드를 못 찾으면 파일을 쓰지 않음(빈 값으로 덮지 않음)")

            # 노드는 멀쩡한데 '지금 시세(quote)'만 있고 일별 이력이 없을 때 —
            # 키 글자가 겹친다고 오늘 값 하나를 이력으로 둔갑시키지 않습니다(#96).
            quote_only = json.dumps({"type": "data", "nodes": [{"type": "data", "data": [
                {"quote": 1}, {"c": 2, "h": 3, "l": 4, "o": 5, "v": 6},
                1.2, 774.61, 769.2, 774.53, 36740555,
            ]}]})
            cui._http_get = lambda url, timeout=None: _FakeResponse(quote_only)
            result3 = cui.run_us_index_history_collector(data_dir=tmp, delay=False)
            check(result3 is None,
                  "quote 스키마만 있는 응답은 '수집 실패'로 처리(엉뚱한 값을 이력으로 담지 않음)")
            payload4 = json.loads(Path(path).read_text(encoding="utf-8"))
            check(payload4["indices"]["SP500_PROXY_SPY"]["closes"].get("2026-08-11") == 770.56,
                  "그 뒤에도 기존 데이터는 그대로 남아 있음")
        finally:
            cui._http_get = original_http_get

    check(cui._http_get is original_http_get, "테스트가 원래 HTTP 함수를 되돌려 놓음")


# =============================================================================
# 8. 가짜 Supabase 클라이언트로 배선 검증
# =============================================================================
class _FakeQuery:
    def __init__(self, table, store, log):
        self.table_name = table
        self.store = store
        self.log = log
        self.filters = []
        self.op = None
        self.payload = None
        self.on_conflict = None

    def select(self, *_args, **_kwargs):
        self.op = "select"
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def gte(self, key, value):
        self.filters.append(("gte", key, value))
        return self

    def lte(self, key, value):
        self.filters.append(("lte", key, value))
        return self

    def upsert(self, rows, on_conflict=None):
        self.op = "upsert"
        self.payload = rows
        self.on_conflict = on_conflict
        return self

    def insert(self, rows):  # 쓰이면 안 되는 경로 — 호출되면 테스트가 잡습니다.
        self.op = "insert"
        self.payload = rows
        return self

    def delete(self):
        self.op = "delete"
        return self

    def update(self, rows):
        self.op = "update"
        self.payload = rows
        return self

    def execute(self):
        self.log.append({"table": self.table_name, "op": self.op,
                         "filters": list(self.filters), "payload": self.payload,
                         "on_conflict": self.on_conflict})
        if self.op == "upsert":
            self.store.setdefault(self.table_name, []).extend(self.payload)
            return types.SimpleNamespace(data=self.payload)
        rows = list(self.store.get(self.table_name, []))
        for kind, key, value in self.filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif kind == "gte":
                rows = [r for r in rows if str(r.get(key)) >= str(value)]
            elif kind == "lte":
                rows = [r for r in rows if str(r.get(key)) <= str(value)]
        return types.SimpleNamespace(data=rows)


class _FakeClient:
    def __init__(self, store=None):
        self.store = store or {}
        self.log = []

    def table(self, name):
        return _FakeQuery(name, self.store, self.log)


def test_supabase_wiring():
    print("\n[8] Supabase 배선 (가짜 클라이언트)")

    client = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": "10", "avg_purchase_price": "70000", "currency": "KRW"},
        {"id": "2", "user_id": "u2", "market": "US", "ticker": "AAPL",
         "quantity": "3", "avg_purchase_price": "200", "currency": "USD"},
    ]})
    holdings = rdb.fetch_all_holdings(client)
    check(len(holdings) == 2 and isinstance(holdings[0]["quantity"], float),
          "전체 사용자 holdings 조회 + 문자열 숫자를 float 로 정규화")
    check(client.log[-1]["op"] == "select" and client.log[-1]["table"] == "holdings",
          "holdings 는 select 만 함(배치가 사용자 데이터를 고치지 않음)")

    broken = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": "??", "avg_purchase_price": "70000"},
    ]})
    expect_raises(lambda: rdb.fetch_all_holdings(broken), ReportError,
                  "손상된 보유 데이터는 조용히 건너뛰지 않고 오류로 올림")

    rows = [
        {"user_id": "u1", "market": "KR", "snapshot_date": "2026-08-11",
         "total_value": 100.0, "total_cost": 90.0, "currency": "KRW",
         "holdings_count": 1, "priced_count": 1, "unpriced_count": 0,
         "benchmark_symbol": "KOSPI", "benchmark_value": 6345.53},
    ]
    saved = upsert_snapshots(client, rows)
    call = client.log[-1]
    check(saved == 1 and call["op"] == "upsert" and call["table"] == "portfolio_daily_snapshots",
          "스냅샷은 upsert 로 저장(insert 아님 — 두 번 돌려도 행이 늘지 않음)")
    check(call["on_conflict"] == "user_id,market,snapshot_date",
          "충돌 키가 스키마의 유니크 제약과 일치")
    check(upsert_snapshots(client, []) == 0, "저장할 행이 없으면 호출도 하지 않음")

    chunky = _FakeClient()
    many = [dict(rows[0], user_id=f"u{i}") for i in range(5)]
    upsert_snapshots(chunky, many, chunk_size=2)
    check(len([c for c in chunky.log if c["op"] == "upsert"]) == 3,
          "많은 행은 나눠서 저장(chunk)")

    reader = _FakeClient({"portfolio_daily_snapshots": [
        dict(rows[0], snapshot_date="2026-08-10", total_value=95.0),
        dict(rows[0], snapshot_date="2026-08-11"),
        dict(rows[0], snapshot_date="2026-09-01", total_value=120.0),
        dict(rows[0], user_id="other", snapshot_date="2026-08-11", total_value=999.0),
    ]})
    fetched = fetch_user_snapshots(reader, "u1", market="KR", end_date="2026-08-31")
    check([r["snapshot_date"] for r in fetched] == [date(2026, 8, 10), date(2026, 8, 11)],
          "화면 조회: 날짜 상한 필터 + 날짜 오름차순 정렬")
    filters = reader.log[-1]["filters"]
    check(("eq", "user_id", "u1") in filters,
          "RLS 가 있어도 앱에서 user_id 필터를 한 번 더 검(이중 방어)")
    check(("eq", "market", "KR") in filters and any(f[0] == "lte" for f in filters),
          "시장·날짜 필터가 질의에 반영됨")
    check(all(r["total_value"] != 999.0 for r in fetched), "다른 사용자 행은 섞이지 않음")
    expect_raises(lambda: fetch_user_snapshots(reader, None), ReportError,
                  "로그인 정보가 없으면 조용히 빈 값이 아니라 오류")
    expect_raises(lambda: fetch_user_snapshots(None, "u1"), ReportError,
                  "클라이언트가 없으면 오류(빈 리포트로 위장하지 않음)")

    saved_env = {name: os.environ.pop(name, None)
                 for name in (rdb.SERVICE_URL_ENV, rdb.SERVICE_ROLE_KEY_ENV)}
    try:
        check(rdb.service_config_present() is False, "배치 설정이 없으면 False")
        expect_raises(rdb.create_service_client, ReportError,
                      "service_role 설정이 없으면 배치는 조용히 넘어가지 않고 실패")
    finally:
        for name, value in saved_env.items():
            if value is not None:
                os.environ[name] = value


def test_batch_end_to_end():
    print("\n[9] 배치 end-to-end (실제 저장소 데이터로, 쓰기 없음)")

    dates, notes = rdb.resolve_session_dates()
    check(MARKET_KR in dates and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dates[MARKET_KR]),
          f"실제 코스피 스냅샷에서 거래일을 읽음({dates.get(MARKET_KR)})")
    check(MARKET_US in dates and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dates[MARKET_US]),
          f"실제 미국 스냅샷에서 거래일을 읽음({dates.get(MARKET_US)})")
    check(all(isinstance(note, str) for note in notes) and len(notes) >= 2,
          "거래일 판정 근거를 로그 문구로 남김")

    with tempfile.TemporaryDirectory() as tmp:
        empty_dates, empty_notes = rdb.resolve_session_dates(data_dir=tmp)
        check(empty_dates == {}, "가격 스냅샷이 없으면 거래일을 지어내지 않음(빈 dict)")
        check(any("확인 실패" in note for note in empty_notes), "그 사유를 문구로 남김")

    lookup = rdb.build_price_lookup()
    check(callable(lookup), "가격 조회 함수 생성")
    samsung = lookup(MARKET_KR, "005930")
    check(samsung is not None and samsung > 0,
          f"실제 스냅샷에서 삼성전자 현재가 조회({samsung})")
    check(lookup(MARKET_KR, "999999") is None, "없는 종목은 None(0으로 채우지 않음)")

    client = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": 10, "avg_purchase_price": 70000, "currency": "KRW"},
        {"id": "2", "user_id": "u1", "market": "KR", "ticker": "999999",
         "quantity": 1, "avg_purchase_price": 1000, "currency": "KRW"},
    ]})
    summary = rdb.run_daily_snapshot_batch(service_client=client, dry_run=True)
    check(summary["dry_run"] is True and summary["saved"] == 0,
          "dry-run 은 계산만 하고 저장하지 않음")
    check(len(summary["rows"]) == 1 and summary["rows"][0]["market"] == MARKET_KR,
          "보유가 있는 시장만 행을 만듦")
    row = summary["rows"][0]
    check(row["holdings_count"] == 2 and row["priced_count"] == 1 and row["unpriced_count"] == 1,
          "가격을 모르는 종목은 합계에서 빼고 개수로 남김")
    check(row["snapshot_date"] == dates[MARKET_KR], "행의 날짜 = 가격 스냅샷의 거래일")
    check(row["benchmark_symbol"] == "KOSPI", "KR 행의 벤치마크 심볼")
    check(all(c["op"] != "upsert" for c in client.log), "dry-run 에서는 저장 호출 자체가 없음")
    check(all(c["table"] != "holdings" or c["op"] == "select" for c in client.log),
          "배치가 holdings 에 쓰기(insert/update/delete)를 하지 않음")


# =============================================================================
# 9-1. 🕐 가격 수집 시각(KST) 저장·표시 배선 (2026-08-13, TASK_HISTORY #112)
# =============================================================================
#  오너 요청: "이 리포트가 만들어지는 날짜와 시간까지는 표시해야 될 것 같아 … 한국 시간
#  기준으로 시간과 분 정도는 표기를 해야 할 것 같아".
#  여기서 지켜야 할 것 — **없는 시각을 만들어내지 않기**(§0-1):
#    · 메타데이터에 시:분이 없으면 NULL 이고, 00:00 이나 오늘 시각으로 메우지 않습니다.
#    · 미국은 수집기가 이미 변환해 둔 KST 값만 씁니다(ET 를 KST 로 둔갑시키지 않음).
# =============================================================================
class _NoStampColumnClient(_FakeClient):
    """`price_as_of_kst` 컬럼이 아직 없는 DB(= 오너가 ALTER 실행 전) 흉내."""

    def table(self, name):
        query = _FakeQuery(name, self.store, self.log)
        original_execute = query.execute

        def execute():
            if query.op == "upsert" and any(rdb.PRICE_STAMP_FIELD in row
                                            for row in (query.payload or [])):
                self.log.append({"table": name, "op": "rejected",
                                 "filters": [], "payload": query.payload,
                                 "on_conflict": query.on_conflict})
                raise RuntimeError(
                    "PGRST204: Could not find the 'price_as_of_kst' column of "
                    "'portfolio_daily_snapshots' in the schema cache"
                )
            return original_execute()

        query.execute = execute
        return query


class _BoomClient(_FakeClient):
    """시각 컬럼과 무관한 다른 오류 — 조용히 삼키면 안 되는 경우."""

    def table(self, name):
        query = _FakeQuery(name, self.store, self.log)

        def execute():
            raise RuntimeError("네트워크가 끊겼습니다")

        query.execute = execute
        return query


class _StreamlitRecorder:
    """화면 함수가 실제로 무슨 문구를 그리는지 받아 적는 가짜 st."""

    def __init__(self):
        self.markdown_calls = []
        self.caption_calls = []

    def markdown(self, text, *_args, **_kwargs):
        self.markdown_calls.append(str(text))

    def caption(self, text, *_args, **_kwargs):
        self.caption_calls.append(str(text))

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None
        return _noop


class _HoldingViewRecorder(_StreamlitRecorder):
    """종목별 상세 섹션 검증용 — info/warning/error/selectbox/expander 까지 받아 적습니다."""

    def __init__(self):
        super().__init__()
        self.warning_calls = []
        self.info_calls = []
        self.error_calls = []
        self.selectbox_calls = []

    def reset(self):
        for calls in (self.markdown_calls, self.caption_calls, self.warning_calls,
                      self.info_calls, self.error_calls, self.selectbox_calls):
            calls.clear()

    def warning(self, text, *_args, **_kwargs):
        self.warning_calls.append(str(text))

    def info(self, text, *_args, **_kwargs):
        self.info_calls.append(str(text))

    def error(self, text, *_args, **_kwargs):
        self.error_calls.append(str(text))

    def selectbox(self, _label, options, *_args, **_kwargs):
        options = list(options)
        self.selectbox_calls.append(options)
        return options[0] if options else None

    def expander(self, *_args, **_kwargs):
        return contextlib.nullcontext()

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]


def test_price_stamp_wiring():
    print("\n[9-1] 가격 수집 시각(KST) 저장·표시 배선")

    # ---- ① 문자열 정규화: 자르기만 하고 없는 값을 만들지 않음 ----------------
    check(rdb.normalize_price_stamp("2026-08-12 17:50") == "2026-08-12 17:50",
          "수집기 형식('YYYY-MM-DD HH:MM')을 그대로 보존")
    check(rdb.normalize_price_stamp("2026-08-13T07:14:33+09:00") == "2026-08-13 07:14",
          "ISO 타임스탬프도 분까지만(초는 표기 통일 위해 버림)")
    check(rdb.normalize_price_stamp("2026-08-12") is None,
          "날짜만 있으면 None — 00:00 을 붙이지 않음(자정 수집이라는 거짓말 방지)")
    check(rdb.normalize_price_stamp("") is None and rdb.normalize_price_stamp(None) is None,
          "빈 값은 None")
    check(rdb.normalize_price_stamp("어제 오후") is None, "형식을 모르는 값은 None(추정 없음)")

    # ---- ② 실제 저장소 메타데이터에서 시각을 뽑아오는지 ----------------------
    dates, stamps, notes = rdb.resolve_session_info()
    kr_meta = json.loads((REPO_ROOT / "data" / "kospi200_pegy_latest.json")
                         .read_text(encoding="utf-8"))["metadata"]
    us_meta = json.loads((REPO_ROOT / "data" / "us_stocks_latest.json")
                         .read_text(encoding="utf-8"))["metadata"]
    check(stamps.get(MARKET_KR) == rdb.normalize_price_stamp(kr_meta.get("last_updated_at")),
          f"KR 수집 시각 = 코스피 스냅샷 last_updated_at ({stamps.get(MARKET_KR)})")
    check(stamps.get(MARKET_US) == rdb.normalize_price_stamp(us_meta.get("last_updated_at_kst")),
          f"US 수집 시각 = 미국 스냅샷 last_updated_at_kst ({stamps.get(MARKET_US)})")
    check(stamps.get(MARKET_US) != rdb.normalize_price_stamp(us_meta.get("last_updated_at_et")),
          "US 는 ET 값이 아니라 수집기가 변환해 둔 KST 값을 씀")
    check(any("가격 수집 시각" in note for note in notes), "시각 판정 근거도 로그 문구로 남김")
    check(rdb.resolve_session_dates() == (dates, notes),
          "기존 2-튜플 시그니처(resolve_session_dates)가 그대로 동작(호출부 무손상)")

    # ---- ③ 시각이 없을 때 — 거래일은 살리고 시각만 비움 ----------------------
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "kospi200_pegy_latest.json").write_text(
            json.dumps({"metadata": {"last_updated_at": "2026-08-12"}, "stocks": []}),
            encoding="utf-8")
        (Path(tmp) / "us_stocks_latest.json").write_text(
            json.dumps({"metadata": {"last_updated_at_et": "2026-08-12 18:14",
                                     "session_hint": {"session_date": "2026-08-12"}},
                        "stocks": []}),
            encoding="utf-8")
        d, s, n = rdb.resolve_session_info(data_dir=tmp)
        check(d.get(MARKET_KR) == "2026-08-12" and MARKET_KR not in s,
              "KR: 날짜만 있는 메타데이터 → 거래일은 저장하고 시각은 비움")
        check(d.get(MARKET_US) == "2026-08-12" and MARKET_US not in s,
              "US: KST 값이 없으면 ET(18:14)를 KST 로 둔갑시키지 않고 비움")
        check(any("ET 값을 KST 로 둔갑" in note for note in n),
              "그 이유를 로그 문구로 남김")

    # ---- ④ 스냅샷 행에 실리는지 ---------------------------------------------
    holdings = [holding(MARKET_KR, "005930", 10, 70000), holding(MARKET_US, "AAPL", 3, 200.0)]
    prices = {(MARKET_KR, "005930"): 80000.0, (MARKET_US, "AAPL"): 250.0}
    session_dates = {MARKET_KR: "2026-08-12", MARKET_US: "2026-08-12"}
    rows, _ = build_snapshot_rows(
        "user-1", holdings, price_lookup_factory(prices), session_dates, None,
        price_stamp_by_market={MARKET_KR: "2026-08-12 17:50",
                               MARKET_US: "2026-08-13T07:14:33+09:00"},
    )
    kr = next(r for r in rows if r["market"] == MARKET_KR)
    us = next(r for r in rows if r["market"] == MARKET_US)
    check(kr[rdb.PRICE_STAMP_FIELD] == "2026-08-12 17:50", "KR 행에 수집 시각 저장")
    check(us[rdb.PRICE_STAMP_FIELD] == "2026-08-13 07:14",
          "US 행에는 한국시간 값이 저장(거래일 다음 날 새벽이 정상)")
    check(us[rdb.PRICE_STAMP_FIELD][:10] != us["snapshot_date"],
          "미국은 수집 시각의 날짜가 거래일과 다를 수 있음(둘을 같은 값으로 맞추지 않음)")

    rows_no_stamp, _ = build_snapshot_rows("user-1", holdings, price_lookup_factory(prices),
                                           session_dates)
    check(all(r[rdb.PRICE_STAMP_FIELD] is None for r in rows_no_stamp),
          "시각을 안 넘기면 NULL(오늘 시각·장 마감 시각으로 메우지 않음)")
    rows_bad, _ = build_snapshot_rows("user-1", holdings, price_lookup_factory(prices),
                                      session_dates, None,
                                      price_stamp_by_market={MARKET_KR: "2026-08-12"})
    check(next(r for r in rows_bad if r["market"] == MARKET_KR)[rdb.PRICE_STAMP_FIELD] is None,
          "시:분이 없는 값은 저장하지 않고 NULL")

    # 배치 전체(dry-run)에서도 실제 데이터로 실려 나가는지
    client = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": 10, "avg_purchase_price": 70000, "currency": "KRW"},
    ]})
    summary = rdb.run_daily_snapshot_batch(service_client=client, dry_run=True)
    check(summary["price_stamps"].get(MARKET_KR) == stamps.get(MARKET_KR),
          "배치 요약에 시장별 수집 시각이 담김")
    check(summary["rows"][0][rdb.PRICE_STAMP_FIELD] == stamps.get(MARKET_KR),
          "배치가 만든 실제 행에 수집 시각이 실림")

    # ---- ⑤ 저장 배선 + 컬럼이 아직 없는 DB 대비 -----------------------------
    row = {"user_id": "u1", "market": "KR", "snapshot_date": "2026-08-12",
           "total_value": 100.0, "total_cost": 90.0, "currency": "KRW",
           "holdings_count": 1, "priced_count": 1, "unpriced_count": 0,
           "benchmark_symbol": "KOSPI", "benchmark_value": 6345.53,
           rdb.PRICE_STAMP_FIELD: "2026-08-12 17:50"}

    normal = _FakeClient()
    upsert_snapshots(normal, [dict(row)])
    check(normal.log[-1]["payload"][0][rdb.PRICE_STAMP_FIELD] == "2026-08-12 17:50",
          "정상 DB 로는 수집 시각이 그대로 전송됨")

    legacy = _NoStampColumnClient()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        saved = upsert_snapshots(legacy, [dict(row)])
    log_text = buffer.getvalue()
    upserts = [c for c in legacy.log if c["op"] == "upsert"]
    check(saved == 1 and len(upserts) == 1,
          "컬럼이 없는 DB 에서도 그날 스냅샷은 저장됨(수치를 통째로 잃지 않음)")
    check(rdb.PRICE_STAMP_FIELD not in upserts[0]["payload"][0],
          "재시도 요청에서는 시각 필드만 빠짐")
    check(upserts[0]["payload"][0]["total_value"] == 100.0
          and upserts[0]["on_conflict"] == "user_id,market,snapshot_date",
          "나머지 값과 충돌 키는 그대로")
    check(rdb.PRICE_STAMP_ALTER_SQL in log_text and "오너 할 일" in log_text,
          "오너가 실행할 ALTER 문을 로그에 그대로 안내(조용히 넘어가지 않음)")

    expect_raises(lambda: upsert_snapshots(_BoomClient(), [dict(row)]), ReportError,
                  "시각 컬럼과 무관한 오류는 그대로 올림(폴백으로 삼키지 않음)")

    # ---- ⑥ 화면 조회 시 값이 살아 오는지 / 옛 행은 None ----------------------
    reader = _FakeClient({"portfolio_daily_snapshots": [
        dict(row, snapshot_date="2026-08-11", **{rdb.PRICE_STAMP_FIELD: None}),   # 옛 행
        dict(row, snapshot_date="2026-08-12"),
        dict(row, snapshot_date="2026-08-13", **{rdb.PRICE_STAMP_FIELD: "  "}),   # 공백만
    ]})
    fetched = fetch_user_snapshots(reader, "u1")
    check(fetched[0][rdb.PRICE_STAMP_FIELD] is None,
          "이 기능 이전에 저장된 행은 None(빈칸이 아니라 '없음'으로 다뤄짐)")
    check(fetched[1][rdb.PRICE_STAMP_FIELD] == "2026-08-12 17:50", "저장된 시각이 그대로 조회됨")
    check(fetched[2][rdb.PRICE_STAMP_FIELD] is None, "공백 문자열도 None 으로 정규화")

    # ---- ⑦ 화면 문구 ---------------------------------------------------------
    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.report_view")
        real_st = module.st
        recorder = _StreamlitRecorder()
        module.st = recorder
        try:
            module._render_price_stamp(MARKET_KR, {"snapshot_date": date(2026, 8, 12),
                                                   rdb.PRICE_STAMP_FIELD: "2026-08-12 17:50"})
            kr_line = recorder.markdown_calls[-1]
            check("2026-08-12 17:50" in kr_line and "한국시간" in kr_line,
                  "한국 블록: 저장된 시각을 한국시간으로 표기")
            check("**" in kr_line, "회색 캡션이 아니라 굵은 본문 한 줄로 노출(오너: '확 들어오질 않아')")

            recorder.markdown_calls.clear()
            recorder.caption_calls.clear()
            module._render_price_stamp(MARKET_US, {"snapshot_date": date(2026, 8, 12),
                                                   rdb.PRICE_STAMP_FIELD: "2026-08-13 07:14"})
            check("2026-08-13 07:14" in recorder.markdown_calls[-1],
                  "미국 블록: 한국 블록과 **따로** 그 시장의 시각을 표기")
            check(any("미국장" in text for text in recorder.caption_calls),
                  "미국은 거래일 다음 날 새벽에 찍히는 이유를 함께 안내(오너 혼동 방지)")

            recorder.markdown_calls.clear()
            module._render_price_stamp(MARKET_KR, {"snapshot_date": date(2026, 8, 1),
                                                   rdb.PRICE_STAMP_FIELD: None})
            missing_line = recorder.markdown_calls[-1]
            check("시각 정보 없음" in missing_line and "2026-08-01" in missing_line,
                  "값이 없는 과거 행은 '시각 정보 없음'으로 정직하게 표시")
            check(re.search(r"\d{1,2}:\d{2}", missing_line) is None,
                  "없는 값을 오늘 시각·자정(00:00) 같은 값으로 대신 채우지 않음(문구에 시:분이 아예 없음)")
        finally:
            module.st = real_st
    except Exception as exc:  # noqa: BLE001
        check(False, "views.report_view 시각 표시 문구 검증", f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.report_view", None)
            sys.modules.pop("views.scorecard_view", None)


# =============================================================================
# 9-2. 🧾 종목별 일일 스냅샷 (2026-08-13, TASK_HISTORY #113)
# =============================================================================
#  오너 결정: "3번으로 해보자(=종목별 일일 스냅샷까지 저장) … 내가 제일 중시하는 데이터의
#  품질관리를 하려면 아무튼 최대한 깨끗하게 잘 정리된 상태의 많은 데이터가 필요해 … 들쑥날쑥
#  하면 세상의 모두가 힘들어져".
#
#  ⇒ 이 블록의 **가장 중요한 검사는 "합계 = 종목별 합"** 입니다(⑵·⑶). 나머지는 그 불변식이
#     저장·조회·화면까지 살아서 도착하는지를 봅니다.
# =============================================================================
class _NoHoldingTableClient(_FakeClient):
    """`portfolio_holding_snapshots` 테이블이 아직 없는 DB(= 오너가 §8 SQL 실행 전) 흉내."""

    def table(self, name):
        query = _FakeQuery(name, self.store, self.log)
        original_execute = query.execute

        def execute():
            if name == rdb.HOLDING_SNAPSHOTS_TABLE:
                self.log.append({"table": name, "op": "rejected", "filters": [],
                                 "payload": query.payload, "on_conflict": query.on_conflict})
                raise RuntimeError(
                    "PGRST205: Could not find the table "
                    "'public.portfolio_holding_snapshots' in the schema cache"
                )
            return original_execute()

        query.execute = execute
        return query


def _assert_totals_match_details(rows, holding_rows, label):
    """
    🔴 이 헬퍼가 이번 작업의 핵심 요구사항입니다 — 합계 행의 모든 수치가 **그날 종목별 행들의
    합과 정확히 같은지**. float 비교로 얼버무리지 않고, DB(numeric)가 계산할 값과 같은
    **Decimal 정확 합**으로도 확인합니다.
    """
    ok = True
    detail = ""
    by_key = {}
    for row in holding_rows:
        by_key.setdefault((row["user_id"], row["market"], row["snapshot_date"]), []).append(row)

    seen_keys = set()
    for row in rows:
        key = (row["user_id"], row["market"], row["snapshot_date"])
        seen_keys.add(key)
        details = by_key.get(key, [])
        priced = [d for d in details if d["priced"]]
        exact_value = sum((Decimal(str(d["market_value"])) for d in priced), Decimal(0))
        exact_cost = sum((Decimal(str(d["cost"])) for d in priced), Decimal(0))
        checks = (
            (Decimal(str(row["total_value"])) == exact_value, "total_value"),
            (Decimal(str(row["total_cost"])) == exact_cost, "total_cost"),
            (row["holdings_count"] == len(details), "holdings_count"),
            (row["priced_count"] == len(priced), "priced_count"),
            (row["unpriced_count"] == len(details) - len(priced), "unpriced_count"),
            (all(d["currency"] == row["currency"] for d in details), "currency"),
            (all(d[rdb.PRICE_STAMP_FIELD] == row[rdb.PRICE_STAMP_FIELD] for d in details),
             "price_as_of_kst"),
        )
        for passed, field in checks:
            if not passed:
                ok = False
                detail += f" [{key} {field}]"
    # 합계 행이 없는데 종목별 행만 있는 날짜가 있으면 두 표의 날짜 집합이 어긋난 것
    for key in by_key:
        if key not in seen_keys:
            ok = False
            detail += f" [합계 없는 종목별 행 {key}]"
    check(ok, label, detail)


def test_holding_snapshots():
    print("\n[9-2] 🧾 종목별 일일 스냅샷 — 합계와 절대 어긋나지 않기")

    holdings = [
        holding(MARKET_KR, "005930", 10, 70000, "삼성전자"),
        holding(MARKET_KR, "000660", 2, 1000000, "SK하이닉스"),
        holding(MARKET_KR, "999999", 3, 1234.56, "가격모르는종목"),
        holding(MARKET_US, "AAPL", 3, 200.0, "Apple"),
    ]
    prices = {(MARKET_KR, "005930"): 80000.0,
              (MARKET_KR, "000660"): 1200000.0,
              (MARKET_US, "AAPL"): 250.0}
    session_dates = {MARKET_KR: "2026-08-12", MARKET_US: "2026-08-12"}
    benchmarks = {MARKET_KR: ("KOSPI", 6345.53), MARKET_US: ("SP500_PROXY_SPY", 754.6)}
    stamps = {MARKET_KR: "2026-08-12 17:50", MARKET_US: "2026-08-13 07:14"}

    rows, holding_rows, skipped = rdb.build_snapshot_rows_with_holdings(
        "u1", holdings, price_lookup_factory(prices), session_dates, benchmarks,
        price_stamp_by_market=stamps)

    # ---- ⑴ 행 자체가 제대로 만들어지는지 -------------------------------------
    check(len(rows) == 2 and len(holding_rows) == 4 and not skipped,
          "합계 2행(KR/US) + 종목별 4행(가격 모르는 종목 포함)이 한 번에 생성됨")
    kr_details = [r for r in holding_rows if r["market"] == MARKET_KR]
    samsung = next(r for r in kr_details if r["ticker"] == "005930")
    unknown = next(r for r in kr_details if r["ticker"] == "999999")
    check(approx(samsung["market_value"], 800000.0) and approx(samsung["cost"], 700000.0)
          and approx(samsung["current_price"], 80000.0) and samsung["priced"] is True,
          "가격을 아는 종목: 수량×현재가 / 수량×매입가 저장")
    check(samsung["stock_name"] == "삼성전자",
          "그날 기준 종목명도 함께 저장(holdings 에서 종목이 사라져도 과거 표가 안 비게)")
    check(unknown["priced"] is False and unknown["current_price"] is None
          and unknown["market_value"] is None,
          "가격을 몰랐던 종목: 값을 지어내지 않고 NULL + priced=False (0원으로 세지 않음)")
    check(approx(unknown["cost"], 3 * 1234.56),
          "가격을 몰라도 **매입원가는 아는 값**이라 그대로 기록(수량·매입가도 함께)")
    check(all(r["currency"] == "KRW" for r in kr_details)
          and all(r["currency"] == "USD" for r in holding_rows if r["market"] == MARKET_US),
          "통화는 시장에서 파생 — 원/달러가 한 표에서 섞이지 않음")
    check(all(r["snapshot_date"] == "2026-08-12" for r in holding_rows),
          "종목별 행의 거래일 = 합계 행의 거래일(배치 실행 시각이 아님)")
    check(next(r for r in holding_rows if r["market"] == MARKET_KR)[rdb.PRICE_STAMP_FIELD]
          == "2026-08-12 17:50"
          and next(r for r in holding_rows if r["market"] == MARKET_US)[rdb.PRICE_STAMP_FIELD]
          == "2026-08-13 07:14",
          "가격 수집 시각(KST)이 종목별 행에도 시장별로 그대로 실림")
    check("profit" not in samsung and "profit_pct" not in samsung,
          "이익·수익률은 저장하지 않음(market_value-cost 로 언제든 정확히 나오는 파생값 — "
          "저장하면 계산 경로가 하나 더 생겨 어긋날 여지가 됨)")

    # ---- ⑵ 🔴 합계 = 종목별 합 (이번 작업의 핵심 요구사항) --------------------
    _assert_totals_match_details(rows, holding_rows,
                                 "🔴 합계 행의 모든 수치가 종목별 행의 합과 정확히 일치")

    # 값이 지저분해도 어긋나지 않는지 — 반올림이 종목별 저장값 기준으로 **한 번만** 일어나고,
    # 합산이 DB(numeric)와 같은 십진수 방식으로 되는지를 보는 검사입니다.
    #   · 현실적인 포트폴리오(한국=정수 수량·정수 단가, 미국=소수점 수량·소액) → **정확히 일치**
    #   · 비현실적으로 큰 금액 + 무한소수 단가 → 배정밀도 표현 한계까지만(허용오차 이내).
    #     이 한계는 utils/report_db._sum_money() 주석에 실측과 함께 적어 뒀습니다.
    rng = random.Random(20260813)
    exact_ok, tolerant_ok, worst = True, True, 0.0
    for round_index in range(600):
        extreme = round_index % 3 == 0
        many, prices_rand = [], {}
        market = MARKET_KR if round_index % 2 else MARKET_US
        for i in range(rng.randint(1, 20)):
            ticker = f"{i:06d}" if market == MARKET_KR else f"TST{i}"
            if extreme:
                quantity = rng.choice([1234.567891, 0.333333, 98765.4321])
                avg = rng.choice([1000 / 3, 93076.923076923, 12345678.9])
                price = rng.choice([1e7 / 3, 987654321.123456, 80000.000001])
            elif market == MARKET_KR:
                quantity = rng.randint(1, 5000)
                # 가중평균 매입단가는 무한소수가 됩니다(내 성적표의 실제 계산 결과)
                avg = rng.choice([rng.randint(100, 500000), 93076.923076, 1210000 / 13])
                price = rng.randint(100, 500000)
            else:
                quantity = rng.choice([rng.randint(1, 500), round(rng.random() * 100, 6)])
                avg = round(rng.uniform(0.01, 900), 4)
                price = round(rng.uniform(0.01, 900), 4)
            many.append(holding(market, ticker, quantity, avg))
            if rng.random() < 0.85:
                prices_rand[(market, ticker)] = price
        r2, h2, _ = rdb.build_snapshot_rows_with_holdings(
            "u1", many, price_lookup_factory(prices_rand), {market: "2026-08-12"})
        for row in r2:
            priced = [d for d in h2 if d["priced"]]
            for field, key in (("total_value", "market_value"), ("total_cost", "cost")):
                exact = sum((Decimal(str(d[key])) for d in priced), Decimal(0))
                gap = float(abs(Decimal(str(row[field])) - exact))
                if extreme:
                    # 금액 자체가 비현실적(수십조 원)인 구간 — 여기서 남는 오차는 우리 계산이
                    # 아니라 **배정밀도 실수의 표현 한계**입니다. 그래서 절대값이 아니라
                    # 상대오차로 봅니다(1e-13 = 배정밀도 한계보다 한참 느슨한 상한).
                    if gap > abs(float(row[field])) * 1e-13 + rdb.TOTAL_MATCH_TOLERANCE:
                        tolerant_ok = False
                else:
                    worst = max(worst, gap)
                    if gap != 0:
                        exact_ok = False
                    if gap > rdb.TOTAL_MATCH_TOLERANCE:
                        tolerant_ok = False
    check(exact_ok,
          f"🔴 현실적인 400가지 무작위 포트폴리오에서 합계 = 종목별 합이 **정확히** 일치 "
          f"(Decimal 비교 — DB numeric 이 계산할 값과 동일. 실측 최대 오차 {worst:g})")
    check(tolerant_ok,
          "🔴 수십조 원처럼 비현실적으로 큰 금액에서도 오차가 배정밀도 표현 한계 안에 머묾"
          f"(허용오차 {rdb.TOTAL_MATCH_TOLERANCE} + 상대오차 1e-13 — "
          "_sum_money() 주석에 이 한계를 그대로 적어 뒀습니다)")

    # ---- ⑶ 두 표의 날짜·시장 집합이 항상 같은지 -------------------------------
    only_unpriced, only_unpriced_details, skips2 = rdb.build_snapshot_rows_with_holdings(
        "u1", [holding(MARKET_KR, "999999", 1, 100)], price_lookup_factory({}),
        {MARKET_KR: "2026-08-12"})
    check(only_unpriced == [] and only_unpriced_details == [],
          "가격을 하나도 모르는 시장: 합계도 종목별도 만들지 않음"
          "(종목별만 남아 '리포트엔 없는 날'이 생기지 않게)")
    check(any("현재가를 알 수 없어" in s["reason"] for s in skips2), "그 사유가 기록됨")

    no_date_rows, no_date_details, skips3 = rdb.build_snapshot_rows_with_holdings(
        "u1", holdings, price_lookup_factory(prices), {MARKET_KR: "2026-08-12"}, benchmarks)
    check(all(r["market"] == MARKET_KR for r in no_date_rows + no_date_details),
          "거래일을 모르는 시장(US)은 합계도 종목별도 안 만듦")
    _assert_totals_match_details(no_date_rows, no_date_details,
                                 "거래일이 일부만 확인된 경우에도 두 표가 일치")

    broken = list(holdings) + [{"market": "KR", "ticker": "005380", "quantity": "??",
                                "avg_purchase_price": 1000, "currency": "KRW"}]
    b_rows, b_details, b_skips = rdb.build_snapshot_rows_with_holdings(
        "u1", broken, price_lookup_factory(prices), session_dates, benchmarks)
    check(any("평가할 수 없어" in s["reason"] for s in b_skips),
          "평가 자체가 불가능한 보유 행은 사유를 남기고 제외")
    _assert_totals_match_details(b_rows, b_details,
                                 "깨진 보유 행이 섞여도 두 표가 똑같이 제외해서 계속 일치")

    # ---- ⑷ 기존 시그니처 무손상 ----------------------------------------------
    legacy = build_snapshot_rows("u1", holdings, price_lookup_factory(prices),
                                 session_dates, benchmarks, price_stamp_by_market=stamps)
    check(isinstance(legacy, tuple) and len(legacy) == 2 and legacy[0] == rows,
          "기존 build_snapshot_rows() 는 2-튜플 그대로이고 합계 행도 완전히 동일"
          "(호출부·기존 테스트 무손상)")

    # ---- ⑸ 저장 배선 ----------------------------------------------------------
    client = _FakeClient()
    saved = rdb.upsert_holding_snapshots(client, [dict(r) for r in holding_rows])
    call = client.log[-1]
    check(saved == 4 and call["op"] == "upsert"
          and call["table"] == "portfolio_holding_snapshots",
          "종목별도 upsert 로 저장(같은 날 두 번 돌려도 행이 늘지 않음)")
    check(call["on_conflict"] == "user_id,market,ticker,snapshot_date",
          "충돌 키가 스키마의 유니크 제약(사용자×시장×종목×거래일)과 일치")
    check(rdb.upsert_holding_snapshots(client, []) == 0, "저장할 행이 없으면 호출도 하지 않음")
    chunky = _FakeClient()
    rdb.upsert_holding_snapshots(chunky, [dict(r, ticker=f"T{i}") for i, r in
                                          enumerate(holding_rows * 2)], chunk_size=3)
    check(len([c for c in chunky.log if c["op"] == "upsert"]) == 3, "많은 행은 나눠서 저장")
    expect_raises(lambda: rdb.upsert_holding_snapshots(
        _FakeClient(), [dict(holding_rows[0]), dict(holding_rows[0])]), ReportError,
        "같은 (사용자·시장·종목·거래일) 이 두 번 들어오면 임의로 합치지 않고 중단")
    expect_raises(lambda: rdb.upsert_holding_snapshots(None, [dict(holding_rows[0])]),
                  ReportError, "클라이언트가 없으면 오류")

    check(rdb.is_missing_holding_table_error(
        "PGRST205: Could not find the table 'public.portfolio_holding_snapshots' "
        "in the schema cache") is True,
        "테이블 없음(PGRST205) 을 알아봄")
    check(rdb.is_missing_holding_table_error("네트워크가 끊겼습니다") is False,
          "무관한 오류를 테이블 없음으로 오인하지 않음(진짜 사고가 조용히 묻히지 않게)")
    check(rdb.is_missing_holding_table_error(
        "Could not find the table 'public.portfolio_daily_snapshots' in the schema cache")
        is False,
        "합계 테이블이 없다는 오류는 이 폴백 경로로 새지 않음")

    # ---- ⑹ 두 표 중 한쪽만 실패하는 경우 --------------------------------------
    legacy_db = _NoHoldingTableClient()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        outcome = rdb.save_holding_snapshots(legacy_db, [dict(r) for r in holding_rows],
                                             summary_saved=2)
    log_text = buffer.getvalue()
    check(outcome["saved"] == 0 and outcome["skipped_reason"],
          "테이블이 없으면 예외로 배치를 죽이지 않고 이 단계만 건너뜀")
    check("report_schema.sql" in log_text and "오너 할 일" in log_text,
          "무엇을 실행하면 되는지 로그에 그대로 안내(조용히 넘어가지 않음)")
    check("합계 스냅샷은 정상 저장" in log_text,
          "기존 기능은 멀쩡하다는 사실도 함께 알림")
    boom_log = io.StringIO()

    def _boom():
        with contextlib.redirect_stdout(boom_log):
            rdb.save_holding_snapshots(_BoomClient(), [dict(holding_rows[0])], summary_saved=2)

    expect_raises(_boom, ReportError,
                  "테이블 없음이 아닌 오류는 삼키지 않고 그대로 올림(배치가 빨갛게 실패)")
    check("합계 스냅샷 2행은 이미 저장" in boom_log.getvalue(),
          "그때도 '합계는 이미 저장됐고 잃은 수치는 없다'는 사실을 로그에 남김")

    # ---- ⑺ 배치 end-to-end ----------------------------------------------------
    batch_client = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": 10, "avg_purchase_price": 70000, "currency": "KRW"},
        {"id": "2", "user_id": "u1", "market": "KR", "ticker": "999999",
         "quantity": 1, "avg_purchase_price": 1000, "currency": "KRW"},
    ]})
    summary = rdb.run_daily_snapshot_batch(service_client=batch_client, dry_run=True)
    check(len(summary["holding_rows"]) == 2 and summary["holding_saved"] == 0,
          "dry-run: 종목별 행도 계산되지만 저장은 하지 않음")
    _assert_totals_match_details(summary["rows"], summary["holding_rows"],
                                 "🔴 실제 저장소 데이터로 돈 배치에서도 합계 = 종목별 합")

    live = _FakeClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": 10, "avg_purchase_price": 70000, "currency": "KRW"},
    ]})
    with contextlib.redirect_stdout(io.StringIO()):
        summary2 = rdb.run_daily_snapshot_batch(service_client=live, dry_run=False)
    upserts = [c for c in live.log if c["op"] == "upsert"]
    check(summary2["saved"] == 1 and summary2["holding_saved"] == 1,
          "실제 저장 경로: 합계 1행 + 종목별 1행")
    check([c["table"] for c in upserts] == ["portfolio_daily_snapshots",
                                            "portfolio_holding_snapshots"],
          "저장 순서 = 합계 먼저, 종목별 나중(기존 기능을 새 기능이 막지 않게)")
    check(all(c["table"] != "holdings" or c["op"] == "select" for c in live.log),
          "배치는 여전히 holdings 를 읽기만 함")

    missing_table_db = _NoHoldingTableClient({"holdings": [
        {"id": "1", "user_id": "u1", "market": "KR", "ticker": "005930",
         "quantity": 10, "avg_purchase_price": 70000, "currency": "KRW"},
    ]})
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        summary3 = rdb.run_daily_snapshot_batch(service_client=missing_table_db, dry_run=False)
    check(summary3["saved"] == 1 and summary3["holding_saved"] == 0
          and summary3["holding_skipped_reason"],
          "🔴 종목별 테이블이 아직 없어도 배치가 죽지 않고 **합계 저장은 정상 진행**"
          "(기존 기능 무손상 — 이번 확장은 순수 추가)")
    check("portfolio_daily_snapshots" in [c["table"] for c in missing_table_db.log
                                          if c["op"] == "upsert"],
          "그 상황에서도 합계 스냅샷은 실제로 저장됨")

    # ---- ⑻ 조회·정규화 --------------------------------------------------------
    stored = [dict(r) for r in holding_rows]
    reader = _FakeClient({"portfolio_holding_snapshots":
                          stored + [dict(stored[0], user_id="other", market="KR",
                                         ticker="000020", market_value=999.0)]})
    fetched = rdb.fetch_user_holding_snapshots(reader, "u1", market="KR",
                                               start_date="2026-08-01",
                                               end_date="2026-08-31")
    filters = reader.log[-1]["filters"]
    check(("eq", "user_id", "u1") in filters and ("eq", "market", "KR") in filters,
          "RLS 위에 user_id·market 필터를 한 번 더 검(이중 방어)")
    check(any(f[0] == "gte" for f in filters) and any(f[0] == "lte" for f in filters),
          "기간만 잘라서 조회(행이 많은 표라 전체를 끌어오지 않음)")
    check(len(fetched) == 3 and all(r["market"] == MARKET_KR for r in fetched),
          "본인·해당 시장 행만 조회됨")
    check([r["ticker"] for r in fetched] == sorted(r["ticker"] for r in fetched),
          "같은 날은 종목코드 순으로 정렬")
    check(all(isinstance(r["snapshot_date"], date) for r in fetched), "날짜는 date 로 정규화")
    weird = {r["ticker"]: r for r in rdb.sort_holding_snapshots([
        dict(stored[0], priced=True, current_price=None, market_value=None),
        dict(stored[0], ticker="000001", stock_name="  ", **{rdb.PRICE_STAMP_FIELD: "  "}),
    ])}
    check(weird["005930"]["priced"] is False,
          "priced=True 인데 값이 비어 있는 손상 행은 '가격 있음'으로 둔갑시키지 않음")
    check(weird["000001"]["stock_name"] is None
          and weird["000001"][rdb.PRICE_STAMP_FIELD] is None,
          "공백만 있는 종목명·시각은 None 으로 정규화(빈 문자열과 없음을 섞지 않음)")
    expect_raises(lambda: rdb.sort_holding_snapshots([dict(stored[0], quantity="??")]),
                  ReportError, "손상된 숫자는 조용히 0으로 만들지 않고 오류")
    expect_raises(lambda: rdb.fetch_user_holding_snapshots(reader, None), ReportError,
                  "로그인 정보가 없으면 오류(빈 표로 위장하지 않음)")

    # ---- ⑼ 화면용 요약(build_holding_history) --------------------------------
    multi = []
    for day, p1, p2 in (("2026-08-10", 75000.0, 1100000.0),
                        ("2026-08-11", 78000.0, None),
                        ("2026-08-12", 80000.0, 1200000.0)):
        day_prices = {(MARKET_KR, "005930"): p1}
        if p2 is not None:
            day_prices[(MARKET_KR, "000660")] = p2
        _r, _h, _s = rdb.build_snapshot_rows_with_holdings(
            "u1", holdings[:2], price_lookup_factory(day_prices), {MARKET_KR: day},
            price_stamp_by_market={MARKET_KR: f"{day} 17:50"})
        multi.extend(_h)
    # 기간 중간에 팔린 종목(마지막 날에는 기록 없음)
    _r, sold_rows, _s = rdb.build_snapshot_rows_with_holdings(
        "u1", [holding(MARKET_KR, "005380", 5, 200000, "현대차")],
        price_lookup_factory({(MARKET_KR, "005380"): 210000.0}), {MARKET_KR: "2026-08-10"})
    multi.extend(sold_rows)
    # DB 에서 읽어 온 것과 같은 상태로 맞춥니다(날짜는 date, 숫자는 float).
    multi = rdb.sort_holding_snapshots(multi)

    history = rdb.build_holding_history(multi, "2026-08-01", "2026-08-31")
    check(history["base_date"] == date(2026, 8, 12) and history["first_date"] == date(2026, 8, 10),
          "기준일 = 기간 안 마지막 기록일")
    check([r["ticker"] for r in history["rows"]] == ["000660", "005930"],
          "기준일 하루의 종목만, 평가금액 큰 순으로 정렬(날짜를 섞지 않음)")
    check(all(r["snapshot_date"] == history["base_date"] for r in history["rows"]),
          "🔴 표의 모든 행이 **같은 거래일** — 종목마다 각자의 마지막 날을 긁어 모으지 않음")
    check(approx(history["totals"]["market_value"], 800000.0 + 2400000.0)
          and approx(history["totals"]["cost"], 700000.0 + 2000000.0),
          "표 합계 = 그날 종목별 합")
    check(history["totals"]["holdings_count"] == 2 and history["totals"]["priced_count"] == 2,
          "표 합계에 종목 수·담긴 종목 수가 함께")
    samsung_row = next(r for r in history["rows"] if r["ticker"] == "005930")
    check(approx(samsung_row["price_change_pct"], (80000 - 75000) / 75000 * 100),
          "기간 주가등락 = 기간 안 첫 가격 → 기준일 가격(수량 변화의 영향을 받지 않음)")
    check(samsung_row["price_change_from"] == date(2026, 8, 10), "비교한 날짜를 함께 돌려줌")
    hynix_row = next(r for r in history["rows"] if r["ticker"] == "000660")
    check(hynix_row["days_recorded"] == 3 and hynix_row["unpriced_days"] == 1,
          "며칠치가 기록됐고 그중 며칠이 '가격 모름'이었는지 표시")
    check([g["ticker"] for g in history["gone"]] == ["005380"]
          and history["gone"][0]["last_date"] == date(2026, 8, 10),
          "기간 중 기록이 끊긴 종목은 표에 섞지 않고 따로 알려 줌")
    check(len(history["daily_by_ticker"]["005930"]) == 3
          and approx(history["daily_by_ticker"]["005930"][0]["profit"], 50000.0),
          "종목별 일별 추이 + 이익은 계산해서 붙임(저장값이 아님)")
    check(history["daily_by_ticker"]["000660"][1]["profit"] is None,
          "가격을 몰랐던 날의 이익은 0 이 아니라 없음(None)")

    one_day = rdb.build_holding_history(
        [r for r in multi if r["snapshot_date"] == date(2026, 8, 12)])
    check(one_day["rows"][0]["price_change_pct"] is None,
          "비교할 날이 하루뿐이면 등락률을 만들어내지 않음(—)")
    check(rdb.build_holding_history([])["rows"] == [], "기록이 없으면 빈 결과(빈 표)")
    check(rdb.build_holding_history(multi, "2027-01-01", "2027-12-31")["rows"] == [],
          "기간 밖은 걸러짐")
    mixed = [dict(multi[0]), dict(multi[0], market="US", currency="USD", ticker="AAPL")]
    expect_raises(lambda: rdb.build_holding_history(mixed), ReportError,
                  "원화·달러가 섞여 들어오면 합산하지 않고 중단(환율 변환 없음)")

    match = rdb.compare_holding_total(3200000.0, 3200000.0)
    check(match["comparable"] and match["matches"] is True, "대조: 일치")
    gap = rdb.compare_holding_total(3200000.0, 3100000.0)
    check(gap["matches"] is False and approx(gap["diff"], 100000.0)
          and "어긋납니다" in gap["message"], "대조: 불일치 시 차이를 그대로 알림")
    check(rdb.compare_holding_total(None, 100.0)["comparable"] is False,
          "대조할 값이 없으면 '일치'라고 말하지 않음")

    # ---- ⑽ 화면 문구 ---------------------------------------------------------
    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.report_view")
        real_st = module.st
        recorder = _HoldingViewRecorder()
        module.st = recorder
        try:
            summary_rows = rdb.sort_snapshots([
                snap(date(2026, 8, 12), 3200000.0, 2700000.0, holdings_count=2, priced_count=2),
            ])
            module._render_holding_history(MARKET_KR, multi, summary_rows,
                                           date(2026, 8, 1), date(2026, 8, 31), "KRW")
            table = next(t for t in recorder.markdown_calls if t.startswith("| 종목 |"))
            check("삼성전자 (005930)" in table and "SK하이닉스 (000660)" in table,
                  "한눈에 보는 표: 종목명(코드) 표기가 '내 성적표'와 같은 관례")
            check(":red[" in table or ":blue[" in table,
                  "수익률 색상이 국내 증시 관례(오르면 빨강/내리면 파랑)로 통일")
            check("원" in table and "$" not in table, "금액은 format_amount() 통화 표기 그대로")
            check("**합계 2종목**" in table, "표 맨 아래 합계 한 줄 — 한 장에서 총액이 바로 보임")
            check(len(table.splitlines()) <= 6,
                  "종목 수 + 헤더 + 합계 만큼만 — 기간 전체를 한 표에 늘어놓지 않음")
            # 2026-08-13 (#114) 오너 지시로 **정상일 때는 아무 말도 하지 않습니다.**
            # ("⚖️ 데이터 대조 통과 …"는 개발자용 자체 검증 문구 — 방문자에게는 소음이고,
            #  정상일 때 매번 뜨면 진짜 경고가 묻힙니다.) 대조 자체는 계속 돌고, 어긋난
            # 경우의 경고는 아래 '대조 불일치' 검사가 그대로 지킵니다.
            check(not any("대조" in t for t in
                          recorder.caption_calls + recorder.info_calls + recorder.warning_calls),
                  "🔴 합계와 일치하면 대조 문구를 아예 띄우지 않음(정상일 땐 조용히)")
            check(any("005380" in t for t in recorder.caption_calls),
                  "기간 중 기록이 끊긴 종목을 표에 섞지 않고 따로 안내")
            daily = next(t for t in recorder.markdown_calls if t.startswith("| 거래일 |"))
            check("종가 수집 시각(KST)" in daily and "2026-08-10 17:50" in daily,
                  "펼친 일별 표에는 그날 가격 수집 시각(한국시간)까지 함께")

            # 가격을 몰랐던 날 — 빈칸·이전 가격 대체 금지
            recorder.reset()
            unpriced_only = [r for r in multi if r["ticker"] == "000660"
                             and r["snapshot_date"] <= date(2026, 8, 11)]
            module._render_holding_history(MARKET_KR, unpriced_only, [],
                                           date(2026, 8, 1), date(2026, 8, 31), "KRW")
            table2 = next(t for t in recorder.markdown_calls if t.startswith("| 종목 |"))
            check("가격 모름" in table2,
                  "가격을 몰랐던 날은 '가격 모름'으로 정직하게 표시(빈칸·이전 가격 대체 금지)")
            check("1,100,000" not in table2,
                  "전날 가격을 끌어와서 채우지 않음")
            check("100.00%" not in table2,
                  "그날 가격을 아는 종목이 하나도 없으면 합계 비중을 '100%'라고 쓰지 않음(§0-1)")
            check("모름" in table2, "그 경우 종목의 비중 칸은 '모름'")
            # 대조할 합계 스냅샷이 없는 경우 — 화면은 **아무 주장도 하지 않습니다**.
            # 말하지 않는 것과 "일치한다"고 말하는 것은 전혀 다릅니다(§0-1 위반 아님).
            check(not any("일치" in t for t in
                          recorder.caption_calls + recorder.info_calls + recorder.warning_calls),
                  "대조할 합계 스냅샷이 없으면 '일치'라고 말하지 않음")

            # 불일치 — 숨기지 않고 경고
            recorder.reset()
            wrong = rdb.sort_snapshots([snap(date(2026, 8, 12), 999.0, 111.0)])
            module._render_holding_history(MARKET_KR, multi, wrong,
                                           date(2026, 8, 1), date(2026, 8, 31), "KRW")
            check(any("대조 불일치" in t for t in recorder.warning_calls),
                  "🔴 합계와 종목별 합이 어긋나면 숨기지 않고 경고로 드러냄")

            # 표가 아직 없는 상태 — 안내로 대체(리포트 나머지는 정상)
            recorder.reset()
            module._render_holding_history(
                MARKET_KR, [], [], date(2026, 8, 1), date(2026, 8, 31), "KRW",
                error="PGRST205: Could not find the table "
                      "'public.portfolio_holding_snapshots' in the schema cache")
            # 2026-08-13 (#114) — 방문자에게는 "아직 준비되지 않았습니다" 한 줄만 보이고,
            # 설치 절차 전문은 '🔧 관리자' expander 안으로 접었습니다(문구 간소화). 안내
            # 자체가 사라지면 안 되므로 실행할 SQL 파일 이름은 그대로 있어야 합니다.
            check(any("준비되지 않았습니다" in t for t in recorder.info_calls),
                  "테이블이 아직 없으면 그 사실을 화면에 알림")
            check(any("report_schema.sql" in t for t in recorder.markdown_calls),
                  "실행할 SQL 파일 안내는 관리자용으로 접어서 보존(삭제하지 않음)")
            check(not recorder.error_calls,
                  "그 경우는 빨간 오류가 아니라 안내(기존 리포트는 정상 동작하므로)")

            recorder.reset()
            module._render_holding_history(MARKET_KR, [], [], date(2026, 8, 1),
                                           date(2026, 8, 31), "KRW",
                                           error="네트워크가 끊겼습니다")
            check(any("네트워크" in t for t in recorder.error_calls),
                  "그 밖의 조회 실패는 조용히 넘기지 않고 화면까지 도달시킴(§0-1)")

            # 기간 리포트가 "데이터 부족"인 구간에서도 **저장된 종목별 기록은 보여야** 합니다.
            # (기능을 켠 첫 달은 기간 시작 이전 기준점이 없어 거의 항상 INSUFFICIENT 입니다 —
            #  여기서 숨기면 오너가 SQL 을 실행하고도 새 표를 한참 못 봅니다.)
            recorder.reset()
            window_only = rdb.sort_snapshots([
                snap(date(2026, 8, 10), 3100000.0, 2700000.0),
                snap(date(2026, 8, 12), 3200000.0, 2700000.0),
            ])
            module._render_market_block(MARKET_KR, window_only, PERIOD_MONTHLY,
                                        date(2026, 8, 15), holding_rows=multi)
            check(any("데이터 부족" in t for t in recorder.error_calls),
                  "기간 시작 이전 기준점이 없으면 '데이터 부족'이 여전히 주 컨텐츠(§3 무손상)")
            check(any(t.startswith("| 종목 |") for t in recorder.markdown_calls),
                  "그 구간에서도 저장된 종목별 기록은 그대로 보여 줌(계산이 아니라 기록이므로)")
        finally:
            module.st = real_st
    except Exception as exc:  # noqa: BLE001
        check(False, "views.report_view 종목별 상세 렌더링 검증",
              f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.report_view", None)
            sys.modules.pop("views.scorecard_view", None)


# =============================================================================
# 9-3. ◀ 이전 기간 / 최신 기간 / 다음 기간 ▶ 버튼 (2026-08-13 #114 회귀 방지)
# =============================================================================
#  오너 신고: "일간으로 했을 때 맨위에 있는 이전기간 / 최신기간 / 다음기간 저거 작동 안하고
#  있어 … 저 단추는 뭐하러 있는건지 모르겠어".
#
#  🔴 이 블록에서 가장 중요한 검사는 **"다음 렌더에서 달력 위젯 자체(session_state의
#     report_ref_date_input 키)가 새 날짜를 갖는가"** 입니다. `report_ref_date`(별도 키)만
#     확인하면 옛 코드도 통과해 버립니다 — 옛 버그는 바로 "다른 키만 바뀌고 위젯은 그대로"
#     였기 때문입니다.
# =============================================================================
class _Rerun(Exception):
    """st.rerun() 흉내 — Streamlit 처럼 그 자리에서 스크립트 실행을 끊습니다."""


class _PeriodControlsFake:
    """
    기준일 달력의 **Streamlit 실제 규칙**을 그대로 흉내 내는 가짜 st.

    재현하는 핵심 규칙: *키를 준 위젯은 한 번 만들어지고 나면 `session_state[그 키]` 가
    유일한 출처이고, `value=` 인자는 무시된다.* 이 규칙을 흉내 내지 않으면 이번 버그를
    재현할 수도, 회귀를 막을 수도 없습니다.
    """

    def __init__(self, pressed=None):
        self.session_state = {}
        self.pressed = pressed
        self.rerun_count = 0

    def selectbox(self, _label, options, index=0, key=None, **_kwargs):
        options = list(options)
        value = options[index]
        if key is not None:
            self.session_state[key] = value
        return value

    def date_input(self, _label, value=None, key=None, **_kwargs):
        if key is None:
            return value
        if key in self.session_state:      # ← 위젯 키가 언제나 이깁니다(= 실제 Streamlit)
            return self.session_state[key]
        self.session_state[key] = value
        return value

    def button(self, _label, key=None, **_kwargs):
        return key == self.pressed

    def rerun(self):
        self.rerun_count += 1
        raise _Rerun()

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    # `with col_period:` 를 쓸 수 있게 — 던더 메서드는 __getattr__ 로 가로챌 수 없어 직접 정의.
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None
        return _noop


def test_period_buttons():
    print("\n[9-3] 기간 이동 버튼 — 눌러도 반응 없던 버그(#114) 회귀 방지")

    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.report_view")
        real_st = module.st
        fake = _PeriodControlsFake()
        module.st = fake
        try:
            widget_key = module.REF_DATE_WIDGET_KEY
            ref_key = module.SESSION_REF_DATE_KEY
            pending_key = module.SESSION_PENDING_REF_DATE_KEY
            today = date.today()

            def render(pressed=None):
                """한 번의 화면 렌더. 버튼을 눌렀으면 rerun 으로 끊깁니다(실제와 동일)."""
                fake.pressed = pressed
                try:
                    return module._render_period_controls()
                except _Rerun:
                    return None

            check(widget_key == "report_ref_date_input" and widget_key != ref_key,
                  "달력 위젯의 진짜 키와 '기준일 저장용' 키가 서로 다른 키임(버그의 무대)")

            # ---- 일간 ----------------------------------------------------
            fake.session_state[module.SESSION_PERIOD_KEY] = PERIOD_DAILY
            period, ref = render()
            check(period == PERIOD_DAILY and ref == today, "첫 렌더 = 일간 · 오늘")
            check(fake.session_state[widget_key] == today, "달력 위젯 키에 오늘이 들어감")

            check(render(pressed="report_prev_period") is None and fake.rerun_count == 1,
                  "'◀ 이전 기간'을 누르면 st.rerun() 으로 화면을 다시 그림")
            check(fake.session_state.get(pending_key) == today - timedelta(days=1),
                  "버튼은 위젯 키를 직접 못 고치므로 pending 표시만 남김(위젯 생성 뒤라 대입 금지)")
            check(fake.session_state[widget_key] == today,
                  "그 렌더에서는 달력이 아직 옛 날짜 — 대입은 다음 렌더 맨 앞에서 일어남")

            period, ref = render()
            yesterday = today - timedelta(days=1)
            check(ref == yesterday, "🔴 다음 렌더에서 기준일이 실제로 하루 전으로 이동")
            check(fake.session_state[widget_key] == yesterday,
                  "🔴 **달력 위젯 자체**(report_ref_date_input)가 새 날짜를 가짐 "
                  "— 옛 코드는 여기서 실패했습니다(다른 키만 바뀌고 위젯은 그대로)")
            check(fake.session_state[ref_key] == yesterday, "기준일 저장용 키도 새 날짜")
            check(pending_key not in fake.session_state, "pending 표시는 쓰고 나서 지워짐")

            render(pressed="report_next_period")
            period, ref = render()
            check(ref == today and fake.session_state[widget_key] == today,
                  "'다음 기간 ▶' 은 정확히 되돌아옴(하루 앞으로)")

            render(pressed="report_prev_period")
            render()
            render(pressed="report_prev_period")
            period, ref = render()
            check(ref == today - timedelta(days=2), "여러 번 눌러도 누적해서 이동")
            render(pressed="report_latest_period")
            period, ref = render()
            check(ref == today and fake.session_state[widget_key] == today,
                  "'최신 기간' 은 어디서 눌러도 오늘로 돌아옴")

            # ---- 월간 (기간 단위가 달라도 같은 경로) ----------------------
            fake.session_state[module.SESSION_PERIOD_KEY] = PERIOD_MONTHLY
            fake.session_state[widget_key] = date(2026, 8, 13)
            fake.session_state[ref_key] = date(2026, 8, 13)
            render()
            render(pressed="report_prev_period")
            period, ref = render()
            check(period == PERIOD_MONTHLY and ref == date(2026, 7, 1),
                  "월간에서 '이전 기간' = 지난달 1일(shift_period 규칙 그대로)")
            check(fake.session_state[widget_key] == date(2026, 7, 1),
                  "월간에서도 달력 위젯 자체가 새 날짜를 가짐")

            # 버튼을 누르지 않은 평범한 렌더가 값을 되돌리지 않는지(옛 버그의 두 번째 겹)
            period, ref = render()
            check(ref == date(2026, 7, 1) and fake.session_state[widget_key] == date(2026, 7, 1),
                  "그냥 다시 그리기만 하면 기준일이 옛 값으로 되돌아가지 않음")
        finally:
            module.st = real_st
    except Exception as exc:  # noqa: BLE001
        check(False, "기간 이동 버튼 검증", f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.report_view", None)
            sys.modules.pop("views.scorecard_view", None)


# =============================================================================
# 9-4. 📊 종목별 비중(%) · 비중 변화 (2026-08-13 #114 신설)
# =============================================================================
#  오너가 수기로 관리해 온 표를 그대로 옮긴 기능입니다(오너 제공 자료 참고).
#     · "종목 | 현재금액 | 현재 금액 합 | 비율"
#     · "종목 | 지난달 비중 | 이번달 비중 | 차이"
#  🔴 핵심 검사: **이미 저장된 값만으로 계산**되고(새 테이블 없음), 가격을 몰랐던 종목을
#     0% 로 둔갑시키지 않으며, 매매로 생기거나 사라진 종목을 숨기지 않는지.
# =============================================================================
def test_holding_weights():
    print("\n[9-4] 📊 종목별 비중(%) · 기간 시작 대비 비중 변화")

    holdings_kr = [holding(MARKET_KR, "005930", 10, 70000, "삼성전자"),
                   holding(MARKET_KR, "000660", 2, 1000000, "SK하이닉스")]

    def _rows(day, prices, items=None):
        _r, detail, _s = rdb.build_snapshot_rows_with_holdings(
            "u1", items or holdings_kr, price_lookup_factory(prices), {MARKET_KR: day},
            price_stamp_by_market={MARKET_KR: f"{day} 17:50"})
        return detail

    rows = []
    # 8/10 — 세 종목(현대차 포함). 합계 4,000,000
    rows += _rows("2026-08-10", {(MARKET_KR, "005930"): 75000.0,
                                 (MARKET_KR, "000660"): 1100000.0})
    rows += _rows("2026-08-10", {(MARKET_KR, "005380"): 210000.0},
                  items=[holding(MARKET_KR, "005380", 5, 200000, "현대차")])
    # 8/12 — 현대차는 매도돼 기록 없음. 합계 3,200,000
    rows += _rows("2026-08-12", {(MARKET_KR, "005930"): 80000.0,
                                 (MARKET_KR, "000660"): 1200000.0})
    rows = rdb.sort_holding_snapshots(rows)

    history = rdb.build_holding_history(rows, "2026-08-01", "2026-08-31")

    # ---- ① 비중(%) 은 '그날 평가금액 ÷ 그날 합계' -----------------------------
    by_ticker = {r["ticker"]: r for r in history["rows"]}
    check(approx(by_ticker["000660"]["weight_pct"], 2400000 / 3200000 * 100),
          "비중 = 그날 평가금액 ÷ 그날 평가금액 합계 (2,400,000 / 3,200,000 = 75%)")
    check(approx(by_ticker["005930"]["weight_pct"], 800000 / 3200000 * 100),
          "나머지 종목도 같은 분모로 계산 (800,000 / 3,200,000 = 25%)")
    check(approx(sum(r["weight_pct"] for r in history["rows"]), 100.0),
          "🔴 비중 합 = 100% (분모가 그날 합계 스냅샷과 같은 값이라 어긋날 수 없음)")
    check(approx(history["totals"]["market_value"], 3200000.0),
          "비중을 붙여도 기존 합계 숫자는 그대로(파생값만 추가)")

    # ---- ② 기간 첫 기록일 대비 비중 변화 --------------------------------------
    weights = rdb.build_weight_comparison(history)
    check(weights["first_date"] == date(2026, 8, 10)
          and weights["base_date"] == date(2026, 8, 12) and weights["comparable"],
          "비교한 두 날짜 = 이 기간의 첫 기록일 → 마지막 기록일")
    check(approx(weights["first_total"], 4000000.0) and approx(weights["base_total"], 3200000.0),
          "각 날의 분모는 그날 '가격을 아는 종목'의 평가금액 합")
    wby = {r["ticker"]: r for r in weights["rows"]}
    check(approx(wby["000660"]["first_pct"], 55.0) and approx(wby["000660"]["base_pct"], 75.0)
          and approx(wby["000660"]["change_pp"], 20.0),
          "비중 변화 = 이번 비중 − 지난 비중 (55.00% → 75.00% = +20.00%p)")
    check(approx(wby["005930"]["first_pct"], 18.75) and approx(wby["005930"]["change_pp"], 6.25),
          "다른 종목도 같은 방식(18.75% → 25.00% = +6.25%p)")
    check(approx(wby["005380"]["first_pct"], 26.25)
          and wby["005380"]["base_pct"] == 0.0
          and wby["005380"]["base_state"] == rdb.WEIGHT_ABSENT
          and approx(wby["005380"]["change_pp"], -26.25),
          "🔴 기간 중 매도된 종목을 숨기지 않고 26.25% → 0.00%(-26.25%p)로 정직하게 표시")
    check([r["ticker"] for r in weights["rows"]] == ["000660", "005930", "005380"],
          "기준일 비중이 큰 종목부터 정렬(없어진 종목은 0% 라 맨 뒤)")

    # 새로 산 종목은 반대 방향으로 — 0.00% → X%
    fresh = rdb.build_holding_history(rdb.sort_holding_snapshots(
        _rows("2026-08-10", {(MARKET_KR, "005930"): 75000.0},
              items=[holdings_kr[0]])
        + _rows("2026-08-12", {(MARKET_KR, "005930"): 80000.0,
                               (MARKET_KR, "000660"): 1200000.0})))
    fresh_w = {r["ticker"]: r for r in rdb.build_weight_comparison(fresh)["rows"]}
    check(fresh_w["000660"]["first_pct"] == 0.0
          and approx(fresh_w["000660"]["base_pct"], 75.0)
          and approx(fresh_w["000660"]["change_pp"], 75.0),
          "기간 중 새로 산 종목은 0.00% → 75.00%(+75.00%p)로 드러남")

    # ---- ③ 가격을 몰랐던 종목 — 0% 가 아니라 '모름' ---------------------------
    unpriced = rdb.build_holding_history(rdb.sort_holding_snapshots(
        _rows("2026-08-10", {(MARKET_KR, "005930"): 75000.0,
                             (MARKET_KR, "000660"): 1100000.0})
        + _rows("2026-08-12", {(MARKET_KR, "005930"): 80000.0})))
    u_rows = {r["ticker"]: r for r in unpriced["rows"]}
    check(u_rows["000660"]["weight_pct"] is None,
          "🔴 그날 가격을 몰랐던 종목의 비중은 0% 가 아니라 None(화면 '모름')")
    check(approx(u_rows["005930"]["weight_pct"], 100.0),
          "분모에서 뺀 결과 — 가격을 아는 종목만으로 100%(없는 값을 0으로 메우지 않음)")
    u_weights = rdb.build_weight_comparison(unpriced)
    u_by = {r["ticker"]: r for r in u_weights["rows"]}
    check(u_by["000660"]["base_pct"] is None
          and u_by["000660"]["base_state"] == rdb.WEIGHT_UNPRICED
          and u_by["000660"]["change_pp"] is None,
          "한쪽이 '모름'이면 변화량도 만들어내지 않음(0%p 로 적으면 거짓말)")
    check(u_weights["unpriced_base"] == ["000660"] and u_weights["unpriced_first"] == [],
          "어느 날 어느 종목이 비중 계산에서 빠졌는지 그대로 돌려줌(화면이 밝힐 수 있게)")

    # ---- ④ 비교할 날이 하루뿐이면 표를 만들지 않음 ----------------------------
    one_day = rdb.build_holding_history(rdb.sort_holding_snapshots(
        _rows("2026-08-12", {(MARKET_KR, "005930"): 80000.0,
                             (MARKET_KR, "000660"): 1200000.0})))
    check(rdb.build_weight_comparison(one_day)["comparable"] is False,
          "기록이 하루뿐이면 비교 불가(0%p 를 늘어놓지 않음)")
    check(rdb.build_weight_comparison(rdb.build_holding_history([]))["rows"] == [],
          "기록이 없으면 빈 결과")
    check(rdb.build_weight_comparison(None)["rows"] == [], "history 가 없어도 죽지 않음")

    # ---- ⑤ 화면 문구 ---------------------------------------------------------
    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.report_view")
        real_st = module.st
        recorder = _HoldingViewRecorder()
        module.st = recorder
        try:
            check(module._md_weight(75.0) == "75.00%", "비중 표기(소수 2자리)")
            check(module._md_weight(None) == "모름",
                  "🔴 비중을 모르면 '0%' 가 아니라 '모름'")
            check(module._colored_pp(20.0) == ":red[+20.00%p]"
                  and module._colored_pp(-26.25) == ":blue[-26.25%p]",
                  "비중 변화는 %p 단위 + 국내 증시 색 관례(늘면 빨강/줄면 파랑)")
            check(module._colored_pp(None) == "—", "변화량이 없으면 —(0으로 속이지 않음)")

            summary = rdb.sort_snapshots([
                snap(date(2026, 8, 12), 3200000.0, 2700000.0, holdings_count=2, priced_count=2)])
            module._render_holding_history(MARKET_KR, rows, summary,
                                           date(2026, 8, 1), date(2026, 8, 31), "KRW")
            table = next(t for t in recorder.markdown_calls if t.startswith("| 종목 |"))
            check("| 종목 | 비중 |" in table, "종목별 상세 표 두 번째 칸이 비중(%)")
            check("75.00%" in table and "25.00%" in table, "표에 실제 비중이 찍힘")
            check("**100.00%**" in table, "합계 줄의 비중은 100%")
            check("원가합" in table,
                  "합계 줄 '평균매입가' 칸이 원가 합계임을 칸 안에서 밝힘(설명 캡션 대신)")

            change_table = [t for t in recorder.markdown_calls if t.startswith("| 종목 |")][1]
            check("2026-08-10" in change_table and "2026-08-12" in change_table,
                  "비중 변화 표 머리글에 비교한 두 날짜를 그대로 표기")
            check(":red[+20.00%p]" in change_table, "늘어난 종목은 +%p (빨강)")
            check(":blue[-26.25%p]" in change_table and "현대차 (005380)" in change_table,
                  "🔴 매도돼 사라진 종목도 숨기지 않고 -26.25%p 로 표시")
            check(any("비중 변화" in t for t in recorder.caption_calls),
                  "비중 변화 표에 제목 한 줄")

            # 하루치뿐이면 비중 변화 표 자체가 없음
            recorder.reset()
            module._render_holding_history(
                MARKET_KR, [r for r in rows if r["snapshot_date"] == date(2026, 8, 12)],
                summary, date(2026, 8, 1), date(2026, 8, 31), "KRW")
            check(len([t for t in recorder.markdown_calls if t.startswith("| 종목 |")]) == 1,
                  "비교할 날이 하루뿐이면 비중 변화 표를 그리지 않음(화면을 늘리지 않음)")
        finally:
            module.st = real_st
    except Exception as exc:  # noqa: BLE001
        check(False, "views.report_view 비중 표시 검증", f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.report_view", None)
            sys.modules.pop("views.scorecard_view", None)


def test_holding_schema_and_wiring():
    print("\n[10-1] 종목별 스냅샷 — SQL 스키마 · 화면 배선")
    sql = (REPO_ROOT / "sql" / "report_schema.sql").read_text(encoding="utf-8")
    sql_code = squeeze(sql_code_only(sql))

    check("create table if not exists public.portfolio_holding_snapshots" in sql,
          "종목별 테이블 생성문(여러 번 실행해도 안전)")
    check("drop table" not in sql_code.lower(),
          "실행되는 SQL 에 여전히 DROP TABLE 없음(기존 데이터 무손상)")
    check("unique (user_id, market, ticker, snapshot_date)" in squeeze(sql),
          "사용자×시장×종목×거래일 유니크 제약(하루 종목당 1행)")
    check("alter table public.portfolio_holding_snapshots enable row level security" in sql,
          "종목별 테이블도 RLS 켜기")
    check("create policy holding_snapshots_select_own" in sql
          and "for select to authenticated" in sql,
          "본인 행 select 정책")
    for forbidden in ("for insert to authenticated", "for update to authenticated",
                      "for delete to authenticated"):
        check(forbidden not in sql,
              f"사용자에게 {forbidden.split()[1]} 정책을 주지 않음(합계 표와 같은 원칙)")
    check("revoke all on public.portfolio_holding_snapshots from anon" in sql,
          "anon 권한 회수")
    check("grant select on public.portfolio_holding_snapshots to authenticated" in sql,
          "로그인 사용자에게는 select 만")
    check("grant select, insert, update on public.portfolio_holding_snapshots to service_role"
          in sql, "배치(service_role)에도 delete 는 주지 않음")
    # CREATE TABLE 블록만 잘라서 확인합니다(파일 다른 곳의 같은 문자열에 속지 않게).
    create_block = sql_code[
        sql_code.index("create table if not exists public.portfolio_holding_snapshots"):
        sql_code.index("create index if not exists holding_snapshots_user_market_date_idx")]
    check("priced boolean not null" in create_block, "가격을 알았는지 여부 컬럼")
    check("current_price is null or current_price > 0" in create_block,
          "가격을 모르면 NULL — 0 으로 메우지 못하게 DB 에서도 강제(§0-1)")
    check("(priced and current_price is not null and market_value is not null)" in create_block
          and "(not priced and current_price is null and market_value is null)" in create_block,
          "'가격 모름'의 표현이 한 가지로 못 박힘(priced 와 값의 유무가 어긋난 행은 못 들어옴)")
    check("(market = 'KR' and currency = 'KRW')" in create_block,
          "종목별 표에도 원/달러 혼용 차단 제약")
    check("create index if not exists holding_snapshots_user_market_date_idx" in sql,
          "주 조회 패턴(user_id, market, snapshot_date) 인덱스")
    check("stock_name text" in create_block, "그날 기준 종목명 컬럼")
    check("price_as_of_kst text" in create_block,
          "종목별 표에도 가격 수집 시각 컬럼(이 표만 봐도 자기완결적으로 읽히게)")
    check("created_at timestamptz not null default now()" in create_block,
          "created_at 컬럼")
    check("quantity numeric(20, 6) not null" in create_block
          and "avg_purchase_price numeric(20, 6) not null" in create_block
          and "cost numeric(20, 6) not null" in create_block,
          "숫자 컬럼 타입·정밀도가 holdings / 합계 표와 동일(numeric(20,6))")
    check(sql.count("sum(market_value) filter (where priced)") == 1,
          "설치 후 '합계 = 종목별 합' 대조 쿼리를 파일에 남김(오너가 눈으로 확인 가능)")
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", sql), "실제 Supabase URL 없음")

    # 기존 합계 테이블 정의가 그대로인지(이번 확장은 순수 추가)
    check("create table if not exists public.portfolio_daily_snapshots" in sql
          and "constraint snapshots_user_market_date_unique unique (user_id, market, snapshot_date)"
          in sql,
          "🔴 기존 합계 테이블 정의·제약은 한 글자도 바뀌지 않음")

    db_src = (REPO_ROOT / "utils" / "report_db.py").read_text(encoding="utf-8")
    view_src = (REPO_ROOT / "views" / "report_view.py").read_text(encoding="utf-8")
    view_code = python_code_only(view_src)
    check("HOLDING_SNAPSHOTS_TABLE" in db_src and "portfolio_holding_snapshots" in db_src,
          "데이터 계층에 종목별 테이블 상수")
    check("create_service_client" not in view_code and "SERVICE_ROLE" not in view_code,
          "🔴 화면 코드에는 여전히 service_role 경로가 없음(가장 중요한 격리)")
    check("_render_holding_history" in view_src and "_render_snapshot_table" in view_src,
          "종목별 상세는 기존 '스냅샷 원본 보기'와 **별도 섹션**")
    check("compare_holding_total" in view_code,
          "화면이 매번 합계와 대조(어긋나면 드러남)")
    check(not re.search(r"open\([^)]*['\"]w", db_src + view_src),
          "새 코드도 어떤 파일에도 쓰지 않음(읽기 전용)")
    check("delete(" not in python_code_only(db_src),
          "데이터 계층에 delete 경로가 없음(과거 기록을 지우는 코드 없음)")

# =============================================================================
# 10. SQL 스키마 · 워크플로우 · 화면 · 범위 확인
# =============================================================================
def test_sql_schema():
    print("\n[10] sql/report_schema.sql")
    path = REPO_ROOT / "sql" / "report_schema.sql"
    check(path.exists(), "sql/report_schema.sql 존재")
    sql = path.read_text(encoding="utf-8")
    sql_code = squeeze(sql_code_only(sql))

    check("create table if not exists public.portfolio_daily_snapshots" in sql,
          "스냅샷 테이블 생성문(여러 번 실행해도 안전)")
    check("drop table" not in sql_code.lower(),
          "실행되는 SQL 에 DROP TABLE 없음(기존 데이터를 지우지 않음)")
    check("unique (user_id, market, snapshot_date)" in sql,
          "사용자·시장·날짜 유니크 제약(하루 1행)")
    check("enable row level security" in sql, "RLS 켜기")
    check("create policy snapshots_select_own" in sql and "for select to authenticated" in sql,
          "본인 행 select 정책")
    check("auth.uid() = user_id" in sql, "정책 조건이 auth.uid() 기준")
    for forbidden in ("for insert to authenticated", "for update to authenticated",
                      "for delete to authenticated"):
        check(forbidden not in sql,
              f"사용자에게 {forbidden.split()[1]} 정책을 주지 않음(과거 기록은 사용자가 못 고침)")
    check("revoke all on public.portfolio_daily_snapshots from anon" in sql,
          "anon 권한 회수")
    check("grant select on public.portfolio_daily_snapshots to authenticated" in sql,
          "로그인 사용자에게는 select 만 부여")
    check("grant select, insert, update on public.portfolio_daily_snapshots to service_role" in sql,
          "배치(service_role)에는 delete 를 주지 않음")
    check("priced_count integer not null check (priced_count > 0)" in sql_code,
          "가격을 하나도 모르면 행 자체가 만들어지지 않도록 DB에서도 강제")
    check("priced_count + unpriced_count = holdings_count" in sql,
          "개수 정합성 제약")
    check("benchmark_value is null or benchmark_value > 0" in sql,
          "벤치마크는 NULL 허용 + 0/음수 금지(실패를 0으로 메우지 않음)")
    # 🕐 2026-08-13 — 가격 수집 시각 컬럼
    check("price_as_of_kst text" in squeeze(sql_code),
          "가격 수집 시각 컬럼(text, nullable — not null 이 아님)")
    check("add column if not exists price_as_of_kst text" in squeeze(sql_code),
          "이미 만들어 둔 테이블용 alter 문이 스크립트에 포함(create table if not exists 만으로는 "
          "기존 테이블에 컬럼이 생기지 않음)")
    check(re.search(r"comment on column public\.portfolio_daily_snapshots\.price_as_of_kst",
                    sql) is not None,
          "컬럼의 의미(어느 메타데이터에서 왔는지·KST·분 단위)를 DB 코멘트로 남김")
    check("price_as_of_kst timestamptz" not in squeeze(sql_code),
          "timestamptz 가 아님(원본이 분 단위라 없는 초·타임존을 만들지 않기 위해)")
    check("(market = 'KR' and currency = 'KRW')" in sql,
          "원/달러 혼용 차단 제약(holdings 와 동일 패턴)")
    check("service_role" in sql and "Streamlit" in sql,
          "왜 이 테이블만 service_role 을 쓰는지, 앱에 넣으면 안 되는 이유가 문서화됨")
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", sql), "실제 Supabase URL 없음")


def test_workflow():
    print("\n[11] .github/workflows/scrape_report_snapshots.yml")
    path = REPO_ROOT / ".github" / "workflows" / "scrape_report_snapshots.yml"
    check(path.exists(), "워크플로우 파일 존재")
    yml = path.read_text(encoding="utf-8")

    check("cron: '20 23 * * 1-5'" in yml, "평일 23:20 UTC 실행(코스피·미국 수집이 끝난 뒤)")
    check("python collector_us_indices.py collect" in yml, "미국 벤치마크 수집 단계")
    check("python -m utils.report_db snapshot" in yml, "스냅샷 적재 단계")
    check("--dry-run" in yml, "수동 실행 시 저장 없이 점검할 수 있는 경로")
    check("${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}" in yml
          and "${{ secrets.SUPABASE_URL }}" in yml,
          "필요한 Secrets 를 환경변수로만 전달")
    check("continue-on-error: true" in yml,
          "벤치마크 수집이 실패해도 스냅샷 적재는 계속(§0-1 — 값은 NULL 로)")
    check("git add data/us_index_history.json" in yml, "커밋 대상은 공개 벤치마크 파일 하나뿐")
    check("git add -A data/" not in yml and "git add data/ " not in yml,
          "다른 데이터 파일을 통째로 커밋하지 않음(다른 워크플로우 산출물 침범 방지)")
    # ⚠️ 2026-08-12 #96: 파일이 없을 때 `git add <파일명>` 이 exit 128 로 잡을 통째로
    #    죽였습니다. 수집기가 "둘 다 실패하면 파일을 건드리지 않는" 정상 동작을 갖고 있어서
    #    파일 없음은 예상 가능한 상태입니다 — 있으면만 add 해야 합니다.
    check("if [ -f data/us_index_history.json ]; then" in yml,
          "파일이 없으면 add 를 건너뜀(없다고 잡 전체가 죽지 않음)")
    check(yml.index("if [ -f data/us_index_history.json ]; then")
          < yml.index("git add data/us_index_history.json"),
          "존재 확인이 add 보다 먼저 옴")
    check("git commit -m \"Report Benchmark Update" in yml and "|| exit 0" in yml,
          "변경분이 없으면 커밋 실패를 조용히 넘김(기존 워크플로우 관례)")
    check("market_history.csv" not in yml, "매크로 파일을 건드리지 않음")
    check("timeout-minutes:" in yml and "concurrency:" in yml,
          "타임아웃·동시성 가드(기존 워크플로우 관례)")
    check(not re.search(r"eyJ[A-Za-z0-9_-]{20,}", yml), "워크플로우에 실제 키 값이 적혀 있지 않음")

    # 기존 두 워크플로우는 건드리지 않았는지
    for other in ("scrape.yml", "scrape_us.yml", "keep_awake.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / other).read_text(encoding="utf-8")
        check("report" not in text.lower(), f"{other} 에 리포트 관련 수정 없음")


def _install_streamlit_stub():
    """streamlit 미설치 환경에서도 views/report_view.py 를 import 할 수 있게 최소 스텁 주입."""
    try:
        import streamlit  # noqa: F401
        return False
    except ImportError:
        pass

    class _Secrets:
        def get(self, _name, default=None):
            return default

    class _Stub(types.ModuleType):
        secrets = _Secrets()

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None
            return _noop

    stub = _Stub("streamlit")
    stub.secrets = _Secrets()
    sys.modules["streamlit"] = stub
    return True


def test_view_and_scope():
    print("\n[12] 화면 배선 · 작업 범위")
    view_path = REPO_ROOT / "views" / "report_view.py"
    check(view_path.exists(), "views/report_view.py 존재")
    view_src = view_path.read_text(encoding="utf-8")

    check("NO_FX_CONVERSION_NOTICE" in view_src, "환율 변환 없음 고지 표시")
    check("REPORT_SIMPLE_RETURN_NOTICE" in view_src,
          "단순 비교 수익률이라는 한계 고지 표시(작업지시서 §5)")
    check("st.error" in view_src, "실패·데이터 부족을 화면까지 도달시킴(§0-1)")
    check("_render_shortage" in view_src and "데이터 부족" in view_src,
          "데이터 부족을 주 컨텐츠로 그리는 전용 렌더러가 있음(§3)")
    check("cache_resource" not in view_src.replace("@st.cache_resource 로 캐시하면", ""),
          "Supabase 클라이언트를 캐시하지 않음(로그인 세션 공유 사고 방지)")
    check("from views.scorecard_view import SESSION_CLIENT_KEY, SESSION_USER_KEY" in view_src,
          "'내 성적표'와 같은 로그인 세션을 재사용(세션 키를 새로 정의하지 않음)")
    check(not re.search(r"open\([^)]*['\"]w", view_src), "화면 코드가 파일을 쓰지 않음(읽기 전용)")
    view_code = python_code_only(view_src)
    check("create_service_client" not in view_code and "SERVICE_ROLE" not in view_code,
          "화면 코드에는 service_role 경로가 전혀 없음(가장 중요한 격리 — 오너 안내문에만 "
          "'앱에 넣지 마세요'라는 설명으로 등장)")
    check(":red[" in view_src and ":blue[" in view_src,
          "수익률 색상이 국내 증시 관례(오르면 빨강/내리면 파랑)로 '내 성적표'와 통일")
    check("_md_amount" in view_src, "마크다운 금액 표기는 $ 이스케이프 사용(#88 렌더링 버그 방지)")
    check("_render_price_stamp" in view_src and "PRICE_STAMP_FIELD" in view_src,
          "가격 수집 시각을 시장 블록마다 그리는 전용 렌더러가 있음(2026-08-13 오너 요청)")
    view_stamp_fn = view_src[view_src.index("def _render_price_stamp"):
                             view_src.index("def _render_not_ready")]
    check("date.today()" not in python_code_only(view_stamp_fn)
          and "datetime.now" not in python_code_only(view_stamp_fn),
          "시각 표시가 '지금'을 쓰지 않음 — 저장된 행의 값만 보여줌(오늘 시각으로 대체 금지)")

    db_src = (REPO_ROOT / "utils" / "report_db.py").read_text(encoding="utf-8")
    check(not re.search(r"open\([^)]*['\"]w", db_src),
          "데이터 모듈이 어떤 파일도 쓰지 않음(market_history.csv 포함)")
    db_code = python_code_only(db_src)
    check(not re.search(r"^\s*(import streamlit|from streamlit)", db_code, re.M)
          and "st.secrets" not in db_code,
          "배치 모듈은 streamlit 을 아예 import 하지 않고 st.secrets 도 읽지 않음"
          "(service_role 이 앱 설정에서 읽히는 경로 자체를 만들지 않기 위해 — 설명 주석에만 등장)")
    check("os.environ.get(name)" in db_src, "배치 키는 환경변수에서만 읽음")
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", db_src + view_src),
          "소스에 실제 Supabase URL 없음")
    check(not re.search(r"eyJ[A-Za-z0-9_-]{20,}", db_src + view_src),
          "소스에 실제 키(JWT) 값 없음")

    collector_src = (REPO_ROOT / "collector_us_indices.py").read_text(encoding="utf-8")
    check("_polite_sleep" in collector_src, "요청 사이 딜레이(§0-3-2)")
    check("USSourceBlockedError" in collector_src and "즉시 중단" in collector_src,
          "차단 시 재시도 반복 없이 중단(§0-3-2)")
    check("from collector_us_stocks import" in collector_src,
          "기존 수집기의 HTTP 헬퍼·devalue 디코더를 재사용(중복 구현 없음)")
    check("FRED" in collector_src and "S&P Dow Jones" in collector_src,
          "소스 조사 결과와 FRED 를 쓰지 않은 이유(재배포 제한)를 파일에 기록")
    check("market_history" not in collector_src, "미국 수집기가 매크로 파일을 건드리지 않음")

    # 기존 파일 무손상 — 리포트 모듈을 만들면서 다른 모듈 파일은 한 줄도 고치지 않았습니다.
    #  ⚠️ 단순히 "report" 라는 낱말을 찾으면 안 됩니다(collector_kospi200.py 에는 예전부터
    #     네이버 "WiseReport" 스크래핑 주석이 있습니다). 이번 모듈 고유의 이름으로 확인합니다.
    #
    #  ⚠️ 2026-08-13 수정 — 이 목록에서 `visiblehand.py` 를 뺐습니다. 리포트 모듈을 처음 만든
    #     날(2026-08-12 오전)에는 작업지시서 §7 지시대로 `visiblehand.py` 를 건드리지 않아서
    #     이 검사가 맞았지만, 같은 날 오후 오너 요청(TASK_HISTORY #102·#105)으로 사이드바가
    #     2단 트리로 개편되면서 리포트 화면이 "내 성적표"의 하위 메뉴로 **정식 배선**됐습니다.
    #     그때 이 검사를 같이 고치지 않아 그 뒤로 계속 실패하고 있던 항목입니다(2026-08-13 공개 전환
    #     점검에서 발견). 배선 자체는 바로 아래에서 따로 검증하므로, 이 목록에는 "리포트가
    #     침범하면 안 되는 다른 모듈들"만 남깁니다.
    report_markers = ("report_db", "report_view", "portfolio_daily_snapshots",
                      "collector_us_indices", "us_index_history")
    for untouched in ("views/scorecard_view.py", "utils/scorecard_db.py",
                      "collector_us_stocks.py", "collector_kospi200.py",
                      "utils/scoring.py", "views/pegy_view.py", "views/us_stocks_view.py",
                      "utils/constants_us.py", "scrape_daily.py", "views/macro_view.py"):
        src = (REPO_ROOT / untouched).read_text(encoding="utf-8").lower()
        check(not any(marker in src for marker in report_markers),
              f"{untouched} 에 리포트 모듈 관련 수정 없음")

    # 사이드바 배선 (TASK_HISTORY #102·#105 + 2026-08-13 레이아웃 정리) --------------
    app_src = (REPO_ROOT / "visiblehand.py").read_text(encoding="utf-8")
    check("from views.report_view import is_report_visible, render_report_page" in app_src,
          "리포트 화면이 사이드바에 배선됨(import 가드 안)")
    check("except Exception as _report_import_exc" in app_src,
          "리포트 모듈 로드 실패해도 기존 화면이 죽지 않도록 import 가드")
    check("report_available = render_report_page is not None and is_report_visible(admin_mode_hint)"
          in app_src,
          "리포트 하위 메뉴도 대분류 라디오와 같은 admin_mode_hint 를 사용(#105 패턴 통일)")
    # 레이아웃 고정: 하위 메뉴 라디오는 반드시 관리자 메뉴(render_admin_sidebar) **위**에서
    # 그려져야 합니다. 아래로 내려가면 대분류를 바꿀 때 관리자 메뉴 위치가 흔들립니다.
    check(app_src.index('key="scorecard_subpage"') < app_src.index("admin_mode = render_admin_sidebar()"),
          "내 성적표 하위 메뉴 라디오가 관리자 메뉴보다 위에서 그려짐(관리자 메뉴 세로 위치 고정)")
    check(app_src.count("render_category_header(") == 3,
          "두 대분류가 같은 헤더 함수를 써서 같은 높이로 그려짐(정의 1 + 호출 2)")
    # ⚠️ 반드시 주석을 걷어낸 '실제 코드'로 확인합니다 — 왜 sticky/fixed 를 쓰지 않았는지
    #    설명하는 주석 자체에 그 낱말이 들어 있어서, 원문으로 검사하면 항상 실패합니다.
    app_code = python_code_only(app_src)
    check("position: sticky" not in app_code and "position: fixed" not in app_code,
          "레이아웃 고정에 Streamlit 내부 DOM 의존 CSS(sticky/fixed)를 쓰지 않음")

    check((REPO_ROOT / "REPORT_WORK_ORDER.md").exists(), "작업지시서 원본 보존")

    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.report_view")
        check(True, "views.report_view import 성공 (supabase 패키지 없이도)")
        saved = os.environ.pop("REPORT_ENABLED", None)
        try:
            check(module.is_report_enabled() is False, "REPORT_ENABLED 기본값 = 꺼짐")
            check(module.is_report_visible(False) is False, "일반 방문자에게는 비노출(스테이징)")
            check(module.is_report_visible(True) is True, "관리자 모드에서는 미리보기 가능")
            os.environ["REPORT_ENABLED"] = "1"
            importlib.reload(module)
            check(module.is_report_enabled() is True, "플래그를 켜면 활성화됨")
            check(module._colored_pct(1.5) == ":red[+1.50%]", "상승은 빨강")
            check(module._colored_pct(-1.5) == ":blue[-1.50%]", "하락은 파랑")
            check(module._colored_pct(0) == "+0.00%", "보합은 색 없음")
            check(module._colored_pct(None) == "—", "값이 없으면 —(0%로 속이지 않음)")
            check(module._md_amount(1234.5, "USD") == "\\$1,234.50",
                  "$ 이스케이프(마크다운 수식 오인 방지)")
        finally:
            if saved is not None:
                os.environ["REPORT_ENABLED"] = saved
            else:
                os.environ.pop("REPORT_ENABLED", None)
            importlib.reload(module)
    except Exception as exc:  # noqa: BLE001
        check(False, "views.report_view import 성공 (supabase 패키지 없이도)",
              f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.report_view", None)
            sys.modules.pop("views.scorecard_view", None)


def main():
    print("=" * 74)
    print("📈 리포트 모듈 오프라인 검증 (Supabase 미연결 · 네트워크 불필요)")
    print("=" * 74)
    test_period_bounds()
    test_build_snapshot_rows()
    test_period_report_status()
    test_period_report_composition()
    test_benchmark_returns()
    test_benchmark_files()
    test_us_index_collector_parsing()
    test_us_index_collector_run()
    test_supabase_wiring()
    test_batch_end_to_end()
    test_price_stamp_wiring()
    test_holding_snapshots()
    test_period_buttons()
    test_holding_weights()
    test_holding_schema_and_wiring()
    test_sql_schema()
    test_workflow()
    test_view_and_scope()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
