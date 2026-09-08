# 🌐 외부 데이터 출처 재고조사 (DATA_SOURCES_INVENTORY)

> **소유 에이전트: `data-sources`** (`.claude/agents/data-sources.md`).
> **이 문서가 낡으면 테스트가 빨간불을 냅니다** — `tests/test_data_sources_inventory.py` 가 부록 A·B 의
> "기계가 읽는 목록"을 코드와 대조합니다. 코드에 새 바깥 주소·새 패키지가 생기면 이 문서에도 적어야
> 테스트가 통과합니다.
>
> 첫 작성: 2026-09-08 (같은 날 외부 출처 두 곳이 동시에 무너진 사고 직후 — 아래 §0).

---

## 0. 왜 이 문서가 생겼는가 — 2026-09-08 에 실제로 난 사고

하루에 외부 출처 **두 개가 동시에** 무너졌습니다 (`TASK_HISTORY.md` #221·#222·#224).

1. **네이버 구 증권 순위 페이지가 0건**을 돌려주기 시작했습니다(종료 예고일 9/10 보다 이틀 빠름).
   브라우저로는 페이지가 보이는데 "Npay 증권"으로 개편돼 **파서가 읽던 표가 사라진 것**으로 추정됩니다.
   → HTTP 200 이면서 우리한테는 0건. **"살아 있음"과 "우리가 쓸 수 있음"은 다릅니다** (§5 참고).
2. **FinanceDataReader `StockListing('KRX')` 가 404.** 신 출처로 전환한 뒤 첫 실전 실행이 이것 때문에
   한 번 더 멈췄습니다(659종목 전부 순위 계산에서 제외 → 0개 → 중단).

🔴 그런데 ②는 `ENGINEERING_SPEC.md` §0-3-2 의 "우리가 접속하는 대상" 목록에 **아예 없었습니다.**
"이게 죽으면 뭐가 멈추지?"를 아무도 미리 생각해 본 적이 없었습니다. 그리고 `StockListing('KRX')` 는
한국거래소에서 직접 받는 게 아니라 ①`data.krx.co.kr` 에 최신 일자를 묻고 ②**FinanceData 라는 곳이
깃허브에 올려두는 캐시 CSV** 를 받는 구조였습니다 — **우리는 그런 구조인 줄도 모르고 쓰고 있었습니다.**

오너 지시(원문): *"우리가 지금 데이터를 가져오는 곳을 API던 공식이던 뭐던 탐색하는 에이전트를 하나
만들고 작업을 시킬 수는 없을까?"* / *"오픈소스던 뭐던 그런것들을 관리가 되고있는 곳이 있는지도 계속
조사를 해보고 관리를 하는 곳을 계속 탐색도 해봐야하니까."*

---

## 1. 🔴 확인한 것 / 확인 못 한 것 (§0-1 — 지어내지 않기)

이 조사는 **오너 컴퓨터에서 저장소 코드와, 그 컴퓨터에 설치된 라이브러리 소스를 읽어서** 했습니다.
바깥 네트워크는 막혀 있었습니다. 그래서:

### ✅ 확인한 것 (코드를 직접 읽음)

- 어느 파일이 어느 주소를 부르는지, 몇 번 부르는지, 실패하면 어떻게 되는지(폴백 유무) — **전부 코드에서 읽음.**
- `FinanceDataReader` **0.9.202** (오너 컴퓨터에 설치된 버전) 소스를 읽어, 우리가 부르는 함수 네 가지가
  실제로 어느 주소로 가는지 확인함 (§2-B). ⚠️ GitHub Actions 러너에 깔리는 버전은 `requirements.txt` 가
  버전을 고정하지 않아 **다를 수 있습니다.**
- `google-genai` **2.22.0** (오너 컴퓨터) 소스에 `generativelanguage.googleapis.com` 이 있음. 러너 버전은 미확인.
- 2026-09-08 사고 로그 원문 (`TASK_HISTORY.md` #221·#224) — 인용은 그 문서에서 가져옴.
- 저장소의 `data/` 파일 메타데이터(읽기만): `kr_all_market_prices.json` 은 **2026-09-07 17:25 자에서 멈춰 있음**
  (오늘 구 페이지 0건 → 파일 미갱신), `indicator_kr_latest.json` 은 **2026-09-08 17:18 SUCCESS 500/500**
  (= FDR 의 네이버 차트 경로는 오늘 살아 있었음), `us_stocks_latest.json` 2026-09-08 08:49 KST SUCCESS.

### ❌ 확인 못 한 것 → 🔴 **오너가 브라우저로 대신 봐줘야 하는 목록 (우선순위 순)**

| # | 확인해야 할 것 | 왜 급한가 | 어디서 보나 |
|---|---|---|---|
| 1 | **`stock.naver.com` JSON API 의 이용 조건** — 공개 API 인지, 약관에 자동 수집 금지 조항이 있는지 | 지금 코스피 수집 **전체**가 이 하나에 걸려 있음. §0-3-2 는 약관 확인을 요구하는데 **미확인** | 네이버 증권 서비스 이용약관 / 개발자 안내 페이지 |
| 2 | **`finance.naver.com` 구 페이지 4종의 9/10 이후 운명** — `sise_market_sum`(전 종목 종가), `sise_index`(코스피), `marketindex/`(환율), `investorDealTrendDay`(수급), `api/sise/etfItemList.nhn`(ETF 목록) | 이 중 `sise_market_sum` 은 **이미 0건**. 나머지 4개는 매크로(동결)·마스터 ETF 부분이 매일 부르는데 9/10 에 같이 사라질 수 있음 | 브라우저로 각 주소 열어 표가 아직 있는지 |
| 3 | **`github.com/FinanceData/fdr_krx_data_cache`** — 저장소가 살아 있는지, `data/listing/krx/2026-09-08.csv` 같은 최신 날짜 파일이 **언제** 올라오는지(하루 지연인지, 아예 멈췄는지) | 오늘 404 의 원인. 마스터 파일·(구 경로) 상장주식수가 여기 의존 | 깃허브 저장소 페이지 커밋 이력 |
| 4 | **`github.com/Ate329/top-us-stock-tickers`** — 마지막 갱신일, 저장소 상태 | **개인 저장소 하나가 미국 모듈 전체의 단일 장애점.** 멈추면 미국 수집이 통째로 안 돎 | 깃허브 저장소 페이지 |
| 5 | **`stockanalysis.com` 이용약관** — `__data.json` 내부 엔드포인트 사용이 허용되는지, robots.txt | 미국 550종목 + 지수 + 전 종목 시세 전부. 비공식 내부 엔드포인트 사용 중 | stockanalysis.com 약관·robots.txt |
| 6 | **`navercomp.wisereport.co.kr` 운영 주체와 9/10 종료 대상 여부** | 코스피 EV/EBITDA·ROE·Forward ROE·목표주가의 유일한 출처 (`NAVER_MIGRATION_WORK_ORDER.md` 도 "불명"으로 남김) | 페이지 하단 저작권 표기 |
| 7 | **KRX OPEN API 실제 응답** — `utils/krx_openapi.py` 머리말이 "실서버 호출은 아직 한 번도 못 했다"고 적음. Actions 로그에서 VKOSPI 지수명·근월물 선택 로그 확인 | 매크로 위험지표 2종이 값이 나오는지 조차 미확인 | `Daily Market Scraper` Actions 로그 |
| 8 | Yahoo 차트 API(`query2.finance.yahoo.com`) 이용 조건 | 매크로가 FDR 뒤에서 매일 2회 부름. 비공식 | Yahoo 약관 |
| 9 | 대체재 후보의 **존재·조건** — §4 의 후보들은 **이름만** 적었고 하나도 확인 못 함 | 지금 죽어 있는 것(전 종목 종가)의 갈아탈 곳이 없음 | §4 |

---

## 1-B. ⚖️💰 대체재를 고를 때의 **1순위 기준 — 법적 조건과 비용** (2026-09-08 오너 지시)

> 오너: *"물론 법적인것이랑 비용이 안드는 방향도 무시하면 안되는거야."*

기술적으로 되는 출처를 찾는 건 쉬운 절반입니다. 후보로 올리기 전에 셋을 먼저 봅니다 —
**하나라도 확인 못 했으면 "후보"가 아니라 "확인 필요"** 입니다.

| 관문 | 무엇을 보나 |
|---|---|
| ⚖️ **법적** | 이용약관 · `robots.txt` · 데이터 재배포·상업적 이용 조건 · 라이선스 |
| 💰 **비용** | 무료 한도 · 유료 전환 조건 · 카드 등록 요구 여부 (**비용이 드는 것은 오너 결정 없이 후보로 올리지 않습니다**) |
| 📜 **공식성** | 공식 API 인가, 화면 뒤 내부 엔드포인트인가 (비공식이면 예고 없이 바뀝니다) |

선호 순서: **공식 무료 API → 공식 파일 배포 → 라이선스 명확한 오픈소스 → (그 외는 오너 판단)**

### ⛔ 오너 기준으로 **아웃 확정** — 다시 검토하지 않습니다 (§0-3-17)

> 오너 지시(2026-09-08): *"「비상업적 목적으로만 이용 가능」 이런 말이 있으면 안 하는 게 맞아.
> 이런 건 생각도 하지 말고 검토도 하지 마. 무슨무슨 조건이 달린 시점에서 아웃이야."*

**아래는 이미 약관을 읽고 아웃 판정한 것입니다. 대체재 후보로 다시 올리지 마세요.**

| 출처 | 아웃 사유 (약관 원문 근거) | 확인일 |
|---|---|---|
| **네이버 공식 API** (`developers.naver.com`) | ⛔ **7.3 ④** *"API의 결과화면과 함께 **광고를 노출하는 행위**"* 금지 · **7.3 ③** 취득 정보의 *"복제, **저장(캐시 행위 포함)**, 가공, 배포"* 금지 · **7.2 ③** 사용자에게서 *"**대가**(금전, 정보 제공 등 일체의 유·무형)"* 수취 금지 · **7.3 ⑥** *"제3자에게 다시 제공"* 금지 · **8.2** *"제한된 사용권의 부여만"* | 2026-09-08 (오너가 약관 전문 확인) |
| **KRX OPEN API** (`data-dbg.krx.co.kr`) | ⛔ **약관 제6조②** *"**비상업적 목적으로만** 이용 가능, 결과에 대한 대가를 제3자에게 청구 불가"* | 2026-08-10 기록 (`.claude/agents/macro.md`) |
| **한국투자증권 KIS Developers** | ⛔ **고객 약관 제5조③** *"시세(국내주식…)정보를 고객이 직접 개발한 프로그램 등 **개인의 업무에 한하여** 이용해야 하며, **제3자에게 제공해서는 아니 된다**"* · 포털 안내 *"시세정보는 계좌를 보유한 개인 고객이 **자기 자산의 투자 목적에 한해** 이용… **제3자 제공은 불가**"* · 제휴법인은 *"**코스콤 등 거래소와 별도 시세정보이용계약**을 반드시 체결"* · *"**핀테크사의 경우 제휴가 불가**"* | 2026-09-08 (오너가 약관 전문 확인) |
| **증권사 무료 API 일반** (키움 등) | 🔺 **추정 — 개별 확인 전에는 후보로 올리지 않음.** 증권사도 거래소에서 시세를 받아 쓰는 입장이라 **재배포 권리가 없습니다.** KIS 가 "너희가 직접 코스콤과 계약해라"라고 하는 이유가 그것이며, 다른 증권사도 같은 구조일 가능성이 높습니다 | 미확인 |

### 🔴 세 곳을 다 읽고 드러난 **구조** — 우연이 아닙니다

약관 세 개를 전문으로 확인한 결과, **전부 같은 곳에서 막힙니다: "제3자에게 보여주는 것".**

```
   거래소(KRX) ── 시세정보이용계약($) ──→ 증권사 · 포털 · 핀테크
                                              │
                                              └─→ 화면에 표출
```

**시세정보의 원소유자는 거래소입니다.** 증권사조차 자기가 받은 시세를 재배포할 권리가 없어서
*"너희가 직접 코스콤 등과 시세정보이용계약을 맺어라"* 라고 합니다(KIS 포털 안내 원문).

→ 즉 **"조건 없이 무료로 남에게 시세를 보여주는" 경로는 구조적으로 존재하지 않습니다.**
특정 회사가 인색한 것이 아니라 시장 데이터 산업의 기본 구조입니다. 상업적으로 하는 곳들은
전부 이 계약을 맺고 있습니다.

⚠️ **다음 세션에게** — 이 구조를 모르고 "무료 증권사 API 를 쓰면 되지 않나"를 다시 제안하지
마세요. 세 곳을 이미 읽었고 전부 같은 이유로 아웃입니다. 새 후보를 볼 때도 **가장 먼저 볼 것은
"제3자 제공·표출이 되는가"** 입니다. 거기서 걸리면 나머지는 볼 필요가 없습니다(§0-3-17).

### 🔵 아직 답이 안 나온 것 — 확인 가치가 있는 두 가지 (추측 금지, 문의 필요)

1. **종가(EOD)와 실시간 시세의 조건이 같은가.** 이 시스템은 **실시간 시세를 쓰지 않습니다** —
   장 마감 종가를 하루 한 번 받습니다. 시장 데이터는 보통 **실시간 / 지연 / 종가**를 다르게
   취급하는데, **국내 종가 데이터의 조건이 다른지 확인하지 못했습니다.**
   → 코스콤·KRX 에 직접 문의하는 것이 가장 확실합니다.
2. **시세(가격)와 공시(재무제표)는 출처도 성격도 다릅니다.** 이 서비스의 재료 중 EPS·ROE·
   배당·재무제표는 **공시**에서 나오고, 우리는 이미 **DART(`opendart.fss.or.kr`, 금융감독원)** 를
   쓰고 있습니다. 법적으로 막히는 것은 **가격** 쪽입니다.
   🔴 **DART 의 이용 조건도 아직 확인하지 못했습니다** — 공공기관이라고 조건이 없다고 단정하지
   마세요(§0-1). 확인 목록(§1)에 있습니다.

📌 **네이버 공식 API 는 조건 이전에 애초에 해당 서비스가 없습니다** — 제공 목록은 검색·로그인·
CLOVA·Papago·데이터랩 등이며 **증권·주식 시세 API 자체가 없습니다**(2026-09-08 약관 §4 및
제공 목록 확인). "공식 창구로 갈아탄다"는 선택지가 존재하지 않습니다.

🔴 **그래서 지금 `stock.naver.com` 은 어떤 상태인가** — 위 약관의 **적용 대상이 아닙니다.**
클라이언트 아이디를 발급받은 적이 없기 때문입니다. 그건 "괜찮다"가 아니라 **"허락도 금지도
명시적으로 받지 않은 상태"** 이고, 구 HTML 크롤링 때와 법적 지위가 **같습니다** — 형식이
HTML 에서 JSON 으로 바뀌었을 뿐 나아지지도 나빠지지도 않았습니다. §0-1 대로 사실만 적습니다.

---

### 🔴 지금 이미 이 관문을 안 거치고 쓰는 것들

**이미 쓰고 있다고 해서 확인이 면제되지 않습니다**(§0-3-12). 아래는 뒤늦게라도 확인해야 합니다:

| 출처 | 상태 | 왜 문제가 될 수 있나 |
|---|---|---|
| **`stock.naver.com` 신 JSON API** | ⚖️ **약관 미확인** | 🔴 2026-09-08 에 **실전 수집이 이 위로 옮겨졌습니다.** 지금 코스피 화면 전체가 여기 얹혀 있는데 이용 조건을 못 봤습니다 |
| **`stockanalysis.com` `__data.json`** | 📜 **비공식 내부 엔드포인트** · ⚖️ 약관 미확인 | 화면 뒤 주소라 예고 없이 바뀝니다. 미국 모듈 전체가 여기 걸려 있습니다 |
| **`navercomp.wisereport.co.kr`** | ❔ 운영 주체 미확인 · ⚖️ 약관 미확인 | EV/EBITDA·ROE·목표주가 |
| **`fchart.stock.naver.com`** | 📜 비공식(FDR 뒤) · ⚖️ 미확인 | 보조지표 500종목/일 |
| **`FinanceData/fdr_krx_data_cache`** | 📜 개인·소규모 오픈소스 | 마스터 파일. 라이선스·갱신 의무 미확인 |
| **`Ate329/top-us-stock-tickers`** | 📜 개인 저장소 | 미국 유니버스 첫 단계. 라이선스 미확인 |

💰 **비용 쪽은 지금까지는 전부 무료 경로입니다** — 유료 데이터 벤더를 쓰는 곳은 없습니다.
Gemini·Supabase 는 무료 한도 안에서 쓰고 있고(§5), **새 출처를 고를 때도 무료를 기본으로 봅니다.**
유료가 유일한 답인 상황이 오면, 대안 없음을 먼저 문서로 보이고 **오너에게 묻습니다.**

---

## 2. 재고 — 밖으로 나가는 요청 전부

범례 — **관리 주체**: 🏛️ 공식 기관 · 🏢 회사 · 👤 개인·소규모 오픈소스 · ❔ 정체불명/미확인.
**폴백**: "없음" = 죽으면 그 산출물이 멈춤(대개 기존 파일 유지). 요청 수는 **코드에서 읽은 하루 기준**.

### 2-A. 코드에 주소가 문자열로 적혀 있는 것

| 출처 | 무엇을 가져오나 | 어느 파일이 부르나 | 누가 이걸 읽나 (하위 영향) | 폴백 있나 | 종료·위험 신호 | 관리 주체 |
|---|---|---|---|---|---|---|
| `stock.naver.com` `/api/domestic/market/stock/default` · `/api/domestic/detail/{code}/detail` (네이버 신 증권 JSON) | 코스피·코스닥 시총 목록(33페이지×20행), 종목 상세(현재가·PER·PBR·배당·상장주식수) | `utils/naver_stock_api.py`(주소 상수 한 곳) ← `collector_kospi200.py` (`_fetch_market_list_new_api`, `fetch_naver_item_new_api`), `run_naver_api_shadow.py`(수동만, #223) | `data/kospi200_pegy_latest.json` → `/kr`(`pegy_page`), `run_duel_daily_batch.py`, `run_scorecard_publish_batch.py`(KR), `utils/report_db.py`, `utils/data_sanity.py`, `kospi200_stock_history.csv` | **실질 없음.** 스위치 `NAVER_SOURCE` 로 구 출처로 되돌릴 수 있지만 **구 출처는 이미 0건** | 문서화되지 않은 내부 JSON API. **약관 미확인.** `NXT` 주소는 코드가 차단(§0-3-2) | 🏢 네이버 |
| `navercomp.wisereport.co.kr` `/v2/company/c1010001.aspx` | EV/EBITDA·ROE·Forward ROE·순이익·자본총계·목표주가 | `collector_kospi200.py::_fetch_wisereport_page` (파서 `utils/wisereport_parser.py`), `run_naver_api_shadow.py` | 코스피 스냅샷의 위 지표 → `/kr` 점수(ROE 프리미엄·EV/EBITDA) | **없음** — 그 종목만 None(서킷 브레이커로 연속 실패 시 남은 종목 건너뜀) | 9/10 네이버 개편의 **종료 대상인지 불명**(`NAVER_MIGRATION_WORK_ORDER.md`) | ❔ 운영사 미확인 (네이버가 연결해 쓰는 외부 기업정보 서비스) |
| `finance.naver.com` `/sise/sise_market_sum.naver` (구 순위 페이지) | **전 종목(ETF 포함) 종가** — 코스피·코스닥 전체 페이지네이션 | `collector_kospi200.py::run_kr_all_market_prices_collector` (🔴 **아직 구 출처 — 신 API 로 안 옮김**, #223 "남은 정리") | `data/kr_all_market_prices.json` → `utils/indicator_universe.py`(보조지표 500종목 유니버스), `web/pages/pegy_page.py`, `dividend_page.py`, `duel_page.py`, `utils/scorecard_db.py`(유니버스 밖 종목 시세), `utils/report_db.py`, `run_duel_daily_batch.py`, `data_sanity.py` | **없음** — 둘 다 실패면 파일 미생성(기존 파일 유지) | 🔴 **2026-09-08 16:11 실행에서 코스피·코스닥 0건**(같은 페이지·같은 표를 쓰는 `fetch_kospi200_real_market_data` 로그, #222). 파일이 09-07 자에서 멈춰 있음(17:40 실행은 앞 단계에서 중단돼 여기까지 못 왔고, 왔어도 0건이면 갱신 안 됨). 9/10 종료 예고 | 🏢 네이버 |
| `finance.naver.com` `/sise/sise_market_sum.naver` · `/item/main.naver` (구 경로) | 코스피200 후보 목록·종목 상세(구 파서) | `collector_kospi200.py` (`fetch_kospi200_real_market_data`, `fetch_naver_item_dps_and_eps`) — `NAVER_SOURCE` 가 구 출처일 때만 | (스위치가 신 출처라 현재 **호출 안 됨**) | — | 위와 같음(0건) | 🏢 네이버 |
| `finance.naver.com` `/sise/sise_index.naver?code=KOSPI` | 코스피 지수 당일값 | `scrape_daily.py` (매크로 🛑 동결) | `market_history.csv` → `/admin/macro` | FDR `^KS11`(→ Yahoo, §2-B) 값이 먼저 있고 네이버 값이 덮어씀 — 네이버가 죽으면 Yahoo 값(전일 기준일)으로 남음 | 9/10 종료 예고. **§0-3-2 목록에 없었음** | 🏢 네이버 |
| `finance.naver.com` `/marketindex/` | USD/KRW 환율 | `scrape_daily.py` | `market_history.csv` → `/admin/macro` | FDR `USDKRW=X`(→ Yahoo) 값 선행, 위와 같음 | 9/10 종료 예고. **§0-3-2 목록에 없었음** | 🏢 네이버 |
| `finance.naver.com` `/sise/investorDealTrendDay.naver` | 투자자별 매매동향(개인·외국인·기관 순매수) | `scrape_daily.py`(최대 5페이지), `utils/db.py::repair_missing_supply_data`(수급 0 고착 행이 있을 때만, 최대 5페이지 — 웹 런타임 `save_and_load_history` 경유) | `market_history.csv` 수급 3열 → `/admin/macro` 수급 지표 | **없음** — 수급 지표 차단(재정규화) | 9/10 종료 예고. **§0-3-2 목록에 없었음** | 🏢 네이버 |
| `opendart.fss.or.kr` `/api/alotMatter.json` · `/api/list.json` · `/api/document.xml` · `/api/corpCode.xml` (DART OPEN API, 인증키) | 배당에 관한 사항(정기보고서), 공시 목록, 공시 원문, 고유번호표 | `collector_dividend_kr.py`, `collector_dividend_payment_kr.py`, `corp_code_mapper.py` | `data/dividend_kr_*` → `/dividend`, 배당 알람(`utils/expiry_alarms.py`) | **없음** — 갱신 정지(파일은 append-only 라 기존 유지) | 하루 20,000건 한도(`status 020`). 키·IP·점검 상태코드는 즉시 중단 | 🏛️ 금융감독원 |
| `data-dbg.krx.co.kr` `/svc/apis/...` (KRX OPEN API, 인증키) | VKOSPI·코스피200 선물(베이시스) | `utils/krx_openapi.py` ← `scrape_daily.py` | `market_history.csv` 위험지표 2종 → `/admin/macro` | **없음** — 그 지표만 None(재정규화) | 하루 10,000회 한도. 🔴 **실서버 응답을 아직 한 번도 못 봤다**고 파일 머리말에 적혀 있음 | 🏛️ 한국거래소 |
| `stockanalysis.com` `/stocks/{ticker}/statistics/` | 미국 종목 펀더멘털(550종목) | `collector_us_stocks.py` (`utils/constants_us.py` 주소 상수) | `data/us_stocks_latest.json` → `/us`, `run_duel_daily_batch_us.py`, `run_scorecard_publish_batch.py`(USD), `report_db` | **없음** — 차단(403/429) 시 즉시 중단·기존 스냅샷 유지 | 비공식(HTML 파싱). **약관 미확인** | 🏢 Stock Analysis (데이터 원천은 S&P Global 로 표기) |
| `stockanalysis.com` `/stocks/screener/__data.json` · `/etf/screener/__data.json` | 미국 전 종목·ETF 시세 목록 | `collector_us_stocks.py` (`run_us_all_market_prices_collector`, `..._etf_...`) | `data/us_all_market_prices.json`, `us_all_etf_prices.json` → 성적표·결투 유니버스 밖 종목 | **없음** — 파일 미갱신 | `__data.json` 은 사이트 내부(SvelteKit) 엔드포인트 — 예고 없이 바뀔 수 있음 | 🏢 Stock Analysis |
| `stockanalysis.com` `/etf/{symbol}/` · `/etf/{symbol}/history/__data.json` | 미국 지수 현재값 3종(SPY·ONEQ·DIA ETF 프록시)·일별 이력 2종(SPY·ONEQ) | `collector_us_stocks.py::fetch_index_quotes`, `collector_us_indices.py` | `data/us_index_history.json` → 결투 USD 벤치마크, 보고서 미국 벤치마크 | **없음** | 위와 같음 | 🏢 Stock Analysis |
| `raw.githubusercontent.com` `/Ate329/top-us-stock-tickers/main/tickers/all.csv` | **미국 종목 유니버스 CSV**(시총 순 전체) | `collector_us_stocks.py::fetch_universe_rows` (`utils/constants_us.py::US_UNIVERSE_CSV_URL`) | **미국 수집 전체의 첫 단계** — 없으면 `run_us_collector` 가 예외로 중단 | **없음** | 🔴 **개인 깃허브 저장소.** 자동 갱신이 멈추면 `US_UNIVERSE_MIN_RAW_ROWS`(700행) 가드가 "깨짐"으로 보고 중단. **§0-3-2 목록에 없었음** | 👤 개인 (GitHub 사용자 Ate329) |
| `raw.githubusercontent.com` `/moonbear135/visible-hand-dashboard/main/...` (환경변수 `DATA_SOURCE_BASE_URL`) | 우리 저장소의 `data/*.json`·`market_history.csv` — **웹앱이 런타임에** 읽음 | `utils/data_source.py` (ETag·TTL 600초·백오프 60초) | 모든 화면 | **있음** — 배포에 실린 로컬 사본 | GitHub 장애 시 화면이 배포 시점 사본으로 후퇴(표시됨) | 🏢 GitHub + 우리 저장소 |
| `www.googleapis.com` (Google Drive API) | `market_history.csv` 백업 업로드 | `utils/gdrive_helper.py` ← `scrape_daily.py` | (백업뿐) | 실패해도 무시 | ⚠️ 필요한 패키지(`google-api-python-client` 등)가 `requirements.txt` 에 없어 **Actions 에서는 사실상 항상 건너뜀** | 🏢 Google |
| `api.github.com` (GitHub REST) | 워크플로우 실행 이력 조회·`workflow_dispatch` 발동 | `.github/workflows/watch_schedule_health.yml`(`gh api`), `cloudflare_worker.js`(평일 2회) | 워치독·예약 보조 | — | GitHub 예약 트리거 지연이 2026-08-27 부터 반복돼 Worker 를 둠 | 🏢 GitHub |
| `visiblehand.co.kr` `/healthz` (우리 배포처 Render) | 핑 | `.github/workflows/render_keep_awake.yml` — **10분 간격, 하루 144회** | — | — | Render Starter 전환으로 **불필요** (§0-3-2 에 "정리 대상"으로 이미 적혀 있음) | 🏢 Render + 우리 |

### 2-B. 🔴 라이브러리 뒤에 숨어 있는 것 — 코드에 주소 문자열이 **없습니다**

`grep` 으로 URL 을 찾으면 **이 표는 통째로 놓칩니다.** 오늘 FDR 이 그랬습니다.
아래 주소는 오너 컴퓨터에 설치된 **FinanceDataReader 0.9.202** 소스에서 읽은 것입니다(러너 버전은 미확인).

| 우리가 부르는 것 | 실제로 가는 곳 (라이브러리 소스에서 확인) | 어느 파일이 부르나 | 누가 이걸 읽나 | 폴백 | 위험 신호 | 관리 주체 |
|---|---|---|---|---|---|---|
| `fdr.StockListing('KRX')` | ① `data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd` (최신 영업일 `max_work_dt` 조회) → ② `raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx/{날짜}.csv` | `collector_kospi200.py::run_kr_ticker_master_collector`(1회/일), `_load_outstanding_shares_lookup`(신 경로: 상장주식수 없는 후보가 있을 때만 → 보통 **0회**, #224; 구 경로: 1회) | `data/kr_ticker_master.json` → 🔴 **신 경로의 종목 선별 자체**(`type=STOCK`, 시장 판정 — 마스터가 없으면 후보 0 → 수집 중단), ETF 판정, 우선주 부모 검증, `pegy_page` 배너 | 문지기(#221): 실패 시 **파일 안 씀, 어제 파일 유지** | 🔴 **2026-09-08 404.** 코드상 가장 그럴듯한 설명은 "②캐시 CSV 가 그 날짜에 아직 없음"(타이밍) — **추정.** 한국거래소가 아니라 **FinanceData 의 깃허브 캐시**에 의존. **§0-3-2 목록에 없었음** | 👤 FinanceData (오픈소스 프로젝트. 캐시 저장소를 누가 어떤 주기로 갱신하는지 **미확인**) |
| `fdr.StockListing('ETF/KR')` | `finance.naver.com/api/sise/etfItemList.nhn` | `collector_kospi200.py::run_kr_ticker_master_collector`(1회/일) | 마스터의 ETF 부분(위와 같음) | 문지기(파일 유지) | **9/10 종료 대상 구 도메인**(`.nhn`). 그때부터 마스터가 매일 "갱신 못 함" 상태가 될 수 있음 | 🏢 네이버 (FDR 이 중계) |
| `fdr.DataReader('005930', 시작, 끝)` (6자리 종목코드) | `fchart.stock.naver.com/sise.nhn?timeframe=day&count=6000&symbol=...` | `collector_indicator_kr.py`(**500회/일**, 0.5초 간격), `collector_kospi200.py::fetch_recent_volatility`(**520회/일**, 변동성 벌점용), `probe_indicator_universe_timing.py`(수동) | `data/indicator_kr_latest.json` → `/indicator`; 코스피 스냅샷의 변동성 벌점·`vol` 라벨 | **없음** — 그 종목만 실패/None | 네이버 차트 서버. 9/10 개편 영향 **불명.** 라이브러리가 User-Agent 없이 보냄(우리가 바깥에서 딜레이만 둠). **§0-3-2 목록에 없었음** | 🏢 네이버 (FDR 이 중계) |
| `fdr.DataReader('^KS11')` · `fdr.DataReader('USDKRW=X')` | `query2.finance.yahoo.com/v8/finance/chart/...` (기호에 `^`·`=X` 가 있어 FDR 의 KRX 지수 캐시가 아니라 **Yahoo** 경로로 감 — 소스 `data.py` 분기 확인) | `scrape_daily.py` (2회/일) | `market_history.csv` 코스피·환율의 1차값(네이버 값이 덮어씀) | 네이버 당일값이 있으면 덮어씀 | 비공식 차트 API. **약관 미확인. §0-3-2 목록에 없었음** | 🏢 Yahoo (FDR 이 중계) |
| `yf.Ticker(...).info` (yfinance) | Yahoo (라이브러리 내부) | `collector_kospi200.py` PER 교차검증(상위 N) | `per_discrepancy` | — | ⚠️ `yfinance` 가 `requirements.txt` 에 없어 **Actions 에서 `HAS_YFINANCE=False` → 죽은 코드.** 검증이 "안 된 것"이지 "이상 없음"이 아님 | 🏢 Yahoo |
| `genai.Client(api_key).models.generate_content(...)` (google-genai) | `generativelanguage.googleapis.com` (SDK 2.22.0 소스) | `utils/macro_ai.py`(지표 8개 × 1회/일, 성공 2초·실패 5초 간격), `utils/indicator_ai.py`(사용자가 카드 열 때 온디맨드, 종목+날짜 캐시, **최대 500회/일**), `utils/scorecard_ocr.py`(사용자당 15회/일) | 매크로 코멘트, 보조지표 코멘트, 성적표 OCR 프리필 | §0-3-11 로 함수 경계 뒤에 두어 **교체 가능하게는** 돼 있으나 **다른 provider 는 미구현** | 유료. 모델명(`gemini-3.6-flash`, `gemini-3.5-flash-lite`) 단종 시 실패 | 🏢 Google |
| `supabase.create_client(url, key)` | `SUPABASE_URL` 시크릿의 호스트 (코드에 없음) | `utils/scorecard_db.py`, `duel_db.py`, `report_db.py`; 배치 `run_duel_daily_batch*.py`, `run_scorecard_publish_batch.py`; 웹 런타임 Auth | 성적표·결투·보고서 **전부** + 로그인 | **없음** — 그 세 모듈 정지("준비중" 안내) | 우리가 결제하는 인프라 | 🏢 Supabase |
| Discord 웹훅 (`DISCORD_WEBHOOK_URL` 시크릿) | 시크릿 값의 호스트 (코드에 없음) | `watch_schedule_health.yml`, `watch_data_sanity.yml`, `test_suite.yml`, `naver_api_shadow.yml` | 알림 | 실패 무시 | — | 🏢 Discord |
| `pip install -r requirements.txt` | PyPI (`pypi.org`, `files.pythonhosted.org`) | **모든 워크플로우 매 실행** + Docker 빌드 | 실행 자체 | 없음 | 패키지 12개 중 **버전 고정 없는 것이 대부분** — 어느 날 새 버전이 깨질 수 있음(`pandas<3` 만 상한) | 🏢 PSF |
| GitHub Actions 예약 트리거·`actions/checkout` 등 | GitHub | 전 워크플로우 | 전부 | Cloudflare Worker 가 발동만 보조 | 2026-08-27 부터 예약 지연 반복(GitHub 인정) | 🏢 GitHub |

### 2-C. 요청은 아니고 **링크·브라우저 쪽**인 것 (테스트가 "주소"로 잡으므로 여기 분류)

| 호스트 | 정체 | 어디에 |
|---|---|---|
| `pagead2.googlesyndication.com` | AdSense 스크립트 — **사용자 브라우저**가 부름(서버 아님) | `web/ads.py` |
| `policies.google.com` · `adssettings.google.com` | 개인정보 페이지의 안내 링크 | `web/pages/privacy_page.py` |
| `dart.fss.or.kr` `/dsaf001/main.do?rcpNo=` | 공시 원문 열람 링크(화면에 표시만) | `collector_dividend_kr.py`, `corp_code_mapper.py` |
| `github.com` | User-Agent 문자열 속 연락처, 안내 링크, 데이터 폴더 링크 | `collector_kospi200.py`, `run_naver_api_shadow.py`, `web/pages/dividend_page.py`, 워크플로우 알림 문구 |

### 2-D. 코드에 이름만 있고 **안 쓰는** 것 (혼동 방지)

- `pykrx` — 주석·화면 안내문에만 등장. **쓰지 않기로 한 결정**(`data.krx.co.kr` 로그인 우회라 §0-3-2 위반, `utils/constants.py`).
- `fred.stlouisfed.org` — `collector_us_indices.py` 머리말에 "이렇게 할 수도 있다"로만 언급. 호출 없음.
- `openapi.krx.co.kr` — KRX OPEN API **안내 포털** 주소(문서 참조). 실제 호출은 `data-dbg.krx.co.kr`.
- `pykrx-openapi` 패키지 — 검토 후 **채택 안 함**(`utils/krx_openapi.py` 머리말).

---

## 3. 🔴 폴백이 없는 단일 장애점 — 죽으면 무엇이 멈추는가

| 순위 | 단일 장애점 | 죽으면 멈추는 것 | 지금 상태 |
|---|---|---|---|
| 1 | **`stock.naver.com` 신 JSON API** | 코스피 스냅샷 전체 → `/kr`, 결투 KR, 성적표 KR 발행, 보고서 KR, 신선도 감시 기준값 | 살아 있음(2026-09-08 17:40 659종목 성공). **약관 미확인.** 되돌릴 구 출처는 죽음 |
| 2 | **`finance.naver.com/sise/sise_market_sum.naver` (전 종목 종가)** | `kr_all_market_prices.json` → 보조지표 유니버스, 성적표·결투·보고서의 유니버스 밖 종목 시세, 배당 화면 시세 | 🔴 **이미 죽은 것으로 판단**(16:11 실행 0건, 파일 09-07 자에서 정지). 신 API 로 옮기는 작업이 필요 — 후보 주소는 이미 있음(`utils/naver_stock_api.py` 목록 API 가 시장 전체를 페이지네이션함, 미확인) |
| 3 | **FinanceData 깃허브 캐시**(`StockListing('KRX')`) | 마스터 파일 갱신 → 신규 상장·폐지 반영. 마스터가 **아예 없으면** 신 경로 후보 0 → 코스피 수집 중단 | 🔴 오늘 404. 문지기 덕에 어제 파일로 버팀. **매일 실패하면 매일 경고만** |
| 4 | **`raw.githubusercontent.com/Ate329/...` 미국 유니버스 CSV** | 미국 수집 **첫 단계** → 미국 모듈 전체(`/us`, 결투 USD, 성적표 USD, 보고서 US) | 살아 있음(09-08 4,230행). 개인 저장소 |
| 5 | **`stockanalysis.com`** | 미국 펀더멘털·지수·전 종목 시세 → 위와 같음 | 살아 있음. 비공식 내부 엔드포인트 |
| 6 | **`fchart.stock.naver.com` (FDR 차트)** | 보조지표 500종목 전부, 코스피 변동성 벌점 | 살아 있음(09-08 500/500). 9/10 영향 불명 |
| 7 | **`navercomp.wisereport.co.kr`** | EV/EBITDA·ROE·Forward ROE·목표주가 → `/kr` 점수 일부 | 살아 있음. 운영사·종료 여부 불명 |
| 8 | **DART OPEN API** | 배당 KR 갱신 | 공식 기관. 한도 있음 |
| 9 | **Supabase** | 성적표·결투·보고서·로그인 | 유료 인프라 |
| 10 | **Gemini** | 코멘트·OCR (핵심 수치엔 영향 없음) | 교체 구조는 있으나 대체 provider 미구현 |

---

## 4. 🔴 개인·소규모 오픈소스에 기대고 있는 곳 — "내일 사라져도 이상하지 않은가?"

| 의존 | 성격 | 우리에게 무엇인가 | 갈아탈 후보 (🔴 **전부 미확인 — 이름만. 존재·조건·약관 확인 필요**) |
|---|---|---|---|
| **FinanceDataReader** (`finance-datareader` 패키지) + **`FinanceData/fdr_krx_data_cache`** 캐시 저장소 | 오픈소스 프로젝트. 라이브러리 자체보다 **캐시 CSV 를 누군가 매일 올려줘야** `StockListing('KRX')` 가 돕니다. 그 "누군가"의 주기·의무는 미확인 | 마스터 파일(종목 유형·시장), 구 경로 상장주식수, 보조지표 시계열(네이버 중계), 매크로 코스피·환율(Yahoo 중계) | · 상장종목 목록: **KRX 정보데이터시스템 공식 다운로드**(로그인 요구 여부 미확인) / ~~KRX OPEN API~~ ⛔ **아웃**(약관 제6조② 비상업적 목적 한정 — §0-3-17) / **DART `corpCode.xml`**(이미 사용 중 — 상장 여부·시장 구분 필드가 있는지 미확인) / 신 네이버 목록 API 의 `listedStockCnt`(상장주식수는 **이미 이걸로 전환**, #224) · 일별 시세: 신 네이버 API 에 차트 엔드포인트가 있는지 **미확인** |
| **`Ate329/top-us-stock-tickers`** | 개인 깃허브 저장소(NASDAQ 스크리너 기반 자동 갱신으로 표기, `utils/constants_us.py`) | 미국 유니버스 전체 | · **`stockanalysis.com/stocks/screener/__data.json`** — 🟢 **이미 우리가 매일 부르고 있고**(전 종목 시세) 시총 컬럼이 있음. 같은 사이트 의존이 더 커지는 대가 · NASDAQ 공식 스크리너 API(약관 미확인) · SEC 공식 `company_tickers.json`(시총 없음 — 순위 매길 수 없음, 미확인) |
| **`yfinance`** | 오픈소스(비공식 Yahoo 래퍼) | 현재 **죽은 코드**(패키지 미설치) | 지우거나, 쓰려면 `requirements.txt` 에 넣고 §0-3-2 목록에 올리는 결정이 먼저 |

📌 판단 기준(에이전트 규칙으로도 둠): **개인 저장소 하나가 모듈 전체의 첫 단계**인 구조는 그 자체로 §0-3-12 위반 상태입니다. 대체재를 확인하기 전에는 "있다"고 적지 않습니다.

---

## 5. 🟡 하루 요청량 (코드에서 읽은 값 — §0-3-2 감량 판단 근거)

| 출처 | 하루 요청(평일 기준) | 근거 |
|---|---|---|
| `stock.naver.com` | 목록 33 + 상세 520 ≈ **553** | 33페이지×20행(#224 산술), 추적 520종목 |
| `navercomp.wisereport.co.kr` | **520** | 종목당 1회 |
| `fchart.stock.naver.com` (FDR) | **≈1,020** (보조지표 500 + 변동성 520) | `--limit 500`, 추적 520 |
| `finance.naver.com` 구 순위(전 종목 종가) | 정상일 때 ≈ **90** 페이지(4,304건 ÷ 50행 + 종료 판정 2) — 0건이 계속되면 **2**(시장마다 1페이지에서 끝) | 4,304건/50행 |
| `finance.naver.com` 매크로 3종 | **3~7** (지수 1 + 환율 1 + 수급 1~5) | `scrape_daily.py` |
| `finance.naver.com/api/sise/etfItemList.nhn` (FDR) | **1** | 마스터 ETF |
| `data.krx.co.kr` + FinanceData 캐시 (FDR) | **2** (신 경로 상장주식수는 0회) | 마스터 |
| `query2.finance.yahoo.com` (FDR) | **2** | 매크로 |
| `data-dbg.krx.co.kr` | **≤10** | `utils/krx_openapi.py` |
| `opendart.fss.or.kr` | 매일: 공시목록 2~3페이지 + 원문 건수(수십) · 연 8회 대량: ≤15,000 | `DEFAULT_MAX_REQUESTS`, 페이지네이션 실측 |
| `stockanalysis.com` | **≈559** (통계 550 + 스크리너 2 + ETF 스크리너 2 + 지수 3 + 지수 이력 2) | 스냅샷 metadata `pages_fetched: 2` |
| `raw.githubusercontent.com/Ate329` | **1** | |
| `raw.githubusercontent.com/moonbear135` (웹 런타임) | 파일 종류 × 최대 6회/시간(TTL 600초) — 사용자 수와 무관 | `utils/data_source.py` |
| `generativelanguage.googleapis.com` | 매크로 8 + 보조지표 ≤500(온디맨드) + OCR 사용자당 ≤15 | |
| `visiblehand.co.kr/healthz` | **144** — 불필요 | 10분 간격 |
| `api.github.com` | 워치독 워크플로우 수 + Worker 2 | |
| PyPI | 워크플로우 실행 수 × 12패키지 | |

**합계(네이버 계열 하루 ≈ 2,100 요청)** — 신 API 553 + 위즈리포트 520 + 차트 1,020 + 구 페이지 ~10.
🔻 여기서 **`fetch_recent_volatility` 520회**는 보조지표 수집기가 같은 날 같은 종목의 같은 시계열을
이미 받아오는 것과 **중복**입니다(§0-3-10·§0-3-2) — 합치면 하루 약 500회를 줄일 수 있습니다. 오너 판단 사항.

---

## 6. 매일 건강검진 워크플로우 — 설계만 (🔴 켜지 않았습니다, §0-3-6 오너 승인 사항)

### 6-1. 🔴 먼저 정직하게 — "살아 있음"과 "우리가 쓸 수 있음"은 다릅니다

오늘 네이버 구 순위 페이지는 **HTTP 200** 이면서 우리한테는 **0건**이었습니다. `HEAD` 나 상태코드만 보는
검진은 **오늘 사고를 못 잡습니다.** 잡으려면 검진이 다음 중 하나를 해야 합니다:

- **파서까지 태워서 "행 수 ≥ 최소치"** 를 봐야 합니다(= 실제 수집기의 첫 페이지 1회를 그대로 돌리는 것).
  이건 이미 `utils/data_sanity.py` + `watch_data_sanity.yml` 이 **수집 완료 이벤트 뒤에** 하는 일과 같습니다.
  즉 "출처가 쓸 수 있는가"의 진짜 검진은 **수집기 자신의 결과**이고, 별도 워크플로우는 그 앞에서
  **"아예 접속이 안 되는가"** 만 미리 알려줄 수 있습니다.
- 라이브러리 뒤 주소(FDR)는 `HEAD` 로 의미가 없습니다 — 캐시 CSV 는 **날짜별 파일**이라 "오늘 파일이
  있는가"를 봐야 하고, 그건 그 함수를 한 번 부르는 것과 같습니다.

그래서 이 설계는 두 층입니다: **(a) 가벼운 접속 확인**(아래 표) + **(b) 기존 수집 결과 감시**(`data_sanity`).
(a)만으로 안심하면 안 된다는 것을 워크플로우 이름과 요약에 박아 둡니다.

### 6-2. 설계 — 워크플로우 이름 `watch_data_sources.yml` (**파일 미생성**)

- 트리거: `workflow_dispatch` + cron **하루 1회, 06:30 KST**(모든 수집기보다 앞. 장중 아님 — 읽기만 하므로 무관).
- 실행 내용: 아래 표의 요청을 **순차·2~3초 간격**으로 보내고, 결과를 Actions 요약 + (실패 시) Discord 로.
- 실패해도 **아무것도 고치지 않습니다**(워치독 원칙 — `automation-ops` 규칙 8). 재시도 0회.
- 판정: 상태코드 + **응답에서 우리가 실제로 읽는 표식 1개**(예: JSON 키 `stocks`, HTML `table.type_2`) 존재 여부.
  표식이 없으면 "**살아 있지만 못 씀**"으로 따로 표시 — 오늘 사고 모양을 이름 붙여 둡니다.

| 출처 | 보낼 요청 (1회) | 방법 | 판정 표식 | 추가 요청/일 |
|---|---|---|---|---|
| `stock.naver.com` | 목록 1페이지(`page=1&pageSize=20`) | GET (HEAD 는 JSON 존재를 못 봄) | `stocks` 배열 길이 ≥ 1 · `marketStatus` 키 | 1 |
| `navercomp.wisereport.co.kr` | 삼성전자 1건 `c1010001.aspx?cmp_cd=005930` | GET | 파서(`utils/wisereport_parser.py`)가 ROE 표를 찾는가 | 1 |
| `finance.naver.com` 구 순위 | `sise_market_sum.naver?sosok=0&page=1` | GET | `table.type_2` 행 ≥ 1 (🔴 지금은 이게 실패해야 정상) | 1 |
| `finance.naver.com` 매크로 3종 | 지수·환율·수급 각 1페이지 | GET | `#now_value` / `.value` / `table.type_1` | 3 |
| FDR `StockListing('KRX')` | 함수 1회 호출 | 라이브러리 | 행 ≥ 2,000 · 오늘/전 영업일 날짜 | 2 (KRX 1 + 캐시 1) |
| FDR `StockListing('ETF/KR')` | 함수 1회 | 라이브러리 | 행 ≥ 500 | 1 |
| FDR `DataReader('005930')` | 최근 10일 | 라이브러리 | 행 ≥ 1 | 1 |
| FDR `DataReader('^KS11')` | 최근 10일 | 라이브러리(Yahoo) | 행 ≥ 1 | 1 |
| `opendart.fss.or.kr` | `list.json` 오늘 1페이지(`page_count=1`) | GET(인증키) | `status == "000"` 또는 `013`(공시 없음) | 1 |
| `data-dbg.krx.co.kr` | 파생지수 1일치 | GET(인증키) | `OutBlock_1` 존재 | 1 |
| `stockanalysis.com` | 스크리너 `__data.json` 1페이지 | GET | 파서가 행 ≥ 1 | 1 |
| `raw.githubusercontent.com/Ate329/...` | `HEAD` | HEAD | 200 + `Last-Modified` 가 7일 이내 | 1 |
| `raw.githubusercontent.com/moonbear135/...` | `HEAD` `kospi200_pegy_latest.json` | HEAD | 200 | 1 |
| Supabase | `create_client` + 가장 가벼운 조회 1회(테이블 1행) | SDK | 예외 없음 | 1 |
| Gemini | **보내지 않음** — 유료. 실제 사용 실패가 곧 검진 | — | — | 0 |
| **총합** | | | | **≈18 요청/일** |

### 6-3. 이 설계가 못 잡는 것 (정직하게)

- 값의 **내용**이 낡았는데 형식은 멀쩡한 경우(어제 값을 오늘도 주는 경우) — 그건 `utils/data_freshness.py` 몫(§0-3-16).
- 검진 시각(06:30)엔 살아 있다가 수집 시각(16:05)에 죽는 경우.
- 약관·정책 변경(기술적으로는 계속 응답함).
- 라이브러리 새 버전이 다른 주소로 가게 바뀌는 경우 — 러너의 `pip install` 이 매번 최신을 받으므로
  **검진 코드와 수집 코드가 같은 라이브러리를 쓰게 해야** 의미가 있음.

### 6-4. 켜기 전에 오너가 결정할 것

1. 하루 **+18 요청**을 받아들일지 (§0-3-2).
2. 인증키(DART·KRX)와 Supabase 키를 검진 워크플로우에도 줄지(시크릿 노출 면적이 늘어남 — `automation-ops` 규칙 7).
3. 실패 알림을 Discord 로 받을지.

---

## 7. 이 문서를 지키는 테스트 — 무엇을 강제하고 무엇은 못 잡나

`tests/test_data_sources_inventory.py` (패턴은 `tests/test_agent_registry.py` 와 같음):

**강제하는 것**
1. 코드(`archive/`·`tests/`·`_to_delete/`·`data/` 제외)의 **문자열 상수 속 `http(s)://호스트`** 는 전부 부록 A 에 있어야 함. 없으면 빨간불.
   - 파이썬은 **AST 로 문자열 상수만** 봄 → **주석과 docstring 속 URL 은 안 잡음**(오탐 제거). YAML·JS 는 `#`·`//` 로 시작하는 줄만 뺌.
2. 부록 A 에서 "코드에 문자열로 있음 = 예"인 호스트는 실제로 코드에 있어야 함(죽은 항목 방지). "아니오"인 호스트는 코드에 **없어야** 함(라이브러리 뒤 주소를 누가 직접 하드코딩하면 문서를 고치게 강제).
3. `requirements.txt` 의 모든 패키지가 부록 B 에 분류돼 있어야 함(밖으로 나가는가/아닌가) — **새 패키지 = 새 잠재 출처**.
4. 코드가 `import` 하는 **네트워크 성격 라이브러리**(FinanceDataReader·yfinance·pykrx·supabase·google.genai·googleapiclient·httpx·aiohttp·urllib.request·pandas_datareader 등 테스트 안의 고정 목록)는 부록 B 에 있어야 함.
5. 부록 A 에서 "요청"으로 분류된 호스트는 `ENGINEERING_SPEC.md` §0-3-2 본문에도 등장해야 함(두 문서가 어긋나지 않게).

**🔴 못 잡는 것 (테스트 docstring 에도 같은 말이 있음)**
- **라이브러리 뒤에 숨은 새 주소** — 코드에 문자열이 없으니 못 봄. 4번의 고정 목록에 없는 새 라이브러리(예: 처음 보는 패키지)는 3번(requirements 분류)이 "이름을 적어라"까지만 강제하고, 그 패키지가 어디로 가는지는 **사람이 소스를 읽어야** 함.
- 문자열을 조각내 붙인 주소(`"https://" + host`), 환경변수·시크릿에서 오는 주소(Supabase·Discord) — 호스트가 코드에 없음.
- 라이브러리 **버전이 바뀌어** 같은 함수가 다른 주소로 가는 것.
- 주소는 그대로인데 **응답 구조가 바뀌는 것**(오늘 사고) — 이건 `data_sanity`·`data_freshness` 영역.

---

## 부록 A. 기계가 읽는 목록 — 호스트 (`tests/test_data_sources_inventory.py` 가 읽음)

형식을 바꾸지 마세요: 3열 표, 1열은 백틱 호스트(소문자), 3열은 `예`/`아니오`.
"코드에 문자열로 있음 = 아니오" 는 라이브러리·시크릿·인프라 뒤에 있어 코드에 호스트가 안 적힌 것.

<!-- BEGIN:HOST_REGISTRY -->
| 호스트 | 분류 | 코드에 문자열로 있음 |
|---|---|---|
| `stock.naver.com` | 요청 | 예 |
| `finance.naver.com` | 요청 | 예 |
| `navercomp.wisereport.co.kr` | 요청 | 예 |
| `opendart.fss.or.kr` | 요청 | 예 |
| `data-dbg.krx.co.kr` | 요청 | 예 |
| `stockanalysis.com` | 요청 | 예 |
| `raw.githubusercontent.com` | 요청 | 예 |
| `www.googleapis.com` | 요청 | 예 |
| `api.github.com` | 요청 | 예 |
| `visiblehand.co.kr` | 요청 | 예 |
| `fchart.stock.naver.com` | 요청(FinanceDataReader 뒤) | 아니오 |
| `data.krx.co.kr` | 요청(FinanceDataReader 뒤) | 아니오 |
| `query2.finance.yahoo.com` | 요청(FinanceDataReader 뒤) | 아니오 |
| `generativelanguage.googleapis.com` | 요청(google-genai 뒤) | 아니오 |
| `pypi.org` | 요청(pip 뒤) | 아니오 |
| `files.pythonhosted.org` | 요청(pip 뒤) | 아니오 |
| `pagead2.googlesyndication.com` | 브라우저 | 예 |
| `policies.google.com` | 링크만 | 예 |
| `adssettings.google.com` | 링크만 | 예 |
| `dart.fss.or.kr` | 링크만 | 예 |
| `github.com` | 링크만 | 예 |
<!-- END:HOST_REGISTRY -->

(시크릿에서 오는 호스트 — Supabase `SUPABASE_URL`, Discord `DISCORD_WEBHOOK_URL` — 는 값 자체를 코드가 모르므로 표에 넣을 수 없습니다. §2-B 에 적어 두었습니다.)

## 부록 B. 기계가 읽는 목록 — 패키지·라이브러리

형식: 1열 `requirements.txt` 이름(백틱), 2열 코드의 `import` 이름(백틱, 없으면 `-`), 3열 밖으로 나가는가.

<!-- BEGIN:LIBRARY_REGISTRY -->
| requirements 이름 | import 이름 | 밖으로 나가는가 |
|---|---|---|
| `finance-datareader` | `FinanceDataReader` | 예 — 네이버 차트·KRX·FinanceData 깃허브 캐시·Yahoo (§2-B) |
| `requests` | `requests` | 예 — 위 2-A 표의 직접 호출 전부 |
| `supabase` | `supabase` | 예 — `SUPABASE_URL` |
| `google-genai` | `google.genai` | 예 — Gemini |
| `nicegui` | `nicegui` | 아니오(서버) — 단, 사용자 브라우저가 정적 자원을 받음 |
| `pandas` | `pandas` | 아니오 — 단 `pd.read_csv(url)` 을 FDR 이 내부에서 씀 |
| `plotly` | `plotly` | 아니오 |
| `beautifulsoup4` | `bs4` | 아니오(파서) |
| `lxml` | `lxml` | 아니오(파서) |
| `schedule` | `schedule` | 아니오 |
| `bcrypt` | `bcrypt` | 아니오 |
| `typing_extensions` | `typing_extensions` | 아니오 |
| - | `yfinance` | 예 — Yahoo. **requirements 에 없어 Actions 에선 미설치(죽은 코드)** |
| - | `googleapiclient` | 예 — Google Drive. requirements 에 없어 Actions 에선 미설치 |
| - | `google_auth_oauthlib` | 예 — Google OAuth. 위와 같음 |
| - | `google.auth` | 예 — Google OAuth. 위와 같음 |
| - | `google.oauth2` | 예 — Google OAuth. 위와 같음 |
<!-- END:LIBRARY_REGISTRY -->
