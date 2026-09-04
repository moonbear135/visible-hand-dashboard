-- =============================================================================
-- 결투다! 현금 원장 정정 — 계좌 개설일(anchor_date) 이전 날짜로 잘못 들어간 정기입금
-- (2026-09-04, TASK_HISTORY #193 · §4 는 #194)
-- =============================================================================
-- 이 파일은 스키마 변경이 아니라 **데이터 정정** 스크립트입니다. `sql/duel_schema.sql` 은
-- "새로 설치한다면 이런 모양"의 기준 문서이고, 이 파일은 **현재 운영 중인 원장 표**에
-- 이미 잘못 들어간 행을 바로잡습니다.
--
-- 실행 방법: Supabase 대시보드 → SQL Editor → 아래 순서대로.
--   1) [진단 1-A / 1-B] 를 먼저 실행해 계좌별 건수·금액이 예상과 맞는지 눈으로 확인합니다
--      (읽기 전용 — 아무것도 바꾸지 않습니다).
--   2) 이상 없으면 [정정 2-A / 2-B] 를 실행합니다(각각 1회).
--   3) [확인 3] 을 실행해 "잘못된 입금 − 되돌림 = 0" 인지 확인합니다(0행이어야 정상).
--   4) [스냅샷 정정 4] — 4-A 진단으로 자동/수동 분류를 확인 → 4-B update(KRW·USD) → 4-C 확인.
--      원장 되돌림만으로는 이미 저장된 `duel_daily_snapshots` (= TWR 입력) 가 안 고쳐지기
--      때문입니다(§4 머리말). 4-B 는 매수 이력이 전혀 없는 계좌만 자동으로 고치고, 나머지는
--      파일 끝의 "사람이 판단" 목록에만 남깁니다.
--   정정 쿼리는 여러 번 실행해도 안전합니다 — 원장 되돌림은 이미 같은 원본 id 로 되돌림 행이
--   있으면 다시 넣지 않고(`not exists`), 스냅샷 update 는 같은 값을 다시 쓸 뿐입니다.
--   그래도 1) → 2) → 3) → 4) 순서는 지켜 주세요(4-C-3 은 §2 가 먼저 실행됐다고 가정합니다).
--
-- ⚠️ 실행 전 Supabase 대시보드에서 백업(스냅샷)이 최근 것인지 한 번 확인하는 것을
--    권장합니다 — 이 프로젝트의 다른 스키마 변경 때와 같은 관례입니다.
--
-- ⚠️ 이 파일은 저장소의 어떤 코드·워크플로우도 실행하지 않습니다. service_role 키는
--    GitHub Actions Secrets 에만 있어야 하므로(`utils/duel_db.py` 머리말 §0-3-8), 오너가
--    SQL 편집기에서 직접 실행합니다.
-- =============================================================================
--
-- ── 무슨 일이 있었나 ────────────────────────────────────────────────────────────
-- 2026-08-29 재감사 H-7 로 `utils/duel_batch.py::_pending_monthly_deposit_dates()` 가
-- 최근 60일 안의 "매월 10일"을 전부 `apply_monthly_deposits()` 에 넘기게 됐습니다(배치가
-- 며칠 못 돌아도 밀린 달을 챙기려고). 그런데 `apply_monthly_deposits()` 는 **지금 활성인
-- 계좌 전체**에 "그 날짜로 이미 입금이 있는지"만 보고 넣었고, **그 계좌가 그 날짜에
-- 존재했는지(anchor_date <= event_date)** 는 보지 않았습니다. 그래서 2026-08-22 에 개설된
-- 계좌(시드 1,000만원)가 7/10·8/10 입금 80만원×2 를 받아 총자산 1,160만원으로 표시됐습니다.
-- 코드는 같은 날 고쳤고(`utils/duel_db.py` · `utils/duel_db_usd.py`), 이 파일은 그 전에
-- 이미 들어간 행을 바로잡습니다.
--
-- ── 왜 update/delete 가 아니라 reversal 행 insert 인가 ─────────────────────────────
-- 현금 원장은 append-only 입니다(`sql/duel_schema.sql` §4-2 — update 는 트리거
-- `duel_cash_ledger_append_only` 가 막고, delete 는 권한 자체가 없습니다). 정정은 **반대
-- 부호의 `reversal` 행을 덧붙여서만** 합니다. `duel_cash_ledger_sign_match` /
-- `duel_cash_ledger_usd_sign_match` 제약은 `event_type = 'reversal'` 이면 부호를 제한하지
-- 않고(§4 "reversal 은 정정이라 양쪽 부호가 다 필요하므로 제약하지 않습니다"),
-- `*_order_link` 제약도 reversal 은 order_id 유무를 제한하지 않습니다.
--
-- ── event_date 를 원본과 같은 날짜로 두는 이유 ──────────────────────────────────────
-- 정정은 "언제 실행했나"가 아니라 "언제 있었던 일을 되돌리나"를 기록합니다. 원본 입금이
-- 7/10 자로 들어갔으면 되돌림도 7/10 자입니다. 그래야 그 날짜 이후의 잔고
-- (`sum(amount) where event_date <= 기준일`)가 어느 기준일에서 보든 정확히 시드만 남습니다.
--
-- ⚠️ 알아 둘 부작용 → §4 에서 처리: 이미 저장된 `duel_daily_snapshots` 의 총자산·현금은
--    잘못된 입금이 반영된 값이고, 배치의 TWR 은 `seed`/`monthly_deposit` 만 외부 현금흐름으로
--    봅니다(`utils/duel_batch.py::EXTERNAL_CASH_FLOW_TYPES`). 원장 되돌림만 넣고 두면 정정
--    뒤 첫 스냅샷에서 현금이 80만원×N 만큼 줄어드는데 그날의 cash_flow 는 0 이므로, 그
--    구간의 일간 수익률이 그만큼 마이너스로 잡힙니다. 그래서 §1~§3 (원장) 뒤에 §4 (스냅샷
--    정정) 를 이어서 실행합니다 — 원장은 §1~§3, 스냅샷은 §4 가 담당합니다.
-- =============================================================================


