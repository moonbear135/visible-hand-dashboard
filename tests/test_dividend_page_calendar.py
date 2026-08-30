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
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.pages.dividend_page import (
    GITHUB_REPO_BLOB_BASE,
    KRX_VERIFIED_RANGE,
    RAW_DOWNLOAD_MAX_BYTES,
    RAW_FILENAME,
    available_months,
    count_future_ex_events,
    dart_link_html,
    ex_dividend_date,
    is_krx_trading_day,
    last_buy_html_kr,
    month_label,
    payment_date_block_html,
    previous_krx_trading_day,
    raw_download_exceeds_cap,
    raw_download_oversize_link_html,
)


def test_available_months_always_includes_today_even_with_no_data():
    today = date(2026, 8, 29)
    months, out_of_range_count = available_months([], {}, today)
    assert months == [(2026, 8)]
    assert out_of_range_count == 0


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
    months, out_of_range_count = available_months(entries, payment_date_index, today)

    # 6월(가장 이른 데이터)부터 4월(가장 늦은 지급예정일)까지 끊김 없이 이어져야 합니다.
    assert months == [
        (2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12),
        (2027, 1), (2027, 2), (2027, 3), (2027, 4),
    ]
    assert (2026, 12) in months, "12월 결산 달 자체는 당연히 포함"
    assert (2027, 4) in months, "다음 해 지급예정일 달까지 이동 가능해야 함(이번 수정의 핵심)"
    assert out_of_range_count == 0


def test_available_months_ignores_unparseable_dates_without_crashing():
    today = date(2026, 1, 15)
    entries = [{"settle_date": None}, {"settle_date": "이상한값"}, {"settle_date": "2026-03-10"}]
    payment_date_index = {"2026-13-99": {}, "": {}}
    months, out_of_range_count = available_months(entries, payment_date_index, today)
    assert months == [(2026, 1), (2026, 2), (2026, 3)]
    assert out_of_range_count == 0


# =============================================================================
# 🔴 M14(2026-08-29) 회귀 테스트 — 손상된 날짜가 월 선택기를 부풀리지 못하게 막기
# =============================================================================
def test_available_months_excludes_and_counts_far_future_corrupted_date():
    today = date(2026, 8, 29)
    entries = [
        {"settle_date": "2026-09-30"},
        {"settle_date": "2062-09-18"},   # 오타로 보이는 손상된 날짜(36년 뒤)
    ]
    months, out_of_range_count = available_months(entries, {}, today)
    assert (2062, 9) not in months
    assert len(months) < 10   # 정상 범위만 남아야 함(손상된 값이 섞이면 440개까지 부풀었음)
    assert out_of_range_count == 1


def test_available_months_excludes_far_future_payment_date_index_key():
    today = date(2026, 8, 29)
    payment_date_index = {"2062-09-18": {}}
    months, out_of_range_count = available_months([], payment_date_index, today)
    assert months == [(2026, 8)]
    assert out_of_range_count == 1


def test_available_months_boundary_at_max_span_is_still_included():
    today = date(2026, 8, 29)
    # 24개월 경계값 — 포함돼야 함(초과가 아니라 "이내"까지 허용).
    entries = [{"settle_date": "2028-08-15"}]
    months, out_of_range_count = available_months(entries, {}, today)
    assert (2028, 8) in months
    assert out_of_range_count == 0

    # 25개월 — 경계를 넘어가면 제외돼야 함.
    entries_over = [{"settle_date": "2028-09-15"}]
    months_over, out_of_range_over = available_months(entries_over, {}, today)
    assert (2028, 9) not in months_over
    assert out_of_range_over == 1


# 🟡 L1(2026-08-29) — `shift_month()`는 이 화면에서 죽은 코드(호출부 없음)라 삭제됐습니다
# (`dividend_page.py` 참고). 이 화면의 달력은 `months.index()` + `_go(index±1)`로만
# 이동하므로 그 함수를 검증할 이유도 함께 사라졌습니다.


def test_month_label_format():
    assert month_label(2027, 4) == "2027년 4월"


# =============================================================================
# 🔴 H5(2026-08-29) 회귀 테스트 — KRX 휴장일 게이트를 연도 단위에서 실제 검증 구간으로
# =============================================================================
# 이 화면이 유일하게 만들어 내는 계산값(배당락일)인데, 고치기 전에는 이 함수들에 테스트가
# 0건이었습니다(H5 가 그대로 통과해 버린 이유 — M16). 아래는 최소한의 회귀 방어입니다.

