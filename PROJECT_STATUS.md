# 프로젝트 현황판 (PROJECT_STATUS.md)

> **다음에 이 프로젝트를 다시 열 때는 (나 자신이든, 제미나이든, 다른 클로드 세션이든) 전체 파일을 처음부터 다 읽지 말고 이 문서부터 읽으세요.**
> 이 문서 하나로 "지금까지 뭘 했고, 지금 뭐가 문제고, 다음에 뭘 해야 하는지"를 알 수 있게 유지하는 게 목적입니다.
> 작업할 때마다 이 문서의 **최근 작업 로그**와 **지금 열려있는 일** 섹션을 업데이트해주세요.

마지막 업데이트: 2026-08-05

---

## 1. 이 프로젝트는 무엇인가

"잘 보면 보이는 손 (The Visible Hand)" — 코스피 시장 위험도 + 코스피200 개별 종목 PEGY(가치) 점수를 매일 자동으로 계산해서 보여주는 대시보드.

- 실제 서비스 주소: `visiblehand.co.kr` (커스텀 도메인, `index.html`이 아래 Streamlit 앱을 iframe으로 감싸는 구조)
- 실제 앱이 돌아가는 곳: **Streamlit Community Cloud** (`https://visible-hand-dashboard-2vmzz6tk63wsac7n345ord.streamlit.app/`)
- 코드 저장소: `github.com/moonbear135/visible-hand-dashboard` (public repo)
- 데이터 자동 수집: **깃허브 액션(GitHub Actions)** — PC를 꺼놔도 매일 자동으로 돈다 (이게 최근 작업의 핵심 목표였음)

## 2. 파일 구조 한눈에 보기 (다시 다 안 읽어도 되게)

| 파일/폴더 | 역할 |
|---|---|
| `scrape_daily.py` | 코스피 지수/환율/수급 데이터 수집 → `market_history.csv`에 누적. 백필 모드 지원(아래 참고) |
| `collector_kospi200.py` | 코스피200 개별 종목 PEGY 데이터 수집 → `data/*.json` |
| `.github/workflows/scrape.yml` | **유일하게 살아있는 자동화 워크플로우.** 매일 평일 KST 16:05 실행 |
| `market_history.csv` | 날짜별 종합 위험 점수 이력 |
| `data/kospi200_pegy_latest.json`, `data/pegy_summary_history.json` | 종목별 최신 데이터 + 요약 이력 |
| `views/*.py` | 화면(매크로 화면, 종목 화면, 관리자 화면) |
| `utils/*.py` | 점수 계산, DB 저장, 검증(guardrail), AI 코멘트, 구글드라이브 백업 |
| `app.py` / `visiblehand.py` | 앱 진입점 |
| `scheduler.py` / `run_scheduler.bat` | **레거시.** PC 켜놨을 때만 도는 로컬 스케줄러 — 지금은 깃허브 액션이 이 역할을 대체함. 굳이 쓸 필요 없음 |
| `ENGINEERING_SPEC.md` | 코딩 원칙 문서. **"하드코딩·더미 데이터 금지" 원칙이 최우선 규칙으로 적혀있음** — 앞으로 이 프로젝트를 건드릴 때 반드시 따를 것 |
| `AUDIT_REPORT.md` | 2026-08-05 오푸스가 전체 코드베이스를 감사한 상세 보고서 (13개 파일, 50여 건, ✅수정완료/⏸️보류 표시됨) |
| `credentials.json`, `service_account.json`, `token.json` | 구글 API 관련 비밀키. `.gitignore`에 등록되어 있어 git에는 안 올라감 (확인 완료) |

## 3. 최근 작업 로그 (최신순)

