# tests/test_duel_db.py
"""
⚔️ "결투다!" — Supabase 접근 계층(`utils/duel_db.py`) 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · `supabase` 패키지 설치 여부와 무관)

DUEL_MODULE_WORK_ORDER.md 4단계에 따라, **가짜 Supabase 클라이언트**로만 검증합니다.
`tests/test_scorecard_ocr.py` 가 Gemini 클라이언트를 스텁으로 대체한 것과 같은 방식이고,
`tests/test_duel.py`(순수 규칙 검증)와 짝을 이룹니다 — 저쪽은 "계산이 맞는가", 이쪽은
"맞는 계산 결과를 **맞는 표에, 맞는 조건으로, 몇 번에** 보내는가"를 봅니다.

가짜 클라이언트가 필요한 이유: supabase-py 는 `.table(x).select(y).eq(a, b).execute()` 처럼
**메서드 체이닝**으로 질의를 조립합니다. 그래서 스텁도 체이닝을 지원해야 하고, 마지막에
"결국 무엇을 요청/기록했는지"를 테스트가 들여다볼 수 있어야 합니다(아래 `FakeClient`).

검증 대상
    ① A 절(사용자용)이 **맞는 표에 맞는 필터**로 가는지
    ② A 절이 RLS 상 쓸 수 없는 값(체결 결과 등)을 **인자로도 받지 않는지** — 코드 경로 자체가
       없다는 것을 시그니처·AST 검사로 고정(스키마 §9 의 권한 배치와 같은 결론)
    ③ `save_order` 가 접수 시간대 밖이면 **명확한 한국어 오류**로 거절하고, 안이면 저장하는지
    ④ `create_duel_accounts_for_user` 멱등성 — 두 번 불러도 오류 없이 계좌가 늘지 않는지
    ⑤ `apply_monthly_deposits` 가 계좌 수와 무관하게 **집합 연산 1회**인지 (§0-3-2 회귀 고정)
    ⑥ `expire_or_cancel_all_pending_for_date` 도 update 질의 **1개**인지
    ⑦ 배치 기록 함수들이 `duel_rules` 의 결과를 **그대로** 담아 보내는지(재계산 금지)
    ⑧ `try/except ImportError` 가드 — `supabase` 미설치 상태에서 import 가 깨지지 않고,
       그 상태로 함수를 부르면 `AttributeError` 가 아니라 **잡을 수 있는 명확한 오류**가 나는지
    ⑨ (2026-08-20 추가) 옵트인 `opt_in()` — 사용자 본인 세션으로 `duel_opt_in()` RPC 를
       **인자 하나 없이** 한 번만 부르는지, 응답을 어떻게 다루는지, 그리고 이 함수가 배치
       키를 건드리지 않는지(AST 검사). SQL 쪽 조건(security definer · 인자 없음 · execute 는
       authenticated 만 · 시드 금액이 앱 상수와 일치)도 파일을 읽어 함께 고정합니다.
       ⚠️ 권한·격리·멱등성의 **실제 동작**은 가짜 클라이언트로 검증할 수 없어서 로컬
          PostgreSQL 16 에 스키마를 올려 역할별로 직접 호출해 확인했습니다(작업 보고 참고).
          여기서 "검증했다"고 말하는 범위를 넘기지 않습니다(§0-1).

실행: pytest tests/test_duel_db.py -v
"""

import ast
import inspect
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

from utils import duel_db  # noqa: E402
from utils import duel_rules  # noqa: E402
from utils.duel_db import DuelDbError  # noqa: E402
from utils.duel_rules import KST, DuelRuleError  # noqa: E402


# =============================================================================
# 0. 가짜 Supabase 클라이언트 — 체이닝을 흉내내고, 요청된 내용을 전부 기록합니다
# =============================================================================
class FakeResponse:
    """supabase-py 의 응답 객체는 `.data` 하나만 보면 됩니다(우리 `_execute` 규약)."""

    def __init__(self, data):
        self.data = data


class FakeQuery:
    """
    `.select()/.insert()/.update()/.upsert()` 로 시작해 `.eq()/.gte()/...` 를 체이닝하고
    `.execute()` 로 끝나는 질의 하나.

    테스트가 들여다보는 것:
        table    : 어느 표인지
        op       : select / insert / update / upsert / delete
        payload  : 실제로 보낸 값(단건이면 dict, 여러 건이면 list)
        filters  : [("eq", "status", "pending"), ...]
        orders   : [("saved_at", False), ...]   (False = 오름차순)
        options  : upsert 의 on_conflict 등
    """

    def __init__(self, client, table, op, payload=None, **options):
        self.client = client
        self.table = table
        self.op = op
        self.payload = payload
        self.options = options
        self.filters = []
        self.orders = []
        self.executed = False

    # ── 필터 ──────────────────────────────────────────────────────────────────
    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    def lt(self, column, value):
        """`.lt()` — 2026-08-29 재감사 H-8 의 "그 이전 전부" 정리가 쓰는 필터입니다."""
        self.filters.append(("lt", column, value))
        return self

    def gt(self, column, value):
        self.filters.append(("gt", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def filter(self, column, operator, criteria):
        """
        PostgREST 의 범용 필터(`.filter(col, "is", "null")`). 2026-08-20 추가 —
        `utils/duel_db.py::_filter_is_null()` / `_filter_not_null()` 이 이 형태를 씁니다
        (NULL 여부를 `.is_()` 와 `.not_.is_()` 두 가지 문법으로 나눠 쓰지 않으려고).
        """
        self.filters.append((operator, column, criteria))
        return self

    def range(self, start, end):
        """
        PostgREST 의 페이지네이션(`.range(start, end)` — **양끝을 포함**하는 구간).
        2026-08-20 추가 — `utils/duel_db.py::fetch_public_leaderboard()` 가 순위표 한
        페이지를 읽는 방법입니다(`.limit()` + `.offset()` 두 갈래로 나누지 않고 한 가지
        형태로만 씁니다 — `.filter()` 를 추가할 때와 같은 판단).
        """
        self.options["range"] = (start, end)
        return self

    def limit(self, count):
        self.options["limit"] = count
        return self

    def order(self, column, desc=False):
        self.orders.append((column, desc))
        return self

    # ── 실행 ──────────────────────────────────────────────────────────────────
    def execute(self):
        self.executed = True
        self.client.calls.append(self)
        return FakeResponse(self.client.resolve(self))

    # ── 테스트 편의 ───────────────────────────────────────────────────────────
    @property
    def filter_map(self):
        return {column: value for _op, column, value in self.filters}

    @property
    def rows(self):
        """payload 를 항상 목록으로(단건 insert 와 다건 insert 를 같은 방식으로 검사)."""
        if self.payload is None:
            return []
        return list(self.payload) if isinstance(self.payload, list) else [self.payload]

    def __repr__(self):  # pragma: no cover - 실패 메시지 가독성용
        return f"<FakeQuery {self.op} {self.table} filters={self.filters}>"


class FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def select(self, columns="*"):
        return FakeQuery(self.client, self.name, "select", columns=columns)

    def insert(self, payload):
        return FakeQuery(self.client, self.name, "insert", payload)

    def update(self, payload):
        return FakeQuery(self.client, self.name, "update", payload)

    def upsert(self, payload, on_conflict=None, **kwargs):
        return FakeQuery(self.client, self.name, "upsert", payload,
                         on_conflict=on_conflict, **kwargs)

    def delete(self):
        return FakeQuery(self.client, self.name, "delete")


class FakeClient:
    """
    `responses` 로 "이 표의 이 동작은 이런 데이터를 돌려준다"를 지정합니다.
      · 값이 Exception 이면 `.execute()` 가 그걸 raise 합니다(트리거 거절·유니크 충돌 모사).
      · 값이 목록이면 **호출될 때마다 앞에서 하나씩** 꺼내 씁니다(같은 질의의 1차/2차 응답).
      · 값이 callable 이면 질의를 받아 데이터를 돌려줍니다.
    지정이 없으면 insert/update/upsert 는 **보낸 payload 를 그대로** 돌려줍니다(PostgREST 의
    기본 동작과 같습니다 — 저장된 행을 반환). select 는 빈 목록입니다.
    """

    def __init__(self, responses=None):
        self.calls = []
        self.responses = dict(responses or {})

    def table(self, name):
        return FakeTable(self, name)

    def rpc(self, function_name, params=None):
        """
        supabase-py 의 `client.rpc("함수이름", {인자})` 흉내. 저장 프로시저 호출은 표가 아니라
        **함수 이름**으로 기록해 두고(`query.table` 자리에 함수 이름), 테스트가 "무슨 이름을,
        어떤 인자로, 몇 번 불렀는지"를 그대로 들여다볼 수 있게 합니다.
        """
        return FakeQuery(self, function_name, "rpc", params)

    def resolve(self, query):
        key = (query.table, query.op)
        if key in self.responses:
            value = self.responses[key]
            if isinstance(value, list) and value and isinstance(value[0], _Sequenced):
                value = value.pop(0).value
            if isinstance(value, _Sequenced):  # pragma: no cover - 방어
                value = value.value
            if callable(value):
                value = value(query)
            if isinstance(value, Exception):
                raise value
            return value
        if query.op in ("insert", "update", "upsert"):
            return [dict(row) for row in query.rows]
        return []

    # ── 테스트 편의 ───────────────────────────────────────────────────────────
    def calls_for(self, table=None, op=None):
        return [call for call in self.calls
                if (table is None or call.table == table) and (op is None or call.op == op)]

    def only_call(self, table=None, op=None):
        found = self.calls_for(table, op)
        assert len(found) == 1, f"질의가 정확히 1개여야 합니다: {found}"
        return found[0]


class _Sequenced:
    """`responses` 값으로 여러 응답을 순서대로 주고 싶을 때 감싸는 표식."""

    def __init__(self, value):
        self.value = value


def sequence(*values):
    """같은 (표, 동작)에 대해 1차·2차 응답을 다르게 주는 헬퍼."""
    return [_Sequenced(value) for value in values]


# ── 시각 고정값 ────────────────────────────────────────────────────────────────
INSIDE_WINDOW = datetime(2026, 8, 19, 19, 30, 0, tzinfo=KST)    # 접수 시간대 한가운데
OUTSIDE_WINDOW = datetime(2026, 8, 19, 17, 59, 59, tzinfo=KST)  # 창이 열리기 2초 전
TRADING_DAYS = [date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)]


# =============================================================================
# 0-A. A 절 — 모듈 참여(옵트인) RPC  (작업지시서 2-1 · 스키마 §9-10)
# =============================================================================
#  오너가 2026-08-20 에 "참여하기를 누르면 시드머니가 즉시 들어와야 한다"를 확정했습니다.
#  시드머니는 현금 원장(`duel_cash_ledger`)에 쓰는 일인데, 그 표는 사용자 세션이 쓸 수 없게
#  일부러 잠가 둔 표이고(스키마 §9-4), 그렇다고 사용자 접속 앱 서버에 배치 키를 두면 이
#  모듈의 RLS 가 통째로 무력화됩니다(§0-3-8). 그래서 **DB 안의 좁은 저장 프로시저**
#  (`duel_opt_in()`, 인자 없음 · auth.uid() 로만 동작)를 사용자 본인 세션으로 부릅니다.
#
#  ⚠️ 여기 테스트가 검증하는 것은 **파이썬 래퍼의 계약**입니다 — "무슨 이름을, 어떤 인자로,
#     몇 번 부르고, 응답을 어떻게 다루는가". 실제 권한·격리·멱등성(다른 사용자의 계좌를
#     만들 수 없는지, 두 번 불러도 시드가 두 번 안 들어가는지)은 오프라인에서 흉내낼 수
#     없어서 **로컬 PostgreSQL 16 에 스키마를 실제로 올리고 역할별로 직접 호출해** 확인했고,
#     그 결과는 작업 보고에 정리돼 있습니다(스키마 §11 ⑨ 자가 점검 쿼리도 참고).
#     아래에는 오프라인에서 확실히 지킬 수 있는 것만 남깁니다 — 흉내낸 DB 로 "권한을
#     검증했다"고 말하지 않기 위해서입니다(§0-1).
# =============================================================================
def _opt_in_rows(user_id="user-1", anchor="2026-08-20"):
    """RPC 가 돌려주는 계좌 3행(실제 반환 모양 그대로: duel_accounts 행)."""
    return [{"id": f"acc-{index}", "user_id": user_id, "window_type": window,
             "seed_amount": duel_rules.SEED_AMOUNT_KRW, "currency": "KRW",
             "anchor_date": anchor, "status": "active"}
            for index, window in enumerate(("M1", "M3", "M6"), start=1)]


def test_opt_in_calls_the_rpc_once_and_returns_three_accounts():
    """
    호출은 **RPC 한 번**이고, 계좌 3행을 그대로 돌려줍니다(화면이 다시 조회하지 않도록).
    """
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): _opt_in_rows()})
    accounts = duel_db.opt_in(client)

    call = client.only_call(duel_db.OPT_IN_RPC, "rpc")
    assert call.op == "rpc"
    assert call.table == "duel_opt_in"
    assert len(client.calls) == 1, "옵트인은 왕복 1회여야 합니다(두 번째 조회 금지)"
    assert [row["window_type"] for row in accounts] == ["M1", "M3", "M6"]
    assert all(row["seed_amount"] == duel_rules.SEED_AMOUNT_KRW for row in accounts)


def test_opt_in_sends_no_arguments_at_all():
    """
    🔴 이 함수의 안전성 근거: **인자가 하나도 없습니다.**
    누구를 참여시킬지(user_id)도, 얼마를 줄지(금액)도, 언제로 할지(날짜)도 보내지 않습니다.
    보내는 순간 "남의 ID 를 넣으면?" "금액을 크게 넣으면?" 이라는 질문이 생깁니다.
    """
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): _opt_in_rows()})
    duel_db.opt_in(client)

    payload = client.only_call(duel_db.OPT_IN_RPC, "rpc").payload
    assert payload in ({}, None), f"RPC 에 인자를 보내고 있습니다: {payload}"

    parameters = list(inspect.signature(duel_db.opt_in).parameters)
    assert parameters == ["client"], f"opt_in 의 인자는 클라이언트 하나뿐이어야 합니다: {parameters}"


