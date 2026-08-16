# tests/test_web_session_isolation.py
"""
🔴 동시 접속 세션 격리 검증 — ENGINEERING_SPEC.md §0-3-8 (이 프로젝트 최상위 금지사항)

오너 지시 원문(2026-08-16): *"개인 자산이 노출 될 수 있는 문제는 집안환경에 따라서 예민하고
분쟁을 일으킬 수 있는 사항이야 … 절대로 개인정보가 꼬여서 노출되는 문제는 발생하면 안되"*

즉 이 테스트가 지키려는 것은 화면의 모양이 아니라 **"서로 다른 브라우저로 동시에 로그인한
두 사람의 보유종목·매입가·손익이 서버 안에서 단 1바이트도 섞이지 않는다"** 하나입니다.
이전 계획서 §9 "4. scorecard" 완료기준 ⑦ — **이 테스트가 실패하면 다른 항목이 전부
통과해도 scorecard 화면은 절대 공개하지 않습니다.**

────────────────────────────────────────────────────────────────────────────
무엇을 어떻게 검증하는가 (그리고 무엇을 못 하는가 — §0-1 정직하게)

  [1] 정적 분석 (AST) — "구조적으로 섞일 수 없는가"
      `web/**/*.py` + `main.py` 를 파싱해서
        · 모듈 최상위(함수/클래스 밖)에 **가변 전역**(dict/list/set)이 새로 생기지 않았는지
          — 읽기 전용 시장데이터 캐시(`web/state.py::_JSON_CACHE`)처럼 안전한 것만 화이트리스트
            (§0-3-8 "읽기 전용 시세 캐시는 전역이어도 안전, 사용자 데이터는 절대 금지" 구분선)
        · 사용자 데이터를 연상시키는 이름(client/user/token/session/holding/…)의 전역이
          **불변 상수 이외의 값**을 갖고 있지 않은지
        · `global` 선언으로 모듈 상태를 다시 묶는 코드가 없는지 (`_client = None` 패턴 차단)
        · 전역 초기화에 `create_supabase_client()` 같은 **사용자 세션을 만드는 호출**이 없는지
        · `app.storage.*` 를 만지는 코드가 `web/auth.py` 의 접근자 2개 안에만 있는지
      → 이 검사들은 "지금 코드가 맞다"가 아니라 **"앞으로 누가 잘못 고치면 즉시 잡힌다"**는
        회귀 안전망이 목적입니다.

  [2] 동작 시뮬레이션 — "실제로 호출해봐도 안 섞이는가"
      `web/auth.py` 의 `get_client()` / `login()` / `logout()` 을 **진짜로 호출**합니다.
      NiceGUI 의 `app.storage.user` / `app.storage.client` 자리에 "가짜 접속 A / B / C" 의
      dict 를 꽂아 넣고(=`web/auth.py` 가 저장소 접근을 함수 2개로 모아둔 이유),
      A로 로그인 → B로 로그인 → A 로그아웃 순서로 진행하며 매 단계마다
      "상대방 서랍이 그대로인지"를 확인합니다.

  [3] 화면 배선 검사 — `web/pages/scorecard_page.py` 가 client/user_id 를 **인자로** 받는지,
      전역에서 사용자를 추측하는 코드가 없는지, XSS 이스케이프·차트 높이 등.

  [5]~[7] 2026-08-17(5단계) 추가 — 로그인이 필요한 **두 번째 화면**
      `web/pages/report_page.py`(사장님 보고서)에 [3]과 같은 기준을 그대로 적용하고,
      표·기간이동을 실제로 실행해 보며(스모크), 두 화면이 **같은 로그인 세션**을 쓰는지를
      함께 검증합니다. 로그인이 필요한 화면이 늘어날 때마다 이 목록도 같이 늘립니다.

  ⚠️ 이 샌드박스에서 **검증하지 못한 것**(배포 후 오너 실기기 확인 필요):
      · 진짜 NiceGUI 서버 프로세스에서 `app.storage.client` 가 접속마다 실제로 다른 dict 를
        돌려주는지(= NiceGUI 내부 contextvar 동작 자체). 이 테스트는 "우리 코드가 그 두 저장소를
        올바르게 구분해서 쓰는가"까지만 증명합니다. NiceGUI 자체 동작은 프레임워크의 문서화된
        계약(`storage.client` = 접속별, `storage.user` = 쿠키별)에 의존합니다.
      · 실제 Supabase RLS 가 남의 행을 막는지(그건 DB 계층 — sql/scorecard_schema.sql 과
        tests/test_scorecard.py 가 담당).

실행: python tests/test_web_session_isolation.py
"""

import ast
import asyncio
import io
import re
import sys
import types
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

FAILURES = []


def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


# =============================================================================
# 검사 대상 파일 (NiceGUI 표현 계층 전체)
# =============================================================================
def target_files():
    files = sorted(p for p in (REPO_ROOT / "web").rglob("*.py") if "__pycache__" not in p.parts)
    files.append(REPO_ROOT / "main.py")
    return files


def rel(path):
    return path.relative_to(REPO_ROOT).as_posix()


def python_code_only(src):
    """주석·독스트링을 걷어낸 파이썬 '실행되는 코드'만 남깁니다.

    (설명 주석에 `st.session_state` 같은 문구가 적혀 있다고 실제로 그 경로가 있는 건
     아니므로, "코드에 없는지"를 볼 때는 반드시 이걸 통과시킨 문자열로 확인합니다.
     `tests/test_report.py` 의 같은 이름 함수와 동일한 규칙입니다.)
    """
    without_docstrings = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)
    return "\n".join(line for line in without_docstrings.splitlines()
                     if not line.strip().startswith("#"))


def module_level_statements(tree):
    """모듈 최상위 스코프의 문장들 (try/if/with/for 안까지 들어가되, 함수·클래스 안은 제외).

    `try: import plotly ... except ImportError: PLOTLY_AVAILABLE = False` 처럼 조건부로
    선언되는 전역도 전역이므로 함께 봅니다. 반대로 함수 안의 지역변수는 접속마다 새로
    만들어지므로 검사 대상이 아닙니다.
    """
    out = []
    stack = list(tree.body)
    while stack:
        node = stack.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        out.append(node)
        for field in ("body", "orelse", "finalbody"):
            stack.extend(getattr(node, field, []) or [])
        for handler in getattr(node, "handlers", []) or []:
            stack.extend(handler.body)
    return out


def assigned_names(node):
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    else:
        return []
    return [t.id for t in targets if isinstance(t, ast.Name)]


