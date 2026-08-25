"""
구글 애드센스(Google AdSense) 배선 — 3단계 공개 절차 (ENGINEERING_SPEC.md §0-3-2 관례,
DUEL_ENABLED 등 다른 모듈과 완전히 같은 방식).

🔴 **이 프로젝트는 "자동 광고(Auto ads)" 스크립트를 절대 쓰지 않습니다.** Auto ads는 구글이
   페이지를 분석해 앵커(화면 하단에 계속 붙어있는 광고)·전면(페이지 전환 때 화면 전체를
   덮는 광고) 같은 포맷까지 자동으로 골라 끼워 넣을 수 있습니다 — 오너가 명시적으로
   금지했습니다("화면 보다가 팝업처럼 나오는 광고는 절대 싫다"). 그래서 여기서는 애드센스
   대시보드에서 직접 만든 **수동 광고 단위(manual ad unit)만**, 아래 정해진 자리에만
   배너 형태로 그립니다. auto ads 스크립트는 이 원칙이 있는 한 추가하지 않습니다.

   🔁 2026-08-25 (같은 날 추가) — 처음엔 "화면 맨 아래 딱 하나"였지만, 오너가 그 자리가
      실제로 뜨는 걸 확인한 뒤 "좌우 사이드도 되면 하고", "카드 목록 사이사이에도 작은
      배너 하나 정도"를 추가로 요청했습니다. 그래서 지금은 자리가 **넷**입니다(맨 아래·
      왼쪽 사이드·오른쪽 사이드·카드 목록 중간). 자리마다 각자의 슬롯ID 환경변수가 따로
      있고, 그 슬롯ID가 비어 있으면 그 자리만 조용히 안 그려집니다 — 그래서 아래 넷 중
      아무거나 순서 상관없이 하나씩 켤 수 있습니다. 다섯 번째 자리를 또 늘릴 때도 이
      파일 하나에서만 늘리세요(§0-3-10).

3단계 절차 (자리 넷 전부 같은 두 값을 공유합니다):
  1단계 (완전 숨김) : ADS_ENABLED=false ← 기본값. <head>에 애드센스 스크립트 자체가
                       안 실리고(구글 쪽에 요청이 전혀 안 나갑니다), 어떤 화면에도
                       광고 자리가 안 그려집니다.
  2단계 (관리자만)  : 서버 환경변수 ADS_ENABLED=true + 아래 ADS_ADMIN_ONLY=True 유지.
                       관리자로 로그인했을 때만 실제 광고가 보여서, 배치·크기·구글 승인
                       상태를 실사용자에게 노출하지 않고 먼저 눈으로 확인할 수 있습니다.
                       **지금 여기입니다 (2026-08-25 기준).**
  3단계 (전체 공개) : 아래 ADS_ADMIN_ONLY 를 False 로 **한 글자만** 바꿉니다. 넷 모두
                       한꺼번에 전체 공개로 바뀝니다(자리별로 따로 못 뒤집습니다 — 자리별
                       공개 시점을 다르게 하고 싶으면 그 자리만 슬롯ID를 비워뒀다가
                       나중에 채우세요).

필요한 환경변수 (Render 대시보드 → Environment):
  - ADS_ENABLED       : "true" 여야 켜짐. 없으면(기본) 전부 꺼짐. (자리 넷 공통)
  - ADS_PUBLISHER_ID  : 구글 애드센스 게시자 ID. "pub-"로 시작하는 형태 그대로 넣으세요
                        (예: "pub-1234567890123456"). ads.txt 발급과 스크립트 태그 양쪽에
                        씁니다. (자리 넷 공통)
  - ADS_SLOT_ID        : 화면 맨 아래 배너의 슬롯 번호(숫자만). 없으면 그 자리만 안 뜸.
  - ADS_SLOT_ID_LEFT   : 왼쪽 사이드 배너의 슬롯 번호. 없으면 그 자리만 안 뜸.
  - ADS_SLOT_ID_RIGHT  : 오른쪽 사이드 배너의 슬롯 번호. 없으면 그 자리만 안 뜸.
  - ADS_SLOT_ID_INFEED : 카드 목록 중간 배너의 슬롯 번호. 없으면 그 자리만 안 뜸.
    (넷 다 애드센스에서 "디스플레이 광고" 단위를 만들 때마다 하나씩 나오는 숫자입니다.
    아직 안 만든 자리는 환경변수를 비워두세요 — 있지도 않은 슬롯 번호를 지어내지
    않습니다, ENGINEERING_SPEC.md §0-1.)
"""

import os

from nicegui import ui

from web.auth import is_admin

ADS_ENABLED = (os.environ.get('ADS_ENABLED') or '').strip().lower() == 'true'

# 2단계(관리자 전용)가 기본값입니다. 구글 승인이 나고 실제 화면에서 광고 위치·크기를
# 관리자 눈으로 먼저 확인한 뒤에만 False 로 바꾸세요. 자리 넷이 이 값 하나를 공유합니다.
ADS_ADMIN_ONLY = True

ADS_PUBLISHER_ID = (os.environ.get('ADS_PUBLISHER_ID') or '').strip()
ADS_SLOT_ID = (os.environ.get('ADS_SLOT_ID') or '').strip()
ADS_SLOT_ID_LEFT = (os.environ.get('ADS_SLOT_ID_LEFT') or '').strip()
ADS_SLOT_ID_RIGHT = (os.environ.get('ADS_SLOT_ID_RIGHT') or '').strip()
ADS_SLOT_ID_INFEED = (os.environ.get('ADS_SLOT_ID_INFEED') or '').strip()


