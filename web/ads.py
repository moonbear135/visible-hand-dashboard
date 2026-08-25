"""
구글 애드센스(Google AdSense) 배선 — 3단계 공개 절차 (ENGINEERING_SPEC.md §0-3-2 관례,
DUEL_ENABLED 등 다른 모듈과 완전히 같은 방식).

🔴 **이 프로젝트는 "자동 광고(Auto ads)" 스크립트를 절대 쓰지 않습니다.** Auto ads는 구글이
   페이지를 분석해 앵커(화면 하단에 계속 붙어있는 광고)·전면(페이지 전환 때 화면 전체를
   덮는 광고) 같은 포맷까지 자동으로 골라 끼워 넣을 수 있습니다 — 오너가 명시적으로
   금지했습니다("화면 보다가 팝업처럼 나오는 광고는 절대 싫다"). 그래서 여기서는 애드센스
   대시보드에서 직접 만든 **수동 광고 단위(manual ad unit) 딱 하나만**, 화면 맨 아래
   고정된 자리 하나에만 배너 형태로 그립니다. 이 원칙 없이 auto ads 스크립트나 두 번째
   광고 자리를 추가하지 마세요.

3단계 절차:
  1단계 (완전 숨김) : ADS_ENABLED=false ← 기본값, 지금 여기입니다. <head>에 애드센스
                       스크립트 자체가 안 실리고(구글 쪽에 요청이 전혀 안 나갑니다),
                       어떤 화면에도 광고 자리가 안 그려집니다.
  2단계 (관리자만)  : 서버 환경변수 ADS_ENABLED=true + 아래 ADS_ADMIN_ONLY=True 유지.
                       관리자로 로그인했을 때만 실제 광고가 보여서, 배치·크기·구글 승인
                       상태를 실사용자에게 노출하지 않고 먼저 눈으로 확인할 수 있습니다.
  3단계 (전체 공개) : 아래 ADS_ADMIN_ONLY 를 False 로 **한 글자만** 바꿉니다.

필요한 환경변수 (Render 대시보드 → Environment, 셋 다 있어야 실제로 켜집니다):
  - ADS_ENABLED      : "true" 여야 켜짐. 없으면(기본) 전부 꺼짐.
  - ADS_PUBLISHER_ID : 구글 애드센스 게시자 ID. "pub-"로 시작하는 형태 그대로 넣으세요
                        (예: "pub-1234567890123456" — 애드센스 대시보드 우측 상단·계정
                        정보에서 확인). ads.txt 발급과 스크립트 태그 양쪽에 씁니다.
  - ADS_SLOT_ID      : 애드센스에서 "광고 단위"를 만들면 나오는 슬롯 번호(숫자만, 예:
                        "1234567890"). 아직 광고 단위를 안 만들었다면 비워두세요 — 있지도
                        않은 슬롯 번호를 지어내지 않습니다(ENGINEERING_SPEC.md §0-1).
"""

import os

from nicegui import ui

from web.auth import is_admin

ADS_ENABLED = (os.environ.get('ADS_ENABLED') or '').strip().lower() == 'true'

# 2단계(관리자 전용)가 기본값입니다. 구글 승인이 나고 실제 화면에서 광고 위치·크기를
# 관리자 눈으로 먼저 확인한 뒤에만 False 로 바꾸세요.
ADS_ADMIN_ONLY = True

ADS_PUBLISHER_ID = (os.environ.get('ADS_PUBLISHER_ID') or '').strip()
ADS_SLOT_ID = (os.environ.get('ADS_SLOT_ID') or '').strip()

# 셋 다 채워졌을 때만 "준비됨"입니다 — 하나라도 비면 아무것도 그리지 않습니다.
_READY = bool(ADS_ENABLED and ADS_PUBLISHER_ID and ADS_SLOT_ID)


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


def ad_slot() -> None:
    """화면 맨 아래에 배너 광고 자리 하나를 그립니다.

    ⚠️ `web/layout.py` 의 공통 껍데기 한 곳에서만 부릅니다 — 화면 파일에서 직접 부르지
       마세요. 그래야 "공개된 화면 전부"에 자동으로 적용되고, 광고 자리가 실수로
       여러 개 생기는 일도 없습니다 (ENGINEERING_SPEC.md §0-3-10 공유 컴포넌트 관례와
       같은 이유입니다).
    """
    if not _READY:
        return
    if ADS_ADMIN_ONLY and not is_admin():
        return
    with ui.column().classes('w-full items-center gap-1 mt-4'):
        ui.label('광고').classes('vh-muted')
        ui.html(
            '<ins class="adsbygoogle" style="display:block" '
            f'data-ad-client="ca-{ADS_PUBLISHER_ID}" '
            f'data-ad-slot="{ADS_SLOT_ID}" '
            'data-ad-format="auto" '
            'data-full-width-responsive="true"></ins>'
            '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
        )
