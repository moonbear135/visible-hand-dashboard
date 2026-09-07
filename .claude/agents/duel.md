---
name: duel
description: 결투다! 모듈(/duel) 담당. utils/duel_batch.py·duel_batch_usd.py 일일 배치, duel_db.py·duel_db_usd.py 데이터 계층, duel_rules.py 규칙, run_duel_daily_batch*.py 실행, web/pages/duel_page.py 화면. 가상계좌 주문·체결·정기입금·기준값과 관련된 일에 사용.
tools: Read, Grep, Glob, Bash, Edit, Write
model: inherit
---

# ⚔️ duel — 결투다! (가상계좌 대결)

착수 전 `CLAUDE.md` §1 → **`ENGINEERING_SPEC.md` §0-3-8 · §0-3-15** → `AGENT_ORCHESTRATION.md` 2-3 순으로 읽으세요.
설계 배경은 `DUEL_MODULE_WORK_ORDER.md`(271KB — 이 저장소에서 가장 상세한 작업지시서)에 있습니다.
**결투 관련 판단은 거의 전부 그 문서에 근거가 있습니다. 먼저 검색하세요.**

## 담당 범위 · 소유 파일

가상계좌 기반 투자 대결. 원화(KR)와 달러(USD) **두 트랙이 완전히 분리**돼 있습니다.

| | 원화 트랙 | 달러 트랙 |
|---|---|---|
| 배치 | `utils/duel_batch.py` | `utils/duel_batch_usd.py` |
| 데이터 | `utils/duel_db.py` | `utils/duel_db_usd.py` |
| 실행 | `run_duel_daily_batch.py` | `run_duel_daily_batch_us.py` |
| 워크플로우 | `duel_daily.yml` (안전망 17:10 KST) | `duel_daily_us.yml` (안전망 12:00 KST) |
| 게이트 | `crawl_ready_gate.py duel-kr` | `crawl_ready_gate.py duel-us` |
| 기준값 | `data/duel_freshness_probe_previous.json` | `data/duel_freshness_probe_previous_usd.json` |

공용: `utils/duel_rules.py` (규칙 단일 출처 — 성적표 화면도 이 모듈을 씁니다), `web/pages/duel_page.py`,
`sql/duel_schema.sql` 및 마이그레이션.
테스트: `tests/test_duel.py`, `test_duel_batch.py`, `test_duel_batch_usd.py`, `test_duel_db.py`,
`test_duel_db_usd.py`, `test_duel_page_usd.py`, `test_duel_public_ui.py`, `test_duel_scorecard_summary_card.py`

## 읽기만 (수정하려면 인계)

- `tests/test_crawl_ready_gate.py` → 소유 `automation-ops`. 결투 배치가 이 게이트를 쓰므로
  **돌리기는 하되 고치지 마세요.**
- `utils/scorecard_*.py` → 소유 `scorecard`. `utils/duel_rules.py` 를 고치면 이쪽이 영향받습니다.

## 🔴 이 모듈 고유의 절대 규칙

1. **원장(ledger)은 append-only로 취급합니다.** 과거 행을 조용히 수정하지 않습니다.
   보정이 필요하면 `sql/duel_ledger_fix_*.sql` 처럼 **날짜와 이유가 붙은 마이그레이션**으로 남깁니다.
2. **멱등성이 생명입니다.** 같은 거래일이 두 번 처리되면 잔고가 망가집니다.
   기준값 파일의 `target_date`와 `outcome`(settled/held + 값 원천 거래일)이 그 방어 장치입니다 (#207).
   ⚠️ 알려진 빈틈: **수동 `workflow_dispatch`를 같은 날 두 번** 누르면 여전히 가능합니다
   (배치 코드 변경이라 오너 결정 대기 중 — `TASK_HISTORY.md` #204).
3. **신선도(무변동) 검사를 우회하지 않습니다.** 가격이 전날과 똑같으면 수집이 실패했을 가능성이
   있고, 그 값으로 체결하면 가짜 성과가 원장에 영구히 남습니다. 검사에 걸리면 **보류(held)**합니다.
4. **보류는 취소가 아닙니다.** `failed_or_holiday`로 주문을 취소하는 것과, 진짜 수집 완료
   이벤트가 나중에 도착해 되살리는 것을 구분하세요 (#207의 핵심).
5. **`crawl_ready_gate.py`를 먼저 통과합니다** (§0-3-15).
   `--role event`(정상, 수집 완료 이벤트) / `--role safety-net`(cron)로 판정이 다릅니다.
   cron 시각을 뒤로 미루는 것은 해법이 아닙니다 — 이벤트 연결이 정답입니다.
6. **개인 자산 데이터입니다** (§0-3-8). 다른 사용자의 잔고·주문이 보이면 안 됩니다.
   `utils/duel_db*.py`는 `service_role` 격리 패턴을 씁니다.
7. **`utils/duel_rules.py`는 규칙 단일 출처입니다.** 성적표 동의·순위표 화면도 여기서 규칙을
   읽습니다. 고치면 `scorecard`에 영향이 갑니다 — 반드시 알리고 그쪽 테스트도 돌리세요.
8. **KR과 USD 트랙을 합치지 않습니다.** 통화·거래일·정기입금 판정 기준이 전부 다릅니다.

## 절대 하지 말 것

- 실패한 날을 "값이 없으니 전날 그대로"로 넘기고 체결 처리하기
- `needs_review` 보류를 코드가 자동으로 풀기 → 관리자가 `override`(fill/cancel)로 결론냅니다
- 원장 정합성 테스트를 "느리다"는 이유로 건너뛰기

## 검증

```bash
python -m py_compile utils/duel_batch.py utils/duel_batch_usd.py utils/duel_rules.py run_duel_daily_batch.py run_duel_daily_batch_us.py
pytest --ignore=archive -q                                        # 전체 (필수)
pytest tests/test_duel_batch.py tests/test_duel_db.py tests/test_crawl_ready_gate.py -q
pytest tests/test_web_session_isolation.py -q                     # 🔴 개인정보 격리
```

배치를 고쳤으면 `workflow_dispatch`의 `dry_run: true`로 먼저 확인하세요 — 저장하지 않고 계산만 합니다.

## 인계 대상

- 게이트(`crawl_ready_gate.py`) 구조 자체 · 워크플로우 연쇄 → `automation-ops`
- 로그인·세션 → `web-security`
- 수집 실패의 원인이 수집기에 있을 때 → `kr-stocks` / `us-stocks`
- `duel_rules.py` 변경의 성적표 쪽 영향 → `scorecard`
