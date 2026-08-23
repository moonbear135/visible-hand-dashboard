# tests/test_scorecard_public_ui.py
"""
💼 "내 성적표" 공개 계층 **화면 2종** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요 · nicegui 설치 여부와 무관)

2026-08-23 전환으로 새로 만든 두 화면
    web/pages/scorecard_consent_page.py      → `/scorecard/consent`
    web/pages/scorecard_leaderboard_page.py  → `/scorecard/leaderboard`
을 회귀로 고정합니다. 은퇴한 `tests/test_duel_public_ui.py` 의 화면 검증 부분을 옮겨 오되,
**구조가 실제로 달라진 세 가지**를 검사 자체로 못 박습니다.

가짜 Supabase 클라이언트는 **새로 만들지 않고** `tests/test_duel_db.py` 의 `FakeClient` 를
그대로 가져다 씁니다(§0-3-10 — 같은 흉내를 두 벌 만들지 않습니다).

검증 대상
    [1] 동의 화면의 **핵심 규칙**(위젯 없이 순수 함수로 확인)
        — 5개 전부 아니면 전무 / 최종 확인 분리 / 철회 확인 단계 / 재동의 차단 안내
        — 🔴 **여섯 번째 동의(`consent_real_principal_bracket`)가 어디에도 없는가**
        — 🔴 화면 문구가 "가상계좌·결투"가 아니라 **실제 보유 자산**을 말하는가
    [2] 순위표 화면 — 고정 문구 2문단(오너 확정, 글자 그대로) · 원본 표 격리 ·
        순위 재계산 금지 · **창유형(window_type) 축이 완전히 사라졌는가**
    [3] 🔐 **XSS (§0-3-9 — 이 파일에서 가장 중요한 검사)**
        `stock_name` 은 사용자가 자유 입력한 값입니다(스키마 §2-4 컬럼 주석 ·
        `scorecard_publish.holdings_payload()` 독스트링이 `<img onerror=...>` 를 명시적으로
        경고). 종목명·종목코드·닉네임이 화면으로 나가는 **모든 경로**가 `esc()` 를 거치는지
        ① 값으로(악성 문자열을 실제로 흘려보고) ② 구조로(AST 로 raw HTML 조립 자리를 훑어)
        두 방향에서 확인합니다.
    [4] 2단계 공개 게이트 배선 — 기본값(스위치 꺼짐 + 관리자 전용)에서 메뉴에 항목이 없고,
        화면도 같은 값을 직접 보는가(§0-3-6).
    [5] 렌더 스모크 — 두 화면의 본문 함수를 **실제로 실행**해 봅니다.

⚠️ 여기서 **검증하지 못하는 것**(§0-1 — 할 수 있는 것만 했다고 말합니다):
    · 실제 NiceGUI 위젯이 브라우저에 어떻게 그려지는지.
    · 실제 Supabase RLS 가 비로그인 접속을 막는지(그건 `sql/scorecard_public_schema.sql`
      §3 의 몫).

실행: pytest tests/test_scorecard_public_ui.py -v
"""

import ast
import asyncio
import importlib
import io
import os
import re
import sys
import tokenize
import types
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))          # from test_duel_db import FakeClient

from test_duel_db import FakeClient                                      # noqa: E402
from utils import duel_rules, scorecard_db, scorecard_publish_db         # noqa: E402
from utils.duel_rules import DuelRuleError                               # noqa: E402

CONSENT_PAGE_NAME = "scorecard_consent_page.py"
BOARD_PAGE_NAME = "scorecard_leaderboard_page.py"

#: 결투 순위표에 붙어 있던 **오너 확정 고정 문구**의 출처. 이번 전환에서 한 글자도 바꾸지
#: 않고 옮겼으므로, 원문(작업지시서 5-3)과 계속 대조할 수 있습니다.
WORK_ORDER = (REPO_ROOT / "DUEL_MODULE_WORK_ORDER.md").read_text(encoding="utf-8")


def _squash(text):
    """공백 차이를 무시하고 문장을 대조하기 위한 정규화(줄바꿈으로 접힌 문구 비교용)."""
    return re.sub(r"\s+", " ", str(text)).strip()


WORK_ORDER_FLAT = _squash(WORK_ORDER)


# =============================================================================
# 0. 스텁 — nicegui 와 web/* (있으면 진짜를 씁니다)
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

        class _Run(types.ModuleType):
            """`nicegui.run` 흉내 — `await run.io_bound(fn, *a, **kw)` 를 그냥 동기 호출로
            대체합니다(`web/blocking.run_blocking()` 이 이걸 씁니다). 스레드 분리 자체는
            `tests/test_event_loop_blocking.py` 가 따로 못 박습니다."""

            @staticmethod
            async def io_bound(fn, *args, **kwargs):
                return fn(*args, **kwargs)

        nicegui = types.ModuleType("nicegui")
        nicegui.ui = _UI("nicegui.ui")
        nicegui.app = element
        nicegui.run = _Run("nicegui.run")
        sys.modules["nicegui"] = nicegui
        sys.modules["nicegui.ui"] = nicegui.ui
        sys.modules["nicegui.run"] = nicegui.run

    if "web.auth" not in sys.modules:
        try:
            import web.auth                                               # noqa: F401
        except ImportError:
            async def _no_client():
                return None

            async def _noop_logout():
                return None

            async def _no_user(_client):
                return None

            auth = types.ModuleType("web.auth")
            auth.get_client = lambda: None
            auth.get_client_async = _no_client
            auth.current_user_async = _no_user
            auth.has_supabase_session = lambda: False
            auth.is_admin = lambda: False
            auth.logout = lambda: None
            auth.logout_async = _noop_logout
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
            components.__path__ = []
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
#  검사가 실패**합니다. 그건 검사가 잘못된 것이지 코드가 잘못된 게 아닙니다.
def _page_source(name):
    return (REPO_ROOT / "web" / "pages" / name).read_text(encoding="utf-8")


def _code_names(name):
    """그 파일에서 **코드로 등장하는 이름**(식별자·속성) 집합."""
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


def _executable_source(name):
    """주석과 docstring 을 걷어낸 '실행되는 코드'만. (설명에 적힌 단어를 코드로 오인하지 않게.)"""
    source = _page_source(name)
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    pieces = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING:
            try:
                value = ast.literal_eval(token.string)
            except (ValueError, SyntaxError):        # f-string 등은 그대로 남깁니다
                pieces.append(token.string)
                continue
            if isinstance(value, str) and value in docstrings:
                continue
        pieces.append(token.string)
    return "\n".join(pieces)


