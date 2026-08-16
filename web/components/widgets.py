"""
공용 NiceGUI 위젯 조각 (배너 · 메트릭 카드 · 다운로드 버튼 · 페이지네이션).

Streamlit 에는 있었지만 NiceGUI 에는 동등 위젯이 없는 것들(`st.metric`,
`st.error/warning/info`, `st.download_button`)을 여기서 한 번만 만들어 두고
모든 화면이 같이 씁니다 (ENGINEERING_SPEC.md §0-3-10 — 화면마다 복붙 금지).

⚠️ §0-1: 실패 배너(`error_banner`)는 **일시적인 토스트(`ui.notify`)가 아니라 화면에
   계속 남는 박스**여야 합니다. 사용자가 스크롤하다 놓치면 "실패 사실이 화면까지 도달"
   했다고 볼 수 없기 때문입니다.
⚠️ §0-3-4: 배너 문구에 파이썬 예외 원문(`str(e)`)·파일경로·트레이스백을 넣지 마세요.
   원인 상세는 `print()` 로 서버 로그에만 남기고, 화면에는 사람이 읽는 문장만 둡니다.
"""

from typing import Callable, Optional, Union

from nicegui import ui

from web.components.html import FOOTER_NOTICE_HTML, compact, esc, fmt_num

# 배너 종류별 색상 (프로젝트 카드 팔레트와 동일 계열)
_BANNER_PALETTE = {
    'error': ('rgba(127, 29, 29, 0.35)', '#ef4444', '#fecaca'),
    'warning': ('rgba(120, 53, 15, 0.35)', '#f59e0b', '#fde68a'),
    'info': ('rgba(14, 116, 144, 0.30)', '#38bdf8', '#bae6fd'),
    # 2026-08-17 (6단계) — `st.success` 대체. 매크로 화면이 "지금 보는 데이터가 최신 마감분인가"
    # (초록) / "아닌가"(파랑)를 색으로 구분해서 알려주는데, 그 신호를 잃지 않으려면 필요합니다.
    'success': ('rgba(6, 78, 59, 0.35)', '#22c55e', '#bbf7d0'),
}


def banner(kind: str, body_html: str) -> None:
    """지속 표시 배너. `body_html` 은 **호출하는 쪽이 이스케이프까지 끝낸** HTML 입니다."""
    background, border, color = _BANNER_PALETTE[kind]
    ui.html(compact(f"""
        <div style="background: {background}; border: 1.5px solid {border}; border-radius: 10px;
                    padding: 14px 20px; margin: 6px 0 14px 0; color: {color}; font-size: 14px;
                    font-weight: 600; line-height: 1.6;">
            {body_html}
        </div>
    """)).classes('w-full')


def _plain(kind: str, text: str) -> None:
    """평문 메시지용 — 이스케이프 후 줄바꿈만 <br> 로 바꿔서 배너로 그립니다."""
    banner(kind, esc(text).replace('\n', '<br>'))


def error_banner(text: str) -> None:
    _plain('error', text)


def warning_banner(text: str) -> None:
    _plain('warning', text)


def info_banner(text: str) -> None:
    _plain('info', text)


def success_banner(text: str) -> None:
    _plain('success', text)