-- =============================================================================
-- 1. 진단 (읽기 전용) — 계좌 개설일보다 이른 날짜의 monthly_deposit 행
-- =============================================================================

-- 1-A. 원화 트랙 — 행 단위 목록 + 계좌별 집계
--      (조건: event_type='monthly_deposit' 이고 event_date < 그 계좌의 anchor_date)
select
    l.id            as ledger_id,
    l.account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    l.event_date,
    l.amount,
    l.memo,
    l.created_at,
    exists (
        select 1 from public.duel_cash_ledger r
         where r.account_id = l.account_id
           and r.event_type = 'reversal'
           and r.memo like '%원본 원장 id=' || l.id
    )               as already_reversed
  from public.duel_cash_ledger l
  join public.duel_accounts a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
 order by l.account_id, l.event_date;

select
    l.account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    count(*)        as wrong_deposit_rows,
    sum(l.amount)   as wrong_deposit_total_krw,
    min(l.event_date) as earliest_wrong_date,
    max(l.event_date) as latest_wrong_date
  from public.duel_cash_ledger l
  join public.duel_accounts a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
 group by l.account_id, a.user_id, a.window_type, a.anchor_date
 order by a.user_id, a.window_type;

-- 1-B. USD 트랙 — 같은 조건, `_usd` 표
select
    l.id            as ledger_id,
    l.account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    l.event_date,
    l.amount,
    l.memo,
    l.created_at,
    exists (
        select 1 from public.duel_cash_ledger_usd r
         where r.account_id = l.account_id
           and r.event_type = 'reversal'
           and r.memo like '%원본 원장 id=' || l.id
    )               as already_reversed
  from public.duel_cash_ledger_usd l
  join public.duel_accounts_usd a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
 order by l.account_id, l.event_date;

select
    l.account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    count(*)        as wrong_deposit_rows,
    sum(l.amount)   as wrong_deposit_total_usd,
    min(l.event_date) as earliest_wrong_date,
    max(l.event_date) as latest_wrong_date
  from public.duel_cash_ledger_usd l
  join public.duel_accounts_usd a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
 group by l.account_id, a.user_id, a.window_type, a.anchor_date
 order by a.user_id, a.window_type;


-- =============================================================================
-- 2. 정정 (쓰기) — 잘못된 monthly_deposit 행마다 반대 부호의 reversal 행 1개 insert
-- =============================================================================
--  · amount    = -(원본 amount)  → reversal 은 sign_match 제약에서 부호 제한 없음
--  · event_date = 원본 event_date (실행일이 아님 — 머리말 참고)
--  · order_id  = null (reversal 은 order_link 제약에서 제한 없음)
--  · memo      = 원본 원장 id 를 끝에 남겨 추적 가능하게 + 재실행 시 중복 방지 키로 사용
--  · not exists 로 같은 원본 id 에 대한 되돌림이 이미 있으면 다시 넣지 않습니다(멱등).
-- -----------------------------------------------------------------------------

-- 2-A. 원화 트랙
insert into public.duel_cash_ledger (account_id, event_type, amount, event_date, order_id, memo)
select
    l.account_id,
    'reversal',
    -l.amount,
    l.event_date,
    null,
    '정정: ' || to_char(a.anchor_date, 'YYYY-MM-DD')
        || ' 계좌 개설 이전(anchor_date보다 이른 날짜 ' || to_char(l.event_date, 'YYYY-MM-DD')
        || ')에 잘못 들어간 정기입금 되돌림 — 원본 원장 id=' || l.id
  from public.duel_cash_ledger l
  join public.duel_accounts a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
   and not exists (
        select 1 from public.duel_cash_ledger r
         where r.account_id = l.account_id
           and r.event_type = 'reversal'
           and r.memo like '%원본 원장 id=' || l.id
   );

