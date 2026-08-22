# tests/test_duel_scorecard_summary_card.py
"""
📊 "결투다!" 화면의 **내 성적표(실제 자산) 요약 카드** 오프라인 검증
   (네트워크 불필요 · Supabase 불필요)

2026-08-21 오너 결정 — "내 가상계좌" 비교 줄에 실제 증권계좌 자산("내 성적표")을 카드
하나로 나란히 붙입니다. 오너가 직접 단 **조건**이 있습니다:

    "예수금이 없는 매입원가 대비 수익률입니다 라고 써놓으면 될 것 같은데"

즉 이 카드는 **계산 방식이 다르다는 문장을 화면에 직접 달아두는 것**을 전제로 허용된
카드입니다. 결투 계좌 수익률은 매달 자동 입금 때문에 시간가중수익률(TWR)이고, 성적표는
예수금 개념이 없는 매입원가 대비 평가손익률이라 **두 숫자는 서로 비교할 수 없습니다**
(이 파일이 지키는 것이 바로 그 전제입니다 — `NOTICE_TWR` 과 같은 취지).

이 파일이 막으려는 사고 (전부 "조용히 틀리는" 종류입니다)
    ① 🔴 **수익률 식이 갈라지는 것** — 성적표 화면(`_render_currency_block()`)은
       `profit / base * 100`(base = 현재가를 아는 종목의 매입원가 합)으로 계산합니다.
       결투 화면이 자기 나름의 식을 새로 만들면 **같은 자산이 두 화면에서 다른 수익률**로
       보입니다(§0-3-10).
    ② 🔴 **없는 값을 0 으로 채우는 것** — 보유 종목이 하나도 없는 사용자에게 "0원 / 0%"
       카드를 그리면 "손익이 0" 이라는 거짓말이 됩니다(§0-1).
    ③ 🔴 **구분 문구가 사라지는 것** — 위 오너 조건 그 자체. 문구가 빠지면 두 수익률이
       비교 가능한 것처럼 읽힙니다.
    ④ 🔴 **원화·달러 합산** — §5-11-2. 환율 시계열이 없는 앱에서 두 통화를 더한 숫자는
       지어낸 값입니다. 두 통화 카드는 **완전히 독립된 두 번의 호출**이어야 합니다.
    ⑤ 🔴 **이벤트 루프 차단** — `fetch_holdings()` 는 동기 HTTP 왕복입니다. 반드시
       `run_blocking()` 으로 넘겨야 하고, 순수 계산인 `build_portfolio()` 는 그러면
       안 됩니다(스레드를 낭비할 뿐).

실행: pytest tests/test_duel_scorecard_summary_card.py -v
"""

import ast
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

from utils.scorecard_db import MARKET_KR, MARKET_US                      # noqa: E402

PAGE_PATH = REPO_ROOT / "web" / "pages" / "duel_page.py"
PAGE_SRC = PAGE_PATH.read_text(encoding="utf-8")
PAGE_TREE = ast.parse(PAGE_SRC)


# =============================================================================
# 0. 도우미 — 소스 구조 + 화면 스텁
# =============================================================================
def _functions():
    found = {}
    for node in ast.walk(PAGE_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


FUNCTIONS = _functions()
CARD = "_render_scorecard_summary_card"
# 🔴 통화별 얇은 창구 두 개 — 이 파일 규칙상 한 함수가 두 통화 상수를 함께 쓸 수 없어서
#    (`test_duel_page_usd.py::test_no_function_mixes_the_two_currency_constants`)
#    `_render_accounts()` 는 이 창구들을 통해 성적표 카드를 부릅니다. 본문은 공유합니다.
CARD_KRW = "_render_scorecard_summary_card_krw"
CARD_USD = "_render_scorecard_summary_card_usd"


def _accounts_branches():
    """`_render_accounts()` 를 (원화 전용 분기, 원화+달러 병기 분기) 노드 목록으로 나눕니다.

    원화 전용 분기는 `if not usd_by_window or usd_market is None:` 의 본문(끝에 `return`)
    이고, 그 `if` 문 **뒤에 오는 나머지 본문**이 병기 분기입니다.
    """
    node = FUNCTIONS["_render_accounts"]
    for index, statement in enumerate(node.body):
        if isinstance(statement, ast.If) and any(
                isinstance(inner, ast.Return) for inner in statement.body):
            return statement.body, node.body[index + 1:]
    raise AssertionError("_render_accounts() 의 원화 전용 분기를 찾지 못했습니다.")


def _calls_named(nodes, name):
    """주어진 노드들 안에서 `name(...)` 호출 노드를 전부 모읍니다."""
    found = []
    for node in nodes:
        for child in ast.walk(node):
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                    and child.func.id == name):
                found.append(child)
    return found


