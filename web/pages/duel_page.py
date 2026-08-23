"""
⚔️ 결투다! — 1갈래 "덤벼라 나 자신" (가상 모의투자 계좌 3개, 로그인 필요, URL `/duel`).

`DUEL_MODULE_WORK_ORDER.md` 2단계의 마지막 남은 파일입니다. 규칙 계산(`utils/duel_rules.py`)과
Supabase 접근(`utils/duel_db.py`)은 **이미 완성돼 승인된 파일**이라 이 화면은 한 줄도 건드리지
않고 **부르기만** 합니다. 체결·수익률·시간대 판정을 이 파일에 다시 구현하지 마세요(§0-3-10 —
같은 규칙을 두 곳에 적으면 언젠가 한쪽만 고쳐지고, 그 순간 화면 숫자와 DB 숫자가 갈라집니다).

🔴 세션 격리 규율 — `web/pages/scorecard_page.py` 와 **똑같은 규칙**입니다(§0-3-8).
   1. **사용자 데이터는 모듈 전역에 두지 않습니다.** 이 파일의 최상위에는 상수(문자열/숫자/
      읽기전용 튜플·사전)만 있습니다. 계좌·주문·현금·클라이언트·사용자 id 는 전부 `@ui.page`
      함수 안의 지역 변수이거나 함수 인자로 명시적으로 전달됩니다.
   2. **"지금 누가 로그인했는지"를 암묵적으로 추측하지 않습니다.** DB 를 만지는 모든 함수는
      `client`(그 접속 전용 Supabase 클라이언트)와 `user_id` 를 인자로 받아야만 동작하고,
      계좌 카드를 그리기 전에 `account["user_id"] == user_id` 를 한 번 더 확인합니다
      (RLS 가 이미 막지만, 정책이 실수로 지워진 최악의 상황에서도 남의 행을 그리지 않기 위한
      이중 방어 — `utils/duel_db.py` A절 머리말의 "앱에서도 소유자 필터를 명시적으로" 와 같은 규율).
   3. 이 규칙이 지켜지는지 `tests/test_web_session_isolation.py` [9] 가 자동으로 검사합니다.

🚧 공개 절차(§0-3-6 / 작업지시서 2-8 · 7단계) — **3단계 공개**의 스위치는 `web/layout.py` 의
   `DUEL_ENABLED` / `DUEL_MENU_ADMIN_ONLY` 두 값이 전부입니다. 이 화면도 **같은 값**을 보고
   ① 플래그가 꺼져 있으면 URL 로 직접 들어와도 "준비중" 안내만 그리고
   ② 관리자 전용 단계에서는 관리자가 아닌 접속에 본문을 한 글자도 그리지 않습니다
   (메뉴만 숨기면 주소를 아는 사람은 그냥 들어올 수 있으므로 — 벨트+멜빵).

📌 이 화면이 사용자에게 **반드시** 말해야 하는 것(2-8 상시 노출 3종 + 작업지시서 곳곳의
   고지 요구)은 아래 `MANDATORY_NOTICES` / `_render_header()` / `_render_rules_expansion()`
   에 모아 뒀습니다. 문구를 고칠 때는 반드시 작업지시서의 해당 절을 다시 읽고 고치세요.

⚠️ 2-8 초안 문구를 **의도적으로 고쳐 쓴 곳이 한 군데** 있습니다 — 아래 `NOTICE_FILL_TIMING`
   주석에 그 이유를 적어 뒀습니다(초안: "그날 밤에 체결" → 확정: "다음 거래일 종가로 체결").

💵 2026-08-21 — **USD 트랙("달러 결투")이 이 화면에 함께 들어왔습니다**(작업지시서 §5-11 ~ §5-18).
   구조 원칙은 스키마·DB계층·배치가 이미 세운 것과 **글자 그대로 같습니다**:
   **데이터는 완전 분리, 순수 규칙은 공유**(§5-11-1).
   1. **원화 코드는 한 줄도 바꾸지 않았습니다 — 추가만 했습니다.** 원화 사용자가 보던 화면은
      그대로입니다(USD 계좌가 하나도 없으면 계좌 카드 영역이 예전과 **똑같은 경로**로 그려집니다).
   2. **표 이름·통화 상수·시간대·문구가 본문에 박힌 것만 새로 정의**하고, 통화를 모르는 순수
      함수(`_parse_positive_int`·`_twr_display`·`_order_status_text`·`_universe_options`·
      `duel_rules.compute_twr`·`is_buy_window_open`·`sum_cash_balance`)는 **그대로 재사용**합니다.
      이 트랙에서 이미 네 번 반복된 판단 기준입니다(`_translate_order_guard_error_usd` ·
      `format_summary_lines_usd` · `resolve_fill_trading_day_usd` · `resolve_bracket_for_season_usd`).
   3. 🔴 **주문 접수 시간대를 절대 섞지 마세요.** 원화는 `duel_rules.resolve_order_window()`,
      달러는 `duel_rules.resolve_order_window_usd()` 입니다(§5-13 오너 확정, 두 시간 차이).
      한 자리만 틀려도 미국 트랙 사용자가 원화 시간대 안내를 보게 됩니다.
   4. 🔴 **체결 시점의 방향이 통화마다 정반대입니다.** 원화는 "다음 거래일(D+1) 종가",
      달러는 "**주문을 넣은 바로 그날**의 미국 정규장 마감가"입니다(§5-16). 접수 시간대가
      그날 장의 뒤(원화)냐 앞(달러)이냐가 다르기 때문입니다 — 원화 문구를 복사해 붙이면
      화면이 사실과 다른 말을 하게 됩니다(§0-1). 아래 `NOTICE_FILL_TIMING_USD` 참고.
   5. 🔴 **두 통화를 합산한 숫자를 화면에 만들지 않습니다**(§5-11-2 오너 확정). 이 앱에는
      환율 시계열이 없고, 환율을 지어내 "총자산"을 합치는 순간 그 숫자는 사실이 아니게
      됩니다. 같은 창유형 카드 안에 위/아래로 나란히 **보여만 주고, 더하지 않습니다.**
   6. 참여(옵트인)·동의는 **트랙별로 완전히 독립**입니다(§5-11-10, 스키마 §14-10 —
      `duel_opt_in_usd()` 는 원화 계좌가 있든 없든 똑같이 동작합니다). 원화만 참여한 사용자,
      달러만 참여한 사용자가 정상적으로 존재하므로 두 블록은 각자 "계좌 있음/없음"을
      판단하고, 한쪽이 없다고 다른 쪽을 안 그리는 경로를 만들지 않습니다.
"""

from datetime import datetime, timedelta

from nicegui import ui

from utils import duel_rules
from utils.duel_db import (
    DuelDbError,
    cancel_order,
    edit_order,
    fetch_my_accounts,
    fetch_my_cash_ledger,
    fetch_my_orders,
    fetch_my_positions,
    fetch_my_snapshots,
    opt_in,
    save_order,
    save_sell_order,
    sum_cash_balance,
)
# 💵 USD 트랙 — **표 이름이 본문에 박힌 함수만** 이쪽에서 가져옵니다(§5-14 의 판단 기준 그대로).
#    `sum_cash_balance`(순수 합계)와 `DuelDbError`(예외 타입)는 통화를 모르므로 위 원화
#    모듈에서 그대로 재사용합니다 — `utils/duel_db_usd.py` 도 같은 것들을 재사용합니다.
from utils.duel_db_usd import (
    cancel_order_usd,
    edit_order_usd,
    fetch_my_accounts_usd,
    fetch_my_cash_ledger_usd,
    fetch_my_orders_usd,
    fetch_my_positions_usd,
    fetch_my_snapshots_usd,
    opt_in_usd,
    save_order_usd,
    save_sell_order_usd,
)
from utils.duel_rules import (
    ACCOUNT_WINDOW_TYPES,
    KST,
    MONTHLY_DEPOSIT_DAY,
    MONTHLY_DEPOSIT_KRW,
    MONTHLY_DEPOSIT_USD,
    ORDER_PENDING,
    SEED_AMOUNT_KRW,
    SEED_AMOUNT_USD,
    TWR_INSUFFICIENT,
    TWR_NO_DATA,
    TWR_OK,
    DuelRuleError,
)
from utils.scorecard_db import (
    KR_ALL_MARKET_PRICES_FILENAME,
    MARKET_KR,
    MARKET_US,
    SNAPSHOT_FILENAMES,
    US_ALL_ETF_PRICES_FILENAME,
    US_ALL_MARKET_PRICES_FILENAME,
    build_portfolio,
    build_universe_index,
    fetch_holdings,
    format_amount,
    make_price_lookup,
    resolve_stock_query,
    supabase_status,
    user_id_of,
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
    error_banner, esc, holdings_table_html, info_banner, metric_card, pct_text, warning_banner,
)
from web.layout import DUEL_ENABLED, DUEL_MENU_ADMIN_ONLY, layout
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file_async,
)

# 이 모듈의 통화는 원화 하나뿐입니다(스키마 `currency = 'KRW'` CHECK). 미국주식·환율은
# v1 범위 밖이고, 환율 시계열이 이 저장소 어디에도 없어 만들 수도 없습니다(작업지시서 1-1).
CURRENCY = "KRW"

# 계좌 유형 → 화면 이름. 세 계좌는 **매매 규칙이 완전히 동일**하고(2-3), 이름은 입금·정산
# 리듬을 가리키는 라벨일 뿐입니다. 규칙이 다른 것처럼 읽히는 문구를 넣지 마세요.
WINDOW_TITLES = {
    "M1": "1개월 계좌",
    "M3": "3개월 계좌",
    "M6": "6개월 계좌",
}

# 🔁 2026-08-21 — **주기적 리밸런싱 매도**가 들어오면서, 세 계좌를 가르는 유일한 규칙 차이가
#    생겼습니다: 매도 기회가 돌아오는 주기(창 길이)입니다. 30/90/180 이라는 숫자를 화면에
#    직접 적어두면 규칙이 바뀔 때 화면만 낡으므로(§0-3-10), 규칙 계층의
#    `duel_rules.REBALANCE_WINDOW_DAYS` 하나에서 문구를 만들어 씁니다.
#    🔴 이 값은 **통화를 모릅니다** — 원화·달러 트랙이 같은 창 길이를 쓰므로(스펙 확정,
#       `duel_rules` 상수 하나를 양쪽이 공유) 문구도 하나만 두고 양쪽에서 씁니다.
REBALANCE_WINDOW_TEXT = " · ".join(
    f'{WINDOW_TITLES[window_type]} {duel_rules.REBALANCE_WINDOW_DAYS[window_type]}일'
    for window_type in ACCOUNT_WINDOW_TYPES
    if window_type in WINDOW_TITLES and window_type in duel_rules.REBALANCE_WINDOW_DAYS
)

# =============================================================================
# 상시 노출 고지 3종 — 작업지시서 2-8 (§0-1: 숨기지 않고 화면에 그대로 씁니다)
# =============================================================================
NOTICE_NO_DIVIDEND = (
    "배당금은 반영되지 않습니다.\n\n"
    "이 앱에는 배당 지급 캘린더(사건별 날짜와 확정 주당 금액)가 "
    "없어서, 추정치로 배당을 흉내 내는 대신 아예 반영하지 않는 쪽을 택했습니다."
)

# ⚠️ 2-8 초안에는 이 문구가 **"그날 장 마감 후 확정된 종가로 그날 밤에 체결됩니다"** 로 적혀
#    있습니다. 그러나 같은 문서 2-4(3차 라운드에서 시간 모델을 **전면 확정**한 절)는 그 문장을
#    명시적으로 뒤집었습니다 — 주문 접수 시간대(18:00:01~22:00:00)는 그날 크롤링이 이미 끝난
#    뒤라 "그날 종가"는 사용자가 **이미 아는 값**이고, 아는 값으로 체결하면 대결이 불공정해지기
#    때문에 체결가는 **다음 거래일(D+1)의 아직 모르는 종가**로 확정됐습니다.
#    → 초안 문구를 그대로 복사하면 화면이 사실과 다른 말을 하게 됩니다(§0-1). 더 나중에 나온,
#      더 자세한 2-4 의 확정 내용을 따릅니다. 작업지시서 2-8 의 문장도 이 방향으로 정정이
#      필요합니다(문서 수정은 이 작업의 범위가 아니라 보고서에 적어 올립니다).
NOTICE_FILL_TIMING = (
    "주문은 저장 즉시 체결되지 않습니다.\n\n"
    "저장한 주문은 예약일 뿐이고, "
    "다음 거래일(D+1)의 장이 끝난 뒤 확정된 종가로 그날 밤 배치가 체결합니다."
)

# 🔁 2026-08-21 오너 확정 — 이 문구는 **사실이 바뀌어서** 다시 썼습니다. 이전 문구는
#    "매도는 지원하지 않습니다 — 한 번 산 종목은 팔 수 없고…" 였는데, 그 결정 자체가
#    이전 라운드의 대화 착오였음이 확인돼 정정됐습니다. 이제 계좌마다 정해진 주기로
#    **딱 1회씩 리밸런싱 매도**가 가능합니다(규칙 계층 §12, DB 부분 유니크 인덱스가 강제).
#    낡은 문구를 남겨두면 화면이 사실과 다른 말을 하게 되므로 통째로 교체했습니다(§0-1).
#
# 🗣️ 2026-08-22 오너 리뷰 — **"창"이 아니라 "매도 기회"를 문장의 주어로 세웁니다.**
#    오너 원문: "'창'보다도 '매도 기회'라고 하는게 직관적으로 이해될 것 같아".
#    사실(주기 30/90/180일 · 누적되지 않음 · 취소하면 다시 열림)은 **한 글자도 바뀌지
#    않았습니다** — 같은 사실을 사용자가 이미 아는 말("기회")로 부르는 것뿐입니다.
#    🔴 코드 쪽 이름(`window_index` · `window_type` · `rebalance_window_*`)은 그대로 둡니다.
#       DB 컬럼·규칙 계층과 이름이 갈라지면 화면과 저장값을 대조할 수 없게 됩니다.
NOTICE_BUY_ONLY = (
    "매수는 언제든, 매도 기회는 주기마다 딱 한 번입니다.\n\n"
    "예수금이 남아 있으면 매수는 접수 시간대 안에서 몇 번이든 할 수 있습니다.\n\n"
    f"매도 기회는 계좌마다 정해진 리밸런싱 주기({REBALANCE_WINDOW_TEXT})마다 딱 1회 "
    "돌아오고, 한 번의 기회로 종목 하나를 1주부터 전량까지 팔 수 있습니다. 쓰지 않고 "
    "흘려보낸 매도 기회는 사라지고 다음 기회에 쌓이지 않습니다.\n\n"
    "주기는 계좌 개설일이 아니라 그 계좌에 처음 주식이 들어온 날부터 셉니다 — "
    "아직 아무것도 사지 않은 계좌는 주기가 시작되지도 않았으므로 매도 기회가 먼저 "
    "사라지지 않습니다."
)

#: 화면 맨 위에 **항상** 보여야 하는 3종. 순서를 바꿔도 되지만 빼지는 마세요(2-8).
MANDATORY_NOTICES = (NOTICE_NO_DIVIDEND, NOTICE_FILL_TIMING, NOTICE_BUY_ONLY)

# 주문 저장 전에 **미리** 고지해야 하는 문구(2-4-5 — "사후 통보로 끝내지 않습니다").
# 아래 주문 폼의 체크 확인 영역에 그대로 들어갑니다.
NOTICE_CRAWL_FAILURE = (
    "⚠️ 그날 코스피 종가 수집이 실패하거나 휴장일이면, 그 날짜로 잡힌 주문은 다음 날로 "
    "미뤄지지 않고 그 자리에서 취소됩니다.\n\n"
    "취소된 주문에는 사유가 남고 예수금은 그대로 "
    "계좌에 남으니, 다음 접수 시간대에 다시 주문하시면 됩니다.\n\n"
    "수집 결과가 애매해서 사람이 확인해야 하는 날(대량 무변동 등)에는 취소하지 않고 "
    "'대기' 상태로 남겨 두었다가, 관리자가 값을 확인한 뒤 체결 또는 취소로 결론을 냅니다."
)

# 왜 다음 거래일 종가로 체결하는지 — 한 줄 설명(2-4 "왜 그날 종가가 아닌가").
NOTICE_WHY_NEXT_DAY = (
    "왜 다음 거래일 종가일까요?\n\n"
    "주문을 받는 저녁 시간대에는 오늘 종가가 이미 다 알려져 "
    "있습니다. 이미 아는 가격으로 체결하면 결과를 보고 베팅하는 셈이라 대결이 불공정해집니다.\n\n"
    "그래서 아직 아무도 모르는 값 — 다음 거래일의 종가 — 로만 체결합니다."
)

# 이월(안 쓴 현금) 설명 — 2-3 "안 쓴 현금은 소멸하지 않고 이월되며 강제 투자되지 않습니다".
NOTICE_CASH_ROLLOVER = (
    "쓰지 않은 예수금은 사라지지 않습니다.\n\n"
    "다음 달로 그대로 넘어가고, 억지로 어딘가에 "
    "투자되지도 않습니다.\n\n"
    "예수금이 남아 있는 한 언제든 매수할 수 있고, 0원이 되면 다음 "
    "입금일까지 매수만 잠깐 쉬게 됩니다(별도의 '매수 기간' 제한은 없습니다)."
)

# 수익률 문구 — 2-6 "'내 성적표'와 계산 방식이 다르다는 걸 화면 문구에도 명확히 구분해서".
NOTICE_TWR = (
    "여기 '누적 수익률'은 시간가중수익률(TWR)입니다.\n\n"
    "매달 돈이 새로 들어오는 계좌라서, "
    "단순히 '지금 자산 ÷ 처음 시드'로 계산하면 입금액이 수익처럼 보입니다(아무것도 안 사도 "
    "수익률이 오르는 착시). 그래서 입금이 있던 날은 그 입금액을 빼고 계산합니다.\n\n"
    "'내 성적표'(실제 자산) 화면의 수익률은 매입원가 대비 평가액이라 계산 방식이 아예 다릅니다 — "
    "두 숫자를 서로 비교하지 마세요."
)

# 체결가·거래일 관련 안내에서 반복되는 접수 시간대 문구. 시각은 반드시 규칙 계층 상수에서
# 만들어 씁니다(화면에 18:00 을 따로 적어두면 규칙이 바뀔 때 한쪽만 낡습니다 — §0-3-10).
ORDER_WINDOW_TEXT = (
    f"{duel_rules.ORDER_WINDOW_OPEN_TIME.strftime('%H:%M:%S')}"
    f"~{duel_rules.ORDER_WINDOW_CLOSE_TIME.strftime('%H:%M:%S')} (한국시간)"
)

# 화면이 "다음 거래일"을 추정할 때 앞으로 며칠까지 훑을지. 연휴가 길어도 그 다음 평일이
# 반드시 들어오도록 넉넉히 잡습니다(아래 `_upcoming_trading_days()` 주석 참고).
TRADING_DAY_HORIZON = 21

# 주문 내역 표에 한 번에 보여줄 최근 주문 수(대기 중 주문은 개수 제한 없이 전부 보여줍니다).
RECENT_ORDER_LIMIT = 20


# =============================================================================
# 1-USD. 💵 달러 결투 전용 상수·문구 (작업지시서 §5-11 ~ §5-17)
# =============================================================================
#  ⚠️ 위 원화 상수·문구는 **한 글자도 건드리지 않았습니다.** 아래는 전부 신규입니다.
#     여기 있는 것들의 공통점은 "통화·시장·시간대·표 이름이 문장 안에 박혀 있다"는 것입니다 —
#     그래서 공유할 수 없고, 이 트랙이 네 번 반복해 온 대로 **갈라서 새로 정의**합니다.
#     반대로 `WINDOW_TITLES`(M1/M3/M6 라벨)·`TRADING_DAY_HORIZON`(며칠 앞까지 훑을지)·
#     `RECENT_ORDER_LIMIT` 은 통화를 모르는 값이라 원화와 **그대로 공유**합니다.
# =============================================================================

# USD 트랙의 통화. 스키마 `duel_accounts_usd.currency = 'USD'` CHECK 와 같은 값입니다.
# 🔴 이 상수와 위 `CURRENCY`(원화)를 같은 계산식 안에서 만나게 하지 마세요 — 두 통화를
#    더하거나 나누는 코드가 생기는 순간 그 숫자는 환율을 지어낸 값이 됩니다(§5-11-2).
CURRENCY_USD = "USD"

# 접수 시간대 문구(달러). 원화와 **같은 방식으로** 규칙 계층 상수에서 만들어 씁니다 —
# 화면에 16:00 을 따로 적어두면 규칙이 바뀔 때 화면만 낡습니다(§0-3-10).
ORDER_WINDOW_TEXT_USD = (
    f"{duel_rules.ORDER_WINDOW_OPEN_TIME_USD.strftime('%H:%M:%S')}"
    f"~{duel_rules.ORDER_WINDOW_CLOSE_TIME_USD.strftime('%H:%M:%S')} (한국시간)"
)

NOTICE_NO_DIVIDEND_USD = (
    "배당금은 반영되지 않습니다.\n\n"
    "미국 주식 수집기에는 배당락일 한 개만 '수집 시점에 화면에 "
    "떠 있던 값'으로 들어와 있을 뿐, 사건별 지급일과 확정 주당 금액을 담은 배당 지급 "
    "캘린더가 없습니다.\n\n"
    "추정치로 배당을 흉내 내는 대신 아예 반영하지 않는 쪽을 택했습니다."
)

# 🔴 이 문구는 원화 `NOTICE_FILL_TIMING` 을 **절대 복사해 오면 안 되는 자리**입니다.
#    원화: 접수 시간대(18:00:01~22:00:00 KST)가 그날 KRX 정규장·크롤링이 끝난 **뒤**라
#          그날 종가는 사용자가 이미 아는 값 → 공정하려면 그날을 빼고 **D+1 종가**로 체결.
#    달러: 접수 시간대(16:00:01~21:00:00 KST = 03:00~08:00 ET)가 그날 미국 정규장 개장
#          (09:30 ET)보다 **한참 전**이라 그날 마감가는 아직 존재조차 하지 않음
#          → 뺄 이유가 없고, **주문을 넣은 그날 자신의 마감가**로 체결.
#    즉 두 트랙의 체결 시점은 "같은 규칙의 통화만 다른 버전"이 아니라 **정반대 방향**이며,
#    그 근거는 `utils/duel_rules.py::resolve_fill_trading_day_usd()` 의 docstring
#    (2026-08-21 작성, 작업지시서 §5-16)에 그대로 적혀 있습니다. 원화 문구를 그대로 붙이면
#    화면이 사실과 다른 안내를 하게 됩니다(§0-1).
NOTICE_FILL_TIMING_USD = (
    "주문은 저장 즉시 체결되지 않습니다.\n\n"
    "저장한 주문은 예약일 뿐이고, "
    "주문을 넣은 바로 그날의 미국 정규장 마감가로 체결됩니다"
    "(그날이 미국 증시 휴장일이면 그 뒤 가장 이른 거래일의 마감가).\n\n"
    f"접수 시간대({ORDER_WINDOW_TEXT_USD})는 그날 미국 정규장이 열리기 한참 전이라, "
    "주문하는 순간 그 마감가는 아직 세상에 존재하지 않습니다.\n\n"
    "체결 기록은 마감가가 수집된 뒤 한국 날짜로 다음 날 낮에 도는 배치가 남깁니다."
)

# 🔁 2026-08-21 — 원화와 **같은 이유로** 다시 쓴 문구입니다(위 `NOTICE_BUY_ONLY` 주석 참고).
#    창 길이(30/90/180일)는 통화와 무관하게 같으므로 `REBALANCE_WINDOW_TEXT` 를 공유하고,
#    달라지는 것은 "달러 계좌 기준으로 따로 센다"는 사실 한 줄뿐입니다(§5-11-10 트랙 독립).
NOTICE_BUY_ONLY_USD = (
    "달러 트랙도 매수는 언제든, 매도 기회는 주기마다 딱 한 번입니다.\n\n"
    "예수금이 남아 있으면 매수는 접수 시간대 안에서 몇 번이든 할 수 있습니다.\n\n"
    f"매도 기회는 계좌마다 정해진 리밸런싱 주기({REBALANCE_WINDOW_TEXT})마다 딱 1회 "
    "돌아오고, 한 번의 기회로 종목 하나를 1주부터 전량까지 팔 수 있습니다. 쓰지 않고 "
    "흘려보낸 매도 기회는 사라지고 다음 기회에 쌓이지 않습니다.\n\n"
    "주기는 그 달러 계좌에 처음 주식이 들어온 날부터 셉니다 — 원화 계좌의 주기와는 "
    "완전히 따로 흘러갑니다."
)

# 🔴 §5-11-2 오너 확정 — 화면 레이어에서도 두 통화를 섞지 않는다는 사실을 사용자에게
#    그대로 말해 둡니다. "왜 총자산 합계가 없지?"를 사용자가 버그로 오해하지 않도록,
#    없는 이유를 정직하게 밝히는 문장입니다(§0-1 — 빠진 것을 눈에 보이게 빼기).
NOTICE_NO_FX_MIX = (
    "원화 계좌와 달러 계좌의 숫자는 어디서도 더하지 않습니다.\n\n"
    "이 앱에는 환율 시계열이 "
    "없고, 환율을 지어내 두 통화를 하나의 '총자산'으로 합치는 순간 그 숫자는 사실이 "
    "아니게 됩니다.\n\n"
    "시드머니도, 정기입금도, 수익률도, 순위표도 두 트랙이 완전히 별개입니다."
)

#: 달러 블록 머리에 **항상** 보여야 하는 3종(2-8 의 USD 판) + 통화 혼합 금지 고지.
MANDATORY_NOTICES_USD = (
    NOTICE_NO_DIVIDEND_USD, NOTICE_FILL_TIMING_USD, NOTICE_BUY_ONLY_USD, NOTICE_NO_FX_MIX,
)

# 주문 저장 전에 **미리** 고지해야 하는 문구(2-4-5 의 USD 판 — 코스피가 아니라 미국 종가).
NOTICE_CRAWL_FAILURE_USD = (
    "⚠️ 그날 미국 종가 수집이 실패하거나 미국 증시 휴장일이면, 그 날짜로 잡힌 주문은 "
    "다음 날로 미뤄지지 않고 그 자리에서 취소됩니다.\n\n"
    "취소된 주문에는 사유가 남고 예수금은 "
    "그대로 계좌에 남으니, 다음 접수 시간대에 다시 주문하시면 됩니다.\n\n"
    "수집 결과가 애매해서 사람이 확인해야 하는 날에는 취소하지 않고 '대기' 상태로 남겨 "
    "두었다가, 관리자가 값을 확인한 뒤 체결 또는 취소로 결론을 냅니다."
)

