-- MIGRATION_2026-08-23_holding_details.sql
--
--  🔴 오너가 Supabase SQL Editor 에 **이 파일만 통째로 붙여넣어 한 번 실행**하면 되는
--     추가분입니다. 아래 내용은 sql/scorecard_public_schema.sql 끝에 덧붙여 둔 같은 이름의
--     절(2026-08-23 추가)과 **글자 그대로 같습니다** — 그쪽은 이력 기록용(원본 스크립트는
--     이미 실행됐으므로 손대지 않습니다)이고, 이 파일은 실행용 사본입니다.
--     🔴 한쪽만 고치지 마세요. 두 파일은 항상 같은 내용이어야 합니다.
--
--  ⚠️ 실행 전 확인: 이 스크립트는 표를 **만들지도 지우지도 않습니다.** alter/update 뿐이고,
--     sql/scorecard_public_schema.sql 의 §1~§3(DROP 9종 + CREATE 5종)이 이미 실행돼 있는
--     상태를 전제합니다.
--  ⚠️ 두 번 실행해도 안전합니다(add column if not exists · drop constraint if exists ·
--     백필 UPDATE 는 같은 값을 다시 쓰는 것). 다만 백필(A-2)은 "지금 final_confirmed 인
--     행"을 대상으로 하므로, 나중에 새로 동의한 사용자에게 이 파일을 다시 돌리지 마세요 —
--     그건 사용자가 화면에서 직접 체크해야 하는 항목입니다(§0-3-8 기본 비공개).

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
