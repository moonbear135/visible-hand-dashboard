-- 🙏 "여기서부터는 신앙입니다" AI 해설 캐시 테이블
-- Supabase 대시보드 → SQL Editor 에서 이 파일 전체를 한 번 붙여넣고 실행하세요.
--
-- 이 테이블은 로그인한 사람의 개인 데이터가 아니라, "종목코드 + 날짜"에 대해
-- AI가 만든 설명 문장 하나만 담습니다(같은 날 같은 종목은 여러 사람이 봐도 재생성 안 함).
-- 그래서 로그인 세션 없이도(anon key만으로도) 이 화면 서버 프로세스가 직접 읽고 쓸 수
-- 있도록 아래에서 RLS(행 단위 보안) 정책을 열어둡니다.
--
-- ⚠️ anon key는 브라우저로 나가지 않고 Render 서버 환경변수에만 있으므로(기존 로그인
--    기능과 동일한 신뢰 경계), 이 정책이 새로운 노출을 만들지는 않습니다. 다만 그 키가
--    유출되면 이 표에 임의의 텍스트를 써넣을 수 있다는 점은 알아두세요(다른 anon-key
--    write 기능들과 동일한 수준의 위험입니다).

create table if not exists public.indicator_ai_commentary (
    stock_code text not null,
    commentary_date date not null,
    commentary text not null,
    model text not null,
    generated_at timestamptz not null default now(),
    primary key (stock_code, commentary_date)
);

alter table public.indicator_ai_commentary enable row level security;

-- 누구나(로그인 여부 무관) 읽을 수 있음 — 화면에 그대로 노출되는 값이라 비공개일 이유가 없음.
drop policy if exists "indicator_ai_commentary_select_all" on public.indicator_ai_commentary;
create policy "indicator_ai_commentary_select_all"
    on public.indicator_ai_commentary for select
    using (true);

-- 서버(anon key)가 새 해설을 써넣을 수 있음.
drop policy if exists "indicator_ai_commentary_insert_all" on public.indicator_ai_commentary;
create policy "indicator_ai_commentary_insert_all"
    on public.indicator_ai_commentary for insert
    with check (true);

-- upsert(같은 종목+날짜 재저장)를 위해 update도 허용.
drop policy if exists "indicator_ai_commentary_update_all" on public.indicator_ai_commentary;
create policy "indicator_ai_commentary_update_all"
    on public.indicator_ai_commentary for update
    using (true)
    with check (true);
