"""
tests/test_collector_indicator_kr.py
collector_indicator_kr.py 의 네트워크-불필요 부분(레코드 조립·교차검증·파일 입출력) 오프라인 테스트.
FDR 실제 호출(fetch_and_calculate)은 네트워크가 필요해 여기서 검증하지 않습니다 —
0단계 실측(probe_indicator_universe_timing.py, GitHub Actions에서 이미 실측 완료)이
그 역할을 담당합니다.

실행: python -m pytest tests/test_collector_indicator_kr.py -v
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collector_indicator_kr
from utils import stock_history
from collector_indicator_kr import (
    build_history_row,
    cross_check_last_close,
    load_price_entries_and_names,
    load_ticker_types,
    load_universe,
    save_universe,
    get_price_list_generated_date,
)


AVAILABLE_RSI = {"available": True, "bars_used": 60, "warmup_insufficient": False, "rsi": 75.0, "signal": "overbought", "reason": None}
AVAILABLE_MACD = {"available": True, "bars_used": 60, "warmup_insufficient": True, "macd": 120.5, "signal_line": 100.2, "histogram": 20.3, "cross": "golden", "reason": None}
AVAILABLE_BB = {"available": True, "bars_used": 60, "warmup_insufficient": False, "upper": 11000.0, "lower": 9000.0, "mid": 10000.0, "percent_b": 0.9, "position": "inside", "reason": None}
VERDICT_OK = {"score": 2, "label": "매수 우위", "contributing": [], "skipped": []}

UNAVAILABLE_RSI = {"available": False, "bars_used": 5, "warmup_insufficient": None, "rsi": None, "signal": None, "reason": "산출 불가 — 종가 5봉 보유, 최소 15봉 필요"}


# ---------------------------------------------------------------------------
# build_history_row
# ---------------------------------------------------------------------------

def test_build_history_row_all_available_no_reasons():
    row = build_history_row("005930", "삼성전자", "2026-08-25", AVAILABLE_RSI, AVAILABLE_MACD, AVAILABLE_BB, VERDICT_OK)
    assert row["code"] == "005930"
    assert row["name"] == "삼성전자"
    assert row["date"] == "2026-08-25"
    assert row["rsi"] == 75.0
    assert row["macd_cross"] == "golden"
    assert row["bb_position"] == "inside"
    assert row["verdict_score"] == 2
    assert row["verdict_label"] == "매수 우위"
    assert row["unavailable_reasons"] is None
    # 셋 중 하나(MACD)라도 warmup_insufficient=True면 행 전체 플래그가 True
    assert row["warmup_insufficient"] is True
    assert row["bars_used"] == 60


def test_build_history_row_partial_unavailable_records_reason():
    row = build_history_row("003000", "테스트종목", "2026-08-25", UNAVAILABLE_RSI, AVAILABLE_MACD, AVAILABLE_BB, VERDICT_OK)
    assert row["rsi"] is None
    assert "RSI" in row["unavailable_reasons"]
    assert "산출 불가" in row["unavailable_reasons"]
    # MACD는 available이므로 그 값은 그대로 살아있음(§0-1: 되는 지표까지 같이 죽이지 않음)
    assert row["macd"] == 120.5
    # bars_used는 첫 번째로 available한 지표(MACD)에서 가져옴
    assert row["bars_used"] == 60


def test_build_history_row_all_unavailable():
    unavailable_macd = {**UNAVAILABLE_RSI, "macd": None, "signal_line": None, "histogram": None, "cross": None}
    unavailable_bb = {**UNAVAILABLE_RSI, "upper": None, "lower": None, "mid": None, "percent_b": None, "position": None}
    verdict_none = {"score": None, "label": "산출 불가", "contributing": [], "skipped": []}
    row = build_history_row("999999", "신규상장", "2026-08-25", UNAVAILABLE_RSI, unavailable_macd, unavailable_bb, verdict_none)
    assert row["bars_used"] is None
    assert row["verdict_label"] == "산출 불가"
    assert row["unavailable_reasons"].count(";") == 2  # RSI/MACD/Bollinger 3개 사유가 세미콜론 2개로 이어짐


# ---------------------------------------------------------------------------
# cross_check_last_close
# ---------------------------------------------------------------------------

def test_cross_check_matches_within_threshold():
    result = cross_check_last_close("005930", 100000.0, {"005930": 100500.0})
    assert result is False  # 0.5% 차이 -> 일치로 판정


def test_cross_check_flags_large_mismatch():
    result = cross_check_last_close("005930", 100000.0, {"005930": 150000.0})
    assert result is True


def test_cross_check_returns_none_when_no_naver_price():
    result = cross_check_last_close("999999", 100000.0, {})
    assert result is None


def test_cross_check_returns_none_when_last_close_missing():
    result = cross_check_last_close("005930", None, {"005930": 100000.0})
    assert result is None


# ---------------------------------------------------------------------------
# 파일 입출력 — 없거나 깨진 파일에서 지어내지 않고 빈 값 반환
# ---------------------------------------------------------------------------

def test_load_price_entries_missing_file_returns_empty(tmp_path):
    entries, names = load_price_entries_and_names(str(tmp_path / "nope.json"))
    assert entries == []
    assert names == {}


def test_load_price_entries_valid_file(tmp_path):
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({"stocks": [{"code": "A1", "name": "가나다"}]}), encoding="utf-8")
    entries, names = load_price_entries_and_names(str(p))
    assert entries == [{"code": "A1", "name": "가나다"}]
    assert names == {"A1": "가나다"}


def test_load_ticker_types_missing_file_returns_empty(tmp_path):
    result = load_ticker_types(str(tmp_path / "nope.json"))
    assert result == {}


def test_load_ticker_types_valid_file(tmp_path):
    p = tmp_path / "tickers.json"
    p.write_text(json.dumps({"stocks": [{"code": "A1", "type": "STOCK"}, {"code": "E1", "type": "ETF"}]}), encoding="utf-8")
    result = load_ticker_types(str(p))
    assert result == {"A1": "STOCK", "E1": "ETF"}


def test_load_universe_missing_file_returns_empty_skeleton(tmp_path):
    universe = load_universe(str(tmp_path / "nope.json"))
    assert universe == {"last_rebalance_date": None, "members": {}}


def test_save_and_load_universe_roundtrip(tmp_path):
    p = tmp_path / "universe.json"
    original = {"last_rebalance_date": "2026-08-25", "members": {"A1": {"joined_date": "2026-08-25", "left_date": None, "is_visible": True}}}
    save_universe(original, str(p))
    loaded = load_universe(str(p))
    assert loaded == original


def test_load_universe_corrupt_file_returns_empty_skeleton(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    universe = load_universe(str(p))
    assert universe == {"last_rebalance_date": None, "members": {}}


# ---------------------------------------------------------------------------
# get_price_list_generated_date
# ---------------------------------------------------------------------------

def test_get_price_list_generated_date_missing_file_returns_none(tmp_path):
    assert get_price_list_generated_date(str(tmp_path / "nope.json")) is None


def test_get_price_list_generated_date_reads_metadata(tmp_path):
    p = tmp_path / "prices.json"
    p.write_text(json.dumps({"metadata": {"generated_at": "2026-08-25 17:34"}, "stocks": []}), encoding="utf-8")
    assert get_price_list_generated_date(str(p)) == "2026-08-25"


def test_get_price_list_generated_date_corrupt_file_returns_none(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("not json", encoding="utf-8")
    assert get_price_list_generated_date(str(p)) is None


# ---------------------------------------------------------------------------
# run() 전체 흐름 — FDR 호출만 가짜로 바꾸고 나머지는 실제 코드 경로를 그대로 태웁니다.
#
# ⚠️ 2026-08-25 실제 GitHub Actions 첫 실행에서 이 경로(이력 기록 직후 결과 출력)가
#    KeyError('reason')로 죽었습니다 — append_daily_history()가 돌려주는 dict에 없는
#    키를 읽으려 한 실수였는데, 오프라인 테스트가 build_history_row()까지만 확인하고
#    run() 전체를 통째로 실행해보지는 않아서 못 잡았습니다. 이 테스트는 그 구멍을
#    메우는 회귀테스트입니다 — 같은 종류의 "함수가 실제로 돌려주는 값과 다른 키를
#    읽는" 실수를 다음엔 로컬에서 pytest만 돌려도 바로 잡히게 합니다.
# ---------------------------------------------------------------------------

def _fake_fetch_and_calculate(code, days=None):
    """FDR 네트워크 호출 없이, 종목코드마다 살짝 다른 값의 '산출 가능' 결과를 돌려줍니다."""
    rsi = {"available": True, "bars_used": 60, "warmup_insufficient": False, "rsi": 55.0, "signal": "neutral", "reason": None}
    macd = {"available": True, "bars_used": 60, "warmup_insufficient": False, "macd": 10.0, "signal_line": 8.0, "histogram": 2.0, "cross": None, "reason": None}
    bb = {"available": True, "bars_used": 60, "warmup_insufficient": False, "upper": 11000.0, "lower": 9000.0, "mid": 10000.0, "percent_b": 0.5, "position": "inside", "reason": None}
    verdict = {"score": 0, "label": "중립", "contributing": [], "skipped": []}
    return rsi, macd, bb, verdict, 10000.0


def test_run_end_to_end_with_mocked_fetch_writes_history_and_snapshot(tmp_path, monkeypatch):
    price_path = tmp_path / "kr_all_market_prices.json"
    ticker_path = tmp_path / "kr_ticker_master.json"
    universe_path = tmp_path / "indicator_universe_kr.json"
    latest_path = tmp_path / "indicator_kr_latest.json"
    history_path = tmp_path / "indicator_kr_history.csv"

    price_path.write_text(json.dumps({
        "metadata": {"generated_at": "2026-08-25 17:00"},
        "stocks": [
            {"code": "A1", "name": "가짜전자", "price": 10000.0},
            {"code": "A2", "name": "가짜하이닉스", "price": 20000.0},
        ],
    }), encoding="utf-8")
    ticker_path.write_text(json.dumps({
        "stocks": [{"code": "A1", "type": "STOCK"}, {"code": "A2", "type": "STOCK"}],
    }), encoding="utf-8")

    monkeypatch.setattr(collector_indicator_kr, "PRICE_LIST_PATH", str(price_path))
    monkeypatch.setattr(collector_indicator_kr, "TICKER_MASTER_PATH", str(ticker_path))
    monkeypatch.setattr(collector_indicator_kr, "UNIVERSE_PATH", str(universe_path))
    monkeypatch.setattr(collector_indicator_kr, "LATEST_SNAPSHOT_PATH", str(latest_path))
    monkeypatch.setattr(collector_indicator_kr, "fetch_and_calculate", _fake_fetch_and_calculate)
    monkeypatch.setattr(stock_history, "stock_history_path", lambda filename: str(history_path))
    # today_str이 price_path의 generated_at(2026-08-25)과 어긋나 신선도 경고가 뜨지 않도록
    monkeypatch.setattr(collector_indicator_kr, "_now_kst",
                         lambda: __import__("datetime").datetime(2026, 8, 25, 17, 10))

    collector_indicator_kr.run(limit=2, days=400, delay=0)  # delay=0: 테스트가 느려지지 않게

    assert history_path.exists()
    with open(history_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert {r["code"] for r in rows} == {"A1", "A2"}
    assert rows[0]["date"] == "2026-08-25"
    assert rows[0]["rsi"] == "55.0"

    assert latest_path.exists()
    snapshot = json.loads(latest_path.read_text(encoding="utf-8"))
    assert snapshot["success_count"] == 2
    assert snapshot["failed_count"] == 0
    assert len(snapshot["stocks"]) == 2

    assert universe_path.exists()
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    assert set(universe["members"].keys()) == {"A1", "A2"}


def test_run_continues_when_one_stock_fetch_fails(tmp_path, monkeypatch):
    """§5-3: 종목 하나 실패해도 나머지는 정상 기록되어야 합니다."""
    price_path = tmp_path / "kr_all_market_prices.json"
    ticker_path = tmp_path / "kr_ticker_master.json"
    universe_path = tmp_path / "indicator_universe_kr.json"
    latest_path = tmp_path / "indicator_kr_latest.json"
    history_path = tmp_path / "indicator_kr_history.csv"

    price_path.write_text(json.dumps({
        "metadata": {"generated_at": "2026-08-25 17:00"},
        "stocks": [{"code": "GOOD", "name": "정상"}, {"code": "BAD", "name": "실패"}],
    }), encoding="utf-8")
    ticker_path.write_text(json.dumps({
        "stocks": [{"code": "GOOD", "type": "STOCK"}, {"code": "BAD", "type": "STOCK"}],
    }), encoding="utf-8")

    def flaky_fetch(code, days=None):
        if code == "BAD":
            raise RuntimeError("가짜 네트워크 실패")
        return _fake_fetch_and_calculate(code, days)

    monkeypatch.setattr(collector_indicator_kr, "PRICE_LIST_PATH", str(price_path))
    monkeypatch.setattr(collector_indicator_kr, "TICKER_MASTER_PATH", str(ticker_path))
    monkeypatch.setattr(collector_indicator_kr, "UNIVERSE_PATH", str(universe_path))
    monkeypatch.setattr(collector_indicator_kr, "LATEST_SNAPSHOT_PATH", str(latest_path))
    monkeypatch.setattr(collector_indicator_kr, "fetch_and_calculate", flaky_fetch)
    monkeypatch.setattr(stock_history, "stock_history_path", lambda filename: str(history_path))
    monkeypatch.setattr(collector_indicator_kr, "_now_kst",
                         lambda: __import__("datetime").datetime(2026, 8, 25, 17, 10))

    collector_indicator_kr.run(limit=2, days=400, delay=0)

    snapshot = json.loads(latest_path.read_text(encoding="utf-8"))
    assert snapshot["success_count"] == 1
    assert snapshot["failed_count"] == 1
    assert {s["code"] for s in snapshot["stocks"]} == {"GOOD"}


# ---------------------------------------------------------------------------
# 2026-09-04: 무인 자동화 사전 점검(--skip-if-not-ready) — "오늘 이미 SUCCESS 면 건너뛰기"
#   배경: GitHub 자체 cron 지연 + Cloudflare Worker dispatch 가 같은 날 둘 다 발동해
#   2026-09-02·09-03 이틀 연속 하루 두 번 수집됨(스냅샷 generated_at 17:1x / 21:3x KST).
#   판정 규칙은 collector_kospi200 / collector_us_stocks 와 같은 방향 — "모르면 수집".
# ---------------------------------------------------------------------------

_GUARD_NOW = __import__("datetime").datetime(2026, 9, 4, 17, 12)


def _write_indicator_snapshot(tmp_path, status, date, drop_status=False):
    d = {"generated_at": f"{date} 17:10", "date": date, "status": status,
         "success_count": 500, "failed_count": 0, "stocks": []}
    if drop_status:
        d.pop("status")
    p = tmp_path / "indicator_kr_latest.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def test_readiness_skips_when_today_already_success(tmp_path):
    """(a) 오늘(KST) 자 스냅샷이 SUCCESS → 건너뜀."""
    snap = _write_indicator_snapshot(tmp_path, "SUCCESS", "2026-09-04")
    r = collector_indicator_kr.evaluate_collection_readiness(snap, now_kst=_GUARD_NOW)
    assert r["should_collect"] is False
    assert r["snapshot_date"] == "2026-09-04"


def test_readiness_collects_when_not_yet_collected_today(tmp_path):
    """(b) 어제 SUCCESS 뿐이거나 파일이 없으면 → 수집."""
    snap = _write_indicator_snapshot(tmp_path, "SUCCESS", "2026-09-03")
    assert collector_indicator_kr.evaluate_collection_readiness(snap, now_kst=_GUARD_NOW)["should_collect"] is True
    assert collector_indicator_kr.evaluate_collection_readiness(
        str(tmp_path / "없는파일.json"), now_kst=_GUARD_NOW)["should_collect"] is True


def test_readiness_retries_when_today_degraded_or_legacy(tmp_path):
    """(c) 오늘 DEGRADED(실패 있음)면 재시도. status 필드가 없는 옛 형식·깨진 파일도 SUCCESS 로 승격하지 않음."""
    snap = _write_indicator_snapshot(tmp_path, "DEGRADED", "2026-09-04")
    r = collector_indicator_kr.evaluate_collection_readiness(snap, now_kst=_GUARD_NOW)
    assert r["should_collect"] is True and r["snapshot_status"] == "DEGRADED"
    snap = _write_indicator_snapshot(tmp_path, None, "2026-09-04", drop_status=True)
    assert collector_indicator_kr.evaluate_collection_readiness(snap, now_kst=_GUARD_NOW)["should_collect"] is True
    broken = tmp_path / "indicator_kr_latest.json"
    broken.write_text("{깨진", encoding="utf-8")
    assert collector_indicator_kr.evaluate_collection_readiness(str(broken), now_kst=_GUARD_NOW)["should_collect"] is True


def test_main_skip_flag_gates_run(tmp_path, monkeypatch):
    """main(argv): 플래그 + 오늘 SUCCESS → run() 미호출 / 플래그 없음(force) → 호출 / 오늘 DEGRADED → 호출."""
    calls = []
    monkeypatch.setattr(collector_indicator_kr, "run", lambda **kw: calls.append(kw))
    monkeypatch.setattr(collector_indicator_kr, "_now_kst", lambda: _GUARD_NOW)
    wf_args = ["--limit", "500", "--days", "400", "--delay", "0.5"]

    monkeypatch.setattr(collector_indicator_kr, "LATEST_SNAPSHOT_PATH",
                        _write_indicator_snapshot(tmp_path, "SUCCESS", "2026-09-04"))
    assert collector_indicator_kr.main(wf_args + ["--skip-if-not-ready"]) is False
    assert calls == []
    assert collector_indicator_kr.main(wf_args) is True            # 탈출구: 플래그를 빼면 무조건 수집
    assert calls == [{"limit": 500, "days": 400, "delay": 0.5}]

    monkeypatch.setattr(collector_indicator_kr, "LATEST_SNAPSHOT_PATH",
                        _write_indicator_snapshot(tmp_path, "DEGRADED", "2026-09-04"))
    assert collector_indicator_kr.main(wf_args + ["--skip-if-not-ready"]) is True
    assert len(calls) == 2


def test_run_records_status_success_only_when_no_failures(tmp_path, monkeypatch):
    """run() 이 쓰는 status: 실패 0건 → SUCCESS, 1건이라도 실패 → DEGRADED (사전 점검이 읽는 값)."""
    price_path = tmp_path / "kr_all_market_prices.json"
    ticker_path = tmp_path / "kr_ticker_master.json"
    latest_path = tmp_path / "indicator_kr_latest.json"
    price_path.write_text(json.dumps({
        "metadata": {"generated_at": "2026-08-25 17:00"},
        "stocks": [{"code": "GOOD", "name": "정상"}, {"code": "BAD", "name": "실패"}],
    }), encoding="utf-8")
    ticker_path.write_text(json.dumps({
        "stocks": [{"code": "GOOD", "type": "STOCK"}, {"code": "BAD", "type": "STOCK"}],
    }), encoding="utf-8")
    monkeypatch.setattr(collector_indicator_kr, "PRICE_LIST_PATH", str(price_path))
    monkeypatch.setattr(collector_indicator_kr, "TICKER_MASTER_PATH", str(ticker_path))
    monkeypatch.setattr(collector_indicator_kr, "UNIVERSE_PATH", str(tmp_path / "indicator_universe_kr.json"))
    monkeypatch.setattr(collector_indicator_kr, "LATEST_SNAPSHOT_PATH", str(latest_path))
    monkeypatch.setattr(stock_history, "stock_history_path", lambda filename: str(tmp_path / "indicator_kr_history.csv"))
    monkeypatch.setattr(collector_indicator_kr, "_now_kst",
                         lambda: __import__("datetime").datetime(2026, 8, 25, 17, 10))

    monkeypatch.setattr(collector_indicator_kr, "fetch_and_calculate", _fake_fetch_and_calculate)
    collector_indicator_kr.run(limit=2, days=400, delay=0)
    assert json.loads(latest_path.read_text(encoding="utf-8"))["status"] == "SUCCESS"

    def flaky_fetch(code, days=None):
        if code == "BAD":
            raise RuntimeError("가짜 네트워크 실패")
        return _fake_fetch_and_calculate(code, days)
    monkeypatch.setattr(collector_indicator_kr, "fetch_and_calculate", flaky_fetch)
    collector_indicator_kr.run(limit=2, days=400, delay=0)
    assert json.loads(latest_path.read_text(encoding="utf-8"))["status"] == "DEGRADED"
