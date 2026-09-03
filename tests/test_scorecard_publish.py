# tests/test_scorecard_publish.py
"""
📋 "내 성적표" 공개 순위표 — **발행 인프라** 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · `supabase` 패키지 설치 여부와 무관)

`tests/test_duel_publish.py`(은퇴하는 결투 공개 계층)의 구조를 그대로 옮긴 스위트입니다.
가짜 Supabase 클라이언트와 손으로 만든 값으로만 검증하고, 여기서 보는 것은
**"남에게 보여도 되는 것만, 사실 그대로 보여지는가"** 입니다.

가짜 클라이언트(`FakeClient`)는 `tests/test_duel_db.py` 가 갖고 있는 것을 그대로 씁니다 —
같은 걸 다시 짜면 두 스위트가 서로 다른 방식으로 Supabase 를 흉내내기 시작합니다
(§0-3-10 — 흉내도 단일 출처로).

검증 대상
    ① 🔴 `resolve_portfolio_return_pct()` — 이 작업에서 **새로 쓴 계산 ①**.
       분모가 `total_cost_priced`(가격을 확인한 종목의 매입원가)인가, 계산 불가일 때
       0 이 아니라 None 인가.
    ② 🔴 `resolve_bracket_cost_basis()` — **새로 쓴 계산 ②**. 체급 입력은 반대로
       `total_cost`(전 종목)이고, 그 값이 KRW·USD 체급 경계와 정확히 맞물리는가.
    ③ `assert_full_consent()` — 전부 아니면 전무, 철회·미확인 행 거절.
    ④ `build_publish_rows()` — `(currency, bracket_key)` 로 묶이는가, 수익률 없는 사용자를
       0% 로 채우지 않고 빼는가.
    ⑤ 발행 payload 에 `user_id` 가 절대 실리지 않는가(`FORBIDDEN_PUBLISH_FIELDS` 재사용).
    ⑥ 최소 인원 경계(`MIN_PARTICIPANTS_FOR_PUBLICATION` — 2026-09-03 부터 1명, 0 vs 1), 미달 그룹의 과거 행 제거.
    ⑦ 🔴 **원화·달러가 어디서도 섞이지 않는가** — 체급 키 집합, 그룹, 발행 payload, 삭제 필터.
    ⑧ 전량 재작성 · dry-run 무기록 · §0-3-2(사용자 수와 무관한 왕복 수).
    ⑨ 🔴 **종목별 상세지표 5종**(2026-08-23 신설) — 이미 계산된 값을 그대로 옮기는가,
       `consent_holding_details` 없이는 다섯 값이 전부 None 인가(0 이 아니라), 그리고
       스키마 추가분(ALTER)이 두 SQL 파일에 **같은 내용으로** 들어 있는가.

실행: pytest tests/test_scorecard_publish.py -v
"""

import ast
import inspect
import sys
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient  # noqa: E402
from utils import duel_db, duel_rules, scorecard_db  # noqa: E402
from utils import scorecard_publish, scorecard_publish_db  # noqa: E402
from utils.duel_db import DuelDbError  # noqa: E402
from utils.duel_rules import KST, DuelRuleError  # noqa: E402
from utils.scorecard_publish import ScorecardPublishError  # noqa: E402

TODAY = date(2026, 8, 23)
SEASON = "2026-03-01"

KRW = scorecard_db.CURRENCY_KRW
USD = scorecard_db.CURRENCY_USD


# =============================================================================
# 0. 손으로 만드는 입력들
# =============================================================================
def _kr_holding(user_id, quantity, price, ticker="005930", stock_name="삼성전자"):
    return {"user_id": user_id, "market": "KR", "ticker": ticker, "stock_name": stock_name,
            "quantity": quantity, "avg_purchase_price": price, "currency": KRW}


def _us_holding(user_id, quantity, price, ticker="AAPL", stock_name="Apple"):
    return {"user_id": user_id, "market": "US", "ticker": ticker, "stock_name": stock_name,
            "quantity": quantity, "avg_purchase_price": price, "currency": USD}


def _prices(mapping):
    """`{(market, ticker): 현재가}` → `build_portfolio()` 에 넘길 조회 함수."""
    return lambda market, ticker: mapping.get((market, ticker))


def _summary(holdings, prices):
    """보유 목록 + 가격표 → 그 통화의 `build_portfolio()` 요약 하나."""
    portfolio = scorecard_db.build_portfolio(holdings, _prices(prices))
    assert len(portfolio) == 1, "이 헬퍼는 한 통화짜리 입력에만 씁니다"
    return next(iter(portfolio.values()))


def _consent_row(user_id="user-1", **overrides):
    row = {"user_id": user_id, "final_confirmed": True, "revoked_at": None}
    row.update({flag: True for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS})
    row.update(overrides)
    return row


# =============================================================================
# 1. 🔴 새 계산 ① — 포트폴리오 수익률
# =============================================================================
def test_return_pct_matches_the_scorecard_profit_rule():
    """
    `evaluate_holding()` 의 개별 종목 `profit_pct` 와 **같은 규칙**이어야 합니다:
    (평가금액 − 매입원가) / 매입원가 × 100.

    10주 × 100,000원 매입(= 100만원) → 현재가 120,000원(= 120만원 평가) → +20%.
    """
    summary = _summary([_kr_holding("u1", 10, 100_000)], {("KR", "005930"): 120_000})
    assert scorecard_publish.resolve_portfolio_return_pct(summary) == pytest.approx(20.0)

    # 개별 종목 규칙과 **같은 숫자**가 나오는지 직접 맞춰 봅니다(§0-3-10).
    assert summary["rows"][0]["profit_pct"] == pytest.approx(20.0)


def test_return_pct_is_negative_when_the_portfolio_lost_money():
    """손실은 음수 그대로입니다 — 0 으로 바닥을 깔지 않습니다."""
    summary = _summary([_kr_holding("u1", 10, 100_000)], {("KR", "005930"): 75_000})
    assert scorecard_publish.resolve_portfolio_return_pct(summary) == pytest.approx(-25.0)


def test_return_pct_divides_by_the_priced_cost_not_the_total_cost():
    """
    🔴 이 작업에서 가장 조심한 한 줄. `build_portfolio()` 의 `total_profit` 은
    **가격을 확인한 종목만의** (평가금액 − 매입원가)입니다. 그 분자를 `total_cost`
    (가격을 못 구한 종목까지 포함한 전체 합)로 나누면 분자와 분모의 모집단이 어긋나서
    수익률이 실제보다 0% 쪽으로 눌립니다(§0-1 — 사실이 아닌 정보 발행).

    여기서는 두 종목 중 하나만 가격이 있습니다:
        005930 : 10주 × 10만원 = 100만원 매입 → 12만원 평가 = 120만원  (+20%)
        000660 : 10주 × 10만원 = 100만원 매입 → **가격 없음**
    올바른 답은 +20% 입니다. `total_cost`(200만원)로 나눴다면 +10% 가 나옵니다.
    """
    summary = _summary(
        [_kr_holding("u1", 10, 100_000), _kr_holding("u1", 10, 100_000, ticker="000660")],
        {("KR", "005930"): 120_000})

    assert summary["total_cost"] == pytest.approx(2_000_000)        # 전 종목
    assert summary["total_cost_priced"] == pytest.approx(1_000_000)  # 가격 아는 종목만
    assert summary["total_profit"] == pytest.approx(200_000)

    got = scorecard_publish.resolve_portfolio_return_pct(summary)
    assert got == pytest.approx(20.0), "분모는 total_cost_priced 여야 합니다"
    assert got != pytest.approx(10.0), "total_cost 로 나누면 수익률이 눌립니다"


def test_return_pct_is_none_when_no_holding_has_a_price():
    """
    🔴 §0-1 — 가격을 하나도 못 구하면 **계산 불가**이지 0% 가 아닙니다.
    0% 로 세우면 그 사람은 실제로 존재하지 않는 성적으로 남들 위나 아래에 섭니다.
    """
    summary = _summary([_kr_holding("u1", 10, 100_000)], {})
    assert summary["total_cost_priced"] is None
    assert summary["total_profit"] is None
    assert scorecard_publish.resolve_portfolio_return_pct(summary) is None


@pytest.mark.parametrize("summary", [
    None,
    {},
    {"total_cost_priced": None, "total_profit": None},
    {"total_cost_priced": 0, "total_profit": 0},        # 0 으로 나눌 수 없습니다
    {"total_cost_priced": 0.0, "total_profit": 100.0},
    {"total_cost_priced": -1, "total_profit": 5},        # 음수 매입원가 = 데이터 손상
])
def test_return_pct_returns_none_instead_of_zero_for_every_uncomputable_case(summary):
    """계산할 수 없는 모든 경우가 **None** 입니다 — 한 곳도 0 으로 새지 않습니다(§0-1)."""
    assert scorecard_publish.resolve_portfolio_return_pct(summary) is None


def test_return_pct_of_exactly_zero_is_kept_as_zero_not_none():
    """
    반대 방향도 못 박습니다 — **진짜 0%** 는 정상값이라 None 으로 바꾸면 안 됩니다.
    (매입가와 현재가가 같은 상태. `or` 로 falsy 를 다루면 여기서 값이 사라집니다.)
    """
    summary = _summary([_kr_holding("u1", 10, 100_000)], {("KR", "005930"): 100_000})
    got = scorecard_publish.resolve_portfolio_return_pct(summary)
    assert got == 0.0
    assert got is not None


def test_return_pct_raises_on_corrupt_numbers_instead_of_silently_dropping_the_user():
    """
    숫자가 아닌 값은 "계산 불가"가 아니라 **데이터 손상**입니다. 조용히 None 으로 바꿔
    그 사용자만 빠뜨리면 아무도 그 사실을 모릅니다(§0-1).
    """
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.resolve_portfolio_return_pct(
            {"total_cost_priced": "많이", "total_profit": 1})
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.resolve_portfolio_return_pct(
            {"total_cost_priced": 100, "total_profit": float("nan")})


# =============================================================================
# 2. 🔴 새 계산 ② — 체급 입력(매입원가합계)
# =============================================================================
def test_bracket_cost_basis_uses_the_scorecard_cost_rule():
    """매입원가 = 수량 × 평균매입가. 그 규칙은 `scorecard_db.evaluate_holding()` 것을 씁니다."""
    summary = _summary(
        [_kr_holding("u1", 10, 700_000), _kr_holding("u1", 3, 100_000, ticker="000660")],
        {("KR", "005930"): 800_000})
    assert scorecard_publish.resolve_bracket_cost_basis(summary) == pytest.approx(7_300_000)


def test_bracket_cost_basis_includes_unpriced_holdings_unlike_the_return():
    """
    🔴 수익률과 **일부러 다른 필드**를 씁니다. 체급은 "얼마를 굴리는가"라, 오늘 가격
    스냅샷에 그 종목이 들어 있었는지와 무관해야 합니다 — `total_cost_priced` 를 쓰면 오늘
    가격 파일에 빠진 종목이 있는 사람만 갑자기 가벼운 체급으로 내려갑니다.
    (은퇴하는 `duel_publish.summarize_real_principal()` 도 같은 이유로 `total_cost` 를
     썼습니다.)
    """
    summary = _summary(
        [_kr_holding("u1", 10, 100_000), _kr_holding("u1", 10, 100_000, ticker="000660")],
        {("KR", "005930"): 120_000})       # 000660 은 가격 없음
    assert scorecard_publish.resolve_bracket_cost_basis(summary) == pytest.approx(2_000_000)
    assert summary["total_cost_priced"] == pytest.approx(1_000_000)


def test_bracket_cost_basis_is_none_when_there_are_no_holdings_in_that_currency():
    """
    🔴 §0-1 — "이 통화로는 아직 아무것도 등록하지 않음"을 "0원어치 보유"로 바꾸면 그 사람은
    자기 것이 아닌 최하위 체급에 들어갑니다. 그래서 값을 만들지 않고 None(→ 구간 미적용).
    """
    assert scorecard_publish.resolve_bracket_cost_basis(None) is None
    assert scorecard_publish.resolve_bracket_cost_basis({}) is None
    assert scorecard_publish.resolve_bracket_cost_basis({"rows": [], "total_cost": 0}) is None

    resolved = scorecard_publish.resolve_bracket_for_user_currency(KRW, None, None, TODAY)
    assert resolved["bracket_key"] == duel_rules.BRACKET_NONE_KEY
    assert resolved["fresh_source"] == scorecard_publish.BRACKET_SOURCE_NO_COST_BASIS


def test_bracket_cost_basis_refuses_a_negative_total():
    """매입원가합계가 음수인 상태는 데이터 손상이지 체급이 아닙니다(§0-1)."""
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.resolve_bracket_cost_basis(
            {"rows": [{"ticker": "005930"}], "total_cost": -1})


