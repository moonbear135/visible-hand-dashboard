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
    sum_cash_balance,
)
from utils.duel_rules import (
    ACCOUNT_WINDOW_TYPES,
    KST,
    MONTHLY_DEPOSIT_DAY,
    MONTHLY_DEPOSIT_KRW,
    ORDER_PENDING,
    SEED_AMOUNT_KRW,
    TWR_INSUFFICIENT,
    TWR_NO_DATA,
    TWR_OK,
    DuelRuleError,
)
from utils.scorecard_db import (
    MARKET_KR,
    SNAPSHOT_FILENAMES,
    build_universe_index,
    current_user,
    format_amount,
    make_price_lookup,
    resolve_stock_query,
    supabase_status,
    user_id_of,
)
from web.auth import get_client, has_supabase_session, is_admin, logout
from web.auth_ui import fail_message, render_auth
from web.components import (
    error_banner, esc, holdings_table_html, info_banner, metric_card, pct_text, warning_banner,
)
from web.layout import DUEL_ENABLED, DUEL_MENU_ADMIN_ONLY, layout
from web.state import data_path, load_json_file

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

# =============================================================================
# 상시 노출 고지 3종 — 작업지시서 2-8 (§0-1: 숨기지 않고 화면에 그대로 씁니다)
# =============================================================================
NOTICE_NO_DIVIDEND = (
    "배당금은 반영되지 않습니다. 이 앱에는 배당 지급 캘린더(사건별 날짜와 확정 주당 금액)가 "
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
    "주문은 저장 즉시 체결되지 않습니다. 저장한 주문은 예약일 뿐이고, "
    "다음 거래일(D+1)의 장이 끝난 뒤 확정된 종가로 그날 밤 배치가 체결합니다."
)

NOTICE_BUY_ONLY = (
    "이 모듈은 매수만 가능합니다. 매도는 지원하지 않습니다 — 한 번 산 종목은 팔 수 없고, "
    "매달 들어오는 돈으로 계속 사 모으는 적립식 매수 방식입니다."
)

#: 화면 맨 위에 **항상** 보여야 하는 3종. 순서를 바꿔도 되지만 빼지는 마세요(2-8).
MANDATORY_NOTICES = (NOTICE_NO_DIVIDEND, NOTICE_FILL_TIMING, NOTICE_BUY_ONLY)

# 주문 저장 전에 **미리** 고지해야 하는 문구(2-4-5 — "사후 통보로 끝내지 않습니다").
# 아래 주문 폼의 체크 확인 영역에 그대로 들어갑니다.
NOTICE_CRAWL_FAILURE = (
    "⚠️ 그날 코스피 종가 수집이 실패하거나 휴장일이면, 그 날짜로 잡힌 주문은 다음 날로 "
    "미뤄지지 않고 그 자리에서 취소됩니다. 취소된 주문에는 사유가 남고 예수금은 그대로 "
    "계좌에 남으니, 다음 접수 시간대에 다시 주문하시면 됩니다. "
    "수집 결과가 애매해서 사람이 확인해야 하는 날(대량 무변동 등)에는 취소하지 않고 "
    "'대기' 상태로 남겨 두었다가, 관리자가 값을 확인한 뒤 체결 또는 취소로 결론을 냅니다."
)

# 왜 다음 거래일 종가로 체결하는지 — 한 줄 설명(2-4 "왜 그날 종가가 아닌가").
NOTICE_WHY_NEXT_DAY = (
    "왜 다음 거래일 종가일까요? 주문을 받는 저녁 시간대에는 오늘 종가가 이미 다 알려져 "
    "있습니다. 이미 아는 가격으로 체결하면 결과를 보고 베팅하는 셈이라 대결이 불공정해집니다. "
    "그래서 아직 아무도 모르는 값 — 다음 거래일의 종가 — 로만 체결합니다."
)

# 이월(안 쓴 현금) 설명 — 2-3 "안 쓴 현금은 소멸하지 않고 이월되며 강제 투자되지 않습니다".
NOTICE_CASH_ROLLOVER = (
    "쓰지 않은 예수금은 사라지지 않습니다. 다음 달로 그대로 넘어가고, 억지로 어딘가에 "
    "투자되지도 않습니다. 예수금이 남아 있는 한 언제든 매수할 수 있고, 0원이 되면 다음 "
    "입금일까지 매수만 잠깐 쉬게 됩니다(별도의 '매수 기간' 제한은 없습니다)."
)

