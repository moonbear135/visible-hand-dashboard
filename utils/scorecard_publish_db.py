# utils/scorecard_publish_db.py
"""
📋 "내 성적표" 공개 순위표 — **Supabase 접근 계층**

`sql/scorecard_public_schema.sql` 이 만드는 다섯 표
(`scorecard_nicknames` / `scorecard_public_consent` / `scorecard_bracket_assignments` /
`scorecard_public_leaderboard` / `scorecard_public_holdings`)를 만지는 **유일한 자리**입니다.

`utils/duel_db.py` 의 "공개 동의 + 발행표" 슬라이스(이번 배포로 은퇴하는 계층)를 그대로 옮긴
미러이고, `utils/duel_db_usd.py` 가 세운 미러 규약을 따릅니다.

-------------------------------------------------------------------------------
🔁 무엇을 그대로 가져다 쓰고, 무엇을 새로 정의했는가 (§0-3-10)
-------------------------------------------------------------------------------
`utils.duel_db` 에서 **import 해서 씁니다**(재구현하지 않습니다) — 표 이름을 인자로 받거나
아예 몰라도 되는 순수 인프라라, 두 번 구현하면 한쪽만 고쳐지는 날 검증 규칙이 갈라집니다:
    `DuelDbError` · `CHUNK_SIZE` · `_execute` · `_require_client` · `_iso_date` · `_now_kst` ·
    `_require_text` · `_require_positive_int` · `_require_offset` · `_first_row` ·
    `_is_duplicate_key_error` · `_assert_unique_keys` · `_filter_is_null` · `_filter_not_null` ·
    `FORBIDDEN_PUBLISH_FIELDS` · `_assert_no_identity_fields` ·
    `create_service_client` · `service_config_present`
      · 마지막 두 개: **같은 Supabase 프로젝트, 같은 service_role 키**입니다(성적표 공개표와
        결투 가상계좌는 같은 DB 안의 다른 표일 뿐). 두 번째 클라이언트 생성 경로를 만들지
        않습니다.
      · `_assert_no_identity_fields()` 는 비공개 함수지만 **일부러** 가져다 씁니다 —
        "발행 payload 에 식별자가 섞였는가"를 판정하는 목록(`FORBIDDEN_PUBLISH_FIELDS`)이
        두 벌 존재하는 것이 이 저장소에서 가장 위험한 종류의 중복이기 때문입니다(§0-3-8).

**새로 정의합니다**(표 이름·키 축이 본문에 박혀 있는 것들):
    · §0 의 표 이름 상수 5개와 `CONSENT_ITEM_FLAGS`.
      ⚠️ `CONSENT_ITEM_FLAGS` 는 컬럼 이름이 결투 쪽과 글자까지 같지만 **다른 표의 컬럼**
         입니다. 결투의 공개 동의 표는 이번 마이그레이션에서 `drop` 되므로,
         `duel_db.CONSENT_ITEM_FLAGS` 를 빌려 쓰면 없어진 표를 가리키는 상수에 이 모듈이
         묶입니다. 그래서 여기 따로 둡니다.
    · A 절(사용자 세션): 동의 CRUD 3종 · 닉네임 2종 · 발행표 읽기 3종.
    · B 절(배치): 발행 대상/철회 조회 · 닉네임 일괄 조회 · 체급 배정 읽기·쓰기 ·
      보유종목 일괄 조회 · 발행표 쓰기/지우기.

-------------------------------------------------------------------------------
🧭 결투 계층과 **구조가 다른 점 두 가지** (실수하기 쉬운 자리라 여기 못 박습니다)
-------------------------------------------------------------------------------
  ① **계좌(`account_id`)가 없습니다.** "내 성적표"는 사용자당 포트폴리오 하나이므로 모든
     키가 `user_id` 입니다. 이 파일에 `account_id` 라는 문자열이 등장하면 그건 버그입니다.
  ② **창유형(`window_type`)이 없습니다.** 대신 `currency`('KRW'/'USD') 축이 있고, 두 통화는
     **어디서도 합산하지 않습니다**(§0-1 / `scorecard_db.NO_FX_CONVERSION_NOTICE`).
     체급 배정 키는 `(user_id, currency, season_key)`, 순위표 그룹 키는
     `(published_date, currency, bracket_key)` 입니다.

-------------------------------------------------------------------------------
🔴 A 절 / B 절 격리 (§0-3-8)
-------------------------------------------------------------------------------
A 절 함수는 **로그인 세션 클라이언트**를, B 절 함수는 **service_role 클라이언트**를 받습니다.
화면 코드가 B 절을 부르기 시작하면 그 순간 앱 서버에 service_role 키가 필요해지고 이 모듈의
모든 RLS 가 장식이 됩니다. A 절에는 배치 키의 이름을 **주석에도** 적지 않습니다.
"""

from __future__ import annotations

from utils import duel_rules, scorecard_db
from utils.duel_db import (
    CHUNK_SIZE,
    FORBIDDEN_PUBLISH_FIELDS,
    DuelDbError,
    _assert_no_identity_fields,
    _assert_unique_keys,
    _execute,
    _filter_is_null,
    _filter_not_null,
    _first_row,
    _is_duplicate_key_error,
    _iso_date,
    _now_kst,
    _require_client,
    _require_offset,
    _require_positive_int,
    _require_text,
    create_service_client,
    service_config_present,
)

__all__ = [
    "DuelDbError",
    "FORBIDDEN_PUBLISH_FIELDS",
    "NICKNAMES_TABLE",
    "CONSENT_TABLE",
    "BRACKET_ASSIGNMENTS_TABLE",
    "PUBLIC_LEADERBOARD_TABLE",
    "PUBLIC_HOLDINGS_TABLE",
    "CONSENT_ITEM_FLAGS",
    "PUBLISHED_CURRENCIES",
    "create_service_client",
    "service_config_present",
    # A 절 — 사용자 세션
    "save_consent",
    "fetch_my_consent",
    "revoke_consent",
    "ensure_nickname",
    "fetch_my_nickname",
    "fetch_public_leaderboard_latest_date",
    "fetch_public_leaderboard",
    "fetch_public_holdings_for_nickname",
    # B 절 — 배치
    "fetch_publishable_consents",
    "fetch_revoked_consent_users",
    "fetch_nicknames_for_users",
    "fetch_bracket_assignments",
    "insert_bracket_assignments",
    "fetch_holdings_for_users",
    "delete_published_rows_for_date",
    "delete_published_rows_for_nicknames",
    "leaderboard_has_any_rows",
    "fetch_published_group_index",
    "delete_published_group",
    "write_public_leaderboard",
    "write_public_holdings",
]


# =============================================================================
# 0. 표 이름 — sql/scorecard_public_schema.sql 과 **문자 그대로** 같아야 합니다
# =============================================================================
NICKNAMES_TABLE = "scorecard_nicknames"
CONSENT_TABLE = "scorecard_public_consent"

# 🔴 발행 전용 공개표 2개 + 체급 배정 기록.
#    ⚠️ 발행표 두 개는 **읽기는 A 절**(로그인 사용자에게 select 만 열려 있습니다),
#       **쓰기·삭제는 B 절**(service_role 만)입니다. 체급 배정 표는 아무에게도 update/delete
#       권한이 없습니다(스키마 §3-3 / §3-8 — "시즌 중 체급 고정"을 DB 권한으로 강제).
BRACKET_ASSIGNMENTS_TABLE = "scorecard_bracket_assignments"
PUBLIC_LEADERBOARD_TABLE = "scorecard_public_leaderboard"
PUBLIC_HOLDINGS_TABLE = "scorecard_public_holdings"