# ── 2-1. KRW 체급 경계 8개 — 기존 결투 테스트가 쓰는 값을 **그대로** 씁니다 ────────────
#  경계는 전부 **[하한 이상, 상한 미만)** 이고, 경계값 **그 자체**(정확히 1억원, 정확히
#  6천만원 …)가 **위쪽** 구간으로 갑니다("1억원 이상"이 오너 원문). 여기가 틀리면 딱 경계에
#  선 사람이 남의 체급에서 겨룹니다.
@pytest.mark.parametrize("amount,expected", [
    (100_000_000, "krw_100m_plus"),        # 경계값 그 자체는 **위쪽** 구간
    (999_999_999, "krw_100m_plus"),
    (100_000_001, "krw_100m_plus"),
    (99_999_999, "krw_60m_100m"),          # 1억원 바로 아래
    (60_000_000, "krw_60m_100m"),          # 경계값 그 자체
    (59_999_999, "krw_30m_60m"),
    (30_000_000, "krw_30m_60m"),
    (29_999_999, "krw_10m_30m"),
    (10_000_000, "krw_10m_30m"),
    (9_999_999, "krw_5m_10m"),
    (5_000_000, "krw_5m_10m"),
    (4_999_999, "krw_3m_5m"),
    (3_000_000, "krw_3m_5m"),
    (2_999_999, "krw_1m_3m"),
    (1_000_000, "krw_1m_3m"),
    (999_999, "krw_under_1m"),
    (0, "krw_under_1m"),
])
def test_bracket_cost_basis_feeds_the_krw_boundaries_exactly(amount, expected):
    """
    체급 입력 헬퍼가 만든 값이 `duel_rules.assign_bracket()` 의 8구간 경계와 정확히
    맞물리는지. 금액을 1주 × 그 금액으로 만들어 헬퍼를 통과시킵니다(직접 숫자를 넣는
    것이 아니라 **실제 경로**를 지나가게 하려고).
    """
    summary = _summary([_kr_holding("u1", 1, amount)] if amount else
                       [{"user_id": "u1", "market": "KR", "ticker": "005930",
                         "stock_name": "삼성전자", "quantity": 1,
                         "avg_purchase_price": 0, "currency": KRW}], {})
    cost_basis = scorecard_publish.resolve_bracket_cost_basis(summary)
    assert cost_basis == pytest.approx(amount)

    resolved = scorecard_publish.resolve_bracket_for_user_currency(
        KRW, cost_basis, None, TODAY)
    assert resolved["bracket_key"] == expected
    assert resolved["bracket_key"] in duel_rules.BRACKET_KEYS


# ── 2-2. USD 체급 경계 8개 — KRW 와 **같은 배율**($750 기준 100/60/30/10/5/3/1) ────────
@pytest.mark.parametrize("amount,expected", [
    (75_000, "usd_75000_plus"),
    (999_999, "usd_75000_plus"),
    (74_999, "usd_45000_75000"),
    (45_000, "usd_45000_75000"),
    (44_999, "usd_22500_45000"),
    (22_500, "usd_22500_45000"),
    (22_499, "usd_7500_22500"),
    (7_500, "usd_7500_22500"),
    (7_499, "usd_3750_7500"),
    (3_750, "usd_3750_7500"),
    (3_749, "usd_2250_3750"),
    (2_250, "usd_2250_3750"),
    (2_249, "usd_750_2250"),
    (750, "usd_750_2250"),
    (749, "usd_under_750"),
    (0, "usd_under_750"),
])
def test_bracket_cost_basis_feeds_the_usd_boundaries_exactly(amount, expected):
    summary = _summary([{"user_id": "u1", "market": "US", "ticker": "AAPL",
                         "stock_name": "Apple", "quantity": 1,
                         "avg_purchase_price": amount, "currency": USD}], {})
    cost_basis = scorecard_publish.resolve_bracket_cost_basis(summary)
    assert cost_basis == pytest.approx(amount)

    resolved = scorecard_publish.resolve_bracket_for_user_currency(
        USD, cost_basis, None, TODAY)
    assert resolved["bracket_key"] == expected
    assert resolved["bracket_key"] in duel_rules.BRACKET_KEYS_USD


def test_bracket_stays_fixed_mid_season_even_if_the_cost_basis_changes():
    """
    🔴 "체급은 시즌 동안 고정". 이 배치는 매일 밤 돌기 때문에 이 규칙이 조용히 사라지기
    가장 쉬운 자리입니다. 통화별로 각각 확인합니다.
    """
    krw_existing = {"season_key": SEASON, "bracket_key": "krw_1m_3m"}
    resolved = scorecard_publish.resolve_bracket_for_user_currency(
        KRW, 150_000_000, krw_existing, TODAY)
    assert resolved["bracket_key"] == "krw_1m_3m"
    assert resolved["source"] == "kept" and resolved["needs_write"] is False

    usd_existing = {"season_key": SEASON, "bracket_key": "usd_under_750"}
    resolved_usd = scorecard_publish.resolve_bracket_for_user_currency(
        USD, 90_000, usd_existing, TODAY)
    assert resolved_usd["bracket_key"] == "usd_under_750"
    assert resolved_usd["source"] == "kept"


def test_bracket_is_recomputed_when_the_season_rolls_over():
    existing = {"season_key": SEASON, "bracket_key": "krw_1m_3m"}
    resolved = scorecard_publish.resolve_bracket_for_user_currency(
        KRW, 150_000_000, existing, date(2027, 3, 1))
    assert resolved["season_key"] == "2027-03-01"
    assert resolved["bracket_key"] == "krw_100m_plus"
    assert resolved["needs_write"] is True


def test_unknown_currency_is_refused_rather_than_guessed():
    for bad in (None, "", "JPY", "krw", "won"):
        with pytest.raises(ScorecardPublishError):
            scorecard_publish.resolve_bracket_for_user_currency(bad, 1_000_000, None, TODAY)


# =============================================================================
# 3. 동의 확인 — 전부 아니면 전무
# =============================================================================
def test_partially_consented_user_is_refused_not_published_with_nulls():
    """
    도달할 수 없는 조합(항목 하나가 빠졌는데 최종확인이 서 있는 상태)을 만나면 **분기 대신
    거절**입니다. 빠진 항목을 null 로 채워 발행하지 않습니다.
    """
    for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS:
        with pytest.raises(ScorecardPublishError):
            scorecard_publish.assert_full_consent(_consent_row(**{flag: False}))


def test_unconfirmed_or_revoked_rows_are_refused():
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.assert_full_consent(_consent_row(final_confirmed=False))
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.assert_full_consent(
            _consent_row(revoked_at="2026-08-01T00:00:00+09:00"))


def test_consent_row_without_a_user_id_is_refused():
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.assert_full_consent(_consent_row(user_id=""))
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.assert_full_consent("동의함")


def test_fully_consented_row_passes():
    assert scorecard_publish.assert_full_consent(_consent_row()) is None


def test_consent_flags_are_exactly_these_six_in_this_order():
    """
    🔴 항목별 동의 목록을 **글자와 순서까지** 고정합니다. 이 목록이 바뀌면 DB 의
    `scorecard_consent_final_requires_all` CHECK · 화면의 `CONSENT_ITEM_SENTENCES` 도
    함께 바뀌어야 하고, 셋 중 하나만 바뀌면 "사용자가 본 문장"과 "실제로 저장·발행되는
    항목"이 갈라집니다 — 이 모듈에서 가장 나쁜 종류의 버그입니다.

    2026-08-23 에 여섯 번째 항목 `consent_holding_details`("종목별 상세지표")가 **끝에**
    붙었습니다. 앞의 다섯 개는 순서까지 그대로여야 합니다(기존 사용자의 동의 이력이 같은
    컬럼을 가리켜야 하므로).
    """
    assert scorecard_publish_db.CONSENT_ITEM_FLAGS == (
        "consent_rank", "consent_return", "consent_holdings",
        "consent_quantity", "consent_buy_amount", "consent_holding_details")


def test_the_duels_independent_bracket_consent_never_came_back():
    """
    🔴 결투의 독립 동의(`consent_real_principal_bracket` — "실제 매입총합을 체급 산정에
    사용")는 이 계층에 **없습니다(앞으로도 만들지 않습니다).** 공개되는 데이터 자체가 이미
    실제 자산이라, 매입원가합계는 이미 공개된 값들의 단순 합으로 재구성 가능합니다
    (스키마 §2-2).

    ⚠️ 2026-08-23 에 여섯 번째 항목이 생겼지만 그건 **다른 것**입니다 — 체급과 무관하고,
       따로 켜고 끄는 독립 동의도 아니라 앞의 다섯 개와 같은 "전부 아니면 전무" 묶음입니다.
       "여섯 번째가 생겼으니 결투 것도 되살리자"가 되지 않게 여기서 따로 못 박습니다.
    """
    assert duel_db.CONSENT_REAL_PRINCIPAL_FLAG not in scorecard_publish_db.CONSENT_ITEM_FLAGS

    code = _executable_source("scorecard_publish.py") + _executable_source(
        "scorecard_publish_db.py")
    assert duel_db.CONSENT_REAL_PRINCIPAL_FLAG not in code


# =============================================================================
# 4. 그룹 조립 — (통화 × 체급)
# =============================================================================
def _portfolio(krw_holdings=(), usd_holdings=(), prices=None):
    """한 사용자의 `build_portfolio()` 결과(통화별 dict)를 만듭니다."""
    rows = list(krw_holdings) + list(usd_holdings)
    return scorecard_db.build_portfolio(rows, _prices(prices or {}))


def test_build_publish_rows_groups_by_currency_and_bracket():
    consents = [_consent_row("u1"), _consent_row("u2")]
    portfolios = {
        "u1": _portfolio([_kr_holding("u1", 10, 100_000)],
                         prices={("KR", "005930"): 110_000}),
        "u2": _portfolio(usd_holdings=[_us_holding("u2", 10, 100)],
                         prices={("US", "AAPL"): 130}),
    }
    built = scorecard_publish.build_publish_rows(
        consents, portfolios, {"u1": "닉네임가", "u2": "닉네임나"},
        {("u1", KRW): "krw_under_1m", ("u2", USD): "usd_750_2250"})

    assert set(built["groups"]) == {(KRW, "krw_under_1m"), (USD, "usd_750_2250")}
    assert built["skipped"] == []

    krw = built["groups"][(KRW, "krw_under_1m")]
    assert [row["nickname"] for row in krw] == ["닉네임가"]
    assert krw[0]["twr_pct"] == pytest.approx(10.0)
    assert krw[0]["rank"] == 1

    usd = built["groups"][(USD, "usd_750_2250")]
    assert usd[0]["twr_pct"] == pytest.approx(30.0)


def test_one_user_with_both_currencies_lands_in_two_groups_with_the_same_nickname():
    """
    한 사용자가 원화·달러를 둘 다 갖고 있으면 **두 그룹에 각각** 들어갑니다(닉네임은 하나 —
    스키마 §2-1). 두 성적을 하나로 합치지 않습니다(§0-1 — 환율 시계열이 없습니다).
    """
    portfolios = {"u1": _portfolio(
        [_kr_holding("u1", 10, 100_000)], [_us_holding("u1", 10, 100)],
        prices={("KR", "005930"): 150_000, ("US", "AAPL"): 90})}
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {"u1": "닉네임가"},
        {("u1", KRW): "krw_under_1m", ("u1", USD): "usd_750_2250"})

    assert set(built["groups"]) == {(KRW, "krw_under_1m"), (USD, "usd_750_2250")}
    assert built["groups"][(KRW, "krw_under_1m")][0]["twr_pct"] == pytest.approx(50.0)
    assert built["groups"][(USD, "usd_750_2250")][0]["twr_pct"] == pytest.approx(-10.0)
    # 두 통화의 수익률이 어디서도 하나로 합쳐지지 않았는지(평균·합계가 없는지).
    values = [entry["twr_pct"] for entries in built["groups"].values() for entry in entries]
    assert sorted(values) == [pytest.approx(-10.0), pytest.approx(50.0)]


def test_user_with_only_one_currency_produces_no_rows_for_the_other():
    """
    한 통화만 가진 사용자가 **다른 통화에서 오류를 내지도, 빈 행을 만들지도** 않습니다.
    (`build_portfolio()` 는 보유가 없는 통화의 키를 아예 만들지 않습니다.)
    그리고 그건 "빠진 것"이 아니므로 사유 목록에도 올리지 않습니다.
    """
    portfolios = {"u1": _portfolio([_kr_holding("u1", 10, 100_000)],
                                   prices={("KR", "005930"): 100_000})}
    assert set(portfolios["u1"]) == {KRW}

    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {"u1": "닉네임가"}, {("u1", KRW): "krw_under_1m"})
    assert set(built["groups"]) == {(KRW, "krw_under_1m")}
    assert built["skipped"] == []


def test_users_without_a_computable_return_are_dropped_never_zeroed():
    """
    🔴 §0-1 — 가격을 못 구한 사용자를 0% 로 세우지 않고 **뺍니다.** 그리고 그 사실을 사유와
    함께 남깁니다(조용히 빠지는 사람을 만들지 않기).
    """
    portfolios = {"u1": _portfolio([_kr_holding("u1", 10, 100_000)], prices={})}
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {"u1": "닉네임가"}, {("u1", KRW): "krw_under_1m"})

    assert built["groups"] == {}
    assert built["skipped"] == [{"user_id": "u1",
                                 "reason": scorecard_publish.SKIP_NO_RETURN,
                                 "currency": KRW}]


def test_user_without_a_nickname_is_skipped_and_said_so():
    portfolios = {"u1": _portfolio([_kr_holding("u1", 10, 100_000)],
                                   prices={("KR", "005930"): 100_000})}
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {}, {})
    assert built["groups"] == {}
    assert [row["reason"] for row in built["skipped"]] == [scorecard_publish.SKIP_NO_NICKNAME]


def test_user_with_no_holdings_at_all_is_skipped_with_its_own_reason():
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], {"u1": {}}, {"u1": "닉네임가"}, {})
    assert built["groups"] == {}
    assert [row["reason"] for row in built["skipped"]] == [scorecard_publish.SKIP_NO_HOLDINGS]


def test_missing_bracket_falls_back_to_no_bracket_never_to_the_lowest_tier():
    """체급을 모르면 최하위 구간이 아니라 **구간 미적용**입니다(§0-1)."""
    portfolios = {"u1": _portfolio([_kr_holding("u1", 10, 100_000)],
                                   prices={("KR", "005930"): 100_000})}
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {"u1": "닉네임가"}, {})
    assert set(built["groups"]) == {(KRW, duel_rules.BRACKET_NONE_KEY)}