# =============================================================================
# [1-a] 모듈 최상위 가변 전역 — 화이트리스트에 없으면 실패
# =============================================================================
#  ⚠️ 여기에 새 항목을 추가하려면 **왜 이 전역이 사용자 데이터를 담을 수 없는지**를 사유로
#     적으세요. "지금은 안 담는다"가 아니라 "구조적으로 담길 수 없다"여야 합니다.
#     (§0-3-8 — 읽기 전용 시세 데이터는 전역이 정답, 사용자 데이터는 절대 금지)
ALLOWED_MUTABLE_GLOBALS = {
    ("web/state.py", "_JSON_CACHE"):
        "읽기 전용 시장 데이터(data/*.json) 캐시. 모든 접속자에게 동일한 시세이며 "
        "개인정보가 아님 (§0-3-8 구분선 · 계획서 §3-3 규칙 4). 키는 파일 경로뿐.",
    ("web/components/widgets.py", "_BANNER_PALETTE"):
        "배너 색상 상수표(문자열 튜플). 값이 CSS 색상 문자열이라 데이터가 들어갈 자리가 없음.",
    ("web/layout.py", "_MENU"):
        "메뉴 정의(경로·라벨·관리자전용 플래그). 고정 문자열/불리언뿐.",
    ("web/pages/pegy_page.py", "FILTER_PRESETS"):
        "필터 드롭다운 항목(고정 문자열 목록).",
    ("web/pages/us_stocks_page.py", "FILTER_PRESETS"):
        "필터 드롭다운 항목(고정 문자열 목록).",
    ("web/pages/scorecard_page.py", "CURRENCY_TITLES"):
        "통화 코드 → 소제목 문구(고정 문자열).",
    ("web/pages/scorecard_page.py", "_CHART_LAYOUT"):
        "plotly 차트 배경/글자색 설정(고정 문자열·숫자). 차트 데이터는 여기 담기지 않음.",
    ("web/pages/report_page.py", "MARKET_TITLES"):
        "시장 코드 → 소제목 문구(고정 문자열). 사용자 데이터가 들어갈 자리가 없음.",
}

_MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque"}


def _is_mutable_value(value):
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        return name in _MUTABLE_CALLS
    return False


def test_no_mutable_globals():
    print("\n[1-a] 모듈 최상위 가변 전역 (사용자 데이터가 숨을 수 있는 유일한 자리)")
    found = 0
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in module_level_statements(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            if not _is_mutable_value(getattr(node, "value", None)):
                continue
            for name in assigned_names(node):
                found += 1
                key = (rel(path), name)
                check(
                    key in ALLOWED_MUTABLE_GLOBALS,
                    f"{rel(path)}:{node.lineno} 전역 `{name}` (가변 컨테이너) 이 허용 목록에 있음",
                    "← 사용자 데이터를 담을 수 있는 새 전역입니다. 페이지 함수의 지역변수로 "
                    "옮기거나, 정말 읽기 전용 시장데이터라면 ALLOWED_MUTABLE_GLOBALS 에 사유와 "
                    "함께 등록하세요 (§0-3-8).",
                )
    check(found >= len(ALLOWED_MUTABLE_GLOBALS),
          f"검사기가 실제로 전역을 훑고 있음(발견 {found}건)",
          "← 0건이면 파서가 아무것도 못 보고 있다는 뜻이라 검사 자체가 무의미합니다.")


# =============================================================================
# [1-b] 사용자 데이터를 연상시키는 이름의 전역은 '불변 상수'만 허용
# =============================================================================
USER_DATA_TOKENS = (
    "client", "user", "token", "session", "holding", "portfolio", "profile",
    "auth", "login", "email", "password", "credential", "account", "asset", "secret",
)

# 이름에 위 단어가 들어가지만 사용자 데이터가 아닌 것 — 사유와 함께 명시적으로 허용합니다.
ALLOWED_USER_NAMED_GLOBALS = {
    ("main.py", "STORAGE_SECRET"):
        "NiceGUI 쿠키 서명키(서버 전체에 하나). 특정 사용자의 데이터가 아니며 환경변수에서 "
        "읽어 ui.run() 에 한 번 넘기고 끝. 값이 로그·화면에 출력되는 경로가 없음(§0-3-9).",
}


def _is_immutable_constant(value):
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Tuple):
        return all(isinstance(e, ast.Constant) for e in value.elts)
    if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
        return True
    return False


