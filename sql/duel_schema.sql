-- =============================================================================
--  ⚔️ "결투다!" (모의투자 대결 · 4번째 모듈) — Supabase 스키마 + Row Level Security
--  파일: sql/duel_schema.sql   (DUEL_MODULE_WORK_ORDER.md 1단계)
-- =============================================================================
--
--  ▶ 이건 앱이 실행하는 코드가 아닙니다. **오너가 Supabase 대시보드에서 1회 수동 실행**하는
--    설정 스크립트입니다. (`sql/scorecard_schema.sql` · `sql/report_schema.sql` 과 같은 방식)
--
--  실행 방법
--    1. https://supabase.com → "내 성적표"·"리포트"용으로 이미 쓰고 있는 **같은 프로젝트**를
--       엽니다. 새 프로젝트를 만들지 마세요 — 이 표들은 기존 `auth.users` 를 참조합니다.
--    2. 좌측 메뉴 → SQL Editor → New query
--    3. 이 파일 전체를 붙여넣고 Run
--    4. 좌측 메뉴 → Table Editor 에서 아래 **10개 표**와 각각의 "RLS enabled" 표시를 눈으로 확인
--         비공개(계좌 소유자 전용)
--           · public.duel_accounts          (§1)  가상계좌 — 사용자당 M1/M3/M6 정확히 3개
--           · public.duel_positions         (§2)  가상 보유 포지션 (매수 전용)
--           · public.duel_orders            (§3)  예약 주문 (수량 기준, D+1 종가 체결)
--           · public.duel_cash_ledger       (§4)  현금 원장 — **append-only**
--           · public.duel_daily_snapshots   (§5)  계좌 × 거래일 합계 스냅샷 (+ 현금흐름)
--           · public.duel_holding_snapshots (§5)  계좌 × 종목 × 거래일 상세 스냅샷
--           · public.duel_nicknames         (§6)  무작위 닉네임 (비공개 대응표)
--           · public.duel_public_consent    (§7)  공개 동의 상태 (boolean 7개)
--         발행 전용 공개표(로그인 사용자 전체가 읽기만)
--           · public.duel_public_leaderboard (§8) 순위표
--           · public.duel_public_holdings    (§8) 보유종목 상세
--    5. 맨 아래 §10 자가 점검 쿼리를 실행해 결과를 눈으로 확인
--
--  ⚠️ 이 스크립트는 **여러 번 실행해도 안전하도록**(idempotent) 작성했습니다.
--     기존 데이터를 지우는 DROP TABLE 은 일부러 넣지 않았습니다.
--
-- -----------------------------------------------------------------------------
--  🔴 이 모듈이 기존 두 모듈과 결정적으로 다른 점 세 가지
-- -----------------------------------------------------------------------------
--  ① **앱이 사용자 대신 상태를 바꿉니다**(주문 → 체결 → 잔고). `holdings` 처럼 "사용자가
--     입력한 것을 그대로 보관"하는 표가 아니라, **야간 배치가 계산해서 쓰는 표**가 대부분입니다.
--     그래서 아래 RLS 는 표마다 다릅니다 — 사용자가 직접 쓰는 표는 `duel_orders` 와
--     `duel_public_consent` 둘뿐이고, 나머지는 **사용자에게 select 만** 줍니다.
--     이유는 단순합니다: 현금 원장이나 포지션에 사용자 insert 를 열어 주면, 화면을 거치지
--     않는 직접 호출(anon key 는 공개된 키입니다)로 **자기 계좌에 가상 현금을 무한히 넣거나
--     사지도 않은 주식을 만들 수 있습니다.** 그 값은 그대로 스냅샷 → 공개 순위표로 흘러갑니다.
--     (§0-3-9 — 이미 알려진 기법에는 예외 없이 방어. §0-1 — 사실이 아닌 숫자를 만들지 않기.)
--
--  ② **가상 자산은 실제 자산 표와 물리적으로 분리**합니다. `public.holdings` 를 재사용하지
--     않습니다(작업지시서 "재사용하면 안 되는 것"). 컬럼 타입·RLS **관례만** 베끼고 표는
--     새로 만듭니다 — 그래야 훗날 공개 순위표의 읽기 경로가 실제 자산 표를 스칠 구조 자체가
--     생기지 않습니다(§0-3-8).
--
--  ③ **공개는 권한 완화가 아니라 별도 발행표**입니다(§8). 원본 표의 RLS 는 한 글자도
--     느슨해지지 않습니다. 배치(service_role)가 동의 범위 안의 필드만 뽑아 발행표에 쓰고,
--     순위표 화면은 그 두 표만 읽습니다. 읽기 경로에 버그가 나도 **의도적으로 발행된 것
--     이상은 물리적으로 존재하지 않습니다.**
--
-- -----------------------------------------------------------------------------
--  📝 작업지시서 1단계 초안에서 **바꾼 것**(실제 구현하며 발견한 구멍 · 전부 아래 각 절에 근거)
-- -----------------------------------------------------------------------------
--   (a) RLS 를 표마다 다르게 잡았습니다 — 위 ①. 초안은 "사용자 본인 행 CRUD"로 뭉뚱그렸는데,
--       그대로 하면 현금·포지션 위조가 가능합니다.
--   (b) `duel_cash_ledger` 에 **update 금지 트리거**를 넣었습니다. 초안은 "append-only 로
--       쓰세요"라고 서술만 했는데, 서술은 강제가 아닙니다(§0-3-9). 정정은 반대 부호
--       `reversal` 행으로만 합니다.
--   (c) 시드 멱등성 인덱스를 추가했습니다. 초안은 매월 입금만 막았는데, 시드 중복도 같은
--       사고입니다(계좌당 1행이어야 함). §4-1.
--   (d) `duel_orders` 에 **상태 전이 가드 트리거**를 넣었습니다. 초안은 "배치가 집어간 뒤에는
--       수정·취소를 막는다"를 화면 로직으로만 요구했는데, 화면은 마지막 방어선이 아닙니다.
--   (e) `duel_public_consent` 에 `final_confirmed` CHECK(5개 전부 동의해야 최종확인 가능)와
--       `revoked_at` 되돌리기 금지 트리거를 넣었습니다. 5-2 "전부 아니면 전무" 규칙과 5-8
--       "3개월 재동의 차단"을 DB 가 강제하지 않으면 화면 버그 한 번에 무너집니다.
--   (f) 인덱스를 실제 질의 패턴대로 추가했습니다(배치의 "그날 pending 주문", 철회 시
--       "이 닉네임의 발행 행 전부 삭제" 등). 초안에는 인덱스가 하나도 없었습니다.
--   (g) `duel_cash_ledger.order_id` 의 FK 를 **on delete no action(기본값)으로 명시**했습니다.
--       근거는 §4 주석 참고(cascade / restrict 를 쓰면 안 되는 이유가 각각 있습니다).
--   (h) `duel_daily_snapshots.cash_flow_kind` 에 `'mixed'` 를 추가했습니다. 근거는 §5 주석.
--   (i) `duel_public_holdings` 에 `window_type` 을 넣어 순위표와 모양을 맞췄습니다(§8-2).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 0. 확장 기능 (gen_random_uuid). Supabase 프로젝트에는 보통 이미 켜져 있습니다.
-- -----------------------------------------------------------------------------
create extension if not exists pgcrypto;


-- -----------------------------------------------------------------------------
-- 0-1. updated_at 자동 갱신 함수
-- -----------------------------------------------------------------------------
--  `report_set_updated_at()` 과 같은 역할이지만 **이 파일 전용**으로 따로 둡니다. 세
--  스크립트를 어떤 순서로 실행해도 서로 의존하지 않게 하려는 것이고, 이름이 달라 충돌하지
--  않습니다(`report_schema.sql` §2 와 같은 판단).
--
--  ⚠️ RLS 정책이 공통으로 쓰는 소유자 판정 함수 `duel_account_is_mine()` 은 여기가 아니라
--     §9-0 에 있습니다 — language sql 함수는 **생성 시점에 본문의 테이블 참조를 검사**하므로
--     duel_accounts 가 아직 없는 이 자리에 두면 스크립트가 통째로 실패합니다.
-- -----------------------------------------------------------------------------
create or replace function public.duel_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;


