# tests/test_duel_publish_usd.py
"""
⚔️ "결투다!" USD 트랙 — **공개 순위표 발행 배치**(`utils/duel_publish_usd.py`) 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · `supabase` 패키지 설치 여부와 무관)

`tests/test_duel_publish.py`(원화, 120개)와 짝을 이룹니다. 발행 순서·NULL 규율·순위 계산·
동의 게이팅 같은 **통화 무관 로직은 원화 모듈에서 그대로 재사용**하므로, 그 로직 자체는
이미 원화 스위트가 exhaustively 검증했습니다 — 여기서 처음부터 다시 반복하지 않습니다.
이 파일이 확인하는 것은 USD 트랙만의 위험 지점입니다:

    ① §0 **재사용-정체성 검사** — 재사용해야 할 함수가 정말 원화 모듈과 **같은 객체**인지,
       USD 전용으로 새로 정의한 것이 원화 함수와 **다른 객체**인지(재정의·오재사용 회귀 방지).
    ② 🔴 `summarize_real_principal_usd()` 가 원화 버전과 **정확히 반대**로 동작하는지 —
       USD 만 있으면 OK / 비-USD 가 섞이면 FX_MIXED / 없으면 NO_HOLDINGS. 두 함수에 **같은
       입력**을 넣어 답이 뒤집히는 것을 직접 대조하는 회귀 테스트를 포함합니다
       (`resolve_fill_trading_day` vs `_usd` 대조 테스트(§5-16)와 같은 성격 — "다름을 고정").
    ③ `resolve_bracket_for_account_usd()` 가 `BRACKET_TIERS_USD` 경계로 정확히 갈리고,
       시즌 고정 규칙이 USD 에서도 유지되는지(+ 원화 시즌 함수를 쓰면 왜 죽는지).
    ④ `all_possible_groups_usd()` 가 3 × len(BRACKET_KEYS_USD) 조합을 정확히 만드는지
       (개수 하드코딩 금지 — 실제 상수 길이로 계산).
    ⑤ 🔴 **§0-3-8 다섯 원칙이 USD 버전에서도 전부 지켜지는지** — `utils/duel_publish.py`
       머리말이 선언한 ①~⑤ 를 하나씩 USD 배치로 증명합니다.
    ⑥ §0-3-2 — 계좌가 3개든 900개든 왕복 수가 그대로인지(원화와 같은 회귀 방식).
    ⑦ **트랙 격리** — KRW 표(`_usd` 없는 표)에 질의가 하나도 가지 않는지.
    ⑧ dry_run · None 클라이언트 에러 처리 · docstring 완비(이 트랙의 관례).
    ⑨ 새 실행 스크립트·워크플로우가 실제로 USD 함수를 부르고, cron 이 선행 체결 배치의
       타임아웃 상한 뒤에 오는지.

실행: pytest tests/test_duel_publish_usd.py -v
"""

import ast
import inspect
import io
import sys
import tokenize
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
# 가짜 Supabase 클라이언트는 `tests/test_duel_db.py` 가 갖고 있습니다(§0-3-10 — 흉내도 단일
# 출처로). `tests/test_duel_batch_usd.py`·`tests/test_duel_publish.py` 와 같은 관례입니다.
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient  # noqa: E402
from utils import (  # noqa: E402
    duel_batch, duel_batch_usd, duel_db, duel_db_usd,
    duel_publish, duel_publish_usd, duel_rules, scorecard_db,
)
from utils.duel_db import DuelDbError  # noqa: E402
from utils.duel_publish import DuelPublishError  # noqa: E402
from utils.duel_rules import DuelRuleError  # noqa: E402

TODAY = date(2026, 8, 21)
SEASON = "2026-03-01"


# =============================================================================
# 0. 재사용 정체성 — 원화 모듈과 같은 객체인가 / 새 함수는 다른 객체인가
# =============================================================================
@pytest.mark.parametrize("name", [
    "DuelPublishError",
    "PRINCIPAL_OK", "PRINCIPAL_NO_HOLDINGS", "PRINCIPAL_FX_MIXED",
    "SKIP_NO_NICKNAME", "SKIP_NO_ACCOUNT", "SKIP_NO_TWR", "SKIP_INACTIVE",
    "_to_date", "_as_float",
    "assert_full_consent", "consented_user_ids_for_real_principal",
    "build_publish_rows", "leaderboard_payload", "holdings_payload",
    "split_groups_by_threshold", "format_summary_lines",
])
def test_shared_publish_helpers_are_the_same_object_as_the_krw_module(name):
    """
    통화를 몰라도 되는 판단·조립 로직은 원화 모듈에서 **그대로** 가져다 씁니다.
    재정의하면 두 벌이 되고, 그러면 "원화 순위표는 고쳤는데 달러 순위표는 옛 규칙"이
    되는 날이 옵니다(§0-3-10).
    """
    assert getattr(duel_publish_usd, name) is getattr(duel_publish, name), \
        f"{name} 이 duel_publish 와 같은 객체가 아닙니다(재정의됐을 가능성)"


def test_declared_reuse_list_matches_what_is_actually_reused():
    """
    머리말이 선언한 "재사용 목록"이 **실제 코드와 일치**하는지. 문서와 코드가 갈라지면
    다음 사람이 머리말을 믿고 잘못된 판단을 합니다(이 트랙의 관례 — `duel_db_usd.py` 의
    같은 검사와 같은 성격).
    """
    declared = duel_publish_usd.REUSED_FROM_DUEL_PUBLISH
    expected = tuple(getattr(duel_publish, name) for name in (
        "DuelPublishError", "PRINCIPAL_OK", "PRINCIPAL_NO_HOLDINGS", "PRINCIPAL_FX_MIXED",
        "SKIP_NO_NICKNAME", "SKIP_NO_ACCOUNT", "SKIP_NO_TWR", "SKIP_INACTIVE",
        "_to_date", "_as_float", "assert_full_consent",
        "consented_user_ids_for_real_principal", "build_publish_rows",
        "leaderboard_payload", "holdings_payload", "split_groups_by_threshold",
        "format_summary_lines"))
    assert declared == expected
    # 그리고 USD 전용 함수는 이 목록에 **없어야** 합니다(재사용이 아니므로).
    assert duel_publish_usd.summarize_real_principal_usd not in declared
    assert duel_publish_usd.run_publish_batch_usd not in declared


def test_shared_exception_type_lets_callers_catch_one_kind():
    """
    두 트랙이 **같은 예외 타입**을 씁니다(`duel_db_usd` 가 `DuelDbError` 를 공유하는 것과
    같은 이유) — 호출 스크립트가 한 종류만 잡으면 됩니다.
    """
    assert duel_publish_usd.DuelPublishError is DuelPublishError


def test_twr_assembly_is_the_shared_batch_function():
    """
    TWR 조립은 야간 배치가 이미 원화 모듈에서 재사용 중인 **같은 객체**입니다(§5-15).
    발행 배치가 TWR 을 두 번째로 구현하면 화면 수익률과 순위표 수익률이 갈라집니다.
    """
    assert duel_batch_usd.compute_twr_by_account is duel_batch.compute_twr_by_account


@pytest.mark.parametrize("usd_name,krw_name", [
    ("summarize_real_principal_usd", "summarize_real_principal"),
    ("summarize_real_principal_by_user_usd", "summarize_real_principal_by_user"),
    ("resolve_bracket_for_account_usd", "resolve_bracket_for_account"),
    ("all_possible_groups_usd", "all_possible_groups"),
    ("run_publish_batch_usd", "run_publish_batch"),
])
def test_usd_specific_functions_are_deliberately_not_the_krw_functions(usd_name, krw_name):
    """
    🔴 반대 방향의 회귀 고정 — 이 다섯은 **통화별 전제가 본문에 박혀 있어** 새로 정의한
    것들입니다. 누가 "같은 로직이니 재사용하자"며 원화 함수를 다시 붙이면 여기서 잡힙니다.
    """
    usd_function = getattr(duel_publish_usd, usd_name)
    krw_function = getattr(duel_publish, krw_name)
    assert usd_function is not krw_function
    assert usd_function.__code__ is not krw_function.__code__


