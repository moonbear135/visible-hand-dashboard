"""
🧾 JS 없이 완성된 HTML 을 돌려주는 자리들의 **공용 조각** (2026-09-04 신설).

누가 쓰나
-------------------------------------------------------------------------------
- `web/pages/landing_page.py` — 도메인 루트 `/` (항상 정적).
- `web/pages/privacy_page.py` — `/privacy` (항상 정적. 데이터와 무관한 고정 법률 문구라
  봇 감지 없이 통째로 정적 라우트).
- 공개 데이터 화면 4개(`/kr`·`/us`·`/dividend`·`/indicator`) — **알려진 크롤러가 왔을 때만**
  `@ui.page` 함수 맨 앞에서 그 화면이 읽는 것과 같은 JSON 스냅샷을 그 자리에서 읽어 순수
  HTML 로 응답합니다. 일반 접속자는 예전 그대로 NiceGUI 인터랙티브 화면을 받습니다.

왜 이런 분기가 필요한가 (실측 — §0-1)
-------------------------------------------------------------------------------
구글 애드센스가 "가치가 별로 없는 콘텐츠"로 사이트를 반려했습니다. NiceGUI `@ui.page` 가
처음 내려주는 HTML `<body>` 에는 본문 텍스트가 없고(socket.io 스크립트뿐), 표·카드는
웹소켓 연결 뒤에야 그려지기 때문입니다(`landing_page.py` 머리말). 이 4개 화면은 실시간
시세가 아니라 **수집기가 하루 1~2번 갱신하는 배치 스냅샷**을 그리는 것뿐이라, 요청 시점의
그 파일을 그대로 서버에서 HTML 로 펼쳐 보여줘도 실사용자가 보는 것과 같은 데이터입니다 —
봇에게 다른 내용을 보여주는 클로킹이 아니라 **같은 데이터를 다른 포장(JS 없음)** 으로
주는 것입니다. 그래서 미리 만들어 저장해 두지 않고, 요청마다 그 순간의 스냅샷을 읽습니다.

어떻게 분기하나 (NiceGUI 3.16.0 설치본을 직접 읽고 로컬 기동 + curl 로 확인)
-------------------------------------------------------------------------------
`nicegui/page.py::page._wrap.decorated` 는 페이지 함수의 반환값이 `fastapi.Response` 이면
NiceGUI 화면을 조립하지 않고 그 응답을 그대로 돌려줍니다
(`if isinstance(result, Response): return result`). 페이지 함수 시그니처에 `request: Request`
가 있으면 FastAPI 가 요청 객체를 주입합니다(`page._wrap` 이 없으면 스스로 끼워 넣는 것과 같은
매개변수). NiceGUI 자신도 같은 패키지(`nicegui/client.py::AI_AGENT_TOKENS`)에서 User-Agent 를
보고 AI 에이전트에게는 마크다운을 돌려주므로, "UA 를 보고 응답 형식을 바꾸는 것"은 이
프레임워크가 이미 하는 일입니다.

⚠️ 페이지 함수의 `request` 매개변수에 기본값 `None` 을 두는 이유 — 테스트가 페이지 함수를
   인자 없이 직접 부릅니다(`tests/test_pegy_page.py` 등 렌더 스모크). `None` 이면 봇이
   아닌 것으로 판정돼 예전 경로를 그대로 탑니다. FastAPI 는 매개변수의 **타입 주석**
   (`Request`)만 보고 주입하므로 기본값이 있어도 실제 요청에서는 항상 채워집니다
   (로컬 실측: Googlebot UA → 정적 HTML, 일반 UA → NiceGUI 셸).

§0-3-8 관점 — 이 모듈은 사용자 데이터를 한 글자도 다루지 않습니다. 모듈 전역은 상수
문자열·튜플뿐이고, 크롤러 응답은 모든 접속자에게 동일한 읽기 전용 시장 데이터만 담습니다.
"""

from fastapi.responses import HTMLResponse
from starlette.background import BackgroundTask

from web.components.html import esc

# 브랜드 표기는 `main.py` 의 `ui.run(title='잘 보면 보이는 손', favicon='💡')` 와 같은 값입니다.
SITE_TITLE = '잘 보면 보이는 손'
SITE_ORIGIN = 'https://visiblehand.co.kr'

# 파비콘은 NiceGUI 가 `ui.run(favicon='💡')` 값으로 `/favicon.ico` 에 이미 내주는 것(실측:
# `image/svg+xml`, 💡 글자 SVG)을 그대로 씁니다 — 같은 아이콘을 여기서 다시 만들지 않습니다(§0-3-10).
FAVICON_HREF = '/favicon.ico'