class _WidgetStub:
    """어떤 NiceGUI 위젯 흉내든 다 내는 객체 — 문자열 인자는 전부 `sink` 에 모읍니다.

    (`tests/test_duel_page_usd.py::_WidgetStub` 과 같은 발상·같은 이유 — 진짜 nicegui 는
    `asyncio.run()` 으로 만든 태스크에 슬롯 스택이 없으면 실패하고, 그 대체 클라이언트는
    프로세스당 한 번뿐이라 렌더 검사를 여러 개 돌릴 수 없습니다.)
    """

    def __init__(self, sink):
        object.__setattr__(self, "_sink", sink)

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        for value in args:
            if isinstance(value, str):
                self._sink.append(value)
        return self

    def __getattr__(self, _name):
        return self

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _UiStub:
    def __init__(self, sink):
        object.__setattr__(self, "_sink", sink)
        object.__setattr__(self, "_widget", _WidgetStub(sink))

    def __getattr__(self, _name):
        return self._widget


class _CardHarness:
    """`_render_scorecard_summary_card()` 를 **실제로 실행**하고 결과를 모읍니다.

    §0-1 — 보유 종목은 전부 합성 데이터이고 Supabase 에는 접속하지 않습니다. 집계는
    진짜 `utils/scorecard_db.build_portfolio()` 가 합니다(화면이 자기 식을 새로 만들지
    않았는지 보려면 진짜 집계 함수를 태워야 합니다).
    """

    def __init__(self, holdings, prices, market_code=MARKET_KR):
        self.holdings = holdings
        self.prices = prices
        self.market_code = market_code
        self.text = []                 # 화면에 나간 문자열
        self.metric_cards = []         # (라벨, 값, 델타)
        self.pct_inputs = []           # pct_text() 에 들어간 값
        self.info = []
        self.errors = []

    def __enter__(self):
        import web.pages.duel_page as page
        self.page = page
        self._saved = {
            name: getattr(page, name) for name in
            ("ui", "fetch_holdings", "metric_card", "pct_text", "info_banner", "error_banner")
        }

        real_pct_text = self._saved["pct_text"]

        def _fetch_holdings(_client, _user_id):
            return [dict(h) for h in self.holdings]

        def _metric_card(label, value, delta='', **kwargs):
            self.metric_cards.append((label, value, delta))
            self.text.extend([str(label), str(value), str(delta)])

        def _pct_text(value, *args, **kwargs):
            self.pct_inputs.append(value)
            return real_pct_text(value, *args, **kwargs)

        page.ui = _UiStub(self.text)
        page.fetch_holdings = _fetch_holdings
        page.metric_card = _metric_card
        page.pct_text = _pct_text
        page.info_banner = lambda text: (self.info.append(str(text)),
                                         self.text.append(str(text)))
        page.error_banner = lambda text: (self.errors.append(str(text)),
                                          self.text.append(str(text)))
        return self

    def __exit__(self, *_exc):
        for name, value in self._saved.items():
            setattr(self.page, name, value)
        return False

    def price_lookup(self):
        """카드가 인자로 받는 현재가 조회 함수 (2026-08-22 — 예전에는 market dict 였습니다).

        어느 목록에서 찾을지는 통화별 창구가 정하고, 카드 본문은 받은 함수를 그대로
        씁니다. 그래서 여기서도 dict 가 아니라 **조회 함수 하나**를 넘깁니다.
        """
        prices = self.prices

        def _lookup(market_code, ticker):
            if market_code != self.market_code:
                return None            # 시장이 다르면 값을 모른다 — 추정하지 않습니다.
            return prices.get(ticker)

        return _lookup

    def run(self, currency):
        asyncio.run(self.page._render_scorecard_summary_card(
            object(), "uid-1", currency, self.price_lookup()))
        return "\n".join(self.text)


