# AGENT_ORCHESTRATION.md — 전체 흐름 지시서 & 모듈별 에이전트 배치도

> **이 문서의 역할**: 이 시스템이 **어떻게 돌아가는지**(데이터 흐름·자동화 연쇄·화면 지도)와,
> 그 위에 **누가 어디를 맡는지**(에이전트 12명의 경계·권한·인계 규칙)를 한 곳에 정리합니다.
>
> - 규칙 **원문**은 `ENGINEERING_SPEC.md`에 있습니다. 여기서는 §번호로 가리키기만 합니다.
> - **지금 상태**는 `PROJECT_STATUS.md`에 있습니다. 이 문서에는 "구조"만 적고 "현황"은 적지 않습니다.
> - 세션 진입 절차는 `CLAUDE.md`에 있습니다.
>
> 마지막 검증: 2026-09-07 — 아래 파일 경로·워크플로우 이름·cron 값은 저장소 실물과 대조했습니다.

---

# 1부. 전체 흐름

## 1-1. 큰 그림

```
 [외부 데이터 출처]                 [수집]              [검증]           [가공]          [저장]         [표현]
 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
 네이버 증권 ──────────────┐
 (KOSPI·KOSDAQ 시총 500)   ├─▶ collector_kospi200.py ─┐
                           │                          │
 KRX OPEN API ─────────────┤                          │
 (VKOSPI·선물, 매크로)     ├─▶ scrape_daily.py ───────┤
                           │                          ├─▶ utils/            ├─▶ utils/       ├─▶ data/*.json
 stockanalysis.com ────────┤                          │   data_validator.py │   scoring.py   │   *.csv
 (미국 종목·ETF 지수)      ├─▶ collector_us_stocks.py─┤   ① raw↔가공 대조   │   scoring_us.py│   market_
                           │   collector_us_indices.py│   ② PER 산티체크    │   guardrail.py │   history.csv
 DART OpenAPI ─────────────┤                          │   ③ 출처 간 교차    │   macro_scoring│
 (배당 공시·정기보고서)    ├─▶ collector_dividend_kr.py                     │   indicators.py│
                           │   collector_dividend_payment_kr.py             │                │
                           │   corp_code_mapper.py                          │                │
                           └─▶ collector_indicator_kr.py ───────────────────┘                │
                                                                                             ▼
 Supabase (Auth·DB) ◀────── utils/db.py · report_db.py · duel_db*.py                  utils/data_source.py
                            scorecard_db.py · scorecard_publish_db.py                  (원격 로드 · ETag)
                                        │                                                    │
                                        └──────────────────┬─────────────────────────────────┘
                                                           ▼
                                            main.py (NiceGUI) + web/pages/*
                                                           │
                                                           ▼
                                                      Render 배포
```

**핵심 원칙 3가지** (원문 `ENGINEERING_SPEC.md`):
- 수집 → 검증 → 가공 → 저장 → 표현의 **계층을 넘나들지 않습니다.** 화면(`web/pages/*`)은 읽기 전용이고,
  계산은 수집기·`utils/`에서 이미 끝나 있어야 합니다 (§6).
- 값이 없으면 **없는 대로 둡니다.** 마스킹하거나 화면에서 빼되, 지어내지 않습니다 (§0-1).
- raw 와 가공 데이터는 **분리 저장**하고 교차검증 후 병합합니다 (§0-3-3).

## 1-2. 자동화 연쇄 (GitHub Actions 17개)

**2026-09-07 기준 구조** — cron은 전부 **안전망**이고, 실제 실행은 `workflow_run`(앞 워크플로우
완료 이벤트)이 겁니다 (§0-3-15). 모든 소비 배치는 `crawl_ready_gate.py`를 먼저 통과해야 합니다.

### 🇰🇷 한국 트랙

```
scrape.yml  "Daily Market Scraper"      cron 07:05 UTC (16:05 KST, 평일)
  └ collector_kospi200.py · scrape_daily.py
        │
        ├─ workflow_run ─▶ duel_daily.yml               안전망 cron 08:10 UTC (17:10 KST)
        │                    └ crawl_ready_gate.py duel-kr → run_duel_daily_batch.py
        │
        └─ workflow_run ─▶ scorecard_publish_daily.yml  안전망 cron 22:35 UTC (07:35 KST)
                             └ crawl_ready_gate.py scorecard-kr → run_scorecard_publish_batch.py
```

