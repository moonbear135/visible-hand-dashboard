"""
web/pages/indicator_page.py

🙏 "여기서부터는 신앙입니다"(7번째 모듈) — RSI·MACD·볼린저밴드 종목별 조회 화면.

작업 지시서: TECHNICAL_INDICATOR_WORK_ORDER.md
  §1  이름·경고 문구 — 이 화면의 상하단 배너(`STRONG_WARNING_TEXT`)가 그 확정 문구입니다.
  §4-1 판정은 100% 파이썬 결정론(utils/indicators.py::combine_verdict), AI는 아직 없음
       (4단계에서 종목별 온디맨드 해설을 추가할 예정 — 이 화면은 그 전 단계입니다).
  §7  로드맵 "3단계: 화면 구현" — 결정론적 판정 + 3지표 원값 + 경고 배너(상하단) + 다운로드.

이 화면이 읽는 데이터: data/indicator_kr_latest.json (collector_indicator_kr.py 가 매일 갱신).
다운로드(종목별 날짜 이력)는 `render_stock_download_tool()`(pegy·us_stocks 와 동일한 공용
도구)을 그대로 재사용합니다 — 새 포맷을 만들지 않습니다(ENGINEERING_SPEC.md §0-3-10).

⚠️ §0-1 — 지표가 산출 불가한 경우 값을 0이나 '중립' 같은 그럴듯한 기본값으로 채우지 않고,
   `unavailable_reasons`(수집기가 남긴 사유)를 그대로 보여줍니다.
"""

import math

from nicegui import ui

from utils.constants import DERIVED_INDICATOR_BADGE
from utils.stock_history import (
    INDICATOR_HISTORY_FIELDS,
    INDICATOR_HISTORY_FILENAME,
    INDICATOR_KEY_FIELD,
)

from web.auth import is_admin
from web.components import (
    disclaimer_footer,
    error_banner,
    esc,
    fmt_num,
    info_banner,
    pager,
    render_stock_download_tool,
    warning_banner,
)
from web.components.html import compact
from web.layout import INDICATOR_ENABLED, INDICATOR_MENU_ADMIN_ONLY, layout
from web.state import PAGE_RESPONSE_TIMEOUT_SECONDS, data_path, load_json_file_async

# =============================================================================
# 상수
# =============================================================================
LATEST_FILENAME = 'indicator_kr_latest.json'

#: 오너 요청(2026-08-25) — 검색만 시키지 말고 전체 목록을 페이지네이션으로 죽 보여줄 것.
#: `web/components/widgets.py::pager()`(dividend/pegy 와 같은 페이지네이션 위젯) 재사용.
ITEMS_PER_PAGE = 20

COMING_SOON_TEXT = (
    '🚧 "여기서부터는 신앙입니다"(보조지표)는 아직 준비중입니다.\n\n'
    '데이터 검수가 끝나고 오너 승인이 나면 열립니다. 그때까지는 아무 수치도 그리지 않습니다.'
)

# 🙏 이 모듈 전용 강한 경고 — TECHNICAL_INDICATOR_WORK_ORDER.md §1 확정 문구.
# 다른 모듈의 "참고용입니다" 수준보다 확실히 강하게, 문장마다 줄을 바꿔서(§0-3-13 배치
# 규칙 위에 얹는 이 모듈만의 예외적으로 강한 버전). error_banner 는 \n 을 <br> 로 바꿔
# 문장 단위 줄바꿈을 그대로 지킵니다 (web/components/widgets.py::_plain 참고 — 새 배너
# 색을 만들지 않고 기존 error 팔레트를 그대로 재사용합니다, §0-3-10).
STRONG_WARNING_TEXT = (
    '🙏 여기서부터는 신앙입니다\n'
    '이 화면의 숫자는 전부 과거 종가를 계산한 결과입니다.\n'
    '미래 주가를 맞히지 않습니다.\n'
    '매수·매도 판단의 근거로 쓰지 마세요.\n'
    '이 정보로 인한 어떤 손실도 개발자와 이 프로젝트는 책임지지 않습니다.'
)

