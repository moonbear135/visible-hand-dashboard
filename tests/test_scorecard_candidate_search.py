# tests/test_scorecard_candidate_search.py
"""
📊 "내 성적표" — 보유 종목 입력의 "종목 빠른 검색" 드롭다운이 한글명으로도 검색되는지.

2026-08-29 — 결투 달러 주문창과 똑같은 버그가 여기(`web/pages/scorecard_page.py::_candidate_options()`)
에도 있었습니다: `ui.select(with_input=True)` 는 라벨 텍스트 자체를 부분일치 검색하는데, 미국 종목은
영문명(`name`)만 라벨에 있어 한글 검색이 전혀 안 됐습니다. 결투 쪽(`web/pages/duel_page.py::_universe_options()`)
을 먼저 고친 뒤(§0-3-10 — 같은 방식 재사용), 여기도 동일하게 고쳤습니다.

실행: python -m pytest tests/test_scorecard_candidate_search.py -q
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from web.pages.scorecard_page import MARKET_KR, MARKET_US, _candidate_options  # noqa: E402


def test_candidate_options_includes_korean_name_so_us_stocks_are_searchable_in_korean():
    market = {
        "indexes": {
            MARKET_US: {
                "NVDA": {"name": "NVIDIA Corporation", "name_kr": "엔비디아"},
                "AAPL": {"name": "Apple Inc.", "name_kr": None},  # §0-1 — 없으면 지어내지 않음
            },
            MARKET_KR: {},
        },
        "kr_master": {},
    }
    options = _candidate_options(MARKET_US, market)

    assert "엔비디아" in options["NVDA"]
    assert options["NVDA"] == "NVDA · NVIDIA Corporation(엔비디아)"
    # 한글명이 없으면(§0-1) 괄호를 지어내 붙이지 않습니다.
    assert options["AAPL"] == "AAPL · Apple Inc."


def test_candidate_options_kr_market_unaffected_by_name_kr_field():
    """한국 종목은 `name` 자체가 이미 한글이라, name_kr 필드가 있어도/없어도 영향이 없어야 합니다."""
    market = {
        "indexes": {
            MARKET_KR: {"005930": {"name": "삼성전자"}},
            MARKET_US: {},
        },
        "kr_master": {"005935": {"name": "삼성전자우"}},
    }
    options = _candidate_options(MARKET_KR, market)

    assert options["005930"] == "005930 · 삼성전자"
    assert options["005935"] == "005935 · 삼성전자우"
