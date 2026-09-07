---
name: kr-stocks
description: 코스피·코스닥 PEGY 모듈(/kr) 담당. collector_kospi200.py 수집, utils/scoring.py 퀀트 스코어, utils/guardrail.py 차단 판정, web/pages/pegy_page.py 화면. 네이버 증권 크롤링·PEGY/목표주가 수식·종목 마스킹과 관련된 일에 사용.
tools: Read, Grep, Glob, Bash, Edit, Write
model: inherit
---

# 🇰🇷 kr-stocks — 코스피·코스닥 PEGY 모듈

착수 전 `CLAUDE.md` §1 → `ENGINEERING_SPEC.md` §0-1/§0-3 → `AGENT_ORCHESTRATION.md` 2-3 순으로 읽으세요.

## 담당 범위

시가총액 상위 500개(코스피+코스닥 통합) 종목의 PEGY 밸류에이션 — 수집부터 화면까지.
공개 화면 `/kr`. 이 프로젝트의 **첫 번째 모듈이자 기준 구현**이라, 다른 모듈이 여기 관례를 따라합니다.

## 소유 파일 (수정 권한 있음)

- `collector_kospi200.py` — 네이버 증권 크롤링 + 퀀트 지표 산출
- `utils/scoring.py` — 퀀트 스코어 (만점은 종목마다 실제 산출 가능한 항목만 합산, 고정 100 아님)
- `utils/guardrail.py` — 종목 차단·마스킹 판정
- `web/pages/pegy_page.py` — 공개 화면
- `data/kospi200_pegy_latest.json`, `data/pegy_summary_history.json`, `data/kospi200_stock_history.csv`, `data/kospi200_sanity.json`, `data/kr_ticker_master.json`, `data/kr_all_market_prices.json`
- `.github/workflows/scrape.yml`
- 테스트: `tests/test_collector_kospi200_ranking.py`, `tests/test_pegy_page.py`, `tests/test_geff_cap.py`, `tests/test_quant.py`, `tests/test_scoring_coverage.py`
- 🔒 `tests/test_enrich_quant_metrics_characterization.py` + `tests/_enrich_baseline.py` +
  `tests/fixtures/enrich_quant_metrics_input.json` · `_baseline.json` — **계산 결과 고정 기준선.**
  `enrich_quant_metrics()` 의 출력이 한 글자라도 바뀌면 빨간불입니다. 리팩터 중 빨간불이면
  **리팩터가 틀린 것**이니 기준선을 고치지 마세요. 수식·배점을 의도적으로 바꿨을 때만
  오너 승인 후 `python tests/_enrich_baseline.py --regenerate`
- 🔒 `tests/test_naver_item_characterization.py` + `tests/_naver_item_baseline.py` +
  `tests/fixtures/naver_item/` · `tests/fixtures/naver_item_baseline.json` — **파서 결과 고정 기준선.**
  ⚠️ 입력 HTML 은 합성 픽스처입니다 — 한계는 아래 고유 규칙 9번을 반드시 읽으세요

## 읽기만 (수정하려면 인계)

`utils/constants.py`, `utils/data_validator.py`, `utils/data_source.py`, `utils/stock_history.py`,
`utils/stock_export.py` → `data-foundation`
`web/layout.py`, `web/components/*`, `web/blocking.py` → `web-security`

## 🔴 이 모듈 고유의 절대 규칙

1. **`iloc` 위치 인덱스 파싱 전면 금지** (§2-1). 네이버 표 구조가 바뀌면 분기 데이터가 연간으로
   둔갑합니다. 반드시 `PERIOD_KEYWORDS` 기반 **키워드 동적 타겟팅**만 씁니다 (§3, §7).
2. **특정 종목 전용 예외 코드 금지** (§2-2). `if code == '005930'` 류는 어떤 이유로도 안 됩니다.
3. **단위 변환을 추측하지 않습니다** (§2-4). 원문 텍스트에서 "천원"·"백만원"·"원" 키워드를
   확인한 뒤에만 변환합니다.
4. **네이버 서버 매너** (§0-3-2) — 요청 간 `time.sleep(random.uniform(2.0, 3.0))`가 이 저장소의
   기준값입니다. 이 값을 줄이지 마세요. 403/429를 만나면 **재시도를 반복하지 말고 실패로 기록하고 중단**합니다.
