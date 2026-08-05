# 🏗️ 보이는 손 (The Visible Hand) — 엔지니어링 명세서

> **이 문서는 AI 모델(Antigravity, Gemini, ChatGPT 등)에 관계없이**
> **크롤링·가공·검증 파이프라인의 무결성을 보장하기 위한 불변 규칙서입니다.**
> **코드를 수정하는 AI 또는 개발자는 반드시 이 문서를 먼저 읽어야 합니다.**

---

## 0. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **프로젝트명** | 잘 보면 보이는 손 (The Visible Hand) |
| **목적** | KOSPI 200 시가총액 상위 종목의 퀀트 밸류에이션(PEGY) 대시보드 |
| **프론트엔드** | Streamlit (`visiblehand.py`) |
| **데이터 수집** | 네이버 증권 웹 스크래핑 (`collector_kospi200.py`, `scrape_daily.py`) |
| **검증 파이프라인** | 3단계 DataValidator (`utils/data_validator.py`) |
| **배포** | GitHub Pages (정적 JSON) + Streamlit Cloud |

---

## 0-1. 🚫 코딩 원칙: 하드코딩 및 더미 데이터 금지 (최우선 규칙)

> [!CAUTION]
> **이 프로젝트의 제1원칙입니다. 아래 다른 모든 규칙보다 우선합니다.**
> AI(Gemini, Claude, ChatGPT 등)든 사람이든, 이 저장소의 코드를 수정하는 누구나 반드시 지켜야 합니다.

### 원칙 선언

**실데이터 수집에 실패했을 때, 그럴듯해 보이는 하드코딩·더미·기본값으로 조용히 메우는 것을 절대 금지합니다.**

에러는 보이면 고칠 수 있습니다. 하지만 가짜 데이터가 실데이터인 척 시스템에 남으면
**어디가 잘못됐는지 영원히 알 수 없습니다.** 이것이 이 프로젝트에서 가장 심각한 결함 유형입니다.

수집/파싱/계산에 실패하면 코드는 반드시 다음 셋 중 하나를 해야 합니다.

1. **명확한 예외를 발생시켜 중단** — `raise RuntimeError("...")` (배치 수집기의 기본 동작)
2. **해당 데이터 포인트를 `None` 으로 두고 UI에 "데이터 없음 / 수집 실패" 로 표시** (개별 종목·지표 단위)
3. **대시보드 상단에 눈에 띄는 경고 배너 노출** — `st.error()` / 빨간 배지 (전체 화면 단위)

### ⛔ "로그만 남기는 것"은 조치가 아닙니다

`print("⚠️ 수집 실패")` 는 **GitHub Actions 로그나 서버 콘솔에만** 남습니다.
대시보드를 보는 사람은 아무것도 알 수 없습니다.
**실패 사실은 반드시 사용자가 보는 화면까지 도달해야 합니다.**

마찬가지로 아래 패턴도 전부 금지입니다.

- `except Exception: pass` — 예외를 삼켜서 실패와 정상을 구분 불가능하게 만듦
- 실패 시 "중립값"(0.5, 50점, 평균값) 대입 — 정상처럼 보이는 숫자가 됨
- 실패 시 이전 값 유지(Forward Fill)를 **표시 없이** 하는 것 — 표시하면 허용
- JSON/CSV에 `status: "SUCCESS"` 를 조건 없이 기록하는 것

---

### 예시 1 — 계산할 수 없는 지표를 지어내지 말 것

이 프로젝트에서 실제로 발견된 사례입니다. `collector_kospi200.py` 의 변동성 판정이
**종목코드 글자 합의 나머지 연산**으로 되어 있었고, 200종목 중 78종목이 이 가짜 값 때문에
PEGY에 1.18배 벌점을 받고 빨간 배지를 달고 있었습니다.

```python
# ❌ 절대 금지 — 주가를 보지도 않고 변동성을 "생성"함
code_hash = sum(ord(c) for c in code)
vol = "🟢 정상" if (code_hash % 3 != 0) else "⚡ 변동성 보정 중"
vol_penalty = 1.18 if "보정" in vol else 1.0

# ✅ 실제 값을 계산하거나, 없으면 지표를 비활성화하고 UI에 명시
returns = price_series.pct_change().dropna()
if len(returns) < 20:
    vol = "❔ 변동성 데이터 없음"      # 카드에 회색으로 표시
    vol_penalty = 1.0                  # 감점/가점 어느 쪽도 주지 않음
else:
    vol_std = float(returns.tail(20).std()) * 100
    vol = "🟢 정상" if vol_std < 2.0 else "⚡ 변동성 확대"
    vol_penalty = 1.18 if vol_std >= 2.0 else 1.0
```

---

### 예시 2 — 파싱 실패를 "평균적인 숫자"로 메우지 말 것

`collector_kospi200.py` 는 PER/EPS/ROE 파싱에 실패하면 `12.5`, `8.5`, `6.8` 같은
그럴듯한 상수를 넣고 있었습니다. 그 결과 현재 스냅샷에서 **`f_roe = 8.5` 인 종목이 27개,
`roic = 6.8` 인 종목이 30개** 이며, 화면 툴팁은 이를 "애널리스트 예상치"라고 설명합니다.

```python
# ❌ 절대 금지 — 실패한 값을 평균치로 채우면 검증도 통과해버림
t_per = 12.5                                  # PER 파싱 실패 시
t_eps = int(price / t_per)                    # EPS를 주가/PER로 역산 → 산티체크 항상 통과
f_roe = round(t_roe * 1.12, 1) if t_roe > 0 else 8.5
roic  = round(t_roe * 0.88, 1) if t_roe > 0 else 6.8

# ✅ 값이 없으면 None으로 두고, 종목 자체를 "검증 대기" 마스크로 차단
if not n_t_per or n_t_per <= 0:
    stock_dict["is_unverified"] = True
    stock_dict["unverified_reason"] = "PER 수집 실패 (네이버 aside_invest_info 파싱 불가)"
    stock_dict["t_per"] = None
    return stock_dict          # 점수 매기지 않음. pegy_view의 회색 마스크 카드로 렌더링됨
```

> **부가 규칙**: 파싱 결과에는 반드시 **범위 검증(sanity range check)** 을 붙이십시오.
> 예: `상장주식수`가 100만 주 미만이면 파싱 실패로 간주하고 `raise`.
> (현재 200종목 중 197종목의 `outstanding_shares`가 46, 51, 79 같은 값으로 깨져 있는데
> 아무 검증이 없어 166종목이 주주환원 총액을 "총 0억원"으로 표시하고 있습니다.)

