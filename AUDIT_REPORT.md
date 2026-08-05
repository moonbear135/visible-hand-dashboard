# 🔍 데이터 무결성 감사 보고서 (AUDIT_REPORT)

> **감사 일자**: 2026-08-05
> **수정 반영일**: 2026-08-05 (동일자 후속 수정 패스)
> **감사 범위**: 프로젝트 내 모든 `.py` 파일 (25개), `.github/workflows`, `data/*.json`, `market_history.csv`, `ENGINEERING_SPEC.md`
> **감사 목적**: **"하드코딩·더미 데이터가 실제 데이터인 척 조용히 대시보드에 표시되는 지점"** 을 전부 찾아내는 것.

---

## ✅ 수정 반영 상태 (2026-08-05)

이 보고서는 원래 **진단 전용**이었으나, 오너 승인("추천 방향대로 전부 수정")에 따라 실제 수정이 반영되었습니다.
각 항목 아래에 다음 표기가 붙어 있습니다.

| 표기 | 의미 |
|------|------|
| ✅ **수정 완료** | 코드가 실제로 수정되었습니다 (무엇을 바꿨는지 함께 기재) |
| ⏸️ **보류** | 의도적으로 수정하지 않았습니다 (오너 판단 필요 / 파일 삭제 권한 필요 / 실데이터 검증 필요) |

**수정 원칙**: 데이터를 얻지 못하면 **그럴듯한 숫자를 만들지 않고** ① 배치 수집기는 `raise` 로 중단, ② 개별 지표는 `None` + UI '데이터 없음', ③ 화면 전체가 불가능하면 빨간 배너 + 렌더링 중단.
사이트가 "꽉 차 보이는 것"보다 **오류가 눈에 보이는 것**을 우선했습니다 (ENGINEERING_SPEC §0-1).

### 🔑 오너가 직접 해야 하는 조치 (2건)

1. **관리자 비밀번호 재설정** — 기존 비밀번호는 git 히스토리에 평문으로 남아 있어 **유출된 것으로 간주**해야 합니다.
   소스에서 해시를 완전히 제거했으므로, `ADMIN_PASSWORD_HASH` (Streamlit Secrets 또는 환경변수)를 설정하기 전까지 **관리자 모드는 열리지 않습니다.** 설정 방법은 `views/admin_view.py` 상단 주석 참고.
2. **GitHub Actions 수동 1회 실행(`Daily Market Scraper` → Run workflow)** 후 대시보드 확인 — 이번 수정으로 '데이터 없음' 표기가 늘어나는 것이 **정상**입니다(그동안 가짜 값으로 채워져 있던 자리입니다).

---

## 📌 요약 (Executive Summary)

가장 심각한 5가지는 다음과 같습니다. 모두 **현재 배포된 실제 데이터에서 발생 중임을 수치로 확인**했습니다.

1. **🔴 변동성(vol) 지표가 종목코드 해시로 만들어진 가짜입니다.** `collector_kospi200.py:348` — `code_hash % 3`. 현재 200종목 중 **78개**가 "⚡ 변동성 보정 중" 배지를 달고 PEGY에 1.18배 벌점을 받고 있는데, 이는 실제 주가 변동성과 아무 관련이 없습니다.
2. **🔴 Forward ROE / ROIC / 성장률이 전부 Trailing ROE의 산술 변환값이거나 상수입니다.** `collector_kospi200.py:341-345` — 현재 **f_roe = 8.5 고정값 27종목, roic = 6.8 고정값 30종목**. 화면 툴팁은 "애널리스트 예상"이라고 설명합니다.
3. **🔴 상장주식수 파싱이 197/200 종목에서 깨져 있는데 아무 경고도 없습니다.** 삼성전자 `outstanding_shares: 46` (실제 59억 주). 그 결과 **166개 종목이 주주환원 총액을 "총 0억원"으로 표시**하고 있으며, guardrail의 배당 교차검증은 같은 깨진 값끼리 비교하므로 절대 걸러내지 못합니다.
4. **🔴 자동 수집 스케줄러 2개가 모두 존재하지 않는 파일을 호출합니다.** `scheduler.py:28`, `utils/scheduler.py:35` → `collector_kospi200_2` (실제 파일명은 `collector_kospi200`). 수집은 영원히 실패하지만 대시보드는 예전 JSON을 "📅 마지막 동기화 …(장 마감 반영)" 배너와 함께 정상인 것처럼 계속 보여줍니다.
5. **🔴 매크로 화면은 CSV 로드가 실패하면 KOSPI 2500 / 환율 1350 이라는 가짜 시세로 위험점수를 계산해 그대로 렌더링합니다.** `views/macro_view.py:83-92, 392-397`. 유일한 신호는 회색 `st.info("⚠️ 안전 모드")` 한 줄입니다.

**추가로 반드시 볼 것**: `utils/guardrail.py:65` 가 3단계 검증(DataValidator) 결과를 **무조건 `is_valid = True`로 덮어씁니다.** 검증에 실패한 종목도 점수가 매겨져 정상 카드로 노출됩니다. 그리고 `views/admin_view.py:18` 주석에 **관리자 비밀번호 평문이 그대로 적혀 있고 git 히스토리에도 남아 있습니다.**

> ✅ **위 5건 + 추가 2건, 전부 수정 완료되었습니다.** 각 항목의 상세 내용은 아래 해당 섹션의 `✅ 수정 완료` 표기를 참고하세요.
> 다만 **관리자 비밀번호는 오너가 직접 새로 설정**해야 합니다(감사자가 비밀번호를 정하지 않았습니다 — 위 '🔑 오너가 직접 해야 하는 조치' 참고).

---

## 1. `scrape_daily.py` (일별 매크로 수집기)

### 🔴 1-1. 변동성·고점대비낙폭 시드값이 실데이터 자리에 그대로 남음 (L96-98)

```python
volatility = 1.2          # L96
dist_from_high = 0.08     # L97
kospi_5d_base = 0.5       # L98
```

이 값들은 FDR 조회가 성공했을 때만 덮어써집니다(L125, L129, L144). 그런데 그 아래 L155-182의 네이버 스크래핑 블록은 **KOSPI/환율만** 갱신합니다.

- **문제 시나리오**: FDR(야후) 조회 실패 → `⚠️ FinanceDataReader 수집 실패` 라고 **print만** 하고 계속 진행 → 네이버에서 KOSPI/환율은 정상 수집 → `volatility=1.2`, `dist_from_high=0.08` 인 채로 아래 계산식에 투입됩니다.
- **오염 범위**: `short_base`(공매도 비중), `els_base`(ELS 낙인), `skew_base`(공포지수), `bal_base`(공매도 잔고) — **14개 지표 중 4개**와 최종 종합점수.
- **왜 위험한가**: 점수는 그럴듯한 숫자로 나오고, CSV에 저장되고, 대시보드에 표시되며, 어디에도 "이 날은 변동성 데이터가 없었음"이라는 표시가 남지 않습니다. GitHub Actions 로그를 열어보지 않는 한 알 수 없습니다.
- **권장 수정**: `volatility = None`, `dist_from_high = None` 으로 초기화하고, 계산 직전에 `if volatility is None: raise RuntimeError("변동성 데이터 수집 실패 - 당일 수집 중단")` 로 **수집 자체를 중단**하십시오. (수급 실패 시 L239-241에서 이미 이렇게 하고 있으므로 같은 패턴을 쓰면 됩니다.)

> ✅ **수정 완료**: 시드값 3개를 모두 `None` 으로 초기화하고, 계산 직전에 `raise RuntimeError` 로 당일 수집을 중단하도록 변경. 5일 모멘텀(`kospi_5d_base`)은 산출 실패 시 0.5 대입 대신 해당 지표를 가중치 딕셔너리에서 제거하고 남은 가중치로 정규화.

### 🔴 1-2. Forward Fill(전일 종가 대입)이 CSV에 흔적 없이 저장됨 (L186-199)

```python
if pd.isna(kospi_close) or pd.isna(usd_close) or kospi_close is None or usd_close is None:
    print("🚨 ... Forward Fill 보정 시도합니다.")
    if not history_df.empty:
        kospi_close = float(history_df.iloc[-1]['KOSPI'])
        kospi_change = 0.0
```

- 전일 종가가 **오늘 종가 자리에** 그대로 저장되고, `kospi_change = 0.0`(보합)으로 기록됩니다. CSV에는 "이 행은 보정값"이라는 컬럼이 없습니다.
- 대시보드는 이 행을 실제 종가와 100% 동일하게 렌더링합니다(`views/macro_view.py:375-385`의 KOSPI 카드). 사용자가 알 방법이 전혀 없습니다.
- **권장 수정**: ① CSV에 `data_quality` 컬럼 추가(`OK` / `FFILL_KOSPI` / `FFILL_USD`), ② 대시보드 카드에 해당 행이 FFILL이면 "⚠️ 전일 값 보정" 배지 노출, ③ 또는 아예 `return` 하여 그날 행을 만들지 않기(가장 안전).
- 참고: L112-113의 `.ffill()` 도 같은 성격입니다. FDR 데이터프레임 자체를 전일 값으로 채우므로, **휴장일이 아닌 진짜 결측**도 조용히 메워집니다.