# 수익률 문구 — 2-6 "'내 성적표'와 계산 방식이 다르다는 걸 화면 문구에도 명확히 구분해서".
NOTICE_TWR = (
    "여기 '누적 수익률'은 시간가중수익률(TWR)입니다. 매달 돈이 새로 들어오는 계좌라서, "
    "단순히 '지금 자산 ÷ 처음 시드'로 계산하면 입금액이 수익처럼 보입니다(아무것도 안 사도 "
    "수익률이 오르는 착시). 그래서 입금이 있던 날은 그 입금액을 빼고 계산합니다. "
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
def _load_kospi_universe() -> dict:
    """코스피 상위 200 유니버스 인덱스 + 메타데이터. 파일이 없으면 인덱스가 빈 dict 입니다.

    반환 dict 에는 **사용자 데이터가 한 조각도 없습니다** — 종목명·종가뿐이라 함수 사이로
    자유롭게 넘겨도 §0-3-8 위반이 아닙니다.
    """
    payload, _load_error = load_json_file(data_path(SNAPSHOT_FILENAMES[MARKET_KR]))
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
@ui.page('/duel')
def duel_page() -> None:
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

        try:
            client = get_client()
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return
        if client is None:
            _render_not_ready(supabase_status())
            return

        # "지금 누가 로그인했는지"는 **이 접속 전용 클라이언트에게 직접 물어봅니다.**
        # 저장소에 캐시해둔 값을 믿지 않는 이유는 §0-3-8 그대로입니다.
        user = current_user(client)
        user_id = user_id_of(user)
        if not user_id:
            logout()                                # 끊어진 세션을 남겨두지 않습니다
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        try:
            _render_body(client, user_id, email)
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
    """
    monthly_total = MONTHLY_DEPOSIT_KRW * len(ACCOUNT_WINDOW_TYPES)
    with ui.expansion('📖 이 대결은 어떻게 굴러가나요? (규칙 전체 보기)').classes('w-full'):
        ui.markdown(
            f'- **계좌 3개, 시드 각각 {format_amount(SEED_AMOUNT_KRW, CURRENCY)}** — 참여하면 '
            f'1개월·3개월·6개월 계좌가 한 번에 만들어지고, 각 계좌에 가상 현금이 들어옵니다 '
            f'(합계 {format_amount(SEED_AMOUNT_KRW * len(ACCOUNT_WINDOW_TYPES), CURRENCY)}). '
            '시드 금액은 사용자가 바꿀 수 없습니다.\n'
            f'- **매월 {MONTHLY_DEPOSIT_DAY}일 정기 입금** — 세 계좌 **각각**에 '
            f'{format_amount(MONTHLY_DEPOSIT_KRW, CURRENCY)}씩, 그날 0시 직후 들어옵니다 '
            f'(사용자 1명당 월 {format_amount(monthly_total, CURRENCY)}). 6개월 계좌라고 '
            '적게 넣지 않습니다 — 세 계좌의 규칙은 완전히 같습니다.\n'
            '- **세 계좌의 차이는 규칙이 아니라 선택입니다** — 같은 규칙 위에서 계좌마다 다른 '
            '종목을 골라 보라고 만든 3개입니다(예: 1개월 계좌엔 이 종목, 6개월 계좌엔 저 종목).\n'
            '- **살 수 있는 종목** — 코스피 시가총액 상위 200종목, 원화만. 미국주식·코스닥·ETF 는 '
            '이 모듈에서 거래할 수 없습니다.\n'
            f'- **주문 접수 시간** — 매일 {ORDER_WINDOW_TEXT}. 이 시간 안에서는 저장한 주문의 '
            '수량을 바꾸거나 취소할 수 있고, 시간이 지나면 다음 거래일 체결 대상으로 확정됩니다.\n'
            f'- **{NOTICE_WHY_NEXT_DAY}**\n'
            f'- **{NOTICE_CASH_ROLLOVER}**\n'
            '- **예수금이 모자라면 살 수 있는 만큼만** — 체결 시점에 주문 금액이 예수금을 넘으면 '
            '주문 전체가 취소되는 게 아니라, 예수금으로 살 수 있는 최대 정수 수량만 체결되고 '
            '나머지는 사유와 함께 남습니다(1주도 못 사면 그때는 체결 없음으로 끝납니다).\n'
            f'- **{NOTICE_TWR}**\n'
            '- **상장폐지** — 확인된 상장폐지는 그 종목 평가액을 0원으로 확정합니다(손실이 손실로 '
            '보여야 하므로 수량·평단가는 지우지 않습니다). 단순히 가격을 못 구한 종목은 '
            '"가격 확인 중"으로 표시하고 **절대 0원으로 처리하지 않습니다**.'
        )


# =============================================================================
# 4. 로그인 후 본문
# =============================================================================
def _render_body(client, user_id: str, email) -> None:
    """로그인 후 화면 전체.

    ⚠️ `client` 와 `user_id` 는 **반드시 인자로 받습니다.** 이 아래 어떤 함수도 "지금 누가
       로그인했는지"를 전역이나 저장소에서 다시 추측하지 않습니다(§0-3-8 함수 설계 원칙).
    """
    def _logout_click() -> None:
        logout()
        ui.navigate.reload()

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.label(f'로그인: {email or user_id}').classes('flex-1 min-w-0 truncate vh-muted')
        ui.button('로그아웃', on_click=_logout_click).props('flat dense no-caps').classes('shrink-0')

    _render_rules_expansion()

    market = _load_kospi_universe()                # 읽기 전용 시세 (사용자 데이터 아님)
    if not market["index"]:
        error_banner(
            '🚫 코스피 상위 200 종목 스냅샷(data/kospi200_pegy_latest.json)을 읽지 못했습니다. '
            '주문 가능 종목 목록과 보유 종목 평가금액을 표시할 수 없습니다 — 값을 추정하지 않습니다.'
        )

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

    # 계좌 목록은 **이 refreshable 안에서 매번 새로 조회**합니다. 참여/주문/수정/취소 후
    # `.refresh()` 만 부르면 이 블록만 다시 그려집니다('내 성적표'와 같은 방식).
    @ui.refreshable
    def duel_section() -> None:
        _render_duel_section(client, user_id, market, window, duel_section.refresh)

    duel_section()


def _render_duel_section(client, user_id: str, market: dict, window: dict, on_changed) -> None:
    """계좌가 있으면 대결 화면을, 없으면 참여 안내를 그립니다."""
    try:
        accounts = fetch_my_accounts(client, user_id)
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

    if not mine:
        _render_opt_in(client, user_id, on_changed)
        return

    _render_accounts(client, user_id, mine, market, on_changed)
    ui.separator()
    _render_order_form(client, user_id, mine, market, window, on_changed)
    ui.separator()
    _render_orders_section(client, user_id, mine, window, on_changed)


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
            '- 거래는 **매수만** 가능하고, **코스피 상위 200종목·원화**만 다룹니다.\n'
            '- **배당금은 반영되지 않습니다.** 주문은 저장 즉시 체결되지 않고 '
            '**다음 거래일 종가**로 체결됩니다.\n'
            '- 여기서 오가는 돈은 전부 **가상**입니다. 실제 계좌·실제 주식과는 아무 관계가 없습니다.'
        )
        ui.label(
            '※ 참여해도 성적이 다른 사람에게 공개되지 않습니다. 공개 순위표는 별도의 동의 절차를 '
            '거친 뒤에만 참여할 수 있고, 아직 준비 중입니다.'
        ).classes('vh-muted')

        message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

        def _join() -> None:
            message.text = ''
            try:
                accounts = opt_in(client)
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


def _render_accounts(client, user_id: str, accounts, market: dict, on_changed) -> None:
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
        for account in accounts:
            _render_account_card(client, user_id, account, market)


def _render_account_card(client, user_id: str, account: dict, market: dict) -> None:
    """계좌 1개 카드 — 총자산·현금·평가액·누적 TWR·보유종목.

    🔒 그리기 전에 소유자를 한 번 더 확인합니다(§0-3-8 이중 방어).
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

        try:
            ledger = fetch_my_cash_ledger(client, account_id)
            cash = sum_cash_balance(ledger)
            positions = fetch_my_positions(client, account_id)
            snapshots = fetch_my_snapshots(client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "계좌 정보를 불러오지 못했습니다.")}')
            return

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
                f'다음 {MONTHLY_DEPOSIT_DAY}일 입금 뒤부터 다시 주문할 수 있습니다.'
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


