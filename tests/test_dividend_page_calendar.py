# tests/test_dividend_page_calendar.py
"""
🇰🇷 배당 KR 달력 — 월 이동 순수 함수 오프라인 검증 (네트워크 불필요)

🔴 2026-08-29(오푸스 감사 Top-5 #4) — `web/pages/dividend_page.py`의 달력이
`today.year`를 못 벗어나 12월 결산 배당의 지급예정일(통상 다음 해 3~4월)이 화면
어디서도 안 보이던 문제를 고치며 추가. `available_months()`/`shift_month()`/
`month_label()`이 미국 배당 화면(`dividend_us_logic.py`)과 같은 방식으로 연도
경계를 올바르게 넘는지만 검증합니다(NiceGUI 렌더링 자체는 여기서 다루지 않습니다 —
이 세 함수는 순수 함수라 이 모듈만 따로 import 해도 부작용이 없습니다, 실측 확인).

실행: python -m pytest tests/test_dividend_page_calendar.py -v
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.pages.dividend_page import available_months, month_label, shift_month


def test_available_months_always_includes_today_even_with_no_data():
    today = date(2026, 8, 29)
    months = available_months([], {}, today)
    assert months == [(2026, 8)]


def test_available_months_spans_year_boundary_for_december_settlement_payment_date():
    """
    이 테스트가 고정하는 정확한 회귀 시나리오: 12월 결산(`settle_date`)의 지급예정일이
    다음 해 4월(`payment_date_index`에만 존재, 확정 목록의 `settle_date`에는 없음)일 때,
    달력이 그 달까지 이동할 수 있어야 합니다. 고치기 전에는 `1 <= month <= 12` 로 월만
    옮기고 연도는 그대로였어서 2027년 쪽으로 절대 못 갔습니다.
    """
    today = date(2026, 8, 29)
    entries = [
        {"settle_date": "2026-12-31"},
        {"settle_date": "2026-06-30"},
    ]
    payment_date_index = {
        "2027-04-15": {"record": [], "pay": [{"ticker": "005390"}], "ex": []},
    }
    months = available_months(entries, payment_date_index, today)

    # 6월(가장 이른 데이터)부터 4월(가장 늦은 지급예정일)까지 끊김 없이 이어져야 합니다.
    assert months == [
        (2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12),
        (2027, 1), (2027, 2), (2027, 3), (2027, 4),
    ]
    assert (2026, 12) in months, "12월 결산 달 자체는 당연히 포함"
    assert (2027, 4) in months, "다음 해 지급예정일 달까지 이동 가능해야 함(이번 수정의 핵심)"


def test_available_months_ignores_unparseable_dates_without_crashing():
    today = date(2026, 1, 15)
    entries = [{"settle_date": None}, {"settle_date": "이상한값"}, {"settle_date": "2026-03-10"}]
    payment_date_index = {"2026-13-99": {}, "": {}}
    months = available_months(entries, payment_date_index, today)
    assert months == [(2026, 1), (2026, 2), (2026, 3)]


def test_shift_month_crosses_year_boundary_both_directions():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2027, 1, -1) == (2026, 12)
    assert shift_month(2026, 6, 6) == (2026, 12)
    assert shift_month(2026, 6, 7) == (2027, 1)


def test_month_label_format():
    assert month_label(2027, 4) == "2027년 4월"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