-- =============================================================================
-- 1. duel_accounts — 가상계좌 (사용자당 M1/M3/M6 정확히 3개)
-- =============================================================================
--  · unique (user_id, window_type) — 사용자당 창 유형별 1개, 즉 **최대 3개**.
--    `holdings` 의 unique (user_id, market, ticker) 와 같은 발상입니다.
--  · currency 를 별도 CHECK 컬럼으로 두는 이유도 `holdings` 와 같습니다 —
--    **원화와 달러가 섞이는 경로를 애초에 만들지 않기 위해서**(§0-1). v1 에 USD 가 없어도
--    컬럼은 둡니다. ⚠️ 이 앱에는 **환율 시계열이 없습니다.** 달러 계좌를 원화 순위표에
--    올리려면 환율을 지어내야 하고 그건 §0-1 정면 위반이라, v1 에서 시도하지 마세요.
--  · seed_amount 는 v1 에서 사용자가 바꿀 수 없습니다(2-1-3). 컬럼으로 둔 이유는 "그 계좌가
--    실제로 얼마로 시작했는지"가 나중에 계산이 아니라 **기록**으로 남아야 하기 때문입니다
--    (상수를 나중에 바꾸면 과거 계좌의 시작 금액을 복원할 수 없습니다).
--    ⚠️ **default 를 일부러 두지 않았습니다.** 금액 1천만원의 단일 출처는 앱 상수
--       `utils/duel_rules.py::SEED_AMOUNT_KRW` 하나입니다. DB 에도 숫자를 박아두면 둘 중
--       하나만 바뀌는 날 조용히 어긋납니다(§0-3-10 — `sql/scorecard_schema.sql` §8 이
--       하루 한도 숫자를 DB 에 적지 않은 것과 정확히 같은 판단). 그래서 앱이 항상 명시적으로
--       넣습니다. 매월 입금액(80만원)도 같은 이유로 DB 어디에도 없습니다.
--  · anchor_date 는 입금·정산 리듬의 기준일(계좌 생성일)입니다. 매수 창의 길이는 사실상
--    무제한이라(2-3) 이 날짜가 매수 가부를 막지는 않습니다 — 라벨이자 기준점입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_accounts (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users (id) on delete cascade,
    window_type  text not null check (window_type in ('M1', 'M3', 'M6')),
    seed_amount  numeric(20, 6) not null check (seed_amount > 0),   -- default 없음(위 주석 참고)
    currency     text not null default 'KRW' check (currency = 'KRW'),
    anchor_date  date not null,
    status       text not null default 'active' check (status in ('active', 'closed')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    constraint duel_accounts_user_window_unique unique (user_id, window_type)
);

-- ⚠️ user_id 단독 인덱스를 따로 만들지 않았습니다 — 위 unique 제약이 만드는
--    (user_id, window_type) 인덱스가 user_id 로 시작하므로 "내 계좌 전부" 질의를 이미
--    커버합니다. 쓰기 비용이 있는 인덱스를 중복으로 두지 않습니다(report_schema.sql §8 의
--    같은 판단).
create index if not exists duel_accounts_status_idx
    on public.duel_accounts (status);   -- 배치의 "활성 계좌 전체" 집합 연산용(§0-3-2)

drop trigger if exists duel_accounts_set_updated_at on public.duel_accounts;
create trigger duel_accounts_set_updated_at
    before update on public.duel_accounts
    for each row execute function public.duel_set_updated_at();

comment on table public.duel_accounts is
    '결투다! 가상계좌. 사용자당 M1/M3/M6 정확히 3개, 시드 1천만원 고정, 원화 전용. 실제 자산(holdings)과 물리적으로 분리된 표입니다.';
comment on column public.duel_accounts.seed_amount is
    '개설 시점의 시드머니. 계산으로 복원하지 않고 기록으로 남깁니다(상수를 나중에 바꿔도 과거 계좌가 흔들리지 않게). DB default 없음 — 금액의 단일 출처는 앱 상수 utils/duel_rules.py::SEED_AMOUNT_KRW 입니다.';
comment on column public.duel_accounts.currency is
    'v1 은 KRW 만. 환율 시계열이 이 앱에 없으므로 USD 계좌를 만들면 환율을 지어내야 합니다(§0-1). CHECK 로 그 경로를 차단합니다.';


-- =============================================================================
-- 2. duel_positions — 가상 보유 포지션 (매수 전용)
-- =============================================================================
--  · **numeric(20, 6) 고정** — `holdings.avg_purchase_price` 가 float 이 아닌 이유를 그대로
--    물려받습니다(§0-3-10). 가중평균을 수십 번 재계산하면 float 는 평단가가 조용히 틀어집니다.
--  · 수량도 numeric 입니다. v1 의 체결은 **항상 정수 주식**만 만들지만, 무상증자·액면분할
--    조정(3-4)이 들어오면 소수가 생길 수 있어 타입을 미리 열어 둡니다.
--  · quantity >= 0 (> 0 이 아님) — 상장폐지 상각(3-1)이나 유니버스 이탈 강제정리(3-3) 후에도
--    **행을 지우지 않고** 남겨야 손실이 손실로 보입니다. 0주 포지션이 정상 상태입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_positions (
    id            uuid primary key default gen_random_uuid(),
    account_id    uuid not null references public.duel_accounts (id) on delete cascade,
    ticker        text not null check (length(ticker) between 1 and 20),
    stock_name    text not null,
    quantity      numeric(20, 6) not null check (quantity >= 0),
    avg_cost      numeric(20, 6) not null check (avg_cost >= 0),
    status        text not null default 'active' check (status in ('active', 'delisted')),
    delisted_date date,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    constraint duel_positions_account_ticker_unique unique (account_id, ticker),

    -- 🔴 "상장폐지 확정"과 "가격 수집 실패"를 절대 같은 모양으로 두지 않습니다(§0-1 / 3-2).
    --    status='delisted' 인데 날짜가 없거나, 날짜만 있고 status 가 active 인 행은
    --    "누가 언제 확인한 상장폐지인지" 알 수 없는 유령 상태라 DB 에서 막습니다.
    constraint duel_positions_delisted_match check (
        (status = 'delisted' and delisted_date is not null)
        or (status <> 'delisted' and delisted_date is null)
    )
);

-- ⚠️ 인덱스는 unique 제약이 만드는 (account_id, ticker) 하나로 충분합니다. 이 표의 질의는
--    항상 "이 계좌의 포지션 전부"(account_id 접두) 아니면 upsert 충돌 판정입니다.

drop trigger if exists duel_positions_set_updated_at on public.duel_positions;
create trigger duel_positions_set_updated_at
    before update on public.duel_positions
    for each row execute function public.duel_set_updated_at();


-- -----------------------------------------------------------------------------
-- 2-1. 🔐 매도 금지의 DB 레벨 강제 (작업지시서 1-2 마지막 항목)
-- -----------------------------------------------------------------------------
--  이 모듈에 매도는 **영원히 없습니다**. 화면 로직·배치 로직에 실수가 있어도 수량이
--  줄어들지 않게 DB 가 마지막으로 한 번 더 막습니다(§0-3-9 의 이중 방어).
--
--  다만 **관리 경로**는 열어 둬야 합니다 — 작업지시서가 예외로 인정한 두 가지입니다.
--    · 3-1 상장폐지 상각 (평가액 0 확정)
--    · 3-3 유니버스 500위 밖 이탈 종목의 강제 정리
--    · 3-4 액면병합·감자처럼 주식 수 자체가 줄어드는 기업행위 조정
--  작업지시서가 제안한 대로 **세션 변수 경유**로 구현했습니다. 관리자는 같은 트랜잭션 안에서
--      set local duel.allow_quantity_decrease = 'on';
--  를 먼저 실행해야 합니다. 역할(role) 검사로 하지 않은 이유: 야간 체결 배치도 service_role
--  로 도는데, **그 배치조차 수량을 줄일 일이 없어야** 하기 때문입니다. 세션 변수는 "지금
--  이 한 트랜잭션에서 의도적으로 줄인다"를 사람이 명시적으로 선언하게 만듭니다.
--
--  🔴 delete 로 우회하는 길은 아래 §9 에서 **권한 자체를 주지 않는 것**으로 막습니다.
--     (여기에 BEFORE DELETE 트리거를 걸면 계정 탈퇴 시의 on delete cascade 까지 막혀서
--      개인정보 정리 경로가 끊깁니다 — cascade 는 표 소유자 권한으로 돌아 RLS·권한을
--      우회하므로, "정책·권한을 안 주는" 방식이 정확히 원하는 결과를 냅니다.)
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
       and coalesce(current_setting('duel.allow_quantity_decrease', true), 'off') <> 'on' then
        raise exception
            'duel_positions: 이 모듈은 매수 전용이라 수량을 줄일 수 없습니다 (% → %). 상장폐지 상각·강제정리 같은 관리 경로는 같은 트랜잭션에서 set local duel.allow_quantity_decrease = ''on'' 을 먼저 실행하세요',
            old.quantity, new.quantity;
    end if;

    return new;
end;
$$;

drop trigger if exists duel_positions_no_sell on public.duel_positions;
create trigger duel_positions_no_sell
    before update on public.duel_positions
    for each row execute function public.duel_positions_buy_only();

comment on table public.duel_positions is
    '결투다! 가상 보유 포지션. 매수 전용 — quantity 감소는 트리거가 막고, 관리 경로만 세션 변수(duel.allow_quantity_decrease)로 예외 허용. 쓰기는 배치(service_role)만, 사용자는 읽기 전용.';
comment on column public.duel_positions.avg_cost is
    '가중평균 매입단가. holdings.avg_purchase_price 와 같은 규칙·같은 타입(numeric(20,6))입니다 — float 로 두면 반복 매수한 계좌의 평단가가 조용히 틀어집니다.';
comment on column public.duel_positions.quantity is
    '0 이어도 행을 지우지 않습니다. 상장폐지 상각·강제정리 이후에도 손실이 손실로 보여야 하기 때문입니다(3-1).';


-- =============================================================================
-- 3. duel_orders — 예약 주문 (수량 기준, D일 접수 → D+1 종가 체결)
-- =============================================================================
--  · **주문은 "얼마어치"가 아니라 "몇 주"입니다**(2026-08-19 오너 확정). 최초 설계안의
--    금액 입력(order_amount_krw)은 폐기됐습니다.
--  · `side` 에 check (side = 'buy') 를 거는 건 장식이 아닙니다. **"나중에 매도 넣을 때 이
--    컬럼만 바꾸면 되지"라는 생각을 물리적으로 막기 위한 표시**입니다.
--  · `fail_reason` 은 반드시 채웁니다. 주문이 조용히 사라지는 경로가 하나라도 있으면
--    §0-1 위반입니다. 아래 CHECK 로 "실패/부분체결인데 사유가 비어 있는 행"을 막습니다.
--  · `target_date` = 이 주문이 귀속되는 **거래일(D+1)**. 저장 시점에 앱이 채웁니다
--    (`utils/duel_rules.resolve_fill_trading_day()` — 거래일 캘린더를 코드에 넣지 않고
--     확정된 거래일 목록을 인자로 받는 순수 함수입니다. §0-1: 공휴일 하드코딩 금지).
--  · 체결가는 **D+1 종가**입니다. D 종가는 접수 시간대(18:00:01~22:00:00)에 이미 세상에
--    공개된 값이라, 그걸로 체결하면 "이미 아는 가격으로 매매"가 됩니다(§0-3-1 위반, 2-4).
-- -----------------------------------------------------------------------------
create table if not exists public.duel_orders (
    id                 uuid primary key default gen_random_uuid(),
    account_id         uuid not null references public.duel_accounts (id) on delete cascade,
    ticker             text not null check (length(ticker) between 1 and 20),
    stock_name         text not null,
    requested_quantity integer not null check (requested_quantity > 0),
    side               text not null default 'buy' check (side = 'buy'),
    status             text not null default 'pending'
                       check (status in
                           ('pending', 'filled', 'partially_filled', 'cancelled', 'expired')),
    saved_at           timestamptz not null default now(),
    last_edited_at     timestamptz,
    target_date        date,
    filled_date        date,
    filled_price       numeric(20, 6) check (filled_price is null or filled_price > 0),
    filled_quantity    integer        check (filled_quantity is null or filled_quantity >= 0),
    filled_amount      numeric(20, 6) check (filled_amount is null or filled_amount >= 0),
    fail_reason        text,

    -- 부분체결은 요청보다 적게 체결된 것이지, 더 많이 체결될 수는 없습니다.
    constraint duel_orders_filled_within_request check (
        filled_quantity is null or filled_quantity <= requested_quantity
    ),

    -- 🔴 "조용히 사라지는 주문" 금지(§0-1). 전량체결이 아닌 종결 상태에는 사람이 읽을
    --    사유 문장이 반드시 남아야 합니다.
    constraint duel_orders_reason_required check (
        status in ('pending', 'filled')
        or (fail_reason is not null and length(btrim(fail_reason)) > 0)
    ),

    -- 체결 결과 4개 필드는 **함께 채워지거나 함께 비어 있어야** 합니다. 하나만 들어 있는
    -- 행은 "얼마에 몇 주가 언제 체결됐는지" 중 일부를 모르는 상태라, 나중에 집계하는
    -- 사람마다 다른 숫자가 나옵니다(report_schema.sql §8 의 priced_match 와 같은 발상).
    constraint duel_orders_fill_fields_together check (
        (filled_date is null and filled_price is null
             and filled_quantity is null and filled_amount is null)
        or (filled_date is not null and filled_price is not null
             and filled_quantity is not null and filled_amount is not null)
    ),

    -- 상태와 체결 결과의 아귀가 맞는지. filled/partially_filled 는 반드시 체결 결과가 있고,
    -- pending 은 반드시 없습니다(저장 시점에 현금을 차감하지 않으므로 — 2-4-4).
    constraint duel_orders_status_fill_match check (
        (status in ('filled', 'partially_filled') and filled_quantity is not null
             and filled_quantity > 0)
        or (status = 'pending' and filled_quantity is null)
        or status in ('cancelled', 'expired')
    )
);

-- 🔎 배치가 실제로 던지는 질의는 딱 하나입니다: "이 거래일에 귀속된 pending 주문 전부를
--    saved_at 빠른 순서대로"(2-4-6 의 FIFO 예수금 배정). 부분 인덱스로 만들면 체결이 끝난
--    과거 주문(대부분)이 인덱스에서 빠져 계속 작게 유지됩니다.
create index if not exists duel_orders_pending_target_idx
    on public.duel_orders (target_date, saved_at)
    where status = 'pending';

-- 화면의 "내 주문 내역"은 계좌별 최신순입니다.
create index if not exists duel_orders_account_saved_idx
    on public.duel_orders (account_id, saved_at desc);


-- -----------------------------------------------------------------------------
-- 3-1. 🔐 주문 상태 전이 가드 (초안에서 추가 — 위 머리말 (d))
-- -----------------------------------------------------------------------------
--  작업지시서 2-4-7: "pending 주문은 접수 시간대 안에서 자유롭게 수정·취소할 수 있고,
--  접수 시간대가 끝나면 D+1 체결 대상으로 확정되어 더 이상 손댈 수 없다."
--
--  시각(18:00:01~22:00:00) 판정은 KST 계산이 필요해 앱(`utils/duel_rules.resolve_order_window`)
--  이 합니다. **DB 가 대신 지키는 건 시각이 아니라 "되돌릴 수 없는 것"입니다**:
--    · 이미 종결된 주문(filled/partially_filled/cancelled/expired)은 누구도 다시 못 고칩니다.
--      → 배치와 사용자가 같은 행을 동시에 건드리는 경합에서, 배치가 먼저 처리한 주문을
--        사용자가 뒤늦게 "취소"로 덮어쓰는 사고를 막습니다.
--    · 계좌·종목·side·최초 저장시각은 어떤 경로로도 바뀌지 않습니다(주문의 정체성).
--    · **사용자 세션은 체결 결과 필드를 쓸 수 없습니다.** 열어 두면 "체결된 적 없는 체결"을
--      스스로 적어 넣을 수 있고, 그건 §0-1 이 금지하는 지어낸 값입니다. 체결 결과를 쓰는
--      주체는 야간 배치(service_role)뿐입니다.
--
--  ⚠️ service_role 은 RLS 는 우회하지만 **트리거는 우회하지 않습니다.** 그래서 배치 경로는
--     current_user 로 식별합니다 — PostgREST 는 요청마다 anon/authenticated/service_role 로
--     역할을 전환하므로 current_user 가 그대로 그 역할 이름이 됩니다. SQL Editor(postgres)와
--     테이블 소유자도 관리 경로로 인정합니다.
-- -----------------------------------------------------------------------------
create or replace function public.duel_orders_guard()
returns trigger
language plpgsql
as $$
declare
    is_batch boolean := current_user in ('service_role', 'postgres', 'supabase_admin');
begin
    if old.status <> 'pending' then
        raise exception
            'duel_orders: 이미 %(으)로 종결된 주문은 수정할 수 없습니다(배치 처리 이후 변경 금지)',
            old.status;
    end if;

    if new.account_id <> old.account_id
       or new.ticker <> old.ticker
       or new.side <> old.side
       or new.saved_at <> old.saved_at then
        raise exception 'duel_orders: 계좌·종목·매매구분·최초저장시각은 수정할 수 없습니다';
    end if;

    if not is_batch then
        if new.status not in ('pending', 'cancelled') then
            raise exception
                'duel_orders: 사용자는 주문을 수정하거나 취소만 할 수 있습니다(체결 상태는 배치만 기록)';
        end if;
        if new.filled_date is distinct from old.filled_date
           or new.filled_price is distinct from old.filled_price
           or new.filled_quantity is distinct from old.filled_quantity
           or new.filled_amount is distinct from old.filled_amount
           or new.target_date is distinct from old.target_date then
            raise exception
                'duel_orders: 체결 결과와 귀속 거래일은 배치만 기록합니다(§0-1 — 없던 체결을 지어내지 않기)';
        end if;
    end if;

    return new;
end;
$$;

drop trigger if exists duel_orders_transition_guard on public.duel_orders;
create trigger duel_orders_transition_guard
    before update on public.duel_orders
    for each row execute function public.duel_orders_guard();

comment on table public.duel_orders is
    '결투다! 예약 주문(수량 기준). 저장 = 예약이지 체결이 아니며, 귀속 거래일(D+1)의 확정 종가로 야간 배치가 체결합니다. 사용자는 pending 상태에서만 수량 수정·취소 가능.';
comment on column public.duel_orders.side is
    '''buy'' 고정. CHECK 는 장식이 아니라 "나중에 매도를 여기에 얹지 말라"는 물리적 표시입니다 — 이 모듈에 매도는 없습니다.';
comment on column public.duel_orders.target_date is
    '이 주문이 귀속되는 거래일(D+1). 앱이 확정 거래일 목록을 보고 채웁니다(utils/duel_rules.resolve_fill_trading_day). 거래일 캘린더를 코드/DB 에 하드코딩하지 않습니다(§0-1). ⚠️ insert 시점의 값은 DB 가 검증할 수 없습니다 — DB 는 거래일을 모르기 때문입니다. duel_db 의 저장 함수가 반드시 서버측에서 계산한 값으로 덮어써야 합니다(사용자가 유리한 날짜를 골라 넣는 경로를 남기지 않기).';
comment on column public.duel_orders.filled_quantity is
    '실제 체결 수량. 예수금이 모자라면 floor(가용현금/종가) 만큼만 부분체결되어 requested_quantity 보다 작을 수 있습니다. 0주면 status=''expired''.';
comment on column public.duel_orders.fail_reason is
    '부분체결·만료·취소의 사유를 사람이 읽을 문장으로. 비워 두는 것을 CHECK 로 막습니다 — 주문이 조용히 사라지는 경로를 만들지 않기 위해서입니다(§0-1).';


-- =============================================================================
-- 4. duel_cash_ledger — 현금 원장 (**append-only**)
-- =============================================================================
--  **잔고 컬럼 하나를 두고 UPDATE 하는 방식을 쓰지 않습니다.** 현금 잔고는 항상
--  `sum(amount)` 로 계산합니다.
--
--  이유는 avg_cost 를 float 대신 numeric(20,6) 으로 잡은 것과 **같은 규율**입니다:
--  숫자·상태가 **되돌릴 수 없게 망가지는 것**을 구조적으로 막는 것. 잔고 컬럼 방식에서는
--  체결 로직에 버그가 한 번 나면 잔고가 조용히 어긋나고, 나중에 발견해도 "원래 얼마였어야
--  하는지"를 복원할 방법이 없습니다. 원장 방식이면 **반대 부호의 `reversal` 행을 한 줄
--  덧붙여 정정**할 수 있고, 무슨 일이 있었는지도 함께 남습니다.
--
--  성능 걱정은 하지 않습니다 — 계좌당 연간 수십~수백 행 수준입니다.
--
--  ⚠️ `rollover`(이월)를 이벤트로 만들지 않았습니다. **이월은 돈의 이동이 아닙니다** —
--     안 쓴 현금이 계좌에 그냥 남아 있는 상태일 뿐입니다. 금액 있는 원장 행으로 남기면
--     잔고가 이중 계상되고 TWR 의 현금흐름 판정까지 오염됩니다. 화면의 "이월 금액"은
--     원장 행이 아니라 **계산해서 표시하는 값**입니다. 이 누락은 의도적입니다.
--
--  ⚠️ event_type 에 매도가 없다는 점도 확인하세요. 'reversal' 은 정정 전용입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_cash_ledger (
    id         bigserial primary key,
    account_id uuid not null references public.duel_accounts (id) on delete cascade,
    event_type text not null
               check (event_type in ('seed', 'monthly_deposit', 'buy', 'reversal')),
    amount     numeric(20, 6) not null,   -- 입금은 +, 매수는 −
    event_date date not null,             -- KST 기준 날짜 (DB 의 current_date 는 UTC 라 안 씁니다)

    -- ⚠️ FK 를 일부러 **on delete no action(기본값)** 으로 둡니다.
    --      · cascade 로 두면 주문 한 건을 지웠을 때 그 매수 원장 행까지 사라져 잔고가
    --        조용히 어긋납니다(원장이 원장이 아니게 됩니다).
    --      · restrict 로 두면 즉시 검사라, 계정 탈퇴 시 duel_orders 와 duel_cash_ledger 가
    --        같은 statement 안에서 함께 cascade 삭제될 때 삭제 순서에 따라 실패할 수 있습니다.
    --    no action 은 statement 끝에서 검사하므로 둘 다 사라진 시점에 통과합니다.
    order_id   uuid references public.duel_orders (id),
    memo       text,
    created_at timestamptz not null default now(),

    -- 방향이 뒤집힌 행을 막습니다. 시드·정기입금은 반드시 +, 매수는 반드시 −.
    -- (reversal 은 정정이라 양쪽 부호가 다 필요하므로 제약하지 않습니다.)
    constraint duel_cash_ledger_sign_match check (
        (event_type in ('seed', 'monthly_deposit') and amount > 0)
        or (event_type = 'buy' and amount < 0)
        or event_type = 'reversal'
    ),

    -- 매수 행은 어떤 주문에서 나왔는지가 반드시 남아야 추적이 됩니다. 반대로 입금 행에
    -- 주문이 붙어 있으면 그건 잘못 만든 행입니다.
    constraint duel_cash_ledger_order_link check (
        (event_type = 'buy' and order_id is not null)
        or (event_type in ('seed', 'monthly_deposit') and order_id is null)
        or event_type = 'reversal'
    )
);

-- 잔고는 항상 "이 계좌의 전 기간 합계"이고, 스냅샷은 "이 계좌의 이 날짜"를 봅니다.
create index if not exists duel_cash_ledger_account_date_idx
    on public.duel_cash_ledger (account_id, event_date);

-- -----------------------------------------------------------------------------
-- 4-1. 멱등성 — 배치가 두 번 돌아도 돈이 두 번 들어오지 않게 (2-2-6)
-- -----------------------------------------------------------------------------
--  ▶ 매월 입금: 계좌 × 해당 월 10일에 1행. 부분 유니크 인덱스라 매수 행(하루 여러 건이
--    정상)에는 영향이 없습니다.
--  ▶ 시드: 초안에는 없었지만 **같은 사고**입니다(위 머리말 (c)). 시드는 계좌당 정확히
--    1행이어야 하므로 날짜를 조건에 넣지 않고 계좌 단위로 막습니다 — 날짜까지 포함하면
--    "다른 날짜로 시드 한 번 더" 가 통과해 버립니다.
-- -----------------------------------------------------------------------------
create unique index if not exists duel_cash_ledger_monthly_deposit_unique
    on public.duel_cash_ledger (account_id, event_date)
    where event_type = 'monthly_deposit';

create unique index if not exists duel_cash_ledger_seed_unique
    on public.duel_cash_ledger (account_id)
    where event_type = 'seed';

-- -----------------------------------------------------------------------------
-- 4-2. 🔐 append-only 강제 (초안에서 추가 — 위 머리말 (b))
-- -----------------------------------------------------------------------------
--  "append-only 로 쓰세요"는 서술이고, 서술은 강제가 아닙니다. 한 번 기록된 원장 행은
--  **누구도**(배치 포함) 고칠 수 없습니다. 정정은 반대 부호의 `reversal` 행을 덧붙여서만
--  합니다 — 그래야 "무슨 일이 있었는지"가 지워지지 않습니다.
--
--  delete 는 트리거 대신 **권한을 주지 않는 것**으로 막습니다(§9). BEFORE DELETE 트리거를
--  걸면 계정 탈퇴 시의 on delete cascade 까지 함께 막혀 개인정보 정리 경로가 끊깁니다.
-- -----------------------------------------------------------------------------
create or replace function public.duel_cash_ledger_append_only()
returns trigger
language plpgsql
as $$
begin
    raise exception
        'duel_cash_ledger: 현금 원장은 append-only 입니다. 정정은 반대 부호의 reversal 행을 추가하세요(기존 행 수정 금지)';
end;
$$;

drop trigger if exists duel_cash_ledger_no_update on public.duel_cash_ledger;
create trigger duel_cash_ledger_no_update
    before update on public.duel_cash_ledger
    for each row execute function public.duel_cash_ledger_append_only();

comment on table public.duel_cash_ledger is
    '결투다! 현금 원장(append-only). 잔고 컬럼을 두지 않고 항상 sum(amount) 로 계산합니다. 수정은 트리거가 막고, 정정은 reversal 행 추가로만 합니다.';
comment on column public.duel_cash_ledger.amount is
    '입금은 +, 매수는 −. 이 표에 매도는 없습니다(event_type CHECK 참고).';
comment on column public.duel_cash_ledger.event_date is
    '앱이 넣는 한국시간(KST) 기준 날짜. DB 의 current_date(UTC) 를 쓰지 않는 이유는 sql/scorecard_schema.sql §8 주석과 같습니다. 매월 입금은 10일이 주말·공휴일이어도 그대로 10일자입니다(시장 이벤트가 아니라 현금 이벤트).';


-- =============================================================================
-- 5. duel_daily_snapshots / duel_holding_snapshots — 일별 스냅샷
-- =============================================================================
--  `sql/report_schema.sql` 의 두 표를 그대로 본떴습니다(§0-3-10 — 새 패턴을 발명하지 않기).
--  결정적으로 다른 점은 **현금흐름 컬럼 2개**입니다.
--
--  🔴 cash_flow_amount / cash_flow_kind 가 이 표의 존재 이유입니다.
--     TWR(시간가중수익률)은 `r_t = (V_t − F_t) / V_{t−1} − 1` 로 계산하는데, F_t 를 그날
--     기록해 두지 않으면 **나중에 절대 복원할 수 없습니다** — "이 날 총자산이 늘어난 게
--     수익인지 입금인지"를 판별할 근거가 아무 데도 없기 때문입니다. 컬럼을 나중에 붙이면
--     그 이전 구간의 수익률은 영원히 계산 불가입니다. 그래서 처음부터 넣습니다(2-6).
--
--  🔴 "외부 현금흐름"의 정의를 여기 못 박습니다:
--       **시드 지급과 매월 10일 정기 입금만** 외부 현금흐름입니다.
--       **주식 매수는 현금흐름이 아닙니다** — 계좌 안에서 현금이 주식으로 바뀐 것뿐이라
--       총자산이 변하지 않습니다. 여기를 헷갈리면 수익률이 통째로 틀립니다.
--       상장폐지 상각(3-1)도 현금흐름이 아니라 **그날의 평가손실**입니다 —
--       position_value 에만 반영되면 위 공식이 특수 처리 없이 손실로 잡아냅니다.
--
--  📝 cash_flow_kind 에 'mixed' 를 더했습니다(초안은 'seed'/'monthly_deposit'/null 만).
--     계좌 개설일이 마침 10일이면 같은 날 시드와 정기입금이 함께 들어올 수 있고, 그때
--     초안의 CHECK 로는 **둘 중 하나를 골라 적어야 해서 기록이 사실과 달라집니다**(§0-1).
--     TWR 계산은 금액(cash_flow_amount)만 쓰므로 종류가 하나 늘어도 영향이 없습니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_daily_snapshots (
    id               uuid primary key default gen_random_uuid(),
    account_id       uuid not null references public.duel_accounts (id) on delete cascade,
    snapshot_date    date not null,
    position_value   numeric(20, 6) not null check (position_value >= 0),
    cash_balance     numeric(20, 6) not null,
    total_value      numeric(20, 6) not null,
    total_cost       numeric(20, 6) not null check (total_cost >= 0),
    cash_flow_amount numeric(20, 6) not null default 0 check (cash_flow_amount >= 0),
    cash_flow_kind   text check (
                         cash_flow_kind is null
                         or cash_flow_kind in ('seed', 'monthly_deposit', 'mixed')
                     ),
    priced_count     integer not null check (priced_count >= 0),
    unpriced_count   integer not null check (unpriced_count >= 0),
    price_as_of_kst  text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),

    constraint duel_snapshots_account_date_unique unique (account_id, snapshot_date),

    -- report_schema.sql 이 이미 쓰는 방어("그날 가격을 하나도 모르면 행 자체를 안 만든다")를
    -- 이 모듈의 현실에 맞게 한 칸 엽니다: **보유 종목이 0개이고 현금만 있는 계좌**가
    -- 정상적으로 존재하기 때문입니다(신규 계좌, 예수금을 다 쓰지 않은 계좌).
    constraint duel_snapshots_priced check (priced_count > 0 or position_value = 0),

    -- 총자산은 파생값이 아니라 **두 관측값의 합**이어야 합니다. 따로 계산한 값이 들어오면
    -- 그때부터 화면과 순위표가 서로 다른 숫자를 말하기 시작합니다(report_schema.sql §8 의
    -- "들쑥날쑥 금지"와 같은 발상). numeric 이라 십진수로 정확히 비교됩니다.
    constraint duel_snapshots_total_match check (total_value = position_value + cash_balance),

    -- 금액과 종류는 함께 있거나 함께 없어야 합니다. "입금은 있었는데 무슨 입금인지 모름"
    -- 이나 "종류만 있고 금액이 0" 인 행은 나중에 사람이 해석할 수 없습니다.
    constraint duel_snapshots_cash_flow_match check (
        (cash_flow_amount = 0 and cash_flow_kind is null)
        or (cash_flow_amount > 0 and cash_flow_kind is not null)
    )
);

create index if not exists duel_snapshots_account_date_desc_idx
    on public.duel_daily_snapshots (account_id, snapshot_date desc);
-- 발행 배치(5단계)는 "그날 전체 계좌"를 한 번에 훑습니다(§0-3-2 집합 연산).
create index if not exists duel_snapshots_date_idx
    on public.duel_daily_snapshots (snapshot_date);

drop trigger if exists duel_snapshots_set_updated_at on public.duel_daily_snapshots;
create trigger duel_snapshots_set_updated_at
    before update on public.duel_daily_snapshots
    for each row execute function public.duel_set_updated_at();

comment on table public.duel_daily_snapshots is
    '결투다! 계좌 × 거래일 = 1행 합계 스냅샷. cash_flow_amount 는 TWR 계산의 필수 입력이며 나중에 소급 복원이 불가능해 처음부터 기록합니다. 쓰기는 배치(service_role)만.';
comment on column public.duel_daily_snapshots.cash_flow_amount is
    '그날 발생한 **외부** 현금흐름(시드·매월 10일 정기입금만). 주식 매수는 계좌 안의 자산 형태 변경일 뿐이라 포함하지 않습니다. 상장폐지 상각도 현금흐름이 아니라 평가손실입니다.';
comment on column public.duel_daily_snapshots.cash_flow_kind is
    '''seed'' / ''monthly_deposit'' / ''mixed''(개설일이 10일이라 둘이 겹친 날) / null(외부 유입 없음).';
comment on column public.duel_daily_snapshots.unpriced_count is
    '보유는 하고 있으나 그날 종가를 몰라 평가액에서 빠진 종목 수. 화면에 정직하게 표시합니다(0원으로 치지 않습니다 — §0-1).';


-- 종목별 상세 — `portfolio_holding_snapshots` 와 같은 모양입니다. 순위표에서 "보유종목·
-- 수량·매입금액"을 공개하려면 결국 이 표가 원천이 됩니다(1-5).
create table if not exists public.duel_holding_snapshots (
    id            uuid primary key default gen_random_uuid(),
    account_id    uuid not null references public.duel_accounts (id) on delete cascade,
    ticker        text not null check (length(ticker) between 1 and 20),
    snapshot_date date not null,
    stock_name    text,
    quantity      numeric(20, 6) not null check (quantity >= 0),
    avg_cost      numeric(20, 6) not null check (avg_cost >= 0),
    cost          numeric(20, 6) not null check (cost >= 0),

    -- ⚠️ 그날 종가를 몰랐던 종목은 여기 두 컬럼이 **NULL** 입니다. 0 으로 채우지 않습니다
    --    (0원이라는 거짓말이 되고, 다음 날 가격이 들어오는 순간 "하루 만에 폭등"처럼 보이는
    --     가짜 수익률이 생깁니다 — §0-1). 상장폐지 상각으로 **확인된 0원**과는 다릅니다:
    --    그 경우는 position status='delisted' 와 함께 close_price=0 이 기록됩니다.
    close_price   numeric(20, 6) check (close_price is null or close_price >= 0),
    market_value  numeric(20, 6) check (market_value is null or market_value >= 0),

    status        text not null default 'active' check (status in ('active', 'delisted')),
    priced        boolean not null,
    price_as_of_kst text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),

    constraint duel_holding_snapshots_account_ticker_date_unique
        unique (account_id, ticker, snapshot_date),

    -- "가격 모름"의 표현을 한 가지로 못 박습니다(report_schema.sql §8 과 같은 제약).
    constraint duel_holding_snapshots_priced_match check (
        (priced and close_price is not null and market_value is not null)
        or (not priced and close_price is null and market_value is null)
    )
);

