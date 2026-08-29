"""
💼 "내 성적표" — **공개 동의 관리 화면** (로그인 필요, URL `/scorecard/consent`).

2026-08-23 — 은퇴한 `web/pages/duel_consent_page.py`(결투 가상계좌 공개 동의)를 대신하는
화면입니다. 공개되는 대상이 **가상계좌 성적에서 "내 성적표"(실제 보유 자산)로** 바뀌었고,
그에 따라 화면의 모양도 함께 바뀌었습니다.

    utils/duel_rules.py            3개월 재동의 차단 · 시즌 길이 · 최소 인원 같은 **숫자의
                                   단일 출처**(통화·모듈과 무관한 순수 규칙이라 그대로
                                   재사용합니다 — 같은 숫자를 두 벌 두지 않습니다).
    utils/scorecard_publish_db.py  save_consent() / fetch_my_consent() / revoke_consent() /
                                   ensure_nickname() / fetch_my_nickname()
    ← 이 파일                      화면 구조와 문구. **동의 규칙을 여기서 다시 구현하지
                                   않습니다**(§0-3-10).

-------------------------------------------------------------------------------
🔁 결투 동의 화면과 **구조가 다른 점 세 가지** (실수하기 쉬운 자리라 여기 못 박습니다)
-------------------------------------------------------------------------------
① **계좌 루프가 없습니다.** "내 성적표"는 사용자당 포트폴리오 하나이므로 로그인한 사람
   에게 **동의 카드는 정확히 한 장**입니다(결투는 M1/M3/M6 계좌마다 한 장이었습니다).
   그래서 결투 쪽에 있던 `_consent_section()` 팩토리(= `for` 루프 안에서 `@ui.refreshable`
   을 정의하면 `.refresh()` 가 마지막 반복 객체로 풀리는 문제를 피하려던 장치)를 **통째로
   들어냈습니다.** 카드가 하나뿐이면 늦은 이름 결정 문제가 생길 자리 자체가 없고,
   쓰이지 않는 우회 장치를 남겨두면 다음 사람이 "왜 이렇게 짜여 있지"를 다시 조사하게
   됩니다.
② **체급 산정을 위한 독립 동의(결투의 `consent_real_principal_bracket`)가 없습니다.**
   결투에서 그 동의가 따로 있던 이유는 "다른 모듈('내 성적표')의 실제 자산 데이터를 끌어다
   쓴다"는 것이었는데, 여기서는 **공개되는 데이터 자체가 이미 그 실제 자산**입니다. 종목별
   매입금액을 공개하기로 한 순간 체급의 입력값(매입원가합계)은 이미 공개된 값들의 단순 합
   이라, 체급을 위한 두 번째 동의 게이트를 세울 대상이 남아 있지 않습니다
   (`utils/scorecard_publish.py` 머리말 ③ ·
   `utils/scorecard_publish_db.CONSENT_ITEM_FLAGS` 주석 · 스키마 §2-2 와 같은 판단).
   ⚠️ 2026-08-23 정정 — **항목별 체크박스는 5개가 아니라 6개입니다.** 늘어난 항목
      (`consent_holding_details`, "종목별 상세지표")은 체급과 무관하며, 결투처럼 따로 켜고
      끄는 독립 동의도 아닙니다 — 앞의 다섯 개와 **같은 '전부 아니면 전무' 묶음**입니다.
   🔴 체크박스를 손으로 하나 더 그리지 **마세요.** 이 화면은 항목을 `consent_item_rows()`
      에서 받아 루프로 그립니다 — 항목을 늘리는 자리는 `CONSENT_ITEM_SENTENCES` +
      `CONSENT_ITEM_FLAGS` 두 상수뿐이고, 화면 코드는 손대지 않습니다(§0-3-10). 하드코딩한
      체크박스를 끼워 넣는 순간 화면이 저장하려는 항목과 DB 의
      `scorecard_consent_final_requires_all` CHECK 가 갈라집니다.
③ **창유형(M1/M3/M6) 축이 없습니다.** 대신 원화·달러라는 통화 축이 있는데, 그 축은
   **동의의 축이 아닙니다** — `scorecard_public_consent` 의 기본키는 `user_id` 하나이고
   철회도 통화를 가리지 않습니다. 즉 공개 동의는 사용자당 **하나의 결정**이고, 그 결정이
   원화 순위표와 달러 순위표 양쪽에 함께 적용됩니다. 사용자가 이 사실을 모르고 동의하면
   안 되므로 화면에 그대로 적습니다(아래 `NOTICE_TRACKS_INDEPENDENT`).

-------------------------------------------------------------------------------
🚧 공개 게이트 — 다른 화면과 **똑같은 2단계 패턴**, 스위치만 다릅니다
-------------------------------------------------------------------------------
    SCORECARD_CONSENT_ENABLED         … 이 화면 전용 스위치(기본 꺼짐, 환경변수)
    SCORECARD_CONSENT_MENU_ADMIN_ONLY … 관리자 전용 단계 ↔ 전체 공개를 가르는 불리언

⚠️ 결투 화면과 달리 `DUEL_ENABLED` 를 보지 **않습니다.** 이 화면이 다루는 데이터는 결투
   가상계좌가 아니라 "내 성적표"이고, `/scorecard` 는 이미 전체 공개된 화면입니다. 결투
   스위치에 묶어 두면 "가상계좌 기능을 끄면 실제 성적표 공개 동의도 사라진다"는 사실과
   다른 의존이 코드에 생깁니다.

메뉴에서 감추는 것만으로는 부족합니다(주소를 아는 사람은 그냥 들어옵니다). 그래서 이
화면도 **같은 값을 직접 보고** 본문을 한 글자도 그리지 않습니다(벨트+멜빵).

-------------------------------------------------------------------------------
🔴 §0-3-8 — 이 화면이 지키는 것
-------------------------------------------------------------------------------
· 사용자 데이터는 모듈 전역에 두지 않습니다. 최상위에는 **문자열 상수뿐**입니다.
· DB 를 만지는 함수는 전부 `client` 와 `user_id` 를 인자로 받습니다("지금 누가 로그인
  했는지"를 추측하지 않습니다).
· **화면을 그리는 행위는 아무것도 만들거나 바꾸지 않습니다** — 닉네임 조회는 만들지 않는
  `fetch_my_nickname()` 을 씁니다(`ensure_nickname()` 은 사용자가 실제로 동의를 저장한
  직후에만 부릅니다).
· 배치 전용 함수(B 절)는 **이름조차 가져오지 않습니다.**

-------------------------------------------------------------------------------
📝 문구에 대하여
-------------------------------------------------------------------------------
· 항목별 동의 6문장은 결투 문안을 **그대로 옮긴 것이 아니라 다시 쓴 것**입니다 — 공개
  대상이 가상계좌 성적이 아니라 실제 보유 자산이라, 옛 문장을 그대로 두면 사용자가 무엇을
  공개하는지 잘못 이해합니다(§0-1). 다만 보유종목 문장의 **"개별 열람"** 은 오너가 명시적
  으로 요구한 문구 요소라 구조를 그대로 유지했습니다.
· 책임 고지(§0-1 "읽지 않고 동의한 것도 본인 책임")는 모듈과 무관하게 성립하는 문장이라
  결투 화면의 확정 문안을 그대로 씁니다.
"""