def test_user_named_globals_are_constants():
    print("\n[1-b] 사용자 데이터 이름의 전역은 불변 상수(문자열/숫자)만 허용")
    inspected = 0
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in module_level_statements(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            for name in assigned_names(node):
                if not any(token in name.lower() for token in USER_DATA_TOKENS):
                    continue
                inspected += 1
                key = (rel(path), name)
                if key in ALLOWED_USER_NAMED_GLOBALS:
                    check(True, f"{rel(path)}:{node.lineno} 전역 `{name}` — 사유 등록된 예외")
                    continue
                check(
                    _is_immutable_constant(getattr(node, "value", None)),
                    f"{rel(path)}:{node.lineno} 전역 `{name}` 이 불변 상수임(데이터를 담을 수 없음)",
                    "← 사용자 데이터를 연상시키는 이름의 전역에 상수가 아닌 값이 대입됐습니다. "
                    "이런 이름은 저장소 키(문자열 상수)일 때만 전역에 둘 수 있습니다 (§0-3-8).",
                )
    check(inspected >= 2,
          f"이름 기반 검사가 실제로 동작 중(대상 {inspected}건)",
          "← web/auth.py 의 SB_TOKENS_KEY/SB_CLIENT_KEY 만으로도 2건 이상이어야 정상입니다.")


# =============================================================================
# [1-c] `global` 선언 금지 + 전역 초기화에서 세션 생성 호출 금지
# =============================================================================
FORBIDDEN_GLOBAL_CALLS = {
    "create_supabase_client", "get_client", "new_auth_client", "login", "sign_in",
    "current_user", "fetch_holdings", "add_lot", "user_storage", "client_storage",
}


def test_no_global_rebinding():
    print("\n[1-c] `global` 재바인딩 금지 · 전역 초기화에서 세션 생성 금지")
    global_stmts = []
    bad_calls = []
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                global_stmts.append(f"{rel(path)}:{node.lineno} global {', '.join(node.names)}")
        for node in module_level_statements(tree):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    if name in FORBIDDEN_GLOBAL_CALLS:
                        bad_calls.append(f"{rel(path)}:{sub.lineno} {name}()")

    check(not global_stmts,
          "`global` 선언이 한 곳도 없음 (`_client = None` + `global _client` 패턴 차단)",
          f"발견: {global_stmts}")
    check(not bad_calls,
          "모듈 로딩 시점에 사용자 세션을 만드는 호출이 없음",
          f"발견: {bad_calls} ← import 시 만들어진 객체는 전 접속자가 공유합니다(§0-3-8).")


# =============================================================================
# [1-d] app.storage 접근 지점은 web/auth.py 의 접근자 2개뿐
# =============================================================================
def test_storage_access_is_centralised():
    print("\n[1-d] app.storage 접근 지점 집중 (감사 지점 1곳)")
    offenders = []
    accessor_hits = set()

    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 함수별로 훑어서 "어느 함수 안에서 app.storage 를 만졌는지" 를 기록합니다.
        parents = {}
        for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for sub in ast.walk(func):
                parents[id(sub)] = func.name

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            # `app.storage.user` / `app.storage.client` → Attribute(value=Attribute(value=Name('app')))
            base = node.value
            if not (isinstance(base, ast.Attribute) and base.attr == "storage"
                    and isinstance(base.value, ast.Name) and base.value.id == "app"):
                continue
            owner = parents.get(id(node))
            where = f"{rel(path)}:{node.lineno} (함수 {owner})"
            if rel(path) == "web/auth.py" and owner in ("user_storage", "client_storage"):
                accessor_hits.add(owner)
            else:
                offenders.append(where)

    check(not offenders,
          "app.storage 를 직접 만지는 코드가 web/auth.py 의 접근자 2개 밖에 없음",
          f"발견: {offenders} ← 저장소 접근을 흩뿌리면 어느 접속의 서랍인지 추적할 수 없게 "
          "되고, 자동 검증도 불가능해집니다 (§0-3-8).")
    check(accessor_hits == {"user_storage", "client_storage"},
          "web/auth.py 의 user_storage()/client_storage() 가 각각 app.storage 를 읽고 있음",
          f"실제: {sorted(accessor_hits)}")


# =============================================================================
# [2] 동작 시뮬레이션 — 가짜 접속 A / B / C 로 실제 함수 호출
# =============================================================================
def _install_nicegui_stub():
    """nicegui 미설치 환경에서도 web/ 모듈을 import 할 수 있게 최소 스텁을 주입합니다.

    (이 샌드박스에는 nicegui 를 설치할 수 없어 실제 서버를 띄울 수 없습니다 — 그래서
     "서버를 띄우는 대신 저장소 접근자만 바꿔치기한다"는 설계를 택했습니다. 자세한 한계는
     이 파일 맨 위 주석 참고.)
    """
    try:
        import nicegui  # noqa: F401
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

        def get(self, *_a, **_k):                 # @app.get('/healthz') 데코레이터용
            return lambda fn: fn

    class _Element:
        """어떤 위젯 흉내든 다 내는 객체 — 호출/속성접근/`with` 를 전부 받아넘깁니다.

        덕분에 화면 함수를 **실제로 실행**해볼 수 있습니다([4] 렌더 스모크 테스트).
        위젯이 그려지진 않지만 f-string·이스케이프·분기·계산은 전부 진짜로 돌아갑니다.
        """

        def __call__(self, *args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]                    # 데코레이터로 쓰인 경우
            return self

        def __getattr__(self, _name):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    element = _Element()

    class _Refreshable:
        """`@ui.refreshable` 흉내 — `.refresh()` 를 가진 호출 가능 객체여야 합니다."""

        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

        def refresh(self, *_a, **_k):
            return None                           # 스모크 테스트에서는 재귀 렌더를 하지 않습니다

    class _UI(types.ModuleType):
        refreshable = staticmethod(_Refreshable)

        def __getattr__(self, _name):
            return element

    class _Run(types.ModuleType):
        """`nicegui.run` 흉내 — `await run.io_bound(fn, *a, **kw)` 를 그냥 동기 호출로
        대체합니다. 오프라인 테스트에는 진짜 스레드풀/이벤트루프가 없으니 이걸로 충분하고,
        중요한 건 `web/pages/scorecard_page.py` 의 `from nicegui import run, ui` 임포트가
        깨지지 않는 것입니다(2026-08-17, 로그인 버튼 로딩 표시 수정분).
        """

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


class FakeConnection:
    """가짜 '접속' 하나 = 서로 완전히 분리된 서랍 두 개.

    실제 NiceGUI 에서는 `app.storage.user`(쿠키별) / `app.storage.client`(접속별)가
    이 역할을 합니다. 시크릿창을 새로 열면 쿠키가 다르므로 `user` 서랍부터 완전히 별개입니다.
    """

    def __init__(self, name):
        self.name = name
        self.user = {}
        self.client = {}


class FakeAuth:
    def __init__(self, owner):
        self.owner = owner
        self.session_token = None

    def set_session(self, access_token, refresh_token):
        self.owner.restored_with = (access_token, refresh_token)
        self.session_token = access_token

    def sign_out(self):
        self.session_token = None
        self.owner.signed_out = True


class FakeSupabaseClient:
    """Supabase 클라이언트 흉내. **중요한 건 이 객체가 로그인 세션을 품는다는 사실**입니다 —
    그래서 이 객체가 두 접속에서 같은 인스턴스면 그 자체가 사고입니다."""

    def __init__(self, serial):
        self.serial = serial
        self.auth = FakeAuth(self)
        self.restored_with = None
        self.signed_out = False

    def __repr__(self):
        return f"<FakeSupabaseClient #{self.serial} token={self.auth.session_token}>"


def test_two_sessions_do_not_mix():
    print("\n[2] 동작 시뮬레이션 — 가짜 접속 A/B/C 동시 로그인")
    _install_nicegui_stub()
    import web.auth as auth

    created = []

    def fake_create_client():
        client = FakeSupabaseClient(len(created) + 1)
        created.append(client)
        return client

    signed_in_on = []

    class _Session:
        def __init__(self, email):
            self.access_token = f"ACCESS::{email}"
            self.refresh_token = f"REFRESH::{email}"

    class _User:
        def __init__(self, email):
            self.email = email
            self.id = f"uid-{email}"

    class _Response:
        def __init__(self, email):
            self.session = _Session(email)
            self.user = _User(email)

    def fake_sign_in(client, email, password):
        # 진짜 supabase-py 도 로그인에 성공하면 **그 클라이언트 객체 안에** 세션을 붙입니다.
        # (바로 이 성질 때문에 클라이언트를 공유하면 남의 권한으로 DB를 읽게 됩니다 — §0-3-8)
        signed_in_on.append((client, email))
        client.auth.session_token = f"ACCESS::{email}"
        return _Response(email)

    def fake_sign_out(client):
        client.auth.sign_out()

    active = {"conn": None}

    # ── 여기가 이 테스트의 핵심 장치 ────────────────────────────────────────
    # web/auth.py 가 저장소 접근을 함수 2개로 모아둔 덕분에, 실제 서버 없이도
    # "지금 요청을 보낸 접속"을 바꿔가며 진짜 login()/get_client()/logout() 을 호출할 수 있습니다.
    original = (auth.user_storage, auth.client_storage,
                auth.create_supabase_client, auth.sign_in, auth.sign_out)
    auth.user_storage = lambda: active["conn"].user
    auth.client_storage = lambda: active["conn"].client
    auth.create_supabase_client = fake_create_client
    auth.sign_in = fake_sign_in
    auth.sign_out = fake_sign_out

    try:
        conn_a = FakeConnection("A(아빠 폰)")
        conn_b = FakeConnection("B(다른 사람의 시크릿창)")
        conn_c = FakeConnection("C(로그인 안 한 방문자)")

        # ── 1. A 로그인 ──────────────────────────────────────────────────
        # ⚠️ 2026-08-17 — login() 이 이제 async def 입니다(배포 후 "로그인이 안 된다"
        # 사고 원인 수정 — web/auth.py 의 login() docstring 참고: 저장소 접근은 이벤트
        # 루프에서, 네트워크 호출 한 줄만 run.io_bound 로). 테스트도 asyncio.run 으로 부릅니다.
        active["conn"] = conn_a
        user_a = asyncio.run(auth.login("a@example.com", "pw-a"))
        check(getattr(user_a, "email", None) == "a@example.com", "A 로그인 성공")
        check(conn_a.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::a@example.com", "refresh_token": "REFRESH::a@example.com"},
              "A의 토큰이 A의 저장소에만 들어감")
        check(conn_b.user == {}, "B의 저장소는 여전히 비어 있음 (A 로그인이 B에게 새지 않음)")
        check(conn_c.user == {} and conn_c.client == {}, "C의 저장소도 비어 있음")

        client_a = auth.get_client()
        check(conn_a.client.get(auth.SB_CLIENT_KEY) is client_a,
              "A의 클라이언트는 A의 접속 저장소(app.storage.client)에 보관됨")
        check(conn_b.client == {}, "B의 접속 저장소에는 클라이언트가 생기지 않음")

        # ── 2. B 로그인 (A가 로그인해 있는 동안) ─────────────────────────
        active["conn"] = conn_b
        asyncio.run(auth.login("b@example.com", "pw-b"))
        client_b = auth.get_client()

        check(conn_b.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::b@example.com", "refresh_token": "REFRESH::b@example.com"},
              "B의 토큰이 B의 저장소에 들어감")
        check(conn_a.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::a@example.com", "refresh_token": "REFRESH::a@example.com"},
              "🔴 B의 로그인 후에도 A의 토큰이 그대로 (덮어쓰기·오염 없음)")
        check(client_a is not client_b,
              "🔴 A와 B가 서로 다른 Supabase 클라이언트 객체를 받음 (같은 객체면 즉시 사고)")
        check(client_a.auth.session_token != client_b.auth.session_token,
              "🔴 두 클라이언트가 서로 다른 세션 토큰을 들고 있음")

        # 로그인 호출이 각자의 클라이언트에만 일어났는지
        check([c for c, _ in signed_in_on] == [client_a, client_b],
              "sign_in() 이 각 접속 자신의 클라이언트에만 호출됨",
              f"실제: {signed_in_on}")

        # ── 3. 같은 접속에서 다시 부르면 같은 객체(캐시), 다른 접속이면 다른 객체 ──
        active["conn"] = conn_a
        check(auth.get_client() is client_a, "같은 접속에서 get_client() 는 같은 객체를 재사용")
        active["conn"] = conn_b
        check(auth.get_client() is client_b, "다른 접속에서는 여전히 자기 객체")

        # ── 4. 로그인 안 한 접속 C ───────────────────────────────────────
        active["conn"] = conn_c
        check(auth.has_supabase_session() is False, "C는 로그인 상태가 아님")
        client_c = auth.get_client()
        check(client_c is not client_a and client_c is not client_b,
              "C도 자기만의 클라이언트를 받음")
        check(client_c.restored_with is None,
              "🔴 C의 클라이언트에는 어떤 세션도 복원되지 않음 (남의 토큰이 붙지 않음)")
        check(client_c.auth.session_token is None, "C의 클라이언트는 미로그인 상태")

        # ── 5. 새로고침 시나리오 — 접속 저장소만 비우고 다시 열기 ────────
        # (실제 NiceGUI 에서 새로고침하면 storage.client 는 폐기되고 storage.user 는 남습니다)
        active["conn"] = conn_a
        conn_a.client.clear()
        client_a2 = auth.get_client()
        check(client_a2 is not client_a, "새로고침 후에는 새 클라이언트가 만들어짐")
        check(client_a2.restored_with ==
              ("ACCESS::a@example.com", "REFRESH::a@example.com"),
              "🔴 새로고침 후 복원되는 토큰은 **A 자신의 것** (로그인 유지 + 남의 토큰 아님)")

        # ── 6. A 로그아웃 — B는 영향 없음 ────────────────────────────────
        active["conn"] = conn_a
        auth.logout()
        check(auth.SB_TOKENS_KEY not in conn_a.user, "A 로그아웃 후 A의 토큰이 지워짐")
        check(auth.SB_CLIENT_KEY not in conn_a.client, "A 로그아웃 후 A의 클라이언트가 폐기됨")
        check(client_a2.signed_out is True, "A의 클라이언트에 실제로 sign_out 이 호출됨")
        check(conn_b.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::b@example.com", "refresh_token": "REFRESH::b@example.com"},
              "🔴 A의 로그아웃이 B의 로그인 상태를 건드리지 않음")
        active["conn"] = conn_b
        check(auth.has_supabase_session() is True, "B는 계속 로그인 상태")
        check(auth.get_client() is client_b, "B의 클라이언트도 그대로 살아 있음")

        # ── 7. 만료된 세션 복원 실패 시 토큰을 남겨두지 않는가 ───────────
        conn_expired = FakeConnection("D(만료된 토큰)")
        conn_expired.user[auth.SB_TOKENS_KEY] = {"access_token": "X", "refresh_token": "Y"}
        active["conn"] = conn_expired

        def _boom(*_a, **_k):
            raise RuntimeError("refresh token expired")

        original_create = auth.create_supabase_client

        def _create_broken():
            client = fake_create_client()
            client.auth.set_session = _boom
            return client

        auth.create_supabase_client = _create_broken
        try:
            auth.get_client()
        finally:
            auth.create_supabase_client = original_create
        check(auth.SB_TOKENS_KEY not in conn_expired.user,
              "세션 복원 실패 시 죽은 토큰을 저장소에 남기지 않음 (로그인 안 된 상태로 정직하게 복귀)")

        # ── 8. 모듈 전역에 클라이언트가 새어나가지 않았는가 ──────────────
        leaked = _find_leaked_objects(auth, created)
        check(not leaked,
              "🔴 web/auth.py 모듈 전역 어디에도 Supabase 클라이언트가 남아있지 않음",
              f"발견: {leaked}")

    finally:
        (auth.user_storage, auth.client_storage,
         auth.create_supabase_client, auth.sign_in, auth.sign_out) = original


def _find_leaked_objects(module, objects):
    """모듈 전역(그리고 전역 dict/list 안 1단계)에 대상 객체가 참조되고 있는지 찾습니다."""
    wanted = {id(o) for o in objects}
    leaked = []
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if id(value) in wanted:
            leaked.append(name)
        elif isinstance(value, dict):
            for key, item in value.items():
                if id(item) in wanted:
                    leaked.append(f"{name}[{key!r}]")
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if id(item) in wanted:
                    leaked.append(f"{name}[…]")
    return leaked


# =============================================================================
# [3] 화면 배선 — scorecard_page.py 가 client/user_id 를 인자로 받는가
# =============================================================================
def test_scorecard_page_wiring():
    print("\n[3] web/pages/scorecard_page.py 배선")
    path = REPO_ROOT / "web" / "pages" / "scorecard_page.py"
    check(path.exists(), "web/pages/scorecard_page.py 존재")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # (a) DB를 만지는 함수는 client·user_id 를 **인자로** 받아야 합니다 (§0-3-8 함수 설계 원칙)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_render_body", "_render_portfolio", "_render_input_form",
                 "_render_currency_block", "_render_row_manager", "_render_edit_card", "_delete"):
        node = funcs.get(name)
        args = [a.arg for a in node.args.args] if node else []
        check(node is not None and "client" in args and "user_id" in args,
              f"`{name}()` 이 client·user_id 를 인자로 받음", f"실제 인자: {args}")

    # (b) DB 호출에 client 가 첫 인자로 들어가는지 (전역에서 추측하지 않는지)
    for call_name in ("fetch_holdings", "add_lot", "update_holding", "delete_holding"):
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == call_name]
        check(calls and all(c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "client"
                            for c in calls),
              f"`{call_name}(client, …)` — 클라이언트를 명시적으로 넘김",
              f"호출 {len(calls)}건")

    # (c) 저장소 직접 접근 금지 (web/auth.py 를 통해서만)
    # ⚠️ 2026-08-17 — `from nicegui import ui` 고정 문자열 대신 정규식을 씁니다.
    #    `from nicegui import run, ui`(로그인 버튼 로딩 표시 수정, run.io_bound 사용)처럼
    #    같은 줄에서 다른 이름과 같이 임포트해도 이 검사가 오탐(false positive)으로
    #    실패하면 안 됩니다 — 이 검사의 목적은 "app.storage 직접 접근 여부"이지 임포트
    #    문구 형태가 아닙니다.
    check(bool(re.search(r'from nicegui import[^\n]*\bui\b', src)) and "app.storage" not in src,
          "화면 파일은 app.storage 를 직접 만지지 않음 (web/auth.py 경유)")

    # (d) XSS — 사용자/DB 문자열이 HTML 로 나가는 곳은 esc() 통과 (§0-3-9)
    check("esc(" in src, "HTML 출력에 esc() 사용")
    check("stock_name" not in src or "_row_label_html" in src,
          "종목명은 이스케이프하는 전용 함수(_row_label_html)를 거침")

    # (e) 완료기준 ③④⑤ 관련 회귀 방지
    check("@ui.refreshable" in src, "부분 갱신(@ui.refreshable) 사용 — 전체 리렌더 없음 (완료기준 ③)")
    check(src.count("no-wrap") >= 2 and "flex-1 min-w-0" in src and "shrink-0" in src,
          "'종목 관리' 줄이 항상 한 줄 유지되는 flex 패턴 사용 (완료기준 ④, #127~#130)")
    check("ui.plotly(fig).classes('w-full h-80')" in src,
          "원형차트에 높이(h-80)를 명시 — 안 주면 0px 로 그려짐 (완료기준 ⑤)")
    check("px.pie(names=names, values=values, hole=0.35)" in src
          and 'fig.update_traces(textposition="inside", textinfo="percent+label")' in src,
          "원형차트 figure 생성 코드가 Streamlit 원본과 동일(px.pie · hole=0.35 · 같은 traces)")

    # (f) 원/달러 분리 (완료기준 ⑥) — 통화별로 따로 그리는 구조인지
    check('for currency in ("KRW", "USD")' in src,
          "통화별로 블록을 나눠 그림 (원/달러 합산 경로 없음, 완료기준 ⑥)")
    check("NO_FX_CONVERSION_NOTICE" in src, "환율 변환 없음 고지를 화면에 표시")

    # (g) Streamlit 잔재가 섞여 들어오지 않았는지
    check("import streamlit" not in src and "st.session_state" not in src,
          "Streamlit 코드가 섞여 있지 않음")

    # (h) 예외 원문·트레이스백 노출 방지 (§0-3-4)
    check("_fail(" in src and "traceback" not in src,
          "예상 못 한 예외는 화면에 원문을 흘리지 않고 로그로만 보냄 (§0-3-4)")


