# tests/test_duel_batch.py
"""
⚔️ "결투다!" — 야간 배치(`utils/duel_batch.py`) 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · 실제 `data/*.json` 불필요)

DUEL_MODULE_WORK_ORDER.md 4단계에 따라, **가짜 Supabase 클라이언트**와 손으로 만든 값으로만
검증합니다. `tests/test_duel.py`(순수 규칙) · `tests/test_duel_db.py`(맞는 표에 맞는 조건으로
보내는가)와 짝을 이루는 세 번째 축입니다 — 여기서 보는 것은 **"하루치 순서가 맞는가"** 입니다.

검증 대상
    ① 신선도 점검표(2-9)를 상위 50종목 + 지수로 제대로 만드는가, 못 만들면 조용히 줄이지 않고
       예외를 내는가
    ② 기준값 파일(어제 값)의 읽기·쓰기·손상 처리 — **임시 경로**로만, 저장소 파일은 안 만집니다
    ③ 신선도 판정 다섯 갈래(ok / failed / failed_or_holiday / needs_review / no_baseline)와
       각각의 **행동**(체결 / 일괄 취소 / 보류)
    ④ 매월 10일에만 정기 입금이 돌고, 그 외 날에는 아예 시도조차 하지 않는가
    ⑤ 같은 계좌의 여러 주문이 `saved_at` 순서대로 예수금을 먹는가(FIFO), 부분체결·만료 처리
    ⑥ 스냅샷 행이 계좌별로 맞게 만들어지는가(현금만 있는 계좌 / 보유 있는 계좌 / 가격 모르는
       종목 / 상장폐지), 그리고 TWR 이 입금을 수익으로 세지 않는가
    ⑦ 🔴 §0-3-2 — 계좌가 3개든 900개든 **Supabase 왕복 횟수가 그대로**인가 (회귀 고정)

실행: pytest tests/test_duel_batch.py -v
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
# 가짜 Supabase 클라이언트는 `tests/test_duel_db.py` 가 이미 갖고 있습니다. 같은 걸 다시 짜면
# 두 스위트가 서로 다른 방식으로 Supabase 를 흉내내기 시작하고, 어느 쪽이 진짜에 가까운지
# 아무도 모르게 됩니다(§0-3-10 — 흉내도 단일 출처로).
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient  # noqa: E402
from utils import duel_batch, duel_db, duel_rules  # noqa: E402
from utils.duel_batch import DuelBatchError  # noqa: E402
from utils.duel_rules import KST  # noqa: E402

TARGET_DATE = date(2026, 8, 20)          # 목요일 — 정기 입금일(10일)이 아닌 평범한 거래일
DEPOSIT_DATE = date(2026, 9, 10)         # 정기 입금일
YESTERDAY = date(2026, 8, 19)


# =============================================================================
# 0. 픽스처 만들기 — 전부 손으로 만든 값(실제 파일을 읽지 않습니다)
# =============================================================================
def _universe(count=60, *, base_price=10_000.0):
    """`scorecard_db.load_universe_index(MARKET_KR)` 이 돌려주는 모양의 가짜 인덱스."""
    return {
        f"{index:06d}": {
            "code": f"{index:06d}",
            "name": f"합성{index}",
            "rank": index,
            "price": base_price + index,
        }
        for index in range(1, count + 1)
    }


def _probe(target_date, *, kospi=3200.0, stock_prices=None, index_keys=("KOSPI",)):
    """`build_freshness_probe()` 가 만드는 것과 같은 모양의 점검표(직접 조립)."""
    values = {"KOSPI": kospi}
    values.update(stock_prices or {})
    return {
        "version": duel_batch.PROBE_STATE_VERSION,
        "generated_at_kst": datetime(2026, 8, 20, 17, 10, tzinfo=KST).isoformat(),
        "target_date": target_date.isoformat() if hasattr(target_date, "isoformat")
        else str(target_date),
        "index_keys": list(index_keys),
        "values": values,
    }


def _stock_prices(count=50, *, bump=0.0, unchanged=0):
    """
    50종목 종가. `bump` 만큼 올린 값을 만들되, 앞에서 `unchanged` 개는 **어제와 같게** 둡니다
    (무변동 종목 수를 테스트가 정확히 통제할 수 있게).
    """
    prices = {}
    for index in range(1, count + 1):
        base = 10_000.0 + index
        prices[f"{index:06d}"] = base if index <= unchanged else base + bump
    return prices


def _accounts(count=2):
    return [{"id": f"acc-{index}", "user_id": f"user-{index}",
             "window_type": duel_rules.ACCOUNT_WINDOW_TYPES[index % 3],
             "seed_amount": duel_rules.SEED_AMOUNT_KRW, "currency": "KRW",
             "anchor_date": "2026-07-01", "status": "active"}
            for index in range(1, count + 1)]


def _seed_ledger(accounts, *, event_date="2026-07-01"):
    return [{"account_id": account["id"], "event_type": "seed",
             "amount": duel_rules.SEED_AMOUNT_KRW, "event_date": event_date}
            for account in accounts]


def _order(order_id, account_id, ticker, quantity, saved_at, *, stock_name=None):
    return {"id": order_id, "account_id": account_id, "ticker": ticker,
            "stock_name": stock_name or f"합성{ticker}", "requested_quantity": quantity,
            "side": "buy", "status": duel_rules.ORDER_PENDING,
            "saved_at": saved_at, "target_date": TARGET_DATE.isoformat()}


def _client(*, accounts=None, ledger=None, orders=None, positions=None, snapshots=None,
            deposits_already=None, cancelled_rows=None):
    """
    배치 한 판을 돌릴 수 있는 가짜 클라이언트.

    같은 표에 성격이 다른 select 가 두 번 가는 곳이 하나 있습니다(현금 원장: 정기 입금 중복
    조회 / 잔고 조회). 그래서 필터를 보고 갈라 줍니다 — `FakeClient` 가 callable 응답을
    지원하는 이유가 이것입니다.
    """
    accounts = accounts if accounts is not None else _accounts()
    ledger = ledger if ledger is not None else _seed_ledger(accounts)

    def ledger_select(query):
        if query.filter_map.get("event_type") == "monthly_deposit":
            return list(deposits_already or [])
        return list(ledger)

    responses = {
        (duel_db.ACCOUNTS_TABLE, "select"): list(accounts),
        (duel_db.LEDGER_TABLE, "select"): ledger_select,
        (duel_db.ORDERS_TABLE, "select"): list(orders or []),
        (duel_db.POSITIONS_TABLE, "select"): list(positions or []),
        (duel_db.DAILY_SNAPSHOTS_TABLE, "select"): list(snapshots or []),
    }
    if cancelled_rows is not None:
        responses[(duel_db.ORDERS_TABLE, "update")] = list(cancelled_rows)
    return FakeClient(responses=responses)


def _price_lookup(prices):
    """`{ticker: 종가}` → 배치가 받는 조회 함수. 모르는 종목은 None(추정 금지)."""
    def lookup(ticker):
        return prices.get(ticker)
    return lookup


def _run(client, **kwargs):
    """`run_nightly_batch()` 기본 인자 묶음(로그는 삼켜서 테스트 출력이 조용하게)."""
    options = {
        "today_probe": _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=10.0)),
        "previous_probe": _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
        "close_price_of": _price_lookup({}),
        "log": lambda *args, **kw: None,
    }
    target_date = kwargs.pop("target_date", TARGET_DATE)
    options.update(kwargs)
    return duel_batch.run_nightly_batch(client, target_date, **options)


# =============================================================================
# 1. 신선도 점검표 만들기 (2-9)
# =============================================================================
def test_probe_takes_the_top_fifty_by_market_cap_rank():
    """
    상위 50종목은 **`rank`(시가총액 순위) 오름차순**으로 고릅니다.
    60종목이 있으면 rank 1~50 만 들어가고 51~60 은 빠져야 합니다.
    """
    probe = duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": 3200.0}, _universe(60))
    codes = set(probe["values"]) - set(probe["index_keys"])

    assert len(probe["values"]) == 51            # 지수 1 + 종목 50 (코스닥 원천 없음 — 아래 주석)
    assert len(codes) == duel_rules.CRAWL_STOCK_COUNT
    assert "000001" in codes and "000050" in codes
    assert "000051" not in codes
    assert probe["values"]["000001"] == 10_001.0
    assert probe["target_date"] == TARGET_DATE.isoformat()
    assert probe["version"] == duel_batch.PROBE_STATE_VERSION


def test_probe_refuses_to_shrink_when_there_are_not_enough_stocks():
    """
    상위 50개를 못 채우면 **줄여서 판정하지 않고 예외**입니다 —
    "몇 종목만 보고 그날 수집 성패를 판정하지 않는다"(2-9)를 배치 쪽에서도 지킵니다.
    """
    with pytest.raises(DuelBatchError) as error:
        duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": 3200.0}, _universe(30))
    assert "50" in str(error.value)


def test_probe_refuses_a_missing_index_value():
    """지수 값이 없으면 그 지수를 빼고 '점검했다'고 하지 않습니다(§0-1)."""
    with pytest.raises(DuelBatchError) as error:
        duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": None}, _universe(60))
    assert "KOSPI" in str(error.value)

    with pytest.raises(DuelBatchError):
        duel_batch.build_freshness_probe(TARGET_DATE, {}, _universe(60))


def test_probe_skips_stocks_without_a_usable_price_but_still_needs_fifty():
    """가격이 0·None 인 종목은 점검에 못 쓰지만, 그렇다고 대상 수를 줄이지도 않습니다."""
    universe = _universe(52)
    universe["000001"]["price"] = 0
    universe["000002"]["price"] = None
    probe = duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": 3200.0}, universe)
    codes = set(probe["values"]) - set(probe["index_keys"])
    assert len(codes) == 50
    assert "000001" not in codes and "000002" not in codes
    assert "000051" in codes and "000052" in codes


def test_probe_does_not_filter_out_unverified_stocks():
    """
    수집에 문제가 있던 종목(`is_unverified`)을 **먼저 빼지 않습니다.** 이 점검의 목적이
    "수집이 제대로 됐는가"라서, 실패한 종목을 걸러 내면 잡아야 할 실패를 스스로 가립니다.
    """
    universe = _universe(50)
    universe["000003"]["is_unverified"] = True
    universe["000004"]["is_visible"] = False
    probe = duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": 3200.0}, universe)
    codes = set(probe["values"]) - set(probe["index_keys"])
    assert {"000003", "000004"} <= codes


# =============================================================================
# 2. 기준값 파일 — 어제 값을 어디서 얻는가 (설계 판단 지점)
# =============================================================================
def test_probe_state_round_trip(tmp_path):
    """오늘 쓴 점검표를 그대로 다시 읽을 수 있어야 합니다(내일의 '어제 값')."""
    path = tmp_path / "duel_freshness_probe_previous.json"
    probe = duel_batch.build_freshness_probe(TARGET_DATE, {"KOSPI": 3200.0}, _universe(60))

    assert duel_batch.load_probe_state(str(path)) is None      # 첫 실행 — 오류가 아닙니다
    duel_batch.save_probe_state(str(path), probe)
    restored = duel_batch.load_probe_state(str(path))

    assert restored["values"] == probe["values"]
    assert restored["target_date"] == TARGET_DATE.isoformat()
    assert restored["index_keys"] == probe["index_keys"]


def test_probe_state_overwrite_leaves_no_temporary_file(tmp_path):
    """임시 파일로 쓴 뒤 바꿔치우므로, 끝나고 나면 디렉터리에 파일 하나만 남아야 합니다."""
    path = tmp_path / "state.json"
    duel_batch.save_probe_state(str(path), _probe(YESTERDAY))
    duel_batch.save_probe_state(str(path), _probe(TARGET_DATE))
    assert [item.name for item in tmp_path.iterdir()] == ["state.json"]
    assert duel_batch.load_probe_state(str(path))["target_date"] == TARGET_DATE.isoformat()


def test_probe_state_corrupt_file_is_loud_not_silent(tmp_path):
    """
    깨진 기준값을 **조용히 '기준값 없음'으로 바꾸지 않습니다.** 둘은 다른 사건이고,
    후자는 사람이 고쳐야 합니다(§0-1).
    """
    path = tmp_path / "state.json"
    path.write_text("{이건 JSON 이 아닙니다", encoding="utf-8")
    with pytest.raises(DuelBatchError):
        duel_batch.load_probe_state(str(path))


def test_probe_state_unknown_version_is_rejected(tmp_path):
    """모르는 형식을 추측해서 읽지 않습니다."""
    path = tmp_path / "state.json"
    payload = _probe(YESTERDAY)
    payload["version"] = 999
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DuelBatchError) as error:
        duel_batch.load_probe_state(str(path))
    assert "버전" in str(error.value)


# =============================================================================
# 3. 신선도 판정 다섯 갈래 (2-9) — 판정 자체는 duel_rules 가 하고, 여기서는 입력 정리
# =============================================================================
def test_freshness_ok_when_index_and_most_stocks_moved():
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0)),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    assert verdict["status"] == duel_rules.CRAWL_OK
    assert verdict["allows_fill"] is True
    assert verdict["compared_stocks"] == 50
    assert verdict["baseline_date"] == YESTERDAY.isoformat()


def test_freshness_failed_or_holiday_when_nothing_moved():
    """52개(여기선 51개) 전부 무변동 → 휴장이거나 수집 실패. 둘을 구분하지 않습니다(2-9-1)."""
    same = _stock_prices()
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3200.0, stock_prices=same),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=same),
    )
    assert verdict["status"] == duel_rules.CRAWL_FAILED_OR_HOLIDAY
    assert verdict["allows_fill"] is False


def test_freshness_needs_review_when_too_many_stocks_are_flat():
    """무변동 종목 11개 이상 → 자동 실패 확정이 아니라 **관리자 확인**(2-9-4)."""
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0, unchanged=11)),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    assert verdict["status"] == duel_rules.CRAWL_NEEDS_REVIEW
    assert verdict["allows_fill"] is False


def test_freshness_tolerance_boundary_is_ten():
    """허용치 경계 고정: 무변동 10개까지는 정상, 11개부터 관리자 확인."""
    ten = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0, unchanged=10)),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    assert ten["status"] == duel_rules.CRAWL_OK


def test_freshness_failed_when_index_is_frozen_but_stocks_moved():
    """지수는 그대로인데 종목만 움직임 → 앞뒤가 안 맞는 상태라 실패(2-9-3)."""
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3200.0, stock_prices=_stock_prices(bump=5.0)),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    assert verdict["status"] == duel_rules.CRAWL_FAILED
    assert verdict["allows_fill"] is False


def test_freshness_without_baseline_is_its_own_state():
    """
    기준값이 없는 것은 "수집 실패"가 **아닙니다.** 우리 배치에 비교 기준이 없다는 우리 쪽
    사정이라, 상태를 따로 두고 주문을 취소하지도 않습니다.
    """
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0)), None)
    assert verdict["status"] == duel_batch.CRAWL_NO_BASELINE
    assert verdict["allows_fill"] is False
    assert verdict["baseline_date"] is None

    action = duel_batch.resolve_action(verdict)
    assert action["fill"] is False
    assert action["cancel_pending"] is False


def test_freshness_absorbs_a_small_change_in_the_top_fifty_list():
    """
    상위 50 명단은 순위가 바뀌면 매일 조금씩 달라집니다. 그 한두 종목 때문에 판정 자체가
    거부되면 배치가 자주 멈춥니다 — **양쪽에 다 있는 종목만** 비교합니다.
    """
    yesterday_stocks = _stock_prices()
    today_stocks = _stock_prices(bump=7.0)
    today_stocks.pop("000050")                 # 50위가 51위로 밀려남
    today_stocks["000051"] = 10_058.0          # 51위가 50위로 올라옴

    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=today_stocks),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=yesterday_stocks),
    )
    assert verdict["status"] == duel_rules.CRAWL_OK
    assert verdict["compared_stocks"] == 49
    assert verdict["dropped_stocks"] == 1


def test_freshness_gives_up_when_the_lists_barely_overlap():
    """명단이 통째로 달라졌으면 비교 근거가 부족하다고 보고 체결하지 않습니다."""
    today_stocks = {f"9{index:05d}": 100.0 + index for index in range(1, 51)}
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=today_stocks),
        _probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    assert verdict["status"] == duel_batch.CRAWL_NO_BASELINE
    assert verdict["allows_fill"] is False


def test_freshness_needs_the_index_in_the_baseline_too():
    """기준값에 지수가 없으면(형식이 바뀐 경우) 추측하지 않고 판정을 포기합니다."""
    previous = _probe(YESTERDAY, stock_prices=_stock_prices())
    previous["values"].pop("KOSPI")
    verdict = duel_batch.judge_crawl_freshness(
        _probe(TARGET_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0)), previous)
    assert verdict["status"] == duel_batch.CRAWL_NO_BASELINE


# =============================================================================
# 4. 판정 → 행동 표 (§3 머리말의 표를 코드로 고정)
# =============================================================================
@pytest.mark.parametrize("status,fill,cancel,snapshots", [
    (duel_rules.CRAWL_OK, True, False, True),
    (duel_rules.CRAWL_FAILED, False, True, False),
    (duel_rules.CRAWL_FAILED_OR_HOLIDAY, False, True, False),
    (duel_rules.CRAWL_NEEDS_REVIEW, False, False, False),
    (duel_batch.CRAWL_NO_BASELINE, False, False, False),
])
def test_action_table_is_fixed(status, fill, cancel, snapshots):
    """
    🔴 이 표가 바뀌면 사용자 주문의 운명이 바뀝니다. 특히 `needs_review` 가 언젠가
    "그냥 체결"로 바뀌지 않도록 회귀로 못 박습니다(§0-1 — 애매할 때 진행하지 않기).
    """
    action = duel_batch.resolve_action({"status": status})
    assert action["fill"] is fill
    assert action["cancel_pending"] is cancel
    assert action["write_snapshots"] is snapshots


def test_admin_override_is_explicit_only():
    """관리자 덮어쓰기는 두 값만, 그 외에는 예외(오타로 조용히 체결되는 경로 금지)."""
    verdict = {"status": duel_rules.CRAWL_NEEDS_REVIEW}
    assert duel_batch.resolve_action(verdict, duel_batch.OVERRIDE_FILL)["fill"] is True
    assert duel_batch.resolve_action(verdict, duel_batch.OVERRIDE_CANCEL)["cancel_pending"] is True
    with pytest.raises(DuelBatchError):
        duel_batch.resolve_action(verdict, "yes")


# =============================================================================
# 5. 정기 입금 (2-2) — 10일에만
# =============================================================================
def test_deposit_runs_only_on_the_tenth():
    assert duel_batch.is_monthly_deposit_date("2026-09-10") is True
    assert duel_batch.is_monthly_deposit_date(date(2026, 9, 10)) is True
    assert duel_batch.is_monthly_deposit_date("2026-09-11") is False
    assert duel_batch.is_monthly_deposit_date("2026-09-09") is False


def test_batch_deposits_on_the_tenth_and_uses_the_money_the_same_day():
    """
    10일에는 정기 입금이 돌고, **그 입금이 반영된 뒤에** 원장을 읽습니다(순서가 뒤집히면
    그날 들어온 80만원을 그날 주문에 못 씁니다 — 2-2-3 의 의도와 어긋납니다).
    """
    accounts = _accounts(2)
    client = _client(accounts=accounts)
    summary = _run(client, target_date=DEPOSIT_DATE)

    assert summary["deposit_attempted"] is True
    assert summary["deposit_applied"] == 2
    deposit_insert = client.only_call(duel_db.LEDGER_TABLE, "insert")
    assert all(row["amount"] == duel_rules.MONTHLY_DEPOSIT_KRW for row in deposit_insert.rows)
    assert all(row["event_date"] == DEPOSIT_DATE.isoformat() for row in deposit_insert.rows)

    # 입금 insert 가 잔고 조회(select)보다 **먼저** 일어났는지 호출 순서로 고정합니다.
    order_of_calls = [(call.table, call.op) for call in client.calls]
    insert_at = order_of_calls.index((duel_db.LEDGER_TABLE, "insert"))
    balance_selects = [index for index, call in enumerate(client.calls)
                       if call.table == duel_db.LEDGER_TABLE and call.op == "select"
                       and call.filter_map.get("event_type") != "monthly_deposit"]
    assert balance_selects and min(balance_selects) > insert_at


def test_batch_does_not_deposit_on_other_days():
    client = _client()
    summary = _run(client, target_date=TARGET_DATE)
    assert summary["deposit_attempted"] is False
    assert summary["deposit_applied"] == 0
    assert client.calls_for(duel_db.LEDGER_TABLE, "insert") == []


def test_batch_deposit_is_idempotent_on_a_second_run():
    """배치를 두 번 돌려도 같은 달 입금이 두 번 들어가지 않습니다(2-2-6)."""
    accounts = _accounts(2)
    client = _client(accounts=accounts,
                     deposits_already=[{"account_id": row["id"]} for row in accounts])
    summary = _run(client, target_date=DEPOSIT_DATE)
    assert summary["deposit_applied"] == 0
    assert client.calls_for(duel_db.LEDGER_TABLE, "insert") == []


def test_batch_deposits_even_when_the_crawl_failed():
    """
    정기 입금은 **시장 이벤트가 아니라 현금 이벤트**입니다(2-2-4). 수집이 실패한 날에도
    10일이면 그대로 들어갑니다 — 체결만 건너뜁니다.
    """
    same = _stock_prices()
    client = _client()
    summary = _run(
        client, target_date=DEPOSIT_DATE,
        today_probe=_probe(DEPOSIT_DATE, kospi=3200.0, stock_prices=same),
        previous_probe=_probe(YESTERDAY, kospi=3200.0, stock_prices=same),
    )
    assert summary["freshness"]["status"] == duel_rules.CRAWL_FAILED_OR_HOLIDAY
    assert summary["deposit_applied"] == 2
    assert summary["orders"]["orders"] == 0


# =============================================================================
# 6. 체결 계획 — FIFO · 부분체결 · 만료 (2-4-6)
# =============================================================================
def test_fifo_earlier_order_eats_the_cash_first():
    """
    🔴 작업지시서 4단계가 **회귀 테스트로 고정하라**고 지목한 항목:
       같은 계좌에 주문이 여럿이면 `saved_at` 이 빠른 주문이 먼저 예수금을 먹고,
       **뒤 주문이 앞 주문 몫까지 넘보지 않습니다.**
    """
    orders = [
        _order("o-late", "acc-1", "000002", 5, "2026-08-19T21:00:00+09:00"),
        _order("o-early", "acc-1", "000001", 5, "2026-08-19T19:00:00+09:00"),
    ]
    plan = duel_batch.plan_order_fills(
        orders, {"acc-1": 60_000.0},
        {"000001": 10_000.0, "000002": 10_000.0}, {}, TARGET_DATE)

    by_id = {row["id"]: row for row in plan["fill_results"]}
    assert by_id["o-early"]["status"] == duel_rules.ORDER_FILLED
    assert by_id["o-early"]["filled_quantity"] == 5
    # 남은 현금 1만원 → 뒤 주문은 1주만 부분체결.
    assert by_id["o-late"]["status"] == duel_rules.ORDER_PARTIALLY_FILLED
    assert by_id["o-late"]["filled_quantity"] == 1
    assert "요청 5주 중 1주" in by_id["o-late"]["fail_reason"]
    assert plan["cash_after"]["acc-1"] == 0.0


def test_partial_fill_records_both_requested_and_filled():
    plan = duel_batch.plan_order_fills(
        [_order("o-1", "acc-1", "000001", 10, "2026-08-19T19:00:00+09:00")],
        {"acc-1": 74_000.0}, {"000001": 10_000.0}, {}, TARGET_DATE)
    result = plan["fill_results"][0]
    assert result["status"] == duel_rules.ORDER_PARTIALLY_FILLED
    assert result["filled_quantity"] == 7
    assert result["filled_amount"] == 70_000.0
    assert plan["cash_after"]["acc-1"] == 4_000.0        # 잔돈은 현금으로 남습니다
    assert plan["ledger_entries"][0]["filled_amount"] == 70_000.0


def test_zero_affordable_becomes_expired_with_no_ledger_row():
    """1주도 못 사면 `expired` + 사유. 현금이 안 움직였으므로 **원장에 흔적을 남기지 않습니다.**"""
    plan = duel_batch.plan_order_fills(
        [_order("o-1", "acc-1", "000001", 3, "2026-08-19T19:00:00+09:00")],
        {"acc-1": 500.0}, {"000001": 10_000.0}, {}, TARGET_DATE)
    result = plan["fill_results"][0]
    assert result["status"] == duel_rules.ORDER_EXPIRED
    assert result["filled_quantity"] is None      # 0주 체결을 0 으로 적지 않습니다
    assert result["filled_price"] is None and result["filled_date"] is None
    assert result["fail_reason"]
    assert plan["ledger_entries"] == []
    assert plan["position_rows"] == []


def test_order_without_a_close_price_is_cancelled_not_guessed():
    """종가를 모르는 종목은 취소입니다 — 0원·전일 종가로 때우지 않습니다(2-4-5 / §0-1)."""
    plan = duel_batch.plan_order_fills(
        [_order("o-1", "acc-1", "999999", 1, "2026-08-19T19:00:00+09:00")],
        {"acc-1": 1_000_000.0}, {}, {}, TARGET_DATE)
    assert plan["fill_results"][0]["status"] == duel_rules.ORDER_CANCELLED
    assert plan["cash_after"]["acc-1"] == 1_000_000.0


def test_two_fills_of_the_same_ticker_become_one_position_row():
    """
    같은 계좌·같은 종목을 두 번 사면 포지션 행은 **한 줄**이어야 합니다
    (`upsert_positions()` 는 한 요청에 같은 (계좌,종목)이 두 번 오면 전체를 거절합니다).
    """
    orders = [
        _order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00"),
        _order("o-2", "acc-1", "000001", 1, "2026-08-19T20:00:00+09:00"),
    ]
    plan = duel_batch.plan_order_fills(orders, {"acc-1": 100_000.0},
                                       {"000001": 10_000.0}, {}, TARGET_DATE)
    assert len(plan["position_rows"]) == 1
    assert plan["position_rows"][0]["quantity"] == 2
    assert plan["position_rows"][0]["avg_cost"] == 10_000.0
    duel_db._assert_unique_keys(plan["position_rows"], ("account_id", "ticker"), "테스트")


def test_weighted_average_uses_the_rules_function():
    """평단가는 `duel_rules.apply_buy_fill_to_position()` 결과 그대로여야 합니다(재계산 금지)."""
    existing = {"acc-1": [{"account_id": "acc-1", "ticker": "000001", "stock_name": "합성1",
                           "quantity": 10, "avg_cost": 10_000.0, "status": "active"}]}
    plan = duel_batch.plan_order_fills(
        [_order("o-1", "acc-1", "000001", 10, "2026-08-19T19:00:00+09:00")],
        {"acc-1": 200_000.0}, {"000001": 20_000.0}, existing, TARGET_DATE)
    expected = duel_rules.apply_buy_fill_to_position(10, 10_000.0, 10, 20_000.0)
    row = plan["position_rows"][0]
    assert row["quantity"] == expected["quantity"]
    assert row["avg_cost"] == expected["avg_cost"] == 15_000.0


def test_accounts_do_not_borrow_each_others_cash():
    """계좌별로 예수금이 완전히 분리되는지(한 계좌가 다른 계좌 돈으로 체결되지 않는지)."""
    orders = [
        _order("o-a", "acc-1", "000001", 5, "2026-08-19T19:00:00+09:00"),
        _order("o-b", "acc-2", "000001", 5, "2026-08-19T19:00:00+09:00"),
    ]
    plan = duel_batch.plan_order_fills(orders, {"acc-1": 100_000.0, "acc-2": 10_000.0},
                                       {"000001": 10_000.0}, {}, TARGET_DATE)
    by_id = {row["id"]: row for row in plan["fill_results"]}
    assert by_id["o-a"]["filled_quantity"] == 5
    assert by_id["o-b"]["filled_quantity"] == 1


# =============================================================================
# 7. 하루치 배치 — 판정별 실제 행동
# =============================================================================
def test_batch_fills_and_writes_everything_on_a_good_day():
    accounts = _accounts(1)
    client = _client(
        accounts=accounts,
        orders=[_order("o-1", "acc-1", "000001", 3, "2026-08-19T19:00:00+09:00")],
    )
    summary = _run(client, close_price_of=_price_lookup({"000001": 10_000.0}))

    assert summary["freshness"]["status"] == duel_rules.CRAWL_OK
    assert summary["orders"]["filled"] == 1
    assert summary["filled_amount_total"] == 30_000.0
    assert summary["ledger_rows_written"] == 1
    assert summary["positions_written"] == 1
    assert summary["snapshots_written"] == 1

    fill_update = client.only_call(duel_db.ORDERS_TABLE, "update")
    assert fill_update.payload["status"] == duel_rules.ORDER_FILLED
    assert fill_update.payload["filled_date"] == TARGET_DATE.isoformat()
    assert fill_update.filter_map["status"] == duel_rules.ORDER_PENDING

    snapshot = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "upsert").rows[0]
    assert snapshot["snapshot_date"] == TARGET_DATE.isoformat()
    assert snapshot["position_value"] == 30_000.0
    assert snapshot["cash_balance"] == duel_rules.SEED_AMOUNT_KRW - 30_000.0
    assert snapshot["total_value"] == duel_rules.SEED_AMOUNT_KRW


def test_batch_cancels_everything_when_the_crawl_failed():
    """
    수집 실패·휴장일이면 **체결 단계 전체를 건너뛰고**(부분 체결 금지) 그날 귀속 주문을
    한 번의 update 로 정리합니다(2-4-5 / §0-3-2).
    """
    same = _stock_prices()
    client = _client(cancelled_rows=[{"id": "o-1"}, {"id": "o-2"}])
    summary = _run(
        client,
        today_probe=_probe(TARGET_DATE, kospi=3200.0, stock_prices=same),
        previous_probe=_probe(YESTERDAY, kospi=3200.0, stock_prices=same),
    )

    assert summary["freshness"]["status"] == duel_rules.CRAWL_FAILED_OR_HOLIDAY
    assert summary["pending_cancelled"] == 2
    assert summary["snapshots_written"] == 0

    update = client.only_call(duel_db.ORDERS_TABLE, "update")     # 질의 1개 = 집합 연산
    assert update.payload["status"] == duel_rules.ORDER_CANCELLED
    assert update.payload["fail_reason"]
    assert update.filter_map == {"status": duel_rules.ORDER_PENDING,
                                 "target_date": TARGET_DATE.isoformat()}
    # 스냅샷·포지션은 아예 건드리지 않습니다.
    assert client.calls_for(duel_db.DAILY_SNAPSHOTS_TABLE) == []
    assert client.calls_for(duel_db.POSITIONS_TABLE) == []


def test_batch_holds_orders_when_review_is_needed():
    """
    `needs_review` 는 체결도 취소도 하지 않고 **그대로 둡니다** — 2-9-4 가 요구한
    "관리자 확인 후 최종 판정"이 실제로 가능하려면 주문이 남아 있어야 합니다.
    """
    client = _client(orders=[_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00")])
    summary = _run(
        client,
        today_probe=_probe(TARGET_DATE, kospi=3210.0,
                           stock_prices=_stock_prices(bump=5.0, unchanged=20)),
        previous_probe=_probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )

    assert summary["freshness"]["status"] == duel_rules.CRAWL_NEEDS_REVIEW
    assert summary["pending_held"] == 1
    assert summary["pending_cancelled"] == 0
    assert summary["snapshots_written"] == 0
    assert client.calls_for(duel_db.ORDERS_TABLE, "update") == []      # 아무것도 안 바꿈
    assert any("관리자" in warning for warning in summary["warnings"])


def test_admin_override_can_resolve_a_held_day():
    """관리자가 값을 확인한 뒤 같은 날짜를 `--override fill` 로 다시 돌리면 체결됩니다."""
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00")])
    summary = _run(
        client,
        today_probe=_probe(TARGET_DATE, kospi=3210.0,
                           stock_prices=_stock_prices(bump=5.0, unchanged=20)),
        previous_probe=_probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
        close_price_of=_price_lookup({"000001": 10_000.0}),
        override=duel_batch.OVERRIDE_FILL,
    )
    assert summary["orders"]["filled"] == 1
    assert summary["snapshots_written"] == 1
    assert summary["action"]["override"] == duel_batch.OVERRIDE_FILL


def test_orders_from_inactive_accounts_are_left_alone_not_expired():
    """
    그날 주문 조회는 계좌 상태를 보지 않습니다. 활성 목록에 없는 계좌의 주문을 그냥 처리하면
    예수금을 못 읽어 0 으로 보이고 "예수금 부족으로 만료"라는 **거짓 사유**가 남습니다.
    손대지 않고 경고만 올려야 합니다(§0-1).
    """
    client = _client(
        accounts=_accounts(1),
        orders=[_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00"),
                _order("o-x", "acc-없는계좌", "000001", 1, "2026-08-19T19:10:00+09:00")],
    )
    summary = _run(client, close_price_of=_price_lookup({"000001": 10_000.0}))

    assert summary["orders"]["orders"] == 1
    updated_ids = [call.filter_map["id"] for call in client.calls_for(duel_db.ORDERS_TABLE, "update")]
    assert updated_ids == ["o-1"]
    assert any("활성 계좌 목록에 없는" in warning for warning in summary["warnings"])


def test_batch_without_a_baseline_neither_fills_nor_cancels():
    """첫 실행: 판정 근거가 없으므로 체결하지 않지만, 남의 주문을 취소하지도 않습니다."""
    client = _client(orders=[_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00")])
    summary = _run(client, previous_probe=None)
    assert summary["freshness"]["status"] == duel_batch.CRAWL_NO_BASELINE
    assert summary["pending_held"] == 1
    assert client.calls_for(duel_db.ORDERS_TABLE, "update") == []


def test_dry_run_writes_nothing():
    client = _client(
        accounts=_accounts(1),
        orders=[_order("o-1", "acc-1", "000001", 3, "2026-08-19T19:00:00+09:00")],
    )
    summary = _run(client, close_price_of=_price_lookup({"000001": 10_000.0}), dry_run=True)
    assert summary["dry_run"] is True
    assert summary["snapshots_written"] == 0
    for op in ("insert", "update", "upsert", "delete"):
        assert client.calls_for(op=op) == [], f"dry-run 인데 {op} 를 보냈습니다"


# =============================================================================
# 8. 스냅샷 행 만들기 (1-5 / 2-5-4)
# =============================================================================
def test_snapshot_row_for_a_cash_only_account():
    """
    보유 종목이 0개이고 현금만 있는 계좌도 **정상적으로 행이 생깁니다**
    (스키마 §5 의 `priced_count > 0 or position_value = 0` 이 이 경우를 위해 열려 있습니다).
    """
    rows = duel_batch.build_snapshot_rows(
        _accounts(1), {}, {"acc-1": 10_000_000.0}, {}, {}, TARGET_DATE)
    row = rows[0]
    assert row["position_value"] == 0
    assert row["priced_count"] == 0 and row["unpriced_count"] == 0
    assert row["total_value"] == row["cash_balance"] == 10_000_000.0
    assert row["cash_flow_amount"] == 0.0 and row["cash_flow_kind"] is None
    assert row["holdings"] == []
    duel_db._validate_daily_snapshot(row, TARGET_DATE.isoformat())


def test_snapshot_row_with_positions_and_an_unpriced_one():
    """
    가격을 모르는 종목은 평가액에 **넣지 않고** `unpriced_count` 로 셉니다.
    0원으로 치면 다음 날 가격이 들어오는 순간 "하루 만에 폭등"이 됩니다(§0-1).
    """
    positions = {"acc-1": [
        {"ticker": "000001", "stock_name": "합성1", "quantity": 10, "avg_cost": 9_000.0,
         "status": "active"},
        {"ticker": "000002", "stock_name": "합성2", "quantity": 5, "avg_cost": 4_000.0,
         "status": "active"},
    ]}
    rows = duel_batch.build_snapshot_rows(
        _accounts(1), positions, {"acc-1": 1_000.0},
        {"000001": 10_000.0}, {}, TARGET_DATE)
    row = rows[0]

    assert row["position_value"] == 100_000.0                 # 000002 는 빠짐
    assert row["priced_count"] == 1 and row["unpriced_count"] == 1
    assert row["total_cost"] == 10 * 9_000.0 + 5 * 4_000.0
    assert row["total_value"] == 101_000.0
    unpriced = [h for h in row["holdings"] if h["ticker"] == "000002"][0]
    assert unpriced["priced"] is False
    assert unpriced["close_price"] is None and unpriced["market_value"] is None
    duel_db._validate_daily_snapshot(row, TARGET_DATE.isoformat())
    for holding in row["holdings"]:
        duel_db._validate_holding_snapshot(holding, TARGET_DATE.isoformat())


def test_delisted_position_is_a_confirmed_zero_not_an_unknown():
    """
    상장폐지는 **확인된 0원**입니다(3-1). "가격 수집 실패"(둘 다 NULL)와 같은 모양이 되면
    안 됩니다 — 스키마 §5 주석이 정한 표현을 그대로 따릅니다.
    """
    positions = {"acc-1": [{"ticker": "000009", "stock_name": "폐지주", "quantity": 10,
                            "avg_cost": 5_000.0, "status": "delisted",
                            "delisted_date": "2026-08-01"}]}
    row = duel_batch.build_snapshot_rows(
        _accounts(1), positions, {"acc-1": 0.0}, {}, {}, TARGET_DATE)[0]
    holding = row["holdings"][0]
    assert holding["priced"] is True
    assert holding["close_price"] == 0.0 and holding["market_value"] == 0.0
    assert row["position_value"] == 0.0
    assert row["total_cost"] == 50_000.0          # 손실이 손실로 보이게 원가는 남습니다
    duel_db._validate_holding_snapshot(holding, TARGET_DATE.isoformat())


def test_total_value_is_the_sum_of_two_observations():
    """총자산은 따로 계산한 값이 아니라 평가액 + 현금이어야 합니다(DB CHECK 와 같은 규칙)."""
    positions = {"acc-1": [{"ticker": "000001", "stock_name": "합성1",
                            "quantity": 3, "avg_cost": 1_111.11, "status": "active"}]}
    row = duel_batch.build_snapshot_rows(
        _accounts(1), positions, {"acc-1": 3_333.33},
        {"000001": 1_234.56}, {}, TARGET_DATE)[0]
    assert row["total_value"] == pytest.approx(row["position_value"] + row["cash_balance"])
    duel_db._validate_daily_snapshot(row, TARGET_DATE.isoformat())


# =============================================================================
# 9. 외부 현금흐름 이월 — TWR 이 입금을 수익으로 세지 않게 (2-6)
# =============================================================================
def test_cash_flow_only_counts_seed_and_monthly_deposit():
    """매수(`buy`)는 외부 현금흐름이 아닙니다 — 계좌 안에서 형태만 바뀐 것입니다."""
    ledger = [
        {"account_id": "acc-1", "event_type": "seed", "amount": 10_000_000,
         "event_date": "2026-08-20"},
        {"account_id": "acc-1", "event_type": "buy", "amount": -30_000,
         "event_date": "2026-08-20"},
    ]
    flows = duel_batch.collect_external_cash_flows(ledger, {}, TARGET_DATE)
    assert flows["acc-1"] == {"amount": 10_000_000.0, "kind": "seed"}


def test_cash_flow_carries_forward_over_skipped_snapshot_days():
    """
    🔴 수집 실패로 스냅샷을 건너뛴 날의 입금이 사라지면, 다음 스냅샷에서 그 입금이
       **수익으로 둔갑**합니다. 직전 스냅샷 이후의 흐름을 전부 합쳐야 합니다.
    """
    ledger = [
        {"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
         "event_date": "2026-08-10"},                 # 이 날은 수집 실패로 스냅샷 없음
        {"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
         "event_date": "2026-08-20"},
    ]
    flows = duel_batch.collect_external_cash_flows(
        ledger, {"acc-1": date(2026, 8, 9)}, TARGET_DATE)
    assert flows["acc-1"]["amount"] == 1_600_000.0
    assert flows["acc-1"]["kind"] == "monthly_deposit"


def test_cash_flow_does_not_double_count_already_recorded_days():
    """직전 스냅샷에 이미 반영된 입금을 두 번 세지 않습니다."""
    ledger = [{"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
               "event_date": "2026-08-10"}]
    flows = duel_batch.collect_external_cash_flows(
        ledger, {"acc-1": date(2026, 8, 10)}, TARGET_DATE)
    assert flows == {}


def test_cash_flow_kind_is_mixed_when_both_happen():
    """개설일이 마침 10일이면 시드와 정기입금이 같은 구간에 들어옵니다 → 'mixed'(스키마 §5)."""
    ledger = [
        {"account_id": "acc-1", "event_type": "seed", "amount": 10_000_000,
         "event_date": "2026-08-10"},
        {"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
         "event_date": "2026-08-10"},
    ]
    flows = duel_batch.collect_external_cash_flows(ledger, {}, TARGET_DATE)
    assert flows["acc-1"]["kind"] == duel_batch.CASH_FLOW_KIND_MIXED
    assert flows["acc-1"]["amount"] == 10_800_000.0


def test_cash_flow_ignores_events_after_the_snapshot_date():
    ledger = [{"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
               "event_date": "2026-09-10"}]
    assert duel_batch.collect_external_cash_flows(ledger, {}, TARGET_DATE) == {}


# =============================================================================
# 10. TWR (2-6) — 현금만 들고 있는 계좌는 0%, 입금을 수익으로 세지 않기
# =============================================================================
def test_twr_of_a_cash_only_account_is_zero_even_after_deposits():
    """
    시드 1천만 + 정기입금 80만이 들어와도 아무것도 안 샀으면 TWR 은 **0%** 여야 합니다.
    단순 수익률이라면 +8% 로 보일 시나리오입니다(2-6 이 단순 수익률을 버린 이유).
    """
    history = [
        {"account_id": "acc-1", "snapshot_date": "2026-08-19",
         "total_value": 10_000_000.0, "cash_flow_amount": 10_000_000.0},
    ]
    new_rows = duel_batch.build_snapshot_rows(
        _accounts(1), {}, {"acc-1": 10_800_000.0}, {},
        {"acc-1": {"amount": 800_000.0, "kind": "monthly_deposit"}}, TARGET_DATE)
    twr = duel_batch.compute_twr_by_account(history, new_rows)["acc-1"]
    assert twr["status"] == duel_rules.TWR_OK
    assert twr["twr_pct"] == pytest.approx(0.0)


def test_twr_reflects_real_gains():
    history = [{"account_id": "acc-1", "snapshot_date": "2026-08-19",
                "total_value": 10_000_000.0, "cash_flow_amount": 10_000_000.0}]
    new_rows = duel_batch.build_snapshot_rows(
        _accounts(1), {}, {"acc-1": 11_000_000.0}, {}, {}, TARGET_DATE)
    twr = duel_batch.compute_twr_by_account(history, new_rows)["acc-1"]
    assert twr["twr_pct"] == pytest.approx(10.0)


def test_twr_rerun_does_not_duplicate_today():
    """배치를 두 번 돌려도 오늘 날짜가 두 번 들어가 예외가 나지 않아야 합니다."""
    history = [
        {"account_id": "acc-1", "snapshot_date": "2026-08-19",
         "total_value": 10_000_000.0, "cash_flow_amount": 10_000_000.0},
        {"account_id": "acc-1", "snapshot_date": TARGET_DATE.isoformat(),
         "total_value": 9_000_000.0, "cash_flow_amount": 0.0},
    ]
    new_rows = duel_batch.build_snapshot_rows(
        _accounts(1), {}, {"acc-1": 11_000_000.0}, {}, {}, TARGET_DATE)
    twr = duel_batch.compute_twr_by_account(history, new_rows)["acc-1"]
    assert twr["period_count"] == 1
    assert twr["twr_pct"] == pytest.approx(10.0)     # 새 행이 이깁니다


def test_batch_carries_the_deposit_into_the_snapshot_cash_flow():
    """배치 전체를 돌렸을 때, 그날 입금이 스냅샷의 `cash_flow_amount` 로 들어가는지."""
    accounts = _accounts(1)
    ledger = _seed_ledger(accounts) + [
        {"account_id": "acc-1", "event_type": "monthly_deposit", "amount": 800_000,
         "event_date": DEPOSIT_DATE.isoformat()}]
    client = _client(accounts=accounts, ledger=ledger,
                     deposits_already=[{"account_id": "acc-1"}])
    summary = _run(
        client, target_date=DEPOSIT_DATE,
        today_probe=_probe(DEPOSIT_DATE, kospi=3210.0, stock_prices=_stock_prices(bump=5.0)),
    )
    assert summary["snapshots_written"] == 1
    row = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "upsert").rows[0]
    assert row["cash_flow_amount"] == 10_800_000.0        # 첫 스냅샷이라 시드까지 함께
    assert row["cash_flow_kind"] == duel_batch.CASH_FLOW_KIND_MIXED


# =============================================================================
# 11. 🔴 §0-3-2 회귀 고정 — 계좌 수가 늘어도 왕복 횟수가 그대로인가
# =============================================================================
@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_batch_query_count_does_not_grow_with_accounts(account_count):
    """
    🔴 작업지시서 2-7 이 명시적으로 요구한 회귀 테스트를, 이번엔 **배치 전체**에 겁니다
    (`tests/test_duel_db.py::test_apply_monthly_deposits_is_one_insert_...` 와 같은 방식).

    주문이 하나도 없는 평범한 날: 읽기는 계좌·원장·주문·포지션·스냅샷 **각 1회씩 = 5회**,
    쓰기는 스냅샷 합계 upsert 만(종목별은 보유가 없으니 0). 계좌가 900개여도 그대로입니다.
    (900행은 CHUNK_SIZE(200)로 잘려 upsert 가 5번이 됩니다 — 그건 요청 크기를 자르는 것이지
     계좌마다 부르는 것이 아닙니다.)
    """
    accounts = _accounts(account_count)
    client = _client(accounts=accounts)
    summary = _run(client)

    assert summary["snapshots_written"] == account_count
    selects = client.calls_for(op="select")
    assert len(selects) == 5, [(call.table, call.filters) for call in selects]
    for table in (duel_db.ACCOUNTS_TABLE, duel_db.LEDGER_TABLE, duel_db.ORDERS_TABLE,
                  duel_db.POSITIONS_TABLE, duel_db.DAILY_SNAPSHOTS_TABLE):
        assert len(client.calls_for(table, "select")) == 1, table

    expected_chunks = -(-account_count // duel_db.CHUNK_SIZE)
    assert len(client.calls_for(duel_db.DAILY_SNAPSHOTS_TABLE, "upsert")) == expected_chunks
    assert client.calls_for(duel_db.HOLDING_SNAPSHOTS_TABLE) == []
    assert len(client.calls) == 5 + expected_chunks


def test_batch_reads_the_ledger_with_one_in_filter():
    """원장·포지션·스냅샷은 계좌 목록을 `in` 필터 하나로 넘겨 한 번에 읽습니다."""
    accounts = _accounts(4)
    client = _client(accounts=accounts)
    _run(client)
    for table in (duel_db.LEDGER_TABLE, duel_db.POSITIONS_TABLE,
                  duel_db.DAILY_SNAPSHOTS_TABLE):
        call = client.only_call(table, "select")
        assert ("in", "account_id", [row["id"] for row in accounts]) in call.filters


def test_fill_updates_scale_with_orders_not_with_accounts():
    """
    체결 결과 update 만 "그날 실제 체결된 주문 수"만큼 나갑니다(PostgREST 제약 —
    `duel_db.record_order_fills()` 주석 참고). 계좌 수가 아니라 **일한 만큼**인지 확인합니다.
    """
    accounts = _accounts(20)
    orders = [_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00"),
              _order("o-2", "acc-2", "000001", 1, "2026-08-19T19:30:00+09:00")]
    client = _client(accounts=accounts, orders=orders)
    _run(client, close_price_of=_price_lookup({"000001": 10_000.0}))
    assert len(client.calls_for(duel_db.ORDERS_TABLE, "update")) == len(orders)
    # 원장·포지션 쓰기는 각각 한 번(집합 연산).
    assert len(client.calls_for(duel_db.LEDGER_TABLE, "insert")) == 1
    assert len(client.calls_for(duel_db.POSITIONS_TABLE, "upsert")) == 1


# =============================================================================
# 12. 계층 분리 — 배치가 규칙을 다시 구현하지 않았는지
# =============================================================================
def test_batch_module_does_not_reimplement_the_rules():
    """
    체결·평단가·TWR·신선도 판정의 단일 출처는 `utils/duel_rules.py` 입니다. 배치가 그
    계산을 복사해 오면 언젠가 둘 중 하나만 고쳐지고, 화면 숫자와 DB 값이 갈라집니다(§0-3-10).
    """
    import ast
    source = (REPO_ROOT / "utils" / "duel_batch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            skip.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    executable = "\n".join(line for number, line in enumerate(source.splitlines(), start=1)
                           if number not in skip and not line.lstrip().startswith("#"))

    for reimplementation in ("math.floor", "// price", "chain *=", "Decimal("):
        assert reimplementation not in executable, f"{reimplementation} 를 여기서 다시 짜지 마세요"
    # 금액 상수도 다시 적지 않습니다(단일 출처는 duel_rules).
    assert "10_000_000" not in executable and "800_000" not in executable
    # 그리고 규칙 함수를 실제로 부르고 있는지.
    for called in ("allocate_pending_orders", "apply_buy_fill_to_position",
                   "check_crawl_freshness", "crawl_status_allows_fill", "compute_twr"):
        assert f"duel_rules.{called}(" in executable, called


def test_batch_does_not_open_files_or_the_network_except_the_state_file():
    """
    이 파일은 기준값 파일 하나 말고는 아무것도 열지 않습니다(오프라인 테스트 가능성의 전제).
    requests·supabase 를 import 하는 순간 4단계의 "네트워크 없이 검증"이 깨집니다.
    """
    source = (REPO_ROOT / "utils" / "duel_batch.py").read_text(encoding="utf-8")
    executable = "\n".join(line for line in source.splitlines()
                           if not line.lstrip().startswith("#"))
    assert "import requests" not in executable
    assert "from supabase" not in executable and "import supabase" not in executable
    # open() 은 기준값 파일 읽기/쓰기 두 곳뿐입니다.
    assert executable.count("open(") == 2


def test_every_public_function_has_a_docstring():
    """이 저장소의 관례(§0-1 — 코드가 왜 그런지 남기기)."""
    import inspect
    missing = [name for name, function in vars(duel_batch).items()
               if inspect.isfunction(function)
               and function.__module__ == duel_batch.__name__
               and not name.startswith("_")
               and not (function.__doc__ or "").strip()]
    assert missing == []


# =============================================================================
# 13. 요약 출력 — 오너가 GitHub Actions 로그에서 실제로 보는 것 (2-5)
# =============================================================================
def test_summary_lines_are_readable_korean():
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "000001", 3, "2026-08-19T19:00:00+09:00")])
    summary = _run(client, close_price_of=_price_lookup({"000001": 10_000.0}))
    text = "\n".join(duel_batch.format_summary_lines(summary))

    assert "결투 야간 배치 요약" in text
    assert "수집 신선도" in text
    assert "전량체결 1" in text
    assert "일별 스냅샷: 1행" in text
    assert TARGET_DATE.isoformat() in text


def test_summary_shows_the_deposit_line_on_a_non_deposit_day():
    client = _client()
    summary = _run(client)
    text = "\n".join(duel_batch.format_summary_lines(summary))
    assert "정기 입금: 오늘은 입금일" in text


def test_summary_shows_the_held_state_loudly():
    client = _client(orders=[_order("o-1", "acc-1", "000001", 1, "2026-08-19T19:00:00+09:00")])
    summary = _run(
        client,
        today_probe=_probe(TARGET_DATE, kospi=3210.0,
                           stock_prices=_stock_prices(bump=5.0, unchanged=20)),
        previous_probe=_probe(YESTERDAY, kospi=3200.0, stock_prices=_stock_prices()),
    )
    text = "\n".join(duel_batch.format_summary_lines(summary))
    assert "⚠️" in text and "보류" in text


# =============================================================================
# 14. 이번 작업에서 `utils/duel_db.py` 에 새로 넣은 일괄 조회 2개
#     (배치가 계좌별로 조회하지 않기 위해 필요했던 함수들 — §0-3-2)
# =============================================================================
def test_fetch_positions_for_accounts_is_one_query_with_an_in_filter():
    client = FakeClient(responses={(duel_db.POSITIONS_TABLE, "select"): [
        {"account_id": "acc-1", "ticker": "000001", "quantity": 3, "avg_cost": 100.0},
    ]})
    rows = duel_db.fetch_positions_for_accounts(client, ["acc-1", "acc-2"])

    assert len(rows) == 1
    call = client.only_call(duel_db.POSITIONS_TABLE, "select")
    assert ("in", "account_id", ["acc-1", "acc-2"]) in call.filters
    assert call.orders == [("account_id", False), ("ticker", False)]


def test_fetch_positions_for_accounts_sends_no_query_for_an_empty_list():
    """대상이 없으면 빈 `in` 필터를 보내지 않습니다(위 `fetch_cash_ledger_for_accounts` 와 동일)."""
    client = FakeClient()
    assert duel_db.fetch_positions_for_accounts(client, []) == []
    assert client.calls == []


def test_fetch_daily_snapshots_for_accounts_reads_the_whole_history_by_default():
    """
    기본값은 **기간을 자르지 않는 것**입니다 — 누적 TWR 은 개설일부터의 스냅샷이 다 있어야
    첫 구간의 분모가 생깁니다(2-6).
    """
    client = FakeClient(responses={(duel_db.DAILY_SNAPSHOTS_TABLE, "select"): []})
    duel_db.fetch_daily_snapshots_for_accounts(client, ["acc-1"])
    call = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "select")
    assert [op for op, _column, _value in call.filters] == ["in"]
    assert call.orders == [("account_id", False), ("snapshot_date", False)]


def test_fetch_daily_snapshots_for_accounts_can_be_bounded():
    client = FakeClient(responses={(duel_db.DAILY_SNAPSHOTS_TABLE, "select"): []})
    duel_db.fetch_daily_snapshots_for_accounts(client, None,
                                               start_date="2026-08-01", end_date=date(2026, 8, 20))
    call = client.only_call(duel_db.DAILY_SNAPSHOTS_TABLE, "select")
    assert call.filter_map == {"snapshot_date": "2026-08-20"}      # gte 뒤에 lte 가 덮어씀
    assert ("gte", "snapshot_date", "2026-08-01") in call.filters
    assert ("lte", "snapshot_date", "2026-08-20") in call.filters


def test_new_batch_reads_are_in_the_service_role_section_only():
    """
    새로 넣은 두 조회는 **B 절(배치 전용)** 에 있어야 합니다. A 절(사용자 세션)에 들어가면
    화면이 남의 계좌까지 읽는 코드 경로가 생깁니다(§0-3-8).
    """
    source = (REPO_ROOT / "utils" / "duel_db.py").read_text(encoding="utf-8")
    user_section = source[source.index("#  A 절 —"):source.index("#  B 절 —")]
    for name in ("fetch_positions_for_accounts", "fetch_daily_snapshots_for_accounts"):
        assert f"def {name}(" not in user_section, f"{name} 이 A 절에 있습니다"
        assert f"def {name}(" in source


def test_twr_failure_for_one_account_does_not_kill_the_batch():
    """
    TWR 은 로그용입니다. 계좌 하나가 계산 불가(과거 어느 날 총자산 0 → 분모 없음)여도
    **배치를 죽이면 안 됩니다** — 그 시점엔 이미 체결·원장이 기록된 뒤라 반쪽 상태가 남습니다.
    """
    history = [{"account_id": "acc-1", "snapshot_date": "2026-08-19",
                "total_value": 0.0, "cash_flow_amount": 0.0}]
    new_rows = duel_batch.build_snapshot_rows(
        _accounts(1), {}, {"acc-1": 1_000.0}, {}, {}, TARGET_DATE)
    twr = duel_batch.compute_twr_by_account(history, new_rows)["acc-1"]
    assert twr["status"] == duel_batch.TWR_ERROR
    assert twr["twr_pct"] is None
    assert twr["error"]


def test_batch_surfaces_a_twr_failure_as_a_warning():
    """계산 불가를 조용히 삼키지 않고 요약 경고로 올립니다(§0-1)."""
    client = _client(
        accounts=_accounts(1),
        snapshots=[{"account_id": "acc-1", "snapshot_date": "2026-08-19",
                    "total_value": 0.0, "cash_flow_amount": 0.0}],
    )
    summary = _run(client)
    assert summary["snapshots_written"] == 1        # 스냅샷은 정상 적재
    assert any("누적 TWR 을 계산하지 못했습니다" in warning for warning in summary["warnings"])