# 왜 '그날' 마감가인지 — 원화의 `NOTICE_WHY_NEXT_DAY` 와 **결론이 정반대인** 설명입니다.
NOTICE_WHY_SAME_DAY_USD = (
    "왜 '그날' 마감가일까요?\n\n"
    "달러 결투의 접수 시간대는 미국 동부시각으로 새벽 3시~아침 "
    "8시라서, 그날 미국 정규장이 열리기(동부 오전 9시 30분) 한참 전입니다. 즉 주문을 "
    "받는 시점에 그날 마감가는 아직 존재조차 하지 않는 값이라, 결과를 보고 베팅하는 일이 "
    "구조적으로 불가능합니다.\n\n"
    "원화 결투가 '다음 거래일' 종가를 쓰는 것과 이유가 정반대입니다 "
    "— 원화는 접수 시간대가 그날 장이 끝난 뒤라 그날 종가를 빼야 공정해지고, 달러는 접수 "
    "시간대가 그날 장이 열리기 전이라 그날 마감가를 그대로 쓰는 것이 공정합니다."
)

NOTICE_CASH_ROLLOVER_USD = (
    "쓰지 않은 예수금은 사라지지 않습니다.\n\n"
    "다음 달로 그대로 넘어가고, 억지로 어딘가에 "
    "투자되지도 않습니다.\n\n"
    "예수금이 남아 있는 한 언제든 매수할 수 있고, $0이 되면 다음 "
    "입금일까지 매수만 잠깐 쉬게 됩니다(별도의 '매수 기간' 제한은 없습니다)."
)

NOTICE_TWR_USD = (
    "달러 계좌의 '누적 수익률'도 시간가중수익률(TWR)입니다 — 계산식은 원화 계좌와 완전히 "
    "같은 함수를 씁니다(입금이 있던 날은 그 입금액을 빼고 계산).\n\n"
    "다만 계산에 들어가는 "
    "돈은 처음부터 끝까지 달러뿐이고, 원화 계좌의 숫자는 단 한 번도 섞이지 않습니다.\n\n"
    "원화 계좌 수익률과 달러 계좌 수익률을 나란히 보시되, 두 값을 더하거나 평균 내지 "
    "마세요 — 그건 환율을 지어내는 것과 같습니다."
)