# =============================================================================
# 7. 주문 창 (2-4 — 매수 전용, 수량 기준, 코스피 상위 200 안에서만)
# =============================================================================
def _render_order_form(client, user_id: str, accounts, market: dict, window: dict,
                       on_changed) -> None:
    """주문 저장 폼.

    ⚠️ 유니버스 검사·시간대 검사·거래일 확정은 전부 `utils/duel_db.py::save_order()` 와
       `utils/duel_rules.py` 가 합니다. 이 함수가 하는 일은 **입력 도우미(검색·수량 입력·
       사전 고지)** 와 실패 문구 표시뿐입니다(§0-3-10 — 판정 로직을 두 번 만들지 않습니다).
    """
    index = market["index"]
    ui.markdown('#### 🛒 주문하기 (매수 전용)')
    ui.label(
        f'코스피 상위 종목만, 원화로만, 주식 수 단위로 주문합니다. '
        f'현재 주문 가능 목록에는 {len(index)}종목이 있습니다.'
    ).classes('vh-muted')
    ui.label(f'⏱️ {NOTICE_FILL_TIMING}').classes('vh-muted')

    if not index:
        error_banner('🚫 주문 가능 종목 목록을 읽지 못해 주문 창을 열 수 없습니다.')
        return

    # ⚠️ 이 dict 들은 **페이지 함수 호출마다 새로 만들어지는 지역 상태**입니다(접속마다 별개).
    #    모듈 전역에 두면 접속자끼리 입력값이 섞입니다(§0-3-8).
    account_options = {
        str(account.get("id")): f'{WINDOW_TITLES.get(account.get("window_type"), "")} '
                                f'({account.get("window_type")})'
        for account in accounts
        if account.get("user_id") == user_id       # 🔒 남의 계좌를 고를 수 있는 경로 자체를 없앰
    }

    account_select = ui.select(
        account_options, value=next(iter(account_options), None), label='주문할 계좌',
    ).classes('w-full')

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

    estimate_label = ui.label('').classes('vh-muted')

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
            return
        price = market["price_lookup"](MARKET_KR, ticker)
        if price is None:
            estimate_label.text = f'{ticker} — 최근 종가를 확인하지 못해 예상 금액을 계산할 수 없습니다.'
            return
        try:
            quantity = _parse_positive_int(quantity_input.value, '수량')
        except ValueError:
            estimate_label.text = (
                f'참고 — {ticker}의 최근 확정 종가는 {format_amount(price, CURRENCY)}입니다.'
            )
            return
        estimate_label.text = (
            f'참고 — 최근 확정 종가 {format_amount(price, CURRENCY)} × {quantity:,}주 ≈ '
            f'{format_amount(price * quantity, CURRENCY)}. '
            '실제 체결가는 다음 거래일 종가라 이 금액과 다릅니다.'
        )

    # 🔴 2-4-5 — "크롤링이 실패하면 이 주문은 체결되지 않고 취소됩니다"를 **주문 전에**
    #    크고 명확하게, 체크 확인 영역에 포함해서 고지합니다(사후 통보로 끝내지 않기).
    warning_banner(NOTICE_CRAWL_FAILURE)
    confirm_box = ui.checkbox('위 안내(수집 실패·휴장일이면 주문이 취소됨)를 확인했습니다.')

    message = ui.label('').classes('text-red-400 text-base whitespace-pre-line')

    def _submit() -> None:
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
            order = save_order(
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
        ui.notify(
            f'✅ 주문을 저장했습니다 — {stock_name} ({ticker}) {quantity:,}주\n'
            f'체결 예정일: {order.get("target_date")} 종가 (지금 체결된 것이 아닙니다)\n'
            f'{ORDER_WINDOW_TEXT} 안에서는 수량 수정·취소가 가능합니다.',
            type='positive', multi_line=True, close_button='닫기',
            classes='text-lg whitespace-pre-line',
        )
        on_changed()

    ui.button('🛒 주문 저장 (매수)', on_click=_submit).props('no-caps color=primary')
    ui.label(
        '※ 저장 시점에는 예수금이 충분한지 확정할 수 없습니다 — 체결가(다음 거래일 종가)를 '
        '아직 모르기 때문입니다. 체결 시점에 모자라면 살 수 있는 만큼만 체결되고 사유가 남습니다.'
    ).classes('vh-muted')


# =============================================================================
# 8. 주문 내역 (대기 중 주문 수정·취소 + 최근 결과)
# =============================================================================
def _render_orders_section(client, user_id: str, accounts, window: dict, on_changed) -> None:
    ui.markdown('#### 📋 내 주문')
    if not window["is_open"]:
        info_banner(
            '지금은 접수 시간이 아니라 주문 수량 수정·취소 버튼이 보이지 않습니다. '
            f'다음 접수 시간({ORDER_WINDOW_TEXT})에 다시 열립니다.'
        )
    for account in accounts:
        _render_account_orders(client, user_id, account, window, on_changed)


def _render_account_orders(client, user_id: str, account: dict, window: dict, on_changed) -> None:
    """계좌 1개의 주문 목록 — 대기 중 주문(수정·취소 가능) + 최근 결과.

    🔒 소유자 확인은 카드와 같은 이유로 여기서도 한 번 더 합니다(§0-3-8).
    """
    if account.get("user_id") != user_id:
        error_banner('🚫 소유자가 확인되지 않는 계좌라 주문을 표시하지 않았습니다.')
        return

    account_id = account.get("id")
    title = WINDOW_TITLES.get(account.get("window_type"), str(account.get("window_type")))
    with ui.card().classes('vh-card w-full'):
        ui.markdown(f'**{esc(title)}**')
        try:
            orders = fetch_my_orders(client, account_id)
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "주문 내역을 불러오지 못했습니다.")}')
            return

        pending = [o for o in orders if o.get("status") == ORDER_PENDING]
        if pending:
            ui.label(f'⏳ 체결 대기 중인 주문 {len(pending)}건').classes('vh-muted')
            for order in pending:
                _render_pending_order_row(client, order, window, on_changed)
        else:
            ui.label('체결 대기 중인 주문이 없습니다.').classes('vh-muted')

        history = [o for o in orders if o.get("status") != ORDER_PENDING][:RECENT_ORDER_LIMIT]
        if history:
            _render_order_history_table(history)


