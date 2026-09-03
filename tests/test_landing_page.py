# tests/test_landing_page.py
"""
🏠 도메인 루트 `/` 정적 소개 페이지 + 한국 주식 화면 `/kr` 이동 — 회귀 테스트 (2026-09-04)

배경: 구글 애드센스가 사이트를 "가치가 별로 없는 콘텐츠"로 반려했습니다. 실측 원인은
NiceGUI `@ui.page` 의 최초 HTML `<body>` 에 본문 텍스트가 전혀 없다는 것(웹소켓 연결 뒤에야
그려짐)이었고, 그래서 `/` 를 **JS 없이 완성된 HTML 을 돌려주는 순수 FastAPI 라우트**로
바꾸고 한국 주식 PEGY 화면을 `/kr` 로 옮겼습니다(`web/pages/landing_page.py` 머리말).

이 파일이 지키는 것
  ① `/` 응답 HTML 에 `<meta name="description">`·`<title>`·소개 본문이 **서버 응답 그 자체에**
     들어 있다 — 이게 무너지면 애드센스 반려 원인이 그대로 되살아납니다.
  ② `/` 는 외부 스크립트·CDN 에 기대지 않는다(`<script` 태그 0개).
  ③ 소개 페이지의 "대시보드 보기" 링크(`DASHBOARD_PATH`)와 `pegy_page.py` 의 실제
     `@ui.page` 경로가 **같은 값**이다 — 어긋나면 첫 버튼이 404 입니다.
  ④ 사이드바 메뉴(`web/layout.py::_MENU_GROUPS`)도 같은 경로를 가리킨다.
  ⑤ `/` 가 `@ui.page` 로 다시 등록되지 않는다(NiceGUI 화면으로 되돌아가면 ①이 무의미).

실행: python -m pytest tests/test_landing_page.py -v
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

from web.pages import landing_page  # noqa: E402
import web.layout as layout_module  # noqa: E402


def _ui_page_routes(source_path: Path) -> list:
    """파일 안 `@ui.page('<경로>', ...)` 데코레이터의 경로 문자열 목록(AST — 문자열 검색 아님)."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    return [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "page" and node.args
        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
    ]


def test_landing_html_carries_description_title_and_body_text_without_scripts():
    html = landing_page.build_landing_html()
    assert '<meta name="description" content="' in html
    assert landing_page.META_DESCRIPTION in html
    assert f"<title>{landing_page.SITE_TITLE}" in html
    # 소개 본문 — 서버 응답 자체에 실제 문장이 있어야 합니다(크롤러는 JS 를 안 돌립니다).
    assert "PEGY = PER ÷ (이익 성장률 + 주주환원율)" in html
    assert "코스피+코스닥 통합 시가총액 상위 500" in html
    assert "정식 금융기관의 서비스가 아니" in html
    # 외부 스크립트·CDN 의존 0.
    assert "<script" not in html
    assert "https://cdn" not in html
    # 법적 고지 링크(개인정보 처리방침)는 다른 모든 화면처럼 여기서도 보여야 합니다.
    assert 'href="/privacy"' in html


def test_landing_route_returns_html_response_directly():
    """라우트 함수 자체가 HTML 응답을 돌려준다(NiceGUI 클라이언트를 만들지 않음)."""
    response = landing_page.landing_page()
    assert response.status_code == 200
    assert response.media_type == "text/html"
    body = response.body.decode("utf-8")
    assert body == landing_page.build_landing_html()


def test_dashboard_link_matches_the_real_pegy_page_route():
    pegy_routes = _ui_page_routes(REPO_ROOT / "web" / "pages" / "pegy_page.py")
    assert pegy_routes == [landing_page.DASHBOARD_PATH], \
        f"pegy_page.py 의 @ui.page 경로 {pegy_routes} ≠ 소개 페이지 링크 {landing_page.DASHBOARD_PATH}"
    html = landing_page.build_landing_html()
    assert f'href="{landing_page.DASHBOARD_PATH}"' in html
    assert 'href="/us"' in html


def test_sidebar_menu_points_at_the_moved_dashboard_path():
    paths = [path for _, items in layout_module._MENU_GROUPS for path, _, _ in items]
    assert landing_page.DASHBOARD_PATH in paths
    assert "/" not in paths, "사이드바가 아직 옛 '/' 를 가리키고 있습니다"


def test_root_is_not_registered_as_a_nicegui_page_anywhere():
    """`/` 가 다시 `@ui.page('/')` 로 등록되면 정적 소개 페이지와 경로가 겹치고, 애드센스
    반려 원인(최초 HTML 에 본문 없음)이 그대로 되살아납니다."""
    offenders = []
    for path in sorted((REPO_ROOT / "web" / "pages").glob("*.py")):
        if "/" in _ui_page_routes(path):
            offenders.append(path.name)
    assert not offenders, f"@ui.page('/') 가 남아 있는 파일: {offenders}"


def test_main_registers_the_landing_module():
    main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "landing_page" in main_source, "main.py 가 landing_page 를 import 하지 않으면 '/' 라우트가 등록되지 않습니다"


if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests

    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")
