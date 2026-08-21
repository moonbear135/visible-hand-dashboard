-- =============================================================================
-- 결투 모듈 — 창당 1회 리밸런싱 매도 기능, 스키마 변경 (2026-08-21)
-- =============================================================================
-- 이 파일은 "이미 살아 있는" Supabase 테이블에 변경을 적용하는 마이그레이션입니다.
-- sql/duel_schema.sql 은 "새로 설치한다면 이런 모양이어야 한다"는 최신 기준 문서로
-- 이미 갱신해 두었고, 이 파일은 그 기준에 맞춰 **현재 운영 중인 테이블**을 실제로
-- 고치는 실행 스크립트입니다.
--
-- 실행 방법: Supabase 대시보드 → SQL Editor → 이 파일 내용을 전부 붙여넣고 Run.
-- 전체를 한 번에 실행해도 되고, 번호 순서대로 나눠 실행해도 됩니다(각 블록은 여러 번
-- 실행해도 안전하게 만들었습니다 — 이미 적용된 블록을 다시 돌려도 에러 없이 넘어갑니다).
--
-- ⚠️ 실행 전 Supabase 대시보드에서 백업(스냅샷)이 최근 것인지 한 번 확인하는 것을
--    권장합니다 — 이 프로젝트의 다른 스키마 변경 때와 같은 관례입니다.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) duel_orders.side — 'buy' 고정 CHECK를 'buy'/'sell' 허용으로 넓힙니다.
-- -----------------------------------------------------------------------------
do $$
declare c record;
begin
    for c in
        select con.conname
          from pg_constraint con
          join pg_class rel on rel.oid = con.conrelid
         where rel.relname = 'duel_orders'
           and con.contype = 'c'
           and pg_get_constraintdef(con.oid) like '%side%'
           and pg_get_constraintdef(con.oid) not like '%rebalance_window_index%'
    loop
        execute format('alter table public.duel_orders drop constraint %I', c.conname);
    end loop;
end $$;

alter table public.duel_orders
    add constraint duel_orders_side_check check (side in ('buy', 'sell'));

do $$
declare c record;
begin
    for c in
        select con.conname
          from pg_constraint con
          join pg_class rel on rel.oid = con.conrelid
         where rel.relname = 'duel_orders_usd'
           and con.contype = 'c'
           and pg_get_constraintdef(con.oid) like '%side%'
           and pg_get_constraintdef(con.oid) not like '%rebalance_window_index%'
    loop
        execute format('alter table public.duel_orders_usd drop constraint %I', c.conname);
    end loop;
end $$;

alter table public.duel_orders_usd
    add constraint duel_orders_usd_side_check check (side in ('buy', 'sell'));


-- -----------------------------------------------------------------------------
-- 2) duel_orders / duel_orders_usd — rebalance_window_index 컬럼 + 짝 CHECK + 유니크 인덱스
-- -----------------------------------------------------------------------------
alter table public.duel_orders
    add column if not exists rebalance_window_index integer;

alter table public.duel_orders
    drop constraint if exists duel_orders_rebalance_window_match;
alter table public.duel_orders
    add constraint duel_orders_rebalance_window_match check (
        (side = 'sell' and rebalance_window_index is not null)
        or (side = 'buy' and rebalance_window_index is null)
    );

create unique index if not exists duel_orders_one_sell_per_window
    on public.duel_orders (account_id, rebalance_window_index)
    where side = 'sell' and status <> 'cancelled';

alter table public.duel_orders_usd
    add column if not exists rebalance_window_index integer;

alter table public.duel_orders_usd
    drop constraint if exists duel_orders_usd_rebalance_window_match;
alter table public.duel_orders_usd
    add constraint duel_orders_usd_rebalance_window_match check (
        (side = 'sell' and rebalance_window_index is not null)
        or (side = 'buy' and rebalance_window_index is null)
    );

create unique index if not exists duel_orders_usd_one_sell_per_window
    on public.duel_orders_usd (account_id, rebalance_window_index)
    where side = 'sell' and status <> 'cancelled';