def test_season_boundary_is_shared_but_bracket_validation_is_not():
    """
    🔴 이번 라운드에 **코드를 직접 읽어 확인한 사실**을 회귀로 고정합니다.

    5-11-8 은 "시즌은 KRW 트랙과 동일 공유"라고 확정했고, 실제로 시즌 경계를 정하는
    `season_key_for_date()` 는 두 트랙이 **같은 함수**를 씁니다. 그런데 시즌 고정 규칙을
    강제하는 `resolve_bracket_for_season()` 본문에는 유효한 체급 목록으로 `BRACKET_KEYS`
    (원화 9개)가 하드코딩돼 있어서, **USD 체급을 넘기면 그 자리에서 예외가 납니다** —
    시즌 고정이 조용히 사라지는 게 아니라 발행 배치가 매일 밤 죽습니다. 그래서
    `resolve_bracket_for_season_usd()` 를 따로 뒀습니다(이 트랙의 네 번째 예외 사례).
    """
    # 경계 자체는 공유합니다.
    assert duel_rules.season_key_for_date(TODAY) == SEASON

    # 원화 시즌 함수에 USD 체급을 넘기면 **예외** — 이게 함수를 가른 이유입니다.
    with pytest.raises(DuelRuleError):
        duel_rules.resolve_bracket_for_season(None, "usd_75000_plus", TODAY)
    # USD 함수는 정상 처리합니다.
    assert duel_rules.resolve_bracket_for_season_usd(None, "usd_75000_plus", TODAY) == {
        "season_key": SEASON, "bracket_key": "usd_75000_plus",
        "source": "assigned", "needs_write": True}
    # 그리고 반대 방향도 막습니다 — USD 함수에 원화 체급을 넘기면 거절합니다.
    with pytest.raises(DuelRuleError):
        duel_rules.resolve_bracket_for_season_usd(None, "krw_100m_plus", TODAY)

    assert duel_rules.resolve_bracket_for_season_usd is not duel_rules.resolve_bracket_for_season


# =============================================================================
# 1. 🔴 실제 매입원가합계(달러) — 원화 버전과 **정확히 반대**임을 고정
# =============================================================================
def _us_holding(user_id, quantity, price, ticker="AAPL"):
    return {"user_id": user_id, "market": "US", "ticker": ticker, "stock_name": "Apple",
            "quantity": quantity, "avg_purchase_price": price, "currency": "USD"}


def _kr_holding(user_id, quantity, price, ticker="005930"):
    return {"user_id": user_id, "market": "KR", "ticker": ticker, "stock_name": "삼성전자",
            "quantity": quantity, "avg_purchase_price": price, "currency": "KRW"}


def test_usd_only_holdings_give_a_usd_cost_basis():
    """
    매입원가 = 수량 × 평균매입가. 규칙은 "내 성적표"(`scorecard_db.evaluate_holding()`)가
    이미 갖고 있으므로 여기서 다시 곱하지 않고 그 함수를 씁니다(§0-3-10).
    """
    summary = duel_publish_usd.summarize_real_principal_usd(
        [_us_holding("u1", 10, 200.0), _us_holding("u1", 3, 500.0, ticker="MSFT")])
    assert summary["status"] == duel_publish.PRINCIPAL_OK
    assert summary["usd_cost_basis"] == pytest.approx(3_500.0)
    assert summary["currencies"] == ["USD"]
    assert duel_rules.assign_bracket_usd(summary["usd_cost_basis"]) == "usd_2250_3750"


def test_any_non_usd_holding_makes_it_fx_mixed_not_a_partial_sum():
    """
    🔴 §0-1 — 이 앱에는 **환율 시계열이 없습니다**
    (`scorecard_db.NO_FX_CONVERSION_NOTICE`). 달러분만으로 체급을 매기면 실제보다 가벼운
    체급이 되어 **그 사용자에게 유리한 방향으로 사실과 다른 결과**가 됩니다.
    """
    summary = duel_publish_usd.summarize_real_principal_usd(
        [_us_holding("u1", 10, 200.0), _kr_holding("u1", 10, 700_000)])
    assert summary["status"] == duel_publish.PRINCIPAL_FX_MIXED
    assert summary["usd_cost_basis"] is None
    assert summary["currencies"] == ["KRW", "USD"]
    assert duel_publish_usd.resolve_bracket_for_account_usd(summary, None, TODAY)["bracket_key"] \
        == duel_rules.BRACKET_NONE_KEY


def test_no_holdings_is_not_zero_dollars():
    """
    🔴 §0-1 — "아직 아무것도 등록하지 않음"을 "$0 어치 보유"로 바꾸면, 그 사람은 자기 것이
    아닌 최하위 체급($750 미만)에 들어갑니다. 그래서 값을 만들지 않고 구간 미적용입니다.
    """
    summary = duel_publish_usd.summarize_real_principal_usd([])
    assert summary["status"] == duel_publish.PRINCIPAL_NO_HOLDINGS
    assert summary["usd_cost_basis"] is None
    resolved = duel_publish_usd.resolve_bracket_for_account_usd(summary, None, TODAY)
    assert resolved["bracket_key"] == duel_rules.BRACKET_NONE_KEY
    assert resolved["fresh_source"] == duel_publish.PRINCIPAL_NO_HOLDINGS


@pytest.mark.parametrize("holdings,krw_status,usd_status", [
    # 국내주식만 → 원화는 OK, USD 는 FX_MIXED
    ([_kr_holding("u1", 10, 700_000)],
     duel_publish.PRINCIPAL_OK, duel_publish.PRINCIPAL_FX_MIXED),
    # 미국주식만 → 원화는 FX_MIXED, USD 는 OK
    ([_us_holding("u1", 10, 200.0)],
     duel_publish.PRINCIPAL_FX_MIXED, duel_publish.PRINCIPAL_OK),
    # 섞여 있음 → 둘 다 FX_MIXED (합치는 경로는 어느 쪽에도 없습니다)
    ([_kr_holding("u1", 10, 700_000), _us_holding("u1", 10, 200.0)],
     duel_publish.PRINCIPAL_FX_MIXED, duel_publish.PRINCIPAL_FX_MIXED),
    # 아무것도 없음 → 둘 다 NO_HOLDINGS (통화와 무관한 개념)
    ([], duel_publish.PRINCIPAL_NO_HOLDINGS, duel_publish.PRINCIPAL_NO_HOLDINGS),
])
def test_krw_and_usd_summaries_are_mirror_opposites(holdings, krw_status, usd_status):
    """
    🔴 **"원화와 USD 가 다르다"를 고정하는 대조 회귀 테스트.** (§5-16 이 추가한
    `resolve_fill_trading_day` vs `_usd` 대조 테스트와 같은 성격입니다 — 같은 입력을 두
    함수에 넣어 답이 갈리는 것을 못 박습니다.)

    **원화 함수를 이 트랙에서 그대로 쓰면 달러 보유자가 전원 FX_MIXED("구간 미적용")로
    떨어져 USD 체급이 통째로 사라집니다.** 화면에도 로그에도 오류로 안 나타나는 종류라
    이 테스트가 유일한 방어선입니다.
    """
    krw = duel_publish.summarize_real_principal(holdings)
    usd = duel_publish_usd.summarize_real_principal_usd(holdings)
    assert krw["status"] == krw_status
    assert usd["status"] == usd_status
    # 키 이름도 일부러 다릅니다 — 같으면 두 요약 dict 가 섞여도 아무도 눈치채지 못합니다.
    assert "krw_cost_basis" in krw and "krw_cost_basis" not in usd
    assert "usd_cost_basis" in usd and "usd_cost_basis" not in krw


def test_currency_constants_come_from_scorecard_not_from_string_literals():
    """
    §0-3-10 — 통화 코드는 `utils/scorecard_db.py` 가 단일 출처입니다. 실행 코드가
    `scorecard_db.CURRENCY_USD` 를 실제로 쓰는지(문자열 "USD" 를 따로 박아 두지 않았는지),
    그리고 **원화 상수를 실수로 보지 않는지**(그 한 줄이면 판정이 통째로 뒤집힙니다).
    """
    tree, _source = _module_ast("duel_publish_usd.py")
    used = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "scorecard_db"}
    assert "CURRENCY_USD" in used, "통화 판정에 scorecard_db.CURRENCY_USD 를 쓰지 않습니다"
    assert "CURRENCY_KRW" not in used, \
        "USD 트랙 발행 배치가 원화 통화 상수를 봅니다 — 판정이 뒤집힐 수 있습니다"
    assert scorecard_db.CURRENCY_USD == "USD"

    # 그리고 실행 코드에 통화 코드 문자열을 따로 박아 두지 않았는지(상수를 우회하지 않기).
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "USD" not in literals and "KRW" not in literals


def test_summarize_by_user_groups_and_uses_the_usd_summary():
    grouped = duel_publish_usd.summarize_real_principal_by_user_usd(
        [_us_holding("u1", 10, 200.0), _us_holding("u2", 1, 100.0),
         _kr_holding("u2", 1, 1_000_000)])
    assert grouped["u1"]["status"] == duel_publish.PRINCIPAL_OK
    assert grouped["u1"]["usd_cost_basis"] == pytest.approx(2000.0)
    assert grouped["u2"]["status"] == duel_publish.PRINCIPAL_FX_MIXED