### 🇺🇸 미국 트랙

```
scrape_us.yml  "Daily US Stocks Scraper"   cron 20:35 + 21:35 UTC (평일, 서머타임 2중 cron)
  └ collector_us_stocks.py   (--skip-if-not-ready 로 하루 한 번만 실제 수집)
        │
        └─ workflow_run ─▶ scrape_report_snapshots.yml  "Daily Report Snapshots"
                             안전망 cron 23:20 UTC (08:20 KST, 평일)
                             └ crawl_ready_gate.py report-snapshots → collector_us_indices.py
                                    │
     ┌──────────────────────────────┘   (두 워크플로우 완료를 모두 트리거로 받음)
     ├─ workflow_run ─▶ duel_daily_us.yml               안전망 cron 03:00 UTC (12:00 KST)
     │                    └ crawl_ready_gate.py duel-us → run_duel_daily_batch_us.py
     └─ workflow_run ─▶ scorecard_publish_daily_us.yml  안전망 cron 02:35 UTC (11:35 KST)
                          └ crawl_ready_gate.py scorecard-us → run_scorecard_publish_batch.py
```

### 독립 트랙

| 워크플로우 | 주기 | 실행 |
|---|---|---|
| `indicator_kr.yml` | cron 08:00 UTC (17:00 KST, 평일) | `collector_indicator_kr.py` |
| `collect_dividend_kr.yml` | 분기 마감 8-cron + 수동 | `collector_dividend_kr.py` (5시간 예산·체크포인트) |
| `watch_dividend_disclosures.yml` | cron 20:00 UTC (05:00 KST) | 신규 정기보고서 낸 회사만 재수집 |
| `watch_dividend_payment_events.yml` | cron 20:30 UTC (05:30 KST) | `collector_dividend_payment_kr.py` |
| `watch_data_sanity.yml` | cron 00:30 UTC (09:30 KST) | 데이터 건전성 감시 |
| `watch_schedule_health.yml` | cron 09:00 UTC (**18:00 KST**) | 11개 워크플로우 누락 감시 → 이슈·디스코드 + 1회 자동 재실행 |
| `test_suite.yml` | `push: main` | `pytest --ignore=archive -q` + 실패 시 디스코드 |
| `render_keep_awake.yml` | 10분 간격 | ⚠️ Render Starter 전환으로 사실상 불필요 — 정리 대상 (§0-3-2) |
| `probe_indicator_timing.yml` | 수동 | 일회성 조사 |
| `collect_dividend_kr_delta_2026_08.yml` | 수동 | 일회성 델타 수집 |

> 🔴 `watch_schedule_health.yml`의 cron을 앞당길 때는 **반드시 "그 시각이 장중인가"를 먼저 따지세요.**
> 예전 값(09:00 KST)은 코스피 개장 정각이라, 자동 재실행이 장중 실시간 가격을 종가로 저장할 뻔했습니다.
> `tests/test_watch_schedule_health_window.py`가 이 cron 값을 파일에서 직접 읽어 검사합니다.

### `crawl_ready_gate.py` 소비자 5종

`duel-kr` · `duel-us` · `scorecard-kr` · `scorecard-us` · `report-snapshots`
`--role event`(정상 경로) / `--role safety-net`(cron 경로)로 판정이 갈립니다.

## 1-3. 화면 지도 (`main.py` 등록 순서 기준)

