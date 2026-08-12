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
    ⑧ SQL 스키마 · 워크플로우 · 화면 배선 (기본 숨김, service_role 격리, 기존 파일 무손상)

⚠️ 저장소의 실제 데이터 파일(data/*.json, market_history.csv)은 **읽기만** 합니다.
   이 테스트는 어떤 저장소 파일도 수정하지 않습니다(쓰기는 tempfile 안에서만).

실행: python tests/test_report.py
"""

import io
import importlib
import json
import os
import re
import sys
import tempfile
import types
from datetime import date
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

    # 기존 파일 무손상 — 이번 작업에서 한 줄도 고치지 않았습니다.
    #  ⚠️ 단순히 "report" 라는 낱말을 찾으면 안 됩니다(collector_kospi200.py 에는 예전부터
    #     네이버 "WiseReport" 스크래핑 주석이 있습니다). 이번 모듈 고유의 이름으로 확인합니다.
    report_markers = ("report_db", "report_view", "portfolio_daily_snapshots",
                      "collector_us_indices", "us_index_history")
    for untouched in ("views/scorecard_view.py", "utils/scorecard_db.py",
                      "collector_us_stocks.py", "collector_kospi200.py", "visiblehand.py",
                      "utils/scoring.py", "views/pegy_view.py", "views/us_stocks_view.py",
                      "utils/constants_us.py", "scrape_daily.py", "views/macro_view.py"):
        src = (REPO_ROOT / untouched).read_text(encoding="utf-8").lower()
        check(not any(marker in src for marker in report_markers),
              f"{untouched} 에 리포트 모듈 관련 수정 없음")

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
