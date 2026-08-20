# tests/test_duel_public_ui.py
"""
⚔️ "결투다!" 2갈래(공개 인프라) **화면 2종 + 발행표 조회 계층** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요 · nicegui 설치 여부와 무관)

`DUEL_MODULE_WORK_ORDER.md` 5-2 · 5-3 · 5-6 · 5-7 · 5-8 의 화면 라운드에서 새로 만든 것들을
회귀로 고정합니다. 가짜 Supabase 클라이언트는 **새로 만들지 않고** `tests/test_duel_db.py`
의 `FakeClient` 를 그대로 가져다 씁니다(§0-3-10 — 같은 흉내를 두 벌 만들지 않습니다).

검증 대상
    ① `duel_db.fetch_public_leaderboard*` / `fetch_public_holdings_for_nickname`
       — 맞는 표에, 맞는 필터·정렬·페이지 범위로 가는가. 빈 결과는 정상인가.
       — `select("*")` 를 쓰지 않는가(§0-3-8 — 나중에 컬럼이 늘어도 새어나가지 않게).
    ② 동의 화면의 **핵심 규칙**(위젯 없이 순수 함수로 확인)
       — 5개 전부 아니면 전무(5-2-2) / 최종 확인 분리(5-2-3) /
         독립 동의 분리(5-2-4) / 철회 확인 단계(5-8)
    ③ 화면 문구가 **작업지시서 원문 그대로**인지 — 5-2-1 의 다섯 문장, 5-2-4 의 독립 동의
       문장, 5-3 의 고정 문구 두 문단을 `DUEL_MODULE_WORK_ORDER.md` 에서 직접 읽어 대조합니다.
       (누가 문구를 "다듬으면" 여기서 잡힙니다 — 오너가 확정한 문안이기 때문입니다.)
    ④ 순위표 화면이 원본 표(`duel_positions`·`holdings`·`profiles`·`duel_cash_ledger`)를
       **이름조차 건드리지 않는지**(5-4-5) — 소스 문자열·AST 검사.
    ⑤ 3단계 공개 게이트 배선 — 기본값(전부 꺼짐)에서 메뉴에 새 항목이 없고, 2갈래 화면은
       `DUEL_ENABLED` 없이는 켜지지 않는가(§0-3-6).

⚠️ 여기서 **검증하지 못하는 것**(§0-1 — 할 수 있는 것만 했다고 말합니다):
    · 실제 NiceGUI 위젯이 화면에 어떻게 그려지는지. 이 샌드박스에는 nicegui 가 없어
      아래 `_install_stubs()` 로 최소 스텁을 꽂습니다(`tests/test_web_session_isolation.py`
      의 `_install_nicegui_stub()` 과 같은 방식).
    · 실제 Supabase RLS 가 비로그인 접속을 막는지(그건 `sql/duel_schema.sql` §9-7 의 몫).

실행: pytest tests/test_duel_public_ui.py -v
"""

import ast
import importlib
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))          # from test_duel_db import FakeClient

from test_duel_db import FakeClient                                      # noqa: E402
from utils import duel_db, duel_rules                                    # noqa: E402
from utils.duel_db import DuelDbError                                    # noqa: E402
from utils.duel_rules import DuelRuleError                               # noqa: E402

WORK_ORDER = (REPO_ROOT / "DUEL_MODULE_WORK_ORDER.md").read_text(encoding="utf-8")


def _squash(text):
    """공백 차이를 무시하고 문장을 대조하기 위한 정규화(줄바꿈으로 접힌 문구 비교용)."""
    return re.sub(r"\s+", " ", str(text)).strip()


WORK_ORDER_FLAT = _squash(WORK_ORDER)


# =============================================================================
# 0. 스텁 — nicegui 와 아직 이 스냅샷에 없는 web/* 모듈 (있으면 진짜를 씁니다)
# =============================================================================
def _install_stubs():
    """
    화면 모듈을 import 할 수 있게 최소 스텁을 꽂습니다. **이미 진짜가 있으면 손대지
    않습니다** — 실제 저장소(nicegui·web/auth.py 가 있는 환경)에서는 진짜 모듈로 검사가
    돌아야 하기 때문입니다.
    """
    try:
        import nicegui                                                    # noqa: F401
    except ImportError:
        class _Element:
            def __call__(self, *args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:
                    return args[0]
                return self

            def __getattr__(self, _name):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        element = _Element()

        class _Refreshable:
            def __init__(self, fn):
                self.fn = fn

            def __call__(self, *args, **kwargs):
                return self.fn(*args, **kwargs)

            def refresh(self, *_a, **_k):
                return None

        class _UI(types.ModuleType):
            refreshable = staticmethod(_Refreshable)

            def __getattr__(self, _name):
                return element

        nicegui = types.ModuleType("nicegui")
        nicegui.ui = _UI("nicegui.ui")
        nicegui.app = element
        sys.modules["nicegui"] = nicegui
        sys.modules["nicegui.ui"] = nicegui.ui

    if "web.auth" not in sys.modules:
        try:
            import web.auth                                               # noqa: F401
        except ImportError:
            auth = types.ModuleType("web.auth")
            auth.get_client = lambda: None
            auth.has_supabase_session = lambda: False
            auth.is_admin = lambda: False
            auth.logout = lambda: None
            sys.modules["web.auth"] = auth

    if "web.auth_ui" not in sys.modules:
        try:
            import web.auth_ui                                            # noqa: F401
        except ImportError:
            auth_ui = types.ModuleType("web.auth_ui")
            auth_ui.fail_message = lambda exc, fallback, context=None: str(fallback)
            auth_ui.render_auth = lambda *a, **k: None
            sys.modules["web.auth_ui"] = auth_ui

    if "web.components" not in sys.modules:
        try:
            import web.components                                         # noqa: F401
        except ImportError:
            import html as _html

            components = types.ModuleType("web.components")
            components.__path__ = []               # `web.components.widgets` 도 가짜 패키지로
            components.esc = lambda value: _html.escape(str(value))
            components.pct_text = lambda value: f"{float(value):+.2f}%"

            def _table(headers, rows):
                head = "".join(f"<th>{h}</th>" for h in headers)
                body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                               for row in rows)
                return f"<table><tr>{head}</tr>{body}</table>"

            components.holdings_table_html = _table
            for name in ("error_banner", "warning_banner", "info_banner", "metric_card"):
                setattr(components, name, lambda *a, **k: None)
            sys.modules["web.components"] = components

            # `web/layout.py` 는 `web.components.widgets` 에서 배너를 가져옵니다.
            widgets = types.ModuleType("web.components.widgets")
            for name in ("error_banner", "warning_banner", "info_banner", "metric_card",
                         "esc", "pct_text", "holdings_table_html"):
                setattr(widgets, name, getattr(components, name))
            components.widgets = widgets
            sys.modules["web.components.widgets"] = widgets