### 예시 2-보충 — 2026-08-05 추가: 대수적 역산("계산값") 허용 예외

> [!IMPORTANT]
> 위 예시 2의 `t_eps = int(price / t_per)` 금지는 여전히 원칙적으로 유효합니다.
> 다만 오너 승인 하에, **아래 조건을 전부 만족할 때만** 예외적으로 대수적 역산을 허용합니다.

**허용 조건 (전부 충족해야 함)**

1. **다른 어떤 출처로도 그 값을 실측할 수 없을 때만.** 실측 시도가 먼저이고, 계산은 항상 최후 수단입니다.
2. **미래를 추정/예측하지 않는, 순수 사칙연산일 것.** 이미 확정된 실측값 2개로부터 나머지 1개를 대수적으로 유도하는 경우만 해당합니다 (예: `EPS = 가격 ÷ PER`). 성장률 추정, 미래 실적 전망치처럼 **가정이 들어가는 값은 이 예외에 해당하지 않으며 여전히 절대 금지**입니다.
3. **역산에 쓰이는 입력값 자체가 실측값이어야 함.** 예시 2의 금지 사례(`t_per = 12.5` 라는 가짜 상수에서 역산)처럼, 가짜/기본값으로부터 역산하는 것은 여전히 금지입니다. 입력값 중 하나라도 하드코딩·추정치이면 이 예외를 쓸 수 없습니다.
4. **반드시 화면과 데이터에 "계산값" 마크를 표시할 것.** 실측값과 절대 구분 없이 섞으면 안 됩니다. 필드명에 `_calculated` 플래그 또는 `_source` 값(예: `"calculated_price_div_per"`)을 남기고, UI에는 실측 배지와 다른 별도 배지(예: "🧮 계산값")를 붙입니다.

**적용 사례**: `collector_kospi200.py`의 Trailing EPS — 네이버 상세페이지 파싱은 실패했지만 Trailing PER은 시총순위표(2차 출처)에서 실측되었고 주가도 실측값일 때, `EPS = 가격 ÷ PER` 로 역산하고 `t_eps_source = "calculated_price_div_per"`, `t_eps_calculated = True` 로 마킹합니다. (Forward EPS·성장률처럼 **미래 추정이 필요한 값에는 이 예외를 적용하지 않습니다** — 그런 값은 실측 컨센서스가 없으면 계속 "데이터 없음"으로 둡니다.)

### 예시 2-보충2 — 2026-08-05 추가: 결측 데이터는 "종목 전체 차단"이 아니라 "해당 섹션만 마스킹"

> [!IMPORTANT]
> 네이버가 애널리스트 컨센서스(추정 PER/EPS)를 제공하지 않는 종목이 KOSPI 200 중 다수 존재합니다.
> 이건 정상적으로 흔한 일(증권사 커버리지 부족)이지, 수집 파이프라인의 결함이 아닙니다.
> **Forward(미래 추정) 데이터가 없다고 해서 정상적으로 수집된 Trailing(과거 실적) 데이터까지
> 통째로 "데이터 없음" 카드로 묻어버리지 않습니다.** 대신:
>
> - `utils/guardrail.py`: Forward 전용 필드(`f_per`/`f_eps`/`growth`)가 없으면 `is_valid`를 `False`로 꺾지 않고, `forward_data_missing = True` 플래그만 남깁니다. 종목을 차단하는 필수 조건은 이제 `price` 하나뿐입니다.
> - `utils/scoring.py`: `forward_available` 여부에 따라 PEGY(35점)만 배점에서 제외하고, 자본효율성·배당·Trailing안정성·변동성 점수는 정상 산출합니다. 전용 배지 `"🔵 Trailing만 검증됨 (Forward 데이터 없음)"`를 부여합니다.
> - `views/pegy_view.py`: 종목 카드 전체는 정상 렌더링하고, **"🚀 Forward" 섹션 하나만** 🔒 마스크 패널로 대체합니다 (Trailing 섹션은 그대로 노출).
>
> 이 패턴(전체 차단 대신 결측된 섹션만 마스킹 + 반드시 이유를 명시)은 이후 다른 화면에서도
> "일부 지표만 없는" 상황에 동일하게 적용하는 것을 권장합니다.

**적용 사례 1-보충(2026-08-06) — 배당 필수 업종 DPS=0 케이스도 같은 원칙으로 완화**: `utils/guardrail.py`는
리츠/인프라/금융지주 등 배당 필수 업종인데 DPS·배당수익률이 모두 0으로 수집되면, 예전엔 `is_unverified=True`로
종목 전체를 차단했습니다. 오너 지적(2026-08-06): "국내 상장사는 아직 주주환원율이 높지 않고 실제로 배당을
전혀 안 주는 곳도 많아서, 이 조건만으로 과거 지표까지 못 믿게 막는 건 과하다." → 종목 전체 차단 대신
`dividend_data_unverified = True` + `dividend_unverified_reason` 플래그만 남기고(`is_valid`/`is_unverified`에는
영향 없음, 퀀트 점수도 정상 산출), `views/pegy_view.py`가 **"🚀 Forward" 카드 자리에만** 노란색(amber) 확인-필요
배지를 띄웁니다(Trailing 섹션·퀀트 점수는 정상 노출). Forward 섹션 자리를 재사용하는 이유는 실제 애널리스트
Forward 컨센서스가 있어도 배당 데이터가 불확실하면 밸류에이션 신뢰도가 같이 흔들리기 때문입니다.

**적용 사례 1-보충2(2026-08-06) — Trailing 데이터가 있는 종목은 하네스 실패·역성장·PER 극단치도 전체 차단하지 않음**:
오너 지적: "재무제표(Trailing)가 이미 존재하는 종목까지 이런 이유로 전체를 가리면 과거 데이터로 공부를 할 수가 없다."
`views/pegy_view.py`를 확인한 결과, DataValidator 3단계 하네스는 애초에 **Trailing(price/t_per/t_eps) 값끼리의
교차검증만** 하고 PBR/EV-EBITDA/DPS/ROE/ROIC는 전혀 건드리지 않는데도, 실패 시 카드 전체를 가렸었습니다.
이제 진짜로 카드를 그릴 수 없는 두 경우만 전체 차단(하드 블록)하고, 나머지는 Forward 카드 자리만 마스킹합니다.

