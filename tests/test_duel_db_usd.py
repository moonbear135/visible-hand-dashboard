# tests/test_duel_db_usd.py
"""
⚔️ "결투다!" USD 트랙 — Supabase 접근 계층(`utils/duel_db_usd.py`) 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · `supabase` 패키지 설치 여부와 무관)

`tests/test_duel_db.py`(원화)와 짝을 이루는 **통화 미러** 검증입니다. 가짜 Supabase
클라이언트는 새로 만들지 않고 그 파일의 `FakeClient`/`sequence`를 그대로 재사용합니다
(`tests/test_duel_publish.py`·`tests/test_duel_batch.py`가 이미 같은 방식을 씁니다 —
흉내도 단일 출처로, §0-3-10).

이 파일이 특히 확인하는 것(원화 검증과 겹치지 않는, USD 트랙만의 위험 지점):
    ① `utils/duel_db_usd.py` 머리말이 선언한 "재사용 vs 신규 정의" 경계가 실제 코드와
       일치하는가 — 공유돼야 할 함수(닉네임 3종·서비스 클라이언트·순수 헬퍼)가 **정말
       같은 객체**인지(재정의해서 두 벌이 되면 나중에 한쪽만 고쳐집니다).
    ② 접수 시간대가 **16:00:01~21:00:00**(KRW 의 18:00:01~22:00:00 이 아님)로 판정되는가.
    ③ 트리거 거절 번역문이 "16:00~21:00"을 말하지, KRW 문구("18:00~22:00")가 새어 들어오지
       않는가(`_translate_order_guard_error_usd` — 이 파일에서 유일하게 "재사용하지 않기로"
       한 함수, 그 이유 자체를 회귀 고정합니다).
    ④ 표 이름·RPC 이름이 KRW 것과 **겹치지 않는가**(`_usd` 접미사가 실제로 붙어 있는가).
    ⑤ 시드($7,500)·정기입금($500) 금액이 `duel_rules` 상수와 일치하는가, 그리고 §0-3-2
       (집합 연산) 회귀가 USD 배치 함수에도 그대로 적용되는가.
    ⑥ 사용자 쓰기 함수의 금지 인자 자가 점검(`user_write_signature_violations_usd`).

실행: pytest tests/test_duel_db_usd.py -v
"""

import ast
import inspect
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
# 가짜 Supabase 클라이언트는 `tests/test_duel_db.py` 가 갖고 있습니다(§0-3-10 — 흉내도
# 단일 출처로). `tests/test_duel_publish.py`/`tests/test_duel_batch.py` 와 같은 관례입니다.
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient, sequence  # noqa: E402
from utils import duel_db, duel_db_usd, duel_rules  # noqa: E402
from utils.duel_db import DuelDbError  # noqa: E402
from utils.duel_rules import KST  # noqa: E402

# ── 시각 고정값 (USD 트랙: 16:00:01~21:00:00, KRW 의 18:00:01~22:00:00 과 다름) ──────────
INSIDE_WINDOW_USD = datetime(2026, 8, 19, 18, 30, 0, tzinfo=KST)    # 접수 시간대 한가운데
OUTSIDE_WINDOW_USD = datetime(2026, 8, 19, 15, 59, 59, tzinfo=KST)  # 창이 열리기 2초 전
TRADING_DAYS = [date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)]


# =============================================================================
# 0. "재사용 vs 신규 정의" 머리말의 약속이 실제 코드와 일치하는지 — 정체성 검사
# =============================================================================
#  `utils/duel_db_usd.py` 머리말은 "이 함수들은 재정의하지 않고 그대로 import 해서
#  씁니다"라고 말합니다. 말로만 하는 약속은 누군가 조용히 `_usd` 쌍둥이를 새로 만들면서
#  깨질 수 있으므로, **같은 객체인지(`is`)**를 직접 대조해 회귀로 고정합니다.
# =============================================================================
@pytest.mark.parametrize("name", [
    "ensure_nickname", "fetch_my_nickname", "fetch_nicknames_for_accounts",
    "create_service_client", "service_config_present",
    "group_rows_by_account", "sum_cash_balance", "cash_balances_by_account",
    "fetch_real_principal_holdings",
    "_execute", "_require_client", "_iso_date", "_now_kst", "_require_text",
    "_require_positive_int", "_require_offset", "_require_amount", "_first_row",
    "_is_duplicate_key_error", "_assert_unique_keys", "_filter_is_null",
    "_filter_not_null", "_assert_no_identity_fields", "_validate_fill_payload",
    "_validate_daily_snapshot", "_validate_holding_snapshot",
])
def test_shared_helpers_are_the_same_object_as_the_krw_file(name):
    """
    🔴 "닉네임은 계좌가 아니라 (user_id, window_type) 로 공유한다"는 5-11-10 확정이,
    코드에서는 "이 파일이 새로 정의하지 않고 그대로 가리킨다"는 사실로 나타납니다.
    누군가 `def fetch_nicknames_for_accounts(...)` 를 이 파일에도 새로 적으면, 그 순간
    두 벌의 닉네임 로직이 생기고 이 테스트가 즉시 잡아냅니다.
    """
    shared = getattr(duel_db, name)
    mirrored = getattr(duel_db_usd, name)
    assert mirrored is shared, f"{name} 이 duel_db 와 같은 객체가 아닙니다(재정의됐을 가능성)"


def test_usd_module_does_not_redefine_the_shared_functions():
    """
    위 정체성 검사를 우회하는 가장 쉬운 방법은 "같은 이름으로 새로 정의하고 import 를
    나중에 덮어쓰는" 실수입니다. AST 로 이 파일 안에 그런 `def` 가 없는지 직접 봅니다.
    """
    source = (REPO_ROOT / "utils" / "duel_db_usd.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    forbidden_redefinitions = {
        "ensure_nickname", "fetch_my_nickname", "fetch_nicknames_for_accounts",
        "create_service_client", "service_config_present",
        "group_rows_by_account", "sum_cash_balance", "cash_balances_by_account",
        "fetch_real_principal_holdings",
    }
    assert not (defined & forbidden_redefinitions), \
        f"공유해야 할 함수를 이 파일이 새로 정의합니다: {defined & forbidden_redefinitions}"


def test_table_names_and_rpc_are_usd_suffixed_and_distinct_from_krw():
    """표 이름·RPC 이름이 KRW 상수와 문자 그대로 겹치지 않는지(복사 실수 방지)."""
    pairs = [
        (duel_db_usd.ACCOUNTS_TABLE_USD, duel_db.ACCOUNTS_TABLE),
        (duel_db_usd.POSITIONS_TABLE_USD, duel_db.POSITIONS_TABLE),
        (duel_db_usd.ORDERS_TABLE_USD, duel_db.ORDERS_TABLE),
        (duel_db_usd.LEDGER_TABLE_USD, duel_db.LEDGER_TABLE),
        (duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, duel_db.DAILY_SNAPSHOTS_TABLE),
        (duel_db_usd.HOLDING_SNAPSHOTS_TABLE_USD, duel_db.HOLDING_SNAPSHOTS_TABLE),
        (duel_db_usd.CONSENT_TABLE_USD, duel_db.CONSENT_TABLE),
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, duel_db.PUBLIC_LEADERBOARD_TABLE),
        (duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, duel_db.PUBLIC_HOLDINGS_TABLE),
        (duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, duel_db.BRACKET_ASSIGNMENTS_TABLE),
        (duel_db_usd.OPT_IN_RPC_USD, duel_db.OPT_IN_RPC),
    ]
    for usd_value, krw_value in pairs:
        assert usd_value != krw_value, f"USD 표/RPC 이름이 KRW 와 같습니다: {usd_value}"
        assert usd_value.endswith("_usd"), f"USD 이름에 _usd 접미사가 없습니다: {usd_value}"


