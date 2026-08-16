"""
HTML 문자열 조립 헬퍼 (순수 함수 — NiceGUI 를 import 하지 않습니다).

`views/pegy_view.py` / `views/us_stocks_view.py` 는 화면의 90% 이상이 f-string 으로
조립한 거대 HTML 문자열입니다(계획서 §1-1). NiceGUI 에서는 그걸 `ui.html(...)` 에
그대로 넣으면 되므로, 이식에서 실제로 손이 가는 건 **문자열을 만드는 부분**뿐입니다.
그 중 두 화면이 공통으로 쓰는 조각만 여기에 모읍니다.

⚠️ 보안 (ENGINEERING_SPEC.md §0-3-9 XSS):
   `ui.html(...)` 로 그리는 문자열에 **우리가 만들지 않은 값**(사용자 입력, 그리고
   네이버에서 크롤링해 온 종목명·배지·사유 문구 등 외부 문자열)이 섞이는 자리는
   반드시 `esc()` 를 거칩니다. 기존 Streamlit 코드는 크롤링 값을 그대로 넣고 있었는데,
   NiceGUI 에서도 같은 실수를 반복하지 않도록 이식하면서 전부 `esc()` 를 붙였습니다.
   (정상적인 한글 종목명은 이스케이프해도 화면 출력이 100% 동일합니다.)
"""

import html as _html

# ── 앰버(주의) 배지 공통 스타일 ────────────────────────────────────────────
# pegy 카드의 "🧮 계산값", "⚡ 추정치 변동 큼", "⚠️ 고성장 추정 보수반영",
# "🧮 상한 적용값" 네 곳이 글자만 다르고 스타일이 완전히 동일했습니다(원본 4중 복붙).
_WARN_BADGE_STYLE = (
    'font-size: 10px; font-weight: 800; color: #fbbf24; background-color: #78350f; '
    'border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; vertical-align: middle;'
)


def esc(value, fallback: str = '') -> str:
    """HTML 특수문자 이스케이프. None 이면 `fallback` 을 그대로 돌려줍니다.

    따옴표까지 이스케이프하므로 `style="...{값}..."` 같은 **속성 안**에 넣어도 안전합니다.
    """
    if value is None:
        return fallback
    return _html.escape(str(value), quote=True)


def compact(markup: str) -> str:
    """줄마다 앞뒤 공백을 없애고 빈 줄을 제거합니다.

    기존 Streamlit 코드가 `st.markdown(...)` 직전에 항상 하던 처리와 동일합니다
    (들여쓰기가 4칸 이상이면 마크다운이 코드블록으로 오인하는 문제 회피). NiceGUI 의
    `ui.html()` 은 마크다운 파서를 거치지 않지만, **출력 HTML을 기존과 동일하게 유지**
    하려고 같은 처리를 그대로 씁니다.
    """
    return '\n'.join(line.strip() for line in markup.split('\n') if line.strip())


def tooltip(label_html: str, body_html: str, *,
            trigger_style: str = '', body_style: str = '') -> str:
    """ℹ️ 툴팁 span 한 개를 만듭니다.

    - `label_html` / `body_html` 은 **우리가 작성한 HTML**입니다(<b>, <br> 포함 가능).
      외부에서 온 값을 넣을 때는 호출하는 쪽에서 `esc()` 를 씌워 넘기세요.
    - `tabindex="0"` 은 #124→#125 에서 확정된 모바일 대응(탭하면 포커스 → 툴팁 표시)이라
      반드시 유지합니다.
    - 클래스명이 `q-tooltip` 이 아니라 `vh-tooltip` 인 이유는 `web/theme.py` 주석 참고
      (Quasar 내장 클래스명과의 충돌 회피).
    """
    trigger_attr = f' style="{trigger_style}"' if trigger_style else ''
    body_attr = f' style="{body_style}"' if body_style else ''
    return (
        f'<span class="vh-tooltip" tabindex="0"{trigger_attr}>{label_html}'
        f'<span class="vh-tooltiptext"{body_attr}>{body_html}</span></span>'
    )


def warn_badge(label_html: str, body_html: str) -> str:
    """앰버색 주의 배지(+툴팁). 앞에 공백 한 칸이 붙습니다(기존 출력과 동일).

    "🧮 계산값" 처럼 **값의 출처가 실측이 아님을 반드시 표시해야 하는 자리**
    (ENGINEERING_SPEC.md §0-1 예시2-보충)에 씁니다.
    """
    return ' ' + tooltip(label_html, body_html, trigger_style=_WARN_BADGE_STYLE)
