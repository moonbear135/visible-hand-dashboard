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
--    4. 좌측 메뉴 → Table Editor 에서 public.portfolio_daily_snapshots 테이블과
--       "RLS enabled" 표시를 눈으로 확인
--    5. 맨 아래 §7 자가 점검 쿼리를 실행해 결과를 눈으로 확인
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
--  ④ 배치를 한 번 돌린 뒤(GitHub Actions 수동 실행), 행이 들어왔는지
--      select market, snapshot_date, total_value, total_cost, holdings_count,
--             priced_count, unpriced_count, benchmark_symbol, benchmark_value
--        from public.portfolio_daily_snapshots
--       order by snapshot_date desc, market
--       limit 20;
--
--  ⑤ 로그인 상태의 **앱에서** 다른 사람 행이 안 보이는지(대시보드 SQL Editor 는 postgres
--     권한이라 RLS 를 우회하므로, 이 확인만은 반드시 앱에서 해야 합니다).
-- =============================================================================