# =============================================================================
# 1. 공통 표시 도우미 (전부 순수 함수 — 상태를 갖지 않습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장. 원문·트레이스백은 화면에 내보내지 않습니다(§0-3-4).

    `web/auth_ui.py::fail_message()` 를 '내 성적표'·'사장님 보고서'와 **같은 방식**으로 씁니다
    (§0-3-10 — 화면마다 예외 번역 규칙을 새로 만들지 않습니다).
    """
    return fail_message(exc, fallback, context='결투다!')


def _parse_positive_int(raw, label: str) -> int:
    """텍스트 입력 → 양의 정수(주식 수). 콤마와 앞뒤 공백을 허용합니다.

    ⚠️ 값을 지어내지 않습니다(§0-1) — 비었거나 숫자가 아니면 예외입니다. 주문 단위는
       **주식 수**이므로 소수점은 받지 않습니다(스키마 `requested_quantity integer`).
    """
    text = str(raw or "").strip().replace(",", "")
    if not text:
        raise ValueError(f"{label}을(를) 입력해 주세요.")
    try:
        number = int(text)
    except ValueError:
        raise ValueError(f"{label}은(는) 정수(주식 수)로 입력해 주세요: {raw!r}")
    if number <= 0:
        raise ValueError(f"{label}은(는) 1주 이상이어야 합니다.")
    return number


def _upcoming_trading_days(from_date):
    """앞으로의 **거래일 후보** 목록(주말 제외 평일). `save_order()` 에 넘기는 값입니다.

    🔴 정직하게 밝혀 둡니다(§0-1) — 이건 **근사치**입니다. 이 저장소에는 앞날의 한국 증시
       휴장일을 알려주는 캘린더가 없습니다(`data/kospi200_stock_history.csv` 는 "실제로
       수집에 성공한 지난 날짜"의 기록이라 미래를 말해주지 못합니다). 그래서 화면은
       "토·일은 확실히 거래일이 아니다"는 사실만 쓰고 평일을 후보로 넘깁니다.

       **진짜 판정은 서버가 합니다.** 야간 배치가 그 날짜의 종가 수집 결과를 보고
       (`duel_rules.check_crawl_freshness()`) 휴장일·수집실패면 그 날짜에 걸린 주문을
       전부 취소하고 사유를 남깁니다(2-4-5). 즉 이 근사치 때문에 **없는 체결이 생기는 일은
       없고**, 공휴일에 걸린 주문은 "체결 안 됨 + 사유"로 정직하게 끝납니다. 그 가능성은
       주문 전에 `NOTICE_CRAWL_FAILURE` 로 미리 고지합니다.

       ⚠️ 여기서 주말을 빼는 것이 특히 중요한 이유: 금요일 저녁 주문의 다음 날은 토요일인데,
          야간 배치는 평일에만 돌기 때문에(`.github/workflows/duel_daily.yml` cron `1-5`)
          토요일로 잡힌 주문은 아무도 처리하지 않고 영영 대기 상태로 남습니다.
    """
    days = []
    for offset in range(1, TRADING_DAY_HORIZON + 1):
        day = from_date + timedelta(days=offset)
        if day.weekday() < 5:                       # 월(0)~금(4)
            days.append(day)
    return days


def _upcoming_trading_days_usd(from_date):
    """앞으로의 **미국 정규장 거래일 후보** 목록(주말 제외 평일). `save_order_usd()` 에 넘깁니다.

    🔴 원화용 `_upcoming_trading_days()` 와 **시작점이 다릅니다.** 원화는 `from_date` 의
       **다음 날**부터 후보를 만들지만, 이 함수는 **`from_date` 자신부터** 만듭니다.
       실수로 원화처럼 `range(1, …)` 로 고치면 후보 목록에 저장일 자신이 없어져서, 방금
       §5-16 에서 고친 "달러 주문은 그날 마감가로 체결" 동작이 화면 쪽에서 다시 하루
       밀립니다 — 코드가 아니라 **넘기는 목록**이 원인이라 로그에도 오류로 안 남습니다.

       근거: `utils/duel_rules.py::resolve_fill_trading_day_usd()` 는 `day >= saved_date`
       로 후보를 고르기 때문에(원화는 `day > saved_date`), **당일이 목록에 들어 있으면
       당일을, 없으면 그 뒤 가장 이른 거래일을** 돌려줍니다. 당일을 뺄지 말지를 판정하는
       코드는 그 함수 어디에도 없습니다 — 즉 "당일을 후보에 넣는다"는 결정이 온전히 이
       함수의 책임입니다. 왜 당일을 빼면 안 되는지(접수 시간대가 그날 미국장 개장 전이라
       그 마감가가 아직 존재하지 않음)는 그 함수의 docstring 에 적혀 있습니다.

    🔴 정직하게 밝혀 둡니다(§0-1) — 원화와 똑같이 이것도 **근사치**입니다. 이 저장소에는
       앞날의 미국 증시 휴장일(추수감사절·독립기념일 등)을 알려주는 캘린더가 없습니다.
       그래서 "토·일은 확실히 거래일이 아니다"는 사실만 쓰고 평일을 후보로 넘깁니다.
       **진짜 판정은 서버가 합니다** — 새벽 배치가 그 날짜의 미국 종가 수집 결과를 보고
       휴장일·수집실패면 그 날짜에 걸린 주문을 전부 취소하고 사유를 남깁니다. 그 가능성은
       주문 전에 `NOTICE_CRAWL_FAILURE_USD` 로 미리 고지합니다.
    """
    days = []
    for offset in range(0, TRADING_DAY_HORIZON + 1):    # ← 0: **저장일 자신부터** (원화는 1)
        day = from_date + timedelta(days=offset)
        if day.weekday() < 5:                       # 월(0)~금(4)
            days.append(day)
    return days


def _order_window_state(now_kst=None) -> dict:
    """지금이 주문 접수 시간대인지 — 판정은 **규칙 계층 한 곳**에서만 합니다.

    화면이 18:00/22:00 을 다시 비교하면 이 프로젝트에 "주문 시간대"의 정의가 두 개가 됩니다
    (§0-3-10). `duel_rules.resolve_order_window()` 가 유일한 정의이고, 실제 저장·수정·취소
    거절도 `utils/duel_db.py` 가 같은 함수로 판정합니다 — 화면 표시와 서버 판정이 어긋날 수
    없습니다.
    """
    return duel_rules.resolve_order_window(now_kst or datetime.now(KST))


def _window_message(window: dict) -> str:
    """접수 시간대 안내 문구(열림/닫힘 각각)."""
    if window["is_open"]:
        return (
            f"🟢 지금은 주문 접수 시간입니다 — 오늘 {ORDER_WINDOW_TEXT} 안에서 주문 저장·수량 "
            f"수정·취소를 할 수 있습니다. 지금 저장하는 주문은 다음 거래일 종가로 체결됩니다."
        )
    opens = window["window_opens_at"]
    return (
        f"🔴 지금은 주문 접수 시간이 아닙니다 — 다음 접수 시작은 "
        f"{opens.strftime('%Y-%m-%d %H:%M:%S')} 입니다(매일 {ORDER_WINDOW_TEXT}). "
        "이 시간 밖에서도 화면은 그대로 보이지만 주문 저장·수정·취소는 되지 않습니다."
    )


def _order_window_state_usd(now_kst=None) -> dict:
    """지금이 **달러 트랙** 주문 접수 시간대인지 — 판정은 규칙 계층 한 곳에서만 합니다.

    🔴 `duel_rules.resolve_order_window()`(원화, 18:00:01~22:00:00)가 아니라 반드시
       `resolve_order_window_usd()`(16:00:01~21:00:00, §5-13 오너 확정)를 씁니다.
       여기를 헷갈리면 달러 트랙 사용자가 **두 시간 어긋난** 안내를 보게 되고, 서버
       (`utils/duel_db_usd.py`)는 USD 시간대로 판정하므로 "화면은 열렸다는데 저장이
       거절되는"(또는 그 반대의) 상태가 됩니다. 이 트랙에서 실제로 반복돼 온 종류의
       사고라, `_translate_order_guard_error_usd()` 가 애초에 그 사고를 막으려고
       만들어진 함수입니다.
    """
    return duel_rules.resolve_order_window_usd(now_kst or datetime.now(KST))


def _window_message_usd(window: dict) -> str:
    """달러 트랙 접수 시간대 안내 문구(열림/닫힘 각각).

    체결 시점 표현이 원화와 다릅니다 — "다음 거래일 종가"가 아니라 **"바로 그날의 미국
    정규장 마감가"** 입니다(§5-16). 원화 문구를 복사하면 사실과 달라집니다.
    """
    if window["is_open"]:
        return (
            f"🟢 지금은 달러 결투 주문 접수 시간입니다 — 오늘 {ORDER_WINDOW_TEXT_USD} 안에서 "
            f"주문 저장·수량 수정·취소를 할 수 있습니다. 지금 저장하는 주문은 오늘 밤 열리는 "
            f"미국 정규장의 마감가로 체결됩니다."
        )
    opens = window["window_opens_at"]
    return (
        f"🔴 지금은 달러 결투 주문 접수 시간이 아닙니다 — 다음 접수 시작은 "
        f"{opens.strftime('%Y-%m-%d %H:%M:%S')} 입니다(매일 {ORDER_WINDOW_TEXT_USD}). "
        "이 시간 밖에서도 화면은 그대로 보이지만 주문 저장·수정·취소는 되지 않습니다."
    )


# =============================================================================
# 1-RB. 🔁 리밸런싱 창 상태 — **통화를 모르는 순수 계산이라 원화·달러가 공유합니다**
# =============================================================================
#  §5-11-1 의 판단 기준 그대로입니다: "데이터는 완전 분리, 순수 규칙은 공유". 창 길이도,
#  창 번호를 세는 방식도, "이번 창을 썼는가"를 판정하는 방식도 통화와 아무 상관이 없습니다
#  (규칙 계층에서도 `resolve_rebalance_window()` 하나를 두 트랙이 함께 씁니다). 그래서 아래
#  두 함수에는 `CURRENCY`/`CURRENCY_USD` 도, 금액 서식도, 표 이름도 한 글자도 없습니다 —
#  통화별로 갈라야 하는 것은 이 값을 **어느 표에서 읽어 오는가**뿐이고, 그건 아래
#  `_load_account_data()` / `_load_account_data_usd()` 가 갈라서 합니다.
# =============================================================================
def _rebalance_state(account: dict, orders, today) -> dict:
    """계좌 1개의 "지금 몇 번째 창이고, 이번 창 매도를 이미 썼는가".

    🔴 판정을 여기서 새로 만들지 않습니다(§0-3-10) — 창 번호·남은 일수·다음 창 시작일은
       전부 `duel_rules.resolve_rebalance_window()` 가 돌려준 값 그대로입니다. 이 함수가
       더하는 것은 "그 창 번호를 쓴 살아 있는 매도 주문이 이미 있는가" 하나뿐입니다.

    ⚠️ `first_holding_date` 가 없는 계좌(= 아직 아무것도 안 산 계좌)에서 규칙 함수는
       **예외를 던집니다.** 그건 사고가 아니라 정상 상태이므로(§0-1 — 시작하지도 않은 창의
       번호를 지어내지 않기 위한 의도된 예외), 여기서 잡아 `unavailable_reason` 으로 바꿔
       돌려주고 화면은 안내만 합니다. 예외가 화면까지 올라가 카드가 통째로 사라지면 안 됩니다.

    ⚠️ **취소된 매도는 창을 소진시키지 않습니다.** DB 의 부분 유니크 인덱스가
       `status <> 'cancelled'` 조건으로 걸려 있어서(Phase A 확정 — 사용자 취소든, 종가를
       못 구해 시스템이 취소한 것이든 구분하지 않습니다) 취소하면 그 창의 자리가 다시
       열립니다. 화면의 판정도 **DB 인덱스와 글자 그대로 같은 조건**이어야 합니다 —
       여기만 다르게 세면 "화면은 남았다는데 저장이 거절되는"(또는 그 반대의) 상태가 됩니다.

    반환 dict
        window             : `resolve_rebalance_window()` 결과 dict, 계산 불가면 None
        used_order         : 이번 창을 이미 쓴 살아 있는 매도 주문 행(없으면 None)
        unavailable_reason : 창을 계산할 수 없을 때의 한국어 사유(가능하면 None)
    """
    try:
        window = duel_rules.resolve_rebalance_window(
            account.get("window_type"), account.get("first_holding_date"), today)
    except DuelRuleError as exc:
        # 규칙 계층이 이미 "사람이 읽을 한국어 한 문장"으로 던집니다 — 다시 포장하지
        # 않고 그대로 전달합니다(§0-1 · `_render_opt_in()` 의 DuelDbError 처리와 같은 규율).
        return {"window": None, "used_order": None, "unavailable_reason": str(exc)}

    used = None
    for order in orders or []:
        if (order or {}).get("side") != "sell":
            continue
        if order.get("status") == "cancelled":
            continue                                # ← DB 인덱스와 같은 조건(위 주석 참고)
        if order.get("rebalance_window_index") != window["window_index"]:
            continue
        used = order
        break
    return {"window": window, "used_order": used, "unavailable_reason": None}


def _rebalance_badge_text(state: dict) -> str:
    """리밸런싱 창 상태 → 계좌 카드에 붙일 한 줄. **통화를 모릅니다**(금액이 없습니다).

    창 번호는 규칙 계층에서 **0부터** 옵니다(`duel_orders.rebalance_window_index` 에 그대로
    들어가는 값). 사람에게는 1부터 세어 보여주되, 저장되는 값과 표시값이 다르다는 사실을
    코드에 남겨 둡니다 — 나중에 "화면엔 2번째 기회인데 DB엔 1"이 버그로 보이지 않도록.

    🗣️ 2026-08-22 오너 리뷰 — 뱃지도 "몇 번째 **창**"이 아니라 "몇 번째 **매도 기회**"로
       셉니다(`NOTICE_BUY_ONLY` 위 주석 참고). 세는 값 자체는 그대로 `window_index` 입니다.
    """
    if state["window"] is None:
        return '🔁 리밸런싱 매도 기회 — 아직 계산할 수 없습니다 (첫 매수 전)'
    window = state["window"]
    ordinal = window["window_index"] + 1            # 0-기반 저장값 → 1부터 세는 표시값
    if state["used_order"] is not None:
        return (
            f'🔁 리밸런싱 매도 기회 — {ordinal}번째 기회는 이미 사용했습니다 '
            f'(다음 기회 {window["next_window_starts_on"]}부터)'
        )
    return (
        f'🔁 리밸런싱 매도 기회 — {ordinal}번째 기회, 앞으로 {window["days_remaining"]}일 남음 '
        f'({window["window_ends_on"]}까지) · 이번 기회 아직 안 씀'
    )


def _sellable_positions(positions):
    """보유 포지션 중 **실제로 팔 수 있는 것**(수량 > 0)만. 순수 함수 — 통화를 모릅니다.

    ⚠️ 상장폐지 확정 종목도 빼지 않습니다(§0-1 — 조용히 사라지는 목록을 만들지 않습니다).
       그날 확정 종가가 없으면 배치가 사유를 남기고 취소하며, 취소된 매도는 창을 소진하지
       않으므로 사용자가 잃는 것이 없습니다. 화면이 미리 골라내면 "왜 이 종목만 목록에
       없지?"라는, 아무도 답을 못 찾는 상태가 됩니다.
    """
    rows = []
    for position in positions or []:
        try:
            quantity = int(float((position or {}).get("quantity") or 0))
        except (TypeError, ValueError):
            continue                                # 값을 지어내지 않고 그냥 뺍니다
        if quantity <= 0:
            continue                                # 0주 포지션은 스키마상 정상 상태입니다
        rows.append({
            "ticker": str(position.get("ticker") or ""),
            "stock_name": position.get("stock_name") or "",
            "quantity": quantity,
        })
    rows.sort(key=lambda row: row["ticker"])
    return rows


def _order_side_text(order: dict) -> str:
    """주문 방향 → 한국어. **통화를 모르는 순수 함수**라 원화·달러가 공유합니다.

    매도에는 몇 번째 매도 기회를 쓴 주문인지도 함께 보여줍니다 — 주문 내역만 보고 "이번
    기회를 썼는지"를 되짚을 수 있어야 하기 때문입니다(창 번호는 0부터라 +1 해서 표시).

    🗣️ 2026-08-22 오너 리뷰 — 뱃지(`_rebalance_badge_text()`)가 "n번째 기회"로 세므로
       주문 내역도 **같은 말**로 셉니다. 두 자리가 다른 낱말을 쓰면 사용자가 "3번째 창"과
       "3번째 기회"가 같은 것인지 다시 추론해야 합니다.
    """
    side = (order or {}).get("side")
    if side == "sell":
        index = order.get("rebalance_window_index")
        if isinstance(index, int):
            return f'🔁 매도 ({index + 1}번째 기회)'
        return '🔁 매도'
    if side == "buy":
        return '🛒 매수'
    # §0-1 — 모르는 값을 '매수'로 위장하지 않습니다(옛 행에는 side 가 없을 수 있습니다).
    return str(side or '—')


# =============================================================================
# 2. 읽기 전용 시장 데이터 (모든 접속자에게 동일 — 개인정보가 아닙니다)
# =============================================================================
#  ⚠️ §0-3-8 의 구분선: 여기서 읽는 `data/*.json` 은 모든 접속자에게 똑같은 시세 스냅샷이라
#     프로세스 전역 캐시(`web/state.py`)를 써도 안전합니다. 사용자별 데이터(계좌·주문·현금)는
#     절대 이 경로로 흐르지 않습니다.
#  ⚠️ 유니버스 목록을 이 파일이 새로 파싱하지 않습니다 — '내 성적표'가 이미 쓰는
#     `scorecard_db.build_universe_index()` 를 **그대로** 씁니다(§0-3-10 — 코스피 상위 200
#     목록을 읽는 두 번째 경로를 만들지 않습니다).
# =============================================================================
async def _load_kospi_universe() -> dict:
    """코스피 상위 200 유니버스 인덱스 + 메타데이터. 파일이 없으면 인덱스가 빈 dict 입니다.

    반환 dict 에는 **사용자 데이터가 한 조각도 없습니다** — 종목명·종가뿐이라 함수 사이로
    자유롭게 넘겨도 §0-3-8 위반이 아닙니다.

    🔴 2026-08-21 — `async def` 로 바뀌었습니다. 반환값은 그대로이고, 파일을 읽는 동안
       이벤트 루프를 붙잡지 않습니다(이유는 `web/state.load_json_file_async` 주석 참고).
    """
    payload, _load_error = await load_json_file_async(data_path(SNAPSHOT_FILENAMES[MARKET_KR]))
    index = build_universe_index(payload, MARKET_KR) if payload is not None else {}
    metadata = (payload or {}).get("metadata") if isinstance(payload, dict) else None
    return {
        "index": index,
        "metadata": metadata,
        # 종가 조회는 '내 성적표'와 같은 함수를 씁니다(같은 값·같은 결측 처리 — §0-3-10).
        # 상위 200 밖으로 밀려난 보유 종목의 폴백(`kr_all_market_prices.json`, 3-3)은 v1
        # 화면에서 쓰지 않습니다 — 그 판정(3개월 추적/500위 밖 정리)은 배치의 몫이고,
        # 화면이 두 번째 판정 경로를 만들면 두 곳이 서로 다른 답을 낼 수 있습니다.
        "price_lookup": make_price_lookup({MARKET_KR: index}),
        "as_of": ((metadata or {}).get("last_updated_at") if isinstance(metadata, dict) else None),
    }


async def _load_us_universe() -> dict:
    """미국 상위 유니버스 인덱스 + 메타데이터. 파일이 없으면 인덱스가 빈 dict 입니다.

    위 `_load_kospi_universe()` 와 **완전히 같은 모양**이고, 시장 인자만 `MARKET_US` 로
    다릅니다. 두 함수를 하나로 합치지 않은 이유는 이 트랙의 다른 파일들과 같습니다 —
    "시장/통화가 본문에 박힌 것은 갈라 둔다". 다만 **실제 파일을 읽고 인덱스를 만드는
    계산은 '내 성적표'·'미국주식' 화면이 이미 쓰는 `build_universe_index(payload,
    MARKET_US)` 를 그대로 재사용**합니다(§0-3-10 — 미국 종목 목록을 읽는 두 번째 경로를
    만들지 않습니다). 반환 dict 에는 사용자 데이터가 한 조각도 없습니다.

    ⚠️ `as_of` 의 키가 원화와 다릅니다 — 미국 스냅샷의 메타데이터는 `last_updated_at_kst`
       입니다(`web/pages/scorecard_page.py` 가 이미 같은 키를 씁니다). 원화 쪽 키
       (`last_updated_at`)를 그대로 쓰면 조용히 `None` 이 되어 "언제 기준 값인지"가
       화면에서 사라집니다.
    """
    payload, _load_error = await load_json_file_async(data_path(SNAPSHOT_FILENAMES[MARKET_US]))
    index = build_universe_index(payload, MARKET_US) if payload is not None else {}
    metadata = (payload or {}).get("metadata") if isinstance(payload, dict) else None
    return {
        "index": index,
        "metadata": metadata,
        # 🔴 `{MARKET_US: index}` 만 넘깁니다 — 한국 인덱스를 함께 넘기면 미국 티커 조회가
        #    한국 목록을 스칠 수 있는 통로가 생깁니다(원/달러 혼용 차단, §5-11-2).
        "price_lookup": make_price_lookup({MARKET_US: index}),
        "as_of": ((metadata or {}).get("last_updated_at_kst")
                  if isinstance(metadata, dict) else None),
    }


# -----------------------------------------------------------------------------
# 2-B. 📊 '내 성적표'(실제 자산) 카드 전용 — **넓은** 현재가 폴백 목록
# -----------------------------------------------------------------------------
#  🔴 왜 위 두 로더로는 부족한가 (2026-08-22 오너 실사용 버그):
#     위 `_load_kospi_universe()` / `_load_us_universe()` 의 `price_lookup` 은 **좁은 것이
#     정답**입니다 — 결투 계좌가 거래할 수 있는 종목이 코스피 상위 200 / 미국 상위 유니버스
#     안으로 못박혀 있고, 그 계좌의 포지션은 정의상 그 목록 안에만 존재하기 때문입니다.
#     (그래서 그 로더들은 폴백을 **일부러** 쓰지 않습니다. 그 주석을 지우지 마세요.)
#     그런데 계좌 카드 줄 맨 앞에 붙는 "내 성적표" 카드가 그리는 것은 결투 포지션이 아니라
#     사용자의 **실제 증권계좌 보유 종목**(`scorecard_db.fetch_holdings()`)입니다. 이쪽은
#     코스닥·ETF 등 **무엇이든** 들어올 수 있어서, 좁은 목록으로 조회하면 멀쩡히 상장된
#     종목이 "가격을 확인하지 못해 제외"로 빠집니다(실측: KRX 상장 미국지수 ETF
#     0174R0 · 379810 · 458730 — 같은 종목이 `/scorecard` 화면에서는 정상 표시됨).
#  🔴 §0-3-10 — 그래서 **세 번째 파싱 경로를 만들지 않습니다.** '내 성적표' 화면
#     (`web/pages/scorecard_page.py::_load_market_data()`)이 이미 쓰는 파일명 상수와
#     `build_universe_index()` 를 그대로 가져다 씁니다. 미국 주식/ETF 파일을 읽는 쪽에서
#     합치는 것도 그 화면과 **글자 그대로 같은 방식**입니다(수집기가 두 파일로 나눠 저장하는
#     이유는 `utils/scorecard_db.load_us_all_etf_prices()` 독스트링 참고).
#  ⚠️ 반환 dict 에는 사용자 데이터가 한 조각도 없습니다 — 티커·이름·종가뿐이라 §0-3-8 의
#     "전역 캐시가 정답"인 쪽입니다(`web/state.py` 의 스냅샷 캐시를 그대로 탑니다).
# -----------------------------------------------------------------------------
async def _load_broad_price_fallbacks() -> dict:
    """유니버스 **밖** 종목까지 현재가를 아는 보조 목록. 파일이 없으면 빈 dict 입니다.

    반환 dict
        broad_kr_prices : 코스피+코스닥 전 종목(ETF 포함) 종가 인덱스
        broad_us_prices : 미국 전 종목 종가 인덱스(개별주식 + ETF 를 합친 것)

    ⚠️ 이 값은 **'내 성적표' 카드 전용**입니다. 결투 계좌의 포지션·주문 폼에 흘려보내면
       거래 가능 종목의 경계가 화면에서 흐려집니다(§5-11-2 의 "섞을 통로를 만들지 않기").
    """
    payload_kr, _load_error = await load_json_file_async(
        data_path(KR_ALL_MARKET_PRICES_FILENAME))
    broad_kr_prices = (build_universe_index(payload_kr, MARKET_KR)
                       if payload_kr is not None else {})

    payload_us, _load_error = await load_json_file_async(
        data_path(US_ALL_MARKET_PRICES_FILENAME))
    broad_us_prices = (build_universe_index(payload_us, MARKET_US)
                       if payload_us is not None else {})

    payload_etf, _load_error = await load_json_file_async(
        data_path(US_ALL_ETF_PRICES_FILENAME))
    us_etf_prices = (build_universe_index(payload_etf, MARKET_US)
                     if payload_etf is not None else {})
    if us_etf_prices:
        # 수집기가 주식/ETF 파일을 나눠 저장하므로 합치는 일은 읽는 쪽에서 합니다.
        # 티커 공간이 겹치지 않지만 겹치면 보통주 우선 — '내 성적표' 화면과 같은 순서입니다.
        broad_us_prices = {**us_etf_prices, **broad_us_prices}

    return {"broad_kr_prices": broad_kr_prices, "broad_us_prices": broad_us_prices}


def _universe_options(index: dict) -> dict:
    """빠른 검색 후보 {티커: "티커 · 종목명"} — 코스피 상위 200 **안에서만**.

    라벨에 티커를 앞세우는 이유는 '내 성적표'의 `_candidate_options()` 와 같습니다(이름만
    넣으면 코드 검색이 철자 순서에 우연히 걸리는 종목까지 잡습니다).
    """
    options = {}
    for ticker, stock in (index or {}).items():
        name = (stock or {}).get("name")
        if name:
            options[ticker] = f"{ticker} · {name}"
    return dict(sorted(options.items(), key=lambda kv: kv[1]))


# =============================================================================
# 3. 페이지 (공개 플래그 게이트 → 로그인 게이트)
# =============================================================================
@ui.page('/duel', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def duel_page() -> None:
    with layout('⚔️ 결투다!'):
        ui.markdown('## ⚔️ 결투다! — 덤벼라 나 자신')

        # ── 공개 게이트 ① 기능 플래그(§0-3-6 기본 숨김) ──────────────────────
        #    메뉴에 항목이 없어도 주소를 아는 사람은 들어올 수 있으므로 화면에서도 막습니다.
        if not DUEL_ENABLED:
            _render_coming_soon()
            return

        # ── 공개 게이트 ② 관리자 전용 단계 ──────────────────────────────────
        #    3단계 공개(작업지시서 2-8)의 2단계. `web/layout.py` 의 같은 상수를 봅니다.
        if DUEL_MENU_ADMIN_ONLY and not is_admin():
            _render_coming_soon()
            return

        _render_header()
        # 💵 달러 트랙 상시 고지 — 원화 고지 **뒤에 덧붙입니다**(원화 쪽은 그대로).
        _render_header_usd()

        status = supabase_status()
        if not status.available:
            _render_not_ready(status)
            return

        # ── 로그인 게이트 ────────────────────────────────────────────────────
        # 토큰이 없으면 로그인 폼만 그리고 **여기서 끝냅니다.** 아래로 내려가는 코드는
        # 전부 "이 접속자 본인의" 데이터만 다룹니다('내 성적표'와 같은 구조).
        if not has_supabase_session():
            render_auth()
            return

        # 🔴 2026-08-21 — 세션 확인 두 단계(`get_client_async` / `current_user_async`)를
        #    **한 try 안**으로 모았습니다. 둘 다 Supabase 왕복을 하는 비동기 호출이 되면서
        #    "요청이 중단됨"으로 실패할 수 있게 됐는데(§0-1 — 빈 값으로 위장 금지), 그 실패를
        #    "로그인 만료"로 오해해 **멀쩡한 토큰을 지워버리면** 안 되기 때문입니다.
        try:
            client = await get_client_async()
            if client is None:
                _render_not_ready(supabase_status())
                return
            # "지금 누가 로그인했는지"는 **이 접속 전용 클라이언트에게 직접 물어봅니다.**
            # 저장소에 캐시해둔 값을 믿지 않는 이유는 §0-3-8 그대로입니다.
            user = await current_user_async(client)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return

        user_id = user_id_of(user)
        if not user_id:
            await logout_async()                    # 끊어진 세션을 남겨두지 않습니다
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        try:
            await _render_body(client, user_id, email)
        except Exception as exc:                   # noqa: BLE001 — 트레이스백을 화면에 흘리지 않습니다
            error_banner(f'🚫 {_fail(exc, "화면을 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_coming_soon() -> None:
    """플래그가 꺼져 있거나(1단계) 관리자 전용 단계(2단계)에서 일반 접속이 들어왔을 때.

    ⚠️ "관리자에게만 열려 있습니다"라고 쓰지 않습니다 — 관리자 화면의 존재를 광고할 이유가
       없고(§0-3-9, `web/layout.py` 의 관리자 메뉴 숨김과 같은 판단), 사용자에게 필요한
       정보는 "아직 열리지 않았다" 하나뿐입니다.
    """
    warning_banner(
        '🚧 "결투다!"는 아직 준비중입니다.\n\n'
        '가상의 돈으로 하는 모의투자 대결 기능으로, 준비가 끝나면 왼쪽 메뉴에 나타납니다.\n'
        '기존 화면(한국/미국 밸류에이션, 내 성적표, 사장님 보고서)은 그대로 이용하실 수 있습니다.'
    )


def _render_header() -> None:
    """제목 + **상시 노출 고지 3종**(2-8). 이 세 문구는 로그인 여부와 무관하게 항상 보입니다."""
    ui.label(
        '가상의 돈 1천만원으로 시작하는 1개월·3개월·6개월 계좌 3개. 실제 돈은 한 푼도 오가지 '
        '않고, 실제 주식을 사지도 않습니다.'
    ).classes('vh-muted')
    for notice in MANDATORY_NOTICES:
        warning_banner(f'⚠️ {notice}')


def _render_header_usd() -> None:
    """💵 달러 결투(USD 트랙)의 **상시 노출 고지**. 원화 고지 3종 바로 아래에 붙습니다.

    원화와 같은 이유로 로그인 여부·계좌 보유 여부와 무관하게 **항상** 보입니다(2-8 의 정신).
    문구가 원화와 다른 이유는 이 파일 머리말 4·5번과 각 상수 위 주석에 적어 뒀습니다 —
    특히 체결 시점(`NOTICE_FILL_TIMING_USD`)은 원화와 **정반대 방향**입니다(§5-16).
    """
    ui.label(
        f'💵 달러 결투 — 가상의 {format_amount(SEED_AMOUNT_USD, CURRENCY_USD)}로 시작하는 '
        '미국주식 계좌 3개가 원화 계좌와 **완전히 따로** 있습니다. 참여도, 성적도, 순위표도 '
        '원화 트랙과 별개입니다.'
    ).classes('vh-muted')
    for notice in MANDATORY_NOTICES_USD:
        warning_banner(f'⚠️ {notice}')


def _render_not_ready(status) -> None:
    """Supabase 가 준비되지 않은 상태 안내 (에러가 아니라 '준비중'입니다)."""
    warning_banner(
        '🚧 결투 모듈은 아직 준비중입니다.\n\n'
        f'사유: {status.reason}\n\n'
        '이 화면이 준비되지 않아도 기존 밸류에이션 리포트(한국/미국)는 정상 동작합니다.'
    )
    with ui.expansion('🔧 오너 설정 체크리스트 (관리자용)').classes('w-full'):
        ui.markdown(
            '1. Supabase → SQL Editor 에서 `sql/duel_schema.sql` 전체 실행\n'
            '   → 결투 표 8개 + RLS + `duel_opt_in()` 함수 생성 확인\n'
            '2. Render → 서비스 → **Environment** 에 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 등록\n'
            '   → `service_role` 키는 **절대 넣지 마세요** (RLS 를 통째로 우회합니다. '
            '결투 배치용 키는 GitHub Actions Secrets 에만 둡니다)\n'
            '3. 야간 배치 워크플로우(`.github/workflows/duel_daily.yml`)가 켜져 있는지 확인\n'
            '   → 이 배치가 돌아야 주문이 체결되고 일별 스냅샷(수익률의 근거)이 쌓입니다'
        )


def _render_rules_expansion() -> None:
    """"이 대결은 어떻게 굴러가나요?" — 접어둔 규칙 설명(2-2 · 2-3 · 2-4 · 2-6).

    상시 노출 3종은 위에 이미 크게 떠 있고, 여기에는 그보다 자세한 설명을 담습니다.
    숫자는 전부 `utils/duel_rules.py` 의 상수에서 옵니다 — 화면에 따로 적어두면 규칙이
    바뀔 때 화면만 낡습니다(§0-3-10).

    📖 2026-08-21 — **읽는 방식**을 오너 요청으로 바꿨습니다(딱딱한 긴 문장 목록 → "규칙 N)"
       번호 목록 + 필요한 곳에 "예시)"). 담긴 사실·숫자·단서는 하나도 빼지 않았고, 문장을
       잇던 연결어만 번호 구조에 맞게 다듬었습니다.
    🔁 2026-08-21 — **규칙 3 은 사실이 바뀌어 통째로 다시 썼습니다.** 이전 문장은 "매도가
       안 되니까 계좌를 3개로 나눴다"를 근거로 삼고 있었는데, 주기적 리밸런싱 매도가
       들어오면서 그 전제 자체가 거짓이 됐습니다. 새 근거는 "세 계좌는 이제 각자 다른
       주기(30/90/180일)로 손볼 수 있으니, 자주 갈아타는 전략과 길게 묻어두는 전략을
       같은 조건에서 동시에 실험할 수 있다"입니다. 낡은 근거를 남겨두면 화면이 사실과
       다른 말을 하게 되므로 요약이 아니라 **새로 작성**했습니다(§0-1).
    🔴 `NOTICE_*` 상수는 문장 사이에 `\\n\\n`(문단 나눔)이 들어 있습니다. 그래서 이 상수를
       `**...**` 안에 넣으면 **굵게 표시가 빈 줄을 건너뛰는** 깨진 마크다운이 됩니다(화면에
       `**` 와 `-` 가 글자 그대로 보이던 그 증상). 굵게는 **규칙 제목 한 줄에만** 쓰고,
       상수는 반드시 그 아래 **평문 문단**으로 놓습니다.
    """
    monthly_total = MONTHLY_DEPOSIT_KRW * len(ACCOUNT_WINDOW_TYPES)
    seed_total = SEED_AMOUNT_KRW * len(ACCOUNT_WINDOW_TYPES)
    # 🔁 창 길이(30/90/180일)는 규칙 계층에서 가져옵니다 — 화면에 다시 적어두지 않습니다(§0-3-10).
    days = duel_rules.REBALANCE_WINDOW_DAYS
    with ui.expansion('📖 이 대결은 어떻게 굴러가나요? (규칙 전체 보기)').classes('w-full'):
        ui.markdown(
            f'**규칙 1) 계좌는 3개, 시드는 계좌마다 '
            f'{format_amount(SEED_AMOUNT_KRW, CURRENCY)}**\n\n'
            '참여하면 1개월·3개월·6개월 계좌가 한 번에 만들어지고, 각 계좌에 가상 현금이 '
            '들어옵니다. 시드 금액은 사용자가 바꿀 수 없습니다.\n\n'
            f'예시) {format_amount(SEED_AMOUNT_KRW, CURRENCY)} × 계좌 3개 = 시작 합계 '
            f'{format_amount(seed_total, CURRENCY)}.\n\n'
            '---\n\n'

            f'**규칙 2) 매월 {MONTHLY_DEPOSIT_DAY}일에 정기 입금이 들어옵니다**\n\n'
            f'세 계좌 **각각**에 {format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)}씩, 그날 0시 '
            '직후 들어옵니다. 6개월 계좌라고 적게 넣지 않습니다 — 세 계좌의 규칙은 완전히 '
            '같습니다.\n\n'
            f'예시) 매월 {MONTHLY_DEPOSIT_DAY}일 0시 직후 → 1개월 계좌 '
            f'{format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)}, 3개월 계좌 '
            f'{format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)}, 6개월 계좌 '
            f'{format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)} → 사용자 1명당 월 '
            f'{format_amount(monthly_total, CURRENCY)}.\n\n'
            '---\n\n'

            "**규칙 3) 세 계좌의 차이는 '손보는 주기'입니다**\n\n"
            '세 계좌는 시드도, 정기입금도, 매수 조건도, 체결 방식도 완전히 같습니다. '
            f'딱 하나 다른 것이 **얼마 만에 한 번 갈아탈 수 있는가**입니다 — '
            f'1개월 계좌는 {days["M1"]}일, 3개월 계좌는 {days["M3"]}일, 6개월 계좌는 '
            f'{days["M6"]}일마다 매도(리밸런싱) 기회가 **딱 1회씩** 돌아옵니다.\n\n'
            '매수는 예수금이 남아 있는 한 언제든 할 수 있습니다. '
            '주기마다 1회로 제한되는 것은 **매도 기회**뿐이고, 한 번의 매도 기회로 종목 '
            '하나를 1주부터 전량까지 팔 수 있습니다. 이번 매도 기회를 그냥 흘려보내면 그 '
            '기회는 사라지고 다음 기회에 쌓이지 않습니다(접수 시간대 안에서 그 매도 주문을 '
            '취소하면 이번 매도 기회는 다시 열립니다).\n\n'
            '주기를 세는 시작점은 계좌 개설일이 아니라 **그 계좌에 처음 주식이 들어온 날**'
            '입니다. 아직 아무것도 사지 않은 계좌는 주기가 시작되지도 않았으므로, 첫 매수를 '
            '하기도 전에 매도 기회가 소멸하는 일은 없습니다.\n\n'
            '그래서 계좌를 3개로 나눈 이유는 "규칙이 달라서"가 아니라, **자주 손보는 전략과 '
            '길게 묻어두는 전략을 같은 조건에서 동시에 굴려보기 위해서**입니다. 시드·입금·'
            "체결 방식까지 다르게 하면 나중에 성적이 갈렸을 때 그게 '규칙 차이' 때문인지 "
            "'내 판단' 때문인지 구분할 수 없어서, 다른 것은 주기 하나로만 두었습니다. "
            "'1개월/3개월/6개월'이라는 이름도 실제 투자 기간이 아니라 이 리밸런싱 주기(와 "
            '입금·정산이 도는 리듬)를 가리키는 라벨입니다.\n\n'
            f'예시) 1개월 계좌에서는 {days["M1"]}일에 한 번씩 종목을 갈아타 보고, 6개월 '
            f'계좌에서는 처음 고른 종목을 {days["M6"]}일 동안 그대로 두어 보세요 — 반년 뒤 두 '
            '계좌의 누적 수익률을 나란히 놓으면 "나에게는 자주 손보는 편이 나았는가"에 대한 '
            '내 데이터가 남습니다.\n\n'
            '---\n\n'

            '**규칙 4) 살 수 있는 종목은 코스피 시가총액 상위 200종목뿐입니다**\n\n'
            '거래 통화는 원화만입니다. 미국주식·코스닥·ETF 는 이 모듈에서 거래할 수 '
            '없습니다.\n\n'
            '---\n\n'

            f'**규칙 5) 주문 접수 시간은 매일 {ORDER_WINDOW_TEXT} 입니다**\n\n'
            '이 시간 안에서는 저장한 주문의 수량을 바꾸거나 취소할 수 있고, 시간이 지나면 '
            '다음 거래일 체결 대상으로 확정됩니다.\n\n'
            '예시) 접수 시간 안이라면 "10주 → 5주"로 수량을 고치는 것도, 주문을 통째로 '
            '취소하는 것도 됩니다. 시간이 지난 뒤에는 둘 다 되지 않습니다.\n\n'
            '---\n\n'

            '**규칙 6) 체결가는 주문한 날이 아니라 다음 거래일 종가입니다**\n\n'
            f'{NOTICE_WHY_NEXT_DAY}\n\n'
            '예시) 오늘 저녁 접수 시간에 넣은 주문은 오늘 종가가 아니라, 다음 거래일 장이 '
            '끝난 뒤 확정되는 그날 종가로 체결됩니다.\n\n'
            '---\n\n'

            '**규칙 7) 안 쓴 예수금은 사라지지 않고 이월됩니다**\n\n'
            f'{NOTICE_CASH_ROLLOVER}\n\n'
            '예시) 이번 달에 한 주도 사지 않았다면 그 돈은 그대로 남아, 다음 입금일에 들어온 '
            '돈과 합쳐져 있습니다.\n\n'
            '---\n\n'

            '**규칙 8) 예수금이 모자라면 살 수 있는 만큼만 체결됩니다**\n\n'
            '체결 시점에 주문 금액이 예수금을 넘으면 주문 전체가 취소되는 게 아니라, '
            '예수금으로 살 수 있는 최대 정수 수량만 체결되고 나머지는 사유와 함께 '
            '남습니다(1주도 못 사면 그때는 체결 없음으로 끝납니다).\n\n'
            '예시) 10주를 주문했는데 체결가 기준으로 예수금이 7주어치뿐이라면 → 7주만 '
            '체결되고, 나머지 3주는 사유와 함께 남습니다.\n\n'
            '---\n\n'

            "**규칙 9) '누적 수익률'은 시간가중수익률(TWR)로 계산합니다**\n\n"
            f'{NOTICE_TWR}\n\n'
            '예시) 입금일에 돈만 들어오고 아무것도 사지 않았다면 누적 수익률은 그대로입니다 '
            '— 입금은 수익이 아니기 때문입니다.\n\n'
            '---\n\n'

            "**규칙 10) 상장폐지는 평가액 0원, '가격 확인 중'은 0원이 아닙니다**\n\n"
            '확인된 상장폐지는 그 종목 평가액을 0원으로 확정합니다(손실이 손실로 보여야 '
            '하므로 수량·평단가는 지우지 않습니다). 단순히 가격을 못 구한 종목은 '
            '"가격 확인 중"으로 표시하고 **절대 0원으로 처리하지 않습니다**.'
        ).classes('vh-rule-divider')


def _render_rules_expansion_usd() -> None:
    """💵 "달러 결투는 어떻게 굴러가나요?" — 원화 규칙 설명의 USD 판(접어둔 상태).

    ⚠️ 원화 `_render_rules_expansion()` 과 **합치지 않았습니다.** 문장마다 통화 기호·
       시장 이름·시간대·체결 방향이 박혀 있어서, 하나로 합치려면 문장 전체를 인자로
       받아야 하고 그러면 "두 트랙의 문구가 실수로 같아지는" 사고를 오히려 부릅니다.
       숫자는 전부 `utils/duel_rules.py` 의 USD 상수에서 옵니다(§0-3-10).

    📖 2026-08-21 — 원화 판과 **같은 읽기 방식**("규칙 N)" 번호 목록 + "예시)")으로 바꿨습니다.
       두 함수는 여전히 따로지만, 사용자가 두 블록을 오갈 때 형식이 달라 보이면 안 되므로
       번호 매기는 방식과 말투는 원화 판과 맞춰 두었습니다(규칙 개수는 내용이 다르니 다릅니다).
    🔴 원화 판과 **똑같은 이유로** `NOTICE_*` 상수를 `**...**` 안에 넣지 않습니다 — 이 상수들은
       문장 사이에 `\\n\\n`(문단 나눔)을 품고 있어서, 굵게 표시가 빈 줄을 건너뛰면 마크다운이
       깨진 채 `**` 가 글자 그대로 화면에 나옵니다. 굵게는 규칙 제목 한 줄에만 씁니다.

    🔁 2026-08-21 — **"왜 계좌가 3개인가" 규칙(규칙 3)이 이번에 처음 들어왔습니다.** 원화 판에는
       처음부터 있었지만 달러 판에는 없어서 미뤄 뒀던 항목인데, 주기적 리밸런싱 매도가
       들어오면서 원화 쪽 근거를 통째로 다시 쓰게 됐고(그쪽 docstring 참고) 그 최종 문구를
       달러 판에도 **같은 자리·같은 형식**으로 함께 넣었습니다. 창 길이(30/90/180일)는
       통화와 무관하게 같은 값이므로 규칙 계층 상수 하나(`REBALANCE_WINDOW_DAYS`)를
       원화 판과 공유하고, 문장만 달러 트랙 기준으로 씁니다.
       그 뒤 규칙 번호가 하나씩 밀렸습니다(옛 3~10 → 4~11).
    """
    monthly_total = MONTHLY_DEPOSIT_USD * len(ACCOUNT_WINDOW_TYPES)
    seed_total = SEED_AMOUNT_USD * len(ACCOUNT_WINDOW_TYPES)
    # 🔁 원화 판과 **같은 규칙 계층 상수**에서 가져옵니다(창 길이는 통화를 모릅니다).
    days = duel_rules.REBALANCE_WINDOW_DAYS
    with ui.expansion('📖 달러 결투는 어떻게 굴러가나요? (규칙 전체 보기)').classes('w-full'):
        ui.markdown(
            f'**규칙 1) 달러 계좌는 3개, 시드는 계좌마다 '
            f'{format_amount(SEED_AMOUNT_USD, CURRENCY_USD)}**\n\n'
            '달러 트랙에 참여하면 1개월·3개월·6개월 **달러 계좌**가 한 번에 만들어지고, 각 '
            '계좌에 가상 달러가 들어옵니다. 원화 계좌와는 **다른 계좌**이고, 두 트랙의 돈은 '
            '서로 오갈 수 없습니다.\n\n'
            f'예시) {format_amount(SEED_AMOUNT_USD, CURRENCY_USD)} × 달러 계좌 3개 = 시작 합계 '
            f'{format_amount(seed_total, CURRENCY_USD)}.\n\n'
            '---\n\n'

            f'**규칙 2) 매월 {MONTHLY_DEPOSIT_DAY}일에 정기 입금이 들어옵니다**\n\n'
            f'세 달러 계좌 **각각**에 {format_amount(MONTHLY_DEPOSIT_USD, CURRENCY_USD)}씩, '
            '그날 0시 직후 들어옵니다. 6개월 계좌라고 적게 넣지 않습니다 — 세 계좌의 규칙은 '
            '완전히 같습니다.\n\n'
            f'예시) 매월 {MONTHLY_DEPOSIT_DAY}일 0시 직후 → 1개월·3개월·6개월 달러 계좌에 '
            f'{format_amount(MONTHLY_DEPOSIT_USD, CURRENCY_USD)}씩 → 달러 트랙에서 월 '
            f'{format_amount(monthly_total, CURRENCY_USD)}.\n\n'
            '---\n\n'

            "**규칙 3) 세 달러 계좌의 차이는 '손보는 주기'입니다**\n\n"
            '세 달러 계좌는 시드도, 정기입금도, 매수 조건도, 체결 방식도 완전히 같습니다. '
            f'딱 하나 다른 것이 **얼마 만에 한 번 갈아탈 수 있는가**입니다 — '
            f'1개월 계좌는 {days["M1"]}일, 3개월 계좌는 {days["M3"]}일, 6개월 계좌는 '
            f'{days["M6"]}일마다 매도(리밸런싱) 기회가 **딱 1회씩** 돌아옵니다.\n\n'
            '매수는 예수금이 남아 있는 한 언제든 할 수 있습니다. '
            '주기마다 1회로 제한되는 것은 **매도 기회**뿐이고, 한 번의 매도 기회로 종목 '
            '하나를 1주부터 전량까지 팔 수 있습니다. 이번 매도 기회를 그냥 흘려보내면 그 '
            '기회는 사라지고 다음 기회에 쌓이지 않습니다(접수 시간대 안에서 그 매도 주문을 '
            '취소하면 이번 매도 기회는 다시 열립니다).\n\n'
            '주기를 세는 시작점은 계좌 개설일이 아니라 **그 달러 계좌에 처음 주식이 들어온 '
            '날**입니다. 원화 계좌의 주기와는 완전히 따로 흘러가고, 한쪽에서 매도했다고 '
            '다른 쪽 매도 기회가 줄어들지 않습니다.\n\n'
            '그래서 달러 계좌도 3개인 이유는 "규칙이 달라서"가 아니라, **자주 손보는 전략과 '
            '길게 묻어두는 전략을 같은 조건에서 동시에 굴려보기 위해서**입니다. 시드·입금·'
            "체결 방식까지 다르게 하면 나중에 성적이 갈렸을 때 그게 '규칙 차이' 때문인지 "
            "'내 판단' 때문인지 구분할 수 없어서, 다른 것은 주기 하나로만 두었습니다. "
            "'1개월/3개월/6개월'이라는 이름도 실제 투자 기간이 아니라 이 리밸런싱 주기(와 "
            '입금·정산이 도는 리듬)를 가리키는 라벨입니다.\n\n'
            f'예시) 1개월 달러 계좌에서는 {days["M1"]}일에 한 번씩 종목을 갈아타 보고, 6개월 '
            f'달러 계좌에서는 처음 고른 종목을 {days["M6"]}일 동안 그대로 두어 보세요 — 반년 뒤 '
            '두 계좌의 누적 수익률을 나란히 놓으면 "나에게는 자주 손보는 편이 나았는가"에 '
            '대한 내 데이터가 남습니다.\n\n'
            '---\n\n'

            '**규칙 4) 살 수 있는 종목은 뉴욕·나스닥 시가총액 상위 유니버스뿐입니다**\n\n'
            '미국주식 화면이 쓰는 바로 그 목록이고, 거래 통화는 달러로만입니다. '
            '코스피·코스닥·원화 종목은 이 트랙에서 거래할 수 없습니다.\n\n'
            '---\n\n'

            f'**규칙 5) 주문 접수 시간은 매일 {ORDER_WINDOW_TEXT_USD} 입니다**\n\n'
            '원화 트랙(저녁)과 **다른 시간대**입니다. 이 시간 안에서는 저장한 주문의 수량을 '
            '바꾸거나 취소할 수 있습니다.\n\n'
            '예시) 같은 날이라도 원화 주문과 달러 주문은 서로 다른 시간에 넣어야 합니다 — '
            '달러 접수 시간에 원화 주문을 넣을 수는 없습니다.\n\n'
            '---\n\n'

            "**규칙 6) 체결가는 '주문을 넣은 바로 그날'의 미국 정규장 마감가입니다**\n\n"
            f'{NOTICE_WHY_SAME_DAY_USD}\n\n'
            '예시) 오늘 새벽 접수 시간에 넣은 주문은 그날 밤(한국시간) 열리는 미국장의 '
            '마감가로 체결됩니다 — 주문할 때는 아직 존재하지 않는 값입니다.\n\n'
            '---\n\n'

            '**규칙 7) 안 쓴 예수금은 사라지지 않고 이월됩니다**\n\n'
            f'{NOTICE_CASH_ROLLOVER_USD}\n\n'
            '예시) 이번 달에 한 주도 사지 않았다면 그 달러는 그대로 남아, 다음 입금일에 들어온 '
            '달러와 합쳐져 있습니다.\n\n'
            '---\n\n'

            '**규칙 8) 예수금이 모자라면 살 수 있는 만큼만 체결됩니다**\n\n'
            '체결 시점에 주문 금액이 예수금을 넘으면 주문 전체가 취소되는 게 아니라, '
            '예수금으로 살 수 있는 최대 정수 수량만 체결되고 나머지는 사유와 함께 '
            '남습니다(1주도 못 사면 그때는 체결 없음으로 끝납니다).\n\n'
            '예시) 10주를 주문했는데 마감가 기준으로 예수금이 7주어치뿐이라면 → 7주만 '
            '체결되고, 나머지 3주는 사유와 함께 남습니다.\n\n'
            '---\n\n'

            "**규칙 9) 달러 계좌의 '누적 수익률'도 시간가중수익률(TWR)입니다**\n\n"
            f'{NOTICE_TWR_USD}\n\n'
            '예시) 입금일에 달러만 들어오고 아무것도 사지 않았다면 누적 수익률은 그대로입니다 '
            '— 입금은 수익이 아니기 때문입니다.\n\n'
            '---\n\n'

            '**규칙 10) 원화와 달러는 어디서도 더하지 않습니다**\n\n'
            f'{NOTICE_NO_FX_MIX}\n\n'
            "예시) 화면에 '원화+달러 총자산' 같은 합계가 보이지 않는 것은 빠뜨린 것이 아니라, "
            '만들지 않기로 한 것입니다.\n\n'
            '---\n\n'

            "**규칙 11) 상장폐지는 평가액 $0, '가격 확인 중'은 $0이 아닙니다**\n\n"
            '확인된 상장폐지는 그 종목 평가액을 $0으로 확정합니다(손실이 손실로 보여야 하므로 '
            '수량·평단가는 지우지 않습니다). 단순히 가격을 못 구한 종목은 '
            '"가격 확인 중"으로 표시하고 **절대 $0으로 처리하지 않습니다**.'
        ).classes('vh-rule-divider')


# =============================================================================
# 4. 로그인 후 본문
# =============================================================================
async def _render_body(client, user_id: str, email) -> None:
    """로그인 후 화면 전체.

    ⚠️ `client` 와 `user_id` 는 **반드시 인자로 받습니다.** 이 아래 어떤 함수도 "지금 누가
       로그인했는지"를 전역이나 저장소에서 다시 추측하지 않습니다(§0-3-8 함수 설계 원칙).
    """
    # 🔴 2026-08-21 — `async def` 입니다. `sign_out()` 도 Supabase 왕복(동기 HTTP)이라,
    #    로그아웃 버튼 하나가 접속자 전원의 이벤트 루프를 붙잡고 있었습니다.
    async def _logout_click() -> None:
        await logout_async()
        ui.navigate.reload()

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.label(f'로그인: {email or user_id}').classes('flex-1 min-w-0 truncate vh-muted')
        ui.button('로그아웃', on_click=_logout_click).props('flat dense no-caps').classes('shrink-0')

    _render_rules_expansion()
    _render_rules_expansion_usd()

    market = await _load_kospi_universe()          # 읽기 전용 시세 (사용자 데이터 아님)
    if not market["index"]:
        error_banner(
            '🚫 코스피 상위 200 종목 스냅샷(data/kospi200_pegy_latest.json)을 읽지 못했습니다. '
            '주문 가능 종목 목록과 보유 종목 평가금액을 표시할 수 없습니다 — 값을 추정하지 않습니다.'
        )

    # 💵 달러 트랙의 시세 스냅샷. 원화와 **완전히 별개의 dict** 로 들고 다닙니다 — 두 시장의
    #    인덱스를 한 dict 에 합치면 티커 조회가 서로의 목록을 스칠 수 있는 통로가 생깁니다.
    market_usd = await _load_us_universe()
    if not market_usd["index"]:
        error_banner(
            '🚫 미국 종목 스냅샷(data/us_stocks_latest.json)을 읽지 못했습니다. '
            '달러 트랙의 주문 가능 종목 목록과 보유 종목 평가금액을 표시할 수 없습니다 — '
            '값을 추정하지 않습니다. (원화 트랙은 그대로 이용하실 수 있습니다.)'
        )

    # 📊 '내 성적표'(실제 자산) 카드 전용 폴백 목록 — **여기서 한 번만** 읽습니다(2-B 절).
    #    결투 계좌의 시세(`market`/`market_usd`)와는 끝까지 별개의 값으로 들고 다닙니다.
    #    파일이 없어도 배너를 띄우지 않습니다 — 이건 없어도 되는 **보조** 목록이고, 없으면
    #    성적표 카드가 예전처럼 "가격을 확인하지 못한 종목"을 정직하게 표시할 뿐입니다.
    broad_prices = await _load_broad_price_fallbacks()

    # 접수 시간대는 **화면을 연 시각 기준**으로 한 번만 판정합니다. 화면을 열어둔 채 시간이
    # 지나면 안내가 낡을 수 있는데, 그 경우에도 실제 저장·수정·취소는 서버(`duel_db`)가 같은
    # 규칙으로 다시 판정해 거절하므로 "화면만 믿고 통과"하는 경로는 없습니다(§0-3-1 — 화면을
    # 실시간처럼 보이게 만들지 않습니다).
    window = _order_window_state()
    if window["is_open"]:
        info_banner(_window_message(window))
    else:
        warning_banner(_window_message(window))
    ui.label(
        f'※ 위 시간 안내는 이 화면을 연 시각({window["now_kst"].strftime("%Y-%m-%d %H:%M:%S")} '
        '한국시간) 기준입니다. 시간이 지났다면 새로고침해 주세요.'
    ).classes('vh-muted')

    # 💵 달러 트랙의 접수 시간대는 **다른 시각**(16:00:01~21:00:00)이라 별도로 판정해
    #    별도로 안내합니다. 같은 화면 안에 두 안내가 나란히 뜨는 것이 정상입니다 —
    #    하나로 합치면 반드시 한쪽이 틀린 시각을 말하게 됩니다.
    window_usd = _order_window_state_usd()
    if window_usd["is_open"]:
        info_banner(_window_message_usd(window_usd))
    else:
        warning_banner(_window_message_usd(window_usd))

    # 계좌 목록은 **이 refreshable 안에서 매번 새로 조회**합니다. 참여/주문/수정/취소 후
    # `.refresh()` 만 부르면 이 블록만 다시 그려집니다('내 성적표'와 같은 방식).
    # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
    #    · 직접 부를 때는 반드시 `await`, 처리기 쪽 `.refresh()` 는 동기 호출 그대로.
    @ui.refreshable
    async def duel_section() -> None:
        await _render_duel_section(client, user_id, market, window, duel_section.refresh,
                                   market_usd=market_usd, window_usd=window_usd,
                                   broad_prices=broad_prices)

    await duel_section()


# -----------------------------------------------------------------------------
# 4-B. 🔁 계좌별 포지션·주문을 **한 번씩만** 읽어 화면 전체가 나눠 쓰는 묶음
# -----------------------------------------------------------------------------
#  🔴 왜 이 함수가 생겼는가 (2026-08-21, 리밸런싱 매도 추가):
#     주문 폼의 매도 칸은 **보유 수량**(팔 수 있는 상한)과 **그 계좌의 주문 목록**(이번 창을
#     이미 썼는지)을 둘 다 알아야 그릴 수 있습니다. 그런데 그 두 값은 이미 화면 다른 곳에서
#     읽고 있었습니다 — 포지션은 `_render_account_card()` 가, 주문은 `_render_account_orders()`
#     가 각자 자기 안에서. 매도 칸이 같은 것을 또 읽으면 이 화면의 Supabase 왕복이 계좌 수
#     × 2 만큼 늘어납니다(이 파일 머리말 · `_render_duel_section()` 독스트링의 "13번" 참고 —
#     이 화면은 이 프로젝트에서 왕복이 가장 많은 화면입니다).
#     그래서 **읽는 자리를 위로 한 번 올리고**, 카드·주문 목록·주문 폼이 같은 묶음을 나눠
#     쓰게 했습니다. 총 왕복 수는 **바뀌지 않습니다**(옮겼을 뿐입니다).
#  🔴 §5-11-2 — 원화용과 달러용을 **갈라 둡니다.** 한 함수가 `fetch_my_positions` 와
#     `fetch_my_positions_usd` 를 함께 부르면 두 트랙의 값이 한 자리에 모이고, 그게 합산
#     코드가 생기는 첫 단추입니다(`tests/test_duel_page_usd.py` 가 이 조건을 검사합니다).
#  🔴 §0-1 — 계좌 하나의 조회가 실패해도 **다른 계좌를 삼키지 않습니다.** 실패한 계좌는
#     `error` 에 예외를 담아 두고, 그 카드·그 주문 목록만 실패로 표시합니다(예전에 각
#     함수가 자기 try 안에서 하던 것과 같은 범위의 격리를 그대로 유지합니다).
# -----------------------------------------------------------------------------
async def _load_account_data(client, accounts) -> dict:
    """원화 계좌별 {예수금·포지션·주문} 묶음 — `{account_id: {"cash", "positions", "orders", "error"}}`.

    💰 2026-08-22 — `cash` 가 여기로 **올라왔습니다.** 예수금은 원래 `_render_account_card()`
       가 자기 안에서 `fetch_my_cash_ledger()` 로 읽던 값인데, 화면 아래쪽 주문 폼도 같은
       값을 보여줘야 해서(오너 요청: "여기만 봐서는 내가 얼마나 주문을 더 할 수 있을 지 알
       수가 없어") 포지션·주문과 **같은 자리**로 옮겼습니다. 카드는 묶음에 `cash` 가 있으면
       자기 조회를 건너뛰므로 **왕복 수는 그대로**입니다(§0-3-2 — 옮긴 것이지 늘린 게
       아닙니다). 계산은 기존 순수 함수 `sum_cash_balance()` 를 그대로 씁니다.
    """
    bundles = {}
    for account in accounts or []:
        account_id = (account or {}).get("id")
        try:
            ledger = await run_blocking(fetch_my_cash_ledger, client, account_id)
            cash = sum_cash_balance(ledger)        # 순수 계산 — 왕복이 아닙니다
            positions = await run_blocking(fetch_my_positions, client, account_id)
            orders = await run_blocking(fetch_my_orders, client, account_id)
        except Exception as exc:                   # noqa: BLE001 — 계좌 단위로만 실패시킵니다
            bundles[account_id] = {"cash": None, "positions": None, "orders": None,
                                   "error": exc}
            continue
        bundles[account_id] = {"cash": cash, "positions": positions, "orders": orders,
                               "error": None}
    return bundles


async def _load_account_data_usd(client, accounts) -> dict:
    """달러 계좌별 {예수금·포지션·주문} 묶음. 위 원화 함수의 미러 — **다른 표**를 읽는 것만 다릅니다.

    ⚠️ 원화 조회 함수를 하나라도 섞어 부르면 달러 화면에 원화 트랙의 숫자가 나옵니다.
       (`sum_cash_balance()` 는 통화를 모르는 순수 합계라 원화와 공유합니다 — 이 파일이
       이미 두 계좌 카드에서 그렇게 쓰고 있습니다.)
    """
    bundles = {}
    for account in accounts or []:
        account_id = (account or {}).get("id")
        try:
            ledger = await run_blocking(fetch_my_cash_ledger_usd, client, account_id)
            cash = sum_cash_balance(ledger)        # 순수 계산 — 원화와 공유
            positions = await run_blocking(fetch_my_positions_usd, client, account_id)
            orders = await run_blocking(fetch_my_orders_usd, client, account_id)
        except Exception as exc:                   # noqa: BLE001 — 계좌 단위로만 실패시킵니다
            bundles[account_id] = {"cash": None, "positions": None, "orders": None,
                                   "error": exc}
            continue
        bundles[account_id] = {"cash": cash, "positions": positions, "orders": orders,
                               "error": None}
    return bundles


def _bundle_for(bundles, account_id) -> dict:
    """계좌 묶음 꺼내기 — 없으면 "아직 못 읽음"이 아니라 **빈 묶음**을 돌려줍니다.

    묶음을 넘기지 않은 옛 호출부·테스트 스텁에서도 화면이 그려져야 하므로(이 파일이 이미
    `market_usd=None` 에 쓰는 것과 같은 방식), 여기서는 조용히 빈 값을 만들지 말고
    호출부가 "묶음이 없다"를 구분할 수 있게 `None` 필드를 그대로 둡니다.

    💰 `cash` 도 같은 규칙입니다 — `None` 은 "예수금 0원"이 아니라 "아직 못 읽음"입니다
       (§0-1 — 못 읽은 것을 0 으로 위장하지 않습니다).
    """
    bundle = (bundles or {}).get(account_id)
    if not isinstance(bundle, dict):
        return {"cash": None, "positions": None, "orders": None, "error": None}
    return bundle


async def _render_duel_section(client, user_id: str, market: dict, window: dict, on_changed,
                               *, market_usd=None, window_usd=None,
                               broad_prices=None) -> None:
    """계좌가 있으면 대결 화면을, 없으면 참여 안내를 그립니다.

    💵 2026-08-21 — 달러 트랙이 추가되면서 **두 통화를 각자 독립적으로 판정**합니다
       (§5-11-10 — 옵트인·동의는 트랙별로 완전히 독립이고, 스키마 §14-10 의
       `duel_opt_in_usd()` 도 원화 계좌 존재 여부와 무관하게 동작합니다).
       그래서 아래 네 경우가 **전부 정상 상태**이고, 어느 하나도 다른 쪽 렌더링을 막지
       않습니다: ① 둘 다 참여 ② 원화만 참여 ③ 달러만 참여 ④ 둘 다 미참여.
       `market_usd`/`window_usd` 가 None 이면(옛 호출부·테스트 스텁) 달러 블록을 통째로
       건너뛰고 **예전과 완전히 같은 원화 전용 화면**을 그립니다.

    📊 `broad_prices`(2-B 절)는 **'내 성적표' 카드에만** 흘려보내는 폴백 시세입니다. 결투
       계좌의 포지션·주문 폼은 이 값을 절대 보지 않습니다 — 거래 가능 종목의 경계가
       화면에서 흐려지면 안 되기 때문입니다. None 이면(옛 호출부·테스트 스텁) 성적표
       카드가 유니버스 안 종목만 값매김하던 **예전 동작 그대로**입니다.

    🔴 2026-08-21 — 이 화면은 이 프로젝트에서 **Supabase 왕복이 가장 많은 화면**입니다.
       계좌 목록 1회 + 계좌 3개 × (현금원장·포지션·스냅샷) 3회 + 계좌 3개 × 주문 1회
       = 최소 **13번**의 동기 HTTP 왕복이 한 번 그릴 때마다 일어납니다. 그 전부가 예전에는
       이벤트 루프 위에서 돌았고, 한 사람이 이 화면을 여는 동안 **접속자 전원**의 연결이
       끊길 수 있었습니다(`web/blocking.py` 모듈 독스트링 — 2026-08-21 사고).
       그래서 이 아래 사슬(`_render_accounts` → `_render_account_card`,
       `_render_orders_section` → `_render_account_orders`)이 전부 `async def` 입니다.
       중간 한 군데라도 동기로 되돌리면 그 지점에서 다시 루프가 막히므로 사슬을 끊지 마세요.
    """
    try:
        accounts = await run_blocking(fetch_my_accounts, client, user_id)
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "가상계좌를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    # 🔒 이중 방어 — RLS 가 이미 남의 행을 막지만, 혹시라도 섞여 온 행은 그리지 않습니다(§0-3-8).
    mine = [a for a in accounts if a.get("user_id") == user_id]
    if len(mine) != len(accounts):
        error_banner(
            '🚫 계좌 목록에 본인 것이 아닌 행이 섞여 있어 화면을 그리지 않았습니다. '
            '관리자에게 알려 주세요.'
        )
        return

    # ── 💵 달러 계좌를 **완전히 따로** 조회합니다 ────────────────────────────────
    #    다른 표(`duel_accounts_usd`)·다른 함수(`fetch_my_accounts_usd`)이고, 실패해도
    #    원화 화면을 막지 않습니다(트랙 독립 — 한쪽 장애가 다른 쪽을 삼키지 않게).
    mine_usd = []
    if market_usd is not None and window_usd is not None:
        try:
            accounts_usd = await run_blocking(fetch_my_accounts_usd, client, user_id)
        except Exception as exc:                   # noqa: BLE001
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

    usd_available = market_usd is not None and window_usd is not None

    if not mine and not mine_usd:
        # 아직 어느 트랙에도 참여하지 않은 사용자 — 두 참여 안내를 **각각** 보여줍니다.
        _render_opt_in(client, user_id, on_changed)
        if usd_available:
            _render_opt_in_usd(client, user_id, on_changed)
        return

    # 🔁 계좌별 포지션·주문을 **여기서 한 번씩만** 읽습니다(4-B 절 참고). 아래 카드·주문
    #    폼·주문 내역이 같은 묶음을 나눠 쓰므로 왕복 수는 예전과 같고, 매도 칸이 필요로
    #    하는 "보유 수량 + 이번 창 사용 여부"가 추가 조회 없이 확보됩니다.
    #    🔴 두 통화를 **각자 다른 함수**로 읽습니다 — 한 함수가 양쪽 표를 만나지 않게(§5-11-2).
    bundles = await _load_account_data(client, mine) if mine else {}
    bundles_usd = await _load_account_data_usd(client, mine_usd) if mine_usd else {}

    await _render_accounts(client, user_id, mine, market, on_changed,
                           usd_accounts=mine_usd, usd_market=market_usd,
                           bundles=bundles, usd_bundles=bundles_usd,
                           broad_prices=broad_prices)

    # 통화별 주문 창·주문 내역. 참여한 트랙의 것만 그립니다 — 원화만 참여한 사용자에게
    # 원화 부분은 예전과 **완전히 같은 순서**(계좌 → 주문 창 → 내 주문)로 이어집니다.
    if mine:
        ui.separator()
        _render_order_form(client, user_id, mine, market, window, on_changed,
                           bundles=bundles)
        ui.separator()
        await _render_orders_section(client, user_id, mine, window, on_changed,
                                     bundles=bundles,
                                     price_lookup=market["price_lookup"])
    if mine_usd:
        ui.separator()
        _render_order_form_usd(client, user_id, mine_usd, market_usd, window_usd, on_changed,
                               bundles=bundles_usd)
        ui.separator()
        await _render_orders_section_usd(client, user_id, mine_usd, window_usd, on_changed,
                                         bundles=bundles_usd,
                                         price_lookup=market_usd["price_lookup"])

    # 아직 참여하지 않은 트랙의 안내는 **맨 아래**에 붙입니다(이미 쓰고 있는 트랙의 흐름을
    # 중간에서 끊지 않기 위해서). 두 트랙의 참여는 서로 완전히 독립입니다(§5-11-10).
    if not mine:
        ui.separator()
        _render_opt_in(client, user_id, on_changed)
    if usd_available and not mine_usd:
        ui.separator()
        _render_opt_in_usd(client, user_id, on_changed)


# =============================================================================
# 5. 참여(옵트인) — 작업지시서 2-1 / 미결항목 2번
# =============================================================================
def _render_opt_in(client, user_id: str, on_changed) -> None:
    """아직 참여하지 않은 사용자에게 보여주는 안내 + '모듈 참여하기' 버튼.

    ⚠️ `user_id` 를 인자로 받지만 `opt_in()` 에는 넘기지 않습니다 — 넘길 수가 없습니다.
       참여 대상은 앱이 정하지 않고 DB 안에서 로그인 토큰의 주인(`auth.uid()`)으로만
       정해집니다(`utils/duel_db.py::opt_in()` 독스트링 · 스키마 §9-10). 여기서 `user_id` 는
       "이 화면이 누구를 위해 그려지고 있는지"를 코드에 남겨 두는 용도이고, 참여 직후
       목록을 다시 읽을 때 그 값으로 조회합니다.
    """
    total_seed = SEED_AMOUNT_KRW * len(ACCOUNT_WINDOW_TYPES)
    monthly_total = MONTHLY_DEPOSIT_KRW * len(ACCOUNT_WINDOW_TYPES)

    with ui.card().classes('vh-card w-full'):
        ui.markdown('#### 🙋 아직 참여하지 않으셨습니다')
        ui.markdown(
            '"참여하기"를 누르면 아래 내용이 **즉시** 적용됩니다.\n\n'
            f'- 1개월·3개월·6개월 **가상계좌 3개**가 한 번에 만들어집니다(개수는 고를 수 없습니다).\n'
            f'- 각 계좌에 가상 시드머니 {format_amount(SEED_AMOUNT_KRW, CURRENCY)}씩, '
            f'합계 {format_amount(total_seed, CURRENCY)}이 바로 들어옵니다.\n'
            f'- 이후 매월 {MONTHLY_DEPOSIT_DAY}일에 세 계좌 각각 '
            f'{format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)}씩'
            f'(월 합계 {format_amount(monthly_total, CURRENCY)}) 추가 입금됩니다.\n'
            '- 거래는 **코스피 상위 200종목·원화**만 다룹니다. 매수는 예수금이 있으면 '
            '언제든 할 수 있고, **매도**는 계좌마다 정해진 리밸런싱 주기'
            f'({REBALANCE_WINDOW_TEXT}) 안에서 **딱 1회**씩 할 수 있습니다.\n'
            '- **배당금은 반영되지 않습니다.** 주문은 저장 즉시 체결되지 않고 '
            '**다음 거래일 종가**로 체결됩니다.\n'
            '- 여기서 오가는 돈은 전부 **가상**입니다. 실제 계좌·실제 주식과는 아무 관계가 없습니다.'
        )
        ui.label(
            '※ 참여해도 성적이 다른 사람에게 공개되지 않습니다. 공개 순위표는 별도의 동의 절차를 '
            '거친 뒤에만 참여할 수 있고, 아직 준비 중입니다.'
        ).classes('vh-muted')

        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _join() -> None:
            message.text = ''
            try:
                # 계좌 3개 개설 + 시드 지급을 DB 함수 하나가 처리합니다 — 이 모듈에서
                # 가장 오래 걸리는 단일 왕복이라 반드시 이벤트 루프 밖에서 돌립니다.
                accounts = await run_blocking(opt_in, client)
            except DuelDbError as exc:
                # `opt_in()` 이 이미 "사람이 읽을 한국어 한 문장"으로 번역해 둔 오류입니다
                # (스키마 미설치 / 로그인 만료 / 권한 없음 등). 그대로 보여줍니다 —
                # 여기서 다시 포장하면 원인이 흐려집니다(§0-1).
                message.text = f'🚫 {exc}'
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True,
                          close_button='닫기', timeout=0, position='center',
                          classes='text-lg whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                text = _fail(exc, '참여를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
                message.text = f'🚫 {text}'
                ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
                return
            ui.notify(
                f'✅ 참여 완료 — 가상계좌 {len(accounts)}개와 시드머니가 들어왔습니다.\n'
                f'주문은 {ORDER_WINDOW_TEXT} 사이에 저장할 수 있습니다.',
                type='positive', multi_line=True, close_button='닫기',
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        ui.button('⚔️ 모듈 참여하기', on_click=_join).props('no-caps color=primary')


def _render_opt_in_usd(client, user_id: str, on_changed) -> None:
    """💵 달러 트랙 참여 안내 + '달러 결투 참여하기' 버튼.

    ⚠️ 원화 `_render_opt_in()` 과 **완전히 독립**입니다(§5-11-10 확정 · 스키마 §14-10).
       원화에 이미 참여한 사용자에게도, 아직 안 한 사용자에게도 **똑같이** 보입니다 —
       `duel_opt_in_usd()` 는 원화 계좌 존재 여부를 전혀 보지 않기 때문입니다.
       반대로 달러만 참여하고 원화는 참여하지 않는 것도 정상 상태입니다.

    ⚠️ `opt_in_usd()` 도 원화와 같은 이유로 **인자가 클라이언트 하나뿐**입니다 — 대상자는
       앱이 정하지 않고 DB 안에서 `auth.uid()` 로만 정해집니다. `user_id` 를 끼워 넣을
       자리를 만들지 마세요(RPC 가 아예 인자를 받지 않습니다).
    """
    total_seed = SEED_AMOUNT_USD * len(ACCOUNT_WINDOW_TYPES)
    monthly_total = MONTHLY_DEPOSIT_USD * len(ACCOUNT_WINDOW_TYPES)

    with ui.card().classes('vh-card w-full'):
        ui.markdown('#### 💵 달러 결투에는 아직 참여하지 않으셨습니다')
        ui.markdown(
            '"달러 결투 참여하기"를 누르면 아래 내용이 **즉시** 적용됩니다. '
            '원화 결투와는 **완전히 별개**이고, 한쪽에 참여했다고 다른 쪽이 따라오지 않습니다.\n\n'
            '- 1개월·3개월·6개월 **달러 가상계좌 3개**가 한 번에 만들어집니다'
            '(개수는 고를 수 없습니다).\n'
            f'- 각 계좌에 가상 시드머니 {format_amount(SEED_AMOUNT_USD, CURRENCY_USD)}씩, '
            f'합계 {format_amount(total_seed, CURRENCY_USD)}가 바로 들어옵니다.\n'
            f'- 이후 매월 {MONTHLY_DEPOSIT_DAY}일에 세 계좌 각각 '
            f'{format_amount(MONTHLY_DEPOSIT_USD, CURRENCY_USD)}씩'
            f'(월 합계 {format_amount(monthly_total, CURRENCY_USD)}) 추가 입금됩니다.\n'
            '- 거래는 **미국 상위 유니버스 종목·달러**만 다룹니다. 매수는 예수금이 있으면 '
            '언제든 할 수 있고, **매도**는 달러 계좌마다 정해진 리밸런싱 주기'
            f'({REBALANCE_WINDOW_TEXT}) 안에서 **딱 1회**씩 할 수 있습니다.\n'
            '- **배당금은 반영되지 않습니다.** 주문은 저장 즉시 체결되지 않고 '
            '**주문을 넣은 바로 그날의 미국 정규장 마감가**로 체결됩니다'
            '(원화 트랙의 "다음 거래일 종가"와 다릅니다 — 이유는 위 규칙 설명 참고).\n'
            f'- 주문 접수 시간대도 원화와 다릅니다 — 매일 {ORDER_WINDOW_TEXT_USD}.\n'
            '- 여기서 오가는 돈은 전부 **가상**입니다. 실제 계좌·실제 주식과는 아무 관계가 없습니다.'
        )
        ui.label(
            '※ 참여해도 성적이 다른 사람에게 공개되지 않습니다. 달러 트랙의 공개 순위표는 '
            '원화와 완전히 별개의 표이고, 공개 동의도 트랙마다 따로 받습니다.'
        ).classes('vh-muted')

        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _join_usd() -> None:
            message.text = ''
            try:
                accounts = await run_blocking(opt_in_usd, client)
            except DuelDbError as exc:
                message.text = f'🚫 {exc}'
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True,
                          close_button='닫기', timeout=0, position='center',
                          classes='text-lg whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                text = _fail(exc, '달러 트랙 참여를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
                message.text = f'🚫 {text}'
                ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
                return
            ui.notify(
                f'✅ 달러 결투 참여 완료 — 달러 가상계좌 {len(accounts)}개와 시드머니가 '
                f'들어왔습니다.\n주문은 {ORDER_WINDOW_TEXT_USD} 사이에 저장할 수 있습니다.',
                type='positive', multi_line=True, close_button='닫기',
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        ui.button('💵 달러 결투 참여하기', on_click=_join_usd).props('no-caps color=primary')


# =============================================================================
# 6. 계좌 3개 비교 (2-8 — 총자산·현금·평가액·TWR·보유종목)
# =============================================================================
def _position_rows(positions, price_lookup):
    """보유 포지션 → 화면용 행 + 합계. **가격을 모르면 지어내지 않습니다**(§0-1).

    · 상장폐지 확정(`status='delisted'`) → 평가액 **0원**으로 확정(3-1. 확인된 사실입니다).
    · 그 밖에 가격을 못 구한 종목 → 평가액을 계산하지 않고 "가격 확인 중"으로 남깁니다.
      (수집 실패와 상장폐지를 절대 같게 취급하지 않습니다 — 3-2)
    """
    rows = []
    position_value = 0.0
    unpriced = []
    for position in positions or []:
        ticker = str(position.get("ticker") or "")
        quantity = float(position.get("quantity") or 0)
        avg_cost = float(position.get("avg_cost") or 0)
        delisted = position.get("status") == "delisted"
        price = None if delisted else price_lookup(MARKET_KR, ticker)

        if delisted:
            value = 0.0
            note = f'상장폐지 상각({position.get("delisted_date") or "날짜 미상"})'
        elif price is None:
            value = None
            note = '가격 확인 중'
            unpriced.append(ticker)
        else:
            value = quantity * price
            note = ''

        if value is not None:
            position_value += value
        rows.append({
            "ticker": ticker,
            "stock_name": position.get("stock_name") or "",
            "quantity": quantity,
            "avg_cost": avg_cost,
            "price": price,
            "value": value,
            "note": note,
        })
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    return {"rows": rows, "position_value": position_value, "unpriced": unpriced}


def _twr_display(snapshots) -> tuple:
    """누적 TWR → (표시 문자열, 보조 설명). **연환산은 하지 않습니다**(2-6, v1 확정).

    ⚠️ 계산 불가일 때 0% 로 채우지 않습니다 — "아직 계산할 수 없음"과 "0% 수익"은 완전히
       다른 말입니다(§0-1). `compute_twr()` 이 상태값을 돌려주는 이유가 그것입니다.
    """
    try:
        result = duel_rules.compute_twr(snapshots)
    except DuelRuleError as exc:
        return '계산 불가', str(exc)
    if result["status"] == TWR_OK:
        return pct_text(result["twr_pct"]), (
            f'{result["baseline_date"]} ~ {result["end_date"]} · {result["period_count"]}개 구간 누적'
        )
    if result["status"] == TWR_NO_DATA:
        return '아직 계산할 수 없음', '일별 기록이 아직 없습니다(야간 배치가 첫 스냅샷을 만든 뒤부터).'
    if result["status"] == TWR_INSUFFICIENT:
        return '아직 계산할 수 없음', '개설일 하루치 기록뿐이라 구간 수익률이 아직 없습니다(0%가 아닙니다).'
    return '아직 계산할 수 없음', ''


async def _render_accounts(client, user_id: str, accounts, market: dict, on_changed, *,
                           usd_accounts=(), usd_market=None,
                           bundles=None, usd_bundles=None, broad_prices=None) -> None:
    """계좌 비교 영역.

    💵 2026-08-21 — 달러 계좌가 하나라도 있으면 **같은 창유형 카드 안에 위쪽 원화 블록,
       아래쪽 달러 블록**을 나란히 그립니다(§5-11-2 오너 확정, "내 성적표"의
       `_render_currency_block()` 이 통화별로 독립 블록을 그리는 방식과 같은 정신).
       🔴 **두 블록을 합산한 숫자는 만들지 않습니다** — 이 함수 어디에도 원화 값과 달러
       값이 같은 산술식에 들어가는 자리가 없습니다. 환율 시계열이 없는 앱에서 두 통화를
       더하면 그 숫자는 지어낸 값이 되기 때문입니다(§0-1).

    ⚠️ **달러 계좌가 하나도 없으면 예전과 글자 그대로 같은 경로**로 그립니다(아래 첫 분기).
       원화만 쓰는 사용자의 화면을 바꾸지 않기 위한 의도적인 두 경로입니다.
    """
    usd_by_window = {a.get("window_type"): a for a in (usd_accounts or [])}
    if not usd_by_window or usd_market is None:
        # ── 원화 전용 — 2026-08-21 이전과 **완전히 동일한 렌더 경로** ────────────
        ui.markdown('#### 💰 내 가상계좌 3개')
        ui.label(
            '세 계좌는 규칙이 완전히 같습니다 — 차이는 "각 계좌에서 어떤 종목을 골랐는가"뿐입니다.'
        ).classes('vh-muted')
        if market["as_of"]:
            ui.label(
                f'🕒 평가금액은 코스피 종가 스냅샷({esc(str(market["as_of"]))} 기준)으로 계산했습니다 — '
                '실시간 시세가 아닙니다.'
            ).classes('vh-muted')

        # 넓은 화면에서는 3개가 나란히, 좁은 화면(폰)에서는 자동으로 세로로 쌓입니다.
        # `flex: 1 1 320px` — 남는 폭이 320px 미만이면 다음 줄로 내려갑니다. `flex-1`(basis 0)은
        # 절대 줄바꿈되지 않아 폰에서 카드가 짓눌리므로 쓰지 않습니다
        # (`web/pages/scorecard_page.py::_render_currency_block()` 의 #122 계열 교훈과 같은 이유).
        with ui.row().classes('w-full gap-4 items-stretch'):
            # 📊 맨 앞 칸은 **실제 자산**('내 성적표') 요약입니다(2026-08-21 오너 요청 스케치:
            #    성적표 → 1개월 → 3개월 → 6개월 순). 계산 방식이 다르다는 사실은 카드 안의
            #    캡션이 직접 말합니다 — 여기서 두 수익률을 섞어 계산하는 자리는 없습니다.
            await _render_scorecard_summary_card_krw(client, user_id, market,
                                                     broad_prices=broad_prices)
            for account in accounts:
                await _render_account_card(client, user_id, account, market,
                                           bundle=_bundle_for(bundles, account.get("id")))
        return

    # ── 원화 + 달러 병기 (§5-11-2) ────────────────────────────────────────────
    krw_by_window = {a.get("window_type"): a for a in (accounts or [])}
    ui.markdown('#### 💰 내 가상계좌')
    ui.label(
        '창유형(1·3·6개월)마다 원화 계좌와 달러 계좌가 **각각 별도 계좌**로 있습니다. '
        '같은 칸의 위쪽이 원화, 아래쪽이 달러입니다.'
    ).classes('vh-muted')
    ui.label(f'※ {NOTICE_NO_FX_MIX}').classes('vh-muted')
    if market["as_of"]:
        ui.label(
            f'🕒 원화 평가금액은 코스피 종가 스냅샷({esc(str(market["as_of"]))} 기준) 기준입니다 — '
            '실시간 시세가 아닙니다.'
        ).classes('vh-muted')
    if usd_market["as_of"]:
        ui.label(
            f'🕒 달러 평가금액은 미국 종가 스냅샷({esc(str(usd_market["as_of"]))} 기준, 한국시간) '
            '기준입니다 — 실시간 시세가 아닙니다. 두 시장은 마감 시각이 다르므로 기준 시각도 '
            '서로 다릅니다.'
        ).classes('vh-muted')

    # 창유형 순서는 규칙 계층의 `ACCOUNT_WINDOW_TYPES`(M1→M3→M6)를 따릅니다. 혹시 그 목록에
    # 없는 창유형이 내려오면 **조용히 빼지 않고** 뒤에 이어 그립니다(§0-1 — 계좌가 화면에서
    # 소리 없이 사라지는 경로를 만들지 않습니다).
    known = list(ACCOUNT_WINDOW_TYPES)
    extra = [w for w in list(krw_by_window) + list(usd_by_window)
             if w not in known and w is not None]
    ordered = known + sorted(set(extra), key=str)

    with ui.row().classes('w-full gap-4 items-stretch'):
        # 📊 맨 앞 칸 — **실제 자산**('내 성적표'). 창유형 칸들과 같은 구조(위쪽 원화,
        #    아래쪽 달러)로 두어 눈으로 바로 대조되게 합니다(2026-08-21 오너 스케치).
        #    🔴 §5-11-2 — 아래 두 줄은 **서로 완전히 독립된 두 번의 호출**입니다. 통화도
        #       시장 데이터도 각자 인자로 따로 넘기고, 두 호출이 공유하는 변수(누적합 등)가
        #       하나도 없습니다 — 원화 값과 달러 값이 같은 산술식에 들어갈 자리 자체가
        #       없어야 하기 때문입니다(환율 시계열이 없으므로 더하면 지어낸 값이 됩니다).
        with ui.element('div').style(
                'flex: 1 1 320px; min-width: 0; display: grid; gap: 12px; align-content: start;'):
            await _render_scorecard_summary_card_krw(client, user_id, market,
                                                     broad_prices=broad_prices)
            if usd_market is not None:
                await _render_scorecard_summary_card_usd(client, user_id, usd_market,
                                                         broad_prices=broad_prices)

        for window_type in ordered:
            krw_account = krw_by_window.get(window_type)
            usd_account = usd_by_window.get(window_type)
            if krw_account is None and usd_account is None:
                continue
            # 🔴 창유형 한 칸. `display: grid` 로 두는 이유: 안쪽 카드가 이미
            #    `flex: 1 1 320px` 을 달고 있어서, 이 칸을 세로 flex 로 만들면 그 320px 이
            #    **높이 기준값**으로 해석돼 빈 카드가 320px 로 늘어납니다. grid 의 암시적
            #    행은 내용 높이를 그대로 따르므로 그 부작용이 없습니다.
            with ui.element('div').style(
                    'flex: 1 1 320px; min-width: 0; display: grid; gap: 12px; align-content: start;'):
                if krw_account is not None:
                    await _render_account_card(
                        client, user_id, krw_account, market,
                        bundle=_bundle_for(bundles, krw_account.get("id")))
                else:
                    ui.label(
                        f'{WINDOW_TITLES.get(window_type, str(window_type))} — 원화 계좌는 아직 '
                        '없습니다(아래 원화 참여 안내 참고).'
                    ).classes('vh-muted vh-keep-all')
                if usd_account is not None:
                    await _render_account_card_usd(
                        client, user_id, usd_account, usd_market,
                        bundle=_bundle_for(usd_bundles, usd_account.get("id")))
                else:
                    ui.label(
                        f'{WINDOW_TITLES.get(window_type, str(window_type))} — 달러 계좌는 아직 '
                        '없습니다(아래 달러 참여 안내 참고).'
                    ).classes('vh-muted vh-keep-all')


async def _render_account_card(client, user_id: str, account: dict, market: dict,
                               *, bundle=None) -> None:
    """계좌 1개 카드 — 총자산·현금·평가액·누적 TWR·리밸런싱 창 상태·보유종목.

    🔒 그리기 전에 소유자를 한 번 더 확인합니다(§0-3-8 이중 방어).

    🔁 2026-08-21 — `bundle`(4-B 절의 계좌별 포지션·주문 묶음)을 받습니다. 넘어오면 포지션을
       **다시 읽지 않고** 그 값을 쓰고, 주문 목록으로 "이번 리밸런싱 창을 이미 썼는지"까지
       뱃지에 적습니다. 묶음을 넘기지 않는 옛 호출부·테스트 스텁에서는 예전과 **글자 그대로
       같은 경로**로 포지션을 직접 읽고, 창 뱃지만 생략합니다(이 파일이 `market_usd=None`
       에 이미 쓰고 있는 것과 같은 방식 — 새 인자가 옛 화면을 깨뜨리지 않게).

    💰 2026-08-22 — **예수금도 같은 방식**이 됐습니다. `bundle["cash"]` 가 있으면 그 값을
       쓰고 `fetch_my_cash_ledger()` 를 부르지 않습니다(그 조회는 4-B 절 로더로 올라갔고,
       주문 폼이 같은 값을 나눠 씁니다 — 왕복 총수는 그대로입니다). 묶음이 없거나 못 읽은
       옛 경로에서는 지금까지처럼 여기서 직접 읽습니다.
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 계좌라 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    window_type = account.get("window_type")
    title = WINDOW_TITLES.get(window_type, str(window_type))

    with ui.column().classes('vh-card gap-2').style('flex: 1 1 320px; min-width: 0;'):
        ui.markdown(f'##### ⚔️ {esc(title)}').classes('vh-keep-all')
        ui.label(f'개설일 {account.get("anchor_date") or "—"}').classes('vh-muted')

        if bundle is not None and bundle.get("error") is not None:
            # 묶음을 읽다 이 계좌만 실패한 경우 — 예전에 아래 try 가 하던 것과 같은 문구입니다.
            error_banner(f'🚫 {_fail(bundle["error"], "계좌 정보를 불러오지 못했습니다.")}')
            return

        try:
            # 계좌 하나당 왕복 3회(묶음이 있으면 예수금·포지션 2회가 빠져 1회)입니다.
            # 전부 `client` 를 인자로 받는 순수 조회 함수라 스레드로 넘겨도 안전합니다.
            if bundle is not None and bundle.get("cash") is not None:
                cash = bundle["cash"]              # 묶음이 이미 읽어 둔 값 — 다시 읽지 않습니다
            else:
                ledger = await run_blocking(fetch_my_cash_ledger, client, account_id)
                cash = sum_cash_balance(ledger)                 # 순수 계산 — 루프에서 그대로
            if bundle is not None and bundle.get("positions") is not None:
                positions = bundle["positions"]
            else:
                positions = await run_blocking(fetch_my_positions, client, account_id)
            snapshots = await run_blocking(fetch_my_snapshots, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "계좌 정보를 불러오지 못했습니다.")}')
            return

        # 🔁 리밸런싱 창 뱃지 — "몇 번째 창인지 · 며칠 남았는지 · 이번 창을 이미 썼는지".
        #    사용자 요청("리밸런싱 기간 중 1회만 가능하게 카운트를 표시")의 자리입니다.
        #    계산은 통화를 모르는 공유 함수(1-RB 절)가 하고, 여기서는 그리기만 합니다.
        if bundle is not None and bundle.get("orders") is not None:
            state = _rebalance_state(account, bundle["orders"],
                                     datetime.now(KST).date())
            ui.label(_rebalance_badge_text(state)).classes('vh-muted vh-keep-all')

        summary = _position_rows(positions, market["price_lookup"])
        total_value = cash + summary["position_value"]
        twr_text, twr_note = _twr_display(snapshots)

        with ui.row().classes('w-full gap-2 items-stretch'):
            metric_card('총자산', format_amount(total_value, CURRENCY))
            metric_card('예수금(현금)', format_amount(cash, CURRENCY))
            metric_card('주식 평가액', format_amount(summary["position_value"], CURRENCY))
        metric_card('누적 수익률 (TWR)', twr_text, twr_note)

        if summary["unpriced"]:
            # §0-1 — 값을 모르는 종목이 있으면 합계가 "일부만 반영된 값"이라는 사실을 밝힙니다.
            warning_banner(
                f'⚠️ {len(summary["unpriced"])}개 종목의 현재 가격을 확인하지 못해 '
                f'평가액·총자산에서 빠져 있습니다: {", ".join(summary["unpriced"])}. '
                '가격을 지어내지 않습니다 — 상장폐지로 확정된 것과는 다른 상태입니다.'
            )

        if not duel_rules.is_buy_window_open(cash):
            info_banner(
                f'ℹ️ 이 계좌는 예수금이 0원이라 지금은 매수할 수 없습니다. '
                f'다음 {MONTHLY_DEPOSIT_DAY}일 입금 뒤부터 다시 주문할 수 있습니다. '
                '(리밸런싱 매도는 예수금과 상관없이, 보유 종목이 있으면 그대로 할 수 있습니다.)'
            )

        if summary["rows"]:
            _render_positions_table(summary["rows"])
        else:
            ui.label('아직 보유 종목이 없습니다 — 아래 주문 창에서 첫 주문을 넣어 보세요.') \
                .classes('vh-muted')


def _render_positions_table(rows) -> None:
    """보유 종목 표 — '내 성적표'와 **같은 표 껍데기**(`holdings_table_html`)를 씁니다.

    🔐 §0-3-9 — `stock_name` 은 DB 에 저장되는 사용자 소유 컬럼이 아니라 주문 저장 시 우리가
       유니버스에서 넣은 값이지만, 표에 나가는 값은 예외 없이 `esc()` 를 거칩니다.
    """
    headers = ['종목', '수량', '평균매입가', '현재가', '평가금액']
    body_rows = []
    for row in rows:
        name = row["stock_name"] or row["ticker"]
        label = (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
                 f'{esc(str(name))}<br>({esc(str(row["ticker"]))})</div>')
        if row["note"]:
            price_cell = esc(row["note"])
            value_cell = esc('0원' if row["note"].startswith('상장폐지') else '—')
        else:
            price_cell = esc(format_amount(row["price"], CURRENCY))
            value_cell = esc(format_amount(row["value"], CURRENCY))
        body_rows.append([
            label,
            esc(f'{row["quantity"]:,.6g}'),
            esc(format_amount(row["avg_cost"], CURRENCY)),
            price_cell,
            value_cell,
        ])
    ui.html(holdings_table_html(headers, body_rows)).classes('w-full')


# -----------------------------------------------------------------------------
# 6-USD. 💵 달러 계좌 블록 — 위 원화 블록의 미러 (표/통화/시장이 본문에 박혀 갈라짐)
# -----------------------------------------------------------------------------
def _position_rows_usd(positions, price_lookup):
    """보유 포지션(달러) → 화면용 행 + 합계. **가격을 모르면 지어내지 않습니다**(§0-1).

    원화 `_position_rows()` 와 판정 논리는 글자 그대로 같고, **가격 조회 시장이
    `MARKET_US`** 라는 점과 상각 문구가 달러 기준이라는 점만 다릅니다. 시장 인자를 받는
    한 함수로 합치지 않은 이유는 이 트랙의 다른 파일들과 같습니다 — 두 트랙이 실수로
    서로의 목록을 조회할 수 있는 통로 자체를 만들지 않기 위해서입니다.

    · 상장폐지 확정(`status='delisted'`) → 평가액 **$0** 으로 확정(3-1. 확인된 사실입니다).
    · 그 밖에 가격을 못 구한 종목 → 평가액을 계산하지 않고 "가격 확인 중"으로 남깁니다.
    """
    rows = []
    position_value = 0.0
    unpriced = []
    for position in positions or []:
        ticker = str(position.get("ticker") or "")
        quantity = float(position.get("quantity") or 0)
        avg_cost = float(position.get("avg_cost") or 0)
        delisted = position.get("status") == "delisted"
        price = None if delisted else price_lookup(MARKET_US, ticker)

        if delisted:
            value = 0.0
            note = f'상장폐지 상각({position.get("delisted_date") or "날짜 미상"})'
        elif price is None:
            value = None
            note = '가격 확인 중'
            unpriced.append(ticker)
        else:
            value = quantity * price
            note = ''

        if value is not None:
            position_value += value
        rows.append({
            "ticker": ticker,
            "stock_name": position.get("stock_name") or "",
            "quantity": quantity,
            "avg_cost": avg_cost,
            "price": price,
            "value": value,
            "note": note,
        })
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    return {"rows": rows, "position_value": position_value, "unpriced": unpriced}


async def _render_account_card_usd(client, user_id: str, account: dict, market: dict,
                                   *, bundle=None) -> None:
    """달러 계좌 1개 카드 — 총자산·현금·평가액·누적 TWR·리밸런싱 창 상태·보유종목.

    🔒 원화와 **같은 이중 방어** — 그리기 전에 소유자를 한 번 더 확인합니다(§0-3-8).

    🔁 2026-08-21 — `bundle`(4-B 절) 처리도 원화 카드와 같은 모양입니다. 창 길이·창 번호
       계산은 통화를 모르는 공유 함수(1-RB 절)를 그대로 쓰고, 갈라지는 것은 그 값을 **어느
       표에서 읽어 왔는가**뿐입니다(이 함수는 달러 표만 봅니다).

    💰 2026-08-22 — 원화 카드와 같이 `bundle["cash"]` 가 있으면 예수금을 다시 읽지 않습니다
       (그 조회는 `_load_account_data_usd()` 로 올라갔고, 달러 주문 폼이 나눠 씁니다).

    🔴 이 함수 안의 모든 금액은 **달러 하나뿐**입니다. 여기서 계산하는 "총자산"은 이 달러
       계좌 하나의 총자산이고, 원화 계좌의 값과 만나는 자리가 한 곳도 없습니다(§5-11-2).
       위 원화 카드와 같은 이름의 지표를 쓰지만, 두 카드의 숫자를 더하는 코드는 이 파일
       어디에도 없습니다 — 더하는 순간 환율을 지어낸 값이 됩니다.

    ⚠️ DB 조회는 전부 `_usd` 함수입니다(`fetch_my_cash_ledger_usd` 등). 원화 함수를 하나라도
       섞어 부르면 **다른 표**를 읽게 되어 화면에 남의 트랙 숫자가 나옵니다.
       반면 `sum_cash_balance()`·`_twr_display()` 는 통화를 모르는 순수 계산이라 공유합니다.
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 달러 계좌라 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    window_type = account.get("window_type")
    title = WINDOW_TITLES.get(window_type, str(window_type))

    with ui.column().classes('vh-card gap-2').style('flex: 1 1 320px; min-width: 0;'):
        ui.markdown(f'##### 💵 {esc(title)} (달러)').classes('vh-keep-all')
        ui.label(f'개설일 {account.get("anchor_date") or "—"}').classes('vh-muted')

        if bundle is not None and bundle.get("error") is not None:
            error_banner(f'🚫 {_fail(bundle["error"], "달러 계좌 정보를 불러오지 못했습니다.")}')
            return

        try:
            if bundle is not None and bundle.get("cash") is not None:
                cash = bundle["cash"]              # 묶음이 이미 읽어 둔 값 — 다시 읽지 않습니다
            else:
                ledger = await run_blocking(fetch_my_cash_ledger_usd, client, account_id)
                cash = sum_cash_balance(ledger)                 # 순수 계산 — 원화와 공유
            if bundle is not None and bundle.get("positions") is not None:
                positions = bundle["positions"]
            else:
                positions = await run_blocking(fetch_my_positions_usd, client, account_id)
            snapshots = await run_blocking(fetch_my_snapshots_usd, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "달러 계좌 정보를 불러오지 못했습니다.")}')
            return

        # 🔁 리밸런싱 창 뱃지 — 원화 카드와 같은 공유 계산, 달러 계좌의 주문만 봅니다.
        if bundle is not None and bundle.get("orders") is not None:
            state = _rebalance_state(account, bundle["orders"],
                                     datetime.now(KST).date())
            ui.label(_rebalance_badge_text(state)).classes('vh-muted vh-keep-all')

        summary = _position_rows_usd(positions, market["price_lookup"])
        total_value = cash + summary["position_value"]          # 달러 + 달러 (통화 혼합 없음)
        twr_text, twr_note = _twr_display(snapshots)

        with ui.row().classes('w-full gap-2 items-stretch'):
            metric_card('총자산 (달러)', format_amount(total_value, CURRENCY_USD))
            metric_card('예수금(현금)', format_amount(cash, CURRENCY_USD))
            metric_card('주식 평가액', format_amount(summary["position_value"], CURRENCY_USD))
        metric_card('누적 수익률 (TWR)', twr_text, twr_note)

        if summary["unpriced"]:
            warning_banner(
                f'⚠️ {len(summary["unpriced"])}개 종목의 현재 가격을 확인하지 못해 '
                f'평가액·총자산에서 빠져 있습니다: {", ".join(summary["unpriced"])}. '
                '가격을 지어내지 않습니다 — 상장폐지로 확정된 것과는 다른 상태입니다.'
            )

        if not duel_rules.is_buy_window_open(cash):
            info_banner(
                f'ℹ️ 이 달러 계좌는 예수금이 $0이라 지금은 매수할 수 없습니다. '
                f'다음 {MONTHLY_DEPOSIT_DAY}일 입금 뒤부터 다시 주문할 수 있습니다. '
                '(리밸런싱 매도는 예수금과 상관없이, 보유 종목이 있으면 그대로 할 수 있습니다.)'
            )

        if summary["rows"]:
            _render_positions_table_usd(summary["rows"])
        else:
            ui.label('아직 보유 종목이 없습니다 — 아래 달러 주문 창에서 첫 주문을 넣어 보세요.') \
                .classes('vh-muted')


def _render_positions_table_usd(rows) -> None:
    """달러 보유 종목 표 — 원화와 **같은 표 껍데기**(`holdings_table_html`)를 씁니다.

    갈라진 이유는 통화 상수 하나뿐입니다(`CURRENCY` → `CURRENCY_USD`, 상각 표기 '0원' → '$0').
    🔐 §0-3-9 — 표에 나가는 값은 예외 없이 `esc()` 를 거칩니다.
    """
    headers = ['종목', '수량', '평균매입가', '현재가', '평가금액']
    body_rows = []
    for row in rows:
        name = row["stock_name"] or row["ticker"]
        label = (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
                 f'{esc(str(name))}<br>({esc(str(row["ticker"]))})</div>')
        if row["note"]:
            price_cell = esc(row["note"])
            value_cell = esc('$0.00' if row["note"].startswith('상장폐지') else '—')
        else:
            price_cell = esc(format_amount(row["price"], CURRENCY_USD))
            value_cell = esc(format_amount(row["value"], CURRENCY_USD))
        body_rows.append([
            label,
            esc(f'{row["quantity"]:,.6g}'),
            esc(format_amount(row["avg_cost"], CURRENCY_USD)),
            price_cell,
            value_cell,
        ])
    ui.html(holdings_table_html(headers, body_rows)).classes('w-full')


# =============================================================================
# 6-SC. 📊 "내 성적표"(실제 자산) 요약 카드 — 가상계좌 카드들 옆에 나란히
# =============================================================================
# 2026-08-21 오너 요청 — "내 가상계좌" 비교 줄에 **실제 보유 자산**("내 성적표") 카드를
# 하나 더 붙여서 한눈에 같이 보고 싶다는 결정입니다.
#
# 🔴 두 숫자는 **계산 방식이 다릅니다.** 결투 계좌는 매달 자동 입금이 있어서 시간가중
#    수익률(TWR)로 계산하고, "내 성적표"는 예수금 개념이 없는 **매입원가 대비 평가손익률**
#    입니다. 오너 확정(2026-08-21): "예수금이 없는 매입원가 대비 수익률입니다" 라고 카드에
#    **직접 써 두는 조건**으로 나란히 보여줍니다 — 그래서 아래 캡션은 지워도 되는 장식이
#    아니라 이 카드가 존재해도 되는 전제입니다(§0-1 · NOTICE_TWR 과 같은 취지).
#
# 🔴 §0-3-10 — 수익률 계산식을 여기서 다시 만들지 않습니다. 조회는
#    `utils/scorecard_db.py::fetch_holdings()`, 집계는 같은 모듈의 `build_portfolio()`,
#    표시 계산은 `web/pages/scorecard_page.py::_render_currency_block()` 과 **글자 그대로
#    같은 식**(`profit / base * 100`)입니다. 한쪽만 고쳐지는 사고를 막기 위해서입니다.
#
# 🔴 §5-11-2 — 이 함수는 **통화 하나만** 다룹니다(`currency` 인자 하나). 원화 카드와 달러
#    카드는 이 함수를 **두 번 따로** 부른 결과일 뿐이고, 두 호출 사이에 공유되는 변수도,
#    두 통화 값이 만나는 산술식도 이 파일 어디에도 없습니다.
async def _render_scorecard_summary_card(client, user_id: str, currency: str,
                                         price_lookup) -> None:
    """'내 성적표'(실제 증권계좌) 통화 1개짜리 요약 카드.

    🔒 §0-3-8 — `fetch_holdings(client, user_id)` 는 우리가 넘긴 `user_id` 로 서버에서
       필터하는 함수입니다("내 성적표" 화면도 추가 재확인 없이 이 함수만 씁니다). 미리
       받아둔 남의 레코드가 섞여 들어올 수 있는 결투 계좌 카드와 달리 여기엔 "남의 것"
       경로 자체가 없으므로, 성립하지 않는 소유자 재확인을 흉내 내지 않습니다.

    💰 2026-08-22 — 현재가 조회 함수를 **인자로 받습니다**(예전에는 결투 계좌용
       `market["price_lookup"]` 을 그대로 썼습니다). 그 목록은 코스피 상위 200 / 미국 상위
       유니버스로 **일부러 좁혀 둔** 것이라, 무엇이든 담길 수 있는 실제 보유 종목을 거기서만
       찾으면 멀쩡히 상장된 종목이 "가격을 확인하지 못해 제외"로 빠졌습니다(2-B 절 참고).
       어느 목록으로 찾을지는 통화별 창구(바로 아래 두 함수)가 정합니다 — 이 함수는 통화도,
       시장 코드도 모른 채 받은 조회 함수를 그대로 씁니다.
    """
    with ui.column().classes('vh-card gap-2').style('flex: 1 1 320px; min-width: 0;'):
        ui.markdown('##### 📊 내 성적표 (실제 자산)').classes('vh-keep-all')

        try:
            # DB 왕복 — 이 파일의 모든 Supabase 호출과 같이 스레드로 넘깁니다.
            holdings = await run_blocking(fetch_holdings, client, user_id)
        except Exception as exc:                   # noqa: BLE001
            # §0-1 — 조회 실패를 "보유 종목 없음"으로 위장하지 않고 실패했다고 적습니다.
            # 문구는 **이 카드 안**, 숫자가 있었어야 할 자리에 그대로 둡니다. 이 카드는
            # 결투 계좌 카드들 옆에 붙는 보조 카드라, 실패했을 때 붉은 배너를 띄우면
            # "결투 계좌 쪽이 실패했다"로 읽히기 쉽습니다(같은 줄에 나란히 있으므로).
            ui.label(f'🚫 {_fail(exc, "내 성적표 보유 종목을 불러오지 못했습니다.")}') \
                .classes('vh-muted vh-keep-all')
            return

        # 순수 계산(입출력 없음) — `_position_rows()` 처럼 그대로 부릅니다.
        portfolio = build_portfolio(holdings, price_lookup)
        group = portfolio.get(currency)

        if group is None or not group["rows"]:
            # §0-1 — 등록된 종목이 없으면 0원짜리 지표 카드를 만들어 채우지 않습니다.
            ui.label(
                "아직 등록된 보유 종목이 없습니다 — '내 성적표' 화면에서 먼저 종목을 "
                '등록해 보세요.'
            ).classes('vh-muted')
            return

        # ⬇️ `scorecard_page.py::_render_currency_block()` 과 같은 분기·같은 식입니다.
        with ui.row().classes('w-full gap-2 items-stretch'):
            metric_card('매입원가 합계', format_amount(group["total_cost"], currency))
            if group["total_value"] is not None:
                base = group["total_cost_priced"]
                profit = group["total_profit"]
                metric_card('평가금액 합계', format_amount(group["total_value"], currency))
                metric_card('평가손익', format_amount(profit, currency),
                            pct_text(profit / base * 100 if base else None))
            else:
                # 현재가를 아는 종목이 하나도 없는 상태 — 수익률을 지어내지 않습니다(§0-1).
                metric_card('평가금액 합계', '—')
                metric_card('평가손익', '—')

        if group["unpriced_count"]:
            info_banner(
                f'ℹ️ {group["unpriced_count"]}개 종목의 현재 가격을 확인하지 못해 '
                f'내 성적표 평가금액에서 빠져 있습니다: '
                f'{", ".join(group["unpriced_tickers"])}. 가격을 지어내지 않습니다.'
            )

        # 🔴 오너 확정 조건 — 숫자를 보여주는 카드에는 반드시 이 문장이 함께 나갑니다.
        ui.label(
            '⚠️ 이 수익률은 예수금을 제외한, 매입원가 대비 평가손익률입니다 — 결투 계좌의 '
            '시간가중수익률(TWR)과 계산 방식이 다릅니다. 두 수익률을 직접 비교하지 마세요.'
        ).classes('vh-muted vh-keep-all')


# 🔴 §5-11-2 를 코드로 강제하기 위한 통화별 얇은 창구 두 개입니다.
#    이 파일에는 "한 함수 안에서 `CURRENCY` 와 `CURRENCY_USD` 가 함께 쓰이지 않는다"는
#    규칙이 있고(`tests/test_duel_page_usd.py::test_no_function_mixes_the_two_currency_constants`),
#    그 규칙이 곧 "두 통화를 더한 숫자를 만들 자리 자체가 없다"는 보증입니다. 계좌 카드가
#    `_render_account_card` / `_render_account_card_usd` 로 갈라져 있는 것과 같은 이유이며,
#    다만 성적표 카드는 통화 상수 하나만 다르므로 **본문은 위 한 함수를 공유**합니다
#    (§0-3-10 — 같은 계산을 두 벌 만들지 않습니다).
async def _render_scorecard_summary_card_krw(client, user_id: str, market: dict,
                                             *, broad_prices=None) -> None:
    """원화(내 성적표) 요약 카드 — 원화 값만 다룹니다.

    💰 조회 목록은 **여기서** 만듭니다(2-B 절): 1차는 결투 계좌와 같은 코스피 상위 200
       스냅샷, 없으면 2차로 코스피+코스닥 전 종목 종가 목록입니다. '내 성적표' 화면
       (`scorecard_page.py::_render_portfolio()`)이 쓰는 것과 **같은 폴백 순서**라 같은
       종목이 두 화면에서 다른 값으로 보이지 않습니다(§0-3-10).
       🔴 `{MARKET_KR: ...}` 하나만 넘깁니다 — 미국 목록을 함께 넘기면 원화 티커 조회가
          미국 목록을 스칠 수 있는 통로가 생깁니다(§5-11-2).
    """
    price_lookup = make_price_lookup(
        {MARKET_KR: market["index"]},
        broad_kr_prices=(broad_prices or {}).get("broad_kr_prices"),
    )
    await _render_scorecard_summary_card(client, user_id, CURRENCY, price_lookup)


async def _render_scorecard_summary_card_usd(client, user_id: str, market: dict,
                                             *, broad_prices=None) -> None:
    """달러(내 성적표) 요약 카드 — 달러 값만 다룹니다. 위 원화 카드와 공유하는 변수는 없습니다.

    💰 원화 창구와 **같은 모양**이고, 보는 목록만 미국 것입니다: 1차는 미국 상위 유니버스
       스냅샷, 없으면 2차로 미국 전 종목 + ETF 종가 목록(2-B 절에서 합쳐 둔 것).
    """
    price_lookup = make_price_lookup(
        {MARKET_US: market["index"]},
        broad_us_prices=(broad_prices or {}).get("broad_us_prices"),
    )
    await _render_scorecard_summary_card(client, user_id, CURRENCY_USD, price_lookup)


# =============================================================================
# 7. 주문 창 (2-4 — 매수 + 창당 1회 리밸런싱 매도, 수량 기준, 코스피 상위 200 안에서만)
# =============================================================================
def _render_order_form(client, user_id: str, accounts, market: dict, window: dict,
                       on_changed, *, bundles=None) -> None:
    """주문 저장 폼 — 위쪽이 **매수**, 아래쪽이 **창당 1회 리밸런싱 매도**입니다.

    ⚠️ 유니버스 검사·시간대 검사·거래일 확정은 전부 `utils/duel_db.py::save_order()` 와
       `utils/duel_rules.py` 가 합니다. 이 함수가 하는 일은 **입력 도우미(검색·수량 입력·
       사전 고지)** 와 실패 문구 표시뿐입니다(§0-3-10 — 판정 로직을 두 번 만들지 않습니다).

    🔁 2026-08-21 — 매도 칸이 생기면서 두 가지가 달라졌습니다.
       ① 제목·버튼에서 "(매수 전용)"·"(매수)" 표기를 뺐습니다 — 이제 사실이 아닙니다.
       ② 매도 칸은 **유니버스 목록이 없어도 그립니다.** 매수는 코스피 상위 목록 안에서만
          가능하지만, 매도에는 유니버스 검사가 아예 없습니다(`save_sell_order()` 독스트링:
          이미 보유한 종목이 목록에서 빠졌다고 "팔 수도 없는" 상태가 되면 그게 더 나쁩니다).
          그래서 목록을 못 읽어 매수 칸을 못 여는 날에도 매도 칸은 그대로 열립니다 —
          아래 이른 반환 자리에서 매도 칸을 한 번 더 부르는 이유입니다.
    """
    index = market["index"]
    ui.markdown('#### 🛒 주문하기')
    ui.label(
        f'코스피 상위 종목만, 원화로만, 주식 수 단위로 주문합니다. '
        f'현재 주문 가능 목록에는 {len(index)}종목이 있습니다.'
    ).classes('vh-muted')
    ui.label(f'⏱️ {NOTICE_FILL_TIMING}').classes('vh-muted')

    if not index:
        error_banner(
            '🚫 주문 가능 종목 목록을 읽지 못해 **매수** 창을 열 수 없습니다. '
            '(보유 종목을 파는 리밸런싱 매도는 유니버스 목록과 무관하므로 아래에 그대로 '
            '열려 있습니다.)'
        )
        _render_sell_form(client, user_id, accounts, window, on_changed, bundles=bundles)
        return

    ui.markdown('##### 🛒 매수')

    # ⚠️ 이 dict 들은 **페이지 함수 호출마다 새로 만들어지는 지역 상태**입니다(접속마다 별개).
    #    모듈 전역에 두면 접속자끼리 입력값이 섞입니다(§0-3-8).
    account_options = {
        str(account.get("id")): f'{WINDOW_TITLES.get(account.get("window_type"), "")} '
                                f'({account.get("window_type")})'
        for account in accounts
        if account.get("user_id") == user_id       # 🔒 남의 계좌를 고를 수 있는 경로 자체를 없앰
    }

    # 💰 계좌별 예수금 — 4-B 절 묶음이 이미 읽어 둔 값입니다(여기서 다시 읽지 않습니다).
    #    키는 `account_options` 와 같은 `str(id)` 로 맞춥니다 — 드롭다운이 돌려주는 값이
    #    그 문자열이기 때문입니다.
    cash_by_account = {
        str(account.get("id")): _bundle_for(bundles, account.get("id")).get("cash")
        for account in accounts
        if account.get("user_id") == user_id       # 🔒 위 목록과 **같은** 소유자 조건
    }

    # 📉 오너 요청(2026-08-23) — "남은 예수금 = 예수금 - 지금 주문넣은 예상 가격"까지 보여
    #    달라는 요청입니다. 주문 목록도 4-B 절 묶음이 이미 읽어 둔 값이라 여기서 새로
    #    읽지 않습니다(§0-3-2).
    orders_by_account = {
        str(account.get("id")): _bundle_for(bundles, account.get("id")).get("orders")
        for account in accounts
        if account.get("user_id") == user_id
    }

    account_select = ui.select(
        account_options, value=next(iter(account_options), None), label='주문할 계좌',
        on_change=lambda _e: _update_cash_label(),
    ).classes('w-full')

    # 🔴 오너 피드백(2026-08-22) — "여기만 봐서는 내가 얼마나 주문을 더 할 수 있을 지 알 수가
    #    없어". 예수금은 화면 위쪽 계좌 카드에 이미 있지만 모바일에서 여기까지 내려오면 화면
    #    밖입니다. 그래서 **계좌를 고른 자리 바로 아래**에, 종목·수량을 정하기 **전에**
    #    보이게 둡니다(가격 보이고 → 수량 조절).
    cash_label = ui.label('').classes('text-base font-bold vh-keep-all')
    # 📉 오너 요청(2026-08-23) — 위 줄이 보여주는 것은 **지금 정산된** 예수금이라, 이미
    #    넣어 둔 대기 주문이 체결되면 얼마가 남는지는 알 수 없었습니다. 그 추정치를 한 줄
    #    더 붙입니다(작은 글씨 — 확정 숫자가 아니라 추정이기 때문입니다).
    remaining_cash_label = ui.label('').classes('vh-muted vh-keep-all')

    def _update_cash_label() -> None:
        """고른 계좌의 예수금 표시. 계좌를 바꾸면 이 함수가 다시 불립니다."""
        cash = cash_by_account.get(account_select.value)
        if cash is None:
            # §0-1 — 못 읽은 것을 0원으로 위장하지 않습니다(0원이면 아래 줄로 갑니다).
            cash_label.text = '💰 이 계좌의 예수금을 읽지 못했습니다 — 위 계좌 카드를 확인해 주세요.'
            remaining_cash_label.text = ''
            return
        cash_label.text = f'💰 이 계좌 주문 가능 예수금: {format_amount(cash, CURRENCY)}'

        orders = orders_by_account.get(account_select.value) or []
        impact = _pending_orders_cash_impact(orders, market["price_lookup"], MARKET_KR)
        if impact["pending_count"] == 0:
            remaining_cash_label.text = ''
        elif impact["unknown_count"] == impact["pending_count"]:
            # §0-1 — 전부 못 구했으면 숫자를 지어내지 않고 그 사실만 말합니다.
            remaining_cash_label.text = (
                f'📉 대기 중인 주문 {impact["pending_count"]}건이 있지만 최근 가격을 확인하지 '
                '못해 예상 남은 예수금을 계산할 수 없습니다.'
            )
        else:
            remaining = cash + impact["delta"]
            remaining_cash_label.text = (
                f'📉 대기 중인 주문(매수 {impact["buy_count"]}건 · 매도 {impact["sell_count"]}건) '
                f'반영 시 예상 남은 예수금: {format_amount(remaining, CURRENCY)} '
                '(최근 종가 기준 추정 — 실제 체결가로 달라질 수 있습니다)'
            )
            if impact["unknown_count"] > 0:
                remaining_cash_label.text += (
                    f' · 가격을 확인하지 못한 주문 {impact["unknown_count"]}건은 이 계산에서 '
                    '제외했습니다.'
                )

    _update_cash_label()

    def _picked(event) -> None:
        if event.value:
            query_input.value = event.value
        _update_estimate()

    ui.select(
        _universe_options(index), with_input=True, clearable=True, on_change=_picked,
        label='🔍 종목 빠른 검색 (코스피 상위 200 — 코드·이름 아무거나 입력)',
    ).classes('w-full')

    query_input = ui.input(
        '종목 (종목코드 또는 종목명)',
        placeholder='예: 005930 / 삼성전자',
        on_change=lambda _e: _update_estimate(),
    ).classes('w-full')

    quantity_input = ui.input(
        '수량 (몇 주)', placeholder='예: 10',
        on_change=lambda _e: _update_estimate(),
    ).style('flex: 1 1 160px;')

    estimate_label = ui.label('').classes('text-lg font-bold whitespace-pre-line')
    estimate_caveat_label = ui.label('').classes('vh-muted')

    def _resolve_ticker():
        """입력창 텍스트 → (티커, 종목명, 실패사유). 코스피 상위 200 **안에서만** 찾습니다.

        `resolve_stock_query()` 는 '내 성적표'가 쓰는 그 함수 그대로이고, `broad_index` 를
        넘기지 않으므로 상위 200 밖 종목은 이름으로 잡히지 않습니다. 다만 "코드처럼 생긴"
        입력은 그 함수가 코드 자체를 그대로 돌려주므로(유니버스 밖 종목을 정직하게
        표시하려는 원래 용도), 여기서 유니버스 포함 여부를 한 번 더 확인합니다.
        """
        ticker, name, error = resolve_stock_query(MARKET_KR, query_input.value or '',
                                                  {MARKET_KR: index})
        if not ticker:
            return None, None, error
        stock = index.get(ticker)
        if not stock:
            return None, None, (
                f'{ticker}은(는) 코스피 상위 종목 목록에 없습니다 — 이 모듈은 상위 종목만 '
                '주문할 수 있습니다.'
            )
        resolved_name = stock.get("name") or name
        if not resolved_name:
            # 이름을 모르면 저장하지 않습니다(§0-1 — 종목명을 지어내지 않습니다).
            return None, None, f'{ticker}의 종목명을 확인하지 못해 주문할 수 없습니다.'
        return ticker, resolved_name, None

    def _update_estimate() -> None:
        """참고용 예상 금액. **차단 조건이 아닙니다**(2-4-3).

        실제 체결가는 다음 거래일 종가라 지금은 알 수 없습니다. 여기 숫자는 "대략 이 정도가
        필요하겠다"는 감을 주기 위한 최근 종가 기준 계산이고, 그렇게 표시합니다.
        """
        ticker, _name, error = _resolve_ticker()
        if not ticker or error:
            estimate_label.text = ''
            estimate_caveat_label.text = ''
            return
        price = market["price_lookup"](MARKET_KR, ticker)
        if price is None:
            estimate_label.text = f'{ticker} — 최근 종가를 확인하지 못해 예상 금액을 계산할 수 없습니다.'
            estimate_caveat_label.text = ''
            return
        try:
            quantity = _parse_positive_int(quantity_input.value, '수량')
        except ValueError:
            estimate_label.text = f'{ticker} 최근 확정 종가 {format_amount(price, CURRENCY)}'
            estimate_caveat_label.text = ''
            return
        # 🔴 오너 피드백(2026-08-22) — 수량·예상 금액이 한눈에 크게 보이는 게 중요한
        # 포인트라, 굵고 큰 글씨로 줄바꿈해 두 줄로 보여주고, 안내 문장은 짧게 줄여
        # 아래 작은 글씨로 뺍니다(§ "수량하고 금액을 잘 보는게 중요한 포인트").
        estimate_label.text = (
            f'{quantity:,}주 × {format_amount(price, CURRENCY)}\n'
            f'≈ {format_amount(price * quantity, CURRENCY)}'
        )
        estimate_caveat_label.text = (
            '예상 금액일 뿐 — 실제 체결가는 다음 거래일 종가로 정해집니다.'
        )

    # 🔴 2-4-5 — "크롤링이 실패하면 이 주문은 체결되지 않고 취소됩니다"를 **주문 전에**
    #    크고 명확하게, 체크 확인 영역에 포함해서 고지합니다(사후 통보로 끝내지 않기).
    warning_banner(NOTICE_CRAWL_FAILURE)
    confirm_box = ui.checkbox('위 안내(수집 실패·휴장일이면 주문이 취소됨)를 확인했습니다.')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    async def _submit() -> None:
        message.text = ''
        if not window["is_open"]:
            # 서버(`save_order`)도 같은 규칙으로 거절하지만, 눌러보기 전에 알려 줍니다.
            message.text = f'🚫 {_window_message(window)}'
            return
        if not confirm_box.value:
            message.text = '🚫 위 안내 확인란을 체크해 주세요 — 체결이 취소될 수 있는 경우를 먼저 알려드리는 절차입니다.'
            return
        account_id = account_select.value
        if not account_id:
            message.text = '🚫 주문할 계좌를 골라 주세요.'
            return
        ticker, stock_name, resolve_error = _resolve_ticker()
        if not ticker:
            message.text = f'🚫 {resolve_error}'
            ui.notify('🚫 종목을 찾지 못했습니다 — 아래 문구에서 이유를 확인해 주세요.',
                      type='negative', multi_line=True, close_button='닫기')
            return
        try:
            quantity = _parse_positive_int(quantity_input.value, '수량')
        except ValueError as exc:
            message.text = f'🚫 {exc}'
            return

        try:
            order = await run_blocking(
                save_order,
                client, account_id, ticker, stock_name, quantity,
                # 거래일 목록은 **호출부가 확정해서 넘깁니다**(규칙 계층이 캘린더를 갖지
                # 않는 이유는 `resolve_fill_trading_day()` 독스트링 참고). 화면이 넘기는 값이
                # 주말을 제외한 평일 근사치라는 사실은 `_upcoming_trading_days()` 에 적어
                # 뒀습니다 — 공휴일 판정의 최종 권한은 야간 배치에 있습니다.
                trading_days=_upcoming_trading_days(window["now_kst"].date()),
                # 이중 방어: 서버가 유니버스를 다시 확인하게 목록을 함께 넘깁니다.
                universe_tickers=set(index),
            )
        except (DuelDbError, DuelRuleError) as exc:
            # 두 예외 모두 이미 "사람이 읽을 한국어 한 문장"입니다(§0-1).
            message.text = f'🚫 {exc}'
            ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                      classes='whitespace-pre-line')
            return
        except Exception as exc:                   # noqa: BLE001
            text = _fail(exc, '주문을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
            message.text = f'🚫 {text}'
            ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
            return

        query_input.value = ''
        quantity_input.value = ''
        estimate_label.text = ''
        estimate_caveat_label.text = ''
        ui.notify(
            f'✅ 주문을 저장했습니다 — {stock_name} ({ticker}) {quantity:,}주\n'
            f'체결 예정일: {order.get("target_date")} 종가 (지금 체결된 것이 아닙니다)\n'
            f'{ORDER_WINDOW_TEXT} 안에서는 수량 수정·취소가 가능합니다.',
            type='positive', multi_line=True, close_button='닫기',
            classes='text-lg whitespace-pre-line',
        )
        on_changed()

    ui.button('🛒 매수 주문 저장', on_click=_submit).props('no-caps color=primary')
    ui.label(
        '※ 저장 시점에는 예수금이 충분한지 확정할 수 없습니다 — 체결가(다음 거래일 종가)를 '
        '아직 모르기 때문입니다. 체결 시점에 모자라면 살 수 있는 만큼만 체결되고 사유가 남습니다.'
    ).classes('vh-muted')

    ui.separator()
    _render_sell_form(client, user_id, accounts, window, on_changed, bundles=bundles)


# -----------------------------------------------------------------------------
# 7-SELL. 🔁 리밸런싱 매도 칸 (원화) — 계좌마다 창당 1회, 종목 1개, 1주~전량
# -----------------------------------------------------------------------------
#  🔴 왜 계좌마다 **별도의 칸**인가: 매도의 제약(보유 종목 목록 · 창 번호 · 이번 창 사용
#     여부)이 전부 **계좌마다 다릅니다.** 매수처럼 계좌 선택 드롭다운 하나로 묶으면 계좌를
#     바꿀 때마다 종목 목록·버튼 활성 여부·안내 문구를 전부 갈아끼워야 하고, 그 갈아끼우기가
#     한 군데라도 빠지면 화면이 **다른 계좌의 조건으로 매도를 받는** 상태가 됩니다. 계좌별로
#     칸을 나누면 그 상태 자체가 생길 수 없습니다(§0-3-9 의 "사고가 날 자리를 없애기").
#  🔴 최종 권한은 서버입니다 — 화면이 버튼을 감추는 것과 별개로, `save_sell_order()` 가
#     접수 시간대·보유 수량을 다시 보고, DB 부분 유니크 인덱스가 "창당 1회"를 강제합니다.
# -----------------------------------------------------------------------------
def _render_sell_form(client, user_id: str, accounts, window: dict, on_changed,
                      *, bundles=None) -> None:
    """원화 계좌들의 리밸런싱 매도 칸 묶음."""
    ui.markdown('##### 🔁 리밸런싱 매도 (매도 기회는 계좌마다 주기당 1회)')
    ui.label(
        '한 번의 매도 기회로 종목 하나를 1주부터 보유 전량까지 팔 수 있습니다. '
        f'접수 시간대는 매수와 같고({ORDER_WINDOW_TEXT}), 체결도 매수와 같이 '
        '다음 거래일 종가로 이루어집니다.'
    ).classes('vh-muted')
    # 2-4-5 — 체결이 취소될 수 있는 경우를 **주문 전에** 알려 둡니다(사후 통보로 끝내지 않기).
    ui.label(
        '⚠️ 그날 종가 수집이 실패하거나 휴장일이면 이 매도 주문도 체결되지 않고 사유와 함께 '
        '취소됩니다. 그 경우 이번 매도 기회는 **다시 열립니다** — 취소된 매도는 그 기회를 '
        '소진하지 않습니다(데이터 문제로 사용자의 기회를 빼앗지 않기 위한 규칙입니다).'
    ).classes('vh-muted vh-keep-all')

    for account in accounts or []:
        _render_sell_panel(client, user_id, account, window, on_changed,
                           bundle=_bundle_for(bundles, account.get("id")))


def _render_sell_panel(client, user_id: str, account: dict, window: dict, on_changed,
                       *, bundle) -> None:
    """계좌 1개의 매도 칸.

    🔒 원화 카드·주문 목록과 같은 이유로 소유자를 여기서도 한 번 더 확인합니다(§0-3-8).
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 계좌라 매도 창을 그리지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))

    # 🔴 2026-08-22 — 오너 요청("굳이 상시 공개로 할 필요는 없을 것 같아"): 창당 1회뿐인
    #    매도 안내문이 계좌 3개마다 항상 펼쳐진 채로 화면을 길게 잡아먹었습니다. `ui.card()`
    #    → `ui.expansion()`으로만 바꿨습니다(이 파일·이 저장소에 이미 있는 접이식 패턴을
    #    그대로 재사용 — §0-3-10, 예: 940번째 줄 "이 대결은 어떻게 굴러가나요?"). 기본값은
    #    닫힘(`value=False`)이고, 안쪽 로직·문구는 한 글자도 바꾸지 않았습니다.
    with ui.expansion(esc(title), icon='🔁', value=False).classes('vh-card w-full'):
        if bundle.get("error") is not None:
            error_banner(
                f'🚫 {_fail(bundle["error"], "보유 종목·주문 내역을 불러오지 못해 매도 창을 열 수 없습니다.")}'
            )
            return
        if bundle.get("positions") is None or bundle.get("orders") is None:
            # §0-1 — 못 읽은 것을 "보유 없음"으로 위장하지 않습니다.
            ui.label('보유 종목·주문 내역을 아직 읽지 못해 매도 창을 열 수 없습니다.') \
                .classes('vh-muted')
            return

        state = _rebalance_state(account, bundle["orders"], datetime.now(KST).date())
        ui.label(_rebalance_badge_text(state)).classes('vh-muted vh-keep-all')

        if state["window"] is None:
            # 첫 매수 전 — 예외가 아니라 **정상 상태**입니다. 안내만 하고 조용히 끝냅니다.
            info_banner(
                'ℹ️ 아직 매수한 종목이 없어 리밸런싱 매도를 계산할 수 없습니다. '
                '첫 매수가 체결되면 그날부터 이 계좌의 주기가 시작되고 첫 매도 기회가 '
                '열립니다.\n\n'
                f'{state["unavailable_reason"]}'
            )
            return

        if state["used_order"] is not None:
            used = state["used_order"]
            info_banner(
                'ℹ️ 이번 매도 기회는 이미 사용했습니다 — 다음 매도 기회: '
                f'{state["window"]["next_window_starts_on"]}부터\n\n'
                f'이번 기회에 쓴 주문: {used.get("stock_name") or ""} ({used.get("ticker")}) '
                f'{used.get("requested_quantity")}주 · {_order_status_text(used)}\n\n'
                '아직 체결 전(대기)이고 접수 시간대 안이라면, 아래 "내 주문"에서 그 매도 '
                '주문을 취소해 이번 매도 기회를 되살릴 수 있습니다.'
            )
            return

        sellable = _sellable_positions(bundle["positions"])
        if not sellable:
            ui.label('이 계좌에는 팔 수 있는 보유 종목이 없습니다.').classes('vh-muted')
            return

        held_by_ticker = {row["ticker"]: row["quantity"] for row in sellable}
        name_by_ticker = {row["ticker"]: (row["stock_name"] or row["ticker"])
                          for row in sellable}
        options = {
            row["ticker"]: f'{row["ticker"]} · {row["stock_name"] or row["ticker"]} '
                           f'(보유 {row["quantity"]:,}주)'
            for row in sellable
        }

        ticker_select = ui.select(
            options, value=next(iter(options)), label='팔 종목 (보유 종목 중에서)',
        ).classes('w-full')
        quantity_input = ui.input(
            '매도 수량 (몇 주)', placeholder='예: 3',
        ).style('flex: 1 1 160px;')
        ui.label(
            '※ 1주부터 보유 전량까지 가능합니다. 이 계좌에서는 이번 매도 기회에 **딱 한 '
            '번**만 저장할 수 있고, 접수 시간대 안에서는 수량 수정·취소가 됩니다.'
        ).classes('vh-muted vh-keep-all')

        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _submit_sell(_=None) -> None:
            message.text = ''
            if not window["is_open"]:
                # 서버(`save_sell_order`)도 같은 규칙으로 거절하지만, 눌러보기 전에 알려 줍니다.
                message.text = f'🚫 {_window_message(window)}'
                return
            ticker = ticker_select.value
            if not ticker:
                message.text = '🚫 팔 종목을 골라 주세요.'
                return
            held = held_by_ticker.get(ticker)
            if not held:
                message.text = ('🚫 보유 수량을 확인하지 못했습니다 — 화면을 새로고침한 뒤 '
                                '다시 시도해 주세요.')
                return
            try:
                quantity = _parse_positive_int(quantity_input.value, '매도 수량')
            except ValueError as exc:
                message.text = f'🚫 {exc}'
                return
            if quantity > held:
                message.text = (f'🚫 보유 수량({held:,}주)보다 많은 {quantity:,}주는 매도할 수 '
                                '없습니다. 보유한 수량 이하로 다시 입력해 주세요.')
                return

            # 🔴 창 번호는 **누를 때 다시 계산합니다.** 화면을 열어둔 채 자정을 넘겨 창이
            #    바뀌었는데 그릴 때 잡아둔 번호로 저장하면, 지난 창의 자리에 주문이 들어갑니다.
            try:
                current = duel_rules.resolve_rebalance_window(
                    account.get("window_type"), account.get("first_holding_date"),
                    datetime.now(KST).date())
            except DuelRuleError as exc:
                message.text = f'🚫 {exc}'
                return

            try:
                order = await run_blocking(
                    save_sell_order,
                    client, account_id, ticker, name_by_ticker.get(ticker) or ticker,
                    quantity, held, current["window_index"],
                    # 매수와 **같은 후보 목록**입니다 — 매도도 D+1 종가로 체결되므로
                    # 저장일 자신을 빼는 원화 규칙이 그대로 적용됩니다.
                    trading_days=_upcoming_trading_days(window["now_kst"].date()),
                )
            except (DuelDbError, DuelRuleError) as exc:
                # 보유 초과·창 소진(부분 유니크 인덱스)·접수 시간대 밖 — 전부 DB 계층이 이미
                # "사람이 읽을 한국어 한 문장"으로 번역해 둔 예외입니다. 다시 포장하면 원인이
                # 흐려지므로 그대로 보여줍니다(§0-1, 매수 폼과 같은 규율).
                message.text = f'🚫 {exc}'
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                text = _fail(exc, '매도 주문을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
                message.text = f'🚫 {text}'
                ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
                return

            quantity_input.value = ''
            ui.notify(
                f'✅ 리밸런싱 매도 주문을 저장했습니다 — {name_by_ticker.get(ticker)} '
                f'({ticker}) {quantity:,}주\n'
                f'체결 예정일: {order.get("target_date")} 종가 (지금 체결된 것이 아닙니다)\n'
                f'{ORDER_WINDOW_TEXT} 안에서는 수량 수정·취소가 가능하고, 취소하면 이번 '
                '매도 기회가 다시 열립니다.',
                type='positive', multi_line=True, close_button='닫기',
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        ui.button('🔁 리밸런싱 매도 주문 저장', on_click=_submit_sell) \
            .props('no-caps color=negative')


# -----------------------------------------------------------------------------
# 7-USD. 💵 달러 주문 창 — 미국 유니버스 · USD 접수 시간대 · **당일 마감가** 체결
# -----------------------------------------------------------------------------
def _render_order_form_usd(client, user_id: str, accounts, market: dict, window: dict,
                           on_changed, *, bundles=None) -> None:
    """달러 주문 저장 폼. 원화 `_render_order_form()` 의 미러이고, 다른 곳은 네 군데입니다.

      ① 종목 검색·유니버스 검사가 **`MARKET_US`** 기준입니다. 종목 조회 자체는 '내 성적표'·
         '미국주식' 화면이 이미 쓰는 통화 무관 함수 `resolve_stock_query(market, …)` 를
         **그대로 재사용**합니다(§0-3-10 — 미국 종목을 찾는 두 번째 경로를 만들지 않습니다).
      ② 접수 시간대·거절 문구가 `resolve_order_window_usd()`(16:00:01~21:00:00) 기준입니다.
      ③ **거래일 후보를 `_upcoming_trading_days_usd()` 로 만듭니다** — 저장일 자신을 포함하는
         목록이라야 `save_order_usd()` → `resolve_fill_trading_day_usd()` 가 §5-16 확정대로
         "그날 마감가"로 체결일을 잡습니다. 원화용 `_upcoming_trading_days()`(다음 날부터)를
         넘기면 체결이 조용히 하루 밀립니다.
      ④ 저장을 `save_order_usd()` 가 합니다(다른 표 `duel_orders_usd`).

    나머지(유니버스·시간대 최종 판정은 서버가, 화면은 입력 도우미와 실패 문구만)는 원화와
    같은 근거이므로 반복하지 않습니다.
    """
    index = market["index"]
    ui.markdown('#### 💵 달러 주문하기')
    ui.label(
        f'미국 상위 유니버스 종목만, 달러로만, 주식 수 단위로 주문합니다. '
        f'현재 주문 가능 목록에는 {len(index)}종목이 있습니다.'
    ).classes('vh-muted')
    ui.label(f'⏱️ {NOTICE_FILL_TIMING_USD}').classes('vh-muted')

    if not index:
        error_banner(
            '🚫 미국 주문 가능 종목 목록을 읽지 못해 달러 **매수** 창을 열 수 없습니다. '
            '(보유 종목을 파는 리밸런싱 매도는 유니버스 목록과 무관하므로 아래에 그대로 '
            '열려 있습니다.)'
        )
        _render_sell_form_usd(client, user_id, accounts, window, on_changed, bundles=bundles)
        return

    ui.markdown('##### 💵 매수')

    # ⚠️ 원화와 같은 이유로 **페이지 함수 호출마다 새로 만들어지는 지역 상태**입니다(§0-3-8).
    account_options = {
        str(account.get("id")): f'{WINDOW_TITLES.get(account.get("window_type"), "")} '
                                f'({account.get("window_type")} · 달러)'
        for account in accounts
        if account.get("user_id") == user_id       # 🔒 남의 계좌를 고를 수 있는 경로 자체를 없앰
    }

    # 💰 계좌별 예수금 — `_load_account_data_usd()` 묶음이 이미 읽어 둔 **달러** 값입니다.
    cash_by_account = {
        str(account.get("id")): _bundle_for(bundles, account.get("id")).get("cash")
        for account in accounts
        if account.get("user_id") == user_id       # 🔒 위 목록과 **같은** 소유자 조건
    }

    # 📉 오너 요청(2026-08-23) — 원화 폼과 같은 이유·같은 자리입니다. 주문 목록도 묶음이
    #    이미 읽어 둔 값이라 여기서 새로 읽지 않습니다(§0-3-2).
    orders_by_account = {
        str(account.get("id")): _bundle_for(bundles, account.get("id")).get("orders")
        for account in accounts
        if account.get("user_id") == user_id
    }

    account_select = ui.select(
        account_options, value=next(iter(account_options), None), label='주문할 달러 계좌',
        on_change=lambda _e: _update_cash_label(),
    ).classes('w-full')

    # 🔴 오너 피드백(2026-08-22) — 원화 폼과 같은 이유·같은 자리입니다(계좌 바로 아래,
    #    종목·수량 입력보다 위).
    cash_label = ui.label('').classes('text-base font-bold vh-keep-all')
    # 📉 오너 요청(2026-08-23) — 원화 폼과 같은 이유·같은 자리·같은 문구입니다(통화 서식만
    #    달러). 이 앱에는 영어 화면이 따로 없으므로 문장 자체는 한 벌입니다.
    remaining_cash_label = ui.label('').classes('vh-muted vh-keep-all')

    def _update_cash_label() -> None:
        """고른 달러 계좌의 예수금 표시. 계좌를 바꾸면 이 함수가 다시 불립니다."""
        cash = cash_by_account.get(account_select.value)
        if cash is None:
            # §0-1 — 못 읽은 것을 $0 으로 위장하지 않습니다($0 이면 아래 줄로 갑니다).
            cash_label.text = '💰 이 달러 계좌의 예수금을 읽지 못했습니다 — 위 계좌 카드를 확인해 주세요.'
            remaining_cash_label.text = ''
            return
        cash_label.text = f'💰 이 달러 계좌 주문 가능 예수금: {format_amount(cash, CURRENCY_USD)}'

        orders = orders_by_account.get(account_select.value) or []
        impact = _pending_orders_cash_impact(orders, market["price_lookup"], MARKET_US)
        if impact["pending_count"] == 0:
            remaining_cash_label.text = ''
        elif impact["unknown_count"] == impact["pending_count"]:
            # §0-1 — 전부 못 구했으면 숫자를 지어내지 않고 그 사실만 말합니다.
            remaining_cash_label.text = (
                f'📉 대기 중인 주문 {impact["pending_count"]}건이 있지만 최근 가격을 확인하지 '
                '못해 예상 남은 예수금을 계산할 수 없습니다.'
            )
        else:
            remaining = cash + impact["delta"]
            remaining_cash_label.text = (
                f'📉 대기 중인 주문(매수 {impact["buy_count"]}건 · 매도 {impact["sell_count"]}건) '
                f'반영 시 예상 남은 예수금: {format_amount(remaining, CURRENCY_USD)} '
                '(최근 종가 기준 추정 — 실제 체결가로 달라질 수 있습니다)'
            )
            if impact["unknown_count"] > 0:
                remaining_cash_label.text += (
                    f' · 가격을 확인하지 못한 주문 {impact["unknown_count"]}건은 이 계산에서 '
                    '제외했습니다.'
                )

    _update_cash_label()

    def _picked(event) -> None:
        if event.value:
            query_input.value = event.value
        _update_estimate()

    # `_universe_options()` 는 {티커: "티커 · 이름"} 를 만드는 통화 무관 순수 함수라 재사용합니다.
    ui.select(
        _universe_options(index), with_input=True, clearable=True, on_change=_picked,
        label='🔍 종목 빠른 검색 (미국 상위 유니버스 — 티커·이름 아무거나 입력)',
    ).classes('w-full')

    query_input = ui.input(
        '종목 (티커 또는 종목명)',
        placeholder='예: AAPL / Apple',
        on_change=lambda _e: _update_estimate(),
    ).classes('w-full')

    quantity_input = ui.input(
        '수량 (몇 주)', placeholder='예: 10',
        on_change=lambda _e: _update_estimate(),
    ).style('flex: 1 1 160px;')

    estimate_label = ui.label('').classes('text-lg font-bold whitespace-pre-line')
    estimate_caveat_label = ui.label('').classes('vh-muted')

    def _resolve_ticker():
        """입력창 텍스트 → (티커, 종목명, 실패사유). 미국 상위 유니버스 **안에서만** 찾습니다.

        `resolve_stock_query()` 는 시장을 인자로 받는 통화 무관 함수라 원화와 **같은 함수**를
        씁니다. `broad_index` 를 넘기지 않으므로 유니버스 밖 종목은 이름으로 잡히지 않고,
        "티커처럼 생긴" 입력은 그 함수가 코드 자체를 돌려주므로(유니버스 밖 종목을 정직하게
        표시하려는 원래 용도) 여기서 유니버스 포함 여부를 한 번 더 확인합니다.
        """
        ticker, name, error = resolve_stock_query(MARKET_US, query_input.value or '',
                                                  {MARKET_US: index})
        if not ticker:
            return None, None, error
        stock = index.get(ticker)
        if not stock:
            return None, None, (
                f'{ticker}은(는) 미국 상위 유니버스 목록에 없습니다 — 이 트랙은 그 목록 안의 '
                '종목만 주문할 수 있습니다.'
            )
        resolved_name = stock.get("name") or name
        if not resolved_name:
            # 이름을 모르면 저장하지 않습니다(§0-1 — 종목명을 지어내지 않습니다).
            return None, None, f'{ticker}의 종목명을 확인하지 못해 주문할 수 없습니다.'
        return ticker, resolved_name, None

    def _update_estimate() -> None:
        """참고용 예상 금액(달러). **차단 조건이 아닙니다**(2-4-3).

        실제 체결가는 아직 열리지도 않은 그날 미국 정규장의 마감가라 지금은 알 수 없습니다.
        """
        ticker, _name, error = _resolve_ticker()
        if not ticker or error:
            estimate_label.text = ''
            estimate_caveat_label.text = ''
            return
        price = market["price_lookup"](MARKET_US, ticker)
        if price is None:
            estimate_label.text = f'{ticker} — 최근 마감가를 확인하지 못해 예상 금액을 계산할 수 없습니다.'
            estimate_caveat_label.text = ''
            return
        try:
            quantity = _parse_positive_int(quantity_input.value, '수량')
        except ValueError:
            estimate_label.text = f'{ticker} 최근 확정 마감가 {format_amount(price, CURRENCY_USD)}'
            estimate_caveat_label.text = ''
            return
        # 🔴 오너 피드백(2026-08-22) — 수량·예상 금액이 한눈에 크게 보이는 게 중요한
        # 포인트라, 굵고 큰 글씨로 줄바꿈해 두 줄로 보여주고, 안내 문장은 짧게 줄여
        # 아래 작은 글씨로 뺍니다(§ "수량하고 금액을 잘 보는게 중요한 포인트").
        estimate_label.text = (
            f'{quantity:,}주 × {format_amount(price, CURRENCY_USD)}\n'
            f'≈ {format_amount(price * quantity, CURRENCY_USD)}'
        )
        estimate_caveat_label.text = (
            '예상 금액일 뿐 — 실제 체결가는 오늘 밤 열릴 미국 정규장의 마감가로 정해집니다.'
        )

    warning_banner(NOTICE_CRAWL_FAILURE_USD)
    confirm_box = ui.checkbox(
        '위 안내(미국 종가 수집 실패·휴장일이면 주문이 취소됨)를 확인했습니다.')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    async def _submit_usd() -> None:
        message.text = ''
        if not window["is_open"]:
            # 서버(`save_order_usd`)도 같은 규칙으로 거절하지만, 눌러보기 전에 알려 줍니다.
            message.text = f'🚫 {_window_message_usd(window)}'
            return
        if not confirm_box.value:
            message.text = '🚫 위 안내 확인란을 체크해 주세요 — 체결이 취소될 수 있는 경우를 먼저 알려드리는 절차입니다.'
            return
        account_id = account_select.value
        if not account_id:
            message.text = '🚫 주문할 달러 계좌를 골라 주세요.'
            return
        ticker, stock_name, resolve_error = _resolve_ticker()
        if not ticker:
            message.text = f'🚫 {resolve_error}'
            ui.notify('🚫 종목을 찾지 못했습니다 — 아래 문구에서 이유를 확인해 주세요.',
                      type='negative', multi_line=True, close_button='닫기')
            return
        try:
            quantity = _parse_positive_int(quantity_input.value, '수량')
        except ValueError as exc:
            message.text = f'🚫 {exc}'
            return

        try:
            order = await run_blocking(
                save_order_usd,
                client, account_id, ticker, stock_name, quantity,
                # 🔴 **저장일 자신을 포함하는** 후보 목록이어야 합니다(§5-16). 원화용
                #    `_upcoming_trading_days()` 를 넘기면 체결이 하루 밀립니다.
                trading_days=_upcoming_trading_days_usd(window["now_kst"].date()),
                # 이중 방어: 서버가 유니버스를 다시 확인하게 목록을 함께 넘깁니다.
                universe_tickers=set(index),
            )
        except (DuelDbError, DuelRuleError) as exc:
            message.text = f'🚫 {exc}'
            ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                      classes='whitespace-pre-line')
            return
        except Exception as exc:                   # noqa: BLE001
            text = _fail(exc, '달러 주문을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
            message.text = f'🚫 {text}'
            ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
            return

        query_input.value = ''
        quantity_input.value = ''
        estimate_label.text = ''
        estimate_caveat_label.text = ''
        ui.notify(
            f'✅ 달러 주문을 저장했습니다 — {stock_name} ({ticker}) {quantity:,}주\n'
            f'체결 예정일: {order.get("target_date")} 미국 정규장 마감가 '
            '(지금 체결된 것이 아닙니다)\n'
            f'{ORDER_WINDOW_TEXT_USD} 안에서는 수량 수정·취소가 가능합니다.',
            type='positive', multi_line=True, close_button='닫기',
            classes='text-lg whitespace-pre-line',
        )
        on_changed()

    ui.button('💵 달러 매수 주문 저장', on_click=_submit_usd).props('no-caps color=primary')
    ui.label(
        '※ 저장 시점에는 예수금이 충분한지 확정할 수 없습니다 — 체결가(그날 미국 정규장 '
        '마감가)를 아직 모르기 때문입니다. 체결 시점에 모자라면 살 수 있는 만큼만 체결되고 '
        '사유가 남습니다.'
    ).classes('vh-muted')

    ui.separator()
    _render_sell_form_usd(client, user_id, accounts, window, on_changed, bundles=bundles)


# -----------------------------------------------------------------------------
# 7-SELL-USD. 🔁 리밸런싱 매도 칸 (달러) — 원화 판의 미러
# -----------------------------------------------------------------------------
#  갈라진 이유는 이 파일의 다른 미러들과 **정확히 같습니다**: ① 저장 함수가
#  `save_sell_order_usd()`(다른 표) ② 접수 시간대 판정·문구가 USD 기준
#  (`_window_message_usd` · `ORDER_WINDOW_TEXT_USD`) ③ 거래일 후보가
#  `_upcoming_trading_days_usd()`(**저장일 자신을 포함** — §5-16).
#  반대로 창 길이·창 번호·"이번 창 썼는가" 판정은 통화를 모르는 공유 함수(1-RB 절)를
#  그대로 씁니다 — 규칙이 바뀌었는데 한쪽만 고쳐지는 사고를 막기 위해서입니다(§5-11-1).
# -----------------------------------------------------------------------------
def _render_sell_form_usd(client, user_id: str, accounts, window: dict, on_changed,
                          *, bundles=None) -> None:
    """달러 계좌들의 리밸런싱 매도 칸 묶음."""
    ui.markdown('##### 🔁 달러 리밸런싱 매도 (매도 기회는 계좌마다 주기당 1회)')
    ui.label(
        '한 번의 매도 기회로 종목 하나를 1주부터 보유 전량까지 팔 수 있습니다. '
        f'접수 시간대는 달러 매수와 같고({ORDER_WINDOW_TEXT_USD}), 체결도 달러 매수와 같이 '
        '주문을 넣은 바로 그날의 미국 정규장 마감가로 이루어집니다.'
    ).classes('vh-muted')
    ui.label(
        '⚠️ 그날 미국 종가 수집이 실패하거나 미국 증시 휴장일이면 이 매도 주문도 체결되지 '
        '않고 사유와 함께 취소됩니다. 그 경우 이번 매도 기회는 **다시 열립니다** — 취소된 '
        '매도는 그 기회를 소진하지 않습니다.'
    ).classes('vh-muted vh-keep-all')

    for account in accounts or []:
        _render_sell_panel_usd(client, user_id, account, window, on_changed,
                               bundle=_bundle_for(bundles, account.get("id")))


def _render_sell_panel_usd(client, user_id: str, account: dict, window: dict, on_changed,
                           *, bundle) -> None:
    """달러 계좌 1개의 매도 칸.

    🔒 원화와 **같은 이중 방어** — 소유자를 여기서도 한 번 더 확인합니다(§0-3-8).
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 달러 계좌라 매도 창을 그리지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))

    # 🔴 2026-08-22 — 원화 매도 칸과 같은 이유로 같은 방식으로 고칩니다(위 KRW
    #    `_render_sell_panel()` 주석 참고). `ui.card()` → `ui.expansion()`, 기본 닫힘.
    with ui.expansion(esc(f'{title} (달러)'), icon='🔁', value=False).classes('vh-card w-full'):
        if bundle.get("error") is not None:
            error_banner(
                f'🚫 {_fail(bundle["error"], "달러 보유 종목·주문 내역을 불러오지 못해 매도 창을 열 수 없습니다.")}'
            )
            return
        if bundle.get("positions") is None or bundle.get("orders") is None:
            ui.label('달러 보유 종목·주문 내역을 아직 읽지 못해 매도 창을 열 수 없습니다.') \
                .classes('vh-muted')
            return

        state = _rebalance_state(account, bundle["orders"], datetime.now(KST).date())
        ui.label(_rebalance_badge_text(state)).classes('vh-muted vh-keep-all')

        if state["window"] is None:
            info_banner(
                'ℹ️ 아직 매수한 종목이 없어 리밸런싱 매도를 계산할 수 없습니다. '
                '첫 매수가 체결되면 그날부터 이 달러 계좌의 주기가 시작되고 첫 매도 기회가 '
                '열립니다.\n\n'
                f'{state["unavailable_reason"]}'
            )
            return

        if state["used_order"] is not None:
            used = state["used_order"]
            info_banner(
                'ℹ️ 이번 매도 기회는 이미 사용했습니다 — 다음 매도 기회: '
                f'{state["window"]["next_window_starts_on"]}부터\n\n'
                f'이번 기회에 쓴 주문: {used.get("stock_name") or ""} ({used.get("ticker")}) '
                f'{used.get("requested_quantity")}주 · {_order_status_text(used)}\n\n'
                '아직 체결 전(대기)이고 접수 시간대 안이라면, 아래 "내 달러 주문"에서 그 '
                '매도 주문을 취소해 이번 매도 기회를 되살릴 수 있습니다.'
            )
            return

        sellable = _sellable_positions(bundle["positions"])
        if not sellable:
            ui.label('이 달러 계좌에는 팔 수 있는 보유 종목이 없습니다.').classes('vh-muted')
            return

        held_by_ticker = {row["ticker"]: row["quantity"] for row in sellable}
        name_by_ticker = {row["ticker"]: (row["stock_name"] or row["ticker"])
                          for row in sellable}
        options = {
            row["ticker"]: f'{row["ticker"]} · {row["stock_name"] or row["ticker"]} '
                           f'(보유 {row["quantity"]:,}주)'
            for row in sellable
        }

        ticker_select = ui.select(
            options, value=next(iter(options)), label='팔 종목 (보유 종목 중에서)',
        ).classes('w-full')
        quantity_input = ui.input(
            '매도 수량 (몇 주)', placeholder='예: 3',
        ).style('flex: 1 1 160px;')
        ui.label(
            '※ 1주부터 보유 전량까지 가능합니다. 이 달러 계좌에서는 이번 매도 기회에 '
            '**딱 한 번**만 저장할 수 있고, 접수 시간대 안에서는 수량 수정·취소가 됩니다.'
        ).classes('vh-muted vh-keep-all')

        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        async def _submit_sell_usd(_=None) -> None:
            message.text = ''
            if not window["is_open"]:
                message.text = f'🚫 {_window_message_usd(window)}'
                return
            ticker = ticker_select.value
            if not ticker:
                message.text = '🚫 팔 종목을 골라 주세요.'
                return
            held = held_by_ticker.get(ticker)
            if not held:
                message.text = ('🚫 보유 수량을 확인하지 못했습니다 — 화면을 새로고침한 뒤 '
                                '다시 시도해 주세요.')
                return
            try:
                quantity = _parse_positive_int(quantity_input.value, '매도 수량')
            except ValueError as exc:
                message.text = f'🚫 {exc}'
                return
            if quantity > held:
                message.text = (f'🚫 보유 수량({held:,}주)보다 많은 {quantity:,}주는 매도할 수 '
                                '없습니다. 보유한 수량 이하로 다시 입력해 주세요.')
                return

            # 🔴 원화와 같은 이유로 창 번호를 **누를 때 다시 계산**합니다(위 원화 판 주석 참고).
            try:
                current = duel_rules.resolve_rebalance_window(
                    account.get("window_type"), account.get("first_holding_date"),
                    datetime.now(KST).date())
            except DuelRuleError as exc:
                message.text = f'🚫 {exc}'
                return

            try:
                order = await run_blocking(
                    save_sell_order_usd,
                    client, account_id, ticker, name_by_ticker.get(ticker) or ticker,
                    quantity, held, current["window_index"],
                    # 🔴 **저장일 자신을 포함하는** 후보 목록이어야 합니다(§5-16) — 달러
                    #    매도도 매수와 같이 그날 마감가로 체결되기 때문입니다.
                    trading_days=_upcoming_trading_days_usd(window["now_kst"].date()),
                )
            except (DuelDbError, DuelRuleError) as exc:
                message.text = f'🚫 {exc}'
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                text = _fail(exc, '달러 매도 주문을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
                message.text = f'🚫 {text}'
                ui.notify(f'🚫 {text}', type='negative', multi_line=True, close_button='닫기')
                return

            quantity_input.value = ''
            ui.notify(
                f'✅ 달러 리밸런싱 매도 주문을 저장했습니다 — {name_by_ticker.get(ticker)} '
                f'({ticker}) {quantity:,}주\n'
                f'체결 예정일: {order.get("target_date")} 미국 정규장 마감가 '
                '(지금 체결된 것이 아닙니다)\n'
                f'{ORDER_WINDOW_TEXT_USD} 안에서는 수량 수정·취소가 가능하고, 취소하면 이번 '
                '매도 기회가 다시 열립니다.',
                type='positive', multi_line=True, close_button='닫기',
                classes='text-lg whitespace-pre-line',
            )
            on_changed()

        ui.button('🔁 달러 리밸런싱 매도 주문 저장', on_click=_submit_sell_usd) \
            .props('no-caps color=negative')


# =============================================================================
# 8. 주문 내역 (대기 중 주문 수정·취소 + 최근 결과)
# =============================================================================
async def _render_orders_section(client, user_id: str, accounts, window: dict, on_changed,
                                 *, bundles=None, price_lookup=None) -> None:
    """내 주문 영역.

    💡 2026-08-23 오너 요청 — 대기 주문 줄에 "최근 종가 기준 예상 금액"을 붙이려고
       `price_lookup` 을 **위에서 받아 그대로 내려보냅니다.** 여기서 조회 함수를 새로
       만들면 주문 폼이 쓰는 목록과 어긋날 수 있고 파일을 읽는 경로가 하나 더 생깁니다
       (§0-3-2 · §0-3-10) — 이미 만들어져 있는 `market["price_lookup"]` 을 전달만 합니다.
    """
    ui.markdown('#### 📋 내 주문')
    if not window["is_open"]:
        info_banner(
            '지금은 접수 시간이 아니라 주문 수량 수정·취소 버튼이 보이지 않습니다. '
            f'다음 접수 시간({ORDER_WINDOW_TEXT})에 다시 열립니다.'
        )
    for account in accounts:
        await _render_account_orders(client, user_id, account, window, on_changed,
                                     bundle=_bundle_for(bundles, account.get("id")),
                                     price_lookup=price_lookup)


async def _render_account_orders(client, user_id: str, account: dict, window: dict, on_changed,
                                 *, bundle=None, price_lookup=None) -> None:
    """계좌 1개의 주문 목록 — 대기 중 주문(수정·취소 가능) + 최근 결과.

    🔒 소유자 확인은 카드와 같은 이유로 여기서도 한 번 더 합니다(§0-3-8).

    🔁 2026-08-21 — 주문 목록을 `bundle`(4-B 절)에서 받습니다. 매도 칸이 "이번 창을 썼는지"를
       판정하려면 같은 목록이 필요한데, 두 곳이 각자 읽으면 왕복이 계좌 수만큼 늘고 게다가
       **두 목록이 서로 다른 순간의 상태**가 될 수 있습니다(그 사이에 저장된 주문이 한쪽에만
       보이는 상태). 묶음을 넘기지 않는 옛 호출부에서는 예전처럼 직접 읽습니다.
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 계좌라 주문을 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))
    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'**{esc(title)}**')
        if bundle is not None and bundle.get("error") is not None:
            error_banner(f'🚫 {_fail(bundle["error"], "주문 내역을 불러오지 못했습니다.")}')
            return
        try:
            if bundle is not None and bundle.get("orders") is not None:
                orders = bundle["orders"]
            else:
                orders = await run_blocking(fetch_my_orders, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "주문 내역을 불러오지 못했습니다.")}')
            return

        pending = [o for o in orders if o.get("status") == ORDER_PENDING]
        if pending:
            ui.label(f'⏳ 체결 대기 중인 주문 {len(pending)}건').classes('vh-muted')
            for order in pending:
                _render_pending_order_row(client, order, window, on_changed,
                                          price_lookup=price_lookup)
        else:
            ui.label('체결 대기 중인 주문이 없습니다.').classes('vh-muted')

        history = [o for o in orders if o.get("status") != ORDER_PENDING][:RECENT_ORDER_LIMIT]
        if history:
            _render_order_history_table(history)