# =============================================================================
# 0-b. 소스 검사 도우미 — 주석·docstring 을 걷어내고 **실제 코드만** 봅니다
# =============================================================================
#  이 저장소는 docstring 에 근거를 길게 적는 관례라, 문자열까지 세면 **설명을 잘 쓸수록
#  검사가 실패**합니다. 그건 검사가 잘못된 것이지 코드가 잘못된 게 아닙니다
#  (`tests/test_duel_publish.py::_executable_source()` 와 같은 판단).
def _page_source(name):
    return (REPO_ROOT / "web" / "pages" / name).read_text(encoding="utf-8")


def _code_names(name):
    """그 파일에서 **코드로 등장하는 이름**(식별자·속성) 집합."""
    import io
    import tokenize

    names = set()
    for token in tokenize.generate_tokens(io.StringIO(_page_source(name)).readline):
        if token.type == tokenize.NAME:
            names.add(token.string)
    return names


def _code_numbers(name):
    """docstring 을 뺀 **숫자 리터럴** 집합(§0-3-10 매직넘버 검사용)."""
    tree = ast.parse(_page_source(name))
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)}


def _code_strings(name):
    """docstring 을 뺀 **문자열 리터럴** 집합(표 이름이 숨어 들어왔는지 검사용)."""
    tree = ast.parse(_page_source(name))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value not in docstrings}


_install_stubs()

from web.pages import duel_consent_page as consent_page                  # noqa: E402
from web.pages import duel_leaderboard_page as board_page                # noqa: E402


# =============================================================================
# 1. 발행표 조회 — 맞는 표에, 맞는 필터로 (§0-3-2 · §0-3-8)
# =============================================================================
def _board_rows(count=3, start_rank=1):
    return [{"published_date": "2026-08-20", "window_type": "M1",
             "bracket_key": "krw_10m_30m", "rank": start_rank + i,
             "nickname": f"닉네임{i}", "twr_pct": 1.5 - i}
            for i in range(count)]


