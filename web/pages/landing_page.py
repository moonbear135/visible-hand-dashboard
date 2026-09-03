"""
🏠 정적 소개 페이지 — 도메인 루트 `/` (2026-09-04 추가, 구글 애드센스 심사 대응).

왜 이 파일이 있나 (실측으로 확인한 사실 — §0-1)
-------------------------------------------------------------------------------
구글 애드센스 사이트 심사에서 "가치가 별로 없는 콘텐츠"로 반려됐습니다. 원인은 NiceGUI
화면(`@ui.page`)의 구조 자체입니다 — 서버가 처음 내려주는 HTML `<body>` 에는 본문 텍스트가
전혀 없고(`socket.io` 스크립트 태그뿐), PEGY 표·카드는 브라우저가 웹소켓으로 서버에 붙은
**뒤에야** 그려집니다. `<meta name="description">` 도 없었습니다. 즉 크롤러 눈에는 `/` 가
빈 페이지였습니다.

그래서 `/` 를 **JS 없이도 완성된 HTML 을 그대로 돌려주는 순수 FastAPI 라우트**로 바꿨습니다.
기존 한국 주식 PEGY 화면(`pegy_page.py`)은 미국판 `/us` 와 짝을 이루는 `/kr` 로 옮겼고,
이 소개 페이지의 "대시보드 보기" 버튼이 거기로 연결됩니다.

어떻게 만들었나
-------------------------------------------------------------------------------
- `@app.get('/')` — `main.py` 의 `/ads.txt`·`/healthz` 가 이미 쓰는 **같은 패턴**입니다
  (§0-3-10 — 새 구조 발명 금지). NiceGUI 3.x 는 `ui.run(root=...)` 을 안 주면 `/` 에 아무
  페이지도 등록하지 않으므로(설치본 `nicegui/nicegui.py` 확인) 충돌이 없습니다.
- 템플릿 엔진은 이 저장소에 없으므로 들이지 않고, 아래 상수 문자열 + 아주 작은 f-string 으로
  조립합니다. 외부 CDN·스크립트 의존 0 — `<style>` 한 블록이 전부입니다.
- 소개 문구는 `ENGINEERING_SPEC.md` §0(프로젝트 개요)·§5(PEGY 수식·배점), `PROJECT_STATUS.md`
  §0-3(화면별 공개 상태), 각 화면 파일의 머리말에서 **확인한 사실만** 적었습니다. 화면에
  이미 걸려 있는 학습용 안내·투자 주의 문구(`web/components/html.py`, `pegy_page.py`)와
  같은 취지의 문장을 그대로 씁니다 — 이 페이지가 서비스를 실제보다 부풀리면 §0-1 위반입니다.
- 링크 목록에서 3단계 공개 스위치(`*_ENABLED`)가 달린 화면은 **켜져 있을 때만** 링크를
  그립니다. 판정은 `web/layout.py` 의 값을 그대로 읽습니다(같은 스위치를 두 번 정의하지
  않음 — §0-3-10). 꺼져 있으면 눌러 봐야 "준비중" 화면이라 소개 페이지에 광고할 이유가 없습니다.

§0-3-8 관점 — 이 페이지는 사용자 데이터를 한 글자도 다루지 않습니다(로그인 상태조차 보지
않고, 접속자 누구에게나 같은 바이트를 돌려줍니다). 모듈 전역은 상수 문자열·튜플뿐입니다.
"""

from fastapi.responses import HTMLResponse
from nicegui import app

from web import layout as _layout

# 브랜드 표기는 `main.py` 의 `ui.run(title='잘 보면 보이는 손', favicon='💡')` 와 같은 값입니다.
SITE_TITLE = '잘 보면 보이는 손'
SITE_TAGLINE = '사실 이 가격이에요 — 코스피·코스닥·미국 주식 PEGY 밸류에이션'

#: 한국 주식 PEGY 대시보드(구 `/`)가 옮겨간 경로. `pegy_page.py` 의 데코레이터와 **같은
#: 값**이어야 합니다(`tests/test_landing_page.py` 가 둘을 대조합니다).
DASHBOARD_PATH = '/kr'