> ✅ **수정 완료**: 권장안 ③ 채택 — Forward Fill 블록 전체를 삭제하고 `raise RuntimeError` 로 당일 행 자체를 만들지 않음. `.ffill()` 도 `.dropna(subset=['Close'])` 로 교체하여 진짜 결측이 조용히 메워지지 않도록 함. (`data_quality` 컬럼은 이제 보정 자체가 없으므로 불필요)

### 🔴 1-3. 14개 "지표"는 수집된 데이터가 아니라 5개 입력값의 공식 파생값입니다 (L243-327)

```python
fx_base   = 0.5 + 0.3 * (usd_close - 1200) / 300     # "외환 스왑포인트"
put_base  = 0.5 - 0.4 * kospi_change                 # "풋옵션 미결제약정"
short_base= 0.4 + 0.4 * (volatility / 5.0)           # "공매도 거래 비중"
stock_net_base = 0.5                                 # "주식 현물 순매도 규모" ← 완전 상수
```

- 실제로 수집되는 원천 데이터는 **KOSPI 종가, 환율, 두 값의 전일 대비 변화율, 투자자 3주체 수급** 5가지뿐입니다. 나머지는 이 5개로부터 계산된 **프록시(추정 대용치)** 입니다.
- 그런데 CSV 컬럼명과 대시보드 표(`views/macro_view.py:511-556`)는 "외환 스왑포인트", "풋옵션 미결제약정", "ELS 낙인 위험", "공매도 잔고"라고 표기합니다. 사용자는 이 숫자들이 실제 파생상품/공매도 시장에서 수집된 값이라고 오해합니다.
- `Stock_Net_Sell`은 `stock_net_base = 0.5`에 수급 부호만 ±0.3 더한 값으로, 사실상 "외국인이 순매도인가?" 라는 이진 신호입니다.
- **권장 수정**: 코드 로직을 바꿀 필요는 없습니다. 다만 **UI 표기를 정직하게** 바꾸십시오. 예: "외환 스왑포인트 **(추정 프록시)**", 그리고 상세 표 상단에 "본 14개 지표는 KOSPI·환율·수급 5개 실측값으로부터 산출한 추정 프록시이며, 실제 파생상품 시장 데이터를 직접 수집한 값이 아닙니다" 문구 추가. (지금은 이 사실이 코드 밖 어디에도 없습니다.)

> ✅ **수정 완료**: `views/macro_view.py` 의 '14개 지표 상세 분석표' 상단에 **추정 프록시 고지 `st.info()` 박스**를 추가 (5개 실측값에서 계산된 대용치이며 파생상품 시장 직접 수집값이 아님을 명시). 산출 불가 지표는 표에 '데이터 없음'으로 표기.

### 🟡 1-4. 이력이 2행뿐이라 Z-Score 정규화가 사실상 무의미 (L329-346)

```python
else:
    mean_val = 0.5
    std_val = 0.15
```

- 현재 `market_history.csv`에는 **데이터 행이 2개뿐**입니다(2026-07-31, 2026-08-03). 2행이면 표준편차가 극단적으로 작아져 `std_val = max(0.02, std)` 하한에 걸리고, Z-score가 ±20으로 클리핑되어 서브 점수가 0.0 또는 100.0으로 튑니다. 실제로 08-03 행을 보면 14개 중 **7개 지표가 정확히 0.0**입니다.
- 이력이 없을 땐 `mean 0.5 / std 0.15` 라는 하드코딩 상수가 쓰이므로 점수의 의미가 날짜마다 달라집니다.
- **권장 수정**: 이력 행 수가 예컨대 20개 미만이면 종합점수 옆에 "⚠️ 표본 부족(n=2) — 점수 신뢰도 낮음"을 대시보드에 표시.

> ✅ **수정 완료**: 대시보드 종합점수 아래에 `n < 20` 이면 표본 부족 경고 배너 노출. 수집기(`scrape_daily.py`)에도 동일 경고 로그 추가.

### 🟡 1-5. 조용한 예외 처리 3곳
- L149-150 `except: print("⚠️ FinanceDataReader 수집 실패")` → 계속 진행 (위 1-1의 원인)
- L181-182 `except: print("⚠️ 네이버 금융 스크래핑 실패 (FDR 값 유지)")` → 계속 진행
- L426-427 `except: print("⚠️ AI 코멘트 생성 중 에러")` → 계속 진행 (전일 코멘트가 오늘 것처럼 남음, 8-1 참조)

> ✅ **수정 완료(1-1 연동)**: FDR/네이버 수집이 모두 실패하면 이후 필수값 검증에서 `raise` 되므로 더 이상 '계속 진행'되지 않습니다. AI 코멘트 실패는 8-1 수정으로 화면에 생성일자가 표기됩니다.

### ⚪ 1-6. 기타
- L46-50 `PERIOD_KEYWORDS` 사본이 정의만 되어 있고 이 파일에서 한 번도 쓰이지 않습니다(죽은 코드). SPEC §3은 "개별 크롤러에 하드코딩 금지"라고 명시하고 있으므로 삭제 대상입니다.
- L430 `TARGET_FOLDER_ID = "1wTMFTI2..."` 구글 드라이브 폴더 ID 하드코딩(기능상 문제는 없음).

> ✅ **수정 완료**: 사본 딕셔너리를 삭제하고 `from utils.data_validator import PERIOD_KEYWORDS` 단일 출처 참조로 교체.
> ⏸️ **보류**: `TARGET_FOLDER_ID` 는 비밀정보가 아니고 기능상 문제도 없어 그대로 두었습니다(환경변수화는 오너 판단).

---

## 2. `collector_kospi200.py` (KOSPI 200 수집기) — 가장 오염이 심한 파일

### 🔴 2-1. 변동성 상태를 종목코드 해시로 만들어냄 (L348-349)

```python
code_hash = sum(ord(c) for c in code)
vol = "🟢 정상" if (code_hash % 3 != 0) else "⚡ 변동성 보정 중"
```

- **주가 데이터를 전혀 보지 않습니다.** 종목코드 글자의 아스키 합이 3의 배수면 "변동성 보정 중"입니다. 같은 종목은 영원히 같은 상태입니다.
- 이 값은 ① `vol_penalty = 1.18` 로 PEGY를 악화시키고(L370), ② 퀀트 스코어 5점 항목을 결정하고(`utils/scoring.py:89`), ③ 종목 카드에 빨간 배지로 노출됩니다(`views/pegy_view.py:616`).
- **실측**: 현재 스냅샷 200종목 중 **78종목**이 이 가짜 배지를 달고 감점당하고 있습니다.
- **권장 수정**: 실제 변동성(예: 최근 20일 수익률 표준편차)을 계산하거나, 계산할 수 없다면 **지표 자체를 제거**하고 스코어 배점을 재조정하십시오. 최소한 `vol = "❔ 변동성 데이터 없음"` 으로 두고 벌점을 주지 않아야 합니다.

> ✅ **수정 완료**: `code_hash` 로직 완전 삭제. 새 함수 `fetch_recent_volatility(code)` 가 FinanceDataReader 로 **최근 20영업일 일간수익률 표준편차(%)** 를 실측하고, 2.0% 이상이면 `⚡ 변동성 확대 (n.n%)`, 미만이면 `🟢 정상 (n.n%)` 으로 표기. 조회 실패 시 `❔ 변동성 데이터 없음` + **벌점(1.18x) 미적용** + 스코어 5점 항목을 **배점에서 제외**(만점이 95점으로 표기됨).

### 🔴 2-2. Forward ROE / ROIC / 성장률이 전부 조작값 (L341-345)

```python
f_roe  = round(t_roe * 1.12, 1) if t_roe > 0 else 8.5
roic   = round(t_roe * 0.88, 1) if t_roe > 0 else 6.8
growth = round(min(max(t_roe * 1.3, 5.0), 45.0), 1) if t_roe > 0 else 0.0
```

- ROIC은 원래 영업이익/투하자본으로 별도 계산해야 하는 지표인데, 여기서는 **ROE에 0.88을 곱한 값**입니다. Forward ROE도 Trailing ROE × 1.12 입니다. 즉 세 지표는 전부 t_roe 하나의 복사본입니다.
- `t_roe`가 0이면 **8.5 / 6.8** 이라는 상수가 들어갑니다. **실측: f_roe=8.5 인 종목 27개, roic=6.8 인 종목 30개.**
- 화면 툴팁(`views/pegy_view.py:717`)은 *"향후 12개월 애널리스트 예상 순이익 기반 ROE"* 라고 설명합니다 — 사실이 아닙니다.
- `growth`는 PEGY 분모이자 목표주가의 핵심 입력이므로, 오염 파급이 가장 큽니다.
- **권장 수정**: 실제 컨센서스를 못 가져오면 `f_roe = None`으로 두고 UI에 "데이터 없음"으로 표기, 스코어링에서 해당 항목 제외. 파생 계산이 불가피하다면 최소한 JSON에 `"f_roe_source": "derived_from_t_roe"` 플래그를 넣고 카드에 "추정치" 표시.