-- 2-B. USD 트랙
insert into public.duel_cash_ledger_usd (account_id, event_type, amount, event_date, order_id, memo)
select
    l.account_id,
    'reversal',
    -l.amount,
    l.event_date,
    null,
    '정정: ' || to_char(a.anchor_date, 'YYYY-MM-DD')
        || ' 계좌 개설 이전(anchor_date보다 이른 날짜 ' || to_char(l.event_date, 'YYYY-MM-DD')
        || ')에 잘못 들어간 정기입금 되돌림 — 원본 원장 id=' || l.id
  from public.duel_cash_ledger_usd l
  join public.duel_accounts_usd a on a.id = l.account_id
 where l.event_type = 'monthly_deposit'
   and l.event_date < a.anchor_date
   and not exists (
        select 1 from public.duel_cash_ledger_usd r
         where r.account_id = l.account_id
           and r.event_type = 'reversal'
           and r.memo like '%원본 원장 id=' || l.id
   );


-- =============================================================================
-- 3. 확인 (읽기 전용) — 정정 뒤 "잘못된 입금 + 되돌림" 의 합이 계좌·날짜별로 0 인지
--    (0행이어야 정상. 행이 나오면 그 계좌·날짜의 되돌림이 빠졌거나 두 번 들어간 것)
-- =============================================================================
select 'KRW' as track, l.account_id, l.event_date, sum(l.amount) as net_amount
  from public.duel_cash_ledger l
  join public.duel_accounts a on a.id = l.account_id
 where l.event_date < a.anchor_date
   and l.event_type in ('monthly_deposit', 'reversal')
 group by l.account_id, l.event_date
having sum(l.amount) <> 0
union all
select 'USD' as track, l.account_id, l.event_date, sum(l.amount) as net_amount
  from public.duel_cash_ledger_usd l
  join public.duel_accounts_usd a on a.id = l.account_id
 where l.event_date < a.anchor_date
   and l.event_type in ('monthly_deposit', 'reversal')
 group by l.account_id, l.event_date
having sum(l.amount) <> 0;