META_DESCRIPTION = (
    '코스피+코스닥 통합 시가총액 상위 500종목과 미국(나스닥·뉴욕) 시가총액 상위 종목의 '
    'Trailing·Forward PEGY 밸류에이션과 100점 만점 퀀트 종합점수를 매일 장마감 후 공개 '
    '재무·시세 데이터로 자동 계산해 보여주는 주식 공부용 보조 도구입니다. '
    '종목 추천이 아니며 모든 수치는 참고용입니다.'
)

# 파비콘은 NiceGUI 가 `ui.run(favicon='💡')` 값으로 `/favicon.ico` 에 이미 내주는 것(실측:
# `image/svg+xml`, 💡 글자 SVG)을 그대로 씁니다 — 같은 아이콘을 여기서 다시 만들지 않습니다(§0-3-10).
_FAVICON_HREF = '/favicon.ico'

_CSS = """
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
main { max-width: 860px; margin: 0 auto; padding: 28px 20px 40px; }
section { margin-bottom: 30px; }
h2 { font-size: 21px; margin: 0 0 10px; color: #b45309; letter-spacing: -0.3px; }
p { margin: 0 0 12px; }
ul { margin: 0 0 12px; padding-left: 22px; }
li { margin-bottom: 6px; }
table { border-collapse: collapse; width: 100%; font-size: 15px; margin-bottom: 12px; }
th, td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #f1f5f9; }
.notice { border: 2px solid #ef4444; background: #fff1f2; border-radius: 12px; padding: 14px 18px;
          color: #7f1d1d; font-weight: 600; }
.learn { border: 2px solid #475569; background: #f1f5f9; border-radius: 12px; padding: 14px 18px;
         color: #1e293b; font-weight: 600; }
.note { font-size: 14px; color: #475569; }
footer { text-align: center; font-size: 13px; color: #64748b; padding: 18px 20px 30px; }
footer a { color: #64748b; }
@media (max-width: 600px) { header h1 { font-size: 27px; } .cta { display: block; margin: 8px 0 0; } }
"""


def _screen_links() -> str:
    """지금 실제로 열려 있는 공개 화면만 `<li>` 로 나열합니다.

    항상 켜져 있는 화면(`/kr`·`/us`·`/scorecard`·`/report`·`/privacy`)은 고정이고, 3단계
    공개 스위치가 달린 화면은 `web/layout.py` 의 판정값을 그대로 따릅니다. 관리자 전용
    화면(`/admin*`)은 공개 소개 페이지에 광고하지 않습니다(§0-3-9 — 공격면 광고 금지).
    """
    rows = [
        (DASHBOARD_PATH, '🇰🇷 한국 주식은 이가격이에요',
         '코스피+코스닥 통합 시가총액 상위 500종목의 Trailing/Forward PEGY·목표주가·퀀트 종합점수 카드. '
         '로그인 없이 볼 수 있습니다.'),
        ('/us', '🇺🇸 미국 주식은 이가격이에요',
         '미국(나스닥·뉴욕) 시가총액 상위 종목을 같은 방법으로 계산한 화면. 모든 금액은 미국 달러(USD) 표기입니다.'),
    ]
    if _layout.DIVIDEND_ENABLED and not _layout.DIVIDEND_MENU_ADMIN_ONLY:
        rows.append(('/dividend', '💰 투자 감사합니다! (한국 배당 달력)',
                     'DART 정기보고서·KIND 연간 집계를 바탕으로 한 한국 상장사 배당 캘린더.'))
    if _layout.DIVIDEND_US_ENABLED and not _layout.DIVIDEND_US_MENU_ADMIN_ONLY:
        rows.append(('/dividend/us', '🇺🇸 미국 배당 달력',
                     '미국 상장사 배당 캘린더(한국 배당 달력의 미국판).'))
    if _layout.INDICATOR_ENABLED and not _layout.INDICATOR_MENU_ADMIN_ONLY:
        rows.append(('/indicator', '🙏 여기서부터는 신앙입니다 (보조지표)',
                     'RSI·MACD·볼린저밴드 세 지표의 원값과 결정론적 판정을 종목별로 조회합니다.'))
    rows.append(('/scorecard', '📊 내 성적표 (로그인 필요)',
                 '내 보유 종목을 직접 입력하거나 증권사 화면 캡처로 인식시켜 손익·비중을 밸류에이션과 대조합니다.'))
    rows.append(('/report', '📈 사장님 보고서 (로그인 필요)',
                 '매일 쌓인 스냅샷으로 내 포트폴리오의 일간~연간 리포트를 봅니다.'))
    if _layout.DUEL_ENABLED and not _layout.DUEL_MENU_ADMIN_ONLY:
        rows.append(('/duel', '⚔️ 결투다! (로그인 필요)',
                     '가상 모의투자 계좌로 나 자신과 겨루는 연습 공간(원화·달러).'))
    return '\n'.join(
        f'<li><a href="{path}"><b>{label}</b></a> — {desc}</li>' for path, label, desc in rows
    )