> ✅ **수정 완료**: 
> - `f_roe` / `roic` → **`None` 고정**(컨센서스 원천을 수집하지 않으므로 지어내지 않음). UI는 '데이터 없음', 스코어 30점(15+15)은 **배점에서 제외**되어 만점이 70점으로 표기됩니다. 툴팁 문구도 "애널리스트 예상" → "수집하지 않아 데이터 없음"으로 정정. 실제 컨센서스 수집기를 붙일 위치에 `TODO(오너)` 주석 명시.
> - `growth` → t_roe 파생값 삭제, **네이버 실측 '추정 EPS(컨센서스)' vs 'TTM EPS' 의 실제 증감률**로 재산출(`growth_source: "consensus_eps_vs_ttm_eps"`). 둘 중 하나라도 없으면 `None` → 해당 종목은 '측정 불가' 카드.

### 🔴 2-3. 자사주 매입 수익률 2.5%를 지어냄 (L331, L337)

```python
buyback_yield = 2.5 if (t_roe >= 10.0 and (dps > 0 or div_yield > 0)) else 0.0
...
tot_return_krw = int((tot_dividend_krw + (int(price * 0.003) * valid_shares)) / 100000000)
```

- 자사주 매입 공시를 확인한 적이 없는데 **ROE 10% 넘고 배당하면 무조건 자사주 2.5% 한다고 가정**합니다. `price * 0.003`(주가의 0.3%)도 근거 없는 상수입니다.
- **실측: 200종목 중 115종목의 `sh_return`이 2.5 이상**이며, 이 값은 퀀트 스코어 20점 항목(주주환원)에 직결됩니다.
- **권장 수정**: 자사주 데이터를 수집하지 않는다면 `buyback_yield = 0.0`으로 두고, UI 라벨을 "배당수익률"로 정정하십시오. "주주환원율"이라는 이름을 유지하려면 실제 자사주 공시를 수집해야 합니다.

> ✅ **수정 완료**: 자사주 2.5% 가정과 `price * 0.003` 총액 가산을 **모두 삭제**. `sh_return` 은 이제 **배당수익률만** 반영하며, JSON에 `sh_return_basis: "배당수익률만 반영 (자사주 매입 공시 미수집)"` 을 기록하고 카드 라벨/툴팁도 '배당수익률'로 정정.

### 🔴 2-4. 상장주식수 파싱 실패가 조용히 통과 (L82-89) → 주주환원 총액 전부 엉터리

```python
elif '상장주식수' in text:
    shares_text = text.split('상장주식수')[-1].strip()
    shares_match = re.search(r'(\d[\d,]*)', shares_text)
```

- **실측: 200종목 중 197종목의 `outstanding_shares`가 100,000 미만**입니다. 삼성전자 `46`, SK하이닉스 `51`, KB금융 `79`, LG에너지솔루션 `5`. (값 분포로 보아 상장주식수가 아니라 외국인소진율(%) 같은 **다른 필드**를 집어온 것으로 보입니다.)
- 결과: `total_dividend_krw = dps * 46 = 26,036원`, `tot_return_krw = 0억원` → **166개 종목이 대시보드에 "총 0억원"** 으로 표시됩니다. 사용자에겐 "이 회사는 주주환원을 0원 한다"로 읽힙니다.
- 예외 처리도 `except ValueError: outstanding_shares = 0` (L88-89)으로 조용합니다.
- **권장 수정**: `if outstanding_shares < 1_000_000: raise ValueError(f"{code} 상장주식수 파싱 실패: {outstanding_shares}")` 같은 **범위 검증(sanity range check)** 을 넣고, 실패 종목은 `is_unverified=True` 로 마스킹하십시오.

> ✅ **수정 완료**: 파서가 행 안의 모든 숫자 후보를 수집한 뒤 **100만 주(`MIN_OUTSTANDING_SHARES`) 이상인 값만** 채택하고, 없으면 `None` + 실패 사유를 `data_issues` 에 기록. guardrail 에도 동일한 범위 검증을 넣어 파싱 오염 종목을 마스킹합니다. 총액은 상장주식수가 검증을 통과했을 때만 산출하며, 실패 시 "총 0억원" 대신 **"데이터 없음 (상장주식수 미확보)"** 로 표시됩니다.

### 🔴 2-5. PER / EPS 결측 시 그럴듯한 숫자로 대체 (L238, L303, L308, L314, L319)

```python
"t_per": abs(t_per) if t_per != 0 else 12.5     # L238 — 시총표 파싱 실패 시 PER 12.5
t_per = 12.5                                     # L303
t_eps = int(price / t_per)                       # L308 — EPS를 주가/PER로 역산
f_per = round(max(t_per * 0.88, 4.5), 2)         # L314 — Forward PER = Trailing PER × 0.88
f_eps = int(price / f_per)                       # L319
```

- `t_eps = price / t_per` 로 역산하면 **DataValidator 2단계 산티체크(`계산PER == 표기PER`)를 항상 통과**합니다. 검증을 통과하도록 데이터를 만들어내는 셈입니다.
- **실측: 39종목의 `f_per`가 `t_per × 0.88` 대체값**입니다. 화면에는 "*12개월 Forward 컨센서스*"라고 적혀 있습니다.
- **권장 수정**: `None` 반환 후 해당 종목을 `is_unverified` 로 마스킹(이미 존재하는 회색 카드 UI를 재활용하면 됩니다).

> ✅ **수정 완료**: `12.5` 상수, `t_eps = price / t_per` 역산, `f_per = t_per × 0.88` 대체, `f_eps = price / f_per` 역산을 **전부 삭제**하고 실측값이 없으면 `None`. 검증 2단계에서 걸러져 회색 '데이터 없음' 카드로 렌더링됩니다(카드 테마 신규 추가). 시총 리스트의 PER 파싱 실패 시 `12.5` 대입도 제거.

### 🔴 2-6. 3단계 검증 결과가 guardrail에 의해 무효화됨 (L397-437)

```python
valid_pass, v_logs = DataValidator.run_pipeline(...)
is_valid = valid_pass                      # L398
...
stock_dict = apply_valuation_guardrail(stock_dict)   # L437 ← 여기서 is_valid가 True로 덮어써짐
```

`utils/guardrail.py:65-66`이 함수 끝에서 조건 없이 `cleaned['is_valid'] = True` 를 씁니다. 즉 **DataValidator가 "차단" 판정한 종목도 그대로 스코어링되어 정상 카드로 표시**됩니다(L455 조건이 항상 참).

> ✅ **수정 완료**: guardrail 을 전면 재작성하여 상위 판정을 **AND 로만 결합**(`is_valid = 상위판정 and 자체판정`). 검증 실패 사유는 `validation_error` → `unverified_reason` 으로 승계되어 카드에 표시됩니다. collector 의 스코어링 조건도 `is_valid` 기본값을 `True` → `False` 로 바꿔 미확인 종목이 점수를 받지 못하게 했습니다.

- 검증 실패의 유일한 흔적은 L402의 `print("⚠️ ... 3단계 하네스 검증 경고")` — GitHub Actions 로그뿐입니다.
- **실측**: 현재 `is_valid=False` 인 종목은 3개인데, 이는 전부 guardrail의 PER 범위 규칙에 걸린 것이고 DataValidator 판정은 하나도 반영되지 않았습니다.
- **권장 수정**: guardrail이 `is_valid`를 True로 올리지 못하게 하고(`cleaned['is_valid'] = cleaned.get('is_valid', True) and ...`), 검증 실패 사유를 `stock_dict['validation_error']`에 담아 카드에 표시하십시오.

### 🟡 2-7. 메타데이터가 항상 "SUCCESS" / "100% 실데이터" (L540-546)

```python
"status": "SUCCESS",
"description": "KOSPI 200 시가총액 상위 1위~200위 100% 실데이터 퀀트 스냅샷 (장 마감 반영)"
```

몇 종목이 실패했든 status는 언제나 SUCCESS입니다. **권장**: `"status": "SUCCESS" if valid_ratio >= 0.95 else "DEGRADED"`, `"valid_count"`, `"failed_codes"` 를 함께 저장하고 대시보드 배너에 노출.

> ✅ **수정 완료**: 권장안 그대로 구현(`SUCCESS` / `DEGRADED` / `FAILED` + `valid_count` + `valid_ratio` + `failed_codes`), description 도 실제 검증 통과 종목 수를 반영하도록 변경. 대시보드 상단에 상태가 SUCCESS가 아니면 경고 배너를 노출합니다.

### 🟡 2-8. SPEC §2-1(iloc 금지) 위반 — 위치 인덱스 폴백 (L105-107)

```python
if not annual_cols:
    annual_cols = [idx for idx, col in enumerate(fin_df.columns) if '분기' not in str(col) and idx > 0][:3]
```
키워드 분류 실패 시 **앞에서 3개 컬럼을 위치로** 집습니다. SPEC이 "절대 금지"한 바로 그 패턴이며, 분기 데이터를 연간으로 오인할 수 있습니다. **권장**: 폴백 없이 `parsed_dps = None` 반환.

> ✅ **수정 완료**: 위치 인덱스 폴백을 삭제하고 DPS 미수집(`None`) + `data_issues` 기록으로 변경.

### 🟡 2-9. 목표주가 상한 캡이 제거되어 SPEC과 불일치 (L380-384)