def test_opt_in_never_writes_to_any_table_directly():
    """사용자 세션은 계좌·원장 표에 **직접** 쓰지 않습니다 — 전부 RPC 안에서 일어납니다."""
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): _opt_in_rows()})
    duel_db.opt_in(client)
    for forbidden in (duel_db.LEDGER_TABLE, duel_db.ACCOUNTS_TABLE):
        assert client.calls_for(forbidden) == [], f"{forbidden} 에 직접 질의했습니다"


def test_opt_in_orders_the_rows_even_if_the_server_shuffles_them():
    """화면이 M1 → M3 → M6 순서를 그대로 믿을 수 있어야 합니다."""
    shuffled = list(reversed(_opt_in_rows()))
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): shuffled})
    assert [row["window_type"] for row in duel_db.opt_in(client)] == ["M1", "M3", "M6"]


def test_opt_in_empty_response_is_not_a_silent_success():
    """
    RPC 가 아무 행도 돌려주지 않았는데 "참여됐습니다"라고 말하면, 사용자는 돈이 들어온 줄
    알고 주문 화면으로 갑니다. 조용한 성공을 만들지 않습니다(§0-1).
    """
    client = FakeClient()          # 응답 미지정 → 빈 목록
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.opt_in(client)
    assert "M1" in str(excinfo.value) and "M3" in str(excinfo.value)


def test_opt_in_partial_response_is_rejected():
    """계좌가 3개 중 2개만 돌아온 반쪽 상태도 성공으로 처리하지 않습니다."""
    client = FakeClient(responses={
        (duel_db.OPT_IN_RPC, "rpc"): _opt_in_rows()[:2],   # M1, M3 만
    })
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.opt_in(client)
    assert "M6" in str(excinfo.value)
    # 다시 눌러도 안전하다는 안내가 함께 나가야 합니다(사용자가 재시도를 겁내지 않도록).
    assert "다시" in str(excinfo.value)


def test_opt_in_without_a_login_session_gets_a_korean_message():
    """
    로그인 세션 없이 호출하면 DB 가 거절합니다(§9-10 의 auth.uid() 검사). 그 거절이
    Postgres 원문 그대로 화면에 뜨지 않게 **사실은 유지하고 표현만** 바꿉니다(§0-3-4).
    """
    rejection = Exception(
        "duel_opt_in: 로그인한 사용자만 결투 모듈에 참여할 수 있습니다"
        "(요청에 로그인 세션이 없습니다). SQLSTATE 28000"
    )
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): rejection})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.opt_in(client)
    message = str(excinfo.value)
    assert "로그인" in message
    assert "SQLSTATE" not in message and "duel_opt_in:" not in message


def test_opt_in_tells_the_owner_when_the_function_is_not_installed_yet():
    """
    스키마 스크립트를 아직 실행하지 않은 상태(PostgREST 의 PGRST202)에서, "알 수 없는
    오류"가 아니라 **무엇을 해야 하는지**가 보이는 문장이 나와야 합니다(§0-3-4).
    """
    missing = Exception(
        "{'code': 'PGRST202', 'message': 'Could not find the function"
        " public.duel_opt_in without parameters in the schema cache'}"
    )
    client = FakeClient(responses={(duel_db.OPT_IN_RPC, "rpc"): missing})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.opt_in(client)
    assert "duel_schema.sql" in str(excinfo.value)


def test_opt_in_with_a_client_that_cannot_call_rpc_says_so_in_korean():
    """
    저장 프로시저를 부를 수 없는 클라이언트가 넘어와도 `'X' object has no attribute 'rpc'`
    같은 메시지를 사용자에게 보여주지 않습니다(§0-3-4 — `_require_client` 와 같은 판단).
    """
    class ClientWithoutRpc:
        def table(self, name):  # pragma: no cover - 호출되지 않아야 정상
            raise AssertionError("표를 건드리면 안 됩니다")

    with pytest.raises(DuelDbError) as excinfo:
        duel_db.opt_in(ClientWithoutRpc())
    assert "attribute" not in str(excinfo.value).lower()


def test_opt_in_rpc_name_matches_the_sql_function_name():
    """
    파이썬이 부르는 이름과 SQL 이 만드는 이름이 어긋나면 배포 후에야 알게 됩니다.
    표 이름 상수들과 같은 규약으로, 여기서 글자 그대로 대조합니다.
    """
    assert duel_db.OPT_IN_RPC == "duel_opt_in"
    schema = _duel_schema_sql()
    assert f"create function public.{duel_db.OPT_IN_RPC}()" in schema


def _duel_schema_sql():
    return (REPO_ROOT / "sql" / "duel_schema.sql").read_text(encoding="utf-8")


def _executable_sql():
    """`--` 주석을 뺀, 실제로 실행되는 SQL 만."""
    return "\n".join(line for line in _duel_schema_sql().splitlines()
                     if not line.lstrip().startswith("--"))


def test_sql_seed_constant_matches_the_app_constant():
    """
    🔴 금액이 두 곳에 적히게 된 지점 — 그래서 **자동으로** 대조합니다.

    원래 이 프로젝트의 규율은 "금액 숫자는 DB 에 적지 않는다"였습니다(스키마 §1 의
    seed_amount default 없음). 옵트인 RPC 는 그 규율이 성립하지 않는 유일한 경우입니다:
    금액을 앱에서 인자로 받으면 **사용자가 금액을 고를 수 있게** 되어(스스로 돈을 찍는 경로)
    함수를 만든 이유 자체가 사라지기 때문입니다. 그래서 금액은 DB 안
    (`public.duel_seed_amount_krw()`)에 있어야 하고, **그 한 곳뿐이어야** 합니다.
    한쪽만 고치는 사고는 사람의 기억이 아니라 이 테스트가 막습니다.
    """
    executable = _executable_sql()
    match = re.search(r"create or replace function public\.duel_seed_amount_krw\(\)"
                      r".*?select\s+(\d+)::numeric", executable, re.S)
    assert match, "SQL 쪽 시드 상수 함수(duel_seed_amount_krw)를 찾지 못했습니다"
    assert int(match.group(1)) == duel_rules.SEED_AMOUNT_KRW, (
        "sql/duel_schema.sql 의 시드 금액이 utils/duel_rules.py::SEED_AMOUNT_KRW 와 다릅니다"
    )
    # SQL 안에서도 출처는 한 곳뿐이어야 합니다(다른 곳에 또 적히면 같은 사고가 재발합니다).
    assert executable.count(str(duel_rules.SEED_AMOUNT_KRW)) == 1
    # 그리고 그 값이 컬럼 default 로 새어 들어가지 않았는지(§1 의 원래 규율은 그대로).
    assert f"default {duel_rules.SEED_AMOUNT_KRW}" not in executable


def test_sql_seed_constant_usd_matches_the_app_constant():
    """
    USD 트랙의 `public.duel_seed_amount_usd()` 도 `utils/duel_rules.py::SEED_AMOUNT_USD` 와
    같은 값이어야 합니다 — KRW 와 같은 이유(§13-1 주석이 이미 이 대조를 요구합니다).
    2026-08-20: 이 스키마는 이미 오너의 프로덕션 Supabase 에 적용·확인(21개 표, seed=7500)
    됐습니다 — 이 테스트는 그 값이 앱 상수와 계속 같은 값을 유지하는지 지키는 회귀 고정입니다.
    """
    executable = _executable_sql()
    match = re.search(r"create or replace function public\.duel_seed_amount_usd\(\)"
                      r".*?select\s+(\d+)::numeric", executable, re.S)
    assert match, "SQL 쪽 시드 상수 함수(duel_seed_amount_usd)를 찾지 못했습니다"
    assert int(match.group(1)) == duel_rules.SEED_AMOUNT_USD, (
        "sql/duel_schema.sql 의 USD 시드 금액이 utils/duel_rules.py::SEED_AMOUNT_USD 와 다릅니다"
    )
    assert executable.count(str(duel_rules.SEED_AMOUNT_USD)) == 1
    assert f"default {duel_rules.SEED_AMOUNT_USD}" not in executable


def test_sql_opt_in_function_is_security_definer_and_argument_free():
    """
    이 함수가 안전한 이유 4가지가 SQL 에 실제로 적혀 있는지 확인합니다.
    (실제 동작은 로컬 PostgreSQL 16 실검증에서 확인했고, 여기서는 그 조건들이 나중에
     조용히 지워지지 않게 **회귀 고정**만 합니다.)
    """
    executable = _executable_sql()
    start = executable.index("create function public.duel_opt_in()")
    body = executable[start:executable.index("comment on function public.duel_opt_in()")]

    assert "security definer" in body          # ① 표 소유자 권한으로 돈다
    assert "set search_path = public" in body  # ② 함수 하이재킹 방지(§9-0 과 같은 관례)
    assert "auth.uid()" in body                # ③ 대상은 지금 요청의 로그인 사용자뿐
    assert "create function public.duel_opt_in()" in body   # ④ 인자 없음(빈 괄호)
    # 사용자에게서 금액·대상·날짜를 받는 인자가 생기면 위 ③④가 무너집니다.
    assert "duel_opt_in(p_" not in executable and "duel_opt_in(user" not in executable
    # 멱등성은 이미 있는 유니크 인덱스에 기댑니다(새 규칙을 발명하지 않기).
    assert "on conflict (user_id, window_type) do nothing" in body
    assert "on conflict (account_id) where event_type = 'seed' do nothing" in body


def test_sql_opt_in_execute_grant_is_authenticated_only():
    """
    🔴 execute 는 로그인 사용자에게만. `anon`(비로그인)에게 주면, auth.uid() 가 NULL 이라
    실패하더라도 "부를 수는 있는 함수"가 하나 생깁니다 — §9-9 의 revoke ... from anon 과
    같은 이중 방어를 함수에도 적용합니다.
    """
    executable = _executable_sql()
    assert "revoke all on function public.duel_opt_in() from public;" in executable
    assert "grant execute on function public.duel_opt_in() to authenticated;" in executable
    for forbidden in ("duel_opt_in() to anon", "duel_opt_in() to public",
                      "duel_opt_in() to authenticated, anon"):
        assert forbidden not in executable, f"금지된 권한 부여: {forbidden}"


# =============================================================================
# 1. A 절 — 주문 저장 (2-4)
# =============================================================================
def test_save_order_inside_window_writes_pending_order():
    """접수 시간대 안이면 pending 주문 1행이 duel_orders 로 들어갑니다."""
    client = FakeClient()
    order = duel_db.save_order(
        client, "acc-1", "005930", "삼성전자", 10,
        trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW,
    )

    call = client.only_call(duel_db.ORDERS_TABLE, "insert")
    payload = call.rows[0]
    assert payload["account_id"] == "acc-1"
    assert payload["ticker"] == "005930"
    assert payload["requested_quantity"] == 10
    assert payload["side"] == "buy"
    assert payload["status"] == "pending"
    # 체결가는 D 종가가 아니라 **D+1 종가**입니다 — 귀속 거래일이 다음 거래일이어야 합니다.
    assert payload["target_date"] == "2026-08-20"
    # 접수 시간대 판정에 쓴 바로 그 시각이 기록됩니다(판정 시각 ≠ 기록 시각 방지).
    assert payload["saved_at"].startswith("2026-08-19T19:30:00")
    assert order["ticker"] == "005930"


