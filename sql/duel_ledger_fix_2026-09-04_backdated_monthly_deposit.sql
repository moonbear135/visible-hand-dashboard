-- =============================================================================
-- 결투다! 현금 원장 정정 — 계좌 개설일(anchor_date) 이전 날짜로 잘못 들어간 정기입금
-- (2026-09-04, TASK_HISTORY #193)
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
--   정정 쿼리는 여러 번 실행해도 안전합니다 — 이미 같은 원본 id 로 되돌림 행이 있으면
--   다시 넣지 않습니다(`not exists`). 그래도 1) → 2) 순서는 지켜 주세요.
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
-- ⚠️ 알아 둘 부작용(이 파일이 고치지 않는 것): 이미 저장된 `duel_daily_snapshots` 의
--    총자산·현금은 잘못된 입금이 반영된 값이고, 배치의 TWR 은 `seed`/`monthly_deposit` 만
--    외부 현금흐름으로 봅니다(`utils/duel_batch.py::EXTERNAL_CASH_FLOW_TYPES`). 정정 뒤
--    첫 스냅샷에서 현금이 80만원×N 만큼 줄어드는데 그 날의 cash_flow 는 0 이므로, 그
--    구간의 일간 수익률이 그만큼 마이너스로 잡힐 수 있습니다. 해당 계좌의 스냅샷·TWR 을
--    어떻게 할지는 별도 판단이 필요합니다(이 파일은 원장만 다룹니다).
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