-- -----------------------------------------------------------------------------
-- 3) duel_cash_ledger / duel_cash_ledger_usd — event_type 에 'sell' 추가
-- -----------------------------------------------------------------------------
do $$
declare c record;
begin
    for c in
        select con.conname
          from pg_constraint con
          join pg_class rel on rel.oid = con.conrelid
         where rel.relname = 'duel_cash_ledger'
           and con.contype = 'c'
           and pg_get_constraintdef(con.oid) like '%event_type%'
           and pg_get_constraintdef(con.oid) not like '%amount%'
           and pg_get_constraintdef(con.oid) not like '%order_id%'
    loop
        execute format('alter table public.duel_cash_ledger drop constraint %I', c.conname);
    end loop;
end $$;

alter table public.duel_cash_ledger
    add constraint duel_cash_ledger_event_type_check
        check (event_type in ('seed', 'monthly_deposit', 'buy', 'sell', 'reversal'));

alter table public.duel_cash_ledger
    drop constraint if exists duel_cash_ledger_sign_match;
alter table public.duel_cash_ledger
    add constraint duel_cash_ledger_sign_match check (
        (event_type in ('seed', 'monthly_deposit', 'sell') and amount > 0)
        or (event_type = 'buy' and amount < 0)
        or event_type = 'reversal'
    );

alter table public.duel_cash_ledger
    drop constraint if exists duel_cash_ledger_order_link;
alter table public.duel_cash_ledger
    add constraint duel_cash_ledger_order_link check (
        (event_type in ('buy', 'sell') and order_id is not null)
        or (event_type in ('seed', 'monthly_deposit') and order_id is null)
        or event_type = 'reversal'
    );

do $$
declare c record;
begin
    for c in
        select con.conname
          from pg_constraint con
          join pg_class rel on rel.oid = con.conrelid
         where rel.relname = 'duel_cash_ledger_usd'
           and con.contype = 'c'
           and pg_get_constraintdef(con.oid) like '%event_type%'
           and pg_get_constraintdef(con.oid) not like '%amount%'
           and pg_get_constraintdef(con.oid) not like '%order_id%'
    loop
        execute format('alter table public.duel_cash_ledger_usd drop constraint %I', c.conname);
    end loop;
end $$;

alter table public.duel_cash_ledger_usd
    add constraint duel_cash_ledger_usd_event_type_check
        check (event_type in ('seed', 'monthly_deposit', 'buy', 'sell', 'reversal'));

alter table public.duel_cash_ledger_usd
    drop constraint if exists duel_cash_ledger_usd_sign_match;
alter table public.duel_cash_ledger_usd
    add constraint duel_cash_ledger_usd_sign_match check (
        (event_type in ('seed', 'monthly_deposit', 'sell') and amount > 0)
        or (event_type = 'buy' and amount < 0)
        or event_type = 'reversal'
    );

alter table public.duel_cash_ledger_usd
    drop constraint if exists duel_cash_ledger_usd_order_link;
alter table public.duel_cash_ledger_usd
    add constraint duel_cash_ledger_usd_order_link check (
        (event_type in ('buy', 'sell') and order_id is not null)
        or (event_type in ('seed', 'monthly_deposit') and order_id is null)
        or event_type = 'reversal'
    );


-- -----------------------------------------------------------------------------
-- 4) duel_positions_buy_only() — settled_sell 세션 변수 경로 추가 (KRW/USD 공유 함수)
-- -----------------------------------------------------------------------------
create or replace function public.duel_positions_buy_only()
returns trigger
language plpgsql
as $$
begin
    if new.account_id <> old.account_id or new.ticker <> old.ticker then
        raise exception 'duel_positions: 계좌·종목은 수정할 수 없습니다(다른 포지션으로 둔갑 방지)';
    end if;

    if new.quantity < old.quantity
       and coalesce(current_setting('duel.allow_quantity_decrease', true), 'off') <> 'on'
       and coalesce(current_setting('duel.settled_sell', true), 'off') <> 'on' then
        raise exception
            'duel_positions: 수량을 줄이려면 정당한 사유가 필요합니다 (% → %). 상장폐지 상각·강제정리 같은 관리 경로는 set local duel.allow_quantity_decrease = ''on'' 을, 리밸런싱 매도 정산은 야간 배치가 set local duel.settled_sell = ''on'' 을 같은 트랜잭션에서 먼저 실행하세요',
            old.quantity, new.quantity;
    end if;

    return new;
