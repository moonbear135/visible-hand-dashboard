# utils/duel_db_usd.py
"""
⚔️ "결투다!" USD 트랙 — Supabase 접근 계층 (2026-08-20, USD 트랙 3차 코딩)

`utils/duel_db.py`(원화 트랙)의 **통화 미러**입니다. 두 파일이 같은 계층 규약(A 절 =
사용자 세션 · B 절 = 배치 전용)을 따르고, `sql/duel_schema.sql` §13~14 의 `_usd` 표를
바라본다는 점만 다릅니다. 아래 두 절 머리말이 이 파일 전체를 지배하는 규칙입니다.

-------------------------------------------------------------------------------
🔁 "완전 분리, 그러나 순수 로직은 공유" — 이 파일이 실제로 새로 쓴 것과 재사용한 것
-------------------------------------------------------------------------------
스키마(§13-14)가 이미 세운 원칙을 코드에도 그대로 옮깁니다: **표 이름이 본문에 박혀
있는 함수만 복제**하고, `NEW`/`OLD` 로만 동작하는 트리거처럼 **표 이름을 몰라도 되는
순수 로직·순수 인프라는 재사용**합니다(5-11-1). 그래서 이 파일은:

  · `utils.duel_db` 에서 그대로 **import 해서 씁니다** (재구현하지 않습니다):
    - 공통 검증·변환 헬퍼(`_execute` · `_require_client` · `_iso_date` · `_now_kst` ·
      `_require_text` · `_require_positive_int` · `_require_offset` · `_require_amount` ·
      `_first_row` · `_is_duplicate_key_error` · `_assert_unique_keys` · `_filter_is_null` ·
      `_filter_not_null` · `_assert_no_identity_fields` · `_validate_fill_payload` ·
      `_validate_daily_snapshot` · `_validate_holding_snapshot`) — 이들은 표 이름을
      인자로 받거나 아예 몰라도 되는 순수 로직입니다. 두 번 구현하면 한쪽만 고쳐지는
      날 원화·달러의 검증 규칙이 갈라집니다(§0-3-10).
    - `group_rows_by_account` · `sum_cash_balance` · `cash_balances_by_account` —
      표를 모르는 순수 집계 함수.
    - `create_service_client` · `service_config_present` · `_read_service_env` —
      **같은 Supabase 프로젝트, 같은 service_role 키**를 씁니다(원화·달러는 같은
      DB 안의 다른 표일 뿐입니다). 두 번째 클라이언트 생성 경로를 만들지 않습니다.
    - `ensure_nickname` · `fetch_my_nickname` · `fetch_nicknames_for_accounts` —
      **닉네임은 처음부터 원화·달러가 공유하는 표입니다**(`duel_nicknames`,
      `(user_id, window_type)` 키 — 5-11-10 확정). USD 전용 함수를 만들면 그 자체가
      "닉네임이 계좌별로 다시 갈라진다"는 잘못된 모델을 코드에 새기는 것이라 만들지
      않습니다. `fetch_nicknames_for_accounts()` 는 계좌 행(딕셔너리)을 받으므로
      호출부는 이 파일의 `fetch_all_active_accounts_usd()` 결과를 그대로 넘기면 됩니다.
    - `fetch_real_principal_holdings` — "내 성적표"의 실제 보유종목은 통화별로 이미
      `currency` 컬럼을 갖고 있어 트랙과 무관한 사용자 단위 조회입니다(5-3). 체급
      산정 시 원화/달러 어느 금액을 쓸지 가르는 것은 `utils/duel_publish.py`(다음
      라운드)의 일이지, 조회 함수를 복제할 이유가 아닙니다.
    - `duel_rules.apply_buy_fill_to_position` · `compute_twr` 등 순수 계산 — 이 파일은
      여전히 "계산하지 않고 담아 보내기만" 합니다. (⚠️ 체결 거래일 확정은 여기서
      빠졌습니다 — 2026-08-21 아래 세 번째 예외 사례로 옮겼습니다.)

  · **새로 정의합니다**(표 이름 또는 통화별 규칙 상수가 함수 본문에 박혀 있는 것들):
    - §0 의 `_usd` 표 이름 상수 10개 + RPC 이름.
    - A 절: `opt_in_usd` · `save_order_usd` · `edit_order_usd` · `cancel_order_usd` ·
      조회 5종 · `save_consent_usd` · `fetch_my_consent_usd` · `revoke_consent_usd` ·
      순위표 읽기 3종.
    - B 절: 배치 전용 CRUD 전부(활성계좌·원장·포지션·스냅샷 일괄조회, 옵트인 백필,
      정기입금, 체결 기록, 발행표 쓰기/지우기 등).
    - 주문 접수 시간대 창은 `duel_rules.resolve_order_window_usd()`(16:00:01~21:00:00,
      2026-08-20 오너 최종 확정)를 씁니다 — `resolve_order_window()`(원화, 18:00:01~
      22:00:00)와 다른 함수입니다. 이 파일에 `resolve_order_window(...)` 를 실수로
      쓰면 원화 트랙 시간대로 판정하게 되므로, 이 사실이 아래 각 함수 docstring 에도
      반복해서 적혀 있습니다.
    - `_translate_order_guard_error_usd()` — 원화용 `_translate_order_guard_error()`
      는 오류 문구 **안에 "18:00~22:00"이 하드코딩**돼 있어 그대로 재사용하면 USD
      사용자에게 원화 시간대를 보여주는 사고가 납니다. 그래서 이 함수만 예외적으로
      새로 정의합니다(트리거 자체는 원화와 공유하지만, 사람이 읽는 번역 문구는
      트랙마다 다른 시간대를 담아야 하므로).
    - `duel_rules.resolve_fill_trading_day_usd()` — 이 트랙의 **세 번째** "공유 로직
      이지만 통화별 전제가 본문에 박혀 있어 신규 정의" 사례입니다(위 번역 함수,
      `duel_batch_usd.format_summary_lines_usd()` 에 이어). 이 함수만은 `duel_rules`
      쪽에 새로 만들었고 여기서는 부르기만 합니다 — 판정 자체가 순수 계산이라 이
      파일이 가질 이유는 없기 때문입니다. 원화용 `resolve_fill_trading_day()` 는
      "주문을 저장한 그날 자신을 무조건 후보에서 제외"하는데, 그건 **원화 접수 시간대
      (18:00:01~22:00:00 KST)가 그날 종가가 이미 확정된 뒤**라서 맞는 규칙입니다.
      USD 접수 시간대(16:00:01~21:00:00 KST = 03:00~08:00 ET)는 반대로 **그날 미국장이
      열리기도 전**이라 그날 마감가가 아직 존재하지 않으므로, 그날 자신을 후보에
      포함해야 맞습니다. 원화 함수를 그대로 쓰면 체결이 조용히 하루 늦어집니다
      (work order §5-16 — 오너가 직접 발견한 실제 버그).

-------------------------------------------------------------------------------
🔴 이 파일도 두 절로 나뉘고, 절대 섞이면 안 됩니다(`utils/duel_db.py` 머리말과 동일)
-------------------------------------------------------------------------------
    A. 사용자용 (anon key + 로그인 세션) — 표는 `duel_orders_usd` · `duel_public_consent_usd`
       **둘만** 쓰기 가능(스키마 §14).
    B. 배치용 (service_role, 야간 GitHub Actions 전용) — §0-3-2(집합 연산)를 그대로 지킵니다.

🧮 계산은 여기 없습니다. `utils/duel_rules.py` 를 호출만 합니다(원화 파일과 동일한 규약).
⚠️ 지어내지 않기(§0-1) — 실패를 조용히 삼키지 않고, 거래일·종가·체결 결과를 만들지
   않고 인자로만 받습니다. 이 규약은 `DuelDbError` 를 그대로 재사용하는 것으로
   자동으로 따라옵니다(원화·달러가 같은 예외 타입을 씁니다 — 호출부가 한 종류만
   잡으면 됩니다).
"""

