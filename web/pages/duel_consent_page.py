"""
⚔️ 결투다! — 2갈래 "내 밑으로 눈 깔어" **공개 동의 관리 화면** (로그인 필요, URL `/duel/consent`).

`DUEL_MODULE_WORK_ORDER.md` **5-2 · 5-5 · 5-8** 의 화면입니다. 판정·저장·차단은 전부 이미
완성된 계층이 합니다 — 이 파일은 **부르기만** 합니다.

    utils/duel_rules.py   3개월 재동의 차단 기간 · 최소 인원 같은 숫자의 단일 출처
    utils/duel_db.py      save_consent() / fetch_my_consent() / revoke_consent() /
                          ensure_nickname() / fetch_my_nickname()
    utils/duel_db_usd.py  save_consent_usd() / fetch_my_consent_usd() /
                          revoke_consent_usd() / fetch_my_accounts_usd()  ← 💵 2026-08-21
    ← 이 파일        화면 구조와 문구. **동의 규칙을 여기서 다시 구현하지 않습니다**(§0-3-10).

-------------------------------------------------------------------------------
💵 2026-08-21 — USD 트랙("달러 결투")이 이 화면에 함께 들어왔습니다 (§5-19)
-------------------------------------------------------------------------------
① **원화 무수정 원칙이 최우선.** 달러 계좌가 하나도 없는 사용자(= 오늘 실제 사용자 전원)는
   2026-08-21 이전과 **글자 그대로 같은 렌더 경로**를 탑니다(`_render_body()` 의 첫 분기).
   달러 계좌가 있을 때만 창유형마다 원화 카드 아래에 달러 카드가 한 장 더 붙습니다
   (§5-11-2 의 "위쪽 원화 / 아래쪽 달러" 를 `/duel` 화면(§5-18)과 같은 방식으로).
② **동의는 트랙별로 완전히 독립입니다**(5-11-10 오너 확정). 표부터 다릅니다
   (`duel_public_consent` ↔ `duel_public_consent_usd`) — 한쪽 동의·철회가 다른 쪽에 아무
   영향이 없고, 3개월 재동의 차단도 트랙별로 따로 셉니다. 네 가지 경우가 **전부 정상**
   입니다: ① 원화만 참여 ② 달러만 참여 ③ 둘 다 ④ 둘 다 미참여.
③ **닉네임만은 공유합니다**(5-11-10 · 스키마 §6). `duel_nicknames` 는 처음부터
   `(user_id, window_type)` 키라 같은 사용자의 같은 창유형이면 원화·달러가 **같은 닉네임
   문자열**을 씁니다. 그래서 이 화면은 `ensure_nickname()`/`fetch_my_nickname()` 을
   **접미사 없는 원본 그대로** 두 트랙에서 함께 부릅니다(`duel_nicknames_usd` 표는
   존재하지 않습니다 — USD 전용 닉네임 함수를 만드는 것 자체가 잘못된 모델입니다).
   🔴 그 결과 **두 트랙에 모두 공개 동의하면 두 순위표에 같은 닉네임이 실립니다** — 보는
   사람이 "이 두 줄은 같은 사람"이라고 알 수 있다는 뜻입니다. 오너가 확정한 설계이지만
   사용자가 모르고 동의하면 안 되는 사실이라 화면에 그대로 밝힙니다(§0-1 · 아래
   `NOTICE_SHARED_NICKNAME`).
④ **체급 기준 통화가 다릅니다.** 독립 동의(실제 매입총합 사용)를 켰을 때 원화 트랙은
   "내 성적표"의 **원화분** 매입원가합계로, 달러 트랙은 **달러분** 매입원가합계로 체급을
   정합니다(`duel_publish.summarize_real_principal()` ↔
   `duel_publish_usd.summarize_real_principal_usd()` — 서로 정확히 반대). 그래서 독립 동의
   설명 문구만은 원화 것을 재사용하지 않고 `NOTICE_REAL_PRINCIPAL_USD` 를 따로 뒀습니다.
⑤ **합산 숫자는 만들지 않습니다.** 이 화면에는 금액이 아예 없지만, 원칙은 같습니다 —
   원화 동의 상태와 달러 동의 상태를 하나로 뭉친 "전체 공개 여부" 같은 값을 만들지
   않습니다(만들면 한쪽만 철회한 사용자의 상태가 화면에서 사라집니다).

-------------------------------------------------------------------------------
🧱 왜 `duel_page.py` 에 이어 붙이지 않고 새 파일인가 (판단 근거를 남깁니다)
-------------------------------------------------------------------------------
① `web/pages/duel_page.py` 는 첫 줄부터 **"1갈래 '덤벼라 나 자신'"** 이라고 자기 범위를
   못 박은 파일이고 이미 1,076줄입니다. 공개 동의는 2갈래(공개 인프라)이고, 작업지시서는
   두 갈래를 "의존 방향이 한쪽뿐인" 별개 갈래로 설계했습니다(0단계 1번).
② `utils/duel_publish.py` 가 `utils/duel_batch.py` 와 갈라선 이유를 그대로 따릅니다 —
   *"공개 인프라를 혼자 읽고 리뷰할 수 있는 한 파일로 묶어 두면 §0-3-8 검토가 '이 파일만
   보면 된다'가 됩니다."* 이 프로젝트에서 가장 위험한 코드(§0-3-8)를 1갈래 화면 코드와
   섞으면, 앞으로 주문 폼을 손볼 때마다 공개 코드를 스치게 됩니다.
③ URL 도 화면도 다르고(`/duel` 는 계좌·주문, 여기는 동의), 공개 전환 스위치도 다릅니다
   (아래 게이트 참고 — 1갈래를 먼저 공개하고 2갈래는 나중에, 가 오너가 확정한 순서입니다).

-------------------------------------------------------------------------------
🚧 공개 게이트 — `duel_page.py` 와 **똑같은 3단계 패턴**, 다만 스위치가 다릅니다
-------------------------------------------------------------------------------
    DUEL_ENABLED                 … 1갈래 전체 스위치. 꺼져 있으면 2갈래도 존재할 수 없습니다
                                    (계좌가 없으면 공개할 성적도 없습니다).
    DUEL_CONSENT_ENABLED         … 이 화면 전용 스위치(기본 꺼짐, 환경변수).
    DUEL_CONSENT_MENU_ADMIN_ONLY … 관리자 전용 단계 ↔ 전체 공개를 가르는 불리언.

메뉴에서 감추는 것만으로는 부족합니다(주소를 아는 사람은 그냥 들어옵니다). 그래서 이
화면도 **같은 값을 직접 보고** 본문을 한 글자도 그리지 않습니다(벨트+멜빵).

-------------------------------------------------------------------------------
🔴 §0-3-8 — 이 화면이 지키는 것
-------------------------------------------------------------------------------
· 사용자 데이터는 모듈 전역에 두지 않습니다. 최상위에는 **문자열 상수뿐**입니다.
· DB 를 만지는 함수는 전부 `client` 와 `account_id` 를 인자로 받습니다("지금 누가
  로그인했는지"를 추측하지 않습니다).
· 계좌 카드를 그리기 전에 `account["user_id"] == user_id` 를 한 번 더 확인합니다.
· **화면을 그리는 행위는 아무것도 만들거나 바꾸지 않습니다** — 닉네임 조회는 만들지 않는
  `fetch_my_nickname()` 을 씁니다(`ensure_nickname()` 은 사용자가 실제로 동의를 저장한
  직후에만 부릅니다 — 5-5 의 발급 시점).

-------------------------------------------------------------------------------
📝 문구에 대하여 (✅ 2026-08-22 — 7-2 오너 검토 완료, 전체 공개 전환과 함께 확정)
-------------------------------------------------------------------------------
· **작업지시서에서 글자 그대로 가져온 문장**: 항목별 동의 5개(5-2-1), 독립 동의 1개
  (5-2-4). 이 6문장은 오너가 문안을 확정하기 전까지 **손대지 마세요.** 특히 보유종목
  문장의 "개별 열람" 은 오너가 명시적으로 요구한 문구 요소입니다.
· **그 밖의 안내·책임 고지 문구**(책임 고지·철회 안내 포함)는 오너가 직접 읽고 승인했습니다
  (2026-08-22 — 내용은 그대로, 문장 단위 줄바꿈과 렌더링 안 되던 `**` 표시 제거만 반영).
  이제 "초안"이 아니라 확정 문안입니다. 내용을 다시 바꿀 때는 여기 주석도 같이 갱신하세요.
"""

