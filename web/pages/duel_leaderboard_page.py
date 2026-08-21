"""
⚔️ 결투다! — 2갈래 "내 밑으로 눈 깔어" **공개 순위표 열람 화면** (로그인 필요, URL `/duel/leaderboard`).

`DUEL_MODULE_WORK_ORDER.md` **5-3 · 5-6 · 5-7 · 5-2** 의 화면입니다.

-------------------------------------------------------------------------------
🔴 이 화면이 읽는 것은 **발행 전용 표 두 개뿐**입니다 (5-4-5 · §0-3-8)
-------------------------------------------------------------------------------
작업지시서 5-4-5 원문: *"화면은 **이 두 표만** 읽습니다. `duel_positions`·`holdings`·
`profiles`·`duel_cash_ledger` 를 순위표 코드 경로에서 **import 조차 하지 않게** 하세요."*

그래서 이 파일이 `utils/duel_db.py` 에서 가져오는 것은 **발행표를 읽는 함수 3개뿐**입니다.
계좌·포지션·현금·스냅샷·동의를 읽는 함수는 이름조차 가져오지 않습니다. 발행표에는
`user_id` 도 `account_id` 도 **컬럼 자체가 없고**(스키마 §8), 그 함수들은 `select("*")` 를
쓰지 않고 읽을 컬럼을 하나하나 적습니다 — 즉 이 화면이 아무리 잘못 짜여도 **닉네임 말고
사람을 가리키는 값이 흘러 들어올 자리가 물리적으로 없습니다.** §0-3-8 이 요구하는 것은
조심이 아니라 이런 구조입니다.

순위(`rank`)는 **밤에 배치가 계산해 저장해 둔 값**을 그대로 읽습니다. 이 화면은 순위도,
수익률도 계산하지 않습니다(§0-3-2 / 5-7 — 방문자 수만큼 전체 스캔이 돌면 안 됩니다).

-------------------------------------------------------------------------------
🚧 공개 게이트 — `duel_page.py` 와 **똑같은 3단계 패턴**, 스위치만 다릅니다
-------------------------------------------------------------------------------
    DUEL_ENABLED                     … 1갈래 전체 스위치(꺼져 있으면 2갈래도 없습니다)
    DUEL_LEADERBOARD_ENABLED         … 이 화면 전용 스위치(기본 꺼짐, 환경변수)
    DUEL_LEADERBOARD_MENU_ADMIN_ONLY … 관리자 전용 단계 ↔ 전체 공개

오너 방침(2026-08-20): *"코드는 지금 만들어도 되지만 실제 공개는 사람이 쌓이기 전까지
미룬다."* 최소 인원 게이팅(5-6)이 이미 구조적으로 막고 있지만, 그건 "발행이 안 된다"는
뜻이고 **화면이 안 보인다**는 뜻은 아니라서 화면 쪽 스위치를 따로 둡니다.

-------------------------------------------------------------------------------
📝 문구에 대하여
-------------------------------------------------------------------------------
· 맨 위 **고정 문구 두 문단은 작업지시서 5-3 에서 글자 그대로** 옮긴 것입니다(오너 확정).
  요약·축약·재배치 금지. 스크롤 없이 보이는 위치에 고정합니다.
· 그 밖의 안내 문구는 **초안**이며 7-2 에서 오너가 다시 검토합니다.
"""

from nicegui import ui

from utils import duel_rules
from utils.duel_db import (
    DuelDbError,
    fetch_public_holdings_for_nickname,
    fetch_public_leaderboard,
    fetch_public_leaderboard_latest_date,
)
from utils.duel_rules import DuelRuleError
# ⚠️ `utils/scorecard_db.py` 에서 가져오는 것은 **로그인 확인과 금액 서식 4개뿐**입니다.
#    실제 보유종목(`holdings`)을 읽는 함수는 이름조차 가져오지 않습니다(5-4-5 위 머리말).
from utils.scorecard_db import format_amount, supabase_status, user_id_of
from web.auth import (
    current_user_async,
    get_client_async,
    has_supabase_session,
    is_admin,
    logout_async,
)
from web.auth_ui import fail_message, render_auth
from web.blocking import run_blocking
from web.components import (
    error_banner, esc, holdings_table_html, info_banner, pct_text, warning_banner,
)
from web.layout import (
    DUEL_ENABLED,
    DUEL_LEADERBOARD_ENABLED,
    DUEL_LEADERBOARD_MENU_ADMIN_ONLY,
    layout,
)
from web.state import PAGE_RESPONSE_TIMEOUT_SECONDS