from __future__ import annotations

from datetime import date, datetime

from utils import duel_rules
from utils import duel_db
from utils.duel_db import (
    DuelDbError,
    CHUNK_SIZE,
    CONSENT_ITEM_FLAGS,
    CONSENT_REAL_PRINCIPAL_FLAG,
    PUBLIC_LEADERBOARD_COLUMNS,
    PUBLIC_HOLDINGS_COLUMNS,
    FORBIDDEN_PUBLISH_FIELDS,
    FORBIDDEN_USER_WRITE_PARAMS,
    _execute,
    _require_client,
    _iso_date,
    _now_kst,
    _require_text,
    _require_positive_int,
    _require_offset,
    _require_amount,
    _first_row,
    _is_duplicate_key_error,
    _assert_unique_keys,
    _filter_is_null,
    _filter_not_null,
    _assert_no_identity_fields,
    _validate_fill_payload,
    _validate_daily_snapshot,
    _validate_holding_snapshot,
    group_rows_by_account,
    sum_cash_balance,
    cash_balances_by_account,
    create_service_client,
    service_config_present,
    ensure_nickname,
    fetch_my_nickname,
    fetch_nicknames_for_accounts,
    fetch_real_principal_holdings,
)
from utils.duel_rules import (
    ACCOUNT_WINDOW_TYPES,
    KST,
    MONTHLY_DEPOSIT_USD,
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_FILLED,
    ORDER_PARTIALLY_FILLED,
    ORDER_PENDING,
    SEED_AMOUNT_USD,
)

__all__ = [
    "DuelDbError",
    "opt_in_usd",
    "save_order_usd",
    "edit_order_usd",
    "cancel_order_usd",
    "fetch_my_accounts_usd",
    "fetch_my_positions_usd",
    "fetch_my_orders_usd",
    "fetch_my_cash_ledger_usd",
    "fetch_my_snapshots_usd",
    "fetch_my_holding_snapshots_usd",
    "save_consent_usd",
    "fetch_my_consent_usd",
    "revoke_consent_usd",
    "fetch_public_leaderboard_latest_date_usd",
    "fetch_public_leaderboard_usd",
    "fetch_public_holdings_for_nickname_usd",
    "fetch_all_active_accounts_usd",
    "fetch_cash_ledger_for_accounts_usd",
    "fetch_positions_for_accounts_usd",
    "fetch_daily_snapshots_for_accounts_usd",
    "create_duel_accounts_for_user_usd",
    "apply_monthly_deposits_usd",
    "fetch_pending_orders_for_fill_usd",
    "record_order_fill_usd",
    "record_order_fills_usd",
    "record_buy_ledger_entry_usd",
    "record_buy_ledger_entries_usd",
    "upsert_position_weighted_average_usd",
    "upsert_positions_usd",
    "expire_or_cancel_all_pending_for_date_usd",
    "write_daily_snapshots_usd",
    "fetch_publishable_consents_usd",
    "fetch_revoked_consent_accounts_usd",
    "fetch_bracket_assignments_usd",
    "insert_bracket_assignments_usd",
    "delete_published_rows_for_date_usd",
    "delete_published_rows_for_nicknames_usd",
    "leaderboard_has_any_rows_usd",
    "fetch_published_group_index_usd",
    "delete_published_group_usd",
    "write_public_leaderboard_usd",
    "write_public_holdings_usd",
]


# =============================================================================
# 0. 표 이름 — sql/duel_schema.sql §13 과 **문자 그대로** 같아야 합니다
# =============================================================================
ACCOUNTS_TABLE_USD = "duel_accounts_usd"
POSITIONS_TABLE_USD = "duel_positions_usd"
ORDERS_TABLE_USD = "duel_orders_usd"
LEDGER_TABLE_USD = "duel_cash_ledger_usd"
DAILY_SNAPSHOTS_TABLE_USD = "duel_daily_snapshots_usd"
HOLDING_SNAPSHOTS_TABLE_USD = "duel_holding_snapshots_usd"
CONSENT_TABLE_USD = "duel_public_consent_usd"
PUBLIC_LEADERBOARD_TABLE_USD = "duel_public_leaderboard_usd"
PUBLIC_HOLDINGS_TABLE_USD = "duel_public_holdings_usd"
BRACKET_ASSIGNMENTS_TABLE_USD = "duel_bracket_assignments_usd"

#: `duel_nicknames` 는 **일부러 여기 없습니다** — 원화·달러가 같은 표를 공유합니다
#: (위 머리말 참고). `utils.duel_db.NICKNAMES_TABLE` 을 그대로 씁니다.

#: 옵트인 RPC. `sql/duel_schema.sql` §14-10 의 함수 이름과 문자 그대로 같아야 합니다.
OPT_IN_RPC_USD = "duel_opt_in_usd"

#: 사용자가 스스로 취소했을 때 남기는 기본 사유. 원화와 같은 문장이 그대로 맞습니다
#: (시간대·통화를 언급하지 않는 일반 문장이라 새로 쓸 이유가 없습니다).
DEFAULT_CANCEL_REASON_USD = "사용자가 접수 시간대 안에서 주문을 취소했습니다."


# #############################################################################
#
#  A 절 — 사용자용 (anon key + 로그인 세션 · RLS 범위 안)
#
#  `utils/duel_db.py` A 절과 같은 규약입니다: 클라이언트를 인자로만 받고, 이 파일이
#  만들지 않습니다. 사용자에게 쓰기 권한이 없는 표(포지션·원장·스냅샷)를 쓰는 함수를
#  이 절에 만들지 않습니다 — 권한이 없는 코드 경로 자체를 두지 않기 위해서입니다.
#
# #############################################################################

# -----------------------------------------------------------------------------
# A-0. 모듈 참여(옵트인) — `duel_opt_in_usd()` RPC 호출
# -----------------------------------------------------------------------------
def opt_in_usd(client):
    """
    로그인한 **본인**을 결투 USD 트랙에 참여시킵니다 — 계좌 3개(M1/M3/M6) + 시드 원장 3행.
    `utils.duel_db.opt_in()` 의 USD 미러입니다 — 논리는 완전히 같고 RPC 이름
    (`duel_opt_in_usd`)과 스키마(§14-10)만 다릅니다.

    사용자 세션 클라이언트로 `duel_opt_in_usd()` RPC 를 한 번 부르고, 돌아온 계좌 3행을
    그대로 담아 돌려줍니다. `user_id`/금액 인자가 없는 이유, 멱등성의 근거는 원화 쪽
    `opt_in()` docstring 과 완전히 동일합니다(RPC 가 같은 방식으로 설계됐습니다).

    ⚠️ 닉네임은 여기서 만들지 않습니다 — 5단계 동의 시점에 `ensure_nickname()` 이
       만듭니다(원화와 같은 순서, 5-11-10).

    반환: 그 사용자의 USD 계좌 3개 dict 목록(M1 → M3 → M6 순).
    """
    _require_client(client)
    try:
        query = client.rpc(OPT_IN_RPC_USD, {})
    except (AttributeError, TypeError) as exc:
        raise DuelDbError(
            "이 Supabase 연결로는 참여 기능을 호출할 수 없습니다"
            " (저장 프로시저 호출을 지원하지 않는 클라이언트입니다)."
        ) from exc
    try:
        rows = _execute(query, "결투 USD 트랙 참여")
    except DuelDbError as exc:
        raise duel_db._translate_opt_in_error(exc, "결투 USD 트랙 참여") from exc

    accounts = [dict(row) for row in rows or []]
    have = {row.get("window_type") for row in accounts}
    missing = [window for window in ACCOUNT_WINDOW_TYPES if window not in have]
    if missing:
        raise DuelDbError(
            "결투 USD 트랙 참여가 끝나지 않았습니다"
            f" (만들어지지 않은 계좌: {missing})."
            " 잠시 뒤 '모듈 참여하기'를 다시 눌러 주세요 — 여러 번 눌러도 시드머니가 두 번"
            " 들어가지는 않습니다."
        )
    return sorted(
        accounts,
        key=lambda row: ACCOUNT_WINDOW_TYPES.index(row["window_type"])
        if row.get("window_type") in ACCOUNT_WINDOW_TYPES else len(ACCOUNT_WINDOW_TYPES),
    )


