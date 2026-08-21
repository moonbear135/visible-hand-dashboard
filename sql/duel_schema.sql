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
--    4. 좌측 메뉴 → Table Editor 에서 아래 **11개 표**와 각각의 "RLS enabled" 표시를 눈으로 확인
--         비공개(계좌 소유자 전용)
--           · public.duel_accounts          (§1)  가상계좌 — 사용자당 M1/M3/M6 정확히 3개
--           · public.duel_positions         (§2)  가상 보유 포지션 (매수 + 창당 1회 리밸런싱 매도)
--           · public.duel_orders            (§3)  예약 주문 (수량 기준, D+1 종가 체결)
--           · public.duel_cash_ledger       (§4)  현금 원장 — **append-only**
--           · public.duel_daily_snapshots   (§5)  계좌 × 거래일 합계 스냅샷 (+ 현금흐름)
--           · public.duel_holding_snapshots (§5)  계좌 × 종목 × 거래일 상세 스냅샷
--           · public.duel_nicknames         (§6)  무작위 닉네임 (비공개 대응표)
--           · public.duel_public_consent    (§7)  공개 동의 상태 (boolean 7개)
--           · public.duel_bracket_assignments (§8-3) 체급(원금 구간) 배정 — 계좌 × 시즌 = 1행
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
--   (k) **2026-08-20 추가(5단계 구현 중 발견)** — `duel_bracket_assignments` 표(§8-3).
--       작업지시서 5-3 은 "한 번 정해진 체급은 시즌(1년) 동안 바뀌지 않는다"를 확정했는데,
--       **그 배정 결과를 적어 둘 자리가 이 스키마 어디에도 없었습니다.** 발행표에서 역으로
--       읽으면 될 것 같지만 안 됩니다 — 발행표의 행은 최소 인원 미달(5-6)이나 철회(5-8)로
--       **지워지는** 행이라, 그걸 기억 장치로 쓰면 지워지는 순간 배치가 체급을 처음부터
--       다시 매깁니다(= 시즌 고정 규칙이 조용히 사라짐). §8-3 참고.
--   (l) **2026-08-20 수정(5단계 구현 중 발견한 진짜 버그)** — `duel_public_leaderboard` 의
--       유니크 제약을 `(published_date, window_type, bracket_key, **rank**)` 에서
--       `(published_date, window_type, bracket_key, **nickname**)` 으로 바꿨습니다.
--       예전 제약은 **동점자 두 명이 같은 순위를 받는 순간 발행 전체를 거절**합니다. 그리고
--       동점은 예외 상황이 아닙니다 — 아무것도 사지 않고 현금만 들고 있는 계좌의 TWR 은
--       정확히 0.000000% 라, 참가자가 500명(5-6 최소 인원)쯤 되면 0% 동점자가 거의 확실히
--       생깁니다. 읽기 성능을 위해 같은 컬럼 조합의 **일반 인덱스**는 그대로 남깁니다. §8-1.
--   (j) **2026-08-20 추가** — 옵트인 RPC `public.duel_opt_in()`(§9-10). 오너가 "참여 즉시
--       시드머니 지급"(작업지시서 미결항목 2번 (B)안)을 확정했는데, 현금 원장은 사용자에게
--       쓰기를 열어 줄 수 없는 표입니다(§4 · §9-4). 그렇다고 사용자 접속 앱 서버에 배치
--       키를 넣으면 이 파일의 RLS 전체가 무력화됩니다(§0-3-8). 그래서 **표 소유자 권한으로
--       도는 좁은 저장 프로시저**를 만들고, 사용자는 자기 로그인 세션으로 그것만 호출합니다.
--       인자가 없고 대상은 `auth.uid()` 뿐이라 남을 대신해 부를 수 없습니다. 자세한 근거는
--       §9-10 주석에 있습니다.
--   (m) **2026-08-20 추가(USD 트랙 §5-11 도입)** — `duel_nicknames`(§6)의 기본키를
--       `account_id`(계좌 단위) → `(user_id, window_type)`(사용자×창유형 단위)로 바꿨습니다.
--       오너가 "같은 사용자면 원화·달러 트랙에서 같은 닉네임을 쓰자"(5-11-10)를 확정했는데,
--       원화 계좌(duel_accounts)와 달러 계좌(duel_accounts_usd, §13)는 물리적으로 다른
--       표의 서로 다른 id 라 계좌 단위 기본키로는 그 공유를 표현할 수 없었습니다. §9-6
--       RLS 정책도 함께 바꿨습니다(auth.uid() = user_id 직접 비교). 예전 버전(계좌 단위)을
--       이미 실행한 프로젝트를 위한 마이그레이션 브리지는 §12 에 있고, 새로 설치하는
--       프로젝트에서는 §6 이 처음부터 새 구조로 만들어 §12 가 아무 일도 하지 않습니다.
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
    -- 2026-08-21 오너 확정(창당 1회 리밸런싱 매도 추가) — 리밸런싱 창(30/90/180일)의
    -- 기준일입니다. anchor_date(계좌 개설일 = 입금 리듬 기준)와 다른 개념이므로 재사용하지
    -- 않습니다. 계좌에 처음으로 보유 종목이 생긴 날(첫 매수 체결일)만 야간 배치가 채우고,
    -- 그 전까지는 NULL — "아직 보유가 없어 리밸런싱 창을 계산할 수 없음"과 "0일차"를
    -- 구분하기 위해 0 이나 오늘 날짜 같은 값으로 채우지 않습니다(§0-1).
    first_holding_date date,
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
-- 2. duel_positions — 가상 보유 포지션 (매수 + 창당 1회 리밸런싱 매도)
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
-- 2-1. 🔐 수량 감소의 DB 레벨 통제 (작업지시서 1-2 마지막 항목 — 2026-08-21 정정)
-- -----------------------------------------------------------------------------
--  ⚠️ 이 절은 원래 "이 모듈에 매도는 영원히 없습니다"라는 절대 규칙으로 쓰여 있었습니다.
--     2026-08-21 오너 확정으로 그 결정 자체가 **이전 라운드의 대화 착오**였음이 드러나
--     정정합니다 — 원래 의도는 M1/M3/M6 계좌가 각각 30/90/180일 주기로 **딱 1회**
--     리밸런싱 매도를 할 수 있어야 한다는 것이었고, 그래야 "내 성적표(실제 계좌)"와
--     비교하는 시스템이 성립합니다(DUEL_MODULE_WORK_ORDER.md 의 정정 섹션 참고). 아래는
--     정정된 설계입니다.
--
--  화면 로직·배치 로직에 실수가 있어도 수량이 **정당한 사유 없이는** 줄어들지 않게 DB 가
--  마지막으로 한 번 더 막습니다(§0-3-9 의 이중 방어). 정당한 사유는 이제 세 가지입니다.
--    · 3-1 상장폐지 상각 (평가액 0 확정) — 관리 경로, `duel.allow_quantity_decrease`
--    · 3-3 유니버스 500위 밖 이탈 종목의 강제 정리 — 관리 경로, 위와 동일 플래그
--    · 3-4 액면병합·감자처럼 주식 수 자체가 줄어드는 기업행위 조정 — 관리 경로, 위와 동일 플래그
--    · **신규** 창당 1회 리밸런싱 매도의 야간 정산 — 배치 경로, `duel.settled_sell`
--  관리 경로와 배치 정산 경로를 **서로 다른 세션 변수**로 나눈 이유: "왜 수량이 줄었는지"가
--  변수 이름만 봐도 구분돼야 나중에 감사(audit)할 수 있습니다. 관리자는 같은 트랜잭션 안에서
--      set local duel.allow_quantity_decrease = 'on';
--  를, 야간 배치는 매도 정산 직전에
--      set local duel.settled_sell = 'on';
--  를 먼저 실행해야 합니다. 역할(role) 검사로 하지 않은 이유: 야간 배치도 service_role 로
--  도는데, **배치의 다른 모든 쓰기(매수 체결 등)는 여전히 수량을 줄일 일이 없어야**
--  하기 때문입니다 — 세션 변수는 "지금 이 한 트랜잭션에서 의도적으로 줄인다"를 명시적으로
--  선언하게 만듭니다.
--
--  🔴 delete 로 우회하는 길은 아래 §9 에서 **권한 자체를 주지 않는 것**으로 막습니다.
--     (여기에 BEFORE DELETE 트리거를 걸면 계정 탈퇴 시의 on delete cascade 까지 막혀서
--      개인정보 정리 경로가 끊깁니다 — cascade 는 표 소유자 권한으로 돌아 RLS·권한을
--      우회하므로, "정책·권한을 안 주는" 방식이 정확히 원하는 결과를 냅니다.)
-- -----------------------------------------------------------------------------
-- 🔴 2026-08-21 오너 확정 — 이름·기본 취지("매수 전용, 수량 감소는 원칙적으로 막는다")는
--    그대로 두되, 이제 수량 감소가 정당한 사유가 **두 가지**가 됐습니다: ① 상장폐지 상각
--    같은 관리 경로(기존 `duel.allow_quantity_decrease`), ② 창당 1회 리밸런싱 매도의
--    정산(신규 `duel.settled_sell`). 두 플래그를 하나로 합치지 않는 이유: "왜 줄었는지"가
--    세션 변수 이름만 봐도 구분돼야 나중에 감사(audit)할 수 있습니다 — 관리자의 예외 처리와
--    배치의 정상 매도 정산은 서로 다른 사건이고, 하나로 합치면 그 구분이 사라집니다.
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

drop trigger if exists duel_positions_no_sell on public.duel_positions;
create trigger duel_positions_no_sell
    before update on public.duel_positions
    for each row execute function public.duel_positions_buy_only();

comment on table public.duel_positions is
    '결투다! 가상 보유 포지션. quantity 감소는 트리거(duel_positions_buy_only)가 원칙적으로 막고, 세션 변수(duel.allow_quantity_decrease=관리 경로, duel.settled_sell=리밸런싱 매도 정산)로만 예외 허용(2026-08-21 오너 확정). 쓰기는 배치(service_role)만, 사용자는 읽기 전용.';
comment on column public.duel_positions.avg_cost is
    '가중평균 매입단가. holdings.avg_purchase_price 와 같은 규칙·같은 타입(numeric(20,6))입니다 — float 로 두면 반복 매수한 계좌의 평단가가 조용히 틀어집니다.';
comment on column public.duel_positions.quantity is
    '0 이어도 행을 지우지 않습니다. 상장폐지 상각·강제정리 이후에도 손실이 손실로 보여야 하기 때문입니다(3-1).';


