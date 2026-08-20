# utils/duel_rules.py
"""
⚔️ "결투다!" (모의투자 대결 · 4번째 모듈) — **순수 규칙 계산 계층**

DUEL_MODULE_WORK_ORDER.md 2단계의 파일 계획에 따라 만든 모듈입니다. 이 파일에는
**계산 규칙만** 있습니다. Supabase 접근(`utils/duel_db.py`), 화면(`web/pages/duel_page.py`),
야간 배치(`.github/workflows/duel_daily.yml`)는 전부 별도 파일이고, 그쪽에서 이 모듈을
호출합니다.

-------------------------------------------------------------------------------
🔌 이 파일이 의존하지 않는 것 (그리고 앞으로도 의존하면 안 되는 것)
-------------------------------------------------------------------------------
표준 라이브러리 말고는 **아무것도 import 하지 않습니다.** Supabase 클라이언트도, requests
도, NiceGUI 도, 이 저장소의 다른 모듈도 없습니다. 파일을 여는 코드조차 없고, 필요한 값
(종가·거래일 목록·스냅샷 목록)은 전부 **인자로 받습니다.**

왜 이렇게까지 하나:
  · 작업지시서 4단계는 체결 계산·가용 현금·TWR·크롤링 신선도를 **네트워크와 Supabase
    없이** 검증하라고 요구합니다(`tests/test_duel.py`). 의존이 하나라도 있으면 그 시점에
    오프라인 테스트가 깨집니다.
  · `utils/report_db.py` 가 A·B 절(순수 계산)과 D 절(Supabase I/O)을 갈라 둔 것과 같은
    이유이고, `utils/scorecard_ocr.py` 가 저장소 의존을 갖지 않는 것과 같은 규율입니다.

-------------------------------------------------------------------------------
⚠️ 지어내지 않기 (ENGINEERING_SPEC §0-1) — 이 파일의 모든 함수가 지키는 규칙
-------------------------------------------------------------------------------
**입력이 없거나 이상하면 숫자를 만들어 돌려주지 않습니다.** 이 파일의 어떤 함수도
"값을 모를 때 0(또는 이전 값, 또는 평균)을 대신 넣는" 경로를 갖고 있지 않습니다. 대신
  · 계산이 불가능하면 `DuelRuleError` 를 던지거나,
  · 상태를 함께 돌려주는 함수는 `status`(예: `"NO_DATA"`)와 `None` 값을 돌려줍니다.
호출부는 그걸 받아 화면에 "데이터 없음"으로 **정직하게** 표시합니다.

특히 조심할 지점 세 가지:
  1. **종가를 모르면 체결하지 않습니다.** `calculate_fill()` 은 종가가 없거나 0 이하면
     예외를 던집니다. "일단 어제 종가로" 같은 폴백은 §0-3-1 위반이고, 사용자가 이미 아는
     가격으로 체결하는 부정이 됩니다.
  2. **거래일 캘린더를 이 파일이 만들지 않습니다.** `resolve_fill_trading_day()` 는 확정된
     거래일 목록을 **인자로 받습니다.** 공휴일을 하드코딩하면 매년 틀립니다
     (`report_db.period_bounds()` 가 같은 이유로 달력 기준만 계산하는 것과 같은 판단).
  3. **스냅샷의 `cash_flow_amount` 가 비어 있으면 TWR 을 계산하지 않습니다.** 0 으로
     기본값을 주면 "그날 늘어난 돈이 수익인지 입금인지"를 조용히 잘못 판정하게 되고,
     그게 바로 이 모듈이 단순 수익률을 버리고 TWR 을 쓰는 이유였습니다(2-6).

-------------------------------------------------------------------------------
🧮 이 파일이 구현하는 규칙과 작업지시서 대응
-------------------------------------------------------------------------------
  · 2-2  정기 입금액·시드 상수 (금액의 단일 출처)
  · 2-3  매수 창 개폐              → `is_buy_window_open()`
  · 2-4  주문 접수 시간대           → `resolve_order_window()`
  · 2-4  D+1 체결 거래일 확정        → `resolve_fill_trading_day()`
  · 2-4  부분체결 계산              → `calculate_fill()`
  · 2-4  FIFO 예수금 배정           → `allocate_pending_orders()`
  · 2-4  가중평균 평단가 갱신        → `apply_buy_fill_to_position()`
  · 2-6  누적 TWR                  → `compute_twr()`
  · 2-9  크롤링 신선도 판정          → `check_crawl_freshness()`

  ── 2026-08-20 추가: 5단계(Branch 2 "내 밑으로 눈 깔어" 공개 순위표) — 아래 §10 ──
  · 5-3  원금 구간(체급) 8개 경계값    → `BRACKET_TIERS` / `assign_bracket()`
  · 5-3  체급 시즌 고정(1년)          → `season_key_for_date()` / `resolve_bracket_for_season()`
  · 5-5  무작위 닉네임                → `generate_nickname()`
  · 5-4  순위 계산(동점 처리 포함)      → `rank_participants()`
  · 5-6  최소 참가 인원(500명)         → `MIN_PARTICIPANTS_FOR_PUBLICATION`
  · 5-8  철회 후 3개월 재동의 차단      → `resolve_reconsent_block()`
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal


class DuelRuleError(RuntimeError):
    """
    결투 규칙 계산에서 사용자/로그에 그대로 보여줄 오류.

    `utils/report_db.py::ReportError` · `utils/scorecard_db.py::ScorecardError` 와 같은
    역할입니다 — 조용히 삼키지 않고, 실패 사실이 화면까지 도달하게 합니다(§0-1).
    """


# =============================================================================
# 0. 규칙 상수 — 숫자의 단일 출처 (§0-3-10)
# =============================================================================
#  ⚠️ 아래 금액·시각을 **다른 파일에 다시 적지 마세요.** SQL 스키마에도 일부러 넣지
#     않았습니다(`sql/duel_schema.sql` §1 의 seed_amount 주석 참고) — 두 곳에 적으면 둘 중
#     하나만 바뀌는 날 조용히 어긋납니다. 화면 문구도 이 상수를 포맷해서 만드세요.

#: 계좌 개설 시 지급하는 가상 시드머니(원). v1 에서 사용자가 바꿀 수 없습니다(2-1-3).
SEED_AMOUNT_KRW = 10_000_000

#: 매월 정기 입금액(원). 창 길이에 비례해 깎지 않습니다 — M6 도 M1 과 똑같이 80만원(2-2-1).
MONTHLY_DEPOSIT_KRW = 800_000

#: 정기 입금일(매월 며칠). 주말·공휴일이어도 그대로 이 날짜입니다 — 시장 이벤트가 아니라
#: 현금 이벤트이기 때문입니다(2-2-4).
MONTHLY_DEPOSIT_DAY = 10

#: 사용자당 개설되는 계좌 유형. 세 계좌는 **매매 규칙이 완전히 동일**하며(2-3), 차별화는
#: 사용자가 각 계좌에서 어떤 종목을 사는지에서 나옵니다. 규칙 레벨의 인위적 차별화를
#: 추가하지 마세요.
ACCOUNT_WINDOW_TYPES = ("M1", "M3", "M6")

#: 한국시간. 이 모듈의 모든 시각 판정 기준입니다(DB 의 UTC 를 쓰지 않는 이유는
#: `sql/scorecard_schema.sql` §8 주석과 같습니다).
KST = timezone(timedelta(hours=9), name="KST")

#: 주문 접수 시간대(2-4-1) — D일 18:00:01 ~ 22:00:00, **양끝 포함**.
#: 코스피 크롤링(평일 KST 16:05)이 끝나고 데이터가 안정된 뒤부터 받습니다.
ORDER_WINDOW_OPEN_TIME = time(18, 0, 1)
ORDER_WINDOW_CLOSE_TIME = time(22, 0, 0)

# ── 주문 상태 (sql/duel_schema.sql duel_orders.status 의 CHECK 와 같은 문자열) ──────────
ORDER_PENDING = "pending"
ORDER_FILLED = "filled"
ORDER_PARTIALLY_FILLED = "partially_filled"
ORDER_CANCELLED = "cancelled"
ORDER_EXPIRED = "expired"

# ── 크롤링 신선도 판정 결과 (2-9) ──────────────────────────────────────────────────────
#: 그날 값이 믿을 만함 → 체결 진행.
CRAWL_OK = "ok"
#: 수집 실패로 확정 → 그날 귀속 주문은 전부 실패 처리(2-4-5). 이월하지 않습니다.
CRAWL_FAILED = "failed"
#: 52개 전부 무변동 — 수집 실패이거나 휴장일. **둘을 구분하지 않습니다**(2-9-1). 어느
#: 쪽이든 "이 날짜엔 신뢰할 수 있는 새 종가가 없다"는 같은 결론이라 처리도 같습니다.
#: 구분해서 돌려주는 이유는 오직 관리자 로그의 가독성입니다 — 자동 판정은 FAILED 와 동일.
CRAWL_FAILED_OR_HOLIDAY = "failed_or_holiday"
#: 무변동 종목이 허용치를 넘음 → 자동으로 실패를 확정하지 않고 **관리자 확인**(2-9-4).
CRAWL_NEEDS_REVIEW = "needs_review"

#: 신선도 점검 대상 지수 2개. 기본값이며, 다른 모듈이 재사용할 때 바꿀 수 있게
#: 키워드 인자로도 받습니다(§0-3-10 — 이 함수는 결투 전용이 아니라 일반적으로 짭니다).
CRAWL_INDEX_KEYS = ("KOSPI", "KOSDAQ")
#: 점검 대상 종목 수(코스피 시가총액 상위 50).
CRAWL_STOCK_COUNT = 50
#: 무변동이어도 정상으로 보는 종목 수의 상한. 유동성이 낮은 날엔 실제로 종가가 안 움직이는
#: 종목이 있을 수 있습니다(2-9-4).
CRAWL_UNCHANGED_TOLERANCE = 10

# ── TWR 계산 상태 (report_db 의 STATUS_* 관례와 같은 방식) ─────────────────────────────
TWR_OK = "OK"
#: 스냅샷이 하나도 없음.
TWR_NO_DATA = "NO_DATA"
#: 개설일(0일차) 스냅샷 하나뿐이라 아직 **구간 수익률이 하나도 없음**. 0% 가 아닙니다.
TWR_INSUFFICIENT = "INSUFFICIENT"


# =============================================================================
# 1. 내부 검증·포맷 헬퍼 — "모르는 값을 숫자로 바꾸지 않는" 관문
# =============================================================================
def _round6(value):
    """
    소수점 6자리 반올림 — DB 의 금액 컬럼이 전부 `numeric(20, 6)` 이라 **여기서 반올림한
    값이 곧 저장되는 값**입니다. `utils/report_db.py::_round6()` 와 같은 함수이며, 같은
    이유로 둡니다(파이썬이 보는 값과 DB 에 들어가는 값이 달라질 여지를 없애기).
    """
    return round(float(value), 6)


def _require_number(value, label, *, allow_negative=False, allow_zero=True):
    """
    숫자여야 하는 입력을 검증해 float 로 돌려줍니다. **없으면 0 으로 메우지 않고 예외**입니다.

    bool 을 거절하는 이유: 파이썬에서 `True == 1` 이라 `quantity=True` 같은 실수가 조용히
    "1주"로 통과합니다. 금액·수량 계산에 bool 이 들어오는 정상 경로는 없습니다.
    """
    if value is None or isinstance(value, bool):
        raise DuelRuleError(f"{label}이(가) 없습니다(비어 있는 값을 0 으로 대체하지 않습니다): {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DuelRuleError(f"{label}이(가) 숫자가 아닙니다: {value!r}") from None
    if not math.isfinite(number):
        raise DuelRuleError(f"{label}이(가) 유효한 숫자가 아닙니다: {value!r}")
    if not allow_negative and number < 0:
        raise DuelRuleError(f"{label}은(는) 0 이상이어야 합니다: {number}")
    if not allow_zero and number == 0:
        raise DuelRuleError(f"{label}은(는) 0 보다 커야 합니다: {number}")
    return number


def _require_int(value, label, *, minimum=None):
    """정수여야 하는 입력(주식 수)을 검증합니다. 소수 주식은 v1 체결 경로에 없습니다."""
    if value is None or isinstance(value, bool):
        raise DuelRuleError(f"{label}이(가) 없습니다: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise DuelRuleError(f"{label}이(가) 정수가 아닙니다: {value!r}") from None
    if float(value) != number:
        raise DuelRuleError(f"{label}은(는) 정수여야 합니다(v1 체결은 정수 주식만): {value!r}")
    if minimum is not None and number < minimum:
        raise DuelRuleError(f"{label}은(는) {minimum} 이상이어야 합니다: {number}")
    return number


def _to_date(value, label="날짜"):
    """'YYYY-MM-DD' / date / datetime → date. 모르는 값은 지어내지 않고 예외입니다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise DuelRuleError(f"{label}이(가) 비어 있습니다.")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise DuelRuleError(f"{label} 형식을 알 수 없습니다: {value!r}") from None