# -----------------------------------------------------------------------------
#  주문 접수 시간대 오류 번역 — 원화용을 재사용하지 않는 유일한 이유
# -----------------------------------------------------------------------------
def _translate_order_guard_error_usd(exc, action):
    """
    `duel_orders_usd_transition_guard` 트리거(= 원화와 공유하는 `duel_orders_guard`
    함수)의 거절을 번역합니다. `utils.duel_db._translate_order_guard_error()` 와
    **트리거는 같지만 문구가 다릅니다** — 원화 버전은 오류 문장에 "18:00~22:00"을
    그대로 박아 두어서, 그대로 재사용하면 USD 사용자에게 원화 시간대를 보여주는
    사고가 납니다. 그래서 이 함수만 새로 정의합니다.
    """
    text = str(exc or "")
    if "종결된 주문" in text:
        return DuelDbError(
            "이미 처리가 끝난 주문이라 수정·취소할 수 없습니다."
            " 접수 시간대(한국시간 16:00~21:00)가 끝나면 그 주문은 다음 거래일(미국 정규장"
            " 마감가) 체결 대상으로 확정됩니다."
        )
    if "체결 결과와 귀속 거래일은 배치만" in text or "체결 상태는 배치만" in text:
        return DuelDbError(
            "체결 결과는 야간 배치만 기록할 수 있습니다(사용자 경로에서는 바꿀 수 없습니다)."
        )
    if "계좌·종목·매매구분" in text:
        return DuelDbError("주문의 종목·계좌는 바꿀 수 없습니다. 취소 후 새로 주문해 주세요.")
    return DuelDbError(f"{action} 실패: {exc}")


# -----------------------------------------------------------------------------
# A-1. 주문 저장 — USD 접수 시간대(16:00:01~21:00:00) 적용
# -----------------------------------------------------------------------------
def save_order_usd(client, account_id, ticker, stock_name, requested_quantity,
                   *, trading_days, now_kst=None, universe_tickers=None):
    """
    새 예약 주문 1건을 저장합니다(`status='pending'`). `utils.duel_db.save_order()` 의
    USD 미러 — 로직은 완전히 같고 다음 네 가지만 다릅니다:
      ① 접수 시간대 판정에 `duel_rules.resolve_order_window_usd()`(16:00:01~21:00:00)를
         씁니다 — `resolve_order_window()`(원화)를 쓰면 시간대가 두 시간 어긋납니다.
      ② 체결 거래일(`target_date`) 확정에 `duel_rules.resolve_fill_trading_day_usd()` 를
         씁니다. 이 트랙의 접수 시간대는 **그날 미국 정규장이 열리기도 전**(03:00~08:00 ET)
         이라 그날 마감가가 아직 존재하지 않으므로, **저장한 그날 자신이 확정 거래일이면
         그날로 체결**됩니다. 원화용 `resolve_fill_trading_day()`(그날 자신을 무조건 제외 —
         원화는 접수 시각이 이미 그날 종가가 확정된 뒤라서 빼는 게 맞습니다)를 쓰면
         체결이 조용히 하루 늦어집니다(work order §5-16 — 실제로 있었던 버그).
      ③ insert 대상 표가 `duel_orders_usd` 입니다.
      ④ 유니버스 검사 실패 문구가 "미국 주식"을 가리킵니다(코스피가 아닙니다).

    나머지 판단(예수금 초과 여부는 체결가를 모르는 저장 시점에 판정하지 않음 등)은 원화
    쪽과 완전히 같은 근거이므로 반복하지 않습니다 — `utils.duel_db.save_order()` docstring
    참고.

    인자
        trading_days : 확정된 미국 정규장 거래일 목록/집합. **필수**입니다.
        now_kst      : 판정 기준 시각(KST). 테스트·재현용.

    반환: 저장된 주문 행 dict.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    code = _require_text(ticker, "종목코드")
    name = _require_text(stock_name, "종목명")
    quantity = _require_positive_int(requested_quantity, "주문 수량")

    if universe_tickers is not None and code not in set(universe_tickers):
        raise DuelDbError(
            f"{code}은(는) 주문 가능한 미국 주식 유니버스 목록에 없습니다."
            " 이 트랙은 미국 주식만, 달러로만 거래합니다."
        )

    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window_usd(moment)
    if not window["is_open"]:
        opens = window["window_opens_at"]
        closes = window["window_closes_at"]
        raise DuelDbError(
            "지금은 주문 접수 시간이 아닙니다 — "
            f"{opens.strftime('%Y-%m-%d %H:%M:%S')} 부터 {closes.strftime('%H:%M:%S')} 까지"
            " 접수합니다(한국시간)."
            " 접수 시간대는 그날 미국 정규장이 열리기 전으로 잡혀 있고, 체결은 다음 거래일의"
            " 미국 정규장 마감가로 이루어집니다."
        )

    target_date = duel_rules.resolve_fill_trading_day_usd(moment, trading_days)

    payload = {
        "account_id": account,
        "ticker": code,
        "stock_name": name,
        "requested_quantity": quantity,
        "side": "buy",
        "status": ORDER_PENDING,
        "saved_at": moment.isoformat(),
        "target_date": target_date.isoformat(),
    }
    rows = _execute(client.table(ORDERS_TABLE_USD).insert(payload), "주문 저장")
    return _first_row(rows, "주문 저장")


def edit_order_usd(client, order_id, new_quantity, *, now_kst=None):
    """
    `pending` 주문의 **수량만** 수정합니다. `utils.duel_db.edit_order()` 의 USD 미러 —
    시간대 판정에 `resolve_order_window_usd()` 를 쓰고, 트리거 거절 번역에
    `_translate_order_guard_error_usd()` 를 쓰는 것만 다릅니다.
    """
    _require_client(client)
    identifier = _require_text(order_id, "주문 ID")
    quantity = _require_positive_int(new_quantity, "수정할 주문 수량")

    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window_usd(moment)
    if not window["is_open"]:
        raise DuelDbError(
            "지금은 주문 수정 시간이 아닙니다 — 접수 시간대(한국시간 16:00:01~21:00:00) 안에서만"
            " 수량을 바꿀 수 있고, 그 시간이 지나면 다음 거래일 체결 대상으로 확정됩니다."
        )

    payload = {
        "requested_quantity": quantity,
        "last_edited_at": moment.isoformat(),
    }
    try:
        rows = _execute(
            client.table(ORDERS_TABLE_USD).update(payload).eq("id", identifier),
            "주문 수정",
        )
    except DuelDbError as exc:
        raise _translate_order_guard_error_usd(exc, "주문 수정") from exc
    return _first_row(rows, "주문 수정")


def cancel_order_usd(client, order_id, *, reason=None, now_kst=None):
    """
    `pending` 주문을 취소합니다. `utils.duel_db.cancel_order()` 의 USD 미러 — 행을
    지우지 않고 `status='cancelled'` + `fail_reason` 으로 남기는 것도 동일합니다.
    """
    _require_client(client)
    identifier = _require_text(order_id, "주문 ID")
    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window_usd(moment)
    if not window["is_open"]:
        raise DuelDbError(
            "지금은 주문 취소 시간이 아닙니다 — 접수 시간대(한국시간 16:00:01~21:00:00) 안에서만"
            " 취소할 수 있고, 그 시간이 지난 주문은 다음 거래일 체결 대상으로 확정됩니다."
        )

    payload = {
        "status": ORDER_CANCELLED,
        "fail_reason": _require_text(reason or DEFAULT_CANCEL_REASON_USD, "취소 사유"),
        "last_edited_at": moment.isoformat(),
    }
    try:
        rows = _execute(
            client.table(ORDERS_TABLE_USD).update(payload).eq("id", identifier),
            "주문 취소",
        )
    except DuelDbError as exc:
        raise _translate_order_guard_error_usd(exc, "주문 취소") from exc
    _first_row(rows, "주문 취소")
    return None


# -----------------------------------------------------------------------------
# A-2. 조회 — 전부 RLS 범위 안의 읽기 전용 (`utils.duel_db.py` A-2 절 미러)
# -----------------------------------------------------------------------------
def fetch_my_accounts_usd(client, user_id):
    """로그인한 사용자 **본인**의 USD 가상계좌(M1/M3/M6)를 읽습니다."""
    _require_client(client)
    owner = _require_text(user_id, "로그인 사용자 ID")
    rows = _execute(
        client.table(ACCOUNTS_TABLE_USD).select("*").eq("user_id", owner).order("window_type"),
        "USD 가상계좌 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_positions_usd(client, account_id):
    """본인 USD 계좌의 가상 보유 포지션(읽기 전용)."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(POSITIONS_TABLE_USD).select("*").eq("account_id", account).order("ticker"),
        "보유 포지션 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_orders_usd(client, account_id):
    """본인 USD 계좌의 주문 내역(최신순)."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(ORDERS_TABLE_USD).select("*").eq("account_id", account)
              .order("saved_at", desc=True),
        "주문 내역 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_cash_ledger_usd(client, account_id):
    """본인 USD 계좌의 현금 원장(append-only) 전부를 오래된 순으로 읽습니다."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(LEDGER_TABLE_USD).select("*").eq("account_id", account).order("event_date"),
        "현금 원장 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_snapshots_usd(client, account_id, start_date=None, end_date=None):
    """본인 USD 계좌의 일별 스냅샷(오래된 순). `duel_rules.compute_twr()` 에 그대로 넘깁니다."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    query = client.table(DAILY_SNAPSHOTS_TABLE_USD).select("*").eq("account_id", account)
    if start_date:
        query = query.gte("snapshot_date", _iso_date(start_date, "조회 시작일"))
    if end_date:
        query = query.lte("snapshot_date", _iso_date(end_date, "조회 종료일"))
    rows = _execute(query.order("snapshot_date"), "일별 스냅샷 조회")
    return [dict(row) for row in rows]


def fetch_my_holding_snapshots_usd(client, account_id, start_date=None, end_date=None):
    """본인 USD 계좌의 종목별 일별 스냅샷."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    query = client.table(HOLDING_SNAPSHOTS_TABLE_USD).select("*").eq("account_id", account)
    if start_date:
        query = query.gte("snapshot_date", _iso_date(start_date, "조회 시작일"))
    if end_date:
        query = query.lte("snapshot_date", _iso_date(end_date, "조회 종료일"))
    rows = _execute(query.order("snapshot_date"), "종목별 스냅샷 조회")
    return [dict(row) for row in rows]