def _pending_order_price_and_quantity(order, price_lookup, market):
    """대기 주문 1건의 (가격, 수량) — 최근 종가 기준, 확정 체결가가 아닙니다.

    `_pending_estimate_text()` 와 `_pending_orders_cash_impact()` 가 공유하는 추출 로직입니다
    (§0-3-10 — 같은 계산을 두 번 만들지 않습니다). 못 구한 값은 `None` 으로 돌려주고,
    "0"으로 지어내지 않습니다(§0-1) — 호출부가 각자의 규칙대로 처리합니다.
    """
    price = price_lookup(market, order.get("ticker")) if price_lookup is not None else None
    try:
        quantity = int(order.get("requested_quantity"))
    except (TypeError, ValueError):
        quantity = None
    return price, quantity


def _pending_orders_cash_impact(orders, price_lookup, market):
    """대기 중인 매수·매도 주문이 예수금에 미칠 **추정** 영향의 합.

    순수 함수 — 통화를 모릅니다(시장은 인자로 받습니다, §5-11-1). 매수는 예수금을 줄이고
    매도는 늘립니다(리밸런싱 매도 대금은 같은 밤 배치에서 매수 재원으로 쓰이므로, 남을
    예수금을 추정할 때도 더해 주는 게 맞습니다). 둘 다 아직 확정 체결가가 아닌 **최근 종가
    기준 추정**입니다(2-4-3). 가격 또는 수량을 모르는 주문, 방향(side)을 모르는 옛 행은
    합계에서 빼고 개수만 셉니다(§0-1 — 모르는 값을 0으로 지어내 합치지 않습니다).
    """
    delta = 0
    unknown_count = 0
    buy_count = 0
    sell_count = 0
    pending_count = 0
    for order in orders or []:
        if (order or {}).get("status") != ORDER_PENDING:
            continue
        pending_count += 1
        side = order.get("side")
        if side == "buy":
            buy_count += 1
        elif side == "sell":
            sell_count += 1
        price, quantity = _pending_order_price_and_quantity(order, price_lookup, market)
        if price is None or quantity is None or side not in ("buy", "sell"):
            unknown_count += 1
            continue
        amount = price * quantity
        delta += amount if side == "sell" else -amount
    return {
        "delta": delta,
        "unknown_count": unknown_count,
        "pending_count": pending_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
    }


