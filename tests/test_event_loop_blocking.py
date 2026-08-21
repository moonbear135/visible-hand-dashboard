"""
🔴 "연결이 끊겼습니다. 다시 연결 중…" 재발 방지 — **이벤트 루프를 막는 코드가 없는가**
   (2026-08-21 2차 수정. 1차는 `tests/test_data_source.py::test_pages_never_block_the_event_loop`)

무슨 사고를 막는 파일인가
────────────────────────────────────────────────────────────────────────────
1차 수정으로 **JSON 스냅샷 읽기**를 이벤트 루프 밖으로 내보냈는데도, 오너가 홈('/')에서
같은 끊김을 다시 겪었습니다. 홈 화면은 그 시점에 블로킹 I/O 를 전혀 하지 않았으므로,
루프를 붙잡은 것은 **그 순간 다른 사람이 보내고 있던 다른 요청**이었습니다. 남아 있던 것은

  ① Supabase(postgrest/gotrue) **동기 HTTP 왕복** — 로그인 확인(`current_user`),
     보유종목·계좌·주문 조회, 주문 저장, 로그아웃까지 전부.
  ② 원격 CSV 읽기 — 홈·미국 화면의 **종목 검색창**(`load_stock_history`)과
     보고서의 벤치마크(`benchmark_closes_for_market`).

NiceGUI 는 한 프로세스·한 이벤트 루프가 모든 접속자를 처리하므로, 저 한 줄이 도는 동안
**접속자 전원**의 WebSocket 하트비트가 멈춥니다. 자기 화면이 느린 게 아니라 남의 요청이
나를 멈추는 구조라 증상이 늘 엉뚱한 화면에서 나타납니다.

이 파일이 못 박는 것 (사람이 한 번 확인하고 끝내면 조용히 되돌아갈 수 있는 종류의 수정입니다)
────────────────────────────────────────────────────────────────────────────
  [1] `web/blocking.run_blocking()` 이 정말 `run.io_bound` 에 넘기는가, 그리고 그 동안
      이벤트 루프가 계속 도는가 (= 다른 접속자 하트비트가 살아 있는가).
  [2] 취소·종료(`io_bound` → None)를 **빈 값으로 위장하지 않는가** (§0-1).
      정상적인 `None` 반환값과 절대 헷갈리지 않는가.
  [3] 🔐 **저장소 접근 순서** — `get_client_async()` / `logout_async()` /
      `current_user_async()` 가 `app.storage.*` 를 **스레드로 넘기기 전에, 이벤트 루프
      에서** 끝내는가. 이게 이 파일에서 가장 중요한 검사입니다: 여기가 틀리면
      2026-08-17 "로그인이 안 된다" 사고(io_bound 스레드 안에서 app.storage 접근)가
      그대로 재현되고, 최악의 경우 **접속 컨텍스트 없는 스레드가 남의 세션을 만지는**
      모양이 됩니다(§0-3-8, 자산·신원 데이터).
  [4] 소스 수준 회귀 방지 — 화면 파일들이 다시 동기 호출로 돌아가지 않도록 AST 로 훑습니다.

⚠️ 이 샌드박스에 진짜 nicegui 가 없으면 [1]의 스레드 분리 검증만 건너뜁니다(스텁 io_bound
   는 그냥 동기 호출이라 확인할 대상이 없습니다). 나머지 검사는 스텁에서도 전부 돕니다.
"""

import ast
import asyncio
import sys
import threading
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# =============================================================================
# 0. nicegui 스텁 (없을 때만) — 다른 테스트 파일들과 같은 방식
# =============================================================================
def _install_nicegui_stub() -> bool:
    """진짜 nicegui 가 있으면 손대지 않습니다. 스텁을 꽂았으면 True."""
    try:
        import nicegui                                                   # noqa: F401
        return False
    except ImportError:
        pass

    class _Storage:
        def __init__(self):
            self.user = {}
            self.client = {}

    class _App:
        def __init__(self):
            self.storage = _Storage()

        def get(self, *_a, **_k):
            return lambda fn: fn

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

    class _UI(types.ModuleType):
        def __getattr__(self, _name):
            return _Element()

    class _Run(types.ModuleType):
        @staticmethod
        async def io_bound(fn, *args, **kwargs):
            return fn(*args, **kwargs)

    nicegui = types.ModuleType("nicegui")
    nicegui.app = _App()
    nicegui.ui = _UI("nicegui.ui")
    nicegui.run = _Run("nicegui.run")
    sys.modules["nicegui"] = nicegui
    sys.modules["nicegui.ui"] = nicegui.ui
    sys.modules["nicegui.run"] = nicegui.run
    return True


