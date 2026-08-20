# utils/duel_publish.py
"""
⚔️ "결투다!" 2갈래 "내 밑으로 눈 깔어" — **공개 순위표 발행 배치 오케스트레이션**

DUEL_MODULE_WORK_ORDER.md **5단계**의 구현부입니다. 밤에 한 번 돌면서
`duel_public_leaderboard` / `duel_public_holdings` 두 발행표를 **통째로 다시 만듭니다.**

-------------------------------------------------------------------------------
🔴 이 파일은 이 저장소에서 **가장 위험한 파일**입니다 (ENGINEERING_SPEC §0-3-8)
-------------------------------------------------------------------------------
§0-3-8 은 이 프로젝트의 **최상위 무예외 원칙**입니다. 이 파일이 만드는 행은 곧 **로그인한
모든 사용자가 읽는 값**이고, 작업지시서 5단계는 이 단계의 모든 코드를 *"버그가 나도 새어나갈
수 없는가"* 를 기준으로 리뷰하라고 요구합니다. 그래서 여기서는 "잘 동작하는가"가 아니라
**"틀려도 안전한가"** 를 기준으로 설계했습니다. 실제로 지킨 것 다섯 가지:

  ① **동의하지 않은 사람의 데이터를 읽는 코드 경로가 존재하지 않습니다.**
     실제 자산(`holdings`)을 읽는 호출은 이 파일에 **한 줄**뿐이고
     (`duel_db.fetch_real_principal_holdings()`), 그 함수는 사용자 id 목록을 **필수 인자**로만
     받습니다. 그 목록은 `consent_real_principal_bracket=true` 인 계좌에서만 만들어집니다.
     동의자가 0명이면 그 함수는 **질의 자체를 보내지 않습니다**(5-3).
  ② **"동의했는가"를 두 번 확인합니다.** DB 조회 필터(`final_confirmed=true`,
     `revoked_at is null`)로 한 번, 그리고 행마다 `assert_full_consent()` 로 또 한 번.
     두 번째 확인은 "필터가 잘못 쓰였을 때"를 위한 것입니다 — 필터 오타 하나가 전원 공개로
     이어지는 구조를 만들지 않습니다(§0-3-9 — 조심이 아니라 구조로).
  ③ **모르는 값을 0 으로 바꾸지 않습니다.** 수익률을 계산할 수 없는 계좌(개설 첫날 등)는
     0% 로 세워 두지 않고 **발행에서 뺍니다**(§0-1). "0% 수익"과 "아직 성적이 없음"은 다른
     말이고, 남에게 보이는 표에서 그 둘을 섞으면 사실이 아닌 정보를 발행하는 것입니다.
  ④ **소수 인원 그룹은 아예 만들지 않습니다.** 3명짜리 구간에서 "1위 닉네임"은 사실상
     실명입니다. 500명(5-6, 오너 확정) 미만인 그룹은 발행하지 않고, 예전에 발행됐던 행도
     지웁니다.
  ⑤ **철회한 사람의 과거 기록을 매일 밤 지웁니다.** "지난번 이후 새로 철회된 것"만 골라
     처리하지 않고 **철회된 것 전부**를 매번 봅니다 — 배치가 하루 걸러도 스스로 따라잡게
     하려는 것입니다(안 지워진 채 남는 것이 이 모듈에서 가장 나쁜 실패라서).

-------------------------------------------------------------------------------
🧱 파일 나누기 — 왜 `duel_batch.py` 에 넣지 않았는가
-------------------------------------------------------------------------------
    utils/duel_rules.py    순수 규칙(체급 경계 · 시즌 · 닉네임 · 순위 · 최소 인원 · 3개월 차단)
    utils/duel_db.py       Supabase 접근(§B-7 이 발행표를 만지는 **유일한** 자리)
    utils/duel_publish.py  ← **여기.** 순서 · 조립 · 게이팅 판단. Supabase 는 인자로 받은
                             클라이언트로만 만지고, 파일도 네트워크도 직접 열지 않습니다.

`utils/duel_batch.py`(1갈래 야간 배치)와 **일부러 분리**했습니다. 그 파일 머리말에는
"5단계 공개표 재생성은 이 파일의 범위 밖입니다. 코드도 상수도 없습니다"라고 적혀 있고,
그 경계를 지키는 편이 좋습니다 — 공개 인프라를 **혼자 읽고 리뷰할 수 있는 한 파일**로
묶어 두면 §0-3-8 검토가 "이 파일만 보면 된다"가 됩니다. 1갈래(체결·스냅샷)에 손댈 때
공개 코드를 스치지 않는다는 뜻이기도 합니다.

-------------------------------------------------------------------------------
🕘 하루 한 번, 이 순서로 (작업지시서 5-4)
-------------------------------------------------------------------------------
  0. **철회 청소** — 철회된 계좌의 발행 기록을 모든 날짜에서 삭제 (5-8-1)
  1. 발행 대상 고르기 — `final_confirmed=true` 그리고 `revoked_at is null` (5-4-1)
  2. 체급 정하기 — 동의자만 실제 매입원가합계 조회 → 시즌 고정 규칙 적용 (5-3)
  3. 수익률 — 이미 쌓인 일별 스냅샷으로 누적 TWR (2-6 의 `compute_twr()` 재사용)
  4. (창유형 × 체급) 그룹별 순위 계산 (5-4-3)
  5. **최소 인원 500명** 게이팅 — 미달 그룹은 발행 안 하고, 과거 행도 삭제 (5-6)
  6. 그날 발행분 **통째로** 삭제 → 새로 삽입 (5-4-4)

-------------------------------------------------------------------------------
⚠️ §0-3-2 (작업지시서 2-7) — 계좌 수에 비례해 질의를 늘리지 않습니다
-------------------------------------------------------------------------------
전체를 몇 번 읽고, 메모리에서 전부 계산하고, 몇 번에 나눠 씁니다. 계좌별 루프는 파이썬
안에서만 돌고 그 안에는 질의가 없습니다. `tests/test_duel_publish.py` 가 계좌 수를 바꿔 가며
**질의 횟수 자체를** 고정합니다.
"""