def test_broken_holdings_stop_the_batch_instead_of_guessing():
    """값을 추측해서 이어 가지 않습니다(§0-1) — 원화 함수와 같은 규약."""
    with pytest.raises(DuelPublishError):
        duel_publish_usd.summarize_real_principal_usd([{"user_id": "u1"}])


# =============================================================================
# 2. 체급(달러) 배정 + 시즌 고정 — work order 5-3 · 5-11-9
# =============================================================================
@pytest.mark.parametrize("amount,expected", [
    (75_000, "usd_75000_plus"),      # 경계값 그 자체는 **위쪽** 구간
    (74_999, "usd_45000_75000"),
    (45_000, "usd_45000_75000"),
    (44_999, "usd_22500_45000"),
    (22_500, "usd_22500_45000"),
    (22_499, "usd_7500_22500"),
    (7_500, "usd_7500_22500"),       # 시드머니 원금 지점
    (7_499, "usd_3750_7500"),
    (3_750, "usd_3750_7500"),
    (3_749, "usd_2250_3750"),
    (2_250, "usd_2250_3750"),
    (2_249, "usd_750_2250"),
    (750, "usd_750_2250"),
    (749, "usd_under_750"),
    (0, "usd_under_750"),
])
def test_resolve_bracket_for_account_usd_splits_on_the_usd_tiers(amount, expected):
    """
    `resolve_bracket_for_account_usd()` 가 `BRACKET_TIERS_USD`(§0-3-2 의 $750/$2,250/…)로
    정확히 갈리는지 — **경계값 그 자체**가 어느 쪽으로 가는지까지 한 줄씩 못 박습니다.
    """
    summary = {"status": duel_publish.PRINCIPAL_OK, "usd_cost_basis": float(amount),
               "currencies": ["USD"]}
    resolved = duel_publish_usd.resolve_bracket_for_account_usd(summary, None, TODAY)
    assert resolved["bracket_key"] == expected
    assert resolved["fresh_source"] == "computed"
    assert resolved["season_key"] == SEASON
    assert resolved["needs_write"] is True


def test_usd_bracket_keys_never_collide_with_krw_bracket_keys():
    """
    두 트랙의 체급 식별자가 겹치면, 발행표를 잘못 섞어도 아무도 눈치채지 못합니다.
    (`BRACKET_NONE_KEY` 는 **의도적으로 공유**하는 유일한 값입니다 — "구간을 못 정하는
    이유"는 통화와 무관한 개념이라 5-13 에서 공유하기로 확정했습니다.)
    """
    krw = set(duel_rules.BRACKET_KEYS) - {duel_rules.BRACKET_NONE_KEY}
    usd = set(duel_rules.BRACKET_KEYS_USD) - {duel_rules.BRACKET_NONE_KEY}
    assert not (krw & usd)
    assert duel_rules.BRACKET_NONE_KEY in duel_rules.BRACKET_KEYS
    assert duel_rules.BRACKET_NONE_KEY in duel_rules.BRACKET_KEYS_USD


def test_usd_bracket_stays_fixed_mid_season_even_if_real_principal_changes():
    """
    🔴 5-3 의 핵심 규칙이 USD 트랙에서도 살아 있는지. 이 배치는 매일 돌기 때문에, 이
    규칙이 조용히 사라지기 가장 쉬운 자리입니다.
    """
    existing = {"season_key": SEASON, "bracket_key": "usd_750_2250"}
    summary = {"status": duel_publish.PRINCIPAL_OK, "usd_cost_basis": 120_000.0,
               "currencies": ["USD"]}
    # 오늘 계산하면 훨씬 무거운 체급이 나오는 상황.
    assert duel_rules.assign_bracket_usd(120_000.0) == "usd_75000_plus"

    resolved = duel_publish_usd.resolve_bracket_for_account_usd(
        summary, existing, date(2027, 2, 28))
    assert resolved["bracket_key"] == "usd_750_2250", "시즌 중에는 기존 체급이 이겨야 합니다"
    assert resolved["source"] == "kept"
    assert resolved["needs_write"] is False


def test_usd_bracket_is_recomputed_when_the_season_rolls_over():
    """해가 바뀌면(새 시즌, 3월 1일) 그 시점의 매입원가합계로 **다시** 매깁니다(5-3 · 5-11-8)."""
    existing = {"season_key": SEASON, "bracket_key": "usd_750_2250"}
    summary = {"status": duel_publish.PRINCIPAL_OK, "usd_cost_basis": 120_000.0,
               "currencies": ["USD"]}
    resolved = duel_publish_usd.resolve_bracket_for_account_usd(
        summary, existing, date(2027, 3, 1))
    assert resolved["season_key"] == "2027-03-01"
    assert resolved["bracket_key"] == "usd_75000_plus"
    assert resolved["source"] == "assigned"
    assert resolved["needs_write"] is True


def test_corrupt_stored_usd_bracket_is_not_silently_replaced():
    """저장된 체급 문자열이 이상하면 임의의 값으로 갈아치우지 않고 멈춥니다(§0-1)."""
    summary = {"status": duel_publish.PRINCIPAL_OK, "usd_cost_basis": 1000.0,
               "currencies": ["USD"]}
    with pytest.raises(DuelRuleError):
        duel_publish_usd.resolve_bracket_for_account_usd(
            summary, {"season_key": SEASON, "bracket_key": "체급없음"}, TODAY)
    # 원화 체급이 USD 배정 기록에 섞여 들어와도 조용히 쓰지 않습니다.
    with pytest.raises(DuelRuleError):
        duel_publish_usd.resolve_bracket_for_account_usd(
            summary, {"season_key": SEASON, "bracket_key": "krw_100m_plus"}, TODAY)


def test_account_without_the_independent_consent_still_joins_without_a_bracket_usd():
    """
    5-2-4 — 실제 매입총합 사용에 동의하지 않은 사용자도 **순위표에는 참여합니다.**
    빠지는 것은 체급뿐입니다. (요약이 `None` = 그 사용자의 holdings 를 **읽지도 않았음**.)
    """
    resolved = duel_publish_usd.resolve_bracket_for_account_usd(None, None, TODAY)
    assert resolved["bracket_key"] == duel_rules.BRACKET_NONE_KEY
    assert resolved["fresh_source"] == "no_consent"


# =============================================================================
# 3. 그룹 조합 — 3 × len(BRACKET_KEYS_USD), 개수 하드코딩 금지
# =============================================================================
def test_all_possible_groups_usd_is_windows_times_usd_brackets():
    groups = duel_publish_usd.all_possible_groups_usd()
    expected = len(duel_rules.ACCOUNT_WINDOW_TYPES) * len(duel_rules.BRACKET_KEYS_USD)
    assert len(groups) == expected, "체급 표가 늘거나 줄면 이 목록이 자동으로 따라가야 합니다"
    assert len(set(groups)) == expected, "중복 조합이 있습니다"
    assert set(groups) == {(window, bracket)
                           for window in duel_rules.ACCOUNT_WINDOW_TYPES
                           for bracket in duel_rules.BRACKET_KEYS_USD}


def test_all_possible_groups_usd_contains_no_krw_bracket_keys():
    """USD 청소 목록에 원화 체급이 섞이면, 원화 그룹 이름으로 USD 표를 뒤지게 됩니다."""
    brackets = {bracket for _window, bracket in duel_publish_usd.all_possible_groups_usd()}
    krw_only = set(duel_rules.BRACKET_KEYS) - {duel_rules.BRACKET_NONE_KEY}
    assert not (brackets & krw_only)


def test_group_count_does_not_appear_as_a_hardcoded_number_in_the_module():
    """
    §0-3-10 — 조합 개수(27)를 파일에 숫자로 적어 두면 체급 표가 바뀔 때 조용히 어긋납니다.
    실행 코드에는 그 숫자가 없어야 합니다(주석·docstring 설명은 허용).
    """
    code = _executable_source("duel_publish_usd.py")
    assert "27" not in code


# =============================================================================
# 4. 픽스처 — USD 발행 배치를 통째로 돌리는 가짜 클라이언트
# =============================================================================
def _consent_row(**overrides):
    row = {"account_id": "acc-1", "consent_rank": True, "consent_return": True,
           "consent_holdings": True, "consent_quantity": True, "consent_buy_amount": True,
           "final_confirmed": True, "final_confirmed_at": "2026-08-01T10:00:00+09:00",
           "consent_real_principal_bracket": True, "revoked_at": None}
    row.update(overrides)
    return row


