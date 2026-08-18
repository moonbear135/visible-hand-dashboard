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

from utils import data_source
from web.auth import is_admin
from web.components.widgets import error_banner

# (경로, 라벨, 관리자전용) — 실제로 이전이 끝난 화면만 넣습니다. "곧 생길 메뉴"를 미리 만들어
# 두면 사용자가 눌렀을 때 404 가 나므로, 화면이 완성된 단계에서 한 줄씩 추가합니다.
# ⚠️ 관리자 콘솔 링크는 **관리자로 인증된 접속에만** 보여줍니다. 화면 자체는 어차피 비밀번호
#    게이트로 막혀 있지만, 공개 화면에 관리자 입구를 광고해 무차별 대입 표적을 만들 이유가
#    없습니다 (ENGINEERING_SPEC.md §0-3-9 — 알려진 기본 공격면은 줄여둡니다).
# ⚠️ '내 성적표'(/scorecard)·'사장님 보고서'(/report)는 §0-3-6 스테이징 절차를 거쳐
#    2026-08-17 오너 승인으로 공개 전환되었습니다(계획서 §9 "4. scorecard" ⑦ 동시 로그인
#    격리 검증 + 실기기 확인 완료). 로그인 없이는 아무 데이터도 그리지 않으며(로그인 폼만),
#    DB 는 RLS 로 본인 행만 허용합니다(§0-3-8). 두 화면은 같은 로그인 세션을 씁니다(오너 확정).
#
# 2026-08-18 오너 피드백 — 예전 Streamlit 버전은 메뉴가 "사실 이 가격이에요"/"내 성적표"
# 두 그룹으로 묶여 있어 한눈에 보기 편했는데, 지금(NiceGUI)은 4개가 한 줄로 쭉 나열돼 있어
# 정렬이 안 보기 편하다는 지적. 평평한 리스트 대신 **그룹(섹션 제목) + 하위 항목** 구조로
# 되돌립니다. 관리자 전용 항목은 별도 그룹으로 마지막에 붙입니다.
_MENU_GROUPS = [
    ('💡 사실 이 가격이에요', [
        ('/', '🇰🇷 한국 주식은 이가격이에요', False),
        ('/us', '🇺🇸 미국 주식은 이가격이에요', False),
    ]),
    ('📊 내 성적표', [
        ('/scorecard', '💼 내 보유종목', False),
        ('/report', '📈 사장님 보고서', False),
    ]),
    # 🏢 매크로 방공망 — **관리자 전용**(공개 화면에서 내려온 지 2026-08-05부터)이고,
    #    오너 지시(2026-08-10)로 **개발 중단 상태**입니다. 메뉴에도 관리자에게만 보입니다.
    ('⚙️ 관리자', [
        ('/admin/macro', '🏢 매크로 방공망 (관리자 전용)', True),
        ('/admin', '⚙️ 관리자 콘솔', True),
    ]),
]

# 하위호환용 평평한 목록 — `_MENU_GROUPS` 를 펼친 것뿐이라 항목(경로·라벨·관리자전용) 값은
# 그룹으로 나누기 전과 완전히 동일합니다(§0-3-10 — 값의 출처를 하나로 유지). 기존에
# `web.layout._MENU` 를 직접 참조하던 배선 검사(`tests/test_web_session_isolation.py`
# [8] 매크로 배선)가 계속 통과하도록 남겨둡니다.
_MENU = [item for _, group_items in _MENU_GROUPS for item in group_items]


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
            # 2026-08-18 오너 피드백 — "사이드탭 여는 버튼이 너무 안 보여": 기존 `flat` 버튼은
            # 배경 없이 아이콘만 떠 있어 헤더 색 위에서 존재감이 거의 없었습니다. 흰 원형
            # 배경 + 진한 아이콘 색으로 바꿔, 눌러야 할 자리라는 게 한눈에 보이게 했습니다.
            ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
                .props('round unelevated color=white text-color=primary size=md') \
                .classes('shadow-2')
            ui.label('💡 잘 보면 보이는 손').classes('text-lg font-bold')
        ui.label(title).classes('text-sm opacity-70')

    admin = is_admin()
    with ui.left_drawer(value=False) as drawer:
        with ui.column().classes('gap-1 p-2'):
            # 2026-08-18 오너 피드백 — 예전 Streamlit 메뉴처럼 "그룹 제목 + 하위 항목"으로
            # 묶어서 정렬을 보기 편하게 바꿨습니다(위 `_MENU_GROUPS` 참고). 그룹 제목은
            # 클릭 대상이 아니라 구획을 나누는 안내용이라 링크가 아닌 라벨로 둡니다.
            for group_label, items in _MENU_GROUPS:
                visible_items = [
                    (path, label) for path, label, admin_only in items
                    if not admin_only or admin
                ]
                if not visible_items:
                    continue
                ui.label(group_label).classes(
                    'text-xs font-bold uppercase tracking-wide opacity-60 mt-3 mb-1'
                )
                for path, label in visible_items:
                    ui.link(label, path).classes(
                        'text-base no-underline pl-3 py-1 rounded-borders vh-menu-link'
                    )

    with ui.column().classes(f'w-full {width_class} mx-auto p-4 gap-4 vh-page'):
        # 🚨 "지금 보이는 값이 최신이 아닐 수 있음" 전역 배너 자리 (NICEGUI_MIGRATION_PLAN §8-5).
        #    · **자리만 먼저 잡고**, 실제 판정은 본문을 다 그린 뒤에 합니다. 본문이 데이터를
        #      읽는 도중에 실패가 확정되기 때문에, 본문보다 먼저 판정하면 "한 박자 늦은 배너"가
        #      됩니다. NiceGUI 는 나중에 만든 요소도 지정한 컨테이너 안에 들어가므로, 화면에는
        #      정상적으로 **맨 위**에 보입니다.
        #    · 화면 5개(pegy/us_stocks/scorecard/report/macro)에 같은 코드를 복붙하지 않으려고
        #      모든 페이지가 공유하는 이 한 곳에 둡니다 (ENGINEERING_SPEC.md §0-3-10).
        stale_slot = ui.element('div').classes('w-full')
        yield
        _render_staleness_banner(stale_slot)


def _render_staleness_banner(slot) -> None:
    """원격 데이터가 최신이 아닐 때만 빨간 배너를 그립니다. 정상이면 아무것도 그리지 않습니다.

    언제 뜨나 — `DATA_SOURCE_BASE_URL` 이 켜져 있고, 이번 프로세스에서 어떤 파일이든 최신화에
    실패해 **마지막 성공분(또는 배포에 함께 실린 사본)** 을 보여주고 있을 때.
    언제 사라지나 — 그 파일의 다음 fetch 가 성공하면 상태가 스스로 풀립니다. 즉 **다음에
    페이지를 열면** 배너가 없습니다. 이미 열려 있는 화면을 자동으로 고치지는 않습니다
    (§0-3-1 — 실시간처럼 보이게 만들지 않습니다).
    """
    try:
        status = data_source.get_staleness_status()
        if not status:
            return
        with slot:
            error_banner(status['message'])
    except Exception as exc:                          # noqa: BLE001 — 배너 때문에 화면이 죽으면 안 됩니다
        print(f'⚠️ 데이터 최신성 배너 표시 실패: {exc}')
