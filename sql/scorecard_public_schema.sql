-- =============================================================================
-- 성적표 공개 순위표("내 밑으로 눈 깔어") — 결투 가상계좌 공개 계층을 대체
-- =============================================================================
--  ✅ 오너 확정 (2026-08-23) — 순위표 최상단 고정 문구("실제로 공개되어있는 '내 성적표'의
--     데이터는...")가 처음부터 실제로 하려던 말이었다는 것이 확인됐습니다. 그동안 구현돼
--     있던 "결투 가상계좌 성적 공개"는 오너의 원래 의도와 달랐던 것으로 드러나, 공개 대상을
--     "내 성적표"(실제 보유 자산)로 전환합니다. 결투 가상계좌 기능(주문·매수·리밸런싱 매도,
--     `/duel` 화면) 자체는 "나와의 결투"라는 개인 연습 목적 그대로 남아 있고, 이 파일이
--     건드리는 것은 **오직 "공개 동의 + 공개 순위표" 계층**입니다.
--
--  이 파일은 두 부분으로 구성됩니다.
--    §1. 결투의 옛 공개 계층 5+3 개 테이블(KRW+USD)과 그 전용 함수·트리거를 DROP 합니다.
--        (`duel_accounts`/`duel_orders`/`duel_positions`/`duel_cash_ledger` 등 가상계좌
--        원본 테이블과 그 KRW/USD 짝, 스냅샷 표는 **하나도 건드리지 않습니다**.)
--    §2. "내 성적표" 기반 새 공개 계층 5개 테이블을 CREATE 합니다. 계좌 개념이 없으므로
--        전부 `user_id` 단위이고(결투의 `account_id` 단위보다 단순), 창유형(M1/M3/M6) 축도
--        없습니다 — 대신 원화/달러 성적표가 완전히 별개이므로 `currency` 축을 둡니다
--        (§0-1/§5-11-2 원칙과 동일하게, 두 통화는 어디서도 합산하지 않습니다 — 앱 코드가
--        지킵니다. 이 표들 자체는 "내 성적표"의 `holdings` 표가 이미 그러듯 한 표 안에서
--        currency 컬럼으로 나눕니다).
--
--  🔴 실행 순서: §1 을 먼저, §2 를 그다음 실행하세요(파일 순서 그대로 위에서 아래로 실행하면
--     됩니다). 이미 실행한 프로젝트에서 다시 돌려도 안전하도록 전부 `if exists`/
--     `if not exists`를 씁니다.
-- =============================================================================


-- #############################################################################
-- § 1. 결투 "공개 동의 + 공개 순위표" 계층 DROP (가상계좌 원본 테이블은 그대로 둠)
-- #############################################################################

-- 1-1. 원화 트랙
drop table if exists public.duel_public_consent cascade;
drop table if exists public.duel_public_leaderboard cascade;
drop table if exists public.duel_public_holdings cascade;
drop table if exists public.duel_bracket_assignments cascade;
drop table if exists public.duel_nicknames cascade;

-- 1-2. 달러 트랙
drop table if exists public.duel_public_consent_usd cascade;
drop table if exists public.duel_public_leaderboard_usd cascade;
drop table if exists public.duel_public_holdings_usd cascade;
drop table if exists public.duel_bracket_assignments_usd cascade;

-- 1-3. 이 5+3개 표에서만 쓰이던 전용 함수 정리.
--      ⚠️ `duel_set_updated_at()` 과 `duel_account_is_mine()`/`duel_account_is_mine_usd()` 는
--      `duel_accounts`/`duel_positions`/`duel_orders`/`duel_cash_ledger`/스냅샷 표(계속 남는
--      가상계좌 원본 테이블들)가 여전히 쓰고 있으므로 **여기서 지우지 않습니다.**
--      `duel_consent_guard()` 는 원화·달러 공개 동의 표 둘 다에서만 쓰였고 그 표를 방금
--      지웠으므로 이제 완전히 고아 함수입니다 — 지웁니다.
drop function if exists public.duel_consent_guard() cascade;

-- 1-4. 결투 공개 발행 배치용 GitHub Actions 워크플로(`.github/workflows/duel_publish_daily.yml`)와
--      그 실행 스크립트(`run_duel_publish_batch.py`)는 이 SQL과 별개로 코드 저장소에서 제거됩니다
--      (이번 배포에 포함) — 여기서 할 일은 없습니다. 참고용 메모입니다.


-- #############################################################################
-- § 2. "내 성적표" 공개 순위표 — 신규 테이블
-- #############################################################################

-- -----------------------------------------------------------------------------
-- 2-1. scorecard_nicknames — 공개 순위표용 무작위 닉네임(비공개 표)
-- -----------------------------------------------------------------------------
--  결투의 duel_nicknames(user_id, window_type)와 달리 창유형이 없으므로 user_id 하나가
--  기본키입니다 — "내 성적표"는 사용자당 포트폴리오 1개뿐입니다(원화/달러 보유분이 섞여
--  있어도 같은 사용자·같은 닉네임). user_id·이메일에서 유도하지 않은 순수 난수이며 해시조차
--  쓰지 않습니다(역조회 방지 — §0-3-8/§0-3-9, 결투와 동일한 원칙).
-- -----------------------------------------------------------------------------
create table if not exists public.scorecard_nicknames (
    user_id     uuid primary key references auth.users (id) on delete cascade,
    nickname    text not null unique check (length(btrim(nickname)) > 0),
    created_at  timestamptz not null default now()
);

comment on table public.scorecard_nicknames is
    '성적표 공개 순위표용 사용자당 1개 무작위 닉네임(비공개). user_id·이메일에서 유도하지 않은 순수 난수입니다.';


-- -----------------------------------------------------------------------------
-- 2-2. scorecard_public_consent — 공개 동의 상태 (사용자당 1행, 계좌 개념 없음)
-- -----------------------------------------------------------------------------
--  결투와 같은 5개 항목별 boolean + 별도 최종확인 구조를 그대로 씁니다("일부 공개" 조합
--  없음 — 전부 아니면 전무). 결투에 있던 6번째 독립 동의("실제 매입총합을 체급 산정에
--  사용")는 **여기서는 만들지 않습니다** — 그 동의가 분리돼 있던 이유는 "이 모듈이 아닌
--  다른 모듈의 실제 자산 데이터를 끌어다 쓴다"는 것이었는데, 이 표에서는 공개되는 데이터
--  자체가 이미 "내 성적표"이므로 매입금액(consent_buy_amount)에 동의하는 순간 매입원가
--  합계는 이미 공개된 값들의 단순 합으로 누구나 재구성 가능합니다 — 분리할 이유가 사라졌
--  습니다.
-- -----------------------------------------------------------------------------
create table if not exists public.scorecard_public_consent (
    user_id             uuid primary key references auth.users (id) on delete cascade,

    consent_rank        boolean not null default false,
    consent_return      boolean not null default false,
    consent_holdings    boolean not null default false,
    consent_quantity    boolean not null default false,
    consent_buy_amount  boolean not null default false,

    final_confirmed     boolean not null default false,
    final_confirmed_at  timestamptz,

    revoked_at          timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint scorecard_consent_final_requires_all check (
        not final_confirmed
        or (consent_rank and consent_return and consent_holdings
            and consent_quantity and consent_buy_amount)
    ),
    constraint scorecard_consent_final_time check (
        (final_confirmed and final_confirmed_at is not null)
        or (not final_confirmed and final_confirmed_at is null)
    ),
    constraint scorecard_consent_revoked_not_confirmed check (
        revoked_at is null or not final_confirmed
    )
);

drop trigger if exists scorecard_consent_set_updated_at on public.scorecard_public_consent;
create trigger scorecard_consent_set_updated_at
    before update on public.scorecard_public_consent
    -- 결투의 duel_accounts 등이 이미 쓰는 범용 트리거 함수를 그대로 재사용합니다
    -- (이름은 duel_ 접두이지만 동작은 "updated_at = now()"뿐인 통화·모듈 무관 함수입니다).
    for each row execute function public.duel_set_updated_at();

-- 2-2-1. 🔐 철회 이력 되돌리기 금지 — duel_consent_guard() 와 정확히 같은 로직, user_id 버전.
create or replace function public.scorecard_consent_guard()
returns trigger
language plpgsql
as $$
declare
    is_batch boolean := current_user in ('service_role', 'postgres', 'supabase_admin');
begin
    if new.user_id <> old.user_id then
        raise exception 'scorecard_public_consent: 사용자는 수정할 수 없습니다';
    end if;

    if not is_batch then
        if old.revoked_at is not null and new.revoked_at is null then
            raise exception
                'scorecard_public_consent: 철회 기록은 지울 수 없습니다(재동의 3개월 차단 판정에 필요)';
        end if;
        if old.revoked_at is not null and new.revoked_at < old.revoked_at then
            raise exception 'scorecard_public_consent: 철회 시각을 과거로 되돌릴 수 없습니다';
        end if;
    end if;

    return new;
end;
$$;

drop trigger if exists scorecard_consent_no_revoke_reset on public.scorecard_public_consent;
create trigger scorecard_consent_no_revoke_reset
    before update on public.scorecard_public_consent
    for each row execute function public.scorecard_consent_guard();

comment on table public.scorecard_public_consent is
    '성적표 공개 동의 상태(사용자당 1행). 항목별 boolean 5개 + 최종확인. 발행 배치는 이 값들로 항목별 게이팅을 합니다. 비공개 표입니다.';
comment on column public.scorecard_public_consent.consent_holdings is
    '문구는 "보유종목을 공개합니다"가 아니라 "내 보유종목이 순위표에서 다른 사람에게 개별 열람 가능하게 공개됩니다" 여야 합니다(결투와 동일한 오너 지시).';
comment on column public.scorecard_public_consent.revoked_at is
    '철회 시각. 발행된 공개 기록은 즉시 영구 삭제하지만 이 한 줄은 남깁니다 — 3개월 재동의 차단 판정에 필요한 비공개 관리 기록입니다.';


-- -----------------------------------------------------------------------------
-- 2-3. scorecard_bracket_assignments — 체급(원금 구간) 배정 기록 (비공개, 시즌 고정)
-- -----------------------------------------------------------------------------
--  결투의 duel_bracket_assignments(account_id, season_key)와 같은 이유로 존재합니다 —
--  "한 번 정해진 체급은 다음 시즌까지 바뀌지 않는다"를 update/delete 권한을 아무에게도
--  주지 않는 방식으로 DB 레벨에서 강제합니다. `currency` 축이 추가된 이유: 원화 성적표와
--  달러 성적표는 매입원가합계 자체가 다른 통화라 체급도 통화별로 따로 매깁니다(원화·달러를
--  어디서도 합산하지 않는다는 원칙과 동일선상).
--  🔴 여기에도 매입원가합계(금액)는 저장하지 않습니다 — 체급 문자열만(§0-3-8).
-- -----------------------------------------------------------------------------
create table if not exists public.scorecard_bracket_assignments (
    user_id     uuid not null references auth.users (id) on delete cascade,
    currency    text not null check (currency in ('KRW', 'USD')),
    season_key  text not null check (length(btrim(season_key)) > 0),
    bracket_key text not null check (length(btrim(bracket_key)) > 0),
    assigned_at timestamptz not null default now(),
    primary key (user_id, currency, season_key)
);

create index if not exists scorecard_bracket_assignments_season_idx
    on public.scorecard_bracket_assignments (currency, season_key, bracket_key);

comment on table public.scorecard_bracket_assignments is
    '성적표 체급(원금 구간) 배정 기록(비공개). 사용자 × 통화 × 시즌 = 1행, 한 번 정해지면 그 시즌 동안 바뀌지 않습니다(update 권한을 아무에게도 주지 않습니다). 매입원가합계 금액 자체는 저장하지 않습니다.';
comment on column public.scorecard_bracket_assignments.season_key is
    '시즌 시작일 문자열(예: 2026-03-01). 값을 만드는 유일한 자리는 utils/duel_rules.py::season_key_for_date() 를 그대로 재사용합니다(§0-3-10).';


-- -----------------------------------------------------------------------------
-- 2-4. scorecard_public_leaderboard / scorecard_public_holdings — 발행 전용 공개표
-- -----------------------------------------------------------------------------
--  결투와 정확히 같은 원칙: user_id 를 담지 않습니다. 순위는 배치가 미리 계산해 저장하고,
--  화면은 이 두 표만 읽습니다("내 성적표"의 원본 holdings 표는 화면 코드가 import 조차 하지
--  않아야 합니다). window_type 축이 없는 대신 currency 축으로 그룹을 나눕니다.
-- -----------------------------------------------------------------------------
create table if not exists public.scorecard_public_leaderboard (
    id             bigserial primary key,
    published_date date not null,
    currency       text not null check (currency in ('KRW', 'USD')),
    bracket_key    text not null check (length(btrim(bracket_key)) > 0),
    rank           integer not null check (rank > 0),
    nickname       text not null check (length(btrim(nickname)) > 0),

    -- consent_return 이 false 면 null(0%와 "비공개"는 다른 말 — §0-1).
    return_pct     numeric(20, 6),

    created_at     timestamptz not null default now(),

    -- 동점(수익률이 완전히 같은 경우)이 실제로 생길 수 있으므로 rank 가 아니라 nickname 을
    -- 유니크 키에 둡니다(결투가 2026-08-20에 겪은 사고와 같은 이유 — §8-1 주석 참고).
    constraint scorecard_public_leaderboard_participant_unique
        unique (published_date, currency, bracket_key, nickname)
);

create index if not exists scorecard_public_leaderboard_group_rank_idx
    on public.scorecard_public_leaderboard (published_date, currency, bracket_key, rank);

create index if not exists scorecard_public_leaderboard_nickname_idx
    on public.scorecard_public_leaderboard (nickname);

comment on table public.scorecard_public_leaderboard is
    '성적표 발행 전용 공개 순위표. user_id 를 절대 담지 않습니다. 배치(service_role)만 쓰고, 로그인 사용자 전체가 읽습니다.';
comment on column public.scorecard_public_leaderboard.return_pct is
    'consent_return 이 false 면 NULL. 0 이나 빈 문자열로 채우지 않습니다(§0-1).';


create table if not exists public.scorecard_public_holdings (
    id             bigserial primary key,
    published_date date not null,
    currency       text not null check (currency in ('KRW', 'USD')),
    nickname       text not null check (length(btrim(nickname)) > 0),
    ticker         text not null check (length(ticker) between 1 and 20),
    stock_name     text,

    -- 동의하지 않은 항목은 null(0 이나 빈 문자열로 채우지 않음 — §0-1).
    quantity       numeric(20, 6) check (quantity is null or quantity >= 0),
    buy_amount     numeric(20, 6) check (buy_amount is null or buy_amount >= 0),

    created_at     timestamptz not null default now(),
    constraint scorecard_public_holdings_unique
        unique (published_date, currency, nickname, ticker)
);

create index if not exists scorecard_public_holdings_nickname_idx
    on public.scorecard_public_holdings (nickname);

comment on table public.scorecard_public_holdings is
    '성적표 발행 전용 공개 보유종목 상세. user_id 를 담지 않습니다. 동의하지 않은 항목(quantity/buy_amount)은 NULL 이며 화면은 "비공개"로 표시합니다.';
comment on column public.scorecard_public_holdings.stock_name is
    '⚠️ 사용자가 자유 입력한 값입니다(holdings.stock_name 을 그대로 옮김) — <img onerror=...> 같은 값이 저장될 수 있습니다(scorecard_page.py 가 이미 §0-3-9 로 문서화한 위험과 동일). 화면은 렌더링하는 모든 자리에서 esc() 를 반드시 적용해야 합니다.';


-- #############################################################################
-- § 3. Row Level Security + 권한
-- #############################################################################

alter table public.scorecard_nicknames            enable row level security;
alter table public.scorecard_public_consent        enable row level security;
alter table public.scorecard_bracket_assignments   enable row level security;
alter table public.scorecard_public_leaderboard    enable row level security;
alter table public.scorecard_public_holdings       enable row level security;

-- 3-1. scorecard_nicknames — 본인 것만 조회 + 최초 1회 생성. update/delete 없음(고정 닉네임).
drop policy if exists scorecard_nicknames_select_own on public.scorecard_nicknames;
create policy scorecard_nicknames_select_own on public.scorecard_nicknames
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists scorecard_nicknames_insert_own on public.scorecard_nicknames;
create policy scorecard_nicknames_insert_own on public.scorecard_nicknames
    for insert to authenticated
    with check (auth.uid() = user_id);

-- 3-2. scorecard_public_consent — 본인 것만 조회/작성/수정. delete 없음(철회는 필드 갱신).
--      계좌 레이어가 없으므로 결투의 duel_account_is_mine() 같은 security-definer 헬퍼 없이
--      바로 auth.uid() = user_id 로 비교합니다.
drop policy if exists scorecard_consent_select_own on public.scorecard_public_consent;
create policy scorecard_consent_select_own on public.scorecard_public_consent
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists scorecard_consent_insert_own on public.scorecard_public_consent;
create policy scorecard_consent_insert_own on public.scorecard_public_consent
    for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists scorecard_consent_update_own on public.scorecard_public_consent;
create policy scorecard_consent_update_own on public.scorecard_public_consent
    for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- 3-3. scorecard_bracket_assignments — 본인 것만 조회만. insert/update/delete 는 아무에게도
--      없음(체급을 정하는 것은 발행 배치의 일 — service_role 이 RLS 를 우회해 씁니다).
drop policy if exists scorecard_bracket_assignments_select_own on public.scorecard_bracket_assignments;
create policy scorecard_bracket_assignments_select_own on public.scorecard_bracket_assignments
    for select to authenticated
    using (auth.uid() = user_id);

-- 3-4. 발행표 2개 — 로그인 사용자 전체에게 select 만. insert/update/delete 정책은 아무에게도
--      없음(쓰기는 RLS 를 우회하는 service_role, 즉 야간 발행 배치만 할 수 있습니다).
drop policy if exists scorecard_public_leaderboard_select_all on public.scorecard_public_leaderboard;
create policy scorecard_public_leaderboard_select_all on public.scorecard_public_leaderboard
    for select to authenticated
    using (true);

drop policy if exists scorecard_public_holdings_select_all on public.scorecard_public_holdings;
create policy scorecard_public_holdings_select_all on public.scorecard_public_holdings
    for select to authenticated
    using (true);

-- 3-5. anon 롤 권한 완전 회수(방어 심화 — 정책을 실수로 지워도 한 겹 더 막힙니다).
revoke all on public.scorecard_nicknames          from anon;
revoke all on public.scorecard_public_consent     from anon;
revoke all on public.scorecard_bracket_assignments from anon;
revoke all on public.scorecard_public_leaderboard from anon;
revoke all on public.scorecard_public_holdings    from anon;

-- 3-6. authenticated 롤 — 화면(사용자 클라이언트)이 실제로 필요한 만큼만.
grant select, insert         on public.scorecard_nicknames          to authenticated;
grant select, insert, update on public.scorecard_public_consent     to authenticated;
grant select                 on public.scorecard_bracket_assignments to authenticated;
grant select                 on public.scorecard_public_leaderboard to authenticated;
grant select                 on public.scorecard_public_holdings    to authenticated;

-- 3-7. bigserial 시퀀스 — anon/authenticated 에게서 회수, service_role 에게만
--      (결투가 이미 겪은 "permission denied for sequence" 사고 재발 방지).
revoke all on sequence public.scorecard_public_leaderboard_id_seq from anon, authenticated;
revoke all on sequence public.scorecard_public_holdings_id_seq    from anon, authenticated;
grant usage, select on sequence public.scorecard_public_leaderboard_id_seq to service_role;
grant usage, select on sequence public.scorecard_public_holdings_id_seq    to service_role;

-- 3-8. service_role(야간 발행 배치) 권한.
grant select, insert, update on public.scorecard_nicknames          to service_role;
grant select, insert, update on public.scorecard_public_consent     to service_role;

-- 체급 배정 표는 update/delete 를 service_role 에게서도 회수합니다("시즌 중 체급 고정"이
-- 앱의 조심성이 아니라 DB 권한으로 강제되도록 — 결투와 동일한 방어).
revoke update, delete on public.scorecard_bracket_assignments from service_role;
grant  select, insert on public.scorecard_bracket_assignments to service_role;

-- 발행표 2개만 service_role 에게 delete 권한도 줍니다(최소인원 미달 그룹 정리, 철회 시 영구
-- 삭제, 그날 발행분 전량 재작성이 전부 삭제를 필요로 하기 때문 — 결투와 동일한 유일한 예외).
grant select, insert, update, delete on public.scorecard_public_leaderboard to service_role;
grant select, insert, update, delete on public.scorecard_public_holdings    to service_role;

-- scorecard_nicknames/scorecard_public_consent 는 행 삭제가 없으므로(닉네임 영구,
-- 동의 철회는 필드 갱신) service_role 에서도 delete 를 명시적으로 회수합니다.
revoke delete on public.scorecard_nicknames      from service_role;
revoke delete on public.scorecard_public_consent from service_role;


-- #############################################################################
-- ============ 2026-08-23 추가: 종목별 상세지표 + 6번째 동의 항목 ============
-- #############################################################################
--
--  🔴 이 절은 **추가분(addendum)입니다.** sql/scorecard_public_schema.sql 의 §1~§3 은 오너가
--     Supabase SQL Editor 에서 이미 실행했고, 그 위에서 실사용 검증(임시 SQL 로 채운 더미
--     참가자 → 순위표 확인 →
--     정리)까지 끝났습니다. 그러므로 그 스크립트를 **다시 만들거나 고치지 않습니다** —
--     아래 ALTER 문만 덧붙여 실행합니다(이미 있는 표를 drop/create 하면 실제 데이터가
--     사라집니다).
--
--  ── 왜 (오너 지시 원문, 2026-08-23) ─────────────────────────────────────────
--  "공개할거면 다 공개를 해야지. 기본적으로 '내 성적표'에 나오는 정보는 다 공개가 되어야
--   하는거 아니야?" · "동의 체크 항목에서 빠져 있는 내용이면 동의 체크 항목에 추가를
--   해야지."
--
--  즉 순위표의 "📄 보유종목 보기" 표가 "내 성적표" 화면의 표와 **같은 열 구성**이 됩니다:
--  기존 종목·수량·매입금액에 더해 **평균매입가 · 현재가 · 평가손익 · 수익률 · 비중**.
--  그 다섯 지표는 기존 5개 동의 문장 어디에도 적혀 있지 않던 값이라, 동의 문장에 없는 것을
--  공개하지 않기 위해(§0-1) **여섯 번째 동의 항목**을 함께 세웁니다.
--
--  ⚠️ 실행 순서를 바꾸지 마세요 — A-2(백필)가 A-3(CHECK 재작성)보다 **반드시 먼저**여야
--     합니다. 순서를 뒤집으면, 이미 final_confirmed=true 인 행이 새 CHECK 를 만족하지
--     못해 `alter table ... add constraint` 자체가 거절됩니다.
--
--  이 절과 **똑같은 내용**이 저장소 루트의 `MIGRATION_2026-08-23_holding_details.sql`
--  에도 있습니다(오너가 SQL Editor 에 붙여넣을 파일). 한쪽만 고치지 마세요.


-- -----------------------------------------------------------------------------
-- A-1. scorecard_public_consent — 여섯 번째 동의 항목
-- -----------------------------------------------------------------------------
--  🔴 이 항목은 결투의 여섯 번째 동의(consent_real_principal_bracket, "실제 매입총합을
--     체급 산정에 사용")와 **성격이 다릅니다.** 그건 따로 켜고 끄는 독립 동의였지만, 이것은
--     앞의 5개와 같은 "전부 아니면 전무" 묶음입니다 — 체크박스만 여섯 개이고, 최종 확인은
--     여섯 개가 전부 켜져야 눌립니다(아래 A-3 의 CHECK 가 그것을 DB 에서 강제합니다).
--  기본값 false = **기본 비공개**(§0-3-8). 새 사용자는 이 항목을 직접 체크해야 합니다.
alter table public.scorecard_public_consent
    add column if not exists consent_holding_details boolean not null default false;

comment on column public.scorecard_public_consent.consent_holding_details is
    '2026-08-23 신설(6번째 항목). 화면 문구: "종목별 상세지표 — 종목별로 평균매입가·현재가·평가손익·수익률·비중까지 함께 공개됩니다." 앞의 5개와 같은 "전부 아니면 전무" 묶음이며(결투의 consent_real_principal_bracket 같은 독립 동의가 아님), scorecard_consent_final_requires_all CHECK 가 최종확인 시 6개 전부를 요구합니다.';


-- -----------------------------------------------------------------------------
-- A-2. 🔴 기존 1행 백필 — **CHECK 를 다시 걸기 전에** 실행되어야 합니다
-- -----------------------------------------------------------------------------
--  이 표에서 final_confirmed = true 인 행은 지금 **오너 본인의 실사용 검증 1건**뿐입니다
--  (500명 문턱을 넘어 실제로 남에게 노출된 적이 없고, 검증에 쓴 임시 참가자는 이미
--   정리됐습니다). 그 한 행에 대해 오너가 이번 세션에서 "공개할거면 다 공개를 해야지"라고
--  **명시적으로** 전체 공개를 확정했으므로, 그 확정을 이 한 줄로 반영합니다.
--
--  ⚠️ 이것은 "동의를 대신 켜 주는" 일반 규칙이 **아닙니다.** 다른 사용자에게는 이런 백필을
--     하지 않습니다 — 동의는 사용자가 화면에서 직접 체크해야 하고(기본값 false), 그것이
--     §0-3-8 의 기본 비공개 원칙입니다. 이 UPDATE 는 "동의 주체 본인이 같은 자리에서 구두로
--     확정한 1행"에 한정된 일회성 반영입니다.
--
--  ⚠️ 이 UPDATE 는 SQL Editor(=postgres/supabase_admin)로 실행되므로
--     scorecard_consent_guard() 트리거의 is_batch 경로를 타 철회 이력 보호에 걸리지
--     않습니다. revoked_at 이 있는 행은 애초에 final_confirmed 가 설 수 없어
--     (scorecard_consent_revoked_not_confirmed CHECK) 이 UPDATE 의 대상이 아닙니다.
update public.scorecard_public_consent
   set consent_holding_details = true
 where final_confirmed = true;


-- -----------------------------------------------------------------------------
-- A-3. "전부 아니면 전무" CHECK 를 6개 기준으로 다시 작성
-- -----------------------------------------------------------------------------
--  기존 5개짜리 제약을 지우고, 컬럼 하나만 더한 **같은 모양**으로 다시 겁니다(이름도 그대로
--  scorecard_consent_final_requires_all — 앱 코드와 문서가 이 이름으로 이 규칙을 가리키고
--  있습니다). add constraint 는 기존 행을 전부 검사하므로, 위 A-2 백필이 빠졌다면 여기서
--  시끄럽게 실패합니다. 그게 맞는 동작입니다(조용히 통과하면 안 되는 자리).
alter table public.scorecard_public_consent
    drop constraint if exists scorecard_consent_final_requires_all;

alter table public.scorecard_public_consent
    add constraint scorecard_consent_final_requires_all check (
        not final_confirmed
        or (consent_rank and consent_return and consent_holdings
            and consent_quantity and consent_buy_amount and consent_holding_details)
    );


-- -----------------------------------------------------------------------------
-- A-4. scorecard_public_holdings — 종목별 상세지표 5개 컬럼
-- -----------------------------------------------------------------------------
--  전부 **nullable** 입니다. null 의 뜻은 두 가지이고 **둘 다 "0" 이 아닙니다**(§0-1):
--    ① 그 참가자가 consent_holding_details 에 동의하지 않음 → 발행 배치가 null 로 넣음.
--    ② 그날 그 종목의 현재가를 구하지 못함 → evaluate_holding() 이 애초에 None 으로 둠
--       (avg_price 는 이 경우에도 값이 있습니다 — 매입가는 시세와 무관하므로).
--  발행표는 ①과 ②를 **구분해 담지 않습니다.** 구분해 담으면 "이 사람은 동의는 했는데 그날
--  가격이 없었다"는 정보가 남에게 드러납니다. 화면은 어느 쪽이든 "비공개"로 그립니다.
--
--  numeric(20, 6) 고정 — holdings.avg_purchase_price / 이 표의 quantity·buy_amount 와 같은
--  정밀도입니다(float 로 두면 표시 단계에서 조용히 값이 틀어집니다).
alter table public.scorecard_public_holdings
    add column if not exists avg_price     numeric(20, 6);
alter table public.scorecard_public_holdings
    add column if not exists current_price numeric(20, 6);
alter table public.scorecard_public_holdings
    add column if not exists profit        numeric(20, 6);
alter table public.scorecard_public_holdings
    add column if not exists profit_pct    numeric(20, 6);
alter table public.scorecard_public_holdings
    add column if not exists weight_pct    numeric(20, 6);

--  값의 범위 — 음수가 될 수 있는 것과 없는 것을 **구분해서** 겁니다.
--    · 가격(avg_price·current_price)은 음수가 될 수 없습니다(scorecard_db 가 이미 양수만
--      받습니다). 여기 음수가 들어오면 데이터 손상이므로 발행을 거절하는 편이 낫습니다.
--    · profit·profit_pct 는 **손실이면 음수가 정상**입니다 — 하한을 걸지 않습니다.
--      (여기에 >= 0 을 걸면 손실 난 사람의 발행이 통째로 거절됩니다.)
--    · weight_pct 는 0 이상. 상한(100)은 **일부러 걸지 않았습니다** — 반올림 끝자리 하나로
--      그날 발행 전체가 거절되는 것보다, 이상값이 화면에 그대로 보이는 편이 낫습니다(§0-1).
alter table public.scorecard_public_holdings
    drop constraint if exists scorecard_public_holdings_prices_not_negative;
alter table public.scorecard_public_holdings
    add constraint scorecard_public_holdings_prices_not_negative check (
        (avg_price     is null or avg_price     >= 0)
        and (current_price is null or current_price >= 0)
        and (weight_pct    is null or weight_pct    >= 0)
    );

comment on column public.scorecard_public_holdings.avg_price is
    '종목별 평균매입가(evaluate_holding().avg_purchase_price 를 그대로 옮긴 값). NULL = consent_holding_details 가 false(=비공개)라는 뜻이며 "0원"이 아닙니다(§0-1). 2026-08-23 신설.';
comment on column public.scorecard_public_holdings.current_price is
    '발행 시점에 조회된 현재가. NULL = consent_holding_details 가 false 이거나 그날 가격을 구하지 못했다는 뜻이며 "0원"이 아닙니다(§0-1). 두 사유를 구분해 담지 않습니다 — 구분하면 "동의는 했는데 가격이 없다"가 드러납니다. 2026-08-23 신설.';
comment on column public.scorecard_public_holdings.profit is
    '종목별 평가손익(평가금액 − 매입원가). 손실이면 음수가 정상입니다. NULL = consent_holding_details 가 false 이거나 가격 미확인이며 "0원"이 아닙니다(§0-1). 2026-08-23 신설.';
comment on column public.scorecard_public_holdings.profit_pct is
    '종목별 수익률(%). 손실이면 음수가 정상입니다. NULL = consent_holding_details 가 false 이거나 가격 미확인이며 "0%"가 아닙니다(§0-1). 2026-08-23 신설.';
comment on column public.scorecard_public_holdings.weight_pct is
    '종목별 비중(%). "내 성적표" 화면과 **같은 정의** — 가격을 확인한 종목들의 평가금액 합을 분모로 씁니다(scorecard_db.build_portfolio()). 두 화면이 같은 이름으로 다른 숫자를 보여주지 않게 하려는 것입니다(§0-1/§0-3-10). NULL = consent_holding_details 가 false 이거나 가격 미확인이며 "0%"가 아닙니다. 2026-08-23 신설.';

comment on table public.scorecard_public_holdings is
    '성적표 발행 전용 공개 보유종목 상세. user_id 를 담지 않습니다. 동의하지 않은 항목(quantity/buy_amount 및 2026-08-23 신설 상세 5종)은 NULL 이며 화면은 "비공개"로 표시합니다.';
comment on table public.scorecard_public_consent is
    '성적표 공개 동의 상태(사용자당 1행). 항목별 boolean 6개(2026-08-23 에 5개 → 6개) + 최종확인. 발행 배치는 이 값들로 항목별 게이팅을 합니다. 비공개 표입니다.';
