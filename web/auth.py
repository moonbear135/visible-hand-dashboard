"""
인증/세션 (NiceGUI 이전, 1단계 — 관리자 로그인).

⚠️ ENGINEERING_SPEC.md §0-3-8 (개인정보·자산 데이터 절대 격리) 필독:
   - `app.storage.user` 는 서버에 저장되고 **쿠키로 접속자별 식별**됩니다 (접속자마다 별도).
   - 모듈 전역 변수에는 절대 사용자별 상태(로그인 여부, 토큰, 클라이언트 객체)를 두지 않습니다.
     NiceGUI는 한 프로세스가 모든 접속자를 처리하므로, 전역에 두면 한 사람의 로그인이
     전원에게 공유되는 사고로 이어집니다.
   - 이 파일의 관리자 인증은 `app.storage.user['admin']` (접속자별)만 씁니다 — 안전합니다.

4단계(scorecard, Supabase 로그인)에서 이 파일에 `get_client()`/`login()`/`logout()`이
추가됩니다. 그때도 위 원칙(§0-3-8)을 다시 확인하고 진행합니다 — 계획서
NICEGUI_MIGRATION_PLAN.md §6-2 설계 스케치 참고.
"""

import hashlib
import hmac
import os

from nicegui import app

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False


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
        app.storage.user['admin'] = True
    return ok


def admin_logout() -> None:
    app.storage.user['admin'] = False


def is_admin() -> bool:
    return bool(app.storage.user.get('admin', False))


# ── 0단계 데모 카운터 (임시) ─────────────────────────────────────────────
# demo_page.py 의 저장소-지속성 검증용. 실제 화면(admin_page 등) 이전이 끝나면
# demo_page.py 와 함께 지워도 됩니다.

def get_demo_counter() -> int:
    return app.storage.user.get('demo_count', 0)


def bump_demo_counter() -> int:
    value = get_demo_counter() + 1
    app.storage.user['demo_count'] = value
    return value