from __future__ import annotations

from datetime import date, datetime

from utils import duel_batch, duel_db, duel_rules, scorecard_db


class DuelPublishError(RuntimeError):
    """
    발행 배치에서 **사람이 읽을** 오류. `duel_batch.DuelBatchError` 와 같은 자리입니다.

    ⚠️ 이 예외가 나면 그날 발행이 멈춥니다. 그게 맞는 방향입니다 — 발행표는 "반쯤 맞는 것"이
       "아무것도 없는 것"보다 나쁜 유일한 표입니다(§0-3-8).
    """


# =============================================================================
# 0. 상수 — 숫자와 경계는 전부 `duel_rules` 에 있습니다(§0-3-10)
# =============================================================================
#: 실제 매입원가합계 요약의 상태값. 값은 **KRW 하나로 말할 수 있을 때만** 나옵니다.
PRINCIPAL_OK = "OK"
#: 이 사용자의 `holdings` 에 행이 하나도 없음. **0원이 아닙니다** — "아직 아무것도 등록하지
#: 않음"을 "0원어치 보유"로 바꾸면 그 사람은 자기 것이 아닌 최하위 체급에 들어갑니다(§0-1).
PRINCIPAL_NO_HOLDINGS = "NO_HOLDINGS"
#: 원화 종목과 달러 종목을 함께 보유 → **하나의 원화 금액으로 합칠 수 없음.**
#: 이 앱에는 환율 시계열이 없습니다(`scorecard_db.NO_FX_CONVERSION_NOTICE` 가 "두 통화의
#: 금액을 하나로 합산한 총자산 숫자는 어디에도 표시하지 않는다"고 못 박고 있습니다).
#: 환율을 지어내면 §0-1 정면 위반이라, 합치지 않고 "구간 미적용"으로 보냅니다.
PRINCIPAL_FX_MIXED = "FX_MIXED"

#: 발행에서 빠진 계좌의 사유 코드(요약·로그용). 조용히 빠지는 계좌가 없게 하려고
#: **모든 제외에 이유를 붙입니다**(§0-1 — 주문이 조용히 사라지는 경로를 만들지 않기와 같은 규율).
SKIP_NO_NICKNAME = "no_nickname"
SKIP_NO_ACCOUNT = "no_account"
SKIP_NO_TWR = "no_twr"
SKIP_INACTIVE = "inactive_account"