from nicegui import ui

from utils import duel_rules
from utils.duel_db import (
    CONSENT_ITEM_FLAGS,
    CONSENT_REAL_PRINCIPAL_FLAG,
    DuelDbError,
    ensure_nickname,
    fetch_my_accounts,
    fetch_my_consent,
    fetch_my_nickname,
    revoke_consent,
    save_consent,
)
from utils.duel_db_usd import (
    fetch_my_accounts_usd,
    fetch_my_consent_usd,
    revoke_consent_usd,
    save_consent_usd,
)
from utils.duel_rules import DuelRuleError
from utils.scorecard_db import supabase_status, user_id_of
from web.auth import (
    current_user_async,
    get_client_async,
    has_supabase_session,
    is_admin,
    logout_async,
)
from web.auth_ui import fail_message, render_auth
from web.blocking import run_blocking
from web.components import error_banner, esc, info_banner, warning_banner
from web.layout import (
    DUEL_CONSENT_ENABLED,
    DUEL_CONSENT_MENU_ADMIN_ONLY,
    DUEL_ENABLED,
    layout,
)
from web.state import PAGE_RESPONSE_TIMEOUT_SECONDS

# 계좌 유형 → 화면 이름. `duel_page.py::WINDOW_TITLES` 와 같은 값이지만 저 파일을 import
# 하지 않습니다 — 1갈래 화면 모듈에 걸린 의존(시세 파일 로딩 등)을 이 화면이 물려받지
# 않게 하려는 것입니다. 값이 어긋나면 곤란한 종류의 상수가 아닙니다(순수 라벨).
WINDOW_TITLES = {
    "M1": "1개월 계좌",
    "M3": "3개월 계좌",
    "M6": "6개월 계좌",
}

# =============================================================================
# 1층 — 항목별 개별 체크박스 5개 (작업지시서 5-2-1)
# =============================================================================
#  🔴 아래 5문장은 **작업지시서 5-2-1 에서 글자 그대로** 옮긴 것입니다. 요약·축약하거나
#     순서를 바꾸지 마세요. 특히 보유종목 문장의 **"개별 열람"** 은 오너가 명시적으로
#     요구한 문구 요소라고 작업지시서에 적혀 있습니다("이 문장에서 '개별 열람'을 빼지
#     마세요").
#  🔴 순서와 키는 `duel_db.CONSENT_ITEM_FLAGS` 와 **같아야 합니다.** 아래
#     `consent_item_rows()` 가 매번 그 사실을 확인합니다(§0-1 — 화면에 보이는 항목과
#     실제로 저장되는 항목이 어긋나면, 사용자는 자기가 동의하지 않은 것에 동의한 셈이
#     됩니다. 이 모듈에서 가장 나쁜 종류의 버그입니다).
CONSENT_ITEM_SENTENCES = {
    "consent_rank": ("순위", "내 순위가 공개 순위표에 표시됩니다."),
    "consent_return": ("수익률", "내 계좌의 수익률이 공개됩니다."),
    "consent_holdings": (
        "보유종목",
        "내 보유종목이 순위표에서 다른 사람에게 개별 열람 가능하게 공개됩니다.",
    ),
    "consent_quantity": ("수량", "종목별 보유 수량이 공개됩니다."),
    "consent_buy_amount": ("매입금액", "종목별 매입금액이 공개됩니다."),
}

#: 🔴 작업지시서 5-2-4 의 문장 **그대로**. 위 5개와 **절대 같은 묶음에 넣지 않습니다** —
#:    다른 모듈("내 성적표")의 **실제 금융 데이터**를 끌어오는 동의이고, 오너가 분리를
#:    명시적으로 확정한 지점입니다.
CONSENT_REAL_PRINCIPAL_SENTENCE = (
    "내 '내 성적표' 실제 매입총합을 순위표 원금 구간 산정에 사용합니다."
)

# =============================================================================
# 책임 고지 (작업지시서 5-2-5) — **개별 체크박스 영역과 최종 확인 영역, 최소 두 곳**
# =============================================================================
#  ⚠️ 정확한 문안은 7-2 에서 오너가 확정합니다. 아래는 **초안**이고, 요구사항 자체(두 곳
#     이상에 명확히 노출)는 지금 지킵니다 — "한 곳에만 작게 적어두는 걸로는 부족합니다".
#  ✍️ 2026-08-22 — 문장마다 `"\n\n"` 로 끊어 읽기 쉽게 했습니다(오너 요청). 뜻·순서·표현은
#     그대로이고 줄바꿈 위치만 넣었습니다. `duel_page.py::NOTICE_BUY_ONLY` 와 같은 관례입니다.
NOTICE_RESPONSIBILITY = (
    "⚠️ 읽지 않고 동의하신 것도 본인 책임입니다.\n\n"
    "아래 항목에 동의하시면 그 내용이 다른 이용자에게 실제로 공개됩니다 — 무엇이 "
    "공개되는지 한 문장씩 직접 확인해 주세요.\n\n"
    "한 번 공개된 기록을 나중에 되돌릴 수 있게 하는 절차(철회)는 있지만, 그때까지 남이 "
    "이미 본 내용까지 되돌릴 수는 없습니다."
)

#: 전부-아니면-전무 규칙(5-2-2)을 사용자에게 설명하는 문구. 초안입니다.
NOTICE_ALL_OR_NOTHING = (
    "이 5개 항목은 전부 공개하거나, 전부 공개하지 않거나 둘 중 하나입니다.\n\n"
    "'수익률만 공개하고 순위는 비공개' 같은 부분 조합은 제공하지 않습니다."
)

#: 최종 확인이 왜 따로 있는지(5-2-3). 초안입니다.
NOTICE_FINAL_CONFIRM = (
    "5개를 다 체크했다고 바로 공개되지 않습니다.\n\n"
    "아래에서 한 번 더 확인하셔야 그때부터 공개 순위표 발행 대상이 됩니다."
)

#: 독립 동의 설명(5-2-4 · 5-3). 초안이지만 "가상이 아니라 실제 데이터"라는 사실은 반드시
#: 남겨야 합니다(§0-1).
NOTICE_REAL_PRINCIPAL = (
    "이 동의만 다른 모듈('내 성적표')의 실제 보유 데이터를 사용합니다.\n\n"
    "위 5개 항목과는 완전히 별개이고, 따로 켜고 끌 수 있습니다.\n\n"
    "켜면 실제 매입원가합계로 '체급'(원금 구간)이 정해져 비슷한 규모끼리 겨루게 되고, "
    "끄면 체급 없이 '구간 미적용' 그룹에서 겨룹니다 — 끈다고 순위표에서 빠지지는 "
    "않습니다.\n\n"
    "실제 매입총합 금액 자체는 공개되지 않고, 어느 구간에 속하는지만 쓰입니다."
)

#: 💵 독립 동의 설명 — **달러 트랙 전용**(§5-19). 위 `NOTICE_REAL_PRINCIPAL` 을 그대로
#: 재사용하면 달러 사용자에게 "원화 매입총합으로 체급이 정해진다"고 읽힐 수 있는데,
#: 실제로는 정반대입니다 — `duel_publish_usd.summarize_real_principal_usd()` 는 "내 성적표"에
#: **달러가 아닌 통화가 하나라도 있으면** 합치지 않고 `FX_MIXED`(→ 구간 미적용)로 떨어뜨리고,
#: 달러분 매입원가합계로만 체급($750/$2,250/…)을 정합니다. 이 앱에는 환율 시계열이 없어
#: 두 통화를 더할 수 없기 때문입니다(§0-1 — 없는 값을 지어내지 않습니다).
NOTICE_REAL_PRINCIPAL_USD = (
    "이 동의만 다른 모듈('내 성적표')의 실제 보유 데이터를 사용합니다.\n\n"
    "위 5개 항목과는 완전히 별개이고, 따로 켜고 끌 수 있습니다.\n\n"
    "달러 순위표의 체급은 '내 성적표'의 달러 보유분 매입원가합계로만 정해집니다"
    "($750 · $2,250 · $3,750 · $7,500 · $22,500 · $45,000 · $75,000 경계).\n\n"
    "원화 종목을 하나라도 함께 갖고 계시면 두 통화를 더하지 않고 '구간 미적용' 그룹으로 "
    "갑니다 — 이 앱에는 환율 시계열이 없어서 합칠 수가 없습니다.\n\n"
    "끈다고 순위표에서 빠지지는 않고, 실제 매입총합 금액 자체는 공개되지 않습니다."
)