def _to_kst(value, label="시각"):
    """
    datetime / ISO 문자열 → **한국시간(KST) 기준 aware datetime**.

    타임존이 없는 값(naive)은 **KST 로 간주**합니다. 이 모듈에 들어오는 시각은 전부 화면과
    원장이 KST 로 다루는 값이고(작업지시서 전체가 KST 기준), 여기서 UTC 로 가정하면 주문
    접수 시간대 판정이 9시간 어긋납니다. 이 해석을 바꾸려면 **이 한 곳만** 고치면 됩니다.
    """
    if value is None:
        raise DuelRuleError(f"{label}이(가) 없습니다.")
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise DuelRuleError(f"{label}이(가) 비어 있습니다.")
        # Supabase 는 '...+00:00' 또는 '...Z' 로 돌려줍니다. 파이썬 3.11 은 Z 도 파싱하지만
        # 구버전 호환을 위해 명시적으로 바꿔 둡니다.
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise DuelRuleError(f"{label} 형식을 알 수 없습니다: {value!r}") from None
    else:
        raise DuelRuleError(f"{label}이(가) 시각이 아닙니다: {value!r}")

    if moment.tzinfo is None:
        return moment.replace(tzinfo=KST)
    return moment.astimezone(KST)


def _fmt_money(value):
    """금액을 사람이 읽는 문자열로(천 단위 콤마, 불필요한 소수점 0 제거). 문구 전용입니다."""
    text = f"{float(value):,.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


# =============================================================================
# 2. 매수 창 개폐 — work order 2-3
# =============================================================================
def is_buy_window_open(available_cash):
    """
    매수 창이 열려 있는지. work order 2-3 참고.

    창 길이는 **사실상 무제한**으로 확정됐습니다(오너 결정). "예수금이 있으면 언제든 매수
    가능, 0 이 되면 다음 입금 전까지 매수 불가"가 이 모듈의 유일한 규칙이라, 판정은 결국
    `가용 현금 > 0` 하나로 줄어듭니다.

    그런데도 함수로 남겨 둔 이유는 작업지시서가 직접 밝힌 것과 같습니다 — 규칙이 나중에
    복잡해지면(예: 창 기간 재도입, 계좌 상태 조건) **고칠 곳이 여기 한 군데**가 됩니다.
    호출부에 `if cash > 0:` 을 흩뿌려 두면 그때 전부 찾아다녀야 합니다(§0-3-10).

    ⚠️ 예수금 값이 없으면 "닫힘"으로 조용히 처리하지 않고 예외를 던집니다 — "잔고를 모르는
       상태"와 "잔고가 0 인 상태"는 다른 말이고, 전자를 후자로 바꿔 표시하면 §0-1 위반입니다.
    """
    cash = _require_number(available_cash, "가용 예수금", allow_negative=True)
    return cash > 0


# =============================================================================
# 3. 주문 접수 시간대 — work order 2-4-1
# =============================================================================
def resolve_order_window(now_kst):
    """
    지금이 주문 접수 시간대(D일 18:00:01 ~ 22:00:00, 양끝 포함)인지 판정합니다.
    work order 2-4-1 참고.

    돌려주는 dict
        is_open           : 지금 주문/수정/취소를 받을 수 있는가
        now_kst           : 판정에 쓴 KST 시각(호출부가 그대로 화면에 쓸 수 있게)
        submission_date   : 이 주문이 **접수되는 날(D)**. 지금 창이 닫혀 있으면
                            "다음에 열리는 창의 날짜"입니다.
        window_opens_at   : 그 창이 열리는 시각(KST)
        window_closes_at  : 그 창이 닫히는 시각(KST)

    경계 처리 (테스트로 고정합니다)
        17:59:59 → 닫힘, 오늘 18:00:01 로 안내
        18:00:00 → 닫힘 (창은 18:00:01 부터입니다)
        18:00:01 → 열림
        22:00:00 → 열림 (양끝 포함)
        22:00:01 → 닫힘, **다음 날** 18:00:01 로 안내

    ⚠️ 창이 닫힌 뒤의 `submission_date` 는 **달력상 다음 날**입니다. 작업지시서 문구는
       "다음 영업일"이지만, 이 함수는 거래일 캘린더를 갖고 있지 않고 만들지도 않습니다
       (§0-1). "그 접수일의 주문이 실제로 어느 거래일에 체결되는가"는 확정 거래일 목록을
       인자로 받는 `resolve_fill_trading_day()` 가 따로 답합니다. 화면 안내 문구를 만들 때
       이 둘을 헷갈리지 마세요.
    """
    moment = _to_kst(now_kst, "현재 시각")
    today = moment.date()
    clock = moment.timetz().replace(tzinfo=None)

    if clock < ORDER_WINDOW_OPEN_TIME:
        is_open, submission_date = False, today
    elif clock <= ORDER_WINDOW_CLOSE_TIME:
        is_open, submission_date = True, today
    else:
        is_open, submission_date = False, today + timedelta(days=1)

    return {
        "is_open": is_open,
        "now_kst": moment,
        "submission_date": submission_date,
        "window_opens_at": datetime.combine(submission_date, ORDER_WINDOW_OPEN_TIME, tzinfo=KST),
        "window_closes_at": datetime.combine(submission_date, ORDER_WINDOW_CLOSE_TIME, tzinfo=KST),
    }


# =============================================================================
# 4. 체결 거래일(D+1) 확정 — work order 2-4
# =============================================================================
def resolve_fill_trading_day(saved_at_kst, trading_days):
    """
    접수 시간대에 저장된 주문이 **어느 거래일 종가로 체결되는지** 돌려줍니다.
    work order 2-4 참고("체결은 D 종가가 아니라 D+1 종가").

    왜 D 가 아니라 D+1 인가: 접수 시간대(18:00:01~22:00:00)는 그날 크롤링이 이미 끝난 뒤라
    **D 종가는 사용자가 이미 아는 값**입니다. 그 값으로 체결하면 "이미 알려진 정보로 매매"가
    되어 대결의 공정성이 무너집니다(§0-3-1).

    인자
        saved_at_kst : 주문 저장 시각(또는 날짜). KST 기준.
        trading_days : **호출부가 확정한** 거래일 목록/집합(date 또는 'YYYY-MM-DD').

    ⚠️ 거래일 캘린더를 이 함수가 갖지 않는 것이 핵심입니다. 공휴일을 코드에 박으면 매년
       틀리고, 이 저장소에 이미 있는 "실제로 수집이 성공한 날" 기록과 **두 번째 캘린더**가
       생깁니다(§0-1 / §0-3-10 — 작업지시서가 명시적으로 금지). 그래서 확정 거래일을
       인자로 받고, 목록에 근거가 없으면 **날짜를 만들어내지 않고 예외**를 던집니다.

    반환: D 이후(D 자신은 제외) 가장 이른 확정 거래일(date).
    """
    saved_date = _to_date(saved_at_kst, "주문 저장 시각")

    if trading_days is None:
        raise DuelRuleError("확정 거래일 목록이 없습니다(거래일을 지어내지 않습니다).")
    days = {_to_date(day, "거래일") for day in trading_days}
    if not days:
        raise DuelRuleError("확정 거래일 목록이 비어 있어 체결 거래일을 정할 수 없습니다.")

    later = [day for day in days if day > saved_date]
    if not later:
        raise DuelRuleError(
            f"{saved_date.isoformat()} 이후의 확정 거래일이 목록에 없어 체결 거래일을 정할 수 없습니다"
            " — 다음 거래일이 확정될 때까지 기다려야 하며, 임의로 다음 날짜를 만들지 않습니다(§0-1)."
        )
    return min(later)


