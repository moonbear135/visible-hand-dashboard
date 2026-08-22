# tests/test_duel_consent_page_usd.py
"""
💵 "결투다!" — **달러 결투(USD 트랙) 공개 동의 관리 화면** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요)

`DUEL_MODULE_WORK_ORDER.md` §5-2(동의 UX) · §5-8(철회) · §5-11-10(트랙 독립 + 닉네임 공유) ·
§5-19(이 라운드)가 `web/pages/duel_consent_page.py` 에서 실제로 지켜지는지 회귀로 고정합니다.

⚠️ **이 파일이 지키려는 사고는 전부 "조용히 틀리는" 종류입니다.** 예외도 로그도 없이,
   사용자에게만 틀린 상태가 보이거나 **엉뚱한 표에 동의가 저장되는** 것들입니다.
   그래서 검사도 "예외가 안 났는가"가 아니라 **"정확히 어느 표에, 무엇을 저장했는가"** 를 봅니다.

     ① 🔴 **표 혼선** — 달러 동의가 원화 표(`duel_public_consent`)에 저장되면, 사용자는
        달러를 공개했다고 믿는데 실제로는 **원화 성적이 공개**됩니다. 이 모듈에서 가장
        나쁜 종류의 버그입니다(§5-2 머리말 "사용자가 동의하지 않은 것에 동의한 셈").
     ② 🔴 **닉네임 함수 오분기** — 닉네임은 원화·달러가 **같은 표**를 공유합니다
        (5-11-10 · 스키마 §6, `duel_nicknames_usd` 라는 표는 존재하지 않습니다).
        여기서 `_usd` 판을 찾아 만들면 "닉네임이 트랙마다 갈린다"는 틀린 모델이 박힙니다.
     ③ 🔴 **원화 회귀** — 달러 계좌가 없는 사용자(= 오늘 실제 사용자 전원)의 화면이
        2026-08-21 이전과 같은 경로를 타는가.
     ④ 🔴 **트랙 독립** — 원화만/달러만/둘 다/둘 다 아님, 네 경우가 전부 정상 상태인가
        (특히 "달러만 참여"가 '참여하지 않으셨습니다' 로 잘못 안내되지 않는가).
     ⑤ 🔴 **소유자 이중 방어(§0-3-8)** — 달러 계좌에도 원화와 **똑같이** 적용되는가.
     ⑥ 🔴 **체급 기준 통화** — 독립 동의(실제 매입총합) 설명이 달러 트랙에서도 사실인가.

⚠️ 여기서 **검증하지 못하는 것**(§0-1 — 할 수 있는 것만 했다고 말합니다):
    · 실제 브라우저에 픽셀이 어떻게 찍히는지. 위젯은 실행되지만 그려지지는 않습니다.
    · 실제 Supabase RLS·트리거가 막아주는지(그건 `sql/duel_schema.sql` §14 의 몫).

실행: pytest tests/test_duel_consent_page_usd.py -v
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

from web.pages import duel_consent_page as consent_page                  # noqa: E402

PAGE_PATH = REPO_ROOT / "web" / "pages" / "duel_consent_page.py"
PAGE_SRC = PAGE_PATH.read_text(encoding="utf-8")
PAGE_TREE = ast.parse(PAGE_SRC)


# =============================================================================
# 0. 도우미 — 소스 구조 / 비동기 실행 / 합성 데이터
# =============================================================================
def _functions():
    """{함수이름: ast 노드} — 중첩 함수(처리기)까지 전부."""
    found = {}
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


FUNCTIONS = _functions()


def _names_used(node):
    """함수 본문에서 쓰인 이름(변수·함수·속성)의 집합. 중첩 함수 안까지 봅니다.

    ⚠️ 이 화면의 DB 호출은 전부 `run_blocking(fetch_x, client, …)` 모양이라, `ast.Call` 만
       세면 **DB 호출이 한 건도 안 보입니다**(§5-18 이 겪은 그대로). 그래서 "이 이름이 이
       함수 안에서 쓰였는가"로 봅니다.
    """
    used = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.add(child.attr)
    return used


def _executable_constants(node):
    """함수 안의 **독스트링을 뺀** 문자열 상수 집합.

    이 저장소는 근거를 독스트링에 길게 적는 관례라, 문자열을 전부 세면 "설명을 잘 쓸수록
    검사가 실패"합니다 — 그건 검사가 잘못된 것이지 코드가 잘못된 게 아닙니다
    (`tests/test_duel_public_ui.py::_code_strings()` 와 같은 판단).
    """
    docstring = ast.get_docstring(node, clean=False)
    return {child.value for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
            and child.value != docstring}


def _run(coro):
    """비동기 화면 함수를 끝까지 실행합니다(NiceGUI 슬롯 컨텍스트를 새 태스크에 넘겨서).

    `tests/test_duel_public_ui.py::_run()` 과 **같은 방식**입니다 — 같은 흉내를 두 벌
    만들지 않으려는 것이지만, 그 파일의 모듈 수준 스텁 설치를 이 파일까지 끌어오지 않으려고
    함수만 같은 모양으로 둡니다(§0-3-10 의 취지는 유지, 부작용은 차단).
    """
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


KRW_ACCOUNTS = [
    {"id": "krw-m1", "user_id": "uid-1", "window_type": "M1", "currency": "KRW"},
    {"id": "krw-m3", "user_id": "uid-1", "window_type": "M3", "currency": "KRW"},
    {"id": "krw-m6", "user_id": "uid-1", "window_type": "M6", "currency": "KRW"},
]

USD_ACCOUNTS = [
    {"id": "usd-m1", "user_id": "uid-1", "window_type": "M1", "currency": "USD"},
    {"id": "usd-m3", "user_id": "uid-1", "window_type": "M3", "currency": "USD"},
    {"id": "usd-m6", "user_id": "uid-1", "window_type": "M6", "currency": "USD"},
]


def _confirmed_row(account_id):
    row = {flag: True for flag in duel_db.CONSENT_ITEM_FLAGS}
    row.update({"account_id": account_id, "final_confirmed": True,
                "final_confirmed_at": "2026-08-20T10:00:00+09:00", "revoked_at": None,
                duel_db.CONSENT_REAL_PRINCIPAL_FLAG: True})
    return row


class _Harness:
    """`_render_body()` 를 실제로 실행하고, **어느 조회 함수를 몇 번 불렀는지** 모읍니다.

    §0-1 — 계좌·동의는 전부 합성 데이터이고 Supabase 에는 접속하지 않습니다.
    """

    _NAMES = ("fetch_my_accounts", "fetch_my_accounts_usd",
              "fetch_my_consent", "fetch_my_consent_usd", "fetch_my_nickname")

    def __init__(self, krw_accounts, usd_accounts, *, usd_fails=False):
        self.krw_accounts = krw_accounts
        self.usd_accounts = usd_accounts
        self.usd_fails = usd_fails
        self.calls = []
        self.banners = []

    def __enter__(self):
        def _record(name, fn):
            def wrapped(*args, **kwargs):
                self.calls.append(name)
                return fn(*args, **kwargs)
            return wrapped

        def _usd_accounts(_client, _user_id):
            if self.usd_fails:
                raise RuntimeError("달러 계좌 조회 실패(테스트)")
            return [dict(a) for a in self.usd_accounts]

        self._saved = _patch(
            consent_page,
            fetch_my_accounts=_record(
                "fetch_my_accounts",
                lambda client, user_id: [dict(a) for a in self.krw_accounts]),
            fetch_my_accounts_usd=_record("fetch_my_accounts_usd", _usd_accounts),
            fetch_my_consent=_record(
                "fetch_my_consent", lambda client, account_id: _confirmed_row(account_id)),
            fetch_my_consent_usd=_record(
                "fetch_my_consent_usd", lambda client, account_id: _confirmed_row(account_id)),
            fetch_my_nickname=_record(
                "fetch_my_nickname",
                lambda client, user_id, window_type: {"nickname": "굳센날쌘범"}),
            error_banner=lambda text: self.banners.append(str(text)),
            info_banner=lambda text: self.banners.append(str(text)),
        )
        return self

    def __exit__(self, *_exc):
        _restore(consent_page, self._saved)
        return False

    def run(self):
        _run(consent_page._render_body(object(), "uid-1"))
        return self


# =============================================================================
# 1. 🔴 표 혼선 금지 — 달러 블록은 `_usd` 함수만 부릅니다 (§5-11-1 "완전 분리")
# =============================================================================
KRW_CONSENT_DB_FUNCTIONS = ("fetch_my_consent", "save_consent", "revoke_consent",
                            "fetch_my_accounts")

USD_ONLY_FUNCTIONS = ("_render_account_consent_usd", "_render_consent_form_usd",
                      "_render_real_principal_form_usd", "_render_revoke_usd", "_save_usd")


@pytest.mark.parametrize("name", USD_ONLY_FUNCTIONS)
def test_usd_functions_never_touch_the_krw_consent_functions(name):
    """달러 함수 어디에도 원화 동의 함수 이름이 나오지 않습니다(AST).

    🔴 이 검사가 잡으려는 사고: `_save_usd()` 가 `save_consent()` 를 부르면, 사용자는
       달러를 공개했다고 믿는데 실제로는 **원화 계좌 동의 표**가 켜집니다. 예외도 로그도
       나지 않습니다 — 그래서 이름 하나하나를 고정합니다.
    """
    used = _names_used(FUNCTIONS[name])
    for krw in KRW_CONSENT_DB_FUNCTIONS:
        assert krw not in used, f"{name}() 이 원화 함수 {krw}() 를 씁니다(§5-11-1 위반)."


def test_usd_functions_actually_use_the_usd_layer():
    """반대 방향 — 달러 함수가 `_usd` 계층을 **실제로** 부르는지."""
    expected = {
        "_render_account_consent_usd": "fetch_my_consent_usd",
        "_render_revoke_usd": "revoke_consent_usd",
        "_save_usd": "save_consent_usd",
    }
    for func, target in expected.items():
        assert target in _names_used(FUNCTIONS[func]), f"{func}() 이 {target}() 을 안 부릅니다."
    assert "fetch_my_accounts_usd" in _names_used(FUNCTIONS["_render_body"])


def test_usd_render_chain_is_wired_to_the_usd_forms():
    """달러 카드가 부르는 세 함수가 전부 `_usd` 판인지(원화 폼이 섞이면 저장이 원화로 갑니다)."""
    used = _names_used(FUNCTIONS["_render_account_consent_usd"])
    for target in ("_render_revoke_usd", "_render_consent_form_usd",
                   "_render_real_principal_form_usd"):
        assert target in used, f"_render_account_consent_usd() 가 {target}() 를 안 부릅니다."
    for krw in ("_render_revoke", "_render_consent_form", "_render_real_principal_form"):
        assert krw not in used, f"_render_account_consent_usd() 가 원화 {krw}() 를 부릅니다."


def test_the_two_consent_tables_are_physically_different():
    """표 이름 자체가 다른지(§5-11-1 — 구분 컬럼이 아니라 물리적 분리)."""
    assert duel_db_usd.CONSENT_TABLE_USD == "duel_public_consent_usd"
    assert duel_db.CONSENT_TABLE == "duel_public_consent"
    assert duel_db_usd.CONSENT_TABLE_USD != duel_db.CONSENT_TABLE


# =============================================================================
# 2. 🔴 닉네임은 통화 공통 — `_usd` 판을 만들지 않았습니다 (5-11-10 · 스키마 §6)
# =============================================================================
def test_nickname_functions_are_shared_objects_not_copies():
    """`is` 항등성 — 같은 이름의 복제본이 아니라 **같은 객체**여야 합니다."""
    assert duel_db_usd.ensure_nickname is duel_db.ensure_nickname
    assert duel_db_usd.fetch_my_nickname is duel_db.fetch_my_nickname
    assert consent_page.ensure_nickname is duel_db.ensure_nickname
    assert consent_page.fetch_my_nickname is duel_db.fetch_my_nickname


def test_no_usd_suffixed_nickname_function_exists_anywhere():
    """`ensure_nickname_usd`/`fetch_my_nickname_usd` 는 **존재하면 안 됩니다**.

    존재하는 순간 "닉네임이 트랙마다 갈린다"는 틀린 모델이 코드에 박히고, 같은 사용자가
    두 트랙에서 서로 다른 이름을 받게 됩니다(5-11-10 정면 위반).
    """
    for name in ("ensure_nickname_usd", "fetch_my_nickname_usd"):
        assert not hasattr(duel_db_usd, name), f"{name}() 이 생겼습니다 — 5-11-10 위반."
        assert name not in PAGE_SRC, f"화면이 {name}() 을 찾습니다 — 그런 함수는 없습니다."


def test_usd_save_path_issues_the_shared_nickname_with_user_and_window():
    """달러 저장 경로도 **접미사 없는** `ensure_nickname(client, user_id, window_type)`.

    계좌 id 로 부르면(옛 시그니처) 원화·달러가 같은 이름을 공유할 수가 없습니다.
    """
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_save_usd"])
    assert 'ensure_nickname, client, account.get("user_id"), account.get("window_type")' in src
    assert "account_id" not in src.split("ensure_nickname")[1][:200], (
        "닉네임을 계좌 id 로 발급하려 합니다(스키마 §6 재구조화 이전 모양)."
    )


def test_nickname_is_never_issued_while_merely_rendering_usd():
    """🔴 5-5 — 달러 쪽 `_render_*` 함수도 화면을 그리면서 닉네임을 만들지 않습니다."""
    for name, node in FUNCTIONS.items():
        if not name.startswith("_render") or not name.endswith("_usd"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                assert sub.func.id != "ensure_nickname", f"{name}() 이 닉네임을 발급합니다."
    # 달러 카드는 **만들지 않는** 조회 함수만 씁니다.
    assert "fetch_my_nickname" in _names_used(FUNCTIONS["_render_account_consent_usd"])


def test_screen_discloses_that_the_nickname_is_shared_across_tracks():
    """
    🔴 §0-1 — 두 트랙에 모두 공개하면 **두 순위표에 같은 닉네임이 실립니다.** 보는 사람이
    "이 두 줄은 같은 사람"이라고 알 수 있다는 뜻이고, 사용자가 모르고 동의하면 안 되는
    사실이라 화면에 그대로 밝혀야 합니다.
    """
    notice = consent_page.NOTICE_SHARED_NICKNAME
    assert "같은 닉네임" in notice
    assert "같은 사람" in notice
    assert "저장조차" in notice, "신원 값이 발행표에 없다는 사실도 함께 밝힙니다(§0-3-8)."
    assert "NOTICE_SHARED_NICKNAME" in PAGE_SRC.split("def _render_both_tracks")[1][:2000], (
        "닉네임 공유 고지가 원화·달러 병기 화면에 실제로 그려지지 않습니다."
    )


# =============================================================================
# 3. 🔴 재사용을 주장하는 순수 함수·상수의 `is` 항등성 (§0-3-10)
# =============================================================================
def test_consent_flags_are_the_same_objects_in_both_layers():
    """항목 5개 + 독립 동의 플래그는 **같은 객체**입니다(복제하면 언젠가 한쪽만 바뀝니다)."""
    assert duel_db_usd.CONSENT_ITEM_FLAGS is duel_db.CONSENT_ITEM_FLAGS
    assert duel_db_usd.CONSENT_REAL_PRINCIPAL_FLAG is duel_db.CONSENT_REAL_PRINCIPAL_FLAG
    assert consent_page.CONSENT_ITEM_FLAGS is duel_db.CONSENT_ITEM_FLAGS
    assert len(duel_db.CONSENT_ITEM_FLAGS) == 5


def test_pure_screen_rules_are_reused_not_duplicated():
    """
    순수 함수는 통화별 판을 만들지 **않았습니다** — `_usd` 이름이 아예 없어야 합니다.

    (근거: 본문에 통화 리터럴도, 표 이름도 없습니다. 이 트랙의 판단 기준 그대로 —
     "표 이름·통화·시간대가 본문에 박힌 것만 새로 정의".)
    """
    for name in ("consent_item_rows", "missing_item_labels", "all_items_checked",
                 "item_save_payload", "final_confirm_payload", "real_principal_payload",
                 "_assert_no_real_principal", "revoke_guard", "consent_state",
                 "reconsent_notice", "_render_current_state"):
        assert hasattr(consent_page, name)
        assert not hasattr(consent_page, f"{name}_usd"), (
            f"{name}_usd() 가 생겼습니다 — 이 함수는 통화 무관이라 복제할 이유가 없습니다."
        )


def test_reused_pure_functions_contain_no_currency_literal():
    """재사용을 주장하는 함수들의 **본문**에 통화 리터럴이 없는지 직접 확인합니다.

    이 프로젝트에서 "통화 무관인 줄 알았는데 실제로는 리터럴이 박혀 있던" 함수가 이미
    여러 개 나왔습니다(`_translate_order_guard_error`·`format_summary_lines`·
    `resolve_fill_trading_day`·`resolve_bracket_for_season`). 주장만 하지 않고 봅니다.
    """
    for name in ("consent_item_rows", "missing_item_labels", "all_items_checked",
                 "item_save_payload", "final_confirm_payload", "real_principal_payload",
                 "revoke_guard", "consent_state", "reconsent_notice",
                 "_render_current_state"):
        # 독스트링은 걷어내고 **실행되는 코드의 문자열 상수만** 봅니다(설명을 길게 쓰는
        # 이 저장소의 관례를 검사가 벌하지 않도록 — `test_duel_public_ui._code_strings()`).
        for literal in _executable_constants(FUNCTIONS[name]):
            for currency_word in ("KRW", "USD", "원화", "달러", "$"):
                assert currency_word not in literal, (
                    f"{name}() 본문 문자열에 통화 리터럴 {currency_word} 이 있습니다: {literal!r}"
                )


def test_the_usd_forms_call_the_shared_pure_functions():
    """달러 폼이 순수 규칙을 **다시 구현하지 않고** 공용 함수를 부르는지."""
    used = _names_used(FUNCTIONS["_render_consent_form_usd"])
    for shared in ("consent_item_rows", "all_items_checked", "missing_item_labels",
                   "item_save_payload", "final_confirm_payload"):
        assert shared in used, f"_render_consent_form_usd() 가 {shared}() 를 안 씁니다."
    assert "real_principal_payload" in _names_used(FUNCTIONS["_render_real_principal_form_usd"])
    assert "revoke_guard" in _names_used(FUNCTIONS["_render_revoke_usd"])


def test_reconsent_block_rule_is_shared_and_counted_per_track():
    """3개월 차단 판정 함수는 공유이고(같은 객체), 판정 **대상 행**만 트랙별입니다."""
    assert "resolve_reconsent_block" in _names_used(FUNCTIONS["reconsent_notice"])
    assert duel_rules.RECONSENT_BLOCK_MONTHS == 3
    # 달러 카드는 달러 동의 행으로만 판정합니다(원화 행을 넘기는 자리가 없습니다).
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_account_consent_usd"])
    assert "reconsent_notice(consent_row)" in src
    assert "fetch_my_consent(" not in src


# =============================================================================
# 4. 🔴 화면이 만든 payload 가 **달러 저장 계층**에 그대로 통하는가 (계약 확인)
# =============================================================================
def _all_checked():
    return {flag: True for flag in duel_db.CONSENT_ITEM_FLAGS}


def test_item_payload_saves_into_the_usd_table_only():
    client = FakeClient()
    duel_db_usd.save_consent_usd(client, "usd-m1",
                                 **consent_page.item_save_payload(_all_checked()))

    assert {call.table for call in client.calls} == {duel_db_usd.CONSENT_TABLE_USD}, (
        "달러 동의가 원화 표로 갔습니다 — 이 모듈에서 가장 나쁜 종류의 버그입니다."
    )
    saved = client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "upsert")[0]
    assert saved.payload.get("final_confirmed") is None, "1단계에는 최종확인이 없습니다(5-2-3)."
    assert duel_db.CONSENT_REAL_PRINCIPAL_FLAG not in saved.payload, "독립 동의 분리(5-2-4)."


def test_final_confirm_payload_saves_into_the_usd_table_with_a_timestamp():
    client = FakeClient()
    duel_db_usd.save_consent_usd(client, "usd-m1",
                                 **consent_page.final_confirm_payload(_all_checked()))
    saved = client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "upsert")[0]
    assert saved.payload["final_confirmed"] is True
    assert saved.payload.get("final_confirmed_at")


def test_real_principal_payload_is_a_separate_usd_request():
    client = FakeClient()
    duel_db_usd.save_consent_usd(client, "usd-m1",
                                 **consent_page.real_principal_payload(True))
    saved = client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "upsert")[0]
    assert saved.payload[duel_db.CONSENT_REAL_PRINCIPAL_FLAG] is True
    assert not any(flag in saved.payload for flag in duel_db.CONSENT_ITEM_FLAGS), (
        "독립 동의는 5개 항목과 **같은 요청**에 절대 실리지 않습니다(5-2-4)."
    )


def test_partial_consent_is_rejected_by_the_usd_layer_too():
    """5-2-2 '전부 아니면 전무'는 달러 저장 계층에서도 그대로 강제됩니다."""
    partial = dict(_all_checked(), **{duel_db.CONSENT_ITEM_FLAGS[0]: False})
    partial["final_confirmed"] = True
    with pytest.raises(duel_db.DuelDbError):
        duel_db_usd.save_consent_usd(FakeClient(), "usd-m1", **partial)


# =============================================================================
# 5. 🔴 트랙 독립 — 네 경우가 전부 정상 상태 (§5-11-10)
# =============================================================================
def test_krw_only_user_never_reads_the_usd_consent_table():
    """달러 계좌가 없으면 달러 **상세** 조회는 한 번도 일어나지 않습니다(불필요한 왕복 금지)."""
    with _Harness(KRW_ACCOUNTS, []) as harness:
        harness.run()

    assert "fetch_my_accounts" in harness.calls
    assert "fetch_my_accounts_usd" in harness.calls, (
        "달러 계좌 유무는 매번 확인해야 합니다(있는데 안 보여주면 그게 더 나쁩니다)."
    )
    assert "fetch_my_consent_usd" not in harness.calls
    assert harness.calls.count("fetch_my_consent") == len(KRW_ACCOUNTS)


def test_usd_only_user_gets_a_full_consent_screen_not_a_join_notice():
    """
    🔴 §5-19 에서 고친 바로 그 자리 — 예전 코드는 `mine`(원화)만 보고 "아직 결투에
    참여하지 않으셨습니다"를 띄웠습니다. 달러에만 참여한 사용자는 동의 화면 자체를
    쓸 수 없었을 것입니다.
    """
    with _Harness([], USD_ACCOUNTS) as harness:
        harness.run()

    assert not any("참여하지 않으셨습니다" in text for text in harness.banners), harness.banners
    assert harness.calls.count("fetch_my_consent_usd") == len(USD_ACCOUNTS)
    assert "fetch_my_consent" not in harness.calls, "원화 계좌가 없는데 원화 동의를 읽었습니다."


def test_both_tracks_render_and_never_mix_the_two_consent_reads():
    with _Harness(KRW_ACCOUNTS, USD_ACCOUNTS) as harness:
        harness.run()

    assert harness.calls.count("fetch_my_consent") == len(KRW_ACCOUNTS)
    assert harness.calls.count("fetch_my_consent_usd") == len(USD_ACCOUNTS)
    # 닉네임은 계좌 6개 각각에 대해 조회되지만, 부르는 함수는 **하나**(공유)뿐입니다.
    assert harness.calls.count("fetch_my_nickname") == len(KRW_ACCOUNTS) + len(USD_ACCOUNTS)


def test_a_user_in_neither_track_still_sees_the_join_notice():
    with _Harness([], []) as harness:
        harness.run()
    assert any("참여하지 않으셨습니다" in text for text in harness.banners), harness.banners
    assert "fetch_my_consent" not in harness.calls
    assert "fetch_my_consent_usd" not in harness.calls


def test_a_usd_lookup_failure_does_not_swallow_the_krw_screen():
    """한쪽 장애가 다른 쪽을 삼키지 않습니다(트랙 독립 — `/duel` 화면 §5-18 과 같은 규약)."""
    with _Harness(KRW_ACCOUNTS, USD_ACCOUNTS, usd_fails=True) as harness:
        harness.run()

    assert harness.calls.count("fetch_my_consent") == len(KRW_ACCOUNTS), (
        "달러 조회가 실패했다고 원화 동의 카드까지 사라지면 안 됩니다."
    )
    assert any("달러" in text for text in harness.banners), harness.banners


def test_missing_window_on_one_side_is_shown_not_silently_dropped():
    """원화 M1 만 있고 달러 M1 이 없는 상태도 정상 — **조용히 빼지 않습니다**(§0-1)."""
    with _Harness(KRW_ACCOUNTS, [USD_ACCOUNTS[0]]) as harness:
        harness.run()

    # 달러 M3/M6 카드가 없으므로 달러 동의 조회는 1건뿐이어야 합니다.
    assert harness.calls.count("fetch_my_consent_usd") == 1
    assert harness.calls.count("fetch_my_consent") == len(KRW_ACCOUNTS)
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_both_tracks"])
    assert "달러 계좌는 아직 없습니다" in src and "원화 계좌는 아직 없습니다" in src


# =============================================================================
# 6. 🔴 §0-3-8 이중 방어 — 달러 계좌에도 **똑같이** 적용
# =============================================================================
def test_a_usd_account_belonging_to_someone_else_is_not_drawn():
    intruder = [dict(USD_ACCOUNTS[0], user_id="uid-someone-else")]
    with _Harness(KRW_ACCOUNTS, intruder) as harness:
        harness.run()

    assert any("본인 것이 아닌" in text for text in harness.banners), harness.banners
    assert "fetch_my_consent_usd" not in harness.calls, (
        "남의 달러 계좌의 동의 상태를 읽었습니다(§0-3-8 정면 위반)."
    )
    # 원화 화면은 그대로 그려집니다(한쪽 사고가 다른 쪽을 지우지 않게).
    assert harness.calls.count("fetch_my_consent") == len(KRW_ACCOUNTS)


def test_the_owner_check_runs_again_inside_the_usd_card():
    """카드를 그리기 직전에 한 번 더 확인하는 줄이 달러 함수에도 있는지(소스 검사)."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_account_consent_usd"])
    assert 'account.get("user_id") != user_id' in src, (
        "_render_account_consent_usd() 에 소유자 이중 확인이 없습니다(§0-3-8)."
    )