def test_ranking_is_descending_and_ties_share_a_rank():
    """순위는 `duel_rules.rank_participants()` 가 매깁니다 — 여기서 다시 매기지 않습니다."""
    consents = [_consent_row(f"u{i}") for i in range(3)]
    prices = {("KR", "005930"): 110_000}
    portfolios = {
        "u0": _portfolio([_kr_holding("u0", 10, 100_000)], prices=prices),   # +10%
        "u1": _portfolio([_kr_holding("u1", 10, 100_000)], prices=prices),   # +10% (동점)
        "u2": _portfolio([_kr_holding("u2", 10, 200_000)], prices=prices),   # -45%
    }
    built = scorecard_publish.build_publish_rows(
        consents, portfolios,
        {"u0": "닉가", "u1": "닉나", "u2": "닉다"},
        {(f"u{i}", KRW): "krw_under_1m" for i in range(3)})

    ranked = built["groups"][(KRW, "krw_under_1m")]
    assert [row["rank"] for row in ranked] == [1, 1, 3], "동점은 같은 순위, 다음 순위는 건너뜁니다"
    assert ranked[-1]["nickname"] == "닉다"


def test_rank_participants_is_fed_the_literal_twr_pct_key():
    """
    🔴 `duel_rules.rank_participants()` 는 참가자 dict 에서 **`"twr_pct"` 라는 키를 리터럴로**
    읽습니다(그 함수 본문에 박혀 있습니다). 이 모듈이 담는 값은 의미상 TWR 이 아니라 매입원가
    대비 수익률이지만, **그 함수에 넘기는 dict 에서는 키 이름을 맞춰야** 합니다.
    여기서 그 규약을 회귀로 고정합니다(밖으로 나가는 이름은 `return_pct` — 아래 §5 참고).
    """
    source = inspect.getsource(duel_rules.rank_participants)
    assert '"twr_pct"' in source or "'twr_pct'" in source

    portfolios = {"u1": _portfolio([_kr_holding("u1", 10, 100_000)],
                                   prices={("KR", "005930"): 110_000})}
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], portfolios, {"u1": "닉네임가"}, {("u1", KRW): "krw_under_1m"})
    entry = built["groups"][(KRW, "krw_under_1m")][0]
    assert "twr_pct" in entry, "rank_participants() 가 읽는 키 이름과 달라졌습니다"
    assert entry["twr_pct"] == pytest.approx(10.0)


# =============================================================================
# 5. 발행 payload — 🔴 식별자가 절대 실리지 않아야 합니다
# =============================================================================
def _ranked(nickname="닉네임가", return_pct=12.5, holdings=None, details=True):
    """
    `build_publish_rows()` 가 만드는 모양의 참가자 한 명.

    `details` 는 6번째 동의 항목(`consent_holding_details`)이 켜져 있는지입니다 — 기본은
    True(= 전부 아니면 전무 규칙 아래 실제로 발행되는 상태)이고, 게이팅을 확인하는 검사만
    False 나 "키 자체 없음"을 씁니다.
    """
    return [{"nickname": nickname, "twr_pct": return_pct, "rank": 1,
             "user_id": "user-1", "currency": KRW,
             "consent_holding_details": details,
             "holdings": holdings if holdings is not None else []}]


def test_leaderboard_payload_never_carries_identifiers():
    """
    🔴 발행표에는 `user_id` 를 절대 싣지 않습니다(스키마 §2-4). 작업용 필드를 whitelist 로
    잘라 내는지 **키 집합 자체**로 확인하고, 마지막 방어선(`FORBIDDEN_PUBLISH_FIELDS`)에도
    걸리지 않는지 함께 봅니다.
    """
    payload = scorecard_publish.leaderboard_payload((KRW, "krw_under_1m"), _ranked())
    assert len(payload) == 1
    assert set(payload[0]) == {"currency", "bracket_key", "rank", "nickname", "return_pct"}
    for key in duel_db.FORBIDDEN_PUBLISH_FIELDS:
        assert key not in payload[0]
    # 마지막 방어선 함수 자체도 통과해야 합니다(발행 직전에 다시 불립니다).
    duel_db._assert_no_identity_fields(
        payload[0], scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE)


def test_holdings_payload_never_carries_identifiers_including_the_holding_row_id():
    """
    🔴 `build_portfolio()` 의 행에는 원본 `holdings.id` 가 들어 있습니다. 그 값을 그대로
    실으면 발행표만 읽어도 원본 행을 특정할 수 있게 됩니다 — whitelist 방식이 그것을
    구조적으로 막는지 확인합니다.
    """
    summary = _summary([_kr_holding("u1", 3, 50_000)], {("KR", "005930"): 60_000})
    row = dict(summary["rows"][0])
    row["id"] = "holding-row-1"          # 원본 표의 기본키가 섞여 있는 상태를 흉내냅니다.

    payload = scorecard_publish.holdings_payload(
        (KRW, "krw_under_1m"), _ranked(holdings=[row]))
    assert set(payload[0]) == {"currency", "nickname", "ticker", "stock_name",
                               "quantity", "buy_amount",
                               "avg_price", "current_price", "profit", "profit_pct",
                               "weight_pct"}
    # 작업용으로만 들고 다니던 동의 플래그도 payload 로 새어 나가지 않아야 합니다.
    assert "consent_holding_details" not in payload[0]
    for key in duel_db.FORBIDDEN_PUBLISH_FIELDS:
        assert key not in payload[0]
    duel_db._assert_no_identity_fields(
        payload[0], scorecard_publish_db.PUBLIC_HOLDINGS_TABLE)


def test_holdings_payload_publishes_the_buy_amount_not_the_market_value():
    """
    `buy_amount` 는 `evaluate_holding()` 의 `cost`(= 수량 × 평균매입가) 그대로입니다.
    평가금액(`market_value`)을 실으면 그날 시세에 따라 값이 달라집니다.
    """
    summary = _summary([_kr_holding("u1", 3, 50_000)], {("KR", "005930"): 60_000})
    payload = scorecard_publish.holdings_payload(
        (KRW, "krw_under_1m"), _ranked(holdings=summary["rows"]))
    assert payload[0]["buy_amount"] == pytest.approx(150_000)     # 3 × 50,000
    assert payload[0]["quantity"] == pytest.approx(3)
    assert summary["rows"][0]["market_value"] == pytest.approx(180_000)  # 실리지 않는 값


def test_zero_percent_return_survives_into_the_payload():
    """0% 는 정상값입니다 — `or 0` 로 falsy 를 다루면 여기서 값이 사라집니다(§0-1)."""
    payload = scorecard_publish.leaderboard_payload(
        (KRW, "krw_under_1m"), _ranked(return_pct=0.0))
    assert payload[0]["return_pct"] == 0.0
    assert payload[0]["return_pct"] is not None


def test_user_with_no_holdings_rows_produces_no_holding_rows_not_zero_rows():
    """수량 0 짜리 행을 만들면 "0주 보유"라는 사실이 아닌 정보가 됩니다."""
    assert scorecard_publish.holdings_payload((KRW, "krw_under_1m"), _ranked()) == []


def test_broken_holding_numbers_stop_the_batch_instead_of_becoming_zero():
    for broken in ({"ticker": "005930", "quantity": None, "cost": 1},
                   {"ticker": "005930", "quantity": 1, "cost": "많이"},
                   {"ticker": "", "quantity": 1, "cost": 1}):
        with pytest.raises(ScorecardPublishError):
            scorecard_publish.holdings_payload(
                (KRW, "krw_under_1m"), _ranked(holdings=[broken]))


def test_write_functions_refuse_identifier_fields_as_a_last_line_of_defence():
    """
    payload 조립이 깨지더라도 **쓰기 직전에** 한 번 더 걸립니다
    (`duel_db._assert_no_identity_fields()` 재사용 — 목록을 두 벌 두지 않습니다).
    """
    client = FakeClient()
    for writer in (scorecard_publish_db.write_public_leaderboard,
                   scorecard_publish_db.write_public_holdings):
        with pytest.raises(DuelDbError):
            writer(client, TODAY, [{"currency": KRW, "nickname": "닉", "user_id": "u1"}])
    assert client.calls_for(op="insert") == [], "거절된 요청이 전송되면 안 됩니다"


# =============================================================================
# 5-b. 🔴 종목별 상세지표 5종 (2026-08-23 신설)
# =============================================================================
#  오너 확정: "'내 성적표'에 나오는 정보는 기본적으로 전부 공개." 그래서 발행 보유종목 행에
#  평균매입가·현재가·평가손익·수익률·비중이 함께 실립니다. 여기서 보는 것은 두 가지입니다:
#    ① **계산하지 않고 옮기기만 하는가** — `evaluate_holding()`/`build_portfolio()` 가 이미
#       만든 값과 **정확히 같은 숫자**여야 합니다. 여기서 다시 곱하거나 나누면 "내 성적표"
#       화면과 순위표가 언젠가 갈라집니다(§0-1/§0-3-10).
#    ② **동의 없이는 실리지 않는가** — 없으면 0 이 아니라 None(§0-1 "비공개 ≠ 0").
# =============================================================================
DETAIL_FIELDS = ("avg_price", "current_price", "profit", "profit_pct", "weight_pct")


def _detail_payload(details=True, prices=None, holdings=None):
    """상세지표 확인용 보유종목 payload 한 벌."""
    rows = holdings if holdings is not None else [_kr_holding("u1", 3, 50_000)]
    summary = _summary(rows, {("KR", "005930"): 60_000} if prices is None else prices)
    return scorecard_publish.holdings_payload(
        (KRW, "krw_under_1m"),
        _ranked(holdings=summary["rows"], details=details)), summary


def test_detail_metrics_are_copied_from_the_already_computed_row_not_recalculated():
    """
    ① 다섯 값이 `build_portfolio()` 의 행과 **글자 그대로 같은 숫자**인가.

    3주 × 50,000원(매입) → 현재가 60,000원이면 평가손익 30,000원 · 수익률 20% 입니다.
    이 검사가 보는 것은 그 숫자가 맞는지가 아니라(그건 `scorecard_db` 의 몫), **발행
    payload 가 그 값을 그대로 옮겼는지**입니다.
    """
    payload, summary = _detail_payload()
    row = summary["rows"][0]
    published = payload[0]

    assert published["avg_price"] == pytest.approx(row["avg_purchase_price"])
    assert published["current_price"] == pytest.approx(row["current_price"])
    assert published["profit"] == pytest.approx(row["profit"])
    assert published["profit_pct"] == pytest.approx(row["profit_pct"])
    assert published["weight_pct"] == pytest.approx(row["weight_pct"])

    # 값 자체도 한 번 봅니다(옮기기는 했는데 엉뚱한 필드를 옮겼을 수 있으므로).
    assert published["avg_price"] == pytest.approx(50_000)
    assert published["current_price"] == pytest.approx(60_000)
    assert published["profit"] == pytest.approx(30_000)
    assert published["profit_pct"] == pytest.approx(20.0)


def test_weight_pct_is_the_same_definition_the_scorecard_screen_uses():
    """
    🔴 비중은 "내 성적표" 화면이 쓰는 값(`build_portfolio()` 의 `weight_pct`) **그대로**
    입니다. 여기서 매입원가 기준으로 따로 계산하면, 같은 "비중"이라는 이름표를 달고 사용자
    본인의 `/scorecard` 화면과 순위표가 서로 다른 숫자를 보여주게 됩니다(§0-1/§0-3-10).

    두 종목의 매입원가는 같지만(각 300,000원) 현재가가 달라 평가금액이 갈리는 입력을 씁니다
    — 매입원가 기준이면 50/50, 평가금액 기준이면 60/40 이라 **어느 쪽을 실었는지가 실제로
    구별됩니다.**
    """
    holdings = [_kr_holding("u1", 3, 100_000, ticker="005930"),
                _kr_holding("u1", 3, 100_000, ticker="000660", stock_name="SK하이닉스")]
    payload, summary = _detail_payload(
        holdings=holdings,
        prices={("KR", "005930"): 120_000, ("KR", "000660"): 80_000})

    by_ticker = {row["ticker"]: row for row in payload}
    assert by_ticker["005930"]["weight_pct"] == pytest.approx(60.0)
    assert by_ticker["000660"]["weight_pct"] == pytest.approx(40.0)
    assert by_ticker["005930"]["weight_pct"] != pytest.approx(50.0), \
        "매입원가 기준으로 다시 계산한 값이 실렸습니다(화면과 갈라집니다)"

    # 화면이 쓰는 바로 그 필드와 같은 값인지 직접 대조합니다.
    screen = {row["ticker"]: row["weight_pct"] for row in summary["rows"]}
    for row in payload:
        assert row["weight_pct"] == pytest.approx(screen[row["ticker"]])


def test_detail_metrics_are_none_when_that_holding_has_no_price():
    """
    가격을 못 구한 종목은 넷이 **원래부터 None** 입니다(0 이 아닙니다 — §0-1).
    평균매입가는 시세와 무관하므로 그 경우에도 값이 있어야 합니다.
    """
    payload, _summary_unused = _detail_payload(prices={})     # 가격표가 비어 있음
    published = payload[0]
    assert published["avg_price"] == pytest.approx(50_000)
    for field in ("current_price", "profit", "profit_pct", "weight_pct"):
        assert published[field] is None, f"{field} 가 None 이 아닙니다"
    # 매입금액·수량은 시세와 무관하므로 여전히 실립니다.
    assert published["buy_amount"] == pytest.approx(150_000)


