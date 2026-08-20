# utils/duel_db.py
"""
⚔️ "결투다!" (모의투자 대결 · 4번째 모듈) — **Supabase 접근 계층**

DUEL_MODULE_WORK_ORDER.md 2단계의 파일 계획에 따라 만든 모듈입니다. 이 파일은
`utils/duel_rules.py`(순수 계산)와 `sql/duel_schema.sql`(표·RLS·트리거) 사이를 잇는
**유일한 접착제**입니다. 화면(`web/pages/duel_page.py`)과 야간 배치
(`.github/workflows/duel_daily.yml`)는 Supabase 를 직접 부르지 않고 전부 여기를 통합니다
(`utils/scorecard_db.py` · `utils/report_db.py` 와 같은 계층 분리).

-------------------------------------------------------------------------------
🧮 계산은 여기 있지 않습니다 — 이 파일은 "부르고, 담고, 저장"만 합니다
-------------------------------------------------------------------------------
체결 수량·부분체결 판정·FIFO 예수금 배정·가중평균 평단가·TWR·크롤링 신선도는 **전부**
`utils/duel_rules.py` 의 순수 함수가 계산합니다. 이 파일에는 그 계산을 다시 구현한 코드가
한 줄도 없어야 합니다. 같은 규칙을 두 곳에 적으면 언젠가 둘 중 하나만 고쳐지고, 그 순간
화면이 말하는 숫자와 DB 에 저장된 숫자가 갈라집니다(§0-3-10).
그래서 이 파일은 `duel_rules` 를 **import 해서 호출**하고, 반환값을 그대로 담아 보냅니다.

-------------------------------------------------------------------------------
🔴 이 파일은 저장소에서 **두 번째로** service_role 키를 쓰는 파일입니다
-------------------------------------------------------------------------------
지금까지 `utils/report_db.py` 하나뿐이었습니다. 이 파일이 두 번째입니다.
⚠️ TODO(작업지시서 2단계 표 · §0-1 "문서도 사실이어야 합니다"): `PROJECT_STATUS.md` 의
   "저장소에서 유일하게 service_role 을 쓰는 파일" 서술을 **반드시 갱신**하세요. 이 파일은
   그 문서를 고치지 않습니다(다른 작업 범위) — 대신 여기에 할 일로 남깁니다.

이 파일은 성격이 다른 두 반쪽으로 나뉘고, **둘은 절대 섞이면 안 됩니다.**

    A. 사용자용 (anon key + 로그인 세션, RLS 가 남의 행을 막아 줍니다)
       화면이 이미 만들어 둔 접속별 클라이언트를 **인자로 받아서만** 씁니다. 이 절에는
       클라이언트를 만드는 코드도, service_role 이라는 단어도 없습니다.
       ⚠️ 2026-08-20 추가된 `opt_in()`(모듈 참여)도 **이 절**에 있습니다. 현금 원장에
          시드머니를 넣는 일이라 사용자 권한으로는 불가능해 보이지만, 앱이 원장에 직접
          쓰는 게 아니라 DB 안의 좁은 저장 프로시저(`sql/duel_schema.sql` §9-10 의
          `duel_opt_in()`, 인자 없음 · `auth.uid()` 로만 동작)를 **본인 세션으로 호출**하는
          방식입니다. 그래서 앱 프로세스에는 배치 키가 여전히 필요 없습니다.
    B. 배치용 (service_role, 야간 GitHub Actions 에서만)
       가입한 **모든 사용자**의 계좌를 한 번에 처리해야 하므로 RLS 를 우회합니다.
       `utils/report_db.py` 의 격리 규율을 **그대로** 따릅니다:
         · 키는 **GitHub Actions Secrets 에만** 등록합니다(`SUPABASE_SERVICE_ROLE_KEY`).
           사용자가 접속하는 앱 프로세스(Render 등)에는 **절대 넣지 않습니다** — 들어가는
           순간 이 모듈의 RLS 가 통째로 무력화되고, 그건 §0-3-8 사고입니다.
         · 그래서 키를 `st.secrets` 가 아니라 **환경변수에서만** 읽습니다
           (`_read_service_env()` — streamlit 을 아예 import 하지 않습니다).
         · 키 값은 어떤 로그·예외 메시지에도 싣지 않습니다.

왜 이 격리가 이 모듈에서 특히 중요한가: `sql/duel_schema.sql` 은 RLS 를 표마다 다르게
잡았습니다. 사용자가 직접 쓰는 표는 `duel_orders` 와 `duel_public_consent` **둘뿐**이고,
포지션·현금 원장·스냅샷은 **select 하나뿐**입니다. anon key 는 공개된 키라, 원장에 insert 를
열어 주면 화면을 거치지 않는 직접 호출로 자기 계좌에 가상 현금을 무한히 넣을 수 있습니다.
그 값은 그대로 스냅샷 → 공개 순위표로 흘러갑니다. **A 절에 "사용자가 못 하는 일"을 하는
함수를 만들지 마세요** — 만들 수 있는 코드 경로 자체가 없어야 합니다(§0-3-9).

-------------------------------------------------------------------------------
⚠️ 배치는 반드시 집합 연산 (§0-3-2 / 작업지시서 2-7)
-------------------------------------------------------------------------------
B 절의 어떤 함수도 **계좌 수·사용자 수에 비례해 쿼리를 늘리지 않습니다.** 전체 계좌를 한 번
읽고, 여러 행을 한 번에 씁니다. 사용자가 10명일 때는 루프도 돌아갑니다 — 그래서 위험합니다.
문제가 드러나는 시점이 사용자가 늘어난 뒤이고, 그때는 이미 실사용 중입니다.
`tests/test_duel_db.py` 가 **호출 횟수 자체를** 회귀 테스트로 고정합니다.

-------------------------------------------------------------------------------
⚠️ 지어내지 않기 (ENGINEERING_SPEC §0-1)
-------------------------------------------------------------------------------
  · 실패를 조용히 빈 값으로 넘기지 않습니다. 모든 Supabase 호출은 `_execute()` 를 거치고,
    실패하면 `DuelDbError` 로 올라가 화면·배치 로그까지 도달합니다.
  · 거래일·종가·체결 결과를 이 파일이 만들지 않습니다. 전부 인자로 받습니다.
  · 주문이 조용히 사라지는 경로를 만들지 않습니다 — 취소·만료는 반드시 `fail_reason` 과
    함께 기록합니다(DB CHECK 도 같은 것을 요구합니다).
"""

from __future__ import annotations

import inspect
import os
from datetime import date, datetime

# 🧮 규칙 계산의 단일 출처. 이 파일은 계산하지 않고 **호출**합니다(위 머리말 참고).
from utils import duel_rules
from utils.duel_rules import (
    ACCOUNT_WINDOW_TYPES,
    KST,
    MONTHLY_DEPOSIT_KRW,
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_FILLED,
    ORDER_PARTIALLY_FILLED,
    ORDER_PENDING,
    SEED_AMOUNT_KRW,
)

# supabase 파이썬 패키지는 **선택적 의존성**입니다. requirements.txt 에 들어 있지만, 아직
# 설치되지 않은 환경(또는 설치 실패)에서도 **기존 모듈들이 정상 동작해야** 하므로 여기서
# 죽으면 안 됩니다. `utils/scorecard_db.py` 의 가드와 같은 패턴입니다.
#  ⚠️ 이 파일의 함수 대부분은 클라이언트를 **인자로 받으므로** 패키지 없이도 그대로
#     테스트·호출됩니다. 패키지가 실제로 필요한 곳은 `create_service_client()` 하나뿐이고,
#     그 함수는 `None` 을 부르다 AttributeError 로 죽는 대신 **명확한 DuelDbError** 를 냅니다.
try:  # pragma: no cover - 환경에 따라 갈리는 import
    from supabase import create_client as _supabase_create_client
    SUPABASE_PACKAGE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _supabase_create_client = None
    SUPABASE_PACKAGE_AVAILABLE = False


class DuelDbError(RuntimeError):
    """
    결투 데이터 계층에서 **사용자/로그에 그대로 보여줄** 오류.

    `utils/report_db.py::ReportError` · `utils/scorecard_db.py::ScorecardError` 와 같은
    역할입니다 — 조용히 삼키지 않고, 실패 사실이 화면·배치 로그까지 도달하게 합니다(§0-1).
    `utils/duel_rules.py::DuelRuleError`(규칙 위반)와 구분해서 씁니다: 이쪽은 "저장·조회가
    안 됐다", 저쪽은 "규칙상 불가능하다"입니다. 호출부가 둘을 다 잡아야 하는 경우가 많아
    두 예외 모두 RuntimeError 하위입니다.
    """


# =============================================================================
# 0. 표 이름 — sql/duel_schema.sql 과 **문자 그대로** 같아야 합니다
# =============================================================================
ACCOUNTS_TABLE = "duel_accounts"
POSITIONS_TABLE = "duel_positions"
ORDERS_TABLE = "duel_orders"
LEDGER_TABLE = "duel_cash_ledger"
DAILY_SNAPSHOTS_TABLE = "duel_daily_snapshots"
HOLDING_SNAPSHOTS_TABLE = "duel_holding_snapshots"
NICKNAMES_TABLE = "duel_nicknames"
CONSENT_TABLE = "duel_public_consent"

# 🔒 발행 전용 공개표(`duel_public_leaderboard` / `duel_public_holdings`)의 이름은 **여기에
#    적지 않았습니다.** 5단계 전까지 이 파일에 그 표를 건드릴 코드가 하나도 없어야 하고,
#    상수만 미리 놓아두면 "이미 절반 열려 있는" 모양이 됩니다(§0-3-8 은 "조심하기"가 아니라
#    구조적 방어를 요구합니다). 아래 §C 의 TODO 를 참고하세요.

#: 옵트인 RPC 의 이름. `sql/duel_schema.sql` §9-10 의 함수 이름과 **문자 그대로** 같아야
#: 합니다(표 이름 상수들과 같은 규약).
#:
#: 왜 표가 아니라 RPC 인가: 옵트인은 계좌 3행 + **현금 원장 3행**을 함께 만드는 일인데,
#: 현금 원장은 사용자 세션이 직접 쓸 수 없는 표입니다(스키마 §9-4 — 열어 주면 공개된
#: anon key 로 자기 계좌에 가상 현금을 무한히 찍을 수 있습니다). 그래서 DB 안에 **인자가
#: 하나도 없고 `auth.uid()` 로만 동작하는 좁은 저장 프로시저**를 두고, 앱은 사용자 본인
#: 세션으로 그것만 호출합니다. 자세한 근거는 스키마 §9-10 주석과 아래 `opt_in()` 참고.
OPT_IN_RPC = "duel_opt_in"

#: 한 번에 보내는 행 수. `utils/report_db.py::upsert_snapshots` 와 같은 값입니다 —
#: PostgREST 요청 하나가 지나치게 커지지 않게만 자르는 것이고, 계좌 수만큼 쿼리를 늘리는
#: 것과는 전혀 다릅니다(§0-3-2 위반이 아닙니다).
CHUNK_SIZE = 200

#: 사용자가 스스로 취소했을 때 남기는 기본 사유 문장. `duel_orders_reason_required` CHECK 가
#: 빈 사유를 막으므로, 취소 경로는 **항상** 문장을 채웁니다(§0-1 — 조용히 사라지는 주문 금지).
DEFAULT_CANCEL_REASON = "사용자가 접수 시간대 안에서 주문을 취소했습니다."