def test_nicknames_table_is_not_redefined_here():
    """`duel_nicknames` 표 이름 상수는 이 파일에 **아예 없어야** 합니다(공유 표 — 위 머리말)."""
    source = (REPO_ROOT / "utils" / "duel_db_usd.py").read_text(encoding="utf-8")
    assert "NICKNAMES_TABLE_USD" not in source
    assert '"duel_nicknames_usd"' not in source


# =============================================================================
# 1. A 절 — 모듈 참여(옵트인) RPC — `duel_opt_in_usd()`
# =============================================================================
def _opt_in_rows_usd(user_id="user-1", anchor="2026-08-20"):
    return [{"id": f"acc-{index}", "user_id": user_id, "window_type": window,
             "seed_amount": duel_rules.SEED_AMOUNT_USD, "currency": "USD",
             "anchor_date": anchor, "status": "active"}
            for index, window in enumerate(("M1", "M3", "M6"), start=1)]


def test_opt_in_usd_calls_the_usd_rpc_once_and_returns_three_accounts():
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): _opt_in_rows_usd()})
    accounts = duel_db_usd.opt_in_usd(client)

    call = client.only_call(duel_db_usd.OPT_IN_RPC_USD, "rpc")
    assert call.table == "duel_opt_in_usd"
    assert len(client.calls) == 1
    assert [row["window_type"] for row in accounts] == ["M1", "M3", "M6"]
    assert all(row["seed_amount"] == duel_rules.SEED_AMOUNT_USD for row in accounts)
    assert all(row["currency"] == "USD" for row in accounts)


def test_opt_in_usd_sends_no_arguments_at_all():
    """KRW 와 같은 안전성 근거 — 인자가 하나도 없습니다."""
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): _opt_in_rows_usd()})
    duel_db_usd.opt_in_usd(client)
    payload = client.only_call(duel_db_usd.OPT_IN_RPC_USD, "rpc").payload
    assert payload in ({}, None)
    assert list(inspect.signature(duel_db_usd.opt_in_usd).parameters) == ["client"]


def test_opt_in_usd_never_writes_to_any_table_directly():
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): _opt_in_rows_usd()})
    duel_db_usd.opt_in_usd(client)
    for forbidden in (duel_db_usd.LEDGER_TABLE_USD, duel_db_usd.ACCOUNTS_TABLE_USD):
        assert client.calls_for(forbidden) == []


def test_opt_in_usd_empty_response_is_not_a_silent_success():
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.opt_in_usd(client)
    assert "M1" in str(excinfo.value) and "M3" in str(excinfo.value)


def test_opt_in_usd_partial_response_is_rejected():
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): _opt_in_rows_usd()[:2]})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.opt_in_usd(client)
    assert "M6" in str(excinfo.value)


def test_opt_in_usd_orders_the_rows_even_if_the_server_shuffles_them():
    shuffled = list(reversed(_opt_in_rows_usd()))
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): shuffled})
    assert [row["window_type"] for row in duel_db_usd.opt_in_usd(client)] == ["M1", "M3", "M6"]


def test_opt_in_usd_translates_the_login_rejection_via_the_shared_translator():
    """
    오류 번역은 `duel_db._translate_opt_in_error()` 를 **그대로** 씁니다(통화와 무관한 순수
    로직이므로). 여기서는 그 재사용이 실제로 동작하는지(문구가 KRW 처럼 사람이 읽게
    바뀌는지)를 통합적으로 확인합니다.
    """
    rejection = Exception(
        "duel_opt_in_usd: 로그인한 사용자만 결투 모듈에 참여할 수 있습니다"
        "(요청에 로그인 세션이 없습니다). SQLSTATE 28000"
    )
    client = FakeClient(responses={(duel_db_usd.OPT_IN_RPC_USD, "rpc"): rejection})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.opt_in_usd(client)
    message = str(excinfo.value)
    assert "로그인" in message
    assert "SQLSTATE" not in message


def test_sql_opt_in_usd_function_is_security_definer_and_argument_free():
    """`duel_opt_in_usd()` SQL 함수도 KRW 와 같은 안전 조건 4가지를 갖는지(회귀 고정)."""
    executable = "\n".join(
        line for line in (REPO_ROOT / "sql" / "duel_schema.sql").read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    start = executable.index("create function public.duel_opt_in_usd()")
    end_marker = "comment on function public.duel_opt_in_usd()"
    assert end_marker in executable, "duel_opt_in_usd() 함수에 comment 가 없습니다"
    body = executable[start:executable.index(end_marker)]

    assert "security definer" in body
    assert "set search_path = public" in body
    assert "auth.uid()" in body
    assert "duel_opt_in_usd(p_" not in executable and "duel_opt_in_usd(user" not in executable
    assert "on conflict (user_id, window_type) do nothing" in body
    assert "on conflict (account_id) where event_type = 'seed' do nothing" in body


# =============================================================================
# 2. A 절 — 주문 저장·수정·취소 — USD 접수 시간대(16:00:01~21:00:00)
# =============================================================================
def test_save_order_usd_inside_window_writes_pending_order_to_the_usd_table():
    client = FakeClient()
    order = duel_db_usd.save_order_usd(
        client, "acc-1", "AAPL", "애플", 10,
        trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW_USD,
    )
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "insert")
    payload = call.rows[0]
    assert payload["ticker"] == "AAPL"
    assert payload["status"] == "pending"
    # 🔴 저장일(8/19) 자신이 확정 거래일 목록에 있으므로 **그날 자신**이 체결 거래일입니다.
    #    USD 접수 시간대(16:00:01~21:00:00 KST = 03:00~08:00 ET)는 그날 미국장이 열리기도
    #    전이라 그날 마감가가 아직 존재하지 않기 때문입니다. 원화용
    #    `resolve_fill_trading_day()`(그날 자신을 무조건 제외)를 쓰면 여기가 "2026-08-20"
    #    으로 하루 밀립니다 — 실제로 있었던 버그입니다(work order §5-16).
    assert payload["target_date"] == "2026-08-19"
    assert order["ticker"] == "AAPL"
    # KRW 표에는 아무 것도 가지 않습니다(트랙이 완전히 분리돼 있습니다).
    assert client.calls_for(duel_db.ORDERS_TABLE) == []


def test_save_order_usd_outside_window_is_rejected_with_the_usd_time_range():
    """
    🔴 이 테스트가 실패하면 USD 사용자가 KRW 시간대(18:00:01~22:00:00) 안내를 보게 됩니다
    — 실제로 일어난 적 있는 종류의 실수(오너가 두 번 시행착오를 거친 지점)라 문구를
    그대로 대조합니다.
    """
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.save_order_usd(client, "acc-1", "AAPL", "애플", 10,
                                   trading_days=TRADING_DAYS, now_kst=OUTSIDE_WINDOW_USD)
    message = str(excinfo.value)
    assert "16:00:01" in message and "21:00:00" in message
    assert "18:00" not in message and "22:00" not in message
    assert client.calls == []