#: 💵 트랙 독립(5-11-10) — 원화·달러 동의는 서로 아무 관계가 없다는 사실.
NOTICE_TRACKS_INDEPENDENT = (
    "※ 원화 결투와 달러 결투의 공개 동의는 완전히 별개입니다.\n\n"
    "저장되는 표부터 다르고, 한쪽만 공개하셔도 되며, 한쪽을 철회해도 다른 쪽은 "
    "그대로입니다(철회 후 3개월 재동의 차단도 트랙마다 따로 셉니다).\n\n"
    "순위표도 원화·달러가 서로 완전히 다른 표입니다 — 두 통화의 성적을 섞거나 비교하지 "
    "않습니다."
)

#: 🔴 💵 닉네임 공유(5-11-10) — 사용자가 **모르고 동의하면 안 되는** 사실이라 명시합니다.
#:    같은 창유형이면 원화·달러가 같은 닉네임을 쓰므로, 두 트랙에 모두 공개하면 두 순위표의
#:    그 두 줄이 같은 사람이라는 것이 드러납니다. (교차 *사용자* 유출은 아닙니다 — 남의
#:    데이터는 어느 경로로도 흐르지 않습니다 — 하지만 공개 범위에 대한 정보이므로 §0-1.)
NOTICE_SHARED_NICKNAME = (
    "※ 닉네임은 같은 창유형이면 원화·달러가 같은 이름을 씁니다(한 사람에게 이름을 두 개 "
    "만들지 않습니다).\n\n"
    "그래서 같은 창유형의 원화와 달러를 둘 다 공개하시면, 두 순위표에 같은 닉네임이 "
    "실려서 보는 사람이 '이 두 줄은 같은 사람'이라고 알 수 있습니다.\n\n"
    "한쪽만 공개하시면 그런 연결은 생기지 않습니다.\n\n"
    "닉네임 말고 사람을 특정할 수 있는 값(이메일·아이디·가입일)은 어느 순위표에도 "
    "저장조차 되지 않습니다."
)

#: 체급 고정 규칙(5-3, 4·5차 확정). 숫자는 전부 `duel_rules` 상수에서 만듭니다(§0-3-10).
NOTICE_BRACKET_FIXED = (
    "한 번 정해진 체급은 다음 시즌 전까지 바뀌지 않습니다.\n\n"
    f"시즌은 {duel_rules.DUEL_SEASON_LENGTH_MONTHS}개월이고 매년 "
    f"{duel_rules.DUEL_SEASON_ANCHOR_MONTH}월 {duel_rules.DUEL_SEASON_ANCHOR_DAY}일에 "
    "새로 시작합니다.\n\n"
    "시즌 도중에 실제 매입총합이 늘거나 줄어도 그 시즌 안에서는 처음 배정된 체급 "
    "그대로이고, 순위는 그 체급 안에서 수익률로만 갈립니다."
)

# =============================================================================
# 철회 (작업지시서 5-8) — 실수로 누르는 것을 막는 확인 단계가 필요합니다
# =============================================================================
#: 철회하면 무슨 일이 일어나는지. 5-8-1 · 5-8-2 의 내용을 사용자 말로 옮긴 **초안**입니다.
#: 숫자(3개월)는 `duel_rules.RECONSENT_BLOCK_MONTHS` 에서 만들어 씁니다(§0-3-10).
NOTICE_REVOKE = (
    "철회하면 ① 발행돼 있던 공개 기록(과거 순위·과거 수익률·공개된 보유종목)이 숨김이 "
    "아니라 영구 삭제되고,\n\n"
    f"② 그 뒤 {duel_rules.RECONSENT_BLOCK_MONTHS}개월 동안 다시 동의할 수 없습니다.\n\n"
    "되돌리기가 아니라 처음부터 다시 시작하는 절차입니다."
)

#: 철회 즉시 사라지지 않는다는 사실(§0-1 — 조용히 넘기지 않습니다).
#: `utils/duel_db.py::revoke_consent()` 독스트링의 "최대 하루의 간격"을 그대로 옮긴 것입니다.
NOTICE_REVOKE_TIMING = (
    "실제 삭제는 다음 야간 발행 배치가 처리합니다 — 철회한 시점과 공개 기록이 실제로 "
    "사라지는 시점 사이에 최대 하루의 간격이 있습니다.\n\n"
    "그 사이에도 새로 발행되지는 않습니다."
)

#: 철회 확인 체크박스 문구(초안). 버튼 하나로 끝나지 않게 하는 것이 요구사항입니다.
REVOKE_CONFIRM_LABEL = "위 내용(공개 기록 영구 삭제 · 3개월 재동의 차단)을 읽고 이해했습니다."


# =============================================================================
# 1. 순수 함수 — 화면 규칙 (위젯 없이 검증할 수 있게 따로 뺐습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장(§0-3-4). `duel_page.py::_fail()` 과 같은 규약."""
    return fail_message(exc, fallback, context='결투다! 공개 동의')