def test_no_detail_metrics_without_the_sixth_consent_and_they_are_none_not_zero():
    """
    ② 🔒 `consent_holding_details` 가 없으면 다섯 값이 **전부 None** 입니다.
    0 으로 채우면 "평가손익 0원 / 비중 0%"라는 사실이 아닌 정보를 남에게 발행하게 됩니다.
    키를 빼 버리는 것도 안 됩니다 — 컬럼이 있는데 값을 안 보내면 그날 그 종목만 값이 안
    바뀐 채 남을 수 있고, 화면은 "왜 이 사람만 칸이 다르지"가 됩니다.
    """
    payload, _ = _detail_payload(details=False)
    published = payload[0]
    for field in DETAIL_FIELDS:
        assert field in published, f"{field} 키 자체가 빠졌습니다(null 로 실어야 합니다)"
        assert published[field] is None, f"{field} 가 None 이 아닙니다"
        assert published[field] != 0, "비공개를 0 으로 그리지 않습니다(§0-1)"
    # 앞의 5개 항목에 걸린 값들은 그대로 실립니다(6번째만 빠진 것이므로).
    assert published["quantity"] == pytest.approx(3)
    assert published["buy_amount"] == pytest.approx(150_000)


def test_missing_consent_key_is_treated_as_not_consented():
    """
    🔒 기본값은 **공개가 아니라 비공개**입니다(§0-3-8). 호출부가 플래그를 아예 안 실어
    보냈다면(예: 새로 생긴 경로가 그 필드를 모른다면) 다섯 값은 None 이어야 합니다 —
    "없으면 켜진 것으로 본다"가 되는 순간 그게 정확히 §0-3-8 사고입니다.
    """
    summary = _summary([_kr_holding("u1", 3, 50_000)], {("KR", "005930"): 60_000})
    entry = _ranked(holdings=summary["rows"])
    del entry[0]["consent_holding_details"]                   # 플래그가 통째로 없는 상태

    payload = scorecard_publish.holdings_payload((KRW, "krw_under_1m"), entry)
    for field in DETAIL_FIELDS:
        assert payload[0][field] is None, f"{field} 가 동의 없이 실렸습니다"


def test_build_publish_rows_carries_the_sixth_consent_flag_from_the_consent_row():
    """
    게이팅 값의 출처는 **동의 행**입니다. `build_publish_rows()` 가 그 값을 참가자 dict 에
    실어 주지 않으면, `holdings_payload()` 는 (기본 비공개 규칙에 따라) 동의한 사람의
    상세지표까지 전부 비워 버립니다 — 조용히 값이 사라지는 쪽이라 검사로 고정합니다.
    """
    portfolio = _portfolio(krw_holdings=[_kr_holding("u1", 3, 50_000)],
                           prices={("KR", "005930"): 60_000})
    built = scorecard_publish.build_publish_rows(
        [_consent_row("u1")], {"u1": portfolio}, {"u1": "닉네임가"}, {})
    (entries,) = built["groups"].values()
    assert entries[0]["consent_holding_details"] is True

    payload = scorecard_publish.holdings_payload(
        (KRW, duel_rules.BRACKET_NONE_KEY), entries)
    assert payload[0]["avg_price"] == pytest.approx(50_000)


def test_leaderboard_payload_does_not_carry_the_consent_flag():
    """순위표 payload 는 whitelist 라 작업용 필드가 하나도 새지 않습니다."""
    payload = scorecard_publish.leaderboard_payload((KRW, "krw_under_1m"), _ranked())
    assert set(payload[0]) == {"currency", "bracket_key", "rank", "nickname", "return_pct"}


def test_write_public_holdings_accepts_the_new_detail_columns():
    """
    마지막 방어선(`_assert_no_identity_fields()`)이 새 필드 이름을 식별자로 오인하지 않고,
    발행 요청이 실제로 나가는지. (`profit` 같은 흔한 이름이 금지 목록과 겹치지 않는지도
    함께 봅니다.)
    """
    for field in DETAIL_FIELDS:
        assert field not in duel_db.FORBIDDEN_PUBLISH_FIELDS

    payload, _ = _detail_payload()
    client = FakeClient()
    written = scorecard_publish_db.write_public_holdings(client, "2026-08-23", payload)
    assert written == len(payload)
    sent = client.only_call(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "insert").payload
    assert sent[0]["profit_pct"] == pytest.approx(20.0)
    for key in duel_db.FORBIDDEN_PUBLISH_FIELDS:
        assert key not in sent[0]


def test_the_reader_selects_the_new_columns_by_name_never_star():
    """
    화면이 새 값을 읽으려면 조회 컬럼 목록에도 들어 있어야 합니다. 다만 `select("*")` 로
    바꿔 해결하면 안 됩니다 — 나중에 발행표에 컬럼이 하나 늘면 그걸 화면으로 그대로
    날라 주게 됩니다(§0-3-8).
    """
    columns = scorecard_publish_db.PUBLIC_HOLDINGS_COLUMNS
    assert "*" not in columns
    for field in DETAIL_FIELDS:
        assert field in columns.split(","), f"{field} 를 읽지 않습니다"


def test_publish_batch_end_to_end_carries_the_detail_metrics_into_the_written_rows():
    """
    조각이 아니라 **배치 전체**를 돌려서, 동의 → 조립 → 발행까지 다섯 값이 살아서 도착하는지
    확인합니다(중간 어느 단계에서 잘려도 여기서 잡힙니다).
    """
    client = _publish_client(duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION)
    _run(client)
    # 삽입은 청크로 나뉘어 여러 번 나갑니다 — 전부 모아서 봅니다.
    rows = [row for call in client.calls_for(
        scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "insert") for row in call.payload]
    assert rows, "보유종목이 한 행도 발행되지 않았습니다"
    for row in rows:
        for field in DETAIL_FIELDS:
            assert field in row
        assert row["avg_price"] is not None, \
            "동의한 사용자인데 상세지표가 비어 있습니다"


# =============================================================================
# 5-c. 스키마 추가분(2026-08-23) — 두 SQL 파일이 **같은 내용**인가
# =============================================================================
#  `sql/scorecard_public_schema.sql` 의 원본 CREATE 스크립트는 이미 운영 DB 에서 실행됐기
#  때문에 다시 만들지 않고, 끝에 ALTER 만 덧붙였습니다. 오너가 실제로 붙여넣어 실행할
#  파일은 저장소 루트의 사본(`MIGRATION_2026-08-23_holding_details.sql`)이라, 둘이 갈라지면
#  "기록된 것"과 "실행된 것"이 달라집니다 — 그건 나중에 추적이 불가능해지는 종류의
#  어긋남이라 검사로 고정합니다.
# =============================================================================
ADDENDUM_MARK = ("-- #############################################################################"
                 "\n-- ============ 2026-08-23 추가")


def _addendum(path):
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    index = text.find(ADDENDUM_MARK)
    assert index >= 0, f"{path} 에 2026-08-23 추가분이 없습니다"
    return text[index:]


def test_the_migration_file_and_the_schema_addendum_are_identical():
    assert _addendum("sql/scorecard_public_schema.sql") == \
        _addendum("MIGRATION_2026-08-23_holding_details.sql"), \
        "두 SQL 파일의 추가분이 어긋났습니다(한쪽만 고쳤습니다)"


def test_the_addendum_only_alters_and_never_drops_a_table():
    """
    🔴 원본 스크립트는 이미 실행됐습니다. 추가분에 `drop table` / `create table` 이 섞이면
    실제 데이터가 사라집니다. (제약조건 재작성을 위한 `drop constraint` 는 예외입니다.)
    """
    sql = _addendum("sql/scorecard_public_schema.sql").lower()
    assert "drop table" not in sql
    assert "create table" not in sql
    assert "truncate" not in sql
    for statement in ("alter table public.scorecard_public_consent",
                      "alter table public.scorecard_public_holdings"):
        assert statement in sql


def test_the_addendum_adds_every_column_the_code_expects():
    """코드가 읽고 쓰는 컬럼이 실제로 추가되는지 — 이름 하나만 틀려도 운영에서 터집니다."""
    sql = _addendum("sql/scorecard_public_schema.sql").lower()
    assert "add column if not exists consent_holding_details boolean not null default false" in sql
    for field in DETAIL_FIELDS:
        assert f"add column if not exists {field}" in sql, f"{field} 컬럼 추가가 없습니다"
        assert "numeric(20, 6)" in sql


def test_the_addendum_backfills_before_it_re_adds_the_check():
    """
    🔴 순서. 백필이 CHECK 재작성보다 뒤에 있으면 `add constraint` 가 기존 행(오너의 검증
    1건)에서 거절돼 마이그레이션이 통째로 멈춥니다.
    """
    sql = _addendum("sql/scorecard_public_schema.sql")
    backfill = sql.find("set consent_holding_details = true")
    add_check = sql.find("add constraint scorecard_consent_final_requires_all")
    assert backfill >= 0 and add_check >= 0
    assert backfill < add_check, "백필이 CHECK 재작성보다 먼저여야 합니다"


def test_the_new_check_requires_all_six_flags():
    """DB 의 '전부 아니면 전무'가 앱의 목록과 같은 6개를 요구하는가."""
    sql = _addendum("sql/scorecard_public_schema.sql")
    start = sql.find("add constraint scorecard_consent_final_requires_all")
    clause = sql[start:start + 400]
    for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS:
        assert flag in clause, f"CHECK 에 {flag} 가 빠졌습니다"



# =============================================================================
# 6. 최소 인원 게이팅
# =============================================================================
def _group(count, prefix="닉"):
    return [{"nickname": f"{prefix}{i:05d}", "twr_pct": float(i), "rank": count - i,
             "user_id": f"u{i}", "currency": KRW, "holdings": []}
            for i in range(count)]


MIN = duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION


def test_minimum_participant_threshold_is_one():
    """
    임계값은 `duel_rules` 의 **상수 하나**를 씁니다(§0-3-10 — 숫자를 두 번 적지 않기).

    2026-09-03 오너 확정으로 500 → 1. 동의자가 한 명이라도 있으면 그 그룹은 발행됩니다.
    (이전엔 여기서 `== 500` 과 "이 모듈에 500 이 다시 적혀 있지 않은가"를 확인했습니다.
    1 은 리터럴로 검사할 수 없는 숫자라, 대신 비교가 `group_meets_minimum()` 한 곳으로만
    가는지를 봅니다.)
    """
    assert MIN == 1
    code = _executable_source("scorecard_publish.py")
    assert "500" not in code, "옛 임계값 숫자가 이 모듈에 남아 있습니다"
    assert "group_meets_minimum(" in code, "발행 판정이 규칙 계층 함수를 거치지 않습니다"
    assert "MIN_PARTICIPANTS_FOR_PUBLICATION >" not in code
    assert "MIN_PARTICIPANTS_FOR_PUBLICATION <" not in code
    assert ">= duel_rules.MIN_PARTICIPANTS" not in code, "비교를 이 모듈에서 직접 하고 있습니다"


@pytest.mark.parametrize("count,publishable", [(0, False), (MIN - 1, False),
                                               (MIN, True), (MIN + 1, True), (500, True)])
def test_split_groups_by_threshold_boundary(count, publishable):
    groups = {(KRW, "krw_under_1m"): _group(count)}
    ok, blocked = scorecard_publish.split_groups_by_threshold(groups)
    assert bool(ok) is publishable
    assert bool(blocked) is (not publishable)


def test_all_possible_groups_pairs_each_currency_with_only_its_own_brackets():
    """
    🔴 KRW 와 USD 의 체급 키 집합은 **서로 다른 튜플**입니다. 곱집합을 만들면
    `("USD", "krw_100m_plus")` 같은 존재할 수 없는 그룹을 매일 밤 지우려 들게 됩니다.
    """
    groups = scorecard_publish.all_possible_groups()
    assert len(groups) == len(duel_rules.BRACKET_KEYS) + len(duel_rules.BRACKET_KEYS_USD) == 18
    assert len(set(groups)) == len(groups)
    for currency, bracket in groups:
        if currency == KRW:
            assert bracket in duel_rules.BRACKET_KEYS
            assert bracket not in [key for key in duel_rules.BRACKET_KEYS_USD
                                   if key != duel_rules.BRACKET_NONE_KEY]
        else:
            assert currency == USD
            assert bracket in duel_rules.BRACKET_KEYS_USD
            assert bracket not in [key for key in duel_rules.BRACKET_KEYS
                                   if key != duel_rules.BRACKET_NONE_KEY]


def test_group_that_fell_below_the_threshold_has_its_old_rows_deleted():
    """
    참가자가 있다가 최소 인원 아래로 줄어든 경우(문턱 1명이면 = 전원 철회) — **이미
    발행돼 있던 행도 제거합니다.**
    보유종목 쪽은 통화까지 함께 걸어 지웁니다(같은 닉네임의 다른 통화 행을 지우지 않으려고).
    """
    client = FakeClient(responses={
        (scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select"): [
            {"published_date": "2026-08-22", "nickname": "닉가"},
            {"published_date": "2026-08-22", "nickname": "닉나"},
        ],
    })
    scorecard_publish_db.delete_published_group(client, KRW, "krw_under_1m")

    deletes = client.calls_for(op="delete")
    leaderboard = [c for c in deletes
                   if c.table == scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE]
    holdings = [c for c in deletes
                if c.table == scorecard_publish_db.PUBLIC_HOLDINGS_TABLE]
    assert len(leaderboard) == 1
    assert leaderboard[0].filter_map == {"currency": KRW, "bracket_key": "krw_under_1m"}
    assert len(holdings) == 1
    assert holdings[0].filter_map["published_date"] == "2026-08-22"
    assert holdings[0].filter_map["currency"] == KRW, \
        "통화를 안 걸면 같은 닉네임의 달러 보유종목까지 지워집니다"