def test_save_order_never_writes_fill_result_fields():
    """저장 시점에는 체결 결과도, 현금 차감도 없습니다(2-4-4)."""
    client = FakeClient()
    duel_db.save_order(client, "acc-1", "005930", "삼성전자", 3,
                       trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    payload = client.only_call(duel_db.ORDERS_TABLE, "insert").rows[0]
    for forbidden in ("filled_price", "filled_quantity", "filled_amount", "filled_date"):
        assert forbidden not in payload
    # 원장·포지션은 손도 대지 않습니다(현금은 체결 시점에만 움직입니다).
    assert client.calls_for(duel_db.LEDGER_TABLE) == []
    assert client.calls_for(duel_db.POSITIONS_TABLE) == []


def test_save_order_outside_window_is_rejected_with_korean_message():
    """
    접수 시간대 밖이면 **조용히 실패하지 않고** 이유를 말합니다(§0-1).
    그리고 DB 로는 아무 요청도 나가지 않아야 합니다.
    """
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_order(client, "acc-1", "005930", "삼성전자", 10,
                           trading_days=TRADING_DAYS, now_kst=OUTSIDE_WINDOW)
    message = str(excinfo.value)
    assert "주문 접수 시간" in message
    assert "18:00:01" in message and "22:00:00" in message
    assert client.calls == [], "거절된 주문이 DB 까지 가면 안 됩니다"


def test_save_order_window_boundaries_match_rules():
    """경계(18:00:00 닫힘 / 18:00:01 열림 / 22:00:00 열림 / 22:00:01 닫힘)."""
    cases = {
        datetime(2026, 8, 19, 18, 0, 0, tzinfo=KST): False,
        datetime(2026, 8, 19, 18, 0, 1, tzinfo=KST): True,
        datetime(2026, 8, 19, 22, 0, 0, tzinfo=KST): True,
        datetime(2026, 8, 19, 22, 0, 1, tzinfo=KST): False,
    }
    for moment, should_pass in cases.items():
        client = FakeClient()
        if should_pass:
            duel_db.save_order(client, "acc-1", "005930", "삼성전자", 1,
                               trading_days=TRADING_DAYS, now_kst=moment)
            assert len(client.calls) == 1, moment
        else:
            with pytest.raises(DuelDbError):
                duel_db.save_order(client, "acc-1", "005930", "삼성전자", 1,
                                   trading_days=TRADING_DAYS, now_kst=moment)
            assert client.calls == [], moment


def test_save_order_requires_confirmed_trading_days():
    """거래일 목록이 없으면 다음 날짜를 지어내지 않고 규칙 계층이 거절합니다(§0-1)."""
    client = FakeClient()
    with pytest.raises((DuelDbError, DuelRuleError)):
        duel_db.save_order(client, "acc-1", "005930", "삼성전자", 1,
                           trading_days=None, now_kst=INSIDE_WINDOW)
    assert client.calls == []


def test_save_order_rejects_ticker_outside_universe_when_universe_given():
    """유니버스를 넘겨주면 한 겹 더 막습니다(넘기지 않으면 검사하지 않는다고 명시)."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_order(client, "acc-1", "999999", "없는종목", 1,
                           trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW,
                           universe_tickers={"005930", "000660"})
    # 2026-08-26: 코스피 단독 상위 200 → 코스피+코스닥 통합 상위 500 확대(오너 요청)에 맞춰
    # duel_db.py의 에러 문구가 "코스피 상위" → "코스피+코스닥 상위"로 바뀜.
    assert "코스피+코스닥 상위" in str(excinfo.value)
    assert client.calls == []


@pytest.mark.parametrize("bad_quantity", [0, -1, 2.5, "세 주", None, True])
def test_save_order_rejects_bad_quantity(bad_quantity):
    """수량은 1주 이상의 정수. 2.5주를 2주로 조용히 깎지 않습니다."""
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.save_order(client, "acc-1", "005930", "삼성전자", bad_quantity,
                           trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert client.calls == []


# =============================================================================
# 1-B. A 절 — 창당 1회 리밸런싱 **매도** 주문 저장 (2026-08-21)
# =============================================================================
def test_save_sell_order_writes_a_pending_sell_with_the_window_index():
    """
    매도 주문은 매수와 **같은 시간대·같은 D+1 규약**으로 저장되고, 두 가지만 다릅니다:
    `side='sell'` 과 `rebalance_window_index`. 창 번호는 DB 의 부분 유니크 인덱스가
    "창당 1회"를 강제하는 근거값이라 반드시 실려야 합니다.
    """
    client = FakeClient()
    order = duel_db.save_sell_order(
        client, "acc-1", "005930", "삼성전자", 3, 10, 2,
        trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW,
    )

    payload = client.only_call(duel_db.ORDERS_TABLE, "insert").rows[0]
    assert payload["side"] == "sell"
    assert payload["rebalance_window_index"] == 2
    assert payload["requested_quantity"] == 3
    assert payload["status"] == "pending"
    assert payload["target_date"] == "2026-08-20"          # 매수와 같은 D+1
    assert payload["saved_at"].startswith("2026-08-19T19:30:00")
    # 보유 수량은 **검증에만** 쓰고 저장하지 않습니다(주문 행이 가질 값이 아닙니다).
    assert "held_quantity" not in payload
    assert order["side"] == "sell"


def test_save_sell_order_rejects_more_than_the_holding_before_touching_the_db():
    """
    🔴 보유 수량 초과는 **DB 로 가기 전에** 사람이 읽을 문장으로 거절합니다(사용자 친화적
    사전 점검). 최종 방어는 체결 시점의 `duel_rules.calculate_sell_fill()` 예외입니다.
    """
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 11, 10, 0,
                                trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert "보유 수량" in str(excinfo.value)
    assert client.calls == [], "거절된 매도 주문이 DB 까지 가면 안 됩니다"


def test_save_sell_order_allows_selling_everything():
    """전량 매도(요청 = 보유)는 정상입니다 — 경계에서 막히면 안 됩니다."""
    client = FakeClient()
    duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 10, 10, 0,
                            trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert client.only_call(duel_db.ORDERS_TABLE, "insert").rows[0]["requested_quantity"] == 10


@pytest.mark.parametrize("bad_quantity", [0, -1, 2.5, "세 주", None, True])
def test_save_sell_order_rejects_bad_quantity(bad_quantity):
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", bad_quantity, 10, 0,
                                trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert client.calls == []


@pytest.mark.parametrize("bad_window", [-1, 1.5, None, True, "첫 번째"])
def test_save_sell_order_rejects_a_bad_window_index(bad_window):
    """창 번호는 0 이상의 정수입니다(0 은 첫 창이라 반드시 허용돼야 합니다)."""
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 1, 10, bad_window,
                                trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert client.calls == []


def test_save_sell_order_outside_the_window_is_rejected():
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 1, 10, 0,
                                trading_days=TRADING_DAYS, now_kst=OUTSIDE_WINDOW)
    assert "주문 접수 시간" in str(excinfo.value)
    assert client.calls == []


def test_save_sell_order_translates_the_one_sell_per_window_index_violation():
    """
    🔴 두 번째 매도를 막는 것은 **DB 의 부분 유니크 인덱스**입니다. 그 거절을 삼키지 않고,
    Postgres 원문 대신 사람이 읽을 문장으로 바꿔 올립니다(§0-3-4).
    """
    client = FakeClient(responses={
        (duel_db.ORDERS_TABLE, "insert"):
            RuntimeError('duplicate key value violates unique constraint '
                         '"duel_orders_one_sell_per_window"'),
    })
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 1, 10, 0,
                                trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    message = str(excinfo.value)
    assert "이미 매도 주문을 한 번 사용" in message
    assert "duplicate key" not in message


def test_save_sell_order_never_writes_fill_result_fields():
    """저장은 예약일 뿐입니다 — 체결 결과도, 현금·포지션 변화도 없습니다."""
    client = FakeClient()
    duel_db.save_sell_order(client, "acc-1", "005930", "삼성전자", 1, 10, 0,
                            trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    payload = client.only_call(duel_db.ORDERS_TABLE, "insert").rows[0]
    for forbidden in ("filled_price", "filled_quantity", "filled_amount", "filled_date"):
        assert forbidden not in payload
    assert client.calls_for(duel_db.LEDGER_TABLE) == []
    assert client.calls_for(duel_db.POSITIONS_TABLE) == []


def test_cancelling_a_sell_order_needs_no_new_function():
    """
    `duel_orders_guard` 트리거는 side 와 무관하게 "종결 전엔 자유, 종결 후엔 불가"를
    강제하므로, 매도 주문의 수정·취소는 기존 `edit_order()`/`cancel_order()` 를 그대로
    씁니다(새 함수를 만들지 않은 근거를 여기서 고정합니다).
    """
    client = FakeClient()
    duel_db.cancel_order(client, "order-sell-1", now_kst=INSIDE_WINDOW)
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.payload["status"] == "cancelled"
    assert call.payload["fail_reason"]
    # 취소는 side 를 보지 않습니다 — 조건은 주문 ID 하나뿐입니다.
    assert call.filter_map == {"id": "order-sell-1"}


# =============================================================================
# 2. A 절 — 주문 수정·취소 (2-4-7)
# =============================================================================
def test_edit_order_updates_quantity_only():
    client = FakeClient()
    duel_db.edit_order(client, "order-1", 7, now_kst=INSIDE_WINDOW)
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.filter_map == {"id": "order-1"}
    assert set(call.payload) == {"requested_quantity", "last_edited_at"}
    assert call.payload["requested_quantity"] == 7


def test_edit_order_translates_db_trigger_rejection():
    """
    이미 배치가 집어간 주문은 DB 트리거가 거절합니다. 그 거절을 삼키지 않고,
    Postgres 원문 대신 **사람이 읽을 한국어**로 바꿔 올립니다(§0-1 + §0-3-4).
    """
    trigger_error = Exception(
        'duel_orders: 이미 filled(으)로 종결된 주문은 수정할 수 없습니다(배치 처리 이후 변경 금지)'
    )
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): trigger_error})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.edit_order(client, "order-1", 7, now_kst=INSIDE_WINDOW)
    message = str(excinfo.value)
    assert "이미 처리가 끝난 주문" in message
    assert "duel_orders:" not in message, "DB 내부 표식을 화면 문구에 그대로 싣지 않습니다"


def test_edit_order_missing_row_is_not_a_silent_success():
    """0행 갱신(없는 주문 / 남의 주문)을 성공으로 넘기지 않습니다."""
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): []})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.edit_order(client, "order-x", 7, now_kst=INSIDE_WINDOW)
    assert "찾지 못했" in str(excinfo.value)


def test_edit_and_cancel_are_blocked_outside_window():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.edit_order(client, "order-1", 7, now_kst=OUTSIDE_WINDOW)
    with pytest.raises(DuelDbError):
        duel_db.cancel_order(client, "order-1", now_kst=OUTSIDE_WINDOW)
    assert client.calls == []


def test_cancel_order_keeps_the_row_with_a_reason():
    """
    취소는 **삭제가 아니라 상태 기록**입니다. 사유 문장이 반드시 남습니다
    (스키마에 delete 정책이 없는 것과 같은 이유 — 조용히 사라지는 주문 금지).
    """
    client = FakeClient()
    assert duel_db.cancel_order(client, "order-1", now_kst=INSIDE_WINDOW) is None
    assert client.calls_for(duel_db.ORDERS_TABLE, "delete") == []
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.payload["status"] == "cancelled"
    assert call.payload["fail_reason"].strip()


def test_cancel_order_accepts_custom_reason():
    client = FakeClient()
    duel_db.cancel_order(client, "order-1", reason="종목을 잘못 골랐습니다",
                         now_kst=INSIDE_WINDOW)
    assert client.calls[0].payload["fail_reason"] == "종목을 잘못 골랐습니다"


# =============================================================================
# 3. A 절 — 조회가 맞는 표·맞는 필터로 가는지
# =============================================================================
def test_fetch_my_accounts_filters_by_user():
    client = FakeClient(responses={(duel_db.ACCOUNTS_TABLE, "select"): [{"id": "acc-1"}]})
    rows = duel_db.fetch_my_accounts(client, "user-1")
    call = client.only_call(duel_db.ACCOUNTS_TABLE, "select")
    assert call.filter_map == {"user_id": "user-1"}
    assert rows == [{"id": "acc-1"}]


def test_fetch_my_positions_and_orders_filter_by_account():
    client = FakeClient()
    duel_db.fetch_my_positions(client, "acc-1")
    duel_db.fetch_my_orders(client, "acc-1")
    positions = client.only_call(duel_db.POSITIONS_TABLE, "select")
    orders = client.only_call(duel_db.ORDERS_TABLE, "select")
    assert positions.filter_map == {"account_id": "acc-1"}
    assert orders.filter_map == {"account_id": "acc-1"}
    assert orders.orders == [("saved_at", True)], "주문 내역은 최신순"


def test_fetch_my_snapshots_applies_date_range():
    client = FakeClient()
    duel_db.fetch_my_snapshots(client, "acc-1",
                               start_date=date(2026, 8, 1), end_date="2026-08-19")
    call = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "select")
    assert ("gte", "snapshot_date", "2026-08-01") in call.filters
    assert ("lte", "snapshot_date", "2026-08-19") in call.filters
    assert call.filter_map["account_id"] == "acc-1"
    assert call.orders == [("snapshot_date", False)], "TWR 입력은 오래된 순이어야 합니다"


def test_fetch_my_snapshots_output_feeds_compute_twr_directly():
    """조회 결과를 그대로 규칙 함수에 넘길 수 있어야 합니다(이 파일은 수익률을 계산하지 않음)."""
    rows = [
        {"snapshot_date": "2026-08-17", "total_value": 10_000_000, "cash_flow_amount": 0},
        {"snapshot_date": "2026-08-18", "total_value": 10_100_000, "cash_flow_amount": 0},
    ]
    client = FakeClient(responses={(duel_db.DAILY_SNAPSHOTS_TABLE, "select"): rows})
    fetched = duel_db.fetch_my_snapshots(client, "acc-1")
    result = duel_rules.compute_twr(fetched)
    assert result["status"] == "OK"
    assert result["twr_pct"] == pytest.approx(1.0, abs=1e-9)


def test_sum_cash_balance_refuses_broken_amounts():
    """'잔고를 모르는 상태'를 '잔고 0'으로 바꿔 보여주지 않습니다."""
    assert duel_db.sum_cash_balance([{"amount": 10_000_000}, {"amount": -1_500_000}]) == 8_500_000
    with pytest.raises(DuelDbError):
        duel_db.sum_cash_balance([{"amount": None}])


# =============================================================================
# 4. A 절 — 사용자가 할 수 **없는** 일은 코드 경로 자체가 없어야 합니다
#    (스키마 §9: 포지션·원장·스냅샷은 사용자에게 select 하나뿐)
# =============================================================================
def test_user_write_functions_do_not_accept_fill_or_balance_params():
    """
    사용자 경로의 쓰기 함수가 체결 결과·잔고·귀속 거래일을 **인자로 받지 않는지**.
    금지 목록은 `utils/duel_db.py` 안에 단일 출처로 있고, 여기서는 그 자기 점검을 돌립니다.
    나중에 누가 `save_order(..., filled_price=...)` 를 추가하면 이 테스트가 먼저 실패합니다.
    """
    assert duel_db.user_write_signature_violations() == []
    # 금지 목록 자체가 조용히 비워지는 것도 막습니다.
    assert "filled_price" in duel_db.FORBIDDEN_USER_WRITE_PARAMS
    # 🔴 `user_id` 도 금지입니다(2026-08-20 추가) — 사용자 경로의 쓰기 함수는 "누구의
    #    것인지"를 인자로 받지 않습니다. 대상은 로그인 세션(auth.uid()) 아니면 소유권이
    #    이미 확인된 계좌·주문 ID 뿐입니다.
    assert "user_id" in duel_db.FORBIDDEN_USER_WRITE_PARAMS
    # 🔴 2026-08-21 `save_sell_order` 추가 — 리밸런싱 매도도 **사용자 경로의 쓰기**이므로
    #    같은 금지 목록의 적용을 받아야 합니다(보유 수량·창 번호는 받지만 체결 결과·잔고·
    #    귀속 거래일은 여전히 인자로 받지 않습니다).
    assert set(duel_db.USER_WRITE_FUNCTIONS) == {
        "opt_in", "save_order", "save_sell_order", "edit_order", "cancel_order",
        "save_consent"}


def _module_ast():
    source = (REPO_ROOT / "utils" / "duel_db.py").read_text(encoding="utf-8")
    return ast.parse(source), source


def _write_targets(function_node):
    """
    함수 안에서 `<...>.table(X).insert/update/upsert/delete(...)` 로 쓰는 표 X 를 모읍니다.
    (체이닝의 어느 위치에 있든 `.table(...)` 까지 거슬러 올라갑니다.)
    """
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


def test_user_facing_functions_only_write_orders_and_consent():
    """
    A 절 쓰기 함수가 **duel_orders / duel_public_consent 이외의 표에 쓰지 않는지**.

    스키마 §9 가 사용자에게 insert/update 를 준 표는 이 둘뿐입니다. 여기에 원장이나 포지션
    쓰기가 생기면 그건 곧 "anon key 로 가상 현금을 찍을 수 있다"는 뜻이고, 그 값은 스냅샷 →
    공개 순위표로 흘러갑니다(§0-3-9).
    """
    tree, _source = _module_ast()
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for name in duel_db.USER_WRITE_FUNCTIONS:
        targets = _write_targets(functions[name])
        assert targets <= {"ORDERS_TABLE", "CONSENT_TABLE"}, \
            f"{name} 이 사용자 권한 밖의 표에 씁니다: {targets}"


def test_user_facing_section_does_not_touch_service_role():
    """
    A 절 본문에 service_role 관련 이름이 등장하지 않는지(격리 회귀 고정).
    화면 코드가 부르는 함수들이 배치 키를 필요로 하기 시작하면, 앱 서버에 그 키를 넣게 되고
    그 순간 이 모듈의 RLS 는 전부 장식이 됩니다(§0-3-8).
    """
    _tree, source = _module_ast()
    start = source.index("#  A 절 —")
    end = source.index("#  B 절 —")
    section = source[start:end]
    for forbidden in ("service_role", "SERVICE_ROLE_KEY_ENV", "create_service_client"):
        assert forbidden not in section, f"A 절에 {forbidden} 이 있습니다"


def test_opt_in_does_not_reach_for_the_batch_key():
    """
    🔴 `opt_in()` 전용 격리 회귀 고정 (2026-08-20 추가).

    이 함수는 "사용자 세션으로 시드머니를 넣는" 함수라, 앞으로 누군가 "그냥 배치 키로
    부르는 게 편하지 않나"라고 고칠 위험이 이 파일에서 가장 큰 자리입니다. 그 순간 사용자가
    접속하는 앱 서버에 **모든 사용자의 원장에 돈을 쓸 수 있는 키**가 필요해지고, 이 모듈의
    RLS 는 전부 장식이 됩니다(§0-3-8 / `utils/report_db.py` 이후의 격리 규율).

    위 `test_user_facing_section_does_not_touch_service_role()` 이 A 절 전체를 문자열로 보는
    것과 달리, 여기서는 **이 함수의 본문만** AST 로 떼어내 봅니다 — 절 구분 주석이 나중에
    바뀌거나 함수가 다른 자리로 옮겨져도 검사가 함께 따라가도록.
    """
    tree, source = _module_ast()
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    node = functions["opt_in"]
    body = ast.get_source_segment(source, node)

    for forbidden in ("service_role", "SERVICE_ROLE_KEY_ENV", "create_service_client",
                      "_read_service_env", "os.environ", "getenv"):
        assert forbidden not in body, f"opt_in 이 {forbidden} 을(를) 건드립니다"

    # 표에 직접 쓰지도 않습니다(원장·계좌 쓰기는 전부 DB 안의 RPC 가 합니다).
    assert _write_targets(node) == set(), "opt_in 이 표에 직접 씁니다"

    # 부르는 것은 RPC 하나뿐인지(이름 상수를 그대로 쓰는지).
    rpc_calls = [child for child in ast.walk(node)
                 if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                 and child.func.attr == "rpc"]
    assert len(rpc_calls) == 1, "opt_in 의 RPC 호출은 정확히 1회여야 합니다"
    assert isinstance(rpc_calls[0].args[0], ast.Name) \
        and rpc_calls[0].args[0].id == "OPT_IN_RPC", \
        "RPC 이름은 문자열을 흩뿌리지 않고 OPT_IN_RPC 상수 하나로 씁니다"


def test_publish_tables_are_only_written_by_the_batch_section():
    """
    🔴 2026-08-20 (순위표 화면 라운드) **의도적으로 다시 조정한** 테스트 — 그 이력을 남깁니다.

    · 5단계 백엔드 이전: "A 절이 발행표를 한 글자도 언급하지 않는다".
    · 5단계 백엔드 라운드: 위와 같되 "읽든 쓰든" 전부 B 절이어야 한다로 교체.
    · **지금(화면 라운드)**: 순위표 화면은 로그인한 **일반 사용자**가 보는 화면이고, 스키마
      §9-7 은 그 두 표에 `authenticated` 의 **select 를 이미 허용**하고 있습니다. 그 조회를
      B 절(배치)에 두면 화면이 배치 함수를 부르게 되고, 그 순간 앱 서버에 service_role 키가
      필요해집니다 — §0-3-8 이 막으려는 바로 그 사고입니다. 그래서 **읽기만** A 절로
      내려왔습니다(`fetch_public_leaderboard*` / `fetch_public_holdings_for_nickname`).

    지금 고정하는 불변식(약해진 것이 아니라 **더 정확해진 것**):
      ① A 절은 발행표에 **쓰지 않습니다** — insert/update/upsert/delete 가 한 번도 없어야
         합니다. (스키마 §9-8 은 그 정책을 아무에게도 주지 않았으므로, 앱에 그런 코드가
         있다면 그건 "권한 오류를 만드는 코드"이거나 누군가 RLS 를 열려는 신호입니다.)
      ② A 절은 **체급 배정표(`duel_bracket_assignments`)를 아예 건드리지 않습니다** —
         이 표는 읽기도 배치 몫입니다(§8-3 은 service_role 에도 update/delete 를 안 줬고,
         화면이 체급을 알아야 할 이유가 없습니다. 체급은 발행표 행에 이미 들어 있습니다).
      ③ 발행표 이름 **문자열**은 여전히 §0 의 상수 두 줄에만 있습니다.
    """
    tree, source = _module_ast()
    a_start = source.index("#  A 절 —")
    b_start = source.index("#  B 절 —")
    a_section = source[a_start:b_start]

    # ② 체급 배정표는 A 절에서 읽지도 않습니다.
    for table in ("duel_bracket_assignments", "BRACKET_ASSIGNMENTS_TABLE"):
        assert table not in a_section, f"A 절이 발행 인프라({table})를 건드립니다"

    # ① A 절 함수 중 발행표에 **쓰는** 함수가 하나도 없어야 합니다.
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for name, node in functions.items():
        marker = f"def {name}("
        if not (a_start <= source.index(marker) < b_start):
            continue
        targets = _write_targets(node)
        assert not ({"PUBLIC_LEADERBOARD_TABLE", "PUBLIC_HOLDINGS_TABLE",
                     "BRACKET_ASSIGNMENTS_TABLE"} & targets), \
            f"A 절 함수 {name} 이 발행표에 씁니다: {targets}"

    # A 절이 발행표를 만지는 방법은 select 하나뿐이라는 것을 문자열로도 한 번 더 고정합니다.
    for forbidden in (".insert(", ".update(", ".upsert(", ".delete()"):
        publish_writes = [line for line in a_section.splitlines()
                          if forbidden in line and ("PUBLIC_LEADERBOARD_TABLE" in line
                                                    or "PUBLIC_HOLDINGS_TABLE" in line)]
        assert not publish_writes, f"A 절이 발행표에 {forbidden} 를 씁니다: {publish_writes}"

    # ③ 표 이름 문자열은 §0 의 상수 두 줄에만 있어야 합니다(문자열을 흩뿌리지 않기).
    literals = [line for line in source.splitlines()
                if '"duel_public_leaderboard"' in line or '"duel_public_holdings"' in line]
    assert len(literals) == 2, f"발행표 이름 문자열이 상수 밖에도 있습니다: {literals}"


# =============================================================================
# 5. A 절 — 공개 동의 (5-2)
# =============================================================================
def test_save_consent_rejects_final_confirm_without_all_five():
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_consent(client, "acc-1", consent_rank=True, consent_return=True,
                             consent_holdings=True, consent_quantity=True,
                             consent_buy_amount=False, final_confirmed=True)
    assert "consent_buy_amount" in str(excinfo.value)
    assert client.calls == []


def test_save_consent_final_confirm_records_time():
    client = FakeClient()
    duel_db.save_consent(client, "acc-1", consent_rank=True, consent_return=True,
                         consent_holdings=True, consent_quantity=True,
                         consent_buy_amount=True, final_confirmed=True)
    call = client.only_call(duel_db.CONSENT_TABLE, "upsert")
    assert call.options["on_conflict"] == "account_id"
    assert call.payload["final_confirmed"] is True
    assert call.payload["final_confirmed_at"], "최종확인 시각이 없는 최종확인은 만들지 않습니다"


def test_save_consent_unsetting_final_clears_the_timestamp():
    client = FakeClient()
    duel_db.save_consent(client, "acc-1", final_confirmed=False)
    # 2026-08-20 — save_consent 가 저장 직전에 철회 이력을 한 번 읽으므로(5-8-2 재동의
    # 차단), `calls[0]` 가 아니라 **upsert 질의**를 집어 봅니다.
    assert client.only_call(duel_db.CONSENT_TABLE,
                            "upsert").payload["final_confirmed_at"] is None


def test_real_principal_consent_is_independent_of_the_five():
    """
    실제 '내 성적표' 매입총합 사용 동의는 5개와 **완전히 별개**입니다(5-2-4).
    5개가 전부 꺼져 있어도 이것만 켤 수 있어야 하고, 그 반대도 마찬가지입니다.
    """
    client = FakeClient()
    duel_db.save_consent(client, "acc-1", consent_real_principal_bracket=True)
    payload = client.only_call(duel_db.CONSENT_TABLE, "upsert").payload
    assert payload["consent_real_principal_bracket"] is True
    for flag in duel_db.CONSENT_ITEM_FLAGS:
        assert flag not in payload, "독립 동의가 다른 항목을 함께 켜면 안 됩니다"

    client = FakeClient()
    duel_db.save_consent(client, "acc-1", consent_rank=True, consent_return=True,
                         consent_holdings=True, consent_quantity=True,
                         consent_buy_amount=True, final_confirmed=True)
    assert "consent_real_principal_bracket" not in \
        client.only_call(duel_db.CONSENT_TABLE, "upsert").payload
    assert duel_db.CONSENT_REAL_PRINCIPAL_FLAG not in duel_db.CONSENT_ITEM_FLAGS


def test_save_consent_rejects_unknown_flag():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.save_consent(client, "acc-1", consent_rankk=True)   # 오타
    with pytest.raises(DuelDbError):
        duel_db.save_consent(client, "acc-1", consent_rank="yes")   # bool 아님
    assert client.calls == []


# =============================================================================
# 6. B 절 — 옵트인(계좌 3개 + 시드) 멱등성 (2-1)
# =============================================================================
def _accounts(user_id="user-1"):
    return [{"id": f"acc-{index}", "user_id": user_id, "window_type": window}
            for index, window in enumerate(("M1", "M3", "M6"), start=1)]


def test_create_duel_accounts_creates_three_accounts_and_three_seed_rows():
    client = FakeClient(responses={
        # ① 기존 계좌 조회 → 없음, ② 개설 후 조회 → 3개
        (duel_db.ACCOUNTS_TABLE, "select"): sequence([], _accounts()),
        (duel_db.LEDGER_TABLE, "select"): [],   # 시드 없음
    })
    accounts = duel_db.create_duel_accounts_for_user(client, "user-1",
                                                     anchor_date=date(2026, 8, 19))
    assert [row["window_type"] for row in accounts] == ["M1", "M3", "M6"]

    account_insert = client.only_call(duel_db.ACCOUNTS_TABLE, "insert")
    assert len(account_insert.rows) == 3, "계좌 3개는 한 번의 insert 로"
    assert {row["window_type"] for row in account_insert.rows} == {"M1", "M3", "M6"}
    # 금액의 단일 출처는 앱 상수입니다(DB default 를 두지 않은 이유 — 스키마 §1).
    assert all(row["seed_amount"] == duel_rules.SEED_AMOUNT_KRW for row in account_insert.rows)

    seed_insert = client.only_call(duel_db.LEDGER_TABLE, "insert")
    assert len(seed_insert.rows) == 3, "시드 3행도 한 번의 insert 로"
    assert all(row["event_type"] == "seed" for row in seed_insert.rows)
    assert all(row["amount"] == duel_rules.SEED_AMOUNT_KRW for row in seed_insert.rows)
    assert all(row["event_date"] == "2026-08-19" for row in seed_insert.rows)


def test_create_duel_accounts_is_idempotent_on_second_call():
    """두 번째 호출은 **아무것도 만들지 않고** 조용히 기존 계좌를 돌려줍니다."""
    existing = _accounts()
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): existing,
        (duel_db.LEDGER_TABLE, "select"): [{"account_id": row["id"]} for row in existing],
    })
    accounts = duel_db.create_duel_accounts_for_user(client, "user-1",
                                                     anchor_date=date(2026, 8, 19))
    assert len(accounts) == 3
    assert client.calls_for(duel_db.ACCOUNTS_TABLE, "insert") == [], "계좌를 또 만들면 안 됩니다"
    assert client.calls_for(duel_db.LEDGER_TABLE, "insert") == [], "시드를 두 번 주면 안 됩니다"


def test_create_duel_accounts_survives_unique_conflict():
    """
    동시 실행으로 유니크 제약에 걸려도 예외를 터뜨리지 않습니다 — 인덱스가 제 일을 한 것이고
    (중복 계좌·중복 시드는 만들어지지 않았습니다), 다시 읽어 정상 상태를 돌려줍니다.
    """
    conflict = Exception(
        'duplicate key value violates unique constraint "duel_accounts_user_window_unique"')
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): sequence([], _accounts()),
        (duel_db.ACCOUNTS_TABLE, "insert"): conflict,
        (duel_db.LEDGER_TABLE, "select"): [{"account_id": "acc-1"},
                                           {"account_id": "acc-2"},
                                           {"account_id": "acc-3"}],
    })
    accounts = duel_db.create_duel_accounts_for_user(client, "user-1",
                                                     anchor_date=date(2026, 8, 19))
    assert len(accounts) == 3
    assert client.calls_for(duel_db.LEDGER_TABLE, "insert") == []


def test_create_duel_accounts_reraises_unrelated_errors():
    """중복 키가 아닌 오류까지 삼키면 진짜 사고가 조용히 묻힙니다(§0-1)."""
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): sequence([], []),
        (duel_db.ACCOUNTS_TABLE, "insert"): Exception("connection reset by peer"),
    })
    with pytest.raises(DuelDbError):
        duel_db.create_duel_accounts_for_user(client, "user-1", anchor_date=date(2026, 8, 19))


def test_create_duel_accounts_fills_only_missing_window_types():
    """M1 만 있는 계정에는 M3·M6 만 새로 만듭니다(있는 걸 다시 만들지 않음)."""
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): sequence(_accounts()[:1], _accounts()),
        (duel_db.LEDGER_TABLE, "select"): [{"account_id": "acc-1"}],
    })
    duel_db.create_duel_accounts_for_user(client, "user-1", anchor_date=date(2026, 8, 19))
    created = client.only_call(duel_db.ACCOUNTS_TABLE, "insert").rows
    assert {row["window_type"] for row in created} == {"M3", "M6"}
    seeded = client.only_call(duel_db.LEDGER_TABLE, "insert").rows
    assert {row["account_id"] for row in seeded} == {"acc-2", "acc-3"}


# =============================================================================
# 7. B 절 — 정기 입금 (2-2) · §0-3-2 집합 연산 회귀 고정
# =============================================================================
def _active_accounts(count):
    return [{"id": f"acc-{index}", "user_id": f"user-{index}", "window_type": "M1",
             "status": "active"} for index in range(count)]


@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_apply_monthly_deposits_is_one_insert_regardless_of_account_count(account_count):
    """
    🔴 §0-3-2 회귀 테스트(작업지시서 2-7 이 명시적으로 요구한 것).

    계좌가 3개든 900개든 **질의 수는 그대로**여야 합니다: 활성 계좌 조회 1 + 중복 조회 1 +
    insert 1. 사용자별 루프를 돌면 사용자가 10명일 때는 잘 돌아가고, 늘어난 뒤에 터집니다.
    (900행은 CHUNK_SIZE(200)로 잘려 insert 가 5번이 됩니다 — 그건 요청 크기를 자르는 것이지
     계좌마다 부르는 것이 아니므로, insert 호출 수가 **계좌 수가 아니라 청크 수**인지를 봅니다.)
    """
    accounts = _active_accounts(account_count)
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): accounts,
        (duel_db.LEDGER_TABLE, "select"): [],
    })
    inserted = duel_db.apply_monthly_deposits(client, date(2026, 9, 10))

    assert inserted == account_count
    assert len(client.calls_for(duel_db.ACCOUNTS_TABLE, "select")) == 1
    assert len(client.calls_for(duel_db.LEDGER_TABLE, "select")) == 1
    expected_chunks = -(-account_count // duel_db.CHUNK_SIZE)
    inserts = client.calls_for(duel_db.LEDGER_TABLE, "insert")
    assert len(inserts) == expected_chunks
    assert sum(len(call.rows) for call in inserts) == account_count
    assert len(client.calls) == 2 + expected_chunks


def test_apply_monthly_deposits_payload_matches_the_rules_constant():
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): _active_accounts(3),
        (duel_db.LEDGER_TABLE, "select"): [],
    })
    duel_db.apply_monthly_deposits(client, "2026-09-10")
    rows = client.only_call(duel_db.LEDGER_TABLE, "insert").rows
    assert all(row["amount"] == duel_rules.MONTHLY_DEPOSIT_KRW for row in rows)
    assert all(row["event_type"] == "monthly_deposit" for row in rows)
    # 10일이 주말·공휴일이어도 그대로 10일자입니다(시장 이벤트가 아니라 현금 이벤트 — 2-2-4).
    assert all(row["event_date"] == "2026-09-10" for row in rows)


def test_apply_monthly_deposits_second_run_inserts_nothing():
    """멱등성: 배치가 두 번 돌아도 같은 달 입금이 두 번 들어가지 않습니다(2-2-6)."""
    accounts = _active_accounts(3)
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): accounts,
        (duel_db.LEDGER_TABLE, "select"): [{"account_id": row["id"]} for row in accounts],
    })
    assert duel_db.apply_monthly_deposits(client, date(2026, 9, 10)) == 0
    assert client.calls_for(duel_db.LEDGER_TABLE, "insert") == []


def test_apply_monthly_deposits_fills_only_the_accounts_that_missed_it():
    accounts = _active_accounts(3)
    client = FakeClient(responses={
        (duel_db.ACCOUNTS_TABLE, "select"): accounts,
        (duel_db.LEDGER_TABLE, "select"): [{"account_id": "acc-0"}],
    })
    assert duel_db.apply_monthly_deposits(client, date(2026, 9, 10)) == 2
    rows = client.only_call(duel_db.LEDGER_TABLE, "insert").rows
    assert {row["account_id"] for row in rows} == {"acc-1", "acc-2"}


def test_apply_monthly_deposits_with_no_accounts_sends_no_write():
    client = FakeClient(responses={(duel_db.ACCOUNTS_TABLE, "select"): []})
    assert duel_db.apply_monthly_deposits(client, date(2026, 9, 10)) == 0
    assert client.calls_for(duel_db.LEDGER_TABLE) == []


# =============================================================================
# 8. B 절 — 체결 (2-4-6)
# =============================================================================
def test_fetch_pending_orders_for_fill_is_one_query_ordered_by_saved_at():
    """
    FIFO 예수금 배정(`duel_rules.allocate_pending_orders`)의 전제가 저장 순서라,
    조회 자체가 `saved_at` 오름차순이어야 합니다. 전체 계좌를 **한 번에** 읽습니다.
    """
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "select"): [{"id": "o1"}]})
    duel_db.fetch_pending_orders_for_fill(client, date(2026, 8, 20))
    call = client.only_call(duel_db.ORDERS_TABLE, "select")
    assert call.filter_map == {"status": "pending", "target_date": "2026-08-20"}
    assert call.orders == [("saved_at", False)]
    assert len(client.calls) == 1


def test_record_order_fill_persists_exactly_what_the_rules_computed():
    """
    체결 계산은 `duel_rules.calculate_fill()` 이 하고, 이 파일은 그 결과를 그대로 적습니다.
    (여기서 floor 나눗셈을 다시 하면 규칙이 두 곳에 생깁니다.)

    ⚠️ 2026-08-29 재감사 L-4 — 단건 래퍼 `record_order_fill()` 은 **비테스트 호출부가 0**
       이라 삭제됐습니다. 실제로 쓰이는 `record_order_fills()` 로 같은 것을 검사합니다.
    """
    outcome = duel_rules.calculate_fill(10, 70_000, 500_000)   # 7주만 체결되는 부분체결
    assert outcome["status"] == "partially_filled" and outcome["filled_quantity"] == 7

    client = FakeClient()
    duel_db.record_order_fills(client, [{
        "id": "order-1", "status": outcome["status"],
        "filled_quantity": outcome["filled_quantity"], "filled_price": 70_000,
        "filled_amount": outcome["filled_amount"], "filled_date": date(2026, 8, 20),
        "fail_reason": outcome["fail_reason"],
    }])
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.payload["status"] == "partially_filled"
    assert call.payload["filled_quantity"] == 7
    assert call.payload["filled_amount"] == outcome["filled_amount"]
    assert call.payload["filled_date"] == "2026-08-20"
    assert "7주" in call.payload["fail_reason"] and "10주" in call.payload["fail_reason"]
    # 배치도 pending 행만 집습니다(재실행 안전 + 종결된 주문 덮어쓰기 방지).
    assert call.filter_map == {"id": "order-1", "status": "pending"}


def test_record_order_fill_requires_the_trading_day():
    """체결일을 모르면 오늘 날짜를 지어 넣지 않고 거절합니다(§0-1)."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.record_order_fills(client, [{
            "id": "order-1", "status": "filled", "filled_quantity": 3,
            "filled_price": 70_000, "filled_amount": 210_000}])
    assert "함께" in str(excinfo.value)
    assert client.calls == []


