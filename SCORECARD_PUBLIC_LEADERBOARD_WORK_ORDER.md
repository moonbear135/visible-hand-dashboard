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
발행합니다. 순위는 매입원가 대비 수익률로 매기고, 최소 인원(`MIN_PARTICIPANTS_FOR_PUBLICATION`)
미만인 그룹은 아예 발행하지 않습니다.

> ✅ **2026-09-03 오너 확정 — 최소 인원 500명 → 1명.** 실사용자가 적어 500명을 기다리면
> 기능이 시작조차 안 되고, 순위표에 오르는 건 어차피 6개 항목 전부 동의 + 최종 확인을 마친
> 사람뿐이라 인원이 적다고 숨길 필요가 없다는 판단입니다. 상수·`group_meets_minimum()`·
> 미달 그룹 청소 로직은 그대로 두고 값만 1 로 낮췄습니다. 아래 본문의 "500명"은 그 이전
> 기록입니다.

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
(=1, 2026-09-03 까지는 500)/`group_meets_minimum()`, `rank_participants()`(⚠️ 입력 dict 키가 내부적으로 `"twr_pct"`로
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

## 동의 항목 — 6개 + 최종 확인, 체급용 독립 동의는 없음

> ⚠️ **2026-08-23 갱신** — 이 절은 원래 "5개 + 최종 확인, 6번째 독립 동의는 없음"이었습니다.
> 오너의 실사용 검증 뒤 6번째 **항목**(`consent_holding_details`)이 생기면서 개수가 바뀌었고,
> 그 사실에 맞춰 문장을 고쳤습니다. **결투식 "독립 동의"가 없다는 판단 자체는 그대로입니다**
> — 늘어난 항목은 따로 켜고 끄는 것이 아니라 앞의 5개와 같은 "전부 아니면 전무" 묶음입니다.

결투의 6번째 **독립** 동의(`consent_real_principal_bracket` — "실제 매입총합을 체급 산정에
사용")는 "이 모듈이 아닌 **다른 모듈**('내 성적표')의 실제 자산 데이터를 끌어다 쓴다"는
이유로 분리돼 있었습니다. 이 모듈에서는 **공개되는 데이터 자체가 이미 "내 성적표"**이므로,
항목에 전부 동의하는 순간 매입원가합계는 이미 공개된 값들의 단순 합으로 누구나 재구성
가능합니다 — 체급을 위해 별도로 게이트를 세울 대상이 남아 있지 않습니다. 그래서
`scorecard_public_consent`에는 항목별 boolean + `final_confirmed`만 있고, 독립적으로 켜고 끄는
동의는 하나도 없습니다. 나머지 동의 UX 규칙은 결투와 동일: 전부 아니면 전무, 별도 최종 확인
단계, 재동의 3개월 대기, 철회는 필드 업데이트(행 삭제 아님, 발행 기록만 실제로 지움).

동의 항목 6문장(화면·DB 키가 반드시 같은 순서로 일치 — `scorecard_consent_page.py::
consent_item_rows()`가 매번 이 사실을 확인하고 어긋나면 예외). DB CHECK
제약(`scorecard_consent_final_requires_all`)도 이 6개 전부를 요구합니다:

1. **순위** — 내 성적표의 순위가 공개 순위표에 표시됩니다.
2. **수익률** — 내 성적표의 수익률이 공개됩니다.
3. **보유종목** — 내가 실제로 보유한 종목이 순위표에서 다른 사람에게 개별 열람 가능하게
   공개됩니다("개별 열람"은 오너가 명시적으로 요구한 문구 요소).
4. **수량** — 종목별로 내가 실제 보유한 수량이 공개됩니다.
5. **매입금액** — 종목별로 내가 실제 매입한 금액이 공개됩니다.
6. **종목별 상세지표** — 종목별로 평균매입가·현재가·평가손익·수익률·비중까지 함께
   공개됩니다. (2026-08-23 신설. 오너 지시: "공개할거면 다 공개를 해야지. 기본적으로
   '내 성적표'에 나오는 정보는 다 공개가 되어야 하는거 아니야?" · "동의 체크 항목에서 빠져
   있는 내용이면 동의 체크 항목에 추가를 해야지." → 순위표 상세표가 "내 성적표" 화면의 표와
   같은 열 구성이 되면서, 그 다섯 지표를 말하는 동의 문장이 없다는 것이 문제가 됐습니다.
   항목을 조용히 늘리지 않고 체크박스를 하나 더 세운 이유가 그것입니다, §0-1.)

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

## 스키마 (`sql/scorecard_public_schema.sql`) — ✅ 오너 실행 완료(2026-08-23), 추가분 1건 대기

> ⚠️ **2026-08-23 갱신** — 이 절 제목은 원래 "🔴 오너가 아직 Supabase에 실행하지 않음"
> 이었습니다. 오너가 §1~§3(DROP 9종 + CREATE 5종)을 실제로 실행했고 실사용 검증까지
> 마쳤습니다. **그러므로 이 스크립트를 다시 만들거나 고치면 안 됩니다** — 이후 변경은 파일
> 끝의 "2026-08-23 추가" 절처럼 **ALTER 만 덧붙이는 방식**이어야 합니다. 그 추가분을 오너가
> 붙여넣기 좋게 뽑아 둔 사본이 저장소 루트의
> `MIGRATION_2026-08-23_holding_details.sql` 이고, 그 한 건이 **아직 실행 대기**입니다.

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

**§A 2026-08-23 추가분** (같은 파일 끝 · 사본 `MIGRATION_2026-08-23_holding_details.sql` —
원본 CREATE 은 이미 실행됐으므로 **ALTER 만**):
- `scorecard_public_consent` ← `consent_holding_details boolean not null default false`
  (6번째 동의 항목) + `final_confirmed=true` 인 **기존 1행 백필**(오너가 이번 세션에서 전체
  공개를 명시 확정) + `scorecard_consent_final_requires_all` CHECK 를 **6개 기준으로 재작성**
  (백필이 CHECK 재작성보다 반드시 먼저 — 순서를 뒤집으면 `add constraint` 가 기존 행에서
  거절됩니다. 실제 Postgres 16 에서 두 순서를 모두 돌려 확인했습니다).
- `scorecard_public_holdings` ← `avg_price` · `current_price` · `profit` · `profit_pct` ·
  `weight_pct` **전부 `numeric(20,6)` nullable**. null 의 뜻은 "`consent_holding_details`
  미동의" 또는 "그날 가격 미확인"이며 **0 이 아닙니다**(§0-1 — 화면은 "비공개"로 그림).
  두 사유를 구분해 담지 않습니다(구분하면 "동의는 했는데 가격이 없다"가 드러남).
  `profit`/`profit_pct` 에는 하한을 걸지 않았습니다 — **손실이면 음수가 정상**이라
  `>= 0` 을 걸면 손실 난 사람의 발행이 통째로 거절됩니다. 가격 2종과 `weight_pct` 에만
  `>= 0` 을 겁니다(`weight_pct` 의 상한 100 도 일부러 걸지 않음 — 반올림 끝자리로 그날 발행
  전체가 거절되는 것보다 낫습니다).

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
- **Phase C(종목별 상세지표 전면 공개 + 6번째 동의 항목, 2026-08-23, 오너 실사용 검증 후)** —
  오너가 임시 SQL로 채운 더미 참가자로 `/scorecard/leaderboard`를 끝까지 써 본 뒤 확정:
  *"공개할거면 다 공개를 해야지. 기본적으로 '내 성적표'에 나오는 정보는 다 공개가 되어야
  하는거 아니야?"* · *"동의 체크 항목에서 빠져 있는 내용이면 동의 체크 항목에 추가를 해야지."*
  (더미 참가자는 이미 정리됨.)
  - **동의**: `consent_holding_details`("종목별 상세지표") 6번째 항목 신설 —
    `scorecard_publish_db.CONSENT_ITEM_FLAGS`(끝에 추가, 앞 5개 순서 불변) +
    `scorecard_consent_page.CONSENT_ITEM_SENTENCES`. 화면 렌더 루프는 **한 줄도 안 고쳤습니다**
    (이미 `consent_item_rows()`를 도는 일반 루프라 체크박스가 저절로 6개가 됩니다 — §0-3-10).
    화면 문구의 "5개"는 전부 `len(CONSENT_ITEM_FLAGS)`에서 세도록 바꿨습니다(다음에 또 늘어도
    문구가 거짓이 되지 않게).
  - **스키마**: `sql/scorecard_public_schema.sql` 끝에 **추가분(ALTER only)** + 오너 실행용
    사본 `MIGRATION_2026-08-23_holding_details.sql`(위 §A). 원본 CREATE 스크립트는 이미
    실행됐으므로 손대지 않았습니다.
  - **발행**: `holdings_payload()`가 5종을 함께 싣되 **전부 이미 계산된 값의 이동**입니다
    (`evaluate_holding()`/`build_portfolio()`의 `avg_purchase_price`·`current_price`·
    `profit`·`profit_pct`·`weight_pct`). 게이팅 값은 동의 행에서 참가자 dict로 실려 오고
    (`build_publish_rows()`), **키가 없으면 비공개**로 봅니다(§0-3-8 기본 비공개).
  - **화면**: 상세표가 3칸 → **8칸**(`HOLDINGS_TABLE_HEADERS`). 서식 함수는 "내 성적표"
    화면과 같은 것(`format_amount()`·`pct_html()`)을 씁니다. 금액 칸이 넷이 되면서 통화를
    빠뜨릴 위험이 커져 `_amount_cell()` 하나로 모았습니다. 페이저에는 **페이지 직접 이동**
    (`ui.number` + "이동")을 덧붙였습니다(오너: 이전/다음만으로 17페이지는 너무 느리다) —
    기존 이전/다음 로직은 그대로이고, 판정은 순수 함수 `resolve_jump_target()`이 합니다
    (범위를 벗어나면 **말없이 잘라 맞추지 않고** 이유를 돌려줍니다, §0-1).
  - 최종 줄 수: `utils/scorecard_publish.py`(858→971)·`utils/scorecard_publish_db.py`
    (1053→1084)·`web/pages/scorecard_consent_page.py`(743→778)·
    `web/pages/scorecard_leaderboard_page.py`(721→844)·
    `tests/test_scorecard_publish.py`(1516→1814, 132→148개)·
    `tests/test_scorecard_public_ui.py`(1152→1569, 48→76개)·
    `sql/scorecard_public_schema.sql`(356→496)·`MIGRATION_...sql`(신규 154줄).

#### Phase C 검증 (AI가 직접 실행, 2026-08-23)

1. `python -m py_compile` — 변경한 7개 파일 전부 클린.
2. `pytest tests/test_scorecard_publish.py tests/test_scorecard_public_ui.py -q` → **223 통과**.
3. 저장소 **전체 스위트** → **2 failed, 1293 passed, 3 errors** — 실패·오류 5건의 **이름이
   기준선과 완전히 동일**(`test_upload_widget_is_really_not_rendered_when_flag_is_off`·
   `test_macro_render_smoke`·`test_render_smoke`·`test_report_render_smoke`·
   `test_duel_render_smoke` — 세션 순서에 따라 흔들리는 기존 NiceGUI 전역 슬롯스택 문제).
   통과 수는 1249 → 1293(+44, 이번에 추가한 검사 수와 일치). **새 실패 0건.**
   ⚠️ `pytest tests/ -k scorecard -q`로 좁혀 돌리면 렌더 스모크 9개가 추가로 실패하는데,
   이는 `tests/test_scorecard_ocr.py`가 먼저 도는 순서에서만 나타나는 **기존** 전역 상태
   문제입니다(두 파일만 함께 돌려 재현 확인). 이번에 추가한 검사는 그 영향을 받지 않도록
   전부 슬롯 없이 도는 방식으로 작성했습니다.
4. 🔴 **실제 Postgres 16에 마이그레이션을 직접 실행해 확인**(문법 검사가 아니라 진짜 실행):
   빈 클러스터에 Supabase 대역(roles·`auth.users`·`auth.uid()`·`duel_set_updated_at()`)을
   깔고 → **원본 스키마 §1~§3을 그대로 적용**(= 오너가 이미 실행한 상태 재현) →
   `final_confirmed=true` 동의 1행 + 발행 보유종목을 심고 → `MIGRATION_...sql` 실행.
   결과: 오류 0, **`UPDATE 1`(백필이 정확히 그 1행)**, 새 컬럼 5개가 전부
   `numeric(20,6) nullable`로 생성, CHECK가 6개 플래그를 요구하는 정의로 재작성됨.
   추가로 직접 확인: ① 백필을 빼고 CHECK를 먼저 걸면 *"is violated by some row"*로 **실제로
   거절됨**(주석의 순서 경고가 사실임을 증명), ② 6개 중 하나만 빠진 `final_confirmed` 행은
   거절 / 6개 전부면 통과, ③ 음수 `profit`·`profit_pct`는 저장됨(손실이 정상값),
   ④ 음수 가격은 거절됨, ⑤ 상세지표가 null인 행도 그대로 들어감, ⑥ 마이그레이션을 **두 번**
   돌려도 오류 없음, ⑦ **`holdings_payload()`가 만든 진짜 payload를 그 표에 그대로 insert**
   해 컬럼 이름·값이 전부 맞물림을 확인(가격 못 구한 종목은 4개가 null, 0이 아님).
   확인 후 임시 클러스터는 삭제했습니다.
5. `holding_row_cells()`/`holdings_table()`을 직접 실행해 확인: 악성 `stock_name`
   (`<img src=x onerror=alert(1)>`)·악성 `ticker`(`"><script>...`)가 **여덟 칸 어디에서도**
   raw로 나오지 않고 `&lt;img …&gt;`로만 나타남 / `consent_holding_details=False`면 새 다섯
   칸이 전부 **"비공개"**(0도 빈칸도 아님) / 값이 있으면 원화는 `50,000원`, 달러는 `$200.00`,
   손실은 파란 `-10.00%`로 정확히 그려짐.
6. 페이지 이동 처리기를 직접 실행: 12 입력 → `view["top"]`이 11로만 바뀌고 새로고침 1회,
   999 입력 → **페이지가 그대로**이고 "1 ~ 17 사이" 안내만 뜸, 반대쪽 구간(`bottom`)은
   건드리지 않음.
7. 두 SQL 파일의 추가분이 **byte-identical**임을 검사로 고정(`tests/test_scorecard_publish.py`
   5-c절) — 한쪽만 고치면 테스트가 실패합니다.

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

## 아직 안 끝난 것 → 전부 완료 (2026-08-23 같은 날, 후속 라운드)

아래 1~6번은 전부 그날 안에 끝났습니다. 이력을 지우지 않고 완료 표시만 남깁니다.

1. ✅ **마이그레이션 실행(오너)** — `MIGRATION_2026-08-23_holding_details.sql` 실행 완료.
   `consent_holding_details` 백필(`true`)과 `scorecard_public_holdings` 신규 컬럼 5개 생성을
   오너가 직접 SQL로 조회해 확인했습니다.
2. ✅ **Render 환경변수** — `SCORECARD_CONSENT_ENABLED`/`SCORECARD_LEADERBOARD_ENABLED`
   둘 다 오너가 `true`로 설정 완료(Render 대시보드 스크린샷으로 확인).
3. ✅ **`.github/workflows/scorecard_publish_daily.yml` 반영** — 배포 완료, `workflow_dispatch`로
   여러 차례 수동 실행해 정상 동작(발행 대상·체급·최소인원 게이팅) 확인.
4. ✅ **6단계(실검증)** — 오너 본인의 실제 계정으로 동의 6개 항목 + 최종 확인 → 배치 실행
   (real GitHub Actions) → 임시로 참가자를 채워 순위표에서 본인 닉네임 + 8개 컬럼(종목·수량·
   매입금액·평균매입가·현재가·평가손익·수익률·비중) 실제 렌더링까지 확인 → 정리(배치
   재실행으로 원복) 완료.
5. ✅ **git 반영** — 삭제 파일 포함 커밋·푸시 완료(commit `8187a2f` 등).
6. ✅ **3단계(전체 공개) 전환** — 2026-08-23 같은 날, 오너가 Render 환경변수를 전부 `true`로
   맞춘 것을 보고 "전체 공개된 게 맞다"고 물었다가, `MENU_ADMIN_ONLY` 두 값은 환경변수가
   아니라 **코드에 박힌 상수**라 Render 설정과 무관하다는 걸 확인 → "안내만 보이더라도
   열어놓자, 사람들 관심을 받기라도 할 것 같다"며 그 자리에서 전체 공개를 확정.
   `SCORECARD_CONSENT_MENU_ADMIN_ONLY`/`SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY`를
   `True → False`로 변경(결투 `/duel`이 2026-08-22에 밟은 것과 같은 마지막 단계).

**같은 라운드에 함께 처리한 사이드바 재정리(오너 요청)**: `web/layout.py`의 메뉴 그룹
"⚔️ 결투다!"를 "⚔️ 내 밑으로 눈 깔어"로 개명하고, `/scorecard/consent`·
`/scorecard/leaderboard` 두 항목을 `📊 보유종목` 그룹에서 이 그룹으로 옮겼습니다(공개 여부
스위치와는 무관한 순전한 UX 결정). 라벨도 오너 지정 문구로 바꿨습니다: "참전하기"→
"나 자신과의 싸움이니라", "공개 동의 관리"→"공개 동의 관리(= 다 덤벼 신청서)",
"공개 순위표 (내 밑으로 눈 깔어)"→"다 덤벼!". `tests/test_scorecard_public_ui.py`의 관련
검사(그룹 소속·라벨·admin_only 값)를 전부 새 상태 기준으로 갱신했고, 전체 스위트(1293개)가
이 세션 이전부터 있던 것과 같은 5개의 nicegui 렌더 순서 flaky 항목만 남기고 통과합니다.

🧹 **정리해도 되는 것(급하지 않음)**: Render 환경변수에 `DUEL_CONSENT_ENABLED`·
`DUEL_LEADERBOARD_ENABLED`가 남아있는데, 이 두 값은 결투 공개 계층이 은퇴하며
`web/layout.py`에서 이미 빠졌으므로(`tests/test_duel_public_ui.py`가 그 은퇴를 고정) 지금은
코드 어디에서도 읽지 않는 죽은 값입니다. 지워도 아무 영향 없고, 안 지워도 해가 없습니다.

## 다음에 이 문서를 다시 열 때

**2026-08-23 기준 진행 상황**: Phase 0~D 전부 ✅ 완료·AI 직접 재검증 완료, 그리고 위 "아직 안
끝난 것" 1~6번(마이그레이션·Render 환경변수·workflow 반영·실검증·git 반영·3단계 전체 공개
전환)까지 **전부 같은 날 안에 끝났습니다.** 사이드바 재정리도 함께 반영됐습니다. **이 모듈은
지금 코드·설정·실검증 전부 완료 상태입니다.** 남은 건 순전히 데이터가 쌓이는 것뿐입니다 —
체급(구간)마다 500명 이상 모여야 순위표에 실제로 뭔가 뜨는데, 이건 사람이 더 할 일이 없고
시간이 해결할 문제입니다.

⚠️ **다음 사람에게** — 이 문서에는 2026-08-23 이전에 쓰인 "동의 항목은 5개"·"6번째는 없다"는
서술이 있었고, Phase C에서 사실에 맞게 고쳤습니다. 혹시 저장소 어딘가에서 아직 "5개"라고
말하는 서술을 보시면 그건 **낡은 것**입니다 — 단일 출처는
`utils/scorecard_publish_db.CONSENT_ITEM_FLAGS`이고, 화면·DB CHECK가 그것과 어긋나면
`consent_item_rows()`와 테스트가 즉시 실패합니다.
