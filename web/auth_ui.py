"""
🔐 로그인 / 회원가입 / 비밀번호 찾기 **화면 조각** — 로그인이 필요한 화면들이 함께 씁니다.

지금 쓰는 곳: `/scorecard`(내 성적표, 4단계) · `/report`(사장님 보고서, 5단계).
두 화면은 **같은 Supabase 로그인 세션을 공유**합니다(오너 확정 — 한쪽에서 로그인하면
다른 쪽도 로그인 상태). 그 공유는 `web/auth.py` 의 `app.storage.user` 하나로 이미
이뤄지고, 이 파일은 **그 위에 그리는 폼이 두 화면에서 글자 하나까지 같도록** 합니다
(ENGINEERING_SPEC.md §0-3-10 — 같은 로직을 화면마다 복붙하지 않기).

⚠️ 5단계(2026-08-17)에 `web/pages/scorecard_page.py` 에서 **그대로 옮겨온** 코드입니다.
   옮기면서 동작은 한 군데도 바꾸지 않았습니다(문구·순서·이벤트·오류 처리 전부 동일).

🔴 §0-3-8 — 이 파일은 **사용자 데이터를 저장하지도, 전역에 남기지도 않습니다.**
   토큰을 넣는 곳은 오직 `web/auth.py::login()` 이고 그 저장소는 접속자별입니다.
   모듈 최상위에는 상수도 두지 않았습니다(함수 정의뿐).
"""

from contextlib import contextmanager

from nicegui import run, ui

from utils.scorecard_db import (
    ScorecardError,
    reset_password_with_code,
    send_password_reset_code,
    sign_up,
)
from web.auth import get_client_async, login, new_auth_client
from web.components import info_banner


