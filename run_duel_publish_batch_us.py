#!/usr/bin/env python3
# run_duel_publish_batch_us.py
"""
⚔️ "결투다!" USD 트랙 — 2갈래 공개 순위표 **발행 배치 실행 스크립트**
   (`.github/workflows/duel_publish_daily_us.yml` 이 부르는 것
    — `run_duel_publish_batch.py`(원화)의 통화 미러)

`DUEL_MODULE_WORK_ORDER.md` **5-4**(발행 순서) · **5-11-9**(순위표는 한국장·미국장 완전
별개 표) 의 USD 발행 배치를 하루 한 번 돌립니다. 저장소 루트에 두는 이유는 원화 스크립트와
같습니다 — GitHub Actions 가 `python run_duel_publish_batch_us.py` 한 줄로 부를 수 있어야
하니까요.

-------------------------------------------------------------------------------
🧱 이 파일이 하는 일 / 하지 않는 일 (`run_duel_publish_batch.py` 와 **같은 분업**)
-------------------------------------------------------------------------------
하는 일(전부 **I/O·환경**):
  · 인자를 읽고 발행일을 확정합니다(기본: 오늘 KST).
  · 환경변수를 읽어 배치 전용 Supabase 클라이언트를 만듭니다
    (`duel_db_usd.create_service_client()` — 이 함수는 원화 모듈에서 그대로 재사용하는
     **같은 객체**이고, 원화·달러가 **같은 Supabase 프로젝트·같은 service_role 키**를
     씁니다. 두 번째 키를 만들지 않습니다 — `utils/duel_db_usd.py` 머리말 참고).
  · `utils/duel_publish_usd.py::run_publish_batch_usd()` 를 **한 번** 부릅니다.
  · 요약을 사람이 읽을 수 있게 출력하고, 실패하면 **비정상 종료**합니다.

하지 않는 일: **판단.** 누가 발행 대상인지, 체급이 무엇인지, 어느 그룹이 최소 인원을
채웠는지는 전부 `utils/duel_publish_usd.py` 가 정하고, 계산은 `utils/duel_rules.py`,
Supabase 접근은 `utils/duel_db_usd.py` 입니다. 그래야 `tests/test_duel_publish_usd.py` 가
네트워크 없이 그 판단들을 통째로 검증할 수 있습니다(실제로 그렇게 검증하고 있습니다).

-------------------------------------------------------------------------------
🔴 이 스크립트는 `SUPABASE_SERVICE_ROLE_KEY` 를 씁니다 (§0-3-8)
-------------------------------------------------------------------------------
키는 **GitHub Actions Secrets 에만** 있어야 합니다. 사용자가 접속하는 앱 서버(Render)의
환경변수에 넣지 마세요 — 넣는 순간 결투 모듈의 RLS 가 통째로 무력화됩니다. 이 파일은 키를
출력하지 않습니다.

그리고 이 배치가 만드는 두 표(`duel_public_leaderboard_usd` / `duel_public_holdings_usd`)는
**로그인한 모든 사용자가 읽는 값**입니다. 그래서 실패했을 때의 기본 동작이 "조용히
넘어가기"가 아니라 **시끄럽게 멈추기**입니다 — 발행표는 "반쯤 맞는 것"이 "아무것도 없는
것"보다 나쁜 유일한 표입니다(`utils/duel_publish.py` 머리말).

-------------------------------------------------------------------------------
🕘 실행 순서 — **USD 체결 배치가 끝난 뒤**에 돌아야 합니다 (원화와 시각이 다릅니다)
-------------------------------------------------------------------------------
발행 배치는 그날의 일별 스냅샷(→ TWR)을 읽어 순위를 매깁니다. 그 스냅샷을 만드는 것이
`run_duel_daily_batch_us.py`(USD 야간 배치, `duel_daily_us.yml`, cron `0 3 * * *` =
03:00 UTC = KST 정오, `timeout-minutes: 20` → 최악의 경우 03:20 UTC 종료)입니다.
순서가 뒤집히면 **하루 낡은 성적으로 순위표가 나갑니다.**

  · **원화 트랙이 쓴 여유 = 30분**(체결 배치 타임아웃 상한 08:30 UTC → 발행 09:00 UTC,
    2026-08-20 오너 확정 — 처음 10분에서 늘림).
  · **같은 30분을 USD 에 적용** → 03:20 UTC + 30분 = **03:50 UTC**(= KST 12:50).

계산 근거 전문은 `.github/workflows/duel_publish_daily_us.yml` 머리말에 적어 뒀습니다.

⚠️ 그렇다고 이 스크립트가 "체결 배치가 끝났는지"를 스스로 확인하지는 않습니다 — 확인할
   방법이 없습니다(이 저장소에 그런 상태 파일이 없습니다). 시간 간격과 워크플로우 순서로
   보장하는 구조이고, 그 사실을 여기 적어 둡니다(§0-1 — 하지 않은 것을 한 척하지 않기).

-------------------------------------------------------------------------------
사용법
-------------------------------------------------------------------------------
    python run_duel_publish_batch_us.py                          # 평소(오늘 KST 기준)
    python run_duel_publish_batch_us.py --dry-run                # 쓰지 않고 계산만
    python run_duel_publish_batch_us.py --published-date 2026-08-21

`--dry-run` 은 "무엇이 발행될 뻔했는지"를 오너가 먼저 눈으로 보기 위한 안전장치입니다
(§0-3-6 의 "기본 숨김 → 확인 → 공개" 순서와 같은 정신). 처음 며칠은 이것부터 돌려 보고,
요약 로그의 그룹별 인원이 납득되는 값일 때 자동 실행으로 넘어가는 것을 권합니다.

⚠️ **발행일은 원화 배치처럼 "오늘 KST"가 기본입니다.** USD **체결** 배치는
   `--target-date` 기본값이 "어제"인데(미국 마감가가 한국 날짜 X+1일 아침에야 들어오기
   때문 — §5-15), 여기서 정하는 것은 **거래일이 아니라 "이 순위표를 몇 일자로 발행하는가"**
   라서 성격이 다릅니다. 화면은 각 그룹의 **가장 최근 발행일**을 읽으므로(5-7), 발행일은
   "이 표가 언제 만들어졌는가"를 뜻하는 값이고 배치가 도는 날이 맞습니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import duel_db, duel_db_usd, duel_publish_usd                 # noqa: E402
from utils.duel_db import DuelDbError                                    # noqa: E402
from utils.duel_publish_usd import DuelPublishError                      # noqa: E402
from utils.duel_rules import KST, DuelRuleError                          # noqa: E402


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="결투다! USD 공개 순위표 발행 배치 (철회 청소 · 체급 · 순위 · 최소인원 게이팅)")
    parser.add_argument("--published-date", default=None,
                        help="발행일(YYYY-MM-DD, KST). 생략하면 오늘.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Supabase 에 쓰지 않고 읽기·계산만 합니다(발행표를 건드리지 않습니다).")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    print("=" * 70)
    print("⚔️ [결투 USD 발행 배치] 시작 — 2갈래 공개 순위표(달러 트랙)")
    # 원화 순위표와 **물리적으로 다른 표**입니다(5-11-9). 로그만 보고 어느 트랙인지
    # 헷갈리지 않도록 여기서 한 번 못박아 둡니다 — 요약 줄 자체는 원화와 공유하는
    # 함수(`format_summary_lines()`)가 만들기 때문입니다.
    print(f"  · 대상 표: {duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD}"
          f" / {duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD}")

    # 발행일은 **호출부가 확정해서 넘깁니다.** `run_publish_batch_usd()` 에 기본값이 없는
    # 이유가 그것입니다(배치 모듈이 스스로 "오늘"을 정하면 자정 근처 실행에서 날짜가 조용히
    # 틀어지고, 그건 나중에 복원할 수 없는 오염입니다 — 그 함수 독스트링 참고).
    published_date = args.published_date or datetime.now(KST).date().isoformat()
    print(f"  · 발행일(KST): {published_date}")
    if args.dry_run:
        print("  · dry-run — Supabase 에 아무것도 쓰지 않습니다(발행표는 그대로 유지됩니다).")

    if not duel_db_usd.service_config_present():
        # 키가 없으면 **조용히 성공한 척하지 않습니다.** 여기서 멈추지 않으면 "매일 잘
        # 돌았는데 순위표만 안 생기는" 상태가 되고, 그건 발견이 가장 늦는 실패입니다(§0-1).
        raise DuelDbError(
            "배치용 Supabase 접속 정보가 없습니다"
            f" ({duel_db.SERVICE_URL_ENV} / {duel_db.SERVICE_ROLE_KEY_ENV} 환경변수)."
            " GitHub Actions Secrets 에 등록됐는지 확인하세요"
            " — 앱 서버(Render)에는 넣지 않습니다(§0-3-8)."
            " (원화 트랙과 **같은 키·같은 프로젝트**를 씁니다 — 두 번째 키를 만들지 않습니다.)"
        )

    service_client = duel_db_usd.create_service_client()
    summary = duel_publish_usd.run_publish_batch_usd(
        service_client, published_date, dry_run=args.dry_run)

    for line in duel_publish_usd.format_summary_lines(summary):
        print(line)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DuelPublishError, DuelDbError, DuelRuleError) as exc:
        # 발행 배치는 조용히 성공한 척하면 안 됩니다 — 비정상 종료로 알립니다
        # (`run_duel_publish_batch.py` · `run_duel_daily_batch_us.py` 와 같은 규약).
        print(f"❌ 결투 USD 발행 배치 실패: {exc}")
        sys.exit(1)
