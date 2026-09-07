# 🔴 네이버 증권 개편 대응 작업지시서 (2026-09-07 신설)

> **배경**: 오너가 네이버 증권 화면에서 배너를 직접 발견 —
> *"기존 증권 서비스는 9월 10일 종료되며, 더 향상된 투자 경험으로 개편됩니다."*
> 구 `finance.naver.com` → 신 `stock.naver.com`("Npay 증권"). **발견일 기준 3일 남음.**
>
> 이 문서는 **조사 결과와 대응 계획**입니다. 코드는 아직 하나도 안 고쳤습니다 —
> 아래 §1 의 미확인 사항을 먼저 확인하지 않고 고치면 엉뚱한 걸 만들게 됩니다.

---

## 0. 영향 범위 (실측)

### 0-1. 저장소가 쓰는 `finance.naver.com` 엔드포인트 7개

| 엔드포인트 | 쓰는 파일 | 담당 에이전트 |
|---|---|---|
| `sise/sise_market_sum.naver?sosok=` | `collector_kospi200.py` | `kr-stocks` |
| `item/main.naver?code=` | `collector_kospi200.py` | `kr-stocks` |
| `sise/investorDealTrendDay.naver` (3종) | `scrape_daily.py` · `utils/db.py` · `web/pages/macro_page.py` | `macro` 🛑동결 · `data-foundation` |
| `sise/sise_index.naver?code=KOSPI` | `scrape_daily.py` · `web/pages/macro_page.py` | `macro` 🛑동결 |
| `marketindex/` | `scrape_daily.py` · `web/pages/macro_page.py` | `macro` 🛑동결 |

별도 도메인: `navercomp.wisereport.co.kr`(EV/EBITDA) — **이번 종료 대상인지 불명.**

### 0-2. 멈추면 번지는 경로

```
scrape.yml ("Daily Market Scraper")  ← 여기가 죽으면
   ├── /kr 코스피·코스닥 PEGY  ......... 공개 화면
   ├── duel_daily.yml ................. ⚔️ 결투 원화 트랙
   └── scorecard_publish_daily.yml .... 📊 성적표 원화 발행
```

워크플로우가 `workflow_run` 으로 엮여 있어(§0-3-15) 앞이 죽으면 뒤도 안 돕니다.

**영향 없음(실측 확인)**: 미국주식(stockanalysis.com) · 배당(DART OpenAPI) ·
**보조지표(`collector_indicator_kr.py` 는 FinanceDataReader 만 씀 — 네이버 미사용)**.

### 0-3. 조용히 틀리지는 않습니다

§0-1 설계 덕분에 파싱이 깨지면 값을 지어내지 않고 `None` → "데이터 없음"이 됩니다.
`watch_data_sanity.yml`(매일 09:30 KST)이 `unusable_ratio` 급등을 잡아 디스코드로 알립니다.

⚠️ **단, 감시 필드가 `price`·`market_cap` 두 개뿐**입니다. 목록 페이지가 깨지면 즉시 걸리지만
**종목 상세만 깨지면(DPS·PBR·추정치) 이 감시망에 안 걸립니다.** → §4-1 참고.

---

## 1. 🔴 먼저 확인해야 할 것 (확인 전에 코드 고치지 말 것)

세션은 웹 접근이 차단돼 있어 직접 확인할 수 없었습니다 — `finance.naver.com` 과
`stock.naver.com` **둘 다 `SITE_BLOCKED`** 였고, curl 등 우회 수단은 쓰지 않았습니다.
**브라우저를 가진 오너가 확인해 주셔야 합니다.**

신 사이트 주소(오너 확인, 2026-09-07): **https://stock.naver.com/**

| # | 확인할 것 | 확인 방법 |
|---|---|---|
| 1 | `finance.naver.com/item/main.naver?code=005930` 이 **9/10 이후에도 열리는가** | 브라우저 주소창에 그대로 입력 |
| 2 | 열린다면 **우측 투자정보 표(PERlEPS·추정PERlEPS·PBRlBPS·배당수익률·상장주식수) 구조가 그대로인가** | 같은 페이지에서 눈으로 |
| 3 | `stock.naver.com` 종목 상세에 **추정 PER·EPS(애널리스트 컨센서스)** 가 있는가 | 새 사이트에서 삼성전자 등 아무 종목 |
| 3-2 | 새 사이트 **종목 상세 주소 형태** (예: `stock.naver.com/domestic/stock/005930/total`) | 종목을 눌러 주소창 확인 |
| 4 | `navercomp.wisereport.co.kr` 이 살아 있는가 | 주소창 입력 |