# =============================================================================
# [4] 렌더 스모크 테스트 — 로그인 후 본문을 **실제로 실행**해봅니다
# =============================================================================
#  위젯은 스텁이라 화면이 그려지진 않지만, f-string 조립·HTML 이스케이프·손익 계산·통화 분리
#  분기는 전부 진짜로 실행됩니다. 오타(NameError)·잘못된 키 접근(KeyError)·이스케이프 누락을
#  배포 전에 잡는 것이 목적입니다.
#  ⚠️ 보유종목은 **합성 데이터**이고 DB 호출은 대체합니다(§0-1 — 실데이터를 지어내지 않고,
#     실제 Supabase 에 접속하지도 않습니다). 시세는 저장소의 실제 스냅샷을 읽기만 합니다.
# =============================================================================
SYNTHETIC_HOLDINGS = [
    {"id": "row-kr-1", "market": "KR", "ticker": "005930", "stock_name": "삼성전자",
     "quantity": 10.0, "avg_purchase_price": 70000.0, "currency": "KRW"},
    # 유니버스 밖 + XSS 시도 문자열이 종목명에 들어간 경우 (§0-3-9 — 그대로 실행되면 안 됨)
    {"id": "row-kr-2", "market": "KR", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3.0,
     "avg_purchase_price": 1000.0, "currency": "KRW"},
    {"id": "row-us-1", "market": "US", "ticker": "NVDA", "stock_name": "NVIDIA Corp",
     "quantity": 2.0, "avg_purchase_price": 100.0, "currency": "USD"},
]