# -----------------------------------------------------------------------------
# A-3/A-4. 공개 동의 저장 + 철회 (`utils.duel_db.py` A-3/A-4 절 미러)
#
#  ⚠️ 5-11-10 확정: 이 표(`duel_public_consent_usd`)는 원화 `duel_public_consent` 와
#     **완전히 독립**입니다. 한쪽 동의·철회가 다른 쪽에 전혀 영향을 주지 않습니다.
#     공유되는 건 오직 닉네임 문자열뿐이고, 그 공유는 이 절이 아니라 `ensure_nickname()`
#     (원화 파일에서 import)이 담당합니다.
# -----------------------------------------------------------------------------
def save_consent_usd(client, account_id, **consent_flags):
    """
    USD 트랙 공개 동의 상태를 저장합니다(`duel_public_consent_usd`). 받는 키·검증 규칙은
    `utils.duel_db.save_consent()` 와 완전히 같습니다(항목별 동의 5개 + 최종확인 +
    실제 매입총합 동의 — 5-2 / 5-2-4). 표만 다릅니다.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")

    allowed = set(CONSENT_ITEM_FLAGS) | {"final_confirmed", CONSENT_REAL_PRINCIPAL_FLAG}
    unknown = sorted(set(consent_flags) - allowed)
    if unknown:
        raise DuelDbError(
            f"알 수 없는 동의 항목입니다: {unknown}"
            f" (허용: {sorted(allowed)}) — 오타를 조용히 무시하면 사용자는 동의했다고 믿는데"
            " 시스템은 안 켜진 상태가 됩니다."
        )
    for key, value in consent_flags.items():
        if not isinstance(value, bool):
            raise DuelDbError(f"동의 값은 True/False 여야 합니다: {key}={value!r}")

    payload = {"account_id": account}
    payload.update({key: bool(value) for key, value in consent_flags.items()})

    if payload.get("final_confirmed"):
        missing = [flag for flag in CONSENT_ITEM_FLAGS if not payload.get(flag)]
        if missing:
            raise DuelDbError(
                "최종 확인은 공개 항목 5개를 **모두** 체크했을 때만 할 수 있습니다"
                f" (아직 체크되지 않음: {missing})."
                " 이 모듈은 '일부만 공개' 조합을 제공하지 않습니다 — 전부 공개하거나,"
                " 전부 공개하지 않거나 둘 중 하나입니다."
            )
        payload["final_confirmed_at"] = _now_kst().isoformat()
    elif "final_confirmed" in payload:
        payload["final_confirmed_at"] = None

    _assert_reconsent_allowed_usd(client, account)

    rows = _execute(
        client.table(CONSENT_TABLE_USD).upsert(payload, on_conflict="account_id"),
        "공개 동의 저장",
    )
    return _first_row(rows, "공개 동의 저장")


def fetch_my_consent_usd(client, account_id):
    """본인 USD 계좌의 공개 동의 행 1개(없으면 None)."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(CONSENT_TABLE_USD).select("*").eq("account_id", account).limit(1),
        "공개 동의 조회",
    )
    return dict(rows[0]) if rows else None


def _assert_reconsent_allowed_usd(client, account_id, *, now_kst=None):
    """USD 트랙의 3개월 재동의 차단(5-8-2). `utils.duel_db._assert_reconsent_allowed()` 미러."""
    existing = fetch_my_consent_usd(client, account_id)
    if not existing:
        return None
    block = duel_rules.resolve_reconsent_block(existing.get("revoked_at"), now_kst)
    if block["blocked"]:
        raise DuelDbError(
            "공개 동의를 철회한 뒤에는 3개월 동안 다시 동의할 수 없습니다."
            f" {block['unblocks_on'].isoformat()} 부터 다시 신청하실 수 있습니다."
            " (철회하면 그때까지 발행됐던 공개 기록은 전부 영구 삭제되므로,"
            " 되돌리기가 아니라 처음부터 다시 시작하는 절차입니다.)"
        )
    return existing