def fail_message(exc, fallback: str, *, context: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장.

    `ScorecardError`(우리가 직접 만든 한국어 메시지)는 그대로 보여주고, 그 밖의 예상 못 한
    예외는 **원문을 화면에 흘리지 않고**(§0-3-4) 서버 로그로만 보냅니다.

    :param context: 서버 로그에만 찍히는 화면 이름(예: '내 성적표'). 화면에는 나오지 않습니다.
    """
    if isinstance(exc, ScorecardError):
        return str(exc)
    print(f'⚠️ {context} 처리 중 예상하지 못한 오류: {type(exc).__name__}: {exc}')
    return fallback


@contextmanager
def busy(button: ui.button):
    """버튼을 로딩 상태로 바꿔 중복 클릭을 막습니다.

    🔴 2026-08-17 (오너 실기기 신고) — Supabase 네트워크 응답까지 2~3초 걸리는데, 그동안
    화면에 아무 표시가 없으면 "로그인 안 된 줄 알고" 여러 번 눌러 요청이 중복 발사되고,
    운 나쁘면 그중 하나가 레이트리밋/일시 오류로 실패해 "비밀번호가 틀렸다"처럼 보이는
    혼란스러운 화면이 됩니다. 버튼에 Quasar 내장 `loading` 표시를 켜고 클릭을 막아서
    "지금 처리 중"임을 명확히 보여주고, 끝나면(성공/실패 상관없이) 원상복구합니다.

    로그인/회원가입/비밀번호 재설정 코드 발송/비밀번호 변경 4곳이 전부 같은 네트워크
    지연을 겪으므로 여기 한 곳에 모아 재사용합니다(§0-3-10 중복 금지).

    ⚠️ 이것만으로는 부족합니다 — 호출하는 쪽(`_submit`/`_send_code`/`_confirm`)이
    `async def` 이고, 안의 네트워크 호출을 `await run.io_bound(...)` 로 감싸야만
    실제로 화면에 로딩 표시가 그려집니다. 동기 함수를 그냥 부르면 응답이 올 때까지
    이 접속의 이벤트 루프 전체가 멈춰서, 이 함수가 막 켠 `loading` 상태조차 브라우저로
    전송되지 못합니다(2026-08-17 오너 실기기 신고 — "스피너가 전혀 안 뜬다"의 원인).
    """
    button.props('loading')
    button.disable()
    try:
        yield
    finally:
        button.props(remove='loading')
        button.enable()


def render_auth() -> None:
    """로그인 전 화면(3탭). 이 함수 안에서는 사용자 데이터를 읽거나 쓰지 않습니다.

    ⚠️ '내 성적표'와 '사장님 보고서'가 **같은 계정**이므로 이 폼도 하나만 둡니다.
       어느 쪽 화면에서 로그인하든 같은 세션이 만들어지고, 로그인 뒤에는 그 자리에서
       (`ui.navigate.reload()`) 원래 보던 화면이 그대로 다시 그려집니다.
    """
    ui.markdown('#### 🔐 로그인')
    ui.label('비밀번호는 Supabase Auth 가 관리합니다 — 이 앱은 비밀번호를 저장하지도, 볼 수도 없습니다.') \
        .classes('vh-muted')
    ui.label("'📊 내 성적표'와 '📈 사장님 보고서'는 같은 계정을 씁니다(한 번 로그인하면 둘 다 열립니다).") \
        .classes('vh-muted')

    with ui.tabs().classes('w-full') as tabs:
        tab_login = ui.tab('로그인')
        tab_signup = ui.tab('회원가입')
        tab_reset = ui.tab('비밀번호 찾기')
    with ui.tab_panels(tabs, value=tab_login).classes('w-full'):
        with ui.tab_panel(tab_login):
            _render_login_form()
        with ui.tab_panel(tab_signup):
            _render_signup_form()
        with ui.tab_panel(tab_reset):
            _render_reset_form()


def _render_login_form() -> None:
    message = ui.label('').classes('text-red-400')

    async def _submit() -> None:
        message.text = ''
        with busy(login_btn):
            try:
                # ⚠️ login() 자체를 io_bound로 감싸지 않습니다 — login()은 접속별
                # 저장소(user_storage()/client_storage())를 읽고 쓰는데, io_bound
                # 스레드 안에서는 그 접속 컨텍스트를 알 수 없어 깨집니다(자세한 사고 경위는
                # web/auth.py 의 login() 함수 docstring 참고). login()은 `async def` 로
                # 이벤트 루프에서 그대로 돌고, 그 안의 네트워크 호출 한 줄만 io_bound 를 씁니다 —
                # 그 한 번의 `await` 만으로 버튼 로딩 표시가 화면에 그려질 시간은 충분합니다.
                user = await login(email_input.value or '', password_input.value or '')
            except Exception as exc:                   # noqa: BLE001
                message.text = f'🚫 {fail_message(exc, "로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.", context="로그인")}'
                return
            if user is None:
                message.text = '🚫 로그인에 실패했습니다(사용자 정보를 받지 못했습니다).'
                return
        # 비밀번호가 브라우저 메모리에 남지 않도록 비우고, 같은 주소를 다시 그립니다.
        # ⚠️ 이동 주소는 우리가 정한 고정 경로뿐입니다 — 사용자가 준 URL 로 보내지 않습니다
        #    (§0-3-9 오픈 리다이렉트 방지). `reload()` 는 **지금 보고 있는 화면**을 다시
        #    그리므로, /scorecard 에서 로그인하면 /scorecard 가, /report 에서 로그인하면
        #    /report 가 그대로 이어집니다.
        password_input.value = ''
        ui.navigate.reload()

    email_input = ui.input('이메일').classes('w-full max-w-sm').on('keydown.enter', _submit)
    password_input = ui.input('비밀번호', password=True, password_toggle_button=True) \
        .classes('w-full max-w-sm').on('keydown.enter', _submit)
    login_btn = ui.button('로그인', on_click=_submit)
    ui.label(
        '🔑 비밀번호를 잊으셨나요? 새 계정을 만들지 마시고 위 "비밀번호 찾기" 탭에서 '
        '이메일로 코드를 받아 새 비밀번호를 정하세요 — 기존에 입력한 보유 종목이 그대로 남습니다.'
    ).classes('vh-muted')


def _render_signup_form() -> None:
    info_banner(
        '가입 시 참고 — 1년 이상 접속하지 않은 계정의 데이터는 나중에 정리될 수 있습니다. '
        '(v1은 안내만 하고 자동 삭제 기능은 아직 없습니다.)'
    )
    message = ui.label('').classes('text-red-400')

    async def _submit() -> None:
        message.text = ''
        if (password_input.value or '') != (confirm_input.value or ''):
            message.text = '🚫 비밀번호가 서로 다릅니다.'
            return
        with busy(signup_btn):
            try:
                # 🔴 2026-08-21 — `get_client()` → `await get_client_async()`. 그 안의 세션
                #    복원(`set_session`)이 만료된 토큰을 만나면 refresh 왕복(HTTP)을 하는데,
                #    그것도 이벤트 루프를 붙잡던 자리였습니다. 저장소 접근은 여전히 전부
                #    이벤트 루프에서 일어납니다(`web/auth.py::get_client_async()` 독스트링).
                client = await get_client_async()
                if client is None:
                    message.text = '🚫 Supabase 연결이 준비되지 않아 가입할 수 없습니다.'
                    return
                # run.io_bound 이유는 로그인 폼과 동일 — 동기 네트워크 호출이 이벤트 루프를
                # 막아 로딩 표시가 화면에 안 그려지는 문제 방지.
                await run.io_bound(sign_up, client, (email_input.value or '').strip(), password_input.value or '')
            except Exception as exc:                   # noqa: BLE001
                message.text = f'🚫 {fail_message(exc, "가입 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.", context="회원가입")}'
                return
        message.text = ''
        password_input.value = ''
        confirm_input.value = ''
        ui.notify(
            '✅ 가입 요청이 접수되었습니다. 이메일 인증이 켜져 있으면 받은 메일함을 확인한 뒤 '
            '로그인 탭에서 로그인해 주세요.',
            type='positive', multi_line=True, close_button='닫기',
        )

    email_input = ui.input('이메일').classes('w-full max-w-sm')
    # ⚠️ 계정 열거(user enumeration) 방어와 UX 를 함께 만족시키기 위한 안내입니다.
    #    `utils/scorecard_db.py::sign_up()` 은 **이미 가입된 이메일인지 여부를 화면에
    #    알려주지 않습니다**(§0-3-9). 그래서 중복 가입을 시도한 사람은 "접수됐다"는 안내를
    #    받고도 메일이 오지 않을 수 있는데, 아무 설명이 없으면 그 사람만 영문을 모른 채
    #    막힙니다. 이 문구는 **누구에게나 항상 보이므로** 특정 이메일의 가입 여부를
    #    알려주지 않으면서도 다음에 뭘 하면 되는지는 알려줍니다.
    ui.label(
        '이미 가입된 이메일로 다시 가입하면 안내 메일이 오지 않을 수 있습니다 — '
        '그럴 때는 위 "비밀번호 찾기" 탭에서 비밀번호를 새로 정해 주세요.'
    ).classes('vh-muted')
    password_input = ui.input('비밀번호', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.label('8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.').classes('vh-muted')
    confirm_input = ui.input('비밀번호 확인', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    signup_btn = ui.button('회원가입', on_click=_submit)


def _render_reset_form() -> None:
    """비밀번호 재설정 (메일로 받은 **코드** 입력 방식 — #109/#110 에서 검증된 그 방식 그대로).

    ⚠️ 이 폼 어디에서도 로그인 세션을 건드리지 않습니다. 코드 검증은 `new_auth_client()` 로
       만든 1회용 클라이언트에서만 일어나고, 끝나면 그 세션은 로그아웃됩니다(§0-3-8).

    2026-08-17 (오너 UX 지적) — 원래 이메일 입력칸이 1단계/2단계에 각각 하나씩(총 2개)
    있었습니다. 2단계 칸은 1단계 발송 성공 후 자동으로 채워지긴 했지만, 애초에 "같은
    비밀번호 재설정 요청" 안에서 이메일이 바뀔 이유가 없어 입력칸 자체가 불필요했습니다
    (기존 Streamlit 원본을 그대로 이식한 부분이었는데, 실사용해보니 번거로워서 여기서
    걷어냅니다 — §0-3-10 "쓰지 않는 걸 굳이 남겨두지 않는다"). 이제 1단계에서 입력한
    이메일을 2단계에서도 그대로 재사용합니다.
    """
    ui.label(
        '가입한 이메일로 재설정 코드를 보내드립니다. 메일에 적힌 숫자를 아래 2단계에 그대로 '
        '입력하면 새 비밀번호를 정할 수 있습니다.'
    ).classes('vh-muted')

    message = ui.label('').classes('text-red-400')

    ui.markdown('**1단계 · 재설정 코드 받기**')

    async def _send_code() -> None:
        message.text = ''
        address = (request_email.value or '').strip()
        with busy(send_code_btn):
            try:
                client = await get_client_async()      # 이유는 위 회원가입 폼과 동일
                if client is None:
                    message.text = '🚫 Supabase 연결이 준비되지 않아 코드를 보낼 수 없습니다.'
                    return
                # 발송 요청은 로그인 세션을 만들지 않으므로 이 접속의 클라이언트로 보내도 안전합니다.
                notice = await run.io_bound(send_password_reset_code, client, address)
            except Exception as exc:                   # noqa: BLE001
                message.text = f'🚫 {fail_message(exc, "재설정 코드를 보내지 못했습니다. 잠시 후 다시 시도해 주세요.", context="비밀번호 재설정")}'
                return
        # ⚠️ 가입된 이메일인지 여부는 알려주지 않습니다(계정 존재 여부 유출 방지, §0-3-9).
        ui.notify(f'✅ {notice}', type='positive', multi_line=True, close_button='닫기')

    request_email = ui.input('가입한 이메일').classes('w-full max-w-sm')
    send_code_btn = ui.button('재설정 코드 보내기', on_click=_send_code)

    ui.markdown('**2단계 · 받은 코드로 새 비밀번호 정하기**')

    async def _confirm() -> None:
        message.text = ''
        with busy(confirm_btn):
            try:
                await run.io_bound(
                    reset_password_with_code,
                    new_auth_client(),
                    (request_email.value or '').strip(),  # 1단계에서 입력한 이메일을 그대로 재사용
                    code_input.value or '',
                    new_pw.value or '',
                    new_pw2.value or '',
                )
            except Exception as exc:                   # noqa: BLE001
                message.text = f'🚫 {fail_message(exc, "비밀번호를 변경하지 못했습니다. 잠시 후 다시 시도해 주세요.", context="비밀번호 재설정")}'
                return
        code_input.value = ''
        new_pw.value = ''
        new_pw2.value = ''
        ui.notify(
            '✅ 비밀번호를 변경했습니다. 위 "로그인" 탭에서 새 비밀번호로 로그인해 주세요.',
            type='positive', multi_line=True, close_button='닫기',
        )

    code_input = ui.input('이메일로 받은 코드') \
        .classes('w-full max-w-sm') \
        .tooltip('메일 본문에 적힌 숫자 코드를 그대로 입력하세요. 링크를 누를 필요는 없습니다.')
    new_pw = ui.input('새 비밀번호', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.label('8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.').classes('vh-muted')
    new_pw2 = ui.input('새 비밀번호 확인', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    confirm_btn = ui.button('비밀번호 변경', on_click=_confirm)