create index if not exists duel_holding_snapshots_account_date_idx
    on public.duel_holding_snapshots (account_id, snapshot_date);

drop trigger if exists duel_holding_snapshots_set_updated_at on public.duel_holding_snapshots;
create trigger duel_holding_snapshots_set_updated_at
    before update on public.duel_holding_snapshots
    for each row execute function public.duel_set_updated_at();

comment on table public.duel_holding_snapshots is
    '결투다! 계좌 × 종목 × 거래일 = 1행 상세 스냅샷. 합계 표(duel_daily_snapshots)는 같은 배치 실행에서 이 행들을 그대로 더해 만듭니다(계산 경로를 둘로 나누지 않기).';
comment on column public.duel_holding_snapshots.priced is
    '그날 이 종목의 종가를 알았는지. false 면 close_price/market_value 가 NULL 이고, 화면은 빈칸이 아니라 ''가격 확인 중''으로 표시합니다(3-2 — 수집 실패를 상장폐지로 자동 판단하지 않기).';


-- =============================================================================
-- 6. duel_nicknames — 무작위 닉네임 (비공개 대응표)
-- =============================================================================
--  · **완전 무작위 생성이며 user_id·이메일·가입시각 등 어떤 값에서도 유도하지 않습니다.**
--    해시도 안 됩니다 — 알고리즘이 알려지면 역조회가 가능해집니다(§0-3-8, §0-3-9).
--    생성은 난수 → unique 충돌 시 재시도입니다.
--  · 한 번 만든 닉네임은 그 계좌에 고정이고 다른 계좌가 물려받지 않습니다(5-5).
--    그래서 update 정책을 주지 않습니다(§9) — 바꿀 수 있으면 "과거 순위표의 그 사람"과
--    "지금의 그 사람"이 다른 문자열이 되어 철회 시 삭제 경로가 어긋납니다.
--  · **이 표는 비공개입니다.** 공개표에는 닉네임 문자열만 실리고 account_id 는 절대
--    실리지 않습니다(§8). 즉 닉네임 ↔ 계좌의 연결고리는 **이 표에만**, 그리고 그 표를 읽는
--    배치(service_role)에만 존재합니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_nicknames (
    account_id uuid primary key references public.duel_accounts (id) on delete cascade,
    nickname   text not null unique check (length(btrim(nickname)) > 0),
    created_at timestamptz not null default now()
);

