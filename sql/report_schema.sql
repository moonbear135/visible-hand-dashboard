-- =============================================================================
--  📈 "리포트" (5번째 모듈) — Supabase 스키마 + Row Level Security 설정 스크립트
--  파일: sql/report_schema.sql   (REPORT_WORK_ORDER.md §2 / §6-1)
-- =============================================================================
--
--  ▶ 이건 앱이 실행하는 코드가 아닙니다. **오너가 Supabase 대시보드에서 1회 수동 실행**하는
--    설정 스크립트입니다. (`sql/scorecard_schema.sql` 과 같은 방식)
--
--  실행 방법
--    1. https://supabase.com → 이미 "내 성적표"용으로 만들어 둔 **같은 프로젝트**를 엽니다
--       (새 프로젝트를 만들지 마세요 — 이 테이블은 기존 `holdings` / `auth.users` 를 참조합니다)
--    2. 좌측 메뉴 → SQL Editor → New query
--    3. 이 파일 전체를 붙여넣고 Run
--    4. 좌측 메뉴 → Table Editor 에서 아래 **두 테이블**과 각각의 "RLS enabled" 표시를
--       눈으로 확인
--         · public.portfolio_daily_snapshots   (시장별 합계 1행 — §1)
--         · public.portfolio_holding_snapshots (종목별 상세 — §8, 2026-08-13 추가)
--    5. 맨 아래 §7 · §9 자가 점검 쿼리를 실행해 결과를 눈으로 확인
--       (특히 §9 의 ⑨ '합계 = 종목별 합' 대조 쿼리는 **항상 0행**이어야 정상입니다)
--
--  ⚠️ 이 스크립트는 **여러 번 실행해도 안전하도록**(idempotent) 작성했습니다.
--     기존 데이터를 지우는 DROP TABLE 은 일부러 넣지 않았습니다.
--
-- -----------------------------------------------------------------------------
--  🔴 이 테이블만 다른 점 — 쓰는 주체가 "사용자"가 아니라 "매일 도는 배치"입니다
-- -----------------------------------------------------------------------------
--  `holdings` 는 사용자가 화면에서 직접 넣고 고치는 표라 anon key + RLS 로 본인 행만
--  읽고 쓰게 했습니다. 반면 이 스냅샷 표는:
--
--    · **쓰기**: GitHub Actions 안에서만 도는 배치 스크립트
--      (`utils/report_db.py` + `.github/workflows/scrape_report_snapshots.yml`)가
--      **가입한 모든 사용자**의 그날 평가금액을 계산해 넣습니다. "로그인한 그 사용자"가
--      아니므로 anon key + RLS 로는 애초에 불가능하고, `service_role` 키가 필요합니다.
--      그래서 그 키는 **GitHub Actions Secrets 에만** 등록하고(Streamlit Cloud Secrets 에는
--      절대 넣지 않습니다), 그 키를 읽는 코드는 저장소 전체에서 `utils/report_db.py` 의
--      배치 전용 함수 하나뿐입니다.
--    · **읽기**: 사용자가 리포트 화면을 열 때, 기존과 똑같이 anon key + 로그인 세션으로
--      **본인 행만** 읽습니다(아래 RLS 정책).
--
--  ⇒ 그래서 아래 RLS 정책은 **select 하나뿐**입니다. 사용자에게 insert/update/delete 를
--    열어 줄 이유가 없습니다(사용자가 자기 과거 수익률 기록을 손댈 수 있으면 리포트의
--    의미 자체가 없어집니다). `service_role` 은 RLS 를 우회하므로 정책 없이도 씁니다.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 0. 확장 기능 (gen_random_uuid). Supabase 프로젝트에는 보통 이미 켜져 있습니다.
-- -----------------------------------------------------------------------------
create extension if not exists pgcrypto;


