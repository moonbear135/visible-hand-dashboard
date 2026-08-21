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

# 🔴 "내 성적표"(실제 자산) 모듈. **오직 표 이름 하나**(`HOLDINGS_TABLE`)를 위해 import
#    합니다 — 체급(원금 구간) 산정에 실제 매입원가합계가 필요하기 때문입니다(5-3).
#    표 이름을 여기 문자열로 다시 적으면, 저쪽에서 이름을 바꾸는 날 이 배치만 조용히
#    빈 결과를 받습니다(§0-3-10).
#    ⚠️ 이 import 는 **B 절의 `fetch_real_principal_holdings()` 한 함수**를 위한 것이고,
#       그 함수는 `consent_real_principal_bracket` 에 동의한 사용자 id 를 **필수 인자**로만
#       받습니다. A 절(사용자 세션)에는 `holdings` 를 건드리는 코드가 하나도 없습니다.
from utils import scorecard_db
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

# 🔴 발행 전용 공개표 2개 + 체급 배정 기록 (2026-08-20 · 5단계에서 추가).
#
#    ⚠️ 이 세 이름은 **B 절(배치·service_role)에서만** 쓰입니다. A 절(사용자 세션)에는
#       이 표를 건드리는 함수가 하나도 없어야 하고, `tests/test_duel_publish.py` 의 AST
#       검사가 그것을 고정합니다. 발행표에는 사용자에게 select 권한밖에 없고
#       (스키마 §9-8 · §9-9), 체급 배정은 아무에게도 쓰기 권한이 없습니다(§8-3).
#
#    ⚠️ 2026-08-20 이전 이 자리에는 "5단계 전까지 이름조차 적지 않는다"는 주석이 있었습니다.
#       그 단계가 지금이라 상수를 놓습니다 — 다만 **쓰는 자리를 B 절 한 곳으로 묶는** 규율은
#       그대로 유지합니다(§0-3-8 은 조심이 아니라 구조를 요구합니다).
PUBLIC_LEADERBOARD_TABLE = "duel_public_leaderboard"
PUBLIC_HOLDINGS_TABLE = "duel_public_holdings"
BRACKET_ASSIGNMENTS_TABLE = "duel_bracket_assignments"

#: 옵트인 RPC 의 이름. `sql/duel_schema.sql` §9-10 의 함수 이름과 **문자 그대로** 같아야
#: 합니다(표 이름 상수들과 같은 규약).
#:
#: 왜 표가 아니라 RPC 인가: 옵트인은 계좌 3행 + **현금 원장 3행**을 함께 만드는 일인데,
#: 현금 원장은 사용자 세션이 직접 쓸 수 없는 표입니다(스키마 §9-4 — 열어 주면 공개된
#: anon key 로 자기 계좌에 가상 현금을 무한히 찍을 수 있습니다). 그래서 DB 안에 **인자가
#: 하나도 없고 `auth.uid()` 로만 동작하는 좁은 저장 프로시저**를 두고, 앱은 사용자 본인
#: 세션으로 그것만 호출합니다. 자세한 근거는 스키마 §9-10 주석과 아래 `opt_in()` 참고.
OPT_IN_RPC = "duel_opt_in"

#: 🔴 리밸런싱 매도 정산 RPC 의 이름(2026-08-21 추가). `sql/duel_schema.sql` §9-11 의 함수
#: 이름과 **문자 그대로** 같아야 합니다.
#:
#: 왜 표 upsert 가 아니라 RPC 인가: `duel_positions` 의 수량 감소는 트리거가 막고 있고,
#: 매도 정산만은 **같은 트랜잭션에서** `set local duel.settled_sell = 'on'` 이 먼저 실행됐을
#: 때 통과합니다. 그런데 PostgREST 는 요청 하나가 곧 트랜잭션 하나라서, 클라이언트가 임의의
#: 세션 변수를 앞세워 보낼 문법이 **없습니다**(PostgREST 가 심어 주는 값은 role·
#: request.jwt.claims·request.headers 처럼 정해진 것뿐이고, `db-pre-request` 는 서버 전역
#: 설정이라 "모든 요청에 항상 켜짐"이 되어 트리거가 무의미해집니다). 그래서 "플래그 켜기 +
#: 수량 줄이기"를 한 호출로 묶은 좁은 함수를 DB 안에 두고, 배치가 그것만 부릅니다.
#: 자세한 근거와 이 함수가 스스로를 좁게 유지하는 장치 넷은 스키마 §9-11 주석에 있습니다.
SETTLE_SELL_RPC = "duel_settle_sell_positions"

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


