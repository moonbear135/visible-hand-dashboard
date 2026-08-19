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
