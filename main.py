"""
NiceGUI 진입점 — **지금 실서비스가 도는 곳**입니다 (2026-08-17 컷오버 완료).

기존 `app.py`(Streamlit 진입점)와 `views/` 는 **즉시 롤백에 대비해 컷오버 후 최소 2주간
그대로 살려둡니다.** 유예가 끝나면 archive/ 로 옮겨 서비스 경로에서 제거합니다
(ENGINEERING_SPEC.md §0-3-10 — 듀얼런은 기한이 있는 임시 상태입니다).

실행 방법:
  로컬:  NICEGUI_STORAGE_SECRET=아무-긴-난수-문자열 python main.py
  Render: Dockerfile + 환경변수(§8-3)로 자동 실행
"""

import os

from nicegui import app, ui

from utils import data_source
import web.ads
import web.theme
# @ui.page 등록을 위해 import 자체가 필요합니다 (모듈을 읽는 순간 경로가 등록됨).
#   pegy_page      → '/'            (공개 기본 화면)
#   us_stocks_page → '/us'          (공개 화면)
#   scorecard_page → '/scorecard'   (로그인 필요 · **2026-08-17 공개 전환 완료**)
#   report_page    → '/report'      (로그인 필요 · **2026-08-17 공개 전환 완료**,
#                                    scorecard 와 같은 로그인 세션을 공유합니다)
#   macro_page     → '/admin/macro' (관리자 전용 · 오너 지시로 개발 중단 상태)
#   admin_page     → '/admin'       (관리자 게이트)
#   duel_page             → '/duel'             (로그인 필요 · "결투다!" 1갈래,
#                                                 DUEL_ENABLED 로 단계적 공개, 2026-08-20 추가)
#   scorecard_consent_page     → '/scorecard/consent'      (로그인 필요 · "내 성적표" 공개
#                                 동의 관리, SCORECARD_CONSENT_ENABLED · 기본 관리자 전용)
#   scorecard_leaderboard_page → '/scorecard/leaderboard'  (로그인 필요 · "내 성적표" 공개
#                                 순위표 열람, SCORECARD_LEADERBOARD_ENABLED · 기본 관리자 전용)
#   dividend_page  → '/dividend'    (공개 화면 · "투자 감사합니다!" 배당 캘린더,
#                                    DIVIDEND_ENABLED 로 단계적 공개, 2026-08-24 추가)
#   indicator_page → '/indicator'   (관리자 전용 시작 · "여기서부터는 신앙입니다" 보조지표
#                                    RSI/MACD/볼린저밴드, INDICATOR_ENABLED 로 단계적 공개,
#                                    2026-08-25 추가)
#
# (2026-08-23 전환) `duel_consent_page → '/duel/consent'` 와
#   `duel_leaderboard_page → '/duel/leaderboard'` 두 화면을 **성적표 공개 계층으로 전환**
#   하며 파일째 지웠습니다. 공개되는 대상이 결투 가상계좌 성적에서 "내 성적표"(실제 보유
#   자산)로 바뀌어, 두 화면의 문구·구조·읽는 표가 전부 달라졌기 때문입니다(부분 수정이
#   아니라 교체). `/duel`(1갈래 가상계좌 대결) 자체는 아무 영향이 없습니다.
#
# (2026-08-17 삭제) `demo_page → '/demo'` — 0단계 모바일 반응형·저장소 지속성 검증 전용
#   화면이었습니다. 8단계와 컷오버가 모두 끝나 역할이 사라져 파일째 지웠습니다
#   (`web/auth.py` 의 데모 카운터 두 함수도 함께 — ENGINEERING_SPEC.md §0-3-10).
from web.pages import (  # noqa: F401
    admin_page,
    dividend_page,
    duel_page,
    indicator_page,
    macro_page,
    pegy_page,
    report_page,
    scorecard_consent_page,
    scorecard_leaderboard_page,
    scorecard_page,
    us_stocks_page,
)

web.theme.register()
web.ads.register_head()

