# utils/duel_publish_usd.py
"""
⚔️ "결투다!" USD 트랙 — **공개 순위표 발행 배치 오케스트레이션** (2026-08-21, USD 트랙 6차 코딩)

`utils/duel_publish.py`(원화)의 통화 미러입니다. 밤에(정확히는 한국 시각 낮에 — 아래 🕘 참고)
한 번 돌면서 `duel_public_leaderboard_usd` / `duel_public_holdings_usd` 두 발행표를
**통째로 다시 만듭니다.** DUEL_MODULE_WORK_ORDER.md **5-4**(발행 순서)와 **5-11-9**(순위표는
한국장·미국장 완전 별개 표, 절대 병합·비교 안 함)의 구현부입니다.

-------------------------------------------------------------------------------
🔴 이 파일도 `utils/duel_publish.py` 와 **똑같이** 이 저장소에서 가장 위험한 부류입니다
   (ENGINEERING_SPEC §0-3-8)
-------------------------------------------------------------------------------
§0-3-8 은 이 프로젝트의 **최상위 무예외 원칙**입니다. 이 파일이 만드는 행은 곧 **로그인한
모든 사용자가 읽는 값**이라, 기준은 "잘 동작하는가"가 아니라 **"틀려도 안전한가"** 입니다.
원화 파일 머리말이 선언한 다섯 가지를 **하나도 빠짐없이** 그대로 지킵니다. 어떻게 지켜지는지
USD 트랙 기준으로 다시 적습니다(그대로 베낀 문장이 아니라, 이 파일의 실제 코드로 확인한
내용입니다):

  ① **동의하지 않은 사람의 데이터를 읽는 코드 경로가 존재하지 않습니다.**
     실제 자산(`holdings`)을 읽는 호출은 이 파일에 **한 줄**뿐이고
     (`duel_db_usd.fetch_real_principal_holdings()` — 원화와 **같은 함수 객체**입니다),
     그 함수는 사용자 id 목록을 **필수 인자**로만 받습니다. 그 목록은
     `consent_real_principal_bracket=true` 인 **USD 동의 행**에서만 만들어집니다(동의는
     트랙별 완전 독립 — 5-11-10). 동의자가 0명이면 그 함수는 **질의 자체를 보내지
     않습니다**(5-3).
  ② **"동의했는가"를 두 번 확인합니다.** `fetch_publishable_consents_usd()` 의 DB 조회
     필터(`final_confirmed=true`, `revoked_at is null`)로 한 번, 그리고 행마다
     `assert_full_consent()`(원화와 **공유**하는 함수 — 동의 항목 이름이 두 트랙에서 같은
     `duel_db.CONSENT_ITEM_FLAGS` 이므로 새로 만들 이유가 없습니다)로 또 한 번.
  ③ **모르는 값을 0 으로 바꾸지 않습니다.** 수익률을 계산할 수 없는 계좌는 0% 로 세우지
     않고 **발행에서 뺍니다**(§0-1). "0% 수익"과 "아직 성적이 없음"은 다른 말입니다.
  ④ **소수 인원 그룹은 아예 만들지 않습니다.** 500명(5-6, 오너 확정 — 통화 무관 상수)
     미만인 그룹은 발행하지 않고, 예전에 발행됐던 행도 지웁니다. 청소 대상은
     `all_possible_groups_usd()`(3 × `len(BRACKET_KEYS_USD)`)로, **참가자가 전부 사라진
     그룹**까지 포함합니다.
  ⑤ **철회한 사람의 과거 기록을 매번 지웁니다.** "지난번 이후 새로 철회된 것"만 고르지
     않고 **철회된 것 전부**를 매번 봅니다.

  ⚠️ **트랙 격리** — 이 파일은 `duel_public_leaderboard`(원화, `_usd` 없는 표)에 어떤
     질의도 보내지 않습니다. 5-11-9 가 확정한 "한국장/미국장 완전 별개"는 화면 규칙이
     아니라 **데이터 경로 규칙**입니다. `tests/test_duel_publish_usd.py` 가 배치를 통째로
     돌려 KRW 표에 요청이 하나도 안 가는 것을 회귀로 고정합니다.

-------------------------------------------------------------------------------
🔁 "완전 분리, 그러나 순수 규칙은 공유" — 이 파일이 재사용한 것과 새로 쓴 것
-------------------------------------------------------------------------------
`utils/duel_db_usd.py` · `utils/duel_batch_usd.py` 머리말이 세운 것과 **같은 원칙**입니다:
**표 이름 또는 통화별 전제가 함수 본문에 박혀 있는 것만 새로 정의**하고, 통화를 몰라도 되는
순수 판단·조립 로직은 **그대로 import 해서 씁니다.** 두 벌로 만들면 한쪽만 고쳐지는 날
"원화 순위표는 고쳤는데 달러 순위표는 옛 규칙"이 됩니다(§0-3-10).

  · `utils.duel_publish` 에서 **그대로 import 해서 씁니다**(재구현하지 않습니다):
    - `DuelPublishError` — **같은 예외 타입**을 씁니다(`duel_db_usd` 가 `DuelDbError` 를
      공유하는 것과 같은 이유: 호출부가 한 종류만 잡으면 됩니다).
    - 상태·사유 상수 — `PRINCIPAL_OK` · `PRINCIPAL_NO_HOLDINGS` · `PRINCIPAL_FX_MIXED` ·
      `SKIP_NO_NICKNAME` · `SKIP_NO_ACCOUNT` · `SKIP_NO_TWR` · `SKIP_INACTIVE`.
      값 자체가 통화별로 다를 이유가 없습니다("보유가 없음"·"통화가 섞임"은 통화 무관 개념).
    - `_to_date` — 날짜 파싱. 통화 무관.
    - `assert_full_consent()` — 동의 항목 5개는 두 트랙이 **같은 컬럼 이름**을 쓰고
      (`duel_db.CONSENT_ITEM_FLAGS`, 스키마 §13-7 이 원화 표와 컬럼을 똑같이 정의),
      함수 본문에 표 이름도 통화도 없습니다. 그대로 재사용합니다.
    - `consented_user_ids_for_real_principal()` — `duel_db.CONSENT_REAL_PRINCIPAL_FLAG`
      (원화·USD 공유 상수)만 보고 계좌 행에서 `user_id` 를 모읍니다. 통화 무관.
    - `summarize_real_principal_by_user()` 는 **재사용하지 않습니다** — 아래 참고.
    - `build_publish_rows()` · `leaderboard_payload()` · `holdings_payload()` · `_as_float()`
      — 조립·whitelist·숫자 검증. 본문에 표 이름도 통화 리터럴도 없고, 체급 키는 인자로
      받은 값을 그대로 실을 뿐입니다(`duel_rules.BRACKET_NONE_KEY` 는 두 트랙 공유 상수).
    - `split_groups_by_threshold()` — `duel_rules.group_meets_minimum()`(500명, 통화 무관)
      하나만 봅니다.
    - `format_summary_lines()` — **직접 한 줄씩 확인했습니다: "원"·"₩"·"$" 같은 통화
      리터럴이 하나도 없습니다.** (`duel_batch.format_summary_lines()` 에는 실행되는
      f-string 안에 "…원" 이 박혀 있어 §5-15 에서 새로 정의해야 했는데, 발행 배치 쪽에는
      같은 함정이 **없습니다** — 발행 요약은 금액을 한 번도 출력하지 않고 계좌 수·인원
      수·행 수만 출력하기 때문입니다.) 그래서 그대로 재사용합니다. USD 실행분임은 요약
      본문이 아니라 **실행 스크립트가 찍는 머리말**(`run_duel_publish_batch_us.py`)로
      구분합니다.
    - `utils.duel_batch_usd.compute_twr_by_account` — TWR 조립. USD 야간 배치가 이미
      원화 모듈에서 그대로 재사용하고 있는 **같은 객체**입니다(§5-15 재사용 목록).

  · **새로 정의합니다**(표 이름 또는 통화별 전제가 함수 본문에 박혀 있던 것들):
    - `summarize_real_principal_usd()` — 원화 함수는 `scorecard_db.CURRENCY_KRW` 가 아닌
      통화가 하나라도 있으면 `FX_MIXED`, 아니면 **원화** 매입원가합계를 돌려줍니다. USD
      트랙의 체급 기준은 사용자의 **실제 미국주식 매입원가합계**라 조건이 **정확히 반대**
      입니다(비-USD 가 섞이면 FX_MIXED, `usd_cost_basis` 반환). 원화 함수를 그대로 쓰면
      달러 보유자가 전원 FX_MIXED("구간 미적용")로 떨어져 **USD 체급이 통째로 사라집니다.**
    - `summarize_real_principal_by_user_usd()` — 위 함수를 부르기 때문에 함께 갈라집니다
      (원화 함수는 본문에서 `summarize_real_principal()` 을 직접 부릅니다). 묶기 로직 자체는
      같습니다.
    - `resolve_bracket_for_account_usd()` — `duel_rules.assign_bracket_usd()`
      ($750/$2,250/… 8구간)와 `duel_rules.resolve_bracket_for_season_usd()` 를 씁니다.
      🔴 **시즌 고정 함수까지 갈라진 것은 이번 라운드에 코드를 직접 읽고 확인한 사실
         입니다** — 원화 `resolve_bracket_for_season()` 본문이 유효한 체급 목록으로
         `BRACKET_KEYS`(원화 9개)를 하드코딩하고 있어서, USD 체급을 넘기면 시즌 고정이
         조용히 사라지는 게 아니라 **그 자리에서 `DuelRuleError` 로 배치가 죽습니다.**
         시즌 경계 자체(`season_key_for_date()`, 3월 1일·12개월)는 5-11-8 확정대로 여전히
         **공유**합니다 — 갈라진 것은 "유효한 체급 식별자 집합"뿐입니다.
    - `all_possible_groups_usd()` — `duel_rules.BRACKET_KEYS_USD` 를 씁니다.
      (`duel_rules.ACCOUNT_WINDOW_TYPES`(M1/M3/M6)는 통화 무관이라 공유.)
    - `run_publish_batch_usd()` — `duel_db.*` 호출을 전부 `duel_db_usd.*` 로 바꾸고, 위
      네 함수를 씁니다. 그 밖의 순서·게이팅·요약 조립은 원화와 글자 그대로 같습니다.

-------------------------------------------------------------------------------
🧱 파일 나누기 — 왜 `utils/duel_publish.py` 를 고치지 않고 새 파일인가
-------------------------------------------------------------------------------
    utils/duel_rules.py       순수 규칙(체급 경계·시즌·닉네임·순위·최소 인원) — 대부분 공유
    utils/duel_db_usd.py      Supabase 접근(§B 절이 USD 발행표를 만지는 **유일한** 자리)
    utils/duel_publish_usd.py ← **여기.** 순서 · 조립 · 게이팅 판단. Supabase 는 인자로 받은
                                클라이언트로만 만지고, 파일도 네트워크도 직접 열지 않습니다.

원화 파일에 `currency=` 인자를 하나 붙여 두 트랙을 태우는 방식은 **채택하지 않았습니다.**
5-11-1 이 확정한 이유가 그대로 적용됩니다 — 인자 하나를 빠뜨리면 두 트랙이 서로의 발행표를
지우는 통로가 생기지만, 파일 자체를 나누면 그 통로가 **존재하지 않습니다.** 그리고
`utils/duel_publish.py` 는 §0-3-8 검토가 "이 파일만 보면 된다"가 되도록 만들어진 파일이라,
분기를 심는 것은 그 성질 자체를 깨는 일입니다. **이 라운드에서 원화 파일은 한 줄도
건드리지 않았습니다.**

-------------------------------------------------------------------------------
🕘 하루 한 번, 이 순서로 (작업지시서 5-4 — 원화와 완전히 같은 순서)
-------------------------------------------------------------------------------
  0. **철회 청소** — 철회된 USD 계좌의 발행 기록을 모든 날짜에서 삭제 (5-8-1)
  1. 발행 대상 고르기 — `final_confirmed=true` 그리고 `revoked_at is null` (5-4-1)
  2. 체급 정하기 — 동의자만 실제 매입원가합계(**달러분**) 조회 → 시즌 고정 규칙 (5-3)
  3. 수익률 — 이미 쌓인 USD 일별 스냅샷으로 누적 TWR (2-6 의 `compute_twr()` 재사용)
  4. (창유형 × 체급) 그룹별 순위 계산 (5-4-3)
  5. **최소 인원 500명** 게이팅 — 미달 그룹은 발행 안 하고, 과거 행도 삭제 (5-6)
  6. 그날 발행분 **통째로** 삭제 → 새로 삽입 (5-4-4)

⚠️ 실행 시각은 원화와 다릅니다 — USD 체결 배치가 한국 시각 정오에 돌기 때문에, 이 배치는
   그 뒤에 옵니다(`.github/workflows/duel_publish_daily_us.yml` 머리말에 계산 근거).

-------------------------------------------------------------------------------
⚠️ §0-3-2 (작업지시서 2-7) — 계좌 수에 비례해 질의를 늘리지 않습니다
-------------------------------------------------------------------------------
전체를 몇 번 읽고, 메모리에서 전부 계산하고, 몇 번에 나눠 씁니다. 계좌별 루프는 파이썬
안에서만 돌고 그 안에는 질의가 없습니다. `tests/test_duel_publish_usd.py` 가 계좌 수를
바꿔 가며 **질의 횟수 자체를** 고정합니다(원화 테스트와 같은 방식).
"""