def test_save_order_usd_window_boundaries_match_the_usd_rule():
    """경계(16:00:00 닫힘 / 16:00:01 열림 / 21:00:00 열림 / 21:00:01 닫힘)."""
    cases = {
        datetime(2026, 8, 19, 16, 0, 0, tzinfo=KST): False,
        datetime(2026, 8, 19, 16, 0, 1, tzinfo=KST): True,
        datetime(2026, 8, 19, 21, 0, 0, tzinfo=KST): True,
        datetime(2026, 8, 19, 21, 0, 1, tzinfo=KST): False,
    }
    for moment, should_pass in cases.items():
        client = FakeClient()
        if should_pass:
            duel_db_usd.save_order_usd(client, "acc-1", "AAPL", "애플", 1,
                                       trading_days=TRADING_DAYS, now_kst=moment)
            assert len(client.calls) == 1, moment
        else:
            with pytest.raises(DuelDbError):
                duel_db_usd.save_order_usd(client, "acc-1", "AAPL", "애플", 1,
                                           trading_days=TRADING_DAYS, now_kst=moment)
            assert client.calls == [], moment


def test_save_order_usd_rejects_ticker_outside_universe_with_us_stock_wording():
    """유니버스 거절 문구가 "미국 주식"을 가리켜야 합니다(KRW 는 "코스피 상위")."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.save_order_usd(client, "acc-1", "ZZZZ", "없는종목", 1,
                                   trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW_USD,
                                   universe_tickers={"AAPL", "MSFT"})
    message = str(excinfo.value)
    assert "미국 주식" in message
    assert "코스피" not in message
    assert client.calls == []


@pytest.mark.parametrize("bad_quantity", [0, -1, 2.5, "세 주", None, True])
def test_save_order_usd_rejects_bad_quantity(bad_quantity):
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.save_order_usd(client, "acc-1", "AAPL", "애플", bad_quantity,
                                   trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW_USD)
    assert client.calls == []


def test_save_order_usd_requires_confirmed_trading_days():
    client = FakeClient()
    with pytest.raises((DuelDbError, duel_rules.DuelRuleError)):
        duel_db_usd.save_order_usd(client, "acc-1", "AAPL", "애플", 1,
                                   trading_days=None, now_kst=INSIDE_WINDOW_USD)
    assert client.calls == []


def test_edit_order_usd_updates_quantity_only_on_the_usd_table():
    client = FakeClient()
    duel_db_usd.edit_order_usd(client, "order-1", 7, now_kst=INSIDE_WINDOW_USD)
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update")
    assert call.filter_map == {"id": "order-1"}
    assert call.payload["requested_quantity"] == 7


def test_edit_and_cancel_order_usd_are_blocked_outside_the_usd_window():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.edit_order_usd(client, "order-1", 7, now_kst=OUTSIDE_WINDOW_USD)
    with pytest.raises(DuelDbError):
        duel_db_usd.cancel_order_usd(client, "order-1", now_kst=OUTSIDE_WINDOW_USD)
    assert client.calls == []


def test_edit_order_usd_translates_db_trigger_rejection_with_usd_time_range():
    """
    🔴 이 파일이 `_translate_order_guard_error()`(KRW) 를 재사용하지 **않기로** 한
    이유 자체를 회귀 고정합니다: 그대로 재사용했다면 여기서 "18:00~22:00"이 나왔을
    것입니다.
    """
    trigger_error = Exception(
        'duel_orders_usd: 이미 filled(으)로 종결된 주문은 수정할 수 없습니다(배치 처리 이후 변경 금지)'
    )
    client = FakeClient(responses={(duel_db_usd.ORDERS_TABLE_USD, "update"): trigger_error})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.edit_order_usd(client, "order-1", 7, now_kst=INSIDE_WINDOW_USD)
    message = str(excinfo.value)
    assert "이미 처리가 끝난 주문" in message
    assert "16:00~21:00" in message
    assert "18:00~22:00" not in message
    assert "duel_orders_usd:" not in message


def test_cancel_order_usd_keeps_the_row_with_a_reason():
    client = FakeClient()
    assert duel_db_usd.cancel_order_usd(client, "order-1", now_kst=INSIDE_WINDOW_USD) is None
    assert client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "delete") == []
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update")
    assert call.payload["status"] == "cancelled"
    assert call.payload["fail_reason"].strip()


def test_cancel_order_usd_accepts_custom_reason():
    client = FakeClient()
    duel_db_usd.cancel_order_usd(client, "order-1", reason="종목을 잘못 골랐습니다",
                                 now_kst=INSIDE_WINDOW_USD)
    assert client.calls[0].payload["fail_reason"] == "종목을 잘못 골랐습니다"


# =============================================================================
# 3. A 절 — 조회가 맞는 (USD) 표·맞는 필터로 가는지
# =============================================================================
def test_fetch_my_accounts_usd_filters_by_user_on_the_usd_table():
    client = FakeClient(responses={(duel_db_usd.ACCOUNTS_TABLE_USD, "select"): [{"id": "acc-1"}]})
    rows = duel_db_usd.fetch_my_accounts_usd(client, "user-1")
    call = client.only_call(duel_db_usd.ACCOUNTS_TABLE_USD, "select")
    assert call.filter_map == {"user_id": "user-1"}
    assert rows == [{"id": "acc-1"}]


def test_fetch_my_positions_orders_ledger_and_snapshots_usd_filter_by_account():
    client = FakeClient()
    duel_db_usd.fetch_my_positions_usd(client, "acc-1")
    duel_db_usd.fetch_my_orders_usd(client, "acc-1")
    duel_db_usd.fetch_my_cash_ledger_usd(client, "acc-1")
    duel_db_usd.fetch_my_snapshots_usd(client, "acc-1")
    duel_db_usd.fetch_my_holding_snapshots_usd(client, "acc-1")
    assert client.only_call(duel_db_usd.POSITIONS_TABLE_USD, "select").filter_map == {"account_id": "acc-1"}
    orders = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "select")
    assert orders.filter_map == {"account_id": "acc-1"}
    assert orders.orders == [("saved_at", True)]
    assert client.only_call(duel_db_usd.LEDGER_TABLE_USD, "select").filter_map == {"account_id": "acc-1"}
    assert client.only_call(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select").filter_map == {"account_id": "acc-1"}
    assert client.only_call(duel_db_usd.HOLDING_SNAPSHOTS_TABLE_USD, "select").filter_map == {"account_id": "acc-1"}


def test_fetch_my_snapshots_usd_applies_date_range():
    client = FakeClient()
    duel_db_usd.fetch_my_snapshots_usd(client, "acc-1",
                                       start_date=date(2026, 8, 1), end_date="2026-08-19")
    call = client.only_call(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select")
    assert ("gte", "snapshot_date", "2026-08-01") in call.filters
    assert ("lte", "snapshot_date", "2026-08-19") in call.filters
    assert call.orders == [("snapshot_date", False)]


def test_fetch_my_snapshots_usd_output_feeds_compute_twr_directly():
    """USD 스냅샷 조회 결과도 (통화 무관한) `duel_rules.compute_twr()` 에 그대로 먹입니다."""
    rows = [
        {"snapshot_date": "2026-08-17", "total_value": 7_500.0, "cash_flow_amount": 0},
        {"snapshot_date": "2026-08-18", "total_value": 7_575.0, "cash_flow_amount": 0},
    ]
    client = FakeClient(responses={(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select"): rows})
    fetched = duel_db_usd.fetch_my_snapshots_usd(client, "acc-1")
    result = duel_rules.compute_twr(fetched)
    assert result["status"] == "OK"
    assert result["twr_pct"] == pytest.approx(1.0, abs=1e-9)


# =============================================================================
# 4. A 절 — 사용자가 할 수 **없는** 일은 코드 경로 자체가 없어야 합니다 (USD 미러)
# =============================================================================
def test_usd_user_write_functions_do_not_accept_fill_or_balance_params():
    assert duel_db_usd.user_write_signature_violations_usd() == []
    assert set(duel_db_usd.USER_WRITE_FUNCTIONS_USD) == {
        "opt_in_usd", "save_order_usd", "edit_order_usd", "cancel_order_usd", "save_consent_usd"}


def _usd_module_ast():
    source = (REPO_ROOT / "utils" / "duel_db_usd.py").read_text(encoding="utf-8")
    return ast.parse(source), source


def _write_targets(function_node):
    """`utils/duel_db.py` 테스트와 같은 AST 도우미 — 어느 표에 쓰는지 모읍니다."""
    targets = set()
    for node in ast.walk(function_node):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("insert", "update", "upsert", "delete"):
            continue
        cursor = node.func.value
        while isinstance(cursor, ast.Call) and isinstance(cursor.func, ast.Attribute):
            if cursor.func.attr == "table" and cursor.args:
                argument = cursor.args[0]
                targets.add(argument.id if isinstance(argument, ast.Name)
                            else ast.dump(argument))
                break
            cursor = cursor.func.value
    return targets


def test_usd_user_facing_functions_only_write_orders_and_consent():
    """스키마 §14 가 사용자에게 준 표는 `duel_orders_usd`/`duel_public_consent_usd` 뿐입니다."""
    tree, source = _usd_module_ast()
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for name in duel_db_usd.USER_WRITE_FUNCTIONS_USD:
        targets = _write_targets(functions[name])
        assert targets <= {"ORDERS_TABLE_USD", "CONSENT_TABLE_USD"}, \
            f"{name} 이 사용자 권한 밖의 USD 표에 씁니다: {targets}"


def test_usd_user_facing_section_does_not_touch_service_role():
    """A 절 본문에 service_role 관련 이름이 등장하지 않는지(격리 회귀 고정, KRW 와 동일)."""
    _tree, source = _usd_module_ast()
    start = source.index("#  A 절 —")
    end = source.index("#  B 절 —")
    section = source[start:end]
    for forbidden in ("service_role", "SERVICE_ROLE_KEY_ENV", "create_service_client"):
        assert forbidden not in section, f"A 절에 {forbidden} 이 있습니다"


def test_opt_in_usd_does_not_reach_for_the_batch_key():
    tree, source = _usd_module_ast()
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    node = functions["opt_in_usd"]
    body = ast.get_source_segment(source, node)
    for forbidden in ("service_role", "SERVICE_ROLE_KEY_ENV", "create_service_client",
                      "_read_service_env", "os.environ", "getenv"):
        assert forbidden not in body, f"opt_in_usd 이 {forbidden} 을(를) 건드립니다"
    assert _write_targets(node) == set(), "opt_in_usd 이 표에 직접 씁니다"

    rpc_calls = [child for child in ast.walk(node)
                 if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                 and child.func.attr == "rpc"]
    assert len(rpc_calls) == 1
    assert isinstance(rpc_calls[0].args[0], ast.Name) and rpc_calls[0].args[0].id == "OPT_IN_RPC_USD"


def test_usd_publish_tables_are_only_written_by_the_batch_section():
    """A 절이 USD 발행표에 쓰지 않고, 체급 배정표도 건드리지 않는지(KRW 와 같은 불변식)."""
    tree, source = _usd_module_ast()
    a_start = source.index("#  A 절 —")
    b_start = source.index("#  B 절 —")
    a_section = source[a_start:b_start]

    for table in ("duel_bracket_assignments_usd", "BRACKET_ASSIGNMENTS_TABLE_USD"):
        assert table not in a_section, f"A 절이 발행 인프라({table})를 건드립니다"

    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for name, node in functions.items():
        marker = f"def {name}("
        if not (a_start <= source.index(marker) < b_start):
            continue
        targets = _write_targets(node)
        assert not ({"PUBLIC_LEADERBOARD_TABLE_USD", "PUBLIC_HOLDINGS_TABLE_USD",
                     "BRACKET_ASSIGNMENTS_TABLE_USD"} & targets), \
            f"A 절 함수 {name} 이 발행표에 씁니다: {targets}"


# =============================================================================
# 5. A 절 — 공개 동의 (USD, `duel_public_consent_usd`)
# =============================================================================
def test_save_consent_usd_rejects_final_confirm_without_all_five():
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.save_consent_usd(client, "acc-1", consent_rank=True, consent_return=True,
                                     consent_holdings=True, consent_quantity=True,
                                     consent_buy_amount=False, final_confirmed=True)
    assert "consent_buy_amount" in str(excinfo.value)
    assert client.calls == []


def test_save_consent_usd_final_confirm_records_time_on_the_usd_table():
    client = FakeClient()
    duel_db_usd.save_consent_usd(client, "acc-1", consent_rank=True, consent_return=True,
                                 consent_holdings=True, consent_quantity=True,
                                 consent_buy_amount=True, final_confirmed=True)
    call = client.only_call(duel_db_usd.CONSENT_TABLE_USD, "upsert")
    assert call.options["on_conflict"] == "account_id"
    assert call.payload["final_confirmed"] is True
    assert call.payload["final_confirmed_at"]
    assert client.calls_for(duel_db.CONSENT_TABLE) == [], "KRW 동의표에는 손대지 않습니다"


def test_real_principal_consent_usd_is_independent_of_the_five():
    client = FakeClient()
    duel_db_usd.save_consent_usd(client, "acc-1", consent_real_principal_bracket=True)
    payload = client.only_call(duel_db_usd.CONSENT_TABLE_USD, "upsert").payload
    assert payload["consent_real_principal_bracket"] is True
    for flag in duel_db.CONSENT_ITEM_FLAGS:
        assert flag not in payload


def test_save_consent_usd_rejects_unknown_flag():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.save_consent_usd(client, "acc-1", consent_rankk=True)
    assert client.calls == []


def test_revoke_consent_usd_is_independent_of_krw_consent():
    """
    🔴 5-11-10 확정 — USD 철회는 KRW 동의에 **아무 영향이 없습니다**. 여기서는 그 독립성을
    "KRW 표에 질의가 전혀 가지 않는다"는 사실로 고정합니다.
    """
    existing = {"account_id": "acc-1", "revoked_at": None}
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): [existing]})
    duel_db_usd.revoke_consent_usd(client, "acc-1")
    call = client.only_call(duel_db_usd.CONSENT_TABLE_USD, "update")
    assert call.payload["revoked_at"]
    assert all(call.payload[flag] is False for flag in duel_db.CONSENT_ITEM_FLAGS)
    assert client.calls_for(duel_db.CONSENT_TABLE) == []


def test_revoke_consent_usd_without_existing_consent_is_rejected():
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): []})
    with pytest.raises(DuelDbError):
        duel_db_usd.revoke_consent_usd(client, "acc-1")


def test_revoke_consent_usd_called_twice_is_idempotent():
    already_revoked = {"account_id": "acc-1", "revoked_at": "2026-08-01T00:00:00+09:00"}
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): [already_revoked]})
    result = duel_db_usd.revoke_consent_usd(client, "acc-1")
    assert result == already_revoked
    assert client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "update") == []


def test_reconsent_block_usd_blocks_within_three_months():
    """
    재동의 차단은 `duel_rules.resolve_reconsent_block()`(순수 함수, 공유)이 판정합니다.
    `_assert_reconsent_allowed_usd()` 는 `save_consent_usd()` 가 저장 직전에 부르는 내부
    헬퍼라 여기서 직접 불러 시각을 고정합니다(공개 인터페이스인 `save_consent_usd()` 는
    `now_kst` 를 받지 않습니다 — KRW 의 `save_consent()` 와 동일한 규약).
    """
    revoked = {"account_id": "acc-1", "revoked_at": "2026-08-01T00:00:00+09:00"}
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): [revoked]})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd._assert_reconsent_allowed_usd(
            client, "acc-1", now_kst=datetime(2026, 8, 20, tzinfo=KST))
    assert "3개월" in str(excinfo.value)


# =============================================================================
# 6. A 절 — 발행표 읽기 전용 조회 (USD)
# =============================================================================
def test_fetch_public_leaderboard_usd_uses_the_shared_column_list():
    """컬럼 목록은 `duel_db.PUBLIC_LEADERBOARD_COLUMNS` 를 그대로 재사용합니다(새로 안 적음)."""
    client = FakeClient(responses={(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): []})
    duel_db_usd.fetch_public_leaderboard_usd(client, window_type="M1", bracket_key="usd_under_750")
    call = client.only_call(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select")
    assert call.options["columns"] == duel_db.PUBLIC_LEADERBOARD_COLUMNS


def test_fetch_public_leaderboard_latest_date_usd_filters_by_window_and_bracket():
    client = FakeClient(responses={
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): [{"published_date": "2026-08-19"}],
    })
    result = duel_db_usd.fetch_public_leaderboard_latest_date_usd(
        client, window_type="M1", bracket_key="usd_under_750")
    assert result == "2026-08-19"
    call = client.only_call(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select")
    assert call.filter_map == {"window_type": "M1", "bracket_key": "usd_under_750"}


def test_fetch_public_holdings_for_nickname_usd_uses_the_shared_column_list():
    client = FakeClient(responses={(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "select"): []})
    duel_db_usd.fetch_public_holdings_for_nickname_usd(client, "떠난사람0009")
    call = client.only_call(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "select")
    assert call.options["columns"] == duel_db.PUBLIC_HOLDINGS_COLUMNS
    assert call.filter_map == {"nickname": "떠난사람0009"}


# =============================================================================
# 7. B 절 — 옵트인 백필(관리 전용) 멱등성 — 시드 $7,500
# =============================================================================
def _accounts_usd(user_id="user-1"):
    return [{"id": f"acc-{index}", "user_id": user_id, "window_type": window}
            for index, window in enumerate(("M1", "M3", "M6"), start=1)]


def test_create_duel_accounts_for_user_usd_creates_three_accounts_with_the_usd_seed():
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): sequence([], _accounts_usd()),
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [],
    })
    accounts = duel_db_usd.create_duel_accounts_for_user_usd(client, "user-1",
                                                             anchor_date=date(2026, 8, 19))
    assert [row["window_type"] for row in accounts] == ["M1", "M3", "M6"]

    account_insert = client.only_call(duel_db_usd.ACCOUNTS_TABLE_USD, "insert")
    assert len(account_insert.rows) == 3
    assert all(row["seed_amount"] == duel_rules.SEED_AMOUNT_USD == 7_500
               for row in account_insert.rows)
    assert all(row["currency"] == "USD" for row in account_insert.rows)

    seed_insert = client.only_call(duel_db_usd.LEDGER_TABLE_USD, "insert")
    assert len(seed_insert.rows) == 3
    assert all(row["amount"] == 7_500 for row in seed_insert.rows)


def test_create_duel_accounts_for_user_usd_is_idempotent_on_second_call():
    existing = _accounts_usd()
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): existing,
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [{"account_id": row["id"]} for row in existing],
    })
    accounts = duel_db_usd.create_duel_accounts_for_user_usd(client, "user-1",
                                                             anchor_date=date(2026, 8, 19))
    assert len(accounts) == 3
    assert client.calls_for(duel_db_usd.ACCOUNTS_TABLE_USD, "insert") == []
    assert client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert") == []


def test_create_duel_accounts_for_user_usd_survives_unique_conflict():
    conflict = Exception(
        'duplicate key value violates unique constraint "duel_accounts_usd_user_window_unique"')
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): sequence([], _accounts_usd()),
        (duel_db_usd.ACCOUNTS_TABLE_USD, "insert"): conflict,
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [{"account_id": "acc-1"},
                                                   {"account_id": "acc-2"},
                                                   {"account_id": "acc-3"}],
    })
    accounts = duel_db_usd.create_duel_accounts_for_user_usd(client, "user-1",
                                                             anchor_date=date(2026, 8, 19))
    assert len(accounts) == 3
    assert client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert") == []


def test_create_duel_accounts_for_user_usd_reraises_unrelated_errors():
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): sequence([], []),
        (duel_db_usd.ACCOUNTS_TABLE_USD, "insert"): Exception("connection reset by peer"),
    })
    with pytest.raises(DuelDbError):
        duel_db_usd.create_duel_accounts_for_user_usd(client, "user-1",
                                                       anchor_date=date(2026, 8, 19))


# =============================================================================
# 8. B 절 — 정기 입금 ($500) · §0-3-2 집합 연산 회귀 고정
# =============================================================================
def _active_accounts_usd(count):
    return [{"id": f"acc-{index}", "user_id": f"user-{index}", "window_type": "M1",
             "status": "active"} for index in range(count)]


@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_apply_monthly_deposits_usd_is_one_insert_regardless_of_account_count(account_count):
    """🔴 §0-3-2 회귀 — USD 배치도 KRW 와 같은 집합 연산 규율을 지킵니다."""
    accounts = _active_accounts_usd(account_count)
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): accounts,
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [],
    })
    inserted = duel_db_usd.apply_monthly_deposits_usd(client, date(2026, 9, 10))

    assert inserted == account_count
    assert len(client.calls_for(duel_db_usd.ACCOUNTS_TABLE_USD, "select")) == 1
    assert len(client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "select")) == 1
    expected_chunks = -(-account_count // duel_db_usd.CHUNK_SIZE)
    inserts = client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert")
    assert len(inserts) == expected_chunks
    assert sum(len(call.rows) for call in inserts) == account_count
    assert len(client.calls) == 2 + expected_chunks


def test_apply_monthly_deposits_usd_payload_matches_the_500_dollar_constant():
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): _active_accounts_usd(3),
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [],
    })
    duel_db_usd.apply_monthly_deposits_usd(client, "2026-09-10")
    rows = client.only_call(duel_db_usd.LEDGER_TABLE_USD, "insert").rows
    assert all(row["amount"] == duel_rules.MONTHLY_DEPOSIT_USD == 500 for row in rows)
    assert all(row["event_type"] == "monthly_deposit" for row in rows)


def test_apply_monthly_deposits_usd_second_run_inserts_nothing():
    accounts = _active_accounts_usd(3)
    client = FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): accounts,
        (duel_db_usd.LEDGER_TABLE_USD, "select"): [{"account_id": row["id"]} for row in accounts],
    })
    assert duel_db_usd.apply_monthly_deposits_usd(client, date(2026, 9, 10)) == 0
    assert client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert") == []


def test_apply_monthly_deposits_usd_with_no_accounts_sends_no_write():
    client = FakeClient(responses={(duel_db_usd.ACCOUNTS_TABLE_USD, "select"): []})
    assert duel_db_usd.apply_monthly_deposits_usd(client, date(2026, 9, 10)) == 0
    assert client.calls_for(duel_db_usd.LEDGER_TABLE_USD) == []


# =============================================================================
# 9. B 절 — 체결
# =============================================================================
def test_fetch_pending_orders_for_fill_usd_is_one_query_ordered_by_saved_at():
    client = FakeClient(responses={(duel_db_usd.ORDERS_TABLE_USD, "select"): [{"id": "o1"}]})
    duel_db_usd.fetch_pending_orders_for_fill_usd(client, date(2026, 8, 20))
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "select")
    assert call.filter_map == {"status": "pending", "target_date": "2026-08-20"}
    assert call.orders == [("saved_at", False)]
    assert len(client.calls) == 1


def test_record_order_fill_usd_persists_exactly_what_the_shared_rules_computed():
    """체결 계산은 (공유) `duel_rules.calculate_fill()` 이 하고, 이 파일은 결과만 적습니다."""
    outcome = duel_rules.calculate_fill(10, 200, 1_000)   # 5주만 체결
    assert outcome["status"] == "partially_filled" and outcome["filled_quantity"] == 5

    client = FakeClient()
    duel_db_usd.record_order_fill_usd(
        client, "order-1", outcome["status"], outcome["filled_quantity"],
        200, outcome["filled_amount"], outcome["fail_reason"],
        filled_date=date(2026, 8, 20),
    )
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update")
    assert call.payload["status"] == "partially_filled"
    assert call.payload["filled_quantity"] == 5
    assert call.payload["filled_amount"] == outcome["filled_amount"]
    assert call.filter_map == {"id": "order-1", "status": "pending"}


def test_record_order_fills_usd_writes_empty_fill_fields_for_expired_orders():
    client = FakeClient()
    duel_db_usd.record_order_fills_usd(client, [{
        "id": "order-1", "status": "expired", "filled_quantity": 0,
        "filled_price": 200, "filled_amount": 0,
        "fail_reason": "예수금이 부족해 1주도 체결되지 않았습니다.",
        "filled_date": date(2026, 8, 20),
    }])
    payload = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update").payload
    assert payload["filled_quantity"] is None
    assert payload["filled_price"] is None
    assert payload["filled_amount"] is None
    assert payload["filled_date"] is None


def test_record_order_fills_usd_with_empty_list_writes_nothing():
    client = FakeClient()
    assert duel_db_usd.record_order_fills_usd(client, []) == 0
    assert client.calls == []


def test_record_buy_ledger_entry_usd_flips_the_sign_once():
    client = FakeClient()
    duel_db_usd.record_buy_ledger_entry_usd(client, "acc-1", "order-1", 490, date(2026, 8, 20))
    row = client.only_call(duel_db_usd.LEDGER_TABLE_USD, "insert").rows[0]
    assert row["amount"] == -490
    assert row["event_type"] == "buy"
    assert row["order_id"] == "order-1"


def test_record_buy_ledger_entries_usd_is_a_single_insert():
    client = FakeClient()
    entries = [{"account_id": f"acc-{i}", "order_id": f"o-{i}",
                "filled_amount": 10 * (i + 1), "event_date": date(2026, 8, 20)}
               for i in range(25)]
    assert duel_db_usd.record_buy_ledger_entries_usd(client, entries) == 25
    assert len(client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert")) == 1


def test_record_buy_ledger_entry_usd_rejects_zero_amount():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.record_buy_ledger_entry_usd(client, "acc-1", "order-1", 0, date(2026, 8, 20))
    assert client.calls == []


def test_upsert_position_weighted_average_usd_uses_the_shared_rules_function():
    """평단가는 (공유) `duel_rules.apply_buy_fill_to_position()` 이 계산합니다."""
    existing = {"quantity": 10, "avg_cost": 100}
    expected = duel_rules.apply_buy_fill_to_position(10, 100, 5, 200)

    client = FakeClient()
    duel_db_usd.upsert_position_weighted_average_usd(
        client, "acc-1", "AAPL", "애플", existing, 5, 200)
    call = client.only_call(duel_db_usd.POSITIONS_TABLE_USD, "upsert")
    assert call.options["on_conflict"] == "account_id,ticker"
    row = call.rows[0]
    assert row["quantity"] == expected["quantity"] == 15
    assert row["avg_cost"] == expected["avg_cost"]


def test_upsert_positions_usd_rejects_duplicate_conflict_keys():
    client = FakeClient()
    rows = [{"account_id": "acc-1", "ticker": "AAPL", "quantity": 1, "avg_cost": 1},
            {"account_id": "acc-1", "ticker": "AAPL", "quantity": 2, "avg_cost": 2}]
    with pytest.raises(DuelDbError):
        duel_db_usd.upsert_positions_usd(client, rows)
    assert client.calls == []


def test_upsert_positions_usd_is_one_call_for_many_rows():
    client = FakeClient()
    rows = [{"account_id": f"acc-{i}", "ticker": "AAPL", "quantity": 1, "avg_cost": 1}
            for i in range(30)]
    duel_db_usd.upsert_positions_usd(client, rows)
    assert len(client.calls_for(duel_db_usd.POSITIONS_TABLE_USD, "upsert")) == 1


# =============================================================================
# 10. B 절 — 체결 불가일 일괄 정리 (§0-3-2 회귀)
# =============================================================================
def test_expire_or_cancel_all_pending_for_date_usd_is_one_set_based_update():
    affected = [{"id": f"o-{i}"} for i in range(37)]
    client = FakeClient(responses={(duel_db_usd.ORDERS_TABLE_USD, "update"): affected})
    reason = "그 거래일의 미국 정규장 마감가 수집이 실패해 체결하지 않고 취소했습니다."

    count = duel_db_usd.expire_or_cancel_all_pending_for_date_usd(
        client, date(2026, 8, 20), reason)

    assert count == 37
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update")
    assert call.filter_map == {"status": "pending", "target_date": "2026-08-20"}
    assert call.payload == {"status": "cancelled", "fail_reason": reason}
    assert len(client.calls) == 1


def test_expire_or_cancel_all_pending_for_date_usd_requires_a_reason():
    client = FakeClient()
    for bad_reason in ("", "   ", None):
        with pytest.raises(DuelDbError):
            duel_db_usd.expire_or_cancel_all_pending_for_date_usd(
                client, date(2026, 8, 20), bad_reason)
    assert client.calls == []


# =============================================================================
# 11. B 절 — 일별 스냅샷 적재 (검증 헬퍼는 KRW 파일에서 재사용)
# =============================================================================
def _snapshot_row_usd(account_id="acc-1", **overrides):
    row = {
        "account_id": account_id,
        "position_value": 3_000.0,
        "cash_balance": 4_500.0,
        "total_value": 7_500.0,
        "total_cost": 2_800.0,
        "cash_flow_amount": 0.0,
        "cash_flow_kind": None,
        "priced_count": 1,
        "unpriced_count": 0,
        "price_as_of_kst": "2026-08-20 07:05",
        "holdings": [{
            "ticker": "AAPL", "stock_name": "애플", "quantity": 20, "avg_cost": 140,
            "cost": 2_800.0, "close_price": 150, "market_value": 3_000.0,
            "status": "active", "priced": True, "price_as_of_kst": "2026-08-20 07:05",
        }],
    }
    row.update(overrides)
    return row


def test_write_daily_snapshots_usd_upserts_both_usd_tables_once():
    client = FakeClient()
    duel_db_usd.write_daily_snapshots_usd(
        client, date(2026, 8, 20), [_snapshot_row_usd("acc-1"), _snapshot_row_usd("acc-2")])

    daily = client.only_call(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "upsert")
    holdings = client.only_call(duel_db_usd.HOLDING_SNAPSHOTS_TABLE_USD, "upsert")
    assert daily.options["on_conflict"] == "account_id,snapshot_date"
    assert holdings.options["on_conflict"] == "account_id,ticker,snapshot_date"
    assert len(daily.rows) == 2 and len(holdings.rows) == 2
    assert client.calls_for(duel_db.DAILY_SNAPSHOTS_TABLE) == [], "KRW 스냅샷 표에는 손대지 않습니다"


def test_write_daily_snapshots_usd_rejects_total_value_mismatch():
    """검증은 (공유) `_validate_daily_snapshot()` 이 그대로 하므로 KRW 와 같은 규칙이 적용됩니다."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.write_daily_snapshots_usd(
            client, date(2026, 8, 20), [_snapshot_row_usd(total_value=9_999.0)])
    assert "총자산" in str(excinfo.value)
    assert client.calls == []