def _in_filtered(rows, column):
    """
    `in` 필터를 실제로 적용하는 가짜 응답(원화 테스트와 같은 도우미). 진짜 PostgREST 와 같게
    동작해야, 청크로 나눠 조회하는 코드가 "매 청크마다 전체를 받는" 비현실적인 상황에서
    통과해 버리는 일이 없습니다.
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


def _publish_client(account_count, *, consented_principal=True, revoked=None,
                    nicknames=None, leaderboard_probe=None, positions=None,
                    existing_assignments=None, extra_accounts=None, holdings=None):
    """
    USD 발행 배치용 가짜 클라이언트. `duel_public_consent_usd` 표를 두 가지 목적(발행 대상 /
    철회 목록)으로 조회하므로, 필터를 보고 갈라 주는 callable 로 응답을 지정합니다.
    (원화 `tests/test_duel_publish.py::_publish_client()` 와 같은 구조이고, 표 이름만
     `_usd` 입니다 — 계좌의 시드·통화도 USD 값입니다.)
    """
    accounts = [{"id": f"acc-{i}", "user_id": f"user-{i}", "window_type": "M1",
                 "status": "active", "seed_amount": duel_rules.SEED_AMOUNT_USD,
                 "currency": "USD", "anchor_date": "2026-01-02"} for i in range(account_count)]
    accounts.extend(list(extra_accounts or []))
    consents = [_consent_row(account_id=f"acc-{i}",
                             consent_real_principal_bracket=consented_principal)
                for i in range(account_count)]
    revoked_rows = list(revoked or [])

    def consent_select(query):
        if ("not.is", "revoked_at", "null") in query.filters:
            return revoked_rows
        return consents

    snapshots = []
    for index in range(account_count):
        snapshots.append({"account_id": f"acc-{index}", "snapshot_date": "2026-08-19",
                          "total_value": duel_rules.SEED_AMOUNT_USD,
                          "cash_flow_amount": duel_rules.SEED_AMOUNT_USD})
        snapshots.append({"account_id": f"acc-{index}", "snapshot_date": "2026-08-20",
                          "total_value": duel_rules.SEED_AMOUNT_USD * (1 + (index % 5) / 100.0),
                          "cash_flow_amount": 0})

    def leaderboard_select(query):
        if "window_type" in query.filter_map:
            return []                     # 미달 그룹 청소 점검 — 과거 발행 없음
        return list(leaderboard_probe if leaderboard_probe is not None else [])

    # 기본 실보유: 사용자마다 미국주식 $3,000 어치 → 체급 `usd_2250_3750`.
    default_holdings = [_us_holding(f"user-{i}", 15, 200.0) for i in range(account_count)]

    return FakeClient(responses={
        (duel_db_usd.CONSENT_TABLE_USD, "select"): consent_select,
        (duel_db_usd.ACCOUNTS_TABLE_USD, "select"): accounts,
        ("holdings", "select"): _in_filtered(
            list(holdings if holdings is not None else default_holdings), "user_id"),
        (duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "select"): list(existing_assignments or []),
        (duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select"): snapshots,
        (duel_db_usd.POSITIONS_TABLE_USD, "select"): list(positions if positions is not None else [
            {"account_id": f"acc-{i}", "ticker": "AAPL", "stock_name": "Apple",
             "quantity": 5, "avg_cost": 200.0, "status": "active"}
            for i in range(account_count)]),
        (duel_db.NICKNAMES_TABLE, "select"): _in_filtered(
            list(nicknames if nicknames is not None else [
                {"user_id": f"user-{i}", "window_type": "M1", "nickname": f"닉네임{i:04d}"}
                for i in range(account_count)]), "user_id"),
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): leaderboard_select,
    })


# =============================================================================
# 5. 🔴 §0-3-8 다섯 원칙 — USD 배치에서도 전부 지켜지는가
# =============================================================================
# ── 원칙 ① 동의하지 않은 사람의 데이터를 읽는 코드 경로가 없다 ────────────────────
def test_holdings_are_never_read_when_nobody_consented_usd():
    """
    🔴 동의자가 0명이면 실제 자산 표에 **질의 자체를 보내지 않습니다.** 배치를 통째로
    돌려서 확인합니다(함수 단위가 아니라 실제 경로로).
    """
    client = _publish_client(account_count=3, consented_principal=False)
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert client.calls_for("holdings") == [], "동의자가 없는데 holdings 를 조회했습니다"


def test_only_consenting_users_ids_reach_the_holdings_query_usd():
    """
    🔴 5-3 — *"동의 없는 사용자의 `holdings` 를 읽는 코드 경로가 **하나라도** 있으면
    §0-3-8 위반"*. 동의자와 비동의자가 섞였을 때 실제 `in` 필터에 동의자만 들어가는지.
    """
    client = _publish_client(account_count=2)
    client.responses[(duel_db_usd.CONSENT_TABLE_USD, "select")] = (
        lambda query: [] if ("not.is", "revoked_at", "null") in query.filters else [
            _consent_row(account_id="acc-0", consent_real_principal_bracket=True),
            _consent_row(account_id="acc-1", consent_real_principal_bracket=False)])
    duel_publish_usd.run_publish_batch_usd(client, TODAY)

    call = client.only_call("holdings", "select")
    assert call.filter_map["user_id"] == ["user-0"], \
        "동의하지 않은 사용자의 id 가 실보유 조회에 섞였습니다"


def test_real_principal_fetch_is_the_shared_function_with_a_required_user_list():
    """
    "안 주면 전부"라는 편의 기본값이 **없어야** 합니다. 그 한 줄이 곧 5-3 위반입니다.
    (원화와 **같은 함수 객체**를 씁니다 — `holdings` 는 통화 컬럼을 이미 갖고 있는
     트랙 무관 표라 조회 함수를 복제할 이유가 없습니다, §5-14.)
    """
    assert duel_db_usd.fetch_real_principal_holdings is duel_db.fetch_real_principal_holdings
    parameters = inspect.signature(duel_db_usd.fetch_real_principal_holdings).parameters
    assert list(parameters) == ["service_client", "user_ids"]
    assert parameters["user_ids"].default is inspect.Parameter.empty


def test_usd_publish_module_does_not_use_report_dbs_fetch_all_holdings():
    """
    🔴 `report_db.fetch_all_holdings()` 는 **전체 사용자**의 보유종목을 읽습니다. 여기서
    그걸 부르면 동의하지 않은 사람의 자산이 이 배치의 메모리에 올라오고, 5-3 위반입니다.
    """
    code = _executable_source("duel_publish_usd.py")
    assert "fetch_all_holdings" not in code
    assert "report_db" not in code


# ── 원칙 ② "동의했는가"를 두 번 확인한다 ────────────────────────────────────────
def test_consent_is_checked_twice_the_filter_and_then_every_row_usd():
    """
    🔴 조회 필터로 한 번(`final_confirmed=true` + `revoked_at is null`), 행마다
    `assert_full_consent()` 로 또 한 번. 두 번째 확인은 "필터가 잘못 쓰였을 때"를 위한
    것입니다 — 필터 오타 하나가 전원 공개로 이어지는 구조를 만들지 않습니다(§0-3-9).
    """
    # (a) 조회 필터가 실제로 걸려 나가는가.
    client = _publish_client(account_count=1)
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    publish_selects = [call for call in client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "select")
                       if call.filter_map.get("final_confirmed") is True]
    assert len(publish_selects) == 1
    assert ("is", "revoked_at", "null") in publish_selects[0].filters

    # (b) 필터가 깨져 동의 안 한 행이 섞여 들어오면 **행 단위 확인이 잡아 멈춥니다.**
    broken = _publish_client(account_count=1)
    broken.responses[(duel_db_usd.CONSENT_TABLE_USD, "select")] = (
        lambda query: [] if ("not.is", "revoked_at", "null") in query.filters
        else [_consent_row(account_id="acc-0", consent_quantity=False)])
    with pytest.raises(DuelPublishError) as excinfo:
        duel_publish_usd.run_publish_batch_usd(broken, TODAY)
    assert "consent_quantity" in str(excinfo.value)
    assert broken.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert") == []


def test_revoked_row_that_slipped_through_the_filter_stops_the_usd_batch():
    revoked_but_returned = _publish_client(account_count=1)
    revoked_but_returned.responses[(duel_db_usd.CONSENT_TABLE_USD, "select")] = (
        lambda query: [] if ("not.is", "revoked_at", "null") in query.filters
        else [_consent_row(account_id="acc-0", revoked_at="2026-08-01T00:00:00+09:00")])
    with pytest.raises(DuelPublishError):
        duel_publish_usd.run_publish_batch_usd(revoked_but_returned, TODAY)


# ── 원칙 ③ 모르는 값을 0 으로 바꾸지 않는다 ─────────────────────────────────────
def test_accounts_without_a_computable_return_are_skipped_not_zeroed_usd():
    """
    개설 첫날처럼 구간 수익률이 없는 계좌는 0% 로 세우지 않고 뺍니다(§0-1).
    "0% 수익"과 "아직 성적이 없음"은 다른 말입니다.
    """
    client = _publish_client(account_count=3)
    # 스냅샷을 계좌당 1개(개설일)만 주면 TWR 은 'INSUFFICIENT' 입니다.
    client.responses[(duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select")] = [
        {"account_id": f"acc-{i}", "snapshot_date": "2026-08-20",
         "total_value": duel_rules.SEED_AMOUNT_USD,
         "cash_flow_amount": duel_rules.SEED_AMOUNT_USD} for i in range(3)]
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["group_counts"] == {}
    assert {row["reason"] for row in summary["skipped"]} == {duel_publish.SKIP_NO_TWR}
    assert client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert") == []


def test_withheld_return_is_none_never_zero_in_the_usd_payload():
    """`or 0` 한 글자면 생기는 사고를 못 박습니다(§0-1) — payload 조립은 원화와 공유 함수."""
    payload = duel_publish_usd.leaderboard_payload(
        ("M1", "usd_2250_3750"),
        [{"nickname": "a", "twr_pct": None, "rank": 1},
         {"nickname": "b", "twr_pct": 0.0, "rank": 2}])
    assert payload[0]["twr_pct"] is None and payload[0]["twr_pct"] != 0
    assert payload[1]["twr_pct"] == 0.0 and payload[1]["twr_pct"] is not None


def test_usd_leaderboard_write_refuses_identifier_fields_as_a_last_line_of_defence():
    """발행표에는 `user_id` 도 `account_id` 도 들어가지 않습니다(스키마 §13-9)."""
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db_usd.write_public_leaderboard_usd(client, TODAY, [
            {"window_type": "M1", "bracket_key": "usd_2250_3750", "rank": 1,
             "nickname": "a", "twr_pct": 1.0, "account_id": "acc-1"}])
    assert "account_id" in str(excinfo.value)
    assert client.calls_for(op="insert") == []


def test_leaderboard_payload_never_carries_identifiers_usd():
    payload = duel_publish_usd.leaderboard_payload(
        ("M1", "usd_2250_3750"),
        [{"nickname": "a", "twr_pct": 1.0, "rank": 1,
          "account_id": "acc-1", "positions": [], "user_id": "user-1"}])
    assert set(payload[0]) == {"window_type", "bracket_key", "rank", "nickname", "twr_pct"}


# ── 원칙 ④ 소수 인원 그룹은 아예 만들지 않는다 ──────────────────────────────────
def test_usd_publish_batch_publishes_nothing_below_the_threshold():
    client = _publish_client(account_count=499)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["leaderboard_rows"] == 0
    assert summary["holdings_rows"] == 0
    assert summary["blocked_groups"] == ["M1/usd_2250_3750"]
    assert client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert") == []


def test_usd_publish_batch_publishes_at_exactly_the_threshold():
    client = _publish_client(account_count=500)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["published_groups"] == ["M1/usd_2250_3750"]
    assert summary["leaderboard_rows"] == 500
    assert summary["holdings_rows"] == 500
    assert duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION == 500, "오너 확정값(5-6, 통화 무관)"


def test_usd_group_that_fell_below_the_threshold_has_its_old_rows_deleted():
    """
    🔴 5-6 — *"임계값 미만인 구간은 아예 발행하지 않습니다. **이미 발행돼 있던 행도
    제거합니다.**"* 어제 501명이었다가 오늘 499명이 된 경우가 정확히 이 경우입니다.
    """
    client = FakeClient(responses={
        (duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select"): [
            {"published_date": "2026-08-19", "nickname": "어제사람0001"},
            {"published_date": "2026-08-20", "nickname": "어제사람0001"},
        ],
    })
    duel_db_usd.delete_published_group_usd(client, "M1", "usd_2250_3750")

    board_delete = client.only_call(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "delete")
    assert board_delete.filter_map == {"window_type": "M1", "bracket_key": "usd_2250_3750"}
    assert "published_date" not in board_delete.filter_map, "과거 날짜도 지워야 합니다"
    holding_deletes = client.calls_for(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "delete")
    assert {call.filter_map["published_date"] for call in holding_deletes} == \
        {"2026-08-19", "2026-08-20"}


def test_usd_publish_batch_checks_every_possible_group_for_stale_rows():
    """
    참가자가 **전부 사라진** 그룹의 과거 행도 지워야 합니다. "오늘 참가자가 있는 그룹"만
    청소하면 그런 그룹이 영원히 공개된 채 남습니다.
    """
    client = _publish_client(account_count=0, leaderboard_probe=[{"id": 1}])
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    probes = client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select")
    group_probes = [call for call in probes if "window_type" in call.filter_map]
    assert len(group_probes) == len(duel_publish_usd.all_possible_groups_usd())


def test_usd_publish_batch_skips_the_group_sweep_when_nothing_was_ever_published():
    """초기 운영 기간(발행표가 완전히 빔)에는 전부 헛걸음이라 질의 1개로 끝냅니다."""
    client = _publish_client(account_count=0, leaderboard_probe=[])
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    probes = [call for call in
              client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "select")
              if "window_type" in call.filter_map]
    assert probes == []


# ── 원칙 ⑤ 철회한 사람의 과거 기록을 매번 지운다 ────────────────────────────────
def test_usd_publish_batch_purges_revoked_accounts_before_anything_else():
    """
    발행 배치가 **가장 먼저** 철회 청소를 하는지. 순서를 뒤집으면, 오늘 발행이 중간에
    실패했을 때 철회한 사람의 과거 기록이 하루 더 남습니다(5-8-1).
    """
    client = _publish_client(
        account_count=0,
        revoked=[{"account_id": "acc-9", "revoked_at": "2026-08-01T00:00:00+09:00"}],
        extra_accounts=[{"id": "acc-9", "user_id": "user-9", "window_type": "M1",
                         "status": "active"}],
        nicknames=[{"user_id": "user-9", "window_type": "M1", "nickname": "떠난사람0009"}])
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)

    assert summary["revoked_accounts"] == 1
    ops = [(call.table, call.op) for call in client.calls]
    first_delete = next(index for index, item in enumerate(ops) if item[1] == "delete")
    first_write = next((index for index, item in enumerate(ops) if item[1] == "insert"), len(ops))
    assert first_delete < first_write
    delete_names = [call.filter_map.get("nickname") for call in client.calls_for(op="delete")]
    assert ["떠난사람0009"] in delete_names


def test_revoked_usd_rows_are_deleted_at_every_date_not_just_today():
    """
    🔴 5-8-1 — *"그 계좌의 발행된 공개 기록을 **전부 영구 삭제**"*. 삭제 질의에
    `published_date` 필터가 **있으면 안 됩니다.**
    """
    client = FakeClient()
    duel_db_usd.delete_published_rows_for_nicknames_usd(client, ["떠난사람0009", "떠난사람0010"])
    deletes = client.calls_for(op="delete")
    assert {call.table for call in deletes} == {duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD,
                                                duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD}
    for call in deletes:
        assert {column for _op, column, _value in call.filters} == {"nickname"}


# =============================================================================
# 6. 전량 재작성(5-4-4) · 시즌 배정 기록 · 닉네임 없는 계좌
# =============================================================================
def test_usd_full_rewrite_deletes_todays_rows_before_inserting():
    """🔴 5-4-4 — 그날 발행분을 통째로 갈아끼웁니다(부분 갱신은 자격 잃은 행을 남깁니다)."""
    client = _publish_client(account_count=500)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["leaderboard_rows"] == 500

    date_deletes = [index for index, call in enumerate(client.calls)
                    if call.op == "delete"
                    and call.filter_map.get("published_date") == TODAY.isoformat()]
    inserts = [index for index, call in enumerate(client.calls)
               if call.op == "insert" and call.table in (
                   duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD,
                   duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD)]
    assert len(date_deletes) == 2, "두 발행표 각각 그날 행을 통째로 지워야 합니다"
    assert max(date_deletes) < min(inserts), "삭제가 삽입보다 먼저여야 합니다"


def test_running_the_usd_batch_twice_on_the_same_day_does_not_duplicate_rows():
    for _run in range(2):
        client = _publish_client(account_count=500)
        duel_publish_usd.run_publish_batch_usd(client, TODAY)
        rows = [row for call in
                client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert")
                for row in call.rows]
        keys = [(row["published_date"], row["window_type"], row["bracket_key"], row["nickname"])
                for row in rows]
        assert len(keys) == len(set(keys)), "같은 참가자가 한 날짜에 두 번 실렸습니다"


def test_usd_publish_batch_reads_the_season_assignments_before_deciding():
    """배치가 체급 배정 기록을 **읽지 않고** 넘어가면 시즌 고정이 조용히 사라집니다."""
    client = _publish_client(account_count=3)
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    call = client.only_call(duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "select")
    assert call.filter_map == {"season_key": SEASON}


def test_usd_publish_batch_keeps_the_season_bracket_and_does_not_rewrite_it():
    existing = [{"account_id": f"acc-{i}", "season_key": SEASON,
                 "bracket_key": "usd_75000_plus"} for i in range(500)]
    client = _publish_client(account_count=500, existing_assignments=existing)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)

    assert summary["published_groups"] == ["M1/usd_75000_plus"], \
        "오늘 계산하면 $2,250~$3,750 이지만 시즌 중이라 기존 체급이 이겨야 합니다"
    assert client.calls_for(duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "insert") == []
    assert summary["principal_status_counts"] == {"kept": 500}


def test_usd_bracket_assignments_are_inserted_never_updated():
    """
    🔴 "시즌 중 고정"이 앱의 조심성이 아니라 **구조**임을 고정합니다. DB 도 배치에게
    update 권한을 주지 않았으므로(스키마 §14), 여기에 upsert 가 생기면 그날 배치가 실패합니다.
    """
    client = FakeClient()
    duel_db_usd.insert_bracket_assignments_usd(client, [
        {"account_id": "acc-1", "season_key": SEASON, "bracket_key": "usd_2250_3750"}])
    assert client.only_call(duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD).op == "insert"

    source = (REPO_ROOT / "utils" / "duel_db_usd.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == "insert_bracket_assignments_usd")
    body = ast.get_source_segment(source, node)
    assert ".upsert(" not in body and ".update(" not in body


def test_usd_publish_batch_skips_accounts_without_a_nickname_and_says_so():
    """
    닉네임이 없는 계좌는 발행하지 않고, **그 사실을 요약에 남깁니다**(§0-1). 배치가 닉네임을
    대신 만들어 주지도 않습니다(`duel_nicknames` 는 두 트랙 공유 표라 더욱 그렇습니다).
    """
    nicknames = [{"user_id": f"user-{i}", "window_type": "M1", "nickname": f"닉네임{i:04d}"}
                 for i in range(499)]
    client = _publish_client(account_count=500, nicknames=nicknames)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["leaderboard_rows"] == 0, "499명이 되어 최소 인원 미달"
    assert [row["reason"] for row in summary["skipped"]] == [duel_publish.SKIP_NO_NICKNAME]
    assert client.calls_for(duel_db.NICKNAMES_TABLE, "insert") == []


def test_usd_holdings_payload_carries_buy_amount_in_dollars():
    """
    매입금액 = 수량 × 평단가(`duel_positions_usd` 의 가중평균 평단가). 조립 함수는 원화와
    공유하지만, 이 트랙에서 나오는 값이 달러 단위인지 한 번 확인해 둡니다.
    """
    client = _publish_client(account_count=500)
    duel_publish_usd.run_publish_batch_usd(client, TODAY)
    rows = [row for call in client.calls_for(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "insert")
            for row in call.rows]
    assert len(rows) == 500
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["quantity"] == 5.0
    assert rows[0]["buy_amount"] == pytest.approx(1000.0)   # 5주 × $200


# =============================================================================
# 7. 🔴 트랙 격리 — KRW 표에는 요청이 하나도 가지 않는가 (5-11-9)
# =============================================================================
def test_usd_publish_batch_never_touches_any_krw_duel_table():
    """
    🔴 5-11-9 확정("순위표는 한국장/미국장 완전 별개 표, 절대 병합·비교 안 함")은 화면
    규칙이 아니라 **데이터 경로 규칙**입니다. 배치를 통째로 돌려서 확인합니다.
    (`duel_nicknames` 는 **의도적으로 공유**하는 유일한 표라 예외입니다 — 5-11-10.)
    """
    client = _publish_client(account_count=500,
                             revoked=[{"account_id": "acc-0",
                                       "revoked_at": "2026-08-01T00:00:00+09:00"}])
    duel_publish_usd.run_publish_batch_usd(client, TODAY)

    touched = {call.table for call in client.calls}
    krw_tables = {duel_db.ACCOUNTS_TABLE, duel_db.POSITIONS_TABLE, duel_db.ORDERS_TABLE,
                  duel_db.LEDGER_TABLE, duel_db.DAILY_SNAPSHOTS_TABLE, duel_db.CONSENT_TABLE,
                  duel_db.PUBLIC_LEADERBOARD_TABLE, duel_db.PUBLIC_HOLDINGS_TABLE,
                  duel_db.BRACKET_ASSIGNMENTS_TABLE}
    assert not (touched & krw_tables), f"KRW 표에 질의가 갔습니다: {sorted(touched & krw_tables)}"
    # 그리고 USD 표에는 실제로 갔어야 합니다(격리 테스트가 "아무것도 안 함"으로 통과하지 않게).
    assert duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD in touched
    assert duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD in touched
    assert duel_db_usd.CONSENT_TABLE_USD in touched
    # 닉네임 표만 공유합니다(5-11-10 확정).
    assert duel_db.NICKNAMES_TABLE in touched


def test_krw_publish_table_names_never_appear_in_the_usd_module():
    """
    🔴 소스 레벨 격리 — `_usd` 없는 발행표 이름이 새 파일 어디에도 나오면 안 됩니다.
    (표 이름은 전부 `duel_db_usd` 의 상수를 통해 갑니다 — 이 파일에는 표 이름 문자열
     자체가 하나도 없어야 합니다.)
    """
    tree, _source = _module_ast("duel_publish_usd.py")
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for table in ("holdings", "duel_positions", "profiles", "duel_cash_ledger",
                  "duel_public_leaderboard", "duel_public_holdings", "duel_nicknames",
                  "duel_public_consent", "duel_accounts", "duel_daily_snapshots",
                  "duel_bracket_assignments",
                  "duel_public_leaderboard_usd", "duel_public_holdings_usd"):
        assert table not in literals, f"duel_publish_usd.py 에 표 이름 문자열({table!r})이 있습니다"


def test_usd_module_calls_only_the_usd_db_layer_for_table_work():
    """
    `duel_db.` 로 직접 표를 만지는 호출이 없어야 합니다. 이 파일이 `duel_db` 에서 쓰는 것은
    **통화 무관 상수 하나**(`CONSENT_REAL_PRINCIPAL_FLAG`)뿐입니다.
    """
    tree, _source = _module_ast("duel_publish_usd.py")
    used = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "duel_db"}
    assert used == {"CONSENT_REAL_PRINCIPAL_FLAG"}, \
        f"duel_publish_usd.py 가 duel_db 에서 예상 밖의 것을 씁니다: {sorted(used)}"
    assert duel_db_usd.CONSENT_REAL_PRINCIPAL_FLAG is duel_db.CONSENT_REAL_PRINCIPAL_FLAG


# =============================================================================
# 8. 🔴 §0-3-2 — 계좌 수와 무관하게 질의 횟수가 고정되는가 (원화와 같은 회귀 방식)
# =============================================================================
@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_usd_publish_batch_query_count_does_not_scale_with_accounts(account_count):
    """
    🔴 §0-3-2 회귀 테스트(작업지시서 2-7 이 명시적으로 요구한 것).
    계좌가 3개든 900개든 **고정 왕복 수는 그대로**이고, 늘어나는 것은 "요청 하나가 지나치게
    커지지 않게 자르는" 청크 수뿐입니다 — 계좌마다 부르는 것이 아닙니다.
    """
    client = _publish_client(account_count=account_count)
    duel_publish_usd.run_publish_batch_usd(client, TODAY)

    chunks = -(-account_count // duel_db_usd.CHUNK_SIZE)
    published = duel_rules.group_meets_minimum(account_count)

    for table, op in ((duel_db_usd.ACCOUNTS_TABLE_USD, "select"),
                      (duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "select"),
                      (duel_db_usd.DAILY_SNAPSHOTS_TABLE_USD, "select"),
                      (duel_db_usd.POSITIONS_TABLE_USD, "select")):
        assert len(client.calls_for(table, op)) == 1, f"{table}.{op} 가 1번이 아닙니다"
    assert len(client.calls_for(duel_db_usd.CONSENT_TABLE_USD, "select")) == 2  # 발행 대상 + 철회

    assert len(client.calls_for(duel_db.NICKNAMES_TABLE, "select")) == chunks
    assert len(client.calls_for("holdings", "select")) == chunks
    assert len(client.calls_for(duel_db_usd.BRACKET_ASSIGNMENTS_TABLE_USD, "insert")) == chunks

    inserts = (client.calls_for(duel_db_usd.PUBLIC_LEADERBOARD_TABLE_USD, "insert")
               + client.calls_for(duel_db_usd.PUBLIC_HOLDINGS_TABLE_USD, "insert"))
    assert len(inserts) == (2 * chunks if published else 0)

    # 그날 발행분 통째 삭제 2개 + (발행표가 비어 있으므로) 미달 그룹 청소 0개.
    assert len(client.calls_for(op="delete")) == 2

    # 총합이 "상수 + 청크 × 상수" 꼴인지 — 계좌 수에 비례하는 항이 없어야 합니다.
    fixed = 7                       # 계좌·배정·스냅샷·포지션·동의2·발행표 존재확인
    per_chunk = 3 + (2 if published else 0)
    assert len(client.calls) == fixed + chunks * per_chunk + 2


def test_usd_publish_batch_with_no_participants_writes_nothing_but_still_cleans():
    client = _publish_client(account_count=0)
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY)
    assert summary["consent_count"] == 0
    assert summary["leaderboard_rows"] == 0
    assert client.calls_for(op="insert") == []
    # 그래도 그날 발행분 삭제는 돕니다 — 어제까지 있던 그룹이 오늘 0명이 됐을 수 있습니다.
    assert len(client.calls_for(op="delete")) == 2


# =============================================================================
# 9. dry_run · 날짜 필수 · None 클라이언트
# =============================================================================
def test_usd_dry_run_writes_absolutely_nothing():
    """오너가 "무엇이 발행될 뻔했는지"를 먼저 눈으로 볼 수 있어야 합니다(§0-3-6 의 정신)."""
    client = _publish_client(account_count=500,
                             revoked=[{"account_id": "acc-0",
                                       "revoked_at": "2026-08-01T00:00:00+09:00"}],
                             leaderboard_probe=[{"id": 1}])
    summary = duel_publish_usd.run_publish_batch_usd(client, TODAY, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["leaderboard_rows"] == 500
    for op in ("insert", "update", "upsert", "delete"):
        assert client.calls_for(op=op) == [], f"dry-run 인데 {op} 가 나갔습니다"


def test_usd_publish_batch_requires_an_explicit_date():
    """
    🔴 §0-1 — 이 모듈은 "오늘"을 스스로 정하지 않습니다. 배치가 자정 근처에 돌거나 하루
    늦게 돌면 발행일이 조용히 틀어지고, 그건 나중에 복원할 수 없는 오염입니다.
    """
    parameters = inspect.signature(duel_publish_usd.run_publish_batch_usd).parameters
    assert parameters["published_date"].default is inspect.Parameter.empty

    client = _publish_client(account_count=0)
    with pytest.raises(DuelPublishError):
        duel_publish_usd.run_publish_batch_usd(client, None)
    with pytest.raises(DuelPublishError):
        duel_publish_usd.run_publish_batch_usd(client, "어제")


def test_none_client_raises_a_catchable_error_usd():
    with pytest.raises(DuelPublishError):
        duel_publish_usd.run_publish_batch_usd(None, TODAY)


def test_usd_summary_lines_show_blocked_groups_and_skipped_accounts():
    """§0-1 — 빠진 것과 막힌 것이 로그에 드러나야 합니다(요약 함수는 원화와 공유)."""
    client = _publish_client(account_count=499)
    lines = duel_publish_usd.format_summary_lines(
        duel_publish_usd.run_publish_batch_usd(client, TODAY))
    text = "\n".join(lines)
    assert "499명" in text
    assert "미발행" in text and "500" in text
    assert "usd_2250_3750" in text


def test_shared_summary_lines_carry_no_currency_literal():
    """
    🔴 `format_summary_lines()` 를 재사용해도 되는 **근거**를 회귀로 고정합니다.
    `duel_batch.format_summary_lines()` 에는 실행되는 f-string 안에
    `"…현금 합계: {…:,.0f}원"` 이 박혀 있어 §5-15 에서 새로 정의해야 했는데
    (`format_summary_lines_usd()`), **발행 요약에는 같은 함정이 없습니다** — 금액을 한 번도
    출력하지 않기 때문입니다. 누가 나중에 이 함수에 금액 줄을 추가하면 여기서 잡히고,
    그때는 USD 전용 함수를 갈라야 합니다.

    ⚠️ 검사어를 "원" 한 글자로 잡으면 안 됩니다 — "참가 **인원**"·"전**원**" 같은 정상
       문구가 걸립니다. 실제 사고 패턴은 **서식 자리 바로 뒤에 붙는 통화 단위**이므로
       (`{…}원`), 그 모양과 명시적 통화 기호만 봅니다. 아래에서 원화 배치 함수가 실제로
       이 검사에 **걸리는지**까지 확인해, 검사 자체가 무력하지 않음을 증명합니다.
    """
    units = ("원", "달러", "₩", "$")

    def _money_markers(function):
        """
        함수의 **실행되는** f-string 에서 "서식 자리 바로 뒤에 통화 단위가 붙은" 자리를
        찾습니다(docstring 제외). `f"...{금액:,.0f}원"` 의 AST 는
        `JoinedStr([Constant('… 합계: '), FormattedValue(...), Constant('원')])` 이므로,
        **FormattedValue 다음에 오는 Constant 가 통화 단위로 시작하는지**를 봅니다.
        명시적 통화 기호(₩·$)는 앞뒤 관계없이 그 자체로 표시로 봅니다.
        """
        tree = ast.parse(inspect.getsource(function).lstrip())
        node = tree.body[0]
        body = node.body[1:] if ast.get_docstring(node) else node.body

        found = []
        for statement in body:
            for child in ast.walk(statement):
                if isinstance(child, ast.JoinedStr):
                    previous = None
                    for part in child.values:
                        if (isinstance(part, ast.Constant) and isinstance(part.value, str)
                                and isinstance(previous, ast.FormattedValue)):
                            for unit in units:
                                if part.value.startswith(unit):
                                    found.append(unit)
                        previous = part
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    for symbol in ("₩", "$"):
                        if symbol in child.value:
                            found.append(symbol)
        return sorted(set(found))

    # ① 이 검사가 실제로 통화 표기를 잡는다는 증명 — 원화 야간 배치 함수는 걸립니다
    #    (`"체결에 쓴 현금 합계: {…:,.0f}원"` — §5-15 가 발견한 바로 그 줄).
    assert _money_markers(duel_batch.format_summary_lines) == ["원"], \
        "검사어가 원화 배치의 알려진 사례를 더 이상 잡지 못합니다(검사가 무력해졌습니다)"
    # 그리고 USD 야간 배치 함수는 "$"를 쓰므로 역시 걸립니다(양방향 확인).
    assert "$" in _money_markers(duel_batch_usd.format_summary_lines_usd)

    # ② 그리고 발행 요약 함수는 걸리지 않습니다 → 재사용해도 됩니다.
    assert _money_markers(duel_publish.format_summary_lines) == [], \
        "발행 요약 함수에 통화 표기가 생겼습니다 — USD 전용 함수를 갈라야 합니다"


# =============================================================================
# 10. 구조 검사 (AST/소스) — "조심했는가"가 아니라 "할 수 있는가"
# =============================================================================
def _module_ast(name):
    source = (REPO_ROOT / "utils" / name).read_text(encoding="utf-8")
    return ast.parse(source), source


def _executable_source(name):
    """
    주석과 **문자열 리터럴(docstring 포함)** 을 걷어낸 소스. "실제로 실행되는 코드"만 봅니다.
    (원화 테스트의 같은 도우미 — 이 저장소는 docstring 에 근거를 길게 적는 관례라, 문자열까지
     세면 설명을 잘 쓸수록 검사가 실패합니다.)
    """
    source = (REPO_ROOT / "utils" / name).read_text(encoding="utf-8")
    pieces = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        pieces.append(token.string)
    return "\n".join(pieces)


def test_usd_publish_module_never_creates_its_own_supabase_client():
    """
    발행 배치는 클라이언트를 **인자로만** 받습니다. 여기서 만들기 시작하면 이 파일이
    환경변수를 읽게 되고, 그 순간 "어디서 부르든 도는 코드"가 됩니다(§0-3-8).
    """
    code = _executable_source("duel_publish_usd.py")
    for forbidden in ("create_service_client", "os.environ", "getenv", "create_client"):
        assert forbidden not in code, f"duel_publish_usd.py 가 {forbidden} 을(를) 씁니다"


def test_usd_publish_module_touches_supabase_only_through_the_db_layer():
    """발행 코드가 직접 `.table(...)`/`.rpc(...)` 를 부르면 발행표를 만지는 자리가 흩어집니다."""
    tree, _source = _module_ast("duel_publish_usd.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("table", "rpc"), \
                "duel_publish_usd.py 가 Supabase 를 직접 부릅니다(전부 duel_db_usd 를 통해야 합니다)"


def test_usd_publish_module_does_not_reach_into_other_modules_private_functions():
    """
    남의 모듈의 밑줄 함수를 **속성 접근으로** 가로질러 부르지 않는지.
    (머리말의 재사용 목록에 있는 `_to_date`·`_as_float` 는 import 로 명시적으로 가져오는
     것이라 여기 검사에 걸리지 않습니다 — `utils/duel_db_usd.py` 가 `duel_db` 의 검증
     헬퍼를 import 해 쓰는 것과 같은 관례입니다.)
    """
    tree, _source = _module_ast("duel_publish_usd.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("duel_db", "duel_db_usd", "duel_rules", "duel_batch_usd",
                                 "duel_publish", "scorecard_db"):
                assert not node.attr.startswith("_"), \
                    f"duel_publish_usd.py 가 {node.value.id}.{node.attr} (비공개)를 부릅니다"


def test_bracket_amounts_live_only_in_duel_rules_usd():
    """
    🔴 §0-3-10 — USD 경계 숫자의 **단일 출처**. 경계값이 다른 파일에 다시 적혀 있으면,
    둘 중 하나만 바뀌는 날 어떤 사용자가 자기 것이 아닌 체급에서 겨루게 됩니다.
    """
    numbers = {"75_000", "45_000", "22_500", "3_750", "2_250"}
    for name in ("duel_publish_usd.py", "duel_db_usd.py"):
        code = _executable_source(name)
        for number in numbers:
            assert number not in code, f"{name} 에 USD 체급 경계 숫자({number})가 다시 적혀 있습니다"


def test_every_public_function_in_duel_publish_usd_has_a_docstring():
    """이 트랙의 관례 — 모듈이 **정의한** 모든 공개 함수에 설명이 있어야 합니다."""
    tree, _source = _module_ast("duel_publish_usd.py")
    missing = [node.name for node in tree.body
               if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
               and not ast.get_docstring(node)]
    assert missing == [], f"docstring 이 없는 공개 함수: {missing}"


def test_krw_publish_module_was_not_modified_to_know_about_usd():
    """
    🔴 이번 라운드의 약속 — `utils/duel_publish.py`(원화)는 **한 줄도 건드리지 않았습니다.**
    거기에 USD 분기가 생기면 "이 파일만 보면 된다"는 §0-3-8 검토 성질이 깨집니다.
    """
    code = _executable_source("duel_publish.py")
    for forbidden in ("_usd", "USD", "duel_publish_usd", "duel_db_usd"):
        assert forbidden not in code, \
            f"utils/duel_publish.py 실행 코드에 {forbidden} 이(가) 생겼습니다 — 원화 파일은 무수정이어야 합니다"


# =============================================================================
# 11. 실행 스크립트 · 워크플로우 — 배선과 cron 순서
# =============================================================================
def test_run_script_calls_the_usd_publish_function_not_the_krw_one():
    """함수만 새로 만들고 실행 스크립트가 원화 함수를 부르면 아무것도 안 바뀝니다."""
    source = (REPO_ROOT / "run_duel_publish_batch_us.py").read_text(encoding="utf-8")
    assert "duel_publish_usd.run_publish_batch_usd(" in source
    assert "duel_publish.run_publish_batch(" not in source
    assert "duel_db_usd.create_service_client()" in source


def test_run_script_takes_the_same_argument_names_as_the_krw_script():
    """
    인자 체계를 원화 스크립트와 같게 유지합니다(`--published-date` · `--dry-run`) —
    오너가 두 배치를 같은 방식으로 수동 실행할 수 있어야 합니다.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_run_duel_publish_batch_us", REPO_ROOT / "run_duel_publish_batch_us.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module._parse_args([])
    assert args.published_date is None and args.dry_run is False
    args = module._parse_args(["--published-date", "2026-08-21", "--dry-run"])
    assert args.published_date == "2026-08-21" and args.dry_run is True