-- =============================================================================
-- 4. 스냅샷 정정 (있을 경우) — 이미 저장된 `duel_daily_snapshots(_usd)` 행 바로잡기
--    (2026-09-04 후속, TASK_HISTORY #194) — 반드시 [2. 정정] 을 먼저 실행한 뒤에.
-- =============================================================================
--
-- ── 왜 원장 reversal(§2)만으로는 끝나지 않나 ──────────────────────────────────────
-- 화면의 숫자는 두 경로로 만들어집니다.
--   · **총자산·예수금** — `web/pages/duel_page.py::_render_account_card()` 가 페이지를 열 때마다
--     원장을 **라이브로 합산**합니다(`sum_cash_balance(fetch_my_cash_ledger(...))`). 저장된
--     스냅샷을 쓰지 않으므로 §2 의 reversal 행만 들어가면 **다음 새로고침에 바로** 정상입니다.
--   · **누적 수익률(TWR)** — `fetch_my_snapshots()` 로 `duel_daily_snapshots` 에 **이미 저장된
--     과거 행**을 읽어 `compute_twr()` 에 넘깁니다. 그 행들은 버그가 있던 시점에 배치가 실제로
--     계산해 넣은 값이라 `total_value`·`cash_balance`(·첫 행이면 `cash_flow_amount`)가 이미
--     틀려 있고, 원장에 reversal 을 추가해도 **저장된 스냅샷 행은 저절로 바뀌지 않습니다**.
--
-- ── 왜 "배치가 다음에 돌면서 알아서 고쳐 줄 것"이라는 기대가 틀렸나 ─────────────────
--   (1) `utils/duel_batch.py::collect_external_cash_flows()` 는 "직전 스냅샷 날짜(boundary)
--       이전의 원장 행은 이미 반영된 것"으로 보고 건너뜁니다. reversal 행은 원본과 같은
--       **과거 날짜**(anchor_date 이전)로 들어가므로 언제 배치가 돌아도 boundary 보다 이르고,
--       따라서 **절대 잡히지 않습니다**. 애초에 `EXTERNAL_CASH_FLOW_TYPES = ('seed',
--       'monthly_deposit')` 라 `reversal` 은 외부 현금흐름으로 세지도 않습니다.
--   (2) `duel_daily_snapshots.cash_flow_amount` 는 `check (cash_flow_amount >= 0)` 라 "되돌림"을
--       음수 현금흐름으로 표현할 방법 자체가 없습니다.
--   ⇒ 잘못 저장된 스냅샷 행은 **SQL 로 직접 update 해야만** 바로잡힙니다. 이 표는
--      `revoke delete … from service_role` 로 삭제는 막혀 있지만 update 는 열려 있습니다
--      (`grant select, insert, update on public.duel_daily_snapshots to service_role`, §9).
--
-- ── 어떤 계좌만 자동으로 고치나 (§0-1 — 확신 없는 값은 만들지 않기) ──────────────────
-- 이번 버그로 들어간 monthly_deposit 은 **전부 무효**입니다(그 날짜에 계좌가 없었으므로). 그러니
-- 아래 두 조건을 **모두** 만족하는 계좌는 "정정 후 정답"이 모호함 없이 정해집니다:
--   (a) 그 계좌의 **모든** 스냅샷 행이 `position_value = 0` — 한 번도 매수한 적이 없음.
--       (한 번이라도 매수했다면 가짜 예수금으로 실제 매수를 했을 수 있어 정답이 seed_amount 뿐
--        이라고 단정할 수 없습니다 → 사람이 판단.)
--   (b) 그 계좌의 원장에 **시드 1행(amount = seed_amount) + 잘못된 monthly_deposit + 그 되돌림**
--       외의 행이 없음. (예: anchor_date 이후의 **정상** 정기입금이 이미 있는 계좌는 정답이
--       "seed_amount + 정상 입금"이라 아래 규칙으로 덮어쓰면 오히려 틀려집니다 → 사람이 판단.)
--   이 두 조건을 만족하는 계좌의 정답:
--     · snapshot_date 가 **가장 이른** 행: total_value = cash_balance = seed_amount,
--                                          cash_flow_amount = seed_amount, cash_flow_kind = 'seed'
--     · **그 외 모든** 행:                 total_value = cash_balance = seed_amount,
--                                          cash_flow_amount = 0,           cash_flow_kind = null
--     · position_value / total_cost 는 이미 0 이므로 손대지 않습니다.
--   `duel_snapshots_total_match`(total = position + cash) · `duel_snapshots_cash_flow_match`
--   (금액 0 ↔ 종류 null) 제약을 위 값이 그대로 만족합니다. `updated_at` 은 트리거
--   `duel_snapshots_set_updated_at` 이 갱신하므로 적지 않습니다.
--
-- 실행 순서: [4-A 진단] 으로 자동/수동 분류를 눈으로 확인 → [4-B 정정] (KRW·USD 각 1회, 여러 번
--            실행해도 같은 결과) → [4-C 확인] (위반 0행이 정상) → 파일 끝의 수동 검토 목록은
--            사람이 판단. 이 섹션은 `duel_holding_snapshots` 는 건드리지 않습니다(대상 계좌는
--            보유가 없어 그 표에 행이 없습니다).
-- =============================================================================

-- 4-A. 진단 (읽기 전용) — 잘못된 입금을 받은 계좌를 자동 정정 / 수동 검토로 분류
--      verdict:
--        'AUTO'                     … 4-B 가 고치는 계좌 ((a)·(b) 모두 만족)
--        'MANUAL: position_value>0' … 매수 이력 있음 → 사람이 판단 (dates_with_positions 참고)
--        'MANUAL: 원장에 다른 행'   … 시드·잘못된 입금·되돌림 외 원장 행 있음 (other_ledger_events 참고)
--        'MANUAL: 시드 불일치'      … 시드 원장 행이 없거나 amount ≠ seed_amount
--        'SKIP: 스냅샷 없음'        … 고칠 스냅샷 행이 없음(원장 정정만으로 끝)

-- 4-A-1. 원화 트랙
with wrong_accounts as (
    select distinct l.account_id
      from public.duel_cash_ledger l
      join public.duel_accounts a on a.id = l.account_id
     where l.event_type = 'monthly_deposit'
       and l.event_date < a.anchor_date
),
snap as (
    select s.account_id,
           count(*)                                   as snapshot_rows,
           min(s.snapshot_date)                       as earliest_snapshot,
           max(s.snapshot_date)                       as latest_snapshot,
           max(s.position_value)                      as max_position_value,
           array_agg(s.snapshot_date order by s.snapshot_date)
               filter (where s.position_value > 0)    as dates_with_positions
      from public.duel_daily_snapshots s
     where s.account_id in (select account_id from wrong_accounts)
     group by s.account_id
),
other_ledger as (
    -- 시드 / anchor_date 이전 monthly_deposit(잘못된 입금) / anchor_date 이전 reversal(그 되돌림)
    -- 을 뺀 나머지 원장 행. 하나라도 있으면 정답이 seed_amount 뿐이라고 단정할 수 없습니다.
    select l.account_id,
           count(*) as other_rows,
           array_agg(l.event_type || ' ' || to_char(l.event_date, 'YYYY-MM-DD') || ' ' || l.amount
                     order by l.event_date, l.id) as other_ledger_events
      from public.duel_cash_ledger l
      join public.duel_accounts a on a.id = l.account_id
     where l.account_id in (select account_id from wrong_accounts)
       and not (l.event_type = 'seed')
       and not (l.event_type in ('monthly_deposit', 'reversal') and l.event_date < a.anchor_date)
     group by l.account_id
),
seed_row as (
    select l.account_id, sum(l.amount) as seed_ledger_amount
      from public.duel_cash_ledger l
     where l.account_id in (select account_id from wrong_accounts)
       and l.event_type = 'seed'
     group by l.account_id
)
select
    'KRW'                                   as track,
    case
        when sn.account_id is null                       then 'SKIP: 스냅샷 없음'
        when sn.max_position_value > 0                   then 'MANUAL: position_value>0'
        when ol.other_rows > 0                           then 'MANUAL: 원장에 다른 행'
        when sr.seed_ledger_amount is distinct from a.seed_amount then 'MANUAL: 시드 불일치'
        else                                                  'AUTO'
    end                                     as verdict,
    a.id                                    as account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    a.seed_amount,
    sn.snapshot_rows,
    sn.earliest_snapshot,
    sn.latest_snapshot,
    sn.max_position_value,
    sn.dates_with_positions,
    ol.other_ledger_events,
    sr.seed_ledger_amount
  from public.duel_accounts a
  join wrong_accounts w  on w.account_id  = a.id
  left join snap sn      on sn.account_id = a.id
  left join other_ledger ol on ol.account_id = a.id
  left join seed_row sr  on sr.account_id = a.id
 order by verdict, a.user_id, a.window_type;

-- 4-A-2. USD 트랙 — 같은 분류, `_usd` 표
with wrong_accounts as (
    select distinct l.account_id
      from public.duel_cash_ledger_usd l
      join public.duel_accounts_usd a on a.id = l.account_id
     where l.event_type = 'monthly_deposit'
       and l.event_date < a.anchor_date
),
snap as (
    select s.account_id,
           count(*)                                   as snapshot_rows,
           min(s.snapshot_date)                       as earliest_snapshot,
           max(s.snapshot_date)                       as latest_snapshot,
           max(s.position_value)                      as max_position_value,
           array_agg(s.snapshot_date order by s.snapshot_date)
               filter (where s.position_value > 0)    as dates_with_positions
      from public.duel_daily_snapshots_usd s
     where s.account_id in (select account_id from wrong_accounts)
     group by s.account_id
),
other_ledger as (
    select l.account_id,
           count(*) as other_rows,
           array_agg(l.event_type || ' ' || to_char(l.event_date, 'YYYY-MM-DD') || ' ' || l.amount
                     order by l.event_date, l.id) as other_ledger_events
      from public.duel_cash_ledger_usd l
      join public.duel_accounts_usd a on a.id = l.account_id
     where l.account_id in (select account_id from wrong_accounts)
       and not (l.event_type = 'seed')
       and not (l.event_type in ('monthly_deposit', 'reversal') and l.event_date < a.anchor_date)
     group by l.account_id
),
seed_row as (
    select l.account_id, sum(l.amount) as seed_ledger_amount
      from public.duel_cash_ledger_usd l
     where l.account_id in (select account_id from wrong_accounts)
       and l.event_type = 'seed'
     group by l.account_id
)
select
    'USD'                                   as track,
    case
        when sn.account_id is null                       then 'SKIP: 스냅샷 없음'
        when sn.max_position_value > 0                   then 'MANUAL: position_value>0'
        when ol.other_rows > 0                           then 'MANUAL: 원장에 다른 행'
        when sr.seed_ledger_amount is distinct from a.seed_amount then 'MANUAL: 시드 불일치'
        else                                                  'AUTO'
    end                                     as verdict,
    a.id                                    as account_id,
    a.user_id,
    a.window_type,
    a.anchor_date,
    a.seed_amount,
    sn.snapshot_rows,
    sn.earliest_snapshot,
    sn.latest_snapshot,
    sn.max_position_value,
    sn.dates_with_positions,
    ol.other_ledger_events,
    sr.seed_ledger_amount
  from public.duel_accounts_usd a
  join wrong_accounts w  on w.account_id  = a.id
  left join snap sn      on sn.account_id = a.id
  left join other_ledger ol on ol.account_id = a.id
  left join seed_row sr  on sr.account_id = a.id
 order by verdict, a.user_id, a.window_type;


-- 4-B. 정정 (쓰기) — 4-A 의 'AUTO' 계좌만 update
--  · 대상(target) 조건은 4-A 의 AUTO 판정과 **같은 네 조건**을 `exists / not exists` 로 다시 씁니다
--    (스냅샷이 있고 · position_value > 0 인 스냅샷이 없고 · 시드/잘못된 입금/되돌림 외 원장 행이
--     없고 · 시드 원장 행 합 = seed_amount). 'MANUAL' 계좌는 여기서 **구조적으로** 빠집니다.
--  · "가장 이른 행"은 `distinct on (account_id) … order by account_id, snapshot_date` 로 잡습니다
--    (`duel_snapshots_account_date_unique` 가 있어 같은 날짜 두 행은 없습니다).
--  · 멱등: 이미 정정된 행에 같은 값을 다시 써도 결과가 같습니다(트리거가 updated_at 만 갱신).
-- -----------------------------------------------------------------------------

-- 4-B-1. 원화 트랙
with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts a
     where exists (                                   -- 이번 버그의 잘못된 입금을 받은 계좌
               select 1 from public.duel_cash_ledger l
                where l.account_id = a.id
                  and l.event_type = 'monthly_deposit'
                  and l.event_date < a.anchor_date)
       and exists (                                   -- 고칠 스냅샷이 있음
               select 1 from public.duel_daily_snapshots s
                where s.account_id = a.id)
       and not exists (                               -- (a) 매수 이력 없음
               select 1 from public.duel_daily_snapshots s
                where s.account_id = a.id
                  and s.position_value > 0)
       and not exists (                               -- (b) 시드·잘못된 입금·되돌림 외 원장 행 없음
               select 1 from public.duel_cash_ledger l
                where l.account_id = a.id
                  and not (l.event_type = 'seed')
                  and not (l.event_type in ('monthly_deposit', 'reversal')
                           and l.event_date < a.anchor_date))
       and (                                          -- 시드 원장 행 합 = seed_amount
               select sum(l.amount) from public.duel_cash_ledger l
                where l.account_id = a.id
                  and l.event_type = 'seed') = a.seed_amount
),
first_snapshot as (
    select distinct on (s.account_id) s.account_id, s.id as first_snapshot_id
      from public.duel_daily_snapshots s
      join target t on t.account_id = s.account_id
     order by s.account_id, s.snapshot_date
)
update public.duel_daily_snapshots s
   set cash_balance     = t.seed_amount,
       total_value      = t.seed_amount,                       -- = position_value(0) + cash_balance
       cash_flow_amount = case when s.id = f.first_snapshot_id then t.seed_amount else 0 end,
       cash_flow_kind   = case when s.id = f.first_snapshot_id then 'seed'        else null end
  from target t
  join first_snapshot f on f.account_id = t.account_id
 where s.account_id = t.account_id;

