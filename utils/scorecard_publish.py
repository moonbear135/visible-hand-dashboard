# utils/scorecard_publish.py
"""
📋 "내 성적표" 공개 순위표 — **발행 배치 오케스트레이션**

`sql/scorecard_public_schema.sql` 이 만드는 두 발행표
(`scorecard_public_leaderboard` / `scorecard_public_holdings`)를 밤에 한 번 **통째로 다시
만듭니다.** `utils/duel_publish.py`(결투 가상계좌 공개 계층, 이번 배포로 **은퇴**)의 구조를
그대로 옮기되, 공개 대상이 "가상 대결 성적"에서 **"내 성적표"(실제 보유 자산)** 로 바뀌면서
축이 둘 달라졌습니다.

-------------------------------------------------------------------------------
🔁 결투 발행 배치와 **무엇이 같고 무엇이 다른가** (2026-08-23 오너 확정)
-------------------------------------------------------------------------------
같은 것(그대로 재사용 — 새로 만들지 않습니다, §0-3-10):
  · 체급 경계·시즌 고정·닉네임·순위·최소 인원·3개월 재동의 차단 규칙 전부
    (`utils/duel_rules.py` 의 순수 함수들을 **글자 그대로** 부릅니다).
  · 발행 payload 에 식별자가 섞였는지 보는 마지막 방어선
    (`utils/duel_db.py::FORBIDDEN_PUBLISH_FIELDS` / `_assert_no_identity_fields()`).
  · "동의를 두 번 확인한다 · 모르는 값을 0 으로 바꾸지 않는다 · 소수 인원 그룹은 만들지
    않는다 · 철회한 사람의 과거 기록을 매일 밤 지운다"는 네 가지 규율.

다른 것(이 파일이 새로 쓴 부분):
  ① **계좌 개념이 없습니다.** 사용자당 포트폴리오가 하나뿐이라 모든 것이 `user_id` 단위
     입니다(결투는 `account_id` 단위였습니다).
  ② **창유형(M1/M3/M6) 축이 없습니다.** 대신 원화 성적표와 달러 성적표가 완전히 별개이므로
     `currency` 축을 씁니다. 그룹은 `(currency, bracket_key)` 쌍입니다.
     🔴 두 통화는 **어디서도 합산하지 않습니다**(§0-1 / `scorecard_db.NO_FX_CONVERSION_NOTICE`).
        KRW 체급 키 집합(`BRACKET_KEYS`)과 USD 체급 키 집합(`BRACKET_KEYS_USD`)도 서로
        다른 튜플이라, 한쪽 키가 다른 쪽 그룹에 섞이면 시즌 고정 함수가 그 자리에서 멈춥니다.
  ③ **결투의 독립 동의(`consent_real_principal_bracket`)가 없습니다.** 결투에서 그 동의가
     분리돼 있던 이유는 "다른 모듈(내 성적표)의 실제 자산을 끌어다 쓴다"는 것이었는데, 여기서
     **공개되는 데이터 자체가 이미 그 실제 자산**입니다. 항목별 동의(보유종목·수량·매입금액
     포함)에 최종 확인을 한 순간 매입원가합계는 이미 공개된 값들의 단순 합으로 누구나
     재구성할 수 있으므로, 체급 산정을 위한 **두 번째 동의 게이트를 만들지 않습니다.**
     → 실제 보유종목을 읽는 대상은 **발행 대상 사용자와 정확히 같은 집합**입니다
       (`final_confirmed=true` 그리고 `revoked_at is null`).
     ⚠️ 2026-08-23 — 항목별 동의는 5개에서 **6개**가 됐습니다
        (`scorecard_publish_db.CONSENT_ITEM_FLAGS`). 늘어난 항목은 체급과 무관한
        `consent_holding_details`("종목별 상세지표": 평균매입가·현재가·평가손익·수익률·비중)
        이고, 앞의 5개와 **같은 '전부 아니면 전무' 묶음**에 들어갑니다 — 결투처럼 따로 켜고
        끄는 독립 동의가 아닙니다. 위 문단이 말하는 "두 번째 동의 게이트를 만들지 않는다"는
        여전히 **체급 산정에 대한** 이야기입니다.
  ④ **수익률의 정의가 다릅니다.** 결투는 일별 스냅샷으로 누적 TWR 을 계산했지만, "내 성적표"
     에는 그런 시계열이 없습니다. 대신 화면이 이미 쓰는 규칙
     (`scorecard_db.evaluate_holding()` 의 `profit_pct`)을 포트폴리오 단위로 올린
     **매입원가 대비 수익률**을 씁니다 — 아래 `resolve_portfolio_return_pct()` 참고.
  ⑤ 결투가 필요로 했던 `FX_MIXED`(원화·달러 혼재라 하나로 합칠 수 없음) 판정이 **없습니다.**
     `scorecard_db.build_portfolio()` 가 애초에 통화별 dict 를 돌려주므로, 두 통화가 한
     숫자로 만날 자리 자체가 없습니다. 통화마다 따로 계산하고 따로 발행합니다.
  ⑥ (2026-09-05, #201) **발행 전 신선도(무변동) 검사**가 결투와 같아졌습니다. 결투 체결
     배치가 "오늘 종가를 믿어도 되는가"를 전일 대비 무변동으로 판정하듯, 이 배치도 발행
     직전에 같은 판정(`duel_batch.judge_crawl_freshness()` → `duel_rules.check_crawl_freshness()`)
     을 빌려 씁니다. 결투가 커밋한 기준값 파일은 **읽기만** 하고, 판정에 따라 완전 중단
     (`failed`) / 오늘 발행 건너뜀(`failed_or_holiday`·`needs_review`) / 평소대로(`ok`·기준선
     없음)로 갈립니다 — 자세한 근거와 기준선 선택 규칙은 §4-b 머리말.

-------------------------------------------------------------------------------
🔴 이 파일이 만드는 행은 **로그인한 모든 사용자가 읽습니다** (§0-3-8)
-------------------------------------------------------------------------------
그래서 기준은 "잘 동작하는가"가 아니라 **"틀려도 안전한가"** 입니다. 실제로 지킨 것:
  ① 동의하지 않은 사람의 `holdings` 를 읽는 코드 경로가 존재하지 않습니다. 실제 자산을 읽는
     호출은 이 파일에 **한 줄**뿐이고(`scorecard_publish_db.fetch_holdings_for_users()`),
     그 함수는 사용자 id 목록을 **필수 인자**로만 받으며 빈 목록이면 질의를 보내지 않습니다.
  ② "동의했는가"를 두 번 확인합니다 — DB 조회 필터로 한 번, 행마다 `assert_full_consent()`
     로 또 한 번. 필터 오타 하나가 전원 공개로 이어지는 구조를 만들지 않습니다.
  ③ 모르는 값을 0 으로 바꾸지 않습니다. 수익률을 계산할 수 없는 사용자는 0% 로 세우지 않고
     **발행에서 뺍니다**(§0-1). "0% 수익"과 "성적을 계산할 수 없음"은 다른 말입니다.
  ④ 최소 인원(`duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION`, 2026-09-03 부터 1명) 미달 그룹은 아예 만들지 않고,
     예전에 발행됐던 행도 지웁니다.
  ⑤ 철회한 사람의 과거 기록을 매일 밤 **전부** 다시 봅니다(배치가 하루 걸러도 따라잡게).

-------------------------------------------------------------------------------
🧱 파일 나누기
-------------------------------------------------------------------------------
    utils/duel_rules.py           순수 규칙(체급·시즌·닉네임·순위·최소 인원·재동의 차단)
                                  — 이 모듈은 **읽기만** 하고 규칙을 새로 쓰지 않습니다.
    utils/duel_batch.py           신선도 점검표 만들기·기준값 파일 읽기·무변동 판정(#201)
    utils/duel_batch_usd.py       — 판정 함수와 기준값 파일 경로를 **빌려 쓰기만** 합니다.
                                  기준값 파일을 쓰는 코드는 이 모듈에 없습니다(결투 배치 전용).
    utils/scorecard_db.py         "내 성적표" 평가 규칙(매입원가·평가금액·통화 분리)
                                  — 이 모듈은 **읽기만** 하고 한 줄도 고치지 않습니다.
    utils/scorecard_publish_db.py Supabase 접근(이 발행표를 만지는 **유일한** 자리)
    utils/scorecard_publish.py    ← **여기.** 순서 · 조립 · 게이팅 판단. Supabase 는 인자로
                                  받은 클라이언트로만 만지고, 네트워크를 직접 열지 않습니다.

⚠️ §0-3-2 — 사용자 수에 비례해 질의를 늘리지 않습니다. 전체를 몇 번 읽고, 메모리에서 전부
   계산하고, 몇 번에 나눠 씁니다. 사용자별 루프는 파이썬 안에서만 돌고 그 안에 질의가
   없습니다. `tests/test_scorecard_publish.py` 가 그 성질을 회귀로 고정합니다.
"""

from __future__ import annotations

import math
import os
from datetime import date, datetime

from utils import (duel_batch, duel_batch_usd, duel_rules, scorecard_db,
                   scorecard_publish_db, stock_history)
from utils.duel_batch import DuelBatchError
from utils.duel_rules import DuelRuleError

# 🔴 현재가 조회 함수는 **"내 성적표" 화면과 완전히 같은 것**을 씁니다. 화면이 보여준
#    수익률과 순위표에 실리는 수익률이 다른 값이면 그 자체가 사실이 아닌 정보입니다(§0-1).
#    `report_db.build_price_lookup()` 이 그 단일 출처입니다(상위 200/550 유니버스 →
#    없으면 전 종목 가격 파일 → 미국은 ETF 목록까지 합침). 함수 하나만 좁게 가져옵니다 —
#    `report_db` 라는 이름을 이 모듈에 묶어 두면 같은 모듈의 `fetch_all_holdings()`
#    (**전체 사용자**의 보유종목을 읽는 함수)가 이 파일에서 손에 닿는 거리에 놓입니다.
from utils.report_db import (build_price_lookup, load_kospi_close_history,
                             load_us_index_closes, resolve_session_dates)


class ScorecardPublishError(DuelRuleError):
    """
    발행 배치에서 **사람이 읽을** 오류.

    `duel_rules.DuelRuleError` 의 하위형입니다 — 이 모듈이 부르는 순수 규칙 함수들이 이미
    그 예외를 내므로, 호출부가 `except DuelRuleError` 한 줄로 규칙 위반과 발행 중단을 함께
    잡을 수 있게 했습니다(둘을 따로 잡아야 하면 언젠가 한쪽을 빠뜨립니다).

    ⚠️ 이 예외가 나면 그날 발행이 멈춥니다. 그게 맞는 방향입니다 — 발행표는 "반쯤 맞는 것"이
       "아무것도 없는 것"보다 나쁜 유일한 표입니다(§0-3-8).
    """


# =============================================================================
# 0. 상수 — 숫자와 경계는 전부 `duel_rules` 에, 통화 코드는 `scorecard_db` 에 있습니다
# =============================================================================
#: 🔴 발행되는 통화 축. `scorecard_db` 의 상수를 그대로 씁니다(문자열을 다시 적지 않습니다 —
#:    DB 의 `check (currency in ('KRW','USD'))` 와 어긋나는 순간 발행이 통째로 거절됩니다).
PUBLISHED_CURRENCIES = (scorecard_db.CURRENCY_KRW, scorecard_db.CURRENCY_USD)

#: 🔴 통화별 체급 규칙표. **KRW 와 USD 는 체급 키 집합 자체가 다릅니다**
#:    (`BRACKET_KEYS` 9개 vs `BRACKET_KEYS_USD` 9개 — 이름이 하나도 겹치지 않습니다).
#:    그래서 "어느 통화의 체급인가"를 함수마다 if 문으로 가르지 않고 이 표 한 곳에서만
#:    가릅니다(§0-3-10). 한쪽 키를 다른 쪽 시즌 고정 함수에 넘기면 `DuelRuleError` 로
#:    **그 자리에서 멈춥니다** — 조용히 잘못된 체급에 들어가는 경로가 없습니다.
CURRENCY_BRACKET_RULES = {
    scorecard_db.CURRENCY_KRW: {
        "keys": duel_rules.BRACKET_KEYS,
        "assign": duel_rules.assign_bracket,
        "resolve_for_season": duel_rules.resolve_bracket_for_season,
        "label": duel_rules.bracket_label,
    },
    scorecard_db.CURRENCY_USD: {
        "keys": duel_rules.BRACKET_KEYS_USD,
        "assign": duel_rules.assign_bracket_usd,
        "resolve_for_season": duel_rules.resolve_bracket_for_season_usd,
        "label": duel_rules.bracket_label_usd,
    },
}