def _workflow_text(name):
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _cron_minutes(text):
    """워크플로우의 `- cron: "M H * * ..."` 에서 UTC 분 단위 시각을 뽑습니다."""
    import re
    match = re.search(r'-\s*cron:\s*"(\d+)\s+(\d+)\s', text)
    assert match, f"cron 을 찾지 못했습니다: {text[:200]}"
    return int(match.group(2)) * 60 + int(match.group(1))


def _timeout_minutes(text):
    import re
    match = re.search(r"timeout-minutes:\s*(\d+)", text)
    assert match, "timeout-minutes 를 찾지 못했습니다"
    return int(match.group(1))


def test_usd_publish_workflow_runs_after_the_usd_fill_batch():
    """
    🔴 발행 배치가 체결 배치의 **타임아웃 상한 이후**에 시작하는지 — 순서가 뒤집히면 그날
    체결이 반영 안 된 하루 낡은 성적으로 순위표가 나갑니다. (원화 테스트
    `test_publish_workflow_runs_after_the_fill_batch` 와 같은 성격이고, 정확한 숫자가 아니라
    **관계**를 고정합니다 — 선행 배치 시각이 바뀌어도 이 테스트가 따라옵니다.)
    """
    fill = _workflow_text("duel_daily_us.yml")
    publish = _workflow_text("duel_publish_daily_us.yml")

    fill_end = _cron_minutes(fill) + _timeout_minutes(fill)
    publish_start = _cron_minutes(publish)
    assert publish_start >= fill_end, \
        f"USD 발행 배치({publish_start}분)가 체결 배치 종료 상한({fill_end}분)보다 앞섭니다"


