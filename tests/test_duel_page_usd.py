# tests/test_duel_page_usd.py
"""
💵 "결투다!" — **달러 결투(USD 트랙) 화면** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요 · nicegui 설치 여부와 무관)

`DUEL_MODULE_WORK_ORDER.md` §5-11(설계 확정) · §5-13(주문 접수 시간대 16:00:01~21:00:00) ·
§5-16(체결 거래일 "당일 포함" 버그 수정) · §5-18(이 라운드)이 화면 계층에서 실제로 지켜지는지
회귀로 고정합니다.

⚠️ **이 파일이 지키려는 사고는 전부 "조용히 틀리는" 종류입니다.** 화면이 예외를 던지지 않고,
   로그에도 아무것도 안 남기면서, 사용자에게만 틀린 값·틀린 안내를 보여주는 것들입니다.
   그래서 검사도 "예외가 안 났는가"가 아니라 **"정확히 무엇을 호출했고 무슨 문구를 썼는가"**
   를 봅니다.

     ① 🔴 **접수 시간대 혼선** — 달러 블록이 원화 시간대(18:00:01~22:00:00)를 쓰면 미국 트랙
        사용자가 두 시간 어긋난 안내를 봅니다. 이 트랙에서 실제로 반복돼 온 사고이고,
        `utils/duel_db_usd.py::_translate_order_guard_error_usd()` 가 애초에 그걸 막으려고
        만들어진 함수입니다.
     ② 🔴 **체결 시점 문구** — 원화는 "다음 거래일(D+1) 종가", 달러는 "**주문을 넣은 바로
        그날**의 미국 정규장 마감가"입니다(§5-16, 이유가 정반대). 원화 문구를 복사해 붙이면
        화면이 사실과 다른 말을 하게 됩니다(§0-1).
     ③ 🔴 **거래일 후보 목록** — 화면이 `save_order_usd()` 에 넘기는 후보에 **당일이 없으면**
        §5-16 에서 고친 동작이 화면 쪽에서 다시 하루 밀립니다. 함수는 멀쩡한데 인자가 틀린,
        가장 잡기 어려운 형태입니다.
     ④ 🔴 **두 통화 합산** — §5-11-2 오너 확정: 원화 값과 달러 값을 더한 숫자를 화면에
        만들지 않습니다(환율 시계열이 없으므로 그 숫자는 지어낸 값입니다).
     ⑤ 🔴 **트랙 독립성** — 원화만 참여/달러만 참여가 전부 정상 상태이고, 한쪽이 없다고
        다른 쪽이 안 그려지면 안 됩니다(§5-11-10 · 스키마 §14-10).
     ⑥ 🔴 **원화 회귀** — 위를 만들면서 원화 쪽 동작·문구가 바뀌지 않았는지.

⚠️ 여기서 **검증하지 못하는 것**(§0-1 — 할 수 있는 것만 했다고 말합니다):
    · 실제 브라우저에 픽셀이 어떻게 찍히는지. 위젯은 실행되지만 그려지지는 않습니다.
    · 실제 Supabase RLS·트리거가 막아주는지(그건 `sql/duel_schema.sql` §14 의 몫).

실행: pytest tests/test_duel_page_usd.py -v
"""

import ast
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from utils import duel_rules                                             # noqa: E402
from utils.duel_rules import KST                                         # noqa: E402

PAGE_PATH = REPO_ROOT / "web" / "pages" / "duel_page.py"
PAGE_SRC = PAGE_PATH.read_text(encoding="utf-8")
PAGE_TREE = ast.parse(PAGE_SRC)


# =============================================================================
# 0. 도우미 — 소스 구조를 함수 단위로 들여다보기
# =============================================================================
def _functions():
    """{함수이름: ast 노드} — 중첩 함수(핸들러)도 전부 포함합니다."""
    found = {}
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


FUNCTIONS = _functions()


def _names_used(node):
    """함수 본문에서 쓰인 이름(변수·함수·속성)의 집합. 중첩 함수 안까지 봅니다."""
    used = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.add(child.attr)
    return used


def _calls_in(node):
    """함수 안에서 **직접 호출된** 이름들. `f(...)` 과 `mod.f(...)` 를 모두 잡습니다."""
    called = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                called.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                called.add(child.func.attr)
    return called


def _referenced_callables(node):
    """호출뿐 아니라 **인자로 넘겨진 함수 이름**까지 포함합니다.

    이 화면은 DB 호출을 `run_blocking(fetch_x, client, ...)` 형태로 스레드에 넘기므로
    (2026-08-21 이벤트 루프 사고 대응), 단순히 `ast.Call` 만 세면 DB 호출이 **한 건도
    안 보입니다.** 그래서 이 파일의 검사는 "이름이 이 함수 안에서 쓰였는가"로 봅니다.
    """
    return _names_used(node) | _calls_in(node)


def _run_blocking_calls(node):
    """`run_blocking(대상함수, 첫인자, …)` 호출 목록 → [(대상함수이름, [인자노드…], 키워드)]."""
    found = []
    for child in ast.walk(node):
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "run_blocking"
                and child.args
                and isinstance(child.args[0], ast.Name)):
            found.append((child.args[0].id, child.args[1:], child.keywords))
    return found


def _own_run_blocking_calls(node):
    """중첩 함수 **안으로는 내려가지 않고**, 이 함수 본문에 직접 있는 run_blocking 호출만."""
    found = []
    stack = list(node.body)
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue                                # 중첩 함수는 자기 자신이 async 면 됩니다
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "run_blocking"
                and child.args
                and isinstance(child.args[0], ast.Name)):
            found.append((child.args[0].id, child.args[1:], child.keywords))
        stack.extend(ast.iter_child_nodes(child))
    return found


# =============================================================================
# 1. 🔴 주문 접수 시간대 — 달러 블록이 원화 시간대를 쓰면 안 됩니다 (§5-13)
# =============================================================================
def test_usd_window_state_helper_delegates_to_the_usd_rule_function():
    """`_order_window_state_usd()` 는 `resolve_order_window_usd()` 만 부릅니다."""
    import web.pages.duel_page as page

    node = FUNCTIONS["_order_window_state_usd"]
    called = _calls_in(node)
    assert "resolve_order_window_usd" in called, (
        "_order_window_state_usd() 가 duel_rules.resolve_order_window_usd() 를 부르지 않습니다."
    )
    assert "resolve_order_window" not in called, (
        "_order_window_state_usd() 가 원화용 resolve_order_window() 를 부르고 있습니다 — "
        "달러 트랙 사용자에게 두 시간 어긋난 안내가 나갑니다(§5-13)."
    )

    # 함수 객체 수준에서도 서로 다른 판정임을 고정합니다(둘이 같은 함수를 가리키면 실패).
    assert duel_rules.resolve_order_window is not duel_rules.resolve_order_window_usd

    # 실제로 두 시간 다른 판정을 하는지 — 17:00 KST 는 달러만 열려 있는 시각입니다.
    seventeen = datetime(2026, 8, 19, 17, 0, 0, tzinfo=KST)
    assert page._order_window_state_usd(seventeen)["is_open"] is True
    assert page._order_window_state(seventeen)["is_open"] is False, (
        "원화 창이 17:00 에 열려 있으면 안 됩니다(18:00:01 부터) — 원화 쪽이 바뀐 것입니다."
    )

    # 반대 방향도 — 21:30 KST 는 원화만 열려 있는 시각입니다.
    half_past_nine = datetime(2026, 8, 19, 21, 30, 0, tzinfo=KST)
    assert page._order_window_state_usd(half_past_nine)["is_open"] is False
    assert page._order_window_state(half_past_nine)["is_open"] is True


def test_no_usd_function_touches_the_krw_order_window_helpers():
    """이름이 `_usd` 로 끝나는 화면 함수는 원화 시간대 도우미를 **하나도** 쓰지 않습니다.

    ⚠️ `_render_body()` 는 예외입니다 — 두 트랙의 안내를 나란히 그려야 하므로 양쪽을 전부
       부르는 것이 정상입니다. 그래서 검사 대상에서 뺍니다.
    """
    krw_only = {"_order_window_state", "_window_message", "resolve_order_window",
                "ORDER_WINDOW_TEXT", "ORDER_WINDOW_OPEN_TIME", "ORDER_WINDOW_CLOSE_TIME",
                "NOTICE_FILL_TIMING", "NOTICE_CRAWL_FAILURE", "NOTICE_WHY_NEXT_DAY",
                "NOTICE_CASH_ROLLOVER", "NOTICE_TWR", "MANDATORY_NOTICES",
                "_upcoming_trading_days"}
    offenders = {}
    for name, node in FUNCTIONS.items():
        if not name.endswith("_usd"):
            continue
        used = _referenced_callables(node)
        # `_usd` 접미어가 붙은 이름은 원화 이름을 접두어로 포함하므로 정확히 일치할 때만 잡습니다.
        hits = sorted(krw_only & used)
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"달러 함수가 원화 전용 상수·도우미를 쓰고 있습니다: {offenders}. "
        "이 트랙에서 실제로 반복돼 온 사고 형태입니다(§5-13 · §5-16)."
    )


def test_usd_order_form_and_orders_use_the_usd_window_message():
    """달러 주문 창·주문 내역이 달러 안내 문구를 씁니다."""
    for name in ("_render_order_form_usd", "_render_orders_section_usd"):
        used = _referenced_callables(FUNCTIONS[name])
        assert "ORDER_WINDOW_TEXT_USD" in used or "_window_message_usd" in used, (
            f"{name}() 이 달러 접수 시간대 문구를 쓰지 않습니다."
        )


def test_usd_window_text_comes_from_the_rule_constants_not_a_hardcoded_string():
    """화면이 16:00 을 따로 적어두지 않고 규칙 계층 상수에서 만들어 씁니다(§0-3-10)."""
    import web.pages.duel_page as page

    expected = (
        f"{duel_rules.ORDER_WINDOW_OPEN_TIME_USD.strftime('%H:%M:%S')}"
        f"~{duel_rules.ORDER_WINDOW_CLOSE_TIME_USD.strftime('%H:%M:%S')} (한국시간)"
    )
    assert page.ORDER_WINDOW_TEXT_USD == expected
    assert "16:00:01" in page.ORDER_WINDOW_TEXT_USD
    assert "21:00:00" in page.ORDER_WINDOW_TEXT_USD


# =============================================================================
# 2. 🔴 체결 시점 문구 — 원화 문구를 복사하면 사실과 달라집니다 (§5-16 · §0-1)
# =============================================================================
def test_usd_fill_timing_notice_states_the_same_day_close_not_the_next_trading_day():
    import web.pages.duel_page as page

    text = page.NOTICE_FILL_TIMING_USD

    # ① 원화 문구를 그대로 복사해 오지 않았는지 — 가장 직접적인 회귀.
    assert text != page.NOTICE_FILL_TIMING, (
        "달러 체결 시점 문구가 원화 문구와 완전히 같습니다 — 복사해 붙인 것입니다."
    )
    assert "다음 거래일(D+1)" not in text, (
        "원화 문구의 'D+1' 표현이 달러 문구에 그대로 들어와 있습니다. 달러는 D+1 이 아니라 "
        "'주문을 넣은 바로 그날'의 마감가로 체결됩니다(§5-16)."
    )

    # ② 시장 이름이 섞이지 않았는지.
    assert "코스피" not in text, "달러 문구에 '코스피'가 들어 있습니다."
    assert "미국 정규장" in text

    # ③ §5-16 이 확정한 사실이 실제로 들어 있는지.
    assert "바로 그날" in text, (
        "'주문을 넣은 바로 그날의 마감가로 체결된다'는 §5-16 확정 사실이 문구에 없습니다."
    )
    # ④ 왜 그런지(그 시점에 마감가가 아직 존재하지 않음)도 함께 말하는지 — §0-1.
    assert "아직 세상에 존재하지 않습니다" in text

    # ⑤ 원화 문구는 그대로여야 합니다(회귀).
    assert "다음 거래일(D+1)" in page.NOTICE_FILL_TIMING
    assert "주문은 저장 즉시 체결되지 않습니다" in page.NOTICE_FILL_TIMING