def test_write_daily_snapshots_usd_with_no_rows_writes_nothing():
    client = FakeClient()
    assert duel_db_usd.write_daily_snapshots_usd(client, date(2026, 8, 20), []) is None
    assert client.calls == []


# =============================================================================
# 12. B 절 — "모든 USD 계좌를 한 번에" 진입점
# =============================================================================
def test_fetch_all_active_accounts_usd_is_one_query():
    client = FakeClient(responses={(duel_db_usd.ACCOUNTS_TABLE_USD, "select"): _active_accounts_usd(4)})
    rows = duel_db_usd.fetch_all_active_accounts_usd(client)
    assert len(rows) == 4
    call = client.only_call(duel_db_usd.ACCOUNTS_TABLE_USD, "select")
    assert call.filter_map == {"status": "active"}
    assert len(client.calls) == 1


def test_fetch_cash_ledger_for_accounts_usd_uses_one_in_filter():
    client = FakeClient(responses={(duel_db_usd.LEDGER_TABLE_USD, "select"): [
        {"account_id": "acc-1", "amount": 7_500},
        {"account_id": "acc-1", "amount": -500},
        {"account_id": "acc-2", "amount": 7_500},
    ]})
    rows = duel_db_usd.fetch_cash_ledger_for_accounts_usd(client, ["acc-1", "acc-2"],
                                                          as_of_date=date(2026, 8, 20))
    call = client.only_call(duel_db_usd.LEDGER_TABLE_USD, "select")
    assert ("in", "account_id", ["acc-1", "acc-2"]) in call.filters
    assert duel_db_usd.cash_balances_by_account(rows) == {"acc-1": 7_000.0, "acc-2": 7_500.0}