end;
$$;
-- (create or replace 라 duel_positions/duel_positions_usd 양쪽 트리거가 이 함수를
--  공유하고 있으므로 한 번만 바꾸면 양쪽에 자동 반영됩니다 — 새 트리거를 안 만들어도 됩니다.)


-- -----------------------------------------------------------------------------
-- 5) duel_accounts / duel_accounts_usd — first_holding_date 컬럼 추가
-- -----------------------------------------------------------------------------
alter table public.duel_accounts
    add column if not exists first_holding_date date;

alter table public.duel_accounts_usd
    add column if not exists first_holding_date date;


-- -----------------------------------------------------------------------------
-- 6) 🔴 매도 정산 RPC 2개 (KRW/USD) — `duel.settled_sell` 을 켤 수 있는 유일한 통로
-- -----------------------------------------------------------------------------
-- ⚠️ 이 블록은 위 1~5번(오너가 이미 실행한 스키마 변경)에 **추가로 실행해야 하는 부분**
--    입니다. 4번의 트리거는 `set local duel.settled_sell = 'on'` 이 **같은 트랜잭션에서**
--    먼저 실행됐을 때만 수량 감소를 통과시키는데, 야간 배치는 Supabase 를 PostgREST(REST)
--    로 부르고 REST 요청은 요청마다 트랜잭션이 달라 클라이언트가 세션 변수를 앞세워 보낼
--    문법이 없습니다. 그래서 "세션 변수 켜기 + 수량 줄이기"를 한 호출 안에서 원자적으로
--    처리하는 좁은 함수 두 개를 둡니다(자세한 근거는 sql/duel_schema.sql §9-11 주석).
--    **이 블록을 실행하지 않으면 매도 체결이 매일 밤 트리거에 막혀 실패합니다.**
--    (create or replace 라 여러 번 실행해도 안전합니다.)

create or replace function public.duel_settle_sell_positions(p_rows jsonb)
returns integer
language plpgsql
as $$
declare
    v_expected integer;
    v_updated  integer;
begin
    if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
        raise exception 'duel_settle_sell_positions: 매도 정산 행 목록(jsonb 배열)이 필요합니다 (받은 형태: %)',
            coalesce(jsonb_typeof(p_rows), 'null');
    end if;

    select count(*) into v_expected
      from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric);
    if v_expected = 0 then
        return 0;   -- 매도가 없는 밤은 오류가 아닙니다(정상적으로 대부분의 밤).
    end if;

    -- ① 보유하지 않은 (계좌, 종목)이 섞여 있으면 **아무것도** 반영하지 않습니다.
    if exists (
        select 1
          from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
          left join public.duel_positions p
                 on p.account_id = x.account_id and p.ticker = x.ticker
         where p.id is null
    ) then
        raise exception 'duel_settle_sell_positions: 보유하지 않은 (계좌, 종목)이 들어 있어 매도 정산을 중단합니다(행을 새로 만들지 않습니다)';
    end if;

    -- ② 줄이는 방향만. 0 은 정상(전량 매도), 음수·유지·증가는 전부 거절입니다.
    if exists (
        select 1
          from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
          join public.duel_positions p
            on p.account_id = x.account_id and p.ticker = x.ticker
         where x.quantity is null or x.quantity < 0 or x.quantity >= p.quantity
    ) then
        raise exception 'duel_settle_sell_positions: 매도 정산은 수량을 줄이는 방향만 허용합니다(0 이상 · 현재 수량 미만)';
    end if;

    -- ③ 여기서만 플래그를 켭니다(트랜잭션 지역 변수 — 세 번째 인자 true).
    perform set_config('duel.settled_sell', 'on', true);

    update public.duel_positions p
       set quantity = x.quantity
      from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
     where p.account_id = x.account_id and p.ticker = x.ticker;
    get diagnostics v_updated = row_count;

    -- ④ 같은 트랜잭션에 다른 쓰기가 따라붙어도 플래그가 남아 있지 않게 바로 끕니다.
    perform set_config('duel.settled_sell', 'off', true);

    if v_updated <> v_expected then
        raise exception 'duel_settle_sell_positions: % 행을 정산하려 했는데 % 행만 반영됐습니다 — 전부 되돌립니다',
            v_expected, v_updated;
    end if;

    return v_updated;