def test_latest_published_date_reads_one_row_ordered_desc():
    client = FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): [{"published_date": "2026-08-20"}],
    })
    day = duel_db.fetch_public_leaderboard_latest_date(
        client, window_type="M1", bracket_key="krw_10m_30m")
    assert day == "2026-08-20"

    call = client.only_call(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
    assert call.filter_map == {"window_type": "M1", "bracket_key": "krw_10m_30m"}
    assert call.orders == [("published_date", True)], "최신 발행일이 먼저 와야 합니다"
    assert call.options.get("limit") == 1, "발행일 조회는 한 행이면 충분합니다(§0-3-2)"


def test_latest_published_date_returns_none_when_nothing_published():
    """
    빈 결과는 **오류가 아니라 정상**입니다(5-6 — 최소 인원 미달 그룹은 발행되지 않습니다).
    화면은 이걸 "아직 공개할 만큼 사람이 안 모였습니다"로 안내합니다.
    """
    client = FakeClient()
    assert duel_db.fetch_public_leaderboard_latest_date(
        client, window_type="M6", bracket_key=duel_rules.BRACKET_NONE_KEY) is None


def test_fetch_public_leaderboard_paginates_with_range_and_rank_order():
    client = FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): _board_rows(30),
    })
    rows = duel_db.fetch_public_leaderboard(
        client, window_type="M1", bracket_key="krw_10m_30m",
        published_date="2026-08-20", limit=30, offset=60)
    assert len(rows) == 30

    call = client.only_call(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
    assert call.filter_map == {"window_type": "M1", "bracket_key": "krw_10m_30m",
                               "published_date": "2026-08-20"}
    # rank 오름차순 + 동순위 안에서는 nickname 으로 **순서를 고정**(페이지 경계에서 같은
    # 사람이 두 번 나오거나 건너뛰어지지 않게). 순위를 다시 매기는 것이 아닙니다.
    assert call.orders == [("rank", False), ("nickname", False)]
    assert call.options.get("range") == (60, 89), "range 는 양끝 포함(0-based)"


def test_fetch_public_leaderboard_can_read_from_the_bottom():
    """"하위 500"은 인원을 세지 않고 **정렬을 뒤집어** 읽습니다(§0-3-2)."""
    client = FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): _board_rows(5),
    })
    duel_db.fetch_public_leaderboard(
        client, window_type="M3", bracket_key="krw_100m_plus",
        published_date="2026-08-20", limit=5, offset=0, order_desc=True)
    call = client.only_call(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
    assert call.orders == [("rank", True), ("nickname", True)]


def test_fetch_public_leaderboard_never_selects_star():
    """
    🔴 §0-3-8 — 읽을 컬럼을 하나하나 적습니다. 나중에 발행표에 컬럼이 하나 늘어도 이
    함수가 그것을 화면으로 날라 주지 않게 하려는 구조적 방어입니다.
    """
    for columns in (duel_db.PUBLIC_LEADERBOARD_COLUMNS, duel_db.PUBLIC_HOLDINGS_COLUMNS):
        assert "*" not in columns
        for forbidden in duel_db.FORBIDDEN_PUBLISH_FIELDS:
            assert forbidden not in columns.split(","), \
                f"발행표 조회 컬럼에 식별자({forbidden})가 있습니다"

    client = FakeClient(responses={(duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): []})
    duel_db.fetch_public_leaderboard(client, window_type="M1", bracket_key="krw_10m_30m")
    call = client.only_call(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
    assert call.options["columns"] == duel_db.PUBLIC_LEADERBOARD_COLUMNS


def test_fetch_public_leaderboard_rejects_nonsense_paging():
    """값을 조용히 보정하지 않습니다 — 2페이지를 눌렀는데 1페이지가 나오면 안 됩니다(§0-1)."""
    client = FakeClient()
    for kwargs in ({"limit": 0}, {"limit": -5}, {"limit": 1.5}, {"offset": -1},
                   {"offset": "두번째"}):
        with pytest.raises(DuelDbError):
            duel_db.fetch_public_leaderboard(
                client, window_type="M1", bracket_key="krw_10m_30m", **kwargs)


def test_fetch_public_leaderboard_empty_page_is_not_an_error():
    client = FakeClient(responses={(duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): []})
    assert duel_db.fetch_public_leaderboard(
        client, window_type="M1", bracket_key="krw_10m_30m", offset=1500) == []


def test_fetch_public_holdings_filters_nickname_date_and_window():
    rows = [{"published_date": "2026-08-20", "window_type": "M1", "nickname": "닉",
             "ticker": "005930", "stock_name": "삼성전자", "quantity": 10.0,
             "buy_amount": 700000.0}]
    client = FakeClient(responses={(duel_db.PUBLIC_HOLDINGS_TABLE, "select"): rows})
    result = duel_db.fetch_public_holdings_for_nickname(
        client, "닉", published_date="2026-08-20", window_type="M1")
    assert result == rows

    call = client.only_call(duel_db.PUBLIC_HOLDINGS_TABLE, "select")
    assert call.filter_map == {"nickname": "닉", "published_date": "2026-08-20",
                               "window_type": "M1"}
    assert call.orders == [("ticker", False)]


def test_fetch_public_holdings_keeps_nulls_as_none():
    """
    동의하지 않은 항목은 발행 배치가 **null 로** 넣습니다(5-4-2). 조회 계층이 그것을 0 으로
    바꾸면 "0주 보유"와 "수량 비공개"가 같아집니다(§0-1). 그대로 통과시켜야 합니다.
    """
    client = FakeClient(responses={(duel_db.PUBLIC_HOLDINGS_TABLE, "select"): [
        {"published_date": "2026-08-20", "window_type": "M1", "nickname": "닉",
         "ticker": "005930", "stock_name": "삼성전자", "quantity": None, "buy_amount": None},
    ]})
    row = duel_db.fetch_public_holdings_for_nickname(client, "닉")[0]
    assert row["quantity"] is None and row["buy_amount"] is None


def test_public_reads_touch_only_the_two_publish_tables():
    """
    🔴 5-4-5 — 순위표 읽기 경로가 원본 표를 스치지 않는지. 세 함수를 실제로 불러 보고,
    **오간 질의의 표 이름**이 발행표 2개뿐인지 확인합니다.
    """
    client = FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): _board_rows(2),
        (duel_db.PUBLIC_HOLDINGS_TABLE, "select"): [],
    })
    duel_db.fetch_public_leaderboard_latest_date(client, window_type="M1",
                                                 bracket_key="krw_10m_30m")
    duel_db.fetch_public_leaderboard(client, window_type="M1", bracket_key="krw_10m_30m",
                                     published_date="2026-08-20")
    duel_db.fetch_public_holdings_for_nickname(client, "닉네임0",
                                               published_date="2026-08-20")
    tables = {call.table for call in client.calls}
    assert tables == {duel_db.PUBLIC_LEADERBOARD_TABLE, duel_db.PUBLIC_HOLDINGS_TABLE}
    assert {call.op for call in client.calls} == {"select"}, "읽기 경로는 select 뿐입니다"


# =============================================================================
# 2. 동의 화면 — 핵심 규칙 (5-2 · 5-8)
# =============================================================================
def _all_checked():
    return {flag: True for flag in duel_db.CONSENT_ITEM_FLAGS}


def test_consent_item_rows_match_the_db_layer_exactly():
    """
    화면에 보이는 항목과 실제로 저장되는 컬럼이 어긋나면, 사용자는 **자기가 동의하지 않은
    것에 동의한 셈**이 됩니다. 순서·키가 같은지 매번 확인합니다.
    """
    rows = consent_page.consent_item_rows()
    assert [flag for flag, _n, _s in rows] == list(duel_db.CONSENT_ITEM_FLAGS)
    assert len(rows) == 5


def test_consent_sentences_are_copied_from_the_work_order_verbatim():
    """
    🔴 5-2-1 의 다섯 문장과 5-2-4 의 독립 동의 문장은 **오너가 확정한 문안**입니다.
    작업지시서 원문에 그대로 들어 있는지 대조합니다(문구를 '다듬는' 순간 실패합니다).
    """
    for _flag, _name, sentence in consent_page.consent_item_rows():
        assert _squash(sentence) in WORK_ORDER_FLAT, f"작업지시서에 없는 문구: {sentence}"
    assert _squash(consent_page.CONSENT_REAL_PRINCIPAL_SENTENCE) in WORK_ORDER_FLAT

    holdings_sentence = consent_page.CONSENT_ITEM_SENTENCES["consent_holdings"][1]
    assert "개별 열람" in holdings_sentence, \
        "오너가 명시적으로 요구한 문구 요소('개별 열람')가 빠졌습니다(5-2-1)"


