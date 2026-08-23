"""
헤더 + 좌측 드로어(사이드바) 뼈대 (NiceGUI 이전 0단계 → 2단계에서 메뉴 배선 시작).

각 페이지 함수는 이렇게 씁니다:

    from web.layout import layout

    @ui.page('/some-page')
    def some_page():
        with layout('화면 제목'):
            ui.label('본문')

메뉴(한국 주식/미국 주식/내 성적표/사장님 보고서)는 각 화면을 옮길 때마다 여기 드로어에
한 줄씩 채웁니다 (NICEGUI_MIGRATION_PLAN.md §3-2 라우팅 표).
"""

import os
from contextlib import contextmanager

from nicegui import ui

from utils import data_source
from web.auth import is_admin
from web.components.widgets import error_banner

# =============================================================================
# ⚔️ "결투다!"(4번째 모듈) 공개 스위치 — DUEL_MODULE_WORK_ORDER.md 2-8 · 7단계
# =============================================================================
#  오너가 확정한 **3단계 공개 절차**가 아래 두 값으로 전부 표현됩니다. 단계를 넘길 때
#  고치는 것은 매번 **이 두 줄 중 하나뿐**입니다.
#
#    1단계 (전체 숨김)     : DUEL_ENABLED=false  ← 기본값. 메뉴에 항목이 아예 안 생기고,
#                            URL 로 /duel 을 직접 쳐도 화면이 "준비중" 안내만 그립니다
#                            (`web/pages/duel_page.py` 가 같은 값을 보고 판단 — 이중 방어).
#    2단계 (관리자 전용)   : 서버 환경변수 DUEL_ENABLED=true + 아래 DUEL_MENU_ADMIN_ONLY=True
#                            → `/admin/macro` 와 **똑같은 방식**으로 관리자 계정에게만
#                            메뉴가 보입니다(§0-3-10 — 기존 패턴 재사용, 새 구조 발명 금지).
#    3단계 (전체 공개)     : 아래 DUEL_MENU_ADMIN_ONLY 를 **False 로 한 글자만** 바꿉니다.
#                            그 순간 메뉴가 모든 로그인 사용자에게 보이고, 화면의 관리자
#                            제한도 함께 풀립니다(같은 값을 화면도 보기 때문입니다).
#
#  ⚠️ 환경변수 판정은 `web/pages/scorecard_page.py::SCORECARD_OCR_ENABLED` 와
#     `utils/data_source.py::is_remote_enabled()` 가 이미 쓰는 관례 그대로입니다 —
#     **값이 정확히 "true"(대소문자 무관)일 때만** 켜집니다. "값이 있으면 켜짐"으로
#     판정하면 환경변수를 실수로 아무 값이나 넣어도 켜지는 사고가 납니다(§0-3-6 기본 숨김).
#  ⚠️ 이 플래그를 화면 파일이 아니라 여기 둔 이유: `web/pages/duel_page.py` 는 이미 이
#     파일(`layout`)을 import 하므로 여기서 가져다 쓰면 순환 import 가 없지만, 반대 방향
#     (layout → duel_page)은 순환이 됩니다. 값의 출처는 한 곳이어야 하므로(§0-3-10)
#     메뉴와 화면이 **같은 상수 하나**를 봅니다.
DUEL_ENABLED = (os.environ.get("DUEL_ENABLED") or "").strip().lower() == "true"

#: 2단계(관리자 전용) ↔ 3단계(전체 공개)를 가르는 **단 하나의 불리언**. 위 설명 참고.
#
# ✅ 오너 확정 (2026-08-22) — 3단계(전체 공개)로 전환합니다. 최근 라운드(리밸런싱 매도 +
# 성적표 카드 가격 버그 + 예상 금액 표시)까지 검수를 마쳤고, 관리자 로그인 없이 일반
# 로그인 사용자 전원이 `/duel`(1갈래 "덤벼라 나 자신")을 볼 수 있어야 모바일 확인도
# 수월해집니다.
#
# 🗑️ 2026-08-23 — 예전에 이 자리에 함께 적혀 있던 "2갈래(공개 동의·공개 순위표)" 설명은
#    지웠습니다. 결투 가상계좌를 공개하던 그 계층(`DUEL_CONSENT_*` / `DUEL_LEADERBOARD_*`,
#    `/duel/consent`, `/duel/leaderboard`)이 은퇴하고, 공개되는 대상이 "내 성적표"(실제
#    보유 자산)로 바뀌었기 때문입니다(아래 `SCORECARD_*` 스위치). **`DUEL_ENABLED` 와 이
#    값은 그 전환과 무관하며 `/duel`(1갈래 가상계좌 대결) 화면 하나만 계속 지배합니다.**
DUEL_MENU_ADMIN_ONLY = False