- **하드 블록(카드 전체 차단) 유지**: ① `price` 자체가 없음(그릴 게 없음), ② 상장주식수 파싱 오류 의심
  (EPS 역산·총배당금 등 다수 지표가 오염될 수 있는 근본 문제).
- **Forward 카드만 마스킹(Trailing·나머지 지표는 정상 노출)으로 완화**:
  - 역성장/무성장(g_eff ≤ 0) — 보라색 테마. (단, 하네스 자체는 통과했는데 g_eff만 마이너스인 경우는
    원래부터 전체 차단 대상이 아니었으므로 그대로 정상 카드+빨간 배지로 렌더링됩니다. 이 마스킹은
    "하네스도 실패했고 g_eff도 마이너스"인 경우에만 적용됩니다.)
  - Forward PER 극단치/데이터 오염 — 빨간 테마. (`f_per`에 대한 검사라 Trailing에는 원래 영향 없음)
  - 실효성장률(g_eff) 산출 불가 — 회색/슬레이트 테마.
  - 그 외 일반 DataValidator 하네스 실패(위 사유에 해당 안 되는 경우) — 노란색 테마, 배당 미확정 케이스와
    동일 색상이지만 문구로 구분.
- 이 경우들은 `is_valid`/`is_unverified`는 그대로 두므로(가드레일 판정 자체를 바꾸지 않음) **퀀트 종합점수는
  여전히 산출되지 않습니다("측정 불가")** — 다만 Trailing 지표 자체는 화면에서 볼 수 있습니다.
- 판정 로직은 `views/pegy_view.py`의 `hard_block`/`was_blocked`/`is_per_extreme`/`is_geff_missing`/
  `is_negative_growth_case`/`is_generic_harness_fail` 플래그로 구현. 합성 데이터 10개 케이스로 분기 검증 완료
  (하드블록 2건, 신규 마스킹 4건, 기존 케이스 4건 모두 기대대로 분류).

**적용 사례 2 — 그레이엄 넘버(Graham Number)**: Forward 섹션이 마스킹된 종목에도 참고할 거리를 주기 위해,
성장률 예측이 필요 없는 순수 트레일링 공식(벤저민 그레이엄 원전, `√(22.5 × Trailing EPS × BPS)`)을
`collector_kospi200.py`에서 계산합니다(`graham_target` 필드). 이 공식은 아래 특수 케이스가 있습니다.

- **적자 기업(EPS ≤ 0)**: 제곱근 안이 음수가 되어 수학적으로 산출 자체가 불가능 → `None`으로 두고 화면에 사유를 명시. 오너 지침에 따라 KOSPI 200의 약 1/4을 차지하는 적자·저PBR 기업을 표에서 배제하지 않고, "산출 불가"임을 그대로 노출합니다.
- **금융업종(은행/보험/증권/캐피탈)**: 공식 자체는 계산되지만 장부가(BPS)의 의미가 제조업과 달라 전제가 잘 안 맞음 → 값은 표시하되 `views/pegy_view.py`에 **강한 경고 배지**(빨간 테두리 + "⚠️⚠️ 강한 경고")를 반드시 함께 표시합니다. 업종 판정은 `guardrail.py`의 `is_high_dividend_sector`와 같은 방식의 키워드 매칭입니다(개별 종목 코드 하드코딩 금지, SPEC §2-2).
- **표시 위치(2026-08-06 변경)**: 처음엔 "🚀 Forward" 마스크 박스 안에 중첩해 표시했으나, 그레이엄 넘버는 Trailing 지표에서만 산출되는 값이라 오너 요청으로 **Trailing 섹션 바로 아래(Forward 섹션과 별개의 독립 박스)** 로 옮겼습니다. 트리거 조건(`forward_data_missing`일 때만 표시)은 그대로입니다.

**적용 사례 3 — 시가총액 순위 히스테리시스 버퍼(2026-08-06 도입)**: 시가총액 순위가 200위 경계에서
하루만 왔다갔다 해도 종목이 사라졌다 재등장하며 요약 이력(`pegy_summary_history.json`)의 연속성이
깨지는 문제를 막기 위한 장치. `collector_kospi200.py`의 `apply_hysteresis_buffer()`가 담당합니다.

- **진입 기준(200위) / 이탈 기준(230위)**: 새 종목은 200위 이내로 들어와야 추적을 시작하지만,
  이미 추적 중이던 종목은 230위 밖으로 완전히 밀려나야 추적을 중단합니다(오너 확정, 2026-08-06).
- **직전 추적 목록 판정**: 매번 오늘자 `kospi200_pegy_latest.json`을 덮어쓰기 전에, 그 파일에 있던
  종목 코드 전체(화면 노출 여부와 무관하게)를 "어제 추적 중이었던 종목" 집합으로 먼저 읽어둡니다
  (`_load_previously_tracked_codes()`). 파일이 없거나 깨졌으면 빈 집합으로 처리해 단순 200위 컷과
  동일하게 안전히 동작합니다(첫 실행 대비, 지어내지 않음).
- **화면 노출은 항상 정확히 200개(오너 확정, 2026-08-06)**: 버퍼 구간(201~230위)에 걸린 종목은
  `is_visible=False`로 표시되어 계속 수집·보강만 되고, `views/pegy_view.py`가 로드 직후
  `is_visible` 기준으로 필터링해 화면에는 절대 노출하지 않습니다. `is_visible` 필드가 없는
  구버전 스냅샷은 하위 호환을 위해 전부 노출(`True`)로 간주합니다.
- **품질 지표 기준**: `metadata.total_count`/`valid_count`/`valid_ratio`는 버퍼 구간을 제외한
  화면 노출 200개 기준으로 집계합니다(배너에 보이는 숫자와 실제 검증 비율이 어긋나지 않도록).
  버퍼 구간 종목 수는 `metadata.tracked_count`/`hidden_buffer_count`로 별도 기록해 투명성을 유지합니다.
- **요약 중앙값 이력**: `update_pegy_summary_history()`에도 화면 노출 200개(`visible_stocks`)만
  넘깁니다 — `views/pegy_view.py`가 "이전 동기화 대비" 델타를 계산할 때도 화면에 보이는 종목만
  쓰므로 기준이 어긋나면 안 됩니다.

---