def test_five_items_are_all_or_nothing():
    """5-2-2 — 전부 아니면 전무. 하나라도 빠지면 최종 확인 payload 자체를 만들 수 없습니다."""
    assert consent_page.all_items_checked(_all_checked()) is True
    for flag in duel_db.CONSENT_ITEM_FLAGS:
        partial = dict(_all_checked(), **{flag: False})
        assert consent_page.all_items_checked(partial) is False
        assert consent_page.missing_item_labels(partial), "무엇이 빠졌는지 알려줘야 합니다"
        with pytest.raises(DuelRuleError):
            consent_page.final_confirm_payload(partial)


def test_item_payload_and_final_payload_are_separate_steps():
    """
    5-2-3 — 최종 확인은 **분리된 단계**입니다. 1층 저장 payload 에 `final_confirmed` 가
    섞여 있으면 "체크하자마자 발행 대상"이 되어 2층이 장식이 됩니다.
    """
    item_payload = consent_page.item_save_payload(_all_checked())
    assert set(item_payload) == set(duel_db.CONSENT_ITEM_FLAGS)
    assert "final_confirmed" not in item_payload

    final_payload = consent_page.final_confirm_payload(_all_checked())
    assert final_payload["final_confirmed"] is True
    assert all(final_payload[flag] is True for flag in duel_db.CONSENT_ITEM_FLAGS)


def test_real_principal_consent_is_never_bundled_with_the_five():
    """
    🔴 5-2-4 — 실제 자산 데이터 사용 동의는 위 5개와 **절대 같은 묶음이 아닙니다.**
    세 payload 중 어디에도 섞여 들어갈 수 없어야 합니다.
    """
    flag = duel_db.CONSENT_REAL_PRINCIPAL_FLAG
    assert flag not in consent_page.item_save_payload(_all_checked())
    assert flag not in consent_page.final_confirm_payload(_all_checked())

    only = consent_page.real_principal_payload(True)
    assert only == {flag: True}
    assert consent_page.real_principal_payload(False) == {flag: False}

    # 누가 나중에 5개 묶음에 끼워 넣으려 하면 즉시 실패합니다.
    with pytest.raises(DuelRuleError):
        consent_page._assert_no_real_principal({flag: True}, "테스트")


def test_payloads_actually_save_through_the_db_layer():
    """
    화면이 만든 payload 를 `duel_db.save_consent()` 가 그대로 받아들이는지(계약 확인).
    1층 저장에는 `final_confirmed` 가 없고, 2층 저장에서만 켜집니다.
    """
    client = FakeClient()
    duel_db.save_consent(client, "acc-1", **consent_page.item_save_payload(_all_checked()))
    first = client.calls_for(duel_db.CONSENT_TABLE, "upsert")[0]
    assert first.payload.get("final_confirmed") is None
    assert "final_confirmed_at" not in first.payload

    client2 = FakeClient()
    duel_db.save_consent(client2, "acc-1",
                         **consent_page.final_confirm_payload(_all_checked()))
    second = client2.calls_for(duel_db.CONSENT_TABLE, "upsert")[0]
    assert second.payload["final_confirmed"] is True
    assert second.payload.get("final_confirmed_at"), "최종확인 시각이 함께 저장돼야 합니다"


def test_revoke_needs_an_explicit_confirmation():
    """5-8 — 실수로 누르는 것을 막는 확인 단계. 체크 없이 누르면 진행하지 않습니다."""
    message = consent_page.revoke_guard(False)
    assert message and "체크" in message
    assert consent_page.revoke_guard(True) is None


def test_revoke_notice_states_both_consequences():
    """
    철회하면 ① 공개 기록이 **삭제**되고 ② 3개월간 재동의가 막힌다 — 둘 다 화면에 있어야
    합니다(5-8-1 · 5-8-2). 기간 숫자는 규칙 계층에서 만들어 씁니다(§0-3-10).
    """
    notice = consent_page.NOTICE_REVOKE
    assert "삭제" in notice
    assert f"{duel_rules.RECONSENT_BLOCK_MONTHS}개월" in notice
    # 즉시 사라지지 않는다는 사실도 숨기지 않습니다(§0-1).
    assert "하루" in consent_page.NOTICE_REVOKE_TIMING


def test_consent_state_distinguishes_four_situations():
    assert consent_page.consent_state(None)["state"] == "none"
    assert consent_page.consent_state({"consent_rank": True})["state"] == "in_progress"
    assert consent_page.consent_state(
        {"final_confirmed": True, "final_confirmed_at": "2026-08-20T10:00:00+09:00"}
    )["state"] == "confirmed"
    assert consent_page.consent_state(
        {"revoked_at": "2026-08-20T10:00:00+09:00"})["state"] == "revoked"

    state = consent_page.consent_state(
        {flag: True for flag in duel_db.CONSENT_ITEM_FLAGS})
    assert all(state["items"].values())
    assert state["real_principal"] is False


def test_reconsent_block_notice_tells_the_unblock_date():
    """
    5-8-2 — "지금은 안 됩니다"만 말하면 사용자는 며칠마다 다시 눌러 보게 됩니다. 언제
    풀리는지 날짜를 알려 줍니다. 판정은 `duel_rules.resolve_reconsent_block()` 이 합니다.
    """
    from datetime import datetime

    revoked = datetime(2026, 8, 1, 12, 0, tzinfo=duel_rules.KST)
    blocked_now = datetime(2026, 9, 1, 12, 0, tzinfo=duel_rules.KST)
    text = consent_page.reconsent_notice({"revoked_at": revoked.isoformat()}, blocked_now)
    assert text and "2026-11-01" in text

    free_now = datetime(2026, 11, 1, 12, 0, tzinfo=duel_rules.KST)
    assert consent_page.reconsent_notice({"revoked_at": revoked.isoformat()}, free_now) is None
    assert consent_page.reconsent_notice(None) is None