- **2026-08-05** — "14개 변동성 지표별 위험 기여도 상세 분석표"의 아래쪽 행들이 화면에서 잘려 보이고 스크롤도 안 되는 문제 발견·수정. 원인: 표를 `st.components.v1.html(height=700, scrolling=False)`로 고정 높이 700px짜리 iframe에 그렸는데, 표 내용이 700px를 넘으면 그 아래는 진짜로 볼 방법이 없었음. `st.markdown(unsafe_allow_html=True)`로 바꿔서 일반 페이지 흐름에 그리도록 수정 (표 길이에 관계없이 페이지 스크롤로 전체 확인 가능). **→ 아직 깃허브에 안 올라감 (푸시 필요)**
- **2026-08-05** — 매크로 화면(잘 보면 보이는 손) 위험지수 차트가 `TypeError`로 죽는 문제 발생. 원인은 `st.line_chart`가 내부적으로 쓰는 `altair` 라이브러리가 Streamlit Cloud의 Python 3.14 환경과 안 맞는 **altair 자체의 미해결 버그**였음. `.python-version`/`runtime.txt`로 Python 버전을 낮춰서 우회 시도했으나 Streamlit Cloud가 반영을 안 해서 실패(리부트해도 그대로 python3.14) → **차트를 altair 의존 없는 Plotly로 교체**해서 해결. (참고: `.python-version`, `runtime.txt` 파일은 효과가 없었던 시도라 지금 레포에 남아있지만 실질적 역할은 없음 — 나중에 지워도 무방)
- **2026-08-05** — "사실 이 가격이에요"(PEGY) 화면에 전 종목 "데이터 없음" 뜨는 문제 발생. 원인: 네이버 상세페이지 텍스트 정규식 파싱이 상장주식수 대신 "외국인소진율"(46, 50 같은 작은 숫자)을 잘못 집어오는 오염 발생. `collector_kospi200.py`에 **FinanceDataReader의 구조화된 KRX 상장종목 표를 1차 출처로 추가**(컬럼명이 명확해서 오염 위험 없음), 기존 네이버 파싱은 백업으로만 사용하도록 수정 → 200종목 중 147종목 검증 통과로 복구 확인. **(나머지 53종목이 왜 아직 안 되는지는 미조사 — 아래 "지금 열려있는 일" 참고)**
- **2026-08-05** — 사이트 전체가 "Oh no. Error running app."로 죽는 크래시 발생. 원인: `requirements.txt`에 streamlit 버전을 안 박아놔서, Streamlit Cloud가 재배포할 때 최신 streamlit이 새 Starlette/protobuf 조합을 끌어와 내부 GZip 미들웨어가 깨짐. `streamlit==1.50.0`으로 버전 고정해서 해결.
- **2026-08-05** — `scrape_daily.py`의 날짜 판단 로직에서 **시간대(timezone) 버그** 발견·수정. 깃허브 액션 서버는 UTC로 도는데, "15시 30분 장마감" 판단 로직은 한국시간(KST) 기준값을 UTC 시각에 그대로 비교하고 있었음 → 실행 시각에 따라 항상 하루 전 날짜로 계산되는 문제. `zoneinfo`로 KST 명시 변환하도록 수정함.
- **2026-08-05** — 오푸스 서브에이전트 2회 실행: (1) 전체 코드 감사 → `AUDIT_REPORT.md` 작성, (2) 감사 결과 기반 15개 파일 실제 수정. 하드코딩된 가짜 변동성/ROE/ROIC, 매크로 화면 임의 폴백값(코스피 2500·환율 1350), 깨진 상장주식수 파싱, 무력화된 검증 로직, 관리자 비밀번호 평문 노출 등을 고치거나 "데이터 없음"으로 정직하게 표시하도록 변경.
- **2026-08-05** — 위 모든 수정사항 전부 깃허브에 푸시 완료. (`git log` 기준 최신 커밋 `08e8140`까지 origin/main과 동기화됨)
- **2026-08-05** — 죽은 파일 7개 삭제: `patch.py`, `patch_macro.py`, `update_snapshot.py`, `templates/test_dashboard.html`, `error.log`, `output.log`, `git_history_target.txt`
- **2026-08-05** — `market_history.csv`에 8/4 데이터 백필 완료 (실제 코스피 종가/환율/수급 기준, 임시값 아님)
- **2026-08-05** — `scrape_daily.py`에 `target_date_override` 백필 모드 추가 (`.github/workflows/scrape.yml`의 `workflow_dispatch` 입력값으로 특정 날짜 지정 실행 가능)
- **2026-08-05** — `scrape_daily.py` 결측치 방어 로직 버그 수정 (renamed 컬럼명을 한글로 잘못 참조하던 것 → 영문으로 수정), FDR 시세 조회 시 `.ffill()` 적용
- **2026-08-05** — 자동화 워크플로우 정비: 미작동 상태였던 `.github/workflows/schedule.yml`(git에 올라간 적 없는 죽은 파일) 삭제, `scrape.yml` 하나로 통합. 실행 시각을 KST 17:00→16:05로 변경(원하는 시간대에 맞추고, 정각 혼잡 회피), `collector_kospi200.py`가 자동화에서 빠져있던 것을 추가