from __future__ import annotations

from utils import duel_batch_usd, duel_db, duel_db_usd, duel_rules, scorecard_db

# ── 재사용(같은 객체) — 위 머리말의 "그대로 import 해서 씁니다" 목록 ──────────────────
#    `tests/test_duel_publish_usd.py` §0 이 이 이름들이 실제로 원화 모듈과 **같은 객체**인지
#    (`is` 동일성) 검사합니다. 재정의가 슬쩍 들어오면 거기서 잡힙니다.
from utils.duel_publish import (                                        # noqa: F401
    DuelPublishError,
    PRINCIPAL_OK,
    PRINCIPAL_NO_HOLDINGS,
    PRINCIPAL_FX_MIXED,
    SKIP_NO_NICKNAME,
    SKIP_NO_ACCOUNT,
    SKIP_NO_TWR,
    SKIP_INACTIVE,
    _to_date,
    _as_float,
    assert_full_consent,
    consented_user_ids_for_real_principal,
    build_publish_rows,
    leaderboard_payload,
    holdings_payload,
    split_groups_by_threshold,
    format_summary_lines,
)

#: 이 모듈이 **원화 모듈에서 그대로 가져다 쓰는** 것들의 목록(문서이자 회귀 고정용).
#: `tests/test_duel_publish_usd.py` §0 이 이 이름들을 `is` 동일성으로 검사합니다.
#: (`_to_date`·`_as_float` 는 `__all__` 에 넣지 않는 내부용이라, 여기에만 적어 둡니다 —
#:  `utils/duel_db_usd.py` 가 `duel_db` 의 검증 헬퍼를 import 해 쓰는 것과 같은 관례입니다.)
REUSED_FROM_DUEL_PUBLISH = (
    DuelPublishError, PRINCIPAL_OK, PRINCIPAL_NO_HOLDINGS, PRINCIPAL_FX_MIXED,
    SKIP_NO_NICKNAME, SKIP_NO_ACCOUNT, SKIP_NO_TWR, SKIP_INACTIVE,
    _to_date, _as_float, assert_full_consent, consented_user_ids_for_real_principal,
    build_publish_rows, leaderboard_payload, holdings_payload,
    split_groups_by_threshold, format_summary_lines,
)