def test_responsibility_notice_appears_in_two_places():
    """
    5-2-5 — 책임 고지는 **개별 체크박스 영역과 최종 확인 영역, 최소 두 곳**에 나와야
    합니다. "한 곳에만 작게 적어두는 걸로는 부족합니다"(작업지시서 원문).
    """
    code = (REPO_ROOT / "web" / "pages" / "duel_consent_page.py").read_text(encoding="utf-8")
    assert code.count("warning_banner(NOTICE_RESPONSIBILITY)") >= 2
    assert "본인 책임" in consent_page.NOTICE_RESPONSIBILITY


def test_consent_page_never_issues_a_nickname_while_merely_rendering():
    """
    🔴 5-5 — 닉네임은 **동의를 저장한 뒤에만** 발급합니다. 화면을 그리는 함수(`_render_*`)
    안에서 `ensure_nickname()` 을 부르면, 구경만 하고 나간 사용자에게도 영구 닉네임이
    생깁니다(한 번 만들면 바꿀 수 없습니다 — 스키마 §9-6).
    """
    source = (REPO_ROOT / "web" / "pages" / "duel_consent_page.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_render"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                assert sub.func.id != "ensure_nickname", \
                    f"{node.name} 이 화면을 그리면서 닉네임을 발급합니다(5-5 위반)"
    # 저장 경로에는 있어야 합니다(있는지도 함께 고정 — 없으면 아무도 순위표에 못 실립니다).
    # 2026-08-20: `duel_nicknames` 가 (user_id, window_type) 키로 바뀌면서 인자도 함께 바뀌었습니다.
    assert 'ensure_nickname(client, account.get("user_id"), account.get("window_type"))' in source


# =============================================================================
# 3. 순위표 화면 — 고정 문구 · 표시 규칙 · 원본 표 격리 (5-3 · 5-7 · 5-4-5)
# =============================================================================
def test_fixed_notice_is_copied_from_the_work_order_verbatim():
    """
    🔴 5-3 — 최상단 고정 문구 두 문단. *"문구는 그대로 씁니다 — 요약·축약하지 마세요."*
    작업지시서 원문에 글자 그대로 들어 있는지 대조합니다.
    """
    assert len(board_page.FIXED_NOTICE_PARAGRAPHS) == 2
    for paragraph in board_page.FIXED_NOTICE_PARAGRAPHS:
        assert _squash(paragraph) in WORK_ORDER_FLAT, f"작업지시서와 다른 문구: {paragraph}"


def test_fixed_notice_is_rendered_before_the_login_gate():
    """
    "스크롤 없이 바로 보이는 위치(최상단)" — 로그인 폼이나 데이터보다 **먼저** 그려져야
    합니다. 소스에서 호출 순서를 확인합니다(위젯을 띄울 수 없는 환경이라 순서로 고정).
    """
    source = (REPO_ROOT / "web" / "pages"
              / "duel_leaderboard_page.py").read_text(encoding="utf-8")
    body = source[source.index("def duel_leaderboard_page("):]
    body = body[:body.index("\ndef _render_coming_soon")]
    assert body.index("_render_fixed_notice()") < body.index("render_auth()")
    assert body.index("_render_fixed_notice()") < body.index("_render_body(client)")


def test_leaderboard_page_never_touches_the_private_source_tables():
    """
    🔴 5-4-5 — *"duel_positions·holdings·profiles·duel_cash_ledger 를 순위표 코드 경로에서
    import 조차 하지 않게 하세요."* 코드에 등장하는 **이름과 문자열 리터럴** 양쪽을 봅니다
    (표 이름은 문자열로, 함수는 이름으로 숨어들 수 있으므로).
    """
    names = _code_names("duel_leaderboard_page.py")
    strings = " | ".join(_code_strings("duel_leaderboard_page.py"))

    for table in ("duel_positions", "duel_cash_ledger", "duel_daily_snapshots",
                  "duel_holding_snapshots", "duel_public_consent", "duel_nicknames",
                  "profiles", "holdings"):
        assert table not in strings, f"순위표 화면의 문자열에 {table} 가 있습니다"
    for function in ("fetch_my_positions", "fetch_my_cash_ledger", "fetch_my_snapshots",
                     "fetch_my_accounts", "fetch_my_consent", "fetch_my_nickname",
                     "fetch_holdings", "ensure_nickname", "save_consent", "revoke_consent",
                     "opt_in", "create_service_client"):
        assert function not in names, f"순위표 화면이 {function}() 를 부릅니다"


def test_leaderboard_page_does_not_recompute_ranks():
    """
    §0-3-2 / 5-7 — 순위는 배치가 계산해 저장한 `rank` 를 **읽기만** 합니다. 화면에서
    정렬·순위 계산을 다시 하면 방문자 수만큼 전체 스캔이 돕니다.
    """
    names = _code_names("duel_leaderboard_page.py")
    for forbidden in ("rank_participants", "compute_twr", "sort", "sorted"):
        assert forbidden not in names, f"순위표 화면이 {forbidden} 로 계산을 다시 합니다"


def test_bracket_and_window_options_come_from_the_rules_layer():
    """8구간 + 구간 미적용 = 9개. 라벨은 `duel_rules.bracket_label()` 만 씁니다(§0-3-10)."""
    brackets = board_page.bracket_options()
    assert list(brackets) == list(duel_rules.BRACKET_KEYS)
    assert len(brackets) == len(duel_rules.BRACKET_TIERS) + 1
    assert brackets[duel_rules.BRACKET_NONE_KEY] == duel_rules.BRACKET_NONE_LABEL
    assert list(board_page.window_options()) == list(duel_rules.ACCOUNT_WINDOW_TYPES)


def test_unpublished_values_are_shown_as_private_not_zero():
    """
    🔴 §0-1 — "수익률 0%"와 "수익률 비공개"는 다른 말입니다. null 은 반드시 '비공개'.
    """
    assert board_page.twr_display(None) == board_page.NOT_PUBLISHED_TEXT
    shown = board_page.twr_display(0)
    assert shown != board_page.NOT_PUBLISHED_TEXT and isinstance(shown, str)

    cells = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": None, "buy_amount": None})
    assert cells[1] == board_page.NOT_PUBLISHED_TEXT
    assert cells[2] == board_page.NOT_PUBLISHED_TEXT

    priced = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 10, "buy_amount": 700000})
    assert priced[1] != board_page.NOT_PUBLISHED_TEXT
    assert priced[2] != board_page.NOT_PUBLISHED_TEXT


