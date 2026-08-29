"""
🏆 "내 성적표" — **공개 순위표 열람 화면** (로그인 필요, URL `/scorecard/leaderboard`).

2026-08-23 — 은퇴한 `web/pages/duel_leaderboard_page.py`(결투 가상계좌 공개 순위표)를
대신하는 화면입니다. 순위표에 실리는 것이 가상계좌 성적에서 **"내 성적표"(실제 보유 자산)**
로 바뀌었습니다.

-------------------------------------------------------------------------------
🔴 이 화면이 읽는 것은 **발행 전용 표 두 개뿐**입니다 (§0-3-8)
-------------------------------------------------------------------------------
`utils/scorecard_publish_db.py` 에서 가져오는 것은 **발행표를 읽는 A 절 함수 3개뿐**입니다.
원본 표(`holdings`·`profiles`)나 동의·닉네임을 읽는 함수는 이름조차 가져오지 않고, 배치
전용 B 절 함수는 더더욱 부르지 않습니다(부르는 순간 앱 서버에 service_role 키가 필요해지고
이 모듈의 모든 RLS 가 장식이 됩니다).

발행표에는 `user_id` 컬럼이 **아예 없고**(스키마 §2-4), 그 함수들은 `select("*")` 를 쓰지
않고 읽을 컬럼을 하나하나 적습니다 — 즉 이 화면이 아무리 잘못 짜여도 **닉네임 말고 사람을
가리키는 값이 흘러 들어올 자리가 물리적으로 없습니다.** §0-3-8 이 요구하는 것은 조심이
아니라 이런 구조입니다.

순위(`rank`)는 **밤에 배치가 계산해 저장해 둔 값**을 그대로 읽습니다. 이 화면은 순위도,
수익률도 계산하지 않습니다(§0-3-2 — 방문자 수만큼 전체 스캔이 돌면 안 됩니다).

-------------------------------------------------------------------------------
🔁 결투 순위표와 **구조가 다른 점 두 가지**
-------------------------------------------------------------------------------
① **창유형(M1/M3/M6) 선택기가 없습니다.** "내 성적표"는 사용자당 포트폴리오 하나이므로
   창유형이라는 축 자체가 존재하지 않습니다. 선택기는 **통화와 체급 둘뿐**입니다.
② **수익률의 정의가 다릅니다.** 결투는 일별 스냅샷으로 누적 TWR(시간가중수익률)을
   계산했지만, "내 성적표"에는 그런 시계열이 없습니다. 여기 실리는 값은 화면이 이미 쓰는
   규칙과 같은 **매입원가 대비 수익률**입니다
   (`utils/scorecard_publish.resolve_portfolio_return_pct()`). 아래
   `NOTICE_HOW_RANKING_WORKS` 가 그 사실을 사용자에게 그대로 말합니다 — 없는 것(TWR)을
   있는 척하지 않습니다(§0-1).

🔴 **원화 순위표와 달러 순위표는 절대 병합·비교하지 않습니다.** 이 앱에는 환율 시계열이
   없어 두 통화의 성적을 한 줄에 세울 수 없고(§0-1 / `scorecard_db.NO_FX_CONVERSION_NOTICE`),
   두 시장은 마감 시각·휴장일 캘린더도 다릅니다. 이 화면은 고른 통화 **한쪽만** 읽습니다.

무엇이 통화마다 다른가 — **딱 세 가지**입니다. 셋이 `track_readers()` 한 곳에 모여 있어서,
§0-3-8 검토가 "이 함수만 보면 된다"가 됩니다:
    ① 체급 목록·라벨(`BRACKET_KEYS`/`bracket_label()` ↔ `..._USD`/`bracket_label_usd()`)
    ② **금액 서식 통화** — 놓치면 달러 금액 칸에 "원"이 찍힙니다(§0-1). 2026-08-23 에 금액
       칸이 넷(매입금액·평균매입가·현재가·평가손익)으로 늘어 이 위험이 커졌으므로, 금액
       서식은 `_amount_cell()` 한 함수만 거치게 모았습니다.
    ③ 화면에 쓸 트랙 이름
  ⚠️ 조회 함수 3개는 두 통화가 **같은 함수**입니다(결투와 다른 점 — 결투는 표 자체가
     둘이라 함수도 둘이었지만, 여기서는 한 표의 `currency` 컬럼이 축입니다). 그래도
     `track_readers()` 가 함께 돌려주는 이유는, "어느 통화로 무엇을 읽고 어떤 통화로
     서식하는가"를 **한 dict 에서 함께 꺼내야** 중간에 갈리지 않기 때문입니다.

-------------------------------------------------------------------------------
🚧 공개 게이트 — 다른 화면과 **똑같은 2단계 패턴**, 스위치만 다릅니다
-------------------------------------------------------------------------------
    SCORECARD_LEADERBOARD_ENABLED         … 이 화면 전용 스위치(기본 꺼짐, 환경변수)
    SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY … 관리자 전용 단계 ↔ 전체 공개

최소 인원 게이팅(`duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION`)이 이미 구조적으로 막고
있지만, 그건 "발행이 안 된다"는 뜻이고 **화면이 안 보인다**는 뜻은 아니라서 화면 쪽 스위치를
따로 둡니다.

-------------------------------------------------------------------------------
📝 문구에 대하여
-------------------------------------------------------------------------------
· 맨 위 **고정 문구 두 문단은 오너 확정 문안 그대로**입니다. 요약·축약·재배치 금지.
  ⚠️ 이 두 문단은 원래 결투 순위표 맨 위에 붙어 있었지만, 그 화면에서는 "'내 성적표'의
     데이터"를 말하면서 정작 순위표에는 가상계좌 성적이 실리는 상태였습니다. 이번 전환으로
     **처음으로 문구와 화면의 내용이 실제로 일치합니다** — 그래서 한 글자도 손대지 않고
     그대로 옮겼습니다.
· 그 밖의 안내 문구는 공개 대상이 바뀐 만큼 다시 썼습니다(특히 순위 산정 방식 —
  TWR 이 아닙니다).

-------------------------------------------------------------------------------
📈 2026-08-23 — 보유종목 상세표가 "내 성적표" 화면과 같은 열 구성이 됨
-------------------------------------------------------------------------------
오너가 실사용 검증 뒤 "'내 성적표'에 나오는 정보는 기본적으로 전부 공개"를 확정해서,
"📄 보유종목 보기"가 종목·수량·매입금액에 더해 **평균매입가·현재가·평가손익·수익률·비중**
까지 보여줍니다(`HOLDINGS_TABLE_HEADERS`). 그 다섯 값은 동의 항목에 새로 생긴
`consent_holding_details`("종목별 상세지표")에 동의한 사람만 채워지고, 아니면 발행 단계에서
이미 null 이라 이 화면은 **"비공개"** 로 그립니다(0 이 아닙니다 — §0-1).
서식은 "내 성적표" 화면(`scorecard_page._render_table()`)이 쓰는 함수를 그대로 씁니다
(§0-3-10 — 같은 값이 두 화면에서 다르게 보이지 않도록).
"""

