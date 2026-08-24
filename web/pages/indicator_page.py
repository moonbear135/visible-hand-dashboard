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
    read_history_rows,
    stock_history_path,
)

from utils.indicator_ai import IndicatorAIError, get_or_create_commentary

from web.auth import is_admin
from web.blocking import run_blocking
from web.components import (
    disclaimer_footer,
    error_banner,
    esc,
    fmt_num,
    info_banner,
    pager,
    pct_html,
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
#
# 오너 요청(2026-08-25, 4단계 AI 해설 배포 후) — "제미나이한테 일부러 제약을 준 거야?"
# 라는 질문에 "프롬프트 지시 + 사후 금지어 필터 2중 방어(utils/indicator_ai.py 참고)"라고
# 답했더니, "그래도 완벽하진 않다니 맨 위에 제미나이 자체에 대한 경고문도 추가해줘"라고
# 요청. 아래 한 줄을 상하단 배너에 추가 — AI 필터가 놓친 표현이 화면에 그대로 뜨는
# 최악의 경우에도, 사용자가 그 문장 자체를 "잘못된 출력"으로 인식하게 만드는 마지막 방어선.
STRONG_WARNING_TEXT = (
    '🙏 여기서부터는 신앙입니다\n'
    '이 화면의 숫자는 전부 과거 종가를 계산한 결과입니다.\n'
    '미래 주가를 맞히지 않습니다.\n'
    '매수·매도 판단의 근거로 쓰지 마세요.\n'
    'AI(제미나이) 해설에서 "사세요/파세요/매수하세요/매도하세요" 같은 매매를 유도하는 '
    '말이 보인다면, 그것은 잘못된 출력물입니다 — 절대로 그 말을 근거로 삼지 마세요.\n'
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

# 오너 요청(2026-08-25) — "글자가 작아서 눈에 안 띈다": 판독값을 색 있는 배지(알약 모양)로
# 눈에 띄게 키웁니다. 기존 화면들의 배지 팔레트(web/components/html.py::quality_badge /
# warn_badge / info_badge)와 같은 색 관례를 그대로 재사용합니다(§0-3-10) — 새 색을
# 발명하지 않습니다: 주의(과매수/상단 돌파)=호박색, 참고(과매도/하단 이탈)=파란색,
# 중립/밴드 안쪽=회색, 골든크로스=초록, 데드크로스=빨강.
# ⚠️ 이건 "종합판정"에 매수=초록/매도=빨강을 입히지 않기로 한 결정과 다른 자리입니다 —
#    여기 색은 "지표가 지금 어떤 상태인가"를 구분하는 것이지 "사라/팔아라"가 아닙니다.
#    (background, text color, border)
_STATE_BADGE_STYLES = {
    'overbought':   ('#78350f', '#fbbf24', '#facc15'),
    'oversold':     ('#1e3a5f', '#7dd3fc', '#38bdf8'),
    'neutral':      ('#334155', '#cbd5e1', '#64748b'),
    'golden':       ('#14532d', '#86efac', '#4ade80'),
    'dead':         ('#7f1d1d', '#fca5a5', '#f87171'),
    'above_upper':  ('#78350f', '#fbbf24', '#facc15'),
    'below_lower':  ('#1e3a5f', '#7dd3fc', '#38bdf8'),
    'inside':       ('#334155', '#cbd5e1', '#64748b'),
}
_STATE_BADGE_DEFAULT_STYLE = ('#334155', '#cbd5e1', '#64748b')


def _state_badge_html(value, labels, none_text):
    """판독값을 색 있는 배지로. 값이 없으면 배지 없이 평범한 텍스트만(§0-1 — 지어내지 않음)."""
    if value is None:
        return f'<span style="color: #64748b; font-size: 13px; font-weight: 600;">{esc(none_text)}</span>'
    label = _translate(value, labels, none_text)
    bg, color, border = _STATE_BADGE_STYLES.get(value, _STATE_BADGE_DEFAULT_STYLE)
    return (
        f'<span style="display: inline-block; background: {bg}; color: {color}; '
        f'border: 1px solid {border}; border-radius: 8px; padding: 4px 12px; '
        f'font-size: 14px; font-weight: 800; white-space: nowrap;">{esc(label)}</span>'
    )


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


def _to_float(value):
    """이력 CSV 셀(전부 문자열)을 float 로. 못 읽으면 None(0으로 때우지 않음, §0-1)."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _index_recent_history_by_code(rows, days=2):
    """이력 행 목록(전 종목·전 날짜)을 종목코드별로 묶고, **최근 N일치만** 남깁니다.

    카드마다 파일을 따로 읽지 않도록 페이지 진입 시 한 번만 호출합니다(§0-3-10).
    날짜 오름차순이 아니라 **최신이 먼저** 오도록 정렬합니다 — "오늘 대 어제" 비교가
    목적이라 이 순서가 더 다루기 쉽습니다.
    """
    by_code = {}
    for row in rows:
        code = row.get('code')
        if not code:
            continue
        by_code.setdefault(code, []).append(row)
    for code, code_rows in by_code.items():
        code_rows.sort(key=lambda r: r.get('date') or '', reverse=True)
        by_code[code] = code_rows[:days]
    return by_code


async def _load_recent_history_by_code(days=2):
    """전일 대비 비교용 — 이력 CSV 전체를 한 번 읽어 종목코드별 최근 N일치로 인덱싱합니다.

    오너 결정(초기 논의) — "-1일 정보는 뒤로 넘겨보기 정도로" 볼 수 있으면 된다고 했고,
    2026-08-25 재확인 요청으로 카드에 "전일 대비"를 직접 보여줍니다. 장기 이력은 여전히
    아래 다운로드 도구로 받는 몫입니다(§6-2 확정 — 화면은 최근 며칠만, 장기는 다운로드).

    ⚠️ 파일 읽기는 스레드로 넘깁니다(§0-3-4/web/blocking.py 관례 — 이벤트 루프를 붙잡지
       않기 위함). `read_history_rows()`는 파일이 없거나 깨졌으면 빈 목록을 돌려주므로
       (§0-1), 아직 하루치뿐인 지금 상태에서도 안전하게 빈 결과로 처리됩니다.
    """
    rows = await run_blocking(read_history_rows, stock_history_path(INDICATOR_HISTORY_FILENAME))
    return _index_recent_history_by_code(rows, days=days)


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

    # ── 전일 대비 + 최근 며칠 흐름용 이력 인덱스 — 페이지 진입 시 한 번만 읽습니다(§0-3-10) ──
    # 오너 요청(2026-08-25) — "-1일 -2일 -3일 정도는 뒤로 넘겨보기"(§6-2 원 결정)를 이제
    # 카드에 직접 반영: 오늘 포함 최근 4일(오늘 + 최대 3일 전)을 가져옵니다. 이력이 아직
    # 하루치뿐이면(막 도입 직후) 그만큼만 채워지고 나머지는 자연히 안 보입니다 — 없는 날짜를
    # 지어내지 않습니다(§0-1). 데이터는 매일 수집이 돌 때마다 그대로 쌓이므로 며칠 지나면
    # 자동으로 4일 전부 채워집니다.
    history_by_code = await _load_recent_history_by_code(days=4)

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
            _render_stock_card(s, history_by_code.get(s.get('code')), data_date=payload.get('date'))

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


def _build_day_over_day_html(stock: dict, recent_rows: list) -> str:
    """"전일 대비" 한 줄. 비교할 전일 데이터가 없으면 지어내지 않고 그 사실을 그대로 밝힙니다.

    RSI 변화량은 `pct_html()`(기존 등락률 색 함수, §0-3-10 재사용)로 표시합니다 —
    오르면 빨강/내리면 파랑은 "숫자가 커졌다/작아졌다"는 사실 색일 뿐, 종합판정에는
    일부러 안 쓴 매수/매도 색과는 다른 자리입니다(RSI 자체는 매수·매도 신호가 아니라
    하나의 계산값이므로).
    """
    recent_rows = recent_rows or []
    if len(recent_rows) < 2:
        return (
            '<div style="font-size: 11.5px; color: #64748b; margin-top: 6px;">'
            '📅 전일 데이터가 아직 없습니다 — 비교 가능한 어제 값이 쌓이면 여기 표시됩니다.'
            '</div>'
        )

    today_row, prev_row = recent_rows[0], recent_rows[1]
    prev_date = prev_row.get('date') or '—'
    today_rsi = _to_float(today_row.get('rsi'))
    prev_rsi = _to_float(prev_row.get('rsi'))
    prev_verdict = prev_row.get('verdict_label')
    today_verdict = stock.get('verdict_label')

    if today_rsi is not None and prev_rsi is not None:
        rsi_delta_html = pct_html(today_rsi - prev_rsi, digits=2, suffix='p')
    else:
        rsi_delta_html = '—'

    change_line = ''
    if prev_verdict and today_verdict and prev_verdict != today_verdict:
        change_line = (
            f'<div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">'
            f'종합판정 변화: {esc(prev_verdict)} → {esc(today_verdict)}</div>'
        )

    return (
        f'<div style="font-size: 12.5px; color: #94a3b8; margin-top: 6px;">'
        f'전일({esc(prev_date)}) 대비 RSI {rsi_delta_html}</div>{change_line}'
    )


def _format_short_date(date_str) -> str:
    """"2026-08-25" → "08/25". 형식이 예상과 다르면 원문을 그대로 돌려줍니다(지어내지 않음)."""
    text = str(date_str or '').strip()
    parts = text.split('-')
    if len(parts) == 3 and len(parts[1]) == 2 and len(parts[2]) == 2:
        return f'{parts[1]}/{parts[2]}'
    return text or '—'


def _build_recent_trend_html(recent_rows: list) -> str:
    """최근 며칠 흐름을 작은 칩으로 나열합니다 — "-1일 -2일 -3일은 뒤로 넘겨보기 정도로"
    (§6-2 원 결정, 2026-08-25 오너 재확인: "데이터는 쌓일 거니까 3일치는 볼 수 있게").

    표(table) 대신 카드 톤에 맞는 작은 칩으로 — 오너가 이미 "표는 딱딱하다"고 반려한 바 있어
    (이번 3단계 리스트↔카드 논의), 여기서도 같은 톤을 유지합니다. 오래된 날짜가 왼쪽,
    오늘이 오른쪽(가장 눈에 띄는 자리)에 오도록 시간순으로 배치합니다.

    이력이 1건뿐이면(비교할 "며칠"이 없음) 아무것도 그리지 않습니다 — 그 경우는
    `_build_day_over_day_html()`의 "전일 데이터가 아직 없습니다" 문구 하나로 충분하고,
    칩을 하나만 덜렁 보여주면 오히려 헷갈립니다.
    """
    recent_rows = recent_rows or []
    if len(recent_rows) < 2:
        return ''

    chips = []
    # recent_rows 는 최신이 먼저(내림차순) — 칩은 과거→오늘 순으로 보여주려 뒤집습니다.
    for i, row in enumerate(reversed(recent_rows)):
        is_today = (i == len(recent_rows) - 1)
        date_label = '오늘' if is_today else _format_short_date(row.get('date'))
        rsi_val = _to_float(row.get('rsi'))
        rsi_text = f'{rsi_val:.1f}' if rsi_val is not None else '—'
        verdict = row.get('verdict_label') or '—'
        border = '#38bdf8' if is_today else '#334155'
        bg = 'rgba(56, 189, 248, 0.12)' if is_today else 'rgba(15, 23, 42, 0.6)'
        chips.append(
            f'<div style="flex: 1 1 0; min-width: 64px; border: 1px solid {border}; '
            f'background: {bg}; border-radius: 8px; padding: 6px 8px; text-align: center;">'
            f'<div style="font-size: 10.5px; color: #94a3b8; font-weight: 700;">{esc(date_label)}</div>'
            f'<div style="font-size: 14px; color: #f1f5f9; font-weight: 800; margin-top: 2px;">RSI {esc(rsi_text)}</div>'
            f'<div style="font-size: 10px; color: #cbd5e1; margin-top: 1px;">{esc(verdict)}</div>'
            f'</div>'
        )

    return (
        '<div style="display: flex; gap: 6px; margin-top: 8px;">' + ''.join(chips) + '</div>'
    )


def _render_stock_card(stock: dict, recent_rows: list = None, data_date: str = None) -> None:
    """:param recent_rows: 이 종목의 최근 이력(최신이 먼저), `_load_recent_history_by_code()`
        가 만든 것. 없거나 1건뿐이면 "전일 대비"는 표시하지 않습니다(§0-1 — 없는 비교를
        지어내지 않음).
    :param data_date: 이 카드가 보여주는 지표의 기준일(YYYY-MM-DD) — AI 해설 캐시 키로
        그대로 넘깁니다(§4-2, `_render_ai_panel` 참고)."""
    name = stock.get('name')
    code = stock.get('code')
    reasons = _parse_unavailable_reasons(stock.get('unavailable_reasons'))
    warmup = bool(stock.get('warmup_insufficient'))
    bars_used = stock.get('bars_used')
    day_over_day_html = _build_day_over_day_html(stock, recent_rows)
    recent_trend_html = _build_recent_trend_html(recent_rows)

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
        f'<div style="margin-top: 5px;">판독: '
        f'{_state_badge_html(stock.get("rsi_signal"), _RSI_SIGNAL_LABELS, "—")}</div>'
    )

    macd_html = (
        f'<div style="font-size: 13.5px; color: #e2e8f0; margin-top: 3px; line-height: 1.6;">'
        f'MACD <b>{esc(fmt_num(stock.get("macd"), "", 2))}</b> · '
        f'시그널선 <b>{esc(fmt_num(stock.get("macd_signal_line"), "", 2))}</b> · '
        f'히스토그램 <b>{esc(fmt_num(stock.get("macd_histogram"), "", 2))}</b></div>'
        f'<div style="margin-top: 5px;">크로스: '
        f'{_state_badge_html(stock.get("macd_cross"), _MACD_CROSS_LABELS, "없음")}</div>'
    )

    bb_html = (
        f'<div style="font-size: 13.5px; color: #e2e8f0; margin-top: 3px; line-height: 1.6;">'
        f'상단 <b>{esc(fmt_num(stock.get("bb_upper"), "", 2))}</b> · '
        f'중심선 <b>{esc(fmt_num(stock.get("bb_mid"), "", 2))}</b> · '
        f'하단 <b>{esc(fmt_num(stock.get("bb_lower"), "", 2))}</b></div>'
        f'<div style="font-size: 12.5px; color: #cbd5e1; margin-top: 2px;">'
        f'%B {esc(fmt_num(stock.get("bb_percent_b"), "", 4))}</div>'
        f'<div style="margin-top: 5px;">위치: '
        f'{_state_badge_html(stock.get("bb_position"), _BB_POSITION_LABELS, "—")}</div>'
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
                {day_over_day_html}
                {recent_trend_html}
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

    # ── 4단계: 종목별 온디맨드 AI 해설(§4-2) — 카드 아래 이어지는 얇은 패널 ──
    _render_ai_panel(stock, data_date)


def _render_ai_panel(stock: dict, data_date: str) -> None:
    """"🤖 AI 해설 보기" 버튼 — 눌렀을 때만 생성/조회합니다(500종목 전부 자동 호출 금지, §4-2).

    §1 — "AI 해설이 붙는 자리에는 그 옆에 축소판 경고를 한 번 더": 버튼 옆 작은 경고
    문구와, 해설이 나온 뒤 그 아래 또 한 번의 축소판 경고 두 곳에 넣습니다.
    """
    state = {'loaded': False}

    # 오너 요청(2026-08-25) — "글자가 너무 작아, 좀 많이 키워줘": 버튼·경고·해설 본문 전부
    # 카드 본문(RSI 큰 숫자 20px, MACD·볼린저 본문 13.5px) 급으로 눈에 띄게 키웠습니다.
    with ui.column().classes('w-full').style('margin-top: -8px; margin-bottom: 10px;'):
        with ui.row().classes('items-center gap-3').style(
            'background: rgba(15, 23, 42, 0.4); border: 1px dashed #334155; '
            'border-top: none; border-radius: 0 0 12px 12px; padding: 12px 22px; width: 100%;'
        ):
            button = ui.button('🤖 AI 해설 보기', icon='auto_awesome').props('no-caps')
            button.style('font-size: 15px; font-weight: 700; padding: 8px 18px;')
            ui.html(
                '<span style="font-size: 13px; color: #94a3b8; font-weight: 600;">⚠️ AI가 쓴 '
                '참고용 설명입니다 — 매매 판단 근거로 쓰지 마세요.</span>'
            )
        output = ui.html('').classes('w-full').style('padding: 0 22px;')

    async def _on_click() -> None:
        if state['loaded']:
            return
        button.props('loading')
        output.content = (
            '<div style="font-size: 15px; color: #cbd5e1; font-weight: 600; padding: 8px 0;">'
            '🤖 AI 해설을 불러오는 중입니다...</div>'
        )
        try:
            result = await run_blocking(get_or_create_commentary, stock, data_date)
        except IndicatorAIError as exc:
            output.content = (
                f'<div style="font-size: 15px; color: #f87171; font-weight: 600; padding: 8px 0;">'
                f'⚠️ {esc(str(exc))}</div>'
            )
            button.props(remove='loading')
            return
        except Exception as exc:  # noqa: BLE001 — §0-3-4: 예외 원문은 로그로만, 화면엔 정해진 문구
            print(f'⚠️ [indicator_page] AI 해설 처리 중 예기치 못한 오류: {type(exc).__name__}: {exc}')
            output.content = (
                '<div style="font-size: 15px; color: #f87171; font-weight: 600; padding: 8px 0;">'
                '⚠️ AI 해설을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>'
            )
            button.props(remove='loading')
            return

        state['loaded'] = True
        text_html = esc(result['text']).replace('\n', '<br>')
        source_note = '(캐시된 해설 — 오늘 다른 사용자가 먼저 조회함)' if result.get('from_cache') else '(방금 새로 생성됨)'
        generated = result.get('generated_at') or '—'
        output.content = compact(f"""
            <div style="font-size: 17px; color: #f1f5f9; font-weight: 500; line-height: 1.8; padding: 14px 0 6px;
                        border-top: 1px solid #334155; margin-top: 6px;">
                {text_html}
            </div>
            <div style="font-size: 13px; color: #94a3b8; margin-top: 4px; line-height: 1.7; font-weight: 600;">
                🤖 AI가 자동 생성한 참고용 설명입니다 {esc(source_note)} · 생성 시각: {esc(generated)}<br>
                매수·매도 판단의 근거로 쓰지 마세요 — 이 화면 상단의 경고와 같은 내용입니다.
            </div>
        """)
        button.props(remove='loading')
        button.set_text('🤖 AI 해설 (표시됨)')

    button.on_click(_on_click)