def test_fetch_cash_ledger_for_accounts_usd_with_empty_list_sends_no_query():
    client = FakeClient()
    assert duel_db_usd.fetch_cash_ledger_for_accounts_usd(client, []) == []
    assert client.calls == []


# =============================================================================
# 13. B 절 — 공개 발행 (USD 미러)
# =============================================================================
def test_fetch_publishable_consents_usd_reads_only_final_confirmed_and_not_revoked():
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): [
        {"account_id": "acc-1", "final_confirmed": True, "revoked_at": None},
    ]})
    rows = duel_db_usd.fetch_publishable_consents_usd(client)
    assert len(rows) == 1
    call = client.only_call(duel_db_usd.CONSENT_TABLE_USD, "select")
    assert ("eq", "final_confirmed", True) in call.filters


def test_fetch_revoked_consent_accounts_usd_reads_only_revoked_rows():
    client = FakeClient(responses={(duel_db_usd.CONSENT_TABLE_USD, "select"): [
        {"account_id": "acc-9", "revoked_at": "2026-08-01T00:00:00+09:00"},
    ]})
    rows = duel_db_usd.fetch_revoked_consent_accounts_usd(client)
    assert rows == [{"account_id": "acc-9", "revoked_at": "2026-08-01T00:00:00+09:00"}]