STUBBED = _install_nicegui_stub()

from web import auth, blocking                                           # noqa: E402
from web.blocking import BlockingCallAborted, run_blocking               # noqa: E402


# =============================================================================
# [1] 블로킹 호출이 정말 **이벤트 루프 밖**에서 도는가
# =============================================================================
def test_run_blocking_hands_the_call_to_io_bound():
    """`run_blocking()` 이 직접 부르지 않고 `run.io_bound` 에 넘기는지 — 감시자로 확인."""
    from nicegui import run as nicegui_run

    handed_over = []
    saved = nicegui_run.io_bound

    async def _spy(fn, *args, **kwargs):
        handed_over.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    def _target(a, b, *, c):
        return (a, b, c)

    nicegui_run.io_bound = _spy
    try:
        result = asyncio.run(run_blocking(_target, 1, 2, c=3))
    finally:
        nicegui_run.io_bound = saved

    assert result == (1, 2, 3), "반환값은 원래 함수와 글자 그대로 같아야 합니다"
    assert len(handed_over) == 1, (
        f"run.io_bound 호출 {len(handed_over)}회 — 0회면 블로킹 호출이 이벤트 루프로 "
        "되돌아온 것입니다(사고 재발)."
    )
    fn, args, kwargs = handed_over[0]
    # 스레드로 넘어가는 것은 `_boxed(대상함수, *인자)` 이어야 합니다 — 대상 함수를 **미리
    # 실행해서** 그 결과를 넘기면(= 첫 인자가 Call) 블로킹이 루프에서 그대로 일어납니다.
    assert fn is blocking._boxed
    assert args == (_target, 1, 2) and kwargs == {"c": 3}


@pytest.mark.skipif(STUBBED, reason="진짜 nicegui 가 없으면 스텁 io_bound 는 동기 호출입니다")
def test_the_event_loop_keeps_running_while_the_blocking_call_works():
    """0.2초짜리 블로킹 호출 동안 **다른 접속자의 하트비트**가 계속 도는지."""
    worker_threads = []

    def _slow():
        worker_threads.append(threading.current_thread())
        time.sleep(0.20)                            # 원격 왕복 흉내 (블로킹)
        return "done"

    async def _scenario():
        ticks = [0]

        async def _heartbeat():
            while True:                             # WebSocket 하트비트 흉내
                await asyncio.sleep(0.01)
                ticks[0] += 1

        beat = asyncio.create_task(_heartbeat())
        try:
            value = await run_blocking(_slow)
        finally:
            beat.cancel()
        return value, ticks[0], threading.current_thread()

    value, ticks, loop_thread = asyncio.run(_scenario())

    assert value == "done"
    assert len(worker_threads) == 1 and worker_threads[0] is not loop_thread, (
        f"작업 스레드={[t.name for t in worker_threads]} / 루프 스레드={loop_thread.name} "
        "— 같으면 블로킹이 이벤트 루프 위에서 일어난 것입니다."
    )
    assert ticks >= 5, (
        f"그 0.2초 동안 루프가 {ticks}번밖에 못 돌았습니다 — 0 이면 루프가 통째로 멈춘 "
        "것이고, 그게 바로 '연결이 끊겼습니다' 토스트의 원인입니다."
    )


# =============================================================================
# [2] 취소·종료를 **빈 값으로 위장하지 않는가** (§0-1)
# =============================================================================
def test_a_genuine_none_result_is_not_mistaken_for_a_cancelled_request():
    """`current_user()` 처럼 **정상적으로 None 을 돌려주는** 함수가 있습니다.

    상자(`_boxed`)에 담지 않으면 그 정상 `None` 과 "요청이 취소됨"의 `None` 이 구별되지
    않고, 화면은 "로그인 세션 만료"로 오해해 **멀쩡한 토큰을 지워버립니다**.
    """
    assert asyncio.run(run_blocking(lambda: None)) is None, (
        "정상적으로 None 을 돌려주는 함수는 그냥 None 이 나와야 합니다(예외 아님)"
    )