def test_usd_why_same_day_notice_explains_the_opposite_reason_from_krw():
    import web.pages.duel_page as page

    assert page.NOTICE_WHY_SAME_DAY_USD != page.NOTICE_WHY_NEXT_DAY
    text = page.NOTICE_WHY_SAME_DAY_USD
    assert "열리기" in text and "전" in text, (
        "달러 트랙의 접수 시간대가 '그날 미국장이 열리기 전'이라는 핵심 근거가 없습니다."
    )
    assert "코스피" not in text
    # 원화 문구는 그대로.
    assert "오늘 종가가 이미 다 알려져" in page.NOTICE_WHY_NEXT_DAY


def test_all_usd_notices_are_free_of_kospi_and_won_amounts():
    """달러 고지 문구에 '코스피'와 '…원' 금액 표기가 섞여 있지 않은지."""
    import re

    import web.pages.duel_page as page

    usd_notices = {
        "NOTICE_NO_DIVIDEND_USD": page.NOTICE_NO_DIVIDEND_USD,
        "NOTICE_FILL_TIMING_USD": page.NOTICE_FILL_TIMING_USD,
        "NOTICE_BUY_ONLY_USD": page.NOTICE_BUY_ONLY_USD,
        "NOTICE_CRAWL_FAILURE_USD": page.NOTICE_CRAWL_FAILURE_USD,
        "NOTICE_WHY_SAME_DAY_USD": page.NOTICE_WHY_SAME_DAY_USD,
        "NOTICE_CASH_ROLLOVER_USD": page.NOTICE_CASH_ROLLOVER_USD,
        "NOTICE_TWR_USD": page.NOTICE_TWR_USD,
    }
    for name, text in usd_notices.items():
        assert "코스피" not in text, f"{name} 에 '코스피'가 들어 있습니다."
        # "1,000,000원" 같은 원화 금액 표기가 남아 있으면 원화 문구를 복사한 흔적입니다.
        assert not re.search(r"\d[\d,]*\s*원", text), f"{name} 에 원화 금액 표기가 남아 있습니다."

    # 상시 노출 4종이 실제로 이 문구들로 구성돼 있는지(§2-8 의 USD 판 + 통화 혼합 금지 고지).
    assert page.MANDATORY_NOTICES_USD == (
        page.NOTICE_NO_DIVIDEND_USD, page.NOTICE_FILL_TIMING_USD,
        page.NOTICE_BUY_ONLY_USD, page.NOTICE_NO_FX_MIX,
    )
    assert page.MANDATORY_NOTICES_USD != page.MANDATORY_NOTICES
    # 원화 3종은 그대로(회귀).
    assert page.MANDATORY_NOTICES == (
        page.NOTICE_NO_DIVIDEND, page.NOTICE_FILL_TIMING, page.NOTICE_BUY_ONLY,
    )


def test_header_renders_both_notice_sets_and_krw_first():
    """화면 머리말이 원화 3종 **뒤에** 달러 고지를 덧붙이는 구조인지."""
    body = FUNCTIONS["_render_header_usd"]
    assert "MANDATORY_NOTICES_USD" in _referenced_callables(body)
    # `duel_page()` 가 두 머리말을 모두, 원화 → 달러 순서로 부릅니다.
    page_fn_src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["duel_page"])
    assert page_fn_src.index("_render_header()") < page_fn_src.index("_render_header_usd()")


# =============================================================================
# 3. 🔴 거래일 후보 — **당일이 반드시 포함**돼야 합니다 (§5-16)
# =============================================================================
def test_usd_trading_day_candidates_include_the_order_day_itself():
    import web.pages.duel_page as page

    wednesday = date(2026, 8, 19)                  # 수요일
    usd_days = page._upcoming_trading_days_usd(wednesday)
    assert usd_days[0] == wednesday, (
        "달러 거래일 후보의 첫 날이 저장일 자신이 아닙니다 — "
        "`resolve_fill_trading_day_usd()` 가 당일을 고를 수 없게 되어 체결이 하루 밀립니다(§5-16)."
    )
    assert wednesday in usd_days


def test_krw_trading_day_candidates_still_exclude_the_order_day():
    """원화 회귀 — 원화는 지금까지 그랬던 대로 **다음 날부터**입니다."""
    import web.pages.duel_page as page

    wednesday = date(2026, 8, 19)
    krw_days = page._upcoming_trading_days(wednesday)
    assert wednesday not in krw_days
    assert krw_days[0] == date(2026, 8, 20)


def test_two_candidate_builders_differ_only_by_the_order_day():
    """두 목록의 차이는 **저장일 자신 하나뿐**이어야 합니다."""
    import web.pages.duel_page as page

    wednesday = date(2026, 8, 19)
    usd_days = set(page._upcoming_trading_days_usd(wednesday))
    krw_days = set(page._upcoming_trading_days(wednesday))
    assert usd_days - krw_days == {wednesday}
    assert krw_days - usd_days == set()


def test_usd_candidates_skip_weekends_like_krw():
    import web.pages.duel_page as page

    saturday = date(2026, 8, 22)                   # 토요일
    days = page._upcoming_trading_days_usd(saturday)
    assert saturday not in days, "토요일은 미국 정규장 거래일 후보가 아닙니다."
    assert days[0] == date(2026, 8, 24)            # 월요일
    assert all(day.weekday() < 5 for day in days)


def test_usd_candidates_feed_resolve_fill_trading_day_usd_to_the_same_day():
    """화면이 만든 후보 목록이 실제로 규칙 함수에서 '당일'을 만들어내는지 — 끝까지 연결 검증.

    함수만 고쳐놓고 화면이 넘기는 목록이 틀리면 §5-16 버그가 그대로 살아납니다. 그래서
    화면 도우미 → 규칙 함수까지 **한 번에** 통과시켜 봅니다.
    """
    import web.pages.duel_page as page

    saved_at = datetime(2026, 8, 19, 18, 30, 0, tzinfo=KST)     # 달러 접수 시간대 한가운데
    usd_target = duel_rules.resolve_fill_trading_day_usd(
        saved_at, page._upcoming_trading_days_usd(saved_at.date()))
    assert usd_target == date(2026, 8, 19), (
        "화면이 넘긴 후보로 체결 거래일을 정하니 당일이 아닙니다 — §5-16 이 고친 동작이 "
        "화면 쪽에서 되살아난 것입니다."
    )

    # 원화 쪽은 여전히 다음 거래일이어야 합니다(같은 시각·같은 방식으로 대조).
    krw_target = duel_rules.resolve_fill_trading_day(
        saved_at, page._upcoming_trading_days(saved_at.date()))
    assert krw_target == date(2026, 8, 20)
    assert usd_target < krw_target


def test_usd_order_form_passes_the_usd_candidate_builder_to_save_order_usd():
    """`save_order_usd()` 호출에 **`_upcoming_trading_days_usd`** 가 넘어가는지(AST)."""
    node = FUNCTIONS["_render_order_form_usd"]
    saves = [call for call in _run_blocking_calls(node) if call[0] == "save_order_usd"]
    assert len(saves) == 1, f"save_order_usd 호출이 정확히 1건이어야 합니다: {saves}"
    _target, _args, keywords = saves[0]
    trading_days = {kw.arg: kw.value for kw in keywords}.get("trading_days")
    assert trading_days is not None, "trading_days 를 키워드로 넘기지 않았습니다."
    assert (isinstance(trading_days, ast.Call)
            and isinstance(trading_days.func, ast.Name)
            and trading_days.func.id == "_upcoming_trading_days_usd"), (
        "달러 주문이 `_upcoming_trading_days_usd()` 가 아닌 다른 목록을 넘기고 있습니다 — "
        "원화용(`_upcoming_trading_days`)을 넘기면 체결이 조용히 하루 밀립니다(§5-16)."
    )

    # 원화 회귀 — 원화 주문은 여전히 원화용 목록을 넘깁니다.
    krw_saves = [c for c in _run_blocking_calls(FUNCTIONS["_render_order_form"])
                 if c[0] == "save_order"]
    assert len(krw_saves) == 1
    krw_days = {kw.arg: kw.value for kw in krw_saves[0][2]}.get("trading_days")
    assert (isinstance(krw_days, ast.Call) and krw_days.func.id == "_upcoming_trading_days")


# =============================================================================
# 4. 🔴 DB 호출 — 달러 블록은 `_usd` 함수만 부릅니다 (다른 표를 읽으면 안 됩니다)
# =============================================================================
KRW_DB_FUNCTIONS = ("fetch_my_accounts", "fetch_my_cash_ledger", "fetch_my_positions",
                    "fetch_my_snapshots", "fetch_my_orders", "save_order", "save_sell_order",
                    "edit_order", "cancel_order", "opt_in")
USD_DB_FUNCTIONS = tuple(f"{name}_usd" for name in KRW_DB_FUNCTIONS)


def test_usd_render_functions_never_call_a_krw_db_function():
    offenders = {}
    for name, node in FUNCTIONS.items():
        if not name.endswith("_usd"):
            continue
        used = _referenced_callables(node)
        hits = sorted(set(KRW_DB_FUNCTIONS) & used)
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"달러 화면 함수가 원화 표를 읽는 함수를 부르고 있습니다: {offenders}. "
        "다른 표를 읽게 되므로 화면에 엉뚱한 트랙의 숫자가 나옵니다."
    )


def test_each_usd_db_function_is_imported_and_actually_used():
    """USD DB 함수 9종이 전부 import 되어 있고, 실제로 화면 어딘가에서 쓰이는지."""
    import web.pages.duel_page as page

    for name in USD_DB_FUNCTIONS:
        assert hasattr(page, name), f"{name} 이 duel_page 에 import 되어 있지 않습니다."
        assert any(name in _referenced_callables(node) for node in FUNCTIONS.values()), (
            f"{name} 을 import 만 하고 화면 어디에서도 쓰지 않습니다."
        )


def test_usd_db_calls_pass_the_connection_client_explicitly():
    """모든 `_usd` DB 호출의 첫 인자가 `client` 인지 — §0-3-8 세션 격리 규율.

    ⚠️ 이 화면은 DB 호출을 `run_blocking(fn, client, …)` 로 스레드에 넘기므로, `fn(client,…)`
       모양을 찾는 검사로는 **한 건도 잡히지 않습니다.** 그래서 `run_blocking` 의 두 번째
       인자를 봅니다.
    """
    seen = set()
    for name, node in FUNCTIONS.items():
        for target, args, _kw in _run_blocking_calls(node):
            if not target.endswith("_usd"):
                continue
            seen.add(target)
            assert args and isinstance(args[0], ast.Name) and args[0].id == "client", (
                f"{name}() 의 {target}() 호출이 client 를 명시적으로 넘기지 않습니다: "
                f"{[ast.dump(a) for a in args[:1]]}"
            )
    assert seen >= set(USD_DB_FUNCTIONS), (
        f"run_blocking 으로 호출되지 않은 USD DB 함수가 있습니다: "
        f"{sorted(set(USD_DB_FUNCTIONS) - seen)}"
    )