def test_holdings_table_escapes_stock_names():
    """🔐 §0-3-9 — 배치가 넣은 값이라도 화면에 나가는 값은 예외 없이 이스케이프합니다."""
    html = board_page.holdings_table([
        {"ticker": "999999", "stock_name": "<img src=x onerror=alert(1)>",
         "quantity": 1, "buy_amount": 1000},
    ])
    assert "<img src=x onerror=" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert board_page.holdings_table([]) is None


def test_pagination_bounds_respect_the_500_caps():
    """5-7 — 상위 500 / 하위 500, 한 페이지 30개. 501번째를 읽어 오는 경로가 없어야 합니다."""
    page_size = duel_rules.LEADERBOARD_PAGE_SIZE
    cap = duel_rules.LEADERBOARD_TOP_COUNT
    assert duel_rules.leaderboard_page_bounds(0) == (0, page_size)

    total = 0
    for index in range(duel_rules.leaderboard_page_count(cap)):
        offset, limit = duel_rules.leaderboard_page_bounds(index, section_cap=cap)
        assert offset + limit <= cap
        total += limit
    assert total == cap, "구간을 전부 훑으면 정확히 상한만큼이어야 합니다"

    beyond = duel_rules.leaderboard_page_bounds(
        duel_rules.leaderboard_page_count(cap), section_cap=cap)
    assert beyond[1] == 0, "상한을 넘은 페이지는 질의를 보내지 않습니다(limit 0)"

    assert board_page.section_cap(board_page.SECTION_TOP) == duel_rules.LEADERBOARD_TOP_COUNT
    assert board_page.section_cap(board_page.SECTION_BOTTOM) == duel_rules.LEADERBOARD_BOTTOM_COUNT
    with pytest.raises(DuelRuleError):
        board_page.section_cap("middle")


def test_screens_do_not_hardcode_the_numbers_that_live_in_the_rules_layer():
    """
    §0-3-10 — 화면 파일에 규칙 계층의 숫자(500 · 30 · 3개월 · 12개월 …)를 다시 적지
    않았는지. 숫자 **리터럴**만 봅니다(설명 문장에 "500명"이라고 쓰는 것은 문제가 아니라
    필요한 안내입니다 — 그 값도 상수에서 만들어 넣고 있습니다).
    """
    forbidden = {3, 12, 30, 500, 1000, 800000, 10000000}
    for name in ("duel_leaderboard_page.py", "duel_consent_page.py"):
        leaked = forbidden & _code_numbers(name)
        assert not leaked, f"{name} 에 규칙 계층의 숫자가 그대로 적혀 있습니다: {sorted(leaked)}"


# =============================================================================
# 4. 3단계 공개 게이트 (§0-3-6 · 7-1)
# =============================================================================
def _menu_with(**env):
    """환경변수를 바꿔 `web/layout.py` 를 다시 읽고, 그때의 메뉴 경로 목록을 돌려줍니다."""
    import web.layout as layout_module

    saved = {key: os.environ.get(key) for key in env}
    os.environ.update({key: value for key, value in env.items()})
    try:
        reloaded = importlib.reload(layout_module)
        return [path for path, _label, _admin_only in reloaded._MENU]
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(layout_module)


def test_public_screens_are_hidden_by_default():
    """§0-3-6 기본 숨김 — 아무 플래그도 없으면 메뉴에 2갈래 항목이 **아예 없습니다**."""
    import web.layout as layout_module

    layout_module = importlib.reload(layout_module)
    assert layout_module.DUEL_CONSENT_ENABLED is False
    assert layout_module.DUEL_LEADERBOARD_ENABLED is False
    assert layout_module.DUEL_CONSENT_MENU_ADMIN_ONLY is True
    assert layout_module.DUEL_LEADERBOARD_MENU_ADMIN_ONLY is True
    assert not [p for p in (item[0] for item in layout_module._MENU)
                if p.startswith("/duel/")]


def test_public_screens_require_branch_one_to_be_enabled():
    """
    🔴 2갈래는 1갈래 없이는 존재할 수 없습니다. `DUEL_ENABLED` 가 꺼진 채로 공개 플래그만
    켜도 메뉴에 아무것도 생기지 않아야 합니다(계좌가 없으면 공개할 성적도 없습니다).
    """
    paths = _menu_with(DUEL_CONSENT_ENABLED="true", DUEL_LEADERBOARD_ENABLED="true")
    assert not [p for p in paths if p.startswith("/duel")]


def test_public_screens_appear_one_at_a_time():
    """동의 화면과 순위표 화면은 **따로** 열 수 있어야 합니다(7-3 의 단계적 공개 순서)."""
    only_consent = _menu_with(DUEL_ENABLED="true", DUEL_CONSENT_ENABLED="true")
    assert "/duel" in only_consent and "/duel/consent" in only_consent
    assert "/duel/leaderboard" not in only_consent

    both = _menu_with(DUEL_ENABLED="true", DUEL_CONSENT_ENABLED="true",
                      DUEL_LEADERBOARD_ENABLED="true")
    assert {"/duel", "/duel/consent", "/duel/leaderboard"} <= set(both)