def revoke_consent_usd(client, account_id, *, now_kst=None):
    """
    USD 트랙 공개 동의를 철회합니다. `utils.duel_db.revoke_consent()` 의 미러 —
    행을 지우지 않고, 항목별 동의 7개를 전부 끄고, 두 번 눌러도 멱등인 것까지 동일합니다.
    ⚠️ 이 철회는 **원화 트랙 동의에 아무 영향이 없습니다**(5-11-10 — 완전 독립).
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")

    existing = fetch_my_consent_usd(client, account)
    if not existing:
        raise DuelDbError(
            "이 계좌에는 철회할 공개 동의 기록이 없습니다"
            " (아직 공개 순위표에 참여한 적이 없습니다)."
        )
    if existing.get("revoked_at"):
        return existing

    payload = {flag: False for flag in CONSENT_ITEM_FLAGS}
    payload[CONSENT_REAL_PRINCIPAL_FLAG] = False
    payload["final_confirmed"] = False
    payload["final_confirmed_at"] = None
    payload["revoked_at"] = _now_kst(now_kst).isoformat()

    rows = _execute(
        client.table(CONSENT_TABLE_USD).update(payload).eq("account_id", account),
        "공개 동의 철회",
    )
    return _first_row(rows, "공개 동의 철회")


# -----------------------------------------------------------------------------
# A-6. 발행표 읽기 전용 조회 (`utils.duel_db.py` A-6 절 미러)
#
#  🔴 컬럼 목록은 `utils.duel_db.PUBLIC_LEADERBOARD_COLUMNS` /
#     `PUBLIC_HOLDINGS_COLUMNS` 를 **그대로 재사용**합니다 — USD 발행표(§13-8)도
#     원화와 컬럼 이름이 완전히 같아서 새로 적을 이유가 없습니다(§0-3-10).
# -----------------------------------------------------------------------------
def fetch_public_leaderboard_latest_date_usd(client, *, window_type, bracket_key):
    """이 그룹(창유형 × 체급)이 USD 발행표에서 **가장 최근에 발행된 날짜** 또는 None."""
    _require_client(client)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        client.table(PUBLIC_LEADERBOARD_TABLE_USD).select("published_date")
        .eq("window_type", window).eq("bracket_key", bracket)
        .order("published_date", desc=True).limit(1),
        "공개 순위표 발행일 조회",
    )
    value = (rows[0] or {}).get("published_date") if rows else None
    return str(value)[:10] if value else None


def fetch_public_leaderboard_usd(client, *, window_type, bracket_key, published_date=None,
                                 limit=duel_rules.LEADERBOARD_PAGE_SIZE, offset=0,
                                 order_desc=False):
    """
    발행된 USD 공개 순위표 한 페이지를 읽습니다. `utils.duel_db.fetch_public_leaderboard()`
    와 인자·정렬·페이지네이션 규약이 완전히 같습니다(표만 다릅니다).
    """
    _require_client(client)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    count = _require_positive_int(limit, "조회 개수")
    start = _require_offset(offset, "건너뛸 개수")

    query = (client.table(PUBLIC_LEADERBOARD_TABLE_USD).select(PUBLIC_LEADERBOARD_COLUMNS)
             .eq("window_type", window).eq("bracket_key", bracket))
    if published_date is not None:
        query = query.eq("published_date", _iso_date(published_date, "발행일"))
    query = (query.order("rank", desc=bool(order_desc))
                  .order("nickname", desc=bool(order_desc)))
    rows = _execute(query.range(start, start + count - 1), "공개 순위표 조회")
    return [dict(row) for row in rows]


def fetch_public_holdings_for_nickname_usd(client, nickname, *, published_date=None,
                                           window_type=None):
    """한 참가자(닉네임)의 **발행된** USD 보유종목을 읽습니다."""
    _require_client(client)
    name = _require_text(nickname, "닉네임")

    query = (client.table(PUBLIC_HOLDINGS_TABLE_USD).select(PUBLIC_HOLDINGS_COLUMNS)
             .eq("nickname", name))
    if published_date is not None:
        query = query.eq("published_date", _iso_date(published_date, "발행일"))
    if window_type is not None:
        query = query.eq("window_type", _require_text(window_type, "창 유형"))
    rows = _execute(query.order("ticker"), "공개 보유종목 조회")
    return [dict(row) for row in rows]


# #############################################################################
#
#  B 절 — 배치용 (service_role · 야간 GitHub Actions 전용)
#
#  🔴 앱 프로세스에서 부르지 마세요(`utils/duel_db.py` B 절과 같은 격리 규율 — §0-3-8).
#  §0-3-2: 계좌 수에 비례해 쿼리를 늘리지 않습니다.
#
# #############################################################################

# -----------------------------------------------------------------------------
# B-1. "모든 USD 계좌를 한 번에"
# -----------------------------------------------------------------------------
def fetch_all_active_accounts_usd(service_client):
    """(배치 전용) **모든 사용자**의 활성 USD 가상계좌를 한 번의 질의로 읽습니다."""
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(ACCOUNTS_TABLE_USD)
        .select("id,user_id,window_type,seed_amount,currency,anchor_date,status")
        .eq("status", "active"),
        "USD 활성 계좌 전체 조회",
    )
    return [dict(row) for row in rows]


def fetch_cash_ledger_for_accounts_usd(service_client, account_ids=None, as_of_date=None):
    """(배치 전용) 여러 USD 계좌의 원장을 한 번에 읽습니다."""
    _require_client(service_client, batch=True)
    query = service_client.table(LEDGER_TABLE_USD).select(
        "account_id,event_type,amount,event_date")
    if account_ids is not None:
        ids = [str(value) for value in account_ids]
        if not ids:
            return []
        query = query.in_("account_id", ids)
    if as_of_date is not None:
        query = query.lte("event_date", _iso_date(as_of_date, "기준일"))
    rows = _execute(query, "현금 원장 일괄 조회")
    return [dict(row) for row in rows]


def fetch_positions_for_accounts_usd(service_client, account_ids=None):
    """(배치 전용) 여러 USD 계좌의 보유 포지션을 한 번의 질의로 읽습니다."""
    _require_client(service_client, batch=True)
    query = service_client.table(POSITIONS_TABLE_USD).select(
        "account_id,ticker,stock_name,quantity,avg_cost,status,delisted_date")
    if account_ids is not None:
        ids = [str(value) for value in account_ids]
        if not ids:
            return []
        query = query.in_("account_id", ids)
    rows = _execute(query.order("account_id").order("ticker"), "보유 포지션 일괄 조회")
    return [dict(row) for row in rows]


def fetch_daily_snapshots_for_accounts_usd(service_client, account_ids=None,
                                           start_date=None, end_date=None):
    """(배치 전용) 여러 USD 계좌의 일별 스냅샷을 한 번의 질의로, 오래된 순으로 읽습니다."""
    _require_client(service_client, batch=True)
    query = service_client.table(DAILY_SNAPSHOTS_TABLE_USD).select(
        "account_id,snapshot_date,total_value,cash_flow_amount")
    if account_ids is not None:
        ids = [str(value) for value in account_ids]
        if not ids:
            return []
        query = query.in_("account_id", ids)
    if start_date is not None:
        query = query.gte("snapshot_date", _iso_date(start_date, "조회 시작일"))
    if end_date is not None:
        query = query.lte("snapshot_date", _iso_date(end_date, "조회 종료일"))
    rows = _execute(query.order("account_id").order("snapshot_date"), "일별 스냅샷 일괄 조회")
    return [dict(row) for row in rows]


# -----------------------------------------------------------------------------
# B-2. 옵트인 백필/관리 도구 — `utils.duel_db.create_duel_accounts_for_user()` 미러
# -----------------------------------------------------------------------------
def create_duel_accounts_for_user_usd(service_client, user_id, *, anchor_date=None):
    """
    (배치/관리 전용) 사용자 1명에게 USD 계좌 3개(M1/M3/M6)와 시드 원장 3행을 만듭니다.
    화면의 "모듈 참여하기" 버튼은 이 함수를 부르지 않습니다 — A 절 `opt_in_usd()` 가
    유일한 사용자 경로입니다(이유는 `utils.duel_db.create_duel_accounts_for_user()`
    docstring 과 완전히 같습니다: 이 함수는 관리자·백필용으로만 남겨 둡니다).

    반환: 그 사용자의 USD 계좌 3개 dict 목록(창유형 순).
    """
    _require_client(service_client, batch=True)
    owner = _require_text(user_id, "사용자 ID")
    anchor = _iso_date(anchor_date or datetime.now(KST).date(), "계좌 개설일")

    existing = _execute(
        service_client.table(ACCOUNTS_TABLE_USD).select("*").eq("user_id", owner),
        "기존 USD 가상계좌 조회",
    )
    have = {row.get("window_type") for row in existing}
    missing = [window for window in ACCOUNT_WINDOW_TYPES if window not in have]

    if missing:
        payload = [{
            "user_id": owner,
            "window_type": window,
            "seed_amount": SEED_AMOUNT_USD,
            "currency": "USD",
            "anchor_date": anchor,
            "status": "active",
        } for window in missing]
        try:
            _execute(service_client.table(ACCOUNTS_TABLE_USD).insert(payload), "USD 가상계좌 개설")
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            print(f"  ℹ️ 이미 개설된 USD 계좌가 있어 건너뜁니다(user={owner[:8]}…).")
        existing = _execute(
            service_client.table(ACCOUNTS_TABLE_USD).select("*").eq("user_id", owner),
            "개설 후 USD 가상계좌 조회",
        )

    accounts = sorted(
        (dict(row) for row in existing),
        key=lambda row: ACCOUNT_WINDOW_TYPES.index(row["window_type"])
        if row.get("window_type") in ACCOUNT_WINDOW_TYPES else len(ACCOUNT_WINDOW_TYPES),
    )
    if accounts:
        _seed_missing_ledger_rows_usd(service_client, accounts, anchor)
    return accounts


def _seed_missing_ledger_rows_usd(service_client, accounts, anchor_date_iso):
    """시드 원장 행을 아직 없는 USD 계좌에만 한 번에 넣습니다."""
    account_ids = [row["id"] for row in accounts if row.get("id")]
    if not account_ids:
        return 0
    seeded = _execute(
        service_client.table(LEDGER_TABLE_USD).select("account_id")
        .in_("account_id", account_ids).eq("event_type", "seed"),
        "시드 원장 조회",
    )
    already = {row.get("account_id") for row in seeded}
    payload = [{
        "account_id": account_id,
        "event_type": "seed",
        "amount": SEED_AMOUNT_USD,
        "event_date": anchor_date_iso,
        "memo": "결투 USD 트랙 계좌 개설 시드머니",
    } for account_id in account_ids if account_id not in already]
    if not payload:
        return 0
    try:
        _execute(service_client.table(LEDGER_TABLE_USD).insert(payload), "시드 지급")
    except DuelDbError as exc:
        if not _is_duplicate_key_error(exc):
            raise
        print("  ℹ️ 시드가 이미 지급돼 있어 건너뜁니다(멱등성 인덱스가 막았습니다).")
        return 0
    return len(payload)


# -----------------------------------------------------------------------------
# B-3. 매월 정기 입금 ($500, 5-11-4)
# -----------------------------------------------------------------------------
def apply_monthly_deposits_usd(service_client, deposit_date):
    """
    (배치 전용) 그 날짜로 **모든 활성 USD 계좌**에 정기 입금 $500 을 넣습니다.
    `utils.duel_db.apply_monthly_deposits()` 의 미러 — §0-3-2 준수(질의 3개 고정),
    멱등성 확보 방식(미리 걸러 넣기)까지 완전히 동일합니다.
    반환: 실제로 새로 넣은 행 수.
    """
    _require_client(service_client, batch=True)
    event_date = _iso_date(deposit_date, "입금일")

    accounts = fetch_all_active_accounts_usd(service_client)
    account_ids = [row["id"] for row in accounts if row.get("id")]
    if not account_ids:
        return 0

    already_rows = _execute(
        service_client.table(LEDGER_TABLE_USD).select("account_id")
        .eq("event_type", "monthly_deposit").eq("event_date", event_date),
        "정기 입금 중복 조회",
    )
    already = {row.get("account_id") for row in already_rows}

    payload = [{
        "account_id": account_id,
        "event_type": "monthly_deposit",
        "amount": MONTHLY_DEPOSIT_USD,
        "event_date": event_date,
        "memo": f"{event_date} 정기 입금",
    } for account_id in account_ids if account_id not in already]
    if not payload:
        return 0

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(LEDGER_TABLE_USD).insert(chunk), "정기 입금")
        inserted += len(chunk)
    return inserted


# -----------------------------------------------------------------------------
# B-4. 체결 — pending 주문 조회 → 결과 기록
# -----------------------------------------------------------------------------
def fetch_pending_orders_for_fill_usd(service_client, target_date):
    """(배치 전용) 그 거래일에 귀속된 **전체 USD 계좌**의 pending 주문을 저장 순서로."""
    _require_client(service_client, batch=True)
    day = _iso_date(target_date, "체결 거래일")
    rows = _execute(
        service_client.table(ORDERS_TABLE_USD).select("*")
        .eq("status", ORDER_PENDING).eq("target_date", day)
        .order("saved_at"),
        "체결 대상 주문 조회",
    )
    return [dict(row) for row in rows]


def record_order_fill_usd(service_client, order_id, status, filled_quantity, filled_price,
                          filled_amount, fail_reason=None, *, filled_date=None):
    """(배치 전용) 주문 1건의 체결 결과를 기록합니다. 여러 건은 `record_order_fills_usd()`로."""
    record_order_fills_usd(service_client, [{
        "id": order_id,
        "status": status,
        "filled_quantity": filled_quantity,
        "filled_price": filled_price,
        "filled_amount": filled_amount,
        "filled_date": filled_date,
        "fail_reason": fail_reason,
    }])
    return None


def record_order_fills_usd(service_client, results):
    """
    (배치 전용) USD 체결 결과 여러 건을 기록합니다. `utils.duel_db.record_order_fills()`
    와 검증 규칙(`_validate_fill_payload`, 원화 파일에서 재사용)이 완전히 같습니다.
    반환: 기록한 행 수.
    """
    _require_client(service_client, batch=True)
    rows = list(results or [])
    if not rows:
        return 0

    written = 0
    for result in rows:
        order_id = _require_text(result.get("id"), "주문 ID")
        status = result.get("status")
        filled_quantity = result.get("filled_quantity")
        filled_price = result.get("filled_price", result.get("fill_price"))
        filled_amount = result.get("filled_amount")
        filled_date = result.get("filled_date")
        fail_reason = result.get("fail_reason")

        if not filled_quantity:
            filled_quantity = filled_price = filled_amount = filled_date = None

        _validate_fill_payload(status, filled_quantity, filled_price, filled_amount,
                               filled_date, fail_reason)

        payload = {
            "status": status,
            "filled_quantity": None if filled_quantity is None else int(filled_quantity),
            "filled_price": filled_price,
            "filled_amount": filled_amount,
            "filled_date": None if filled_date is None else _iso_date(filled_date, "체결일"),
            "fail_reason": fail_reason,
        }
        updated = _execute(
            service_client.table(ORDERS_TABLE_USD).update(payload).eq("id", order_id)
            .eq("status", ORDER_PENDING),
            "체결 결과 기록",
        )
        if updated:
            written += 1
    return written


def record_buy_ledger_entry_usd(service_client, account_id, order_id, filled_amount, event_date,
                                memo=None):
    """(배치 전용) 매수 체결 1건의 현금 원장 행을 남깁니다. 여러 건은 아래 함수로."""
    return record_buy_ledger_entries_usd(service_client, [{
        "account_id": account_id,
        "order_id": order_id,
        "filled_amount": filled_amount,
        "event_date": event_date,
        "memo": memo,
    }])


def record_buy_ledger_entries_usd(service_client, entries):
    """(배치 전용) 매수 원장 행 여러 개를 한 번의 insert 로. 반환: 넣은 행 수."""
    _require_client(service_client, batch=True)
    rows = list(entries or [])
    if not rows:
        return 0

    payload = []
    for entry in rows:
        amount = _require_amount(entry.get("filled_amount"), "체결금액")
        payload.append({
            "account_id": _require_text(entry.get("account_id"), "계좌 ID"),
            "event_type": "buy",
            "amount": -amount,
            "event_date": _iso_date(entry.get("event_date"), "체결일"),
            "order_id": _require_text(entry.get("order_id"), "주문 ID"),
            "memo": entry.get("memo"),
        })

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(LEDGER_TABLE_USD).insert(chunk), "매수 원장 기록")
        inserted += len(chunk)
    return inserted


def upsert_position_weighted_average_usd(service_client, account_id, ticker, stock_name,
                                         existing_position, filled_quantity, fill_price):
    """
    (배치 전용) 매수 체결 1건을 USD 포지션에 반영합니다. 평단가 계산은 여기서 하지 않고
    `duel_rules.apply_buy_fill_to_position()`(원화·달러 공유)를 그대로 씁니다.
    """
    _require_client(service_client, batch=True)
    existing = existing_position or {}
    updated = duel_rules.apply_buy_fill_to_position(
        existing.get("quantity") if existing else None,
        existing.get("avg_cost") if existing else None,
        filled_quantity,
        fill_price,
    )
    rows = upsert_positions_usd(service_client, [{
        "account_id": _require_text(account_id, "계좌 ID"),
        "ticker": _require_text(ticker, "종목코드"),
        "stock_name": _require_text(stock_name, "종목명"),
        "quantity": updated["quantity"],
        "avg_cost": updated["avg_cost"],
    }])
    return _first_row(rows, "포지션 갱신")


def upsert_positions_usd(service_client, rows):
    """(배치 전용) USD 포지션 여러 개를 한 번의 upsert 로 저장합니다. 반환: 저장된 행 목록."""
    _require_client(service_client, batch=True)
    payload = [dict(row) for row in (rows or [])]
    if not payload:
        return []
    _assert_unique_keys(payload, ("account_id", "ticker"), "포지션 저장 요청")

    saved = []
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        saved.extend(_execute(
            service_client.table(POSITIONS_TABLE_USD).upsert(chunk, on_conflict="account_id,ticker"),
            "포지션 저장",
        ))
    return [dict(row) for row in saved]


# -----------------------------------------------------------------------------
# B-5. 체결 불가일 일괄 정리
# -----------------------------------------------------------------------------
def expire_or_cancel_all_pending_for_date_usd(service_client, target_date, reason,
                                              *, status=ORDER_CANCELLED):
    """
    (배치 전용) 그 거래일에 귀속된 **모든 USD 계좌의** pending 주문을 한 번에 실패 처리합니다.
    `utils.duel_db.expire_or_cancel_all_pending_for_date()` 미러. 반환: 실제로 바뀐 행 수.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(target_date, "체결 거래일")
    text = _require_text(reason, "실패 사유")
    if status not in (ORDER_CANCELLED, ORDER_EXPIRED):
        raise DuelDbError(
            f"일괄 실패 처리에 쓸 수 없는 상태입니다: {status!r}"
            f" (가능: {ORDER_CANCELLED} / {ORDER_EXPIRED})."
        )

    rows = _execute(
        service_client.table(ORDERS_TABLE_USD)
        .update({"status": status, "fail_reason": text})
        .eq("status", ORDER_PENDING).eq("target_date", day),
        "미체결 주문 일괄 정리",
    )
    return len(rows)