from nicegui import ui

from utils import duel_rules
from utils.duel_rules import DuelRuleError
# ⚠️ `utils/scorecard_db.py` 에서 가져오는 것은 **로그인 확인과 금액 서식뿐**입니다.
#    실제 보유 자산을 읽는 함수는 이름조차 가져오지 않습니다(위 머리말).
from utils.scorecard_db import (
    CURRENCY_KRW, CURRENCY_USD, format_amount, supabase_status, user_id_of,
)
from utils.scorecard_publish_db import (
    DuelDbError,
    fetch_public_holdings_for_nickname,
    fetch_public_leaderboard,
    fetch_public_leaderboard_latest_date,
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
from web.components import (
    error_banner, esc, holdings_table_html, info_banner, pct_html, pct_text, warning_banner,
)
from web.layout import (
    SCORECARD_LEADERBOARD_ENABLED,
    SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY,
    layout,
)
from web.state import PAGE_RESPONSE_TIMEOUT_SECONDS

# =============================================================================
# 🔴 순위표 최상단 고정 문구 — **오너 확정 · 글자 그대로**
# =============================================================================
#  원문 지시: *"아래 문구를 랭킹 페이지 어디서도 스크롤 없이 바로 보이는 위치(최상단)에
#  고정합니다. 문구는 그대로 씁니다 — 요약·축약하지 마세요."*
#
#  ⚠️ 이 두 문단은 다듬지 마세요. 맞춤법·띄어쓰기까지 원문 그대로입니다("공개되어있는",
#     "주의바랍니다"). 결투 순위표에서 **한 글자도 바꾸지 않고** 옮겨 왔습니다 — 두 문단
#     어디에도 "가상계좌"·"결투" 같은 말이 없고, 오히려 "'내 성적표'의 데이터"를 가리키고
#     있어서 이번 화면에서 비로소 정확한 안내가 됩니다.
FIXED_NOTICE_PARAGRAPHS = (
    "종목의 추천, 매수, 매도 권유가 아니라 지금의 데이터는 어디까지나 개인의 공부를 목적으로 "
    "진행되고 있는 것이며 투자의 책임은 개인에게 있습니다.",
    "실제로 공개되어있는 '내 성적표'의 데이터는 개인이 등록한 것입니다. 운영자는 '내 성적표'의 "
    "데이터를 확인, 검증하고 있지 않으며 확인, 검증을 요청하고 있지 않습니다. 주의바랍니다.",
)

#: "동의하지 않아 발행되지 않은 값"을 화면에 그리는 말. **0 이나 빈칸으로 그리지 않습니다** —
#: "수익률 0%"와 "수익률 비공개"는 다른 말입니다(§0-1 / 스키마 §2-4 컬럼 주석).
NOT_PUBLISHED_TEXT = "비공개"

# --- 안내 문구 ----------------------------------------------------------------
#: 🔴 순위가 어떻게 갈리는가. **여기 실리는 수익률은 TWR 이 아닙니다** — 그 사실을 에둘러
#:    말하지 않고 문장으로 못 박습니다(§0-1). "내 성적표"에는 날짜별 잔고 시계열이 없어서
#:    시간가중수익률을 계산할 방법 자체가 없고, 대신 화면이 이미 쓰는
#:    `scorecard_db.evaluate_holding()` 의 규칙을 포트폴리오 단위로 올려 씁니다
#:    (`utils/scorecard_publish.resolve_portfolio_return_pct()`).
NOTICE_HOW_RANKING_WORKS = (
    "순위는 '체급'(매입원가 구간) 안에서 수익률로만 갈립니다.\n\n"
    "여기서 말하는 수익률은 시간가중수익률(TWR)이 아닙니다. '내 성적표' 화면이 이미 쓰는 "
    "것과 같은 규칙, 즉 (평가금액 − 매입원가) ÷ 매입원가 로 계산한 "
    "'매입원가 대비 수익률'입니다. '내 성적표'에는 날짜별 잔고 시계열이 없어서 "
    "시간가중수익률을 계산할 방법 자체가 "
    "없습니다 — 없는 값을 지어내지 않습니다.\n\n"
    "그래서 언제 얼마를 더 넣었는지·뺐는지는 반영되지 않습니다. 지금 등록돼 있는 보유종목의 "
    "매입원가와 현재 평가금액만 비교한 값입니다.\n\n"
    "가격을 확인하지 못한 종목이 있으면 그 종목은 분자와 분모 양쪽에서 함께 빠집니다 — "
    "어떤 분의 수익률은 보유 전부를 반영한 값이 아닐 수 있습니다.\n\n"
    "체급은 그분이 공개에 동의한 종목별 매입금액을 통화별로 합한 매입원가합계로 나뉩니다. "
    f"그 통화의 보유종목이 없어 매입원가합계를 구할 수 없으면 "
    f"'{duel_rules.BRACKET_NONE_LABEL}' 그룹입니다."
)

NOTICE_MIN_PARTICIPANTS = (
    f"참가자가 {duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명 이상인 그룹만 공개됩니다. "
    "사람이 적으면 닉네임만으로 누구인지 추측될 수 있어서, 인원이 모자란 그룹은 순위표를 "
    "아예 만들지 않습니다(이미 만들어져 있었더라도 지웁니다)."
)

NOTICE_DAILY = (
    "순위표는 하루 한 번, 밤에 그날치로 통째로 다시 만들어집니다.\n\n"
    "지금 보시는 값은 화면을 여는 순간 계산한 것이 아니라 가장 최근 발행분입니다."
)

NOTICE_OVERLAP = (
    f"위쪽 목록은 1위부터 최대 {duel_rules.LEADERBOARD_TOP_COUNT:,}명, 아래쪽 목록은 "
    f"꼴찌부터 최대 {duel_rules.LEADERBOARD_BOTTOM_COUNT:,}명입니다. 그룹 인원이 그 둘을 "
    "합친 수보다 적으면 같은 분이 양쪽에 함께 나올 수 있습니다."
)

NOTICE_EMPTY_GROUP = (
    "아직 공개할 만큼 사람이 모이지 않았습니다. 이 그룹의 순위표는 참가자가 충분히 쌓인 "
    "뒤부터 보입니다 — 오류가 아닙니다."
)

#: 위쪽/아래쪽 두 구간의 표시 이름. 인원 상한은 규칙 계층에서 가져옵니다(§0-3-10).
SECTION_TOP = "top"
SECTION_BOTTOM = "bottom"

# =============================================================================
# 💵 통화(트랙)
# =============================================================================
#: 통화 코드 → 선택기에 보일 이름. 코드 자체는 `scorecard_db.CURRENCY_KRW/USD` 가 단일
#: 출처입니다(§0-3-10 — 이 화면이 "KRW"/"USD" 문자열을 새로 정의하지 않습니다).
#: 순서가 곧 기본값입니다 — 첫 항목(원화)이 화면을 열었을 때 선택돼 있습니다.
CURRENCY_TITLES = {
    CURRENCY_KRW: "🇰🇷 원화 성적표 (국내 보유종목)",
    CURRENCY_USD: "🇺🇸 달러 성적표 (미국 보유종목)",
}

#: 🔴 두 순위표가 왜 별개인지. 사용자가 "왜 달러 1등이 원화 1등보다 수익률이 높은데 위에
#:    없지?" 라고 묻기 전에 먼저 밝힙니다(§0-1 — 없는 것은 없다고 말합니다).
NOTICE_TRACKS_NEVER_MERGED = (
    "원화 순위표와 달러 순위표는 완전히 다른 표입니다.\n\n"
    "두 통화의 성적을 합치거나 서로 비교하지 않습니다 — 이 앱에는 환율 시계열이 없어서 "
    "두 통화를 한 줄에 세울 방법이 없고(없는 값을 지어내지 않습니다), 두 시장은 마감 "
    "시각과 휴장일도 달라 갱신 주기 자체가 다르기 때문입니다.\n\n"
    "한 분이 국내 종목과 미국 종목을 함께 갖고 계시면 두 순위표에 각각 따로 실립니다 — "
    "같은 닉네임으로 실리지만, 두 줄의 성적을 더하거나 비교하지 않습니다.\n\n"
    "통화를 바꾸면 그 통화의 발행분만 새로 읽습니다."
)

#: 💵 달러 트랙의 체급 기준 통화. 위 `NOTICE_HOW_RANKING_WORKS` 는 "통화별 매입원가합계"
#:    까지만 말하는데, 달러 순위표를 보고 있을 때는 그 통화가 무엇인지가 실제로 결과를
#:    가르므로 한 번 더 못 박습니다.
NOTICE_BRACKET_CURRENCY_USD = (
    "달러 순위표의 체급은 '내 성적표'의 달러 보유분 매입원가합계로만 나뉩니다.\n\n"
    "원화 보유분은 여기에 더해지지 않고 원화 순위표에서 따로 셉니다 — 두 통화를 더하지 "
    "않습니다."
)


# =============================================================================
# 1. 순수 함수 (위젯 없이 검증할 수 있게 따로 뺐습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장(§0-3-4)."""
    return fail_message(exc, fallback, context='내 성적표 공개 순위표')


def bracket_options():
    """
    원화 체급 선택지 {bracket_key: 한글 라벨} — 8구간 + "구간 미적용".

    라벨은 `duel_rules.bracket_label()` 만 씁니다. 화면에 금액 경계를 다시 적으면 경계값이
    두 곳에 존재하게 되고, 언젠가 한쪽만 바뀝니다(§0-3-10).
    """
    return {key: duel_rules.bracket_label(key) for key in duel_rules.BRACKET_KEYS}


def bracket_options_usd():
    """
    💵 달러 체급 선택지 {bracket_key: 라벨} — 8구간 + "구간 미적용".

    위 `bracket_options()` 와 **같은 모양**이고 출처만 다릅니다
    (`BRACKET_KEYS`/`bracket_label()` → `BRACKET_KEYS_USD`/`bracket_label_usd()`).

    🔴 원화 `bracket_label()` 에 달러 체급 키를 넘기면 라벨이 조용히 틀리는 게 아니라
       `DuelRuleError` 로 **화면이 통째로 안 그려집니다**(모르는 키를 지어내지 않으므로).
       그게 맞는 동작이고, 그래서 목록과 라벨을 반드시 짝지어 씁니다 — 짝짓는 자리는
       아래 `track_readers()` 한 곳뿐입니다.
    """
    return {key: duel_rules.bracket_label_usd(key) for key in duel_rules.BRACKET_KEYS_USD}


def currency_options():
    """통화 선택지 {통화코드: 라벨}. 첫 항목(원화)이 기본 선택값입니다."""
    return dict(CURRENCY_TITLES)


def track_readers(currency):
    """
    🔴 **통화마다 다른 것이 전부 모여 있는 단 하나의 자리**.

    돌려주는 dict
        latest_date   : 발행일 조회 함수
        page_rows     : 순위표 한 페이지 조회 함수
        detail_rows   : 한 참가자의 발행된 보유종목 조회 함수
        bracket_label : bracket_key → 라벨 함수
        brackets      : 체급 선택지 {key: 라벨}
        currency      : 조회 함수에 넘길 통화 코드
        amount        : `format_amount()` 에 넘길 통화 코드
        title         : 화면에 쓸 트랙 이름

    ⚠️ 조회 함수 3개는 두 통화가 **같은 함수**입니다(발행표가 한 벌이고 `currency` 컬럼이
       축이라서). 그래도 여기서 함께 돌려주는 이유는 "무엇을 어느 통화로 읽고, 어느 통화로
       금액을 서식하는가"가 **한 dict 에서 함께 나와야** 화면 중간에 갈리지 않기
       때문입니다. 결투 화면이 같은 이유로 쓰던 구조를 그대로 가져왔습니다(§0-3-10).

    ⚠️ 이 함수가 하는 일은 **고르기뿐**입니다 — 두 통화의 값을 섞거나 합치는 계산은 하나도
       없고, 호출부는 고른 쪽 값만 씁니다. 모르는 통화는 기본값으로 때우지 않고 예외입니다
       (§0-1 — 잘못 고른 통화로 남의 트랙 행을 읽는 것보다 안 그리는 게 낫습니다).
    """
    code = str(currency or "").strip()
    if code == CURRENCY_KRW:
        return {
            "latest_date": fetch_public_leaderboard_latest_date,
            "page_rows": fetch_public_leaderboard,
            "detail_rows": fetch_public_holdings_for_nickname,
            "bracket_label": duel_rules.bracket_label,
            "brackets": bracket_options(),
            "currency": CURRENCY_KRW,
            "amount": CURRENCY_KRW,
            "title": CURRENCY_TITLES[CURRENCY_KRW],
        }
    if code == CURRENCY_USD:
        return {
            "latest_date": fetch_public_leaderboard_latest_date,
            "page_rows": fetch_public_leaderboard,
            "detail_rows": fetch_public_holdings_for_nickname,
            "bracket_label": duel_rules.bracket_label_usd,
            "brackets": bracket_options_usd(),
            "currency": CURRENCY_USD,
            "amount": CURRENCY_USD,
            "title": CURRENCY_TITLES[CURRENCY_USD],
        }
    raise DuelRuleError(f"알 수 없는 통화입니다: {currency!r}")


def section_cap(section):
    """구간(위/아래)의 최대 인원 — "상위 500 + 하위 500"."""
    if section == SECTION_TOP:
        return duel_rules.LEADERBOARD_TOP_COUNT
    if section == SECTION_BOTTOM:
        return duel_rules.LEADERBOARD_BOTTOM_COUNT
    raise DuelRuleError(f"알 수 없는 순위표 구간입니다: {section!r}")


def return_display(value):
    """
    발행된 수익률 → 화면 문자열. **None 은 '비공개'** 입니다(0% 로 그리지 않습니다 — §0-1).

    값이 있는데 숫자로 해석되지 않으면 그것도 지어내지 않고 그대로 알립니다.

    🔴 이름이 결투판의 `twr_display()` 와 다릅니다. 여기 실리는 값은 시간가중수익률이
       아니라 매입원가 대비 수익률이라(위 `NOTICE_HOW_RANKING_WORKS`), 함수 이름에 TWR 이
       남아 있으면 다음 사람이 그 값을 TWR 로 취급하게 됩니다.
    """
    if value is None:
        return NOT_PUBLISHED_TEXT
    try:
        return pct_text(float(value))
    except (TypeError, ValueError):
        return '값 확인 필요'


def rank_text(row):
    """"12위" 형태. 순위는 발행표의 `rank` 를 **그대로** 씁니다(다시 매기지 않습니다)."""
    value = (row or {}).get("rank")
    if value is None:
        # 발행표의 rank 는 not null 이라 정상적으로는 올 수 없는 상태입니다. 조용히 빈칸으로
        # 두지 않고 그렇게 표시합니다(§0-1).
        return '순위 없음'
    return f'{value}위'


#: 공개 보유종목 표의 열 제목. **"내 성적표" 화면(`scorecard_page._render_table()`)의 표와
#: 같은 것을 보여주자**는 오너 확정(2026-08-23)에 따라, 그 화면의 열 다섯 개
#: (평균매입가·현재가·평가손익·수익률·비중)가 여기에도 붙었습니다.
#:
#: 🔴 순서에 대하여 — 새 다섯 열은 기존 세 열 **뒤에** 붙였고, 다섯 열끼리의 순서는 "내
#:    성적표" 표와 **똑같이** 두었습니다(평균매입가 → 현재가 → 평가손익 → 수익률 → 비중).
#:    두 화면을 번갈아 보는 사람이 같은 순서로 읽게 하려는 것이고, 기존 세 열의 자리를
#:    건드리지 않아 "매입금액이 어느 칸인지"에 의존하던 코드·검사가 조용히 어긋나지
#:    않습니다.
HOLDINGS_TABLE_HEADERS = (
    '종목', '수량', '매입금액', '평균매입가', '현재가', '평가손익', '수익률', '비중',
)


def _amount_cell(value, currency):
    """금액 한 칸 — 없으면(=동의 안 함 / 값 없음) **"비공개"**, 0 으로 그리지 않습니다."""
    return esc(format_amount(value, currency) if value is not None else NOT_PUBLISHED_TEXT)


def holding_row_cells(row, currency=CURRENCY_KRW):
    """
    공개 보유종목 한 행 → 표 셀 8개. 동의하지 않은 항목(null)은 **"비공개"** 로 그립니다.

    🔐 §0-3-9 — **`stock_name` 은 사용자가 자유 입력한 값입니다.** `holdings.stock_name` 을
       배치가 그대로 옮겨 실으므로(`utils/scorecard_publish.holdings_payload()` 독스트링 ·
       스키마 §2-4 컬럼 주석), `<img src=x onerror=...>` 같은 문자열이 이 자리에 도착할 수
       있습니다. 이 화면에서 **가장 중요한 한 줄**이 아래 `esc()` 입니다 — 종목명도,
       종목코드도 예외 없이 거칩니다("종목코드는 숫자니까 괜찮다"는 판단을 코드에 남기지
       않습니다).

    💵 `currency` 를 인자로 받습니다(생략하면 원화). 통화가 본문에 박혀 있으면 달러
       보유종목의 매입금액이 그대로 **"1,234원"** 으로 찍힙니다(§0-1 정면 위반 — 예외도
       로그도 없이 사용자에게만 틀린 값이 보이는 종류).
       🔴 그런데도 `holding_row_cells_usd()` 를 따로 만들지 **않은** 이유: 이 함수에서
       통화에 걸린 것은 `format_amount()` 의 인자 하나뿐이고, 나머지는 전부 XSS 이스케이프
       (§0-3-9)와 "비공개 ≠ 0"(§0-1) 판정입니다. 그 둘을 복제하면 이스케이프 경로가 두 개가
       되어, 한쪽만 고치는 순간 조용히 뚫립니다.
       🔴 2026-08-23 에 금액 칸이 넷(매입금액·평균매입가·현재가·평가손익)으로 늘면서 이
          위험이 네 배가 됐습니다. 그래서 금액 칸은 `_amount_cell()` **하나만** 쓰게
          모았습니다 — 통화를 넘기는 것을 한 칸에서만 빠뜨려도 그 칸만 "1,234원"이 되므로.

    ── 🔴 2026-08-23 늘어난 다섯 칸 (평균매입가·현재가·평가손익·수익률·비중) ────────
    오너 확정("'내 성적표'에 나오는 정보는 기본적으로 전부 공개")에 따라, 이 표는 이제 "내
    성적표" 화면의 보유종목 표와 **같은 열 구성**입니다. 서식 함수도 그 화면
    (`scorecard_page._render_table()`)과 **같은 것을 씁니다**(§0-3-10):
        · 금액 네 칸  → `format_amount(value, currency)` (`_amount_cell()` 경유)
        · 수익률      → `pct_html()`  (국내 증시 관례 색: 오르면 빨강 / 내리면 파랑.
                        `web/components` 안에서 이스케이프까지 끝난 조각을 돌려줍니다 —
                        `esc()` 로 한 번 더 감싸면 색 태그가 글자로 보입니다)
        · 비중        → 소수점 한 자리 + '%'
    같은 값을 두 화면이 서로 다르게 보여주면 그 자체가 사실이 아닌 정보이므로(§0-1), 여기서
    서식을 새로 짜지 않습니다.

    🔴 다섯 칸 모두 **없으면 "비공개"** 입니다. null 의 사유는 두 가지(그 참가자가
       `consent_holding_details` 에 동의하지 않았거나, 그날 그 종목의 가격을 구하지
       못했거나)인데 발행표는 둘을 구분해 담지 않습니다 — 구분해 담으면 "이 사람은 동의는
       했는데 가격이 없다"가 남에게 드러납니다. 어느 쪽이든 **0 으로 그리지 않는다**는 것이
       지켜야 할 규율입니다("평가손익 0원"과 "평가손익 비공개"는 다른 말입니다).
    """
    data = dict(row or {})
    ticker = str(data.get("ticker") or "")
    name = data.get("stock_name") or ticker
    quantity = data.get("quantity")
    profit_pct = data.get("profit_pct")
    weight_pct = data.get("weight_pct")
    return [
        (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
         f'{esc(str(name))}<br>({esc(ticker)})</div>'),
        esc(f'{float(quantity):,.6g}주' if quantity is not None else NOT_PUBLISHED_TEXT),
        _amount_cell(data.get("buy_amount"), currency),
        _amount_cell(data.get("avg_price"), currency),
        _amount_cell(data.get("current_price"), currency),
        _amount_cell(data.get("profit"), currency),
        # `pct_html()` 은 이미 이스케이프를 마친 HTML 조각을 돌려줍니다(위 독스트링).
        pct_html(profit_pct) if profit_pct is not None else esc(NOT_PUBLISHED_TEXT),
        esc(f'{float(weight_pct):.1f}%' if weight_pct is not None else NOT_PUBLISHED_TEXT),
    ]


def holdings_table(rows, currency=CURRENCY_KRW):
    """공개 보유종목 표 HTML. 행이 없으면 None(호출부가 안내 문구를 대신 그립니다).

    💵 `currency` 는 위 `holding_row_cells()` 로 그대로 넘어갑니다(생략하면 원화).

    ⚠️ 열 제목은 `HOLDINGS_TABLE_HEADERS` 한 곳에만 있습니다 — 칸을 하나 늘리면서 제목을
       빠뜨리면 표가 통째로 밀립니다(제목과 칸을 서로 다른 자리에 적어 두면 언젠가 그렇게
       됩니다).
    """
    body = [holding_row_cells(row, currency) for row in rows or []]
    if not body:
        return None
    return holdings_table_html(list(HOLDINGS_TABLE_HEADERS), body)


# =============================================================================
# 2. 페이지 (공개 플래그 게이트 → 고정 문구 → 로그인 게이트)
# =============================================================================
#  NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 발행일
#  조회 + 위/아래 두 구간 조회가 순서대로 일어나므로 느린 날에는 3초를 넘길 수 있고,
#  그러면 화면 대신 **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반).
@ui.page('/scorecard/leaderboard', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def scorecard_leaderboard_page() -> None:
    with layout('💼 내 성적표 — 공개 순위표', width_class='max-w-6xl'):
        ui.markdown('## 🏆 내 밑으로 눈 깔어 — 성적표 공개 순위표')

        if not SCORECARD_LEADERBOARD_ENABLED:
            _render_coming_soon()
            return
        if SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY and not is_admin():
            _render_coming_soon()
            return

        # 🔴 고정 문구 — **본문 맨 위, 로그인 폼보다도 위**. 이 화면에서 무엇을 보든
        #    이 두 문단을 먼저 보게 됩니다(스크롤 없이 보이는 위치).
        _render_fixed_notice()

        status = supabase_status()
        if not status.available:
            warning_banner(f'🚧 공개 순위표는 아직 준비중입니다.\n\n사유: {status.reason}')
            return

        # ── 로그인 게이트 ────────────────────────────────────────────────────
        #    비로그인 접근 불가 — 발행표의 RLS 도 `authenticated` 에게만 select 를
        #    허용합니다(스키마 §3-4). 화면과 DB 가 같은 방향으로 막습니다.
        if not has_supabase_session():
            info_banner('🔒 공개 순위표는 로그인한 이용자에게만 보입니다. 먼저 로그인해 주세요.')
            render_auth()
            return

        try:
            client = await get_client_async()
            if client is None:
                warning_banner('🚧 공개 순위표는 아직 준비중입니다(로그인 연결이 준비되지 않았습니다).')
                return
            user = await current_user_async(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return

        if not user_id_of(user):
            await logout_async()
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        try:
            await _render_body(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "순위표를 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_coming_soon() -> None:
    warning_banner(
        '🚧 공개 순위표는 아직 준비중입니다.\n\n'
        '참가자가 충분히 모이면 열립니다. 그때까지 누구의 성적표도 공개되지 않습니다.'
    )


def _render_fixed_notice() -> None:
    """🔴 고정 문구 두 문단. **글자 그대로**, 크게, 맨 위에."""
    with ui.card().classes('vh-card w-full'):
        for paragraph in FIXED_NOTICE_PARAGRAPHS:
            ui.label(paragraph).classes('text-base vh-keep-all')


# =============================================================================
# 3. 로그인 후 본문 — 그룹 고르기 → 순위표
# =============================================================================
async def _render_body(client) -> None:
    """
    통화 · 체급을 고르면 그 그룹의 순위표를 그립니다(창유형 축은 없습니다).

    🔴 발행표 조회 3종을 `run_blocking()` 으로 별도 스레드에 넘깁니다. 전부 Supabase 로
       **동기 HTTP 왕복**을 하고, 그룹을 바꾸거나 페이지를 넘길 때마다 다시 불립니다.
       그동안 이벤트 루프가 멈추면 **다른 화면을 보던 접속자까지** 함께 끊깁니다
       (`web/blocking.py` 독스트링).

    ⚠️ 선택 값과 페이지 번호는 **이 함수 안의 지역 변수**입니다. 모듈 전역에 두면 접속자
       끼리 화면 상태가 섞입니다(§0-3-8 — 순위표는 사용자 데이터가 아니지만, "다른 사람이
       페이지를 넘기면 내 화면이 바뀌는" 것 자체가 같은 종류의 사고입니다).
    """
    ui.label(NOTICE_HOW_RANKING_WORKS).classes('vh-muted vh-keep-all whitespace-pre-line')
    ui.label(NOTICE_MIN_PARTICIPANTS).classes('vh-muted')
    ui.label(NOTICE_DAILY).classes('vh-muted whitespace-pre-line')
    ui.label(NOTICE_TRACKS_NEVER_MERGED).classes('vh-muted vh-keep-all whitespace-pre-line')

    currencies = currency_options()
    default_currency = next(iter(currencies))
    brackets = track_readers(default_currency)["brackets"]
    # 지역 상태(접속마다 별개). 값은 "지금 무엇을 보고 있는가"뿐이고 사용자 데이터가 아닙니다.
    view = {
        "currency": default_currency,
        "bracket_key": next(iter(brackets)),
        SECTION_TOP: 0,
        SECTION_BOTTOM: 0,
    }

    def _changed(_event=None) -> None:
        view["bracket_key"] = bracket_select.value
        view[SECTION_TOP] = 0                      # 그룹이 바뀌면 페이지는 처음으로
        view[SECTION_BOTTOM] = 0
        group_section.refresh()

    def _currency_changed(_event=None) -> None:
        """🔴 통화가 바뀌면 **체급 목록 자체가 통째로 바뀝니다**.

        원화 체급 키(`krw_…`)와 달러 체급 키(`usd_…`)는 겹치는 것이 하나도 없어서, 옛 값을
        그대로 들고 가면 `bracket_label_usd()` 가 모르는 키로 예외를 냅니다. 그래서 목록을
        새로 깔고 **그 목록의 첫 항목**으로 선택을 리셋합니다(임의로 비슷한 구간을 골라
        주지 않습니다 — 그건 사용자가 안 고른 값을 지어내는 일입니다, §0-1).
        """
        view["currency"] = currency_select.value
        new_brackets = track_readers(view["currency"])["brackets"]
        view["bracket_key"] = next(iter(new_brackets))
        view[SECTION_TOP] = 0
        view[SECTION_BOTTOM] = 0
        bracket_select.set_options(new_brackets, value=view["bracket_key"])
        group_section.refresh()

    with ui.row().classes('w-full gap-4 items-end'):
        # 통화를 **맨 앞**에 둔 이유: 통화가 바로 옆 체급 목록을 결정하기 때문입니다.
        currency_select = ui.select(currencies, value=view["currency"], label='통화(트랙)',
                                    on_change=_currency_changed).style('flex: 1 1 240px;')
        bracket_select = ui.select(brackets, value=view["bracket_key"],
                                   label='체급(매입원가 구간)',
                                   on_change=_changed).style('flex: 1 1 260px;')

    # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
    #    직접 부를 때는 `await`, 위 처리기 안의 `.refresh()` 는 동기 호출 그대로입니다.
    @ui.refreshable
    async def group_section() -> None:
        await _render_group(client, view, group_section.refresh)

    await group_section()


async def _render_group(client, view: dict, on_changed) -> None:
    """한 그룹(통화 × 체급)의 순위표. 발행일을 **먼저 한 번** 확정하고 시작합니다.

    💵 고른 통화의 값만 씁니다. `readers` 를 여기서 한 번 고른 뒤 아래 두 단계
       (`_render_section` → `_render_holdings`)에 **그대로 넘겨**, 한 화면 안에서 통화가
       중간에 갈릴 수 있는 자리를 없앴습니다.
    """
    bracket_key = view["bracket_key"]
    try:
        readers = track_readers(view["currency"])
    except DuelRuleError as exc:
        error_banner(f'🚫 {exc}')
        return
    try:
        published_date = await run_blocking(
            readers["latest_date"],
            client, currency=readers["currency"], bracket_key=bracket_key)
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "순위표를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    # 🔴 제목에 **통화를 먼저** 적습니다. 원화 표와 달러 표는 절대 섞이지 않지만, 보는
    #    사람이 어느 쪽을 보고 있는지 헷갈리면 그것만으로도 잘못된 비교를 하게 됩니다.
    ui.markdown(
        f'#### {esc(readers["title"])} · {esc(readers["bracket_label"](bracket_key))}'
    )
    if view["currency"] == CURRENCY_USD:
        ui.label(NOTICE_BRACKET_CURRENCY_USD).classes('vh-muted vh-keep-all whitespace-pre-line')

    if not published_date:
        # 🔴 정상 상태입니다(오류 아님). 참가자가 없거나, 최소 인원 미달이라 발행되지
        #    않았거나, 발행됐다가 인원이 줄어 지워진 경우 — 셋을 구분해 보여주지 않습니다
        #    (구분 자체가 "이 구간에 몇 명쯤 있는지"의 힌트가 되고, 그건 소수 N 역추적의
        #     재료입니다 — `scorecard_publish_db.fetch_public_leaderboard_latest_date()`
        #     독스트링과 같은 판단).
        info_banner(f'ℹ️ {NOTICE_EMPTY_GROUP}')
        return

    ui.label(f'📅 {published_date} 발행분').classes('vh-muted')
    ui.label(NOTICE_OVERLAP).classes('vh-muted')

    await _render_section(client, view, published_date, SECTION_TOP, on_changed, readers)
    ui.separator()
    await _render_section(client, view, published_date, SECTION_BOTTOM, on_changed, readers)


async def _render_section(client, view: dict, published_date: str, section: str, on_changed,
                          readers: dict) -> None:
    """
    위쪽(1위부터) 또는 아래쪽(꼴찌부터) 한 페이지.

    ⚠️ "몇 명인지"를 세는 질의는 보내지 않습니다. 아래쪽 목록은 정렬을 뒤집어 읽고 화면에서
       다시 뒤집습니다 — 인원을 세려면 방문마다 전체를 훑어야 하고, 그게 §0-3-2 가 막는
       모양입니다. 대신 마지막 페이지인지는 "돌아온 행 수 < 요청한 수"로 판정합니다.
    """
    cap = section_cap(section)
    page_index = view[section]
    offset, limit = duel_rules.leaderboard_page_bounds(page_index, section_cap=cap)

    title = (f'#### 🔼 위에서부터 (최대 {cap:,}명)' if section == SECTION_TOP
             else f'#### 🔽 아래에서부터 (최대 {cap:,}명)')
    ui.markdown(title)

    if limit <= 0:
        # 구간 상한을 넘어간 페이지 — 질의 자체를 보내지 않습니다.
        info_banner('ℹ️ 이 구간에서 보여드릴 수 있는 마지막 페이지를 넘었습니다.')
        _render_pager(view, section, page_index, has_next=False, on_changed=on_changed)
        return

    try:
        rows = await run_blocking(
            readers["page_rows"],
            client, currency=readers["currency"], bracket_key=view["bracket_key"],
            published_date=published_date, limit=limit, offset=offset,
            order_desc=(section == SECTION_BOTTOM),
        )
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "순위표를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    if not rows:
        info_banner('ℹ️ 이 페이지에는 표시할 참가자가 없습니다.')
        _render_pager(view, section, page_index, has_next=False, on_changed=on_changed)
        return

    # 아래쪽 목록은 꼴찌부터 읽어 왔으므로, 화면에서는 순위가 올라가는 방향으로 뒤집어
    # 보여줍니다(읽는 사람에게는 "…998위, 999위, 1000위" 가 자연스럽습니다).
    display_rows = list(rows) if section == SECTION_TOP else list(reversed(rows))
    for row in display_rows:
        _render_participant(client, published_date, row, readers)

    _render_pager(view, section, page_index, has_next=len(rows) >= limit,
                  on_changed=on_changed)


def _render_participant(client, published_date: str, row: dict, readers: dict) -> None:
    # (이 함수 자체는 위젯만 만듭니다 — 조회는 아래 `_open()` 을 눌렀을 때만 일어납니다.)
    """
    순위표 한 줄. 펼치면 그 닉네임의 **공개된** 보유종목을 개별 열람합니다.

    보유종목은 **펼칠 때 처음 읽습니다.** 페이지를 여는 것만으로 30명분 상세를 미리 읽으면
    그게 §0-3-2 가 막는 모양이고, 대부분의 방문자는 몇 명만 펼쳐 봅니다.

    🔐 §0-3-9 — 닉네임은 서버가 무작위로 뽑은 값이라 사용자가 내용을 정할 수 없지만, 화면에
       나가는 값은 예외 없이 `esc()` 를 거칩니다("이 값은 안전하다"는 판단이 코드에 흩어지기
       시작하면 언젠가 한 곳이 틀립니다).
    """
    nickname = str((row or {}).get("nickname") or '')
    header = (f'{rank_text(row)} · {esc(nickname)} · '
              f'수익률 {return_display((row or {}).get("return_pct"))}')

    with ui.card().classes('vh-card w-full'):
        # 이 행 하나만의 지역 상태(접속마다·행마다 별개 — 모듈 전역에 두지 않습니다).
        slot = {"body": None, "loaded": False}

        async def _open(_event=None) -> None:
            # 펼칠 때 Supabase 왕복이 일어나므로 이 처리기도 이벤트 루프를 붙잡으면 안
            # 됩니다. NiceGUI 는 `on_click` 에 코루틴 함수를 그대로 받아 줍니다.
            if slot["loaded"] or slot["body"] is None:
                return
            slot["loaded"] = True                  # 두 번 눌러도 두 번 읽지 않습니다
            with slot["body"]:
                ok = await _render_holdings(client, published_date, nickname, readers)
            if not ok:
                # 2026-08-29 재감사(L-2) — 조회가 실패했는데도 위에서 이미 `loaded=True`
                # 를 걸어 버리면, DB 오류가 한 번 나는 순간 그 참가자의 상세는 **페이지를
                # 새로고침해야만** 다시 시도할 수 있습니다("두 번 눌러도 두 번 읽지 않는다"는
                # 원래 의도가 실패한 시도까지 잠가버린 것). 실패했을 때만 되돌려서 다시
                # 눌러볼 수 있게 합니다 — 성공한 렌더는 여전히 한 번만 읽습니다.
                slot["loaded"] = False

        with ui.row().classes('no-wrap items-center gap-2 w-full'):
            ui.label(header).classes('flex-1 min-w-0 vh-keep-all')
            ui.button('📄 보유종목 보기', on_click=_open) \
                .props('flat dense no-caps').classes('shrink-0')
        slot["body"] = ui.column().classes('w-full gap-1')


async def _render_holdings(client, published_date: str, nickname: str, readers: dict) -> bool:
    """한 참가자의 공개 보유종목 표(없으면 그 사실을 그대로 알립니다).

    반환값(2026-08-29 재감사 L-2): 실제로 표를 그렸으면(또는 "공개 안 함" 등 **정상** 빈
    상태를 확인했으면) `True`, 조회 자체가 실패했으면 `False` — 호출부(`_open()`)가 이
    값으로 "다시 눌러볼 수 있게 할지"를 판단합니다. 실패와 "정상적으로 비어 있음"은
    다른 말입니다(§0-1) — 후자는 다시 눌러도 같은 결과이므로 `True` 를 돌려줍니다.

    💵 조회 통화도, 금액 서식 통화도 `readers` 에서 옵니다. 둘이 어긋나면(예: 달러 행을 읽고
       원화로 서식) 화면이 조용히 "1,234원"이라고 말하게 됩니다 — 그래서 **한 dict 에서 함께
       꺼냅니다**(두 곳에서 따로 고르지 않습니다).
       🔴 통화를 반드시 걸어야 하는 또 다른 이유: 한 분이 국내·미국 종목을 둘 다 공개했다면
          **닉네임이 같습니다.** 통화를 안 걸면 원화 순위표에서 그분의 달러 종목까지 함께
          보입니다.

    🔐 §0-3-9 — 표 안의 종목명·종목코드는 `holdings_table()` → `holding_row_cells()` 가
       전부 `esc()` 로 감싼 뒤에야 `ui.html()` 에 들어갑니다. 이 화면에서 사용자 자유
       입력값이 raw HTML 로 나갈 수 있는 자리는 여기 하나뿐입니다.
    """
    if not nickname:
        error_banner('🚫 닉네임을 확인하지 못해 보유종목을 불러오지 않았습니다.')
        return False
    try:
        rows = await run_blocking(
            readers["detail_rows"],
            client, nickname, published_date=published_date, currency=readers["currency"])
    except (DuelDbError, DuelRuleError) as exc:
        error_banner(f'🚫 {exc}')
        return False
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "보유종목을 불러오지 못했습니다.")}')
        return False

    table = holdings_table(rows, readers["amount"])
    if table is None:
        # 행이 아예 없는 것은 "보유종목을 공개하지 않았다" 또는 "그 통화로는 아직 아무것도
        # 등록하지 않았다"입니다. 둘 중 무엇인지 이 표만 보고는 알 수 없으므로 **단정하지
        # 않습니다**(§0-1). 2026-08-29 재감사 M-2 — 발행 배치가 순위표·보유종목 두 표를
        # 순서대로 쓰는 동안(트랜잭션으로 묶이지 않음) 아주 잠깐 이 상태가 될 수 있다는
        # 것도 함께 밝힙니다 — 그 경우 실제로는 두 조건 다 아닙니다.
        ui.label(
            '이 참가자의 보유종목은 공개되어 있지 않거나, 아직 등록된 종목이 없습니다. '
            '(발행 직후라면 잠시 후 다시 확인해 주세요.)'
        ).classes('vh-muted')
        return True             # 정상적으로 "비어 있음"을 확인한 것 — 다시 눌러도 결과는 같음(L-2)
    ui.html(table).classes('w-full')
    ui.label(
        f'※ "{NOT_PUBLISHED_TEXT}" 로 표시된 항목은 그 참가자가 공개에 동의하지 않은 값입니다 '
        '— 0 이라는 뜻이 아닙니다.'
    ).classes('vh-muted')
    return True


def resolve_jump_target(raw_value, max_pages):
    """
    "N 페이지로 이동" 입력 → `(page_index, 오류 문장)` 중 **정확히 한쪽만** 채워 돌려줍니다.

    (위젯 없이 검증할 수 있게 순수 함수로 뺐습니다 — 아래 `_render_pager()` 의 처리기는
     이 함수를 부르고 결과를 화면에 옮기기만 합니다.)

    🔴 **범위를 벗어난 값을 조용히 잘라 맞추지 않습니다**(§0-1). 사용자가 99 를 넣었는데
       말없이 17페이지를 보여주면, 그 사람은 자기가 99페이지를 보고 있다고 믿게 됩니다.
       대신 "1 ~ {max_pages} 사이"라고 말하고 페이지를 **바꾸지 않습니다.**

    ⚠️ `ui.number` 는 값을 float 로 줍니다(빈칸이면 None). 1.5 처럼 정수가 아닌 값은
       가까운 쪽으로 반올림하지 않고 거절합니다 — "1.5페이지"라는 것이 없기 때문입니다.

    반환: `(page_index, None)` 또는 `(None, 사용자에게 보여줄 한국어 문장)`.
    """
    if raw_value is None or str(raw_value).strip() == '':
        return None, '이동할 페이지 번호를 입력해 주세요.'
    try:
        number = float(raw_value)
    except (TypeError, ValueError):
        return None, '페이지 번호는 숫자로 입력해 주세요.'
    if number != int(number):
        return None, '페이지 번호는 정수로 입력해 주세요.'
    page_number = int(number)
    if page_number < 1 or page_number > max_pages:
        return None, f'1 ~ {max_pages} 사이의 페이지 번호를 입력해 주세요.'
    return page_number - 1, None


def _render_pager(view: dict, section: str, page_index: int, *, has_next: bool,
                  on_changed) -> None:
    """
    이전/다음 버튼 + **페이지 직접 이동**. 페이지 번호는 **이 접속의 지역 상태**(`view`)
    에만 있습니다.

    누를 수 없는 방향의 버튼은 비활성으로 두지 않고 **아예 그리지 않습니다** — 눌러도
    아무 일이 없는 버튼보다 없는 편이 덜 헷갈리고, 화면 상태 판정이 한 곳(여기)에만
    남습니다.

    🔴 2026-08-23 오너 요청 — "이전/다음만으로 17페이지를 넘기는 건 너무 느리다". 그래서
       번호를 직접 넣어 뛰는 칸을 **덧붙였습니다**(기존 이전/다음 동작은 한 줄도 바꾸지
       않았습니다). 페이지가 한 장뿐이면 뛸 곳이 없으므로 그 칸도 그리지 않습니다.
       ⚠️ 뛰어도 `view[section]` 을 바꾸고 `on_changed()` 를 부르는 것이 전부입니다 —
          "지금 몇 페이지인가"의 단일 출처는 여전히 `view` 하나입니다(§0-3-10). 이 함수는
          질의를 직접 보내지 않고, 상한을 넘은 페이지에서 질의가 나가지 않게 막는 것도
          기존 그대로 `_render_section()`(limit <= 0)의 몫입니다.
    """
    max_pages = duel_rules.leaderboard_page_count(section_cap(section))

    def _go(delta):
        def _handler(_event=None) -> None:
            view[section] = max(0, page_index + delta)
            on_changed()
        return _handler

    with ui.row().classes('items-center gap-2'):
        if page_index > 0:
            ui.button('◀ 이전', on_click=_go(-1)).props('flat dense no-caps')
        ui.label(f'{page_index + 1} / 최대 {max_pages} 페이지').classes('vh-muted')
        if has_next and page_index + 1 < max_pages:
            ui.button('다음 ▶', on_click=_go(1)).props('flat dense no-caps')

    if max_pages <= 1:
        return

    with ui.row().classes('items-center gap-2'):
        jump_input = ui.number(label='페이지로 이동', value=page_index + 1,
                               min=1, max=max_pages, step=1) \
            .props('dense').style('flex: 0 0 140px;')
        jump_message = ui.label('').classes('text-red-400 vh-muted')

        def _jump(_event=None) -> None:
            target, problem = resolve_jump_target(jump_input.value, max_pages)
            if problem:
                # 값을 지어내지 않고 이유만 알려 줍니다 — 페이지는 그대로입니다.
                jump_message.text = f'🚫 {problem}'
                return
            jump_message.text = ''
            view[section] = target
            on_changed()

        ui.button('이동', on_click=_jump).props('flat dense no-caps')