def _pending_estimate_text(order: dict, price_lookup, market: str, currency: str,
                           *, price_name: str, caveat: str) -> str:
    """대기 주문 줄에 붙는 **참고용** 예상 금액 문구.

    통화도 시장도 **인자로 받는** 순수 함수입니다(§5-11-1 — 데이터는 분리, 규칙은 공유).
    두 트랙이 이 계산을 각자 복제하면 한쪽만 고치는 사고가 나므로 여기 한 군데만 둡니다.

    · 매수·매도 구분이 없습니다 — 두 방향 모두 "수량 × 최근 가격"이 그대로 맞습니다.
    · §0-1 — 가격을 못 구하면 **0 으로 위장하지 않고** "가격 확인 중"이라고 말합니다
      (`_position_rows()` 가 이미 쓰는 것과 같은 문구·같은 원칙).
    · 2-4-3 — 이 값은 확정 체결가가 아니라 최근 종가 기준 추정입니다. 그 사실이 문구에서
      드러나도록 "참고"·"예상"과 `caveat` 를 함께 답니다.
    """
    price, quantity = _pending_order_price_and_quantity(order, price_lookup, market)

    if price is None:
        return f'💡 참고 · 가격 확인 중 — {price_name}를 확인하지 못해 예상 금액을 낼 수 없습니다.'
    if quantity is None:
        return f'💡 참고 · {price_name} {format_amount(price, currency)} — 주문 수량을 읽지 못해 예상 금액을 낼 수 없습니다.'
    return (f'💡 참고 · {price_name} {format_amount(price, currency)} × {quantity:,}주 '
            f'≈ 예상 {format_amount(price * quantity, currency)} — {caveat}')