-- -----------------------------------------------------------------------------
-- 1. portfolio_daily_snapshots — 하루 1행(사용자 × 시장)만 저장
-- -----------------------------------------------------------------------------
--  왜 기간별(주간/월간/분기…) 테이블을 따로 만들지 않는가 (REPORT_WORK_ORDER.md §2)
--    사용자 1명 × 시장(KR/US) × 거래일 1일 = 1행. 연 250거래일 × 2시장 ≈ 사용자당
--    연 500행. 10년을 써도 수천 행이라 용량 문제가 없고, 주간·월간·분기·반기·연간
--    리포트는 전부 **이 표에 대한 날짜 범위 쿼리**로 계산합니다. 미리 계산해 저장하면
--    보유 종목이 바뀔 때마다 과거 집계가 서로 어긋나기 시작합니다.
--
--  왜 market 으로 행을 나누는가
--    "내 성적표"가 지키는 원칙 — **원화와 달러를 절대 한 숫자로 합치지 않는다**(환율 변환
--    없음) — 을 그대로 잇습니다. 벤치마크도 시장마다 다릅니다(한국=코스피, 미국=S&P500·나스닥).
--
--  숫자 컬럼이 numeric 인 이유
--    `holdings` 와 같습니다. 평가금액 합계는 소수점이 길어질 수 있고(가중평균 단가 ×
--    수량), double precision 은 오차가 누적됩니다.
--
--  ⚠️ priced_count / unpriced_count 를 둔 이유 (ENGINEERING_SPEC §0-1)
--    보유 종목 중 일부는 현재가를 모를 수 있습니다(수집 실패, 유니버스 밖 등).
--    그런 종목을 0원으로 치고 합계에 넣으면 "지어낸 숫자"가 됩니다. 그래서
--    **총평가금액·총매입원가는 그날 현재가를 실제로 아는 종목만으로** 계산하고,
--    몇 개를 담고 몇 개를 못 담았는지를 이 두 컬럼에 남깁니다. 화면은 이 값을 보고
--    "이 날 스냅샷은 5종목 중 3종목만 담겨 있습니다" 라고 정직하게 알려줍니다.
--    한 종목도 값을 모르면 배치는 **행 자체를 만들지 않습니다**(아래 CHECK 로도 강제).
-- -----------------------------------------------------------------------------
create table if not exists public.portfolio_daily_snapshots (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references auth.users (id) on delete cascade,
    market           text not null check (market in ('KR', 'US')),
    snapshot_date    date not null,
    total_value      numeric(20, 6) not null check (total_value >= 0),
    total_cost       numeric(20, 6) not null check (total_cost >= 0),
    currency         text not null check (currency in ('KRW', 'USD')),
    holdings_count   integer not null check (holdings_count >= 0),
    priced_count     integer not null check (priced_count > 0),
    unpriced_count   integer not null check (unpriced_count >= 0),
    benchmark_symbol text,
    benchmark_value  numeric(20, 6),

    -- 🕐 이 행의 가격이 **몇 시 몇 분에 수집된 값인가** (2026-08-13 추가, 오너 요청)
    --    snapshot_date 는 "어느 거래일"만 말해 줄 뿐, 한국장(오후)과 미국장(한국시간 새벽)의
    --    수집 시각이 다르다는 사실이 리포트에 전혀 드러나지 않았습니다. 그래서 배치가 그날
    --    실제로 읽은 가격 파일의 타임스탬프를 **한국 시간(KST) 기준 'YYYY-MM-DD HH:MM'** 로
    --    그대로 남깁니다.
    --      · KR = data/kospi200_pegy_latest.json 의 metadata.last_updated_at (이미 KST)
    --      · US = data/us_stocks_latest.json  의 metadata.last_updated_at_kst
    --             (수집기가 이미 KST 로 변환해 둔 값을 재사용 — 앱이 직접 시차 계산을 하지 않습니다)
    --    ⚠️ timestamptz 가 아니라 text 인 이유: 원본 메타데이터가 **분 단위까지만** 기록합니다.
    --       timestamptz 로 넣으면 없는 초(:00)와 없는 정밀도가 생기고, 표시할 때 서버 타임존에
    --       따라 다른 시각으로 렌더링될 여지도 생깁니다. 수집기가 적어 둔 문자열을 그대로 보관해
    --       화면에도 그대로 보여 줍니다(§0-1 — 없는 정밀도를 지어내지 않기, TASK_HISTORY #111 과 같은 판단).
    --    ⚠️ NULL 허용: 이 컬럼을 만들기 전에 저장된 과거 행과, 수집기 메타데이터에 시각이
    --       없었던 날은 NULL 입니다. 화면은 그 행을 "시각 정보 없음"으로 정직하게 표시하고
    --       오늘 시각이나 추정값으로 메우지 않습니다.
    price_as_of_kst  text,

    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),

    -- 같은 사용자·같은 시장·같은 날짜는 딱 한 행. 배치를 두 번 돌려도 늘어나지 않고
    -- 갱신(upsert)됩니다.
    constraint snapshots_user_market_date_unique unique (user_id, market, snapshot_date),

    -- holdings 테이블과 동일한 이중 방어 — 원/달러 혼용을 DB 레벨에서도 차단합니다.
    constraint snapshots_market_currency_match check (
        (market = 'KR' and currency = 'KRW')
        or (market = 'US' and currency = 'USD')
    ),

    -- 담긴 종목 수 + 못 담은 종목 수 = 그날 보유 종목 수. 어긋나면 계산 버그입니다.
    constraint snapshots_counts_match check (priced_count + unpriced_count = holdings_count),

    -- 벤치마크는 없을 수 있습니다(그 날 수집 실패 등) → NULL 허용. 다만 0 이나 음수는
    -- 지수값으로 있을 수 없으므로 막습니다(§0-1 — 실패를 0으로 메우지 않기).
    constraint snapshots_benchmark_positive check (
        benchmark_value is null or benchmark_value > 0
    )
);

