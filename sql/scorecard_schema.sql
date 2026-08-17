-- =============================================================================
--  📊 "내 성적표" (3번째 모듈) — Supabase 스키마 + Row Level Security 설정 스크립트
--  파일: sql/scorecard_schema.sql   (SCORECARD_WORK_ORDER.md §6-1)
-- =============================================================================
--
--  ▶ 이건 앱이 실행하는 코드가 아닙니다. **오너가 Supabase 대시보드에서 1회 수동 실행**하는
--    설정 스크립트입니다.
--
--  실행 방법
--    1. https://supabase.com 에서 프로젝트 생성 (무료 티어로 충분)
--    2. 좌측 메뉴 → SQL Editor → New query
--    3. 이 파일 전체를 붙여넣고 Run
--    4. 좌측 메뉴 → Table Editor 에서 public.profiles / public.holdings / public.ocr_usage_daily
--       세 테이블과 각 테이블의 "RLS enabled" 표시를 눈으로 확인
--       (ocr_usage_daily 는 2026-08-17 에 추가된 표입니다 — 이 파일 맨 아래 §8 참고.
--        이미 §1~§7 을 실행해 둔 프로젝트라면 §8 블록만 따로 Run 해도 됩니다.)
--    5. 좌측 메뉴 → Authentication → Providers → Email 활성화 확인
--       (이메일 인증 메일 발송 여부는 오너 취향대로. 끄면 가입 즉시 로그인됩니다.)
--
--  ⚠️ 이 스크립트는 **여러 번 실행해도 안전하도록**(idempotent) 작성했습니다.
--     기존 데이터를 지우는 DROP TABLE 은 일부러 넣지 않았습니다.
--
--  ⚠️ 크레덴셜 주의
--     - 앱(Streamlit)에는 **anon key만** 넣습니다. `service_role` 키는 RLS를 통째로
--       우회하므로 사용자 대면 프론트엔드에 절대 넣지 마세요.
--     - anon key는 설계상 브라우저에 노출되는 게 정상인 키입니다(KRX 인증키와 다름).
--       **실제 방어선은 이 파일의 RLS 정책**입니다. 그래서 정책 없이 테이블만 만들면
--       "누구나 남의 보유종목을 읽는" 상태가 됩니다 — 아래 정책 블록을 절대 빼지 마세요.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 0. 확장 기능 (gen_random_uuid). Supabase 프로젝트에는 보통 이미 켜져 있습니다.
-- -----------------------------------------------------------------------------
create extension if not exists pgcrypto;