def consent_item_rows():
    """
    화면에 그릴 항목별 동의 5개를 `[(flag, 이름, 문장), ...]` 로. 순서는 5-2-1 그대로입니다.

    🔴 여기서 `duel_db.CONSENT_ITEM_FLAGS` 와 **키·순서가 같은지** 확인합니다. 어긋나면
       화면을 그리지 않고 예외입니다 — "사용자가 본 문장"과 "실제로 저장되는 컬럼"이
       달라지는 것은 이 모듈에서 가장 나쁜 버그이고, 조용히 넘어가면 안 됩니다(§0-1).
    """
    if tuple(CONSENT_ITEM_SENTENCES) != tuple(CONSENT_ITEM_FLAGS):
        raise DuelRuleError(
            "동의 항목 문구 목록이 duel_db.CONSENT_ITEM_FLAGS 와 다릅니다: "
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
    """5개가 **전부** 체크됐는가(5-2-2 '전부 아니면 전무'의 화면 쪽 판정)."""
    return not missing_item_labels(values)


def item_save_payload(values):
    """
    1층(항목별 5개) 저장용 인자 dict.

    🔴 이 payload 에는 **최종 확인도, 독립 동의도 들어가지 않습니다.** 세 가지를 각각
       별개의 payload 로 만드는 것이 5-2 의 구조(1층 / 2층 / 완전히 별개인 독립 동의)를
       코드로 강제하는 방법입니다 — 하나의 dict 에 다 담기 시작하면 어느 버튼이 무엇을
       켜는지가 흐려지고, 언젠가 실제 자산 데이터 동의가 공개 동의에 딸려 들어갑니다.
    """
    checked = dict(values or {})
    payload = {flag: bool(checked.get(flag)) for flag in CONSENT_ITEM_FLAGS}
    _assert_no_real_principal(payload, "항목별 동의 저장")
    return payload


def final_confirm_payload(values):
    """
    2층(최종 확인) 저장용 인자 dict — 5개 전부 True + `final_confirmed=True`.

    5개를 다시 넘기는 이유: `duel_db.save_consent()` 는 **이번에 보낸 payload 안에서**
    5개가 전부 켜져 있는지를 봅니다(DB CHECK 와 같은 규칙을 앱에서 한 번 더 보는 자리).
    최종 확인만 따로 보내면 그 검사에 걸립니다 — 그리고 그게 맞는 동작입니다.

    🔴 여기서도 독립 동의는 넣지 않습니다.
    """
    if not all_items_checked(values):
        raise DuelRuleError(
            "최종 확인은 공개 항목 5개를 모두 체크했을 때만 할 수 있습니다"
            f" (아직 체크되지 않음: {', '.join(missing_item_labels(values))})."
        )
    payload = {flag: True for flag in CONSENT_ITEM_FLAGS}
    payload["final_confirmed"] = True
    _assert_no_real_principal(payload, "최종 확인 저장")
    return payload


def real_principal_payload(enabled):
    """
    독립 동의(실제 매입총합 사용) 저장용 인자 dict — **이 키 하나뿐**입니다.

    5개 항목과 같은 요청에 절대 섞지 않습니다(5-2-4). 켜고 끄는 것도 이 화면의 다른
    버튼과 완전히 독립입니다.
    """
    return {CONSENT_REAL_PRINCIPAL_FLAG: bool(enabled)}


def _assert_no_real_principal(payload, where):
    """공개 동의 payload 에 독립 동의가 섞여 들어갔는지 마지막으로 한 번 더 봅니다(5-2-4)."""
    if CONSENT_REAL_PRINCIPAL_FLAG in payload:
        raise DuelRuleError(
            f"{where} 요청에 독립 동의({CONSENT_REAL_PRINCIPAL_FLAG})가 섞여 있습니다 —"
            " 실제 자산 데이터 사용 동의는 공개 항목 5개와 같은 묶음이 될 수 없습니다(5-2-4)."
        )


def revoke_guard(confirmed):
    """
    철회 버튼을 눌러도 되는가. 확인 체크가 없으면 **사용자에게 보여줄 문장**을 돌려줍니다
    (None 이면 진행해도 좋다는 뜻).

    5-8 은 실수로 누르는 것을 막는 확인 단계를 요구합니다 — 철회는 되돌릴 수 없고
    3개월 재동의 차단이 따라붙기 때문입니다.
    """
    if confirmed:
        return None
    return (
        "🚫 철회하려면 위 확인란을 먼저 체크해 주세요 — 되돌릴 수 없는 작업이라 "
        "한 단계 더 두었습니다."
    )


def consent_state(consent_row):
    """
    동의 행(없으면 None) → 화면이 그릴 **상태 요약** dict. 값을 지어내지 않습니다(§0-1).

    반환
        state        : "none"(기록 없음) / "revoked"(철회됨) /
                       "confirmed"(최종 확인까지 끝나 발행 대상) / "in_progress"(체크 중)
        items        : {flag: bool} 5개
        real_principal : 독립 동의 on/off
        final_confirmed_at / revoked_at : 원본 값(없으면 None)
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
        "real_principal": bool(row.get(CONSENT_REAL_PRINCIPAL_FLAG)),
        "final_confirmed_at": row.get("final_confirmed_at"),
        "revoked_at": row.get("revoked_at"),
    }


def reconsent_notice(consent_row, now=None):
    """
    재동의가 막혀 있으면 **언제 풀리는지**까지 적힌 안내 문장, 아니면 None.

    ⚠️ 판정은 이 파일이 하지 않습니다 — `duel_rules.resolve_reconsent_block()` 이 3개월의
       단일 출처이고, 실제 거절도 `duel_db.save_consent()` 가 같은 함수로 합니다(5-8-2).
       화면은 "눌러 보기 전에 미리 알려 주는" 역할만 합니다.
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
# 🔴 2026-08-21 — `async def` + `response_timeout` 이 붙었습니다.
#    NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 이 화면은
#    계좌 3개 × (동의 상태·닉네임) 조회를 하므로 느린 날에는 3초를 넘길 수 있고, 그러면
#    화면 대신 **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반). 값의 근거는
#    `web/state.PAGE_RESPONSE_TIMEOUT_SECONDS` 주석에 적어 뒀습니다.
@ui.page('/duel/consent', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def duel_consent_page() -> None:
    with layout('⚔️ 결투다! — 공개 동의'):
        ui.markdown('## 🔓 공개 동의 관리 — "내 밑으로 눈 깔어"')

        # ── 공개 게이트 ① 1갈래가 꺼져 있으면 2갈래도 존재하지 않습니다 ──────────
        #    ② 이 화면 전용 스위치 ③ 관리자 전용 단계 (전부 `web/layout.py` 의 값)
        if not (DUEL_ENABLED and DUEL_CONSENT_ENABLED):
            _render_coming_soon()
            return
        if DUEL_CONSENT_MENU_ADMIN_ONLY and not is_admin():
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

        # ── 로그인 게이트 (`duel_page.py` 와 같은 순서·같은 함수) ────────────────
        if not has_supabase_session():
            render_auth()
            return

        # 🔴 2026-08-21 — 세션 확인 두 단계를 **한 try 안**으로 모았습니다. 둘 다 Supabase
        #    왕복이라 "요청이 중단됨"으로 실패할 수 있는데, 그 실패를 "로그인 만료"로
        #    오해해 멀쩡한 토큰을 지워버리면 안 되기 때문입니다(§0-1).
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
        '🚧 공개 순위표(2갈래 "내 밑으로 눈 깔어")는 아직 준비중입니다.\n\n'
        '준비가 끝나면 왼쪽 메뉴에 나타납니다. 그때까지 결투 성적은 아무에게도 공개되지 '
        '않습니다 — 이 기능은 처음부터 끝까지 동의하신 분만 참여합니다.'
    )


def _render_header() -> None:
    ui.label(
        '내 가상계좌 성적을 다른 이용자에게 공개할지 여기서 정합니다. 기본값은 비공개이고, '
        '동의하지 않으면 공개 순위표 어디에도 나타나지 않습니다.'
    ).classes('vh-muted')
    info_banner(
        'ℹ️ 여기서 공개되는 것은 결투다! 가상계좌의 성적입니다. 실제 보유 자산 금액이 '
        "그대로 공개되지는 않습니다(아래 '실제 매입총합' 항목만 예외적으로 실제 데이터를 "
        '쓰는데, 그것도 금액이 아니라 어느 구간인지만 씁니다).'
    )


# =============================================================================
# 3. 로그인 후 본문
# =============================================================================
async def _render_body(client, user_id: str) -> None:
    """계좌별 동의 카드. `client`·`user_id` 는 **반드시 인자로** 받습니다(§0-3-8).

    🔴 2026-08-21 — Supabase 조회를 전부 `run_blocking()` 으로 별도 스레드에 넘깁니다.
       계좌 목록 1회 + 계좌 3개 × (동의 상태·닉네임) = 최대 7회의 **동기 HTTP 왕복**이
       한 번 그릴 때마다 일어나고, 그동안 이벤트 루프가 멈추면 **다른 화면을 보던
       접속자까지** 함께 끊깁니다(`web/blocking.py` 모듈 독스트링).

    💵 2026-08-21(§5-19) — 원화 계좌와 달러 계좌를 **각각 따로** 조회하고 **각각 따로**
       소유자 이중 확인을 합니다. 달러 조회가 실패해도 원화 화면은 그대로 그립니다
       (한쪽 장애가 다른 쪽을 삼키지 않게 — `/duel` 화면 §5-18 과 같은 규약).
    """
    try:
        accounts = await run_blocking(fetch_my_accounts, client, user_id)
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "가상계좌를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    # 🔒 이중 방어 — 남의 행이 섞여 오면 아무것도 그리지 않습니다(§0-3-8).
    mine = [a for a in accounts if a.get("user_id") == user_id]
    if len(mine) != len(accounts):
        error_banner(
            '🚫 계좌 목록에 본인 것이 아닌 행이 섞여 있어 화면을 그리지 않았습니다. '
            '관리자에게 알려 주세요.'
        )
        return

    # ── 💵 달러 계좌를 **완전히 따로** 조회합니다 (다른 표·다른 함수) ────────────
    mine_usd = []
    try:
        accounts_usd = await run_blocking(fetch_my_accounts_usd, client, user_id)
    except Exception as exc:                       # noqa: BLE001
        accounts_usd = None
        error_banner(
            f'🚫 {_fail(exc, "달러 가상계좌를 불러오지 못했습니다. 원화 계좌는 아래에 그대로 표시됩니다.")}'
        )
    if accounts_usd is not None:
        # 🔒 원화와 **같은 이중 방어** — RLS 가 이미 막지만 한 번 더 확인합니다(§0-3-8).
        owned_usd = [a for a in accounts_usd if a.get("user_id") == user_id]
        if len(owned_usd) != len(accounts_usd):
            error_banner(
                '🚫 달러 계좌 목록에 본인 것이 아닌 행이 섞여 있어 달러 블록을 그리지 '
                '않았습니다. 관리자에게 알려 주세요.'
            )
        else:
            mine_usd = owned_usd

    if not mine and not mine_usd:
        # 🔴 §5-19 — 예전에는 `mine`(원화)만 보고 이 안내를 띄웠습니다. 그대로 두면 달러에만
        #    참여한 사용자가 "참여하지 않으셨습니다"를 보게 됩니다(§5-11-10 의 ② 경우).
        info_banner(
            'ℹ️ 아직 결투에 참여하지 않으셨습니다. 먼저 "⚔️ 참전하기" 화면에서 참여하시면 '
            '가상계좌 3개가 만들어지고, 그 뒤에 계좌별로 공개 여부를 정하실 수 있습니다.'
        )
        return

    usd_by_window = {a.get("window_type"): a for a in mine_usd}
    if usd_by_window:
        await _render_both_tracks(client, user_id, mine, usd_by_window)
        return

    # ── 원화 전용 — 2026-08-21 이전과 **완전히 동일한 렌더 경로** ────────────────
    #    (원화만 쓰는 사용자의 화면을 한 글자도 바꾸지 않기 위한 의도적인 두 경로 —
    #     `/duel` 화면의 `_render_accounts()` 가 같은 이유로 쓰는 방식입니다, §5-18.)
    ui.markdown(
        '#### 계좌마다 따로 정합니다\n'
        '공개 동의는 **계좌 단위**입니다. 예를 들어 6개월 계좌만 공개하고 나머지 둘은 '
        '비공개로 둘 수 있습니다. 계좌마다 서로 다른 무작위 닉네임이 발급되며, 닉네임끼리 '
        '같은 사람인지 알 수 있는 정보는 어디에도 공개되지 않습니다.'
    )
    ui.label(
        f'※ 순위표는 참가자가 충분히 모인 그룹만 공개됩니다(같은 창유형·같은 체급에 '
        f'{duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명 이상). 인원이 적은 그룹은 '
        '동의하셔도 순위표가 만들어지지 않습니다 — 사람이 적으면 닉네임만으로 누구인지 '
        '추측될 수 있기 때문입니다.'
    ).classes('vh-muted')

    for account in mine:
        # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
        #    직접 부를 때는 `await`, 처리기 쪽 `.refresh()` 는 동기 호출 그대로입니다.
        # 🔴 2026-08-22 — 예전에는 이 자리에서 `@ui.refreshable` 을 바로 정의했습니다.
        #    그러면 `.refresh()` 가 참조하는 이름이 **마지막 반복의 객체**로 풀려서
        #    (파이썬의 늦은 이름 결정), 계좌가 2개 이상일 때 두 번째 카드의 저장·철회가
        #    마지막 카드를 다시 그렸습니다. 달러 경로가 이미 쓰던 `_consent_section()`
        #    팩토리를 그대로 재사용해서 고칩니다(§0-3-10 — 새 함수를 만들지 않습니다).
        #    그리는 내용도, 넘기는 인자도 예전과 같습니다 — 갱신 대상만 제자리로.
        await _consent_section(_render_account_consent, client, user_id, account)()


# =============================================================================
# 3-b. 💵 원화 + 달러 병기 (§5-19 — §5-11-2 "위쪽 원화 / 아래쪽 달러")
# =============================================================================
def _consent_section(render_fn, client, user_id: str, account: dict):
    """동의 카드 하나를 감싼 `@ui.refreshable` 을 **팩토리로** 만들어 돌려줍니다.

    ⚠️ 왜 팩토리인가: `for` 루프 안에서 `@ui.refreshable` 을 바로 정의하면, 나중에
       `.refresh()` 로 다시 그릴 때 본문이 참조하는 이름이 **마지막 반복의 객체**로 풀립니다
       (파이썬의 늦은 이름 결정). 팩토리 안에서는 `section` 이 그 호출만의 지역 이름이라
       그 문제가 아예 생기지 않습니다.
    🔴 2026-08-22 — 원화 전용 경로(`_render_body()` 의 `for account in mine:`)도 이 팩토리를
       쓰도록 바꿨습니다. 예전 모양 그대로 두었던 그 루프에서 실제로 위 증상이 났습니다
       (계좌 2번 카드의 저장·철회가 3번 카드를 다시 그림). 화면에 그려지는 내용과 넘기는
       인자는 그대로이고, 갱신 대상만 제 카드로 돌아옵니다 — 원화 무수정 원칙(§5-19)이
       지키려는 것은 "사용자가 보는 화면"이지 버그가 아닙니다.
    """
    @ui.refreshable
    async def section() -> None:
        await render_fn(client, user_id, account, section.refresh)

    return section


async def _render_both_tracks(client, user_id: str, mine, usd_by_window: dict) -> None:
    """창유형(M1/M3/M6)마다 **위쪽에 원화 동의 카드, 아래쪽에 달러 동의 카드**.

    🔴 §5-11-10 — 네 경우가 전부 정상입니다. 이 함수가 그리는 것은 그중 ②(달러만)·③(둘 다)
       이고, 어느 창유형에서든 한쪽 계좌가 없는 상태(예: 원화 M1 만 있고 달러 M1 은 없음)도
       정상이라 **조용히 빼지 않고** "아직 없습니다"라고 적습니다(§0-1).
    🔴 원화 카드는 기존 `_render_account_consent()` 를 **그대로** 부릅니다(내용·문구 무수정).
       새로 생긴 것은 그 카드를 감싸는 칸과, 그 아래의 달러 카드뿐입니다.
    """
    krw_by_window = {a.get("window_type"): a for a in (mine or [])}

    ui.markdown(
        '#### 계좌마다 따로 정합니다 (원화·달러도 따로)\n'
        '공개 동의는 **계좌 단위**입니다. 예를 들어 6개월 계좌만 공개하고 나머지는 비공개로 '
        '둘 수 있습니다. 창유형(1·3·6개월)마다 원화 계좌와 달러 계좌가 **각각 별도 계좌**라, '
        '같은 칸의 위쪽이 원화 동의, 아래쪽이 달러 동의입니다.'
    )
    ui.label(NOTICE_TRACKS_INDEPENDENT).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(NOTICE_SHARED_NICKNAME).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(
        f'※ 순위표는 참가자가 충분히 모인 그룹만 공개됩니다(같은 창유형·같은 체급에 '
        f'{duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명 이상). 인원이 적은 그룹은 '
        '동의하셔도 순위표가 만들어지지 않습니다 — 사람이 적으면 닉네임만으로 누구인지 '
        '추측될 수 있기 때문입니다. 원화 순위표와 달러 순위표는 인원도 따로 셉니다.'
    ).classes('vh-muted')

    # 창유형 순서는 규칙 계층의 `ACCOUNT_WINDOW_TYPES`(M1→M3→M6). 목록에 없는 창유형이
    # 내려와도 **조용히 빼지 않고** 뒤에 이어 그립니다(§0-1 — `/duel` 화면과 같은 규약).
    known = list(duel_rules.ACCOUNT_WINDOW_TYPES)
    extra = [w for w in list(krw_by_window) + list(usd_by_window)
             if w not in known and w is not None]
    ordered = known + sorted(set(extra), key=str)

    for window_type in ordered:
        krw_account = krw_by_window.get(window_type)
        usd_account = usd_by_window.get(window_type)
        if krw_account is None and usd_account is None:
            continue
        title = WINDOW_TITLES.get(window_type, str(window_type))
        with ui.element('div').classes('w-full').style(
                'display: grid; gap: 12px; align-content: start;'):
            if krw_account is not None:
                await _consent_section(_render_account_consent, client, user_id, krw_account)()
            else:
                ui.label(
                    f'{title} — 원화 계좌는 아직 없습니다("⚔️ 참전하기" 화면에서 원화 결투에 '
                    '참여하시면 이 자리에 원화 동의 카드가 생깁니다).'
                ).classes('vh-muted vh-keep-all')
            if usd_account is not None:
                await _consent_section(_render_account_consent_usd, client, user_id,
                                       usd_account)()
            else:
                ui.label(
                    f'{title} — 달러 계좌는 아직 없습니다("⚔️ 참전하기" 화면에서 달러 결투에 '
                    '참여하시면 이 자리에 달러 동의 카드가 생깁니다).'
                ).classes('vh-muted vh-keep-all')


async def _render_account_consent(client, user_id: str, account: dict, on_changed) -> None:
    """계좌 1개의 동의 카드 — 현재 상태 → 1층 → 2층 → 독립 동의 → 철회."""
    if account.get("user_id") != user_id:          # 🔒 카드를 그리기 전에 한 번 더(§0-3-8)
        error_banner('🚫 소유자가 확인되지 않는 계좌라 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))

    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'##### ⚔️ {esc(title)}')

        try:
            consent_row = await run_blocking(fetch_my_consent, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "공개 동의 상태를 불러오지 못했습니다.")}')
            return

        state = consent_state(consent_row)
        nickname_row = None
        if state["state"] in ("in_progress", "confirmed"):
            # 철회 상태에서는 조회하지 않습니다 — 철회한 계좌의 공개용 별명을 다시 보여줄
            # 이유가 없습니다. (조회 자체는 만들지 않는 함수라 안전하지만, 안 부르는 편이
            # 더 좋습니다 — §0-3-8 은 "필요할 때만 만진다"도 포함합니다.)
            try:
                # 🔴 2026-08-20 USD 트랙(§5-11) 도입으로 닉네임 표가 (user_id, window_type)
                #    단위로 바뀌었습니다(스키마 §6 재구조화, 5-11-10 — 같은 사용자의 원화·
                #    달러 계좌가 같은 닉네임을 공유). 더 이상 account_id 로 조회하지 않습니다.
                nickname_row = await run_blocking(
                    fetch_my_nickname, client, account["user_id"], account["window_type"])
            except Exception as exc:               # noqa: BLE001
                error_banner(f'🚫 {_fail(exc, "닉네임을 불러오지 못했습니다.")}')

        _render_current_state(state, nickname_row)

        blocked_text = reconsent_notice(consent_row)
        if blocked_text:
            # 재동의 차단 중 — 새 동의 입력창을 아예 그리지 않습니다. 판정·거절의 최종
            # 권한은 `duel_db.save_consent()` 에 있고(5-8-2 "화면만 막으면 안 됩니다"),
            # 여기서는 눌러 보기 전에 이유와 날짜를 알려 주는 것까지만 합니다.
            warning_banner(blocked_text)
            return

        if state["state"] == "confirmed":
            _render_revoke(client, account_id, on_changed)
            ui.separator()

        _render_consent_form(client, account, state, on_changed)
        ui.separator()
        _render_real_principal_form(client, account, state, on_changed)


