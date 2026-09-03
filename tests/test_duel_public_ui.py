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
    [3] 🗑️ 은퇴 확인 — 두 화면 파일·`DUEL_CONSENT_*`/`DUEL_LEADERBOARD_*` 스위치·메뉴
        항목이 정말로 사라졌는가, 그러면서 `/duel` 쪽 스위치는 그대로인가.

    (🗑️ [1] 발행표 조회 검증은 2026-09-03 에, [2] 발행 배치 스크립트 검증은 2026-08-25 에
     각각 검증 대상이 삭제되면서 함께 지웠습니다 — 아래 [3] 앞의 주석 참고.)

실행: pytest tests/test_duel_public_ui.py -v
"""

import importlib
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))


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


# 🗑️ 2026-09-03 — 이 자리에 있던 「1. 발행표 조회」 10개 테스트(`duel_db.fetch_public_leaderboard*`
#    / `fetch_public_holdings_for_nickname` 검증)를 지웠습니다. 검증 대상 함수와 표 상수
#    (`PUBLIC_LEADERBOARD_TABLE` · `PUBLIC_HOLDINGS_TABLE` · `PUBLIC_*_COLUMNS`)가
#    `utils/duel_db.py` 에서 삭제됐기 때문입니다 — 그 표 두 개는 2026-08-23 마이그레이션
#    (`sql/scorecard_public_schema.sql` §0)에서 drop 됐고, 함수는 저장소 어디에서도
#    호출되지 않았습니다(2026-08-25 주석이 "이번 정리 범위 밖"으로 남겨 뒀던 것을 이번에
#    실행). 후임 순위표 읽기 함수의 검증은 `tests/test_scorecard_publish.py` 에 있습니다.
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