def _require_offset(value, label):
    """
    페이지네이션의 `offset` 검증(0 이상 정수). `_require_positive_int()` 와 짝이지만 **0 을
    허용**한다는 점만 다릅니다 — 첫 페이지의 offset 은 0 이라 위 함수를 쓸 수 없습니다.

    ⚠️ 음수·소수를 0 으로 조용히 보정하지 않습니다. 보정하면 "2페이지를 눌렀는데 1페이지가
       나오는" 조용한 오작동이 되고, 사용자는 그 사실을 알 수 없습니다(§0-1).
    """
    if value is None or isinstance(value, bool):
        raise DuelDbError(f"{label}가 올바르지 않습니다: {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DuelDbError(f"{label}는 정수여야 합니다: {value!r}") from exc
    if isinstance(value, float) and number != value:
        raise DuelDbError(f"{label}는 정수여야 합니다(소수 불가): {value!r}")
    if number < 0:
        raise DuelDbError(f"{label}는 0 이상이어야 합니다: {value!r}")
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


def _filter_is_null(query, column):
    """
    `where <column> is null` 필터. PostgREST 의 `.filter(col, "is", "null")` 형태를 씁니다.

    `.is_()` 대신 `.filter()` 를 쓰는 이유: NULL 아님(`not.is`)까지 한 가지 방법으로 표현할
    수 있어서, 두 조건이 **같은 모양**으로 읽히기 때문입니다(클라이언트 버전에 따라
    `.not_.is_()` 체인의 유무가 갈리는 것도 피합니다).
    """
    return query.filter(column, "is", "null")


def _filter_not_null(query, column):
    """`where <column> is not null` 필터. 위 함수와 짝입니다."""
    return query.filter(column, "not.is", "null")



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


def save_sell_order(client, account_id, ticker, stock_name, requested_quantity,
                    held_quantity, window_index, *, trading_days, now_kst=None):
    """
    **창당 1회 리밸런싱 매도** 주문 1건을 저장합니다(`status='pending'`, `side='sell'`).
    2026-08-21 오너 확정 스펙 참고.

    `save_order()`(매수)의 매도판입니다 — 접수 시간대 판정, 체결 거래일(D+1) 계산,
    `saved_at` 을 판정에 쓴 바로 그 시각으로 저장하는 규약까지 **완전히 같습니다.**
    같은 시간대에 접수해 같은 D+1 종가로 체결되므로, 두 함수가 달라야 할 이유가 없습니다.
    아래 셋만 다릅니다.

      ① `side='sell'` + `rebalance_window_index=window_index`
         창 번호는 앱이 `duel_rules.resolve_rebalance_window()` 로 계산해 넘깁니다. DB 는
         이 값과 `unique (account_id, rebalance_window_index) where side='sell' and
         status <> 'cancelled'` 부분 유니크 인덱스로 **"창당 1회"를 직접 강제**합니다 —
         이 기능 전체에서 가장 중요한 제약입니다(화면 로직이 실수해도 두 번째 매도 주문
         저장이 DB 에서 거절됩니다).
      ② 저장 전에 `requested_quantity <= held_quantity` 를 확인합니다. 이건 **사용자에게
         친절한 사전 점검**이고, 최종 방어는 체결 시점의
         `duel_rules.calculate_sell_fill()` 예외입니다(§0-3-9 의 이중 방어).
      ③ **유니버스 검사를 하지 않습니다.** 매수는 코스피 상위 종목만 가능하지만, 이미
         보유한 종목이 그 목록에서 빠질 수 있고 그때 "팔 수도 없는" 상태가 되면 그게 더
         나쁩니다. 그래서 `universe_tickers` 인자 자체를 두지 않았습니다.

    ⚠️ **취소하면 그 창의 자리가 다시 열립니다.** 유니크 인덱스 조건이
       `status <> 'cancelled'` 이므로, 접수 시간대 안에서 `cancel_order()` 로 취소한 매도는
       같은 창에 다시 낼 수 있습니다. 반면 배치가 처리해 `filled` 또는 (종가 없음)
       `cancelled` 로 종결된 매도는 — 뒤쪽은 status 가 cancelled 라 인덱스상 자리가 열리지만,
       그날 이후 같은 창에 다시 주문할 수 있는지는 화면이 판단합니다. 이 함수는 창 번호를
       받아 그대로 적을 뿐, 기회가 남았는지를 스스로 판정하지 않습니다(판정은 규칙 계층과
       DB 인덱스의 몫 — 여기서 세 번째 판정 자리를 만들지 않습니다).

    ⚠️ `held_quantity` 는 **호출부가 조회한 보유 수량**입니다. 이 함수가 포지션 표를 읽지
       않는 이유는 A 절 규약과 같습니다(사용자 세션은 포지션을 읽을 수 있지만, 그 조회를
       여기서 또 하면 화면이 이미 갖고 있는 값과 두 번째 출처가 생깁니다).

    인자
        requested_quantity : 팔려는 수량(1주 ~ 전량).
        held_quantity      : 지금 보유 수량(화면이 조회해 넘깁니다).
        window_index       : `resolve_rebalance_window()['window_index']`.
        trading_days       : 확정된 거래일 목록/집합. **필수**(§0-1 — 지어내지 않습니다).
        now_kst            : 판정 기준 시각(KST). 테스트·재현용.

    반환: 저장된 주문 행 dict.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    code = _require_text(ticker, "종목코드")
    name = _require_text(stock_name, "종목명")
    quantity = _require_positive_int(requested_quantity, "매도 수량")
    held = _require_positive_int(held_quantity, "보유 수량")
    window = _require_offset(window_index, "리밸런싱 창 번호")   # 0 부터 시작하므로 0 허용

    if quantity > held:
        raise DuelDbError(
            f"보유 수량({held}주)보다 많은 {quantity}주는 매도할 수 없습니다."
            " 보유한 수량 이하로 다시 입력해 주세요."
        )

    moment = _now_kst(now_kst)
    window_state = duel_rules.resolve_order_window(moment)
    if not window_state["is_open"]:
        opens = window_state["window_opens_at"]
        closes = window_state["window_closes_at"]
        raise DuelDbError(
            "지금은 주문 접수 시간이 아닙니다 — "
            f"{opens.strftime('%Y-%m-%d %H:%M:%S')} 부터 {closes.strftime('%H:%M:%S')} 까지"
            " 접수합니다(한국시간)."
            " 매도도 매수와 같은 시간대에 접수하고, 체결은 다음 거래일의 확정 종가로"
            " 이루어집니다."
        )

    target_date = duel_rules.resolve_fill_trading_day(moment, trading_days)

    payload = {
        "account_id": account,
        "ticker": code,
        "stock_name": name,
        "requested_quantity": quantity,
        "side": "sell",
        "status": ORDER_PENDING,
        "saved_at": moment.isoformat(),
        "target_date": target_date.isoformat(),
        # 창당 1회를 DB 가 강제하는 근거값. 매수 주문은 여기가 NULL 이어야 하고,
        # 매도 주문은 NULL 이면 안 됩니다(`duel_orders_rebalance_window_match` CHECK).
        "rebalance_window_index": window,
    }
    try:
        rows = _execute(client.table(ORDERS_TABLE).insert(payload), "매도 주문 저장")
    except DuelDbError as exc:
        if _is_duplicate_key_error(exc):
            # 부분 유니크 인덱스가 두 번째 매도를 막은 것 — 사고가 아니라 규칙이 제 일을
            # 한 것이므로, Postgres 원문 대신 사람이 읽을 문장으로 바꿔 올립니다(§0-3-4).
            raise DuelDbError(
                "이번 리밸런싱 창에서는 이미 매도 주문을 한 번 사용했습니다"
                " (창마다 딱 1회만 가능하고, 놓친 기회는 누적되지 않습니다)."
                " 기존 주문을 접수 시간대 안에서 취소하면 이 창의 기회가 다시 열립니다."
            ) from exc
        raise
    return _first_row(rows, "매도 주문 저장")


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

    ④ **철회 후 3개월 재동의 차단**(5-8-2, 2026-08-20 추가). 저장을 시작하기 전에 이 계좌의
       기존 동의 행을 한 번 읽어 `revoked_at` 을 확인하고, 아직 3개월이 안 지났으면 **언제
       풀리는지 날짜까지 적힌 한국어 오류**로 거절합니다. 화면만 막으면 안 된다는 것이
       5-8-2 의 명문이라 저장 경로인 여기에 둡니다(발행 배치 쪽은
       `utils/duel_publish.py` 가 `final_confirmed=true and revoked_at is null` 로 한 번 더
       거릅니다 — 앱·배치 양쪽 확인).
       ⚠️ 판정 자체는 이 파일이 하지 않습니다. `duel_rules.resolve_reconsent_block()` 이
          "3개월"이라는 숫자와 경계 규칙의 단일 출처입니다(§0-3-10).

    ⚠️ 철회 **저장**은 이 함수가 아니라 `revoke_consent()` 입니다(바로 아래). 한 함수가
       "켜기"와 "끄기"를 둘 다 하면, 나중에 누가 `save_consent(..., revoked_at=None)` 같은
       인자를 붙여 철회를 되돌리는 경로를 만들게 됩니다.

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

    # 5-8-2 — 철회 후 3개월 동안은 어떤 동의 저장도 진행하지 않습니다(아래 함수 참고).
    #  ⚠️ 순서가 중요합니다: **입력 검증을 전부 마친 뒤**에 조회합니다. 오타나 잘못된
    #     값처럼 저장 자체가 불가능한 요청 때문에 DB 를 왕복하지 않기 위해서입니다.
    _assert_reconsent_allowed(client, account)

    rows = _execute(
        client.table(CONSENT_TABLE).upsert(payload, on_conflict="account_id"),
        "공개 동의 저장",
    )
    return _first_row(rows, "공개 동의 저장")


# -----------------------------------------------------------------------------
# A-4. 동의 철회 + 3개월 재동의 차단 (작업지시서 5-8) — 2026-08-20 추가
# -----------------------------------------------------------------------------
def fetch_my_consent(client, account_id):
    """
    본인 계좌의 공개 동의 행 1개(없으면 None). 화면이 체크박스 상태를 그릴 때,
    그리고 아래 두 함수가 철회 이력을 확인할 때 씁니다.

    ⚠️ 없는 것과 실패한 것은 다릅니다 — 질의가 실패하면 `_execute()` 가 예외를 냅니다.
       "행이 없다"만 None 입니다(§0-1).
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")
    rows = _execute(
        client.table(CONSENT_TABLE).select("*").eq("account_id", account).limit(1),
        "공개 동의 조회",
    )
    return dict(rows[0]) if rows else None


def _assert_reconsent_allowed(client, account_id, *, now_kst=None):
    """
    철회 후 **3개월 재동의 차단**(5-8-2)을 저장 경로에서 강제합니다.

    왜 앱에서도 막는가: 5-8-2 는 "애플리케이션과 배치 **양쪽에서** 확인하세요. 화면만 막으면
    배치가 되살립니다"라고 명시합니다. 여기가 그 '애플리케이션' 쪽입니다.
    (DB 쪽은 `duel_consent_guard()` 트리거가 "철회 기록 자체를 지우는 것"을 막고,
     발행 쪽은 `utils/duel_publish.py` 가 철회된 계좌를 발행 대상에서 거릅니다.)

    ⚠️ 3개월이라는 숫자와 경계 규칙(정확히 3개월이 되는 순간 풀림)은 이 파일이 정하지
       않습니다 — `duel_rules.resolve_reconsent_block()` 이 단일 출처입니다(§0-3-10).
    ⚠️ 사용자에게 **언제 풀리는지 날짜를 알려 줍니다.** "지금은 안 됩니다"만 말하면 사용자는
       며칠마다 다시 눌러 보게 되고, 그건 우리가 정보를 숨긴 것입니다(§0-1 / §0-3-4).
    """
    existing = fetch_my_consent(client, account_id)
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


def revoke_consent(client, account_id, *, now_kst=None):
    """
    공개 동의를 **철회**합니다(`duel_public_consent.revoked_at` 기록). 작업지시서 5-8 참고.

    ── 이 함수가 하는 일 / 하지 않는 일 ──────────────────────────────────────────
    하는 일: 동의 행에 `revoked_at` 을 찍고, `final_confirmed` 와 항목별 동의 7개를 전부
             끕니다. 그 결과 이 계좌는 **다음 발행 대상에서 즉시 빠집니다.**
    하지 않는 일: **행을 지우지 않습니다**(5-8-3). `revoked_at` 한 줄은 3개월 재동의 차단을
             판정하는 데 필요한 **비공개 관리 기록**이고, 삭제 대상인 "발행된 공개 기록"과는
             다른 것입니다. 스키마 §7 의 컬럼 주석에도 같은 구분이 적혀 있습니다.
    하지 않는 일 ②: **이미 발행된 공개 행을 지우지 않습니다.** 그건 야간 배치만 할 수 있는
             일이라(발행표에는 사용자 쓰기 권한이 아예 없습니다 — 스키마 §9-8),
             `utils/duel_publish.py::purge_revoked_accounts()` 가 야간 배치에서 처리합니다.
             ⚠️ 즉 **철회 시점과 공개 기록이 실제로 사라지는 시점 사이에 최대 하루의 간격이
                있습니다.** 이 사실을 화면에 그대로 써야 합니다(§0-1 — 조용히 넘기지 않기).
                즉시 삭제가 필요한지는 오너 결정 사항입니다(작업 보고 (h) 참고).

    ── 왜 항목별 동의 5개 + 실제 매입총합 동의까지 함께 끄는가 ────────────────────
    DB CHECK(`duel_consent_revoked_not_confirmed`)는 "철회 + 최종확인"이 동시에 서지
    못하게만 합니다. 5개 항목은 그대로 true 로 남길 수도 있는데, 그러면 남은 상태가
    "최종확인 직전까지 다 체크한 사람"과 **글자 그대로 같아집니다** — 화면이 그 상태를
    "동의 중"으로 그릴 위험이 있고, 나중에 어떤 코드가 `final_confirmed` 하나만 켜면
    `duel_consent_final_requires_all` CHECK 를 그냥 통과해 버립니다. 전부 꺼 두면 그
    실수는 CHECK 에 걸려 막힙니다(§0-3-9 — 조심이 아니라 구조로).
    `consent_real_principal_bracket` 도 끕니다 — 철회한 사용자의 실제 `holdings` 를 읽을
    이유가 하나도 남지 않게 하기 위해서입니다(5-3 / §0-3-8).

    ── 두 번 눌러도 안전합니다(멱등) ─────────────────────────────────────────────
    이미 철회된 계좌면 **아무것도 쓰지 않고** 기존 행을 그대로 돌려줍니다. `revoked_at` 을
    지금 시각으로 다시 찍으면 3개월 차단이 그만큼 **연장**되는데, 그건 사용자가 버튼을 두 번
    눌렀다는 이유로 불이익을 주는 일입니다.

    반환: 갱신된(또는 이미 철회된) 동의 행 dict.
    """
    _require_client(client)
    account = _require_text(account_id, "계좌 ID")

    existing = fetch_my_consent(client, account)
    if not existing:
        raise DuelDbError(
            "이 계좌에는 철회할 공개 동의 기록이 없습니다"
            " (아직 공개 순위표에 참여한 적이 없습니다)."
        )
    if existing.get("revoked_at"):
        # 이미 철회됨 — 재기록하지 않습니다(위 '멱등' 문단 참고).
        return existing

    payload = {flag: False for flag in CONSENT_ITEM_FLAGS}
    payload[CONSENT_REAL_PRINCIPAL_FLAG] = False
    payload["final_confirmed"] = False
    payload["final_confirmed_at"] = None
    payload["revoked_at"] = _now_kst(now_kst).isoformat()

    rows = _execute(
        client.table(CONSENT_TABLE).update(payload).eq("account_id", account),
        "공개 동의 철회",
    )
    return _first_row(rows, "공개 동의 철회")


# -----------------------------------------------------------------------------
# A-5. 무작위 닉네임 만들기 (작업지시서 5-5 · 스키마 §6) — 2026-08-20 추가
# -----------------------------------------------------------------------------
#: 닉네임 후보를 다시 뽑아 보는 최대 횟수. 공간이 약 214만 가지나 되어서
#: (`duel_rules.nickname_space_size()`) 실제로는 첫 시도에서 끝납니다 — 이 숫자는
#: "무한 루프를 만들지 않는다"는 안전장치이지 성능 조절값이 아닙니다.
NICKNAME_MAX_ATTEMPTS = 8


def ensure_nickname(client, user_id, window_type):
    """
    이 (사용자, 창유형)의 공개용 **무작위 닉네임**을 보장합니다(없으면 만들고, 있으면 그대로).
    작업지시서 5-5 / 스키마 §6 참고.

    🔴 2026-08-20 USD 트랙(§5-11) 도입으로 인자가 `account_id` 하나에서 `(user_id,
       window_type)` 둘로 바뀌었습니다. 오너가 "같은 사용자면 원화·달러 트랙에서 같은
       닉네임을 쓰자"(5-11-10)를 확정하면서, 닉네임 표(§6)의 기본키 자체가 계좌 단위에서
       사용자×창유형 단위로 재구조화됐기 때문입니다 — 원화 계좌(duel_accounts)와 달러
       계좌(duel_accounts_usd)는 물리적으로 다른 표의 서로 다른 id 라, 계좌 id 하나만으로는
       "이 사용자의 이 창유형" 을 특정할 수 없습니다. **이 함수는 원화·USD 양쪽 동의 화면이
       그대로 공유해서 씁니다** — 어느 트랙에서 부르든 같은 (user_id, window_type) 이면
       같은 닉네임 행을 반환합니다.

    ── 언제 부르는가 (호출 시점이 설계의 일부입니다) ─────────────────────────────
    🔴 **2갈래(공개 순위표) 동의 화면에서, 첫 `save_consent()` 직전(또는 직후)에 한 번.**
       `opt_in()`(1갈래 참여)에 끼워 넣지 **않았습니다.** 이유:
         · 1갈래 "덤벼라 나 자신"은 혼자 쓰는 모의투자이고, 작업지시서도 "1갈래만 만들고
           배포해도 된다"고 적고 있습니다. 그 사용자에게는 **공개용 별명이라는 물건 자체가
           필요 없습니다.** 안 만들면 그 계좌는 공개 세계에 이름조차 존재하지 않습니다 —
           기본값은 비공개(5-1)라는 원칙의 가장 구체적인 형태입니다(§0-3-8).
         · 닉네임은 한 번 만들면 **바꿀 수 없습니다**(스키마 §9-6 에 update 정책이 없습니다).
           쓰지도 않을 사람에게 미리 발급하면, 나중에 그 사람이 공개에 참여할 때 예전에
           찍힌 이름을 그대로 써야 합니다.
       ⚠️ 반대로 **발행 배치가 닉네임을 만들지는 않습니다.** 배치는 권한상 만들 수는
          있지만, 그러면 "닉네임이 없는 참가자"를 배치가 조용히 메꾸게 되고 그 계좌가
          정말 동의했는지의 판단이 두 곳으로 갈라집니다. 닉네임이 없는 계좌를 만나면
          `utils/duel_publish.py` 는 **발행에서 빼고 그 사실을 로그에 남깁니다.**

    ── 유일성은 DB 가 판정합니다 ─────────────────────────────────────────────────
    "이미 쓰는 이름인가"를 앱이 먼저 조회해서 정하면, 조회와 삽입 사이에 다른 세션이 같은
    이름을 넣는 경합을 막을 수 없습니다. 그래서 **그냥 넣어 보고, unique 충돌이면 새 후보로
    다시 넣습니다**(스키마 §6 이 요구하는 "난수 → unique 충돌 시 재시도").

    ── 두 탭에서 동시에 눌러도 안전합니다 ────────────────────────────────────────
    `duel_nicknames` 의 기본키가 `(user_id, window_type)` 라, 두 번째 삽입은 충돌합니다.
    그때 이 함수는 "내 이름이 이미 생겼나"를 다시 확인하고 **그 이름을 돌려줍니다.** 새
    이름을 또 만들지 않습니다 — 이름이 둘이면 과거 발행 행과 대응이 끊깁니다(5-5 "재계산·재사용 금지").

    반환: `{"user_id": ..., "window_type": ..., "nickname": ..., ...}` dict.
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")
    window = _require_text(window_type, "창유형")

    existing = _fetch_nickname_row(client, user, window)
    if existing:
        return existing

    last_error = None
    for _attempt in range(NICKNAME_MAX_ATTEMPTS):
        # 🔴 후보는 인자 없는 순수 난수 함수가 만듭니다 — user_id·이메일·시각에서 유도하지
        #    않습니다(5-5). 여기서 user/window 를 섞어 넣고 싶은 유혹을 이기세요.
        candidate = duel_rules.generate_nickname()
        try:
            rows = _execute(
                client.table(NICKNAMES_TABLE).insert(
                    {"user_id": user, "window_type": window, "nickname": candidate}),
                "닉네임 생성",
            )
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise                       # 진짜 사고를 재시도로 덮지 않습니다(§0-1).
            last_error = exc
            # 충돌의 원인은 둘 중 하나입니다:
            #   ① (user_id, window_type) 기본키 — 다른 탭/요청·다른 통화 트랙이 방금
            #      내 이름을 만들었다 → 그걸 씁니다.
            #   ② nickname unique — 남이 쓰는 이름을 뽑았다 → 새 후보로 다시.
            already = _fetch_nickname_row(client, user, window)
            if already:
                return already
            continue
        if rows:
            return _first_row(rows, "닉네임 생성")
        # insert 가 0행을 돌려주는 경우(RLS 가 막은 남의 계좌 등)는 성공이 아닙니다.
        raise DuelDbError(
            "닉네임을 만들지 못했습니다(내 계좌가 아니거나 접근이 차단됐습니다)."
        )

    raise DuelDbError(
        f"닉네임 후보를 {NICKNAME_MAX_ATTEMPTS}번 만들었는데 전부 이미 쓰이는 이름이었습니다."
        " 임의의 이름을 억지로 붙이지 않고 중단합니다 —"
        f" 후보 공간({duel_rules.nickname_space_size():,}가지)이 참가자 수에 비해 좁아졌는지"
        f" 확인이 필요합니다. (마지막 오류: {last_error})"
    )


def fetch_my_nickname(client, user_id, window_type):
    """
    이 (사용자, 창유형)의 공개용 닉네임 행(없으면 None) — **만들지 않고 읽기만** 합니다.
    2026-08-20 추가(동의 관리 화면용). 인자는 `ensure_nickname()` 과 같은 이유로
    `(user_id, window_type)` 입니다(위 함수 docstring 참고 — §5-11-10).

    왜 `ensure_nickname()` 을 그대로 쓰지 않는가: 그 함수는 없으면 **만듭니다.** 화면을
    그리는 것만으로 닉네임이 발급되면, 동의 화면을 열어 보기만 하고 나간 사용자에게도
    공개용 별명이 생깁니다 — 5-5 가 발급 시점을 "옵트인 시가 아니라 5단계 동의 시"로 못
    박은 이유가 정확히 그것이고, 한 번 만든 닉네임은 바꿀 수 없습니다(스키마 §9-6 에
    update 정책이 없습니다). **화면을 그리는 행위는 아무것도 만들지 않아야 합니다.**
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")
    window = _require_text(window_type, "창유형")
    return _fetch_nickname_row(client, user, window)


def _fetch_nickname_row(client, user_id, window_type):
    """이 (사용자, 창유형)의 닉네임 행(없으면 None). 사용자 세션·배치 클라이언트 양쪽에서 같은 모양입니다."""
    rows = _execute(
        client.table(NICKNAMES_TABLE).select("*")
        .eq("user_id", user_id).eq("window_type", window_type).limit(1),
        "닉네임 조회",
    )
    return dict(rows[0]) if rows else None


# -----------------------------------------------------------------------------
# A-6. 발행표 **읽기 전용** 조회 (작업지시서 5-7 · 5-2) — 2026-08-20 추가
# -----------------------------------------------------------------------------
#  🔴 이 절에서 발행표(`duel_public_leaderboard` / `duel_public_holdings`)를 만지는
#     유일한 자리입니다. 그리고 **select 밖으로는 한 발짝도 나가지 않습니다.**
#
#     왜 A 절에 두는가: 순위표 화면은 로그인한 **일반 사용자**가 보는 화면이고, 이 두 표는
#     스키마 §9-7 에서 로그인 사용자(`authenticated`)에게 **select 만** 준 표입니다(insert/update/delete
#     정책은 아무에게도 없습니다). 즉 사용자 세션 클라이언트로 읽는 것이 정상 경로이고,
#     여기에 배치 키가 끼어들 이유가 하나도 없습니다. 반대로 이 조회를 B 절에 두면 화면이
#     B 절 함수를 부르게 되고, 그러면 앱 서버가 **RLS 를 우회하는 배치 키**를 갖게 됩니다
#     (§0-3-8). ⚠️ 그 키의 이름을 이 절에는 **주석에도** 적지 않습니다 — A 절 전체를
#     문자열로 훑는 `tests/test_duel_db.py` 의 격리 회귀 검사가 그것까지 실패로 잡습니다.
#     그 검사를 느슨하게 만들지 마세요(§0-3-9 — 조심이 아니라 구조로).
#
#     🔒 이 세 함수가 지키는 것(버그가 나도 새어나갈 수 없게 — 5-4-5 / §0-3-8):
#       ① **`select("*")` 를 쓰지 않습니다.** 읽는 컬럼을 하나하나 적습니다. 나중에 누가
#          발행표에 컬럼을 하나 더 붙여도, 이 함수가 그것을 화면으로 날라 주는 일은
#          없습니다. (발행표에는 애초에 식별자 컬럼이 없지만 — 스키마 §8 — 두 겹으로
#          막아 둡니다. §0-3-9 "조심이 아니라 구조로".)
#       ② 원본 표(`duel_positions` · `holdings` · `profiles` · `duel_cash_ledger`)를
#          **부르지 않습니다.** 이 두 함수의 호출부(순위표 화면)는 그 표의 이름조차 몰라도
#          됩니다(5-4-5).
#       ③ 순위를 **계산하지 않습니다.** 배치가 미리 계산해 넣은 `rank` 컬럼으로 정렬만
#          합니다(§0-3-2 / 5-7 — 방문자 수만큼 전체 스캔이 돌지 않게).
#
#     ⚠️ 이 표는 **날짜별 발행 이력이 쌓이는 표**입니다(5-4-4 는 "그날 발행분"을 통째로
#        갈아끼우지, 과거 날짜를 지우지 않습니다). 그래서 날짜를 지정하지 않고 읽으면
#        여러 날짜가 섞입니다. 화면은 `fetch_public_leaderboard_latest_date()` 로 **그
#        그룹의 최신 발행일을 한 번 확정한 뒤**, 그 날짜를 아래 두 함수에 명시적으로
#        넘깁니다(페이지를 넘기는 도중에 발행일이 바뀌어 목록이 뒤섞이는 것도 막습니다).
# -----------------------------------------------------------------------------
#: 순위표 화면에 실어 보내는 컬럼(위 ①). 이 목록에 `id` 를 넣지 마세요 — 화면에 쓸모가
#: 없고, 발행 순서(= 계좌 생성 순서와 상관관계가 생길 수 있는 값)를 노출합니다.
PUBLIC_LEADERBOARD_COLUMNS = "published_date,window_type,bracket_key,rank,nickname,twr_pct"

#: 공개 보유종목 화면에 실어 보내는 컬럼(위 ①).
PUBLIC_HOLDINGS_COLUMNS = "published_date,window_type,nickname,ticker,stock_name,quantity,buy_amount"


def fetch_public_leaderboard_latest_date(client, *, window_type, bracket_key):
    """
    이 그룹(창유형 × 체급)이 **가장 최근에 발행된 날짜**(`YYYY-MM-DD`) 또는 None.

    None 은 오류가 아니라 정상 상태입니다 — ① 아직 아무도 이 그룹에 없거나,
    ② 최소 인원(5-6)을 못 채워 발행되지 않았거나, ③ 발행됐다가 인원이 줄어
    5-6 청소로 지워진 경우입니다. 화면은 이 셋을 "아직 공개할 만큼 사람이 모이지
    않았습니다"로 **똑같이** 안내합니다 — 셋을 구분해 보여주면 그 자체가 "이 구간에 몇
    명쯤 있는지"에 대한 정보가 되고, 그건 소수 N 역추적의 재료입니다(5-6).

    질의 1개(`limit(1)`)입니다.
    """
    _require_client(client)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        client.table(PUBLIC_LEADERBOARD_TABLE).select("published_date")
        .eq("window_type", window).eq("bracket_key", bracket)
        .order("published_date", desc=True).limit(1),
        "공개 순위표 발행일 조회",
    )
    value = (rows[0] or {}).get("published_date") if rows else None
    return str(value)[:10] if value else None