_INDICATOR_LABELS = {'RSI': 'RSI(14)', 'MACD': 'MACD', 'Bollinger': '볼린저밴드'}

# 오너 요청(2026-08-25) — "neutral"/"golden"/"inside" 같은 영어 원문만 보여주면 처음 보는
# 사람은 무슨 뜻인지 모릅니다. 한글 설명 + 영어 원문을 함께 보여줍니다(전문 용어 학습도
# 겸하도록 — 영어만 쓰면 있어 보이지만 초보자는 못 읽음). 값의 출처는
# `utils/indicators.py`의 실제 반환 문자열 그대로이고(단일 출처, §0-3-10), 여기서는
# 화면 표시용 한글 라벨만 얹습니다.
_RSI_SIGNAL_LABELS = {
    'overbought': '과매수 (Overbought)',
    'oversold': '과매도 (Oversold)',
    'neutral': '중립 (Neutral)',
}
_MACD_CROSS_LABELS = {
    'golden': '골든크로스 — 상승 전환 신호 (Golden Cross)',
    'dead': '데드크로스 — 하락 전환 신호 (Dead Cross)',
}
_BB_POSITION_LABELS = {
    'above_upper': '상단 밴드 돌파 (Above Upper Band)',
    'below_lower': '하단 밴드 이탈 (Below Lower Band)',
    'inside': '밴드 안쪽 (Inside Band)',
}


def _translate(value, labels, none_text):
    """`utils/indicators.py`가 돌려주는 영어 원문 값을 "한글 (English)" 표시용 문구로.

    사전에 없는 값(예: 새 상태가 나중에 추가됐는데 여기 라벨을 안 넣은 경우)은 값을
    그대로 보여줍니다 — 모르는 값을 숨기거나 엉뚱한 라벨로 덮어씌우지 않습니다(§0-1).
    """
    if value is None:
        return none_text
    return labels.get(value, str(value))


# =============================================================================
# 순수 함수 (nicegui 위젯을 만들지 않습니다 — 오프라인 검증 가능)
# =============================================================================
def _parse_unavailable_reasons(text):
    """수집기가 남긴 "RSI:사유;MACD:사유" 형태 문자열을 {라벨: 사유} 로 쪼갭니다."""
    result = {}
    if not text:
        return result
    for part in str(text).split(';'):
        part = part.strip()
        if not part or ':' not in part:
            continue
        label, reason = part.split(':', 1)
        result[label.strip()] = reason.strip()
    return result


def _search_matches(stock, query):
    q = query.lower()
    return q in (stock.get('name') or '').lower() or query in (stock.get('code') or '')