@pytest.mark.parametrize("module_name,flag_names", [
    ("duel_consent_page.py", ("DUEL_ENABLED", "DUEL_CONSENT_ENABLED",
                              "DUEL_CONSENT_MENU_ADMIN_ONLY")),
    ("duel_leaderboard_page.py", ("DUEL_ENABLED", "DUEL_LEADERBOARD_ENABLED",
                                  "DUEL_LEADERBOARD_MENU_ADMIN_ONLY")),
])
def test_each_public_screen_checks_its_own_flags_and_login(module_name, flag_names):
    """
    메뉴에서 감추는 것만으로는 부족합니다 — 주소를 아는 사람은 그냥 들어옵니다. 화면도
    같은 값을 직접 보고, 로그인 게이트를 `duel_page.py` 와 같은 순서로 통과해야 합니다.
    """
    names = _code_names(module_name)
    for flag in flag_names:
        assert flag in names, f"{module_name} 이 {flag} 를 보지 않습니다"
    assert "is_admin" in names, "관리자 전용 단계를 화면에서도 확인해야 합니다"
    for gate in ("supabase_status", "has_supabase_session", "render_auth",
                 "get_client", "current_user", "user_id_of", "logout"):
        assert gate in names, f"{module_name} 에 로그인 게이트({gate})가 없습니다"