def test_usd_opt_in_takes_only_the_client_and_never_the_krw_opt_in():
    """`opt_in_usd(client)` — 대상자는 DB 안 `auth.uid()` 로만 정해집니다(스키마 §14-10).

    화면이 `user_id` 를 끼워 넣을 자리를 만들면 "남을 대신 참여시키는" 경로가 생깁니다.
    """
    node = FUNCTIONS["_render_opt_in_usd"]
    calls = [c for c in _run_blocking_calls(node) if c[0] == "opt_in_usd"]
    assert len(calls) == 1, f"opt_in_usd 호출이 정확히 1건이어야 합니다: {calls}"
    _target, args, keywords = calls[0]
    assert len(args) == 1 and isinstance(args[0], ast.Name) and args[0].id == "client"
    assert not keywords, "opt_in_usd 에 추가 인자를 넘기고 있습니다(사용자 id·금액·날짜 금지)."

    # 🔴 원화 옵트인을 실수로 부르지 않는지 — 달러 참여 버튼이 원화 계좌를 만들면 대형 사고입니다.
    assert "opt_in" not in _calls_in(node)
    assert not any(c[0] == "opt_in" for c in _run_blocking_calls(node))

    # 원화 회귀 — 원화 참여 버튼은 여전히 `opt_in(client)` 하나만 부릅니다.
    krw = [c for c in _run_blocking_calls(FUNCTIONS["_render_opt_in"]) if c[0] == "opt_in"]
    assert len(krw) == 1 and len(krw[0][1]) == 1 and not krw[0][2]
    assert not any(c[0] == "opt_in_usd" for c in _run_blocking_calls(FUNCTIONS["_render_opt_in"]))


# =============================================================================
# 5. 🔴 두 통화를 합산하지 않습니다 (§5-11-2 오너 확정)
# =============================================================================
def test_no_function_mixes_the_two_currency_constants():
    """한 함수 안에서 `CURRENCY`(원)와 `CURRENCY_USD`(달러)가 함께 쓰이는 자리가 없습니다.

    이게 이 원칙을 코드로 강제하는 가장 실질적인 방법입니다 — 두 통화를 더한 숫자를
    화면에 내려면 결국 한 함수 안에서 두 서식이 만나야 하기 때문입니다.
    """
    offenders = {}
    for name, node in FUNCTIONS.items():
        used = _names_used(node)
        if "CURRENCY" in used and "CURRENCY_USD" in used:
            offenders[name] = sorted(used & {"CURRENCY", "CURRENCY_USD"})
    assert not offenders, (
        f"한 함수가 두 통화를 동시에 다루고 있습니다: {offenders}. "
        "환율 시계열이 없는 앱에서 두 통화를 합치면 그 숫자는 지어낸 값입니다(§5-11-2)."
    )


def test_no_function_reads_both_currencies_cash_or_positions():
    """원화 원장/포지션과 달러 원장/포지션이 같은 함수 안에 함께 들어오지 않습니다."""
    pairs = [("fetch_my_cash_ledger", "fetch_my_cash_ledger_usd"),
             ("fetch_my_positions", "fetch_my_positions_usd"),
             ("fetch_my_snapshots", "fetch_my_snapshots_usd")]
    for name, node in FUNCTIONS.items():
        used = _referenced_callables(node)
        for krw, usd in pairs:
            assert not (krw in used and usd in used), (
                f"{name}() 이 {krw} 와 {usd} 를 함께 읽습니다 — 두 통화의 값이 한 자리에 "
                "모이면 합산 코드가 생길 수 있습니다(§5-11-2)."
            )


def test_the_pairing_function_only_delegates_and_never_draws_a_number_itself():
    """창유형 카드를 조립하는 `_render_accounts()` 는 숫자를 직접 그리지 않습니다.

    합산 숫자가 생길 수 있는 유일한 자리가 여기이므로, "지표를 직접 만들지 않고 통화별
    카드 함수에 넘기기만 한다"를 구조로 고정합니다.
    """
    node = FUNCTIONS["_render_accounts"]
    called = _calls_in(node)
    assert "metric_card" not in called, (
        "_render_accounts() 가 지표 카드를 직접 그립니다 — 통화별 카드 함수에만 맡기세요."
    )
    assert "format_amount" not in called, (
        "_render_accounts() 가 금액을 직접 서식화합니다 — 합산 숫자가 생길 수 있는 자리입니다."
    )
    assert {"_render_account_card", "_render_account_card_usd"} <= called


def test_screen_says_out_loud_that_the_two_currencies_are_never_added():
    """§0-1 — '합계가 없다'는 사실을 사용자에게 정직하게 말합니다(버그로 오해하지 않도록)."""
    import web.pages.duel_page as page

    assert "더하지 않습니다" in page.NOTICE_NO_FX_MIX
    assert "환율" in page.NOTICE_NO_FX_MIX
    assert page.NOTICE_NO_FX_MIX in page.MANDATORY_NOTICES_USD


# =============================================================================
# 6. 통화별 표시 계산 — `_position_rows_usd()` 는 미국 시장만 조회합니다
# =============================================================================
def _price_lookup_spy(prices):
    """`(market, ticker) → price` 를 흉내내고, **어느 시장으로 물었는지** 기록합니다."""
    asked = []

    def lookup(market, ticker):
        asked.append((market, ticker))
        return prices.get((market, ticker))

    return lookup, asked


def test_position_rows_usd_looks_up_prices_in_the_us_market_only():
    from utils.scorecard_db import MARKET_KR, MARKET_US

    import web.pages.duel_page as page

    lookup, asked = _price_lookup_spy({(MARKET_US, "AAPL"): 200.0})
    positions = [
        {"ticker": "AAPL", "stock_name": "Apple Inc.", "quantity": 3, "avg_cost": 150.0,
         "status": "active"},
    ]
    summary = page._position_rows_usd(positions, lookup)
    assert asked == [(MARKET_US, "AAPL")], f"미국 시장으로만 물어야 합니다: {asked}"
    assert all(market != MARKET_KR for market, _ in asked)
    assert summary["position_value"] == pytest.approx(600.0)
    assert summary["unpriced"] == []


def test_position_rows_usd_does_not_invent_a_price_and_separates_delisting():
    """§0-1 / 3-2 — 가격 결측과 상장폐지는 절대 같게 취급하지 않습니다."""
    import web.pages.duel_page as page

    lookup, _asked = _price_lookup_spy({})
    positions = [
        {"ticker": "ZZZZ", "stock_name": "Unknown", "quantity": 5, "avg_cost": 10.0,
         "status": "active"},
        {"ticker": "DEAD", "stock_name": "Delisted Co", "quantity": 2, "avg_cost": 50.0,
         "status": "delisted", "delisted_date": "2026-07-01"},
    ]
    summary = page._position_rows_usd(positions, lookup)
    by_ticker = {row["ticker"]: row for row in summary["rows"]}
    assert by_ticker["ZZZZ"]["value"] is None and by_ticker["ZZZZ"]["note"] == "가격 확인 중"
    assert by_ticker["DEAD"]["value"] == 0.0
    assert by_ticker["DEAD"]["note"].startswith("상장폐지")
    assert summary["unpriced"] == ["ZZZZ"]
    # 상각된 종목만 0 으로 들어가고, 값을 모르는 종목은 합계에서 빠집니다.
    assert summary["position_value"] == pytest.approx(0.0)


def test_usd_positions_table_uses_dollar_amounts_and_escapes_names():
    """💵 표기가 달러이고, 종목명은 §0-3-9 대로 이스케이프됩니다."""
    import web.pages.duel_page as page

    captured = []
    saved_ui = page.ui
    page.ui = _UiStub(captured)
    try:
        page._render_positions_table_usd([
            {"ticker": "AAPL", "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3,
             "avg_cost": 150.0, "price": 200.0, "value": 600.0, "note": ""},
            {"ticker": "DEAD", "stock_name": "Delisted Co", "quantity": 2, "avg_cost": 50.0,
             "price": None, "value": 0.0, "note": "상장폐지 상각(2026-07-01)"},
        ])
    finally:
        page.ui = saved_ui

    blob = "\n".join(captured)
    assert "$200.00" in blob and "$600.00" in blob
    assert "원" not in blob.replace("onerror", ""), "달러 표에 원화 표기가 섞였습니다."
    assert "$0.00" in blob, "상장폐지 상각은 $0 으로 확정 표시해야 합니다."
    assert "<img src=x onerror=" not in blob
    assert "&lt;img src=x onerror=alert(1)&gt;" in blob


