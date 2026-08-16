"""
헤더 + 좌측 드로어(사이드바) 뼈대 (NiceGUI 이전 0단계).

각 페이지 함수는 이렇게 씁니다:

    from web.layout import layout

    @ui.page('/some-page')
    def some_page():
        with layout('화면 제목'):
            ui.label('본문')

지금은 골격만입니다. 실제 메뉴 라우팅(한국 주식/미국 주식/내 성적표/사장님 보고서)은
2~6단계에서 각 화면을 옮기며 이 드로어에 실제 링크를 채워 넣습니다
(NICEGUI_MIGRATION_PLAN.md §3-2 라우팅 표 참고).
"""

from contextlib import contextmanager

from nicegui import ui


@contextmanager
def layout(title: str):
    with ui.header().classes('items-center justify-between q-pa-sm'):
        with ui.row().classes('items-center gap-2'):
            ui.label('💡 잘 보면 보이는 손').classes('text-lg font-bold')
        ui.label(title).classes('vh-muted')

    with ui.left_drawer(value=False).classes('bg-gray-50') as drawer:
        ui.label('메뉴 (0단계 — 아직 배선 전)').classes('vh-muted q-pa-sm')
        # 2~6단계에서 여기에 ui.link('한국 주식', '/'), ui.link('미국 주식', '/us') 등을 채웁니다.

    with ui.column().classes('w-full max-w-4xl mx-auto p-4 gap-4'):
        yield