def test_record_order_fill_requires_reason_for_non_filled_status():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.record_order_fills(client, [{
            "id": "order-1", "status": "expired", "filled_quantity": 0}])
    with pytest.raises(DuelDbError):
        duel_db.record_order_fills(client, [{
            "id": "order-1", "status": "pending", "filled_quantity": None}])
    assert client.calls == []


def test_record_order_fill_writes_empty_fill_fields_for_expired_orders():
    """0주 체결은 '0원에 체결'이 아니라 '체결 없음'입니다 — 네 필드 모두 NULL."""
    client = FakeClient()
    duel_db.record_order_fills(client, [{
        "id": "order-1", "status": "expired", "filled_quantity": 0,
        "filled_price": 70_000, "filled_amount": 0,
        "filled_date": date(2026, 8, 20),
        "fail_reason": "예수금이 부족해 1주도 체결되지 않았습니다."}])
    payload = client.only_call(duel_db.ORDERS_TABLE, "update").payload
    assert payload["filled_quantity"] is None
    assert payload["filled_price"] is None
    assert payload["filled_amount"] is None
    assert payload["filled_date"] is None
    assert payload["fail_reason"]


def test_record_buy_ledger_entry_flips_the_sign_once():
    """매수 원장은 음수. 부호를 뒤집는 자리는 이 파일 한 군데뿐이어야 합니다.

    ⚠️ 2026-08-29 재감사 L-4 — 단건 래퍼 `record_buy_ledger_entry()` 는 삭제됐습니다
       (비테스트 호출부 0건). 실제로 쓰이는 `record_buy_ledger_entries()` 로 검사합니다.
    """
    client = FakeClient()
    duel_db.record_buy_ledger_entries(client, [{
        "account_id": "acc-1", "order_id": "order-1",
        "filled_amount": 490_000, "event_date": date(2026, 8, 20)}])
    row = client.only_call(duel_db.LEDGER_TABLE, "insert").rows[0]
    assert row["amount"] == -490_000
    assert row["event_type"] == "buy"
    assert row["order_id"] == "order-1"      # buy 행에는 주문 링크가 반드시 필요(CHECK)
    assert row["event_date"] == "2026-08-20"