-- -----------------------------------------------------------------------------
-- 1-1. 🔧 이미 만들어 둔 테이블에 컬럼 추가 (마이그레이션 — 2026-08-13)
-- -----------------------------------------------------------------------------
--  ⚠️ 위 `create table if not exists` 는 **테이블이 이미 있으면 아무 일도 하지 않습니다.**
--     그래서 2026-08-12 에 이미 이 스크립트를 실행해 둔 프로젝트에는 `price_as_of_kst`
--     컬럼이 생기지 않습니다. 아래 한 줄이 그 경우를 위한 것입니다(새 프로젝트에서 실행하면
--     이미 있는 컬럼이라 조용히 넘어갑니다 — 여러 번 실행해도 안전).
--
--  기존 행은 NULL 로 남습니다. 그 시각을 지금 와서 계산해 채우지 않습니다 — 그날 배치가
--  몇 시 몇 분 가격을 봤는지는 아무 데도 기록돼 있지 않고, 추정해 넣으면 그게 지어낸
--  값입니다(§0-1). 화면은 그 행을 "시각 정보 없음"으로 표시합니다.
-- -----------------------------------------------------------------------------
alter table public.portfolio_daily_snapshots
    add column if not exists price_as_of_kst text;

create index if not exists snapshots_user_id_idx
    on public.portfolio_daily_snapshots (user_id);
create index if not exists snapshots_date_idx
    on public.portfolio_daily_snapshots (snapshot_date);
-- 리포트 화면이 실제로 던지는 질의는 항상 "이 사용자 / 이 시장 / 이 날짜 구간" 입니다.
create index if not exists snapshots_user_market_date_idx
    on public.portfolio_daily_snapshots (user_id, market, snapshot_date);

comment on table public.portfolio_daily_snapshots is
    '리포트 모듈: 사용자별·시장별 하루 1행 평가금액 스냅샷. 쓰기는 GitHub Actions 배치(service_role)만, 사용자는 읽기 전용.';
comment on column public.portfolio_daily_snapshots.total_value is
    '그날 종가 기준 평가금액 합계. **현재가를 실제로 아는 종목만** 합산합니다(§0-1).';
comment on column public.portfolio_daily_snapshots.total_cost is
    'total_value 와 같은 종목 집합의 매입원가 합계(수량 × 가중평균 매입가). 두 값의 종목 집합이 항상 일치해야 수익률이 의미를 가집니다.';
comment on column public.portfolio_daily_snapshots.priced_count is
    '그날 현재가를 알아서 합계에 담긴 종목 수. 0이면 행을 만들지 않습니다.';
comment on column public.portfolio_daily_snapshots.unpriced_count is
    '보유는 하고 있으나 그날 현재가를 몰라 합계에서 빠진 종목 수. 화면에 정직하게 표시합니다.';
comment on column public.portfolio_daily_snapshots.benchmark_symbol is
    '한국=KOSPI(코스피 지수 종가). 미국=SP500_PROXY_SPY / NASDAQ_PROXY_ONEQ (지수 자체가 아니라 추종 ETF 종가라는 사실을 이름에 그대로 남깁니다 — §0-1).';
comment on column public.portfolio_daily_snapshots.benchmark_value is
    '그날 벤치마크 종가. 수집 실패한 날은 NULL 이며, 전날 값을 복사해 채우지 않습니다(보간 금지).';
comment on column public.portfolio_daily_snapshots.price_as_of_kst is
    '이 행의 가격이 수집된 시각(한국시간 KST, ''YYYY-MM-DD HH:MM'' 문자열). KR=kospi200_pegy_latest.json last_updated_at / US=us_stocks_latest.json last_updated_at_kst 를 그대로 저장합니다. 원본이 분 단위까지만 기록하므로 초는 없습니다(지어내지 않음). 이 컬럼 신설 이전 행과 메타데이터에 시각이 없던 날은 NULL.';