-- 4-B-2. USD 트랙
with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts_usd a
     where exists (
               select 1 from public.duel_cash_ledger_usd l
                where l.account_id = a.id
                  and l.event_type = 'monthly_deposit'
                  and l.event_date < a.anchor_date)
       and exists (
               select 1 from public.duel_daily_snapshots_usd s
                where s.account_id = a.id)
       and not exists (
               select 1 from public.duel_daily_snapshots_usd s
                where s.account_id = a.id
                  and s.position_value > 0)
       and not exists (
               select 1 from public.duel_cash_ledger_usd l
                where l.account_id = a.id
                  and not (l.event_type = 'seed')
                  and not (l.event_type in ('monthly_deposit', 'reversal')
                           and l.event_date < a.anchor_date))
       and (
               select sum(l.amount) from public.duel_cash_ledger_usd l
                where l.account_id = a.id
                  and l.event_type = 'seed') = a.seed_amount
),
first_snapshot as (
    select distinct on (s.account_id) s.account_id, s.id as first_snapshot_id
      from public.duel_daily_snapshots_usd s
      join target t on t.account_id = s.account_id
     order by s.account_id, s.snapshot_date
)
update public.duel_daily_snapshots_usd s
   set cash_balance     = t.seed_amount,
       total_value      = t.seed_amount,
       cash_flow_amount = case when s.id = f.first_snapshot_id then t.seed_amount else 0 end,
       cash_flow_kind   = case when s.id = f.first_snapshot_id then 'seed'        else null end
  from target t
  join first_snapshot f on f.account_id = t.account_id
 where s.account_id = t.account_id;