def test_usd_publish_workflow_keeps_the_same_buffer_the_owner_confirmed_for_krw():
    """
    원화 트랙이 오너 확정으로 쓰는 여유(체결 배치 타임아웃 상한 + 30분)를 USD 에도 그대로
    적용했는지. 이 값이 조용히 좁아지면 두 배치가 부딪힐 여지가 늘어납니다.
    """
    krw_fill = _workflow_text("duel_daily.yml")
    krw_publish = _workflow_text("duel_publish_daily.yml")
    krw_buffer = _cron_minutes(krw_publish) - (_cron_minutes(krw_fill)
                                               + _timeout_minutes(krw_fill))
    assert krw_buffer == 30, f"원화 여유 폭이 바뀌었습니다({krw_buffer}분) — USD 도 다시 계산하세요"

    usd_fill = _workflow_text("duel_daily_us.yml")
    usd_publish = _workflow_text("duel_publish_daily_us.yml")
    usd_buffer = _cron_minutes(usd_publish) - (_cron_minutes(usd_fill)
                                               + _timeout_minutes(usd_fill))
    assert usd_buffer == krw_buffer, \
        f"USD 여유 폭({usd_buffer}분)이 원화({krw_buffer}분)와 다릅니다"


def test_usd_publish_workflow_finishes_before_the_next_usd_order_window_opens():
    """
    이 배치가 타임아웃을 다 써도 다음 USD 주문 접수 시작(16:00:01 KST = 07:00:01 UTC)보다
    앞서 끝나는지. 원화 트랙이 30분 버퍼를 택하면서 포기한 보장이 USD 에서는 지켜집니다.
    """
    publish = _workflow_text("duel_publish_daily_us.yml")
    end_utc = _cron_minutes(publish) + _timeout_minutes(publish)
    open_kst = duel_rules.ORDER_WINDOW_OPEN_TIME_USD
    open_utc = (open_kst.hour * 60 + open_kst.minute) - 9 * 60     # KST = UTC+9
    assert end_utc < open_utc, \
        f"발행 배치 종료({end_utc}분 UTC)가 주문 접수 시작({open_utc}분 UTC) 이후입니다"