from nicegui import ui

from utils import duel_rules
from utils.duel_rules import DuelRuleError
from utils.scorecard_db import supabase_status, user_id_of
from utils.scorecard_publish_db import (
    CONSENT_ITEM_FLAGS,
    DuelDbError,
    ensure_nickname,
    fetch_my_consent,
    fetch_my_nickname,
    revoke_consent,
    save_consent,
)
from web.auth import (
    current_user_async,
    get_client_async,
    has_supabase_session,
    is_admin,
    logout_async,
)
from web.auth_ui import fail_message, render_auth
from web.blocking import run_blocking
from web.components import error_banner, esc, guard_double_click, info_banner, warning_banner
from web.layout import (
    SCORECARD_CONSENT_ENABLED,
    SCORECARD_CONSENT_MENU_ADMIN_ONLY,
    layout,
)
from web.state import PAGE_RESPONSE_TIMEOUT_SECONDS

# =============================================================================
# 1층 — 항목별 개별 체크박스 6개 (2026-08-23 에 5개 → 6개)
# =============================================================================
#  🔴 순서와 키는 `scorecard_publish_db.CONSENT_ITEM_FLAGS` 와 **같아야 합니다.** 아래
#     `consent_item_rows()` 가 매번 그 사실을 확인합니다(§0-1 — 화면에 보이는 항목과 실제로
#     저장되는 항목이 어긋나면, 사용자는 자기가 동의하지 않은 것에 동의한 셈이 됩니다.
#     이 모듈에서 가장 나쁜 종류의 버그입니다).
#  🔴 여섯 문장 모두 **실제 보유 자산**을 말합니다. "가상계좌"·"결투"라는 말이 이 화면에
#     남아 있으면 그것 자체가 사실과 다른 안내입니다.
#  🔴 보유종목 문장의 **"개별 열람"** 은 오너가 명시적으로 요구한 문구 요소입니다 — 빼지
#     마세요("목록에 이름만 뜨는 것"과 "한 사람 것을 펼쳐서 볼 수 있는 것"은 전혀 다릅니다).
#  🔴 2026-08-23 추가 — 여섯 번째 항목 `consent_holding_details`. 오너가 실사용 검증 뒤
#     "'내 성적표'에 나오는 정보는 기본적으로 전부 공개"를 확정하면서, 순위표의 보유종목
#     상세표가 평균매입가·현재가·평가손익·수익률·비중까지 함께 싣게 됐습니다. 그 다섯 지표는
#     앞의 다섯 문장 어디에도 적혀 있지 않던 값이라, **동의 문장에 없는 것을 공개하지 않기
#     위해**(§0-1) 항목을 조용히 늘리는 대신 체크박스를 하나 더 세웠습니다. 오너 지시 원문:
#     "동의 체크 항목에서 빠져 있는 내용이면 동의 체크 항목에 추가를 해야지".
#     ⚠️ 이 항목은 결투의 여섯 번째 동의(`consent_real_principal_bracket`)와 **성격이 다릅니다.**
#        그건 따로 켜고 끄는 독립 동의였지만, 이것은 앞의 다섯 개와 **같은 '전부 아니면 전무'
#        묶음**입니다(체크박스만 여섯 개이고, 최종 확인은 여섯 개가 전부 켜져야 눌립니다).
CONSENT_ITEM_SENTENCES = {
    "consent_rank": ("순위", "내 성적표의 순위가 공개 순위표에 표시됩니다."),
    "consent_return": ("수익률", "내 성적표의 수익률이 공개됩니다."),
    "consent_holdings": (
        "보유종목",
        "내가 실제로 보유한 종목이 순위표에서 다른 사람에게 개별 열람 가능하게 공개됩니다.",
    ),
    "consent_quantity": ("수량", "종목별로 내가 실제 보유한 수량이 공개됩니다."),
    "consent_buy_amount": ("매입금액", "종목별로 내가 실제 매입한 금액이 공개됩니다."),
    "consent_holding_details": (
        "종목별 상세지표",
        "종목별로 평균매입가·현재가·평가손익·수익률·비중까지 함께 공개됩니다.",
    ),
}

#: 화면 문구에 쓰는 **항목 개수**. 숫자를 문장 안에 글자로 박아 두면 항목이 늘어난 날
#: 사용자에게 그대로 거짓말이 됩니다(2026-08-23 에 5 → 6 으로 실제로 늘었습니다).
#: 세는 곳은 `CONSENT_ITEM_FLAGS` 한 곳뿐입니다(§0-3-10).
CONSENT_ITEM_COUNT = len(CONSENT_ITEM_FLAGS)

