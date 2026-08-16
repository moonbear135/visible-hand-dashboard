"""
세션/인증 (NiceGUI 이전 0단계 — 골격만).

⚠️ 지금은 진짜 로그인 기능이 없습니다. 이 파일이 완성되는 시점:
  - 1단계(admin): `views/admin_view.py`의 bcrypt 관리자 비밀번호 검증 로직을 그대로 옮겨
    `app.storage.user`에 저장하도록 완성합니다.
  - 4단계(scorecard): `utils/scorecard_db.py`의 Supabase 로그인(sign_in/sign_out)을 연결합니다.
    이때 §0-3-8(개인정보 격리 — 이 프로젝트 최상위 금지사항)을 반드시 다시 확인합니다:
    Supabase 클라이언트·로그인 토큰 등 "사용자별" 객체는 모듈 전역에 절대 두지 않고
    app.storage.client(접속별)에만 둡니다. 시크릿창 동시 로그인 자동화 테스트가
    scorecard 공개의 필수 통과 조건입니다(ENGINEERING_SPEC.md §0-3-8).

0단계에서 이 파일이 하는 일은 딱 하나 — `app.storage.user`가 새로고침·재접속 후에도
실제로 값을 유지하는지 증명하는 것뿐입니다(데모 페이지에서 사용).
"""

from nicegui import app


def is_admin() -> bool:
    """1단계에서 실제 bcrypt 검증으로 채워질 자리. 지금은 항상 False."""
    return bool(app.storage.user.get('admin'))


def get_demo_counter() -> int:
    """0단계 검증 전용 — app.storage.user 가 새로고침 후에도 유지되는지 보여주는 카운터."""
    return int(app.storage.user.get('demo_count', 0))


def bump_demo_counter() -> int:
    new_value = get_demo_counter() + 1
    app.storage.user['demo_count'] = new_value
    return new_value