#: 항목별 동의 5개. **이 5개만** "전부 아니면 전무" 규칙의 대상입니다.
#:
#: 🔴 결투에 있던 여섯 번째 독립 동의(`consent_real_principal_bracket`)에 해당하는 항목이
#:    **여기에는 없습니다.** 그 동의가 분리돼 있던 이유는 "이 모듈이 아닌 다른 모듈의 실제
#:    자산 데이터를 끌어다 쓴다"는 것이었는데, 이 표에서는 공개되는 데이터 자체가 이미 실제
#:    자산("내 성적표")입니다. `consent_buy_amount` 에 동의하는 순간 매입원가합계는 이미
#:    공개된 값들의 단순 합으로 누구나 재구성 가능하므로, 체급 산정을 위한 두 번째 동의
#:    게이트를 만들 이유가 사라졌습니다(스키마 §2-2 주석과 같은 판단).
#:    ⚠️ 그러므로 이 목록에 항목을 **더하지 마세요.** 더하는 순간 DB 의
#:       `scorecard_consent_final_requires_all` CHECK 와 앱의 판정이 갈라집니다.
CONSENT_ITEM_FLAGS = (
    "consent_rank",
    "consent_return",
    "consent_holdings",
    "consent_quantity",
    "consent_buy_amount",
)

#: 발행 축이 되는 통화. `scorecard_db` 의 상수를 그대로 씁니다(문자열을 다시 적지 않습니다 —
#: DB 의 `check (currency in ('KRW','USD'))` 와 어긋나면 발행이 통째로 거절됩니다).
PUBLISHED_CURRENCIES = (scorecard_db.CURRENCY_KRW, scorecard_db.CURRENCY_USD)


def _require_currency(value, label="통화"):
    """`'KRW'` / `'USD'` 만 통과시킵니다. 모르는 통화는 지어내지 않고 예외입니다."""
    code = str(value or "").strip()
    if code not in PUBLISHED_CURRENCIES:
        raise DuelDbError(
            f"알 수 없는 {label} 입니다: {value!r} (허용: {', '.join(PUBLISHED_CURRENCIES)})."
        )
    return code


# #############################################################################
#
#  A 절 — 사용자용 (anon key + 로그인 세션 · RLS 범위 안)
#
#  이 절의 함수는 전부 **첫 인자로 클라이언트를 받습니다.** 여기서 클라이언트를 만들지
#  않습니다 — 만드는 자리가 여럿이면 "어느 키로 갔는지"를 추적할 수 없게 됩니다.
#
#  ⚠️ `user_id` 를 인자로 받는 이유(결투 A 절은 일부러 받지 않았습니다):
#     결투에는 소유권이 이미 확인된 `account_id` 라는 중간 키가 있었지만, 이 모듈의 표는
#     `user_id` 가 곧 기본키이고 RLS 정책도 `auth.uid() = user_id` 입니다. 그래서
#     `utils/scorecard_db.py` 의 기존 함수들(`fetch_holdings(client, user_id)` ·
#     `insert_holding(client, user_id, ...)`)과 **같은 규약**으로 맞췄습니다 — "내 성적표"
#     모듈 안에서 한 함수만 다른 모양이면 그게 더 위험합니다.
#     🔒 남의 id 를 넣어도 RLS(그리고 `with check (auth.uid() = user_id)`)가 막습니다.
#        앱에서 id 를 명시적으로 거는 것은 `scorecard_db.fetch_holdings()` 와 같은 이중 방어
#        입니다.
#
# #############################################################################

# -----------------------------------------------------------------------------
# A-1. 공개 동의 저장 / 조회 / 철회
# -----------------------------------------------------------------------------
def save_consent(client, user_id, **consent_flags):
    """
    공개 동의 상태를 저장합니다(`scorecard_public_consent`). 스키마 §2-2 참고.

    받는 키(그 밖의 키는 **거절**합니다 — 오타로 동의가 조용히 안 켜지는 사고를 막습니다):
        consent_rank / consent_return / consent_holdings / consent_quantity /
        consent_buy_amount        … 항목별 동의 5개
        final_confirmed           … 5개를 전부 체크한 뒤 밟는 **별도의** 최종 확인

    ── 이 함수가 앱에서도 강제하는 것(DB 가 최종 권한, 여기는 이중 방어) ──────────────
    ① `final_confirmed=True` 는 **5개가 전부 True 일 때만** 허용합니다.
       DB 의 `scorecard_consent_final_requires_all` CHECK 와 같은 규칙을 앱에서 한 번 더
       봅니다. DB 만 믿어도 데이터는 안전하지만, 그때 사용자는 Postgres 제약 이름이 섞인
       오류를 보게 됩니다(§0-3-4). 여기서 먼저 잡아 **왜 안 되는지**를 한국어로 알려 줍니다.
    ② `final_confirmed_at` 은 앱이 채웁니다. `final_confirmed` 가 켜지면 시각이 반드시
       있어야 하고(CHECK), 꺼지면 반드시 없어야 합니다 — 두 값을 따로 받지 않고 여기서 짝을
       맞춥니다("언제 최종확인했는지 모르는 최종확인"을 만들지 않기).
    ③ **철회 후 3개월 재동의 차단.** 저장을 시작하기 전에 기존 동의 행을 한 번 읽어
       `revoked_at` 을 확인하고, 아직 3개월이 안 지났으면 **언제 풀리는지 날짜까지 적힌
       한국어 오류**로 거절합니다. 화면만 막으면 배치가 되살리므로 저장 경로인 여기에
       둡니다(발행 배치 쪽은 `fetch_publishable_consents()` 가
       `final_confirmed=true and revoked_at is null` 로 한 번 더 거릅니다).
       ⚠️ 판정 자체는 이 파일이 하지 않습니다 — `duel_rules.resolve_reconsent_block()` 이
          "3개월"이라는 숫자와 경계 규칙의 단일 출처입니다(§0-3-10).

    ⚠️ 5개 항목을 **부분적으로 저장하는 것 자체는 막지 않습니다.** 화면이 체크박스를 하나씩
       켜는 중간 상태가 정상이기 때문입니다. "전부 아니면 전무"는 **발행 대상이 되는 조건**
       (= final_confirmed)에 걸리는 규칙이고, 위 ①이 정확히 그걸 강제합니다.

    ⚠️ 철회 **저장**은 이 함수가 아니라 `revoke_consent()` 입니다(아래). 한 함수가 "켜기"와
       "끄기"를 둘 다 하면, 나중에 누가 `save_consent(..., revoked_at=None)` 같은 인자를
       붙여 철회를 되돌리는 경로를 만들게 됩니다.

    반환: 저장된 동의 행 dict.
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")

    allowed = set(CONSENT_ITEM_FLAGS) | {"final_confirmed"}
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

    payload = {"user_id": user}
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

    # 철회 후 3개월 동안은 어떤 동의 저장도 진행하지 않습니다(아래 함수 참고).
    #  ⚠️ 순서가 중요합니다: **입력 검증을 전부 마친 뒤**에 조회합니다. 오타나 잘못된 값처럼
    #     저장 자체가 불가능한 요청 때문에 DB 를 왕복하지 않기 위해서입니다.
    _assert_reconsent_allowed(client, user)

    rows = _execute(
        client.table(CONSENT_TABLE).upsert(payload, on_conflict="user_id"),
        "공개 동의 저장",
    )
    return _first_row(rows, "공개 동의 저장")


def fetch_my_consent(client, user_id):
    """
    본인의 공개 동의 행 1개(없으면 None). 화면이 체크박스 상태를 그릴 때, 그리고 아래 두
    함수가 철회 이력을 확인할 때 씁니다.

    ⚠️ 없는 것과 실패한 것은 다릅니다 — 질의가 실패하면 `_execute()` 가 예외를 냅니다.
       "행이 없다"만 None 입니다(§0-1).
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")
    rows = _execute(
        client.table(CONSENT_TABLE).select("*").eq("user_id", user).limit(1),
        "공개 동의 조회",
    )
    return dict(rows[0]) if rows else None