#: 5-2 의 항목별 동의 5개. **이 5개만** "전부 아니면 전무" 규칙의 대상입니다.
CONSENT_ITEM_FLAGS = (
    "consent_rank",
    "consent_return",
    "consent_holdings",
    "consent_quantity",
    "consent_buy_amount",
)
#: 위 5개와 **절대 같은 묶음이 아닌** 독립 동의(5-2-4). 이름을 따로 상수로 둔 이유는,
#: 나중에 누가 `CONSENT_ITEM_FLAGS` 에 이 값을 슬쩍 끼워 넣는 일을 눈에 띄게 만들기
#: 위해서입니다 — 끼워 넣는 순간 "실제 자산 데이터 사용 동의"가 가상 성적 공개 동의에
#: 딸려 들어가고, 그건 오너가 명시적으로 분리를 확정한 지점입니다.
CONSENT_REAL_PRINCIPAL_FLAG = "consent_real_principal_bracket"


# =============================================================================
# 0-1. 공통 도우미 — 실패를 삼키지 않기 위한 얇은 층
# =============================================================================
def _execute(query, action):
    """
    Supabase 질의 1건 실행. `utils/report_db.py::_execute` · `scorecard_db::_execute` 와
    **같은 규약**입니다 — 실패를 조용히 빈 목록으로 바꾸지 않습니다(§0-1).

    반환은 항상 list 입니다(응답에 data 가 없으면 빈 목록). "데이터가 없다"와 "요청이
    실패했다"는 다른 말이고, 후자는 여기서 예외가 됩니다.
    """
    try:
        response = query.execute()
    except Exception as exc:  # noqa: BLE001
        raise DuelDbError(f"{action} 실패: {exc}") from exc
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    return data if data is not None else []


def _require_client(client, *, batch=False):
    """
    클라이언트가 없으면 **AttributeError 로 죽지 않고** 사람이 읽을 오류를 냅니다.

    `None.table(...)` 은 "'NoneType' object has no attribute 'table'" 이라는, 사용자에게도
    오너에게도 아무 도움이 안 되는 메시지를 냅니다(§0-3-4). 여기서 먼저 잡습니다.
    """
    if client is None:
        raise DuelDbError(
            "Supabase 배치 클라이언트가 없습니다(create_service_client() 결과를 넘겨주세요)."
            if batch else
            "Supabase 연결이 준비되지 않았습니다(로그인 세션 클라이언트가 필요합니다)."
        )
    return client


def _iso_date(value, label="날짜"):
    """date / datetime / 'YYYY-MM-DD' → 'YYYY-MM-DD'. 없으면 만들지 않고 예외입니다(§0-1)."""
    if value is None:
        raise DuelDbError(f"{label}가 없습니다(임의의 날짜를 만들어 넣지 않습니다).")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        raise DuelDbError(f"{label}가 비어 있습니다.")
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise DuelDbError(f"{label} 형식을 해석할 수 없습니다: {value!r}") from exc


def _now_kst(now_kst=None):
    """
    판정에 쓸 '지금'(KST). 인자로 받으면 그대로 쓰고(테스트·재현용), 없으면 실제 시각입니다.

    ⚠️ DB 의 `now()`(UTC)를 쓰지 않는 이유는 `sql/duel_schema.sql` §4 주석과 같습니다 —
       접수 시간대 판정이 한국시간 기준이라, 판정과 기록이 같은 시계를 봐야 합니다.
    """
    if now_kst is None:
        return datetime.now(KST)
    if not isinstance(now_kst, datetime):
        raise DuelDbError(f"현재 시각은 datetime 이어야 합니다: {now_kst!r}")
    return now_kst if now_kst.tzinfo else now_kst.replace(tzinfo=KST)


def _require_text(value, label):
    text = "" if value is None else str(value).strip()
    if not text:
        raise DuelDbError(f"{label}가 비어 있습니다.")
    return text