comment on table public.duel_nicknames is
    '결투다! 계좌별 무작위 닉네임(비공개). user_id·이메일에서 유도하지 않은 순수 난수여야 하며, 해시조차 쓰지 않습니다(역조회 방지 — §0-3-8/§0-3-9). 닉네임 ↔ 계좌 연결고리는 이 표에만 있습니다.';


-- =============================================================================
-- 7. duel_public_consent — 공개 동의 상태 (**하나의 boolean 으로 뭉치지 않습니다**)
-- =============================================================================
--  **왜 boolean 7개인가**: "공개" 토글 하나로 뭉치면 사용자가 **무엇에 동의했는지 시스템이
--  알 수 없게** 되고, 그 상태에서 발행 배치가 필드를 하나 더 실어버리면 그게 곧 §0-3-8
--  사고입니다. 동의는 **항목별로 저장돼야 발행 배치가 항목별로 게이팅**할 수 있습니다.
--
--  ⚠️ consent_real_principal_bracket 은 위 5개와 **절대 같은 묶음이 아닙니다.** 이건 이
--     모듈의 데이터가 아니라 **"내 성적표"의 실제 자산 데이터**(매입원가합계)를 끌어다
--     체급(원금 구간)을 정하는 데 쓰는 동의입니다. 가상 대결 성적은 자랑하고 싶지만 실제
--     자산 규모는 어떤 형태로도 알리고 싶지 않은 사용자가 당연히 존재합니다(5-2-4).
--     이 동의가 없는 사용자의 `holdings` 를 읽는 코드 경로가 **하나라도** 있으면 §0-3-8
--     위반입니다.
--
--  ⚠️ 철회 후에도 `revoked_at` 한 줄은 남깁니다. 3개월 재동의 차단(5-8)을 판정하려면 이
--     시각이 필요합니다. **삭제 대상은 "발행된 공개 기록"이지 "동의 상태 관리 기록"이
--     아닙니다.** 이 구분이 §0-3-8 과 충돌하지 않는 이유이고, 그래서 이 표는 비공개입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_public_consent (
    account_id                     uuid primary key
                                   references public.duel_accounts (id) on delete cascade,

    -- 2갈래 공개 항목별 개별 동의 (5개). UI 는 문장을 하나씩 보여주지만, 5-2-2 확정에 따라
    -- **전부 체크하거나 전부 안 하거나** 둘 중 하나입니다("일부 공개" 조합 없음).
    consent_rank                   boolean not null default false,
    consent_return                 boolean not null default false,
    consent_holdings               boolean not null default false,
    consent_quantity               boolean not null default false,
    consent_buy_amount             boolean not null default false,

    -- 위 5개를 모두 체크한 뒤 밟는 **별도의** 최종 확인. 여기가 true 여야 발행 대상입니다.
    final_confirmed                boolean not null default false,
    final_confirmed_at             timestamptz,

    -- ★ 완전히 독립된 별개 동의: 실제 '내 성적표' 매입총합을 체급(구간) 산정에 사용
    consent_real_principal_bracket boolean not null default false,

    -- 철회 이력 (재동의 3개월 차단 판정용)
    revoked_at                     timestamptz,
    created_at                     timestamptz not null default now(),
    updated_at                     timestamptz not null default now(),

    -- 🔴 5-2-2 "전부 아니면 전무"를 DB 가 강제합니다(초안에서 추가 — 머리말 (e)).
    --    화면에서 최종확인 버튼을 잘못 활성화해도, 5개 중 하나라도 빠진 상태로는 발행
    --    대상이 될 수 없습니다.
    constraint duel_consent_final_requires_all check (
        not final_confirmed
        or (consent_rank and consent_return and consent_holdings
            and consent_quantity and consent_buy_amount)
    ),

    -- "언제 최종확인했는지 모르는 최종확인"을 막습니다. 3개월 차단·감사 추적에 필요합니다.
    constraint duel_consent_final_time check (
        (final_confirmed and final_confirmed_at is not null)
        or (not final_confirmed and final_confirmed_at is null)
    ),

    -- 철회한 상태에서 final_confirmed 가 true 로 남아 있으면 배치가 다시 발행해 버립니다.
    -- 철회는 곧 "발행 대상에서 빠진다"이므로 두 값이 동시에 설 수 없게 못 박습니다(5-8).
    constraint duel_consent_revoked_not_confirmed check (
        revoked_at is null or not final_confirmed
    )
);

