-- =============================================================================
-- 결투다! 체결 원장 멱등성 마이그레이션 (2026-08-29, 재감사 H-4)
-- =============================================================================
-- 이 파일은 "이미 살아 있는" Supabase 테이블에 변경을 적용하는 마이그레이션입니다.
-- sql/duel_schema.sql 은 "새로 설치한다면 이런 모양이어야 한다"는 최신 기준 문서이고,
-- 이 파일은 **현재 운영 중인 테이블**을 실제로 고치는 실행 스크립트입니다.
--
-- 실행 방법: Supabase 대시보드 → SQL Editor → 이 파일 내용을 전부 붙여넣고 Run.
-- 여러 번 실행해도 안전합니다(`if not exists`).
--
-- ⚠️ 실행 전 Supabase 대시보드에서 백업(스냅샷)이 최근 것인지 한 번 확인하는 것을
--    권장합니다 — 이 프로젝트의 다른 스키마 변경 때와 같은 관례입니다.
--
-- ⚠️ 이 인덱스를 만들기 전에 이미 중복 원장 행이 쌓여 있으면 인덱스 생성이 실패합니다.
--    아래 2) 의 확인 질의를 먼저 돌려 0행인지 보고 실행하세요.
-- =============================================================================
--
-- 배치가 체결 원장(record_buy_ledger_entries)을 기록한 뒤 주문 상태 갱신
-- (record_order_fills)이 실패하면, 재실행 시 같은 주문의 원장 행이 다시 insert돼
-- 사용자 잔고가 중복 계상될 수 있습니다. (account_id, ticker) 부분 유니크 인덱스인
-- duel_cash_ledger_seed_unique 와 같은 방식으로, 주문 하나당 buy/sell 원장 행이
-- 정확히 하나만 존재하도록 막습니다.


-- -----------------------------------------------------------------------------
-- 1) 원화 트랙 — duel_cash_ledger
-- -----------------------------------------------------------------------------
create unique index if not exists duel_cash_ledger_order_event_unique
    on public.duel_cash_ledger (order_id, event_type)
    where order_id is not null;


-- -----------------------------------------------------------------------------
-- 1-USD) 달러 트랙 — duel_cash_ledger_usd (원화와 같은 규칙)
-- -----------------------------------------------------------------------------
create unique index if not exists duel_cash_ledger_usd_order_event_unique
    on public.duel_cash_ledger_usd (order_id, event_type)
    where order_id is not null;


-- -----------------------------------------------------------------------------
-- 2) 실행 전 확인 질의 — 이미 중복이 있으면 위 인덱스 생성이 실패합니다.
--    (0행이어야 정상입니다. 0행이 아니면 오너에게 알리고, 어느 주문이 두 번
--     기록됐는지 확인한 뒤에 정리해야 합니다 — 조용히 지우지 마세요.)
-- -----------------------------------------------------------------------------
-- select order_id, event_type, count(*)
--   from public.duel_cash_ledger
--  where order_id is not null
--  group by order_id, event_type
-- having count(*) > 1;
--
-- select order_id, event_type, count(*)
--   from public.duel_cash_ledger_usd
--  where order_id is not null
--  group by order_id, event_type
-- having count(*) > 1;