-- -----------------------------------------------------------------------------
-- 2. updated_at 자동 갱신 트리거
-- -----------------------------------------------------------------------------
--  `sql/scorecard_schema.sql` 에도 같은 역할의 함수가 있지만, 두 스크립트를 서로 다른
--  순서로 실행해도 안전하도록 **이 파일 전용 함수**를 따로 둡니다(이름이 달라 충돌 없음).
-- -----------------------------------------------------------------------------
create or replace function public.report_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists snapshots_set_updated_at on public.portfolio_daily_snapshots;
create trigger snapshots_set_updated_at
    before update on public.portfolio_daily_snapshots
    for each row execute function public.report_set_updated_at();


-- =============================================================================
-- 3. 🔐 Row Level Security — 이 블록이 이 파일의 핵심입니다
-- =============================================================================
--  사용자는 **자기 행만 읽을 수 있고, 쓰기는 아예 못 합니다.**
--  auth.uid() = 지금 요청에 실려온 JWT 의 사용자 UUID. 로그인하지 않은 요청(anon key만
--  들고 온 요청)에서는 NULL 이라 어떤 행도 매칭되지 않습니다.
--
--  ⚠️ insert / update / delete 정책을 **일부러 만들지 않았습니다.** RLS 가 켜진 테이블에서
--     정책이 없는 동작은 전부 거부됩니다 → 로그인한 사용자도 자기 스냅샷을 고치거나 지울
--     수 없습니다. 과거 수익률 기록은 사람이 손대면 안 되는 값이기 때문입니다.
--     (배치는 `service_role` 키를 쓰고, 그 키는 RLS 자체를 우회합니다.)
-- =============================================================================
alter table public.portfolio_daily_snapshots enable row level security;

drop policy if exists snapshots_select_own on public.portfolio_daily_snapshots;
create policy snapshots_select_own on public.portfolio_daily_snapshots
    for select to authenticated
    using (auth.uid() = user_id);


-- -----------------------------------------------------------------------------
-- 4. 권한(GRANT) 정리 — 방어 심화
-- -----------------------------------------------------------------------------
--  RLS 만으로도 비로그인(anon) 요청은 막히지만, anon 롤의 테이블 권한 자체를 거둬서
--  한 겹 더 막습니다. 로그인 사용자에게도 **select 만** 줍니다.
-- -----------------------------------------------------------------------------
revoke all on public.portfolio_daily_snapshots from anon;
grant select on public.portfolio_daily_snapshots to authenticated;

-- 배치(service_role)는 Supabase 기본 설정으로도 권한이 있지만, 명시적으로 남겨 둡니다.
-- delete 는 주지 않습니다 — 이 배치가 하는 일은 "오늘 한 줄 추가/갱신"뿐이고,
-- 과거 기록을 지우는 코드는 저장소 어디에도 없습니다.
grant select, insert, update on public.portfolio_daily_snapshots to service_role;


-- =============================================================================
-- 5. ⚠️ 배치가 절대 하지 말아야 할 것 (코드 리뷰용 메모)
-- =============================================================================
--  · 배치는 `holdings` / `profiles` / `auth.users` 를 **읽기만** 합니다. 쓰기는 이
--    스냅샷 테이블 한 곳뿐입니다(`utils/report_db.py` 에 같은 내용의 주석이 있습니다).
--  · 과거 날짜를 소급해서 채우지 않습니다. 기능을 켠 날부터 쌓이고, 그 전 기간 리포트는
--    화면에서 "데이터 부족"으로 정직하게 표시됩니다(REPORT_WORK_ORDER.md §3).
--  · 벤치마크 값이 없는 날은 NULL 로 두고 전날 값을 복사하지 않습니다.


-- =============================================================================
-- 6. (선택) 나중에 사용자가 계정을 지웠을 때
-- =============================================================================
--  user_id 는 auth.users 를 on delete cascade 로 참조합니다 — 회원 탈퇴 시 이 사용자의
--  스냅샷도 함께 사라집니다(개인정보 최소 보관). 별도 정리 배치가 필요 없습니다.