def _require_positive_int(value, label):
    """
    정수 수량 검증. 규칙 계산 전에 **입력 자체가 말이 되는지**만 봅니다.

    ⚠️ 2.7 주를 2주로 조용히 깎지 않습니다. 사용자가 낸 값과 다른 값을 저장하면, 나중에
       "왜 내가 낸 것과 다르지"를 설명할 방법이 없습니다(§0-1). 소수는 거절합니다.
       (bool 은 파이썬에서 int 의 하위형이라 True 가 1주로 통과합니다 — 따로 막습니다.)
    """
    if value is None or isinstance(value, bool):
        raise DuelDbError(f"{label}가 올바르지 않습니다: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DuelDbError(f"{label}는 정수여야 합니다: {value!r}") from exc
    if isinstance(value, float) and number != value:
        raise DuelDbError(f"{label}는 정수여야 합니다(소수 불가): {value!r}")
    if isinstance(value, str) and str(number) != value.strip():
        raise DuelDbError(f"{label}는 정수여야 합니다: {value!r}")
    if number <= 0:
        raise DuelDbError(f"{label}는 1 이상이어야 합니다: {value!r}")
    return number


def _require_amount(value, label, *, allow_zero=False):
    if value is None:
        raise DuelDbError(f"{label}가 없습니다.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DuelDbError(f"{label}가 숫자가 아닙니다: {value!r}") from exc
    if number < 0 or (number == 0 and not allow_zero):
        raise DuelDbError(f"{label}가 올바르지 않습니다: {value!r}")
    return number


def _first_row(rows, action):
    """
    insert/update 는 PostgREST 가 저장된 행을 그대로 돌려줍니다. 그게 비어 있다는 건
    **아무 행도 안 바뀌었다**는 뜻입니다(없는 id, 또는 RLS 가 막은 남의 행). 성공으로
    넘기면 화면이 "저장됐습니다"라고 거짓말을 하게 됩니다.
    """
    if not rows:
        raise DuelDbError(
            f"{action}: 대상 행을 찾지 못했습니다"
            " (없는 항목이거나, 다른 사용자의 것이라 접근이 차단됐습니다)."
        )
    return dict(rows[0])


def _error_text(exc):
    return str(exc or "").lower()


def _is_duplicate_key_error(exc):
    """
    유니크 제약 위반(멱등성 인덱스가 제 일을 한 것)인지.

    ⚠️ 아무 오류나 이 경로로 새어 들어가면 진짜 사고가 조용히 묻힙니다
       (`report_db.is_missing_holding_table_error()` 와 같은 판단) — 그래서 표식을 좁게 봅니다.
    """
    text = _error_text(exc)
    return any(marker in text for marker in
               ("23505", "duplicate key", "already exists", "unique constraint"))


def _translate_order_guard_error(exc, action):
    """
    `duel_orders_transition_guard` 트리거의 거절을 **사람이 읽을 한 문장**으로 바꿉니다.

    왜 삼키지 않고 번역만 하는가: 트리거는 이 모듈의 마지막 방어선입니다("화면은 마지막
    방어선이 아니다" — 스키마 머리말 (d)). 거절당했다는 사실은 반드시 사용자에게 도달해야
    하고, 동시에 Postgres 원문(함수명·SQLSTATE)을 그대로 화면에 뿌리면 §0-3-4 위반입니다.
    그래서 **사실은 유지하고 표현만** 바꿉니다.
    """
    text = str(exc or "")
    if "종결된 주문" in text:
        return DuelDbError(
            "이미 처리가 끝난 주문이라 수정·취소할 수 없습니다."
            " 접수 시간대(18:00~22:00)가 끝나면 그 주문은 다음 거래일 체결 대상으로 확정됩니다."
        )
    if "체결 결과와 귀속 거래일은 배치만" in text or "체결 상태는 배치만" in text:
        return DuelDbError(
            "체결 결과는 야간 배치만 기록할 수 있습니다(사용자 경로에서는 바꿀 수 없습니다)."
        )
    if "계좌·종목·매매구분" in text:
        return DuelDbError("주문의 종목·계좌는 바꿀 수 없습니다. 취소 후 새로 주문해 주세요.")
    return DuelDbError(f"{action} 실패: {exc}")


def _translate_opt_in_error(exc, action):
    """
    옵트인 RPC(`duel_opt_in`)의 거절을 **사람이 읽을 한 문장**으로 바꿉니다.

    `_translate_order_guard_error()` 와 같은 규약입니다 — 실패 사실은 그대로 올리고
    표현만 바꿉니다(§0-1 은 실패를 숨기지 말라고 하고, §0-3-4 는 Postgres 원문을 화면에
    그대로 뿌리지 말라고 합니다).
    """
    text = str(exc or "")
    lowered = text.lower()
    if "로그인한 사용자만" in text or "28000" in text:
        return DuelDbError(
            "로그인 상태가 확인되지 않아 참여를 진행할 수 없습니다."
            " 다시 로그인한 뒤 '모듈 참여하기'를 눌러 주세요."
        )
    if ("could not find the function" in lowered or "does not exist" in lowered
            or "pgrst202" in lowered):
        return DuelDbError(
            f"{action} 실패: 참여 기능이 아직 데이터베이스에 설치되지 않았습니다"
            f" (sql/duel_schema.sql 의 {OPT_IN_RPC} 함수). 오너가 SQL 스크립트를 한 번"
            " 실행해야 합니다."
        )
    if "permission denied" in lowered or "42501" in lowered:
        return DuelDbError(
            f"{action} 실패: 이 계정에는 참여 권한이 없습니다"
            " (로그인 상태와 데이터베이스 권한 설정을 확인하세요)."
        )
    return DuelDbError(f"{action} 실패: {exc}")


def _assert_unique_keys(rows, key_fields, label):
    """
    한 번의 upsert 요청 안에 **같은 충돌 키가 두 번** 들어오는 것을 미리 막습니다.

    PostgREST 의 upsert 는 그 경우 "ON CONFLICT DO UPDATE command cannot affect row a second
    time" 로 **요청 전체를** 거절합니다. 그러면 그날 저장이 통째로 날아가는데 원인이 로그에
    잘 드러나지 않습니다(`report_db._assert_unique_holding_keys()` 와 똑같은 방어).

    ⚠️ 겹친 행을 임의로 합치거나 하나를 버리지 않습니다. 합치면 합계가 어긋나고 버리면
       모자랍니다 — 어느 쪽이든 우리 손으로 사실과 다른 숫자를 만드는 셈입니다(§0-1).
    """
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if key in seen:
            raise DuelDbError(
                f"{label}에 같은 키의 행이 두 번 들어 있습니다: {key}"
                " — 임의로 합치거나 버리지 않고 중단합니다(원본 데이터를 확인하세요)."
            )
        seen.add(key)


# #############################################################################
#
#  A 절 — 사용자용 (anon key + 로그인 세션 · RLS 범위 안)
#
#  이 절의 함수는 전부 **첫 인자로 클라이언트를 받습니다.** 여기서 클라이언트를 만들지
#  않는 것이 핵심입니다:
#    · 화면은 접속(브라우저 세션)마다 다른 클라이언트를 씁니다. 이 파일이 클라이언트를
#      만들어 캐시하면 **로그인 세션이 방문자끼리 공유**됩니다
#      (`scorecard_db.create_supabase_client()` 의 경고와 같은 사고 — §0-3-8).
#    · anon 클라이언트 생성은 이미 `utils/scorecard_db.py::create_supabase_client()` 와
#      `web/auth.py::get_client()` 가 하고 있습니다. 두 번째 생성 경로를 만들지 않습니다
#      (§0-3-10 — 나중에 바꿀 곳이 한 군데이게).
#
#  🔴 이 절에 **없어야 하는 것**(스키마 §9 의 실제 RLS 를 그대로 옮긴 것):
#    · 포지션·현금 원장·스냅샷에 쓰는 함수 — 사용자에게는 select 권한밖에 없습니다.
#      (권한이 없으니 "만들어 두고 실패하게" 두면 안 됩니다. 코드 경로 자체가 없어야
#       나중에 누가 RLS 를 열어 보려는 생각을 안 합니다.)
#    · 체결 결과(filled_price / filled_quantity / filled_amount / filled_date)와
#      target_date 를 사용자 입력으로 받는 인자 — 트리거가 막지만, **애초에 인자가 없으면
#      막을 일도 없습니다.** `tests/test_duel_db.py` 가 이 함수들의 시그니처를 검사해서
#      나중에 누가 인자를 늘리면 바로 잡히게 고정해 뒀습니다.
#
# #############################################################################

# -----------------------------------------------------------------------------
# A-0. 모듈 참여(옵트인) — "참여하기" 버튼이 부르는 **유일한** 함수 (2-1)
# -----------------------------------------------------------------------------
#  🔴 이 함수만 이 절에서 유일하게 표가 아니라 **RPC**(DB 안의 저장 프로시저)를 부릅니다.
#     이유를 한 문단으로 적어 둡니다 — 나중에 "왜 여기만 다르지"를 다시 묻지 않도록.
#
#     오너가 2026-08-20 에 "참여하기를 누르면 시드머니가 즉시 들어와야 한다"를 확정했습니다.
#     그런데 시드머니는 `duel_cash_ledger`(현금 원장)에 한 줄을 넣는 일이고, 그 표는 사용자
#     세션이 **쓸 수 없게 일부러 잠가 둔** 표입니다(스키마 §9-4 · §9-9 — anon key 는 공개된
#     키라, 열어 주면 자기 계좌에 가상 현금을 무한히 찍을 수 있고 그 값이 스냅샷 → 공개
#     순위표로 흘러갑니다).
#
#     그렇다고 사용자가 접속하는 앱 서버(Render)에 배치 키를 넣으면, 이 모듈의 RLS 가 통째로
#     무력화됩니다(§0-3-8 / `utils/report_db.py` 이후의 격리 규율). 그래서 **DB 안에 인자가
#     하나도 없고 `auth.uid()` 로만 동작하는 좁은 저장 프로시저**(`sql/duel_schema.sql`
#     §9-10)를 만들고, 앱은 **사용자 본인의 로그인 세션 클라이언트로 그것만** 호출합니다.
#     호출 경로 어디에도 배치 키가 없고, 앱 프로세스는 그 키를 알 필요조차 없습니다.
# -----------------------------------------------------------------------------
def opt_in(client):
    """
    로그인한 **본인**을 결투 모듈에 참여시킵니다 — 계좌 3개(M1/M3/M6) + 시드 원장 3행.
    작업지시서 2-1 / 미결항목 2번 (B)안(즉시 지급) / 스키마 §9-10 참고.

    ── 이 함수가 실제로 하는 일 ──────────────────────────────────────────────────
    사용자 세션 클라이언트로 `duel_opt_in()` RPC 를 **한 번** 부르고, 돌아온 계좌 3행을
    그대로 담아 돌려줍니다. 계산도, 두 번째 왕복도 없습니다(RPC 가 계좌 행을 돌려주므로
    화면이 다시 조회할 필요가 없습니다).

    ── 왜 인자가 클라이언트 하나뿐인가 (이 함수의 안전성이 여기서 나옵니다) ──────────
    누구를 참여시킬지는 **앱이 정하지 않습니다.** 대상은 DB 안에서 `auth.uid()`,
    즉 이 요청에 실려온 로그인 토큰의 주인으로만 정해집니다(RLS 정책들이 쓰는 것과 같은
    값·같은 함수). 그래서 `user_id` 인자가 없고, 남을 대신해 부를 **문법 자체가 없습니다.**
    금액(시드 1천만원)과 개설일도 인자가 아닙니다 — 사용자가 금액이나 날짜를 고를 수 있는
    경로를 만들지 않기 위해서입니다(§0-3-9 — "조심하기"가 아니라 구조로 막기).

    ── 여러 번 눌러도 안전합니다(멱등) ───────────────────────────────────────────
    이미 있는 계좌는 `unique (user_id, window_type)` 이, 이미 지급된 시드는
    `duel_cash_ledger_seed_unique` 부분 유니크 인덱스가 흡수합니다(스키마 §4-1). 즉 버튼을
    연타해도, 두 탭에서 동시에 눌러도 돈이 두 번 들어가지 않습니다. 이 멱등성은 앱의
    조심성이 아니라 **DB 인덱스**가 보장합니다 — 로컬 PostgreSQL 16 에 실제로 두 세션을
    동시에 붙여 확인했습니다.

    ⚠️ 실패를 조용히 넘기지 않습니다(§0-1). 돌아온 계좌가 3개가 아니면 "참여됐습니다"라고
       말하지 않고 예외를 냅니다 — 반쪽 상태를 성공으로 보여주면 사용자는 돈이 들어온 줄
       알고 주문 화면으로 갑니다.

    인자
        client : **로그인한 사용자 본인의** Supabase 클라이언트(화면이 접속마다 만든 것).
                 이 절의 다른 함수들과 같은 규약입니다.

    반환: 그 사용자의 계좌 3개 dict 목록(M1 → M3 → M6 순).
    """
    _require_client(client)
    try:
        # 인자는 빈 dict 입니다 — 보낼 값이 하나도 없습니다(위 설명 참고).
        query = client.rpc(OPT_IN_RPC, {})
    except (AttributeError, TypeError) as exc:
        # 저장 프로시저 호출을 지원하지 않는 클라이언트가 넘어온 경우. 사용자에게
        # `'X' object has no attribute 'rpc'` 를 보여주지 않습니다(§0-3-4).
        raise DuelDbError(
            "이 Supabase 연결로는 참여 기능을 호출할 수 없습니다"
            " (저장 프로시저 호출을 지원하지 않는 클라이언트입니다)."
        ) from exc
    try:
        rows = _execute(query, "결투 모듈 참여")
    except DuelDbError as exc:
        raise _translate_opt_in_error(exc, "결투 모듈 참여") from exc

    accounts = [dict(row) for row in rows or []]
    have = {row.get("window_type") for row in accounts}
    missing = [window for window in ACCOUNT_WINDOW_TYPES if window not in have]
    if missing:
        raise DuelDbError(
            "결투 모듈 참여가 끝나지 않았습니다"
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
# A-1. 주문 저장 — 저장은 **예약**이지 체결이 아닙니다 (2-4)
# -----------------------------------------------------------------------------
def save_order(client, account_id, ticker, stock_name, requested_quantity,
               *, trading_days, now_kst=None, universe_tickers=None):
    """
    새 예약 주문 1건을 저장합니다(`status='pending'`). 작업지시서 2-4 참고.

    이 함수가 실제로 하는 일은 셋뿐입니다 — **판정은 duel_rules 가, 저장은 여기가**:
      ① 지금이 주문 접수 시간대(D일 18:00:01~22:00:00)인가
         → `duel_rules.resolve_order_window()`. 아니면 **명확한 한국어 오류**로 거절합니다.
           조용히 실패하거나 "일단 저장하고 나중에" 하지 않습니다(§0-1).
      ② 이 주문이 귀속되는 거래일(D+1)이 어디인가
         → `duel_rules.resolve_fill_trading_day()`. 거래일 목록은 **호출부가 확정해서 넘깁니다.**
      ③ 위 결과로 만든 행을 `duel_orders` 에 insert.

    ⚠️ `target_date` 를 사용자 입력으로 받지 않고 **여기서 계산해 채우는 이유**는
       스키마의 컬럼 주석에 그대로 적혀 있습니다: DB 는 거래일을 모르므로 insert 시점의
       값을 검증할 수 없고, 그대로 두면 사용자가 자기에게 유리한 날짜를 골라 넣는 경로가
       남습니다. 그래서 서버측 계산값으로 **항상** 채웁니다.

    ⚠️ **유니버스 검사는 이 함수의 일이 아닙니다**(작업지시서 2-4-3의 첫 항목). 코스피 상위
       200 목록은 `data/kospi200_pegy_latest.json` 에서 오고, 그 파일을 읽는 건 화면·수집
       계층의 일입니다. 다만 호출부가 이미 목록을 갖고 있다면 `universe_tickers` 로 넘겨
       한 겹 더 막을 수 있게 열어 뒀습니다(이중 방어). **넘기지 않으면 검사하지 않으며,
       "검사했다"고 가장하지도 않습니다.**

    ⚠️ 예수금 초과 여부는 **저장 시점에 판정하지 않습니다**(2-4-3). 체결가(D+1 종가)를 아직
       모르기 때문입니다. 최종 판정은 야간 배치(B 절)에서만 이루어집니다.

    인자
        trading_days : 확정된 거래일 목록/집합(date 또는 'YYYY-MM-DD'). **필수**입니다 —
                       없으면 다음 거래일을 지어내지 않고 거절합니다(§0-1).
        now_kst      : 판정 기준 시각(KST). 테스트·재현용이며 보통 생략합니다.

    반환: 저장된 주문 행 dict.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    code = _require_text(ticker, "종목코드")
    name = _require_text(stock_name, "종목명")
    quantity = _require_positive_int(requested_quantity, "주문 수량")

    if universe_tickers is not None and code not in set(universe_tickers):
        raise DuelDbError(
            f"{code}은(는) 주문 가능한 코스피 상위 종목 목록에 없습니다."
            " 이 모듈은 코스피 상위 종목만, 원화로만 거래합니다."
        )

    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window(moment)
    if not window["is_open"]:
        opens = window["window_opens_at"]
        closes = window["window_closes_at"]
        raise DuelDbError(
            "지금은 주문 접수 시간이 아닙니다 — "
            f"{opens.strftime('%Y-%m-%d %H:%M:%S')} 부터 {closes.strftime('%H:%M:%S')} 까지"
            " 접수합니다(한국시간)."
            " 접수 시간대는 그날 종가 수집이 끝난 뒤로 잡혀 있고, 체결은 그 다음 거래일의"
            " 확정 종가로 이루어집니다."
        )

    # 거래일 확정. 규칙 위반은 규칙 계층의 예외 그대로 올려 보냅니다 — 문구가 이미
    # 사람이 읽을 수 있고(§0-1), 여기서 다시 포장하면 원인이 흐려집니다.
    target_date = duel_rules.resolve_fill_trading_day(moment, trading_days)

    payload = {
        "account_id": account,
        "ticker": code,
        "stock_name": name,
        "requested_quantity": quantity,
        # side/status 는 DB default 와 같은 값이지만 **명시적으로** 보냅니다. 이 행이
        # 무엇인지가 코드에서 바로 읽혀야 하고, default 가 바뀌어도 여기 의미가 안 흔들립니다.
        "side": "buy",
        "status": ORDER_PENDING,
        # 접수 시간대 판정에 쓴 **바로 그 시각**을 저장합니다. DB default now() 에 맡기면
        # 판정 시각과 기록 시각이 미세하게 달라져, 경계(22:00:00)에서 "창 안에서 통과했는데
        # 창 밖 시각으로 기록된" 행이 생길 수 있습니다.
        "saved_at": moment.isoformat(),
        # 서버측 계산값(위 주석 참고). 사용자 입력을 그대로 받지 않습니다.
        "target_date": target_date.isoformat(),
    }
    rows = _execute(client.table(ORDERS_TABLE).insert(payload), "주문 저장")
    return _first_row(rows, "주문 저장")


def edit_order(client, order_id, new_quantity, *, now_kst=None):
    """
    `pending` 주문의 **수량만** 수정합니다. 작업지시서 2-4-7 참고.

    두 겹으로 막습니다.
      ① 앱: 접수 시간대 밖이면 여기서 거절합니다(화면에 이유가 그대로 뜹니다).
      ② DB: `duel_orders_transition_guard` 트리거가 **최종 권한**입니다. 이미 배치가 집어간
         주문(status ≠ pending)은 트리거가 거절하고, 그 거절을 여기서 **삼키지 않고
         번역해서** 올립니다(`_translate_order_guard_error()`).

    왜 앱에서 status 를 필터로 걸지 않는가(`.eq("status", "pending")` 를 붙이지 않는 이유):
    그러면 이미 체결된 주문을 고치려 할 때 **0행 갱신**이 되어 "왜 안 됐는지"를 알 수 없게
    됩니다. 트리거가 던지는 이유 있는 실패를 받는 편이 사용자에게 훨씬 정직합니다(§0-1).

    ⚠️ 수량 외에는 아무것도 바꾸지 않습니다. 종목·계좌를 바꾸는 건 "다른 주문으로 둔갑"이고
       트리거도 막습니다. 체결 결과 필드는 **인자로도 받지 않습니다**(위 A 절 머리말).
    """
    _require_client(client)
    identifier = _require_text(order_id, "주문 ID")
    quantity = _require_positive_int(new_quantity, "수정할 주문 수량")

    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window(moment)
    if not window["is_open"]:
        raise DuelDbError(
            "지금은 주문 수정 시간이 아닙니다 — 접수 시간대(한국시간 18:00:01~22:00:00) 안에서만"
            " 수량을 바꿀 수 있고, 그 시간이 지나면 다음 거래일 체결 대상으로 확정됩니다."
        )

    payload = {
        "requested_quantity": quantity,
        # 수정 이력은 "마지막 시각 하나"만 남기는 단순 필드입니다(1-3 — 전체 이력이 필요해지면
        # 그때 별도 표로 분리, 지금은 YAGNI).
        "last_edited_at": moment.isoformat(),
    }
    try:
        rows = _execute(
            client.table(ORDERS_TABLE).update(payload).eq("id", identifier),
            "주문 수정",
        )
    except DuelDbError as exc:
        raise _translate_order_guard_error(exc, "주문 수정") from exc
    return _first_row(rows, "주문 수정")


def cancel_order(client, order_id, *, reason=None, now_kst=None):
    """
    `pending` 주문을 취소합니다. 작업지시서 2-4-7 참고. 반환값은 없습니다.

    ⚠️ **행을 지우지 않습니다.** 스키마에 delete 정책이 아예 없는 것과 같은 이유입니다 —
       취소는 `status='cancelled'` + `fail_reason` 으로 **남아야** 합니다. 지우면 "그 주문이
       왜 사라졌는지"가 어디에도 없게 되고, 그게 §0-1 이 금지하는 조용한 소멸입니다.
       그래서 사유 문장은 비워 둘 수 없고(DB CHECK 도 같은 것을 요구합니다), 인자를 주지
       않으면 기본 문장이 들어갑니다.
    """
    _require_client(client)
    identifier = _require_text(order_id, "주문 ID")
    moment = _now_kst(now_kst)
    window = duel_rules.resolve_order_window(moment)
    if not window["is_open"]:
        raise DuelDbError(
            "지금은 주문 취소 시간이 아닙니다 — 접수 시간대(한국시간 18:00:01~22:00:00) 안에서만"
            " 취소할 수 있고, 그 시간이 지난 주문은 다음 거래일 체결 대상으로 확정됩니다."
        )

    payload = {
        "status": ORDER_CANCELLED,
        "fail_reason": _require_text(reason or DEFAULT_CANCEL_REASON, "취소 사유"),
        "last_edited_at": moment.isoformat(),
    }
    try:
        rows = _execute(
            client.table(ORDERS_TABLE).update(payload).eq("id", identifier),
            "주문 취소",
        )
    except DuelDbError as exc:
        raise _translate_order_guard_error(exc, "주문 취소") from exc
    _first_row(rows, "주문 취소")  # 0행이면 여기서 실패합니다(조용한 성공 금지).
    return None


# -----------------------------------------------------------------------------
# A-2. 조회 — 전부 RLS 범위 안의 **읽기 전용**
# -----------------------------------------------------------------------------
#  RLS 가 이미 남의 행을 막지만, 앱에서도 소유자 필터를 명시적으로 겁니다(이중 방어 —
#  `scorecard_db.fetch_holdings()` · `report_db.fetch_user_snapshots()` 와 같은 관례).
#  정책을 실수로 지운 최악의 상황에서도 앱이 남의 데이터를 화면에 그리지 않게 하려는 겁니다.
# -----------------------------------------------------------------------------
def fetch_my_accounts(client, user_id):
    """로그인한 사용자 **본인**의 가상계좌(M1/M3/M6)를 읽습니다."""
    _require_client(client)
    owner = _require_text(user_id, "로그인 사용자 ID")
    rows = _execute(
        client.table(ACCOUNTS_TABLE).select("*").eq("user_id", owner).order("window_type"),
        "가상계좌 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_positions(client, account_id):
    """본인 계좌의 가상 보유 포지션. **읽기 전용**입니다(사용자에게 쓰기 권한이 없습니다)."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(POSITIONS_TABLE).select("*").eq("account_id", account).order("ticker"),
        "보유 포지션 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_orders(client, account_id):
    """본인 계좌의 주문 내역(최신순 — 화면의 '내 주문 내역' 인덱스와 같은 정렬)."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(ORDERS_TABLE).select("*").eq("account_id", account)
              .order("saved_at", desc=True),
        "주문 내역 조회",
    )
    return [dict(row) for row in rows]


def fetch_my_cash_ledger(client, account_id):
    """
    본인 계좌의 현금 원장(append-only) 전부를 **오래된 순으로** 읽습니다.

    잔고 컬럼이 없으므로 예수금은 항상 `sum(amount)` 로 계산합니다(스키마 §4). 화면이
    "지금 매수할 수 있는가"(`duel_rules.is_buy_window_open()`)를 물으려면 이 합계가
    필요해서, 원장 조회를 A 절에 둡니다 — 사용자에게 select 권한이 있는 표입니다.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(LEDGER_TABLE).select("*").eq("account_id", account).order("event_date"),
        "현금 원장 조회",
    )
    return [dict(row) for row in rows]


def sum_cash_balance(ledger_rows):
    """
    원장 행들의 `amount` 합계 = 그 계좌의 예수금.

    ⚠️ 이건 계산 규칙이 아니라 **표현 그대로의 합**이라 여기 둡니다(규칙 계층에 둘 만한
       판단이 하나도 없습니다). 금액이 숫자가 아니면 0 으로 넘기지 않고 예외입니다 —
       "잔고를 모르는 상태"를 "잔고 0"으로 바꿔 보여주면 §0-1 위반입니다.
    """
    total = 0.0
    for row in ledger_rows or []:
        amount = (row or {}).get("amount")
        try:
            total += float(amount)
        except (TypeError, ValueError) as exc:
            raise DuelDbError(f"현금 원장 금액이 손상됐습니다: {amount!r}") from exc
    return total


def fetch_my_snapshots(client, account_id, start_date=None, end_date=None):
    """
    본인 계좌의 일별 스냅샷(오래된 순). `report_db.fetch_user_snapshots()` 와 같은 규약입니다.

    이 결과를 그대로 `duel_rules.compute_twr()` 에 넘기면 누적 TWR 이 나옵니다 — 이 파일은
    수익률을 계산하지 않습니다.

    ⚠️ 기간을 자를 때 시작일을 너무 늦게 잡지 마세요. TWR 은 직전 구간의 `total_value` 가
       분모라, 화면에 보이는 기간의 **바로 앞 기록**까지 함께 있어야 첫 구간이 계산됩니다.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    query = client.table(DAILY_SNAPSHOTS_TABLE).select("*").eq("account_id", account)
    if start_date:
        query = query.gte("snapshot_date", _iso_date(start_date, "조회 시작일"))
    if end_date:
        query = query.lte("snapshot_date", _iso_date(end_date, "조회 종료일"))
    rows = _execute(query.order("snapshot_date"), "일별 스냅샷 조회")
    return [dict(row) for row in rows]


def fetch_my_holding_snapshots(client, account_id, start_date=None, end_date=None):
    """본인 계좌의 **종목별** 일별 스냅샷. 합계 표보다 행이 많으므로 기간을 잘라서 부릅니다."""
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    query = client.table(HOLDING_SNAPSHOTS_TABLE).select("*").eq("account_id", account)
    if start_date:
        query = query.gte("snapshot_date", _iso_date(start_date, "조회 시작일"))
    if end_date:
        query = query.lte("snapshot_date", _iso_date(end_date, "조회 종료일"))
    rows = _execute(query.order("snapshot_date"), "종목별 스냅샷 조회")
    return [dict(row) for row in rows]


# -----------------------------------------------------------------------------
# A-3. 공개 동의 저장 — 사용자가 직접 쓰는 **두 번째이자 마지막** 표
# -----------------------------------------------------------------------------
def save_consent(client, account_id, **consent_flags):
    """
    공개 동의 상태를 저장합니다(`duel_public_consent`). 작업지시서 5-2 / 스키마 §7 참고.

    받는 키(그 밖의 키는 **거절**합니다 — 오타로 동의가 조용히 안 켜지는 사고를 막습니다):
        consent_rank / consent_return / consent_holdings / consent_quantity /
        consent_buy_amount        … 5-2 의 항목별 동의 5개
        final_confirmed           … 5개를 전부 체크한 뒤 밟는 **별도의** 최종 확인
        consent_real_principal_bracket … 위 5개와 **완전히 독립된** 별개 동의

    ── 이 함수가 앱에서도 강제하는 것(DB 가 최종 권한, 여기는 이중 방어) ──────────────
    ① `final_confirmed=True` 는 **5개가 전부 True 일 때만** 허용합니다.
       DB 의 `duel_consent_final_requires_all` CHECK 와 같은 규칙을 앱에서 한 번 더 봅니다.
       DB 만 믿어도 데이터는 안전하지만, 그때 사용자는 Postgres 제약 이름이 섞인 오류를 보게
       됩니다(§0-3-4). 여기서 먼저 잡아 **왜 안 되는지**를 한국어로 알려 줍니다.
    ② `final_confirmed_at` 은 앱이 채웁니다. `final_confirmed` 가 켜지면 시각이 반드시 있어야
       하고(CHECK), 꺼지면 반드시 없어야 합니다 — 두 값을 따로 받지 않고 여기서 짝을 맞춥니다.
       ("언제 최종확인했는지 모르는 최종확인"을 만들지 않기.)
    ③ `consent_real_principal_bracket` 은 **위 5개와 절대 묶지 않습니다.** 5개가 전부 False
       여도 이 동의만 True 일 수 있고, 반대로 최종확인을 해도 이 동의는 따로입니다. 이건
       가상 대결 성적이 아니라 **"내 성적표"의 실제 자산 데이터**를 끌어다 쓰는 동의라,
       오너가 명시적으로 분리를 확정한 지점입니다(5-2-4). 이 함수에 "전부 켜기" 같은
       편의 인자를 만들지 마세요 — 그 순간 둘이 한 몸이 됩니다.

    ⚠️ 5개 항목을 **부분적으로 저장하는 것 자체는 막지 않습니다.** 화면이 체크박스를 하나씩
       켜는 중간 상태가 정상이기 때문입니다. "전부 아니면 전무"(5-2-2)는 **발행 대상이 되는
       조건**(= final_confirmed)에 걸리는 규칙이고, 위 ①이 정확히 그걸 강제합니다.

    ⚠️ 철회(revoked_at)와 3개월 재동의 차단은 이 함수의 범위가 **아닙니다** — 5단계입니다.
       TODO(작업지시서 5-8): 철회 저장·재동의 차단 판정은 발행 인프라와 함께 만듭니다.
       (지금 철회를 반쯤 구현해 두면, 발행표가 없는 상태에서 "철회했는데 지울 게 없는"
        어중간한 경로가 생깁니다.)

    반환: 저장된 동의 행 dict.
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
        # 최종확인을 끄면 시각도 함께 지웁니다(CHECK 가 둘의 짝을 요구합니다).
        payload["final_confirmed_at"] = None

    rows = _execute(
        client.table(CONSENT_TABLE).upsert(payload, on_conflict="account_id"),
        "공개 동의 저장",
    )
    return _first_row(rows, "공개 동의 저장")


# #############################################################################
#
#  B 절 — 배치용 (service_role · 야간 GitHub Actions 전용)
#
#  🔴 **앱 프로세스에서 이 절의 함수를 부르지 마세요.** 여기 함수들은 RLS 를 우회하는
#     클라이언트를 받습니다. 화면 코드가 이 절을 부르기 시작하면, 그 순간 앱 서버에
#     service_role 키가 필요해지고 이 모듈의 모든 RLS 가 장식이 됩니다(§0-3-8).
#     `utils/report_db.py` 의 D 절과 **같은 격리 규율**입니다.
#
#  §0-3-2: 이 절의 어떤 함수도 계좌 수에 비례해 쿼리를 늘리지 않습니다.
#          전체를 한 번 읽고, 여러 행을 한 번에 씁니다.
#
# #############################################################################

SERVICE_URL_ENV = "SUPABASE_URL"
SERVICE_ROLE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"


def _read_service_env(name):
    """
    **환경변수에서만** 읽습니다. `st.secrets` 는 일부러 보지 않습니다 —
    `utils/report_db.py::_read_service_env()` 와 글자 그대로 같은 판단입니다: 이 파일이
    다루는 service_role 키가 **앱 쪽 설정에서 읽히는 경로 자체**를 만들지 않기 위해서입니다.
    값은 어떤 로그·에러 메시지에도 넣지 않습니다.
    """
    value = os.environ.get(name)
    return value.strip() if value else None


def service_config_present():
    """배치 설정이 갖춰졌는지(값은 돌려주지 않습니다)."""
    return bool(_read_service_env(SERVICE_URL_ENV) and _read_service_env(SERVICE_ROLE_KEY_ENV))


def create_service_client():
    """
    배치 전용 Supabase 클라이언트(service_role). **앱에서는 절대 호출하지 마세요.**

    설정이 없으면 조용히 None 을 돌려주지 않고 **예외**를 냅니다 — 배치는 실패해야 사람이
    알아챕니다(A 절의 화면용 경로가 None 을 허용하는 것과 정반대의 판단이고, 이유는
    `report_db.create_service_client()` 와 같습니다: 화면은 "준비중"을 띄우면 되지만, 배치가
    조용히 아무 일도 안 하면 그날 체결이 통째로 사라진 걸 아무도 모릅니다).
    """
    url = _read_service_env(SERVICE_URL_ENV)
    key = _read_service_env(SERVICE_ROLE_KEY_ENV)
    if not url or not key:
        missing = [n for n, v in ((SERVICE_URL_ENV, url), (SERVICE_ROLE_KEY_ENV, key)) if not v]
        raise DuelDbError(
            "배치용 Supabase 설정이 없습니다: " + ", ".join(missing)
            + " (GitHub Actions Secrets 에 등록하세요."
              " ⚠️ 사용자가 접속하는 앱 서버의 환경변수가 아닙니다)"
        )
    # 선택적 의존성 가드. 패키지가 없을 때 `None(url, key)` 를 불러 TypeError 로 죽는 대신,
    # 무엇을 해야 하는지가 적힌 오류를 냅니다(§0-1 / §0-3-4).
    if not SUPABASE_PACKAGE_AVAILABLE or _supabase_create_client is None:
        raise DuelDbError(
            "`supabase` 파이썬 패키지가 설치돼 있지 않습니다(requirements.txt 확인)."
        )
    try:
        return _supabase_create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        raise DuelDbError(f"Supabase 배치 클라이언트 생성 실패: {type(exc).__name__}") from exc


# -----------------------------------------------------------------------------
# B-1. "모든 계좌를 한 번에" — 다른 배치 함수들이 딛고 서는 진입점
# -----------------------------------------------------------------------------
def fetch_all_active_accounts(service_client):
    """
    (배치 전용) **모든 사용자**의 활성 가상계좌를 한 번의 질의로 읽습니다.
    service_role 이라 RLS 를 우회하므로 이게 가능합니다(`report_db.fetch_all_holdings()` 와
    같은 자리·같은 역할).

    이 함수가 §0-3-2 의 출발점입니다. 아래 배치 함수들은 전부 **이 결과 하나**를 받아
    집합으로 처리하고, "사용자별로 다시 조회"하지 않습니다.
    """
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(ACCOUNTS_TABLE)
        .select("id,user_id,window_type,seed_amount,currency,anchor_date,status")
        .eq("status", "active"),
        "활성 계좌 전체 조회",
    )
    return [dict(row) for row in rows]


def group_rows_by_account(rows):
    """[{account_id...}] → {account_id: [행, ...]}. (account_id 없는 행은 버리고 세지 않습니다)"""
    grouped = {}
    for row in rows or []:
        account_id = (row or {}).get("account_id")
        if not account_id:
            continue
        grouped.setdefault(account_id, []).append(row)
    return grouped


def fetch_cash_ledger_for_accounts(service_client, account_ids=None, as_of_date=None):
    """
    (배치 전용) 여러 계좌의 원장을 **한 번에** 읽습니다(계좌별 반복 조회 금지 — §0-3-2).

    `account_ids` 를 주면 `in` 필터로 좁히고, 안 주면 전체를 읽습니다. `as_of_date` 를 주면
    그 날짜까지의 행만 읽습니다(체결 시점의 가용 예수금을 구할 때 씁니다).
    """
    _require_client(service_client, batch=True)
    query = service_client.table(LEDGER_TABLE).select("account_id,event_type,amount,event_date")
    if account_ids is not None:
        ids = [str(value) for value in account_ids]
        if not ids:
            return []          # 대상이 없으면 질의 자체를 보내지 않습니다(빈 in 필터 방지).
        query = query.in_("account_id", ids)
    if as_of_date is not None:
        query = query.lte("event_date", _iso_date(as_of_date, "기준일"))
    rows = _execute(query, "현금 원장 일괄 조회")
    return [dict(row) for row in rows]


def cash_balances_by_account(ledger_rows):
    """{account_id: 예수금 합계}. 위 일괄 조회 결과를 그대로 넘기면 됩니다."""
    balances = {}
    for account_id, rows in group_rows_by_account(ledger_rows).items():
        balances[account_id] = sum_cash_balance(rows)
    return balances


# -----------------------------------------------------------------------------
#  ⬇️ 2026-08-20 추가 — 야간 배치(`utils/duel_batch.py`)가 필요로 하는 **일괄 조회 2개**
#
#  왜 새로 만들었는가: A 절에는 `fetch_my_positions()` · `fetch_my_snapshots()` 가 이미
#  있지만 둘 다 **계좌 1개씩** 읽는 화면용 함수입니다. 배치가 그걸 계좌마다 부르면 그게
#  정확히 §0-3-2(작업지시서 2-7)가 금지한 "사용자 수 × 쿼리" 모양이 됩니다. 그렇다고
#  배치가 Supabase 를 직접 부르면 이 파일이 "유일한 접착제"라는 계층 규약이 깨집니다.
#  그래서 위 `fetch_cash_ledger_for_accounts()` 와 **완전히 같은 모양**(in 필터 1회,
#  대상이 비면 질의 자체를 보내지 않음)으로 B 절에 둡니다.
# -----------------------------------------------------------------------------
def fetch_positions_for_accounts(service_client, account_ids=None):
    """
    (배치 전용) 여러 계좌의 보유 포지션을 **한 번의 질의로** 읽습니다(§0-3-2).

    `account_ids` 를 주면 `in` 필터로 좁히고, 안 주면 전체를 읽습니다. 정렬은 (계좌, 종목)
    이라 `group_rows_by_account()` 로 묶으면 계좌 안에서 종목 순서가 항상 같습니다 —
    배치를 두 번 돌렸을 때 스냅샷 행 순서가 흔들리지 않게 하려는 것입니다.

    ⚠️ 수량·평단가를 여기서 고치지 않습니다(읽기 전용). 갱신은 `upsert_positions()` 가
       `duel_rules.apply_buy_fill_to_position()` 의 결과를 담아서만 합니다.
    """
    _require_client(service_client, batch=True)
    query = service_client.table(POSITIONS_TABLE).select(
        "account_id,ticker,stock_name,quantity,avg_cost,status,delisted_date")
    if account_ids is not None:
        ids = [str(value) for value in account_ids]
        if not ids:
            return []          # 대상이 없으면 질의 자체를 보내지 않습니다(빈 in 필터 방지).
        query = query.in_("account_id", ids)
    rows = _execute(query.order("account_id").order("ticker"), "보유 포지션 일괄 조회")
    return [dict(row) for row in rows]


def fetch_daily_snapshots_for_accounts(service_client, account_ids=None,
                                       start_date=None, end_date=None):
    """
    (배치 전용) 여러 계좌의 일별 스냅샷을 **한 번의 질의로**, 오래된 순으로 읽습니다(§0-3-2).

    배치가 이걸 왜 읽는가 — 두 가지 때문입니다(둘 다 계좌별로 다시 조회하면 안 됩니다):
      ① **누적 TWR**(2-6). `duel_rules.compute_twr()` 는 개설일부터의 스냅샷 전부를 받아야
         구간 곱을 만들 수 있습니다. 그래서 기본값은 기간을 자르지 않습니다 —
         자르면 첫 구간의 분모(V_{t−1})가 사라져 수익률이 조용히 달라집니다.
      ② **직전 스냅샷 날짜.** 수집 실패·휴장으로 스냅샷을 건너뛴 날의 외부 현금흐름(시드·
         정기입금)이 어느 날 행에도 안 적히면, 다음 스냅샷에서 입금이 **수익으로 둔갑**합니다.
         배치는 "직전 스냅샷 다음날 ~ 오늘"의 현금흐름을 오늘 행에 합산해 그걸 막습니다
         (자세한 근거는 `utils/duel_batch.py` 의 현금흐름 이월 주석).

    ⚠️ `start_date` 를 함부로 주지 마세요(위 ① 이유). 인자를 열어 둔 것은 나중에 계좌가
       아주 많아졌을 때 오너가 의도적으로 자를 수 있게 하려는 것뿐입니다.
    """
    _require_client(service_client, batch=True)
    query = service_client.table(DAILY_SNAPSHOTS_TABLE).select(
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
# B-2. 옵트인 — 계좌 3개 + 시드 원장 3행 (2-1)
# -----------------------------------------------------------------------------
def create_duel_accounts_for_user(service_client, user_id, *, anchor_date=None):
    """
    (배치/관리 전용) 사용자 1명에게 계좌 3개(M1/M3/M6)와 시드 원장 3행을 만듭니다.
    작업지시서 2-1 참고. **여러 번 불러도 안전합니다(멱등).**

    🔴 **화면의 "모듈 참여하기" 버튼은 이 함수를 부르지 않습니다.** 2026-08-20 부터 사용자
       옵트인의 경로는 A 절의 `opt_in(client)` 하나뿐입니다 — 사용자 본인 세션으로
       `sql/duel_schema.sql` §9-10 의 `duel_opt_in()` RPC 를 부르는 함수입니다. 화면이 이
       함수를 부르기 시작하면 앱 서버에 배치 키가 필요해지고, 그 순간 이 모듈의 RLS 가
       전부 장식이 됩니다(§0-3-8).
       그럼 이 함수는 왜 남겨 두는가: **관리자·백필·지원 도구** 때문입니다. 예를 들어 RPC
       설치 전에 가입해 계좌가 없는 사용자를 뒤늦게 메우거나, 지원 요청으로 특정 계정의
       상태를 오너가 직접 복구할 때는 GitHub Actions 쪽 경로가 필요합니다. 두 경로는 같은
       유니크 인덱스(§4-1)에 기대므로 서로 부딪히지 않습니다 — 어느 쪽을 먼저 돌려도
       계좌가 늘거나 시드가 두 번 들어가지 않습니다.

    ── 왜 이 함수가 A 절이 아니라 B 절에 있는가 (구현하며 확인한 사실) ────────────────
    스키마 §9-1 은 사용자에게 `duel_accounts` insert 를 허용합니다. 그런데 `duel_cash_ledger`
    에는 **사용자 insert 정책도 권한도 없습니다**(§9-4 / §9-9 — 시퀀스 usage 조차 authenticated
    에게 주지 않습니다). 즉 **원장에 직접 쓰는 방식의 시드 지급은 사용자 세션으로 불가능**
    하고, 계좌만 만들고 시드가 안 들어가면 "돈 없는 계좌"라는 반쪽 상태가 남습니다.
    그래서 이 함수는 옵트인 전체를 배치 키 경로 하나로 묶습니다.

    ✅ 2026-08-20 — 이 제약은 **표에 직접 쓰는 경우에만** 참이라는 것이 확인됐고, 사용자
       세션으로도 안전하게 시드를 넣는 길이 생겼습니다: 표 소유자 권한으로 도는 좁은
       `security definer` 저장 프로시저(`sql/duel_schema.sql` §9-10 `duel_opt_in()`)를 본인
       세션으로 호출하는 방식입니다. 사용자는 여전히 원장 표에 **한 글자도 직접 쓰지
       못하고**, 앱 서버는 배치 키를 갖지 않습니다. 화면용 진입점은 A 절 `opt_in()` 입니다.

    ── 멱등성을 어떻게 확보하는가 ────────────────────────────────────────────────────
    ① 먼저 그 사용자의 기존 계좌를 **한 번** 읽습니다. 없는 창유형만 만듭니다.
    ② 시드도 마찬가지로, 이미 시드가 있는 계좌를 **한 번** 읽고 없는 계좌에만 넣습니다.
    ③ 그래도 동시 실행으로 충돌이 나면(`unique (user_id, window_type)` /
       `duel_cash_ledger_seed_unique`) **예외를 그대로 터뜨리지 않고** 다시 읽어 정상 상태를
       돌려줍니다. 유니크 인덱스가 제 일을 한 것이고, 그건 사고가 아니라 방어의 성공입니다.
       (다른 오류는 그대로 올립니다 — `_is_duplicate_key_error()` 로 표식을 좁게 봅니다.)

    ⚠️ `seed_amount` 는 `duel_rules.SEED_AMOUNT_KRW` 하나가 단일 출처입니다. DB 에 default 를
       두지 않은 이유가 그것이므로(스키마 §1), 여기서 **항상 명시적으로** 넣습니다.

    반환: 그 사용자의 계좌 3개 dict 목록(창유형 순).
    """
    _require_client(service_client, batch=True)
    owner = _require_text(user_id, "사용자 ID")
    anchor = _iso_date(anchor_date or datetime.now(KST).date(), "계좌 개설일")

    existing = _execute(
        service_client.table(ACCOUNTS_TABLE).select("*").eq("user_id", owner),
        "기존 가상계좌 조회",
    )
    have = {row.get("window_type") for row in existing}
    missing = [window for window in ACCOUNT_WINDOW_TYPES if window not in have]

    if missing:
        payload = [{
            "user_id": owner,
            "window_type": window,
            "seed_amount": SEED_AMOUNT_KRW,
            "currency": "KRW",
            "anchor_date": anchor,
            "status": "active",
        } for window in missing]
        try:
            # 3행을 **한 번에** 넣습니다(창유형별로 3번 부르지 않습니다).
            _execute(service_client.table(ACCOUNTS_TABLE).insert(payload), "가상계좌 개설")
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            # 같은 사용자에 대해 동시에 두 번 돌았습니다. 유니크 제약이 막아 줬으니
            # 중복 계좌는 없습니다 — 아래에서 다시 읽어 실제 상태를 돌려줍니다.
            print(f"  ℹ️ 이미 개설된 계좌가 있어 건너뜁니다(user={owner[:8]}…).")
        existing = _execute(
            service_client.table(ACCOUNTS_TABLE).select("*").eq("user_id", owner),
            "개설 후 가상계좌 조회",
        )

    accounts = sorted(
        (dict(row) for row in existing),
        key=lambda row: ACCOUNT_WINDOW_TYPES.index(row["window_type"])
        if row.get("window_type") in ACCOUNT_WINDOW_TYPES else len(ACCOUNT_WINDOW_TYPES),
    )
    if accounts:
        _seed_missing_ledger_rows(service_client, accounts, anchor)
    return accounts


def _seed_missing_ledger_rows(service_client, accounts, anchor_date_iso):
    """
    시드 원장 행을 **아직 없는 계좌에만** 한 번에 넣습니다(위 함수의 ②·③ 단계).

    시드는 계좌당 정확히 1행이어야 하므로 스키마가 날짜를 조건에 넣지 않은 부분 유니크
    인덱스로 막고 있습니다(`duel_cash_ledger_seed_unique`). 여기서는 그 인덱스에 기대기
    **전에** 먼저 걸러서, 정상적인 재실행이 예외로 시끄러워지지 않게 합니다.
    """
    account_ids = [row["id"] for row in accounts if row.get("id")]
    if not account_ids:
        return 0
    seeded = _execute(
        service_client.table(LEDGER_TABLE).select("account_id")
        .in_("account_id", account_ids).eq("event_type", "seed"),
        "시드 원장 조회",
    )
    already = {row.get("account_id") for row in seeded}
    payload = [{
        "account_id": account_id,
        "event_type": "seed",
        "amount": SEED_AMOUNT_KRW,
        "event_date": anchor_date_iso,
        "memo": "결투 계좌 개설 시드머니",
    } for account_id in account_ids if account_id not in already]
    if not payload:
        return 0
    try:
        _execute(service_client.table(LEDGER_TABLE).insert(payload), "시드 지급")
    except DuelDbError as exc:
        if not _is_duplicate_key_error(exc):
            raise
        print("  ℹ️ 시드가 이미 지급돼 있어 건너뜁니다(멱등성 인덱스가 막았습니다).")
        return 0
    return len(payload)


# -----------------------------------------------------------------------------
# B-3. 매월 10일 정기 입금 (2-2)
# -----------------------------------------------------------------------------
def apply_monthly_deposits(service_client, deposit_date):
    """
    (배치 전용) 그날짜로 **모든 활성 계좌**에 정기 입금 80만원을 넣습니다. 2-2 참고.
    반환: 실제로 새로 넣은 행 수.

    ── §0-3-2 (이 함수가 그 원칙의 대표 사례입니다) ──────────────────────────────────
    계좌가 3개든 3만개든 질의 수는 **항상 3개**입니다:
        ① 활성 계좌 전체 조회  ② 그날 이미 들어간 입금 조회  ③ 나머지 전부를 한 번에 insert
    계좌별 루프를 돌면 사용자 수 × 2 쿼리가 되고, 사용자가 10명일 때는 그것도 잘 돌아갑니다
    — 그래서 위험합니다. `tests/test_duel_db.py` 가 **호출 횟수 자체를** 고정합니다.

    ── 멱등성을 인덱스에만 맡기지 않는 이유 ─────────────────────────────────────────
    스키마의 `duel_cash_ledger_monthly_deposit_unique` 는 **부분 유니크 인덱스**
    (`where event_type='monthly_deposit'`)입니다. PostgREST 의 upsert 는 이 인덱스를
    ON CONFLICT 대상으로 추론하지 못하고(부분 인덱스는 술어까지 맞아야 추론됩니다),
    게다가 원장은 append-only 라 `do update` 자체가 트리거에 막힙니다. 그래서 여기서는
    **미리 걸러서 넣는 방식**을 씁니다 — 배치를 두 번 돌리면 두 번째는 0행을 넣고 조용히
    끝납니다. 인덱스는 그 뒤의 마지막 방어선으로 그대로 남습니다(경합 시 예외 → 시끄럽게
    실패, 돈은 두 번 들어가지 않음).

    ⚠️ 10일이 주말·공휴일이어도 **그대로 10일자**로 넣습니다(2-2-4). 이건 시장 이벤트가
       아니라 현금 이벤트입니다. 날짜를 영업일로 밀지 마세요.
    """
    _require_client(service_client, batch=True)
    event_date = _iso_date(deposit_date, "입금일")

    accounts = fetch_all_active_accounts(service_client)
    account_ids = [row["id"] for row in accounts if row.get("id")]
    if not account_ids:
        return 0

    already_rows = _execute(
        service_client.table(LEDGER_TABLE).select("account_id")
        .eq("event_type", "monthly_deposit").eq("event_date", event_date),
        "정기 입금 중복 조회",
    )
    already = {row.get("account_id") for row in already_rows}

    payload = [{
        "account_id": account_id,
        "event_type": "monthly_deposit",
        "amount": MONTHLY_DEPOSIT_KRW,
        "event_date": event_date,
        "memo": f"{event_date} 정기 입금",
    } for account_id in account_ids if account_id not in already]
    if not payload:
        return 0

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(LEDGER_TABLE).insert(chunk), "정기 입금")
        inserted += len(chunk)
    return inserted


# -----------------------------------------------------------------------------
# B-4. 체결 — pending 주문 조회 → 결과 기록 (2-4-6)
# -----------------------------------------------------------------------------
def fetch_pending_orders_for_fill(service_client, target_date):
    """
    (배치 전용) 그 거래일에 귀속된 **전체 계좌**의 pending 주문을 `saved_at` 오름차순으로.
    작업지시서 2-4-6 참고.

    정렬이 규약의 일부입니다: `duel_rules.allocate_pending_orders()` 의 FIFO 예수금 배정이
    "뒤 주문이 앞 주문 몫까지 넘보지 않게" 하려면 저장 순서가 필요합니다. 규칙 함수도 자체
    정렬을 하지만, 여기서 정렬해 오는 편이 **DB 인덱스를 그대로 쓰는** 길이기도 합니다
    (`duel_orders_pending_target_idx (target_date, saved_at) where status='pending'`).

    ⚠️ 한 번의 질의로 전체 계좌를 가져옵니다. 계좌별로 부르지 마세요(§0-3-2).
    """
    _require_client(service_client, batch=True)
    day = _iso_date(target_date, "체결 거래일")
    rows = _execute(
        service_client.table(ORDERS_TABLE).select("*")
        .eq("status", ORDER_PENDING).eq("target_date", day)
        .order("saved_at"),
        "체결 대상 주문 조회",
    )
    return [dict(row) for row in rows]


def _validate_fill_payload(status, filled_quantity, filled_price, filled_amount,
                           filled_date, fail_reason):
    """
    체결 결과 4필드의 아귀를 **보내기 전에** 맞춥니다(스키마의 세 CHECK 와 같은 규칙).

    DB 가 어차피 막지만, PostgREST 를 통해 오는 CHECK 위반 메시지는 제약 이름만 있고 어느
    주문인지도 안 나옵니다. 배치 로그에서 원인을 찾을 수 있도록 여기서 먼저 잡습니다.
    """
    valid = (ORDER_FILLED, ORDER_PARTIALLY_FILLED, ORDER_CANCELLED, ORDER_EXPIRED)
    if status not in valid:
        raise DuelDbError(
            f"체결 결과로 기록할 수 없는 상태입니다: {status!r} (가능: {list(valid)})."
            " pending 은 '아직 아무 일도 없음'이라 결과로 기록하지 않습니다."
        )
    has_fill = filled_quantity is not None
    if has_fill:
        # 넷은 함께 있거나 함께 없어야 합니다 — 하나만 든 행은 "얼마에 몇 주가 언제"
        # 중 일부를 모르는 상태라 나중에 집계하는 사람마다 다른 숫자가 나옵니다.
        if filled_price is None or filled_amount is None or filled_date is None:
            raise DuelDbError(
                "체결 결과는 (체결일·체결가·체결수량·체결금액) 네 값이 **함께** 있어야 합니다"
                f" (date={filled_date!r}, price={filled_price!r},"
                f" qty={filled_quantity!r}, amount={filled_amount!r})."
                " 체결일을 모르면 오늘 날짜를 지어 넣지 말고, 체결에 쓴 거래일을 넘겨주세요(§0-1)."
            )
        if status in (ORDER_FILLED, ORDER_PARTIALLY_FILLED) and int(filled_quantity) <= 0:
            raise DuelDbError(
                f"{status} 인데 체결 수량이 {filled_quantity} 입니다."
                " 0주 체결은 filled/partially_filled 가 아니라 expired 입니다(2-4-6)."
            )
    if status != ORDER_FILLED and not str(fail_reason or "").strip():
        raise DuelDbError(
            f"{status} 상태에는 사람이 읽을 사유 문장이 반드시 필요합니다"
            " — 주문이 조용히 사라지는 경로를 만들지 않습니다(§0-1)."
        )


def record_order_fill(service_client, order_id, status, filled_quantity, filled_price,
                      filled_amount, fail_reason=None, *, filled_date=None):
    """
    (배치 전용) 주문 1건의 **체결 결과를 기록**합니다. 반환값은 없습니다.

    ⚠️ 이 함수는 **계산하지 않습니다.** 체결 수량·부분체결 판정·사유 문구는 전부
       `duel_rules.calculate_fill()` / `allocate_pending_orders()` 가 만든 값을 그대로
       받아 적습니다. 여기서 다시 `floor(cash/price)` 같은 걸 쓰면 규칙이 두 곳에 생깁니다.

    ⚠️ `filled_date` 는 **체결에 쓴 거래일**입니다. 기본값을 오늘로 두지 않았습니다 — 배치가
       하루 늦게 돌면 체결일이 조용히 틀어지고, 그건 나중에 복원할 수 없는 오염입니다(§0-1).

    ⚠️ 한 건씩 부르는 함수입니다. 배치는 주문 수만큼 이걸 반복하지 말고
       `record_order_fills()`(아래)로 **한 번에** 보내세요(§0-3-2).
    """
    record_order_fills(service_client, [{
        "id": order_id,
        "status": status,
        "filled_quantity": filled_quantity,
        "filled_price": filled_price,
        "filled_amount": filled_amount,
        "filled_date": filled_date,
        "fail_reason": fail_reason,
    }])
    return None


def record_order_fills(service_client, results):
    """
    (배치 전용) 체결 결과 여러 건을 기록합니다. 반환: 기록한 행 수.

    `duel_rules.allocate_pending_orders()` 의 결과 목록을 거의 그대로 받을 수 있게 키 이름을
    맞춰 뒀습니다(`id` / `status` / `filled_quantity` / `filled_amount` / `fail_reason`;
    체결가는 규칙 쪽이 `fill_price` 로 돌려주므로 둘 다 받습니다).

    ── 왜 update 를 행마다 부르는가 (여기만 §0-3-2 의 예외처럼 보이는 이유) ─────────────
    PostgREST 에는 "행마다 다른 값으로 한 번에 update" 하는 문법이 없습니다. 대안은 upsert 인데,
    체결 결과 upsert 는 `duel_orders` 의 **모든 not null 컬럼을 다시 보내야** 하고(insert 경로가
    될 수 있으므로), 그 과정에서 `saved_at` 같은 정체성 컬럼을 배치가 덮어쓰게 됩니다 —
    상태 전이 가드 트리거가 정확히 그걸 막고 있습니다. 그래서 **체결된 주문 수만큼** update 를
    보냅니다. 이건 "사용자 수에 비례"가 아니라 "그날 실제 체결 건수에 비례"이고, 하루에 한 번
    도는 배치에서 그 수는 주문이 실제로 들어온 만큼입니다(§0-3-2 가 막으려는 건 **일하지 않은
    행까지 훑는** 사용자별 루프입니다). 조회·원장·포지션·스냅샷은 전부 집합 연산입니다.
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

        # 체결이 하나도 없었던 결과(취소·만료)는 체결 4필드를 **전부 비워** 기록합니다.
        # 0원·0주를 넣으면 "0에 체결됐다"는 다른 뜻이 됩니다(§0-1).
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
            service_client.table(ORDERS_TABLE).update(payload).eq("id", order_id)
            # 이미 종결된 주문을 다시 덮어쓰지 않게 배치도 pending 만 집습니다. 트리거가
            # 최종 방어선이지만, 배치를 두 번 돌렸을 때 시끄럽게 실패하는 대신 0행이 되게
            # 해서 재실행이 안전하게 만듭니다.
            .eq("status", ORDER_PENDING),
            "체결 결과 기록",
        )
        if updated:
            written += 1
    return written


def record_buy_ledger_entry(service_client, account_id, order_id, filled_amount, event_date,
                            memo=None):
    """
    (배치 전용) 매수 체결 1건의 현금 원장 행을 남깁니다. 2-4-6 참고.

    ⚠️ 원장의 매수 금액은 **음수**입니다(`amount < 0` CHECK). 호출부는 체결금액을 **양수로**
       넘기고, 부호는 여기서 한 번만 뒤집습니다 — 부호를 호출부마다 다루면 언젠가 한 곳에서
       빠지고, 그 계좌의 잔고가 조용히 두 배가 됩니다.
    ⚠️ 체결금액 0원짜리 행은 만들지 않습니다(만료된 주문은 원장에 아무 흔적도 남기지
       않는 것이 맞습니다 — 현금이 움직이지 않았으니까요).
    ⚠️ 여러 건은 `record_buy_ledger_entries()` 로 **한 번에** 보내세요(§0-3-2).
    """
    return record_buy_ledger_entries(service_client, [{
        "account_id": account_id,
        "order_id": order_id,
        "filled_amount": filled_amount,
        "event_date": event_date,
        "memo": memo,
    }])


def record_buy_ledger_entries(service_client, entries):
    """(배치 전용) 매수 원장 행 여러 개를 **한 번의 insert** 로. 반환: 넣은 행 수."""
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
            "amount": -amount,   # 부호를 뒤집는 유일한 자리(위 주석 참고).
            "event_date": _iso_date(entry.get("event_date"), "체결일"),
            # buy 행에는 주문 링크가 반드시 있어야 추적이 됩니다(`..._order_link` CHECK).
            "order_id": _require_text(entry.get("order_id"), "주문 ID"),
            "memo": entry.get("memo"),
        })

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(LEDGER_TABLE).insert(chunk), "매수 원장 기록")
        inserted += len(chunk)
    return inserted


def upsert_position_weighted_average(service_client, account_id, ticker, stock_name,
                                     existing_position, filled_quantity, fill_price):
    """
    (배치 전용) 매수 체결 1건을 포지션에 반영합니다(가중평균 평단가 갱신). 2-4-6 참고.

    ⚠️ **평단가 계산은 여기서 하지 않습니다.** `duel_rules.apply_buy_fill_to_position()` 이
       `holdings` 와 **같은 규칙**으로 계산하고, 이 함수는 그 결과를 담아 보낼 뿐입니다.
       (같은 규칙을 두 번 구현하면 "내 성적표"의 평단가와 결투 평단가가 언젠가 갈라집니다.)

    인자
        existing_position : 기존 포지션 행 dict 또는 None(신규). None 이면 규칙 함수에
                            수량·평단가를 **둘 다** None 으로 넘깁니다 — 한쪽만 아는 상태는
                            복원 불가라 규칙 계층이 예외로 막습니다.

    반환: 저장된 포지션 행 dict.
    """
    _require_client(service_client, batch=True)
    existing = existing_position or {}
    updated = duel_rules.apply_buy_fill_to_position(
        existing.get("quantity") if existing else None,
        existing.get("avg_cost") if existing else None,
        filled_quantity,
        fill_price,
    )
    rows = upsert_positions(service_client, [{
        "account_id": _require_text(account_id, "계좌 ID"),
        "ticker": _require_text(ticker, "종목코드"),
        "stock_name": _require_text(stock_name, "종목명"),
        "quantity": updated["quantity"],
        "avg_cost": updated["avg_cost"],
    }])
    return _first_row(rows, "포지션 갱신")


def upsert_positions(service_client, rows):
    """
    (배치 전용) 포지션 여러 개를 **한 번의 upsert** 로 저장합니다(§0-3-2 — 2-7 이 명시적으로
    요구하는 `insert ... on conflict (account_id, ticker) do update` 모양).

    반환: 저장된 행 목록.

    ⚠️ 같은 (계좌, 종목)이 한 요청에 두 번 들어오면 PostgREST 가 요청 전체를 거절합니다.
       그 경우 그날 포지션이 통째로 안 들어가므로 **먼저 잡아** 어느 키가 겹쳤는지 알립니다.
    ⚠️ 수량을 줄이는 값은 보내지 마세요. 이 모듈에 매도는 없고, `duel_positions_no_sell`
       트리거가 DB 에서 막습니다(관리 경로만 세션 변수로 예외).
    """
    _require_client(service_client, batch=True)
    payload = [dict(row) for row in (rows or [])]
    if not payload:
        return []
    _assert_unique_keys(payload, ("account_id", "ticker"), "포지션 저장 요청")

    saved = []
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        saved.extend(_execute(
            service_client.table(POSITIONS_TABLE).upsert(chunk, on_conflict="account_id,ticker"),
            "포지션 저장",
        ))
    return [dict(row) for row in saved]


# -----------------------------------------------------------------------------
# B-5. 크롤링 실패일 처리 (2-4-5 / 2-5 의 1번 단계)
# -----------------------------------------------------------------------------
def expire_or_cancel_all_pending_for_date(service_client, target_date, reason,
                                          *, status=ORDER_CANCELLED):
    """
    (배치 전용) 그 거래일에 귀속된 **모든 계좌의** pending 주문을 한 번에 실패 처리합니다.
    반환: 실제로 바뀐 행 수.

    언제 부르는가: `duel_rules.check_crawl_freshness()` 의 판정이 `'ok'` 가 아닐 때
    (= `crawl_status_allows_fill()` 이 False). 그날은 **체결 단계 전체를 건너뛰고**(부분
    체결 금지) 귀속 주문을 전부 정리합니다. 다음 성공일로 **이월하지 않습니다**(2-4-5).

    왜 이월하지 않는가(오너 확정): 이월하면 사용자는 자기가 낸 주문이 **며칠 뒤 모르는
    가격에** 체결되는 상황을 맞습니다. 실패를 명확히 남기고 다시 주문하게 하는 편이 정직합니다.
    그래서 `fail_reason` 은 필수이고 비워 둘 수 없습니다.

    ── 집합 연산 ──────────────────────────────────────────────────────────────────
    주문이 몇 건이든 **update 질의 1개**입니다. `.eq(status,'pending').eq(target_date, D)` 로
    한 번에 걸러 같은 값을 씁니다(모든 행에 같은 사유를 쓰므로 행별 분기가 필요 없습니다).
    `tests/test_duel_db.py` 가 호출 횟수를 고정합니다.

    ⚠️ 기본 상태를 `cancelled` 로 둔 이유: `duel_rules.allocate_pending_orders()` 도 종가를
       모르는 종목을 `cancelled` 로 돌려줍니다. "가격을 몰라서 안 된 것"의 표현을 한 가지로
       통일해야 화면이 두 경로를 같은 문구로 설명할 수 있습니다. `expired` 는 "예수금으로
       1주도 못 샀다"는 **다른 사실**을 가리키므로 여기 기본값이 아닙니다.
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
        service_client.table(ORDERS_TABLE)
        .update({"status": status, "fail_reason": text})
        .eq("status", ORDER_PENDING).eq("target_date", day),
        "미체결 주문 일괄 정리",
    )
    return len(rows)