def _function_nodes(name):
    """`{함수이름: AST 노드}` — 동기·비동기 함수를 함께 봅니다."""
    tree = ast.parse(_page_source(name))
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


# =============================================================================
# 0-c. 비동기 화면 함수를 테스트에서 돌리는 방법
# =============================================================================
#  NiceGUI 는 "위젯이 그려질 자리(슬롯)"를 **asyncio 태스크별로** 들고 있습니다
#  (`nicegui.slot.Slot.stacks` — 키가 `id(current_task())`). `asyncio.run()` 은 새 태스크를
#  만드니 그 안에서는 슬롯 스택이 비어 있고, `ui.markdown(...)` 한 줄에서 바로 터집니다.
#  그래서 바깥 컨텍스트의 슬롯 스택을 새 태스크에 복사해 준 뒤 코루틴을 돌립니다.
def _run(coro):
    """비동기 화면 함수를 끝까지 실행합니다 (NiceGUI 슬롯 컨텍스트를 함께 넘겨서)."""
    try:
        from nicegui import context as nicegui_context
        from nicegui.slot import Slot, get_task_id
    except ImportError:                            # 스텁 환경(nicegui 미설치)
        return asyncio.run(coro)

    outer = list(nicegui_context.slot_stack)

    async def _main():
        Slot.stacks[get_task_id()] = list(outer)
        try:
            return await coro
        finally:
            Slot.stacks.pop(get_task_id(), None)

    return asyncio.run(_main())


_install_stubs()

from web.pages import scorecard_consent_page as consent_page             # noqa: E402
from web.pages import scorecard_leaderboard_page as board_page           # noqa: E402

KRW = scorecard_db.CURRENCY_KRW
USD = scorecard_db.CURRENCY_USD

#: 🔐 §0-3-9 검사에 쓰는 악성 종목명. `holdings.stock_name` 은 사용자가 자유 입력하는
#:    값이므로 이런 문자열이 실제로 발행표에 저장될 수 있습니다(스키마 §2-4 컬럼 주석).
XSS_STOCK_NAME = '<img src=x onerror=alert(1)>'
XSS_TICKER = '"><script>alert(2)</script>'


# =============================================================================
# 1. 동의 화면 — 핵심 규칙
# =============================================================================
def _all_checked():
    return {flag: True for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS}


def test_consent_item_rows_match_the_db_layer_exactly():
    """
    화면에 보이는 항목과 실제로 저장되는 컬럼이 어긋나면, 사용자는 **자기가 동의하지 않은
    것에 동의한 셈**이 됩니다. 순서·키가 같은지 매번 확인합니다.
    """
    rows = consent_page.consent_item_rows()
    assert [flag for flag, _n, _s in rows] == list(scorecard_publish_db.CONSENT_ITEM_FLAGS)
    assert len(rows) == 5, "항목별 동의는 정확히 5개입니다(여섯 번째를 만들지 마세요)"


def test_consent_sentences_describe_real_holdings_not_the_duel_accounts():
    """
    🔴 이 전환의 핵심 — 공개되는 것이 **가상계좌 성적이 아니라 실제 보유 자산**입니다.
    옛 문구를 그대로 복사해 왔다면 여기서 잡힙니다(§0-1 — 사실과 다른 안내 금지).
    """
    sentences = [sentence for _f, _n, sentence in consent_page.consent_item_rows()]
    blob = " ".join(sentences)
    for stale in ("가상계좌", "가상 계좌", "결투", "계좌의 수익률"):
        assert stale not in blob, f"동의 문구에 은퇴한 결투 표현이 남아 있습니다: {stale}"
    assert "실제" in blob, "무엇이 실제 데이터인지 한 번은 말해야 합니다"

    holdings_sentence = consent_page.CONSENT_ITEM_SENTENCES["consent_holdings"][1]
    assert "개별 열람" in holdings_sentence, \
        "오너가 명시적으로 요구한 문구 요소('개별 열람')가 빠졌습니다"
    assert "공개됩니다" in holdings_sentence


def test_no_sixth_consent_item_anywhere_in_the_new_screens():
    """
    🔴 결투에 있던 여섯 번째 독립 동의(`consent_real_principal_bracket`)에 해당하는 것이
    **이 계층에는 존재하지 않습니다.** 공개되는 데이터 자체가 이미 실제 자산이라, 체급
    산정을 위한 두 번째 동의 게이트를 세울 대상이 남아 있지 않기 때문입니다
    (`utils/scorecard_publish_db.CONSENT_ITEM_FLAGS` 주석 · 스키마 §2-2).

    누가 "결투에는 있었으니까"라며 되살리면 DB CHECK 와 화면 판정이 갈라집니다. 화면 코드
    (주석·docstring 제외)에 그 흔적이 하나도 없어야 합니다.
    """
    assert "consent_real_principal_bracket" not in scorecard_publish_db.CONSENT_ITEM_FLAGS
    for name in (CONSENT_PAGE_NAME, BOARD_PAGE_NAME):
        code = _executable_source(name)
        assert "real_principal" not in code, \
            f"{name} 에 여섯 번째 동의의 흔적이 있습니다"
        assert "REAL_PRINCIPAL" not in code, \
            f"{name} 에 여섯 번째 동의의 흔적이 있습니다"
    # 상태 요약에도 그 키가 없어야 합니다(항상 False 인 줄이 화면에 남지 않게 — §0-1).
    assert "real_principal" not in consent_page.consent_state(None)


def test_five_items_are_all_or_nothing():
    """전부 아니면 전무. 하나라도 빠지면 최종 확인 payload 자체를 만들 수 없습니다."""
    assert consent_page.all_items_checked(_all_checked()) is True
    for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS:
        partial = dict(_all_checked(), **{flag: False})
        assert consent_page.all_items_checked(partial) is False
        assert consent_page.missing_item_labels(partial), "무엇이 빠졌는지 알려줘야 합니다"
        with pytest.raises(DuelRuleError):
            consent_page.final_confirm_payload(partial)


def test_item_payload_and_final_payload_are_separate_steps():
    """
    최종 확인은 **분리된 단계**입니다. 1층 저장 payload 에 `final_confirmed` 가 섞여 있으면
    "체크하자마자 발행 대상"이 되어 2층이 장식이 됩니다.
    """
    item_payload = consent_page.item_save_payload(_all_checked())
    assert set(item_payload) == set(scorecard_publish_db.CONSENT_ITEM_FLAGS)
    assert "final_confirmed" not in item_payload

    final_payload = consent_page.final_confirm_payload(_all_checked())
    assert final_payload["final_confirmed"] is True
    assert all(final_payload[flag] is True
               for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS)