# =============================================================================
# 🔴 순위표 최상단 고정 문구 — 작업지시서 5-3, **오너 확정 · 글자 그대로**
# =============================================================================
#  작업지시서 원문: *"아래 문구를 랭킹 페이지 어디서도 스크롤 없이 바로 보이는
#  위치(최상단)에 고정합니다. 문구는 그대로 씁니다 — 요약·축약하지 마세요."*
#
#  ⚠️ 이 두 문단은 다듬지 마세요. 맞춤법·띄어쓰기까지 원문 그대로입니다("공개되어있는",
#     "주의바랍니다"). 고치고 싶으면 작업지시서 5-3 을 먼저 고치고 오너 확인을 받으세요.
FIXED_NOTICE_PARAGRAPHS = (
    "종목의 추천, 매수, 매도 권유가 아니라 지금의 데이터는 어디까지나 개인의 공부를 목적으로 "
    "진행되고 있는 것이며 투자의 책임은 개인에게 있습니다.",
    "실제로 공개되어있는 '내 성적표'의 데이터는 개인이 등록한 것입니다. 운영자는 '내 성적표'의 "
    "데이터를 확인, 검증하고 있지 않으며 확인, 검증을 요청하고 있지 않습니다. 주의바랍니다.",
)

#: 창유형 → 화면 이름(`duel_page.py::WINDOW_TITLES` 와 같은 라벨). 순서는 규칙 계층의
#: `ACCOUNT_WINDOW_TYPES` 를 따릅니다(§0-3-10 — 목록의 출처는 한 곳).
WINDOW_TITLES = {
    "M1": "1개월 계좌",
    "M3": "3개월 계좌",
    "M6": "6개월 계좌",
}

#: "동의하지 않아 발행되지 않은 값"을 화면에 그리는 말. **0 이나 빈칸으로 그리지 않습니다** —
#: "수익률 0%"와 "수익률 비공개"는 다른 말입니다(§0-1 / 스키마 §8 컬럼 주석).
NOT_PUBLISHED_TEXT = "비공개"

# --- 안내 문구(초안 — 7-2 오너 검토 대기) -------------------------------------
NOTICE_HOW_RANKING_WORKS = (
    "순위는 '체급'(원금 구간) 안에서 **시간가중수익률(TWR)** 로만 갈립니다. 체급은 실제 "
    "'내 성적표' 매입원가합계로 나뉘는데, 결투 시드머니는 모두 같은 금액이라 그것으로는 "
    "구분이 되지 않기 때문입니다. 체급 산정에 실제 매입총합을 쓰는 데 동의하지 않은 분들은 "
    f"'{duel_rules.BRACKET_NONE_LABEL}' 그룹에서 겨룹니다."
)

NOTICE_MIN_PARTICIPANTS = (
    f"참가자가 {duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명 이상인 그룹만 공개됩니다. "
    "사람이 적으면 닉네임만으로 누구인지 추측될 수 있어서, 인원이 모자란 그룹은 순위표를 "
    "아예 만들지 않습니다(이미 만들어져 있었더라도 지웁니다)."
)

NOTICE_DAILY = (
    "순위표는 하루 한 번, 밤에 그날치로 통째로 다시 만들어집니다. 지금 보시는 값은 화면을 "
    "여는 순간 계산한 것이 아니라 **가장 최근 발행분**입니다."
)

NOTICE_OVERLAP = (
    f"위쪽 목록은 1위부터 최대 {duel_rules.LEADERBOARD_TOP_COUNT:,}명, 아래쪽 목록은 "
    f"꼴찌부터 최대 {duel_rules.LEADERBOARD_BOTTOM_COUNT:,}명입니다. 그룹 인원이 그 둘을 "
    "합친 수보다 적으면 같은 분이 양쪽에 함께 나올 수 있습니다."
)

NOTICE_EMPTY_GROUP = (
    "아직 공개할 만큼 사람이 모이지 않았습니다. 이 그룹의 순위표는 참가자가 충분히 쌓인 "
    "뒤부터 보입니다 — 오류가 아닙니다."
)

#: 위쪽/아래쪽 두 구간의 표시 이름과 규칙 계층 상한. 화면에 숫자를 다시 적지 않습니다(§0-3-10).
SECTION_TOP = "top"
SECTION_BOTTOM = "bottom"


# =============================================================================
# 1. 순수 함수 (위젯 없이 검증할 수 있게 따로 뺐습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장(§0-3-4)."""
    return fail_message(exc, fallback, context='결투다! 순위표')