```python
target_per = 10.4 * (1.0 + roe_prem + roic_prem)
# 목표주가 폭발 방지 상한선 캡 없음
f_target = int(max(f_eps * target_per, 0))
```
SPEC §5-2는 `target_per = min(target_pegy × growth_eff, 25.0)`, `f_target = min(f_eps × target_per, price × 2.5)` 라고 적혀 있습니다. **실측: 현재가의 2.5배를 넘는 목표주가가 15종목**(삼성전자 목표가 548,307원 = 현재가의 2.29배). 문서와 코드가 다르면 문서를 신뢰할 수 없게 됩니다 — 둘 중 하나를 맞추십시오.

> ✅ **수정 완료**: **코드를 SPEC §5-2 에 맞췄습니다.** `target_pegy = 1.0 × (1 + roe_prem + roic_prem)`, `target_per = min(target_pegy × growth_eff, 25.0)`, `f_target = min(f_eps × target_per, price × 2.5)`, `t_fair = min(t_eps × min(g_eff, 25.0), price × 2.5)`.

### 🟡 2-10. 조용한 예외 3곳
- L120-121 `except Exception: pass` (DPS 파싱)
- L137-138 EV/EBITDA 실패 → print만, `ev_ebitda = "-"` 로 남음 (이건 "-"로 표시되므로 그나마 정직함)
- L361-362 `except Exception: pass` (yfinance 교차검증) — 교차검증이 통째로 실패해도 `per_discrepancy=False`(=이상 없음)로 기록됩니다. **실패와 정상을 구분할 수 없습니다.**

> ✅ **수정 완료**: 세 곳 모두 실패 사유를 종목별 `data_issues` 리스트(JSON에 저장)에 기록하도록 변경. `per_discrepancy` 는 **`None`(검증 미수행/실패) / `False`(이상 없음) / `True`(이격 발생)** 3상태로 분리했고, 관리자 화면에 '외부 교차검증 미수행' 배지가 따로 표시됩니다. EV/EBITDA 미수집은 `"-"` 대신 `None` → UI '데이터 없음'.

### ⚪ 2-11. 요약지표 폴백 상수 (L495-497)
`calc_f_per=10.4 / calc_growth=14.2 / calc_pegy=0.73` — 종목 리스트가 비면 이 값이 이력 JSON에 기록됩니다. (동일 상수가 `views/pegy_view.py:303-309`에도 중복.)

> ✅ **수정 완료**: 수집기·화면 양쪽에서 상수 3개를 제거하고 표본이 없으면 `None`(화면은 '데이터 없음'). 요약 이력 JSON에는 `f_per_sample_count` 등 **표본 개수**를 함께 기록합니다.

---

## 3. `utils/guardrail.py`

- **🔴 3-1 (L65-66)**: `cleaned['is_valid'] = True` 무조건 대입 — 위 2-6 참조. 상위에서 내려온 검증 실패 판정을 파괴합니다.
  > ✅ **수정 완료**: `_finish()` 헬퍼로 모든 반환 경로가 상위 판정과 **AND 결합**하도록 재작성. 이제 어떤 경로로도 `is_valid` 가 False→True 로 올라가지 않습니다.
- **🟡 3-2 (L37-45)**: 배당 교차검증이 **동어반복**입니다. `total_dividend_krw`는 collector L336에서 `dps * outstanding_shares`로 계산된 값인데, 여기서 다시 `dps * outstanding_shares`와 비교합니다. 오차는 항상 0이므로 이 검증은 **절대 발동하지 않습니다.** 2-4의 197종목 파싱 오류를 잡지 못한 이유가 이것입니다. → 서로 다른 출처(예: 공시 총배당금)와 비교하도록 바꾸거나, 검증이 무의미하다는 사실을 명시하십시오.
  > ✅ **수정 완료**: 동어반복 검증을 삭제하고 **상장주식수 범위 검증(sanity range check)** 으로 교체. 코드 주석에 "서로 다른 출처의 총배당금 공시를 수집하기 전까지는 범위 검증으로 대체"라고 명시했습니다.
  > ⏸️ **보류**: 진짜 교차검증(공시 총배당금 별도 수집)은 새 데이터 소스가 필요하므로 오너 판단 사항입니다.
- **⚪ 3-3 (L51-54)**: `g_eff <= 0` 이면 `is_valid=True, is_unverified=False`로 통과시킵니다. SPEC §5-4 표는 "PEGY 99.0 강제, 40점 감점, 목표가=현재가×0.7"이라고 적혀 있으나 코드에는 그 로직이 없습니다(scoring.py에서 15점 처리로 대체). SPEC과 코드 불일치.
  > ⏸️ **보류**: 역성장 종목은 현재 `is_negative_growth` 플래그를 달고 scoring.py 에서 15점 + '🔴 실적 역성장/적자' 배지로 **명확히 표시**되고 있어 사용자에게 숨겨지는 문제는 없습니다. "PEGY 99.0 강제 / 40점 감점" 이라는 SPEC 문구를 코드에 맞출지, 코드를 SPEC에 맞출지는 **점수 체계 변경이라 오너 판단이 필요**하여 보류합니다.

---

## 4. `utils/data_validator.py`

- **🔴 4-1 (L105)**: 
  ```python
  raw_period = raw_dict.get("raw_period", expected_target)
  ```
  raw에 기간 정보가 없으면 **기대값을 그대로 가져다 자기 자신과 비교**합니다. 게다가 호출부(`collector_kospi200.py:393`)는 `{"raw_period": "TTM"}` 을 **하드코딩**해서 넘깁니다. 즉 1단계 "타겟-목적 1:1 일치" 검증은 **어떤 경우에도 성공 로그(`✅ 1단계 ... 일치 확인`)만 출력하는 껍데기**입니다. 검증했다는 착각을 만든다는 점에서 검증이 없는 것보다 나쁩니다.
  → 실제 파싱한 컬럼 헤더에서 `classify_header_timeframe()` 결과를 넘기도록 고치고, 없으면 `raise`.
  > ✅ **수정 완료**: `raw_dict.get("raw_period", expected_target)` 의 기본값을 제거(`get("raw_period")`)하여 **없으면 1단계 검증 실패**로 처리. collector 는 하드코딩 "TTM" 대신 **실제 파싱한 헤더 라벨**(예: `PERlEPS(2026.09)`)을 판정해 넘깁니다. 네이버의 `PER|EPS(YYYY.MM)` 은 정의상 최근 4분기 합산(TTM)이므로 그 규칙만 코드 주석과 함께 명시적으로 매핑했고, 헤더 자체를 못 찾으면 `None` → 검증 실패 → 해당 종목 마스킹.
- **🟡 4-2 (L7-10)**: 키워드에 단일 문자 `"A"`, `"Q"`, `"D"`, `"E"`, `"P"` 가 포함되어 있어 영문이 섞인 헤더는 거의 무조건 매칭됩니다(예: "Annual Data"에 D가 있어 DAILY로 오분류). 단일 문자는 정규식 경계(`\b`)로 감싸야 합니다.
  > ✅ **수정 완료**: 단일 문자 키워드를 전부 `r"\bA\b"` 형태로 교체하고 매칭 로직을 정리(+영문 대소문자 무관 매칭). 검증 결과 `"Annual Data" → TTM`, `"1Q 실적" → QUARTERLY`, `"일별" → DAILY` 로 정상 분류됩니다.
- **🟡 4-3 (L156, L171)**: 2차 출처가 없으면 "Primary 단독 승인" 으로 **통과** 처리됩니다. 교차검증 미수행과 교차검증 통과가 같은 결과값(True)입니다.
  > ✅ **수정 완료**: 로그 문구를 "⚠️ 3단계 교차 검증 미수행 … (검증되지 않음 / 통과 아님)" 으로 바꾸고, 종목 JSON에 `cross_validated: true/false` 플래그를 저장하여 미수행 사실이 데이터에 남도록 했습니다. (차단까지 하면 2차 출처가 없는 대부분 종목이 사라지므로 반환값은 통과 유지)

---

## 5. `utils/db.py` (대시보드가 쓰는 CSV 입출력)

### 🔴 5-1. 예외 발생 시 히스토리 전체가 1행으로 덮어써짐 (L206-210)

```python
except Exception as e:
    if is_admin:
        st.error(f"❌ [관리자] 파일 읽기/쓰기 중 오류 발생: {str(e)}")
    new_df.rename(columns=COL_MAP).to_csv(HISTORY_FILE, index=False)   # ← 전체 이력 파괴
    history_df = new_df
```

CSV 읽기 중 어떤 예외든 발생하면 **누적 이력 전체를 오늘 1행짜리 파일로 덮어씁니다.** 관리자 모드가 아니면 오류 메시지조차 보이지 않습니다. 대시보드는 그냥 "이력이 1개"인 화면을 정상적으로 그립니다.
→ **권장**: 예외 시 절대 쓰지 말고 `raise` 하거나 `st.error`를 무조건 노출. 쓰기 전 `.bak` 백업 필수.

> ✅ **수정 완료**: 예외 처리에서 **쓰기 동작을 완전히 제거**했습니다. 이제 실패 시 ① 아무것도 저장하지 않고 ② `st.error` 를 **모든 사용자에게** 노출하며 ③ 읽을 수 있는 만큼만 반환합니다. 또한 모든 저장 경로를 `_safe_write_history()` 로 통일해 **쓰기 전 `market_history.csv.bak` 백업**을 남깁니다.