def test_a_cancelled_call_fails_loudly_instead_of_returning_empty_data():
    """`io_bound` 가 None(취소·서버 종료)을 돌려주면 예외로 올립니다 — §0-1."""
    from nicegui import run as nicegui_run

    saved = nicegui_run.io_bound

    async def _cancelled(*_a, **_k):
        return None                                 # NiceGUI 3.x 의 취소/종료 규약

    nicegui_run.io_bound = _cancelled
    try:
        with pytest.raises(BlockingCallAborted) as caught:
            asyncio.run(run_blocking(lambda: ["행1", "행2"]))
    finally:
        nicegui_run.io_bound = saved

    text = str(caught.value)
    assert text and "Traceback" not in text and "None" not in text, (
        f"실패 문구에 파이썬 내부 사정이 새면 안 됩니다(§0-3-4): {text!r}"
    )


# =============================================================================
# [3] 🔐 저장소 접근 순서 — 여기가 이 파일에서 가장 중요한 검사입니다
# =============================================================================
class _StorageTripwire:
    """`app.storage.*` 흉내 — **이벤트 루프 스레드가 아닌 곳에서 만지면 터집니다.**

    실제 NiceGUI 에서도 `run.io_bound` 스레드 안에는 "지금 어느 접속인지"를 담은
    컨텍스트가 없어 `app.storage.*` 가 동작하지 않습니다(GitHub Discussion #2228/#2801).
    2026-08-17 "로그인이 안 된다" 사고가 정확히 그것이었습니다. 여기서는 그 상황을
    **테스트가 확실히 잡을 수 있는 형태(예외)** 로 재현합니다.
    """

    def __init__(self, owner_thread):
        self.owner_thread = owner_thread
        self.data = {}
        self.violations = []

    def _check(self):
        if threading.current_thread() is not self.owner_thread:
            self.violations.append(threading.current_thread().name)
            raise RuntimeError(
                '🔴 app.storage 를 이벤트 루프가 아닌 스레드에서 만졌습니다 '
                '(2026-08-17 사고 재현 — web/auth.py::get_client_async() 독스트링 참고).'
            )

    def get(self, key, default=None):
        self._check()
        return self.data.get(key, default)

    def pop(self, key, default=None):
        self._check()
        return self.data.pop(key, default)

    def __setitem__(self, key, value):
        self._check()
        self.data[key] = value

    def __getitem__(self, key):
        self._check()
        return self.data[key]

    def __contains__(self, key):
        self._check()
        return key in self.data


class _FakeAuthClient:
    """`supabase` 클라이언트 흉내 — 어느 스레드에서 무엇이 불렸는지 기록합니다."""

    def __init__(self, log):
        self.log = log
        self.auth = self
        self.session = None
        self.signed_out = False

    def set_session(self, access_token, refresh_token):
        self.log.append(("set_session", threading.current_thread(), access_token, refresh_token))
        self.session = (access_token, refresh_token)

    def sign_out(self):
        self.log.append(("sign_out", threading.current_thread()))
        self.signed_out = True

    def get_user(self):
        self.log.append(("get_user", threading.current_thread()))
        return types.SimpleNamespace(user={"id": "uid-1", "email": "a@example.com"})


def _with_tripwire_storage(coro_factory):
    """트립와이어 저장소를 꽂고 코루틴을 돌린 뒤 `(결과, user, client, 호출로그)` 를 돌려줍니다."""
    log = []
    holder = {}

    async def _main():
        loop_thread = threading.current_thread()
        user_store = _StorageTripwire(loop_thread)
        client_store = _StorageTripwire(loop_thread)
        holder["user"] = user_store
        holder["client"] = client_store

        # ⚠️ 접근자(`user_storage()`/`client_storage()`) **자체를 부르는 것**도 위반으로
        #    셉니다. 실제 NiceGUI 에서 `app.storage.user` 는 접속 컨텍스트가 없으면 그
        #    자리에서 바로 터지므로, "스레드 안에서 서랍을 꺼내 오기만 하고 아직 읽지는
        #    않았다"는 변명은 성립하지 않습니다. (이 한 줄이 없으면
        #    `run_blocking(lambda: user_storage().get(...))` 같은 우회를 놓칩니다.)
        def _user_storage():
            user_store._check()
            return user_store

        def _client_storage():
            client_store._check()
            return client_store

        saved = (auth.user_storage, auth.client_storage, auth.create_supabase_client,
                 auth.sign_out, auth.current_user)
        auth.user_storage = _user_storage
        auth.client_storage = _client_storage
        auth.create_supabase_client = lambda: _FakeAuthClient(log)
        auth.sign_out = lambda client: client.auth.sign_out()
        auth.current_user = lambda client: getattr(client.auth.get_user(), "user", None)
        try:
            return await coro_factory(user_store, client_store)
        finally:
            (auth.user_storage, auth.client_storage, auth.create_supabase_client,
             auth.sign_out, auth.current_user) = saved

    result = asyncio.run(_main())
    return result, holder["user"], holder["client"], log


