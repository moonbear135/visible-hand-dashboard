# 작업 이력 (TASK_HISTORY.md)

> Cowork 진행 상황(작업 목록) 위젯에 쌓인 완료 항목들을 정리해둔 기록입니다.
> 위젯 자체는 깔끔하게 유지하기 위해 완료된 항목을 지우고, 여기에 전체 이력을 남깁니다.
> 지금 진행 중/예정 상태는 `PROJECT_STATUS.md`의 "지금 열려있는 일"을 참고하세요.

📦 **#1~#153(2026-08-28 이전, 이미 마무리된 오래된 구간)은 `TASK_HISTORY_ARCHIVE.md`로 옮겼습니다** — 번호나 키워드로 옛 항목을 찾아야
할 때만 그 파일을 여세요. 아카이브 기준·경위는 #172, 이 관행 자체의 정책은
`ENGINEERING_SPEC.md` §0-3-14 참고.

---

## 완료된 작업 (시간순)

154. **🚨 `watch_schedule_health.yml` — 예약 실행(schedule) 감시 워치독 신설
     (2026-08-28, 오너 요청 — "우연찮게 내가 주문 넣어놓은게 실패로 떠서 알았지
     안그러면 몰랐을꺼 같니야").** `scrape.yml`의 schedule 트리거가 2026-08-27
     (11시간 넘게 지연)·2026-08-28(6시간 넘게 미발동) 이틀 연속 문제를 겪었는데,
     이걸 듀얼게임 주문 취소로 우연히 알게 된 것이 문제라는 오너 지적으로 시작.
     GitHub Actions API(`gh api .../actions/workflows/{file}/runs?event=schedule`)
     로 최근 실행 기록을 조회해 확인하는 방식. `AskUserQuestion`으로 "저장소 워치독
     워크플로우 vs Claude/Cowork 매일 확인" 두 옵션을 제시했고, 오너가 저장소
     워치독(권장) 선택 — 이어서 "scrape.yml 하나뿐이냐, 다른 크롤링도 한두 개가
     아닌데"라고 범위를 되물어, scrape.yml 하나가 아니라 저장소의 schedule 트리거
     워크플로우 전체를 훑어(`grep -l "schedule:" .github/workflows/*.yml`) 아래
     9개로 감시 범위를 넓힘: `scrape.yml`·`scrape_us.yml`·`indicator_kr.yml`·
     `scrape_report_snapshots.yml`·`duel_daily.yml`(평일 전용), `duel_daily_us.yml`·
     `scorecard_publish_daily.yml`·`watch_dividend_disclosures.yml`·
     `watch_dividend_payment_events.yml`(매일).
     일부러 뺀 것 — `keep_awake.yml`/`render_keep_awake.yml`(데이터 수집이 아닌
     단순 핑, 실패해도 조용히 잘못된 판단으로 안 이어짐, 주기도 너무 짧아 "하루
     한 번 확인" 방식과 안 맞음), `collect_dividend_kr.yml`(1년에 한 번만 도는
     스케줄이라 "오늘 안 돌았나" 검사 자체가 무의미 — `watch_dividend_disclosures.yml`
     이 이미 매일 안전망 역할을 함).
     매일 00:00 UTC(KST 09:00, 감시 대상 중 가장 늦게 끝나는 것 이후)에 각 대상의
     최근 schedule 실행 중 "예상 창(window)" 안에 conclusion=success 가 있는지
     확인 — 평일 전용은 주말엔 검사 자체를 건너뛰고, 월요일엔 지난 금요일 실행분
     까지 보이도록 창을 30시간 → 76시간으로 넓힘. 하나라도 빠지면 이슈 생성(오너를
     assignee 로 지정해 GitHub 기본 알림으로 이메일 발송 유도) + 잡 자체도
     실패(exit 1) 처리해 Actions 탭에 빨간 X로 남김. 비밀키 불필요(기본
     `GITHUB_TOKEN`으로 충분).
     헤더 코멘트에 한계 2가지를 정직하게 명시(§0-1) — ①이 워치독도 결국 같은
     GitHub Actions schedule 로 돌기 때문에 워치독 자신이 늦게 돌거나 안 돌 가능성을
     완전히 배제할 수 없음, ②"그 시각 tick이 정확히 발동했는지"가 아니라 "최근
     window 안에 성공 실행이 한 번이라도 있었는지"만 보므로, 이틀 연속 지연이 겹치는
     아주 드문 경우 진짜 미발동을 놓칠 가능성이 이론상 있음.
     검증 — YAML 유효성(`yaml.safe_load`, U+FFFD 0건 확인), 두 `run:` 스텝 모두
     `bash -n` 문법 통과, 핵심 판정 로직(day-of-week 창 계산 + API 응답 파싱)을
     실제 저장소의 실시간 GitHub API 응답으로 재현해 9개 대상 전부 예상대로 ✅
     판정됨을 확인(2026-08-28 22:28 KST 기준). `gh issue create` 경로는 실제
     이슈를 만드는 부작용이 있어 이번 검증에서는 실행하지 않음(아래 "진행 예정"
     참고). 커밋 `2257248`.

155. **🧪 `test_export_end_to_end` CSV 헤더 기대값 — #152 컬럼 신설을 못 따라온
     테스트 하나 수정 (2026-08-29, 결투 모듈 작업 세션이 전체 pytest를 돌리다
     발견해 넘긴 건).** 증상은 `tests/test_stock_history.py::test_export_end_to_end`
     의 "헤더 앞부분 확인"이 CSV 5번째 칸으로 `현재가(원)`을 기대하는데 실제로는
     `시장구분(KOSPI/KOSDAQ)`이 나오는 것.
     원인은 2026-08-26 `33ae5a0`(#152, 코스피/코스닥 시장 라벨 표시)에서
     `utils/stock_history.py`의 `KOSPI_HISTORY_FIELDS`에 `("market",
     "시장구분(KOSPI/KOSDAQ)", "text")`를 `code`와 `price` **사이**(5번째)에
     끼워 넣으면서 `price`가 6번째로 밀린 것. 그 커밋이 이 파일에 새 테스트 2건
     (market round-trip)은 추가했는데, 정작 예전부터 앞 5칸을 **문자열로 하드코딩**
     해 둔 이 검사(`parsed[0][:5] == [...]`)만 같이 못 고쳐 그 이후로 계속 실패
     상태였습니다.
     **어느 쪽을 고칠지 먼저 확인** — 컬럼 순서(소스)를 되돌릴 이유가 있는지 봤고,
     되돌리지 않기로 판단했습니다. 근거 ①`market`은 종목 식별 정보(날짜·순위·
     종목명·종목코드) 바로 뒤에 붙는 게 사람이 엑셀로 열었을 때 자연스럽고 #152
     커밋 메시지·TASK_HISTORY #152 모두 CSV/JSON 노출을 의도한 작업으로 적고 있음,
     ②이력 CSV를 **컬럼 위치(인덱스)로 읽는 소비자가 저장소에 하나도 없음**을
     확인 — 쓰기는 `csv.DictWriter`, 읽기는 `read_history_rows()`/
     `load_stock_history()`의 `csv.DictReader`로 전부 **영문 키 기준**이고
     (`utils/stock_history.py`), 다운로드 바이트를 만드는 `utils/stock_export.py`도
     `field_labels(FIELDS)`로 헤더를 생성. `views/pegy_view.py`·
     `views/us_stocks_view.py`·`web/pages/pegy_page.py`·`web/pages/us_stocks_page.py`
     는 `FIELDS` 상수를 통째로 넘기기만 하고 인덱스를 쓰지 않음(§0-3-10 재사용
     관례대로 로더를 공유하고 있어 인덱스 하드코딩이 애초에 없었음).
     `grep`으로 `현재가(원)` 하드코딩도 저장소 전체에서 이 테스트 한 줄뿐임을 확인.
     그래서 **소스는 그대로 두고 테스트 기대값만** 새 순서
     (`날짜·시가총액 순위·종목명·종목코드·시장구분(KOSPI/KOSDAQ)·현재가(원)`, `[:6]`)로
     맞추고, 왜 바뀌었는지(#152, `33ae5a0`)와 "인덱스 의존 소비자가 없어 순서 변경이
     안전하다"는 확인 결과를 주석으로 남겨 다음에 컬럼이 또 끼어들 때 헤매지 않게 했습니다.
     검증 — `pytest tests/test_stock_history.py -q` → `15 passed`(수정 전 동일 명령은
     `15 passed, 1 error`), `python tests/test_stock_history.py` 직접 실행도 "✅ 전체 통과".
     전체 스위트는 같은 환경에서 수정 전/후를 각각 돌려 비교(`pytest -q
     --continue-on-collection-errors`): 수정 전 `4 failed, 1487 passed, 6 errors`
     → 수정 후 `4 failed, 1487 passed, 5 errors`로, 사라진 것은 정확히
     `test_export_end_to_end` 하나뿐이고 다른 항목은 실패 목록까지 그대로 —
     회귀 없음. 남은 실패는 이번 범위 밖(배당 모듈 이벤트루프 블로킹 관련
     `tests/test_event_loop_blocking.py` 작업분과 렌더 스모크·수집기 의존성/
     네트워크 이슈)이라 손대지 않았습니다.
156. **🍝 레포 전체 스파게티 코드 감사 (2026-08-29, 오푸스 높음, 오너 요청 —**
     **"전체 파일 스파게티 코드 한번 점검 해줄래?").** 프로덕션 Python 91,528줄
     (106개 파일) + 테스트 스위트 33,280줄(29개 파일)을 8개 모듈(수집기/결투/
     스코어카드/배당KR·US/매크로·PEGY·보조지표·리포트/미국주식/공유 인프라/테스트
     스위트)로 나눠 Opus 서브에이전트가 각각 전 파일을 정독하고, 재현 실행·grep
     전수확인·AST 함수길이 측정까지 동원해 교차검증. 전체 결과는
     `SPAGHETTI_AUDIT_2026-08-29.md`(레포 루트, 커밋 `ba2b62b`)에 정리.
     결과 요약 — 높음 41건 · 중간 73건 · 낮음 66건 · 죽은 코드 10건. 가장 심각한
     5가지: ①`collector_kospi200.py`의 ETF 필터가 브랜드명 부분일치라 "BNK금융지주"
     같은 실제 상장사가 매일 유니버스에서 조용히 빠짐(순위 전체가 밀리는 부수효과
     포함), ②`utils/scoring_us.py`의 BPS 바닥값(floor) 보정이 목표가 2.5배 폭주
     방지 캡을 우회하고 교차검증을 `PBR-1` 동어반복으로 만듦(재현 실행으로 확인),
     ③결투 모듈 달러 계좌의 체결 실패 사유 문구에 "원" 단위가 그대로 남아있음
     (`utils/duel_rules.py::calculate_fill`), ④배당 KR 달력이 `today.year`에 갇혀
     12월 결산 배당의 지급예정일(보통 다음해 3~4월)에 도달할 방법이 없음
     (`web/pages/dividend_page.py`), ⑤`web/auth_ui.py`의 회원가입/비밀번호
     재설정·변경 4곳이 프로젝트 표준 블로킹 처리(`run_blocking`)를 우회해 요청이
     취소돼도 "성공" 토스트가 뜸. 이 5개는 전부 격리 수정 가능하지만 실서비스
     데이터·화면에 영향을 주는 항목이라 판단만으로 코드를 건드리지 않고 리포트에만
     남김 — 오너 검토 후 다음 라운드로.
     **바로 반영한 것(위험도 낮고 순수 격리된 항목만, 커밋 `ba2b62b`)**:
     `scrape_daily.py` 수급 크롤링 요청 `timeout=5` 누락 수정(무기한 hang 위험
     제거), `probe_indicator_universe_timing.py` 죽은 코드 제거, 배당 다운로드
     파일명 `date.today()`→`today_kst()`(UTC 배포 서버 한국 새벽 어제자 파일 문제),
     `duel_page.py`의 `ui.label`/`error_banner`에 박힌 마크다운 `**` 리터럴 7곳
     제거(마크다운 미렌더링 위젯이라 별표가 그대로 화면에 보이던 문제) + 규칙 4
     안내 문구 정정("코스피 상위 200종목뿐" → 실제 유니버스인 "코스피+코스닥
     통합 상위 500종목"), `utils/data_validator.py`의 죽은 함수 `normalize_currency`
     제거(미사용 + 실패 시 0.0을 돌려주는 형태로 방치돼 있었음), `utils/db.py`의
     미참조 `RETIRED_METRIC_COLUMNS`·`backfill_missing_metrics` 별칭 제거,
     `utils/gdrive_helper.py`의 개발자 로컬 Windows 경로가 박힌 `__main__` 블록
     제거. 검증 — 7개 파일 전부 `py_compile` 통과, `test_duel_page_usd.py`(149
     passed)·`test_dividend_us_page.py`·`test_duel.py`(176 passed, 무관한 픽스처
     경로 문제 2건 제외) 회귀 없음 확인, 삭제한 식별자를 참조하는 테스트 0건 확인.
     또한 매크로/PEGY/보조지표/리포트 모듈 감사에서 확인된 사실 — `main.py`가
     예고한 Streamlit(`views/`)/NiceGUI 듀얼런 유예기간(2026-08-17 컷오버 + 2주)이
     **2026-08-31로 이미 도래**했고, 그 안에 관리자 인증 로직의 두 번째 사본
     (`views/admin_view.py`, 평문 비밀번호가 세션에 상주하는 문제 포함)이 살아
     있어 삭제가 보안 개선도 겸함을 확인 — #157 후보로 아래 백로그에 기록.


157. **🔧 스파게티 감사 Top 5 전부 반영 (2026-08-29, 오푸스 높음, 오너 요청 —**
     **"1번에서 5번은 지금 바로 다 고쳐버리자").** #156 리포트의 Top 5를 순서대로
     수정. ①`collector_kospi200.py` — 브랜드명 부분일치 ETF 필터("BNK" 키워드가
     "BNK금융지주"를 오탐)를 걷어내고, `collector_indicator_kr.py`/
     `utils/indicator_universe.py`가 이미 쓰던 `data/kr_ticker_master.json`
     (FinanceDataReader 공식 상장종목 목록) 기반 `type == "STOCK"` 판정으로 교체
     (같은 저장소의 검증된 패턴 재사용, §0-3-10). 마스터 파일이 없거나 못 읽으면
     빈 dict → 전부 걸러짐(안전한 쪽으로, 기존 규약과 동일). `load_ticker_types()`
     신설 + 회귀 테스트 3건. ②`utils/scoring_us.py` — BPS 바닥값(floor) 보정 두
     가지 결함 수정: (A-1) `f_target_floored`/`t_fair_floored` 플래그를
     `calculate_us_quant_score()`까지 실제로 전달해, 목표가 초과 교차검증(현재는
     floor 적용 시 대수적으로 `PBR-1`의 동어반복이 되어 실효성장률과 무관한 값으로
     점수를 잘못 짓누르던 문제)을 캡 적용 종목과 동일하게 건너뛰도록 함.
     (A-2) 바닥값 자체가 2.5배 폭주 방지 캡을 넘으면 캡도 그대로 적용(캡은 산출
     경로를 안 가림). 재현 시나리오(저PBR 우량주, floor가 목표가를 밀어올려 현재가
     대비 100% "초과"로 오판정되던 case)로 점수가 20/100 → 58/100으로 정상화됨을
     확인, 회귀 테스트 10건 추가. ③`utils/duel_rules.py::calculate_fill()` — 실패
     사유 문구에 `currency` 인자(기본값 "KRW") 신설, `_fmt_currency()` 헬퍼로
     KRW="원"(접미)/USD="$"(접두, 기존 체급 문구·`format_summary_lines_usd()`와
     같은 표기 관례)를 분기. `allocate_pending_orders()`→`utils/duel_batch.py::
     plan_order_fills()`까지 그대로 관통시키고, `duel_batch_usd.py`의 호출부
     한 곳에서만 `currency="USD"`를 명시(원화 결투 배치는 기본값 그대로라 무변경).
     회귀 테스트 4건. ④`web/pages/dividend_page.py` — 연도 경계를 못 넘던
     `_shift()`/`_on_month()`(`1 <= month <= 12`)를 미국 배당 화면
     (`dividend_us_logic.py::available_months()`)과 같은 방식(데이터가 실제로
     덮는 최소~최대 달을 연도 상관없이 한 줄로 이어놓고 그 안에서 이동)으로 교체.
     새 `available_months()`(결산기준일 + 지급예정일 색인 둘 다 스캔)/
     `shift_month()`/`month_label()` 신설 — 두 배당 화면은 서로 import하지 않는
     확정 원칙(`dividend_us_logic.py` 머리말)이라 로직만 복제. 12월 결산 배당의
     익년 3~4월 지급예정일 도달 재현 테스트로 확인, 신규 테스트 파일 5건.
     ⑤`web/auth_ui.py` — 회원가입/비밀번호 재설정 코드 발송/비밀번호 변경 3곳의
     `run.io_bound()` 직접 호출을 전부 `run_blocking()`(`web/blocking.py`)으로
     교체. 취소 시 예외 없이 `None`을 돌려주던 것을 `BlockingCallAborted`로 바꿔,
     이미 있던 `except Exception`(§0-3-4 정직한 실패 배너 규약)이 대신 처리하게
     함 — 기존 예외 처리 코드는 한 글자도 안 바꿈. 특히 비밀번호 변경 경로는 취소돼도
     "✅ 비밀번호를 변경했습니다" 성공 토스트가 그대로 뜨던, Top 5 중 가장 직접적인
     사용자 피해 항목. 소스 검증 테스트 1건 추가(AST로 `run.io_bound` 직접 호출
     소멸 확인). **검증** — 5개 파일 + 관련 테스트 12건 신규, 코드 전체 기존
     스위트 재실행 결과 `sql/duel_schema.sql`·`DUEL_MODULE_WORK_ORDER.md` 등
     이 클라우드 검토용 사본에만 없는 파일 때문에 나는 실패 91건은 수정 전후
     완전히 동일(diff 0건)함을 확인 — 이번 5개 수정으로 인한 회귀 0건, 새 회귀
     테스트 12건 전부 통과.


158. **🔧 스파게티 감사 2차 — 수집기(Collectors) 모듈 41건 전부 반영 (2026-08-29,
     오푸스 엑스트라, 오너 요청 — "모듈별로 하나씩 오푸스 높음으로 검토하면서
     고쳐보자, 한번 할 때 전부 다").** `SPAGHETTI_AUDIT_2026-08-29.md`의 8개 모듈
     순회 중 첫 번째(수집기→결투→매크로 순으로 오푸스 엑스트라, 나머지는 오푸스
     높음). 대상 9개 파일(`collector_kospi200.py`/`collector_dividend_kr.py`/
     `collector_dividend_payment_kr.py`/`collector_us_stocks.py`/
     `collector_us_indices.py`/`corp_code_mapper.py`/
     `probe_indicator_universe_timing.py`/`scrape_daily.py`/
     `collector_indicator_kr.py`, 총 11,314줄) 재감사(오푸스 서브에이전트, 실행
     재현 4건 포함) 결과 나온 높음 12·중간 14·낮음 15 = 41건 중 38건 반영(M1/M2/M3
     제외 — 아래 참고), 나머지 M11 1건은 제가 직접 수정.

     **높음 12건** — ①`collector_kospi200.py`: 종목 상세 파싱 260줄을 감싸던
     단일 try/except가 재무제표 파싱 실패 시 이미 성공한 aside 스냅샷(PER/EPS/
     PBR/상장주식수)까지 통째로 버리던 문제(H1) → 구획 A(aside)/구획 B(재무제표)로
     try 분리. ②DPS 셀 파싱 실패(공백 포함 등)가 "무배당 확정"으로 오판정되던
     문제(H2) → `dps_cell_parse_error` 플래그로 구분. ③배당수익률 **행이 있기만
     하면**(값 유무 무관) 무배당 확정되던 `or` 버그(H3) → 재무제표 확인 +
     배당수익률 명시적 N/A 둘 다 만족해야 확정. ④코스피·코스닥 시가총액 순위표
     현재가/PER/ROE를 `cols[2]`/`cols[10]`/`cols[11]` 고정 인덱스로 읽던 것(H4,
     SPEC §2-1 위반) → `extract_market_sum_column_indices()`로 헤더 라벨 기반
     판정(가격 라벨 실패 시 페이지 실패로 처리해 기존 순위 무결성 가드 재사용).
     ⑤`pegy_summary_history.json` 읽기 실패 시 `history=[]`로 몇 년치 이력을
     1행으로 덮어쓰던 것(H5) → 손상 파일 백업 + 이력 갱신 스킵 + tmp/os.replace
     원자적 쓰기. ⑥`__main__` 실행 순서가 "코스피200 수집(ETF/우선주 판정에
     `kr_ticker_master.json` 필요) → 마스터 목록 생성" 순이라 항상 전날 파일
     기준이었던 것(H6) → 마스터 목록을 먼저 만들도록 순서 교체 + 신선도 경고.
     ⑦`scrape_daily.py`: `market_history.csv` 읽기 실패 시 `pd.DataFrame()`으로
     몇 년치 이력을 1행으로 덮어쓰던 것(H7) → `RuntimeError`로 즉시 중단.
     ⑧투자자별 매매동향(개인/외국인/기관) `cells[1]/[2]/[3]` 고정 인덱스 + 한 행
     파싱 실패가 5페이지 순회 전체를 중단시키던 것(H8) → 헤더 라벨 기반 열 판정
     (`extract_investor_flow_column_indices`) + 예외 범위를 행 단위/페이지
     단위로 축소. ⑨`collector_dividend_kr.py`: `run_watch_disclosures()`가
     `run_collection()`의 반환값(`completed` 여부)을 확인하지 않아 DART 예산
     초과·차단으로 중단돼도 워터마크를 전진시켜 미확인 공시 구간을 영구히
     놓치던 것(H9) → `completed=False`면 워터마크 미전진 + 사유 로그.
     ⑩`collector_us_stocks.py`: `--limit N`(테스트용 부분 수집)이 가드 없이
     프로덕션 스냅샷·이력을 덮어쓰던 것(H10) → `collector_dividend_kr.py`와
     같은 `--allow-overwrite` 가드 도입. ⑪시총÷상장주식수로 역산한 종가에 범위
     검증이 전혀 없던 것(H11) → 상식 범위 검증 + 그동안 저장만 하고 안 쓰던
     `csv_price`와 교차대조. ⑫우선주 부모(보통주) 코드를 `code[:-1]+'0'` 문자열
     추측만으로 확정해 DPS를 상속하던 것(H12) → `kr_ticker_master.json`에서 그
     코드가 실제 보통주(STOCK)로 확인될 때만 상속.

     **중간 14건·낮음 15건** — 매직넘버 상수화 다수, 죽은 코드 제거(`compute_
     roic_premium()` — 이 파일은 ROIC 원천 데이터를 수집하지 않아 `roic`가 코드
     어디서도 `None` 외의 값이었던 적이 없어 늘 0.0만 반환하던 경로, 소비부
     `pegy_view.py`/`pegy_page.py`/`scoring.py`는 전부 `.get()` 안전 접근이라
     키 제거로 인한 영향 없음 확인), 이력 중복 판정 입도 통일(분 단위→일 단위),
     역산 대신 이미 가진 실측 전일 종가 재사용, `missing_labels` 중복 보고(별칭
     라벨 둘 다 못 찾았을 때 필드 하나가 두 번 잡히던 것, 관련 테스트도 버그를
     정답으로 인코딩하고 있던 것 함께 수정) 등. **M11**(DART 엔드포인트·매너
     상수 8종이 `collector_dividend_kr.py`/`collector_dividend_payment_kr.py`
     양쪽에 각각 하드코딩 — "완전히 독립적으로 두기 위함"이 근거였는데 두 파일
     모두 이미 서로/`corp_code_mapper.py`를 import하고 있어 독립이 성립하지
     않던 항목)은 서브에이전트 지시에서 실수로 빠뜨렸던 것을 발견해 제가 직접
     `corp_code_mapper.py`로 이동·단일화(`DART_STATUS_MESSAGES`를 이미 그렇게
     공유하는 것과 같은 방식) — 회귀 0건 재확인.

     **의도적으로 손대지 않은 것** — M1(`enrich_quant_metrics()`, 591줄)/
     M2(`scrape_and_update()`, 510줄)/M3(`fetch_naver_item_dps_and_eps()`,
     300줄·10단 중첩) 3건은 순수 구조 리팩터(§0-1 위반 아님)이고, 실거래망
     검증이 안 되는 샌드박스에서 손대기엔 파급범위가 커 백로그로 유예.

     **검증** — 10개 파일(수집기 9개 + `utils/constants.py`·
     `utils/macro_scoring.py`) 수정, 61건 회귀 테스트 신규(6개 파일). 오푸스
     서브에이전트의 자체 보고를 그대로 신뢰하지 않고 이 대화방에서 직접
     재검증(오너 요청 — "전체 검증은 이 채팅방에서 하고 싶다"): H1~H12·M4·
     M13/M14·L15 전부 실제 수정 코드를 직접 읽고 로직·초기화·소비부(consumer)
     안전성까지 확인. 커밋 `6ea3773`(Top-5 반영 직후) 기준으로 이번에 손댄 16개
     파일(소스 10 + 테스트 6)만 `git show`로 복원해 전용 베이스라인을 재구성,
     전체 테스트 스위트를 두 번(수정 전/후) 직접 실행해 FAILED/ERROR 테스트
     ID 집합을 통째로 diff — 신규 실패 0건, 신규 통과 55건, 기존 실패 1건만
     ERROR→FAILED로 상태가 이동(이 클라우드 검토용 사본에 없는 픽스처 파일이
     원인이라 수정 전후 근본원인 동일). M11 격리 수정 추가 후에도 동일 diff로
     회귀 0건 재확인.


159. **🔧 스파게티 감사 2차 — 결투(Duel) 모듈 37건 전부 반영 (2026-08-29,
     오푸스 엑스트라, 오너 요청 — "모듈별로 하나씩 오푸스 높음으로 검토하면서
     고쳐보자, 한번 할 때 전부 다").** `SPAGHETTI_AUDIT_2026-08-29.md` 순회 두
     번째(수집기 다음). 대상 8개 파일(`run_duel_daily_batch.py`/
     `run_duel_daily_batch_us.py`/`utils/duel_batch.py`/`utils/duel_batch_usd.py`/
     `utils/duel_db.py`/`utils/duel_db_usd.py`/`utils/duel_rules.py`/
     `web/pages/duel_page.py`, 총 12,166줄) 재감사(오푸스 서브에이전트, 실행
     재현 포함) 결과 나온 높음 8·중간 13·낮음 12·구조 리팩터 4 = 37건 중 33건을
     즉시 반영, M-10(재감사에서 "위반" 판정) 1건은 제가 직접 설계해 후속으로
     반영, S-1~S-4(구조 리팩터)·M-1(KR/USD 완전 통합)·M-7(왕복 수 최적화) 3건은
     의도적으로 백로그 유예.

     **높음 8건 중 두 건은 오너에게 정책 결정을 먼저 물었습니다** — 순수 기술
     판단이 아니라 "무엇을 옳은 동작으로 볼 것인가"의 문제였기 때문입니다.
     ①**H-1**(코스피/코스닥 지수 종가 원천이 처리 거래일보다 낡아도 그날 전체
     주문이 "지수 무변동 = 수집 실패"로 오판정·취소되던 문제) → 오너 답변
     **"날짜 검증을 확실하게 할 수 있으면 1번으로 하는게 맞다"**를 그대로
     반영: 실행 스크립트가 지수 원천 날짜와 처리 거래일을 비교해 낡았으면
     그 사실을 사유 문장으로 배치에 넘기고, 배치는 취소가 아니라 **보류**로
     처리(`no_baseline`과 같은 방식, 체결·취소 둘 다 하지 않음). USD 트랙은
     지수가 2개라 부분 낡음이 가능해, 낡은 지수만 빼고 나머지로 판정하거나
     전부 낡았으면 지수 없이 보류합니다. ②**H-8**(배치가 하루라도 못 돌면
     그날 주문이 체결도 취소도 안 된 채 무기한 대기로 남는 문제 — 오너가 실제로
     프로덕션에 이미 약 20건이 이 상태로 누적돼 있다고 알려주심) → 오너 답변
     **"1번(자동 취소)으로 하고, 이때 예수금·자동 처리가 어떻게 되는지 확인해
     달라, 취소 사유 문장은 줄이거나 줄바꿈해 달라(지금 너무 길다)"**를 그대로
     반영: 매 배치 실행의 **맨 앞**에서 `target_date < 처리일`인 pending 주문을
     전부 훑어 자동 취소하는 `expire_stale_pending_orders_before()`를 새로
     만들어 호출 — **이미 쌓여 있는 약 20건도 다음 정상 배치 실행 한 번으로
     자동 정리됩니다**(날짜 조건만 보므로 언제부터 쌓였는지와 무관). 예수금
     영향은 **없습니다** — 이 주문들은 pending(미체결) 상태라 애초에 원장에
     현금이 묶인 적이 없고(현금은 원장 이벤트로만 계산됩니다), 이번 정리도
     주문 상태·사유 필드만 갱신할 뿐 원장에는 아무 것도 쓰지 않습니다. 취소
     사유 문장도 요청대로 짧게 바꿨습니다: "이 주문은 목표 거래일 이후 배치가
     정상적으로 처리하지 못해 취소됐습니다(이월 안 됨)." (기존에 있던
     "작업지시서 2-4-5" 같은 내부 문서 인용은 사용자 문장에서 빼 코드 주석으로만
     남겼습니다.)

     **높음 나머지 6건** — ③**H-2/M-9**: 가격 스냅샷의 실제 거래일이 처리
     거래일과 다르면("사용자가 이미 아는 어제 종가로 체결"이 되는 상황) 위와
     같은 보류 경로로 보내고, `--override fill`과 겹치면 덮어쓰기 자체를
     거부. ④**H-3**: 같은 밤에 팔고 다시 산 종목은 매도 정산 RPC가 수량만
     갱신하고 평단가는 일부러 건드리지 않아 새 평단가가 통째로 버려지던 문제
     → 정산 직후 같은 수량으로 한 번 더 upsert해 평단가만 바로잡는 별도 경로
     추가. ⑤**H-4**: 배치가 원장 insert 뒤 주문 상태 갱신 사이에 죽으면 재실행이
     같은 체결을 원장에 중복 기록해 잔고가 두 배가 될 수 있던 문제 → 쓰기
     순서를 뒤집어(원장·포지션 먼저, 주문 상태 마지막) 중간에 죽어도 주문이
     pending으로 남아 재실행이 다시 집도록 하고, 원장 insert와 매도 정산 양쪽에
     "이미 반영된 행은 사전 조회로 걸러내는" 재실행 안전장치를 추가 + DB에
     `(order_id, event_type)` 부분 유니크 인덱스를 마지막 방어선으로 추가하는
     마이그레이션 SQL 작성(**오너가 Supabase SQL Editor에서 직접 실행 필요** —
     아래 참고). ⑥**H-5**: 계좌 하나의 보유 종목 중 하나라도 종가 결측이면
     그 계좌 총자산이 현금만으로 계산돼 그날 −95%대 TWR이 공개 순위표까지
     갔던 문제 → 그 계좌만 그날 스냅샷을 건너뛰고 다음 정상일부터 재개.
     ⑦**H-6**: 배치의 여러 일괄 조회가 페이지네이션 없이 서버 기본 상한만큼만
     읽고 "전부 읽었다"고 취급하던 문제(SPEC §2-1) → `_execute_all()` 헬퍼로
     `.range()` 끝까지 읽고, 페이지 상한에 걸리면 예외. ⑧**H-7**: "그날이
     10일인가"로만 정기 입금을 트리거해 10일에 배치가 실패한 달의 입금이
     영구히 누락되던 문제 → 최근 60일 구간의 모든 10일을 훑어 밀린 달을 함께
     채움(이미 날짜 단위 멱등이라 재실행 안전).

     **M-10 후속(제가 직접 설계·지시)** — 재감사가 "위반"으로 판정한 항목으로,
     `needs_review`/`no_baseline`으로 보류된 날의 주문이 사용자 화면에는 일반
     대기 주문과 똑같이 보이던 문제(로그에만 남기는 것은 조치가 아님, §0-1).
     실제 DB 트리거(`duel_orders_guard()`)·CHECK 제약을 직접 읽어 "status는
     그대로 두고 fail_reason만 갱신"하는 경로가 트리거를 통과함을 확인한 뒤
     `annotate_pending_orders_with_hold_reason()` 신설, 화면은 "⏸️ 판정
     보류" 배지로 갈라 그림. 후속 에이전트가 스스로 발견한 사각지대까지 함께
     처리: 주문 내역 표(종결된 주문만 봄)뿐 아니라 **별도의 대기 주문
     목록**(주문 폼 아래, pending 주문 전용)에도 같은 배지·사유를 붙임 —
     그렇지 않으면 이 수정 자체가 무의미했습니다.

     **중간 13건·낮음 12건** — 매도 수량 검증이 정수만 받아 소수 보유
     수량(기업행위 조정분)을 가진 계좌가 한 주도 못 팔던 버그(M-4), 화면의
     계좌 카드 데이터 로딩이 하나의 try로 묶여 있어 조회 3개 중 1개만
     실패해도 카드 전체가 사라지던 문제(M-5/M-6, 조회별로 분리), 매수·매도·
     주문취소 버튼에 중복 클릭 방어 없어 두 번 누르면 매수 주문이 중복
     생성되던 문제(M-3, 화면 8곳에 `_guard_double_click()` 적용), 죽은
     단건 래퍼 함수 3종 삭제(L-4, 비테스트 호출부 0건 확인 후), 원자적 파일
     쓰기에 fsync 추가(L-9), 스냅샷 TWR 계산에서 날짜 파싱 예외가 이미 체결·
     원장이 기록된 뒤에 배치를 죽이던 것을 계좌 단위 격리로 축소(L-10),
     '내 성적표' 카드가 원화·달러 각각 같은 보유 종목을 중복 조회하던 것을
     한 번으로 통합(L-11), 동의 철회의 TOCTOU 경쟁 조건 수정(L-12) 등.

     **의도적으로 손대지 않은 것** — S-1~S-4(구조 리팩터, §0-1 위반 아님),
     M-1(KR/USD 미러 완전 통합 — 파급범위가 커 실거래망 검증 없는 샌드박스에서
     유예), M-7(왕복 수 최적화, 이미 §0-3-2 위반은 아님)은 백로그로 유예.

     **검증** — 8개 소스 파일 + `sql/duel_schema_migration_2026-08-29_
     ledger_order_event_unique.sql`(신규, 오너가 Supabase에서 직접 실행 필요)
     수정, 62건 회귀 테스트 신규(6개 파일). 오푸스 서브에이전트 두 번(본작업 +
     M-10 후속)의 자체 보고를 그대로 신뢰하지 않고 이 대화방에서 직접 재검증
     (오너 요청 — "전체 검증은 이 채팅방에서 하고 싶다"): H-1~H-8 전부와 M-3·
     M-4·M-5/M-6·M-10·M-11·M-13·L-4·L-8·L-9·L-10·L-11·L-12의 실제 수정 코드를
     전부 직접 읽고 로직·트리거 안전성(DB 스키마 직접 확인)·소비부 안전성까지
     확인. 이번 배치 작업 시작 시점에 기기 저장소가 정확히 커밋 `7d79f3e`
     (수집기 반영 직후) 상태 그대로였다는 점을 이용해, 그 상태의 13개 파일
     (소스 7 + 테스트 6)을 그대로 전용 베이스라인으로 재구성 → 전체 테스트
     스위트를 두 번(수정 전/후) 직접 실행해 FAILED 테스트 ID 집합을 통째로
     diff — **완전히 동일**(신규 실패 0건), 신규 통과 62건, 기존 실패 8건은
     전부 이 클라우드 검토용 사본에 없는 `sql/duel_schema.sql` 픽스처 파일이
     원인(수정 전후 근본원인 동일). 레포 전체 테스트(1,486개 통과 기준)로도
     동일하게 신규 실패 0건 재확인.

     **오너 후속 조치 필요** — `sql/duel_schema_migration_2026-08-29_ledger_
     order_event_unique.sql`을 Supabase 대시보드 → SQL Editor에서 실행해
     주세요(여러 번 실행해도 안전, `if not exists`). 코드는 이 인덱스 없이도
     정상 동작하지만(앱 단에서 이미 중복을 걸러냄), DB 인덱스는 그 뒤의 마지막
     방어선입니다. 실행 전 파일 안의 확인 질의(주석 처리됨)로 이미 중복 원장
     행이 있는지 먼저 확인하는 것을 권장합니다.

160. **🗑️ Streamlit 은퇴 — 듀얼런 종료 (2026-08-29, 오푸스 엑스트라, 오너 결정 —
     "streamlit은 없애는 방향으로 가기로 했는데 그것까지 진행을 지금해버리자
     그걸 고려하고 문제가 되는걸 정리해줘").** `NICEGUI_MIGRATION_PLAN.md`
     부록 B에 예정(2026-08-31)돼 있던 정리 작업을 오너 지시로 이틀 앞당겨
     실행. 매크로/PEGY/보조지표/리포트 재감사(`MACRO_REAUDIT_FINDINGS.md`,
     47건) 처리 도중 S-1(구조 리팩터) 항목이 시급해져, PEGY 모듈 자체
     수정보다 먼저 처리했습니다(PEGY는 다음 순서로 유예 — 아래 참고).

     **부록 B 체크리스트 그대로 실행** — `index.html`·`keep_awake_ping.py`·
     `.github/workflows/keep_awake.yml` **삭제**(`CNAME`은 이전부터 이미
     없었음), `visiblehand.py`·`app.py` → `archive/`, `views/` 6개 →
     `archive/streamlit_views/` 이동, `requirements.txt`에서 `streamlit`·
     `altair` 제거, `ENGINEERING_SPEC.md`(§0 표·§6 표현계층 표·§10 디렉토리
     구조)·`PROJECT_STATUS.md`(§0-2·§0-5 항목4)를 NiceGUI 단일 스택
     기준으로 갱신.

     **회귀 테스트 처리 원칙** — 화면(옛 `views/*.py`)만 검증하던 코드는
     제거하되, 같은 함수 안에서 여전히 살아있는 공유 로직(`utils/report_db.py`
     ·`utils/scorecard_db.py` 등)을 함께 검증하던 부분은 위쪽 그대로 보존.
     `test_report.py`(8개 함수)·`test_scorecard.py`(2개 함수 + 의존성
     검사)·`test_web_session_isolation.py::test_macro_page_wiring`에서
     이 방식으로 화면 전용 블록만 제거. `test_macro_scoring.py`는 다르게
     처리 — 5개 함수가 `views/macro_view.py`의 리터럴을 조회하던 것을
     **삭제 대신 `web/pages/macro_page.py`로 재배선**(네 핵심 리터럴
     `layers`·`FRIENDLY_NAMES`·`STUDY_ONLY_INDICATORS`·`DROPPED_AS_DUPLICATE`가
     실제로 그 파일에 있음을 직접 확인한 뒤 재배선 — 삭제했다면 매크로
     화면-상수 정합성 회귀 보호가 통째로 사라졌을 것). `test_stock_history.py`도
     같은 이유로 `views/pegy_view.py`+`views/us_stocks_view.py` 개별 검사를
     두 화면이 공유하는 `web/components/stock_download.py` 검사로 재배선.

     **제가 직접 발견해 고친 것 2건** (에이전트 자체 보고에는 없었음,
     오너 요청 — "전체 검증은 이 채팅방에서") — ①`test_scorecard.py::
     test_requirements_and_docs`가 `streamlit==1.50.0`을 "유지해야 할
     의존성"으로 단언하고 있어 `requirements.txt` 정리 직후 깨질 예정이던
     것을 발견해 "streamlit/altair가 더 이상 없어야 한다"는 반대 방향
     단언으로 직접 수정. ②`test_report.py::test_workflow`가 실제 기기
     저장소의 `.github/workflows/keep_awake.yml`을 직접 읽어 "다른
     워크플로우를 안 건드렸는지" 확인하는 목록에 포함하고 있어, 그 파일
     삭제 직후 `FileNotFoundError`로 깨지는 것을 기기에서 전체 테스트
     실행 중 발견 → 목록에서 제거(살아있는 `scrape.yml`·`scrape_us.yml`
     검사는 그대로 유지). 이 두 건 모두 클라우드 검토용 사본에는
     `requirements.txt`·`.github/`가 애초에 없어서 구현 에이전트가
     건드릴 수 없었던 파일이라, 기기에서 직접 재현·수정했습니다.

     **검증** — 기기 저장소에서 `git stash`로 이번 변경 전 상태를 정확히
     복원해 전용 베이스라인으로 삼고, 전체 테스트 스위트를 두 번(수정
     전/후) 직접 실행해 FAILED/ERROR 테스트 ID 집합을 통째로 diff —
     **완전히 동일**(13개 항목, 전부 이번 작업과 무관한 기존 실패 —
     예: `test_duel.py`·`test_event_loop_blocking.py`의 사전 존재하던
     실패, `archive/test_scrape.py`의 프록시 오류). 통과 수만 정확히
     1건 감소(1612 → 1611)했는데, 이는 삭제한 옛 `test_period_buttons`
     테스트 함수 1개가 통째로 없어진 것과 정확히 일치(신규 실패 아님).
     `py_compile`로 수정한 파일 전부 컴파일 확인. `archive/` 밑 파일들도
     `.gitignore`에 걸려 있지만 `git mv`로 이미 추적 중이던 파일의
     이동이라 정상적으로 추적 유지됨을 확인.

     **오너 후속 조치 필요** — Streamlit Cloud 대시보드에서 구 앱
     (`visible-hand-dashboard-2vmzz6tk63wsac7n345ord.streamlit.app`)을
     **직접 중지**해 주세요. 코드 정리는 끝났지만 그 앱 자체를 내리는
     것은 코드로 할 수 없는 일입니다.

     **의도적으로 남겨둔 것** — `archive/test_harness.py` 등 이전부터
     `archive/`에 있던 무관한 스크립트는 이번 작업 대상이 아니므로
     그대로 둠. PEGY 모듈 자체의 버그 수정(H-4·M-1·M-2·M-3·M-14·L-6·L-7·
     L-8·L-11 등, `MACRO_REAUDIT_FINDINGS.md` 기준)은 다음 순서로 유예 —
     오너의 원래 요청("PEGY모듈 검토에 집중해줘")이 이번 작업 다음
     차례입니다.

161. **🔧 스파게티 감사 3차 — PEGY 모듈 버그 수정 (2026-08-29, 오푸스 엑스트라, 오너
     요청 — "PEGY모듈 검토에 집중해줘").** `MACRO_REAUDIT_FINDINGS.md` 재감사 47건 중
     PEGY(`/`, `web/pages/pegy_page.py`) 전용 8건 — H-4·M-1·M-2·M-3·M-14·L-5(PEGY
     부분)·L-6·L-7·L-8·L-11 — 을 전부 반영. 매크로 서브모듈(H-1·M-4·M-5·M-6·M-8~M-13·
     L-1~L-4·L-9·L-10·L-12~L-14)은 오너 지시대로 전부 유예했고, 구조 리팩터
     S-3(`build_stock_card_html` 436줄 분해)도 §0-1 위반이 아니라 백로그로 유예.

     **①H-4** — `dps=None`("미수집")과 `dps=0`("무배당 확인됨")을 화면이 다시
     "무배당" 한 단어로 뭉개던 문제. `collector_kospi200.py`가 이미 저장해 두는
     `dps_source`(`not_collected`/`no_dividend_confirmed`/그 외 실측값)를 그대로 따라
     세 갈래로 갈랐습니다: 미수집 → "데이터 없음", 확정 무배당 → "무배당(확인됨)",
     그 외 → 금액. 파이프라인이 네 곳(scoring.py·guardrail.py·data_issues·collector
     H3 수정)에서 지켜 온 구분을 화면이 되돌리던 걸 바로잡았습니다.

     **②M-1·M-2** — "🔴 고평가/주의" 프리셋이 `"검증" in b` 부분일치로 컨센서스
     미커버리지일 뿐인 중립 배지(`🔵 Trailing만 검증됨`)까지 끌고 오던 문제(M-1),
     "세부 뱃지 직접 선택"에서 배지를 전부 해제하면 `if badges:`가 빈 리스트를
     "필터 없음"으로 오독해 500종목이 그대로 남던 문제(M-2). 두 버그를 고치면서
     `_selected_badges`(화면 함수 안 클로저라 단위 테스트 불가능했음)를 모듈
     최상위 순수함수 `resolve_preset_badges(preset, custom_badges, all_badge_options)`
     로 뽑아 실제 값으로 검증 가능하게 만들었습니다. `None`(필터 없음)과
     `[]`(전부 해제)을 이제 구분해서 반환합니다.

     **③M-3** — 공개 화면 3곳(스냅샷 실패 배너·다운로드 안내·다운로드 버튼)이 아직
     "시가총액 상위 200"이라던 것을 500으로 정정(실제 유니버스·필터 프리셋·제목
     꼬리말은 이미 500으로 맞았음 — 세 곳만 낙오돼 있었습니다).

     **④L-5** — 원본/누적이력 다운로드 4곳의 파일명이 `datetime.now()`(Render는
     UTC) 기준이라 한국 자정 근처엔 파일명 날짜가 하루 어긋날 수 있던 문제.
     이 파일이 이미 갖고 있던 KST 헬퍼(:23-27)로 `_kst_today_str()`를 만들어
     통일(`dividend_page.py` 커밋 `ba2b62b`와 같은 계열 수정).

     **⑤L-6·L-11** — EV/EBITDA가 음수(적자)여도 "(약 -3.4년)" 같은 의미 없는 M&A
     원금회수기간을 그리던 문제(L-6, 같은 카드의 그레이엄 넘버는 적자를 이미
     정확히 차단하고 있어 방어 수준을 맞췄습니다) + 그 문자열의 폰트 크기를
     11px로 만들어 놓고 유일한 사용처에서 `.replace("11px","13px")`로 바꿔치기
     하던 것(L-11)을 처음부터 13px로 직접 만들도록 정리.

     **⑥L-7** — `price = s.get("price") or 0`가 결측(None)과 실측 0원을 구분 못 해
     Forward 비교박스 '현재가'와 PBR 바닥가가 "0원"으로 나오던 문제. 갭 계산 등
     기존 산술 분기는 그대로 두고(이미 `price > 0` 방어가 있었음), 화면에 보이는
     문구에만 `price_display`를 따로 둬 결측이면 "데이터 없음"으로 표기 — 카드
     헤더 쪽 현재가는 원래도 `fmt_num()`으로 이렇게 하고 있었는데 이 한 자리만
     빠뜨리고 있었습니다.

     **⑦L-8** — 적자 경고 배너의 ROE가 반올림 없이 `esc(t_roe_val)`로 그대로 찍혀
     "ROE -3.2000000001%"가 가능하던 것을, 카드의 다른 모든 자리와 같은
     `fmt_num(..., 1)` 규칙으로 통일.

     **⑧M-14** — `tests/test_quant.py`의 §0-1 골든 테스트 8건(PEGY 화면의 유일한
     회귀 방지선)이 `run_golden_tests()`라는 이름 때문에 pytest 명명 규약에 안
     걸려 `pytest tests/test_quant.py` → "no tests ran"으로 CI에서 한 번도 실행
     안 되고 있던 문제. CASE 1~8을 독립된 `test_case1_...`~`test_case8_...` 8개
     함수로 쪼갰습니다(로직·단언문은 한 글자도 안 바꿈, CASE 2·4가 기대던 CASE 1
     dict 는 `_base_case1()`로 뽑아 매번 새로 만들어 테스트 간 실행순서 의존을
     없앴습니다). `run_golden_tests()`는 `python tests/test_quant.py` 직접 실행용
     으로 남기되 이 8개를 그대로 순서대로 부르는 얇은 래퍼로 바꿨습니다.

     **신규 회귀 테스트** — `tests/test_pegy_page.py`(신규, 13건)를 만들어 위
     H-4·M-1·M-2·L-6·L-7·L-8을 소스 문자열 패턴이 아니라 **실제 함수를 호출한
     결과**로 검증합니다(`build_stock_card_html`·`resolve_preset_badges`가 모두
     화면 함수 안 클로저가 아니라 모듈 최상위라 직접 호출 가능). 수정 전 코드에
     그대로 돌려 6개 테스트가 정확히 그 수정 전 코드에서만 실패함을 직접
     확인했습니다(아래 검증 참고) — 통과하는 테스트가 아니라 **버그를 실제로
     잡아내는** 테스트임을 실행으로 증명.

     **검증** — 기기 저장소에서 `git stash`로 이번 세 파일(`web/pages/pegy_page.py`·
     `tests/test_quant.py`·신규 `tests/test_pegy_page.py`)만 정확히 되돌려
     진짜 베이스라인으로 삼고, 전체 테스트 스위트를 두 번(수정 전/후) 직접 실행해
     FAILED/ERROR ID 집합을 통째로 diff — **완전히 동일**(신규 실패 0건). 통과
     수는 정확히 새 테스트 수만큼(1611 → 1632, +21 = test_quant.py 8건 + 
     test_pegy_page.py 13건) 증가. 별도로 `tests/test_pegy_page.py`의 H-4·L-6·L-7·
     L-8 담당 6개 테스트를 기기의 수정 전 `pegy_page.py`에 그대로 돌려 **정확히
     그 6개만** 실패(나머지 정상값 대조 테스트는 그대로 통과)함을 확인 — 이
     테스트들이 실제로 해당 버그를 잡아낸다는 것을 실행으로 증명했습니다.
     `py_compile`로 수정·신규 파일 전부 컴파일 확인.

     **의도적으로 손대지 않은 것** — 매크로 서브모듈 전체(오너 지시), S-3 구조
     리팩터(급하지 않음, §0-1 위반 아님), M-15(Streamlit 쌍둥이 전용 버그 —
     2026-08-29 Streamlit 은퇴(#160)로 이미 archive/ 행이라 무의미해짐). 보조지표
     (H-5·M-10·L-1~L-4)·리포트(M-13·S-4) 서브모듈 findings 는 아직 오너와 범위를
     확정하지 않은 상태로 남겨둡니다.

162. **🔧 스파게티 감사 3차 — 보조지표·리포트 모듈 버그 수정 (2026-08-29, 오푸스
     엑스트라, 오너 지시 — "작업 순서는 뭐가 편하겠어? … 처리할 수 있는건 지금
     최대한 처리하자").** `MACRO_REAUDIT_FINDINGS.md` 재감사 47건 중 보조지표
     (`web/pages/indicator_page.py`) H-5·M-10, 리포트(`web/pages/report_page.py`·
     `utils/report_db.py`) M-13 을 반영. S-4(`report_db.py` 1,903줄 구조 분해)는
     감사 문서 자신의 판단("급하지 않습니다 — 지금 실제 버그는 이 파일에서 나오지
     않았습니다")대로 이번에도 백로그 유예.

     **①H-5** — 보조지표 카드가 이력(`recent_rows`)의 가장 최근 행을 위치만 보고
     무조건 "오늘"이라 라벨링하고 강조 테두리까지 두르던 문제. 그날 이력 수집이
     실패하면 최신 행이 실제로는 며칠 전 값인데도 "오늘"·"전일 대비"라고 단정적으로
     말하고 있었습니다(§0-1). `_build_day_over_day_html()`·`_build_recent_trend_html()`
     에 카드 상단이 실제로 쓰는 기준일 `data_date`를 넘겨, 이력 최신 행 날짜와
     실제로 일치할 때만 "오늘"이라 부르고 강조하도록 고쳤습니다. 어긋나면 "이력에
     쌓인 가장 최근 기록일은 YYYY-MM-DD입니다(오늘 수집분 아님)"는 경고를 그
     자리에 그대로 붙입니다 — 값을 지어내거나 숨기지 않고 어긋난 사실 자체를
     보여주는 쪽을 택했습니다. 재현: 수정 전 코드에 "최신 이력 = 3일 전" 상황을
     그대로 넣으면 `>오늘<` 라벨과 `#38bdf8` 강조 테두리가 그대로 나오는 것을
     직접 실행으로 확인했습니다(아래 회귀 테스트가 이 케이스를 고정합니다).

     **②M-10** — AI 해설 버튼에 중복 클릭 방어가 없어(`state['loaded']`가 응답이
     온 **뒤**에만 세워지고 `button.props('loading')`은 스피너일 뿐 재클릭을 막지
     않음) 빠르게 두 번 누르면 유료 Gemini 호출이 2회 나가던 문제. `duel_page.py`가
     이미 8곳에서 쓰던 `_guard_double_click`(M-3, 2026-08-29 재감사)를 그대로
     재사용해 `_render_ai_panel`의 버튼에 걸었습니다. 이 화면이 두 번째 소비자가
     된 시점에 §0-3-10에 따라 화면 전용 헬퍼를 `web/components/widgets.py::
     guard_double_click`로 승격하고, `duel_page.py`도 그 공용 이름을 import해서
     쓰도록 바꿨습니다(동작은 한 글자도 안 바뀜 — 이름과 위치만 바뀜).
     `utils/indicator_ai.py::_fetch_cached()`가 캐시 조회 실패를 "캐시 없음"과
     동일하게 처리해 무제한 재생성될 수 있다는 감사의 두 번째 지적은 코드를 직접
     읽고 **의도적으로 손대지 않았습니다** — 아래 "의도적으로 손대지 않은 것"
     참고.

     **③M-13** — `utils/report_db.py::compute_period_report`의 `today` 기본값이
     `date.today()`라 배포 서버(Render, UTC) 기준으로 계산돼, 한국 자정 근처엔
     "오늘"이 실제 한국 날짜보다 하루 이를 수 있던 문제. 이 파일이 `utils/`
     계층이라 `web/`을 import할 수 없어(§6 계층 분리) 이 파일 전용 로컬
     `_KST`(zoneinfo) 헬퍼를 다른 `utils/*.py`·수집기 파일들과 같은 관용구로
     새로 만들었고, `web/pages/report_page.py`는 이미 있는 `dividend_page.py::
     today_kst()`를 재사용했습니다(§0-3-10, `report_page.py`가 `scorecard_page.py`
     의 `_display_name`을 재사용하던 것과 같은 전례). `pegy_page.py`의 L-5·
     `dividend_page.py`의 커밋 `ba2b62b`와 같은 계열의 UTC 기준일 버그입니다.

     **신규 회귀 테스트** — `tests/test_indicator_page.py`(신규, 8건)가 H-5를
     `_build_day_over_day_html`/`_build_recent_trend_html`(둘 다 화면 함수 밖
     모듈 최상위 순수 함수라 직접 호출 가능)을 실제로 호출한 HTML로 검증합니다.
     수정 전 코드에 그대로 돌려 "최신 이력 = 3일 전" 상황에서 `>오늘<` 라벨과
     `#38bdf8` 강조가 실제로 나오는 것을 직접 실행으로 재현·확인했습니다(버그를
     실제로 잡아내는 테스트임을 실행으로 증명). `tests/test_web_components.py`
     (신규, 4건)는 승격된 `guard_double_click`이 처리 중 두 번째 호출을 실제로
     버리는지, 완료 후엔 다시 정상 동작하는지, 예외가 나도 `finally`로 버튼을
     되살리는지, 버튼을 안 묶어도 안 죽는지를 NiceGUI 없이(가짜 버튼 객체로)
     검증합니다. 기존 `tests/test_duel_page_usd.py::
     test_every_write_handler_is_guarded_against_double_clicks`(M-3 회귀 테스트)
     도 헬퍼가 로컬 정의에서 공용 import로 바뀐 것을 반영해 갱신했습니다(원래
     테스트가 `_guard_double_click` 로컬 정의를 AST로 직접 찾고 있어, 승격만
     했는데도 그 자체로 "깨지는" 것을 발견해 고쳤습니다 — 아래 검증 참고).

     **검증** — 기기 저장소에서 `git stash`로 이번에 바뀐 9개 파일 전부(수정 7 ·
     신규 2)를 정확히 되돌려 진짜 베이스라인으로 삼고, 전체 테스트 스위트를 두 번
     (수정 전/후) 직접 실행해 FAILED/ERROR ID 집합을 통째로 diff — **완전히
     동일**(신규 실패 0건, 기존에 있던 4 failed·5 errors 그대로 — `archive/`
     구버전 화면·OCR 플래그·매크로 렌더 스모크 등 이번 변경과 무관한 기존 결함).
     통과 수는 정확히 새 테스트 수만큼 증가(1658 → 1670, +12 = test_indicator_page.py
     8건 + test_web_components.py 4건). 이번엔 기기의 nicegui·supabase·plotly 등
     의존성이 (기기 VM이 최근 재시작된 것으로 보여) 전부 빠져 있던 것을 발견해
     `pip install -r requirements.txt`로 재설치했고, 그 과정에서 드러난 별개의
     기존 환경 결함(pyOpenSSL 21.0.0이 새로 설치된 cryptography 50.0.0과 안 맞아
     `archive/test_live.py`·`tests/test_collector_indicator_kr.py` 등 4개 파일이
     수집조차 안 되던 문제)도 `pyopenssl` 패키지만 최신으로 올려 코드 변경 없이
     해결 — 이 부분은 이번 재감사 대상과 무관한 순수 환경 문제였습니다(`archive/
     test_scrape.py`가 import 시점에 `finance.naver.com`으로 실제 네트워크 호출을
     하는 것은 기기 방화벽 때문에 여전히 막혀 있어, 이 파일 하나만 두 번의 실행
     모두에서 동일하게 `--ignore`했습니다). `py_compile`로 수정·신규 파일 전부
     컴파일 확인.

     **의도적으로 손대지 않은 것** — S-4(구조 리팩터, 급하지 않음). M-10의
     캐시-실패-를-캐시-없음으로-처리하는 부분(`utils/indicator_ai.py::
     _fetch_cached()`/`_save_cache()`) — 코드를 직접 읽어보니 이미 실패를
     `print()`로 서버 로그에 남기고 있고(§0-3-4 준수), Supabase upsert라 중복
     저장이 행을 깨뜨리지 않으며, 감사 문서 자신의 "실제 적용 순서" 표(§8)에도
     이 부분의 코드 수정은 올라 있지 않고 "Supabase RLS 미확인 — 서버 로그로만
     판별 가능"이라고 **운영 확인 사항**으로만 남겨 뒀습니다. 즉 이건 코드 결함이
     아니라 "오너가 실제 서비스 Supabase 대시보드에서 `indicator_ai_commentary`
     테이블/RLS가 실제로 살아 있는지, 서버 로그에 `⚠️ [indicator_ai] 캐시 조회/
     저장 실패`가 찍히고 있는지"를 확인해야 하는 운영 항목이라 판단해 코드는
     그대로 두었습니다 — 오너가 원하면 로그 확인 방법을 별도로 안내하겠습니다.
     매크로 서브모듈(H-1·M-4~M-9·M-11·M-12·L-1~L-4·L-9·L-10·L-12~L-14)은 오너
     지시대로 여전히 전부 유예 상태입니다.

163. **🔧 스파게티 감사 3차 — 스코어카드(내 성적표) 모듈 버그 수정 25건 전부 반영
     (2026-08-29, 오푸스 높음, 오너 지시 — "작업 순서는 뭐가 편하겠어? … 처리할 수
     있는건 지금 최대한 처리하자").** `SCORECARD_REAUDIT_FINDINGS.md`(신규 감사,
     사전 감사 문서가 없던 모듈이라 이번에 새로 감사) 25건(🔴 High 5·🟠 Medium 8·
     🟡 Low 7·🏗️ Structural 5) 중 22건을 반영하고, 나머지 3건(S-1·S-4·S-5)은
     감사 문서 자신의 권고대로 "급하지 않음/오너 판단"으로 백로그에 남겼습니다.

     **🔴 High 5건 전부** — **①H-3** 가격 스냅샷(data/*.json)을 아예 못 읽어
     거래일조차 확인 못 하는 상태(수집기 완전 정지·파일 형식 변경 등)와 "동의자가
     500명 미만이라 발행 안 함"(정상)이 똑같이 "발행 대상 0명"으로 합쳐져, 발행
     배치가 **그 상태에서도 과거 발행 이력을 지웠습니다**(§0-1 — 데이터 문제를
     인원 미달로 위장). `utils/scorecard_publish.py::run_publish_batch()`에
     안전장치 2개 추가 — (a) `price_lookup` 생략 시 `report_db.resolve_session_dates()`
     로 거래일을 하나도 못 찾으면 즉시 중단, (b) 동의자가 있는데 전원이
     `SKIP_NO_RETURN`으로 걸러져 발행 대상이 0명이면(인원 미달이 아니라 계산 실패)
     즉시 중단 — 둘 다 과거 이력을 지우기 **전에** 걸립니다. **②H-2**
     `scorecard_publish_db.py`가 `duel_db.py`를 미러링하며(§0-3-10) `_execute`는
     가져오고 `_execute_all`(페이지네이션)은 안 가져와서, 발행 배치의 5개 조회
     함수(동의자·철회자·체급배정·보유종목·발행이력) 전부 서버 응답 상한에 걸리면
     "일부만 읽고 전부 읽은 척" 했습니다 — `_execute_all` import 추가 + 5개 함수
     전부 페이지네이션 적용. **③H-1** `scorecard_db.py`·`duel_db.py`의 `_execute()`
     가 `f"{action} 실패: {exc}"`로 PostgREST 응답 원문을 그대로 붙여, 이 계약을
     믿고 원문까지 그대로 화면에 보여주는 호출부(`scorecard_consent_page.py`·
     `scorecard_leaderboard_page.py`의 `except (DuelDbError, DuelRuleError):`
     블록 — `fail_message()`도 안 거치는 경로)에 원문이 새고 있었습니다. 두
     `_execute()` 모두 원문은 `print()`로 로그에만 보내고 화면 문구는 처음부터
     안전하게 재작성(`raise ... from exc`로 원인은 체이닝만). **④H-4**
     `scorecard_db.py::current_user()`가 `client.auth.get_user()`의 예외를
     원인 안 가리고 전부 "세션 없음"(`None`)으로 재분류해, 네트워크 장애·Supabase
     5xx 때도 정상 로그인 사용자를 강제 로그아웃시켰습니다 — 진짜 세션 부재
     (`_SESSION_MISSING_MARKERS`)만 `None`으로 재분류하고 그 밖은 예외를 그대로
     올리게 수정. **⑤H-5+M-7** OCR 일괄등록이 신뢰도 낮음(`confidence: low`)
     항목과 미해결 티커를 사용자 확인 없이 그대로 등록했던 문제 — 확인 필요 항목은
     자동 등록 대상에서 빼고, 버튼 라벨도 "인식된 N개 전부"에서 "확인된 N개만"으로
     바꿨습니다.

     **🟠 Medium 8건 전부** — **①M-1** 보유종목 추가·수정·삭제 버튼 9곳 중
     `guard_double_click`이 걸린 곳이 하나도 없어(중복 클릭 시 `add_lot()`의
     읽기-수정-쓰기가 경합) `scorecard_page.py` 6곳·`scorecard_consent_page.py`
     3곳에 적용. 같은 탭 중복 클릭 방어와는 별개로, **다른 탭/기기의 동시 수정**
     까지는 못 막으므로 `update_holding()`에 `expected_quantity` 낙관적 잠금을
     추가 — `add_lot()`의 병합 경로가 자신이 읽은 수량과 DB의 현재 수량이 다르면
     (그 사이 다른 곳에서 먼저 저장) 값을 추측해 덮어쓰지 않고 예외로 멈춥니다.
     **②M-2** 발행 배치가 순위표(leaderboard)를 먼저 쓰고 보유종목(holdings)을
     나중에 써서, 그 사이 배치가 죽으면 "순위표엔 있는데 보유종목 상세가 없는"
     어중간한 상태가 노출됐습니다 — holdings를 먼저 쓰도록 순서 교환(반대로 죽어도
     "아직 순위표에 없음"으로만 보여 덜 이상함). **③M-3** 체급 배정 청크 삽입이
     Postgres insert의 원자성 때문에 청크(최대 200명) 안에 중복 키 1건만 있어도
     **청크 전체**(최대 199건의 진짜 새 배정 포함)가 롤백되는데, 예전엔 그 실패를
     그냥 `continue`로 넘겨 전부 버렸습니다 — 청크 실패 시 행 단위로 재시도해 진짜
     중복만 건너뛰도록 수정. **④M-4** 매입원가/평가금액/평가손익 요약 카드가
     서로 다른 모집단(매입원가=전종목, 평가금액=시세 있는 종목만)을 섞어 써서 셋을
     나란히 보면 앞뒤가 안 맞아 보였던 문제 — 시세 없는 종목이 있으면 카드에
     안내를 덧붙임. **⑤M-5** OCR 프롬프트 자신이 "못 찾으면 `{"items": []}`"을
     정상 응답으로 명시했는데, 코드가 그 정상 빈 응답을 예외로 취급해(`OcrError`)
     아래 UI 분기 하나가 죽은 코드였던 문제 — 빈 응답을 더 이상 예외로 취급하지
     않고, 이름을 못 읽어 제외된 항목 수(`dropped`)를 세어 사용자에게 알림.
     **⑥M-6** 테스트 스위트가 실행 순서에 따라 실패 수가 9건↔1건으로 갈리던 문제 —
     `test_scorecard_ocr.py`의 렌더 스모크가 `asyncio.run()`을 직접 써서, NiceGUI의
     프로세스당 1회용 "유사 클라이언트"를 소진하면 뒤이어 도는 다른 렌더 스모크까지
     연쇄 실패했습니다(같은 테스트 함수 안에서도 두 번째 호출부터 재현 — 실행
     순서와 무관하게 이 파일 하나만 단독 실행해도 "플래그 ON일 때 위젯이 그려지는가"
     검증은 한 번도 실행된 적이 없었습니다). `test_scorecard_public_ui.py`가 이미
     갖고 있던 올바른 해법(슬롯 컨텍스트 전파)을 `tests/_render_helpers.py::
     run_render()`(신규)로 승격해 두 파일이 공유하도록 함(§0-3-10). **⑦M-8**
     "종목명" 정렬이 표시되는 한글명이 아니라 저장된 영문명 기준이라 미국 종목의
     정렬이 화면에 보이는 순서와 어긋났던 문제 — `sort_holding_rows()`에
     `label_fn` 콜백을 추가해(계산 계층은 그대로 순수하게 유지, §6 계층 분리)
     화면이 자신의 표시명 로직을 주입. **⑧M-2 관련 부수 발견** — H-1 수정을
     `duel_db.py::_execute()`에 적용하는 과정에서, 이 파일 안의 기존 오류
     번역기들(`_is_duplicate_key_error()`·`_translate_order_guard_error()`·
     `_translate_opt_in_error()`)이 **원문 텍스트를 패턴 매칭**해 "이번 리밸런싱
     창에서는 이미 매도 주문을 한 번 사용했습니다" 같은 더 나은 한국어로 바꾸고
     있었다는 것을 뒤늦게(전체 테스트 스위트 실행 중) 발견 — `_execute()`가 원문을
     화면 문구에서 지우면 이 번역기들이 더 이상 패턴을 못 찾아 `test_duel_db.py`의
     기존 회귀 테스트 7건이 깨졌습니다. `_raw_cause_text(exc)`(원래 원인
     `exc.__cause__`를 우선 보는 헬퍼)를 추가해 번역기들은 원문을 계속 읽되 화면에
     최종적으로 나가는 문구는 안전한 채로 유지하도록 재설계 — `duel_db_usd.py`의
     동일한 번역기(`_translate_order_guard_error_usd`)에도 같은 수정 적용. 이
     과정에서 `tests/test_scorecard.py`의 가짜 클라이언트(`FakeQuery._matches`)가
     `.eq()` 필터를 문자열 비교로만 해서 `expected_quantity=10.0`(앱이 정규화한
     float)과 저장된 `"10"`(문자열)이 실제로는 같은 값인데 다르다고 오판(`M-1`의
     낙관적 잠금이 오탐)하는 것도 함께 발견해, 숫자로 먼저 비교하도록 고쳤습니다
     (실제 PostgREST/Postgres numeric 컬럼은 10과 10.0을 같은 값으로 비교합니다).

     **🟡 Low 6/7건, 🏗️ Structural 2/5건** — **L-1** 시세 스냅샷 6개 중 KR·US
     인덱스가 둘 다 실패했을 때만 배너를 띄우고 한쪽만(또는 보조 목록만) 실패하면
     조용히 그 부분만 "정보 없음"으로 보이던 문제 — 파일별 실패사유를 모아 부분
     실패도 알림. **L-2** 순위표 "보유종목 보기"가 조회 실패해도 `loaded=True`가
     이미 걸려 페이지 새로고침 없이는 재시도가 안 되던 문제 — 실패 시에만
     `loaded=False`로 되돌림. **L-3** 동의 화면이 최종확인/철회 시각을
     `2026-08-23T14:02:11.482913+09:00` 같은 ISO 원문 그대로 노출 — `duel_rules.
     _to_kst()`로 파싱해 `2026-08-23 14:02 (KST)`로 표시. **L-4** "내 평균매입가
     VS 현재가" 배너(오르면 빨강/내리면 파랑)가 `error_banner`/`info_banner`를
     재사용해 DB 실패 배너와 똑같이 보이던 문제 — `pct_html()`과 같은 색 규칙의
     전용 배너(`price_up_banner`/`price_down_banner`, `web/components/widgets.py`
     신규) 추가. **L-5** `zoneinfo`가 없는 환경에서 OCR 하루 한도의 "오늘"이
     조용히 서버 로컬 시간(UTC)으로 물러서 한국 자정이 아니라 오전 9시에 리셋될
     뻔한 문제 — 운영 환경(Render)엔 항상 있어 평소엔 안 타는 분기지만, 혹시
     타면 서버 로그에 경고를 남기도록 함. **L-6** `fetch_holdings()`에
     페이지네이션이 없어 보유 종목이 1,000개(서버 상한)를 넘으면 일부만 읽힐 수
     있던 문제 — `scorecard_db.py` 전용 `_execute_all()`(duel_db와 같은 알고리즘,
     예외 타입만 이 모듈 것 — 계층 분리 유지) 추가해 적용. **S-2** 은퇴한
     Streamlit 잔재(`import streamlit as st`, `st.secrets` 폴백,
     `@st.cache_resource` 경고 주석) 정리 — `_read_secret()`을 환경변수 전용으로
     단순화하고, `views/scorecard_view.py` 참조 8곳을 실제 위치
     (`archive/streamlit_views/scorecard_view.py` 또는 대체한 현재 파일)로 갱신.
     **S-3** `scorecard_publish_db.py`가 `duel_db`에서 비공개 함수를 손으로 골라
     import하는 방식(§0-3-10상 옳은 판단) 자체의 유일한 약점 — "목록이 사람 손으로
     유지된다"(실제로 H-2가 이렇게 생겼습니다) — 를 막는 AST 회귀 테스트
     추가(`_execute`를 import하면 `_execute_all`도 반드시 함께 import해야 함,
     현재 미러 모듈 2개 전부 통과 확인). **L-7**(`test_scorecard.py`의 `check()`
     실패가 FAILED가 아니라 ERROR at teardown으로 보고되는 문제)은 조사 결과
     pytest가 fixture teardown에서 발생한 예외를 예외 종류와 무관하게 항상 ERROR로
     분류하는 구조적 제약이라, 감사 문서의 "pytest.fail() 1줄로 해결" 제안이
     실제로는 동작하지 않음을 직접 실험으로 확인(진짜 해법은 테스트 본문 40여 개
     전부에 검사를 옮기거나 conftest.py 수준의 훅이 필요해 리스크 대비 효과가
     낮다고 판단) — 동작 자체는 이미 옳다는 감사의 평가에 따라 백로그로 유예.

     **의도적으로 손대지 않은 것** — S-1(694줄 `_render_input_form()` 분리),
     S-4(`twr_pct` 키 이름을 `duel_rules.rank_participants()`의 `value_key`
     인자로 일반화), S-5(발행 배치 원자성 — `publish_run_id` 도입은 스키마 변경이라
     규모가 큼). 셋 다 감사 문서 자신이 "급하지 않음/오너 판단"으로 명시했고, 이번
     회차에서 반영한 22건과 결합 리스크를 키우지 않기 위해 손대지 않았습니다.

     **신규 회귀 테스트** — `tests/_render_helpers.py`(신규, M-6 공용 헬퍼) +
     `tests/test_scorecard.py`(H-1 재검증 1건 갱신, H-4 신규 1건, M-1 낙관적 잠금
     신규 1건) + `tests/test_scorecard_ocr.py`(M-6 수정 1건, M-1 버튼 커버리지
     신규 2건) + `tests/test_scorecard_publish.py`(S-3 AST 신규 1건, H-2 신규
     2건, H-3 신규 3건, M-2 신규 1건, M-3 신규 1건) — 전부 실제 함수를 직접
     호출하고, 가능한 곳(M-3·H-3)은 수정 전 로직을 재현해 "이 테스트가 진짜로
     버그를 잡아내는지" 직접 실행으로 증명.

     **검증** — 기기 저장소에서 `git stash -u`로 이번에 바뀐 18개 파일(수정 17 ·
     신규 1: `tests/_render_helpers.py`) 전부를 정확히 되돌려 진짜 베이스라인으로
     삼고, `tests/` 전체를 두 번(수정 전/후) 직접 실행해 FAILED/ERROR ID 집합을
     통째로 diff — **새 실패 0건, `test_scorecard_ocr.py::
     test_upload_widget_is_really_not_rendered_when_flag_is_off` 1건만 FAILED→
     PASSED**(M-6이 실제 기기 데이터로도 재현·수정 확인됨), 나머지 기존 결함
     8건(`test_duel.py` 표기 통일성 2건·`test_web_session_isolation.py`의 매크로/
     리포트/결투 렌더 스모크 4건 — M-6과 같은 nicegui 유사 클라이언트 계열 버그지만
     이번 감사 범위 밖의 다른 모듈·`test_report.py` 2건)는 이번 변경과 무관하게
     그대로. 통과 수 1670 → 1684(+14, 위 신규 테스트 수와 일치). `py_compile`로
     수정·신규 파일 전부 컴파일 확인.
     ⚠️ 위 렌더 스모크 4건(매크로·리포트·결투 화면)은 M-6과 **같은 근본 원인**
     (`asyncio.run()` 직접 호출로 인한 nicegui 유사 클라이언트 소진)일 가능성이
     높지만 이번 스코어카드 감사 범위 밖이라 손대지 않았습니다 — 다음 감사 대상이
     될 만합니다(오너 판단).


164. **🔧 재감사 4차 — 배당(KR/US) 모듈 버그 수정 37건 반영, 4건 유예 (2026-08-29,
     오푸스 높음, 오너 지시 — "한번 할 때 전부 다").** `DIVIDEND_REAUDIT_FINDINGS.md`
     (신규 감사) 41건(🔴 High 7·🟠 Medium 17·🟡 Low 12·🏗️ Structural 5) 중 37건을
     반영하고, 나머지 4건(H-2·S-2·S-3·S-4)은 각기 다른 이유로 백로그에 남겼습니다
     (아래 "의도적으로 손대지 않은 것" 참고).

     **🔴 High 7건 중 6건(H-2 제외)** — **①H-1** `apply_watch_update()`가 감시
     델타의 `status`를 확인하지 않고 그대로 교체해, 일시적 DART 오류(ERROR)로 끝난
     델타가 확정된 배당(OK, 실측 dps_cash_common 746.0)을 조용히 지워 버렸습니다 —
     델타 `status != "OK"`면 교체를 건너뛰고 `watch_skipped_replacements`로 남기도록
     수정, CLI 감시 경로도 델타 레코드 중 하나라도 ERROR면 워터마크(last_checked_de)를
     전진시키지 않도록 추가 방어(그래야 다음 실행이 그 종목을 다시 봅니다). **②H-3**
     KR 배당 캘린더의 "배당락일 전까지 매수하세요" 큰 배너가 조건 없이 항상 떠서,
     이전 달로 넘겨 이미 지난 배당락일을 보고 있어도 "지금부터 준비하라"는 배너가
     그대로 보였습니다 — 미국 배당 화면이 이미 방어해 둔 패턴(`future_count`)을
     그대로 이식(`count_future_ex_events()`), 달력 칸·상세 블록도 지난 날짜는
     색을 죽이고 "(지남)"을 붙임. **③H-4** 미국 배당 화면의 "주당 배당금"이 실은
     최근 1년(TTM) 합계인데 그 사실이 어디에도 없어 분기·월 배당 회사에서 실제
     받는 금액의 최대 4~12배로 오독될 수 있었습니다 — `DPS_ANNUAL_NOTICE` 상시
     배너 + 표·달력 값 아래 "연간 합계(TTM) — 1회 지급액 아님" 문구 추가. **④H-5**
     KRX 휴장일 게이트가 **연도 단위**로만 막아, 표가 실제로는 "2025년 12월 두
     날짜 + 2026년 전체"만 덮는데도 `2025-01-01`·`2025-05-05` 같은 날짜가 전부
     "개장일"로 조용히 오판됐습니다 — 게이트를 `KRX_VERIFIED_RANGE`(실제 표가
     덮는 날짜 구간)로 교체. **⑤H-6/H-7** 수집기가 이미 기록해 둔 실패·경고
     신호(`completed`/`stopped_reason`/`unit_mismatch_notes`/`cross_source_notes`/
     `watch_skipped_replacements`/`watch_filings_outside_universe`)가 화면
     어디에도 안 보였습니다(§0-1) — `_render_completion_status()` 신설 + 배지
     헬퍼 2개(`unit_mismatch_badge_html`/`cross_source_badge_html`) 추가해 전부
     화면에 노출.

     **🟠 Medium 17건 전부** — **M-1** 지급일정 수집기가 "신규 레코드 0건"이면
     `failures`/`raw_write_failures`/`scan_stats.unrecognized`가 있어도 산출물
     갱신을 건너뛰어 그 신호들이 사라졌던 문제 — 건너뛰기 조건을 네 신호 전부를
     보도록 확장. **M-2** 파일 없음과 파일 읽기 실패를 화면이 구분하지 않던 문제
     — 오류 문구의 "읽지 못했습니다" 부분 문자열로 실제 읽기 실패만 경고 배너로
     승격. **M-3** 주식종류 구분 없이("-") 들어온 2026년 배당액(`dps_cash_
     unspecified`)이 미확정 목록 어디에도 안 보였던 문제 — 자동 승격은 하지 않고
     (오너 판단 유보) 배지로만 노출. **M-4** ERROR 상태 레코드가 요약 카드·문구
     어디에도 잡히지 않고 조용히 다른 분류로 흡수되던 문제 — 전용 상태 문구 +
     6번째 요약 카드 추가. **M-5** "주당 현금배당금"이 1분기보고서면 1분기분만,
     3분기보고서면 9개월 누적인데 그 차이가 안 보여 종목 간 비교가 위험했던 문제
     — 열 제목에 "(해당 보고서까지 누적)" 추가 + `CUMULATIVE_DPS_NOTICE` 상시
     노출. **M-6** `UNIVERSE_NOTICE`·`YIELD_SOURCE_NOTICE`가 접이식 패널 안에
     숨어 있던 문제(§0-3-13 위반) — 요약 카드 바로 아래 상시 노출로 이동. **M-7**
     KR·US 두 화면 모두 표시 금액이 세전이라는 사실이 어디에도 없던 문제 — 두
     화면 모두 `TAX_NOTICE` 상시 배너 추가(세후 예상액은 개인마다 세율이 달라
     계산하지 않음, §0-1). **M-8** 같은 out_dir을 전체수집·병합·감시가 동시에
     건드리면 결과가 깨질 수 있던 문제(동시성 방어 없음) — CLI 진입점에
     `_locked_output_dir()`(원자적 파일 락, Windows·Linux 양쪽에서 동작하도록
     `fcntl` 대신 `os.O_EXCL` 사용, 6시간 넘은 락은 죽은 락으로 간주해 자동 해제)
     추가, 락을 못 잡으면 종료코드 2로 즉시 실패. **M-9/S-5** raw.jsonl이
     append-only라 계속 커지는데(실측 9.4MB→18.5MB, 5일 만에 거의 2배) 다운로드
     버튼이 무제한으로 전체를 메모리에 올리던 문제 — 50MB 상한 추가, 넘으면 GitHub
     저장소 링크로 안내(롤오버 전략 자체는 여전히 미정, `PROJECT_STATUS.md` §11-4
     5번 참고). **M-10** raw.jsonl의 상한 로직을 넣으면서 `_render_raw_downloads()`
     가 latest.json·raw.jsonl·history.json 세 버튼 전부를 `os.path.exists()`
     (로컬 파일 존재)로 게이트했는데, 실제 다운로드 함수(`read_download_bytes()`)는
     원격(Render 배포 환경)에서도 `data_source.read_text()`로 읽을 수 있어 —
     배포 환경에서는 데이터가 실제로 존재해도 버튼 자체가 안 보였던 문제.
     latest.json·history.json은 존재 확인 없이 항상 버튼을 그리도록 하고(클릭
     실패 시 기존 `download_button`의 토스트가 처리), raw.jsonl만 로컬에 있으면
     상한 검사를, 없으면 상한 없이 버튼만 그리도록 분리. **M-11** 유니버스 밖
     종목의 공시 접수 사실이 병합 결과에 안 남던 문제 — `apply_watch_update()`에
     `outside_universe_codes` 매개변수 추가. **M-12** 감시 델타 유니버스가 기존
     유니버스의 부분집합이라 같은 종목이 `unmapped_detail`에 두 번(기존+델타)
     들어가 레코드 수와 안 맞던 문제 — 종목코드 기준 dedupe(`_dedupe_unmapped()`,
     델타가 이김). **M-13** 검색창에 debounce가 없어 키 입력마다 2,734건 필터링
     + 3개 구획 재렌더가 실행되던 문제 — Quasar `debounce=300` 추가. **M-14**
     오타·손상된 날짜(예: `2062-09-18`) 하나가 섞이면 월 선택기가 440개까지
     부풀 수 있던 문제 — 오늘 기준 ±24개월 밖은 목록에서 빼고 제외 건수를 화면에
     그대로 밝힘(`available_months()`가 `(months, out_of_range_count)` 튜플을
     돌려주도록 시그니처 변경). **M-15** 요청 예산 카운터가 재시도를 빼고 세어
     실제 DART 트래픽을 과소집계하던 문제 — 카운터 증가 위치를 호출부
     (`fetch_alot_matter`)에서 실제 HTTP 호출 지점(`_http_get_json()`)으로 이동.
     **M-16** H-5를 그대로 통과시킨 원인 — 달력 순수 함수(`is_krx_trading_day`·
     `ex_dividend_date`·`count_future_ex_events` 등)에 테스트가 0건이었던 문제 —
     `tests/test_dividend_page_calendar.py` 신설 + `dividend_page`/`dividend_us_
     page`를 `test_pages_import_cleanly()` 대상에 추가. **M-17** 지급일정
     수집기의 리포트(`by_parse_status`·`documents_failed_this_run`·`scan_stats.
     unrecognized` 등)가 산출물 파일에만 있고 화면에 없던 문제 —
     `_render_payment_report_block()` 신설.

     **🟡 Low 12건 전부** — **L-1** 이 화면에서 호출부가 없는 죽은 함수
     `shift_month()`(미국 배당 화면 것과 이름만 같음) 삭제. **L-2** 3-tuple인데
     4-tuple이라고 잘못 적힌 주석 정정. **L-3** `skipped_bad_stock_code` 카운터가
     실은 버리지 않고 유지하는 건인데 이름이 반대로 읽혀 `kept_with_
     unnormalized_stock_code`로 개명. **L-4** `utils.expiry_alarms` import가
     `sys.path.append`보다 먼저 있어 `python -m` 없이 직접 실행 시 못 찾을 수
     있던 순서 버그 정정. **L-5** KRX 마지막 검증 연도(2026) 상수가
     `dividend_page.py`·`collector_dividend_payment_kr.py` 두 곳에 손으로
     중복 — `utils/expiry_alarms.KRX_VERIFIED_LAST_YEAR` 한 곳으로 통합. **L-6**
     유니버스에 "5930"·"005930"이 함께 있으면 둘 다 같은 종목으로 정규화되는데
     dedupe를 안 해 두 번 조회·레코드 2건이 남던 문제 — `seen_targets` 집합으로
     dedupe, 건너뛴 건수는 로그로 밝힘. **L-7** 체크포인트·raw 저장 실패가
     로그 한 줄로만 끝나고 리포트에 안 남던 문제 — `save_checkpoint()`/
     `append_raw()`가 True/False를 돌려주고 실패 건수를 `raw_write_failures`/
     `checkpoint_write_failures`로 summary에 남기도록 수정. **L-8** KR 화면의
     월 선택 핸들러엔 있는 방어적 범위 검사(`0 <= picked < len(months)`)가 US
     화면엔 없던 비대칭 — 같은 가드 추가. **L-9** 페이지가 1개뿐이어도 pager가
     항상 그려지던 문제(형제 함수는 이미 조건부) — 조건부로 통일. **L-10**
     접수번호(rcept_no)가 없는 행끼리 "같은 접수번호(None)"로 취급해 서로를
     중복이라고 버리던 문제 — 빈 rcept_no는 dedupe 대상에서 빼고
     `missing_rcept_no` 카운터로 별도 집계. **L-11** US 화면에는 있는 "매수
     마지막 날"이 KR 화면엔 없던 비대칭 — `last_buy_html_kr()`(배당락일의
     1영업일 전을 한 번 더 계산, 이미 있는 "🧮 계산값" 배지 재사용) 추가,
     배당락일 상세 블록의 ex 행에만 붙임(배당기준일·지급예정일 행은 배당락일
     축이 아니라 대상이 아님). **L-12** `DIVIDEND_MODULE_WORK_ORDER.md`가 "화면
     파일마다 esc() 사용을 자동으로 강제 검사한다"고 적어 놨지만 실제로는
     스코어카드·리포트·결투 등 이름을 하나하나 지정한 파일에만 걸려 있고 배당
     화면 2개는 빠져 있던 문제 — 문서를 정정하고, `test_dividend_pages_use_
     esc_for_external_strings()` 신규 검사를 실제로 추가해 그 화면 2개도 커버.

     **🏗️ Structural 5건 중 2건(S-1·S-5, S-5는 M-9와 병합)** — **S-1**
     `collector_dividend_payment_kr.py`가 "완전 독립"을 표방하면서도 실제로는
     `normalize_stock_code`·`dart_document_url`을 `collector_dividend_kr.py`
     경유(2-hop)로 import하고 있어, 독립 선언과 실제 import 그래프가 어긋나 있던
     구조적 문제 — `DART_DOCUMENT_URL_TEMPLATE`/`dart_document_url()`을 두 수집기의
     공통 하위 모듈인 `corp_code_mapper.py`로 옮기고, 두 수집기 모두 거기서 직접
     import하도록 정리(동작 변화 없음, 순수 구조 정리).

     **의도적으로 손대지 않은 것(4건)** — **H-2**(정정 공시 중 "어느 것이 최종본인가"
     판정)와 그와 짝인 **S-3**(그 판정의 소유권)은 감사 문서 자신이 "정책 결정이
     먼저 필요합니다 — 정책 없이 화면에서 임의로 원본을 숨기면 §0-1 위반이 새로
     생깁니다"라고 명시한 항목이라 손대지 않았습니다(오너 정책 결정 필요). **S-2**
     (KR·US 두 화면의 거래일 계산 로직 중복 — 감사가 "H-3·H-5가 서로 다르게
     구현된 근본 원인"이라고 지적할 만큼 가치가 있다고 밝힌 구조 개선)는 가치를
     인정하면서도 이번 회차에는 의도적으로 유예했습니다 — 두 화면 모두 이미
     실서비스 중이고 방금 이번 회차에서 검증까지 마친 휴장일 계산 로직을, 41건
     짜리 같은 커밋 안에서 또 건드리면 결합 리스크가 커진다고 판단했습니다(다음
     감사 후보 1순위). **S-4**(`_render_body()` 210줄짜리 단일 함수가 로딩·검증·
     렌더링을 다 섞고 있는 문제)는 감사 자신의 우선순위표에서도 구조 리팩터 그룹
     중 상대적으로 낮은 순위로 분류돼 이번 회차에는 미루었습니다.

     **🚨 이번 회차 자체 검증 중 발견한 회귀(스스로 잡고 스스로 고침)** — M-15를
     구현하며 `_http_get_json()`이 `request_counter=` 키워드를 항상 받게
     바꿨는데, `tests/test_dividend_collector.py`의 여러 네트워크 가짜 함수
     (`faked_network`·`faked_network_widened` 픽스처 등 8곳)가 그 키워드를
     받지 못하는 좁은 시그니처(`lambda url, params, timeout, session: ...`)라
     실제로는 **`run_collection()`을 쓰는 기존 테스트 전부가 TypeError로
     깨지는 회귀**였습니다(compile 통과만으로는 못 잡고, 이번 세션 마지막
     `pytest tests/test_dividend_collector.py -q` 전수 실행에서 드러남 —
     "compile만 확인하고 pytest 전수 실행을 생략하면 안 된다"는 교훈). 가짜
     함수 8곳 전부 `request_counter=None` 키워드를 받도록 고치고, `faked_
     network`/`faked_network_widened`는 진짜 `_http_get_json()`처럼 실제로
     카운터를 증가시키도록(`_fake_alot_matter_response()` 공용 헬퍼 신설)
     고쳐 `requests_used` 검증 테스트들도 원래 의미 그대로 복구했습니다.

     **신규 회귀 테스트** — `tests/test_dividend_page_calendar.py`(H-5 계산
     함수 12건 + H-3 과거/미래 판정 2건 + L-11 매수 마지막 날 5건 + M-14 월
     범위 상한 3건 + M-9/S-5 다운로드 상한 4건 + M-10 다운로드 버튼 게이트
     검사 1건, 기존 2건 포함 총 29건 전부 통과) + `tests/test_web_session_
     isolation.py`(M-16 페이지 import 검사 2개 모듈 추가, L-12 esc() 검사
     신규 1건) + `tests/test_dividend_collector.py`(H-1 3건·M-8 락 6건·M-11
     2건·M-12 1건·M-15 1건·L-6 1건·L-7 4건 = 신규 18건, 기존 8곳 시그니처
     수정) + `tests/test_dividend_payment_collector.py`(L-10 신규 2건). S-1은
     동작 변화가 없는 순수 구조 정리라 별도 신규 테스트 없이 기존 스위트
     전체(수집기 두 개 관련 테스트 포함)로 회귀 여부만 확인.

     **검증** — 기기 저장소에서 `git stash -u`로 이번에 바뀐 12개 파일(수정만,
     신규 파일 없음: `web/pages/dividend_page.py`·`dividend_us_page.py`·
     `collector_dividend_kr.py`·`collector_dividend_payment_kr.py`·
     `corp_code_mapper.py`·`utils/expiry_alarms.py`·`DIVIDEND_MODULE_WORK_
     ORDER.md`·`PROJECT_STATUS.md`·테스트 4개) 전부를 정확히 되돌려 진짜
     베이스라인으로 삼고, `tests/` 전체를 두 번(수정 전/후) 직접 실행해
     FAILED/ERROR ID 집합을 통째로 diff — **새 실패 0건, 새로 고쳐진 기존
     실패도 0건**(그대로 남은 기존 결함 8건은 #163에서 이미 "이번 감사 범위
     밖"으로 기록된 매크로·리포트·결투 렌더 스모크 4건 + 결투 표기 통일성
     2건 + 리포트 2건 — 전부 배당 모듈과 무관). 통과 수 1684 → 1729(+45).
     배당 전용 테스트 파일 4개(`test_dividend_collector.py`·`test_dividend_
     payment_collector.py`·`test_dividend_page_calendar.py`·`test_dividend_
     us_page.py`)만 따로 돌리면 455건 전부 통과, 에러 0건. `py_compile`로
     수정 파일 전부 컴파일 확인.


165. **🔧 재감사 4차 — 미국주식 모듈 버그 수정 32건 반영, 8건 유예 (2026-08-29,
     오푸스 높음, 오너 지시 — "한번 할 때 전부 다").** `US_STOCKS_REAUDIT_FINDINGS.md`
     (신규 감사) 44건(🔴 High 7·🟠 Medium 17·🟡 Low 13·🏗️ Structural 7) 중 32건을
     반영하고, 나머지 8건(M-13·M-16·L-11·S-1·S-2 일부·S-4 일부·S-6·S-7)은 각기
     다른 이유로 백로그에 남겼습니다(아래 "의도적으로 손대지 않은 것" 참고).

     **🔴 High 7건 전부** — **①H-1** 550종목 중 542종목이 실패해도 스냅샷이
     `status: "SUCCESS"`로 저장될 수 있었던 문제(`valid_ratio`의 분모가 "수집
     성공분"만이라 대량 실패를 놓침) — 수집 대상 전체를 분모로 하는
     `collect_ratio`를 새로 계산해 AND 조건으로 판정, 직전 스냅샷 대비 노출
     종목 수가 급감하면(예: 550→8종목) 프로덕션 산출물을 덮어쓰지 않고 중단하는
     `US_SNAPSHOT_SHRINK_GUARD_RATIO` 가드도 함께 추가. **②H-2** 자기자본이
     음수인 미국 대형 우량주(맥도날드·홈디포 등 자사주 매입형)가 ROE 부호가
     뒤집힌다는 이유만으로 "적자 기업 + 데이터 정합성 모순"으로 오판정되던
     문제 — 적자 판정에서 `t_roe < 0` 조건 제거(EPS≤0/순이익<0 만 사용),
     `negative_equity` 플래그 신설, 가드레일의 모순 판정도 자기자본 음수가
     확인되면 건너뛰도록 수정. **③H-3** "데이터 정합성 모순"으로 차단된
     종목의 Forward 밸류에이션이 경고 한 줄 없이 그대로 렌더되던 문제 — 코스피
     화면의 `is_generic_harness_fail` 분기를 그대로 이식해 "🛡️ 데이터 검증
     실패" 마스킹 패널 추가. **④H-4** BPS 바닥값이 모델 목표가를 대체하면서
     "장부가 기준 +66.7% 상승 여력"만 보여주고 정작 PEGY 역산값(대개 마이너스)은
     화면 어디에도 없던 문제 — 두 값을 병기하도록 수정(2026-08-07 오너 결정
     "우리 모델이 무엇을 목표가라 부를지"에 대한 재검토는 정책 결정이 먼저
     필요해 병기까지만 함). **⑤H-5** Trailing 「과거 적정가」(`t_fair`)의
     바닥값·캡 적용이 화면에 아무 표시 없이 나가던 문제 — `f_target` 자리에
     이미 있던 배지 두 종류(🧮 상한 적용값 / 🛡️ 장부가 바닥값)를 `t_fair`
     자리에도 동일하게 적용. **⑥H-6** 목표가가 바닥값(장부가)으로 대체된
     종목은 목표가 교차검증을 통째로 건너뛰어 "목표가 초과" 경고와 점수 캡이
     사라지던 문제 — 캡·바닥값 적용 여부와 무관하게 캡 미적용 원값
     (`f_target_uncapped`)으로 교차검증하도록 수정(이 수정으로 뜻대로 바뀌는
     기존 테스트 기댓값도 같은 커밋에서 함께 수정, 사유는 테스트 주석에 명시).
     **⑦H-7** `--limit` 테스트 실행이 아무것도 쓰지 않았는데도 진행 중이던
     전수 수집 체크포인트를 삭제해 버리던 문제 — 체크포인트 정리 시점을
     `write_outputs` 블록 안으로 이동.

     **🟠 Medium 17건 중 15건** — **M-1** 히스테리시스 버퍼(진입 550/이탈 600)가
     `filter_universe`가 550위 밖 후보를 애초에 돌려주지 않아 구조적으로 한 번도
     발동할 수 없던 문제 — 유니버스 조회 크기를 이탈 순위까지 확장하고
     `entry_rank` 파라미터를 실제로 넘기도록 배선 수정. **M-2** 지수 프록시의
     "Index Tracked" 라벨 불일치 같은 검증 실패(`error`)가 등락률이 정상
     계산되면 화면에서 통째로 버려지던 문제 — 등락률 유무와 무관하게 항상
     노출. **M-3** 스냅샷이 담고 있는 실제 거래일이 화면 어디에도 없어(휴장일에
     크론이 돌면 전 거래일 종가를 오늘 시각으로 갱신한 스냅샷이 나올 수 있음),
     상단 지수 카드엔 있는 거래일 표기가 종목 쪽엔 없는 비대칭도 있던 문제 —
     `session_dates_from_source`의 최빈값을 "마지막 동기화" 배너에 함께 노출.
     **M-4** 스냅샷 노후(며칠째 갱신 안 됨) 경고가 코스피 화면에만 있고
     미국에는 아예 없던 문제 — 미국 시장 휴장일 캘린더가 없어 "영업일"이
     아니라 "달력일"(4일 이상, 통상 주말 3일 간격은 오탐 안 나도록)로 계산해
     감사 권고대로 **일반 사용자에게도** 노출(코스피는 관리자 전용 유지).
     **M-5/M-6** 착시 저평가 ROIC 기준선이 코드 세 곳에서 서로 다르고(6.5 /
     8.0 / "8%"), ROE 기준선 문구도 상수(16.0%)와 화면 문구("15% 안팎")가
     어긋나 있던 문제 — 화면이 `US_VALUE_TRAP_ROE_PCT`/`US_VALUE_TRAP_ROIC_PCT`
     를 직접 import해 쓰도록 통일(실측: ROIC 7.0% 종목이 하드코딩 8.0 기준으론
     빨간색으로 보였지만 실제 기준 6.5%는 통과한 상태였음). **M-7** 수집 실패
     종목 목록이 접힌 아코디언 안에만 있어 §0-3-13 위반이던 문제(H-1과 결합하면
     "542종목이 사라졌다"는 사실이 접힌 한 줄로만 존재) — 실패 비율이 유니버스의
     2% 이상이면 목록은 그대로 아코디언에 두되 펼쳐진 경고 배너를 추가로 노출.
     **M-8** 주주환원 미수집 안내문의 `<br>` 리터럴이 화면에 글자 그대로 보이던
     문제 — 수집 계층은 순수 텍스트(`\n`)만 만들고, 화면이 `<br>`로 변환하도록
     계층 분리. **M-9** 검색창에 debounce가 없어 타건마다 550종목 재필터가
     실행되던 문제 — 배당 화면(M-13 선례)과 같은 방식으로 300ms debounce 추가.
     **M-10** 다운로드 파일명이 배포 서버 로컬시각(UTC) 기준이라 스냅샷 실제
     거래일과 어긋날 수 있던 문제 — `session_dates_from_source` 최빈값(M-3과
     같은 로직 공유)을 파일명에 사용. **M-11** `os.path.exists()`(로컬 파일
     존재 여부)로만 다운로드 버튼·요약 이력 로딩을 게이트해, 원격
     (`DATA_SOURCE_BASE_URL`) 모드에서 로컬 사본이 없으면 화면엔 데이터가
     정상 표시되면서 다운로드 버튼과 요약 이력만 조용히 사라지던 문제 —
     배당 모듈의 같은 문제(M-10) 수정과 같은 방향으로, 존재 판정 없이 항상
     시도하고 실패는 `failure_text`로 알림. **M-12** 「🟢 저평가 우량주 그룹」
     프리셋에 밸류에이션 배지 조건만 있고 '우량' 조건이 하나도 없어 착시
     저평가(`value_trap=True`) 종목도 그대로 포함되던 문제 — 이 프리셋일 때만
     `value_trap` 종목 제외. **M-14** 「Trailing (과거 실적 참고용)」 라벨
     안의 PEGY·과거 적정가 두 값이 실은 애널리스트 3년 성장 전망(미래
     컨센서스)에 의존하는데 그 사실이 안 보이던 문제 — 라벨에 상시 노출 문구
     추가. **M-15** `DEGRADED` 스냅샷이 "이미 수집됨"으로 취급돼 같은 날
     재시도가 막히던 문제 — 재시도 대상에 `DEGRADED`도 포함. **M-17** 상단
     지수 3종이 통째로 없거나 일부만 있을 때 화면이 조용히 카드만 생략하던
     문제 — 통째로 없으면 경고 카드, 일부만 없으면 어떤 지수가 빠졌는지 명시한
     배너 추가.

     **🟡 Low 13건 중 12건** — **L-1/L-2** `US_PEGY_SCORE_BANDS`/
     `US_ROIC_SCORE_KNOTS` 주석이 실제 값(3.0/6.5)과 다른 옛날 값(2.00/"WACC
     하단 8%")으로 남아 있던 문제 — 주석 정정. **L-3** 화면 제목의 "상위
     550개 종목"이 하드코딩돼 있던 문제 — `US_TARGET_UNIVERSE_SIZE`를 문자열에
     반영. **L-4** 캡·상한 수치(35%p/10%p/40%p/35배/2.5배 등)가 툴팁에 여러 곳
     하드코딩돼 있던 문제 — 전부 `constants_us`에서 import해 씀. **L-5** 필드명
     `intraday_change_pct`가 실은 "장중"이 아니라 "장마감 종가 대비 전일 종가
     등락률"(확정치)이라 §0-3-1 표현 원칙과 어긋나던 문제 — `daily_change_pct`
     로 개명(수집기·화면 양쪽, 관련 테스트도 함께). **L-6** `fetch_one_index_
     quote()`가 같은 HTML을 3번 파싱하던 문제 — `_as_soup()` 재사용(이전
     세션에 이미 반영돼 있었는데 주석 라벨이 "L-10"으로 잘못 붙어 있던 것을
     이번에 "L-6"으로 정정). **L-7** `parse_close_timestamp()`가 소스의
     EDT/EST 약어를 정규식으로 잡아만 놓고 실제로는 검증하지 않던 문제
     (지금은 날짜만 써서 무해하지만 나중에 시각까지 쓰면 서머타임 전환일
     근처에서 어긋날 수 있음) — zoneinfo가 계산한 약어와 소스 약어가 다르면
     서버 로그에만 남기도록 추가(화면 노출 없음, §0-3-4). **L-8** 이어하기
     실행에서 배치 휴지기 카운터가 매번 0부터 다시 시작해 §0-3-2 완화책의
     의도(총 요청 밀도 낮추기)가 약해지던 문제 — 누적 카운터(`overall`)를
     쓰도록 수정. **L-9** 커스텀 배지 필터에서 전부 해제하면 "0건"이 아니라
     "전체"가 보이던 문제(`if badges:`가 빈 리스트와 필터-없음을 구분 못 함)
     — `is not None` 검사로 교체. **L-10** `forward_available`이 서로 다른
     정의로 세 번 계산되고 마지막에 덮어써지던 죽은 코드 — 중복 계산 제거,
     단일 출처(`scoring_us.py`의 `derive_valuation()`)만 남김. **L-12** 검증
     미통과 종목의 폴백 배지 "⚠️ 데이터 검증 필요"에 사유가 없던 문제 —
     `unverified_reason`/`reject_reason`을 `score_excluded_items`에 담아 기존
     툴팁 경로로 자동 노출. **L-13** 요약 지표의 "이전 동기화 대비" 델타에
     비교 대상 날짜가 없어, 수집이 며칠 건너뛰었으면 "어제 대비"가 아니라
     "며칠 전 대비"인데도 구분이 안 되던 문제 — 레코드의 `session_date`를
     델타 문구에 포함(코스피 화면과 공유하는 `render_summary_metrics()`를
     고쳤지만, 코스피 레코드엔 `session_date`가 없어 기존 문구로 자동
     하위호환).

     **🏗️ Structural 7건 중 3건(S-3·S-4 일부·S-5)** — **S-3**
     `tests/test_us_scoring.py`가 `.gitignore` 대상인 `data/us_sample/`에
     의존해 오너 PC 밖(이 저장소의 클라우드 검토 사본·CI 등)에서는 항상
     빨간불이라 회귀 게이트로 못 쓰던 문제 — 실데이터를 커밋된 픽스처로
     옮기는 이상적인 수정은 그 실데이터 자체가 오너 PC에만 있어 이번 세션에서
     만들 수 없었으므로(§0-1 — 있지도 않은 실측 데이터를 지어내지 않음),
     대신 부재를 "정보성 스킵"으로 낮춰 있으면(오너 PC) 실데이터 검증 15건이
     그대로 실행되고 없으면(이 사본·CI) 이 섹션만 건너뛰고 나머지 스위트는
     정상적인 회귀 게이트 역할을 하도록 수정. **S-4(부분)** 단위 함수는
     검증하지만 프로덕션 배선은 검증하지 않던 문제 중, 대량 수집 실패(H-1)가
     `run_us_collector()` 전체 배선에서 실제로 `status`/`valid_ratio`/
     `collect_ratio`에 반영되는지, `apply_us_guardrail()`이 진짜 정합성
     모순(H-2/H-3)을 잡으면서 자기자본 음수인 정상 종목은 오판정하지 않는지
     — 두 시나리오를 실제 배선으로 재현하는 회귀 테스트를 새로 추가(히스테리시스
     M-1의 프로덕션 배선 테스트는 이번 회차에 넣지 못해 아래 "손대지 않은 것"
     참고). **S-5** 화면 파일(`us_stocks_page.py`) 전용 테스트가 0건이던 문제
     — `tests/test_us_stocks_page.py` 신규(15개 테스트 함수, H-3/M-2/M-3/M-4/
     H-5/M-5/M-6/M-7/L-3/L-4/L-9/M-10/M-11/M-12/L-13 커버, 배당 모듈의
     `test_dividend_page_calendar.py` 선례와 같은 패턴 — NiceGUI 서버 없이
     순수 함수 문자열 검사만으로 검증).

     **의도적으로 손대지 않은 것(8건)** — **M-13**(이력 CSV에 캡·바닥값·
     계산값 플래그 컬럼 추가)은 감사 문서의 권고이지만, `utils/stock_
     history.py`를 실제로 고치려는 순간 `tests/test_stock_history.py`의
     `FORBIDDEN_KEYS`가 "오너가 명시적으로 빼라고 한 내부 필드"로
     `f_target_capped`/`f_target_uncapped`/`t_fair_capped`/`t_fair_uncapped`/
     `is_unverified`를 이미 지정해 둔 것을 발견했습니다 — 새 감사 문서가
     기존의 명시적 오너 결정과 정면으로 부딪히는 경우라 감사 권고보다
     기존 결정을 우선했습니다(추가했다가 되돌림, §0-3-6). **M-16/L-11**
     (`collector_us_indices.py`의 장마감 게이트 부재·"seen" 가드 주석 오류)은
     실제로는 미국주식 모듈이 아니라 이미 완료된 「리포트」 모듈의 파일이라
     이번 회차 범위 밖으로 남겼습니다 — 특히 M-16은 "사장님 보고서"의 벤치마크
     수익률을 영구히 왜곡할 수 있는 §0-3-1 위반으로 실제 영향이 커서, 리포트
     모듈 전용 재감사를 별도로 열 것을 권합니다. **S-1**(320줄짜리
     `build_stock_card_html()` 단일 함수 분해)은 배당 모듈 등 이전 회차와
     같은 이유로 고위험 대규모 리팩터라 유예했습니다 — 다만 필터 로직
     (`select_badges_for_preset`/`apply_stock_filters`)과 배선 로직
     (`compute_stale_days`/`_snapshot_trading_date_iso`)은 이번 회차에서
     테스트 가능한 순수 함수로 이미 뽑아냈습니다. **S-2**(화면이
     `constants_us.py`를 임계값 출처로 안 쓰던 문제)는 M-5/M-6/L-3/L-4
     수정으로 감사가 지목한 구체적 사례는 전부 해소됐지만, 감사가 함께
     권고한 "화면 소스에 판정용 숫자 리터럴이 남아 있지 않은지 확인하는 AST
     테스트" 자체는 범위가 넓어(베타 등급 경계·PEGY 표시 구간 등 스코어링과
     무관한 순수 표시용 상수까지 다 걸릴 수 있음) 이번 회차에는 넣지 않았습니다.
     **S-4(나머지)** 히스테리시스(M-1)의 `filter_universe → apply_us_
     hysteresis_buffer` 프로덕션 배선 회귀 테스트는 진입 순위를 동적으로
     넘기는 지금 구조에서 작은 테스트 유니버스로 재현하려면 순위 계산이
     까다로워, 대량 실패·정합성 모순 두 배선 테스트만 우선 넣고 이 항목은
     다음 회차로 미뤘습니다. **S-6**(`us_stocks_latest.json`의 4개 모듈 공용
     계약 문서화·자기검증)과 **S-7**(KR/US 두 화면의 미러링 divergence 관리
     장치)은 배당 모듈의 S-2/S-7과 같은 이유로 — 문서화·정책 결정 성격이 강하고
     여러 모듈에 걸쳐 있어, 공유인프라 모듈 차례에 다시 다루는 편이 낫다고
     판단했습니다.

     **검증** — 기기 저장소에서 `git stash -u`로 이번에 바뀐 9개 파일(수정 8개:
     `collector_us_stocks.py`·`utils/constants_us.py`·`utils/scoring_us.py`·
     `utils/stock_history.py`(코멘트만, 필드 추가는 되돌림)·
     `web/pages/us_stocks_page.py`·`web/components/widgets.py`·테스트 2개,
     신규 1개: `tests/test_us_stocks_page.py`) 전부를 정확히 되돌려 진짜
     베이스라인으로 삼고, `tests/` 전체(`--ignore=archive`)를 두 번(수정
     전/후) 직접 실행해 FAILED/ERROR ID 집합을 통째로 diff — **새 실패 0건,
     새로 고쳐진 기존 실패도 0건**(그대로 남은 기존 결함 8건은 배당 모듈
     때와 동일하게 매크로·리포트·결투 렌더 스모크 5건 + 결투 표기 통일성
     2건 + 리포트 1건, 전부 미국주식 모듈과 무관). 통과 수 1729 → 1745(+16,
     신규 테스트 함수 13개 + 배당 모듈 이후 추가된 무관 테스트분 반영).
     미국주식 전용 테스트 3개(`test_us_stocks.py`·`test_us_scoring.py`·
     `test_us_stocks_page.py`)만 pytest로 따로 돌리면 35건 전부 통과, 각
     파일을 `python 파일명.py`로 직접 실행해도(원본 실행법) 전부 통과.
     `py_compile`로 수정 파일 전부 컴파일 확인.


166. **🔧 재감사 4차 유예 항목 후속 처리 — 미국주식 8건 중 6건 반영, 1건 정책
     재검토로 이관(공유인프라 모듈 예정), 1건 그대로 유예 (2026-08-29, 오푸스
     높음, 오너 지시 — "유예한 것을 하나씩 해치워보자").** #165에서 남겨 둔
     8건(M-13·M-16·L-11·S-1·S-2 일부·S-4 일부·S-6·S-7)을 하나씩 처리했습니다.

     **0) 선행 조치 — `git push` 거부 해소.** #165 커밋(`e6055b0`) 이후
     `github-actions[bot]`의 배당 자동 수집 커밋 2개(`ce474a1`·`bc92585`,
     `data/dividend_kr_2026_*`·`data/cache/*` 파일만 변경)가 `origin/main`에
     먼저 올라가 push가 거부됐습니다. `git show --stat`으로 두 커밋이 이번
     변경 파일과 전혀 겹치지 않음을 먼저 확인한 뒤 `git rebase origin/main`을
     실행 — 충돌 없이 재베이스됐고(`e6055b0` → `00fe083`), 관련 테스트
     재실행으로 이상 없음을 확인했습니다.

     **1) M-16 반영 — `collector_us_indices.py`에 장마감 게이트 추가.**
     이 수집기에는 `collector_us_stocks.py`의 `resolve_collection_session_et()`
     같은 장마감 게이트가 없어, 장중에 실행되면 그날의 미확정 종가가
     `merge_closes()`의 "기록 개변 금지" 원칙에 의해 영구히 확정 종가 자리에
     고정될 수 있었습니다. `resolve_collection_session_et()`로 "지금 담아도
     되는 거래일"을 구하고, 그보다 미래인 행은 새 `trim_unconfirmed_rows()`로
     잘라낸 뒤 병합하도록 고쳤습니다. 잘려나간 행은 다음 실행(장마감 이후)에서
     정상적으로 다시 들어옵니다. 또한 `metadata.warnings`/`last_error`/
     `value_conflicts`가 파일에만 남고 화면까지 전달되지 않던 것을,
     `utils/report_db.py::benchmark_closes_for_market()`이 두 신호를 함께
     반환하도록 하고 `web/pages/report_page.py::_render_benchmarks()`가
     "⚠️ 벤치마크 데이터 확인 필요" 배너로(§0-3-13 — 항상 보이게) 띄우도록
     배선했습니다. 리포트 모듈 파일을 다시 여는 것이라 §0-3-6에 따라 오너
     확인을 먼저 구했고("지금 여기서 그냥 바로 진행을 해줘"), 승인 후
     진행했습니다.

     **1-1) 작업 중 추가 발견 — `run_us_index_history_collector()` 반환값
     계약 재확인.** 이 함수가 실패해도 항상 파일 경로를 반환하는지 확인하려다
     `test_us_index_collector_run`의 `result is None` 기대치 3곳이 이미 낡아
     있었음을 발견했습니다. 실제로는 L8(전부 실패해도 실패 사유를 남기려고
     파일은 항상 씀 — 그 근거의 회귀 테스트
     `test_reaudit_total_failure_records_reason_without_touching_closes`가
     이미 존재)이 의도적으로 "항상 경로 반환"을 요구하므로, **코드가 아니라
     낡은 테스트 기대치와 docstring 쪽을 고쳤습니다**(반환값 대신
     `metadata.fetched_any`로 신규 수집 여부를 구분하도록 문서화). 두 계약이
     충돌한다는 걸 모르고 처음엔 반대로(코드를 `None` 반환하게) 고쳤다가
     L8 회귀 테스트가 깨지는 것을 보고 원인을 추적해 바로잡았습니다.

     **2) L-11 반영 — `iter_history_row_candidates()`의 `seen` 가드 주석
     정정.** "devalue는 같은 객체를 공유하므로 순환·중복 방지"라는 주석이
     실제로는 틀렸습니다(`_devalue_deref()`가 참조마다 매번 새 객체로
     펼치므로 디코드 후에는 공유·순환이 없음 — 무한 재귀 방지는
     `MAX_SEARCH_DEPTH`가 전담). 동작은 그대로 두고(디코더 구현이 바뀌면
     다시 방어망 역할을 할 수 있어 §0-3-6상 범위 밖 리팩터링 없이 유지),
     주석만 사실대로 정정했습니다.

     **3) S-2 나머지 반영 — 화면 소스 판정 리터럴 금지 AST 테스트.**
     `tests/test_us_stocks_page.py`에
     `test_s2_no_hardcoded_threshold_literals_outside_import()`를 추가해
     `us_stocks_page.py`의 비교식(Compare 노드)에 `constants_us.py`의
     판정 임계값(ROE/ROIC/캡 상수 등)이 리터럴로 남아 있으면 잡아냅니다.
     처음에는 int 리터럴까지 봐서 무관한 값(광고 위치 `offset == 9`, 문자열
     길이 `>= 10`)과 우연히 값이 겹쳐 오탐이 났고, 이 코드베이스의 판정
     임계값은 전부 float로 쓰인다는 점을 이용해 float 리터럴만 보도록
     좁혀 해결했습니다. 실제로 하나(`t_roe < US_VALUE_TRAP_ROE_PCT`)를
     일부러 `9.0`으로 되돌려 테스트가 진짜로 잡아내는지 확인한 뒤 원상
     복구했습니다.

     **4) S-4 나머지 반영 — M1 히스테리시스 프로덕션 배선 회귀 테스트.**
     `run_us_collector()` 안에 인라인으로 있던 M1 수정(entry_rank가 아니라
     exit_rank까지 넉넉히 뽑은 뒤 버퍼 적용)을 `build_hysteresis_tracked_
     universe()`로 뽑아내 `run_us_collector()`가 그 함수를 그대로 호출하게
     했습니다. `tests/test_us_stocks.py`에 700종목 합성 유니버스로 이 함수
     자체(사본이 아님)를 호출하는
     `test_reaudit_s4_hysteresis_production_wiring()`을 추가 — 직전 추적
     종목이 561위로 밀려도 실제 배선에서 버퍼로 유지되는지 확인합니다.

     **5) S-6 반영 — `us_stocks_latest.json` 공용 계약 문서화 + 자기검증.**
     `utils/constants_us.py`의 `US_SNAPSHOT_FILENAME` 위에 실제 소비처 5곳
     (미국주식 화면·배당 미국 화면(유일 입력)·결투 USD 배치·스코어카드
     종목명·리포트 거래일 점검, grep으로 직접 확인)과 최소 보증을 문서화했고,
     새 상수 `US_SNAPSHOT_MIN_GUARANTEED_COUNT = 400`을 추가했습니다.
     `collector_us_stocks.py`에 `violates_snapshot_min_guarantee()`를
     뽑아 `run_us_collector()`의 쓰기 직전에서 호출 — 기존 축소 가드(H1)가
     "직전 스냅샷이 있을 때"만 보는 데 반해, 이 가드는 직전 스냅샷 유무와
     무관하게 절대 하한을 봅니다. 단, `target_size`가 실제로
     550(production) 규모를 노릴 때만 적용되도록 해 — 회귀 테스트가 쓰는
     4종목 합성 유니버스 같은 의도된 소규모 수집까지 막지 않습니다.
     `tests/test_us_stocks.py`에 `test_reaudit_s6_snapshot_min_guarantee()`로
     경계값·소규모 target_size 면제까지 확인.

     **6) S-7 반영 — 그레이엄 넘버 산출 불가 else 폴백 박스.** 코스피
     화면(`pegy_page.py`)에는 있고 미국 화면에는 없던 마지막 방어(적자가
     아닌 사유로 `graham_target`이 없을 때의 `else` 분기)를 추가했습니다.
     실제 원인(BPS 미상 또는 BPS≤0)을 추적해 보니 코스피 쪽 원본 문구
     ("적자 기업")를 그대로 베끼면 자사주 매입형 우량주(H2/H4에서 이미
     구분해 둔 케이스)를 적자로 오진하는 결과가 됐을 것이라, BPS 값 자체를
     명시하는 정확한 문구로 새로 썼습니다. `tests/test_us_stocks_page.py`에
     `test_s7_graham_fallback_box_for_non_loss_reasons()` 추가(BPS 없음·
     BPS 음수 두 경우 모두 "적자 기업"이라고 잘못 짚지 않는지까지 확인).
     또한 `PROJECT_STATUS.md`에 §15(공개 화면 3개 최소 방어선 체크리스트)를
     신설 — 코스피·미국주식·배당 세 화면이 공통으로 가져야 할 방어 장치
     현황표를 한 곳에 두어, 다음에 화면 하나를 고칠 때 나머지와 대조하기
     쉽게 했습니다.

     **M-13 — 코드 미반영, 정책 방향은 확정(공유인프라 모듈에서 구현 예정).**
     이력 CSV에 캡·바닥값·계산값 플래그 컬럼을 추가하라는 권고는
     `tests/test_stock_history.py`의 `FORBIDDEN_KEYS`(오너가 이미 명시적으로
     뺀 내부 진단 필드 목록, KOSPI 쪽 `g_eff_capped` 등도 같은 이유로 빠져
     있음)와 정면으로 충돌해, 배경(카드에는 캡·바닥값 배지가 보이는데 같은
     정보가 다운로드 CSV에는 빠진다는 점)을 다시 설명하고 오너 확인을
     구했습니다. 오너 판단: "카드에는 표기가 되는데 CSV에 빠진다면 말이
     안 되는데, 정보는 항상 같아야지 여기하고 저기하고 다르면 안 되는 것" —
     즉 **기존 FORBIDDEN_KEYS 정책이 잘못됐다는 데 동의**하되, 지금 바로
     고치기보다는 "나중에 작업 다 끝나고 그 정책 자체를 다시 손보자"는
     뜻을 밝혔습니다. 코스피·미국 두 시장에 동일하게 걸린 공용 정책이라
     한 시장만 먼저 고치면 §0-3-10(단일 출처) 위반이 되므로, **다음
     공유인프라 모듈 차례에 KOSPI·US 이력 CSV 필드 정책을 한 번에
     재정비**하기로 하고 이번 라운드에서는 코드를 건드리지 않았습니다.

     **미룸 — S-1(320줄 함수 분해).** 이번 세션에서 `select_badges_for_
     preset`·`apply_stock_filters`·`compute_stale_days`·
     `_snapshot_trading_date_iso` 4개를 이미 뽑아냈고(#165), 나머지 전체
     분해는 여전히 고위험 대규모 리팩터링이라 별도로 시간을 들여 진행하는
     편이 낫다고 보고 이번 라운드에서는 손대지 않았습니다.

     **검증** — 기기 저장소에서 이번에 바뀐 9개 파일(`collector_us_indices.py`·
     `collector_us_stocks.py`·`utils/constants_us.py`·`utils/report_db.py`·
     `web/pages/report_page.py`·`web/pages/us_stocks_page.py`·`PROJECT_STATUS.md`
     ·테스트 3개: `tests/test_us_stocks.py`·`tests/test_us_stocks_page.py`·
     `tests/test_report.py`)를 매번 동기화한 직후 `tests/` 전체
     (`--ignore=archive`)를 실행해 FAILED/ERROR ID 집합을 사전 기록해 둔
     베이스라인과 비교 — **새 실패 0건, 새로 고쳐진 기존 실패는
     `test_us_index_collector_run` 1건**(위 1-1항의 반환값 계약 정정
     결과)이고 그 외 그대로 남은 기존 결함 7건은 미국주식 모듈과 무관.
     통과 수 1745 → 1749(+4, 이번에 추가한 신규 회귀 테스트 4개:
     S4 배선·S6 하한·S2 AST·S7 폴백). 도중에 `collector_us_indices.py`·
     `utils/report_db.py`·`web/pages/report_page.py`를 처음 편집할 때
     클라우드 작업 사본이 기기의 실제 최신 커밋과 한 군데(`tests/
     test_report.py`의 이미 삭제된 `keep_awake.yml` 참조 관련 낡은 3항목
     루프) 어긋나 있던 것을 `git diff HEAD`로 발견 — 기기 쪽 정정된 버전을
     기준으로 다시 맞춰 해결했습니다(다른 두 파일은 대조 결과 어긋남 없음).
     `py_compile`로 수정 파일 전부 컴파일 확인.


### #167 — 4차 재감사 7번째 모듈: 공유인프라(web/theme·auth·auth_ui·layout·state·
blocking·ads·components, utils/data_source·stock_history·stock_export) 전수
재감사 + M-13(카드·CSV 정보 정책) 최종 반영 (2026-08-30)

**배경.** 표준 절차(오디팅 서브에이전트 파견 → 직접 실제 코드 재확인 →
수정·회귀 테스트 → 기기 전체 pytest 베이스라인 대조)를 이번에도 그대로
따랐습니다. 대상은 이미 각자 전담 재감사를 마친 업무 모듈(수집기·결투·
매크로/PEGY/보조지표/리포트·스코어카드·배당·미국주식)이 아니라, 그 모듈들이
**공통으로 가져다 쓰는** 코드 14개 파일입니다. 스코핑 단계에서 `utils/db.py`
(이름과 달리 실제로는 매크로 방공망 전용 — `market_history.csv` 저장·복구
계층)와 `utils/guardrail.py`(코스피 PEGY 전용)·`utils/data_validator.py`/
`utils/gdrive_helper.py`(둘 다 매크로 `scrape_daily.py`·코스피 수집기 전용)를
grep으로 실제 호출처를 하나씩 추적해 "이름은 범용적이지만 실제로는 특정
모듈 전용"인 파일들을 제외했습니다(§0-3-6·§0-3-10) — 최종 대상은
`web/theme.py`·`web/auth.py`·`web/auth_ui.py`·`web/layout.py`·`web/state.py`·
`web/blocking.py`·`web/ads.py`·`web/components/*.py`·`utils/data_source.py`·
`utils/stock_history.py`·`utils/stock_export.py`.

**감사 결과.** Structural/High급 결함은 없었습니다(세션 격리·인증 우회·XSS
전부 기존 방어가 견고). Medium 2건, Low 2건, 그리고 지난 미국주식 모듈에서
정책 결정만 나고 구현이 미뤄져 있던 M-13을 발견해 함께 처리했습니다.

**1) Medium-1 반영 — `utils/data_source.py` 콜드 스타트 동시 요청 시 중복
HTTP GET.** `_read_remote()`의 "다른 요청이 이미 받아오는 중" 가드
(`entry['fetching'] and entry['text'] is not None`)가 **아직 한 번도 성공한
적 없는**(재배포 직후 등) 상태에서는 뒷부분 조건에 걸려 무력화돼, 동시
접속자 수만큼 같은 파일에 `raw.githubusercontent.com` GET이 중복으로
나갔습니다(§0-3-2 "원격 서버에 무리 주지 않기" 위반). `threading.Event`를
캐시 엔트리에 추가해, 콜드 스타트 중 뒤늦게 도착한 요청은 새 GET을 내지
않고 이미 진행 중인 요청의 완료를 기다렸다가 그 결과를 같이 쓰도록
고쳤습니다(락 밖에서 대기 + 타임아웃 방어). `tests/test_data_source.py`에
`test_reaudit_medium1_concurrent_cold_start_no_duplicate_fetch()`를 추가 —
가짜 HTTP 응답을 일부러 지연시켜 두 스레드가 동시에 콜드 스타트 구간에
들어가게 만든 뒤 실제 HTTP 호출이 1번만 나가는지 확인합니다(수정 전
코드로 되돌려 이 테스트가 실제로 실패함을 확인한 뒤 원상 복구).

**2) Medium-2 반영 — `utils/stock_history.py` 필드 목록에서 컬럼을 빼면
과거 이력이 조용히 영구 삭제됨.** `write_history_rows()`는 매번 "전체 읽기
→ 새 필드 목록으로 통째로 재작성" 방식이라, 누군가 `KOSPI_HISTORY_FIELDS`/
`US_HISTORY_FIELDS`에서 키 하나를 지우거나 이름을 바꾸면 다음 수집 한 번에
그 컬럼의 **과거 몇 달치 데이터까지 전부** 사라지는데도 경고나 확인 절차가
전혀 없었습니다(§0-1 정신 — 실데이터가 조용히 사라지면 안 됨). 기존 파일
헤더와 새 필드 목록을 대조해 빠진 컬럼이 있으면 서버 로그에 경고를 남기는
`_detect_dropped_history_columns()`를 추가했습니다(화면에는 노출하지
않음 — 수집기 콘솔에만 남는 진단이라 §0-3-4 취지에 맞게 서버 쪽 채널로).
`tests/test_stock_history.py`에
`test_reaudit_medium2_dropped_column_warns_before_data_loss()` 추가(컬럼을
빼는 경우/안 빼는 경우 양쪽 다 확인해 오탐도 점검).

**3) Low-4 반영(주석만, 동작 변경 없음) — `web/blocking.py`의 "블로킹 위임은
한 곳으로 모은다" 원칙을 우회하는 곳 2군데.** `web/state.py::
load_json_file_async()`와 `web/components/widgets.py::download_button()`의
`_click()`이 `run.io_bound()`를 `web/blocking.py`를 거치지 않고 직접 부릅니다.
지금은 둘 다 감싸는 함수가 **항상 튜플**을 반환해 우연히 안전하지만(그래서
`web/blocking._boxed()`가 막으려는 "정상적으로 bare None을 반환하는 함수"
모호성이 애초에 생기지 않음), 이 사실이 코드에 명시돼 있지 않아 나중에
반환 계약이 바뀌면 §0-1 버그(취소를 정상 빈 값으로 오인)가 조용히
재발할 수 있습니다. 두 곳에 "왜 안전한지"와 "이 가정이 깨지면 재검토할
것"을 명시하는 주석만 추가했습니다.

**4) Low-5 반영 — 설정 오류 배너 문구가 항상 "사본입니다"라고 단정.**
`get_staleness_status()`의 설정 오류(`DATA_SOURCE_BASE_URL` 오타 등) 분기는
`_read_local()`이 이 함수가 보는 캐시에 결과를 남기지 않는 구조라, 로컬
사본조차 없는 화면이 섞여 있어도 전역 배너가 "사본을 보여주고 있다"고
단정적으로 말했습니다(정상 배포에서는 거의 발생하지 않는 조합이지만
§0-1 정신에는 어긋남). 문구를 "화면에 값이 보인다면 사본, 안 보이는 화면은
그 화면의 개별 실패 안내를 확인하라"는 조건부 표현으로 바꿨습니다.

**5) M-13 최종 반영 — 이력 CSV의 카드·CSV 정보 정책 재정비 (코스피·미국
동시).** 지난 미국주식 모듈(#165~#166)에서 오너가 이미 정책 방향을
확정했던 사안입니다: "카드에는 표기가 되는데 CSV에 빠지면 말이 안 되는데,
정보는 항상 같아야지 여기하고 저기하고 다르면 안 되는 것"(2026-08-29).
이번에 실제 구현했습니다.

  - `tests/test_stock_history.py`의 `FORBIDDEN_KEYS`(카드·CSV 정책의 실질적
    구현체)를 다시 감사해, **화면이 실제로 읽어서 문구를 만드는 필드**인지
    grep으로 하나씩 확인했습니다. `is_valid`·`is_unverified`·`reject_reason`·
    `unverified_reason`·`forward_data_missing`·`forward_missing_fields`·
    `score_excluded_items`·`growth_score_capped`·`f_target_capped`·
    `f_target_cap_reason`·`f_target_uncapped`·`t_fair_capped`·
    `t_fair_uncapped`·`g_eff_capped`·`g_eff_uncapped`·`dps_source`·
    `growth_source`·`sh_return_basis` 18개는 실제로 카드의 배지·툴팁·
    Forward 마스킹 박스·그레이엄 산출불가 박스 문구를 만드는 데 쓰이고
    있어 **차단 목록에서 뺐습니다.** 반대로 `badge_bg`/`badge_fg`(색상
    hex)·`is_visible`(단순 노출 필터)·`data_issues`/`collect_errors`
    (관리자 전용 진단)·`t_roe_inherited_from`/`dps_inherited_from`/
    `target_per_capped`/`t_eps_source`/`f_eps_source`/`price_source`/
    `name_kr_source`/`sector_basis`/`url`/`raw_score`(전 화면 어디서도
    읽지 않음, grep으로 확인)는 **차단을 그대로 유지**했습니다 — "카드에
    보이는 것과 CSV가 같아야 한다"는 원칙이지 "스냅샷의 모든 내부 필드를
    다 내보내자"는 게 아니기 때문입니다.
  - `KOSPI_HISTORY_FIELDS`에 24개, `US_HISTORY_FIELDS`에 25개 필드를
    새로 추가했습니다(위 18개 + FORBIDDEN_KEYS에는 원래 없었지만 필드
    목록에서만 빠져 있던 `t_eps_calculated`·`is_trailing_loss`·
    `loss_evidence`·`t_per_measured`·`graham_is_financial_sector`·
    `dividend_data_unverified`·`dividend_unverified_reason`(코스피) /
    `price_calculated`·`f_eps_calculated`·`f_target_floored`·
    `t_fair_floored`·`forward_per_extreme`·`dividend_data_unverified`·
    `dividend_unverified_reason`(미국) 등). 각 필드가 실제로 어느
    collector/scoring 모듈에서 어떤 타입(bool/num/text)으로 채워지는지
    `collector_kospi200.py`·`collector_us_stocks.py`·`utils/scoring_us.py`·
    `utils/guardrail.py`를 grep으로 대조해 라벨과 종류를 정했습니다.
  - `dps_source`/`growth_source`처럼 값 자체가 `"derived_from_div_yield"`
    같은 **내부 코드 문자열**인 필드는, 카드가 보여주는 자연어 문구를 CSV에
    그대로 복제하지 않았습니다(§0-3-10 — 렌더링 로직을 두 곳에 중복
    구현하지 않기 위해). 대신 같은 근거 정보(왜 이 값인지)를 코드값
    그대로 실어, "정보 자체는 카드와 CSV에 항상 같이 존재한다"는 원칙을
    지켰습니다.
  - `score_excluded_items`/`loss_evidence`/`forward_missing_fields`는
    스냅샷에 **리스트**로 저장돼 있어(`to_storage_cell()`이 `str()`로
    바로 찍으면 파이썬 리스트 표기 `['a', 'b']`가 나와 엑셀에서 읽기
    나쁨), `to_storage_cell()`에 리스트를 `"; "`로 이어붙이는 분기를
    추가했습니다. 기존 필드 중 리스트값은 없어 회귀 위험 없이 일반화만
    했습니다.
  - `tests/test_stock_history.py`에
    `test_reaudit_m13_card_and_csv_information_parity()`를 추가 — 코스피·
    미국 양쪽 합성 종목으로 새 필드 24/25개가 실제 CSV/JSON에 값 그대로
    실리는지, 리스트값이 `"; "`로 정상 이어붙는지 확인합니다(수정 전
    코드로 되돌려 `KeyError`로 실패함을 확인한 뒤 원상 복구). 기존
    `test_export_end_to_end()`의 "내부 필드가 CSV에 없어야 한다" 예시
    목록에서 이제는 정당하게 CSV에 포함되는 `f_target_cap_reason`을 빼고
    여전히 차단 대상인 `value_trap_basis`로 교체했습니다.

**6) Low-6 — 검토했으나 조치하지 않음.** `pegy_page.py`의 관리자 전용
야후 파이낸스 교차검증 배지(`per_discrepancy`)도 CSV에는 없지만, 이건
일반 사용자에게는 애초에 보이지 않는 관리자 전용 정보라 "카드·CSV 정보
불일치"에 해당하지 않습니다. 참고로만 기록해 두고 이번 라운드에서는
건드리지 않았습니다.

**검증.** 기기 저장소에서 이번에 바뀐 6개 파일(`utils/data_source.py`·
`utils/stock_history.py`·`web/state.py`·`web/components/widgets.py`·
`tests/test_data_source.py`·`tests/test_stock_history.py`)을 매번 동기화한
직후 `git diff HEAD`로 의도한 변경만 있는지 확인했고, 각 신규 회귀
테스트는 수정 전 코드로 일시적으로 되돌려 실제로 실패하는지(오탐이 아닌지)
개별 확인한 뒤 복구했습니다. 마지막에 `git stash`로 커밋된 HEAD 상태의
전체 `pytest --ignore=archive`를 먼저 돌려 베이스라인(FAILED 3건·ERROR
4건 — 전부 이 모듈과 무관한 기존 결함: `test_duel.py` 표기 통일 2건,
NiceGUI 슬롯 스택 관련 렌더 스모크 4건)을 기록해 두고, `git stash pop`
후 다시 전체를 돌려 FAILED/ERROR ID 집합이 베이스라인과 **완전히 동일**함을
확인했습니다. 통과 수 1749 → 1752(+3, 이번에 추가한 신규 회귀 테스트
3개: Medium-1·Medium-2·M-13). `py_compile`로 수정 파일 전부 컴파일 확인.

이것으로 4차 재감사 8개 모듈 중 공유인프라까지 7개가 끝났습니다. 마지막
남은 모듈은 테스트 스위트입니다.


### #168 — 4차 재감사 8번째(마지막) 모듈: 테스트 스위트 자체 전수 재감사 (2026-08-30)

**배경.** 이번 모듈은 지금까지와 성격이 다릅니다 — 프로덕션 코드가 아니라
**그 프로덕션 코드를 지키는 테스트 코드 자신**을 감사 대상으로 삼았습니다
(오너의 8개 모듈 계획의 마지막 항목). 표준 절차(오디팅 서브에이전트 파견 →
직접 실제 코드 재확인 → 수정·회귀 검증 → 기기 전체 pytest 베이스라인 대조)를
그대로 따르되, 이번엔 사전 문서(`SPAGHETTI_AUDIT_2026-08-29.md`)의 "2-8.
테스트 스위트" 항목(높음 4·중간 9·낮음 3, 집계만 있고 세부는 없어짐)을 출발
단서로 삼아 실제 소스를 직접 재확인하며 항목을 다시 확정했습니다.

**감사 결과 — 실제로 확인된 항목만 High 3·Medium 2·Low 1로 정리, 재구조화형
2건(S)은 이번 라운드에서 백로그로 넘겼습니다.** 이 모듈 특유의 위험은 딱
하나입니다 — "이 테스트, 사실 한 번도 실행된 적이 없었다"는 부류의 결함은
프로덕션 버그와 달리 **화면·로그 어디에도 흔적이 안 남아** 다음 재감사가
소스를 한 줄씩 읽기 전까진 영원히 안 드러납니다. 이번에 확인된 High 3건이
전부 정확히 이 부류였습니다.

**1) H-1 — `test_us_stocks_page.py`에 `check()`/`FAILURES` 무음 통과 방지
장치가 없었음.** 2026-08-21 `test_data_source.py`에서 처음 발견된 것과 같은
버그 종류(`check()`는 실패를 리스트에 적기만 하고, 그 리스트를 실제로 검사해
죽는 코드는 `if __name__ == "__main__": main()` 안에만 있어 pytest 경로에서는
실패해도 초록불)입니다. 이 파일에는 그 이후 다른 7개 파일에 이미 퍼진
표준 방어(`@pytest.fixture(autouse=True)`로 테스트 전후 `FAILURES` 증가분을
확인)가 아직 없었습니다 — 새 파일이 생길 때마다 이 방어를 손으로 복사해
넣는 방식의 구조적 한계(§0-3-10 위반 소지, S-2에서 근본 해결 검토).
동일한 fixture를 추가하고, 기존 검사 하나를 일부러 깨뜨려 pytest가 실제로
빨간불이 되는지 확인한 뒤 원상 복구했습니다.

**2) H-3 — `main()`의 수동 함수 목록이 실제 `test_*` 정의보다 오래됨(4개
파일).** `python tests/test_x.py`로 직접 실행하는 경로 전용 문제입니다
(pytest 경로는 위 fixture 덕분에 애초에 무영향). `test_macro_scoring.py`
(29개 중 12개 미호출)·`test_report.py`(23개 중 3개)·`test_scorecard.py`
(20개 중 2개)·`test_stock_history.py`(17개 중 1개)에서 새 `test_*`를
추가하면서 `main()`의 호출 목록에 넣는 걸 빠뜨린 사례가 누적돼 있었습니다.
patch가 아니라 **이 버그 종류 자체를 구조적으로 없애는** 방향으로
갔습니다(§0-3-10) — `inspect`로 그 모듈 자신이 정의한 `test_*`를 소스
줄 번호 순서대로 자동 수집해 부르는 공용 헬퍼 `tests/_test_discovery.py`를
신설하고, 4개 파일의 `main()`을 전부 이 헬퍼 호출 한 줄로 교체했습니다.
pytest 전용 픽스처(`tmp_path`/`monkeypatch`)를 받는 함수는 인자를 채울
방법이 없어 자동으로 건너뛰되, 건너뛴 개수를 출력해 조용히 누락되지
않게 했습니다. 4개 파일 전부 `python3 tests/test_x.py` 직접 실행으로
컴파일·정상 동작 확인, `test_stock_history.py`가 그동안 조용히 빠져있던
`test_market_field_round_trips_and_defaults_to_blank_when_absent`를 이제
실제로 실행함을 확인했습니다.

**3) S-1 — `test_web_session_isolation.py`의 렌더 스모크 4개가 슬롯 스택
`RuntimeError`로 실패(pytest 전체 실행 시).** 2026-08-29 스코어카드 모듈
M-6에서 발견해 `tests/_render_helpers.py::run_render()`로 해결했던 문제와
같은 근본 원인인데, 이 파일은 그 헬퍼가 생기기 전에 작성돼 여전히
`asyncio.run()`을 직접 쓰고 있었습니다(§0-3-10 — 같은 문제의 같은 해법을
한 곳에서만 관리하지 못하고 있었음). `run_render` import를 추가하고 4개
렌더 스모크 함수(내 성적표·사장님 보고서·매크로·결투) 안의 `asyncio.run(`
10곳을 `run_render(`로 교체했습니다(로그인류 `auth.login()` 호출은 UI를
그리지 않으므로 그대로 둠). 교체 도중 **한 곳을 놓쳤던 것**을 이번에
검증 단계에서 직접 잡았습니다 — `test_report_render_smoke()`가 부르는
헬퍼 함수 `_capture_report_render()` 안의 `asyncio.run(page._render_report_body(...))`
는 `test_report_render_smoke()` 함수 자체의 줄 범위 밖에 있어 처음 교체
때 범위에서 빠졌습니다. `pytest tests/test_web_session_isolation.py -q`를
전체로 돌려서야(개별 실행으로는 안 잡힘 — 프로세스당 한 번만 생기는
"유사 클라이언트"를 먼저 도는 테스트가 소진해버리는 게 원인이라, 실행
순서·조합에 따라 드러나는 결함) 드러났고, 즉시 같은 방식으로 교체했습니다.

  또한 `test_macro_render_smoke()`는 `nicegui.app.storage.user`를 직접
  건드리고 있었는데, 이 저장소에는 실제 nicegui가 설치돼 있어(스텁이 아님)
  진짜 `Storage` 클래스가 동작합니다 — 실제 요청 컨텍스트 없이 접근하면
  `RuntimeError: app.storage.user needs a storage_secret` 로 죽거나(단독
  실행), "스크립트 모드" 폴백 경로가 **접근할 때마다 새로 만드는 일회용
  딕셔너리**를 돌려줘 쓰기가 다음 읽기에 반영되지 않습니다(전체 실행 —
  `nicegui/context.py`의 `is_script_mode_preflight()` 조건 직접 확인).
  이건 `run_render()`로 고칠 수 있는 종류가 아니라 애초에 잘못된 도구를
  쓰고 있던 것이라 판단해, `web/pages/macro_page.py`가 `web.auth`에서
  이름으로 가져다 쓰는 `is_admin` 함수를 **직접 monkeypatch**하는 방식으로
  바꿨습니다 — 실제 Storage 객체를 건드리지 않고, §0-3-8이 요구하는 대로
  "관리자 여부는 명시적으로 받는다"는 원칙에 오히려 더 맞습니다. 나머지
  구간(2)~(4)는 `_render_dashboard()`/`_render_ai_commentary()`를
  `macro_page()` 게이트를 우회해 직접 호출하므로 `app.storage.user` 조작이
  원래도 무해했음을 확인하고 그대로 뒀습니다. `pytest -q`(개별)·
  `pytest tests/test_web_session_isolation.py -q`(전체)·
  `python3 tests/test_web_session_isolation.py`(직접 실행) 세 경로 모두
  18개 테스트 전부 통과 확인.

**4) H-2 — `test_report.py::test_view_and_scope()`의 "다른 모듈 안 건드림"
검사가 주석까지 코드로 오해해 오탐.** "리포트 관련 키워드가 다른 모듈
소스에 없어야 한다"는 검사가 원문 그대로 문자열 검색을 해서, 실제로는
전혀 무관한 **설명 주석**(`collector_us_stocks.py:610`·
`utils/constants_us.py:277` — 후자는 이번 4차 재감사 도중 제가 직접 적어
넣은 주석) 때문에 계속 빨간불이었습니다. 같은 파일에 이미 있던
`python_code_only()`(주석·docstring을 걷어내는 헬퍼, 다른 검사에서 이미
같은 목적으로 쓰이고 있음)를 재사용해(§0-3-10 — 새 헬퍼를 또 만들지 않음)
검사 대상을 실제 코드로 좁혔습니다. 진짜 위반(주석이 아니라 실제 코드에
`report_db` 문자열이 들어간 경우)은 여전히 잡히는지 일부러 그런 줄을
넣어 확인한 뒤 되돌렸습니다.

**5) M-2 — `test_scorecard_public_ui.py::test_consent_body_renders_every_state`가
assert 없는 순수 스모크였음.** 동의 화면의 세 상태(기록없음/최종확인/철회)를
각각 그려보긴 했지만 "예외 없이 끝까지 실행됐다"만 확인했지 "그 상태에
맞는 문구가 실제로 나왔다"는 전혀 확인하지 않았습니다 — 세 상태의 라벨을
서로 뒤바꿔 매핑해도 이 테스트는 계속 초록불이었을 것입니다.
`consent_page.ui.markdown`을 캡처해 `_render_current_state()`가 상태별로
쓰는 정확한 문구("비공개 (공개 동의 기록이 없습니다)" / "공개 신청 완료
(발행 대상)" / "철회됨")가 실제로 나왔는지, 그리고 **다른 상태의 문구가
섞여 나오지 않는지**까지 확인하도록 다시 썼습니다. 검증을 위해
`scorecard_consent_page.py`의 "confirmed" 라벨을 일부러 "철회됨"으로
바꿔치기해 새 assert가 정확히 그 오류를 잡아내는지 확인한 뒤 되돌렸습니다
(`git checkout --`로 원복, `git status`로 프로덕션 코드에 변경 없음 확인).

**6) M-3 — `tests/_render_helpers.py` 독스트링의 import 예시가 실제와
다름.** "`from tests._render_helpers import run_render`로 가져다 쓴다"고
적혀 있었는데, `tests/`는 `__init__.py`가 없는 패키지가 아니라서 이
문장 그대로 쓰면 실제로는 `ModuleNotFoundError`가 납니다. 실제로 쓰는
3개 파일(`test_scorecard_ocr.py`·`test_scorecard_public_ui.py`·
`test_web_session_isolation.py`) 전부 `sys.path.append(...)`로 `tests/`
자신을 경로에 얹은 뒤 `from _render_helpers import run_render`로 가져다
쓰는 걸 확인하고, 독스트링을 그 실제 관례에 맞게 고쳤습니다.

**7) 검토 후 이번 라운드에서는 백로그로 넘김.**
  - **S-2 — `tests/conftest.py` 부재.** 29개 파일이 `sys.path` 부트스트랩을
    각자 복제하고, `check()`/`FAILURES` 무음 방지 fixture가 이제 8개 파일에
    (이번 H-1 수정으로 1개 늘어) 동일하게 복제돼 있고, 6개 파일이
    `test_duel_db.py`를 라이브러리처럼 import합니다. 이건 이미 백로그에
    "🆕 #156 `tests/conftest.py` 부재"로 등재돼 있던 항목과 같은 사안임을
    이번에 재확인했습니다 — 그 항목의 세부 사례 목록을 이번 감사 결과로
    갱신했습니다(아래 백로그 섹션 참고). 공용 fixture 하나로 옮기는 리팩터는
    29개 파일 전부에 손을 대는 범위라 스팟 감사 스타일 재감사보다는 별도
    계획이 필요하다고 판단해 이번에도 손대지 않았습니다.
  - **M-1 — `.count("문자열") == N` 형태의 브리틀한 단언 여러 곳.** 소스에
    무해한 리팩터(예: 같은 문자열을 설명하는 주석 한 줄 추가)만 있어도
    깨질 수 있는 검사 방식입니다. 지금 당장 오탐/미탐이 실제로 발생하고
    있는 건 아니고(H-2처럼 이미 발생한 사례는 이번에 고쳤음), 스타일·
    견고성 문제라 우선순위를 낮춰 백로그로 남겼습니다.

**8) 재확인만 하고 손대지 않은 기존 결함 — `test_duel.py` 통화 표기 통일성
2건.** 공유인프라 모듈(#167)을 포함해 지난 여러 라운드의 베이스라인
검증에서 계속 "이 모듈과 무관한 기존 결함"으로 기록만 되고 있던 항목인데,
이번이 마지막 모듈이라 처음으로 백로그에 독립 항목으로 등재했습니다
(§0-3-6 — 결투 모듈은 이미 완료된 모듈이라 이번엔 건드리지 않음). 아래
백로그 섹션 참고.

**검증.** 기기 저장소에서 수정한 8개 파일(`tests/_render_helpers.py`·
`tests/test_macro_scoring.py`·`tests/test_report.py`·`tests/test_scorecard.py`·
`tests/test_scorecard_public_ui.py`·`tests/test_stock_history.py`·
`tests/test_us_stocks_page.py`·`tests/test_web_session_isolation.py`)과
신규 파일(`tests/_test_discovery.py`)마다 `python3 -c "import ast; ast.parse(...)"`로
구문 확인, 각 수정 지점은 해당 파일만 pytest로 개별 확인 후 마지막에
`git stash -u`로 이번 라운드의 모든 변경을 걷어낸 **커밋 `7f89d8b`
그대로의 상태**에서 전체 `pytest --ignore=archive -q`를 한 번 돌리고,
`git stash pop`으로 되돌린 뒤 다시 한 번 돌려 결과를 대조했습니다.
수정 전: `FAILED` 3건(`test_duel.py` 통화 표기 통일성 2건 + 아직 고치기
전의 `test_macro_render_smoke`) + `ERROR` 4건(`test_report.py::test_view_and_scope`
[H-2] · 렌더 스모크 3건인 `test_render_smoke`·`test_report_render_smoke`·
`test_duel_render_smoke` [S-1] — 이 4건은 `check()`/`FAILURES` 방식 특성상
테스트 본문은 "통과"로 집계되고 autouse fixture 뒤처리에서만 별도로
`ERROR`로 잡히는 방식이라 `1752 passed`에도 동시에 포함됨), 총 문제
노드 7개 / 정상 노드 1752개(전체 1755개 중). 수정 후: `FAILED` 2건
(`test_duel.py` 통화 표기 통일성 — 완전히 무관한 기존 결함, 값·메시지
전부 수정 전후 동일함을 확인) · `ERROR` 0건, `1753 passed` — 문제 노드가
7개에서 2개로 줄고, 그 2개는 전부 이번 모듈이 손대지 않은 기존 결함임을
확인했습니다(전체 노드 수 1755개는 불변 — 테스트를 늘리거나 줄이지
않고 오탐만 걷어냄). `test_consent_body_renders_every_state`는 위 5)에서
설명한 대로 프로덕션 코드를 일부러 깨뜨려 새 assert가 실제로 잡는지
음성 대조까지 마쳤습니다.

이것으로 오너가 계획한 4차 재감사 8개 모듈(수집기·결투·매크로/PEGY/
보조지표/리포트·스코어카드·배당 KR/US·미국주식·공유인프라·테스트 스위트)이
전부 끝났습니다.

### #169 — 테스트 스위트 무결성 메타 테스트 신설 (`tests/test_suite_integrity.py`) (2026-08-30)

**배경.** #168(테스트 스위트 재감사)을 마치고 오너에게 결과를 보고하는 자리에서
나온 지적: "이걸 좀 더 막으려면 감시형 모듈을 하나 만들어 둬야 하지 않을까 —
어차피 채팅방은 대화가 너무 쌓여서 모듈별로 영구적으로 관리할 수는 없다."
정확한 지적입니다. #168의 High 3건, 그리고 그보다 앞선 2026-08-29 M-14
(`test_quant.py`)까지 합치면, **같은 뿌리의 결함이 세 가지 다른 모양으로 세 번**
나왔습니다 — 전부 "테스트가 빨간불을 내야 하는데 조용히 초록불"이었던 경우이고,
전부 사람이 몇 주에 한 번 재감사를 돌다 우연히 발견한 것입니다. 오너 지시대로
사람의 기억이나 대화 이력에 의존하지 않는 **영구적·구조적 방어선**을 만들기로
하고, 오푸스에게 "최대한 신중하게" 설계·구현·검증을 맡겼습니다(제가 최종
검토·독립 검증·커밋).

**신설한 것.** `tests/test_suite_integrity.py`(354줄, 신규) — `tests/` 안의
`test_*.py` 34개 전체(자기 자신 포함, `archive/`는 저장소 관례대로 제외)를
매 pytest 실행마다 자동으로 다시 훑어 세 가지를 검사합니다.

  - **Check A** — `FAILURES`/`check()` 하네스를 쓰는 파일은 반드시 그 실패를
    pytest 실패로 승격시키는 장치(`autouse` 픽스처가 `FAILURES`를 실제로
    들여다보거나, 모든 `test_*`가 스스로 `assert not FAILURES`로 끝나거나)가
    있어야 합니다. 이름을 살짝 바꿔 복사한 하네스 사본(`_FAILURES`/`_check` 등)도
    잡도록 느슨하게 인식합니다 — 이 하네스 자체가 복사·붙여넣기로 퍼지는 물건이기
    때문입니다.
  - **Check B** — `main()`(직접 실행 진입점)이 있는 파일은 그 파일이 정의한
    `test_*`를 빠짐없이 불러야 합니다. `tests/_test_discovery.py`의
    `discover_and_run_module_tests()`를 쓰면 설계상 합격(§0-3-10 — 같은 판정을
    두 번 구현하지 않음), 손으로 나열하는 방식이면 실제 정의와 AST로 한 건씩
    대조해 빠진 함수 이름을 그대로 실패 메시지에 찍습니다.
  - **Check C** — 모든 `test_*.py`에서 pytest가 실제로 1건 이상 수집해야 합니다.
    이 판정만은 AST로 흉내 내지 않고 `pytest --collect-only`를 하위 프로세스로
    직접 불러 **pytest 자신에게 물어봅니다**(전체 1회 약 6~7초, `lru_cache`로
    34개 케이스가 공유) — 판정 로직을 재구현하면 그 사본이 어긋나는 순간 이
    파일 자신이 새로운 "겉보기 정상"의 원천이 되기 때문입니다.

**검증 — 오푸스 자체 검증 + 제 독립 재검증.** 오푸스가 세 검사 각각에 대해
실제 역사적 결함을 파일에 일부러 재현(A: `test_us_stocks_page.py`의 픽스처를
지움/`autouse=False`로 바꿈/`FAILURES`를 안 보게 본문만 바꿈 3종, B:
`test_us_stocks.py`·`test_report.py`의 호출 목록에서 각각 1건·3건 빼기, C:
`run_golden_tests()`류 새 파일 추가 + `test_quant.py`를 실제로 `run_case*`로
치환한 재현)한 뒤 정확히 그 파일을 지목하는 실패가 나는지 확인하고 즉시
원복했다고 보고했습니다. **이걸 그대로 믿지 않고** 제가 별도로 — 오푸스가
건드리지 않은 `test_data_source.py`의 픽스처를 골라 똑같이 무력화해 Check A가
잡아내는지 재현했고(정확히 그 파일명을 지목하는 동일한 실패 메시지 확인),
`diff`로 원복이 바이트 단위로 깨끗한지 확인했습니다. 전체 스위트는 `git stash`
베이스라인 대조로: 신설 전 `2 failed, 1753 passed`(무관한 기존 `test_duel.py`
통화 표기 결함 2건, 변화 없음) → 신설 후 `2 failed, 1807 passed, 53 skipped`
(신규 +54 pass/+53 skip, 전부 이 파일 소관 — Check A 10 pass/25 skip, Check B
7 pass/28 skip, Check C 35 pass, 표준 2건). 전체 실행 시간은 6~8초 늘었습니다
(Check C의 하위 pytest 1회 호출).

**알아둘 것 — 이 방어선의 한계(오푸스가 스스로 밝힌 것, 그대로 남겨둠).**
Check A·B는 모듈 최상위 정의만 봅니다(현재 `class Test*`·`async def test_*`가
저장소에 0건임을 확인했지만, 생기면 사각지대). Check B는 `f()`처럼 이름으로
직접 부르는 호출만 인식하므로 `globals()[name]()` 같은 간접 호출은 오탐
가능(다만 실패 방향이 "헬퍼를 쓰라"는 안전한 쪽). **가장 중요한 것**: 백로그의
`tests/conftest.py` 통합(#156/S-2, `FAILURES`/`check()` 하네스를 공용 모듈로
옮기는 리팩터)이 실행되면, Check A는 그 공용 모듈을 보지 않으므로 **조용히
무력화됩니다** — 그 리팩터를 할 때는 이 파일의 하네스 인식 로직도 함께
갱신해야 합니다.

이것으로 4차 재감사(#158~#168)에 이어, 같은 부류의 결함이 다섯 번째로
재발하는 걸 막는 구조적 장치가 생겼습니다.

### #170 — pytest 자동 실행 워크플로우 신설 + 디스코드 알림 연결 (2026-08-30)

**배경.** #169(테스트 스위트 무결성 메타 테스트)를 만든 직후 오너가 짚은 점:
지금 디스코드로 최대한 오류 알림을 받아보려 하고 있는데, 이번 같은 부류(테스트가
조용히 안 도는 것)는 애초에 "터지는" 게 없어서 알림받을 신호 자체가 없었다.
정확한 지적이라 실제로 저장소를 확인해 보니, **이 저장소에는 지금까지 pytest를
자동으로 돌리는 GitHub Actions 워크플로우가 하나도 없었습니다** — 13개 워크플로우가
전부 수집·배치·감시용이고, 테스트는 항상 사람이 로컬(개발 기기)에서 손으로
돌려서만 확인해 왔습니다. `#169`처럼 "매 실행마다 재검사"를 전제로 설계한
안전장치도 그 실행 자체가 자동으로 안 일어나면 무의미하다는 점에서, 이건
`#169`를 만들면서 바로 드러난 간극이었습니다.

**신설.** `.github/workflows/test_suite.yml` — `main` 브랜치에 push될 때마다(+
수동 실행 버튼) `requirements.txt` 설치 후 `pytest --ignore=archive -q`를 그대로
돌립니다. 실패하면 (1) 잡 자체가 실패 처리돼 Actions 탭에 빨간 X로 남고, (2)
저장소에 이미 등록돼 있는 `DISCORD_WEBHOOK_URL` 시크릿(2026-08-28, `watch_schedule_health.yml`이
쓰는 것과 **동일한 시크릿을 재사용** — 이 워크플로우를 위해 새로 설정할 게
없음)으로 같은 내용을 디스코드에도 보냅니다. 통과했을 때는 알림을 보내지
않습니다(문제 있을 때만 알리는 게 낫다는 판단 — 매 push 알림은 소음). 페이로드는
`watch_schedule_health.yml`과 같은 방식(`python3 -c`로 JSON 이스케이프)이라
커밋 관련 문자열에 따옴표·개행이 섞여도 깨지지 않습니다. 일부러 안 한 것 —
실패마다 이슈를 자동 생성하지는 않음(빨간 X + 디스코드로 이미 충분히 눈에
띄고, push마다 이슈가 쌓이면 소음이 될 수 있어서). 필요하면 나중에 추가 가능.

**검증.** 세 단계로 확인했습니다.
1. YAML 자체를 `pytest`가 아니라 `yaml.safe_load()`로 파싱해 문법 오류를
   잡았습니다 — 실제로 한 번 잡혔습니다: `- name: pytest 전체 실행 (저장소
   관례와 동일: archive/ 제외)`의 괄호 안 콜론이 YAML 매핑 구분자로 오인되는
   `ScannerError`가 났고, 그 값을 따옴표로 감싸 해결했습니다.
2. 디스코드 알림 스텝의 셸 스크립트를 `bash -n`으로 문법 검사하고, 실제로
   실행해 메시지·JSON 페이로드가 한글·이모지·백틱이 섞여도 깨지지 않고
   `json.loads()`로 파싱 가능한 유효한 JSON이 나오는지 확인했습니다(실제
   디스코드 전송은 하지 않음 — 웹훅 URL이 없어 안전하게 시뮬레이션만).
3. **이 저장소에서 pytest를 자동 실행 환경에서 돌리는 게 이번이 처음**이라,
   개발 기기에 이미 설치된 패키지에 기대지 않고 완전히 새 가상환경을 만들어
   `requirements.txt` + `pytest`만 새로 설치한 뒤 워크플로우와 똑같은 순서로
   미리 돌려봤습니다 — 결과가 로컬 개발 환경과 완전히 동일(FAILED 2건[기존
   `test_duel.py` 통화 표기 결함, 무관·미변경] · 1807 passed · 53 skipped)했습니다.
   가짜 클라이언트(FakeClient 등) 기반 설계와 `os.getenv()`(값 없으면 None)만
   쓰는 프로덕션 코드가 실제로 맞아떨어진다는 걸 시뮬레이션으로 확인한 것입니다.
   다만 GitHub Actions의 실제 러너는 이 가상환경 시뮬레이션과 완전히 같지는
   않으므로(OS 패키지·네트워크 환경 차이 가능), 워크플로우 파일 자체의 주석에도
   "배포 후 Actions 탭에서 실제 첫 실행 한 번은 오너가 확인" 문구를 남겼습니다.

**주의사항 — 오너 확인 필요.**
  - `DISCORD_WEBHOOK_URL` 시크릿이 지금도 저장소에 등록돼 있는지는 제가 값을
    읽을 수 없어(시크릿은 쓰기 전용) 확인하지 못했습니다. `watch_schedule_health.yml`이
    2026-08-28부터 정상적으로 디스코드 알림을 보내고 있다면 이미 등록돼 있는
    것이므로 별도 조치가 필요 없습니다.
  - push 후 GitHub Actions 탭에서 "테스트 스위트" 워크플로우가 실제로 초록불로
    끝나는지 한 번 확인해 주세요(위 3번 시뮬레이션으로 상당히 확신하지만, 클라우드
    러너 환경 자체의 실제 실행은 아직 아무도 안 해봤습니다).

### #171 — 결투 배치 통화 표기 불일치 수정 (`utils/duel_rules.py::_fmt_currency`) (2026-08-30)

**배경.** #170(pytest 자동 실행 + 디스코드 알림)을 push하자마자 실제로 디스코드
알림이 왔습니다 — 정확히 그동안 백로그에 남아 있던 기존 결함(`test_duel.py`
통화 표기 통일성 2건)이었습니다. 처음엔 "이미 아는 결함이니 놔둬도 된다"고
안내했는데, 오너가 "고치자"고 결정해 바로 반영했습니다.

**실제로 확인해 보니 알려진 것보다 범위가 넓었습니다.** 기존에 백로그에 적어둔
설명은 "USD에서만 끝자리 0이 잘린다"였는데, 두 함수(`duel_rules._fmt_currency()`
vs 화면의 단일 출처 `scorecard_db.format_amount()`)를 실제로 나란히 돌려 대조해
보니 **KRW 쪽에도 별도의 불일치가 있었습니다** — 소수점이 있는 원화 금액(예:
93,076.923)을 `format_amount()`는 화면 규칙대로 내림해서 "93,076원"으로 보여주는데,
`_fmt_currency()`는 소수점을 그대로 남겨 "93,076.923원"이 됩니다. `tests/test_duel.py`의
기존 회귀 테스트는 각 케이스마다 USD 검사를 KRW보다 먼저 실행하는 루프 구조라,
첫 번째 실패값(0.5)에서 USD 검사가 먼저 걸려 멈췄고, 그 뒤에 있던 KRW 쪽 불일치는
같은 테스트 실행에서 한 번도 드러난 적이 없었습니다.

**원인.** `_fmt_currency()`가 내부적으로 쓰던 `_fmt_money()`는 `f"{value:,.6f}"`로
찍은 뒤 끝자리 0을 기계적으로 지우는 범용 포매터였습니다 — 통화별 규칙(원화는
소수점 내림 후 정수 표기, 달러는 항상 소수점 둘째 자리 고정)을 전혀 반영하지
않고 있었습니다.

**수정.** `duel_rules.py`는 "표준 라이브러리 말고는 아무것도 import하지 않는다"는
이 파일 고유의 규율(순수 계산 계층, `tests/test_duel.py`가 네트워크·Supabase
없이 오프라인으로 검증하기 위한 설계)이 있어 `format_amount()`를 직접 부를 수
없습니다. 대신 `_fmt_money()`를 제거하고 `_fmt_currency()` 안에 `format_amount()`와
**같은 규칙을 표준 라이브러리(`math.floor`)만으로 재구현**했습니다 — USD는
`f"${number:,.2f}"`(항상 둘째 자리 고정), KRW는 `math.floor()`로 내림한 정수를
`f"{truncated:,}원"`. `_fmt_money()`는 이 파일 안에서도, 저장소 전체에서도 다른
호출부가 없어(grep으로 확인) 삭제해도 영향 없습니다.

**검증.** 기존 회귀 테스트(`test_fail_reason_amounts_use_the_same_notation_as_the_screen`·
`test_fill_failure_messages_carry_the_shared_notation`) 통과 확인에 더해, 그
테스트가 원래 다루던 6개 값 외에 **직접 추가로** `0`·`-5.5`(음수) 케이스까지
`_fmt_currency()`와 `format_amount()`를 나란히 돌려 전부 문자열이 정확히 일치하는지
확인했습니다(음수는 기존 회귀 테스트 케이스 목록에 없어 별도로 짚어본 것).
전체 baseline-diff: 수정 전 `2 failed, 1807 passed, 53 skipped` → 수정 후
`1809 passed, 53 skipped`(0 failed) — 새로 통과한 2건 외 회귀 0건.

**부수 효과.** 이걸로 이 저장소의 pytest 전체 스위트가 **처음으로 100% 초록불**이
됐습니다(`#170`이 감시하는 CI가 다음 push부터는 조용할 것입니다).

### #172 — `TASK_HISTORY.md` 오래된 구간 아카이브 분리 + 아카이브 정책 신설 (2026-08-30)

**배경.** 오늘 하루에만 #169~#171 세 항목이 새로 쌓이면서, 오너가 "이 속도면
200~300개가 됐을 때 이 문서 하나 읽는 데만 토큰이 엄청나게 들지 않겠냐"는 우려를
제기했습니다. 실제로 확인해 보니 근거가 있었습니다 — 파일이 4,253줄·약 573KB(171개
항목)까지 커진 상태였고, 특히 #100 이전 시절엔 항목 하나가 한두 줄이었던 것이 오늘
만든 #169~#171은 하나당 40~90줄(배경·원인·수정·검증·부수효과 문단)로, 항목당
무게가 이미 10배 가까이 늘어 있었습니다. 오너는 "기록 자체는 자세하게 쌓는 게
맞다(두 번 열어볼 일 없게)"는 입장이라 항목 분량을 줄이는 방향은 배제하고, 대신
"이미 완전히 끝난 오래된 구간을 별도 아카이브 파일로 옮기고 본 파일엔 안내만
남기자"는 방향을 오너가 직접 제시했습니다.

**신설/변경.**
1. `TASK_HISTORY_ARCHIVE.md` 신설 — #1~#153(2026-08-28 이전, `watch_schedule_health.yml`
   신설 이전까지의 전체 작업 이력)을 **글자 하나 안 바꾸고 그대로** 옮겼습니다.
   번호도 원래 번호(1~153) 그대로 유지.
2. 본 파일(`TASK_HISTORY.md`)에는 옮겨진 자리에 "#1~#153은 `TASK_HISTORY_ARCHIVE.md`
   참고"라는 안내 한 줄만 남겼습니다 — 별도 인덱스(항목별 제목 목록 등)는 일부러
   만들지 않았습니다(그 인덱스 자체가 또 다른 유지보수 부담이 되는 걸 피하기 위함,
   오너 지시 취지 그대로).
3. `ENGINEERING_SPEC.md`에 **§0-3-14**(오래된 완료 구간의 아카이브 분리 정책)를
   신설해, 이번 조치를 일회성이 아니라 앞으로도 반복될 표준 절차로 문서화했습니다.

**컷오프 기준 = #153/#154 경계, 임의로 고르지 않았습니다.** "이미 완전히 끝났다"는
걸 확인하려고 `## 진행 예정 (백로그)` 섹션을 먼저 훑었습니다 — 그 안에서 아직
🆕(미해결)로 남아 번호를 직접 참조하는 가장 오래된 항목이 **#154**
(`watch_schedule_health.yml`)와 **#156**(컷오버 유예·`tests/conftest.py` 리팩터)
이었고, #153 이하로 참조되는 항목(#148~#153)은 전부 ✅(완료 확인됨)로 이미 닫혀
있었습니다. 그래서 #153까지만 옮기고 #154부터는 본 파일에 그대로 남겼습니다 —
아직 살아있는 백로그 참조를 아카이브 뒤로 보내지 않기 위함입니다.

**검증.** 파이썬 스크립트로 줄 번호 기준 정확히 잘라 옮겼고(수작업 재입력 없음 —
오타·누락 위험 원천 차단), 옮긴 후 (1) 아카이브 파일 줄 수 + 본 파일 줄 수 = 원본
줄 수와 정확히 일치, (2) 아카이브 파일 안에 1~153번이 빠짐없이 순서대로 존재(정규식
번호 시퀀스 확인), (3) 본 파일 안에 154~172번이 빠짐없이 순서대로 존재, (4) `diff`로
옮겨진 아카이브 본문이 원본에서 발췌한 구간과 바이트 단위로 동일함을 확인했습니다.
코드·데이터 파일은 전혀 안 건드렸습니다 — 순수 문서 재배치입니다.

**참고 — 오너가 이미 명시적으로 배제한 방향.** "항목을 지금보다 짧게 요약해서
쓰자"는 채택하지 않았습니다(오너: "기록 자체를 할 거라면... 상세하게 쓰는 게
맞다") — 이 조치는 오직 "어디에 보관하느냐"만 바꾼 것이고, 앞으로 새로 쓰는
항목의 분량·상세도는 지금(예: #169~#171) 수준을 그대로 유지합니다.

### #173 — #172 아카이브 분리가 깨뜨린 테스트 핫픽스 (`tests/test_macro_scoring.py`) (2026-08-30)

**배경.** #172(TASK_HISTORY.md 아카이브 분리)를 push하자마자 새로 만든
CI(#170)가 실제로 실패를 잡아 디스코드 알림을 보냈습니다 — 만든 지 몇 시간도
안 돼 이 파이프라인이 실전에서 두 번째로 진짜 결함을 잡아낸 것입니다(#171에
이어).

**원인.** #172에서 #1~#153 항목을 `TASK_HISTORY_ARCHIVE.md`로 옮기면서,
`tests/test_macro_scoring.py`의 `test_short_indicators_reclassified`가
`TASK_HISTORY.md` 파일을 직접 읽어 "72번 항목이 기록됐는지"·"85.48이라는
재분배 계산 근거가 문서에 남아있는지"를 확인하던 검사가 깨졌습니다. #72(공매도
2종 재분류) 항목이 정확히 아카이브로 옮겨간 범위(#1~#153) 안에 있었기 때문 —
내용이 지워진 게 아니라 옮겨졌을 뿐인데, 테스트가 `TASK_HISTORY.md` 한 파일만
보고 있었던 게 문제였습니다.

**제가 놓친 부분 — 정직하게 남깁니다.** #172를 만들 때 아카이브 컷오프를
정하려고 `## 진행 예정 (백로그)` 섹션은 확인했지만, 저장소 전체(특히 `tests/`)에
`TASK_HISTORY.md` 파일 내용을 직접 읽어 검증하는 코드가 있는지는 확인하지
않았습니다. `grep` 한 번이면 미리 잡을 수 있었던 구멍이었습니다.

**수정.** `test_macro_scoring.py`가 `TASK_HISTORY.md`뿐 아니라
`TASK_HISTORY_ARCHIVE*.md`(glob, 앞으로 더 분리돼도 계속 잡히도록)까지 합쳐서
검사하도록 변경 — 내용이 어느 파일에 있든 계속 통과합니다. 저장소 전체를
`grep`해 `TASK_HISTORY.md`를 코드에서 직접 여는 곳이 이 한 곳뿐임을 확인했습니다
(나머지는 전부 주석·독스트링 안의 "TASK_HISTORY #NN 참고" 같은 텍스트 인용이라
파일을 열지 않음). `ENGINEERING_SPEC.md` §0-3-14에도 "아카이브 전에 백로그뿐
아니라 코드 전체에서 TASK_HISTORY.md를 직접 읽는 곳이 있는지 grep으로 확인"
문구를 추가해, 다음 아카이브 때 같은 구멍이 재발하지 않게 했습니다.

**검증.** 로컬 재현 — 수정 전 `1 error`(정확히 이 테스트. `ERROR`로 표시된
이유는 이 검사가 `check()`/`FAILURES` 하네스의 `autouse` 픽스처 teardown에서
올라오기 때문 — #169의 Check A가 지키는 바로 그 구조가 여기서도 조용히 넘어가지
않게 막아준 것). 수정 후 `1809 passed, 53 skipped, 0 error` — 완전히 원복.

### #174 — 수집 결과 산티체크(data sanity) 신설 — "돌긴 도는데 값이 이상한" 날 감시 (`utils/data_sanity.py`) (2026-08-30)

**배경.** 오늘 #171·#173 두 번 다 CI+디스코드가 실제 결함을 잡아낸 뒤, 오너가
"필요하면 알람은 더 와도 문제 없다, 자산 숫자를 다루는 이상 뻔히 아는 구멍을
넘어가면 안 된다, 알고 있는 요소는 지금 다 잡자"고 지시했습니다. 실제로 확인해
보니 이 저장소의 감시망엔 구체적인 빈틈이 하나 있었습니다 — `watch_schedule_health.yml`은
스스로 범위를 "오늘 이 워크플로우가 **실행됐는지**"로만 한정하고 있고(파일
머리말에 명시), `test_suite.yml`(pytest)은 **이미 아는 검사**만 지킵니다. 그
사이 — 수집은 성공했다고 기록됐는데 결과 값 자체가 그럴듯하지 않은 경우(종목
수 급감, 핵심 컬럼 전부 결측·0, 수집 실패를 상수로 채움, 어제 대비 값 수준이
말이 안 되게 튐)는 아무것도 안 잡고 있었습니다.

**신설(오푸스에게 최대한 신중하게 맡기고, 제가 독립적으로 재검증).**
- `utils/data_sanity.py`(신규, 순수 계산 계층 — 네트워크·Supabase·NiceGUI
  미접속) — 건수 급감(-30%)·급증(2배)·핵심 컬럼 결측/0 비율(30% 또는 급등
  +25%p)·값 전부 동일·중앙값 급변(2배/0.5배) 5가지 신호로 판정. **아무것도
  고치거나 채우지 않고 판정만** 함(§0-1). 임계값은 2026-08-29자 실제 산출물을
  직접 세어 정한 값이고, "정답이 아니라 판단"이라는 걸 코드 주석에 그대로
  남김(예: 코스피 507행 기준 결측 실측 0.0%, distinct 469/507 등).
- `collector_kospi200.py`·`collector_us_stocks.py`·`collector_indicator_kr.py` —
  기존 저장이 **전부 끝난 뒤**에 판정 호출 한 줄만 추가. 수집·파싱·계산 로직은
  한 글자도 안 건드림(`git diff` 확인 — 순수 추가 70줄, 삭제 0줄).
  `collector_dividend_kr.py`는 **의도적으로 제외**— 배당 수집은 스케줄이 연
  8회에 실행마다 정상적으로 건수가 크게 늘고, 부분 실행·이어하기가 정상
  동작이라 이 판정 방식 자체가 성립하지 않음(자체 `summary` 자기점검이 이미
  별도로 있음).
- `.github/workflows/watch_data_sanity.yml`(신규) — 위 세 수집기가 남긴
  `data/*_sanity.json`을 매일 한 번(00:30 UTC) 모아 읽고 `suspect`/`error`면
  기존 `DISCORD_WEBHOOK_URL` 시크릿·기존 페이로드 방식(`python3 -c` JSON
  이스케이프)을 그대로 재사용해 알림. `watch_schedule_health.yml`은 건드리지
  않음(그 파일이 스스로 밝힌 "실행 여부"라는 별개 관심사를 그대로 존중).
  기존 워크플로우 중 `indicator_kr.yml`의 `git add` 목록 9줄만 수정 —
  `scrape.yml`/`scrape_us.yml`은 이미 `data/` 전체를 커밋해 무수정.
- `tests/test_data_sanity.py`(신규, 39개).

**검증.**
- 에이전트 자체: 변이 테스트 6종(각 검사 무력화 시도) 전부 정확히 해당 검사가
  잡아냄 + 원복 diff 바이트 동일, 실제 최근 데이터로 스모크(정상일엔 조용,
  주입한 이상엔 정확한 사유 문구), 워크플로우 스텝 실추출 실행 4케이스, 자체
  재검토로 결함 2건 스스로 발견·수정(상태파일 손상 시 zip 밀림으로 엉뚱한
  파일에 남의 판정이 붙던 버그, 디스코드 2000자 초과 시 무음 실패).
- 제가 독립적으로 재확인: `git diff`로 수집기 3개가 정말 저장 이후 한 줄만
  추가했는지 직접 읽어 확인, `utils/data_sanity.py`의 `check_dataset()`이
  절대 예외를 던지지 않고 실패도 `error` 상태로 남기는 구조인지 코드로 직접
  확인, **에이전트가 안 한 시나리오로 별도 재현**(건수 90% 급감 + 상수 채움
  2건을 임시 디렉터리에서 처음부터 다시 실행) — 둘 다 정확히 `suspect`와
  올바른 한글 사유로 잡힘. `pytest --ignore=archive -q` 전체 재실행:
  `1809 passed` → `1849 passed, 55 skipped`(회귀 0, 신규 40개는 `test_data_sanity.py`
  39개 + `test_suite_integrity` Check C 인식 1개). YAML 문법 재확인.

**알아둘 한계(정직하게).** 판정이 데이터셋별 파일에 저장된 뒤 하루 한 번 도는
구조라 최대 하루 지연 가능, 이 워크플로우도 GitHub schedule 지연·누락 한계를
그대로 가짐(`watch_schedule_health.yml`과 동일 한계). 배포 직후 첫 실행엔
`data/*_sanity.json`이 아직 없어 "이상" 알림이 한 번 울릴 수 있음(오탐이
아니라 "감시가 살아있다"는 신호 — §0-1 원칙대로 0건을 조용히 통과시키지
않음). 이틀째부터 어제 대비 비교가 시작됨.

### #175 — 핵심 금융 계산 모듈 테스트 커버리지 보강 + 실제 계산 결함 4건 발견 (2026-08-30)

**배경.** #174에 이어, 오너 지시("알고 있는 요소는 지금 다 잡자")의 두 번째
갈래 — "테스트가 1800개 넘게 있어도 실제로 화면 숫자를 결정하는 함수 중
테스트가 아예 없는 곳이 있는지"를 커버리지 도구로 처음 실측했습니다.

**결과 — 커버리지(branch 기준).** `scoring.py` 62%→99%, `macro_scoring.py`
63%→99%, `guardrail.py` 68%→98%, `expiry_alarms.py` 43%→100%. 가장 심각했던
건 **점수·배지를 실제로 결정하는 분기 전체가 한 번도 실행된 적이 없었다**는
것 — PER 이상치 상한, 역성장 상한, 목표가 초과 상한, 극단 고평가 상한, 배지
5분기 전부, 그리고 매크로 종합 위험 지수를 만드는 4개 함수
(`compute_shock_amplifier`/`compute_historical_stats`/`compute_sub_scores`/
`compute_final_score`)가 **통째로 미실행**이었습니다. 신규 테스트 135건
(`tests/test_scoring_coverage.py`·`test_macro_scoring_coverage.py`·
`test_portfolio_money_coverage.py`) 추가, 기대값은 SPEC §5와 상수에서 손으로
계산해 작성(코드 출력을 그대로 베끼지 않음). 돌연변이 검증 4건(PEGY 밴드
경계값 변경·매크로 증폭기 무력화·guardrail 모순 감지 제거·원화 반올림으로
변경) 전부 실제로 테스트가 빨간불이 됨을 확인 후 원복(md5 일치). **프로덕션
코드는 한 줄도 수정하지 않음**(`git diff --stat` 빈 출력 — 테스트 전용
커밋). 전체 pytest: 1849 passed → 1987 passed, 61 skipped(회귀 0). 제가
독립적으로 재확인: `git status`/`git diff --stat`로 신규 3파일 외 변경
없음 확인, 전체 재실행으로 숫자 재현.

**🔴 부산물로 발견한 실제 계산 결함/문서 불일치 — 코드는 고치지 않고 보고만
합니다(값이 바뀌는 변경이라 오너 판단 필요, §0-1).**

- **[A] SPEC §5-1 "2중 Cap"이 코스피 경로에 미구현 (심각 — 화면에 노출되는
  실제 밸류에이션에 영향).** `ENGINEERING_SPEC.md` §5-1은 `g_eff = min(min(성장률,
  35%) + min(주주환원율, 10%), 40%)`를 명시하는데, `collector_kospi200.py:1613`의
  실제 코드는 `geff = growth + sh_yield`로 **세 캡 전부 없음**. 미국 경로
  (`utils/scoring_us.py:288`, `utils/constants_us.py`)는 이 캡을 정확히 구현하고
  있고, 그 코드 주석은 "코스피와 동일 값을 유지합니다(시장 무관 상수)"라고 적혀
  있어 — 즉 **문서와 미국 코드는 코스피도 이렇게 해야 한다고 말하는데 코스피만
  안 하고 있는** 상태입니다. **제가 직접 두 파일을 열어 코드 레벨로 확인**했습니다.
  에이전트 실측: 화면 노출 200종목 중 **17종목의 PEGY 밴드가 바뀝니다**(예:
  고영 growth 118.4% — 현재 "강력저평가" → 캡 적용 시 "적정"). 성장률이 큰
  종목일수록 실효성장률이 부풀려져 PEGY가 인위적으로 낮아지고, 저평가처럼
  보이는 배지가 붙습니다. **오너 결정 필요**: ① 코드를 §5-1대로 고칠지
  (실제 밸류에이션 배지가 다시 바뀌는 종목이 생김), ② 명세를 지금 코드에
  맞춰 고칠지(그럼 미국 쪽 "코스피와 동일" 주석·구현도 재검토 필요).
- **[B] `format_amount()`가 NaN/무한대에서 크래시 또는 `$nan` 출력 (중 —
  현재 실데이터 경로로는 재현 안 됨, 계약이 뚫린 잠재 결함).** 같은 파일의
  `_positive_number()`는 `math.isfinite()`로 이미 방어하는데 `format_amount()`만
  빠져 있음. **제가 직접 재현 확인**: `format_amount(float('nan'),'KRW')` →
  `ValueError`, `format_amount(float('inf'),'USD')` → `'$inf'`. `data/*.json`
  전수 스캔 결과 지금 비유한 float 0건이라 당장 터지는 버그는 아님.
- **[C] `ENGINEERING_SPEC.md` §5-4 표가 2026-08-06 개편 이후 갱신 안 됨(문서만).**
  PER 이상치·역성장·PER>200 임계값·고배당 DPS=0 처리 4행 중 3행이 실제 코드와
  다른 옛 규칙을 적고 있음(예: 문서는 "PER>200 → 10점 강제"라 적지만 실제
  임계값은 300이고 강제 점수도 없음).
- **[D] 역성장 종목은 배당 데이터 미수집 배지를 받지 못함(낮음, 현재 실데이터
  0건 — 조건이 안 겹쳐서 아직 안 보임).** `guardrail.py:162-165`가 `g_eff<=0`이면
  즉시 return해 그 아래 배당 판정 블록을 건너뜀.

**다음 우선순위(에이전트 제안, 미착수)**: `utils/data_validator.py`(50%,
PEGY 카드 차단 여부를 결정하는 3단계 검증 하네스 — 커버리지가 가장 낮으면서
영향력은 가장 큰 다음 대상으로 추천).

### #176 — SPEC §5-1 "2중 Cap" 코스피 실효성장률(g_eff) 계산에 반영 (2026-08-30)

**배경.** #175에서 발견한 [A] 결함(오너 확인 완료 — "일부러 뺀 기억은 없고,
미국 시장은 따로 점수를 배치하겠다고 결정했던 기억만 있다")을 오너가
"해결이 맞다"고 직접 지시해 바로 수정했습니다. `ENGINEERING_SPEC.md` §5-1은
`g_eff = min(min(성장률, 35%p) + min(주주환원율, 10%p), 40%p)`로 정의돼
있고, 이 캡은 미국 경로(`utils/scoring_us.py`)에는 프로젝트 최초 커밋부터
구현돼 있었으며 그 코드 주석에도 "코스피와 동일한 값을 유지한다(시장 무관
상수)"고 적혀 있었는데, 코스피 경로(`collector_kospi200.py`)에는 이 캡이
한 번도 구현된 적이 없었습니다.

**영향 범위 확정.** Forward 실효성장률(`growth_eff` → `f_pegy`·목표주가에
사용)에만 적용됩니다. Trailing 쪽(`geff` → `t_pegy`·`t_fair`)은 SPEC 설계상
원래부터 캡이 없는 게 맞아서(§5-1 원문이 Trailing은 원값 그대로 쓰도록
설계돼 있음) **의도적으로 그대로 두었습니다** — 이번 수정으로 Trailing
계산은 단 한 줄도 바뀌지 않았습니다.

**수정.**
- `utils/constants.py` — `GROWTH_CAP_PCT=35.0`·`SH_RETURN_CAP_PCT=10.0`·
  `GEFF_TOTAL_CAP_PCT=40.0` 신설(미국 쪽 `constants_us.py`의 동명 상수와
  값이 일치함을 새 테스트로 교차 확인).
- `collector_kospi200.py` — g_eff 계산부를 "Trailing용 `geff`(캡 없음, 기존
  그대로) / Forward용 `growth_eff`(성장률·주주환원율 각각 캡 후 합산까지
  한 번 더 캡)"로 분리. 출력 딕셔너리에 `g_eff_capped`(캡이 실제로 걸렸는지
  bool)·`g_eff_uncapped`(캡 적용 전 원값) 필드를 추가했습니다 — 이 두 필드는
  이미 `tests/test_stock_history.py`의 `FORBIDDEN_KEYS` 정책과 미국 페이지
  패턴이 코스피 쪽에도 존재할 것으로 전제하고 있던 필드라 이름을 새로
  짓지 않고 그대로 맞췄습니다.

**검증.**
1. **실데이터 재현.** `data/kospi200_pegy_latest.json`(236종목, growth·
   sh_return·vol_penalty·f_per 모두 있는 종목 기준)에 저장된 옛 `g_eff`
   값을 수정 전 공식(무캡)으로 그대로 재현해 **불일치 0건**을 확인한 뒤,
   새 공식(캡 적용)으로 다시 계산해 비교했습니다. 캡이 실제로 걸리는
   종목은 79개였지만, **PEGY 밴드(강력저평가/저평가/적정/고평가)가 실제로
   바뀌는 종목은 14개**였습니다(#175 최초 보고 때 에이전트가 추정한 17개는
   부정확한 수치였고, 이번에 제가 직접 재현한 정확한 수치입니다):

   | 종목코드 | 종목명 | 기존 f_pegy(밴드) | 수정 후 f_pegy(밴드) |
   |---|---|---|---|
   | 006400 | 삼성SDI | 0.04(강력저평가) | 2.19(고평가) |
   | 475150 | SK이터닉스 | 0.27(강력저평가) | 2.22(고평가) |
   | 377300 | 카카오페이 | 1.01(적정) | 1.53(고평가) |
   | 140860 | 파크시스템스 | 0.47(강력저평가) | 1.32(적정) |
   | 098460 | 고영 | 0.33(강력저평가) | 1.12(적정) |
   | 009240 | 한샘 | 0.40(강력저평가) | 1.12(적정) |
   | 122640 | 예스티 | 0.18(강력저평가) | 1.13(적정) |
   | 403870 | HPSP | 0.61(강력저평가) | 1.16(적정) |
   | 010060 | OCI홀딩스 | 0.11(강력저평가) | 1.07(적정) |
   | 353200 | 대덕전자 | 0.58(강력저평가) | 0.85(저평가) |
   | 035720 | 카카오 | 0.44(강력저평가) | 0.86(저평가) |
   | 181710 | NHN | 0.55(강력저평가) | 0.80(저평가) |
   | 009155 | 삼성전기우 | 0.62(강력저평가) | 0.93(저평가) |
   | 218410 | RFHIC | 0.49(강력저평가) | 0.82(저평가) |

   가장 극단적이었던 삼성SDI·SK이터닉스는 "강력저평가"에서 "고평가"로
   두 단계를 건너뛸 만큼 왜곡돼 있었습니다 — 실효성장률이 캡 없이 과대
   계산되면서 PEGY 분모가 부풀려져 실제보다 훨씬 싸 보였던 것입니다.
2. **경계값·단위 테스트.** `tests/test_geff_cap.py`(신규 7건) — 성장률만
   캡에 걸리는 경우/주주환원율만 걸리는 경우/개별 캡엔 안 걸리지만 합계
   40%p 캡에는 걸리는 경우/경계값(정확히 35.0·10.0·40.0)은 캡에 걸리지
   않아야 하는 경우를 각각 손으로 계산한 값과 대조, 미국·코스피 상수
   교차 일치 확인, 위 삼성SDI 실데이터 케이스 재현(스냅샷이 갱신돼 더는
   극단치가 아니게 되면 자동으로 skip). 전부 통과.
3. **회귀.** `pytest --ignore=archive -q` — 수정 전후 모두 **0 failed**
   (수정 전 1988 passed / 63 skipped, 신규 파일 추가 후 1995 passed /
   63 skipped — 신규 7건 전부 pass로 반영, 그 외 회귀 0건).
4. `python3 -m py_compile utils/constants.py collector_kospi200.py`로
   구문 확인, grep으로 `f_pegy`/목표주가 계산부만 `growth_eff`(캡 적용)를
   쓰고 `t_pegy`/`t_fair`는 여전히 `geff`(무캡)를 쓰는지 재확인했습니다.

**일부러 안 한 것 — UI 배지는 이번엔 보류.** 미국 페이지(`us_stocks_page.py`)는
화면에 g_eff 숫자를 직접 노출하면서 캡이 걸리면 "🧮 상한 적용값" 배지로
원값을 함께 보여줍니다. 코스피 페이지(`pegy_page.py`)는 애초에 g_eff를
숫자로 직접 노출하는 자리가 없어(목표가 하나만 보여주는 레이아웃), 이번
수정만으로는 화면 UI가 하나도 바뀌지 않습니다 — **계산값 자체는 이미
올바르게 고쳐졌고, 배지 유무와 무관하게 정확합니다.** 배지 추가는 순수
표시(투명성) 개선이라 이번 수정과 성격이 달라 백로그로 분리해 두었습니다
(오너가 필요하다고 판단하면 착수).

**교훈.** 이번 것도 #169~#175와 같은 뿌리 — "명세에는 있는데 한쪽 시장
경로에만 구현이 안 됨"이 사람의 기억이나 리뷰만으로는 몇 달 동안 안
걸릴 수 있다는 것을 다시 보여줬습니다. 미국 쪽 코드 주석이 정확히
"코스피와 동일해야 한다"고 적어뒀는데도 그랬습니다 — 앞으로 시장별
분리 상수(`constants.py` vs `constants_us.py`)를 새로 만들 때는, "이
상수가 시장 무관인데 한쪽에만 있는 건 아닌지"를 커밋 시점에 한 번
확인하는 습관이 필요해 보입니다(자동화 여부는 별도 판단 — 지금은 기록만).

### #177 — "오푸스 익스트림" 보강 3/4: 외부 사이트 스키마 드리프트 방어 점검 + NiceGUI 진입점 렌더 스모크 테스트 신설 (2026-08-30)

**배경.** #175/#176(핵심 계산 모듈 커버리지 + §5-1 캡 수정)에 이어, 오너의 "오푸스
익스트림으로 알고 있는 문제 요소는 지금 전부 잡자" 지시의 다음 항목 — "① 외부
사이트가 구조를 바꿔도(스키마 드리프트) 우리가 알아챌 수 있는가, ② 화면(NiceGUI)
자체가 렌더링 중 죽는 걸 배포 전에 잡을 수 있는가"를 점검했습니다. 두 질문의 답이
서로 달라서 아래처럼 나눠 처리했습니다.

**① 스키마 드리프트 — 새 코드를 만들지 않기로 결정(이미 3중 방어가 있음을 확인).**
직접 코드·과거 사고 이력을 조사한 결과, 이 저장소는 이미 세 겹의 방어가 있습니다.
  1. **라벨 텍스트 기반 파싱(SPEC §2-1, "위치 인덱스 iloc 전면 금지")** — 네이버·
     stockanalysis.com 표를 열 번호가 아니라 헤더/라벨 문자열로 찾습니다. 열 순서가
     바뀌어도 안 깨집니다(과거 #48 "장마감 종가 파서" 사고도 결국 이 원칙 강화로
     귀결됨).
  2. **라벨을 못 찾으면 값을 지어내지 않고 그 필드 키 자체를 생략**(collector_kospi200.py
     962줄 주석) — 화면은 "데이터 없음"으로만 보여주고 허위 값을 절대 안 만듭니다.
  3. **`utils/data_sanity.py`(#174, 이미 신설)** — 행 수 급감/급증, null 비율 급등,
     전 종목 값 동일, 중앙값 급변을 매 수집 직후 자동 판정해 Discord로 알림. 사이트가
     구조를 크게 바꿔 다수 종목이 한꺼번에 영향받는 경우(가장 위험한 시나리오)는 이
     장치가 이미 잡습니다.

  **남는 잔여 위험(낮음, 기록만 남김)**: 극소수 종목 하나만 라벨이 미묘하게 바뀌는
  경우는 ②번 원칙대로 안전하게(거짓말 없이) "데이터 없음"으로만 빠지고, 전체 통계를
  보는 ③번은 비율이 거의 안 움직여 못 잡을 수 있습니다. 다만 이건 안전 실패(사용자가
  틀린 숫자를 보는 게 아니라 그 항목만 못 보는 것)이지 §0-1 위반이 아니라서, 새 감시
  코드를 얹기보다 **기록만 남기고 넘어가는 게 맞다고 판단**했습니다(§0-3-10 — 이미
  있는 방어와 겹치는 코드를 또 만들지 않음, 오너가 전에 밝힌 "불필요한 자동화 부담"
  기준에도 부합).

**② UI 렌더링 — 진짜 사각지대 발견, 오푸스로 메움.** `web/pages/*.py`의 각 화면은
`@ui.page(...)`가 붙은 "진짜 진입점" 함수(예: `pegy_index_page()`, `admin_page()`)가
있는데, grep으로 확인한 결과 **12개 진입점 중 9개는 그 함수가 테스트에서 단 한 번도
직접 실행된 적이 없었고**(내부 헬퍼 함수만 따로 테스트됨), 나머지 3개(`scorecard_page`/
`report_page`/`duel_page`)도 진입점 자체가 아니라 안쪽 `_render_body()`만 테스트되고
있었습니다. 이런 함수 안의 오타·참조 오류는 로컬 테스트로 못 잡고 **배포 후 실사용자가
크래시를 봐야만** 발견됩니다 — 정확히 이 저장소가 과거에 겪은 사고(TASK_HISTORY_ARCHIVE
#128/#129: CSS f-string 중괄호 하나 빠뜨려 배포 직후 전체 사이트가 `UnboundLocalError`로
다운)와 같은 부류입니다.

오푸스에게 12개 진입점 전부에 대해 **기존 공용 렌더 헬퍼(`tests/_render_helpers.py::run_render()`)
를 재사용**해 "예외 없이 끝까지 실행되는가" 스모크 테스트를 만들도록 맡겼고, 제가
직접 재검증했습니다.

**신설 — 6개 테스트 파일에 총 15개 렌더 스모크 테스트, 프로덕션 코드 0줄 변경**:
`tests/test_web_session_isolation.py`(admin/privacy/scorecard_consent/scorecard_leaderboard
+ scorecard_page/report_page/duel_page 진짜 진입점, 7건), `tests/test_pegy_page.py`(1건),
`tests/test_us_stocks_page.py`(1건), `tests/test_indicator_page.py`(2건),
`tests/test_dividend_page_calendar.py`(2건), `tests/test_dividend_us_page.py`(2건).
데이터 페이지는 가짜 데이터를 만들지 않고 **실제 `data/*.json` 스냅샷을 그대로**
읽게 했습니다(§0-1 — 가짜 데이터로 얻은 초록불 방지).

**이 테스트들이 "빈 초록불"이 아님을 스스로 방어하는 장치 2가지(오푸스가 자체
설계, 제가 재검증).**
  - 로그인 필요 화면 5개는 진입점이 본문 전체를 `try/except → error_banner(...)`로
    감싸고 있어, 본문이 통째로 터져도 "예외 없음"만으로는 통과해버릴 수 있었습니다.
    그래서 `error_banner`의 폴백 문구("화면을 그리는 중 문제가 발생했습니다" 등)가
    뜨면 실패하도록 별도로 확인합니다.
  - 데이터 페이지 5개는 스냅샷이 없으면 §0-1 원칙대로 배너만 뜨고 조기 `return`되는데,
    이 상태로도 "예외 없음"은 통과합니다. 그래서 스냅샷이 실제로 있을 때는 "조기
    반환 배너가 뜨지 않고 본문 전체가 그려졌는지"까지 함께 확인합니다.

**검증 — 오푸스 자체 검증 + 제 독립 재검증(실제로 코드를 부순 뒤 원복).** 오푸스가
`scorecard_page._render_body`를 `NameError`로, `dividend_us_page.DATA_FILENAME`을
없는 파일로, `pegy_page._render_title`을 `NameError`로(=#128/#129 재현) 각각 바꿔
새 테스트가 정확히 잡는지 확인 후 원복했다고 보고했습니다. **이걸 그대로 믿지 않고**
제가 별도로 — 오푸스가 건드리지 않은 `admin_page()`와 `scorecard_leaderboard_page()`를
골라 똑같이 `NameError`를 주입해 재현했고(두 곳 다 정확히 해당 진입점을 지목하는
실패 확인), `diff`로 원복이 바이트 단위로 깨끗한지 확인했습니다.

**전체 스위트**: 신설 전 `1995 passed, 63 skipped` → 신설 후 `2010 passed, 63 skipped`
(+15, 회귀 0건). `git diff --numstat` — 삭제 0줄, 6개 테스트 파일만 767줄 순수 추가,
`web/`·`utils/`·`collector_*.py` 등 프로덕션 코드는 diff에 하나도 없음을 확인했습니다.

**직접 추가로 처리한 것 — 오푸스가 발견해 보고한 사소한 불일치.** `tests/test_us_stocks_page.py`는
`main()`이 아니라 손으로 함수를 나열하는 `test_us_stocks_page_full_suite()`가 직접
실행(`python3 tests/test_us_stocks_page.py`) 진입점인데, 새 렌더 스모크가 거기 등록이
안 돼 있어 pytest 경로로는 정상 수집·통과하지만 직접 실행 시에는 빠지는 사소한
불일치가 있었습니다. 오푸스가 "동작을 바꾸지 않는 순수 추가만" 원칙을 지키려 일부러
안 건드렸다고 정직하게 보고했고, 제가 한 줄(`test_us_stocks_index_page_render_smoke()`
호출) 추가로 직접 마무리해 직접 실행 경로도 일치시켰습니다.

**한계(정직하게 기록).** `scorecard_leaderboard_page()`는 "발행된 순위표가 **있는**"
경로까지는 검증하지 않습니다 — 발행표 행의 모양을 추측해 가짜로 만들면 그 자체가
§0-1 위반이라 하지 않았습니다. 진입점 몸통·공개 게이트·로그인 게이트·통화/체급
선택까지는 전부 실행됩니다. 발행 순위표가 실제로 있는 경우까지 검증하려면 나중에
실제 발행 배치를 한 번 돌린 뒤 그 결과로 테스트를 보강하는 것을 검토할 수 있습니다
(급하지 않음, 백로그로 남김).

### #178 — 이전 "스파게티 감사" 모듈 목록 완료 상태 동기화 + 잔여 문서/커버리지 정리 (2026-08-30)

**배경.** 오너의 "이어서 진행해줘" 지시로, 이전에 남아있던 별도 작업 목록
(스코어카드·배당·미국주식·공유인프라·테스트 스위트 모듈별 개별 감사 등, 세션
작업 목록 #19·#26~37)을 이어가려 했습니다. 확인해보니 **이 항목들은 전부 이미
완료된 작업이었습니다** — `SPAGHETTI_AUDIT_2026-08-29.md`(2026-08-29 레포 전체
감사)가 지정한 8개 모듈 전부가 그 이후 순차적으로 감사·수정·커밋됐고
(TASK_HISTORY #153·#157~168), EV/EBITDA 서킷브레이커(#19)도 2026-08-27에 이미
반영·실전 검증까지 끝나 있었습니다. 다만 세션 작업 목록(Cowork Task 위젯) 쪽은
그 완료 상태가 반영되지 않은 채 "진행 중/대기"로 남아 있었고, `TASK_HISTORY.md`
백로그에도 #160에서 이미 처리된 "#156 컷오버 유예 만료" 항목이 미완료인 것처럼
그대로 남아 있었습니다 — 실제 작업 누락이 아니라 **기록 동기화 누락**이었습니다.

**한 일.**
1. **작업 목록 동기화** — #19·#26~31·#33~37을 실제 완료 근거(각각의 TASK_HISTORY
   번호)와 함께 완료로 표시.
2. **`TASK_HISTORY.md` 백로그 정리** — "#156 컷오버 유예 만료"(이미 #160에서
   완전히 실행됨을 `ls app.py visiblehand.py views/`로 재확인 — 셋 다 없음,
   `archive/`에 있음)를 ✅ 완료로 갱신.
3. **`ENGINEERING_SPEC.md` §5-4 Guardrail 표 갱신** — #175에서 지적된 대로, 2026-08-06
   개편(하드컷오프를 고정 점수에서 "오늘 종목 전체 분포 대비 z-score 윈저라이즈"로
   전환) 이후 이 표가 갱신되지 않은 채 방치돼 있었습니다. `utils/guardrail.py`·
   `utils/scoring.py`를 직접 재확인해 "①종목 전체 차단/②배지만(차단 안 함)/
   ③퀀트 점수만 z-score로 캡" 3단으로 다시 정리했습니다. **코드 변경 없음, 문서만.**
4. **`utils/data_validator.py` 커버리지 50% → 100% 보강** — #175가 지목한 "다음
   커버리지 보강 1순위" 항목. 이 파일은 PEGY 카드가 화면에 나갈지 최종 승인하는
   3단계 검증 하네스인데, ②단계(`sanity_check_per`)·③단계(`cross_reconcile`)는
   **지금까지 단 한 번도 직접 테스트된 적이 없었습니다**(기존 유일한 관련 테스트
   `tests/test_quant.py::test_case8_...`는 ①단계 한 갈래만 `run_pipeline`을 통해
   간접적으로 지나감). `tests/test_data_validator.py` 신규 29건 — 세 단계 각각의
   통과/차단/경계값 분기와, `run_pipeline`이 2단계·3단계에서 조기 종료되는 경로까지
   전부 커버.

**검증.**
- `coverage run --branch -m pytest`로 측정: `utils/data_validator.py` 50%(113
  stmt/40 branch 중 53개 statement·8개 branch 미검증) → **100%**(0 miss).
- **변이(mutation) 검증 — 직접 코드를 부순 뒤 새 테스트가 잡는지 확인 후 원복.**
  `sanity_check_per`의 `<=` 비교를 `>=`로 반전시키자 관련 테스트 7건이 정확히
  실패(원복 후 `diff`로 바이트 단위 동일 확인). `cross_reconcile`의 "2차 출처
  없음 → 통과(True)" 반환을 의도적으로 실패(False)로 바꾸자 관련 테스트 3건이
  정확히 실패(원복 후 동일 확인). 처음 시도한 완화형 변이(허용 오차 3배 확대)는
  기존 테스트 데이터의 오차폭이 이미 그보다 커서 안 잡혔던 것도 함께 확인·기록
  — "약한 변이가 안 잡힌 것"과 "테스트가 허술한 것"을 구분하기 위해 더 결정적인
  변이로 재시도한 결과입니다.
- 전체 스위트: `2010 passed` → **`2040 passed`**(+30 = 새 테스트 29건 +
  `test_suite_integrity.py` Check C 1건 자동 추가), `65 skipped`(+2 = 같은
  신규 파일에 대한 Check A/B — 이 파일은 `check()`/`FAILURES` 하네스도, 직접
  실행 `main()`도 안 쓰는 순수 assert 스타일이라 두 체크 모두 정상적으로 skip),
  **회귀 0건**.
- 부수적으로 만든 `.coverage`(coverage.py 측정 산출물) 파일을 `.gitignore`에
  추가 — 커밋 대상 아님.

**의도적으로 더 하지 않은 것.** 백로그에 남아있는 나머지 항목들(`tests/conftest.py`
통합 리팩터 — 29개 파일 전체에 손대는 별도 계획 필요, `format_amount()` NaN 가드 —
현재 실데이터로 재현 안 됨, 브리틀한 `.count()` 단언 스타일 정리 — 스타일 문제라
우선순위 낮음, `scorecard_leaderboard_page()` 발행분-있음 경로 — 가짜 데이터 필요해
보류)는 각자 이미 백로그에 사유와 함께 남아 있어 이번엔 손대지 않았습니다. 애드센스
슬롯ID·심사 대기, 워치독(#154) 이슈 생성 경로 수동 확인, 회원탈퇴 기능 여부는
전부 **오너 쪽 조치나 결정이 필요한 항목**이라 코드로 처리할 수 있는 범위 밖입니다.

### #179 — 잔여 백로그 2건 직접 처리: `format_amount()` NaN 방어 + `pegy_page.py` g_eff 캡 배지 (2026-08-30)

**배경.** 오너의 "전부 다 오푸스 엑스트라로 검토하면서 신중하게 진행" 지시로,
#175/#176/#178에 낮은 우선순위로 남아있던 두 항목을 처리했습니다.

**① `format_amount()` NaN/Infinity 방어.** #175는 "현재 실데이터로는 재현 안 됨"
이라 낮은 우선순위였는데, 직접 재현해보니 **원화(KRW) 경로는 실제로 크래시**했습니다
— `math.floor(float('nan'))`이 `ValueError: cannot convert float NaN to integer`를
던집니다(달러 경로는 크래시는 안 나지만 화면에 "$nan"이 그대로 노출됨). 계산 계층의
`_positive_number()`가 이미 쓰고 있던 `math.isfinite()` 가드를 표시 계층에도 추가해
값이 없을 때와 동일하게 "—"로 처리했습니다. `tests/test_scorecard.py`에 NaN·
Infinity·-Infinity 3종 회귀 추가 — 가드를 되돌려 정확히 같은 `ValueError`가 재현되고
새 테스트가 잡는지 확인한 뒤 바이트 단위로 원복했습니다.

**② `pegy_page.py` g_eff 캡 투명성 배지.** #176에서 코스피 g_eff에 이중 캡을
반영했지만, 코스피 화면엔 g_eff 숫자를 직접 보여주는 자리가 없어 미국 페이지의
"🧮 상한 적용값" 배지와 달리 캡이 걸렸다는 사실 자체가 화면에 안 보였습니다.
"예상 성장률" 표시 옆에 동일한 배지를 추가하고, `g_eff_capped`/`g_eff_uncapped`
필드가 없는 옛 스냅샷(아직 수집기 재실행 전)에서도 예외 없이 조용히 생략되는지
확인했습니다. `tests/test_pegy_page.py`에 신규 테스트 1건 — 배지 라벨("🧮 상한
적용값")이 목표가 캡 안내 툴팁의 설명 문장 안에도 항상 등장해 라벨만으로는
판정이 안 된다는 걸 실행 중 직접 발견해, g_eff 배지 툴팁에만 있는 고유 문구로
판정 기준을 다시 잡았습니다(사소하지만 브리틀 테스트를 실제로 만들 뻔한 경험).
프로덕션 코드를 되돌려 새 테스트가 정확히 잡는지 확인 후 원복.

**검증.** 전체 스위트 `2040 passed` → `2041 passed`(+1), 회귀 0건.

### #180 — `tests/conftest.py` 신설: FAILURES/check() 하네스 공용화 + Check A 동시 갱신 (2026-08-30)

**배경.** 백로그에 "#156 `tests/conftest.py` 부재"로 오래 남아있던 항목입니다.
29개 테스트 파일이 각자 `sys.path` 부트스트랩을 복제하고, 그중 10개는 추가로
"check() 실패를 pytest 실패로 승격시키는" FAILURES/check()/autouse 픽스처
하네스까지 손으로 복사해 두고 있었습니다. 이 복제 방식 자체가 이미 한 번
실제 사고를 냈습니다(#168 H-1 — `test_us_stocks_page.py` 하나가 그 복사에서
빠져 있던 게 뒤늦게 발견). 29개 파일 전체에 손을 대는 범위라 여러 재감사
라운드에서 "별도 계획 필요"로 계속 유예돼 있었는데, 오너의 "전부 다 오푸스
엑스트라로 신중하게" 지시로 이번에 처리했습니다.

**⚠️ 이 리팩터의 핵심 위험 — 미리 알고 있던 함정.** 백로그 자체에 이미 경고가
적혀 있었습니다: "`tests/test_suite_integrity.py`의 Check A는 하네스가 각
파일 최상위에 있다는 전제로 짜여 있다. FAILURES/check를 공용 모듈로 옮기면
Check A가 그 공용 모듈을 보지 못해 **조용히 무력화된다**." 이번 작업은 이
경고를 정확히 실현시키지 않기 위해 하네스 이동과 Check A 갱신을 **하나의
변경**으로 묶어 처리했습니다.

**한 일.**
- `tests/conftest.py` 신설(89줄) — `sys.path` 부트스트랩, 공유 `FAILURES = []`,
  `check(condition, label, detail="")`, `@pytest.fixture(autouse=True)`
  `_assert_no_check_failures()`를 한 곳에서만 정의.
- 9개 파일(`test_data_source`·`test_macro_scoring`·`test_pegy_page`·
  `test_report`·`test_scorecard`·`test_stock_history`·`test_us_stocks`·
  `test_us_stocks_page`·`test_web_session_isolation`)에서 중복 제거,
  `from conftest import FAILURES, check`로 교체.
- **`test_us_scoring.py`는 의도적으로 제외**했습니다 — 이 파일의 유일한
  테스트 함수가 첫 줄에서 `FAILURES.clear()`를 부릅니다. 공용 픽스처는
  "테스트 시작 시점 길이 대비 증가분만" 검사하는 설계라, 도중에 `clear()`로
  목록이 비면 그 앞에 기록된 실패가 슬라이싱에서 빠져 조용히 사라집니다 —
  정확히 이 리팩터가 막으려는 결함을 새로 만드는 꼴이라 자기 파일 안
  하네스를 그대로 남겨뒀습니다.
- `tests/test_suite_integrity.py`의 Check A(`_uses_check_failures_harness`
  계열)를 갱신 — 파일 자신의 AST에 FAILURES/check 정의가 없어도, conftest에서
  가져다 쓰는 파일이면 **실제로 `import conftest`해서 그 안에 FAILURES·
  check·autouse 픽스처 3종이 진짜 있는지, 그리고 그 픽스처 이름이 지금 이
  테스트의 활성 픽스처 목록(`request.fixturenames`)에 실제로 들어 있는지**까지
  3중으로 확인하도록 강화(이름 하드코딩 없이 동작 확인).

**검증 — 오푸스 자체 검증.**
- `git stash -u` 베이스라인 대비 FAILED/ERROR/**SKIPPED** ID 집합 전부 동일
  (통과 개수 비교로 대체하지 않음 — 이 리팩터의 회귀는 실패가 아니라 스킵으로
  나타날 수 있어서), 판정 결과 줄 2,106개 완전 일치.
- Check A 무력화를 하네스만 옮기고 갱신 전 상태로 먼저 재현 — 감시 대상이
  10개 → 1개로 조용히 줄어드는 것을 실측으로 확인(위험이 실재함을 먼저 증명).
- 갱신 후 사보타주 5종(autouse 픽스처 삭제·`autouse=False`·**정의는 멀쩡한데
  이름만 `None`으로 덮어써 실제 등록만 무력화**·`check()` 정의 제거·구버전
  Check A로 되돌리기) 전부 정확히 잡힘, 매번 원복 후 diff로 확인.

**검증 — 제 독립 재검증(오푸스가 안 건드린 방식으로 재현).**
- `tests/test_scorecard.py`에 직접 `check(False, "__DELIBERATE_MUTATION_TEST__")`를
  주입 → 정확히 그 실패로 에러, 원복 후 바이트 단위 동일 확인.
- `tests/conftest.py`의 autouse 픽스처 정의 직후에 `_assert_no_check_failures = None`
  한 줄만 추가(오푸스의 E3과 유사하지만 독립적으로 직접 재현) → conftest 경유
  9개 파일 전부 정확히 실패, `test_us_scoring.py`만 영향 없음(설계대로) 확인,
  원복 후 바이트 단위 동일 확인.
- `python tests/test_scorecard.py`·`python tests/test_report.py` 직접 실행
  둘 다 exit 0, 정상 출력 확인.
- 전체 스위트 재실행: `2041 passed, 65 skipped`, 회귀 0건(순수 리팩터라
  테스트 개수 자체는 불변).

**부수 발견 — 알아둘 사소한 동작 변화(무해).** `test_us_stocks_page.py`의
`test_us_stocks_page_full_suite()`는 끝에서 `FAILURES`가 남아있으면
`SystemExit(1)`을 던지는데, `FAILURES`가 이제 디렉터리 공유라 **이미
빨간불인 스위트**에서는 다른 파일이 남긴 실패 때문에 이 테스트도 함께
실패로 보일 수 있습니다. 초록불 상태에서는 절대 발생하지 않고(이번 검증
전체가 그 상태), 방향이 과다 보고일 뿐 무음 통과가 되는 것은 아니라
문제로 보지 않았습니다.

### #181 — `scorecard_leaderboard_page()` 진입점에 "발행분 있음" 렌더 스모크 분기 추가 (2026-08-30)

**배경.** #177에서 12개 페이지 진입점 렌더 스모크를 신설할 때 `/scorecard/leaderboard`는
의도적으로 3분기(플래그 꺼짐·비로그인·발행분 없음)만 다루고 "발행분 있음"은 "발행표 행
모양을 지어내야 해서 §0-1 위반"이라는 이유로 빠져 있었습니다. 다시 살펴보니 같은 파일 안
`tests/test_scorecard_public_ui.py::_leaderboard_client()`가 **이미 정확히 이 패턴**
(발행일 1개 + 순위 행 3개, 닉네임도 "닉네임1/2/3"처럼 명백한 합성 픽스처)으로
`_render_body()`를 직접 검증하고 있었습니다 — §0-1이 막는 것은 "실제처럼 지어낸 값"이지
"테스트임이 명백한 픽스처 재사용"이 아니므로, 기존 관례를 그대로 가져다 쓰면 §0-1 위반
없이 이 분기를 채울 수 있었습니다.

**한 일.** `tests/test_web_session_isolation.py`의
`test_scorecard_leaderboard_page_entrypoint_render_smoke()`에 ④ "정상 로그인 · 발행분
있음" 분기 추가. `page.fetch_public_leaderboard_latest_date`·`page.fetch_public_leaderboard`·
`page.fetch_public_holdings_for_nickname`·`page._render_participant` 4개를 몽키패치
(실제 시그니처·컬럼명은 `utils/scorecard_publish_db.py`의 `PUBLIC_LEADERBOARD_COLUMNS`/
`fetch_public_leaderboard()` 정의를 그대로 따름). 진입점이 새로 검증하는 것은 딱 하나 —
로그인 게이트 → `_render_body` → 위/아래 두 구간 배선이 "발행분 있음" 상태에서 예외 없이
끝까지 도는가. 화면 내용의 세부 정확성(금액 서식·이스케이프)은 기존 [4]/[9-b] 테스트가
이미 담당.

**검증 — 오푸스 자체.** 뮤테이션 4종(섹션 조회 예외 유발·몽키패치 누락·프로덕션
`order_desc` 반전·프로덕션 펼치기 전 프리로드 주입) 전부 정확히 잡힘, 매번 원복.
전체 스위트 회귀 0건.

**검증 — 제 독립 재검증.** 오푸스와 다른 방식으로 프로덕션 코드의 아래쪽 구간 렌더 호출
자체를 통째로 `pass`로 날려 사보타주 → 새로 추가한 "위/아래 두 구간을 각각 한 번씩
읽음"·"발행 행 3개를 실제로 그림" 두 검사가 정확히 잡음 확인, `git diff --stat`로
프로덕션 파일이 바이트 단위로 원복됐음을 확인. 전체 스위트 재실행 `2064 passed`.

⚠️ **작업 중 발견한 특이사항.** 이 항목을 처리한 오푸스 서브에이전트와, 아래 #182를 처리한
서브에이전트가 같은 device 파일시스템에서 동시에 작업했습니다. #182 담당 에이전트가
작업 도중 `tests/test_web_session_isolation.py`가 (자신이 건드리지 않았는데도) 바뀐 것을
정확히 감지하고 "제가 한 변경이 아닙니다"라고 정직하게 보고했는데, 실제로는 #181 담당
에이전트가 같은 시간대에 그 파일을 수정하고 있던 것이었습니다 — 두 변경 모두 서로 다른
파일(`tests/test_web_session_isolation.py` vs 신규 `tests/test_watch_schedule_health_window.py`)
이라 충돌 없이 공존했고, 제가 최종적으로 두 diff를 모두 직접 확인·재검증했습니다.

---

### #182 — `watch_schedule_health.yml` 예약 실행 판정 로직에 신규 회귀 테스트 21건 추가 (2026-08-30)

**배경.** `#154` 백로그 항목 — 워치독(`watch_schedule_health.yml`)의 핵심 판정 로직
("최근 window 안에 conclusion=success인 schedule 실행이 있는가")이 YAML 안에 인라인
`python3 -c '...'`로만 존재해 단위 테스트가 전혀 없었습니다. 이슈 생성·디스코드 알림
단계는 실제 GitHub 부수효과(오너에게 실제 이메일 알림)가 있어 로컬에서 안전하게 검증할
방법이 없어 **이번에도 손대지 않았습니다** — 여전히 오너가 수동으로 `workflow_dispatch`
한 번 돌려봐야 하는 부분으로 남습니다.

**어떻게 했는가 — 워크플로우 파일은 한 글자도 안 건드림.** 이 로직을 별도 `scripts/`
모듈로 빼는 방법도 검토했지만, 이 저장소는 CI 스크립트를 인라인으로 두는 게 기존 관례이고
(`watch_data_sanity.yml` 등도 동일), YAML을 고치면 실제 GitHub Actions에서 돌려보기
전까지 셸 따옴표·heredoc 처리가 맞는지 로컬에서 100% 확신할 수 없어 — 잘못 고치면 "조용히
안 도는 워치독"이라는, 이 워치독이 막으려는 바로 그 사고를 낼 위험이 있었습니다. 대신
`tests/test_watch_schedule_health_window.py`(21개 테스트)가 워크플로우 YAML **텍스트를
그대로 읽어** 판정 스크립트의 실제 소스를 두 마커 사이에서 추출하고, 워크플로우가 부르는
것과 동일한 방식(`python3 -c <추출한 소스> <now_ts> <window_hours>`, JSON은 stdin)으로
직접 실행해 stdout("yes"/"no")만 검증합니다 — **사본을 만들지 않으므로**(§0-3-10) 나중에
워크플로우 쪽만 고쳐져도 조용히 어긋날 위험이 없고, 마커를 못 찾으면 "검사할 게 없네"로
조용히 넘어가지 않고 명시적으로 실패합니다(§0-1).

커버한 경계: window 안/밖 성공, 성공이 아닌 결론(failure/cancelled/timed_out/skipped/
startup_failure), 진행 중(`conclusion: null`), 실행 0건, `workflow_runs` 키 자체 없음,
혼합 목록에서 조건 만족 1건, 정확한 경계 시각(`<=`, 등호 포함) 안/밖 1초 차이, 월요일
76시간 창이 지난 금요일 실행까지 닿는지, 출력이 정확히 "yes"/"no" 문자열인지. PyYAML이
있으면 추출한 소스가 실제 YAML 파서가 만드는 셸 스크립트의 부분문자열인지까지 교차 확인
(없으면 그 검사만 skip).

**검증 — 오푸스 자체.** 뮤테이션 3종을 워크플로우 YAML **원본에** 직접 적용 —
`<=`→`<`(경계 케이스 1건만 정확히 실패), `"success"`→`"succeeded"`(yes 기대 7건 실패),
시작 마커 문구 변경(21건 중 20건이 `_MarkerNotFound`로 명시적 실패, 조용한 통과 없음).
매번 sha256 대조로 원복 확인.

**검증 — 제 독립 재검증(다른 뮤테이션).** `print("yes" if found else "no")`를
`print("yes")`(무조건 yes)로 사보타주 → 13개 테스트 정확히 실패. 원복 후
`sha256sum`이 원본과 완전히 동일(`c6ad2e38…2e43`), `git diff --exit-code`도 0(무변경)
확인. 전체 스위트 재실행 `2064 passed, 66 skipped`, 회귀 0건.

**남은 한계(문서화됨, 코드로 못 채움).** `gh issue create`(이슈 생성 + assignee 지정)와
디스코드 웹훅 전송은 이번에도 검증 범위 밖입니다 — 실제 부수효과 없이는 로컬에서 확인할
방법이 없어, 여전히 오너가 Actions 탭에서 직접 `workflow_dispatch`로 한 번 실행해봐야
확인되는 부분입니다.


### #183 — [실전 버그] `watch_schedule_health.yml` 이슈 생성 경로 실전 확인 중 진짜 결함 발견·수정 (2026-08-30)

**어떻게 발견했는가.** #182에서 판정 로직(핵심 window 검사)을 테스트 21건으로 검증한 뒤,
오너가 직접 GitHub Actions에서 `workflow_dispatch`로 이 워치독을 실행해 이슈 생성 경로까지
실전 확인해보기로 했습니다. 존재하지 않는 워크플로우 파일명(`__watchdog_issue_path_test__.yml`)을
TARGETS에 임시로 추가한 테스트 브랜치(`test/watchdog-issue-check`)를 만들어 실행했는데,
**이슈가 생성되지 않고 잡 자체가 파이썬 예외로 죽었습니다**:
```
json.decoder.JSONDecodeError: Extra data: line 1 column 146 (char 145)
```
8개 정상 대상은 전부 ✅로 확인된 뒤, 9번째(존재하지 않는 파일명) 차례에서 죽었습니다.

**근본 원인.** 판정 로직 앞의 셸 코드가 이렇게 한 줄이었습니다:
```bash
RESP=$(gh api ".../${FILE}/runs?event=schedule&per_page=5" 2>/dev/null || echo '{"workflow_runs":[]}')
```
`gh api`가 실패하면서 에러 응답 몸통을 **stderr가 아니라 stdout에** 이미 찍어 놓은
경우(이번처럼 워크플로우 파일 자체가 없어 404가 난 경우 관측됨), `2>/dev/null`은 stdout은
전혀 못 막습니다. 그 뒤 `||`의 `echo` 출력까지 **그대로 이어 붙어서** RESP가 JSON 두
덩어리가 나란히 붙은 문자열이 됐고, 그걸 `json.load(sys.stdin)`이 파싱하다 "Extra data"로
죽었습니다. 예외가 파이썬 스크립트 안에서 잡히지 않으니 `run:` 스텝 전체가 비정상 종료,
`has_failures` 출력 자체가 만들어지지 못해 **이슈 생성 단계로 아예 못 넘어갔습니다** —
워치독이 "놓친 걸 놓치는" 정확히 그 실패 모양이었습니다.

로컬에서 정확히 같은 실패를 그대로 재현해 원인을 확정했습니다(가짜 `gh api` 함수가 stdout에
에러 JSON을 찍고 실패 종료하도록 만들어 `RESP=$(... || echo ...)` 한 줄로 돌려보니 실제로
두 JSON이 이어 붙었고, `json.loads()`에 그 문자열을 그대로 먹여보니 원본과 같은
`JSONDecodeError: Extra data`가 재현됨).

**고친 것 — 2중 안전장치.**
1. 셸 쪽: `RESP=$(cmd1 || cmd2)` 한 줄을 `if ! RESP=$(cmd1); then RESP=cmd2; fi`로 나눠,
   실패 시 RESP를 **통째로 덮어써서** 이어붙기 자체가 물리적으로 불가능하게 함.
2. 파이썬 쪽: `json.load(sys.stdin)`을 `try/except json.JSONDecodeError`로 감싸고,
   최상위가 dict가 아닌 경우(배열·문자열 등)도 `{}`로 처리 — "파싱 실패 = 확인 못 함 = no"
   로 안전한 쪽(이슈를 생성하는 쪽)으로 떨어지게 함. 셸 쪽 수정만으로 이번 사례는 막히지만,
   앞으로 다른 경로로 RESP가 오염될 가능성까지 대비한 벨트-앤-서스펜더입니다.

**검증.**
- 실제 실패를 그대로 재현하는 입력(에러 JSON + 폴백 JSON이 이어 붙은 문자열)을 수정 전/후
  스크립트에 각각 먹여봄 — 수정 전: `JSONDecodeError: Extra data`로 그대로 재현.
  수정 후: 예외 없이 `"no"` 출력.
- bash 조각만 따로 떼어 `if ! RESP=$(...); then RESP=...; fi` 패턴이 `set -euo pipefail`
  아래에서도 안전한지(조건문 안의 명령 실패는 `set -e`를 안 건드림) 직접 실행해 확인 —
  가짜 실패 함수가 stdout에 뭘 찍어놔도 RESP가 폴백 값으로 완전히 덮어써짐을 확인.
- `tests/test_watch_schedule_health_window.py`에 신규 회귀 테스트 4건 추가(이어붙은
  JSON·완전히 무효한 문자열·빈 stdin·유효하지만 dict가 아닌 JSON) — 전부 이번에 고친
  코드에서는 통과, **고치기 전 코드로 되돌려서 돌려보면 정확히 4건 다 실패**함을 직접
  확인해 테스트가 실제로 이 결함을 잡아낸다는 것을 검증한 뒤 다시 원복.
- `python3 -m pytest tests/test_watch_schedule_health_window.py` → 25 passed(기존 21 +
  신규 4). `python3 -m pytest --ignore=archive -q` 전체 스위트 → 2068 passed, 66 skipped,
  회귀 0건.
- 수정한 YAML을 PyYAML로 다시 파싱해 두 스텝의 셸 스크립트를 뽑아 각각 `bash -n`으로
  문법 검사 통과 확인(간접 수정이라 YAML 들여쓰기가 깨지지 않았는지 별도 확인).

**의미.** #182에서 만든 21건짜리 테스트는 판정 로직(성공 실행이 window 안에 있는가) 자체는
정확히 검증했지만, 그 앞단의 `gh api` 호출·실패 처리 셸 코드는 테스트 범위 밖이었습니다 —
바로 그 사각지대에서 실제 버그가 나왔고, 오너가 직접 실전 확인을 요청하지 않았다면 발견하지
못했을 결함입니다. "테스트가 통과한다"와 "실전에서 안전하다"가 다르다는 걸 보여준 사례라
기록해 둡니다.

**여전히 남은 것.** 이슈 생성(`gh issue create` + assignee)·디스코드 알림 자체는 이번에도
실행되지 못했습니다(예외로 그 앞에서 멈춰서). 이 수정을 테스트 브랜치에도 반영한 뒤,
존재하지 않는 파일명 대신 **저장소에 실제로 있지만 schedule로는 안 도는 워크플로우
파일명**(예: `test_suite.yml`)으로 바꿔서 다시 실행하면, 이번엔 `gh api` 자체는 200으로
성공하고 그냥 `workflow_runs: []`가 돌아와 정상적으로 "누락" 판정 → 이슈 생성 단계까지
갈 것으로 예상됩니다. 이 재확인은 오너가 다시 `workflow_dispatch`를 눌러야 하는 부분입니다.


### #184 — `watch_schedule_health.yml`에 자동 재실행(self-healing) 기능 추가 — 예약 실행이 안 도는 채로 며칠씩 방치되는 상황 방지 (2026-08-31)

**배경.** #183까지로 워치독은 "예약 실행이 안 돌았다는 걸 알아채고 알린다"까지는
검증됐습니다. 그런데 2026-08-31(월요일), `scrape.yml`(평일 07:05 UTC)과
`indicator_kr.yml`(평일 08:00 UTC) 둘 다 5시간 넘게 지나도록 자동으로 안 돈 사례가
실제로 또 발생했고(2026-08-27·28에도 비슷한 지연이 있었음), 오너가 이렇게 정리했습니다:
"내가 외출 중이라 컴퓨터를 못 만지는 상황에서 이런 일이 생기면 2박 3일이나 일주일씩
데이터가 밀리는 큰일이 될 수 있다." GitHub Actions 스케줄러 자체의 지연·누락은
저장소 쪽에서 원인을 고칠 수 있는 부분이 아니므로(§0-1, 백로그에도 이미 기록됨),
"알림만 보내고 오너가 직접 컴퓨터로 수동 재실행해야 하는" 현재 방식 대신, **워치독이
누락을 발견하면 그 자리에서 스스로 한 번 재실행(`workflow_dispatch`)까지 걸어주는**
자가 치유(self-healing) 방식으로 확장하기로 했습니다.

**오너가 명시적으로 그은 범위.** "2번(자동 재실행)을 진짜 신중하게 검토하면서
해보자 — 근데 또 이 감시하는 역할을 만들어야 하는데, 감시의 감시의 감시의... 이런
식으로 하면 끝이 없으니까, 진짜 외부 사이트 구조 변경이면 그건 천재지변인거니까"라는
지시대로, 이번 작업은 딱 두 가지로 스스로 범위를 제한했습니다.
1. 재실행을 **1회만** 트리거하고 끝냅니다. "재실행이 성공했는지 다시 감시하는" 별도
   레이어(감시의 감시)는 만들지 않습니다 — 성공 여부는 다음 날 이 워치독이 같은
   방식으로 다시 확인하게 되므로 자연히 커버됩니다.
2. 실제 수집 대상 사이트의 구조가 바뀌어서 코드 자체가 틀려진 "진짜 버그"는 이
   워치독의 책임 범위가 아닙니다 — 그건 이미 있는 `utils/data_sanity.py`
   (`DataValidator`)·화면 에러 배너가 담당하는 영역이고, 이 워치독은 "예약이
   안 돌았다"만 감지·치유합니다. 재실행이 실패해도(예: `dispatches` API 자체가
   실패) 이슈 본문에 "자동 재실행도 실패 — 수동 확인 필요"라고만 남기고, 그 이상
   따라 들어가 원인을 판정하려 하지 않습니다.

**무엇을 바꿨는가.**
1. `permissions:` 블록에 `actions: write` 추가 — `POST .../dispatches` 호출에 필요.
2. **`event=schedule` 쿼리 필터를 완전히 제거**(`runs?event=schedule&per_page=5` →
   `runs?per_page=5`). 이유는 두 가지입니다.
   - 자동 재실행이 성공하면 그 실행 기록은 `event: workflow_dispatch`로 남는데,
     `event=schedule` 필터가 남아있으면 워치독이 그 성공을 영영 못 보고 **매일
     똑같은 대상을 다시 재실행하는 무한 루프**가 됩니다.
   - 조사 중에 `duel_daily.yml`이 2026-08-26부터 실제 주 트리거를 `workflow_run`
     (`scrape.yml` 완료 시 발동, cron은 안전망으로 격하)으로 쓰고 있다는 걸
     발견했는데, 옛 `event=schedule` 필터는 이 경우도 못 보고 있었습니다 — 이번
     필터 제거로 이 기존 오탐 소지도 같이 없어집니다. 9개 대상 전부 push/PR
     트리거는 없어서, 필터를 빼도 다른 이벤트가 끼어들어 오탐을 만들 여지는 없음을
     확인했습니다.
3. 판정이 "누락"(`LATEST_OK != yes`)으로 나온 대상마다, 기존 이슈 생성·디스코드
   알림 앞에 자동 재실행 단계를 추가: `gh api -X POST .../dispatches -f ref=main`을
   시도하고, 성공/실패에 따라 이슈 본문의 해당 항목 문구를 "자동 재실행 트리거함" /
   "자동 재실행도 실패 — 수동 확인 필요"로 구분해 남깁니다.
4. 이슈 본문·헤더 주석을 갱신 — 이 워치독이 이제 "0단계: 자동 재실행" →
   "1단계: 그래도 안 되면 이슈+디스코드 알림"의 2단 구조라는 것, 재실행 성공 여부를
   별도로 재검증하는 레이어는 의도적으로 안 만들었다는 것, 진짜 사이트 구조 변경으로
   인한 실패는 이 워치독이 아니라 `data_sanity.py` 쪽 책임이라는 것을 명시.

**구현 및 검증 — 오푸스 익스트림으로 신중하게 진행.** 오너의 지시대로 구현은 Opus
서브에이전트에게 맡기고, 완료 후 제가 별도로 독립 재검증했습니다.
- 서브에이전트: 오프라인 `gh`/`date` 스텁 테스트 하네스를 새로 만듦 — 진짜 프로덕션
  bash 스크립트를 YAML에서 PyYAML로 그대로 추출해(중복 사본 없이) 실행하되, `PATH`
  맨 앞에 가짜 `gh`(호출 인자를 JSONL로 기록하고, GET은 `event=` 쿼리 필터링까지
  진짜 GitHub API처럼 흉내내고, `-X POST`는 설정된 종료 코드를 반환)와 가짜 `date`
  (환경변수로 주입한 가짜 현재 시각/요일 반환)를 심어 완전히 네트워크 없이 테스트.
  신규 테스트 8건 추가(누락 대상마다 정확히 1회씩 재실행되는지, 정상 대상은 재실행
  안 되는지, 재실행 실패가 제대로 보고되는지, **어제 자동 재실행으로 성공한 실행이
  오늘 "정상"으로 인식되는지**(이벤트 필터 제거의 핵심 회귀 테스트), `duel_daily.yml`
  류의 `workflow_run` 트리거 성공도 인식되는지, 주말 스킵, 월요일 확장 윈도우와의
  상호작용, `actions: write` 권한 확인) — 전체 33건(기존 25 + 신규 8).
- 제 독립 재검증:
  - `git diff` 전체를 줄 단위로 검토해 지시한 범위(permissions·필터 제거·재실행
    블록·문서)와 정확히 일치하는지 확인.
  - 수정된 YAML을 PyYAML로 재파싱, 두 스텝의 bash 스크립트를 각각 `bash -n`으로
    문법 검사 통과 확인.
  - `tests/test_watch_schedule_health_window.py` 단독 실행 → 33 passed.
  - 전체 스위트 `python3 -m pytest --ignore=archive -q` → **2076 passed, 66 skipped,
    회귀 0건**.
  - 서브에이전트가 이미 돌린 것과는 별개로, 제가 직접 뮤테이션 테스트를 하나 더
    수행: 파일을 `/tmp`에 백업해두고 재실행 호출에서 `-f ref=main` 인자를 실수로
    빠뜨린 것처럼 만든 뒤 관련 테스트만 재실행 → **정확히 2건이 실패**하며 누락된
    인자를 지목하는 명확한 assertion diff 확인 → `cp`로 백업에서 원복(바이트
    단위로 동일함이 보장되는 복사) → 33/33 재통과 확인.

**남은 것 — 오너가 해야 할 실전 확인.** 이번에도 코드·오프라인 테스트로는 "재실행
API 호출 인자가 맞는가"까지만 검증했고, **실제로 GitHub Actions에 대고 `dispatches`
POST가 진짜로 동작하는가**는 아직 실전으로 확인되지 않았습니다. #182/#183에서 썼던
것과 같은 방법 — `test/watchdog-issue-check` 스타일의 임시 브랜치를 만들어
`TARGETS`에 `test_suite.yml`(저장소에 실제로 있고 schedule로는 안 도는, 안전한
워크플로우)을 넣고 `workflow_dispatch`로 워치독을 한 번 돌려보면, 이번엔 "누락 판정
→ 자동으로 `test_suite.yml`이 재실행되는 것"까지 실전으로 볼 수 있습니다. `scrape.yml`
같은 실제 수집기 대상으로는 절대 테스트하지 않는 것이 맞습니다(§0-3-2 — 외부
사이트에 불필요한 요청을 만들면 안 됨). 확인 후에는 지난번처럼 테스트 브랜치를
삭제하면 됩니다.

### #185 — [실전 버그] 자동 재실행(#184)이 장중에 걸려 "틀린 종가"를 정상인 것처럼 저장할 수 있던 설계 허점 발견·수정 (2026-09-01)

**어떻게 발견했는가.** #184(2026-08-31)로 워치독에 자동 재실행을 넣고 실전 확인까지
마친 바로 다음 날, 이번엔 진짜로 `scrape.yml`·`indicator_kr.yml`이 지연되는 상황이
실전에서 발생했습니다(2026-09-01 18:49 KST 기준 둘 다 예정 시각보다 1.5~2.7시간
지연). 오너가 "내일 아침 9시에 자동 재실행이 걸리면, 그때 크롤링하는 동안 마침 열려
있는 장의 실시간 시세를 오늘자 데이터인 것처럼 가져오게 되는 거 아니냐"고 정확히
지적했습니다 — #184를 만들 때 "언제 재실행해도 안전한가"를 전혀 따지지 않았다는
것을 그제야 깨달았습니다.

**근본 원인 — 코드로 직접 확인(추측 아님, §0-1).** `watch_schedule_health.yml` 자신의
cron이 `0 0 * * *`(UTC) = **09:00 KST**였는데, 이건 코스피 정규장(09:00~15:30 KST)
개장 정각입니다. 그리고 대상 수집기 중 핵심 두 개는 **"과거 특정 날짜"를 지정해
백필하는 기능이 아예 없습니다**:
- `collector_kospi200.py` — `argparse`/`sys.argv` 사용이 0건입니다(인자를 하나도 안
  받음). 항상 "지금 이 순간"의 시세만 긁습니다. `scrape.yml`의 `target_date` 입력은
  백필이 아니라 **이 수집기 스텝 자체를 건너뛰는 스위치**일 뿐입니다
  (`if: ${{ github.event.inputs.target_date == '' }}`, `scrape.yml:39`).
- `collector_indicator_kr.py` — 기록되는 날짜가 `today_str = _now_kst()`(236행)로
  **실행 시각이 곧 그 데이터의 날짜**입니다. `--limit/--days/--delay` 세 인자 중
  "어느 날짜로 기록할지"를 바꿀 수 있는 건 없습니다.

즉 09:00 KST 체크에서 "누락"(최근 30/76시간 내 성공 없음 — 최소 이틀 가까이 실패가
누적된 상황)이 확정되면, 자동 재실행이 **정확히 장 시작 직후**에 걸리고, 그러면
(a) 장 시작 직후의 어중간한 실시간 가격이 그날의 정상 종가인 것처럼 그대로 저장되고,
(b) 정작 진짜로 빠졌던 과거 날짜의 종가는 백필 수단이 없어 영영 못 채웁니다. 에러 없이
**틀린 값이 정상인 척 남는** — 지금까지 이 프로젝트에서 나온 실패 중 가장 늦게
발견될 수 있는 유형이었습니다.

**조사 범위 확대 — 나머지 7개 대상도 직접 확인.** Opus 서브에이전트에게 조사를
맡기면서 "어느 게 안전한지"를 대상별로 판단하지 말고 코드로 확인하라고 지시했더니,
오너가 지적한 두 개 말고도 실제로는 백필이 안 되는 대상이 더 있었습니다:
`run_duel_daily_batch.py`/`run_duel_daily_batch_us.py`/`run_scorecard_publish_batch.py`는
`--target-date`/`--published-date` 같은 날짜 인자가 있어서 언뜻 백필이 되는 것처럼
보이지만, 가격 자체는 `data/` 안의 **현재 스냅샷**에서 읽으므로 실제로는 "현재
가격에 과거 날짜 라벨만 붙이는" 가짜 백필이었습니다. 반대로
`collector_us_stocks.py`(`--skip-if-not-ready`로 이미 담긴 세션이면 스스로 건너뜀),
`collector_us_indices.py`/`utils/report_db.py`(날짜가 시계가 아니라 받아온 가격
데이터 자체에서 옴), 배당 감시 2종(DART 접수일 워터마크로 스스로 따라잡음)은
언제 재실행해도 비교적 안전했습니다. 이렇게 대상마다 안전성이 갈리다 보니,
**대상별 예외를 두지 않고 9개 전부 똑같이 장중에는 재실행을 건너뛰는 쪽**을
택했습니다 — 어느 게 안전한지 매번 다시 판단해야 하는 구조 자체를 안 만들기 위해서
입니다.

**고친 것 — #183 때와 같은 벨트-앤-서스펜더(두 겹).**
1. **워치독 자신의 cron을 09:00 KST → 18:00 KST(UTC 09:00)로 이동.** 장 마감(15:30)
   이후라 그 시점 "현재 시세"가 곧 종가이고, 대상 9개의 그날 정규 스케줄 중 가장
   늦은 것(`duel_daily.yml`, 17:10 KST)보다도 뒤라 **그날 안 돈 것을 다음 날이
   아니라 그날 저녁에** 잡아냅니다 — 오히려 대응이 하루 빨라지는 부수 효과가
   있습니다. 9개 대상 × 7개 요일 = 63가지 조합 전부에 대해 "정상적으로 그날
   스케줄대로 돌았다면 18:00 KST 체크 시점에 window(평소 30시간/월요일 76시간)
   안에 들어오는가"를 cron 값으로 직접 계산해 검산했습니다(가장 빡빡한
   `duel_daily.yml`도 그날치가 0.83시간 전, 설령 진행 중이어도 어제치가
   24.83시간 전이라 30시간 안 — 지연·진행중으로 인한 오탐 없음).
2. **재실행 POST 직전에 "지금 한국 증시 장중(평일 09:00~15:30 KST)인가"를 한 번
   확인**해서, 장중이면 대상 9개 전부 재실행을 걸지 않고 건너뜁니다. 1번 조치만으로는
   오너가 수동 `workflow_dispatch`로 이 워치독을 장중에 돌리는 경우(2026-09-01
   실전 확인 때 실제로 있었던 상황)를 못 막기 때문입니다. "지금"의 출처를 하나로
   두려고(자정 근처 이중 호출로 날짜·시각이 어긋나는 것 방지) 이미 읽어 둔
   `NOW_TS`에서 KST 분을 계산했습니다(한국은 1988년 이후 서머타임이 없어 UTC+9
   고정이므로 이 계산으로 충분). 이 판단은 **그 순간 한 번 보고 끝**입니다 —
   재시도 스케줄링이나 상태 파일은 만들지 않았습니다("감시의 감시"가 되지 않도록
   하라는 오너의 기존 지시를 그대로 지킴). 어차피 다음 날 18:00 KST에 이 워치독이
   다시 돌면서 같은 판정을 한 번 더 합니다. 공휴일(휴장일)은 판정하지
   않습니다 — 휴장일 표를 코드에 넣으면 매년 틀리고(§0-1), 휴장일에 한 번
   건너뛰는 것은 "안전한 쪽으로 틀리는" 방향이라 그대로 뒀습니다.
3. 이슈 본문에 **세 번째 케이스**를 추가 — 기존 "자동 재실행 트리거함"/"자동
   재실행도 실패"에 더해 "장중이라 자동 재실행 생략"과 그 이유·다음 확인
   시각(18:00 KST)·급하면 수동으로 실행하는 우회로를 명시했습니다. 이유 없이
   조용히 아무것도 안 하면 "워치독이 고장났나"로 읽히기 때문입니다. 실제로 이슈
   본문을 렌더해 보다가 "재실행을 걸어만 둔 상태입니다"라는 기존 문구가 장중
   생략 케이스에서는 사실이 아니게 되는 것도 발견해 "건 항목은 걸어만 둔 상태"로
   같이 고쳤습니다.

**검증 — 전부 오프라인(진짜 `gh`는 이 환경에 설치조차 안 돼 있고 네트워크 호출
0건).**
- `tests/test_watch_schedule_health_window.py` 33건 → **46건**(+13). 기존
  `_GH_STUB`/`_DATE_STUB` 패턴을 그대로 확장해 장중·장마감·경계·주말을 오프라인
  재현. 장중 dispatch 완전 차단, 장 마감 후 정상 동작, 경계(08:59/09:00/11:00/
  15:30/15:31) 5건, 주말엔 시각만으로는 장중이어도 휴장 처리, 정상일 땐 장중
  판정이 정상 판정을 오염 안 시키는지, `market_hours` 출력이 항상 나가는지,
  워치독 cron 자체를 YAML에서 읽어 대상 9개 cron과 대조하는 테스트, 이슈 본문을
  실제로 렌더해 장중 생략 설명이 있는지/없는지 검사하는 테스트까지 포함.
- 과정에서 기존 테스트에 있던 진짜 결함도 하나 발견: 하드코딩돼 있던
  `NOW_TS = 1756512000`이 주석이 말하던 2026-08-30이 아니라 실제로는
  **2025-08-30(토)**였습니다(연도가 하나 밀린, 사람이 못 알아채는 종류의
  어긋남). 요일도 `dow=4`로 따로 하드코딩돼 있어 시각과 요일이 서로 안 맞는
  채로도 기존 테스트가 통과하고 있었습니다 — 이번에 `kst_ts()` 헬퍼로 날짜를
  그대로 적고 계산하게 바꾸고, `dow`도 `now_ts`에서 자동 유도하도록 고쳐 이
  어긋남 자체를 구조적으로 없앴습니다.
- Opus 서브에이전트가 돌연변이 4종(cron을 09:00 KST로 원복 / 장중 판정 무력화 /
  요일 조건 제거 / 이슈 문구 삭제)으로 테스트가 실제로 빨간불이 되는지 확인.
- 제(상위 세션)가 별도로 독립 뮤테이션 테스트 수행: `KST_MARKET_CLOSE_MIN` 경계
  비교를 `-le`→`-lt`로 바꿔 15:30 정각이 장중에서 빠지도록 만듦(off-by-one) →
  경계 테스트 정확히 1건만 실패, 실패 메시지에 "15:30에 실제로 재실행이
  걸린다"는 구체적 증거(`scrape.yml (자동 재실행 트리거함)`)가 그대로 찍힘 →
  `cp`로 백업에서 바이트 단위 원복 → 46/46 재통과 확인.
- `python3 -m pytest tests/test_watch_schedule_health_window.py` → 46 passed.
  `python3 -m pytest --ignore=archive -q` 전체 스위트 → **2089 passed, 66
  skipped, 회귀 0건**.
- 수정한 YAML을 PyYAML로 재파싱, 두 스텝의 셸 스크립트를 각각 `bash -n`으로
  문법 검사 통과 확인. 저장소의 다른 워크플로우 파일 16개도 여전히 정상
  파싱됨(회귀 없음).

**의미.** #184가 "며칠씩 데이터가 밀리는 것"을 막으려다, 검토가 부족하면 그보다
더 나쁜 "틀린 데이터가 조용히 정상인 척 쌓이는 것"을 만들 수 있었던 사례입니다.
외부 사이트 구조 변경 같은 천재지변이 아니라, 순전히 새 자동화 기능 자체의 시점
설계 누락이었고 — 오너의 실전 감각("이거 재실행되면 그때 시세를 가져오는 거
아니냐")이 오프라인 테스트만으로는 못 잡을 종류의 결함을 잡아낸 사례로 기록해
둡니다.

### #186 — [실전 버그] "내 성적표" 종목 이름 검색이 공백 하나 차이로 못 찾던 문제 수정 — LLY "일라이 릴리" (2026-09-02)

**어떻게 발견했는가.** 오너가 토스증권 앱에서 보유 종목("일라이 릴리", LLY)을 그대로
따라 입력했는데 "이 종목은 찾지 못했습니다"가 떴습니다. 확인해보니 이 앱이 추적하는
미국 시가총액 상위 550 안에 LLY는 분명히 있었고(대형 제약주로 랭킹도 높음), 티커
`LLY`로 직접 입력하면 정상적으로 잡혔습니다 — 이름으로만 못 찾는 상태였습니다.

**근본 원인 — 코드로 직접 확인.** `utils/company_names_kr.py`에 LLY의 한글명이
공백 없이 `"일라이릴리"`로 저장돼 있는데, `find_ticker_by_name()`(`utils/scorecard_db.py`)의
정확일치·부분일치 판정이 둘 다 공백까지 그대로 비교하는 단순 문자열 검사였습니다.
사용자가 화면에 보이는 대로("일라이 릴리", 공백 있음) 입력하면 정확일치(`query in
candidates` 리스트 멤버십)도, 부분일치(`query in candidate` 부분 문자열 검사)도 공백
한 칸 차이로 전부 실패합니다. 세 번째 스크린샷(토스증권 잔고 "자세히" 보기 화면)으로
확인한바 실제 증권사 앱들이 잔고 상세 화면에서 한글 종목명에 공백을 넣어 보여주는 게
일반적이라, LLY 하나만의 문제가 아니라 공백 표기가 저장값과 다른 모든 종목에서
재현될 수 있는 구조적인 틈이었습니다(실측: `company_names_kr.py`의 250개 override 중
공백이 포함된 건 4개뿐(`GOOGL`/`GOOG`/`BRK.A`/`BRK.B` — 전부 클래스 구분자 " A"/" B"/
"C" 형태)이라, 대부분 종목이 공백 없이 저장돼 있어 이 틈에 노출돼 있었습니다).

**고친 것.** `find_ticker_by_name()`의 정확일치→유일한 부분일치 판정 로직 자체는
그대로 두고, 비교 직전에만 양쪽 문자열에서 공백(중간 포함)을 전부 제거하는
`_strip_spaces()` 헬퍼를 추가해 적용했습니다. 화면에 보여줄 종목명은 항상
`stock.get("name")` 원본을 그대로 반환하므로 저장값·표시값은 전혀 건드리지 않았고,
"코드가 이름을 지어내는" 것도 아닙니다 — 그저 비교 시점의 공백 민감도만 없앴습니다.

**검증.** `tests/test_scorecard.py`의 `test_resolve_stock_query()`에 회귀 케이스
4건을 추가했습니다: (1) 기존처럼 공백 없이 입력해도 여전히 인식(회귀 없음 확인),
(2) 토스증권처럼 공백을 넣어 입력해도 정확일치로 인식(이번 버그의 실제 재현),
(3) 공백 섞인 부분 입력도 유일하면 부분일치로 인식, (4) 연속 공백이 여러 군데
섞여도 정규화 후 인식. 뮤테이션 테스트로 수정 전 코드로 되돌려 새 테스트 3건이
정확히 빨간불이 되는 것을 확인한 뒤(그 중 어떤 것도 우연히 통과하지 않음) 원상
복구했습니다. `python3 -m pytest tests/test_scorecard.py -k resolve_stock_query` →
통과, `python3 -m pytest --ignore=archive -q` 전체 스위트 → **2089 passed, 66
skipped, 회귀 0건**.

**의미.** 정확일치·부분일치 판정 자체는 이미 신중하게 설계돼 있었지만(§0-1 —
모호하면 추측하지 않고 실패), 비교 이전 단계의 아주 사소한 공백 정규화 누락 때문에
"엄연히 목록 안에 있는 종목을 없다고 잘못 알려주는" 실사용 버그로 이어졌습니다.
LLY 하나가 아니라 비슷한 표기 차이가 있는 다른 종목에서도 앞으로 재현되지 않도록
비교 단계 전체에 정규화를 적용했습니다.

### #187 — 국내 스코어카드 카드에 "다음 배당 일정" 보조 정보 연결 — 매일 도는 DART 배당 캘린더 재활용 (2026-09-03)

**배경.** `collector_dividend_payment_kr.py`가 매일 05:30 KST에 DART 배당결정 공시를
수집해 `data/dividend_kr_2026_payment_events.json`을 쌓아 온 지 일주일 넘었는데,
이 데이터는 `/dividend`(배당 캘린더) 화면에서만 쓰이고 있었습니다. 오너가 "지금까지
안 쌓인 과거분은 어쩔 수 없지만, 지금부터 쌓고 있는 데이터는 최대한 활용하는 게
좋겠다"며 국내 종목 스코어카드 카드에도 연결해 달라고 요청했고, "기재정정 공시도
어느 정도 따라갈 수 있지 않을까"라는 구체적 요구도 함께 주었습니다. 처음엔 이
데이터로 배당수익률 자체를 TTM(최근 12개월 합산)으로 재계산하는 안도 검토했지만,
수집 기간이 짧아 아직 근거가 부족해 이번엔 "다음 배당 일정 안내"로 범위를
좁혔습니다(오너 확인: "지금 당장에는 [TTM 재계산이] 무리더라도... 연결을 같이
할 수 있지 않을까").

**설계 — 오푸스 서브에이전트(높은 노력)에게 위임, 상위 세션이 독립 검증.**
1. **선택 로직 (`web/pages/dividend_page.py::next_dividend_event()`, 신규)** — 한
   종목의 이벤트 목록에서 배당기준일이 **오늘 이후(오늘 포함)**인 것만 후보로 삼고,
   같은 배당기준일에 원본과 `[기재정정]`이 함께 있으면 **가장 나중에 접수된 것**을
   대표로 삼습니다(호출부의 정렬 상태에 기대지 않고 함수 안에서 한 번 더 정렬).
   그중 가장 가까운 날짜 1건만 반환합니다. `dividend_kr_2026_payment_events.json`
   자체가 "`[기재정정]`은 원본과 별개 레코드로 남고 어느 게 최종본인지는 이 파일이
   판단하지 않는다"고 스스로 명시한 파일이라(수집기 §0-1), 최종본 판정은 화면 몫으로
   설계돼 있었고 — 이번에 그 몫을 순수 함수 한 곳에 모았습니다.
2. **배선 (`web/pages/pegy_page.py`)** — `_render_body()`에서 payment_events 파일을
   한 번만 로드해 `build_payment_event_index()`(캘린더 화면 기존 함수, 재사용)로
   색인을 만들고, 종목 500개 각각에 `next_dividend_event`를 미리 계산해 붙입니다
   (카드 500장이 각자 파일을 다시 읽지 않도록). 실측 성능: 0.418ms — 체감 지연 없음.
3. **표시** — "작년 배당률(확정)" 블록 바로 아래 "📅 다음 배당 일정" 한 줄을
   **다가오는 공시가 있는 종목에만** 추가합니다(500장 전부에 "예정 없음"을 찍지
   않음 — 캘린더 화면의 다른 선택적 배지들과 같은 태도). 현재가로 배당수익률을 다시
   계산하지 않고 공시 원문값(배당기준일·지급예정일·1주당 배당금·배당구분)만 그대로
   보여주며, `[기재정정]`을 따라간 경우 "[기재정정 반영]" 표시를 남기고, 자회사
   대리공시·원문 일부 파싱 실패(`parse_status≠OK`)는 배지로 그대로 밝힙니다 — 실측
   확인 결과 PARTIAL 22건 중 13건이 화면에 보이는 네 항목이 전부 채워져 있어서
   배지가 없으면 완전히 읽힌 공시처럼 오해될 수 있었습니다.

**검증.** 신규 테스트 19건(`tests/test_dividend_next_event.py` 12건 + 기존
`tests/test_pegy_page.py`에 7건 추가) — 정정본 승리, 입력 순서와 무관하게 같은 결과,
접수번호 tie-break, 과거 배당기준일 제외, **오늘==기준일 경계 포함**, 후보 없음 →
None, 가장 가까운 미래 날짜 우선, 파싱 불가 이벤트 무시, 카드에 보조 줄이 없을 때
기존 "작년 배당률" 표시를 건드리지 않는지, 자회사 대리공시·부분 파싱 배지가 실제로
뜨는지까지 포함. 뮤테이션 테스트 5종(정정 우선순위 뒤집기·경계값 뒤집기·최근접→최원거리
뒤집기·빈 자리에 "예정 없음" 강제 표시·파싱 배지 코드 삭제) 전부 의도한 테스트가
정확히 빨간불이 되는 것을 확인한 뒤 원상 복구(원본과 바이트 동일 재확인). 전체
스위트 `python3 -m pytest --ignore=archive -q` → **2109 passed, 68 skipped**
(직전 기준선 2089/66, 회귀 0건 — 상위 세션이 독립적으로 재실행해 재확인). `git diff`로
`pegy_page.py`가 삭제 없이 순수 추가(+160/-0)임을 확인, 기존 "작년 배당률(확정)"
계산·표시 로직은 전혀 건드리지 않았습니다.

**실제 데이터로 확인(2026-09-03 기준)** — 국내 500종목 중 7종목에 보조 줄이
붙었습니다. 예: LG(003550) "배당기준일 2026-09-11 · 지급예정일 2026-09-23 · 1주당
1,000원 (중간배당)", 롯데지주(004990)는 자회사 대리공시 배지가 함께 뜸. 정정본
추종이 실제로 걸리는 사례도 확인(S-Oil, 같은 배당기준일에 원본+기재정정이 함께
접수됨 — 다만 그 기준일이 이미 지나 오늘 카드엔 안 보임, 테스트에서 같은 모양을
미래 날짜로 고정해 재현).

**의미.** 새 데이터를 새로 만들지 않고, 이미 매일 쌓이고 있던(그러나 한 화면에서만
쓰이던) 데이터를 다른 화면에 순수 추가로 연결한 사례입니다. 오너가 요청한 "기재정정
공시 따라가기"는 원본 데이터가 스스로 "판단하지 않는다"고 명시한 지점을 화면이
대신 판단해야 하는 경우였고, 그 판단 규칙(가장 나중 접수분 우선)과 근거를 코드
주석·툴팁 양쪽에 명시해 나중에 다시 봐도 "왜 이렇게 골랐는지"가 드러나게 했습니다.

### #188 — 클라우드플레어 워커(`cloudflare_worker.js`) 저장소 반영 누락 발견 및 정정 (2026-09-03)

**배경.** 오너가 `Duel Daily Batch #21`이 `skipped`로 남은 걸 캡처로 보내와 원인을
조사하던 중, 오늘 `scrape.yml`이 16:10 KST(UTC 07:10:33)에 `workflow_dispatch`로
자동 실행된 기록(run #47)을 발견했습니다. actor 필드가 `moonbear135`로 남아 있어
처음엔 오너가 직접 "Run workflow"를 누른 것으로 추정해 그렇게 안내했는데, 저장소를
더 뒤져보니 #184/#185 직후(2026-09-01)에 만든 클라우드플레어 워커 코드
(`cloudflare_worker.js`)가 있었고, 이 워커의 `CRON_TARGETS`(`"10 7 * * 1-5"` →
`scrape.yml`, UTC 07:10)와 오늘 실행 시각이 정확히 일치해 — 사람이 아니라 이
워커가 자동으로 건 것으로 정정했습니다(GitHub API가 PAT 기반 호출을 그 PAT
소유자 계정 이름으로 기록하는 것으로 보이며, 그래서 actor가 봇이 아니라
`moonbear135`로 남습니다).

**발견한 문제.** 이 워커는 실제로 클라우드플레어에 배포돼 지금도 평일 매일
정상 작동하고 있는데(오늘 실행이 그 증거), 정작 이 저장소(git)에는 한 번도
커밋된 적이 없었고 `TASK_HISTORY.md`에도 기록이 없었습니다. 파일 자체는
이전 세션이 쓰던 임시 작업공간에만 남아 있었던 것으로 보입니다 — "실제로
돌고 있는 코드"와 "저장소에 기록된 코드"가 어긋나 있던 상태였고, 다음에 이
워커를 고치거나 재배포해야 할 때 원본을 못 찾는 상황이 될 뻔했습니다.

**한 일.** 파일을 저장소 루트에 그대로 커밋(`cloudflare_worker.js`, 코드
변경 없이 원본 그대로, 5206바이트 일치 확인)하고 이 항목으로 이력에 남깁니다.

**한계 — 확인 못 한 것(§0-1, 추측 금지).** 클라우드플레어 대시보드 자체
(Cron Trigger 설정값·`GH_TOKEN` 시크릿 값)는 이 세션에서 접근할 수 없어서,
실제 배포본이 이 파일과 바이트 단위로 완전히 동일한지는 확인하지 못했습니다.
다만 오늘 실행 로그(`scrape.yml` run #47, UTC 07:10:33 시작, `workflow_dispatch`,
actor=`moonbear135`)가 이 파일의 `CRON_TARGETS` 설정과 정확히 들어맞아, 최소한
이 로직 그대로 배포돼 있고 정상 작동 중이라는 강한 정황 증거는 있습니다.
오너가 클라우드플레어 대시보드에서 실제 배포본과 이 파일을 한 번 대조해두면
더 확실해집니다.

**참고 — 오늘 duel_daily.yml #21이 skip된 이유(이 워커와는 별개 설계).**
`duel_daily.yml`은 `scrape.yml` 완료를 받아 자동 실행되는데, 그 완료가
`workflow_dispatch`(수동/이 워커에 의한 트리거 포함)로 온 경우는 백필과
구분 못 해 의도적으로 건너뛰도록 설계돼 있습니다(2026-08-26 설계, 파일
자체 주석 참고). 오늘도 이 워커가 건 `scrape.yml` 완료는 건너뛰었고,
이후 GitHub 자체 schedule cron(오늘은 5시간 넘게 지연됨)이 뒤늦게 성공하면
그 완료(`event=schedule`)로 `duel_daily.yml`이 정상 실행됩니다 — 데이터
유실은 아니고 처리 시점만 늦어지는 구조입니다.

### #189 — 코스피·보조지표 수집기에 "오늘 이미 SUCCESS 면 건너뛰기" 사전 점검(`--skip-if-not-ready`) 이식 — 하루 두 번 크롤링 차단 (2026-09-04)

**배경.** #184/#185/#188의 클라우드플레어 워커(`cloudflare_worker.js`)는 "오늘 실행
기록이 없으면 `workflow_dispatch`로 깨움"이라 GitHub 자체 cron이 **먼저** 돌면 조용히
빠지지만, 워커가 먼저 깨우고 GitHub cron이 몇 시간 **뒤에** 늦게 발동하는 반대 순서는
못 막습니다. 실측(`git log --date=iso -- data/...`, 추측 아님 §0-1):
- `kospi200_pegy_latest.json` — 09-02 08:59/13:12 UTC, 09-03 08:46/13:11 UTC → 이틀 연속 하루 두 번
- `indicator_kr_latest.json` — 09-02 17:19/21:39 KST, 09-03 17:17/21:38 KST → 이틀 연속 하루 두 번
같은 날 두 번째 실행은 같은 종가를 한 번 더 긁는 것이라(§0-3-2 정중한 크롤링 위반) 수집기
쪽에서 스스로 멈추게 했습니다. `collector_us_stocks.py`에 이미 있던
`collect --skip-if-not-ready`(`evaluate_collection_readiness()` — 이번에 담길 거래일이
이미 스냅샷에 있으면 exit 0, 단 `status`가 FAILED/DEGRADED 면 빈 집합으로 취급해 재시도,
M15)를 먼저 읽고 같은 취지·같은 플래그 이름으로 옮겼습니다.

**한 일.**
1. `collector_kospi200.py` — `evaluate_kospi200_collection_readiness()` 신설 + `__main__`에
   argparse(`--skip-if-not-ready`) 추가. 판정: 스냅샷 없음/깨짐 → 수집, `metadata.status`
   ≠ SUCCESS(DEGRADED/FAILED, status 키 없는 옛 형식 포함) → 수집(재시도), `last_updated_at`
   의 KST 날짜 == 오늘 → **건너뜀(exit 0)**. 건너뛰면 마스터 목록·전 종목 종가 수집까지
   4단계 전부 돌지 않습니다(미국 쪽과 같은 구조). 파일명 하드코딩은 `KOSPI_SNAPSHOT_FILENAME`
   상수로 단일화(§0-3-10).
2. `collector_indicator_kr.py` — 스냅샷에 `status` 필드 신설(실패 0건 → SUCCESS, 1건이라도
   실패 → DEGRADED. 비율 임계값을 두지 않은 근거: 커밋된 최근 10회 스냅샷 전부 성공 500/실패 0
   이라 "몇 %까지 정상"의 실측 근거가 없음) + `evaluate_collection_readiness()` +
   `main(argv)` 분리(`--skip-if-not-ready`). 옛 형식(status 없음)은 SUCCESS 로 승격하지 않음.
3. `.github/workflows/scrape.yml`·`indicator_kr.yml` — `scrape_us.yml`과 같은 관례로
   `force` 입력(boolean, 기본 false) 추가, 평소엔 `--skip-if-not-ready`, `force=true`면 플래그
   없이 무조건 수집. **`schedule:` cron 블록은 한 줄도 건드리지 않음**(워커 장애 시 안전망).
   워커·워치독은 입력 없이 dispatch 하므로 기본값 false → 점검 켜진 채 돕니다.
4. 문서 동기화 — `watch_schedule_health.yml` 헤더의 "argparse 자체가 없다" 문구,
   `cloudflare_worker.js` 헤더에 "반대 순서는 못 막음 → 수집기 플래그가 막음" 주석(둘 다 주석만).
5. 회귀테스트 — `tests/test_collector_kospi200_ranking.py`·`tests/test_collector_indicator_kr.py`
   에 (a) 오늘 SUCCESS → 스킵, (b) 어제 SUCCESS/파일 없음 → 수집, (c) 오늘 DEGRADED/FAILED/
   옛 형식/깨진 파일 → 재시도, 플래그 없으면(force) 무조건 수집, `__main__` 배선 순서, 워크플로우
   배선·cron 불변 검사 9개 추가. 전체 스위트 2,000+ passed / 회귀 0건.

**확인 못 한 것 / 한계(§0-1).** 실제 GitHub Actions 위에서 하루 두 트리거가 실제로 한 번만
수집하는지는 다음 평일 실행 로그로 확인해야 합니다(로컬에서는 스텁 수집기로 `__main__`
블록을 그대로 exec 해 호출 여부만 검증). 코스피 쪽은 첫 실행이 SUCCESS 가 아니면(예:
FAILED) 두 번째 트리거가 마스터 목록·전 종목 종가까지 한 번 더 돌게 되는데, 이건 미국
쪽과 동일한 의도된 재시도입니다. 첫 실행이 SUCCESS 인데 뒤따르는 전 종목 종가 수집만
실패한 경우는 두 번째 트리거도 통째로 건너뛰므로 그날 `kr_all_market_prices.json`이
갱신되지 않을 수 있습니다(지금까지 그 조합이 실제로 난 적은 없고, 워치독이 잡는 범위 밖 —
필요하면 후속으로 다룰 것).

### #190 — 가드레일 "정합성 모순" ①②④가 연간 ROE 와 TTM PER/EPS 를 같은 기간처럼 비교해 흑자 전환 종목 20개를 오탐하던 문제 수정 (2026-09-03)

**배경(실측, 추측 아님 §0-1).** `utils/guardrail.py`의 2026-08-06 회귀 가드 ①②④는
`t_roe<0 이면서 t_per>0 / t_eps>0 / graham_target 있음`을 "부호 유실 모순"으로 보고
`is_unverified=True`로 승격시켰습니다. 2026-09-03 22:06 스냅샷(`data/kospi200_pegy_latest.json`)
에서 정확히 **20종목**(삼성SDI −3.15%/PER 1,176.86/EPS 458, 에코프로 −8.39%/78.86/1,036,
OCI홀딩스, 펄어비스, DL, 위메이드, 아이에스동서 등)이 이 셋에 모두 걸려 있었고 전부
`t_eps_source=naver_실측`, price÷EPS≈PER 정합이었습니다. 두 지표의 집계 기간이 다릅니다:
- `t_roe` = 네이버 시가총액 순위표 ROE 열. `kospi200_stock_history.csv` 8/27~9/3(2분기 실적이
  TTM 에 반영된 구간)에서 **511종목 중 2종목만** 값이 바뀜 → 분기 롤오버와 무관한 연간(최근 결산) 기준.
- `t_per`/`t_eps` = 종목 상세 aside `PER|EPS(YYYY.MM)` = 최근 4분기 합산(TTM). 같은 구간에
  **78종목** 변동(에코프로 EPS 452→1,036, 펄어비스 2,320→4,227). 시가총액표 PER 열도 이 값과
  3% 이내로 같이 움직임(3단계 교차검증 괴리 0건).
- 거울상 증거: ROE(연간)>0 인데 시가총액표 PER(TTM)<0 인 종목 **14개**(대한항공 7.28%/−42.06,
  LG디스플레이 3.44%/−3.34, 한진칼, 테크윙 등)가 같은 스냅샷에 공존. 부호 유실 버그라면 이
  조합은 생길 수 없음 → 20종목은 "연간 적자 → TTM 흑자 전환"의 정상 조합이지 모순이 아님.
- 영향 범위: `is_unverified=True` → 화면 Forward 카드가 "🛡️ 데이터 검증 실패 (PER·EPS 교차검증)
  … 부호 유실 의심"으로 마스킹되고 퀀트 스코어 풀(`_score_pool`)에서 제외됨. valid_ratio 는
  #11358d4 이후 `is_trailing_loss` 종목을 실패로 안 세므로 영향 없음(0.978 그대로).

**한 일.**
1. `utils/guardrail.py` — ①②④를 **같은 기간(TTM) 지표끼리만** 비교하는 ①'②'④'로 교체:
   ①' 상세 페이지 PER(`t_per_primary`) vs 시가총액표 PER(`t_per_secondary`) 부호 불일치,
   ②' TTM PER(`t_per_measured`, 없으면 `t_per`) vs 실측 TTM EPS 부호 불일치, ④' TTM EPS≤0 인데
   그레이엄 넘버 산출. 이 셋만 "모순"(검증 미통과 승격). 연간 ROE<0 · TTM 흑자 조합은
   `주의(기간 불일치): … 집계 기간이 달라 직접 비교 불가(흑자 전환 구간일 수 있음)`로 기록만
   하고(`consistency_warnings`/`data_issues`) 승격하지 않음. 계산값 EPS(`t_eps_calculated`)는 판정 제외 유지.
2. `collector_kospi200.py` — 스냅샷 딕셔너리에 `t_per_primary`(aside, 부호 보존)·
   `t_per_secondary`(시가총액표, 부호 보존) 신설. ①'는 다음 수집부터 실제로 동작합니다
   (현재 스냅샷엔 두 필드가 없어 판정 생략 — 없는 값으로 판정하지 않음).
3. `tests/test_scoring_coverage.py` — 옛 ①②④ 테스트 3건을 새 규칙 8건으로 교체(기간 불일치 →
   주의만/승격 없음, 진짜 적자는 경고 없음, ①'②'④' 각각 모순 승격, 한쪽 출처 없으면 판정 안 함,
   실제 스냅샷 20종목 재현(없으면 skip), 수집기 배선).

**검증.** 옛 guardrail 을 스냅샷 515종목에 재실행 → 저장값과 불일치 0건(재현 정확). 새 코드:
"모순" 승격 20 → **0**, `is_unverified` 가 바뀐 종목은 정확히 그 20개뿐, ③⑤⑥ 등 나머지 경고
달라진 종목 0, valid_ratio 0.978 불변, 퀀트 스코어 풀 384 → 404. 카드 렌더링(`build_stock_card_html`)
삼성SDI: "데이터 검증 실패 … 부호 유실" 마스크 사라지고 Forward 정상 표시. `py_compile` OK,
전체 스위트 2,072 passed / 68 skipped (수정 전 2,067 / 68, 회귀 0).

**확인 못 한 것 / 한계(§0-1).** (a) 네이버 시가총액표 ROE 가 "연간 결산 기준"이라는 것은
네이버 페이지의 각주를 직접 읽은 게 아니라(이 작업 환경에서 네이버 접속이 차단됨) 위 시계열·거울상
실측으로 추정한 것입니다 — 반대 가설(ROE 도 TTM)은 78 대 2 변동 수와 14개 거울상 조합으로
설명이 안 되지만, 각주 원문 확인은 다음에 브라우저로 한 번 해두면 좋겠습니다. (b) 20종목 중
진짜 부호 유실이 섞여 있는지는 ①'가 다음 수집에서 두 출처를 대조해야 최종 확정됩니다 — 현재
스냅샷엔 시가총액표 PER 원본이 남아있지 않았습니다. (c) 부수 발견: TTM 적자 99종목 전부 aside
`PER|EPS` 파싱이 실패(`t_eps=None`, 시가총액표 PER 로 폴백)해 스냅샷에 음수 `t_eps` 가 0건 —
1-1 감사 때와 달리 네이버가 적자 PER/EPS 를 정규식이 못 읽는 형태로 내보내는 것으로 보이며,
별도 확인 필요(이번 범위 밖). (d) `web/pages/pegy_page.py` 그레이엄 박스는 여전히 `t_roe<0`
만으로 "적자 기업 (EPS가 0 이하…)"라고 쓰는데, 에코프로처럼 TTM EPS 가 +1,036원인 종목엔
문구가 정확하지 않습니다 — 화면 문구 결정은 오너 몫이라 손대지 않음.

### #191 — 도메인 루트 `/` 를 JS 없는 정적 소개 페이지로, 한국 주식 PEGY 화면은 `/kr` 로 이동 (구글 애드센스 "가치가 별로 없는 콘텐츠" 반려 대응, 2026-09-04)

**배경(실측, 추측 아님 §0-1).** 애드센스 사이트 심사가 "빈약하며 제공하는 가치가 전혀 또는 거의
없는 콘텐츠"로 반려됐습니다. `curl` 로 확인한 원인: NiceGUI `@ui.page` 가 서버에서 내려주는 최초
HTML 의 `<body>` 에는 텍스트가 한 글자도 없고(`socket.io.min.js`·`quasar` 등 `<script>` 태그뿐),
PEGY 표·카드는 브라우저가 웹소켓으로 붙은 뒤에야 그려집니다. `<meta name="description">` 도 없었습니다.
크롤러 눈에는 `/` 가 빈 페이지였던 것입니다. 오너 승인 방향: **정적 소개 페이지 추가**.

**한 일.**
1. `web/pages/landing_page.py` 신설 — `@app.get('/')` 순수 FastAPI 라우트(`main.py` 의 `/ads.txt`·
   `/healthz` 와 같은 패턴, §0-3-10). 템플릿 엔진 없이 상수 문자열 + f-string, 외부 CDN·스크립트 0,
   `<style>` 한 블록. 내용: `<title>`·`<meta name="description">`·canonical, 서비스 소개(개인 학습용
   보조 도구, 코스피+코스닥 통합 상위 500 + 미국 상위 종목, 후행지표 원칙), PEGY 설명(SPEC §5-1 수식
   ·Trailing/Forward·성장률 캡), 퀀트 스코어 배점표(SPEC §5-3 그대로), 화면 목록(3단계 공개 스위치가
   켜진 것만 — `web/layout.py` 의 `*_ENABLED` 값을 그대로 읽음), 데이터 출처·3단계 검증(네이버 증권/
   stockanalysis.com, `utils/data_validator.py` 단계명 그대로), 화면과 같은 학습용 안내·투자 주의
   문구, "대시보드 보기" 버튼 → `/kr`, `/us`·`/privacy` 링크. 파비콘은 NiceGUI 가 이미 내주는
   `/favicon.ico`(💡 SVG, 실측) 재사용.
2. `web/pages/pegy_page.py` — `@ui.page('/')` → `@ui.page('/kr')`. **화면 내용은 변경 없음.** 경로
   이름은 미국판 `/us` 와 짝을 이루는 두 글자 소문자(`🇰🇷`/`🇺🇸` 메뉴 쌍)로 정함.
3. `web/layout.py` — 사이드바 `('/', '🇰🇷 한국 주식은 이가격이에요')` → `'/kr'`. 헤더의
   "💡 잘 보면 보이는 손" 라벨을 `/` 링크로 바꿔 대시보드 어디서든 소개 페이지로 돌아갈 입구를 둠.
4. `main.py` — `landing_page` import 추가(등록), 경로 주석 갱신. `dividend_us_page.py` 머리말의
   `/` 언급 정정. 내부 참조 전수 조사(`grep -rn "'/'\|\"/\"" web/ main.py tests/`): 코드상 `/` 를
   가리키는 곳은 `layout.py` 메뉴 한 줄뿐이었고, 로그인 후 이동은 전부 `ui.navigate.reload()`
   (경로 무관)라 리다이렉트 갱신 대상 없음.
5. `tests/test_landing_page.py` 신설(6건) — `/` 응답에 description·title·본문 문장이 **서버 응답
   자체에** 있음, `<script` 0개, 소개 페이지 링크 ↔ `pegy_page.py` 실제 `@ui.page` 경로 일치(AST),
   사이드바가 `/kr` 을 가리키고 `/` 는 안 가리킴, `web/pages/*.py` 어디에도 `@ui.page('/')` 가
   없음, `main.py` 등록. `test_pegy_page.py`·`test_event_loop_blocking.py` 의 낡은 `/` 주석 갱신.
6. `PROJECT_STATUS.md` §0-3 표·§0-4 파일 구조 갱신.

**검증.** `py_compile` OK. 로컬 기동(`NICEGUI_STORAGE_SECRET` 임시 난수) 후 `curl -s localhost:PORT/`
→ 200 · `text/html` · 9,638 바이트, 응답 원문에 `<title>잘 보면 보이는 손 — …</title>`·
`<meta name="description" …>`·"PEGY = PER ÷ (이익 성장률 + 주주환원율)" 등 본문이 그대로 있고
`<script` 태그 0개. `/kr` → 200(기존 NiceGUI 셸, `socket.io` 포함 — 예전 `/` 와 동일),
`/us`·`/privacy`·`/favicon.ico` 200, `/ads.txt` 404(게시자 ID 미설정 시 기대 동작), `/nonexistent` 404.
전체 스위트 **2,081 passed / 70 skipped**(회귀 0, 신규 +6).

**확인 못 한 것 / 한계(§0-1).** (a) 애드센스 재심사 통과 여부는 구글 쪽 판단이라 장담할 수 없습니다 —
이번 수정은 "크롤러가 실제 텍스트를 읽을 수 있다"는 확인된 원인 하나를 없앤 것입니다. 심사관이
`/kr`·`/us` 같은 대시보드 화면까지 크롤링해 "빈 페이지"로 볼 가능성은 남습니다(그 화면들은 여전히
NiceGUI 렌더). (b) 외부에서 `/` 를 북마크한 사용자는 소개 페이지를 먼저 보고 버튼 한 번을 더
눌러야 합니다(오너가 승인한 방향). (c) `robots.txt`·sitemap 은 원래 없었고 이번에도 추가하지
않았습니다(요청 범위 밖). (d) Render 재배포 후 실제 도메인에서 `curl https://visiblehand.co.kr/`
로 한 번 더 확인하는 것을 권합니다(이 작업은 로컬 기동으로만 검증했습니다).

### #192 — 공개 화면 4개(`/kr`·`/us`·`/dividend`·`/indicator`)에 크롤러용 즉석 정적 HTML 분기, `/privacy` 순수 정적 전환 (애드센스 반려 대응 2차, 2026-09-04)

**배경.** #191 이 `/` 만 고쳤고, 로그인 없이 누구나 보는 데이터 화면 4개는 여전히 NiceGUI 렌더라
크롤러에게 빈 페이지였습니다. 이 화면들은 실시간 시세가 아니라 **수집기가 하루 1~2번 갱신하는 배치
스냅샷(JSON)** 을 그리는 것뿐이라, 요청 시점의 그 파일을 서버에서 HTML 로 펼쳐 보여줘도 실사용자가
보는 것과 같은 데이터입니다. 오너 확정: 봇에게만 **그 순간의 스냅샷을 즉석 렌더**한 정적 HTML(미리
만들어 저장하지 않음 — 워크플로우 무변경), 일반 사용자는 예전 그대로, `/privacy` 는 고정 법률 문구라
봇 감지 없이 통째로 정적 전환.

**조사(§0-1, 추측 아님).** 설치본 NiceGUI **3.16.0** `nicegui/page.py::page._wrap.decorated` 를 직접
읽음: 페이지 함수가 `fastapi.Response` 를 반환하면 `if isinstance(result, Response): return result`
로 NiceGUI 화면 조립을 건너뜀. `request` 매개변수는 `_wrap` 이 시그니처에 없으면 스스로 끼워 넣고,
있으면 FastAPI 가 타입 주석으로 주입. NiceGUI 자신도 `nicegui/client.py::AI_AGENT_TOKENS` 로 UA 를
보고 AI 에이전트에게 마크다운을 돌려주고 있음(프레임워크가 이미 하는 일). 별도 미니 앱으로 로컬
기동 + curl 로 **early return 실동작 확인** 후 채택(미들웨어 불필요). 각 화면이 읽는 파일·필드는
실제 JSON 을 열어 확인: `kospi200_pegy_latest.json`(metadata.last_updated_at/status/total_count,
stocks[].rank/name/code/market/price/t_per/t_pegy/f_pegy/f_target/quant_score/score_max/badge/is_visible),
`us_stocks_latest.json`(metadata.last_updated_at_kst/session_dates_from_source/indices/failed_tickers,
stocks[].symbol/name_kr/industry/price/t_per/f_per/t_pegy/f_pegy/f_target/…),
`dividend_kr_2026_latest.json`(summary.generated_at_kst/completed/…, records[].stock_code/corp_name/
market/stlm_dt/reprt_name/dps_cash_common/cash_yield_common/bsns_year) + `dividend_history_kr_2023_2025.json`,
`indicator_kr_latest.json`(generated_at/date/…count, stocks[].rsi/rsi_signal/macd/macd_signal_line/
macd_cross/bb_percent_b/bb_position/verdict_label/unavailable_reasons).

**한 일.**
1. `web/static_html.py` 신설 — `BOT_UA_TOKENS`(googlebot·mediapartners-google·adsbot-google·
   google-inspectiontool·storebot-google·googleother·bingbot — 일반 브라우저 UA 에 있는 토큰은
   넣지 않음, 보수적), `is_known_crawler(request)`(None → False), `crawler_response(html)`
   (`Vary: User-Agent`·`Cache-Control: no-store`, NiceGUI 가 만들어 둔 요청용 `Client` 를 응답 직후
   `BackgroundTask` 로 삭제 — NiceGUI 마크다운 응답과 같은 방식), 문서 뼈대 `render_document()`
   (`<title>`·`<meta description>`·canonical·CSS·푸터), `notice_box()`·`table_html()`·
   `remaining_note()`. `landing_page.py` 의 CSS·뼈대를 여기로 옮겨 재사용(§0-3-10).
2. 4개 화면 — `@ui.page` 함수에 `request: Request = None` 추가(테스트가 인자 없이 부르므로 기본값
   None = 봇 아님), 맨 앞에서 `if is_known_crawler(request): return crawler_response(await
   build_crawler_html())`. `build_crawler_html()` 은 화면의 `_render_body()` 가 쓰는 **같은 로더·
   같은 파일**을 읽어 제목·투자주의/학습용 고지(`_TITLE_HEAD + LEARNING_NOTICE_HTML + _TITLE_TAIL`
   HTML 조각 그대로 재사용)·동기화 시각·상태 경고·상위 30건 표(`CRAWLER_TABLE_ROWS`)·"나머지는
   브라우저에서" 안내·푸터 고지를 만듦. 실패 시 화면과 같은 문구 + "데이터 준비 중"만(§0-1).
   `/dividend`·`/indicator` 는 공개 스위치(`*_ENABLED`·`*_MENU_ADMIN_ONLY`)를 화면과 같은 상수로
   판정해 꺼져 있으면 크롤러에게도 같은 "준비중" 문구(클로킹 아님). 일반 접속자 경로는 `return None`
   한 줄 외 변경 없음.
3. `/privacy` — `@app.get('/privacy')` 순수 라우트로 전환. 본문 `_BODY_MARKDOWN` 은 한 글자도 안
   바꾸고 `ui.markdown` 이 쓰던 것과 같은 `markdown2`(extras `fenced-code-blocks`·`tables`)로 HTML 화.
4. 테스트 — `tests/test_crawler_html.py` 신설(15건: 봇 판정 보수성, 4개 화면 실데이터 HTML 에
   title/description/실제 종목명·코드/`<script` 0, 스냅샷 실패 시 표 없음+정직 문구, 스위치 꺼짐/
   관리자 전용 시 "준비중", 페이지 함수에 봇 요청 → `HTMLResponse` 반환·헤더, `request` 시그니처,
   4개 파일만 분기, `/privacy` 정적·법률 문구·`@ui.page` 아님). `test_web_session_isolation.py`
   의 `/privacy` 스모크를 정적 라우트 방식으로 갱신. `PROJECT_STATUS.md`·`main.py` 주석 갱신.

**검증.** `py_compile` OK. 로컬 기동(`NICEGUI_STORAGE_SECRET` 임시 난수, `DIVIDEND_ENABLED`·
`INDICATOR_ENABLED`=true) 후 curl:
- Googlebot UA → `/kr` 200 · text/html · 14,858B · `<script` 0 · `vary: User-Agent` · 본문에
  "📅 마지막 동기화: 2026-09-03 22:06", 삼성전자/005930/250,000원/… 30행 표. `/us` 17,321B(엔비디아
  NVDA $224.41 …, S&P500·나스닥·다우 ETF 프록시 등락률). `/dividend` 14,832B(요약 5건, 고려아연
  10,000원 … 확정 148건 중 30건, 수집 중단 경고 그대로). `/indicator` 12,355B(삼성전자 RSI 46.59 …,
  강한 경고 상·하단). `/privacy` 8,746B 정적, 법률 문구 원문.
- Mediapartners-Google / AdsBot-Google / Google-InspectionTool / bingbot → 전부 정적(socket.io 0).
- Chrome / iPhone Safari / curl UA → `/kr` 417KB NiceGUI 셸(`x-nicegui-content: page`, script 10개,
  socket.io 포함) — **예전과 동일**, `/us`·`/dividend`·`/indicator` 도 같음.
- 전체 스위트 **2,097 passed / 72 skipped**(회귀 0, 신규 +15; skip 은 #191 때와 같은
  `test_suite_integrity` Check A 의 하네스 미사용 파일 건너뜀).

**확인 못 한 것 / 한계(§0-1).** (a) 애드센스 재심사 통과 여부는 구글 판단. (b) 클로킹 정책:
봇과 사람이 **같은 파일의 같은 데이터**를 보되 포장(정적 표 30행 vs 인터랙티브 카드 500장)이
다릅니다 — 구글 문서상 "동적 렌더링"류의 허용 범주로 판단하지만, 심사관이 어떻게 볼지는 장담
못 함. 상위 30행만 싣는 것도 같은 맥락(전부 싣지 않음을 본문에 명시). (c) Render 배포 환경은
같은 `main.py`·같은 nicegui 핀이라 동일하게 동작할 것으로 보나, Render/Cloudflare 앞단이 UA 를
바꾸거나 캐시하면(`Vary: User-Agent` 를 무시하는 캐시) 분기가 달라질 수 있음 — 배포 후 실제
도메인에서 `curl -A Googlebot…` 으로 확인 권장. (d) `DATA_SOURCE_BASE_URL` 원격 모드에서는
크롤러 요청도 같은 `load_json_file_async`(스레드) 를 타므로 첫 요청이 원격 왕복만큼 느릴 수 있음
(`response_timeout` 60초 안). (e) `markdown2` 를 `privacy_page.py` 가 직접 import 하게 됨 —
nicegui 의 필수 의존성이라 설치본에 항상 있지만 `requirements.txt` 에 명시적으로는 없음.

### #193 — 결투 정기입금이 계좌 개설일(`anchor_date`) 이전 날짜에도 들어가던 버그 수정(KRW·USD) + 잘못 들어간 원장 정정 SQL (2026-09-04)

**배경(재현 수치).** 2026-08-22 에 개설된 결투 계좌(시드 1,000만원)가 2026-09-04 화면에서 총자산
**1,160만원 = 1,000만원 + 80만원×2** 로 표시됐습니다. 이 계좌는 8/22 에 생겼으니 7/10·8/10 정기입금을
받을 수 없는데(그때 계좌가 없었음) 둘 다 들어가 있었습니다.

**원인(코드 레벨, 오너가 먼저 특정).** 2026-08-29 재감사 H-7 로 `utils/duel_batch.py::
_pending_monthly_deposit_dates(day, lookback_days=60)` 가 최근 60일 안의 "매월 10일"을 전부 찾아
날짜마다 `duel_db.apply_monthly_deposits()` 를 부르게 됐습니다(배치 공백 보정). 그런데
`apply_monthly_deposits()` 는 `fetch_all_active_accounts()` 로 **지금 활성인 계좌 전체**를 가져와
"그 계좌·그 날짜로 이미 입금이 있는지"만 걸렀고, **그 계좌가 그 날짜에 존재했는지
(`anchor_date <= event_date`)** 는 보지 않았습니다. `fetch_all_active_accounts()` 는 이미
`anchor_date` 를 select 하고 있었는데 필터에 안 쓰였습니다. `utils/duel_db_usd.py::
apply_monthly_deposits_usd()` 도 같은 구조의 미러라 같은 버그. (스키마 §1 주석: "anchor_date 는
입금·정산 리듬의 기준일(계좌 생성일)".)

**한 일.**
1. `utils/duel_db.py::apply_monthly_deposits()` · `utils/duel_db_usd.py::apply_monthly_deposits_usd()`
   — payload 대상 계좌를 `_iso_date(row["anchor_date"]) <= event_date` 인 것으로만 좁힘
   (`anchor_date == event_date` 는 개설 당일이 10일인 정상 케이스라 포함, `>` 만 제외). 이미 읽어
   온 `anchor_date` 를 그대로 쓰므로 **추가 질의 없음**(§0-3-2 — 질의 수 3개 유지). 날짜 정규화는
   같은 파일의 기존 헬퍼 `_iso_date()` 재사용(§0-3-10 — 문자열/date/datetime 모두 ISO 문자열로
   맞춘 뒤 사전순 비교 = 날짜 비교). `anchor_date` 가 없는 행(스키마상 not null 이라 정상이면
   없음)은 지어내지 않고 `_iso_date` 가 `DuelDbError` 로 멈춤(§0-1). 두 함수 docstring 에 왜 이
   필터가 필요해졌는지(H-7 60일 lookback 과 만나 개설 전 날짜 입금) 기록.
2. 회귀 테스트 — `tests/test_duel_db.py` +5, `tests/test_duel_db_usd.py` +3. 핵심은
   `test_apply_monthly_deposits_skips_accounts_opened_after_the_deposit_date`(KRW/USD): 계좌 A
   (anchor 9/20)·계좌 B(anchor 9/5)에 9/10 입금을 넣으면 **B 에만** 들어가야 함. 수정 전 코드에
   돌려 보면 `assert 2 == 1` 로 실패(버그 재현 확인), 수정 후 통과. 그 외: 개설 당일(=10일) 포함,
   `anchor_date` 가 date 객체로 와도 동일 판정, 전부 개설 전이면 중복 조회조차 안 하고 0행,
   `anchor_date` 없는 행은 예외. 기존 fixture `_active_accounts()`/`_active_accounts_usd()` 에
   `anchor_date` 컬럼 추가(실제 표에서 not null 이라 실제 행 모양에 맞춘 것 — 기존 단언은 무변경).
3. `sql/duel_ledger_fix_2026-09-04_backdated_monthly_deposit.sql` 신설(기존 `duel_schema_migration_
   <날짜>_<주제>.sql` 이름 규칙을 따르되 스키마 변경이 아닌 **데이터 정정**이라 `ledger_fix` 로 구분).
   ① 진단(읽기 전용): `duel_cash_ledger`/`_usd` 에서 `event_type='monthly_deposit'` 이고
   `event_date < 계좌.anchor_date` 인 행 목록 + 계좌별 건수·합계. ② 정정(쓰기): 각 행마다
   **반대 부호의 `reversal` 행**을 `insert … select` 로 추가 — `event_date` 는 원본과 같은 날짜,
   `order_id` null, memo 는 "정정: <anchor_date> 계좌 개설 이전(anchor_date보다 이른 날짜
   <event_date>)에 잘못 들어간 정기입금 되돌림 — 원본 원장 id=N". `not exists` 로 같은 원본 id 의
   되돌림이 있으면 다시 넣지 않음(재실행 안전). ③ 확인: 잘못된 입금+되돌림의 계좌·날짜별 합이 0 이
   아닌 행(0행이어야 정상). 원장은 append-only(§4-2 트리거)라 update/delete 를 쓰지 않았고,
   `duel_cash_ledger(_usd)_sign_match`·`_order_link` 제약이 `reversal` 에는 부호·order_id 제한이
   없음을 스키마에서 확인. 파일 머리말에 "진단 → 건수 확인 → 정정 → 확인" 순서와 백업 권장 주석.
   **이 SQL 은 실행하지 않았음** — service_role 키는 GitHub Actions Secrets 에만(§0-3-8), 오너가
   Supabase SQL 편집기에서 실행.

**검증.** `py_compile` OK. `tests/test_duel_db.py`+`test_duel_db_usd.py` **267 passed**. 전체
`pytest -q --ignore=archive` **2,105 passed / 72 skipped**(#192 의 2,097 + 신규 8, 회귀 0).
SQL 은 실서버 대신 **로컬 PostgreSQL 16 에 `sql/duel_schema.sql` + 2026-08-29 마이그레이션을 그대로
올리고**(auth 스키마·role 만 스텁) 재현 데이터(8/22 개설 계좌에 7/10·8/10 입금 80만원×2, 8/5 개설
계좌에 8/10 정상 입금, USD 8/22 계좌에 8/10 $500)로 실행: 진단이 정확히 잘못된 3행(KRW 2·USD 1)만
집계, 정정 insert 가 제약·트리거를 통과해 잔고 11,600,000 → 10,000,000(USD 10,500 → 10,000), 정상
계좌(10,800,000)는 무변경, 2회째 실행은 `INSERT 0 0`, 확인 쿼리 0행, reversal 행에 update 시도 →
append-only 트리거가 거부.

**확인 못 한 것 / 남는 일(§0-1).** (a) 실제 Supabase 의 잘못된 행 건수·계좌 수는 진단 쿼리를 오너가
돌려야 알 수 있음(이 세션에는 키 없음). (b) **스냅샷·TWR 부작용**: 이미 저장된
`duel_daily_snapshots(_usd)` 의 총자산·현금은 잘못된 입금이 반영된 값이고, 배치 TWR 은
`EXTERNAL_CASH_FLOW_TYPES = ('seed','monthly_deposit')` 만 외부 현금흐름으로 봐서 `reversal` 을
세지 않음. 정정 뒤 첫 스냅샷에서 현금이 80만원×N 줄어드는데 그날 cash_flow 는 0 이라 그 구간 일간
수익률이 그만큼 마이너스로 잡힐 수 있음. 이 작업은 원장만 다뤘고 스냅샷·TWR 처리는 별도 판단 필요
(SQL 머리말에도 기록). (c) 잔고 계산은 `duel_db.sum_cash_balance()`/`cash_balances_by_account()` 가 event_type 을
가리지 않고 `amount` 를 전부 더하는 구조임을 코드로 읽어 확인 — 따라서 `reversal` 행은 화면·
배치 잔고에 자동 반영될 것으로 보이나, 실제 화면에서 실행 확인은 안 함.

### #194 — #193 후속: 잘못된 정기입금이 이미 반영된 `duel_daily_snapshots(_usd)` 행 정정 SQL 추가 (같은 파일 §4, 2026-09-04)

**왜 원장 되돌림(#193 §2)만으로는 안 끝나나(코드 레벨, 오너가 먼저 특정).** 화면 숫자가 두 경로로
만들어짐. ① **총자산·예수금** — `web/pages/duel_page.py::_render_account_card()` 가 매 페이지 로드마다
원장을 라이브 합산(`sum_cash_balance(fetch_my_cash_ledger(...))`, 저장 스냅샷 안 씀) → reversal 행만
들어가면 **다음 새로고침에 바로** 정상. ② **누적 수익률(TWR)** — `fetch_my_snapshots()` 로
`duel_daily_snapshots` 에 **이미 저장된** 과거 행을 읽어 `compute_twr()` → 그 행들은 버그 시점에 배치가
실제 계산해 넣은 값이라 `total_value`·`cash_balance`(첫 행이면 `cash_flow_amount`까지)가 이미 틀려
있고, 원장에 reversal 을 넣어도 **저절로 안 바뀜**. 배치가 나중에 고쳐 줄 수도 없음:
`utils/duel_batch.py::collect_external_cash_flows()` 는 직전 스냅샷 경계(boundary) 이전 날짜의 원장
행을 "이미 반영됨"으로 건너뛰는데 reversal 은 원본과 같은 과거 날짜(anchor_date 이전)라 **언제 돌아도
boundary 보다 이르고**, 애초에 `EXTERNAL_CASH_FLOW_TYPES=('seed','monthly_deposit')` 라 reversal 은
세지도 않으며, `cash_flow_amount` 는 `check (>= 0)` 라 되돌림을 음수 현금흐름으로 적을 수도 없음.
`duel_daily_snapshots` 는 `revoke delete … from service_role` 이지만 **update 는 열려 있음**
(`grant select, insert, update … to service_role`, 스키마 §9) → SQL 로 직접 update 해야만 바로잡힘.

**한 일.** `sql/duel_ledger_fix_2026-09-04_backdated_monthly_deposit.sql` 에 **§4 "스냅샷 정정(있을
경우)"** 을 이어 붙임(새 파일 없음 — 기존 진단→정정→확인 흐름 뒤에 4-A/4-B/4-C). 머리말 실행 순서에
4) 추가, "이 파일이 고치지 않는 것" 문단은 "→ §4 에서 처리" 로 갱신.
1. **4-A 진단(읽기 전용, KRW·USD)** — §1 조건(`monthly_deposit` 이고 `event_date < anchor_date`)으로
   잘못된 입금을 받은 계좌를 verdict 로 분류: `AUTO` / `MANUAL: position_value>0`(매수 이력 —
   `dates_with_positions`) / `MANUAL: 원장에 다른 행`(시드·잘못된 입금·그 되돌림 외 원장 행 —
   `other_ledger_events`) / `MANUAL: 시드 불일치` / `SKIP: 스냅샷 없음`. 오너 지시는 (i) 전 스냅샷
   `position_value = 0` ↔ (ii) `> 0` 두 갈래였는데, §0-1 로 **(b) "원장에 시드+잘못된 입금+되돌림
   외 행이 없음"** 조건을 하나 더 걸었음 — 예: 8/05 개설 계좌가 7/10 잘못된 입금과 8/10 **정상** 입금을
   함께 가진 경우, 정답은 seed_amount 가 아니라 "seed + 정상 입금"이라 오너 규칙대로 덮어쓰면 오히려
   틀려짐. 이런 계좌는 AUTO 에서 빼고 수동 목록에 사유와 함께 남김.
2. **4-B 정정(쓰기, KRW·USD 각 1문)** — `target` CTE 가 4-A 의 AUTO 조건 네 가지를 `exists/not exists`
   로 그대로 다시 씀(→ MANUAL 계좌는 where 에서 **구조적으로** 제외). "가장 이른 행"은 `distinct on
   (account_id) … order by account_id, snapshot_date`(unique (account_id, snapshot_date) 라 동률 없음).
   update: 모든 행 `cash_balance = total_value = seed_amount`; 가장 이른 행만 `cash_flow_amount =
   seed_amount, kind='seed'`, 나머지 `0 / null`. `position_value`·`total_cost` 는 이미 0 이라 안 건드림,
   `updated_at` 은 트리거(`duel_snapshots_set_updated_at`)에 맡김. 같은 값을 다시 쓰므로 멱등.
3. **4-C 확인(읽기 전용)** — 4-C-1/2: AUTO 계좌 스냅샷 중 정답(위 규칙, `row_number()` 로 첫 행 판정)과
   다른 행(0행이 정상). 4-C-3: AUTO 계좌의 최신 스냅샷 `cash_balance` 와 원장 라이브 합계가 같은지
   (화면 예수금 ↔ TWR 입력 교차 확인, 0행이 정상). 파일 끝 "⚠️ 여기부터는 사람이 판단" — MANUAL 계좌를
   사유·매수 날짜·기타 원장 행과 함께 다시 SELECT(값을 지어내지 않음, §0-1).

**검증(로컬 PostgreSQL 16, #193 과 같은 방식).** `sql/duel_schema.sql` + 마이그레이션 2개를 auth 스텁
위에 올리고 재현 데이터 6계좌: KRW A(8/22 개설·매수 없음·7/10+8/10 잘못된 입금, 스냅샷 9행 중 8/29
이후 4행이 11,600,000), B(A 와 같되 8/25 삼성전자 100주 700만원 실제 매수 주문+원장, position 7,000,000),
C(8/05 개설·7/10 잘못된 입금+8/10 정상 입금·매수 없음), D(정상 계좌, 버그 무관); USD E(8/22 개설·8/10
$500 잘못 입금·매수 없음·첫 스냅샷이 버그 이후라 첫 행 `mixed 10,500`), F(E + position 5,000).
§1~§3 실행 후(reversal 5+2행) §4 를 `set role service_role` 로 실행:
- 4-A: A·E → AUTO, B·F → `MANUAL: position_value>0`(날짜 목록 포함), C → `MANUAL: 원장에 다른 행`
  (`monthly_deposit 2026-08-10 800000`), D 는 어디에도 안 나옴.
- 4-B: `UPDATE 9`(A) / `UPDATE 4`(E). 전 행 덤프 before/after diff — 값이 바뀐 행은 **A 의 4행
  (11,600,000→10,000,000)과 E 의 4행(첫 행 10,500 mixed→10,000 seed, 나머지 10,500→10,000)뿐**.
  B·C·D·F 는 `updated_at` 까지 바이트 단위로 동일(diff 없음).
- 4-C: 실행 전엔 A 4행·E 4행이 위반으로 잡히고(4-C-3 도 A·E 불일치), 실행 후 4-C-1/2/3 모두 0행.
- 재실행: 4-B 를 한 번 더 → `UPDATE 9 / 4`, 값 diff 없음(13행의 `updated_at` 만 갱신 = 트리거 동작 확인),
  4-C 여전히 0행. 파일 전체(§1~§4)를 새 DB 에서 두 번 연속 실행해도 오류 없음(2회째는 `INSERT 0 0`).
- 제약: update 가 `duel_snapshots(_usd)_total_match`·`_cash_flow_match` 를 통과했고, 실행 후 두 제약
  조건을 SELECT 로 다시 세어 위반 0행.
코드(.py) 변경 없음 → pytest 는 돌리지 않음.

**확인 못 한 것 / 남는 일(§0-1).** (a) 실제 Supabase 에서 AUTO/MANUAL 계좌가 각각 몇 개인지는 4-A 를
오너가 돌려야 알 수 있음(키 없음). (b) MANUAL 계좌(매수 이력 있음 / 정상 입금 공존)의 스냅샷은 이
파일이 손대지 않음 — 목록만 남기고 사람이 계좌별로 판단. (c) `duel_holding_snapshots` 는 안 건드림
(AUTO 계좌는 보유가 없어 행이 없음). (d) 화면에서 TWR 이 실제로 정상화되는지는 실행 후 확인 필요.
(e) 4-C-3 은 §2 를 먼저 실행했다는 전제 — 순서를 바꾸면 A 같은 계좌가 불일치로 보일 수 있음(머리말에
명시).

### #195 — [실전 버그] 코스피 수집기 사전 점검(#189)이 "오늘 날짜" 만 보고 "시각" 은 안 봐서, 새벽 07:04 SUCCESS 가 금요일 정식 장마감 수집을 통째로 건너뛰게 한 결함 수정 (2026-09-05)

**사고 경위(실측, §0-1).** 오너가 2026-09-05(토) 아침 확인: `/kr` 의 삼성전자우가 184,100원
(= 9/3 목 종가)인데 실제 9/4(금) 종가는 191,600원. 결투 계좌 평가금액·"내 성적표" 현재가도 같이
목요일 값에서 멈춰 있음. `git log --date=iso -- data/kospi200_pegy_latest.json`:
- `2026-09-03 22:09:19 +0000` = **2026-09-04(금) 07:09 KST** — 장 시작(09:00) 전 새벽에 GitHub 자체
  cron(9/3 tick 이 밤새 밀린 것으로 보임, #154 와 같은 지연 유형)이 발동해 크롤링 1회.
- 그때 저장된 `metadata.last_updated_at = "2026-09-04 07:04"`, `status = SUCCESS`. 네이버가 그 시각에
  보여주는 값은 전날(목) 종가이므로 **"오늘 날짜 라벨 + 어제 내용물"** 인 스냅샷이 됨.
- 금요일 정식 트리거(cron 16:05 / Worker 16:10 KST)는 #189 의 `evaluate_kospi200_collection_readiness()`
  가 `last_updated_at[:10] == 오늘` 만 보고 "이미 SUCCESS" 로 판정 → `sys.exit(0)`. 이 exit 에
  뒤이어 도는 마스터 목록·**전 종목 종가(`kr_all_market_prices.json`, 결투·성적표 현재가 조회용)** 수집까지
  4단계가 통째로 묶여 있어(#189 "한계" 문단에 적어둔 결합) 함께 멈춤. 금요일 종가는 한 번도 수집되지 않음.
`indicator_kr_latest.json` 은 09-04 21:40 KST 생성이라 이번엔 무사했지만, #189 에서 같은 모양(date 만
비교)으로 옮겨 온 `collector_indicator_kr.evaluate_collection_readiness()` 에도 같은 결함이 잠복해 있었음
(새벽 실행이면 FDR 에 오늘 봉이 없어 "오늘 날짜인데 어제 지표" 가 되는 구조 동일).

**원인.** #189 는 "같은 날 두 번째 트리거는 언제나 첫 번째보다 늦다(둘 다 오후)" 를 암묵 전제로 날짜만
비교. GitHub cron 이 몇 시간 지연되는 것을 넘어 **전날 tick 이 다음 날 새벽에** 발동하는 경우를 고려하지
않음. #185 가 워치독의 장중 자동 재실행은 막았지만, GitHub 자체 cron 이 새벽에 발동하는 경로는 그 방어
밖이었음.

**한 일.**
1. `utils/constants.py` — `KR_MARKET_CLOSE_HOUR = 15`, `KR_MARKET_CLOSE_MINUTE = 30` 신설(§0-3-10 —
   미국 쪽 `US_MARKET_CLOSE_HOUR/MINUTE` 와 같은 꼴, 두 국내 수집기가 공용). 휴장·조기마감 캘린더 판정은
   하지 않음을 주석에 명시(§0-1).
2. `collector_kospi200.py` — `kr_snapshot_time_is_after_close(last_updated_at)` 신설(시각 ≥ 15:30 이면
   True, 15:30 정각 포함; 시각이 없거나 파싱 불가면 False = "모르면 수집"). `evaluate_kospi200_collection_readiness()`
   의 **"오늘 날짜 + SUCCESS" 분기에만** 이 시각 조건을 덧붙임 — 장마감 이후면 종전대로 건너뜀, 이전(새벽·
   장중)이면 "아직 오늘 장마감 데이터 아님" 으로 다시 수집. 스냅샷 없음/깨짐, DEGRADED/FAILED, 어제 이전
   SUCCESS 분기는 한 줄도 안 바꿈. 반환 dict 에 `snapshot_after_close`(오늘 자 SUCCESS 가 아니면 None) 추가,
   사유 문구·`--skip-if-not-ready` help·헤더 주석(§ "2026-09-05 개정") 에 경위와 규칙 변경 이유 기록.
   `last_updated_at` 은 수집 **완료** 시점에 찍히므로 "15:30 이후 완료" 판정이 되는 점, 15:30 직전 시작·
   직후 완료라는 이론상 빈틈(정식 트리거가 모두 16:05 이후라 운영 범위 밖)도 헤더에 명시.
3. `collector_indicator_kr.py` — 같은 결함을 같은 방식으로 수정(`snapshot_time_is_after_close(generated_at)`,
   `evaluate_collection_readiness()` 오늘 자 SUCCESS 분기만). 요청 범위(코스피·미국)를 넘는 파일이지만
   #189 에서 같은 코드 모양으로 함께 이식된 쌍둥이라 이번에 같이 닫음.
4. `collector_us_stocks.py` — **점검 결과 같은 결함 없음, 손대지 않음.** `evaluate_collection_readiness()` 는
   달력 날짜가 아니라 `resolve_collection_session_et()`(마감 16:00 + 30분이 지난 가장 최근 평일)이 계산한
   **거래일** 을 스냅샷의 실제 세션 날짜(`session_dates_from_source`, 페이지 "At close" 타임스탬프에서 읽음)와
   비교함. 실제 호출로 확인: 목요일 세션 스냅샷 상태에서 금 09:05 ET(장 시작 전) 실행 → 대상 = 목요일 → 건너뜀
   (그 시각 페이지도 목요일 종가라 옳음), 금 16:35 ET → 대상 = 금요일 → 수집, 토 03:00 ET → 대상 = 금요일 → 수집.
   즉 "대상 날짜" 자체에 마감 시각 규칙이 들어 있어 코스피 쪽 날짜-only 결함이 구조적으로 없음.
5. 회귀 테스트 — `tests/test_collector_kospi200_ranking.py`(+2): (b) 사고 원본 그대로 `07:04` SUCCESS → 수집,
   `15:29` → 수집, 시각 없는 날짜만 → 수집; 경계 `15:30` 정각 → 건너뜀, 상수 (15, 30) 단일 출처, 파싱 불가
   입력 6종 전부 False. 기존 (a)(c)(d)(e) 테스트에 `snapshot_after_close` 단언 보강(어제 자 22:11 SUCCESS 도
   수집 — 시각 조건은 오늘 자에만). `tests/test_collector_indicator_kr.py`(+2): 같은 케이스 + `main(argv)` 배선
   (플래그 + 새벽 SUCCESS → `run()` 실제 호출). `tests/test_us_stocks.py::test_automation_readiness` 에 위 4번
   재현 케이스 2건(`r9`/`r10`) 추가해 "미국 쪽엔 이 결함이 없음" 을 고정. 수정 전 코드로 되돌려 돌리면
   코스피 readiness 테스트 5개가 실패함을 확인한 뒤 적용.

**검증.** `pytest -q tests/test_collector_kospi200_ranking.py tests/test_collector_indicator_kr.py tests/test_us_stocks.py`
94 passed. 전체 `pytest -q --ignore=archive` **2,109 passed / 72 skipped**(#193 의 2,105 + 신규 4, 회귀 0).
저장소에 실제로 남아 있는 사고 스냅샷(`last_updated_at 2026-09-04 07:04`)으로 새 판정을 호출하면 "장마감 15:30
이후가 아닙니다 — 다시 수집합니다" 로 나옴(수정 전에는 "이미 완료 — 건너뜀").
중간에 두 테스트가 깨진 것은 코드가 아니라 **주석 문구** 때문이었음 — `test_scorecard.py` 가
`utils/constants.py` 에 "scorecard" 문자열이 없어야 한다고 보고(`scorecard_page.py` 언급 → "내 성적표 화면" 으로
고침), `test_stock_history.py` 가 `collector_kospi200.py` 에서 `run_kr_ticker_master_collector()` 문자열의
첫 등장이 `run_kr_all_market_prices_collector()` 보다 앞이어야 한다고 봐서(헤더 주석의 함수명 언급을 풀어 씀).

**하지 않은 것 / 남는 일(§0-1).** (a) **2026-09-04(금) 종가 백필은 하지 않음** — 이 수집기는 "지금 이 순간"
시세만 가져오는 구조라 과거 시점 재수집이 불가능(`watch_schedule_health.yml` 헤더 명시). 금요일 데이터는 결측으로
남고, 09-07(월) 정식 장마감 수집이 정상적으로 도는지는 오너가 실제 운영에서 확인. (b) 새벽 실행 자체(GitHub cron
지연 발동)를 막은 것은 아님 — 그 실행은 여전히 크롤링 1회를 하고 "오늘 날짜 + 새벽" SUCCESS 를 남기지만, 이제
그날 오후 정식 실행이 그것을 덮어씀. 새벽 실행을 아예 안 하게 하려면 수집기 시작 시 "지금 장마감 전이면 종료"
가드가 필요한데(미국 쪽 `is_ready_now` 2차 방어선과 같은 취지), 로컬 수동 실행·테스트 경로까지 영향이 가서
이번엔 넣지 않음 — 후속 판단 사항. (c) #189 "한계" 의 "첫 실행 SUCCESS 인데 전 종목 종가만 실패" 조합은 그대로.


### #196 — [실전 버그 2건] ① `/indicator` 카드 이력표가 컨테이너의 얼어붙은 로컬 사본을 읽음(`read_history_rows` 원격 경로 누락) ② 스케줄 워치독이 "스킵으로 조용히 끝난 실행" 을 성공으로 오판 (2026-09-05)

#195 직후 저장소 전체 감사에서 발견된 후속 결함 2건. 둘 다 09-04(금) 사고(#195)와 같은 날 실제로 겉으로
드러난 증상이 있었고, 이번 수정으로 각각의 재발 경로를 닫음.

**결함 A — `/indicator` 카드 "최근 이력/전일 대비" 표가 하루 늦음.**
- 증상(실측): 페이지 상단 배너는 "데이터 기준 2026-09-04 21:40"(원격 최신)인데, 같은 페이지 종목 카드 안의
  이력표는 "가장 최근 기록은 2026-09-03까지". 실제로는 09-04 지표 수집이 21:40 에 500종목 전부 성공해
  `data/indicator_kr_history.csv` 에 09-04 행 500개가 이미 정상적으로 쌓여 있었음.
- 원인: Render 는 `DATA_SOURCE_BASE_URL` 로 원격(GitHub raw)에서 읽고 `data/**` 커밋은 Build Filters 로 재배포를
  막아 두므로(`utils/data_source.py` 머리말), 컨테이너의 로컬 `data/` 사본은 **마지막 코드 배포 시점에 얼어붙음**.
  2026-08-17 에 `load_stock_history()`(한 종목 조회) 는 `data_source.read_text()` 로 옮겼는데, 전체 표를 읽는
  `read_history_rows()` 는 그 마이그레이션에서 **누락** 되어 여전히 순수 로컬 `open()`. `web/pages/indicator_page.py::
  _load_recent_history_by_code()` 가 카드 렌더링에 이 함수를 직접 씀. `grep -rn read_history_rows` 결과 화면 쪽
  호출부는 `/indicator` 한 곳뿐 — `/kr`·`/us` 의 종목별 다운로드는 `load_stock_history()`(이미 수정됨)를 쓰므로 영향 없음.
- 수정 (`utils/stock_history.py`): `read_history_rows(path, *, local_only=False)` 가 `data_source.read_text(path,
  encoding="utf-8-sig")` 를 거치도록 변경 — 원격 성공이면 원격 최신, 실패+캐시면 마지막 성공분+배너, 콜드스타트 실패면
  로컬 사본+배너, 셋 다 없으면 빈 목록. `DATA_SOURCE_BASE_URL` 미설정(기본값)이면 예전과 100% 동일한 로컬 읽기
  (`_read_local`). 시그니처(동기)·반환값(행 dict 목록, 실패 시 빈 목록)·`run_blocking(read_history_rows, path)`
  호출 방식은 그대로. **기록 경로는 원격 전환하지 않음** — `append_daily_history()` 는 "읽은 것 + 오늘치" 를 같은
  로컬 파일에 통째로 다시 쓰므로 읽기·쓰기가 반드시 같은 파일이어야 함(읽기만 원격이면 원격이 뒤처졌을 때 로컬에
  쌓인 날짜가 통째로 사라질 수 있음). 그래서 `local_only=True`(= 예전 원본 그대로인 `_read_history_rows_local`)
  로 호출. 헤더 주석에 경위 기록.
- 회귀 테스트 (`tests/test_data_source.py::test_read_history_rows_goes_through_data_source`, [9-b]): [9]의
  `load_stock_history()` 검사와 대칭 — ① 원격 꺼짐(로컬 그대로·BOM 처리·네트워크 0회·배너 없음·없는 파일 → []),
  ② 원격 성공 → 09-04 행이 보임(얼어붙은 사본의 09-03 아님) + `local_only=True` 는 원격이 켜져 있어도 로컬만 읽고
  네트워크를 안 탐, ③ TTL 뒤 원격 실패+캐시 → 마지막 성공분 유지 + 배너 대상에 `data/indicator_kr_history.csv`,
  ④ 콜드스타트 실패 → 로컬 사본 + `local_fallback` 배너, ⑤ 셋 다 없음 → [], ⑥ 소스 수준(기록 경로 `local_only=True`,
  indicator_page 가 여전히 `run_blocking(read_history_rows,` 로 부름).

**결함 B — 스케줄 워치독(`watch_schedule_health.yml`)이 "데이터를 하나도 안 만든 날" 에 초록불.**
- 증상: 09-04(금) `scrape.yml` 정식 실행은 `--skip-if-not-ready` 로 아무것도 수집하지 않고 exit 0(#195) → 실행
  결과는 conclusion=success. 워치독은 conclusion 만 보므로 "✅ 성공 실행 확인됨" — 새 데이터가 하루 종일 하나도 안
  만들어졌는데 이슈도 디스코드 알림도 없었음.
- 수정 (`.github/workflows/watch_schedule_health.yml` — 구조·알림 방식은 그대로, 판정 조건만 강화):
  - `TARGETS` 에 3·4번째 필드(데이터 파일|타임스탬프 JSON 키) 추가. 이번 결함 범위인 두 대상만:
    `scrape.yml → data/kospi200_pegy_latest.json / metadata.last_updated_at`,
    `indicator_kr.yml → data/indicator_kr_latest.json / generated_at`. 나머지 8개는 종전대로 conclusion 만 봄(범위 확장 안 함).
  - 성공 실행이 있는 경우에만 `gh api -H "Accept: application/vnd.github.raw" repos/…/contents/<path>?ref=main` 으로
    main 의 파일을 받아(체크아웃 없이 파일 하나만 읽는 가장 가벼운 방법; 기존 `contents: read` 권한으로 충분) 인라인
    파이썬으로 판정: 타임스탬프 날짜가 **기대 거래일**(지금이 평일 장마감 이후면 오늘, 아니면 가장 최근 평일 — 사람이
    장 마감 전에 수동 실행해도 오탐 없음)이고 **시각 ≥ 15:30 KST**(정각 포함 — 수집기의
    `kr_snapshot_time_is_after_close()`/`snapshot_time_is_after_close()` 와 같은 규칙). 파일을 못 받거나 JSON 이
    아니거나 키가 없으면 "갱신 확인 못 함 = 미갱신"(안전한 쪽). 장마감 기준값은 기존 `KST_MARKET_CLOSE_MIN=930` 을
    그대로 인자로 넘김 — 워크플로우는 체크아웃 없이 돌아 `utils/constants.py` 를 import 할 수 없으므로, 테스트가 두
    파일을 직접 읽어 `KR_MARKET_CLOSE_HOUR*60+KR_MARKET_CLOSE_MINUTE` 와 같은지 대조(한쪽만 바뀌면 빨간불).
  - "데이터 미갱신" 은 "실행 없음" 과 똑같이 처리: 같은 자동 재실행(장중이면 종전대로 생략)·같은 이슈/디스코드 알림·
    같은 잡 실패(exit 1). 이슈 항목 문구만 `- scrape.yml (실행은 성공했지만 데이터 미갱신: 데이터 기준 2026-09-04 07:04
    KST — 날짜는 오늘이지만 장마감 15:30 이전 시각(장 시작 전·장중 값); 자동 재실행 트리거함)` 처럼 사유가 앞에 붙고,
    "실행 없음" 항목 문구는 예전과 글자 그대로 동일. 이슈 본문 첫 문단에 "성공인데 왜 이슈인지"(`--skip-if-not-ready`
    → 타임스탬프까지 확인) 설명 추가. 18:00 KST 재실행은 장마감 후라 #195 로 고쳐진 수집기 사전 점검이 "오늘자
    SUCCESS 지만 장마감 이전 시각" 을 보고 이번엔 실제로 수집함.
- 회귀 테스트 (`tests/test_watch_schedule_health_window.py` §6, +14): 가짜 `gh` 에 contents API(GH_DATA_FILES) 추가,
  `run_check_step(data_files=…)`(생략 시 정상 파일 → 기존 46개 검사가 그대로 통과). ⭐ 사고 원본 재현(금 18:00,
  success 실행 + `2026-09-04 07:04` → ❌·재실행·사유 문구), 어제 날짜 16:05 → ❌("기대 거래일 2026-09-04"),
  경계 4종(15:30 정각 통과 / 15:29 ❌ / 21:40 통과 / 00:00 ❌), 정상 → 재실행 0건 + 로그 "갱신 확인" 문구, 404 → ❌,
  HTML·키 없음 → ❌(예외로 안 죽음), 조회 범위(두 대상만·성공 실행 있을 때만·"실행 없음" 문구 불변), 장 마감 전
  수동 실행(화 11:00 → 월 데이터 정상, 월 08:00 → 금 정상·목 ❌), 장중 미갱신 → 보고만 하고 재실행 생략, 상수 대조,
  이슈 본문 설명. `load_check_step_script()` 에 `DATA_FRESH`/`/contents/` 마커 검사 추가(사라지면 `_MarkerNotFound`).
  수정 전 워크플로우로 되돌려 돌리면 31개 실패 확인.

**검증.** 관련: `pytest -q tests/test_data_source.py tests/test_stock_history.py` 34 passed,
`tests/test_watch_schedule_health_window.py` 60 passed(46 + 14). 전체 `pytest -q --ignore=archive` **2,124 passed / 72 skipped**
(#195 의 2,109 + 신규 15, 회귀 0; 실행 환경의 명령 시간 상한 때문에 45개 파일을 3묶음으로 나눠 돌렸고 합계가
`--collect-only` 의 2,196건과 일치). 중간에 `test_suite_integrity.py` 가 `test_data_source.py::main()` 의 수동 호출
목록에 새 테스트가 빠졌다고 잡아 목록에 추가(#168 H-3 재발 방지 장치가 의도대로 작동).

**하지 않은 것(§0-1).** (a) 워치독의 데이터 확인 대상을 두 개 밖으로 넓히지 않음(다른 8개는 파일·키가 제각각이라
별도 작업). (b) 공휴일(휴장일) 판정은 여전히 없음 — 휴장일에는 수집기가 그날 날짜로 스냅샷을 남기므로 오탐은 없고,
어느 쪽이든 안전한 방향. (c) 09-04(금) 종가 백필은 #195 와 같은 이유로 하지 않음. (d) 실제 GitHub/디스코드 부수효과
(이슈 생성·웹훅)는 여전히 오프라인 검증 밖 — 오너가 Actions 탭에서 workflow_dispatch 로 한 번 돌려 확인 필요.


### #197 — 결투 주문 취소 사유(`fail_reason`)에 "(작업지시서 2-4-5)" 같은 내부 문서 인용이 사용자 화면에 그대로 노출 — 실행되는 문자열 4곳 정리 + 재발 방지 메타 테스트 (2026-09-05)

**경위(오너가 실제 화면 캡처로 지적).** 결투 주문 내역 화면에 8/28 취소 주문의 사유가
"… 휴장일이거나 수집 실패입니다(둘을 구분하지 않습니다, 작업지시서 2-9-1). 다음 거래일로 이월하지 않습니다(작업지시서 2-4-5)."
로 떠 있었고, 오너 지적 — "이건 내부에서 코딩하면서 쓰는 용어잖아, 실패한 사람 입장에서는 뭘 어쩌라는 건지 모르겠다".
캡처의 문장 자체는 8/28 에 저장된 **과거 기록**(그 경로 `duel_batch._freshness_reason()` 은 이미 8/29 에 같은 이유로
정리됨 — 그 함수 docstring 참고)이라 DB 의 옛 문구는 소급 수정하지 않음. 그러나 **지금도 새로 만들어지는** 사용자 노출
문구에 같은 모양이 남아 있었음.

**전체 스캔.** `utils/`·`web/` 의 `.py` 전부를 AST 로 훑어(주석·docstring 제외, f-string 조각·이어붙인 문자열 포함)
"작업지시서" 가 **실행되는 문자열 리터럴** 안에 있는 곳을 찾음 — 4곳(전부 KRW/USD 공용 경로. `duel_batch_usd.py`·
`duel_db.py`·`duel_db_usd.py`·`web/` 은 docstring/주석뿐이라 해당 없음):

| 파일:행 | 이전 | 이후 |
|---|---|---|
| `utils/duel_rules.py:546` `allocate_pending_orders()` 매수 취소 `fail_reason` | `{ticker}의 확정 종가를 확보하지 못해 체결하지 않고 취소했습니다 — 모르는 가격으로 체결하거나 다음 날로 이월하지 않습니다(작업지시서 2-4-5).` | `{ticker}의 그날 확정 종가를 확보하지 못해 이 주문은 체결하지 않고 취소했습니다. 확인되지 않은 가격으로 체결하거나 다음 날로 넘기지 않습니다. 예수금은 그대로 남아 있으니, 원하시면 다음 접수 시간대에 다시 주문하시면 됩니다.` |
| `utils/duel_batch.py:771` `plan_order_fills()` 매도 취소 `fail_reason` | `{ticker}의 확정 종가를 확보하지 못해 매도를 체결하지 않고 취소했습니다 — 모르는 가격으로 팔거나 다음 날로 이월하지 않습니다(작업지시서 2-4-5).` | `{ticker}의 그날 확정 종가를 확보하지 못해 이 매도 주문은 체결하지 않고 취소했습니다. 확인되지 않은 가격으로 팔거나 다음 날로 넘기지 않습니다. 보유 주식은 그대로 남아 있으니, 원하시면 다음 접수 시간대에 다시 주문하시면 됩니다.` |
| `utils/duel_rules.py:796` `compute_twr()` `DuelRuleError` 메시지 | `… 입금을 수익으로 착각하게 됩니다(작업지시서 2-6). 값이 없는 구간의 TWR 은 계산하지 않습니다.` | `… 입금을 수익으로 착각하게 됩니다. 값이 없는 구간의 수익률(TWR)은 계산하지 않습니다.` |
| `utils/duel_batch.py:326` `_top_ranked_prices()` `DuelBatchError` 메시지 | `… 몇 종목만 보고 그날 수집 성패를 판정하지 않습니다(작업지시서 2-9).` | `… 몇 종목만 보고 그날 수집 성패를 판정하지 않습니다.` |

각 지점의 근거 인용(2-4-5 / 2-6 / 2-9)은 **바로 위 코드 주석**으로 옮김(`_freshness_reason()` 의 8/29 정리와 같은 패턴).
뒤의 두 예외 메시지는 배치 로그/화면 예외 표시용이라 사용자가 볼 가능성은 낮지만, 화면이 `DuelRuleError` 를 잡아
`str(exc)` 를 그대로 그리는 자리가 여럿이고(`duel_page.py`) "실행되는 문자열에는 내부 문서 번호를 남기지 않는다" 는
규칙을 예외 없이 적용하는 편이 메타 테스트를 단순하게 만들어 함께 정리.

**"그래서 뭘 하면 되나" 안내 — 사실 확인 뒤 덧붙임.** 코드상 종가 없는 주문의 취소는 현금을 건드리지 않고
(`allocate_pending_orders()` `remaining_cash: cash`), 매도 취소는 포지션을 건드리지 않으며, 취소 주문은 이월되지 않음.
사용자가 원하면 다음 접수 시간대(KRW 18:00~22:00 / USD 16:00~21:00 KST)에 새 주문을 넣을 수 있음 — 주문 전 사전 고지
`duel_page.NOTICE_CRAWL_FAILURE(_USD)` 가 이미 "예수금은 그대로 계좌에 남으니, 다음 접수 시간대에 다시 주문하시면 됩니다"
라고 말하고 있어 같은 사실을 취소 사유에도 한 줄로 넣음("휴장일이거나 …" 류의 메타 설명·사무적 나열은 뺌). 지어낸 안심
문구 없음.

**재발 방지 — `tests/test_user_facing_wording.py` 신규(+60건).** `utils/`·`web/` 의 `.py` 전부(archive·`__pycache__`
제외)를 파일별 `parametrize` 로 펼쳐, 실행되는 문자열 리터럴 안에 "작업지시서" 가 남아 있으면 그 파일 이름·행·문장을
찍으며 실패(주석·docstring 은 허용 — 근거는 거기에 두라는 것이 정리 방향). 스캐너 자체 검증(f-string 은 잡고 주석·
docstring 은 놓아줌), 검사 대상이 비지 않았는지(§0-1), 오너가 지적한 매수·매도 취소 사유 두 문장이 "인용 없음 + 확정
종가/취소 + 예수금(보유 주식)은 그대로 + 다시 주문" 을 담는지까지. 수정 전 코드로 돌리면 `duel_rules.py`·`duel_batch.py`
파일별 검사 2건 + 문장 검사 1건 = 3건 실패 확인. 기존 `test_suite_integrity.py` 는 테스트 파일 자신의 구조만 보므로 이 검사와 겹치지 않음.

**검증.** 관련: `pytest -q tests/test_user_facing_wording.py tests/test_duel.py tests/test_duel_batch.py
tests/test_duel_batch_usd.py tests/test_suite_integrity.py` **379 passed / 73 skipped**. 전체 `pytest -q --ignore=archive`
**2,186 passed / 73 skipped**(#196 의 2,124 + 이후 커밋분 + 신규 60, 회귀 0; `--collect-only` 2,259건과 일치).

**하지 않은 것(§0-1).** (a) DB 에 이미 저장된 옛 `fail_reason`(8/28 캡처 문장 포함)은 소급 수정하지 않음 — 지나간
기록은 그때 문구 그대로 둠. (b) "§0-1" 같은 ENGINEERING_SPEC 절 번호는 이번 검사 대상이 아님(화면에 새어 나와 지적된 것은
"작업지시서 X-X-X" 였고, 실행 문자열에서 §번호가 확인된 곳도 없음). (c) `_freshness_reason()` 의 현재 문구("점검 대상 전부
전일과 동일(휴장 또는 수집 실패)")는 8/29 오너 확인분이라 손대지 않음.

### #198 — [실전 결함, #196-A 와 같은 계열] `/kr` 최상단 코스피/환율 카드가 컨테이너의 얼어붙은 로컬 `market_history.csv` 를 직접 읽음(`load_latest_kospi_usd` 원격 경로 누락) + 관리자 히스토리 Excel 다운로드도 로컬 직접 읽기 (2026-09-05)

#196 직후 별도 조사 에이전트가 저장소 전체를 "화면용 데이터를 로컬 고정 사본으로 읽는 문제"(원격 우선
`data_source.read_text()` 를 안 거치고 `open()`/`pd.read_*(경로)` 로 직접 읽어, 데이터만 새로 커밋되고 Render 가
재배포 안 될 때 화면이 하루 지연) 로 감사해 남긴 우선순위 1·2번을 이번에 고침. 3·4번(`macro_page._load_history_df`/
`fetch_verified_market_data` — `data_source.py` 에 "읽기·쓰기 짝을 맞추기 위해 의도적으로 제외" 로 문서화된 알려진
트레이드오프 + 개발 중단된 관리자 화면, `macro_ai.generate_macro_commentary` 의 날짜만 비교하는 캐시 스킵 — 영향 미미)
은 조사 에이전트 판단대로 백로그로 남김(손대지 않음).

**결함 1 (최우선) — `/kr` 최상단 "📈 코스피 지수 / 💵 원/달러 환율" 카드가 하루 늦음.**
- 원인: `web/pages/pegy_page.py::load_latest_kospi_usd()` 가 `pd.read_csv(HISTORY_FILE)` 로 저장소 루트의
  `market_history.csv` 를 **컨테이너 로컬에서 직접** 읽음. 같은 파일을 읽는 `utils/report_db.py::load_kospi_close_history()`
  (사장님 보고서 벤치마크)는 2026-08-17 [9] 마이그레이션 때 `data_source.read_text()` 로 옮겨졌고 `market_history.csv` 는
  `data_source._REMOTE_ROOT_FILES` 에 이미 등록돼 있었는데, **이 화면의 카드 함수만 누락**. #196-A(`read_history_rows`)와
  정확히 같은 유형이고, 노출 화면은 주력 공개 페이지 `/kr` 최상단이라 이쪽이 더 큼.
- 수정 (`web/pages/pegy_page.py`): `load_latest_kospi_usd(csv_path=None)` 가 `data_source.read_text(path,
  encoding="utf-8-sig")` 를 거쳐 받은 본문을 `pd.read_csv(io.StringIO(text))` 로 파싱. 뒤의 처리(COL_MAP 으로 한글 컬럼
  복원 → 마지막 행 → `{"kospi","usd","date"}` / 실패 시 None)는 예전과 글자 하나 다르지 않음. 원격 성공이면 원격 최신,
  실패+캐시면 마지막 성공분+전역 배너, 콜드스타트 실패면 로컬 사본+배너, 셋 다 없으면 None. `DATA_SOURCE_BASE_URL`
  미설정(기본값)이면 예전과 100% 동일한 로컬 읽기. 시그니처(동기)·반환 모양·`run_blocking(load_latest_kospi_usd)`
  호출 방식 그대로. `csv_path` 인자는 테스트용이며 `load_kospi_close_history(csv_path=None)` 와 같은 관례.
- 지시서는 `load_kospi_close_history()` 를 재사용하라고 했으나, 그 함수는 **코스피 종가 dict 만** 돌려주고 이 카드에
  필요한 **원/달러 환율이 없음**(파일 두 번 읽기·`report_db.py` 수정 모두 부적절). 그래서 그 함수가 쓰는 같은 원시 함수
  `data_source.read_text()` 를 그대로 씀 — #196-A 와 동일한 처방이며 새 구조를 만들지 않음(§0-3-10). docstring 에 경위 기록.

**결함 2 (낮은 우선순위) — 관리자 "📊 [관리자] 히스토리 다운로드 (Excel)" 버튼.**
- 원인: 람다가 `pd.read_json(history_path)` 로 `data/pegy_summary_history.json` 을 로컬 직접 읽기. 바로 위 일반 JSON
  다운로드 버튼은 `read_download_bytes()`(원격 우선)라 같은 화면의 두 버튼이 서로 다른 날짜의 파일을 내려줄 수 있었음.
- 수정: 람다 본문을 `_summary_history_csv_bytes(history_path)` 로 빼내고, `read_download_bytes()` 가 돌려주는 바이트를
  `pd.read_json(io.BytesIO(raw))` 에 넘김(뒤의 `to_csv(index=False).encode('utf-8-sig')` 동일). 못 읽으면 None →
  `download_button` 이 기존 `failure_text` 를 띄움. 원격 꺼짐일 때 실제 파일로 바이트 단위 동일 확인.
  `tests/test_event_loop_blocking.py::SYNC_CALL_ALLOWED` 에 새 함수 등록(사유: `_snapshot_csv_bytes` 와 같은 자리 —
  클릭 시 `run.io_bound`), `load_latest_kospi_usd` 항목 사유도 갱신.

**회귀 테스트 (`tests/test_data_source.py::test_load_latest_kospi_usd_goes_through_data_source`, [9-c]).** [9-b] #196-A
와 대칭 — ⓪ 기본 인자로 저장소의 실제 `market_history.csv` 를 읽어 세 키 반환, ① 원격 꺼짐(로컬 마지막 행·BOM 처리·
네트워크 0회·배너 없음·없는 파일/컬럼 없음/마지막 행 빈값/빈 파일 → None), ② 원격 성공 → 09-04 행(얼어붙은 사본의
09-03 아님) + TTL 안 재호출은 네트워크 없이 캐시, ③ TTL 뒤 원격 실패+캐시 → 마지막 성공분 + 배너 대상, ④ 콜드스타트
실패 → 로컬 사본 + `local_fallback` 배너, ⑤ 셋 다 없음 → None, ⑥ 관리자 히스토리 CSV(원격 꺼짐이면 예전 방식과 바이트
동일·없는 파일 None·원격 성공이면 원격 최신 행 포함), ⑦ 소스 수준(`data_source.read_text` 사용, `pd.read_csv(HISTORY_FILE)`
/`pd.read_json(history_path)` 부활 금지, `run_blocking(load_latest_kospi_usd)` 유지, 함수 본문에 `open()` 없음).
`main()` 수동 호출 목록에도 추가(#168 H-3).

**검증.** 관련: `pytest -q tests/test_data_source.py tests/test_event_loop_blocking.py tests/test_pegy_page.py` **55 passed**.
전체 `pytest -q --ignore=archive` **2,187 passed / 73 skipped**(#197 의 2,186 + 신규 1, 회귀 0; `--collect-only`
2,260건과 일치).

**하지 않은 것(§0-1).** (a) 위 백로그 3·4번. (b) `utils/report_db.py::load_kospi_close_history()` 는 한 글자도
바꾸지 않음(다른 화면이 검증된 채로 쓰는 중). (c) 실제 raw.githubusercontent.com 왕복은 여전히 오프라인 검증 밖 —
배포 후 `/kr` 최상단 카드의 "(YYYY-MM-DD 장마감 기준)" 날짜가 `market_history.csv` 마지막 행과 같은지 오너 확인 필요.

## 진행 예정 (백로그)

- ✅ #177 `scorecard_leaderboard_page()` "발행분 있음" 렌더 스모크 → #181에서 완료(2026-08-30). §0-1 재검토 결과 `test_scorecard_public_ui.py::_leaderboard_client()`가 이미 쓰던 합성 픽스처 관례를 그대로 재사용하면 위반이 아님을 확인, 진입점 ④ 분기로 위/아래 두 구간 배선까지 실제 실행 확인.
- ✅ **#175 SPEC §5-1 2중 Cap 코스피 미구현 → #176에서 수정 완료(2026-08-30).**
  `collector_kospi200.py`의 Forward `g_eff`(→f_pegy·목표주가)에 성장률
  35%p·주주환원 10%p·총합 40%p 캡을 반영. 실데이터 236종목 중 캡이 걸리는
  종목 79개, PEGY 밴드가 실제로 바뀌는 종목 14개(최초 추정 17개는 부정확했음
  — #176에서 재검증한 정확한 수치). Trailing(t_pegy/t_fair)은 SPEC 설계상
  그대로 무캡 유지. 자세한 내용은 TASK_HISTORY #176 참고.
- ✅ #176 코스피 페이지(`pegy_page.py`) g_eff 캡 투명성 배지 → #179에서 추가
  완료(2026-08-30). "예상 성장률" 옆에 미국 페이지와 동일한 "🧮 상한 적용값"
  배지, 옛 스냅샷(필드 없음)에서도 조용히 생략됨을 확인.
- ✅ #175 `format_amount()` NaN/무한대 방어 → #179에서 추가 완료(2026-08-30).
  직접 재현해보니 원화 경로는 실제로 `ValueError`(math.floor(nan))로 크래시함을
  확인 — "재현 안 됨"이 아니라 아직 안 겪었을 뿐이었음. 값 없음과 동일하게 "—".
- ✅ #175 `ENGINEERING_SPEC.md` §5-4 표 → #178에서 갱신 완료(2026-08-30). 예전
  "고정 점수 하드컷오프" 서술이 2026-08-06 개편(z-score/윈저라이즈 기반 %대 캡)
  이후로도 안 고쳐진 채 방치돼 있었음 — `utils/guardrail.py`·`utils/scoring.py`를
  직접 재확인해 3단으로(종목 차단/배지만/점수 캡) 다시 정리. 코드 변경 없음.
- 🆕 #175 역성장 종목(`g_eff<=0`)은 배당 미수집 배지를 못 받음(`guardrail.py` 조기
  return) — 현재 실데이터로 두 조건이 안 겹쳐 안 보이지만 구조적 갭.
- ✅ #175 `utils/data_validator.py` 커버리지 50% → #178에서 100%로 보강 완료
  (2026-08-30). ②단계 `sanity_check_per`·③단계 `cross_reconcile`은 지금까지
  단 한 번도 직접 테스트된 적이 없었음(기존 유일한 관련 테스트는 ①단계 한
  갈래만 간접적으로 지나감). `tests/test_data_validator.py` 신규 29건.
- ✅ `duel_daily.yml`의 `workflow_run` 트리거(#150) 실동작 — 2026-08-26
  workflow_dispatch(#37→#5, event≠schedule이라 정상 skip)와 2026-08-27 지연된
  실제 schedule 실행(#38→duel_daily.yml #7, event=schedule로 정상 실행·성공)
  두 케이스 모두로 의도대로 동작함을 실전 로그로 확인 완료.
- ✅ #153 EV/EBITDA 서킷브레이커 — 2026-08-27 실전 실행(#38) 로그에서 서킷브레이커
  로그 라인이 연속 8회 실패 직후 정확히 1회 출력되고 이후 EV/EBITDA 요청이 전혀
  없음을 확인. 핵심 수집 시간도 57분(03:14→04:11 KST)으로 실측 — 수정 전 2시간
  7분 대비 큰 폭 개선을 로그로 직접 검증 완료.
- ✅ #154 `watch_schedule_health.yml` 워치독 → #182(핵심 판정 로직 테스트 21건) +
  #183(오너 실전 확인 중 발견한 JSON 이어붙기 버그 수정)을 거쳐, 2026-08-30 오너가
  `test/watchdog-issue-check` 브랜치(`test_suite.yml`을 임시 감시 대상으로 지정)로
  `workflow_dispatch` 재실행 → 판정·이슈 생성(issues/1)·디스코드 알림·assignee
  이메일까지 **실전 전 구간 정상 동작 최종 확인 완료**(이메일은 처음엔 안 보였지만
  GitHub 쪽 발송 지연이었을 뿐 결국 정상 수신됨 — 코드 문제 아니었음). 이걸로 이
  워치독은 코드·실전 양쪽 다 검증 끝. 테스트 브랜치는 확인 후 삭제.
- GitHub Actions schedule 트리거 자체의 지연·누락(2026-08-27·28·31, scrape.yml·
  indicator_kr.yml 등 여러 워크플로우에서 반복 관측)의 근본 원인은 여전히
  미확인 — GitHub 쪽 스케줄러 인프라 문제로 추정되나 저장소 설정으로 원인을
  특정하거나 고칠 수 있는 부분이 아님(§0-1). ✅ 2026-08-31 **#184**에서
  워치독에 자동 재실행(self-healing) 기능을 추가해, 오너가 외출 등으로 컴퓨터를
  못 만지는 상황에서도 "누락 감지 즉시 1회 자동 재시도"까지는 되도록 완화함
  ("감시의 감시"가 되지 않도록 재시도 성공 여부를 별도로 재검증하는 레이어는
  의도적으로 안 만들었고, 진짜 외부 사이트 구조 변경으로 인한 실패는 이 워치독이
  아니라 `data_sanity.py` 쪽 책임으로 범위를 명확히 분리함).
  ✅ **자동 재실행 API 호출 자체의 실전 동작도 같은 날 확인 완료.** 처음엔
  `test_suite.yml`을 임시 대상으로 쓰려 했으나 이 파일은 `push: branches:[main]`
  트리거가 있어 #184를 main에 push한 시점에 이미 진짜 성공 실행이 하나 생겨버려
  "항상 누락" 상태를 만들 수 없었음(버그가 아니라 event 필터를 뺀 #184가
  의도대로 그 성공도 인정한 것) — 그래서 `workflow_dispatch` 외 트리거가 전혀
  없는 완전히 무해한 임시 프로브 워크플로우(`_watchdog_retry_probe.yml`, echo만
  하고 끝)를 새로 만들어 main에 잠깐 올리고 그걸 감시 대상으로 재실행. 그 과정에서
  프로브 자체의 진짜 YAML 버그도 하나 발견(`run: echo "...#184..."`처럼 한 줄로
  쓰면 YAML이 공백 뒤 `#`를 주석 시작으로 해석해 echo 문 뒷부분이 통째로 잘려나가
  닫는 따옴표 없이 끝남 — `run: |` 블록 스타일로 수정, 실전 프로덕션 스크립트는
  전부 블록 스타일이라 이 문제와 무관). 수정 후 재실행 → 워치독이 `누락` 판정 →
  이슈(issues/3)·디스코드 알림 정상 생성 → 그 직후 프로브 워크플로우가
  **`Manually run by github-actions[bot]`으로(오너가 아니라 워치독 자신이 건 것)**
  자동 실행되어 성공까지, 오너가 GitHub Actions 화면에서 직접 스크린샷으로 확인.
  판정→자동 dispatch→실제 재실행 성공 전 구간이 실전으로 검증됨. 테스트 브랜치·
  프로브 워크플로우·테스트 이슈는 확인 후 정리. #154 워치독은 여전히 "원인 제거"가
  아니라 "재발 시 놓치지 않고 알아채고, 가능하면 스스로 한 번 고쳐보기" 용도임을
  오너도 인지하고 있음.
  ⚠️→✅ **바로 다음 날(2026-09-01) #184 자체의 설계 허점이 실전에서 발견돼
  #185에서 수정됨** — 자동 재실행이 하필 장중(워치독 cron이 09:00 KST였음)에
  걸리면, 백필 기능이 없는 핵심 수집기(`collector_kospi200.py`·
  `collector_indicator_kr.py`)가 장중 실시간 가격을 그날 종가인 것처럼 저장할
  수 있었음. 워치독 cron을 18:00 KST(장 마감 후)로 옮기고, 재실행 직전 "지금
  장중인가"를 한 번 더 확인해 장중이면 건너뛰는 이중 안전장치로 수정. 상세는
  TASK_HISTORY #185 참고.
- `tests/test_scorecard.py`(약 1464·1469행), `tests/test_duel_page_usd.py`(약
  1749행)에 남아있는 "코스피 상위 200" 표현 — 테스트 정확성에는 영향 없는 순수
  코멘트/독스트링이라 #151에서는 보류. 정리하고 싶으면 언제든 요청.
- 회원탈퇴(계정 삭제) 셀프서비스 기능 신설 여부 — 오너가 2026-08-25 판단 보류
  ("유지보수 차원의 문제는 계속 관리하면서 봐야 하는 거라 지금 결론은 못 내리겠다").
  지금은 `/privacy` 문서에 "메일로 요청받아 처리"라고 정직하게 적어둔 상태(#149).
- 애드센스 좌/우/인피드 슬롯ID(`ADS_SLOT_ID_LEFT`/`_RIGHT`/`_INFEED`) — 오너가
  Render 환경변수에 입력하기로 함(2026-08-25). 코드는 이미 배포됨(#148) — 값만
  채우면 그 자리가 바로 켜짐.
- 애드센스 사이트 심사 결과 대기 중(2026-08-25 검토 요청). 승인되면 관리자 화면에서
  자리 4개가 실제로 잘 뜨는지 확인 후 `web/ads.py`의 `ADS_ADMIN_ONLY`를 `False`로
  바꿔 3단계(전체 공개) 전환.

- ✅ #156 컷오버 유예 만료 → #160(2026-08-29)에서 예정보다 이틀 앞당겨 완전히
  실행 완료. `app.py`/`visiblehand.py`/`views/`는 `archive/`로 이동,
  `keep_awake_ping.py`·`index.html`·`.github/workflows/keep_awake.yml`은
  삭제, `requirements.txt`에서 streamlit·altair 제거까지 확인됨(2026-08-30
  재확인 — `ls app.py visiblehand.py views/` 전부 없음, `archive/`에 이동
  확인). 이 항목이 그동안 완료 처리가 안 된 채 백로그에 남아있던 것 자체가
  #172/#173 같은 부류의 문서 동기화 누락이었음 — 뒤늦게 바로잡음.
- ✅ #156 `tests/conftest.py` 부재 → #180에서 완료(2026-08-30). 9개 파일
  (`test_data_source`·`test_macro_scoring`·`test_pegy_page`·`test_report`·
  `test_scorecard`·`test_stock_history`·`test_us_stocks`·`test_us_stocks_page`·
  `test_web_session_isolation`)의 FAILURES/check()/autouse 하네스 중복을 공용
  `tests/conftest.py`로 제거. `test_us_scoring.py`는 `FAILURES.clear()` 설계
  충돌로 의도적으로 제외, 자기 파일 하네스 유지. 경고(#169)대로 같은 변경에서
  `test_suite_integrity.py` Check A도 함께 갱신(실제 `import conftest` +
  `request.fixturenames` 확인으로 강화)해 조용한 무력화 위험을 실현 전에 차단—
  갱신 전 상태로 먼저 재현해 위험이 실재함도 확인했음. 사보타주 5종(오푸스) +
  독립 재현 2종(직접) 전부 정확히 잡힘, git-stash 베이스라인 대비 FAILED/ERROR/
  SKIPPED ID 2,106개 완전 일치, 전체 스위트 2041 passed/65 skipped, 회귀 0건.
- ✅ #168 M-1 `.count("문자열") == N` 브리틀 단언 → 2026-08-30 직접 표본 재검토
  완료, **코드 변경 없음**. `test_duel.py`(SEED_AMOUNT_KRW 등 정의 1곳),
  `test_duel_batch.py`(open() 정확히 2곳), `test_duel_scorecard_summary_card.py`
  (카드 폭 스타일 정확히 2곳) 등 표본을 직접 열어보니 전부 §0-3-10(단일 출처)
  또는 명시적 설계 의도가 주석으로 근거까지 남아있는 의도적 정확-개수 검사였음 —
  무해한 리팩터로 깨질 브리틀 케이스를 찾지 못함. `>=`/`in`으로 바꾸면 오히려
  실제 중복 방지 효과가 있는 검사를 약화시킬 위험이 있어 그대로 둠.
- ✅ `test_duel.py` 통화 표기 통일성 2건 — #171(2026-08-30)에서 반영 완료.
(그 밖의 백로그 항목은 `PROJECT_STATUS.md`의 "지금 열려있는 일" 참고)

---

> 이후 완료되는 작업은 이 문서 "완료된 작업" 목록 맨 아래에 번호를 이어서 추가해주세요.
> 파일이 다시 눈에 띄게 무거워지면 `ENGINEERING_SPEC.md` §0-3-14의 절차대로
> 오래된 구간을 아카이브로 옮기세요(항목 분량은 절대 줄이지 않습니다).