-- =============================================================================
-- 7. 설치 후 자가 점검 — 아래 쿼리를 실행해 결과를 눈으로 확인하세요
-- =============================================================================
--  ① RLS 가 켜져 있는지 (true 여야 정상)
--      select relname, relrowsecurity as rls_enabled
--        from pg_class
--       where relname = 'portfolio_daily_snapshots';
--
--  ② 정책이 **select 1개뿐**인지 (insert/update/delete 가 있으면 잘못 실행된 것)
--      select tablename, policyname, cmd
--        from pg_policies
--       where schemaname = 'public' and tablename = 'portfolio_daily_snapshots';
--
--  ③ 컬럼·제약이 다 들어갔는지
--      select column_name, data_type, is_nullable
--        from information_schema.columns
--       where table_schema = 'public' and table_name = 'portfolio_daily_snapshots'
--       order by ordinal_position;
--
--  ③-1 (2026-08-13) 가격 수집 시각 컬럼이 실제로 붙었는지 — 이 한 줄이 안 나오면 위
--      §1-1 의 alter 문을 실행하지 않은 것입니다(그 상태에서도 배치는 죽지 않고, 시각만
--      비운 채 저장한 뒤 로그에 경고를 남깁니다).
--      select column_name, data_type, is_nullable
--        from information_schema.columns
--       where table_schema = 'public' and table_name = 'portfolio_daily_snapshots'
--         and column_name = 'price_as_of_kst';
--
--  ④ 배치를 한 번 돌린 뒤(GitHub Actions 수동 실행), 행이 들어왔는지
--      select market, snapshot_date, price_as_of_kst, total_value, total_cost,
--             holdings_count, priced_count, unpriced_count,
--             benchmark_symbol, benchmark_value
--        from public.portfolio_daily_snapshots
--       order by snapshot_date desc, market
--       limit 20;
--     (price_as_of_kst 는 KR 이 그날 오후, US 가 거래일 **다음 날 새벽~오전** 으로 찍히는 게
--      정상입니다 — 미국장 마감이 한국시간 새벽이기 때문입니다.)
--
--  ⑤ 로그인 상태의 **앱에서** 다른 사람 행이 안 보이는지(대시보드 SQL Editor 는 postgres
--     권한이라 RLS 를 우회하므로, 이 확인만은 반드시 앱에서 해야 합니다).
-- =============================================================================


