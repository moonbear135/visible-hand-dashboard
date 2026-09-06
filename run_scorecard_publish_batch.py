#!/usr/bin/env python3
# run_scorecard_publish_batch.py
"""
📋 "내 성적표" 공개 순위표 — **발행 배치 실행 스크립트**
   (`.github/workflows/scorecard_publish_daily.yml`(원화) 과
    `.github/workflows/scorecard_publish_daily_us.yml`(달러) 이 부르는 것)

하루 한 번(통화마다) 돌면서 `scorecard_public_leaderboard` / `scorecard_public_holdings` 두
발행표의 **그 통화 몫**을 통째로 다시 만듭니다. 저장소 루트에 두는 이유는
`run_duel_daily_batch.py` 와 같습니다 — GitHub Actions 가
`python run_scorecard_publish_batch.py --currency KRW` 한 줄로 부를 수 있어야 하니까요.

-------------------------------------------------------------------------------
💱 통화 분리 (2026-09-07, #203) — 결투와 달리 **파일이 아니라 인자**로 가릅니다
-------------------------------------------------------------------------------
결투는 `run_duel_daily_batch.py` / `run_duel_daily_batch_us.py` 로 **파일 자체**를 나눴습니다.
그쪽은 원화·달러가 모듈부터 다르기 때문입니다(`utils/duel_batch.py` vs `duel_batch_usd.py`,
표도 `duel_*` vs `duel_*_usd` 로 따로). 이 발행 배치는 처음부터 `currency` 를 **한 모듈의
축**으로 다루고(`utils/scorecard_publish.py` 머리말 ②), 두 통화의 순서·게이팅·삭제 규칙이
글자 그대로 같아서, 파일을 둘로 나누면 같은 코드가 두 벌 생깁니다(§0-3-10 위반). 그래서
스크립트는 하나이고 `--currency KRW` / `--currency USD` 가 담당 통화를 정합니다 — 워크플로우
두 개는 결투처럼 **파일을 나눠**(시각과 이름이 다르므로) 각각 이 인자 하나만 다르게 넘깁니다.
  · 인자를 생략하면 두 통화를 한 번에 발행합니다(수동 백필·예전 동작). 그 경우에도 판정은
    통화별이라 한 시장이 건너뛰어도 다른 통화는 발행됩니다(`utils/scorecard_publish.py` §4-b).
  · 🔴 어느 쪽이든 **범위 밖 통화의 발행 행은 읽지도 지우지도 않습니다** — 이 분리의 정합성
    조건이고 `tests/test_scorecard_publish.py` §14 가 고정합니다.

-------------------------------------------------------------------------------
🧱 이 파일이 하는 일 / 하지 않는 일
-------------------------------------------------------------------------------
하는 일(전부 **I/O·환경**):
  · 인자를 읽고 발행일과 담당 통화를 확정합니다(기본: 오늘 KST · 두 통화 전부).
  · 환경변수를 읽어 배치 전용 Supabase 클라이언트를 만듭니다
    (`scorecard_publish_db.create_service_client()` — 결투 배치와 **같은 프로젝트, 같은
     service_role 키**를 씁니다. 그 키를 읽는 자리는 `utils/duel_db.py` 한 곳뿐입니다).
  · `utils/scorecard_publish.py::run_publish_batch()` 를 **한 번** 부릅니다.
  · 요약을 사람이 읽을 수 있게 출력하고, 실패하면 **비정상 종료**합니다.

하지 않는 일: **판단.** 누가 발행 대상인지, 체급이 무엇인지, 어느 그룹이 최소 인원을
채웠는지는 전부 `utils/scorecard_publish.py` 가 정하고, 계산은 `utils/duel_rules.py`(순수
규칙)와 `utils/scorecard_db.py`(성적표 평가), Supabase 접근은
`utils/scorecard_publish_db.py` 입니다. 그래야 `tests/test_scorecard_publish.py` 가 네트워크
없이 그 판단들을 통째로 검증할 수 있습니다(실제로 그렇게 검증하고 있습니다).

-------------------------------------------------------------------------------
🔴 이 스크립트는 `SUPABASE_SERVICE_ROLE_KEY` 를 씁니다 (§0-3-8)
-------------------------------------------------------------------------------
키는 **GitHub Actions Secrets 에만** 있어야 합니다. 사용자가 접속하는 앱 서버(Render)의
환경변수에 넣지 마세요 — 넣는 순간 이 모듈의 RLS 가 통째로 무력화됩니다. 이 파일은 키를
출력하지 않습니다.

그리고 이 배치가 만드는 두 표는 **로그인한 모든 사용자가 읽는 값**이고, 그 내용은 가상
데이터가 아니라 사용자의 **실제 보유 자산**입니다. 그래서 실패했을 때의 기본 동작이 "조용히
넘어가기"가 아니라 **시끄럽게 멈추기**입니다 — 발행표는 "반쯤 맞는 것"이 "아무것도 없는 것"
보다 나쁜 유일한 표입니다(`utils/scorecard_publish.py` 머리말).

-------------------------------------------------------------------------------
🕘 실행 시각 — 다른 배치에 **의존하지 않습니다**
-------------------------------------------------------------------------------
결투 발행 배치는 그날의 일별 스냅샷(→ TWR)이 필요해서 체결 배치 뒤에 돌아야 했지만, 이
배치는 **`holdings` 표와 가격 스냅샷 파일**만 읽습니다. `holdings` 는 사용자가 직접 고치는
표이고, 가격 파일은 저장소에 커밋돼 있는 수집 결과입니다. 즉 선행 배치가 없습니다.
  ⚠️ 다만 **그 통화의 가격 수집이 끝난 뒤**에 도는 편이 낫습니다 — 가격을 못 구한 종목이
     많으면 그만큼 수익률을 계산할 수 없는 사용자가 늘어나고, 그 사용자들은 (0% 로 채워지는
     것이 아니라) 그날 발행에서 빠집니다. 또한 #201 의 신선도 검사가 지수 원천을 읽으므로
     그 뒤여야 검사가 살아 있습니다. 통화마다 그 "앞 단계"가 다르기 때문에(코스피 16:05
     KST 수집 → 전날 저녁에 이미 확정 / 미국 벤치마크 `scrape_report_snapshots.yml` 08:20 KST,
     실측 10시대) #203 에서 워크플로우를 둘로 나눴습니다 — 원화 07:35 KST, 달러 11:35 KST.
     각 시각의 계산은 두 워크플로우 파일의 cron 주석에 있습니다.

-------------------------------------------------------------------------------
사용법
-------------------------------------------------------------------------------
    python run_scorecard_publish_batch.py --currency KRW           # 원화 워크플로우가 부르는 것
    python run_scorecard_publish_batch.py --currency USD           # 달러 워크플로우가 부르는 것
    python run_scorecard_publish_batch.py                          # 두 통화 한 번에(수동)
    python run_scorecard_publish_batch.py --dry-run                # 쓰지 않고 계산만
    python run_scorecard_publish_batch.py --published-date 2026-08-23 --currency KRW

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

from utils import scorecard_publish, scorecard_publish_db                 # noqa: E402
from utils.duel_db import DuelDbError                                     # noqa: E402
from utils.duel_rules import KST, DuelRuleError                           # noqa: E402
from utils.scorecard_db import ScorecardError                             # noqa: E402
from utils.scorecard_publish import ScorecardPublishError                 # noqa: E402


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="내 성적표 공개 순위표 발행 배치"
                    " (철회 청소 · 체급 · 수익률 · 순위 · 최소인원 게이팅)")
    parser.add_argument("--published-date", default=None,
                        help="발행일(YYYY-MM-DD, KST). 생략하면 오늘.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Supabase 에 쓰지 않고 읽기·계산만 합니다(발행표를 건드리지 않습니다).")
    # (#203) 담당 통화. 여러 번 줄 수 있고(`--currency KRW --currency USD` = 전체), 생략하면 전체.
    # 모르는 값은 argparse 가 여기서 거절합니다 — 모듈 쪽 `normalize_currencies()` 도 다시 확인.
    parser.add_argument("--currency", action="append", default=None,
                        choices=list(scorecard_publish.PUBLISHED_CURRENCIES),
                        help="이번 실행이 발행할 통화(KRW / USD). 생략하면 두 통화 전부. "
                             "워크플로우는 원화·달러를 각각 하나씩만 넘깁니다(#203).")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    print("=" * 70)
    print("📋 [성적표 발행 배치] 시작 — 내 성적표 공개 순위표")

    # 발행일은 **호출부가 확정해서 넘깁니다.** `run_publish_batch()` 에 기본값이 없는 이유가
    # 그것입니다(배치 모듈이 스스로 "오늘"을 정하면 자정 근처 실행에서 날짜가 조용히
    # 틀어지고, 그건 나중에 복원할 수 없는 오염입니다 — 그 함수 독스트링 참고).
    published_date = args.published_date or datetime.now(KST).date().isoformat()
    currencies = scorecard_publish.normalize_currencies(args.currency)
    print(f"  · 발행일(KST): {published_date}")
    print(f"  · 담당 통화: {', '.join(currencies)}"
          + ("" if args.currency else " (인자 생략 — 두 통화 전부)"))
    if args.dry_run:
        print("  · dry-run — Supabase 에 아무것도 쓰지 않습니다(발행표는 그대로 유지됩니다).")

    if not scorecard_publish_db.service_config_present():
        # 키가 없으면 **조용히 성공한 척하지 않습니다.** 여기서 멈추지 않으면 "매일 잘
        # 돌았는데 순위표만 안 생기는" 상태가 되고, 그건 발견이 가장 늦는 실패입니다(§0-1).
        raise DuelDbError(
            "배치용 Supabase 접속 정보가 없습니다"
            " (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수)."
            " GitHub Actions Secrets 에 등록됐는지 확인하세요"
            " — 앱 서버(Render)에는 넣지 않습니다(§0-3-8)."
        )

    service_client = scorecard_publish_db.create_service_client()
    summary = scorecard_publish.run_publish_batch(
        service_client, published_date, dry_run=args.dry_run, currencies=currencies)

    for line in scorecard_publish.format_summary_lines(summary):
        print(line)
    if summary.get("publish_skipped"):
        # #201 — 건너뛴 날은 잡이 성공(exit 0)이라 로그를 열어 보지 않으면 모릅니다. GitHub
        # Actions 주석(::warning)으로 실행 요약 화면에 바로 보이게 합니다(watch_data_sanity.yml
        # 이 같은 방식을 씁니다). 예외로 잡을 실패시키지 않는 것은 오너 정책입니다.
        print(f"::warning title=성적표 발행 건너뜀::{summary.get('publish_skip_reason')}")
    else:
        # (#203) 두 통화를 한 번에 도는 실행에서 한쪽만 건너뛴 경우도 같은 방식으로 드러냅니다.
        for currency, reason in sorted((summary.get("skipped_currencies") or {}).items()):
            print(f"::warning title=성적표 {currency} 발행 건너뜀::{reason}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ScorecardPublishError, DuelDbError, DuelRuleError, ScorecardError) as exc:
        # 발행 배치는 조용히 성공한 척하면 안 됩니다 — 비정상 종료로 알립니다
        # (`run_duel_publish_batch.py` · `utils/report_db.py::main()` 과 같은 규약).
        # ⚠️ `ScorecardPublishError` 는 `DuelRuleError` 의 하위형이라 사실 두 번째 항목만으로도
        #    잡히지만, **무엇을 잡으려 했는지가 읽히도록** 이름을 그대로 적어 둡니다.
        print(f"❌ 성적표 발행 배치 실패: {exc}")
        sys.exit(1)