| 경로 | 파일 | 접근 | 공개 스위치 |
|---|---|---|---|
| `/` | `landing_page.py` | 공개 | — (순수 FastAPI 정적 HTML) |
| `/kr` | `pegy_page.py` | 공개 | — |
| `/us` | `us_stocks_page.py` | 공개 | — |
| `/dividend` | `dividend_page.py` | 공개 | `DIVIDEND_ENABLED` |
| `/dividend/us` | `dividend_us_page.py` | 관리자 | `DIVIDEND_US_ENABLED` |
| `/indicator` | `indicator_page.py` | 관리자 | `INDICATOR_ENABLED` |
| `/scorecard` | `scorecard_page.py` | 로그인 | (공개 전환 완료) |
| `/scorecard/consent` | `scorecard_consent_page.py` | 로그인 | `SCORECARD_CONSENT_ENABLED` |
| `/scorecard/leaderboard` | `scorecard_leaderboard_page.py` | 로그인 | `SCORECARD_LEADERBOARD_ENABLED` |
| `/report` | `report_page.py` | 로그인 | (공개 전환 완료) |
| `/duel` | `duel_page.py` | 로그인 | `DUEL_ENABLED` |
| `/admin` | `admin_page.py` | 관리자 게이트 | — |
| `/admin/macro` | `macro_page.py` | 관리자 | 🛑 개발 중단 |
| `/privacy` | `privacy_page.py` | 항상 공개 | — (법적 고지문) |
| `/healthz`, `/ads.txt` | `main.py` | 공개 | — |

`/kr`·`/us`·`/dividend`·`/indicator`는 **알려진 크롤러 UA**에게만 같은 데이터를 읽은 순수 HTML을
돌려줍니다 (`web/static_html.py`). 일반 접속 경로는 바뀌지 않습니다.

---

# 2부. 에이전트 배치

## 2-1. 배치도

```
                          ┌────────────────────────────────────┐
                          │  CLAUDE.md  (진입점 · 라우팅)       │
                          │  ENGINEERING_SPEC.md (절대준수)     │
                          │  PROJECT_STATUS.md  (현재 현황)     │
                          └────────────────┬───────────────────┘
                                           │
   ┌───────────────────────── 서비스 모듈 8 ─────────────────────────┐
   │                                                                 │
   │  kr-stocks     us-stocks     dividend      indicator            │
   │   (/kr)          (/us)     (/dividend)   (/indicator)           │
   │                                                                 │
   │  scorecard       report        duel          macro 🛑           │
   │ (/scorecard)   (/report)     (/duel)     (/admin/macro)         │
   └───────────────────────────────┬─────────────────────────────────┘
                                   │  (모두 아래 4개에 의존)
   ┌───────────────────────── 공통 기반 4 ───────────────────────────┐
   │                                                                 │
   │  data-foundation   web-security   automation-ops   test-audit   │
   │   데이터·저장·검증   인증·개인정보   워크플로우·배치   테스트·감사  │
   └─────────────────────────────────────────────────────────────────┘
```

## 2-2. 에이전트 명부