def test_usd_render_functions_take_client_and_user_id_as_arguments():
    """§0-3-8 — "지금 누가 로그인했는지"를 전역에서 추측하지 않습니다."""
    args = [a.arg for a in FUNCTIONS["_render_account_consent_usd"].args.args]
    assert "client" in args and "user_id" in args, args
    for name in ("_render_consent_form_usd", "_render_real_principal_form_usd", "_save_usd"):
        assert "client" in [a.arg for a in FUNCTIONS[name].args.args], name


def test_no_user_data_became_a_module_global():
    """§0-3-8 — 최상위에는 문자열 상수뿐. 이번 라운드가 새 전역을 만들지 않았는지."""
    for node in PAGE_TREE.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assert target.id.isupper() or target.id.startswith("_"), (
                    f"모듈 최상위에 상수가 아닌 이름이 생겼습니다: {target.id}"
                )


# =============================================================================
# 7. 🔴 문구 — 달러 트랙에서 사실인 것만 말합니다 (§0-1)
# =============================================================================
def test_real_principal_notice_for_usd_is_not_a_copy_of_the_krw_one():
    """
    🔴 이 라운드에서 가장 놓치기 쉬웠던 자리입니다. 원화 문구를 그대로 재사용했다면
    달러 사용자에게 "실제 매입원가합계로 체급이 정해진다"고만 말하게 되는데, 실제로는
    `duel_publish_usd.summarize_real_principal_usd()` 가 **달러가 아닌 통화가 하나라도
    있으면 합치지 않고 '구간 미적용'** 으로 보냅니다(정반대 판정).
    """
    usd = consent_page.NOTICE_REAL_PRINCIPAL_USD
    krw = consent_page.NOTICE_REAL_PRINCIPAL
    assert usd != krw, "달러 독립 동의 설명이 원화 문구의 복사본입니다."
    assert "달러 보유분" in usd
    assert duel_rules.BRACKET_NONE_LABEL in usd, "'구간 미적용'으로 간다는 사실을 밝혀야 합니다."
    assert "환율" in usd, "두 통화를 못 합치는 이유(환율 시계열 없음)를 밝혀야 합니다."
    assert "$7,500" in usd or "$750" in usd, "달러 경계값임을 알 수 있어야 합니다."
    # 원화 문구는 한 글자도 바뀌지 않았습니다(회귀).
    assert "실제 매입원가합계로 '체급'(원금 구간)이 정해져" in krw