def fetch_public_leaderboard(client, *, window_type, bracket_key, published_date=None,
                             limit=duel_rules.LEADERBOARD_PAGE_SIZE, offset=0,
                             order_desc=False):
    """
    발행된 공개 순위표 한 페이지를 읽습니다(작업지시서 5-7). 반환: 행 dict 목록.

    인자
        window_type    : "M1" / "M3" / "M6"
        bracket_key    : `duel_rules.BRACKET_KEYS` 중 하나(구간 미적용 포함)
        published_date : 발행일. **화면은 반드시 넘깁니다**
                         (`fetch_public_leaderboard_latest_date()` 로 먼저 확정).
                         None 이면 날짜를 가리지 않습니다 — 과거 이력을 통째로 훑어야 하는
                         관리 목적에만 쓰세요.
        limit / offset : 페이지네이션(기본 한 페이지 = `duel_rules.LEADERBOARD_PAGE_SIZE`).
                         "상위 500 / 하위 500"이라는 **구간 상한**은 화면이 아니라
                         `duel_rules.leaderboard_page_bounds()` 가 계산해 여기로 넘깁니다.
        order_desc     : False 면 1위부터(= 상위 500), True 면 꼴찌부터(= 하위 500).

    ── 왜 `order_desc` 가 필요한가 ───────────────────────────────────────────────
    "하위 500"을 얻으려면 전체 인원을 알아야 `offset` 을 계산할 수 있는데, 인원을 세는
    질의를 화면 로드마다 돌리는 것은 §0-3-2 가 막는 바로 그 모양입니다. 정렬 방향만
    뒤집으면 인원을 몰라도 꼴찌부터 500명을 정확히 읽을 수 있습니다(화면이 그 페이지를
    다시 뒤집어 보여줍니다).

    ── 동순위(같은 rank)와 페이지 경계 ──────────────────────────────────────────
    순위는 동점자가 **같은 값을 공유**합니다(`duel_rules.rank_participants()`). 정렬 키가
    `rank` 하나뿐이면 같은 rank 안의 순서가 질의마다 달라질 수 있고, 그러면 페이지를 넘길
    때 같은 사람이 두 번 나오거나 한 명이 통째로 건너뛰어집니다. 그래서 `nickname` 을
    **2차 정렬 키**로 함께 씁니다.
    ⚠️ 이건 순위를 다시 매기는 것이 **아닙니다.** 화면에 보이는 등수는 발행표의 `rank`
       그대로이고(동점자는 같은 등수로 보입니다), 닉네임 정렬은 "같은 등수 안에서 목록에
       찍히는 차례"를 고정하는 용도일 뿐입니다. 여기서 등수를 새로 만들면 그건 사실이
       아닌 정보를 발행하는 일입니다(§0-1).

    ── 🔴 스테이징에서 눈으로 확인할 것 두 가지 (작업지시서 6단계) ─────────────────
    이 샌드박스에는 `supabase` 패키지가 설치돼 있지 않아 **클라이언트 라이브러리의 실제
    동작**은 확인하지 못했습니다(§0-1 — 확인한 것만 확인했다고 적습니다). 스테이징에서
    두 가지만 눈으로 보세요:
      ① `.order()` 를 두 번 부르면 정렬 키가 **둘 다** 걸리는가(덮어쓰지 않는가).
         만약 덮어쓴다면 목록이 닉네임 순으로만 나옵니다 — 데이터가 새는 문제는 아니고
         "보이는 차례가 이상한" 문제라 화면만 보면 바로 압니다.
      ② `.range(start, end)` 가 **양끝을 포함하는** 구간인가(0-based). 2페이지의 첫 줄이
         1페이지의 마지막 줄과 겹치거나 한 줄 건너뛰면 여기가 원인입니다.
    """
    _require_client(client)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    count = _require_positive_int(limit, "조회 개수")
    start = _require_offset(offset, "건너뛸 개수")

    query = (client.table(PUBLIC_LEADERBOARD_TABLE).select(PUBLIC_LEADERBOARD_COLUMNS)
             .eq("window_type", window).eq("bracket_key", bracket))
    if published_date is not None:
        query = query.eq("published_date", _iso_date(published_date, "발행일"))
    query = (query.order("rank", desc=bool(order_desc))
                  .order("nickname", desc=bool(order_desc)))
    rows = _execute(query.range(start, start + count - 1), "공개 순위표 조회")
    return [dict(row) for row in rows]