def build_landing_html() -> str:
    """완성된 HTML 문서 한 장을 돌려줍니다. 순수 함수 — 테스트가 직접 부릅니다."""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{SITE_TITLE} — {SITE_TAGLINE}</title>
<meta name="description" content="{META_DESCRIPTION}">
<link rel="canonical" href="https://visiblehand.co.kr/">
<link rel="icon" href="{_FAVICON_HREF}">
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>💡 {SITE_TITLE}</h1>
  <p class="tagline">{SITE_TAGLINE}</p>
  <a class="cta primary" href="{DASHBOARD_PATH}">🇰🇷 한국 주식 대시보드 보기</a>
  <a class="cta secondary" href="/us">🇺🇸 미국 주식 대시보드 보기</a>
</header>
<main>
<section>
  <h2>이 서비스는 무엇인가요?</h2>
  <p>"잘 보면 보이는 손"은 정식 금융기관의 서비스가 아니라, 주식 초보자가 <b>밸류에이션(이 회사가 지금 싼지 비싼지)</b>을
  직관적으로 이해하도록 돕는 <b>개인 학습용 보조 도구</b>입니다. 코스피+코스닥 통합 시가총액 상위 500개 종목과
  미국(나스닥·뉴욕) 시가총액 상위 종목에 대해, 공개된 재무제표와 시장 데이터를 바탕으로
  <b>PEGY 밸류에이션</b>과 <b>100점 만점 퀀트 종합점수</b>를 매일 장마감 후 자동으로 계산해 카드 형태로 보여줍니다.</p>
  <p>실시간 시세 서비스가 아닙니다. 모든 화면은 <b>장마감 뒤 확정된 후행 데이터</b>만 다루며, 각 화면 상단에
  "언제 수집된 데이터인지"를 그대로 표시합니다.</p>
</section>

<section>
  <h2>PEGY 밸류에이션이란?</h2>
  <p>PER(주가수익비율)만 보면 성장 속도가 다른 회사를 같은 잣대로 비교하게 됩니다. PEG 는 PER 을 이익 성장률로 나눠
  성장을 감안하고, <b>PEGY 는 여기에 배당·자사주 매입 같은 주주환원율까지 더해 나눈 값</b>입니다.</p>
  <ul>
    <li><b>PEGY = PER ÷ (이익 성장률 + 주주환원율)</b> — 값이 <b>낮을수록</b> 성장·환원 대비 주가가 싸다고 읽습니다.</li>
    <li><b>Trailing PEGY</b>는 이미 확정된 최근 4개 분기 실적 기준, <b>Forward PEGY</b>는 증권가 추정치(예상 실적) 기준입니다.
    두 값을 나란히 놓고 "과거로 보면 어떤지, 기대치로 보면 어떤지"를 함께 봅니다.</li>
    <li>Forward 계산의 성장률에는 상한(성장률 35%p·주주환원 10%p·합계 40%p)을 두어, 일회성 급성장이 목표주가를 폭발시키지 않게 합니다.
    목표주가 역시 현재가의 2.5배를 넘지 않도록 제한합니다.</li>
  </ul>
  <p>종목마다 <b>퀀트 종합점수</b>도 함께 계산합니다. 배점은 다음과 같습니다.</p>
  <table>
    <tr><th>영역</th><th>배점</th><th>설명</th></tr>
    <tr><td>PEGY 밸류에이션</td><td>최대 35점</td><td>Forward PEGY 가 낮을수록 고득점</td></tr>
    <tr><td>자본효율성 (ROE/ROIC)</td><td>최대 30점</td><td>ROE·ROIC 가 높을수록 고득점</td></tr>
    <tr><td>주주환원율</td><td>최대 20점</td><td>배당 + 자사주 매입 수익률</td></tr>
    <tr><td>Trailing 안정성</td><td>최대 10점</td><td>확정 실적 기준 ROE 의 안정성</td></tr>
    <tr><td>변동성 보정</td><td>최대 5점</td><td>주가 변동성이 정상 범위면 만점</td></tr>
  </table>
  <p class="note">만점은 종목마다 다릅니다 — 수집하지 못한 지표는 점수를 지어내지 않고 배점에서 제외하므로, 각 카드에
  "획득점수 / 그 종목의 만점 (달성률%)"로 표기됩니다.</p>
