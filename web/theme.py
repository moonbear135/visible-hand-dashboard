"""
전역 CSS 등록 (NiceGUI 이전 0단계).

2026-08-16 — 이전 계획서(NICEGUI_MIGRATION_PLAN.md) §5-2 "프로젝트 반응형 규약"의
실제 구현 시작점입니다. Streamlit에서 겪은 문제(특히 #127~#130의 `st.columns()` 세로쌓임)
는 여기서 CSS를 f-string으로 조립하지 않고(그 f-string 중괄호 이스케이프 실수가 #129
크래시의 원인이었습니다 — TASK_HISTORY 참고) 순수 정적 문자열 하나만 등록하는 것으로도
이미 절반은 예방됩니다.

이 파일은 앞으로 화면(pegy·us_stocks·scorecard 등)을 옮길 때마다 기존 Streamlit CSS
(`.q-tooltip` 툴팁, 카드 스타일 등)를 그대로 옮겨와 붙이는 자리입니다. 0단계에서는
데모 페이지에 필요한 최소 스타일만 둡니다.
"""

from nicegui import ui

_CSS = """
/* 0단계 검증용 최소 스타일 — 이후 단계에서 기존 Streamlit CSS를 여기로 이식합니다. */
.vh-card {
    border: 1px solid rgba(49, 51, 63, 0.15);
    border-radius: 8px;
    padding: 12px 16px;
}
.vh-muted {
    color: rgba(49, 51, 63, 0.6);
    font-size: 0.85rem;
}
"""


def register() -> None:
    """main.py 에서 ui.run() 호출 전에 한 번만 부릅니다."""
    ui.add_css(_CSS)