### 🔴 5-2. `backfill_missing_metrics()` — 과거 14개 지표를 역산해서 실측값처럼 저장 (L35-110)

```python
for col in metrics_cols:
    df[col] = 0.5
...
df.at[i, "FX_Swap_Point"] = round(clip(fx_base + 0.1*u_change)*0.55 + ..., 3)
```

- 과거 날짜의 "외환 스왑포인트/풋옵션 미결제약정/공매도 잔고"를 KOSPI·환율만 가지고 **소급 생성**하여 CSV에 씁니다. 저장된 뒤에는 당일 수집분과 **구분이 불가능**합니다.
- `save_and_load_history()`가 호출될 때마다 자동 실행되므로(L187), 대시보드를 열기만 해도 발동할 수 있습니다.
- **권장**: 백필 값에는 `_est` 접미사 컬럼을 쓰거나 `source` 컬럼으로 `collected` / `backfilled` 를 구분하고, 차트/표에서 백필 구간을 점선·회색으로 구분하십시오.

> ✅ **수정 완료**: 더 강한 방향으로 조치했습니다 — **역산 생성 로직을 통째로 삭제**하고 `ensure_metric_columns()` 로 교체했습니다. 이제 구형 CSV에는 컬럼만 추가되고 **값은 결측(NaN)** 으로 남으며, 화면에는 '데이터 없음'으로 표기되고 가중평균에서 제외됩니다. (구 함수명 `backfill_missing_metrics` 는 별칭으로 남겨 두었으나 더 이상 데이터를 생성하지 않습니다.)

### 🟡 5-3. `repair_missing_supply_data()` (L112-158)
- URL이 **구형 `.nhn` 엔드포인트**입니다(현재 네이버는 `.naver`). 실패하면 `except Exception: pass` (L143-144)로 완전히 침묵합니다.
- 수급이 0/0/0인 행을 발견하면 조용히 덮어쓰고 CSV를 저장합니다. 성공했는지 실패했는지 UI에 아무 표시가 없습니다.

> ✅ **수정 완료**: `.nhn` → `.naver` 로 교정, 실패 시 `st.warning` 으로 화면에 노출 후 원본 그대로 반환(덮어쓰기 안 함). 저장은 `.bak` 백업을 남기는 `_safe_write_history()` 를 사용합니다.

### 🟡 5-4. (L62) 백필 시작값 `df[col] = 0.5` — 계산 루프가 실패한 행은 "위험도 0.5(중립)"라는 그럴듯한 값이 남습니다.

> ✅ **수정 완료**: 5-2 조치로 `df[col] = 0.5` 초기화 자체가 사라졌습니다(결측은 NaN 유지).

---

## 6. `views/macro_view.py` (매크로 방공망 화면)

### 🔴 6-1. 실데이터가 없을 때 KOSPI 2500 / 환율 1350으로 위험점수를 계산 (L83-92)

```python
kospi_close = 2500.0
usd_close   = 1350.0
volatility  = 1.2
dist_from_high = 0.08
score = 50.0
```

CSV가 없거나 L133의 `except Exception as e: print(...)` 에 걸리면 `local_loaded=False`가 되고, L219-269가 **이 가짜 시세로 14개 지표와 종합 위험점수를 전부 계산**해 아파트 층수·AI 코멘트까지 정상적으로 렌더링합니다.
유일한 표시는 `data_source_log = "⚠️ 안전 모드"` → `st.info()` 회색 박스 한 줄입니다(L145, L366).
→ **권장**: `st.error("🚨 시장 데이터를 불러오지 못했습니다. 아래 수치는 표시하지 않습니다.")` 후 `st.stop()`. 숫자를 아예 그리지 마십시오.

> ✅ **수정 완료**: 권장안 그대로 구현. 하드코딩 폴백을 모두 삭제하고, 실데이터 로드 실패 시 `score=None` 을 반환 → 화면은 **빨간 `st.error` 배너 + `st.stop()`** 으로 위험점수·아파트 층수·지표표·AI 코멘트를 **하나도 그리지 않습니다.**

### 🔴 6-2. KOSPI/환율 대형 카드의 하드코딩 폴백 (L392-397)

```python
else:
    k_val = 2500.0
    u_val = 1350.0
```

이력이 비면 **46px 대형 폰트로 "2,500.00" 과 "1,350.00원"** 이 실제 시세처럼 표시됩니다. `format_val()`은 NaN만 "-"로 바꾸므로 이 값은 걸러지지 않습니다.
→ **권장**: `k_val = None` → 카드에 "데이터 없음 / 수집 실패" 표기.

> ✅ **수정 완료**: `k_val`/`u_val` 을 `None` 으로 두고 `format_val()` 이 `None`·NaN 을 모두 **"데이터 없음"** 으로 표기하도록 변경(폰트 크기도 자동 축소).

### 🔴 6-3. 정의되지 않은 변수로 인해 5일 모멘텀 계산이 항상 죽어 있음 (L162-171)

```python
if FDR_AVAILABLE and not local_loaded:
    try:
        if len(kospi_df) >= 6:      # ← kospi_df 는 이 함수 어디에도 정의되지 않음 (NameError)
            ...
    except Exception:
        pass                        # ← 조용히 삼킴
```

`kospi_df`는 존재하지 않는 변수입니다. 항상 `NameError`가 나고 `pass`로 삼켜져, `KOSPI_5D_Return` 지표는 **영원히 0.5(중립) 고정**입니다. 가중치 5점짜리 지표가 죽어 있는데 화면상으로는 정상 값처럼 보입니다.
→ **권장**: 죽은 블록을 제거하거나 실제 FDR 조회를 넣고, `except Exception: pass` 대신 로그+UI 경고.

> ✅ **수정 완료**: `kospi_df` 참조 블록을 삭제하고, **누적 이력 CSV에서 5영업일 전 종가를 실제로 조회**해 모멘텀을 산출하도록 재작성. 이력이 6행 미만이면 0.5(중립)를 넣지 않고 **해당 지표를 가중평균에서 제외**하며 표에 '데이터 없음'으로 표기합니다.

### 🟡 6-4. 컬럼 결측 시 중립값 대입 (L277-278, L309-310)
```python
else:
    sub_scores[item] = 50.0     # 위험도 0.5
    metrics_dict[item] = 0.5
```
CSV에 해당 지표 컬럼이 없으면 "위험도 0.5"라는 정상적으로 보이는 값이 표에 찍힙니다. → "N/A"로 표시하고 가중 평균에서 제외해야 합니다.

> ✅ **수정 완료**: `50.0` / `0.5` 대입을 제거하고 `None` 처리 → 표에 '데이터 없음' + 회색 표기, **가중평균 분모에서도 제외**(남은 가중치로 정규화), 상단에 "14개 중 n개 산출 불가" 경고. 결측 지표는 CSV 에도 기록하지 않습니다.

### 🟡 6-5. 관리자 수동 입력 경로에서도 변동성이 하드코딩 (L77-80)
```python
volatility = 1.2
dist_from_high = 0.08
sugeub_fetched = True
data_source_log = "✅ 동기화 완료 (관리자 입력)"
```
관리자가 KOSPI·환율·수급만 입력해도 변동성/낙폭은 상수가 쓰이는데, 상태 배지는 **초록색 "✅ 동기화 완료"** 입니다. 그리고 이 값으로 계산된 점수가 CSV에 영구 저장됩니다(L313).

> ✅ **수정 완료**: 관리자 입력 경로에서도 `volatility`/`dist_from_high` 를 `None` 으로 두고 **관련 4개 지표를 산출에서 제외**합니다. 배지 문구도 "⚠️ 관리자 수동 입력 (변동성·고점대비낙폭 미입력 → 해당 지표 제외)" 로 변경. 입력 폼의 기본값 `2500.0`/`1350.0` 도 제거하고 0 이하 값은 저장을 거부합니다.

### 🟡 6-6. 오래된 CSV를 "실시간 연결됨"으로 표기 (L322-323)
```python
if local_loaded:
    is_live_connected = True
```
파일이 몇 주 전 것이어도 초록색 `st.success` 로 표시됩니다. 화면 문구는 "실시간 수급 연동형"입니다. → 파일 mtime이 N일 이상이면 경고로 전환하십시오.

> ✅ **수정 완료**: 최신 데이터 일자가 **3일 이상 지났으면** 노란 경고 배너("⚠️ 최신 시장 데이터가 N일 전 기준입니다")를 띄우고 `is_live` 를 False 로 내려 초록 배지를 회수합니다.

### 🟡 6-7. 조회 화면이 DB를 씁니다 (L312-313)
`render_macro_page()`(읽기 전용이어야 함)가 `save_and_load_history()`를 호출해 CSV를 재작성합니다. SPEC §6 "표현 계층: UI만 담당, 데이터 가공 로직 절대 금지" 위반이며, 5-1의 이력 파괴 위험을 대시보드 접속만으로 유발할 수 있습니다.

> ✅ **수정 완료**: 조회 경로에서는 **읽기 전용 `_load_history_df()`** 만 호출하도록 변경. CSV 쓰기는 **관리자 수동 입력(override) 경로에서만** 발생합니다.

