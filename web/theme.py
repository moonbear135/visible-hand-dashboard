"""
전역 CSS 등록 (NiceGUI 이전 0단계 → 2단계에서 pegy 화면 CSS 이식).

2026-08-16 — 이전 계획서(NICEGUI_MIGRATION_PLAN.md) §5-2 "프로젝트 반응형 규약"의
실제 구현 시작점입니다. Streamlit에서 겪은 문제(특히 #127~#130의 `st.columns()` 세로쌓임)
는 여기서 CSS를 f-string으로 조립하지 않고(그 f-string 중괄호 이스케이프 실수가 #129
크래시의 원인이었습니다 — TASK_HISTORY 참고) 순수 정적 문자열 하나만 등록하는 것으로도
이미 절반은 예방됩니다.

⚠️ 이 파일의 `_CSS` 는 **절대 f-string으로 만들지 마십시오.** CSS는 `{}` 투성이라
   f-string으로 조립하는 순간 #129와 같은 사고(중괄호 이스케이프 누락 → 사이트 전체 크래시)가
   재발합니다. 동적인 값이 필요하면 CSS를 바꾸지 말고 파이썬 쪽에서 **클래스 이름만** 토글하세요.

2026-08-17 (2단계, pegy 이식) 추가분
  - `views/pegy_view.py` 가 매 렌더마다 `st.markdown("<style>...")` 로 주입하던 CSS를
    여기로 옮겼습니다 (계획서 §5-3 "1단계" 채택 — 글자 하나 안 바꾸고 이식).
  - 단 **클래스 이름만** `.q-tooltip`/`.q-tooltiptext` → `.vh-tooltip`/`.vh-tooltiptext` 로
    바꿨습니다. 이유: `.q-tooltip` 은 **Quasar(NiceGUI의 UI 프레임워크)가 실제로 쓰는
    내장 클래스명**입니다. 그대로 두면 우리 규칙(`position: relative; display: inline-flex;
    cursor: help; border-bottom: dotted ...`)이 Quasar 네이티브 툴팁(`ui.tooltip`,
    Quasar 내부 컴포넌트 툴팁)까지 덮어써서 그쪽이 깨집니다. Streamlit에는 Quasar가 없어
    지금까지 문제가 없었을 뿐입니다(계획서 §11-2 "Quasar/Tailwind 기본 스타일과 충돌" 위험).
    CSS 규칙 내용·수치는 한 글자도 바꾸지 않았습니다.
"""

from nicegui import ui