def test_record_buy_ledger_entries_is_a_single_insert():
    client = FakeClient()
    entries = [{"account_id": f"acc-{i}", "order_id": f"o-{i}",
                "filled_amount": 1000 * (i + 1), "event_date": date(2026, 8, 20)}
               for i in range(25)]
    assert duel_db.record_buy_ledger_entries(client, entries) == 25
    assert len(client.calls_for(duel_db.LEDGER_TABLE, "insert")) == 1


def test_record_buy_ledger_entry_rejects_zero_amount():
    """체결금액 0원짜리 원장 행은 만들지 않습니다(현금이 움직이지 않았으므로)."""
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.record_buy_ledger_entries(client, [{
            "account_id": "acc-1", "order_id": "order-1",
            "filled_amount": 0, "event_date": date(2026, 8, 20)}])
    assert client.calls == []


def test_upsert_positions_rejects_duplicate_conflict_keys():
    """
    같은 (계좌, 종목)이 한 요청에 두 번 들어오면 PostgREST 가 요청 전체를 거절합니다.
    미리 잡아 어느 키가 겹쳤는지 알립니다(report_db 의 같은 방어와 짝).
    """
    client = FakeClient()
    rows = [{"account_id": "acc-1", "ticker": "005930", "quantity": 1, "avg_cost": 1},
            {"account_id": "acc-1", "ticker": "005930", "quantity": 2, "avg_cost": 2}]
    with pytest.raises(DuelDbError):
        duel_db.upsert_positions(client, rows)
    assert client.calls == []


def test_upsert_positions_is_one_call_for_many_rows():
    client = FakeClient()
    rows = [{"account_id": f"acc-{i}", "ticker": "005930", "quantity": 1, "avg_cost": 1}
            for i in range(30)]
    duel_db.upsert_positions(client, rows)
    assert len(client.calls_for(duel_db.POSITIONS_TABLE, "upsert")) == 1