#: 발행에서 빠진 사용자의 사유 코드(요약·로그용). 조용히 빠지는 사람이 없게 하려고
#: **모든 제외에 이유를 붙입니다**(§0-1).
SKIP_NO_NICKNAME = "no_nickname"
SKIP_NO_HOLDINGS = "no_holdings"
SKIP_NO_RETURN = "no_return"

#: 체급을 정할 수 없었던 사유(요약용 — `duel_rules.BRACKET_NONE_KEY` 로 가는 경우).
BRACKET_SOURCE_NO_COST_BASIS = "no_cost_basis"
BRACKET_SOURCE_COMPUTED = "computed"


def _to_date(value, label="날짜"):
    """
    date / datetime / 'YYYY-MM-DD' → date. 없으면 만들지 않고 예외입니다(§0-1).

    `utils/duel_publish.py::_to_date()` 와 같은 함수입니다. 남의 모듈의 비공개 함수를 건너
    부르지 않으려고 여기에도 둡니다 — 비공개 함수를 가로질러 쓰기 시작하면 그 함수를 고치는
    사람이 어디까지 영향이 가는지 알 수 없게 됩니다.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ScorecardPublishError(f"{label}가 비어 있습니다(임의의 날짜를 만들지 않습니다).")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise ScorecardPublishError(f"{label} 형식을 알 수 없습니다: {value!r}") from None


def _as_float(value, label):
    """숫자로 바꿉니다. 못 바꾸면 **0 으로 넘기지 않고** 예외입니다(§0-1)."""
    if value is None:
        raise ScorecardPublishError(f"{label}가 없습니다 — 0 으로 채워 발행하지 않습니다.")
    if isinstance(value, bool):
        raise ScorecardPublishError(f"{label}가 숫자가 아닙니다: {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScorecardPublishError(f"{label}가 숫자가 아닙니다: {value!r}") from exc
    if not math.isfinite(number):
        raise ScorecardPublishError(f"{label}가 유효한 숫자가 아닙니다: {value!r}")
    return number


def _optional_float(value, label):
    """
    숫자로 바꾸되, **없는 값(None)은 없는 채로** 돌려줍니다.

    바로 위 `_as_float()` 와 짝입니다. 차이는 딱 하나 — None 을 받았을 때 예외가 아니라
    None 을 돌려줍니다. "반드시 있어야 하는 값"(수량·매입금액)과 "정상적으로 없을 수 있는
    값"을 서로 다른 함수로 가르기 위해서입니다:
      · 수량이 없는 보유 행은 **데이터 손상**이라 발행을 멈춰야 합니다(`_as_float`).
      · 오늘 가격을 못 구한 종목의 현재가·평가손익·수익률·비중은 **정상적으로 없는 값**
        입니다(`evaluate_holding()` 이 그렇게 두도록 만들어져 있습니다). 그런 값까지
        예외로 다루면, 가격 파일에 빠진 종목 하나가 그날 발행 전체를 멈춥니다.

    🔴 어느 쪽이든 **0 으로 바꾸지 않습니다**(§0-1). None 은 "0 원"이 아니라 "모름"입니다.
       숫자가 아닌 값(문자열 등)이 들어오면 그건 "모름"이 아니라 손상이므로 예외입니다.
    """
    if value is None:
        return None
    return _as_float(value, label)


def _require_currency(currency, label="통화"):
    """`'KRW'` / `'USD'` 만 통과시킵니다. 모르는 통화는 지어내지 않고 예외입니다."""
    code = str(currency or "").strip()
    if code not in CURRENCY_BRACKET_RULES:
        raise ScorecardPublishError(
            f"알 수 없는 {label} 입니다: {currency!r}"
            f" (허용: {', '.join(PUBLISHED_CURRENCIES)})."
        )
    return code


# =============================================================================
# 1. 🔴 새 계산 두 개 — 수익률과 체급 입력
#    (이 파일에서 **유일하게** 새로 쓴 업무 규칙입니다. 나머지는 전부 구조 미러링입니다.)
# =============================================================================
def resolve_portfolio_return_pct(currency_summary):
    """
    `build_portfolio()` 가 돌려주는 통화별 요약 dict 하나 → 포트폴리오 수익률(%).

    `evaluate_holding()` 의 개별 종목 `profit_pct` 와 **같은 규칙**입니다:
    `(평가금액 − 매입원가) / 매입원가 × 100`.

    ── 분모로 `total_cost_priced` 를 쓰는 이유 (`total_cost` 가 아닙니다) ──────────
    `scorecard_db.build_portfolio()` 의 실제 소스가 이렇게 짝지어져 있습니다:

        priced            = [r for r in rows if r["price_available"]]
        total_value       = sum(r["market_value"] for r in priced) if priced else None
        total_cost_priced = sum(r["cost"] for r in priced) if priced else None
        ...
        "total_cost":   sum(r["cost"] for r in rows),                    # 전 종목
        "total_value":  total_value,                                     # 가격 아는 종목만
        "total_profit": (total_value - total_cost_priced) if priced else None

    즉 `total_profit` 은 **가격을 확인한 종목만의** (평가금액 − 매입원가)입니다. 그 분자를
    `total_cost`(가격을 못 구한 종목의 매입원가까지 포함한 전체 합)로 나누면 분자와 분모의
    모집단이 어긋나서, 가격을 못 구한 종목이 하나라도 있는 사람의 수익률이 **실제보다 0% 쪽
    으로 눌린 값**이 됩니다. 그건 사실이 아닌 정보를 남에게 발행하는 일입니다(§0-1).
    그래서 분자·분모를 **같은 모집단**(가격을 확인한 종목)으로 맞춥니다.
      ⚠️ 그 대신 "이 사람의 수익률은 보유 전부를 반영한 값이 아닐 수 있다"는 사실이 남습니다.
         그 사실은 여기서 숨기지 않고, 화면이 `unpriced_count` 로 함께 안내하면 됩니다
         (이 함수의 반환값에는 담지 않습니다 — 수익률 하나만 돌려주는 함수라서).

    ── None 을 돌려주는 경우 (§0-1 — 0 으로 위장하지 않습니다) ────────────────────
      · 요약이 없거나 그 통화에 보유종목이 하나도 없을 때.
      · 가격을 구한 종목이 **하나도 없어** `total_cost_priced` / `total_profit` 이 None 일 때.
      · `total_cost_priced` 가 0 이하일 때(0 으로 나눌 수 없고, 음수 매입원가는 데이터 손상).
    None 은 "수익률이 0%"가 아니라 **"계산할 수 없음"** 입니다. 호출부는 그 사용자를 그
    통화의 순위에서 **빼고**, 뺐다는 사실을 요약에 남깁니다.

    ⚠️ 숫자가 아닌 값이 들어오면 None 이 아니라 **예외**입니다. `build_portfolio()` 는 항상
       float 를 담으므로, 숫자가 아닌 값은 "계산 불가"가 아니라 데이터 손상이고 그건 조용히
       넘어갈 일이 아닙니다(§0-1).
    """
    summary = currency_summary or {}
    if not isinstance(summary, dict):
        raise ScorecardPublishError(f"통화별 요약이 dict 가 아닙니다: {currency_summary!r}")

    cost_priced = summary.get("total_cost_priced")
    total_profit = summary.get("total_profit")
    if cost_priced is None or total_profit is None:
        # 가격을 구한 종목이 하나도 없습니다 — 계산 자체가 불가능합니다.
        return None

    denominator = _as_float(cost_priced, "가격이 확인된 종목의 매입원가 합")
    numerator = _as_float(total_profit, "평가손익")
    if denominator <= 0:
        return None
    return numerator / denominator * 100.0


def resolve_bracket_cost_basis(currency_summary):
    """
    `build_portfolio()` 통화별 요약 dict 하나 → **체급 산정에 넣을 매입원가합계**.

    ── 왜 여기만 `total_cost`(전 종목)를 쓰는가 ──────────────────────────────────
    바로 위 수익률과 **일부러 다른 필드**를 씁니다. 체급은 "이 사람이 얼마를 굴리는가"를
    구간으로 나누는 값이라, **오늘 가격 스냅샷에 그 종목이 들어 있었는지와 무관해야**
    합니다. `total_cost_priced` 를 쓰면 오늘 가격 파일에 빠진 종목이 있는 사람만 그날
    갑자기 가벼운 체급으로 내려갑니다 — 시즌 고정 규칙이 그런 흔들림을 막으려고 있는
    것인데 입력 자체가 흔들리면 의미가 없습니다.
    (은퇴하는 `duel_publish.summarize_real_principal()` 도 같은 이유로
     `build_portfolio(...)["KRW"]["total_cost"]` 를 썼습니다 — 그 판단을 그대로 옮깁니다.)

    ── None 을 돌려주는 경우 ────────────────────────────────────────────────────
    그 통화에 보유종목이 하나도 없을 때. **0원이 아닙니다** — "이 통화로는 아직 아무것도
    등록하지 않음"을 "0원어치 보유"로 바꾸면 그 사람은 자기 것이 아닌 최하위 체급에
    들어갑니다(§0-1). 호출부는 None 을 `BRACKET_NONE_KEY`(구간 미적용)로 옮깁니다.

    반환: 매입원가합계(float, 0 이상) 또는 None.
    """
    summary = currency_summary or {}
    if not isinstance(summary, dict):
        raise ScorecardPublishError(f"통화별 요약이 dict 가 아닙니다: {currency_summary!r}")
    if not (summary.get("rows") or []):
        return None
    total_cost = summary.get("total_cost")
    if total_cost is None:
        return None
    amount = _as_float(total_cost, "매입원가합계")
    if amount < 0:
        raise ScorecardPublishError(
            f"매입원가합계가 음수입니다({amount}) — 데이터 손상이지 체급이 아닙니다."
            " 임의의 체급으로 대체하지 않고 중단합니다(§0-1)."
        )
    return amount


def resolve_bracket_for_user_currency(currency, cost_basis, existing_assignment, on_date):
    """
    한 사용자의 **그 통화 체급**을 정합니다(오늘 쓸 값 하나).

    두 단계입니다:
      ① 오늘 값으로 체급을 계산해 봅니다. 매입원가합계가 없으면(그 통화 보유 없음)
         `BRACKET_NONE_KEY`(구간 미적용).
      ② 🔴 그 값을 **그대로 쓰지 않습니다.** 통화에 맞는 시즌 고정 함수
         (`duel_rules.resolve_bracket_for_season()` / `..._usd()`)에 넘겨, 이번 시즌에 이미
         배정된 체급이 있으면 **그것이 이깁니다.** 이 배치는 매일 밤 돌기 때문에, 시즌 고정
         규칙이 조용히 사라지기 가장 쉬운 자리입니다.

    ⚠️ KRW 체급 키를 USD 시즌 고정 함수에(또는 그 반대로) 넘기면 `DuelRuleError` 로 **그
       자리에서 멈춥니다** — 두 통화가 섞이는 경로가 조용히 성립하지 않습니다.

    반환: 시즌 고정 함수의 dict + `"fresh_source"`(진단용) + `"currency"`.
    """
    code = _require_currency(currency)
    rules = CURRENCY_BRACKET_RULES[code]

    if cost_basis is None:
        fresh, source = duel_rules.BRACKET_NONE_KEY, BRACKET_SOURCE_NO_COST_BASIS
    else:
        fresh = rules["assign"](cost_basis)
        source = BRACKET_SOURCE_COMPUTED

    resolved = rules["resolve_for_season"](existing_assignment, fresh, on_date)
    resolved["fresh_source"] = source
    resolved["currency"] = code
    return resolved


# =============================================================================
# 2. 동의 확인 — DB CHECK 와 **같은 규칙을 앱에서 한 번 더**
# =============================================================================
def assert_full_consent(consent_row):
    """
    이 동의 행이 **정말로 발행 대상인가**를 행 단위로 다시 확인합니다.

    ── 이게 왜 죽은 코드가 아닌가 (중요) ─────────────────────────────────────────
    DB 의 `scorecard_consent_final_requires_all` CHECK 는 `final_confirmed=true` 인 행에
    항목별 동의 6개가 전부 true 임을 이미 보장합니다. 그러니 이 확인은 "이론적으로 절대
    실패하지 않는" 확인입니다. 그래도 둡니다:
      · 이 함수가 지키는 것은 **DB 의 상태**가 아니라 **우리 조회 필터**입니다. 위층에서
        `.eq("final_confirmed", True)` 를 실수로 빼거나 오타를 내면(`final_confimed`),
        PostgREST 는 조용히 **전체 행**을 돌려줍니다. 그 순간 동의하지 않은 사람의 **실제
        보유 자산**이 발행 대상이 되고, 그게 정확히 §0-3-8 사고입니다.
      · "전부 아니면 전무"를 **읽을 수 있는 한 곳**에 적어 두는 자리이기도 합니다.

    ── 그래서 "필드별 게이팅"을 하지 않습니다 ────────────────────────────────────
    `consent_holdings=true` 인데 `consent_quantity=false` 인 상태로는 `final_confirmed` 가
    설 수 없으므로(CHECK), **발행되는 보유종목 행은 항상 필드가 모두 채워집니다.** 도달할 수
    없는 조합을 위해 "이 필드는 null 로" 분기를 만들면 그 분기는 영원히 테스트되지 않는
    코드가 되고, 나중에 누가 그걸 보고 "아, 부분 공개가 되는구나"라고 오해합니다. 그래서
    **분기 대신 거절**합니다 — 조합이 이상하면 발행하지 않고 시끄럽게 실패합니다.
      ⚠️ 진짜로 null 이 되는 값은 따로 있습니다: **계산할 수 없는 수익률**. 그건 동의 문제가
         아니라 데이터 문제라 `build_publish_rows()` 에서 다룹니다(그 사용자를 아예 뺍니다).

    실패하면 `ScorecardPublishError`. 통과하면 None.
    """
    if not isinstance(consent_row, dict):
        raise ScorecardPublishError(f"동의 행이 dict 가 아닙니다: {consent_row!r}")

    user_id = str(consent_row.get("user_id") or "").strip()
    if not user_id:
        raise ScorecardPublishError(
            "동의 행에 사용자 ID 가 없습니다(누구의 성적표인지 모르면 발행할 수 없습니다).")

    if consent_row.get("revoked_at"):
        raise ScorecardPublishError(
            f"철회한 사용자가 발행 대상 목록에 섞여 있습니다(user_id={user_id})."
            " 조회 필터(revoked_at is null)를 확인하세요 — 재동의 차단은 앱과 배치"
            " 양쪽에서 확인합니다."
        )
    if not consent_row.get("final_confirmed"):
        raise ScorecardPublishError(
            f"최종 확인을 하지 않은 사용자가 발행 대상 목록에 있습니다(user_id={user_id})."
            " 조회 필터(final_confirmed=true)를 확인하세요."
        )
    missing = [flag for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS
               if not consent_row.get(flag)]
    if missing:
        raise ScorecardPublishError(
            f"항목별 동의가 빠진 사용자가 발행 대상에 있습니다(user_id={user_id},"
            f" 빠진 항목={missing}). 이 모듈은 '일부만 공개' 조합을 제공하지 않습니다"
            " — 전부 공개하거나 전부 공개하지 않거나 둘 중 하나입니다."
            " 빠진 항목을 null 로 채워 발행하지 않고 중단합니다."
        )
    return None


# =============================================================================
# 3. 발행 행 조립 — 여기서 **처음으로** 남에게 보일 값이 만들어집니다
# =============================================================================
def build_publish_rows(consents, portfolios_by_user, nicknames_by_user,
                       brackets_by_user_currency):
    """
    발행 대상 사용자들 → **그룹별 순위표 행 + 보유종목 행**.

    입력은 전부 이미 읽어 온 값입니다(이 함수는 Supabase 를 만지지 않습니다).

    인자
        consents                  : `fetch_publishable_consents()` 결과(각 행에 `user_id`).
        portfolios_by_user        : `{user_id: build_portfolio() 결과}`
                                    (= `{"KRW": 요약, "USD": 요약}`, 보유가 없는 통화는
                                     **키 자체가 없습니다** — `split_by_currency()` 동작).
        nicknames_by_user         : `{user_id: nickname}`
        brackets_by_user_currency : `{(user_id, currency): bracket_key}`

    반환 dict
        groups   : `{(currency, bracket_key): [순위 매겨진 참가자 dict, ...]}`
                   참가자 dict = {"nickname", "twr_pct", "rank", "user_id", "currency",
                                  "holdings", "consent_holding_details"}
                   ⚠️ `user_id` · `holdings` · `consent_holding_details` 는 **여기서만** 들고
                      다니는 작업용 필드입니다. 실제 발행 payload 를 만들 때 잘라 냅니다
                      (아래 두 함수는 넣을 키를 whitelist 로 명시합니다).
        skipped  : `[{"user_id", "reason", "currency"?}, ...]` — 빠진 사용자와 그 이유(§0-1)

    ── 🔴 `"twr_pct"` 라는 키 이름에 대하여 (헷갈리지 않도록 여기 적어 둡니다) ──────
    순위를 매기는 것은 `duel_rules.rank_participants()` 이고, 그 함수는 참가자 dict 에서
    **`"twr_pct"` 라는 이름의 키를 리터럴로 읽습니다**(그 함수 본문에 박혀 있습니다 —
    정렬·동점 판정·`None` 제외가 전부 그 키로 이뤄집니다). 그래서 이 모듈이 담는 값이
    의미상으로는 **시간가중수익률(TWR)이 아니라 매입원가 대비 수익률**임에도, 그 함수에
    넘기는 dict 에서는 키 이름을 `"twr_pct"` 로 맞춥니다.
      · 규칙 함수 쪽 키 이름을 바꾸면 은퇴 대상이 아닌 결투 가상계좌 코드까지 함께 고쳐야
        하므로(§0-3-10 의 반대 방향 위험), **여기서 이름을 맞추는 쪽**을 택했습니다.
      · 밖으로 나가는 이름은 다릅니다 — 발행 payload 와 DB 컬럼은 `return_pct` 입니다
        (`leaderboard_payload()` 참고). 즉 `"twr_pct"` 는 **이 모듈 안에서만** 사는
        이름이고, 저장되지도 화면에 보이지도 않습니다.

    ── 수익률이 없는 사용자를 빼는 이유 ──────────────────────────────────────────
    가격을 하나도 못 구했거나 매입원가가 0 이하인 포트폴리오는 수익률을 계산할 수 없습니다.
    0% 로 세우면 그 사람은 실제로 존재하지 않는 성적으로 남들 위나 아래에 서게 되고, 그건
    사실이 아닌 정보를 남에게 발행하는 일입니다(§0-1). 그래서 순위에서 빼고, **최소 인원을
    셀 때도 세지 않습니다** — "자격은 있지만 성적이 없는" 사람을 인원수에 넣으면 그만큼
    익명성이 얇아집니다.
    """
    skipped = []
    by_group = {}

    for consent in consents or []:
        assert_full_consent(consent)                       # 🔴 위 §2 — 두 번째 확인.
        user_id = str(consent["user_id"]).strip()

        nickname = (nicknames_by_user or {}).get(user_id)
        if not nickname:
            # 닉네임이 없으면 발행할 수 없습니다. 배치가 여기서 만들어 주지 않습니다 —
            # `scorecard_publish_db.ensure_nickname()` 의 docstring 에 그 이유가 있습니다.
            skipped.append({"user_id": user_id, "reason": SKIP_NO_NICKNAME})
            continue

        portfolio = (portfolios_by_user or {}).get(user_id) or {}
        if not portfolio:
            skipped.append({"user_id": user_id, "reason": SKIP_NO_HOLDINGS})
            continue

        # 🔴 통화는 **고정된 순서의 상수 튜플**로 돕니다. 포트폴리오 dict 를 그대로 순회하면
        #    나중에 `build_portfolio()` 가 새 통화 키를 돌려주기 시작했을 때 이 배치가 그것을
        #    조용히 발행표로 날라 줍니다(DB CHECK 가 거절하겠지만, 거절되는 이유가 로그에서
        #    드러나지 않습니다).
        for currency in PUBLISHED_CURRENCIES:
            summary = portfolio.get(currency)
            if not summary or not (summary.get("rows") or []):
                # 그 통화로는 보유가 없습니다 — 빠진 것이 아니라 **애초에 참가 대상이
                # 아닙니다.** 사유 목록에 넣지 않습니다(원화만 하는 사용자가 매일 밤
                # "달러에서 빠졌다"는 줄을 만들면 로그가 사실을 가립니다).
                continue

            return_pct = resolve_portfolio_return_pct(summary)
            if return_pct is None:
                skipped.append({"user_id": user_id, "reason": SKIP_NO_RETURN,
                                "currency": currency})
                continue

            bracket_key = ((brackets_by_user_currency or {}).get((user_id, currency))
                           or duel_rules.BRACKET_NONE_KEY)
            by_group.setdefault((currency, bracket_key), []).append({
                "nickname": nickname,
                # ⚠️ 이름이 "twr_pct" 인 이유는 위 docstring 참고 — `rank_participants()` 가
                #    이 키를 리터럴로 읽습니다. 담긴 값은 **매입원가 대비 수익률(%)** 입니다.
                "twr_pct": return_pct,
                "user_id": user_id,
                "currency": currency,
                "holdings": list(summary.get("rows") or []),
                # 🔴 6번째 동의 항목(2026-08-23)을 **동의 행에서 그대로** 실어 보냅니다.
                #    `holdings_payload()` 가 종목별 상세지표 5종을 채울지 말지를 이 값
                #    하나로 가릅니다 — 그 함수가 동의 행을 다시 읽거나 "어차피 전부
                #    아니면 전무니까 켜져 있겠지"라고 가정하지 않게 하려는 것입니다
                #    (가정을 코드에 남기면 그 가정이 깨지는 날 조용히 새어 나갑니다).
                "consent_holding_details": bool(
                    consent.get("consent_holding_details")),
            })

    groups = {}
    for key, entries in by_group.items():
        ranked, unrankable = duel_rules.rank_participants(entries)
        # `twr_pct is None` 은 위에서 이미 걸러졌으므로 여기 unrankable 은 항상 비어 있어야
        # 합니다. 비어 있지 않다면 위 필터가 깨졌다는 뜻이라 조용히 넘기지 않습니다.
        if unrankable:
            raise ScorecardPublishError(
                f"순위를 매길 수 없는 참가자가 그룹 {key} 에 남아 있습니다"
                f" ({len(unrankable)}명). 수익률 없는 사용자를 걸러 내는 단계가 깨졌습니다."
            )
        groups[key] = ranked
    return {"groups": groups, "skipped": skipped}


def _holding_detail(holding, allowed, field, label, ticker):
    """
    (`holdings_payload()` 전용) 종목별 상세지표 한 칸.

    하는 일이 **두 가지뿐**입니다 — ① 동의(`consent_holding_details`)가 없으면 None,
    ② 있으면 행에 **이미 계산돼 있는** 값을 숫자로만 확인해서 그대로 돌려줍니다.
    여기서 곱하거나 나누는 일은 하나도 없습니다(§0-3-10 — 같은 산수를 두 번 하지 않기).

    저장 정밀도(`numeric(20,6)`)에 맞춰 소수점 6자리에서 반올림합니다. `buy_amount` 가
    이미 같은 처리를 하고 있고, 컬럼이 잘라 버릴 자리를 미리 맞춰 두면 "발행 요청에 보낸
    값"과 "DB 에 저장된 값"이 어긋나지 않습니다.
    """
    if not allowed:
        return None
    number = _optional_float(holding.get(field), f"{label}({ticker})")
    return None if number is None else round(number, 6)


def leaderboard_payload(group_key, ranked_entries):
    """
    한 그룹의 순위 결과 → `scorecard_public_leaderboard` 에 넣을 payload 목록.

    🔴 **작업용 필드를 여기서 잘라 냅니다.** `build_publish_rows()` 가 들고 다니던 `user_id`
       와 `holdings` 는 발행표에 들어가면 안 됩니다(스키마 §2-4 — 발행표에 `user_id` 를 담지
       않는 것이 이 구조의 전부입니다). 그래서 넘길 키를 **whitelist 로 명시**합니다 —
       "빼야 할 것을 뺀다"가 아니라 "넣을 것만 넣는다"입니다. (전자는 나중에 필드가 하나
       늘면 조용히 새어 나가고, 후자는 그렇지 않습니다.)
       `scorecard_publish_db.write_public_leaderboard()` 가 마지막으로 한 번 더 검사합니다.

    ⚠️ 컬럼 이름은 `return_pct` 입니다. 이 모듈 안에서만 쓰던 `"twr_pct"` 라는 이름은 여기서
       끝나고 밖으로 나가지 않습니다(`build_publish_rows()` docstring 참고).
    """
    currency, bracket_key = group_key
    code = _require_currency(currency)
    payload = []
    for entry in ranked_entries or []:
        payload.append({
            "currency": code,
            "bracket_key": bracket_key,
            "rank": int(entry["rank"]),
            "nickname": entry["nickname"],
            # 여기서 `or 0` 을 쓰지 마세요 — 수익률 0% 는 정상값이고, 그걸 falsy 로 다루면
            # 0% 인 사람의 값이 조용히 사라집니다(§0-1).
            "return_pct": entry.get("twr_pct"),
        })
    return payload


def holdings_payload(group_key, ranked_entries):
    """
    한 그룹의 순위 결과 → `scorecard_public_holdings` 에 넣을 payload 목록.

    ── 필드가 항상 함께 채워지는 이유 ────────────────────────────────────────────
    "항목별 동의는 전부 아니면 전무" 확정과 DB CHECK(`scorecard_consent_final_requires_all`)
    때문에, 여기 오는 사용자는 **보유종목·수량·매입금액에 전부 동의한 사용자**뿐입니다
    (`assert_full_consent()` 가 이미 확인했습니다). 그래서 "수량은 공개하지만 매입금액은
    비공개" 같은 반쪽 행은 **만들 수 없습니다** — 만들 수 있는 조합 자체가 없습니다.
    스키마가 `quantity` · `buy_amount` 를 nullable 로 둔 것은 그 조합을 위해서가 아니라,
    "0 이나 빈 문자열로 채우지 않는다"는 규율을 컬럼 수준에서 표현하기 위해서입니다.

    ── 🔴 종목별 상세지표 5종 (2026-08-23 신설) ─────────────────────────────────
    오너 확정("'내 성적표'에 나오는 정보는 기본적으로 전부 공개")에 따라, 이 payload 는
    **평균매입가 · 현재가 · 평가손익 · 수익률 · 비중**을 함께 싣습니다. 다섯 값 전부
    `scorecard_db.evaluate_holding()` / `build_portfolio()` 가 **이미 계산해 둔 필드를
    그대로 옮긴 것**이고, 여기서 같은 산수를 다시 하지 않습니다(§0-3-10) — 다시 하면
    "'내 성적표' 화면이 보여준 숫자"와 "순위표에 실린 숫자"가 언젠가 갈라지고, 그 순간
    둘 중 하나는 사실이 아닌 정보가 됩니다.

        payload 키      ← 행의 필드            (계산 주체)
        avg_price       ← "avg_purchase_price" (evaluate_holding)
        current_price   ← "current_price"      (evaluate_holding, 가격 없으면 None)
        profit          ← "profit"             (evaluate_holding, 가격 없으면 None)
        profit_pct      ← "profit_pct"         (evaluate_holding, 가격 없으면 None)
        weight_pct      ← "weight_pct"         (build_portfolio, 가격 없으면 None)

    🔴 `weight_pct` 의 정의에 대하여 — **"내 성적표" 화면이 쓰는 그 값 그대로**입니다.
       `build_portfolio()` 가 이미 계산해 둔 값이고, 분모는 **가격을 확인한 종목들의 평가금액
       합**(`total_value`)입니다(`scorecard_db.build_portfolio()` 독스트링). 매입원가 기준
       비중을 여기서 따로 계산할 수도 있었지만 그러지 않았습니다 — 같은 "비중"이라는 이름표를
       달고 사용자 본인의 `/scorecard` 화면과 순위표가 **서로 다른 숫자**를 보여주게 되고,
       그건 §0-1 이 금지하는 "사실과 다른 정보"이자 §0-3-10 이 금지하는 "같은 값의 두 번째
       계산식"입니다. 이 모듈이 수익률에 대해 이미 지키고 있는 규율("화면이 보여준 값과 순위표
       값이 다르면 그 자체가 사실이 아닌 정보")과 같은 판단입니다.
         · 분모가 없는 경우(가격을 하나도 못 구함)에는 `build_portfolio()` 가 이미 None 을
           넣어 둡니다 — 0% 로 위장되는 경로가 없습니다(§0-1).

    ⚠️ 가격을 확인하지 못한 종목은 이 중 넷이 **원래부터 None** 입니다. 그 None 은 "동의
       안 함"이 아니라 "오늘 가격을 못 구함"이지만, 화면에서는 둘 다 "비공개"가 아니라
       각각의 사실대로 보이는 것이 이상적입니다 — 다만 발행표는 두 사유를 구분해 담지
       않습니다(구분해 담으면 "이 사람은 동의는 했는데 가격이 없다"는 정보가 남에게
       드러납니다). **어느 쪽이든 0 으로 채우지 않는다**는 것이 지켜야 할 규율입니다(§0-1).

    ── 🔒 게이팅: 다섯 값은 `consent_holding_details` 없이는 실리지 않습니다 ────────
    동의하지 않았으면 다섯 값 **전부 None** 입니다(0 도, 빈 문자열도, 키 생략도 아닙니다 —
    `quantity`/`buy_amount` 와 똑같은 "비공개 ≠ 0" 규약). 판정 값은 호출부가 참가자 dict 에
    실어 보낸 `consent_holding_details` 이고(`build_publish_rows()`), **키가 아예 없으면
    False 로 봅니다** — 기본값이 "공개"인 경로를 만들지 않습니다(§0-3-8 기본 비공개).
      ⚠️ 지금의 DB CHECK 아래에서는 `final_confirmed` 인 사람은 이 값이 항상 true 라서, 이
         분기는 "이론적으로 절대 타지 않는" 분기입니다. 그래도 둡니다 — `assert_full_consent()`
         를 남겨 둔 것과 **정확히 같은 이유**입니다(위 §2 독스트링). 이 함수가 지키는 것은
         DB 의 상태가 아니라 **호출부가 넘긴 것**이고, 조회 필터 오타 하나가 곧 §0-3-8
         사고인 계층에서는 "여기까지 왔으면 동의했겠지"가 가장 위험한 문장입니다.

    ── 매입금액 ─────────────────────────────────────────────────────────────────
    `buy_amount` 는 `scorecard_db.evaluate_holding()` 이 이미 계산해 둔 `cost`
    (= 수량 × 평균매입가)를 **그대로** 씁니다. 여기서 같은 곱셈을 다시 하지 않습니다 —
    다시 하면 "내 성적표 화면의 매입금액"과 "순위표에 실린 매입금액"이 언젠가 갈라집니다
    (§0-3-10). **평가금액이 아니라 매입금액**입니다(평가금액은 그날 시세라 발행 시각에
    따라 값이 달라집니다).

    ⚠️ `stock_name` 은 사용자가 자유 입력한 값입니다(`holdings.stock_name` 을 그대로 옮김).
       `<img onerror=...>` 같은 값이 들어 있을 수 있으므로 **화면은 렌더링하는 모든 자리에서
       `esc()` 를 적용해야 합니다**(스키마 §2-4 컬럼 주석과 같은 경고 — 여기서 값을 고치지는
       않습니다. 사용자가 적은 것과 다른 값을 저장하면 그게 §0-1 위반입니다).
    """
    currency, _bracket_key = group_key
    code = _require_currency(currency)
    payload = []
    for entry in ranked_entries or []:
        nickname = entry["nickname"]
        # 🔒 이 참가자가 종목별 상세지표까지 공개하기로 했는가(위 독스트링). 키가 없으면
        #    False — 기본값은 언제나 비공개입니다(§0-3-8).
        details_allowed = bool((entry or {}).get("consent_holding_details"))
        for holding in entry.get("holdings") or []:
            ticker = str((holding or {}).get("ticker") or "").strip()
            if not ticker:
                raise ScorecardPublishError(
                    f"종목코드가 없는 보유 행이 있습니다(nickname={nickname})."
                    " 빈 값으로 발행하지 않고 중단합니다."
                )

            # 🔴 키를 whitelist 로 **하나하나** 적습니다(`**holding` 같은 전개 금지) —
            #    행에는 원본 `holdings.id` · `market` · `market_value` 같은, 발행표에
            #    실리면 안 되는 값이 함께 들어 있습니다.
            payload.append({
                "currency": code,
                "nickname": nickname,
                "ticker": ticker,
                "stock_name": holding.get("stock_name"),
                "quantity": _as_float(holding.get("quantity"), f"수량({ticker})"),
                "buy_amount": round(_as_float(holding.get("cost"), f"매입금액({ticker})"), 6),
                # ↓ 2026-08-23 신설 5종. 전부 이미 계산된 값의 이동일 뿐입니다.
                "avg_price": _holding_detail(
                    holding, details_allowed, "avg_purchase_price", "평균매입가", ticker),
                "current_price": _holding_detail(
                    holding, details_allowed, "current_price", "현재가", ticker),
                "profit": _holding_detail(
                    holding, details_allowed, "profit", "평가손익", ticker),
                "profit_pct": _holding_detail(
                    holding, details_allowed, "profit_pct", "수익률", ticker),
                "weight_pct": _holding_detail(
                    holding, details_allowed, "weight_pct", "비중", ticker),
            })
    return payload


# =============================================================================
# 4. 최소 인원 게이팅 — 순수 판정
# =============================================================================
def split_groups_by_threshold(groups):
    """
    그룹들을 **발행할 것 / 발행하지 않을 것**으로 가릅니다.

    임계값은 `duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION` 하나이고, 비교도
    `duel_rules.group_meets_minimum()` 한 곳에서만 합니다(§0-3-10).

    2026-09-03 오너 확정으로 그 값이 500 → 1 이 됐습니다(상수 주석 참고). 그래서 지금은
    **동의자가 한 명이라도 순위가 매겨진 그룹은 전부 발행**되고, `blocked` 에는 실질적으로
    아무것도 담기지 않습니다(`build_publish_rows()` 는 참가자가 0명인 그룹을 만들지 않으므로).
    함수·반환 형태·요약 출력은 그대로 둡니다 — 문턱을 다시 올리면 상수 하나만 바꾸면 됩니다.

    반환 `(publishable, blocked)` — 둘 다 `{(currency, bracket_key): [참가자...]}`.

    ⚠️ 여기서 세는 것은 **실제로 순위가 매겨진 사람 수**입니다. 수익률을 계산할 수 없어 빠진
       사람은 이미 `build_publish_rows()` 에서 제외됐으므로 세지 않습니다 — 익명성 계산은
       "표에 실제로 실리는 사람 수"로 해야 의미가 있습니다.
    """
    publishable, blocked = {}, {}
    for key, entries in (groups or {}).items():
        target = publishable if duel_rules.group_meets_minimum(len(entries)) else blocked
        target[key] = entries
    return publishable, blocked


def all_possible_groups():
    """
    발행표에 **나타날 수 있는 모든 (통화 × 체급) 조합**. 9 + 9 = 18개(고정).

    🔴 KRW 와 USD 의 체급 키 집합은 **서로 다른 튜플**입니다(`BRACKET_KEYS` 는
       `krw_...`+`no_bracket`, `BRACKET_KEYS_USD` 는 `usd_...`+`no_bracket`). 그래서 두
       통화의 곱집합이 아니라 **통화별로 그 통화의 키만** 짝지어야 합니다 — 곱집합을 만들면
       `("USD", "krw_100m_plus")` 같은 존재할 수 없는 그룹을 매일 밤 지우려 들게 됩니다.

    최소 인원 미달 청소에 씁니다. "오늘 참가자가 있는 그룹"만 청소하면, 참가자가 **전부
    사라진** 그룹의 과거 행이 영원히 남습니다 — 그게 가장 위험한 경우입니다(한 명도 없는데
    어제 순위표가 그대로 보이는 상태).

    ⚠️ 이 수는 사용자 수와 무관한 **상수**입니다. 그래서 이 목록을 훑는 청소 단계가 §0-3-2 를
       어기지 않습니다.
    """
    groups = []
    for currency in PUBLISHED_CURRENCIES:
        for bracket in CURRENCY_BRACKET_RULES[currency]["keys"]:
            groups.append((currency, bracket))
    return groups


# =============================================================================
# 4-b. 발행 전 신선도(무변동) 검사 — 결투 배치의 검사를 **그대로 빌려** 씁니다 (2026-09-05, #201)
# =============================================================================
#  왜 생겼는가 — 2026-09-05 오너 요청("이런 일이 앞으로도 없었으면 좋겠다").
#    #195 사고: 코스피 수집기가 새벽 07:04 에 한 번 돌아 "오늘 날짜 라벨 + 어제 내용물"인
#    스냅샷을 남겼고, 정식 16:05 수집은 사전 점검이 "오늘 날짜면 됐다"고 보고 건너뛰었습니다.
#    결투는 `duel_batch.judge_crawl_freshness()`(→ `duel_rules.check_crawl_freshness()`)의
#    전일 대비 무변동 검사로 그날 값을 믿지 않고 체결하지 않았지만, 이 발행 배치는 "스냅샷을
#    **아예** 못 읽음"(위 H-3)만 막고 있었기 때문에 **얼어붙은 어제 가격으로 순위를 매겨
#    발행**했습니다. 두 소비자의 방어 수준이 달랐고, 오너가 "결투의 무변동 검사를 성적표에도"
#    라고 명시적으로 승인했습니다.
#
#  무엇을 재사용하는가(§0-3-10 — 판정 코드를 이 파일에 다시 짜지 않습니다).
#    · 판정: `duel_batch.judge_crawl_freshness()` — 안에서 `duel_rules.check_crawl_freshness()`
#      를 부르고, 상위 50종목 명단이 어제와 조금 다른 경우(순위 교체)를 흡수합니다.
#    · 오늘 점검표: `duel_batch.build_freshness_probe()` + `select_probe_stocks()`.
#    · 기준선(어제 값): `duel_batch.load_probe_state()` 로 결투가 커밋해 둔
#      `data/duel_freshness_probe_previous.json`(KR) / `..._usd.json`(US)을 읽습니다.
#      🔴 **읽기 전용입니다.** 이 파일들을 새로 쓰거나 덮어쓰는 코드는 이 모듈에 없어야 합니다 —
#         일별 갱신은 결투 배치(`duel_daily.yml` / `duel_daily_us.yml`)만의 책임입니다.
#         `tests/test_scorecard_publish.py` 가 `save_probe_state` 를 이 파일이 부르지 않음을
#         고정합니다.
#
#  🔴 기준선을 고르는 규칙 — "결투 기준선 = 어제 값"이 **이 배치의 실행 시각에는 성립하지
#     않습니다.** 실제 cron 으로 확인한 사실(§0-1):
#       · 결투 KR 배치는 코스피 수집 직후(16:40~17:10 KST, 거래일 D)에 돌아 **D 의 값**을
#         기준선으로 남깁니다. 이 발행 배치는 다음 날 오전(#201 당시 07:30 KST, #202 부터
#         11:35 KST)에 도는데, 그때 가격 스냅샷도 여전히 D 의 값입니다(그날 코스피 수집은 16:05).
#         즉 평일 오전에는 결투 기준선과 오늘 스냅샷이 **같은 거래일의 같은 값**이라, 그대로
#         비교하면 매일 "전부 무변동"(`failed_or_holiday`)이 나와
#         **발행이 영원히 건너뛰어집니다.** 2026-09-05 저장소 데이터로 실제 확인했습니다.
#       · 그래서 결투 기준선은 **그 `target_date` 가 오늘 스냅샷의 거래일과 다를 때만**
#         씁니다. 같은 날이면 결투가 이미 오늘 값을 기준선으로 남긴 뒤라 "어제 값"이 아니고,
#         그 경우 **수집기가 매일 남기는 이력 CSV(`data/kospi200_stock_history.csv` /
#         `us_stocks_history.csv`)의 직전 날짜 행**으로 어제 점검표를 만들어 대신 씁니다
#         (`_previous_probe_from_history()`). 이 이력은 스냅샷과 **같은 수집기가 같은 실행에서**
#         남기므로, #195 모양("오늘 라벨 + 어제 내용물")이면 오늘 행과 직전 행이 같은 값이
#         되어 정확히 잡힙니다. 판정 함수는 어느 쪽 기준선이든 같은 것을 씁니다.
#       · 결투 기준선의 날짜가 스냅샷 거래일보다 **뒤**인 경우(결투는 D 를 처리했는데 스냅샷은
#         D-1 에 멈춤 = 수집기가 아예 돌지 않은 날·휴장일)는 값이 그대로라 `failed_or_holiday`
#         로 잡혀 그날 발행을 건너뜁니다 — 낡은 가격에 새 발행일을 붙이지 않습니다.
#     ⚠️ 지수 원천(코스피 `market_history.csv`, 미국 `us_index_history.json`)은 결투와 마찬가지로
#        **다른 파이프라인 산출물**입니다. 지수의 최신 날짜가 스냅샷 거래일보다 낡았으면 그
#        지수는 비교에서 빼고(결투의 H-1 과 같은 이유 — 지수 파이프라인만 실패한 날을 "수집
#        실패"로 오판하지 않기), 지수가 하나도 안 남으면 검사를 생략합니다(판정 규칙이 지수
#        없이는 판정하지 않습니다). 미국 지수는 08:20 KST(`scrape_report_snapshots.yml`)에
#        수집됩니다. #201 당시 이 배치는 07:30 KST 라 **미국 쪽 검사가 항상 이 이유로 생략**됐고,
#        2026-09-06 #202 에서 오너 승인으로 cron 을 11:35 KST(02:35 UTC)로 옮겨 **미국 쪽 검사가
#        활성화**됐습니다 — 시각의 근거(실제 커밋 시각·30분 여유 관례)는 워크플로우 머리말
#        🕘 #202 문단에 있습니다. 미국 결투 기준선(`duel_daily_us.yml`, 12:00 KST 갱신)은 11:35 엔
#        아직 D-1 값이라 결투 기준선을 그대로 쓰고, 지연으로 12:00 을 넘겨 돌면 위 "같은 날" 규칙이
#        이력 CSV 대체 경로로 받습니다 — 어느 쪽이든 판정 함수는 같습니다.
#
#  판정 → 행동 표 (오너 확정 정책, 2026-09-05)
#     판정                  행동                                 근거
#     ─────────────────────────────────────────────────────────────────────────────
#     ok                    평소대로 발행                        —
#     failed                `ScorecardPublishError` — **완전 중단**  명백한 수집 실패. 과거 발행
#                                                                이력을 지우기 **전에** 멈춤(H-3 과 동일)
#     failed_or_holiday     오늘 발행 **건너뜀**(예외 없음)        휴장일엔 값이 그대로인 게 맞음 —
#     needs_review          기존 발행 내역 그대로, 요약에 사유       어제 순위가 하루 더 유지되면 충분
#     no_baseline / 생략    평소대로 발행 + 요약에 안내             우리 쪽 사정이지 실패의 증거가 아님
#
#  ⚠️ 건너뛰는 날에도 **철회 청소(0단계)는 합니다.** 철회한 사람의 공개 기록을 지우는 일은
#     가격과 무관한 의무이고, 이 모듈에서 "하루도 거르면 안 되는 일"입니다. 건너뛰는 것은
#     그 뒤의 발행(1~6단계)뿐입니다. 시장 하나라도 skip 이면 그날 발행 전체를 건너뜁니다 —
#     한 통화만 발행하면 5단계가 다른 통화 그룹을 "발행 대상 아님"으로 보고 **과거 행을
#     지워 버리기** 때문입니다.
# =============================================================================
FRESHNESS_PROCEED = "proceed"          # 평소대로 발행
FRESHNESS_SKIP = "skip"                # 오늘 발행 건너뜀(조용히 — CI 는 성공)
FRESHNESS_ABORT = "abort"              # ScorecardPublishError 로 완전 중단
FRESHNESS_NOT_CHECKED = "not_checked"  # 검사 자체를 못 함(기준선 없음 등) — 발행은 진행

#: 기준선을 어디서 가져왔는가(요약·로그용).
BASELINE_SOURCE_DUEL = "duel_probe"        # 결투가 커밋한 data/duel_freshness_probe_previous*.json
BASELINE_SOURCE_HISTORY = "stock_history"  # 수집기 이력 CSV 의 직전 날짜 행

#: 코스피 점검에 실제로 넣는 지수. `run_duel_daily_batch.ACTIVE_PROBE_INDEX_KEYS` 와 같은 값이어야
#: 합니다(코스닥 지수 원천이 아직 없어 코스피만 — 그 스크립트 머리말 참고). 실행 스크립트를 이
#: 모듈이 import 하지 않으므로 리터럴을 옮기고 테스트로 일치를 고정합니다(`duel_batch_usd` 가
#: `report_db.US_BENCHMARK_KEYS` 를 다루는 방식과 같습니다).
KR_PROBE_INDEX_KEYS = ("KOSPI",)

#: 시장별로 "어느 파일이 오늘 값·기준선·지수인가". 통화 축(`PUBLISHED_CURRENCIES`)과 1:1 입니다.
FRESHNESS_MARKETS = {
    scorecard_db.MARKET_KR: {
        "label": "코스피",
        "index_keys": KR_PROBE_INDEX_KEYS,
        "state_path": duel_batch.default_state_path,
        "history_filename": stock_history.KOSPI_HISTORY_FILENAME,
        "code_field": "code",
    },
    scorecard_db.MARKET_US: {
        "label": "미국주식",
        "index_keys": duel_batch_usd.PROBE_INDEX_KEYS_SPEC_USD,
        "state_path": duel_batch_usd.default_state_path_usd,
        "history_filename": stock_history.US_HISTORY_FILENAME,
        "code_field": "symbol",
    },
}


def decision_for_freshness_status(status):
    """
    신선도 판정 문자열 → 이 배치가 **오늘 무엇을 할지**(위 §4-b 머리말의 표를 코드로).

    `duel_rules.crawl_status_allows_fill()` 이 결투에서 하는 역할과 같습니다 — 판정 문자열을
    호출부마다 비교하지 않고 한 곳에서만 행동으로 바꿉니다(§0-3-10). 모르는 판정은 추측해서
    진행하지 않고 예외입니다(§0-1).
    """
    if status == duel_rules.CRAWL_OK:
        return FRESHNESS_PROCEED
    if status == duel_rules.CRAWL_FAILED:
        return FRESHNESS_ABORT
    if status in (duel_rules.CRAWL_FAILED_OR_HOLIDAY, duel_rules.CRAWL_NEEDS_REVIEW):
        return FRESHNESS_SKIP
    if status in (duel_batch.CRAWL_NO_BASELINE, FRESHNESS_NOT_CHECKED):
        return FRESHNESS_PROCEED
    raise ScorecardPublishError(f"알 수 없는 신선도 판정입니다: {status!r}")


def judge_market_freshness(market, *, session_date, today_probe, previous_probe,
                           baseline_source=None, notes=()):
    """
    시장 하나의 신선도를 판정합니다. **순수 함수** — 파일도 네트워크도 열지 않고, 오늘
    점검표와 기준선을 인자로만 받습니다(`price_lookup` 을 인자로 열어 둔 것과 같은 이유:
    `tests/test_scorecard_publish.py` 가 파일 없이 이 판정을 검증합니다).

    인자
        session_date   : 오늘 가격 스냅샷의 거래일(ISO). 없으면 그 시장은 검사하지 않습니다.
        today_probe    : `duel_batch.build_freshness_probe()` 결과(못 만들었으면 None).
        previous_probe : `duel_batch.load_probe_state()` 결과 또는 이력에서 만든 점검표(없으면 None).
        baseline_source: 요약용 — `BASELINE_SOURCE_DUEL` / `BASELINE_SOURCE_HISTORY`.
        notes          : 입력을 준비하며 남긴 안내 문장들(요약에 그대로 실립니다).

    판정 자체는 `duel_batch.judge_crawl_freshness()`(→ `duel_rules.check_crawl_freshness()`)가
    합니다. 이 함수가 새로 정하는 것은 두 가지뿐입니다:
      ① **기준선의 날짜가 오늘 스냅샷 거래일과 같으면 비교하지 않습니다** — 결투 배치가 이미
         오늘 값을 기준선으로 남긴 뒤라 "어제 값"이 아닙니다(§4-b 머리말). 같은 값끼리 비교해
         "전부 무변동"이라고 하면 사실이 아닌 판정입니다(§0-1).
      ② 판정 함수가 입력 상태 때문에 예외를 내면(값이 없음 등) 발행을 막지 않고 **검사 생략**
         으로 처리해 사유만 남깁니다 — 이 검사가 발행 자체를 막는 원인이 되지 않게(오너 정책).

    반환 dict: market / checked / decision / status / reason / session_date / baseline_date /
               baseline_source / compared_stocks / dropped_stocks / notes
    """
    result = {
        "market": market,
        "checked": False,
        "decision": FRESHNESS_PROCEED,
        "status": FRESHNESS_NOT_CHECKED,
        "reason": "",
        "session_date": session_date,
        "baseline_date": None,
        "baseline_source": baseline_source,
        "compared_stocks": 0,
        "dropped_stocks": 0,
        "notes": list(notes or ()),
    }
    if not session_date:
        result["reason"] = "가격 스냅샷의 거래일을 확인하지 못해 이 시장은 검사를 생략합니다."
        return result
    if not isinstance(today_probe, dict) or not today_probe.get("values"):
        result["reason"] = "오늘 신선도 점검표가 없어 검사를 생략합니다."
        return result
    if not today_probe.get("index_keys"):
        result["reason"] = "오늘 점검표에 비교할 지수가 없어 검사를 생략합니다(지수 없이는 판정하지 않습니다)."
        return result
    if not isinstance(previous_probe, dict) or not previous_probe.get("values"):
        result["reason"] = "신선도 기준선(어제 값)이 없어 이 검사를 생략합니다 — 최초 실행이거나 기준선 파일을 읽지 못한 경우입니다."
        return result

    baseline_date = previous_probe.get("target_date")
    result["baseline_date"] = baseline_date
    if baseline_date == session_date:
        result["reason"] = (
            f"기준선({baseline_source or '?'})의 날짜({baseline_date})가 오늘 스냅샷의 거래일과 같아"
            " 비교 대상이 아닙니다 — 검사를 생략합니다."
        )
        return result

    try:
        judged = duel_batch.judge_crawl_freshness(today_probe, previous_probe)
    except (DuelBatchError, DuelRuleError) as exc:
        # 값이 없거나 형식이 맞지 않아 규칙 함수가 판정을 거부한 경우. 이 검사가 발행을
        # 막는 원인이 되지 않게 "검사 생략"으로 두고 사유만 남깁니다(오너 정책).
        result["reason"] = f"신선도 판정을 할 수 없어 검사를 생략합니다: {exc}"
        return result

    result["status"] = judged["status"]
    result["compared_stocks"] = judged.get("compared_stocks", 0)
    result["dropped_stocks"] = judged.get("dropped_stocks", 0)
    result["reason"] = judged.get("reason") or ""
    if judged["status"] == duel_batch.CRAWL_NO_BASELINE:
        # 기준선에 지수가 없거나 공통 종목이 너무 적음 — 우리 쪽 사정이지 실패의 증거가 아닙니다.
        return result
    result["checked"] = True
    result["decision"] = decision_for_freshness_status(judged["status"])
    return result


def evaluate_publish_freshness(freshness_inputs):
    """
    시장별 입력(`load_freshness_inputs()` 결과 또는 테스트가 손으로 만든 dict) → 그날 발행에 대한
    **하나의 결정**. 순수 함수입니다.

    합치는 규칙: 시장 하나라도 `abort` 면 abort, 아니면 하나라도 `skip` 이면 skip, 아니면 proceed.
    (한 통화만 발행하면 다른 통화 그룹의 과거 행이 지워지므로 — §4-b 머리말 — 발행은 전부 아니면
    전무입니다.)

    반환 dict: decision / markets({시장: judge_market_freshness() 결과}) / reasons(사람이 읽을 문장들)
    """
    markets = {}
    for market, inputs in (freshness_inputs or {}).items():
        markets[market] = judge_market_freshness(market, **dict(inputs or {}))

    decision = FRESHNESS_PROCEED
    if any(item["decision"] == FRESHNESS_ABORT for item in markets.values()):
        decision = FRESHNESS_ABORT
    elif any(item["decision"] == FRESHNESS_SKIP for item in markets.values()):
        decision = FRESHNESS_SKIP

    reasons = []
    for market in sorted(markets):
        item = markets[market]
        if item["decision"] != FRESHNESS_PROCEED or not item["checked"]:
            reasons.append(f"{market}: [{item['status']}] {item['reason']}")
    return {"decision": decision, "markets": markets, "reasons": reasons}


def _index_series_for_market(market, data_dir=None):
    """
    시장별 지수 종가 이력 `{지수키: {날짜: 종가}}`. **읽기 전용.**
    코스피는 `market_history.csv`(`report_db.load_kospi_close_history()`), 미국은
    `data/us_index_history.json`(`report_db.load_us_index_closes()`) — 결투 실행 스크립트 두 개가
    각각 쓰는 원천과 같습니다. 없으면 빈 dict 로 두고, 그 사실은 호출부가 안내 문장으로 남깁니다.
    """
    spec = FRESHNESS_MARKETS[market]
    if market == scorecard_db.MARKET_KR:
        return {key: dict(load_kospi_close_history() or {}) for key in spec["index_keys"]}
    indices = load_us_index_closes(data_dir) or {}
    return {key: dict((indices.get(key) or {}).get("closes") or {}) for key in spec["index_keys"]}


def _previous_probe_from_history(market, session_date, *, index_series, data_dir=None):
    """
    수집기 이력 CSV 의 **직전 날짜 행**으로 "어제 점검표"를 만듭니다(§4-b 머리말 — 결투 기준선이
    오늘 스냅샷과 같은 날일 때의 대체 기준선). **읽기 전용.**

    이력 행에는 `rank`(시가총액 순위)와 `price` 가 스냅샷과 **같은 이름**으로 있어
    (`utils/stock_history.py::KOSPI_HISTORY_FIELDS` / `US_HISTORY_FIELDS`),
    `duel_batch.build_freshness_probe()` → `select_probe_stocks()` 를 그대로 재사용합니다 —
    상위 50종목을 고르는 코드를 여기서 다시 짜지 않습니다(§0-3-10).

    지수는 그 직전 날짜의 종가(`index_series[키][날짜]`)를 넣고, 없으면 그 지수를 뺀 채 만듭니다
    (`allow_empty_index=True`) — 그러면 `judge_crawl_freshness()` 가 "기준값에 지수가 없다"로
    `no_baseline` 을 돌려 검사가 생략됩니다(없는 값을 지어내지 않습니다, §0-1).

    반환: (점검표 dict 또는 None, 못 만든 이유 문장 또는 None)
    """
    spec = FRESHNESS_MARKETS[market]
    path = (os.path.join(data_dir, spec["history_filename"]) if data_dir
            else stock_history.stock_history_path(spec["history_filename"]))
    rows = stock_history.read_history_rows(path) or []
    dates = sorted({str(row.get(stock_history.DATE_FIELD) or "").strip()[:10] for row in rows})
    earlier = [day for day in dates if day and day < str(session_date)]
    if not earlier:
        return None, f"수집 이력({spec['history_filename']})에 {session_date} 이전 날짜 행이 없습니다."
    previous_date = earlier[-1]

    code_field = spec["code_field"]
    universe_like = {}
    for row in rows:
        if str(row.get(stock_history.DATE_FIELD) or "").strip()[:10] != previous_date:
            continue
        code = str(row.get(code_field) or "").strip()
        if code:
            universe_like[code] = {"price": row.get("price"), "rank": row.get("rank")}

    index_closes = {}
    for key in spec["index_keys"]:
        close = (index_series.get(key) or {}).get(previous_date)
        if close is not None:
            index_closes[key] = close

    probe = duel_batch.build_freshness_probe(previous_date, index_closes, universe_like,
                                            allow_empty_index=True)
    return probe, None


def load_freshness_inputs(*, session_dates, data_dir=None, state_paths=None):
    """
    (배치 전용 I/O) 시장별 신선도 검사 입력을 **읽기 전용**으로 준비합니다 —
    `evaluate_publish_freshness()` 에 그대로 넘길 `{시장: {...}}` 을 돌려줍니다.

    `data_dir` 는 유니버스 스냅샷·미국 지수·이력 CSV 를 찾는 곳(기본 `data/`),
    `state_paths` 는 `{시장: 결투 기준값 파일 경로}` 덮어쓰기(기본은 결투 모듈의
    `default_state_path()` / `default_state_path_usd()`) — 둘 다 **테스트가 임시 디렉터리로
    갈아끼우기 위한** 인자입니다.

    시장마다:
      ① 오늘 점검표 — 지수의 **가장 최근 종가**(결투 실행 스크립트와 같은 선택. 최신 날짜가
         스냅샷 거래일보다 낡은 지수는 뺍니다 — 결투 H-1 과 같은 이유) + 유니버스 스냅샷 상위
         50종목 → `duel_batch.build_freshness_probe()`.
      ② 기준선 — 결투 기준값 파일(`duel_batch.load_probe_state()`, 🔴 읽기만). 그 `target_date`
         가 오늘 스냅샷 거래일과 **다르면** 그것을, 같으면 수집 이력 CSV 의 직전 날짜 행을 씁니다
         (§4-b 머리말에 이유).
    어느 단계든 실패하면 예외를 올리지 않고 `notes` 에 사유를 적고 그 시장은 "검사 생략"이
    됩니다 — 기준선이 없거나 못 읽는 상태가 신규 배포 초기의 정상 상태이기 때문입니다.

    ⚠️ 이 함수는 파일을 **쓰지 않습니다.** 결투 기준값 파일의 갱신은 결투 배치만 합니다.
    """
    inputs = {}
    for market, spec in FRESHNESS_MARKETS.items():
        session_date = (session_dates or {}).get(market)
        notes = []
        entry = {"session_date": session_date, "today_probe": None, "previous_probe": None,
                 "baseline_source": None, "notes": notes}
        inputs[market] = entry
        if not session_date:
            notes.append(f"{spec['label']} 가격 스냅샷의 거래일을 확인하지 못했습니다.")
            continue

        # ── ① 오늘 점검표 ─────────────────────────────────────────────────────
        try:
            index_series = _index_series_for_market(market, data_dir=data_dir)
            today_index = {}
            for key, closes in index_series.items():
                if not closes:
                    notes.append(f"지수 {key} 의 종가 원천이 없어 비교에서 뺐습니다.")
                    continue
                latest = max(closes)
                if latest < str(session_date):
                    notes.append(
                        f"지수 {key} 원천이 {latest} 까지라 스냅샷 거래일({session_date})보다"
                        " 낡았습니다 — 그 지수는 비교에서 뺍니다(다른 파이프라인 산출물)."
                    )
                    continue
                today_index[key] = closes[latest]
            if not today_index:
                notes.append("비교할 지수가 하나도 남지 않아 이 시장 검사를 생략합니다.")
                continue
            universe_index, _meta = scorecard_db.load_universe_index(market, data_dir=data_dir)
            entry["today_probe"] = duel_batch.build_freshness_probe(
                session_date, today_index, universe_index)
        except DuelBatchError as exc:
            notes.append(f"오늘 신선도 점검표를 만들지 못해 검사를 생략합니다: {exc}")
            continue

        # ── ② 기준선 — 결투 기준값 파일(읽기만) → 같은 날이면 수집 이력 직전 행 ────
        state_path = (state_paths or {}).get(market) or spec["state_path"]()
        duel_probe = None
        try:
            duel_probe = duel_batch.load_probe_state(state_path)
            if duel_probe is None:
                notes.append(f"결투 신선도 기준선 파일이 없습니다({os.path.basename(state_path)}).")
        except DuelBatchError as exc:
            notes.append(f"결투 신선도 기준선 파일을 읽지 못했습니다: {exc}")

        if duel_probe is not None and duel_probe.get("target_date") != str(session_date):
            entry["previous_probe"] = duel_probe
            entry["baseline_source"] = BASELINE_SOURCE_DUEL
            continue
        if duel_probe is not None:
            notes.append(
                f"결투 기준선의 날짜({duel_probe.get('target_date')})가 오늘 스냅샷 거래일과 같습니다"
                " — 결투 배치가 이미 오늘 값을 기준선으로 남긴 뒤라, 수집 이력의 직전 날짜 행을"
                " 기준선으로 씁니다."
            )
        try:
            probe, why = _previous_probe_from_history(
                market, session_date, index_series=index_series, data_dir=data_dir)
        except DuelBatchError as exc:
            probe, why = None, str(exc)
        if probe is not None:
            entry["previous_probe"] = probe
            entry["baseline_source"] = BASELINE_SOURCE_HISTORY
        else:
            notes.append(f"수집 이력에서도 기준선을 만들지 못해 검사를 생략합니다: {why}")
    return inputs


# =============================================================================
# 5. 하루치 발행 배치 본체
# =============================================================================
def run_publish_batch(service_client, published_date, *, dry_run=False, price_lookup=None,
                      freshness_inputs=None):
    """
    (배치 전용) 하루치 공개 순위표를 **통째로 다시 발행**합니다.

    인자
        service_client : `scorecard_publish_db.create_service_client()` 결과
                         (RLS 우회 — 배치 전용). 🔴 앱 프로세스에서 부르지 마세요.
        published_date : 발행일. **기본값이 없습니다** — 이 모듈이 "오늘"을 스스로 정하지
                         않습니다. 배치가 자정 근처에 돌거나 하루 늦게 돌면 날짜가 조용히
                         틀어지고, 그건 나중에 복원할 수 없는 오염입니다(§0-1).
                         호출부(실행 스크립트)가 확정해서 넘깁니다.
        dry_run        : True 면 **읽기만** 하고 아무것도 쓰지 않습니다. 오너가 "무엇이
                         발행될 뻔했는지"를 먼저 눈으로 볼 수 있게 하는 안전장치입니다
                         (§0-3-6 의 "기본 숨김 → 확인 → 공개" 순서와 같은 정신).
        price_lookup   : `(market, ticker) -> 현재가 또는 None`. 생략하면 **"내 성적표"
                         화면과 같은 조회 함수**(`report_db.build_price_lookup()`)를 만들어
                         씁니다. 인자로 열어 둔 이유는 두 가지입니다 — ① 테스트가 가격
                         파일 없이 이 배치 전체를 돌릴 수 있어야 하고, ② 결투 배치들도
                         같은 방식으로 가격 조회를 **호출부에서 주입**받습니다
                         (`utils/duel_batch.py`).
                         ⚠️ 2026-08-29 재감사 H-3 — 원래 이 문단은 "가격을 하나도 못 구하면
                            그날 발행이 0행이 된다"고만 적혀 있었는데, 사실이 아니었습니다.
                            0행 발행은 곧바로 "발행 대상이 하나도 없다"로 읽혀 5단계에서
                            **과거 발행 이력 전체가 영구 삭제**됐습니다(수집 실패와 "이
                            구간 인원 미달"이 코드상 구분되지 않았기 때문). 지금은 그 전에
                            멈춥니다 — `price_lookup` 미지정 호출은 스냅샷을 실제로 확인
                            (`resolve_session_dates()`)하고, 그래도 못 읽으면
                            `ScorecardPublishError` 로 중단합니다(값을 추측해서 저장하거나
                            지우지 않습니다, §0-1 — `report_db.run_daily_snapshot_batch()`
                            와 같은 판단). 그 아래 5단계에도 "동의자는 있는데 전원
                            `no_return`" 상황을 한 번 더 잡는 안전장치를 뒀습니다.
        freshness_inputs : (2026-09-05, #201) 발행 전 **신선도(무변동) 검사**의 입력
                         `{시장: {session_date, today_probe, previous_probe, ...}}`.
                         생략하면 — `price_lookup` 도 생략한 실제 배치 실행에서는 —
                         `load_freshness_inputs()` 가 저장소 파일에서 **읽기 전용**으로
                         만듭니다(결투 기준값 파일 + 수집 이력 CSV + 지수 원천). 테스트는
                         `price_lookup` 과 함께 이 dict 를 직접 넣어 파일 없이 판정을
                         검증하고, 둘 다 생략한 예전 테스트 호출(`price_lookup` 만 주입)은
                         검사 없이 예전과 똑같이 돕니다. 빈 dict 는 "검사할 시장 없음".
                         정책(§4-b 머리말): `failed` 는 **완전 중단**, `failed_or_holiday`·
                         `needs_review` 는 **오늘 발행 건너뜀**(철회 청소만 하고 정상 종료),
                         기준선이 없으면 검사 생략 후 평소대로.

    반환: 요약 dict(로그·작업보고용). `format_summary_lines()` 로 사람이 읽는 줄로 바꿉니다.

    ── 하루 한 번, 이 순서로 ────────────────────────────────────────────────────
      ⓪-1. **신선도 검사**(#201) — 결투와 같은 무변동 검사. `failed` 면 여기서 중단
      0. **철회 청소** — 철회한 사용자의 발행 기록을 모든 날짜에서 삭제
      ⓪-2. 신선도 검사가 `skip` 이면 **여기서 정상 종료**(아래는 하지 않음)
      1. 발행 대상 고르기 — `final_confirmed=true` 그리고 `revoked_at is null`
      2. 그 사용자들의 "내 성적표" 보유종목을 한 번에 읽어 통화별 포트폴리오로 집계
      3. 체급 — 통화별 매입원가합계 → 시즌 고정 규칙 적용
      4. 수익률 → (통화 × 체급) 그룹별 순위
      5. **최소 인원** 게이팅 — 미달 그룹은 발행 안 하고, 과거 행도 삭제
      6. 그날 발행분 **통째로** 삭제 → 새로 삽입

    ── 질의 횟수 (§0-3-2) ───────────────────────────────────────────────────────
    사용자가 3명이든 3만명이든 **왕복 수가 사용자 수에 비례하지 않습니다.** 고정 왕복은
      동의 조회 1 · 철회 조회 1 · 시즌 체급 배정 1 · 발행표 존재 확인 1 ·
      당일 발행분 삭제 2 · 미달 그룹 점검 18(상수)
    이고, 나머지(보유종목 조회 · 닉네임 조회 · 배정 기록 · 발행 삽입 · 철회 삭제)는 **요청
    크기를 자르는 청크 수**에 비례합니다 — 사용자마다 부르는 것이 아니라 한 요청이 지나치게
    커지지 않게 자르는 것입니다. `tests/test_scorecard_publish.py` 가 이 성질을 고정합니다.
    """
    if service_client is None:
        raise ScorecardPublishError(
            "발행 배치용 Supabase 클라이언트가 없습니다"
            " (scorecard_publish_db.create_service_client() 결과를 넘겨주세요)."
        )
    day_iso = _to_date(published_date, "발행일").isoformat()
    season_key = duel_rules.season_key_for_date(day_iso)

    # 2026-08-29 재감사 H-3 — `price_lookup` 을 안 넘긴 실제 배치 실행에서는, 가격 스냅샷
    # (`data/*.json`) 을 하나도 못 읽는 것과 "이 구간에 사람이 최소 인원 미만이다"(정상적인
    # 게이팅 — 2026-09-03 부터 문턱 1명)가 **코드상 완전히 같은 상태**(전원 `no_return`)가 됩니다. 그 상태가
    # 아래 5단계에서 "발행 대상이 없다"로 읽혀 **과거 발행 이력 전체를 영구 삭제**합니다.
    # `report_db.run_daily_snapshot_batch()` 가 같은 상황에서 이미 하는 것처럼, 스냅샷을
    # 아예 못 읽었으면 값을 추측해서 진행하지 않고 여기서 멈춥니다(§0-1).
    if price_lookup is None:
        available_dates, _notes = resolve_session_dates()
        if not available_dates:
            raise ScorecardPublishError(
                "어느 시장의 거래일도 확인하지 못했습니다 — 가격 스냅샷(data/*.json)이 "
                "없거나 형식이 바뀌었습니다. 값을 추측해서 발행하지 않고 중단합니다."
            )
        if freshness_inputs is None:
            # #201 — 실제 배치 실행(가격 조회도 파일에서)에서만 파일을 읽습니다. 읽기 전용.
            freshness_inputs = load_freshness_inputs(session_dates=available_dates)
    lookup = price_lookup if price_lookup is not None else build_price_lookup()

    # ── ⓪-1. 신선도(무변동) 검사 — 결투와 같은 판정, 정책은 §4-b 머리말 (#201) ─────────
    freshness = evaluate_publish_freshness(freshness_inputs)

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
        "revoked_users": 0,
        "revoked_rows_deleted": 0,
        "pruned_group_rows_deleted": 0,
        "new_bracket_assignments": 0,
        "bracket_status_counts": {},
        "freshness": freshness,
        "publish_skipped": False,
        "publish_skip_reason": None,
    }

    if freshness["decision"] == FRESHNESS_ABORT:
        # 명백한 수집 실패(지수·종목 움직임이 앞뒤가 안 맞음). 과거 발행 이력을 지우기 **전에**
        # 멈춥니다 — H-3 과 같은 원칙(값을 추측해서 저장하거나 지우지 않습니다, §0-1).
        raise ScorecardPublishError(
            "발행 전 신선도 검사에서 가격 수집 실패로 판정돼 중단합니다(과거 발행 이력은 "
            "그대로 둡니다 — 가격 스냅샷과 수집 워크플로우를 확인해 주세요): "
            + " / ".join(freshness["reasons"])
        )

    # ── 0. 철회 청소 — **다른 무엇보다 먼저** ────────────────────────────────────
    #    발행 대상을 고르는 것보다 먼저 지웁니다. 순서를 뒤집으면, 오늘 발행이 어떤 이유로
    #    중간에 실패했을 때 "철회한 사람의 과거 기록이 그대로 남은 채 하루가 더 가는" 상태가
    #    됩니다. 지우는 일이 실패해도 그건 예외로 올라가 배치 전체가 시끄럽게 멈춥니다.
    revoked = scorecard_publish_db.fetch_revoked_consent_users(service_client)
    summary["revoked_users"] = len(revoked)
    if revoked and not dry_run:
        revoked_user_ids = [str(row["user_id"]) for row in revoked if row.get("user_id")]
        revoked_nicknames = scorecard_publish_db.fetch_nicknames_for_users(
            service_client, revoked_user_ids)
        summary["revoked_rows_deleted"] = \
            scorecard_publish_db.delete_published_rows_for_nicknames(
                service_client, list(revoked_nicknames.values()))

    # ── ⓪-2. 신선도 검사가 "건너뜀"이면 여기서 정상 종료 (#201) ──────────────────
    #    휴장일이거나 수집이 실패했는지 구분되지 않는 날(값이 전부 전일과 동일) · 무변동
    #    종목이 허용치를 넘어 사람이 봐야 하는 날은, 어제 발행분을 그대로 두는 것이 낡은
    #    가격에 오늘 날짜를 붙여 발행하는 것보다 낫습니다. 철회 청소는 위에서 이미 했습니다.
    if freshness["decision"] == FRESHNESS_SKIP:
        summary["publish_skipped"] = True
        summary["publish_skip_reason"] = " / ".join(freshness["reasons"])
        return summary

    # ── 1. 발행 대상 고르기 ──────────────────────────────────────────────────────
    consents = scorecard_publish_db.fetch_publishable_consents(service_client)
    summary["consent_count"] = len(consents)
    consent_user_ids = [str(row["user_id"]) for row in consents if row.get("user_id")]

    # ── 2. 🔴 실제 자산(`holdings`)을 읽는 것은 이 배치에서 **여기 한 번뿐**입니다 ────
    #    대상은 위에서 고른 발행 대상 사용자로만 좁혀집니다. 동의자가 0명이면 그 함수는
    #    질의 자체를 보내지 않습니다.
    holding_rows = scorecard_publish_db.fetch_holdings_for_users(
        service_client, consent_user_ids)
    portfolios_by_user = build_portfolios_by_user(holding_rows, lookup)

    # ── 3. 체급 (통화별) ────────────────────────────────────────────────────────
    existing_assignments = scorecard_publish_db.fetch_bracket_assignments(
        service_client, season_key)
    brackets_by_user_currency, new_assignments = {}, []
    for user_id in consent_user_ids:
        portfolio = portfolios_by_user.get(user_id) or {}
        for currency in PUBLISHED_CURRENCIES:
            summary_for_currency = portfolio.get(currency)
            if not summary_for_currency or not (summary_for_currency.get("rows") or []):
                # 그 통화로는 보유가 없습니다 — 체급을 매길 대상이 아닙니다(배정 기록도
                # 만들지 않습니다. 만들면 나중에 그 통화를 시작했을 때 "보유도 없던 시절의
                # 구간 미적용"이 시즌 내내 그 사람을 따라다닙니다).
                continue
            cost_basis = resolve_bracket_cost_basis(summary_for_currency)
            resolved = resolve_bracket_for_user_currency(
                currency, cost_basis,
                existing_assignments.get((user_id, currency)), day_iso)
            brackets_by_user_currency[(user_id, currency)] = resolved["bracket_key"]
            status_key = (resolved["fresh_source"] if resolved["source"] == "assigned"
                          else "kept")
            summary["bracket_status_counts"][status_key] = \
                summary["bracket_status_counts"].get(status_key, 0) + 1
            if resolved["needs_write"]:
                new_assignments.append({"user_id": user_id, "currency": currency,
                                        "season_key": season_key,
                                        "bracket_key": resolved["bracket_key"]})
    if new_assignments and not dry_run:
        summary["new_bracket_assignments"] = \
            scorecard_publish_db.insert_bracket_assignments(service_client, new_assignments)

    nicknames_by_user = scorecard_publish_db.fetch_nicknames_for_users(
        service_client, consent_user_ids)

    # ── 4. 조립 + 순위 ───────────────────────────────────────────────────────────
    built = build_publish_rows(consents, portfolios_by_user, nicknames_by_user,
                               brackets_by_user_currency)
    summary["skipped"] = built["skipped"]
    summary["group_counts"] = {f"{currency}/{bracket}": len(entries)
                               for (currency, bracket), entries in built["groups"].items()}

    # ── 5. 최소 인원 게이팅 ──────────────────────────────────────────────────────
    publishable, blocked = split_groups_by_threshold(built["groups"])
    summary["published_groups"] = sorted(f"{c}/{b}" for c, b in publishable)
    summary["blocked_groups"] = sorted(f"{c}/{b}" for c, b in blocked)

    #    발행하지 않는 그룹 = 전체 18개 중 오늘 발행되는 것을 뺀 나머지. 인원이 줄어 미달이
    #    된 그룹뿐 아니라 **참가자가 전부 사라진 그룹**까지 포함해야 과거 행이 안 남습니다.
    #    ⚡ 발행표가 아직 완전히 비어 있으면(초기 운영 기간) 18번이 전부 헛걸음이라,
    #       질의 하나로 먼저 확인하고 건너뜁니다.
    #
    # 2026-08-29 재감사 H-3 — 위쪽 스냅샷 확인이 "완전히 못 읽음"은 잡아 주지만, "일부만
    # 읽혔는데 하필 오늘 발행 대상 전원의 종목만 못 읽음" 같은 경계 상황은 못 잡습니다.
    # 그래서 여기 한 번 더 확인합니다: 동의자가 있는데(자격 문제가 아닌데) 아무도 발행
    # 대상이 못 됐고 그 이유가 전부 "수익률 계산 불가"뿐이면, 그건 인원 미달(정상)이 아니라
    # 데이터 문제이므로 과거 이력을 지우지 않고 멈춥니다(§0-1).
    if (not dry_run and summary["consent_count"] > 0 and not publishable
            and built["skipped"]
            and all(item.get("reason") == SKIP_NO_RETURN for item in built["skipped"])):
        raise ScorecardPublishError(
            f"동의자 {summary['consent_count']}명 전원의 수익률을 계산하지 못해 발행 대상이 "
            "0명입니다 — 정상적인 인원 미달이 아니라 데이터 문제로 보여, 과거 발행 이력을 "
            "지우지 않고 중단합니다(가격 스냅샷을 확인해 주세요)."
        )

    to_prune = [key for key in all_possible_groups() if key not in publishable]
    if not dry_run and to_prune and scorecard_publish_db.leaderboard_has_any_rows(service_client):
        for currency, bracket_key in to_prune:
            summary["pruned_group_rows_deleted"] += \
                scorecard_publish_db.delete_published_group(service_client, currency, bracket_key)

    # ── 6. 그날 발행분 통째로 갈아끼우기 ─────────────────────────────────────────
    leaderboard_rows, holdings_rows = [], []
    for key, entries in sorted(publishable.items()):
        leaderboard_rows.extend(leaderboard_payload(key, entries))
        holdings_rows.extend(holdings_payload(key, entries))
    summary["leaderboard_rows"] = len(leaderboard_rows)
    summary["holdings_rows"] = len(holdings_rows)

    if dry_run:
        return summary

    scorecard_publish_db.delete_published_rows_for_date(service_client, day_iso)
    # 2026-08-29 재감사 M-2 — 원래는 순위표를 먼저, 보유종목을 나중에 썼습니다. 두 표는
    # 트랜잭션으로 묶이지 않고(Supabase REST 의 한계) 보유종목은 청크 단위로 여러 번
    # insert 되므로, "순위표 write 완료 ~ 보유종목 write 완료" 사이에는 순위표는 있는데
    # 그날 보유종목 행은 아직 0개인 창이 생깁니다. 그동안 "📄 보유종목 보기"를 누른
    # 방문자는 실제로 동의·보유가 있는데도 "공개되어 있지 않습니다"라는 **거짓 문장**을
    # 봅니다(§0-1). 순서를 바꾸면 그 창에는 "보유종목만 있고 순위표가 아직 없음"이 되는데,
    # `fetch_public_leaderboard_latest_date()`가 최신 발행일을 순위표 존재로 판정하므로
    # 그 상태는 발견 경로(순위표) 자체가 안 열려 있어 아무에게도 보이지 않습니다 —
    # `report_db.save_holding_snapshots()`가 "합계 먼저, 종목별 나중"을 쓰는 것과 반대
    # 방향이지만, 그쪽은 두 표 다 항상 함께 발견되고 여기는 순위표가 "문"이라는 점이
    # 다릅니다.
    scorecard_publish_db.write_public_holdings(service_client, day_iso, holdings_rows)
    scorecard_publish_db.write_public_leaderboard(service_client, day_iso, leaderboard_rows)
    return summary


def build_portfolios_by_user(holding_rows, price_lookup):
    """
    `fetch_holdings_for_users()` 결과(여러 사용자가 섞인 한 목록) →
    `{user_id: build_portfolio() 결과}`.

    계산을 여기서 새로 짜지 않습니다(§0-3-10) — "내 성적표" 화면이 쓰는 그 함수를 그대로
    부릅니다. 여기서 같은 곱셈·합산을 다시 쓰면 화면의 숫자와 순위표의 숫자가 언젠가
    갈라집니다.

    ⚠️ 보유가 하나도 없는 사용자는 이 dict 에 **키가 생기지 않습니다.** 호출부가 그것을
       "발행에서 빠짐(사유: 보유 없음)"으로 다룹니다 — 0원으로 채우지 않습니다(§0-1).
    """
    grouped = {}
    for row in holding_rows or []:
        user_id = (row or {}).get("user_id")
        if user_id:
            grouped.setdefault(str(user_id), []).append(row)

    portfolios = {}
    for user_id, rows in grouped.items():
        try:
            portfolios[user_id] = scorecard_db.build_portfolio(rows, price_lookup)
        except Exception as exc:  # noqa: BLE001 - scorecard 쪽 예외 종류가 여럿입니다
            # 값을 추측해서 이어 가지 않습니다. 사용자 하나의 데이터가 이상하면 그날 발행을
            # 멈추는 편이, 틀린 수익률을 남에게 공개하는 것보다 낫습니다(§0-1 / §0-3-8).
            raise ScorecardPublishError(
                f"보유종목으로 포트폴리오를 집계하지 못했습니다(user_id={user_id}): {exc}"
            ) from exc
    return portfolios


# =============================================================================
# 6. 요약 출력 — GitHub Actions 로그에서 오너가 눈으로 읽을 줄
# =============================================================================
def format_summary_lines(summary):
    """
    `run_publish_batch()` 결과를 사람이 읽는 줄 목록으로.
    **빠진 것과 막힌 것을 반드시 드러냅니다**(§0-1: 조용히 넘어가지 않기).

    🔴 사용자 식별자는 한 줄도 찍지 않습니다. `summary["skipped"]` 는 진단을 위해 `user_id`
       를 들고 있지만(메모리 안에서만), 여기서는 **사유별 개수만** 셉니다 — 이 함수의 출력은
       GitHub Actions 로그에 그대로 남고, 그 로그는 발행표만큼 조심해야 할 자리입니다.
       `tests/test_scorecard_publish.py` 가 이 성질을 회귀로 고정합니다.
    """
    data = summary or {}
    lines = [
        f"📅 발행일 {data.get('published_date')} (시즌 {data.get('season_key')})"
        + ("  ⚠️ DRY RUN — 아무것도 쓰지 않았습니다" if data.get("dry_run") else ""),
        f"👥 발행 대상 동의 사용자: {data.get('consent_count', 0)}명",
        f"🧱 체급 배정: 새로 {data.get('new_bracket_assignments', 0)}건"
        f" (시즌 중 유지 포함 내역: {data.get('bracket_status_counts') or {}})",
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
        lines.append(f"⚠️ 발행에서 빠진 사용자 {len(skipped)}명 — 사유별: {reasons}")

    if data.get("freshness"):
        lines.extend(format_freshness_lines(data["freshness"]))

    lines.append(
        f"🧹 철회 사용자 {data.get('revoked_users', 0)}명 처리"
        f" (지운 공개 행 {data.get('revoked_rows_deleted', 0)}개),"
        f" 미달 그룹 정리로 지운 행 {data.get('pruned_group_rows_deleted', 0)}개")
    if data.get("publish_skipped"):
        lines.append(
            "⏭️ 오늘 발행을 건너뛰었습니다(기존 발행 내역 유지) — "
            f"{data.get('publish_skip_reason') or '사유 없음'}")
    else:
        lines.append(
            f"📤 발행: 순위 {data.get('leaderboard_rows', 0)}행 /"
            f" 보유종목 {data.get('holdings_rows', 0)}행")
    return lines


def format_freshness_lines(freshness):
    """
    `summary["freshness"]`(= `evaluate_publish_freshness()` 결과) → 사람이 읽는 줄 목록.
    (#201) 검사한 시장은 판정·기준선 날짜·출처·비교 종목 수를, 생략한 시장은 **왜 생략했는지**를
    반드시 찍습니다 — "검사했다"와 "검사하지 못했다"가 로그에서 같은 모양이면 안 됩니다(§0-1).
    사용자 식별자는 이 자료에 애초에 없습니다(지수·종목 코드·가격뿐).
    """
    data = freshness or {}
    markets = data.get("markets") or {}
    if not markets:
        return ["🩺 발행 전 신선도 검사: 검사할 시장 입력이 없어 생략했습니다."]
    lines = [f"🩺 발행 전 신선도(무변동) 검사 — 결정: {data.get('decision')}"]
    for market in sorted(markets):
        item = markets[market] or {}
        if item.get("checked"):
            lines.append(
                f"    · {market}: 검사함 → {item.get('status')} ({item.get('decision')})"
                f" — 기준선 {item.get('baseline_date') or '?'} ({item.get('baseline_source') or '?'}),"
                f" 비교 종목 {item.get('compared_stocks', 0)}개"
                f"(명단 교체 {item.get('dropped_stocks', 0)}개) — {item.get('reason')}")
        else:
            lines.append(f"    · {market}: 검사 생략 — {item.get('reason')}")
        for note in item.get("notes") or []:
            lines.append(f"        ↳ {note}")
    return lines