# -----------------------------------------------------------------------------
# B-6. 일별 스냅샷 적재 — 검증은 원화 파일의 순수 함수를 재사용
# -----------------------------------------------------------------------------
def write_daily_snapshots_usd(service_client, snapshot_date, computed_rows):
    """
    (배치 전용) **이미 계산된** 하루치 USD 스냅샷을 저장합니다. 반환값은 없습니다.
    `utils.duel_db.write_daily_snapshots()` 의 미러 — 행 검증(`_validate_daily_snapshot`
    / `_validate_holding_snapshot`)은 통화와 무관한 순수 규칙이라 그대로 재사용합니다.
    저장 순서(합계 먼저, 종목별 나중)도 동일합니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(snapshot_date, "스냅샷 날짜")
    rows = list(computed_rows or [])
    if not rows:
        return None

    daily_payload = []
    holding_payload = []
    for row in rows:
        if not isinstance(row, dict):
            raise DuelDbError(f"스냅샷 행이 dict 가 아닙니다: {row!r}")
        _validate_daily_snapshot(row, day)
        summary = {key: value for key, value in row.items() if key != "holdings"}
        summary["snapshot_date"] = day
        daily_payload.append(summary)

        for holding in row.get("holdings") or []:
            _validate_holding_snapshot(holding, day)
            detail = dict(holding)
            detail["account_id"] = row["account_id"]
            detail["snapshot_date"] = day
            holding_payload.append(detail)

    _assert_unique_keys(daily_payload, ("account_id", "snapshot_date"), "일별 스냅샷 요청")
    _assert_unique_keys(holding_payload, ("account_id", "ticker", "snapshot_date"),
                        "종목별 스냅샷 요청")

    for start in range(0, len(daily_payload), CHUNK_SIZE):
        _execute(
            service_client.table(DAILY_SNAPSHOTS_TABLE_USD).upsert(
                daily_payload[start:start + CHUNK_SIZE], on_conflict="account_id,snapshot_date"),
            "일별 스냅샷 저장",
        )
    for start in range(0, len(holding_payload), CHUNK_SIZE):
        _execute(
            service_client.table(HOLDING_SNAPSHOTS_TABLE_USD).upsert(
                holding_payload[start:start + CHUNK_SIZE],
                on_conflict="account_id,ticker,snapshot_date"),
            "종목별 스냅샷 저장",
        )
    return None


# -----------------------------------------------------------------------------
# B-7. 공개 발행 (5단계 Branch 2 의 USD 미러) — 가장 민감한 함수들
#
#  🔴 이 절도 원화 파일과 같은 규율을 따릅니다: 판단하지 않고, 이미 결정된 행을 그대로
#     담아 보내거나 지정된 것을 지울 뿐입니다. 닉네임 조회(`fetch_nicknames_for_accounts`)
#     는 원화 파일에서 그대로 재사용합니다(공유 표이므로 — 위 머리말 참고).
#  🔴 발행표에는 user_id/account_id 를 넣지 않습니다(스키마 §13-8 / §0-3-8).
# -----------------------------------------------------------------------------
def fetch_publishable_consents_usd(service_client):
    """(배치 전용) **USD 발행 대상 계좌의 동의 행**을 한 번의 질의로 전부 읽습니다."""
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE_USD).select(
        "account_id,consent_rank,consent_return,consent_holdings,consent_quantity,"
        "consent_buy_amount,final_confirmed," + CONSENT_REAL_PRINCIPAL_FLAG + ",revoked_at"
    ).eq("final_confirmed", True)
    query = _filter_is_null(query, "revoked_at")
    rows = _execute(query, "발행 대상 동의 조회")
    return [dict(row) for row in rows]


def fetch_revoked_consent_accounts_usd(service_client):
    """(배치 전용) **철회된 USD 계좌의 account_id 목록**을 한 번의 질의로 읽습니다."""
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE_USD).select("account_id,revoked_at")
    query = _filter_not_null(query, "revoked_at")
    rows = _execute(query, "철회 계좌 조회")
    return [dict(row) for row in rows]


def fetch_bracket_assignments_usd(service_client, season_key):
    """
    (배치 전용) **이번 시즌의 USD 체급 배정 기록 전부**를 한 번의 질의로 읽습니다.
    `season_key` 는 원화 트랙과 **같은 함수**(`duel_rules.season_key_for_date()`)가
    만드는 값이라 시즌 경계 자체는 공유합니다(5-11-8) — 배정 기록 표만 별개입니다.
    반환: `{account_id: {"season_key": ..., "bracket_key": ...}}`.
    """
    _require_client(service_client, batch=True)
    season = _require_text(season_key, "시즌 식별자")
    rows = _execute(
        service_client.table(BRACKET_ASSIGNMENTS_TABLE_USD)
        .select("account_id,season_key,bracket_key").eq("season_key", season),
        "체급 배정 조회",
    )
    return {row["account_id"]: dict(row) for row in rows if (row or {}).get("account_id")}


def insert_bracket_assignments_usd(service_client, rows):
    """(배치 전용) 새로 배정된 USD 체급을 기록합니다(insert 만). 반환: 넣은 행 수."""
    _require_client(service_client, batch=True)
    payload = []
    for row in rows or []:
        payload.append({
            "account_id": _require_text((row or {}).get("account_id"), "계좌 ID"),
            "season_key": _require_text((row or {}).get("season_key"), "시즌 식별자"),
            "bracket_key": _require_text((row or {}).get("bracket_key"), "체급 식별자"),
        })
    if not payload:
        return 0
    _assert_unique_keys(payload, ("account_id", "season_key"), "체급 배정 요청")

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        try:
            _execute(service_client.table(BRACKET_ASSIGNMENTS_TABLE_USD).insert(chunk), "체급 배정 기록")
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            continue
        inserted += len(chunk)
    return inserted


# ── 발행표 쓰기·지우기 ─────────────────────────────────────────────────────────
def delete_published_rows_for_date_usd(service_client, published_date):
    """(배치 전용) **그날 USD 발행분을 통째로 지웁니다**(두 표 각각 질의 1개)."""
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    _execute(service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).delete()
             .eq("published_date", day), "순위표 당일 발행분 삭제")
    _execute(service_client.table(PUBLIC_HOLDINGS_TABLE_USD).delete()
             .eq("published_date", day), "보유종목 당일 발행분 삭제")
    return None


def delete_published_rows_for_nicknames_usd(service_client, nicknames):
    """(배치 전용) 지정한 닉네임의 USD 발행 행을 **모든 날짜에서 영구 삭제**합니다."""
    _require_client(service_client, batch=True)
    names = sorted({str(value).strip() for value in (nicknames or []) if str(value).strip()})
    if not names:
        return 0

    removed = 0
    for start in range(0, len(names), CHUNK_SIZE):
        chunk = names[start:start + CHUNK_SIZE]
        removed += len(_execute(
            service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).delete().in_("nickname", chunk),
            "철회 계좌의 발행 순위 삭제",
        ))
        removed += len(_execute(
            service_client.table(PUBLIC_HOLDINGS_TABLE_USD).delete().in_("nickname", chunk),
            "철회 계좌의 발행 보유종목 삭제",
        ))
    return removed


def leaderboard_has_any_rows_usd(service_client):
    """(배치 전용) USD 순위표 발행표에 **행이 하나라도 있는가**(질의 1개, `limit(1)`)."""
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).select("id").limit(1),
        "발행표 존재 확인",
    )
    return bool(rows)


def fetch_published_group_index_usd(service_client, window_type, bracket_key):
    """
    (배치 전용) 한 USD 그룹(창유형 × 체급)이 과거에 발행된 적이 있는지와, 있다면 어느
    날짜에 누구(닉네임)로 실렸는지를 읽습니다. 최소 인원 미달 그룹 청소 전용(5-6).
    반환: `{published_date: [nickname, ...]}`
    """
    _require_client(service_client, batch=True)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).select("published_date,nickname")
        .eq("window_type", window).eq("bracket_key", bracket),
        "발행 이력 조회",
    )
    index = {}
    for row in rows:
        day = (row or {}).get("published_date")
        nickname = str((row or {}).get("nickname") or "").strip()
        if day and nickname:
            index.setdefault(str(day)[:10], []).append(nickname)
    return index


def delete_published_group_usd(service_client, window_type, bracket_key, *, holdings_index=None):
    """
    (배치 전용) 최소 인원 미달 USD 그룹의 발행 행을 **모든 날짜에서** 지웁니다.
    `utils.duel_db.delete_published_group()` 미러(질의 수는 계좌·사용자 수에 비례하지 않음).
    """
    _require_client(service_client, batch=True)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")

    index = (fetch_published_group_index_usd(service_client, window, bracket)
             if holdings_index is None else dict(holdings_index))
    if not index:
        return 0

    removed = len(_execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).delete()
        .eq("window_type", window).eq("bracket_key", bracket),
        "최소 인원 미달 그룹 순위 삭제",
    ))
    for day, nicknames in sorted(index.items()):
        names = sorted({str(name).strip() for name in nicknames if str(name).strip()})
        for start in range(0, len(names), CHUNK_SIZE):
            removed += len(_execute(
                service_client.table(PUBLIC_HOLDINGS_TABLE_USD).delete()
                .eq("published_date", day).in_("nickname", names[start:start + CHUNK_SIZE]),
                "최소 인원 미달 그룹 보유종목 삭제",
            ))
    return removed


def write_public_leaderboard_usd(service_client, published_date, rows):
    """
    (배치 전용) USD 순위표 발행 행을 한 번에 넣습니다(청크 단위 insert). 반환: 넣은 행 수.
    식별자 혼입 방어(`_assert_no_identity_fields`, 원화 파일에서 재사용)는 동일합니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    payload = []
    for row in rows or []:
        item = dict(row)
        _assert_no_identity_fields(item, PUBLIC_LEADERBOARD_TABLE_USD)
        item["published_date"] = day
        payload.append(item)
    if not payload:
        return 0
    _assert_unique_keys(payload, ("published_date", "window_type", "bracket_key", "nickname"),
                        "순위표 발행 요청")

    written = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(PUBLIC_LEADERBOARD_TABLE_USD).insert(chunk), "순위표 발행")
        written += len(chunk)
    return written