def _render_pending_order_row(client, order: dict, window: dict, on_changed) -> None:
    """대기 주문 한 줄 — 수량 수정 · 취소.

    수정·취소가 가능한 시간대인지는 화면에서도 확인하지만, **최종 권한은 서버**입니다
    (`utils/duel_db.py` 의 시간대 판정 + DB 트리거). 화면은 버튼을 감추는 것까지만 합니다.
    """
    order_id = order.get("id")
    label = (f'{order.get("stock_name") or ""} ({order.get("ticker")}) · '
             f'{order.get("requested_quantity")}주 · 체결 예정일 {order.get("target_date")}')

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.label(label).classes('flex-1 min-w-0 vh-keep-all')
        if not window["is_open"]:
            return

        quantity_input = ui.input(value=str(order.get("requested_quantity") or '')) \
            .props('dense').style('flex: 0 0 90px;').tooltip('바꿀 수량(주)')

        def _save(_=None) -> None:
            try:
                quantity = _parse_positive_int(quantity_input.value, '수량')
            except ValueError as exc:
                ui.notify(f'🚫 {exc}', type='negative', multi_line=True, close_button='닫기')
                return
            try:
                edit_order(client, order_id, quantity)
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

        def _cancel(_=None) -> None:
            try:
                cancel_order(client, order_id)
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
    """최근 주문 결과 표. 체결가·체결금액·사유를 **전부** 보여줍니다(§0-1 — 조용한 실패 금지)."""
    headers = ['종목', '상태', '체결일', '체결가', '체결금액', '사유']
    body_rows = []
    for order in orders:
        name = order.get("stock_name") or order.get("ticker")
        body_rows.append([
            (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
             f'{esc(str(name))}<br>({esc(str(order.get("ticker")))})</div>'),
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