def test_payloads_actually_save_through_the_db_layer():
    """
    화면이 만든 payload 를 `scorecard_publish_db.save_consent()` 가 그대로 받아들이는지
    (계약 확인). 1층 저장에는 `final_confirmed` 가 없고, 2층 저장에서만 켜집니다.
    """
    client = FakeClient()
    scorecard_publish_db.save_consent(
        client, "uid-1", **consent_page.item_save_payload(_all_checked()))
    first = client.calls_for(scorecard_publish_db.CONSENT_TABLE, "upsert")[0]
    assert first.payload.get("final_confirmed") is None
    assert "final_confirmed_at" not in first.payload
    assert first.payload["user_id"] == "uid-1"

    client2 = FakeClient()
    scorecard_publish_db.save_consent(
        client2, "uid-1", **consent_page.final_confirm_payload(_all_checked()))
    second = client2.calls_for(scorecard_publish_db.CONSENT_TABLE, "upsert")[0]
    assert second.payload["final_confirmed"] is True
    assert second.payload.get("final_confirmed_at"), "최종확인 시각이 함께 저장돼야 합니다"


def test_revoke_needs_an_explicit_confirmation():
    """실수로 누르는 것을 막는 확인 단계. 체크 없이 누르면 진행하지 않습니다."""
    message = consent_page.revoke_guard(False)
    assert message and "체크" in message
    assert consent_page.revoke_guard(True) is None


def test_revoke_notice_states_every_consequence():
    """
    철회하면 ① 공개 기록이 **삭제**되고 ② 3개월간 재동의가 막히고 ③ 원화·달러가 **함께**
    지워진다 — 셋 다 화면에 있어야 합니다. 특히 ③ 은 이 계층에서 새로 생긴 사실입니다
    (결투는 트랙마다 동의가 따로였습니다). 기간 숫자는 규칙 계층에서 만들어 씁니다.
    """
    notice = consent_page.NOTICE_REVOKE
    assert "삭제" in notice
    assert f"{duel_rules.RECONSENT_BLOCK_MONTHS}개월" in notice
    assert "원화" in notice and "달러" in notice, \
        "한쪽만 철회할 수 없다는 사실을 밝혀야 합니다(§0-1)"
    # 즉시 사라지지 않는다는 사실도 숨기지 않습니다(§0-1).
    assert "하루" in consent_page.NOTICE_REVOKE_TIMING


def test_consent_state_distinguishes_four_situations():
    assert consent_page.consent_state(None)["state"] == "none"
    assert consent_page.consent_state({"consent_rank": True})["state"] == "in_progress"
    assert consent_page.consent_state(
        {"final_confirmed": True, "final_confirmed_at": "2026-08-22T10:00:00+09:00"}
    )["state"] == "confirmed"
    assert consent_page.consent_state(
        {"revoked_at": "2026-08-22T10:00:00+09:00"})["state"] == "revoked"

    state = consent_page.consent_state(
        {flag: True for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS})
    assert all(state["items"].values())


def test_reconsent_block_notice_tells_the_unblock_date():
    """
    "지금은 안 됩니다"만 말하면 사용자는 며칠마다 다시 눌러 보게 됩니다. 언제 풀리는지
    날짜를 알려 줍니다. 판정은 `duel_rules.resolve_reconsent_block()` 이 합니다(§0-3-10).
    """
    revoked = datetime(2026, 8, 1, 12, 0, tzinfo=duel_rules.KST)
    blocked_now = datetime(2026, 9, 1, 12, 0, tzinfo=duel_rules.KST)
    text = consent_page.reconsent_notice({"revoked_at": revoked.isoformat()}, blocked_now)
    assert text and "2026-11-01" in text

    free_now = datetime(2026, 11, 1, 12, 0, tzinfo=duel_rules.KST)
    assert consent_page.reconsent_notice({"revoked_at": revoked.isoformat()}, free_now) is None
    assert consent_page.reconsent_notice(None) is None


def test_responsibility_notice_appears_in_two_places():
    """
    책임 고지는 **개별 체크박스 영역과 최종 확인 영역, 최소 두 곳**에 나와야 합니다.
    "한 곳에만 작게 적어두는 걸로는 부족합니다"(오너 확정 요구사항).
    """
    code = _page_source(CONSENT_PAGE_NAME)
    assert code.count("warning_banner(NOTICE_RESPONSIBILITY)") >= 2
    assert "본인 책임" in consent_page.NOTICE_RESPONSIBILITY


def test_bracket_notice_explains_why_there_is_no_separate_consent():
    """
    🔴 체급 안내는 두 가지를 함께 말해야 합니다:
      ① 체급의 입력이 **지금 동의하는 그 데이터**(종목별 매입금액의 합)라는 것 —
         그래서 별도의 동의 항목이 없다는 설명이 함께 있어야 결투 화면을 본 사용자가
         "체급 동의를 안 했는데 왜 체급이 정해졌지"라고 오해하지 않습니다(§0-1).
      ② 시즌 동안 고정된다는 것. 숫자는 전부 `duel_rules` 상수에서 만듭니다(§0-3-10).
    """
    notice = consent_page.NOTICE_BRACKET_FIXED
    assert "매입원가합계" in notice
    assert "별도의 동의 항목이" in notice and "없습니다" in notice
    assert f"{duel_rules.DUEL_SEASON_LENGTH_MONTHS}개월" in notice
    assert f"{duel_rules.DUEL_SEASON_ANCHOR_MONTH}월" in notice
    assert f"{duel_rules.DUEL_SEASON_ANCHOR_DAY}일" in notice
    assert duel_rules.BRACKET_NONE_LABEL in notice


def test_nickname_notice_says_one_nickname_per_person():
    """
    🔴 `scorecard_publish_db.ensure_nickname(client, user_id)` 에는 통화 인자가 없습니다 —
    닉네임은 **사람당 하나**이고, 원화 순위표와 달러 순위표에 같은 이름이 실립니다. 사용자가
    모르고 동의하면 안 되는 사실이라 화면에 그대로 있어야 합니다(§0-1).
    """
    import inspect

    signature = inspect.signature(scorecard_publish_db.ensure_nickname)
    assert list(signature.parameters) == ["client", "user_id"], \
        "닉네임이 통화별로 갈리기 시작하면 아래 안내 문구가 거짓이 됩니다"

    notice = consent_page.NOTICE_SHARED_NICKNAME
    assert "하나" in notice
    assert "원화" in notice and "달러" in notice
    assert "같은 닉네임" in notice