def _render_pending_order_row(client, order: dict, window: dict, on_changed,
                              *, price_lookup=None) -> None:
    """대기 주문 한 줄 — 수량 수정 · 취소 + 최근 종가 기준 **참고용** 예상 금액.

    수정·취소가 가능한 시간대인지는 화면에서도 확인하지만, **최종 권한은 서버**입니다
    (`utils/duel_db.py` 의 시간대 판정 + DB 트리거). 화면은 버튼을 감추는 것까지만 합니다.

    💡 2026-08-23 오너 요청 — "주문을 넣은 곳에도 얼마나 샀는지 가격이 얼마나 샀는지 표시해
       주는건 안한거지?". 저장된 대기 주문만 봐서는 체결되면 얼마가 빠져나갈지 알 수 없어
       주문 폼의 예상 금액과 **같은 성격의 참고 줄**을 여기에도 붙입니다.
       ⚠️ 이 숫자는 **최근 종가 기준 추정**이지 확정 체결가가 아닙니다(2-4-3 — 이 앱에는
          실시간 시세가 없고 체결가는 체결일 종가로 정해집니다). 그래서 문구에 "참고"·
          "예상"을 넣고, 체결가가 아직 정해지지 않았다는 말을 함께 답니다.
       매도 주문도 같은 계산(수량 × 최근 종가)이 그대로 맞아 방향을 가리지 않습니다.
    """
    order_id = order.get("id")
    # 🔁 2026-08-21 — 매수·매도가 같은 목록에 섞이므로 방향을 **맨 앞에** 붙입니다.
    #    (수량 수정·취소 자체는 side 와 무관하게 같은 함수·같은 트리거를 씁니다.)
    label = (f'{_order_side_text(order)} · '
             f'{order.get("stock_name") or ""} ({order.get("ticker")}) · '
             f'{order.get("requested_quantity")}주 · 체결 예정일 {order.get("target_date")}')
    estimate = _pending_estimate_text(order, price_lookup, MARKET_KR, CURRENCY,
                                      price_name='최근 종가',
                                      caveat='실제 체결가는 체결일 종가로 정해집니다')

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        with ui.column().classes('flex-1 min-w-0 gap-0'):
            ui.label(label).classes('vh-keep-all')
            ui.label(estimate).classes('vh-muted vh-keep-all')
        if not window["is_open"]:
            return

        quantity_input = ui.input(value=str(order.get("requested_quantity") or '')) \
            .props('dense').style('flex: 0 0 90px;').tooltip('바꿀 수량(주)')

        async def _save(_=None) -> None:
            try:
                quantity = _parse_positive_int(quantity_input.value, '수량')
            except ValueError as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기')
                return
            try:
                await run_blocking(edit_order, client, order_id, quantity)
            except (DuelDbError, DuelRuleError) as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                ui.notify(f'🚫 {_fail(exc, "주문을 수정하지 못했습니다.")}',
                          type='negative', multi_line=True, close_button='닫기')
                return
            ui.notify(f'✅ 수량을 {quantity:,}주로 바꿨습니다.', type='positive')
            on_changed()

        async def _cancel(_=None) -> None:
            try:
                await run_blocking(cancel_order, client, order_id)
            except (DuelDbError, DuelRuleError) as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                ui.notify(f'🚫 {_fail(exc, "주문을 취소하지 못했습니다.")}',
                          type='negative', multi_line=True, close_button='닫기')
                return
            # 주문 행은 지워지지 않고 '취소됨 + 사유'로 남습니다(§0-1 — 조용히 사라지지 않기).
            ui.notify('✅ 주문을 취소했습니다 — 내역에는 취소 기록이 남습니다.', type='positive')
            on_changed()

        ui.button('수량 저장', on_click=_save).props('flat dense no-caps').classes('shrink-0')
        ui.button('취소', on_click=_cancel).props('flat dense no-caps color=negative') \
            .classes('shrink-0')