> 📌 1번이 "열린다"면 이 문서의 나머지는 **당분간 보류**해도 됩니다. 대형 서비스는 구 URL 을
> 한동안 유지하는 경우가 많습니다. **확인 전에 "3일 뒤 다 죽는다"고 단정하지 않습니다(§0-1).**

---

## 2. 필드 단위 의존 목록 · 대체 후보 (2026-09-07 실측)

수집 종목 520개 기준. "네이버 현재"는 지금 스냅샷의 실제 충족률입니다.

| 항목 | 네이버 현재 | 대체 후보 | 대체 커버리지 | 판정 |
|---|---|---|---|---|
| 현재가·시가총액 | 100% | FinanceDataReader | 가능 | ✅ |
| 상장주식수 | 100% | FDR (**이미 1차 출처**) | 100% | ✅ |
| EPS (Trailing) | 79% | DART 배당보고서 `eps` | 78% | ✅ |
| 순이익 | — | DART `net_income_mkrw` | 79% | ✅ |
| 주당배당금(DPS) | 98% | KIND 연간요약 `dps_krw` (`data/dividend_history_kr_2023_2025.json`) | 70% | 🟡 |
| 배당수익률 | — | KIND `dividend_yield_pct` | 70% | 🟡 |
| PER (Trailing) | 79% | **가격 ÷ EPS 계산** | 계산 | 🟡 |
| PBR | 98% | BPS 출처 필요 | **미확인** | ❔ |
| **추정 PER·EPS** | **50%** | **없음** | — | 🔴 |
| **Forward ROE** | **72%** | **없음** | — | 🔴 |

### 2-1. 이미 저장소 안에 있는 대체 출처 3개 (새로 붙일 필요 없음)

- **FinanceDataReader** — `collector_kospi200.py` 가 상장주식수 1차 출처로 이미 사용 중.
- **DART OpenAPI** — 배당 모듈이 이미 수집. `data/dividend_kr_2026_latest.json` 2,590건에
  `eps` · `net_income_mkrw` · `payout_ratio` 포함. 코스피 종목과 **92.3% 겹침**.
- **KIND 연간 배당요약** — `data/dividend_history_kr_2023_2025.json` 8,202건(2023~2025 각 2,734종목).
  `dps_krw` · `dividend_yield_pct` · `shares_outstanding_year_end` 포함.

### 2-2. 🔴 진짜 병목 — 애널리스트 컨센서스

**추정 PER·EPS 와 Forward ROE 는 대체 출처가 없습니다.** 이건 증권사 애널리스트 추정치라
공공 API 로 안 나옵니다. `ENGINEERING_SPEC.md` §5-1 의 PEGY 공식이 이 값들을 쓰므로,
못 구하면 **Forward 계열(f_pegy·목표주가·상승여력)이 산출 불가**가 됩니다.

**다만 치명적이지는 않습니다.** 지금도 **520종목 중 279종목(53.7%)이 이미 Forward 없이**
돌고 있습니다(`forward_data_missing=True`). 코드가 그 상태를 정상 처리하도록 이미 설계돼
있습니다 — 해당 섹션만 마스킹하고 Trailing 계열(t_pegy·그레이엄 넘버)로 표시합니다
(§0-1 예시2-보충2).

→ **최악의 경우 `/kr` 은 "Trailing 전용 화면"으로 축소되지만, 죽지는 않습니다.**

### 2-3. 우선주 DPS

현재 우선주 DPS 는 보통주에서 **추측 상속**합니다(재감사 H12 로 마스터 확인 조건을 붙였지만
여전히 추측). 대체 출처를 뒤졌으나 **DART·KIND 어느 쪽에도 우선주 DPS 실측이 없었습니다**
(우선주 14개 중 0개). 이 항목은 네이버가 죽으면 **그냥 미수집으로 두는 것이 맞습니다** —
지어내지 않습니다(§0-1).

---

## 3. 대응 단계 (§1 확인 후 진행)