def test_tracks_notice_says_consent_is_one_decision():
    """
    🔴 결투와 **정반대**인 사실 — 원화·달러 순위표는 별개의 표지만 **동의는 하나**입니다
    (`scorecard_public_consent` 의 기본키가 `user_id` 하나). "달러만 공개하면 되겠지"라는
    오해를 남기지 않아야 합니다.
    """
    notice = consent_page.NOTICE_TRACKS_INDEPENDENT
    assert "공개 동의 자체는 하나" in notice or "동의 자체는 하나" in notice
    assert "환율" in notice, "두 통화를 합치지 않는 이유를 밝혀야 합니다"


def test_consent_page_never_issues_a_nickname_while_merely_rendering():
    """
    🔴 닉네임은 **동의를 저장한 뒤에만** 발급합니다. 화면을 그리는 함수(`_render_*`) 안에서
    `ensure_nickname()` 을 부르면, 구경만 하고 나간 사용자에게도 영구 닉네임이 생깁니다
    (한 번 만들면 바꿀 수 없습니다 — 스키마 §3-1 에 update 정책이 없습니다).
    """
    source = _page_source(CONSENT_PAGE_NAME)
    for name, node in _function_nodes(CONSENT_PAGE_NAME).items():
        if not name.startswith("_render"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                assert sub.func.id != "ensure_nickname", \
                    f"{name} 이 화면을 그리면서 닉네임을 발급합니다"
    # 저장 경로에는 있어야 합니다(없으면 아무도 순위표에 못 실립니다).
    # 🔴 인자가 `(client, user_id)` 뿐입니다 — 창유형·통화 축이 없기 때문입니다.
    assert "ensure_nickname, client, user_id" in source


def test_consent_page_has_no_account_or_window_axis():
    """
    🔴 "내 성적표"는 사용자당 포트폴리오 하나입니다. 계좌(`account_id`)·창유형
    (`window_type`)이라는 말이 코드에 등장하면 그건 결투 구조를 그대로 옮겨 온 것입니다.
    함께 사라져야 하는 것: 계좌 루프를 위해 존재하던 `_consent_section()` 팩토리.
    """
    names = _code_names(CONSENT_PAGE_NAME)
    for stale in ("account_id", "window_type", "WINDOW_TITLES", "fetch_my_accounts",
                  "_consent_section"):
        assert stale not in names, f"{CONSENT_PAGE_NAME} 에 결투 구조의 잔재가 있습니다: {stale}"


# =============================================================================
# 2. 순위표 화면 — 고정 문구 · 표시 규칙 · 원본 표 격리
# =============================================================================
def test_fixed_notice_is_the_owner_confirmed_text_verbatim():
    """
    🔴 최상단 고정 문구 두 문단. *"문구는 그대로 씁니다 — 요약·축약하지 마세요."*

    이 두 문단은 원래 결투 순위표 맨 위에 있었지만 정작 그 화면에는 가상계좌 성적이
    실려 있었습니다. 이번 전환으로 **처음으로 문구와 내용이 일치**하므로, 한 글자도
    바꾸지 않았는지 원문과 대조합니다.
    """
    assert len(board_page.FIXED_NOTICE_PARAGRAPHS) == 2
    for paragraph in board_page.FIXED_NOTICE_PARAGRAPHS:
        assert _squash(paragraph) in WORK_ORDER_FLAT, f"확정 문안과 다릅니다: {paragraph}"
        # 이 두 문단에 결투 표현이 섞여 있었다면 그대로 옮기면 안 됐을 것입니다.
        assert "가상계좌" not in paragraph and "결투" not in paragraph
    assert "'내 성적표'" in board_page.FIXED_NOTICE_PARAGRAPHS[1]


def test_fixed_notice_is_rendered_before_the_login_gate():
    """
    "스크롤 없이 바로 보이는 위치(최상단)" — 로그인 폼이나 데이터보다 **먼저** 그려져야
    합니다. 소스에서 호출 순서를 확인합니다(위젯을 띄울 수 없는 환경이라 순서로 고정).
    """
    source = _page_source(BOARD_PAGE_NAME)
    body = source[source.index("async def scorecard_leaderboard_page("):]
    body = body[:body.index("\ndef _render_coming_soon")]
    assert body.index("_render_fixed_notice()") < body.index("render_auth()")
    assert body.index("_render_fixed_notice()") < body.index("_render_body(client)")


def test_leaderboard_page_never_touches_the_private_source_tables():
    """
    🔴 §0-3-8 — 순위표 화면은 **발행 전용 표 두 개만** 읽습니다. 원본 표(`holdings` ·
    `profiles`)와 동의·닉네임 표, 그리고 **배치 전용 B 절 함수**는 이름조차 등장하면
    안 됩니다(부르는 순간 앱 서버에 service_role 키가 필요해집니다).
    """
    names = _code_names(BOARD_PAGE_NAME)
    strings = " | ".join(_code_strings(BOARD_PAGE_NAME))

    for table in ("holdings", "profiles", "scorecard_public_consent", "scorecard_nicknames",
                  "scorecard_bracket_assignments", "duel_positions", "duel_cash_ledger"):
        assert table not in strings, f"순위표 화면의 문자열에 {table} 가 있습니다"
    for function in ("fetch_holdings", "fetch_my_consent", "fetch_my_nickname",
                     "ensure_nickname", "save_consent", "revoke_consent",
                     "create_service_client", "fetch_holdings_for_users",
                     "fetch_publishable_consents", "write_public_leaderboard",
                     "write_public_holdings", "build_portfolio"):
        assert function not in names, f"순위표 화면이 {function}() 를 부릅니다"


def test_leaderboard_page_does_not_recompute_ranks():
    """
    §0-3-2 — 순위는 배치가 계산해 저장한 `rank` 를 **읽기만** 합니다. 화면에서 정렬·순위
    계산을 다시 하면 방문자 수만큼 전체 스캔이 돕니다.
    """
    names = _code_names(BOARD_PAGE_NAME)
    for forbidden in ("rank_participants", "compute_twr", "resolve_portfolio_return_pct",
                      "sort", "sorted"):
        assert forbidden not in names, f"순위표 화면이 {forbidden} 로 계산을 다시 합니다"


def test_leaderboard_has_no_window_type_axis_at_all():
    """
    🔴 창유형(M1/M3/M6) 선택기가 **통째로 사라졌습니다.** "내 성적표"는 사용자당
    포트폴리오 하나라 그 축이 존재하지 않습니다 — 선택기는 통화와 체급 둘뿐입니다.
    """
    for name in (BOARD_PAGE_NAME, CONSENT_PAGE_NAME):
        names = _code_names(name)
        for stale in ("window_type", "window_options", "WINDOW_TITLES",
                      "ACCOUNT_WINDOW_TYPES"):
            assert stale not in names, f"{name} 에 창유형 축이 남아 있습니다: {stale}"
    assert not hasattr(board_page, "window_options")


def test_ranking_notice_says_it_is_not_time_weighted():
    """
    🔴 §0-1 — 여기 실리는 수익률은 **TWR 이 아닙니다.** "내 성적표"에는 날짜별 잔고
    시계열이 없어서 시간가중수익률을 계산할 방법 자체가 없고, 대신 매입원가 대비
    수익률을 씁니다(`scorecard_publish.resolve_portfolio_return_pct()`).
    그 사실을 에둘러 말하지 않고 문장으로 밝혀야 합니다.
    """
    notice = board_page.NOTICE_HOW_RANKING_WORKS
    assert "시간가중수익률(TWR)이 아닙니다" in notice
    assert "매입원가" in notice
    assert duel_rules.BRACKET_NONE_LABEL in notice
    # 함수 이름에도 TWR 이 남아 있으면 다음 사람이 그 값을 TWR 로 취급합니다.
    assert not hasattr(board_page, "twr_display")
    assert callable(board_page.return_display)


def test_bracket_options_come_from_the_rules_layer():
    """8구간 + 구간 미적용 = 9개. 라벨은 `duel_rules.bracket_label[_usd]()` 만 씁니다."""
    brackets = board_page.bracket_options()
    assert list(brackets) == list(duel_rules.BRACKET_KEYS)
    assert len(brackets) == len(duel_rules.BRACKET_TIERS) + 1
    assert brackets[duel_rules.BRACKET_NONE_KEY] == duel_rules.BRACKET_NONE_LABEL

    usd = board_page.bracket_options_usd()
    assert list(usd) == list(duel_rules.BRACKET_KEYS_USD)
    # 🔴 두 체급 키 집합은 '구간 미적용' 말고는 하나도 겹치지 않습니다.
    assert set(brackets) & set(usd) == {duel_rules.BRACKET_NONE_KEY}


def test_track_readers_pairs_currency_with_its_own_labels_and_formatting():
    """
    🔴 통화마다 다른 것이 **한 dict 에서 함께** 나와야 합니다 — 조회 통화와 금액 서식
    통화가 두 곳에서 따로 정해지면 언젠가 달러 금액에 "원"이 찍힙니다(§0-1).
    """
    krw = board_page.track_readers(KRW)
    usd = board_page.track_readers(USD)
    assert krw["currency"] == krw["amount"] == KRW
    assert usd["currency"] == usd["amount"] == USD
    assert krw["bracket_label"] is duel_rules.bracket_label
    assert usd["bracket_label"] is duel_rules.bracket_label_usd
    assert list(krw["brackets"]) == list(duel_rules.BRACKET_KEYS)
    assert list(usd["brackets"]) == list(duel_rules.BRACKET_KEYS_USD)
    # 짝이 맞으므로 라벨 함수가 자기 목록의 키를 전부 소화합니다(짝이 틀리면 예외).
    for readers in (krw, usd):
        for key in readers["brackets"]:
            assert readers["bracket_label"](key)
    with pytest.raises(DuelRuleError):
        board_page.track_readers("JPY")


def test_unpublished_values_are_shown_as_private_not_zero():
    """🔴 §0-1 — "수익률 0%"와 "수익률 비공개"는 다른 말입니다. null 은 반드시 '비공개'."""
    assert board_page.return_display(None) == board_page.NOT_PUBLISHED_TEXT
    shown = board_page.return_display(0)
    assert shown != board_page.NOT_PUBLISHED_TEXT and isinstance(shown, str)

    cells = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": None, "buy_amount": None})
    assert cells[1] == board_page.NOT_PUBLISHED_TEXT
    assert cells[2] == board_page.NOT_PUBLISHED_TEXT

    priced = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 10, "buy_amount": 700000})
    assert priced[1] != board_page.NOT_PUBLISHED_TEXT
    assert priced[2] != board_page.NOT_PUBLISHED_TEXT


