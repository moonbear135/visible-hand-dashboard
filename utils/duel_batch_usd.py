# utils/duel_batch_usd.py
"""
⚔️ "결투다!" USD 트랙 — **야간 배치 오케스트레이션 계층** (2026-08-20, USD 트랙 4차 코딩)

`utils/duel_batch.py`(원화)의 통화 미러입니다. `utils/duel_db_usd.py` 머리말이 세운 원칙을
그대로 옮깁니다: **표 이름(=`duel_db_usd` 호출)이 본문에 박혀 있는 함수만 새로 정의**하고,
계좌·데이터가 어느 표에서 왔는지 몰라도 되는 순수 판정·계산 로직은 **그대로 재사용**합니다.

-------------------------------------------------------------------------------
🔁 재사용 vs 신규 정의 — 이 파일이 실제로 새로 쓴 것
-------------------------------------------------------------------------------
`utils.duel_batch`에서 **그대로 import 해서 씁니다**(재구현하지 않습니다):
  · 순수 도우미 — `_to_date` · `_positive_price` · `_round6` · `is_monthly_deposit_date`
    (매월 10일 판정은 통화와 무관한 달력 규칙입니다).
  · 신선도 점검표 만들기·읽기·쓰기 — `select_probe_stocks()` · `build_freshness_probe()` ·
    `load_probe_state()` · `save_probe_state()`. 이들은 지수·종목 종가를 **인자로만** 받고
    "KOSPI"라는 문자열을 코드에 박아두지 않습니다 — `select_probe_stocks()`는 `universe_index`
    dict 에서 `rank`/`price` 필드만 보는데, 미국 스냅샷(`data/us_stocks_latest.json`)도
    `utils/stock_history.py::US_HISTORY_FIELDS`가 이미 **같은 필드 이름**("rank" = 시가총액
    순위)으로 정의해 뒀으므로 함수를 두 벌 만들 이유가 없습니다.
  · 판정 로직 — `judge_crawl_freshness()` · `resolve_action()` · `_freshness_reason()`
    (내부에서 import 됨). 문구도 "코스피"를 언급하지 않는 일반 문장이라 그대로 맞습니다.
  · 체결 계획 — `plan_order_fills()`(2026-08-21 부터 **리밸런싱 매도 → 매수** 순서 포함) ·
    `resolve_first_holding_updates()`(오늘 처음 보유가 생긴 계좌 판정 — 계좌·포지션
    딕셔너리만 보는 순수 계산이라 통화와 무관합니다).
    FIFO 예수금 배정·평단가 갱신은 계좌·종목 딕셔너리만
    다루는 순수 함수입니다(내부에서 `duel_db.group_rows_by_account()`를 쓰는데, 이 함수도
    표 이름을 몰라도 되는 순수 집계라 원화 모듈에서 가져다 써도 무방합니다 — 이미
    `duel_db_usd.py`도 같은 함수를 재사용합니다).
  · 스냅샷·TWR — `last_snapshot_dates()` · `collect_external_cash_flows()` ·
    `build_snapshot_rows()` · `compute_twr_by_account()`. 계산은 `duel_rules.compute_twr()`
    (공유)가 하고, 이 함수들은 그 결과를 표에 넣을 모양으로 다듬을 뿐입니다.
  · 상수 — `PROBE_STATE_VERSION` · `MIN_PROBE_STOCK_OVERLAP` · `CRAWL_NO_BASELINE` ·
    `OVERRIDE_FILL` · `OVERRIDE_CANCEL` · `EXTERNAL_CASH_FLOW_TYPES` · `CASH_FLOW_KIND_MIXED` ·
    `TWR_ERROR` · `default_state_dir()`.

**새로 정의합니다**:
  · `PROBE_STATE_FILENAME_USD` — USD 전용 신선도 기준값 파일 이름 + `default_state_path_usd()`.
    원화와 **절대 같은 파일을 공유하면 안 됩니다** — 비교 대상 자체가 다른 시장(코스피 지수·
    상위 200 vs 미국 지수·상위 550)이라, 같은 파일을 쓰면 어제 값이 다른 시장 값이 되어
    판정 자체가 무의미해집니다.
  · `PROBE_INDEX_KEYS_SPEC_USD` — 이 트랙이 점검에 넣는 지수 키. **원화와 달리 둘 다 이미
    수집되고 있어** "목표 대비 실제로 못 하는 지수"라는 격차가 없습니다(아래 §0 참고).
  · `run_nightly_batch_usd()` — 유일하게 실질적으로 새로 쓴 함수입니다. `duel_db.*` 대신
    `duel_db_usd.*`를 부르는 것 외에, **아래 "날짜가 하나에서 둘로 갈라진 이유"**가 원화
    파일과 다른 진짜 이유입니다.
  · `format_summary_lines_usd()` — `utils.duel_batch.format_summary_lines()`를 그대로 쓰지
    **않는** 유일한 예외입니다. 그 함수의 로그 한 줄("체결에 쓴 현금 합계: …원")에 원화
    단위 "원"이 리터럴로 박혀 있어(코드를 직접 확인 — docstring 이 아니라 실행되는 f-string
    입니다), 그대로 재사용하면 달러 금액에 "원"이 찍히는 사고가 납니다. 그래서 이 한 줄만
    다시 쓴 새 함수를 만들었습니다(`_translate_order_guard_error_usd()`와 같은 이유의
    예외 — 로직은 같지만 사람이 읽는 문구에 통화 표기가 박혀 있는 경우).

-------------------------------------------------------------------------------
🔴 "처리 거래일"과 "배치가 실제로 도는 한국 날짜"가 원화에서는 같았는데, USD에서는 다릅니다
-------------------------------------------------------------------------------
원화 배치는 `target_date`(체결 대상 거래일)와 "오늘"이 **항상 같은 날**이었습니다 — 코스피는
한국 시간 15:30에 장을 마감하고, 그날 16:05~16:40 KST 사이에 확정 종가 수집이 끝나서, 그날
저녁(17:10 KST) 배치가 "오늘 거래일"을 그대로 처리할 수 있었습니다.

미국은 그렇지 않습니다. **미국 정규장은 한국 시각으로 다음 날 새벽에 마감합니다**(4:00pm
ET = 서머타임 05:00 KST/표준시 06:00 KST, 전부 "다음 날"). 그리고 실제 수집
(`.github/workflows/scrape_us.yml`, device_bash 로 직접 확인한 원문 — 2026-08-20)은 장마감
30분 뒤부터 시작해 **실측 55.5분, 최악의 경우(타임아웃) 90분**까지 걸립니다. 두 cron
(서머타임 20:35 UTC / 표준시 21:35 UTC) 중 실제로 도는 쪽을 기준으로 계산하면:

  · 서머타임(EDT) — 마감 20:00 UTC, 수집 완료 21:30~22:05 UTC = **06:30~07:05 KST(다음 날)**.
  · 표준시(EST)   — 마감 21:00 UTC, 수집 완료 22:30~23:05 UTC = **07:30~08:05 KST(다음 날)**.

즉 "미국 거래일 X"의 확정 종가는 **한국 날짜로 X+1일 이른 아침(늦어도 08:05 KST)**에야
저장소에 들어옵니다. 그리고 주문 접수 시간대(16:00:01~21:00:00 KST)는 — 서머타임·표준시
어느 쪽으로 계산해도 — **같은 한국 날짜의 미국 동부시각 이른 아침(03:00~08:00 ET 안팎, 개장
9:30am ET 전)**과 겹칩니다.

그래서 한국 날짜 X일 저녁에 접수된 주문의 체결 거래일(`duel_rules.resolve_fill_trading_day_usd()`
의 결과)은 — 그 시각이 아직 **그날 미국장이 열리기도 전**이므로 — **X일 자신**입니다(X가 확정
거래일 목록에 있는 한. X가 미국 휴장일이면 그 이후 첫 확정 거래일). 접수 직후 열리는 바로 그
장의 마감가로 체결되는 것이고, 주문 시점에 그 마감가는 아직 존재하지 않으니 선행매매는 구조적
으로 불가능합니다. ⚠️ 원화용 `resolve_fill_trading_day()`(그날 자신을 무조건 제외)를 여기에
쓰면 체결이 근거 없이 하루 늦어집니다 — 실제로 그렇게 짜여 있던 것을 2026-08-21 오너가 발견해
바로잡았습니다(work order §5-16).

그리고 그 X일 마감가는 위에서 본 대로 **한국 날짜 X+1일 이른 아침**에야 저장소에 들어옵니다 —
그래서 **배치는 항상 "실행되는 한국 날짜의 하루 전"에 해당하는 거래일을 처리해야** 합니다
(`run_duel_daily_batch_us.py`가 `--target-date`를 생략하면 "어제"를 기본값으로 쓰는 이유입니다).
즉 한국 날짜 X일 저녁에 접수된 주문은 **다음 날(X+1일) 낮에 도는 배치**가 X일자 마감가로
체결합니다. §5-16 의 수정은 이 스케줄 구조 자체를 바꾸지 않습니다 — 배치가 어느 날짜를
처리하느냐(= 실행일 하루 전)는 그대로이고, 주문이 붙는 `target_date` 의 절대값만 하루 앞당겨
정확해진 것입니다.

반면 **매월 10일 정기입금은 시장 이벤트가 아니라 현금 이벤트**입니다(work order 2-2-4, 원화와
같은 원칙). 배치가 실제로 실행되는 그 한국 날짜가 10일이면, 그날 입금이 나가야 정직합니다 —
"처리 중인 거래일이 10일인가"로 판정하면 하루가 밀려 입금일 자체가 어긋납니다. 그래서 이
함수는 원화와 달리 **날짜 인자를 둘로 받습니다**:
  · `target_date` — 체결·스냅샷·신선도 비교에 쓰는 "확정하려는 미국 거래일"(= X, 항상
    배치 실행일보다 하루 이상 이전).
  · `today_kst`   — 정기입금 판정에만 쓰는 "배치가 실제로 도는 한국 날짜"(생략하면
    `datetime.now(KST).date()`). 입금 원장의 `event_date`도 이 값을 씁니다.

⚠️ 이 구분은 오너가 명시적으로 확정한 것이 아니라, 위에 적은 **실제 수집 스케줄과 주문 접수
   시간대(16:00:01~21:00:00 KST, §5-13 오너 확정)로부터 이번 라운드에 도출한 설계**입니다.
   장이 열리기 전에 그날 종가로 주문을 받을 수는 없으므로 뒤집힐 여지는 적지만, 저장소를
   다시 열면 이 문단을 오너 확인 항목으로 다시 짚어 주세요.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from utils import duel_batch, duel_db_usd, duel_rules
from utils.duel_batch import (
    DuelBatchError,
    PROBE_STATE_VERSION,
    MIN_PROBE_STOCK_OVERLAP,
    CRAWL_NO_BASELINE,
    OVERRIDE_FILL,
    OVERRIDE_CANCEL,
    EXTERNAL_CASH_FLOW_TYPES,
    CASH_FLOW_KIND_MIXED,
    TWR_ERROR,
    _to_date,
    _positive_price,
    _round6,
    is_monthly_deposit_date,
    select_probe_stocks,
    build_freshness_probe,
    load_probe_state,
    save_probe_state,
    judge_crawl_freshness,
    resolve_action,
    plan_order_fills,
    resolve_first_holding_updates,
    last_snapshot_dates,
    collect_external_cash_flows,
    build_snapshot_rows,
    compute_twr_by_account,
    default_state_dir,
)
from utils.duel_rules import KST

__all__ = [
    "DuelBatchError",
    "PROBE_STATE_FILENAME_USD",
    "PROBE_INDEX_KEYS_SPEC_USD",
    "default_state_path_usd",
    "run_nightly_batch_usd",
    "format_summary_lines_usd",
]


# =============================================================================
# 0. 이 파일만의 상수 — USD 전용 신선도 기준값 파일 + 점검 대상 지수
# =============================================================================
#: 원화(`duel_freshness_probe_previous.json`)와 **절대 같은 파일을 쓰지 않습니다** — 비교
#: 대상 시장 자체가 다르므로, 같은 파일을 공유하면 "어제 값"이 다른 시장의 값이 되어 신선도
#: 판정이 통째로 무의미해집니다.
PROBE_STATE_FILENAME_USD = "duel_freshness_probe_previous_usd.json"

#: 이 트랙이 점검에 넣는 지수 키(2-9 의 USD 미러). **원화의 `PROBE_INDEX_KEYS_SPEC`과 달리
#: 목표·실제 격차가 없습니다** — `data/us_index_history.json`(`collector_us_indices.py`
#: 산출물)에 두 벤치마크가 이미 다 있습니다(`utils/report_db.py::US_BENCHMARK_KEYS`가 단일
#: 출처 — 값이 어긋나면 `tests/test_duel_batch_usd.py`가 잡습니다. 이 파일은 그 모듈을 직접
#: import 하지 않습니다 — 배치 판단 계층에 파일 I/O 계층 상수를 끌어오지 않기 위해서이고,
#: 대신 리터럴 값을 그대로 옮기고 테스트로 일치를 고정합니다).
PROBE_INDEX_KEYS_SPEC_USD = ("SP500_PROXY_SPY", "NASDAQ_PROXY_ONEQ")


def default_state_path_usd():
    """USD 신선도 기준값 파일의 기본 경로. 테스트는 임시 경로를 직접 넘깁니다."""
    return os.path.join(default_state_dir(), PROBE_STATE_FILENAME_USD)


# =============================================================================
# 1. 하루치 배치 본체 (USD) — work order 2-5 의 USD 미러
# =============================================================================
def run_nightly_batch_usd(service_client, target_date, *,
                          today_probe,
                          previous_probe,
                          close_price_of,
                          today_kst=None,
                          unchanged_tolerance=duel_rules.CRAWL_UNCHANGED_TOLERANCE,
                          min_stock_overlap=MIN_PROBE_STOCK_OVERLAP,
                          price_as_of_kst=None,
                          override=None,
                          dry_run=False,
                          log=print):
    """
    USD 트랙의 하루치 배치를 한 번 돌립니다. `utils.duel_batch.run_nightly_batch()`의 미러 —
    순서(① 신선도 판정 → ② 정기입금 → ③ 체결/취소/보류 → ④ 스냅샷)와 §0-3-2(집합 연산) 준수는
    완전히 같습니다. **파일도 네트워크도 열지 않습니다** — Supabase는 인자로 받은 클라이언트로,
    가격은 인자로 받은 조회 함수로만 만집니다.

    인자
        service_client  : `duel_db_usd.create_service_client()`(= `duel_db.create_service_client()`,
                          같은 프로젝트를 공유합니다) 결과.
        target_date     : **확정하려는 미국 거래일**(= X). 그날 pending 주문의 target_date,
                          그날 스냅샷의 snapshot_date 로 씁니다. 항상 배치 실행일(한국 날짜)
                          보다 하루 이상 이전입니다 — 위 모듈 머리말의 날짜 오프셋 설명 참고.
        today_probe     : `build_freshness_probe(target_date, ...)` 결과(= X일 점검표).
        previous_probe  : `load_probe_state()` 결과(첫 실행이면 None).
        close_price_of  : `(ticker) -> 미국 정규장 마감가 또는 None`.
        today_kst       : **정기입금 판정에만 쓰는, 배치가 실제로 도는 한국 날짜.** 생략하면
                          `datetime.now(KST).date()`. `target_date`(=X)와 **일부러 다른 값**을
                          받습니다 — 위 모듈 머리말 "날짜가 하나에서 둘로 갈라진 이유" 참고.
                          입금 원장의 `event_date`도 이 값을 씁니다(X 가 아닙니다).
        override        : 관리자 덮어쓰기(`OVERRIDE_FILL`/`OVERRIDE_CANCEL`) — CLI 전용.
        dry_run         : True 면 **쓰기만** 건너뜁니다(읽기·계산은 그대로).

    반환: 요약 dict(`format_summary_lines()`에 그대로 넘길 수 있습니다 — 원화와 같은 모양).
    """
    day = _to_date(target_date, "확정하려는 미국 거래일")
    today = _to_date(today_kst, "배치 실행일(KST)") if today_kst is not None \
        else datetime.now(KST).date()

    summary = {
        "target_date": day.isoformat(),
        "today_kst": today.isoformat(),
        "dry_run": bool(dry_run),
        "freshness": None,
        "action": None,
        "deposit_applied": 0,
        "deposit_attempted": False,
        "orders": {"filled": 0, "partially_filled": 0, "expired": 0, "cancelled": 0,
                   "sells": 0, "sell_filled": 0, "orders": 0, "accounts": 0},
        "filled_amount_total": 0.0,
        "sold_amount_total": 0.0,
        "ledger_rows_written": 0,
        "positions_written": 0,
        "sell_positions_settled": 0,
        "first_holding_dates_set": 0,
        "pending_cancelled": 0,
        "pending_held": 0,
        "snapshots_written": 0,
        "account_count": 0,
        "twr": {},
        "warnings": [],
    }

    # ── ① 신선도 판정 (2-5-1 / 2-9, USD 미러) ─────────────────────────────────
    freshness = judge_crawl_freshness(
        today_probe, previous_probe,
        unchanged_tolerance=unchanged_tolerance,
        min_stock_overlap=min_stock_overlap,
    )
    action = resolve_action(freshness, override)
    summary["freshness"] = freshness
    summary["action"] = action

    log(f"  · [USD] 수집 신선도 판정: {freshness['status']} — {freshness['reason']}")
    if override is not None:
        log(f"  ⚠️ 관리자 덮어쓰기 '{override}' 로 판정을 대체합니다"
            f" (실제 판정은 {freshness['status']} 였습니다).")

    accounts = duel_db_usd.fetch_all_active_accounts_usd(service_client)
    summary["account_count"] = len(accounts)
    account_ids = [row["id"] for row in accounts if row.get("id")]
    log(f"  · [USD] 활성 계좌 {len(accounts)}개")

    # ── ② 정기 입금 (2-2) — 신선도·target_date 와 무관하게, **오늘 한국 날짜** 기준 ──────
    #    🔴 여기서 `today`(배치 실행일)를 쓰고 `day`(target_date=X)를 쓰지 않는 것이 이
    #    파일의 핵심 차이입니다 — 모듈 머리말 참고.
    if is_monthly_deposit_date(today):
        summary["deposit_attempted"] = True
        if dry_run:
            log("  · (dry-run) 정기 입금은 실행하지 않습니다.")
        else:
            summary["deposit_applied"] = duel_db_usd.apply_monthly_deposits_usd(
                service_client, today)
            log(f"  ✅ [USD] 정기 입금 {summary['deposit_applied']}건"
                f" (이미 들어간 계좌는 건너뜁니다 — 멱등)")

    # 입금 이후에 원장을 읽습니다(2-2-3 과 같은 순서 — 그날 입금을 그날 체결에 쓸 수 있게).
    # 잔고는 **target_date(=X) 기준**으로 읽습니다 — X일 주문을 X일 시점의 예수금으로
    # 체결해야 하므로, 혹시 X 와 today 사이에 시차가 있어도(있을 수 없지만) 안전합니다.
    ledger_rows = duel_db_usd.fetch_cash_ledger_for_accounts_usd(
        service_client, account_ids, as_of_date=day)
    cash_balances = duel_db_usd.cash_balances_by_account(ledger_rows)

    positions_by_account = {}

    if action["fill"]:
        # ── ③ 체결 (2-4-6, USD 미러) ──────────────────────────────────────────
        pending = duel_db_usd.fetch_pending_orders_for_fill_usd(service_client, day)
        position_rows = duel_db_usd.fetch_positions_for_accounts_usd(service_client, account_ids)
        positions_by_account = duel_db_usd.group_rows_by_account(position_rows)
        # 체결 **전** 보유 상태(= "오늘 처음 주식이 생긴 계좌" 판정의 유일한 근거).
        positions_before_fill = positions_by_account

        active_ids = set(account_ids)
        orphaned = [row for row in pending if row.get("account_id") not in active_ids]
        if orphaned:
            pending = [row for row in pending if row.get("account_id") in active_ids]
            summary["warnings"].append(
                f"활성 USD 계좌 목록에 없는 계좌의 pending 주문 {len(orphaned)}건은 손대지"
                " 않고 그대로 두었습니다(예수금을 확인할 수 없어 체결·만료 판정을 하지"
                " 않습니다)."
            )

        needed = {str(row.get("ticker") or "").strip() for row in pending}
        close_prices = {}
        for ticker in sorted(needed):
            if not ticker:
                continue
            price = _positive_price(close_price_of(ticker))
            if price is not None:
                close_prices[ticker] = price

        fill_plan = plan_order_fills(pending, cash_balances, close_prices,
                                     positions_by_account, day)
        summary["orders"] = fill_plan["counts"]
        summary["filled_amount_total"] = fill_plan["filled_amount_total"]
        summary["sold_amount_total"] = fill_plan["sold_amount_total"]
        positions_by_account = fill_plan["positions_by_account"]
        cash_balances = fill_plan["cash_after"]

        # 오늘 처음 보유가 생긴 계좌(= 리밸런싱 창의 기준일이 오늘로 정해지는 계좌).
        first_holding = resolve_first_holding_updates(
            accounts, positions_before_fill, positions_by_account)
        if first_holding["missing"]:
            summary["warnings"].append(
                f"보유 종목이 있는데 `first_holding_date` 가 비어 있는 USD 계좌가"
                f" {len(first_holding['missing'])}개 있습니다"
                f" (예: {first_holding['missing'][:3]})."
                " 오늘 처음 생긴 보유가 아니라 오늘 날짜로 채우지 않았습니다 — 채우면 사실과"
                " 다른 리밸런싱 창이 만들어집니다(§0-1). 과거 체결 기록을 보고 오너가 직접"
                " 채워 주세요."
            )

        if dry_run:
            log(f"  · (dry-run) 체결 결과 {len(fill_plan['fill_results'])}건을 기록하지 않습니다.")
        else:
            written = duel_db_usd.record_order_fills_usd(service_client, fill_plan["fill_results"])
            summary["ledger_rows_written"] = duel_db_usd.record_buy_ledger_entries_usd(
                service_client, fill_plan["ledger_entries"])
            # 🔴 매도 정산이 먼저 — 수량이 줄어드는 행은 전용 RPC 로만 통과합니다
            #    (원화 `run_nightly_batch()` 의 같은 자리와 완전히 같은 이유).
            summary["sell_positions_settled"] = duel_db_usd.settle_sell_positions_usd(
                service_client, fill_plan["sell_position_rows"])
            saved = duel_db_usd.upsert_positions_usd(service_client, fill_plan["position_rows"])
            summary["positions_written"] = len(saved)
            if first_holding["new_ids"]:
                summary["first_holding_dates_set"] = duel_db_usd.set_first_holding_dates_usd(
                    service_client, first_holding["new_ids"], day)
            log(f"  ✅ [USD] 체결 결과 {written}건 기록 ·"
                f" 체결 원장 {summary['ledger_rows_written']}행 · 포지션 {len(saved)}건 갱신"
                + (f" · 매도 정산 {summary['sell_positions_settled']}건"
                   if summary["sell_positions_settled"] else "")
                + (f" · 최초 보유일 {summary['first_holding_dates_set']}계좌 기록"
                   if summary["first_holding_dates_set"] else ""))

    elif action["cancel_pending"]:
        # ── ③' 실패일 처리 (2-4-5, USD 미러) ─────────────────────────────────
        reason = (f"{day.isoformat()} 미국 정규장 확정 마감가를 신뢰할 수 없어 이 주문은"
                  f" 체결되지 않고 취소되었습니다. {freshness['reason']}"
                  " 다음 거래일로 이월하지 않습니다(작업지시서 2-4-5).")
        if dry_run:
            log("  · (dry-run) 미체결 주문 일괄 취소를 실행하지 않습니다.")
        else:
            summary["pending_cancelled"] = duel_db_usd.expire_or_cancel_all_pending_for_date_usd(
                service_client, day, reason)
            log(f"  ⚠️ [USD] 체결하지 않고 그날 귀속 주문 {summary['pending_cancelled']}건을"
                " 취소했습니다(사유를 행에 남겼습니다).")

    else:
        # ── ③'' 보류 (needs_review / no_baseline, USD 미러) ───────────────────
        held = duel_db_usd.fetch_pending_orders_for_fill_usd(service_client, day)
        summary["pending_held"] = len(held)
        summary["warnings"].append(
            f"[{freshness['status']}] {day.isoformat()} 귀속 USD pending 주문 {len(held)}건을"
            " 체결도 취소도 하지 않고 그대로 두었습니다 — 관리자가 값을 확인한 뒤"
            " `--override fill` 또는 `--override cancel` 로 이 날짜를 다시 돌려 결론을 내세요."
        )
        wait_for = ("관리자 확인 대기" if freshness["status"] == duel_rules.CRAWL_NEEDS_REVIEW
                    else "판정 기준값 없음")
        log(f"  ⚠️ [USD] {wait_for} — pending 주문 {len(held)}건을 그대로 보류했습니다"
            " (자동으로 체결하지도, 취소하지도 않습니다).")

    # ── ④ 일별 스냅샷 (2-5-4, USD 미러) ───────────────────────────────────────
    if action["write_snapshots"]:
        history = duel_db_usd.fetch_daily_snapshots_for_accounts_usd(service_client, account_ids)
        previous_dates = last_snapshot_dates(
            [row for row in history if _to_date(row.get("snapshot_date")) < day])
        flows = collect_external_cash_flows(ledger_rows, previous_dates, day)

        snapshot_prices = {}
        for rows in positions_by_account.values():
            for position in rows:
                ticker = str((position or {}).get("ticker") or "").strip()
                if ticker and ticker not in snapshot_prices:
                    price = _positive_price(close_price_of(ticker))
                    if price is not None:
                        snapshot_prices[ticker] = price

        rows = build_snapshot_rows(accounts, positions_by_account, cash_balances,
                                   snapshot_prices, flows, day,
                                   price_as_of_kst=price_as_of_kst)
        summary["twr"] = compute_twr_by_account(
            [row for row in history if _to_date(row.get("snapshot_date")) < day], rows)
        for account_id, twr in summary["twr"].items():
            if twr.get("status") == TWR_ERROR:
                summary["warnings"].append(
                    f"USD 계좌 {account_id} 의 누적 TWR 을 계산하지 못했습니다: {twr.get('error')}"
                    " (스냅샷 적재 자체에는 영향이 없습니다.)"
                )

        if dry_run:
            log(f"  · (dry-run) 스냅샷 {len(rows)}행을 저장하지 않습니다.")
        else:
            duel_db_usd.write_daily_snapshots_usd(service_client, day, rows)
            summary["snapshots_written"] = len(rows)
            log(f"  ✅ [USD] 일별 스냅샷 {len(rows)}행 적재(계좌 × 거래일 = 1행)")
    else:
        summary["warnings"].append(
            f"{day.isoformat()} 은(는) 그날 미국 정규장 종가를 신뢰할 수 없어 스냅샷을 쓰지"
            " 않았습니다 — 그 사이의 시드·정기입금은 다음 스냅샷의 cash_flow_amount 로"
            " 이월됩니다."
        )
        log("  · [USD] 스냅샷은 쓰지 않았습니다(믿을 수 있는 그날 종가가 없어 평가액을 만들 수"
            " 없습니다).")

    return summary


# =============================================================================
# 2. 사람이 읽는 요약 — 원화 `format_summary_lines()`의 유일한 예외
# =============================================================================
def format_summary_lines_usd(summary):
    """
    USD 배치 결과를 오너가 로그에서 바로 읽을 수 있는 한국어 여러 줄로 만듭니다.
    `utils.duel_batch.format_summary_lines()`와 **글자 하나까지 같되**, "체결에 쓴 현금
    합계" 줄의 통화 표기만 "원" 대신 "$"(달러 기호, `utils/duel_rules.py`의 체급 문구가
    이미 쓰는 표기 — "$750 이상"과 같은 관례)로 바꿉니다. 모듈 머리말의 "재사용 vs 신규
    정의" 절 참고.
    """
    freshness = summary.get("freshness") or {}
    action = summary.get("action") or {}
    orders = summary.get("orders") or {}
    lines = [
        "─" * 70,
        f"⚔️ 결투 USD 야간 배치 요약 — {summary.get('target_date')}"
        + (f" (배치 실행일 KST {summary['today_kst']})" if summary.get("today_kst") else "")
        + ("  (dry-run: 아무것도 저장하지 않았습니다)" if summary.get("dry_run") else ""),
        f"  · 수집 신선도: {freshness.get('status')}"
        f" (기준일 {freshness.get('baseline_date') or '없음'},"
        f" 비교 종목 {freshness.get('compared_stocks', 0)}개)",
    ]
    if action.get("override"):
        lines.append(f"  ⚠️ 관리자 덮어쓰기: {action['override']}"
                     f" → 실제 적용 판정 {action.get('effective_status')}")
    lines.append(f"  · 활성 USD 계좌: {summary.get('account_count', 0)}개")

    if summary.get("deposit_attempted"):
        lines.append(f"  · 정기 입금(매월 10일): {summary.get('deposit_applied', 0)}건 신규 입금")
    else:
        lines.append("  · 정기 입금: 오늘은 입금일(매월 10일)이 아닙니다")

    if action.get("fill"):
        lines.append(
            f"  · 주문 {orders.get('orders', 0)}건 처리 —"
            f" 전량체결 {orders.get('filled', 0)} ·"
            f" 부분체결 {orders.get('partially_filled', 0)} ·"
            f" 예수금부족 만료 {orders.get('expired', 0)} ·"
            f" 종가없음 취소 {orders.get('cancelled', 0)}"
        )
        # 🔴 여기만 원화와 다릅니다 — "원" 대신 "$"(달러 기호를 금액 앞에).
        lines.append(f"  · 체결에 쓴 현금 합계: ${summary.get('filled_amount_total', 0):,.2f}")
        if orders.get("sells"):
            lines.append(
                f"  · 리밸런싱 매도 {orders.get('sells', 0)}건 중"
                f" {orders.get('sell_filled', 0)}건 체결 —"
                f" 매도 대금 ${summary.get('sold_amount_total', 0):,.2f}"
                " (그날 매수 재원으로 즉시 반영됨)"
            )
    elif action.get("cancel_pending"):
        lines.append(f"  ⚠️ 체결 없음 — 그날 귀속 주문 {summary.get('pending_cancelled', 0)}건 취소")
    else:
        lines.append(f"  ⚠️ 체결 없음 — 판정 보류로 pending 주문 {summary.get('pending_held', 0)}건을"
                     " 그대로 두었습니다(취소하지 않았습니다)")

    lines.append(f"  · 일별 스냅샷: {summary.get('snapshots_written', 0)}행 적재")

    twr = summary.get("twr") or {}
    computed = [value for value in twr.values() if value.get("twr_pct") is not None]
    failed = [value for value in twr.values() if value.get("status") == TWR_ERROR]
    if computed:
        best = max(computed, key=lambda item: item["twr_pct"])
        worst = min(computed, key=lambda item: item["twr_pct"])
        lines.append(f"  · 누적 TWR 산출 계좌 {len(computed)}개 —"
                     f" 최고 {best['twr_pct']:.2f}% / 최저 {worst['twr_pct']:.2f}%")
    elif twr and not failed:
        lines.append(f"  · 누적 TWR: 아직 계산할 구간이 없습니다(계좌 {len(twr)}개 전부 개설 직후)")
    if failed:
        lines.append(f"  ⚠️ 누적 TWR 계산 불가 계좌 {len(failed)}개 — 아래 경고 참고")

    for warning in summary.get("warnings") or []:
        lines.append(f"  ⚠️ {warning}")
    lines.append("─" * 70)
    return lines