def test_group_that_was_never_published_sends_no_delete():
    client = FakeClient(responses={
        (scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select"): [],
    })
    assert scorecard_publish_db.delete_published_group(client, USD, "usd_under_750") == 0
    assert client.calls_for(op="delete") == []


# =============================================================================
# 7. 🔴 통화 격리 — 원화·달러가 어디서도 섞이지 않는가
# =============================================================================
def test_krw_only_and_usd_only_fixtures_never_contaminate_each_other():
    """
    KRW 만 있는 사용자와 USD 만 있는 사용자를 같은 배치에 넣고, **출력의 어느 곳에서도**
    통화가 섞이지 않는지 봅니다(체급 키 집합 · 그룹 키 · payload 의 currency 컬럼).
    """
    consents = [_consent_row("u-krw"), _consent_row("u-usd")]
    portfolios = {
        "u-krw": _portfolio([_kr_holding("u-krw", 10, 100_000)],
                            prices={("KR", "005930"): 120_000}),
        "u-usd": _portfolio(usd_holdings=[_us_holding("u-usd", 10, 100)],
                            prices={("US", "AAPL"): 80}),
    }
    brackets = {
        ("u-krw", KRW): scorecard_publish.resolve_bracket_for_user_currency(
            KRW, scorecard_publish.resolve_bracket_cost_basis(portfolios["u-krw"][KRW]),
            None, TODAY)["bracket_key"],
        ("u-usd", USD): scorecard_publish.resolve_bracket_for_user_currency(
            USD, scorecard_publish.resolve_bracket_cost_basis(portfolios["u-usd"][USD]),
            None, TODAY)["bracket_key"],
    }
    built = scorecard_publish.build_publish_rows(
        consents, portfolios, {"u-krw": "닉원", "u-usd": "닉달"}, brackets)

    for (currency, bracket_key), entries in built["groups"].items():
        expected_keys = (duel_rules.BRACKET_KEYS if currency == KRW
                         else duel_rules.BRACKET_KEYS_USD)
        assert bracket_key in expected_keys, f"{currency} 그룹에 다른 통화의 체급 키가 있습니다"
        for entry in entries:
            assert entry["currency"] == currency
            for holding in entry["holdings"]:
                assert holding["currency"] == currency

        leaderboard = scorecard_publish.leaderboard_payload((currency, bracket_key), entries)
        holdings = scorecard_publish.holdings_payload((currency, bracket_key), entries)
        assert {row["currency"] for row in leaderboard} == {currency}
        assert {row["currency"] for row in holdings} == {currency}

    # 원화 사용자는 원화 그룹에만, 달러 사용자는 달러 그룹에만 있어야 합니다.
    nicknames_by_currency = {currency: {entry["nickname"] for entry in entries}
                             for (currency, _b), entries in built["groups"].items()}
    assert nicknames_by_currency[KRW] == {"닉원"}
    assert nicknames_by_currency[USD] == {"닉달"}


def test_the_two_bracket_key_sets_share_nothing_but_the_no_bracket_marker():
    """
    '구간 미적용'만 공유합니다(통화와 무관한 개념이라 결투가 이미 상수를 공유합니다).
    그 밖의 키가 하나라도 겹치면 통화별 그룹이 서로를 덮어씁니다.
    """
    shared = set(duel_rules.BRACKET_KEYS) & set(duel_rules.BRACKET_KEYS_USD)
    assert shared == {duel_rules.BRACKET_NONE_KEY}


def test_a_krw_bracket_key_cannot_be_stored_as_a_usd_assignment():
    """
    통화가 뒤바뀐 체급 키를 시즌 고정 함수에 넘기면 **조용히 통과하지 않고 멈춥니다.**
    (`resolve_bracket_for_season_usd()` 는 `BRACKET_KEYS_USD` 로만 검증합니다.)
    """
    with pytest.raises(DuelRuleError):
        duel_rules.resolve_bracket_for_season_usd(
            {"season_key": SEASON, "bracket_key": "krw_100m_plus"}, "usd_under_750", TODAY)
    with pytest.raises(DuelRuleError):
        duel_rules.resolve_bracket_for_season(
            {"season_key": SEASON, "bracket_key": "usd_under_750"}, "krw_under_1m", TODAY)


def test_no_single_function_reads_both_currency_summaries_at_once():
    """
    한 함수 안에서 두 통화의 **요약값**이 만나는 자리가 없어야 합니다 — 두 통화를 더한 숫자를
    만들려면 결국 한 함수 안에서 두 요약이 만나야 하기 때문입니다(§0-1: 환율 시계열이 없는
    앱에서 두 통화를 합치면 그 숫자는 지어낸 값입니다).

    ⚠️ `CURRENCY_KRW`/`CURRENCY_USD` **상수 자체**는 표(`CURRENCY_BRACKET_RULES`)와
       `PUBLISHED_CURRENCIES` 를 세우는 모듈 최상위에서 나란히 등장합니다. 그건 "축이 둘"이라는
       선언이지 합산이 아니므로, 검사는 **함수 본문**만 봅니다.
    """
    tree, _source = _module_ast("scorecard_publish.py")
    offenders = {}
    for node in _functions(tree).values():
        used = _names_used(node)
        if "CURRENCY_KRW" in used and "CURRENCY_USD" in used:
            offenders[node.name] = sorted(used & {"CURRENCY_KRW", "CURRENCY_USD"})
        if "assign_bracket" in used and "assign_bracket_usd" in used:
            offenders[node.name] = sorted(used & {"assign_bracket", "assign_bracket_usd"})
    assert not offenders, (
        f"한 함수가 두 통화를 동시에 다루고 있습니다: {offenders}."
        " 통화를 가르는 자리는 CURRENCY_BRACKET_RULES 표 하나뿐이어야 합니다."
    )


# =============================================================================
# 8. 하루치 발행 배치 — 전량 재작성 · 순서 · dry-run · §0-3-2
# =============================================================================
def _in_filtered(rows, column):
    """
    `in` 필터를 실제로 적용하는 가짜 응답. 진짜 PostgREST 와 같게 동작해야, 청크로 나눠
    조회하는 코드가 "매 청크마다 전체를 받는" 비현실적인 상황에서 통과해 버리는 일이
    없습니다(그 상황에서만 안 보이는 버그가 실제로 있습니다 — 합계 중복 계산).
    """
    def resolve(query):
        wanted = None
        for op, name, value in query.filters:
            if op == "in" and name == column:
                wanted = set(value)
        if wanted is None:
            return list(rows)
        return [row for row in rows if str(row.get(column)) in wanted]
    return resolve


#: 배치 시나리오에서 쓰는 현재가. 아래 `_publish_client()` 의 매입가와 짝지어 KRW 는
#: +10%, USD 는 +30% 가 나오게 골랐습니다(수익률이 0 이 아니어야 "0 으로 채우기"와
#: 구분이 됩니다).
PRICES = {("KR", "005930"): 770_000, ("US", "AAPL"): 130}


def _publish_client(user_count, *, revoked=None, nicknames=None, holdings=None,
                    existing_assignments=None, leaderboard_probe=None, currency=KRW):
    """
    발행 배치용 가짜 클라이언트. `scorecard_public_consent` 표를 두 가지 목적(발행 대상 /
    철회 목록)으로 조회하므로, 필터를 보고 갈라 주는 callable 로 응답을 지정합니다.
    """
    consents = [_consent_row(f"user-{i}") for i in range(user_count)]
    revoked_rows = list(revoked or [])

    def consent_select(query):
        if ("not.is", "revoked_at", "null") in query.filters:
            return revoked_rows
        return consents

    if holdings is None:
        make = _kr_holding if currency == KRW else _us_holding
        # 전원이 **같은 체급**에 모이게 합니다(500명이 한 그룹에 모여야 최소 인원 경계를
        # 시험할 수 있습니다). KRW: 10주 × 70만원 = 700만원 → krw_5m_10m,
        # USD: 10주 × $100 = $1,000 → usd_750_2250.
        holdings = [make(f"user-{i}", 10, 700_000 if currency == KRW else 100)
                    for i in range(user_count)]

    def leaderboard_select(query):
        if "bracket_key" in query.filter_map:
            return []                     # 미달 그룹 청소 점검 — 과거 발행 없음
        return list(leaderboard_probe if leaderboard_probe is not None else [])

    return FakeClient(responses={
        (scorecard_publish_db.CONSENT_TABLE, "select"): consent_select,
        # ⚠️ 청크마다 **전체 목록**을 돌려주면 안 됩니다(실제 PostgREST 는 in 필터를
        #    적용하므로). 그러면 사용자가 200명을 넘는 순간 같은 사람의 보유종목이 여러 번
        #    세어져 매입원가합계가 부풀고, 체급이 조용히 달라집니다.
        (scorecard_db.HOLDINGS_TABLE, "select"): _in_filtered(holdings, "user_id"),
        (scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "select"):
            list(existing_assignments or []),
        (scorecard_publish_db.NICKNAMES_TABLE, "select"): _in_filtered(
            list(nicknames if nicknames is not None else [
                {"user_id": f"user-{i}", "nickname": f"닉네임{i:05d}"}
                for i in range(user_count)]), "user_id"),
        (scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select"): leaderboard_select,
    })


def _run(client, **kwargs):
    """가격 파일 없이 배치를 돌립니다(가격 조회 함수를 주입)."""
    kwargs.setdefault("price_lookup", _prices(PRICES))
    return scorecard_publish.run_publish_batch(client, TODAY, **kwargs)


def test_publish_batch_full_rewrite_deletes_todays_rows_before_inserting():
    """
    **그날 발행분을 통째로 갈아끼웁니다.** 부분 갱신은 "어제는 있었는데 오늘은 자격을 잃은
    행"을 남깁니다. 통째로 지우고 다시 쓰면 남는 경우가 구조적으로 없습니다.
    """
    client = _publish_client(user_count=500)
    summary = _run(client)
    assert summary["leaderboard_rows"] == 500

    date_deletes = [index for index, call in enumerate(client.calls)
                    if call.op == "delete"
                    and call.filter_map.get("published_date") == TODAY.isoformat()]
    inserts = [index for index, call in enumerate(client.calls)
               if call.op == "insert" and call.table in (
                   scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE,
                   scorecard_publish_db.PUBLIC_HOLDINGS_TABLE)]
    assert len(date_deletes) == 2, "두 발행표 각각 그날 행을 통째로 지워야 합니다"
    assert max(date_deletes) < min(inserts), "삭제가 삽입보다 먼저여야 합니다"


def test_h3_missing_price_snapshots_aborts_before_touching_history():
    """
    🔴 2026-08-29 재감사 H-3 회귀 고정 — 가격 스냅샷(data/*.json)이 전혀 없어서 거래일조차
    확인 못 하는 상태(예: 수집기가 완전히 멈췄거나 파일 형식이 바뀜)는 "참가자가 부족하다"
    는 정상 상태가 아닙니다. `price_lookup` 을 생략(=`report_db.build_price_lookup()` 을
    실제로 부르게)하고 `resolve_session_dates()` 가 거래일을 하나도 못 찾게 만들어, 옛
    발행 이력을 지우기 **전에** 멈추는지 확인합니다.
    """
    client = _publish_client(user_count=500)
    with mock.patch.object(scorecard_publish, "resolve_session_dates", return_value=([], [])):
        with pytest.raises(ScorecardPublishError, match="거래일도 확인하지 못했습니다"):
            scorecard_publish.run_publish_batch(client, TODAY)   # price_lookup 생략(§H-3)
    assert client.calls_for(scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "delete") == [], \
        "원인을 확인하기 전에는 과거 발행 이력을 지우면 안 됩니다"
    assert client.calls_for(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "delete") == [], \
        "원인을 확인하기 전에는 과거 발행 이력을 지우면 안 됩니다"


def test_h3_everyone_skipped_for_no_return_aborts_instead_of_wiping_history():
    """
    🔴 H-3 회귀 고정 — 동의자가 있는데(500명) **전원**이 가격을 못 구해(`SKIP_NO_RETURN`)
    발행 대상이 0명이 되는 경우는 "정상적인 인원 미달"이 아니라 데이터 문제입니다(예:
    한쪽 시장 스냅샷만 손상). 이 경우도 과거 발행 이력을 지우지 않고 멈춰야 합니다.

    (인원 미달 자체는 정상 동작입니다 — `test_publish_batch_publishes_nothing_below_the_
    threshold` 가 그 경로를 이미 지킵니다. 여기는 "인원은 충분한데 전원 계산 실패"만
    다룹니다.)
    """
    client = _publish_client(user_count=500)
    with pytest.raises(ScorecardPublishError, match="수익률을 계산하지 못해"):
        _run(client, price_lookup=_prices({}))    # 가격표가 비어 전원 SKIP_NO_RETURN
    assert client.calls_for(scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "delete") == [], \
        "전원 계산 실패는 과거 이력을 지울 이유가 아닙니다"
    assert client.calls_for(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "delete") == [], \
        "전원 계산 실패는 과거 이력을 지울 이유가 아닙니다"


def test_h3_dry_run_does_not_trip_the_safety_brake():
    """🔴 H-3 — `dry_run=True` 는 애초에 아무것도 쓰지 않으므로, 안전장치가 굳이
    예외를 던져 "무엇이 발행될 뻔했는지" 미리 보는 것까지 막으면 안 됩니다."""
    client = _publish_client(user_count=500)
    summary = _run(client, dry_run=True, price_lookup=_prices({}))
    assert summary["leaderboard_rows"] == 0


def test_m2_holdings_are_written_before_the_leaderboard():
    """
    🔴 2026-08-29 재감사 M-2 회귀 고정 — 예전엔 순위표(leaderboard)를 먼저 쓰고 보유종목
    (holdings)을 나중에 썼습니다. 그 순서면 두 삽입 사이에 배치가 죽었을 때 "순위표에는
    있는데 보유종목 상세를 열면 아무것도 없다"는 어중간한 상태가 화면에 노출됩니다.
    반대 순서(holdings 먼저)면 같은 사고가 나도 "순위표에 아직 없음"(=화면에 아예 안 보임)
    으로만 보여 덜 이상합니다.
    """
    client = _publish_client(user_count=500)
    _run(client)
    holdings_inserts = [i for i, call in enumerate(client.calls)
                        if call.op == "insert" and call.table == scorecard_publish_db.PUBLIC_HOLDINGS_TABLE]
    leaderboard_inserts = [i for i, call in enumerate(client.calls)
                           if call.op == "insert" and call.table == scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE]
    assert holdings_inserts and leaderboard_inserts
    assert max(holdings_inserts) < min(leaderboard_inserts), \
        "holdings 삽입이 leaderboard 삽입보다 먼저 끝나야 합니다(M-2)"


def test_running_twice_on_the_same_day_does_not_duplicate_rows():
    for _run_index in range(2):
        client = _publish_client(user_count=500)
        summary = _run(client)
        assert summary["leaderboard_rows"] == 500
        rows = [row for call in client.calls_for(
                    scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "insert")
                for row in call.rows]
        keys = [(row["published_date"], row["currency"], row["bracket_key"], row["nickname"])
                for row in rows]
        assert len(keys) == len(set(keys)), "같은 참가자가 한 날짜에 두 번 실렸습니다"


def test_publish_batch_publishes_nothing_below_the_threshold():
    """
    최소 인원 미만이면 아무것도 쓰지 않습니다. 2026-09-03 부터 문턱이 1명이라 "미만"은
    곧 동의자 0명이고, 참가자가 없는 그룹은 `build_publish_rows()` 가 애초에 만들지 않으므로
    `blocked_groups` 도 비어 있습니다(예전 499명 시험에서는 `["KRW/krw_5m_10m"]` 였습니다).
    """
    client = _publish_client(user_count=MIN - 1)
    summary = _run(client)
    assert summary["leaderboard_rows"] == 0
    assert summary["holdings_rows"] == 0
    assert summary["published_groups"] == []
    assert summary["blocked_groups"] == []
    assert client.calls_for(scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "insert") == []
    assert client.calls_for(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "insert") == []


def test_publish_batch_publishes_at_exactly_the_threshold():
    """동의자가 딱 최소 인원(=1명)이면 그 한 명만으로 그룹이 발행됩니다(2026-09-03 오너 확정)."""
    client = _publish_client(user_count=MIN)
    summary = _run(client)
    assert summary["published_groups"] == ["KRW/krw_5m_10m"]
    assert summary["blocked_groups"] == []
    assert summary["leaderboard_rows"] == MIN
    assert summary["holdings_rows"] == MIN
    rows = [row for call in client.calls_for(
                scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "insert")
            for row in call.rows]
    assert [row["rank"] for row in rows] == [1]


def test_publish_batch_still_publishes_a_large_group():
    """문턱을 낮춘 뒤에도 옛 경계값(500명) 그룹이 그대로 발행되는지 — 회귀 방지."""
    client = _publish_client(user_count=500)
    summary = _run(client)
    assert summary["published_groups"] == ["KRW/krw_5m_10m"]
    assert summary["leaderboard_rows"] == 500
    assert summary["holdings_rows"] == 500


def test_publish_batch_publishes_a_usd_only_population_into_usd_groups_only():
    """🔴 통화 격리 — 달러만 있는 모집단이 원화 그룹을 만들지 않습니다."""
    client = _publish_client(user_count=500, currency=USD)
    summary = _run(client)
    assert summary["published_groups"] == ["USD/usd_750_2250"]
    rows = [row for call in client.calls_for(
                scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "insert")
            for row in call.rows]
    assert {row["currency"] for row in rows} == {USD}
    assert {row["bracket_key"] for row in rows} <= set(duel_rules.BRACKET_KEYS_USD)


def test_dry_run_writes_absolutely_nothing():
    """오너가 "무엇이 발행될 뻔했는지"를 먼저 눈으로 볼 수 있어야 합니다(§0-3-6 의 정신)."""
    client = _publish_client(user_count=500)
    summary = _run(client, dry_run=True)
    assert summary["leaderboard_rows"] == 500, "계산은 그대로 해야 미리보기가 의미가 있습니다"
    assert summary["dry_run"] is True
    assert client.calls_for(op="insert") == []
    assert client.calls_for(op="delete") == []
    assert client.calls_for(op="update") == []
    assert client.calls_for(op="upsert") == []


def test_publish_batch_purges_revoked_users_before_anything_else():
    """
    🔴 철회 청소가 **가장 먼저** 돕니다. 순서를 뒤집으면 오늘 발행이 중간에 실패했을 때
    "철회한 사람의 과거 기록이 그대로 남은 채 하루가 더 가는" 상태가 됩니다.
    """
    client = _publish_client(
        user_count=0,
        revoked=[{"user_id": "user-x", "revoked_at": "2026-08-01T00:00:00+09:00"}],
        nicknames=[{"user_id": "user-x", "nickname": "철회닉"}])
    summary = _run(client)
    assert summary["revoked_users"] == 1

    nickname_deletes = [index for index, call in enumerate(client.calls)
                        if call.op == "delete" and "nickname" in call.filter_map]
    other_ops = [index for index, call in enumerate(client.calls)
                 if call.op in ("insert", "upsert")]
    assert len(nickname_deletes) == 2, "두 발행표에서 모든 날짜의 행을 지워야 합니다"
    for call in client.calls_for(op="delete"):
        if "nickname" in call.filter_map:
            assert "published_date" not in call.filter_map, \
                "철회 삭제는 날짜를 가리지 않습니다(과거 발행분까지 전부 지웁니다)"
    assert not other_ops or max(nickname_deletes) < min(other_ops)


def test_publish_batch_keeps_the_season_bracket_and_does_not_rewrite_it():
    existing = [{"user_id": f"user-{i}", "currency": KRW, "season_key": SEASON,
                 "bracket_key": "krw_100m_plus"} for i in range(500)]
    client = _publish_client(user_count=500, existing_assignments=existing)
    summary = _run(client)

    assert summary["published_groups"] == ["KRW/krw_100m_plus"], \
        "오늘 계산하면 500만~1천만이지만 시즌 중이라 기존 체급이 이겨야 합니다"
    assert client.calls_for(
        scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert") == []
    assert summary["bracket_status_counts"] == {"kept": 500}


def test_publish_batch_reads_the_season_assignments_before_deciding():
    """배치가 체급 배정 기록을 **읽지 않고** 넘어가면 시즌 고정이 조용히 사라집니다."""
    client = _publish_client(user_count=3)
    _run(client)
    call = client.only_call(scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "select")
    assert call.filter_map == {"season_key": SEASON}


def test_bracket_assignments_are_inserted_never_updated():
    """
    "시즌 중 고정"이 앱의 조심성이 아니라 **구조**임을 고정합니다. DB 도 배치에게
    update/delete 권한을 주지 않으므로(스키마 §3-8), 여기에 upsert 가 생기면 그날 배치가
    실패합니다.
    """
    client = FakeClient()
    scorecard_publish_db.insert_bracket_assignments(client, [
        {"user_id": "u1", "currency": KRW, "season_key": SEASON,
         "bracket_key": "krw_1m_3m"}])
    call = client.only_call(scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE)
    assert call.op == "insert"
    assert call.rows[0] == {"user_id": "u1", "currency": KRW, "season_key": SEASON,
                            "bracket_key": "krw_1m_3m"}

    tree, source = _module_ast("scorecard_publish_db.py")
    node = _functions(tree)["insert_bracket_assignments"]
    body = ast.get_source_segment(source, node)
    assert ".upsert(" not in body and ".update(" not in body


def test_bracket_assignment_duplicate_is_absorbed_not_raised():
    """같은 시즌 배정이 이미 있으면(배치 두 번 실행·경합) **기존 값이 이깁니다.**"""
    client = FakeClient(responses={
        (scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert"):
            Exception("duplicate key value violates unique constraint"),
    })
    assert scorecard_publish_db.insert_bracket_assignments(client, [
        {"user_id": "u1", "currency": KRW, "season_key": SEASON,
         "bracket_key": "krw_1m_3m"}]) == 0


def test_m3_chunk_level_duplicate_retries_row_by_row_keeping_new_rows():
    """
    🔴 2026-08-29 재감사 M-3 회귀 고정 — 청크(최대 200명)에 중복 키 1건이 섞여 있으면,
    Postgres 의 insert 는 한 statement 단위로 원자적이라 **청크 전체가 롤백**됩니다.
    예전엔 그 실패를 그냥 `continue` 로 넘겨서, 청크 안에 있던 최대 199건의 **진짜 새
    배정까지 함께 사라졌습니다.** 지금은 청크가 실패하면 행 단위로 재시도해 진짜
    중복(`u-dup`)만 건너뛰고 나머지는 살립니다.
    """
    duplicate_row = {"user_id": "u-dup", "currency": KRW, "season_key": SEASON,
                      "bracket_key": "krw_1m_3m"}
    new_rows = [{"user_id": f"u-{i}", "currency": KRW, "season_key": SEASON,
                 "bracket_key": "krw_1m_3m"} for i in range(2)]
    payload = [duplicate_row] + new_rows

    def resolve(query):
        if len(query.rows) > 1:
            # 청크 전체 insert — 안에 중복이 섞여 있으니 statement 전체가 실패합니다.
            raise Exception("duplicate key value violates unique constraint")
        row = query.rows[0]
        if row["user_id"] == "u-dup":
            raise Exception("duplicate key value violates unique constraint")
        return [dict(row)]

    client = FakeClient(responses={
        (scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert"): resolve,
    })
    inserted = scorecard_publish_db.insert_bracket_assignments(client, payload)
    assert inserted == 2, "청크 안의 진짜 새 배정 2건은 살아남아야 합니다(M-3)"
    single_row_calls = [c for c in client.calls_for(
        scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert") if len(c.rows) == 1]
    assert len(single_row_calls) == 3, "청크 실패 후 3건 모두 행 단위로 재시도해야 합니다"


def test_unrelated_insert_errors_are_not_swallowed():
    client = FakeClient(responses={
        (scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert"):
            Exception("connection reset"),
    })
    with pytest.raises(DuelDbError):
        scorecard_publish_db.insert_bracket_assignments(client, [
            {"user_id": "u1", "currency": KRW, "season_key": SEASON,
             "bracket_key": "krw_1m_3m"}])


def test_holdings_are_never_read_when_nobody_consented():
    """동의자가 0명이면 실제 자산 표에 **질의 자체를 보내지 않습니다.**"""
    client = FakeClient()
    assert scorecard_publish_db.fetch_holdings_for_users(client, []) == []
    assert client.calls == [], "동의자가 없는데 holdings 를 조회했습니다"


def test_holdings_fetch_requires_an_explicit_user_list():
    """
    "안 주면 전부"라는 편의 기본값이 **없어야** 합니다. 그 한 줄이 곧 §0-3-8 위반입니다.
    (닉네임 일괄 조회도 같은 규약입니다.)
    """
    for function in (scorecard_publish_db.fetch_holdings_for_users,
                     scorecard_publish_db.fetch_nicknames_for_users):
        parameters = inspect.signature(function).parameters
        assert list(parameters) == ["service_client", list(parameters)[1]]
        last = parameters[list(parameters)[1]]
        assert last.default is inspect.Parameter.empty, \
            f"{function.__name__} 에 '안 주면 전부' 기본값이 생겼습니다"


def test_holdings_fetch_selects_named_columns_never_star():
    client = _publish_client(user_count=3)
    _run(client)
    call = client.only_call(scorecard_db.HOLDINGS_TABLE, "select")
    columns = call.options["columns"]
    assert columns != "*"
    assert set(columns.split(",")) == {
        "user_id", "market", "ticker", "stock_name", "quantity",
        "avg_purchase_price", "currency"}


def test_publish_modules_never_call_report_dbs_fetch_all_holdings():
    """
    🔴 `report_db.fetch_all_holdings()` 는 **전체 사용자**의 보유종목을 읽습니다(리포트
    배치는 전원이 대상이라 그게 맞습니다). 여기서 그걸 부르면 동의하지 않은 사람의 자산이
    이 배치의 메모리에 올라옵니다.

    ⚠️ `utils/scorecard_publish.py` 는 `report_db.build_price_lookup()` **하나만** 좁게
       가져옵니다("내 성적표" 화면과 같은 현재가 조회를 쓰기 위해서 — §0-3-10). 모듈 이름을
       통째로 묶지 않으므로 `fetch_all_holdings` 는 이 파일에서 이름조차 닿지 않습니다.
    """
    for name in ("scorecard_publish.py", "scorecard_publish_db.py"):
        code = _executable_source(name)
        assert "fetch_all_holdings" not in code, f"{name} 이 전체 보유종목 조회를 부릅니다"


def test_publish_batch_with_no_participants_writes_nothing_but_still_cleans():
    client = _publish_client(user_count=0)
    summary = _run(client)
    assert summary["consent_count"] == 0
    assert summary["leaderboard_rows"] == 0
    assert client.calls_for(op="insert") == []
    # 그래도 그날 발행분 삭제는 돕니다 — 어제까지 있던 그룹이 오늘 0명이 됐을 수 있습니다.
    assert len(client.calls_for(op="delete")) == 2


def test_publish_batch_checks_every_possible_group_for_stale_rows():
    """
    참가자가 **전부 사라진** 그룹의 과거 행이 영원히 남지 않도록, 발행되지 않는 18개 그룹을
    전부 훑습니다(발행표에 행이 하나라도 있을 때만).
    """
    client = _publish_client(user_count=0, leaderboard_probe=[{"id": 1}])
    _run(client)
    group_probes = [call for call in client.calls_for(
        scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select")
        if "bracket_key" in call.filter_map]
    probed = {(call.filter_map["currency"], call.filter_map["bracket_key"])
              for call in group_probes}
    assert probed == set(scorecard_publish.all_possible_groups())


def test_publish_batch_skips_the_group_sweep_when_nothing_was_ever_published():
    client = _publish_client(user_count=0)
    _run(client)
    group_probes = [call for call in client.calls_for(
        scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "select")
        if "bracket_key" in call.filter_map]
    assert group_probes == [], "발행표가 비어 있으면 18번 훑을 이유가 없습니다"


@pytest.mark.parametrize("user_count", [3, 50, 900])
def test_publish_batch_query_count_does_not_scale_with_users(user_count):
    """
    🔴 §0-3-2 회귀 테스트. 사용자가 3명이든 900명이든 **고정 왕복 수는 그대로**이고,
    늘어나는 것은 "요청 하나가 지나치게 커지지 않게 자르는" 청크 수뿐입니다 — 사용자마다
    부르는 것이 아닙니다. 사용자가 10명일 때는 사용자별 루프도 잘 돌아갑니다. 그래서
    위험합니다.
    """
    client = _publish_client(user_count=user_count)
    _run(client)

    chunks = -(-user_count // duel_db.CHUNK_SIZE)
    published = duel_rules.group_meets_minimum(user_count)

    # 사용자 수와 무관하게 정확히 1번씩만 나가는 조회들.
    assert len(client.calls_for(
        scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "select")) == 1
    assert len(client.calls_for(scorecard_publish_db.CONSENT_TABLE, "select")) == 2

    # 청크에 비례하는 것들(사용자 수가 아니라 **청크 수**).
    assert len(client.calls_for(scorecard_publish_db.NICKNAMES_TABLE, "select")) == chunks
    assert len(client.calls_for(scorecard_db.HOLDINGS_TABLE, "select")) == chunks
    assert len(client.calls_for(
        scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE, "insert")) == chunks

    inserts = (client.calls_for(scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE, "insert")
               + client.calls_for(scorecard_publish_db.PUBLIC_HOLDINGS_TABLE, "insert"))
    assert len(inserts) == (2 * chunks if published else 0)

    # 그날 발행분 통째 삭제 2개 + (발행표가 비어 있으므로) 미달 그룹 청소 0개.
    assert len(client.calls_for(op="delete")) == 2

    # 총합이 "상수 + 청크 × 상수" 꼴인지 — 사용자 수에 비례하는 항이 없어야 합니다.
    fixed = 4                       # 동의 2 · 배정 조회 1 · 발행표 존재확인 1
    per_chunk = 3 + (2 if published else 0)
    assert len(client.calls) == fixed + chunks * per_chunk + 2


def test_publish_batch_requires_an_explicit_date():
    """
    이 모듈이 "오늘"을 스스로 정하지 않습니다. 배치가 자정 근처에 돌거나 하루 늦게 돌면
    날짜가 조용히 틀어지고, 그건 나중에 복원할 수 없는 오염입니다(§0-1).
    """
    parameters = inspect.signature(scorecard_publish.run_publish_batch).parameters
    assert parameters["published_date"].default is inspect.Parameter.empty
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.run_publish_batch(_publish_client(0), None,
                                            price_lookup=_prices({}))
    with pytest.raises(ScorecardPublishError):
        scorecard_publish.run_publish_batch(None, TODAY, price_lookup=_prices({}))


# =============================================================================
# 9. 요약 출력 — 빠진 것과 막힌 것이 드러나되, 식별자는 한 글자도 안 나오게
# =============================================================================
def test_summary_lines_show_published_groups_with_their_counts():
    """문턱이 1명이라 실제 배치에서 3명짜리 그룹은 발행됩니다 — 요약에도 그렇게 찍혀야 합니다."""
    client = _publish_client(user_count=3)
    lines = scorecard_publish.format_summary_lines(_run(client))
    text = "\n".join(lines)
    assert "3명" in text
    assert "✅ 발행" in text
    assert "미발행" not in text


def test_summary_lines_show_blocked_groups_and_skipped_users():
    """
    미발행 분기(`⛔ 미발행(최소 N명)`)는 문턱이 1명인 지금 실제 배치로는 만들 수 없지만
    (참가자 0명 그룹은 애초에 안 생기므로), 문턱을 다시 올리면 곧바로 쓰이는 출력이라
    요약 dict 를 직접 만들어 형식을 고정합니다 — 숫자는 상수에서 가져와야 합니다.
    """
    summary = {"published_date": TODAY.isoformat(), "season_key": "2026",
               "consent_count": 2, "group_counts": {"KRW/krw_5m_10m": 2},
               "published_groups": [], "blocked_groups": ["KRW/krw_5m_10m"],
               "skipped": [{"user_id": "u1", "reason": scorecard_publish.SKIP_NO_HOLDINGS}]}
    text = "\n".join(scorecard_publish.format_summary_lines(summary))
    assert "2명" in text
    assert "미발행" in text and f"최소 {MIN}명" in text


def test_summary_lines_never_print_a_user_id():
    """
    🔴 이 함수의 출력은 GitHub Actions 로그에 그대로 남습니다. 진단을 위해 `skipped` 는
    메모리 안에서 `user_id` 를 들고 있지만, **찍히는 것은 사유별 개수뿐**이어야 합니다.
    """
    client = _publish_client(user_count=3, nicknames=[])
    summary = _run(client)
    assert summary["skipped"], "이 시나리오는 빠진 사용자가 있어야 의미가 있습니다"
    assert all("user_id" in row for row in summary["skipped"])

    text = "\n".join(scorecard_publish.format_summary_lines(summary))
    for row in summary["skipped"]:
        assert row["user_id"] not in text, "요약 줄에 사용자 식별자가 찍혔습니다"
    assert scorecard_publish.SKIP_NO_NICKNAME in text, "사유는 드러나야 합니다(§0-1)"


# =============================================================================
# 10. 동의 저장 / 철회 / 닉네임 — 사용자 경로
# =============================================================================
def test_save_consent_requires_all_five_before_the_final_confirmation():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        scorecard_publish_db.save_consent(
            client, "u1", consent_rank=True, final_confirmed=True)
    assert client.calls_for(op="upsert") == []


def test_save_consent_stamps_the_confirmation_time_and_uses_user_id_as_the_key():
    client = FakeClient()
    flags = {flag: True for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS}
    scorecard_publish_db.save_consent(client, "u1", final_confirmed=True, **flags)

    call = client.only_call(scorecard_publish_db.CONSENT_TABLE, "upsert")
    assert call.options["on_conflict"] == "user_id"
    assert call.rows[0]["user_id"] == "u1"
    assert call.rows[0]["final_confirmed_at"], "최종확인 시각이 비어 있습니다"
    assert "account_id" not in call.rows[0] and "window_type" not in call.rows[0]


def test_save_consent_refuses_unknown_flags_including_the_retired_sixth_one():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        scorecard_publish_db.save_consent(
            client, "u1", **{duel_db.CONSENT_REAL_PRINCIPAL_FLAG: True})
    with pytest.raises(DuelDbError):
        scorecard_publish_db.save_consent(client, "u1", consent_rannk=True)


def test_revoke_consent_records_the_time_and_turns_everything_off():
    client = FakeClient(responses={
        (scorecard_publish_db.CONSENT_TABLE, "select"): [_consent_row("u1")],
    })
    now = datetime(2026, 8, 23, 21, 0, tzinfo=KST)
    scorecard_publish_db.revoke_consent(client, "u1", now_kst=now)

    call = client.only_call(scorecard_publish_db.CONSENT_TABLE, "update")
    payload = call.rows[0]
    assert payload["revoked_at"].startswith("2026-08-23")
    assert payload["final_confirmed"] is False and payload["final_confirmed_at"] is None
    for flag in scorecard_publish_db.CONSENT_ITEM_FLAGS:
        assert payload[flag] is False
    assert call.filter_map == {"user_id": "u1"}


def test_revoking_twice_does_not_extend_the_block():
    """두 번 눌렀다는 이유로 3개월 차단이 연장되면 안 됩니다."""
    client = FakeClient(responses={
        (scorecard_publish_db.CONSENT_TABLE, "select"): [
            _consent_row("u1", revoked_at="2026-08-01T00:00:00+09:00",
                         final_confirmed=False)],
    })
    row = scorecard_publish_db.revoke_consent(client, "u1")
    assert row["revoked_at"] == "2026-08-01T00:00:00+09:00"
    assert client.calls_for(op="update") == []


@pytest.mark.parametrize("now,blocked", [
    (datetime(2026, 10, 31, 23, 59, tzinfo=KST), True),
    (datetime(2026, 11, 1, 0, 0, tzinfo=KST), False),      # 정확히 3개월 → 풀립니다
])
def test_save_consent_is_blocked_for_three_months_after_revoking(now, blocked):
    """
    판정 규칙은 `duel_rules.resolve_reconsent_block()` 하나가 단일 출처입니다(§0-3-10).
    여기서는 저장 경로가 **실제로 그 판정을 거치는지**를 봅니다.
    """
    assert duel_rules.resolve_reconsent_block(
        "2026-08-01T00:00:00+09:00", now)["blocked"] is blocked

    client = FakeClient(responses={
        (scorecard_publish_db.CONSENT_TABLE, "select"): [
            _consent_row("u1", revoked_at="2026-08-01T00:00:00+09:00",
                         final_confirmed=False)],
    })
    # `_assert_reconsent_allowed()` 는 실제 시각을 봅니다. 위 순수 판정으로 규칙을 고정하고,
    # 여기서는 "차단이 저장 경로에 실제로 걸려 있는가"만 확인합니다(오늘은 차단 기간 안).
    with pytest.raises(DuelDbError) as caught:
        scorecard_publish_db.save_consent(client, "u1", consent_rank=True)
    assert "3개월" in str(caught.value) and "2026-11-01" in str(caught.value)
    assert client.calls_for(op="upsert") == []


def test_ensure_nickname_takes_no_window_type_and_never_derives_from_identity():
    """
    🔴 결투와 달리 창유형 인자가 없습니다(사용자당 포트폴리오 1개 → 닉네임 1개).
    그리고 닉네임 후보는 **인자가 하나도 없는** 난수 함수가 만듭니다 — 정체성에서 유도할
    문법 자체가 없어야 역조회가 불가능합니다(§0-3-9).
    """
    assert list(inspect.signature(scorecard_publish_db.ensure_nickname).parameters) == \
        ["client", "user_id"]
    assert list(inspect.signature(scorecard_publish_db.fetch_my_nickname).parameters) == \
        ["client", "user_id"]
    assert list(inspect.signature(duel_rules.generate_nickname).parameters) == []

    client = FakeClient()
    row = scorecard_publish_db.ensure_nickname(client, "9f3a2c11-b8d4-4e7a-9c02-5ad61f0e7b3d")
    assert row["user_id"] == "9f3a2c11-b8d4-4e7a-9c02-5ad61f0e7b3d"
    for chunk in "9f3a2c11-b8d4-4e7a-9c02-5ad61f0e7b3d".split("-"):
        assert chunk not in row["nickname"]
    insert = client.only_call(scorecard_publish_db.NICKNAMES_TABLE, "insert")
    assert set(insert.rows[0]) == {"user_id", "nickname"}


def test_ensure_nickname_yields_to_the_other_tab_on_a_race():
    """두 탭에서 동시에 눌러도 이름이 둘 생기지 않습니다 — 이미 생긴 이름을 씁니다."""
    from test_duel_db import sequence
    client = FakeClient(responses={
        (scorecard_publish_db.NICKNAMES_TABLE, "select"): sequence(
            [], [{"user_id": "u1", "nickname": "먼저생긴이름"}]),
        (scorecard_publish_db.NICKNAMES_TABLE, "insert"):
            Exception("duplicate key value violates unique constraint"),
    })
    assert scorecard_publish_db.ensure_nickname(client, "u1")["nickname"] == "먼저생긴이름"


def test_fetch_my_nickname_never_creates_one():
    """화면을 그리는 행위는 아무것도 만들지 않아야 합니다."""
    client = FakeClient()
    assert scorecard_publish_db.fetch_my_nickname(client, "u1") is None
    assert client.calls_for(op="insert") == []


# =============================================================================
# 11. 발행표 읽기 — select 밖으로 나가지 않고, 컬럼을 하나하나 적습니다
# =============================================================================
def test_public_reads_never_use_select_star_and_never_expose_the_row_id():
    client = FakeClient()
    scorecard_publish_db.fetch_public_leaderboard(client, currency=KRW,
                                                  bracket_key="krw_under_1m")
    scorecard_publish_db.fetch_public_holdings_for_nickname(client, "닉네임가")
    for call in client.calls_for(op="select"):
        columns = call.options["columns"]
        assert columns != "*"
        assert "id" not in columns.split(","), "발행 순서를 노출하는 id 를 싣지 마세요"
        assert "user_id" not in columns


def test_public_reads_filter_by_currency_so_the_two_tracks_never_mix():
    """
    🔴 한 사람이 원화·달러를 둘 다 공개하면 **닉네임이 같습니다.** 통화를 안 걸면 원화
    순위표에서 그 사람의 달러 종목까지 함께 보이고, 사용자는 그 둘을 머릿속에서 더하게
    됩니다(이 앱에는 환율 시계열이 없습니다 — §0-1).
    """
    client = FakeClient()
    scorecard_publish_db.fetch_public_leaderboard(
        client, currency=USD, bracket_key="usd_under_750", published_date=TODAY)
    scorecard_publish_db.fetch_public_holdings_for_nickname(
        client, "닉네임가", published_date=TODAY, currency=USD)
    for call in client.calls_for(op="select"):
        assert call.filter_map.get("currency") == USD
        assert call.filter_map.get("published_date") == TODAY.isoformat()


def test_public_reads_refuse_an_unknown_currency():
    client = FakeClient()
    with pytest.raises(DuelDbError):
        scorecard_publish_db.fetch_public_leaderboard(
            client, currency="JPY", bracket_key="krw_under_1m")
    with pytest.raises(DuelDbError):
        scorecard_publish_db.fetch_public_leaderboard_latest_date(
            client, currency="", bracket_key="krw_under_1m")
    assert client.calls == []


# =============================================================================
# 12. 🔴 구조 검사 (AST) — "조심했는가"가 아니라 "할 수 있는가"
# =============================================================================
def _module_ast(name):
    source = (REPO_ROOT / "utils" / name).read_text(encoding="utf-8")
    return ast.parse(source), source


def _executable_source(name):
    """
    주석과 **문자열 리터럴(docstring 포함)** 을 걷어낸 소스. "실제로 실행되는 코드"만 봅니다
    (`tests/test_duel_publish.py::_executable_source()` 와 같은 방식).
    """
    tree, _source = _module_ast(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.unparse(tree)


def _functions(tree):
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _names_used(node):
    """함수 본문에서 쓰인 이름(변수·함수·속성)의 집합. 중첩 함수 안까지 봅니다."""
    used = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.add(child.attr)
    return used


NEW_MODULES = ("scorecard_publish.py", "scorecard_publish_db.py")


def test_any_module_mirroring_duel_db_execute_also_imports_execute_all():
    """
    🏗️ 2026-08-29 재감사(스코어카드 모듈) S-3 회귀 고정.

    `utils/scorecard_publish_db.py`(그리고 `utils/duel_db_usd.py`)가 `utils/duel_db.py`
    에서 비공개 함수를 여러 개 손으로 골라 import 하는 방식 자체는 §0-3-10 상 옳은
    판단입니다(그 이유가 각 파일 머리말에 잘 적혀 있습니다). 문제는 **그 목록이 사람 손
    으로 유지된다**는 것이고, 실제로 이 목록에서 `_execute_all` 하나가 빠져 H-2(배치
    조회에 페이지네이션이 없어 "일부만 읽고 전부 읽은 척"하는 사고)가 생겼습니다.

    이 검사가 하는 일은 단 하나입니다 — `utils/*.py` 아무 파일이나 `utils.duel_db` 에서
    `_execute` 를 import 하면, **같은 import 문에서 `_execute_all` 도 함께** import 해야
    합니다. 다음에 또 같은 모양의 미러 모듈이 생겨도(예: 결투 3번째 통화 트랙 등) 이 검사
    하나가 같은 누락을 자동으로 막습니다. (`_execute` 만 쓰고 배치 조회가 전혀 없는 모듈
    이라면 애초에 `_execute_all` 을 import 할 이유도 없어야 정상이라, 이 규칙은 "혹시
    모를 배치 조회"에 대비한 **최소 방어선**입니다 — 실제로 배치 조회가 필요 없는 아주
    작은 미러 모듈에는 다소 과할 수 있다는 뜻이고, 그런 경우가 생기면 그때 이 검사를
    좁히면 됩니다.)
    """
    utils_dir = REPO_ROOT / "utils"
    checked_modules = []
    for path in sorted(utils_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module == "utils.duel_db"):
                continue
            imported_names = {alias.name for alias in node.names}
            if "_execute" not in imported_names:
                continue
            checked_modules.append(path.name)
            assert "_execute_all" in imported_names, (
                f"{path.name} 이 utils.duel_db 에서 _execute 를 import 하면서 "
                "_execute_all 은 import 하지 않습니다 — 이 모듈에 배치(다건) 조회가 있다면 "
                "H-2 처럼 페이지네이션 없이 '일부만 읽고 전부 읽은 척' 할 위험이 있습니다."
            )
    # 검사 자체가 대상을 하나도 못 찾으면 (예: 두 미러 모듈이 모두 리팩터로 사라지면)
    # 이 테스트가 조용히 "항상 통과"하는 죽은 검사가 됩니다 — 그것도 §0-1 위반이라 확인합니다.
    assert set(checked_modules) >= {"scorecard_publish_db.py", "duel_db_usd.py"}, (
        f"예상한 미러 모듈을 찾지 못했습니다(실제로 찾은 목록: {checked_modules}) — "
        "검사 대상이 사라졌다면 이 검사 자체를 다시 봐야 합니다."
    )


def test_h2_batch_reads_all_use_range():
    """
    🔴 2026-08-29 재감사 H-2 회귀 고정 — 예전엔 이 다섯 함수 중 어느 것도 `.range()` 를
    보내지 않아서, 서버 응답 상한에 걸리면 "일부만 읽고 전부 읽은 척" 했습니다
    (`tests/test_duel_db.py::test_batch_reads_all_use_range()` 와 같은 검사를 이 모듈의
    다섯 함수에 적용합니다).
    """
    checks = [
        (lambda c: scorecard_publish_db.fetch_publishable_consents(c),
         scorecard_publish_db.CONSENT_TABLE),
        (lambda c: scorecard_publish_db.fetch_revoked_consent_users(c),
         scorecard_publish_db.CONSENT_TABLE),
        (lambda c: scorecard_publish_db.fetch_bracket_assignments(c, "2026-H2"),
         scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE),
        (lambda c: scorecard_publish_db.fetch_holdings_for_users(c, ["user-1"]),
         scorecard_db.HOLDINGS_TABLE),
        (lambda c: scorecard_publish_db.fetch_published_group_index(c, "KRW", "krw_under_1m"),
         scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE),
    ]
    for call, table in checks:
        client = FakeClient()
        call(client)
        query = client.only_call(table, "select")
        assert "range" in query.options, f"{table} 조회에 .range() 가 없습니다(H-2 재발)"


def test_h2_fetch_holdings_for_users_reads_every_page_per_chunk():
    """
    🔴 H-2 — 한 청크(최대 200명)의 총 보유종목 행 수가 서버 상한(`_execute_all` 기본
    페이지 크기 1000행)을 넘어도 전부 읽습니다. 첫 페이지를 **꽉 채워** 돌려주고, 두
    번째(짧은) 페이지까지 실제로 이어서 읽는지 확인합니다 — 페이지가 짧으면 멈추므로
    첫 페이지가 짧으면 애초에 두 번째 호출 자체가 없어 이 검사가 무의미해집니다.
    """
    full_page = [{"user_id": "user-1", "ticker": f"T{i:04d}"} for i in range(1000)]
    pages = [full_page, [{"user_id": "user-1", "ticker": "000660"}]]

    def _holdings_select(query):
        return pages.pop(0) if pages else []

    client = FakeClient(responses={(scorecard_db.HOLDINGS_TABLE, "select"): _holdings_select})
    rows = scorecard_publish_db.fetch_holdings_for_users(client, ["user-1"])
    assert len(rows) == 1001, "짧은 페이지가 나올 때까지 계속 읽어 1001행 전부를 모아야 합니다"
    calls = client.calls_for(scorecard_db.HOLDINGS_TABLE, "select")
    assert len(calls) == 2, "페이지 2개(1000행 가득 참 + 1행 짧음)를 읽었어야 합니다"


def test_no_account_or_window_concept_leaked_into_the_user_currency_model():
    """
    🔴 이 계층에는 계좌도 창유형도 없습니다. 결투 코드를 옮기다 남은 축이 있으면 그 축은
    DB 에 없는 컬럼이라 발행이 통째로 거절되거나, 더 나쁘게는 조용히 무시됩니다.
    """
    for name in NEW_MODULES:
        code = _executable_source(name)
        for forbidden in ("account_id", "window_type", "ACCOUNT_WINDOW_TYPES",
                          "duel_public_", "duel_nicknames", "duel_bracket_"):
            assert forbidden not in code, f"{name} 에 {forbidden} 이(가) 남아 있습니다"


def test_publish_module_touches_supabase_only_through_the_db_layer():
    """
    오케스트레이션 파일은 Supabase 를 **직접** 만지지 않습니다(`.table(` 이 없어야 합니다).
    그래야 "어느 표에 무엇을 쓰는가"를 `scorecard_publish_db.py` 한 파일만 읽고 검토할 수
    있습니다(§0-3-8).
    """
    code = _executable_source("scorecard_publish.py")
    assert ".table(" not in code
    assert ".insert(" not in code and ".delete(" not in code and ".upsert(" not in code


def test_publish_module_never_creates_its_own_supabase_client():
    """클라이언트는 **인자로 받습니다.** 여기서 만들면 배치 키의 출처가 늘어납니다."""
    code = _executable_source("scorecard_publish.py")
    assert "create_service_client" not in code
    assert "SUPABASE" not in code


def test_only_the_batch_section_writes_the_publish_tables():
    """
    발행표에 **쓰는**(insert/delete) 코드가 B 절 함수에만 있는지 확인합니다. A 절(사용자
    세션)에 하나라도 생기면 앱 서버가 발행표를 고칠 수 있게 됩니다(§0-3-8).
    """
    tree, source = _module_ast("scorecard_publish_db.py")
    batch_writers = {
        "delete_published_rows_for_date", "delete_published_rows_for_nicknames",
        "delete_published_group", "write_public_leaderboard", "write_public_holdings",
    }
    offenders = []
    for name, node in _functions(tree).items():
        body = ast.get_source_segment(source, node) or ""
        writes = ".insert(" in body or ".delete(" in body or ".update(" in body \
            or ".upsert(" in body
        touches_publish_table = ("PUBLIC_LEADERBOARD_TABLE" in body
                                 or "PUBLIC_HOLDINGS_TABLE" in body)
        if writes and touches_publish_table and name not in batch_writers:
            offenders.append(name)
    assert not offenders, f"발행표에 쓰는 함수가 B 절 밖에 있습니다: {offenders}"


def test_the_db_layer_never_writes_the_source_holdings_table():
    """이 계층은 `holdings` 를 **읽기만** 합니다. 쓰는 코드가 한 줄도 없어야 합니다."""
    tree, source = _module_ast("scorecard_publish_db.py")
    for name, node in _functions(tree).items():
        body = ast.get_source_segment(source, node) or ""
        if "HOLDINGS_TABLE" in body and "scorecard_db" in body:
            assert ".insert(" not in body and ".update(" not in body \
                and ".delete(" not in body and ".upsert(" not in body, \
                f"{name}() 이 holdings 표에 쓰려고 합니다"


def test_every_new_public_function_has_a_docstring():
    """
    §0-3-8 검토는 "이 파일만 읽으면 된다"가 되어야 합니다 — 공개 함수에 설명이 없으면
    그게 안 됩니다.
    """
    for name in NEW_MODULES:
        tree, _source = _module_ast(name)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                assert ast.get_docstring(node), f"{name}::{node.name}() 에 설명이 없습니다"


def test_schema_file_declares_the_new_tables_and_drops_the_old_layer():
    """
    파이썬이 바라보는 표 이름과 SQL 파일이 어긋나지 않는지. (SQL 은 오너가 손으로 실행하므로,
    코드와 스키마가 갈라졌을 때 이 테스트가 먼저 알려 줍니다.)
    """
    sql = (REPO_ROOT / "sql" / "scorecard_public_schema.sql").read_text(encoding="utf-8")
    for table in (scorecard_publish_db.NICKNAMES_TABLE,
                  scorecard_publish_db.CONSENT_TABLE,
                  scorecard_publish_db.BRACKET_ASSIGNMENTS_TABLE,
                  scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE,
                  scorecard_publish_db.PUBLIC_HOLDINGS_TABLE):
        assert f"create table if not exists public.{table}" in sql

    # 은퇴하는 결투 공개 계층은 이 파일이 지웁니다(가상계좌 원본 표는 건드리지 않습니다).
    for dropped in ("duel_public_consent", "duel_public_leaderboard", "duel_public_holdings",
                    "duel_bracket_assignments", "duel_nicknames"):
        assert f"drop table if exists public.{dropped} cascade;" in sql
    for kept in ("duel_accounts", "duel_orders", "duel_positions", "duel_cash_ledger"):
        assert f"drop table if exists public.{kept} " not in sql, \
            f"가상계좌 원본 표({kept})를 지우면 안 됩니다"

    # 발행표에 `user_id` 컬럼이 없다는 것이 이 설계의 전부입니다(스키마 §2-4).
    leaderboard = sql.split(f"create table if not exists public."
                            f"{scorecard_publish_db.PUBLIC_LEADERBOARD_TABLE}")[1].split(");")[0]
    assert "user_id" not in leaderboard


def test_the_runner_script_and_workflow_exist_and_point_at_this_module():
    """실행 껍데기(스크립트·워크플로우)가 실제로 이 모듈을 부르는지."""
    runner = (REPO_ROOT / "run_scorecard_publish_batch.py").read_text(encoding="utf-8")
    assert "scorecard_publish.run_publish_batch(" in runner
    assert "--dry-run" in runner and "--published-date" in runner

    workflow = (REPO_ROOT / ".github" / "workflows"
                / "scorecard_publish_daily.yml").read_text(encoding="utf-8")
    assert "python run_scorecard_publish_batch.py" in workflow
    assert "concurrency:" in workflow and "scorecard-publish-batch" in workflow
    assert "secrets.SUPABASE_SERVICE_ROLE_KEY" in workflow
    assert "workflow_dispatch:" in workflow