drop trigger if exists duel_consent_set_updated_at on public.duel_public_consent;
create trigger duel_consent_set_updated_at
    before update on public.duel_public_consent
    for each row execute function public.duel_set_updated_at();

-- -----------------------------------------------------------------------------
-- 7-1. 🔐 철회 이력 되돌리기 금지 (초안에서 추가 — 머리말 (e))
-- -----------------------------------------------------------------------------
--  이 표는 **사용자 본인이 직접 쓰는** 두 표 중 하나입니다(다른 하나는 duel_orders).
--  그런데 아래 RLS 가 update 를 허용하는 이상, 사용자는 anon key 로 화면을 거치지 않고
--  자기 행의 `revoked_at` 을 null 로 되돌려 **3개월 재동의 차단을 그냥 풀 수 있습니다.**
--  `ocr_usage_daily_guard()`(sql/scorecard_schema.sql §8-1)와 정확히 같은 상황이고, 같은
--  방식으로 막습니다 — 카운터를 되돌리지 못하게 한 그 트리거의 형제입니다.
--
--  ⚠️ 3개월이 지난 뒤의 재동의는 **배치/관리 경로(service_role)가** revoked_at 을 지우고
--     다시 열어 줍니다. 앱과 배치 양쪽에서 확인해야 한다는 5-8-2 요구를 이 트리거가
--     "앱 쪽 한 겹"으로 구현한 것입니다.
-- -----------------------------------------------------------------------------
create or replace function public.duel_consent_guard()
returns trigger
language plpgsql
as $$
declare
    is_batch boolean := current_user in ('service_role', 'postgres', 'supabase_admin');