def fetch_public_holdings_for_nickname(client, nickname, *, published_date=None,
                                       window_type=None):
    """
    한 참가자(닉네임)의 **발행된** 보유종목을 읽습니다 — 5-2 의 "보유종목이 순위표에서
    다른 사람에게 **개별 열람** 가능하게 공개됩니다"가 실제로 일어나는 자리입니다.

    인자
        nickname       : 순위표 행에서 사용자가 고른 닉네임(이 표에는 이 값 말고 사람을
                         가리키는 것이 아무것도 없습니다 — 스키마 §8).
        published_date : 그 순위표 행의 발행일. 화면은 반드시 넘깁니다(날짜를 안 걸면
                         과거 발행분까지 같이 나와 같은 종목이 여러 번 보입니다).
        window_type    : 그 순위표 행의 창유형(M1/M3/M6). 한 사람이 계좌 3개를 각각
                         공개했다면 닉네임은 계좌마다 다르지만(5-5 "계좌별로 저장"),
                         그래도 화면이 보고 있는 축을 그대로 걸어 둡니다.

    ── 동의하지 않은 항목은 여기서 거르지 않습니다(그럴 필요가 없습니다) ────────────
    `quantity` · `buy_amount` 는 동의가 없으면 **발행 배치가 애초에 null 로 넣습니다**
    (5-4-2 — 0 이나 빈 문자열로 채우지 않습니다). 그리고 `consent_holdings` 자체가 없으면
    이 표에 **행이 만들어지지 않습니다.** 즉 여기서 다시 걸러야 할 것이 없고, 화면은
    null 을 "비공개"로 그리기만 하면 됩니다. 필터를 여기에 또 만들면 "동의 판정"이 두 곳에
    존재하게 되고, 그게 §0-3-8 이 가장 싫어하는 모양입니다.
    """
    _require_client(client)
    name = _require_text(nickname, "닉네임")

    query = (client.table(PUBLIC_HOLDINGS_TABLE).select(PUBLIC_HOLDINGS_COLUMNS)
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

    ⚠️ `first_holding_date` 를 함께 읽습니다(2026-08-21 추가). 배치가 "이 계좌에 오늘 처음
       주식이 들어왔는가"를 판정하려면 **지금 값이 NULL 인지**를 알아야 하는데, 그걸 따로
       조회하면 계좌 수만큼 왕복이 늘거나(§0-3-2 위반) 두 번째 계좌 조회가 생깁니다.
       이미 계좌 전체를 읽는 이 질의에 컬럼 하나를 더하는 것이 정확히 같은 왕복 수입니다.
    """
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(ACCOUNTS_TABLE)
        .select("id,user_id,window_type,seed_amount,currency,anchor_date,status,"
                "first_holding_date")
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


def _fill_ledger_payload(entries):
    """
    체결 원장 행(매수·매도)의 payload 를 만듭니다. `record_buy_ledger_entries()` 와 USD
    미러가 **같은 규칙**을 쓰도록 여기 한 곳에 둡니다(§0-3-10).

    ⚠️ 부호를 정하는 **유일한 자리**입니다. 매수는 음수(`amount < 0`), 매도는 양수
       (`amount > 0` — 입금과 같은 방향)이고, 호출부는 **둘 다 체결금액을 양수로** 넘깁니다.
       부호를 호출부마다 다루면 언젠가 한 곳에서 빠지고, 그 계좌 잔고가 조용히 두 배가
       되거나 매도 대금이 잔고를 깎습니다.
    """
    payload = []
    for entry in entries:
        event_type = str(entry.get("event_type") or "buy").strip()
        if event_type not in ("buy", "sell"):
            raise DuelDbError(
                f"체결 원장에 쓸 수 없는 event_type 입니다: {event_type!r} (가능: buy / sell)."
                " 시드·정기입금은 이 함수가 아니라 각자의 경로로 기록합니다."
            )
        amount = _require_amount(entry.get("filled_amount"), "체결금액")
        payload.append({
            "account_id": _require_text(entry.get("account_id"), "계좌 ID"),
            "event_type": event_type,
            "amount": -amount if event_type == "buy" else amount,
            "event_date": _iso_date(entry.get("event_date"), "체결일"),
            # buy·sell 행에는 주문 링크가 반드시 있어야 추적이 됩니다(`..._order_link` CHECK).
            "order_id": _require_text(entry.get("order_id"), "주문 ID"),
            "memo": entry.get("memo"),
        })
    return payload


def record_buy_ledger_entries(service_client, entries):
    """
    (배치 전용) 체결 원장 행 여러 개를 **한 번의 insert** 로. 반환: 넣은 행 수.

    ⚠️ 이름은 `buy` 로 남아 있지만(호출부·테스트가 이 이름을 쓰고 있습니다), 2026-08-21
       부터 **매도 행도 같은 함수로** 기록합니다 — 각 항목의 `event_type` 이 `'sell'` 이면
       금액을 양수로 넣습니다(기본값은 `'buy'` 라 기존 호출부는 글자 하나 안 바뀝니다).
       얇은 `record_sell_ledger_entries()` 를 따로 만들지 않은 이유는 코드 중복 때문입니다 —
       두 함수가 되면 CHUNK 처리·검증·부호 규칙이 두 벌이 되고, 그중 하나만 고쳐지는 날이
       옵니다(§0-3-10).
    """
    _require_client(service_client, batch=True)
    rows = list(entries or [])
    if not rows:
        return 0

    payload = _fill_ledger_payload(rows)

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(LEDGER_TABLE).insert(chunk), "체결 원장 기록")
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
    ⚠️ **수량을 줄이는 값은 이 함수로 보내지 마세요.** `duel_positions_no_sell` 트리거가
       DB 에서 막고, 요청 전체가 실패합니다. 리밸런싱 매도 정산은 전용 경로인
       `settle_sell_positions()`(아래)로 보내야 합니다 — 그쪽만 `duel.settled_sell` 세션
       변수를 켤 수 있고, 그렇게 경로를 갈라 둔 덕분에 "왜 수량이 줄었는지"가 코드에서도
       원장에서도 한눈에 보입니다.
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


def _sell_settlement_payload(rows, label):
    """
    매도 정산 RPC 에 보낼 행 목록을 만듭니다(KRW/USD 공통 규칙 — §0-3-10).

    보내는 필드는 **셋뿐**입니다: `account_id` · `ticker` · `quantity`(정산 후 남는 수량).
    `avg_cost` 를 일부러 보내지 않습니다 — 매도는 잔여 주식의 매입단가를 바꾸지 않고
    (`duel_rules.apply_sell_fill_to_position()`), DB 함수도 수량만 갱신하도록 좁혀 뒀기
    때문입니다. 여기서 원가를 함께 보내기 시작하면 "정산 경로로 원가를 다시 쓰는" 길이
    생깁니다.
    """
    payload = []
    for row in rows:
        quantity = _require_amount(row.get("quantity"), "매도 후 잔여 수량", allow_zero=True)
        payload.append({
            "account_id": _require_text(row.get("account_id"), "계좌 ID"),
            "ticker": _require_text(row.get("ticker"), "종목코드"),
            "quantity": quantity,
        })
    _assert_unique_keys(payload, ("account_id", "ticker"), label)
    return payload


def settle_sell_positions(service_client, rows):
    """
    (배치 전용) 🔴 **리밸런싱 매도 체결을 포지션에 반영하는 유일한 경로.** 반환: 반영된 행 수.

    `upsert_positions()` 로는 수량을 줄일 수 없습니다 — `duel_positions_buy_only()` 트리거가
    막고, 예외는 같은 트랜잭션에서 `set local duel.settled_sell = 'on'` 이 먼저 실행된
    경우뿐입니다. PostgREST 는 요청마다 트랜잭션이 달라 클라이언트가 세션 변수를 앞세울 수
    없으므로, "플래그 켜기 + 수량 줄이기"를 한 호출로 묶은 DB 함수
    (`sql/duel_schema.sql` §9-11 `duel_settle_sell_positions(jsonb)`)를 부릅니다.
    자세한 근거는 위 `SETTLE_SELL_RPC` 상수 주석에 있습니다.

    ⚠️ 이 함수는 **계산하지 않습니다.** 잔여 수량은 `duel_rules.apply_sell_fill_to_position()`
       이 만든 값을 그대로 받습니다.
    ⚠️ 계좌마다 부르지 마세요 — 그날 매도 정산 **전체**를 한 번(길면 CHUNK_SIZE 단위)에
       보냅니다(§0-3-2).
    ⚠️ DB 함수가 "없는 포지션"·"줄지 않는 수량"을 만나면 **아무것도 반영하지 않고 예외**를
       냅니다. 그 실패는 여기서 삼키지 않고 그대로 올립니다 — 매도가 체결됐다고 기록됐는데
       수량이 그대로인 상태를 조용히 넘기면, 그 계좌의 자산이 하루아침에 늘어난 것처럼
       보입니다(§0-1).
    """
    _require_client(service_client, batch=True)
    payload = _sell_settlement_payload(list(rows or []), "매도 정산 요청")
    if not payload:
        return 0

    settled = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        try:
            query = service_client.rpc(SETTLE_SELL_RPC, {"p_rows": chunk})
        except (AttributeError, TypeError) as exc:
            raise DuelDbError(
                "이 Supabase 연결로는 매도 정산을 호출할 수 없습니다"
                " (저장 프로시저 호출을 지원하지 않는 클라이언트입니다)."
            ) from exc
        _execute(query, "매도 포지션 정산")
        settled += len(chunk)
    return settled


def set_first_holding_dates(service_client, account_ids, first_holding_date):
    """
    (배치 전용) 오늘 **처음으로** 보유 종목이 생긴 계좌들의 `first_holding_date` 를 채웁니다.
    반환: 실제로 채워진 행 수.

    왜 필요한가: 리밸런싱 창의 카운트다운 기준은 계좌 개설일(`anchor_date`)이 아니라
    **계좌에 최초로 주식이 들어온 날**입니다(2026-08-21 오너 확정). 개설일 기준으로 세면
    아무것도 안 산 채로 창이 흘러가 첫 매수 전에 매도 기회가 소멸합니다.

    ⚠️ 계좌마다 update 를 보내지 않습니다 — 값이 **모든 대상에 같은 날짜 하나**라서
       `in` 필터 한 번으로 끝납니다(§0-3-2). 계좌가 900개여도 왕복은 1회입니다.
    ⚠️ `first_holding_date is null` 조건을 **DB 쪽에서도** 겁니다. 배치를 두 번 돌려도
       이미 채워진 날짜를 오늘로 덮어쓰지 않게 하는 멱등 장치입니다 — 덮어쓰면 그 계좌의
       리밸런싱 창이 통째로 밀려 매도 기회가 사라지거나 하나 더 생깁니다.
    """
    _require_client(service_client, batch=True)
    ids = [str(value) for value in (account_ids or []) if str(value or "").strip()]
    if not ids:
        return 0        # 대상이 없으면 질의 자체를 보내지 않습니다(빈 in 필터 방지).

    day = _iso_date(first_holding_date, "최초 보유일")
    query = service_client.table(ACCOUNTS_TABLE).update({"first_holding_date": day}) \
        .in_("id", ids)
    updated = _execute(_filter_is_null(query, "first_holding_date"), "최초 보유일 기록")
    return len(updated or [])


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


# -----------------------------------------------------------------------------
# B-7. 🔴 공개 발행(5단계 · Branch 2) — **이 저장소에서 가장 민감한 함수들**
#      2026-08-20 추가. 작업지시서 5-3 · 5-4 · 5-6 · 5-8 / 스키마 §8 · §8-3 · §9-8
# -----------------------------------------------------------------------------
#  아래 함수들이 쓰는 표는 **로그인한 모든 사용자가 읽을 수 있는 표**입니다. 즉 여기 들어간
#  값은 곧 남에게 보이는 값입니다(§0-3-8 — 이 프로젝트의 최상위 무예외 원칙).
#
#  그래서 이 절은 다른 절보다 규율이 하나 더 있습니다:
#    · **판단하지 않습니다.** "누가 발행 대상인가", "체급이 무엇인가", "순위가 몇 등인가"는
#      전부 `utils/duel_rules.py`(순수 규칙)와 `utils/duel_publish.py`(오케스트레이션)가
#      정합니다. 이 절의 함수는 **이미 결정된 행을 그대로 담아 보내거나, 지정된 것을 지울
#      뿐**입니다. 여기에 "동의했으면 이 필드를 채우고..." 같은 조건문이 생기면, 게이팅
#      규칙이 두 곳에 존재하게 되고 언젠가 둘이 갈라집니다.
#    · 발행표에는 `user_id` 도 `account_id` 도 **넣지 않습니다**(스키마 §8). 닉네임 ↔ 계좌의
#      연결고리는 비공개 `duel_nicknames` 와 이 배치 안에만 존재합니다.
# -----------------------------------------------------------------------------
def fetch_publishable_consents(service_client):
    """
    (배치 전용) **발행 대상 계좌의 동의 행**을 한 번의 질의로 전부 읽습니다. 5-4-1 참고.

    거르는 조건은 둘입니다 — `final_confirmed = true` **그리고** `revoked_at is null`.
      · 사실 DB CHECK(`duel_consent_revoked_not_confirmed`)가 이미 "철회 + 최종확인"을 동시에
        설 수 없게 막고 있어서, 앞 조건 하나만으로도 결과는 같습니다.
      · 그래도 **둘 다 겁니다.** 5-8-2 가 "애플리케이션과 배치 양쪽에서 확인하라"고 명시하고,
        여기가 그 '배치' 쪽이기 때문입니다. 조건 하나를 아끼는 것보다, 나중에 CHECK 를 손대는
        사람이 이 필터를 보고 "아, 여기도 같은 규칙이 있구나"를 아는 편이 낫습니다.

    ⚠️ 항목별 동의 5개를 여기서 거르지 **않습니다.** `duel_consent_final_requires_all` CHECK
       때문에 `final_confirmed=true` 인 행은 5개가 전부 true 임이 DB 수준에서 보장되지만,
       그 보장을 **믿고 넘어가지 않고** `duel_publish.assert_full_consent()` 가 행마다 다시
       확인합니다. 여기서 필터로 처리하면 "조건에 안 맞아서 빠진 사람"이 조용히 사라지는데,
       그건 데이터가 이상하다는 신호를 삼키는 일입니다(§0-1).
    """
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE).select(
        "account_id,consent_rank,consent_return,consent_holdings,consent_quantity,"
        "consent_buy_amount,final_confirmed," + CONSENT_REAL_PRINCIPAL_FLAG + ",revoked_at"
    ).eq("final_confirmed", True)
    query = _filter_is_null(query, "revoked_at")
    rows = _execute(query, "발행 대상 동의 조회")
    return [dict(row) for row in rows]


def fetch_revoked_consent_accounts(service_client):
    """
    (배치 전용) **철회된 계좌의 account_id 목록**을 한 번의 질의로 읽습니다. 5-8-1 참고.

    야간 배치가 "철회된 사람의 발행 기록을 전부 지우는" 청소 단계에서 씁니다. "지난 실행
    이후 새로 철회된 것"만 고르지 않고 **철회된 것 전부**를 매번 봅니다:
      · 배치가 하루 걸렀거나 중간에 실패해도 다음 실행이 스스로 따라잡습니다(자가 치유).
      · "어디까지 처리했는지"를 기억하는 상태 파일이 필요 없습니다. 그런 파일이 손상되면
        누군가의 공개 기록이 **영원히 안 지워진 채로 남습니다** — 이 모듈에서 가장 나쁜 실패.
      · 삭제는 멱등이라 이미 지운 것을 다시 지워도 아무 일도 일어나지 않습니다.
    """
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE).select("account_id,revoked_at")
    query = _filter_not_null(query, "revoked_at")
    rows = _execute(query, "철회 계좌 조회")
    return [dict(row) for row in rows]


def fetch_nicknames_for_accounts(service_client, accounts):
    """
    (배치 전용) 여러 계좌의 닉네임을 **한 번의 질의로** 읽습니다(§0-3-2).
    반환: `{account_id: nickname}`.

    ⚠️ `duel_nicknames` 가 `(user_id, window_type)` 키로 바뀌면서(2026-08-20, USD 트랙
       작업) 계좌 id 만으로는 닉네임을 찾을 수 없게 됐습니다 — 같은 사용자의 KRW/USD
       계좌가 창유형이 같으면 닉네임을 공유하기 때문입니다(5-11-10). 그래서 이 함수는
       이제 **계좌 id 문자열이 아니라 계좌 행(딕셔너리, `id`/`user_id`/`window_type`
       포함)** 을 받습니다 — 호출부는 `fetch_all_active_accounts()` 등으로 이미 읽어
       둔 계좌 행을 그대로 넘기면 됩니다.

    ⚠️ `accounts` 는 **필수**입니다(기본값 None 으로 "전부 읽기"를 만들지 않았습니다).
       이 표는 닉네임 ↔ 사용자 대응표라, 통째로 읽는 편의 함수가 있으면 언젠가 누군가
       "일단 다 읽어 놓고 필요한 것만 쓰지"라고 하게 됩니다. 필요한 계좌만 읽습니다.
    """
    _require_client(service_client, batch=True)
    rows_in = [dict(row) for row in (accounts or []) if row and row.get("id")]
    if not rows_in:
        return {}
    user_ids = sorted({str(row["user_id"]) for row in rows_in if row.get("user_id")})
    if not user_ids:
        return {}
    lookup = {}
    for start in range(0, len(user_ids), CHUNK_SIZE):
        rows = _execute(
            service_client.table(NICKNAMES_TABLE).select("user_id,window_type,nickname")
            .in_("user_id", user_ids[start:start + CHUNK_SIZE]),
            "닉네임 일괄 조회",
        )
        for row in rows:
            nickname = str((row or {}).get("nickname") or "").strip()
            if not nickname:
                continue
            key = (str(row.get("user_id")), str(row.get("window_type")))
            lookup[key] = nickname
    mapping = {}
    for row in rows_in:
        key = (str(row.get("user_id")), str(row.get("window_type")))
        nickname = lookup.get(key)
        if nickname:
            mapping[row["id"]] = nickname
    return mapping


def fetch_bracket_assignments(service_client, season_key):
    """
    (배치 전용) **이번 시즌의 체급 배정 기록 전부**를 한 번의 질의로 읽습니다(스키마 §8-3).
    반환: `{account_id: {"season_key": ..., "bracket_key": ...}}`.

    이 결과가 `duel_rules.resolve_bracket_for_season()` 의 첫 인자가 되고, 그 함수가
    "시즌 중이면 그대로 유지"를 강제합니다(5-3). 배치가 체급을 스스로 정하지 않게 하려면
    **먼저 읽어야** 합니다 — 이 질의를 빼먹으면 시즌 고정 규칙이 조용히 사라집니다.
    """
    _require_client(service_client, batch=True)
    season = _require_text(season_key, "시즌 식별자")
    rows = _execute(
        service_client.table(BRACKET_ASSIGNMENTS_TABLE)
        .select("account_id,season_key,bracket_key").eq("season_key", season),
        "체급 배정 조회",
    )
    return {row["account_id"]: dict(row) for row in rows if (row or {}).get("account_id")}


def insert_bracket_assignments(service_client, rows):
    """
    (배치 전용) **새로 배정된** 체급을 기록합니다(insert 만 — 스키마 §8-3). 반환: 넣은 행 수.

    ⚠️ upsert 가 아니라 insert 인 것이 이 함수의 핵심입니다. 배치에도 update 권한이 없어서
       (§9-9) 이미 배정된 체급은 **물리적으로 바꿀 수 없습니다.** "체급은 시즌 동안 고정"이
       앱의 조심성이 아니라 DB 권한으로 강제되는 자리입니다.
    ⚠️ 그래서 중복 키 충돌은 **사고가 아니라 정상**입니다(두 배치가 겹쳐 돌거나, 같은 날
       두 번 실행). 조용히 흡수하고 0 을 돌려줍니다 — 이미 있는 값이 이깁니다.
    """
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
            _execute(service_client.table(BRACKET_ASSIGNMENTS_TABLE).insert(chunk), "체급 배정 기록")
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            continue        # 이미 배정된 시즌 — 기존 값이 이깁니다(위 주석 참고).
        inserted += len(chunk)
    return inserted


def fetch_real_principal_holdings(service_client, user_ids):
    """
    (배치 전용) 🔴 **동의한 사용자의** "내 성적표" 실제 보유종목을 한 번의 질의로 읽습니다.
    작업지시서 5-3 참고 — 체급(원금 구간) 산정에만 씁니다.

    ── 이 함수가 이 파일에서 가장 조심스러운 자리인 이유 ─────────────────────────
    이건 **가상 대결 데이터가 아니라 사용자의 진짜 자산 데이터**(`public.holdings`)입니다.
    5-3 이 못 박습니다: *"이 값은 5-2 의 4번(독립 동의)이 있는 사용자에 대해서만 조회합니다.
    동의 없는 사용자의 holdings 를 읽는 코드 경로가 **하나라도** 있으면 §0-3-8 위반입니다."*

    그래서 이 함수는 이렇게 생겼습니다:
      · `user_ids` 가 **필수 인자**입니다. 기본값이 없습니다. "안 주면 전부"라는 편의 경로를
        만들지 않았습니다 — 그 한 줄이 곧 위 문장의 위반입니다.
      · 빈 목록이면 **질의를 아예 보내지 않습니다.** 빈 `in` 필터가 실수로 전체 조회가 되는
        일을 구조적으로 막습니다.
      · ⚠️ `utils/report_db.py::fetch_all_holdings()` 를 **쓰지 않습니다.** 그 함수는 이름
        그대로 **전체 사용자의 보유종목**을 읽습니다(리포트 스냅샷 배치는 전원이 대상이라
        그게 맞습니다). 여기서 그걸 부르면 동의하지 않은 사람의 자산이 이 배치의 메모리에
        올라오고, 그 순간 5-3 위반입니다. 필터가 다르므로 질의를 따로 씁니다.
      · 읽기만 합니다. 이 파일 어디에도 `holdings` 를 쓰는 코드는 없습니다.

    반환: 보유 행 목록(`user_id` 포함). 금액 계산은 이 파일이 하지 않고
          `utils/duel_publish.py` 가 `utils/scorecard_db.py` 의 **진짜 평가 함수**로 합니다.
    """
    _require_client(service_client, batch=True)
    ids = [str(value) for value in (user_ids or [])]
    if not ids:
        return []               # 🔴 동의자가 없으면 holdings 를 **한 번도 건드리지 않습니다.**

    result = []
    for start in range(0, len(ids), CHUNK_SIZE):
        rows = _execute(
            service_client.table(scorecard_db.HOLDINGS_TABLE).select(
                "user_id,market,ticker,stock_name,quantity,avg_purchase_price,currency"
            ).in_("user_id", ids[start:start + CHUNK_SIZE]),
            "체급 산정용 보유종목 조회",
        )
        result.extend(dict(row) for row in rows)
    return result


# ── 발행표 쓰기·지우기 ─────────────────────────────────────────────────────────
def delete_published_rows_for_date(service_client, published_date):
    """
    (배치 전용) **그날 발행분을 통째로 지웁니다**(두 표 각각 질의 1개). 5-4-4 참고.

    작업지시서 5-4-4 가 "부분 갱신이 아니라 그날 발행분을 통째로 갈아끼우는 방식"을 확정한
    이유는 안전입니다. 부분 갱신은 "어제는 있었는데 오늘은 자격을 잃은 행"을 **남깁니다** —
    지워야 할 것을 지우는 코드는 항상 넣기 쉬운 코드가 아니고, 하나 빠뜨리면 그 행은 계속
    공개된 채로 남습니다. 통째로 지우고 다시 쓰면 "남는" 경우가 구조적으로 없습니다.

    ⚠️ 지우고 나서 넣기 전에 배치가 죽으면 그날 순위표가 잠깐 비어 있게 됩니다. 그 방향이
       안전한 쪽입니다 — 반대(지워야 할 것이 남아 있는 상태)는 §0-3-8 사고입니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    # 표 이름을 반복문 변수로 감싸지 않고 **한 줄씩 그대로** 씁니다. §0-3-8 검토와
    # `tests/test_duel_publish.py` 의 AST 검사가 "어느 함수가 어느 표에 쓰는가"를
    # 코드에서 바로 읽을 수 있어야 하기 때문입니다(짧게 쓰는 것보다 보이는 게 중요).
    _execute(service_client.table(PUBLIC_LEADERBOARD_TABLE).delete()
             .eq("published_date", day), "순위표 당일 발행분 삭제")
    _execute(service_client.table(PUBLIC_HOLDINGS_TABLE).delete()
             .eq("published_date", day), "보유종목 당일 발행분 삭제")
    return None


def delete_published_rows_for_nicknames(service_client, nicknames):
    """
    (배치 전용) 🔴 지정한 닉네임의 발행 행을 **모든 날짜에서 영구 삭제**합니다. 5-8-1 참고.

    5-8-1 원문: *"철회 즉시 그 계좌의 발행된 공개 기록을 **전부 영구 삭제**합니다 — 과거 순위,
    과거 발행 수익률, 발행된 보유종목 행까지 **숨김이 아니라 삭제**입니다."*
    그래서 `published_date` 필터를 **일부러 걸지 않습니다.** 오늘 것만 지우면 어제 것이
    그대로 남고, 그건 "삭제했다"고 말할 수 없는 상태입니다.

    ⚠️ 계좌가 아니라 **닉네임**으로 지웁니다. 발행표에는 `account_id` 가 아예 없기 때문이고
       (스키마 §8), 그게 이 설계의 핵심입니다 — 공개표만 읽어서는 누구인지 알 수 없습니다.
       닉네임 ↔ 계좌 대응은 비공개 `duel_nicknames` 와 이 배치 안에만 있습니다.
    ⚠️ 닉네임은 한 번 만들면 바뀌지 않으므로(스키마 §9-6 에 update 정책 없음), 이 삭제가
       과거 행을 놓칠 일이 없습니다.

    반환: 실제로 지운 행 수(두 표 합계). PostgREST 가 지운 행을 돌려주지 않는 설정이면
          0 이 나올 수 있어, 호출부는 이 값을 "성공 여부"로 쓰지 않습니다.
    """
    _require_client(service_client, batch=True)
    names = sorted({str(value).strip() for value in (nicknames or []) if str(value).strip()})
    if not names:
        return 0

    removed = 0
    for start in range(0, len(names), CHUNK_SIZE):
        chunk = names[start:start + CHUNK_SIZE]
        # 표 이름을 한 줄씩 그대로(위 `delete_published_rows_for_date()` 와 같은 이유).
        removed += len(_execute(
            service_client.table(PUBLIC_LEADERBOARD_TABLE).delete().in_("nickname", chunk),
            "철회 계좌의 발행 순위 삭제",
        ))
        removed += len(_execute(
            service_client.table(PUBLIC_HOLDINGS_TABLE).delete().in_("nickname", chunk),
            "철회 계좌의 발행 보유종목 삭제",
        ))
    return removed


def leaderboard_has_any_rows(service_client):
    """
    (배치 전용) 순위표 발행표에 **행이 하나라도 있는가**(질의 1개, `limit(1)`).

    최소 인원 미달 청소(5-6)를 시작하기 전의 값싼 사전 점검입니다. 청소는 "발행될 수 있는
    모든 그룹"(3 창유형 × 9 체급 = 27개, 상수)을 훑는데, **아직 한 번도 발행된 적이 없는
    초기 운영 기간에는 그 27번이 전부 헛걸음**입니다. 이 한 줄이 그걸 1번으로 줄입니다.

    ⚠️ "없으면 건너뛴다"가 안전한 이유: 표가 비어 있으면 지울 것도 없습니다. 반대 방향의
       실수(있는데 없다고 판단)는 이 질의가 `limit(1)` 조회 하나뿐이라 생기지 않습니다.
    """
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).select("id").limit(1),
        "발행표 존재 확인",
    )
    return bool(rows)