### 3-A. 구 URL 이 살아 있는 경우
아무것도 안 합니다. `PROJECT_STATUS.md` §4 항목에 확인 결과와 날짜만 남기고, 산티체크
감시 필드 확대(§4-1)만 별도로 진행합니다.

### 3-B. 구 URL 이 죽고, 새 사이트에 같은 데이터가 있는 경우
1. 새 페이지 HTML(또는 JSON 응답)을 **몇 종목만** 받아 `tests/fixtures/naver_item/` 에 저장.
   §0-3-2 — 조사 목적이라도 요청은 최소로, 딜레이를 두고.
2. 바뀐 구획만 고칩니다. 2026-09-07(#210) 분해 덕분에 범위가 좁습니다:
   - aside 표기 변경 → `_parse_aside_invest_info` (108줄)
   - 재무제표 표 변경 → `_parse_financial_statement` (147줄)
   - 목록 페이지 변경 → `fetch_kospi200_real_market_data`
3. **기준선을 새 구조로 재생성**(오너 승인 필요):
   `python tests/_naver_item_baseline.py --regenerate`
   ⚠️ 지금 기준선은 **구 구조 합성 HTML** 이라 새 구조를 보증하지 못합니다.
4. `sabotage-verify` 스킬대로 일부러 망가뜨려 새 기준선이 진짜 잡는지 확인.
5. `ENGINEERING_SPEC.md` §0-3-2 매너 장치 목록에 새 주소 추가.

### 3-C. 새 사이트에도 추정치가 없는 경우 (최악)
1. 대체 가능한 항목부터 이관: 가격·시총·상장주식수(FDR) → EPS·순이익(DART) → DPS·배당수익률(KIND).
2. Trailing PER 을 **계산값**으로 산출하되 반드시 마킹합니다
   (§0-1 예시2-보충 — 이미 `t_eps_calculated` 전례가 있음).
3. Forward 계열은 **산출하지 않고 마스킹**합니다. 이미 절반이 그 상태이므로 새 코드가 아닙니다.
4. 🔴 **화면 문구를 반드시 함께 고칩니다** — 사용자가 "왜 목표주가가 사라졌지?"를 알 수 있게
   (§0-3-13 — 유의사항을 툴팁 뒤에 숨기지 않음). **오너 승인 사항.**

### 3-D. KRX OPEN API 를 늘려 쓰는 경우 — ⚠️ 약관 재검토 필수
`utils/krx_openapi.py` 가 이미 있지만, **약관 제6조②(비상업적 목적 한정, 결과에 대한 대가를
제3자에게 청구 불가)** 가 걸립니다. `/kr` 은 **광고가 붙는 공개 화면**이라 매크로(비공개)와
사정이 다릅니다. 쓰기 전에 ① 그 페이지 광고 제외 ② 유료 상업 라이선스 중 하나를 골라야
합니다. **오너 결정 사항** (`PROJECT_STATUS.md` §4 매크로 항목과 같은 조항).

---

## 4. 함께 하면 좋은 것

### 4-1. 산티체크 감시 필드 확대 (`data-foundation` 소관)
현재 `price`·`market_cap` 두 개만 봅니다. **`dps`·`t_pbr`·`t_eps`·`outstanding_shares`** 를
추가하면 종목 상세 페이지 구조 변경도 다음 날 아침에 걸립니다. 이번 건과 무관하게 가치가 있고,
이번 건에서는 **"조용히 절반만 깨지는" 상황을 잡아주는 안전망**이 됩니다.

---

## 5. 하지 않은 것 (§0-1)

- **구 URL 이 실제로 죽는지 확인하지 못했습니다.** 세션의 웹 접근이 차단(`SITE_BLOCKED`)돼
  있고, 우회 수단(curl 등)은 쓰지 않았습니다. §1 은 오너 확인 사항입니다.
- **새 사이트 `stock.naver.com` 의 데이터 구조를 보지 못했습니다.** 같은 이유입니다.
  "JSON API 일 것이다" 같은 추측은 적지 않았습니다.
- **PBR 대체 출처를 찾지 못했습니다.** BPS(자본총계 ÷ 상장주식수)로 계산할 수 있을 가능성은
  있으나 DART 배당보고서에 자본총계가 있는지 확인하지 않았습니다 — 미확인으로 남깁니다.
- **코드는 한 줄도 고치지 않았습니다.** §1 확인 전에 고치는 것은 추측으로 만드는 것입니다.