KRW_HOLDINGS = [
    {"market": MARKET_KR, "ticker": "005930", "stock_name": "삼성전자",
     "quantity": 10, "avg_purchase_price": 70000},
    {"market": MARKET_KR, "ticker": "000660", "stock_name": "SK하이닉스",
     "quantity": 3, "avg_purchase_price": 200000},
]
KRW_PRICES = {"005930": 80000, "000660": 180000}

USD_HOLDINGS = [
    {"market": MARKET_US, "ticker": "AAPL", "stock_name": "Apple",
     "quantity": 4, "avg_purchase_price": 150.0},
]
USD_PRICES = {"AAPL": 200.0}


# =============================================================================
# 1. 숫자 — '내 성적표' 화면과 **같은 식**으로 계산합니다 (§0-3-10)
# =============================================================================
def test_priced_holdings_render_the_three_metric_cards_with_the_scorecard_formula():
    with _CardHarness(KRW_HOLDINGS, KRW_PRICES) as harness:
        harness.run("KRW")

    labels = [label for label, _value, _delta in harness.metric_cards]
    assert labels == ['매입원가 합계', '평가금액 합계', '평가손익'], (
        f"성적표 카드의 지표 구성이 '내 성적표' 화면과 다릅니다: {labels}"
    )

    # 테스트가 **독립적으로** 계산한 값과 맞는지 (화면 식을 그대로 베끼지 않습니다).
    cost = 10 * 70000 + 3 * 200000              # 1,300,000
    value = 10 * 80000 + 3 * 180000             # 1,340,000
    profit = value - cost                       # 40,000
    expected_pct = profit / cost * 100.0        # 전 종목 가격을 알므로 base == 매입원가 합

    assert harness.pct_inputs == [expected_pct], (
        f"수익률이 매입원가 대비 평가손익률이 아닙니다: {harness.pct_inputs} != {expected_pct}"
    )
    assert f'{cost:,}' in harness.metric_cards[0][1]
    assert f'{value:,}' in harness.metric_cards[1][1]
    assert f'{profit:,}' in harness.metric_cards[2][1]
    assert harness.metric_cards[2][2] == f'{expected_pct:+.2f}%'


def test_the_percentage_base_excludes_holdings_whose_price_is_unknown():
    """현재가를 모르는 종목은 분모(base)에서도 빠집니다 — 성적표 화면과 같은 규약."""
    holdings = KRW_HOLDINGS + [
        {"market": MARKET_KR, "ticker": "999999", "stock_name": "가격없는종목",
         "quantity": 5, "avg_purchase_price": 10000},
    ]
    with _CardHarness(holdings, KRW_PRICES) as harness:
        harness.run("KRW")

    base = 10 * 70000 + 3 * 200000              # 가격을 아는 종목만
    profit = (10 * 80000 + 3 * 180000) - base
    assert harness.pct_inputs == [profit / base * 100.0], (
        "가격을 모르는 종목의 매입원가가 수익률 분모에 섞여 들어갔습니다."
    )
    # 매입원가 '합계' 카드는 전 종목 기준이라 그 종목까지 포함합니다(성적표 화면과 동일).
    assert f'{base + 50000:,}' in harness.metric_cards[0][1]

    # 그리고 빠졌다는 사실을 화면에서 숨기지 않습니다(§0-1).
    assert harness.info, "현재가를 모르는 종목이 있는데 아무 안내도 하지 않았습니다."
    assert "999999" in harness.info[0]
    assert "지어내지 않습니다" in harness.info[0]


