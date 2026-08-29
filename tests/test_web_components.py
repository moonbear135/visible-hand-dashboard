# tests/test_web_components.py
"""
공용 화면 조각(`web/components/`) 회귀 테스트.

`guard_double_click`(중복 클릭 방어)은 원래 `duel_page.py` 전용 `_guard_double_click`
(2026-08-29 재감사 M-3)이었는데, 같은 재감사 M-10에서 `indicator_page.py`도 같은
결함(AI 해설 버튼을 빠르게 두 번 누르면 유료 Gemini 호출이 2회 나감)을 갖고 있는 것이
드러나 `web/components/widgets.py`로 승격했습니다(§0-3-10 — 두 번째 소비자가 생긴
시점에 화면 전용 헬퍼를 공용 모듈로 옮깁니다). 이 파일은 그 승격된 함수 자체를
NiceGUI 없이(가짜 버튼 객체로) 검증합니다.

실행: python -m pytest tests/test_web_components.py -v
"""
import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from web.components.widgets import guard_double_click


class _FakeButton:
    """`ui.button`을 대신하는 가짜 — `disable()`/`enable()` 호출 여부·순서만 봅니다."""

    def __init__(self):
        self.disabled = False
        self.disable_calls = 0
        self.enable_calls = 0

    def disable(self):
        self.disabled = True
        self.disable_calls += 1

    def enable(self):
        self.disabled = False
        self.enable_calls += 1


def test_guard_double_click_drops_second_click_while_first_in_flight():
    """처리 중(첫 호출이 아직 안 끝남)일 때 들어온 두 번째 호출은 핸들러를 다시 부르지
    않고 조용히 버려야 합니다 — 이게 M-3/M-10이 요구하는 핵심 동작입니다."""
    calls = {"count": 0}
    gate = asyncio.Event()

    async def handler():
        calls["count"] += 1
        await gate.wait()  # "await run_blocking(...)" 같은 느린 왕복을 흉내냅니다.

    async def _run():
        wrapped = guard_double_click(handler)
        button = _FakeButton()
        wrapped.bind_button(button)

        first = asyncio.create_task(wrapped())
        await asyncio.sleep(0)  # 첫 호출이 시작돼 running=True/버튼 잠금까지 진행되게 함
        assert button.disabled is True, "처리 중에는 버튼이 잠겨 있어야 합니다"

        await wrapped()  # 두 번째 클릭 — 처리 중이므로 즉시 반환, 핸들러 재호출 없음
        assert calls["count"] == 1, "처리 중 두 번째 클릭이 핸들러를 또 불렀습니다(중복 클릭 방어 실패)"

        gate.set()
        await first
        assert button.disabled is False, "완료 후에는 버튼이 다시 풀려야 합니다"
        assert calls["count"] == 1

    asyncio.run(_run())


def test_guard_double_click_allows_sequential_calls_after_completion():
    """처리가 끝난 뒤의 새 클릭은 정상적으로 핸들러를 다시 부릅니다(영구 잠금이 아님)."""
    calls = {"count": 0}

    async def handler():
        calls["count"] += 1

    async def _run():
        wrapped = guard_double_click(handler)
        wrapped.bind_button(_FakeButton())
        await wrapped()
        await wrapped()
        assert calls["count"] == 2

    asyncio.run(_run())


def test_guard_double_click_reenables_button_after_exception():
    """핸들러가 예외를 던져도 `finally`에서 버튼을 반드시 되살립니다 — 안 그러면 사용자는
    새로고침 전까지 그 버튼을 영원히 못 씁니다."""

    async def handler():
        raise RuntimeError("boom")

    async def _run():
        wrapped = guard_double_click(handler)
        button = _FakeButton()
        wrapped.bind_button(button)
        try:
            await wrapped()
        except RuntimeError:
            pass
        assert button.disabled is False
        assert button.enable_calls == 1

    asyncio.run(_run())


def test_guard_double_click_works_without_bound_button():
    """`bind_button()`을 안 불러도(버튼이 없어도) 크래시하지 않아야 합니다."""
    calls = {"count": 0}

    async def handler():
        calls["count"] += 1

    async def _run():
        wrapped = guard_double_click(handler)
        await wrapped()
        assert calls["count"] == 1

    asyncio.run(_run())