# =============================================================================
# 7. 🔴 트랙 독립 — 한쪽만 참여해도 화면이 깨지지 않습니다 (§5-11-10 · 스키마 §14-10)
# =============================================================================
SYNTHETIC_KRW_ACCOUNTS = [
    {"id": "krw-m1", "user_id": "uid-1", "window_type": "M1", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
    {"id": "krw-m3", "user_id": "uid-1", "window_type": "M3", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
    {"id": "krw-m6", "user_id": "uid-1", "window_type": "M6", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
]

SYNTHETIC_USD_ACCOUNTS = [
    {"id": "usd-m1", "user_id": "uid-1", "window_type": "M1", "seed_amount": 7500,
     "currency": "USD", "anchor_date": "2026-08-05", "status": "active"},
    {"id": "usd-m3", "user_id": "uid-1", "window_type": "M3", "seed_amount": 7500,
     "currency": "USD", "anchor_date": "2026-08-05", "status": "active"},
    {"id": "usd-m6", "user_id": "uid-1", "window_type": "M6", "seed_amount": 7500,
     "currency": "USD", "anchor_date": "2026-08-05", "status": "active"},
]

SYNTHETIC_USD_LEDGER = [
    {"id": 1, "account_id": "usd-m1", "event_type": "seed", "amount": 7500,
     "event_date": "2026-08-05"},
    {"id": 2, "account_id": "usd-m1", "event_type": "monthly_deposit", "amount": 500,
     "event_date": "2026-08-10"},
    {"id": 3, "account_id": "usd-m1", "event_type": "buy", "amount": -600,
     "event_date": "2026-08-11"},
]

SYNTHETIC_USD_POSITIONS = [
    {"id": "up-1", "account_id": "usd-m1", "ticker": "AAPL", "stock_name": "Apple Inc.",
     "quantity": 3, "avg_cost": 200.0, "status": "active", "delisted_date": None},
    # 🔐 종목명에 스크립트를 심어 둔 행 — 글자 그대로 나와야 합니다(§0-3-9).
    {"id": "up-2", "account_id": "usd-m1", "ticker": "ZZZZ",
     "stock_name": "<img src=x onerror=alert(2)>", "quantity": 1, "avg_cost": 10.0,
     "status": "active", "delisted_date": None},
]

SYNTHETIC_USD_ORDERS = [
    {"id": "uo-1", "account_id": "usd-m1", "ticker": "MSFT", "stock_name": "Microsoft",
     "requested_quantity": 4, "status": "pending", "saved_at": "2026-08-19T18:30:00+09:00",
     "target_date": "2026-08-19"},
    {"id": "uo-2", "account_id": "usd-m1", "ticker": "AAPL", "stock_name": "Apple Inc.",
     "requested_quantity": 5, "status": "partially_filled", "filled_quantity": 3,
     "filled_price": 200.0, "filled_amount": 600.0, "filled_date": "2026-08-11",
     "saved_at": "2026-08-11T18:30:00+09:00", "target_date": "2026-08-11",
     "fail_reason": "요청 5주 중 3주만 예수금 부족으로 체결"},
]

SYNTHETIC_USD_SNAPSHOTS = [
    {"snapshot_date": "2026-08-05", "account_id": "usd-m1", "position_value": 0,
     "cash_balance": 7500, "total_value": 7500, "total_cost": 0,
     "cash_flow_amount": 7500, "cash_flow_kind": "seed", "priced_count": 0,
     "unpriced_count": 0},
    {"snapshot_date": "2026-08-11", "account_id": "usd-m1", "position_value": 620,
     "cash_balance": 7400, "total_value": 8020, "total_cost": 600,
     "cash_flow_amount": 500, "cash_flow_kind": "monthly_deposit", "priced_count": 1,
     "unpriced_count": 0},
]


def _for_account(rows):
    return lambda client, account_id: [dict(r) for r in rows if r.get("account_id") == account_id]


class _WidgetStub:
    """어떤 NiceGUI 위젯 흉내든 다 내는 객체 — 호출/속성접근/`with` 를 전부 받아넘깁니다.

    화면 함수를 **실제로 실행**해볼 수 있게 해주는 최소 스텁입니다
    (`tests/test_web_session_isolation.py::_install_nicegui_stub()` 과 같은 발상).
    위젯이 그려지진 않지만 f-string·이스케이프·분기·금액 서식·소유자 확인은 전부 진짜로
    돌아갑니다. 호출 인자로 들어온 문자열은 전부 `sink` 에 모읍니다.

    ⚠️ **진짜 nicegui 를 쓰지 않는 이유**(2026-08-21에 직접 부딪힌 것): 실제 nicegui 는
       `asyncio.run()` 으로 만든 새 태스크에 슬롯 스택이 없으면 예외를 던지고, 그 대체
       클라이언트는 프로세스당 한 번만 만들어집니다. 그래서 진짜 nicegui 로 렌더 스모크를
       두 번 이상 돌리면 두 번째부터 무조건 실패합니다 — 이 파일은 렌더 검사를 여러 개
       돌리므로 스텁이 필요하고, 겸사겸사 다른 테스트 파일의 스모크와 서로 간섭하지도
       않습니다.
    """

    def __init__(self, sink):
        object.__setattr__(self, "_sink", sink)

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]                          # 데코레이터로 쓰인 경우
        for value in args:
            if isinstance(value, str):
                self._sink.append(value)
        return self

    def __getattr__(self, _name):
        return self

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _RefreshableStub:
    """`@ui.refreshable` 흉내 — `.refresh()` 를 가진 호출 가능 객체여야 합니다."""

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)

    def refresh(self, *_a, **_k):
        return None                                 # 스모크에서는 재귀 렌더를 하지 않습니다


class _UiStub:
    def __init__(self, sink):
        object.__setattr__(self, "_sink", sink)
        object.__setattr__(self, "_widget", _WidgetStub(sink))

    def __getattr__(self, name):
        if name == "refreshable":
            return _RefreshableStub
        return self._widget


class _RenderHarness:
    """`_render_body()` 를 실제로 실행하고, 화면에 나간 문자열과 DB 호출을 모읍니다.

    §0-1 — 계좌·주문·현금은 **전부 합성 데이터**이고 Supabase 에는 접속하지 않습니다.
    시세 스냅샷만 저장소의 실제 파일을 읽습니다(그 파일이 없으면 화면이 정직하게 "못
    읽었다"고 말하는 경로를 타므로 아래 검사들은 그대로 성립합니다).
    """

    _DB_NAMES = ("fetch_my_accounts", "fetch_my_cash_ledger", "fetch_my_positions",
                 "fetch_my_orders", "fetch_my_snapshots",
                 "fetch_my_accounts_usd", "fetch_my_cash_ledger_usd",
                 "fetch_my_positions_usd", "fetch_my_orders_usd", "fetch_my_snapshots_usd")

    def __init__(self, krw_accounts, usd_accounts):
        self.krw_accounts = krw_accounts
        self.usd_accounts = usd_accounts
        self.html = []
        self.calls = []

    def __enter__(self):
        import web.components.widgets as widgets
        import web.pages.duel_page as page
        self.page = page
        self.widgets = widgets
        self._saved = {name: getattr(page, name) for name in self._DB_NAMES}
        self._saved_ui = (page.ui, widgets.ui)

        def _record(name, fn):
            def wrapped(*args, **kwargs):
                self.calls.append(name)
                return fn(*args, **kwargs)
            return wrapped

        page.fetch_my_accounts = _record(
            "fetch_my_accounts", lambda client, user_id: [dict(a) for a in self.krw_accounts])
        page.fetch_my_cash_ledger = _record("fetch_my_cash_ledger", _for_account([]))
        page.fetch_my_positions = _record("fetch_my_positions", _for_account([]))
        page.fetch_my_orders = _record("fetch_my_orders", _for_account([]))
        page.fetch_my_snapshots = _record(
            "fetch_my_snapshots",
            lambda client, account_id, start_date=None, end_date=None: [])

        page.fetch_my_accounts_usd = _record(
            "fetch_my_accounts_usd", lambda client, user_id: [dict(a) for a in self.usd_accounts])
        page.fetch_my_cash_ledger_usd = _record(
            "fetch_my_cash_ledger_usd", _for_account(SYNTHETIC_USD_LEDGER))
        page.fetch_my_positions_usd = _record(
            "fetch_my_positions_usd", _for_account(SYNTHETIC_USD_POSITIONS))
        page.fetch_my_orders_usd = _record(
            "fetch_my_orders_usd", _for_account(SYNTHETIC_USD_ORDERS))
        page.fetch_my_snapshots_usd = _record(
            "fetch_my_snapshots_usd",
            lambda client, account_id, start_date=None, end_date=None:
            [dict(r) for r in SYNTHETIC_USD_SNAPSHOTS if r.get("account_id") == account_id])

        stub = _UiStub(self.html)
        page.ui = stub
        widgets.ui = stub
        return self

    def __exit__(self, *_exc):
        for name, fn in self._saved.items():
            setattr(self.page, name, fn)
        self.page.ui, self.widgets.ui = self._saved_ui
        return False

    def run(self):
        asyncio.run(self.page._render_body(object(), "uid-1", "duel@example.com"))
        return "\n".join(self.html)


def test_both_tracks_render_side_by_side_without_a_combined_total():
    with _RenderHarness(SYNTHETIC_KRW_ACCOUNTS, SYNTHETIC_USD_ACCOUNTS) as harness:
        blob = harness.run()

    # 두 트랙의 데이터를 모두 실제로 읽었는지.
    assert "fetch_my_accounts" in harness.calls and "fetch_my_accounts_usd" in harness.calls
    assert "fetch_my_positions_usd" in harness.calls
    assert "fetch_my_orders_usd" in harness.calls

    # 달러 보유 종목·부분체결이 화면에 나왔는지.
    assert "AAPL" in blob
    assert "요청 5주 중 3주만" in blob, "부분체결은 요청·실제 수량을 둘 다 보여야 합니다."
    # 🔐 XSS — 달러 쪽 종목명도 글자 그대로.
    assert "<img src=x onerror=" not in blob
    assert "&lt;img src=x onerror=alert(2)&gt;" in blob
    # 가격을 못 구한 종목은 0 이 아니라 "가격 확인 중".
    assert "가격 확인 중" in blob


def test_usd_only_user_still_gets_a_full_usd_screen():
    """원화에 참여하지 않은 사용자도 달러 화면을 온전히 봅니다(§5-11-10)."""
    with _RenderHarness([], SYNTHETIC_USD_ACCOUNTS) as harness:
        blob = harness.run()

    assert "fetch_my_accounts_usd" in harness.calls
    assert "fetch_my_positions_usd" in harness.calls, "달러 계좌 카드가 그려지지 않았습니다."
    assert "fetch_my_orders_usd" in harness.calls, "달러 주문 내역이 그려지지 않았습니다."
    # 원화 계좌가 없으니 원화 계좌 상세는 읽지 않습니다(참여 안내만 나옵니다).
    assert "fetch_my_positions" not in harness.calls
    assert "AAPL" in blob


def test_krw_only_user_screen_does_not_break_and_never_reads_usd_details():
    """달러에 참여하지 않은 사용자(= 오늘 실제 사용자 전원)의 화면이 그대로인지."""
    with _RenderHarness(SYNTHETIC_KRW_ACCOUNTS, []) as harness:
        harness.run()

    assert "fetch_my_accounts" in harness.calls
    assert "fetch_my_accounts_usd" in harness.calls, (
        "달러 계좌 유무는 매번 확인해야 합니다(참여 안내를 보여주기 위해)."
    )
    # 달러 계좌가 없으므로 달러 상세 조회는 **한 번도** 일어나지 않습니다(불필요한 왕복 금지).
    for name in ("fetch_my_cash_ledger_usd", "fetch_my_positions_usd",
                 "fetch_my_snapshots_usd", "fetch_my_orders_usd"):
        assert name not in harness.calls, f"달러 계좌가 없는데 {name} 을 불렀습니다."


def test_a_user_in_neither_track_sees_both_join_cards():
    import web.pages.duel_page as page

    with _RenderHarness([], []) as harness:
        rendered = []
        saved = (page._render_opt_in, page._render_opt_in_usd)
        page._render_opt_in = lambda *a, **k: rendered.append("krw")
        page._render_opt_in_usd = lambda *a, **k: rendered.append("usd")
        try:
            harness.run()
        finally:
            page._render_opt_in, page._render_opt_in_usd = saved

    assert rendered == ["krw", "usd"], f"두 참여 안내가 모두 나와야 합니다: {rendered}"


def test_a_usd_account_belonging_to_someone_else_is_not_drawn():
    """🔒 §0-3-8 이중 방어 — RLS 가 지워져도 남의 달러 계좌를 그리지 않습니다."""
    import web.pages.duel_page as page

    intruder = [dict(SYNTHETIC_USD_ACCOUNTS[0], user_id="uid-someone-else")]
    banners = []
    saved_banner = page.error_banner
    page.error_banner = lambda text: banners.append(str(text))
    try:
        with _RenderHarness(SYNTHETIC_KRW_ACCOUNTS, intruder) as harness:
            harness.run()
    finally:
        page.error_banner = saved_banner

    assert any("본인 것이 아닌" in text for text in banners), (
        f"남의 달러 계좌가 섞였는데 경고가 없습니다: {banners}"
    )
    # 그 계좌의 상세를 읽지 않았어야 합니다.
    assert "fetch_my_positions_usd" not in harness.calls


def test_the_owner_check_runs_inside_every_usd_render_function():
    """계좌를 그리는 달러 함수마다 소유자 확인 한 줄이 다시 들어 있는지(소스 검사)."""
    for name in ("_render_account_card_usd", "_render_account_orders_usd"):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert 'account.get("user_id") != user_id' in src, (
            f"{name}() 에 소유자 이중 확인이 없습니다(§0-3-8)."
        )


def test_usd_render_functions_take_client_and_user_id_as_arguments():
    """§0-3-8 — "지금 누가 로그인했는지"를 전역에서 추측하지 않습니다."""
    for name in ("_render_opt_in_usd", "_render_account_card_usd", "_render_order_form_usd",
                 "_render_orders_section_usd", "_render_account_orders_usd"):
        args = [a.arg for a in FUNCTIONS[name].args.args]
        assert "client" in args and "user_id" in args, f"{name}{tuple(args)}"


# =============================================================================
# 8. 상수 — 화면이 시드·입금액을 스스로 적어두지 않고 규칙 계층에서 가져오는지
# =============================================================================
def test_usd_amounts_come_from_the_rule_layer_single_source():
    import web.pages.duel_page as page

    assert page.SEED_AMOUNT_USD == duel_rules.SEED_AMOUNT_USD == 7500
    assert page.MONTHLY_DEPOSIT_USD == duel_rules.MONTHLY_DEPOSIT_USD == 500
    assert page.CURRENCY_USD == "USD"
    # 원화 상수는 그대로(회귀).
    assert page.CURRENCY == "KRW"
    assert page.SEED_AMOUNT_KRW == duel_rules.SEED_AMOUNT_KRW

    # 화면 소스에 시드 금액을 숫자로 다시 적어둔 자리가 없어야 합니다(§0-3-10).
    assert "7500" not in PAGE_SRC.replace("SEED_AMOUNT_USD", "")
    assert "7,500" not in PAGE_SRC


def test_usd_track_reuses_the_shared_pure_helpers_instead_of_copying_them():
    """§5-11-1 — "데이터는 분리, 순수 규칙은 공유". 복제본이 생기지 않았는지 고정합니다."""
    shared_that_must_not_be_forked = (
        "_parse_positive_int_usd", "_twr_display_usd", "_order_status_text_usd",
        "_universe_options_usd", "_fail_usd", "sum_cash_balance_usd", "compute_twr_usd",
        "is_buy_window_open_usd",
    )
    for name in shared_that_must_not_be_forked:
        assert name not in FUNCTIONS, (
            f"{name}() 이 새로 생겼습니다 — 이 함수는 통화를 모르는 순수 계산이라 원화와 "
            "공유해야 합니다(규칙이 바뀌었는데 한쪽만 고치는 사고를 막기 위해서)."
        )

    # 달러 카드가 실제로 공유 함수를 쓰고 있는지.
    used = _referenced_callables(FUNCTIONS["_render_account_card_usd"])
    assert "sum_cash_balance" in used and "_twr_display" in used
    assert "is_buy_window_open" in used


# =============================================================================
# 9. 원화 회귀 — 이번 라운드가 원화 쪽 동작·문구를 바꾸지 않았는지
# =============================================================================
def test_krw_rendering_path_is_untouched_when_the_user_has_no_usd_account():
    """달러 계좌가 없으면 `_render_accounts()` 가 **예전과 같은 원화 전용 경로**를 탑니다."""
    import web.pages.duel_page as page

    rows = []
    saved_ui = page.ui
    saved_card = page._render_account_card

    class _RowSpy:
        def __init__(self, *a, **k):
            pass

        def classes(self, value=''):
            rows.append(value)
            return self

        def style(self, _value=''):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    drawn = []

    # 🔁 2026-08-21 — 계좌 카드가 `bundle`(포지션·주문 묶음)을 **키워드로** 받습니다.
    #    묶음을 위에서 한 번만 읽어 카드·주문 폼·주문 내역이 나눠 쓰는 구조로 바뀐 결과이고
    #    (왕복 수는 그대로), 카드가 그려지는 **순서와 개수**를 보는 이 검사의 취지는 그대로입니다.
    async def _spy_card(client, user_id, account, market, *, bundle=None):
        drawn.append(account.get("window_type"))

    stub = _UiStub([])
    stub.row = lambda *a, **k: _RowSpy()
    page.ui = stub
    page._render_account_card = _spy_card
    try:
        market = {"index": {}, "metadata": None, "price_lookup": lambda *_a: None,
                  "as_of": "2026-08-20"}
        asyncio.run(page._render_accounts(object(), "uid-1", SYNTHETIC_KRW_ACCOUNTS,
                                          market, lambda: None))
    finally:
        page.ui = saved_ui
        page._render_account_card = saved_card

    assert drawn == ["M1", "M3", "M6"]
    assert "w-full gap-4 items-stretch" in rows, (
        "원화 전용 경로의 카드 줄 클래스가 바뀌었습니다 — 화면 배치가 달라집니다."
    )


def test_krw_notices_and_helpers_kept_their_exact_wording():
    """원화 문구·시간대의 실제 문장 내용이 한 글자도 바뀌지 않았는지(이 라운드의 최우선
    제약). 2026-08-21 가독성 개선(오너 요청 — 문단이 너무 빽빽해서 읽기 힘들다)으로
    문장 사이에 `\\n\\n` 만 추가됐고, 그 외 단어·조사·순서는 그대로입니다.
    """
    import web.pages.duel_page as page

    assert page.NOTICE_FILL_TIMING == (
        "주문은 저장 즉시 체결되지 않습니다.\n\n저장한 주문은 예약일 뿐이고, "
        "다음 거래일(D+1)의 장이 끝난 뒤 확정된 종가로 그날 밤 배치가 체결합니다."
    )
    assert page.NOTICE_FILL_TIMING.replace("\n\n", " ") == (
        "주문은 저장 즉시 체결되지 않습니다. 저장한 주문은 예약일 뿐이고, "
        "다음 거래일(D+1)의 장이 끝난 뒤 확정된 종가로 그날 밤 배치가 체결합니다."
    ), "문장 사이 줄바꿈을 다시 공백으로 되돌리면 원래 문구와 완전히 같아야 합니다."
    # 🔁 2026-08-21 — `NOTICE_BUY_ONLY` 는 **사실이 바뀌어** 다시 썼습니다(옛 문장:
    #    "이 모듈은 매수만 가능합니다. / 매도는 지원하지 않습니다 …"). 그 검사는 아래
    #    §10 의 리밸런싱 매도 절로 옮겼습니다 — 이 함수는 "이번 라운드가 원화 문구를
    #    건드리지 않았는가"를 보는 자리이므로, 의도적으로 바꾼 문구는 여기서 고정하지
    #    않습니다(안 그러면 두 자리가 서로 반대되는 것을 주장하게 됩니다).
    assert page.ORDER_WINDOW_TEXT == "18:00:01~22:00:00 (한국시간)"
    assert page.CURRENCY == "KRW"


def test_krw_order_form_still_targets_the_kospi_universe():
    """원화 주문 폼이 여전히 `MARKET_KR` 로만 종목을 찾는지."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_order_form"])
    assert "MARKET_KR" in src
    assert "MARKET_US" not in src, "원화 주문 폼에 미국 시장이 섞여 들어갔습니다."

    usd_src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_order_form_usd"])
    assert "MARKET_US" in usd_src
    assert "MARKET_KR" not in usd_src, "달러 주문 폼에 한국 시장이 섞여 들어갔습니다."


def test_us_universe_loader_reuses_the_shared_index_builder_and_us_metadata_key():
    """미국 목록을 읽는 두 번째 경로를 만들지 않았는지 + 메타데이터 키가 미국용인지."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_load_us_universe"])
    assert "build_universe_index" in src, (
        "'내 성적표'·'미국주식'이 이미 쓰는 build_universe_index() 를 재사용해야 합니다(§0-3-10)."
    )
    assert "SNAPSHOT_FILENAMES[MARKET_US]" in src
    assert "last_updated_at_kst" in src, (
        "미국 스냅샷의 시각 키는 last_updated_at_kst 입니다 — 원화 키(last_updated_at)를 "
        "쓰면 조용히 None 이 되어 '언제 기준 값인지'가 화면에서 사라집니다."
    )