# -----------------------------------------------------------------------------
# B-6. 일별 스냅샷 적재 (2-5 의 4번 단계 / 1-5)
# -----------------------------------------------------------------------------
def _validate_daily_snapshot(row, snapshot_date_iso):
    """
    스냅샷 합계 행 1건의 아귀를 보내기 전에 맞춥니다(스키마 §5 의 CHECK 들과 같은 규칙).

    특히 `total_value = position_value + cash_balance` 는 DB 가 십진수로 정확히 비교합니다.
    여기서 먼저 보지 않으면, 어긋난 행 하나 때문에 **그날 전체 upsert 가 거절**되고
    로그에는 제약 이름만 남습니다.
    """
    required = ("account_id", "position_value", "cash_balance", "total_value",
                "total_cost", "cash_flow_amount", "priced_count", "unpriced_count")
    missing = [field for field in required if row.get(field) is None]
    if missing:
        raise DuelDbError(f"스냅샷 행에 값이 없습니다: {missing} (계좌={row.get('account_id')!r})")

    given_date = row.get("snapshot_date")
    if given_date is not None and _iso_date(given_date, "스냅샷 날짜") != snapshot_date_iso:
        raise DuelDbError(
            f"스냅샷 행의 날짜({given_date})가 적재 날짜({snapshot_date_iso})와 다릅니다"
            " — 한 번의 적재는 하루치입니다(섞이면 어느 날 값인지 알 수 없게 됩니다)."
        )

    position_value = float(row["position_value"])
    cash_balance = float(row["cash_balance"])
    total_value = float(row["total_value"])
    if abs(total_value - (position_value + cash_balance)) > 1e-6:
        raise DuelDbError(
            f"총자산이 평가액+현금과 다릅니다(계좌={row.get('account_id')}):"
            f" {total_value} ≠ {position_value} + {cash_balance}."
            " 총자산은 따로 계산한 값이 아니라 두 관측값의 합이어야 합니다."
        )

    cash_flow = float(row["cash_flow_amount"])
    kind = row.get("cash_flow_kind")
    if (cash_flow > 0) != bool(kind):
        raise DuelDbError(
            f"현금흐름 금액과 종류가 짝이 맞지 않습니다(계좌={row.get('account_id')}):"
            f" amount={cash_flow}, kind={kind!r}."
            " '입금은 있었는데 무슨 입금인지 모름'은 나중에 사람이 해석할 수 없습니다."
        )
    if int(row["priced_count"]) <= 0 and position_value != 0:
        raise DuelDbError(
            f"그날 가격을 하나도 모르는데 평가액이 {position_value} 입니다"
            f" (계좌={row.get('account_id')}) — 모르는 가격을 0 이나 추정으로 채우지 않습니다(§0-1)."
        )


