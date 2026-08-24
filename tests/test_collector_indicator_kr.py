"""
tests/test_collector_indicator_kr.py
collector_indicator_kr.py 의 네트워크-불필요 부분(레코드 조립·교차검증·파일 입출력) 오프라인 테스트.
FDR 실제 호출(fetch_and_calculate)은 네트워크가 필요해 여기서 검증하지 않습니다 —
0단계 실측(probe_indicator_universe_timing.py, GitHub Actions에서 이미 실측 완료)이
그 역할을 담당합니다.

실행: python -m pytest tests/test_collector_indicator_kr.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