__all__ = [
    # 재사용(원화와 같은 객체) — 호출부가 이 모듈 하나만 import 하면 되도록 다시 내보냅니다.
    "REUSED_FROM_DUEL_PUBLISH",
    "DuelPublishError",
    "PRINCIPAL_OK", "PRINCIPAL_NO_HOLDINGS", "PRINCIPAL_FX_MIXED",
    "SKIP_NO_NICKNAME", "SKIP_NO_ACCOUNT", "SKIP_NO_TWR", "SKIP_INACTIVE",
    "assert_full_consent", "consented_user_ids_for_real_principal",
    "build_publish_rows", "leaderboard_payload", "holdings_payload",
    "split_groups_by_threshold", "format_summary_lines",
    # USD 전용(새로 정의)
    "summarize_real_principal_usd",
    "summarize_real_principal_by_user_usd",
    "resolve_bracket_for_account_usd",
    "all_possible_groups_usd",
    "run_publish_batch_usd",
]


# =============================================================================
# 2. 실제 매입원가합계(달러) → 체급 (5-3 · 5-11-9)
# =============================================================================
def summarize_real_principal_usd(user_holdings):
    """
    한 사용자의 실제 보유 목록 → **달러 매입원가합계**(USD 체급 산정용). 5-3 / 5-11-9 참고.

    ── 원화 함수와 **정확히 반대**입니다 (이 함수가 새로 정의된 유일한 이유) ──────────
    `duel_publish.summarize_real_principal()` 은 `scorecard_db.CURRENCY_KRW` 가 **아닌**
    통화가 하나라도 있으면 `FX_MIXED` 를 돌려주고, 원화 매입원가합계만 반환합니다. 이
    함수는 `scorecard_db.CURRENCY_USD` 가 **아닌** 통화가 하나라도 있으면 `FX_MIXED` 이고,
    달러 매입원가합계를 반환합니다.
      · 미국주식만 등록한 사용자 → 원화 함수는 `FX_MIXED`, 이 함수는 `OK`.
      · 국내주식만 등록한 사용자 → 원화 함수는 `OK`, 이 함수는 `FX_MIXED`.
    **원화 함수를 이 트랙에서 그대로 쓰면 달러 보유자가 전원 "구간 미적용"으로 떨어져
    USD 체급이 통째로 사라집니다.** (조용히 틀리는 종류라 테스트로 고정해 뒀습니다 —
    `tests/test_duel_publish_usd.py` 의 KRW·USD 직접 대조 회귀 테스트.)

    ── 계산을 여기서 새로 짜지 않습니다 (§0-3-10) ────────────────────────────────
    "내 성적표"가 화면에 쓰는 그 함수를 그대로 부릅니다 —
    `scorecard_db.build_portfolio(holdings, price_lookup)["USD"]["total_cost"]`.
    매입원가는 `수량 × 평균매입가` 이고, 그 규칙은 `scorecard_db.evaluate_holding()` 안에
    이미 있습니다. `price_lookup` 으로 **항상 None 을 돌려주는 함수**를 넘기는 것도 원화와
    같습니다(매입원가는 현재가와 무관하고, 시세를 넣으면 이 배치가 가격 파일에 의존하게
    됩니다).

    ── 🔴 통화를 합치지 않습니다 (§0-1) ──────────────────────────────────────────
    USD 체급 경계는 전부 **달러 금액**입니다($75,000 / $45,000 / …). 이 앱에는 **환율
    시계열이 어디에도 없습니다**(`scorecard_db.NO_FX_CONVERSION_NOTICE`). 그래서:
      · 달러 종목만 있으면 → 그 합계로 체급을 정합니다.
      · 원화 종목이 하나라도 있으면 → **합치지 않고** `FX_MIXED` 를 돌려줍니다. 호출부는
        그 계좌를 "구간 미적용"(`BRACKET_NONE_KEY`, 통화 무관 공유 상수) 그룹에 넣습니다.

    반환 dict
        status          : 'OK' / 'NO_HOLDINGS' / 'FX_MIXED' (원화와 **같은 상수**를 씁니다)
        usd_cost_basis  : 달러 매입원가합계(float) — status 가 OK 일 때만, 아니면 None
                          ⚠️ 키 이름이 원화의 `krw_cost_basis` 와 다릅니다. 일부러 다릅니다 —
                             같은 이름을 쓰면 두 요약 dict 가 섞여도 아무도 눈치채지 못합니다.
        currencies      : 이 사용자가 실제로 갖고 있는 통화 목록(정렬)
    """
    rows = [row for row in (user_holdings or []) if row]
    if not rows:
        return {"status": PRINCIPAL_NO_HOLDINGS, "usd_cost_basis": None, "currencies": []}

    try:
        portfolio = scorecard_db.build_portfolio(rows, lambda _market, _ticker: None)
    except Exception as exc:  # noqa: BLE001 - scorecard 쪽 예외 종류가 여럿입니다
        # 값을 추측해서 이어 가지 않습니다(§0-1) — 원화 함수와 같은 규약.
        raise DuelPublishError(
            f"실제 보유종목으로 매입원가합계(USD)를 구하지 못했습니다: {exc}"
        ) from exc

    currencies = sorted(portfolio)
    non_usd = [code for code in currencies if code != scorecard_db.CURRENCY_USD]
    if non_usd:
        return {"status": PRINCIPAL_FX_MIXED, "usd_cost_basis": None, "currencies": currencies}

    usd = portfolio.get(scorecard_db.CURRENCY_USD) or {}
    total_cost = usd.get("total_cost")
    if total_cost is None:
        return {"status": PRINCIPAL_NO_HOLDINGS, "usd_cost_basis": None, "currencies": currencies}
    return {"status": PRINCIPAL_OK, "usd_cost_basis": float(total_cost),
            "currencies": currencies}