def test_h5_dates_before_the_verified_range_raise_instead_of_guessing():
    """🔴 H5 재현 — 표가 실제로 덮는 구간은 2025-12-01부터입니다. 그 전 날짜(2025년 신정·
    어린이날 등)는 예전 연도 게이트에서는 전부 '개장일(True)'로 잘못 판정됐습니다. 이제는
    구간 밖이라 예외를 던져야 합니다(추측 금지)."""
    for bad in (date(2025, 1, 1), date(2025, 5, 5), date(2025, 5, 6), date(2025, 8, 15)):
        with pytest.raises(ValueError):
            is_krx_trading_day(bad)


def test_h5_verified_range_boundaries_are_inclusive():
    start, end = KRX_VERIFIED_RANGE
    # 경계값 자체는 예외 없이 판정할 수 있어야 합니다(월요일/휴장일 여부와 무관하게 호출 자체는 됨).
    is_krx_trading_day(start)
    is_krx_trading_day(end)
    with pytest.raises(ValueError):
        is_krx_trading_day(start - timedelta(days=1))
    with pytest.raises(ValueError):
        is_krx_trading_day(end + timedelta(days=1))


def test_is_krx_trading_day_within_verified_range():
    assert is_krx_trading_day(date(2026, 1, 5)) is True    # 월요일, 휴장일 아님
    assert is_krx_trading_day(date(2026, 1, 1)) is False   # 신정(휴장일 표에 있음)
    assert is_krx_trading_day(date(2026, 1, 3)) is False   # 토요일


def test_confirmed_out_of_range_year_still_raises():
    with pytest.raises(ValueError):
        is_krx_trading_day(date(2027, 1, 1))
    with pytest.raises(ValueError):
        is_krx_trading_day(date(2024, 12, 31))


def test_previous_krx_trading_day_skips_weekend_and_holiday():
    # 2026-01-01(신정)의 직전 개장일을 찾으면, 그 결과는 실제로 개장일이어야 하고
    # 신정보다 이전이어야 합니다(2025-12-25·12-31이 모두 휴장일 표에 있어 여러 날을
    # 건너뛰어야 하는 경우입니다).
    assert not is_krx_trading_day(date(2026, 1, 1))  # 신정 자체는 개장일이 아님(사전 확인)
    result = previous_krx_trading_day(date(2026, 1, 1))
    assert result < date(2026, 1, 1)
    assert is_krx_trading_day(result)


def test_ex_dividend_date_computes_one_trading_day_before_record_date():
    # 2026-01-05(월, 개장일)이 배당기준일이면 배당락일은 그 직전 개장일.
    ex_date, reason = ex_dividend_date("2026-01-05")
    assert reason is None
    assert ex_date is not None
    assert ex_date < date(2026, 1, 5)
    assert is_krx_trading_day(ex_date)


def test_ex_dividend_date_refuses_to_guess_outside_verified_range():
    """🔴 H5와 같은 방어 — 확인 안 된 연도의 배당기준일은 (None, 이유)를 돌려줘야지
    아무 날짜나 계산해 주면 안 됩니다."""
    ex_date, reason = ex_dividend_date("2025-01-15")
    assert ex_date is None
    assert reason is not None


def test_ex_dividend_date_returns_none_for_unparseable_input():
    ex_date, reason = ex_dividend_date("이상한값")
    assert ex_date is None
    assert '형식' in reason


# =============================================================================
# 🔴 H3(2026-08-29) 회귀 테스트 — 지급일정의 과거/미래 구분
# =============================================================================
def test_count_future_ex_events_only_counts_today_and_later():
    payment_date_index = {
        "2026-01-01": {"ex": [{"a": 1}, {"a": 2}]},   # 과거
        "2026-08-29": {"ex": [{"a": 3}]},              # 오늘(포함)
        "2026-09-01": {"ex": [{"a": 4}]},              # 미래
    }
    today = date(2026, 8, 29)
    assert count_future_ex_events(payment_date_index, today) == 2