def test_page_still_has_exactly_one_route_and_no_new_url_was_added():
    """이번 라운드는 기존 `/duel` 을 확장한 것이라 새 URL 이 생기면 안 됩니다."""
    routes = [
        node.args[0].value
        for node in ast.walk(PAGE_TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "page" and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert routes == ["/duel"], f"경로가 정확히 /duel 하나여야 합니다: {routes}"


def test_every_usd_db_call_goes_through_run_blocking_on_an_async_function():
    """🔴 이벤트 루프 보호 — 달러 DB 호출도 전부 스레드로 넘깁니다.

    2026-08-21 사고(`web/blocking.py` 머리말) 이후 이 화면의 Supabase 왕복은 예외 없이
    `run_blocking()` 을 거칩니다. 달러 블록이 그 규율에서 빠지면 계좌 3개 × 왕복 3회가
    다시 이벤트 루프 위로 올라와, 한 사람이 화면을 여는 동안 접속자 전원의 연결이 끊깁니다.
    """
    for name, node in FUNCTIONS.items():
        direct = {call for call in _calls_in(node) if call in USD_DB_FUNCTIONS}
        assert not direct, (
            f"{name}() 이 {sorted(direct)} 를 이벤트 루프 위에서 직접 부릅니다 — "
            "run_blocking() 으로 넘겨야 합니다."
        )
        # ⚠️ 중첩 함수(버튼 핸들러)는 **자기 자신이** `async def` 이면 되므로 바깥 함수까지
        #    async 여야 한다고 보면 안 됩니다(원화 `_render_opt_in()` 도 동기 함수입니다).
        #    그래서 중첩 함수 안으로는 내려가지 않고 **자기 본문에 직접 있는** 것만 셉니다.
        if any(target.endswith("_usd") for target, _a, _k in _own_run_blocking_calls(node)):
            assert isinstance(node, ast.AsyncFunctionDef), (
                f"{name}() 이 run_blocking 을 직접 쓰는데 async 함수가 아닙니다."
            )


def test_usd_card_and_orders_render_chain_is_async_end_to_end():
    """`_render_duel_section` → 달러 카드/주문 사슬이 중간에 동기로 끊기지 않는지."""
    for name in ("_render_duel_section", "_render_accounts", "_render_account_card_usd",
                 "_render_orders_section_usd", "_render_account_orders_usd"):
        assert isinstance(FUNCTIONS[name], ast.AsyncFunctionDef), (
            f"{name}() 이 동기 함수입니다 — 그 지점에서 이벤트 루프가 다시 막힙니다."
        )


# =============================================================================
# 10. 🔁 주기적 리밸런싱 **매도** (2026-08-21 오너 정정 — 원화·달러 공통)
# =============================================================================
#  ── 이 절이 왜 생겼는가 ──────────────────────────────────────────────────────
#  이 모듈은 "매도는 영원히 없다"를 스키마·작업지시서·화면 문구·테스트에까지 박아 두고
#  만들어졌습니다. 2026-08-21 오너가 그 결정 자체가 **이전 라운드의 대화 착오**였음을
#  확인해 정정했고(계좌마다 30/90/180일 주기로 딱 1회 리밸런싱 매도), 그래서 이번 라운드는
#  **사실이 반대로 바뀐 자리들**을 고칩니다. 이 절이 고정하려는 사고는 두 종류입니다.
#    ① 🔴 **낡은 문구가 살아남는 것** — "매도는 지원하지 않습니다"가 한 군데라도 남으면
#       화면이 사실과 반대인 말을 합니다(§0-1). 특히 규칙 3 은 "매도가 안 되니까 계좌를
#       3개로 나눴다"를 **논거로** 쓰고 있었으므로, 문장 몇 개를 지우는 것으로는 부족하고
#       근거 자체가 바뀌었는지를 봐야 합니다.
#    ② 🔴 **창 판정이 두 벌이 되는 것** — 창 길이·창 번호는 규칙 계층
#       (`resolve_rebalance_window()`)에만 있어야 하고, 화면이 30/90/180 을 다시 세면
#       규칙이 바뀔 때 화면만 낡습니다(§0-3-10).
# =============================================================================
def _capture_render(fn, *args, **kwargs):
    """화면 함수를 스텁 위젯으로 실제 실행하고, 화면에 나간 문자열을 하나로 이어 돌려줍니다.

    `web/components/widgets.py` 의 배너들도 `ui` 를 통해 그리므로 두 모듈을 함께 갈아끼웁니다
    (이 파일 위쪽 `_RenderHarness` 와 같은 방식).
    """
    import web.components.widgets as widgets
    import web.pages.duel_page as page

    sink = []
    stub = _UiStub(sink)
    saved = (page.ui, widgets.ui)
    page.ui, widgets.ui = stub, stub
    try:
        fn(*args, **kwargs)
    finally:
        page.ui, widgets.ui = saved
    return "\n".join(sink)


def _today_kst():
    return datetime.now(KST).date()


# -----------------------------------------------------------------------------
# 10-1. 고지 문구 — "매도 없음"이 한 글자도 남아 있지 않아야 합니다
# -----------------------------------------------------------------------------
def test_buy_only_notices_now_describe_the_rebalancing_sell():
    """`NOTICE_BUY_ONLY` / `_USD` 가 **매수 + 주기당 1회 매도 기회**를 말하는지.

    🗣️ 2026-08-22 오너 리뷰 — 사실은 그대로이고 **부르는 말**만 바뀌었습니다("'창'보다도
       '매도 기회'라고 하는게 직관적으로 이해될 것 같아"). 그래서 이 검사도 사실 목록은
       그대로 두고, 문장이 "매도 기회"를 주어로 세우는지를 함께 봅니다.
    """
    import web.pages.duel_page as page

    for name, text in (("NOTICE_BUY_ONLY", page.NOTICE_BUY_ONLY),
                       ("NOTICE_BUY_ONLY_USD", page.NOTICE_BUY_ONLY_USD)):
        # ① 옛 사실이 남아 있으면 화면이 사실과 반대인 말을 합니다.
        assert "매도는 지원하지 않습니다" not in text, f"{name} 에 옛 '매도 없음' 문구가 남아 있습니다."
        assert "매수만 가능합니다" not in text, f"{name} 이 아직 '매수만 가능'이라고 말합니다."
        assert "팔 수 없" not in text, f"{name} 에 '팔 수 없다'는 옛 서술이 남아 있습니다."
        # ② 새 사실 — 주기마다 1회, 종목 1개, 1주~전량, 기회는 누적되지 않음.
        assert "매도 기회는 주기마다 딱 한 번" in text, (
            f"{name} 이 '주기당 매도 기회 1회'를 말하지 않습니다."
        )
        assert "1주부터 전량까지" in text, f"{name} 이 매도 수량 범위를 말하지 않습니다."
        assert "다음 기회에 쌓이지 않습니다" in text, (
            f"{name} 이 '놓친 기회는 누적되지 않는다'를 말하지 않습니다(스펙 확정 ②)."
        )
        # ②-1 🗣️ 오너 리뷰 — 문장의 주어가 "창"이 아니라 "매도 기회"여야 합니다.
        assert "매도 기회" in text, f"{name} 이 '매도 기회'라는 말을 쓰지 않습니다."
        assert "창" not in text, (
            f"{name} 에 '창' 표현이 남아 있습니다 — 사용자에게는 '매도 기회'로만 "
            "말합니다(코드 쪽 window_index/window_type 은 그대로 둡니다)."
        )
        # ③ 창 길이 세 개가 전부 문구에 들어 있는지(규칙 계층 값 그대로).
        for window_type, window_days in duel_rules.REBALANCE_WINDOW_DAYS.items():
            assert f"{window_days}일" in text, f"{name} 에 {window_type} 창 길이가 없습니다."
        # ④ 창을 세는 기준이 개설일이 아니라 **최초 보유일**이라는 사실.
        assert "처음 주식이 들어온 날" in text, (
            f"{name} 이 창 계산의 기준일을 말하지 않습니다 — 이걸 안 적으면 사용자는 "
            "개설일부터 세는 줄 압니다."
        )

    # 두 문구는 서로 복사본이 아니어야 합니다(달러 쪽은 '원화와 따로 센다'가 더 붙습니다).
    assert page.NOTICE_BUY_ONLY != page.NOTICE_BUY_ONLY_USD
    # 상시 노출 목록의 자리·개수는 그대로입니다(고지는 여전히 원화 3종 / 달러 4종).
    assert page.NOTICE_BUY_ONLY in page.MANDATORY_NOTICES
    assert page.NOTICE_BUY_ONLY_USD in page.MANDATORY_NOTICES_USD
    assert len(page.MANDATORY_NOTICES) == 3 and len(page.MANDATORY_NOTICES_USD) == 4


def test_rebalance_window_text_is_built_from_the_rule_layer_constant():
    """§0-3-10 — 화면이 30/90/180 을 따로 적어두지 않고 규칙 계층에서 만들어 씁니다."""
    import web.pages.duel_page as page

    expected = " · ".join(
        f'{page.WINDOW_TITLES[window_type]} {duel_rules.REBALANCE_WINDOW_DAYS[window_type]}일'
        for window_type in duel_rules.ACCOUNT_WINDOW_TYPES
    )
    assert page.REBALANCE_WINDOW_TEXT == expected
    # 통화를 모르는 값이므로 **하나만** 있어야 합니다(원화용/달러용으로 갈리면 안 됩니다).
    assert not hasattr(page, "REBALANCE_WINDOW_TEXT_USD"), (
        "창 길이는 통화와 무관한 값입니다 — 달러용 복제본을 만들면 한쪽만 낡습니다(§5-11-1)."
    )


def test_join_cards_no_longer_say_buy_only():
    """참여(옵트인) 카드의 '매수만 가능' 불릿이 두 트랙 모두 바뀌었는지."""
    for name in ("_render_opt_in", "_render_opt_in_usd"):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert "거래는 **매수만** 가능" not in src, f"{name}() 에 옛 '매수만' 불릿이 남아 있습니다."
        assert "REBALANCE_WINDOW_TEXT" in src, (
            f"{name}() 이 리밸런싱 주기를 안내하지 않습니다."
        )


def test_order_form_headings_dropped_the_buy_only_qualifier():
    """주문 폼 제목·버튼에서 '(매수 전용)'/'(매수)' 표기가 빠졌는지."""
    assert "주문하기 (매수 전용)" not in PAGE_SRC
    assert "주문 저장 (매수)" not in PAGE_SRC
    assert "'#### 🛒 주문하기'" in PAGE_SRC
    assert "'#### 💵 달러 주문하기'" in PAGE_SRC
    assert "'🛒 매수 주문 저장'" in PAGE_SRC
    assert "'💵 달러 매수 주문 저장'" in PAGE_SRC


# -----------------------------------------------------------------------------
# 10-2. 규칙 3 — 근거 자체가 바뀌었는지 (문장 몇 개 지우는 것으로는 부족합니다)
# -----------------------------------------------------------------------------
def test_krw_rule_three_no_longer_argues_that_selling_is_impossible():
    """원화 규칙 3 이 "매도가 안 되니까 3개"라는 **논거**를 더 이상 쓰지 않는지."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_rules_expansion"])

    for dead in ("매도는 지원하지 않습니다", "한 번 산 종목은",
                 "팔고 갈아탈 방법이 없습니다", "세 계좌의 차이는 규칙이 아니라 선택입니다"):
        assert dead not in src, (
            f"규칙 설명에 옛 논거/제목이 남아 있습니다: {dead!r} — 이 전제는 이제 사실이 "
            "아닙니다(2026-08-21 오너 정정)."
        )
    # 새 근거: 세 계좌가 서로 다른 **주기**로 리밸런싱한다.
    assert "규칙 3) 세 계좌의 차이는 '손보는 주기'입니다" in src
    assert "리밸런싱" in src and "주기마다 1회로 제한되는 것은" in src
    assert "예시)" in src, "규칙 3 에 '예시)' 줄이 사라졌습니다(이 화면의 읽기 방식)."
    # 번호 목록·구분선 관례가 유지되는지(형식 회귀).
    assert src.count("---\\n\\n") >= 9
    assert "vh-rule-divider" in src


def test_usd_rules_expansion_now_has_the_three_accounts_rule_too():
    """달러 규칙 설명에도 같은 규칙이 **같은 자리(3번)** 로 들어왔는지."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_rules_expansion_usd"])

    assert "규칙 3) 세 달러 계좌의 차이는 '손보는 주기'입니다" in src, (
        "달러 규칙 설명에 '왜 계좌가 3개인지' 규칙이 없습니다(원화와 같은 자리여야 합니다)."
    )
    assert "예시)" in src
    # 뒤 규칙들이 하나씩 밀렸는지 — 번호가 겹치거나 빠지면 사용자가 규칙을 찾지 못합니다.
    for number in range(1, 12):
        assert f"**규칙 {number})" in src, f"달러 규칙 {number} 번이 없습니다(번호가 밀리다 빠짐)."
    assert "**규칙 12)" not in src

    # 창 길이는 두 판이 **같은 규칙 상수**를 씁니다(숫자를 다시 적지 않았는지).
    for name in ("_render_rules_expansion", "_render_rules_expansion_usd"):
        body = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert "duel_rules.REBALANCE_WINDOW_DAYS" in body, (
            f"{name}() 이 창 길이를 규칙 계층에서 가져오지 않습니다(§0-3-10)."
        )