def summarize_real_principal_by_user_usd(holding_rows):
    """
    `duel_db_usd.fetch_real_principal_holdings()`(원화와 **같은 함수 객체**) 결과를
    `{user_id: 요약}` 으로 묶습니다. 묶기 로직은 원화 함수와 같고, 안에서 부르는 요약 함수만
    `summarize_real_principal_usd()` 로 다릅니다 — 원화 함수가 본문에서
    `summarize_real_principal()` 을 직접 부르기 때문에 이 함수도 함께 갈라졌습니다.
    """
    grouped = {}
    for row in holding_rows or []:
        user_id = (row or {}).get("user_id")
        if user_id:
            grouped.setdefault(str(user_id), []).append(row)
    return {user_id: summarize_real_principal_usd(rows) for user_id, rows in grouped.items()}


def resolve_bracket_for_account_usd(principal_summary, existing_assignment, on_date):
    """
    한 USD 계좌의 **오늘 쓸 체급**을 정합니다. 5-3 / 5-11-9 참고.
    `duel_publish.resolve_bracket_for_account()` 와 같은 두 단계이고, 부르는 규칙 함수만
    USD 것입니다.

      ① 오늘 값으로 체급을 계산해 봅니다(`duel_rules.assign_bracket_usd()` — $750/$2,250/
         $3,750/$7,500/$22,500/$45,000/$75,000 8구간). 매입원가합계를 쓸 수 없으면
         (동의 없음 / 보유 없음 / 통화 혼재) `BRACKET_NONE_KEY`(구간 미적용, 통화 무관 공유).
      ② 🔴 그 값을 **그대로 쓰지 않습니다.** `duel_rules.resolve_bracket_for_season_usd()`
         에 넘겨, 이번 시즌에 이미 배정된 체급이 있으면 **그것이 이깁니다**(5-3 시즌 고정).
         ⚠️ 원화용 `resolve_bracket_for_season()` 을 여기에 쓰면 안 됩니다 — 그 함수는
            유효한 체급 목록으로 `BRACKET_KEYS`(원화)를 하드코딩하고 있어서, USD 체급을
            넘기는 순간 `DuelRuleError` 로 **발행 배치가 그 자리에서 죽습니다.**
            시즌 경계(3월 1일·12개월)는 두 트랙이 여전히 공유합니다(5-11-8).

    인자
        principal_summary : `summarize_real_principal_usd()` 결과 또는 None
                            (None = `consent_real_principal_bracket` 에 동의하지 않은 계좌 —
                             그런 계좌의 `holdings` 는 **읽지도 않았으므로** 요약이 없습니다)
    반환: `duel_rules.resolve_bracket_for_season_usd()` 의 dict + `"fresh_source"` (진단용)
    """
    if principal_summary is None:
        fresh, source = duel_rules.BRACKET_NONE_KEY, "no_consent"
    elif principal_summary.get("status") == PRINCIPAL_OK:
        fresh = duel_rules.assign_bracket_usd(principal_summary.get("usd_cost_basis"))
        source = "computed"
    else:
        fresh, source = duel_rules.BRACKET_NONE_KEY, principal_summary.get("status")

    resolved = duel_rules.resolve_bracket_for_season_usd(existing_assignment, fresh, on_date)
    resolved["fresh_source"] = source
    return resolved