#: 알려진 크롤러 User-Agent 토큰 (소문자 부분일치). **보수적으로** 잡습니다 — 일반 브라우저
#: UA 에 절대 들어가지 않는 문자열만 올려서, 실사용자가 정적 페이지로 새는 일이 없게 합니다.
#:   googlebot            — 구글 검색 크롤러 (Googlebot/2.1, Googlebot-Image 등 전부 포함)
#:   mediapartners-google — 애드센스 크롤러 (광고 게재 전 페이지 내용 확인 — 이번 반려의 당사자)
#:   adsbot-google        — 구글 애즈 랜딩 페이지 품질 크롤러
#:   google-inspectiontool— 서치 콘솔 "URL 검사" 실시간 테스트
#:   storebot-google      — 구글 스토어 봇
#:   googleother          — 구글의 기타 R&D 크롤러
#:   bingbot              — 빙 검색 크롤러
#: `Mozilla/5.0` 같은 일반 토큰이나 `compatible` 은 실사용자 UA 에도 있으므로 절대 넣지 않습니다.
BOT_UA_TOKENS = (
    'googlebot',
    'mediapartners-google',
    'adsbot-google',
    'google-inspectiontool',
    'storebot-google',
    'googleother',
    'bingbot',
)


def is_known_crawler(request) -> bool:
    """이 요청이 위 목록의 크롤러에서 왔는지. `request` 가 None(테스트 직접 호출)이면 False."""
    if request is None:
        return False
    try:
        user_agent = (request.headers.get('user-agent') or '').lower()
    except Exception:                              # noqa: BLE001 — 헤더 접근 실패 = 봇 아님으로
        return False
    return any(token in user_agent for token in BOT_UA_TOKENS)


def crawler_response(html: str) -> HTMLResponse:
    """크롤러에게 돌려줄 응답. `Vary: User-Agent` 로 "UA 에 따라 다른 바이트" 임을 캐시에
    알리고, NiceGUI 응답과 같은 `Cache-Control: no-store` 를 답니다.

    `@ui.page` 안에서 조기 반환할 때 NiceGUI 는 이 요청용 `Client` 객체를 이미 만들어 둔
    상태입니다(`page._wrap`). 그대로 두어도 60초 뒤 `Client.prune_instances` 가 지우지만,
    크롤러는 짧은 시간에 여러 URL 을 훑으므로 NiceGUI 자신이 마크다운 응답에서 하는 방식
    (`client.build_response` 의 `BackgroundTask(self.delete)`)과 같게 응답 직후 바로 지웁니다.
    NiceGUI 컨텍스트 밖(테스트 직접 호출·`/privacy` 같은 순수 라우트)에서는 지울 클라이언트가
    없으므로 그냥 응답만 돌려줍니다.
    """
    background = None
    try:
        # ⚠️ `nicegui.context.slot_stack` 이 아니라 `Slot.get_stack()` 을 직접 봅니다 — 전자는
        #    스택이 비어 있으면 "유사 클라이언트"를 만들어 `core.script_mode` 를 켜는 부작용이
        #    있어(설치본 `nicegui/context.py`), 테스트 프로세스에서 그 부작용을 내면 안 됩니다.
        from nicegui.slot import Slot              # noqa: PLC0415 — nicegui 없이도 import 되게
        stack = Slot.get_stack()
        if stack:
            client = stack[-1].parent.client
            # `client.request` 는 요청 없이 만들어진 클라이언트에서 RuntimeError 를 냅니다.
            client.request                         # noqa: B018 — 접근 자체가 검사입니다
            background = BackgroundTask(client.delete)
    except Exception:                              # noqa: BLE001 — 슬롯/요청 컨텍스트가 없으면 생략
        background = None
    return HTMLResponse(
        html,
        headers={'Cache-Control': 'no-store', 'Vary': 'User-Agent'},
        background=background,
    )


# =============================================================================
# 문서 뼈대 — 외부 CDN·스크립트 의존 0. `<style>` 한 블록이 전부입니다.
# =============================================================================
CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f8fafc; color: #0f172a;
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
                    "Noto Sans KR", "Malgun Gothic", sans-serif; line-height: 1.65; }
a { color: #0369a1; }
header { background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); color: #fff;
         padding: 40px 20px 36px; text-align: center; }