def fetch_published_group_index(service_client, window_type, bracket_key):
    """
    (배치 전용) 한 그룹(창유형 × 체급)이 **과거에 발행된 적이 있는지**와, 있다면 어느 날짜에
    누구(닉네임)로 실렸는지를 읽습니다. 최소 인원 미달 그룹을 청소할 때만 씁니다(5-6).

    ⚠️ 인원이 임계값을 **넘는** 그룹에는 절대 부르지 마세요 — 그런 그룹은 정의상 500명
       이상이라 결과가 큽니다. 호출부(`utils/duel_publish.py`)는 **미달 그룹에만** 부릅니다.
       미달 그룹은 500명 미만이라 결과 크기가 구조적으로 작습니다.

    반환: `{published_date: [nickname, ...]}`
    """
    _require_client(service_client, batch=True)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).select("published_date,nickname")
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


def delete_published_group(service_client, window_type, bracket_key, *, holdings_index=None):
    """
    (배치 전용) 최소 인원 미달 그룹의 발행 행을 **모든 날짜에서** 지웁니다. 5-6 참고.

    5-6 원문: *"임계값 미만인 구간은 아예 발행하지 않습니다. **이미 발행돼 있던 행도
    제거합니다.**"* 참가자가 501명이었다가 499명으로 줄어든 경우가 정확히 이 경우입니다.

    ── 두 표를 다르게 지우는 이유 ────────────────────────────────────────────────
    `duel_public_leaderboard` 에는 `bracket_key` 컬럼이 있어서 **질의 한 방**으로 끝납니다.
    `duel_public_holdings` 에는 없습니다(스키마 §8-2 가 의도적으로 뺐습니다 — 체급은 순위표의
    축이지 보유종목의 속성이 아니고, 중복 저장하면 두 표가 어긋날 여지가 생기기 때문).
    그래서 보유종목 쪽은 **"그 그룹에 실렸던 날짜 × 그 날짜의 닉네임"** 으로 지웁니다.
    날짜별로 나누는 이유: 시즌이 바뀌면 같은 닉네임이 다른 체급으로 옮겨갈 수 있어서,
    날짜를 묶어서 지우면 **다른 시즌의 정상 행까지 지울 수 있습니다.** 날짜별로 그날 실제로
    이 그룹에 있던 닉네임만 지우면 그 위험이 없습니다.

    ⚠️ 질의 수는 (1 + 그 그룹이 발행된 날짜 수)입니다. 계좌 수·사용자 수에 비례하지 않으므로
       §0-3-2 위반이 아니고, 대부분의 밤에는 발행된 날짜가 0 이라 질의 1개로 끝납니다.

    인자
        holdings_index : `fetch_published_group_index()` 결과. None 이면 여기서 읽습니다.
    """
    _require_client(service_client, batch=True)
    window = _require_text(window_type, "창 유형")
    bracket = _require_text(bracket_key, "체급 식별자")

    index = (fetch_published_group_index(service_client, window, bracket)
             if holdings_index is None else dict(holdings_index))
    if not index:
        return 0            # 발행된 적이 없는 그룹 — 지울 것도, 보낼 질의도 없습니다.

    removed = len(_execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).delete()
        .eq("window_type", window).eq("bracket_key", bracket),
        "최소 인원 미달 그룹 순위 삭제",
    ))
    for day, nicknames in sorted(index.items()):
        names = sorted({str(name).strip() for name in nicknames if str(name).strip()})
        for start in range(0, len(names), CHUNK_SIZE):
            removed += len(_execute(
                service_client.table(PUBLIC_HOLDINGS_TABLE).delete()
                .eq("published_date", day).in_("nickname", names[start:start + CHUNK_SIZE]),
                "최소 인원 미달 그룹 보유종목 삭제",
            ))
    return removed