def test_render_smoke():
    print("\n[4] 로그인 후 본문 렌더 스모크 테스트 (합성 보유종목)")
    _install_nicegui_stub()
    import web.pages.scorecard_page as page

    captured_html = []
    import web.components.widgets as widgets
    from nicegui import ui

    original_fetch = page.fetch_holdings
    original_html = ui.html
    page.fetch_holdings = lambda client, user_id: [dict(h) for h in SYNTHETIC_HOLDINGS]

    def _capture_html(content='', *a, **k):
        captured_html.append(str(content))
        return original_html(content, *a, **k)

    ui.html = _capture_html
    widgets.ui.html = _capture_html                # widgets 모듈이 참조하는 것도 같은 스텁
    try:
        page._render_body(object(), "uid-test", "a@example.com")
        check(True, "_render_body() 가 예외 없이 끝까지 실행됨")
    except Exception as exc:                       # noqa: BLE001
        check(False, "_render_body() 가 예외 없이 끝까지 실행됨", f"({type(exc).__name__}: {exc})")
    finally:
        page.fetch_holdings = original_fetch
        ui.html = original_html
        widgets.ui.html = original_html

    blob = "\n".join(captured_html)
    check(bool(blob), "렌더 중 HTML 이 실제로 만들어짐", f"(조각 {len(captured_html)}개)")
    check("<img src=x onerror=" not in blob,
          "🔐 종목명에 심어둔 <img onerror=...> 가 HTML 로 살아나오지 않음 (§0-3-9 XSS)")
    check("&lt;img src=x onerror=alert(1)&gt;" in blob,
          "🔐 그 문자열이 이스케이프되어 '글자 그대로' 출력됨")
    check("현재가 없음" in blob,
          "유니버스 밖 종목(999999)은 값을 지어내지 않고 '현재가 없음' 으로 표시 (§0-1)")