def _assert_reconsent_allowed(client, user_id, *, now_kst=None):
    """
    철회 후 **3개월 재동의 차단**을 저장 경로에서 강제합니다.

    왜 앱에서도 막는가: 화면만 막으면 배치가 되살립니다. 여기가 '애플리케이션' 쪽이고,
    DB 쪽은 `scorecard_consent_guard()` 트리거가 "철회 기록 자체를 지우는 것"을 막고,
    발행 쪽은 `fetch_publishable_consents()` 가 철회한 사용자를 발행 대상에서 거릅니다.

    ⚠️ 3개월이라는 숫자와 경계 규칙(정확히 3개월이 되는 순간 풀림)은 이 파일이 정하지
       않습니다 — `duel_rules.resolve_reconsent_block()` 이 단일 출처입니다(§0-3-10).
    ⚠️ 사용자에게 **언제 풀리는지 날짜를 알려 줍니다.** "지금은 안 됩니다"만 말하면 사용자는
       며칠마다 다시 눌러 보게 되고, 그건 우리가 정보를 숨긴 것입니다(§0-1 / §0-3-4).
    """
    existing = fetch_my_consent(client, user_id)
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


def revoke_consent(client, user_id, *, now_kst=None):
    """
    공개 동의를 **철회**합니다(`scorecard_public_consent.revoked_at` 기록).

    ── 이 함수가 하는 일 / 하지 않는 일 ──────────────────────────────────────────
    하는 일: 동의 행에 `revoked_at` 을 찍고, `final_confirmed` 와 항목별 동의 5개를 전부
             끕니다. 그 결과 이 사용자는 **다음 발행 대상에서 즉시 빠집니다.**
    하지 않는 일: **행을 지우지 않습니다.** `revoked_at` 한 줄은 3개월 재동의 차단을
             판정하는 데 필요한 **비공개 관리 기록**이고, 삭제 대상인 "발행된 공개 기록"과는
             다른 것입니다(스키마 §2-2 컬럼 주석에 같은 구분이 적혀 있습니다).
    하지 않는 일 ②: **이미 발행된 공개 행을 지우지 않습니다.** 그건 야간 배치만 할 수 있는
             일이라(발행표에는 사용자 쓰기 권한이 아예 없습니다 — 스키마 §3-4),
             `utils/scorecard_publish.py::run_publish_batch()` 의 0단계가 처리합니다.
             ⚠️ 즉 **철회 시점과 공개 기록이 실제로 사라지는 시점 사이에 최대 하루의 간격이
                있습니다.** 이 사실을 화면에 그대로 써야 합니다(§0-1 — 조용히 넘기지 않기).

    ── 왜 항목별 동의 5개까지 함께 끄는가 ────────────────────────────────────────
    DB CHECK(`scorecard_consent_revoked_not_confirmed`)는 "철회 + 최종확인"이 동시에 서지
    못하게만 합니다. 5개 항목을 그대로 true 로 남기면 그 상태가 "최종확인 직전까지 다 체크한
    사람"과 **글자 그대로 같아집니다** — 화면이 그 상태를 "동의 중"으로 그릴 위험이 있고,
    나중에 어떤 코드가 `final_confirmed` 하나만 켜면 CHECK 를 그냥 통과해 버립니다. 전부 꺼
    두면 그 실수는 CHECK 에 걸려 막힙니다(§0-3-9 — 조심이 아니라 구조로).

    ── 두 번 눌러도 안전합니다(멱등) ─────────────────────────────────────────────
    이미 철회된 사용자면 **아무것도 쓰지 않고** 기존 행을 그대로 돌려줍니다. `revoked_at` 을
    지금 시각으로 다시 찍으면 3개월 차단이 그만큼 **연장**되는데, 그건 사용자가 버튼을 두 번
    눌렀다는 이유로 불이익을 주는 일입니다.

    반환: 갱신된(또는 이미 철회된) 동의 행 dict.
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")

    existing = fetch_my_consent(client, user)
    if not existing:
        raise DuelDbError(
            "철회할 공개 동의 기록이 없습니다(아직 공개 순위표에 참여한 적이 없습니다)."
        )
    if existing.get("revoked_at"):
        # 이미 철회됨 — 재기록하지 않습니다(위 '멱등' 문단 참고).
        return existing

    payload = {flag: False for flag in CONSENT_ITEM_FLAGS}
    payload["final_confirmed"] = False
    payload["final_confirmed_at"] = None
    payload["revoked_at"] = _now_kst(now_kst).isoformat()

    rows = _execute(
        client.table(CONSENT_TABLE).update(payload).eq("user_id", user),
        "공개 동의 철회",
    )
    return _first_row(rows, "공개 동의 철회")


# -----------------------------------------------------------------------------
# A-2. 무작위 닉네임 (스키마 §2-1)
# -----------------------------------------------------------------------------
#: 닉네임 후보를 다시 뽑아 보는 최대 횟수. 공간이 약 214만 가지나 되어서
#: (`duel_rules.nickname_space_size()`) 실제로는 첫 시도에서 끝납니다 — 이 숫자는
#: "무한 루프를 만들지 않는다"는 안전장치이지 성능 조절값이 아닙니다.
NICKNAME_MAX_ATTEMPTS = 8


def ensure_nickname(client, user_id):
    """
    이 사용자의 공개용 **무작위 닉네임**을 보장합니다(없으면 만들고, 있으면 그대로).

    🔴 결투와 달리 **창유형 인자가 없습니다.** "내 성적표"는 사용자당 포트폴리오가 하나뿐
       이므로 `scorecard_nicknames` 의 기본키가 `user_id` 하나입니다(스키마 §2-1). 원화
       성적표와 달러 성적표는 같은 사용자의 같은 닉네임으로 나갑니다 — 통화별로 이름이
       갈리면 "이 두 이름이 같은 사람"임을 숨기는 것도 드러내는 것도 아닌 어중간한 상태가
       되고, 오너가 확정한 모델은 "사용자 = 닉네임 1개"입니다.

    ── 언제 부르는가 (호출 시점이 설계의 일부입니다) ─────────────────────────────
    🔴 **공개 동의 화면에서, 첫 `save_consent()` 직전(또는 직후)에 한 번.**
       "내 성적표" 화면을 여는 것만으로는 만들지 않습니다:
         · 혼자 성적표만 쓰는 사용자에게는 **공개용 별명이라는 물건 자체가 필요 없습니다.**
           안 만들면 그 사람은 공개 세계에 이름조차 존재하지 않습니다 — 기본값은 비공개라는
           원칙의 가장 구체적인 형태입니다(§0-3-8).
         · 닉네임은 한 번 만들면 **바꿀 수 없습니다**(스키마 §3-1 에 update 정책이 없습니다).
           쓰지도 않을 사람에게 미리 발급하면, 나중에 그 사람이 공개에 참여할 때 예전에 찍힌
           이름을 그대로 써야 합니다.
       ⚠️ 반대로 **발행 배치가 닉네임을 만들지는 않습니다.** 배치는 권한상 만들 수는 있지만,
          그러면 "닉네임이 없는 참가자"를 배치가 조용히 메꾸게 되고 그 사용자가 정말
          동의했는지의 판단이 두 곳으로 갈라집니다. 닉네임이 없는 사용자를 만나면
          `utils/scorecard_publish.py` 는 **발행에서 빼고 그 사실을 로그에 남깁니다.**

    ── 유일성은 DB 가 판정합니다 ─────────────────────────────────────────────────
    "이미 쓰는 이름인가"를 앱이 먼저 조회해서 정하면, 조회와 삽입 사이에 다른 세션이 같은
    이름을 넣는 경합을 막을 수 없습니다. 그래서 **그냥 넣어 보고, unique 충돌이면 새 후보로
    다시 넣습니다**(스키마 §2-1 의 `nickname text not null unique`).

    ── 두 탭에서 동시에 눌러도 안전합니다 ────────────────────────────────────────
    기본키가 `user_id` 라 두 번째 삽입은 충돌합니다. 그때 이 함수는 "내 이름이 이미 생겼나"를
    다시 확인하고 **그 이름을 돌려줍니다.** 새 이름을 또 만들지 않습니다 — 이름이 둘이면 과거
    발행 행과 대응이 끊깁니다.

    반환: `{"user_id": ..., "nickname": ..., ...}` dict.
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")

    existing = _fetch_nickname_row(client, user)
    if existing:
        return existing

    last_error = None
    for _attempt in range(NICKNAME_MAX_ATTEMPTS):
        # 🔴 후보는 인자 없는 순수 난수 함수가 만듭니다 — user_id·이메일·시각에서 유도하지
        #    않습니다(해시도 쓰지 않습니다: 입력 공간이 "우리 서비스의 사용자 id 목록"처럼
        #    좁으면 전수 대입으로 즉시 역조회됩니다 — §0-3-9). 여기서 user 를 섞어 넣고 싶은
        #    유혹을 이기세요.
        candidate = duel_rules.generate_nickname()
        try:
            rows = _execute(
                client.table(NICKNAMES_TABLE).insert(
                    {"user_id": user, "nickname": candidate}),
                "닉네임 생성",
            )
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise                       # 진짜 사고를 재시도로 덮지 않습니다(§0-1).
            last_error = exc
            # 충돌의 원인은 둘 중 하나입니다:
            #   ① user_id 기본키 — 다른 탭/요청이 방금 내 이름을 만들었다 → 그걸 씁니다.
            #   ② nickname unique — 남이 쓰는 이름을 뽑았다 → 새 후보로 다시.
            already = _fetch_nickname_row(client, user)
            if already:
                return already
            continue
        if rows:
            return _first_row(rows, "닉네임 생성")
        # insert 가 0행을 돌려주는 경우(RLS 가 막은 남의 행 등)는 성공이 아닙니다.
        raise DuelDbError("닉네임을 만들지 못했습니다(접근이 차단됐습니다).")

    raise DuelDbError(
        f"닉네임 후보를 {NICKNAME_MAX_ATTEMPTS}번 만들었는데 전부 이미 쓰이는 이름이었습니다."
        " 임의의 이름을 억지로 붙이지 않고 중단합니다 —"
        f" 후보 공간({duel_rules.nickname_space_size():,}가지)이 참가자 수에 비해 좁아졌는지"
        f" 확인이 필요합니다. (마지막 오류: {last_error})"
    )