-- 4-C. 확인 (읽기 전용)
-- 4-C-1. AUTO 계좌의 스냅샷 행 중 정답과 다른 행 (0행이어야 정상)
--        정답: total_value = cash_balance = seed_amount, position_value = 0,
--              가장 이른 행만 cash_flow_amount = seed_amount·kind 'seed', 나머지는 0·null
with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts a
     where exists (select 1 from public.duel_cash_ledger l
                    where l.account_id = a.id and l.event_type = 'monthly_deposit'
                      and l.event_date < a.anchor_date)
       and exists (select 1 from public.duel_daily_snapshots s where s.account_id = a.id)
       and not exists (select 1 from public.duel_daily_snapshots s
                        where s.account_id = a.id and s.position_value > 0)
       and not exists (select 1 from public.duel_cash_ledger l
                        where l.account_id = a.id
                          and not (l.event_type = 'seed')
                          and not (l.event_type in ('monthly_deposit', 'reversal')
                                   and l.event_date < a.anchor_date))
       and (select sum(l.amount) from public.duel_cash_ledger l
             where l.account_id = a.id and l.event_type = 'seed') = a.seed_amount
),
ranked as (
    select s.*, t.seed_amount,
           row_number() over (partition by s.account_id order by s.snapshot_date) as rn
      from public.duel_daily_snapshots s
      join target t on t.account_id = s.account_id
)
select 'KRW' as track, account_id, snapshot_date, position_value, cash_balance, total_value,
       cash_flow_amount, cash_flow_kind, seed_amount, rn
  from ranked
 where not (
       position_value = 0
   and cash_balance   = seed_amount
   and total_value    = seed_amount
   and ((rn = 1 and cash_flow_amount = seed_amount and cash_flow_kind = 'seed')
        or (rn > 1 and cash_flow_amount = 0 and cash_flow_kind is null))
 )
 order by account_id, snapshot_date;

-- 4-C-2. USD 트랙 — 같은 확인
with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts_usd a
     where exists (select 1 from public.duel_cash_ledger_usd l
                    where l.account_id = a.id and l.event_type = 'monthly_deposit'
                      and l.event_date < a.anchor_date)
       and exists (select 1 from public.duel_daily_snapshots_usd s where s.account_id = a.id)
       and not exists (select 1 from public.duel_daily_snapshots_usd s
                        where s.account_id = a.id and s.position_value > 0)
       and not exists (select 1 from public.duel_cash_ledger_usd l
                        where l.account_id = a.id
                          and not (l.event_type = 'seed')
                          and not (l.event_type in ('monthly_deposit', 'reversal')
                                   and l.event_date < a.anchor_date))
       and (select sum(l.amount) from public.duel_cash_ledger_usd l
             where l.account_id = a.id and l.event_type = 'seed') = a.seed_amount
),
ranked as (
    select s.*, t.seed_amount,
           row_number() over (partition by s.account_id order by s.snapshot_date) as rn
      from public.duel_daily_snapshots_usd s
      join target t on t.account_id = s.account_id
)
select 'USD' as track, account_id, snapshot_date, position_value, cash_balance, total_value,
       cash_flow_amount, cash_flow_kind, seed_amount, rn
  from ranked
 where not (
       position_value = 0
   and cash_balance   = seed_amount
   and total_value    = seed_amount
   and ((rn = 1 and cash_flow_amount = seed_amount and cash_flow_kind = 'seed')
        or (rn > 1 and cash_flow_amount = 0 and cash_flow_kind is null))
 )
 order by account_id, snapshot_date;