# =============================================================================
# [5] 화면 배선 — web/pages/report_page.py (5단계 · 사장님 보고서)
# =============================================================================
#  '내 성적표'와 **같은 로그인 세션**을 쓰는 두 번째 화면이라, [3] 과 같은 기준을 그대로
#  적용합니다. 로그인이 필요한 화면이 늘어날 때마다 이 검사를 함께 늘립니다(§0-3-8).
# =============================================================================
def test_report_page_wiring():
    print("\n[5] web/pages/report_page.py 배선 (사장님 보고서)")
    path = REPO_ROOT / "web" / "pages" / "report_page.py"
    check(path.exists(), "web/pages/report_page.py 존재")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # ⚠️ "이 낱말이 코드에 없는지"를 볼 때는 **주석·독스트링을 걷어낸** 문자열로 확인합니다.
    #    이 파일은 "Streamlit 의 _consume_pending_ref_date 우회가 왜 필요 없어졌는지"를
    #    주석으로 길게 설명하고 있어서, 원문으로 검사하면 그 설명 자체에 걸려 항상 실패합니다.
    code = python_code_only(src)

    # (a) DB를 만지는 함수는 client·user_id 를 **인자로** 받아야 합니다 (§0-3-8 함수 설계 원칙)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_render_signed_in", "_render_report_body"):
        node = funcs.get(name)
        args = [a.arg for a in node.args.args] if node else []
        check(node is not None and "client" in args and "user_id" in args,
              f"`{name}()` 이 client·user_id 를 인자로 받음", f"실제 인자: {args}")

    # (b) DB 호출에 client 가 첫 인자로 들어가는지 (전역에서 추측하지 않는지)
    for call_name in ("fetch_user_snapshots", "fetch_user_holding_snapshots"):
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == call_name]
        check(calls and all(c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "client"
                            for c in calls),
              f"`{call_name}(client, …)` — 클라이언트를 명시적으로 넘김",
              f"호출 {len(calls)}건")

    # (c) 저장소 직접 접근 금지 (web/auth.py 를 통해서만)
    check(bool(re.search(r'from nicegui import[^\n]*\bui\b', src)) and "app.storage" not in code,
          "화면 파일은 app.storage 를 직접 만지지 않음 (web/auth.py 경유)")

    # (d) 🔑 로그인 공유 — '내 성적표'와 **같은 세션 함수·같은 로그인 폼**을 쓰는지
    check("has_supabase_session" in code and "from web.auth import" in code,
          "로그인 여부를 web/auth.py 의 접속자 저장소로 판단 (scorecard 와 동일 경로 = 세션 공유)")
    check("from web.auth_ui import" in code and "render_auth()" in code,
          "로그인 폼을 web/auth_ui.py 공용 함수로 그림 (화면마다 폼을 복붙하지 않음, §0-3-10)")
    for forbidden in ("sign_in(", "sign_up(", "SESSION_USER_KEY", "set_session("):
        check(forbidden not in code,
              f"자체 로그인 처리(`{forbidden}`)를 따로 만들지 않음 — 인증 경로는 web/auth.py 하나")

    # (e) XSS — 사용자/DB 문자열이 HTML 로 나가는 곳은 esc() 통과 (§0-3-9)
    check("esc(" in src, "HTML 출력에 esc() 사용")
    check("stock_name" not in src or "_holding_label_html" in src,
          "종목명은 이스케이프하는 전용 함수(_holding_label_html)를 거침")

    # (f) 🔴 Streamlit 위젯 키 우회 코드가 통째로 사라졌는지 (계획서 §4-2)
    for leftover in ("_consume_pending_ref_date", "pending_ref_date", "REF_DATE_WIDGET_KEY",
                     "st.session_state", "st.rerun", "import streamlit"):
        check(leftover not in code,
              f"Streamlit 잔재 `{leftover}` 가 없음 (위젯 키 우회는 지역변수+refresh 로 대체)")
    check("@ui.refreshable" in code and ".refresh()" in code,
          "기간 이동/기간 변경이 부분 갱신(@ui.refreshable + .refresh())으로 동작")

    # (g) 계산은 utils/report_db.py 가 하고 화면은 그리기만 하는지 (계층 분리)
    check("from utils.report_db import" in code and "PERIOD_OPTIONS" in code,
          "6기간 목록·계산 함수를 utils/report_db.py 에서 그대로 가져다 씀(문자열 이중 관리 금지)")
    check("resolve_display_date" in code and "period_title" in code,
          "주말·공휴일 대체(#117) 판정을 기존 함수로 하고 두 날짜를 화면에 밝힘")

    # (h) 예외 원문·트레이스백 노출 방지 (§0-3-4)
    check("_fail(" in src and "traceback" not in src,
          "예상 못 한 예외는 화면에 원문을 흘리지 않고 로그로만 보냄 (§0-3-4)")


# =============================================================================
# [6] 사장님 보고서 렌더 스모크 — 표·기간이동을 **실제로 실행**해봅니다
# =============================================================================
#  ⚠️ 스냅샷은 **합성 데이터**이고 DB 호출은 대체합니다(§0-1 — 실 Supabase 에 접속하지 않음).
#     벤치마크만 저장소의 실제 `market_history.csv` 를 읽으므로, 아래 기대값(+5.80%)은
#     그 파일의 실측 코스피 종가(2026-07-31 6595.45 → 2026-08-14 6977.94)에서 나옵니다.
# =============================================================================
SYNTHETIC_SNAPSHOTS = [
    {"snapshot_date": "2026-07-31", "market": "KR", "currency": "KRW",
     "total_value": 700000, "total_cost": 703000, "holdings_count": 2, "priced_count": 2,
     "unpriced_count": 0, "benchmark_symbol": "KOSPI", "benchmark_value": 6595.45,
     "price_as_of_kst": "2026-07-31 16:05"},
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW",
     "total_value": 723300, "total_cost": 703000, "holdings_count": 2, "priced_count": 2,
     "unpriced_count": 0, "benchmark_symbol": "KOSPI", "benchmark_value": 6358.95,
     "price_as_of_kst": "2026-08-03 16:05"},
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW",
     "total_value": 750000, "total_cost": 700000, "holdings_count": 2, "priced_count": 1,
     "unpriced_count": 1, "benchmark_symbol": "KOSPI", "benchmark_value": 6977.94,
     "price_as_of_kst": "2026-08-14 16:05"},
]

SYNTHETIC_HOLDING_SNAPSHOTS = [
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW", "ticker": "005930",
     "stock_name": "삼성전자", "quantity": 10, "avg_purchase_price": 70000, "cost": 700000,
     "current_price": 72000, "market_value": 720000, "priced": True,
     "price_as_of_kst": "2026-08-03 16:05"},
    # 종목명에 XSS 시도 문자열이 들어간 경우 (§0-3-9 — 그대로 실행되면 안 됨)
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3, "avg_purchase_price": 1000,
     "cost": 3000, "current_price": 1100, "market_value": 3300, "priced": True,
     "price_as_of_kst": "2026-08-03 16:05"},
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW", "ticker": "005930",
     "stock_name": "삼성전자", "quantity": 10, "avg_purchase_price": 70000, "cost": 700000,
     "current_price": 75000, "market_value": 750000, "priced": True,
     "price_as_of_kst": "2026-08-14 16:05"},
    # 그날 가격을 몰랐던 종목 — 0 이 아니라 '가격 모름'/'모름' 으로 나와야 합니다(§0-1)
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3, "avg_purchase_price": 1000,
     "cost": 3000, "current_price": None, "market_value": None, "priced": False,
     "price_as_of_kst": "2026-08-14 16:05"},
]


