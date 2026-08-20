#!/usr/bin/env python3
# run_duel_daily_batch.py
"""
⚔️ "결투다!" — 야간 배치 **실행 스크립트** (`.github/workflows/duel_daily.yml` 이 부르는 것)

DUEL_MODULE_WORK_ORDER.md 2-5 의 야간 배치를 하루 한 번 돌립니다. 저장소 루트에 두는 이유는
`collector_us_indices.py` · `collector_kospi200.py` 와 같습니다 — GitHub Actions 가
`python run_duel_daily_batch.py` 한 줄로 부를 수 있어야 하니까요.

-------------------------------------------------------------------------------
🧱 이 파일이 하는 일 / 하지 않는 일
-------------------------------------------------------------------------------
하는 일(전부 **I/O**):
  · 환경변수를 읽고 배치 전용 Supabase 클라이언트를 만듭니다(`duel_db.create_service_client()`).
  · 그날 가격 파일을 **이미 있는 로더로** 읽습니다
    (`scorecard_db.load_universe_index()` · `report_db.build_price_lookup()` ·
     `report_db.load_kospi_close_history()` — §0-3-10, 파싱을 새로 짜지 않습니다).
  · 신선도 기준값 파일(`data/duel_freshness_probe_previous.json`)을 읽고, 끝에 덮어씁니다.
  · 요약을 사람이 읽을 수 있게 출력합니다.

하지 않는 일: **판단.** 순서·판정·행 만들기는 전부 `utils/duel_batch.py` 에 있고,
계산은 `utils/duel_rules.py`, Supabase 접근은 `utils/duel_db.py` 입니다. 그래야
`tests/test_duel_batch.py` 가 네트워크·파일 없이 그 판단들을 통째로 검증할 수 있습니다.

-------------------------------------------------------------------------------
🔴 이 스크립트는 `SUPABASE_SERVICE_ROLE_KEY` 를 씁니다
-------------------------------------------------------------------------------
키는 **GitHub Actions Secrets 에만** 있어야 합니다. 사용자가 접속하는 앱 서버(Render)의
환경변수에 넣지 마세요 — 넣는 순간 결투 모듈의 RLS 가 통째로 무력화됩니다(§0-3-8,
`utils/report_db.py` 이후의 격리 규율과 같습니다). 이 파일은 키를 출력하지 않습니다.

-------------------------------------------------------------------------------
사용법
-------------------------------------------------------------------------------
    python run_duel_daily_batch.py                      # 평소(오늘 KST 기준)
    python run_duel_daily_batch.py --dry-run            # 저장하지 않고 계산만
    python run_duel_daily_batch.py --target-date 2026-08-20
    python run_duel_daily_batch.py --target-date 2026-08-20 --override fill
    python run_duel_daily_batch.py --target-date 2026-08-20 --override cancel

`--override` 는 신선도 판정이 `needs_review`(무변동 종목이 허용치를 넘음, 2-9-4)로 나와
배치가 주문을 보류했을 때, **관리자가 값을 직접 확인한 뒤** 결론을 내리는 용도입니다.
자동 경로에서는 절대 쓰이지 않습니다(워크플로우에도 없습니다).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import duel_batch, duel_db, duel_rules, report_db, scorecard_db   # noqa: E402
from utils.duel_batch import DuelBatchError                              # noqa: E402
from utils.duel_db import DuelDbError                                    # noqa: E402
from utils.duel_rules import KST, DuelRuleError                          # noqa: E402
from utils.scorecard_db import MARKET_KR, ScorecardError                 # noqa: E402

#: 실제로 점검에 넣는 지수. 작업지시서 2-9 는 **코스피 + 코스닥 = 지수 2개**(총 52개 점검)를
#: 요구하지만, 이 저장소에는 **코스닥 지수 종가 원천이 없습니다** —
#: `market_history.csv` 에는 "코스피 종가" 컬럼만 있고, PROJECT_STATUS.md §10-3 이
#: "코스닥 지수는 이 파일에 없어 v1 은 코스피만(후속 과제)"이라고 이미 적어 두었습니다.
#: 그래서 지금 실제로 돌아가는 점검은 **51개(코스피 지수 + 상위 50종목)** 입니다.
#: ⚠️ 이 차이를 조용히 두지 않습니다 — 아래 `_load_index_closes()` 가 **매 실행 로그에**
#:    경고 한 줄을 찍습니다(§0-1: 못 한 것을 한 척하지 않기). 코스닥 지수 수집이 생기면
#:    이 튜플에 "KOSDAQ" 을 추가하고 `_load_index_closes()` 에 원천 한 줄만 붙이면 됩니다.
ACTIVE_PROBE_INDEX_KEYS = ("KOSPI",)


def duel_rules_stock_count():
    """점검에 넣는 종목 수(단일 출처는 `duel_rules.CRAWL_STOCK_COUNT` — 여기 숫자를 안 적습니다)."""
    return duel_rules.CRAWL_STOCK_COUNT


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="결투다! 야간 배치 (체결 · 정기입금 · 일별 스냅샷)")
    parser.add_argument("--target-date", default=None,
                        help="처리할 거래일(YYYY-MM-DD, KST). 생략하면 오늘.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Supabase 에 쓰지 않고 읽기·계산만 합니다(기준값 파일도 안 씁니다).")
    parser.add_argument("--override", choices=[duel_batch.OVERRIDE_FILL,
                                               duel_batch.OVERRIDE_CANCEL],
                        default=None,
                        help="관리자 확인 후 신선도 판정을 덮어씁니다(needs_review 해소용).")
    parser.add_argument("--data-dir", default=None,
                        help="가격 스냅샷 디렉터리(기본: <저장소>/data).")
    parser.add_argument("--state-path", default=None,
                        help=f"신선도 기준값 파일 경로(기본: data/{duel_batch.PROBE_STATE_FILENAME}).")
    return parser.parse_args(argv)


def _load_index_closes(log=print):
    """
    점검에 넣을 지수 종가를 읽습니다. **읽기 전용**입니다.

    코스피는 `market_history.csv` 의 "코스피 종가"를 그대로 씁니다
    (`report_db.load_kospi_close_history()` — 매크로 파이프라인 산출물이라 이 저장소의 다른
    코드처럼 **절대 쓰지 않습니다**). 파일에서 **가장 최근 날짜의 종가**를 쓰고, 그 날짜를
    로그에 함께 찍습니다.

    ⚠️ 왜 "target_date 의 종가"가 아니라 "가장 최근 종가"인가: 신선도 점검의 질문 자체가
       "오늘 수집이 새 값을 만들어 냈는가"입니다. 수집이 실패하면 파일에 오늘 행이 아예
       없는데, 그때 예외를 내고 배치를 멈추면 **그날 귀속 주문을 취소하는 단계까지 못 갑니다**
       (2-4-5 가 요구하는 처리를 못 하게 됩니다). 최신 값을 그대로 넣으면 전일 기준값과
       같아져 `failed_or_holiday` 로 정확히 판정되고, 후속 처리가 정상적으로 돕니다.
       기준 날짜를 로그에 찍으므로 "며칠 낡았는지"는 사람이 항상 볼 수 있습니다.

    반환: ({"KOSPI": 종가}, 그 종가의 날짜 문자열)
    """
    # 작업지시서가 요구한 지수 중 **실제로 수집하고 있지 않은 것**을 매 실행 로그에 올립니다.
    # 상수 두 개를 비교하는 것뿐이지만, 이렇게 해 두면 나중에 코스닥 수집이 생겨
    # ACTIVE_PROBE_INDEX_KEYS 에 추가하는 순간 이 경고가 저절로 사라집니다(§0-3-10).
    unavailable = [key for key in duel_batch.PROBE_INDEX_KEYS_SPEC
                   if key not in ACTIVE_PROBE_INDEX_KEYS]
    if unavailable:
        expected = len(duel_batch.PROBE_INDEX_KEYS_SPEC) + duel_rules_stock_count()
        actual = len(ACTIVE_PROBE_INDEX_KEYS) + duel_rules_stock_count()
        log(f"  ⚠️ 지수 {unavailable} 의 종가 원천이 이 저장소에 없어(코스피만 수집 중),"
            f" 작업지시서 2-9 의 {expected}개 점검 대신 **{actual}개"
            f"(지수 {len(ACTIVE_PROBE_INDEX_KEYS)}개 + 상위 {duel_rules_stock_count()}종목)** 로"
            " 점검합니다. 수집이 생기면 ACTIVE_PROBE_INDEX_KEYS 에 추가하세요.")

    closes = report_db.load_kospi_close_history()
    if not closes:
        raise DuelBatchError(
            "코스피 지수 종가 이력(market_history.csv)을 읽지 못해 신선도 점검을 할 수 없습니다"
            " — 지수 없이 '점검했다'고 하지 않습니다(§0-1)."
        )
    latest_day = max(closes)
    return {"KOSPI": closes[latest_day]}, latest_day


def main(argv=None):
    args = _parse_args(argv)
    log = print

    print("=" * 70)
    print("⚔️ [결투 야간 배치] 시작")

    target_date = args.target_date or datetime.now(KST).date().isoformat()
    print(f"  · 처리 거래일(KST): {target_date}")
    if args.dry_run:
        print("  · dry-run — Supabase 에 아무것도 쓰지 않고, 기준값 파일도 갱신하지 않습니다.")

    data_dir = args.data_dir or scorecard_db.default_data_dir()
    state_path = args.state_path or duel_batch.default_state_path()

    # ── ① 그날 가격 파일이 어느 거래일 것인지 (2-5 의 "수집 완료 사전 점검"과 같은 자리) ──
    session_dates, price_stamps, notes = report_db.resolve_session_info(data_dir=data_dir)
    for note in notes:
        print(f"  · {note}")
    kr_session_date = session_dates.get(MARKET_KR)
    if kr_session_date and kr_session_date != target_date:
        print(f"  ⚠️ 코스피 가격 스냅샷의 거래일({kr_session_date})이 처리 거래일({target_date})과"
              " 다릅니다 — 오늘 수집이 아직 끝나지 않았거나 실패한 상태일 수 있습니다."
              " 아래 신선도 판정이 이 상황을 그대로 잡아냅니다(값을 보정하지 않습니다).")

    # ── ② 오늘 점검표(51개) 만들기 ─────────────────────────────────────────────
    index_closes, index_source_date = _load_index_closes(log=log)
    print(f"  · 코스피 지수 종가 {index_closes['KOSPI']} (market_history.csv 기준 {index_source_date})")

    universe_index, _universe_meta = scorecard_db.load_universe_index(MARKET_KR,
                                                                     data_dir=data_dir)
    today_probe = duel_batch.build_freshness_probe(target_date, index_closes, universe_index)
    print(f"  · 신선도 점검표 {len(today_probe['values'])}개 구성"
          f" (지수 {len(today_probe['index_keys'])} + 상위 종목"
          f" {len(today_probe['values']) - len(today_probe['index_keys'])})")

    previous_probe = duel_batch.load_probe_state(state_path)
    if previous_probe is None:
        print(f"  ⚠️ 전일 기준값 파일이 없습니다({state_path}) — 오늘은 판정 근거가 없어"
              " 체결하지 않고, 오늘 값을 기준값으로 남깁니다(다음 실행부터 정상 판정).")
    else:
        print(f"  · 전일 기준값 {previous_probe.get('target_date')} 기준"
              f" {len(previous_probe.get('values') or {})}개")

    # ── ③ 종가 조회 함수 — "내 성적표"·"리포트"와 **같은** 가격을 씁니다(§0-3-10) ──
    price_lookup = report_db.build_price_lookup(data_dir=data_dir)

    def close_price_of(ticker):
        return price_lookup(MARKET_KR, ticker)

    # ── ④ 배치 본체 ────────────────────────────────────────────────────────────
    service_client = duel_db.create_service_client()
    summary = duel_batch.run_nightly_batch(
        service_client, target_date,
        today_probe=today_probe,
        previous_probe=previous_probe,
        close_price_of=close_price_of,
        price_as_of_kst=price_stamps.get(MARKET_KR),
        override=args.override,
        dry_run=args.dry_run,
        log=log,
    )

    # ── ⑤ 내일의 기준값 남기기 (워크플로우가 이 파일을 커밋합니다) ──────────────
    if args.dry_run:
        print("  · (dry-run) 기준값 파일을 갱신하지 않았습니다.")
    else:
        duel_batch.save_probe_state(state_path, today_probe)
        print(f"  ✅ 내일 비교용 기준값을 남겼습니다: {state_path}")

    for line in duel_batch.format_summary_lines(summary):
        print(line)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DuelBatchError, DuelDbError, DuelRuleError, ScorecardError) as exc:
        # 배치는 조용히 성공한 척하면 안 됩니다 — 비정상 종료로 알립니다
        # (`utils/report_db.py::main()` 과 같은 규약).
        print(f"❌ 결투 야간 배치 실패: {exc}")
        sys.exit(1)