# =============================================================================
# 4. 최소 인원 게이팅 (5-6) — 그룹 목록만 USD 체급으로
# =============================================================================
def all_possible_groups_usd():
    """
    USD 발행표에 **나타날 수 있는 모든 (창유형 × 체급) 조합**.
    = `len(ACCOUNT_WINDOW_TYPES)` × `len(BRACKET_KEYS_USD)` (지금은 3 × 9 = 27, 상수).

    ⚠️ 개수를 이 파일에 숫자로 적지 않습니다 — 체급 표가 늘거나 줄면 자동으로 따라가야
       합니다(§0-3-10). 테스트도 하드코딩 대신 실제 상수 길이로 계산합니다.

    최소 인원 미달 청소(5-6)에 씁니다. "오늘 참가자가 있는 그룹"만 청소하면, 참가자가
    **전부 사라진** 그룹의 과거 행이 영원히 남습니다 — 한 명도 없는데 어제 순위표가 그대로
    보이는 상태가 이 모듈에서 가장 나쁜 실패입니다.

    ⚠️ 이 수는 사용자 수와 무관한 **상수**입니다. 그래서 이 목록을 훑는 청소 단계가
       §0-3-2 를 어기지 않습니다.
    """
    return [(window, bracket)
            for window in duel_rules.ACCOUNT_WINDOW_TYPES
            for bracket in duel_rules.BRACKET_KEYS_USD]