def test_amount_currency_follows_the_track():
    """💵 달러 보유종목의 매입금액에 "원"이 찍히면 안 됩니다(§0-1)."""
    krw_cell = board_page.holding_row_cells(
        {"ticker": "005930", "stock_name": "삼성전자", "quantity": 1, "buy_amount": 1234}, KRW)[2]
    usd_cell = board_page.holding_row_cells(
        {"ticker": "AAPL", "stock_name": "Apple", "quantity": 1, "buy_amount": 1234}, USD)[2]
    assert "원" in krw_cell and "$" not in krw_cell
    assert "$" in usd_cell and "원" not in usd_cell


def test_pagination_bounds_respect_the_500_caps():
    """상위 500 / 하위 500, 한 페이지 30개. 501번째를 읽어 오는 경로가 없어야 합니다."""
    page_size = duel_rules.LEADERBOARD_PAGE_SIZE
    cap = duel_rules.LEADERBOARD_TOP_COUNT
    assert duel_rules.leaderboard_page_bounds(0) == (0, page_size)

    total = 0
    for index in range(duel_rules.leaderboard_page_count(cap)):
        offset, limit = duel_rules.leaderboard_page_bounds(index, section_cap=cap)
        assert offset + limit <= cap
        total += limit
    assert total == cap, "구간을 전부 훑으면 정확히 상한만큼이어야 합니다"

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
    for name in (BOARD_PAGE_NAME, CONSENT_PAGE_NAME):
        leaked = forbidden & _code_numbers(name)
        assert not leaked, f"{name} 에 규칙 계층의 숫자가 그대로 적혀 있습니다: {sorted(leaked)}"


