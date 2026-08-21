# tests/test_duel_leaderboard_page_usd.py
"""
💵 "결투다!" — **달러 결투(USD 트랙) 공개 순위표 화면** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요)

`DUEL_MODULE_WORK_ORDER.md` §5-3(고정 문구·체급) · §5-7(상위/하위 500) ·
§5-11-9(**한국장/미국장 완전 별개 표, 절대 병합·비교 금지**) · §5-19(이 라운드)가
`web/pages/duel_leaderboard_page.py` 에서 실제로 지켜지는지 회귀로 고정합니다.

⚠️ **이 파일이 지키려는 사고는 전부 "조용히 틀리는" 종류입니다.**

     ① 🔴 **금액 통화** — 예전 코드에는 `format_amount(buy_amount, "KRW")` 로 통화가 본문에
        박혀 있었습니다. 그대로 뒀다면 달러 보유종목의 매입금액이 **"1,234원"** 으로
        찍힙니다. 예외도 로그도 나지 않고 사용자에게만 틀린 값이 보이는, 이 라운드에서
        가장 놓치기 쉬운 자리입니다(§0-1).
     ② 🔴 **표 혼선** — 통화를 달러로 골랐는데 원화 발행표를 읽으면, 화면 제목은 달러인데
        내용은 원화입니다. 두 트랙은 배치 시각도 휴장일도 달라서 "그럴듯하게" 보입니다.
     ③ 🔴 **체급 목록 오분기** — 원화 체급 키(`krw_…`)와 달러 체급 키(`usd_…`)는 하나도
        겹치지 않습니다. 짝을 잘못 맞추면 라벨 함수가 예외를 냅니다(그게 맞는 동작이고,
        그래서 목록과 라벨을 **한 곳에서 함께** 고릅니다).
     ④ 🔴 **병합 금지** — 두 통화의 순위·수익률을 한 화면에서 합치거나 비교하는 자리가
        하나도 없어야 합니다(5-11-9 — 환율 시계열이 없으므로 그 비교는 지어낸 값입니다).
     ⑤ 🔴 **§0-3-8** — 발행표에는 `user_id`·`account_id` 컬럼 자체가 없고, USD 읽기 함수도
        `select("*")` 를 쓰지 않습니다(컬럼이 늘어도 화면으로 새어나가지 않는 구조).
     ⑥ 🔴 **원화 회귀** — 통화 선택기가 하나 늘어난 것 말고, 원화를 고른 화면이 예전과
        같은 표·같은 질의 수로 도는가.

⚠️ 여기서 **검증하지 못하는 것**(§0-1): 실제 브라우저 렌더링, 실제 Supabase RLS.

실행: pytest tests/test_duel_leaderboard_page_usd.py -v
"""

import ast
import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))          # from test_duel_db import FakeClient

from test_duel_db import FakeClient                                      # noqa: E402
from utils import duel_db, duel_db_usd, duel_rules                       # noqa: E402
from utils.duel_rules import DuelRuleError                               # noqa: E402
from utils.scorecard_db import CURRENCY_KRW, CURRENCY_USD                # noqa: E402

from web.pages import duel_leaderboard_page as board_page                # noqa: E402

PAGE_PATH = REPO_ROOT / "web" / "pages" / "duel_leaderboard_page.py"
PAGE_SRC = PAGE_PATH.read_text(encoding="utf-8")
PAGE_TREE = ast.parse(PAGE_SRC)
WORK_ORDER = (REPO_ROOT / "DUEL_MODULE_WORK_ORDER.md").read_text(encoding="utf-8")


# =============================================================================
# 0. 도우미 — 소스 구조 / 비동기 실행 / 가짜 발행표
# =============================================================================
def _functions():
    found = {}
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


FUNCTIONS = _functions()


def _names_used(node):
    """함수 본문에서 쓰인 이름(변수·함수·속성)의 집합 — `run_blocking(fn, …)` 도 잡힙니다."""
    used = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.add(child.attr)
    return used