def _order_status_text(order: dict) -> str:
    """주문 상태 → 한국어. **부분체결은 요청·실제 수량을 둘 다** 보여줍니다(1-3 / 2-4-6)."""
    status = order.get("status")
    requested = order.get("requested_quantity")
    filled = order.get("filled_quantity")
    if status == "filled":
        return f'✅ 전량 체결 ({filled}주)'
    if status == "partially_filled":
        return f'⚠️ 부분 체결 — 요청 {requested}주 중 {filled}주만 체결'
    if status == "cancelled":
        return '🚫 취소됨'
    if status == "expired":
        return '🚫 체결 없음(예수금으로 1주도 사지 못함)'
    if status == ORDER_PENDING:
        return '⏳ 체결 대기'
    return str(status)


def _render_order_history_table(orders) -> None:
    """최근 주문 결과 표. 체결가·체결금액·사유를 **전부** 보여줍니다(§0-1 — 조용한 실패 금지).

    🔁 2026-08-21 — **'구분'(매수/매도) 칸이 생겼습니다.** 두 방향이 한 표에 섞이는데 방향을
       안 적으면 "왜 이 종목이 줄었지?"를 내역만 보고는 알 수 없습니다. 매도 행에는 몇 번째
       창을 쓴 주문인지도 함께 나옵니다(`_order_side_text()` — 통화를 모르는 공유 함수).
    """
    headers = ['종목', '구분', '상태', '체결일', '체결가', '체결금액', '사유']
    body_rows = []
    for order in orders:
        name = order.get("stock_name") or order.get("ticker")
        body_rows.append([
            (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
             f'{esc(str(name))}<br>({esc(str(order.get("ticker")))})</div>'),
            esc(_order_side_text(order)),
            esc(_order_status_text(order)),
            esc(str(order.get("filled_date") or order.get("target_date") or '—')),
            esc(format_amount(order.get("filled_price"), CURRENCY)
                if order.get("filled_price") is not None else '—'),
            esc(format_amount(order.get("filled_amount"), CURRENCY)
                if order.get("filled_amount") is not None else '—'),
            # 🔐 §0-3-9 — 사유 문장은 배치가 쓴 값이지만 예외 없이 이스케이프합니다.
            esc(str(order.get("fail_reason") or '—')),
        ])
    ui.html(holdings_table_html(headers, body_rows)).classes('w-full')