def metric_card(label: str, value: str, delta: str = '', *, delta_html: str = '') -> None:
    """`st.metric` 대체 (NiceGUI 에 동등 위젯 없음).

    값이 없을 때 `—`/'데이터 없음' 을 그대로 크게 보여주는 용도까지 포함합니다(§0-1).

    :param delta: 카드 아래 작은 회색 한 줄. **평문**이며 여기서 이스케이프합니다.
    :param delta_html: 색을 입힌 등락률처럼 **이미 HTML 인 한 줄**(예: `pct_html()` 결과).
        이 값은 그대로 출력하므로 **호출하는 쪽이 이스케이프까지 끝내서** 넘겨야 합니다
        (§0-3-9). 사장님 보고서의 '평가금액 변화' 카드가 국내 관례 색(오르면 빨강/내리면
        파랑)을 유지하려고 씁니다 — 색 있는 카드를 화면마다 따로 만들지 않기 위한 것입니다.
    """
    delta_body = delta_html or (esc(delta) if delta else '')
    delta_block = (
        f'<div style="font-size: 13px; color: #94a3b8; font-weight: 600; margin-top: 4px;">{delta_body}</div>'
        if delta_body else ''
    )
    ui.html(compact(f"""
        <div style="background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155;
                    border-radius: 14px; padding: 14px 18px; height: 100%;">
            <div style="font-size: 13px; color: #94a3b8; font-weight: 700; line-height: 1.4;">{esc(label)}</div>
            <div style="font-size: 30px; color: #f8fafc; font-weight: 800; letter-spacing: -1px;
                        margin-top: 6px; overflow-wrap: break-word;">{esc(value)}</div>
            {delta_block}
        </div>
    """)).style('flex: 1 1 240px;')
    # ⚠️ 폭 지정은 Tailwind 임의값 클래스(`min-w-[240px]`)가 아니라 인라인 style 로 둡니다.
    #    NiceGUI 버전에 따라 Tailwind/UnoCSS 빌드가 임의값 클래스를 만들어 주지 않을 수 있어,
    #    "적용된 줄 알았는데 아무 효과가 없는" 상태가 되기 쉽기 때문입니다(계획서 §11-2).