def test_usd_bracket_boundaries_in_the_notice_match_the_rule_layer():
    """화면에 적은 경계값이 `BRACKET_TIERS_USD` 와 실제로 같은 값인지(§0-3-10)."""
    usd = consent_page.NOTICE_REAL_PRINCIPAL_USD
    lows = {low for _key, _label, low, _high in duel_rules.BRACKET_TIERS_USD if low}
    for low in lows:
        assert f"${low:,}" in usd, f"규칙 계층의 경계 ${low:,} 가 화면 문구에 없습니다."


def test_responsibility_notice_appears_twice_in_the_usd_form_too():
    """5-2-5 — 책임 고지는 **개별 체크박스 영역과 최종 확인 영역** 두 곳(달러도 동일)."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_consent_form_usd"])
    assert src.count("warning_banner(NOTICE_RESPONSIBILITY)") >= 2
    # 문구 자체는 통화 무관이라 **같은 상수를 재사용**합니다(두 벌로 갈리지 않게).
    assert "NOTICE_RESPONSIBILITY_USD" not in PAGE_SRC


def test_revoke_notice_says_the_other_track_is_untouched():
    """
    §0-1 — 한쪽만 철회한 사용자가 "다 지워졌겠지" 하고 오해하면 안 됩니다.
    `revoke_consent_usd()` 는 달러 표만 건드립니다(5-11-10).
    """
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_revoke_usd"])
    assert "원화" in src and "그대로" in src
    assert "revoke_consent_usd" in src and "revoke_consent," not in src


def test_track_independence_is_stated_on_screen():
    notice = consent_page.NOTICE_TRACKS_INDEPENDENT
    assert "완전히 별개" in notice
    assert "3개월" in notice or "차단" in notice
    assert "NOTICE_TRACKS_INDEPENDENT" in ast.get_source_segment(
        PAGE_SRC, FUNCTIONS["_render_both_tracks"])


def test_consent_sentences_are_identical_in_both_tracks():
    """5-2-1 의 다섯 문장은 통화와 무관합니다 — 달러 폼도 **같은 상수**를 씁니다."""
    assert "CONSENT_ITEM_SENTENCES" not in ast.get_source_segment(
        PAGE_SRC, FUNCTIONS["_render_consent_form_usd"]), (
        "달러 폼이 문구 사전을 직접 뒤집니다 — `consent_item_rows()` 를 쓰세요."
    )
    rows = consent_page.consent_item_rows()
    assert [flag for flag, _n, _s in rows] == list(duel_db.CONSENT_ITEM_FLAGS)
    assert "개별 열람" in consent_page.CONSENT_ITEM_SENTENCES["consent_holdings"][1]


# =============================================================================
# 8. 🔴 이벤트 루프 — 달러 DB 호출도 전부 `run_blocking()` 을 거칩니다
# =============================================================================
USD_DB_CALLS = ("fetch_my_accounts_usd", "fetch_my_consent_usd", "save_consent_usd",
                "revoke_consent_usd")


def test_every_usd_db_call_goes_through_run_blocking():
    """
    2026-08-21 사고 — 동기 HTTP 왕복이 이벤트 루프 위에서 돌면 **다른 화면을 보던
    접속자까지** 함께 끊깁니다(`web/blocking.py` 독스트링).
    """
    wrapped = set()
    for node in ast.walk(PAGE_TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "run_blocking" and node.args
                and isinstance(node.args[0], ast.Name)):
            wrapped.add(node.args[0].id)
    for name in USD_DB_CALLS:
        assert name in wrapped, f"{name}() 이 run_blocking() 없이 불립니다."

    # 반대로, 감싸지 않은 **직접 호출**이 하나도 없어야 합니다.
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in USD_DB_CALLS, (
                f"{node.func.id}() 를 이벤트 루프 위에서 직접 부릅니다."
            )


def test_usd_card_and_save_helpers_are_async_where_they_need_to_be():
    assert isinstance(FUNCTIONS["_render_account_consent_usd"], ast.AsyncFunctionDef)
    assert isinstance(FUNCTIONS["_save_usd"], ast.AsyncFunctionDef)
    assert isinstance(FUNCTIONS["_render_both_tracks"], ast.AsyncFunctionDef)


# =============================================================================
# 9. 원화 회귀 — 달러 계좌가 없으면 예전과 같은 경로 (§5-19 최우선 제약)
# =============================================================================
def test_krw_only_path_is_a_separate_branch_that_was_not_rewritten():
    """
    달러 계좌가 없을 때 타는 코드가 예전 그대로인지 — 같은 제목, 같은 안내문, 계좌마다
    한 장씩 도는 같은 렌더 루프. (`/duel` 화면 §5-18 이 쓴 "의도적인 두 경로" 와 같은
    방식입니다.)

    🔴 2026-08-22 — 예전에는 `"await account_section()"` 라는 **루프의 옛 모양 자체**를
       확인했습니다. 그 모양이 바로 늦은 이름 결정 버그(계좌 2개 이상일 때 두 번째 카드의
       저장·철회가 마지막 카드를 다시 그림)의 원인이라, 달러 경로가 이미 쓰던
       `_consent_section()` 팩토리로 바뀌었습니다. 확인하려던 것(= 원화 전용 분기가 살아
       있고, 계좌마다 원화 카드를 한 장씩 그린다)은 그대로 확인합니다.
    """
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_body"])
    assert "#### 계좌마다 따로 정합니다\\n" in src
    assert "계좌마다 서로 다른 무작위 닉네임이 발급되며" in src
    assert "for account in mine:" in src, "계좌마다 한 장씩 도는 루프가 있어야 합니다."
    assert "_consent_section(_render_account_consent, client, user_id, account)()" in src, (
        "원화 전용 경로가 계좌마다 원화 동의 카드를 그리지 않습니다."
    )
    assert "_render_both_tracks" in src, "달러가 있을 때만 새 경로로 갈라져야 합니다."


def test_krw_only_loop_does_not_define_a_refreshable_inside_the_loop():
    """
    🔴 늦은 이름 결정 회귀 방지 — `for` 루프 **안에서** `@ui.refreshable` 을 정의하면
       `.refresh()` 가 마지막 반복의 섹션을 가리킵니다(그래서 계좌 2번 카드의 저장이 3번
       카드를 다시 그렸습니다). 두 트랙 모두 `_consent_section()` 팩토리만 씁니다.
    """
    body = FUNCTIONS["_render_body"]
    for node in ast.walk(body):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {ast.unparse(d) for d in inner.decorator_list}
            assert "ui.refreshable" not in decorators, (
                f"_render_body() 의 루프 안에서 @ui.refreshable 을 직접 정의했습니다"
                f"({inner.name}) — `_consent_section()` 팩토리를 쓰세요."
            )

    # 팩토리 쪽은 루프 밖의 제 함수 안에서 정의합니다(여기가 유일한 실제 정의 자리 —
    # 문자열이 아니라 실제 데코레이터만 셉니다. 주석·독스트링에는 여러 번 나옵니다).
    decorated = [
        node.name
        for node in ast.walk(ast.parse(PAGE_SRC))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(ast.unparse(d) == "ui.refreshable" for d in node.decorator_list)
    ]
    assert decorated == ["section"], (
        f"`@ui.refreshable` 정의 자리는 `_consent_section()` 안의 `section()` 한 곳뿐이어야 "
        f"합니다. 실제: {decorated}"
    )


def test_krw_render_functions_were_not_touched_by_this_round():
    """원화 함수 본문에 달러 이름이 하나도 섞이지 않았는지."""
    for name in ("_render_account_consent", "_render_consent_form",
                 "_render_real_principal_form", "_render_revoke", "_save"):
        used = _names_used(FUNCTIONS[name])
        leaked = {n for n in used if n.endswith("_usd")}
        assert not leaked, f"원화 함수 {name}() 에 달러 이름이 들어왔습니다: {leaked}"


def test_krw_only_screen_still_shows_the_account_level_wording():
    """원화 전용 사용자에게는 새 고지(트랙 독립·닉네임 공유)가 뜨지 않습니다(화면 무변경)."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_body"])
    assert "NOTICE_TRACKS_INDEPENDENT" not in src
    assert "NOTICE_SHARED_NICKNAME" not in src


def test_page_route_is_still_exactly_one_url():
    """새 URL 도, 새 화면 파일도 만들지 않았습니다(§5-19 설계 결정 1번)."""
    routes = [
        deco.args[0].value
        for node in ast.walk(PAGE_TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for deco in node.decorator_list
        if isinstance(deco, ast.Call) and getattr(deco.func, "attr", None) == "page"
        and deco.args and isinstance(deco.args[0], ast.Constant)
    ]
    assert routes == ["/duel/consent"], routes


def test_public_gate_flags_are_shared_by_both_currencies():
    """§5-19 설계 결정 1번 — 통화별 새 플래그를 만들지 않았습니다."""
    assert "DUEL_CONSENT_ENABLED" in PAGE_SRC and "DUEL_CONSENT_MENU_ADMIN_ONLY" in PAGE_SRC
    for forbidden in ("DUEL_CONSENT_USD_ENABLED", "DUEL_USD_CONSENT_ENABLED",
                      "DUEL_CONSENT_ENABLED_USD"):
        assert forbidden not in PAGE_SRC, f"통화별 새 플래그 {forbidden} 가 생겼습니다."