### ⚪ 6-8. 기타
- `FRIENDLY_NAMES`(L43)와 `friendly_names`(L181)가 문구까지 미묘하게 다른 중복 사전. 표에는 `FRIENDLY_NAMES`만 쓰이고 `friendly_names`는 죽은 코드입니다.
- `PYKRX_AVAILABLE`(L17-21)는 정의만 되고 사용되지 않습니다.
- L727-767 감사이력 탭이 *"[v1.2.0] 더미 데이터 제거 — 임의 디폴트값(2500, 1350) 삭제"* 라고 선언하지만, **6-1/6-2에서 보듯 2500·1350은 지금도 코드에 살아 있습니다.** 문서가 사실과 다릅니다.

> ✅ **수정 완료**: 중복 사전 `friendly_names`(죽은 코드) 삭제, 감사이력에 **v1.4.0 탭**을 추가해 이번 감사에서 실제로 제거한 항목을 5W1H로 기록했습니다(이제 2500/1350 은 코드에 존재하지 않습니다).
> ⏸️ **보류**: `PYKRX_AVAILABLE` 미사용 변수는 향후 pykrx 도입 여지가 있어 그대로 두었습니다(무해).

---

## 7. `views/pegy_view.py` (밸류에이션 화면)

### 🔴 7-1. 스냅샷이 없어도 "실시간 중앙값"이 표시됨 (L303-309)

```python
calc_f_per  = round(...) if f_per_list else 10.4
calc_growth = round(...) if growth_list else 14.2
calc_pegy   = round(...) if pegy_list  else 0.73
else:
    calc_f_per, calc_growth, calc_pegy = 10.4, 14.2, 0.73
```
그리고 L312-314에서 이 숫자에 **"KOSPI 200 실시간 중앙값" / "실시간 중앙값 컨센서스"** 라는 라벨이 붙어 `st.metric`으로 표시됩니다. 데이터가 0건이어도 세 개의 그럴듯한 숫자가 뜹니다.
→ **권장**: `st.metric(..., "데이터 없음")` 또는 `st.error` 후 return.

> ✅ **수정 완료**: 상수 3개를 제거하고 표본이 없으면 `None` → `st.metric(..., "데이터 없음")`. 라벨도 "KOSPI 200 실시간 중앙값" → **"n개 종목 실측 중앙값"** 으로 정정하고, 일부가 산출 불가면 경고 배너를 띄웁니다. 종목이 0건이면 `st.error` 후 `st.stop()`.

### 🔴 7-2. 스냅샷 로드 실패 시 "마지막 동기화 = 지금" (L45-46, L68)

```python
now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
return {"last_updated_at": now_str, "status": "BACKUP"}, []
```
JSON이 없거나 깨져도 배너에는 **"📅 마지막 동기화: (현재시각) (장 마감 반영)"** 이 찍힙니다(L237). `status: "BACKUP"` 은 **UI 어디에서도 읽지 않습니다.** 가장 최근 수집 실패를 최신 성공으로 오인시키는 구조입니다.
→ **권장**: `last_updated_at = None` 으로 두고 배너를 "🚨 스냅샷 로드 실패"로 교체. `status`를 반드시 화면에 반영.

> ✅ **수정 완료**: 권장안 그대로 구현(`last_updated_at=None`, `status="LOAD_FAILED"`, `load_error` 사유 포함). 화면은 `st.error` 후 `st.stop()`. 정상 로드 시에도 **`status` 를 배너에 표시**하고, 마지막 수집이 **24시간 이상 지났으면 빨간 staleness 경고**를 띄웁니다.

### 🔴 7-3. 퀀트 스코어 기본값 80점 (L611)

```python
<b>{s.get('quant_score', 80)}점</b> / 100점
```
`quant_score` 키가 없는 종목은 **80점**으로 표시됩니다. 0점이나 "N/A"가 아니라 우수한 점수입니다.
→ **권장**: `s.get('quant_score')` 가 None이면 "측정 불가" 배지로 대체.

> ✅ **수정 완료**: 기본값 80 제거. `None` 이면 **"측정 불가 (데이터 없음)"**, 값이 있으면 `{점수}점 / {score_max}점` 으로 **실제 만점**을 함께 표기하고 툴팁에 배점 제외 항목을 명시합니다.

### 🟡 7-4. 조용한 예외 4곳
L19-20, L56-57 (`except: pass` → 빈 리스트 반환 → 7-1의 하드코딩 요약값 발동), L271-272, L293-294 (`except Exception as e: pass`).

> ✅ **수정 완료**: 4곳 모두 `print` + `st.warning`/`st.error` 로 실패를 노출하도록 변경(요약 히스토리 로드 실패, 관리자 Excel 변환 실패 포함).

### 🟡 7-5. 화면 렌더링 중 200종목 크롤링 (L12-13, L28-31)
JSON이 없으면 페이지 렌더 도중 `run_kospi200_collector()`를 호출합니다. 종목당 2~3초 슬립이므로 **10분 이상 블로킹**되며 Streamlit Cloud에서는 타임아웃 → 7-2의 가짜 배너로 이어집니다.

> ✅ **수정 완료**: 렌더링 중 수집기 실행을 **완전히 제거**하고, 스냅샷이 없으면 "자동 수집(GitHub Actions)이 정상 동작했는지 확인해 주세요" 안내와 함께 즉시 중단합니다.

### 🟡 7-6. `is_valid=False` 는 화면에 반영되지 않음 (L453)
카드 분기는 `is_unverified`만 봅니다. `is_valid=False`인 종목도 (guardrail이 True로 덮지 않은 경우) 그대로 정상 카드로 그려집니다.

> ✅ **수정 완료**: 카드 분기 조건을 `is_unverified or not is_valid` 로 확장하고, **데이터 미수집 전용 회색 카드 테마**를 새로 추가해 실패 사유를 그대로 노출합니다.

### ⚪ 7-7. 죽은 코드
`get_kospi200_pegy_data()`(L8-21)는 어디서도 호출되지 않습니다. `import random`(L3)도 미사용.

> ✅ **수정 완료**: 미사용 `import random` 과 죽은 함수 `get_kospi200_pegy_data()` 를 제거했습니다(이 함수도 렌더 중 수집기를 실행하는 위험 코드였습니다).

---

## 8. `utils/macro_ai.py`

- **🟡 8-1 (L96-100)**: AI 호출 실패 시 **이미 값이 있으면 전일 코멘트를 그대로 유지**합니다. `commentary_data["date"]`만 오늘로 갱신되므로(L102), 대시보드는 어제(혹은 3일 전) 코멘트를 **오늘의 AI 분석**으로 표시합니다. 실패 흔적은 stdout뿐입니다.
  → 코멘트별로 `generated_at`을 저장하고, 오늘 것이 아니면 "⚠️ (전일 코멘트)" 라고 표기하십시오.
  > ✅ **수정 완료**: `comment_dates` 맵을 JSON에 추가하고 **생성에 성공한 코멘트만** 오늘 날짜를 기록합니다. 대시보드는 오늘 것이 아니면 `⚠️ (YYYY-MM-DD 생성 코멘트)`, 날짜가 없으면 `ℹ️ (생성 일자 미기록)` 을 앞에 붙여 표시합니다.
- **🟡 8-2 (L66-68)**: "이미 오늘 코멘트가 있습니다"를 print만 하고 `return` 하지 않아, 실제로는 매번 14회 재호출합니다(API 비용/쿼터).
  > ✅ **수정 완료**: 해당 분기에서 즉시 `return` 하도록 수정.
- **⚪ 8-3**: `requirements.txt`에 `google-generativeai`가 없습니다. 따라서 **GitHub Actions에서 AI 코멘트 생성은 항상 ImportError로 건너뜁니다**(`scrape_daily.py:426-427`에서 조용히 흡수). 화면에는 `"AI 코멘트가 준비되지 않았습니다."`(macro_view L581)가 뜨므로 그나마 눈에 보이는 편입니다.
  > ✅ **수정 완료**: 9-4와 함께 `requirements.txt` 에 추가.

---

## 9. 스케줄러 — `scheduler.py`, `utils/scheduler.py`, `.github/workflows/scrape.yml`

### 🔴 9-1. 두 스케줄러 모두 존재하지 않는 파일을 호출

```python
# scheduler.py L28
script_path = os.path.join(BASE_DIR, "collector_kospi200_2.py")     # ← 그런 파일 없음

# utils/scheduler.py L35
from collector_kospi200_2 import run_kospi200_collector             # ← ImportError
```

- 실제 파일명은 `collector_kospi200.py` 입니다.
- `scheduler.py`는 subprocess가 비정상 종료 코드를 뱉으므로 `scheduler.log`에만 에러가 남고, `utils/scheduler.py`는 `except Exception as e: print(...)` 로 서버 콘솔에만 남습니다. **대시보드에는 아무 표시가 없습니다.**
- 결과: `data/kospi200_pegy_latest.json`은 자동 갱신되지 않고, 화면은 오래된 스냅샷을 "마지막 동기화" 배너와 함께 정상처럼 보여줍니다(실제로 스냅샷 시각은 2026-08-04 02:33, 오늘은 2026-08-05).
- **권장**: 파일명 수정 + 스냅샷의 `last_updated_at`이 N시간 이상 지났으면 대시보드 상단에 빨간 경고 배너를 띄우는 **staleness 체크** 추가.