def test_get_client_async_reads_storage_before_dispatching_to_the_thread():
    """🔐 `get_client_async()` — 저장소는 루프에서, 네트워크(`set_session`)만 스레드에서.

    이 테스트가 실패하는 유일한 방법은 누군가 `get_client_async()` 를 통째로
    `run_blocking(...)` 으로 감싸는 것입니다. 그게 2026-08-17 사고입니다.
    """
    async def _scenario(user_store, _client_store):
        user_store.data[auth.SB_TOKENS_KEY] = {
            "access_token": "ACCESS::a@example.com",
            "refresh_token": "REFRESH::a@example.com",
        }
        return await auth.get_client_async(), threading.current_thread()

    (client, loop_thread), user_store, client_store, log = _with_tripwire_storage(_scenario)

    assert not user_store.violations and not client_store.violations, (
        f"저장소를 만진 잘못된 스레드: {user_store.violations + client_store.violations}"
    )
    assert client is not None
    # 세션 복원은 **정확히 이 접속자 자신의 토큰**으로, 그리고 다른 스레드에서.
    calls = [row for row in log if row[0] == "set_session"]
    assert len(calls) == 1, f"set_session 호출 {len(calls)}회"
    _name, thread, access, refresh = calls[0]
    assert (access, refresh) == ("ACCESS::a@example.com", "REFRESH::a@example.com"), (
        "🔴 남의 토큰이 붙으면 그 사람의 권한으로 DB 를 읽게 됩니다 (§0-3-8)"
    )
    if not STUBBED:
        assert thread is not loop_thread, (
            "세션 복원(refresh 왕복)이 이벤트 루프 스레드에서 일어났습니다 — 그동안 "
            "접속자 전원이 멈춥니다."
        )
    # 만들어진 클라이언트는 **이 접속의 서랍**에만 들어갑니다.
    assert client_store.data.get(auth.SB_CLIENT_KEY) is client


def test_get_client_async_drops_a_dead_token_from_the_right_drawer():
    """세션 복원이 실패하면 죽은 토큰을 **이 접속자의 서랍에서** 지웁니다 (§0-1).

    ⚠️ 그 삭제도 반드시 이벤트 루프에서 일어나야 합니다(저장소 쓰기). 스레드 안에서
       지우려 들면 위 트립와이어가 터집니다.
    """
    async def _scenario(user_store, _client_store):
        user_store.data[auth.SB_TOKENS_KEY] = {"access_token": "X", "refresh_token": "Y"}

        def _broken():
            client = _FakeAuthClient([])

            def _boom(*_a, **_k):
                raise RuntimeError("refresh token expired")

            client.set_session = _boom
            return client

        auth.create_supabase_client = _broken
        return await auth.get_client_async()

    client, user_store, client_store, _log = _with_tripwire_storage(_scenario)

    assert not user_store.violations and not client_store.violations
    assert auth.SB_TOKENS_KEY not in user_store.data, (
        "만료된 토큰을 남겨두면 화면이 '로그인된 척' 합니다 (§0-1)"
    )
    assert client is not None, "복원에 실패해도 (로그인 안 된) 클라이언트 자체는 돌려줍니다"


