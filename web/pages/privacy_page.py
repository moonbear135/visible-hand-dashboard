"""
🔒 개인정보 처리방침 — 언제나 공개인 화면 (URL `/privacy`, 2026-08-25 추가).

🧾 2026-09-04 — **순수 FastAPI 정적 라우트로 전환.** 구글 애드센스가 NiceGUI 화면의 최초 HTML
   에 본문이 없다("가치가 별로 없는 콘텐츠")며 사이트를 반려했고(`landing_page.py` 머리말),
   애드센스 승인 조건인 이 방침 페이지가 크롤러 눈에 빈 페이지였습니다. 이 문서는 데이터와
   무관한 **고정 법률 문구**라 봇 감지 분기조차 필요 없이 `/` 와 같은 `@app.get` 패턴으로
   통째로 정적 HTML 을 돌려줍니다(§0-3-10 — `/ads.txt`·`/` 가 이미 쓰는 패턴). 본문 원문
   (`_BODY_MARKDOWN`)은 한 글자도 바꾸지 않았고, 예전 `ui.markdown` 이 쓰던 것과 **같은
   라이브러리·같은 extras**(`markdown2`, `fenced-code-blocks`·`tables` — 설치본
   `nicegui/elements/markdown.py` 확인)로 HTML 을 만듭니다.

구글 애드센스 승인 조건("사이트에 개인정보/쿠키 처리방침 페이지가 있어야 함")을 채우려고
오너가 명시적으로 요청한 화면입니다("이것도 같이 해줘"). 다른 공개 화면과 달리 **3단계
공개 절차(§0-3-2)를 적용하지 않습니다** — 이 문서는 켜고 끄는 기능이 아니라 항상 켜져
있어야 하는 법적 고지문이라, `*_ENABLED` 스위치 자체가 없습니다.

⚠️ 내용은 **실제로 코드를 뒤져 확인한 사실**만 적었습니다(ENGINEERING_SPEC.md §0-1 —
   추측으로 확인하지 않기). 확인한 근거:
     - `sql/scorecard_schema.sql` : `public.profiles`(email·display_name) ·
       `public.holdings` 테이블 존재 확인
     - `utils/scorecard_ocr.py` 머리말 : "원본 스크린샷 바이트는 이 모듈 안 어디에도
       저장하지 않습니다(디스크/DB 모두)" — OCR 업로드 이미지는 Gemini API로 보내되
       저장하지 않는다는 정확한 문구를 그대로 반영
     - `utils/macro_ai.py` / `utils/indicator_ai.py` : `google.genai` 클라이언트로
       Gemini API 호출 확인
     - 코드 전체 grep(`analytics|gtag|google-analytics`) : 제3자 분석 도구 없음 확인
     - 코드 전체 grep(`회원 탈퇴|계정 삭제|delete_account`) : **자체 삭제 기능 없음**
       확인 — 그래서 이 문서에도 "버튼으로 즉시 삭제"라고 쓰지 않고, 문의 메일로 요청받아
       처리한다고 정직하게 적었습니다.

이 문서는 **초안이며 법률 자문이 아닙니다** — 본문에도 같은 문구를 명시했습니다. 실제
금융·개인정보가 오가는 서비스인 만큼, 오너가 나중에 변호사·법무 전문가 검토를 받는 걸
권장합니다(이 파일 어디에도 "법적으로 완벽하다"고 주장하지 않습니다).
"""

import markdown2
from fastapi.responses import HTMLResponse
from nicegui import app

from web.static_html import SITE_TITLE, render_document

CONTACT_EMAIL = 'redmoon11230@gmail.com'

PAGE_TITLE = '🔒 개인정보 처리방침'

META_DESCRIPTION = (
    f'{SITE_TITLE}(visiblehand.co.kr)의 개인정보 처리방침 — 수집하는 항목(이메일·표시 이름·'
    '보유종목·세션 쿠키), 수집 목적, 처리 위탁(Supabase·Google Gemini API·Render·Google AdSense), '
    '보유 기간, 쿠키·광고, 이용자 권리와 문의처를 안내합니다.'
)

#: `ui.markdown` 의 기본 extras 와 같은 값(설치본 `nicegui/elements/markdown.py::Markdown.default_extras`).
_MARKDOWN_EXTRAS = ('fenced-code-blocks', 'tables')