# =============================================================================
# 5. 하루치 USD 발행 배치 본체 — work order 5-4 · 5-11-9
# =============================================================================
def run_publish_batch_usd(service_client, published_date, *, dry_run=False):
    """
    (배치 전용) 하루치 **USD** 공개 순위표를 **통째로 다시 발행**합니다.
    `duel_publish.run_publish_batch()` 의 통화 미러 — 순서·게이팅·요약 키는 완전히 같고,
    Supabase 접근이 전부 `duel_db_usd.*` 이며 체급 계산이 USD 규칙인 점만 다릅니다.

    인자
        service_client : `duel_db_usd.create_service_client()` 결과(= 원화와 **같은 함수**,
                         같은 Supabase 프로젝트·같은 service_role 키 — RLS 우회, 배치 전용).
                         🔴 앱 프로세스에서 부르지 마세요.
        published_date : 발행일. **기본값이 없습니다** — 이 모듈이 "오늘"을 스스로 정하지
                         않습니다. 배치가 자정 근처에 돌거나 하루 늦게 돌면 날짜가 조용히
                         틀어지고, 그건 나중에 복원할 수 없는 오염입니다(§0-1).
                         호출부(`run_duel_publish_batch_us.py`)가 확정해서 넘깁니다.
        dry_run        : True 면 **읽기만** 하고 아무것도 쓰지 않습니다.

    반환: 요약 dict(로그·작업보고용). `format_summary_lines()`(원화와 공유)로 사람이 읽는
          줄로 바꿉니다.

    ── 질의 횟수 (§0-3-2) ───────────────────────────────────────────────────────
    계좌가 3개든 3만개든 **왕복 수가 계좌 수에 비례하지 않습니다.** 고정 왕복은
      동의 조회 1 · 계좌 전체 1 · 시즌 체급 배정 1 · 스냅샷 전체 1 · 포지션 전체 1 ·
      철회 계좌 1 · 당일 발행분 삭제 2 · 미달 그룹 점검 27(상수)
    이고, 나머지(닉네임 조회 · 보유종목 조회 · 배정 기록 · 발행 삽입 · 철회 삭제)는
    **요청 크기를 자르는 청크 수**에 비례합니다.
    `tests/test_duel_publish_usd.py` 가 이 성질을 회귀로 고정합니다.
    """
    if service_client is None:
        raise DuelPublishError(
            "USD 발행 배치용 Supabase 클라이언트가 없습니다"
            " (duel_db_usd.create_service_client() 결과를 넘겨주세요)."
        )
    day_iso = _to_date(published_date, "발행일").isoformat()
    # 🔴 시즌 경계는 원화와 **공유**합니다(5-11-8 — 3월 1일 기준, 12개월).
    season_key = duel_rules.season_key_for_date(day_iso)

    summary = {
        "published_date": day_iso,
        "season_key": season_key,
        "dry_run": bool(dry_run),
        "consent_count": 0,
        "skipped": [],
        "group_counts": {},
        "published_groups": [],
        "blocked_groups": [],
        "leaderboard_rows": 0,
        "holdings_rows": 0,
        "revoked_accounts": 0,
        "revoked_rows_deleted": 0,
        "pruned_group_rows_deleted": 0,
        "new_bracket_assignments": 0,
        "principal_status_counts": {},
    }

    # `duel_nicknames` 는 (user_id, window_type) 키이고 **원화·USD 가 공유하는 표**입니다
    # (5-11-10). 계좌 행(user_id/window_type 포함)이 있어야 닉네임을 찾을 수 있으므로,
    # 철회 청소보다 먼저 전체 USD 계좌 목록을 읽어 둡니다(원화 배치와 같은 순서).
    accounts = duel_db_usd.fetch_all_active_accounts_usd(service_client)
    accounts_by_id = {row["id"]: row for row in accounts if row.get("id")}

    # ── 0. 철회 청소 (5-8-1) — **다른 무엇보다 먼저** ─────────────────────────────
    #    발행 대상을 고르는 것보다 먼저 지웁니다. 순서를 뒤집으면, 오늘 발행이 어떤 이유로
    #    중간에 실패했을 때 "철회한 사람의 과거 기록이 그대로 남은 채 하루가 더 가는" 상태가
    #    됩니다. 지우는 일이 실패해도 그건 예외로 올라가 배치 전체가 시끄럽게 멈춥니다.
    #    ⚠️ 동의·철회는 **트랙별 완전 독립**입니다(5-11-10) — 여기서 보는 것은
    #       `duel_public_consent_usd` 뿐이고, 원화 쪽 철회는 원화 배치가 처리합니다.
    revoked = duel_db_usd.fetch_revoked_consent_accounts_usd(service_client)
    summary["revoked_accounts"] = len(revoked)
    if revoked and not dry_run:
        revoked_accounts = [accounts_by_id[row["account_id"]] for row in revoked
                            if row.get("account_id") and row["account_id"] in accounts_by_id]
        # 닉네임 조회는 원화와 **같은 함수**입니다(닉네임 표는 트랙 공유 — 5-11-10).
        revoked_nicknames = duel_db_usd.fetch_nicknames_for_accounts(
            service_client, revoked_accounts)
        summary["revoked_rows_deleted"] = duel_db_usd.delete_published_rows_for_nicknames_usd(
            service_client, list(revoked_nicknames.values()))

    # ── 1. 발행 대상 고르기 (5-4-1) ──────────────────────────────────────────────
    consents = duel_db_usd.fetch_publishable_consents_usd(service_client)
    summary["consent_count"] = len(consents)

    consent_account_ids = [row["account_id"] for row in consents if row.get("account_id")]

    # ── 2. 체급 (5-3 · 5-11-9) ───────────────────────────────────────────────────
    #    🔴 실제 자산(`holdings`)을 읽는 것은 이 배치에서 **여기 한 번뿐**이고, 대상은
    #       `consent_real_principal_bracket=true` 인 **USD 동의 계좌**의 사용자로만
    #       좁혀집니다. `fetch_real_principal_holdings()` 는 원화와 같은 함수 객체이지만
    #       `user_ids` 가 필수 인자라 "안 주면 전부"라는 경로가 없습니다.
    consented_users = consented_user_ids_for_real_principal(consents, accounts_by_id)
    principal_rows = duel_db_usd.fetch_real_principal_holdings(service_client, consented_users)
    principal_by_user = summarize_real_principal_by_user_usd(principal_rows)
    for user_id in consented_users:
        # holdings 행이 하나도 없는 동의자는 위 묶음에 안 잡히므로 여기서 채웁니다
        # ("등록한 게 없음"과 "조회를 안 했음"을 구분해서 남기기 위해).
        principal_by_user.setdefault(
            user_id, {"status": PRINCIPAL_NO_HOLDINGS, "usd_cost_basis": None, "currencies": []})

    existing_assignments = duel_db_usd.fetch_bracket_assignments_usd(service_client, season_key)
    brackets_by_account, new_assignments = {}, []
    for consent in consents:
        account_id = consent.get("account_id")
        account = accounts_by_id.get(account_id) or {}
        summary_for_user = (principal_by_user.get(str(account.get("user_id")))
                            if consent.get(duel_db.CONSENT_REAL_PRINCIPAL_FLAG) else None)
        resolved = resolve_bracket_for_account_usd(
            summary_for_user, existing_assignments.get(account_id), day_iso)
        brackets_by_account[account_id] = resolved["bracket_key"]
        status_key = resolved["fresh_source"] if resolved["source"] == "assigned" else "kept"
        summary["principal_status_counts"][status_key] = \
            summary["principal_status_counts"].get(status_key, 0) + 1
        if resolved["needs_write"] and account_id:
            new_assignments.append({"account_id": account_id, "season_key": season_key,
                                    "bracket_key": resolved["bracket_key"]})
    if new_assignments and not dry_run:
        summary["new_bracket_assignments"] = duel_db_usd.insert_bracket_assignments_usd(
            service_client, new_assignments)

    # ── 3. 수익률 (2-6 의 compute_twr 재사용 — 다시 구현하지 않습니다) ────────────
    #    이미 낮마다 쌓아 둔 `duel_daily_snapshots_usd` 를 읽습니다. 현금 원장에서 다시
    #    계산하지 않는 이유는 원화와 같습니다 — 스냅샷에는 그날의 `cash_flow_amount`
    #    (외부 현금흐름, USD 는 시드 $7,500 · 월 $500)가 **이미 확정된 값**으로 들어 있고,
    #    TWR 은 정확히 그 값을 필요로 합니다(§0-3-10).
    snapshot_rows = duel_db_usd.fetch_daily_snapshots_for_accounts_usd(
        service_client, consent_account_ids)
    twr_by_account = duel_batch_usd.compute_twr_by_account(snapshot_rows, [])

    positions = duel_db_usd.fetch_positions_for_accounts_usd(service_client, consent_account_ids)
    positions_by_account = duel_db_usd.group_rows_by_account(positions)

    consent_accounts = [accounts_by_id[aid] for aid in consent_account_ids
                        if aid in accounts_by_id]
    nicknames_by_account = duel_db_usd.fetch_nicknames_for_accounts(
        service_client, consent_accounts)

    # ── 4. 조립 + 순위 (5-4-2 · 5-4-3) — 원화와 **같은 함수** ─────────────────────
    built = build_publish_rows(consents, accounts_by_id, nicknames_by_account,
                               brackets_by_account, twr_by_account, positions_by_account)
    summary["skipped"] = built["skipped"]
    summary["group_counts"] = {f"{window}/{bracket}": len(entries)
                               for (window, bracket), entries in built["groups"].items()}

    # ── 5. 최소 인원 게이팅 (5-6) ────────────────────────────────────────────────
    publishable, blocked = split_groups_by_threshold(built["groups"])
    summary["published_groups"] = sorted(f"{w}/{b}" for w, b in publishable)
    summary["blocked_groups"] = sorted(f"{w}/{b}" for w, b in blocked)

    #    발행하지 않는 그룹 = USD 전체 조합 중 오늘 발행되는 것을 뺀 나머지. 인원이 줄어
    #    미달이 된 그룹뿐 아니라 **참가자가 전부 사라진 그룹**까지 포함해야 과거 행이 안
    #    남습니다. ⚡ 발행표가 아직 완전히 비어 있으면(초기 운영 기간) 전부 헛걸음이라,
    #    질의 하나로 먼저 확인하고 건너뜁니다.
    to_prune = [key for key in all_possible_groups_usd() if key not in publishable]
    if not dry_run and to_prune and duel_db_usd.leaderboard_has_any_rows_usd(service_client):
        for window_type, bracket_key in to_prune:
            summary["pruned_group_rows_deleted"] += duel_db_usd.delete_published_group_usd(
                service_client, window_type, bracket_key)

    # ── 6. 그날 발행분 통째로 갈아끼우기 (5-4-4) ─────────────────────────────────
    leaderboard_rows, holding_rows = [], []
    for key, entries in sorted(publishable.items()):
        leaderboard_rows.extend(leaderboard_payload(key, entries))
        holding_rows.extend(holdings_payload(key, entries))
    summary["leaderboard_rows"] = len(leaderboard_rows)
    summary["holdings_rows"] = len(holding_rows)

    if dry_run:
        return summary

    duel_db_usd.delete_published_rows_for_date_usd(service_client, day_iso)
    duel_db_usd.write_public_leaderboard_usd(service_client, day_iso, leaderboard_rows)
    duel_db_usd.write_public_holdings_usd(service_client, day_iso, holding_rows)
    return summary