def test_logout_async_clears_both_drawers_before_the_network_call():
    """🔐 `logout_async()` — 서랍 두 개를 **네트워크보다 먼저** 비웁니다.

    왜 순서가 중요한가: `await` 이 들어가면 서버 왕복이 끝날 때까지 몇 초가 흐릅니다.
    그 사이에 같은 사람이 다른 탭을 새로고침하면, 아직 남아 있는 토큰으로 **다시
    로그인된 화면**이 그려집니다 — "로그아웃을 눌렀는데 옆 탭은 로그인 상태"는 자산
    화면에서 절대 만들면 안 되는 상태입니다(§0-3-8).
    """
    async def _scenario(user_store, client_store):
        client = _FakeAuthClient([])
        client.log = []
        # 로그아웃 시점의 서랍 상태를 sign_out 안에서 들여다봅니다.
        seen = {}

        def _sign_out(c):
            seen["tokens_left"] = auth.SB_TOKENS_KEY in user_store.data
            seen["client_left"] = auth.SB_CLIENT_KEY in client_store.data
            c.signed_out = True

        auth.sign_out = _sign_out
        user_store.data[auth.SB_TOKENS_KEY] = {"access_token": "A", "refresh_token": "B"}
        client_store.data[auth.SB_CLIENT_KEY] = client
        await auth.logout_async()
        return client, seen

    (client, seen), user_store, client_store, _log = _with_tripwire_storage(_scenario)

    assert not user_store.violations and not client_store.violations, (
        "🔴 로그아웃 경로가 스레드 안에서 app.storage 를 만졌습니다"
    )
    assert client.signed_out is True, "서버 쪽 로그아웃 요청도 실제로 나가야 합니다"
    assert auth.SB_TOKENS_KEY not in user_store.data
    assert auth.SB_CLIENT_KEY not in client_store.data
    assert seen == {"tokens_left": False, "client_left": False}, (
        f"네트워크 호출 시점에 서랍이 아직 차 있었습니다: {seen}"
    )


def test_logout_async_still_drops_the_local_session_when_the_server_call_fails():
    """서버 로그아웃이 실패(또는 취소)해도 **로컬 세션은 반드시 폐기**됩니다."""
    async def _scenario(user_store, client_store):
        def _boom(_client):
            raise RuntimeError('supabase down')

        auth.sign_out = _boom
        user_store.data[auth.SB_TOKENS_KEY] = {"access_token": "A", "refresh_token": "B"}
        client_store.data[auth.SB_CLIENT_KEY] = _FakeAuthClient([])
        await auth.logout_async()                   # 예외가 밖으로 새면 안 됩니다

    _r, user_store, client_store, _log = _with_tripwire_storage(_scenario)
    assert auth.SB_TOKENS_KEY not in user_store.data
    assert auth.SB_CLIENT_KEY not in client_store.data


def test_current_user_async_never_touches_storage_and_runs_off_the_loop():
    """🔐 `current_user_async(client)` — `client` 를 **인자로** 받고 저장소를 안 만집니다.

    스레드 안에서 `get_client()` 를 다시 부르는 식으로 "고치면" 곧바로 2026-08-17 사고가
    재현됩니다. 그래서 저장소 접근이 0회라는 사실 자체를 못 박습니다.
    """
    async def _scenario(_user_store, _client_store):
        log = []
        client = _FakeAuthClient(log)
        user = await auth.current_user_async(client)
        return user, log, threading.current_thread()

    (user, log, loop_thread), user_store, client_store, _ = _with_tripwire_storage(_scenario)

    assert user == {"id": "uid-1", "email": "a@example.com"}
    assert not user_store.violations and not client_store.violations
    assert not user_store.data and not client_store.data, (
        "current_user_async() 는 저장소를 읽지도 쓰지도 않아야 합니다"
    )
    calls = [row for row in log if row[0] == "get_user"]
    assert len(calls) == 1
    if not STUBBED:
        assert calls[0][1] is not loop_thread, (
            "get_user() 왕복이 이벤트 루프에서 일어났습니다 — 로그인이 필요한 화면 5개가 "
            "본문을 그리기 전에 반드시 거치는 자리라 영향이 가장 큽니다."
        )


def test_current_user_async_returns_none_without_a_client():
    """클라이언트가 없으면 스레드를 만들 것도 없이 None (동기판과 같은 규약)."""
    assert asyncio.run(auth.current_user_async(None)) is None


# =============================================================================
# [4] 소스 수준 회귀 방지 — 다시 동기 호출로 돌아가지 않도록
# =============================================================================
WEB_FILES = sorted(
    p for p in (REPO_ROOT / "web").rglob("*.py") if "__pycache__" not in str(p)
)