def fetch_my_nickname(client, user_id):
    """
    이 사용자의 공개용 닉네임 행(없으면 None) — **만들지 않고 읽기만** 합니다.

    왜 `ensure_nickname()` 을 그대로 쓰지 않는가: 그 함수는 없으면 **만듭니다.** 화면을
    그리는 것만으로 닉네임이 발급되면, 동의 화면을 열어 보기만 하고 나간 사용자에게도 공개용
    별명이 생깁니다 — 한 번 만든 닉네임은 바꿀 수 없습니다(스키마 §3-1 에 update 정책이
    없습니다). **화면을 그리는 행위는 아무것도 만들지 않아야 합니다.**
    """
    _require_client(client)
    user = _require_text(user_id, "사용자 ID")
    return _fetch_nickname_row(client, user)


def _fetch_nickname_row(client, user_id):
    """이 사용자의 닉네임 행(없으면 None). 사용자 세션·배치 클라이언트 양쪽에서 같은 모양입니다."""
    rows = _execute(
        client.table(NICKNAMES_TABLE).select("*").eq("user_id", user_id).limit(1),
        "닉네임 조회",
    )
    return dict(rows[0]) if rows else None


# -----------------------------------------------------------------------------
# A-3. 발행표 **읽기 전용** 조회
# -----------------------------------------------------------------------------
#  🔴 이 절에서 발행표를 만지는 유일한 자리이고, **select 밖으로는 한 발짝도 나가지 않습니다.**
#
#     왜 A 절에 두는가: 순위표 화면은 로그인한 **일반 사용자**가 보는 화면이고, 이 두 표는
#     스키마 §3-4 에서 로그인 사용자에게 **select 만** 준 표입니다(insert/update/delete 정책은
#     아무에게도 없습니다). 즉 사용자 세션 클라이언트로 읽는 것이 정상 경로입니다. 반대로 이
#     조회를 B 절에 두면 화면이 B 절 함수를 부르게 되고, 그러면 앱 서버가 **RLS 를 우회하는
#     배치 키**를 갖게 됩니다(§0-3-8).
#
#     🔒 이 세 함수가 지키는 것(버그가 나도 새어나갈 수 없게):
#       ① **`select("*")` 를 쓰지 않습니다.** 읽는 컬럼을 하나하나 적습니다. 나중에 누가
#          발행표에 컬럼을 하나 더 붙여도, 이 함수가 그것을 화면으로 날라 주는 일은 없습니다.
#       ② 원본 표(`holdings` · `profiles`)를 **부르지 않습니다.** 순위표 화면은 그 표의
#          이름조차 몰라도 됩니다.
#       ③ 순위를 **계산하지 않습니다.** 배치가 미리 계산해 넣은 `rank` 컬럼으로 정렬만
#          합니다(§0-3-2 — 방문자 수만큼 전체 스캔이 돌지 않게).
#
#     ⚠️ 이 표는 **날짜별 발행 이력이 쌓이는 표**입니다(그날 발행분을 통째로 갈아끼우지, 과거
#        날짜를 지우지 않습니다). 그래서 날짜를 지정하지 않고 읽으면 여러 날짜가 섞입니다.
#        화면은 `fetch_public_leaderboard_latest_date()` 로 **그 그룹의 최신 발행일을 한 번
#        확정한 뒤**, 그 날짜를 아래 두 함수에 명시적으로 넘깁니다.
# -----------------------------------------------------------------------------
#: 순위표 화면에 실어 보내는 컬럼(위 ①). 이 목록에 `id` 를 넣지 마세요 — 화면에 쓸모가 없고,
#: 발행 순서(= 가입 순서와 상관관계가 생길 수 있는 값)를 노출합니다.
PUBLIC_LEADERBOARD_COLUMNS = "published_date,currency,bracket_key,rank,nickname,return_pct"

#: 공개 보유종목 화면에 실어 보내는 컬럼(위 ①).
PUBLIC_HOLDINGS_COLUMNS = "published_date,currency,nickname,ticker,stock_name,quantity,buy_amount"