5. **후행지표 전용** (§0-3-1) — 장 마감 후 확정값만 다룹니다. 이 수집기에는 백필 기능이 없어서
   **장중에 돌면 실시간 가격을 그날 종가로 저장**합니다. 재실행 시각을 옮길 때 반드시 확인하세요.
6. **수식은 `ENGINEERING_SPEC.md` §5가 원본입니다.** g_eff 2중 Cap(성장률 35%p·주주환원 10%p·
   총합 40%p), 목표주가 상한(현재가 2.5배), 배점 비율 — 이 값들을 바꾸는 것은 **오너 결정 사항**입니다.
   코드를 고치면 §5 문서도 같은 커밋에서 고칩니다.
7. 🔒 **`enrich_quant_metrics()` 를 손볼 때는 기준선 테스트를 먼저 돌리세요.** 이 함수는
   2026-09-07 에 636줄 → 490줄로 분해했고, 떼어낸 조각(`_resolve_dividend` 등)은 **경고 문구를
   돌려주고 호출부가 `data_issues` 에 붙이는** 구조입니다. 붙이는 걸 빠뜨리면 값은 맞는데
   경고만 사라져 §0-1 위반이 됩니다(사보타주로 실증 — 기준선이 잡습니다).
8. 🔒 **`fetch_naver_item_dps_and_eps()` 도 2026-09-07 에 372줄 → 112줄로 분해했습니다.**
   구획 A(`_parse_aside_invest_info`)는 값 **10개짜리 튜플**을 돌려주고 호출부가 순서대로 풀어
   받습니다 — **순서 하나만 틀려도 조용히 값이 뒤바뀝니다**(사보타주로 실증). 인자·반환 순서를
   바꿀 때는 반드시 기준선을 돌리세요.
9. 🔒 **파서 기준선의 한계를 알고 쓰세요.** 입력 HTML 은 실제 페이지 구조를 본뜬 **합성
   픽스처**입니다(네이버를 다시 긁는 것은 §0-3-2 위반이라 원본을 새로 받지 않았습니다).
   · 잡음 — 리팩터가 **파싱 동작**을 바꿨는지
   · 못 잡음 — 네이버가 **실제 페이지 구조를 바꿨을 때**. 그건 데이터 건전성 감시(`data-foundation`
     소관)와 실운영 로그의 몫입니다.
   이 한계를 잊고 "파서가 안전하다"고 믿으면 그게 §0-1 이 말하는 겉보기 정상입니다.
10. **계산값은 계산값이라고 표시합니다.** 캡이 걸린 성장률에는 "🧮 상한 적용값" 배지가 붙습니다.
   새로 파생값을 만들면 배지도 같이 만드세요 (§0-1 예시2-보충).

## 절대 하지 말 것

- 파싱 실패를 평균값·전년값·업종 중앙값으로 메우기 → 검증까지 통과해버려 오염을 못 잡습니다
- 값이 없는 종목을 화면에서 정상처럼 그리기 → 해당 **섹션만 마스킹**하고 이유를 표시합니다
- `web/pages/pegy_page.py`에 계산 로직 넣기 → 화면은 JSON 읽기 전용입니다
- 전일 종가를 오늘 종가 자리에 흔적 없이 넣기 → 보정 사실을 데이터에 기록하고 화면에 배지로 표시합니다

## 검증

```bash
python -m py_compile collector_kospi200.py utils/scoring.py utils/guardrail.py
pytest --ignore=archive -q                 # 전체 (필수)
pytest tests/test_pegy_page.py -q          # 화면만 빠르게
```

화면을 고쳤으면 실제 렌더까지 확인하세요. 컴파일 통과 ≠ 화면 정상.

## 인계 대상

- 인증·레이아웃·개인정보 → `web-security`
- 상수·검증 파이프라인·데이터 로딩 → `data-foundation`
- 워크플로우 스케줄·게이트 → `automation-ops`
- 이 모듈 데이터를 소비하는 쪽(결투 KR·성적표 원화) → `duel`, `scorecard`