# =============================================================================
# 안내·책임 고지 문구
# =============================================================================
#: 🔴 이 화면이 다루는 것이 **실제 자산**이라는 사실. 맨 처음에, 다른 어떤 설명보다 먼저.
#:    (결투 화면에는 "가상계좌라서 실제 금액은 공개되지 않는다"는 안도의 문장이 있었습니다 —
#:     여기서는 정확히 반대라서, 그 자리를 비워두지 않고 반대 사실로 채웁니다, §0-1.)
NOTICE_REAL_DATA = (
    "🔴 여기서 공개되는 것은 가상의 성적이 아니라, '내 성적표'에 직접 등록하신 실제 "
    "보유 자산입니다.\n\n"
    "종목·수량·매입금액은 물론 종목별 평균매입가·현재가·평가손익·수익률·비중까지 그대로 "
    "다른 이용자에게 보입니다. 기본값은 비공개이고, 동의하지 않으시면 공개 순위표 "
    "어디에도 나타나지 않습니다."
)

#: 책임 고지 — **개별 체크박스 영역과 최종 확인 영역, 최소 두 곳**에 나옵니다.
#:  ✍️ 결투 화면(2026-08-22 오너 확정 문안)에서 **글자 그대로** 가져왔습니다. 이 세 문장에는
#:     가상계좌·계좌 같은 모듈 고유의 말이 하나도 없어서, 다시 쓰면 확정된 문안을 이유 없이
#:     흔드는 일이 됩니다(§0-3-10 — 같은 문장을 두 벌 만들지 않기).
NOTICE_RESPONSIBILITY = (
    "⚠️ 읽지 않고 동의하신 것도 본인 책임입니다.\n\n"
    "아래 항목에 동의하시면 그 내용이 다른 이용자에게 실제로 공개됩니다 — 무엇이 "
    "공개되는지 한 문장씩 직접 확인해 주세요.\n\n"
    "한 번 공개된 기록을 나중에 되돌릴 수 있게 하는 절차(철회)는 있지만, 그때까지 남이 "
    "이미 본 내용까지 되돌릴 수는 없습니다."
)

#: 전부-아니면-전무 규칙을 사용자에게 설명하는 문구.
NOTICE_ALL_OR_NOTHING = (
    f"이 {CONSENT_ITEM_COUNT}개 항목은 전부 공개하거나, 전부 공개하지 않거나 둘 중 "
    "하나입니다.\n\n"
    "'수익률만 공개하고 보유종목은 비공개' 같은 부분 조합은 제공하지 않습니다."
)

#: 최종 확인이 왜 따로 있는지.
NOTICE_FINAL_CONFIRM = (
    f"{CONSENT_ITEM_COUNT}개를 다 체크했다고 바로 공개되지 않습니다.\n\n"
    "아래에서 한 번 더 확인하셔야 그때부터 공개 순위표 발행 대상이 됩니다."
)

#: 🔴 체급(원금 구간)이 어떻게 정해지는지 + 시즌 고정 규칙.
#:
#:  결투 화면의 같은 이름 상수와 **말하는 내용이 다릅니다.** 결투에서는 체급의 입력이 "다른
#:  모듈에서 끌어오는 실제 매입총합"이라 별도의 동의가 필요했지만, 여기서는 그 입력이 바로
#:  위 항목들로 이미 공개하기로 한 값들의 합입니다. 그래서 이 문구는 "왜 **체급을 위한**
#:  별도 동의 항목이 없는가"를 함께 설명합니다 — 없는 항목을 그냥 안 그리고 넘어가면, 결투
#:  화면을 본 적 있는 사용자는 "체급 동의를 안 했는데 왜 체급이 정해졌지"라고 생각하게
#:  됩니다(§0-1).
#:  ⚠️ 2026-08-23 정정 — 이 설명은 **체급에 대한** 이야기입니다. 항목별 체크박스 자체는
#:     이날 6개가 됐고(`consent_holding_details`), 그 항목은 체급과 아무 관계가 없습니다.
#:     아래 본문의 "체급을 위한 별도의 동의 항목이 없습니다"는 여전히 사실이라 그대로 둡니다
#:     — 체급 계산 설명(시즌 고정·통화별 분리)도 한 글자도 바꾸지 않았습니다.
#:  숫자는 전부 `duel_rules` 상수에서 만듭니다(§0-3-10 — 시즌 길이를 여기 다시 적지 않기).
NOTICE_BRACKET_FIXED = (
    "순위는 '체급'(매입원가 구간) 안에서만 매겨집니다.\n\n"
    "체급은 지금 공개에 동의하시는 바로 그 데이터 — '내 성적표'의 종목별 매입금액 — 을 "
    "통화별로 합한 매입원가합계로 정해집니다. 그래서 체급을 위한 별도의 동의 항목이 "
    "없습니다: 매입금액을 공개하기로 하신 순간 그 합계는 공개된 값들을 더하기만 하면 나오는 "
    "값이라, 따로 동의를 받을 대상이 남아 있지 않기 때문입니다.\n\n"
    "매입원가합계 금액 자체를 숫자로 공개하지는 않고, 어느 구간에 속하는지만 씁니다.\n\n"
    "한 번 정해진 체급은 다음 시즌 전까지 바뀌지 않습니다. 시즌은 "
    f"{duel_rules.DUEL_SEASON_LENGTH_MONTHS}개월이고 매년 "
    f"{duel_rules.DUEL_SEASON_ANCHOR_MONTH}월 {duel_rules.DUEL_SEASON_ANCHOR_DAY}일에 "
    "새로 시작합니다.\n\n"
    "시즌 도중에 매입원가합계가 늘거나 줄어도 그 시즌 안에서는 처음 배정된 체급 그대로이고, "
    "순위는 그 체급 안에서 수익률로만 갈립니다.\n\n"
    "원화 보유분과 달러 보유분은 매입원가합계의 통화 자체가 다르므로 체급도 통화별로 따로 "
    "정해집니다 — 두 통화를 더하지 않습니다(이 앱에는 환율 시계열이 없습니다). 그 통화의 "
    f"보유종목이 하나도 없으면 '{duel_rules.BRACKET_NONE_LABEL}' 그룹입니다."
)