# =============================================================================
# 💼 "내 성적표" 공개 계층 스위치 — 2026-08-23 추가
#    (`/scorecard/consent` 공개 동의 관리 · `/scorecard/leaderboard` 공개 순위표)
# =============================================================================
#  🔁 이 네 값은 은퇴한 `DUEL_CONSENT_*` / `DUEL_LEADERBOARD_*` 네 값의 자리를 그대로
#     이어받습니다. 공개되는 데이터가 **가상계좌 성적에서 "내 성적표"(실제 보유 자산)로**
#     바뀌었을 뿐, 단계적 공개 절차와 판정 관례는 한 글자도 바뀌지 않았습니다 —
#     환경변수 값이 **정확히 "true"(대소문자 무관)** 일 때만 켜집니다(§0-3-6 기본 숨김).
#
#  🔴 **결투 스위치에 묶지 않습니다.** 예전 2갈래 화면은 `DUEL_ENABLED and ...` 로 1갈래에
#     의존했는데(계좌가 없으면 공개할 성적도 없으므로 옳았습니다), 지금 공개되는 것은
#     `/scorecard` 의 실제 보유종목입니다. `/scorecard` 는 이미 전체 공개된 화면이므로 이
#     계층은 결투와 아무 의존 관계가 없고, 묶어 두면 "가상계좌 기능을 끄면 실제 성적표
#     공개 동의도 사라진다"는 **사실과 다른 의존**이 코드에 생깁니다.
#
#  🔴 화면마다 스위치를 한 쌍씩 두는 이유도 그대로입니다. 동의 화면은 "참가자를 모으는"
#     화면이라 먼저 열어야 하고, 순위표 화면은 최소 인원
#     (`duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION`)이 찰 때까지 어차피 아무것도 보여줄 수
#     없습니다.

#: 🔓 공개 동의 관리 화면(`/scorecard/consent`) 기본 숨김 스위치.
SCORECARD_CONSENT_ENABLED = (
    (os.environ.get("SCORECARD_CONSENT_ENABLED") or "").strip().lower() == "true"
)

#: 위 화면의 2단계(관리자 전용) ↔ 3단계(전체 공개).
#
# ⏳ 2026-08-23 — **2단계(관리자 전용)에서 시작합니다.** 결투 공개 계층도 정확히 같은
# 순서를 밟았습니다(2026-08-20 관리자 전용으로 열고, 오너가 코드 근거까지 직접 재확인한
# 뒤 2026-08-22 에 이 한 글자를 False 로 바꿔 전체 공개). 이번 계층은 공개 대상이 **실제
# 보유 자산**이라 그 검수를 다시 처음부터 받아야 하므로, 전환은 오너가 직접 이 값을
# False 로 바꾸는 것으로만 일어납니다.
SCORECARD_CONSENT_MENU_ADMIN_ONLY = True

#: 🏆 공개 순위표 열람 화면(`/scorecard/leaderboard`) 기본 숨김 스위치.
SCORECARD_LEADERBOARD_ENABLED = (
    (os.environ.get("SCORECARD_LEADERBOARD_ENABLED") or "").strip().lower() == "true"
)

#: 위 화면의 2단계(관리자 전용) ↔ 3단계(전체 공개).
#
# ⏳ 2026-08-23 — 위와 같은 이유로 **2단계(관리자 전용)에서 시작합니다.** 최소 인원 미달
# 그룹은 `utils/scorecard_publish.py::split_groups_by_threshold()` 가 애초에 발행표에 쓰지도
# 않으므로 이 화면을 열어도 "참가자가 부족합니다" 안내만 보이지만, 그건 "발행이 안 된다"는
# 뜻이지 "화면이 안 보인다"는 뜻이 아니라서 화면 쪽 스위치를 따로 둡니다.
SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY = True

