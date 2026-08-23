# 🏆 "내 밑으로 눈 깔어" — "내 성적표" 공개 순위표 작업지시서

> 이 문서는 `DUEL_MODULE_WORK_ORDER.md` §5-20(2026-08-23 정정)에서 갈라져 나온 신규 문서입니다.
> 원래 이 공개 순위표는 결투 가상계좌("덤벼라 나 자신") 성적을 공개하는 것으로 설계·구현·전체
> 공개 전환까지 끝났었는데, 오너가 실사용 중 순위표 상단 고정 문구("실제로 공개되어있는
> '내 성적표'의 데이터는…")와 실제 구현(가상계좌 성적 공개)이 어긋나 있음을 짚어냈고, 그
> 문구가 처음부터(2026-08-19 원본 지시서) 그렇게 적혀 있었다는 것이 확인되면서, **공개 대상
> 자체를 "내 성적표"(실제 보유 자산)로 전면 전환하기로 오너가 확정**했습니다(2026-08-23).
> 경위의 전체 서술·증거는 `DUEL_MODULE_WORK_ORDER.md` §5-20을 보세요 — 여기서는 되풀이하지
> 않고, **이 신규 모듈 자체의 설계·구현·검증만** 다룹니다.

## 한 줄 요약

로그인한 사용자가 자신의 **"내 성적표"**(`holdings` 표에 직접 등록한 실제 보유 자산)를
공개 동의하면, 매일 밤 배치가 통화(원화/달러) × 체급(매입원가 구간)별로 순위표를 만들어
발행합니다. 순위는 매입원가 대비 수익률로 매기고, 참가자가 500명 미만인 그룹은 아예
발행하지 않습니다.

## `/duel`(결투 가상계좌)과의 관계 — 가장 먼저 읽어야 하는 절

**이 모듈은 결투 가상계좌 트레이딩 기능(`/duel`)과 완전히 무관합니다.** `duel_page.py`,
`duel_accounts`/`duel_orders`/`duel_positions`/`duel_cash_ledger` 원본 표, 야간 정산 배치는
이번 전환에서 **한 글자도 건드리지 않았고**, `/duel`은 "나와의 결투"라는 원래 목적(내 실제
투자 방식과 다른 모의투자를 스스로 비교) 그대로 개인 연습 도구로 계속 운영됩니다. 이 문서가
다루는 것은 오직 **"공개 동의 + 공개 순위표" 계층**이고, 그 계층이 읽는 데이터가 결투
가상계좌에서 "내 성적표"로 바뀐 것뿐입니다.

`utils/duel_rules.py`의 **통화·계좌와 무관한 순수 규칙 함수**(체급 판정, 최소 인원, 시즌
계산, 순위 매기기, 재동의 차단 등)는 그대로 import해서 재사용합니다 — 사본을 새로 만들지
않았습니다(§0-3-10). 아래에서 "재사용"이라고 표시된 것은 전부 이 원칙입니다.

## 재사용 vs 신규 — 한눈에 보는 표

| 결투(참고용, 손대지 않음) | 새 모듈 |
|---|---|
| `duel_public_consent`(계좌별) | `scorecard_public_consent`(**사용자당 1행** — 계좌 개념 없음) |
| `duel_nicknames`(user_id, window_type) | `scorecard_nicknames`(**user_id만** — 창유형 없음) |
| `duel_bracket_assignments`(account_id, season_key) | `scorecard_bracket_assignments`(**user_id, currency, season_key**) |
| `duel_public_leaderboard`/`_holdings`(window_type 축) | `scorecard_public_leaderboard`/`_holdings`(**currency 축만**) |
| `utils/duel_db.py` 동의·닉네임·발행 CRUD | `utils/scorecard_publish_db.py`(신규) |
| `utils/duel_publish.py` 배치 오케스트레이션 | `utils/scorecard_publish.py`(신규) |
| `run_duel_publish_batch.py` + workflow | `run_scorecard_publish_batch.py` + `.github/workflows/scorecard_publish_daily.yml`(신규, 독립 cron) |
| `web/pages/duel_consent_page.py` | `web/pages/scorecard_consent_page.py`(신규, 계좌 루프 없음) |
| `web/pages/duel_leaderboard_page.py` | `web/pages/scorecard_leaderboard_page.py`(신규) |

**그대로 import 재사용**(새로 만들지 않음): `duel_rules.DuelRuleError`, `BRACKET_TIERS`/
`BRACKET_KEYS`/`BRACKET_NONE_KEY`/`BRACKET_NONE_LABEL`/`assign_bracket()`/`bracket_label()`(원화
8구간), `BRACKET_TIERS_USD`/`BRACKET_KEYS_USD`/`assign_bracket_usd()`/`bracket_label_usd()`(달러
대응), `resolve_bracket_for_season()`/`resolve_bracket_for_season_usd()`,
`season_key_for_date()`(매년 3월 1일 시작, 12개월 시즌), `MIN_PARTICIPANTS_FOR_PUBLICATION`
(=500)/`group_meets_minimum()`, `rank_participants()`(⚠️ 입력 dict 키가 내부적으로 `"twr_pct"`로
고정돼 있음 — 새 코드도 이 리터럴 키로 넘겨야 하며, DB 컬럼/최종 payload 키는 `return_pct`로
바꿔서 저장), `RECONSENT_BLOCK_MONTHS`(=3)/`resolve_reconsent_block()`,
`LEADERBOARD_TOP_COUNT`/`LEADERBOARD_BOTTOM_COUNT`/`leaderboard_page_bounds()`/
`leaderboard_page_count()`. `utils/duel_db.py`의 `FORBIDDEN_PUBLISH_FIELDS`/
`_assert_no_identity_fields()`도 계좌·통화 무관 범용 가드라 그대로 재사용. `duel_set_updated_at()`
트리거 함수(범용)도 그대로 재사용.

**새로 만든 것은 딱 하나의 순수 함수**: `resolve_portfolio_return_pct(currency_summary)` —
`total_profit / total_cost_priced * 100.0`, 분모가 `None`이거나 `0` 이하면 결과도 `None`(0%로
위장하지 않음, §0-1). `evaluate_holding()`의 종목 단위 규칙을 포트폴리오 단위로 올린 것입니다.
`resolve_bracket_cost_basis(currency_summary)`도 신규이지만 로직 자체는 결투의
`summarize_real_principal()`과 동일 — 체급 입력은 **가격 유무와 무관하게 무조건 합산한
`total_cost`**를 씁니다(오늘 시세 커버리지에 따라 체급이 흔들리면 안 되므로).

## 동의 항목 — 5개 + 최종 확인, 6번째 독립 동의는 없음

결투의 6번째 독립 동의(`consent_real_principal_bracket` — "실제 매입총합을 체급 산정에
사용")는 "이 모듈이 아닌 **다른 모듈**('내 성적표')의 실제 자산 데이터를 끌어다 쓴다"는
이유로 분리돼 있었습니다. 이 모듈에서는 **공개되는 데이터 자체가 이미 "내 성적표"**이므로,
5개 항목(순위·수익률·보유종목·수량·매입금액)에 전부 동의하는 순간 매입원가합계는 이미 공개된
값들의 단순 합으로 누구나 재구성 가능합니다 — 별도로 게이트를 세울 대상이 남아 있지 않습니다.
그래서 `scorecard_public_consent`에는 5개 boolean + `final_confirmed`만 있고, DB CHECK
제약(`scorecard_consent_final_requires_all`)도 5개 기준입니다. 나머지 동의 UX 규칙은 결투와
동일: 5개 전부 아니면 전무, 별도 최종 확인 단계, 재동의 3개월 대기, 철회는 필드 업데이트(행
삭제 아님, 발행 기록만 실제로 지움).

동의 항목 5문장(화면·DB 키가 반드시 같은 순서로 일치 — `scorecard_consent_page.py::
consent_item_rows()`가 매번 이 사실을 확인하고 어긋나면 예외):

1. **순위** — 내 성적표의 순위가 공개 순위표에 표시됩니다.
2. **수익률** — 내 성적표의 수익률이 공개됩니다.
3. **보유종목** — 내가 실제로 보유한 종목이 순위표에서 다른 사람에게 개별 열람 가능하게
   공개됩니다("개별 열람"은 오너가 명시적으로 요구한 문구 요소).
4. **수량** — 종목별로 내가 실제 보유한 수량이 공개됩니다.
5. **매입금액** — 종목별로 내가 실제 매입한 금액이 공개됩니다.

## 그룹 기준 — 체급(원금 구간)만, 통화별로 완전히 분리

"내 성적표"에는 결투의 M1/M3/M6 같은 창유형 구분이 없으므로, 새 순위표는 **체급으로만**
나눕니다(오너 확정: "내 밑으로 눈 깔어에서 구분하고 있는 체급만으로 구분하면 돼"). 원화
보유분과 달러 보유분은 이 앱에 환율 시계열이 없어(`scorecard_db.NO_FX_CONVERSION_NOTICE`)
절대 합산·비교하지 않고, 체급도 통화별로 완전히 따로 매깁니다 — 그룹은 `(currency,
bracket_key)` 쌍이고 총 18개(원화 9개 체급 키 × 1, 달러 9개 체급 키 × 1)가 가능합니다.

닉네임은 **사람당 하나**(통화별로 나눠 배정하지 않음) — 국내·미국 종목을 둘 다 공개하면
원화·달러 순위표 양쪽에 같은 닉네임이 실려 "이 두 줄은 같은 사람"임을 알 수 있게 하지만, 두
줄의 성적을 더하거나 비교하지는 않습니다. 공개 동의 자체도 **사용자당 하나의 결정**이라
통화별로 따로 동의하거나 한쪽만 철회할 수 없습니다.

## 수익률 계산 — "내 성적표"가 이미 쓰는 방식 그대로 (TWR 아님)

결투는 일별 스냅샷으로 시간가중수익률(TWR)을 계산했지만, "내 성적표"에는 그런 시계열이
없습니다(오너 확정: "'내 성적표'가 이미 쓰는 방식 그대로"). 여기 실리는 값은
`evaluate_holding()`이 이미 쓰는 규칙(매입원가 대비 (평가금액−매입원가)÷매입원가)을
포트폴리오 단위로 올린 `resolve_portfolio_return_pct()`의 결과입니다. 가격을 확인하지 못한
종목은 분자·분모 양쪽에서 함께 빠지므로, 어떤 참가자의 수익률은 보유 전부를 반영한 값이
아닐 수 있습니다 — 화면(`NOTICE_HOW_RANKING_WORKS`)이 이 사실을 그대로 밝힙니다.

## 스키마 (`sql/scorecard_public_schema.sql`) — 🔴 오너가 아직 Supabase에 실행하지 않음

**§1 DROP**: 결투 공개 계층의 원화 5종(`duel_public_consent`/`duel_public_leaderboard`/
`duel_public_holdings`/`duel_bracket_assignments`/`duel_nicknames`) + USD 대응 4종 + 이제
쓰이지 않는 `duel_consent_guard()` 함수. `duel_accounts`/`duel_orders`/`duel_positions`/
`duel_cash_ledger`는 **절대 포함하지 않음**. (아직 500명 문턱을 넘어 실제로 노출된 적이
없으므로 — 오너 본인 테스트 동의 1건이 전부 — 데이터 유실 걱정 없이 지워도 되는 상태입니다.)

**§2 CREATE** (5개 표):
- `scorecard_nicknames(user_id PK, nickname unique not null, created_at)`
- `scorecard_public_consent(user_id PK, consent_rank/return/holdings/quantity/buy_amount
  boolean, final_confirmed, final_confirmed_at, revoked_at, created_at, updated_at)` + 3개
  CHECK(전부-아니면-전무 재확인 · final_confirmed_at 짝 · 철회 시 final_confirmed 아님) +
  `scorecard_consent_guard()` 트리거(철회 이력 되돌리기 금지, `duel_consent_guard()`와 동일
  로직의 user_id 버전).
- `scorecard_bracket_assignments(user_id, currency, season_key, bracket_key, assigned_at,
  PK(user_id, currency, season_key))` — update/delete 권한을 아무에게도 주지 않아 "한 번
  정해진 체급은 시즌 끝까지 불변"을 DB 레벨에서 강제.
- `scorecard_public_leaderboard(id, published_date, currency, bracket_key, rank, nickname,
  return_pct, created_at, unique(published_date, currency, bracket_key, nickname))` —
  동점자가 실제로 생길 수 있어 유니크 키는 rank가 아니라 nickname 기준.
- `scorecard_public_holdings(id, published_date, currency, nickname, ticker, stock_name,
  quantity, buy_amount, created_at, unique(published_date, currency, nickname, ticker))`.

**§3 RLS**: 계좌 소유 확인 헬퍼(`duel_account_is_mine()`) 대신 **직접 `auth.uid() =
user_id`**로 단순화(계좌 레이어가 없어 security-definer 헬퍼가 필요 없음). 발행 두 표는
`select`는 `authenticated`에게 `using(true)`, `insert/update/delete`는 `service_role`만.
`holdings`(내 성적표 원본) 표는 **스키마·RLS 변경 없음** — 배치가 읽을 때도 service_role
클라이언트로 `user_id in (...)` 필터를 명시적으로 걸어서 읽습니다.

## 화면

- **`/scorecard/consent`**(`web/pages/scorecard_consent_page.py`, 743줄) — 카드 한 장(계좌
  루프 없음). 결투 화면에 있던 `_consent_section()` 팩토리(루프 안 `@ui.refreshable`이
  마지막 반복 객체로 풀리는 문제를 피하려던 장치)는 반복 자체가 없어 필요 없으므로 통째로
  들어냄. 문구는 전부 "가상계좌"가 아니라 "실제 보유 자산" 기준으로 다시 씀. 책임 고지
  문구(§0-1, 결투 확정 문안)는 모듈과 무관하게 성립하는 문장이라 글자 그대로 재사용.
- **`/scorecard/leaderboard`**(`web/pages/scorecard_leaderboard_page.py`, 721줄) — 창유형
  선택기 없음(통화·체급만). `twr_display()` → `return_display()`로 개명(더 이상 TWR이
  아니므로). **맨 위 고정 문구 2문단은 결투 순위표에서 글자 하나 안 건드리고 그대로 가져옴**
  — 이번 전환 덕분에 그 문구가 **처음으로 실제 구현과 일치**하게 됨.
- 게이팅은 결투와 같은 2단계 패턴: `SCORECARD_CONSENT_ENABLED`/`SCORECARD_LEADERBOARD_ENABLED`
  (Render 환경변수, 기본 꺼짐) + `SCORECARD_CONSENT_MENU_ADMIN_ONLY`/
  `SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY`(코드 상수, **둘 다 `True`로 시작** — 관리자 전용).
  `DUEL_ENABLED`는 참조하지 않음("내 성적표"는 결투 스위치와 무관한 별개 데이터).

## 🔐 XSS 방어 (§0-3-9) — `stock_name`은 사용자 자유 입력값

`holdings.stock_name`은 사용자가 직접 입력하는 값이라 `<img src=x onerror=...>` 같은
문자열이 저장될 수 있습니다(`scorecard_page.py`가 이미 문서화한 위험과 동일). 렌더링하는
모든 자리는 예외 없이 `esc()`를 거칩니다:
- `scorecard_consent_page.py` 551행(닉네임)·567행(최종 확인 시각)·569행(철회 시각).
- `scorecard_leaderboard_page.py` 357-360행(종목명·종목코드, `holding_row_cells()`)·545행
  (트랙 제목·체급 라벨)·632행(참가자 닉네임).
- `ui.html()` 호출은 파일 전체에서 **692행 단 한 곳**뿐이고, 그 입력(`holdings_table()` →
  `holding_row_cells()`)은 전부 위 `esc()`를 거친 뒤에야 도달합니다.

**직접 실행해 확인**: `holding_row_cells({'ticker': '005930', 'stock_name': '<img src=x
onerror=alert(1)>', ...})`를 호출한 결과와 `holdings_table()`이 만든 최종 HTML 양쪽에서
`<img`가 이스케이프된 `&lt;img …&gt;`로만 나타나고 raw `<img onerror`는 어디에도 없음을
확인했습니다(2026-08-23, AI가 직접 실행 — 서브에이전트 보고를 그대로 믿지 않음).

## 구현 이력

- **Phase 0(스키마)** — `sql/scorecard_public_schema.sql` 작성 완료. **오너가 Supabase SQL
  Editor에서 아직 실행하지 않음** — 실행 전까지 아래 Python/화면 코드는 실제 데이터에 대해
  동작하지 않습니다.
- **Phase A(규칙·DB·배치 계층, 2026-08-23, 오푸스 서브에이전트 + AI 직접 재검증)** —
  `utils/scorecard_publish.py`(858줄)·`utils/scorecard_publish_db.py`(1053줄)·
  `run_scorecard_publish_batch.py`(135줄)·`.github/workflows/scorecard_publish_daily.yml`
  (138줄, cron `30 22 * * *` = 매일 07:30 KST)·`tests/test_scorecard_publish.py`(1516줄,
  132개 전부 통과). AI가 직접 실행해 확인한 것: `resolve_portfolio_return_pct()`가
  `total_cost_priced`를 분모로 쓰는지(20% vs `total_cost`를 썼을 때의 16.67%로 실제
  구별됨), `resolve_bracket_cost_basis()`가 무조건 합계를 쓰는지, `all_possible_groups()`가
  정확히 18개를 반환하는지, `leaderboard_payload()`/`holdings_payload()`가 입력에 `user_id`/
  `id`가 섞여 있어도 제거하는지.
- **Phase B(화면 층, 2026-08-23, 오푸스 서브에이전트 + AI 직접 재검증)** —
  `web/pages/scorecard_consent_page.py`·`web/pages/scorecard_leaderboard_page.py`(신규),
  `web/layout.py`·`main.py`(교체 배선), `web/pages/duel_consent_page.py`·
  `web/pages/duel_leaderboard_page.py` 삭제, `tests/test_duel_consent_page_usd.py`·
  `tests/test_duel_leaderboard_page_usd.py` 삭제(더 이상 존재하지 않는 모듈을 import하고
  있었으므로), `tests/test_duel_public_ui.py` 트리밍(1047→447줄, 은퇴 확인 테스트 3개
  신규), `tests/test_web_session_isolation.py`의 `ALLOWED_MUTABLE_GLOBALS` 갱신, 신규
  `tests/test_scorecard_public_ui.py`(1152줄, 48개).

### 검증 (AI가 서브에이전트 보고와 별개로 직접 재실행·재확인, 2026-08-23)

1. `python -m py_compile` — Phase A·B 신규/변경 파일 전부 클린.
2. `pytest tests/test_scorecard_public_ui.py -q` → **48개 전부 통과**(서브에이전트 보고와 일치).
3. `pytest tests/ -k duel -q` → **886 passed, 365 deselected, 오류 0**(서브에이전트 보고와
   일치 — 은퇴 전 기준선 1006 통과에서, 삭제된 화면·테스트 파일 분량만큼 정확히 줄어듦).
4. 저장소 **전체 스위트** → **2 failed, 1249 passed, 3 errors** — 실패·오류 5건 전부 이
   전환과 무관한, 세션 순서에 따라 흔들리는 기존 NiceGUI 전역 슬롯스택 문제
   (`test_upload_widget_is_really_not_rendered_when_flag_is_off`·`test_macro_render_smoke`·
   `test_render_smoke`·`test_report_render_smoke`·`test_duel_render_smoke`)이고, 이번 전환이
   만든 새 실패는 0건.
5. 두 화면 파일을 직접 읽어 `esc()` 자리·문구·구조를 확인 — 6번째 동의 항목·window_type
   축이 실제로 없음을 grep으로 재확인, `ui.html()` 호출이 파일당 1곳뿐임을 확인.
6. 위 "XSS 방어" 절의 악성 `stock_name` 직접 실행 확인.
7. `web/layout.py`에서 `DUEL_ENABLED`/`DUEL_MENU_ADMIN_ONLY`가 이 전환으로 값이 바뀌지
   않았음을 확인(`/duel`은 이미 전체 공개 상태 그대로).
8. 저장소 전체에서 `duel_consent_page`/`duel_leaderboard_page` 문자열을 grep — 남은 자리는
   전부 주석(경위 설명)이거나 "삭제됐음을 확인하는 테스트 코드"뿐이고, 실제 import·호출은
   0건.

## 아직 안 끝난 것

1. **Phase 0 실행** — 오너가 Supabase SQL Editor에서 `sql/scorecard_public_schema.sql`을
   직접 실행(DROP 5+4종 + CREATE 5종). 이게 끝나야 아래 코드가 실제 데이터에 대해 동작합니다.
2. **Render 환경변수** — `SCORECARD_CONSENT_ENABLED`/`SCORECARD_LEADERBOARD_ENABLED`를
   오너가 직접 설정(기본 꺼짐 — 결투 때와 같은 절차, Render 대시보드에서만 가능).
3. **`.github/workflows/scorecard_publish_daily.yml` 반영** — `device_commit_files`가
   `.github/workflows/` 경로를 막으므로, 결투 USD 트랙 워크플로우 파일들을 전달했던 것과
   같은 대체 방식(오너 컴퓨터에 직접 쓰기 등)이 필요합니다. 파일 내용 자체는 완성돼 있고
   YAML 파싱까지 확인했습니다.
4. **6단계(실검증)** — 이 새 모듈에 대해 처음부터: 성적표 등록 → 5개 동의 + 최종 확인 →
   (배치를 dry-run/직접 실행으로 앞당겨) → 순위표에서 본인 닉네임 확인 → 철회 → 순위표에서
   사라짐 확인. Supabase SQL Editor에서 부분 유니크 인덱스·RLS 정책·트리거도 수동 확인.
5. **git 반영** — 삭제된 파일(`web/pages/duel_consent_page.py`·
   `web/pages/duel_leaderboard_page.py`·`tests/test_duel_consent_page_usd.py`·
   `tests/test_duel_leaderboard_page_usd.py`)을 `git add -A`(또는 `git rm`)로 새 파일과
   함께 커밋해야 합니다 — 새 파일만 add하면 저장소에 죽은 코드가 남습니다.
6. 초기 배포는 관리자 전용으로 열고, 오너가 직접 눈으로 확인 후 결투 때와 같은 절차(코드
   상수 `MENU_ADMIN_ONLY`를 `True → False` 한 글자만 바꾸는 3단계 공개 전환)를 따릅니다.

## 다음에 이 문서를 다시 열 때

**2026-08-23 기준 진행 상황**: Phase 0(SQL 작성) ✅ 완료(오너 미실행) · Phase A(규칙·DB·배치)
✅ 완료·AI 직접 재검증 완료 · Phase B(화면·배선·삭제) ✅ 완료·AI 직접 재검증 완료(위 "검증"
절 전부). **코드 쪽은 이것으로 다 끝났습니다.** 남은 것은 위 "아직 안 끝난 것" 1~6번뿐이고,
그중 1~3번은 오너만 할 수 있는 수동 단계(SQL 실행 · Render 환경변수 · workflow 파일 반영)라
AI가 다음에 대신 진행할 수 있는 건 4번(실검증 준비)과 5번(git 정리) 정도입니다.