_BODY_MARKDOWN = f"""
> ⚠️ **이 문서는 초안입니다.** 서비스 운영자가 실제 데이터 처리 방식을 바탕으로 직접
> 작성했지만, 법률 전문가의 검토를 거친 정식 법률 자문 문서는 아닙니다. 궁금한 점이나
> 정정이 필요한 부분은 아래 문의처로 알려주세요.

**최종 수정일: 2026년 8월 25일**

## 1. 이 서비스에 대하여

"잘 보면 보이는 손"(visiblehand.co.kr, 이하 "서비스")은 정식 금융기관이 아닌, 주식
공부를 돕는 개인 프로젝트(보조 도구)입니다. 종목 추천이나 원금 보장을 하지 않으며,
서비스에서 제공하는 모든 데이터는 참고용입니다.

## 2. 수집하는 개인정보 항목

서비스는 다음 정보를 수집합니다.

- **회원가입·로그인 정보**: 이메일 주소, (입력하신 경우) 표시 이름. 로그인은 Supabase
  Auth를 통해 처리됩니다.
- **보유종목(포트폴리오) 정보**: "내 성적표" 등 기능을 이용하며 직접 입력하시거나,
  아래 OCR 기능으로 인식시킨 종목명·수량·매입가 등 보유종목 데이터.
- **업로드하신 증권사 스크린샷 이미지 (OCR 기능 이용 시)**: 보유종목을 자동으로
  인식하기 위해 이미지를 구글 Gemini API로 전송해 분석합니다. **원본 이미지 파일은
  분석이 끝나면 서비스 서버나 데이터베이스 어디에도 저장하지 않습니다.**
- **세션 쿠키**: 로그인 상태를 유지하기 위한 서버 측 세션 쿠키입니다. 광고·추적
  목적이 아니라 로그인 유지 목적으로만 사용합니다.

## 3. 개인정보 수집 목적

- 회원 식별 및 로그인 상태 유지
- 입력하신 보유종목을 바탕으로 한 "내 성적표"·"사장님 보고서" 등 개인 맞춤 화면 제공
- OCR 기능을 통한 보유종목 입력 편의 제공
- 서비스 운영·개선, 문의 응대

## 4. 처리 위탁 및 제3자 제공

서비스는 아래 업체의 인프라·API를 이용해 운영되며, 각 업체는 자체 개인정보처리방침을
따릅니다.

- **Supabase** (회원 인증·데이터베이스): 이메일, 보유종목 등 회원 데이터를 저장하는
  데 이용합니다.
- **Google (Gemini API)**: OCR 이미지 인식, 시황·보조지표 AI 해설 생성에 이용합니다.
  OCR 이미지는 위 2항과 같이 저장되지 않습니다.
- **Render** (웹 호스팅): 서비스 서버를 운영하는 데 이용합니다.
- **Google AdSense** (광고): 아래 6항 참고.

서비스는 위 목적 외에 이용자의 개인정보를 판매하거나 제3자에게 제공하지 않습니다.

## 5. 보유 및 이용 기간

회원 탈퇴나 삭제를 요청하시기 전까지 보관합니다. 서비스에는 아직 자체적인 즉시 삭제
버튼이 없어서, 삭제나 열람·정정을 원하시면 아래 문의처로 이메일을 보내주세요 — 확인
후 처리해 드립니다.

"내 성적표" 공개 동의를 철회하고 싶으신 경우, 로그인 후 `/scorecard/consent`
화면에서 직접 철회하실 수 있습니다(이 경우는 즉시 처리됩니다).

## 6. 쿠키 및 광고 (Google AdSense)

서비스는 Google AdSense를 통해 광고를 게재합니다. Google과 광고 파트너는 이용자에게
관심사 기반 광고를 보여주기 위해 자체 쿠키를 사용할 수 있습니다. 이 쿠키는 서비스가
아니라 Google이 직접 관리하며, 아래 링크에서 광고 개인화를 끄거나 자세한 정책을
확인하실 수 있습니다.

- 광고 개인화 설정: [adssettings.google.com](https://adssettings.google.com)
- Google 광고 관련 개인정보처리방침: [policies.google.com/technologies/ads](https://policies.google.com/technologies/ads)

## 7. 만 14세 미만 아동

서비스는 만 14세 미만 아동을 대상으로 하지 않으며, 아동으로부터 개인정보를 의도적으로
수집하지 않습니다.

## 8. 이용자의 권리

이용자는 언제든지 본인의 개인정보 열람, 정정, 삭제를 요청할 수 있습니다. 아래
문의처로 이메일을 보내주시면 신원을 확인한 뒤 처리해 드립니다.

## 9. 문의처

개인정보 관련 문의, 열람·정정·삭제 요청은 아래 이메일로 보내주세요.

📧 **{CONTACT_EMAIL}**

## 10. 이 방침의 변경

서비스 내용이 바뀌면 이 방침도 함께 업데이트될 수 있습니다. 중요한 변경이 있으면 이
페이지 상단의 "최종 수정일"을 갱신합니다.
"""


def build_privacy_html() -> str:
    """완성된 HTML 문서 한 장. 순수 함수 — 테스트가 직접 부릅니다."""
    body_html = markdown2.markdown(_BODY_MARKDOWN, extras=list(_MARKDOWN_EXTRAS))
    return render_document(
        title=f'{PAGE_TITLE} — {SITE_TITLE}',
        description=META_DESCRIPTION,
        canonical_path='/privacy',
        main_html=f'<h1>{PAGE_TITLE}</h1>\n{body_html}',
    )


@app.get('/privacy', include_in_schema=False)
def privacy_page() -> HTMLResponse:
    """개인정보 처리방침. 로그인 불필요 — 누구나(구글 크롤러 포함) 볼 수 있어야 합니다.

    JS 없이 서버가 완성된 HTML 을 그대로 돌려줍니다(NiceGUI `@ui.page` 아님 — `/` 와 같은
    패턴). 봇 감지도 하지 않습니다: 누가 오든 같은 바이트입니다.
    """
    return HTMLResponse(build_privacy_html())