def fetch_public_leaderboard_latest_date(client, *, currency, bracket_key):
    """
    이 그룹(통화 × 체급)이 **가장 최근에 발행된 날짜**(`YYYY-MM-DD`) 또는 None.

    None 은 오류가 아니라 정상 상태입니다 — ① 아직 아무도 이 그룹에 없거나, ② 최소 인원을
    못 채워 발행되지 않았거나, ③ 발행됐다가 인원이 줄어 청소로 지워진 경우입니다. 화면은 이
    셋을 "아직 공개할 만큼 사람이 모이지 않았습니다"로 **똑같이** 안내합니다 — 셋을 구분해
    보여주면 그 자체가 "이 구간에 몇 명쯤 있는지"에 대한 정보가 되고, 그건 소수 N 역추적의
    재료입니다.

    질의 1개(`limit(1)`)입니다.
    """
    _require_client(client)
    code = _require_currency(currency)
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        client.table(PUBLIC_LEADERBOARD_TABLE).select("published_date")
        .eq("currency", code).eq("bracket_key", bracket)
        .order("published_date", desc=True).limit(1),
        "공개 순위표 발행일 조회",
    )
    value = (rows[0] or {}).get("published_date") if rows else None
    return str(value)[:10] if value else None


def fetch_public_leaderboard(client, *, currency, bracket_key, published_date=None,
                             limit=duel_rules.LEADERBOARD_PAGE_SIZE, offset=0,
                             order_desc=False):
    """
    발행된 공개 순위표 한 페이지를 읽습니다. 반환: 행 dict 목록.

    인자
        currency       : "KRW" / "USD"
        bracket_key    : 그 통화의 체급 식별자
                         (`duel_rules.BRACKET_KEYS` 또는 `BRACKET_KEYS_USD` 중 하나 —
                          🔴 두 집합은 서로 다릅니다. 통화와 짝이 맞지 않는 키를 넘기면
                          결과가 0행이 됩니다)
        published_date : 발행일. **화면은 반드시 넘깁니다**
                         (`fetch_public_leaderboard_latest_date()` 로 먼저 확정).
                         None 이면 날짜를 가리지 않습니다 — 과거 이력을 통째로 훑어야 하는
                         관리 목적에만 쓰세요.
        limit / offset : 페이지네이션(기본 한 페이지 = `duel_rules.LEADERBOARD_PAGE_SIZE`).
                         "상위 500 / 하위 500"이라는 **구간 상한**은 화면이 아니라
                         `duel_rules.leaderboard_page_bounds()` 가 계산해 여기로 넘깁니다.
        order_desc     : False 면 1위부터(= 상위 500), True 면 꼴찌부터(= 하위 500).

    ── 동순위(같은 rank)와 페이지 경계 ──────────────────────────────────────────
    순위는 동점자가 **같은 값을 공유**합니다(`duel_rules.rank_participants()`). 정렬 키가
    `rank` 하나뿐이면 같은 rank 안의 순서가 질의마다 달라질 수 있고, 그러면 페이지를 넘길 때
    같은 사람이 두 번 나오거나 한 명이 통째로 건너뛰어집니다. 그래서 `nickname` 을 **2차 정렬
    키**로 함께 씁니다.
    ⚠️ 이건 순위를 다시 매기는 것이 **아닙니다.** 화면에 보이는 등수는 발행표의 `rank`
       그대로이고(동점자는 같은 등수로 보입니다), 닉네임 정렬은 "같은 등수 안에서 목록에
       찍히는 차례"를 고정하는 용도일 뿐입니다.
    """
    _require_client(client)
    code = _require_currency(currency)
    bracket = _require_text(bracket_key, "체급 식별자")
    count = _require_positive_int(limit, "조회 개수")
    start = _require_offset(offset, "건너뛸 개수")

    query = (client.table(PUBLIC_LEADERBOARD_TABLE).select(PUBLIC_LEADERBOARD_COLUMNS)
             .eq("currency", code).eq("bracket_key", bracket))
    if published_date is not None:
        query = query.eq("published_date", _iso_date(published_date, "발행일"))
    query = (query.order("rank", desc=bool(order_desc))
                  .order("nickname", desc=bool(order_desc)))
    rows = _execute(query.range(start, start + count - 1), "공개 순위표 조회")
    return [dict(row) for row in rows]


def fetch_public_holdings_for_nickname(client, nickname, *, published_date=None,
                                       currency=None):
    """
    한 참가자(닉네임)의 **발행된** 보유종목을 읽습니다 — "내 보유종목이 순위표에서 다른
    사람에게 **개별 열람** 가능하게 공개됩니다"가 실제로 일어나는 자리입니다.

    인자
        nickname       : 순위표 행에서 사용자가 고른 닉네임(이 표에는 이 값 말고 사람을
                         가리키는 것이 아무것도 없습니다 — 스키마 §2-4).
        published_date : 그 순위표 행의 발행일. 화면은 반드시 넘깁니다(날짜를 안 걸면 과거
                         발행분까지 같이 나와 같은 종목이 여러 번 보입니다).
        currency       : 그 순위표 행의 통화. 한 사람이 원화·달러 성적표를 둘 다 공개했다면
                         닉네임은 같으므로, **화면이 보고 있는 축을 반드시 걸어야** 원화
                         순위표에서 그 사람의 달러 종목까지 함께 보이는 일이 없습니다.
                         🔴 두 통화를 한 목록에 섞어 보여주면 사용자는 그 합을 머릿속에서
                            더하게 되고, 이 앱에는 환율 시계열이 없습니다(§0-1).

    ── 동의하지 않은 항목은 여기서 거르지 않습니다(그럴 필요가 없습니다) ────────────
    `quantity` · `buy_amount` 는 동의가 없으면 **발행 배치가 애초에 null 로 넣습니다**(0 이나
    빈 문자열로 채우지 않습니다). 그리고 `consent_holdings` 자체가 없으면 이 표에 **행이
    만들어지지 않습니다.** 즉 여기서 다시 걸러야 할 것이 없고, 화면은 null 을 "비공개"로
    그리기만 하면 됩니다. 필터를 여기에 또 만들면 "동의 판정"이 두 곳에 존재하게 됩니다.

    ⚠️ `stock_name` 은 사용자가 자유 입력한 값입니다 — 화면은 렌더링하는 모든 자리에서
       `esc()` 를 반드시 적용해야 합니다(스키마 §2-4 컬럼 주석 / §0-3-9).
    """
    _require_client(client)
    name = _require_text(nickname, "닉네임")

    query = (client.table(PUBLIC_HOLDINGS_TABLE).select(PUBLIC_HOLDINGS_COLUMNS)
             .eq("nickname", name))
    if published_date is not None:
        query = query.eq("published_date", _iso_date(published_date, "발행일"))
    if currency is not None:
        query = query.eq("currency", _require_currency(currency))
    rows = _execute(query.order("ticker"), "공개 보유종목 조회")
    return [dict(row) for row in rows]


# #############################################################################
#
#  B 절 — 배치용 (service_role · 야간 GitHub Actions 전용)
#
#  🔴 **앱 프로세스에서 이 절의 함수를 부르지 마세요.** 여기 함수들은 RLS 를 우회하는
#     클라이언트를 받습니다. 화면 코드가 이 절을 부르기 시작하면, 그 순간 앱 서버에
#     service_role 키가 필요해지고 이 모듈의 모든 RLS 가 장식이 됩니다(§0-3-8).
#
#  §0-3-2: 이 절의 어떤 함수도 사용자 수에 비례해 쿼리를 늘리지 않습니다. 전체를 한 번 읽고,
#          여러 행을 한 번에 씁니다(청크는 "요청 하나가 지나치게 커지지 않게 자르는 것"이지
#          사용자별 호출이 아닙니다).
#
#  이 절의 규율 하나 더: **판단하지 않습니다.** "누가 발행 대상인가", "체급이 무엇인가",
#  "순위가 몇 등인가"는 전부 `utils/duel_rules.py`(순수 규칙)와
#  `utils/scorecard_publish.py`(오케스트레이션)가 정합니다. 여기 함수는 **이미 결정된 행을
#  그대로 담아 보내거나, 지정된 것을 지울 뿐**입니다. 여기에 "동의했으면 이 필드를 채우고..."
#  같은 조건문이 생기면 게이팅 규칙이 두 곳에 존재하게 되고 언젠가 둘이 갈라집니다.
#
# #############################################################################