def test_public_screens_do_not_keep_user_state_in_module_globals():
    """
    §0-3-8 — 모듈 최상위에는 상수만 있어야 합니다. 사용자·클라이언트·상태를 연상시키는
    이름의 전역이 새로 생기면 여기서 잡힙니다(`tests/test_web_session_isolation.py` [1-a]
    와 같은 규율의 가벼운 사본 — 저쪽은 web/ 전체를, 여기는 이번에 만든 두 파일을 봅니다).
    """
    suspicious = re.compile(r"^(client|user|session|token|state|view|cache|_[a-z]+_cache)",
                            re.IGNORECASE)
    for name in ("duel_consent_page.py", "duel_leaderboard_page.py"):
        tree = ast.parse((REPO_ROOT / "web" / "pages" / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assert not suspicious.match(target.id), \
                        f"{name} 의 전역 `{target.id}` 가 사용자 상태처럼 보입니다(§0-3-8)"


# =============================================================================
# 5. 발행 배치 실행 스크립트 · 워크플로우 (C 파트)
# =============================================================================
def test_publish_runner_delegates_and_never_decides():
    """
    루트 실행 스크립트는 **I/O 와 환경**만 다룹니다. 판단(누가 발행 대상인지 등)이 여기로
    새어 들어오면 `tests/test_duel_publish.py` 가 검증하지 못하는 로직이 생깁니다
    (`run_duel_daily_batch.py` 와 같은 분업).
    """
    source = (REPO_ROOT / "run_duel_publish_batch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "run_publish_batch" in called
    assert "create_service_client" in called
    # 발행표를 직접 만지거나 규칙을 다시 계산하지 않습니다.
    for forbidden in ("write_public_leaderboard", "write_public_holdings",
                      "rank_participants", "assign_bracket", "compute_twr"):
        assert forbidden not in source, f"실행 스크립트가 {forbidden} 를 직접 부릅니다"


def test_publish_workflow_runs_after_the_fill_batch():
    """
    🔴 순서 — 발행 배치는 그날 스냅샷(→ TWR)을 읽으므로 **체결 배치보다 뒤**여야 합니다.
    두 워크플로우의 cron 을 실제로 파싱해 비교합니다(주석이 아니라 값으로 고정).
    """
    yaml = pytest.importorskip("yaml", reason="pyyaml 이 없으면 이 검사만 건너뜁니다")
    workflows = REPO_ROOT / ".github" / "workflows"
    fill = yaml.safe_load((workflows / "duel_daily.yml").read_text(encoding="utf-8"))
    publish = yaml.safe_load((workflows / "duel_publish_daily.yml").read_text(encoding="utf-8"))

    def _cron_minutes(document):
        # YAML 1.1 에서 `on:` 은 불리언 True 로 파싱됩니다(GitHub 은 정상 처리).
        schedule = (document.get("on") or document.get(True))["schedule"]
        minute, hour = schedule[0]["cron"].split()[:2]
        return int(hour) * 60 + int(minute)

    fill_at = _cron_minutes(fill)
    publish_at = _cron_minutes(publish)
    fill_timeout = fill["jobs"]["duel-batch"]["timeout-minutes"]
    assert publish_at >= fill_at + fill_timeout, (
        "발행 배치가 체결 배치의 타임아웃 상한보다 먼저 시작합니다"
        f" (체결 {fill_at}분 + 타임아웃 {fill_timeout}분 vs 발행 {publish_at}분)"
    )

    job = publish["jobs"]["duel-publish"]
    assert publish["permissions"] == {"contents": "read"}, \
        "발행 배치는 저장소에 커밋하지 않으므로 쓰기 권한이 필요 없습니다(최소 권한)"
    assert publish["concurrency"]["group"], "겹쳐 도는 실행을 막아야 합니다"
    step_env = [step.get("env", {}) for step in job["steps"]]
    assert any("SUPABASE_SERVICE_ROLE_KEY" in env for env in step_env), \
        "배치 키를 실행 단계에만 넘겨야 합니다"
    assert any(step.get("if") == "failure()" for step in job["steps"]), \
        "실패했을 때 무엇을 확인해야 하는지 남겨야 합니다"


# =============================================================================
# 6. 렌더 스모크 — 화면 함수를 **실제로 실행**해 봅니다
# =============================================================================
#  위젯은 스텁이라 화면이 그려지지는 않지만, 분기·문구 조립·이스케이프·질의 횟수는 전부
#  진짜로 돕니다(`tests/test_web_session_isolation.py` [9-b] 와 같은 방식). 계좌·동의·순위는
#  **합성 데이터**이고 DB 호출은 전부 대체합니다 — 실제 Supabase 에 접속하지 않습니다(§0-1).
# =============================================================================
SYNTHETIC_ACCOUNTS = [
    {"id": f"acc-{window}", "user_id": "uid-1", "window_type": window, "status": "active"}
    for window in ("M1", "M3", "M6")
]

SYNTHETIC_CONSENTS = {
    "acc-M1": None,                                        # 아직 아무것도 안 한 계좌
    "acc-M3": dict({flag: True for flag in duel_db.CONSENT_ITEM_FLAGS},
                   account_id="acc-M3", final_confirmed=True,
                   final_confirmed_at="2026-08-19T20:00:00+09:00",
                   consent_real_principal_bracket=True),   # 최종 확인까지 끝난 계좌
    "acc-M6": {"account_id": "acc-M6",
               "revoked_at": "2026-08-15T20:00:00+09:00"},  # 철회 후 3개월 차단 중
}


def _patch(module, **replacements):
    """모듈 속성을 잠시 바꿨다가 되돌리는 아주 작은 도우미(원상복구를 잊지 않기 위해)."""
    saved = {name: getattr(module, name) for name in replacements}
    for name, value in replacements.items():
        setattr(module, name, value)
    return saved


def _restore(module, saved):
    for name, value in saved.items():
        setattr(module, name, value)


def test_consent_body_renders_all_three_account_states():
    """
    동의 화면 본문이 **끝까지** 실행되는지 — 기록 없음 / 최종확인 완료 / 철회(차단 중)
    세 상태를 한 번에 그립니다.
    """
    saved = _patch(
        consent_page,
        fetch_my_accounts=lambda client, user_id: [dict(a) for a in SYNTHETIC_ACCOUNTS],
        fetch_my_consent=lambda client, account_id: SYNTHETIC_CONSENTS[account_id],
        fetch_my_nickname=lambda client, user_id, window_type: {"nickname": "굳센날쌘범"},
    )
    try:
        consent_page._render_body(object(), "uid-1")
    finally:
        _restore(consent_page, saved)


def test_consent_body_refuses_to_draw_someone_elses_account():
    """🔒 §0-3-8 — 남의 `user_id` 가 섞여 오면 **아무것도 그리지 않고** 오류로 알립니다."""
    drawn = []
    saved = _patch(
        consent_page,
        fetch_my_accounts=lambda client, user_id: [
            dict(SYNTHETIC_ACCOUNTS[0], user_id="uid-somebody-else")],
        error_banner=lambda text: drawn.append(text),
    )
    try:
        consent_page._render_body(object(), "uid-1")
    finally:
        _restore(consent_page, saved)
    assert drawn and "본인 것이 아닌" in drawn[0]


def _leaderboard_client():
    """발행일 조회(`limit(1)`)와 순위 페이지 조회에 서로 다른 응답을 주는 가짜 클라이언트."""
    rows = [{"published_date": "2026-08-20", "window_type": "M1",
             "bracket_key": duel_rules.BRACKET_KEYS[0], "rank": rank,
             "nickname": f"닉네임{rank}",
             "twr_pct": None if rank == 2 else 5.5 - rank}      # 2위는 수익률 비공개
            for rank in (1, 2, 3)]
    holdings = [{"published_date": "2026-08-20", "window_type": "M1", "nickname": "닉네임1",
                 "ticker": "005930", "stock_name": "<img src=x onerror=alert(1)>",
                 "quantity": None, "buy_amount": 700000.0}]
    return FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"):
            lambda query: ([{"published_date": "2026-08-20"}]
                           if query.options.get("limit") == 1 else rows),
        (duel_db.PUBLIC_HOLDINGS_TABLE, "select"): holdings,
    })


def test_leaderboard_body_renders_and_does_not_preload_holdings():
    """
    §0-3-2 — 화면을 여는 것만으로 참가자 상세를 미리 읽지 않습니다(펼칠 때 처음 읽습니다).
    질의는 발행일 1 + 위쪽 1 + 아래쪽 1 = 3개뿐이어야 합니다.
    """
    client = _leaderboard_client()
    board_page._render_body(client)

    assert {call.table for call in client.calls} == {duel_db.PUBLIC_LEADERBOARD_TABLE}, \
        "보유종목은 펼치기 전에는 읽지 않습니다"
    assert len(client.calls) == 3, [(c.table, c.options) for c in client.calls]


def test_leaderboard_body_handles_an_unpublished_group_as_a_normal_state():
    """
    참가자가 없거나 최소 인원 미달이면 **오류가 아니라 안내**입니다(5-6). 질의도 1개만
    나갑니다(발행일이 없으면 순위를 읽으러 가지 않습니다).
    """
    notices = []
    client = FakeClient()                                    # 모든 select 가 빈 목록
    saved = _patch(board_page, info_banner=lambda text: notices.append(text))
    try:
        board_page._render_body(client)
    finally:
        _restore(board_page, saved)

    assert len(client.calls) == 1
    assert any("아직 공개할 만큼" in text for text in notices), notices


def test_leaderboard_holdings_panel_renders_escaped_and_marks_private_fields():
    """펼쳤을 때의 경로 — XSS 이스케이프(§0-3-9)와 '비공개' 표기(§0-1)를 함께 확인합니다."""
    captured = []
    client = _leaderboard_client()
    real_table = board_page.holdings_table

    def _spy(rows):
        result = real_table(rows)
        captured.append(result)
        return result

    saved = _patch(board_page, holdings_table=_spy)
    try:
        board_page._render_holdings(client, "2026-08-20", "M1", "닉네임1")
    finally:
        _restore(board_page, saved)

    blob = "\n".join(str(item) for item in captured)
    assert "<img src=x onerror=" not in blob
    assert "&lt;img src=x onerror=alert(1)&gt;" in blob
    assert board_page.NOT_PUBLISHED_TEXT in blob, "수량 비공개가 '비공개'로 그려져야 합니다"
    # 닉네임·날짜·창유형으로 정확히 걸러 읽었는지(다른 날짜·다른 사람의 행이 섞이지 않게).
    call = client.only_call(duel_db.PUBLIC_HOLDINGS_TABLE, "select")
    assert call.filter_map == {"nickname": "닉네임1", "published_date": "2026-08-20",
                               "window_type": "M1"}