#: 🔴 원화 순위표와 달러 순위표는 별개의 표지만, **동의는 하나**라는 사실.
#:    결투에서는 트랙마다 동의 표가 달라 "한쪽만 공개"가 가능했습니다. 여기서는 아닙니다 —
#:    `scorecard_public_consent` 의 기본키가 `user_id` 하나이고, 철회도 통화를 가리지
#:    않습니다(`scorecard_publish_db.delete_published_rows_for_nicknames()` 독스트링).
#:    사용자가 "달러만 공개할 수 있겠지"라고 오해하면 안 되는 자리입니다(§0-1).
NOTICE_TRACKS_INDEPENDENT = (
    "※ 원화 순위표와 달러 순위표는 완전히 다른 표입니다.\n\n"
    "'내 성적표'에 국내 종목과 미국 종목을 함께 갖고 계시면 두 순위표에 각각 따로 실립니다 "
    "— 한 사람의 성적을 하나로 합치지 않습니다. 이 앱에는 환율 시계열이 없어서 두 통화를 "
    "한 줄에 세울 방법이 없기 때문입니다(없는 값을 지어내지 않습니다).\n\n"
    "다만 공개 동의 자체는 하나입니다. 통화별로 따로 동의하거나 한쪽만 철회하실 수는 "
    "없습니다 — 동의하시면 갖고 계신 두 통화가 모두 공개 대상이 되고, 철회하시면 두 쪽의 "
    "기록이 함께 지워집니다."
)

#: 🔴 닉네임은 **사람당 하나**입니다(통화별로 나눠 배정하지 않습니다 —
#:    `scorecard_publish_db.ensure_nickname(client, user_id)` 에 통화 인자가 없습니다).
#:    사용자가 모르고 동의하면 안 되는 사실이라 명시합니다(§0-1).
NOTICE_SHARED_NICKNAME = (
    "※ 닉네임은 한 사람에게 하나입니다(원화용·달러용으로 나눠 배정하지 않습니다).\n\n"
    "그래서 국내 종목과 미국 종목을 둘 다 갖고 계시면, 원화 순위표와 달러 순위표에 같은 "
    "닉네임이 실려서 보는 사람이 '이 두 줄은 같은 사람'이라고 알 수 있습니다.\n\n"
    "닉네임은 무작위로 뽑히며 한 번 정해지면 바꿀 수 없습니다. 닉네임 말고 사람을 특정할 수 "
    "있는 값(이메일·아이디·가입일)은 어느 순위표에도 저장조차 되지 않습니다."
)

# =============================================================================
# 철회 — 실수로 누르는 것을 막는 확인 단계가 필요합니다
# =============================================================================
#: 철회하면 무슨 일이 일어나는지. 숫자(3개월)는 `duel_rules.RECONSENT_BLOCK_MONTHS` 에서
#: 만들어 씁니다(§0-3-10).
NOTICE_REVOKE = (
    "철회하면 ① 발행돼 있던 공개 기록(과거 순위·과거 수익률·공개된 보유종목)이 숨김이 "
    "아니라 영구 삭제되고,\n\n"
    f"② 그 뒤 {duel_rules.RECONSENT_BLOCK_MONTHS}개월 동안 다시 동의할 수 없습니다.\n\n"
    "원화 순위표의 기록과 달러 순위표의 기록이 함께 지워집니다 — 한쪽만 남기는 철회는 "
    "없습니다.\n\n"
    "되돌리기가 아니라 처음부터 다시 시작하는 절차입니다."
)

#: 철회 즉시 사라지지 않는다는 사실(§0-1 — 조용히 넘기지 않습니다).
#: `scorecard_publish_db.revoke_consent()` 독스트링의 "최대 하루의 간격"을 그대로 옮긴 것입니다.
NOTICE_REVOKE_TIMING = (
    "실제 삭제는 다음 야간 발행 배치가 처리합니다 — 철회한 시점과 공개 기록이 실제로 "
    "사라지는 시점 사이에 최대 하루의 간격이 있습니다.\n\n"
    "그 사이에도 새로 발행되지는 않습니다."
)

#: 철회 확인 체크박스 문구. 버튼 하나로 끝나지 않게 하는 것이 요구사항입니다.
REVOKE_CONFIRM_LABEL = "위 내용(공개 기록 영구 삭제 · 3개월 재동의 차단)을 읽고 이해했습니다."


# =============================================================================
# 1. 순수 함수 — 화면 규칙 (위젯 없이 검증할 수 있게 따로 뺐습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장(§0-3-4)."""
    return fail_message(exc, fallback, context='내 성적표 공개 동의')


def consent_item_rows():
    """
    화면에 그릴 항목별 동의 6개를 `[(flag, 이름, 문장), ...]` 로.

    🔴 여기서 `scorecard_publish_db.CONSENT_ITEM_FLAGS` 와 **키·순서가 같은지** 확인합니다.
       어긋나면 화면을 그리지 않고 예외입니다 — "사용자가 본 문장"과 "실제로 저장되는 컬럼"이
       달라지는 것은 이 모듈에서 가장 나쁜 버그이고, 조용히 넘어가면 안 됩니다(§0-1).
       이 확인 하나가 "항목을 한쪽에만 슬쩍 끼워 넣거나 순서를 바꾸는" 변경도 함께
       막습니다(2026-08-23 에 여섯 번째 항목을 늘릴 때 실제로 두 상수를 함께 고쳤습니다).
    """
    if tuple(CONSENT_ITEM_SENTENCES) != tuple(CONSENT_ITEM_FLAGS):
        raise DuelRuleError(
            "동의 항목 문구 목록이 scorecard_publish_db.CONSENT_ITEM_FLAGS 와 다릅니다: "
            f"{tuple(CONSENT_ITEM_SENTENCES)} vs {tuple(CONSENT_ITEM_FLAGS)}"
        )
    return [(flag, CONSENT_ITEM_SENTENCES[flag][0], CONSENT_ITEM_SENTENCES[flag][1])
            for flag in CONSENT_ITEM_FLAGS]


def missing_item_labels(values):
    """아직 체크되지 않은 항목의 **이름** 목록(사용자에게 무엇이 빠졌는지 알려주기 위해)."""
    checked = dict(values or {})
    return [CONSENT_ITEM_SENTENCES[flag][0]
            for flag in CONSENT_ITEM_FLAGS if not checked.get(flag)]


def all_items_checked(values):
    """항목이 **전부** 체크됐는가('전부 아니면 전무'의 화면 쪽 판정)."""
    return not missing_item_labels(values)