-- =============================================================================
-- 8. 🆕 portfolio_holding_snapshots — **종목별** 일일 스냅샷 (2026-08-13 오너 결정)
-- =============================================================================
--  ▶ 이 블록은 **추가**입니다. 위 §1~§7 의 portfolio_daily_snapshots(시장별 합계 1행)은
--    한 글자도 바뀌지 않았고, 지금 쌓여 있는 데이터도 그대로 씁니다. 파일 전체를 다시
--    실행하면 기존 테이블은 건드리지 않고(`create table if not exists`) 이 테이블만 새로
--    생깁니다.
--
--  ── 왜 만드나 (오너 결정, 2026-08-13) ────────────────────────────────────────
--  처음에는 "일간·주간·월간·분기·반기·연간을 다 저장하면 계정당 데이터가 너무 쌓인다"는
--  우려로 **시장별 합계 1줄만** 저장했습니다(§1 의 설명). 그 판단은 기간 리포트에 대해서는
--  지금도 유효합니다(기간별 테이블은 여전히 만들지 않습니다 — 날짜 범위 쿼리로 계산).
--
--  이번에 늘리는 건 **기간 축이 아니라 종목 축**입니다. 오너 원문:
--    "내가 제일 중시하는 데이터의 품질관리를 하려면 아무튼 최대한 깨끗하게 잘 정리된
--     상태의 많은 데이터가 필요해 … 나중에 유료로 할 정도로 자료가 많아지는데 들쑥날쑥하면
--     세상의 모두가 힘들어져"
--  합계 1줄만으로는 "이 달 수익이 어느 종목에서 났는지"를 **영원히** 알 수 없습니다.
--  과거 종목별 값은 소급 계산이 불가능하므로(그날 가격을 아무 데도 보관하지 않음), 지금부터
--  저장하지 않으면 그 데이터는 영구히 존재하지 않습니다.
--
--  ── 저장량 (오너가 인지하고 감수하기로 한 부분) ─────────────────────────────
--    사용자 1명 × 보유 10종목 × 거래일 250일 ≈ 연 2,500행 (합계 테이블의 500행 + α).
--    한 행이 대략 150~200바이트 → 사용자당 연 0.5MB 안팎. 무료 티어 500MB 기준으로
--    수백 사용자 · 수년 단위까지 여유가 있습니다. 그래도 무한하지는 않으므로, 용량이
--    한계에 가까워지면 **오래된 종목별 행만** 지우는 보존 정책을 그때 도입하면 됩니다
--    (합계 테이블은 그대로 두면 되므로 기간 리포트는 영향받지 않습니다 — 이렇게 두 표를
--     나눠 둔 덕에 나중에 선택지가 생깁니다).
--
--  ── 🔴 이 표의 존재 이유이자 가장 중요한 원칙 : "들쑥날쑥" 금지 ──────────────
--  합계 표와 이 표는 **같은 배치 실행에서, 같은 메모리 위의 평가 결과 하나**로부터
--  함께 만들어집니다(`utils/report_db.build_snapshot_rows_with_holdings()`).
--    · 종목별 행을 먼저 만들고 → **그 행들을 그대로 더해서** 합계 행을 만듭니다.
--    · 합계를 따로 계산하는 경로가 코드에 없습니다. 두 값이 서로 다른 계산을 타지 않으므로
--      원천적으로 어긋날 수 없습니다.
--    · 반올림도 같은 자리(소수점 6자리)에서 **한 번만** 합니다 — 종목별 행에 저장되는
--      바로 그 숫자를, DB 와 같은 십진수 방식으로 더해서 합계를 만듭니다(먼저 더하고 나중에
--      반올림하지 않고, 파이썬 float 로 대충 더하지도 않습니다).
--  ⇒ 아래 §9 의 ⑨ 대조 쿼리는 항상 0행이어야 정상입니다. 화면에서도 같은 대조를 하고,
--    어긋나면 숨기지 않고 표시합니다.
--  ⚠️ 다만 **완전한 비트 단위 일치를 약속하지는 않습니다**(지어내지 않기). 배치가 쓰는
--     파이썬의 배정밀도 실수는 유효자릿수가 15~17자리라, 합계가 대략 10^10 을 넘으면서
--     동시에 소수점 이하 금액까지 있는 경우(수백억원 + 가중평균 매입단가처럼 무한소수인
--     단가) 마지막 자리가 어긋날 수 있습니다 — 실측 최대 오차 0.00005원. 그래서 대조는
--     **0.01(1원의 100분의 1)** 허용오차로 봅니다. 화면 표기 단위(원=정수, 달러=소수 2자리)
--     보다 훨씬 작아 사람이 볼 수 있는 불일치는 전부 잡힙니다.
--
--  ── 왜 종목명(stock_name)을 여기에 또 저장하나 ──────────────────────────────
--  `holdings` 에도 있지만 그건 **지금** 이름입니다. 사용자가 종목을 팔면 그 행은 사라지고,
--  회사명이 바뀌기도 합니다. 리포트는 "그날 무엇을 들고 있었나"를 보여주는 기록이라
--  **그날 기준 이름**을 함께 남깁니다(과거 표에서 종목명이 빈칸이 되지 않게).
--
--  ── 왜 price_as_of_kst 를 종목마다 반복해서 넣나 ─────────────────────────────
--  같은 시장·같은 날이면 모든 종목이 같은 값입니다(시장별로 하루 1값). 그럼에도 넣는 이유는
--  이 표만 조회해도 "이 가격은 몇 시 몇 분 것인가"가 **자기완결적으로** 읽히게 하기
--  위해서입니다. 조인 없이 CSV 로 뽑아 봐도 시각이 함께 나오는 것이 오너가 말한 "깨끗하게
--  잘 정리된 데이터"에 맞다고 판단했습니다. 비용은 행당 16바이트 남짓입니다.
--
--  ── 이익(profit)·수익률을 컬럼으로 두지 않은 이유 ───────────────────────────
--  `market_value - cost` 로 언제든 정확히 나옵니다. 저장하면 계산 경로가 하나 더 생기고,
--  그게 바로 "들쑥날쑥"의 씨앗입니다. 저장하는 것은 **관측값**(수량·매입가·현재가)과 그
--  곱셈 결과까지이고, 뺄셈·나눗셈은 화면에서 그때그때 합니다.
-- -----------------------------------------------------------------------------
create table if not exists public.portfolio_holding_snapshots (
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid not null references auth.users (id) on delete cascade,
    market             text not null check (market in ('KR', 'US')),
    ticker             text not null check (length(ticker) between 1 and 20),
    snapshot_date      date not null,

    -- 그날 기준 표시용 이름(holdings.stock_name 과 같은 성격). 없을 수 있어 NULL 허용.
    stock_name         text,

    -- 관측값 — holdings 와 완전히 같은 타입·제약(numeric(20,6))으로 맞춥니다.
    quantity           numeric(20, 6) not null check (quantity > 0),
    avg_purchase_price numeric(20, 6) not null check (avg_purchase_price >= 0),
    cost               numeric(20, 6) not null check (cost >= 0),

    -- ⚠️ 그날 현재가를 몰랐던 종목은 여기 두 컬럼이 **NULL** 입니다.
    --    0 으로 채우지 않습니다(0원이라는 거짓말이 되고, 다음 날 가격이 들어오는 순간
    --    "하루 만에 폭등"처럼 보이는 가짜 수익률이 생깁니다 — ENGINEERING_SPEC §0-1).
    current_price      numeric(20, 6) check (current_price is null or current_price > 0),
    market_value       numeric(20, 6) check (market_value is null or market_value >= 0),

    currency           text not null check (currency in ('KRW', 'USD')),

    -- 합계 표의 priced_count / unpriced_count 와 같은 개념을 **행 단위**로 남긴 것.
    -- 화면은 이 값이 false 인 행을 빈칸이 아니라 "가격 모름"으로 표시합니다.
    priced             boolean not null,

    -- 이 행의 가격이 수집된 시각(한국시간 'YYYY-MM-DD HH:MM'). 합계 표의 같은 이름 컬럼과
    -- 같은 값이며, 같은 배치가 같은 문자열을 양쪽에 넣습니다. 모르면 NULL(추정 금지).
    price_as_of_kst    text,

    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),

    -- 사용자 × 시장 × 종목 × 거래일 = 딱 한 행. 배치를 두 번 돌려도 늘지 않고 갱신됩니다.
    constraint holding_snapshots_user_market_ticker_date_unique
        unique (user_id, market, ticker, snapshot_date),

    -- holdings / portfolio_daily_snapshots 와 동일한 이중 방어 — 원·달러 혼용 차단.
    constraint holding_snapshots_market_currency_match check (
        (market = 'KR' and currency = 'KRW')
        or (market = 'US' and currency = 'USD')
    ),

    -- 🔴 "가격 모름"의 표현을 한 가지로 못 박습니다. priced=true 인데 값이 비어 있거나,
    --    priced=false 인데 값이 들어 있는 행은 DB 레벨에서 아예 들어오지 못합니다.
    --    (이 제약이 없으면 "값이 0인지 NULL인지 false인지"가 행마다 달라지면서, 나중에
    --     집계할 때 사람마다 다른 숫자가 나옵니다 — 오너가 말한 "들쑥날쑥"의 전형입니다.)
    constraint holding_snapshots_priced_match check (
        (priced and current_price is not null and market_value is not null)
        or (not priced and current_price is null and market_value is null)
    )
);