</section>

<section>
  <h2>어떤 화면이 있나요?</h2>
  <ul>
{_screen_links()}
  </ul>
</section>

<section>
  <h2>데이터는 어디서 오고, 어떻게 검증하나요?</h2>
  <ul>
    <li>한국 주식은 네이버 증권, 미국 주식은 stockanalysis.com 의 공개 페이지에서 장마감 후 자동 수집합니다(GitHub Actions, 평일 매일). 프리마켓·애프터마켓 시세는 쓰지 않고 장마감 종가만 씁니다.</li>
    <li>수집한 값은 3단계 검증 파이프라인(원본↔가공 데이터 1:1 대조 → 단일 출처 정합성 검사(PER ≈ 주가÷EPS) → 출처 간 교차 검증)을 거칩니다. 검증에 실패한 지표는
    화면에서 "측정 불가"로 표시하고, 그 종목의 점수 배점에서 제외합니다.</li>
    <li><b>없는 값은 지어내지 않습니다.</b> 적자 기업처럼 PER 을 계산할 수 없는 경우, 평균값이나 기본값으로 메우지 않고
    "계산 불가"라고 그대로 보여줍니다.</li>
    <li>스냅샷을 아예 불러오지 못하면 숫자를 하나도 그리지 않고 빨간 안내만 표시합니다.</li>
  </ul>
</section>

<section>
  <div class="learn">
    📘 [학습용 보조 도구 안내] '잘 보면 보이는 손'은 정식 금융기관의 서비스가 아니며, 주식 초보자의 직관적인
    밸류에이션 이해를 돕는 참고용 프로젝트입니다. 본 서비스는 종목 추천이나 원금 보장을 하지 않습니다.
  </div>
</section>

<section>
  <div class="notice">
    🚨 [투자 주의 경고 및 AI 분석 안내] 이 사이트의 수치 및 분석 결과는 공시된 재무제표와 시장 데이터를 기반으로
    퀀트 알고리즘이 자동 계산한 단순 참고용 정보입니다. 특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며,
    데이터의 정확성이나 완벽성을 보장하지 않습니다. 모든 투자 결정과 그에 따른 결과(법적·경제적 책임)는 전적으로
    투자자 본인에게 있습니다.
  </div>
</section>

<section style="text-align:center">
  <a class="cta primary" href="{DASHBOARD_PATH}">🇰🇷 한국 주식 대시보드 시작하기</a>
  <a class="cta secondary" href="/us" style="color:#1e293b;border-color:#94a3b8">🇺🇸 미국 주식 보기</a>
</section>
</main>
<footer>
  <a href="/privacy">개인정보 처리방침</a> · {SITE_TITLE} (visiblehand.co.kr) — 개인 학습용 프로젝트
</footer>
</body>
</html>
"""


@app.get('/', include_in_schema=False)
def landing_page() -> HTMLResponse:
    """도메인 루트. JS 없이 서버가 완성된 HTML 을 그대로 돌려줍니다(NiceGUI `@ui.page` 아님)."""
    return HTMLResponse(build_landing_html())
