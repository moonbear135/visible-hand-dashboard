# 잘 보면 보이는 손 — Streamlit → NiceGUI 이전 종합 계획서

> 작성일 2026-08-16 · 대상 저장소 `github.com/moonbear135/visible-hand-dashboard`
> 이 문서는 **계획서**입니다. 코드는 한 줄도 바꾸지 않았습니다.
> 조사 범위: `ENGINEERING_SPEC.md`, `PROJECT_STATUS.md`, `TASK_HISTORY.md`(#95~#130), `visiblehand.py`, `views/` 6개 파일 전부, `utils/` 17개 파일 구조, `sql/`, `requirements.txt`, `index.html`, `.github/workflows/`, `tests/` 7개 스위트 + NiceGUI 공식 문서·Render 공식 문서 실조회.

---

## 0. 한 장 요약

| 항목 | 지금 (Streamlit) | 이전 후 (NiceGUI + Render) |
|---|---|---|
| 접속 경로 | `visiblehand.co.kr`(GitHub Pages) → `index.html` → **iframe** → `*.streamlit.app` | `visiblehand.co.kr` → **Render 앱 직접** (iframe 없음) |
| "Built with Streamlit" 바 | 제거 불가 (#119~#121에서 최종 결론) | **애초에 존재하지 않음** |
| 모바일 가로/세로 레이아웃 | `st.columns()`가 JS 인라인 style로 강제 쌓기 → CSS로 덮어쓰기 불가(공식 이슈 #6592) | 레이아웃이 **100% 우리 CSS** — 프레임워크가 런타임에 style을 주입하는 경로 자체가 없음 |
| `@media` 신뢰성 | iframe 뷰포트 때문에 판정이 어긋나는 것으로 의심(#126) | 최상위 문서라 `@media`·`100vw`가 정상 동작 |
| 세션/인증 | `st.session_state`(휘발) + 매 rerun마다 비밀번호 재검증 | `app.storage.user`(쿠키 서명, 서버 저장) + Supabase 토큰 |
| 데이터 파이프라인 | GitHub Actions → `data/*.json` | **완전 무변경** |
| `utils/`, `sql/`, `collector_*.py` | — | **거의 그대로 재사용** (streamlit import 3곳만 손봄) |
| 비용 | $0 (제약 큼) | 검증 단계 $0(Free) → 공개 시 Starter 유료 인스턴스 |

**핵심 판단**: 이번 이전은 "기능 재작성"이 아니라 **표현 계층(6개 뷰)만 교체**하는 작업입니다. 수집·검증·가공(`collector_*.py`, `utils/data_validator.py`, `utils/scoring*.py`, `utils/guardrail.py`, `utils/scorecard_db.py`, `utils/report_db.py`, `utils/stock_*.py`)은 프레임워크 무관 순수 파이썬이라 **손대지 않습니다**. 이게 이 프로젝트가 이전하기 쉬운 결정적 이유입니다.

---

## 1. 지금 저장소의 실제 구조 (조사 결과 사실 정리)

### 1-1. 표현 계층 (교체 대상)

| 파일 | 줄수 | 실제로 쓰는 Streamlit 위젯 (실측) |
|---|---|---|
| `visiblehand.py` | 334 | `set_page_config`, 전역 `<style>` 주입, `sidebar.markdown/radio`, 라우팅, `st.rerun()` 재렌더 트릭 |
| `views/admin_view.py` | 150 | `sidebar.text_input(password)`, `checkbox`, `session_state.admin_mode`, `form`+`number_input`×5, `date_input`, `expander` |
| `views/pegy_view.py` | 1,540 | `markdown(unsafe_allow_html)`×19(대부분 **거대 HTML 카드**), `columns`×5, `download_button`×6, `metric`×3, `text_input`, `selectbox`, `multiselect`, `checkbox`, `radio`(페이지 이동), `expander`, `json`, `<script>` 스크롤 트릭 |
| `views/us_stocks_view.py` | 1,365 | pegy와 **거의 동일 패턴** (카드 HTML + 30개 페이지네이션) |
| `views/scorecard_view.py` | 1,206 | `session_state`×29, `error`×23, `columns`×17, `text_input`×13, `form`×6, `container(key=)`, `rerun`×9, `plotly_chart`×2(원형차트), `dataframe`, `tabs`, `metric`, `selectbox`, `radio`, `secrets` |
| `views/report_view.py` | 1,030 | `session_state`×21, `caption`×21, `columns`×4, `date_input`×2, `form`, `expander`×5, `cache_resource` |
| `views/macro_view.py` | 1,428 | `tabs`(7개), `plotly_chart`, `line_chart`, `table`, `download_button`, `components.v1.html`, `radio`, `expander`×4 |

**중요한 관찰 하나**: `pegy_view.py`·`us_stocks_view.py`는 화면의 90% 이상이 **f-string으로 조립한 순수 HTML 문자열**입니다(`.q-tooltip` 툴팁 span만 51곳). 이건 NiceGUI에서 `ui.html(...)` 한 줄에 그대로 넣으면 **글자 단위로 동일하게** 렌더링됩니다. 즉 두 공개 화면의 이전 난이도는 겉보기 줄수(2,900줄)보다 훨씬 낮습니다.

### 1-2. 재사용 계층 (건드리지 않음)

- `utils/` 17개 파일 8,155줄 중 **streamlit을 import하는 파일은 단 3개**:
  - `utils/scorecard_db.py` — 이미 `try/except ImportError`로 감싸 선택적 의존(그대로 두고 `os.environ` 경로만 사용)
  - `utils/db.py` — 매크로 CSV 저장용. `st.warning/write/error/session_state` 7곳 (매크로 이전 시 처리)
  - `utils/macro_ai.py` — 매크로 전용
- `sql/*.sql` 2개 — **무변경**
- `collector_*.py`, `scrape_daily.py`, `.github/workflows/*.yml` 4개 — **무변경**
- `tests/` 7개 스위트 약 1,713체크 중 **뷰를 참조하는 건 `test_report.py`(43곳)·`test_scorecard.py`(8곳)·`test_macro_scoring.py`(6곳)뿐** → 나머지는 그대로 통과합니다 (§11-3)

### 1-3. `index.html` iframe이 왜 없어지는가

지금 구조:
```
사용자 → visiblehand.co.kr (GitHub Pages, CNAME 파일)
        → index.html
        → <iframe src="...streamlit.app/?embed=true">
        → 실제 앱
```
GitHub Pages는 정적 파일만 서빙하므로 "커스텀 도메인 + 파이썬 앱"을 붙이려면 iframe 우회밖에 없었고, Streamlit Community Cloud는 iframe 임베드 시 `embed=true`를 사실상 요구하며(#121에서 503으로 실측 확인), `embed=true`는 "Built with Streamlit" 바를 **항상** 붙입니다.

NiceGUI + Render 구조:
```
사용자 → visiblehand.co.kr (DNS A 레코드 → Render)
        → Render 웹서비스 (Docker 컨테이너, uvicorn)
        → NiceGUI 앱 (최상위 문서)
```
**앱이 직접 그 도메인의 최상위 문서가 되므로** `index.html`, `CNAME`, GitHub Pages 설정, `keep_awake.yml`(Selenium 깨우기), `keep_awake_ping.py`가 전부 불필요해집니다. 동시에 #126이 의심했던 "iframe 안에서 `@media` 판정이 어긋나는" 문제군도 원인 자체가 사라집니다.

---

## 2. NiceGUI 확인 사항 (2026-08-16 기준 실조회)

| 확인 항목 | 결과 | 출처 |
|---|---|---|
| 최신 버전 | **3.16.0** (2026-08-12 업로드), PyPI 분류 "Production/Stable" | PyPI / 릴리스 이력 |
| 스택 | FastAPI + uvicorn, 프런트는 Vue 3 + Quasar, 스타일은 Tailwind(기본) 또는 UnoCSS 선택 가능 | 공식 문서 |
| 빌드 단계 | **없음** — `python main.py` 하나로 서버 기동 (Node 불필요) | 공식 문서 |
| Plotly | `ui.plotly(fig)` — `go.Figure` **또는** dict 그대로 지원. `update_figure()`, 클릭 이벤트, 대용량 NumPy 바이너리 인코딩까지 | `/documentation/plotly` |
| 세션/스토리지 | `app.storage.user`(서버저장·쿠키식별·**서버 재시작 후에도 유지**), `.tab`, `.client`, `.browser`, `.general` 5종. `user`/`browser`는 `ui.run(storage_secret=...)` 필수 | `/documentation/storage` |
| 인증 패턴 | 공식 예제가 `BaseHTTPMiddleware` + `app.storage.user['authenticated']` + `ui.navigate.to()` | `examples/authentication/main.py` |
| 페이지 라우팅 | `@ui.page('/경로')`, 쿼리스트링은 함수 인자로 자동 바인딩 | 공식 예제 |
| 다운로드 | `ui.download.content(bytes|str, filename)` / `.file(path)` / `.from_url()` (2.14.0+) | `/documentation/download` |
| 페이지네이션 | `ui.pagination(min, max, direction_links=True, on_change=...)` (Quasar QPagination) | `/documentation/pagination` |
| 표 | `ui.table`(Quasar QTable, 컬럼 dict 스키마) / `ui.aggrid` / 그냥 `ui.html('<table>')` 도 가능 | `/documentation/table` |
| 배포 | 공식 Docker 이미지 `zauberzeug/nicegui` 제공. 또는 직접 Dockerfile로 `python main.py`. 리버스 프록시(Render) 뒤 배치 정석 | `/documentation/section_configuration_deployment` |
| 주의점 | 멀티 워커(uvicorn workers>1)는 추가 설정 필요(Redis 스토리지). **단일 인스턴스 전제로 갑니다** | 공식 문서 |

> ⚠️ 정직한 한계 고지(§0-1 정신): 아래 계획의 API 시그니처는 **공식 문서로 확인한 것**이고, "우리 화면이 실제로 어떻게 보이는지"는 **오너가 실기기로 확인해야만** 확정됩니다. #106~#130에서 배운 교훈 그대로, "될 것 같다"로 배포하지 않고 **매 단계 실기기 확인을 완료 조건에 넣습니다**(§9).

---

## 3. 목표 아키텍처

### 3-1. 파일 구조 (기존 파일을 지우지 않고 **옆에** 만듭니다 = 언제든 롤백 가능)

```
main.py                     ← 신규. NiceGUI 진입점 (ui.run)
web/                        ← 신규. 표현 계층 전부
  __init__.py
  theme.py                  ← 전역 CSS(.q-tooltip, 카드 스타일 등 기존 CSS 이식)
  layout.py                 ← 헤더 + 좌측 드로어(사이드바) + 라우팅 껍데기
  auth.py                   ← Supabase 세션 + 관리자 게이트 (단일 출처)
  state.py                  ← 데이터 로더 캐시 (읽기 전용, 전역 공유)
  components/
    tooltip.py              ← ℹ️ 툴팁 헬퍼 (기존 .q-tooltip HTML 재현 + ui.tooltip 대안)
    metric.py               ← st.metric 대체 카드 (NiceGUI에 동등 위젯 없음)
    banner.py               ← st.info/warning/error 대체 (§0-1 실패 배너)
    paging.py               ← 페이지네이션 + 상단 스크롤
  pages/
    pegy_page.py             ← views/pegy_view.py 대체
    us_stocks_page.py
    scorecard_page.py
    report_page.py
    macro_page.py
    admin_page.py
utils/                      ← 그대로 (streamlit import 3곳만 정리)
data/, sql/, tests/         ← 그대로
views/, visiblehand.py, app.py, index.html   ← 컷오버 전까지 그대로 살려둠 → 이후 archive/로 이동
```

### 3-2. 라우팅 (Streamlit 사이드바 라디오 → 진짜 URL)

| 화면 | URL | 공개 여부 |
|---|---|---|
| 한국 주식 밸류에이션 (기본) | `/` | 공개 |
| 미국 주식 밸류에이션 | `/us` | 공개 |
| 내 성적표 | `/scorecard` | 로그인 필요 (지금은 스테이징) |
| 사장님 보고서 | `/report` | 로그인 필요 (지금은 스테이징) |
| 매크로 방공망 | `/admin/macro` | 관리자 전용 |
| 관리자 콘솔 | `/admin` | 관리자 전용 |
| 헬스체크 | `/healthz` | Render용, UI 없음 |

**부가 이득**: 지금은 어느 화면을 보고 있어도 URL이 하나라 "이 화면 링크 보내줘"가 불가능한데, 이전 후에는 화면마다 고유 주소가 생깁니다. `visiblehand.co.kr/us` 같은 주소를 그대로 공유·북마크·SNS 링크에 쓸 수 있고, 검색엔진도 화면별로 인식합니다(공개 서비스 목표에 직접 기여).

### 3-3. 상태 관리 모델 전환 (가장 중요한 개념 차이)

| | Streamlit | NiceGUI |
|---|---|---|
| 실행 모델 | 상호작용마다 **스크립트 전체 재실행** | 페이지 함수는 접속 시 **1회 실행**, 이후 이벤트 콜백만 실행 |
| 화면 갱신 | `st.rerun()` (전체) | `@ui.refreshable` 붙인 **그 블록만** `.refresh()` |
| 사용자별 상태 | `st.session_state` | 페이지 함수의 **지역변수**(클라이언트별로 자연 분리) + `app.storage.*` |

이전 시 실무 규칙:
1. **`st.session_state["x"]` 중 "화면 한 번 보는 동안만 필요한 값"** (선택된 페이지 번호, 필터, 편집중 플래그) → 페이지 함수 안의 지역변수/작은 dict로. 위젯 키 지옥(#85, #114 두 번이나 오너를 괴롭힌 그 함정)이 **구조적으로 사라집니다**.
2. **"새로고침해도 남아야 하는 값"** (로그인, 관리자 모드) → `app.storage.user`.
3. **절대 금지**: 사용자 데이터를 모듈 전역 변수에 두는 것. Streamlit은 프로세스가 세션별로 격리되는 느낌을 줬지만, NiceGUI는 한 프로세스가 모든 접속자를 처리합니다. **`utils/scorecard_db.py`의 주석이 경고한 "@st.cache_resource로 클라이언트를 캐시하면 한 사람의 로그인이 모두에게 공유된다"는 위험이 NiceGUI에서는 더 쉽게 발생**하므로, `web/auth.py` 한 곳에서만 클라이언트를 만들고 반드시 클라이언트별로 보관합니다(§6).
4. 반대로 **읽기 전용 시장 데이터**(`data/*.json`)는 모듈 전역 캐시가 **오히려 정답**입니다. 지금 `@st.cache_data`로 세션마다 재파싱하던 걸, 프로세스 전체에서 1회만 파싱해 공유하면 됩니다(2.2MB짜리 `us_stocks_latest.json` 파싱 비용이 접속자 수와 무관해짐 → 공개 서비스에 유리).

---

## 4. 이전 순서 · 난이도 · 리스크

### 4-1. 순서 (권장)

```
0단계  인프라 뼈대     ─┐ 여기서 "모바일에서 진짜 되는가"를 먼저 증명
1단계  admin           ─┘ (가장 값싼 실패 지점)
2단계  pegy (공개 본진)
3단계  us_stocks (2단계 복제)
4단계  scorecard
5단계  report
6단계  macro (관리자 전용, 마지막)
7단계  컷오버 (DNS 전환) + 정리
```

**왜 이 순서인가**
- 0~1단계에서 "빈 껍데기 + 관리자 로그인"만 Render에 올려 **오너 폰으로 실제 접속**해봅니다. 이 시점에 도메인·HTTPS·WebSocket·모바일 레이아웃·로그인 유지가 전부 검증됩니다. 여기서 문제가 나면 **아직 아무것도 옮기지 않은 상태**라 손실이 0입니다.
- 2단계에 `pegy`를 두는 이유: ① 공개 기본 화면이라 가장 중요, ② 카드가 순수 HTML이라 "복붙 이식"이 되는지 여기서 판가름, ③ 툴팁·페이지네이션·다운로드·필터라는 **다른 모든 화면이 재사용할 패턴 4종**이 여기 다 있음.
- 3단계 `us_stocks`는 2단계 결과물의 복제에 가깝습니다(카드 구조 동일). 여기서 "패턴이 재사용되는가"가 확인되면 나머지는 속도가 붙습니다.
- `scorecard`를 4단계로 미루는 이유: 로그인·CRUD·차트가 얽혀 있어 가장 어렵고, **아직 스테이징(비공개) 상태라 늦게 옮겨도 사용자 피해가 0**입니다.
- `macro`는 관리자 전용 + 오너 지시로 개발 중단 상태(§PROJECT_STATUS 배너)라 **맨 뒤**. 최악의 경우 "이번엔 안 옮기고 Streamlit에 남겨둔다"는 선택지도 열려 있습니다.

### 4-2. 난이도·리스크 평가표

| 단계 | 대상 | 난이도 | 주요 리스크 | 완화책 |
|---|---|---|---|---|
| 0 | 뼈대·Docker·Render | ★★☆☆☆ | Render 환경변수/포트/헬스체크 오설정, 컨테이너 타임존 누락으로 KST 계산 어긋남 | Dockerfile에 `tzdata` 명시 설치(§8-2), `/healthz` 추가, Free 인스턴스로 먼저 검증 |
| 1 | `admin_view` | ★☆☆☆☆ | 없음에 가까움 (150줄) | bcrypt 검증 로직은 **그대로 복사**, 화면만 교체 |
| 2 | `pegy_view` | ★★★☆☆ | 카드 HTML 안의 `<script>` 스크롤 트릭은 `window.parent` 전제 → iframe 없어져서 **수정 필요**. 툴팁 51곳 | `<script>` → `ui.run_javascript('window.scrollTo(...)')` 로 교체. 툴팁은 CSS 그대로 이식 후 실기기 확인 |
| 3 | `us_stocks_view` | ★★☆☆☆ | 2단계 패턴 재사용 실패 시 중복 코드 | 2단계에서 `components/`로 공통화 강제 |
| 4 | `scorecard_view` | ★★★★★ | 로그인 세션 전환, 종목 CRUD 후 부분 갱신, 원형차트 2종, 정렬, #127~#130에서 싸웠던 "종목 관리" 줄 | §5-3의 flex 패턴 + `@ui.refreshable`. **가장 시간이 많이 드는 단계** |
| 5 | `report_view` | ★★★★☆ | 기간 선택 위젯(달력 + 이전/최신/다음 버튼)의 상태 흐름, 표가 많음. **테스트 43곳이 뷰를 참조** | 위젯 키 함정이 없어지므로 `_consume_pending_ref_date()` 같은 우회 코드가 **통째로 삭제**됨(오히려 단순해짐). 테스트는 §11-3 |
| 6 | `macro_view` | ★★★☆☆ | `st.tabs` 7개, `st.line_chart`(altair) 대체, `utils/db.py`의 streamlit 의존 | `line_chart` → `ui.plotly`. `utils/db.py`의 `st.*` 7곳을 콜백/로거로 추상화 |
| 7 | 컷오버·정리 | ★★☆☆☆ | DNS 전환 중 접속 불가 구간 | §11-1 듀얼런 절차 |

---

## 5. 오늘(2026-08-16) 겪은 버그들이 NiceGUI에서 왜 안 생기는가

### 5-1. `st.columns()` 세로 쌓임 (#106 → #126 → #127 → #128 → #129 → #130)

**Streamlit에서 왜 못 고쳤나 (TASK_HISTORY #127에 이미 정확히 기록됨)**
Streamlit은 각 칸 `<div>`에 **JS가 인라인 `style` 속성을 직접 박아넣어** 반응형 쌓기를 구현합니다(공식 이슈 #6592). CSS 우선순위 규칙상 인라인 style은 `!important`가 붙은 스타일시트 규칙보다도 강하고(정확히는 인라인 + !important만 이길 수 있음), 게다가 Streamlit이 재렌더할 때마다 다시 씁니다. 그래서 `@media` 조건부(#106/#126)도, 무조건 적용(#126)도, 컨테이너 flex 전환(#128/#130)도 전부 같은 벽에 부딪혔습니다.

**NiceGUI에서 왜 안 생기나 (구조적 이유)**
NiceGUI의 `ui.row()`/`ui.column()`/`ui.grid()`는 **클래스 이름만 붙은 평범한 `<div>`**입니다. Quasar의 `row` 클래스(= `display:flex; flex-wrap:wrap`)와 Tailwind 유틸리티 클래스로만 동작하며, **런타임에 인라인 style을 계산해서 주입하는 로직이 프레임워크 안에 존재하지 않습니다.** 즉 "프레임워크와 CSS가 싸우는" 상황 자체가 성립하지 않습니다.

⚠️ 정직하게 말하면: **NiceGUI가 알아서 잘해주는 게 아니라, 반응형 책임이 전부 우리에게 넘어옵니다.** 그래서 아래 규칙을 프로젝트 규약으로 못박아야 합니다.

### 5-2. 프로젝트 반응형 규약 (오너 지시 "모바일이라고 기능을 줄이면 안 돼"의 구현 규칙)

> **제1규칙: 좁으면 "숨긴다"가 아니라 "줄바꿈하거나 가로 스크롤한다".**
> 어떤 화면 요소도 `display:none`으로 모바일에서 사라지게 하지 않습니다. (#124에서 툴팁을 껐다가 #125에서 되돌린 그 판단을 규약으로 승격)

```python
# ── 패턴 A: 항상 한 줄을 유지해야 하는 줄 (예: 종목명 + ✏️ + 🗑️) ──────────
#    #127~#130에서 6번 싸웠던 바로 그 레이아웃. NiceGUI에서는 이게 전부입니다.
with ui.row().classes('no-wrap items-center gap-2 w-full'):
    ui.html(row_label_html).classes('flex-1 min-w-0 truncate')   # 남는 폭 다 먹고, 넘치면 말줄임
    ui.button(icon='edit',   on_click=...).props('flat dense').classes('shrink-0')
    ui.button(icon='delete', on_click=...).props('flat dense').classes('shrink-0')
# → 'no-wrap'(Quasar) 이 flex-wrap:nowrap, 'min-w-0' 이 flex 자식의 축소 금지 기본값을 풀어줌.
#    화면 폭과 무관하게 항상 한 줄. 프레임워크가 이걸 되돌리는 코드는 없음.

# ── 패턴 B: 넓은 표 (보유종목 7칸, #127에서 <table>로 해결한 그 방식 유지) ────
with ui.element('div').classes('w-full overflow-x-auto'):
    ui.html(table_html)            # 기존 <table> HTML 그대로 재사용 가능
# → 좁으면 가로 스크롤. 칸이 사라지지도, 세로로 쌓이지도 않음.

# ── 패턴 C: 진짜로 쌓여도 되는 곳 (요약 지표 3~4개 카드) ──────────────────
with ui.row().classes('w-full gap-4'):       # Quasar row 기본값 = flex-wrap: wrap
    metric_card('매입원가 합계', ...)
    metric_card('평가금액 합계', ...)
# → 넓으면 가로, 좁으면 자연스럽게 줄바꿈. **우리가 그렇게 하기로 선택한 것**이지
#    프레임워크가 강제한 게 아님. 언제든 'no-wrap' 한 단어로 뒤집을 수 있음.

# ── 패턴 D: 화면폭별로 다르게 (Tailwind 브레이크포인트) ────────────────────
ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4')
# → iframe이 없어져 뷰포트가 정직하므로 md:/lg: 판정이 정상 동작(#126이 의심했던 문제 소멸)
```

### 5-3. 툴팁 (#124 → #125)

- **1단계(권장, 무위험)**: 지금의 `.q-tooltip` + `.q-tooltiptext` CSS와 `tabindex="0"` 전략을 **글자 하나 안 바꾸고** `web/theme.py`의 `ui.add_css(...)`로 옮깁니다. `@media (max-width: 768px)`에서 `position: fixed; bottom: 64px`로 화면 하단에 고정하는 #125의 해법도 그대로. iframe이 없어져 이번엔 `@media`가 확실히 걸립니다. (덤: `bottom: 64px` 여백은 원래 "Built with Streamlit" 바를 피하려던 것인데 그 바가 사라지므로 여유값을 줄일 수 있습니다.)
- **2단계(선택, 나중에)**: Quasar 네이티브 `element.tooltip('설명')`로 교체. Quasar 툴팁은 **문서 최상단 포털에 렌더링**되어 부모 요소의 레이아웃 폭에 절대 영향을 주지 않습니다 → #124가 발견한 "숨겨진 300px 박스가 페이지 가로폭을 늘린다"는 문제군이 **원천적으로 재발 불가**. 다만 카드가 하나의 거대 HTML 문자열이라 51곳을 쪼개야 하므로 **1단계 이식이 안정된 뒤에** 별건으로 진행합니다.

### 5-4. 그 외 오늘의 버그들

| 오늘의 문제 | NiceGUI에서 |
|---|---|
| #119 "Built with Streamlit" 바 | **존재하지 않음.** 페이지 제목·파비콘은 `ui.run(title=..., favicon='💡')`로 우리가 지정 |
| #121 `embed=true` 제거 시 503 | iframe 자체가 없어 해당 없음 |
| #122/#123 `white-space:nowrap`·가로 라디오 넘침 | 원인은 CSS라 동일하게 주의해야 함. 단 `ui.radio`는 세로가 기본이고, 페이지 이동은 아예 `ui.pagination`(Quasar QPagination)으로 교체 → 옵션이 28개여도 "1 … 5 6 7 … 28" 형태로 압축 표시되어 넘침 자체가 없음 |
| #129 f-string 중괄호 이스케이프로 사이트 전체 크래시 | CSS를 f-string으로 조립할 필요가 없어짐(`ui.add_css`에 정적 문자열 1회 등록, 동적 값은 파이썬 변수로 클래스만 토글) → 같은 유형의 사고 확률 급감 |
| 크래시 시 화면에 트레이스백 노출(§0-3-4 위반) | NiceGUI 예외는 **서버 로그에만** 남고 화면은 그대로 유지됨. 우리가 `try/except` + 한국어 배너를 띄우는 지금 방식과 궁합이 더 좋음 |

---

## 6. Supabase 인증 · 세션 포팅 구체안

### 6-1. 지금 방식과 문제

```python
# views/scorecard_view.py 현재
st.session_state[SESSION_CLIENT_KEY] = create_supabase_client()   # 클라이언트를 세션에 보관
st.session_state[SESSION_USER_KEY] = user                          # 로그인 사용자
# views/admin_view.py 현재
admin_mode = bool(pw) and _verify_admin_password(pw, stored_hash)  # 매 rerun마다 재검증
```
- 브라우저 새로고침 = 세션 소멸 = **로그아웃**
- 관리자 비밀번호는 rerun마다 다시 해시 검증 (bcrypt는 의도적으로 느림 → 매 상호작용마다 비용)
- 로그인 상태가 사이드바 렌더 순서보다 늦게 확정돼 `st.rerun()` 강제 재렌더 트릭 필요(#103/#105)

### 6-2. NiceGUI 목표 설계

```python
# web/auth.py  (설계 스케치 — 실제 구현은 다음 세션)
from nicegui import app, ui
from utils.scorecard_db import create_supabase_client, ScorecardError, sign_in, sign_out

# ── 저장 위치 정책 ──────────────────────────────────────────────────────
#  app.storage.user  : 직렬화 가능한 값만. 서버에 저장되고 쿠키(서명됨)로 사용자 식별.
#                      → 로그인 토큰 2개 + 관리자 플래그만 넣음.
#  app.storage.client: 서버 메모리, 페이지 이동/새로고침 시 폐기.
#                      → Supabase 클라이언트 객체(직렬화 불가)를 여기 캐시.
#  ⚠️ 모듈 전역에는 사용자 관련 객체를 절대 두지 않음 (모든 접속자가 공유되어 버림).

def get_client():
    """이 접속(클라이언트)에 묶인 Supabase 클라이언트. 로그인 토큰이 있으면 복원."""
    client = app.storage.client.get('sb')
    if client is None:
        client = create_supabase_client()
        if client is None:
            return None
        tokens = app.storage.user.get('sb_tokens')
        if tokens:
            # 새로고침·서버 재시작 후에도 RLS가 걸린 상태로 이어짐
            client.auth.set_session(tokens['access_token'], tokens['refresh_token'])
        app.storage.client['sb'] = client
    return client

def login(email, password):
    client = get_client()
    resp = sign_in(client, email.strip(), password)     # 기존 함수 그대로 재사용
    session = getattr(resp, 'session', None)
    app.storage.user['sb_tokens'] = {
        'access_token': session.access_token,
        'refresh_token': session.refresh_token,
    }
    app.storage.user['email'] = resp.user.email
    ui.navigate.to('/scorecard')

def logout():
    client = app.storage.client.pop('sb', None)
    if client: sign_out(client)
    app.storage.user.clear()
    ui.navigate.to('/')

def is_admin() -> bool:
    return bool(app.storage.user.get('admin'))

def try_admin_login(password: str) -> bool:
    """기존 _verify_admin_password() 를 그대로 호출. 성공 시 한 번만 저장."""
    from web.admin_secret import verify_admin_password, get_admin_password_hash  # 기존 로직 이식
    stored = get_admin_password_hash()      # os.environ["ADMIN_PASSWORD_HASH"]
    if not stored:
        return False                         # 해시 미설정 시 절대 열지 않음 (기존 정책 유지)
    ok = verify_admin_password(password, stored)
    if ok:
        app.storage.user['admin'] = True
    return ok
```

**페이지 보호는 미들웨어가 아니라 페이지 단위 체크로**: NiceGUI 공식 예제는 전 페이지를 막는 `AuthMiddleware`를 쓰지만, 우리는 `/`·`/us`가 **공개**여야 하므로 미들웨어 대신 각 페이지 함수 첫 줄에서 확인합니다.

```python
@ui.page('/scorecard')
def scorecard_page():
    with layout('📊 내 성적표'):
        if not app.storage.user.get('sb_tokens'):
            render_login()          # 로그인 폼만 그리고 종료 (기존 _render_auth 이식)
            return
        render_scorecard_body()
```

### 6-3. 이 전환으로 얻는 것 / 주의할 것

**얻는 것**
- 새로고침해도 로그인 유지 (지금은 풀림) — 공개 서비스에 필수
- 관리자 비밀번호를 **한 번만** 검증 (bcrypt 비용 1회)
- `st.rerun()` 강제 재렌더 트릭(#103/#105)과 위젯 키 함정(#85/#114) 코드가 **삭제** 대상이 됨
- "내 성적표"와 "사장님 보고서"가 같은 로그인을 공유하던 구조(`SESSION_USER_KEY` 공유)는 `app.storage.user` 하나로 더 깔끔하게 유지됨

**주의할 것 (반드시 계획에 반영)**
1. `storage_secret`은 **환경변수 필수**. 없으면 앱이 기동을 거부하고 로그에 이유를 남깁니다(기본값 하드코딩 금지 = §0-1 정신, `admin_view.py`가 `ADMIN_PASSWORD_HASH` 없을 때 관리자 모드를 아예 안 여는 것과 같은 원칙).
2. `app.storage.user`는 서버 파일(`.nicegui/`)에 저장되는데, **Render는 파일시스템이 휘발성**입니다. 재배포·재시작하면 로그인이 전부 풀립니다 → §8-5에서 다루는 "배포 빈도" 설계와 직결됩니다.
3. `service_role` 키는 지금처럼 **GitHub Actions에만** 두고 앱에는 절대 넣지 않습니다(`utils/report_db.py` 주석의 정책 유지).
4. Supabase의 비밀번호 재설정(코드 방식, #109/#110)은 **더 좋아집니다**: Streamlit이 URL 해시 프래그먼트를 못 읽어서 코드 입력 방식을 택했는데, NiceGUI는 자체 라우팅이 있으므로 향후 링크 방식도 가능해집니다. **단, 지금 잘 동작하는 코드 방식을 이번 이전에서는 그대로 유지**하고(무변경 이식), 링크 방식 전환은 별건으로 미룹니다.

---

## 7. Plotly 호환성

**결론: 그대로 씁니다. 코드 수정이 거의 없습니다.**

| 지금 | 이전 후 |
|---|---|
| `st.plotly_chart(fig, use_container_width=True)` | `ui.plotly(fig).classes('w-full h-80')` |
| `px.pie(names=..., values=..., hole=0.35)` + `fig.update_traces(...)` (scorecard 원형차트 2종) | **완전 동일** — figure 만드는 코드는 한 줄도 안 바뀜 |
| `st.line_chart(df)` (macro, 내부적으로 altair/vega) | 동등 위젯 없음 → `ui.plotly(go.Figure(...))` 또는 `ui.echart(...)`로 **재작성 필요** (macro 1곳) |
| `PLOTLY_AVAILABLE` try/except 폴백 | 유지 가능. 단 `requirements.txt`에 plotly가 이미 있어 실사용상 항상 True |

부가 확인 사항:
- `ui.plotly`는 `go.Figure`와 `{'data':..., 'layout':...}` dict를 **둘 다** 받습니다. 데이터가 많으면 dict 쪽이 빠릅니다(원형차트 정도는 무관).
- 차트 크기: Streamlit의 `use_container_width=True` 대신 Tailwind 클래스(`w-full h-80`)로 지정합니다. **높이를 반드시 줘야 합니다** — 안 주면 0px로 그려집니다(첫 이식 때 흔한 실수, 검증 항목에 포함).
- `plotly` 패키지 버전은 기존 그대로. NiceGUI가 Plotly 6.x의 바이너리 인코딩을 활용하지만 우리 데이터 규모에선 무관.

---

## 8. 인프라 · 배포 계획 (Render)

### 8-1. 전체 그림

```
GitHub(main) ──push──▶ Render 웹서비스 (Docker 빌드 → 컨테이너 실행)
                              │
   DNS: visiblehand.co.kr ────┘  (A 216.24.57.1  /  www CNAME → *.onrender.com)
                              │
                        Render 관리형 TLS (Let's Encrypt 자동, 무료)
                              │
GitHub Actions (수집) ──commit data/*.json──▶ (§8-5 정책에 따라 재배포 또는 런타임 로드)
Supabase (Auth + holdings + snapshots) ◀── 앱이 anon 키로만 접근
```

### 8-2. Dockerfile 초안

```dockerfile
# Dockerfile  (저장소 루트)
FROM python:3.12-slim

# ⚠️ tzdata 필수 — python:*-slim 에는 타임존 DB가 없어서
#    zoneinfo.ZoneInfo("Asia/Seoul") 이 실패합니다. 우리 코드는 실패 시 naive datetime
#    으로 조용히 폴백하도록 되어 있어(utils/scheduler.py, utils/db.py 등),
#    설치를 빼먹으면 KST 기준 날짜가 UTC로 어긋난 채 "정상처럼" 동작합니다 (§0-1 위반).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render 는 PORT 환경변수를 주입합니다. main.py 가 이걸 읽습니다.
ENV PORT=10000
EXPOSE 10000

CMD ["python", "main.py"]
```

```python
# main.py  (초안)
import os
from nicegui import app, ui

import web.theme            # 전역 CSS 등록
from web.pages import pegy_page, us_stocks_page, scorecard_page, report_page, admin_page, macro_page  # noqa: F401  (@ui.page 등록용)

@app.get('/healthz')
def healthz():
    """Render 헬스체크 · 무료 인스턴스 깨우기용. UI를 그리지 않아 가볍습니다."""
    return {'ok': True}

STORAGE_SECRET = os.environ.get('NICEGUI_STORAGE_SECRET')
if not STORAGE_SECRET:
    # 기본값을 지어내지 않습니다 (§0-1). 로그에 이유를 남기고 기동 실패시킵니다.
    raise SystemExit(
        '[기동 실패] 환경변수 NICEGUI_STORAGE_SECRET 가 설정되지 않았습니다. '
        'Render 대시보드 → Environment 에 임의의 긴 난수 문자열을 등록하세요.'
    )

ui.run(
    host='0.0.0.0',
    port=int(os.environ.get('PORT', 8080)),
    title='잘 보면 보이는 손',
    favicon='💡',
    storage_secret=STORAGE_SECRET,
    reload=False,          # 운영에서는 반드시 False
    show=False,            # 컨테이너에는 브라우저가 없음
    uvicorn_logging_level='info',
)
```

> `requirements.txt`는 컷오버 전까지 **streamlit을 남겨둔 채** `nicegui` 를 추가합니다(듀얼런). 컷오버 후 `streamlit`, `altair`, `typing_extensions` 제거.

### 8-3. Render 설정 절차 (오너가 직접)

1. render.com 가입 (GitHub 계정 연동) — **무료**
2. New → **Web Service** → 저장소 `moonbear135/visible-hand-dashboard` 연결
3. 설정값
   - Language/Runtime: **Docker** (루트 `Dockerfile` 자동 인식)
   - Region: **Singapore** (한국 사용자 기준 지연 최소)
   - Branch: `main`
   - Instance Type: **Free** (0~1단계 검증용) → 공개 직전 **Starter**로 변경
   - Health Check Path: `/healthz`
4. Environment 탭에 환경변수 등록 (**Streamlit Secrets에 있던 값을 그대로 옮김**)
   ```
   NICEGUI_STORAGE_SECRET = (임의의 긴 난수, 예: openssl rand -hex 32 결과)
   ADMIN_PASSWORD_HASH    = (기존 값 그대로)
   SUPABASE_URL           = (기존 값 그대로 — 베이스 프로젝트 URL, REST 경로 포함 금지)
   SUPABASE_ANON_KEY      = (기존 값 그대로)
   SCORECARD_ENABLED      = (스테이징 유지하려면 등록하지 않음)
   REPORT_ENABLED         = (동일)
   GEMINI_API_KEY / KRX_OPENAPI_KEY = (매크로 이전 시에만)
   ```
   ⚠️ `service_role` 키는 **여기 절대 넣지 않습니다** (GitHub Actions 전용).
5. 첫 배포 → `https://<서비스명>.onrender.com` 접속 확인

### 8-4. 커스텀 도메인 연결 (`visiblehand.co.kr`)

1. Render 대시보드 → 서비스 → **Settings → Custom Domains** → `visiblehand.co.kr` 과 `www.visiblehand.co.kr` **둘 다 추가**
2. 도메인 등록기관(현재 CNAME 파일로 GitHub Pages를 쓰고 있으므로, 그 DNS 관리 화면)에서:
   - **`AAAA` 레코드가 있으면 전부 삭제** (Render는 IPv4만 씀 — 공식 문서 명시 경고)
   - 기존 **GitHub Pages용 A 레코드 4개**(`185.199.108~111.153`) **삭제**
   - 루트 도메인 `visiblehand.co.kr`:
     - DNS 제공자가 `ALIAS`/`ANAME`을 지원하면 → `ALIAS visiblehand.co.kr → <서비스명>.onrender.com` (권장)
     - 지원 안 하면 → **`A` 레코드 `216.24.57.1`**
   - `www` → **`CNAME` → `<서비스명>.onrender.com`**
   - (Cloudflare를 쓰는 경우엔 A가 아니라 **반드시 CNAME**을 쓰라고 공식 문서가 명시)
3. Render가 도메인 검증 후 **TLS 인증서를 자동 발급·자동 갱신** (무료 인스턴스 포함 전 플랜 지원). HTTPS 리디렉션도 Render가 처리 → 우리 코드에는 SSL 설정이 전혀 필요 없습니다.
4. DNS 전파 확인: `dnschecker.org` 또는 `nslookup visiblehand.co.kr`

**전환 전 리허설 방법(권장)**: 컷오버 전에 **`beta.visiblehand.co.kr`** 서브도메인을 CNAME으로 먼저 붙여두면, 진짜 도메인·진짜 HTTPS 환경에서 오너가 폰으로 미리 전부 확인할 수 있습니다. 루트 도메인은 마지막에 딱 한 번만 바꿉니다.

### 8-5. ⚠️ 반드시 결정해야 할 것: "매일 커밋되는 데이터"와 배포의 관계

현황: GitHub Actions 워크플로우 3개(`scrape.yml`, `scrape_us.yml`, `scrape_report_snapshots.yml`)가 매일 `data/*.json`을 **저장소에 커밋**합니다. Render는 기본적으로 **`main`에 커밋이 올라올 때마다 자동 재배포**합니다.

| | A안: 자동 재배포 유지 | B안: 데이터를 런타임에 가져오기 |
|---|---|---|
| 방식 | 데이터 커밋 → 이미지 재빌드 → 새 컨테이너 | `utils/data_source.py` 신설. `raw.githubusercontent.com`에서 ETag 캐시로 읽음. 코드 변경 때만 재배포 |
| 코드 변경량 | 0 | 로더 1개(약 80줄) + 각 뷰의 파일 경로 호출부 |
| 하루 재배포 | 2~3회 | 0회 |
| **로그인 유지** | **재배포마다 전원 로그아웃** (`app.storage.user`가 휘발성 디스크에 있음) | 유지됨 |
| 빌드 시간 소모 | 매일 소모 (무료 파이프라인 분 한도 압박) | 거의 없음 |
| 데이터 반영 지연 | 빌드 시간(수 분) | TTL(예: 10분) |
| 실패 시 | 배포 실패 = 이전 버전 유지 | 로드 실패 → §0-1대로 화면에 빨간 배너 + 마지막 성공 시각 표시 |

**권장 로드맵**
- **0~3단계(검증기)**: A안 그대로. 사용자가 오너 혼자라 로그아웃이 문제되지 않고, 설정이 0입니다.
- **공개 전환 전(4~7단계)**: **B안으로 전환.** 이유 ① 로그인이 매일 풀리면 "내 성적표"·"사장님 보고서"의 사용자 경험이 무너집니다. ② 재배포 순간 접속자의 WebSocket이 끊깁니다. ③ 빌드 파이프라인 분을 아낍니다.
- B안 구현 시 §0-1 준수: 원격 로드 실패를 **조용히 이전 캐시로 덮지 않고**, 화면 상단에 "🚨 최신 데이터를 불러오지 못했습니다 — 지금 보이는 값은 YYYY-MM-DD HH:MM 기준입니다"를 **반드시** 표시합니다.

### 8-6. 무료 티어 vs 유료 (Render 공식 문서 확인 결과)

| 항목 | Free | Starter(유료) |
|---|---|---|
| 유휴 시 정지 | **15분 무접속 시 정지**, 다음 요청에 약 1분 콜드스타트 | 없음 |
| WebSocket | **지원됨** (정지 판정에 WebSocket 메시지도 포함, 새 WebSocket 연결로 깨어남) | 지원 |
| 커스텀 도메인 + TLS | 지원 | 지원 |
| 월 한도 | 워크스페이스당 750 인스턴스-시간 | 없음 |
| 셸 접속/영구 디스크/스케일 | 불가 | 가능 |

→ **0~3단계는 Free로 충분**(콜드스타트 1분은 오너 혼자 테스트할 때 감수 가능). **공개 전환 시점에 Starter로 승격**. 오너 예산(월 $5~7)에 부합합니다. 참고로 지금 쓰는 `keep_awake.yml` + Selenium 스크립트는 **유료 전환 시 완전히 삭제**되고, Free 유지 시에도 `curl https://.../healthz` 한 줄로 대체됩니다.

---

## 9. 단계별 검증 방법 (각 단계의 "완료" 기준)

> 🆕 **로컬 LAN 실기기 확인**: `ui.run(host='0.0.0.0', port=8080)`으로 오너 PC에서 서버를 띄우면, **같은 Wi-Fi의 폰에서 `http://<PC의 내부IP>:8080` 으로 바로 접속**할 수 있습니다. #106→#130 여섯 번의 왕복이 필요했던 이유는 "배포해야만 실기기에서 볼 수 있어서"였는데, 이제 **배포 전에 폰에서 확인**할 수 있습니다. 이게 이번 이전의 숨은 최대 이득입니다.

### 공통 완료 기준 (매 단계)

- [ ] `python -m py_compile main.py web/**/*.py` 통과
- [ ] `python tests/test_quant.py` 등 **7개 스위트 전부 통과**(회귀 0). 뷰를 참조하는 검사는 §11-3 정책대로 갱신
- [ ] `git diff -w --stat` 이 **이번 단계에서 만지기로 한 파일만** 보여줌
- [ ] 로컬 실행 후 **데스크탑 브라우저 + 오너 폰(LAN)** 양쪽 확인
- [ ] 브라우저 콘솔에 JS 에러 0건, 서버 로그에 예외 0건
- [ ] 화면에 파이썬 함수명·파일경로·트레이스백이 **한 글자도** 노출되지 않음 (§0-3-4)

### 단계별 추가 기준

| 단계 | 완료 판정 |
|---|---|
| **0. 뼈대** | ① `https://<서비스>.onrender.com` 이 뜬다 ② `/healthz` 가 `{"ok":true}` ③ 폰 세로/가로 모두 **가로 스크롤이 0px** ④ 페이지 새로고침해도 `app.storage.user` 값이 유지된다 ⑤ 서버 로그에 KST 시각이 정확히 찍힌다(tzdata 확인) |
| **1. admin** | ① 잘못된 비밀번호로 진입 불가 ② 맞는 비밀번호로 진입 후 **새로고침해도 관리자 상태 유지** ③ `ADMIN_PASSWORD_HASH` 미설정 시 어떤 비밀번호로도 안 열림 ④ bcrypt·구 SHA-256 해시 **둘 다** 동작(기존 하위호환 유지) |
| **2. pegy** | ① 종목 카드가 데스크탑에서 **기존 화면과 눈으로 구분 안 될 정도로** 동일 ② 폰에서 **가로 스크롤 0**, 카드 안 문구가 자연 줄바꿈 ③ ℹ️ 툴팁을 **탭하면** 뜨고 다른 곳 탭하면 닫힘 ④ 페이지네이션 이동 시 **화면 최상단으로 스크롤** ⑤ CSV/JSON 다운로드 파일이 **기존과 바이트 단위로 동일** ⑥ 검색·배지 필터·착시저평가 체크박스 결과 개수가 기존과 일치 ⑦ 스냅샷 파일을 일부러 없앤 상태에서 **빨간 실패 배너**가 뜨고 숫자를 그리지 않음(§0-1 회귀 검사) |
| **3. us_stocks** | 2단계 기준 전부 + 상단 지수 3종 표시 + 30개 페이지네이션 + 한글 종목명 표기가 기존과 동일 |
| **4. scorecard** | ① 로그인/회원가입/비밀번호 찾기 3탭 전부 동작 ② **새로고침 후에도 로그인 유지** ③ 종목 추가/수정/삭제 후 화면이 **깜빡임 없이** 갱신 ④ **"종목 관리" 줄이 데스크탑·모바일 모두 한 줄**(#127~#130의 최종 목표) ⑤ 원형차트 2종이 폰에서 잘리지 않음 ⑥ 원/달러가 어디서도 합산되지 않음 ⑦🔴 **서로 다른 브라우저(시크릿창)로 동시 로그인 시 서로의 보유종목·매입가·손익이 절대 안 보임 — 실기기 수동 확인 + `tests/`에 두 클라이언트 컨텍스트를 동시에 만들어 검증하는 자동화 테스트를 반드시 추가**(§0-3-8). **이 항목이 실패하면 다른 항목이 전부 통과해도 scorecard는 절대 공개하지 않습니다** — 이 프로젝트에서 가장 심각한 실패 등급(실제 자산 정보 노출)이기 때문입니다 |
| **5. report** | ① 6기간 전부 표시 ② '◀ 이전 / 최신 / 다음 ▶' 버튼이 **실제로 기준일을 바꿈** ③ 주말·공휴일 대체 표시 안내 문구(#117)가 그대로 뜸 ④ 벤치마크·비중 변화 표 숫자가 기존 화면과 일치 |
| **6. macro** | ① 관리자만 진입 가능 ② 7개 탭 전부 렌더 ③ `line_chart` 대체 차트가 기존과 같은 계열·같은 값 ④ CSV 다운로드 동작 |
| **7. 컷오버** | ① `beta.visiblehand.co.kr`에서 오너가 **전 화면 실기기 최종 확인 완료** ② 루트 DNS 전환 후 `visiblehand.co.kr` HTTPS 정상 ③ `www.` 도 정상 ④ 전환 후 24시간 내 서버 로그 예외 0건 ⑤ 기존 Streamlit 앱은 **아직 살아있음**(즉시 되돌릴 수 있는 상태) |

---

## 10. 오너가 직접 할 일 vs 어시스턴트가 코드로 할 일

### 오너만 할 수 있는 일 (계정·결제·DNS·실기기)

| 시점 | 할 일 | 예상 소요 |
|---|---|---|
| 0단계 전 | Render 가입(GitHub 연동). **결제수단 등록은 아직 안 해도 됨** | 5분 |
| 0단계 | 웹서비스 생성 + 환경변수 6~7개 등록 (§8-3) | 15분 |
| 0단계 | `NICEGUI_STORAGE_SECRET` 난수 생성 (본인 PC에서 `python -c "import secrets;print(secrets.token_hex(32))"`) | 1분 |
| **매 단계** | **실기기(폰) 확인 및 스크린샷 피드백** ← 지금까지 해오던 그대로, 가장 중요 | 단계당 10분 |
| 4단계 전 | Supabase 대시보드에서 아무 설정 변경 없음 확인(스키마·RLS·Auth 그대로 씀) | 5분 |
| 7단계 전 | `beta.visiblehand.co.kr` CNAME 추가 (리허설용) | 10분 |
| 7단계 | 루트 도메인 DNS 전환: AAAA 삭제 → GitHub Pages A 4개 삭제 → Render A(`216.24.57.1`) 추가 | 15분 |
| 공개 전환 시 | Render 인스턴스 Free → **Starter 승격(결제수단 등록)** | 5분 |
| 컷오버 후 | GitHub Pages 설정 해제, Streamlit Cloud 앱 정지(단, **최소 2주는 살려둠** §11-1) | 10분 |

### 어시스턴트가 코드로 처리하는 일

- `main.py`, `web/` 전체 신규 작성 (뼈대·테마·레이아웃·인증·6개 화면)
- 기존 HTML/CSS 이식 및 반응형 규약 적용
- `Dockerfile`, `render.yaml`(선택), `.dockerignore`
- `utils/db.py`·`utils/macro_ai.py`의 streamlit 의존 제거(콜백/로거로 추상화)
- `requirements.txt` 갱신
- `tests/` 뷰 참조 검사 갱신 + NiceGUI 화면 배선 검사 신설
- `ENGINEERING_SPEC.md` §6 파일별 역할표, `PROJECT_STATUS.md` §2 구조표 갱신 (§0-2 절차)
- 컷오버 후 `views/`·`visiblehand.py`·`app.py`·`index.html`·`CNAME`·`keep_awake*` 정리 → `archive/` 이동

---

## 11. 위험 요소와 완화 방안

### 11-1. 듀얼런 · DNS 전환 전략 (가장 중요)

```
현재 ─────────────────────────────────────────────────────────────▶ 시간
Streamlit 앱     ████████████████████████████████████░░░░░░░░  ← 컷오버 후 2주 더 유지
NiceGUI(Render)      ░░░░████████████████████████████████████
DNS(visiblehand.co.kr)  ──── GitHub Pages ────────┤ 전환 ├──── Render ────
beta.visiblehand.co.kr       ────────── Render(리허설) ──────
```

원칙 5가지:
1. **Streamlit 코드를 지우지 않습니다.** 이전 기간 내내 `views/`·`visiblehand.py`가 그대로 살아있고 Streamlit Cloud 앱도 계속 돕니다. 어떤 단계에서 막혀도 오너 서비스는 멀쩡합니다.
2. **DNS는 전 화면 검증이 끝난 뒤 딱 한 번** 바꿉니다. 부분 이전 상태로 도메인을 넘기지 않습니다.
3. 전환 전에 **`beta.` 서브도메인으로 진짜 도메인·진짜 HTTPS 리허설**을 합니다.
4. 전환 시각은 **주말 낮**(장 마감 후, 수집 워크플로우가 도는 평일 16:05 KST를 피해서).
5. 전환 후 **최소 2주간 Streamlit 앱을 살려둡니다.** DNS만 되돌리면 즉시 롤백됩니다(TTL을 전환 전날 300초로 낮춰두면 롤백이 5분 내에 반영).

### 11-2. 기술적 위험 목록

| 위험 | 가능성 | 영향 | 완화 |
|---|---|---|---|
| 이식한 카드 HTML이 Quasar/Tailwind 기본 스타일과 충돌해 색·간격이 어긋남 | 중 | 중 | 카드 HTML을 `ui.element('div').classes('vh-scope')`로 감싸고 스코프 CSS 사용. 2단계에서 **화면 비교 스크린샷**으로 판정 |
| NiceGUI가 Tailwind를 기본 로드해서 우리 CSS와 섞임 | 중 | 낮 | 우리 CSS를 `ui.add_css`로 **나중에** 등록(후순위 우선). 필요 시 `ui.run(tailwind=False)`도 선택 가능 |
| 다중 사용자 상태 오염(한 사람 데이터가 다른 사람에게) | **낮지만 치명적** | **최상** | 모듈 전역에 사용자 객체 금지 규칙(§3-3), 4단계 완료 기준에 **시크릿창 동시 접속 검사** 명시 |
| Render 재배포 시 로그인 전원 해제 | 높(A안일 때) | 중 | §8-5 B안으로 전환 |
| Render 무료 인스턴스 콜드스타트(1분)를 오너가 "죽었다"고 오인 | 중 | 낮 | 검증기에만 사용, 공개 전 Starter 승격 |
| 메모리 부족 (`us_stocks_latest.json` 2.2MB 등 총 ~10MB JSON) | 낮 | 중 | 전역 1회 파싱 공유(오히려 Streamlit보다 유리). `us_stocks_raw_latest.json`(4.3MB)은 **화면에서 안 읽으므로 로드 금지** 확인 |
| WebSocket 끊김(모바일 화면 잠금 등) | 중 | 낮 | NiceGUI가 `reconnect_timeout`·메시지 히스토리로 자동 재연결 |
| Supabase 파이썬 SDK의 `set_session` 시그니처가 버전에 따라 다름 | 중 | 중 | 4단계 착수 시 설치된 `supabase` 버전으로 **실호출 확인** 후 확정 |

### 11-3. 테스트 자산 보호

지금 7개 스위트 약 1,713체크 중:
- **그대로 통과**: `test_quant.py`, `test_us_scoring.py`, `test_us_stocks.py`, `test_stock_history.py`, `test_macro_scoring.py` 대부분 — 순수 로직 검사라 프레임워크 무관
- **갱신 필요**: `test_report.py`(뷰 참조 43곳), `test_scorecard.py`(뷰 8곳 + streamlit 54곳), `test_macro_scoring.py`(뷰 6곳)

정책:
1. **로직 검사(계산·경계·데이터부족 판정)는 한 줄도 안 건드립니다.**
2. 화면 배선 검사는 "Streamlit 위젯이 있는지"에서 **"NiceGUI 페이지가 등록되어 있는지 / 필요한 함수가 호출되는지"**로 치환합니다.
3. #129의 교훈(문자열 존재 확인이 아니라 **실제 조립해보는** 런타임 검사)을 계승 — NiceGUI 화면은 `nicegui.testing`의 `User` 픽스처로 **실제 렌더 후 요소 존재 확인**이 가능해져, 지금보다 검사 품질이 올라갑니다.
4. 각 단계마다 **화면을 옮긴 뒤 같은 커밋에서 검사를 갱신**합니다(`git diff -w --stat`가 두 파일만 나오는 기존 습관 유지).

### 11-4. 원칙 문서 준수 (§0 시리즈)

- **§0-1(지어내지 않기)**: NiceGUI에서도 100% 동일. `st.error()` → `web/components/banner.py`의 빨간 배너. `st.stop()`은 페이지 함수의 `return`으로 치환.
- **§0-3-1(후행지표 전용)**: NiceGUI는 WebSocket 실시간 갱신이 쉬워서 **"실시간처럼 보이게 만들고 싶은 유혹"이 생깁니다 — 금지**. `ui.timer`로 자동 갱신하는 코드를 넣지 않습니다.
- **§0-3-2(크롤링 매너 — 상대 서버에 무리를 주지 않음)**: 이번 이전에서 수집기(`collector_*.py`)는 무변경이라 이 원칙은 그대로 유지됩니다. 단, §8-5의 "B안"(런타임에 `raw.githubusercontent.com`에서 데이터를 읽어오는 방식)을 채택하면 **그 요청 자체도 이 원칙의 적용 대상**입니다 — 접속자마다 매번 새로 받아오지 않고 ETag·TTL(예: 10분) 캐시를 반드시 두어, 우리 서비스가 커져도 GitHub 쪽에 무리한 요청을 반복하지 않도록 합니다.
- **§0-3-4(코드 노출 금지)**: NiceGUI는 예외를 화면에 안 띄우므로 자동으로 유리. 전역 예외 핸들러로 "일시적인 문제가 발생했습니다" 한국어 문구만 노출.
- **§0-3-6(신규는 스테이징 후 승인)**: `beta.` 도메인이 곧 스테이징이고, 오너 승인 후에만 루트 DNS를 바꿉니다.
- **§0-3-8(🔴 개인정보·자산 데이터 격리 — 최상위 금지사항, 2026-08-16 신설·오너 재강조로 강화)**: 이번 이전 전체에서 **가장 주의해야 할, 예외 없는 원칙**입니다. 오너 지시: *"개인 자산이 노출될 수 있는 문제는 집안환경에 따라서 예민하고 분쟁을 일으킬 수 있는 사항 … 절대로 개인정보가 꼬여서 노출되는 문제는 발생하면 안 돼."* §3-3·§6-3·§11-2에서 이미 다뤘듯, NiceGUI는 한 프로세스가 모든 접속자를 동시에 처리하므로 Supabase 클라이언트·로그인 토큰·보유종목·매입가·손익 같은 사용자별 데이터를 모듈 전역에 두면 이 원칙을 정면으로 위반합니다. **"대중 공개"라는 이 프로젝트의 최종 목표와 절대 혼동하지 않습니다** — 공개는 사용자가 스스로 선택했을 때만(미래의 명시적 동의 기능) 일어나야 하고, 지금 이 원칙이 막는 건 사용자 동의 없이 시스템 결함으로 새어나가는 것입니다. 4단계(scorecard) 완료 기준을 "시크릿창 수동 확인"에서 **"자동화 테스트 필수 + 실패 시 무조건 비공개 유지"**로 강화했습니다(§9 표 참고).
- **§0-3-9(이미 알려진·공개된 해킹 기법 방어, 2026-08-16 신설)**: 오너 지시 — "완벽한 방어는 불가능해도, 이미 널리 알려진 기본적인 취약점에는 절대 당하면 안 됨". NiceGUI 이전에서 특히 관련된 항목: ① `ui.html(...)`로 그리는 문자열에 사용자 입력이 섞이면 반드시 `html.escape()`(XSS — 기존 `_row_label_html()` 관행을 신규 화면에도 동일 적용), ② SQL은 Supabase 쿼리 빌더만 쓰고 문자열 조립 금지, ③ `NICEGUI_STORAGE_SECRET`도 `service_role`급 비밀로 취급해 앱 코드·로그에 노출 금지, ④ 로그인 후 이동(`ui.navigate.to()`)에 사용자 조작 가능한 URL을 검증 없이 쓰지 않음(오픈 리다이렉트), ⑤ HTTPS는 Render가 자동 강제(§8-4). 4단계(scorecard) 착수 전 이 체크리스트를 한 번 더 훑습니다.
- **§0-3-10(코드 단순성·중복 금지, 2026-08-16 신설)**: 듀얼런(§11-1)은 "검증될 때까지"의 임시 상태이지 무기한 방치가 아닙니다 — 컷오버 후 2주 뒤 옛 코드를 반드시 `archive/`로 정리합니다(부록 B). 새로 짜는 `web/` 코드도 §4-1의 순서(pegy에서 공용 컴포넌트를 먼저 만들고 us_stocks가 재사용)를 지켜, 같은 로직을 화면마다 복붙하지 않습니다.
- **§0-2 / §0-3-5**: 매 단계 종료 시 `PROJECT_STATUS.md` 갱신 + `git push`까지 완료.

---

## 12. 작업 규모감

| 단계 | 상대 규모 | 근거 |
|---|---|---|
| 0. 인프라 뼈대 | **1** (기준 단위) | 신규 코드 약 300줄 + Render 설정 |
| 1. admin | **0.5** | 150줄, 로직 복사 |
| 2. pegy | **4~5** | HTML은 복붙, 실작업은 공용 컴포넌트 설계 |
| 3. us_stocks | **2** | 2단계 컴포넌트 재사용 |
| 4. scorecard | **6~7** | 인증 + CRUD + 부분 갱신 + 차트. **가장 큰 단계** |
| 5. report | **4~5** | 표가 많지만 위젯 키 우회 코드 삭제로 상쇄 |
| 6. macro | **3** | 탭 7개 + 차트 대체. **선택적으로 연기 가능** |
| 7. 컷오버·정리 | **1** | DNS + 문서 갱신 |
| **합계** | **약 22~25** | 0단계를 1로 봤을 때 |

체감 기준: **0~2단계(약 6)만 끝나면 "이 길이 맞는지"가 확실히 판명**되고, 3단계까지 가면 **공개 화면 2개가 전부 새 프레임워크로 옮겨져** 이전의 가장 큰 가치를 이미 손에 넣습니다. 4~6단계는 비공개 화면이라 여유 있게 진행해도 됩니다.

---

## 13. 다음 세션에서 바로 할 일 (오너용 체크리스트)

**어시스턴트에게 이렇게 말하면 됩니다: "이전 계획서 0단계 시작해줘."**

세션 시작 전 오너가 준비할 것:
1. [ ] render.com 가입 (GitHub 계정으로) — 결제수단 등록 불필요
2. [ ] 본인 PC에서 난수 생성해 메모: `python -c "import secrets;print(secrets.token_hex(32))"`
3. [ ] 현재 Streamlit Cloud Secrets 값을 손 닿는 곳에 복사해두기 (`ADMIN_PASSWORD_HASH`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, 그 외)
4. [ ] `visiblehand.co.kr` **DNS를 어디서 관리하는지** 확인 (도메인 등록기관 로그인 가능한지)
5. [ ] 폰과 PC가 **같은 Wi-Fi**에 있는지 확인 (LAN 실기기 확인용)

0단계에서 어시스턴트가 만들 것:
- `Dockerfile`, `.dockerignore`, `main.py`, `web/theme.py`, `web/layout.py`, `web/auth.py`
- 임시 확인용 페이지: 헤더 + 드로어 + "모바일 레이아웃 4패턴 데모"(§5-2의 A~D를 실제로 그려서 폰으로 눈으로 확인)
- `requirements.txt`에 `nicegui` 추가 (streamlit은 유지)

**0단계의 완료 = "오너 폰에서 `<서비스명>.onrender.com` 을 열었을 때, 좌우로 아무리 밀어도 화면이 안 밀리고, 한 줄로 고정된 줄은 데스크탑에서도 모바일에서도 한 줄로 나온다"** — 이게 확인되면 #106~#130의 전투가 구조적으로 끝났다는 증명입니다.

---

## 부록 A. Streamlit → NiceGUI 위젯 대응표

| Streamlit | NiceGUI | 비고 |
|---|---|---|
| `st.markdown(html, unsafe_allow_html=True)` | `ui.html(html)` | 기존 카드 HTML 그대로 이식 가능 |
| `st.markdown("<style>...")` | `ui.add_css(css)` / `ui.add_head_html(...)` | 페이지당 1회. f-string 중괄호 사고(#129) 회피 |
| `st.columns([4, .6, .6])` | `ui.row().classes('no-wrap ...')` + 자식 `flex-1 min-w-0` / `shrink-0` | §5-2 패턴 A |
| `st.container(key=...)` | `ui.column()` / `ui.element('div').classes(...)` | `.st-key-` 클래스 해킹 불필요 |
| `st.expander` | `ui.expansion('제목')` | |
| `st.tabs([...])` | `ui.tabs()` + `ui.tab_panels()` | |
| `st.form` + `st.form_submit_button` | `ui.card()` + `ui.button(on_click=...)` | Enter 제출은 `.on('keydown.enter', ...)` |
| `st.text_input` | `ui.input(label)` | |
| `st.text_input(type="password")` | `ui.input(label, password=True, password_toggle_button=True)` | |
| `st.number_input` | `ui.number` | |
| `st.selectbox` | `ui.select(options)` | |
| `st.multiselect` | `ui.select(options, multiple=True)` | |
| `st.radio(horizontal=True)` | `ui.radio(...).props('inline')` / `ui.toggle` | #123의 넘침은 `ui.pagination`으로 대체 |
| `st.checkbox` | `ui.checkbox` | |
| `st.date_input` | `ui.date` | |
| `st.button(icon=":material/edit:")` | `ui.button(icon='edit')` | Material 아이콘 그대로 |
| `st.metric` | 동등 위젯 없음 → `web/components/metric.py` 자작 | |
| `st.dataframe` / `st.table` | `ui.table` / `ui.aggrid` / `ui.html('<table>')` | 보유종목 표는 **#127의 `<table>` 방식 유지 권장** |
| `st.plotly_chart(fig, use_container_width=True)` | `ui.plotly(fig).classes('w-full h-80')` | 높이 클래스 필수 |
| `st.line_chart` | `ui.plotly` 또는 `ui.echart` | macro 1곳 재작성 |
| `st.download_button` | `ui.button(on_click=lambda: ui.download.content(data, name))` | |
| `st.info/warning/error/success` | 일시 `ui.notify(...)` / 지속 `banner.py` 자작 카드 | §0-1 실패 배너는 반드시 지속 표시 쪽 |
| `st.session_state` | 페이지 함수 지역변수 + `app.storage.user/tab/client` | §3-3 |
| `st.rerun()` | `@ui.refreshable` + `.refresh()` | |
| `st.cache_data` | 모듈 전역 dict 캐시 (읽기 전용 데이터만) | |
| `st.cache_resource` | 모듈 전역 싱글턴 | ⚠️ 사용자별 객체 금지 |
| `st.secrets` | `os.environ` (Render Environment) | |
| `st.stop()` | 페이지 함수에서 `return` | |
| `st.set_page_config` | `ui.run(title=, favicon=)` | |
| `st.sidebar` | `ui.left_drawer()` | 모바일에서 햄버거로 접힘(Quasar 기본) |
| `st.query_params` | `@ui.page('/x')` 함수 인자 자동 바인딩 | |
| `st.components.v1.html` | `ui.html` 또는 `ui.element('iframe')` | macro 1곳 |
| (없음) | `ui.run_javascript('window.scrollTo(...)')` | 기존 `window.parent` 스크롤 트릭 대체 |

## 부록 B. 컷오버 후 삭제·보관 대상

| 파일 | 처리 |
|---|---|
| `index.html` | **삭제** |
| `CNAME` | **삭제** |
| `visiblehand.py`, `app.py` | `archive/` 이동 |
| `views/` 6개 | `archive/streamlit_views/` 이동 |
| `keep_awake_ping.py`, `.github/workflows/keep_awake.yml` | **삭제** |
| `requirements.txt`의 `streamlit`, `altair` | 제거 |
| `ENGINEERING_SPEC.md` §0 표·§6 역할표·§10 디렉토리 | "프론트엔드: NiceGUI", "배포: Render"로 갱신 |
| `PROJECT_STATUS.md` §1·§2 | 서비스 주소·구조표 갱신 |

---

### 이 계획의 정직한 한계 (§0-1 정신)

- NiceGUI API는 공식 문서(2026-08-16 조회)로 확인했지만, 실제 HTML/CSS가 Quasar·Tailwind와 어떻게 섞일지는 실행해봐야만 압니다. 0단계를 "데모 페이지로 먼저 증명"하는 구조로 짠 이유입니다.
- `supabase` 파이썬 SDK의 `set_session()` 동작은 4단계 착수 시 실호출 확인이 필요합니다.
- Render의 Starter 요금은 오너가 대시보드에서 직접 확인해 주세요.
- 성능(동시접속 수십~수백 명)은 단일 인스턴스로 충분하다고 판단하지만, 실측 전에는 단정하지 않습니다. 그 규모가 실제로 오면 그때 재투자 판단합니다.
