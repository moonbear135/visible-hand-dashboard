"""
0단계 검증 전용 데모 페이지.

NICEGUI_MIGRATION_PLAN.md §5-2 "프로젝트 반응형 규약"의 패턴 A~D를 실제로 그려서
오너가 폰(같은 Wi-Fi에서 이 서버의 로컬 IP로 접속, 또는 Render 배포 후 실주소)으로
직접 확인하는 화면입니다.

0단계 완료 기준(계획서 §9):
  ① https://<서비스>.onrender.com 이 뜬다
  ② /healthz 가 {"ok": true}
  ③ 폰 세로/가로 모두 가로 스크롤이 0px
  ④ 새로고침해도 아래 카운터 값이 유지된다 (app.storage.user 확인)
  ⑤ 서버 로그에 KST 시각이 정확히 찍힌다 (Dockerfile의 tzdata 설치 확인용)

이 파일은 1단계 이후 실제 화면(admin/pegy/...)으로 교체될 때 지워도 됩니다.
"""

from datetime import datetime

from nicegui import ui

from web.auth import bump_demo_counter, get_demo_counter
from web.layout import layout


@ui.page('/')
def index_page() -> None:
    with layout('0단계 — 모바일 반응형 데모'):
        ui.markdown(
            '이 화면은 **0단계 검증 전용**입니다. 폰으로 열어서 '
            '① 좌우로 아무리 밀어도 화면이 안 밀리는지, '
            '② 아래 4가지 패턴이 각각 의도대로 보이는지 확인해주세요.'
        )

        # ── 새로고침 유지 확인 (app.storage.user) ──────────────────────────
        with ui.card().classes('vh-card w-full'):
            ui.markdown('**새로고침 유지 테스트** — 버튼을 누르고 브라우저를 새로고침해도 숫자가 그대로면 정상')
            counter_label = ui.label(f'지금 값: {get_demo_counter()}')

            def _bump() -> None:
                counter_label.text = f'지금 값: {bump_demo_counter()}'

            ui.button('숫자 올리기', on_click=_bump)

        ui.separator()

        # ── 패턴 A: 항상 한 줄 유지 (라벨 + 버튼 2개) ────────────────────────
        # #127~#130에서 여섯 차례 씨름했던 바로 그 레이아웃. st.columns() 없이
        # 일반 ui.row() + flex 클래스만으로 화면 폭과 무관하게 항상 한 줄을 유지합니다.
        ui.markdown('**패턴 A — 항상 한 줄 유지** (종목명 + ✏️ + 🗑️ 같은 줄)')
        with ui.row().classes('no-wrap items-center gap-2 w-full vh-card'):
            ui.label('아주 아주 아주 아주 긴 종목명 예시 표시용 (005387)').classes('flex-1 min-w-0 truncate')
            ui.button(icon='edit').props('flat dense').classes('shrink-0')
            ui.button(icon='delete').props('flat dense').classes('shrink-0')

        # ── 패턴 B: 넓은 표는 가로 스크롤 ────────────────────────────────────
        # #127에서 <table> + overflow-x:auto 로 해결한 방식을 그대로 재현.
        ui.markdown('**패턴 B — 넓은 표는 가로 스크롤** (세로로 안 쌓임)')
        _table_html = (
            '<table style="border-collapse:collapse;width:100%;min-width:640px;font-size:0.9rem;">'
            '<tr>' + ''.join(
                f'<th style="padding:6px 10px;text-align:right;border-bottom:1px solid rgba(49,51,63,.15);">칸{i}</th>'
                for i in range(1, 8)
            ) + '</tr>'
            '<tr>' + ''.join(
                f'<td style="padding:6px 10px;text-align:right;border-bottom:1px solid rgba(49,51,63,.15);">값{i}</td>'
                for i in range(1, 8)
            ) + '</tr>'
            '</table>'
        )
        with ui.element('div').classes('w-full overflow-x-auto vh-card'):
            ui.html(_table_html)

        # ── 패턴 C: 좁아지면 자연스럽게 줄바꿈 ────────────────────────────────
        ui.markdown('**패턴 C — 좁아지면 자연스럽게 줄바꿈되는 카드** (요약 지표류)')
        with ui.row().classes('w-full gap-4'):
            for label, value in [
                ('매입원가 합계', '2,017,840원'),
                ('평가금액 합계', '1,692,425원'),
                ('평가손익', '-325,415원'),
            ]:
                with ui.column().classes('vh-card'):
                    ui.label(label).classes('vh-muted')
                    ui.label(value).classes('text-xl font-bold')

        # ── 패턴 D: 화면 폭에 따라 칸 수가 바뀌는 그리드 ──────────────────────
        ui.markdown('**패턴 D — 화면 폭별 그리드** (좁으면 1칸, 넓으면 2~3칸)')
        with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 w-full'):
            for i in range(1, 4):
                ui.label(f'그리드 칸 {i}').classes('vh-card text-center')

        ui.separator()
        ui.label(f'서버 시각(KST 기대값 — tzdata 확인용): {datetime.now():%Y-%m-%d %H:%M:%S}').classes('vh-muted')