def test_count_future_ex_events_is_zero_when_all_ex_dates_are_past():
    payment_date_index = {"2026-01-01": {"ex": [{"a": 1}]}}
    today = date(2026, 8, 29)
    assert count_future_ex_events(payment_date_index, today) == 0


# =============================================================================
# 🔴 XSS(§0-3-9) 회귀 테스트 — L12가 지적한 대로 "esc() 자동 강제 검사" 문서 서술과 달리
# 이 화면은 자동 검사 대상이 아니지만, 실제로는 잘 방어돼 있습니다(감사 확인). 그 방어를
# 회귀 없이 고정합니다.
# =============================================================================
def test_dart_link_html_blocks_javascript_scheme():
    html = dart_link_html("javascript:alert(1)")
    assert 'javascript:' not in html
    assert '<a href' not in html


def test_dart_link_html_allows_https():
    html = dart_link_html("https://dart.fss.or.kr/example")
    assert 'href="https://dart.fss.or.kr/example"' in html


# =============================================================================
# 🔴 L11(2026-08-29) 회귀 테스트 — "매수 마지막 날"이 미국 화면과 비대칭으로 KR 화면에
# 없던 문제. `last_buy_html_kr()`이 미래/과거/계산불가 세 경우를 §0-1대로 다루는지,
# `payment_date_block_html()`이 이 줄을 '배당락일' 행에만 붙이는지 확인합니다.
# =============================================================================
def test_last_buy_html_kr_shows_computed_date_for_future_ex_date():
    ex_date = date(2026, 1, 5)  # 개장일(월요일)
    html = last_buy_html_kr(ex_date, is_future=True)
    last_buy = previous_krx_trading_day(ex_date)
    assert '매수 마지막 날' in html
    assert f'{last_buy.year}년 {last_buy.month}월 {last_buy.day}일' in html
    assert '🧮 계산값' in html


def test_last_buy_html_kr_does_not_print_a_date_for_past_ex_date():
    html = last_buy_html_kr(date(2026, 1, 5), is_future=False)
    assert '이미 지난 배당락일이라 매수 안내를 하지 않습니다' in html
    assert '까지' not in html


def test_last_buy_html_kr_reports_reason_when_ex_date_is_none():
    html = last_buy_html_kr(None, is_future=True)
    assert '계산할 수 없습니다' in html


def test_last_buy_html_kr_reports_reason_when_out_of_verified_range():
    # 검증 구간(KRX_VERIFIED_RANGE) 시작일 바로 다음 날 → previous_krx_trading_day가
    # 구간 밖으로 넘어가려다 ValueError를 던지는 경우를 재현합니다.
    start, _end = KRX_VERIFIED_RANGE
    html = last_buy_html_kr(start, is_future=True)
    assert '까지' not in html
    assert html  # 빈 문자열이 아니라 이유가 담긴 문구여야 함


def test_payment_date_block_html_attaches_last_buy_line_only_to_ex_row():
    today = date(2026, 8, 29)
    ex_event = {"corp_name": "가짜회사", "stock_code": "000001",
                "record_date": "2026-09-10", "pay_date_expected": "2026-09-30",
                "dps_common": 100}
    record_event = {"corp_name": "가짜회사2", "stock_code": "000002",
                     "record_date": "2026-09-01", "pay_date_expected": "2026-09-30",
                     "dps_common": 200}
    ex_date, _reason = ex_dividend_date("2026-09-10")
    assert ex_date is not None
    payment_date_index = {
        ex_date.isoformat(): {"ex": [ex_event], "record": [], "pay": []},
        "2026-09-01": {"ex": [], "record": [record_event], "pay": []},
    }
    ex_html = payment_date_block_html(ex_date.isoformat(), payment_date_index, today)
    record_html = payment_date_block_html("2026-09-01", payment_date_index, today)
    assert '🛒 매수 마지막 날' in ex_html
    assert '🛒 매수 마지막 날' not in record_html


# =============================================================================
# 🔴 M9/S5(2026-08-29) 회귀 테스트 — raw.jsonl 다운로드 크기 상한
# =============================================================================
def test_raw_download_exceeds_cap_false_under_limit():
    assert raw_download_exceeds_cap(RAW_DOWNLOAD_MAX_BYTES - 1) is False
    assert raw_download_exceeds_cap(RAW_DOWNLOAD_MAX_BYTES) is False  # 경계값은 아직 허용