def _to_date(value, label="날짜"):
    """
    date / datetime / 'YYYY-MM-DD' → date. 없으면 만들지 않고 예외입니다(§0-1).

    `utils/duel_batch.py::_to_date()` 와 같은 함수입니다. 남의 모듈의 비공개 함수
    (`duel_db._iso_date()`)를 건너 부르지 않으려고 여기에도 둡니다 — 비공개 함수를 가로질러
    쓰기 시작하면 그 함수를 고치는 사람이 어디까지 영향이 가는지 알 수 없게 됩니다.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise DuelPublishError(f"{label}가 비어 있습니다(임의의 날짜를 만들지 않습니다).")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise DuelPublishError(f"{label} 형식을 알 수 없습니다: {value!r}") from None


# =============================================================================
# 1. 동의 확인 — DB CHECK 와 **같은 규칙을 앱에서 한 번 더** (5-2-2 / 5-4-1)
# =============================================================================
def assert_full_consent(consent_row):
    """
    이 동의 행이 **정말로 발행 대상인가**를 행 단위로 다시 확인합니다.

    ── 이게 왜 죽은 코드가 아닌가 (중요) ─────────────────────────────────────────
    DB 의 `duel_consent_final_requires_all` CHECK 는 `final_confirmed=true` 인 행에
    항목별 동의 5개가 전부 true 임을 이미 보장합니다. 그러니 이 확인은 "이론적으로 절대
    실패하지 않는" 확인입니다. 그래도 둡니다:
      · 이 함수가 지키는 것은 **DB 의 상태**가 아니라 **우리 조회 필터**입니다. 위층에서
        `.eq("final_confirmed", True)` 를 실수로 빼거나 오타를 내면(`final_confimed`),
        PostgREST 는 조용히 **전체 행**을 돌려줍니다. 그 순간 동의하지 않은 사람이 발행
        대상이 되고, 그게 정확히 §0-3-8 사고입니다. 이 함수는 그 경우를 잡습니다.
      · 5-2-2 의 "전부 아니면 전무"를 **읽을 수 있는 한 곳**에 적어 두는 자리이기도 합니다.

    ── 그래서 "필드별 게이팅"을 하지 않습니다 ────────────────────────────────────
    작업지시서 초안에는 "동의한 항목만 채우고 나머지는 null" 이라고 적혀 있지만(5-4-2),
    5-2-2 가 나중에 **"5개는 전부 아니면 전무"** 로 확정되면서 실제로 도달 가능한 조합이
    바뀌었습니다. `consent_holdings=true` 인데 `consent_quantity=false` 인 상태로는
    `final_confirmed` 가 설 수 없으므로(CHECK), **발행되는 보유종목 행은 항상 4개 필드가
    모두 채워집니다.** 도달할 수 없는 조합을 위해 "이 필드는 null 로" 분기를 만들면,
    그 분기는 영원히 테스트되지 않는 코드가 되고 나중에 누가 그걸 보고 "아, 부분 공개가
    되는구나"라고 오해합니다. 그래서 **분기 대신 거절**합니다 — 조합이 이상하면 그 계좌를
    발행하지 않고 시끄럽게 실패합니다.
      ⚠️ 진짜로 null 이 되는 값은 따로 있습니다: **계산할 수 없는 수익률**(`twr_pct`).
         그건 동의 문제가 아니라 데이터 문제라 아래 §4 에서 다룹니다.

    실패하면 `DuelPublishError`. 통과하면 None.
    """
    if not isinstance(consent_row, dict):
        raise DuelPublishError(f"동의 행이 dict 가 아닙니다: {consent_row!r}")

    account_id = str(consent_row.get("account_id") or "").strip()
    if not account_id:
        raise DuelPublishError("동의 행에 계좌 ID 가 없습니다(어느 계좌인지 모르면 발행할 수 없습니다).")

    if consent_row.get("revoked_at"):
        raise DuelPublishError(
            f"철회된 계좌가 발행 대상 목록에 섞여 있습니다(account_id={account_id})."
            " 조회 필터(revoked_at is null)를 확인하세요 — 5-8-2 는 앱과 배치 양쪽에서"
            " 확인하라고 요구합니다."
        )
    if not consent_row.get("final_confirmed"):
        raise DuelPublishError(
            f"최종 확인을 하지 않은 계좌가 발행 대상 목록에 있습니다(account_id={account_id})."
            " 조회 필터(final_confirmed=true)를 확인하세요."
        )
    missing = [flag for flag in duel_db.CONSENT_ITEM_FLAGS if not consent_row.get(flag)]
    if missing:
        raise DuelPublishError(
            f"항목별 동의가 빠진 계좌가 발행 대상에 있습니다(account_id={account_id},"
            f" 빠진 항목={missing}). 이 모듈은 '일부만 공개' 조합을 제공하지 않습니다"
            " — 전부 공개하거나 전부 공개하지 않거나 둘 중 하나입니다(5-2-2)."
            " 빠진 항목을 null 로 채워 발행하지 않고 중단합니다."
        )
    return None


def consented_user_ids_for_real_principal(consents, accounts_by_id):
    """
    🔴 실제 `holdings` 를 읽어도 되는 **사용자 id 집합**을 만듭니다. 5-3 / 5-2-4 참고.

    이 함수가 만든 목록이 `duel_db.fetch_real_principal_holdings()` 의 **유일한** 인자이고,
    그게 이 배치에서 실제 자산 표를 건드리는 **유일한** 경로입니다. 즉 "동의 없는 사용자의
    holdings 를 읽는 코드 경로가 하나라도 있으면 §0-3-8 위반"이라는 5-3 의 요구가,
    "이 함수가 맞으면 된다"는 **한 지점**으로 좁혀집니다.

    ⚠️ 조건은 `consent_real_principal_bracket` 하나뿐입니다. 나머지 5개 항목과 **묶지
       않습니다** — 가상 대결 성적은 자랑하고 싶지만 실제 자산 규모는 어떤 형태로도 알리고
       싶지 않은 사용자가 당연히 존재하고, 오너가 이 분리를 명시적으로 확정했습니다(5-2-4).
       그런 사용자도 순위표에는 참여합니다. 빠지는 것은 체급뿐입니다.
    """
    user_ids = set()
    for consent in consents or []:
        if not consent.get(duel_db.CONSENT_REAL_PRINCIPAL_FLAG):
            continue
        account = (accounts_by_id or {}).get(consent.get("account_id"))
        user_id = (account or {}).get("user_id")
        if user_id:
            user_ids.add(str(user_id))
    return sorted(user_ids)


# =============================================================================
# 2. 실제 매입원가합계 → 체급 (5-3)
# =============================================================================
def summarize_real_principal(user_holdings):
    """
    한 사용자의 실제 보유 목록 → **원화 매입원가합계**(체급 산정용). 5-3 참고.

    ── 계산을 여기서 새로 짜지 않습니다 (§0-3-10) ────────────────────────────────
    "내 성적표"가 화면에 쓰는 그 함수를 그대로 부릅니다 —
    `scorecard_db.build_portfolio(holdings, price_lookup)["KRW"]["total_cost"]`.
    매입원가는 `수량 × 평균매입가` 이고, 그 규칙은 `scorecard_db.evaluate_holding()` 안에
    이미 있습니다. 여기서 같은 곱셈을 다시 쓰면 "내 성적표 화면의 매입총합"과 "순위표가
    체급을 정할 때 쓴 매입총합"이 언젠가 갈라집니다.
      · `price_lookup` 으로 **항상 None 을 돌려주는 함수**를 넘깁니다. 매입원가는 현재가와
        무관한 값이라 시세가 필요 없고, 시세를 넣으면 이 배치가 가격 파일에까지 의존하게
        됩니다. (`build_portfolio()` 는 가격을 모르는 종목의 평가액을 None 으로 두도록 이미
        설계돼 있어서, 이 사용법이 예외 경로가 아니라 정상 경로입니다.)

    ── 🔴 원화·달러를 합치지 않습니다 (§0-1) ────────────────────────────────────
    체급 경계는 전부 **원화 금액**입니다(1억원 / 6천만원 / …). 그런데 이 앱에는
    **환율 시계열이 어디에도 없습니다.** `scorecard_db.NO_FX_CONVERSION_NOTICE` 가
    *"두 통화의 금액을 하나로 합산한 '총 자산' 숫자는 어디에도 표시하지 않습니다"* 라고
    못 박고 있습니다. 그래서:
      · 원화 종목만 있으면 → 그 합계로 체급을 정합니다.
      · 달러 종목이 하나라도 있으면 → **합치지 않고** `FX_MIXED` 를 돌려줍니다. 호출부는
        그 계좌를 "구간 미적용" 그룹에 넣습니다. 원화분만으로 체급을 매기면 실제보다 가벼운
        체급이 되어 **그 사용자에게 유리한 방향으로 사실과 다른 결과**가 됩니다.
      ⚠️ 이 처리는 오너 확인이 필요한 지점입니다(작업 보고 (f)·(h) 참고).

    반환 dict
        status          : 'OK' / 'NO_HOLDINGS' / 'FX_MIXED'
        krw_cost_basis  : 원화 매입원가합계(float) — status 가 OK 일 때만, 아니면 None
        currencies      : 이 사용자가 실제로 갖고 있는 통화 목록(정렬)
    """
    rows = [row for row in (user_holdings or []) if row]
    if not rows:
        return {"status": PRINCIPAL_NO_HOLDINGS, "krw_cost_basis": None, "currencies": []}

    try:
        portfolio = scorecard_db.build_portfolio(rows, lambda _market, _ticker: None)
    except Exception as exc:  # noqa: BLE001 - scorecard 쪽 예외 종류가 여럿입니다
        # 값을 추측해서 이어 가지 않습니다. 이 사용자만 체급 없이 참여하게 두는 편이
        # 틀린 체급에 넣는 것보다 낫습니다(§0-1).
        raise DuelPublishError(
            f"실제 보유종목으로 매입원가합계를 구하지 못했습니다: {exc}"
        ) from exc

    currencies = sorted(portfolio)
    non_krw = [code for code in currencies if code != scorecard_db.CURRENCY_KRW]
    if non_krw:
        return {"status": PRINCIPAL_FX_MIXED, "krw_cost_basis": None, "currencies": currencies}

    krw = portfolio.get(scorecard_db.CURRENCY_KRW) or {}
    total_cost = krw.get("total_cost")
    if total_cost is None:
        return {"status": PRINCIPAL_NO_HOLDINGS, "krw_cost_basis": None, "currencies": currencies}
    return {"status": PRINCIPAL_OK, "krw_cost_basis": float(total_cost),
            "currencies": currencies}


def summarize_real_principal_by_user(holding_rows):
    """
    `duel_db.fetch_real_principal_holdings()` 결과(여러 사용자가 섞인 한 목록)를
    `{user_id: 요약}` 으로 묶습니다. 묶기는 `report_db.group_holdings_by_user()` 와 같은 모양.
    """
    grouped = {}
    for row in holding_rows or []:
        user_id = (row or {}).get("user_id")
        if user_id:
            grouped.setdefault(str(user_id), []).append(row)
    return {user_id: summarize_real_principal(rows) for user_id, rows in grouped.items()}


def resolve_bracket_for_account(principal_summary, existing_assignment, on_date):
    """
    한 계좌의 **오늘 쓸 체급**을 정합니다. 5-3 참고.

    두 단계입니다:
      ① 오늘 값으로 체급을 계산해 봅니다(`duel_rules.assign_bracket()`). 매입원가합계를
         쓸 수 없으면(동의 없음 / 보유 없음 / 통화 혼재) `BRACKET_NONE_KEY`(구간 미적용).
      ② 🔴 그 값을 **그대로 쓰지 않습니다.** `duel_rules.resolve_bracket_for_season()` 에
         넘겨, 이번 시즌에 이미 배정된 체급이 있으면 **그것이 이깁니다.** 시즌 중에는
         매입원가가 얼마로 바뀌든 체급이 고정된다는 것이 5-3 의 확정 규칙이고, 이 배치는
         매일 밤 돌기 때문에 그 규칙이 조용히 사라지기 가장 쉬운 자리입니다.

    인자
        principal_summary : `summarize_real_principal()` 결과 또는 None
                            (None = `consent_real_principal_bracket` 에 동의하지 않은 계좌 —
                             그런 계좌의 `holdings` 는 **읽지도 않았으므로** 요약이 없습니다)
    반환: `duel_rules.resolve_bracket_for_season()` 의 dict + `"fresh_source"` (진단용)
    """
    if principal_summary is None:
        fresh, source = duel_rules.BRACKET_NONE_KEY, "no_consent"
    elif principal_summary.get("status") == PRINCIPAL_OK:
        fresh = duel_rules.assign_bracket(principal_summary.get("krw_cost_basis"))
        source = "computed"
    else:
        fresh, source = duel_rules.BRACKET_NONE_KEY, principal_summary.get("status")

    resolved = duel_rules.resolve_bracket_for_season(existing_assignment, fresh, on_date)
    resolved["fresh_source"] = source
    return resolved


# =============================================================================
# 3. 발행 행 조립 — 여기서 **처음으로** 남에게 보일 값이 만들어집니다
# =============================================================================
def build_publish_rows(consents, accounts_by_id, nicknames_by_account, brackets_by_account,
                       twr_by_account, positions_by_account):
    """
    발행 대상 계좌들 → **그룹별 순위표 행 + 보유종목 행**. 5-4 참고.

    입력은 전부 이미 읽어 온 값입니다(이 함수는 Supabase 를 만지지 않습니다).

    반환 dict
        groups        : {(window_type, bracket_key): [순위 매겨진 참가자 dict, ...]}
                        참가자 dict = {"nickname", "twr_pct", "rank", "account_id", "positions"}
                        ⚠️ `account_id` 와 `positions` 는 **여기서만** 들고 다니는 작업용
                           필드입니다. 실제 발행 payload 를 만들 때 잘라 냅니다(아래 두 함수).
        skipped       : [{"account_id", "reason"}, ...] — 발행에서 빠진 계좌와 그 이유(§0-1)

    ── `twr_pct` 가 없는 계좌를 빼는 이유 ────────────────────────────────────────
    개설 첫날처럼 구간 수익률이 아직 하나도 없는 계좌는 `compute_twr()` 가
    `status='INSUFFICIENT'`, `twr_pct=None` 을 돌려줍니다. **0% 가 아닙니다.**
    0% 로 세우면 그 사람은 실제로 존재하지 않는 성적으로 남들 위나 아래에 서게 되고,
    그건 사실이 아닌 정보를 남에게 발행하는 일입니다(§0-1). 그래서 순위에서 빼고,
    **최소 인원(500명)을 셀 때도 세지 않습니다** — "자격은 있지만 성적이 없는" 사람을
    인원수에 넣으면 그만큼 익명성이 얇아지기 때문입니다.
    """
    skipped = []
    by_group = {}

    for consent in consents or []:
        assert_full_consent(consent)                       # 🔴 위 §1 — 두 번째 확인.
        account_id = consent["account_id"]

        account = (accounts_by_id or {}).get(account_id)
        if not account:
            skipped.append({"account_id": account_id, "reason": SKIP_NO_ACCOUNT})
            continue
        if account.get("status") and account.get("status") != "active":
            skipped.append({"account_id": account_id, "reason": SKIP_INACTIVE})
            continue

        nickname = (nicknames_by_account or {}).get(account_id)
        if not nickname:
            # 닉네임이 없으면 발행할 수 없습니다. 배치가 여기서 만들어 주지 않습니다 —
            # `duel_db.ensure_nickname()` 의 docstring 에 그 이유를 적어 뒀습니다.
            skipped.append({"account_id": account_id, "reason": SKIP_NO_NICKNAME})
            continue

        twr = (twr_by_account or {}).get(account_id) or {}
        twr_pct = twr.get("twr_pct")
        if twr_pct is None:
            skipped.append({"account_id": account_id, "reason": SKIP_NO_TWR,
                            "twr_status": twr.get("status")})
            continue

        window_type = account.get("window_type")
        bracket_key = (brackets_by_account or {}).get(account_id) or duel_rules.BRACKET_NONE_KEY
        by_group.setdefault((window_type, bracket_key), []).append({
            "nickname": nickname,
            "twr_pct": twr_pct,
            "account_id": account_id,
            "positions": list((positions_by_account or {}).get(account_id) or []),
        })

    groups = {}
    for key, entries in by_group.items():
        ranked, unrankable = duel_rules.rank_participants(entries)
        # `twr_pct is None` 은 위에서 이미 걸러졌으므로 여기 unrankable 은 항상 비어 있어야
        # 합니다. 비어 있지 않다면 위 필터가 깨졌다는 뜻이라 조용히 넘기지 않습니다.
        if unrankable:
            raise DuelPublishError(
                f"순위를 매길 수 없는 참가자가 그룹 {key} 에 남아 있습니다"
                f" ({len(unrankable)}명). 수익률 없는 계좌를 걸러 내는 단계가 깨졌습니다."
            )
        groups[key] = ranked
    return {"groups": groups, "skipped": skipped}


def leaderboard_payload(group_key, ranked_entries):
    """
    한 그룹의 순위 결과 → `duel_public_leaderboard` 에 넣을 payload 목록.

    🔴 **작업용 필드를 여기서 잘라 냅니다.** `build_publish_rows()` 가 들고 다니던
       `account_id` 와 `positions` 는 발행표에 들어가면 안 됩니다(스키마 §8 — 발행표에
       `user_id` 도 `account_id` 도 넣지 않는 것이 이 구조의 전부입니다). 그래서 넘길 키를
       **whitelist 로 명시**합니다 — "빼야 할 것을 뺀다"가 아니라 "넣을 것만 넣는다"입니다.
       (전자는 나중에 필드가 하나 늘면 조용히 새어 나가고, 후자는 그렇지 않습니다.)
       `duel_db.write_public_leaderboard()` 가 마지막으로 한 번 더 검사합니다.
    """
    window_type, bracket_key = group_key
    payload = []
    for entry in ranked_entries or []:
        payload.append({
            "window_type": window_type,
            "bracket_key": bracket_key,
            "rank": int(entry["rank"]),
            "nickname": entry["nickname"],
            # 여기서 `or 0` 을 쓰지 마세요 — 수익률 0% 는 정상값이고, 그걸 falsy 로 다루면
            # 0% 인 사람의 값이 조용히 사라집니다(§0-1).
            "twr_pct": entry.get("twr_pct"),
        })
    return payload


def holdings_payload(group_key, ranked_entries):
    """
    한 그룹의 순위 결과 → `duel_public_holdings` 에 넣을 payload 목록.

    ── 4개 필드가 항상 함께 채워지는 이유 ────────────────────────────────────────
    5-2-2 확정("5개 항목은 전부 아니면 전무")과 DB CHECK(`duel_consent_final_requires_all`)
    때문에, 여기 오는 계좌는 **보유종목·수량·매입금액에 전부 동의한 계좌**뿐입니다
    (`assert_full_consent()` 가 이미 확인했습니다). 그래서 "수량은 공개하지만 매입금액은
    비공개" 같은 반쪽 행은 **만들 수 없습니다** — 만들 수 있는 조합 자체가 없습니다.
    스키마가 `quantity` · `buy_amount` 를 nullable 로 둔 것은 그 조합을 위해서가 아니라,
    "0 이나 빈 문자열로 채우지 않는다"는 규율을 컬럼 수준에서 표현하기 위해서입니다.

    ── 보유가 없는 계좌 ─────────────────────────────────────────────────────────
    아무것도 사지 않은 계좌(현금만)는 **행을 하나도 만들지 않습니다.** 수량 0 짜리 행을
    만들면 "0주 보유"라는 사실이 아닌 정보가 됩니다. 화면은 순위표에는 있는데 보유종목이
    없는 참가자를 "보유 없음"으로 그리면 됩니다.

    ── 매입금액 ─────────────────────────────────────────────────────────────────
    `buy_amount = quantity × avg_cost` — `duel_positions` 의 가중평균 평단가를 그대로 씁니다
    (`scorecard_db.evaluate_holding()` 의 `cost` 와 같은 규칙). 평가금액이 아니라 **매입금액**
    입니다. 평가금액을 실으면 그날 종가가 필요해지고, 이 배치는 시세에 의존하지 않습니다.
    """
    window_type, _bracket_key = group_key
    payload = []
    for entry in ranked_entries or []:
        nickname = entry["nickname"]
        for position in entry.get("positions") or []:
            ticker = str((position or {}).get("ticker") or "").strip()
            if not ticker:
                raise DuelPublishError(
                    f"종목코드가 없는 포지션이 있습니다(nickname={nickname})."
                    " 빈 값으로 발행하지 않고 중단합니다."
                )
            quantity = _as_float(position.get("quantity"), f"수량({ticker})")
            avg_cost = _as_float(position.get("avg_cost"), f"평단가({ticker})")
            payload.append({
                "window_type": window_type,
                "nickname": nickname,
                "ticker": ticker,
                "stock_name": position.get("stock_name"),
                "quantity": quantity,
                "buy_amount": round(quantity * avg_cost, 6),
            })
    return payload


def _as_float(value, label):
    """숫자로 바꿉니다. 못 바꾸면 **0 으로 넘기지 않고** 예외입니다(§0-1)."""
    if value is None:
        raise DuelPublishError(f"{label}가 없습니다 — 0 으로 채워 발행하지 않습니다.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DuelPublishError(f"{label}가 숫자가 아닙니다: {value!r}") from exc


# =============================================================================
# 4. 최소 인원 게이팅 (5-6) — 순수 판정
# =============================================================================
def split_groups_by_threshold(groups):
    """
    그룹들을 **발행할 것 / 발행하지 않을 것**으로 가릅니다. 5-6 참고.

    임계값은 `duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION`(오너 확정 500명) 하나이고,
    비교도 `duel_rules.group_meets_minimum()` 한 곳에서만 합니다(§0-3-10).

    반환 `(publishable, blocked)` — 둘 다 `{(window_type, bracket_key): [참가자...]}`.

    ⚠️ 여기서 세는 것은 **실제로 순위가 매겨진 사람 수**입니다. 수익률을 계산할 수 없어
       빠진 사람은 이미 `build_publish_rows()` 에서 제외됐으므로 세지 않습니다 — 익명성
       계산은 "표에 실제로 실리는 사람 수"로 해야 의미가 있습니다.
    """
    publishable, blocked = {}, {}
    for key, entries in (groups or {}).items():
        target = publishable if duel_rules.group_meets_minimum(len(entries)) else blocked
        target[key] = entries
    return publishable, blocked


def all_possible_groups():
    """
    발행표에 **나타날 수 있는 모든 (창유형 × 체급) 조합**. 3 × 9 = 27개(고정).

    최소 인원 미달 청소(5-6)에 씁니다. "오늘 참가자가 있는 그룹"만 청소하면, 참가자가
    **전부 사라진** 그룹의 과거 행이 영원히 남습니다 — 그게 가장 위험한 경우입니다
    (한 명도 없는데 어제 순위표가 그대로 보이는 상태).

    ⚠️ 이 수는 사용자 수와 무관한 **상수**입니다. 그래서 이 목록을 훑는 청소 단계가
       §0-3-2 를 어기지 않습니다.
    """
    return [(window, bracket)
            for window in duel_rules.ACCOUNT_WINDOW_TYPES
            for bracket in duel_rules.BRACKET_KEYS]


# =============================================================================
# 5. 하루치 발행 배치 본체 — work order 5-4
# =============================================================================
def run_publish_batch(service_client, published_date, *, dry_run=False):
    """
    (배치 전용) 하루치 공개 순위표를 **통째로 다시 발행**합니다. 작업지시서 5-4 참고.

    인자
        service_client : `duel_db.create_service_client()` 결과(RLS 우회 — 배치 전용).
                         🔴 앱 프로세스에서 부르지 마세요.
        published_date : 발행일. **기본값이 없습니다** — 이 모듈이 "오늘"을 스스로 정하지
                         않습니다. 배치가 자정 근처에 돌거나 하루 늦게 돌면 날짜가 조용히
                         틀어지고, 그건 나중에 복원할 수 없는 오염입니다(§0-1).
                         호출부(워크플로우 실행 스크립트)가 확정해서 넘깁니다 —
                         `utils/duel_batch.py::run_nightly_batch()` 와 같은 규약입니다.
        dry_run        : True 면 **읽기만** 하고 아무것도 쓰지 않습니다. 오너가 "무엇이
                         발행될 뻔했는지"를 먼저 눈으로 볼 수 있게 하는 안전장치입니다
                         (§0-3-6 의 "기본 숨김 → 확인 → 공개" 순서와 같은 정신).

    반환: 요약 dict(로그·작업보고용). `format_summary_lines()` 로 사람이 읽는 줄로 바꿉니다.

    ── 질의 횟수 (§0-3-2) ───────────────────────────────────────────────────────
    계좌가 3개든 3만개든 **왕복 수가 계좌 수에 비례하지 않습니다.** 고정 왕복은
      동의 조회 1 · 계좌 전체 1 · 시즌 체급 배정 1 · 스냅샷 전체 1 · 포지션 전체 1 ·
      철회 계좌 1 · 당일 발행분 삭제 2 · 미달 그룹 점검 27(상수)
    이고, 나머지(닉네임 조회 · 보유종목 조회 · 배정 기록 · 발행 삽입 · 철회 삭제)는
    **요청 크기를 자르는 청크 수**에 비례합니다 — 계좌마다 부르는 것이 아니라 한 요청이
    지나치게 커지지 않게 자르는 것이고, `duel_db.apply_monthly_deposits()` 가 이미 쓰는
    같은 방식입니다. `tests/test_duel_publish.py` 가 이 성질을 회귀로 고정합니다.
    """
    if service_client is None:
        raise DuelPublishError(
            "발행 배치용 Supabase 클라이언트가 없습니다"
            " (duel_db.create_service_client() 결과를 넘겨주세요)."
        )
    day_iso = _to_date(published_date, "발행일").isoformat()
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

    # `duel_nicknames` 가 (user_id, window_type) 키로 바뀌면서(2026-08-20) 닉네임을
    # 계좌 id 만으로는 찾을 수 없게 됐습니다 — 계좌 행(user_id/window_type 포함)이
    # 있어야 하므로, 철회 청소보다 먼저 전체 계좌 목록을 읽어 둡니다.
    accounts = duel_db.fetch_all_active_accounts(service_client)
    accounts_by_id = {row["id"]: row for row in accounts if row.get("id")}

    # ── 0. 철회 청소 (5-8-1) — **다른 무엇보다 먼저** ─────────────────────────────
    #    발행 대상을 고르는 것보다 먼저 지웁니다. 순서를 뒤집으면, 오늘 발행이 어떤 이유로
    #    중간에 실패했을 때 "철회한 사람의 과거 기록이 그대로 남은 채 하루가 더 가는" 상태가
    #    됩니다. 지우는 일이 실패해도 그건 예외로 올라가 배치 전체가 시끄럽게 멈춥니다.
    revoked = duel_db.fetch_revoked_consent_accounts(service_client)
    summary["revoked_accounts"] = len(revoked)
    if revoked and not dry_run:
        revoked_accounts = [accounts_by_id[row["account_id"]] for row in revoked
                             if row.get("account_id") and row["account_id"] in accounts_by_id]
        revoked_nicknames = duel_db.fetch_nicknames_for_accounts(
            service_client, revoked_accounts)
        summary["revoked_rows_deleted"] = duel_db.delete_published_rows_for_nicknames(
            service_client, list(revoked_nicknames.values()))

    # ── 1. 발행 대상 고르기 (5-4-1) ──────────────────────────────────────────────
    consents = duel_db.fetch_publishable_consents(service_client)
    summary["consent_count"] = len(consents)

    consent_account_ids = [row["account_id"] for row in consents if row.get("account_id")]

    # ── 2. 체급 (5-3) ────────────────────────────────────────────────────────────
    #    🔴 실제 자산(`holdings`)을 읽는 것은 이 배치에서 **여기 한 번뿐**이고, 대상은
    #       `consent_real_principal_bracket=true` 인 계좌의 사용자로만 좁혀집니다.
    consented_users = consented_user_ids_for_real_principal(consents, accounts_by_id)
    principal_rows = duel_db.fetch_real_principal_holdings(service_client, consented_users)
    principal_by_user = summarize_real_principal_by_user(principal_rows)
    for user_id in consented_users:
        # holdings 행이 하나도 없는 동의자는 위 묶음에 안 잡히므로 여기서 채웁니다
        # ("등록한 게 없음"과 "조회를 안 했음"을 구분해서 남기기 위해).
        principal_by_user.setdefault(
            user_id, {"status": PRINCIPAL_NO_HOLDINGS, "krw_cost_basis": None, "currencies": []})

    existing_assignments = duel_db.fetch_bracket_assignments(service_client, season_key)
    brackets_by_account, new_assignments = {}, []
    for consent in consents:
        account_id = consent.get("account_id")
        account = accounts_by_id.get(account_id) or {}
        summary_for_user = (principal_by_user.get(str(account.get("user_id")))
                            if consent.get(duel_db.CONSENT_REAL_PRINCIPAL_FLAG) else None)
        resolved = resolve_bracket_for_account(
            summary_for_user, existing_assignments.get(account_id), day_iso)
        brackets_by_account[account_id] = resolved["bracket_key"]
        status_key = resolved["fresh_source"] if resolved["source"] == "assigned" else "kept"
        summary["principal_status_counts"][status_key] = \
            summary["principal_status_counts"].get(status_key, 0) + 1
        if resolved["needs_write"] and account_id:
            new_assignments.append({"account_id": account_id, "season_key": season_key,
                                    "bracket_key": resolved["bracket_key"]})
    if new_assignments and not dry_run:
        summary["new_bracket_assignments"] = duel_db.insert_bracket_assignments(
            service_client, new_assignments)

    # ── 3. 수익률 (2-6 의 compute_twr 재사용 — 다시 구현하지 않습니다) ────────────
    #    이미 밤마다 쌓아 둔 `duel_daily_snapshots` 를 읽습니다. 현금 원장에서 다시 계산하지
    #    않는 이유: 스냅샷에는 그날의 `cash_flow_amount`(외부 현금흐름)가 **이미 확정된 값**
    #    으로 들어 있고, TWR 은 정확히 그 값을 필요로 합니다. 원장에서 되짚으면 1갈래 배치가
    #    한 계산을 두 번째로 구현하는 셈이고, 두 계산이 갈라지면 화면의 수익률과 순위표의
    #    수익률이 다른 값이 됩니다(§0-3-10).
    snapshot_rows = duel_db.fetch_daily_snapshots_for_accounts(
        service_client, consent_account_ids)
    twr_by_account = duel_batch.compute_twr_by_account(snapshot_rows, [])

    positions = duel_db.fetch_positions_for_accounts(service_client, consent_account_ids)
    positions_by_account = duel_db.group_rows_by_account(positions)

    consent_accounts = [accounts_by_id[aid] for aid in consent_account_ids
                        if aid in accounts_by_id]
    nicknames_by_account = duel_db.fetch_nicknames_for_accounts(
        service_client, consent_accounts)

    # ── 4. 조립 + 순위 (5-4-2 · 5-4-3) ───────────────────────────────────────────
    built = build_publish_rows(consents, accounts_by_id, nicknames_by_account,
                               brackets_by_account, twr_by_account, positions_by_account)
    summary["skipped"] = built["skipped"]
    summary["group_counts"] = {f"{window}/{bracket}": len(entries)
                               for (window, bracket), entries in built["groups"].items()}

    # ── 5. 최소 인원 게이팅 (5-6) ────────────────────────────────────────────────
    publishable, blocked = split_groups_by_threshold(built["groups"])
    summary["published_groups"] = sorted(f"{w}/{b}" for w, b in publishable)
    summary["blocked_groups"] = sorted(f"{w}/{b}" for w, b in blocked)

    #    발행하지 않는 그룹 = 전체 27개 중 오늘 발행되는 것을 뺀 나머지. 인원이 줄어 미달이
    #    된 그룹뿐 아니라 **참가자가 전부 사라진 그룹**까지 포함해야 과거 행이 안 남습니다.
    #    ⚡ 발행표가 아직 완전히 비어 있으면(초기 운영 기간) 27번이 전부 헛걸음이라,
    #       질의 하나로 먼저 확인하고 건너뜁니다.
    to_prune = [key for key in all_possible_groups() if key not in publishable]
    if not dry_run and to_prune and duel_db.leaderboard_has_any_rows(service_client):
        for window_type, bracket_key in to_prune:
            summary["pruned_group_rows_deleted"] += duel_db.delete_published_group(
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

    duel_db.delete_published_rows_for_date(service_client, day_iso)
    duel_db.write_public_leaderboard(service_client, day_iso, leaderboard_rows)
    duel_db.write_public_holdings(service_client, day_iso, holding_rows)
    return summary


# =============================================================================
# 6. 요약 출력 — GitHub Actions 로그에서 오너가 눈으로 읽을 줄
# =============================================================================
def format_summary_lines(summary):
    """
    `run_publish_batch()` 결과를 사람이 읽는 줄 목록으로. `duel_batch.format_summary_lines()`
    와 같은 규약입니다 — **빠진 것과 막힌 것을 반드시 드러냅니다**(§0-1: 조용히 넘어가지 않기).
    """
    data = summary or {}
    lines = [
        f"📅 발행일 {data.get('published_date')} (시즌 {data.get('season_key')})"
        + ("  ⚠️ DRY RUN — 아무것도 쓰지 않았습니다" if data.get("dry_run") else ""),
        f"👥 발행 대상 동의 계좌: {data.get('consent_count', 0)}개",
        f"🧱 체급 배정: 새로 {data.get('new_bracket_assignments', 0)}건"
        f" (시즌 중 유지 포함 내역: {data.get('principal_status_counts') or {}})",
    ]

    counts = data.get("group_counts") or {}
    if counts:
        lines.append("📊 그룹별 참가 인원(순위가 실제로 매겨진 사람 수):")
        for name in sorted(counts):
            mark = "✅ 발행" if name in (data.get("published_groups") or []) \
                else f"⛔ 미발행(최소 {duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION}명)"
            lines.append(f"    · {name}: {counts[name]}명 — {mark}")
    else:
        lines.append("📊 순위가 매겨진 그룹이 없습니다(참가자 없음 또는 전원 수익률 계산 불가).")

    skipped = data.get("skipped") or []
    if skipped:
        reasons = {}
        for row in skipped:
            reasons[row.get("reason")] = reasons.get(row.get("reason"), 0) + 1
        lines.append(f"⚠️ 발행에서 빠진 계좌 {len(skipped)}개 — 사유별: {reasons}")

    lines.append(
        f"🧹 철회 계좌 {data.get('revoked_accounts', 0)}개 처리"
        f" (지운 공개 행 {data.get('revoked_rows_deleted', 0)}개),"
        f" 미달 그룹 정리로 지운 행 {data.get('pruned_group_rows_deleted', 0)}개")
    lines.append(
        f"📤 발행: 순위 {data.get('leaderboard_rows', 0)}행 /"
        f" 보유종목 {data.get('holdings_rows', 0)}행")
    return lines
