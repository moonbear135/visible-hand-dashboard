"""
⚔️ 결투다! — 2갈래 "내 밑으로 눈 깔어" **공개 동의 관리 화면** (로그인 필요, URL `/duel/consent`).

`DUEL_MODULE_WORK_ORDER.md` **5-2 · 5-5 · 5-8** 의 화면입니다. 판정·저장·차단은 전부 이미
완성된 계층이 합니다 — 이 파일은 **부르기만** 합니다.

    utils/duel_rules.py   3개월 재동의 차단 기간 · 최소 인원 같은 숫자의 단일 출처
    utils/duel_db.py      save_consent() / fetch_my_consent() / revoke_consent() /
                          ensure_nickname() / fetch_my_nickname()
    ← 이 파일        화면 구조와 문구. **동의 규칙을 여기서 다시 구현하지 않습니다**(§0-3-10).

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
📝 문구에 대하여 (7-2 — 오너 최종 검토 대기)
-------------------------------------------------------------------------------
· **작업지시서에서 글자 그대로 가져온 문장**: 항목별 동의 5개(5-2-1), 독립 동의 1개
  (5-2-4). 이 6문장은 오너가 문안을 확정하기 전까지 **손대지 마세요.** 특히 보유종목
  문장의 "개별 열람" 은 오너가 명시적으로 요구한 문구 요소입니다.
· **그 밖의 안내·책임 고지 문구는 전부 초안입니다.** 7-2 에서 오너가 직접 읽고 승인해야
  합니다("법적·신뢰 측면에서 오너가 직접 읽고 승인해야 합니다" — 작업지시서 7-2).
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
from utils.duel_rules import DuelRuleError
from utils.scorecard_db import current_user, supabase_status, user_id_of
from web.auth import get_client, has_supabase_session, is_admin, logout
from web.auth_ui import fail_message, render_auth
from web.components import error_banner, esc, info_banner, warning_banner
from web.layout import (
    DUEL_CONSENT_ENABLED,
    DUEL_CONSENT_MENU_ADMIN_ONLY,
    DUEL_ENABLED,
    layout,
)

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
NOTICE_RESPONSIBILITY = (
    "⚠️ 읽지 않고 동의하신 것도 본인 책임입니다. 아래 항목에 동의하시면 그 내용이 다른 "
    "이용자에게 실제로 공개됩니다 — 무엇이 공개되는지 한 문장씩 직접 확인해 주세요. "
    "한 번 공개된 기록을 나중에 되돌릴 수 있게 하는 절차(철회)는 있지만, 그때까지 남이 "
    "이미 본 내용까지 되돌릴 수는 없습니다."
)

#: 전부-아니면-전무 규칙(5-2-2)을 사용자에게 설명하는 문구. 초안입니다.
NOTICE_ALL_OR_NOTHING = (
    "이 5개 항목은 전부 공개하거나, 전부 공개하지 않거나 둘 중 하나입니다. "
    "'수익률만 공개하고 순위는 비공개' 같은 부분 조합은 제공하지 않습니다."
)

#: 최종 확인이 왜 따로 있는지(5-2-3). 초안입니다.
NOTICE_FINAL_CONFIRM = (
    "5개를 다 체크했다고 바로 공개되지 않습니다. 아래에서 **한 번 더** 확인하셔야 그때부터 "
    "공개 순위표 발행 대상이 됩니다."
)

#: 독립 동의 설명(5-2-4 · 5-3). 초안이지만 "가상이 아니라 실제 데이터"라는 사실은 반드시
#: 남겨야 합니다(§0-1).
NOTICE_REAL_PRINCIPAL = (
    "이 동의만 **다른 모듈('내 성적표')의 실제 보유 데이터**를 사용합니다. 위 5개 항목과는 "
    "완전히 별개이고, 따로 켜고 끌 수 있습니다. 켜면 실제 매입원가합계로 '체급'(원금 구간)이 "
    "정해져 비슷한 규모끼리 겨루게 되고, 끄면 체급 없이 '구간 미적용' 그룹에서 겨룹니다 — "
    "끈다고 순위표에서 빠지지는 않습니다. 실제 매입총합 **금액 자체는 공개되지 않고**, "
    "어느 구간에 속하는지만 쓰입니다."
)

#: 체급 고정 규칙(5-3, 4·5차 확정). 숫자는 전부 `duel_rules` 상수에서 만듭니다(§0-3-10).
NOTICE_BRACKET_FIXED = (
    f"한 번 정해진 체급은 다음 시즌 전까지 바뀌지 않습니다. 시즌은 "
    f"{duel_rules.DUEL_SEASON_LENGTH_MONTHS}개월이고 매년 "
    f"{duel_rules.DUEL_SEASON_ANCHOR_MONTH}월 {duel_rules.DUEL_SEASON_ANCHOR_DAY}일에 "
    "새로 시작합니다. 시즌 도중에 실제 매입총합이 늘거나 줄어도 그 시즌 안에서는 처음 "
    "배정된 체급 그대로이고, 순위는 그 체급 안에서 수익률로만 갈립니다."
)

# =============================================================================
# 철회 (작업지시서 5-8) — 실수로 누르는 것을 막는 확인 단계가 필요합니다
# =============================================================================
#: 철회하면 무슨 일이 일어나는지. 5-8-1 · 5-8-2 의 내용을 사용자 말로 옮긴 **초안**입니다.
#: 숫자(3개월)는 `duel_rules.RECONSENT_BLOCK_MONTHS` 에서 만들어 씁니다(§0-3-10).
NOTICE_REVOKE = (
    f"철회하면 ① 발행돼 있던 공개 기록(과거 순위·과거 수익률·공개된 보유종목)이 "
    f"**숨김이 아니라 영구 삭제**되고, ② 그 뒤 "
    f"**{duel_rules.RECONSENT_BLOCK_MONTHS}개월 동안 다시 동의할 수 없습니다.** "
    "되돌리기가 아니라 처음부터 다시 시작하는 절차입니다."
)

#: 철회 즉시 사라지지 않는다는 사실(§0-1 — 조용히 넘기지 않습니다).
#: `utils/duel_db.py::revoke_consent()` 독스트링의 "최대 하루의 간격"을 그대로 옮긴 것입니다.
NOTICE_REVOKE_TIMING = (
    "실제 삭제는 다음 야간 발행 배치가 처리합니다 — 철회한 시점과 공개 기록이 실제로 "
    "사라지는 시점 사이에 **최대 하루의 간격**이 있습니다. 그 사이에도 새로 발행되지는 "
    "않습니다."
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
@ui.page('/duel/consent')
def duel_consent_page() -> None:
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

        try:
            client = get_client()
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return
        if client is None:
            warning_banner('🚧 공개 동의 화면은 아직 준비중입니다(로그인 연결이 준비되지 않았습니다).')
            return

        user = current_user(client)
        user_id = user_id_of(user)
        if not user_id:
            logout()
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        try:
            _render_body(client, user_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "화면을 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_coming_soon() -> None:
    """플래그가 꺼져 있거나 관리자 전용 단계일 때. 관리자 화면의 존재를 광고하지 않습니다."""
    warning_banner(
        '🚧 공개 순위표(2갈래 "내 밑으로 눈 깔어")는 아직 준비중입니다.\n\n'
        '준비가 끝나면 왼쪽 메뉴에 나타납니다. 그때까지 결투 성적은 **아무에게도 공개되지 '
        '않습니다** — 이 기능은 처음부터 끝까지 동의하신 분만 참여합니다.'
    )


def _render_header() -> None:
    ui.label(
        '내 가상계좌 성적을 다른 이용자에게 공개할지 여기서 정합니다. 기본값은 비공개이고, '
        '동의하지 않으면 공개 순위표 어디에도 나타나지 않습니다.'
    ).classes('vh-muted')
    info_banner(
        'ℹ️ 여기서 공개되는 것은 **결투다! 가상계좌의 성적**입니다. 실제 보유 자산 금액이 '
        "그대로 공개되지는 않습니다(아래 '실제 매입총합' 항목만 예외적으로 실제 데이터를 "
        '쓰는데, 그것도 금액이 아니라 어느 구간인지만 씁니다).'
    )


# =============================================================================
# 3. 로그인 후 본문
# =============================================================================
def _render_body(client, user_id: str) -> None:
    """계좌별 동의 카드. `client`·`user_id` 는 **반드시 인자로** 받습니다(§0-3-8)."""
    try:
        accounts = fetch_my_accounts(client, user_id)
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

    if not mine:
        info_banner(
            'ℹ️ 아직 결투에 참여하지 않으셨습니다. 먼저 "⚔️ 참전하기" 화면에서 참여하시면 '
            '가상계좌 3개가 만들어지고, 그 뒤에 계좌별로 공개 여부를 정하실 수 있습니다.'
        )
        return

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
        @ui.refreshable
        def account_section(account=account) -> None:
            _render_account_consent(client, user_id, account, account_section.refresh)

        account_section()


def _render_account_consent(client, user_id: str, account: dict, on_changed) -> None:
    """계좌 1개의 동의 카드 — 현재 상태 → 1층 → 2층 → 독립 동의 → 철회."""
    if account.get("user_id") != user_id:          # 🔒 카드를 그리기 전에 한 번 더(§0-3-8)
        error_banner('🚫 소유자가 확인되지 않는 계좌라 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))

    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'##### ⚔️ {esc(title)}')

        try:
            consent_row = fetch_my_consent(client, account_id)
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
                nickname_row = fetch_my_nickname(client, account["user_id"], account["window_type"])
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


def _render_current_state(state: dict, nickname_row) -> None:
    """지금 이 계좌가 어떤 상태인지 — 닉네임 · 항목별 on/off · 언제 동의했는지."""
    labels = {
        "none": '비공개 (공개 동의 기록이 없습니다)',
        "in_progress": '비공개 (항목은 체크됐지만 **최종 확인 전**이라 아직 발행되지 않습니다)',
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
    ui.label(NOTICE_ALL_OR_NOTHING).classes('vh-muted')

    boxes = {}
    for flag, name, sentence in consent_item_rows():
        boxes[flag] = ui.checkbox(
            f'{name} — {sentence}',
            value=bool(state["items"].get(flag)),
        ).props('dense').classes('w-full vh-keep-all')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _values():
        return {flag: bool(box.value) for flag, box in boxes.items()}

    def _save_items() -> None:
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
        _save(client, account, item_save_payload(_values()), message, on_changed,
              '✅ 공개 항목 5개를 저장했습니다. 아래 2단계(최종 확인)까지 마쳐야 발행 대상이 됩니다.')

    ui.button('1단계 저장 (아직 공개되지 않습니다)', on_click=_save_items) \
        .props('no-caps outline')

    # ── 2층 — 별도의 최종 확인 (5-2-3) ────────────────────────────────────────
    ui.separator()
    ui.markdown('#### 2단계 — 최종 확인')
    ui.label(NOTICE_FINAL_CONFIRM).classes('vh-muted')
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

    def _save_final() -> None:
        final_message.text = ''
        if not final_box.value:
            final_message.text = '🚫 최종 확인란을 체크해 주세요 — 1단계와는 별개의 확인 절차입니다.'
            return
        try:
            payload = final_confirm_payload(_values())
        except DuelRuleError as exc:
            final_message.text = f'🚫 {exc}'
            return
        _save(client, account, payload, final_message, on_changed,
              '✅ 최종 확인이 끝났습니다. 다음 발행 배치부터 공개 순위표 대상이 됩니다.')

    ui.button('🔓 최종 확인하고 공개 신청', on_click=_save_final).props('no-caps color=primary')


def _render_real_principal_form(client, account: dict, state: dict, on_changed) -> None:
    """완전히 별개인 독립 동의(5-2-4). **위 5개와 같은 카드 묶음처럼 보이지 않게** 그립니다."""
    ui.markdown('#### 별개 항목 — 실제 매입총합을 체급 산정에 사용')
    ui.label(NOTICE_REAL_PRINCIPAL).classes('vh-muted')
    ui.label(NOTICE_BRACKET_FIXED).classes('vh-muted')

    box = ui.checkbox(
        CONSENT_REAL_PRINCIPAL_SENTENCE, value=bool(state["real_principal"]),
    ).props('dense').classes('w-full vh-keep-all')
    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _save_flag() -> None:
        message.text = ''
        enabled = bool(box.value)
        _save(client, account, real_principal_payload(enabled), message, on_changed,
              '✅ 실제 매입총합 사용 동의를 켰습니다(체급이 배정됩니다).' if enabled
              else '✅ 실제 매입총합 사용 동의를 껐습니다(다음 시즌부터 구간 미적용 그룹).')

    ui.button('이 항목만 저장', on_click=_save_flag).props('no-caps outline')
    ui.label(
        '※ 이 항목은 위 5개와 따로 저장됩니다. 켜지 않아도 순위표에는 참여할 수 있습니다.'
    ).classes('vh-muted')


# =============================================================================
# 5. 철회 (5-8) — 확인 단계 필수
# =============================================================================
def _render_revoke(client, account_id, on_changed) -> None:
    with ui.expansion('🚫 공개 동의 철회하기').classes('w-full'):
        warning_banner(NOTICE_REVOKE)
        ui.label(NOTICE_REVOKE_TIMING).classes('vh-muted')
        confirm = ui.checkbox(REVOKE_CONFIRM_LABEL).props('dense').classes('w-full vh-keep-all')
        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        def _revoke() -> None:
            message.text = ''
            guard = revoke_guard(bool(confirm.value))
            if guard:
                message.text = guard
                return
            try:
                revoke_consent(client, account_id)
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


# =============================================================================
# 6. 저장 공통 — 저장 성공 시에만 닉네임을 발급합니다 (5-5)
# =============================================================================
def _save(client, account: dict, payload: dict, message, on_changed, success_text: str) -> None:
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
        save_consent(client, account_id, **payload)
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
        ensure_nickname(client, account.get("user_id"), account.get("window_type"))
    except Exception as exc:                       # noqa: BLE001
        nickname_warning = (
            '\n⚠️ 다만 공개 닉네임 발급에 실패했습니다: '
            f'{_fail(exc, "잠시 후 이 화면에서 다시 저장해 주세요.")}'
            '\n닉네임이 없으면 순위표에 실리지 않습니다 — 다시 저장하면 재시도합니다.'
        )

    ui.notify(success_text + nickname_warning, type='positive', multi_line=True,
              close_button='닫기', classes='text-lg whitespace-pre-line')
    on_changed()
