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
from utils import duel_batch, duel_batch_usd, duel_db_usd, duel_rules  # noqa: E402
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
           deposits_already=None):
    accounts = accounts if accounts is not None else _accounts()
    ledger = ledger if ledger is not None else []

    def ledger_select(query):
        if query.filter_map.get("event_type") == "monthly_deposit":
            return list(deposits_already or [])
        return list(ledger)

    return FakeClient(responses={
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): list(accounts),
        (duel_db_usd.LEDGER_TABLE_USD, "select"): ledger_select,
        (duel_db_usd.ORDERS_TABLE_USD, "select"): list(orders or []),
        (duel_db_usd.POSITIONS_TABLE_USD, "select"): list(positions or []),
        (duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select"): list(snapshots or []),
    })


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
    assert client.only_call(duel_db_usd.ACCOUNTS_TABLE_USD, "select").filter_map == \
        {"status": "active"}


# =============================================================================
# 3. 🔴 날짜 분리 — target_date(확정 거래일) vs today_kst(배치 실행일, 입금 전용)
# =============================================================================
def test_deposit_uses_today_kst_not_target_date():
    """
    정기입금 판정·event_date 는 `today_kst`(배치 실행일)를 씁니다. `target_date`가 10일이어도
    `today_kst`가 10일이 아니면 입금하지 않고, 그 반대(오늘이 10일, target_date는 아님)면
    입금해야 합니다 — 원화 배치라면 있을 수 없는 분기라 이 테스트로만 지킵니다.
    """
    accounts = _accounts(2)

    # target_date 가 10일이지만 today_kst 는 10일이 아님 → 입금하지 않습니다.
    client_a = _client(accounts=accounts)
    summary_a = _run(client_a, target_date=date(2026, 9, 10), today_kst=TODAY_KST)
    assert summary_a["deposit_attempted"] is False
    assert client_a.calls_for(duel_db_usd.LEDGER_TABLE_USD, "insert") == []

    # target_date 는 10일이 아니지만 today_kst 가 10일 → 입금합니다.
    client_b = _client(accounts=accounts)
    summary_b = _run(client_b, target_date=TARGET_DATE, today_kst=DEPOSIT_TODAY_KST)
    assert summary_b["deposit_attempted"] is True
    assert summary_b["deposit_applied"] == 2
    deposit_rows = client_b.only_call(duel_db_usd.LEDGER_TABLE_USD, "insert").rows
    # event_date 는 today_kst(입금 판정일) 이지 target_date(거래일) 가 아닙니다.
    assert all(row["event_date"] == DEPOSIT_TODAY_KST.isoformat() for row in deposit_rows)
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
    call = client.only_call(duel_db_usd.ORDERS_TABLE_USD, "update")
    assert "미국 정규장" in call.payload["fail_reason"]


def test_batch_usd_holds_orders_without_a_baseline():
    today_probe = _index_probe(TARGET_DATE)
    client = _client(accounts=_accounts(1),
                    orders=[_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T18:00:00+09:00")])
    summary = _run(client, today_probe=today_probe, previous_probe=None)
    assert summary["freshness"]["status"] == duel_batch_usd.CRAWL_NO_BASELINE
    assert summary["pending_held"] == 1
    assert client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "update") == []


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
    client = _client(accounts=accounts)
    summary = _run(client)

    assert summary["snapshots_written"] == account_count
    selects = client.calls_for(op="select")
    assert len(selects) == 5, [(call.table, call.filters) for call in selects]
    for table in (duel_db_usd.ACCOUNTS_TABLE_USD, duel_db_usd.LEDGER_TABLE_USD,
                 duel_db_usd.ORDERS_TABLE_USD, duel_db_usd.POSITIONS_TABLE_USD,
                 duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD):
        assert len(client.calls_for(table, "select")) == 1, table

    expected_chunks = -(-account_count // duel_db_usd.CHUNK_SIZE)
    assert len(client.calls_for(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "upsert")) == expected_chunks
    assert len(client.calls) == 5 + expected_chunks


def test_fill_updates_scale_with_orders_not_with_accounts_usd():
    accounts = _accounts(20)
    orders = [_order("o-1", "acc-1", "AAPL", 1, "2026-08-19T19:00:00+09:00"),
              _order("o-2", "acc-2", "AAPL", 1, "2026-08-19T19:30:00+09:00")]
    client = _client(accounts=accounts, orders=orders, ledger=_seed_ledger(accounts))
    _run(client, close_price_of=lambda ticker: 150.0 if ticker == "AAPL" else None)
    assert len(client.calls_for(duel_db_usd.ORDERS_TABLE_USD, "update")) == len(orders)
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
