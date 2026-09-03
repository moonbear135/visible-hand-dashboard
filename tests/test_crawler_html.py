# tests/test_crawler_html.py
"""
🧾 크롤러용 정적 HTML 분기 + `/privacy` 정적 전환 — 회귀 테스트 (2026-09-04)

배경: 구글 애드센스가 "가치가 별로 없는 콘텐츠"로 사이트를 반려했습니다(NiceGUI 화면의 최초
HTML 에 본문이 없음 — `tests/test_landing_page.py` 머리말). 공개 데이터 화면 4개
(`/kr`·`/us`·`/dividend`·`/indicator`)는 알려진 크롤러 UA 에게만 **같은 스냅샷 파일을 그 자리에서
읽은 순수 HTML** 을 돌려주고, `/privacy` 는 `/` 처럼 통째로 정적 라우트가 됐습니다
(`web/static_html.py` 머리말).

이 파일이 지키는 것
  ① 봇 판정이 **보수적**이다 — 알려진 크롤러 토큰만 True, 일반 브라우저·curl·None 은 False.
  ② 4개 화면의 크롤러용 HTML 에 `<title>`·`<meta name="description">`·실제 데이터(종목명 등)가
     서버 응답 그 자체에 들어 있고, `<script` 태그가 0개다.
  ③ 스냅샷을 못 읽으면 숫자를 지어내지 않고 "준비 중" 안내만 있다(§0-1).
  ④ 공개 스위치가 꺼진 화면(`/dividend`·`/indicator`)은 크롤러에게도 실사용자와 같은 "준비중"
     문구를 보여준다(봇에게만 다른 내용을 보여주는 클로킹이 아니라는 근거).
  ⑤ 페이지 함수에 봇 UA 요청을 넣으면 NiceGUI 화면을 그리지 않고 `HTMLResponse` 를 **반환**한다
     (NiceGUI 3.16 `page._wrap` 의 `isinstance(result, Response)` 분기가 타는 형태).
     인자 없이 부르면(기존 렌더 스모크 방식) `None` 을 돌려 예전 경로를 탄다.
  ⑥ `/privacy` 응답이 정적 HTML 이고 법률 문구 원문이 그대로 들어 있다.

실행: python -m pytest tests/test_crawler_html.py -v
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from _render_helpers import run_render  # noqa: E402

from web import static_html  # noqa: E402
from web.pages import dividend_page, indicator_page, pegy_page, privacy_page, us_stocks_page  # noqa: E402

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


class _FakeRequest:
    """`is_known_crawler()` 가 보는 건 `request.headers.get('user-agent')` 뿐입니다."""

    def __init__(self, user_agent):
        self.headers = {"user-agent": user_agent}


def _assert_static_document(html: str, canonical_path: str) -> None:
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>" in html
    assert '<meta name="description" content="' in html
    assert f'<link rel="canonical" href="{static_html.SITE_ORIGIN}{canonical_path}">' in html
    assert "<script" not in html
    assert "https://cdn" not in html
    assert 'href="/privacy"' in html


# =============================================================================
# ① 봇 판정
# =============================================================================
def test_known_crawler_tokens_are_detected_and_ordinary_agents_are_not():
    for ua in (
        GOOGLEBOT_UA,
        "Mediapartners-Google",
        "AdsBot-Google (+http://www.google.com/adsbot.html)",
        "Mozilla/5.0 (compatible; Google-InspectionTool/1.0)",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    ):
        assert static_html.is_known_crawler(_FakeRequest(ua)), ua
    for ua in (
        CHROME_UA,
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1",
        "curl/8.0",
        "",
    ):
        assert not static_html.is_known_crawler(_FakeRequest(ua)), ua
    assert static_html.is_known_crawler(None) is False
    # 일반 브라우저 UA 에 흔한 토큰이 목록에 들어가면 실사용자가 정적 페이지로 샙니다.
    for forbidden in ("mozilla", "compatible", "chrome", "safari", "gecko"):
        assert forbidden not in static_html.BOT_UA_TOKENS


def test_crawler_response_carries_vary_and_no_store_headers():
    response = static_html.crawler_response("<!DOCTYPE html><html></html>")
    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert response.headers["vary"] == "User-Agent"
    assert response.headers["cache-control"] == "no-store"


# =============================================================================
# ② 실제 스냅샷으로 만든 크롤러용 HTML (저장소의 data/*.json 이 그대로 입력입니다)
# =============================================================================
def test_kr_crawler_html_carries_real_stock_rows_without_scripts():
    html = run_render(pegy_page.build_crawler_html())
    _assert_static_document(html, "/kr")
    assert pegy_page.CRAWLER_META_DESCRIPTION in html
    assert "마지막 동기화" in html
    assert "<table>" in html and "Forward PEGY" in html
    # 시가총액 1위 종목의 이름·코드가 표에 실제로 있어야 합니다(지어낸 값이 아니라 파일에서 온 값).
    metadata, stocks = run_render(pegy_page.load_kospi200_snapshot())
    top = min((s for s in stocks if s.get("is_visible", True)), key=lambda s: s.get("rank") or 10**9)
    assert f"<td>{top['name']}</td>" in html
    assert f"<td>{top['code']}</td>" in html
    assert str(metadata["last_updated_at"]) in html


def test_us_crawler_html_carries_real_stock_rows_without_scripts():
    html = run_render(us_stocks_page.build_crawler_html())
    _assert_static_document(html, "/us")
    assert us_stocks_page.CRAWLER_META_DESCRIPTION in html
    assert "<table>" in html and "Forward PEGY" in html and "USD" in html
    _metadata, stocks = run_render(us_stocks_page.load_us_snapshot())
    top = min((s for s in stocks if s.get("is_visible", True)), key=lambda s: s.get("rank") or 10**9)
    assert f"<td>{top['symbol']}</td>" in html


def test_dividend_crawler_html_uses_the_same_records_when_enabled(monkeypatch):
    monkeypatch.setattr(dividend_page, "DIVIDEND_ENABLED", True)
    monkeypatch.setattr(dividend_page, "DIVIDEND_MENU_ADMIN_ONLY", False)
    html = run_render(dividend_page.build_crawler_html())
    _assert_static_document(html, "/dividend")
    assert dividend_page.CRAWLER_META_DESCRIPTION in html
    assert "2026년 배당 확정" in html
    # 정직성 고지는 크롤러에게도 그대로(§0-3-13 — 숨기지 않기).
    assert "배당금 받는 날" in html
    assert dividend_page.COMING_SOON_TEXT.split("\n")[0] not in html


def test_indicator_crawler_html_uses_the_same_snapshot_when_enabled(monkeypatch):
    monkeypatch.setattr(indicator_page, "INDICATOR_ENABLED", True)
    monkeypatch.setattr(indicator_page, "INDICATOR_MENU_ADMIN_ONLY", False)
    html = run_render(indicator_page.build_crawler_html())
    _assert_static_document(html, "/indicator")
    assert indicator_page.CRAWLER_META_DESCRIPTION in html
    assert "RSI(14)" in html and "종합판정" in html
    # 강한 경고는 화면과 똑같이 상·하단 두 번.
    assert html.count("미래 주가를 맞히지 않습니다.") == 2


# =============================================================================
# ③ 스냅샷을 못 읽으면 지어내지 않는다 / ④ 스위치가 꺼지면 크롤러도 "준비중"
# =============================================================================
def test_kr_crawler_html_shows_only_an_honest_notice_when_the_snapshot_is_missing(monkeypatch):
    async def _failed():
        return {"last_updated_at": None, "status": "LOAD_FAILED", "load_error": "테스트용 실패"}, []

    monkeypatch.setattr(pegy_page, "load_kospi200_snapshot", _failed)
    html = run_render(pegy_page.build_crawler_html())
    _assert_static_document(html, "/kr")
    assert "테스트용 실패" in html and "데이터 준비 중" in html
    assert "<table>" not in html


def test_us_crawler_html_shows_only_an_honest_notice_when_the_snapshot_is_missing(monkeypatch):
    async def _failed():
        return {"status": "LOAD_FAILED", "load_error": "테스트용 실패"}, []

    monkeypatch.setattr(us_stocks_page, "load_us_snapshot", _failed)
    html = run_render(us_stocks_page.build_crawler_html())
    assert "테스트용 실패" in html and "데이터 준비 중" in html
    assert "<table>" not in html


def test_gated_screens_show_the_same_coming_soon_text_to_crawlers(monkeypatch):
    monkeypatch.setattr(dividend_page, "DIVIDEND_ENABLED", False)
    html = run_render(dividend_page.build_crawler_html())
    _assert_static_document(html, "/dividend")
    assert "아직 준비중입니다" in html and "<table>" not in html

    monkeypatch.setattr(indicator_page, "INDICATOR_ENABLED", False)
    html = run_render(indicator_page.build_crawler_html())
    _assert_static_document(html, "/indicator")
    assert "아직 준비중입니다" in html and "<table>" not in html


def test_gated_screens_stay_closed_to_crawlers_while_admin_only(monkeypatch):
    """크롤러는 로그인할 수 없으므로 2단계(관리자 전용)에서는 비관리자와 같은 "준비중"."""
    monkeypatch.setattr(dividend_page, "DIVIDEND_ENABLED", True)
    monkeypatch.setattr(dividend_page, "DIVIDEND_MENU_ADMIN_ONLY", True)
    assert "아직 준비중입니다" in run_render(dividend_page.build_crawler_html())
    monkeypatch.setattr(indicator_page, "INDICATOR_ENABLED", True)
    monkeypatch.setattr(indicator_page, "INDICATOR_MENU_ADMIN_ONLY", True)
    assert "아직 준비중입니다" in run_render(indicator_page.build_crawler_html())


# =============================================================================
# ⑤ 페이지 함수의 분기 자체 — 봇이면 Response 반환, 아니면 None(예전 경로)
# =============================================================================
def test_page_functions_return_a_response_for_crawlers_and_none_otherwise():
    for module, fn in (
        (pegy_page, pegy_page.pegy_index_page),
        (us_stocks_page, us_stocks_page.us_stocks_index_page),
        (dividend_page, dividend_page.dividend_page),
        (indicator_page, indicator_page.indicator_page),
    ):
        response = run_render(fn(request=_FakeRequest(GOOGLEBOT_UA)))
        assert response is not None, module.__name__
        assert response.status_code == 200 and response.media_type == "text/html", module.__name__
        assert b"<script" not in response.body, module.__name__
        assert response.headers["vary"] == "User-Agent", module.__name__


def test_page_functions_take_an_optional_request_parameter():
    """`request: Request = None` — FastAPI 는 타입 주석으로 주입하고, 테스트는 인자 없이 부릅니다."""
    import inspect
    from fastapi import Request

    for fn in (pegy_page.pegy_index_page, us_stocks_page.us_stocks_index_page,
               dividend_page.dividend_page, indicator_page.indicator_page):
        params = inspect.signature(fn).parameters
        assert "request" in params, fn.__name__
        assert params["request"].annotation is Request, fn.__name__
        assert params["request"].default is None, fn.__name__


def test_every_public_data_page_has_the_crawler_branch():
    """4개 화면 파일이 전부 `is_known_crawler(` 로 분기하고, 다른 `@ui.page` 파일은 건드리지 않았다."""
    pages_dir = REPO_ROOT / "web" / "pages"
    branched = sorted(
        path.name for path in pages_dir.glob("*.py")
        if "is_known_crawler(" in path.read_text(encoding="utf-8")
    )
    assert branched == ["dividend_page.py", "indicator_page.py", "pegy_page.py", "us_stocks_page.py"]


# =============================================================================
# ⑥ `/privacy` 정적 전환
# =============================================================================
def test_privacy_route_returns_static_html_with_the_policy_text():
    response = privacy_page.privacy_page()
    assert response.status_code == 200 and response.media_type == "text/html"
    html = response.body.decode("utf-8")
    assert html == privacy_page.build_privacy_html()
    _assert_static_document(html, "/privacy")
    assert privacy_page.META_DESCRIPTION in html
    assert "<h2>2. 수집하는 개인정보 항목</h2>" in html
    assert "원본 이미지 파일은" in html
    assert privacy_page.CONTACT_EMAIL in html
    assert "이 문서는 초안입니다" in html


def test_privacy_is_no_longer_a_nicegui_page():
    tree = ast.parse((REPO_ROOT / "web" / "pages" / "privacy_page.py").read_text(encoding="utf-8"))
    ui_pages = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "page"
    ]
    assert not ui_pages, "/privacy 가 다시 @ui.page 로 등록되면 크롤러에게 빈 페이지가 됩니다"
    assert "@app.get('/privacy'" in (REPO_ROOT / "web" / "pages" / "privacy_page.py").read_text(encoding="utf-8")


if __name__ == "__main__":
    from _test_discovery import discover_and_run_module_tests

    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")