async def _render_account_consent_usd(client, user_id: str, account: dict, on_changed) -> None:
    """💵 달러 계좌 1개의 동의 카드 — `_render_account_consent()` 의 통화 미러(§5-19).

    🔴 위 원화 함수와 **다른 것은 네 가지뿐**입니다: ① 카드 제목 ② `fetch_my_consent_usd()`
       ③ 아래에서 부르는 세 함수가 전부 `_usd` 판 ④ 독립 동의 설명 문구
       (`NOTICE_REAL_PRINCIPAL_USD` — 체급 기준 통화가 다릅니다).
    🔴 **닉네임 조회만은 접미사 없는 원본**(`fetch_my_nickname`)입니다 — 원화·달러가 같은
       `duel_nicknames` 표를 공유하기 때문입니다(5-11-10 · 스키마 §6). `duel_nicknames_usd`
       라는 표는 존재하지 않고, 여기서 `_usd` 판을 찾아 만들면 "닉네임이 트랙마다 갈린다"는
       **틀린 모델**을 코드에 새기게 됩니다.
    """
    if account.get("user_id") != user_id:          # 🔒 카드를 그리기 전에 한 번 더(§0-3-8)
        error_banner('🚫 소유자가 확인되지 않는 계좌라 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))

    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'##### 💵 {esc(title)} (달러 결투)')

        try:
            consent_row = await run_blocking(fetch_my_consent_usd, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "공개 동의 상태를 불러오지 못했습니다.")}')
            return

        state = consent_state(consent_row)
        nickname_row = None
        if state["state"] in ("in_progress", "confirmed"):
            try:
                nickname_row = await run_blocking(
                    fetch_my_nickname, client, account["user_id"], account["window_type"])
            except Exception as exc:               # noqa: BLE001
                error_banner(f'🚫 {_fail(exc, "닉네임을 불러오지 못했습니다.")}')

        _render_current_state(state, nickname_row)

        blocked_text = reconsent_notice(consent_row)
        if blocked_text:
            # 재동의 차단은 **트랙별로 따로** 셉니다 — 이 안내는 달러 동의 기록의
            # `revoked_at` 만 보고 나옵니다(원화 철회는 여기에 영향이 없습니다, 5-11-10).
            warning_banner(blocked_text)
            return

        if state["state"] == "confirmed":
            _render_revoke_usd(client, account_id, on_changed)
            ui.separator()

        _render_consent_form_usd(client, account, state, on_changed)
        ui.separator()
        _render_real_principal_form_usd(client, account, state, on_changed)