begin
    if new.account_id <> old.account_id then
        raise exception 'duel_public_consent: 계좌는 수정할 수 없습니다';
    end if;

    if not is_batch then
        if old.revoked_at is not null and new.revoked_at is null then
            raise exception
                'duel_public_consent: 철회 기록은 지울 수 없습니다(철회 후 3개월 재동의 차단 판정에 필요 — 5-8)';
        end if;
        if old.revoked_at is not null and new.revoked_at < old.revoked_at then
            raise exception 'duel_public_consent: 철회 시각을 과거로 되돌릴 수 없습니다';
        end if;
    end if;

    return new;
end;
$$;

drop trigger if exists duel_consent_no_revoke_reset on public.duel_public_consent;
create trigger duel_consent_no_revoke_reset
    before update on public.duel_public_consent
    for each row execute function public.duel_consent_guard();

comment on table public.duel_public_consent is
    '결투다! 공개 동의 상태. 항목별 boolean 5개 + 최종확인 + 실제 매입총합 사용 동의(완전 별개). 발행 배치는 이 값들로 항목별 게이팅을 합니다. 비공개 표입니다.';
comment on column public.duel_public_consent.consent_holdings is
    '문구는 "보유종목을 공개합니다"가 아니라 "내 보유종목이 순위표에서 다른 사람에게 **개별 열람 가능하게** 공개됩니다" 여야 합니다(오너 지시 — 개별 열람은 공개의 함축이 아니라 따로 명시해야 하는 사실입니다).';
comment on column public.duel_public_consent.consent_real_principal_bracket is
    '위 5개와 절대 묶지 않는 독립 동의. "내 성적표"의 실제 매입원가합계를 체급(구간) 산정에만 사용합니다. 이 값이 false 인 사용자의 holdings 를 읽는 코드 경로가 하나라도 있으면 §0-3-8 위반입니다.';
comment on column public.duel_public_consent.revoked_at is
    '철회 시각. 발행된 공개 기록은 즉시 영구 삭제하지만 이 한 줄은 남깁니다 — 3개월 재동의 차단 판정에 필요한 비공개 관리 기록이고, 삭제 대상인 "발행된 공개 데이터"와는 다릅니다(5-8-3).';


-- =============================================================================
-- 8. 발행 전용 공개표 — duel_public_leaderboard / duel_public_holdings
-- =============================================================================
--  🔴 **이 두 표에는 user_id 도 account_id 도 없습니다.** 넣는 순간 "이 표만 읽으면
--     안전하다"는 보장이 사라집니다. 철회 시 삭제는 **비공개 duel_nicknames 에서 닉네임을
--     찾아 그 닉네임의 공개 행을 지우는** 방식으로 합니다 — 즉 연결고리는 배치(service_role)
--     쪽에만 존재합니다. 순위표 화면 코드는 duel_positions·holdings·profiles·
--     duel_cash_ledger 를 **import 조차 하지 않아야** 합니다(5-4-5).
--
--  🔴 RLS: 이 두 표만 **로그인 사용자 전체에게 select 허용**. insert/update/delete 정책은
--     **아무에게도 주지 않습니다** — RLS 가 켜진 표에서 정책 없는 동작은 전부 거부되므로,
--     쓰기는 RLS 를 우회하는 service_role(야간 발행 배치)만 할 수 있습니다.
--
--  · 순위는 배치가 `rank() over (partition by window_type, bracket_key order by twr_pct desc)`
--    로 **미리 계산해 저장**합니다. 화면 로드 시 순위를 계산하는 코드는 만들지 마세요 —
--    방문자 수만큼 전체 스캔이 돕니다(§0-3-2, 2-7).
--  · 최소 인원(500명) 미달 구간은 아예 발행하지 않고, 이미 발행돼 있던 행도 제거합니다(5-6).
--    그래서 이 표들에는 service_role 에 **delete 권한을 줍니다**(§9) — 다른 표들과 다른
--    유일한 지점이고, 5-4-4 의 "그날 발행분 전량 재작성"과 5-8-1 의 "철회 시 영구 삭제"가
--    둘 다 삭제를 필요로 하기 때문입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_public_leaderboard (
    id             bigserial primary key,
    published_date date not null,
    window_type    text not null check (window_type in ('M1', 'M3', 'M6')),

    -- 원금 구간(체급) 식별자. consent_real_principal_bracket 이 없는 참가자는 구간 산정에서
    -- 제외되지만 순위표 참여 자체는 가능하므로, 그 그룹을 가리키는 값도 여기 들어옵니다
    -- (5-2-4). 경계값 8구간은 앱 상수가 단일 출처이고 DB 에 숫자를 박지 않습니다(§0-3-10 —
    -- 두 곳에 적으면 둘 중 하나만 바뀌는 날 조용히 어긋납니다).
    bracket_key    text not null check (length(btrim(bracket_key)) > 0),

    rank           integer not null check (rank > 0),
    nickname       text not null check (length(btrim(nickname)) > 0),

    -- consent_return 이 false 면 null. **0 이나 빈 문자열로 채우지 마세요** —
    -- "수익률 0%"와 "수익률 비공개"는 다른 말입니다(§0-1). 화면은 null 을 "비공개"로 렌더링합니다.
    twr_pct        numeric(20, 6),

    created_at     timestamptz not null default now(),
    constraint duel_public_rank_unique
        unique (published_date, window_type, bracket_key, rank)
);

-- 철회(5-8)·최소인원 미달(5-6) 시 "이 닉네임의 발행 행을 전부 삭제"가 실제 질의입니다.
-- 초안에는 인덱스가 없었는데, 이 경로는 사용자 대기 시간에 직접 걸리는 삭제라 필요합니다.
create index if not exists duel_public_leaderboard_nickname_idx
    on public.duel_public_leaderboard (nickname);

comment on table public.duel_public_leaderboard is
    '결투다! 발행 전용 공개 순위표. user_id/account_id 를 절대 담지 않습니다. 배치(service_role)만 쓰고, 로그인 사용자 전체가 읽습니다. 순위는 배치가 window 함수로 미리 계산해 저장한 값입니다.';
comment on column public.duel_public_leaderboard.twr_pct is
    'consent_return 이 false 면 NULL. 0 이나 빈 문자열로 채우지 않습니다 — "0%"와 "비공개"는 다른 말입니다(§0-1).';


-- 보유종목·수량·매입금액 상세. 순위표 행(같은 published_date + nickname)에 딸린 표입니다.
--  📝 초안은 컬럼을 (published_date, nickname, ticker, stock_name, quantity, buy_amount) 로만
--     적어 뒀는데, window_type 을 더했습니다(머리말 (i)). 순위표가 창유형별 탭으로 나뉘므로
--     상세도 같은 축으로 걸러야 하고, 없으면 화면이 duel_public_leaderboard 와 조인해서
--     창유형을 알아내야 합니다 — 발행표는 **조인 없이 자기완결적으로 읽히는 편**이
--     안전합니다(report_schema.sql §8 이 price_as_of_kst 를 종목마다 반복해 넣은 것과 같은 판단).
--     bracket_key 는 넣지 않았습니다 — 체급은 순위표의 축이지 보유종목의 속성이 아니고,
--     중복 저장하면 두 표가 어긋날 여지만 생깁니다.
create table if not exists public.duel_public_holdings (
    id             bigserial primary key,
    published_date date not null,
    window_type    text not null check (window_type in ('M1', 'M3', 'M6')),
    nickname       text not null check (length(btrim(nickname)) > 0),
    ticker         text not null check (length(ticker) between 1 and 20),
    stock_name     text,

    -- 🔴 동의하지 않은 항목은 **null** 입니다. 0 이나 빈 문자열로 채우지 마세요 —
    --    "0주 보유"와 "수량 비공개"는 다른 말입니다(§0-1, 1-8). 화면은 null 을 "비공개"로
    --    렌더링합니다.
    quantity       numeric(20, 6) check (quantity is null or quantity >= 0),
    buy_amount     numeric(20, 6) check (buy_amount is null or buy_amount >= 0),

    created_at     timestamptz not null default now(),
    constraint duel_public_holdings_unique
        unique (published_date, nickname, ticker)
);