def _executable_constants(node):
    """함수 안의 **독스트링을 뺀** 문자열 상수 집합.

    이 저장소는 근거를 독스트링에 길게 적는 관례라, 문자열 리터럴을 전부 세면 "설명을 잘
    쓸수록 검사가 실패"합니다 — 그건 검사가 잘못된 것이지 코드가 잘못된 게 아닙니다
    (`tests/test_duel_public_ui.py::_code_strings()` 와 같은 판단).
    """
    docstring = ast.get_docstring(node, clean=False)
    return {child.value for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
            and child.value != docstring}


def _run(coro):
    """비동기 화면 함수를 끝까지 실행합니다(NiceGUI 슬롯 컨텍스트를 새 태스크에 넘겨서)."""
    try:
        from nicegui import context as nicegui_context
        from nicegui.slot import Slot, get_task_id
    except ImportError:                              # 스텁 환경(nicegui 미설치)
        return asyncio.run(coro)

    outer = list(nicegui_context.slot_stack)

    async def _main():
        Slot.stacks[get_task_id()] = list(outer)
        try:
            return await coro
        finally:
            Slot.stacks.pop(get_task_id(), None)

    return asyncio.run(_main())


def _patch(module, **replacements):
    saved = {name: getattr(module, name) for name in replacements}
    for name, value in replacements.items():
        setattr(module, name, value)
    return saved


def _restore(module, saved):
    for name, value in saved.items():
        setattr(module, name, value)


def _board_rows(bracket_key):
    return [{"published_date": "2026-08-20", "window_type": "M1", "bracket_key": bracket_key,
             "rank": rank, "nickname": f"닉네임{rank}",
             "twr_pct": None if rank == 2 else 5.5 - rank}
            for rank in (1, 2, 3)]


def _detail_rows(nickname="닉네임1"):
    return [{"published_date": "2026-08-20", "window_type": "M1", "nickname": nickname,
             "ticker": "AAPL", "stock_name": "<img src=x onerror=alert(1)>",
             "quantity": 3, "buy_amount": 612.5}]


def _both_tracks_client():
    """원화·달러 **양쪽** 발행표에 데이터가 있는 가짜 클라이언트.

    한쪽만 채우면 "잘못된 표를 읽었는데 빈 결과라 아무 일도 없었다"가 되어 검사가
    사라집니다 — 그래서 양쪽 다 채우고, **어느 표에 갔는지**를 봅니다.
    """
    return FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"):
            lambda query: ([{"published_date": "2026-08-20"}]
                           if query.options.get("limit") == 1
                           else _board_rows(duel_rules.BRACKET_KEYS[0])),
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"):
            lambda query: ([{"published_date": "2026-08-19"}]
                           if query.options.get("limit") == 1
                           else _board_rows(duel_rules.BRACKET_KEYS_USD[0])),
        (duel_db.PUBLIC_HOLDINGS_TABLE, "select"): _detail_rows(),
        (duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "select"): _detail_rows(),
    })


# =============================================================================
# 1. 통화 선택기 — 있는가, 기본값은 원화인가, 새 URL 을 만들지 않았는가
# =============================================================================
def test_currency_options_offer_exactly_two_tracks_with_krw_first():
    options = board_page.currency_options()
    assert list(options) == [CURRENCY_KRW, CURRENCY_USD], options
    assert "원화" in options[CURRENCY_KRW] and "달러" in options[CURRENCY_USD]


def test_currency_codes_come_from_the_single_source():
    """§0-3-10 — 화면이 "KRW"/"USD" 문자열을 새로 정의하지 않습니다."""
    from utils import scorecard_db
    assert board_page.CURRENCY_KRW is scorecard_db.CURRENCY_KRW
    assert board_page.CURRENCY_USD is scorecard_db.CURRENCY_USD


def test_the_screen_has_a_currency_select_wired_to_its_own_handler():
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_body"])
    assert "currency_select = ui.select(" in src
    assert "on_change=_currency_changed" in src
    # 창유형·체급 선택기도 그대로 남아 있어야 합니다(총 3개).
    assert src.count("ui.select(") == 3, "선택기가 3개(통화·창유형·체급)여야 합니다."