# 📢 구글 애드센스 켜짐/꺼짐도 데이터 소스와 같은 이유로 기동 로그 한 줄에 남깁니다
#    (추측으로 확인하지 않기 — §0-1). 게시자 ID·슬롯 ID 값 자체는 비밀이 아니지만
#    로그에는 켜짐/꺼짐과 단계만 남기고 값은 남기지 않습니다.
if web.ads.ADS_ENABLED and web.ads.ADS_PUBLISHER_ID and web.ads.ADS_SLOT_ID:
    _ads_stage = '2단계(관리자 전용)' if web.ads.ADS_ADMIN_ONLY else '3단계(전체 공개)'
    print(f'📢 [광고] 애드센스 켜짐 — {_ads_stage}.')
elif web.ads.ADS_ENABLED:
    print('📢 [광고] ADS_ENABLED=true 이지만 ADS_PUBLISHER_ID/ADS_SLOT_ID 가 비어 있어 '
          '실제로는 꺼진 상태입니다 (web/ads.py 참고).')
else:
    print('📢 [광고] 꺼짐 (기본값 — ADS_ENABLED 로 단계적 공개, web/ads.py 참고).')

# 🌐 데이터 원격 로드(NICEGUI_MIGRATION_PLAN.md §8-5 B안)가 켜졌는지 **기동 로그 한 줄로** 확인할
#    수 있게 합니다. 오너가 Render 대시보드에서 DATA_SOURCE_BASE_URL 을 넣은 뒤, 값이 실제로
#    반영됐는지 "Logs" 탭에서 바로 볼 수 있어야 하기 때문입니다(추측으로 확인하지 않기 — §0-1).
#    ⚠️ 주소 자체는 공개 저장소의 raw URL 이라 비밀이 아니지만, 로그에는 켜짐/꺼짐만 남깁니다.
_DS_BASE, _DS_CONFIG_ERROR = data_source.resolve_base_url()
if _DS_CONFIG_ERROR:
    print(f'⚠️ [데이터 소스] {data_source.ENV_BASE_URL} 설정이 올바르지 않습니다 — {_DS_CONFIG_ERROR}. '
          '이미지에 함께 배포된 data/ 사본으로 동작합니다.')
elif _DS_BASE:
    print('🌐 [데이터 소스] 원격 로드 켜짐 — data/*.json 을 실행 중에 원격에서 읽습니다 '
          f'(TTL {data_source.DEFAULT_TTL_SECONDS:.0f}초 기본, ETag 조건부 GET).')
else:
    print('📁 [데이터 소스] 원격 로드 꺼짐 — 이미지에 포함된 data/ 파일을 그대로 읽습니다 (기존 동작).')


@app.get('/healthz')
def healthz():
    """Render 헬스체크 · 무료 인스턴스 깨우기용. UI를 그리지 않아 가볍습니다."""
    return {'ok': True}


@app.get('/ads.txt')
def ads_txt():
    """구글 애드센스가 이 사이트의 광고 게재 권한을 확인하려고 크롤링하는 표준 경로.

    ADS_PUBLISHER_ID 가 없으면(승인 전·환경변수 미설정) **404를 그대로 돌려줍니다** —
    있지도 않은 게시자 ID로 잘못된 ads.txt 를 내보내는 것보다, 아예 없는 편이
    안전합니다(ENGINEERING_SPEC.md §0-1 — 값을 지어내지 않습니다).
    """
    from fastapi.responses import PlainTextResponse

    if not web.ads.ADS_PUBLISHER_ID:
        from fastapi import Response
        return Response(status_code=404)
    return PlainTextResponse(
        f'google.com, {web.ads.ADS_PUBLISHER_ID}, DIRECT, f08c47fec0942fa0\n'
    )


STORAGE_SECRET = os.environ.get('NICEGUI_STORAGE_SECRET')
if not STORAGE_SECRET:
    # 기본값을 지어내지 않습니다 (ENGINEERING_SPEC.md §0-1). 이유를 로그에 남기고 기동을 거부합니다.
    raise SystemExit(
        '[기동 실패] 환경변수 NICEGUI_STORAGE_SECRET 가 설정되지 않았습니다.\n'
        '  - 로컬 실행: export NICEGUI_STORAGE_SECRET="아무-긴-난수-문자열" (또는 .env 파일)\n'
        '  - Render 배포: 대시보드 → Environment 에 등록\n'
        '  - 난수 생성 예시: python -c "import secrets; print(secrets.token_hex(32))"'
    )


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 8080)),
        title='잘 보면 보이는 손',
        favicon='💡',
        storage_secret=STORAGE_SECRET,
        reload=False,
        show=False,
        uvicorn_logging_level='info',
    )