-- 4-C-3. 교차 확인 — AUTO 계좌는 정정 뒤 "원장 라이브 잔고(화면의 예수금)" 와 "가장 최근 스냅샷의
--        cash_balance(TWR 입력)" 가 같아야 합니다 (0행이어야 정상. §2 를 먼저 실행했어야 합니다)
with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts a
     where exists (select 1 from public.duel_cash_ledger l
                    where l.account_id = a.id and l.event_type = 'monthly_deposit'
                      and l.event_date < a.anchor_date)
       and exists (select 1 from public.duel_daily_snapshots s where s.account_id = a.id)
       and not exists (select 1 from public.duel_daily_snapshots s
                        where s.account_id = a.id and s.position_value > 0)
       and not exists (select 1 from public.duel_cash_ledger l
                        where l.account_id = a.id
                          and not (l.event_type = 'seed')
                          and not (l.event_type in ('monthly_deposit', 'reversal')
                                   and l.event_date < a.anchor_date))
       and (select sum(l.amount) from public.duel_cash_ledger l
             where l.account_id = a.id and l.event_type = 'seed') = a.seed_amount
),
latest as (
    select distinct on (s.account_id) s.account_id, s.snapshot_date, s.cash_balance
      from public.duel_daily_snapshots s
      join target t on t.account_id = s.account_id
     order by s.account_id, s.snapshot_date desc
)
select 'KRW' as track, x.account_id, x.snapshot_date, x.cash_balance as snapshot_cash,
       (select sum(l.amount) from public.duel_cash_ledger l where l.account_id = x.account_id) as ledger_cash
  from latest x
 where x.cash_balance <> (select sum(l.amount) from public.duel_cash_ledger l where l.account_id = x.account_id);

with target as (
    select a.id as account_id, a.seed_amount
      from public.duel_accounts_usd a
     where exists (select 1 from public.duel_cash_ledger_usd l
                    where l.account_id = a.id and l.event_type = 'monthly_deposit'
                      and l.event_date < a.anchor_date)
       and exists (select 1 from public.duel_daily_snapshots_usd s where s.account_id = a.id)
       and not exists (select 1 from public.duel_daily_snapshots_usd s
                        where s.account_id = a.id and s.position_value > 0)
       and not exists (select 1 from public.duel_cash_ledger_usd l
                        where l.account_id = a.id
                          and not (l.event_type = 'seed')
                          and not (l.event_type in ('monthly_deposit', 'reversal')
                                   and l.event_date < a.anchor_date))
       and (select sum(l.amount) from public.duel_cash_ledger_usd l
             where l.account_id = a.id and l.event_type = 'seed') = a.seed_amount
),
latest as (
    select distinct on (s.account_id) s.account_id, s.snapshot_date, s.cash_balance
      from public.duel_daily_snapshots_usd s
      join target t on t.account_id = s.account_id
     order by s.account_id, s.snapshot_date desc
)
select 'USD' as track, x.account_id, x.snapshot_date, x.cash_balance as snapshot_cash,
       (select sum(l.amount) from public.duel_cash_ledger_usd l where l.account_id = x.account_id) as ledger_cash
  from latest x
 where x.cash_balance <> (select sum(l.amount) from public.duel_cash_ledger_usd l where l.account_id = x.account_id);


