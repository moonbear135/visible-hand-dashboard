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


def _load_index_closes(target_date, data_dir=None, log=print):
    """
    점검에 넣을 지수 종가를 읽습니다. **읽기 전용**입니다.

    코스피는 `market_history.csv` 의 "코스피 종가"를 그대로 씁니다
    (`report_db.load_kospi_close_history()` — 매크로 파이프라인 산출물이라 이 저장소의 다른
    코드처럼 **절대 쓰지 않습니다**). 파일에서 **가장 최근 날짜의 종가**를 쓰고, 그 날짜를
    로그에 함께 찍습니다.

    ⚠️ 왜 "target_date 의 종가"가 아니라 "가장 최근 종가"인가: 신선도 점검의 질문 자체가
       "오늘 수집이 새 값을 만들어 냈는가"입니다. 수집이 실패하면 파일에 오늘 행이 아예
       없는데, 그때 예외를 내고 배치를 멈추면 **그날 귀속 주문을 취소하는 단계까지 못 갑니다**
       (2-4-5 가 요구하는 처리를 못 하게 됩니다).

    🔴 2026-08-29 재감사 H-1 — 다만 "최신 값을 그대로 넣는다"만으로는 부족합니다. 이 지수는
       결투가 아니라 **매크로 파이프라인 산출물**이라, 그 파이프라인만 따로 실패해 지수가
       하루 낡는 일이 정상적으로 일어납니다. 그때 종목 종가는 멀쩡한데도 "지수 무변동"으로
       `failed` 판정이 나 그날 전체 주문이 **거짓 사유로 취소**됐습니다. 그래서 이제
       `latest_day != target_date` 면 **그 사실을 문장으로 만들어 함께 돌려줍니다** — 배치는
       그 문장을 받아 취소가 아니라 **보류**로 처리합니다(§0-1: 실패하지 않은 것을 실패했다고
       사용자 주문 행에 적지 않기).

    ⚠️ `data_dir` (2026-08-29 재감사 L-1): 예전에는 `--data-dir` 를 통째로 무시하고 항상
       저장소 루트의 `market_history.csv` 만 봤습니다(USD 쪽은 넘기고 있어 비대칭이었고,
       테스트가 임시 디렉터리로 지수를 갈아끼울 수 없었습니다). 이제 넘어온 디렉터리 안에
       그 파일이 **실제로 있으면** 그것을 쓰고, 없으면 예전과 같이 저장소 루트를 봅니다 —
       어느 쪽을 썼는지는 로그에 남깁니다(조용히 다른 파일을 읽지 않기).

    반환: ({"KOSPI": 종가}, 그 종가의 날짜 문자열, 낡음 사유 문자열 또는 None)
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

    csv_path = None
    if data_dir:
        candidate = os.path.join(data_dir, report_db.MARKET_HISTORY_FILENAME)
        if os.path.exists(candidate):
            csv_path = candidate
            log(f"  · 코스피 지수 종가 원천으로 --data-dir 안의 파일을 씁니다: {candidate}")

    closes = report_db.load_kospi_close_history(csv_path)
    if not closes:
        raise DuelBatchError(
            "코스피 지수 종가 이력(market_history.csv)을 읽지 못해 신선도 점검을 할 수 없습니다"
            " — 지수 없이 '점검했다'고 하지 않습니다(§0-1)."
        )
    latest_day = max(closes)

    index_stale_reason = None
    if latest_day != target_date:
        index_stale_reason = (
            f"코스피 지수 종가 원천(market_history.csv)이 {latest_day} 기준으로 처리 거래일"
            f"({target_date})보다 낡았습니다 — 이 지수는 결투와 다른 파이프라인 산출물이라"
            " 그 파이프라인만 따로 실패했을 수 있습니다."
        )
        log(f"  ⚠️ {index_stale_reason}")
    return {"KOSPI": closes[latest_day]}, latest_day, index_stale_reason


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
    #  🔴 2026-08-29 재감사 M-12 — 이 단계의 실패를 **예외로 배치를 죽이지 않습니다.**
    #     `_load_index_closes()` 는 "예외를 내고 배치를 멈추면 그날 귀속 주문을 처리하는
    #     단계까지 못 갑니다"라는 명시적 근거로 폴백을 택했는데, 바로 다음 두 단계
    #     (`select_probe_stocks()` 안의 스냅샷·상위 50종목 검사, `load_probe_state()` 의
    #     기준값 파일 검사)는 그 배려 없이 그냥 예외를 던졌습니다 — 한 파일 안에서 같은
    #     질문에 답이 두 가지였고, 그 결과 그날 주문은 **체결도 취소도 보류 기록도 없이**
    #     남았습니다(H-8 로 합류).
    #     이제 그 실패들을 "우리 쪽 사정"으로 묶어 배치에 넘깁니다: 신선도는
    #     `no_baseline` 으로 강등돼 **보류**(체결·취소 둘 다 안 함)가 되고, 배치는 계속
    #     진행해 정기입금·정체 주문 정리처럼 신선도와 무관한 일은 정상적으로 합니다.
    #     ⚠️ 순수 함수들(`select_probe_stocks()` · `load_probe_state()`)의 예외는 그대로
    #        둡니다 — 그 함수들의 계약("모르는 형식을 추측해 읽지 않는다")은 여전히 맞고,
    #        "그래서 배치가 무엇을 할 것인가"는 이 실행 스크립트가 정할 일입니다.
    today_probe = None
    previous_probe = None
    universe_index = {}
    probe_error_reasons = []
    index_stale_reason = None
    try:
        index_closes, index_source_date, index_stale_reason = _load_index_closes(
            target_date, data_dir=data_dir, log=log)
        print(f"  · 코스피 지수 종가 {index_closes['KOSPI']}"
              f" (market_history.csv 기준 {index_source_date})")

        universe_index, _universe_meta = scorecard_db.load_universe_index(MARKET_KR,
                                                                         data_dir=data_dir)
        today_probe = duel_batch.build_freshness_probe(target_date, index_closes,
                                                       universe_index)
        print(f"  · 신선도 점검표 {len(today_probe['values'])}개 구성"
              f" (지수 {len(today_probe['index_keys'])} + 상위 종목"
              f" {len(today_probe['values']) - len(today_probe['index_keys'])})")
    except DuelBatchError as exc:
        today_probe = None
        probe_error_reasons.append(f"오늘 신선도 점검표를 만들지 못했습니다: {exc}")
        print(f"  ⚠️ {probe_error_reasons[-1]}")

    try:
        previous_probe = duel_batch.load_probe_state(state_path)
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
    #  🔴 2026-08-29 재감사 M-13 — 예전에는 `report_db.build_price_lookup()`(넓은 폴백:
    #     kr_all_market_prices.json 등)을 썼습니다. 그런데 신선도 점검(`build_freshness_probe()`)
    #     은 **상위 유니버스 파일만** 보므로, 유니버스 밖으로 밀려난 종목은 "아무도 신선도를
    #     확인하지 않은 파일"의 값으로 체결됐습니다. 화면 주문 폼은 이미 같은 이유로 폴백을
    #     일부러 쓰지 않습니다(`web/pages/duel_page.py::_load_kospi_universe()`) — 배치만 그
    #     규율 밖에 있었습니다. 위에서 점검표용으로 이미 읽어 둔 `universe_index` 를 그대로
    #     재사용하므로 추가 I/O 가 없습니다.
    price_lookup = scorecard_db.make_price_lookup({MARKET_KR: universe_index})

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
        # 🔴 2026-08-29 재감사 H-1/H-2/M-9 — "우리 쪽 자료가 낡았다"는 사실을 판정에
        #    실제로 넣습니다. 예전에는 둘 다 print 만 하고 배치에 전달조차 하지 않았습니다.
        index_stale_reason=index_stale_reason,
        session_date=kr_session_date,
        override=args.override,
        dry_run=args.dry_run,
        log=log,
    )

    # ── ⑤ 내일의 기준값 남기기 (워크플로우가 이 파일을 커밋합니다) ──────────────
    if args.dry_run:
        print("  · (dry-run) 기준값 파일을 갱신하지 않았습니다.")
    elif today_probe is None:
        # M-12 — 점검표를 못 만든 날은 남길 기준값도 없습니다. 예전 파일을 그대로 두는 것이
        # 맞습니다(빈 파일로 덮어쓰면 다음 실행까지 판정을 못 하게 됩니다).
        print("  ⚠️ 오늘 점검표를 만들지 못해 기준값 파일을 갱신하지 않았습니다"
              " (예전 기준값을 그대로 둡니다).")
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
