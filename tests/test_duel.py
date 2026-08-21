# tests/test_duel.py
"""
⚔️ "결투다!" 모듈 오프라인 검증 (네트워크 불필요 · Supabase 접속 불필요)

DUEL_MODULE_WORK_ORDER.md 4단계에 따라, `utils/duel_rules.py` 의 **순수 함수만** 합성
데이터로 검증합니다. `tests/test_scorecard.py` · `tests/test_scorecard_ocr.py` 의 오프라인
검증 컨벤션을 그대로 따릅니다(`pytest` 로 실행 가능한 `test_*` 함수 + `assert`).

검증 대상
    ① 체결 계산 — 전량체결 / 부분체결(사유 문구에 요청·실제 수량) / 1주도 못 사면 expired,
       잔돈이 현금으로 남는지
    ② 후행지표 원칙 회귀 — 그날 확정 종가가 없으면 **절대 체결되지 않고** 명확히 실패하는지
       (SCORECARD_V2_OCR_WORK_ORDER.md 가 "OCR 값이 현재가를 채우지 않는지"를 고정한 것과
        같은 목적 — 나중에 누가 실수로 넣으면 바로 잡히게)
    ③ 가용 현금 — 같은 계좌의 여러 pending 주문이 `saved_at` 빠른 순서대로 배정되고,
       **뒷 주문이 앞 주문 몫까지 넘보지 않는지**(회귀 고정)
    ④ 매수 창 개폐 — 예수금 경계(0원)
    ⑤ 주문 접수 시간대 — 18:00:01 / 22:00:00 앞뒤 경계
    ⑥ 체결 거래일(D+1) — 확정 거래일 목록을 인자로 받고, 근거가 없으면 날짜를 만들지 않는지
       (+ ⑥-USD: USD 트랙은 접수 시간대가 그날 미국장 **개장 전**이라 **당일 자신을 포함**
        한다는, 원화와 정반대 판정을 회귀 고정 — work order §5-16)
    ⑦ 크롤링 신선도 — 2-9 판정의 6가지 분기 전부 + 무변동 10개/11개 경계
    ⑧ TWR — 손으로 계산한 예시와 일치하는지, **입금이 있는 기간에 단순 수익률과 다른 값**이
       나오는지(둘이 같으면 TWR 이 안 걸린 것), 현금만 들고 있는 계좌가 0% 인지,
       상장폐지 상각(현금흐름 0인 평가손실)은 손실로 잡히는지
    ⑨ 매수 경로로는 수량이 줄지 않는지(매도는 아래 ⑪ 의 전용 함수만 줄일 수 있습니다)
    ⑩ 계층 분리 — `utils/duel_rules.py` 가 Supabase·네트워크·NiceGUI 를 import 하지 않는지
    ⑪ (2026-08-21 추가) 창당 1회 리밸런싱 매도 — 창 번호 경계값, 최초 보유일이 없으면 예외,
       매도 전량 체결·보유초과 거절, 매도 후 평단가 불변

⚠️ 이 파일은 어떤 파일도 수정하지 않고, 네트워크도 쓰지 않습니다. 저장소의 실제 파일은
   ⑩ 의 소스 검사에서 **읽기만** 합니다.

실행: pytest tests/test_duel.py -v
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

from utils import duel_rules as rules  # noqa: E402
from utils.duel_rules import (  # noqa: E402
    CRAWL_FAILED,
    CRAWL_FAILED_OR_HOLIDAY,
    CRAWL_NEEDS_REVIEW,
    CRAWL_OK,
    KST,
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_FILLED,
    ORDER_PARTIALLY_FILLED,
    TWR_INSUFFICIENT,
    TWR_NO_DATA,
    TWR_OK,
    DuelRuleError,
    allocate_pending_orders,
    apply_buy_fill_to_position,
    apply_sell_fill_to_position,
    calculate_fill,
    calculate_sell_fill,
    check_crawl_freshness,
    compute_twr,
    crawl_status_allows_fill,
    is_buy_window_open,
    resolve_fill_trading_day,
    resolve_fill_trading_day_usd,
    resolve_order_window,
    resolve_rebalance_window,
)


# =============================================================================
# ① 체결 계산 (work order 1-3 / 2-4-6)
# =============================================================================
def test_fill_full_when_cash_is_enough():
    """요청 수량 × 종가가 예수금 이내면 전량 체결되고, 잔돈은 현금으로 남습니다."""
    result = calculate_fill(requested_quantity=10, close_price=70_000, available_cash=1_000_000)
    assert result["status"] == ORDER_FILLED
    assert result["filled_quantity"] == 10
    assert result["filled_amount"] == 700_000
    # 잔돈 30만원이 사라지지 않고 현금으로 남아야 합니다(다음 매수에 쓰입니다).
    assert result["remaining_cash"] == 300_000
    # 전량 체결에는 실패 사유가 없어야 합니다(있으면 화면이 괜한 경고를 띄웁니다).
    assert result["fail_reason"] is None


def test_fill_partial_keeps_the_order_and_says_both_numbers():
    """
    예수금이 모자라면 **주문 전체를 취소하지 않고** floor(가용현금/종가) 만큼만 체결하고,
    사유 문구에 요청 수량과 실제 체결 수량이 **둘 다** 남아야 합니다(§0-1 — 조용히 다른
    결과를 주지 않기). 작업지시서 1-3 의 예시 문구가 "요청 10주 중 7주만 …" 입니다.
    """
    result = calculate_fill(requested_quantity=10, close_price=70_000, available_cash=500_000)
    assert result["status"] == ORDER_PARTIALLY_FILLED
    assert result["filled_quantity"] == 7            # floor(500,000 / 70,000) = 7
    assert result["filled_amount"] == 490_000
    assert result["remaining_cash"] == 10_000
    reason = result["fail_reason"]
    assert reason is not None
    assert "요청 10주 중 7주만 예수금 부족으로 체결" in reason, reason
    # 요청값과 실제값이 둘 다 문구에 있어야 화면이 그대로 보여줄 수 있습니다.
    assert "10" in reason and "7" in reason


def test_fill_expired_when_not_even_one_share():
    """1주 가격에도 못 미치면 expired 이고, 사유 문구가 반드시 남습니다(§0-1)."""
    result = calculate_fill(requested_quantity=3, close_price=70_000, available_cash=50_000)
    assert result["status"] == ORDER_EXPIRED
    assert result["filled_quantity"] == 0
    assert result["filled_amount"] == 0
    # 체결이 없었으니 예수금은 한 푼도 줄지 않아야 합니다.
    assert result["remaining_cash"] == 50_000
    assert result["fail_reason"] and "1주" in result["fail_reason"]


def test_fill_share_count_is_not_flipped_by_binary_rounding():
    """
    정수 주식 수가 2진 반올림 부스러기 때문에 한 주 줄어드는 일이 없어야 합니다.
    (0.1 × 3 이 float 에서 0.30000000000000004 가 되는 종류의 사고를 고정합니다.)
    """
    result = calculate_fill(requested_quantity=3, close_price=0.1, available_cash=0.3)
    assert result["filled_quantity"] == 3, "십진수로 나누지 않으면 여기서 2주가 됩니다"
    assert result["status"] == ORDER_FILLED


# =============================================================================
# ② 후행지표 원칙 회귀 — 종가가 없으면 절대 체결하지 않는다 (§0-1 / §0-3-1)
# =============================================================================
@pytest.mark.parametrize("bad_price", [None, 0, -1, "", "몰라"])
def test_fill_refuses_to_run_without_a_confirmed_close_price(bad_price):
    """
    🔴 회귀 고정 — 그날 확정 종가가 없는 상태로 체결 함수를 부르면 **체결되지 않고**
    명확한 실패가 나야 합니다. 나중에 누가 "일단 전일 종가로라도" 를 넣으면 여기서 잡힙니다.
    """
    with pytest.raises(DuelRuleError):
        calculate_fill(requested_quantity=1, close_price=bad_price, available_cash=1_000_000)


def test_fill_refuses_missing_cash_instead_of_assuming_zero():
    """예수금을 모르는 것과 예수금이 0인 것은 다릅니다 — 전자를 후자로 바꿔 처리하지 않습니다."""
    with pytest.raises(DuelRuleError):
        calculate_fill(requested_quantity=1, close_price=70_000, available_cash=None)


# =============================================================================
# ③ 가용 현금 FIFO 배정 (work order 2-4-6) — 4단계가 회귀 고정을 요구한 항목
# =============================================================================
def _order(order_id, ticker, quantity, saved_at):
    return {"id": order_id, "ticker": ticker, "requested_quantity": quantity, "saved_at": saved_at}


def test_pending_orders_are_filled_in_saved_at_order_without_double_spending():
    """
    같은 계좌에 pending 주문이 여러 건이면 **saved_at 빠른 순서대로** 예수금을 배정하고,
    뒷 주문이 앞 주문 몫까지 넘보면 안 됩니다.

    예수금 1,000,000원 / 종가 A=300,000 · B=40,000 · C=50,000
        1) 18:05 A 3주 → 900,000  전량체결, 남은 돈 100,000
        2) 18:15 B 3주 → 120,000 필요하지만 100,000뿐 → 2주 부분체결, 남은 돈 20,000
        3) 18:25 C 1주 → 50,000 필요하지만 20,000뿐 → 체결 0주(expired)
    입력 순서를 일부러 뒤섞어 넣어도 결과가 같아야 합니다.
    """
    prices = {"A": 300_000, "B": 40_000, "C": 50_000}
    orders = [
        _order("o3", "C", 1, "2026-08-19T18:25:00+09:00"),
        _order("o1", "A", 3, "2026-08-19T18:05:00+09:00"),
        _order("o2", "B", 3, "2026-08-19T18:15:00+09:00"),
    ]

    results = allocate_pending_orders(1_000_000, orders, prices)

    assert [row["id"] for row in results] == ["o1", "o2", "o3"], "saved_at 순으로 처리돼야 합니다"

    assert results[0]["status"] == ORDER_FILLED
    assert results[0]["filled_quantity"] == 3
    assert results[0]["cash_after"] == 100_000

    assert results[1]["status"] == ORDER_PARTIALLY_FILLED
    assert results[1]["filled_quantity"] == 2, "앞 주문이 이미 쓴 돈을 다시 쓰면 3주가 됩니다"
    assert results[1]["cash_after"] == 20_000

    assert results[2]["status"] == ORDER_EXPIRED
    assert results[2]["filled_quantity"] == 0
    assert results[2]["cash_after"] == 20_000

    # 🔴 이중 지출 회귀 고정 — 총 체결금액이 시작 예수금을 절대 넘지 않아야 합니다.
    spent = sum(row["filled_amount"] for row in results)
    assert spent == 980_000
    assert spent <= 1_000_000


def test_ties_on_saved_at_keep_input_order_so_the_batch_is_repeatable():
    """초 단위까지 같은 주문이 있어도 결과가 흔들리면 안 됩니다(배치 두 번 = 같은 결과)."""
    same_time = "2026-08-19T18:05:00+09:00"
    orders = [_order("first", "A", 2, same_time), _order("second", "A", 2, same_time)]
    results = allocate_pending_orders(300_000, orders, {"A": 100_000})
    assert [row["id"] for row in results] == ["first", "second"]
    assert results[0]["filled_quantity"] == 2      # 200,000 사용
    assert results[1]["filled_quantity"] == 1      # 남은 100,000 으로 1주만


def test_order_is_cancelled_not_guessed_when_the_close_price_is_missing():
    """
    귀속 거래일의 확정 종가를 확보하지 못한 종목은 **취소**로 남기고 예수금을 건드리지
    않습니다(2-4-5 — 이월하지 않고 사유를 남겨 실패 확정). 0원이나 전일 종가로 체결하지 않습니다.
    """
    orders = [_order("o1", "없는종목", 1, "2026-08-19T18:05:00+09:00")]
    results = allocate_pending_orders(1_000_000, orders, {"A": 100})
    assert results[0]["status"] == ORDER_CANCELLED
    assert results[0]["filled_quantity"] == 0
    assert results[0]["cash_after"] == 1_000_000
    assert "확정 종가" in results[0]["fail_reason"]


def test_no_pending_orders_is_a_normal_empty_result_not_an_error():
    """주문이 없는 날은 오류가 아니라 정상입니다(계좌 대부분이 대부분의 날에 이 상태)."""
    assert allocate_pending_orders(1_000_000, [], {"A": 100}) == []


# =============================================================================
# ④ 매수 창 개폐 (work order 2-3)
# =============================================================================
def test_buy_window_is_exactly_the_cash_boundary():
    """창 길이는 사실상 무제한이고, 판정은 '가용 현금 > 0' 하나로 줄어듭니다."""
    assert is_buy_window_open(1) is True
    assert is_buy_window_open(0.000001) is True
    assert is_buy_window_open(0) is False, "예수금 0원이면 다음 입금 전까지 매수 불가"
    assert is_buy_window_open(-1) is False


def test_buy_window_refuses_unknown_cash_instead_of_saying_closed():
    """'잔고를 모른다'를 '잔고가 0이다'로 바꿔 표시하면 §0-1 위반입니다."""
    with pytest.raises(DuelRuleError):
        is_buy_window_open(None)


# =============================================================================
# ⑤ 주문 접수 시간대 경계 (work order 2-4-1) — D일 18:00:01 ~ 22:00:00
# =============================================================================
def _kst(year, month, day, hour, minute, second):
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def test_order_window_is_closed_just_before_it_opens():
    """17:59:59 · 18:00:00 은 아직 닫혀 있습니다(창은 18:00:01 부터)."""
    for moment in (_kst(2026, 8, 19, 17, 59, 59), _kst(2026, 8, 19, 18, 0, 0)):
        window = resolve_order_window(moment)
        assert window["is_open"] is False, moment
        # 오늘 저녁 창을 안내해야 합니다(내일로 넘기면 안 됩니다).
        assert window["submission_date"] == date(2026, 8, 19)
        assert window["window_opens_at"] == _kst(2026, 8, 19, 18, 0, 1)


def test_order_window_is_open_at_both_ends():
    """18:00:01 과 22:00:00 은 **양끝 포함**으로 열려 있어야 합니다."""
    for moment in (_kst(2026, 8, 19, 18, 0, 1),
                   _kst(2026, 8, 19, 20, 30, 0),
                   _kst(2026, 8, 19, 22, 0, 0)):
        window = resolve_order_window(moment)
        assert window["is_open"] is True, moment
        assert window["submission_date"] == date(2026, 8, 19)


def test_order_window_rolls_to_the_next_day_after_it_closes():
    """22:00:01 부터는 닫히고, 다음 창(다음 날 18:00:01)으로 안내해야 합니다."""
    window = resolve_order_window(_kst(2026, 8, 19, 22, 0, 1))
    assert window["is_open"] is False
    assert window["submission_date"] == date(2026, 8, 20)
    assert window["window_opens_at"] == _kst(2026, 8, 20, 18, 0, 1)
    assert window["window_closes_at"] == _kst(2026, 8, 20, 22, 0, 0)


def test_order_window_treats_naive_time_as_kst_not_utc():
    """타임존 없는 값을 UTC 로 가정하면 판정이 9시간 어긋납니다 — KST 로 해석해야 합니다."""
    assert resolve_order_window(datetime(2026, 8, 19, 19, 0, 0))["is_open"] is True


def test_order_window_converts_an_aware_utc_timestamp_into_kst():
    """DB 가 UTC(+00:00)로 돌려주는 시각도 KST 로 변환해 판정해야 합니다."""
    # 2026-08-19 10:00 UTC = 2026-08-19 19:00 KST → 접수 시간대 안
    window = resolve_order_window("2026-08-19T10:00:00+00:00")
    assert window["is_open"] is True
    assert window["submission_date"] == date(2026, 8, 19)


# =============================================================================
# ⑤-USD USD 트랙 주문 접수 시간대 (work order 5-11-6) — KRW 경계 검증의 통화만 다른 미러
#  ✅ 2026-08-20 오너 최종 확정: USD 는 **16:00:01~21:00:00** — KRW(18:00:01~22:00:00)와
#  **같은 관례(정각에서 1초 뒤에 열림)**입니다. 중간에 정각(16:00:00)으로 잠깐 바꿨다가,
#  다시 KRW 와 같은 :01 관례로 확정했습니다(`utils/duel_rules.py` §11 주석 참고).
# =============================================================================
def test_order_window_usd_is_closed_just_before_it_opens():
    """15:59:59 · 16:00:00 은 아직 닫혀 있습니다(창은 16:00:01 부터)."""
    for moment in (_kst(2026, 8, 19, 15, 59, 59), _kst(2026, 8, 19, 16, 0, 0)):
        window = rules.resolve_order_window_usd(moment)
        assert window["is_open"] is False, moment
        assert window["submission_date"] == date(2026, 8, 19)
        assert window["window_opens_at"] == _kst(2026, 8, 19, 16, 0, 1)


def test_order_window_usd_is_open_at_both_ends():
    """16:00:01 과 21:00:00 은 **양끝 포함**으로 열려 있어야 합니다."""
    for moment in (_kst(2026, 8, 19, 16, 0, 1),
                   _kst(2026, 8, 19, 18, 30, 0),
                   _kst(2026, 8, 19, 21, 0, 0)):
        window = rules.resolve_order_window_usd(moment)
        assert window["is_open"] is True, moment
        assert window["submission_date"] == date(2026, 8, 19)


def test_order_window_usd_rolls_to_the_next_day_after_it_closes():
    """21:00:01 부터는 닫히고, 다음 창(다음 날 16:00:01)으로 안내해야 합니다."""
    window = rules.resolve_order_window_usd(_kst(2026, 8, 19, 21, 0, 1))
    assert window["is_open"] is False
    assert window["submission_date"] == date(2026, 8, 20)
    assert window["window_opens_at"] == _kst(2026, 8, 20, 16, 0, 1)
    assert window["window_closes_at"] == _kst(2026, 8, 20, 21, 0, 0)


def test_order_window_usd_does_not_share_state_with_the_krw_window():
    """
    🔴 같은 순간이 KRW 창은 닫혀 있고 USD 창은 열려 있을 수 있어야 합니다(두 상수 세트가
    실제로 분리돼 있는지 — 전역 변수를 헷갈려 뒤섞어 쓰면 이 테스트가 잡습니다).
    """
    moment = _kst(2026, 8, 19, 17, 0, 0)          # KRW: 18:00:01 전 → 닫힘 / USD: 창 안 → 열림
    assert resolve_order_window(moment)["is_open"] is False
    assert rules.resolve_order_window_usd(moment)["is_open"] is True


def test_order_window_usd_and_krw_share_the_same_one_second_offset_convention():
    """
    🔴 KRW·USD 둘 다 **정각에서 1초 뒤**에 열립니다(오너 최종 확정) — 우연이 아니라 같은
    관례를 공유하기로 한 것이라, 두 상수의 "초" 값이 우연히도 아니라 항상 1로 같은지
    회귀 고정합니다. 나중에 누가 둘 중 하나만 고치면 이 테스트가 잡습니다.
    """
    assert rules.ORDER_WINDOW_OPEN_TIME_USD.second == rules.ORDER_WINDOW_OPEN_TIME.second == 1


# =============================================================================
# ⑥ 체결 거래일(D+1) 확정 (work order 2-4)
# =============================================================================
def test_fill_trading_day_is_the_next_confirmed_trading_day_not_the_next_calendar_day():
    """
    금요일 저녁에 넣은 주문은 토·일을 건너뛰고 **월요일** 종가로 체결돼야 합니다.
    그 판정 근거는 이 함수가 만드는 게 아니라 **호출부가 준 확정 거래일 목록**입니다
    (거래일 캘린더를 코드에 넣지 않기 — §0-1).
    """
    trading_days = {date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 24)}
    assert resolve_fill_trading_day("2026-08-21T19:00:00+09:00", trading_days) == date(2026, 8, 24)
    # D 자신은 후보가 아닙니다(D 종가는 이미 알려진 값이라 체결에 쓰면 안 됩니다).
    assert resolve_fill_trading_day(date(2026, 8, 19), trading_days) == date(2026, 8, 20)


def test_fill_trading_day_refuses_to_invent_a_date():
    """목록에 근거가 없으면 '아마 내일'로 넘기지 않고 실패해야 합니다."""
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day(date(2026, 8, 24), {date(2026, 8, 19), date(2026, 8, 24)})
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day(date(2026, 8, 19), set())
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day(date(2026, 8, 19), None)


# =============================================================================
# ⑥-USD 체결 거래일 확정 — USD 트랙 (work order 5-11-6 / 5-13 / 5-16)
#  🔴 원화와 **판정 방향이 정반대**인, 이 트랙에서 유일하게 "규칙 자체가 갈라진" 함수입니다.
#     원화 접수 시간대(18:00:01~22:00:00 KST)는 그날 종가가 **이미 확정된 뒤**라 그날 자신을
#     빼야 공정하지만, USD 접수 시간대(16:00:01~21:00:00 KST = 03:00~08:00 ET)는 그날 미국장이
#     **열리기도 전**이라 그날 마감가가 아직 존재하지 않습니다 — 뺄 이유가 없습니다.
#     (2026-08-21 오너가 미국장 개장/마감 시간대를 직접 짚어보다 발견한 실제 버그의 회귀 고정.)
# =============================================================================
def test_fill_trading_day_usd_is_the_saved_day_itself_when_it_is_a_confirmed_trading_day():
    """
    (a) 저장일 자신이 확정 거래일 목록에 있으면 **그날 자신**이 체결 거래일입니다.
        원화 함수처럼 하루 건너뛰면 체결이 근거 없이 하루 늦어집니다(§5-16).
    """
    trading_days = {date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)}
    assert resolve_fill_trading_day_usd(date(2026, 8, 19), trading_days) == date(2026, 8, 19)
    # 시각이 붙어 있어도(접수 시간대 한가운데) 판정은 날짜 단위로 같아야 합니다.
    assert resolve_fill_trading_day_usd(
        "2026-08-19T18:30:00+09:00", trading_days) == date(2026, 8, 19)
    # 접수 시간대의 양끝(16:00:01 · 21:00:00)에서도 마찬가지입니다.
    assert resolve_fill_trading_day_usd(
        _kst(2026, 8, 19, 16, 0, 1), trading_days) == date(2026, 8, 19)
    assert resolve_fill_trading_day_usd(
        _kst(2026, 8, 19, 21, 0, 0), trading_days) == date(2026, 8, 19)


def test_fill_trading_day_usd_skips_to_the_next_day_when_the_saved_day_is_not_a_trading_day():
    """
    (b) 저장일이 후보 목록에 없으면(미국 휴장일 등) **그 이후 가장 이른 확정 거래일**입니다.
        "그날 자신을 포함한다"가 "무조건 그날을 돌려준다"는 뜻이 아님을 고정합니다.
    """
    # 2026-08-22(토)·23(일)은 목록에 없습니다 → 다음 확정 거래일 8/24(월).
    trading_days = {date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 24)}
    assert resolve_fill_trading_day_usd(date(2026, 8, 22), trading_days) == date(2026, 8, 24)
    # 추수감사절처럼 평일이 통째로 빠진 경우도 같은 방식으로 흡수됩니다.
    holiday_calendar = {date(2026, 11, 25), date(2026, 11, 27)}   # 11/26(목) 휴장
    assert resolve_fill_trading_day_usd(
        date(2026, 11, 26), holiday_calendar) == date(2026, 11, 27)


def test_fill_trading_day_usd_refuses_to_invent_a_date():
    """
    (c) 근거가 없으면 '아마 오늘'로 넘기지 않고 실패해야 합니다(§0-1) — 원화 함수와
        **완전히 같은** 예외 처리입니다. 당일 포함 규칙이 "목록이 없어도 오늘을 쓴다"는
        뜻으로 잘못 구현되면 이 테스트가 잡습니다.
    """
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day_usd(date(2026, 8, 19), None)
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day_usd(date(2026, 8, 19), set())
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day_usd(date(2026, 8, 19), [])
    # 목록에 저장일 이후가 하나도 없으면(전부 과거) 역시 날짜를 만들지 않습니다.
    with pytest.raises(DuelRuleError):
        resolve_fill_trading_day_usd(date(2026, 8, 25), {date(2026, 8, 19), date(2026, 8, 24)})


def test_fill_trading_day_usd_and_krw_deliberately_disagree_on_the_saved_day():
    """
    (d) 🔴 **두 함수가 다르다는 것을 고정하는 회귀 테스트.**
        `test_order_window_usd_and_krw_share_the_same_one_second_offset_convention`
        (두 트랙이 **같음**을 고정)과 정반대 성격입니다 — 여기서는 **정확히 같은 입력**에
        두 함수가 **다른 답**을 내야 한다는 것이 요구사항입니다.

        누군가 USD 호출부를 원화 함수로 되돌리거나, USD 함수 본문을 원화처럼
        `day > saved_date` 로 고치면 이 테스트가 즉시 잡습니다.
    """
    saved_date = date(2026, 8, 19)
    trading_days = {date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)}

    krw_answer = resolve_fill_trading_day(saved_date, trading_days)
    usd_answer = resolve_fill_trading_day_usd(saved_date, trading_days)

    assert krw_answer == date(2026, 8, 20), "원화는 그날 자신을 제외합니다(그날 종가는 이미 알려진 값)"
    assert usd_answer == date(2026, 8, 19), "USD 는 그날 자신을 포함합니다(그날 미국장은 아직 열리지도 않음)"
    assert usd_answer != krw_answer, "두 트랙의 판정이 같아졌습니다 — 한쪽이 잘못 고쳐졌습니다"
    assert usd_answer < krw_answer, "USD 가 원화보다 하루 이르게 체결돼야 합니다"

    # 두 함수는 물리적으로도 다른 객체여야 합니다(별칭으로 묶어두면 위 차이가 사라집니다).
    assert rules.resolve_fill_trading_day_usd is not rules.resolve_fill_trading_day

    # 반대로, 저장일이 거래일이 **아닌** 날에는 두 함수의 답이 자연히 같아집니다
    # (제외할 당일 자체가 후보에 없으므로) — 차이는 오직 "당일 포함 여부" 하나뿐임을 고정.
    off_day = date(2026, 8, 22)
    assert resolve_fill_trading_day_usd(off_day, {date(2026, 8, 21), date(2026, 8, 24)}) \
        == resolve_fill_trading_day(off_day, {date(2026, 8, 21), date(2026, 8, 24)}) \
        == date(2026, 8, 24)


def test_usd_track_call_site_uses_the_usd_fill_day_function_not_the_krw_one():
    """
    🔴 함수를 새로 만들어놓고 **호출부를 안 바꾸면** 버그는 그대로 남습니다. USD 주문
    저장 경로(`utils/duel_db_usd.py::save_order_usd()`)가 실제로 `_usd` 함수를 부르는지
    소스로 직접 대조합니다(원화 파일 `utils/duel_db.py` 는 반대로 원화 함수를 그대로
    유지해야 합니다 — 이번 수정은 원화 트랙을 건드리지 않습니다).
    """
    usd_source = (REPO_ROOT / "utils" / "duel_db_usd.py").read_text(encoding="utf-8")
    assert "duel_rules.resolve_fill_trading_day_usd(moment, trading_days)" in usd_source
    assert "duel_rules.resolve_fill_trading_day(moment, trading_days)" not in usd_source

    krw_source = (REPO_ROOT / "utils" / "duel_db.py").read_text(encoding="utf-8")
    assert "duel_rules.resolve_fill_trading_day(moment, trading_days)" in krw_source
    assert "resolve_fill_trading_day_usd" not in krw_source


# =============================================================================
# ⑦ 크롤링 신선도 판정 (work order 2-9) — 6가지 분기 전부 + 10/11 경계
# =============================================================================
INDEX_KEYS = ("KOSPI", "KOSDAQ")


def _price_pair(*, indices_changed, unchanged_stock_count, stock_count=50):
    """
    (오늘, 전일) 종가 dict 한 쌍을 만듭니다.
      indices_changed        : 지수 2개가 전일 대비 움직였는지
      unchanged_stock_count  : 50종목 중 무변동으로 둘 종목 수
    """
    yesterday = {"KOSPI": 3000.0, "KOSDAQ": 900.0}
    today = {"KOSPI": 3010.0 if indices_changed else 3000.0,
             "KOSDAQ": 905.0 if indices_changed else 900.0}
    for i in range(stock_count):
        ticker = f"{i:06d}"
        yesterday[ticker] = 10_000 + i
        today[ticker] = yesterday[ticker] if i < unchanged_stock_count else yesterday[ticker] + 100
    return today, yesterday


def test_crawl_all_52_unchanged_is_failure_or_holiday():
    """분기①: 52개 전부 무변동 → 수집 실패이거나 휴장일(굳이 구분하지 않습니다)."""
    today, yesterday = _price_pair(indices_changed=False, unchanged_stock_count=50)
    assert check_crawl_freshness(today, yesterday) == CRAWL_FAILED_OR_HOLIDAY


def test_crawl_all_stocks_moved_but_no_index_moved_is_failure():
    """분기②: 50종목이 전부 움직였는데 지수가 둘 다 그대로 → 앞뒤가 안 맞는 상태(실패)."""
    today, yesterday = _price_pair(indices_changed=False, unchanged_stock_count=0)
    assert check_crawl_freshness(today, yesterday) == CRAWL_FAILED


def test_crawl_some_stocks_moved_but_no_index_moved_is_failure():
    """분기③: 종목이 일부만 움직였는데 지수가 무변동인 것도 같은 이유로 실패입니다."""
    today, yesterday = _price_pair(indices_changed=False, unchanged_stock_count=25)
    assert check_crawl_freshness(today, yesterday) == CRAWL_FAILED


def test_crawl_index_moved_but_every_stock_frozen_is_failure():
    """분기④: 지수는 움직였는데 50종목이 통째로 멈춤 → 부분 실패(허용치의 극단)."""
    today, yesterday = _price_pair(indices_changed=True, unchanged_stock_count=50)
    assert check_crawl_freshness(today, yesterday) == CRAWL_FAILED


@pytest.mark.parametrize("unchanged", [0, 1, 9, 10])
def test_crawl_up_to_ten_unchanged_stocks_is_ok(unchanged):
    """분기⑤: 무변동 종목 10개까지는 정상(유동성이 낮은 날엔 실제로 안 움직입니다)."""
    today, yesterday = _price_pair(indices_changed=True, unchanged_stock_count=unchanged)
    assert check_crawl_freshness(today, yesterday) == CRAWL_OK


@pytest.mark.parametrize("unchanged", [11, 30, 49])
def test_crawl_eleven_or_more_unchanged_needs_a_human(unchanged):
    """분기⑥: 11개 이상이면 자동으로 실패를 확정하지 않고 관리자 확인으로 넘깁니다."""
    today, yesterday = _price_pair(indices_changed=True, unchanged_stock_count=unchanged)
    assert check_crawl_freshness(today, yesterday) == CRAWL_NEEDS_REVIEW


def test_crawl_boundary_is_exactly_ten_versus_eleven():
    """🔴 경계 고정 — 10개는 ok, 11개는 needs_review. 이 한 칸이 바뀌면 바로 잡힙니다."""
    ten_today, ten_yesterday = _price_pair(indices_changed=True, unchanged_stock_count=10)
    eleven_today, eleven_yesterday = _price_pair(indices_changed=True, unchanged_stock_count=11)
    assert check_crawl_freshness(ten_today, ten_yesterday) == CRAWL_OK
    assert check_crawl_freshness(eleven_today, eleven_yesterday) == CRAWL_NEEDS_REVIEW


def test_crawl_refuses_to_count_a_missing_value_as_unchanged():
    """
    값이 하나라도 없으면 판정하지 않고 실패해야 합니다. '없는 값 = 무변동'으로 세면
    수집 실패를 정상으로 넘겨 버립니다(§0-1).
    """
    today, yesterday = _price_pair(indices_changed=True, unchanged_stock_count=0)
    broken = dict(today)
    broken["000000"] = None
    with pytest.raises(DuelRuleError):
        check_crawl_freshness(broken, yesterday)

    del broken["000000"]
    with pytest.raises(DuelRuleError):
        check_crawl_freshness(broken, yesterday)   # 키 집합 자체가 달라진 경우


def test_crawl_refuses_a_partial_universe():
    """50종목이 아니라 몇 종목만 보고 그날 수집 성패를 판정하지 않습니다."""
    today, yesterday = _price_pair(indices_changed=True, unchanged_stock_count=0, stock_count=7)
    with pytest.raises(DuelRuleError):
        check_crawl_freshness(today, yesterday)
    # 다른 모듈이 재사용할 때는 대상 수를 명시해서 쓸 수 있어야 합니다(§0-3-10).
    assert check_crawl_freshness(today, yesterday, expected_stock_count=7) == CRAWL_OK


def test_only_ok_allows_the_batch_to_fill_orders():
    """'needs_review' 는 '아마 괜찮을 것'이 아닙니다 — 자동 체결로 기울면 안 됩니다."""
    assert crawl_status_allows_fill(CRAWL_OK) is True
    assert crawl_status_allows_fill(CRAWL_NEEDS_REVIEW) is False
    assert crawl_status_allows_fill(CRAWL_FAILED) is False
    assert crawl_status_allows_fill(CRAWL_FAILED_OR_HOLIDAY) is False
    with pytest.raises(DuelRuleError):
        crawl_status_allows_fill("아마도")


# =============================================================================
# ⑧ TWR (work order 2-6)
# =============================================================================
def _snap(day, total_value, cash_flow=0):
    return {"snapshot_date": day, "total_value": total_value, "cash_flow_amount": cash_flow}


def test_twr_matches_a_hand_computed_example_with_a_flow_day_and_a_no_flow_day():
    """
    손으로 계산한 예시와 정확히 맞아야 합니다.

        0일차 8/10 : V=10,000,000  F=10,000,000(시드)  ← 시작점, 구간에 넣지 않음
        1일차 8/11 : V=10,500,000  F=0
                     r1 = 10,500,000 / 10,000,000 − 1 = +5.0%
        2일차 8/12 : V=11,500,000  F=800,000(정기입금)
                     r2 = (11,500,000 − 800,000) / 10,500,000 − 1 = +1.904761…%
        TWR = 1.05 × (10,700,000 / 10,500,000) − 1 = +7.0%
    """
    snapshots = [
        _snap("2026-08-10", 10_000_000, 10_000_000),
        _snap("2026-08-11", 10_500_000, 0),
        _snap("2026-08-12", 11_500_000, 800_000),
    ]
    result = compute_twr(snapshots)
    assert result["status"] == TWR_OK
    assert result["twr_pct"] == pytest.approx(7.0, abs=1e-9)
    assert result["period_count"] == 2, "0일차는 구간이 아닙니다"
    assert result["baseline_date"] == date(2026, 8, 10)
    assert result["end_date"] == date(2026, 8, 12)


def test_twr_differs_from_the_naive_simple_return_when_a_deposit_lands_mid_period():
    """
    🔴 이 파일에서 가장 중요한 회귀 테스트 — 작업지시서가 지목한 "단순 수익률 버그"를
    막습니다. 기간 중 입금이 있으면 TWR 과 단순 수익률이 **반드시 달라야** 합니다.
    둘이 같게 나오면 TWR 이 안 걸린 것(= 입금을 성과로 착각하는 상태)입니다.
    """
    snapshots = [
        _snap("2026-08-10", 10_000_000, 10_000_000),
        _snap("2026-08-11", 10_500_000, 0),
        _snap("2026-08-12", 11_500_000, 800_000),
    ]
    twr = compute_twr(snapshots)["twr_pct"]
    naive_simple_return = (11_500_000 / 10_000_000 - 1) * 100    # = 15.0%

    assert naive_simple_return == pytest.approx(15.0)
    assert twr == pytest.approx(7.0, abs=1e-9)
    assert twr != pytest.approx(naive_simple_return), "TWR 이 입금을 성과로 세고 있습니다"
    assert twr < naive_simple_return


def test_cash_only_account_earns_zero_percent_not_the_deposit_amount():
    """
    아무것도 안 사고 현금으로만 들고 있는 계좌는 **0%** 여야 합니다.
    단순 수익률이라면 입금액만큼 +8% 로 보일 시나리오입니다(작업지시서 2-6 의 예시).
    """
    snapshots = [
        _snap("2026-08-10", 10_000_000, 10_000_000),
        _snap("2026-09-09", 10_000_000, 0),
        _snap("2026-09-10", 10_800_000, 800_000),
    ]
    result = compute_twr(snapshots)
    assert result["twr_pct"] == pytest.approx(0.0, abs=1e-9)
    naive = (10_800_000 / 10_000_000 - 1) * 100
    assert naive == pytest.approx(8.0)


def test_valuation_loss_hits_twr_but_a_real_deposit_does_not_inflate_it():
    """
    상장폐지 상각처럼 **현금흐름 0인 순수 평가손실**은 TWR 에 손실로 그대로 잡히고,
    같은 금액대의 **실제 입금**은 TWR 을 부풀리지 않아야 합니다(3-1 / 2-6).
    두 시나리오는 마지막 날 총자산만 다르고 구조가 같습니다.
    """
    base = [_snap("2026-08-10", 10_000_000, 10_000_000), _snap("2026-08-11", 10_000_000, 0)]

    # (가) 보유 종목이 상장폐지로 100% 상각 — cash_flow_amount 는 0
    write_down = compute_twr(base + [_snap("2026-08-12", 9_000_000, 0)])
    assert write_down["twr_pct"] == pytest.approx(-10.0, abs=1e-9)

    # (나) 정기 입금 80만원 — 총자산은 늘었지만 성과는 0
    deposit = compute_twr(base + [_snap("2026-08-12", 10_800_000, 800_000)])
    assert deposit["twr_pct"] == pytest.approx(0.0, abs=1e-9)

    # 단순 수익률이었다면 (나)가 +8% 로 보였을 자리입니다.
    assert deposit["twr_pct"] < (10_800_000 / 10_000_000 - 1) * 100


def test_twr_says_no_data_and_insufficient_instead_of_returning_zero():
    """
    스냅샷이 없거나 개설일 하나뿐일 때 **0.0% 를 돌려주면 거짓말**입니다.
    상태와 None 으로 정직하게 알려야 화면이 '데이터 부족'을 표시할 수 있습니다(§0-1).
    """
    empty = compute_twr([])
    assert empty["status"] == TWR_NO_DATA and empty["twr_pct"] is None

    only_day_zero = compute_twr([_snap("2026-08-10", 10_000_000, 10_000_000)])
    assert only_day_zero["status"] == TWR_INSUFFICIENT
    assert only_day_zero["twr_pct"] is None
    assert only_day_zero["period_count"] == 0


def test_twr_refuses_a_snapshot_without_cash_flow_instead_of_assuming_zero():
    """
    🔴 `cash_flow_amount` 를 0 으로 기본값 처리하면 입금을 수익으로 착각합니다.
    없으면 계산하지 않고 실패해야 합니다(이 컬럼이 스키마 1단계에 들어간 이유 그 자체).
    """
    with pytest.raises(DuelRuleError):
        compute_twr([
            {"snapshot_date": "2026-08-10", "total_value": 10_000_000, "cash_flow_amount": 0},
            {"snapshot_date": "2026-08-11", "total_value": 10_800_000},   # 컬럼 자체가 없음
        ])
    with pytest.raises(DuelRuleError):
        compute_twr([
            {"snapshot_date": "2026-08-10", "total_value": 10_000_000, "cash_flow_amount": 0},
            {"snapshot_date": "2026-08-11", "total_value": 10_800_000, "cash_flow_amount": None},
        ])


def test_twr_is_independent_of_input_order_and_rejects_duplicate_days():
    """스냅샷이 뒤섞여 와도 날짜순으로 계산하고, 같은 날짜가 둘이면 거부합니다."""
    ordered = [
        _snap("2026-08-10", 10_000_000, 10_000_000),
        _snap("2026-08-11", 10_500_000, 0),
        _snap("2026-08-12", 11_500_000, 800_000),
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    assert compute_twr(shuffled)["twr_pct"] == compute_twr(ordered)["twr_pct"]

    with pytest.raises(DuelRuleError):
        compute_twr([_snap("2026-08-10", 10_000_000, 0), _snap("2026-08-10", 11_000_000, 0)])


# =============================================================================
# ⑨ 가중평균 평단가 갱신 + 매도 불가 (work order 2-4-6 / 1-2)
# =============================================================================
def test_weighted_average_follows_the_same_rule_as_holdings():
    """
    `holdings` 와 같은 규칙: (기존수량×기존평단 + 체결수량×체결가) / 총수량.
    `tests/test_scorecard.py` 가 쓰는 마인드맵 예시와 같은 모양의 무한소수 사례로 고정합니다.
        10주 @100,000 + 3주 @70,000 → 13주 / 1,210,000원 → 93,076.923077원(6자리 반올림)
    """
    merged = apply_buy_fill_to_position(10, 100_000, 3, 70_000)
    assert merged["quantity"] == 13
    assert merged["total_cost"] == 1_210_000
    assert merged["avg_cost"] == pytest.approx(1_210_000 / 13, abs=1e-6)
    # numeric(20,6) 에 저장되는 값이므로 소수점 6자리에서 한 번만 반올림돼야 합니다.
    assert merged["avg_cost"] == round(1_210_000 / 13, 6)


def test_first_buy_creates_the_position():
    """신규 포지션이면 기존 수량·평단가를 둘 다 None 으로 줍니다."""
    created = apply_buy_fill_to_position(None, None, 7, 70_000)
    assert created["quantity"] == 7
    assert created["avg_cost"] == 70_000
    assert created["total_cost"] == 490_000


def test_total_cost_is_money_actually_spent_not_derived_from_the_rounded_average():
    """
    원가는 **실제로 쓴 돈의 합**이어야 합니다. 반올림된 평단가 × 수량으로 되돌려 계산하면
    미세하게 어긋나고, 그 차이가 스냅샷의 total_cost 로 흘러갑니다.
    (평단가가 무한소수인 이 사례에서 두 방식이 실제로 다른 값을 냅니다.)
    """
    merged = apply_buy_fill_to_position(10, 100_000, 3, 70_000)
    assert merged["total_cost"] == 10 * 100_000 + 3 * 70_000 == 1_210_000
    derived_from_rounded_average = round(merged["avg_cost"] * merged["quantity"], 6)
    assert merged["total_cost"] != derived_from_rounded_average, (
        "되돌려 계산하는 방식으로 바뀌면 이 테스트가 통과해 버립니다"
    )


@pytest.mark.parametrize("bad_quantity", [0, -1, -100])
def test_application_path_cannot_reduce_a_position(bad_quantity):
    """
    🔴 **매수 경로로는** 수량이 절대 줄지 않습니다 — 음수·0 체결은 전부 거부돼야 합니다.
    (2026-08-21 부터 리밸런싱 매도가 생겼지만, 수량을 줄일 수 있는 것은 전용 함수
     `apply_sell_fill_to_position()` 하나뿐입니다 — 아래 ⑪ 참고. DB 레벨 방어는
     sql/duel_schema.sql §2-1 의 트리거가 세션 변수 두 개로 경로를 갈라 맡습니다.)
    """
    with pytest.raises(DuelRuleError):
        apply_buy_fill_to_position(10, 100_000, bad_quantity, 70_000)


def test_fractional_share_fill_is_rejected_in_v1():
    """v1 의 매수 체결은 항상 정수 주식만 만듭니다(작업지시서 1-2)."""
    with pytest.raises(DuelRuleError):
        apply_buy_fill_to_position(10, 100_000, 1.5, 70_000)


def test_half_known_position_is_an_error_not_a_guess():
    """'수량은 아는데 평단가는 모르는' 상태를 0 으로 메우고 진행하지 않습니다."""
    with pytest.raises(DuelRuleError):
        apply_buy_fill_to_position(10, None, 1, 70_000)
    with pytest.raises(DuelRuleError):
        apply_buy_fill_to_position(None, 100_000, 1, 70_000)


# =============================================================================
# ⑩ 계층 분리 · 단일 출처 회귀 고정
# =============================================================================
def _rules_source():
    return (REPO_ROOT / "utils" / "duel_rules.py").read_text(encoding="utf-8")


def test_rules_module_stays_pure_so_offline_tests_keep_working():
    """
    `utils/duel_rules.py` 에 Supabase·네트워크·NiceGUI·streamlit 의존이 들어오면 4단계
    오프라인 검증이 통째로 깨집니다(`tests/test_scorecard_ocr.py` 의 계층 분리 검사와 같은 목적).
    주석에 이름이 나오는 건 의존이 아니므로 **실제 import 문**만 봅니다.
    """
    source = _rules_source()
    for forbidden in ("supabase", "nicegui", "streamlit", "requests", "duel_db",
                      "scorecard_db", "report_db", "data_source"):
        assert not re.search(rf"^\s*(from|import)\s+\S*{forbidden}", source, re.M | re.I), (
            f"duel_rules.py 가 {forbidden} 을(를) import 하면 오프라인 단독 테스트가 깨집니다"
        )
    # 파일을 여는 코드도 없어야 합니다(가격·거래일은 전부 인자로 받습니다).
    assert not re.search(r"^\s*(from|import)\s+\S*\b(os|pathlib|json|csv)\b", source, re.M)


def test_money_constants_have_exactly_one_source():
    """
    §0-3-10 — 시드 1천만원·매월 80만원을 두 곳에 적어두면 둘 중 하나만 바뀌는 날 조용히
    어긋납니다. 앱 상수 하나가 단일 출처이고, SQL 스키마에는 숫자를 박지 않습니다
    (`sql/scorecard_schema.sql` §8 이 하루 한도 숫자를 DB 에 적지 않은 것과 같은 판단).
    """
    assert rules.SEED_AMOUNT_KRW == 10_000_000
    assert rules.MONTHLY_DEPOSIT_KRW == 800_000
    assert rules.MONTHLY_DEPOSIT_DAY == 10
    assert rules.ACCOUNT_WINDOW_TYPES == ("M1", "M3", "M6")

    source = _rules_source()
    assert source.count("SEED_AMOUNT_KRW = ") == 1, "시드 금액 정의는 정확히 한 곳"
    assert source.count("MONTHLY_DEPOSIT_KRW = ") == 1

    # ⚠️ **실행되는 SQL 만** 봅니다. `--` 주석에는 자가 점검용 예시 쿼리가 들어 있고
    #    (§11 의 ⑥ 멱등성 확인), 예시는 두 번째 출처가 아니라 사람이 읽는 설명입니다.
    #    (`tests/test_scorecard_ocr.py` 가 "주석에 이름이 나오는 건 의존이 아니다"라고
    #     구분한 것과 같은 판단입니다.)
    schema = (REPO_ROOT / "sql" / "duel_schema.sql").read_text(encoding="utf-8")
    executable_sql = "\n".join(
        line for line in schema.splitlines() if not line.lstrip().startswith("--")
    )
    assert "default 10000000" not in executable_sql, (
        "DB default 로 시드 금액을 박으면 앱 상수와 어긋날 수 있습니다"
    )
    assert "800000" not in executable_sql, (
        "매월 입금액은 실행되는 DDL 어디에도 적지 않습니다(앱 상수가 단일 출처)"
    )


# =============================================================================
# ⑪ 창당 1회 리밸런싱 매도 (2026-08-21 오너 확정 — duel_rules §12)
# =============================================================================
def test_rebalance_window_days_are_the_single_source():
    """
    §0-3-10 — 창 길이 30/90/180 을 두 곳에 적으면 둘 중 하나만 바뀌는 날 "매도 기회가 하나
    더 생기거나 사라지는" 형태로 어긋납니다. 정의는 정확히 한 곳이어야 합니다.
    """
    assert rules.REBALANCE_WINDOW_DAYS == {"M1": 30, "M3": 90, "M6": 180}
    # 계좌 유형 목록과 키가 정확히 같아야 합니다(한쪽에만 유형이 늘어나면 창을 못 셉니다).
    assert set(rules.REBALANCE_WINDOW_DAYS) == set(rules.ACCOUNT_WINDOW_TYPES)
    assert _rules_source().count("REBALANCE_WINDOW_DAYS = ") == 1

    # 실행되는 SQL 에는 창 길이를 적지 않습니다(시드 금액과 같은 판단 — 위 ⑩ 참고).
    schema = (REPO_ROOT / "sql" / "duel_schema.sql").read_text(encoding="utf-8")
    executable_sql = "\n".join(
        line for line in schema.splitlines() if not line.lstrip().startswith("--")
    )
    for length in ("30", "90", "180"):
        assert f"rebalance_window_index = {length}" not in executable_sql


def test_rebalance_window_starts_on_the_first_holding_date():
    """창 0 의 첫날은 **최초 보유일 그 자신**입니다(개설일이 아닙니다)."""
    window = resolve_rebalance_window("M1", date(2026, 1, 1), date(2026, 1, 1))
    assert window["window_index"] == 0
    assert window["window_started_on"] == date(2026, 1, 1)
    assert window["window_ends_on"] == date(2026, 1, 30)      # 30일 = 첫날 포함
    assert window["next_window_starts_on"] == date(2026, 1, 31)
    assert window["days_remaining"] == 30                     # 오늘 포함
    assert window["window_days"] == 30


def test_rebalance_window_last_day_still_belongs_to_the_same_window():
    """
    🔴 경계 고정: 창의 **마지막 날에도** 아직 그 창입니다(그날 매도할 수 있어야 합니다).
    하루만 어긋나도 사용자가 마지막 날 매도 기회를 잃습니다.
    """
    window = resolve_rebalance_window("M1", date(2026, 1, 1), date(2026, 1, 30))
    assert window["window_index"] == 0
    assert window["days_remaining"] == 1


def test_rebalance_window_rolls_over_the_day_after_the_last_day():
    """마지막 날 다음 날부터 다음 창입니다 — 기회는 **누적되지 않고** 새로 하나 생깁니다."""
    window = resolve_rebalance_window("M1", date(2026, 1, 1), date(2026, 1, 31))
    assert window["window_index"] == 1
    assert window["window_started_on"] == date(2026, 1, 31)
    assert window["window_ends_on"] == date(2026, 3, 1)
    assert window["days_remaining"] == 30


@pytest.mark.parametrize("window_type,length", [("M1", 30), ("M3", 90), ("M6", 180)])
def test_rebalance_window_boundary_is_the_same_rule_for_all_three_accounts(window_type, length):
    """세 계좌의 차이는 **길이 하나뿐**이고 경계 규칙은 완전히 같습니다."""
    first_holding = date(2026, 1, 1)
    last_day = first_holding + timedelta(days=length - 1)

    assert resolve_rebalance_window(window_type, first_holding, last_day)["window_index"] == 0
    rolled = resolve_rebalance_window(window_type, first_holding,
                                      last_day + timedelta(days=1))
    assert rolled["window_index"] == 1
    assert rolled["window_started_on"] == last_day + timedelta(days=1)
    # 창 번호는 경과일 // 창길이 — 두 번째 창의 마지막 날까지도 1 이어야 합니다.
    assert resolve_rebalance_window(
        window_type, first_holding, last_day + timedelta(days=length))["window_index"] == 1


def test_rebalance_window_without_a_first_holding_date_is_an_error_not_a_guess():
    """
    🔴 §0-1 — 아직 아무것도 안 산 계좌의 창을 "오늘부터"로 지어내지 않습니다. 지어내면
    사용자마다 다른 창이 조용히 생기고, 그 값이 DB 유니크 인덱스의 키가 되어 되돌릴 수
    없습니다.
    """
    with pytest.raises(DuelRuleError) as excinfo:
        resolve_rebalance_window("M1", None, date(2026, 1, 1))
    assert "보유" in str(excinfo.value)


def test_rebalance_window_rejects_an_unknown_account_type():
    with pytest.raises(DuelRuleError):
        resolve_rebalance_window("M12", date(2026, 1, 1), date(2026, 1, 1))
    with pytest.raises(DuelRuleError):
        resolve_rebalance_window(None, date(2026, 1, 1), date(2026, 1, 1))


def test_rebalance_window_refuses_a_date_before_the_first_holding():
    """음수 창 번호를 만들지 않습니다(과거 날짜로 매도 기회가 하나 더 생기는 경로 차단)."""
    with pytest.raises(DuelRuleError):
        resolve_rebalance_window("M1", date(2026, 1, 10), date(2026, 1, 9))


def test_sell_fill_is_always_a_full_fill():
    """매도는 부분체결이 없습니다 — 보유 수량 이하 요청은 전량 체결됩니다."""
    result = calculate_sell_fill(requested_quantity=3, close_price=70_000, held_quantity=10)
    assert result["status"] == ORDER_FILLED
    assert result["filled_quantity"] == 3
    assert result["filled_amount"] == 210_000
    assert result["remaining_holding"] == 7
    assert result["fail_reason"] is None


def test_sell_fill_can_sell_everything():
    result = calculate_sell_fill(10, 1_234.56, 10)
    assert result["filled_quantity"] == 10
    assert result["remaining_holding"] == 0
    assert result["filled_amount"] == round(10 * 1_234.56, 6)


def test_sell_more_than_held_is_an_error_not_a_silent_clamp():
    """
    🔴 보유 수량을 넘는 매도를 **보유량만큼으로 깎아서** 체결하지 않습니다. 깎으면 "왜 요청과
    다른 수량이 팔렸는지"를 아무도 설명할 수 없습니다(§0-1).
    """
    with pytest.raises(DuelRuleError) as excinfo:
        calculate_sell_fill(11, 70_000, 10)
    assert "보유" in str(excinfo.value)


@pytest.mark.parametrize("bad_price", [None, 0, -1])
def test_sell_fill_refuses_to_run_without_a_confirmed_close_price(bad_price):
    """매수와 같은 방어 — 모르는 가격으로 팔지 않습니다(§0-3-1)."""
    with pytest.raises(DuelRuleError):
        calculate_sell_fill(1, bad_price, 10)


def test_sell_fill_rejects_zero_and_fractional_quantities():
    for bad in (0, -1, 1.5):
        with pytest.raises(DuelRuleError):
            calculate_sell_fill(bad, 70_000, 10)


def test_sell_tolerates_a_fractional_holding_but_still_sells_whole_shares():
    """
    보유 수량은 `numeric(20, 6)` 이고 기업행위 조정(관리 경로)이 소수 수량을 남길 수
    있습니다. 거기서 정수를 강요하면 "팔 수는 있어야 하는 보유"가 체결 시점에 막힙니다 —
    제약은 **파는 수량이 정수**라는 것뿐입니다.
    """
    result = calculate_sell_fill(1, 100.0, 2.5)
    assert result["filled_quantity"] == 1
    assert result["remaining_holding"] == 1.5
    with pytest.raises(DuelRuleError):
        calculate_sell_fill(3, 100.0, 2.5)


def test_full_sell_leaves_zero_quantity_and_an_unchanged_average_cost():
    """
    🔴 전량 매도 → 수량 0(스키마가 정상 상태로 명시한 값), 평단가는 **그대로**입니다.
    행을 지우지도, 평단가를 0 으로 만들지도 않습니다.
    """
    updated = apply_sell_fill_to_position(10, 100_000, 10)
    assert updated["quantity"] == 0
    assert updated["avg_cost"] == 100_000


def test_partial_sell_does_not_touch_the_cost_basis():
    """
    남은 주식의 매입단가는 매도로 바뀌지 않습니다(표준 관례). 매수(`apply_buy_...`)가
    가중평균을 **다시 계산**하는 것과 정반대라, 두 함수가 섞이지 않았는지 여기서 고정합니다.
    """
    updated = apply_sell_fill_to_position(10, 93_076.923077, 3)
    assert updated["quantity"] == 7
    assert updated["avg_cost"] == 93_076.923077
    # 매도 결과에는 total_cost 가 없습니다(잔여 원가는 수량 × 평단가로 언제든 정확히 나옵니다).
    assert set(updated) == {"quantity", "avg_cost"}


def test_sell_cannot_push_a_position_negative():
    with pytest.raises(DuelRuleError):
        apply_sell_fill_to_position(3, 100_000, 4)


def test_sell_needs_both_quantity_and_average_cost():
    """'수량은 아는데 평단가는 모르는' 상태로 매도를 반영하지 않습니다(매수와 같은 규율)."""
    with pytest.raises(DuelRuleError):
        apply_sell_fill_to_position(None, 100_000, 1)
    with pytest.raises(DuelRuleError):
        apply_sell_fill_to_position(10, None, 1)


def test_twr_is_untouched_by_a_sell_because_it_is_an_internal_conversion():
    """
    🔴 매도는 **외부 현금흐름이 아닙니다** — 계좌 안에서 주식이 현금으로 바뀐 것뿐이라
    총자산이 그대로입니다. 그래서 `compute_twr()` 는 이번 변경에서 손댈 필요가 없었고,
    그 사실을 여기서 회귀로 고정합니다(누가 매도 대금을 cash_flow_amount 에 넣기 시작하면
    수익률이 통째로 틀어집니다).

    같은 날 총자산이 그대로인 두 스냅샷(하나는 매도 전, 하나는 매도 후 구성만 다름)의
    구간 수익률은 0% 여야 합니다.
    """
    before = _snap("2026-08-19", 10_000_000, 0)          # 주식 300만 + 현금 700만
    after = _snap("2026-08-20", 10_000_000, 0)           # 주식 0 + 현금 1,000만 (매도 직후)
    result = compute_twr([before, after])
    assert result["status"] == TWR_OK
    assert result["twr_pct"] == 0.0