def window_options():
    """창유형 선택지 {값: 라벨}. 목록의 출처는 `duel_rules.ACCOUNT_WINDOW_TYPES` 입니다."""
    return {key: f'{WINDOW_TITLES.get(key, key)} ({key})'
            for key in duel_rules.ACCOUNT_WINDOW_TYPES}


def bracket_options():
    """
    체급 선택지 {bracket_key: 한글 라벨} — 8구간 + "구간 미적용".

    라벨은 `duel_rules.bracket_label()` 만 씁니다. 화면에 금액 경계를 다시 적으면 경계값이
    두 곳에 존재하게 되고, 언젠가 한쪽만 바뀝니다(§0-3-10).
    """
    return {key: duel_rules.bracket_label(key) for key in duel_rules.BRACKET_KEYS}


def section_cap(section):
    """구간(위/아래)의 최대 인원. 5-7 의 "상위 500 + 하위 500"."""
    if section == SECTION_TOP:
        return duel_rules.LEADERBOARD_TOP_COUNT
    if section == SECTION_BOTTOM:
        return duel_rules.LEADERBOARD_BOTTOM_COUNT
    raise DuelRuleError(f"알 수 없는 순위표 구간입니다: {section!r}")


def twr_display(value):
    """
    발행된 수익률 → 화면 문자열. **None 은 '비공개'** 입니다(0% 로 그리지 않습니다 — §0-1).

    값이 있는데 숫자로 해석되지 않으면 그것도 지어내지 않고 그대로 알립니다.
    """
    if value is None:
        return NOT_PUBLISHED_TEXT
    try:
        return pct_text(float(value))
    except (TypeError, ValueError):
        return '값 확인 필요'


def rank_text(row):
    """"12위" 형태. 순위는 발행표의 `rank` 를 **그대로** 씁니다(다시 매기지 않습니다)."""
    value = (row or {}).get("rank")
    if value is None:
        # 발행표의 rank 는 not null 이라 정상적으로는 올 수 없는 상태입니다. 조용히 빈칸으로
        # 두지 않고 그렇게 표시합니다(§0-1).
        return '순위 없음'
    return f'{value}위'


def holding_row_cells(row):
    """
    공개 보유종목 한 행 → 표 셀 5개. 동의하지 않은 항목(null)은 **"비공개"** 로 그립니다.

    🔐 §0-3-9 — 종목명은 배치가 넣은 값이지만 예외 없이 `esc()` 를 거칩니다.
    """
    data = dict(row or {})
    ticker = str(data.get("ticker") or "")
    name = data.get("stock_name") or ticker
    quantity = data.get("quantity")
    buy_amount = data.get("buy_amount")
    return [
        (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
         f'{esc(str(name))}<br>({esc(ticker)})</div>'),
        esc(f'{float(quantity):,.6g}주' if quantity is not None else NOT_PUBLISHED_TEXT),
        esc(format_amount(buy_amount, "KRW") if buy_amount is not None else NOT_PUBLISHED_TEXT),
    ]


def holdings_table(rows):
    """공개 보유종목 표 HTML. 행이 없으면 None(호출부가 안내 문구를 대신 그립니다)."""
    body = [holding_row_cells(row) for row in rows or []]
    if not body:
        return None
    return holdings_table_html(['종목', '수량', '매입금액'], body)