> ✅ **수정 완료**: 두 파일 모두 `collector_kospi200` 으로 교정(+ `scheduler.py` 는 스크립트 존재 여부까지 확인). **staleness 체크**도 구현했습니다 — 밸류에이션 화면은 24시간 초과 시 빨간 배너, 매크로 화면은 3일 초과 시 노란 배너.

### 🟡 9-2. 수집 경로가 3개로 중복
`.github/workflows/scrape.yml`(정상 동작, 파일명 올바름) / `scheduler.py`(로컬 배치, 깨짐) / `utils/scheduler.py`(Streamlit 프로세스 내 스레드, 깨짐). 셋이 동시에 살아나면 같은 CSV/JSON에 경쟁적으로 씁니다. **하나만 남기십시오** (Actions 권장).

> ✅ **수정 완료(부분)**: `utils/scheduler.py` 의 앱 내장 스케줄러를 **기본 비활성화**했습니다(`ENABLE_INAPP_SCHEDULER=1` 일 때만 동작). 정식 경로는 GitHub Actions 하나입니다.
> ⏸️ **보류**: `scheduler.py`(로컬 배치) 파일 자체의 삭제는 오너 승인이 필요해 남겨 두었습니다 — 로컬에서 수동 실행할 때만 동작하므로 자동 경합은 발생하지 않습니다.

### 🟡 9-3. Streamlit 프로세스 안에서 크롤러 실행
`visiblehand.py:92-96` → `start_scheduler_thread()`. `@st.cache_resource`는 프로세스 단위이므로 워커가 여러 개면 스레드도 여러 개 뜹니다. 웹 렌더링 프로세스가 CSV를 쓰는 구조는 5-1의 이력 파괴와 결합하면 위험합니다.

> ✅ **수정 완료**: 9-2 조치(기본 비활성화)로 스레드가 뜨지 않습니다. 여기에 6-7(조회 화면 쓰기 금지) + 5-1(예외 시 쓰기 금지) 수정이 더해져 웹 프로세스가 이력을 파괴할 경로가 사라졌습니다.

### 🟡 9-4. `requirements.txt` 누락 패키지
`yfinance`, `google-generativeai`, `google-api-python-client`, `google-auth-oauthlib`, `pykrx` 가 빠져 있습니다. 이들 임포트는 모두 `try/except`로 감싸져 있어 **기능이 조용히 꺼집니다**(교차검증 미수행, AI 코멘트 미생성, 드라이브 백업 미실행). 특히 `HAS_YFINANCE=False`이면 `per_discrepancy`가 전 종목 False(=이상 없음)로 기록됩니다.

> ✅ **수정 완료**: `yfinance`, `google-generativeai`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` 를 `requirements.txt` 에 추가(주석 포함). `per_discrepancy` 는 2-10 수정으로 **미수행이면 `None`** 이 되어 '이상 없음'과 구분됩니다. (`pykrx` 는 실제로 사용되지 않아 추가하지 않았습니다.)

---

## 10. 개발 잔재 파일 (실행되면 실데이터를 덮어씀)

| 파일 | 등급 | 문제 |
|------|------|------|
| `patch_macro.py` | 🟡 | 실행하면 `views/macro_view.py`를 **하드코딩된 42개 캔 문구(INDICATOR_AI_COMMENTS)로 갈아엎습니다.** 지금은 실제 AI 코멘트(`data/macro_commentary.json`)를 쓰고 있는데, 이 스크립트를 다시 돌리면 "가짜 코멘트"로 회귀합니다. git에 추적 중. |
| `patch.py` | 🟡 | 실행하면 `scrape_daily.py`를 **더 오래된 코드 블록으로 되돌립니다**(현재 파일의 `.ffill()` 수정본이 사라짐). 소스 파일을 직접 rewrite하는 스크립트가 저장소에 남아 있는 것 자체가 위험합니다. |
| `update_snapshot.py` | 🟡 | 이미 가공된 스냅샷 행을 **원본(raw)인 척 다시 `enrich_quant_metrics()`에 투입**하고, 삼성전자·SK하이닉스 2종목만 하드코딩(L12)해서 프로덕션 JSON을 덮어씁니다. `last_updated_at`은 갱신하지 않아 "언제 손댄 파일인지" 알 수 없게 됩니다. |
| `archive/init_history.py` | 🟡 | `HISTORY_FILE = "market_history.csv"` **상대경로**. 프로젝트 루트에서 실행하면 **실제 이력 파일을 2026-06~07 생성 데이터로 덮어씁니다.** (`archive/`는 .gitignore 처리되어 있어 배포에는 포함되지 않음) |
| `archive/recalculate_history.py`, `archive/patch_fridays.py` | ⚪ | 절대경로가 `archive/` 기준이라 현재는 무해하나, 루트로 옮기면 전체 점수를 소급 재계산해 덮어씁니다. |
| `archive/test_harness.py` | ⚪ | SPEC §6·§8·§9가 "반드시 실행하라"고 지시하는 파일인데 **.gitignore된 archive/에 들어가 있습니다.** SPEC의 검증 절차가 실행 불가 상태입니다. |
| `templates/test_dashboard.html` | 🟡 | 가짜 종목 수치(25.21배 / 3,792원 / +24.9% 상승여력 등)가 박힌 UI 샌드박스. **git에 추적 중이고 GitHub Pages(CNAME `visiblehand.co.kr`)로 배포되므로 `https://visiblehand.co.kr/templates/test_dashboard.html` 로 외부에서 접근 가능**합니다. 실제 리포트로 오인될 수 있습니다. |
| `error.log`, `output.log`, `git_history_target.txt`(279KB) | ⚪ | 저장소에 커밋되어 있습니다. `git_history_target.txt`에는 커밋 히스토리 전문과 작성자 이메일이 들어 있습니다(자격증명은 없음 — 확인함). |

> ✅ **수정 완료(실행 차단 가드)**: 파일 삭제는 **오너 승인이 필요**하여 하지 않았고, 대신 **실수로 실행되어 실데이터를 덮어쓰는 것을 막는 가드**를 넣었습니다.
> - `patch.py`, `patch_macro.py` → `ALLOW_DESTRUCTIVE_PATCH=1` 없이 실행하면 경고 출력 후 `sys.exit(1)`
> - `update_snapshot.py` → `ALLOW_SNAPSHOT_OVERWRITE=1` 없이 실행 차단
> - `archive/init_history.py` → `ALLOW_HISTORY_REINIT=1` 없이 실행 차단
> - `templates/test_dashboard.html` → `<title>` 을 **"[테스트용 가짜 데이터] … 실제 리포트 아님"** 으로 바꾸고, `noindex` 메타태그 + 페이지 최상단에 **빨간 경고 배너**("표시된 모든 수치는 임의의 예시이며 투자 판단에 사용 금지") 삽입
>
> ⏸️ **보류(오너 결정 필요 — 삭제 권한)**: 아래 파일들은 **저장소에서 제거하는 것을 권장**하지만, 이 환경에서는 파일 삭제에 별도 승인이 필요해 남겨 두었습니다.
> `patch.py`, `patch_macro.py`, `update_snapshot.py`, `templates/test_dashboard.html`, `error.log`, `output.log`, `git_history_target.txt`
> (삭제해도 대시보드 동작에는 전혀 영향이 없습니다. 특히 `templates/test_dashboard.html` 은 GitHub Pages 로 외부 공개되므로 삭제를 권장합니다.)
> ⏸️ **보류**: `archive/test_harness.py` 를 archive 밖으로 복구하는 건은 SPEC 검증 절차 재설계가 필요해 보류했습니다. 대신 `tests/test_quant.py` 를 실제 동작에 맞게 재작성해 **지금 바로 실행 가능한 검증 스위트**를 확보했습니다(§11 참조).

---

## 11. `tests/test_quant.py`

- **🟡 11-1**: 테스트가 **현재 코드와 맞지 않아 반드시 실패**합니다.
  ```python
  assert res1['g_eff'] == 20.0      # guardrail은 g_eff를 계산하지 않음 → KeyError
  assert res2['f_pegy'] == 99.0     # guardrail은 f_pegy를 만들지 않음 → KeyError
  assert res2['f_target'] == 21000.0
  ```
  현재 `apply_valuation_guardrail()`은 `g_eff`를 **입력에서 읽기만** 하고(L48), `f_pegy`/`f_target`은 건드리지 않습니다. 즉 마지막의 *"🎉 모든 수식 및 방공망 테스트 통과!"* 는 도달 불가능한 문구입니다.
- 안전망이 있다고 착각하게 만드는 테스트는 없는 것보다 위험합니다. 실제 로직에 맞춰 다시 쓰거나 삭제하십시오.

> ✅ **수정 완료**: `tests/test_quant.py` 를 **실제 코드 동작에 맞춰 전면 재작성**하고 실행 성공을 확인했습니다(8개 케이스 전부 통과).
> 검증 항목: ① guardrail 정상 통과 ② **상위 검증 실패를 guardrail 이 되돌리지 않는지** ③ 필수값 결측 차단 ④ 상장주식수 범위 검증 ⑤ 스코어링 배점 제외(만점 70점) ⑥ 변동성 미수집 시 감점·가점 모두 없음(만점 95점) ⑦ 측정 불가 시 `quant_score=None` ⑧ `raw_period` 없으면 1단계 검증 실패.
> 실행: `python tests/test_quant.py`