# =============================================================================
# 8-B. B 절 — 매도 정산 RPC · 최초 보유일 기록 (2026-08-21)
# =============================================================================
def test_settle_sell_positions_calls_the_rpc_with_only_three_fields():
    """
    🔴 매도 정산은 표 upsert 가 아니라 **RPC** 입니다 — `duel_positions` 의 수량 감소는
    트리거가 막고, 예외는 같은 트랜잭션에서 `duel.settled_sell` 이 켜진 경우뿐인데
    PostgREST 로는 세션 변수를 앞세울 수 없기 때문입니다(스키마 §9-11).

    보내는 필드는 셋뿐입니다 — `avg_cost` 를 보내지 않는 것이 규약의 일부입니다(매도는
    잔여 주식의 매입단가를 바꾸지 않으므로, 정산 경로로 원가를 다시 쓰는 길을 없앱니다).

    ⚠️ 2026-08-29 재감사 H-4 — RPC **앞에** 현재 수량을 읽는 select 가 하나 붙었습니다
       (이미 반영된 행을 다시 보내면 RPC 가 예외를 내 재시도를 막기 때문). 그래서
       포지션 표에 대한 호출은 **select 만** 있고 쓰기(upsert/update)는 여전히 0 입니다.
    """
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 10.0}]})
    settled = duel_db.settle_sell_positions(client, [
        {"account_id": "acc-1", "ticker": "005930", "stock_name": "삼성전자",
         "quantity": 6, "avg_cost": 70_000.0},
    ])

    call = client.only_call(duel_db.SETTLE_SELL_RPC, "rpc")
    assert call.op == "rpc"
    assert call.table == "duel_settle_sell_positions"
    assert call.payload == {"p_rows": [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 6.0}]}
    assert settled == 1
    # 포지션 표에 **쓰지** 않습니다(그 경로로는 수량 감소가 통과할 수 없습니다).
    assert [c.op for c in client.calls_for(duel_db.POSITIONS_TABLE)] == ["select"]


def test_settle_sell_positions_skips_rows_already_settled_by_an_earlier_attempt():
    """
    🔴 2026-08-29 재감사 H-4 — 재실행 안전. 이전 시도에서 이미 목표 수량까지 줄어든 행을
    다시 보내면 DB 함수가 "수량이 줄지 않았다"며 예외를 내고, 그 예외가 그날 밤 전체를
    멈춥니다(= 재시도가 불가능해집니다). 호출 직전 현재 수량을 읽어 걸러 냅니다.
    """
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 6.0},   # 이미 반영됨
        {"account_id": "acc-1", "ticker": "000660", "quantity": 10.0},  # 아직 안 됨
    ]})
    settled = duel_db.settle_sell_positions(client, [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 6},
        {"account_id": "acc-1", "ticker": "000660", "quantity": 4},
    ])
    assert settled == 1
    call = client.only_call(duel_db.SETTLE_SELL_RPC, "rpc")
    assert call.payload == {"p_rows": [
        {"account_id": "acc-1", "ticker": "000660", "quantity": 4.0}]}


def test_settle_sell_positions_sends_no_rpc_when_everything_is_already_settled():
    """전부 이미 반영돼 있으면 RPC 자체를 보내지 않고 0 을 돌려줍니다."""
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 6.0}]})
    assert duel_db.settle_sell_positions(
        client, [{"account_id": "acc-1", "ticker": "005930", "quantity": 6}]) == 0
    assert client.calls_for(duel_db.SETTLE_SELL_RPC, "rpc") == []


def test_settle_sell_positions_sends_one_call_for_many_rows():
    """§0-3-2 — 계좌마다 부르지 않고 그날 매도 정산 전체를 한 번에 보냅니다."""
    rows = [{"account_id": f"acc-{index}", "ticker": "005930", "quantity": 1}
            for index in range(1, 51)]
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": row["account_id"], "ticker": "005930", "quantity": 5.0}
        for row in rows]})
    assert duel_db.settle_sell_positions(client, rows) == 50
    assert len(client.calls_for(duel_db.SETTLE_SELL_RPC, "rpc")) == 1
    # 사전 조회(H-4)도 **한 번**입니다 — 계좌마다 읽지 않습니다(§0-3-2).
    assert len(client.calls_for(duel_db.POSITIONS_TABLE, "select")) == 1


def test_settle_sell_positions_sends_nothing_for_an_empty_list():
    """매도가 없는 밤에는 질의 자체를 보내지 않습니다."""
    client = FakeClient()
    assert duel_db.settle_sell_positions(client, []) == 0
    assert client.calls == []


def test_settle_sell_positions_refuses_duplicate_keys_and_missing_values():
    """
    같은 (계좌, 종목)이 두 번 들어오면 어느 쪽이 맞는지 알 수 없으므로 **먼저 잡습니다**
    (`upsert_positions()` 와 같은 방어). 수량이 비어 있어도 0 으로 메우지 않습니다.
    """
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.settle_sell_positions(client, [
            {"account_id": "acc-1", "ticker": "005930", "quantity": 1},
            {"account_id": "acc-1", "ticker": "005930", "quantity": 2},
        ])
    with pytest.raises(DuelDbError):
        duel_db.settle_sell_positions(client, [
            {"account_id": "acc-1", "ticker": "005930", "quantity": None}])
    assert client.calls == []


def test_settle_sell_positions_allows_a_zero_quantity():
    """전량 매도(잔여 0주)는 정상 상태입니다 — 여기서 막히면 안 됩니다."""
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 5.0}]})
    duel_db.settle_sell_positions(client, [
        {"account_id": "acc-1", "ticker": "005930", "quantity": 0}])
    assert client.only_call(duel_db.SETTLE_SELL_RPC, "rpc").payload["p_rows"][0]["quantity"] == 0


def test_sell_ledger_rows_are_positive_and_buy_rows_stay_negative():
    """
    부호를 정하는 자리는 원장 계층 **한 곳**입니다. 매수는 음수, 매도는 양수(입금과 같은
    방향)이고, 호출부는 둘 다 체결금액을 **양수로** 넘깁니다.
    """
    client = FakeClient()
    written = duel_db.record_buy_ledger_entries(client, [
        {"account_id": "acc-1", "order_id": "o-buy", "filled_amount": 30_000.0,
         "event_date": "2026-08-20", "memo": "005930 3주 체결"},
        {"account_id": "acc-1", "order_id": "o-sell", "event_type": "sell",
         "filled_amount": 48_000.0, "event_date": "2026-08-20", "memo": "000660 4주 매도 체결"},
    ])
    assert written == 2
    rows = client.only_call(duel_db.LEDGER_TABLE, "insert").rows
    assert rows[0]["event_type"] == "buy" and rows[0]["amount"] == -30_000.0
    assert rows[1]["event_type"] == "sell" and rows[1]["amount"] == 48_000.0
    # 두 event_type 모두 주문 링크가 필수입니다(`..._order_link` CHECK).
    assert rows[0]["order_id"] == "o-buy" and rows[1]["order_id"] == "o-sell"


def test_ledger_rejects_an_event_type_that_is_not_a_fill():
    """시드·정기입금은 이 함수로 넣지 않습니다(각자의 경로가 따로 있습니다)."""
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.record_buy_ledger_entries(client, [
            {"account_id": "acc-1", "order_id": "o-1", "event_type": "seed",
             "filled_amount": 1.0, "event_date": "2026-08-20"}])
    assert client.calls == []


def test_set_first_holding_dates_is_one_update_with_an_idempotent_null_guard():
    """
    🔴 리밸런싱 창의 기준일은 한 번만 정해집니다. `is null` 조건을 **DB 쪽에도** 걸어,
    배치를 두 번 돌려도 이미 채워진 날짜가 오늘로 덮어써지지 않게 합니다(덮어쓰면 그
    계좌의 매도 기회가 사라지거나 하나 더 생깁니다).
    """
    client = FakeClient()
    duel_db.set_first_holding_dates(client, ["acc-1", "acc-2"], date(2026, 8, 20))

    call = client.only_call(duel_db.ACCOUNTS_TABLE, "update")
    assert call.payload == {"first_holding_date": "2026-08-20"}
    assert ("in", "id", ["acc-1", "acc-2"]) in call.filters
    assert ("is", "first_holding_date", "null") in call.filters


def test_set_first_holding_dates_sends_nothing_for_an_empty_list():
    client = FakeClient()
    assert duel_db.set_first_holding_dates(client, [], date(2026, 8, 20)) == 0
    assert client.calls == []


def test_active_accounts_query_brings_the_first_holding_date_along():
    """
    창 계산에 필요한 값이라 **계좌를 읽는 그 질의**에서 함께 가져옵니다(따로 조회하면
    왕복이 늘거나 두 번째 계좌 조회가 생깁니다 — §0-3-2).
    """
    client = FakeClient()
    duel_db.fetch_all_active_accounts(client)
    call = client.only_call(duel_db.ACCOUNTS_TABLE, "select")
    assert "first_holding_date" in call.options["columns"]


# =============================================================================
# 9. B 절 — 크롤링 실패일 일괄 정리 (2-4-5)
# =============================================================================
def test_expire_or_cancel_all_pending_is_one_set_based_update():
    """
    🔴 §0-3-2 회귀 테스트 — 주문이 몇 건이든 update 질의는 **1개**입니다.
    (`duel_rules.check_crawl_freshness()` 가 'ok' 를 주지 않은 날의 처리)
    """
    affected = [{"id": f"o-{i}"} for i in range(37)]
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): affected})
    reason = "그 거래일의 확정 종가 수집이 실패해 체결하지 않고 취소했습니다."

    count = duel_db.expire_or_cancel_all_pending_for_date(client, date(2026, 8, 20), reason)

    assert count == 37
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.filter_map == {"status": "pending", "target_date": "2026-08-20"}
    assert call.payload == {"status": "cancelled", "fail_reason": reason}
    assert len(client.calls) == 1


def test_expire_or_cancel_all_pending_requires_a_reason():
    """사유 없는 실패 처리는 '조용히 사라지는 주문'입니다(§0-1, DB CHECK 와 같은 규칙)."""
    client = FakeClient()
    for bad_reason in ("", "   ", None):
        with pytest.raises(DuelDbError):
            duel_db.expire_or_cancel_all_pending_for_date(client, date(2026, 8, 20), bad_reason)
    assert client.calls == []


def test_expire_or_cancel_all_pending_rejects_wrong_status():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.expire_or_cancel_all_pending_for_date(
            client, date(2026, 8, 20), "사유", status="filled")
    assert client.calls == []


def test_crawl_failure_path_wires_rules_to_db():
    """
    2-5 의 1번 단계 통합: 신선도가 'ok' 가 아니면 체결을 건너뛰고 일괄 정리로 갑니다.
    (판정은 규칙 함수가, 처리 여부 결정은 `crawl_status_allows_fill()` 이 합니다.)
    """
    today = {"KOSPI": 2500.0, "KOSDAQ": 800.0}
    yesterday = {"KOSPI": 2500.0, "KOSDAQ": 800.0}
    for index in range(50):
        today[f"S{index}"] = 1000.0
        yesterday[f"S{index}"] = 1000.0
    status = duel_rules.check_crawl_freshness(today, yesterday)
    assert duel_rules.crawl_status_allows_fill(status) is False

    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): [{"id": "o-1"}]})
    duel_db.expire_or_cancel_all_pending_for_date(
        client, date(2026, 8, 20), f"수집 신선도 판정 결과 '{status}' 로 체결하지 않았습니다.")
    assert client.only_call(duel_db.ORDERS_TABLE, "update").payload["status"] == "cancelled"


# =============================================================================
# 10. B 절 — 일별 스냅샷 적재 (1-5 / 2-5-4)
# =============================================================================
def _snapshot_row(account_id="acc-1", **overrides):
    row = {
        "account_id": account_id,
        "position_value": 3_000_000.0,
        "cash_balance": 7_000_000.0,
        "total_value": 10_000_000.0,
        "total_cost": 2_800_000.0,
        "cash_flow_amount": 0.0,
        "cash_flow_kind": None,
        "priced_count": 1,
        "unpriced_count": 0,
        "price_as_of_kst": "2026-08-20 16:05",
        "holdings": [{
            "ticker": "005930", "stock_name": "삼성전자", "quantity": 40, "avg_cost": 70_000,
            "cost": 2_800_000.0, "close_price": 75_000, "market_value": 3_000_000.0,
            "status": "active", "priced": True, "price_as_of_kst": "2026-08-20 16:05",
        }],
    }
    row.update(overrides)
    return row


def test_write_daily_snapshots_upserts_both_tables_once():
    client = FakeClient()
    duel_db.write_daily_snapshots(client, date(2026, 8, 20),
                                  [_snapshot_row("acc-1"), _snapshot_row("acc-2")])

    daily = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "upsert")
    holdings = client.only_call(duel_db.HOLDING_SNAPSHOTS_TABLE, "upsert")
    assert daily.options["on_conflict"] == "account_id,snapshot_date"
    assert holdings.options["on_conflict"] == "account_id,ticker,snapshot_date"
    assert len(daily.rows) == 2 and len(holdings.rows) == 2
    # 날짜의 단일 출처는 인자 하나 — 모든 행에 같은 날짜가 찍힙니다.
    assert all(row["snapshot_date"] == "2026-08-20" for row in daily.rows + holdings.rows)
    # 종목별 행에는 계좌가 실려야 합니다(합계 표와 짝이 맞아야 하므로).
    assert {row["account_id"] for row in holdings.rows} == {"acc-1", "acc-2"}
    # 합계 표에 holdings 목록이 그대로 실려 나가면 PostgREST 가 거절합니다.
    assert all("holdings" not in row for row in daily.rows)


