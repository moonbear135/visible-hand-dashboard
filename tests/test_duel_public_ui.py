# tests/test_duel_public_ui.py
"""
⚔️ "결투다!" 2갈래(공개 인프라) — **발행표 조회 계층 + 발행 배치 스크립트** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요 · nicegui 설치 여부와 무관)

-------------------------------------------------------------------------------
🗑️ 2026-08-23 — 이 파일에서 **화면 2종 검증이 통째로 빠졌습니다** (은퇴)
-------------------------------------------------------------------------------
`web/pages/duel_consent_page.py`(`/duel/consent`)와
`web/pages/duel_leaderboard_page.py`(`/duel/leaderboard`)가 **파일째 삭제**됐습니다. 공개
대상이 결투 가상계좌 성적에서 **"내 성적표"(실제 보유 자산)** 로 바뀌면서 두 화면이
`web/pages/scorecard_consent_page.py` · `web/pages/scorecard_leaderboard_page.py` 로
교체됐기 때문입니다(문구·구조·읽는 표가 전부 달라진 교체라 부분 수정이 아닙니다).

그래서 이 파일에 있던 아래 검증들은 **`tests/test_scorecard_public_ui.py` 로 옮겨졌습니다**:
    · 동의 화면의 핵심 규칙(전부 아니면 전무 · 최종 확인 분리 · 철회 확인 단계)
    · 순위표 화면의 고정 문구 · 표시 규칙 · 원본 표 격리 · XSS 이스케이프
    · 3단계 공개 게이트 배선과 렌더 스모크
같은 검사를 두 벌 두지 않으려고 여기서는 지웠습니다(§0-3-10). 아래 [3] 이 "정말로
은퇴했는가"(파일도 스위치도 메뉴 항목도 남아 있지 않은가)를 대신 고정합니다.

⚠️ **`/duel`(1갈래 "덤벼라 나 자신")은 이 전환과 아무 관계가 없습니다.** `duel_page.py` ·
   `duel_accounts`/`duel_orders`/`duel_positions`/`duel_cash_ledger` · `DUEL_ENABLED` /
   `DUEL_MENU_ADMIN_ONLY` 는 한 글자도 바뀌지 않았습니다.

-------------------------------------------------------------------------------
지금 이 파일이 검증하는 것
-------------------------------------------------------------------------------
    [1] `duel_db.fetch_public_leaderboard*` / `fetch_public_holdings_for_nickname`
        — 맞는 표에, 맞는 필터·정렬·페이지 범위로 가는가. 빈 결과는 정상인가.
        — `select("*")` 를 쓰지 않는가(§0-3-8 — 나중에 컬럼이 늘어도 새어나가지 않게).
    [2] 발행 배치 실행 스크립트·워크플로우 — 판단하지 않고 위임만 하는가, 체결 배치 뒤에
        도는가.
    [3] 🗑️ 은퇴 확인 — 두 화면 파일·`DUEL_CONSENT_*`/`DUEL_LEADERBOARD_*` 스위치·메뉴
        항목이 정말로 사라졌는가, 그러면서 `/duel` 쪽 스위치는 그대로인가.

가짜 Supabase 클라이언트는 **새로 만들지 않고** `tests/test_duel_db.py` 의 `FakeClient` 를
그대로 가져다 씁니다(§0-3-10 — 같은 흉내를 두 벌 만들지 않습니다).

실행: pytest tests/test_duel_public_ui.py -v
"""

import importlib
import os
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


# =============================================================================
# 0. 스텁 — nicegui 와 아직 이 스냅샷에 없는 web/* 모듈 (있으면 진짜를 씁니다)
# =============================================================================
def _install_stubs():
    """
    `web/layout.py` 를 import 할 수 있게 최소 스텁을 꽂습니다. **이미 진짜가 있으면 손대지
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
            대체합니다(`web/blocking.run_blocking()` 이 이걸 씁니다)."""

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