# (경로, 라벨, 관리자전용) — 실제로 이전이 끝난 화면만 넣습니다. "곧 생길 메뉴"를 미리 만들어
# 두면 사용자가 눌렀을 때 404 가 나므로, 화면이 완성된 단계에서 한 줄씩 추가합니다.
# ⚠️ 관리자 콘솔 링크는 **관리자로 인증된 접속에만** 보여줍니다. 화면 자체는 어차피 비밀번호
#    게이트로 막혀 있지만, 공개 화면에 관리자 입구를 광고해 무차별 대입 표적을 만들 이유가
#    없습니다 (ENGINEERING_SPEC.md §0-3-9 — 알려진 기본 공격면은 줄여둡니다).
# ⚠️ '내 성적표'(/scorecard)·'사장님 보고서'(/report)는 §0-3-6 스테이징 절차를 거쳐
#    2026-08-17 오너 승인으로 공개 전환되었습니다(계획서 §9 "4. scorecard" ⑦ 동시 로그인
#    격리 검증 + 실기기 확인 완료). 로그인 없이는 아무 데이터도 그리지 않으며(로그인 폼만),
#    DB 는 RLS 로 본인 행만 허용합니다(§0-3-8). 두 화면은 같은 로그인 세션을 씁니다(오너 확정).
#
# 2026-08-18 오너 피드백 — 예전 Streamlit 버전은 메뉴가 "사실 이 가격이에요"/"내 성적표"
# 두 그룹으로 묶여 있어 한눈에 보기 편했는데, 지금(NiceGUI)은 4개가 한 줄로 쭉 나열돼 있어
# 정렬이 안 보기 편하다는 지적. 평평한 리스트 대신 **그룹(섹션 제목) + 하위 항목** 구조로
# 되돌립니다. 관리자 전용 항목은 별도 그룹으로 마지막에 붙입니다.
_MENU_GROUPS = [
    ('💡 사실 이 가격이에요', [
        ('/', '🇰🇷 한국 주식은 이가격이에요', False),
        ('/us', '🇺🇸 미국 주식은 이가격이에요', False),
    ]),
    # 💼 "내 성적표" 공개 계층(2026-08-23) 두 화면도 **같은 그룹 안에** 넣습니다 —
    #    공개되는 데이터가 바로 이 그룹의 `/scorecard` 이기 때문입니다. 각자의 스위치가
    #    켜졌을 때만 항목이 생기고, 꺼져 있으면 **항목 자체를 만들지 않습니다**(숨긴 링크를
    #    그려두고 CSS 로 가리는 방식이 아닙니다 — §0-3-6).
    #    ⚠️ 항목 목록을 `_scorecard_items = [...]` 같은 **이름 붙은 전역**으로 빼지
    #       않았습니다 — `tests/test_web_session_isolation.py` [1-a] 가 "모듈 최상위 가변
    #       전역"을 전부 잡아 사유 등록을 요구하기 때문입니다(§0-3-8). 아래 `⚔️ 결투다!`
    #       그룹이 같은 이유로 쓰는 방식과 같습니다.
    ('📊 보유종목', [
        ('/scorecard', '💼 내 성적표', False),
        ('/report', '📈 사장님 보고서입니다', False),
    ]
        + ([('/scorecard/consent', '🔓 공개 동의 관리', SCORECARD_CONSENT_MENU_ADMIN_ONLY)]
           if SCORECARD_CONSENT_ENABLED else [])
        + ([('/scorecard/leaderboard', '🏆 공개 순위표 (내 밑으로 눈 깔어)',
             SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY)]
           if SCORECARD_LEADERBOARD_ENABLED else [])),
    # 🏢 매크로 방공망 — **관리자 전용**(공개 화면에서 내려온 지 2026-08-05부터)이고,
    #    오너 지시(2026-08-10)로 **개발 중단 상태**입니다. 메뉴에도 관리자에게만 보입니다.
    ('⚙️ 관리자', [
        ('/admin/macro', '🏢 매크로 방공망 (관리자 전용)', True),
        ('/admin', '⚙️ 관리자 콘솔', True),
    ]),
]

# ⚔️ 결투다! — 기능 영역마다 그룹을 하나씩 두는 위 구조를 그대로 따릅니다. `DUEL_ENABLED`
#    가 꺼져 있으면(기본값) **항목 자체를 만들지 않습니다** — 숨긴 링크를 그려두고 CSS 로
#    가리는 방식이 아니라, 메뉴 데이터에 존재하지 않게 합니다.
#    `insert(-1)` = 마지막 '⚙️ 관리자' 그룹 **바로 앞**에 넣기(관리자 그룹은 항상 맨 끝).
#    🗑️ 2026-08-23 — 이 그룹에 함께 있던 `/duel/consent`·`/duel/leaderboard` 두 항목을
#       뺐습니다. 결투 가상계좌를 공개하던 계층이 은퇴하고, 그 자리를 "내 성적표" 공개
#       계층(위 '📊 보유종목' 그룹의 `/scorecard/consent`·`/scorecard/leaderboard`)이
#       이어받았기 때문입니다. **`/duel` 자체는 아무 영향이 없습니다.**
if DUEL_ENABLED:
    _MENU_GROUPS.insert(-1, ('⚔️ 결투다!',
        [('/duel', '⚔️ 참전하기', DUEL_MENU_ADMIN_ONLY)]
    ))

# 하위호환용 평평한 목록 — `_MENU_GROUPS` 를 펼친 것뿐이라 항목(경로·라벨·관리자전용) 값은
# 그룹으로 나누기 전과 완전히 동일합니다(§0-3-10 — 값의 출처를 하나로 유지). 기존에
# `web.layout._MENU` 를 직접 참조하던 배선 검사(`tests/test_web_session_isolation.py`
# [8] 매크로 배선)가 계속 통과하도록 남겨둡니다.
_MENU = [item for _, group_items in _MENU_GROUPS for item in group_items]


