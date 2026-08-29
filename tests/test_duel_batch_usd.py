# tests/test_duel_batch_usd.py
"""
⚔️ "결투다!" USD 트랙 — 야간 배치(`utils/duel_batch_usd.py`) 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · 실제 `data/*.json` 불필요)

`tests/test_duel_batch.py`(원화)와 짝을 이룹니다. 순수 판정·계산 로직(신선도 점검표·FIFO
체결·스냅샷·TWR)은 원화 파일에서 **그대로 재사용**하므로 그 로직 자체는 이미
`tests/test_duel_batch.py`가 exhaustively 검증했습니다 — 여기서 다시 반복하지 않습니다.
이 파일이 확인하는 것은 USD 트랙만의 위험 지점입니다:

    ① 재사용해야 할 순수 함수가 정말 원화 모듈과 **같은 객체**인지(재정의 회귀 방지).
    ② `run_nightly_batch_usd()`가 `duel_db_usd.*`(원화 `duel_db.*`가 아님)를 부르는지 —
       배치 전체를 한 번 돌려 어느 표에 질의가 갔는지로 확인합니다.
    ③ 🔴 **날짜 분리**(이 라운드의 핵심 설계) — 정기입금은 `today_kst`(배치 실행일) 기준으로,
       체결·스냅샷·신선도는 `target_date`(확정하려는 미국 거래일) 기준으로 갈라지는지.
    ④ USD 신선도 기준값 파일 이름이 원화와 다른지(같은 파일을 공유하면 안 되므로).
    ⑤ §0-3-2 — 계좌 수와 무관하게 질의 횟수가 고정되는지(USD 배치에도 그대로 적용).
    ⑥ `format_summary_lines_usd()`가 "원"이 아니라 "$"를 쓰는지(원화 함수를 그대로 썼다면
       틀렸을 지점).

실행: pytest tests/test_duel_batch_usd.py -v
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
# 가짜 Supabase 클라이언트는 `tests/test_duel_db.py`가 갖고 있습니다(§0-3-10 — 흉내도 단일
# 출처로). `tests/test_duel_batch.py`·`tests/test_duel_publish.py`와 같은 관례입니다.
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient  # noqa: E402
from utils import duel_batch, duel_batch_usd, duel_db, duel_db_usd, duel_rules  # noqa: E402
from utils.duel_batch_usd import DuelBatchError  # noqa: E402
from utils.duel_rules import KST  # noqa: E402

TARGET_DATE = date(2026, 8, 19)      # 확정하려는 미국 거래일(수요일)
TODAY_KST = date(2026, 8, 20)        # 배치가 실제로 도는 한국 날짜(목요일, 입금일 아님)
DEPOSIT_TODAY_KST = date(2026, 9, 10)  # 배치 실행일이 입금일인 경우
YESTERDAY_TARGET = date(2026, 8, 18)


# =============================================================================
# 0. 재사용 정체성 — 원화 모듈과 같은 객체인지 (재정의 회귀 방지)
# =============================================================================
@pytest.mark.parametrize("name", [
    "select_probe_stocks", "build_freshness_probe", "load_probe_state", "save_probe_state",
    "judge_crawl_freshness", "resolve_action", "plan_order_fills", "last_snapshot_dates",
    "collect_external_cash_flows", "build_snapshot_rows", "compute_twr_by_account",
    "is_monthly_deposit_date", "default_state_dir",
    "_to_date", "_positive_price", "_round6",
])
def test_shared_batch_helpers_are_the_same_object_as_the_krw_module(name):
    """순수 판정·계산 함수는 원화 모듈에서 **그대로** 가져다 씁니다(재정의하면 두 벌이 됩니다)."""
    assert getattr(duel_batch_usd, name) is getattr(duel_batch, name), \
        f"{name} 이 duel_batch 와 같은 객체가 아닙니다(재정의됐을 가능성)"


def test_format_summary_lines_usd_is_deliberately_not_the_krw_function():
    """
    🔴 유일한 의도적 예외 — 원화 `format_summary_lines()`에는 "…원"이 리터럴로 박혀 있어
    그대로 재사용하면 달러 금액에 원화 단위가 찍힙니다. 그래서 이 함수만 새로 정의했다는
    사실 자체를 회귀로 고정합니다.
    """
    assert duel_batch_usd.format_summary_lines_usd is not duel_batch.format_summary_lines


def test_probe_state_filename_usd_is_not_shared_with_krw():
    """USD 기준값 파일 이름이 원화와 다른지 — 같은 파일을 쓰면 비교 대상이 다른 시장이 됩니다."""
    assert duel_batch_usd.PROBE_STATE_FILENAME_USD != duel_batch.PROBE_STATE_FILENAME
    assert duel_batch_usd.PROBE_STATE_FILENAME_USD.endswith("_usd.json")
    assert duel_batch_usd.default_state_path_usd() != duel_batch.default_state_path()


def test_probe_index_keys_spec_usd_matches_report_db_benchmark_keys():
    """
    이 트랙이 점검에 넣는 지수 키 리터럴이 `utils/report_db.py::US_BENCHMARK_KEYS`(단일
    출처)와 어긋나지 않는지. `duel_batch_usd.py`는 그 모듈을 import 하지 않으므로(배치
    판단 계층에 파일 I/O 상수를 끌어오지 않기 위해), 여기서 문자열 그대로 대조합니다.
    """
    from utils import report_db
    assert tuple(duel_batch_usd.PROBE_INDEX_KEYS_SPEC_USD) == tuple(report_db.US_BENCHMARK_KEYS)


# =============================================================================
# 1. 픽스처
# =============================================================================
def _index_probe(target_date, *, sp500=500.0, nasdaq=300.0, stock_prices=None):
    values = {"SP500_PROXY_SPY": sp500, "NASDAQ_PROXY_ONEQ": nasdaq}
    values.update(stock_prices or {})
    return {
        "version": duel_batch_usd.PROBE_STATE_VERSION,
        "generated_at_kst": datetime(2026, 8, 20, 11, 0, tzinfo=KST).isoformat(),
        "target_date": target_date.isoformat() if hasattr(target_date, "isoformat")
        else str(target_date),
        "index_keys": ["SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ"],
        "values": values,
    }


def _stock_prices(count=50, *, bump=0.0, unchanged=0):
    prices = {}
    for index in range(1, count + 1):
        base = 100.0 + index
        prices[f"{index:04d}"] = base if index <= unchanged else base + bump
    return prices


def _ok_probes():
    """신선도 'ok'가 나오는 오늘/전일 점검표 한 쌍(지수·상위 50종목 모두 충분히 변동)."""
    today = _index_probe(TARGET_DATE, sp500=505.0, nasdaq=303.0,
                         stock_prices=_stock_prices(bump=5.0))
    previous = _index_probe(YESTERDAY_TARGET, sp500=500.0, nasdaq=300.0,
                            stock_prices=_stock_prices())
    return today, previous


def _accounts(count=2):
    return [{"id": f"acc-{index}", "user_id": f"user-{index}",
             "window_type": duel_rules.ACCOUNT_WINDOW_TYPES[index % 3],
             "seed_amount": duel_rules.SEED_AMOUNT_USD, "currency": "USD",
             "anchor_date": "2026-07-01", "status": "active"}
            for index in range(1, count + 1)]


def _seed_ledger(accounts, *, event_date="2026-07-01", amount=None):
    """계좌에 체결 자금을 대는 시드 원장 행(기본값: `duel_rules.SEED_AMOUNT_USD`)."""
    value = amount if amount is not None else duel_rules.SEED_AMOUNT_USD
    return [{"account_id": account["id"], "event_type": "seed",
             "amount": value, "event_date": event_date} for account in accounts]


def _order(order_id, account_id, ticker, quantity, saved_at, *, target_date=TARGET_DATE):
    return {"id": order_id, "account_id": account_id, "ticker": ticker,
            "stock_name": f"합성{ticker}", "requested_quantity": quantity,
            "side": "buy", "status": duel_rules.ORDER_PENDING,
            "saved_at": saved_at, "target_date": target_date.isoformat()}


def _client(*, accounts=None, ledger=None, orders=None, positions=None, snapshots=None,
           deposits_already=None, cancelled_rows=None, stale_pending_rows=None):
    """배치 한 판을 돌릴 수 있는 가짜 클라이언트(원화 `tests/test_duel_batch.py` 의 미러).

    🔴 2026-08-29 재감사 H-8 — 주문 표에 성격이 다른 update 가 둘입니다:
       ① 매 실행 맨 앞의 정체 주문 스윕(`target_date < 처리일`, `.lt` 필터) — 기본 0행
       ② 그날짜 일괄 취소 / 체결 결과 기록
    """
    accounts = accounts if accounts is not None else _accounts()
    ledger = ledger if ledger is not None else []

    def ledger_select(query):
        if query.filter_map.get("event_type") == "monthly_deposit":
            return list(deposits_already or [])
        return list(ledger)

    def orders_update(query):
        if any(op == "lt" and column == "target_date" for op, column, _v in query.filters):
            return list(stale_pending_rows or [])
        if cancelled_rows is not None:
            return list(cancelled_rows)
        return [dict(row) for row in query.rows]

    return FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): list(accounts),
        (duel_db_usd.LEDGER_TABLE_USD, "select"): ledger_select,
        (duel_db_usd.ORDERS_TABLE_USD, "select"): list(orders or []),
        (duel_db_usd.ORDERS_TABLE_USD, "update"): orders_update,
        (duel_db_usd.POSITIONS_TABLE_USD, "select"): list(positions or []),
        (duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select"): list(snapshots or []),
    })


def _stale_sweep_calls(client):
    """H-8 정체 주문 스윕 update 호출들."""
    return [call for call in client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "update")
            if any(op == "lt" and column == "target_date" for op, column, _v in call.filters)]


def _hold_annotation_calls(client):
    """M-10 보류 사유 기록 update 호출들(payload 에 `status` 가 없는 것이 표식) — 원화와 동일."""
    return [call for call in client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "update")
            if "status" not in (call.payload or {})]


def _order_updates_excluding_stale_sweep(client):
    """**주문 상태를 바꾸는** update 호출들(체결 결과 기록 · 그날짜 일괄 취소).
    스윕(H-8)과 보류 사유 기록(M-10)은 뺍니다 — 원화 파일과 같은 이유입니다."""
    ignored = set(id(call) for call in _stale_sweep_calls(client))
    ignored |= set(id(call) for call in _hold_annotation_calls(client))
    return [call for call in client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "update")
            if id(call) not in ignored]


def _run(client, **kwargs):
    today_probe, previous_probe = _ok_probes()
    options = {
        "today_probe": today_probe,
        "previous_probe": previous_probe,
        "close_price_of": lambda ticker: None,
        "today_kst": TODAY_KST,
        "log": lambda *args, **kw: None,
    }
    target_date = kwargs.pop("target_date", TARGET_DATE)
    options.update(kwargs)
    return duel_batch_usd.run_nightly_batch_usd(client, target_date, **options)


# =============================================================================
# 2. 표 배선 — USD 표에만 가는지 (KRW 표를 실수로 부르면 여기서 잡힙니다)
# =============================================================================
def test_batch_usd_only_touches_usd_tables_never_krw_tables():
    from utils import duel_db
    accounts = _accounts(3)
    client = _client(accounts=accounts)
    _run(client)

    touched = {call.table for call in client.calls}
    krw_tables = {duel_db.ACCOUNTS_TABLE, duel_db.LEDGER_TABLE, duel_db.ORDERS_TABLE,
                 duel_db.POSITIONS_TABLE, duel_db.DAILY_SNAPSHOTS_TABLE}
    assert not (touched & krw_tables), f"KRW 표에 질의가 갔습니다: {touched & krw_tables}"
    assert duel_db_usd.ACCOUNTS_TABLE_USD in touched
    assert duel_db_usd.LEDGER_TABLE_USD in touched
    assert duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD in touched


def test_batch_usd_reads_accounts_ledger_and_writes_snapshots_on_a_good_day():
    accounts = _accounts(2)
    client = _client(accounts=accounts)
    summary = _run(client)

    assert summary["freshness"]["status"] == duel_rules.CRAWL_OK
    assert summary["account_count"] == 2
    assert summary["snapshots_written"] == 2
    # 정기입금 따라잡기(H-7)도 활성 계좌를 읽으므로 호출이 여럿입니다 — 전부 같은 필터인지
    # (= 계좌 상태를 보는 조건이 한 가지인지) 확인합니다.
    account_selects = client.calls_for(duel_db_usd.ACCOUNTS_TABLE_USD, "select")
    assert account_selects
    assert all(call.filter_map == {"status": "active"} for call in account_selects)


# =============================================================================
# 3. 🔴 날짜 분리 — target_date(확정 거래일) vs today_kst(배치 실행일, 입금 전용)
# =============================================================================
def test_deposit_uses_today_kst_not_target_date():
    """
    정기입금 판정·event_date 는 `today_kst`(배치 실행일)를 씁니다 — 원화 배치라면 있을 수
    없는 분기라 이 테스트로만 지킵니다.

    🔴 2026-08-29 재감사 H-7 로 검사 방식이 바뀌었습니다. 이제 "그날이 10일인가" 하나가
    아니라 **최근 구간의 모든 10일**을 보므로(밀린 달을 놓치지 않기 위해), 확인할 것은
    "10일이 아니면 아예 시도하지 않는가"가 아니라 **"어느 날짜 축을 기준으로 구간을
    잡는가"** 입니다: `today_kst`(실행일)이지 `target_date`(거래일)가 아닙니다.
    """
    accounts = _accounts(2)

    # target_date 가 9/10 이어도 구간은 today_kst(8/20) 기준이라 9/10 은 들어가지 않습니다.
    client_a = _client(accounts=accounts)
    summary_a = _run(client_a, target_date=date(2026, 9, 10), today_kst=TODAY_KST)
    dates_a = {row["event_date"]
               for call in client_a.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert")
               for row in call.rows}
    assert dates_a == {d.isoformat()
                       for d in duel_batch._pending_monthly_deposit_dates(TODAY_KST)}
    assert "2026-09-10" not in dates_a

    # today_kst 가 9/10 이면 그 날짜분이 들어갑니다(target_date 는 8/19 그대로).
    client_b = _client(accounts=accounts)
    summary_b = _run(client_b, target_date=TARGET_DATE, today_kst=DEPOSIT_TODAY_KST)
    assert summary_b["deposit_attempted"] is True
    pending_b = duel_batch._pending_monthly_deposit_dates(DEPOSIT_TODAY_KST)
    assert summary_b["deposit_applied"] == 2 * len(pending_b)
    deposit_rows = [row for call in client_b.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert")
                    for row in call.rows]
    # event_date 는 today_kst 축의 날짜들이지 target_date(거래일) 가 아닙니다.
    assert DEPOSIT_TODAY_KST.isoformat() in {row["event_date"] for row in deposit_rows}
    assert TARGET_DATE.isoformat() not in {row["event_date"] for row in deposit_rows}
    assert all(row["amount"] == duel_rules.MONTHLY_DEPOSIT_USD == 500 for row in deposit_rows)


def test_deposit_defaults_to_real_today_when_today_kst_is_omitted(monkeypatch):
    """`today_kst`를 생략하면 `datetime.now(KST).date()`를 씁니다(문서화된 기본값)."""
    import utils.duel_batch_usd as module

    fixed_now = datetime(2026, 9, 10, 13, 0, tzinfo=KST)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _FixedDatetime)
    accounts = _accounts(1)
    client = _client(accounts=accounts)
    summary = _run(client, today_kst=None)
    assert summary["deposit_attempted"] is True
    assert summary["today_kst"] == "2026-09-10"


def test_summary_reports_both_dates_when_they_differ():
    client = _client(accounts=_accounts(1))
    summary = _run(client, target_date=TARGET_DATE, today_kst=TODAY_KST)
    assert summary["target_date"] == TARGET_DATE.isoformat()
    assert summary["today_kst"] == TODAY_KST.isoformat()


def test_snapshot_and_cash_balance_reads_use_target_date_not_today_kst():
    """체결·스냅샷·잔고 조회는 여전히 `target_date`(거래일) 기준이어야 합니다(입금만 예외)."""
    accounts = _accounts(1)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")]
    client = _client(accounts=accounts, orders=orders)
    _run(client, target_date=TARGET_DATE, today_kst=DEPOSIT_TODAY_KST,
        close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)

    orders_call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "select")
    assert orders_call.filter_map == {"status": "pending", "target_date": TARGET_DATE.isoformat()}
    ledger_calls = client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "select")
    balance_call = next(c for c in ledger_calls if c.filter_map.get("event_type") != "monthly_deposit")
    assert ("lte", "event_date", TARGET_DATE.isoformat()) in balance_call.filters


# =============================================================================
# 4. 신선도 갈래 — 취소 / 보류 (재사용된 로직이 USD 표로 올바르게 배선됐는지만 확인)
# =============================================================================
def test_batch_usd_cancels_pending_orders_on_a_failed_day():
    same = _stock_prices()
    today_probe = _index_probe(TARGET_DATE, sp500=500.0, nasdaq=300.0, stock_prices=same)
    previous_probe = _index_probe(YESTERDAY_TARGET, sp500=500.0, nasdaq=300.0, stock_prices=same)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")]
    client = _client(accounts=_accounts(1))
    client.responses[(duel_db_usd.ORDERS_TABLE_USD, "update")] = [{"id": "o-1"}]

    summary = _run(client, today_probe=today_probe, previous_probe=previous_probe)
    assert summary["freshness"]["status"] == duel_rules.CRAWL_FAILED_OR_HOLIDAY
    assert summary["pending_cancelled"] == 1
    (call,) = _order_updates_excluding_stale_sweep(client)   # H-8 스윕은 제외
    assert "미국 정규장" in call.payload["fail_reason"]


def test_batch_usd_holds_orders_without_a_baseline():
    today_probe = _index_probe(TARGET_DATE)
    client = _client(accounts=_accounts(1),
                    orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")])
    summary = _run(client, today_probe=today_probe, previous_probe=None)
    assert summary["freshness"]["status"] == duel_batch_usd.CRAWL_NO_BASELINE
    assert summary["pending_held"] == 1
    assert _order_updates_excluding_stale_sweep(client) == []


def test_admin_override_fill_works_on_the_usd_batch():
    same = _stock_prices()
    today_probe = _index_probe(TARGET_DATE, sp500=500.0, nasdaq=300.0, stock_prices=same)
    previous_probe = _index_probe(YESTERDAY_TARGET, sp500=500.0, nasdaq=300.0, stock_prices=same)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")]
    accounts = _accounts(1)
    client = _client(accounts=accounts, orders=orders, ledger=_seed_ledger(accounts))
    summary = _run(client, today_probe=today_probe, previous_probe=previous_probe,
                  override=duel_batch_usd.OVERRIDE_FILL,
                  close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert summary["freshness"]["status"] == duel_rules.CRAWL_FAILED_OR_HOLIDAY
    assert summary["action"]["effective_status"] == duel_rules.CRAWL_OK
    assert summary["orders"]["filled"] == 1


# =============================================================================
# 5. 🔴 §0-3-2 — 계좌 수와 무관하게 질의 횟수가 고정되는지 (USD 배치 회귀)
# =============================================================================
@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_batch_usd_query_count_does_not_grow_with_accounts(account_count):
    accounts = _accounts(account_count)
    # 정기입금 따라잡기(H-7)가 0행으로 끝나게 해 두면, 이 테스트가 보려는 "왕복 수" 자체에
    # 집중할 수 있습니다(입금 insert 는 위 전용 테스트가 봅니다).
    client = _client(accounts=accounts,
                     deposits_already=[{"account_id": row["id"]} for row in accounts])
    summary = _run(client)

    assert summary["snapshots_written"] == account_count
    # 🔴 2026-08-29 재감사로 **고정된 숫자만** 늘었습니다(계좌 수 비례는 여전히 아닙니다):
    #    H-7 따라잡기(날짜당 계좌 1 + 중복 조회 1) · H-8 스윕 update 1 ·
    #    H-6 페이지네이션(페이지 1개면 왕복 1회 그대로).
    deposit_dates = duel_batch._pending_monthly_deposit_dates(TODAY_KST)
    deposit_selects = 2 * len(deposit_dates)
    selects = client.calls_for(op="select")
    assert len(selects) == 5 + deposit_selects, [(c.table, c.filters) for c in selects]
    assert len(client.calls_for(duel_db_usd.ACCOUNTS_TABLE_USD, "select")) \
        == 1 + len(deposit_dates)
    assert len(client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "select")) \
        == 1 + len(deposit_dates)
    for table in (duel_db_usd.ORDERS_TABLE_USD, duel_db_usd.POSITIONS_TABLE_USD,
                 duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD):
        assert len(client.calls_for(table, "select")) == 1, table

    expected_chunks = -(-account_count // duel_db_usd.CHUNK_SIZE)
    assert len(client.calls_for(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "upsert")) == expected_chunks
    assert len(_stale_sweep_calls(client)) == 1
    assert len(client.calls) == 5 + deposit_selects + expected_chunks + 1


def test_fill_updates_scale_with_orders_not_with_accounts_usd():
    accounts = _accounts(20)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T19:00:00+09:00"),
              _order("o-2", "acc-2", "AAPL", 1, "2026-08-19T19:30:00+09:00")]
    client = _client(accounts=accounts, orders=orders, ledger=_seed_ledger(accounts),
                     deposits_already=[{"account_id": row["id"]} for row in accounts])
    _run(client, close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert len(_order_updates_excluding_stale_sweep(client)) == len(orders)
    assert len(client.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert")) == 1
    assert len(client.calls_for(duel_db_usd.POSITIONS_TABLE_USD, "upsert")) == 1


# =============================================================================
# 6. dry-run — 아무것도 저장하지 않는지
# =============================================================================
def test_dry_run_writes_nothing_usd():
    accounts = _accounts(2)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T19:00:00+09:00")]
    client = _client(accounts=accounts, orders=orders)
    summary = _run(client, dry_run=True,
                  close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert summary["dry_run"] is True
    writes = client.calls_for(op="insert") + client.calls_for(op="update") \
        + client.calls_for(op="upsert") + client.calls_for(op="delete")
    assert writes == []


# =============================================================================
# 7. 요약 출력 — "$" 를 쓰지 "원"을 쓰지 않는지
# =============================================================================
def test_format_summary_lines_usd_uses_dollar_sign_not_won():
    accounts = _accounts(1)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")]
    client = _client(accounts=accounts, orders=orders, ledger=_seed_ledger(accounts))
    summary = _run(client, close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    lines = duel_batch_usd.format_summary_lines_usd(summary)
    joined = "\n".join(lines)
    assert "$150.00" in joined
    assert "원" not in joined
    assert "결투 USD 야간 배치 요약" in joined


def test_format_summary_lines_usd_shows_both_dates_in_the_header():
    client = _client(accounts=_accounts(1))
    summary = _run(client, target_date=TARGET_DATE, today_kst=TODAY_KST)
    joined = "\n".join(duel_batch_usd.format_summary_lines_usd(summary))
    assert TARGET_DATE.isoformat() in joined
    assert TODAY_KST.isoformat() in joined


# =============================================================================
# 8. None 클라이언트 — DuelDbError (배치 계층은 duel_db_usd 를 그대로 통과시킵니다)
# =============================================================================
def test_none_client_raises_a_catchable_error_usd():
    from utils.duel_db import DuelDbError
    today_probe, previous_probe = _ok_probes()
    with pytest.raises(DuelDbError):
        duel_batch_usd.run_nightly_batch_usd(
            None, TARGET_DATE, today_probe=today_probe, previous_probe=previous_probe,
            close_price_of=lambda t: None, today_kst=TODAY_KST, log=lambda *a, **k: None,
        )


# =============================================================================
# 9. 문서화 규율 — 공개 함수는 전부 docstring
# =============================================================================
def test_every_public_function_in_duel_batch_usd_has_a_docstring():
    import inspect
    missing = [name for name, function in vars(duel_batch_usd).items()
              if inspect.isfunction(function)
              and function.__module__ == duel_batch_usd.__name__
              and not name.startswith("_")
              and not (function.__doc__ or "").strip()]
    assert missing == [], f"docstring 없는 공개 함수: {missing}"


# =============================================================================
# 7. 창당 1회 리밸런싱 매도 (USD 미러 · 2026-08-21)
# =============================================================================
def test_batch_usd_settles_sells_through_the_usd_rpc_only():
    """
    🔴 USD 배치도 매도 정산을 **USD 전용 RPC** 로 보냅니다. 일반 upsert 로 보내면 공유
    트리거(`duel_positions_buy_only()`)가 그날 USD 포지션 저장을 통째로 거절하고,
    원화 RPC 로 보내면 다른 트랙의 표를 건드리게 됩니다.
    """
    accounts = _accounts(1)
    accounts[0]["first_holding_date"] = "2026-07-01"
    sell = _order("o-sell", accounts[0]["id"], "AAPL", 4, "2026-08-19T18:30:00+09:00")
    sell["side"] = "sell"
    sell["rebalance_window_index"] = 0
    position = {"account_id": accounts[0]["id"], "ticker": "AAPL", "stock_name": "애플",
                "quantity": 10, "avg_cost": 150.0, "status": "active", "delisted_date": None}

    client = _client(accounts=accounts, orders=[sell], positions=[position])
    summary = _run(client, close_price_of=lambda ticker: 200.0 if ticker == "AAPL" else None)

    assert summary["orders"]["sell_filled"] == 1
    assert summary["sold_amount_total"] == 800.0
    assert summary["sell_positions_settled"] == 1

    call = client.only_call(duel_db_usd.SETTLE_SELL_RPC_USD, "rpc")
    assert call.payload == {"p_rows": [
        {"account_id": accounts[0]["id"], "ticker": "AAPL", "quantity": 6.0}]}
    assert client.calls_for(duel_db_usd.POSITIONS_TABLE_USD, "upsert") == []
    # 원화 표·원화 RPC 는 근처에도 가지 않습니다.
    assert client.calls_for(duel_db.SETTLE_SELL_RPC) == []
    assert client.calls_for(duel_db.POSITIONS_TABLE) == []


def test_batch_usd_records_the_first_holding_date_on_the_first_fill():
    """USD 계좌의 리밸런싱 창 기준일도 첫 체결이 있는 밤에 USD 계좌 표에 기록됩니다."""
    accounts = _accounts(1)
    ledger = _seed_ledger(accounts)
    client = _client(
        accounts=accounts, ledger=ledger,
        orders=[_order("o-1", accounts[0]["id"], "AAPL", 1, "2026-08-19T18:30:00+09:00")],
    )
    summary = _run(client, close_price_of=lambda ticker: 200.0 if ticker == "AAPL" else None)

    assert summary["first_holding_dates_set"] >= 1
    call = client.only_call(duel_db_usd.ACCOUNTS_TABLE_USD, "update")
    assert call.payload == {"first_holding_date": TARGET_DATE.isoformat()}
    assert client.calls_for(duel_db.ACCOUNTS_TABLE) == []


def test_summary_lines_usd_show_sell_proceeds_in_dollars():
    """매도 요약 줄도 "원"이 아니라 "$" 여야 합니다(§5-15 와 같은 함정)."""
    lines = duel_batch_usd.format_summary_lines_usd({
        "target_date": "2026-08-19", "action": {"fill": True},
        "orders": {"orders": 1, "filled": 1, "sells": 1, "sell_filled": 1},
        "filled_amount_total": 0.0, "sold_amount_total": 800.0,
    })
    sell_line = [line for line in lines if "리밸런싱 매도" in line]
    assert len(sell_line) == 1
    # ("재원" 같은 낱말에 '원' 글자가 들어가므로, 금액 표기 자체를 대조합니다.)
    assert "$800.00" in sell_line[0]
    assert "800원" not in sell_line[0] and "800.00원" not in sell_line[0]


# =============================================================================
# 8. 🔴 2026-08-29 재감사 회귀 테스트 (USD 미러)
#    같은 결함을 두 트랙에 각각 고쳤으므로, 회귀 테스트도 양쪽에 각각 둡니다(§0-3-10 의
#    비용이 이 자리에 그대로 드러납니다 — M-1 구조 통합은 별도 백로그입니다).
# =============================================================================
def test_stale_index_source_holds_instead_of_cancelling_everyones_orders_usd():
    """H-1(USD) — 지수 원천이 낡았다고 전원 주문을 취소하지 않고 **보류**합니다."""
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    summary = _run(client, index_stale_reason="지수 원천 일부가 낡았습니다(합성).")
    assert summary["freshness"]["status"] == duel_batch_usd.CRAWL_NO_BASELINE
    assert summary["action"]["fill"] is False and summary["action"]["cancel_pending"] is False
    assert summary["pending_held"] == 1
    assert _order_updates_excluding_stale_sweep(client) == []


def test_a_held_day_writes_the_reason_onto_the_orders_usd():
    """
    🔴 M-10(USD 미러) — 보류 사실을 주문 행에도 남깁니다(상태는 pending 그대로).
    배치 로그에만 남기면 화면은 일반 대기 주문과 구분할 수단이 없습니다(§0-1).
    """
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    summary = _run(client, index_stale_reason="지수 원천 일부가 낡았습니다(합성).")
    assert summary["pending_held"] == 1
    (annotation,) = _hold_annotation_calls(client)
    assert "status" not in annotation.payload
    assert annotation.filter_map == {"status": duel_rules.ORDER_PENDING,
                                     "target_date": TARGET_DATE.isoformat()}
    assert "보류" in annotation.payload["fail_reason"]
    assert summary["freshness"]["reason"] in annotation.payload["fail_reason"]
    assert client.calls_for(duel_db.ORDERS_TABLE) == []      # 원화 표는 안 건드립니다


def test_a_dry_run_does_not_write_the_hold_reason_usd():
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    _run(client, index_stale_reason="지수 원천 일부가 낡았습니다(합성).", dry_run=True)
    assert client.calls_for(op="update") == []


def test_a_price_snapshot_from_another_trading_day_holds_instead_of_filling_usd():
    """H-2(USD) — 가격 스냅샷 거래일이 처리 거래일과 다르면 체결하지 않습니다."""
    client = _client(accounts=_accounts(1), ledger=_seed_ledger(_accounts(1)),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    summary = _run(client, session_date=YESTERDAY_TARGET.isoformat(),
                   close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert summary["freshness"]["status"] == duel_batch_usd.CRAWL_NO_BASELINE
    assert summary["pending_held"] == 1
    assert summary["snapshots_written"] == 0


def test_override_fill_is_refused_when_the_basis_is_stale_usd():
    """M-9(USD) — `--override fill` + 낡은 근거 조합은 거절합니다(쓰기 전에)."""
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    with pytest.raises(DuelBatchError) as excinfo:
        _run(client, session_date=YESTERDAY_TARGET.isoformat(),
             override=duel_batch_usd.OVERRIDE_FILL)
    assert "override fill" in str(excinfo.value)
    for op in ("insert", "upsert", "delete"):
        assert client.calls_for(op=op) == [], op


def test_a_probe_without_any_index_holds_instead_of_raising_usd():
    """H-1/M-12(USD) — 낡은 지수를 전부 뺀 점검표(지수 0개)여도 배치는 죽지 않고 보류합니다."""
    probe = _index_probe(TARGET_DATE, stock_prices=_stock_prices(bump=5.0))
    probe["index_keys"] = []
    for key in ("SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ"):
        probe["values"].pop(key, None)
    client = _client(accounts=_accounts(1),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")])
    summary = _run(client, today_probe=probe,
                   index_stale_reason="지수 원천이 전부 낡아 판정에서 뺐습니다(합성).")
    assert summary["freshness"]["status"] == duel_batch_usd.CRAWL_NO_BASELINE
    assert summary["pending_held"] == 1


def test_the_batch_repairs_the_average_cost_after_the_sell_settlement_rpc_usd():
    """H-3(USD) — 같은 밤 매도 뒤 재매수의 새 평단가가 정산 **뒤** upsert 로 살아 갑니다."""
    accounts = _accounts(1)
    accounts[0]["first_holding_date"] = "2026-07-01"
    sell = _order("o-sell", "acc-1", "AAPL", 5, "2026-08-18T18:00:00+09:00")
    sell["side"] = "sell"
    sell["rebalance_window_index"] = 0
    client = _client(
        accounts=accounts, ledger=_seed_ledger(accounts, amount=0.0),
        positions=[{"account_id": "acc-1", "ticker": "AAPL", "stock_name": "애플",
                    "quantity": 5, "avg_cost": 200.0, "status": "active",
                    "delisted_date": None}],
        orders=[sell, _order("o-buy", "acc-1", "AAPL", 2, "2026-08-18T18:30:00+09:00")],
    )
    summary = _run(client, close_price_of=lambda ticker: 10.0 if ticker == "AAPL" else None)
    assert summary["sell_positions_settled"] == 1

    rows = [row for call in client.calls_for(duel_db_usd.POSITIONS_TABLE_USD, "upsert")
            for row in call.rows if row["ticker"] == "AAPL"]
    assert rows, "평단가 보정 upsert 가 나가지 않았습니다"
    assert all(row["avg_cost"] == 10.0 and row["quantity"] == 2 for row in rows), rows

    order_of_calls = [(call.table, call.op) for call in client.calls]
    assert order_of_calls.index((duel_db_usd.SETTLE_SELL_RPC_USD, "rpc")) < \
        order_of_calls.index((duel_db_usd.POSITIONS_TABLE_USD, "upsert"))


def test_a_failing_ledger_insert_leaves_the_order_pending_for_the_next_run_usd():
    """H-4(USD) — 원장 insert 실패 시 주문은 여전히 pending(주문 상태가 마지막이므로)."""
    from utils.duel_db import DuelDbError
    accounts = _accounts(1)
    client = _client(accounts=accounts, ledger=_seed_ledger(accounts),
                     orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-18T18:00:00+09:00")],
                     deposits_already=[{"account_id": "acc-1"}])
    client.responses[(duel_db_usd.LEDGER_TABLE_USD, "insert")] = RuntimeError("network reset")
    with pytest.raises(DuelDbError):
        _run(client, close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert _order_updates_excluding_stale_sweep(client) == []
    assert client.calls_for(duel_db_usd.POSITIONS_TABLE_USD, "upsert") == []


def test_the_batch_sweeps_pending_orders_the_batch_never_got_to_process_usd():
    """H-8(USD) — 매 실행 맨 앞에서 과거 정체 주문을 정리하고 요약에 올립니다."""
    client = _client(accounts=_accounts(1),
                     stale_pending_rows=[{"id": "old-1"}, {"id": "old-2"}])
    summary = _run(client)
    assert summary["stale_pending_expired"] == 2
    (sweep,) = _stale_sweep_calls(client)
    assert "배치가 정상적으로 처리하지 못해" in sweep.payload["fail_reason"]
    assert ("lt", "target_date", TARGET_DATE.isoformat()) in sweep.filters
    text = "\n".join(duel_batch_usd.format_summary_lines_usd(summary))
    assert "과거 주문 2건 정리" in text
