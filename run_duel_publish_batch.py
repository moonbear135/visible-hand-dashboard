#!/usr/bin/env python3
# run_duel_publish_batch.py
"""
⚔️ "결투다!" — 2갈래 공개 순위표 **발행 배치 실행 스크립트**
   (`.github/workflows/duel_publish_daily.yml` 이 부르는 것)

`DUEL_MODULE_WORK_ORDER.md` **5-4** 의 발행 배치를 하루 한 번 돌립니다. 저장소 루트에 두는
이유는 `run_duel_daily_batch.py` 와 같습니다 — GitHub Actions 가
`python run_duel_publish_batch.py` 한 줄로 부를 수 있어야 하니까요.

-------------------------------------------------------------------------------
🧱 이 파일이 하는 일 / 하지 않는 일 (`run_duel_daily_batch.py` 와 **같은 분업**)
-------------------------------------------------------------------------------
하는 일(전부 **I/O·환경**):
  · 인자를 읽고 발행일을 확정합니다(기본: 오늘 KST).
  · 환경변수를 읽어 배치 전용 Supabase 클라이언트를 만듭니다
    (`duel_db.create_service_client()` — 이 저장소에서 그 키를 읽는 자리는 거기 한 곳뿐).
  · `utils/duel_publish.py::run_publish_batch()` 를 **한 번** 부릅니다.
  · 요약을 사람이 읽을 수 있게 출력하고, 실패하면 **비정상 종료**합니다.

하지 않는 일: **판단.** 누가 발행 대상인지, 체급이 무엇인지, 어느 그룹이 최소 인원을
채웠는지는 전부 `utils/duel_publish.py` 가 정하고, 계산은 `utils/duel_rules.py`, Supabase
접근은 `utils/duel_db.py` 입니다. 그래야 `tests/test_duel_publish.py` 가 네트워크 없이 그
판단들을 통째로 검증할 수 있습니다(실제로 그렇게 검증하고 있습니다).

-------------------------------------------------------------------------------
🔴 이 스크립트는 `SUPABASE_SERVICE_ROLE_KEY` 를 씁니다 (§0-3-8)
-------------------------------------------------------------------------------
키는 **GitHub Actions Secrets 에만** 있어야 합니다. 사용자가 접속하는 앱 서버(Render)의
환경변수에 넣지 마세요 — 넣는 순간 결투 모듈의 RLS 가 통째로 무력화됩니다. 이 파일은 키를
출력하지 않습니다.

그리고 이 배치가 만드는 두 표(`duel_public_leaderboard` / `duel_public_holdings`)는 **로그인한
모든 사용자가 읽는 값**입니다. 그래서 실패했을 때의 기본 동작이 "조용히 넘어가기"가 아니라
**시끄럽게 멈추기**입니다 — 발행표는 "반쯤 맞는 것"이 "아무것도 없는 것"보다 나쁜 유일한
표입니다(`utils/duel_publish.py` 머리말).

-------------------------------------------------------------------------------
🕘 실행 순서 — **체결 배치가 끝난 뒤**에 돌아야 합니다
-------------------------------------------------------------------------------
발행 배치는 그날의 일별 스냅샷(→ TWR)을 읽어 순위를 매깁니다. 그 스냅샷을 만드는 것이
`run_duel_daily_batch.py`(야간 체결 배치, `duel_daily.yml`)입니다. 순서가 뒤집히면 **하루
낡은 성적으로 순위표가 나갑니다.** 워크플로우 파일의 cron 주석에 그 시각 계산을 적어
뒀습니다(`.github/workflows/duel_publish_daily.yml`).

⚠️ 그렇다고 이 스크립트가 "체결 배치가 끝났는지"를 스스로 확인하지는 않습니다 — 확인할
   방법이 없습니다(이 저장소에 그런 상태 파일이 없습니다). 시간 간격과 워크플로우 순서로
   보장하는 구조이고, 그 사실을 여기 적어 둡니다(§0-1 — 하지 않은 것을 한 척하지 않기).

-------------------------------------------------------------------------------
사용법
-------------------------------------------------------------------------------
    python run_duel_publish_batch.py                          # 평소(오늘 KST 기준)
    python run_duel_publish_batch.py --dry-run                # 쓰지 않고 계산만
    python run_duel_publish_batch.py --published-date 2026-08-20

`--dry-run` 은 "무엇이 발행될 뻔했는지"를 오너가 먼저 눈으로 보기 위한 안전장치입니다
(§0-3-6 의 "기본 숨김 → 확인 → 공개" 순서와 같은 정신). 처음 며칠은 이것부터 돌려 보고,
요약 로그의 그룹별 인원이 납득되는 값일 때 자동 실행으로 넘어가는 것을 권합니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import duel_db, duel_publish                                  # noqa: E402
from utils.duel_db import DuelDbError                                    # noqa: E402
from utils.duel_publish import DuelPublishError                          # noqa: E402
from utils.duel_rules import KST, DuelRuleError                          # noqa: E402


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="결투다! 공개 순위표 발행 배치 (철회 청소 · 체급 · 순위 · 최소인원 게이팅)")
    parser.add_argument("--published-date", default=None,
                        help="발행일(YYYY-MM-DD, KST). 생략하면 오늘.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Supabase 에 쓰지 않고 읽기·계산만 합니다(발행표를 건드리지 않습니다).")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    print("=" * 70)
    print("⚔️ [결투 발행 배치] 시작 — 2갈래 공개 순위표")

    # 발행일은 **호출부가 확정해서 넘깁니다.** `run_publish_batch()` 에 기본값이 없는 이유가
    # 그것입니다(배치 모듈이 스스로 "오늘"을 정하면 자정 근처 실행에서 날짜가 조용히
    # 틀어지고, 그건 나중에 복원할 수 없는 오염입니다 — 그 함수 독스트링 참고).
    published_date = args.published_date or datetime.now(KST).date().isoformat()
    print(f"  · 발행일(KST): {published_date}")
    if args.dry_run:
        print("  · dry-run — Supabase 에 아무것도 쓰지 않습니다(발행표는 그대로 유지됩니다).")

    if not duel_db.service_config_present():
        # 키가 없으면 **조용히 성공한 척하지 않습니다.** 여기서 멈추지 않으면 "매일 잘
        # 돌았는데 순위표만 안 생기는" 상태가 되고, 그건 발견이 가장 늦는 실패입니다(§0-1).
        raise DuelDbError(
            "배치용 Supabase 접속 정보가 없습니다"
            f" ({duel_db.SERVICE_URL_ENV} / {duel_db.SERVICE_ROLE_KEY_ENV} 환경변수)."
            " GitHub Actions Secrets 에 등록됐는지 확인하세요"
            " — 앱 서버(Render)에는 넣지 않습니다(§0-3-8)."
        )

    service_client = duel_db.create_service_client()
    summary = duel_publish.run_publish_batch(
        service_client, published_date, dry_run=args.dry_run)

    for line in duel_publish.format_summary_lines(summary):
        print(line)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DuelPublishError, DuelDbError, DuelRuleError) as exc:
        # 발행 배치는 조용히 성공한 척하면 안 됩니다 — 비정상 종료로 알립니다
        # (`run_duel_daily_batch.py` · `utils/report_db.py::main()` 과 같은 규약).
        print(f"❌ 결투 발행 배치 실패: {exc}")
        sys.exit(1)