# =============================================================================
# 2. 페이지 (공개 플래그 게이트 → 고정 문구 → 로그인 게이트)
# =============================================================================
# 🔴 2026-08-21 — `async def` + `response_timeout` 이 붙었습니다.
#    NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 발행일
#    조회 + 위/아래 두 구간 조회가 순서대로 일어나므로 느린 날에는 3초를 넘길 수 있고,
#    그러면 화면 대신 **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반). 값의 근거는
#    `web/state.PAGE_RESPONSE_TIMEOUT_SECONDS` 주석에 적어 뒀습니다.
@ui.page('/duel/leaderboard', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def duel_leaderboard_page() -> None:
    with layout('⚔️ 결투다! — 공개 순위표', width_class='max-w-6xl'):
        ui.markdown('## 🏆 내 밑으로 눈 깔어 — 공개 순위표')

        if not (DUEL_ENABLED and DUEL_LEADERBOARD_ENABLED):
            _render_coming_soon()
            return
        if DUEL_LEADERBOARD_MENU_ADMIN_ONLY and not is_admin():
            _render_coming_soon()
            return

        # 🔴 5-3 고정 문구 — **본문 맨 위, 로그인 폼보다도 위**. 이 화면에서 무엇을 보든
        #    이 두 문단을 먼저 보게 됩니다(스크롤 없이 보이는 위치).
        _render_fixed_notice()

        status = supabase_status()
        if not status.available:
            warning_banner(f'🚧 공개 순위표는 아직 준비중입니다.\n\n사유: {status.reason}')
            return

        # ── 로그인 게이트 ────────────────────────────────────────────────────
        #    비로그인 접근 불가 — 발행표의 RLS 도 `authenticated` 에게만 select 를
        #    허용합니다(스키마 §9-7). 화면과 DB 가 같은 방향으로 막습니다.
        if not has_supabase_session():
            info_banner('🔒 공개 순위표는 로그인한 이용자에게만 보입니다. 먼저 로그인해 주세요.')
            render_auth()
            return

        # 🔴 2026-08-21 — 세션 확인 두 단계를 **한 try 안**으로 모았습니다. 둘 다 Supabase
        #    왕복이라 "요청이 중단됨"으로 실패할 수 있는데, 그 실패를 "로그인 만료"로
        #    오해해 멀쩡한 토큰을 지워버리면 안 되기 때문입니다(§0-1).
        try:
            client = await get_client_async()
            if client is None:
                warning_banner('🚧 공개 순위표는 아직 준비중입니다(로그인 연결이 준비되지 않았습니다).')
                return
            user = await current_user_async(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return

        if not user_id_of(user):
            await logout_async()
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        try:
            await _render_body(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "순위표를 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_coming_soon() -> None:
    warning_banner(
        '🚧 공개 순위표는 아직 준비중입니다.\n\n'
        '참가자가 충분히 모이면 열립니다. 그때까지 누구의 성적도 공개되지 않습니다.'
    )


def _render_fixed_notice() -> None:
    """🔴 5-3 고정 문구 두 문단. **글자 그대로**, 크게, 맨 위에."""
    with ui.card().classes('vh-card w-full'):
        for paragraph in FIXED_NOTICE_PARAGRAPHS:
            ui.label(paragraph).classes('text-base vh-keep-all')


# =============================================================================
# 3. 로그인 후 본문 — 그룹 고르기 → 순위표
# =============================================================================
async def _render_body(client) -> None:
    """
    창유형 · 체급을 고르면 그 그룹의 순위표를 그립니다.

    🔴 2026-08-21 — 공개 순위표 조회 3종(`fetch_public_leaderboard_latest_date` /
       `fetch_public_leaderboard` / `fetch_public_holdings_for_nickname`)을
       `run_blocking()` 으로 별도 스레드에 넘깁니다. 전부 Supabase 로 **동기 HTTP 왕복**을
       하고, 그룹을 바꾸거나 페이지를 넘길 때마다 다시 불립니다. 그동안 이벤트 루프가
       멈추면 **다른 화면을 보던 접속자까지** 함께 끊깁니다(`web/blocking.py` 독스트링).

    ⚠️ 선택 값과 페이지 번호는 **이 함수 안의 지역 변수**입니다. 모듈 전역에 두면 접속자
       끼리 화면 상태가 섞입니다(§0-3-8 — 순위표는 사용자 데이터가 아니지만, "다른 사람이
       페이지를 넘기면 내 화면이 바뀌는" 것 자체가 같은 종류의 사고입니다).
    """
    ui.label(NOTICE_HOW_RANKING_WORKS).classes('vh-muted')
    ui.label(NOTICE_MIN_PARTICIPANTS).classes('vh-muted')
    ui.label(NOTICE_DAILY).classes('vh-muted')

    windows = window_options()
    brackets = bracket_options()
    # 지역 상태(접속마다 별개). 값은 "지금 무엇을 보고 있는가"뿐이고 사용자 데이터가 아닙니다.
    view = {
        "window_type": next(iter(windows)),
        "bracket_key": next(iter(brackets)),
        SECTION_TOP: 0,
        SECTION_BOTTOM: 0,
    }

    def _changed(_event=None) -> None:
        view["window_type"] = window_select.value
        view["bracket_key"] = bracket_select.value
        view[SECTION_TOP] = 0                      # 그룹이 바뀌면 페이지는 처음으로
        view[SECTION_BOTTOM] = 0
        group_section.refresh()

    with ui.row().classes('w-full gap-4 items-end'):
        # `on_change=` 생성자 인자는 `duel_page.py::_render_order_form()` 이 이미 쓰는
        # 방식 그대로입니다(§0-3-10 — 화면마다 다른 이벤트 배선 관례를 만들지 않습니다).
        window_select = ui.select(windows, value=view["window_type"], label='계좌 유형',
                                  on_change=_changed).style('flex: 1 1 200px;')
        bracket_select = ui.select(brackets, value=view["bracket_key"],
                                   label='체급(원금 구간)',
                                   on_change=_changed).style('flex: 1 1 260px;')

    # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
    #    직접 부를 때는 `await`, 위 `_changed()` 안의 `.refresh()` 는 동기 호출 그대로입니다.
    @ui.refreshable
    async def group_section() -> None:
        await _render_group(client, view, group_section.refresh)

    await group_section()


async def _render_group(client, view: dict, on_changed) -> None:
    """한 그룹(창유형 × 체급)의 순위표. 발행일을 **먼저 한 번** 확정하고 시작합니다."""
    window_type = view["window_type"]
    bracket_key = view["bracket_key"]
    try:
        published_date = await run_blocking(
            fetch_public_leaderboard_latest_date,
            client, window_type=window_type, bracket_key=bracket_key)
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "순위표를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    ui.markdown(
        f'#### {esc(WINDOW_TITLES.get(window_type, str(window_type)))} · '
        f'{esc(duel_rules.bracket_label(bracket_key))}'
    )

    if not published_date:
        # 🔴 정상 상태입니다(오류 아님). 참가자가 없거나, 최소 인원 미달이라 발행되지
        #    않았거나, 발행됐다가 인원이 줄어 지워진 경우 — 셋을 구분해 보여주지 않습니다
        #    (구분 자체가 "이 구간에 몇 명쯤 있는지"의 힌트가 되기 때문 — 5-6).
        info_banner(f'ℹ️ {NOTICE_EMPTY_GROUP}')
        return

    ui.label(f'📅 {published_date} 발행분').classes('vh-muted')
    ui.label(NOTICE_OVERLAP).classes('vh-muted')

    await _render_section(client, view, published_date, SECTION_TOP, on_changed)
    ui.separator()
    await _render_section(client, view, published_date, SECTION_BOTTOM, on_changed)


async def _render_section(client, view: dict, published_date: str, section: str, on_changed) -> None:
    """
    위쪽(1위부터) 또는 아래쪽(꼴찌부터) 한 페이지.

    ⚠️ "몇 명인지"를 세는 질의는 보내지 않습니다. 아래쪽 목록은 정렬을 뒤집어 읽고 화면에서
       다시 뒤집습니다 — 인원을 세려면 방문마다 전체를 훑어야 하고, 그게 §0-3-2 가 막는
       모양입니다. 대신 마지막 페이지인지는 "돌아온 행 수 < 요청한 수"로 판정합니다.
    """
    cap = section_cap(section)
    page_index = view[section]
    offset, limit = duel_rules.leaderboard_page_bounds(page_index, section_cap=cap)

    title = (f'#### 🔼 위에서부터 (최대 {cap:,}명)' if section == SECTION_TOP
             else f'#### 🔽 아래에서부터 (최대 {cap:,}명)')
    ui.markdown(title)

    if limit <= 0:
        # 구간 상한을 넘어간 페이지 — 질의 자체를 보내지 않습니다.
        info_banner('ℹ️ 이 구간에서 보여드릴 수 있는 마지막 페이지를 넘었습니다.')
        _render_pager(view, section, page_index, has_next=False, on_changed=on_changed)
        return

    try:
        rows = await run_blocking(
            fetch_public_leaderboard,
            client, window_type=view["window_type"], bracket_key=view["bracket_key"],
            published_date=published_date, limit=limit, offset=offset,
            order_desc=(section == SECTION_BOTTOM),
        )
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "순위표를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    if not rows:
        info_banner('ℹ️ 이 페이지에는 표시할 참가자가 없습니다.')
        _render_pager(view, section, page_index, has_next=False, on_changed=on_changed)
        return

    # 아래쪽 목록은 꼴찌부터 읽어 왔으므로, 화면에서는 순위가 올라가는 방향으로 뒤집어
    # 보여줍니다(읽는 사람에게는 "…998위, 999위, 1000위" 가 자연스럽습니다).
    display_rows = list(rows) if section == SECTION_TOP else list(reversed(rows))
    for row in display_rows:
        _render_participant(client, published_date, view["window_type"], row)

    _render_pager(view, section, page_index, has_next=len(rows) >= limit,
                  on_changed=on_changed)


def _render_participant(client, published_date: str, window_type: str, row: dict) -> None:
    # (이 함수 자체는 위젯만 만듭니다 — 조회는 아래 `_open()` 을 눌렀을 때만 일어납니다.)
    """
    순위표 한 줄. 펼치면 그 닉네임의 **공개된** 보유종목을 개별 열람합니다(5-2).

    보유종목은 **펼칠 때 처음 읽습니다.** 페이지를 여는 것만으로 30명분 상세를 미리 읽으면
    그게 §0-3-2 가 막는 모양이고, 대부분의 방문자는 몇 명만 펼쳐 봅니다.
    """
    nickname = str((row or {}).get("nickname") or '')
    header = f'{rank_text(row)} · {nickname} · 수익률 {twr_display((row or {}).get("twr_pct"))}'

    with ui.card().classes('vh-card w-full'):
        # 이 행 하나만의 지역 상태(접속마다·행마다 별개 — 모듈 전역에 두지 않습니다).
        slot = {"body": None, "loaded": False}

        async def _open(_event=None) -> None:
            # 🔴 2026-08-21 — `async def`. 펼칠 때 Supabase 왕복이 일어나므로 이 처리기도
            #    이벤트 루프를 붙잡으면 안 됩니다. NiceGUI 는 `on_click` 에 코루틴 함수를
            #    그대로 받아 줍니다.
            if slot["loaded"] or slot["body"] is None:
                return
            slot["loaded"] = True                  # 두 번 눌러도 두 번 읽지 않습니다
            with slot["body"]:
                await _render_holdings(client, published_date, window_type, nickname)

        with ui.row().classes('no-wrap items-center gap-2 w-full'):
            ui.label(header).classes('flex-1 min-w-0 vh-keep-all')
            ui.button('📄 보유종목 보기', on_click=_open) \
                .props('flat dense no-caps').classes('shrink-0')
        slot["body"] = ui.column().classes('w-full gap-1')


async def _render_holdings(client, published_date: str, window_type: str, nickname: str) -> None:
    """한 참가자의 공개 보유종목 표(없으면 그 사실을 그대로 알립니다)."""
    if not nickname:
        error_banner('🚫 닉네임을 확인하지 못해 보유종목을 불러오지 않았습니다.')
        return
    try:
        rows = await run_blocking(
            fetch_public_holdings_for_nickname,
            client, nickname, published_date=published_date, window_type=window_type)
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "보유종목을 불러오지 못했습니다.")}')
        return

    table = holdings_table(rows)
    if table is None:
        # 행이 아예 없는 것은 "보유종목을 공개하지 않았다" 또는 "아직 아무것도 사지 않았다"
        # 입니다. 둘 중 무엇인지 이 표만 보고는 알 수 없으므로 **단정하지 않습니다**(§0-1).
        ui.label(
            '이 참가자의 보유종목은 공개되어 있지 않거나, 아직 보유한 종목이 없습니다.'
        ).classes('vh-muted')
        return
    ui.html(table).classes('w-full')
    ui.label(
        f'※ "{NOT_PUBLISHED_TEXT}" 로 표시된 항목은 그 참가자가 공개에 동의하지 않은 값입니다 '
        '— 0 이라는 뜻이 아닙니다.'
    ).classes('vh-muted')


def _render_pager(view: dict, section: str, page_index: int, *, has_next: bool,
                  on_changed) -> None:
    """
    이전/다음 버튼. 페이지 번호는 **이 접속의 지역 상태**(`view`)에만 있습니다.

    누를 수 없는 방향의 버튼은 비활성으로 두지 않고 **아예 그리지 않습니다** — 눌러도
    아무 일이 없는 버튼보다 없는 편이 덜 헷갈리고, 화면 상태 판정이 한 곳(여기)에만
    남습니다.
    """
    max_pages = duel_rules.leaderboard_page_count(section_cap(section))

    def _go(delta):
        def _handler(_event=None) -> None:
            view[section] = max(0, page_index + delta)
            on_changed()
        return _handler

    with ui.row().classes('items-center gap-2'):
        if page_index > 0:
            ui.button('◀ 이전', on_click=_go(-1)).props('flat dense no-caps')
        ui.label(f'{page_index + 1} / 최대 {max_pages} 페이지').classes('vh-muted')
        if has_next and page_index + 1 < max_pages:
            ui.button('다음 ▶', on_click=_go(1)).props('flat dense no-caps')