# =============================================================================
# 페이지 (공개 플래그 게이트 → 본문) — dividend_page.py 와 같은 패턴(§0-3-10)
# =============================================================================
@ui.page('/indicator', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def indicator_page() -> None:
    """관리자 전용으로 시작(§0-3-6 2단계). 로그인 불필요 — 사용자별 데이터가 없습니다(§0-3-8)."""
    with layout('🙏 여기서부터는 신앙입니다', width_class='max-w-6xl'):
        ui.markdown('## 🙏 여기서부터는 신앙입니다 — RSI·MACD·볼린저밴드')

        # 🚧 이중 방어 — 메뉴(web/layout.py)와 **같은 상수**를 보고 판단합니다.
        if not INDICATOR_ENABLED:
            warning_banner(COMING_SOON_TEXT)
            return
        if INDICATOR_MENU_ADMIN_ONLY and not is_admin():
            warning_banner(COMING_SOON_TEXT)
            return

        await _render_body()


async def _render_body() -> None:
    payload, error = await load_json_file_async(data_path(LATEST_FILENAME))

    # ── §0-1 회귀 지점 — 수집 결과가 없으면 숫자를 하나도 그리지 않습니다 ──
    if payload is None or not isinstance(payload, dict):
        error_banner(
            '🚨 보조지표 수집 결과를 불러오지 못했습니다. '
            f'({error or "파일 형식이 예상과 다릅니다."})\n\n'
            '가짜 값으로 채우지 않기 위해 아무 수치도 표시하지 않습니다.'
        )
        return

    stocks = payload.get('stocks') or []
    if not stocks:
        error_banner(
            '🚨 보조지표 수집 결과에 종목이 0건입니다.\n\n'
            '수집이 정상적으로 끝났는지 확인이 필요합니다. 값을 지어내지 않고 여기서 멈춥니다.'
        )
        return

    # ── 데이터 기준 시각 (§0-3-1 — "실시간"이라 말하지 않고 수집 시각을 그대로) ──
    _render_data_timestamp(payload)

    # ── 🔴 최상단 강한 경고 배너 (TECHNICAL_INDICATOR_WORK_ORDER.md §1) ──
    error_banner(STRONG_WARNING_TEXT)

    if payload.get('failed_count'):
        warning_banner(
            f"⚠️ 오늘 수집에서 {payload['failed_count']}개 종목은 계산에 실패해 이 목록에 "
            '없습니다. 실패한 종목은 다음 수집을 기다려 주세요 (§5-3 — 종목 하나 실패해도 '
            '나머지는 정상 기록되므로, 지금 보이는 값들은 실패와 무관합니다).'
        )

    ui.separator()

    # ── 전체 목록(페이지네이션) + 검색 필터 (state 는 이 함수의 지역 변수만 씁니다, §0-3-8) ──
    # 2026-08-25 오너 요청 — 검색으로만 찾게 하지 말고 목록을 20개씩 죽 보여줄 것.
    # 정렬은 시가총액 내림차순(수집기가 만든 stocks 배열 순서 그대로) — 지표값으로 다시
    # 줄 세우는 랭킹 기능은 만들지 않습니다(오너가 이미 "필요 없다"고 판단한 항목,
    # TECHNICAL_INDICATOR_WORK_ORDER.md §6 항목 7 참고).
    state = {'query': '', 'page': 1}

    def _on_query(event) -> None:
        state['query'] = (event.value or '').strip()
        state['page'] = 1
        _list_section.refresh()

    ui.input('🔍 종목명 / 종목코드 검색 (비워두면 전체 목록)', placeholder='예: 삼성전자, 005930',
              on_change=_on_query).props('clearable').classes('w-full')

    @ui.refreshable
    def _list_section() -> None:
        query = state['query']
        filtered = [s for s in stocks if not query or _search_matches(s, query)]
        if not filtered:
            warning_banner(f"🔎 '{query}' 검색 결과가 없습니다. 종목명이나 6자리 종목코드로 다시 검색해 주세요.")
            return

        total_pages = max(1, math.ceil(len(filtered) / ITEMS_PER_PAGE))
        page = min(max(1, state['page']), total_pages)
        start = (page - 1) * ITEMS_PER_PAGE
        page_items = filtered[start:start + ITEMS_PER_PAGE]

        ui.markdown(
            f'총 **{len(filtered)}종목** 중 {start + 1}~{min(start + ITEMS_PER_PAGE, len(filtered))}번째 '
            f'(페이지 {page}/{total_pages}, 시가총액 순)'
        ).classes('vh-muted')

        # 2026-08-25 오너 요청 — 표(딱딱함) 대신 카드형으로. 나중에 AI 해설(4단계)을 종목별로
        # 붙일 자리도 카드 쪽이 훨씬 자연스럽습니다(표 칸 안에 문단을 넣기는 어려움).
        for s in page_items:
            _render_stock_card(s)

        def _on_page_change(new_page: int) -> None:
            state['page'] = new_page
            _list_section.refresh()

        pager(total_pages, page, _on_page_change)

    _list_section()

    ui.separator()

    # ── 종목별 데이터 다운로드 (pegy·us_stocks 와 같은 공용 도구 재사용, §0-3-10) ──
    await render_stock_download_tool(
        stocks,
        fields=INDICATOR_HISTORY_FIELDS,
        history_filename=INDICATOR_HISTORY_FILENAME,
        key_field=INDICATOR_KEY_FIELD,
        key_of=lambda s: s.get('code'),
        name_of=lambda s: s.get('name'),
        subtitle_of=lambda s: s.get('code'),
        price_text_of=lambda s: s.get('verdict_label') or '데이터 없음',
        matches=_search_matches,
        search_label='🔍 종목명 / 종목코드 검색 (다운로드용)',
        search_placeholder='예: 삼성전자, 005930',
        empty_hint='검색어를 입력하면 그 종목의 날짜별 지표 이력을 CSV/JSON으로 받을 수 있습니다.',
        no_match_hint='종목명이나 6자리 종목코드로 다시 검색해 주세요.',
        price_label='종합판정',
        caption=(
            '한 종목을 검색해 고르면 그 종목의 **날짜별 RSI·MACD·볼린저밴드·종합판정 이력**을 '
            'CSV/JSON으로 받을 수 있습니다. 이력은 이 모듈이 도입된 날부터 쌓이므로, 초기에는 '
            '줄 수가 적은 게 정상입니다(소급 생성하지 않음, §0-1).'
        ),
    )

    # ── 🔴 최하단 강한 경고 배너 (상단과 완전히 같은 문구 — §0-3-13 상하단 배치 규칙) ──
    error_banner(STRONG_WARNING_TEXT)
    disclaimer_footer()


def _render_data_timestamp(payload) -> None:
    generated = payload.get('generated_at')
    date_str = payload.get('date')
    tracked = payload.get('universe_tracked_count')
    visible = payload.get('universe_visible_count')
    success = payload.get('success_count')

    if not generated:
        warning_banner(
            '⚠️ 데이터 기준 시각(generated_at)이 수집 결과에 없습니다. '
            '아래 값이 언제 수집된 것인지 이 화면에서는 확인할 수 없습니다.'
        )
        return

    counts_line = ''
    if tracked is not None:
        counts_line = (
            f"\n\n추적 대상 {tracked}종목(그중 화면 노출 {visible if visible is not None else '—'}종목) "
            f"중 오늘 {success if success is not None else '—'}종목 계산 성공."
        )

    info_banner(
        f'🕒 데이터 기준 (KST): {generated} (기준일 {date_str or "—"})\n\n'
        '이 화면의 모든 값은 그 시각에 계산된 결과이며, 실시간 시세가 아닙니다. '
        'RSI·MACD·볼린저밴드는 매일 새로 받은 종가로 매번 다시 계산합니다(누적 저장된 원본 '
        '시계열을 재사용하지 않음).' + counts_line
    )


def _render_stock_card(stock: dict) -> None:
    name = stock.get('name')
    code = stock.get('code')
    reasons = _parse_unavailable_reasons(stock.get('unavailable_reasons'))
    warmup = bool(stock.get('warmup_insufficient'))
    bars_used = stock.get('bars_used')

    def _block(label_key, available_html):
        """지표 하나(RSI/MACD/Bollinger) — 산출 가능하면 값, 아니면 사유를 그대로 보여줍니다(§0-1)."""
        reason = reasons.get(label_key)
        if reason:
            return (
                f'<div style="padding: 8px 0; border-top: 1px solid #334155;">'
                f'<div style="font-size: 12px; color: #94a3b8; font-weight: 700;">{esc(_INDICATOR_LABELS[label_key])}</div>'
                f'<div style="font-size: 13px; color: #fbbf24; font-weight: 600; margin-top: 2px;">'
                f'⚠️ 산출 불가 — {esc(reason)}</div></div>'
            )
        return (
            f'<div style="padding: 8px 0; border-top: 1px solid #334155;">'
            f'<div style="font-size: 12px; color: #94a3b8; font-weight: 700;">{esc(_INDICATOR_LABELS[label_key])} '
            f'<span style="font-size: 10px; font-weight: 800; color: #7dd3fc;">{esc(DERIVED_INDICATOR_BADGE)}</span></div>'
            f'{available_html}</div>'
        )

    rsi_html = (
        f'<div style="font-size: 20px; color: #f8fafc; font-weight: 800; margin-top: 3px;">'
        f'{esc(fmt_num(stock.get("rsi"), "", 2))}</div>'
        f'<div style="font-size: 12.5px; color: #cbd5e1; margin-top: 1px;">판독: '
        f'{esc(_translate(stock.get("rsi_signal"), _RSI_SIGNAL_LABELS, "—"))}</div>'
    )

    macd_html = (
        f'<div style="font-size: 13.5px; color: #e2e8f0; margin-top: 3px; line-height: 1.6;">'
        f'MACD <b>{esc(fmt_num(stock.get("macd"), "", 2))}</b> · '
        f'시그널선 <b>{esc(fmt_num(stock.get("macd_signal_line"), "", 2))}</b> · '
        f'히스토그램 <b>{esc(fmt_num(stock.get("macd_histogram"), "", 2))}</b></div>'
        f'<div style="font-size: 12.5px; color: #cbd5e1; margin-top: 1px;">크로스: '
        f'{esc(_translate(stock.get("macd_cross"), _MACD_CROSS_LABELS, "없음"))}</div>'
    )

    bb_html = (
        f'<div style="font-size: 13.5px; color: #e2e8f0; margin-top: 3px; line-height: 1.6;">'
        f'상단 <b>{esc(fmt_num(stock.get("bb_upper"), "", 2))}</b> · '
        f'중심선 <b>{esc(fmt_num(stock.get("bb_mid"), "", 2))}</b> · '
        f'하단 <b>{esc(fmt_num(stock.get("bb_lower"), "", 2))}</b></div>'
        f'<div style="font-size: 12.5px; color: #cbd5e1; margin-top: 1px;">'
        f'%B {esc(fmt_num(stock.get("bb_percent_b"), "", 4))} · 위치: '
        f'{esc(_translate(stock.get("bb_position"), _BB_POSITION_LABELS, "—"))}</div>'
    )

    verdict_score = stock.get('verdict_score')
    verdict_label = stock.get('verdict_label')
    # ⚠️ 매수=초록/매도=빨강 같은 방향성 색을 일부러 쓰지 않습니다 — 이 화면 자체가
    #    "매수·매도 판단 근거로 쓰지 말라"는 강한 경고 위에 서 있는데, 판정에 색을 입히면
    #    그 경고와 정면으로 배치되는 신호를 주게 됩니다(§0-1 취지 확장 적용).
    verdict_html = (
        f'<div style="font-size: 26px; color: #f8fafc; font-weight: 900; margin-top: 4px;">'
        f'{esc(verdict_label or "산출 불가")}</div>'
        f'<div style="font-size: 12.5px; color: #94a3b8; margin-top: 2px;">'
        f'합산 점수: {esc(fmt_num(verdict_score, "", 0)) if verdict_score is not None else "산출 불가"} '
        f'(3개 지표 중 산출 가능한 것만 합산 — §4-1)</div>'
    )

    warmup_note = (
        '<div style="font-size: 12px; color: #fbbf24; font-weight: 600; margin-top: 8px;">'
        '⚠️ 이 종목은 아직 충분한 데이터가 쌓이지 않아(워밍업 부족) 지표 값이 안정되지 않았을 '
        '수 있습니다. 값이 없다는 뜻이 아니라, 시간이 더 지나야 신뢰도가 올라간다는 뜻입니다.'
        '</div>'
    ) if warmup else ''

    ui.html(compact(f"""
        <div style="background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155;
                    border-radius: 14px; padding: 18px 22px; margin: 10px 0;">
            <div style="display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;">
                <span style="font-size: 20px; font-weight: 800; color: #e2e8f0;">{esc(name)}</span>
                <span style="font-size: 13px; color: #94a3b8; font-weight: 600;">({esc(code)})</span>
            </div>
            <div style="margin-top: 6px; padding: 10px 14px; background: rgba(15, 23, 42, 0.6);
                        border-radius: 10px;">
                <div style="font-size: 12px; color: #94a3b8; font-weight: 700;">종합판정</div>
                {verdict_html}
            </div>
            {_block('RSI', rsi_html)}
            {_block('MACD', macd_html)}
            {_block('Bollinger', bb_html)}
            {warmup_note}
            <div style="font-size: 11px; color: #64748b; margin-top: 10px;">
                사용 종가 봉 수: {esc(bars_used) if bars_used is not None else '—'}봉
            </div>
        </div>
    """)).classes('w-full')