-- 주 조회 패턴은 화면과 완전히 같습니다: "이 사용자 / 이 시장 / 이 날짜 구간".
create index if not exists holding_snapshots_user_market_date_idx
    on public.portfolio_holding_snapshots (user_id, market, snapshot_date);
-- ⚠️ 인덱스를 더 만들지 않았습니다. 위 unique 제약이 (user_id, market, ticker, snapshot_date)
--    인덱스를 이미 만들어 주고, 이 표는 **매일 쓰기가 일어나는 표**라 인덱스 하나하나가
--    행 수만큼의 쓰기 비용·저장 공간으로 돌아옵니다(합계 표보다 행이 10배 이상 많습니다).
--    실제로 던지는 질의가 늘면 그때 근거를 남기고 추가하세요.

drop trigger if exists holding_snapshots_set_updated_at on public.portfolio_holding_snapshots;
create trigger holding_snapshots_set_updated_at
    before update on public.portfolio_holding_snapshots
    for each row execute function public.report_set_updated_at();

comment on table public.portfolio_holding_snapshots is
    '리포트 모듈: 사용자별·시장별·종목별 하루 1행 스냅샷(2026-08-13 추가). portfolio_daily_snapshots 의 합계는 이 표의 같은 날 행들을 그대로 더한 값이며, 두 표는 같은 배치 실행의 같은 계산 결과로 함께 저장됩니다. 쓰기는 GitHub Actions 배치(service_role)만, 사용자는 읽기 전용.';
comment on column public.portfolio_holding_snapshots.stock_name is
    '그날 기준 표시용 종목명. holdings 에서 그대로 복사합니다(나중에 종목을 팔거나 회사명이 바뀌어도 과거 표가 빈칸이 되지 않게).';
comment on column public.portfolio_holding_snapshots.cost is
    '수량 × 평균매입가. 같은 날 같은 시장의 priced=true 행들의 합이 portfolio_daily_snapshots.total_cost 와 정확히 같아야 합니다.';
comment on column public.portfolio_holding_snapshots.market_value is
    '수량 × 그날 현재가. 현재가를 몰랐으면 NULL(0 으로 채우지 않음). 같은 날 같은 시장의 priced=true 행들의 합이 portfolio_daily_snapshots.total_value 와 정확히 같아야 합니다.';
comment on column public.portfolio_holding_snapshots.priced is
    '그날 이 종목의 현재가를 알았는지. false 면 current_price/market_value 가 NULL 이고, 화면은 빈칸이 아니라 ''가격 모름''으로 표시합니다. 같은 날 같은 시장의 true 개수 = portfolio_daily_snapshots.priced_count.';