header h1 { margin: 0 0 8px; font-size: 34px; font-weight: 800; letter-spacing: -0.5px; }
header p.tagline { margin: 0 0 22px; font-size: 17px; color: #cbd5e1; font-weight: 600; }
.cta { display: inline-block; margin: 6px 6px 0; padding: 12px 22px; border-radius: 10px;
       font-weight: 800; font-size: 16px; text-decoration: none; }
.cta.primary { background: #f59e0b; color: #1e293b; }
.cta.secondary { background: transparent; color: #e2e8f0; border: 1.5px solid #64748b; }
main { max-width: 960px; margin: 0 auto; padding: 28px 20px 40px; }
section { margin-bottom: 30px; }
h1 { font-size: 30px; margin: 0 0 12px; letter-spacing: -0.5px; }
h2 { font-size: 21px; margin: 0 0 10px; color: #b45309; letter-spacing: -0.3px; }
h3 { font-size: 17px; margin: 18px 0 8px; }
p { margin: 0 0 12px; }
ul { margin: 0 0 12px; padding-left: 22px; }
li { margin-bottom: 6px; }
blockquote { margin: 0 0 16px; padding: 10px 16px; border-left: 4px solid #f59e0b; background: #fffbeb; }
.table-wrap { overflow-x: auto; margin-bottom: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin-bottom: 12px; }
th, td { border: 1px solid #e2e8f0; padding: 7px 9px; text-align: left; vertical-align: top;
         white-space: nowrap; }
th { background: #f1f5f9; }
.notice { border: 2px solid #ef4444; background: #fff1f2; border-radius: 12px; padding: 14px 18px;
          color: #7f1d1d; font-weight: 600; margin-bottom: 14px; white-space: pre-line; }
.learn { border: 2px solid #475569; background: #f1f5f9; border-radius: 12px; padding: 14px 18px;
         color: #1e293b; font-weight: 600; margin-bottom: 14px; white-space: pre-line; }
.info { border: 1.5px solid #0284c7; background: #f0f9ff; border-radius: 12px; padding: 12px 18px;
        color: #0c4a6e; font-weight: 600; margin-bottom: 14px; white-space: pre-line; }
.warn { border: 1.5px solid #d97706; background: #fffbeb; border-radius: 12px; padding: 12px 18px;
        color: #78350f; font-weight: 600; margin-bottom: 14px; white-space: pre-line; }
.note { font-size: 14px; color: #475569; }
footer { text-align: center; font-size: 13px; color: #64748b; padding: 18px 20px 30px; }
footer a { color: #64748b; }
@media (max-width: 600px) { header h1 { font-size: 27px; } .cta { display: block; margin: 8px 0 0; } }
"""


def render_document(*, title: str, description: str, canonical_path: str,
                    header_html: str = '', main_html: str = '') -> str:
    """완성된 HTML 문서 한 장. `<title>`·`<meta name="description">`·canonical 을 항상 넣습니다.

    :param title: `<title>` 원문(여기서 이스케이프합니다 — 호출부는 평문으로 넘깁니다).
    :param description: `<meta name="description">` 원문(평문).
    :param canonical_path: `/kr` 같은 경로. `SITE_ORIGIN` 을 앞에 붙입니다.
    :param header_html: `<header>` 안에 들어갈 **완성된 HTML**(이스케이프 책임은 호출부).
    :param main_html: `<main>` 안에 들어갈 완성된 HTML.
    """
    header_block = f'<header>\n{header_html}\n</header>' if header_html else ''
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(SITE_ORIGIN + canonical_path)}">
<link rel="icon" href="{FAVICON_HREF}">
<style>{CSS}</style>
</head>
<body>
{header_block}
<main>
{main_html}
</main>
<footer>
  <a href="/">홈</a> · <a href="/privacy">개인정보 처리방침</a> · {SITE_TITLE} (visiblehand.co.kr) — 개인 학습용 프로젝트
</footer>
</body>
</html>
"""


def notice_box(text: str, kind: str = 'notice') -> str:
    """평문 고지 한 덩어리 → `<div class="...">`. 줄바꿈은 CSS `white-space: pre-line` 이 지킵니다.

    :param kind: `notice`(빨강·경고) / `learn`(회색·학습용 안내) / `info`(파랑) / `warn`(호박색).
    """
    return f'<div class="{esc(kind)}">{esc(text)}</div>'


def table_html(headers, rows) -> str:
    """평문 셀 → `<table>`. **모든 셀을 이스케이프**하므로 호출부는 값을 그대로 넘깁니다.

    `web/components/html.py::holdings_table_html` 과 달리 이 표는 JS 없는 문서용이라
    Quasar 클래스 없이 위 CSS 만으로 그려집니다.
    """
    head = ''.join(f'<th>{esc(h)}</th>' for h in headers)
    body = '\n'.join(
        '<tr>' + ''.join(f'<td>{esc(cell)}</td>' for cell in row) + '</tr>' for row in rows
    )
    return f'<div class="table-wrap"><table>\n<tr>{head}</tr>\n{body}\n</table></div>'


def remaining_note(shown: int, total: int, what: str) -> str:
    """"상위 N개만 표로, 나머지는 실제 화면에서" 안내 한 문단. 전부 실었으면 그 사실만 적습니다."""
    if total <= shown:
        return (f'<p class="note">위 표는 {what} {total:,}건 전부입니다. 검색·필터·종목별 상세 카드는 '
                '브라우저(자바스크립트 실행)에서 같은 주소를 열면 볼 수 있습니다.</p>')
    return (f'<p class="note">위 표는 {what} {total:,}건 가운데 상위 {shown:,}건입니다. 나머지 '
            f'{total - shown:,}건과 검색·필터·종목별 상세 카드는 브라우저(자바스크립트 실행)에서 '
            '같은 주소를 열면 볼 수 있습니다.</p>')
