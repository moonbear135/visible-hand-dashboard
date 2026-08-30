# tests/test_indicator_page.py
"""
「여기서부터는 신앙입니다」(보조지표, `/indicators`) — 2026-08-29 재감사 회귀 테스트

이 화면은 지금까지 화면 코드(`web/pages/indicator_page.py`)를 직접 건드리는 회귀
테스트가 없었습니다. 이 파일은 2026-08-29 재감사(`MACRO_REAUDIT_FINDINGS.md`) H-5를
실제 함수를 호출해 반환된 HTML로 직접 검증합니다(문자열 패턴만 보는 게 아니라 실행
결과를 봅니다) — `tests/test_pegy_page.py`와 같은 방식입니다.

H-5 요약: 이력(`recent_rows`)의 가장 최근 행을 예전엔 무조건 "오늘"이라고 라벨링
했는데, 그날 이력 수집이 실패했으면 그 행은 실제로 며칠 전 값입니다. 카드 상단이
기준으로 삼는 실제 날짜(`data_date`)와 이력 최신 행의 날짜가 어긋나면 "오늘"이라고
부르지 않고 그 사실을 밝히도록 고쳤습니다.

`_build_day_over_day_html`/`_build_recent_trend_html`는 화면 함수 안 클로저가 아니라
모듈 최상위 순수 함수라 직접 호출할 수 있습니다(밑줄로 시작하지만, 이 저장소는
`test_pegy_page.py`에서도 같은 이유로 모듈 최상위 순수 함수를 직접 테스트합니다).

실행: python -m pytest tests/test_indicator_page.py -v
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from web.pages.indicator_page import (
    _build_day_over_day_html,
    _build_recent_trend_html,
)


def _row(date, rsi, verdict='중립'):
    return {'date': date, 'rsi': rsi, 'verdict_label': verdict}


# ---------------------------------------------------------------------------
# _build_day_over_day_html — H-5
# ---------------------------------------------------------------------------

def test_day_over_day_no_stale_note_when_history_matches_data_date():
    """이력 최신 행 날짜 == data_date → "며칠 전 대비"라는 경고를 붙이지 않습니다."""
    rows = [_row('2026-08-29', 65.0), _row('2026-08-28', 60.0)]
    html = _build_day_over_day_html({'verdict_label': '중립'}, rows, data_date='2026-08-29')
    assert '전일(2026-08-28) 대비' in html
    assert '⚠️' not in html
    assert '수집분 아님' not in html


def test_day_over_day_stale_note_when_history_lags_data_date():
    """이력 최신 행이 실제로는 3일 전 값인데 오늘 날짜(data_date)가 따로 넘어오면,
    "전일 대비"가 사실은 "N일 전 대비"였다는 것을 화면에 그대로 밝혀야 합니다(§0-1)."""
    rows = [_row('2026-08-26', 61.2), _row('2026-08-25', 58.0)]
    html = _build_day_over_day_html({'verdict_label': '중립'}, rows, data_date='2026-08-29')
    assert '⚠️' in html
    assert '2026-08-26' in html and '2026-08-29' in html
    assert '수집분 아님' in html
    # 비교 대상 자체는 여전히 정직하게 "2026-08-26 vs 2026-08-25" 라고 밝혀야 합니다.
    assert '2026-08-26 vs 2026-08-25' in html


def test_day_over_day_no_data_date_keeps_old_behavior():
    """`data_date`를 안 넘기면(하위호환) 경고를 붙일 근거가 없으므로 붙이지 않습니다."""
    rows = [_row('2026-08-26', 61.2), _row('2026-08-25', 58.0)]
    html = _build_day_over_day_html({'verdict_label': '중립'}, rows, data_date=None)
    assert '⚠️' not in html
    assert '전일(2026-08-25) 대비' in html


def test_day_over_day_insufficient_history_message_unaffected_by_data_date():
    rows = [_row('2026-08-29', 65.0)]
    html = _build_day_over_day_html({'verdict_label': '중립'}, rows, data_date='2026-08-29')
    assert '전일 데이터가 아직 없습니다' in html
    assert '⚠️' not in html


# ---------------------------------------------------------------------------
# _build_recent_trend_html — H-5
# ---------------------------------------------------------------------------

def test_recent_trend_labels_today_only_when_it_actually_matches_data_date():
    rows = [_row('2026-08-29', 65.0), _row('2026-08-28', 60.0), _row('2026-08-27', 55.0)]
    html = _build_recent_trend_html(rows, data_date='2026-08-29')
    assert '>오늘<' in html
    assert '#38bdf8' in html  # 강조 테두리 색 — 실제로 오늘일 때만
    assert '가장 최근 기록은' not in html


def test_recent_trend_does_not_label_stale_latest_row_as_today():
    """이력 최신 행(08/26)이 실제 기준일(08/29)과 다르면, 가장 최근 칩을 '오늘'이라고
    부르지 않고(강조도 하지 않고) 실제 날짜와 정직 경고를 보여줍니다."""
    rows = [_row('2026-08-26', 61.2), _row('2026-08-25', 58.0), _row('2026-08-24', 50.0)]
    html = _build_recent_trend_html(rows, data_date='2026-08-29')
    assert '>오늘<' not in html
    assert '08/26' in html  # 진짜 날짜가 라벨로 대신 찍힘
    assert '#38bdf8' not in html  # 강조 테두리 없음 — "이게 오늘 값"이라는 암묵적 주장 금지
    assert '가장 최근 기록은 08/26까지입니다' in html
    assert '08/29 수집분이 아직 없음' in html


def test_recent_trend_no_data_date_falls_back_to_no_today_label():
    """하위호환: `data_date`가 없으면 '오늘'이라 부를 근거가 없으므로 라벨링하지 않습니다
    (지어내지 않기 — §0-1)."""
    rows = [_row('2026-08-29', 65.0), _row('2026-08-28', 60.0)]
    html = _build_recent_trend_html(rows, data_date=None)
    assert '>오늘<' not in html
    assert '가장 최근 기록은' not in html  # data_date 자체가 없으니 지연 경고도 낼 수 없음


def test_recent_trend_single_row_renders_nothing():
    html = _build_recent_trend_html([_row('2026-08-29', 65.0)], data_date='2026-08-29')
    assert html == ''


# =============================================================================
# 🚪 진입점 렌더 스모크 — `@ui.page('/indicator')` 함수 **자체**를 실제로 실행
#    (2026-08-30 추가)
# =============================================================================
#  위 테스트들은 전부 **순수 함수**(HTML 조립·정렬·라벨)만 부릅니다. 그래서
#  `indicator_page()` 와 그 안의 `_render_body()` 몸통 — 3단계 공개 게이트, 수집 결과
#  로드, 경고 배너, 카드 루프, 페이저, 다운로드 도구 — 은 지금까지 **어떤 테스트로도 한
#  번도 실행된 적이 없었습니다**. 화면 함수 안의 오타·참조 오류는 그 함수를 실제로
#  실행해봐야만 잡힙니다(TASK_HISTORY_ARCHIVE.md `#128`/`#129` 사고 참고).
#
#  데이터는 저장소의 **실제 수집 결과**(`data/indicator_kr_latest.json`)를 그대로
#  읽습니다(가짜로 만들지 않습니다 — §0-1). AI 해설은 버튼을 눌러야 생성되는 구조라
#  렌더만으로는 외부 API 호출이 일어나지 않습니다.
# =============================================================================
def _run_indicator_page():
    """진입점을 실제로 실행하고 (예외, error_banner 로 그려진 문구 목록) 을 돌려줍니다."""
    sys.path.append(str(Path(__file__).parent))            # tests/ (공용 렌더 헬퍼)
    from _render_helpers import run_render

    import web.pages.indicator_page as page

    drawn = []
    original = page.error_banner
    page.error_banner = lambda text: drawn.append(str(text))
    error = None
    try:
        run_render(page.indicator_page())
    except Exception as exc:                               # noqa: BLE001
        error = exc
    finally:
        page.error_banner = original
    return error, drawn


def test_indicator_page_render_smoke_when_flag_is_off():
    """🚧 1단계(전체 숨김) — URL 로 직접 들어와도 준비중 안내만 그리고 끝납니다."""
    import web.pages.indicator_page as page

    saved = page.INDICATOR_ENABLED
    page.INDICATOR_ENABLED = False
    try:
        error, _drawn = _run_indicator_page()
    finally:
        page.INDICATOR_ENABLED = saved
    assert error is None, f"indicator_page()(플래그 꺼짐)가 예외를 던졌습니다: {error!r}"


def test_indicator_page_render_smoke_with_real_snapshot():
    """🔓 플래그가 켜진 상태에서 **본문 전체**를 실제 수집 결과로 그려 봅니다."""
    import web.pages.indicator_page as page

    saved = (page.INDICATOR_ENABLED, page.INDICATOR_MENU_ADMIN_ONLY)
    page.INDICATOR_ENABLED = True
    page.INDICATOR_MENU_ADMIN_ONLY = False
    try:
        error, drawn = _run_indicator_page()
    finally:
        (page.INDICATOR_ENABLED, page.INDICATOR_MENU_ADMIN_ONLY) = saved
    assert error is None, f"indicator_page()(플래그 켜짐)가 예외를 던졌습니다: {error!r}"

    # 실제 수집 결과가 있는데 §0-1 조기 반환 배너가 떴다면, 본문을 거의 안 그리고 얻은
    # 초록불이라 스모크의 의미가 없습니다.
    snapshot = Path(__file__).parent.parent / "data" / "indicator_kr_latest.json"
    if snapshot.exists():
        early = [b for b in drawn if "불러오지 못했습니다" in b or "0건입니다" in b]
        assert not early, f"실제 수집 결과가 있는데 조기 반환 배너가 떴습니다: {early}"