def test_a_portfolio_with_no_priced_holding_shows_dashes_instead_of_a_made_up_return():
    """가격을 아는 종목이 하나도 없으면 '—' 입니다 — 0% 를 만들어내지 않습니다(§0-1)."""
    with _CardHarness(KRW_HOLDINGS, {}) as harness:
        harness.run("KRW")

    labels = [label for label, _v, _d in harness.metric_cards]
    assert labels == ['매입원가 합계', '평가금액 합계', '평가손익']
    assert harness.metric_cards[1][1] == '—'
    assert harness.metric_cards[2][1] == '—'
    assert harness.pct_inputs == [], (
        "평가금액을 모르는데 수익률을 계산했습니다 — None 에서 숫자를 만들면 안 됩니다."
    )


# =============================================================================
# 2. 빈 상태 — 없는 값을 0 으로 채우지 않습니다 (§0-1)
# =============================================================================
def test_empty_holdings_render_the_empty_state_and_no_metric_card_at_all():
    with _CardHarness([], KRW_PRICES) as harness:
        blob = harness.run("KRW")

    assert "아직 등록된 보유 종목이 없습니다" in blob
    assert "내 성적표" in blob
    assert harness.metric_cards == [], (
        f"보유 종목이 없는데 지표 카드를 그렸습니다: {harness.metric_cards} — "
        "0원/0% 는 '등록된 것이 없음'과 완전히 다른 말입니다(§0-1)."
    )
    assert "0원" not in blob and "0.00%" not in blob
    assert not harness.errors


def test_a_currency_with_no_holdings_falls_back_to_the_same_empty_state():
    """원화 종목만 가진 사용자의 **달러 카드** — 그룹 자체가 없는 경우입니다."""
    with _CardHarness(KRW_HOLDINGS, KRW_PRICES) as harness:
        blob = harness.run("USD")

    assert "아직 등록된 보유 종목이 없습니다" in blob
    assert harness.metric_cards == [], (
        "달러 보유 종목이 하나도 없는데 달러 지표 카드가 그려졌습니다."
    )


def test_a_failed_holdings_query_is_reported_instead_of_being_shown_as_empty():
    """조회 실패를 '보유 종목 0건'으로 위장하지 않습니다(§0-1 · §0-3-4)."""
    import web.pages.duel_page as page

    with _CardHarness([], KRW_PRICES) as harness:
        def _boom(_client, _user_id):
            raise RuntimeError("postgrest 500")

        page.fetch_holdings = _boom
        blob = harness.run("KRW")

    assert "불러오지 못했습니다" in blob, (
        f"조회가 실패했는데 화면이 아무 말도 하지 않습니다: {blob!r}"
    )
    assert "아직 등록된 보유 종목이 없습니다" not in blob, (
        "조회 실패가 '보유 종목 0건'으로 위장됐습니다 — 완전히 다른 상태입니다(§0-1)."
    )
    assert harness.metric_cards == []
    assert "postgrest" not in blob, "예외 원문이 화면에 그대로 나갔습니다(§0-3-4)."


# =============================================================================
# 3. 🔴 구분 문구 — 이 카드가 존재해도 되는 **전제 조건** (2026-08-21 오너 확정)
# =============================================================================
def test_the_caption_distinguishes_cost_basis_return_from_twr():
    with _CardHarness(KRW_HOLDINGS, KRW_PRICES) as harness:
        blob = harness.run("KRW")

    for fragment in ("예수금", "매입원가 대비", "TWR", "비교하지"):
        assert fragment in blob, (
            f"구분 문구에서 '{fragment}' 가 빠졌습니다 — 이 문장이 있다는 조건으로 허용된 "
            "카드입니다(오너 확정 2026-08-21). 없으면 두 수익률이 비교 가능한 것처럼 읽힙니다."
        )
    assert "시간가중수익률" in blob