def test_usd_publish_workflow_runs_the_usd_script_with_its_own_concurrency_group():
    text = _workflow_text("duel_publish_daily_us.yml")
    assert "python run_duel_publish_batch_us.py" in text
    assert "run_duel_publish_batch.py $ARGS" not in text
    # 같은 concurrency 그룹을 쓰면 서로 다른 표를 만지는 두 배치가 서로를 기다립니다.
    krw = _workflow_text("duel_publish_daily.yml")
    assert "group: duel-publish-batch-usd" in text
    assert "group: duel-publish-batch\n" in krw
    # 결과를 커밋하지 않으므로 쓰기 권한을 주지 않습니다(최소 권한 §0-3-9).
    assert "contents: read" in text


def test_usd_publish_workflow_runs_every_day_like_its_fill_batch():
    """
    선행 USD 체결 배치가 매일 도는데 발행만 평일이면, 주말에 체결된(=미국 금요일 마감)
    성적이 월요일까지 순위표에 안 실립니다.
    """
    import re
    fill = re.search(r'-\s*cron:\s*"[^"]*"', _workflow_text("duel_daily_us.yml")).group(0)
    publish = re.search(r'-\s*cron:\s*"[^"]*"', _workflow_text("duel_publish_daily_us.yml")).group(0)
    assert fill.endswith('* * *"'), fill
    assert publish.endswith('* * *"'), publish