def _render_current_state(state: dict, nickname_row) -> None:
    """지금 이 계좌가 어떤 상태인지 — 닉네임 · 항목별 on/off · 언제 동의했는지."""
    labels = {
        "none": '비공개 (공개 동의 기록이 없습니다)',
        # 🔴 2026-08-22 — 이 문자열은 806줄에서 이미 `**현재 상태 — …**` 로 한 번 더
        #    감싸입니다. 여기 안에 또 `**`를 넣으면 굵게 안에 굵게(중첩)가 되어 마크다운이
        #    애매하게 해석되므로, 강조는 바깥쪽 한 겹에만 맡기고 여기서는 뺍니다.
        "in_progress": '비공개 (항목은 체크됐지만 최종 확인 전이라 아직 발행되지 않습니다)',
        "confirmed": '공개 신청 완료 (발행 대상)',
        "revoked": '철회됨',
    }
    ui.markdown(f'**현재 상태 — {labels.get(state["state"], state["state"])}**')

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
        mark = '✅' if state["real_principal"] else '⬜'
        ui.label(f'{mark} 실제 매입총합을 체급 산정에 사용 (독립 동의)').classes('vh-muted')

    if state["final_confirmed_at"]:
        ui.label(f'최종 확인 시각: {esc(str(state["final_confirmed_at"]))}').classes('vh-muted')
    if state["revoked_at"]:
        ui.label(f'철회 시각: {esc(str(state["revoked_at"]))}').classes('vh-muted')


