# 네이버 신 증권(`stock.naver.com`) API 실제 응답 픽스처

## 🟢 이 픽스처는 **합성이 아닙니다**

`tests/fixtures/naver_item/*.html`(구 사이트)은 실제 페이지를 다시 긁을 수 없어
**구조만 본뜬 합성**이었습니다. 여기 있는 것은 다릅니다 —
**2026-09-07 저녁, 오너가 Chrome DevTools 에서 실제 응답을 그대로 복사해 준 원문**입니다.
세션이 네트워크로 받은 것이 아니므로 §0-3-2(상대 서버 매너) 위반이 없습니다.

## 파일

| 파일 | 원 주소 | 비고 |
|---|---|---|
| `detail_000660_codeType_KRX.json` | `stock.naver.com/api/domestic/detail/000660/detail?codeType=KRX` | 🟢 **KRX**. 추정PER·EPS·BPS 포함 |
| `consensus_000660.json` | `stock.naver.com/api/domestic/detail/000660/consensus` | 투자의견·목표주가만 (4필드) |
| `market_list_marketSum_NXT_top10.json` | `stock.naver.com/api/domestic/market/stock/default?tradeType=NXT&marketType=ALL&orderType=marketSum&startIdx=0&pageSize=10` | 🔴 **NXT**(시간외 혼입) — 그래서 **NXT 차단 테스트용으로도 씁니다** |
| `wisereport_c1010001_000660.html` | `navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd=000660` | 🟢 **오너가 브라우저에서 직접 저장한 실제 페이지**(2026-09-07). ROE·Forward ROE·EV/EBITDA·순이익·자본총계 포함. 저장 시 딸려온 JS/CSS `_files` 폴더는 저장소에 넣지 않았습니다 |

## ⚠️ 원문에서 **뺀 것** (§0-1 — 숨기지 않고 밝힙니다)

`market_list_...json` 의 각 종목에서 **값이 전부 `null` 인 ETF 전용 필드 14개**를 제외했습니다:
`etfChseErnrtDblSmbl` · `etfChseErnrtDbl` · `refNidxLvgTpCd` · `etfType` ·
`oneMonthEarnRate` · `threeMonthEarnRate` · `sixMonthEarnRate` · `oneYearEarnRate` ·
`nav` · `deviationSign` · `deviationRate` · `totalNetAssets` · `totalFee` · `issuerNameKo`.
→ 원본 75필드 → 픽스처 61필드. **숫자 필드는 하나도 건드리지 않았습니다.**
→ ETF 를 다루게 되면 이 픽스처로는 부족합니다. 그때 새로 받아야 합니다.

## 🔴 전사(轉寫) 오류 방지 장치

사람이 복사·붙여넣기 한 값이므로 **오타 한 글자가 조용한 오류**가 됩니다.
그래서 `tests/test_naver_new_api.py` 가 픽스처 자체의 **산술 정합성**을 검사합니다:

- `per` ≟ `nowPrice ÷ eps`
- `estimatedPer` ≟ `nowPrice ÷ estimatedEps`
- `pbr` ≟ `nowPrice ÷ bps` (detail 만 — 목록의 `pbr` 은 **전일 종가 기준**이라 다름)
- `dividendRate` ≟ `dividendAmount ÷ nowPrice × 100`
- `marketSum` ≟ `listedStockCnt × nowPrice`

이 검사가 빨간불이면 **픽스처가 잘못 옮겨 적힌 것**입니다. 코드를 의심하기 전에 픽스처를 보세요.

## 관련 문서

`NAVER_MIGRATION_WORK_ORDER.md` §1-5-2 ~ §1-5-13 에 각 API 의 실측 결과·함정·판정이 있습니다.
특히 **§1-5-11(NXT 함정)** 은 이 픽스처를 쓰기 전에 반드시 읽어야 합니다.