## 4. 지금 열려있는 일 (다음에 반드시 확인/처리할 것)

1. **🟡 PEGY 화면 200종목 중 147종목만 검증 통과.** 나머지 53종목이 왜 "데이터 없음"인지는 아직 원인 미조사 (상장주식수 문제는 해결됐지만, 다른 지표 결측일 수 있음). 급한 불은 껐으니 급하지 않지만, 다음에 시간 될 때 어떤 종목들이 왜 빠졌는지 확인 필요.
2. **🟡 관리자 비밀번호(`ADMIN_PASSWORD_HASH`) 설정 여부 미확인.** 예전 비밀번호는 유출로 간주하고 폐기했음. Streamlit Cloud Secrets에 새 해시값을 등록하기 전까지는 관리자 모드 접근이 아무도 안 됨(의도된 동작). 설정법은 `views/admin_view.py` 상단 주석 참고.
3. **🟡 `AUDIT_REPORT.md`에 남아있는 보류 항목** — 오너 판단이 필요해서 일부러 안 건드린 것들: SPEC §5-4 역성장 종목 처리 방식 변경 여부, 총배당금 실제 교차검증(새 데이터 소스 필요), 비밀번호 해시를 bcrypt로 업그레이드할지, git 히스토리에서 옛 비밀번호 완전히 지울지(`git filter-repo` 필요 — 지금은 최신 코드에서만 제거된 상태, 과거 커밋 기록엔 여전히 남아있음)
4. **⚪ 참고만** — `.python-version`, `runtime.txt` 파일은 Python 버전 우회 시도 흔적인데 효과가 없었음 (Streamlit Cloud가 무시함). 지금은 그냥 남아있는 죽은 파일이라 지워도 되고 안 지워도 상관없음.
5. **⚪ 참고만** — `GEMINI_API_KEY`는 매크로 화면 AI 코멘트 기능에만 쓰이는 선택 사항. 깃허브 Secrets에 등록 안 해도 자동화 자체는 정상 작동함(그 부분만 건너뜀).

## 5. 자동화 동작 방식 요약

- 트리거: 매일 평일 KST 16:05 (`.github/workflows/scrape.yml`의 cron), 또는 Actions 탭에서 수동(`Run workflow`)
- 순서: `collector_kospi200.py`(종목 데이터) → `scrape_daily.py`(매크로 데이터) → 변경사항 `git commit & push`
- 수동 실행 시 `target_date` 입력칸에 `YYYY-MM-DD`를 넣으면 그 날짜만 콕 집어 보정(백필) 가능. 이때는 실시간 시세 조회를 건너뛰고 그 날짜의 실제 종가만 사용함 (오늘 시세로 과거가 오염되는 걸 방지)

## 6. 다음에 코드를 또 고칠 때 지켜야 할 원칙

`ENGINEERING_SPEC.md`의 최우선 규칙: **데이터를 못 가져오면 하드코딩된 값이나 그럴듯한 가짜 숫자로 조용히 채우지 말고, 명확한 오류를 내거나 화면에 "데이터 없음"으로 표시할 것.** (오너가 가장 중요하게 생각하는 원칙 — 조용히 더미 데이터가 섞이면 어디가 문제인지 알 수 없기 때문)