def test_page_route_is_still_exactly_one_url_and_flags_are_shared():
    """§5-19 설계 결정 1번 — 새 URL 도, 통화별 새 플래그도 만들지 않았습니다."""
    routes = [
        deco.args[0].value
        for node in ast.walk(PAGE_TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for deco in node.decorator_list
        if isinstance(deco, ast.Call) and getattr(deco.func, "attr", None) == "page"
        and deco.args and isinstance(deco.args[0], ast.Constant)
    ]
    assert routes == ["/duel/leaderboard"], routes
    assert "DUEL_LEADERBOARD_ENABLED" in PAGE_SRC
    for forbidden in ("DUEL_LEADERBOARD_USD_ENABLED", "DUEL_USD_LEADERBOARD_ENABLED"):
        assert forbidden not in PAGE_SRC, f"통화별 새 플래그 {forbidden} 가 생겼습니다."


# =============================================================================
# 2. 🔴 체급 목록 — 원화와 달러가 **하나도 겹치지 않습니다**
# =============================================================================
def test_usd_bracket_options_come_from_the_usd_rule_layer():
    options = board_page.bracket_options_usd()
    assert list(options) == list(duel_rules.BRACKET_KEYS_USD)
    assert len(options) == len(duel_rules.BRACKET_TIERS_USD) + 1     # 8구간 + 구간 미적용
    assert options[duel_rules.BRACKET_NONE_KEY] == duel_rules.BRACKET_NONE_LABEL
    for key, label in options.items():
        assert label == duel_rules.bracket_label_usd(key)


def test_krw_and_usd_bracket_keys_never_overlap_except_no_bracket():
    """
    '구간 미적용'만 공유합니다(통화 무관 개념 — 5-13). 나머지는 하나도 안 겹쳐야
    "옛 선택값을 그대로 들고 통화를 바꾸는" 사고가 **조용히** 지나가지 않습니다.
    """
    krw = set(duel_rules.BRACKET_KEYS)
    usd = set(duel_rules.BRACKET_KEYS_USD)
    assert krw & usd == {duel_rules.BRACKET_NONE_KEY}


def test_krw_bracket_label_rejects_a_usd_key_loudly():
    """짝을 잘못 맞추면 조용히 틀린 라벨이 아니라 **예외**입니다(§0-1)."""
    with pytest.raises(DuelRuleError):
        duel_rules.bracket_label(duel_rules.BRACKET_KEYS_USD[0])
    with pytest.raises(DuelRuleError):
        duel_rules.bracket_label_usd(duel_rules.BRACKET_KEYS[0])


def test_window_options_are_reused_because_the_window_list_is_currency_free():
    """창유형은 통화 무관이라 `window_options()` 하나만 씁니다(`_usd` 판 없음)."""
    assert list(board_page.window_options()) == list(duel_rules.ACCOUNT_WINDOW_TYPES)
    assert not hasattr(board_page, "window_options_usd")
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["window_options"])
    for literal in ("KRW", "USD", "원화", "달러"):
        assert literal not in src, f"window_options() 본문에 통화 리터럴 {literal} 이 있습니다."


def test_changing_currency_resets_the_bracket_selection_to_the_new_list():
    """
    🔴 통화가 바뀌면 체급 목록 자체가 통째로 바뀝니다. 옛 값을 들고 가면 라벨 함수가
    예외를 냅니다 — 그래서 새 목록의 첫 항목으로 리셋합니다(비슷한 구간을 골라 주지
    않습니다, §0-1).
    """
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_currency_changed"])
    assert "track_readers(view[\"currency\"])" in src
    assert "set_options" in src
    assert "next(iter(new_brackets))" in src
    assert "SECTION_TOP" in src and "SECTION_BOTTOM" in src, "페이지도 처음으로 되돌립니다."


def test_switching_currency_yields_a_key_the_new_label_function_accepts():
    """
    통화 전환의 **결과**를 실제 객체로 확인합니다(위 검사는 소스 모양만 봅니다).
    새 목록의 첫 키는 새 라벨 함수가 받아들이고, 옛 키를 그대로 들고 가면 예외입니다 —
    즉 리셋을 빼먹으면 화면이 조용히 틀리는 게 아니라 **그 자리에서 멈춥니다**.
    """
    for source, target in ((CURRENCY_KRW, CURRENCY_USD), (CURRENCY_USD, CURRENCY_KRW)):
        stale_key = next(iter(board_page.track_readers(source)["brackets"]))
        readers = board_page.track_readers(target)
        fresh_key = next(iter(readers["brackets"]))
        assert readers["bracket_label"](fresh_key)
        with pytest.raises(DuelRuleError):
            readers["bracket_label"](stale_key)