# -----------------------------------------------------------------------------
# 10-3. 매도 폼 배선 — 두 통화 모두, 각자의 저장 함수·거래일 후보로
# -----------------------------------------------------------------------------
def test_sell_panels_save_through_the_matching_currency_function():
    """매도 저장이 통화별로 **다른 함수·다른 거래일 후보**를 쓰는지(AST)."""
    krw = [c for c in _run_blocking_calls(FUNCTIONS["_render_sell_panel"])
           if c[0] == "save_sell_order"]
    assert len(krw) == 1, f"원화 매도 저장 호출이 정확히 1건이어야 합니다: {krw}"
    krw_days = {kw.arg: kw.value for kw in krw[0][2]}.get("trading_days")
    assert (isinstance(krw_days, ast.Call) and isinstance(krw_days.func, ast.Name)
            and krw_days.func.id == "_upcoming_trading_days"), (
        "원화 매도가 원화용 거래일 후보(저장일 **다음 날**부터)를 넘기지 않습니다."
    )

    usd = [c for c in _run_blocking_calls(FUNCTIONS["_render_sell_panel_usd"])
           if c[0] == "save_sell_order_usd"]
    assert len(usd) == 1, f"달러 매도 저장 호출이 정확히 1건이어야 합니다: {usd}"
    usd_days = {kw.arg: kw.value for kw in usd[0][2]}.get("trading_days")
    assert (isinstance(usd_days, ast.Call) and isinstance(usd_days.func, ast.Name)
            and usd_days.func.id == "_upcoming_trading_days_usd"), (
        "달러 매도가 `_upcoming_trading_days_usd()` 를 넘기지 않습니다 — 원화용을 넘기면 "
        "체결이 조용히 하루 밀립니다(§5-16, 매수에서 실제로 났던 사고)."
    )

    # 첫 인자는 두 경우 모두 이 접속 전용 클라이언트여야 합니다(§0-3-8).
    for target, args, _kw in krw + usd:
        assert args and isinstance(args[0], ast.Name) and args[0].id == "client", target


def test_sell_panels_ask_the_rule_layer_for_the_window_number():
    """§0-3-10 — 화면이 창 번호를 스스로 세지 않고 규칙 함수에 물어봅니다."""
    for name in ("_render_sell_panel", "_render_sell_panel_usd"):
        used = _referenced_callables(FUNCTIONS[name])
        assert "_rebalance_state" in used, f"{name}() 이 창 상태 계산을 공유 함수에 맡기지 않습니다."
        assert "resolve_rebalance_window" in used, (
            f"{name}() 이 저장 직전에 창 번호를 다시 계산하지 않습니다 — 화면을 열어둔 채 "
            "창이 바뀌면 지난 창의 자리에 주문이 들어갑니다."
        )
        # 창 길이를 화면이 다시 세지 않는지.
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert "REBALANCE_WINDOW_DAYS" not in src


def test_sell_panels_recheck_the_owner_like_every_other_account_renderer():
    """🔒 §0-3-8 이중 방어 — 계좌를 그리는 새 함수에도 소유자 확인이 있는지."""
    for name in ("_render_sell_panel", "_render_sell_panel_usd"):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert 'account.get("user_id") != user_id' in src, f"{name}() 에 소유자 확인이 없습니다."
        args = [a.arg for a in FUNCTIONS[name].args.args]
        assert "client" in args and "user_id" in args, f"{name}{tuple(args)}"


def test_sell_form_is_reachable_even_when_the_universe_snapshot_is_missing():
    """매도에는 유니버스 검사가 없으므로, 목록을 못 읽는 날에도 매도 칸은 열려야 합니다.

    (`save_sell_order()` 독스트링: 보유 종목이 상위 목록에서 빠졌다고 "팔 수도 없는" 상태가
    되면 그게 더 나쁩니다 — 그래서 그 함수에는 `universe_tickers` 인자 자체가 없습니다.)
    """
    for form, sell in (("_render_order_form", "_render_sell_form"),
                       ("_render_order_form_usd", "_render_sell_form_usd")):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[form])
        assert src.count(f"{sell}(") >= 2, (
            f"{form}() 이 유니버스를 못 읽어 일찍 반환하는 경로에서 {sell}() 를 부르지 "
            "않습니다 — 그날은 매도 칸이 통째로 사라집니다."
        )