def write_public_leaderboard(service_client, published_date, rows):
    """
    (배치 전용) 순위표 발행 행을 **한 번에** 넣습니다(청크 단위 insert). 반환: 넣은 행 수.

    ⚠️ 이 함수는 **아무것도 판단하지 않습니다.** 어떤 계좌가 발행 대상인지, 수익률을 실을지
       말지, 순위가 몇 등인지는 전부 호출부가 정해서 넘깁니다. 여기서 값을 채우거나
       바꾸는 코드가 생기면, 동의 게이팅 규칙이 두 곳에 존재하게 됩니다(§0-3-8).

    ⚠️ 그래도 **최소한의 자기 방어**는 합니다 — `account_id` / `user_id` 같은 키가 payload 에
       섞여 있으면 **거절**합니다. 발행표에는 그 컬럼이 아예 없어서 PostgREST 가 어차피
       거절하지만, 그때 나오는 메시지("column ... does not exist")로는 **무엇이 위험했는지**가
       드러나지 않습니다. 여기서 잡아 "발행표에 식별자를 실으려 했다"고 말해 줍니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    payload = []
    for row in rows or []:
        item = dict(row)
        _assert_no_identity_fields(item, PUBLIC_LEADERBOARD_TABLE)
        item["published_date"] = day
        payload.append(item)
    if not payload:
        return 0
    _assert_unique_keys(payload, ("published_date", "window_type", "bracket_key", "nickname"),
                        "순위표 발행 요청")

    written = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(PUBLIC_LEADERBOARD_TABLE).insert(chunk), "순위표 발행")
        written += len(chunk)
    return written


def write_public_holdings(service_client, published_date, rows):
    """
    (배치 전용) 공개 보유종목 발행 행을 **한 번에** 넣습니다. 반환: 넣은 행 수.
    규약은 위 `write_public_leaderboard()` 와 같습니다(판단하지 않고, 식별자 혼입은 거절).
    """
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    payload = []
    for row in rows or []:
        item = dict(row)
        _assert_no_identity_fields(item, PUBLIC_HOLDINGS_TABLE)
        item["published_date"] = day
        payload.append(item)
    if not payload:
        return 0
    _assert_unique_keys(payload, ("published_date", "nickname", "ticker"), "보유종목 발행 요청")

    written = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(PUBLIC_HOLDINGS_TABLE).insert(chunk), "보유종목 발행")
        written += len(chunk)
    return written


#: 🔴 발행표에 **절대 실리면 안 되는** 키. 스키마 §8 이 이 컬럼들을 두지 않은 이유가
#:    "이 표만 읽으면 안전하다"는 보장을 지키기 위해서라, 앱도 같은 목록을 들고 한 번 더
#:    거릅니다(§0-3-9 — 두 겹이 같은 방향을 가리키게).
FORBIDDEN_PUBLISH_FIELDS = ("account_id", "user_id", "email", "id", "auth_id", "owner_id")


def _assert_no_identity_fields(payload, table_name):
    """발행 payload 에 식별자가 섞였는지 검사합니다(위 상수 참고)."""
    leaked = sorted(key for key in payload if key in FORBIDDEN_PUBLISH_FIELDS)
    if leaked:
        raise DuelDbError(
            f"{table_name} 발행 payload 에 식별자가 들어 있습니다: {leaked}"
            " — 발행표에는 user_id·account_id 를 절대 싣지 않습니다(스키마 §8 / §0-3-8)."
            " 닉네임 ↔ 계좌의 연결고리는 비공개 duel_nicknames 에만 있어야 합니다."
        )


# #############################################################################
#
#  C 절 — 아직 만들지 않은 것 (5단계 이후)
#
#  🔴 여기에는 코드가 없습니다. 스텁조차 두지 않습니다 — "절반 열린 문"이 §0-3-8 에서
#     가장 위험한 모양이기 때문입니다. 아래는 **어디에 무엇이 들어올지**의 메모입니다.
#
#  TODO(작업지시서 5-2 / 5-7): 공개 동의 UI 확장과 순위표 화면(`web/pages/`). 순위표 화면은
#      `duel_public_leaderboard` / `duel_public_holdings` **두 표만** 읽어야 하고,
#      `duel_positions` · `holdings` · `profiles` · `duel_cash_ledger` 를 **import 조차
#      하지 않아야** 합니다(5-4-5).
#  TODO(작업지시서 5-4): 발행 배치 워크플로우 yml(`.github/workflows/duel_publish.yml`).
#      파이썬 쪽 로직은 `utils/duel_publish.py` 에 이미 있습니다 — yml 은 그걸 부르는 껍데기.
#  TODO(작업지시서 5-8, 오너 결정 대기): 철회 즉시 공개 기록을 지우는 **앱 경로**가 필요한지.
#      지금은 야간 배치가 지우므로 최대 하루의 간격이 있습니다. 즉시 삭제가 필요하다면
#      `duel_opt_in()` 과 같은 종류의 SECURITY DEFINER 함수가 답이 되겠지만, 그건 발행표에
#      쓰기(삭제) 권한을 가진 함수를 하나 더 만드는 일이라 오너 확인 없이 만들지 않습니다.
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
USER_WRITE_FUNCTIONS = ("opt_in", "save_order", "save_sell_order", "edit_order",
                        "cancel_order", "save_consent")

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