def test_the_select_widget_really_supports_swapping_its_options():
    """`set_options(options, value=…)` 가 이 NiceGUI 판에서 실제로 도는지(API 계약 확인).

    ⚠️ 처리기 자체(`_currency_changed`)는 페이지 함수 안의 지역 클로저라 여기서 직접 부를
       수 없습니다. 그래서 **그 처리기가 의지하는 위젯 API** 만 실물로 확인합니다(§0-1 —
       확인한 것만 확인했다고 말합니다).
    """
    ui = pytest.importorskip("nicegui").ui
    krw_options = board_page.bracket_options()
    select = ui.select(krw_options, value=next(iter(krw_options)), label='체급')
    usd_options = board_page.bracket_options_usd()
    select.set_options(usd_options, value=next(iter(usd_options)))
    assert select.options == usd_options
    assert select.value == next(iter(usd_options))


# =============================================================================
# 3. 🔴 `track_readers()` — 통화마다 다른 것이 모여 있는 단 하나의 자리
# =============================================================================
def test_krw_bundle_contains_only_krw_functions():
    bundle = board_page.track_readers(CURRENCY_KRW)
    assert bundle["latest_date"] is duel_db.fetch_public_leaderboard_latest_date
    assert bundle["page_rows"] is duel_db.fetch_public_leaderboard
    assert bundle["detail_rows"] is duel_db.fetch_public_holdings_for_nickname
    assert bundle["bracket_label"] is duel_rules.bracket_label
    assert bundle["amount"] == CURRENCY_KRW


def test_usd_bundle_contains_only_usd_functions():
    bundle = board_page.track_readers(CURRENCY_USD)
    assert bundle["latest_date"] is duel_db_usd.fetch_public_leaderboard_latest_date_usd
    assert bundle["page_rows"] is duel_db_usd.fetch_public_leaderboard_usd
    assert bundle["detail_rows"] is duel_db_usd.fetch_public_holdings_for_nickname_usd
    assert bundle["bracket_label"] is duel_rules.bracket_label_usd
    assert bundle["amount"] == CURRENCY_USD


def test_the_two_bundles_share_no_callable_at_all():
    """🔴 한 객체라도 겹치면 그 자리로 두 트랙이 섞입니다(5-11-9)."""
    krw = board_page.track_readers(CURRENCY_KRW)
    usd = board_page.track_readers(CURRENCY_USD)
    for key in ("latest_date", "page_rows", "detail_rows", "bracket_label", "amount"):
        assert krw[key] is not usd[key], f"'{key}' 가 두 트랙에서 같은 객체입니다."
    assert set(krw["brackets"]) & set(usd["brackets"]) == {duel_rules.BRACKET_NONE_KEY}


def test_unknown_currency_is_refused_not_defaulted():
    """§0-1 — 모르는 통화를 원화로 때우면 **남의 트랙 표**를 읽게 됩니다."""
    for bad in ("", None, "JPY", "krw", "usd "):
        with pytest.raises(DuelRuleError):
            board_page.track_readers(bad)


def test_the_usd_publish_tables_are_physically_separate():
    assert duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD == "duel_public_leaderboard_usd"
    assert duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD == "duel_public_holdings_usd"
    assert duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD != duel_db.PUBLIC_LEADERBOARD_TABLE
    assert duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD != duel_db.PUBLIC_HOLDINGS_TABLE


# =============================================================================
# 4. 🔴 금액 서식 — 달러 매입금액에 "원"이 찍히면 안 됩니다 (이 라운드 최대 함정)
# =============================================================================
def test_usd_buy_amount_is_formatted_in_dollars_not_won():
    cells = board_page.holding_row_cells(
        {"ticker": "AAPL", "stock_name": "Apple Inc.", "quantity": 3, "buy_amount": 612.5},
        CURRENCY_USD)
    assert "$612.50" in cells[2], cells[2]
    assert "원" not in cells[2], (
        "달러 보유종목의 매입금액이 '원'으로 표시됩니다 — 예전 하드코딩된 \"KRW\" 가 "
        "남아 있는 자리입니다(§0-1)."
    )