# 이벤트 루프 위에서 부르면 안 되는 함수들(전부 네트워크 왕복 또는 큰 파일 읽기).
BLOCKING_NAMES = {
    # ── Supabase / postgrest / gotrue ──────────────────────────────────────
    "sign_in", "sign_out", "sign_up", "current_user", "set_session",
    "fetch_holdings", "insert_holding", "update_holding", "delete_holding", "add_lot",
    "ocr_quota_status", "consume_ocr_quota",
    "send_password_reset_code", "reset_password_with_code",
    "fetch_user_snapshots", "fetch_user_holding_snapshots",
    "fetch_my_accounts", "fetch_my_positions", "fetch_my_orders", "fetch_my_cash_ledger",
    "fetch_my_snapshots", "fetch_my_holding_snapshots",
    "save_order", "edit_order", "cancel_order", "opt_in",
    "save_consent", "fetch_my_consent", "revoke_consent",
    "ensure_nickname", "fetch_my_nickname",
    "fetch_public_leaderboard", "fetch_public_leaderboard_latest_date",
    "fetch_public_holdings_for_nickname",
    # ── 파일 / 원격 읽기 ────────────────────────────────────────────────────
    "load_stock_history", "benchmark_closes_for_market", "load_kospi_close_history",
    "load_us_index_closes", "primary_benchmark_value", "load_json_file",
    "load_latest_kospi_usd", "_load_history_df", "fetch_verified_market_data",
    "read_download_bytes", "extract_holdings_from_image", "read_csv", "read_json",
}

# 동기로 불러도 되는 예외 자리 — **사유를 반드시 함께 적으세요.**
SYNC_CALL_ALLOWED = {
    ("web/auth.py", "get_client"):
        "문서화된 동기 쌍둥이. 화면은 get_client_async() 를 쓰고, 이쪽은 이벤트 루프 "
        "밖에서 저장소 격리를 검증하는 tests/test_web_session_isolation.py 가 씁니다.",
    ("web/auth.py", "logout"):
        "위와 같은 이유의 동기 쌍둥이(logout_async 가 화면용).",
    ("web/auth.py", "_restore_session"):
        "이 함수 자체가 run_blocking 으로 스레드에서 실행되는 대상입니다.",
    ("web/pages/pegy_page.py", "load_latest_kospi_usd"):
        "함수 자기 자신의 본문(pandas.read_csv). run_blocking 이 스레드에서 돌립니다.",
    ("web/pages/pegy_page.py", "_snapshot_csv_bytes"):
        "다운로드 버튼 클릭 시에만 실행되고, download_button 이 이미 run.io_bound 로 "
        "별도 스레드에서 돌립니다(1차 수정에서 확인된 자리).",
    ("web/pages/pegy_page.py", "_render_raw_downloads"):
        "download_button 에 넘기는 람다 안. 실행 시점은 클릭이고, 그때 run.io_bound 를 탑니다.",
    ("web/pages/us_stocks_page.py", "_render_raw_downloads"):
        "위와 동일(다운로드 버튼 람다).",
    ("web/pages/macro_page.py", "_render_trend_chart"):
        "위와 동일(_csv_bytes 람다 → download_button → run.io_bound).",
    ("web/pages/macro_page.py", "fetch_verified_market_data"):
        "함수 자기 자신의 본문(원본 계산 로직 그대로). run_blocking 이 스레드에서 돌립니다.",
    ("web/pages/macro_page.py", "_load_history_df"):
        "위 함수가 스레드 안에서 부르는 내부 헬퍼(pandas.read_csv).",
    ("web/pages/scorecard_page.py", "_render_row_manager"):
        "on_click 람다가 async def _delete(...) 의 코루틴을 돌려주고, NiceGUI 가 그걸 "
        "await 해 줍니다(nicegui.events.handle_event). 루프를 막지 않습니다.",
}


def _owner_map(tree):
    owner = {}
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for sub in ast.walk(fn):
            owner.setdefault(id(sub), fn.name)
    return owner


def test_no_blocking_call_is_left_on_the_event_loop():
    """web/ 전체를 훑어 "동기로 그냥 부른" 블로킹 호출이 남아 있지 않은지 확인합니다."""
    offenders = []
    for path in WEB_FILES:
        rel = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _owner_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in BLOCKING_NAMES:
                continue
            holder = owner.get(id(node), "<모듈 최상위>")
            if (rel, holder) in SYNC_CALL_ALLOWED:
                continue
            offenders.append(f"{rel}:{node.lineno} `{name}(...)` inside `{holder}()`")

    assert not offenders, (
        "이벤트 루프 위에서 도는 블로킹 호출이 남아 있습니다:\n  "
        + "\n  ".join(offenders)
        + "\n→ `await run_blocking(그함수, ...)` 로 감싸세요(web/blocking.py). 정말 예외라면 "
          "SYNC_CALL_ALLOWED 에 **사유와 함께** 추가하세요."
    )