# -----------------------------------------------------------------------------
# 8-USD. 💵 달러 주문 내역 — 다른 표(`duel_orders_usd`) · USD 접수 시간대 · 달러 표기
# -----------------------------------------------------------------------------
async def _render_orders_section_usd(client, user_id: str, accounts, window: dict,
                                     on_changed, *, bundles=None, price_lookup=None) -> None:
    """달러 주문 내역 영역. 원화 `_render_orders_section()` 의 미러입니다.

    갈라진 이유는 ① 조회 함수가 `fetch_my_orders_usd`(다른 표) ② 안내 문구의 접수 시간대가
    `ORDER_WINDOW_TEXT_USD` ③ 금액 표기가 달러 — 이 세 가지뿐이고, 판정 논리는 같습니다.

    💡 2026-08-23 — 원화와 같은 이유로 `price_lookup` 을 받아 그대로 내려보냅니다. 여기로
       오는 것은 **달러 유니버스로 만든** `market_usd["price_lookup"]` 이어야 합니다 —
       원화 조회 함수가 들어오면 미국 티커를 하나도 못 찾습니다(§5-11-2).
    """
    ui.markdown('#### 📋 내 달러 주문')
    if not window["is_open"]:
        info_banner(
            '지금은 달러 트랙 접수 시간이 아니라 주문 수량 수정·취소 버튼이 보이지 않습니다. '
            f'다음 접수 시간({ORDER_WINDOW_TEXT_USD})에 다시 열립니다.'
        )
    for account in accounts:
        await _render_account_orders_usd(client, user_id, account, window, on_changed,
                                         bundle=_bundle_for(bundles, account.get("id")),
                                         price_lookup=price_lookup)


async def _render_account_orders_usd(client, user_id: str, account: dict, window: dict,
                                     on_changed, *, bundle=None, price_lookup=None) -> None:
    """달러 계좌 1개의 주문 목록 — 대기 중 주문(수정·취소 가능) + 최근 결과.

    🔒 소유자 확인은 원화와 같은 이유로 여기서도 한 번 더 합니다(§0-3-8).
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 달러 계좌라 주문을 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))
    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'**{esc(title)} (달러)**')
        if bundle is not None and bundle.get("error") is not None:
            error_banner(f'🚫 {_fail(bundle["error"], "달러 주문 내역을 불러오지 못했습니다.")}')
            return
        try:
            if bundle is not None and bundle.get("orders") is not None:
                orders = bundle["orders"]
            else:
                orders = await run_blocking(fetch_my_orders_usd, client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "달러 주문 내역을 불러오지 못했습니다.")}')
            return

        pending = [o for o in orders if o.get("status") == ORDER_PENDING]
        if pending:
            ui.label(f'⏳ 체결 대기 중인 달러 주문 {len(pending)}건').classes('vh-muted')
            for order in pending:
                _render_pending_order_row_usd(client, order, window, on_changed,
                                              price_lookup=price_lookup)
        else:
            ui.label('체결 대기 중인 달러 주문이 없습니다.').classes('vh-muted')

        history = [o for o in orders if o.get("status") != ORDER_PENDING][:RECENT_ORDER_LIMIT]
        if history:
            _render_order_history_table_usd(history)


def _render_pending_order_row_usd(client, order: dict, window: dict, on_changed,
                                  *, price_lookup=None) -> None:
    """달러 대기 주문 한 줄 — 수량 수정 · 취소 + 최근 마감가 기준 **참고용** 예상 금액.

    ⚠️ `edit_order_usd()` / `cancel_order_usd()` 를 부릅니다. 원화 함수를 섞어 부르면
       **다른 표의 주문 id 를 찾게 되어** 아무것도 못 찾거나(운이 좋으면) 엉뚱한 행을
       건드립니다(운이 나쁘면). 그리고 두 함수는 접수 시간대도 USD 기준으로 판정합니다 —
       거절 문구까지 `_translate_order_guard_error_usd()` 가 달러용으로 번역해 둡니다.

    수정·취소 가능 시간대인지는 화면에서도 확인하지만 **최종 권한은 서버**입니다.

    💡 2026-08-23 — 원화와 같은 참고 줄을 붙입니다. 계산·문구 규칙은 통화를 모르는 공유
       함수(`_pending_estimate_text()`)에 있고, 여기서는 **미국 시장·달러 서식**만 골라
       넘깁니다. 이 값도 확정 체결가가 아니라 최근 마감가 기준 추정입니다(2-4-3).
    """
    order_id = order.get("id")
    # 🔁 원화와 같은 이유로 방향을 맨 앞에 붙입니다(매수·매도가 한 목록에 섞입니다).
    label = (f'{_order_side_text(order)} · '
             f'{order.get("stock_name") or ""} ({order.get("ticker")}) · '
             f'{order.get("requested_quantity")}주 · '
             f'체결 예정일 {order.get("target_date")} (미국 정규장 마감가)')
    estimate = _pending_estimate_text(order, price_lookup, MARKET_US, CURRENCY_USD,
                                      price_name='최근 마감가',
                                      caveat='실제 체결가는 그날 미국 정규장 마감가로 정해집니다')

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        with ui.column().classes('flex-1 min-w-0 gap-0'):
            ui.label(label).classes('vh-keep-all')
            ui.label(estimate).classes('vh-muted vh-keep-all')
        if not window["is_open"]:
            return

        quantity_input = ui.input(value=str(order.get("requested_quantity") or '')) \
            .props('dense').style('flex: 0 0 90px;').tooltip('바꿀 수량(주)')

        async def _save_usd(_=None) -> None:
            try:
                quantity = _parse_positive_int(quantity_input.value, '수량')
            except ValueError as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기')
                return
            try:
                await run_blocking(edit_order_usd, client, order_id, quantity)
            except (DuelDbError, DuelRuleError) as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                ui.notify(f'🚫 {_fail(exc, "달러 주문을 수정하지 못했습니다.")}',
                          type='negative', multi_line=True, close_button='닫기')
                return
            ui.notify(f'✅ 수량을 {quantity:,}주로 바꿨습니다.', type='positive')
            on_changed()

        async def _cancel_usd(_=None) -> None:
            try:
                await run_blocking(cancel_order_usd, client, order_id)
            except (DuelDbError, DuelRuleError) as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기',
                          classes='whitespace-pre-line')
                return
            except Exception as exc:               # noqa: BLE001
                ui.notify(f'🚫 {_fail(exc, "달러 주문을 취소하지 못했습니다.")}',
                          type='negative', multi_line=True, close_button='닫기')
                return
            # 주문 행은 지워지지 않고 '취소됨 + 사유'로 남습니다(§0-1 — 조용히 사라지지 않기).
            ui.notify('✅ 달러 주문을 취소했습니다 — 내역에는 취소 기록이 남습니다.', type='positive')
            on_changed()

        ui.button('수량 저장', on_click=_save_usd).props('flat dense no-caps').classes('shrink-0')
        ui.button('취소', on_click=_cancel_usd).props('flat dense no-caps color=negative') \
            .classes('shrink-0')


def _render_order_history_table_usd(orders) -> None:
    """달러 최근 주문 결과 표. 체결가·체결금액·사유를 **전부** 보여줍니다(§0-1).

    상태 문구(`_order_status_text()`)와 방향 문구(`_order_side_text()`)는 통화를 모르는
    순수 함수라 원화와 **공유**하고, 갈라진 것은 금액 표기 통화 하나뿐입니다.
    """
    headers = ['종목', '구분', '상태', '체결일', '체결가', '체결금액', '사유']
    body_rows = []
    for order in orders:
        name = order.get("stock_name") or order.get("ticker")
        body_rows.append([
            (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
             f'{esc(str(name))}<br>({esc(str(order.get("ticker")))})</div>'),
            esc(_order_side_text(order)),
            esc(_order_status_text(order)),
            esc(str(order.get("filled_date") or order.get("target_date") or '—')),
            esc(format_amount(order.get("filled_price"), CURRENCY_USD)
                if order.get("filled_price") is not None else '—'),
            esc(format_amount(order.get("filled_amount"), CURRENCY_USD)
                if order.get("filled_amount") is not None else '—'),
            # 🔐 §0-3-9 — 사유 문장은 배치가 쓴 값이지만 예외 없이 이스케이프합니다.
            esc(str(order.get("fail_reason") or '—')),
        ])
    ui.html(holdings_table_html(headers, body_rows)).classes('w-full')