def test_krw_formatting_is_unchanged_when_the_currency_is_omitted():
    """회귀 — 인자를 생략하면 2026-08-21 이전과 **완전히 같은** 원화 표기."""
    cells = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 10, "buy_amount": 700000})
    assert cells[2].endswith("원"), cells[2]
    assert "700,000원" in cells[2]
    explicit = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 10, "buy_amount": 700000},
        CURRENCY_KRW)
    assert cells == explicit


def test_the_currency_reaches_the_table_builder():
    html_usd = board_page.holdings_table(_detail_rows(), CURRENCY_USD)
    html_krw = board_page.holdings_table(
        [{"ticker": "005930", "stock_name": "삼성전자", "quantity": 1, "buy_amount": 1000}])
    assert "$612.50" in html_usd and "원" not in html_usd.split("612")[-1]
    assert "1,000원" in html_krw


def test_private_fields_stay_private_in_both_currencies():
    """§0-1 — "비공개"와 "0"은 다른 말입니다(통화를 붙였다고 0 이 되면 안 됩니다)."""
    for currency in (CURRENCY_KRW, CURRENCY_USD):
        cells = board_page.holding_row_cells(
            {"ticker": "AAPL", "stock_name": "Apple", "quantity": None, "buy_amount": None},
            currency)
        assert cells[1] == board_page.NOT_PUBLISHED_TEXT
        assert cells[2] == board_page.NOT_PUBLISHED_TEXT


def test_stock_names_are_escaped_in_the_usd_path_too():
    """🔐 §0-3-9 — 이스케이프 경로가 통화마다 갈리지 않았는지(그래서 함수를 복제하지 않음)."""
    html = board_page.holdings_table(_detail_rows(), CURRENCY_USD)
    assert "<img src=x onerror=" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_holdings_table_was_not_duplicated_per_currency():
    """
    통화에 걸린 것이 `format_amount()` 인자 하나뿐이라 **인자로 갈랐습니다.** 복제하면
    XSS 이스케이프 경로가 두 개가 되어 한쪽만 고치는 순간 조용히 뚫립니다.
    """
    for name in ("holding_row_cells_usd", "holdings_table_usd"):
        assert not hasattr(board_page, name), f"{name}() 가 생겼습니다 — 이스케이프 경로가 둘입니다."
    # ⚠️ 독스트링은 걷어내고 **실행되는 코드만** 봅니다 — 이 저장소는 근거를 독스트링에 길게
    #    적는 관례라, 문자열까지 세면 "설명을 잘 쓸수록 검사가 실패"합니다
    #    (`tests/test_duel_public_ui.py::_code_strings()` 와 같은 판단).
    assert "KRW" not in _executable_constants(FUNCTIONS["holding_row_cells"]), (
        "통화가 아직 본문에 박혀 있습니다 — 달러 금액에 '원'이 찍히는 자리입니다."
    )


# =============================================================================
# 5. 🔴 발행표 격리 — 고른 통화의 표에만 질의가 갑니다 (5-11-9)
# =============================================================================
def _render_with_currency(currency):
    """`_render_body()` 를 실제로 돌리되, 통화만 바꿔 첫 화면을 그립니다.

    통화 선택기의 기본값은 원화라서, 달러 화면은 `currency_options()` 의 순서를 바꿔
    (= 첫 항목을 달러로) 그립니다 — 처리기(`_currency_changed`)를 흉내내는 것보다
    실제 코드 경로를 그대로 태우는 쪽이 검사로서 정직합니다.
    """
    client = _both_tracks_client()
    options = {currency: board_page.CURRENCY_TITLES[currency]}
    saved = _patch(board_page, currency_options=lambda: dict(options))
    try:
        _run(board_page._render_body(client))
    finally:
        _restore(board_page, saved)
    return client