def test_write_daily_snapshots_rejects_total_value_mismatch():
    """총자산은 파생값이 아니라 두 관측값의 합입니다(DB CHECK 와 같은 규칙)."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.write_daily_snapshots(client, date(2026, 8, 20),
                                      [_snapshot_row(total_value=9_999_999.0)])
    assert "총자산" in str(excinfo.value)
    assert client.calls == []


def test_write_daily_snapshots_rejects_cash_flow_without_kind():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.write_daily_snapshots(client, date(2026, 8, 20), [_snapshot_row(
            cash_flow_amount=800_000.0, cash_flow_kind=None,
            cash_balance=7_800_000.0, total_value=10_800_000.0)])
    assert client.calls == []


def test_write_daily_snapshots_rejects_unpriced_holding_with_a_price():
    """'가격 모름'은 NULL 로만 표현합니다 — 0 이나 추정치로 채우지 않습니다(§0-1)."""
    row = _snapshot_row()
    row["holdings"][0]["priced"] = False      # 가격을 모른다면서 값은 남아 있음
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.write_daily_snapshots(client, date(2026, 8, 20), [row])
    assert "priced" in str(excinfo.value)


def test_write_daily_snapshots_rejects_row_dated_differently():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        duel_db.write_daily_snapshots(client, date(2026, 8, 20),
                                      [_snapshot_row(snapshot_date="2026-08-19")])


def test_write_daily_snapshots_allows_cash_only_account():
    """보유 종목이 0개이고 현금만 있는 계좌는 정상입니다(신규 계좌 — 스키마 §5 의 CHECK 완화)."""
    client = FakeClient()
    duel_db.write_daily_snapshots(client, date(2026, 8, 20), [_snapshot_row(
        position_value=0.0, cash_balance=10_000_000.0, total_value=10_000_000.0,
        total_cost=0.0, priced_count=0, holdings=[])])
    assert len(client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "upsert").rows) == 1
    assert client.calls_for(duel_db.HOLDING_SNAPSHOTS_TABLE) == []


def test_write_daily_snapshots_with_no_rows_writes_nothing():
    client = FakeClient()
    assert duel_db.write_daily_snapshots(client, date(2026, 8, 20), []) is None
    assert client.calls == []


# =============================================================================
# 11. B 절 — "모든 사용자를 한 번에" 진입점
# =============================================================================
def test_fetch_all_active_accounts_is_one_query():
    client = FakeClient(responses={(duel_db.ACCOUNTS_TABLE, "select"): _active_accounts(4)})
    rows = duel_db.fetch_all_active_accounts(client)
    assert len(rows) == 4
    call = client.only_call(duel_db.ACCOUNTS_TABLE, "select")
    assert call.filter_map == {"status": "active"}
    assert len(client.calls) == 1


def test_fetch_cash_ledger_for_accounts_uses_one_in_filter():
    client = FakeClient(responses={(duel_db.LEDGER_TABLE, "select"): [
        {"account_id": "acc-1", "amount": 10_000_000},
        {"account_id": "acc-1", "amount": -1_000_000},
        {"account_id": "acc-2", "amount": 10_000_000},
    ]})
    rows = duel_db.fetch_cash_ledger_for_accounts(client, ["acc-1", "acc-2"],
                                                  as_of_date=date(2026, 8, 20))
    call = client.only_call(duel_db.LEDGER_TABLE, "select")
    assert ("in", "account_id", ["acc-1", "acc-2"]) in call.filters
    assert ("lte", "event_date", "2026-08-20") in call.filters
    assert duel_db.cash_balances_by_account(rows) == {"acc-1": 9_000_000.0,
                                                      "acc-2": 10_000_000.0}


def test_fetch_cash_ledger_with_empty_account_list_sends_no_query():
    """빈 in 필터를 보내면 PostgREST 가 전체를 돌려줄 수 있어 아예 부르지 않습니다."""
    client = FakeClient()
    assert duel_db.fetch_cash_ledger_for_accounts(client, []) == []
    assert client.calls == []


# =============================================================================
# 12. service_role 격리 · 선택적 의존성 가드
# =============================================================================
def test_service_env_names_match_report_db_convention():
    """
    `utils/report_db.py` 와 **같은 환경변수 이름**을 씁니다. 이름이 갈라지면 오너가 배치
    시크릿을 두 벌 관리하게 되고, 한쪽만 등록된 날 조용히 절반만 동작합니다(§0-3-10).
    """
    assert duel_db.SERVICE_URL_ENV == "SUPABASE_URL"
    assert duel_db.SERVICE_ROLE_KEY_ENV == "SUPABASE_SERVICE_ROLE_KEY"


def test_service_env_is_read_from_environment_only(monkeypatch):
    """
    `st.secrets` 경로를 만들지 않습니다 — streamlit 을 import 조차 하지 않습니다.

    ⚠️ **실행되는 코드만** 봅니다. 주석·docstring 에 "streamlit 을 import 하지 않는다"는
       설명이 나오는 건 의존이 아닙니다(`tests/test_duel.py` 가 SQL 주석을 같은 방식으로
       구분한 것과 같은 판단).
    """
    tree, source = _module_ast()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "streamlit" not in imported
    # 실행 코드에 `st.` 접근이 아예 없어야 합니다(설명 문장에 나오는 건 의존이 아닙니다).
    assert not any(isinstance(node, ast.Name) and node.id == "st" for node in ast.walk(tree))
    assert source.count("os.environ") >= 1, "키는 환경변수에서만 읽습니다"

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert duel_db.service_config_present() is False
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-value")
    assert duel_db.service_config_present() is True


def test_create_service_client_without_config_raises_clear_error(monkeypatch):
    """배치는 조용히 아무 일도 안 하면 안 됩니다 — 설정이 없으면 실패해야 사람이 알아챕니다."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.create_service_client()
    message = str(excinfo.value)
    assert "SUPABASE_URL" in message and "SUPABASE_SERVICE_ROLE_KEY" in message


def test_create_service_client_does_not_leak_the_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret-key")
    monkeypatch.setattr(duel_db, "SUPABASE_PACKAGE_AVAILABLE", True)

    def _boom(url, key):
        raise RuntimeError(f"bad url {url} key {key}")

    monkeypatch.setattr(duel_db, "_supabase_create_client", _boom)
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.create_service_client()
    assert "super-secret-key" not in str(excinfo.value)


#: `supabase` 미설치 상태를 **별도 프로세스**에서 재현하는 스크립트.
#  왜 subprocess 인가: 같은 프로세스에서 `importlib.reload()` 를 하면 모듈의 클래스 객체가
#  통째로 새로 만들어져, 이 파일 맨 위에서 import 해 둔 `DuelDbError` 와 **다른 클래스**가
#  됩니다. 그러면 뒤따르는 테스트의 `pytest.raises(DuelDbError)` 가 엉뚱하게 실패하고,
#  원인을 찾기 어려운 순서 의존 버그가 됩니다. 프로세스를 분리하면 그 오염이 아예 없습니다.
_NO_SUPABASE_SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
sys.modules["supabase"] = None          # from supabase import ... → ImportError
from utils import duel_db
assert duel_db.SUPABASE_PACKAGE_AVAILABLE is False
assert duel_db._supabase_create_client is None

# 클라이언트를 **인자로 받는** 함수들은 패키지 없이도 그대로 동작해야 합니다.
class R:
    def __init__(self, data): self.data = data
class Q:
    def __init__(self, sink, payload): self.sink, self.payload = sink, payload
    def execute(self):
        self.sink.append(self.payload)
        return R([dict(self.payload)])
class T:
    def __init__(self, sink): self.sink = sink
    def insert(self, payload): return Q(self.sink, payload)
class C:
    def __init__(self): self.sink = []
    def table(self, name): return T(self.sink)

import datetime
from utils.duel_rules import KST
client = C()
duel_db.save_order(client, "acc-1", "005930", "삼성전자", 1,
                   trading_days=[datetime.date(2026, 8, 20)],
                   now_kst=datetime.datetime(2026, 8, 19, 19, 30, tzinfo=KST))
assert len(client.sink) == 1, client.sink

# 배치 클라이언트만 패키지가 필요합니다 — 없으면 AttributeError/TypeError 가 아니라
# 잡을 수 있는 DuelDbError 여야 합니다.
import os
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "secret-value"
try:
    duel_db.create_service_client()
except duel_db.DuelDbError as exc:
    assert "supabase" in str(exc)
else:
    raise AssertionError("패키지가 없는데 클라이언트가 만들어졌습니다")