def write_public_holdings_usd(service_client, published_date, rows):
    """(배치 전용) USD 공개 보유종목 발행 행을 한 번에 넣습니다. 반환: 넣은 행 수."""
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    payload = []
    for row in rows or []:
        item = dict(row)
        _assert_no_identity_fields(item, PUBLIC_HOLDINGS_TABLE_USD)
        item["published_date"] = day
        payload.append(item)
    if not payload:
        return 0
    _assert_unique_keys(payload, ("published_date", "nickname", "ticker"), "보유종목 발행 요청")

    written = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(PUBLIC_HOLDINGS_TABLE_USD).insert(chunk), "보유종목 발행")
        written += len(chunk)
    return written


# =============================================================================
#  회귀 방어용 자기 점검 — 원화 파일의 같은 회귀 방어를 USD 함수에도 적용
# =============================================================================
#: A 절에서 사용자가 부르는 쓰기 함수(USD). `tests/test_duel_db_usd.py` 가 이 목록의
#: 시그니처를 검사합니다 — `utils.duel_db.USER_WRITE_FUNCTIONS` 와 같은 규약입니다.
USER_WRITE_FUNCTIONS_USD = (
    "opt_in_usd", "save_order_usd", "edit_order_usd", "cancel_order_usd", "save_consent_usd",
)


def user_write_signature_violations_usd():
    """USD 트랙 A 절 쓰기 함수들이 금지된 인자를 받고 있지 않은지 스스로 점검합니다."""
    import inspect
    violations = []
    for name in USER_WRITE_FUNCTIONS_USD:
        function = globals().get(name)
        if function is None:
            violations.append(f"{name}: 함수가 없습니다")
            continue
        params = set(inspect.signature(function).parameters)
        for forbidden in FORBIDDEN_USER_WRITE_PARAMS:
            if forbidden in params:
                violations.append(f"{name}({forbidden})")
    return violations