-- -----------------------------------------------------------------------------
-- 1. profiles — auth.users 확장 프로필
-- -----------------------------------------------------------------------------
--  로그인/비밀번호 자체는 Supabase Auth(auth.users)가 관리합니다. 우리는 비밀번호를
--  저장하지도, 볼 수도 없습니다(그게 Auth 서비스를 쓰는 이유입니다).
--
--  v1은 **개인정보 최소 수집** 원칙으로 이메일만 둡니다.
--  마인드맵에 있던 성별·전화번호 뒷자리(아이디/비밀번호 찾기용)는 v1 범위 밖이라
--  컬럼 자체를 만들지 않았습니다. 나중에 실제로 쓰기로 확정되면 그때
--  `alter table public.profiles add column ...` 로 추가하세요(안 쓰는 개인정보 컬럼을
--  미리 만들어두지 않는 편이 안전합니다).
-- -----------------------------------------------------------------------------
create table if not exists public.profiles (
    id           uuid primary key references auth.users (id) on delete cascade,
    email        text,
    display_name text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

comment on table public.profiles is
    '내 성적표 사용자 확장 프로필. 비밀번호는 여기 없고 Supabase Auth(auth.users)가 관리합니다.';


-- -----------------------------------------------------------------------------
-- 2. holdings — 보유 종목 (사용자 수동 입력)
-- -----------------------------------------------------------------------------
--  * quantity / avg_purchase_price 는 numeric(20,6) — 부동소수점 오차 없이 저장하기
--    위해 double precision 대신 numeric 을 씁니다(가중평균 재계산 결과가
--    93,076.923076... 처럼 무한소수가 될 수 있음).
--  * currency 는 market 에서 자동으로 결정되지만, **원화/달러가 섞이는 사고를 DB
--    레벨에서도 막기 위해** 별도 컬럼 + CHECK 제약으로 이중 방어합니다.
--    (환율 변환은 앱에서도 DB에서도 하지 않습니다 — 각 통화 그대로 표시)
--  * (user_id, market, ticker) 유니크 — 같은 종목을 여러 증권사에서 사서 여러 번
--    입력하면 행이 늘어나는 게 아니라 **수량 가중평균으로 한 행이 갱신**됩니다.
-- -----------------------------------------------------------------------------
create table if not exists public.holdings (
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid not null references auth.users (id) on delete cascade,
    market             text not null check (market in ('KR', 'US')),
    ticker             text not null check (length(ticker) between 1 and 20),
    stock_name         text,
    quantity           numeric(20, 6) not null check (quantity > 0),
    avg_purchase_price numeric(20, 6) not null check (avg_purchase_price >= 0),
    currency           text not null check (currency in ('KRW', 'USD')),
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint holdings_market_currency_match check (
        (market = 'KR' and currency = 'KRW')
        or (market = 'US' and currency = 'USD')
    ),
    constraint holdings_user_ticker_unique unique (user_id, market, ticker)
);

create index if not exists holdings_user_id_idx on public.holdings (user_id);

comment on table public.holdings is
    '내 성적표 보유 종목(수동 입력). 같은 종목 재입력 시 수량 가중평균으로 avg_purchase_price 갱신.';
comment on column public.holdings.currency is
    'market 에서 파생되지만 CHECK 제약으로 원/달러 혼용을 DB에서도 차단합니다. 환율 변환 없음.';


-- -----------------------------------------------------------------------------
-- 3. updated_at 자동 갱신 트리거
-- -----------------------------------------------------------------------------
create or replace function public.scorecard_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
    before update on public.profiles
    for each row execute function public.scorecard_set_updated_at();

drop trigger if exists holdings_set_updated_at on public.holdings;
create trigger holdings_set_updated_at
    before update on public.holdings
    for each row execute function public.scorecard_set_updated_at();


-- -----------------------------------------------------------------------------
-- 4. 회원가입 시 profiles 행 자동 생성
-- -----------------------------------------------------------------------------
--  auth 스키마에 트리거를 걸어야 해서 security definer 가 필요합니다
--  (Supabase SQL Editor 는 postgres 권한으로 실행되므로 그대로 통과합니다).
--  search_path 를 명시해 함수 하이재킹을 막습니다.
-- -----------------------------------------------------------------------------
create or replace function public.handle_new_scorecard_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created_scorecard on auth.users;
create trigger on_auth_user_created_scorecard
    after insert on auth.users
    for each row execute function public.handle_new_scorecard_user();


-- =============================================================================
-- 5. 🔐 Row Level Security — 이 블록이 이 파일의 핵심입니다
-- =============================================================================
--  "사용자는 자기 자신의 행만 읽고 쓸 수 있다"를 애플리케이션 코드가 아니라
--  DB 정책으로 강제합니다. 앱 코드에 버그가 생겨 `.eq("user_id", ...)` 필터를
--  빠뜨려도, DB가 남의 행을 애초에 돌려주지 않습니다.
--
--  auth.uid() = 지금 요청에 실려온 JWT 의 사용자 UUID.
--  로그인하지 않은 요청(anon key만 들고 온 요청)에서는 NULL 이므로 어떤 행도
--  매칭되지 않습니다 → 비로그인 상태에서는 아무것도 안 보입니다.
-- =============================================================================

alter table public.profiles enable row level security;
alter table public.holdings enable row level security;

-- profiles ---------------------------------------------------------------
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select to authenticated
    using (auth.uid() = id);

drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own on public.profiles
    for insert to authenticated
    with check (auth.uid() = id);

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
    for update to authenticated
    using (auth.uid() = id)
    with check (auth.uid() = id);

drop policy if exists profiles_delete_own on public.profiles;
create policy profiles_delete_own on public.profiles
    for delete to authenticated
    using (auth.uid() = id);

-- holdings ---------------------------------------------------------------
drop policy if exists holdings_select_own on public.holdings;
create policy holdings_select_own on public.holdings
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists holdings_insert_own on public.holdings;
create policy holdings_insert_own on public.holdings
    for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists holdings_update_own on public.holdings;
create policy holdings_update_own on public.holdings
    for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists holdings_delete_own on public.holdings;
create policy holdings_delete_own on public.holdings
    for delete to authenticated
    using (auth.uid() = user_id);


-- -----------------------------------------------------------------------------
-- 6. 권한(GRANT) 정리 — 방어 심화
-- -----------------------------------------------------------------------------
--  RLS만으로도 비로그인(anon) 요청은 막히지만, anon 롤의 테이블 권한 자체를 거둬서
--  한 겹 더 막습니다. (정책을 실수로 지웠을 때의 최악 상황 대비)
-- -----------------------------------------------------------------------------
revoke all on public.profiles from anon;
revoke all on public.holdings from anon;

grant select, insert, update, delete on public.profiles  to authenticated;
grant select, insert, update, delete on public.holdings  to authenticated;


-- =============================================================================
-- 7. 설치 후 자가 점검 (선택) — 아래 쿼리를 실행해 결과를 눈으로 확인하세요
-- =============================================================================
--  ① RLS가 켜져 있는지 (rowsecurity 두 줄 다 true 여야 정상)
--      select relname, relrowsecurity as rls_enabled
--        from pg_class
--       where relname in ('profiles', 'holdings');
--
--  ② 정책이 8개(테이블당 4개) 인지
--      select tablename, policyname, cmd
--        from pg_policies
--       where schemaname = 'public' and tablename in ('profiles', 'holdings')
--       order by tablename, cmd;
--
--  ③ 로그아웃(anon) 상태에서 holdings 를 조회하면 0행이 나와야 정상입니다.
--     (Supabase 대시보드의 SQL Editor 는 postgres 권한이라 RLS를 우회하므로
--      이 확인은 반드시 **앱에서 로그아웃 상태로** 해보세요.)
-- =============================================================================


-- =============================================================================
-- 8. ocr_usage_daily — 📷 스크린샷 OCR 업로드 하루 사용량 (2026-08-17 추가)
-- =============================================================================
--  ▶ 이 섹션은 나중에 추가된 것이라 **이 파일을 다시 통째로 Run 해도 안전합니다**
--    (위 §0~§7 과 마찬가지로 idempotent). 이미 운영 중인 프로젝트라면 이 §8 블록만
--    복사해서 SQL Editor 에 붙여 넣고 Run 해도 됩니다.
--
--  왜 필요한가
--    "📷 스크린샷으로 채우기"(성적표 v2)는 **유료 외부 AI API** 를 호출합니다. 한 사람이
--    반복 업로드하면 비용이 그대로 늘어나므로, 오너 결정(2026-08-17)에 따라 **로그인
--    사용자 1명당 하루 N회** 로 제한합니다.
--
--    ⚠️ 한도 값(N)은 **여기에 적지 않습니다.** 앱 코드의 상수 하나
--       (`utils/scorecard_db.py::DAILY_OCR_UPLOAD_LIMIT`)가 단일 출처입니다. DB 에도
--       숫자를 박아두면 둘 중 하나만 바뀌는 날 조용히 어긋납니다(§0-3-10).
--       그래서 아래 CHECK 는 "0 이상"만 강제하고 상한은 앱이 판단합니다.
--
--  왜 카운터를 DB 에 두는가
--    브라우저·세션(메모리)에 두면 새로고침·다른 기기·서버 재배포로 초기화됩니다. 그러면
--    제한이 사실상 없는 것과 같습니다. 사용자별 영속 저장은 이 파일이 이미 쓰는 방식
--    (Supabase + RLS) 을 그대로 따릅니다 — 새 저장소를 만들지 않았습니다.
--
--  "하루"의 기준
--    `usage_date` 에는 앱이 **한국시간(KST) 기준 오늘 날짜**를 넣습니다
--    (`utils/scorecard_db.py::ocr_usage_today()`). DB 의 `now()`/`current_date` 는 UTC 라
--    쓰지 않습니다 — 한국 사용자에게는 자정이 아니라 오전 9시에 한도가 풀리는 것처럼
--    보입니다. 그래서 default 도 두지 않고 앱이 항상 명시적으로 넣습니다.
--
--  (user_id, usage_date) 유니크 = 사용자 × 날짜 1행. 지난 날짜 행은 지우지 않습니다
--  (사용자당 하루 1행이라 양이 미미하고, "언제 얼마나 썼는지" 기록이 비용 확인에 쓰입니다).
-- -----------------------------------------------------------------------------
create table if not exists public.ocr_usage_daily (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users (id) on delete cascade,
    usage_date date not null,
    used_count integer not null default 0 check (used_count >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ocr_usage_daily_user_date_unique unique (user_id, usage_date)
);

create index if not exists ocr_usage_daily_user_id_idx on public.ocr_usage_daily (user_id);

comment on table public.ocr_usage_daily is
    '스크린샷 OCR 업로드(유료 API) 하루 사용 횟수. 사용자 × 날짜 1행. 하루 한도 값은 앱 상수(DAILY_OCR_UPLOAD_LIMIT)가 단일 출처.';
comment on column public.ocr_usage_daily.usage_date is
    '앱이 넣는 한국시간(KST) 기준 날짜. DB 의 current_date(UTC) 를 쓰지 않는 이유는 파일 §8 주석 참고.';

-- updated_at 자동 갱신 — §3 에서 만든 함수를 그대로 재사용합니다(중복 정의 없음).
drop trigger if exists ocr_usage_daily_set_updated_at on public.ocr_usage_daily;
create trigger ocr_usage_daily_set_updated_at
    before update on public.ocr_usage_daily
    for each row execute function public.scorecard_set_updated_at();


-- -----------------------------------------------------------------------------
-- 8-1. 🔐 카운터를 되돌리지 못하게 막는 트리거
-- -----------------------------------------------------------------------------
--  아래 RLS 는 "본인 행 update 허용"입니다. 증가시키려면 반드시 필요한 권한인데, 그걸
--  그대로 두면 사용자가 자기 행의 `used_count` 를 0 으로 되돌려 한도를 무한히 푸는 요청을
--  보낼 수 있습니다(anon key 는 공개된 키라서 앱 화면을 거치지 않는 직접 호출이 가능합니다).
--  그래서 **줄이는 방향의 수정과 소유자·날짜 변경을 DB 에서 거절**합니다.
--  (§5 의 RLS 와 같은 사고방식 — 앱 코드가 아니라 DB 가 마지막 방어선입니다.)
--
--  🔴 delete 는 아래 §8-2 에서 정책도 권한도 주지 않습니다. 행을 지워 리셋하는 길을
--     열어두면 이 트리거가 무의미해집니다.
-- -----------------------------------------------------------------------------
create or replace function public.ocr_usage_daily_guard()
returns trigger
language plpgsql
as $$
begin
    if new.user_id <> old.user_id or new.usage_date <> old.usage_date then
        raise exception 'ocr_usage_daily: user_id / usage_date 는 수정할 수 없습니다';
    end if;
    if new.used_count < old.used_count then
        raise exception 'ocr_usage_daily: 사용 횟수는 줄일 수 없습니다';
    end if;
    return new;
end;
$$;

drop trigger if exists ocr_usage_daily_no_reset on public.ocr_usage_daily;
create trigger ocr_usage_daily_no_reset
    before update on public.ocr_usage_daily
    for each row execute function public.ocr_usage_daily_guard();


-- -----------------------------------------------------------------------------
-- 8-2. RLS + 권한 — 본인 행만, 그리고 delete 는 아무에게도 열지 않습니다
-- -----------------------------------------------------------------------------
alter table public.ocr_usage_daily enable row level security;

drop policy if exists ocr_usage_daily_select_own on public.ocr_usage_daily;
create policy ocr_usage_daily_select_own on public.ocr_usage_daily
    for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists ocr_usage_daily_insert_own on public.ocr_usage_daily;
create policy ocr_usage_daily_insert_own on public.ocr_usage_daily
    for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists ocr_usage_daily_update_own on public.ocr_usage_daily;
create policy ocr_usage_daily_update_own on public.ocr_usage_daily
    for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- ⚠️ delete 정책은 **일부러 없습니다**(위 8-1 참고). 계정을 지우면 on delete cascade 로
--    함께 사라지므로 정리 경로는 이미 있습니다.

revoke all on public.ocr_usage_daily from anon;
grant select, insert, update on public.ocr_usage_daily to authenticated;


-- -----------------------------------------------------------------------------
-- 8-3. 설치 후 자가 점검 (선택)
-- -----------------------------------------------------------------------------
--  ① 표와 RLS 가 생겼는지 (rowsecurity = true 여야 정상)
--      select relname, relrowsecurity as rls_enabled
--        from pg_class where relname = 'ocr_usage_daily';
--
--  ② 정책이 3개(select/insert/update)이고 **delete 가 없는지**
--      select policyname, cmd from pg_policies
--       where schemaname = 'public' and tablename = 'ocr_usage_daily' order by cmd;
--
--  ③ 오늘 누가 몇 번 썼는지 (비용 확인용)
--      select usage_date, count(*) as users, sum(used_count) as total_uploads
--        from public.ocr_usage_daily group by usage_date order by usage_date desc limit 14;
-- =============================================================================