@contextmanager
def layout(title: str, width_class: str = 'max-w-4xl'):
    """공통 껍데기.

    :param title: 헤더 우측에 작게 표시할 화면 이름
    :param width_class: 본문 최대 폭(Tailwind). 카드가 넓은 화면(pegy 등)은 'max-w-6xl'.
    """
    # 화면 카드가 전부 짙은 남색 계열이라(기존 Streamlit 다크 테마 기준으로 만들어진 HTML)
    # 밝은 배경 위에 그리면 인상이 크게 달라집니다. 프로젝트 전체를 다크로 고정합니다.
    ui.dark_mode(True)

    with ui.header().classes('items-center justify-between q-pa-sm'):
        with ui.row().classes('items-center gap-2'):
            # 2026-08-18 오너 피드백 — "사이드탭 여는 버튼이 너무 안 보여": 기존 `flat` 버튼은
            # 배경 없이 아이콘만 떠 있어 헤더 색 위에서 존재감이 거의 없었습니다. 흰 원형
            # 배경 + 진한 아이콘 색으로 바꿔, 눌러야 할 자리라는 게 한눈에 보이게 했습니다.
            ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
                .props('round unelevated color=white text-color=primary size=md') \
                .classes('shadow-2')
            ui.label('💡 잘 보면 보이는 손').classes('text-lg font-bold')
        ui.label(title).classes('text-sm opacity-70')

    admin = is_admin()
    with ui.left_drawer(value=False) as drawer:
        with ui.column().classes('gap-1 p-2'):
            # 2026-08-18 오너 피드백 — 예전 Streamlit 메뉴처럼 "그룹 제목 + 하위 항목"으로
            # 묶어서 정렬을 보기 편하게 바꿨습니다(위 `_MENU_GROUPS` 참고). 그룹 제목은
            # 클릭 대상이 아니라 구획을 나누는 안내용이라 링크가 아닌 라벨로 둡니다.
            for group_label, items in _MENU_GROUPS:
                visible_items = [
                    (path, label) for path, label, admin_only in items
                    if not admin_only or admin
                ]
                if not visible_items:
                    continue
                ui.label(group_label).classes(
                    'text-xs font-bold uppercase tracking-wide opacity-60 mt-3 mb-1'
                )
                for path, label in visible_items:
                    ui.link(label, path).classes(
                        'text-base no-underline pl-3 py-1 rounded-borders vh-menu-link'
                    )

    with ui.column().classes(f'w-full {width_class} mx-auto p-4 gap-4 vh-page'):
        # 🚨 "지금 보이는 값이 최신이 아닐 수 있음" 전역 배너 자리 (NICEGUI_MIGRATION_PLAN §8-5).
        #    · **자리만 먼저 잡고**, 실제 판정은 본문을 다 그린 뒤에 합니다. 본문이 데이터를
        #      읽는 도중에 실패가 확정되기 때문에, 본문보다 먼저 판정하면 "한 박자 늦은 배너"가
        #      됩니다. NiceGUI 는 나중에 만든 요소도 지정한 컨테이너 안에 들어가므로, 화면에는
        #      정상적으로 **맨 위**에 보입니다.
        #    · 화면 5개(pegy/us_stocks/scorecard/report/macro)에 같은 코드를 복붙하지 않으려고
        #      모든 페이지가 공유하는 이 한 곳에 둡니다 (ENGINEERING_SPEC.md §0-3-10).
        stale_slot = ui.element('div').classes('w-full')
        yield
        _render_staleness_banner(stale_slot)


def _render_staleness_banner(slot) -> None:
    """원격 데이터가 최신이 아닐 때만 빨간 배너를 그립니다. 정상이면 아무것도 그리지 않습니다.

    언제 뜨나 — `DATA_SOURCE_BASE_URL` 이 켜져 있고, 이번 프로세스에서 어떤 파일이든 최신화에
    실패해 **마지막 성공분(또는 배포에 함께 실린 사본)** 을 보여주고 있을 때.
    언제 사라지나 — 그 파일의 다음 fetch 가 성공하면 상태가 스스로 풀립니다. 즉 **다음에
    페이지를 열면** 배너가 없습니다. 이미 열려 있는 화면을 자동으로 고치지는 않습니다
    (§0-3-1 — 실시간처럼 보이게 만들지 않습니다).
    """
    try:
        status = data_source.get_staleness_status()
        if not status:
            return
        with slot:
            error_banner(status['message'])
    except Exception as exc:                          # noqa: BLE001 — 배너 때문에 화면이 죽으면 안 됩니다
        print(f'⚠️ 데이터 최신성 배너 표시 실패: {exc}')
