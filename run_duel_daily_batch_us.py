#!/usr/bin/env python3
# run_duel_daily_batch_us.py
"""
⚔️ "결투다!" USD 트랙 — 야간 배치 **실행 스크립트**
   (`.github/workflows/duel_daily_us.yml` 이 부르는 것 — `run_duel_daily_batch.py`(원화)의 미러)

하는 일(전부 **I/O**, 판단은 `utils/duel_batch_usd.py`가 합니다 — 원화 스크립트와 같은 분업):
  · 환경변수를 읽고 배치 전용 Supabase 클라이언트를 만듭니다(`duel_db_usd.create_service_client()`
    — 원화와 **같은** service_role 키·같은 프로젝트를 씁니다, 두 번째 키를 만들지 않습니다).
  · 미국 지수·상위 550 종목 가격 파일을 **이미 있는 로더로** 읽습니다
    (`report_db.load_us_index_closes()` · `scorecard_db.load_universe_index(MARKET_US)` ·
     `report_db.build_price_lookup()` — §0-3-10, 파싱을 새로 짜지 않습니다).
  · USD 전용 신선도 기준값 파일(`data/duel_freshness_probe_previous_usd.json`)을 읽고 덮어씁니다.
  · 요약을 사람이 읽을 수 있게 출력합니다.

-------------------------------------------------------------------------------
🔴 `--target-date` 를 생략하면 기본값이 **"어제"**입니다 (원화 스크립트는 "오늘"입니다)
-------------------------------------------------------------------------------
`utils/duel_batch_usd.py` 머리말에 근거를 자세히 적어 두었습니다 — 요약하면: 미국 정규장은
한국 시각으로 다음 날 새벽에 마감하고, 확정 종가 수집은(`.github/workflows/scrape_us.yml`,
2026-08-20 device_bash 로 직접 확인) 늦어도 한국 시각 08:05 에 끝납니다. 그래서 "미국 거래일
X"의 확정 종가는 **한국 날짜 X+1일 아침**에야 저장소에 들어오고, 이 배치가 한국 날짜 Y에 돌면
처리할 수 있는 것은 언제나 **Y의 하루 전(X = Y-1)** 거래일입니다.

반대로 **정기 입금(매월 10일)은 배치가 실제로 도는 한국 날짜**(`--today-date`, 생략하면
`datetime.now(KST).date()`) 기준입니다 — 시장 이벤트가 아니라 현금 이벤트라서(2-2-4)입니다.

-------------------------------------------------------------------------------
🔴 이 스크립트는 `SUPABASE_SERVICE_ROLE_KEY` 를 씁니다 — 원화 스크립트와 같은 격리 규율(§0-3-8)
-------------------------------------------------------------------------------
키는 GitHub Actions Secrets 에만 있어야 하고, 이 파일은 키를 출력하지 않습니다.

-------------------------------------------------------------------------------
사용법
-------------------------------------------------------------------------------
    python run_duel_daily_batch_us.py                     # 평소(어제 = 확정하려는 미국 거래일)
    python run_duel_daily_batch_us.py --dry-run
    python run_duel_daily_batch_us.py --target-date 2026-08-19
    python run_duel_daily_batch_us.py --target-date 2026-08-19 --override fill
    python run_duel_daily_batch_us.py --target-date 2026-08-19 --override cancel
    python run_duel_daily_batch_us.py --today-date 2026-09-10   # 정기입금 판정일을 직접 지정
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import duel_batch_usd, duel_db_usd, duel_rules, report_db, scorecard_db  # noqa: E402
from utils.duel_batch_usd import DuelBatchError                                 # noqa: E402
from utils.duel_db import DuelDbError                                           # noqa: E402
from utils.duel_rules import KST, DuelRuleError                                 # noqa: E402
from utils.scorecard_db import MARKET_US, ScorecardError                        # noqa: E402


def duel_rules_stock_count():
    """점검에 넣는 종목 수(단일 출처는 `duel_rules.CRAWL_STOCK_COUNT` — 원화와 공유)."""
    return duel_rules.CRAWL_STOCK_COUNT


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="결투다! USD 트랙 야간 배치 (체결 · 정기입금 · 일별 스냅샷)")
    parser.add_argument("--target-date", default=None,
                        help="확정하려는 미국 거래일(YYYY-MM-DD). 생략하면 어제(한국 날짜).")
    parser.add_argument("--today-date", default=None,
                        help="정기입금 판정에 쓸 한국 날짜(YYYY-MM-DD). 생략하면 오늘.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Supabase 에 쓰지 않고 읽기·계산만 합니다(기준값 파일도 안 씁니다).")
    parser.add_argument("--override", choices=[duel_batch_usd.OVERRIDE_FILL,
                                               duel_batch_usd.OVERRIDE_CANCEL],
                        default=None,
                        help="관리자 확인 후 신선도 판정을 덮어씁니다(needs_review 해소용).")
    parser.add_argument("--data-dir", default=None,
                        help="가격 스냅샷 디렉터리(기본: <저장소>/data).")
    parser.add_argument("--state-path", default=None,
                        help="신선도 기준값 파일 경로"
                             f"(기본: data/{duel_batch_usd.PROBE_STATE_FILENAME_USD}).")
    return parser.parse_args(argv)


def _load_index_closes_usd(data_dir, log=print):
    """
    ⚠️ 2026-08-29 재감사 L-2 — `log` 인자는 예전에 **한 번도 쓰이지 않았습니다**(원화판은
       씁니다 — 미러 divergence 의 흔적). 인자를 없애는 대신 원화판과 같은 자리에서 실제로
       로그를 찍게 했습니다: 어느 지수를 어느 날짜로 읽었는지가 매 실행 로그에 남습니다.

    점검에 넣을 미국 지수(추종 ETF) 종가 2개를 읽습니다. **읽기 전용**입니다.

    `data/us_index_history.json`(`report_db.load_us_index_closes()`)에서 두 벤치마크
    (`report_db.US_BENCHMARK_KEYS` = S&P500·나스닥 추종 ETF) 각각의 **가장 최근 종가**를
    씁니다. 원화 스크립트의 `_load_index_closes()`와 같은 이유로 "target_date 의 종가"가
    아니라 "가장 최근 종가"를 씁니다 — 수집이 실패해도 예외로 배치를 멈추지 않고, 최신값이
    기준값과 같아져 `failed_or_holiday` 로 정확히 판정되게 하기 위해서입니다.

    반환: ({"SP500_PROXY_SPY": 종가, "NASDAQ_PROXY_ONEQ": 종가}, {키: 그 종가의 날짜 문자열})
    """
    indices = report_db.load_us_index_closes(data_dir)
    closes = {}
    source_dates = {}
    missing = []
    for key in duel_batch_usd.PROBE_INDEX_KEYS_SPEC_USD:
        entry = indices.get(key) or {}
        series = entry.get("closes") or {}
        if not series:
            missing.append(key)
            continue
        latest_day = max(series)
        closes[key] = series[latest_day]
        source_dates[key] = latest_day
        log(f"  · {key} 종가 원천 기준일 {latest_day} (us_index_history.json)")
    if missing:
        raise DuelBatchError(
            f"미국 벤치마크 종가를 확보하지 못했습니다: {missing}"
            " — 지수 없이 '점검했다'고 하지 않습니다(§0-1). data/us_index_history.json"
            " 을 만드는 collector_us_indices.py 가 아직 한 번도 돌지 않았을 수 있습니다."
        )
    return closes, source_dates


def main(argv=None):
    args = _parse_args(argv)
    log = print

    print("=" * 70)
    print("⚔️ [결투 USD 야간 배치] 시작")

    now_kst_date = datetime.now(KST).date()
    # 🔴 기본값이 "어제"입니다(원화는 "오늘") — 미국 정규장 확정 종가는 한국 날짜로 다음 날
    #    아침에야 들어오기 때문입니다. 근거는 이 파일·utils/duel_batch_usd.py 머리말 참고.
    target_date = args.target_date or (now_kst_date - timedelta(days=1)).isoformat()
    today_date = args.today_date or now_kst_date.isoformat()
    print(f"  · 확정하려는 미국 거래일(target-date): {target_date}"
          + ("" if args.target_date else "  (기본값 = 어제, 한국 날짜)"))
    print(f"  · 정기입금 판정 기준일(today-date, 한국 날짜): {today_date}")
    if args.dry_run:
        print("  · dry-run — Supabase 에 아무것도 쓰지 않고, 기준값 파일도 갱신하지 않습니다.")

    data_dir = args.data_dir or scorecard_db.default_data_dir()
    state_path = args.state_path or duel_batch_usd.default_state_path_usd()

    # ── ① 미국 가격 스냅샷이 어느 거래일 것인지 (원화 스크립트의 ①과 같은 사전 점검) ──────
    session_dates, price_stamps, notes = report_db.resolve_session_info(data_dir=data_dir)
    for note in notes:
        print(f"  · {note}")
    us_session_date = session_dates.get(MARKET_US)
    if us_session_date and us_session_date != target_date:
        print(f"  ⚠️ 미국주식 가격 스냅샷의 거래일({us_session_date})이 처리 거래일"
              f"({target_date})과 다릅니다 — 아직 그 거래일 수집이 안 됐거나 실패했을 수"
              " 있습니다. 아래 신선도 판정이 이 상황을 그대로 잡아냅니다(값을 보정하지"
              " 않습니다).")

    # ── ② 오늘 점검표(지수 2개 + 상위 50종목) 만들기 ───────────────────────────
    #  🔴 2026-08-29 재감사 M-12(원화 스크립트의 같은 자리와 같은 이유) — 이 단계의 실패로
    #     배치를 죽이지 않습니다. 실패 사유를 "우리 쪽 사정"으로 묶어 배치에 넘기면
    #     신선도가 `no_baseline` 으로 강등돼 **보류**(체결·취소 둘 다 안 함)가 되고,
    #     정기입금·정체 주문 정리처럼 신선도와 무관한 일은 정상적으로 돕니다.
    today_probe = None
    previous_probe = None
    universe_index = {}
    probe_error_reasons = []
    index_stale_reason = None
    try:
        index_closes, index_source_dates = _load_index_closes_usd(data_dir, log=log)
        for key, close in index_closes.items():
            print(f"  · {key} 종가 {close}"
                  f" (us_index_history.json 기준 {index_source_dates[key]})")

        # 🔴 2026-08-29 재감사 H-1(USD 판) — 지수 원천이 처리 거래일보다 낡았는지 검사합니다.
        #    원화와 달리 이 트랙은 지수가 2개라 **부분 낡음**이 가능합니다: 하나만 낡았으면 그
        #    지수만 판정에서 빼고 나머지로 판정하고, 전부 낡았으면 판정 근거가 하나도 없다는
        #    사실을 문장으로 만들어 배치에 넘깁니다(취소가 아니라 보류로 처리됩니다).
        stale_keys = [k for k, d in index_source_dates.items() if d != target_date]
        if stale_keys:
            fresh_keys = [k for k in index_closes if k not in stale_keys]
            detail = ", ".join(f"{k}({index_source_dates[k]})" for k in stale_keys)
            if fresh_keys:
                index_stale_reason = (
                    f"지수 원천 일부가 처리 거래일({target_date})보다 낡았습니다 — {detail}."
                    f" 나머지 지수({', '.join(fresh_keys)})만으로 판정합니다."
                )
                index_closes = {k: v for k, v in index_closes.items() if k not in stale_keys}
            else:
                index_stale_reason = (
                    f"지수 원천이 전부 처리 거래일({target_date})보다 낡았습니다 — {detail}."
                    " 이 지수들은 결투와 다른 파이프라인 산출물이라 그 파이프라인만"
                    " 실패했을 수 있습니다."
                )
                index_closes = {}
            print(f"  ⚠️ {index_stale_reason}")

        universe_index, _universe_meta = scorecard_db.load_universe_index(MARKET_US,
                                                                          data_dir=data_dir)
        today_probe = duel_batch_usd.build_freshness_probe(
            target_date, index_closes, universe_index,
            # 위에서 낡은 지수를 **의도적으로** 뺐을 수 있습니다(H-1). 그 사실은
            # `index_stale_reason` 으로 배치까지 그대로 전달됩니다.
            allow_empty_index=bool(index_stale_reason))
        print(f"  · 신선도 점검표 {len(today_probe['values'])}개 구성"
              f" (지수 {len(today_probe['index_keys'])} + 상위 종목"
              f" {len(today_probe['values']) - len(today_probe['index_keys'])})")
    except DuelBatchError as exc:
        today_probe = None
        probe_error_reasons.append(f"오늘 신선도 점검표를 만들지 못했습니다: {exc}")
        print(f"  ⚠️ {probe_error_reasons[-1]}")

    try:
        previous_probe = duel_batch_usd.load_probe_state(state_path)
    except DuelBatchError as exc:
        previous_probe = None
        probe_error_reasons.append(f"전일 기준값 파일을 읽지 못했습니다: {exc}")
        print(f"  ⚠️ {probe_error_reasons[-1]}")
    if previous_probe is None and not probe_error_reasons:
        print(f"  ⚠️ 전일 기준값 파일이 없습니다({state_path}) — 오늘은 판정 근거가 없어"
              " 체결하지 않고, 오늘 값을 기준값으로 남깁니다(다음 실행부터 정상 판정).")
    elif previous_probe is not None:
        print(f"  · 전일 기준값 {previous_probe.get('target_date')} 기준"
              f" {len(previous_probe.get('values') or {})}개")

    if probe_error_reasons:
        index_stale_reason = " ".join(
            ([index_stale_reason] if index_stale_reason else []) + probe_error_reasons)

    # ── ③ 종가 조회 함수 — **화면 주문 폼과 같은 좁은 조회**를 씁니다(§0-3-10) ──
    #  🔴 2026-08-29 재감사 M-13(원화 스크립트의 같은 자리와 같은 이유) — 넓은 폴백
    #     (`us_all_market_prices.json` · `us_all_etf_prices.json`)은 신선도 점검이 보지 않는
    #     파일이라, 그 값으로 체결하면 "아무도 확인하지 않은 가격"으로 체결하게 됩니다.
    #     점검표용으로 이미 읽어 둔 `universe_index` 를 그대로 재사용합니다(추가 I/O 없음).
    price_lookup = scorecard_db.make_price_lookup({MARKET_US: universe_index})

    def close_price_of(ticker):
        return price_lookup(MARKET_US, ticker)

    # ── ④ 배치 본체 ────────────────────────────────────────────────────────────
    service_client = duel_db_usd.create_service_client()
    summary = duel_batch_usd.run_nightly_batch_usd(
        service_client, target_date,
        today_probe=today_probe,
        previous_probe=previous_probe,
        close_price_of=close_price_of,
        today_kst=today_date,
        price_as_of_kst=price_stamps.get(MARKET_US),
        # 🔴 2026-08-29 재감사 H-1/H-2/M-9 — "우리 쪽 자료가 낡았다"는 사실을 판정에
        #    실제로 넣습니다(원화 스크립트와 같은 자리·같은 이유).
        index_stale_reason=index_stale_reason,
        session_date=us_session_date,
        override=args.override,
        dry_run=args.dry_run,
        log=log,
    )

    # ── ⑤ 내일의 기준값 남기기 (워크플로우가 이 파일을 커밋합니다) ──────────────
    if args.dry_run:
        print("  · (dry-run) 기준값 파일을 갱신하지 않았습니다.")
    elif today_probe is None:
        # M-12 — 점검표를 못 만든 날은 남길 기준값도 없습니다(예전 파일을 그대로 둡니다).
        print("  ⚠️ 오늘 점검표를 만들지 못해 기준값 파일을 갱신하지 않았습니다"
              " (예전 기준값을 그대로 둡니다).")
    else:
        duel_batch_usd.save_probe_state(state_path, today_probe)
        print(f"  ✅ 다음 비교용 기준값을 남겼습니다: {state_path}")

    for line in duel_batch_usd.format_summary_lines_usd(summary):
        print(line)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DuelBatchError, DuelDbError, DuelRuleError, ScorecardError) as exc:
        # 배치는 조용히 성공한 척하면 안 됩니다 — 비정상 종료로 알립니다
        # (`run_duel_daily_batch.py::main()` 과 같은 규약).
        print(f"❌ 결투 USD 야간 배치 실패: {exc}")
        sys.exit(1)