end;
$$;

revoke all on function public.duel_settle_sell_positions(jsonb) from public;
grant execute on function public.duel_settle_sell_positions(jsonb) to service_role;

comment on function public.duel_settle_sell_positions(jsonb) is
    '창당 1회 리밸런싱 매도의 야간 정산 전용 RPC(2026-08-21). duel.settled_sell 세션 변수를 함수 안에서만 켰다 끄고 duel_positions.quantity 를 **줄이는 방향으로만** 갱신합니다. PostgREST 는 요청마다 트랜잭션이 달라 set local 을 앞세울 수 없어서, 세션 변수와 update 를 한 호출로 묶은 것입니다. avg_cost 는 건드리지 않고, 없는 포지션은 만들지 않으며, execute 는 service_role 에게만 있습니다.';

create or replace function public.duel_settle_sell_positions_usd(p_rows jsonb)
returns integer
language plpgsql
as $$
declare
    v_expected integer;
    v_updated  integer;
begin
    if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
        raise exception 'duel_settle_sell_positions_usd: 매도 정산 행 목록(jsonb 배열)이 필요합니다 (받은 형태: %)',
            coalesce(jsonb_typeof(p_rows), 'null');
    end if;

    select count(*) into v_expected
      from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric);
    if v_expected = 0 then
        return 0;   -- 매도가 없는 밤은 오류가 아닙니다(정상적으로 대부분의 밤).
    end if;

    -- ① 보유하지 않은 (계좌, 종목)이 섞여 있으면 **아무것도** 반영하지 않습니다.
    if exists (
        select 1
          from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
          left join public.duel_positions_usd p
                 on p.account_id = x.account_id and p.ticker = x.ticker
         where p.id is null
    ) then
        raise exception 'duel_settle_sell_positions_usd: 보유하지 않은 (계좌, 종목)이 들어 있어 매도 정산을 중단합니다(행을 새로 만들지 않습니다)';
    end if;

    -- ② 줄이는 방향만. 0 은 정상(전량 매도), 음수·유지·증가는 전부 거절입니다.
    if exists (
        select 1
          from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
          join public.duel_positions_usd p
            on p.account_id = x.account_id and p.ticker = x.ticker
         where x.quantity is null or x.quantity < 0 or x.quantity >= p.quantity
    ) then
        raise exception 'duel_settle_sell_positions_usd: 매도 정산은 수량을 줄이는 방향만 허용합니다(0 이상 · 현재 수량 미만)';
    end if;

    -- ③ 여기서만 플래그를 켭니다(트랜잭션 지역 변수 — 세 번째 인자 true).
    perform set_config('duel.settled_sell', 'on', true);

    update public.duel_positions_usd p
       set quantity = x.quantity
      from jsonb_to_recordset(p_rows) as x(account_id uuid, ticker text, quantity numeric)
     where p.account_id = x.account_id and p.ticker = x.ticker;
    get diagnostics v_updated = row_count;

    -- ④ 같은 트랜잭션에 다른 쓰기가 따라붙어도 플래그가 남아 있지 않게 바로 끕니다.
    perform set_config('duel.settled_sell', 'off', true);

    if v_updated <> v_expected then
        raise exception 'duel_settle_sell_positions_usd: % 행을 정산하려 했는데 % 행만 반영됐습니다 — 전부 되돌립니다',
            v_expected, v_updated;
    end if;

    return v_updated;
end;
$$;

revoke all on function public.duel_settle_sell_positions_usd(jsonb) from public;
grant execute on function public.duel_settle_sell_positions_usd(jsonb) to service_role;

comment on function public.duel_settle_sell_positions_usd(jsonb) is
    '창당 1회 리밸런싱 매도의 야간 정산 전용 RPC(2026-08-21, §9-11 의 USD 미러). duel.settled_sell 세션 변수를 함수 안에서만 켰다 끄고 duel_positions.quantity 를 **줄이는 방향으로만** 갱신합니다. PostgREST 는 요청마다 트랜잭션이 달라 set local 을 앞세울 수 없어서, 세션 변수와 update 를 한 호출로 묶은 것입니다. avg_cost 는 건드리지 않고, 없는 포지션은 만들지 않으며, execute 는 service_role 에게만 있습니다.';