comment on column public.portfolio_holding_snapshots.price_as_of_kst is
    '이 행의 가격이 수집된 시각(한국시간 ''YYYY-MM-DD HH:MM'' 문자열). 같은 시장·같은 날이면 모든 종목이 같은 값이지만, 이 표만 조회해도 자기완결적으로 읽히도록 행마다 넣습니다. 모르면 NULL(추정하지 않음).';


-- -----------------------------------------------------------------------------
-- 8-1. 🔐 RLS — 합계 표(§3)와 **정확히 같은 원칙**
-- -----------------------------------------------------------------------------
--  select 정책 **하나뿐**입니다. insert/update/delete 정책은 일부러 만들지 않습니다 —
--  RLS 가 켜진 테이블에서 정책 없는 동작은 전부 거부되므로, 로그인한 사용자도 자기 과거
--  기록을 고치거나 지울 수 없습니다. 배치는 service_role 키를 쓰고 그 키는 RLS 를 우회합니다.
-- -----------------------------------------------------------------------------
alter table public.portfolio_holding_snapshots enable row level security;

drop policy if exists holding_snapshots_select_own on public.portfolio_holding_snapshots;
create policy holding_snapshots_select_own on public.portfolio_holding_snapshots
    for select to authenticated
    using (auth.uid() = user_id);

revoke all on public.portfolio_holding_snapshots from anon;
grant select on public.portfolio_holding_snapshots to authenticated;
-- delete 는 주지 않습니다(§4 와 같은 이유 — 과거 기록을 지우는 코드가 저장소에 없습니다).
grant select, insert, update on public.portfolio_holding_snapshots to service_role;


-- =============================================================================
-- 9. 설치 후 자가 점검 — 종목별 표 (위 §7 에 이어서)
-- =============================================================================
--  ⑥ 테이블·RLS 가 만들어졌는지 (rls_enabled = true 여야 정상)
--      select relname, relrowsecurity as rls_enabled
--        from pg_class
--       where relname = 'portfolio_holding_snapshots';
--
--  ⑦ 정책이 **select 1개뿐**인지
--      select tablename, policyname, cmd
--        from pg_policies
--       where schemaname = 'public' and tablename = 'portfolio_holding_snapshots';
--
--  ⑧ 배치를 한 번 돌린 뒤, 종목별 행이 들어왔는지
--      select snapshot_date, market, ticker, stock_name, quantity,
--             avg_purchase_price, cost, current_price, market_value, priced,
--             price_as_of_kst
--        from public.portfolio_holding_snapshots
--       order by snapshot_date desc, market, market_value desc nulls last
--       limit 30;
--
--  ⑨ 🔴 **가장 중요한 점검 — 합계와 종목별 합이 어긋나지 않는지.**
--     아래 쿼리는 **항상 0행**이어야 정상입니다. 한 행이라도 나오면 그날 두 표가 서로 다른
--     값을 말하고 있다는 뜻이므로, 그대로 두지 말고 배치 로그부터 확인하세요.
--     (그날 종목별 저장만 실패했다면 종목별 행이 아예 없어서 여기서도 잡힙니다.)
--
--      select d.user_id, d.market, d.snapshot_date,
--             d.total_value, h.sum_value,
--             d.total_cost,  h.sum_cost,
--             d.priced_count, h.priced_rows,
--             d.holdings_count, h.all_rows
--        from public.portfolio_daily_snapshots d
--        left join (
--              select user_id, market, snapshot_date,
--                     sum(market_value) filter (where priced) as sum_value,
--                     sum(cost)         filter (where priced) as sum_cost,
--                     count(*)          filter (where priced) as priced_rows,
--                     count(*)                                as all_rows
--                from public.portfolio_holding_snapshots
--               group by user_id, market, snapshot_date
--             ) h
--          on h.user_id = d.user_id and h.market = d.market
--         and h.snapshot_date = d.snapshot_date
--       where h.user_id is null                          -- 종목별 행이 통째로 없는 날
--          or abs(d.total_value - h.sum_value) > 0.01   -- 허용오차 이유는 위 §8 마지막 ⚠️ 참고
--          or abs(d.total_cost  - h.sum_cost)  > 0.01
--          or d.priced_count   is distinct from h.priced_rows
--          or d.holdings_count is distinct from h.all_rows;
--
--     ⚠️ 이 표를 만들기 **전에** 쌓인 날짜는 종목별 행이 없어서 위 쿼리에 나옵니다.
--        정상입니다 — 그날 종목별 값은 아무 데도 기록돼 있지 않아 **소급해서 만들지
--        않습니다**(§0-1). 위 쿼리로 실제 점검을 할 때는 이 표를 만든 날 이후만 보세요:
--          ... and d.snapshot_date >= '이 SQL 을 실행한 날짜'