# 🇺🇸 미국 블록 — 벤치마크 두 줄 + **평균 한 줄**(#116)과 한글 종목명(#115) 확인용.
#    날짜는 저장소의 실제 `data/us_index_history.json` 에 들어 있는 거래일을 씁니다
#    (SPY 773.26 → 776.34 = +0.40% / ONEQ 105.184 → 105.32 = +0.13% / 평균 +0.26%).
SYNTHETIC_US_SNAPSHOTS = [
    {"snapshot_date": "2026-08-07", "market": "US", "currency": "USD",
     "total_value": 10000, "total_cost": 9000, "holdings_count": 1, "priced_count": 1,
     "unpriced_count": 0, "benchmark_symbol": "SP500_PROXY_SPY", "benchmark_value": 773.26,
     "price_as_of_kst": "2026-08-08 06:10"},
    {"snapshot_date": "2026-08-14", "market": "US", "currency": "USD",
     "total_value": 10500, "total_cost": 9000, "holdings_count": 1, "priced_count": 1,
     "unpriced_count": 0, "benchmark_symbol": "SP500_PROXY_SPY", "benchmark_value": 776.34,
     "price_as_of_kst": "2026-08-15 06:10"},
]

SYNTHETIC_US_HOLDINGS = [
    # 스냅샷에는 **영문 원문**이 저장돼 있고, 화면은 '내 성적표'와 같은 한글명으로 보여야 합니다(#115).
    {"snapshot_date": "2026-08-07", "market": "US", "currency": "USD", "ticker": "NVDA",
     "stock_name": "NVIDIA Corp", "quantity": 2, "avg_purchase_price": 4500, "cost": 9000,
     "current_price": 5000, "market_value": 10000, "priced": True,
     "price_as_of_kst": "2026-08-08 06:10"},
    {"snapshot_date": "2026-08-14", "market": "US", "currency": "USD", "ticker": "NVDA",
     "stock_name": "NVIDIA Corp", "quantity": 2, "avg_purchase_price": 4500, "cost": 9000,
     "current_price": 5250, "market_value": 10500, "priced": True,
     "price_as_of_kst": "2026-08-15 06:10"},
]


def _capture_report_render(period, ref_date,
                           snapshots=SYNTHETIC_SNAPSHOTS, holdings=SYNTHETIC_HOLDING_SNAPSHOTS):
    """리포트 본문을 스텁 위에서 실제로 그려 보고, 만들어진 HTML 조각을 모아 돌려줍니다."""
    _install_nicegui_stub()
    import web.pages.report_page as page
    import web.components.widgets as widgets
    from nicegui import ui

    captured = []
    original_html = ui.html
    original_snapshots = page.fetch_user_snapshots
    original_holdings = page.fetch_user_holding_snapshots

    def _capture(content='', *a, **k):
        captured.append(str(content))
        return original_html(content, *a, **k)

    # ⚠️ 실제 `fetch_user_*` 는 DB 행을 `sort_snapshots()` / `sort_holding_snapshots()` 로
    #    정규화해서 돌려줍니다(날짜는 date, 숫자는 float). 화면이 그 규약 위에서 돌기 때문에
    #    가짜 조회도 **같은 정규화를 거쳐** 돌려줘야 진짜와 같은 조건이 됩니다.
    from utils.report_db import sort_holding_snapshots, sort_snapshots
    page.fetch_user_snapshots = lambda client, user_id, **kw: sort_snapshots(snapshots)
    page.fetch_user_holding_snapshots = \
        lambda client, user_id, **kw: sort_holding_snapshots(holdings)
    ui.html = _capture
    widgets.ui.html = _capture
    try:
        page._render_report_body(object(), "uid-test", period, ref_date)
        error = None
    except Exception as exc:                       # noqa: BLE001
        error = exc
    finally:
        page.fetch_user_snapshots = original_snapshots
        page.fetch_user_holding_snapshots = original_holdings
        ui.html = original_html
        widgets.ui.html = original_html
    return "\n".join(captured), error


def test_report_render_smoke():
    print("\n[6] 사장님 보고서 렌더 스모크 (합성 스냅샷)")
    import datetime

    # ── 월간 (2026-08-14 기준) ────────────────────────────────────────────
    blob, error = _capture_report_render("MONTHLY", datetime.date(2026, 8, 14))
    check(error is None, "_render_report_body() 가 예외 없이 끝까지 실행됨",
          f"({type(error).__name__}: {error})" if error else "")
    check(bool(blob), "렌더 중 HTML 이 실제로 만들어짐")
    check("<img src=x onerror=" not in blob,
          "🔐 종목명에 심어둔 <img onerror=...> 가 HTML 로 살아나오지 않음 (§0-3-9 XSS)")
    check("&lt;img src=x onerror=alert(1)&gt;" in blob,
          "🔐 그 문자열이 이스케이프되어 '글자 그대로' 출력됨")
    check("750,000원" in blob, "기간 종료 평가금액이 스냅샷 값 그대로 표시됨")
    check("+7.14%" in blob,
          "평가금액 변화율이 계산 함수 결과와 일치 (700,000 → 750,000)")
    check("+5.80%" in blob,
          "벤치마크(코스피 6595.45 → 6977.94) 수익률이 실측 CSV 값으로 계산됨")
    check("가격 모름" in blob and "모름" in blob,
          "그날 가격을 몰랐던 종목을 0 이 아니라 '가격 모름'/'모름' 으로 표시 (§0-1)")
    check("대조 불일치" not in blob,
          "종목별 합계(750,000)와 같은 날 합계 스냅샷이 일치해 경고가 뜨지 않음")
    check("비중 변화" in blob or "%p" in blob, "비중 변화 표가 그려짐(기록이 이틀 이상)")

    # ── 일간 · 주말(기록 없는 날) → 가장 최근 기록일로 대체 (#117) ────────
    blob_sun, error_sun = _capture_report_render("DAILY", datetime.date(2026, 8, 16))
    check(error_sun is None, "일간(주말) 렌더도 예외 없이 실행됨",
          f"({type(error_sun).__name__}: {error_sun})" if error_sun else "")
    check("2026-08-16" in blob_sun and "2026-08-14" in blob_sun,
          "주말 대체 안내가 **고른 날과 실제로 보여주는 날 둘 다** 밝힘 (#117 · §0-1)")
    check("저장된 기록이 없는 날" in blob_sun, "대체 안내 문구가 그대로 이식됨")

    # ── 🇺🇸 미국 주간 — 벤치마크 2종 + 평균 한 줄(#116) + 한글 종목명(#115) ─
    import datetime as _dt
    blob_us, error_us = _capture_report_render(
        "WEEKLY", _dt.date(2026, 8, 14),
        snapshots=SYNTHETIC_US_SNAPSHOTS, holdings=SYNTHETIC_US_HOLDINGS)
    check(error_us is None, "미국 블록도 예외 없이 렌더됨",
          f"({type(error_us).__name__}: {error_us})" if error_us else "")
    check("+0.40%" in blob_us and "+0.13%" in blob_us,
          "벤치마크 두 줄이 실측 ETF 종가(SPY 773.26→776.34 / ONEQ 105.184→105.32)로 계산됨")
    check("+0.26%" in blob_us and "평균" in blob_us,
          "미국 두 벤치마크 **평균 한 줄**(#116)이 두 값의 산술평균으로 나옴")
    check("엔비디아" in blob_us and "NVIDIA Corp" not in blob_us,
          "미국 종목명이 '내 성적표'와 같은 한글 표기로 나옴 (#115 — 저장된 영문 원문 아님)")
    check("$10,500.00" in blob_us,
          "달러 금액이 통화 기호 그대로 표시됨 (환율 변환·원화 합산 없음)")