| 에이전트 | 소관 | 소유 파일(수정 권한) |
|---|---|---|
| `kr-stocks` | 코스피·코스닥 PEGY | `collector_kospi200.py`, `utils/scoring.py`, `utils/guardrail.py`, `web/pages/pegy_page.py`, `data/kospi200_*`, `.github/workflows/scrape.yml` |
| `us-stocks` | 미국주식 | `collector_us_stocks.py`, `utils/scoring_us.py`, `utils/constants_us.py`, `utils/company_names_kr.py`, `web/pages/us_stocks_page.py`, `data/us_*`, `.github/workflows/scrape_us.yml` |
| `dividend` | 배당 (KR·US) | `collector_dividend_kr.py`, `collector_dividend_payment_kr.py`, `corp_code_mapper.py`, `utils/expiry_alarms.py`, `web/pages/dividend_page.py`, `dividend_us_page.py`, `dividend_us_logic.py`, `data/dividend_*`, 배당 워크플로우 4종 |
| `indicator` | 보조지표 (RSI·MACD·볼린저) | `collector_indicator_kr.py`, `utils/indicators.py`, `utils/indicator_universe.py`, `utils/indicator_ai.py`, `web/pages/indicator_page.py`, `data/indicator_*`, `.github/workflows/indicator_kr.yml` |
| `scorecard` | 내 성적표 + 공개 순위표 | `utils/scorecard_db.py`, `scorecard_ocr.py`, `scorecard_publish.py`, `scorecard_publish_db.py`, `run_scorecard_publish_batch.py`, `web/pages/scorecard_*.py`, `sql/scorecard*.sql`, 발행 워크플로우 2종 |
| `report` | 사장님 보고서 | `utils/report_db.py`, `collector_us_indices.py`, `web/pages/report_page.py`, `sql/report_schema.sql`, `.github/workflows/scrape_report_snapshots.yml` |
| `duel` | 결투다! | `utils/duel_batch.py`, `duel_batch_usd.py`, `duel_db.py`, `duel_db_usd.py`, `duel_rules.py`, `run_duel_daily_batch*.py`, `web/pages/duel_page.py`, `sql/duel_*.sql`, 결투 워크플로우 2종 |
| `macro` 🛑 | 매크로 방공망 | `scrape_daily.py`, `utils/macro_scoring.py`, `macro_ai.py`, `krx_openapi.py`, `web/pages/macro_page.py`, `market_history.csv` — **동결** |
| `data-foundation` | 데이터·저장·검증 기반 | `utils/data_source.py`, `db.py`, `data_validator.py`, `data_sanity.py`, `constants.py`, `stock_history.py`, `stock_export.py`, `gdrive_helper.py`, `.github/workflows/watch_data_sanity.yml` |
| `web-security` | 인증·개인정보·화면 기반 | `web/auth.py`, `auth_ui.py`, `layout.py`, `state.py`, `blocking.py`, `theme.py`, `static_html.py`, `ads.py`, `components/*`, `web/pages/admin_page.py`, `privacy_page.py`, `landing_page.py`, `main.py` |
| `automation-ops` | 자동화·스케줄·운영 | `.github/workflows/*` (전체 조망), `crawl_ready_gate.py`, `Dockerfile`, `requirements.txt`, `.devcontainer/`, `cloudflare_worker.js` |
| `test-audit` | 테스트·코드리뷰·감사 | `tests/*`, `AUDIT_*.md`, `SPAGHETTI_AUDIT_*.md`, 전체 코드리뷰 |

---

## 2-3. 🚧 경계 규칙 — 이것이 이 문서의 핵심입니다

### 규칙 1. 남의 파일은 읽을 수 있지만 고칠 수 없다

에이전트는 **소유 파일만 수정**합니다. 다른 에이전트의 파일은 **읽기만** 합니다.
남의 파일을 고쳐야 한다면 그 자리에서 고치지 말고 **인계 요청**(2-4)을 남깁니다.

> 예: `duel` 에이전트가 결투 화면 버그를 쫓다가 원인이 `web/auth.py`에 있음을 발견 →
> `web/auth.py`를 직접 고치지 않고, `web-security` 에게 넘길 항목으로 정리합니다.

### 규칙 2. 공통 기반 4개를 고치면 8개 모듈이 전부 영향을 받는다

`data-foundation` · `web-security` 소유 파일을 고칠 때는 **영향받는 모든 모듈을 열거**하고
그 모듈의 테스트를 전부 돌린 뒤에야 끝냅니다. 영향 범위를 열거하지 못하면 착수하지 않습니다.

### 규칙 3. 계층을 넘나들지 않는다 (§6)

- 화면(`web/pages/*`)에 **계산 로직을 넣지 않습니다.** 화면은 읽고 그리기만 합니다.
- 수집기에 **화면 문구를 넣지 않습니다.**
- 두 곳에 같은 값이 필요하면 `utils/constants*.py`에 **한 번만** 둡니다 (§0-3-10).

### 규칙 4. KR과 US는 파일도 스위치도 분리한다

`pegy_page`/`us_stocks_page`, `dividend_page`/`dividend_us_page`,
`duel_batch`/`duel_batch_usd`, `scorecard_publish_daily`/`_us` — 이 분리는 **의도된 설계**입니다.
"중복이니 합치자"는 제안은 §0-3-10 위반이 아니라 **설계 위반**입니다. 한쪽을 꺼도 다른 쪽이
그대로 돌아야 하기 때문입니다. 통합하려면 오너 승인이 필요합니다.

### 규칙 5. 매크로(`macro`)는 동결 상태다

오너 지시(2026-08-10)로 매크로 작업은 중단됐습니다. **오너가 먼저 명시적으로 지시하지 않는 한**
조사·코딩·제안 어느 것도 하지 않습니다. "다음에 뭘 할까요?"라는 질문에도 매크로를 꺼내지 않습니다.
단, `scrape_daily.py`는 매크로 데이터를 계속 쌓고 있으므로 **깨뜨리지 않게 보존**합니다.