### 예시 3 — 화면은 "데이터 없음"을 그려야지, 기본 시세를 그리면 안 됨

`views/macro_view.py` 는 CSV 로드에 실패하면 **KOSPI 2500 / 환율 1350** 이라는 상수로
14개 지표와 종합 위험점수를 전부 계산해 평소와 똑같이 렌더링했습니다.
유일한 신호는 회색 `st.info("⚠️ 안전 모드")` 한 줄이었습니다.

```python
# ❌ 절대 금지 — 가짜 시세로 점수를 계산해서 정상 화면처럼 그림
kospi_close = 2500.0
usd_close   = 1350.0
volatility  = 1.2
score       = 50.0
data_source_log = "⚠️ 안전 모드"        # st.info() 회색 박스 → 아무도 눈치 못 챔

# ✅ 숫자를 아예 그리지 않고, 빨간 에러로 중단
if not local_loaded:
    st.error(
        "🚨 시장 데이터를 불러오지 못했습니다.\n\n"
        f"- 파일: {HISTORY_FILE}\n"
        "- 위험 지수와 14개 지표는 표시하지 않습니다. 수집 파이프라인을 확인해 주세요."
    )
    st.stop()
```

동일 원칙이 `views/pegy_view.py` 에도 적용됩니다.

```python
# ❌ 절대 금지 — 스냅샷이 없는데 "마지막 동기화: 지금" + 그럴듯한 중앙값 3종 세트
return {"last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "BACKUP"}, []
calc_f_per, calc_growth, calc_pegy = 10.4, 14.2, 0.73      # 라벨은 "KOSPI 200 실시간 중앙값"
st.metric("타겟 중앙 Forward PER", f"{calc_f_per} 배", "KOSPI 200 실시간 중앙값")

# ✅ 상태를 그대로 화면에 전달
if not all_stocks:
    st.error("🚨 KOSPI 200 스냅샷(data/kospi200_pegy_latest.json)을 읽지 못했습니다.")
    st.metric("타겟 중앙 Forward PER", "—", "데이터 없음")
    return
```

---

### 예시 4 — Forward Fill / 이전 값 유지는 "표시하면" 허용

이전 정상 데이터를 유지하는 것 자체는 SPEC §2-3이 허용하는 방식입니다.
**단, 그 사실이 데이터와 화면에 남아야 합니다.** 흔적 없는 FFILL은 더미 데이터와 동일합니다.

```python
# ❌ 절대 금지 — 전일 종가를 오늘 종가 자리에 넣고 변동률 0%로 저장. CSV에 흔적 없음
if kospi_close is None:
    kospi_close = float(history_df.iloc[-1]['KOSPI'])
    kospi_change = 0.0

# ✅ 보정했다는 사실을 데이터에 기록하고 UI에 표시
if kospi_close is None:
    kospi_close = float(history_df.iloc[-1]['KOSPI'])
    kospi_change = 0.0
    data_quality = "FFILL_KOSPI"        # market_history.csv 의 data_quality 컬럼에 저장
    print("🚨 KOSPI 결측 → 전일 종가로 보정 (data_quality=FFILL_KOSPI)")
# → macro_view 의 KOSPI 카드에서 data_quality != "OK" 이면
#    "⚠️ 전일 값 보정 (당일 수집 실패)" 배지를 반드시 함께 렌더링할 것
```

---

### 체크리스트 (모든 PR/코드 수정 시)

- [ ] 새로 추가한 상수 중, **실데이터가 들어갈 자리를 대신 채우는 값**이 있는가? (있으면 제거)
- [ ] `except` 블록이 `pass` 나 `print` 만 하고 계속 진행하지 않는가?
- [ ] 수집/파싱 실패가 **대시보드 화면까지** 전달되는가? (로그만으로는 불합격)
- [ ] Forward Fill·백필·수동입력 값에 **출처 표시(data_quality / source 컬럼)** 가 있는가?
- [ ] `status`, `is_valid`, `last_updated_at` 같은 상태 필드를 **조건 없이 성공값으로** 쓰고 있지 않은가?
- [ ] 하위 함수가 상위의 검증 결과를 **덮어쓰지** 않는가? (예: guardrail이 DataValidator 판정을 `True`로 덮는 사례 있었음)
- [ ] 파싱 결과에 **범위 검증**이 있는가? (주가 > 0, 상장주식수 > 100만, PER 0~300 등)

> 📄 이 원칙이 도입된 배경과 현재 코드베이스에서 발견된 위반 사례 전체 목록은
> 프로젝트 루트의 **`AUDIT_REPORT.md`** 를 참고하십시오.

---

## 0-2. 🗂️ 작업 시작·종료 절차: `PROJECT_STATUS.md` 먼저 확인할 것 (필수)

> [!CAUTION]
> **이 저장소를 작업하는 모든 AI(Gemini, Claude, ChatGPT 등)와 사람은 코드를 열어보기 전에
> 프로젝트 루트의 `PROJECT_STATUS.md` 를 먼저 읽어야 합니다.**
> 매번 전체 파일을 처음부터 다시 읽는 것은 시간과 비용(토큰) 낭비이며,
> 이미 파악된 맥락을 놓쳐 같은 문제를 두 번 진단하게 만듭니다.

### 작업 시작 시

1. `PROJECT_STATUS.md` 를 읽고 "지금 열려있는 일" 섹션부터 확인한다.
2. 정말 필요한 파일만 선택적으로 읽는다 (전체 파일을 순서대로 다 읽지 않는다).
3. `PROJECT_STATUS.md`에 없는 내용이 필요하면 그때 관련 코드를 찾아 읽는다.

### 작업 종료 시 (반드시 지킬 것)

1. **"최근 작업 로그"** 섹션 맨 위에 오늘 날짜로 무엇을 했는지 한두 줄로 추가한다 (전체 diff를 다시 쓰지 않는다 — 핵심 변경점만).
2. **"지금 열려있는 일"** 섹션을 다시 정리한다 — 완료된 항목은 지우고, 새로 발견된 미해결 항목은 추가한다.
3. 파일 구조가 바뀌었다면(파일 추가/삭제/역할 변경) "파일 구조 한눈에 보기" 표도 갱신한다.

### 왜 이 절차가 필요한가

