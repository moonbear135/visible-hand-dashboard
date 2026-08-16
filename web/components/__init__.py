"""
공용 화면 조각 (NiceGUI 이전, 2단계에서 신설).

ENGINEERING_SPEC.md §0-3-10 (코드 단순성 · 중복 금지) 에 따라,
`pegy`(2단계)와 `us_stocks`(3단계)가 **같이 쓰는 조각만** 여기에 둡니다.
한 화면에서만 쓰는 로직은 그 화면 파일(`web/pages/*.py`)에 남깁니다.

구성 (파일을 잘게 쪼개지 않습니다 — §0-3-10 "파일 하나로 될 일을 여러 파일에 나누지 않기")
  - `html.py`     : HTML **문자열**을 만드는 순수 함수 (이스케이프·툴팁·배지)
  - `widgets.py`  : NiceGUI **위젯**을 그리는 함수 (배너·메트릭 카드·다운로드·페이지네이션)
  - `stock_download.py` : 위 둘을 조합한 "종목별 데이터 다운로드" 도구
                          (pegy·us_stocks 두 화면이 동일하게 사용)
"""

from web.components.html import (  # noqa: F401
    compact,
    esc,
    tooltip,
    warn_badge,
)
from web.components.stock_download import render_stock_download_tool  # noqa: F401
from web.components.widgets import (  # noqa: F401
    banner,
    download_button,
    error_banner,
    info_banner,
    metric_card,
    pager,
    scroll_to_top,
    warning_banner,
)