# =============================================================================
# 5. 체결 수량 계산(부분체결 포함) — work order 1-3 / 2-4-6
# =============================================================================
def calculate_fill(requested_quantity, close_price, available_cash):
    """
    주문 1건의 부분체결 계산. work order 2-4-6 참고.

    규칙(오너 확정)
      · `requested_quantity × 종가` ≤ 가용 현금  → **전량 체결**(`filled`)
      · 초과하면 주문 전체를 취소하지 않고 `floor(가용현금 / 종가)` 만큼 **부분체결**
        (`partially_filled`) 하고, `fail_reason` 에 요청/실제 수량을 사람이 읽을 문장으로 남깁니다.
      · 1주도 못 사면 `expired` + 사유 문구. 잔돈은 현금으로 남습니다.

    ⚠️ **종가가 없으면 계산 자체를 하지 않습니다**(예외). 이 회귀 방어가 이 함수에서 가장
       중요합니다 — 작업지시서 4단계가 "그날 확정 종가가 없는 상태에서 체결 함수를 호출하면
       절대 체결되지 않고 명확한 실패를 내는지"를 회귀 테스트로 고정하라고 요구합니다
       (§0-1 / §0-3-1). 나중에 누가 "일단 전일 종가라도" 를 넣으면 여기서 잡힙니다.

    ⚠️ 살 수 있는 주식 수는 **Decimal 로 나눠서** 내림합니다. float 로 하면 예를 들어
       가용 3.0 · 단가 1.0 이 2.9999999... 로 떨어지는 순간 **살 수 있는 주식이 한 주
       줄어듭니다.** 정수 주식 수가 2진 반올림 부스러기로 뒤집히면 안 됩니다
       (`report_db._sum_money()` 가 십진수로 더하는 것과 같은 규율).

    반환 dict
        status          : 'filled' / 'partially_filled' / 'expired'
        filled_quantity : 실제 체결 주식 수(정수)
        filled_amount   : 체결금액 = 체결수량 × 종가
        remaining_cash  : 체결 후 남는 현금(잔돈)
        fail_reason     : 전량체결이면 None, 아니면 사람이 읽을 사유 문장
    """
    requested = _require_int(requested_quantity, "주문 수량", minimum=1)
    price = _require_number(close_price, "체결 종가(확정 종가)", allow_zero=False)
    cash = _require_number(available_cash, "가용 예수금")

    affordable = int(Decimal(str(cash)) // Decimal(str(price)))
    filled = min(requested, affordable)
    amount = _round6(filled * price)
    remaining = _round6(cash - amount)

    if filled == requested:
        status, reason = ORDER_FILLED, None
    elif filled > 0:
        status = ORDER_PARTIALLY_FILLED
        reason = (
            f"요청 {requested}주 중 {filled}주만 예수금 부족으로 체결되었습니다"
            f" (체결가 {_fmt_money(price)}원, 가용 예수금 {_fmt_money(cash)}원)."
        )
    else:
        status = ORDER_EXPIRED
        reason = (
            f"예수금 {_fmt_money(cash)}원으로는 1주({_fmt_money(price)}원)도 살 수 없어"
            f" 요청 {requested}주가 체결되지 않았습니다."
        )

    return {
        "status": status,
        "filled_quantity": filled,
        "filled_amount": amount,
        "remaining_cash": remaining,
        "fail_reason": reason,
    }


# =============================================================================
# 6. 같은 계좌의 pending 주문 여러 건 — FIFO 예수금 배정 (work order 2-4-6)
# =============================================================================
def allocate_pending_orders(available_cash, pending_orders, close_prices):
    """
    한 계좌의 `pending` 주문들에 예수금을 **`saved_at` 빠른 순서대로** 배정합니다.
    work order 2-4-6 참고.

    왜 순서가 중요한가: 같은 계좌에 주문이 여러 건 있으면 **뒤 주문이 앞 주문 몫까지
    넘보면 안 됩니다.** 앞 주문부터 하나씩 체결하며 가용 현금을 깎아 나가고, 그 결과
    뒤 주문은 남은 돈으로만 판정됩니다. 작업지시서 4단계가 이걸 **회귀 테스트로 고정**하라고
    지목한 항목입니다.

    인자
        available_cash : 체결 시작 시점의 예수금(원장 합계).
        pending_orders : dict 목록. 최소 `saved_at` · `ticker` · `requested_quantity` 필요.
                         `id` 가 있으면 결과에 그대로 실어 돌려줍니다.
        close_prices   : {ticker: 그 거래일 확정 종가}. **없는 종목은 체결하지 않습니다.**

    같은 `saved_at` 이 여럿이면 **입력 순서를 유지**합니다(안정 정렬). 초 단위까지 같은
    주문이 실제로 생길 수 있고, 그때 순서를 난수처럼 바꾸면 같은 입력에 다른 결과가
    나옵니다 — 배치를 두 번 돌렸을 때 결과가 달라지면 안 됩니다.

    ⚠️ 종가를 모르는 종목의 주문은 **취소(`cancelled`)** 로 돌려주고 현금을 건드리지
       않습니다. 작업지시서 2-4-5 가 정한 처리(이월하지 않고 사유를 남겨 실패 확정)이며,
       "0원으로 체결"이나 "전일 종가로 체결" 같은 대체는 하지 않습니다(§0-1).

    반환: 처리 순서(= saved_at 순)대로의 결과 dict 목록.
          각 항목: order / id / ticker / saved_at / status / filled_quantity /
                   filled_amount / fail_reason / cash_before / cash_after
    """
    cash = _require_number(available_cash, "가용 예수금")
    orders = list(pending_orders or [])
    if not orders:
        # 주문이 없는 것은 오류가 아닙니다(정상적으로 흔한 상태). 빈 결과를 돌려줍니다.
        return []
    if close_prices is None:
        raise DuelRuleError("확정 종가 표가 없습니다(종가 없이 체결하지 않습니다).")

    # 안정 정렬: 같은 saved_at 이면 입력 순서 유지.
    prepared = []
    for index, raw in enumerate(orders):
        if not isinstance(raw, dict):
            raise DuelRuleError(f"주문 항목이 dict 가 아닙니다: {raw!r}")
        prepared.append((_to_kst(raw.get("saved_at"), "주문 저장 시각"), index, raw))
    prepared.sort(key=lambda item: (item[0], item[1]))

    results = []
    for saved_at, _index, raw in prepared:
        ticker = str(raw.get("ticker") or "").strip()
        if not ticker:
            raise DuelRuleError(f"주문에 종목코드가 없습니다: {raw!r}")
        requested = _require_int(raw.get("requested_quantity"), "주문 수량", minimum=1)

        cash_before = cash
        price = close_prices.get(ticker)
        if price is None:
            outcome = {
                "status": ORDER_CANCELLED,
                "filled_quantity": 0,
                "filled_amount": 0.0,
                "remaining_cash": cash,
                "fail_reason": (
                    f"{ticker}의 확정 종가를 확보하지 못해 체결하지 않고 취소했습니다"
                    " — 모르는 가격으로 체결하거나 다음 날로 이월하지 않습니다(작업지시서 2-4-5)."
                ),
            }
        else:
            outcome = calculate_fill(requested, price, cash)
            cash = outcome["remaining_cash"]

        results.append({
            "order": raw,
            "id": raw.get("id"),
            "ticker": ticker,
            "saved_at": saved_at,
            "requested_quantity": requested,
            "status": outcome["status"],
            "filled_quantity": outcome["filled_quantity"],
            "filled_amount": outcome["filled_amount"],
            "fill_price": None if price is None else _round6(price),
            "fail_reason": outcome["fail_reason"],
            "cash_before": _round6(cash_before),
            "cash_after": _round6(cash),
        })

    return results


# =============================================================================
# 7. 가중평균 평단가 갱신 — work order 2-4-6 (`holdings` 와 동일 규칙)
# =============================================================================
def apply_buy_fill_to_position(existing_quantity, existing_avg_cost,
                               filled_quantity, fill_price):
    """
    매수 체결 1건을 기존 포지션에 반영해 **수량 가중평균 평단가**를 다시 계산합니다.
    work order 2-4-6 참고 — `holdings` 와 **같은 규칙**입니다.

        new_avg = (기존수량 × 기존평단 + 체결수량 × 체결가) / (기존수량 + 체결수량)

    계산 방식은 `utils/scorecard_db.py::weighted_average_price()` 를 그대로 따릅니다
    (float 로 가중평균을 내고, **저장 직전 소수점 6자리로 한 번만** 반올림 —
    `utils/report_db.py::_round6()` 와 같은 자리). 여기서 다른 방식을 발명하면 "내 성적표"의
    평단가와 결투 계좌의 평단가가 서로 다른 규칙으로 계산되기 시작합니다(§0-3-10).

    ⚠️ `total_cost` 는 새 평단가에서 되돌려 계산하지 않고 **실제로 쓴 돈을 더해서** 만듭니다.
       반올림된 평단가 × 수량으로 되돌리면 원가가 미세하게 어긋나고, 그 차이가 스냅샷의
       total_cost 로 흘러갑니다.

    ⚠️ 매도는 없습니다. `filled_quantity` 는 항상 1 이상이어야 하고, 음수·0 은 예외입니다 —
       애플리케이션 경로로 수량을 줄이는 시도를 여기서 막습니다(DB 레벨 방어는
       `sql/duel_schema.sql` §2-1 의 트리거).

    신규 포지션이면 `existing_quantity` 와 `existing_avg_cost` 를 **둘 다** None 으로 주세요.
    한쪽만 None 이면 "수량은 아는데 평단가는 모르는" 복원 불가 상태라 예외입니다.
    """
    if existing_quantity is None and existing_avg_cost is None:
        prev_qty, prev_avg = 0.0, 0.0
    elif existing_quantity is None or existing_avg_cost is None:
        raise DuelRuleError(
            "기존 수량과 기존 평단가는 함께 주어져야 합니다"
            f" (수량={existing_quantity!r}, 평단가={existing_avg_cost!r})."
        )
    else:
        prev_qty = _require_number(existing_quantity, "기존 보유 수량")
        prev_avg = _require_number(existing_avg_cost, "기존 평균 매입단가")

    filled = _require_int(filled_quantity, "체결 수량", minimum=1)
    price = _require_number(fill_price, "체결가", allow_zero=False)

    new_qty = prev_qty + filled
    if new_qty <= 0:
        raise DuelRuleError("총수량이 0 이하라 평단가를 계산할 수 없습니다.")

    total_cost = prev_qty * prev_avg + filled * price
    return {
        "quantity": _round6(new_qty),
        "avg_cost": _round6(total_cost / new_qty),
        "total_cost": _round6(total_cost),
    }


# =============================================================================
# 8. 크롤링 신선도 판정 — work order 2-9
# =============================================================================
def check_crawl_freshness(today_prices, yesterday_prices, *,
                          index_keys=CRAWL_INDEX_KEYS,
                          expected_stock_count=CRAWL_STOCK_COUNT,
                          unchanged_tolerance=CRAWL_UNCHANGED_TOLERANCE):
    """
    "오늘 수집한 종가를 믿어도 되는가"를 전일 대비 무변동 검사로 판정합니다.
    work order 2-9 참고.

    이 모듈이 생기기 전까지 수집 실패는 "화면 숫자가 하루 낡는" 문제였지만, 이제는
    **사용자의 주문이 체결되느냐 마느냐**를 직접 좌우합니다. 그래서 별도의 가벼운 점검을
    둡니다. 일별 이력을 쌓지 않고 **그날 값이 전일 대비 변했는지만** 순수하게 검사합니다.

    점검 대상 52개 = 지수 2개(`index_keys`) + 코스피 시가총액 상위 50종목.

    ── 판정 순서 (오너 설계 규칙 1~4를 실제로 구현 가능하게 정리한 것) ────────────────
    작업지시서의 규칙 2("지수가 변했는데 종목 일부가 무변동 → 실패")와 규칙 4("50종목 중
    최대 10개까지는 무변동이어도 정상")는 **문자 그대로 읽으면 서로 겹칩니다** — 규칙 2를
    먼저 적용하면 무변동 종목이 1개만 있어도 실패가 되어 규칙 4의 허용치가 영원히 죽습니다.
    그래서 작업지시서 4번이 "허용 오차"라고 명시한 대로 **규칙 4의 허용치를 우선**시키고,
    규칙 2는 그 허용치를 넘어서는 극단(지수는 움직였는데 50종목이 통째로 멈춤)에 남겼습니다.
    이 해석은 오너 확인이 필요한 지점이라 여기 명시해 둡니다.

        ① 지수 2개 전부 무변동 + 50종목 전부 무변동  → 'failed_or_holiday'
           (수집 실패인지 휴장일인지 구분하지 않습니다 — 어느 쪽이든 그날 체결은 없습니다)
        ② 지수 2개 전부 무변동 + 종목은 일부/전부 움직임 → 'failed'
           (지수는 종목 움직임을 반영해야 하므로 앞뒤가 안 맞는 상태 — 규칙 3)
        ③ 지수 중 하나 이상 변동 + 50종목 전부 무변동 → 'failed' (규칙 2의 극단)
        ④ 지수 중 하나 이상 변동 + 무변동 종목 ≤ 허용치(10) → 'ok'
        ⑤ 지수 중 하나 이상 변동 + 무변동 종목 11~49 → 'needs_review'
           (자동으로 실패를 확정하지 않고 관리자가 한 번 봅니다 — 규칙 4)

    ⚠️ **값이 하나라도 없으면 판정하지 않고 예외**입니다. "없는 값 = 무변동"으로 세면 수집
       실패를 정상으로 넘겨 버릴 수 있습니다(§0-1). 두 dict 의 키 집합도 정확히 같아야 합니다.

    ⚠️ 값 비교는 Decimal 로 합니다. 종가는 십진수로 들어오므로 float 비교에서 생기는
       "같은 값인데 다르다" 를 애초에 없앱니다.

    다른 모듈에서도 "오늘 데이터가 신선한가"를 묻는 데 쓸 수 있게 대상 키와 임계값을 전부
    키워드 인자로 열어 뒀습니다(§0-3-10).
    """
    if not isinstance(today_prices, dict) or not isinstance(yesterday_prices, dict):
        raise DuelRuleError("오늘/전일 종가는 dict 로 주어져야 합니다.")
    if not today_prices or not yesterday_prices:
        raise DuelRuleError("종가 표가 비어 있어 신선도를 판정할 수 없습니다(§0-1 — 모르면 모른다고 합니다).")

    index_key_set = tuple(index_keys or ())
    if not index_key_set:
        raise DuelRuleError("점검할 지수 키가 없습니다.")

    today_keys, yesterday_keys = set(today_prices), set(yesterday_prices)
    if today_keys != yesterday_keys:
        missing = sorted(yesterday_keys - today_keys)
        extra = sorted(today_keys - yesterday_keys)
        raise DuelRuleError(
            "오늘과 전일의 점검 대상이 다릅니다(빠진 값을 무변동으로 세지 않습니다) — "
            f"오늘 빠짐: {missing}, 오늘만 있음: {extra}"
        )

    missing_indices = [key for key in index_key_set if key not in today_keys]
    if missing_indices:
        raise DuelRuleError(f"점검 대상에 지수가 빠져 있습니다: {missing_indices}")

    stock_keys = sorted(today_keys - set(index_key_set))
    if expected_stock_count is not None and len(stock_keys) != expected_stock_count:
        raise DuelRuleError(
            f"점검 대상 종목 수가 {expected_stock_count}개가 아니라 {len(stock_keys)}개입니다"
            " — 몇 종목만 보고 그날 수집 성패를 판정하지 않습니다."
        )

    def _unchanged(key):
        now = _require_number(today_prices[key], f"오늘 종가({key})", allow_zero=False)
        before = _require_number(yesterday_prices[key], f"전일 종가({key})", allow_zero=False)
        return Decimal(str(now)) == Decimal(str(before))

    any_index_changed = any(not _unchanged(key) for key in index_key_set)
    unchanged_stocks = sum(1 for key in stock_keys if _unchanged(key))
    total_stocks = len(stock_keys)

    if not any_index_changed:
        # 지수가 둘 다 그대로 → 종목이 전부 멈췄으면 휴장/실패, 일부라도 움직였으면 모순 상태.
        return CRAWL_FAILED_OR_HOLIDAY if unchanged_stocks == total_stocks else CRAWL_FAILED
    if unchanged_stocks == total_stocks:
        return CRAWL_FAILED
    if unchanged_stocks <= unchanged_tolerance:
        return CRAWL_OK
    return CRAWL_NEEDS_REVIEW


def crawl_status_allows_fill(status):
    """
    그 판정 결과로 **체결을 진행해도 되는가**. work order 2-9 / 2-5-1 참고.

    `'ok'` 하나만 True 입니다. `'needs_review'` 는 "아마 괜찮을 것"이 아니라 "사람이 봐야
    한다"이므로, 자동 배치는 체결하지 않습니다 — 애매할 때 진행하는 쪽으로 기울면 언젠가
    잘못된 가격으로 체결됩니다(§0-1). 판정 문자열을 호출부마다 비교하지 않고 이 함수를
    쓰면, 상태가 하나 늘어도 고칠 곳이 한 군데입니다(§0-3-10).
    """
    if status not in (CRAWL_OK, CRAWL_FAILED, CRAWL_FAILED_OR_HOLIDAY, CRAWL_NEEDS_REVIEW):
        raise DuelRuleError(f"알 수 없는 수집 신선도 판정입니다: {status!r}")
    return status == CRAWL_OK


# =============================================================================
# 9. 누적 시간가중수익률(TWR) — work order 2-6
# =============================================================================
def compute_twr(snapshots):
    """
    일별 스냅샷 목록에서 **누적 TWR(시간가중수익률)** 을 계산합니다. work order 2-6 참고.

    왜 단순 수익률을 쓰면 안 되는가
      매월 80만원이 계속 들어오기 때문에 `(현재가치 / 시드머니) − 1` 은 **입금액을 투자
      성과로 착각**합니다. 시드 1천만원에 6개월간 480만원이 입금되면, 아무것도 안 사고
      현금으로만 들고 있어도 "48% 수익"으로 보입니다. §0-1 이 금지하는 사실과 다른 숫자입니다.

    계산식
        r_t = (V_t − F_t) / V_(t−1) − 1        (일별 구간 수익률)
        TWR = Π(1 + r_t) − 1
      · V_t = t일 종료 시점 총자산(`total_value` = 포지션 평가액 + 현금)
      · F_t = t일에 발생한 **외부** 현금흐름(`cash_flow_amount` — 시드·정기입금만)

    **외부 현금흐름의 정의**(여기를 헷갈리면 수익률이 통째로 틀립니다):
      · 포함: 시드 지급, 매월 10일 정기 입금
      · 제외: **주식 매수** — 계좌 안에서 현금이 주식으로 바뀐 것뿐이라 총자산이 안 변합니다
      · 제외: **상장폐지 상각** — 현금흐름이 아니라 그날의 평가손실입니다. `position_value`
        에만 반영되면 위 공식이 특수 처리 없이 손실로 잡아냅니다(3-1).

    **0일차 처리(2-6 확정)**: 계좌 개설일을 0일차로 두고, 그날은 "수익률이 발생하기 전
    시작점"이라 구간 수익률 계산에 **넣지 않습니다.** 즉 곱은 1일차(개설 다음 기록일)부터
    시작하고, 0일차의 `cash_flow_amount`(시드)는 분자에서 빼지 않습니다 — 이미 V_0 에
    들어 있는 시작 자본이기 때문입니다.

    ⚠️ `cash_flow_amount` 가 없는 행은 **0 으로 채우지 않고 예외**입니다. 기본값을 주면
       "그날 늘어난 돈이 수익인지 입금인지"를 조용히 잘못 판정하고, 그게 정확히 이 함수가
       막으려는 버그입니다.

    반환 dict (report_db 의 기간 리포트와 같은 "상태 + 값" 관례)
        status        : 'OK' / 'NO_DATA' / 'INSUFFICIENT'
        twr_pct       : 누적 수익률(%). OK 가 아니면 **None**(0.0 이 아닙니다)
        period_count  : 실제로 곱한 구간 수(= 스냅샷 수 − 1)
        baseline_date : 0일차 날짜
        end_date      : 마지막 스냅샷 날짜

    표시 반올림은 화면이 소수점 둘째 자리로 합니다(2-6). 여기서는 DB 컬럼과 같은 6자리까지
    남겨 두므로, 화면이 다시 반올림해도 값이 흔들리지 않습니다.
    """
    rows = list(snapshots or [])
    if not rows:
        return {"status": TWR_NO_DATA, "twr_pct": None, "period_count": 0,
                "baseline_date": None, "end_date": None}

    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise DuelRuleError(f"스냅샷 항목이 dict 가 아닙니다: {row!r}")
        day = _to_date(row.get("snapshot_date"), "스냅샷 날짜")
        total_value = _require_number(row.get("total_value"), f"총자산({day})")
        if "cash_flow_amount" not in row or row.get("cash_flow_amount") is None:
            raise DuelRuleError(
                f"{day} 스냅샷에 cash_flow_amount 가 없습니다 — 0 으로 가정하면 입금을 수익으로"
                " 착각하게 됩니다(작업지시서 2-6). 값이 없는 구간의 TWR 은 계산하지 않습니다."
            )
        cash_flow = _require_number(row.get("cash_flow_amount"), f"외부 현금흐름({day})")
        parsed.append((day, total_value, cash_flow))

    parsed.sort(key=lambda item: item[0])
    days = [item[0] for item in parsed]
    if len(set(days)) != len(days):
        raise DuelRuleError("같은 날짜의 스냅샷이 둘 이상입니다(계좌 × 거래일 = 1행이어야 합니다).")

    if len(parsed) == 1:
        # 개설일 스냅샷 하나뿐 → 구간이 아직 없습니다. **0% 가 아니라 "계산 불가"** 입니다.
        return {"status": TWR_INSUFFICIENT, "twr_pct": None, "period_count": 0,
                "baseline_date": days[0], "end_date": days[0]}

    chain = 1.0
    for index in range(1, len(parsed)):
        _prev_day, prev_value, _prev_flow = parsed[index - 1]
        day, value, cash_flow = parsed[index]
        if prev_value <= 0:
            raise DuelRuleError(
                f"{_prev_day} 의 총자산이 {prev_value} 라 {day} 구간 수익률을 계산할 수 없습니다"
                " — 분모가 0 이하인 구간을 임의의 값으로 넘기지 않습니다."
            )
        chain *= (value - cash_flow) / prev_value

    return {
        "status": TWR_OK,
        "twr_pct": _round6((chain - 1.0) * 100.0),
        "period_count": len(parsed) - 1,
        "baseline_date": days[0],
        "end_date": days[-1],
    }


# #############################################################################
#
#  10. 🔴 5단계(Branch 2 "내 밑으로 눈 깔어") 공개 순위표 규칙 — 2026-08-20 추가
#
#  ⚠️ 이 절은 이 프로젝트에서 **가장 민감한 코드**입니다(§0-3-8 — 최상위 무예외 원칙).
#     여기 함수들이 만드는 값은 곧 **다른 사람에게 보여지는 값**입니다. 그래서 아래 규칙을
#     지킵니다:
#       · 이 절의 함수는 여전히 **아무것도 읽지 않습니다.** 동의 여부·매입원가·닉네임 중복
#         판정 같은 "실제 사실"은 전부 인자로 받습니다. 여기서 DB 를 보면 "동의 안 한 사람의
#         데이터를 실수로 읽는" 경로가 이 파일에 생깁니다.
#       · 값을 **지어내지 않습니다.** 체급을 못 정하면 아무 구간이나 찍지 않고 "구간 미적용"
#         이라고 말하고, 수익률을 못 구하면 0% 가 아니라 **계산 불가**로 돌려줍니다(§0-1).
#
#  작업지시서 대응
#    · 5-3  원금 구간(체급) 8개 경계값        → BRACKET_TIERS / assign_bracket()
#    · 5-3  체급 시즌 고정(1년)               → resolve_bracket_for_season()
#    · 5-5  무작위 닉네임                     → generate_nickname()
#    · 5-4-3 순위 계산                        → rank_participants()
#    · 5-6  최소 참가 인원(500명)             → MIN_PARTICIPANTS_FOR_PUBLICATION
#    · 5-8-2 철회 후 3개월 재동의 차단        → resolve_reconsent_block()
#
# #############################################################################

# =============================================================================
# 10-1. 원금 구간(체급) — work order 5-3 · 경계값의 **단일 출처** (§0-3-10)
# =============================================================================
#  🔴 아래 8줄이 이 프로젝트에서 구간 경계 숫자가 적힌 **유일한 자리**입니다.
#     SQL 에도, 화면에도, 배치에도 이 숫자를 다시 적지 마세요. 두 곳에 적으면 둘 중 하나만
#     바뀌는 날이 오고, 그날 어떤 사용자는 자기가 속하지 않은 체급에서 겨루게 됩니다.
#     (`sql/duel_schema.sql` §8 의 bracket_key 주석도 "앱 상수가 단일 출처"라고 못 박아
#      뒀습니다 — DB 는 문자열을 그대로 받기만 합니다.)
#
#  경계 해석(오너 확정 원문 그대로): "1억원 **이상**" / "6천만원 **이상** ~ 1억원 **미만**" …
#  즉 각 구간은 **[하한 이상, 상한 미만)** 입니다. 겹치는 구간도, 빈 구간도 없습니다.
#
#  key 를 한글이 아니라 ASCII 로 둔 이유: 이 값은 화면에 보이는 라벨이 아니라 **DB 컬럼 값 ·
#  유니크 제약의 일부 · 나중에 순위표 탭/URL 파라미터로 쓰일 식별자**입니다. 식별자와 라벨을
#  같은 문자열로 쓰면, 나중에 라벨 문구를 다듬는 순간(예: "6천~1억" → "6천만~1억원") 이미
#  발행된 과거 행과 새 행이 **서로 다른 구간으로 갈라집니다.** 그래서 key(불변)와
#  label(문구, 언제든 다듬어도 안전)을 한 줄 안에서 짝지어 둡니다.
#: (bracket_key, 화면 라벨, 하한(이상), 상한(미만) — 상한 None 은 "위로 열려 있음")
BRACKET_TIERS = (
    ("krw_100m_plus",  "1억원 이상",              100_000_000, None),
    ("krw_60m_100m",   "6천만원 이상 1억원 미만",  60_000_000, 100_000_000),
    ("krw_30m_60m",    "3천만원 이상 6천만원 미만", 30_000_000, 60_000_000),
    ("krw_10m_30m",    "1천만원 이상 3천만원 미만", 10_000_000, 30_000_000),
    ("krw_5m_10m",     "500만원 이상 1천만원 미만",  5_000_000, 10_000_000),
    ("krw_3m_5m",      "300만원 이상 500만원 미만",  3_000_000, 5_000_000),
    ("krw_1m_3m",      "100만원 이상 300만원 미만",  1_000_000, 3_000_000),
    ("krw_under_1m",   "100만원 미만",                        0, 1_000_000),
)

#: 체급을 **정할 수 없는** 참가자들의 그룹(5-2-4). 세 종류가 여기로 옵니다:
#:   ① `consent_real_principal_bracket` 이 false — 실제 매입총합을 쓰지 말라고 한 사용자.
#:      **이 사용자도 순위표에는 참여합니다.** 빠지는 것은 체급뿐입니다.
#:   ② "내 성적표"에 등록된 보유종목이 하나도 없어서 매입원가합계라는 값 자체가 없는 경우.
#:      0원으로 간주해 최하위 구간에 넣지 않습니다 — "0원어치 보유"와 "아직 아무것도 등록
#:      하지 않음"은 다른 말이고, 후자를 전자로 바꾸면 §0-1 위반입니다.
#:   ③ 원화·달러 종목을 함께 보유해 **하나의 원화 금액으로 합칠 수 없는** 경우.
#:      이 앱에는 환율 시계열이 없습니다(`scorecard_db.NO_FX_CONVERSION_NOTICE`). 환율을
#:      지어내면 §0-1 정면 위반이라, 합치지 않고 "구간 미적용"으로 둡니다.
BRACKET_NONE_KEY = "no_bracket"
BRACKET_NONE_LABEL = "구간 미적용"

#: 발행표에 실제로 나타날 수 있는 bracket_key 전부(위 8개 + 구간 미적용).
BRACKET_KEYS = tuple(tier[0] for tier in BRACKET_TIERS) + (BRACKET_NONE_KEY,)

#: bracket_key → 화면 라벨. 화면(6단계)이 이 표만 보게 해서 라벨을 한 곳에서만 고치게 합니다.
BRACKET_LABELS = dict(
    [(key, label) for key, label, _low, _high in BRACKET_TIERS]
    + [(BRACKET_NONE_KEY, BRACKET_NONE_LABEL)]
)


def assign_bracket(real_principal_krw):
    """
    실제 "내 성적표" 매입원가합계(원) → 체급(bracket_key). work order 5-3 참고.

    경계는 전부 **[하한 이상, 상한 미만)** 입니다. 경계값 그 자체(예: 정확히 1억원)는
    **위쪽 구간**에 들어갑니다 — "1억원 이상"이 오너가 준 원문이기 때문입니다.

    ⚠️ `None` 을 넣으면 0 으로 간주하지 않고 예외입니다. "매입총합을 모른다"를 "0원"으로
       바꾸면 그 사용자는 자기 것이 아닌 최하위 체급에서 겨루게 됩니다(§0-1). 값을 모르는
       경우는 호출부가 `BRACKET_NONE_KEY`(구간 미적용)를 쓰세요.
    ⚠️ 음수도 예외입니다. 매입원가합계가 음수인 상태는 데이터 손상이지 체급이 아닙니다.
    """
    amount = _require_number(real_principal_krw, "매입원가합계", allow_negative=False)
    for key, _label, low, high in BRACKET_TIERS:
        if amount >= low and (high is None or amount < high):
            return key
    # 여기 도달하면 위 표에 구멍이 있다는 뜻입니다(하한 0 짜리 구간이 있으므로 정상적으로는
    # 불가능). 조용히 최하위로 떨어뜨리지 않고 시끄럽게 실패합니다.
    raise DuelRuleError(
        f"매입원가합계 {amount} 에 해당하는 체급이 없습니다 — BRACKET_TIERS 에 구멍이 있습니다."
    )


def bracket_label(bracket_key):
    """bracket_key → 화면에 쓸 한국어 라벨. 모르는 키는 지어내지 않고 예외입니다."""
    key = str(bracket_key or "").strip()
    if key not in BRACKET_LABELS:
        raise DuelRuleError(f"알 수 없는 체급 식별자입니다: {bracket_key!r}")
    return BRACKET_LABELS[key]


# =============================================================================
# 10-2. 시즌 — 체급은 시즌 동안 **고정**됩니다 (work order 5-3 · 5차 확정)
# =============================================================================
#  왜 고정인가: 체급이 시즌 중에 계속 흔들리면 "체급을 맞춰 공정하게 겨룬다"는 취지가
#  무너집니다(원금이 큰 사람이 유리한 체급으로 옮겨 다니는 것과 같아짐 — 오너 판단).
#
#  ✅ 시즌 시작 기준일 = **매년 3월 1일**(고정 달력일, 2026-08-20 오너 확정).
#     처음엔 1월 1일을 코딩 에이전트가 추천했었으나(집합 연산으로 한 번에 재산정하기
#     쉽다는 이유), 오너가 3월 1일로 확정했습니다. 고정 달력일이라는 성질 자체는
#     그대로입니다 — 아래 두 이유는 "왜 고정 달력일인가"(3월 1일이든 1월 1일이든
#     공통으로 성립하는 이유)로 계속 유효합니다:
#       · 전원을 **한 번에** 재산정하는 집합 연산이 됩니다(§0-3-2). 가입 기념일 방식이면
#         배치가 매일 "오늘이 기념일인 사람"을 찾아 계좌별로 처리하게 되고, 그게 정확히
#         2-7 이 금지한 모양입니다.
#       · 순위표에 "지금은 2026 시즌"이라고 한 줄 쓰면 모든 참가자에게 같은 뜻이 됩니다.
#         사람마다 시즌 경계가 다르면 "왜 저 사람만 체급이 바뀌었지"를 설명할 수 없습니다.
#     날짜를 다시 바꿔야 하면 아래 상수 두 줄만 고치면 됩니다(§0-3-10).
#: 시즌 길이(개월). 작업지시서 5-3 의 표기(`duel_season_length_months = 12`)를 그대로 씁니다.
DUEL_SEASON_LENGTH_MONTHS = 12
#: 시즌이 시작하는 달·일(매년 3월 1일, 2026-08-20 오너 확정).
DUEL_SEASON_ANCHOR_MONTH = 3
DUEL_SEASON_ANCHOR_DAY = 1


def _add_months(base_date, months):
    """달 단위 덧셈(표준 라이브러리만으로). 말일 보정 포함 — 1/31 + 1개월 = 2/28(29)."""
    total = (base_date.year * 12 + (base_date.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    # 그 달의 마지막 날을 넘지 않게 자릅니다(3/31 → 4/30).
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(base_date.day, last_day))


def season_start_for_date(on_date):
    """
    그 날짜가 속한 시즌의 **시작일**. 시즌 길이가 12개월이므로 결과는 해당 연도의 3월 1일
    입니다(길이·앵커 상수를 바꾸면 여기 계산이 함께 따라갑니다 — 숫자를 두 곳에 적지 않기).
    """
    day = _to_date(on_date, "기준일")
    anchor = date(day.year, DUEL_SEASON_ANCHOR_MONTH, DUEL_SEASON_ANCHOR_DAY)
    if day < anchor:
        # 앵커(3/1)보다 앞이면 직전 시즌.
        anchor = _add_months(anchor, -DUEL_SEASON_LENGTH_MONTHS)
    while _add_months(anchor, DUEL_SEASON_LENGTH_MONTHS) <= day:
        anchor = _add_months(anchor, DUEL_SEASON_LENGTH_MONTHS)
    return anchor


def season_key_for_date(on_date):
    """
    그 날짜가 속한 **시즌 식별자**(예: `'2026-03-01'`). 이 문자열이 체급 배정 기록의 키이고,
    "같은 시즌인가"를 묻는 유일한 방법입니다.

    시작일을 그대로 키로 쓰는 이유: 연도만 쓰면(`'2026'`) 나중에 시즌 길이나 앵커를 바꿨을 때
    같은 연도 안에 시즌이 둘 생기면서 키가 충돌합니다. 시작일은 어떤 설정에서도 유일합니다.
    """
    return season_start_for_date(on_date).isoformat()


def resolve_bracket_for_season(existing_assignment, fresh_bracket_key, on_date):
    """
    🔴 **"체급은 시즌 동안 고정"을 강제하는 단 하나의 자리입니다.** work order 5-3 참고.

    배치는 매일 밤 돌고, 매일 밤 "지금 이 사람의 매입원가합계는 얼마지"를 다시 물을 수
    있습니다. 그 값으로 매번 체급을 다시 매기면 시즌 고정 규칙이 **조용히 사라집니다.**
    그래서 배치가 체급을 직접 정하지 못하게 하고, 반드시 이 함수를 통과하게 했습니다.

    인자
        existing_assignment : 이미 저장된 배정 기록 dict 또는 None.
                              `{"season_key": ..., "bracket_key": ...}` 모양이면 됩니다.
        fresh_bracket_key   : 오늘 값으로 새로 계산한 체급(`assign_bracket()` 결과 또는
                              `BRACKET_NONE_KEY`). **시즌이 바뀌었을 때만** 쓰입니다.
        on_date             : 오늘(발행일).

    반환 dict
        season_key   : 오늘이 속한 시즌
        bracket_key  : 실제로 쓸 체급
        source       : 'kept'(시즌 중 — 기존 배정 유지) / 'assigned'(새 시즌 또는 첫 배정)
        needs_write  : 배정 기록을 새로 저장해야 하는가(= source == 'assigned')

    ⚠️ 기존 배정이 **다른 시즌**의 것이면 그건 "지난 시즌 기록"이라 유지하지 않습니다.
    ⚠️ 기존 배정이 같은 시즌이면 오늘 매입원가가 얼마로 바뀌었든 **그대로 유지**합니다 —
       `fresh_bracket_key` 는 쳐다보지도 않습니다. 이게 이 함수의 존재 이유입니다.
    """
    season_key = season_key_for_date(on_date)

    existing = existing_assignment or None
    if existing:
        if not isinstance(existing, dict):
            raise DuelRuleError(f"체급 배정 기록이 dict 가 아닙니다: {existing!r}")
        existing_season = str(existing.get("season_key") or "").strip()
        existing_bracket = str(existing.get("bracket_key") or "").strip()
        if existing_season == season_key:
            if existing_bracket not in BRACKET_KEYS:
                raise DuelRuleError(
                    f"저장된 체급 식별자를 알 수 없습니다: {existing_bracket!r}"
                    " — 임의의 체급으로 대체하지 않고 중단합니다(§0-1)."
                )
            return {"season_key": season_key, "bracket_key": existing_bracket,
                    "source": "kept", "needs_write": False}

    fresh = str(fresh_bracket_key or "").strip()
    if fresh not in BRACKET_KEYS:
        raise DuelRuleError(f"새로 계산한 체급 식별자를 알 수 없습니다: {fresh_bracket_key!r}")
    return {"season_key": season_key, "bracket_key": fresh,
            "source": "assigned", "needs_write": True}


# =============================================================================
# 10-3. 무작위 닉네임 — work order 5-5 · 스키마 §6
# =============================================================================
#  🔴 **이 파일에서 유일하게 결정적이지 않은(= 같은 입력에 같은 출력을 주지 않는) 함수**
#     입니다. 그게 버그가 아니라 **요구사항**입니다.
#
#     닉네임을 `user_id`·이메일·가입시각 같은 값에서 유도하면(해시를 포함해서), 알고리즘이
#     알려지는 순간 "이 닉네임은 누구인가"를 역계산할 수 있습니다. 소스 코드는 공개
#     저장소에 있고, 알고리즘이 알려지는 것은 시간 문제입니다(§0-3-9 — 이미 알려진 기법에
#     예외 없이 방어). 그래서 **입력 자체를 받지 않습니다.**
#
#     ⚠️ 이 함수의 안전성 근거는 "우리가 조심해서 user_id 를 안 넣는다"가 아니라
#        **인자가 하나도 없다** 입니다. 남의 정체성에서 닉네임을 만들 문법 자체가 없습니다
#        (`duel_db.opt_in()` 이 인자를 안 받는 것과 같은 종류의 구조적 방어).
#        `tests/test_duel_publish.py` 가 시그니처를 검사해 이걸 고정합니다.
#
#  난수원: `secrets`(OS 의 암호학적 난수). `random` 모듈의 기본 난수는 시드를 알면 수열을
#  재현할 수 있어서, "언제 만들어졌는지"를 아는 사람이 후보를 좁힐 여지가 남습니다. 닉네임은
#  익명성의 마지막 껍질이라 여기서 아끼지 않습니다.
import secrets  # noqa: E402  (이 절에서만 쓰는 표준 라이브러리 — 위 규율의 예외 아님)

#: 형용사(관형어) 목록. 대결 모듈의 분위기에 맞춰 **사람·성별·지역·나이를 암시하지 않는**
#: 단어만 골랐습니다 — 닉네임이 사람에 대한 힌트를 주면 익명성이 약해집니다.
#: ✅ 2026-08-20 오너 확인 — 숫자 접미사가 "기계적으로 느껴진다"는 지적에 따라 숫자를
#:    완전히 없애는 대신 **이 목록 자체를 3배 가까이(48→130) 늘렸습니다.** 아래
#:    `generate_nickname()`의 "왜 숫자 없이도 안전한가" 절 참고.
NICKNAME_ADJECTIVES = (
    "고요한", "날쌘", "느긋한", "단단한", "당당한", "듬직한", "따끈한", "또렷한",
    "말끔한", "매서운", "묵직한", "바지런한", "발랄한", "번쩍이는", "보드라운", "부지런한",
    "빛나는", "새침한", "서늘한", "선선한", "수줍은", "시원한", "싱그러운", "아득한",
    "야무진", "얌전한", "엉뚱한", "여유로운", "올곧은", "우렁찬", "은은한", "잔잔한",
    "재빠른", "정갈한", "짜릿한", "차분한", "촘촘한", "출렁이는", "커다란", "포근한",
    "푸른", "한결같은", "홀가분한", "화사한", "환한", "훈훈한", "흐뭇한", "힘찬",
    "씩씩한", "용맹한", "늠름한", "다부진", "굳센", "억센", "날렵한", "활기찬",
    "상큼한", "달콤한", "새콤한", "쌉싸름한", "고소한", "짭짤한", "향긋한", "은근한",
    "살랑이는", "두근거리는", "알록달록한", "반짝거리는", "말랑한", "몽실몽실한", "오동통한", "넉넉한",
    "푸짐한", "소담한", "아늑한", "정겨운", "다정한", "살가운", "애틋한", "살뜰한",
    "알뜰한", "소박한", "담백한", "우직한", "성실한", "꼼꼼한", "세심한", "치밀한",
    "다감한", "상냥한", "친절한", "온화한", "유쾌한", "명랑한", "쾌활한", "늠실거리는",
    "넘실대는", "그윽한", "아리따운", "어여쁜", "곱디고운", "청초한", "단아한", "우아한",
    "고상한", "기품있는", "근사한", "멋들어진", "탐스러운", "소담스러운", "향기로운", "산뜻한",
    "청량한", "쨍쨍한", "눈부신", "영롱한", "반들반들한", "매끄러운", "쫀득한", "쫄깃한",
    "바삭한", "폭신한", "나긋한", "유연한", "늘씬한", "견고한", "굳건한", "든든한",
    "믿음직한", "재치있는",
)

#: 명사 목록. 마찬가지로 **실명·지명·회사명·종목명을 연상시키지 않는** 일반명사만 씁니다
#: (종목명을 쓰면 "이 사람이 그 종목을 산 사람인가" 하는 엉뚱한 추측이 생깁니다).
#: ✅ 2026-08-20 오너 확인 — 형용사와 같은 이유로 48→128개로 늘렸습니다.
NICKNAME_NOUNS = (
    "가람", "고래", "구름", "그림자", "나루", "노을", "다람쥐", "달빛",
    "도토리", "돌고래", "동백", "들판", "등대", "매화", "모래알", "무지개",
    "물결", "미나리", "바람개비", "반딧불", "밤하늘", "별똥별", "보름달", "부엉이",
    "북극성", "사슴", "산들바람", "새벽", "소나기", "소나무", "솔방울", "수달",
    "수박씨", "숲길", "실개천", "썰물", "안개꽃", "여울", "연잎", "오솔길",
    "은하수", "이슬", "잔디", "종달새", "지평선", "찻잔", "코끼리", "파도",
    "호랑이", "사자", "매", "독수리", "여우", "늑대", "참새", "두루미",
    "원앙", "백로", "청둥오리", "나비", "잠자리", "반딧불이", "사슴벌레", "청설모",
    "오소리", "살쾡이", "담비", "너구리", "개구리", "도롱뇽", "잉어", "붕어",
    "은어", "반달곰", "산양", "노루", "멧돼지", "메아리", "소나기구름", "뭉게구름",
    "노을빛", "별빛", "물안개", "이슬비", "진눈깨비", "함박눈", "첫눈", "아지랑이",
    "봄바람", "갈바람", "하늬바람", "물레방아", "강바람", "실바람", "소용돌이", "여울목",
    "개울가", "시냇물", "자갈밭", "모래밭", "갯벌", "등불", "촛불", "모닥불",
    "화롯불", "장작불", "처마", "툇마루", "장독대", "우물가", "대숲", "갈대밭",
    "억새밭", "메밀꽃", "유채꽃", "진달래", "개나리", "벚꽃", "민들레", "강아지풀",
    "클로버", "이끼", "조약돌", "몽돌", "자갈", "여치", "방울벌레", "풀벌레",
)


def nickname_space_size():
    """
    만들 수 있는 닉네임의 총 가짓수. 충돌 확률을 눈으로 확인하려고 함수로 빼 뒀습니다
    (테스트가 이 값이 조용히 줄어드는 것을 잡습니다 — 단어를 지우면 익명성이 얇아집니다).

    닉네임은 **서로 다른 형용사 2개(순서 있음) + 명사 1개**로 만들므로, 전체 가짓수는
    형용사 개수 × (형용사 개수 - 1) × 명사 개수 입니다(형용사 2개를 고르는 순서 있는 쌍).
    """
    a = len(NICKNAME_ADJECTIVES)
    return a * (a - 1) * len(NICKNAME_NOUNS)


def generate_nickname():
    """
    무작위 닉네임 **후보** 하나를 만듭니다(예: `'씩씩한잔잔한물결'`). work order 5-5 참고.

    ── 2026-08-20 — 숫자 접미사를 없앴습니다 ────────────────────────────────────
    원래는 (형용사 + 명사 + 숫자 4자리) 형태였는데, 오너가 "숫자가 붙으니 닉네임이
    기계적으로 느껴진다"고 지적했습니다. 숫자를 없애고도 충돌 위험이 커지지 않도록,
    숫자가 채우던 공간을 **형용사를 서로 다른 것으로 2개 뽑는 방식**으로 옮겼습니다
    (그래서 위 두 단어 목록도 48개 → 130개/128개로 크게 늘렸습니다).

    ── 이 함수의 안전성 근거 ─────────────────────────────────────────────────────
    **인자가 하나도 없습니다.** `user_id`·이메일·가입시각은 물론이고 그 어떤 값도 받지
    않으므로, 닉네임을 사람에게 되돌려 계산할 **입력 자체가 존재하지 않습니다.** 해시도
    쓰지 않습니다 — 해시는 되돌릴 수 없다고들 하지만, 입력 공간이 "우리 서비스의 사용자
    id 목록"처럼 좁으면 전수 대입으로 즉시 역조회됩니다(§0-3-9).

    ── 유일성은 여기서 보장하지 않습니다 ─────────────────────────────────────────
    이 함수는 **후보만** 만듭니다. "이미 쓰는 닉네임인가"는 DB 의 `unique` 제약이 판정하고,
    충돌하면 `duel_db.ensure_nickname()` 이 다시 부릅니다(스키마 §6: "생성은 난수 → unique
    충돌 시 재시도", 최대 `NICKNAME_MAX_ATTEMPTS`번). 앱이 "이미 있는지 먼저 조회"하는
    방식을 쓰지 않는 이유는, 조회와 삽입 사이에 다른 세션이 같은 이름을 넣는 경합을 앱이
    막을 수 없기 때문입니다.

    ── 충돌이 얼마나 드문가 (두 가지 서로 다른 질문을 헷갈리지 않도록 나눠서) ──────────
    현재 공간은 `nickname_space_size()` = 130 × 129 × 128 ≈ 214만 가지입니다.
      · **"이미 참가자가 N명 있는 상태에서, 방금 만든 새 후보 하나가 그중 하나와 겹칠
        확률"**(재시도를 실제로 유발하는 확률)은 **N ÷ 214만**입니다. 참가자 1만 명일 때
        약 0.47%, 5만 명일 때도 약 2.3%에 불과합니다 — 겹쳐도 곧바로 재시도 한 번이면
        끝나므로 이 정도는 문제가 되지 않습니다. 8번 연속 겹쳐서 발급 자체가 실패할
        확률은 참가자 5만 명 기준으로도 10^-13 수준(사실상 0)입니다.
      · **"참가자 N명이 다 모일 때까지, 그 사이 어디선가 재시도가 최소 한 번은
        일어날 확률"**(생일 문제 계산)은 이보다 훨씬 빠르게 커져서 N=5,000명 근처부터는
        오히려 거의 100%에 가깝습니다. 그래도 걱정할 숫자는 아닙니다 — 이건 "실제로 같은
        닉네임을 가진 두 사람이 생긴다"는 뜻이 아니라(그건 `duel_nicknames.nickname`의
        `unique` 제약이 애초에 불가능하게 막습니다), **"N명이 늘어나는 동안 위에서 말한
        저렴한 재시도가 최소 한 번쯤은 어딘가에서 일어난다"**는 뜻일 뿐입니다. 재시도
        자체는 바로 위에서 계산한 것처럼 거의 항상 1번 만에 끝나고, 8번 다 실패해서
        발급이 진짜로 막힐 확률은 참가자 5만 명 기준으로도 사실상 0입니다.
    """
    while True:
        adjective_1, adjective_2 = secrets.choice(NICKNAME_ADJECTIVES), secrets.choice(NICKNAME_ADJECTIVES)
        if adjective_1 != adjective_2:
            break
    noun = secrets.choice(NICKNAME_NOUNS)
    return f"{adjective_1}{adjective_2}{noun}"


# =============================================================================
# 10-4. 순위 계산 — work order 5-4-3 · 2-7
# =============================================================================
#  왜 SQL 의 `rank() over (...)` 가 아니라 파이썬인가 (선택의 근거를 남깁니다)
#    · 2-7 이 진짜로 금지한 것은 **"화면 로드 시 순위를 계산하는 것"** 입니다. 순위를
#      배치에서 미리 계산해 발행표에 저장하기만 하면 그 요구는 충족됩니다 — 계산을 어느
#      언어로 하느냐는 그 요구와 무관합니다.
#    · 이 저장소는 Supabase 를 **PostgREST(표 단위 REST)** 로만 씁니다. 윈도우 함수를 쓰려면
#      DB 안에 새 함수나 뷰를 만들어 RPC 로 불러야 하고, 그건 §0-3-8 에서 가장 조심해야 할
#      표(발행표)의 주변에 **검토해야 할 표면을 하나 더 늘리는 일**입니다.
#    · 배치는 어차피 TWR 을 구하려고 스냅샷 전부를 이미 메모리에 갖고 있습니다. 정렬
#      한 번(O(n log n))이 추가될 뿐이고, 이건 하루 한 번입니다. 방문자마다 도는 게 아닙니다.
#    · 저장소 선례도 파이썬 정렬입니다(`scorecard_db.sort_holding_rows()`).
#  → 결론: 순위는 여기(순수 함수)에서 계산하고, 발행표에는 **계산된 값만** 저장합니다.

#: 🔴 최소 참가 인원(5-6, 오너 확정 500명). 이 인원을 못 채운 (창유형 × 체급) 그룹은 아예
#:    발행하지 않습니다 — 3명짜리 구간에서 "1위 닉네임"은 사실상 실명이기 때문입니다.
MIN_PARTICIPANTS_FOR_PUBLICATION = 500


def group_meets_minimum(participant_count):
    """그 그룹을 발행해도 되는 인원인가(5-6). 비교를 여기 한 곳에만 둡니다(§0-3-10)."""
    count = _require_int(participant_count, "참가 인원", minimum=0)
    return count >= MIN_PARTICIPANTS_FOR_PUBLICATION


def rank_participants(entries):
    """
    한 그룹(창유형 × 체급) 안의 참가자들에게 **순위**를 매깁니다. work order 5-4-3 참고.

    인자
        entries : `[{"nickname": str, "twr_pct": float|None}, ...]`
                  (다른 키가 함께 있어도 그대로 통과시켜 돌려줍니다 — 발행 배치가 종목
                   목록 같은 걸 같이 들고 다닐 수 있게)

    반환 `(ranked, unrankable)`
        ranked     : 원본 dict 에 `rank` 를 더한 목록. **수익률 내림차순**(높을수록 1위).
        unrankable : `twr_pct` 가 None 이라 순위를 매길 수 없는 참가자 목록(원본 그대로).

    ── `twr_pct` 가 None 인 참가자를 왜 빼는가 (§0-1) ────────────────────────────
    개설 첫날처럼 **구간 수익률이 아직 하나도 없는** 계좌는 `compute_twr()` 가
    `status='INSUFFICIENT'`, `twr_pct=None` 을 돌려줍니다. "0%"가 아니라 "계산 불가"입니다.
    이걸 0% 로 바꿔 순위에 끼우면 그 사람은 **실제로는 존재하지 않는 성적**으로 남들 위나
    아래에 서게 됩니다. 그래서 순위를 매기지 않고 **발행 대상에서 빼고**, 호출부가 그
    사실을 로그에 남깁니다. (5-6 의 최소 인원도 이렇게 **실제로 순위가 나온 사람 수**로
    셉니다 — "자격은 있지만 성적이 없는" 사람을 인원수에 넣으면 그만큼 익명성이 얇아집니다.)

    ── 동점 처리 ────────────────────────────────────────────────────────────────
    같은 수익률이면 **같은 순위**를 주고, 다음 순위는 그만큼 건너뜁니다(1, 2, 2, 4 — 스포츠
    중계에서 쓰는 그 방식). 동점자에게 억지로 다른 순위를 주려면 어딘가에서 순서를 지어내야
    하고(닉네임 가나다순? 계좌 생성순?), 그건 사실이 아닌 정보를 발행하는 일입니다(§0-1).
      ⚠️ 동점은 드문 일이 **아닙니다.** 아무것도 사지 않고 현금만 들고 있는 계좌의 TWR 은
         정확히 0.000000% 라, 참가자가 500명쯤 되면 0% 동점자는 거의 확실히 생깁니다.
         (`sql/duel_schema.sql` 의 유니크 제약이 이 때문에 2026-08-20 에 수정됐습니다 —
          예전 제약은 `(published_date, window_type, bracket_key, rank)` 라 동점 두 행이
          들어가는 순간 발행이 통째로 거절됐습니다.)

    ── 표시 순서 ────────────────────────────────────────────────────────────────
    반환 목록의 순서는 (수익률 내림차순, 닉네임 오름차순)입니다. 두 번째 키는 **순위를
    가르는 데 쓰이지 않고**(동점은 여전히 같은 순위), 배치를 두 번 돌렸을 때 행 순서가
    흔들리지 않게만 합니다.
    """
    rows = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            raise DuelRuleError(f"참가자 항목이 dict 가 아닙니다: {entry!r}")
        nickname = str(entry.get("nickname") or "").strip()
        if not nickname:
            raise DuelRuleError("참가자 닉네임이 비어 있습니다(익명 식별자가 없는 행은 발행할 수 없습니다).")
        rows.append((nickname, entry))

    seen = set()
    for nickname, _entry in rows:
        if nickname in seen:
            raise DuelRuleError(
                f"같은 닉네임이 한 그룹에 두 번 있습니다: {nickname!r}"
                " — 임의로 하나를 버리지 않고 중단합니다(원본 데이터를 확인하세요)."
            )
        seen.add(nickname)

    unrankable = [entry for _nickname, entry in rows if entry.get("twr_pct") is None]
    rankable = [(nickname, entry) for nickname, entry in rows if entry.get("twr_pct") is not None]

    scored = []
    for nickname, entry in rankable:
        scored.append((_require_number(entry.get("twr_pct"), f"수익률({nickname})",
                                       allow_negative=True), nickname, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))

    ranked = []
    previous_score = None
    current_rank = 0
    for index, (score, _nickname, entry) in enumerate(scored, start=1):
        if previous_score is None or score != previous_score:
            current_rank = index          # 동점이 끝나면 "몇 번째 줄인가"가 곧 순위입니다.
            previous_score = score
        row = dict(entry)
        row["rank"] = current_rank
        ranked.append(row)
    return ranked, unrankable


# =============================================================================
# 10-5. 철회 후 재동의 차단 — work order 5-8-2
# =============================================================================
#: 철회 후 재동의가 막히는 기간(개월). 오너 확정 3개월(5-8-2).
RECONSENT_BLOCK_MONTHS = 3


def resolve_reconsent_block(revoked_at, now=None):
    """
    철회 이력으로 **지금 재동의가 가능한지** 판정합니다. work order 5-8-2 참고.

    인자
        revoked_at : 철회 시각(ISO 문자열 / datetime) 또는 None(철회한 적 없음).
        now        : 판정 기준 시각(KST). 테스트·재현을 위해 인자로 받습니다.

    반환 dict
        blocked        : 지금 재동의가 막혀 있는가
        unblocks_at    : 풀리는 시각(KST, aware datetime) 또는 None
        unblocks_on    : 풀리는 **날짜**(사용자에게 보여줄 값) 또는 None
        revoked_at     : 해석된 철회 시각 또는 None

    ⚠️ 화면만 막으면 안 됩니다(5-8-2 명문). 이 판정은 앱 저장 경로(`duel_db.save_consent()`
       / `revoke_consent()`)와 발행 배치 양쪽에서 씁니다 — 화면만 막으면 배치가 되살립니다.
    ⚠️ 경계 처리: 정확히 3개월이 **되는 순간부터** 풀립니다(`now >= unblocks_at`).
       "3개월이 지나야"를 하루 더 미루지 않습니다 — 사용자에게 알려 준 날짜에 실제로
       풀려야 하기 때문입니다.
    """
    if revoked_at is None or (isinstance(revoked_at, str) and not revoked_at.strip()):
        return {"blocked": False, "unblocks_at": None, "unblocks_on": None, "revoked_at": None}

    revoked = _to_kst(revoked_at, "철회 시각")
    moment = _to_kst(now, "현재 시각") if now is not None else datetime.now(KST)

    unblock_date = _add_months(revoked.date(), RECONSENT_BLOCK_MONTHS)
    unblocks_at = datetime.combine(unblock_date, revoked.timetz())
    return {
        "blocked": moment < unblocks_at,
        "unblocks_at": unblocks_at,
        "unblocks_on": unblock_date,
        "revoked_at": revoked,
    }


# =============================================================================
# 10-6. 순위표 **표시** 상수 — work order 5-7 (2026-08-20 · 화면 2종 작업에서 추가)
# =============================================================================
#  5-7 원문: *"**상위 500 + 하위 500**, 페이지네이션. 미국주식 화면(30개 페이지네이션)의
#  기존 패턴을 참고하세요(§0-3-10)."*
#
#  ⚠️ 여기 있는 세 숫자는 **표시 규칙**이지 발행 규칙이 아닙니다. 발행 여부를 가르는
#     `MIN_PARTICIPANTS_FOR_PUBLICATION`(500) 과 아래 `LEADERBOARD_TOP_COUNT`(500) 는
#     **숫자가 우연히 같을 뿐 완전히 다른 개념**입니다 — 하나는 "몇 명부터 공개해도
#     익명성이 지켜지는가"(5-6), 다른 하나는 "공개된 순위표에서 몇 등까지 보여줄
#     것인가"(5-7)입니다. 한쪽을 바꾼다고 다른 쪽이 따라 바뀌면 안 되므로 상수를 따로
#     둡니다(같은 값을 참조하게 묶으면 나중에 그 사실을 잊고 한쪽만 바꿉니다).
#  ⚠️ 화면 파일에 이 숫자를 다시 적지 마세요(§0-3-10). 화면은 이 상수만 봅니다.

#: 순위표 위쪽에서 보여줄 최대 인원(5-7 "상위 500").
LEADERBOARD_TOP_COUNT = 500

#: 순위표 아래쪽에서 보여줄 최대 인원(5-7 "하위 500").
LEADERBOARD_BOTTOM_COUNT = 500

#: 한 페이지에 보여줄 행 수. 5-7 이 지목한 미국주식 화면의 기존 값과 같은 30 입니다
#: (`PROJECT_STATUS.md` §7 파일 지도 — `views/us_stocks_view.py` "30개 페이지네이션").
#: 이 저장소 안에서 확인한 값이라 새로 정한 숫자가 아닙니다(§0-1).
LEADERBOARD_PAGE_SIZE = 30


def leaderboard_page_bounds(page_index, *, page_size=None, section_cap=None):
    """
    페이지 번호(0부터) → 그 페이지가 읽어야 할 `(offset, limit)`. work order 5-7 참고.

    "상위 500"·"하위 500" 두 구간 **각각의 안에서만** 페이지가 넘어갑니다. 마지막 페이지가
    구간 상한(500)에 걸리면 `limit` 이 그만큼 줄어듭니다 — 501번째 행을 읽어 오는 경로
    자체를 만들지 않으려는 것입니다(화면에서 잘라내면 이미 읽어 온 뒤라 의미가 없습니다).

    반환 `(offset, limit)`. 그 페이지가 구간 밖이면 `limit` 이 0 입니다(질의를 보내지 말라는 뜻).

    ⚠️ 순위 자체는 여기서 계산하지 않습니다 — 배치가 이미 계산해 발행표에 저장한 `rank`
       컬럼을 읽기만 합니다(§0-3-2 / 5-7).
    """
    index = _require_int(page_index, "페이지 번호", minimum=0)
    size = _require_int(page_size if page_size is not None else LEADERBOARD_PAGE_SIZE,
                        "페이지 크기", minimum=1)
    cap = _require_int(section_cap if section_cap is not None else LEADERBOARD_TOP_COUNT,
                       "구간 상한", minimum=0)
    offset = index * size
    if offset >= cap:
        return offset, 0
    return offset, min(size, cap - offset)


def leaderboard_page_count(section_cap=None, *, page_size=None):
    """한 구간(상위/하위)이 최대 몇 페이지인가. 화면의 '다음' 버튼 한계 판정용."""
    size = _require_int(page_size if page_size is not None else LEADERBOARD_PAGE_SIZE,
                        "페이지 크기", minimum=1)
    cap = _require_int(section_cap if section_cap is not None else LEADERBOARD_TOP_COUNT,
                       "구간 상한", minimum=0)
    return (cap + size - 1) // size


# =============================================================================
# 11. USD 트랙 — 5-11 (2026-08-20, USD 트랙 2차 코딩 · 스키마는 이미 오너 확인 완료)
# =============================================================================
#  이 절 전체가 지키는 원칙(작업지시서 5-11, 오너가 이전 대화에서 확정): **KRW·USD 는
#  물리적으로 완전히 분리된 트랙**입니다 — 표도, 배치도, 워크플로도 따로입니다
#  (`sql/duel_schema.sql` §13 의 `_usd` 표들 및 이 파일의 header 참고). 그러나 "숫자만
#  다르고 로직은 같은" 순수 계산 함수들(체결·FIFO 배정·평단가 갱신·TWR·시즌 판정·순위
#  계산·닉네임 생성·재동의 차단·페이지네이션)은 **통화와 무관하게 이미 재사용 가능**해서
#  새로 만들지 않습니다 — 이 절에는 오직 "숫자 자체가 통화마다 다른" 것들만 옵니다.
#
#  ⚠️ 아래 상수도 위 0절과 같은 이유로 **다른 파일에 다시 적지 마세요**(§0-3-10).
#     `sql/duel_schema.sql` §14-10 의 `duel_seed_amount_usd()` 는 이 파일의
#     `SEED_AMOUNT_USD` 와 반드시 같은 값이어야 하고, 스키마 자체가 그 코멘트로
#     못박아 뒀습니다(§13-1 주석 참고) — 값을 바꿀 때는 **두 곳을 함께** 고치세요.

#: 계좌 개설 시 지급하는 가상 시드머니(달러). 오너 확정 $7,500 — `sql/duel_schema.sql`
#: `duel_seed_amount_usd()` 가 돌려주는 값과 반드시 같습니다(이미 프로덕션에 적용·확인됨).
SEED_AMOUNT_USD = 7500

#: 매월 정기 입금액(달러). KRW 와 같은 이유로 창 길이에 비례해 깎지 않습니다(5-11-4 —
#: "원화 트랙의 규칙을 그대로 재사용"이 `duel_cash_ledger_usd` 테이블 코멘트에 명시돼 있음).
MONTHLY_DEPOSIT_USD = 500

#: 정기 입금일은 원화 트랙과 **같은 날짜를 그대로 씁니다**(`MONTHLY_DEPOSIT_DAY`, 매월
#: 10일) — 통화가 달라도 "이번 달 몇 번째 날인가"는 달력 개념이지 금액 개념이 아니라서,
#: 따로 상수를 만들지 않았습니다. USD 전용 배치를 짤 때도 이 상수를 그대로 참조하세요.

#: ✅ USD 주문 접수 시간대(5-11-6) — **D일 KST 16:00:01~21:00:00, 양끝 포함**
#: (2026-08-20 오너 최종 확정 — KRW 트랙(`ORDER_WINDOW_OPEN_TIME` 18:00:01)과 **같은
#: 관례로, 정각에서 1초 뒤에 엽니다.** 처음엔 정각(16:00:00)으로 잠깐 바꿨다가, 역시
#: KRW 와 같은 관례가 낫다고 판단해 :01 로 다시 확정했습니다 — 두 트랙이 결국 같은
#: 규칙(정각+1초로 열어 경계 판정을 단순하게 만듦)을 공유합니다.
#: `sql/duel_schema.sql` 의 `duel_orders_usd` 테이블 코멘트("16:00~21:00")는 초 단위까지
#: 담고 있지 않으므로 이 상수가 그 초 단위의 단일 출처입니다(§0-3-10).
ORDER_WINDOW_OPEN_TIME_USD = time(16, 0, 1)
ORDER_WINDOW_CLOSE_TIME_USD = time(21, 0, 0)


def resolve_order_window_usd(now_kst):
    """
    USD 트랙의 주문 접수 시간대 판정. `resolve_order_window()` 와 **완전히 같은 로직**이고
    상수만 다릅니다(5-11-6) — 로직을 복제하면 나중에 한쪽만 고치는 사고가 나므로, 이 함수는
    `resolve_order_window()` 본체를 그대로 부르지 않고 **같은 판정을 상수만 바꿔 다시
    구현**했습니다. 이유: `resolve_order_window()` 는 전역 상수(`ORDER_WINDOW_OPEN_TIME` 등)를
    직접 참조하는 순수 함수라 상수를 인자로 받도록 시그니처를 바꾸면 KRW 쪽의 기존 호출부·
    테스트를 전부 건드리게 됩니다. 대신 판정 로직 자체(경계 포함 여부, D/D+1 계산)는 아래에서
    한 글자도 다르지 않게 맞춰 뒀습니다 — 둘 중 하나를 고치면 반드시 다른 쪽도 함께 고치세요
    (이 사실이 두 함수의 docstring 양쪽에 다 적혀 있습니다).

    돌려주는 dict 모양은 `resolve_order_window()` 와 동일합니다(`is_open` / `now_kst` /
    `submission_date` / `window_opens_at` / `window_closes_at`).
    """
    moment = _to_kst(now_kst, "현재 시각")
    today = moment.date()
    clock = moment.timetz().replace(tzinfo=None)

    if clock < ORDER_WINDOW_OPEN_TIME_USD:
        is_open, submission_date = False, today
    elif clock <= ORDER_WINDOW_CLOSE_TIME_USD:
        is_open, submission_date = True, today
    else:
        is_open, submission_date = False, today + timedelta(days=1)

    return {
        "is_open": is_open,
        "now_kst": moment,
        "submission_date": submission_date,
        "window_opens_at": datetime.combine(submission_date, ORDER_WINDOW_OPEN_TIME_USD, tzinfo=KST),
        "window_closes_at": datetime.combine(submission_date, ORDER_WINDOW_CLOSE_TIME_USD, tzinfo=KST),
    }


# ── 11-2. 체급(달러) — work order 5-11-9, KRW `BRACKET_TIERS`(10절)의 통화만 다른 미러 ──
#  경계값은 오너가 이전 대화에서 확정한 값입니다: $750 / $2,250 / $3,750 / $7,500 /
#  $22,500 / $45,000 / $75,000. 우연이 아니라 **KRW 구간과 정확히 같은 배율**입니다 —
#  KRW 는 100만원을 기준 단위로 100/60/30/10/5/3/1 배, USD 는 $750 을 기준 단위로 똑같이
#  100/60/30/10/5/3/1 배입니다(75000/750=100, 45000/750=60, 22500/750=30, 7500/750=10,
#  3750/750=5, 2250/750=3, 750/750=1) — 시드머니 비율($7,500 / 1,000만원 ≈ 1,333배)과는
#  무관하게, "체급 구간의 촘촘한 정도"를 KRW 와 같은 모양으로 맞춘 결과입니다.
#  ⚠️ KRW 표와 마찬가지로 **[하한 이상, 상한 미만)** 이고, key 는 화면 라벨이 아니라
#     DB 컬럼 값·유니크 제약의 일부이므로 ASCII 로 고정합니다.
BRACKET_TIERS_USD = (
    ("usd_75000_plus",   "$75,000 이상",                  75_000, None),
    ("usd_45000_75000",  "$45,000 이상 $75,000 미만",     45_000, 75_000),
    ("usd_22500_45000",  "$22,500 이상 $45,000 미만",     22_500, 45_000),
    ("usd_7500_22500",   "$7,500 이상 $22,500 미만",       7_500, 22_500),
    ("usd_3750_7500",    "$3,750 이상 $7,500 미만",        3_750, 7_500),
    ("usd_2250_3750",    "$2,250 이상 $3,750 미만",        2_250, 3_750),
    ("usd_750_2250",     "$750 이상 $2,250 미만",             750, 2_250),
    ("usd_under_750",    "$750 미만",                          0, 750),
)

#: USD 발행표에 실제로 나타날 수 있는 bracket_key 전부(위 8개 + 구간 미적용).
#: 구간 미적용 사유는 KRW 와 같습니다(`BRACKET_NONE_KEY`/`BRACKET_NONE_LABEL` 을 그대로
#: 공유합니다 — "구간을 못 정하는 이유"는 통화와 무관한 개념이라 새로 만들지 않았습니다).
BRACKET_KEYS_USD = tuple(tier[0] for tier in BRACKET_TIERS_USD) + (BRACKET_NONE_KEY,)

#: bracket_key(USD) → 화면 라벨.
BRACKET_LABELS_USD = dict(
    [(key, label) for key, label, _low, _high in BRACKET_TIERS_USD]
    + [(BRACKET_NONE_KEY, BRACKET_NONE_LABEL)]
)


def assign_bracket_usd(real_principal_usd):
    """
    실제 "내 성적표" 매입원가합계(달러) → 체급(bracket_key). `assign_bracket()` 의 통화만
    다른 미러입니다(5-11-9) — 검증 규칙(None·음수 거절)도 동일합니다.
    """
    amount = _require_number(real_principal_usd, "매입원가합계(USD)", allow_negative=False)
    for key, _label, low, high in BRACKET_TIERS_USD:
        if amount >= low and (high is None or amount < high):
            return key
    raise DuelRuleError(
        f"매입원가합계(USD) {amount} 에 해당하는 체급이 없습니다 — BRACKET_TIERS_USD 에 구멍이 있습니다."
    )


def bracket_label_usd(bracket_key):
    """bracket_key(USD) → 화면에 쓸 라벨. 모르는 키는 지어내지 않고 예외입니다."""
    key = str(bracket_key or "").strip()
    if key not in BRACKET_LABELS_USD:
        raise DuelRuleError(f"알 수 없는 체급 식별자(USD)입니다: {bracket_key!r}")
    return BRACKET_LABELS_USD[key]