# -----------------------------------------------------------------------------
# 10-4. 창 상태 계산 — 순수 함수의 실제 동작
# -----------------------------------------------------------------------------
def test_rebalance_state_does_not_crash_before_the_first_buy():
    """🔴 `first_holding_date` 가 없으면 **예외가 화면까지 올라오면 안 됩니다**(§0-1)."""
    import web.pages.duel_page as page

    account = {"id": "a1", "user_id": "u1", "window_type": "M1", "first_holding_date": None}
    state = page._rebalance_state(account, [], _today_kst())
    assert state["window"] is None
    assert state["used_order"] is None
    assert state["unavailable_reason"], "왜 계산할 수 없는지 사유가 비어 있습니다."
    assert "리밸런싱 창을 계산할 수 없습니다" in state["unavailable_reason"]

    badge = page._rebalance_badge_text(state)
    assert "아직 계산할 수 없습니다" in badge and "첫 매수 전" in badge


def test_rebalance_state_counts_only_live_sell_orders_of_this_window():
    """취소된 매도·다른 창의 매도·매수는 이번 창을 소진하지 않습니다(DB 인덱스와 같은 조건)."""
    import web.pages.duel_page as page

    account = {"id": "a1", "user_id": "u1", "window_type": "M1",
               "first_holding_date": "2020-01-01"}
    today = _today_kst()
    current = duel_rules.resolve_rebalance_window("M1", "2020-01-01", today)
    index = current["window_index"]

    # ① 아무 매도도 없을 때.
    empty = page._rebalance_state(account, [], today)
    assert empty["window"]["window_index"] == index
    assert empty["used_order"] is None

    # ② 관계없는 주문들만 있을 때 — 전부 이번 창을 소진하지 않습니다.
    irrelevant = [
        {"id": "o-buy", "side": "buy", "status": "filled", "rebalance_window_index": None},
        {"id": "o-cancelled", "side": "sell", "status": "cancelled",
         "rebalance_window_index": index},
        {"id": "o-other-window", "side": "sell", "status": "pending",
         "rebalance_window_index": index - 1},
    ]
    assert page._rebalance_state(account, irrelevant, today)["used_order"] is None, (
        "취소된 매도/다른 창의 매도/매수 중 하나가 이번 창을 소진시키고 있습니다 — "
        "DB 부분 유니크 인덱스(status <> 'cancelled')와 조건이 어긋납니다."
    )

    # ③ 살아 있는 이번 창의 매도가 있으면 소진 — pending 도 filled 도 모두.
    for status in ("pending", "filled"):
        rows = irrelevant + [{"id": f"o-{status}", "side": "sell", "status": status,
                              "ticker": "005930", "stock_name": "삼성전자",
                              "requested_quantity": 2, "rebalance_window_index": index}]
        used = page._rebalance_state(account, rows, today)["used_order"]
        assert used is not None and used["id"] == f"o-{status}"

    badge = page._rebalance_badge_text(
        page._rebalance_state(account, [
            {"id": "o", "side": "sell", "status": "pending", "rebalance_window_index": index},
        ], today))
    assert "이미 사용했습니다" in badge
    assert str(current["next_window_starts_on"]) in badge, (
        "이미 쓴 창의 뱃지가 '다음 기회' 날짜를 말하지 않습니다."
    )


def test_rebalance_badge_counts_the_window_from_one_for_humans():
    """저장값은 0부터, 표시값은 1부터 — 둘이 섞이지 않는지."""
    import web.pages.duel_page as page

    account = {"id": "a1", "user_id": "u1", "window_type": "M1",
               "first_holding_date": _today_kst()}
    state = page._rebalance_state(account, [], _today_kst())
    assert state["window"]["window_index"] == 0
    badge = page._rebalance_badge_text(state)
    assert "1번째 기회" in badge and "0번째 기회" not in badge
    assert f'{duel_rules.REBALANCE_WINDOW_DAYS["M1"]}일 남음' in badge


def test_sellable_positions_keeps_everything_it_can_actually_sell():
    """0주 포지션만 빠지고, 상장폐지 종목은 **조용히 사라지지 않습니다**(§0-1)."""
    import web.pages.duel_page as page

    rows = page._sellable_positions([
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 3, "status": "active"},
        {"ticker": "000660", "stock_name": "SK하이닉스", "quantity": 0, "status": "active"},
        {"ticker": "DEAD", "stock_name": "상장폐지사", "quantity": 1, "status": "delisted"},
    ])
    tickers = [row["ticker"] for row in rows]
    assert "000660" not in tickers, "0주 포지션은 팔 수 없습니다."
    assert tickers == ["005930", "DEAD"], f"상장폐지 종목이 목록에서 사라졌습니다: {tickers}"


# -----------------------------------------------------------------------------
# 10-5. 실제 렌더 — 창을 이미 썼으면 버튼이 없어야 합니다
# -----------------------------------------------------------------------------
_SELL_ACCOUNT = {"id": "krw-m1", "user_id": "uid-1", "window_type": "M1",
                 "anchor_date": "2026-08-03", "first_holding_date": "2020-01-01"}
_SELL_ACCOUNT_USD = {"id": "usd-m1", "user_id": "uid-1", "window_type": "M1",
                     "anchor_date": "2026-08-05", "first_holding_date": "2020-01-01"}
_SELL_POSITIONS = [{"ticker": "005930", "stock_name": "삼성전자", "quantity": 4,
                    "avg_cost": 70000.0, "status": "active"}]


def _open_window():
    import web.pages.duel_page as page
    return page._order_window_state(datetime(2026, 8, 19, 19, 0, 0, tzinfo=KST))


def _open_window_usd():
    import web.pages.duel_page as page
    return page._order_window_state_usd(datetime(2026, 8, 19, 17, 0, 0, tzinfo=KST))


def test_sell_panel_offers_the_button_when_the_window_is_free():
    import web.pages.duel_page as page

    blob = _capture_render(
        page._render_sell_panel, object(), "uid-1", _SELL_ACCOUNT, _open_window(),
        lambda: None,
        bundle={"positions": _SELL_POSITIONS, "orders": [], "error": None})

    assert "🔁 리밸런싱 매도 주문 저장" in blob, "매도 기회가 남았는데 매도 버튼이 없습니다."
    assert "이미 사용했습니다" not in blob
    assert "이번 기회 아직 안 씀" in blob


def test_sell_panel_hides_the_button_and_names_the_next_chance_when_used():
    """🔴 이번 창을 이미 썼으면 버튼이 사라지고 **다음 기회 날짜**를 말해야 합니다."""
    import web.pages.duel_page as page

    today = _today_kst()
    window = duel_rules.resolve_rebalance_window("M1", "2020-01-01", today)
    used = {"id": "o1", "side": "sell", "status": "pending", "ticker": "005930",
            "stock_name": "삼성전자", "requested_quantity": 2,
            "rebalance_window_index": window["window_index"]}

    blob = _capture_render(
        page._render_sell_panel, object(), "uid-1", _SELL_ACCOUNT, _open_window(),
        lambda: None,
        bundle={"positions": _SELL_POSITIONS, "orders": [used], "error": None})

    assert "🔁 리밸런싱 매도 주문 저장" not in blob, (
        "이번 창을 이미 썼는데 매도 버튼이 그대로 있습니다 — DB 가 막긴 하지만 사용자는 "
        "누를 수 있다고 착각하게 됩니다."
    )
    assert "이번 매도 기회는 이미 사용했습니다" in blob
    assert str(window["next_window_starts_on"]) in blob, "다음 기회 날짜가 없습니다."


def test_sell_panel_is_informational_before_the_first_buy():
    """첫 매수 전 — 예외가 아니라 **안내**로 끝나야 합니다(계좌 카드가 사라지면 안 됩니다)."""
    import web.pages.duel_page as page

    account = dict(_SELL_ACCOUNT, first_holding_date=None)
    blob = _capture_render(
        page._render_sell_panel, object(), "uid-1", account, _open_window(), lambda: None,
        bundle={"positions": [], "orders": [], "error": None})

    assert "아직 매수한 종목이 없어 리밸런싱 매도를 계산할 수 없습니다" in blob
    assert "🔁 리밸런싱 매도 주문 저장" not in blob


def test_usd_sell_panel_behaves_the_same_but_speaks_dollars():
    import web.pages.duel_page as page

    blob = _capture_render(
        page._render_sell_panel_usd, object(), "uid-1", _SELL_ACCOUNT_USD, _open_window_usd(),
        lambda: None,
        bundle={"positions": [{"ticker": "AAPL", "stock_name": "Apple Inc.", "quantity": 3,
                               "avg_cost": 200.0, "status": "active"}],
                "orders": [], "error": None})

    assert "🔁 달러 리밸런싱 매도 주문 저장" in blob
    assert "(달러)" in blob


def test_sell_panel_refuses_a_bundle_it_could_not_read():
    """§0-1 — 못 읽은 것을 '보유 없음'으로 위장하지 않습니다."""
    import web.pages.duel_page as page

    blob = _capture_render(
        page._render_sell_panel, object(), "uid-1", _SELL_ACCOUNT, _open_window(), lambda: None,
        bundle={"positions": None, "orders": None, "error": None})
    assert "읽지 못해 매도 창을 열 수 없습니다" in blob
    assert "🔁 리밸런싱 매도 주문 저장" not in blob


def test_a_sell_panel_for_someone_elses_account_is_not_drawn():
    """🔒 §0-3-8 이중 방어 — 남의 계좌의 매도 칸은 그리지 않습니다."""
    import web.pages.duel_page as page

    banners = []
    saved = page.error_banner
    page.error_banner = lambda text: banners.append(str(text))
    try:
        blob = _capture_render(
            page._render_sell_panel, object(), "uid-1",
            dict(_SELL_ACCOUNT, user_id="uid-someone-else"), _open_window(), lambda: None,
            bundle={"positions": _SELL_POSITIONS, "orders": [], "error": None})
    finally:
        page.error_banner = saved

    assert any("소유자가 확인되지 않는" in text for text in banners), banners
    assert "🔁 리밸런싱 매도 주문 저장" not in blob


# -----------------------------------------------------------------------------
# 10-6. 주문 내역 — 매수/매도 구분 칸
# -----------------------------------------------------------------------------
def test_order_history_tables_have_a_buy_sell_column_in_both_currencies():
    import web.pages.duel_page as page

    orders = [
        {"ticker": "005930", "stock_name": "삼성전자", "side": "buy", "status": "filled",
         "filled_quantity": 3, "filled_price": 70000.0, "filled_amount": 210000.0,
         "filled_date": "2026-08-18", "rebalance_window_index": None},
        {"ticker": "005930", "stock_name": "삼성전자", "side": "sell", "status": "filled",
         "filled_quantity": 2, "filled_price": 71000.0, "filled_amount": 142000.0,
         "filled_date": "2026-08-20", "rebalance_window_index": 0},
    ]
    blob = _capture_render(page._render_order_history_table, orders)
    assert "구분" in blob, "매수/매도 구분 칸이 없습니다."
    assert "🛒 매수" in blob and "🔁 매도 (1번째 기회)" in blob
    # 기존 칸이 그대로 남아 있는지(회귀).
    for header in ("종목", "상태", "체결일", "체결가", "체결금액", "사유"):
        assert header in blob

    blob_usd = _capture_render(page._render_order_history_table_usd, [
        dict(orders[1], ticker="AAPL", stock_name="Apple Inc.", filled_price=200.0,
             filled_amount=400.0),
    ])
    assert "구분" in blob_usd and "🔁 매도 (1번째 기회)" in blob_usd
    assert "$200.00" in blob_usd, "달러 표기가 사라졌습니다."