def test_selecting_usd_reads_only_the_usd_publish_tables():
    client = _render_with_currency(CURRENCY_USD)
    tables = {call.table for call in client.calls}
    assert tables == {duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD}, tables
    assert duel_db.PUBLIC_LEADERBOARD_TABLE not in tables, (
        "달러를 골랐는데 원화 발행표를 읽었습니다(5-11-9 정면 위반)."
    )
    assert {call.op for call in client.calls} == {"select"}, "읽기 경로는 select 뿐입니다."


def test_selecting_krw_reads_only_the_krw_publish_tables():
    client = _render_with_currency(CURRENCY_KRW)
    tables = {call.table for call in client.calls}
    assert tables == {duel_db.PUBLIC_LEADERBOARD_TABLE}, tables
    assert duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD not in tables


def test_one_render_never_queries_both_currencies():
    """🔴 한 요청에 두 통화가 섞이지 않는지 — 질의 개수까지 예전과 같습니다(§0-3-2)."""
    for currency in (CURRENCY_KRW, CURRENCY_USD):
        client = _render_with_currency(currency)
        assert len(client.calls) == 3, (
            f"{currency}: 발행일 1 + 위쪽 1 + 아래쪽 1 = 3개여야 합니다: "
            f"{[(c.table, c.options) for c in client.calls]}"
        )


def test_usd_group_uses_the_usd_bracket_filter():
    """달러 화면의 질의가 **달러 체급 키**로 걸러 읽는지(원화 키를 보내면 항상 빈 결과)."""
    client = _render_with_currency(CURRENCY_USD)
    call = client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select")[0]
    assert call.filter_map["bracket_key"] == duel_rules.BRACKET_KEYS_USD[0]
    assert call.filter_map["bracket_key"] not in duel_rules.BRACKET_KEYS


def test_expanding_a_usd_participant_reads_the_usd_holdings_table():
    """펼치기 경로도 통화를 따라갑니다(§0-3-2 — 펼칠 때 처음 읽습니다)."""
    client = _both_tracks_client()
    readers = board_page.track_readers(CURRENCY_USD)
    _run(board_page._render_holdings(client, "2026-08-19", "M1", "닉네임1", readers))

    tables = {call.table for call in client.calls}
    assert tables == {duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD}, tables
    call = client.only_call(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "select")
    assert call.filter_map == {"nickname": "닉네임1", "published_date": "2026-08-19",
                               "window_type": "M1"}


def test_the_readers_bundle_is_threaded_through_instead_of_being_re_picked():
    """
    통화를 여러 곳에서 따로 고르면 그중 한 곳만 틀려도 화면이 조용히 어긋납니다
    (예: 달러 표를 읽고 원화로 서식). `_render_group()` 이 한 번 고른 뒤 **넘깁니다**.
    """
    assert "track_readers" in _names_used(FUNCTIONS["_render_group"])
    for name in ("_render_section", "_render_participant", "_render_holdings"):
        args = [a.arg for a in FUNCTIONS[name].args.args]
        assert "readers" in args, f"{name}{tuple(args)} 가 readers 를 인자로 받지 않습니다."
        assert "track_readers" not in _names_used(FUNCTIONS[name]), (
            f"{name}() 이 통화를 **다시** 고릅니다 — 고르는 자리는 한 곳뿐이어야 합니다."
        )


# =============================================================================
# 6. 🔴 5-3 고정 문구 — 화면 전체에 **딱 한 번**, 통화와 무관하게
# =============================================================================
def test_fixed_notice_is_still_verbatim_from_the_work_order():
    for paragraph in board_page.FIXED_NOTICE_PARAGRAPHS:
        assert paragraph in " ".join(WORK_ORDER.split()) or paragraph in WORK_ORDER, paragraph
    assert len(board_page.FIXED_NOTICE_PARAGRAPHS) == 2