def test_the_caption_also_appears_next_to_the_dash_only_numbers():
    """숫자 카드가 나가는 경우에는 항상 함께 나갑니다(값이 '—' 여도 마찬가지)."""
    with _CardHarness(KRW_HOLDINGS, {}) as harness:
        blob = harness.run("KRW")

    assert harness.metric_cards, "이 경우에는 지표 카드가 나가야 합니다."
    assert "매입원가 대비" in blob and "비교하지" in blob


# =============================================================================
# 4. 배선 — 두 분기 모두에서 불리는가 (소스 검사)
# =============================================================================
def test_the_scorecard_card_is_rendered_in_both_branches_of_render_accounts():
    krw_only, combined = _accounts_branches()

    krw_calls = _calls_named(krw_only, CARD_KRW)
    assert len(krw_calls) == 1, (
        f"원화 전용 분기에서 {CARD_KRW}() 호출이 1건이 아닙니다: {len(krw_calls)}"
    )
    args = [ast.unparse(a) for a in krw_calls[0].args]
    assert args == ["client", "user_id", "market"], args
    assert not _calls_named(krw_only, CARD_USD), (
        "원화 전용 분기(= 달러 계좌가 없는 사용자)에서 달러 성적표 카드를 그리고 있습니다."
    )

    combined_krw = _calls_named(combined, CARD_KRW)
    combined_usd = _calls_named(combined, CARD_USD)
    assert len(combined_krw) == 1 and len(combined_usd) == 1, (
        f"원화+달러 병기 분기의 성적표 카드 호출이 각 1건이 아닙니다: "
        f"{len(combined_krw)} / {len(combined_usd)}"
    )
    assert [ast.unparse(a) for a in combined_krw[0].args] == ["client", "user_id", "market"]
    assert [ast.unparse(a) for a in combined_usd[0].args] == ["client", "user_id", "usd_market"]

    # 두 창구는 공유 본문을 통화 상수 하나만 바꿔 부르는 얇은 함수여야 합니다(§0-3-10).
    for wrapper, constant in ((CARD_KRW, "CURRENCY"), (CARD_USD, "CURRENCY_USD")):
        inner = _calls_named([FUNCTIONS[wrapper]], CARD)
        assert len(inner) == 1, f"{wrapper}() 이 {CARD}() 를 부르지 않습니다."
        assert [ast.unparse(a) for a in inner[0].args] == [
            "client", "user_id", constant, "price_lookup"], wrapper

    # 성적표 칸이 창유형 칸들과 **같은 배치 스타일**을 쓰는지(카드 폭이 혼자 달라지지 않게).
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS["_render_accounts"])
    grid_style = ('flex: 1 1 320px; min-width: 0; display: grid; gap: 12px; '
                  'align-content: start;')
    assert src.count(grid_style) == 2, (
        "성적표 칸과 창유형 칸의 배치 스타일이 다릅니다(같은 grid 칸이어야 합니다)."
    )
    # 원화 전용 분기의 카드 줄 클래스는 그대로여야 합니다(기존 화면 회귀).
    assert "'w-full gap-4 items-stretch'" in ast.unparse(ast.Module(body=list(krw_only),
                                                                    type_ignores=[]))


def test_the_usd_scorecard_card_is_guarded_by_usd_market_being_present():
    _krw_only, combined = _accounts_branches()
    usd_call = _calls_named(combined, CARD_USD)[0]

    guarded = False
    for node in combined:
        for child in ast.walk(node):
            if isinstance(child, ast.If) and usd_call in list(ast.walk(child)):
                if "usd_market" in ast.unparse(child.test):
                    guarded = True
    assert guarded, (
        "달러 성적표 카드가 `usd_market` 존재 확인 없이 그려집니다."
    )