def test_order_side_text_never_guesses_an_unknown_side():
    """§0-1 — side 를 모르면 '매수'로 위장하지 않습니다(옛 행에는 side 가 없을 수 있습니다)."""
    import web.pages.duel_page as page

    assert page._order_side_text({"side": "buy"}) == "🛒 매수"
    assert page._order_side_text({"side": "sell"}) == "🔁 매도"
    assert page._order_side_text({"side": "sell", "rebalance_window_index": 2}) == "🔁 매도 (3번째 기회)"
    assert page._order_side_text({}) == "—"
    assert page._order_side_text({"side": "weird"}) == "weird"


def test_pending_rows_show_the_side_in_both_currencies():
    for name in ("_render_pending_order_row", "_render_pending_order_row_usd"):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        assert "_order_side_text(order)" in src, (
            f"{name}() 이 대기 주문의 매수/매도를 표시하지 않습니다 — 두 방향이 한 목록에 "
            "섞이는데 방향이 없으면 어느 쪽인지 알 수 없습니다."
        )


# -----------------------------------------------------------------------------
# 10-7. 왕복 수 — 매도 칸 때문에 조회가 늘어나지 않았는지 (§0-3-2 의 정신)
# -----------------------------------------------------------------------------
def test_positions_and_orders_are_read_once_per_account_not_twice():
    """계좌별 포지션·주문은 **한 번씩만** 읽고 카드·주문 폼·주문 내역이 나눠 씁니다."""
    with _RenderHarness(SYNTHETIC_KRW_ACCOUNTS, SYNTHETIC_USD_ACCOUNTS) as harness:
        harness.run()

    for name, accounts in (("fetch_my_positions", SYNTHETIC_KRW_ACCOUNTS),
                           ("fetch_my_orders", SYNTHETIC_KRW_ACCOUNTS),
                           ("fetch_my_positions_usd", SYNTHETIC_USD_ACCOUNTS),
                           ("fetch_my_orders_usd", SYNTHETIC_USD_ACCOUNTS)):
        assert harness.calls.count(name) == len(accounts), (
            f"{name} 을 계좌 수({len(accounts)})보다 많이/적게 불렀습니다: "
            f"{harness.calls.count(name)}회. 매도 칸이 같은 값을 또 읽고 있지 않은지 "
            "확인하세요(이 화면은 이 프로젝트에서 왕복이 가장 많은 화면입니다)."
        )


def test_the_two_bundle_loaders_never_touch_each_others_tables():
    """§5-11-2 — 묶음을 읽는 함수도 통화별로 갈라져 있어야 합니다."""
    krw = _referenced_callables(FUNCTIONS["_load_account_data"])
    usd = _referenced_callables(FUNCTIONS["_load_account_data_usd"])
    assert {"fetch_my_positions", "fetch_my_orders"} <= krw
    assert not ({"fetch_my_positions_usd", "fetch_my_orders_usd"} & krw)
    assert {"fetch_my_positions_usd", "fetch_my_orders_usd"} <= usd
    assert not ({"fetch_my_positions", "fetch_my_orders"} & usd)


# =============================================================================
# 11. 📊 '내 성적표' 카드의 **넓은** 현재가 폴백 (2026-08-22 오너 실사용 버그)
# =============================================================================
#  ── 무슨 사고였나 ────────────────────────────────────────────────────────────
#  결투 계좌 줄 맨 앞의 "내 성적표" 카드가 사용자의 **실제** 보유 종목을 그리면서, 결투
#  계좌용으로 **일부러 좁혀 둔** 시세 목록(코스피 상위 200 / 미국 상위 유니버스)으로 값을
#  찾고 있었습니다. 그래서 `/scorecard` 화면에서는 멀쩡히 값이 나오는 KRX 상장 ETF
#  (0174R0 · 379810 · 458730)가 결투 화면에서는 "가격을 확인하지 못해 제외"로 빠졌습니다.
#  ── 이 절이 고정하려는 것 ────────────────────────────────────────────────────
#    ① 성적표 카드는 넓은 폴백을 **실제로** 쓴다.
#    ② 결투 계좌의 시세는 **여전히 좁다** — 넓힌 값이 주문 폼·포지션 표로 새면 거래 가능
#       종목의 경계가 화면에서 흐려집니다(그 좁음은 버그가 아니라 설계입니다).
#    ③ 파일을 읽는 **세 번째 경로**를 만들지 않는다(§0-3-10).
# =============================================================================
def test_the_scorecard_card_is_wired_to_the_broad_price_fallback():
    """성적표 카드의 통화별 창구가 넓은 폴백으로 조회 함수를 만드는지(AST)."""
    assert "_load_broad_price_fallbacks" in FUNCTIONS, (
        "넓은 폴백을 읽는 로더가 없습니다 — 성적표 카드는 유니버스 밖 종목도 값매김해야 합니다."
    )

    for wrapper, kwarg, other in (
            ("_render_scorecard_summary_card_krw", "broad_kr_prices", "broad_us_prices"),
            ("_render_scorecard_summary_card_usd", "broad_us_prices", "broad_kr_prices")):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[wrapper])
        assert "make_price_lookup" in src, f"{wrapper}() 이 조회 함수를 만들지 않습니다."
        assert kwarg in src, f"{wrapper}() 이 {kwarg} 폴백을 넘기지 않습니다."
        assert other not in src, (
            f"{wrapper}() 이 다른 시장의 폴백({other})까지 넘깁니다 — 원/달러 조회가 서로의 "
            "목록을 스칠 수 있는 통로가 생깁니다(§5-11-2)."
        )

    # 카드 본문은 결투 계좌용 좁은 조회 함수를 **더 이상 쓰지 않습니다**.
    #  ⚠️ 주석·독스트링을 걷어낸 **코드만** 봅니다 — 이 카드의 독스트링은 "예전에는
    #     market['price_lookup'] 을 썼다"는 사고 경위를 일부러 적어 두고 있습니다.
    card = FUNCTIONS["_render_scorecard_summary_card"]
    card_code = ast.unparse(card)
    assert 'market[\'price_lookup\']' not in card_code, (
        "성적표 카드가 다시 결투 계좌용 좁은 시세로 실제 보유 종목을 찾고 있습니다."
    )
    assert "build_portfolio(holdings, price_lookup)" in card_code

    # 폴백은 화면을 그릴 때 **한 번만** 읽습니다(카드마다 다시 읽지 않도록).
    body = _referenced_callables(FUNCTIONS["_render_body"])
    assert "_load_broad_price_fallbacks" in body, (
        "폴백 목록을 화면 최상단에서 한 번 읽어 내려보내지 않습니다."
    )


def test_the_broad_fallback_loader_reuses_the_scorecard_files_and_merges_us_etfs():
    """§0-3-10 — 파일명·인덱스 만드는 계산을 새로 만들지 않았는지."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_load_broad_price_fallbacks"])
    for constant in ("KR_ALL_MARKET_PRICES_FILENAME", "US_ALL_MARKET_PRICES_FILENAME",
                     "US_ALL_ETF_PRICES_FILENAME"):
        assert constant in src, f"{constant} 을 쓰지 않습니다 — 파일명을 본문에 다시 적지 마세요."
    assert "build_universe_index" in src, (
        "'내 성적표'가 이미 쓰는 build_universe_index() 를 재사용해야 합니다(§0-3-10)."
    )
    assert "load_json_file_async" in src, (
        "파일 읽기는 비동기판으로만 합니다 — 동기로 읽으면 접속자 전원의 루프가 멈춥니다."
    )
    # 미국은 주식/ETF 두 파일을 **읽는 쪽에서** 합칩니다('내 성적표' 화면과 같은 방식).
    assert "{**us_etf_prices, **broad_us_prices}" in src, (
        "미국 ETF 가격 파일을 합치지 않았습니다 — 미국 ETF 보유 종목이 계속 빠집니다."
    )


def test_the_duel_accounts_are_still_priced_by_the_narrow_universe_only():
    """🔴 결투 계좌 쪽 시세는 **여전히 좁아야** 합니다(그 좁음은 설계입니다)."""
    for name in ("_load_kospi_universe", "_load_us_universe"):
        src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[name])
        for leaked in ("broad_kr_prices", "broad_us_prices", "KR_ALL_MARKET_PRICES_FILENAME",
                       "US_ALL_MARKET_PRICES_FILENAME", "US_ALL_ETF_PRICES_FILENAME"):
            assert leaked not in src, (
                f"{name}() 에 넓은 폴백({leaked})이 들어갔습니다 — 결투 계좌는 거래 가능 "
                "유니버스 안에서만 값매김해야 합니다(주문 폼과 같은 목록)."
            )

    # 폴백 값이 흐르는 함수는 **성적표 경로뿐**이어야 합니다.
    allowed = {"_load_broad_price_fallbacks", "_render_body", "duel_section",
               "_render_duel_section", "_render_accounts",
               "_render_scorecard_summary_card_krw", "_render_scorecard_summary_card_usd"}
    carriers = {name for name, node in FUNCTIONS.items()
                if "broad_prices" in _names_used(node)}
    assert carriers <= allowed, (
        f"넓은 폴백이 성적표 카드 밖으로 샜습니다: {sorted(carriers - allowed)} — 결투 "
        "포지션 표·주문 폼이 유니버스 밖 종목까지 값매김하면 거래 가능 종목의 경계가 "
        "화면에서 흐려집니다."
    )
    for name in ("_render_account_card", "_render_account_card_usd", "_render_order_form",
                 "_render_order_form_usd", "_position_rows", "_position_rows_usd"):
        assert "broad_prices" not in _names_used(FUNCTIONS[name]), name


def test_a_krx_etf_outside_the_top200_now_gets_a_real_price(tmp_path):
    """🔴 실제 저장소 데이터로 확인 — 상위 200 밖 ETF 가 값매김되는지.

    `data/kr_all_market_prices.json` 이 없는 체크아웃에서는 건너뜁니다(그 파일은 수집기가
    만드는 스냅샷이라 없을 수 있고, 없으면 화면은 예전처럼 정직하게 "가격 확인 못 함"을
    표시할 뿐이라 이 검사만 성립하지 않습니다).
    """
    from utils.scorecard_db import MARKET_KR, make_price_lookup

    import web.pages.duel_page as page

    if not (REPO_ROOT / "data" / "kr_all_market_prices.json").exists():
        pytest.skip("data/kr_all_market_prices.json 스냅샷이 없는 체크아웃입니다.")

    market = asyncio.run(page._load_kospi_universe())
    broad = asyncio.run(page._load_broad_price_fallbacks())
    narrow = market["price_lookup"]                     # 결투 계좌용(좁음 — 그대로 둡니다)
    wide = make_price_lookup({MARKET_KR: market["index"]},
                             broad_kr_prices=broad["broad_kr_prices"])

    outside = [t for t in ("379810", "458730", "0174R0")
               if t not in (market["index"] or {}) and t in (broad["broad_kr_prices"] or {})]
    if not outside:
        pytest.skip("이 스냅샷에는 상위 200 밖 검증용 ETF 가 들어 있지 않습니다.")

    for ticker in outside:
        assert narrow(MARKET_KR, ticker) is None, (
            f"{ticker} 이 상위 200 스냅샷 안에 들어왔습니다 — 이 검사를 다시 골라야 합니다."
        )
        price = wide(MARKET_KR, ticker)
        assert price is not None and price > 0, (
            f"{ticker} 의 현재가를 넓은 폴백으로도 못 찾았습니다 — '내 성적표' 화면에서는 "
            "나오는 값이라 두 화면이 서로 다른 말을 하게 됩니다."
        )
