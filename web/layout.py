"""
헤더 + 좌측 드로어(사이드바) 뼈대 (NiceGUI 이전 0단계 → 2단계에서 메뉴 배선 시작).

각 페이지 함수는 이렇게 씁니다:

    from web.layout import layout

    @ui.page('/some-page')
    def some_page():
        with layout('화면 제목'):
            ui.label('본문')

메뉴(한국 주식/미국 주식/내 성적표/사장님 보고서)는 각 화면을 옮길 때마다 여기 드로어에
한 줄씩 채웁니다 (NICEGUI_MIGRATION_PLAN.md §3-2 라우팅 표).
"""

from contextlib import contextmanager

from nicegui import ui

from web.auth import is_admin

# (경로, 라벨, 관리자전용) — 실제로 이전이 끝난 화면만 넣습니다. "곧 생길 메뉴"를 미리 만들어
# 두면 사용자가 눌렀을 때 404 가 나므로, 화면이 완성된 단계에서 한 줄씩 추가합니다.
# ⚠️ 관리자 콘솔 링크는 **관리자로 인증된 접속에만** 보여줍니다. 화면 자체는 어차피 비밀번호
#    게이트로 막혀 있지만, 공개 화면에 관리자 입구를 광고해 무차별 대입 표적을 만들 이유가
#    없습니다 (ENGINEERING_SPEC.md §0-3-9 — 알려진 기본 공격면은 줄여둡니다).
# ⚠️ '내 성적표'(/scorecard)는 **스테이징 상태**입니다 (§0-3-6 — 오너 승인 전 공개 금지).
#    그래서 메뉴에는 관리자에게만 보입니다. 화면 자체는 URL 로 접근할 수 있지만 로그인 없이는
#    아무 데이터도 그리지 않으며(로그인 폼만), DB 는 RLS 로 본인 행만 허용합니다(§0-3-8).
#    실기기 동시 로그인 검증(계획서 §9 "4. scorecard" ⑦)을 하려면 시크릿창에서 주소를 직접
#    입력하면 됩니다 — 그 검증이 끝나고 오너가 승인하면 이 줄의 `True` 를 `False` 로 바꿉니다.
# ⚠️ '사장님 보고서'(/report)도 **같은 스테이징 규칙**입니다(§0-3-6). '내 성적표'와 **같은
#    로그인 세션**을 쓰므로(오너 확정), 한쪽에서 로그인하면 다른 쪽도 폼 없이 열립니다.
_MENU = [
    ('/', '🇰🇷 한국 주식은 이가격이에요', False),
    ('/us', '🇺🇸 미국 주식은 이가격이에요', False),
    ('/scorecard', '📊 내 성적표 (스테이징)', True),
    ('/report', '📈 사장님 보고서 (스테이징)', True),
    ('/admin', '⚙️ 관리자 콘솔', True),
]


@contextmanager
def layout(title: str, width_class: str = 'max-w-4xl'):
    """공통 껍데기.

    :param title: 헤더 우측에 작게 표시할 화면 이름
    :param width_class: 본문 최대 폭(Tailwind). 카드가 넓은 화면(pegy 등)은 'max-w-6xl'.
    """
    # 화면 카드가 전부 짙은 남색 계열이라(기존 Streamlit 다크 테마 기준으로 만들어진 HTML)
    # 밝은 배경 위에 그리면 인상이 크게 달라집니다. 프로젝트 전체를 다크로 고정합니다.
    ui.dark_mode(True)

    with ui.header().classes('items-center justify-between q-pa-sm'):
        with ui.row().classes('items-center gap-2'):
            ui.button(icon='menu', on_click=lambda: drawer.toggle()).props('flat dense round')
            ui.label('💡 잘 보면 보이는 손').classes('text-lg font-bold')
        ui.label(title).classes('text-sm opacity-70')

    admin = is_admin()
    with ui.left_drawer(value=False) as drawer:
        with ui.column().classes('gap-2 p-2'):
            for path, label, admin_only in _MENU:
                if admin_only and not admin:
                    continue
                ui.link(label, path).classes('text-base no-underline')

    with ui.column().classes(f'w-full {width_class} mx-auto p-4 gap-4 vh-page'):
        yield