def register_head() -> None:
    """main.py 에서 ui.run() 호출 전에 한 번만 부릅니다 (web.theme.register() 와 같은 자리).

    ADS_ENABLED 가 꺼져 있거나 게시자 ID가 없으면 아무것도 하지 않습니다 — <head>에
    애드센스 로더 스크립트 자체가 안 실리므로, 애드센스 승인 전에는 구글 쪽으로 어떤
    요청도 나가지 않습니다.
    """
    if not (ADS_ENABLED and ADS_PUBLISHER_ID):
        return
    ui.add_head_html(
        '<script async src="https://pagead2.googlesyndication.com/pagead/js/'
        f'adsbygoogle.js?client=ca-{ADS_PUBLISHER_ID}" crossorigin="anonymous"></script>',
        shared=True,
    )


def _ready(slot_id: str) -> bool:
    """이 자리 하나가 실제로 그려질 조건: 공통 스위치(켜짐·게시자ID) + 이 자리 전용
    슬롯ID + (2단계면) 관리자 로그인. 자리 넷이 전부 이 판정 하나를 같이 씁니다."""
    if not (ADS_ENABLED and ADS_PUBLISHER_ID and slot_id):
        return False
    if ADS_ADMIN_ONLY and not is_admin():
        return False
    return True


def _render_unit(slot_id: str) -> None:
    """<ins> 태그 하나 + push 호출 하나를 그립니다. 실제로 화면에 그리는 부분은 자리
    넷이 전부 이 함수 하나로 통일합니다 (같은 실수를 네 군데 복붙해서 반복하지 않기 위함).

    ⚠️ 2026-08-25 장애 교훈 — `ui.html(...)` 안에 `<script>` 태그를 같이 넣으면 NiceGUI가
       "HTML elements must not contain <script> tags" 로 **화면 전체를 500 에러**로
       떨어뜨립니다. 그래서 `<ins>` 태그만 `ui.html()`로 그리고, 광고를 채우는 push
       호출은 반드시 `ui.run_javascript()`로 따로 실행합니다. 이 함수 밖에서 `<ins>`를
       직접 `ui.html()`에 새로 쓰지 마세요 — 다시 같은 사고가 날 수 있습니다.
    """
    ui.html(
        '<ins class="adsbygoogle" style="display:block" '
        f'data-ad-client="ca-{ADS_PUBLISHER_ID}" '
        f'data-ad-slot="{slot_id}" '
        'data-ad-format="auto" '
        'data-full-width-responsive="true"></ins>'
    )
    ui.run_javascript('(adsbygoogle = window.adsbygoogle || []).push({});')


def ad_slot() -> None:
    """화면 맨 아래에 배너 광고 자리 하나를 그립니다.

    ⚠️ `web/layout.py` 의 공통 껍데기 한 곳에서만 부릅니다 — 화면 파일에서 직접 부르지
       마세요. 그래야 "공개된 화면 전부"에 자동으로 적용되고, 광고 자리가 실수로
       여러 개 생기는 일도 없습니다 (ENGINEERING_SPEC.md §0-3-10 공유 컴포넌트 관례와
       같은 이유).
    """
    if not _ready(ADS_SLOT_ID):
        return
    with ui.column().classes('w-full items-center gap-1 mt-4'):
        ui.label('광고').classes('vh-muted')
        _render_unit(ADS_SLOT_ID)


def _ad_rail(slot_id: str) -> None:
    """왼쪽/오른쪽 사이드 배너 자리 하나. 본문이 좁아지는 화면(태블릿 이하)에서는
    본문 폭을 밀어내며 오히려 UX 를 해치니, 충분히 넓은 화면(Tailwind `xl` 이상,
    대략 1280px~)에서만 보이고 그보다 좁으면 아예 숨깁니다."""
    if not _ready(slot_id):
        return
    with ui.column().classes('hidden xl:flex w-40 shrink-0 items-center gap-1 sticky top-4'):
        ui.label('광고').classes('vh-muted text-xs')
        _render_unit(slot_id)


def ad_rail_left() -> None:
    """`web/layout.py` 의 공통 껍데기에서만 부릅니다 — 본문 왼쪽 사이드 배너."""
    _ad_rail(ADS_SLOT_ID_LEFT)


def ad_rail_right() -> None:
    """`web/layout.py` 의 공통 껍데기에서만 부릅니다 — 본문 오른쪽 사이드 배너."""
    _ad_rail(ADS_SLOT_ID_RIGHT)


def ad_infeed() -> None:
    """종목 카드 목록 중간에 끼워 넣는 작은 배너 하나 (오너 요청 2026-08-25 — "너무 큰거
    말고 적당한 사이에 끼어들어가는 작은 크기 같은거 배너같은느낌으로"). 폭을 좁게
    제한해서 카드들 사이에서 안 튀게 합니다.

    ⚠️ 카드 목록이 있는 화면(`pegy_page.py`/`us_stocks_page.py`)의 렌더 루프 안에서
       **한 페이지에 한 번만** 부르세요 — 카드마다 부르면 광고 밀도가 너무 높아져
       애드센스 정책(과도한 광고) 위반 소지가 있습니다.
    """
    if not _ready(ADS_SLOT_ID_INFEED):
        return
    with ui.column().classes('w-full max-w-sm mx-auto items-center gap-1 my-2'):
        ui.label('광고').classes('vh-muted text-xs')
        _render_unit(ADS_SLOT_ID_INFEED)