- 이 프로젝트는 여러 AI 도구(제미나이, 클로드 등)를 오가며 작업되고 있습니다. 매번 세션이 새로 시작되면 이전 세션의 맥락이 없습니다.
- `PROJECT_STATUS.md` 없이 시작하면, 이미 고친 버그를 다시 진단하거나(토큰 낭비), 이미 삭제하기로 한 죽은 파일을 다시 살리는 등 **역행**이 발생할 수 있습니다.
- `AUDIT_REPORT.md`, `ENGINEERING_SPEC.md`(이 문서)는 "원칙/이력" 문서이고, `PROJECT_STATUS.md`는 "지금 이 순간의 진행 상태"를 담는 문서로 역할이 다릅니다. 상태가 바뀔 때마다 갱신해야 하는 쪽은 `PROJECT_STATUS.md` 입니다.

---

## 0-3. 📜 절대 준수 메뉴얼 (오너 지정, 2026-08-05 추가)

> [!CAUTION]
> 아래 항목은 오너가 직접 작성한 **절대 준수 규칙**입니다. 위 0-1/0-2와 동급의 최우선 규칙이며,
> 이 문서의 다른 어떤 관행보다 우선합니다. AI/개발자는 코드를 고치기 전에 반드시 확인하십시오.

### 0-3-1. 후행지표(後行指標) 전용 원칙 — "실시간"은 이 프로젝트의 목표가 아님

> **이 프로젝트의 모든 화면·데이터는 장마감 후 확정된 후행지표만 다룹니다. 실시간 데이터는 다루지 않습니다.**

- 장마감(당일 데이터가 최종 확정되는 시점) 이후에 얻을 수 있는, **수집·가공·계산이 완전히 끝난 정리된 데이터**만 사용합니다.
- "실시간", "실시간 수급 연동형", "최종 동기화: (지금 시각)" 처럼 **실시간을 암시하는 표현은 화면·문서 어디에도 두지 않습니다.** 발견 즉시 삭제 대상입니다. (참고: `visiblehand.py`의 "실시간 수급 연동형 시장 종합 위험 방공망 대시보드" 부제, `views/macro_view.py`의 "최종 동기화" 표시가 대표 사례 — 정리 필요 항목으로 `PROJECT_STATUS.md`에 등록할 것)
- 데이터를 누적/저장할 때는 **년/월/일/시/분/초**까지 명확히 남깁니다. "언제 기준으로 확정된 데이터인지"가 애매하면 안 됩니다.
- **"추정 프록시" 라벨링으로 대체하는 것도 더 이상 허용하지 않습니다.** 지금까지는 실데이터를 못 구하면 "추정 프록시입니다"라고 정직하게 라벨만 붙이고 계산은 계속했습니다(0-1 원칙의 연장). 앞으로는 한 단계 더 나아가, **후행지표로도 구할 수 없는 지표는 아예 화면에서 빼는 것을 우선 검토**합니다. (예: `views/macro_view.py`의 14개 위험 지표 중 실데이터 소스가 없는 항목들 — `PROJECT_STATUS.md`에 정리 대상으로 등록)

### 0-3-2. 크롤링 매너 — 상대 서버에 무리를 주거나 우리가 차단당할 행동 금지

- 크롤링 간격에 **항상 여유 있는 딜레이**를 둡니다 (현재 `collector_kospi200.py`의 `time.sleep(random.uniform(2.0, 3.0))` 패턴이 기준. 새 크롤러를 추가해도 이 수준 이상을 유지).
- 과도한 동시 요청, 짧은 간격 반복 요청, 상대 서버의 이용약관을 벗어나는 방식(로그인 우회, 비공개 API 무단 호출 등)은 금지합니다.
- 크롤링이 차단(403/429, IP 차단 등)되면 **재시도를 무한 반복하지 말고** 실패로 기록하고 중단합니다 (0-1 원칙과 동일하게, 조용히 우회 시도하지 않음).

### 0-3-3. 다중 출처 크롤링 및 raw/가공 데이터 분리 보관

- 신규로 크롤링을 붙이는 지표는 **최소 2개 이상의 서로 다른 출처**에서 가져오는 것을 원칙으로 합니다.
- 크롤링 직후의 **원본(raw) 데이터**와, 계산·정제를 거친 **재가공 데이터**는 항상 분리해서 보관합니다. 둘을 합치기 전에 반드시 서로 비교검사(교차검증)를 거칩니다. (기존 `utils/data_validator.py`의 "출처 간 교차 검증" 단계와 같은 원칙이며, 앞으로는 PEGY 수집기뿐 아니라 **매크로 지표를 포함한 모든 신규 크롤러에도 동일하게 적용**합니다.)
- raw 데이터와 가공 데이터 둘 다 **사용자가 다운로드할 수 있어야 합니다.**

### 0-3-4. 사용자 화면에 코드가 노출되면 안 됨

- 대시보드 화면에는 **파이썬 함수명, 파일 경로, 스택 트레이스, `TypeError` 같은 원본 에러 메시지**가 그대로 노출되면 안 됩니다. (오늘 발생했던 "Oh no. Error running app." 크래시 화면에 내부 트레이스백이 그대로 떴던 것이 반례 — 정상적인 실패 처리라면 `st.error()`로 사람이 읽을 수 있는 문구만 보여줘야 합니다.)
- 0-1 원칙("실패는 화면에 보여야 한다")과 모순되지 않습니다 — **"실패했다는 사실과 이유"는 사람이 읽을 수 있는 문장으로 보여주되, 코드 내부 구조(트레이스백)까지 그대로 노출하지는 않습니다.**

### 0-3-5. 작업 종료 시 항상 깃허브 푸시까지 완료

- 코드 작업이 끝나면 커밋만 하고 끝내지 않고, **반드시 `git push`까지 완료된 상태**로 세션을 마칩니다. (`PROJECT_STATUS.md`의 "지금 열려있는 일"에 "푸시 필요"가 남아있으면 안 됩니다.)

### 0-3-6. 신규 기능은 모듈로 관리 + 스테이징(테스트) 승인 후 반영

- 새로 추가하는 기능은 유지보수하기 쉽도록 **독립된 모듈**로 만듭니다 (기존 "수집/검증/가공/표현" 계층 분리 원칙의 연장, §6 참고).
- **버그 수정(유지보수)이 아닌, 완전히 새로운 기능 추가**는 실전 페이지에 바로 반영하지 않습니다. 별도의 테스트 페이지에서 먼저 동작을 확인하고, **오너의 승인/허가가 떨어진 뒤에만** 실전 페이지에 반영합니다.
- (참고: 오늘 있었던 크래시 대응처럼 "이미 망가진 실전 서비스를 되살리는 긴급 수정"은 이 승인 절차의 예외입니다 — 빠르게 고쳐서 바로 반영하는 것이 맞습니다. 이 절차는 "잘 되고 있는데 새 기능을 얹는" 경우에 적용됩니다.)