def test_fixed_notice_is_rendered_exactly_once_and_outside_the_currency_branch():
    """
    통화를 바꿔도 이 두 문단은 **사라지지도, 두 번 그려지지도** 않아야 합니다.
    그래서 고정 문구는 통화 선택보다 위(로그인 게이트보다도 위)에서 딱 한 번 그립니다.
    """
    page_src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["duel_leaderboard_page"])
    assert page_src.count("_render_fixed_notice()") == 1
    # 통화별 렌더 함수 어디에도 고정 문구를 다시 그리는 자리가 없습니다.
    for name in ("_render_body", "_render_group", "_render_section", "_render_holdings"):
        assert "FIXED_NOTICE_PARAGRAPHS" not in _names_used(FUNCTIONS[name]), name
        assert "_render_fixed_notice" not in _names_used(FUNCTIONS[name]), name
    assert PAGE_SRC.count("def _render_fixed_notice") == 1


def test_screen_states_that_the_two_leaderboards_are_never_merged():
    notice = board_page.NOTICE_TRACKS_NEVER_MERGED
    assert "완전히 다른 표" in notice
    assert "환율" in notice, "합칠 수 없는 이유(환율 시계열 없음)를 밝혀야 합니다(§0-1)."
    assert "NOTICE_TRACKS_NEVER_MERGED" in _names_used(FUNCTIONS["_render_body"])


def test_usd_group_header_says_which_currency_and_which_bracket_basis():
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_group"])
    assert 'readers["title"]' in src, "제목에 어느 트랙인지가 안 나옵니다."
    assert "NOTICE_BRACKET_CURRENCY_USD" in src
    notice = board_page.NOTICE_BRACKET_CURRENCY_USD
    assert "달러 보유분" in notice
    assert duel_rules.BRACKET_NONE_LABEL in notice


# =============================================================================
# 7. 재사용을 주장하는 순수 함수 — 통화 리터럴이 정말 없는지 (§0-3-10)
# =============================================================================
REUSED_PURE_FUNCTIONS = ("window_options", "section_cap", "twr_display", "rank_text")


@pytest.mark.parametrize("name", REUSED_PURE_FUNCTIONS)
def test_reused_pure_functions_have_no_currency_variant_and_no_currency_literal(name):
    assert hasattr(board_page, name)
    assert not hasattr(board_page, f"{name}_usd"), (
        f"{name}_usd() 가 생겼습니다 — 이 함수는 통화 무관이라 복제할 이유가 없습니다."
    )
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
    for literal in ('"KRW"', "'KRW'", '"USD"', "'USD'", "원화", "달러", "$"):
        assert literal not in src, f"{name}() 본문에 통화 리터럴 {literal} 이 있습니다."


def test_display_helpers_behave_identically_regardless_of_track():
    """수익률·순위 표기는 통화와 무관합니다(값 자체가 %와 등수이기 때문)."""
    assert board_page.twr_display(None) == board_page.NOT_PUBLISHED_TEXT
    assert board_page.twr_display(0) != board_page.NOT_PUBLISHED_TEXT
    assert board_page.rank_text({"rank": 12}) == "12위"
    assert board_page.rank_text({}) == "순위 없음"
    assert board_page.section_cap(board_page.SECTION_TOP) == duel_rules.LEADERBOARD_TOP_COUNT
    assert board_page.section_cap(board_page.SECTION_BOTTOM) == duel_rules.LEADERBOARD_BOTTOM_COUNT


def test_pagination_and_minimum_participants_are_shared_constants():
    """상위/하위 500·페이지 크기·최소 인원은 통화 무관 — `_USD` 판이 없어야 합니다."""
    for name in ("LEADERBOARD_TOP_COUNT_USD", "LEADERBOARD_BOTTOM_COUNT_USD",
                 "LEADERBOARD_PAGE_SIZE_USD", "MIN_PARTICIPANTS_FOR_PUBLICATION_USD"):
        assert not hasattr(duel_rules, name), f"{name} 이 생겼습니다 — 통화 무관 상수입니다."
    assert duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION == 500