def test_bracket_assignments_usd_round_trip_through_insert_and_fetch():
    client = FakeClient(responses={
        (duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "select"): [
            {"account_id": "acc-1", "season_key": "2026-03-01", "bracket_key": "usd_under_750"},
        ],
    })
    inserted = duel_db_usd.insert_bracket_assignments_usd(client, [
        {"account_id": "acc-1", "season_key": "2026-03-01", "bracket_key": "usd_under_750"},
    ])
    assert inserted == 1
    fetched = duel_db_usd.fetch_bracket_assignments_usd(client, "2026-03-01")
    assert fetched["acc-1"]["bracket_key"] == "usd_under_750"


def test_insert_bracket_assignments_usd_rejects_duplicate_conflict_keys():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.insert_bracket_assignments_usd(client, [
            {"account_id": "acc-1", "season_key": "2026-03-01", "bracket_key": "usd_under_750"},
            {"account_id": "acc-1", "season_key": "2026-03-01", "bracket_key": "usd_750_2250"},
        ])
    assert client.calls == []


def test_delete_published_rows_for_date_usd_touches_only_usd_tables():
    client = FakeClient()
    duel_db_usd.delete_published_rows_for_date_usd(client, date(2026, 8, 20))
    assert client.only_call(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "delete").filter_map == \
        {"published_date": "2026-08-20"}
    assert client.only_call(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "delete").filter_map == \
        {"published_date": "2026-08-20"}
    assert client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE) == []
    assert client.calls_for(duel_db.PUBLIC_HOLDINGS_TABLE) == []