print("OK")
"""


def test_module_imports_and_works_without_supabase_package():
    """
    🔴 선택적 의존성 가드 — `supabase` 가 없어도 **import 가 깨지지 않아야** 합니다.
    (`utils/scorecard_db.py` 와 같은 규율: 이 패키지가 없다고 기존 모듈이 죽으면 안 됩니다.)

    같은 스크립트 안에서 세 가지를 함께 확인합니다:
      ① import 자체가 성공하고 `SUPABASE_PACKAGE_AVAILABLE` 이 False 인지
      ② 클라이언트를 인자로 받는 함수는 패키지 없이도 그대로 동작하는지
      ③ 배치 클라이언트 생성만 실패하되, `None` 을 부르다 나는 AttributeError/TypeError 가
         아니라 **잡을 수 있는 DuelDbError** 인지
    """
    result = subprocess.run(
        [sys.executable, "-c", _NO_SUPABASE_SCRIPT.format(repo=str(REPO_ROOT))],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK")


def test_calling_service_client_without_package_raises_catchable_error(monkeypatch):
    """
    패키지가 없는 상태에서 배치 클라이언트를 만들면 `None(url, key)` 로 죽는 게 아니라
    **무엇을 해야 하는지 적힌 DuelDbError** 가 나야 합니다(§0-3-4 — 사용자·오너에게 코드가
    아니라 문장이 보이도록).
    """
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-value")
    monkeypatch.setattr(duel_db, "SUPABASE_PACKAGE_AVAILABLE", False)
    monkeypatch.setattr(duel_db, "_supabase_create_client", None)
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.create_service_client()
    assert "supabase" in str(excinfo.value)
    assert not isinstance(excinfo.value, AttributeError)


@pytest.mark.parametrize("call", [
    lambda: duel_db.opt_in(None),
    lambda: duel_db.fetch_my_accounts(None, "user-1"),
    lambda: duel_db.fetch_my_positions(None, "acc-1"),
    lambda: duel_db.fetch_my_orders(None, "acc-1"),
    lambda: duel_db.fetch_my_snapshots(None, "acc-1"),
    lambda: duel_db.save_order(None, "acc-1", "005930", "삼성전자", 1,
                               trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW),
    lambda: duel_db.edit_order(None, "order-1", 3, now_kst=INSIDE_WINDOW),
    lambda: duel_db.cancel_order(None, "order-1", now_kst=INSIDE_WINDOW),
    lambda: duel_db.save_consent(None, "acc-1", consent_rank=True),
    lambda: duel_db.fetch_all_active_accounts(None),
    lambda: duel_db.apply_monthly_deposits(None, date(2026, 9, 10)),
    lambda: duel_db.create_duel_accounts_for_user(None, "user-1"),
    lambda: duel_db.fetch_pending_orders_for_fill(None, date(2026, 8, 20)),
    lambda: duel_db.expire_or_cancel_all_pending_for_date(None, date(2026, 8, 20), "사유"),
    lambda: duel_db.write_daily_snapshots(None, date(2026, 8, 20), [_snapshot_row()]),
    lambda: duel_db.record_order_fills(None, [{"id": "o-1", "status": "filled",
                                               "filled_quantity": 1, "filled_price": 100,
                                               "filled_amount": 100,
                                               "filled_date": date(2026, 8, 20)}]),
    lambda: duel_db.record_buy_ledger_entries(None, [{"account_id": "acc-1",
                                                      "order_id": "o-1",
                                                      "filled_amount": 100,
                                                      "event_date": date(2026, 8, 20)}]),
    lambda: duel_db.upsert_positions(None, [{"account_id": "acc-1", "ticker": "005930",
                                             "stock_name": "삼성전자", "quantity": 1,
                                             "avg_cost": 100}]),
    lambda: duel_db.expire_stale_pending_orders_before(None, date(2026, 8, 20), "사유"),
    lambda: duel_db.annotate_pending_orders_with_hold_reason(None, date(2026, 8, 20), "사유"),
])
def test_none_client_raises_duel_db_error_not_attribute_error(call):
    """
    클라이언트가 없을 때 `'NoneType' object has no attribute 'table'` 로 죽지 않습니다 —
    사용자에게도 오너에게도 아무 도움이 안 되는 메시지이기 때문입니다(§0-3-4).
    """
    with pytest.raises(DuelDbError):
        call()


# =============================================================================
# 13. 계층 분리 — 계산을 이 파일에서 다시 구현하지 않았는지
# =============================================================================
def test_duel_db_calls_the_rules_module_and_does_not_reimplement_it():
    """
    체결·평단가·창 판정·TWR 의 단일 출처는 `utils/duel_rules.py` 입니다.
    이 파일에 그 계산이 복사돼 들어오면(예: floor 나눗셈, 가중평균 식) 언젠가 둘 중 하나만
    고쳐지고, 화면 숫자와 DB 값이 갈라집니다(§0-3-10).
    """
    tree, source = _module_ast()
    assert "from utils import duel_rules" in source

    # 실행되는 코드만 봅니다(docstring 에서 규칙 함수 이름을 **설명하는** 건 재구현이 아니라
    # 오히려 권장되는 안내입니다 — tests/test_duel.py 가 SQL 주석을 다룬 방식과 같습니다).
    executable_lines = []
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
    for number, line in enumerate(source.splitlines(), start=1):
        if number in skip or line.lstrip().startswith("#"):
            continue
        executable_lines.append(line)
    executable = "\n".join(executable_lines)

    for reimplementation in ("math.floor", "// price", "chain *=", "Decimal("):
        assert reimplementation not in executable, f"{reimplementation} 를 여기서 다시 짜지 마세요"
    # 금액 상수도 다시 적지 않습니다(단일 출처는 duel_rules — 스키마에도 안 적은 이유와 같음).
    assert "10_000_000" not in executable and "10000000" not in executable
    assert "800_000" not in executable and "800000" not in executable


def test_rules_module_was_not_modified_by_this_layer():
    """
    이 작업은 `utils/duel_rules.py` 를 고치지 않는 것이 전제입니다(승인된 파일).
    여기서는 이 계층이 기대하는 공개 함수·상수가 **그대로 있는지**만 확인합니다 —
    없어졌다면 규칙 파일이 손을 탄 것입니다.
    """
    for name in ("resolve_order_window", "resolve_fill_trading_day", "calculate_fill",
                 "allocate_pending_orders", "apply_buy_fill_to_position",
                 "check_crawl_freshness", "crawl_status_allows_fill", "compute_twr",
                 "is_buy_window_open"):
        assert callable(getattr(duel_rules, name)), name
    assert duel_rules.SEED_AMOUNT_KRW == 10_000_000
    assert duel_rules.MONTHLY_DEPOSIT_KRW == 800_000
    assert duel_rules.ACCOUNT_WINDOW_TYPES == ("M1", "M3", "M6")


def test_every_public_function_has_a_docstring():
    """
    이 저장소의 관례(§0-1 — 코드가 왜 그런지 남기기). 공개 함수는 전부 설명을 답니다.
    """
    missing = [name for name, function in vars(duel_db).items()
               if inspect.isfunction(function)
               and function.__module__ == duel_db.__name__
               and not name.startswith("_")
               and not (function.__doc__ or "").strip()]
    assert missing == [], f"docstring 없는 공개 함수: {missing}"


# =============================================================================
# 16. 🔴 2026-08-29 재감사 H-6 — 배치 읽기 페이지네이션
#
#  예전에는 배치 조회 **어디에도 `.range()` 가 없었습니다.** PostgREST/Supabase 가 행을
#  잘라 돌려주면 "일부만 읽고 전부 읽은 척" 하게 되고(잘린 성공 응답은 `_execute()` 의
#  실패 방어를 그대로 통과합니다), 그 반쪽 원장으로 계산한 예수금이 "예수금 부족"이라는
#  **사실이 아닌 만료 사유**를 사용자 주문에 적었습니다.
# =============================================================================
def test_execute_all_reads_every_page_and_stops_on_a_short_one():
    """페이지가 꽉 차 있으면 계속 읽고, 짧은 페이지에서 멈춥니다."""
    client = FakeClient()
    pages = [[{"n": i} for i in range(3)], [{"n": 3}]]

    def factory(offset, limit):
        query = client.table("t").select("*").range(offset, limit)
        query.execute = lambda q=query: FakeResponse(pages.pop(0)) if pages else FakeResponse([])
        return query

    calls = []

    def spy(offset, limit):
        calls.append((offset, limit))
        return factory(offset, limit)

    rows = duel_db._execute_all(spy, "테스트 조회", page=3)
    assert [row["n"] for row in rows] == [0, 1, 2, 3]
    assert calls == [(0, 2), (3, 5)]


def test_execute_all_makes_exactly_one_round_trip_for_a_single_page():
    """🔴 회귀 원칙 유지 — 페이지가 1개뿐이면 왕복은 **예전과 똑같이 1회**입니다(§0-3-2)."""
    client = FakeClient(responses={(duel_db.ACCOUNTS_TABLE, "select"):
                                   [{"id": f"acc-{i}"} for i in range(3)]})
    duel_db.fetch_all_active_accounts(client)
    assert len(client.calls_for(duel_db.ACCOUNTS_TABLE, "select")) == 1
    assert client.calls[0].options["range"] == (0, 999)


def test_execute_all_raises_instead_of_silently_returning_half_the_rows():
    """
    🔴 §0-1 — 상한에 걸린 채로 멈추면 **예외**입니다. 조용히 반쪽 데이터로 넘어가면
    그 위에서 계산한 예수금이 사용자 주문의 체결·만료를 결정하게 됩니다.
    """
    client = FakeClient()

    def factory(offset, limit):
        query = client.table("t").select("*").range(offset, limit)
        query.execute = lambda: FakeResponse([{"n": 0}, {"n": 1}])   # 언제나 가득 참
        return query

    with pytest.raises(DuelDbError) as excinfo:
        duel_db._execute_all(factory, "테스트 조회", page=2, max_pages=3)
    assert "페이지 상한" in str(excinfo.value)


def test_batch_reads_all_use_range():
    """배치 읽기 함수들이 실제로 `.range()` 를 붙여 보내는지(하나라도 빠지면 H-6 재발)."""
    checks = [
        (lambda c: duel_db.fetch_all_active_accounts(c), duel_db.ACCOUNTS_TABLE),
        (lambda c: duel_db.fetch_cash_ledger_for_accounts(c, ["acc-1"]), duel_db.LEDGER_TABLE),
        (lambda c: duel_db.fetch_positions_for_accounts(c, ["acc-1"]), duel_db.POSITIONS_TABLE),
        (lambda c: duel_db.fetch_daily_snapshots_for_accounts(c, ["acc-1"]),
         duel_db.DAILY_SNAPSHOTS_TABLE),
        (lambda c: duel_db.fetch_pending_orders_for_fill(c, date(2026, 8, 20)),
         duel_db.ORDERS_TABLE),
        (lambda c: duel_db.fetch_publishable_consents(c), duel_db.CONSENT_TABLE),
        (lambda c: duel_db.fetch_revoked_consent_accounts(c), duel_db.CONSENT_TABLE),
        (lambda c: duel_db.fetch_bracket_assignments(c, "2026-H2"),
         duel_db.BRACKET_ASSIGNMENTS_TABLE),
    ]
    for call, table in checks:
        client = FakeClient()
        call(client)
        query = client.only_call(table, "select")
        assert "range" in query.options, f"{table} 조회에 .range() 가 없습니다(H-6)"


def test_revoke_consent_does_not_extend_the_block_when_another_tab_won():
    """
    🔴 L-12 — 두 탭에서 동시에 철회해도 `revoked_at` 을 덮어쓰지 않습니다(TOCTOU).

    update 문 자체에 "아직 철회되지 않은 행만" 조건을 넣고, 0행이면 다른 요청이 먼저
    끝냈다는 뜻이므로 그 결과를 다시 읽어 돌려줍니다(3개월 차단이 연장되지 않습니다).
    """
    already = {"account_id": "acc-1", "revoked_at": "2026-08-01T00:00:00+09:00"}
    client = FakeClient(responses={
        # 1차 조회에서는 "아직 철회 전"으로 보이지만(다른 탭이 그 사이 철회),
        # update 는 0행이고, 그 뒤 재조회에서 이미 철회된 행이 나옵니다.
        (duel_db.CONSENT_TABLE, "select"): sequence(
            [{"account_id": "acc-1", "revoked_at": None}], [already]),
        (duel_db.CONSENT_TABLE, "update"): [],
    })
    result = duel_db.revoke_consent(client, "acc-1")
    assert result["revoked_at"] == already["revoked_at"], "먼저 찍힌 철회 시각을 덮어썼습니다"
    update = client.only_call(duel_db.CONSENT_TABLE, "update")
    assert ("is", "revoked_at", "null") in update.filters


def test_save_sell_order_accepts_a_fractional_holding():
    """
    🔴 M-4 — 소수 보유 수량이 **매도 자체를 막지 않습니다.**

    `duel_rules.calculate_sell_fill()` 은 "액면병합·감자 같은 기업행위 조정이 소수 수량을
    남길 수 있다"는 이유로 보유 수량에 정수를 요구하지 않는데, 이 계층에서만 거절해서
    10.5주 보유 계좌는 한 주도 팔 수 없었고 0.4주 포지션은 영원히 정리할 수 없었습니다.
    **파는 수량(quantity)의 정수 검증은 그대로**입니다(부분 주식을 팔 수는 없습니다).
    """
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "insert"): [{"id": "o-1"}]})
    saved = duel_db.save_sell_order(
        client, "acc-1", "005930", "삼성전자", 1, 10.5, 0,
        trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    assert saved["id"] == "o-1"

    # 보유량을 넘는 수량은 여전히 거절합니다.
    with pytest.raises(DuelDbError):
        duel_db.save_sell_order(
            client, "acc-1", "005930", "삼성전자", 11, 10.5, 0,
            trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)
    # 파는 수량은 여전히 정수여야 합니다.
    with pytest.raises(DuelDbError):
        duel_db.save_sell_order(
            client, "acc-1", "005930", "삼성전자", 1.5, 10.5, 0,
            trading_days=TRADING_DAYS, now_kst=INSIDE_WINDOW)


def test_expire_stale_pending_orders_before_uses_a_less_than_filter():
    """
    🔴 H-8 — "그 이전 전부"를 **한 번의 update** 로 정리합니다(집합 연산, §0-3-2).
    기존 `expire_or_cancel_all_pending_for_date()` 는 정확히 그 날짜 하나만 봅니다.
    """
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"):
                                   [{"id": "old-1"}, {"id": "old-2"}]})
    assert duel_db.expire_stale_pending_orders_before(
        client, date(2026, 8, 20), "사유") == 2
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert ("lt", "target_date", "2026-08-20") in call.filters
    assert ("eq", "status", "pending") in call.filters
    assert call.payload["status"] == duel_db.ORDER_CANCELLED
    assert call.payload["fail_reason"] == "사유"


def test_expire_or_cancel_all_pending_for_date_can_be_limited_to_active_accounts():
    """
    🔴 M-11 — 실패일 일괄 취소도 **활성 계좌만** 대상으로 할 수 있어야 합니다.
    체결 경로는 활성 계좌 목록에 없는 주문을 손대지 않고 경고로 올리는데, 이 경로만
    계좌 상태를 보지 않아 같은 주문이 날에 따라 보호받거나 취소됐습니다.
    """
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): [{"id": "o-1"}]})
    duel_db.expire_or_cancel_all_pending_for_date(
        client, date(2026, 8, 20), "사유", account_ids=["acc-1", "acc-2"])
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert ("in", "account_id", ["acc-1", "acc-2"]) in call.filters

    # 대상이 비어 있으면 질의 자체를 보내지 않습니다(빈 in 필터 방지).
    empty = FakeClient()
    assert duel_db.expire_or_cancel_all_pending_for_date(
        empty, date(2026, 8, 20), "사유", account_ids=[]) == 0
    assert empty.calls == []


# -----------------------------------------------------------------------------
# 12-2. 보류 사유 표식 (2026-08-29 재감사 M-10)
# -----------------------------------------------------------------------------
def test_hold_reason_is_written_without_touching_the_status():
    """
    🔴 M-10 — 보류는 **결론이 아닙니다.** 그래서 `status` 는 `pending` 그대로 두고
    `fail_reason` 만 적습니다. payload 에 status 가 섞여 들어가면 그날 주문이 조용히
    종결되어 사용자가 다시 주문할 기회도, 관리자가 override 로 결론 낼 기회도 사라집니다.
    """
    affected = [{"id": f"o-{i}"} for i in range(5)]
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): affected})
    reason = "2026-08-20 종가로 체결할지 판단하지 못해 보류 중입니다(관리자 확인 대기)."

    count = duel_db.annotate_pending_orders_with_hold_reason(
        client, date(2026, 8, 20), reason)

    assert count == 5
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert call.payload == {"fail_reason": reason}, (
        "보류 표식이 status 까지 건드립니다 — 보류를 종결로 바꿔 적는 셈입니다(§0-1)."
    )
    assert "status" not in call.payload
    # 대상 집합은 보류 판단에 쓴 `fetch_pending_orders_for_fill()` 과 같은 필터입니다.
    assert call.filter_map == {"status": "pending", "target_date": "2026-08-20"}
    assert len(client.calls) == 1, "주문이 몇 건이든 update 질의는 1개입니다(§0-3-2)."


def test_hold_reason_requires_a_sentence():
    """사유 없는 표식은 화면에 "왜 멈췄는지"를 못 알려 줍니다 — 애초에 적을 이유가 없습니다."""
    client = FakeClient()
    for bad_reason in ("", "   ", None):
        with pytest.raises(DuelDbError):
            duel_db.annotate_pending_orders_with_hold_reason(
                client, date(2026, 8, 20), bad_reason)
    assert client.calls == []


def test_a_later_fill_overwrites_the_hold_reason():
    """
    🔴 M-10 후속 — 보류 표식은 **임시**입니다. 나중에 그 주문이 실제로 체결되면
    `record_order_fills()` 가 `fail_reason` 을 payload 에 **항상 다시 써서**(전량 체결이면
    `None`) 덮어씁니다. 표식이 남아 화면에 "보류 중"이라고 계속 적히면 그게 새로운 거짓말이
    됩니다 — 별도 정리 로직 없이 이 성질만으로 충분한지를 여기서 고정합니다.
    """
    client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): [{"id": "o-1"}]})
    duel_db.record_order_fills(client, [{
        "id": "o-1", "status": duel_rules.ORDER_FILLED, "filled_quantity": 2,
        "filled_price": 10_000, "filled_amount": 20_000, "filled_date": date(2026, 8, 20),
    }])
    call = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert "fail_reason" in call.payload and call.payload["fail_reason"] is None, (
        "체결 기록이 fail_reason 을 다시 쓰지 않습니다 — 보류 표식이 체결된 주문에 그대로 "
        "남아 화면이 '보류 중'이라고 계속 말하게 됩니다."
    )
    # 취소로 결론 나는 경우도 같은 자리(새 사유 문장)로 덮어써집니다.
    cancel_client = FakeClient(responses={(duel_db.ORDERS_TABLE, "update"): [{"id": "o-1"}]})
    duel_db.expire_or_cancel_all_pending_for_date(
        cancel_client, date(2026, 8, 20), "관리자 확인 결과 취소했습니다.")
    cancel_call = cancel_client.only_call(duel_db.ORDERS_TABLE, "update")
    assert cancel_call.payload["fail_reason"] == "관리자 확인 결과 취소했습니다."
    assert cancel_call.payload["status"] == duel_db.ORDER_CANCELLED