# =============================================================================
# 3. 🔐 XSS (§0-3-9) — 이 파일에서 **가장 중요한 검사**
# =============================================================================
#  `scorecard_public_holdings.stock_name` 은 사용자가 자유 입력한 값을 배치가 **그대로**
#  옮겨 실은 것입니다(스키마 §2-4 컬럼 주석 · `scorecard_publish.holdings_payload()`
#  독스트링이 `<img onerror=...>` 를 명시적으로 경고). 이 값이 순위표에서 다른 사람의
#  브라우저에 raw HTML 로 도착하면 그건 **저장형 XSS** 입니다 — 화면 하나의 버그가 아니라
#  전 사용자 대상 사고입니다. 값과 구조 두 방향에서 봅니다.
# =============================================================================
def test_holdings_table_escapes_a_malicious_stock_name():
    """🔐 값으로 확인 — 악성 종목명이 **글자 그대로** 출력되고 태그로 살아나지 않는가."""
    html = board_page.holdings_table([
        {"ticker": "999999", "stock_name": XSS_STOCK_NAME,
         "quantity": 1, "buy_amount": 1000},
    ])
    assert "<img src=x onerror=" not in html, "🔐 악성 종목명이 HTML 로 살아났습니다"
    assert "&lt;img src=x onerror=alert(1)&gt;" in html, "이스케이프되어 글자로 보여야 합니다"
    assert board_page.holdings_table([]) is None


def test_holdings_table_escapes_a_malicious_ticker_too():
    """
    🔐 종목코드도 예외가 아닙니다. "종목코드는 숫자니까 안전하다"는 가정은 **발행표에
    저장된 값**에 대해 아무것도 보장하지 않습니다(`ticker` 도 사용자 등록값에서 옵니다).
    """
    html = board_page.holdings_table([
        {"ticker": XSS_TICKER, "stock_name": None, "quantity": 1, "buy_amount": 1000},
    ])
    assert "<script>" not in html, "🔐 악성 종목코드가 HTML 로 살아났습니다"
    assert "&lt;script&gt;" in html
    # stock_name 이 없으면 종목코드가 이름 자리에도 들어갑니다 — 그 자리도 이스케이프됩니다.
    assert html.count("&lt;script&gt;") >= 2


def test_every_interpolated_value_in_the_raw_html_builder_goes_through_esc():
    """
    🔐 구조로 확인 — `holding_row_cells()` 는 이 화면에서 **유일하게 raw HTML 을 조립하는
    함수**입니다. 그 안의 f-string 에 끼워 넣는 값이 하나라도 `esc()` 를 안 거치면 즉시
    실패합니다. 값 검사(위 두 개)는 "지금 넣어본 문자열"만 보지만, 이 검사는 **앞으로
    추가될 칸**까지 함께 막습니다.
    """
    def _is_esc(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "esc")

    node = _function_nodes(BOARD_PAGE_NAME)["holding_row_cells"]

    # 안전한 조합은 둘 중 하나입니다:
    #   ① f-string **통째로** `esc(...)` 안에 들어가 있다 → 그 안의 값은 이미 다 걸러집니다.
    #      (수량 칸이 이 모양입니다: `esc(f'{float(quantity):,.6g}주')`)
    #   ② f-string 이 raw HTML 을 만들고, **끼워 넣는 값마다** `esc(...)` 를 쓴다.
    #      (종목 칸이 이 모양입니다: `f'<div ...>{esc(name)}<br>({esc(ticker)})</div>'`)
    #    (① 은 `esc(f'…' if 조건 else '비공개')` 처럼 조건식을 한 겹 끼고 있을 수도 있어서,
    #     `esc()` 인자 **아래 전체**를 훑어 그 안의 f-string 을 전부 안전으로 표시합니다.)
    wrapped = {id(inner) for sub in ast.walk(node) if _is_esc(sub) for arg in sub.args
               for inner in ast.walk(arg) if isinstance(inner, ast.JoinedStr)}
    templates = [sub for sub in ast.walk(node) if isinstance(sub, ast.JoinedStr)]
    assert templates, "검사기가 f-string 을 하나도 못 찾았습니다(검사가 무의미해집니다)"

    checked = 0
    for template in templates:
        if id(template) in wrapped:
            continue                               # ① 통째로 esc() 안 — 안전
        for value in template.values:
            if not isinstance(value, ast.FormattedValue):
                continue                           # 그냥 글자 조각
            checked += 1
            assert _is_esc(value.value), \
                ("🔐 raw HTML 조립에 esc() 를 거치지 않은 값이 있습니다: "
                 f"{ast.dump(value.value)[:120]}")
    assert checked, "raw HTML 을 만드는 f-string 을 하나도 못 찾았습니다(검사가 무의미해집니다)"


def test_only_one_place_writes_raw_html_and_it_is_the_escaped_table():
    """
    🔐 `ui.html()` 은 문자열을 **그대로** 브라우저에 넣습니다. 이 화면에서 그 호출은 한
    곳뿐이어야 하고, 그 인자는 `holdings_table()`(→ 전부 `esc()` 를 거친 표)에서 온 값
    이어야 합니다. 호출이 하나 늘어나는 순간 이 검사가 그것을 사람 눈앞에 세웁니다.
    """
    tree = ast.parse(_page_source(BOARD_PAGE_NAME))
    html_calls = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "html"]
    assert len(html_calls) == 1, f"ui.html() 호출이 {len(html_calls)}개입니다(1개여야 합니다)"
    (only,) = html_calls
    assert isinstance(only.args[0], ast.Name) and only.args[0].id == "table"


def test_nickname_is_escaped_where_it_reaches_the_screen():
    """
    🔐 닉네임은 서버가 무작위로 뽑은 값이라 사용자가 내용을 정할 수 없지만, **방어는
    깊이로** 겁니다(§0-3-9) — "이 값은 안전하다"는 판단이 코드 여기저기에 흩어지기
    시작하면 언젠가 한 곳이 틀립니다.
    """
    board_src = ast.get_source_segment(
        _page_source(BOARD_PAGE_NAME), _function_nodes(BOARD_PAGE_NAME)["_render_participant"])
    assert "esc(nickname)" in board_src, "순위표 한 줄의 닉네임이 esc() 를 거치지 않습니다"

    consent_src = ast.get_source_segment(
        _page_source(CONSENT_PAGE_NAME),
        _function_nodes(CONSENT_PAGE_NAME)["_render_current_state"])
    assert "esc(str(nickname))" in consent_src, "동의 화면의 닉네임이 esc() 를 거치지 않습니다"


# =============================================================================
# 4. 2단계 공개 게이트 (§0-3-6)
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
    """§0-3-6 기본 숨김 — 아무 플래그도 없으면 메뉴에 항목이 **아예 없습니다**."""
    import web.layout as layout_module

    layout_module = importlib.reload(layout_module)
    assert layout_module.SCORECARD_CONSENT_ENABLED is False
    assert layout_module.SCORECARD_LEADERBOARD_ENABLED is False
    assert not [p for p in (item[0] for item in layout_module._MENU)
                if p.startswith("/scorecard/")]