### 0-3-7. 작업지시서 / 작업완료서

- 이 요구사항은 이미 **`PROJECT_STATUS.md`**로 충족되고 있습니다 (0-2 참고). 작업을 시작할 때는 이 문서를 먼저 읽고, 끝낼 때는 "최근 작업 로그"와 "지금 열려있는 일"을 갱신하는 지금의 절차가 곧 오너가 원하는 "작업지시서/작업완료서"입니다. 별도 문서를 새로 만들 필요는 없습니다.

---

## 1. 아키텍처 다이어그램 (데이터 흐름)

```
[네이버 증권 웹페이지]
        │
        ▼
┌─────────────────────────────────────────┐
│  1. Scraper (collector_kospi200.py)      │
│     - 시총 순위 페이지 → 종목 리스트     │
│     - 종목 상세 페이지 → PER/EPS/DPS     │
│     ★ 위치 인덱스(iloc) 사용 절대 금지   │
│     ★ 키워드 기반 동적 파싱만 허용        │
└────────────────┬────────────────────────┘
                 │ raw data
                 ▼
┌─────────────────────────────────────────┐
│  2. DataValidator (utils/data_validator) │
│     ① Raw vs Processed 1:1 대조         │
│     ② PER Sanity Check (오차 ≤ 5%)     │
│     ③ Cross-Reconciliation (오차 ≤ 3%)  │
└────────────────┬────────────────────────┘
                 │ validated data
                 ▼
┌─────────────────────────────────────────┐
│  3. Scoring (utils/scoring.py)          │
│     - 100점 만점 퀀트 스코어             │
│     - PEGY / ROE / 주주환원 가중         │
│                                         │
│  4. Guardrail (utils/guardrail.py)      │
│     - PER > 300 / ≤ 0 차단             │
│     - 역성장 g_eff ≤ 0 컷오프          │
│     - 고배당 업종 DPS 미확인 마스크       │
└────────────────┬────────────────────────┘
                 │ final data
                 ▼
┌─────────────────────────────────────────┐
│  5. JSON 저장                           │
│     data/kospi200_pegy_latest.json       │
│     data/pegy_summary_history.json       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  6. Dashboard (visiblehand.py)          │
│     Streamlit 대시보드 렌더링            │
└─────────────────────────────────────────┘
```

---

## 2. 🚫 절대 금지 규칙 (NEVER Rules)

> [!CAUTION]
> 아래 규칙을 위반하면 데이터 전체가 오염됩니다. 어떤 AI/개발자도 예외 없이 준수해야 합니다.

### 2-1. 위치 인덱스(iloc) 기반 파싱 전면 금지

```python
# ❌ 절대 금지 — 표 구조가 바뀌면 분기 데이터가 연간으로 둔갑
df.iloc[:, 2]
row.values[2]
cols[2].text

# ✅ 반드시 키워드 기반 동적 타겟팅 사용
for idx, col in enumerate(df.columns):
    tf_type = DataValidator.classify_header_timeframe(col)
    if tf_type == "TTM":
        annual_cols.append(idx)
```

**이유**: 네이버 증권 HTML 테이블은 종목마다 컬럼 수/순서가 다릅니다. `iloc[:, 2]`로 고정하면 어떤 종목에서는 분기(Q) 데이터를, 어떤 종목에서는 연간(TTM) 데이터를 가져오게 되어 PER이 3배 이상 왜곡됩니다.

### 2-2. 특정 종목 전용 예외 코드 금지

```python
# ❌ 절대 금지
if code == "055550":  # 신한지주 전용 보정
    eps = eps * 4

# ✅ 범용 로직으로 모든 종목에 동일하게 적용
# PERIOD_KEYWORDS 사전 기반으로 TTM/Q/D 자동 분류
```

### 2-3. 더미/가상 데이터 자동 생성 금지

```python
# ❌ 절대 금지 — 실패 시 가짜 데이터 생성하여 DB 오염
if scraping_failed:
    return generate_dummy_data()

# ✅ 실패 시 이전 안전 데이터 유지 또는 None 반환
if scraping_failed:
    return None  # 호출측에서 fallback 처리
```

### 2-4. 단위 변환 임의 적용 금지

```python
# ❌ 절대 금지 — EPS가 '원' 단위인지 '천원' 단위인지 모르고 변환
eps = raw_eps * 1000

# ✅ 원문 텍스트에서 단위 키워드 확인 후 변환
# "천원" → ×1000, "백만원" → ×1000000, "원" → ×1
```

---

## 3. 📖 기간 키워드 매핑 사전 (PERIOD_KEYWORDS)

> [!IMPORTANT]
> 이 사전은 `utils/data_validator.py`에 정의되어 있으며, 모든 크롤링 모듈이 참조합니다.
> 키워드를 추가/삭제할 때는 반드시 이 사전만 수정하고, 개별 크롤러에 하드코딩하지 마세요.

```python
PERIOD_KEYWORDS = {
    "TTM": [
        "연간", "TTM", "최근 12개월", "최근 연간 실적",
        "ANNUAL", "YEARLY", "A",
        r"\b20\d{2}\.12\b",    # 2024.12, 2025.12 등
        r"\bFY\d{2,4}\b"       # FY24, FY2025 등
    ],
    "QUARTERLY": [
        "분기", "1Q", "2Q", "3Q", "4Q", "3개월",
        "Q1", "Q2", "Q3", "Q4", "QUARTERLY", "Q",
        r"\b20\d{2}\.03\b",    # 2024.03 등 (3월 결산)
        r"\b20\d{2}\.06\b",    # 2024.06 등 (6월 결산)
        r"\b20\d{2}\.09\b"     # 2024.09 등 (9월 결산)
    ],
    "DAILY": [
        "일별", "당일", "D", "일간", "주간", "월간",
        "DAILY", "WEEKLY", "MONTHLY"
    ],
    "ESTIMATE": [
        "(E)", "(P)", "E", "P", "ESTIMATE", "CONSENSUS"
    ]
}
```

### 지표별 타겟팅 규칙