# =============================================================================
# 8. 🔴 §0-3-8 — 발행표에 신원 컬럼이 없고, `select("*")` 도 쓰지 않습니다
# =============================================================================
def test_usd_publish_reads_list_columns_explicitly_and_share_the_krw_column_lists():
    """
    USD 읽기 함수도 컬럼을 하나하나 적습니다(§0-3-8 — 나중에 발행표에 컬럼이 늘어도
    화면으로 새어나가지 않게). 목록 자체는 원화와 **같은 객체**를 씁니다(§0-3-10).
    """
    import inspect
    for fn in (duel_db_usd.fetch_public_leaderboard_usd,
               duel_db_usd.fetch_public_holdings_for_nickname_usd,
               duel_db_usd.fetch_public_leaderboard_latest_date_usd):
        src = inspect.getsource(fn)
        assert 'select("*")' not in src, f"{fn.__name__}() 가 select(\"*\") 를 씁니다."
    assert duel_db_usd.PUBLIC_LEADERBOARD_COLUMNS is duel_db.PUBLIC_LEADERBOARD_COLUMNS
    assert duel_db_usd.PUBLIC_HOLDINGS_COLUMNS is duel_db.PUBLIC_HOLDINGS_COLUMNS


def test_no_identity_column_can_arrive_through_the_usd_read_path():
    """발행표에는 `user_id`·`account_id` 컬럼 **자체가 없습니다**(스키마 §13-8)."""
    for columns in (duel_db.PUBLIC_LEADERBOARD_COLUMNS, duel_db.PUBLIC_HOLDINGS_COLUMNS):
        names = columns.split(",")
        for forbidden in duel_db.FORBIDDEN_PUBLISH_FIELDS:
            assert forbidden not in names, f"{forbidden} 가 화면으로 오는 컬럼 목록에 있습니다."
    assert "nickname" in duel_db.PUBLIC_LEADERBOARD_COLUMNS


def test_the_screen_never_imports_the_private_source_tables_for_either_currency():
    """
    5-4-5 — 순위표 코드 경로는 계좌·포지션·현금·동의를 **이름조차** 가져오지 않습니다.
    달러 쪽 함수가 들어오면서 그 규칙이 흐려지지 않았는지 다시 봅니다.
    """
    imported = set()
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.name)
    forbidden = {"fetch_my_accounts", "fetch_my_accounts_usd", "fetch_my_positions_usd",
                 "fetch_my_consent_usd", "save_consent_usd", "revoke_consent_usd",
                 "ensure_nickname", "opt_in_usd", "create_service_client"}
    assert not (imported & forbidden), imported & forbidden
    assert imported >= {"fetch_public_leaderboard_usd",
                        "fetch_public_leaderboard_latest_date_usd",
                        "fetch_public_holdings_for_nickname_usd"}


def test_every_publish_read_goes_through_run_blocking():
    wrapped = set()
    for node in ast.walk(PAGE_TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "run_blocking" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Subscript) and isinstance(arg.slice, ast.Constant):
                wrapped.add(arg.slice.value)
    assert {"latest_date", "page_rows", "detail_rows"} <= wrapped, wrapped


# =============================================================================
# 9. 원화 회귀 — 통화 선택기 말고는 예전 그대로 (§5-19 최우선 제약)
# =============================================================================
def test_krw_bracket_options_are_untouched():
    options = board_page.bracket_options()
    assert list(options) == list(duel_rules.BRACKET_KEYS)
    assert options[duel_rules.BRACKET_NONE_KEY] == duel_rules.BRACKET_NONE_LABEL


def test_default_view_opens_on_the_krw_track():
    """화면을 열면 예전과 같은 원화 순위표가 먼저 보입니다(기본값 변경 없음)."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_body"])
    assert "default_currency = next(iter(currencies))" in src
    assert list(board_page.currency_options())[0] == CURRENCY_KRW


def test_the_krw_notices_were_not_rewritten():
    assert "시간가중수익률(TWR)" in board_page.NOTICE_HOW_RANKING_WORKS
    assert str(duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION) in board_page.NOTICE_MIN_PARTICIPANTS
    assert "가장 최근 발행분" in board_page.NOTICE_DAILY
    assert board_page.NOT_PUBLISHED_TEXT == "비공개"


def test_ranks_are_still_never_recomputed_on_the_screen():
    """§0-3-2 / 5-7 — 통화가 늘었다고 화면에서 정렬·순위 계산을 시작하면 안 됩니다."""
    names = set()
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    for forbidden in ("rank_participants", "compute_twr", "sorted", "sort"):
        assert forbidden not in names, f"순위표 화면이 {forbidden} 로 계산을 다시 합니다."