-- =============================================================================
-- 3. duel_orders — 예약 주문 (수량 기준, D일 접수 → D+1 종가 체결)
-- =============================================================================
--  · **주문은 "얼마어치"가 아니라 "몇 주"입니다**(2026-08-19 오너 확정). 최초 설계안의
--    금액 입력(order_amount_krw)은 폐기됐습니다.
--  · `side` 는 'buy'/'sell' 둘 다 허용합니다(2026-08-21 오너 확정 — 이전엔 check (side =
--    'buy') 로 매도를 물리적으로 막아 뒀으나 정정됨). 'sell' 은 `rebalance_window_index`가
--    반드시 채워지는 창당 1회 리밸런싱 전용이며, `duel_orders_one_sell_per_window` 유니크
--    인덱스가 창당 1건만 허용합니다.
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
    side               text not null default 'buy' check (side in ('buy', 'sell')),
    -- ⚠️ 2026-08-21 오너 확정 — "매도 영원히 없음"을 정정합니다(work order 참고). 매도는
    --    창(30/90/180일)당 1회 리밸런싱 전용이라 rebalance_window_index 가 반드시 짝을
    --    이룹니다. 매수는 창 개념이 없으므로 반드시 NULL 이어야 합니다 — 실수로 둘 다 채우거나
    --    둘 다 비우면 "이 주문이 리밸런싱 소진 대상인지"를 나중에 알 수 없습니다.
    rebalance_window_index integer,
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

    constraint duel_orders_rebalance_window_match check (
        (side = 'sell' and rebalance_window_index is not null)
        or (side = 'buy' and rebalance_window_index is null)
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

-- 🔴 2026-08-21 추가 — "창당 매도 1회"를 화면이 아니라 DB 가 직접 강제합니다. status
--    가 'cancelled'(배치 처리 전 사용자가 스스로 취소)인 행은 제외해 그 창의 기회를
--    되살립니다 — 이미 종결(filled/expired 성격의 취소 = 가격 미확보)된 행만 그 창을
--    영구히 소진시킵니다. 화면 로직이 실수해도 두 번째 매도 주문의 insert 자체가 이
--    유니크 인덱스에 막힙니다(§0-3-9 이중 방어).
create unique index if not exists duel_orders_one_sell_per_window
    on public.duel_orders (account_id, rebalance_window_index)
    where side = 'sell' and status <> 'cancelled';


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
    '결투다! 예약 주문(수량 기준). 저장 = 예약이지 체결이 아니며, 귀속 거래일(D+1)의 확정 종가로 야간 배치가 체결합니다. 사용자는 pending 상태에서만 수량 수정·취소 가능. side=''sell'' 은 창(30/90/180일)당 1회 리밸런싱 전용(2026-08-21 오너 확정 — 이전의 "매도 영원히 없음" 결정을 정정).';
comment on column public.duel_orders.side is
    '''buy'' 또는 ''sell''. sell 은 rebalance_window_index 가 반드시 채워지고, duel_orders_one_sell_per_window 유니크 인덱스가 창당 1건만 허용합니다.';
comment on column public.duel_orders.rebalance_window_index is
    '리밸런싱 창 번호(0부터). utils/duel_rules.resolve_rebalance_window() 가 계좌의 first_holding_date 와 창 길이(M1=30일/M3=90일/M6=180일)로 계산해 매도 주문 저장 시 채웁니다. 매수 주문은 항상 NULL.';
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
--  ⚠️ 2026-08-21 오너 확정 — event_type 에 'sell' 이 추가됐습니다(창당 1회 리밸런싱
--     매도, work order 정정 섹션 참고). 'reversal' 은 여전히 정정 전용입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_cash_ledger (
    id         bigserial primary key,
    account_id uuid not null references public.duel_accounts (id) on delete cascade,
    event_type text not null
               check (event_type in ('seed', 'monthly_deposit', 'buy', 'sell', 'reversal')),
    amount     numeric(20, 6) not null,   -- 입금·매도는 +, 매수는 −
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
        (event_type in ('seed', 'monthly_deposit', 'sell') and amount > 0)
        or (event_type = 'buy' and amount < 0)
        or event_type = 'reversal'
    ),

    -- 매수 행은 어떤 주문에서 나왔는지가 반드시 남아야 추적이 됩니다. 반대로 입금 행에
    -- 주문이 붙어 있으면 그건 잘못 만든 행입니다.
    constraint duel_cash_ledger_order_link check (
        (event_type in ('buy', 'sell') and order_id is not null)
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
    '입금·매도는 +, 매수는 −. 매도는 창(30/90/180일)당 1회 리밸런싱 전용(2026-08-21 오너 확정 — event_type CHECK 참고).';
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
--  · **기본키는 (user_id, window_type) 입니다(계좌 단위가 아닙니다).** 📝 2026-08-20
--    USD 트랙(§5-11) 도입 결정으로 바뀐 부분입니다(머리말 (m) 참고) — 오너가 "같은
--    사용자면 같은 닉네임을 쓰자"(5-11-10)를 확정하면서, 같은 사용자의 원화 계좌와
--    달러 계좌(같은 창유형)가 같은 닉네임을 공유해야 했습니다. 두 계좌는 물리적으로
--    다른 표(duel_accounts / duel_accounts_usd, §13)에 있는 서로 다른 id 라 계좌 단위
--    기본키로는 그 공유를 표현할 방법이 없어, 사용자 × 창유형 단위로 바꿨습니다.
--    **창유형을 넘어선 공유(M1과 M3가 같은 닉네임)는 하지 않습니다** — 순위표 자체가
--    창유형별로 나뉘어 있어 그 경계를 그대로 존중합니다.
--  · 한 번 만든 닉네임은 그 (사용자, 창유형)에 고정이고 다른 창유형이 물려받지
--    않습니다(5-5). 그래서 update 정책을 주지 않습니다(§9) — 바꿀 수 있으면 "과거
--    순위표의 그 사람"과 "지금의 그 사람"이 다른 문자열이 되어 철회 시 삭제 경로가
--    어긋납니다.
--  · **이 표는 비공개입니다.** 공개표에는 닉네임 문자열만 실리고 user_id·account_id 는
--    절대 실리지 않습니다(§8). 즉 닉네임 ↔ 사용자의 연결고리는 **이 표에만**, 그리고
--    그 표를 읽는 배치(service_role)에만 존재합니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_nicknames (
    user_id     uuid not null references auth.users (id) on delete cascade,
    window_type text not null check (window_type in ('M1', 'M3', 'M6')),
    nickname    text not null unique check (length(btrim(nickname)) > 0),
    created_at  timestamptz not null default now(),
    primary key (user_id, window_type)
);

comment on table public.duel_nicknames is
    '결투다! 사용자 × 창유형별 무작위 닉네임(비공개). 계좌 단위가 아니라 (user_id, window_type) 단위입니다 — 같은 사용자의 원화·달러 계좌(같은 창유형)는 같은 닉네임을 공유합니다(5-11-10). user_id·이메일에서 유도하지 않은 순수 난수이며 해시조차 쓰지 않습니다(역조회 방지 — §0-3-8/§0-3-9).';


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

    -- 🔴 2026-08-20 수정 — 자세한 근거는 바로 아래 §8-1 블록. 요약: 예전 제약은 rank 를
    --    유니크 키에 넣어서 **동점자 두 명이 들어오는 순간 발행이 통째로 거절**됐습니다.
    --    한 참가자가 같은 그룹·같은 날짜에 두 번 실리는 것을 막는 게 진짜 목적이므로,
    --    키를 rank 가 아니라 nickname 으로 잡습니다.
    constraint duel_public_leaderboard_participant_unique
        unique (published_date, window_type, bracket_key, nickname)
);

-- -----------------------------------------------------------------------------
-- 8-1. 🔴 유니크 제약 교체 (2026-08-20 · 5단계 구현 중 발견한 실제 버그)
-- -----------------------------------------------------------------------------
--  **무엇이 잘못돼 있었나.** 최초 스크립트는
--      constraint duel_public_rank_unique unique (published_date, window_type, bracket_key, rank)
--  였습니다. "같은 그룹에 같은 순위가 두 번 들어가면 안 된다"는 뜻이었는데, 이건 순위에
--  **동점이 없다는 가정**입니다. 그 가정은 사실이 아닙니다:
--    · 순위 기준은 TWR(누적 수익률)입니다. 아무것도 사지 않고 현금만 들고 있는 계좌의 TWR 은
--      **정확히 0.000000%** 입니다(계산식이 그렇게 나옵니다 — `duel_rules.compute_twr()`).
--    · 5-6 이 요구하는 발행 최소 인원이 **500명**입니다. 500명 중 "아직 아무것도 안 산 사람"이
--      두 명 이상일 확률은 사실상 1 입니다.
--    · 동점자에게 억지로 다른 순위를 매기려면 어딘가에서 순서를 지어내야 하고(닉네임 가나다순?
--      계좌 생성순?), 그건 사실이 아닌 정보를 남에게 발행하는 일입니다(§0-1). 그래서 앱은
--      동점에 **같은 순위**를 줍니다(1, 2, 2, 4 — `duel_rules.rank_participants()`).
--  → 즉 예전 제약을 그대로 두면, **참가자가 500명을 넘겨 처음으로 순위표가 열리는 바로 그날
--    밤에 발행 배치가 유니크 위반으로 실패**합니다. 지금 고칩니다.
--
--  **무엇으로 바꾸는가.** 이 표에서 실제로 막아야 하는 중복은 "같은 순위"가 아니라
--  **"같은 참가자가 한 그룹·한 날짜에 두 번"** 입니다(발행 배치가 두 번 돌거나 절반만 지워진
--  상태에서 다시 넣는 경우). 그래서 키의 마지막 컬럼을 rank → nickname 으로 바꿉니다.
--  `duel_public_holdings_unique (published_date, nickname, ticker)` 와 같은 발상입니다.
--
--  **읽기 성능은 그대로 유지**합니다 — 화면 질의는
--  `where published_date=? and window_type=? and bracket_key=? order by rank` 이므로,
--  없어진 유니크 인덱스와 **같은 컬럼 조합의 일반 인덱스**를 아래에 다시 만듭니다.
--
--  ⚠️ 이 블록은 이미 예전 스크립트를 실행한 프로젝트를 위한 것입니다. 처음 설치하는
--     프로젝트에서는 위 create table 이 이미 새 제약으로 만들어지므로 아무 일도 하지 않습니다.
--     (drop … if exists → add 순서라 여러 번 실행해도 안전합니다.)
-- -----------------------------------------------------------------------------
alter table public.duel_public_leaderboard
    drop constraint if exists duel_public_rank_unique;

alter table public.duel_public_leaderboard
    drop constraint if exists duel_public_leaderboard_participant_unique;
alter table public.duel_public_leaderboard
    add  constraint duel_public_leaderboard_participant_unique
         unique (published_date, window_type, bracket_key, nickname);

-- 화면 질의용(순위 정렬). 위에서 유니크를 떼면서 사라진 인덱스를 같은 컬럼으로 되살립니다.
create index if not exists duel_public_leaderboard_group_rank_idx
    on public.duel_public_leaderboard (published_date, window_type, bracket_key, rank);

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
-- 8-3. duel_bracket_assignments — 체급 배정 기록 (**비공개**)
--      2026-08-20 추가 · 5단계 구현 중 발견한 구조적 누락 (머리말 (k))
-- =============================================================================
--  **왜 이 표가 없으면 안 되는가.** 작업지시서 5-3(4·5차 확정)은 이렇게 못 박습니다:
--
--      "한 번 정해진 체급(구간)은 다음 정기 시즌이 오기 전까지 바뀌지 않습니다.
--       시즌 도중에 '내 성적표'의 매입원가합계가 실제로 늘거나 줄어도, 그 시즌 안에서는
--       처음 배정된 체급 그대로 유지되고, 순위는 그 고정된 체급 안에서 TWR 로만 갈립니다."
--
--  그런데 **발행 배치는 매일 밤 돕니다.** 매일 밤 "지금 이 사람의 매입원가합계는 얼마지"를
--  다시 물어 체급을 다시 매기면, 위 규칙은 코드 어디에도 위반이라고 적히지 않은 채
--  **조용히 사라집니다.** 그러면 원금이 큰 사람이 시즌 중에 유리한 체급으로 옮겨 다니는
--  것과 같아지고, 그건 "체급을 맞춰 공정하게 겨룬다"는 이 기능의 존재 이유를 없앱니다.
--
--  **발행표를 기억 장치로 쓸 수는 없나 → 없습니다.** `duel_public_leaderboard` 의 행에도
--  bracket_key 가 있지만, 그 행은 최소 인원 미달(5-6)이나 철회(5-8)로 **지워지는 행**입니다.
--  지워지는 것을 기억 장치로 쓰면, 지워진 다음 날 배치가 체급을 처음부터 다시 매깁니다.
--  그래서 배정 기록은 **지워지지 않는 비공개 표**에 따로 있어야 합니다.
--
--  🔴 **이 표에 매입원가합계(금액)를 저장하지 않습니다.** 저장하고 싶은 유혹이 있습니다
--     ("왜 이 체급이 됐는지 나중에 확인하려면?"). 하지만 그 순간 이 표는 **사용자의 실제
--     자산 규모를 담은 표**가 되고, 그건 §0-3-8 이 가장 경계하는 물건입니다. 체급 문자열은
--     어차피 사용자가 공개에 동의해 발행되는 값이지만, 정확한 금액은 아닙니다.
--     "왜 이 체급인가"가 필요하면 그날의 계산을 배치 로그에서 보면 됩니다.
--
--  · 갱신(update) 권한을 **아무에게도 주지 않습니다**(§9-9). 시즌이 바뀌면 `season_key` 가
--    다른 **새 행**이 생기는 것이지, 기존 행이 고쳐지는 게 아닙니다. 즉 "시즌 중 체급 고정"이
--    앱의 조심성이 아니라 **DB 권한**으로 강제됩니다 — 배치 코드에 버그가 나도 이미 배정된
--    체급을 바꿀 수 있는 문법 자체가 없습니다(§0-3-9).
--  · `season_key` 는 시즌 **시작일** 문자열입니다(예: '2026-01-01'). 연도만 쓰면 나중에
--    시즌 길이·기준일을 바꿨을 때 같은 연도 안에 시즌이 둘 생기며 키가 충돌합니다.
--    값을 만드는 곳은 앱 한 곳뿐입니다(`duel_rules.season_key_for_date()`) — 경계 계산을
--    SQL 에도 적으면 두 곳이 언젠가 어긋납니다(§0-3-10).
-- -----------------------------------------------------------------------------
create table if not exists public.duel_bracket_assignments (
    account_id  uuid not null references public.duel_accounts (id) on delete cascade,
    season_key  text not null check (length(btrim(season_key)) > 0),
    bracket_key text not null check (length(btrim(bracket_key)) > 0),
    assigned_at timestamptz not null default now(),
    primary key (account_id, season_key)
);

-- 배치의 실제 질의는 "이번 시즌 배정을 전부 한 번에 읽기"입니다(계좌별 반복 조회 금지 —
-- §0-3-2). 기본키는 account_id 가 앞이라 그 질의를 못 타므로 별도 인덱스를 둡니다.
create index if not exists duel_bracket_assignments_season_idx
    on public.duel_bracket_assignments (season_key, bracket_key);

comment on table public.duel_bracket_assignments is
    '결투다! 체급(원금 구간) 배정 기록(비공개). 계좌 × 시즌 = 1행이며 한 번 쓰이면 그 시즌 동안 바뀌지 않습니다(5-3 "체급은 시즌 동안 고정" 의 강제 장치 — update 권한을 아무에게도 주지 않습니다). 매입원가합계 금액 자체는 저장하지 않습니다(§0-3-8).';
comment on column public.duel_bracket_assignments.season_key is
    '시즌 시작일 문자열(예: 2026-01-01). 값을 만드는 유일한 자리는 utils/duel_rules.py::season_key_for_date() 입니다 — 경계 계산을 SQL 에 두 번 적지 않습니다(§0-3-10).';


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
--      ⚠️ 2026-08-20 이후 **실제 옵트인 경로는 §9-10 의 `duel_opt_in()` RPC 하나**입니다.
--         계좌만 만들고 시드(현금 원장)를 못 넣는 반쪽 상태를 남기지 않기 위해서입니다.
--         아래 insert 정책은 그대로 두지만(과거 경로·관리 도구 호환), 화면은 쓰지 않습니다.
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
alter table public.duel_bracket_assignments enable row level security;


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
--  update/delete 정책 없음: 닉네임은 한 번 만들면 그 (사용자, 창유형)에 고정입니다(5-5).
--  바꿀 수 있으면 발행표에 남아 있는 과거 닉네임과 대응이 끊겨 철회 시 삭제가 새어 나갑니다.
--  🔴 2026-08-20 변경(머리말 (m)): 이 표는 이제 user_id 를 직접 갖고 있어(계좌 id 를
--     거치지 않음), duel_account_is_mine() 을 쓰지 않고 auth.uid() = user_id 로 바로
--     비교합니다 — 원화·달러 어느 계좌를 통해 왔는지와 무관하게 판정이 같아야 하기
--     때문입니다(5-11-10, USD 트랙과의 닉네임 공유).
drop policy if exists duel_nicknames_select_own on public.duel_nicknames;
create policy duel_nicknames_select_own on public.duel_nicknames
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists duel_nicknames_insert_own on public.duel_nicknames;
create policy duel_nicknames_insert_own on public.duel_nicknames
    for insert to authenticated
    with check (auth.uid() = user_id);


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


-- 9-7-1. duel_bracket_assignments — 본인 것만 **조회**만 (2026-08-20 추가 · §8-3) ----
--  insert/update/delete 정책은 **아무에게도** 없습니다. 체급을 정하는 것은 발행 배치의
--  일이고(service_role 이 RLS 를 우회해 씁니다), 사용자가 자기 체급을 고를 수 있으면
--  "가벼운 체급으로 내려가서 1등하기"가 그대로 가능해집니다.
--  select 를 열어 두는 이유는 화면이 "당신은 이번 시즌 ○○ 체급입니다"를 보여줘야 하기
--  때문입니다 — 본인 계좌 것만 보입니다(§9-0 의 소유자 판정 함수).
drop policy if exists duel_bracket_assignments_select_own on public.duel_bracket_assignments;
create policy duel_bracket_assignments_select_own on public.duel_bracket_assignments
    for select to authenticated
    using (public.duel_account_is_mine(account_id));


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
revoke all on public.duel_bracket_assignments from anon;

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
grant select                 on public.duel_bracket_assignments to authenticated;

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

-- 🔴 체급 배정 기록은 배치에게도 **insert 와 select 만** 줍니다(2026-08-20 · §8-3).
--    "체급은 시즌 동안 고정"(5-3)을 **권한으로** 강제하는 자리입니다 — 배치 코드에 버그가
--    나도 이미 배정된 체급을 바꿀 문법 자체가 없습니다. 시즌이 바뀌면 season_key 가 다른
--    **새 행**이 생기는 것이지, 기존 행이 고쳐지는 게 아닙니다.
--    (`duel_cash_ledger` 에 update 를 안 준 것과 같은 종류의 판단입니다.)
revoke update, delete on public.duel_bracket_assignments from service_role;
grant  select, insert on public.duel_bracket_assignments to service_role;

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


-- -----------------------------------------------------------------------------
-- 9-10. 🔐 옵트인 RPC — `public.duel_opt_in()` (2026-08-20 추가 · 작업지시서 2-1)
-- -----------------------------------------------------------------------------
--  **무엇을 푸는 함수인가.** 오너가 2026-08-20 에 "참여하기 버튼을 누르면 시드머니가 즉시
--  들어와야 한다"((B)안)를 확정했습니다. 그런데 위 §9-4 · §9-9 에서 보듯 `duel_cash_ledger`
--  는 **authenticated 에게 insert 정책도, 테이블 권한도, 시퀀스 usage 도 주지 않습니다.**
--  일부러 그렇게 잠근 표입니다 — 사용자 세션(공개된 anon key)이 원장에 직접 쓸 수 있으면
--  자기 계좌에 가상 현금을 무한히 찍을 수 있고, 그 값은 스냅샷 → 공개 순위표로 흘러갑니다.
--
--  그래서 남는 선택지는 둘뿐이었습니다.
--    (가) 사용자 접속 앱 프로세스(Render)에 배치 키를 넣고 거기서 직접 원장에 쓴다.
--         → **채택하지 않습니다.** 그 키는 이 모듈의 RLS 를 통째로 우회합니다. 항상 인터넷에
--           떠 있는 앱 프로세스가 그 키를 들고 있으면, 앱이 한 번 털리는 순간 **모든 사용자의
--           원장에 돈을 쓸 수 있는 키**가 함께 새어 나갑니다. 키를 GitHub Actions Secrets 에만
--           두는 `utils/report_db.py` 이후의 격리 규율(§0-3-8)이 여기서 깨집니다.
--    (나) **이 함수** — 표 소유자 권한으로 도는 `security definer` 저장 프로시저를 만들어,
--         사용자의 **본인 세션(anon key + 로그인 JWT)** 으로 호출하게 합니다(PostgREST RPC).
--         호출 경로 어디에도 배치 키가 없고, 앱 프로세스는 그 키를 알 필요조차 없습니다.
--
--  **왜 이게 안전한가 — 이 함수가 남에게 해줄 수 있는 일이 구조적으로 없습니다.**
--    · **인자가 하나도 없습니다.** user_id 도, 금액도, 날짜도 받지 않습니다. 남의 계좌를
--      만들어 달라고 부탁할 **문법 자체가 없습니다**(§0-3-9 — "조심하기"가 아니라 구조로 막기).
--    · 대상 사용자는 오직 `auth.uid()`, 즉 **지금 이 요청에 실려온 JWT 의 주인**입니다.
--      위 RLS 정책들이 쓰는 것과 **같은 함수, 같은 값**입니다. JWT 가 없으면(비로그인 anon
--      요청) NULL 이라 아래에서 즉시 예외로 거절합니다.
--    · 금액은 인자가 아니라 **`public.duel_seed_amount_krw()` 상수**입니다. 사용자가 금액을
--      불러 주는 경로가 없으므로 "시드 1억으로 주세요"가 불가능합니다.
--    · 하는 일이 계좌 3행 + 시드 원장 3행뿐입니다. 이 함수로 주문·포지션·스냅샷·발행표를
--      건드릴 수 없습니다.
--    · 여러 번 불러도 안전합니다(멱등). 이미 있는 계좌는 `unique (user_id, window_type)`,
--      이미 지급된 시드는 §4-1 의 부분 유니크 인덱스(`duel_cash_ledger_seed_unique`)가
--      흡수합니다 — **이 함수가 새 멱등성 규칙을 발명하지 않고, 이미 있는 것에 기댑니다.**
--      따라서 버튼을 연타해도, 두 탭에서 동시에 눌러도 돈이 두 번 들어가지 않습니다.
--
--  ⚠️ 이 파일에 이미 있는 `duel_account_is_mine()`(§9-0)과 **같은 종류의 장치**입니다 —
--     "권한은 높지만 하는 일이 좁고, 판정은 auth.uid() 로만" 하는 함수. 새 패러다임이
--     아니라 이 스키마가 이미 쓰고 있는 패턴의 두 번째 사례입니다(§0-3-10).
--
--  ⚠️ `service_role` 에는 execute 를 주지 않았습니다. 배치는 `auth.uid()` 가 NULL 이라
--     이 함수를 쓸 수 없고(그래서 즉시 예외), 쓸 필요도 없습니다 — 관리자·백필 경로는
--     `utils/duel_db.py::create_duel_accounts_for_user()`(배치 키 경로)가 그대로 맡습니다.
-- -----------------------------------------------------------------------------

-- 🔴 금액의 **SQL 쪽 유일한 출처**입니다. 여기 말고 다른 SQL 어디에도 시드 금액을 적지 마세요.
--
--    이 파일은 원래 "금액 숫자는 DB 에 적지 않는다"(§1 의 seed_amount default 없음)를
--    규율로 삼았습니다. 그 규율의 목적은 **두 곳에 적힌 숫자가 조용히 어긋나는 것**을 막는
--    것이었고, 지금까지는 앱(`utils/duel_rules.py::SEED_AMOUNT_KRW`)이 항상 명시적으로
--    금액을 넣었기 때문에 DB 가 숫자를 알 필요가 없었습니다.
--
--    옵트인 RPC 는 그 조건이 성립하지 않습니다. 금액을 앱에서 인자로 받으면 **사용자가
--    금액을 고를 수 있게** 되고(= 스스로 돈을 찍는 경로), 그건 이 함수를 만든 이유 자체를
--    없앱니다. 그래서 금액은 DB 안에 있어야만 하고, **여기 한 줄이 그 자리**입니다.
--
--    🔁 앱 상수와의 동기화는 사람의 기억에 맡기지 않습니다:
--       `tests/test_duel_db.py::test_sql_seed_constant_matches_the_app_constant` 이 이 파일을
--       읽어 아래 숫자와 `utils/duel_rules.py::SEED_AMOUNT_KRW` 가 다르면 **테스트를 실패**
--       시킵니다. 한쪽만 고치면 배포 전에 잡힙니다.
create or replace function public.duel_seed_amount_krw()
returns numeric
language sql
immutable
as $$
    select 10000000::numeric   -- ⚠️ utils/duel_rules.py::SEED_AMOUNT_KRW 와 반드시 같아야 합니다
$$;

revoke all on function public.duel_seed_amount_krw() from public;
grant execute on function public.duel_seed_amount_krw() to authenticated, service_role;

comment on function public.duel_seed_amount_krw() is
    '결투 시드머니(원)의 SQL 쪽 단일 출처. 앱 상수 utils/duel_rules.py::SEED_AMOUNT_KRW 와 같아야 하며, tests/test_duel_db.py 가 두 값의 일치를 자동으로 검사합니다.';


-- 반환 타입이 나중에 바뀌어도 스크립트 재실행이 안전하도록 drop 후 create 합니다
-- (create or replace 는 반환 타입 변경을 거부합니다). 함수가 없을 때도 조용히 넘어갑니다.
drop function if exists public.duel_opt_in();

create function public.duel_opt_in()
returns setof public.duel_accounts
language plpgsql
security definer
set search_path = public
as $$
declare
    -- 🔴 **대상 사용자는 여기서만 정해집니다.** 인자가 아니라 지금 요청의 JWT 입니다.
    caller    uuid    := auth.uid();
    -- 🔴 금액도 인자가 아닙니다(위 상수 함수).
    seed      numeric := public.duel_seed_amount_krw();
    -- 개설일도 인자가 아닙니다 — 사용자가 유리한 날짜를 고르는 경로를 만들지 않습니다.
    -- DB 의 current_date 는 UTC 라 쓰지 않습니다(§4 event_date 주석과 같은 이유). 한국시간
    -- 자정 직후에 참여한 사용자의 개설일이 하루 전으로 기록되면 안 됩니다.
    today_kst date    := (now() at time zone 'Asia/Seoul')::date;
begin
    if caller is null then
        -- 조용히 0행을 돌려주지 않습니다(§0-1). 비로그인 호출은 실패로 드러나야 합니다.
        raise exception
            'duel_opt_in: 로그인한 사용자만 결투 모듈에 참여할 수 있습니다(요청에 로그인 세션이 없습니다).'
            using errcode = '28000';
    end if;

    -- ① 계좌 3개(M1/M3/M6) — **없는 창유형만** 한 번의 insert 로.
    --    동시에 두 번 눌려도 unique (user_id, window_type) 가 두 번째를 흡수합니다.
    insert into public.duel_accounts
        (user_id, window_type, seed_amount, currency, anchor_date, status)
    select caller, w.window_type, seed, 'KRW', today_kst, 'active'
      from unnest(array['M1', 'M3', 'M6']) as w(window_type)
    on conflict (user_id, window_type) do nothing;

    -- ② 시드 원장 — **시드가 아직 없는 계좌에만** 한 번의 insert 로.
    --    멱등성은 §4-1 의 duel_cash_ledger_seed_unique(계좌당 seed 1행) 부분 유니크 인덱스가
    --    보장합니다. 새 규칙을 만들지 않고 이미 있는 방어에 기댑니다.
    --    event_date 는 그 계좌의 anchor_date 입니다 — 오늘 날짜가 아니라 **계좌가 실제로
    --    열린 날**이어야 시드가 개설일 현금흐름(TWR 의 F_0)으로 잡힙니다(2-6).
    --    ⚠️ 금액은 a.seed_amount 가 아니라 위 상수를 씁니다. §9-1 이 사용자에게
    --       duel_accounts insert 를 허용하므로, 계좌 행의 숫자는 사용자가 미리 적어 넣었을
    --       수 있는 값입니다 — 원장 금액의 근거로 삼지 않습니다.
    insert into public.duel_cash_ledger
        (account_id, event_type, amount, event_date, memo)
    select a.id, 'seed', seed, a.anchor_date, '결투 계좌 개설 시드머니'
      from public.duel_accounts a
     where a.user_id = caller
    on conflict (account_id) where event_type = 'seed' do nothing;

    -- ③ 앱이 두 번 왕복하지 않도록 계좌 3행을 그대로 돌려줍니다(창유형 순서 고정).
    return query
        select a.*
          from public.duel_accounts a
         where a.user_id = caller
         order by array_position(array['M1', 'M3', 'M6'], a.window_type);
end;
$$;

-- 🔴 execute 는 **로그인 사용자(authenticated)에게만**. anon(비로그인)에게 주지 않습니다 —
--    auth.uid() 가 NULL 이라 어차피 예외로 끝나지만, "부를 수는 있는 함수"로 남겨 두지
--    않습니다(§9-9 의 revoke ... from anon 과 같은 이중 방어).
revoke all on function public.duel_opt_in() from public;
grant execute on function public.duel_opt_in() to authenticated;

comment on function public.duel_opt_in() is
    '결투 모듈 옵트인(계좌 3개 + 시드 원장 3행)을 사용자 **본인 세션**으로 처리하는 security definer RPC. 인자가 없고 대상은 auth.uid() 뿐이라 남을 대신해 부를 수 없으며, 금액은 duel_seed_amount_krw() 상수입니다. 여러 번 불러도 안전합니다(계좌·시드 유니크 인덱스). 앱 서버에 배치 키를 두지 않고 즉시 지급을 구현하기 위한 장치입니다.';


-- =============================================================================
-- 9-11. 🔴 리밸런싱 매도 정산 RPC — `duel.settled_sell` 을 켤 수 있는 **유일한 자리**
--        (2026-08-21 추가 · service_role 전용 · USD 미러는 §14-11)
-- =============================================================================
--  ── 왜 표 update 가 아니라 RPC 인가 (이 파일에서 RPC 를 쓰는 두 번째 자리) ─────────
--  §2-1 의 `duel_positions_buy_only()` 트리거는 수량 감소를 막고, 리밸런싱 매도 정산만은
--  **같은 트랜잭션에서** `set local duel.settled_sell = 'on'` 이 먼저 실행됐을 때 통과시킵니다.
--  그런데 야간 배치는 Supabase 를 **PostgREST(REST)** 로 부릅니다 — REST 요청 하나가 곧
--  트랜잭션 하나이고, 클라이언트가 임의의 세션 변수를 앞세워 보낼 문법이 없습니다.
--  (PostgREST 가 트랜잭션에 심어 주는 값은 role · request.jwt.claims · request.headers 처럼
--   정해진 것뿐이고, `db-pre-request` 는 서버 전역 설정이라 "모든 요청에 항상 켜짐"이 됩니다 —
--   그건 정확히 이 트리거가 막으려던 상태입니다.)
--  그래서 **"세션 변수 켜기 + 수량 줄이기"를 한 번의 호출 안에서 원자적으로** 하는 좁은
--  함수를 둡니다. 플래그는 이 함수 안에서만 켜졌다가 끝나기 전에 꺼집니다.
--
--  ── 이 함수를 좁게 유지하는 장치 넷 (트리거를 우회하는 유일한 통로이므로) ──────────
--    · **수량만** 바꿉니다. `avg_cost` 는 손대지 않습니다 — "매도는 잔여 주식의 매입단가를
--      바꾸지 않는다"(`utils/duel_rules.py::apply_sell_fill_to_position()`)를 DB 에서도
--      그대로 강제하고, 정산 경로로 원가를 다시 쓰는 길을 아예 없앱니다.
--    · **줄이는 방향만** 허용합니다. 새 수량이 현재 수량 이상인 행이 하나라도 있으면 전체를
--      거절합니다 — 이 통로로 수량을 늘릴 수 있으면 트리거 전체가 장식이 됩니다.
--    · **행을 만들지 않습니다.** 없는 (계좌, 종목)이 들어오면 거절합니다(보유하지 않은
--      종목이 팔렸다는 뜻이라, 조용히 0건 처리하면 그 사실이 사라집니다 — §0-1).
--    · execute 는 **service_role 에게만**. 사용자 세션(anon/authenticated)은 이 함수를
--      부를 수 없습니다(§9-9 의 revoke 관례와 같은 이중 방어).
--
--  ⚠️ 한 번에 여러 행을 받습니다(jsonb 배열). 배치가 계좌마다 부르면 그게 §0-3-2 가 금지한
--     모양이 됩니다 — 호출부(`utils/duel_db.py::settle_sell_positions()`)는 그날 매도 정산
--     전체를 한 번(또는 CHUNK_SIZE 단위)에 보냅니다.
-- =============================================================================
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
--  ④ 수량 감소 통제 트리거가 실제로 막는지 (개발용 계좌에서만 시도하세요)
--      -- 아래 update 는 세션 변수 없이는 반드시 예외로 실패해야 정상입니다.
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
--
--  ⑨ 옵트인 RPC(§9-10)가 제대로 설치됐는지 — 아래 3가지를 눈으로 확인하세요.
--     (가) 함수가 security definer 이고 인자가 0개인지 (prosecdef=true, pronargs=0 이어야 정상)
--      select proname, prosecdef, pronargs, pg_get_function_result(oid) as returns
--        from pg_proc
--       where pronamespace = 'public'::regnamespace
--         and proname in ('duel_opt_in', 'duel_seed_amount_krw');
--
--     (나) execute 권한이 **authenticated 에게만** 있는지 (anon 이 나오면 잘못된 것입니다)
--      select grantee, privilege_type
--        from information_schema.routine_privileges
--       where routine_schema = 'public' and routine_name = 'duel_opt_in';
--
--     (다) 시드 금액이 앱 상수와 같은지 (10000000 이어야 정상 —
--          다르면 utils/duel_rules.py::SEED_AMOUNT_KRW 와 어긋난 것입니다)
--      select public.duel_seed_amount_krw();
--
--     ⏱️ 함수를 새로 만든 직후에는 PostgREST(Supabase 의 REST 계층)의 **스키마 캐시**가
--        아직 갱신되지 않아 앱에서 몇 초간 "함수를 찾을 수 없다"(PGRST202)가 날 수 있습니다.
--        보통 저절로 반영되며, 급하면 대시보드에서 API 재시작(또는
--        `notify pgrst, 'reload schema';`)으로 즉시 반영됩니다. 앱은 이 오류를 "아직
--        설치되지 않았습니다"라는 한국어 문장으로 바꿔 보여줍니다(utils/duel_db.py).
--
--     ⚠️ 실제 동작(본인 계좌 3개만 생기는지, 두 번 눌러도 시드가 한 번만 들어가는지)은
--        SQL Editor 가 아니라 **로그인한 앱에서** 확인해야 합니다 — SQL Editor 는 postgres
--        권한이라 auth.uid() 가 NULL 이고, 이 함수는 그 경우 일부러 실패합니다.
-- =============================================================================
-- =============================================================================
--  ⚔️ "결투다!" USD 트랙("달러 결투") 스키마 추가분 — DUEL_MODULE_WORK_ORDER.md §5-11
--  이 블록은 sql/duel_schema.sql **끝에 그대로 이어 붙이는** 추가분입니다(같은 파일,
--  같은 실행 방법 — SQL Editor 에 전체를 붙여넣고 Run). 기존 §1~11 은 한 글자도 건드리지
--  않았고(원화 트랙 보호), 아래는 전부 새로 추가되는 내용입니다.
--
--  🔴 아키텍처 원칙(작업지시서 5-11-1 그대로): **데이터는 완전 분리, 순수 규칙은 공유.**
--     · 데이터 표는 전부 새 표(_usd 접미사)로 물리적으로 분리합니다 — 원화 표를 절대
--       건드리지 않고, 구분 컬럼으로 묶지도 않습니다(오너 확정 — WHERE 절 하나 빠뜨리면
--       두 트랙이 섞이는 통로가 생기는 걸 원천 차단).
--     · 트리거 함수(duel_set_updated_at · duel_positions_buy_only · duel_orders_guard ·
--       duel_cash_ledger_append_only · duel_consent_guard)는 전부 NEW/OLD 로만 동작하고
--       표 이름을 하드코딩하지 않으므로, **그대로 재사용**합니다 — 이 함수들을 복제하면
--       "규칙을 고쳤는데 한쪽만 고쳤다"는 사고가 생깁니다(5-11-1 의 "순수 규칙 공유").
--     · 소유자 판정 함수(duel_account_is_mine)만은 표 이름이 본문에 박혀 있어 복제가
--       불가피합니다 — duel_account_is_mine_usd() 로 새로 만듭니다.
--     · 닉네임(duel_nicknames)은 예외적으로 **공유 자원**입니다(5-11-10, 오너 확정) —
--       원화 계좌와 달러 계좌가 같은 (user_id, window_type) 이면 같은 닉네임을 씁니다.
--       그래서 새 _usd 표를 만들지 않고, sql/duel_schema.sql §6 의 정의 자체를 이미
--       (user_id, window_type) 단위로 바꿨습니다(머리말 (m)) — 아래 §12 는 예전 버전을
--       이미 설치한 프로젝트만을 위한 마이그레이션 브리지입니다(새 설치는 아무 일도 안 함).
-- =============================================================================


-- =============================================================================
-- 12. duel_nicknames 마이그레이션 브리지 — 예전 버전(계좌 단위)을 이미 설치한 프로젝트 전용
--      2026-08-20 추가 · USD 트랙 도입에 따른 마이그레이션
-- =============================================================================
--  🔴 **위 §6 의 duel_nicknames 정의 자체를 이미 (user_id, window_type) 단위로 바꿨습니다**
--     (머리말 (m) 참고). 즉 **새로 설치하는 프로젝트는 이 블록이 통째로 아무 일도 하지
--     않습니다** — §6 의 create table 이 처음부터 최종 구조를 만들기 때문입니다.
--
--  이 블록은 오직 "이 파일의 예전 버전(2026-08-20 이전, `account_id` 를 기본키로 쓰던
--  버전)을 이미 실행해 계좌 단위 duel_nicknames 가 실제로 만들어져 있는 프로젝트"만을
--  위한 것입니다. 컬럼 존재 여부로 스스로 판단해서, 이미 새 구조라면 그냥 넘어갑니다.
--
--  ⚠️ **정책을 컬럼 삭제보다 먼저 지웁니다.** 예전 정책(duel_nicknames_select_own/
--     insert_own)이 account_id 컬럼을 참조하고 있어서, 정책을 먼저 지우지 않고 컬럼부터
--     지우면 "다른 객체가 이 컬럼에 의존한다"는 오류가 납니다(실제로 로컬 PostgreSQL 16 에
--     반대 순서로 실행해보고 걸린 문제라 지금 이 순서로 고쳐 둡니다 — 그리고 이 오류를
--     아예 만나지 않도록, 전체를 `if exists` 로 감싸 새 설치에서는 실행조차 안 되게 합니다).
-- -----------------------------------------------------------------------------
do $$
begin
    if exists (
        select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'duel_nicknames'
           and column_name = 'account_id'
    ) then
        execute 'drop policy if exists duel_nicknames_select_own on public.duel_nicknames';
        execute 'drop policy if exists duel_nicknames_insert_own on public.duel_nicknames';

        execute 'alter table public.duel_nicknames add column if not exists user_id uuid';
        execute 'alter table public.duel_nicknames add column if not exists window_type text';

        -- 기존 행(계좌 단위로 만들어진 것)을 duel_accounts 에서 역참조해 백필합니다.
        execute '
            update public.duel_nicknames n
               set user_id     = a.user_id,
                   window_type = a.window_type
              from public.duel_accounts a
             where n.account_id = a.id
               and n.user_id is null';

        execute 'alter table public.duel_nicknames alter column user_id set not null';
        execute 'alter table public.duel_nicknames alter column window_type set not null';

        execute '
            alter table public.duel_nicknames
                add constraint duel_nicknames_window_type_check
                    check (window_type in (''M1'', ''M3'', ''M6''))';

        execute 'alter table public.duel_nicknames drop constraint if exists duel_nicknames_pkey';
        execute '
            alter table public.duel_nicknames
                add constraint duel_nicknames_pkey primary key (user_id, window_type)';

        execute '
            alter table public.duel_nicknames
                add constraint duel_nicknames_user_fk
                    foreign key (user_id) references auth.users (id) on delete cascade';

        -- account_id 는 더 이상 이 표의 정체성이 아닙니다 — 위에서 정책을 먼저 지웠으므로
        -- 이제 안전하게 지울 수 있습니다.
        execute 'alter table public.duel_nicknames drop column account_id';

        -- §9-6 의 최종 형태와 똑같은 새 정책을 다시 만듭니다.
        execute '
            create policy duel_nicknames_select_own on public.duel_nicknames
                for select to authenticated
                using (auth.uid() = user_id)';
        execute '
            create policy duel_nicknames_insert_own on public.duel_nicknames
                for insert to authenticated
                with check (auth.uid() = user_id)';

        raise notice 'duel_nicknames: 예전 계좌 단위 구조를 (user_id, window_type) 단위로 마이그레이션했습니다.';
    end if;
end
$$;


-- =============================================================================
-- 13. USD 트랙 전용 표 — 원화 표(§1~8-3)와 물리적으로 완전히 분리된 미러
--      2026-08-20 추가 · DUEL_MODULE_WORK_ORDER.md §5-11
-- =============================================================================
--  아래 10개 표는 각각 §1(duel_accounts) ~ §8-3(duel_bracket_assignments) 의 원화 표와
--  **컬럼·제약·트리거·인덱스가 전부 동일**하고, 차이는 딱 두 가지뿐입니다 — 표 이름 뒤에
--  `_usd` 가 붙는다는 것과, duel_accounts_usd.currency 의 CHECK 값이 'USD' 라는 것.
--  중복 설명은 생략하고 각 표 위 원화 표의 절 번호만 표시합니다 — 근거·트레이드오프는
--  전부 그 절의 주석을 그대로 적용하면 됩니다.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 13-1. duel_accounts_usd (§1 미러) — currency='USD' 고정, 시드 $7,500(앱 상수가 단일 출처)
-- -----------------------------------------------------------------------------
create table if not exists public.duel_accounts_usd (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users (id) on delete cascade,
    window_type  text not null check (window_type in ('M1', 'M3', 'M6')),
    seed_amount  numeric(20, 6) not null check (seed_amount > 0),   -- default 없음(§1 과 같은 이유)
    currency     text not null default 'USD' check (currency = 'USD'),
    anchor_date  date not null,
    -- 원화 트랙과 같은 이유(§1 주석 참고) — 2026-08-21 오너 확정.
    first_holding_date date,
    status       text not null default 'active' check (status in ('active', 'closed')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    constraint duel_accounts_usd_user_window_unique unique (user_id, window_type)
);

create index if not exists duel_accounts_usd_status_idx
    on public.duel_accounts_usd (status);

drop trigger if exists duel_accounts_usd_set_updated_at on public.duel_accounts_usd;
create trigger duel_accounts_usd_set_updated_at
    before update on public.duel_accounts_usd
    for each row execute function public.duel_set_updated_at();   -- 원화와 같은 함수 재사용

comment on table public.duel_accounts_usd is
    '결투다! USD 트랙 가상계좌(§5-11). 사용자당 M1/M3/M6 정확히 3개, 시드 $7,500 고정, 달러 전용. duel_accounts(원화)와 물리적으로 완전히 분리된 별개 표 — 절대 조인·합산하지 않습니다.';
comment on column public.duel_accounts_usd.seed_amount is
    '개설 시점의 시드머니(달러). DB default 없음 — 금액의 단일 출처는 앱 상수 utils/duel_rules.py::SEED_AMOUNT_USD 입니다(§1 과 같은 이유).';


-- -----------------------------------------------------------------------------
-- 13-2. duel_positions_usd (§2 미러) — 매수 + 창당 1회 리밸런싱 매도, 트리거 함수는 원화와 공유
-- -----------------------------------------------------------------------------
create table if not exists public.duel_positions_usd (
    id            uuid primary key default gen_random_uuid(),
    account_id    uuid not null references public.duel_accounts_usd (id) on delete cascade,
    ticker        text not null check (length(ticker) between 1 and 20),
    stock_name    text not null,
    quantity      numeric(20, 6) not null check (quantity >= 0),
    avg_cost      numeric(20, 6) not null check (avg_cost >= 0),
    status        text not null default 'active' check (status in ('active', 'delisted')),
    delisted_date date,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    constraint duel_positions_usd_account_ticker_unique unique (account_id, ticker),
    constraint duel_positions_usd_delisted_match check (
        (status = 'delisted' and delisted_date is not null)
        or (status <> 'delisted' and delisted_date is null)
    )
);

drop trigger if exists duel_positions_usd_set_updated_at on public.duel_positions_usd;
create trigger duel_positions_usd_set_updated_at
    before update on public.duel_positions_usd
    for each row execute function public.duel_set_updated_at();

-- §2-1 의 수량 감소 통제 트리거 함수(duel_positions_buy_only)는 NEW/OLD 로만 동작하고 표 이름을
-- 하드코딩하지 않으므로 그대로 재사용합니다 — 함수를 복제하지 않습니다(5-11-1).
drop trigger if exists duel_positions_usd_no_sell on public.duel_positions_usd;
create trigger duel_positions_usd_no_sell
    before update on public.duel_positions_usd
    for each row execute function public.duel_positions_buy_only();

comment on table public.duel_positions_usd is
    '결투다! USD 트랙 가상 보유 포지션(§5-11). 수량 감소 제어 트리거는 원화 표와 같은 함수(duel_positions_buy_only)를 공유합니다 — 리밸런싱 매도 정산은 duel.settled_sell 세션 변수로(2026-08-21 오너 확정). 쓰기는 배치(service_role)만, 사용자는 읽기 전용.';


-- -----------------------------------------------------------------------------
-- 13-3. duel_orders_usd (§3 미러) — 수량 기준, D일 접수 → D+1 미국 정규장 마감가 체결
-- -----------------------------------------------------------------------------
create table if not exists public.duel_orders_usd (
    id                 uuid primary key default gen_random_uuid(),
    account_id         uuid not null references public.duel_accounts_usd (id) on delete cascade,
    ticker             text not null check (length(ticker) between 1 and 20),
    stock_name         text not null,
    requested_quantity integer not null check (requested_quantity > 0),
    side               text not null default 'buy' check (side in ('buy', 'sell')),
    -- 2026-08-21 오너 확정 — 원화 트랙과 같은 이유로 매도를 추가합니다(§2-1 주석 참고).
    rebalance_window_index integer,
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

    constraint duel_orders_usd_filled_within_request check (
        filled_quantity is null or filled_quantity <= requested_quantity
    ),
    constraint duel_orders_usd_rebalance_window_match check (
        (side = 'sell' and rebalance_window_index is not null)
        or (side = 'buy' and rebalance_window_index is null)
    ),
    constraint duel_orders_usd_reason_required check (
        status in ('pending', 'filled')
        or (fail_reason is not null and length(btrim(fail_reason)) > 0)
    ),
    constraint duel_orders_usd_fill_fields_together check (
        (filled_date is null and filled_price is null
             and filled_quantity is null and filled_amount is null)
        or (filled_date is not null and filled_price is not null
             and filled_quantity is not null and filled_amount is not null)
    ),
    constraint duel_orders_usd_status_fill_match check (
        (status in ('filled', 'partially_filled') and filled_quantity is not null
             and filled_quantity > 0)
        or (status = 'pending' and filled_quantity is null)
        or status in ('cancelled', 'expired')
    )
);

create index if not exists duel_orders_usd_pending_target_idx
    on public.duel_orders_usd (target_date, saved_at)
    where status = 'pending';

create index if not exists duel_orders_usd_account_saved_idx
    on public.duel_orders_usd (account_id, saved_at desc);

-- 원화 트랙의 duel_orders_one_sell_per_window 와 같은 이유(§2-1 주석 참고).
create unique index if not exists duel_orders_usd_one_sell_per_window
    on public.duel_orders_usd (account_id, rebalance_window_index)
    where side = 'sell' and status <> 'cancelled';

-- §3-1 의 상태 전이 가드(duel_orders_guard)도 표 이름을 하드코딩하지 않으므로 재사용합니다.
drop trigger if exists duel_orders_usd_transition_guard on public.duel_orders_usd;
create trigger duel_orders_usd_transition_guard
    before update on public.duel_orders_usd
    for each row execute function public.duel_orders_guard();

comment on table public.duel_orders_usd is
    '결투다! USD 트랙 예약 주문(수량 기준). D일 KST 16:00~21:00 접수 → D+1 미국 정규장 마감가로 야간 배치가 체결합니다(5-11-6 — 이 시간대는 그날 미국 정규장 개장 전이라 국내 모델과 다른 메커니즘이지만 결과는 동일하게 선행매매 불가능합니다). 사용자는 pending 상태에서만 수량 수정·취소 가능. side=''sell'' 은 창당 1회 리밸런싱 전용(2026-08-21 오너 확정, 원화 트랙과 동일 규칙).';


-- -----------------------------------------------------------------------------
-- 13-4. duel_cash_ledger_usd (§4 미러) — append-only, 트리거 함수는 원화와 공유
-- -----------------------------------------------------------------------------
create table if not exists public.duel_cash_ledger_usd (
    id         bigserial primary key,
    account_id uuid not null references public.duel_accounts_usd (id) on delete cascade,
    event_type text not null
               check (event_type in ('seed', 'monthly_deposit', 'buy', 'sell', 'reversal')),
    amount     numeric(20, 6) not null,
    event_date date not null,
    order_id   uuid references public.duel_orders_usd (id),   -- on delete no action(§4 와 같은 이유)
    memo       text,
    created_at timestamptz not null default now(),

    constraint duel_cash_ledger_usd_sign_match check (
        (event_type in ('seed', 'monthly_deposit', 'sell') and amount > 0)
        or (event_type = 'buy' and amount < 0)
        or event_type = 'reversal'
    ),
    constraint duel_cash_ledger_usd_order_link check (
        (event_type in ('buy', 'sell') and order_id is not null)
        or (event_type in ('seed', 'monthly_deposit') and order_id is null)
        or event_type = 'reversal'
    )
);

create index if not exists duel_cash_ledger_usd_account_date_idx
    on public.duel_cash_ledger_usd (account_id, event_date);

-- 멱등성(§4-1 미러) — 월 $500 입금은 계좌×해당월 1행, 시드는 계좌당 1행.
create unique index if not exists duel_cash_ledger_usd_monthly_deposit_unique
    on public.duel_cash_ledger_usd (account_id, event_date)
    where event_type = 'monthly_deposit';

create unique index if not exists duel_cash_ledger_usd_seed_unique
    on public.duel_cash_ledger_usd (account_id)
    where event_type = 'seed';

-- §4-2 의 append-only 강제 함수(duel_cash_ledger_append_only)도 표 이름을 하드코딩하지
-- 않으므로 재사용합니다.
drop trigger if exists duel_cash_ledger_usd_no_update on public.duel_cash_ledger_usd;
create trigger duel_cash_ledger_usd_no_update
    before update on public.duel_cash_ledger_usd
    for each row execute function public.duel_cash_ledger_append_only();

comment on table public.duel_cash_ledger_usd is
    '결투다! USD 트랙 현금 원장(append-only). 매월 $500 정기입금이 창 길이와 무관하게 누적됩니다(5-11-4 — 원화 트랙의 "창 길이에 비례해 깎지 않음" 규칙을 그대로 재사용). event_type=''sell'' 은 창당 1회 리밸런싱 전용(2026-08-21 오너 확정, 원화 트랙과 동일). 정정은 반대 부호의 reversal 행으로만.';


-- -----------------------------------------------------------------------------
-- 13-5. duel_daily_snapshots_usd / duel_holding_snapshots_usd (§5 미러)
-- -----------------------------------------------------------------------------
create table if not exists public.duel_daily_snapshots_usd (
    id               uuid primary key default gen_random_uuid(),
    account_id       uuid not null references public.duel_accounts_usd (id) on delete cascade,
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

    constraint duel_snapshots_usd_account_date_unique unique (account_id, snapshot_date),
    constraint duel_snapshots_usd_priced check (priced_count > 0 or position_value = 0),
    constraint duel_snapshots_usd_total_match check (total_value = position_value + cash_balance),
    constraint duel_snapshots_usd_cash_flow_match check (
        (cash_flow_amount = 0 and cash_flow_kind is null)
        or (cash_flow_amount > 0 and cash_flow_kind is not null)
    )
);

create index if not exists duel_snapshots_usd_account_date_desc_idx
    on public.duel_daily_snapshots_usd (account_id, snapshot_date desc);
create index if not exists duel_snapshots_usd_date_idx
    on public.duel_daily_snapshots_usd (snapshot_date);

drop trigger if exists duel_snapshots_usd_set_updated_at on public.duel_daily_snapshots_usd;
create trigger duel_snapshots_usd_set_updated_at
    before update on public.duel_daily_snapshots_usd
    for each row execute function public.duel_set_updated_at();

comment on table public.duel_daily_snapshots_usd is
    '결투다! USD 트랙 계좌 × 거래일 = 1행 합계 스냅샷(§5-11). cash_flow_amount 는 TWR 계산의 필수 입력(원화 표와 같은 규칙). 쓰기는 배치(service_role)만.';


create table if not exists public.duel_holding_snapshots_usd (
    id            uuid primary key default gen_random_uuid(),
    account_id    uuid not null references public.duel_accounts_usd (id) on delete cascade,
    ticker        text not null check (length(ticker) between 1 and 20),
    snapshot_date date not null,
    stock_name    text,
    quantity      numeric(20, 6) not null check (quantity >= 0),
    avg_cost      numeric(20, 6) not null check (avg_cost >= 0),
    cost          numeric(20, 6) not null check (cost >= 0),
    close_price   numeric(20, 6) check (close_price is null or close_price >= 0),
    market_value  numeric(20, 6) check (market_value is null or market_value >= 0),
    status        text not null default 'active' check (status in ('active', 'delisted')),
    priced        boolean not null,
    price_as_of_kst text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),

    constraint duel_holding_snapshots_usd_account_ticker_date_unique
        unique (account_id, ticker, snapshot_date),
    constraint duel_holding_snapshots_usd_priced_match check (
        (priced and close_price is not null and market_value is not null)
        or (not priced and close_price is null and market_value is null)
    )
);

create index if not exists duel_holding_snapshots_usd_account_date_idx
    on public.duel_holding_snapshots_usd (account_id, snapshot_date);

drop trigger if exists duel_holding_snapshots_usd_set_updated_at on public.duel_holding_snapshots_usd;
create trigger duel_holding_snapshots_usd_set_updated_at
    before update on public.duel_holding_snapshots_usd
    for each row execute function public.duel_set_updated_at();

comment on table public.duel_holding_snapshots_usd is
    '결투다! USD 트랙 계좌 × 종목 × 거래일 = 1행 상세 스냅샷(§5-11). priced=false 인 종목은 close_price/market_value 가 NULL 입니다(가격 미확인을 0으로 치지 않음 — §0-1).';


-- -----------------------------------------------------------------------------
-- 13-6. duel_public_consent_usd (§7 미러) — 트리거 함수는 원화와 공유
-- -----------------------------------------------------------------------------
--  ⚠️ 작업지시서 5-11-10 확정: **이 표는 duel_public_consent(원화)와 완전히 독립입니다.**
--     한쪽만 동의하고 다른 쪽은 동의 안 해도 되고, 한쪽 철회가 다른 쪽에 영향을 주지
--     않습니다. 공유되는 건 오직 duel_nicknames(§12)의 닉네임 문자열뿐입니다.
-- -----------------------------------------------------------------------------
create table if not exists public.duel_public_consent_usd (
    account_id                     uuid primary key
                                   references public.duel_accounts_usd (id) on delete cascade,
    consent_rank                   boolean not null default false,
    consent_return                 boolean not null default false,
    consent_holdings               boolean not null default false,
    consent_quantity                boolean not null default false,
    consent_buy_amount             boolean not null default false,
    final_confirmed                boolean not null default false,
    final_confirmed_at             timestamptz,
    consent_real_principal_bracket boolean not null default false,
    revoked_at                     timestamptz,
    created_at                     timestamptz not null default now(),
    updated_at                     timestamptz not null default now(),

    constraint duel_consent_usd_final_requires_all check (
        not final_confirmed
        or (consent_rank and consent_return and consent_holdings
            and consent_quantity and consent_buy_amount)
    ),
    constraint duel_consent_usd_final_time check (
        (final_confirmed and final_confirmed_at is not null)
        or (not final_confirmed and final_confirmed_at is null)
    ),
    constraint duel_consent_usd_revoked_not_confirmed check (
        revoked_at is null or not final_confirmed
    )
);

drop trigger if exists duel_consent_usd_set_updated_at on public.duel_public_consent_usd;
create trigger duel_consent_usd_set_updated_at
    before update on public.duel_public_consent_usd
    for each row execute function public.duel_set_updated_at();

-- §7-1 의 철회 되돌리기 금지 함수(duel_consent_guard)도 표 이름을 하드코딩하지 않으므로
-- 재사용합니다.
drop trigger if exists duel_consent_usd_no_revoke_reset on public.duel_public_consent_usd;
create trigger duel_consent_usd_no_revoke_reset
    before update on public.duel_public_consent_usd
    for each row execute function public.duel_consent_guard();

comment on table public.duel_public_consent_usd is
    '결투다! USD 트랙 공개 동의 상태(§5-11). duel_public_consent(원화)와 완전히 독립입니다 — 한쪽만 동의해도 되고, 철회도 서로 영향 없습니다. 공유되는 건 duel_nicknames 의 닉네임 문자열뿐입니다(5-11-10).';


-- -----------------------------------------------------------------------------
-- 13-7. duel_bracket_assignments_usd (§8-3 미러) — 체급 8단계(달러), update/delete 권한 없음
-- -----------------------------------------------------------------------------
--  경계값은 여기 저장하지 않습니다(원화 표와 같은 이유 — §0-3-8). 단일 출처는
--  utils/duel_rules.py::BRACKET_TIERS_USD 입니다.
create table if not exists public.duel_bracket_assignments_usd (
    account_id  uuid not null references public.duel_accounts_usd (id) on delete cascade,
    season_key  text not null check (length(btrim(season_key)) > 0),
    bracket_key text not null check (length(btrim(bracket_key)) > 0),
    assigned_at timestamptz not null default now(),
    primary key (account_id, season_key)
);

create index if not exists duel_bracket_assignments_usd_season_idx
    on public.duel_bracket_assignments_usd (season_key, bracket_key);

comment on table public.duel_bracket_assignments_usd is
    '결투다! USD 트랙 체급(원금 구간) 배정 기록(비공개, §5-11). 계좌 × 시즌 = 1행, 한 번 쓰이면 그 시즌 동안 바뀌지 않습니다(update 권한을 아무에게도 주지 않음). 시즌은 원화 트랙과 공유합니다(5-11-8) — season_key 값 자체는 같은 함수(season_key_for_date)가 만듭니다.';


-- -----------------------------------------------------------------------------
-- 13-8. duel_public_leaderboard_usd / duel_public_holdings_usd (§8 미러) — 완전 별개 발행표
-- -----------------------------------------------------------------------------
--  🔴 작업지시서 5-11-9 확정: 한국장·미국장 순위표는 **절대 병합·비교하지 않습니다.**
--     이 표들은 duel_public_leaderboard(원화)와 물리적으로 다른 표이고, 화면도 탭이나
--     선택으로 완전히 분리해서 보여줍니다 — 같은 화면에 두 트랙의 순위를 나란히 놓고
--     "누가 더 잘했는지" 비교하는 UI 는 만들지 않습니다(환율 없이는 그 비교 자체가
--     의미가 없습니다 — §0-1).
-- -----------------------------------------------------------------------------
create table if not exists public.duel_public_leaderboard_usd (
    id             bigserial primary key,
    published_date date not null,
    window_type    text not null check (window_type in ('M1', 'M3', 'M6')),
    bracket_key    text not null check (length(btrim(bracket_key)) > 0),
    rank           integer not null check (rank > 0),
    nickname       text not null check (length(btrim(nickname)) > 0),
    twr_pct        numeric(20, 6),
    created_at     timestamptz not null default now(),

    -- §8-1 과 같은 이유로 처음부터 nickname 을 유니크 키에 둡니다(동점자 다수 발생을
    -- 이미 알고 있으므로, rank 를 키에 넣는 실수를 USD 트랙에서는 반복하지 않습니다).
    constraint duel_public_leaderboard_usd_participant_unique
        unique (published_date, window_type, bracket_key, nickname)
);

create index if not exists duel_public_leaderboard_usd_group_rank_idx
    on public.duel_public_leaderboard_usd (published_date, window_type, bracket_key, rank);

create index if not exists duel_public_leaderboard_usd_nickname_idx
    on public.duel_public_leaderboard_usd (nickname);

comment on table public.duel_public_leaderboard_usd is
    '결투다! USD 트랙 발행 전용 공개 순위표(§5-11). duel_public_leaderboard(원화)와 물리적으로 완전히 분리 — 절대 병합·비교하지 않습니다(5-11-9). user_id/account_id 를 담지 않습니다. 배치(service_role)만 쓰고, 로그인 사용자 전체가 읽습니다.';


create table if not exists public.duel_public_holdings_usd (
    id             bigserial primary key,
    published_date date not null,
    window_type    text not null check (window_type in ('M1', 'M3', 'M6')),
    nickname       text not null check (length(btrim(nickname)) > 0),
    ticker         text not null check (length(ticker) between 1 and 20),
    stock_name     text,
    quantity       numeric(20, 6) check (quantity is null or quantity >= 0),
    buy_amount     numeric(20, 6) check (buy_amount is null or buy_amount >= 0),
    created_at     timestamptz not null default now(),
    constraint duel_public_holdings_usd_unique
        unique (published_date, nickname, ticker)
);

create index if not exists duel_public_holdings_usd_nickname_idx
    on public.duel_public_holdings_usd (nickname);

comment on table public.duel_public_holdings_usd is
    '결투다! USD 트랙 발행 전용 공개 보유종목 상세(§5-11). user_id/account_id 를 담지 않습니다. 동의하지 않은 항목은 NULL 이며 화면은 "비공개"로 표시합니다.';


-- =============================================================================
-- 14. 🔐 USD 트랙 RLS + 권한 — §9 와 정확히 같은 원칙을 _usd 표에 적용
-- =============================================================================

-- 14-0. 소유자 판정 함수 — duel_account_is_mine() 의 USD 버전(표 이름이 본문에 박혀
--       있어 재사용이 불가능한 유일한 함수입니다. §9-0 참고)
create or replace function public.duel_account_is_mine_usd(target_account_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
          from public.duel_accounts_usd a
         where a.id = target_account_id
           and a.user_id = auth.uid()
    );
$$;

revoke all on function public.duel_account_is_mine_usd(uuid) from public;
grant execute on function public.duel_account_is_mine_usd(uuid) to authenticated, service_role;


alter table public.duel_accounts_usd            enable row level security;
alter table public.duel_positions_usd           enable row level security;
alter table public.duel_orders_usd              enable row level security;
alter table public.duel_cash_ledger_usd         enable row level security;
alter table public.duel_daily_snapshots_usd     enable row level security;
alter table public.duel_holding_snapshots_usd   enable row level security;
alter table public.duel_public_consent_usd      enable row level security;
alter table public.duel_public_leaderboard_usd  enable row level security;
alter table public.duel_public_holdings_usd     enable row level security;
alter table public.duel_bracket_assignments_usd enable row level security;

-- 14-1. duel_accounts_usd (§9-1 미러)
drop policy if exists duel_accounts_usd_select_own on public.duel_accounts_usd;
create policy duel_accounts_usd_select_own on public.duel_accounts_usd
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists duel_accounts_usd_insert_own on public.duel_accounts_usd;
create policy duel_accounts_usd_insert_own on public.duel_accounts_usd
    for insert to authenticated
    with check (auth.uid() = user_id);

-- 14-2. duel_positions_usd (§9-2 미러) — 읽기 전용
drop policy if exists duel_positions_usd_select_own on public.duel_positions_usd;
create policy duel_positions_usd_select_own on public.duel_positions_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

-- 14-3. duel_orders_usd (§9-3 미러)
drop policy if exists duel_orders_usd_select_own on public.duel_orders_usd;
create policy duel_orders_usd_select_own on public.duel_orders_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

drop policy if exists duel_orders_usd_insert_own on public.duel_orders_usd;
create policy duel_orders_usd_insert_own on public.duel_orders_usd
    for insert to authenticated
    with check (public.duel_account_is_mine_usd(account_id));

drop policy if exists duel_orders_usd_update_own on public.duel_orders_usd;
create policy duel_orders_usd_update_own on public.duel_orders_usd
    for update to authenticated
    using (public.duel_account_is_mine_usd(account_id))
    with check (public.duel_account_is_mine_usd(account_id));

-- 14-4. duel_cash_ledger_usd (§9-4 미러) — 읽기 전용
drop policy if exists duel_cash_ledger_usd_select_own on public.duel_cash_ledger_usd;
create policy duel_cash_ledger_usd_select_own on public.duel_cash_ledger_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

-- 14-5. 스냅샷 2표 (§9-5 미러) — 읽기 전용
drop policy if exists duel_snapshots_usd_select_own on public.duel_daily_snapshots_usd;
create policy duel_snapshots_usd_select_own on public.duel_daily_snapshots_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

drop policy if exists duel_holding_snapshots_usd_select_own on public.duel_holding_snapshots_usd;
create policy duel_holding_snapshots_usd_select_own on public.duel_holding_snapshots_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

-- 14-6. duel_public_consent_usd (§9-7 미러)
drop policy if exists duel_consent_usd_select_own on public.duel_public_consent_usd;
create policy duel_consent_usd_select_own on public.duel_public_consent_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

drop policy if exists duel_consent_usd_insert_own on public.duel_public_consent_usd;
create policy duel_consent_usd_insert_own on public.duel_public_consent_usd
    for insert to authenticated
    with check (public.duel_account_is_mine_usd(account_id));

drop policy if exists duel_consent_usd_update_own on public.duel_public_consent_usd;
create policy duel_consent_usd_update_own on public.duel_public_consent_usd
    for update to authenticated
    using (public.duel_account_is_mine_usd(account_id))
    with check (public.duel_account_is_mine_usd(account_id));

-- 14-7. duel_bracket_assignments_usd (§9-7-1 미러) — 조회만
drop policy if exists duel_bracket_assignments_usd_select_own on public.duel_bracket_assignments_usd;
create policy duel_bracket_assignments_usd_select_own on public.duel_bracket_assignments_usd
    for select to authenticated
    using (public.duel_account_is_mine_usd(account_id));

-- 14-8. 발행표 2개 (§9-8 미러) — 로그인 사용자 전체에게 select 만
drop policy if exists duel_public_leaderboard_usd_select_all on public.duel_public_leaderboard_usd;
create policy duel_public_leaderboard_usd_select_all on public.duel_public_leaderboard_usd
    for select to authenticated
    using (true);

drop policy if exists duel_public_holdings_usd_select_all on public.duel_public_holdings_usd;
create policy duel_public_holdings_usd_select_all on public.duel_public_holdings_usd
    for select to authenticated
    using (true);


-- -----------------------------------------------------------------------------
-- 14-9. 권한(GRANT) 정리 (§9-9 미러)
-- -----------------------------------------------------------------------------
revoke all on public.duel_accounts_usd            from anon;
revoke all on public.duel_positions_usd           from anon;
revoke all on public.duel_orders_usd              from anon;
revoke all on public.duel_cash_ledger_usd         from anon;
revoke all on public.duel_daily_snapshots_usd     from anon;
revoke all on public.duel_holding_snapshots_usd   from anon;
revoke all on public.duel_public_consent_usd      from anon;
revoke all on public.duel_public_leaderboard_usd  from anon;
revoke all on public.duel_public_holdings_usd     from anon;
revoke all on public.duel_bracket_assignments_usd from anon;

grant select, insert         on public.duel_accounts_usd            to authenticated;
grant select                 on public.duel_positions_usd           to authenticated;
grant select, insert, update on public.duel_orders_usd              to authenticated;
grant select                 on public.duel_cash_ledger_usd         to authenticated;
grant select                 on public.duel_daily_snapshots_usd     to authenticated;
grant select                 on public.duel_holding_snapshots_usd   to authenticated;
grant select, insert, update on public.duel_public_consent_usd      to authenticated;
grant select                 on public.duel_public_leaderboard_usd  to authenticated;
grant select                 on public.duel_public_holdings_usd     to authenticated;
grant select                 on public.duel_bracket_assignments_usd to authenticated;

-- bigserial 표의 시퀀스 권한(§9-9 의 "잊으면 insert 가 통째로 실패" 경고와 같은 이유)
revoke all on sequence public.duel_cash_ledger_usd_id_seq        from anon, authenticated;
revoke all on sequence public.duel_public_leaderboard_usd_id_seq from anon, authenticated;
revoke all on sequence public.duel_public_holdings_usd_id_seq    from anon, authenticated;

grant usage, select on sequence public.duel_cash_ledger_usd_id_seq        to service_role;
grant usage, select on sequence public.duel_public_leaderboard_usd_id_seq to service_role;
grant usage, select on sequence public.duel_public_holdings_usd_id_seq    to service_role;

grant select, insert, update on public.duel_accounts_usd          to service_role;
grant select, insert, update on public.duel_positions_usd         to service_role;
grant select, insert, update on public.duel_orders_usd            to service_role;
grant select, insert, update on public.duel_daily_snapshots_usd   to service_role;
grant select, insert, update on public.duel_holding_snapshots_usd to service_role;
grant select, insert, update on public.duel_public_consent_usd    to service_role;

-- 체급 배정은 배치에게도 insert 와 select 만(§9-9 의 duel_bracket_assignments 와 같은 이유
-- — 시즌 고정을 권한으로 강제).
revoke update, delete on public.duel_bracket_assignments_usd from service_role;
grant  select, insert on public.duel_bracket_assignments_usd to service_role;

-- 현금 원장은 배치에게도 insert 와 select 만(append-only 를 권한으로도 강제).
revoke update, delete on public.duel_cash_ledger_usd from service_role;
grant  select, insert on public.duel_cash_ledger_usd to service_role;

-- 포지션·주문·스냅샷·동의의 delete 도 거둡니다(§9-9 와 같은 이유 — 이 모듈에 "지워서
-- 되돌리는" 경로는 없습니다).
revoke delete on public.duel_accounts_usd          from service_role;
revoke delete on public.duel_positions_usd         from service_role;
revoke delete on public.duel_orders_usd            from service_role;
revoke delete on public.duel_daily_snapshots_usd   from service_role;
revoke delete on public.duel_holding_snapshots_usd from service_role;
revoke delete on public.duel_public_consent_usd    from service_role;

-- 발행표 2개만 예외로 delete 를 줍니다(§9-9 와 같은 이유 — 전량 재작성·철회 시 영구 삭제).
grant select, insert, update, delete on public.duel_public_leaderboard_usd to service_role;
grant select, insert, update, delete on public.duel_public_holdings_usd    to service_role;


-- -----------------------------------------------------------------------------
-- 14-10. 🔐 USD 옵트인 RPC — `public.duel_opt_in_usd()` (§9-10 미러)
-- -----------------------------------------------------------------------------
--  §9-10 과 같은 이유·같은 안전성 근거입니다(인자 없음, 대상은 auth.uid() 뿐, 금액은
--  상수 함수, 멱등). 닉네임은 여기서 만들지 않습니다 — 닉네임은 5단계 공개 동의 시점에
--  생성됩니다(5-5 확정 순서 그대로, USD 트랙도 동일).
-- -----------------------------------------------------------------------------
create or replace function public.duel_seed_amount_usd()
returns numeric
language sql
immutable
as $$
    select 7500::numeric   -- ⚠️ utils/duel_rules.py::SEED_AMOUNT_USD 와 반드시 같아야 합니다
$$;

revoke all on function public.duel_seed_amount_usd() from public;
grant execute on function public.duel_seed_amount_usd() to authenticated, service_role;

comment on function public.duel_seed_amount_usd() is
    '결투 USD 트랙 시드머니(달러)의 SQL 쪽 단일 출처. 앱 상수 utils/duel_rules.py::SEED_AMOUNT_USD 와 같아야 하며, tests/test_duel_db.py 가 두 값의 일치를 자동으로 검사합니다.';


drop function if exists public.duel_opt_in_usd();

create function public.duel_opt_in_usd()
returns setof public.duel_accounts_usd
language plpgsql
security definer
set search_path = public
as $$
declare
    caller    uuid    := auth.uid();
    seed      numeric := public.duel_seed_amount_usd();
    today_kst date    := (now() at time zone 'Asia/Seoul')::date;
begin
    if caller is null then
        raise exception
            'duel_opt_in_usd: 로그인한 사용자만 결투 USD 트랙에 참여할 수 있습니다(요청에 로그인 세션이 없습니다).'
            using errcode = '28000';
    end if;

    insert into public.duel_accounts_usd
        (user_id, window_type, seed_amount, currency, anchor_date, status)
    select caller, w.window_type, seed, 'USD', today_kst, 'active'
      from unnest(array['M1', 'M3', 'M6']) as w(window_type)
    on conflict (user_id, window_type) do nothing;

    insert into public.duel_cash_ledger_usd
        (account_id, event_type, amount, event_date, memo)
    select a.id, 'seed', seed, a.anchor_date, '결투 USD 트랙 계좌 개설 시드머니'
      from public.duel_accounts_usd a
     where a.user_id = caller
    on conflict (account_id) where event_type = 'seed' do nothing;

    return query
        select a.*
          from public.duel_accounts_usd a
         where a.user_id = caller
         order by array_position(array['M1', 'M3', 'M6'], a.window_type);
end;
$$;

revoke all on function public.duel_opt_in_usd() from public;
grant execute on function public.duel_opt_in_usd() to authenticated;

comment on function public.duel_opt_in_usd() is
    '결투 USD 트랙 옵트인(계좌 3개 + 시드 원장 3행)을 사용자 본인 세션으로 처리하는 security definer RPC(§9-10 미러). 인자가 없고 대상은 auth.uid() 뿐이라 남을 대신해 부를 수 없으며, 금액은 duel_seed_amount_usd() 상수입니다. 닉네임은 여기서 만들지 않습니다(5단계 동의 시점에 생성, duel_nicknames 는 원화 트랙과 공유).';


-- =============================================================================
-- 14-11. 🔴 리밸런싱 매도 정산 RPC — `duel.settled_sell` 을 켤 수 있는 **유일한 자리**
--        (2026-08-21 추가 · service_role 전용 · 원화 원본은 §9-11)
-- =============================================================================
--  ── 왜 표 update 가 아니라 RPC 인가 (이 파일에서 RPC 를 쓰는 두 번째 자리) ─────────
--  §13(USD 표) · §2-1(공유 트리거 함수) 의 `duel_positions_buy_only()` 트리거는 수량 감소를 막고, 리밸런싱 매도 정산만은
--  **같은 트랜잭션에서** `set local duel.settled_sell = 'on'` 이 먼저 실행됐을 때 통과시킵니다.
--  그런데 야간 배치는 Supabase 를 **PostgREST(REST)** 로 부릅니다 — REST 요청 하나가 곧
--  트랜잭션 하나이고, 클라이언트가 임의의 세션 변수를 앞세워 보낼 문법이 없습니다.
--  (PostgREST 가 트랜잭션에 심어 주는 값은 role · request.jwt.claims · request.headers 처럼
--   정해진 것뿐이고, `db-pre-request` 는 서버 전역 설정이라 "모든 요청에 항상 켜짐"이 됩니다 —
--   그건 정확히 이 트리거가 막으려던 상태입니다.)
--  그래서 **"세션 변수 켜기 + 수량 줄이기"를 한 번의 호출 안에서 원자적으로** 하는 좁은
--  함수를 둡니다. 플래그는 이 함수 안에서만 켜졌다가 끝나기 전에 꺼집니다.
--
--  ── 이 함수를 좁게 유지하는 장치 넷 (트리거를 우회하는 유일한 통로이므로) ──────────
--    · **수량만** 바꿉니다. `avg_cost` 는 손대지 않습니다 — "매도는 잔여 주식의 매입단가를
--      바꾸지 않는다"(`utils/duel_rules.py::apply_sell_fill_to_position()`)를 DB 에서도
--      그대로 강제하고, 정산 경로로 원가를 다시 쓰는 길을 아예 없앱니다.
--    · **줄이는 방향만** 허용합니다. 새 수량이 현재 수량 이상인 행이 하나라도 있으면 전체를
--      거절합니다 — 이 통로로 수량을 늘릴 수 있으면 트리거 전체가 장식이 됩니다.
--    · **행을 만들지 않습니다.** 없는 (계좌, 종목)이 들어오면 거절합니다(보유하지 않은
--      종목이 팔렸다는 뜻이라, 조용히 0건 처리하면 그 사실이 사라집니다 — §0-1).
--    · execute 는 **service_role 에게만**. 사용자 세션(anon/authenticated)은 이 함수를
--      부를 수 없습니다(§9-9 의 revoke 관례와 같은 이중 방어).
--
--  ⚠️ 한 번에 여러 행을 받습니다(jsonb 배열). 배치가 계좌마다 부르면 그게 §0-3-2 가 금지한
--     모양이 됩니다 — 호출부(`utils/duel_db_usd.py::settle_sell_positions_usd()`)는 그날 매도 정산
--     전체를 한 번(또는 CHUNK_SIZE 단위)에 보냅니다.
-- =============================================================================
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
-- 15. USD 트랙 설치 후 자가 점검 (§11 확장)
-- =============================================================================
--  ① 표 10개 + 재구조화된 닉네임 표 전부 RLS 켜져 있는지
--      select relname, relrowsecurity as rls_enabled
--        from pg_class
--       where relname like 'duel\_%usd' and relkind = 'r'
--       order by relname;
--
--  ② 발행표 2개(USD)에 식별자가 새어 들어가지 않았는지 — 항상 0행이어야 정상.
--      select table_name, column_name
--        from information_schema.columns
--       where table_schema = 'public'
--         and table_name in ('duel_public_leaderboard_usd', 'duel_public_holdings_usd')
--         and column_name in ('user_id', 'account_id', 'email');
--
--  ③ 닉네임 표가 더 이상 account_id 를 갖지 않고 (user_id, window_type) 기본키인지
--      select column_name from information_schema.columns
--       where table_schema='public' and table_name='duel_nicknames';
--      -- account_id 가 나오면 마이그레이션이 실패한 것입니다.
--
--  ④ 시드 금액이 앱 상수와 같은지 (7500 이어야 정상)
--      select public.duel_seed_amount_usd();
--
--  ⑤ 옵트인 RPC(USD)가 인자 0개 · security definer 인지
--      select proname, prosecdef, pronargs
--        from pg_proc
--       where pronamespace = 'public'::regnamespace
--         and proname in ('duel_opt_in_usd', 'duel_seed_amount_usd', 'duel_account_is_mine_usd');
-- =============================================================================