def test_run_blocking_is_never_handed_an_already_executed_call():
    """`run_blocking(f(x))` 는 f 를 **루프에서 먼저 실행**해 버립니다 — 절대 금지.

    올바른 형태는 `run_blocking(f, x)` 입니다. 눈으로는 거의 구별이 안 되는 실수라
    (괄호 위치 하나 차이) 자동으로 잡습니다.
    """
    offenders = []
    for path in WEB_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("run_blocking", "io_bound"):
                continue
            rel = str(path.relative_to(REPO_ROOT))
            if not node.args:
                offenders.append(f"{rel}:{node.lineno} {name}() 에 대상 함수가 없습니다")
            elif isinstance(node.args[0], ast.Call):
                offenders.append(
                    f"{rel}:{node.lineno} {name}() 의 첫 인자가 **호출식**입니다 — "
                    "그 호출은 이벤트 루프에서 그대로 실행됩니다")
    assert not offenders, "\n".join(offenders)


def test_every_page_function_is_async_with_an_explicit_response_timeout():
    """`@ui.page` 함수는 전부 `async def` + `response_timeout=` 이어야 합니다.

    · `async def` 가 아니면 그 안의 모든 로드가 다시 이벤트 루프 위에서 돕니다.
    · NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다.
      명시하지 않으면 조금만 느려도 화면 대신 **영어 500 오류 페이지**가 나갑니다
      (§0-3-4 위반이자, 이번 수정의 목적과 정반대).
    """
    # 데이터·네트워크를 전혀 쓰지 않아 3초 제한이 문제되지 않는 화면만 예외입니다.
    NO_IO_PAGES = {("web/pages/admin_page.py", "admin_page")}

    found = []
    for path in WEB_FILES:
        rel = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            pages = [d for d in node.decorator_list
                     if isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "page"]
            if not pages:
                continue
            found.append((rel, node.name))
            if (rel, node.name) in NO_IO_PAGES:
                continue
            assert isinstance(node, ast.AsyncFunctionDef), (
                f"{rel}::{node.name}() 이 동기 함수입니다 — 안의 데이터 로드가 다시 "
                "이벤트 루프를 막습니다."
            )
            keywords = {kw.arg for kw in pages[0].keywords}
            assert "response_timeout" in keywords, (
                f"{rel}::{node.name}() 에 response_timeout 이 없습니다 — 비동기 페이지에는 "
                "NiceGUI 가 3초 기본 제한을 겁니다(web/state.PAGE_RESPONSE_TIMEOUT_SECONDS)."
            )

    assert len(found) >= 8, f"찾은 @ui.page 함수가 너무 적습니다: {found}"


def test_the_home_page_search_box_no_longer_reads_files_on_the_loop():
    """오너가 실제로 끊김을 겪은 자리 — 홈/미국 화면의 **종목 검색창**.

    `render_stock_download_tool()` 은 검색 결과를 그릴 때마다 종목별 이력 CSV 를 읽습니다
    (원격 모드에서는 `requests.get()`). 이 함수와 그 호출부가 다시 동기로 돌아가면
    2026-08-21 사고가 그대로 재현됩니다.
    """
    src = (REPO_ROOT / "web" / "components" / "stock_download.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for name in ("render_stock_download_tool", "_results", "_render_target"):
        assert name in funcs, f"{name}() 이 사라졌습니다"
        assert isinstance(funcs[name], ast.AsyncFunctionDef), (
            f"stock_download.py::{name}() 이 다시 동기 함수가 되었습니다"
        )
    assert "await run_blocking(\n                    load_stock_history" in src, (
        "이력 CSV 읽기가 run_blocking 을 거치지 않습니다"
    )

    # 두 호출부(홈 '/' 와 미국 '/us')가 실제로 await 하는지.
    for page in ("pegy_page.py", "us_stocks_page.py"):
        page_tree = ast.parse((REPO_ROOT / "web" / "pages" / page).read_text(encoding="utf-8"))
        awaited = [
            n for n in ast.walk(page_tree)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", None) == "render_stock_download_tool"
        ]
        assert len(awaited) == 1, (
            f"{page} 가 render_stock_download_tool() 을 await 하지 않습니다 — "
            "코루틴만 만들어 놓고 버리면 검색 도구가 통째로 그려지지 않습니다."
        )