# =============================================================================
# 4. 1층(항목별 5개) + 2층(최종 확인) — 5-2-1 · 5-2-2 · 5-2-3
# =============================================================================
def _render_consent_form(client, account: dict, state: dict, on_changed) -> None:
    """항목별 체크박스 5개 → (5개 전부 체크 시) 별도의 최종 확인.

    ⚠️ 두 단계는 **저장 요청도 따로** 나갑니다(`item_save_payload()` / `final_confirm_payload()`).
       한 번에 보내면 "최종 확인이 분리된 단계"라는 5-2-3 의 요구가 화면 장식이 됩니다.

    🔴 2026-08-20 — 인자가 `account_id`(문자열)에서 `account`(딕셔너리)로 바뀌었습니다.
       `_save()`가 저장 성공 뒤 `ensure_nickname()`을 부를 때 이제 `user_id`·`window_type`도
       필요하기 때문입니다(USD 트랙과 닉네임을 공유하는 재구조화 — §5-11-10).
    """
    account_id = account.get("id")
    already = state["state"] == "confirmed"
    ui.markdown('#### 1단계 — 무엇을 공개할지 한 문장씩 확인')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 5-2-5 — 두 곳 중 **첫 번째**
    ui.label(NOTICE_ALL_OR_NOTHING).classes('vh-muted whitespace-pre-line')

    boxes = {}
    for flag, name, sentence in consent_item_rows():
        boxes[flag] = ui.checkbox(
            f'{name} — {sentence}',
            value=bool(state["items"].get(flag)),
        ).props('dense').classes('w-full vh-keep-all')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _values():
        return {flag: bool(box.value) for flag, box in boxes.items()}

    async def _save_items() -> None:
        message.text = ''
        if not all_items_checked(_values()):
            # 부분 저장을 막습니다. `duel_db.save_consent()` 는 중간 상태 저장 자체를
            # 허용하지만(체크하는 도중이 정상이라서), 화면이 굳이 "일부만 켜진 기록"을
            # 남길 이유가 없습니다 — 전부 아니면 전무가 이 모듈의 규칙입니다(5-2-2).
            message.text = (
                '🚫 5개 항목을 모두 체크해 주세요. 아직 체크되지 않음: '
                + ', '.join(missing_item_labels(_values()))
                + '\n(부분 공개 조합은 제공하지 않습니다.)'
            )
            return
        await _save(client, account, item_save_payload(_values()), message, on_changed,
                    '✅ 공개 항목 5개를 저장했습니다. 아래 2단계(최종 확인)까지 마쳐야 발행 대상이 됩니다.')

    ui.button('1단계 저장 (아직 공개되지 않습니다)', on_click=_save_items) \
        .props('no-caps outline')

    # ── 2층 — 별도의 최종 확인 (5-2-3) ────────────────────────────────────────
    ui.separator()
    ui.markdown('#### 2단계 — 최종 확인')
    ui.label(NOTICE_FINAL_CONFIRM).classes('vh-muted whitespace-pre-line')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 5-2-5 — 두 곳 중 **두 번째**

    if already:
        info_banner(
            '✅ 이 계좌는 최종 확인까지 마친 상태입니다. 다음 발행 배치부터 순위표에 '
            '나타납니다(같은 그룹에 사람이 충분히 모였다면).'
        )
        return

    final_box = ui.checkbox(
        '위 5개 항목 전부를 읽고 이해했으며, 내 결투 성적을 공개 순위표에 공개하는 데 '
        '최종적으로 동의합니다.'
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
        await _save(client, account, payload, final_message, on_changed,
                    '✅ 최종 확인이 끝났습니다. 다음 발행 배치부터 공개 순위표 대상이 됩니다.')

    ui.button('🔓 최종 확인하고 공개 신청', on_click=_save_final).props('no-caps color=primary')


def _render_real_principal_form(client, account: dict, state: dict, on_changed) -> None:
    """완전히 별개인 독립 동의(5-2-4). **위 5개와 같은 카드 묶음처럼 보이지 않게** 그립니다."""
    ui.markdown('#### 별개 항목 — 실제 매입총합을 체급 산정에 사용')
    ui.label(NOTICE_REAL_PRINCIPAL).classes('vh-muted whitespace-pre-line')
    ui.label(NOTICE_BRACKET_FIXED).classes('vh-muted whitespace-pre-line')

    box = ui.checkbox(
        CONSENT_REAL_PRINCIPAL_SENTENCE, value=bool(state["real_principal"]),
    ).props('dense').classes('w-full vh-keep-all')
    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    async def _save_flag() -> None:
        message.text = ''
        enabled = bool(box.value)
        await _save(client, account, real_principal_payload(enabled), message, on_changed,
                    '✅ 실제 매입총합 사용 동의를 켰습니다(체급이 배정됩니다).' if enabled
                    else '✅ 실제 매입총합 사용 동의를 껐습니다(다음 시즌부터 구간 미적용 그룹).')

    ui.button('이 항목만 저장', on_click=_save_flag).props('no-caps outline')
    ui.label(
        '※ 이 항목은 위 5개와 따로 저장됩니다. 켜지 않아도 순위표에는 참여할 수 있습니다.'
    ).classes('vh-muted')


# =============================================================================
# 4-b. 💵 달러 트랙의 1층 + 2층 + 독립 동의 (§5-19 — 위 두 함수의 통화 미러)
# =============================================================================
#  🔴 왜 인자 하나(`save_fn=`)를 붙여 원화 함수에 태우지 않고 복제했는가:
#     `utils/duel_publish_usd.py` 머리말이 적어 둔 이유가 그대로 적용됩니다 — 인자 하나를
#     빠뜨리면 **달러 동의가 원화 동의 표에 저장되는** 통로가 생기지만, 함수를 나누면 그
#     통로가 **존재하지 않습니다**(5-11-1 "완전 분리"). 이 트랙이 다섯 라운드에 걸쳐 쓴
#     같은 판단 기준이고, 원화 함수를 한 글자도 건드리지 않는다는 이번 라운드의 최우선
#     제약과도 맞습니다. 공유하는 것은 **순수 함수와 문구 상수**뿐입니다
#     (`consent_item_rows()`·`item_save_payload()`·`final_confirm_payload()`·
#      `real_principal_payload()`·`all_items_checked()`·`missing_item_labels()` ·
#      `NOTICE_*` — 전부 통화 리터럴이 본문에 없어서 그대로 재사용합니다).
def _render_consent_form_usd(client, account: dict, state: dict, on_changed) -> None:
    """💵 달러 트랙 항목별 체크박스 5개 → (전부 체크 시) 별도의 최종 확인.

    문구·규칙은 원화와 **완전히 같습니다**(5-2 는 통화와 무관한 요구사항입니다). 다른 것은
    저장이 `save_consent_usd()`(→ `duel_public_consent_usd` 표)로 나간다는 것뿐입니다.
    """
    already = state["state"] == "confirmed"
    ui.markdown('#### 1단계 — 무엇을 공개할지 한 문장씩 확인 (달러)')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 5-2-5 — 두 곳 중 **첫 번째**
    ui.label(NOTICE_ALL_OR_NOTHING).classes('vh-muted whitespace-pre-line')

    boxes = {}
    for flag, name, sentence in consent_item_rows():
        boxes[flag] = ui.checkbox(
            f'{name} — {sentence}',
            value=bool(state["items"].get(flag)),
        ).props('dense').classes('w-full vh-keep-all')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _values():
        return {flag: bool(box.value) for flag, box in boxes.items()}

    async def _save_items() -> None:
        message.text = ''
        if not all_items_checked(_values()):
            message.text = (
                '🚫 5개 항목을 모두 체크해 주세요. 아직 체크되지 않음: '
                + ', '.join(missing_item_labels(_values()))
                + '\n(부분 공개 조합은 제공하지 않습니다.)'
            )
            return
        await _save_usd(client, account, item_save_payload(_values()), message, on_changed,
                        '✅ 달러 결투의 공개 항목 5개를 저장했습니다. 아래 2단계(최종 확인)까지 '
                        '마쳐야 발행 대상이 됩니다.')

    ui.button('1단계 저장 (아직 공개되지 않습니다)', on_click=_save_items) \
        .props('no-caps outline')

    # ── 2층 — 별도의 최종 확인 (5-2-3) ────────────────────────────────────────
    ui.separator()
    ui.markdown('#### 2단계 — 최종 확인 (달러)')
    ui.label(NOTICE_FINAL_CONFIRM).classes('vh-muted whitespace-pre-line')
    warning_banner(NOTICE_RESPONSIBILITY)          # 🔴 5-2-5 — 두 곳 중 **두 번째**

    if already:
        info_banner(
            '✅ 이 달러 계좌는 최종 확인까지 마친 상태입니다. 다음 발행 배치부터 달러 '
            '순위표에 나타납니다(같은 그룹에 사람이 충분히 모였다면). 원화 순위표와는 '
            '아무 관계가 없습니다.'
        )
        return

    final_box = ui.checkbox(
        '위 5개 항목 전부를 읽고 이해했으며, 내 달러 결투 성적을 공개 순위표에 공개하는 '
        '데 최종적으로 동의합니다.'
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
        await _save_usd(client, account, payload, final_message, on_changed,
                        '✅ 최종 확인이 끝났습니다. 다음 발행 배치부터 달러 공개 순위표 '
                        '대상이 됩니다.')

    ui.button('🔓 최종 확인하고 달러 순위표 공개 신청', on_click=_save_final) \
        .props('no-caps color=primary')


def _render_real_principal_form_usd(client, account: dict, state: dict, on_changed) -> None:
    """💵 달러 트랙의 독립 동의(5-2-4).

    🔴 설명 문구만 원화와 다릅니다(`NOTICE_REAL_PRINCIPAL_USD`) — 체급 기준이 "내 성적표"의
       **달러 보유분** 매입원가합계이고, 원화 종목이 섞여 있으면 합치지 않고 '구간 미적용'
       으로 갑니다. 원화 문구를 그대로 쓰면 사실과 다른 안내가 됩니다(§0-1).
    """
    ui.markdown('#### 별개 항목 — 실제 **달러** 매입총합을 체급 산정에 사용')
    ui.label(NOTICE_REAL_PRINCIPAL_USD).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(NOTICE_BRACKET_FIXED).classes('vh-muted whitespace-pre-line')

    box = ui.checkbox(
        CONSENT_REAL_PRINCIPAL_SENTENCE, value=bool(state["real_principal"]),
    ).props('dense').classes('w-full vh-keep-all')
    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    async def _save_flag() -> None:
        message.text = ''
        enabled = bool(box.value)
        await _save_usd(client, account, real_principal_payload(enabled), message, on_changed,
                        '✅ 실제 매입총합 사용 동의를 켰습니다(달러 체급이 배정됩니다).' if enabled
                        else '✅ 실제 매입총합 사용 동의를 껐습니다(다음 시즌부터 구간 미적용 그룹).')

    ui.button('이 항목만 저장', on_click=_save_flag).props('no-caps outline')
    ui.label(
        '※ 이 항목은 위 5개와 따로 저장됩니다. 켜지 않아도 달러 순위표에는 참여할 수 있습니다.'
    ).classes('vh-muted')


# =============================================================================
# 5. 철회 (5-8) — 확인 단계 필수
# =============================================================================
def _render_revoke(client, account_id, on_changed) -> None:
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
                await run_blocking(revoke_consent, client, account_id)
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

        ui.button('철회합니다', on_click=_revoke).props('no-caps color=negative')


def _render_revoke_usd(client, account_id, on_changed) -> None:
    """💵 달러 트랙 철회 — `_render_revoke()` 의 통화 미러(§5-19).

    🔴 `revoke_consent_usd()` 는 `duel_public_consent_usd` 만 건드립니다. **원화 동의는
       그대로 남습니다**(5-11-10) — 그 사실을 화면에도 한 줄로 밝힙니다(§0-1: 한쪽만
       철회한 사용자가 "다 지워졌겠지" 하고 오해하면 안 됩니다).
    """
    with ui.expansion('🚫 달러 결투 공개 동의 철회하기').classes('w-full'):
        warning_banner(NOTICE_REVOKE)
        ui.label(NOTICE_REVOKE_TIMING).classes('vh-muted whitespace-pre-line')
        ui.label(
            '※ 이 철회는 달러 순위표에만 적용됩니다. 원화 결투의 공개 동의는 그대로 '
            '남고, 원화 순위표 기록도 지워지지 않습니다(원화도 그만두시려면 위쪽 원화 '
            '카드에서 따로 철회하셔야 합니다).'
        ).classes('vh-muted vh-keep-all')
        confirm = ui.checkbox(REVOKE_CONFIRM_LABEL).props('dense').classes('w-full vh-keep-all')
        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _revoke() -> None:
            message.text = ''
            guard = revoke_guard(bool(confirm.value))
            if guard:
                message.text = guard
                return
            try:
                await run_blocking(revoke_consent_usd, client, account_id)
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
                '✅ 달러 결투의 공개 동의를 철회했습니다(원화 동의는 그대로입니다).\n'
                f'{NOTICE_REVOKE_TIMING}\n'
                f'{duel_rules.RECONSENT_BLOCK_MONTHS}개월 동안은 달러 트랙에 다시 동의하실 수 '
                '없습니다.',
                type='positive', multi_line=True, close_button='닫기', timeout=0,
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        ui.button('달러 동의를 철회합니다', on_click=_revoke).props('no-caps color=negative')


# =============================================================================
# 6. 저장 공통 — 저장 성공 시에만 닉네임을 발급합니다 (5-5)
# =============================================================================
async def _save(client, account: dict, payload: dict, message, on_changed, success_text: str) -> None:
    """
    `save_consent()` 호출 + 오류 표시 + (성공 시) 닉네임 발급.

    ── 순서가 설계의 일부입니다 (5-5) ────────────────────────────────────────────
    **저장이 성공한 뒤에** `ensure_nickname()` 을 부릅니다. 반대로 하면, 3개월 재동의
    차단에 걸려 저장이 거절된 사용자에게도 닉네임이 만들어집니다 — 닉네임은 한 번 만들면
    바꿀 수 없으므로(스키마 §9-6), "쓰지도 않을 이름을 영구히 점유"하는 셈입니다.
    `ensure_nickname()` 은 멱등이라 두 번째 저장부터는 기존 이름을 그대로 돌려줍니다.

    ⚠️ 닉네임 발급이 실패해도 **동의 저장은 이미 끝난 사실**입니다. 그 사실을 지우지 않고,
       "동의는 저장됐지만 닉네임 발급에 실패했다"고 정확히 알립니다(§0-1). 닉네임이 없는
       계좌는 발행 배치가 발행에서 빼고 로그에 남깁니다(`utils/duel_publish.py`) — 즉
       이 실패로 잘못된 공개가 일어나지는 않습니다.

    🔴 2026-08-20 — 인자가 `account_id`(문자열)에서 `account`(딕셔너리)로 바뀌었습니다.
       `save_consent()`는 여전히 계좌 id 하나만 필요하지만, `ensure_nickname()`은
       이제 `(user_id, window_type)`로 조회합니다(USD 트랙과 닉네임을 공유하는 재구조화
       — 스키마 §6, §5-11-10). 계좌 id 하나로는 그 두 값을 알 수 없어 dict 전체를 받습니다.
    """
    account_id = account.get("id")
    try:
        # 🔴 2026-08-21 — 저장·닉네임 발급 둘 다 Supabase 왕복입니다. **순서는 그대로**
        #    (저장 성공 뒤에만 닉네임 발급)이고, 각 왕복이 이벤트 루프 밖에서 돌 뿐입니다.
        await run_blocking(save_consent, client, account_id, **payload)
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
        await run_blocking(
            ensure_nickname, client, account.get("user_id"), account.get("window_type"))
    except Exception as exc:                       # noqa: BLE001
        nickname_warning = (
            '\n⚠️ 다만 공개 닉네임 발급에 실패했습니다: '
            f'{_fail(exc, "잠시 후 이 화면에서 다시 저장해 주세요.")}'
            '\n닉네임이 없으면 순위표에 실리지 않습니다 — 다시 저장하면 재시도합니다.'
        )

    ui.notify(success_text + nickname_warning, type='positive', multi_line=True,
              close_button='닫기', classes='text-lg whitespace-pre-line')
    on_changed()


# =============================================================================
# 6-b. 💵 달러 트랙 저장 공통 (§5-19 — `_save()` 의 통화 미러)
# =============================================================================
async def _save_usd(client, account: dict, payload: dict, message, on_changed,
                    success_text: str) -> None:
    """
    `save_consent_usd()` 호출 + 오류 표시 + (성공 시) 닉네임 발급.

    🔴 원화 `_save()` 와 **다른 것은 저장 함수 한 개뿐**입니다
       (`save_consent` → `save_consent_usd`, 즉 `duel_public_consent_usd` 표).
       순서(저장 성공 뒤에만 닉네임 발급 — 5-5), 실패 처리, "동의는 저장됐지만 닉네임
       발급에 실패했다"는 정직한 안내(§0-1)는 전부 같습니다.

    🔴 **닉네임 발급은 접미사 없는 `ensure_nickname()` 그대로**입니다 — `duel_nicknames` 는
       원화·달러가 공유하는 유일한 표이고(5-11-10 · 스키마 §6), 인자도 계좌 id 가 아니라
       `(user_id, window_type)` 입니다. 그래서 같은 사용자의 같은 창유형이면 원화에서 이미
       발급받은 이름을 **그대로 다시 받습니다**(멱등) — 달러라고 새 이름이 생기지 않습니다.
    """
    account_id = account.get("id")
    try:
        await run_blocking(save_consent_usd, client, account_id, **payload)
    except (DuelDbError, DuelRuleError) as exc:
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
        await run_blocking(
            ensure_nickname, client, account.get("user_id"), account.get("window_type"))
    except Exception as exc:                       # noqa: BLE001
        nickname_warning = (
            '\n⚠️ 다만 공개 닉네임 발급에 실패했습니다: '
            f'{_fail(exc, "잠시 후 이 화면에서 다시 저장해 주세요.")}'
            '\n닉네임이 없으면 순위표에 실리지 않습니다 — 다시 저장하면 재시도합니다.'
        )

    ui.notify(success_text + nickname_warning, type='positive', multi_line=True,
              close_button='닫기', classes='text-lg whitespace-pre-line')
    on_changed()