def _median(values):
    """중앙값. 표본이 없으면 **평균값 같은 그럴듯한 수를 만들지 않고** None 입니다(§0-1)."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def render_summary_metrics(stocks, summary_history, labels) -> None:
    """상단 요약 지표 3종 (중앙 Forward PER / 중앙 성장률 / 중앙 PEGY).

    pegy·us_stocks 두 화면이 **완전히 같은 계산식과 같은 문구**를 쓰고 라벨만 다릅니다
    (원본 Streamlit 코드에서도 45줄이 통째로 복붙돼 있었습니다 — §0-3-10).

    :param labels: (Forward PER 라벨, 성장률 라벨, PEGY 라벨)
    ⚠️ 표본이 없으면 10.4 / 14.2 / 0.73 같은 그럴듯한 상수를 표시하지 않고 '데이터 없음'입니다(§0-1).
    """
    f_per_list = [s['f_per'] for s in stocks if s.get('f_per')]
    growth_list = [s['growth'] for s in stocks if s.get('growth') is not None]
    pegy_list = [s['f_pegy'] for s in stocks if s.get('f_pegy') and 0 < s['f_pegy'] < 50.0]

    calc_f_per = round(_median(f_per_list), 1) if f_per_list else None
    calc_growth = round(_median(growth_list), 1) if growth_list else None
    calc_pegy = round(_median(pegy_list), 2) if pegy_list else None

    f_per_delta_str = f'{len(f_per_list)}개 종목 실측 중앙값'
    growth_delta_str = f'{len(growth_list)}개 종목 실측 중앙값'
    pegy_delta_num = None

    if len(summary_history) >= 2 and None not in (calc_f_per, calc_growth, calc_pegy):
        prev = summary_history[-2]
        p_per, p_growth, p_pegy = prev.get('f_per'), prev.get('growth'), prev.get('pegy')
        if p_per is not None:
            f_per_delta_str = f'{calc_f_per - p_per:+.1f}배 (이전 동기화 대비)'
        if p_growth is not None:
            growth_delta_str = f'{calc_growth - p_growth:+.1f}%p (이전 동기화 대비)'
        if p_pegy is not None:
            pegy_delta_num = f'{calc_pegy - p_pegy:+.2f}'

    if calc_pegy is None:
        pegy_status = '산출 불가 (표본 없음)'
    elif calc_pegy < 0.85:
        pegy_status = '🟢 저평가 수용 구간'
    elif calc_pegy < 1.15:
        pegy_status = '🟡 적정 밸류 구간'
    else:
        pegy_status = '🔴 고평가 관망 구간'

    pegy_delta_str = f'{pegy_delta_num} | {pegy_status}' if pegy_delta_num else pegy_status

    with ui.row().classes('w-full gap-4 items-stretch'):
        metric_card(labels[0], fmt_num(calc_f_per, ' 배', 1), f_per_delta_str)
        metric_card(labels[1], fmt_num(calc_growth, ' %', 1), growth_delta_str)
        metric_card(labels[2], fmt_num(calc_pegy, '', 2), pegy_delta_str)

    if None in (calc_f_per, calc_growth, calc_pegy):
        warning_banner("⚠️ 위 요약 지표 중 일부는 실측 표본이 없어 산출하지 못했습니다 ('데이터 없음').")


def disclaimer_footer() -> None:
    """화면 맨 아래 "학습용 보조 도구" 고지 (두 공개 화면 공통)."""
    ui.html(compact(FOOTER_NOTICE_HTML)).classes('w-full')


def download_button(label: str,
                    filename: Union[str, Callable[[], str]],
                    data: Union[bytes, str, Callable[[], Optional[Union[bytes, str]]]],
                    *,
                    media_type: str = '',
                    failure_text: str = '파일을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.') -> None:
    """`st.download_button` 대체.

    `data`/`filename` 에 **무인자 콜러블**을 넘기면 클릭한 순간에 계산합니다
    (큰 JSON 을 접속할 때마다 미리 읽지 않기 위함).

    ⚠️ 완료기준 ⑤ — 파일 내용은 기존과 **바이트 단위로 동일**해야 하므로, 데이터를 만드는
    로직은 반드시 기존 함수(`utils/stock_export.py` 등)를 그대로 재사용하세요.
    여기서 새로 포맷을 짜지 않습니다.
    """
    def _click() -> None:
        try:
            payload = data() if callable(data) else data
            name = filename() if callable(filename) else filename
        except Exception as exc:                      # noqa: BLE001 — 사용자에겐 문장만, 상세는 로그로
            print(f'⚠️ 다운로드 파일 생성 실패: {exc}')
            ui.notify(failure_text, type='negative')
            return
        if payload is None:
            ui.notify(failure_text, type='negative')
            return
        ui.download.content(payload, name, media_type)

    ui.button(label, on_click=_click).props('outline no-caps').classes('text-sm')


def scroll_to_top() -> None:
    """화면 최상단으로 부드럽게 스크롤.

    기존 `views/pegy_view.py` 는 `<script>` 안에서 `window.parent.document` 를 뒤졌습니다 —
    Streamlit 앱이 `index.html` 의 **iframe 안**에 들어가 있었기 때문입니다. NiceGUI +
    Render 에서는 앱이 최상위 문서라 iframe 자체가 없어져(계획서 §1-3) 그 코드는 동작하지
    않습니다. 계획서 §4-2 대로 `ui.run_javascript` 로 교체했습니다.
    """
    ui.run_javascript(
        "window.scrollTo({top: 0, behavior: 'smooth'});"
        "const el = document.scrollingElement || document.documentElement;"
        "if (el && el.scrollTo) el.scrollTo({top: 0, behavior: 'smooth'});"
    )


def pager(total_pages: int, current_page: int, on_change: Callable[[int], None]) -> None:
    """페이지네이션 + **이동 시 최상단 스크롤** (계획서 §9 "2. pegy" 완료기준 ④).

    `st.radio` 세로 목록(#123 의 가로 넘침 회피책)을 Quasar QPagination 으로 교체합니다 —
    페이지가 28개여도 "1 … 5 6 7 … 28" 로 압축돼 좁은 화면에서 넘칠 수가 없습니다.
    """
    total_pages = max(1, int(total_pages))
    current_page = min(max(1, int(current_page)), total_pages)

    def _changed(event) -> None:
        page = int(event.value) if event.value else 1
        # 스크롤을 먼저 보내고 나서 목록을 다시 그립니다. 순서를 반대로 하면 새 카드가
        # 그려진 뒤에 화면이 위로 튀어 깜빡이는 느낌이 납니다.
        scroll_to_top()
        on_change(page)

    with ui.row().classes('w-full justify-center'):
        ui.pagination(1, total_pages, direction_links=True, value=current_page, on_change=_changed)
