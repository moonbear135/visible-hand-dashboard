# tests/_render_helpers.py
"""
NiceGUI 화면 함수를 테스트에서 **실제로 실행**할 때 쓰는 공용 헬퍼.

2026-08-29 재감사(스코어카드 모듈) M-6 — 원래 이 함수(`_run`)는
`tests/test_scorecard_public_ui.py` 안에만 있었고, `tests/test_scorecard_ocr.py`의 렌더
스모크(`test_upload_widget_is_really_not_rendered_when_flag_is_off`)는 그냥 `asyncio.run(...)`
을 직접 썼습니다. NiceGUI는 "위젯이 그려질 자리(슬롯)"를 asyncio 태스크별로 들고 있는데,
`asyncio.run(...)`은 새 태스크를 만들어 그 안에서는 슬롯 스택이 비어 `RuntimeError`가 납니다
(에러 메시지 자체가 권하는 대로 `with container_element:`로 명시적으로 슬롯에 들어가야
합니다). 게다가 이 프로세스에서 처음 만들어지는 "유사 클라이언트"는 프로세스당 한 번만
생기므로(`nicegui/context.py`), 슬롯 전파 없이 `asyncio.run()`을 쓰는 렌더 스모크가 하나라도
먼저 돌면 그 한 번을 소진해서 **그 뒤에 도는 다른 파일의 렌더 스모크까지 전부 연쇄 실패**
합니다 — 실행 순서에 따라 실패 수가 갈리던 원인이 이것입니다. 두 파일이 이 함수 하나를
같이 쓰면(§0-3-10) 그 문제가 사라집니다.

실행: 이 파일 자체는 테스트가 아닙니다(파일 이름이 `test_`로 시작하지 않아 pytest가
수집하지 않습니다). `tests/`가 패키지가 아니라서(`__init__.py` 없음) `from tests._render_helpers import ...`
는 실제로는 `ModuleNotFoundError`가 납니다 — 실제 쓰는 파일들(예:
`test_scorecard_public_ui.py`, `test_web_session_isolation.py`)처럼 각 테스트 파일
맨 위에서 `sys.path.append(str(Path(__file__).parent))`로 `tests/` 자신을 경로에 얹은 뒤
`from _render_helpers import run_render` 로 가져다 씁니다.

2026-08-30 재감사(테스트 스위트) M-3 — 이 파일이 옮겨지기 전에 쓰던 예시 그대로 남아
있던 잘못된 import 경로를 실제 호출 관례에 맞게 바로잡음.
"""

import asyncio


def run_render(coro):
    """비동기 화면 함수를 끝까지 실행합니다 (NiceGUI 슬롯 컨텍스트를 함께 넘겨서)."""
    try:
        from nicegui import context as nicegui_context
        from nicegui.slot import Slot, get_task_id
    except ImportError:                            # 스텁 환경(nicegui 미설치)
        return asyncio.run(coro)

    outer = list(nicegui_context.slot_stack)

    async def _main():
        Slot.stacks[get_task_id()] = list(outer)
        try:
            return await coro
        finally:
            Slot.stacks.pop(get_task_id(), None)

    return asyncio.run(_main())