def item_save_payload(values):
    """
    1층(항목별 전체) 저장용 인자 dict.

    🔴 이 payload 에는 **최종 확인이 들어가지 않습니다.** 두 가지를 각각 별개의 payload 로
       만드는 것이 "최종 확인은 분리된 단계"를 코드로 강제하는 방법입니다 — 하나의 dict 에
       다 담기 시작하면 어느 버튼이 무엇을 켜는지가 흐려집니다.
    """
    checked = dict(values or {})
    return {flag: bool(checked.get(flag)) for flag in CONSENT_ITEM_FLAGS}


def final_confirm_payload(values):
    """
    2층(최종 확인) 저장용 인자 dict — 항목 전부 True + `final_confirmed=True`.

    항목을 다시 넘기는 이유: `scorecard_publish_db.save_consent()` 는 **이번에 보낸 payload
    안에서** 항목이 전부 켜져 있는지를 봅니다(DB CHECK 와 같은 규칙을 앱에서 한 번 더 보는
    자리). 최종 확인만 따로 보내면 그 검사에 걸립니다 — 그리고 그게 맞는 동작입니다.
    """
    if not all_items_checked(values):
        raise DuelRuleError(
            f"최종 확인은 공개 항목 {CONSENT_ITEM_COUNT}개를 모두 체크했을 때만 할 수 있습니다"
            f" (아직 체크되지 않음: {', '.join(missing_item_labels(values))})."
        )
    payload = {flag: True for flag in CONSENT_ITEM_FLAGS}
    payload["final_confirmed"] = True
    return payload


def revoke_guard(confirmed):
    """
    철회 버튼을 눌러도 되는가. 확인 체크가 없으면 **사용자에게 보여줄 문장**을 돌려줍니다
    (None 이면 진행해도 좋다는 뜻).

    철회는 되돌릴 수 없고 3개월 재동의 차단이 따라붙으므로, 실수로 누르는 것을 막는 확인
    단계를 둡니다.
    """
    if confirmed:
        return None
    return (
        "🚫 철회하려면 위 확인란을 먼저 체크해 주세요 — 되돌릴 수 없는 작업이라 "
        "한 단계 더 두었습니다."
    )


def _kst_display(value):
    """저장된 시각(ISO 문자열 등) → 사람이 읽을 `'YYYY-MM-DD HH:MM (KST)'`.

    2026-08-29 재감사(스코어카드 모듈) L-3 — 예전엔 `str(state["final_confirmed_at"])` 를
    그대로 보여줘서 `2026-08-23T14:02:11.482913+09:00` 같은 내부 표현(ISO 8601 원문 +
    마이크로초)이 그대로 노출됐습니다(§0-3-4). `duel_rules._to_kst()`(이미 이 파일이 같은
    목적으로 쓰는 함수)로 파싱해 분 단위까지만 보여줍니다 — 시간대 표기는 반드시 남깁니다
    (§0-3-1). 파싱에 실패하면(값이 진짜로 이상하면) 값을 지어내지 않고 원본을 그대로
    보여줍니다(§0-1) — 화면이 죽는 것보다는 못생긴 원문이 낫습니다.
    """
    if not value:
        return ''
    try:
        moment = duel_rules._to_kst(value, "표시 시각")  # noqa: SLF001 - 같은 파일 관례상 허용
    except DuelRuleError:
        return str(value)
    return f"{moment.strftime('%Y-%m-%d %H:%M')} (KST)"


def consent_state(consent_row):
    """
    동의 행(없으면 None) → 화면이 그릴 **상태 요약** dict. 값을 지어내지 않습니다(§0-1).

    반환
        state        : "none"(기록 없음) / "revoked"(철회됨) /
                       "confirmed"(최종 확인까지 끝나 발행 대상) / "in_progress"(체크 중)
        items        : {flag: bool} — `CONSENT_ITEM_FLAGS` 전체
        final_confirmed_at / revoked_at : 원본 값(없으면 None)

    🔴 결투판에 있던 `real_principal` 키가 **없습니다.** 이 모듈에는 여섯 번째 동의가
       존재하지 않으므로(위 머리말 ②), 항상 False 인 키를 남겨 두면 화면에 "⬜ 실제 매입총합"
       같은 줄이 영원히 켜지지 않은 채로 남게 됩니다 — 사용자에게는 "내가 아직 안 켠 항목"
       으로 보입니다(§0-1).
    """
    row = dict(consent_row or {})
    items = {flag: bool(row.get(flag)) for flag in CONSENT_ITEM_FLAGS}
    if not consent_row:
        state = "none"
    elif row.get("revoked_at"):
        state = "revoked"
    elif row.get("final_confirmed"):
        state = "confirmed"
    else:
        state = "in_progress"
    return {
        "state": state,
        "items": items,
        "final_confirmed_at": row.get("final_confirmed_at"),
        "revoked_at": row.get("revoked_at"),
    }


def reconsent_notice(consent_row, now=None):
    """
    재동의가 막혀 있으면 **언제 풀리는지**까지 적힌 안내 문장, 아니면 None.

    ⚠️ 판정은 이 파일이 하지 않습니다 — `duel_rules.resolve_reconsent_block()` 이 3개월의
       단일 출처이고, 실제 거절도 `scorecard_publish_db.save_consent()` 가 같은 함수로
       합니다. 화면은 "눌러 보기 전에 미리 알려 주는" 역할만 합니다.
    """
    row = dict(consent_row or {})
    block = duel_rules.resolve_reconsent_block(row.get("revoked_at"), now)
    if not block["blocked"]:
        return None
    return (
        f"🚫 {block['revoked_at'].date().isoformat()} 에 공개 동의를 철회하셔서, "
        f"{block['unblocks_on'].isoformat()} 까지는 다시 동의하실 수 없습니다"
        f" (철회 후 {duel_rules.RECONSENT_BLOCK_MONTHS}개월). 그 날짜부터 이 화면에서 "
        "처음부터 다시 신청하실 수 있습니다."
    )


