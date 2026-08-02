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
| `collector_kospi200.py` | KOSPI 200 실시간 수집 + 퀀트 지표 산출 | **네이버 HTML 구조 변경 시에만 파싱 로직 수정. iloc 금지. PERIOD_KEYWORDS 참조 필수** |
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