| 지표 | 타겟 기간 | 설명 |
|------|-----------|------|
| PER, EPS, DPS, PBR, ROE | `TTM` | 최근 4분기 합산(연환산) 값 사용 |
| 분기 실적, 3개월 모멘텀 | `QUARTERLY` | 단일 분기 값 사용 |
| 일별 주가, 거래량, 수급 | `DAILY` | 당일 값 사용 |

> **핵심 원칙**: 분기(Q) 데이터를 연간(TTM)으로 오인하여 변환하거나 덮어쓰면 안 됩니다.
> 수집 타겟과 가공 목적의 1:1 일치 여부를 Raw-Processed 대조 단계에서 반드시 확인합니다.

---

## 4. 🛡️ 3단계 데이터 검증 파이프라인 (DataValidator)

> [!IMPORTANT]
> 파일 위치: `utils/data_validator.py`
> 모든 수집 데이터는 이 3단계를 통과해야만 대시보드에 반영됩니다.

### 4-1단계: Raw vs Processed 1:1 대조

```
검증 항목:
├── 필수 키 존재 여부 (price, t_per, t_eps)
├── 지표-기간 1:1 타겟팅 매핑 검증 (PER → TTM 맞는지)
└── Raw EPS ↔ Processed EPS 수치 스왑/0 변형 체크
```

### 4-2단계: PER 산티 체크 (Sanity Check)

```
공식: 계산_PER = 현재가 / EPS_TTM
기준: |계산_PER - 표기_PER| / 표기_PER ≤ 5%
실패 시: 해당 종목 대시보드 반영 차단
```

### 4-3단계: 출처 간 교차 검증

```
1차 출처 (네이버 종목 상세 aside_invest_info) PER vs
2차 출처 (시총 순위 테이블) PER
오차 ≤ 3% → 승인
오차 > 3% → Fallback (이전 정상 데이터 유지)
```

---

## 5. 📐 핵심 수식 명세 (PEGY / Scoring / Guardrail)

### 5-1. PEGY (PEG + Yield) 산출

```python
# 실효성장률 (g_eff): 2중 Cap
sh_return_capped = min(sh_yield, 10.0)           # 주주환원 10% 상한
g_eff = min(min(growth, 35.0) + sh_return_capped, 40.0)  # 총합 40% 상한
g_eff_safe = max(g_eff, 0.1)                     # 역성장 Floor (0 나눗셈 방지)

# 변동성 보정
vol_penalty = 1.18 if 변동성_보정중 else 1.0
growth_eff = g_eff_safe / vol_penalty

# Forward PEGY
f_pegy = f_per / growth_eff    # 낮을수록 저평가

# Trailing PEGY
t_pegy = t_per / max(growth + sh_yield, 0.1)
```

### 5-2. 목표주가 산출

```python
# ROE/ROIC 프리미엄
roe_prem  = +0.15 if f_roe >= 12.0 else -0.10
roic_prem = +0.10 if roic >= 10.0 else -0.05

target_pegy = 1.0 × (1.0 + roe_prem + roic_prem)
target_per  = min(target_pegy × growth_eff, 25.0)  # 25배 Cap

# 목표주가 폭발 방지 (현재가의 최대 2.5배)
f_target = min(f_eps × target_per, price × 2.5)
t_fair   = min(t_eps × min(growth + sh_yield, 25.0), price × 2.5)
```

### 5-3. 100점 만점 퀀트 스코어 배점

| 영역 | 배점 | 설명 |
|------|------|------|
| PEGY 밸류에이션 | 최대 35점 | f_pegy 낮을수록 고득점 |
| 자본효율성 (ROE/ROIC) | 최대 30점 | f_roe, roic 높을수록 고득점 |
| 주주환원율 | 최대 20점 | 배당+자사주 수익률 |
| Trailing 안정성 | 최대 10점 | t_roe 기반 안정성 |
| 변동성 보정 | 최대 5점 | 변동성 정상 시 만점 |

### 5-4. Guardrail 차단 규칙

| 조건 | 처리 |
|------|------|
| PER > 300 또는 PER ≤ 0 또는 주가 ≤ 0 | `is_valid = False`, 스코어 0점, 차단 |
| g_eff ≤ 0 (역성장) | PEGY 99.0 강제, 스코어 40점 감점, 목표주가 = 현재가×0.7 |
| 고배당 업종인데 DPS = 0 | `is_unverified = True`, 검증 대기 마스크 |
| PER > 200 (scoring 레벨) | 스코어 10점 강제, 데이터 이상 배지 |

---

## 6. 🔧 파일별 역할 및 수정 시 주의사항

### 수집 계층 (Scraper Layer)

| 파일 | 역할 | 수정 시 주의 |
|------|------|-------------|
| `collector_kospi200.py` | KOSPI 200 배치 수집(GitHub Actions 실행 시점 기준) + 퀀트 지표 산출 | **네이버 HTML 구조 변경 시에만 파싱 로직 수정. iloc 금지. PERIOD_KEYWORDS 참조 필수** |
| `scrape_daily.py` | 일별 매크로 위험 지표 수집 | 수급/환율/선물 지표. 별도의 PERIOD_KEYWORDS 사본 보유 (동기화 필요) |

### 검증 계층 (Validation Layer)

| 파일 | 역할 | 수정 시 주의 |
|------|------|-------------|
| `utils/data_validator.py` | 3단계 검증 파이프라인 + PERIOD_KEYWORDS 원본 | **키워드 추가/삭제는 여기서만. 검증 임계값(5%, 3%) 변경 시 test_harness.py 동시 업데이트** |

### 가공 계층 (Processing Layer)

| 파일 | 역할 | 수정 시 주의 |
|------|------|-------------|
| `utils/scoring.py` | 100점 만점 스코어 산출 | **배점 비율 변경 시 test_harness.py에 수식 검증 로직 반드시 추가** |
| `utils/guardrail.py` | 하드 컷오프/차단 규칙 | **차단 기준값 변경 시 scoring.py와 동기화 필수** |

### 표현 계층 (Presentation Layer)

| 파일 | 역할 | 수정 시 주의 |
|------|------|-------------|
| `visiblehand.py` | Streamlit 메인 앱 | UI만 담당. 데이터 가공 로직 절대 여기에 넣지 말 것 |
| `views/pegy_view.py` | PEGY 밸류에이션 페이지 | JSON 데이터 읽기 전용. 가공은 collector에서 완료 |
| `views/macro_view.py` | 매크로 방공망 페이지 | market_history.csv 읽기 전용 |