# =============================================================================
# 2. 페이지 (공개 플래그 게이트 → 로그인 게이트)
# =============================================================================
#  NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 이 화면은
#  동의 상태·닉네임 조회를 하므로 느린 날에는 기본값을 넘길 수 있고, 그러면 화면 대신
#  **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반). 값의 근거는
#  `web/state.PAGE_RESPONSE_TIMEOUT_SECONDS` 주석에 적혀 있습니다.
@ui.page('/scorecard/consent', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def scorecard_consent_page() -> None:
    with layout('💼 내 성적표 — 공개 동의'):
        ui.markdown('## 🔓 공개 동의 관리 — "내 밑으로 눈 깔어"')

        # ── 공개 게이트 ① 이 화면 전용 스위치 ② 관리자 전용 단계 ─────────────────
        #    (둘 다 `web/layout.py` 의 값 — 메뉴와 화면이 같은 상수 하나를 봅니다.)
        if not SCORECARD_CONSENT_ENABLED:
            _render_coming_soon()
            return
        if SCORECARD_CONSENT_MENU_ADMIN_ONLY and not is_admin():
            _render_coming_soon()
            return

        _render_header()

        status = supabase_status()
        if not status.available:
            warning_banner(
                '🚧 공개 동의 화면은 아직 준비중입니다.\n\n'
                f'사유: {status.reason}'
            )
            return

        # ── 로그인 게이트 (`scorecard_page.py` 와 같은 순서·같은 함수) ────────────
        if not has_supabase_session():
            render_auth()
            return

        # 🔴 세션 확인 두 단계를 **한 try 안**으로 모읍니다. 둘 다 Supabase 왕복이라
        #    "요청이 중단됨"으로 실패할 수 있는데, 그 실패를 "로그인 만료"로 오해해 멀쩡한
        #    토큰을 지워버리면 안 되기 때문입니다(§0-1).
        try:
            client = await get_client_async()
            if client is None:
                warning_banner('🚧 공개 동의 화면은 아직 준비중입니다(로그인 연결이 준비되지 않았습니다).')
                return
            user = await current_user_async(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return

        user_id = user_id_of(user)
        if not user_id:
            await logout_async()
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        try:
            await _render_body(client, user_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "화면을 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_coming_soon() -> None:
    """플래그가 꺼져 있거나 관리자 전용 단계일 때. 관리자 화면의 존재를 광고하지 않습니다."""
    warning_banner(
        '🚧 "내 밑으로 눈 깔어"(성적표 공개 순위표)는 아직 준비중입니다.\n\n'
        '준비가 끝나면 왼쪽 메뉴에 나타납니다. 그때까지 여러분의 성적표는 아무에게도 공개되지 '
        '않습니다 — 이 기능은 처음부터 끝까지 동의하신 분만 참여합니다.'
    )


def _render_header() -> None:
    ui.label(
        "'내 성적표'를 다른 이용자에게 공개할지 여기서 정합니다. 기본값은 비공개이고, "
        '동의하지 않으면 공개 순위표 어디에도 나타나지 않습니다.'
    ).classes('vh-muted')
    warning_banner(NOTICE_REAL_DATA)


# =============================================================================
# 3. 로그인 후 본문 — **카드 한 장** (계좌 루프 없음)
# =============================================================================
async def _render_body(client, user_id: str) -> None:
    """공개 동의 카드 한 장. `client`·`user_id` 는 **반드시 인자로** 받습니다(§0-3-8).

    🔴 결투 화면에 있던 `for account in mine:` 루프와 `_consent_section()` 팩토리가 여기에는
       없습니다 — "내 성적표"는 사용자당 포트폴리오 하나이므로 카드가 한 장뿐이고, 팩토리가
       피하려던 문제(루프 안에서 정의한 `@ui.refreshable` 의 `.refresh()` 가 마지막 반복
       객체로 풀리는 것)는 반복이 없으면 생기지 않습니다. 쓰이지 않는 우회 장치를 남겨두면
       다음 사람이 그 이유를 다시 조사하게 됩니다.

    🔴 Supabase 조회는 전부 `run_blocking()` 으로 별도 스레드에 넘깁니다. 동기 HTTP 왕복이
       이벤트 루프를 붙잡으면 **다른 화면을 보던 접속자까지** 함께 끊깁니다
       (`web/blocking.py` 모듈 독스트링).
    """
    ui.label(NOTICE_TRACKS_INDEPENDENT).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(NOTICE_SHARED_NICKNAME).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(
        f'※ 순위표는 참가자가 충분히 모인 그룹만 공개됩니다(같은 통화·같은 체급에 '
        f'{duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명 이상). 인원이 적은 그룹은 '
        '동의하셔도 순위표가 만들어지지 않습니다 — 사람이 적으면 닉네임만으로 누구인지 '
        '추측될 수 있기 때문입니다. 원화 순위표와 달러 순위표는 인원도 따로 셉니다.'
    ).classes('vh-muted vh-keep-all')

    # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
    #    직접 부를 때는 `await`, 처리기 쪽 `.refresh()` 는 동기 호출 그대로입니다.
    @ui.refreshable
    async def section() -> None:
        await _render_consent_card(client, user_id, section.refresh)

    await section()


async def _render_consent_card(client, user_id: str, on_changed) -> None:
    """동의 카드 — 현재 상태 → 1단계(항목별 전체) → 2단계(최종 확인) → 철회."""
    with ui.card().classes('vh-card w-full'):
        ui.markdown('##### 💼 내 성적표 공개 동의')

        try:
            consent_row = await run_blocking(fetch_my_consent, client, user_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "공개 동의 상태를 불러오지 못했습니다.")}')
            return

        state = consent_state(consent_row)
        nickname_row = None
        if state["state"] in ("in_progress", "confirmed"):
            # 철회 상태에서는 조회하지 않습니다 — 철회한 사용자의 공개용 별명을 다시 보여줄
            # 이유가 없습니다. (조회 자체는 만들지 않는 함수라 안전하지만, 안 부르는 편이
            # 더 좋습니다 — §0-3-8 은 "필요할 때만 만진다"도 포함합니다.)
            try:
                nickname_row = await run_blocking(fetch_my_nickname, client, user_id)
            except Exception as exc:               # noqa: BLE001
                error_banner(f'🚫 {_fail(exc, "닉네임을 불러오지 못했습니다.")}')

        _render_current_state(state, nickname_row)

        blocked_text = reconsent_notice(consent_row)
        if blocked_text:
            # 재동의 차단 중 — 새 동의 입력창을 아예 그리지 않습니다. 판정·거절의 최종
            # 권한은 `scorecard_publish_db.save_consent()` 에 있고(화면만 막으면 안 됩니다),
            # 여기서는 눌러 보기 전에 이유와 날짜를 알려 주는 것까지만 합니다.
            warning_banner(blocked_text)
            return

        if state["state"] == "confirmed":
            _render_revoke(client, user_id, on_changed)
            ui.separator()

        _render_consent_form(client, user_id, state, on_changed)


def _render_current_state(state: dict, nickname_row) -> None:
    """지금 어떤 상태인지 — 닉네임 · 항목별 on/off · 언제 동의했는지."""
    labels = {
        "none": '비공개 (공개 동의 기록이 없습니다)',
        # 이 문자열은 아래에서 `**현재 상태 — …**` 로 한 번 더 감싸입니다. 여기 안에 또
        # `**`를 넣으면 굵게 안에 굵게(중첩)가 되어 마크다운이 애매하게 해석되므로, 강조는
        # 바깥쪽 한 겹에만 맡깁니다.
        "in_progress": '비공개 (항목은 체크됐지만 최종 확인 전이라 아직 발행되지 않습니다)',
        "confirmed": '공개 신청 완료 (발행 대상)',
        "revoked": '철회됨',
    }
    ui.markdown(f'**현재 상태 — {labels.get(state["state"], state["state"])}**')

    # 🔐 닉네임은 서버가 무작위로 뽑은 값이라 사용자가 내용을 정할 수 없지만, 화면에 나가는
    #    값은 예외 없이 `esc()` 를 거칩니다(§0-3-9 — "이 값은 안전하다"는 판단이 코드에
    #    흩어지기 시작하면 언젠가 한 곳이 틀립니다). 결투 화면도 같은 규약이었습니다.
    nickname = (nickname_row or {}).get("nickname") if nickname_row else None
    if nickname:
        ui.label(f'공개 닉네임: {esc(str(nickname))}').classes('vh-keep-all')
        ui.label(
            '※ 순위표에는 이 닉네임만 나옵니다. 이메일·아이디·가입일 등 사람을 특정할 수 있는 '
            '값은 공개표에 저장조차 되지 않습니다. 닉네임은 무작위로 뽑히며 한 번 정해지면 '
            '바꿀 수 없습니다.'
        ).classes('vh-muted')
    elif state["state"] in ("in_progress", "confirmed"):
        ui.label('공개 닉네임: 아직 발급되지 않았습니다(동의를 저장하면 그때 발급됩니다).') \
            .classes('vh-muted')

    with ui.column().classes('gap-0'):
        for flag, name, _sentence in consent_item_rows():
            mark = '✅' if state["items"].get(flag) else '⬜'
            ui.label(f'{mark} {name}').classes('vh-muted')

    if state["final_confirmed_at"]:
        ui.label(f'최종 확인 시각: {esc(_kst_display(state["final_confirmed_at"]))}').classes('vh-muted')
    if state["revoked_at"]:
        ui.label(f'철회 시각: {esc(_kst_display(state["revoked_at"]))}').classes('vh-muted')


# =============================================================================
# 4. 1층(항목별 전체) + 2층(최종 확인)
# =============================================================================
def _render_consent_form(client, user_id: str, state: dict, on_changed) -> None:
    """항목별 체크박스 전체(`consent_item_rows()` 가 주는 만큼) → (전부 체크 시) 별도의
    최종 확인.

    ⚠️ 두 단계는 **저장 요청도 따로** 나갑니다(`item_save_payload()` / `final_confirm_payload()`).
       한 번에 보내면 "최종 확인이 분리된 단계"라는 요구가 화면 장식이 됩니다.
    """
    already = state["state"] == "confirmed"
    ui.markdown('#### 1단계 — 무엇을 공개할지 한 문장씩 확인')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 책임 고지 — 두 곳 중 **첫 번째**
    ui.label(NOTICE_ALL_OR_NOTHING).classes('vh-muted whitespace-pre-line')

    boxes = {}
    for flag, name, sentence in consent_item_rows():
        boxes[flag] = ui.checkbox(
            f'{name} — {sentence}',
            value=bool(state["items"].get(flag)),
        ).props('dense').classes('w-full vh-keep-all')

    ui.label(NOTICE_BRACKET_FIXED).classes('vh-muted vh-keep-all whitespace-pre-line')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _values():
        return {flag: bool(box.value) for flag, box in boxes.items()}

    async def _save_items() -> None:
        message.text = ''
        if not all_items_checked(_values()):
            # 부분 저장을 막습니다. `save_consent()` 는 중간 상태 저장 자체를 허용하지만
            # (체크하는 도중이 정상이라서), 화면이 굳이 "일부만 켜진 기록"을 남길 이유가
            # 없습니다 — 전부 아니면 전무가 이 모듈의 규칙입니다.
            message.text = (
                f'🚫 {CONSENT_ITEM_COUNT}개 항목을 모두 체크해 주세요. 아직 체크되지 않음: '
                + ', '.join(missing_item_labels(_values()))
                + '\n(부분 공개 조합은 제공하지 않습니다.)'
            )
            return
        await _save(client, user_id, item_save_payload(_values()), message, on_changed,
                    f'✅ 공개 항목 {CONSENT_ITEM_COUNT}개를 저장했습니다.'
                    ' 아래 2단계(최종 확인)까지 마쳐야 발행 대상이 됩니다.')

    # 2026-08-29 재감사 M-1 — save_consent 왕복이 있는 버튼입니다.
    _save_items_guarded = guard_double_click(_save_items)
    _save_items_guarded.bind_button(
        ui.button('1단계 저장 (아직 공개되지 않습니다)', on_click=_save_items_guarded)
        .props('no-caps outline')
    )

    # ── 2층 — 별도의 최종 확인 ────────────────────────────────────────────────
    ui.separator()
    ui.markdown('#### 2단계 — 최종 확인')
    ui.label(NOTICE_FINAL_CONFIRM).classes('vh-muted whitespace-pre-line')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 책임 고지 — 두 곳 중 **두 번째**

    if already:
        info_banner(
            '✅ 최종 확인까지 마친 상태입니다. 다음 발행 배치부터 순위표에 나타납니다'
            '(같은 그룹에 사람이 충분히 모였다면).'
        )
        return

    final_box = ui.checkbox(
        f'위 {CONSENT_ITEM_COUNT}개 항목 전부를 읽고 이해했으며, 내 성적표의 실제 보유 내역을 '
        '공개 순위표에 공개하는 데 최종적으로 동의합니다.'
    ).props('dense').classes('w-full vh-keep-all')
    final_message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    async def _save_final() -> None:
        final_message.text = ''
        if not final_box.value:
            final_message.text = '🚫 최종 확인란을 체크해 주세요 — 1단계와는 별개의 확인 절차입니다.'
            return
        try:
            payload = final_confirm_payload(_values())
        except DuelRuleError as exc:
            final_message.text = f'🚫 {exc}'
            return
        await _save(client, user_id, payload, final_message, on_changed,
                    '✅ 최종 확인이 끝났습니다. 다음 발행 배치부터 공개 순위표 대상이 됩니다.')

    # M-1 — save_consent + ensure_nickname 왕복이 있는 버튼입니다.
    _save_final_guarded = guard_double_click(_save_final)
    _save_final_guarded.bind_button(
        ui.button('🔓 최종 확인하고 공개 신청', on_click=_save_final_guarded)
        .props('no-caps color=primary')
    )


# =============================================================================
# 5. 철회 — 확인 단계 필수
# =============================================================================
def _render_revoke(client, user_id: str, on_changed) -> None:
    with ui.expansion('🚫 공개 동의 철회하기').classes('w-full'):
        warning_banner(NOTICE_REVOKE)
        ui.label(NOTICE_REVOKE_TIMING).classes('vh-muted whitespace-pre-line')
        confirm = ui.checkbox(REVOKE_CONFIRM_LABEL).props('dense').classes('w-full vh-keep-all')
        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _revoke() -> None:
            message.text = ''
            guard = revoke_guard(bool(confirm.value))
            if guard:
                message.text = guard
                return
            try:
                await run_blocking(revoke_consent, client, user_id)
            except (DuelDbError, DuelRuleError) as exc:
                message.text = f'🚫 {exc}'
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                text = _fail(exc, '철회를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
                message.text = f'🚫 {text}'
                ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
                return
            ui.notify(
                '✅ 공개 동의를 철회했습니다.\n'
                f'{NOTICE_REVOKE_TIMING}\n'
                f'{duel_rules.RECONSENT_BLOCK_MONTHS}개월 동안은 다시 동의하실 수 없습니다.',
                type='positive', multi_line=True, close_button='닫기', timeout=0,
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        # M-1 — revoke_consent 왕복이 있는 버튼입니다.
        _revoke_guarded = guard_double_click(_revoke)
        _revoke_guarded.bind_button(
            ui.button('철회합니다', on_click=_revoke_guarded).props('no-caps color=negative')
        )


# =============================================================================
# 6. 저장 공통 — 저장 성공 시에만 닉네임을 발급합니다
# =============================================================================
async def _save(client, user_id: str, payload: dict, message, on_changed,
                success_text: str) -> None:
    """
    `save_consent()` 호출 + 오류 표시 + (성공 시) 닉네임 발급.

    ── 순서가 설계의 일부입니다 ──────────────────────────────────────────────────
    **저장이 성공한 뒤에** `ensure_nickname()` 을 부릅니다. 반대로 하면, 3개월 재동의
    차단에 걸려 저장이 거절된 사용자에게도 닉네임이 만들어집니다 — 닉네임은 한 번 만들면
    바꿀 수 없으므로(스키마 §3-1 에 update 정책이 없습니다), "쓰지도 않을 이름을 영구히
    점유"하는 셈입니다. `ensure_nickname()` 은 멱등이라 두 번째 저장부터는 기존 이름을
    그대로 돌려줍니다.

    🔴 결투판과 달리 인자가 `(client, user_id)` 하나뿐입니다 — `scorecard_nicknames` 의
       기본키가 `user_id` 하나이고 통화·창유형 축이 없기 때문입니다
       (`scorecard_publish_db.ensure_nickname()` 독스트링).

    ⚠️ 닉네임 발급이 실패해도 **동의 저장은 이미 끝난 사실**입니다. 그 사실을 지우지 않고,
       "동의는 저장됐지만 닉네임 발급에 실패했다"고 정확히 알립니다(§0-1). 닉네임이 없는
       사용자는 발행 배치가 발행에서 빼고 로그에 남깁니다
       (`utils/scorecard_publish.py`) — 즉 이 실패로 잘못된 공개가 일어나지는 않습니다.
    """
    try:
        await run_blocking(save_consent, client, user_id, **payload)
    except (DuelDbError, DuelRuleError) as exc:
        # 이미 "사람이 읽을 한국어 한 문장"입니다(3개월 차단 안내 등) — 그대로 보여줍니다.
        message.text = f'🚫 {exc}'
        ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                  timeout=0, classes='whitespace-pre-line')
        return
    except Exception as exc:                       # noqa: BLE001
        text = _fail(exc, '동의를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
        message.text = f'🚫 {text}'
        ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
        return

    nickname_warning = ''
    try:
        await run_blocking(ensure_nickname, client, user_id)
    except Exception as exc:                       # noqa: BLE001
        nickname_warning = (
            '\n⚠️ 다만 공개 닉네임 발급에 실패했습니다: '
            f'{_fail(exc, "잠시 후 이 화면에서 다시 저장해 주세요.")}'
            '\n닉네임이 없으면 순위표에 실리지 않습니다 — 다시 저장하면 재시도합니다.'
        )

    ui.notify(success_text + nickname_warning, type='positive', multi_line=True,
              close_button='닫기', classes='text-lg whitespace-pre-line')
    on_changed()