def _validate_holding_snapshot(row, snapshot_date_iso):
    """종목별 스냅샷 1건. '가격 모름'의 표현을 한 가지로 못 박습니다(priced ⟺ 두 값 존재)."""
    for field in ("ticker", "quantity", "avg_cost", "cost"):
        if row.get(field) is None:
            raise DuelDbError(f"종목별 스냅샷에 {field} 가 없습니다: {row!r}")
    if "priced" not in row:
        raise DuelDbError(
            f"종목별 스냅샷에 priced 가 없습니다: {row!r}"
            " — '그날 이 종목 가격을 알았는가'는 추측하지 않고 반드시 기록합니다."
        )
    priced = bool(row.get("priced"))
    has_price = row.get("close_price") is not None and row.get("market_value") is not None
    if priced != has_price:
        raise DuelDbError(
            f"priced={priced} 인데 close_price/market_value 가 {row.get('close_price')!r}/"
            f"{row.get('market_value')!r} 입니다({row.get('ticker')})."
            " 가격을 모르면 두 값 모두 NULL 이어야 합니다 — 0 으로 채우면 다음 날 가격이"
            " 들어오는 순간 '하루 만에 폭등'처럼 보이는 가짜 수익률이 생깁니다(§0-1)."
        )
    given_date = row.get("snapshot_date")
    if given_date is not None and _iso_date(given_date, "스냅샷 날짜") != snapshot_date_iso:
        raise DuelDbError(
            f"종목별 스냅샷의 날짜({given_date})가 적재 날짜({snapshot_date_iso})와 다릅니다."
        )