def fetch_publishable_consents(service_client):
    """
    (배치 전용) **발행 대상 사용자의 동의 행**을 한 번의 질의로 전부 읽습니다.

    거르는 조건은 둘입니다 — `final_confirmed = true` **그리고** `revoked_at is null`.
      · 사실 DB CHECK(`scorecard_consent_revoked_not_confirmed`)가 이미 "철회 + 최종확인"을
        동시에 설 수 없게 막고 있어서, 앞 조건 하나만으로도 결과는 같습니다.
      · 그래도 **둘 다 겁니다.** 재동의 차단은 "앱과 배치 양쪽에서" 확인하는 규칙이고, 여기가
        그 '배치' 쪽입니다. 조건 하나를 아끼는 것보다, 나중에 CHECK 를 손대는 사람이 이 필터를
        보고 "아, 여기도 같은 규칙이 있구나"를 아는 편이 낫습니다.

    ⚠️ 항목별 동의 5개를 여기서 거르지 **않습니다.** `scorecard_consent_final_requires_all`
       CHECK 때문에 `final_confirmed=true` 인 행은 5개가 전부 true 임이 DB 수준에서
       보장되지만, 그 보장을 **믿고 넘어가지 않고**
       `scorecard_publish.assert_full_consent()` 가 행마다 다시 확인합니다. 여기서 필터로
       처리하면 "조건에 안 맞아서 빠진 사람"이 조용히 사라지는데, 그건 데이터가 이상하다는
       신호를 삼키는 일입니다(§0-1).
    """
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE).select(
        "user_id," + ",".join(CONSENT_ITEM_FLAGS) + ",final_confirmed,revoked_at"
    ).eq("final_confirmed", True)
    query = _filter_is_null(query, "revoked_at")
    rows = _execute(query, "발행 대상 동의 조회")
    return [dict(row) for row in rows]


def fetch_revoked_consent_users(service_client):
    """
    (배치 전용) **철회한 사용자 목록**을 한 번의 질의로 읽습니다.

    야간 배치가 "철회한 사람의 발행 기록을 전부 지우는" 청소 단계에서 씁니다. "지난 실행 이후
    새로 철회된 것"만 고르지 않고 **철회된 것 전부**를 매번 봅니다:
      · 배치가 하루 걸렀거나 중간에 실패해도 다음 실행이 스스로 따라잡습니다(자가 치유).
      · "어디까지 처리했는지"를 기억하는 상태 파일이 필요 없습니다. 그런 파일이 손상되면
        누군가의 공개 기록이 **영원히 안 지워진 채로 남습니다** — 이 모듈에서 가장 나쁜 실패.
      · 삭제는 멱등이라 이미 지운 것을 다시 지워도 아무 일도 일어나지 않습니다.
    """
    _require_client(service_client, batch=True)
    query = service_client.table(CONSENT_TABLE).select("user_id,revoked_at")
    query = _filter_not_null(query, "revoked_at")
    rows = _execute(query, "철회 사용자 조회")
    return [dict(row) for row in rows]


def fetch_nicknames_for_users(service_client, user_ids):
    """
    (배치 전용) 여러 사용자의 닉네임을 **한 번에**(청크 단위로) 읽습니다(§0-3-2).
    반환: `{user_id: nickname}`.

    ⚠️ `user_ids` 는 **필수**입니다(기본값 None 으로 "전부 읽기"를 만들지 않았습니다).
       이 표는 닉네임 ↔ 사용자 대응표라, 통째로 읽는 편의 함수가 있으면 언젠가 누군가
       "일단 다 읽어 놓고 필요한 것만 쓰지"라고 하게 됩니다. 필요한 사용자만 읽습니다.
    """
    _require_client(service_client, batch=True)
    ids = sorted({str(value).strip() for value in (user_ids or []) if str(value).strip()})
    if not ids:
        return {}
    mapping = {}
    for start in range(0, len(ids), CHUNK_SIZE):
        rows = _execute(
            service_client.table(NICKNAMES_TABLE).select("user_id,nickname")
            .in_("user_id", ids[start:start + CHUNK_SIZE]),
            "닉네임 일괄 조회",
        )
        for row in rows:
            nickname = str((row or {}).get("nickname") or "").strip()
            user_id = str((row or {}).get("user_id") or "").strip()
            if nickname and user_id:
                mapping[user_id] = nickname
    return mapping


def fetch_bracket_assignments(service_client, season_key):
    """
    (배치 전용) **이번 시즌의 체급 배정 기록 전부**를 한 번의 질의로 읽습니다(스키마 §2-3).
    반환: `{(user_id, currency): {"user_id", "currency", "season_key", "bracket_key"}}`.

    🔴 키가 `(user_id, currency)` 인 이유: 원화 성적표와 달러 성적표는 매입원가합계 자체가
       다른 통화라 체급도 통화별로 따로 매깁니다(표의 기본키도
       `(user_id, currency, season_key)` 입니다). 사용자 id 하나로 묶으면 한 통화의 체급이
       다른 통화를 덮어씁니다.

    이 결과가 `duel_rules.resolve_bracket_for_season[_usd]()` 의 첫 인자가 되고, 그 함수가
    "시즌 중이면 그대로 유지"를 강제합니다. 배치가 체급을 스스로 정하지 않게 하려면 **먼저
    읽어야** 합니다 — 이 질의를 빼먹으면 시즌 고정 규칙이 조용히 사라집니다.
    """
    _require_client(service_client, batch=True)
    season = _require_text(season_key, "시즌 식별자")
    rows = _execute(
        service_client.table(BRACKET_ASSIGNMENTS_TABLE)
        .select("user_id,currency,season_key,bracket_key").eq("season_key", season),
        "체급 배정 조회",
    )
    index = {}
    for row in rows:
        user_id = str((row or {}).get("user_id") or "").strip()
        currency = str((row or {}).get("currency") or "").strip()
        if user_id and currency:
            index[(user_id, currency)] = dict(row)
    return index


def insert_bracket_assignments(service_client, rows):
    """
    (배치 전용) **새로 배정된** 체급을 기록합니다(insert 만 — 스키마 §3-8). 반환: 넣은 행 수.

    ⚠️ upsert 가 아니라 insert 인 것이 이 함수의 핵심입니다. 배치에도 update/delete 권한이
       없어서(스키마 §3-8 이 service_role 에게서도 회수합니다) 이미 배정된 체급은 **물리적
       으로 바꿀 수 없습니다.** "체급은 시즌 동안 고정"이 앱의 조심성이 아니라 DB 권한으로
       강제되는 자리입니다.
    ⚠️ 그래서 중복 키 충돌은 **사고가 아니라 정상**입니다(두 배치가 겹쳐 돌거나, 같은 날 두 번
       실행). 조용히 흡수하고 그 청크를 세지 않습니다 — 이미 있는 값이 이깁니다.
    """
    _require_client(service_client, batch=True)
    payload = []
    for row in rows or []:
        payload.append({
            "user_id": _require_text((row or {}).get("user_id"), "사용자 ID"),
            "currency": _require_currency((row or {}).get("currency")),
            "season_key": _require_text((row or {}).get("season_key"), "시즌 식별자"),
            "bracket_key": _require_text((row or {}).get("bracket_key"), "체급 식별자"),
        })
    if not payload:
        return 0
    _assert_unique_keys(payload, ("user_id", "currency", "season_key"), "체급 배정 요청")

    inserted = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        try:
            _execute(service_client.table(BRACKET_ASSIGNMENTS_TABLE).insert(chunk),
                     "체급 배정 기록")
        except DuelDbError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            continue        # 이미 배정된 시즌 — 기존 값이 이깁니다(위 주석 참고).
        inserted += len(chunk)
    return inserted