def test_public_screens_start_admin_only():
    """
    ⏳ 2026-08-23 — 두 화면 모두 **2단계(관리자 전용)에서 시작**합니다. 전체 공개 전환은
    오너가 이 값을 False 로 바꾸는 것으로만 일어납니다(결투 공개 계층이 밟았던 순서 그대로).
    이 검사가 실패한다면 그건 실수로 전체 공개된 것이거나, 오너가 전환하면서 여기를 함께
    갱신하지 않은 것입니다 — 어느 쪽이든 사람이 봐야 합니다.
    """
    import web.layout as layout_module

    layout_module = importlib.reload(layout_module)
    assert layout_module.SCORECARD_CONSENT_MENU_ADMIN_ONLY is True
    assert layout_module.SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY is True


def test_public_screens_appear_one_at_a_time_inside_the_scorecard_group():
    """
    동의 화면과 순위표 화면은 **따로** 열 수 있어야 합니다(동의 화면을 먼저 열어 참가자를
    모으는 것이 원래 순서). 그리고 두 항목은 `/scorecard` 와 **같은 메뉴 그룹**에 붙습니다.
    """
    only_consent = _menu_with(SCORECARD_CONSENT_ENABLED="true")
    assert "/scorecard/consent" in only_consent
    assert "/scorecard/leaderboard" not in only_consent

    both = _menu_with(SCORECARD_CONSENT_ENABLED="true", SCORECARD_LEADERBOARD_ENABLED="true")
    assert {"/scorecard", "/scorecard/consent", "/scorecard/leaderboard"} <= set(both)

    # 🔴 결투 스위치와 무관합니다 — `DUEL_ENABLED` 없이도 켜집니다(공개되는 것은 결투
    #    가상계좌가 아니라 "내 성적표"이기 때문).
    assert "/duel" not in both

    # 두 항목이 붙는 자리는 `/scorecard` 와 **같은 그룹**입니다(공개되는 데이터가 바로
    # 그 화면의 보유종목이라, 다른 그룹에 두면 사용자가 무엇을 공개하는지 헷갈립니다).
    with_flags = _menu_group_items("📊 보유종목", SCORECARD_CONSENT_ENABLED="true",
                                   SCORECARD_LEADERBOARD_ENABLED="true")
    assert [path for path, _l, _a in with_flags] == [
        "/scorecard", "/report", "/scorecard/consent", "/scorecard/leaderboard"]


def _menu_group_items(group_label, **env):
    """환경변수를 바꾼 상태에서 특정 메뉴 그룹의 항목 목록을 돌려줍니다."""
    import web.layout as layout_module

    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        reloaded = importlib.reload(layout_module)
        return [items for label, items in reloaded._MENU_GROUPS if label == group_label][0]
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(layout_module)


@pytest.mark.parametrize("module_name,flag_names", [
    (CONSENT_PAGE_NAME, ("SCORECARD_CONSENT_ENABLED", "SCORECARD_CONSENT_MENU_ADMIN_ONLY")),
    (BOARD_PAGE_NAME, ("SCORECARD_LEADERBOARD_ENABLED",
                       "SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY")),
])
def test_each_public_screen_checks_its_own_flags_and_login(module_name, flag_names):
    """
    메뉴에서 감추는 것만으로는 부족합니다 — 주소를 아는 사람은 그냥 들어옵니다. 화면도
    같은 값을 직접 보고, 로그인 게이트를 다른 화면과 같은 순서로 통과해야 합니다.
    """
    names = _code_names(module_name)
    for flag in flag_names:
        assert flag in names, f"{module_name} 이 {flag} 를 보지 않습니다"
    assert "is_admin" in names, "관리자 전용 단계를 화면에서도 확인해야 합니다"
    for gate in ("supabase_status", "has_supabase_session", "render_auth",
                 "get_client_async", "current_user_async", "user_id_of", "logout_async"):
        assert gate in names, f"{module_name} 에 로그인 게이트({gate})가 없습니다"


def test_public_screens_do_not_keep_user_state_in_module_globals():
    """
    §0-3-8 — 모듈 최상위에는 상수만 있어야 합니다. 사용자·클라이언트·상태를 연상시키는
    이름의 전역이 새로 생기면 여기서 잡힙니다.
    """
    suspicious = re.compile(r"^(client|user|session|token|state|view|cache|_[a-z]+_cache)",
                            re.IGNORECASE)
    for name in (CONSENT_PAGE_NAME, BOARD_PAGE_NAME):
        tree = ast.parse(_page_source(name))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assert not suspicious.match(target.id), \
                        f"{name} 의 전역 `{target.id}` 가 사용자 상태처럼 보입니다(§0-3-8)"


def test_pages_are_registered_at_the_expected_routes():
    """경로가 바뀌면 메뉴 링크가 404 가 됩니다. 소스에서 직접 확인합니다."""
    assert "@ui.page('/scorecard/consent'" in _page_source(CONSENT_PAGE_NAME)
    assert "@ui.page('/scorecard/leaderboard'" in _page_source(BOARD_PAGE_NAME)
    main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "scorecard_consent_page" in main_source
    assert "scorecard_leaderboard_page" in main_source