# =============================================================================
# 5. 🔴 §5-11-2 — 원화 값과 달러 값이 한 산술식에 들어가는 자리가 없는가
# =============================================================================
# 금액이 들어 있을 수 있는 이름들 — 이 이름이 낀 산술식이 `_render_accounts()` 에
# 하나라도 생기면 두 통화를 더할 여지가 열린 것입니다.
MONEY_TOKENS = ("total_value", "total_cost", "total_profit", "profit", "cash",
                "position_value", "market_value", "amount", "group", "sum(")

# 이 함수에 원래부터 있던 산술식은 **창유형 코드(M1/M3/M6) 목록 이어붙이기 둘뿐**입니다.
# 금액이 아니라 문자열 목록이라 통화와 아무 상관이 없습니다.
PREEXISTING_BINOPS = sorted([
    "known + sorted(set(extra), key=str)",
    "list(krw_by_window) + list(usd_by_window)",
])


def test_no_expression_in_render_accounts_mixes_a_krw_value_with_a_usd_value():
    node = FUNCTIONS["_render_accounts"]

    money_math = [
        ast.unparse(child) for child in ast.walk(node)
        if isinstance(child, (ast.BinOp, ast.AugAssign))
        and any(token in ast.unparse(child) for token in MONEY_TOKENS)
    ]
    assert not money_math, (
        f"계좌 비교 영역에 금액 계산식이 생겼습니다: {money_math} — 이 함수는 원화 카드와 "
        "달러 카드를 나란히 부르기만 해야 하고, 두 통화 값이 만나는 자리를 만들면 안 됩니다"
        "(§5-11-2 · §0-1: 환율 시계열이 없으므로 더한 숫자는 지어낸 값입니다)."
    )

    binops = sorted(ast.unparse(c) for c in ast.walk(node) if isinstance(c, ast.BinOp))
    assert binops == PREEXISTING_BINOPS, (
        f"`_render_accounts()` 의 산술식이 바뀌었습니다: {binops} — 원래 있던 것은 "
        f"{PREEXISTING_BINOPS}(창유형 코드 목록 이어붙이기) 하나뿐입니다."
    )

    # 두 호출이 **서로 독립된 두 문장**인지 (한쪽 결과를 다른 쪽에 넘기지 않았는지).
    _krw_only, combined = _accounts_branches()
    for call in _calls_named(combined, CARD_KRW) + _calls_named(combined, CARD_USD):
        for arg in call.args:
            assert isinstance(arg, ast.Name), (
                f"{CARD}() 에 계산식이 인자로 들어갔습니다: {ast.unparse(arg)}"
            )


def test_the_card_function_itself_knows_only_one_currency():
    """카드 함수는 통화 인자 하나만 받고, 본문에 달러 전용 이름이 한 개도 없습니다."""
    node = FUNCTIONS[CARD]
    args = [a.arg for a in node.args.args]
    assert args == ["client", "user_id", "currency", "price_lookup"], args

    src = ast.get_source_segment(PAGE_SRC, node)
    body_src = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#"))
    for banned in ("CURRENCY_USD", "usd_market", "_usd("):
        assert banned not in body_src, (
            f"카드 함수 본문에 달러 전용 이름 '{banned}' 이 있습니다 — 이 함수는 인자로 받은 "
            "통화 하나만 다뤄야 두 통화가 섞일 자리가 없습니다."
        )

    # 산술식은 성적표 화면과 같은 `profit / base * 100` 하나뿐이어야 합니다.
    # (중첩된 조각 `profit / base` 는 같은 식의 일부이므로 최상위 식만 셉니다.)
    nested = {id(part) for c in ast.walk(node) if isinstance(c, ast.BinOp)
              for part in (c.left, c.right)}
    binops = [ast.unparse(c) for c in ast.walk(node)
              if isinstance(c, ast.BinOp) and id(c) not in nested]
    assert binops == ["profit / base * 100"], (
        f"카드 함수에 예상 밖의 계산식이 있습니다: {binops} — 수익률 식은 "
        "scorecard_page.py::_render_currency_block() 과 글자 그대로 같아야 합니다(§0-3-10)."
    )