def write_daily_snapshots(service_client, snapshot_date, computed_rows):
    """
    (배치 전용) **이미 계산된** 하루치 스냅샷을 저장합니다. 반환값은 없습니다.

    이 함수는 아무것도 계산하지 않습니다 — 평가금액·현금흐름·TWR 입력은 호출부(배치)가
    `duel_rules` 와 원장·포지션·종가로 만들어 넘깁니다. 여기서 한 번 더 계산하면 "두 개의
    정답"이 생깁니다.

    `computed_rows` 의 모양(계좌 1개당 1개):
        {
          "account_id": ..., "position_value": ..., "cash_balance": ..., "total_value": ...,
          "total_cost": ..., "cash_flow_amount": ..., "cash_flow_kind": 'seed'|'monthly_deposit'
                                                        |'mixed'|None,
          "priced_count": ..., "unpriced_count": ..., "price_as_of_kst": ... (선택),
          "holdings": [ {"ticker", "stock_name", "quantity", "avg_cost", "cost",
                         "close_price"|None, "market_value"|None, "status", "priced",
                         "price_as_of_kst"}, ... ]     # 없으면 종목별 표에 아무것도 안 씁니다
        }

    `snapshot_date` 는 **인자 하나가 단일 출처**입니다. 행마다 날짜를 따로 넣어 보내면 하루
    적재에 두 날짜가 섞일 수 있어, 행에 날짜가 있으면 인자와 같은지 검사만 하고 값은
    인자 것으로 씁니다.

    ── 저장 순서와 원자성 ────────────────────────────────────────────────────────
    Supabase REST 에는 여러 표에 걸친 트랜잭션이 없습니다. `report_db.save_holding_snapshots()`
    가 정리한 규칙을 그대로 따릅니다: **합계 먼저, 종목별 나중.** 합계가 실패하면 예외가 나서
    종목별까지 가지도 않으므로 "종목별은 있는데 합계가 없는 날"은 생기지 않습니다. 반대
    (합계만 있고 종목별이 없는 날)는 생길 수 있고, 그쪽이 안전한 방향입니다. 둘 다 upsert 라
    다음 실행이 같은 날짜를 그대로 다시 채웁니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(snapshot_date, "스냅샷 날짜")
    rows = list(computed_rows or [])
    if not rows:
        # 저장할 게 없는 것은 오류가 아닙니다(참여자가 아직 없는 날). 조용히 끝냅니다.
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
            service_client.table(DAILY_SNAPSHOTS_TABLE).upsert(
                daily_payload[start:start + CHUNK_SIZE], on_conflict="account_id,snapshot_date"),
            "일별 스냅샷 저장",
        )
    for start in range(0, len(holding_payload), CHUNK_SIZE):
        _execute(
            service_client.table(HOLDING_SNAPSHOTS_TABLE).upsert(
                holding_payload[start:start + CHUNK_SIZE],
                on_conflict="account_id,ticker,snapshot_date"),
            "종목별 스냅샷 저장",
        )
    return None


# #############################################################################
#
#  C 절 — 아직 만들지 않은 것 (5단계 · 공개 인프라)
#
#  🔴 여기에는 코드가 없습니다. 스텁조차 두지 않았습니다 — "절반 열린 문"이 §0-3-8 에서
#     가장 위험한 모양이기 때문입니다. 아래는 **어디에 무엇이 들어올지**의 메모입니다.
#
#  TODO(작업지시서 5-5): 무작위 닉네임 생성·저장(`duel_nicknames`). user_id·이메일·가입시각
#      에서 유도하지 않는 순수 난수 + unique 충돌 시 재시도. 해시도 금지(역조회 가능).
#  TODO(작업지시서 5-3): 체급(원금 구간) 배정. `consent_real_principal_bracket` 이 true 인
#      계좌에 대해서만 "내 성적표"의 매입원가합계를 읽습니다. false 인 계좌의 holdings 를
#      읽는 코드 경로가 하나라도 생기면 §0-3-8 위반입니다. 체급은 시즌(1년) 단위로 고정.
#  TODO(작업지시서 5-4): 발행 배치 — `duel_public_leaderboard` / `duel_public_holdings` 에
#      **동의한 항목만** 채워 전량 재작성. 동의 없는 필드는 NULL(0·빈 문자열 금지).
#      순위는 `rank() over (...)` 로 배치가 미리 계산해 저장(화면 로드 시 계산 금지 — §0-3-2).
#  TODO(작업지시서 5-6): 최소 인원(500명) 미달 구간은 발행하지 않고, 이미 발행된 행도 제거.
#  TODO(작업지시서 5-8): 동의 철회 — 발행 기록 영구 삭제 + 3개월 재동의 차단(앱·배치 양쪽).
#
#  그리고 이 파일 범위 밖:
#  TODO(작업지시서 2-8 / 2-5): `web/pages/duel_page.py`(NiceGUI 화면, 기본 숨김 DUEL_ENABLED),
#      `.github/workflows/duel_daily.yml`(야간 배치), `main.py` 배선.
#
# #############################################################################


# =============================================================================
#  회귀 방어용 자기 점검 — "사용자 경로가 체결 결과를 쓸 수 있게" 되는 순간 잡히도록
# =============================================================================
#: A 절에서 사용자가 부르는 쓰기 함수. `tests/test_duel_db.py` 가 이 목록의 시그니처를
#: 검사해서, 나중에 누가 여기에 체결 결과 인자를 늘리면 **테스트가 먼저 실패**합니다.
#:
#: `opt_in` 도 목록에 있습니다. 지금은 인자가 클라이언트 하나뿐이지만, 나중에 누가
#: "관리자가 대신 참여시키는 기능"을 만들려고 `opt_in(client, user_id=...)` 나
#: `opt_in(client, seed_amount=...)` 를 붙이는 순간 그 함수의 안전성 근거(대상은 auth.uid()
#: 뿐, 금액은 DB 상수)가 무너집니다 — 아래 금지 목록이 그 시도를 먼저 잡습니다.
USER_WRITE_FUNCTIONS = ("opt_in", "save_order", "edit_order", "cancel_order", "save_consent")

#: 사용자 경로가 절대 인자로 받으면 안 되는 이름들(스키마 §3-1 트리거가 막는 것과 같은 집합).
#:  · `user_id` 가 여기 있는 이유(2026-08-20 추가): 이 절의 쓰기 함수는 **"누구의 것인지"를
#:    인자로 받지 않습니다.** 대상은 항상 로그인 세션(`auth.uid()`) 아니면 소유권이 이미
#:    확인된 계좌/주문 ID 입니다. 사용자 ID 를 인자로 받기 시작하면 "남의 ID 를 넣으면
#:    어떻게 되지"라는 질문이 생기고, 그 질문이 생기지 않게 하는 것이 이 설계의 핵심입니다.
FORBIDDEN_USER_WRITE_PARAMS = (
    "filled_price", "filled_quantity", "filled_amount", "filled_date",
    "target_date", "status", "seed_amount", "amount", "avg_cost", "quantity",
    "user_id",
)


def user_write_signature_violations():
    """
    A 절 쓰기 함수들이 금지된 인자를 받고 있지 않은지 스스로 점검합니다.

    테스트에서만 쓰는 함수를 왜 본 파일에 두는가: 금지 목록의 단일 출처를 코드 쪽에 두기
    위해서입니다. 테스트 파일에만 적어 두면 "테스트가 아는 규칙"이 되고, 이 파일을 고치는
    사람은 그 규칙을 못 봅니다. 여기 있으면 함수 바로 아래에서 읽힙니다(§0-3-10).
    """
    violations = []
    for name in USER_WRITE_FUNCTIONS:
        function = globals().get(name)
        if function is None:
            violations.append(f"{name}: 함수가 없습니다")
            continue
        params = set(inspect.signature(function).parameters)
        for forbidden in FORBIDDEN_USER_WRITE_PARAMS:
            if forbidden in params:
                violations.append(f"{name}({forbidden})")
    return violations