---

## 12. 🔐 보안 (별도 카테고리)

### 🔴 12-1. 관리자 비밀번호 평문이 소스 주석에 있음 — `views/admin_view.py:18-19`

```python
# ***REMOVED-OLD-ADMIN-PASSWORD*** 의 SHA-256 해시값
stored_hash = "***REMOVED-OLD-PASSWORD-HASH***"
```

해시를 써도 **바로 위 줄에 평문이 적혀 있으면 의미가 없습니다.** 이 파일은 공개 저장소(`github.com/moonbear135/visible-hand-dashboard`)에 커밋되어 있고, git 히스토리(커밋 `80bb132`)에도 남아 있습니다.
→ **즉시 조치**: ① 비밀번호 변경, ② 주석 삭제, ③ `st.secrets["ADMIN_PASSWORD_HASH"]` 또는 환경변수로 이전, ④ 솔트 추가(가능하면 `bcrypt`), ⑤ 히스토리 정리(`git filter-repo`)는 선택.

> ✅ **수정 완료**: 평문 주석과 **하드코딩된 해시값을 모두 삭제**하고, `os.environ["ADMIN_PASSWORD_HASH"]` → `st.secrets.get("ADMIN_PASSWORD_HASH")` 순으로 읽도록 변경(GEMINI_API_KEY와 동일 패턴). 비밀값이 설정되지 않으면 **관리자 모드는 아무도 열 수 없습니다**(기본 해시 폴백 없음). 새 비밀번호 생성·등록 절차는 `views/admin_view.py` 상단 `TODO(오너 조치 필요)` 주석에 단계별로 적어 두었습니다.
> ⏸️ **보류(오너 조치 필요)**: ① **새 비밀번호 설정은 오너가 직접** 해야 합니다(감사자가 비밀번호를 정하지 않았습니다). ② 기존 비밀번호는 git 히스토리에 남아 있으므로 **유출된 것으로 간주**해야 하며, `git filter-repo` 히스토리 정리는 저장소 재작성이 필요해 보류했습니다. ③ bcrypt 솔트 도입은 의존성 추가가 필요해 보류(현행 SHA-256 + `hmac.compare_digest` 유지).

### ✅ 12-2. 자격증명 파일은 안전
`credentials.json`, `token.json`, `service_account.json` 은 `.gitignore`에 포함되어 있고, `git rev-list --all --objects` 확인 결과 **한 번도 커밋된 적이 없습니다.** 정상입니다.

### ⚪ 12-3. GEMINI_API_KEY는 GitHub Secrets로 올바르게 주입되고 있습니다(`scrape.yml:45`). 소스에 하드코딩된 API 키는 없습니다.

---

## 13. 우선순위 제안 (수정 순서)

**1단계 — "거짓말하는 숫자"부터 끄기 (반나절)**
1. `collector_kospi200.py:348` 코드해시 변동성 제거 → `"❔ 데이터 없음"` + 벌점 미적용
2. `utils/guardrail.py:65` 무조건 `is_valid=True` 제거
3. `views/pegy_view.py:611` `quant_score` 기본값 80 제거
4. `views/macro_view.py:392-397`, `83-92` 2500/1350 제거 → `st.error` + `st.stop()`
5. `views/pegy_view.py:45,68,303-309` 스냅샷 실패 시 현재시각·10.4/14.2/0.73 제거
6. `views/admin_view.py:18` 비밀번호 주석 삭제 + 비밀번호 변경

**2단계 — 실패를 보이게 만들기 (1~2일)**
7. `scheduler.py`, `utils/scheduler.py` 의 `collector_kospi200_2` 오타 수정(또는 둘 다 삭제하고 Actions만 사용)
8. 스냅샷/CSV **staleness 배너**: `last_updated_at`이 24시간 이상 지났으면 대시보드 최상단에 빨간 경고
9. `market_history.csv`에 `data_quality` 컬럼(OK / FFILL / BACKFILL / MANUAL) 추가 후 표·차트에 반영
10. `utils/db.py:206-210` 예외 시 CSV 덮어쓰기 금지

**3단계 — 파생 지표 정직하게 표기 (설계 판단 필요)**
11. `f_roe`/`roic`/`growth`/`buyback_yield`/14개 매크로 지표에 "추정 프록시" 라벨 부여, 또는 실데이터 수집으로 교체
12. `outstanding_shares` 범위 검증 추가 (현재 197/200 오류)
13. `patch.py`, `patch_macro.py`, `update_snapshot.py`, `templates/test_dashboard.html` 저장소에서 제거
14. SPEC §5-2(목표가 캡)·§5-4(역성장 처리)와 코드 동기화, `test_harness.py`를 archive에서 복구

---

## 14. ✅ 최종 수정 요약 (2026-08-05 후속 패스)

### 수정된 파일 (13개)

| 파일 | 핵심 변경 |
|------|-----------|
| `collector_kospi200.py` | 가짜 변동성(code_hash) → 실측 20일 표준편차 / f_roe·roic → None / growth → 실측 컨센서스EPS 증감률 / 자사주 2.5% 삭제 / 상장주식수 범위 검증 / PER·EPS 대체값·역산 삭제 / SPEC §5-2 목표가 캡 적용 / status SUCCESS·DEGRADED 구분 |
| `utils/guardrail.py` | 무조건 `is_valid=True` 제거 → 상위 판정과 AND 결합, 동어반복 배당검증 → 상장주식수 범위 검증 |
| `utils/scoring.py` | 데이터 없는 항목은 배점에서 제외(`score_max`·`excluded_items` 반환), 캡도 만점 대비 비례 환산 |
| `utils/data_validator.py` | `raw_period` 기본값(자기 자신 비교) 제거, 단일문자 키워드 `\b` 경계 처리, 교차검증 미수행 명시 |
| `utils/db.py` | 예외 시 이력 덮어쓰기 **금지**(+`.bak` 백업), 14개 지표 역산 백필 로직 삭제, `.nhn`→`.naver` |
| `utils/scheduler.py` | `collector_kospi200_2` → `collector_kospi200`, 앱 내장 스케줄러 기본 비활성화 |
| `scheduler.py` | `collector_kospi200_2.py` → `collector_kospi200.py` + 파일 존재 확인 |
| `scrape_daily.py` | 시드값(1.2/0.08/0.5) 제거 후 실패 시 `raise`, Forward Fill·`.ffill()` 제거, PERIOD_KEYWORDS 사본 제거 |
| `views/macro_view.py` | KOSPI 2500·환율 1350 폴백 삭제 + 실패 시 `st.error`+`st.stop()`, 결측 지표 가중평균 제외, staleness/표본부족 경고, 프록시 고지, 죽은 5일모멘텀 블록 재작성 |
| `views/pegy_view.py` | 스냅샷 실패 시 현재시각 위장 제거, 요약 상수(10.4/14.2/0.73) 제거, quant_score 기본값 80 제거, `is_valid=False` 카드 마스킹, 렌더 중 크롤링 제거, None 안전 표기(`fmt_num`) |
| `views/admin_view.py` | 평문 비밀번호 주석 + 하드코딩 해시 삭제 → 환경변수/Secrets 로 이전, 입력 폼 기본값 2500/1350 제거 |
| `utils/macro_ai.py` | 오늘 코멘트 있으면 즉시 return(API 낭비 차단), 코멘트별 생성일자 기록 |
| `tests/test_quant.py` | 실제 로직에 맞게 전면 재작성 (8케이스 통과) |
| `requirements.txt` | yfinance / google-generativeai / google-api-python-client 등 누락 패키지 추가 |
| `patch.py`·`patch_macro.py`·`update_snapshot.py`·`archive/init_history.py`·`templates/test_dashboard.html` | 실행 차단 가드 및 가짜 데이터 경고 배너 |

### 사용자 화면에서 달라지는 점 (정상 동작입니다)

- Forward ROE / ROIC 는 **모든 종목에서 "데이터 없음"** 으로 표시됩니다 → 실제로 수집한 적이 없는 값이기 때문입니다. 퀀트 스코어 만점도 100점이 아니라 **70점(또는 95점)** 으로 표기됩니다.
- 주주환원율은 **배당수익률만** 반영되어 수치가 낮아집니다(자사주 2.5% 가정 제거).
- 상장주식수를 못 읽은 종목은 "총 0억원" 대신 **"데이터 없음 (상장주식수 미확보)"** 로 표시됩니다.
- 변동성 배지는 실제 수치(예: `🟢 정상 (1.1%)`)가 붙고, 조회 실패 시 `❔ 변동성 데이터 없음` + 감점 없음.
- 데이터 수집이 실패한 날에는 화면이 **빈 채로 빨간 오류 배너**만 뜹니다 — 가짜 숫자를 그리지 않기 위한 의도된 동작입니다.

### 검증 방법

```bash
python tests/test_quant.py     # 8개 케이스 전부 PASS 확인
python collector_kospi200.py   # (네트워크 필요) 수집 후 data/kospi200_pegy_latest.json 의 status 확인
```