### 검증 계층 (Test Layer)

| 파일 | 역할 | 수정 시 주의 |
|------|------|-------------|
| `test_harness.py` | 통합 거버넌스 검사 + 감사 이력 | **모든 수식/로직 변경 시 AuditRecord 추가 필수** |

---

## 7. 🔄 네이버 크롤링 파싱 규칙 상세

### 7-1. 데이터 소스 우선순위

```
1순위: 종목 상세 페이지 우측 aside_invest_info 공식 스냅샷
       → PER, EPS (trailing + forward), 배당수익률
       → 정규식 패턴: r'([\d\.,]+)배\s*l\s*([\d\.,]+)원'

2순위: 재무제표 HTML 테이블 (pd.read_html)
       → DPS (주당배당금), 기타 재무 지표
       → 반드시 PERIOD_KEYWORDS 기반 헤더 분류 후 연간 컬럼만 타겟팅

3순위: 시총 순위 테이블 PER/ROE
       → 교차검증용 2차 출처 (1순위와 3% 이내 일치 확인)
```

### 7-2. aside_invest_info 파싱 패턴

```python
# Trailing PER/EPS (실적 기반)
if 'PERlEPS' in text and '추정' not in text and '동일업종' not in text:
    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)

# Forward PER/EPS (추정치)
elif '추정PERlEPS' in text:
    per_match = re.search(r'([\d\.,]+)배\s*l\s*([\d\.,]+)원', text)

# 배당수익률
elif '배당수익률' in text:
    yield_match = re.search(r'([\d\.,]+)%', text)
```

> **주의**: `'PERlEPS'`의 `l`은 알파벳 소문자 L입니다 (파이프`|`가 아님). 네이버 실제 HTML 텍스트 구조 그대로입니다.

### 7-3. 재무제표 DPS 파싱 (동적 키워드 타겟팅)

```python
# 1. 모든 HTML 테이블에서 재무제표 테이블 식별
fin_df_list = [d for d in dfs if ('매출액' in str(d) or '영업이익' in str(d))]

# 2. 헤더 시계열 동적 분류 (iloc 금지!)
for idx, col in enumerate(fin_df.columns):
    tf_type = DataValidator.classify_header_timeframe(col)
    if tf_type in ["TTM", "ANNUAL_TTM"]:
        annual_cols.append(idx)

# 3. '주당배당금' 행에서 가장 최근 연간 컬럼 값 추출
for col_i in reversed(annual_cols):
    v = float(str(row.values[col_i]).replace(',', ''))
    if v > 0:
        parsed_dps = int(v)
        break
```

---

## 8. 📝 코드 변경 시 체크리스트

코드를 수정하는 AI 또는 개발자는 아래 체크리스트를 반드시 확인하세요.

- [ ] `iloc` 또는 고정 위치 인덱스를 사용하지 않았는가?
- [ ] 특정 종목 전용 `if code == "..."` 예외 코드를 넣지 않았는가?
- [ ] 기간 키워드 변경 시 `utils/data_validator.py`의 `PERIOD_KEYWORDS`만 수정했는가?
- [ ] 수식 변경 시 `test_harness.py`에 `AuditRecord`를 추가했는가?
- [ ] Guardrail 임계값 변경 시 `scoring.py`와 `guardrail.py` 동기화했는가?
- [ ] 변경 후 `python test_harness.py` 실행하여 전체 검증을 통과했는가?
- [ ] 변경 후 `python collector_kospi200.py` 실행하여 200개 종목 수집 성공했는가?
- [ ] 검증 통과율이 95% 이상인가?
- [ ] 더미 데이터를 자동 생성하는 코드를 넣지 않았는가?

---

## 9. 🧪 검증 명령어

```bash
# 1. 코드 컴파일 체크
python -m py_compile collector_kospi200.py
python -m py_compile utils/data_validator.py
python -m py_compile test_harness.py

# 2. 통합 하네스 검증 (거버넌스 + UI + 데이터 교차검증)
python test_harness.py

# 3. 전체 수집 실행 (200개 종목, 약 3~5분 소요)
python collector_kospi200.py

# 4. 수집 결과 검증 (유효 통과 비율 확인)
python -c "import json; d=json.load(open('data/kospi200_pegy_latest.json',encoding='utf-8')); v=sum(1 for s in d['stocks'] if s.get('is_valid')); print(f'Total:{len(d[\"stocks\"])} Valid:{v} Rate:{v/len(d[\"stocks\"])*100:.1f}%')"
```

---

## 10. 📂 디렉토리 구조 (전체)

```
visible_hand/
├── ENGINEERING_SPEC.md          ← 이 문서 (AI 불변 규칙서)
├── visiblehand.py               ← Streamlit 메인 앱
├── app.py                       ← 앱 엔트리포인트
├── collector_kospi200.py        ← KOSPI 200 수집기 (핵심)
├── scrape_daily.py              ← 일별 매크로 지표 수집기
├── test_harness.py              ← 통합 검증 하네스
├── test_live.py                 ← 라이브 테스트
├── requirements.txt             ← Python 의존성
├── data/
│   ├── kospi200_pegy_latest.json    ← 최신 200종목 스냅샷
│   └── pegy_summary_history.json    ← 요약 지표 이력
├── utils/
│   ├── data_validator.py        ← 3단계 검증 + PERIOD_KEYWORDS (원본)
│   ├── scoring.py               ← 100점 만점 퀀트 스코어링
│   ├── guardrail.py             ← 하드 컷오프 방공망
│   ├── db.py                    ← DB 유틸리티
│   └── gdrive_helper.py         ← Google Drive 연동
├── views/
│   ├── pegy_view.py             ← PEGY 밸류에이션 뷰
│   ├── macro_view.py            ← 매크로 방공망 뷰
│   └── admin_view.py            ← 관리자 사이드바
└── .github/                     ← GitHub Actions CI/CD
```

---

> **최종 요약**: 이 프로젝트의 크롤링·가공·검증 로직은 **순수 Python**으로 작성되어
> 어떤 AI 모델과도 독립적으로 동작합니다. AI 모델의 역할은 코드를 **수정/개선**할 때에만
> 관여하므로, 이 명세서의 규칙을 읽고 따르면 모델 교체에도 파이프라인이 안전합니다.
