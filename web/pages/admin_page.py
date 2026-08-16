"""
관리자 콘솔 (NiceGUI 이전, 1단계).

views/admin_view.py 대체. 이번 단계에서는 **로그인 게이트**만 옮깁니다.
"수동 데이터 입력" 폼(render_admin_console)은 macro_view.py 전용 기능이라
6단계(macro 이전)에서 이 화면에 이어붙입니다(NICEGUI_MIGRATION_PLAN.md §4-1).

완료 기준(계획서 §9 "1. admin"):
  ① 잘못된 비밀번호로 진입 불가
  ② 맞는 비밀번호로 진입 후 새로고침해도 관리자 상태 유지
  ③ ADMIN_PASSWORD_HASH 미설정 시 어떤 비밀번호로도 안 열림
  ④ bcrypt·구 SHA-256 해시 둘 다 동작
"""

import os

from nicegui import ui

from utils.db import HISTORY_FILE
from web.auth import admin_logout, get_admin_password_hash, is_admin, try_admin_login
from web.layout import layout


@ui.page('/admin')
def admin_page() -> None:
    with layout('⚙️ 관리자 콘솔'):
        if not is_admin():
            render_admin_login()
            return
        _render_console()


def render_admin_login() -> None:
    """관리자 비밀번호 게이트 (관리자 전용 화면들이 **같은 함수 하나**를 씁니다).

    2026-08-17(6단계) — `/admin/macro`(매크로 방공망)도 같은 게이트를 써야 해서
    `_render_login` 에서 공개 이름으로 바꿨습니다. 게이트 로직을 화면마다 복붙하면
    한쪽만 고쳐지는 사고가 납니다 (ENGINEERING_SPEC.md §0-3-10).
    """
    ui.markdown('일반 방문자에게 노출되지 않는 디버그용 화면입니다. 관리자 비밀번호를 입력하세요.')

    if not get_admin_password_hash():
        ui.label('🚫 관리자 비밀번호가 서버에 설정되어 있지 않습니다.').classes('text-red-600')
        ui.markdown(
            '`ADMIN_PASSWORD_HASH` 환경변수를 Render 대시보드(Environment 탭)에 먼저 등록해 주세요.'
        ).classes('vh-muted')
        return

    error_label = ui.label('').classes('text-red-600')

    def _submit() -> None:
        if try_admin_login(password_input.value or ''):
            ui.navigate.reload()
        else:
            error_label.text = '🚫 비밀번호가 올바르지 않습니다.'
            password_input.value = ''

    password_input = ui.input('🔑 관리자 비밀번호', password=True, password_toggle_button=True) \
        .classes('w-full max-w-sm') \
        .on('keydown.enter', _submit)
    ui.button('로그인', on_click=_submit)


def _render_console() -> None:
    ui.label('🔓 관리자 권한 인증 성공').classes('text-green-700 font-bold')

    def _logout() -> None:
        admin_logout()
        ui.navigate.reload()

    ui.button('로그아웃', on_click=_logout).props('flat')

    ui.separator()

    with ui.card().classes('vh-card w-full'):
        ui.markdown('**⚙️ 관리자 시스템 정보**')
        ui.label(f'DB 파일 경로: {HISTORY_FILE}')
        ui.label(f'DB 파일 존재 여부: {os.path.exists(HISTORY_FILE)}')

    # 2026-08-17(6단계) — 수동 데이터 입력 콘솔은 원본(`views/macro_view.py` 가
    # `render_admin_console()` 을 화면 안에서 호출)과 **같은 자리**인 매크로 화면에
    # 그대로 붙였습니다. 여기서는 그리로 가는 링크만 둡니다.
    ui.markdown(
        '📌 매크로 방공망 수동 데이터 입력 콘솔은 [🏢 매크로 방공망 화면](/admin/macro) 안에 있습니다 '
        '(원본 Streamlit 화면과 같은 위치).'
    ).classes('vh-muted')