def test_delete_published_rows_for_nicknames_usd_deletes_from_both_usd_tables():
    client = FakeClient(responses={
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "delete"): [{"id": "r1"}],
        (duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "delete"): [{"id": "h1"}, {"id": "h2"}],
    })
    removed = duel_db_usd.delete_published_rows_for_nicknames_usd(client, ["떠난사람0009"])
    assert removed == 3


def test_leaderboard_has_any_rows_usd_true_and_false():
    empty_client = FakeClient(responses={(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): []})
    assert duel_db_usd.leaderboard_has_any_rows_usd(empty_client) is False

    full_client = FakeClient(responses={
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): [{"id": "r1"}],
    })
    assert duel_db_usd.leaderboard_has_any_rows_usd(full_client) is True


def test_fetch_published_group_index_usd_groups_nicknames_by_date():
    client = FakeClient(responses={(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): [
        {"published_date": "2026-08-19", "nickname": "떠난사람0001"},
        {"published_date": "2026-08-19", "nickname": "떠난사람0002"},
        {"published_date": "2026-08-20", "nickname": "떠난사람0001"},
    ]})
    index = duel_db_usd.fetch_published_group_index_usd(client, "M1", "usd_under_750")
    assert index == {
        "2026-08-19": ["떠난사람0001", "떠난사람0002"],
        "2026-08-20": ["떠난사람0001"],
    }


