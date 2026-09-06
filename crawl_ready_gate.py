#!/usr/bin/env python3
# crawl_ready_gate.py
"""
🚦 "크롤링이 **진짜** 끝났는가" 게이트 — 크롤링 결과를 소비하는 배치 워크플로우 공용
   (2026-09-07 신설, TASK_HISTORY #204)

-------------------------------------------------------------------------------
왜 생겼는가 — 오너 방향 지시(#204)
-------------------------------------------------------------------------------
  "어느쪽이든 전부다 크롤링 끝나고 연결해서 작업이 발생하게 해줘. … 크롤링의 안전빵을
   고려하는 것뿐이지 시간을 뒤로 영원히 미뤄도 OK라는건 절대로 아닌거야. … 크롤링 후
   현재가가 적용이 최대한 빨리 되는 방향으로."

  즉 소비 배치(결투 체결·성적표 발행·리포트 스냅샷)는 **고정 시각(cron)에 "이쯤이면 끝났겠지"
  하고 기다리지 않고**, 크롤링 워크플로우가 실제로 끝나는 이벤트(`workflow_run`)로 곧바로
  깨어나야 합니다. cron 은 "그 이벤트가 안 왔을 때"만을 위한 **안전망**입니다.

  그런데 `workflow_run` 은 "앞 워크플로우가 **끝났다**"만 알려 주지 "**오늘 데이터가 실제로
  들어왔다**"는 뜻이 아닙니다. 실측(#204, 공개 Actions API 로 2026-09-01~06 실행 이력 조회):
    · `scrape.yml` 은 Cloudflare Worker 가 16:10 KST 에 `workflow_dispatch` 로 깨우고(진짜 수집,
      68~109분), GitHub 자체 cron 은 4~5시간 늦게(21:03~21:05) 한 번 더 돌아 수집기 사전 점검
      (`--skip-if-not-ready`)이 1분 만에 건너뜁니다 — 둘 다 conclusion=success 로 끝납니다.
    · `scrape_us.yml` 은 서머타임 대비로 cron 이 두 줄이라 매일 두 번 완료되고, 한 번은 건너뛰기.
    · 과거 날짜 백필(`scrape.yml` `target_date` 입력)도 success 로 끝나지만 오늘 값이 아닙니다.
    · 장 시작 전 새벽 수동 실행(#195 사고, 09-04 06:01)도 success 로 끝나지만 어제 값입니다.
  이벤트만 믿고 배치를 돌리면 위 경우마다 **어제 값으로 오늘을 처리**하거나 같은 날을 두 번
  처리합니다. 결투는 같은 날 두 번 돌면 두 번째 실행이 첫 실행의 기준값과 비교해 "전부
  무변동" → `failed_or_holiday` → **첫 실행이 보류해 둔 주문을 취소**할 수 있습니다(§0-1 —
  `utils/duel_batch.resolve_action()`). 그래서 이벤트로 깨어난 뒤 **데이터 스스로**가 "오늘 자
  수집이 끝났고, 아직 처리하지 않았다"고 말할 때만 배치를 돌립니다. 이 파일이 그 판정입니다.

-------------------------------------------------------------------------------
무엇을 보는가 — 판정은 전부 **수집기·배치가 이미 쓰는 함수**로 합니다(§0-3-10)
-------------------------------------------------------------------------------
  · 코스피 수집 완료  : `collector_kospi200.evaluate_kospi200_collection_readiness()` 가
                        "오늘(KST) 자 SUCCESS 스냅샷이 장마감(15:30) 이후에 저장됨"(#189/#195)이라
                        **수집을 건너뛰겠다**고 답하면, 그것이 곧 "오늘 수집이 끝났다"입니다.
  · 미국 수집 완료    : `report_db.resolve_session_info()` 가 읽는 미국 스냅샷의 거래일이 처리
                        거래일(어제, 한국 날짜 — `run_duel_daily_batch_us.py` 와 같은 정의)과 같고
                        `metadata.status == SUCCESS`.
  · 미국 벤치마크     : `report_db.load_us_index_closes()` 의 두 벤치마크(`US_BENCHMARK_KEYS`)에
                        처리 거래일 종가가 있음. 결투 USD 는 지수가 낡으면 체결하지 않고 **보류**
                        하므로(`run_duel_daily_batch_us.py` H-1), 지수 없이 돌리면 안 됩니다.
  · 이미 처리했는가   : 결투 기준값 파일(`duel_batch.load_probe_state()`)의 `target_date` 가 처리
                        거래일과 같으면 그날 배치가 이미 돌아 커밋한 것 — 다시 돌리지 않습니다.
                        (성적표 발행은 "그날 발행분 통째로 갈아끼우기"라 두 번 돌아도 무해 —
                        이 검사를 하지 않습니다. 리포트 스냅샷은 벤치마크 수집 시각이 미국 스냅샷
                        수집 시각보다 뒤이면 "이미 이번 수집분으로 돌았다"로 봅니다.)

-------------------------------------------------------------------------------
소비자별 판정표 (`--role event` = workflow_run 으로 깨어남 / `--role safety-net` = cron)
-------------------------------------------------------------------------------
  소비자            event 일 때 준비 조건                                    safety-net(cron) 일 때
  ──────────────────────────────────────────────────────────────────────────────────────────────
  duel-kr           평일(KST) + 코스피 오늘 수집 완료 + 오늘 아직 미처리       오늘 아직 미처리
  duel-us           미국 스냅샷=처리일 + 벤치마크=처리일 + 처리일 아직 미처리   처리일 아직 미처리
  scorecard-kr      코스피 오늘 수집 완료                                    (게이트 없음 — 항상 진행)
  scorecard-us      미국 스냅샷=처리일 + 벤치마크=처리일                       (게이트 없음 — 항상 진행)
  report-snapshots  미국 스냅샷=처리일 + 이번 수집분으로 아직 안 돌았음          (게이트 없음 — 항상 진행)

  ⚠️ safety-net 에서 "수집 완료"를 조건으로 걸지 **않는** 이유: cron 안전망의 존재 이유가
     "크롤링이 그날 아예 안 돌았을 때도 배치가 돌아 신선도 판정으로 주문을 정리한다"
     (`duel_daily.yml` 머리말)이기 때문입니다. 안전망은 **중복만** 막습니다.
  ⚠️ `workflow_dispatch`(사람이 직접 실행)는 워크플로우가 이 게이트를 **부르지 않습니다** —
     관리자 덮어쓰기·백필 경로는 예전과 완전히 같습니다.

-------------------------------------------------------------------------------
출력 계약
-------------------------------------------------------------------------------
  · 표준출력에 판정 근거를 사람이 읽을 수 있게 찍습니다.
  · `$GITHUB_OUTPUT` 이 있으면 `ready=true|false` 와 `reason=<한 줄>` 을 씁니다 — 워크플로우의
    다음 단계가 `if: steps.gate.outputs.ready == 'true'` 로 읽습니다.
  · 종료 코드는 판정과 무관하게 **0** 입니다("준비 안 됨"은 실패가 아니라 정상적인 건너뜀).
    사용법 오류만 2. 파일이 없거나 깨진 경우는 "준비 안 됨"으로 답합니다(추측해서 돌리지 않음).
  · 이 파일은 **아무것도 쓰지 않습니다**(파일·네트워크·Supabase 전부 읽기 전용).

테스트: `tests/test_crawl_ready_gate.py` (임시 디렉터리 픽스처로 판정표 전부 + 워크플로우 YAML 의
트리거·게이트 배선).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import duel_batch, duel_batch_usd, report_db, scorecard_db   # noqa: E402
from utils.duel_batch import DuelBatchError                            # noqa: E402
from utils.duel_rules import KST                                       # noqa: E402
from utils.scorecard_db import MARKET_KR, MARKET_US                    # noqa: E402

ROLE_EVENT = "event"
ROLE_SAFETY_NET = "safety-net"
ROLES = (ROLE_EVENT, ROLE_SAFETY_NET)

CONSUMER_DUEL_KR = "duel-kr"
CONSUMER_DUEL_US = "duel-us"
CONSUMER_SCORECARD_KR = "scorecard-kr"
CONSUMER_SCORECARD_US = "scorecard-us"
CONSUMER_REPORT_SNAPSHOTS = "report-snapshots"
CONSUMERS = (CONSUMER_DUEL_KR, CONSUMER_DUEL_US, CONSUMER_SCORECARD_KR,
             CONSUMER_SCORECARD_US, CONSUMER_REPORT_SNAPSHOTS)

#: 소비자 → 어느 시장의 수집을 기다리는가 (워크플로우 YAML 테스트가 트리거 원천과 대조합니다).
CONSUMER_MARKETS = {
    CONSUMER_DUEL_KR: (MARKET_KR,),
    CONSUMER_DUEL_US: (MARKET_US,),
    CONSUMER_SCORECARD_KR: (MARKET_KR,),
    CONSUMER_SCORECARD_US: (MARKET_US,),
    CONSUMER_REPORT_SNAPSHOTS: (MARKET_US,),
}


# =============================================================================
# 1. 개별 사실 확인 — 각각 (ready: bool, reason: str[, ...]) 를 돌려주는 읽기 전용 함수
# =============================================================================
def _now_kst(now=None):
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def kr_snapshot_ready(data_dir, now_kst):
    """
    코스피 오늘 자 수집이 끝났는가 — 수집기의 사전 점검 함수를 **그대로** 묻습니다.
    수집기가 "오늘 SUCCESS 가 장마감 이후에 있으니 수집을 건너뛰겠다"(should_collect=False)고
    답하는 상태가 곧 "소비 배치가 써도 되는 오늘 데이터가 있다"입니다(#189/#195 규칙 재사용).
    """
    import collector_kospi200   # 무거운 모듈이라 필요할 때만(미국 쪽 판정에는 안 읽음)

    path = os.path.join(data_dir, scorecard_db.SNAPSHOT_FILENAMES[MARKET_KR])
    verdict = collector_kospi200.evaluate_kospi200_collection_readiness(
        snapshot_path=path, now_kst=now_kst)
    ready = not verdict["should_collect"]
    detail = (f"스냅샷 {verdict.get('snapshot_status') or '(없음)'} @ "
              f"{verdict.get('snapshot_updated_at') or '(없음)'} KST, 오늘 {verdict['target_date']}")
    if ready:
        return True, f"코스피 오늘 자 수집 완료 — {detail}"
    return False, f"코스피 오늘 자 수집 미완료 — {verdict['reason']} ({detail})"


def us_snapshot_ready(data_dir, target_date):
    """미국 스냅샷이 처리 거래일(`target_date`)의 것이고 status 가 SUCCESS 인가."""
    session_dates, price_stamps, _notes = report_db.resolve_session_info(data_dir=data_dir)
    session = session_dates.get(MARKET_US)
    payload = scorecard_db.load_snapshot_payload(MARKET_US, data_dir=data_dir) or {}
    status = (payload.get("metadata") or {}).get("status")
    stamp = price_stamps.get(MARKET_US)
    detail = f"스냅샷 거래일 {session or '(없음)'}, status {status or '(없음)'}, 수집 {stamp or '(시각 없음)'} KST"
    if session != str(target_date):
        return False, f"미국 스냅샷이 처리 거래일({target_date})의 것이 아닙니다 — {detail}", stamp
    if status != "SUCCESS":
        return False, f"미국 스냅샷 status 가 SUCCESS 가 아닙니다 — {detail}", stamp
    return True, f"미국 {target_date} 수집 완료 — {detail}", stamp


def _read_us_index_history(data_dir):
    path = os.path.join(data_dir, report_db.US_INDEX_HISTORY_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def us_benchmark_ready(data_dir, target_date):
    """두 미국 벤치마크(`report_db.US_BENCHMARK_KEYS`)에 처리 거래일 종가가 모두 있는가."""
    indices = report_db.load_us_index_closes(data_dir)
    missing = []
    for key in report_db.US_BENCHMARK_KEYS:
        closes = (indices.get(key) or {}).get("closes") or {}
        if str(target_date) not in closes:
            latest = max(closes) if closes else "(없음)"
            missing.append(f"{key}(최신 {latest})")
    if missing:
        return False, f"미국 벤치마크에 {target_date} 종가가 아직 없습니다 — {', '.join(missing)}"
    return True, f"미국 벤치마크 {target_date} 종가 확보 ({', '.join(report_db.US_BENCHMARK_KEYS)})"


def us_benchmark_collected_at_kst(data_dir):
    """`us_index_history.json` 의 `metadata.collected_at_kst` → aware datetime(KST) 또는 None."""
    payload = _read_us_index_history(data_dir) or {}
    raw = (payload.get("metadata") or {}).get("collected_at_kst")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _parse_price_stamp(stamp):
    """'YYYY-MM-DD HH:MM'(KST, `report_db.normalize_price_stamp()` 출력) → aware datetime 또는 None."""
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except ValueError:
        return None


def duel_already_done(state_path, target_date):
    """결투 기준값 파일의 `target_date` 가 처리 거래일과 같으면 그날 배치가 이미 돌아 커밋한 것."""
    try:
        probe = duel_batch.load_probe_state(state_path)
    except DuelBatchError as exc:
        # 깨진 기준값은 "처리한 적 없음"으로 봅니다 — 배치 자체가 같은 파일을 읽고 사람이 읽을
        # 사유로 보류하므로, 여기서 건너뛰면 그 안내가 로그에 남을 기회가 없어집니다.
        return False, f"결투 기준값 파일을 읽지 못했습니다({exc}) — 처리한 적 없는 것으로 봅니다"
    if probe is None:
        return False, f"결투 기준값 파일 없음({os.path.basename(state_path)}) — 첫 실행"
    baseline = probe.get("target_date")
    if str(baseline) == str(target_date):
        return True, f"결투 기준값이 이미 {target_date} 자 — 그날 배치가 이미 돌아 커밋했습니다"
    return False, f"결투 기준값은 {baseline} 자 — {target_date} 는 아직 처리 전"


# =============================================================================
# 2. 소비자별 판정 — 머리말의 판정표를 코드로
# =============================================================================
def evaluate(consumer, role, *, now=None, data_dir=None, state_path=None):
    """
    반환 dict: consumer / role / target_date / ready / reason / checks([{"name","ok","reason"}]).
    `ready` 는 checks 가 전부 ok 일 때만 True — 조건을 하나라도 확인 못 하면 "준비 안 됨"입니다.
    """
    if consumer not in CONSUMERS:
        raise ValueError(f"모르는 소비자입니다: {consumer!r} (가능: {', '.join(CONSUMERS)})")
    if role not in ROLES:
        raise ValueError(f"모르는 역할입니다: {role!r} (가능: {', '.join(ROLES)})")

    now_kst = _now_kst(now)
    data_dir = data_dir or scorecard_db.default_data_dir()
    checks = []

    def add(name, ok, reason):
        checks.append({"name": name, "ok": bool(ok), "reason": reason})

    if consumer in (CONSUMER_DUEL_KR, CONSUMER_SCORECARD_KR):
        # 코스피 배치의 처리 거래일 = 오늘(KST) — run_duel_daily_batch.py / run_scorecard_publish_batch.py 와 동일
        target_date = now_kst.date().isoformat()
    else:
        # 미국 배치의 처리 거래일 = 어제(KST) — run_duel_daily_batch_us.py 와 동일(미국 종가는 한국 다음 날 아침)
        target_date = (now_kst.date() - timedelta(days=1)).isoformat()

    if consumer == CONSUMER_DUEL_KR:
        state_path = state_path or duel_batch.default_state_path()
        if role == ROLE_EVENT:
            weekday = now_kst.weekday() < 5
            add("평일(KST)", weekday,
                f"{target_date} 는 {'평일' if weekday else '주말'} — 결투 KR 은 cron 과 같이 평일만 처리")
            add("코스피 수집 완료", *kr_snapshot_ready(data_dir, now_kst))
        done, why = duel_already_done(state_path, target_date)
        add("오늘 아직 미처리", not done, why)

    elif consumer == CONSUMER_SCORECARD_KR:
        if role == ROLE_EVENT:
            add("코스피 수집 완료", *kr_snapshot_ready(data_dir, now_kst))
        else:
            add("안전망 게이트 없음", True, "성적표 발행은 그날 발행분을 통째로 갈아끼우므로 중복 실행이 무해합니다")

    elif consumer == CONSUMER_DUEL_US:
        state_path = state_path or duel_batch_usd.default_state_path_usd()
        if role == ROLE_EVENT:
            ok, why, _stamp = us_snapshot_ready(data_dir, target_date)
            add("미국 수집 완료", ok, why)
            add("미국 벤치마크 확보", *us_benchmark_ready(data_dir, target_date))
        done, why = duel_already_done(state_path, target_date)
        add("처리 거래일 아직 미처리", not done, why)

    elif consumer == CONSUMER_SCORECARD_US:
        if role == ROLE_EVENT:
            ok, why, _stamp = us_snapshot_ready(data_dir, target_date)
            add("미국 수집 완료", ok, why)
            add("미국 벤치마크 확보", *us_benchmark_ready(data_dir, target_date))
        else:
            add("안전망 게이트 없음", True, "성적표 발행은 그날 발행분을 통째로 갈아끼우므로 중복 실행이 무해합니다")

    elif consumer == CONSUMER_REPORT_SNAPSHOTS:
        if role == ROLE_EVENT:
            ok, why, stamp = us_snapshot_ready(data_dir, target_date)
            add("미국 수집 완료", ok, why)
            collected = us_benchmark_collected_at_kst(data_dir)
            stamp_dt = _parse_price_stamp(stamp)
            if collected is not None and stamp_dt is not None and collected >= stamp_dt:
                add("이번 수집분으로 아직 미처리", False,
                    f"벤치마크 수집 시각 {collected.isoformat(timespec='minutes')} 이 미국 스냅샷 수집"
                    f" 시각 {stamp} 보다 뒤 — 리포트 스냅샷이 이번 수집분으로 이미 돌았습니다")
            else:
                add("이번 수집분으로 아직 미처리", True,
                    "벤치마크 수집 시각이 미국 스냅샷 수집 시각보다 앞이거나 없음 — 아직 안 돌았습니다"
                    if collected is not None else "벤치마크 파일이 없거나 수집 시각이 없음 — 아직 안 돌았거나 첫 실행")
        else:
            add("안전망 게이트 없음", True, "벤치마크·스냅샷 적재는 날짜 기준 upsert 라 중복 실행이 무해합니다")

    ready = all(check["ok"] for check in checks)
    failed = [check for check in checks if not check["ok"]]
    reason = ("준비 완료 — " + " / ".join(c["reason"] for c in checks)) if ready \
        else ("준비 안 됨 — " + " / ".join(c["reason"] for c in failed))
    return {
        "consumer": consumer,
        "role": role,
        "now_kst": now_kst.isoformat(timespec="minutes"),
        "target_date": target_date,
        "ready": ready,
        "reason": reason,
        "checks": checks,
    }


# =============================================================================
# 3. 실행 껍데기
# =============================================================================
def write_github_output(result, path):
    """`$GITHUB_OUTPUT` 형식(`키=값` 한 줄씩). reason 은 개행을 없애 한 줄로."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"ready={'true' if result['ready'] else 'false'}\n")
        handle.write("reason=" + " ".join(str(result["reason"]).split()) + "\n")


def format_lines(result):
    lines = [
        "=" * 70,
        f"🚦 [크롤링 완료 게이트] {result['consumer']} ({result['role']})",
        f"  · 지금(KST)       : {result['now_kst']}",
        f"  · 처리 거래일     : {result['target_date']}",
    ]
    for check in result["checks"]:
        lines.append(f"  {'✅' if check['ok'] else '⏭️'} {check['name']}: {check['reason']}")
    lines.append(f"  → {'진행' if result['ready'] else '건너뜀'}: {result['reason']}")
    lines.append("=" * 70)
    return lines


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="크롤링 결과를 소비하는 배치가 지금 돌아도 되는지(오늘 데이터가 실제로 들어왔고, "
                    "아직 처리하지 않았는지) 판정합니다. 읽기 전용, 종료 코드는 항상 0.")
    parser.add_argument("consumer", choices=CONSUMERS, help="어느 배치의 게이트인가")
    parser.add_argument("--role", choices=ROLES, default=ROLE_EVENT,
                        help="event = workflow_run 으로 깨어남(기본) / safety-net = cron 안전망")
    parser.add_argument("--data-dir", default=None, help="data/ 위치 덮어쓰기(테스트용)")
    parser.add_argument("--state-path", default=None, help="결투 기준값 파일 경로 덮어쓰기(테스트용)")
    parser.add_argument("--now", default=None, help="지금 시각 덮어쓰기(ISO, KST 로 해석 — 테스트용)")
    parser.add_argument("--github-output", default=None,
                        help="결과를 쓸 $GITHUB_OUTPUT 파일(기본: 환경변수 GITHUB_OUTPUT)")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    result = evaluate(args.consumer, args.role, now=now, data_dir=args.data_dir,
                      state_path=args.state_path)
    for line in format_lines(result):
        print(line)
    if not result["ready"]:
        # 실행 요약(Summary)에 한 줄로 드러납니다 — 건너뛴 날을 로그를 열지 않고도 알 수 있게.
        print(f"::notice title=크롤링 완료 게이트({args.consumer})::건너뜀 — {result['reason']}")
    write_github_output(result, args.github_output or os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
