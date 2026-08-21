"""
인증/세션 (NiceGUI 이전 — 1단계 관리자 로그인 + 4단계 Supabase 로그인).

⚠️ ENGINEERING_SPEC.md §0-3-8 (개인정보·자산 데이터 절대 격리) 필독:
   - `app.storage.user` 는 서버에 저장되고 **쿠키로 접속자별 식별**됩니다 (접속자마다 별도).
   - `app.storage.client` 는 **그 접속(브라우저 탭 하나)** 의 서버 메모리이고,
     새로고침/재접속하면 폐기됩니다 (접속마다 완전히 별개의 dict).
   - 모듈 전역 변수에는 절대 사용자별 상태(로그인 여부, 토큰, 클라이언트 객체)를 두지 않습니다.
     NiceGUI는 한 프로세스가 모든 접속자를 처리하므로, 전역에 두면 한 사람의 로그인이
     전원에게 공유되는 사고로 이어집니다.
   - 이 파일의 관리자 인증은 `app.storage.user['admin']` (접속자별)만 씁니다 — 안전합니다.

🔴 **이 파일을 고치는 사람에게 (오너 포함) — 절대 하지 말 것**
   `_client = None` / `_CLIENTS = {}` / `_current_user = ...` 같은 **모듈 전역 변수에
   사용자 객체·토큰·보유종목을 담지 마세요.** "어차피 한 명만 쓰니까", "캐시하면 빠르니까"
   라는 이유로 전역에 담는 순간, 나중에 접속한 다른 사람이 **먼저 로그인한 사람의 자산
   정보를 그대로 보게 됩니다.** 이건 성능 문제가 아니라 이 프로젝트에서 가장 심각한 사고
   등급(§0-3-8 최상위 금지사항)입니다. 아래 두 접근자(`user_storage()` /
   `client_storage()`)를 거치지 않는 저장 경로를 새로 만들지 마세요 —
   `tests/test_web_session_isolation.py` 가 이 파일을 AST로 훑어 자동으로 잡습니다.
"""

import hashlib
import hmac
import os

from nicegui import app, run

from utils.scorecard_db import (
    ScorecardError,
    create_supabase_client,
    current_user,
    sign_in,
    sign_out,
    supabase_status,
)

from web.blocking import run_blocking

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False


# ── 저장소 접근 지점 (이 두 함수 밖에서 app.storage 를 직접 만지지 않습니다) ──────
#
# 왜 함수로 한 겹 감싸는가 (두 가지 이유, 둘 다 §0-3-8 을 위한 것):
#  1. **감사(audit) 지점이 한 곳**이 됩니다. "사용자 데이터가 어디에 저장되는가"를 확인하려면
#     이 파일의 이 두 함수만 보면 됩니다. 전역 dict 가 몰래 끼어들 자리가 구조적으로 없습니다.
#  2. **자동화 테스트가 가짜 접속 두 개를 만들 수 있습니다.** 실제 NiceGUI 서버를 띄우지 않고도
#     `tests/test_web_session_isolation.py` 가 이 두 함수만 바꿔치기해서 "접속 A"와 "접속 B"를
#     동시에 만들고, 서로의 토큰이 절대 섞이지 않는지 검증합니다(§0-3-8 "자동 회귀 테스트 필수").
# ⚠️ 이 두 함수는 **호출될 때마다** app.storage 를 다시 읽습니다. 반환값을 모듈 전역이나
#    기본 인자에 캐시하면(예: `def f(store=user_storage())`) 그 순간 첫 접속자의 저장소가
#    모두에게 공유됩니다 — 절대 금지.

def user_storage():
    """이 **접속자**(브라우저, 서명된 쿠키로 식별)의 저장소. 새로고침해도 유지됩니다.

    직렬화 가능한 값만 넣습니다 — 로그인 토큰 2개와 관리자 플래그가 전부입니다.
    """
    return app.storage.user


def client_storage():
    """이 **접속**(탭 하나, WebSocket 연결 하나)의 서버 메모리. 새로고침하면 폐기됩니다.

    Supabase 클라이언트처럼 **직렬화할 수 없는 객체**를 담는 유일한 자리입니다.
    (쿠키/파일에 저장되지 않으므로 토큰이 디스크에 남지 않는 이점도 있습니다.)
    """
    return app.storage.client