-- =============================================================================
-- 실행 후 확인용 스니펫 (선택 — 눈으로 한 번 확인하고 싶을 때)
-- =============================================================================
--  ① side 가 넓어졌는지:
--      select conname, pg_get_constraintdef(oid)
--        from pg_constraint
--       where conrelid = 'public.duel_orders'::regclass and contype = 'c';
--
--  ② 창당 1회 유니크 인덱스가 실제로 두 번째 매도 주문을 막는지 (개발용 데이터로만):
--      -- 같은 account_id, 같은 rebalance_window_index 로 side='sell' 행을 두 번 insert
--      -- → 두 번째 insert 가 duel_orders_one_sell_per_window 위반으로 실패해야 정상.
--
--  ③ settled_sell 세션 변수 없이는 여전히 막히는지:
--      update public.duel_positions set quantity = quantity - 1 where id = '<개발용 포지션>';
--      -- 예외로 실패해야 정상.
--      begin;
--        set local duel.settled_sell = 'on';
--        update public.duel_positions set quantity = quantity - 1 where id = '<개발용 포지션>';
--      rollback;
--      -- 이번엔 통과해야 정상.
--
--  ④ 컬럼이 생겼는지:
--      select column_name from information_schema.columns
--       where table_schema = 'public'
--         and table_name in ('duel_accounts', 'duel_accounts_usd')
--         and column_name = 'first_holding_date';
--
--  ⑤ 매도 정산 RPC 2개가 설치됐고 service_role 에게만 execute 가 있는지:
--      select p.proname, pg_get_function_identity_arguments(p.oid) as args,
--             array(select grantee from information_schema.routine_privileges r
--                    where r.specific_name = p.proname || '_' || p.oid) as grantees
--        from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--       where n.nspname = 'public' and p.proname like 'duel_settle_sell_positions%';
-- =============================================================================


-- =============================================================================
-- 7) (선택, 1회성) 기존 계좌의 first_holding_date 과거값 채우기
-- =============================================================================
-- 이 기능이 생기기 전부터 이미 주식을 갖고 있던 계좌는 first_holding_date 가 계속 NULL로
-- 남습니다 — 배치가 "오늘 처음 생긴 보유"만 채우고, 사실이 아닌 오늘 날짜로 채우지
-- 않기 때문입니다(§0-1). 그 계좌들은 첫 매수가 실제로 체결된 날짜를 duel_orders 에서
-- 역산해 채울 수 있습니다: 그 계좌의 filled/partially_filled 매수 주문 중 가장 이른
-- filled_date. 지금 당장 매도 화면을 켜야 하는 게 아니라면, 급하지 않습니다 — 배치가
-- 매일 밤 "채우지 못한 계좌" 경고로 알려주므로 그 목록을 보고 나중에 실행해도 됩니다.
--
-- ⚠️ 여러 번 실행해도 안전합니다(where first_holding_date is null 조건이 이미 채운
--    행을 건드리지 않습니다). 실행 전 위 ④ 스니펫으로 대상 계좌 수를 먼저 확인하세요.
update public.duel_accounts a
   set first_holding_date = (
       select min(o.filled_date)
         from public.duel_orders o
        where o.account_id = a.id
          and o.side = 'buy'
          and o.status in ('filled', 'partially_filled')
          and o.filled_date is not null
   )
 where a.first_holding_date is null
   and exists (
       select 1 from public.duel_positions p
        where p.account_id = a.id and p.quantity > 0
   );

update public.duel_accounts_usd a
   set first_holding_date = (
       select min(o.filled_date)
         from public.duel_orders_usd o
        where o.account_id = a.id
          and o.side = 'buy'
          and o.status in ('filled', 'partially_filled')
          and o.filled_date is not null
   )
 where a.first_holding_date is null
   and exists (
       select 1 from public.duel_positions_usd p
        where p.account_id = a.id and p.quantity > 0
   );
-- =============================================================================