# ⚠️ 아래는 f-string이 아닙니다. 절대 f 접두어를 붙이지 마세요 (#129 재발 방지).
_CSS = """
/* ── 0단계 검증용 최소 스타일 ─────────────────────────────────────────── */
/* 2026-08-17: 2단계에서 화면 전체를 다크로 고정(web/layout.py 의 ui.dark_mode)하면서
   밝은 배경 전제였던 회색 두 개를 다크에서도 읽히는 값으로 바꿨습니다. */
.vh-card {
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 8px;
    padding: 12px 16px;
}
.vh-muted {
    color: #94a3b8;
    font-size: 0.85rem;
}

/* ── 2단계(pegy) 이식분 ───────────────────────────────────────────────── */
/* 페이지 배경 — 카드가 전부 짙은 남색(#0f172a 계열)이라 밝은 배경 위에 두면
   기존 화면과 인상이 크게 달라집니다. Streamlit 다크 테마 배경(#0e1117)에 맞춥니다. */
body.body--dark,
.body--dark .q-page-container {
    background-color: #0e1117;
}
.vh-page {
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}

/* (i) 툴팁 — 기존 .q-tooltip / .q-tooltiptext 규칙 그대로, 이름만 vh- 로 변경 */
.vh-tooltip {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: help;
    color: #94a3b8;
    border-bottom: 1px dotted #64748b;
    font-weight: 500;
}
.vh-tooltip .vh-tooltiptext {
    visibility: hidden;
    width: 300px;
    box-sizing: border-box;
    white-space: normal;
    overflow-wrap: break-word;
    word-break: keep-all;
    line-height: 1.4;
    background-color: #0f172a;
    color: #f1f5f9;
    text-align: left;
    border-radius: 8px;
    padding: 12px 15px;
    position: absolute;
    z-index: 9999;
    bottom: 130%;
    left: 50%;
    transform: translateX(-50%);
    opacity: 0;
    transition: opacity 0.2s ease-in-out, visibility 0.2s;
    border: 1px solid #38bdf8;
    font-size: 11.5px;
    line-height: 1.55;
    box-shadow: 0 6px 18px rgba(0,0,0,0.6);
    font-weight: 400;
}
.vh-tooltip .vh-tooltiptext::after {
    content: "";
    position: absolute;
    top: 100%;
    left: 50%;
    margin-left: -5px;
    border-width: 5px;
    border-style: solid;
    border-color: #38bdf8 transparent transparent transparent;
}
.vh-tooltip:hover .vh-tooltiptext {
    visibility: visible;
    opacity: 1;
}
/* 2026-08-16 (#119→#122→#123 이어서 발견한 진짜 원인, #124→#125로 개선) — 이 (i)
   툴팁 박스는 카드마다 여러 개(Forward ROE·PER·EPS 등) 있고 `visibility: hidden`
   으로만 숨겨 둔 채 `width: 300px`에 `position: absolute; left: 50%;
   transform: translateX(-50%)`로 트리거(ℹ️) 바로 밑에 항상 그려져 있었습니다.
   `visibility: hidden`은 `display: none`과 달리 레이아웃 공간을 계속 차지하므로,
   트리거가 화면 가장자리 근처에 있으면 이 숨겨진 300px 박스가 뷰포트 밖으로
   삐져나가면서도 **눈에는 안 보이는 채** 페이지 전체의 가로 스크롤 폭을 계속
   늘려놓고 있었습니다.
   ⚠️ 2026-08-16 오너 지적 — "모바일이라고 기능을 줄이면 안 된다".
   그래서 #124에서 했던 "좁은 화면엔 아예 display:none으로 꺼버리기"를 되돌리고,
   기능은 그대로 살리되 위치만 화면 안으로 고정합니다:
   ① `tabindex="0"`을 모든 툴팁 트리거에 붙여 **탭(터치)하면 포커스**가 가게 하고
      `:focus`에서도 툴팁이 보이도록 CSS로만 처리(JS 불필요, 다른 곳 탭하면 자동으로 닫힘).
   ② 좁은 화면에서는 툴팁 박스를 `position: fixed`로 **화면 하단 중앙에 고정**하고
      폭을 `min(300px, 화면폭-32px)`로 제한 — 가로 스크롤을 만들 수가 없습니다. */
.vh-tooltip:focus .vh-tooltiptext,
.vh-tooltip:focus-within .vh-tooltiptext {
    visibility: visible;
    opacity: 1;
}
.vh-tooltip:focus {
    outline: none;
}
@media (max-width: 768px) {
    .vh-tooltip .vh-tooltiptext {
        position: fixed;
        left: 50%;
        right: auto;
        top: auto;
        bottom: 64px;
        transform: translateX(-50%);
        width: min(300px, calc(100vw - 32px));
        max-height: 45vh;
        overflow-y: auto;
    }
    .vh-tooltip .vh-tooltiptext::after {
        display: none;
    }
}

/* 0.1초 가격 비교 박스 (위아래 직관 배치) */
.comparison-box {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 10px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.comparison-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 3px 0;
}
.comparison-row.divider {
    border-bottom: 1px dashed #334155;
    padding-bottom: 6px;
    margin-bottom: 6px;
}
.label-text {
    font-size: 12px;
    color: #94a3b8;
    font-weight: 600;
}
.price-text-curr {
    font-size: 15px;
    font-weight: 800;
    color: #cbd5e1;
}
.price-text-target {
    font-size: 16px;
    font-weight: 800;
    color: #14b8a6;
}
.gap-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    font-weight: 700;
}
.gap-bar-bg {
    height: 6px;
    background: #334155;
    border-radius: 3px;
    overflow: hidden;
    margin-top: 8px;
}
"""


def register() -> None:
    """main.py 에서 ui.run() 호출 전에 한 번만 부릅니다.

    2026-08-16 (Render 첫 배포 실패 대응) — `shared=True`가 없으면 NiceGUI가
    "@ui.page 를 쓰는 중에는 전역 스코프에서 ui.add_css를 호출할 수 없다"며
    RuntimeError로 즉시 죽습니다(런타임 로그로 확인). shared=True 는 "이 CSS를
    모든 페이지에 공통 적용해라"는 뜻으로, 지금 우리가 원하는 동작 그대로입니다.
    """
    ui.add_css(_CSS, shared=True)