# ── 관리자 비밀번호 검증 ──────────────────────────────────────────────────
# views/admin_view.py 의 _get_admin_password_hash() / _verify_admin_password() 를
# **로직 그대로** 옮겼습니다(계획서 §4-2 "bcrypt 검증 로직은 그대로 복사"). 바뀐 건
# 비밀번호 저장소를 `st.secrets` 대신 환경변수 하나만 보는 것뿐입니다 — Render는
# Streamlit Cloud secrets 같은 게 없고 전부 Environment 탭(환경변수)으로 통일되기 때문입니다.

def get_admin_password_hash() -> str:
    """환경변수 ADMIN_PASSWORD_HASH 에서 저장된 해시를 읽어옵니다. 없으면 빈 문자열."""
    return (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip()


def verify_admin_password(input_password: str, stored_hash: str) -> bool:
    """
    저장된 해시 형식을 자동 판별해 검증합니다 (기존 admin_view.py와 동일한 하위호환 규칙).
    - bcrypt 해시: "$2a$"/"$2b$"/"$2y$" 로 시작 (솔트 포함, 권장).
    - 그 외(64자리 hex): 예전 SHA-256 방식으로 간주.
    """
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        if not BCRYPT_AVAILABLE:
            return False
        try:
            return bcrypt.checkpw(input_password.encode(), stored_hash.encode())
        except ValueError:
            return False
    input_hash = hashlib.sha256(input_password.encode()).hexdigest()
    return hmac.compare_digest(input_hash, stored_hash)


def try_admin_login(password: str) -> bool:
    """
    성공 시 app.storage.user['admin'] = True 로 저장합니다(접속자별, 새로고침해도 유지).
    ADMIN_PASSWORD_HASH 가 서버에 설정되어 있지 않으면 어떤 비밀번호로도 절대 열리지
    않습니다(기본 해시 하드코딩 금지 — 기존 admin_view.py와 동일 정책, §0-1).
    """
    stored_hash = get_admin_password_hash()
    if not stored_hash:
        return False
    ok = bool(password) and verify_admin_password(password, stored_hash)
    if ok:
        user_storage()['admin'] = True
    return ok


def admin_logout() -> None:
    user_storage()['admin'] = False


def is_admin() -> bool:
    return bool(user_storage().get('admin', False))


# (2026-08-17 삭제) 0단계 데모 카운터 `get_demo_counter`/`bump_demo_counter` 는
#  `web/pages/demo_page.py` 와 함께 지웠습니다. 그 페이지는 "새로고침해도 app.storage.user
#  값이 유지되는가"를 실기기로 확인하기 위한 0단계 검증용이었고, 8단계와 컷오버까지 전부
#  끝나 역할이 사라졌습니다 (ENGINEERING_SPEC.md §0-3-10 — 안 쓰는 코드를 남기지 않습니다).
#  저장소 지속성은 이제 실제 로그인 세션(아래 `SB_TOKENS_KEY`)이 매일 증명하고 있습니다.


# =============================================================================
# Supabase 로그인 세션 (4단계 — "내 성적표" /scorecard)
#
# 계획서 NICEGUI_MIGRATION_PLAN.md §6-2 설계 그대로입니다. 인증 자체(비밀번호 검증·토큰
# 발급)는 전부 Supabase Auth 가 하고, 이 파일은 **"그 토큰을 어느 접속의 서랍에 넣느냐"**
# 만 담당합니다. 그 서랍 선택이 곧 §0-3-8(자산 정보 격리)의 전부입니다.
#
#  ┌ 무엇을 어디에 두는가 ──────────────────────────────────────────────────┐
#  │ 토큰 2개(access/refresh)  → app.storage.user   (= user_storage())      │
#  │   · 왜: 새로고침해도 로그인이 풀리면 안 되므로 접속(탭)이 아니라        │
#  │     접속자(쿠키)에 묶여야 합니다. 문자열이라 직렬화도 됩니다.          │
#  │ Supabase 클라이언트 객체  → app.storage.client (= client_storage())    │
#  │   · 왜: 직렬화가 안 되고(내부에 소켓·세션 상태를 들고 있음), 무엇보다  │
#  │     **로그인 세션(JWT)을 객체 안에 품고 있어서** 누군가와 공유되는 순간 │
#  │     그 사람의 RLS 권한으로 DB를 읽게 됩니다. 그래서 프로세스 전역도,    │
#  │     접속자 단위도 아닌 **접속 하나**에만 묶습니다(가장 좁은 범위).      │
#  │ 사용자 id / 이메일 / 보유종목 → **아무 데도 저장하지 않습니다**         │
#  │   · 왜: 화면을 그릴 때마다 그 접속 전용 클라이언트에게 직접 물어보면    │
#  │     되고(current_user), 저장해두면 "누구 것인지 헷갈릴 여지"가 생깁니다.│
#  └────────────────────────────────────────────────────────────────────────┘
#
# ⚠️ `utils/scorecard_db.create_supabase_client()` 의 경고 주석("@st.cache_resource 로
#    캐시하면 로그인 세션이 모든 방문자에게 공유된다")이 NiceGUI 에서 그대로, 오히려 더
#    쉽게 재현됩니다. 이 파일에서 클라이언트를 만드는 곳은 `get_client()` 한 군데뿐이고,
#    그 결과는 항상 `client_storage()` 에만 들어갑니다.
# =============================================================================

# app.storage.user 안의 키 이름. **값이 아니라 이름(문자열 상수)** 이라 전역이어도 안전합니다.
SB_TOKENS_KEY = 'sb_tokens'
# app.storage.client 안의 키 이름.
SB_CLIENT_KEY = 'sb_client'


def has_supabase_session() -> bool:
    """이 접속자가 로그인 상태인지 (토큰 보유 여부). 화면이 로그인 폼을 그릴지 판단합니다."""
    return bool(user_storage().get(SB_TOKENS_KEY))


def _restore_session(client, access_token, refresh_token):
    """저장해 둔 토큰 2개를 클라이언트에 이어붙입니다 — **네트워크가 일어날 수 있는 한 줄**.

    ⚠️ 인자가 `client` + 문자열 2개뿐인 것이 **의도된 설계**입니다. 이 함수는
       `get_client_async()` 가 `run_blocking()` 으로 **별도 스레드**에서 실행하는데,
       그 스레드에는 접속 컨텍스트가 없어 `user_storage()` 를 부를 수 없기 때문입니다
       (아래 `get_client_async()` 독스트링 참고). 토큰은 **부르는 쪽이 이벤트 루프에서
       미리 꺼내** 평범한 문자열로 넘깁니다.

    ⚠️ `set_session()` 은 이름만 보면 로컬 대입 같지만, gotrue 는 access token 이 이미
       만료돼 있으면 **그 자리에서 refresh 왕복(HTTP)** 을 합니다. 즉 몇 초가 걸릴 수
       있는 진짜 네트워크 호출입니다 — 이번 수정이 이 함수를 따로 떼어낸 이유입니다.
    """
    return client.auth.set_session(access_token, refresh_token)


def _forget_broken_session(exc) -> None:
    """세션 복원 실패 처리 — 조용히 넘기지 않고 죽은 토큰을 버립니다 (§0-1).

    그래야 화면이 "로그인 안 된 상태"로 정직하게 되돌아갑니다.
    ⚠️ 저장소를 만지므로 **반드시 이벤트 루프(호출 스레드)에서만** 부릅니다.
    """
    print(f'⚠️ 저장된 Supabase 세션 복원 실패 (재로그인이 필요합니다): {type(exc).__name__}')
    user_storage().pop(SB_TOKENS_KEY, None)


def get_client():
    """**이 접속 전용** Supabase 클라이언트를 돌려줍니다 (없으면 만들어서 보관).

    Supabase 미설정/미설치면 `None` (에러가 아니라 "준비중" — create_supabase_client 정책).

    ⚠️ 반환값을 페이지 함수의 지역 변수로만 들고 쓰세요. 모듈 전역·기본 인자·클래스 속성에
       담는 순간 다른 접속자와 공유됩니다(§0-3-8).

    🔴 2026-08-21 — **화면(@ui.page)·이벤트 처리기는 아래 `get_client_async()` 를 쓰세요.**
       이 동기판은 세션 복원(`_restore_session`)이 네트워크 왕복을 할 수 있어 이벤트 루프를
       붙잡습니다. 남겨 두는 이유는 `tests/test_web_session_isolation.py` 처럼 이벤트 루프
       밖에서 저장소 격리를 검증하는 호출자가 있고, 비동기판도 결국 이 함수와 **똑같은
       규칙**(같은 헬퍼 2개)을 쓰기 때문입니다 (§0-3-10 — 규칙은 한 곳에만).
    """
    store = client_storage()
    client = store.get(SB_CLIENT_KEY)
    if client is not None:
        return client

    client = create_supabase_client()          # 실패 시 ScorecardError 를 그대로 올립니다(§0-1)
    if client is None:
        return None

    tokens = user_storage().get(SB_TOKENS_KEY)
    if tokens:
        # 새로고침·서버 재시작 뒤에도 RLS 가 걸린 "본인" 상태로 이어붙입니다.
        try:
            _restore_session(client, tokens.get('access_token'), tokens.get('refresh_token'))
        except Exception as exc:               # noqa: BLE001 — 상세는 서버 로그로만 (§0-3-4)
            _forget_broken_session(exc)

    store[SB_CLIENT_KEY] = client
    return client


async def get_client_async():
    """`get_client()` 의 비동기 판 — **반환값·예외는 동기판과 완전히 같습니다**.

    화면 코드는 `client = get_client()` 를 `client = await get_client_async()` 로
    바꾸기만 하면 됩니다.

    🔴 왜 "함수 전체를 `run_blocking` 으로 감싸기"가 **틀린 답인가** (2026-08-17 사고 재연 금지)
    ─────────────────────────────────────────────────────────────────────────────
    `web/state.load_json_file_async()` 는 함수 **전체**를 스레드에 넘겨도 안전했습니다.
    그 경로가 만지는 것은 모든 접속자에게 동일한 읽기 전용 캐시뿐이기 때문입니다.
    **여기는 정반대입니다.** 이 함수는 `client_storage()`(이 접속의 서랍)와
    `user_storage()`(이 접속자의 서랍)를 읽고 씁니다. 둘 다 `app.storage.*` 이고,
    `app.storage.*` 는 "지금 어느 접속인지"를 담은 컨텍스트가 있어야 동작합니다.
    별도 스레드에는 그 컨텍스트가 **없습니다**(NiceGUI GitHub Discussion #2228/#2801).
    2026-08-17 에 `login()` 을 통째로 감쌌다가 "로그인이 안 된다" 신고를 받은 게 정확히
    이 실수였습니다 — `web/auth.py::login()` 독스트링에 그 전말이 적혀 있습니다.

    그래서 이 함수는 `login()` 과 **같은 방식으로 쪼갭니다**:
      ① 저장소 읽기(클라이언트 캐시 조회, 토큰 꺼내기)      → 이벤트 루프에서 **동기로**
      ② 실제로 몇 초 걸릴 수 있는 네트워크(`_restore_session`) → `run_blocking` 으로 스레드에
      ③ 저장소 쓰기(클라이언트 보관, 죽은 토큰 폐기)        → 다시 이벤트 루프에서 **동기로**
    스레드로 넘어가는 것은 `client` 객체와 문자열 토큰 2개뿐이고, 스레드 안의 코드는
    `app.storage` 를 **한 번도** 건드리지 않습니다.

    ⚠️ ②와 ③ 사이에는 `await` 이 있으므로 그 동안 같은 접속의 다른 처리가 끼어들 수
       있습니다. 그래도 안전한 이유: ③이 쓰는 값은 전부 **이 접속 자신의 것**이고
       (`store` 는 ①에서 이 접속의 서랍으로 확정됐습니다), 같은 접속에서 두 번 들어와
       각자 클라이언트를 만들면 나중 것이 덮어쓸 뿐 **남의 서랍은 절대 건드리지
       않습니다**. 동기판도 같은 성질입니다.
    """
    store = client_storage()                   # ① 여기부터 ↓ 전부 이벤트 루프(이 접속 컨텍스트)
    client = store.get(SB_CLIENT_KEY)
    if client is not None:
        return client

    client = create_supabase_client()
    if client is None:
        return None

    tokens = user_storage().get(SB_TOKENS_KEY)
    access_token = tokens.get('access_token') if tokens else None
    refresh_token = tokens.get('refresh_token') if tokens else None

    if tokens:
        try:
            # ② 스레드로 넘기는 것은 client 객체와 문자열 2개뿐입니다 (저장소 접근 없음).
            await run_blocking(_restore_session, client, access_token, refresh_token)
        except Exception as exc:               # noqa: BLE001 — 상세는 서버 로그로만 (§0-3-4)
            _forget_broken_session(exc)        # ③ 저장소 쓰기 — 다시 이벤트 루프에서

    store[SB_CLIENT_KEY] = client              # ③ 저장소 쓰기 — 다시 이벤트 루프에서
    return client


async def current_user_async(client):
    """"지금 이 접속에 로그인해 있는 사람"을 **그 접속 전용 클라이언트에게 직접** 물어봅니다.

    `utils/scorecard_db.current_user()` 의 비동기 판입니다. 미로그인이면 `None` —
    반환값 규약은 동기판과 같습니다.

    🔴 이 한 줄이 왜 블로킹인가: `client.auth.get_user()` 는 Supabase 에 **HTTP 왕복**을
       합니다(토큰이 유효한지 서버에 물어보는 것이라 로컬 판단이 불가능합니다). 로그인이
       필요한 화면 4개(/scorecard · /report · /duel · /duel/leaderboard · /duel/consent)가
       **본문을 그리기 전에 반드시** 이 호출을 하므로, 여기가 막히면 그 사람이 화면을 여는
       내내 접속자 전원이 멈춥니다.

    ⚠️ `client` 를 **인자로** 받는 것이 핵심입니다 — 스레드 안에서 `get_client()` 를 다시
       부르면 `app.storage` 에 접근하게 되어 2026-08-17 사고가 재현됩니다
       (`get_client_async()` 독스트링 참고). 이 함수는 저장소를 한 번도 만지지 않습니다.
    """
    if client is None:
        return None
    return await run_blocking(current_user, client)


async def login(email: str, password: str):
    """이메일+비밀번호 로그인. 성공하면 **이 접속자의** 저장소에만 토큰을 넣습니다.

    실패는 `ScorecardError` 로 올라갑니다(호출한 화면이 사람이 읽는 문구로 보여줍니다).
    화면 이동(`ui.navigate`)은 일부러 여기서 하지 않습니다 — 인증 로직과 화면 전환을 섞으면
    테스트에서 이 함수를 직접 호출할 수 없게 되고(§0-3-8 자동 검증 필수), 나중에 다른
    화면이 이 함수를 재사용할 때도 걸림돌이 됩니다.

    🔴 2026-08-17 (배포 직후 "로그인이 안 된다" 신고 — 근본 원인과 수정) — 이 함수를
    통째로 `run.io_bound(login, ...)` 로 감쌌던 게 원인이었습니다. `run.io_bound` 는
    별도 스레드에서 실행되는데, 그 스레드에는 **"지금 어느 접속인지" 를 담은 컨텍스트가
    없어서** `get_client()`/`user_storage()` 가 접근하는 `app.storage.*` 가 그 안에서는
    작동하지 않습니다(NiceGUI 공식 안내: storage는 io_bound 스레드 안에서 접근하기 전에
    미리 동기적으로 읽어둬야 함 — GitHub Discussion #2228/#2801).
    그래서 이 함수 자체는 (`get_client()`·저장소 쓰기 포함) **원래 이벤트 루프에서** 그대로
    실행하고, 실제로 몇 초씩 걸리는 네트워크 호출(`sign_in`) **한 줄만** `run.io_bound` 로
    감쌉니다. 로딩 스피너가 보이는 데도(§ui.button.props('loading') 반영) 필요한 "제어권을
    한 번 넘겨준다"는 효과는 이 한 줄의 `await` 만으로 충분합니다.

    🔴 2026-08-21 — `get_client()` 도 `await get_client_async()` 로 바꿨습니다. 그 안의
       세션 복원(`set_session`)이 만료된 토큰을 만나면 refresh 왕복을 하는데, 그것도
       똑같이 이벤트 루프를 붙잡던 자리였기 때문입니다. **저장소 접근은 여전히 전부
       이벤트 루프에서** 일어납니다(위 사고 원인 그대로) — 자세한 근거는
       `get_client_async()` 독스트링에 적어 뒀습니다.
    """
    client = await get_client_async()
    if client is None:
        raise ScorecardError(
            'Supabase 연결이 준비되지 않아 로그인할 수 없습니다. ' + (supabase_status().reason or '')
        )
    response = await run.io_bound(sign_in, client, (email or '').strip(), password)

    session = getattr(response, 'session', None)
    access_token = getattr(session, 'access_token', None)
    refresh_token = getattr(session, 'refresh_token', None)
    if not access_token or not refresh_token:
        # 토큰 없이 "로그인된 척" 하지 않습니다 (§0-1).
        raise ScorecardError('로그인 응답에 세션 정보가 없습니다. 잠시 후 다시 시도해 주세요.')

    # ⚠️ 대입 대상은 반드시 `user_storage()` — 지금 이 요청을 보낸 접속자의 저장소입니다.
    #    (전역 dict 에 `[email]` 을 키로 넣는 식의 "사용자별 캐시"도 금지입니다. 서버 메모리에
    #     남의 토큰이 함께 존재하는 구조 자체를 만들지 않습니다.)
    user_storage()[SB_TOKENS_KEY] = {
        'access_token': access_token,
        'refresh_token': refresh_token,
    }
    return getattr(response, 'user', None)


def logout() -> None:
    """로그아웃. 이 접속의 클라이언트와 이 접속자의 토큰을 **둘 다** 버립니다.

    ⚠️ `user_storage().clear()` 를 쓰지 않는 이유: 같은 저장소에 관리자 플래그 등 다른
       접속자 상태가 함께 들어있고, 그것까지 지우면 "성적표에서 로그아웃했더니 관리자
       세션도 풀렸다"는 별개의 사고가 됩니다. 지워야 할 것(자산 데이터에 접근하는 열쇠)만
       정확히 지웁니다.
    """
    client = client_storage().pop(SB_CLIENT_KEY, None)
    if client is not None:
        try:
            sign_out(client)
        except ScorecardError as exc:          # 서버 호출이 실패해도 로컬 토큰은 반드시 지웁니다
            print(f'⚠️ Supabase 로그아웃 요청 실패(로컬 세션은 그대로 폐기합니다): {exc}')
    user_storage().pop(SB_TOKENS_KEY, None)


async def logout_async() -> None:
    """`logout()` 의 비동기 판 — 화면·버튼 처리기는 **이쪽**을 쓰세요.

    `sign_out()` 도 Supabase 로 HTTP 왕복을 하는 동기 호출이라, 로그아웃 버튼 하나가
    접속자 전원의 이벤트 루프를 붙잡고 있었습니다(2026-08-21 2차 수정 — `web/blocking.py`
    모듈 독스트링 참고).

    🔴 동기판과 **의도적으로 한 가지 다른 점**: 서랍 두 개(이 접속의 클라이언트 / 이 접속자의
       토큰)를 **네트워크 호출보다 먼저** 비웁니다.
         · 왜: `await` 이 들어가면 서버 왕복이 끝날 때까지 몇 초가 흐르는데, 그 사이에
           같은 사람이 다른 탭을 새로고침하면 **아직 남아 있는 토큰으로 다시 로그인된
           화면**이 그려질 수 있습니다. "로그아웃을 눌렀는데 옆 탭은 로그인 상태"는
           자산 화면에서 절대 만들면 안 되는 상태입니다(§0-3-8).
         · 순서를 바꿔도 동기판의 약속("서버 호출이 실패해도 로컬 세션은 반드시 폐기")은
           그대로이고, 오히려 더 강해집니다.
       저장소 접근 두 줄은 모두 `await` **앞**이라 이벤트 루프에서 실행됩니다 —
       스레드로 넘어가는 것은 `client` 객체 하나뿐입니다(`get_client_async()` 와 같은 규칙).

    ⚠️ 동기판 `logout()` 은 그대로 남겨 둡니다 — `tests/test_web_session_isolation.py` 가
       이벤트 루프 없이 접속 격리를 검증할 때 씁니다.
    """
    client = client_storage().pop(SB_CLIENT_KEY, None)
    user_storage().pop(SB_TOKENS_KEY, None)
    if client is None:
        return
    try:
        await run_blocking(sign_out, client)
    except ScorecardError as exc:              # 서버 호출이 실패해도 로컬 세션은 이미 폐기됐습니다
        print(f'⚠️ Supabase 로그아웃 요청 실패(로컬 세션은 그대로 폐기합니다): {exc}')
    except Exception as exc:                   # noqa: BLE001 — 취소(BlockingCallAborted) 포함
        print(f'⚠️ Supabase 로그아웃 요청 중단(로컬 세션은 그대로 폐기합니다): {type(exc).__name__}')


def new_auth_client():
    """비밀번호 재설정 2단계 전용 **1회용** 클라이언트 (저장소 어디에도 넣지 않습니다).

    `views/scorecard_view.py::_new_auth_client()` 의 이식본이며 이유도 동일합니다 —
    `verify_otp()` 가 성공하면 그 클라이언트에 **재설정 대상 계정의 로그인 세션이 붙습니다.**
    이 접속의 공용 클라이언트에 그 일이 벌어지면, 지금 로그인해 있던 사람의 세션이 조용히
    다른 계정으로 바뀌어 **남의 보유종목이 보이는** 사고가 됩니다(§0-3-8). 그래서 새로 만들어
    쓰고 그대로 버립니다(`reset_password_with_code()` 가 끝나면서 로그아웃시킵니다).
    """
    client = create_supabase_client()
    if client is None:
        raise ScorecardError(
            'Supabase 연결이 준비되지 않아 비밀번호를 재설정할 수 없습니다. '
            + (supabase_status().reason or '')
        )
    return client