-- =============================================================================
-- ⚠️ 여기부터는 사람이 판단합니다 — 4-B 가 손대지 않은 계좌 목록 (읽기 전용)
-- =============================================================================
-- 아래에 나오는 계좌는 잘못된 입금은 받았지만(§1) 스냅샷을 자동으로 고칠 수 없는 계좌입니다.
--   · 'MANUAL: position_value>0' — 가짜 예수금이 섞인 상태에서 실제 매수가 있었을 수 있습니다.
--     그 매수가 정당한 예수금 범위였는지, 스냅샷의 어떤 행부터 어떻게 고칠지는 계좌별로 원장·
--     주문·스냅샷을 함께 보고 오너가 정합니다. 이 파일은 그 값을 지어내지 않습니다(§0-1).
--   · 'MANUAL: 원장에 다른 행' — anchor_date 이후의 정상 정기입금 등이 있어 정답이 seed_amount
--     가 아닙니다. 그 계좌의 올바른 일별 현금은 원장을 날짜별로 누적해 다시 계산해야 합니다.
--   · 'MANUAL: 시드 불일치' — 시드 원장 행이 없거나 amount 가 계좌의 seed_amount 와 다릅니다.
--     그 자체가 별개의 이상이므로 먼저 원인을 봐야 합니다.
-- 원장(§2)은 이미 정정돼 있으므로 이 계좌들의 화면 총자산·예수금은 정상입니다. 남는 것은
-- 저장된 스냅샷(= TWR 입력)뿐입니다.
with wrong_accounts as (
    select distinct l.account_id
      from public.duel_cash_ledger l
      join public.duel_accounts a on a.id = l.account_id
     where l.event_type = 'monthly_deposit' and l.event_date < a.anchor_date
)
select 'KRW' as track,
       case
           when exists (select 1 from public.duel_daily_snapshots s
                         where s.account_id = a.id and s.position_value > 0)
                then 'MANUAL: position_value>0'
           when exists (select 1 from public.duel_cash_ledger l
                         where l.account_id = a.id
                           and not (l.event_type = 'seed')
                           and not (l.event_type in ('monthly_deposit', 'reversal')
                                    and l.event_date < a.anchor_date))
                then 'MANUAL: 원장에 다른 행'
           else 'MANUAL: 시드 불일치'
       end as reason,
       a.id as account_id, a.user_id, a.window_type, a.anchor_date, a.seed_amount,
       (select count(*) from public.duel_daily_snapshots s where s.account_id = a.id) as snapshot_rows,
       (select array_agg(s.snapshot_date order by s.snapshot_date)
          from public.duel_daily_snapshots s
         where s.account_id = a.id and s.position_value > 0)                          as dates_with_positions,
       (select array_agg(l.event_type || ' ' || to_char(l.event_date, 'YYYY-MM-DD') || ' ' || l.amount
                         order by l.event_date, l.id)
          from public.duel_cash_ledger l
         where l.account_id = a.id
           and not (l.event_type = 'seed')
           and not (l.event_type in ('monthly_deposit', 'reversal')
                    and l.event_date < a.anchor_date))                                 as other_ledger_events
  from public.duel_accounts a
  join wrong_accounts w on w.account_id = a.id
 where exists (select 1 from public.duel_daily_snapshots s where s.account_id = a.id)
   and (
        exists (select 1 from public.duel_daily_snapshots s
                 where s.account_id = a.id and s.position_value > 0)
     or exists (select 1 from public.duel_cash_ledger l
                 where l.account_id = a.id
                   and not (l.event_type = 'seed')
                   and not (l.event_type in ('monthly_deposit', 'reversal')
                            and l.event_date < a.anchor_date))
     or (select sum(l.amount) from public.duel_cash_ledger l
          where l.account_id = a.id and l.event_type = 'seed') is distinct from a.seed_amount
   )
 order by reason, a.user_id, a.window_type;

with wrong_accounts as (
    select distinct l.account_id
      from public.duel_cash_ledger_usd l
      join public.duel_accounts_usd a on a.id = l.account_id
     where l.event_type = 'monthly_deposit' and l.event_date < a.anchor_date
)
select 'USD' as track,
       case
           when exists (select 1 from public.duel_daily_snapshots_usd s
                         where s.account_id = a.id and s.position_value > 0)
                then 'MANUAL: position_value>0'
           when exists (select 1 from public.duel_cash_ledger_usd l
                         where l.account_id = a.id
                           and not (l.event_type = 'seed')
                           and not (l.event_type in ('monthly_deposit', 'reversal')
                                    and l.event_date < a.anchor_date))
                then 'MANUAL: 원장에 다른 행'
           else 'MANUAL: 시드 불일치'
       end as reason,
       a.id as account_id, a.user_id, a.window_type, a.anchor_date, a.seed_amount,
       (select count(*) from public.duel_daily_snapshots_usd s where s.account_id = a.id) as snapshot_rows,
       (select array_agg(s.snapshot_date order by s.snapshot_date)
          from public.duel_daily_snapshots_usd s
         where s.account_id = a.id and s.position_value > 0)                          as dates_with_positions,
       (select array_agg(l.event_type || ' ' || to_char(l.event_date, 'YYYY-MM-DD') || ' ' || l.amount
                         order by l.event_date, l.id)
          from public.duel_cash_ledger_usd l
         where l.account_id = a.id
           and not (l.event_type = 'seed')
           and not (l.event_type in ('monthly_deposit', 'reversal')
                    and l.event_date < a.anchor_date))                                 as other_ledger_events
  from public.duel_accounts_usd a
  join wrong_accounts w on w.account_id = a.id
 where exists (select 1 from public.duel_daily_snapshots_usd s where s.account_id = a.id)
   and (
        exists (select 1 from public.duel_daily_snapshots_usd s
                 where s.account_id = a.id and s.position_value > 0)
     or exists (select 1 from public.duel_cash_ledger_usd l
                 where l.account_id = a.id
                   and not (l.event_type = 'seed')
                   and not (l.event_type in ('monthly_deposit', 'reversal')
                            and l.event_date < a.anchor_date))
     or (select sum(l.amount) from public.duel_cash_ledger_usd l
          where l.account_id = a.id and l.event_type = 'seed') is distinct from a.seed_amount
   )
 order by reason, a.user_id, a.window_type;