def test_delete_published_group_usd_with_empty_group_does_nothing():
    client = FakeClient(responses={(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): []})
    removed = duel_db_usd.delete_published_group_usd(client, "M1", "usd_under_750")
    assert removed == 0
    assert client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "delete") == []


def test_write_public_leaderboard_usd_rejects_identity_fields():
    """식별자 혼입 방어(`_assert_no_identity_fields`)는 KRW 파일 함수를 그대로 재사용합니다."""
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.write_public_leaderboard_usd(client, date(2026, 8, 20), [
            {"window_type": "M1", "bracket_key": "usd_under_750", "rank": 1,
             "nickname": "떠난사람0001", "twr_pct": 1.5, "account_id": "acc-1"},
        ])
    assert client.calls == []


def test_write_public_leaderboard_usd_writes_the_usd_table_only():
    client = FakeClient()
    written = duel_db_usd.write_public_leaderboard_usd(client, date(2026, 8, 20), [
        {"window_type": "M1", "bracket_key": "usd_under_750", "rank": 1,
         "nickname": "떠난사람0001", "twr_pct": 1.5},
    ])
    assert written == 1
    assert client.only_call(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert").rows[0]["published_date"] \
        == "2026-08-20"
    assert client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE) == []


def test_write_public_holdings_usd_rejects_identity_fields():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db_usd.write_public_holdings_usd(client, date(2026, 8, 20), [
            {"window_type": "M1", "nickname": "떠난사람0001", "ticker": "AAPL",
             "stock_name": "애플", "quantity": 20, "buy_amount": 2_800, "user_id": "user-1"},
        ])
    assert client.calls == []


# =============================================================================
# 14. None 클라이언트는 AttributeError 가 아니라 DuelDbError 여야 합니다
# =============================================================================
@pytest.mark.parametrize("call", [
    lambda: duel_db_usd.opt_in_usd(None),
    lambda: duel_db_usd.fetch_my_accounts_usd(None, "user-1"),
    lambda: duel_db_usd.fetch_my_positions_usd(None, "acc-1"),
    lambda: duel_db_usd.save_order_usd(None, "acc-1", "AAPL", "애플", 1,
                                       trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW_USD),
    lambda: duel_db_usd.edit_order_usd(None, "order-1", 3, now_kst=INSIDE_WINDOW_USD),
    lambda: duel_db_usd.cancel_order_usd(None, "order-1", now_kst=INSIDE_WINDOW_USD),
    lambda: duel_db_usd.save_consent_usd(None, "acc-1", consent_rank=True),
    lambda: duel_db_usd.revoke_consent_usd(None, "acc-1"),
    lambda: duel_db_usd.fetch_all_active_accounts_usd(None),
    lambda: duel_db_usd.apply_monthly_deposits_usd(None, date(2026, 9, 10)),
    lambda: duel_db_usd.create_duel_accounts_for_user_usd(None, "user-1"),
    lambda: duel_db_usd.fetch_pending_orders_for_fill_usd(None, date(2026, 8, 20)),
    lambda: duel_db_usd.expire_or_cancel_all_pending_for_date_usd(None, date(2026, 8, 20), "사유"),
    lambda: duel_db_usd.write_daily_snapshots_usd(None, date(2026, 8, 20), [_snapshot_row_usd()]),
    lambda: duel_db_usd.record_order_fill_usd(None, "o-1", "filled", 1, 100, 100,
                                               filled_date=date(2026, 8, 20)),
    lambda: duel_db_usd.record_buy_ledger_entry_usd(None, "acc-1", "o-1", 100, date(2026, 8, 20)),
    lambda: duel_db_usd.upsert_position_weighted_average_usd(None, "acc-1", "AAPL", "애플",
                                                             None, 1, 100),
])
def test_none_client_raises_duel_db_error_not_attribute_error_usd(call):
    with pytest.raises(DuelDbError):
        call()


# =============================================================================
# 15. 계층 분리 — 계산을 이 파일에서 다시 구현하지 않았는지 (USD 미러)
# =============================================================================
def test_duel_db_usd_calls_the_rules_module_and_does_not_reimplement_it():
    tree, source = _usd_module_ast()
    assert "from utils import duel_rules" in source

    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstring_nodes.add((body[0].lineno, body[0].end_lineno))
    skip = set()
    for start, end in docstring_nodes:
        skip.update(range(start, (end or start) + 1))
    executable_lines = [line for number, line in enumerate(source.splitlines(), start=1)
                        if number not in skip and not line.lstrip().startswith("#")]
    executable = "\n".join(executable_lines)

    for reimplementation in ("math.floor", "// price", "chain *=", "Decimal("):
        assert reimplementation not in executable, f"{reimplementation} 를 여기서 다시 짜지 마세요"
    # 시드/입금 금액 상수도 다시 하드코딩하지 않습니다(단일 출처는 duel_rules —
    # 이 파일은 `from utils.duel_rules import SEED_AMOUNT_USD, MONTHLY_DEPOSIT_USD` 로
    # 이름만 가져다 씁니다. 숫자 리터럴 7500/500 은 executable 코드에 없어야 합니다).
    assert "7_500" not in executable and "7500" not in executable
    assert "SEED_AMOUNT_USD" in source
    assert "MONTHLY_DEPOSIT_USD" in source


def test_rules_module_usd_constants_were_not_modified_by_this_layer():
    for name in ("resolve_order_window_usd", "assign_bracket_usd", "bracket_label_usd"):
        assert callable(getattr(duel_rules, name)), name
    assert duel_rules.SEED_AMOUNT_USD == 7_500
    assert duel_rules.MONTHLY_DEPOSIT_USD == 500


def test_every_public_function_in_duel_db_usd_has_a_docstring():
    missing = [name for name, function in vars(duel_db_usd).items()
               if inspect.isfunction(function)
               and function.__module__ == duel_db_usd.__name__
               and not name.startswith("_")
               and not (function.__doc__ or "").strip()]
    assert missing == [], f"docstring 없는 공개 함수: {missing}"