_install_stubs()


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
    빈 결과는 **오류가 아니라 정상**입니다(최소 인원 미달 그룹은 발행되지 않습니다).
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
    동의하지 않은 항목은 발행 배치가 **null 로** 넣습니다. 조회 계층이 그것을 0 으로
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
    🔴 순위표 읽기 경로가 원본 표를 스치지 않는지. 세 함수를 실제로 불러 보고, **오간
    질의의 표 이름**이 발행표 2개뿐인지 확인합니다.
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
# 2. 발행 배치 실행 스크립트 · 워크플로우
# =============================================================================
def test_publish_runner_delegates_and_never_decides():
    """
    루트 실행 스크립트는 **I/O 와 환경**만 다룹니다. 판단(누가 발행 대상인지 등)이 여기로
    새어 들어오면 `tests/test_duel_publish.py` 가 검증하지 못하는 로직이 생깁니다
    (`run_duel_daily_batch.py` 와 같은 분업).
    """
    import ast

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
# 3. 🗑️ 은퇴 확인 (2026-08-23) — 정말로 사라졌는가, 그리고 /duel 은 그대로인가
# =============================================================================
def test_duel_public_screens_are_really_gone():
    """
    🗑️ 결투 공개 계층의 화면 2종이 **파일째** 사라졌는지. "쓰이지 않는 동의 화면 코드가
    저장소 어딘가에 남아 있는 것"은 이 저장소에서 가장 위험한 종류의 잔여물입니다 —
    누군가 `main.py` 에 import 한 줄만 되살리면 옛 문구·옛 표로 다시 동작하기 때문입니다.
    """
    for name in ("duel_consent_page.py", "duel_leaderboard_page.py"):
        assert not (REPO_ROOT / "web" / "pages" / name).exists(), \
            f"은퇴한 화면 파일이 아직 있습니다: web/pages/{name}"

    main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    for name in ("scorecard_consent_page", "scorecard_leaderboard_page"):
        assert name in main_source, f"main.py 가 {name} 를 import 하지 않습니다"
    # 후임 화면 파일은 실제로 있어야 합니다(지우기만 하고 안 만든 상태를 잡습니다).
    for name in ("scorecard_consent_page.py", "scorecard_leaderboard_page.py"):
        assert (REPO_ROOT / "web" / "pages" / name).exists()


def test_duel_public_flags_are_gone_but_duel_itself_is_untouched():
    """
    🗑️ `DUEL_CONSENT_*` / `DUEL_LEADERBOARD_*` 네 스위치가 `web/layout.py` 에서 사라졌는지,
    그러면서 **`/duel` 자체를 지배하는 두 스위치는 그대로**인지.

    ⚠️ 이 두 가지를 한 검사에 묶어 둔 것이 의도입니다 — "공개 계층을 은퇴시키다가 1갈래까지
       건드렸다"가 이 변경에서 가장 하기 쉬운 실수라서, 사라진 것과 남아야 하는 것을 같은
       자리에서 확인합니다.
    """
    import web.layout as layout_module

    layout_module = importlib.reload(layout_module)
    for gone in ("DUEL_CONSENT_ENABLED", "DUEL_CONSENT_MENU_ADMIN_ONLY",
                 "DUEL_LEADERBOARD_ENABLED", "DUEL_LEADERBOARD_MENU_ADMIN_ONLY"):
        assert not hasattr(layout_module, gone), \
            f"은퇴한 스위치가 web/layout.py 에 남아 있습니다: {gone}"

    # 🔴 /duel 은 그대로 — 이름도, 기본값도.
    assert layout_module.DUEL_ENABLED is False, "환경변수 없이는 꺼져 있어야 합니다(§0-3-6)"
    assert layout_module.DUEL_MENU_ADMIN_ONLY is False, \
        "2026-08-22 오너 확정(전체 공개)이 이 변경으로 바뀌면 안 됩니다"

    assert not [p for p in (item[0] for item in layout_module._MENU)
                if p.startswith("/duel/")], "은퇴한 2갈래 메뉴 항목이 남아 있습니다"


def test_enabling_duel_only_adds_the_branch_one_menu_item():
    """
    `DUEL_ENABLED=true` 로 켜면 `/duel` **하나만** 생깁니다(예전에는 이 블록 안에서
    `/duel/consent`·`/duel/leaderboard` 가 함께 생길 수 있었습니다).
    """
    import web.layout as layout_module

    saved = os.environ.get("DUEL_ENABLED")
    os.environ["DUEL_ENABLED"] = "true"
    try:
        reloaded = importlib.reload(layout_module)
        paths = [path for path, _label, _admin_only in reloaded._MENU]
    finally:
        if saved is None:
            os.environ.pop("DUEL_ENABLED", None)
        else:
            os.environ["DUEL_ENABLED"] = saved
        importlib.reload(layout_module)

    assert [p for p in paths if p.startswith("/duel")] == ["/duel"]