def test_the_card_uses_the_same_group_fields_as_the_scorecard_page():
    """'내 성적표' 화면이 쓰는 것과 **같은 키**를 읽는지 — 식이 갈라지는 첫 징후를 잡습니다."""
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[CARD])
    for key in ('"total_cost"', '"total_cost_priced"', '"total_value"', '"total_profit"',
                '"unpriced_count"', '"unpriced_tickers"', '"rows"'):
        assert f'group[{key}]' in src, f"group[{key}] 을 읽지 않습니다."


# =============================================================================
# 6. 🔴 이벤트 루프 — 조회는 스레드로, 순수 계산은 그대로
# =============================================================================
def test_fetch_holdings_goes_through_run_blocking_and_build_portfolio_does_not():
    src = ast.get_source_segment(PAGE_SRC, FUNCTIONS[CARD])
    assert "run_blocking(fetch_holdings, client, user_id)" in src, (
        "fetch_holdings() 를 run_blocking() 으로 넘기지 않았습니다 — 동기 HTTP 왕복이라 "
        "이벤트 루프 위에서 부르면 접속자 전원이 멈춥니다(web/blocking.py)."
    )

    node = FUNCTIONS[CARD]
    run_blocking_targets = [
        child.args[0].id
        for child in ast.walk(node)
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            and child.func.id == "run_blocking" and child.args
            and isinstance(child.args[0], ast.Name))
    ]
    assert run_blocking_targets == ["fetch_holdings"], run_blocking_targets
    assert "build_portfolio" not in run_blocking_targets, (
        "build_portfolio() 는 입출력이 없는 순수 계산입니다 — 스레드로 넘길 이유가 없습니다."
    )

    # 그리고 실제로 **직접** 불리는지.
    direct = [c for c in ast.walk(node)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
              and c.func.id == "build_portfolio"]
    assert len(direct) == 1, "build_portfolio() 직접 호출이 정확히 1건이어야 합니다."

    # 조회 함수를 이벤트 루프 위에서 직접 부른 자리가 없어야 합니다.
    bad = [c for c in ast.walk(node)
           if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
           and c.func.id == "fetch_holdings"]
    assert not bad, "fetch_holdings() 를 직접 호출한 자리가 있습니다."


def test_the_page_imports_the_scorecard_functions_instead_of_reimplementing_them():
    import web.pages.duel_page as page
    import utils.scorecard_db as scorecard_db

    assert page.fetch_holdings is scorecard_db.fetch_holdings
    assert page.build_portfolio is scorecard_db.build_portfolio


# =============================================================================
# 7. 두 통화 카드가 서로의 숫자를 물들이지 않는지 (실제 실행)
# =============================================================================
def test_krw_and_usd_cards_are_two_independent_calls_with_per_currency_totals():
    holdings = KRW_HOLDINGS + USD_HOLDINGS

    with _CardHarness(holdings, KRW_PRICES, market_code=MARKET_KR) as harness:
        harness.run("KRW")
    krw_cards = list(harness.metric_cards)

    with _CardHarness(holdings, USD_PRICES, market_code=MARKET_US) as harness:
        harness.run("USD")
    usd_cards = list(harness.metric_cards)

    krw_cost = 10 * 70000 + 3 * 200000
    usd_cost = 4 * 150.0
    assert f'{krw_cost:,}' in krw_cards[0][1]
    assert "150" not in krw_cards[0][1] and "600" not in krw_cards[0][1], (
        f"원화 카드에 달러 금액이 섞였습니다: {krw_cards[0]}"
    )
    assert "600" in usd_cards[0][1], usd_cards[0]
    assert f'{krw_cost:,}' not in usd_cards[0][1], (
        f"달러 카드에 원화 금액이 섞였습니다: {usd_cards[0]}"
    )
    # 합계가 두 통화를 더한 값이 아닌지 — 가장 직접적인 회귀.
    assert f'{krw_cost + usd_cost:,.0f}' not in krw_cards[0][1]