### 규칙 6. 개인정보·자산 데이터에 손대는 순간 `web-security`가 개입한다

Supabase 사용자 데이터를 읽거나 쓰는 코드(`scorecard`·`report`·`duel` 전부 해당)는
**변경 전후로 `web-security`의 세션 격리 검사**를 통과해야 합니다.
관련 테스트: `tests/test_web_session_isolation.py` (148KB, 이 저장소 최대 테스트).
§0-3-8은 이 프로젝트 최상위 금지사항이며 예외가 없습니다.

---

## 2-4. 🔁 인계 프로토콜

에이전트 사이의 인계는 **말이 아니라 문서**로 합니다. 다음 세션에는 지금 대화가 없습니다.

인계가 필요할 때 `PROJECT_STATUS.md` §4 "지금 열려있는 일"에 아래 형식으로 남깁니다.

```markdown
- 🔀 **[인계: duel → web-security]** `/duel` 로그인 만료 시 빈 화면.
  - **증상**: 세션 만료 후 `/duel` 재진입 시 카드가 0개로 렌더됨 (재현 100%).
  - **원인 추정**: `web/auth.py:has_supabase_session()` 이 만료 토큰에 True를 돌려줌 (미확인).
  - **duel 쪽에서 확인한 것**: `duel_page.py` 는 세션 판정 결과를 그대로 신뢰만 함 — 이쪽 버그 아님.
  - **넘기는 이유**: `web/auth.py` 는 web-security 소유 파일 (경계 규칙 1).
  - **영향 범위**: `/scorecard`·`/report` 도 같은 함수를 씀 — 함께 확인 필요.
```

**인계서에 반드시 들어갈 5가지**: 증상(재현 방법) / 원인 추정과 **미확인 표시** /
내 쪽에서 배제한 것 / 넘기는 이유 / 영향 범위.

> ⚠️ 원인을 **확인하지 않았으면 "추정"이라고 씁니다** (§0-1). 추정을 사실처럼 넘기면
> 받는 쪽이 엉뚱한 곳을 파게 됩니다.

---

## 2-5. 🔨 작업 프로토콜 (모든 에이전트 공통)

### 착수 전
1. `CLAUDE.md` §1 세션 시작 절차 완료.
2. 이 일이 **내 소유 파일 안에서 끝나는가?** 아니면 인계·협업인가 판단.
3. **버그 수정인가, 새 기능인가?** 새 기능이면 §0-3-6 — 스테이징 + 오너 승인이 먼저.
4. `CLAUDE.md` §4 "오너 결정 사항"에 해당하는가 확인. 해당하면 **멈추고 묻는다.**

### 작업 중
5. 값이 없으면 **없는 대로 둔다.** 지어내는 순간 §0-1 위반이고 데이터 전체가 오염된다.
6. 외부 서버에 요청을 붙이면 **딜레이·재시도 상한·차단 시 중단**을 같이 넣는다 (§0-3-2).
7. 비밀값은 환경변수에서만 읽고 로그·화면·문서에 남기지 않는다.
8. raw 와 가공 데이터를 분리해 저장한다 (§0-3-3).

### 종료 전
9. `pytest --ignore=archive -q` **전체** 통과. 내 모듈만 돌리고 끝내지 않는다.
10. 화면을 고쳤으면 실제로 렌더되는지 확인한다 — 코드가 통과했다고 화면이 뜨는 것은 아니다.
11. `PROJECT_STATUS.md` + `TASK_HISTORY.md` 갱신, `git push`까지 완료 (§0-2, §0-3-5).
12. 이 문서(`AGENT_ORCHESTRATION.md`)의 소유 파일 목록이 바뀌었으면 **여기도 고친다.**

### 🔍 코드리뷰·재검토 (§ 오너 지시)
목표 구간이 끝나면 스파게티 코드를 막기 위해 전체 코드를 읽고 정리하는 재검토를 합니다.
**이 작업은 토큰을 크게 쓰므로 착수 전에 반드시 오너에게 먼저 묻습니다.**
담당은 `test-audit`이며, 결과는 `AUDIT_*.md` 형식으로 남깁니다.

