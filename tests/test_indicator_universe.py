"""
tests/test_indicator_universe.py
「여기서부터는 신앙입니다」 500종목 유니버스(리밸런싱·히스테리시스 버퍼) 오프라인 단위테스트.

실행: python -m pytest tests/test_indicator_universe.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicator_universe import (
    empty_universe,
    select_top_n_stock_codes,
    rebalance_if_due,
    prune_expired_members,
    get_tracked_codes,
    get_visible_codes,
    update_universe_for_today,
)


# ---------------------------------------------------------------------------
# select_top_n_stock_codes — ETF 제외, 순서 보존, 개수 제한
# ---------------------------------------------------------------------------

def test_select_top_n_filters_etf_and_preserves_order():
    price_entries = [
        {"code": "A1", "name": "삼성전자"},
        {"code": "E1", "name": "ETF1"},
        {"code": "A2", "name": "SK하이닉스"},
        {"code": "A3", "name": "현대차"},
    ]
    ticker_types = {"A1": "STOCK", "E1": "ETF", "A2": "STOCK", "A3": "STOCK"}
    result = select_top_n_stock_codes(price_entries, ticker_types, n=10)
    assert result == ["A1", "A2", "A3"]


def test_select_top_n_respects_limit():
    price_entries = [{"code": f"A{i}"} for i in range(10)]
    ticker_types = {f"A{i}": "STOCK" for i in range(10)}
    result = select_top_n_stock_codes(price_entries, ticker_types, n=3)
    assert result == ["A0", "A1", "A2"]


def test_select_top_n_skips_unknown_type():
    # kr_ticker_master.json 에 없는 코드(둘 사이 날짜 어긋남 등)는 안전하게 제외
    price_entries = [{"code": "A1"}, {"code": "UNKNOWN"}]
    ticker_types = {"A1": "STOCK"}
    result = select_top_n_stock_codes(price_entries, ticker_types, n=10)
    assert result == ["A1"]


# ---------------------------------------------------------------------------
# rebalance_if_due
# ---------------------------------------------------------------------------

def test_first_rebalance_always_happens():
    universe = empty_universe()
    universe, rebalanced = rebalance_if_due(universe, "2026-08-25", ["A1", "A2"])
    assert rebalanced is True
    assert set(universe["members"].keys()) == {"A1", "A2"}
    assert universe["members"]["A1"]["is_visible"] is True
    assert universe["members"]["A1"]["joined_date"] == "2026-08-25"
    assert universe["last_rebalance_date"] == "2026-08-25"


def test_not_due_before_interval_elapsed():
    universe = {"last_rebalance_date": "2026-08-25", "members": {"A1": {"joined_date": "2026-08-25", "left_date": None, "is_visible": True}}}
    # 89일 뒤(90일 미만) — top_candidates가 완전히 달라져도 무시
    universe2, rebalanced = rebalance_if_due(universe, "2026-11-22", ["B1", "B2"], interval_days=90)
    assert rebalanced is False
    assert set(universe2["members"].keys()) == {"A1"}


def test_due_after_interval_elapsed_adds_and_removes_members():
    universe = {"last_rebalance_date": "2026-08-25", "members": {
        "A1": {"joined_date": "2026-08-25", "left_date": None, "is_visible": True},
        "A2": {"joined_date": "2026-08-25", "left_date": None, "is_visible": True},
    }}
    # 90일 뒤, A2는 밀려나고 A3가 새로 들어옴
    universe2, rebalanced = rebalance_if_due(universe, "2026-11-23", ["A1", "A3"], interval_days=90)
    assert rebalanced is True
    assert universe2["last_rebalance_date"] == "2026-11-23"
    assert universe2["members"]["A1"]["is_visible"] is True
    assert universe2["members"]["A3"]["is_visible"] is True
    assert universe2["members"]["A3"]["joined_date"] == "2026-11-23"
    # A2는 지워지지 않고 이탈 표시만 됨 — 1년 추적을 위해
    assert universe2["members"]["A2"]["is_visible"] is False
    assert universe2["members"]["A2"]["left_date"] == "2026-11-23"
    assert "A2" in universe2["members"]


def test_re_entering_stock_clears_left_date():
    universe = {"last_rebalance_date": "2026-08-25", "members": {
        "A1": {"joined_date": "2026-01-01", "left_date": "2026-08-25", "is_visible": False},
    }}
    universe2, rebalanced = rebalance_if_due(universe, "2026-11-23", ["A1"], interval_days=90)
    assert rebalanced is True
    assert universe2["members"]["A1"]["is_visible"] is True
    assert universe2["members"]["A1"]["left_date"] is None


# ---------------------------------------------------------------------------
# prune_expired_members
# ---------------------------------------------------------------------------

def test_prune_removes_only_after_retention_exceeded():
    universe = {"last_rebalance_date": "2026-08-25", "members": {
        "STILL_VISIBLE": {"joined_date": "2020-01-01", "left_date": None, "is_visible": True},
        "LEFT_RECENTLY": {"joined_date": "2020-01-01", "left_date": "2026-08-01", "is_visible": False},
        "LEFT_LONG_AGO": {"joined_date": "2020-01-01", "left_date": "2025-01-01", "is_visible": False},
    }}
    pruned = prune_expired_members(universe, "2026-08-25", retention_days=365)
    codes = set(pruned["members"].keys())
    assert "STILL_VISIBLE" in codes            # is_visible=True는 절대 안 지워짐
    assert "LEFT_RECENTLY" in codes            # 이탈한 지 얼마 안 됨(365일 이내)
    assert "LEFT_LONG_AGO" not in codes        # 1년 넘게 이탈 상태 -> 제거


# ---------------------------------------------------------------------------
# get_tracked_codes / get_visible_codes
# ---------------------------------------------------------------------------

def test_tracked_vs_visible_codes():
    universe = {"last_rebalance_date": "2026-08-25", "members": {
        "VIS": {"joined_date": "x", "left_date": None, "is_visible": True},
        "BUFFER": {"joined_date": "x", "left_date": "2026-08-25", "is_visible": False},
    }}
    assert set(get_tracked_codes(universe)) == {"VIS", "BUFFER"}
    assert set(get_visible_codes(universe)) == {"VIS"}


# ---------------------------------------------------------------------------
# update_universe_for_today — 통합 시나리오
# ---------------------------------------------------------------------------

def test_update_universe_for_today_first_run():
    universe = empty_universe()
    universe, info = update_universe_for_today(universe, "2026-08-25", ["A1", "A2", "A3"])
    assert info["rebalanced"] is True
    assert info["tracked_count"] == 3
    assert info["visible_count"] == 3


def test_update_universe_for_today_prunes_and_skips_rebalance_together():
    universe = {"last_rebalance_date": "2026-08-25", "members": {
        "VIS": {"joined_date": "2020-01-01", "left_date": None, "is_visible": True},
        "EXPIRED": {"joined_date": "2020-01-01", "left_date": "2025-01-01", "is_visible": False},
    }}
    # 리밸런싱 주기(90일) 안 지남 -> top_candidates 무시, 그런데 만료된 멤버는 여전히 정리됨
    universe2, info = update_universe_for_today(universe, "2026-09-01", ["ZZZ"])
    assert info["rebalanced"] is False
    assert "EXPIRED" not in universe2["members"]
    assert "VIS" in universe2["members"]
    assert "ZZZ" not in universe2["members"]  # 리밸런싱 안 했으므로 신규 후보는 아직 안 들어옴