create index if not exists duel_public_holdings_nickname_idx
    on public.duel_public_holdings (nickname);

comment on table public.duel_public_holdings is
    '결투다! 발행 전용 공개 보유종목 상세. user_id/account_id 를 담지 않습니다. 동의하지 않은 항목(quantity/buy_amount)은 NULL 이며 화면은 "비공개"로 표시합니다.';


-- =============================================================================
-- 9. 🔐 Row Level Security + 권한 — 이 블록이 이 파일의 핵심입니다
-- =============================================================================
--  auth.uid() = 지금 요청에 실려온 JWT 의 사용자 UUID. 로그인하지 않은 요청(anon key만
--  들고 온 요청)에서는 NULL 이라 어떤 행도 매칭되지 않습니다.
--
--  표마다 정책 개수가 다릅니다. **의도된 차이**이며 이유는 각 블록 위 주석에 적었습니다.
--  요약하면:
--    · 사용자가 직접 쓰는 표는 duel_orders(주문 저장·수정·취소)와 duel_public_consent
--      (동의 저장) **둘뿐**입니다.
--    · duel_accounts / duel_nicknames 는 옵트인 시점에 앱이 만들어야 하므로 insert 까지,
--      그 뒤의 변경은 배치·관리 경로만.
--    · 나머지(포지션·원장·스냅샷)는 **select 하나뿐**입니다. 사용자가 자기 가상 현금과
--      보유 주식을 스스로 써넣을 수 있으면 대결 자체가 성립하지 않습니다.
--    · 발행표 2개는 로그인 사용자 전체에게 select 만. 쓰기 정책은 아무에게도 없습니다.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 9-0. 소유자 판정 함수 — 자식 표 정책 전부가 이 한 줄을 씁니다
-- -----------------------------------------------------------------------------
--  자식 표(포지션·주문·원장·스냅샷·닉네임·동의)의 RLS 정책은 전부 "이 account_id 가 내
--  계좌인가"를 묻습니다. 그 질문을 **한 곳에만** 적어두려고 함수로 뺐습니다(§0-3-10 —
--  나중에 바꿀 곳이 한 군데이게). 정책마다 서브쿼리를 복사해 두면 같은 조건이 열 군데 넘게
--  흩어지고, 그중 하나만 잘못 써도 §0-3-8 사고입니다.
--
--  security definer 인 이유: 이 함수 안의 duel_accounts 조회가 다시 그 표의 RLS 를 타면
--  정책 평가가 중첩됩니다. 소유자 권한으로 한 번에 판정하고 **boolean 하나만** 돌려주므로
--  새어나가는 정보가 없습니다(자기 uid 가 그 계좌 주인인지 여부뿐). `search_path` 를 고정해
--  함수 하이재킹을 막는 것은 `scorecard_schema.sql` §4 와 같은 관례입니다.
-- -----------------------------------------------------------------------------
create or replace function public.duel_account_is_mine(target_account_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
          from public.duel_accounts a
         where a.id = target_account_id
           and a.user_id = auth.uid()
    );
$$;

revoke all on function public.duel_account_is_mine(uuid) from public;
grant execute on function public.duel_account_is_mine(uuid) to authenticated, service_role;


alter table public.duel_accounts           enable row level security;
alter table public.duel_positions          enable row level security;
alter table public.duel_orders             enable row level security;
alter table public.duel_cash_ledger        enable row level security;
alter table public.duel_daily_snapshots    enable row level security;
alter table public.duel_holding_snapshots  enable row level security;
alter table public.duel_nicknames          enable row level security;
alter table public.duel_public_consent     enable row level security;
alter table public.duel_public_leaderboard enable row level security;
alter table public.duel_public_holdings    enable row level security;


-- 9-1. duel_accounts — 본인 계좌 조회 + 옵트인 시 개설 -------------------------
--  update/delete 정책은 일부러 없습니다. 계좌 종료(status='closed')는 규칙에 따른 상태
--  변경이라 배치·관리 경로의 일이고, 삭제는 회원 탈퇴 시 auth.users 의 on delete cascade
--  가 처리합니다(별도 정리 배치 불필요).
drop policy if exists duel_accounts_select_own on public.duel_accounts;
create policy duel_accounts_select_own on public.duel_accounts
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists duel_accounts_insert_own on public.duel_accounts;
create policy duel_accounts_insert_own on public.duel_accounts
    for insert to authenticated
    with check (auth.uid() = user_id);


-- 9-2. duel_positions — 읽기 전용 ---------------------------------------------
drop policy if exists duel_positions_select_own on public.duel_positions;
create policy duel_positions_select_own on public.duel_positions
    for select to authenticated
    using (public.duel_account_is_mine(account_id));


-- 9-3. duel_orders — 사용자가 실제로 쓰는 표 ----------------------------------
--  insert/update 는 허용하되, 무엇을 어떻게 바꿀 수 있는지는 위 §3-1 트리거가 좁힙니다.
--  ⚠️ delete 정책은 **주지 않습니다.** 취소는 status='cancelled' + fail_reason 으로 남겨야
--     하고(§0-1 — 주문이 조용히 사라지는 경로 금지), 행을 지우면 그 기록이 없어집니다.
drop policy if exists duel_orders_select_own on public.duel_orders;
create policy duel_orders_select_own on public.duel_orders
    for select to authenticated
    using (public.duel_account_is_mine(account_id));

drop policy if exists duel_orders_insert_own on public.duel_orders;
create policy duel_orders_insert_own on public.duel_orders
    for insert to authenticated
    with check (public.duel_account_is_mine(account_id));

drop policy if exists duel_orders_update_own on public.duel_orders;
create policy duel_orders_update_own on public.duel_orders
    for update to authenticated
    using (public.duel_account_is_mine(account_id))
    with check (public.duel_account_is_mine(account_id));


-- 9-4. duel_cash_ledger — 읽기 전용 (append-only 는 §4-2 트리거) ---------------
drop policy if exists duel_cash_ledger_select_own on public.duel_cash_ledger;
create policy duel_cash_ledger_select_own on public.duel_cash_ledger
    for select to authenticated
    using (public.duel_account_is_mine(account_id));


-- 9-5. 스냅샷 2표 — 읽기 전용 (report_schema.sql §3 과 정확히 같은 원칙) ------
drop policy if exists duel_snapshots_select_own on public.duel_daily_snapshots;
create policy duel_snapshots_select_own on public.duel_daily_snapshots
    for select to authenticated
    using (public.duel_account_is_mine(account_id));

drop policy if exists duel_holding_snapshots_select_own on public.duel_holding_snapshots;
create policy duel_holding_snapshots_select_own on public.duel_holding_snapshots
    for select to authenticated
    using (public.duel_account_is_mine(account_id));


-- 9-6. duel_nicknames — 본인 것만 조회 + 옵트인 시 1회 생성 -------------------
--  update/delete 정책 없음: 닉네임은 한 번 만들면 그 계좌에 고정입니다(5-5). 바꿀 수 있으면
--  발행표에 남아 있는 과거 닉네임과 대응이 끊겨 철회 시 삭제가 새어 나갑니다.
drop policy if exists duel_nicknames_select_own on public.duel_nicknames;
create policy duel_nicknames_select_own on public.duel_nicknames
    for select to authenticated
    using (public.duel_account_is_mine(account_id));

drop policy if exists duel_nicknames_insert_own on public.duel_nicknames;
create policy duel_nicknames_insert_own on public.duel_nicknames
    for insert to authenticated
    with check (public.duel_account_is_mine(account_id));


-- 9-7. duel_public_consent — 사용자가 실제로 쓰는 두 번째 표 ------------------
--  delete 정책 없음: 철회는 행 삭제가 아니라 revoked_at 기록입니다(5-8-3).
drop policy if exists duel_consent_select_own on public.duel_public_consent;
create policy duel_consent_select_own on public.duel_public_consent
    for select to authenticated
    using (public.duel_account_is_mine(account_id));

drop policy if exists duel_consent_insert_own on public.duel_public_consent;
create policy duel_consent_insert_own on public.duel_public_consent
    for insert to authenticated
    with check (public.duel_account_is_mine(account_id));

drop policy if exists duel_consent_update_own on public.duel_public_consent;
create policy duel_consent_update_own on public.duel_public_consent
    for update to authenticated
    using (public.duel_account_is_mine(account_id))
    with check (public.duel_account_is_mine(account_id));


-- 9-8. 발행표 2개 — 로그인 사용자 전체에게 select 만 -------------------------
--  ⚠️ insert/update/delete 정책을 **아무에게도** 만들지 않았습니다. 발행표에 쓰는 주체는
--     야간 배치(service_role)뿐이고, 그 키는 RLS 자체를 우회합니다. 정책을 하나라도 열면
--     "누가 순위표를 직접 조작할 수 있는가"라는 질문이 생기고, 그 순간 이 구조의 의미가
--     사라집니다.
drop policy if exists duel_public_leaderboard_select_all on public.duel_public_leaderboard;
create policy duel_public_leaderboard_select_all on public.duel_public_leaderboard
    for select to authenticated
    using (true);

drop policy if exists duel_public_holdings_select_all on public.duel_public_holdings;
create policy duel_public_holdings_select_all on public.duel_public_holdings
    for select to authenticated
    using (true);