# =============================================================================
# 5. 렌더 스모크 — 화면 함수를 **실제로 실행**해 봅니다
# =============================================================================
#  위젯은 (환경에 따라) 스텁이라 화면이 그려지지는 않지만, 분기·문구 조립·이스케이프·질의
#  횟수는 전부 진짜로 돕니다. 동의·순위는 **합성 데이터**이고 DB 호출은 전부 대체합니다 —
#  실제 Supabase 에 접속하지 않습니다(§0-1).
# =============================================================================
SYNTHETIC_CONSENTS = {
    "none": None,                                          # 아직 아무것도 안 한 사용자
    "confirmed": dict({flag: True for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS},
                      user_id="uid-1", final_confirmed=True,
                      final_confirmed_at="2026-08-22T20:00:00+09:00"),
    "revoked": {"user_id": "uid-1", "revoked_at": "2026-08-22T20:00:00+09:00"},
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


@pytest.mark.parametrize("situation", sorted(SYNTHETIC_CONSENTS))
def test_consent_body_renders_every_state(situation):
    """
    동의 화면 본문이 **끝까지** 실행되는지 — 기록 없음 / 최종확인 완료 / 철회(차단 중)
    세 상태를 각각 그립니다(카드가 한 장이므로 상태마다 한 번씩).
    """
    saved = _patch(
        consent_page,
        fetch_my_consent=lambda client, user_id: SYNTHETIC_CONSENTS[situation],
        fetch_my_nickname=lambda client, user_id: {"nickname": "굳센날쌘범"},
    )
    try:
        _run(consent_page._render_body(object(), "uid-1"))
    finally:
        _restore(consent_page, saved)


def test_consent_body_never_reads_holdings_or_creates_a_nickname_while_rendering():
    """
    🔴 화면을 그리는 것만으로 ① 실제 보유종목을 읽거나 ② 닉네임을 발급하지 않습니다.
    가짜 클라이언트가 오간 질의의 **표 이름**을 그대로 들고 있으므로 값으로 확인합니다.
    """
    client = FakeClient(responses={
        (scorecard_publish_db.CONSENT_TABLE, "select"): [SYNTHETIC_CONSENTS["confirmed"]],
        (scorecard_publish_db.NICKNAMES_TABLE, "select"): [{"nickname": "굳센날쌘범"}],
    })
    _run(consent_page._render_body(client, "uid-1"))

    assert {call.table for call in client.calls} <= {
        scorecard_publish_db.CONSENT_TABLE, scorecard_publish_db.NICKNAMES_TABLE}
    assert {call.op for call in client.calls} == {"select"}, \
        "화면을 그리는 행위는 아무것도 만들거나 바꾸지 않습니다"


def _leaderboard_client(stock_name=XSS_STOCK_NAME):
    """발행일 조회(`limit(1)`)와 순위 페이지 조회에 서로 다른 응답을 주는 가짜 클라이언트."""
    rows = [{"published_date": "2026-08-22", "currency": KRW,
             "bracket_key": duel_rules.BRACKET_KEYS[0], "rank": rank,
             "nickname": f"닉네임{rank}",
             "return_pct": None if rank == 2 else 5.5 - rank}   # 2위는 수익률 비공개
            for rank in (1, 2, 3)]
    holdings = [{"published_date": "2026-08-22", "currency": KRW, "nickname": "닉네임1",
                 "ticker": "005930", "stock_name": stock_name,
                 "quantity": None, "buy_amount": 700000.0}]
    return FakeClient(responses={
        (scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select"):
            lambda query: ([{"published_date": "2026-08-22"}]
                           if query.options.get("limit") == 1 else rows),
        (scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "select"): holdings,
    })


def test_leaderboard_body_renders_and_does_not_preload_holdings():
    """
    §0-3-2 — 화면을 여는 것만으로 참가자 상세를 미리 읽지 않습니다(펼칠 때 처음 읽습니다).
    질의는 발행일 1 + 위쪽 1 + 아래쪽 1 = 3개뿐이어야 합니다.
    """
    client = _leaderboard_client()
    _run(board_page._render_body(client))

    assert {call.table for call in client.calls} == {
        scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE}, "보유종목은 펼치기 전에는 읽지 않습니다"
    assert len(client.calls) == 3, [(c.table, c.options) for c in client.calls]
    # 🔴 통화를 반드시 걸어 읽습니다(걸지 않으면 원화 화면에 달러 행이 섞입니다).
    for call in client.calls:
        assert call.filter_map.get("currency") == KRW
        assert "window_type" not in call.filter_map


def test_leaderboard_body_handles_an_unpublished_group_as_a_normal_state():
    """
    참가자가 없거나 최소 인원 미달이면 **오류가 아니라 안내**입니다. 질의도 1개만 나갑니다
    (발행일이 없으면 순위를 읽으러 가지 않습니다). 셋 중 무엇인지 **구분해 보여주지
    않습니다** — 구분 자체가 "이 구간에 몇 명쯤 있는지"의 힌트가 되기 때문입니다.
    """
    notices = []
    client = FakeClient()                                    # 모든 select 가 빈 목록
    saved = _patch(board_page, info_banner=lambda text: notices.append(text))
    try:
        _run(board_page._render_body(client))
    finally:
        _restore(board_page, saved)

    assert len(client.calls) == 1
    assert any("아직 공개할 만큼" in text for text in notices), notices
    blob = " ".join(notices)
    for leak in ("명", "미달", "참가자 수"):
        assert leak not in board_page.NOTICE_EMPTY_GROUP or "충분히" in blob


def test_leaderboard_holdings_panel_renders_escaped_and_marks_private_fields():
    """
    🔐 펼쳤을 때의 경로 — 이 화면에서 사용자 자유 입력값이 실제로 브라우저까지 가는 **유일한
    경로**입니다. 악성 종목명을 진짜로 흘려보고, 그 문자열이 raw 로는 한 번도 나타나지
    않는지 확인합니다(§0-3-9). '비공개' 표기(§0-1)도 함께 봅니다.
    """
    captured = []
    client = _leaderboard_client()
    real_table = board_page.holdings_table

    def _spy(rows, currency=KRW):
        result = real_table(rows, currency)
        captured.append(result)
        return result

    saved = _patch(board_page, holdings_table=_spy)
    try:
        _run(board_page._render_holdings(
            client, "2026-08-22", "닉네임1", board_page.track_readers(KRW)))
    finally:
        _restore(board_page, saved)

    blob = "\n".join(str(item) for item in captured)
    assert blob, "보유종목 표가 그려지지 않았습니다(검사가 무의미해집니다)"
    assert XSS_STOCK_NAME not in blob, "🔐 악성 종목명이 이스케이프되지 않고 그대로 나갔습니다"
    assert "<img src=x onerror=" not in blob
    assert "&lt;img src=x onerror=alert(1)&gt;" in blob
    assert board_page.NOT_PUBLISHED_TEXT in blob, "수량 비공개가 '비공개'로 그려져야 합니다"

    # 닉네임·날짜·통화로 정확히 걸러 읽었는지(다른 날짜·다른 사람·다른 통화가 섞이지 않게).
    call = client.only_call(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "select")
    assert call.filter_map == {"nickname": "닉네임1", "published_date": "2026-08-22",
                               "currency": KRW}


def test_leaderboard_usd_track_reads_the_usd_rows_and_formats_in_dollars():
    """💵 달러를 골랐을 때 달러 행만 읽고, 금액도 달러로 씁니다(§0-1)."""
    captured = []
    client = _leaderboard_client(stock_name="Apple")
    real_table = board_page.holdings_table

    def _spy(rows, currency=KRW):
        captured.append(currency)
        return real_table(rows, currency)

    saved = _patch(board_page, holdings_table=_spy)
    try:
        _run(board_page._render_holdings(
            client, "2026-08-22", "닉네임1", board_page.track_readers(USD)))
    finally:
        _restore(board_page, saved)

    assert captured == [USD]
    call = client.only_call(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "select")
    assert call.filter_map["currency"] == USD