def test_raw_download_exceeds_cap_true_over_limit():
    assert raw_download_exceeds_cap(RAW_DOWNLOAD_MAX_BYTES + 1) is True


def test_raw_download_exceeds_cap_true_for_measured_real_size_headroom_check():
    # 2026-08-29 실측 raw.jsonl 크기(18,543,149B)가 상한 안에 있는지 — 상한 자체가
    # 이미 넘은 값으로 설정돼 있으면 화면이 열리자마자 정상 파일도 링크로 빠지는 회귀.
    measured_real_size = 18_543_149
    assert raw_download_exceeds_cap(measured_real_size) is False


def test_raw_download_oversize_link_html_points_to_github_and_shows_size():
    html = raw_download_oversize_link_html(60 * 1024 * 1024)  # 60MB
    assert GITHUB_REPO_BLOB_BASE in html
    assert RAW_FILENAME in html
    assert '60.0MB' in html
    assert 'target="_blank"' in html


# =============================================================================
# 🚪 진입점 렌더 스모크 — `@ui.page('/dividend')` 함수 **자체**를 실제로 실행
#    (2026-08-30 추가)
# =============================================================================
#  위 테스트들은 전부 **순수 함수**(달력 격자·색인·집계·다운로드 상한)만 부릅니다.
#  그래서 `dividend_page()` 와 그 안의 `_render_body()` 몸통 — 3단계 공개 게이트,
#  수집 결과 3종 로드, 정직성 고지, 달력 렌더, 미확정 목록 — 은 지금까지 **어떤
#  테스트로도 한 번도 실행된 적이 없었습니다**. 화면 함수 안의 오타·참조 오류는 그
#  함수를 실제로 실행해봐야만 잡힙니다(TASK_HISTORY_ARCHIVE.md `#128`/`#129`).
#
#  데이터는 저장소의 **실제 수집 결과**를 그대로 읽습니다(가짜로 만들지 않습니다 — §0-1).
#  실행 방법은 공용 헬퍼 `tests/_render_helpers.py::run_render()` 를 그대로 씁니다.
# =============================================================================
def _run_dividend_page():
    """진입점을 실제로 실행하고 (예외, error_banner 로 그려진 문구 목록) 을 돌려줍니다."""
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))   # tests/ (공용 렌더 헬퍼)
    from _render_helpers import run_render

    import web.pages.dividend_page as page

    drawn = []
    original = page.error_banner
    page.error_banner = lambda text: drawn.append(str(text))
    error = None
    try:
        run_render(page.dividend_page())
    except Exception as exc:                               # noqa: BLE001
        error = exc
    finally:
        page.error_banner = original
    return error, drawn


def test_dividend_page_render_smoke_when_flag_is_off():
    """🚧 1단계(전체 숨김) — URL 로 직접 들어와도 준비중 안내만 그리고 끝납니다."""
    import web.pages.dividend_page as page

    saved = page.DIVIDEND_ENABLED
    page.DIVIDEND_ENABLED = False
    try:
        error, _drawn = _run_dividend_page()
    finally:
        page.DIVIDEND_ENABLED = saved
    assert error is None, f"dividend_page()(플래그 꺼짐)가 예외를 던졌습니다: {error!r}"


def test_dividend_page_render_smoke_with_real_snapshot():
    """🔓 플래그가 켜진 상태에서 **달력 본문 전체**를 실제 수집 결과로 그려 봅니다."""
    import web.pages.dividend_page as page

    saved = (page.DIVIDEND_ENABLED, page.DIVIDEND_MENU_ADMIN_ONLY)
    page.DIVIDEND_ENABLED = True
    page.DIVIDEND_MENU_ADMIN_ONLY = False
    try:
        error, drawn = _run_dividend_page()
    finally:
        (page.DIVIDEND_ENABLED, page.DIVIDEND_MENU_ADMIN_ONLY) = saved
    assert error is None, f"dividend_page()(플래그 켜짐)가 예외를 던졌습니다: {error!r}"

    snapshot = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "dividend_kr_2026_latest.json")
    if os.path.exists(snapshot):
        early = [b for b in drawn if "불러오지 못했습니다" in b or "0건입니다" in b]
        assert not early, f"실제 수집 결과가 있는데 조기 반환 배너가 떴습니다: {early}"

if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