def fetch_holdings_for_users(service_client, user_ids):
    """
    (배치 전용) 🔴 **발행에 동의한 사용자의** "내 성적표" 실제 보유종목을 읽습니다.

    ── 이 함수가 이 파일에서 가장 조심스러운 자리인 이유 ─────────────────────────
    이건 사용자의 **진짜 자산 데이터**(`public.holdings`)입니다. 동의 없는 사용자의
    holdings 를 읽는 코드 경로가 **하나라도** 있으면 §0-3-8 위반입니다. 그래서 이 함수는
    이렇게 생겼습니다:
      · `user_ids` 가 **필수 인자**입니다. 기본값이 없습니다. "안 주면 전부"라는 편의 경로를
        만들지 않았습니다 — 그 한 줄이 곧 위 문장의 위반입니다.
      · 빈 목록이면 **질의를 아예 보내지 않습니다.** 빈 `in` 필터가 실수로 전체 조회가 되는
        일을 구조적으로 막습니다.
      · ⚠️ `utils/report_db.py::fetch_all_holdings()` 를 **쓰지 않습니다.** 그 함수는 이름
        그대로 **전체 사용자**의 보유종목을 읽습니다(리포트 스냅샷 배치는 전원이 대상이라
        그게 맞습니다). 여기서 그걸 부르면 동의하지 않은 사람의 자산이 이 배치의 메모리에
        올라옵니다. 필터가 다르므로 질의를 따로 씁니다.
      · ⚠️ `scorecard_db.fetch_holdings()` 도 쓰지 않습니다. 그 함수는 **로그인한 본인
        세션**이 자기 것 하나를 읽는 함수이고(`select("*")` 이라 컬럼도 전부 가져옵니다),
        사용자 한 명당 질의 하나가 나갑니다(§0-3-2 위반). 여기서는 필요한 컬럼만, 여러
        사용자를 한 요청에 묶어 읽습니다.
      · `select("*")` 를 쓰지 않습니다 — 읽는 컬럼을 하나하나 적습니다.
      · 읽기만 합니다. 이 파일 어디에도 `holdings` 에 쓰는 코드는 없습니다.

    반환: 보유 행 목록(`user_id` 포함, 사용자가 섞여 있음). 금액 계산은 이 파일이 하지 않고
          `utils/scorecard_publish.py` 가 `utils/scorecard_db.py` 의 **진짜 평가 함수**로
          합니다(§0-3-10).
          ⚠️ `quantity` · `avg_purchase_price` 는 DB 의 numeric 이라 드라이버에 따라 문자열로
             올 수 있습니다. `scorecard_db.evaluate_holding()` 이 `float()` 로 정규화하므로
             여기서 손대지 않습니다(같은 변환을 두 번 하지 않기).
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
            "발행용 보유종목 조회",
        )
        result.extend(dict(row) for row in rows)
    return result


# ── 발행표 쓰기·지우기 ─────────────────────────────────────────────────────────
def delete_published_rows_for_date(service_client, published_date):
    """
    (배치 전용) **그날 발행분을 통째로 지웁니다**(두 표 각각 질의 1개).

    "부분 갱신이 아니라 그날 발행분을 통째로 갈아끼우는 방식"인 이유는 안전입니다. 부분
    갱신은 "어제는 있었는데 오늘은 자격을 잃은 행"을 **남깁니다** — 지워야 할 것을 지우는
    코드는 항상 넣기 쉬운 코드가 아니고, 하나 빠뜨리면 그 행은 계속 공개된 채로 남습니다.
    통째로 지우고 다시 쓰면 "남는" 경우가 구조적으로 없습니다.

    ⚠️ 지우고 나서 넣기 전에 배치가 죽으면 그날 순위표가 잠깐 비어 있게 됩니다. 그 방향이
       안전한 쪽입니다 — 반대(지워야 할 것이 남아 있는 상태)는 §0-3-8 사고입니다.
    """
    _require_client(service_client, batch=True)
    day = _iso_date(published_date, "발행일")
    # 표 이름을 반복문 변수로 감싸지 않고 **한 줄씩 그대로** 씁니다. §0-3-8 검토와 테스트의
    # AST 검사가 "어느 함수가 어느 표에 쓰는가"를 코드에서 바로 읽을 수 있어야 하기
    # 때문입니다(짧게 쓰는 것보다 보이는 게 중요).
    _execute(service_client.table(PUBLIC_LEADERBOARD_TABLE).delete()
             .eq("published_date", day), "순위표 당일 발행분 삭제")
    _execute(service_client.table(PUBLIC_HOLDINGS_TABLE).delete()
             .eq("published_date", day), "보유종목 당일 발행분 삭제")
    return None


def delete_published_rows_for_nicknames(service_client, nicknames):
    """
    (배치 전용) 🔴 지정한 닉네임의 발행 행을 **모든 날짜에서 영구 삭제**합니다.

    철회하면 그 사용자의 발행된 공개 기록을 **전부 영구 삭제**합니다 — 과거 순위, 과거 발행
    수익률, 발행된 보유종목 행까지 **숨김이 아니라 삭제**입니다. 그래서 `published_date`
    필터를 **일부러 걸지 않습니다.** 오늘 것만 지우면 어제 것이 그대로 남고, 그건 "삭제했다"고
    말할 수 없는 상태입니다.

    ⚠️ 사용자가 아니라 **닉네임**으로 지웁니다. 발행표에는 `user_id` 가 아예 없기 때문이고
       (스키마 §2-4), 그게 이 설계의 핵심입니다 — 공개표만 읽어서는 누구인지 알 수 없습니다.
       닉네임 ↔ 사용자 대응은 비공개 `scorecard_nicknames` 와 이 배치 안에만 있습니다.
    ⚠️ 닉네임은 한 번 만들면 바뀌지 않으므로(스키마 §3-1 에 update 정책 없음), 이 삭제가 과거
       행을 놓칠 일이 없습니다.
    ⚠️ 통화를 가리지 않습니다 — 철회는 "내 성적표 공개"라는 하나의 결정이고, 원화만 지우고
       달러를 남기는 상태는 존재할 수 없습니다.

    반환: 실제로 지운 행 수(두 표 합계). PostgREST 가 지운 행을 돌려주지 않는 설정이면 0 이
          나올 수 있어, 호출부는 이 값을 "성공 여부"로 쓰지 않습니다.
    """
    _require_client(service_client, batch=True)
    names = sorted({str(value).strip() for value in (nicknames or []) if str(value).strip()})
    if not names:
        return 0

    removed = 0
    for start in range(0, len(names), CHUNK_SIZE):
        chunk = names[start:start + CHUNK_SIZE]
        # 표 이름을 한 줄씩 그대로(위 함수와 같은 이유).
        removed += len(_execute(
            service_client.table(PUBLIC_LEADERBOARD_TABLE).delete().in_("nickname", chunk),
            "철회 사용자의 발행 순위 삭제",
        ))
        removed += len(_execute(
            service_client.table(PUBLIC_HOLDINGS_TABLE).delete().in_("nickname", chunk),
            "철회 사용자의 발행 보유종목 삭제",
        ))
    return removed


def leaderboard_has_any_rows(service_client):
    """
    (배치 전용) 순위표 발행표에 **행이 하나라도 있는가**(질의 1개, `limit(1)`).

    최소 인원 미달 청소를 시작하기 전의 값싼 사전 점검입니다. 청소는 "발행될 수 있는 모든
    그룹"(KRW 9 + USD 9 = 18개, 상수)을 훑는데, **아직 한 번도 발행된 적이 없는 초기 운영
    기간에는 그 18번이 전부 헛걸음**입니다. 이 한 줄이 그걸 1번으로 줄입니다.

    ⚠️ "없으면 건너뛴다"가 안전한 이유: 표가 비어 있으면 지울 것도 없습니다. 반대 방향의
       실수(있는데 없다고 판단)는 이 질의가 `limit(1)` 조회 하나뿐이라 생기지 않습니다.
    """
    _require_client(service_client, batch=True)
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).select("id").limit(1),
        "발행표 존재 확인",
    )
    return bool(rows)


def fetch_published_group_index(service_client, currency, bracket_key):
    """
    (배치 전용) 한 그룹(통화 × 체급)이 **과거에 발행된 적이 있는지**와, 있다면 어느 날짜에
    누구(닉네임)로 실렸는지를 읽습니다. 최소 인원 미달 그룹을 청소할 때만 씁니다.

    ⚠️ 인원이 임계값을 **넘는** 그룹에는 절대 부르지 마세요 — 그런 그룹은 정의상 500명
       이상이라 결과가 큽니다. 호출부(`utils/scorecard_publish.py`)는 **미달 그룹에만**
       부릅니다. 미달 그룹은 500명 미만이라 결과 크기가 구조적으로 작습니다.

    반환: `{published_date: [nickname, ...]}`
    """
    _require_client(service_client, batch=True)
    code = _require_currency(currency)
    bracket = _require_text(bracket_key, "체급 식별자")
    rows = _execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).select("published_date,nickname")
        .eq("currency", code).eq("bracket_key", bracket),
        "발행 이력 조회",
    )
    index = {}
    for row in rows:
        day = (row or {}).get("published_date")
        nickname = str((row or {}).get("nickname") or "").strip()
        if day and nickname:
            index.setdefault(str(day)[:10], []).append(nickname)
    return index


def delete_published_group(service_client, currency, bracket_key, *, holdings_index=None):
    """
    (배치 전용) 최소 인원 미달 그룹의 발행 행을 **모든 날짜에서** 지웁니다.

    임계값 미만인 구간은 아예 발행하지 않고, **이미 발행돼 있던 행도 제거합니다.** 참가자가
    501명이었다가 499명으로 줄어든 경우가 정확히 이 경우입니다.

    ── 두 표를 다르게 지우는 이유 ────────────────────────────────────────────────
    `scorecard_public_leaderboard` 에는 `bracket_key` 컬럼이 있어서 **질의 한 방**으로
    끝납니다. `scorecard_public_holdings` 에는 없습니다(스키마가 의도적으로 뺐습니다 —
    체급은 순위표의 축이지 보유종목의 속성이 아니고, 중복 저장하면 두 표가 어긋날 여지가
    생기기 때문). 그래서 보유종목 쪽은 **"그 그룹에 실렸던 날짜 × 그 날짜의 닉네임"** 으로
    지웁니다. 날짜별로 나누는 이유: 시즌이 바뀌면 같은 닉네임이 다른 체급으로 옮겨갈 수 있어서
    날짜를 묶어서 지우면 **다른 시즌의 정상 행까지 지울 수 있습니다.**
      🔴 그리고 통화를 함께 겁니다. 한 사람이 원화·달러를 둘 다 공개했다면 두 표에 **같은
         닉네임**이 있으므로, 통화를 안 걸면 원화 그룹 청소가 그 사람의 달러 보유종목까지
         지워 버립니다.

    ⚠️ 질의 수는 (1 + 그 그룹이 발행된 날짜 수)입니다. 사용자 수에 비례하지 않으므로 §0-3-2
       위반이 아니고, 대부분의 밤에는 발행된 날짜가 0 이라 질의 1개로 끝납니다.

    인자
        holdings_index : `fetch_published_group_index()` 결과. None 이면 여기서 읽습니다.
    """
    _require_client(service_client, batch=True)
    code = _require_currency(currency)
    bracket = _require_text(bracket_key, "체급 식별자")

    index = (fetch_published_group_index(service_client, code, bracket)
             if holdings_index is None else dict(holdings_index))
    if not index:
        return 0            # 발행된 적이 없는 그룹 — 지울 것도, 보낼 질의도 없습니다.

    removed = len(_execute(
        service_client.table(PUBLIC_LEADERBOARD_TABLE).delete()
        .eq("currency", code).eq("bracket_key", bracket),
        "최소 인원 미달 그룹 순위 삭제",
    ))
    for day, nicknames in sorted(index.items()):
        names = sorted({str(name).strip() for name in nicknames if str(name).strip()})
        for start in range(0, len(names), CHUNK_SIZE):
            removed += len(_execute(
                service_client.table(PUBLIC_HOLDINGS_TABLE).delete()
                .eq("published_date", day).eq("currency", code)
                .in_("nickname", names[start:start + CHUNK_SIZE]),
                "최소 인원 미달 그룹 보유종목 삭제",
            ))
    return removed


def write_public_leaderboard(service_client, published_date, rows):
    """
    (배치 전용) 순위표 발행 행을 **한 번에** 넣습니다(청크 단위 insert). 반환: 넣은 행 수.

    ⚠️ 이 함수는 **아무것도 판단하지 않습니다.** 어떤 사용자가 발행 대상인지, 수익률을 실을지
       말지, 순위가 몇 등인지는 전부 호출부가 정해서 넘깁니다. 여기서 값을 채우거나 바꾸는
       코드가 생기면, 동의 게이팅 규칙이 두 곳에 존재하게 됩니다(§0-3-8).

    ⚠️ 그래도 **최소한의 자기 방어**는 합니다 — `user_id` / `id` 같은 키가 payload 에 섞여
       있으면 **거절**합니다(`duel_db._assert_no_identity_fields()` 재사용). 발행표에는 그
       컬럼이 아예 없어서 PostgREST 가 어차피 거절하지만, 그때 나오는 메시지
       ("column ... does not exist")로는 **무엇이 위험했는지**가 드러나지 않습니다. 여기서
       잡아 "발행표에 식별자를 실으려 했다"고 말해 줍니다.
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
    # 🔴 유니크 키에 `rank` 가 아니라 `nickname` 이 들어가는 이유: 동점(수익률이 완전히 같은
    #    경우)이 실제로 생기고, 동점자는 **같은 rank 를 공유**합니다(스키마 §2-4 주석).
    _assert_unique_keys(payload, ("published_date", "currency", "bracket_key", "nickname"),
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

    ⚠️ 유니크 키에 `currency` 가 들어갑니다(스키마 §2-4 의
       `scorecard_public_holdings_unique`). 한 사람이 원화·달러를 둘 다 공개하면 같은
       닉네임의 행이 두 통화에 존재하므로, 통화를 빼면 정상 데이터가 중복으로 오인됩니다.
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
    _assert_unique_keys(payload, ("published_date", "currency", "nickname", "ticker"),
                        "보유종목 발행 요청")

    written = 0
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start:start + CHUNK_SIZE]
        _execute(service_client.table(PUBLIC_HOLDINGS_TABLE).insert(chunk), "보유종목 발행")
        written += len(chunk)
    return written