---

## 2-6. 새 모듈을 추가할 때 (= 새 기능을 만들 때)

> 🔴 **이 절차는 문서가 아니라 테스트가 강제합니다.**
> `tests/test_agent_registry.py::test_every_module_file_has_exactly_one_owning_agent` 가
> `web/pages/*.py` · `web/*.py` · `utils/*.py` · `.github/workflows/*.yml` ·
> 루트의 `collector_*`·`run_*`·`scrape_*`·`crawl_*`·`corp_*`·`probe_*`·`main.py` 를 훑어
> **어느 에이전트도 소유하지 않는 파일이 하나라도 있으면 빨간불**을 냅니다.
> `test_suite.yml` 이 `push: main` 마다 돌리므로, 잊으면 반드시 걸립니다.

**누가 쓰는가** — 그 모듈을 만든 세션이 직접 씁니다. 모듈을 방금 만든 세션이 그 모듈을 가장 잘
알고, 나중에 다른 에이전트가 쓰려면 코드를 처음부터 다시 읽어야 하기 때문입니다.
`test-audit` 에게 넘기지 마세요.

**순서** (§0-3-6 에 따라 새 기능은 **오너 승인 후** 실전 반영입니다 — 승인 전에 아래를 끝내 두세요):

1. `.claude/agents/_TEMPLATE.md` 를 `.claude/agents/<이름>.md` 로 복사해 채운다.
   - `name` 은 **파일명과 똑같이** (소문자·하이픈). 검사됨.
   - `description` 은 라우팅을 결정하는 문장이다 — 어떤 파일·경로·주제일 때 부를지 구체적으로.
   - **`## 소유 파일` 섹션 제목을 바꾸지 않는다.** 테스트가 이 제목으로 소유를 판정한다.
2. 새로 만든 파일 경로를 그 `## 소유 파일` 섹션에 **백틱으로** 적는다.
   남의 파일을 참고만 한다면 `## 읽기만` 섹션에 적는다 — 거기 적은 것은 소유로 치지 않는다.
3. `CLAUDE.md` §3 라우팅 표에 한 줄 추가한다. (양쪽 다 있어야 통과)
4. 이 문서 §2-2 명부 표에 한 줄 추가한다.
5. `PROJECT_STATUS.md` §2 파일 구조 표에 새 파일을 추가한다.
6. 새 외부 출처를 쓴다면 `ENGINEERING_SPEC.md` §0-3-2 의 **매너 장치 목록에도 추가**한다.
7. `pytest tests/test_agent_registry.py -q` 로 확인한다.

**기존 에이전트가 맡는 게 맞다면** 새 에이전트를 만들지 말고 그 파일의 `## 소유 파일` 섹션에
한 줄만 추가하세요. 에이전트를 늘리는 것 자체가 목적이 아닙니다.

### 이 검사가 잡는 것 (사보타주로 실증, 2026-09-07)

| 망가뜨린 것 | 결과 |
|---|---|
| 새 화면 `web/pages/*.py` 를 만들고 등록 안 함 | 🔴 `test_every_module_file_has_exactly_one_owning_agent` |
| 새 수집기 + 새 워크플로우를 만들고 등록 안 함 | 🔴 같은 검사 |
| 두 에이전트가 같은 파일을 소유 | 🔴 `test_no_file_is_owned_by_two_agents` |
| 에이전트를 만들고 `CLAUDE.md` 라우팅 표에 안 넣음 | 🔴 `test_every_agent_is_routed_from_both_entry_documents` |
| `## 소유 파일` 섹션 제목을 바꿈 | 🔴 `test_every_agent_declares_an_ownership_section` |
| 문서가 없는 파일을 가리킴 | 🔴 `test_agent_documents_do_not_reference_nonexistent_files` |

> ⚠️ 이 검사는 **"주인이 있는가"만** 봅니다. 그 에이전트 문서의 내용이 좋은지, 규칙이 맞는지는
> 검사하지 못합니다. 서식만 맞춰 빈 껍데기를 만들면 통과합니다 — 검사는 최저선일 뿐입니다.