def test_report_period_navigation():
    """'◀ 이전 / 최신 / 다음 ▶' — Streamlit 의 pending 우회 없이 지역 상태만으로 동작하는가."""
    print("\n[6-b] 기간 이동 버튼 (위젯 키 우회 코드 없이)")
    _install_nicegui_stub()
    import datetime
    import web.pages.report_page as page

    class _FakeInput:
        def __init__(self, value):
            self.value = value

    class _FakeBody:
        def __init__(self):
            self.refreshed = 0

        def refresh(self):
            self.refreshed += 1

    view = {"period": "MONTHLY", "ref_date": datetime.date(2026, 8, 17)}
    date_input, body = _FakeInput("2026-08-17"), _FakeBody()

    page._shift_ref_date(view, -1, date_input, body)
    check(view["ref_date"] == datetime.date(2026, 7, 1) and date_input.value == "2026-07-01",
          "◀ 이전 기간: 기준일과 **달력 칸 값이 함께** 바뀜(= 화면에 즉시 반영)",
          f"실제: {view['ref_date']} / {date_input.value}")
    check(body.refreshed == 1, "본문이 한 번 다시 그려짐")

    page._shift_ref_date(view, 1, date_input, body)
    check(view["ref_date"] == datetime.date(2026, 8, 1) and date_input.value == "2026-08-01",
          "다음 기간 ▶ 로 되돌아옴(기간 시작일 기준 — shift_period 규약 그대로)")

    page._apply_ref_date(view, datetime.date(2026, 8, 1), date_input, body)
    check(body.refreshed == 2, "같은 날짜를 다시 넣으면 다시 그리지 않음(무한 루프 방지)")

    page._on_date_typed(view, "이건날짜가아님", date_input, body)
    check(date_input.value == "2026-08-01" and view["ref_date"] == datetime.date(2026, 8, 1),
          "달력 칸에 이상한 값이 들어오면 날짜를 지어내지 않고 직전 기준일로 되돌림 (§0-1)")

    page._apply_period(view, "DAILY", body)
    check(view["period"] == "DAILY" and body.refreshed == 3, "기간 종류 변경이 본문을 다시 그림")


def test_login_is_shared_between_scorecard_and_report():
    """🔑 '내 성적표'와 '사장님 보고서'가 **같은 로그인 세션**을 쓰는가 (오너 확정 사항).

    Streamlit 에서는 두 화면이 같은 `session_state` 키를 공유해서 맞췄지만, NiceGUI 에서는
    두 화면이 **같은 함수(web/auth.py)** 를 부르기만 하면 저장소가 접속자 단위라 자동으로
    공유됩니다. 그래서 여기서 확인하는 것은 두 가지입니다.
      ① 두 화면이 참조하는 세션 함수·로그인 폼이 **같은 객체**인가 (다른 사본이면 언젠가
         한쪽만 고쳐져 두 화면의 로그인 상태가 어긋납니다)
      ② 한 접속에서 로그인하면 그 접속의 저장소 하나로 **양쪽 게이트가 함께 열리는가**,
         그리고 다른 접속(B)은 그대로 닫혀 있는가 (§0-3-8 — 공유는 같은 사람 안에서만)
    """
    print("\n[7] 🔑 내 성적표 ↔ 사장님 보고서 로그인 공유")
    _install_nicegui_stub()
    import web.auth as auth
    import web.auth_ui as auth_ui
    import web.pages.report_page as report
    import web.pages.scorecard_page as scorecard

    check(report.has_supabase_session is scorecard.has_supabase_session is auth.has_supabase_session,
          "두 화면이 **같은** has_supabase_session() 을 봄 (로그인 판정 단일 출처)")
    check(report.get_client is scorecard.get_client is auth.get_client,
          "두 화면이 **같은** get_client() 를 씀 (접속 전용 Supabase 클라이언트 1개)")
    check(report.render_auth is scorecard.render_auth is auth_ui.render_auth,
          "두 화면이 **같은** 로그인 폼을 그림 (web/auth_ui.py 하나 — §0-3-10)")

    conn_a, conn_b = FakeConnection("A"), FakeConnection("B")
    active = {"conn": conn_a}
    original = (auth.user_storage, auth.client_storage)
    auth.user_storage = lambda: active["conn"].user
    auth.client_storage = lambda: active["conn"].client
    try:
        # '내 성적표'에서 로그인한 상태를 흉내 냅니다(토큰이 접속자 저장소에 들어간 상태).
        conn_a.user[auth.SB_TOKENS_KEY] = {"access_token": "A", "refresh_token": "A-r"}
        check(report.has_supabase_session() is True,
              "🔑 /scorecard 에서 로그인해 두면 /report 도 로그인 상태 (폼 없이 본문)")
        active["conn"] = conn_b
        check(report.has_supabase_session() is False and scorecard.has_supabase_session() is False,
              "🔴 다른 접속(B)에는 그 로그인이 전혀 보이지 않음 (§0-3-8)")
    finally:
        (auth.user_storage, auth.client_storage) = original


def test_pages_import_cleanly():
    print("\n[3-b] 모듈 import 검증 (문법·배선 오류 조기 발견)")
    _install_nicegui_stub()
    for module_name in ("web.auth", "web.auth_ui", "web.layout",
                        "web.pages.scorecard_page", "web.pages.report_page"):
        try:
            __import__(module_name)
        except Exception as exc:                   # noqa: BLE001
            check(False, f"{module_name} import", f"({type(exc).__name__}: {exc})")
        else:
            check(True, f"{module_name} import")


# =============================================================================
def main():
    print("=" * 74)
    print("🔴 동시 접속 세션 격리 검증 (ENGINEERING_SPEC.md §0-3-8 / 계획서 §9 완료기준 ⑦)")
    print("=" * 74)

    test_no_mutable_globals()
    test_user_named_globals_are_constants()
    test_no_global_rebinding()
    test_storage_access_is_centralised()
    test_two_sessions_do_not_mix()
    test_scorecard_page_wiring()
    test_render_smoke()
    test_report_page_wiring()
    test_report_render_smoke()
    test_report_period_navigation()
    test_login_is_shared_between_scorecard_and_report()
    test_pages_import_cleanly()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        print("   ⚠️ 이 테스트가 실패하는 동안 '내 성적표' 화면을 공개하면 안 됩니다 (§0-3-8).")
        sys.exit(1)
    print("✅ 전체 통과 — 두 접속의 저장소가 물리적으로 분리되어 있고, 서로를 읽지도 쓰지도 않습니다.")
    print("=" * 74)


if __name__ == "__main__":
    main()