-- -----------------------------------------------------------------------------
-- 9-9. 권한(GRANT) 정리 — 방어 심화
-- -----------------------------------------------------------------------------
--  RLS 만으로도 비로그인(anon) 요청은 막히지만, anon 롤의 테이블 권한 자체를 거둬서 한 겹 더
--  막습니다(정책을 실수로 지웠을 때의 최악 상황 대비). 그리고 **정책이 있어도 권한이 없으면
--  못 합니다** — 두 겹이 같은 방향을 가리키게 맞춰 둡니다.
-- -----------------------------------------------------------------------------
revoke all on public.duel_accounts           from anon;
revoke all on public.duel_positions          from anon;
revoke all on public.duel_orders             from anon;
revoke all on public.duel_cash_ledger        from anon;
revoke all on public.duel_daily_snapshots    from anon;
revoke all on public.duel_holding_snapshots  from anon;
revoke all on public.duel_nicknames          from anon;
revoke all on public.duel_public_consent     from anon;
revoke all on public.duel_public_leaderboard from anon;
revoke all on public.duel_public_holdings    from anon;

grant select, insert         on public.duel_accounts           to authenticated;
grant select                 on public.duel_positions          to authenticated;
grant select, insert, update on public.duel_orders             to authenticated;
grant select                 on public.duel_cash_ledger        to authenticated;
grant select                 on public.duel_daily_snapshots    to authenticated;
grant select                 on public.duel_holding_snapshots  to authenticated;
grant select, insert         on public.duel_nicknames          to authenticated;
grant select, insert, update on public.duel_public_consent     to authenticated;
grant select                 on public.duel_public_leaderboard to authenticated;
grant select                 on public.duel_public_holdings    to authenticated;

-- 🔧 bigserial 표(duel_cash_ledger · 발행표 2개)의 **시퀀스 권한**을 잊지 마세요.
--    테이블에 insert 권한이 있어도 시퀀스에 usage 가 없으면
--    `permission denied for sequence ...` 로 insert 가 통째로 실패합니다.
--    (이 파일을 실제 Postgres 16 에 실행해 보고 잡은 문제입니다 — 배치가 원장 한 줄도 못
--     쓰는 상태로 배포될 뻔했습니다. Supabase 의 기본 grant 에 기대지 않고 명시합니다.)
--    사용자(authenticated)에게는 **주지 않습니다** — 이 세 표에 사용자가 insert 할 일이
--    없기 때문입니다(원장·발행표는 전부 배치가 씁니다).
revoke all on sequence public.duel_cash_ledger_id_seq        from anon, authenticated;
revoke all on sequence public.duel_public_leaderboard_id_seq from anon, authenticated;
revoke all on sequence public.duel_public_holdings_id_seq    from anon, authenticated;

grant usage, select on sequence public.duel_cash_ledger_id_seq        to service_role;
grant usage, select on sequence public.duel_public_leaderboard_id_seq to service_role;
grant usage, select on sequence public.duel_public_holdings_id_seq    to service_role;

-- 배치(service_role)는 Supabase 기본 설정으로도 권한이 있지만, **무엇을 못 하는지**를
-- 명시적으로 남기는 편이 리뷰에 도움이 됩니다.
grant select, insert, update on public.duel_accounts          to service_role;
grant select, insert, update on public.duel_positions         to service_role;
grant select, insert, update on public.duel_orders            to service_role;
grant select, insert, update on public.duel_daily_snapshots   to service_role;
grant select, insert, update on public.duel_holding_snapshots to service_role;
grant select, insert, update on public.duel_nicknames         to service_role;
grant select, insert, update on public.duel_public_consent    to service_role;

-- 🔴 현금 원장은 배치에게도 **insert 와 select 만** 줍니다. append-only 는 §4-2 트리거가
--    막지만, 권한까지 함께 거둬야 "실수로 update 문을 짰다"가 배포 전에 잡힙니다.
revoke update, delete on public.duel_cash_ledger from service_role;
grant  select, insert on public.duel_cash_ledger to service_role;

-- 🔴 포지션·주문·스냅샷의 delete 도 거둡니다. 이 모듈에는 "지워서 되돌리는" 경로가 없습니다
--    (취소는 status, 상각은 quantity/평가액, 정정은 reversal 행). 유일한 삭제 경로는 회원
--    탈퇴 시의 on delete cascade 이고, 그건 표 소유자 권한으로 돌아 이 revoke 와 무관합니다.
revoke delete on public.duel_accounts          from service_role;
revoke delete on public.duel_positions         from service_role;
revoke delete on public.duel_orders            from service_role;
revoke delete on public.duel_daily_snapshots   from service_role;
revoke delete on public.duel_holding_snapshots from service_role;
revoke delete on public.duel_nicknames         from service_role;
revoke delete on public.duel_public_consent    from service_role;

-- ⚠️ 발행표 2개만 예외로 **delete 를 줍니다.** 5-4-4(그날 발행분 전량 재작성)와
--    5-8-1(철회 시 과거 공개 기록 영구 삭제)이 둘 다 삭제를 필요로 하기 때문입니다.
--    "숨김이 아니라 삭제"가 오너의 명시적 요구입니다.
grant select, insert, update, delete on public.duel_public_leaderboard to service_role;
grant select, insert, update, delete on public.duel_public_holdings    to service_role;


-- =============================================================================
-- 10. ⚠️ 배치가 절대 하지 말아야 할 것 (코드 리뷰용 메모)
-- =============================================================================
--  · 사용자별 루프 금지(§0-3-2, 2-7). 체결은 `update ... from` 한 방, 포지션은
--    `insert ... on conflict (account_id, ticker) do update`, 원장은 `insert ... select`,
--    스냅샷은 `insert ... select ... group by account_id`, 순위는 `rank() over (...)`.
--    사용자가 10명일 때는 루프도 돌아갑니다 — 그래서 위험합니다.
--  · 그날 확정 종가를 확보하지 못했으면 **체결 단계 전체를 건너뜁니다**(부분 체결 금지).
--    판정은 `utils/duel_rules.check_crawl_freshness()`(2-9)가 합니다.
--  · 종가를 모르는 종목을 0원으로 치지 않습니다. 스냅샷은 priced=false 로 남깁니다.
--  · consent_real_principal_bracket 이 false 인 계좌의 `holdings` 를 읽지 않습니다(§0-3-8).
--  · 발행표에 account_id/user_id 를 넣지 않습니다.


-- =============================================================================
-- 11. 설치 후 자가 점검 — 아래 쿼리를 실행해 결과를 눈으로 확인하세요
-- =============================================================================
--  ① 표 10개와 RLS 가 전부 켜져 있는지 (rls_enabled 가 전부 true 여야 정상)
--      select relname, relrowsecurity as rls_enabled
--        from pg_class
--       where relname like 'duel\_%' and relkind = 'r'
--       order by relname;
--
--  ② 정책이 표별로 의도한 개수·종류인지 (아래 표와 대조하세요)
--        duel_accounts            select, insert
--        duel_positions           select
--        duel_orders              select, insert, update
--        duel_cash_ledger         select
--        duel_daily_snapshots     select
--        duel_holding_snapshots   select
--        duel_nicknames           select, insert
--        duel_public_consent      select, insert, update
--        duel_public_leaderboard  select   ← 조건이 true (로그인 사용자 전체)
--        duel_public_holdings     select   ← 조건이 true (로그인 사용자 전체)
--      select tablename, policyname, cmd, qual
--        from pg_policies
--       where schemaname = 'public' and tablename like 'duel\_%'
--       order by tablename, cmd;
--     🔴 어느 표든 delete 정책이 하나라도 나오면 잘못 실행된 것입니다.
--
--  ③ 발행표에 식별자가 새어 들어가지 않았는지 — **항상 0행**이어야 정상입니다.
--      select table_name, column_name
--        from information_schema.columns
--       where table_schema = 'public'
--         and table_name in ('duel_public_leaderboard', 'duel_public_holdings')
--         and column_name in ('user_id', 'account_id', 'email');
--
--  ④ 매도 금지 트리거가 실제로 막는지 (개발용 계좌에서만 시도하세요)
--      -- 아래 update 는 반드시 예외로 실패해야 정상입니다.
--      update public.duel_positions set quantity = quantity - 1 where id = '<개발용 포지션>';
--      -- 관리 경로는 통과해야 정상입니다.
--      begin;
--        set local duel.allow_quantity_decrease = 'on';
--        update public.duel_positions set quantity = 0, status = 'delisted',
--               delisted_date = current_date where id = '<개발용 포지션>';
--      rollback;
--
--  ⑤ 현금 원장이 정말 append-only 인지 (아래 update 는 반드시 실패해야 정상)
--      update public.duel_cash_ledger set amount = amount + 1 where id = <개발용 행>;
--
--  ⑥ 멱등성 인덱스가 실제로 두 번째 입금을 막는지 (두 번째 insert 가 실패해야 정상)
--      insert into public.duel_cash_ledger (account_id, event_type, amount, event_date)
--      values ('<개발용 계좌>', 'monthly_deposit', 800000, date '2026-09-10');
--      -- 같은 문장을 한 번 더 → duel_cash_ledger_monthly_deposit_unique 위반이어야 합니다.
--
--  ⑦ 잔고와 스냅샷이 어긋나지 않는지 (원장 합계 vs 그날 저장된 현금). 스냅샷을 쌓기 시작한
--     뒤에 돌려 보세요 — **항상 0행**이어야 정상입니다.
--      select s.account_id, s.snapshot_date, s.cash_balance, l.ledger_balance
--        from public.duel_daily_snapshots s
--        join lateral (
--              select coalesce(sum(amount), 0) as ledger_balance
--                from public.duel_cash_ledger c
--               where c.account_id = s.account_id
--                 and c.event_date <= s.snapshot_date
--             ) l on true
--       where abs(s.cash_balance - l.ledger_balance) > 0.000001;
--
--  ⑧ 로그인 상태의 **앱에서** 다른 사람의 계좌·주문·현금이 안 보이는지. 대시보드 SQL Editor
--     는 postgres 권한이라 RLS 를 우회하므로, 이 확인만은 반드시 앱에서 해야 합니다
--     (그리고 서로 다른 브라우저 세션 두 개로 — §0-3-8 필수 절차).
-- =============================================================================
