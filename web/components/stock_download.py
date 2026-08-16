"""
⬇️ 종목별 데이터 다운로드 도구 (공용).

`views/pegy_view.py` 의 `render_stock_download_tool()` 과
`views/us_stocks_view.py` 의 `_render_stock_download_tool()` 은 **텍스트와 필드 목록만
다르고 구조가 완전히 같은 130줄짜리 복붙**이었습니다. NiceGUI 이전을 하면서 두 번 옮기지
않도록 여기 하나로 합칩니다 (ENGINEERING_SPEC.md §0-3-10).

기능 자체는 원본과 동일합니다.
  - 한 종목을 검색해 고르면 그 종목의 **날짜별 이력 표**(날짜=행 / 지표=열)를 CSV·JSON 으로.
  - 내보내는 항목·라벨의 단일 출처는 `utils/stock_history.py` 의 `*_HISTORY_FIELDS`,
    바이트 생성은 `utils/stock_export.py` — **여기서 새로 포맷을 만들지 않습니다**
    (계획서 §9 완료기준 ⑤ "기존과 바이트 단위로 동일").
  - 이력이 아직 없으면 파일을 만들어 주지 않고 그 사실을 그대로 안내합니다(§0-1 소급 생성 금지).
  - 이 검색창은 **다운로드 전용**이라 아래 카드 목록 필터와 공유하지 않습니다(회귀 위험 회피).
"""

from datetime import datetime
from typing import Callable, List

from nicegui import ui

from utils.stock_export import (
    build_export_filename,
    build_history_csv_bytes,
    build_history_json_bytes,
    history_date_range,
)
from utils.stock_history import load_stock_history, stock_history_path

from web.components.html import compact, esc
from web.components.widgets import download_button, info_banner, warning_banner


def render_stock_download_tool(
    stocks: List[dict],
    *,
    fields: list,
    history_filename: str,
    key_field: str,
    key_of: Callable[[dict], str],
    name_of: Callable[[dict], str],
    subtitle_of: Callable[[dict], str],
    price_text_of: Callable[[dict], str],
    matches: Callable[[dict, str], bool],
    search_label: str,
    search_placeholder: str,
    empty_hint: str,
    no_match_hint: str,
    price_label: str,
    caption: str,
) -> None:
    """검색 → 종목 선택 → CSV/JSON 다운로드. 페이지 함수 안에서 호출하세요.

    상태(검색어·선택 종목)는 **이 함수의 지역 변수**에만 둡니다 — 모듈 전역에 두면
    한 사람의 검색어가 다른 접속자에게 보입니다 (ENGINEERING_SPEC.md §0-3-8 / 계획서 §3-3).
    """
    state = {'query': '', 'picked': 0}

    with ui.expansion(
        '⬇️ 종목별 데이터 다운로드 — 한 종목의 날짜별 데이터(시계열)를 CSV / JSON으로 받기'
    ).classes('w-full').props('dense-toggle'):
        ui.markdown(caption).classes('vh-muted')

        def _on_query(event) -> None:
            state['query'] = (event.value or '').strip()
            state['picked'] = 0
            _results.refresh()

        ui.input(search_label, placeholder=search_placeholder, on_change=_on_query) \
            .props('clearable') \
            .classes('w-full') \
            .style('max-width: 28rem;')

        @ui.refreshable
        def _results() -> None:
            query = state['query']
            if not query:
                info_banner(empty_hint)
                return

            found = [s for s in stocks if matches(s, query)]
            if not found:
                warning_banner(f"🔎 '{query}' 검색 결과가 없습니다. {no_match_hint}")
                return

            if len(found) > 1:
                options = {i: f'{name_of(s)} ({key_of(s)})' for i, s in enumerate(found)}
                index = state['picked'] if state['picked'] in options else 0

                def _on_pick(event) -> None:
                    state['picked'] = event.value or 0
                    _results.refresh()

                ui.select(options, value=index, on_change=_on_pick,
                          label=f'📋 검색 결과 {len(found)}개 — 다운로드할 종목을 선택하세요') \
                    .classes('w-full') \
                    .style('max-width: 28rem;')
                target = found[index]
            else:
                target = found[0]

            _render_target(target)

        def _render_target(target: dict) -> None:
            code = key_of(target)
            name = name_of(target)

            history_rows = load_stock_history(stock_history_path(history_filename), key_field, code)
            if not history_rows:
                warning_banner(
                    f"📭 '{name}({code})'의 날짜별 이력이 아직 없습니다.\n\n"
                    '종목별 이력은 이 기능이 도입된 뒤 첫 수집분부터 쌓이기 시작합니다. '
                    '과거 데이터는 종목 단위로 보관해 둔 적이 없어 소급해서 만들어내지 않습니다'
                    '(없는 숫자를 지어내지 않는다는 원칙). 다음 수집이 끝나면 이 자리에서 받을 수 있습니다.'
                )
                return

            first_date, last_date = history_date_range(history_rows)
            period_text = first_date if first_date == last_date else f'{first_date} ~ {last_date}'
            badge_text = target.get('badge') or '뱃지 없음'

            ui.html(compact(f"""
                <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 1px solid #0284c7; border-radius: 10px; padding: 14px 18px; margin: 6px 0 12px 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                    <div style="display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 6px;">
                        <span style="font-size: 19px; font-weight: 800; color: #e2e8f0;">{esc(name)}</span>
                        <span style="font-size: 13px; color: #94a3b8; font-weight: 600;">{esc(subtitle_of(target))}</span>
                        <span style="font-size: 12.5px; color: #7dd3fc; font-weight: 700;">{esc(badge_text)}</span>
                    </div>
                    <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600;">
                        {esc(price_label)} <b style="color: #38bdf8;">{esc(price_text_of(target))}</b>
                        &nbsp;·&nbsp; 이력 기간 <b style="color: #fef08a;">{esc(period_text)}</b>
                        &nbsp;·&nbsp; 기록일수 <b>{len(history_rows)}</b>일
                        &nbsp;·&nbsp; 지표 <b>{len(fields) - 1}</b>개
                    </div>
                </div>
            """)).classes('w-full')

            date_str = datetime.now().strftime('%Y%m%d')
            with ui.row().classes('w-full gap-3'):
                download_button(
                    '⬇ CSV로 다운로드',
                    build_export_filename(name, code, date_str, 'csv'),
                    # utf-8-sig(BOM) — 그냥 utf-8로 주면 윈도우 엑셀에서 한글이 깨집니다.
                    lambda: build_history_csv_bytes(history_rows, fields),
                    media_type='text/csv',
                )
                download_button(
                    '⬇ JSON으로 다운로드',
                    build_export_filename(name, code, date_str, 'json'),
                    lambda: build_history_json_bytes(history_rows, fields),
                    media_type='application/json',
                )
            ui.markdown(
                '※ 한 줄이 하루입니다(날짜=행 / 지표=열). CSV는 엑셀에서 한글이 깨지지 않도록 UTF-8(BOM)로 '
                '저장됩니다. 값이 비어 있는 칸은 **그날 수집하지 못한 항목**이며 임의의 숫자로 채우지 않습니다. '
                '이력은 이 기능 도입 이후부터 쌓이므로, 시작 초기에는 줄 수가 적은 게 정상입니다.'
            ).classes('vh-muted')

        _results()
