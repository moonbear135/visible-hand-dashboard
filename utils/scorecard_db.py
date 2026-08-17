# utils/scorecard_db.py
"""
📊 "내 성적표" 모듈 — 데이터 계층 단일 출처 (Supabase 래퍼 + 순수 계산 로직)

SCORECARD_WORK_ORDER.md §6-2 에 따라 만든 모듈입니다.
화면(`views/scorecard_view.py`)은 Supabase 호출을 직접 하지 않고 **전부 이 모듈을 통해서만**
접근합니다(§4-3 계층 분리).

이 파일은 크게 네 부분으로 나뉩니다.
    A. 상수 / 정규화        — 시장·통화·티커 (원/달러 혼용 차단)
    B. 순수 계산 로직        — 수량 가중평균, 보유 평가, 비중 계산
                              → **Supabase 클라이언트 없이 단독 호출·테스트 가능**
    C. 기존 PEGY 스냅샷 조회 — data/*.json 을 **읽기 전용**으로 재사용
    D. Supabase 래퍼        — 클라이언트 생성, 회원가입/로그인/로그아웃, holdings CRUD

⚠️ 크레덴셜 규칙 (ENGINEERING_SPEC.md §0-1 / 작업지시서 §4-2)
    - `SUPABASE_URL` / `SUPABASE_ANON_KEY` 는 `st.secrets`(Streamlit Cloud → Settings →
      Secrets) 또는 동명의 환경변수에서만 읽습니다. 소스코드에 값을 적지 않습니다.
    - anon key 는 **설계상 클라이언트에 노출되는 게 정상인 키**라서 KRX 인증키와 성격이
      다릅니다. 실제 방어선은 DB의 Row Level Security(`sql/scorecard_schema.sql`)입니다.
      그래도 로그·에러메시지에 키 값을 찍지 않습니다(습관적 유출 방지).
    - `service_role` 키는 RLS를 통째로 우회하므로 이 앱에 절대 넣지 않습니다.
    - 비밀번호는 Supabase Auth 가 처리합니다. 이 코드가 평문 비밀번호를 저장하거나
      로그로 남기는 경로는 존재하지 않습니다.

⚠️ 지어내지 않기 (§0-1)
    - 현재가는 사용자가 입력한 매입가가 아니라 **기존 수집 스냅샷의 실측 price** 만 씁니다.
    - 유니버스(코스피 상위200 / 미국 상위550) 밖 종목은 현재가를 `None` 으로 두고
      화면에 "현재가 없음"으로 정직하게 표시합니다. 추정하지 않습니다.
    - Supabase 호출 실패는 조용히 빈 값으로 넘기지 않고 `ScorecardError` 로 올려
      화면이 사용자에게 그대로 보여주게 합니다.

⚠️ 환율 변환 없음
    - 원화 종목과 달러 종목은 끝까지 분리해서 계산·표시합니다. 이 파일 어디에도
      환율을 곱하는 코드는 없습니다(합계도 통화별로 따로 냅니다).
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass

# streamlit 은 st.secrets 를 읽을 때만 씁니다. 오프라인 테스트(스트림릿 미설치)에서도
# 이 모듈을 그대로 import 할 수 있어야 하므로 선택적 의존성으로 감쌉니다.
try:  # pragma: no cover - 환경에 따라 갈리는 import
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:  # pragma: no cover
    st = None
    STREAMLIT_AVAILABLE = False

# supabase 파이썬 패키지도 선택적 의존성입니다.
# requirements.txt 에 추가돼 있지만, 아직 설치 안 된 환경(또는 설치 실패)에서도
# **기존 두 모듈(코스피/미국주식)이 정상 동작해야** 하므로 여기서 죽으면 안 됩니다.
try:  # pragma: no cover
    from supabase import create_client as _supabase_create_client
    SUPABASE_PACKAGE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _supabase_create_client = None
    SUPABASE_PACKAGE_AVAILABLE = False


class ScorecardError(RuntimeError):
    """내 성적표 데이터 계층에서 사용자에게 보여줄 오류(조용히 삼키지 않습니다)."""


# =============================================================================
# A. 상수 / 정규화
# =============================================================================

MARKET_KR = "KR"
MARKET_US = "US"
MARKETS = (MARKET_KR, MARKET_US)

CURRENCY_KRW = "KRW"
CURRENCY_USD = "USD"

# 시장 → 통화. 이 매핑이 원/달러 혼용을 막는 단일 출처입니다(DB의 CHECK 제약과 동일).
CURRENCY_BY_MARKET = {
    MARKET_KR: CURRENCY_KRW,
    MARKET_US: CURRENCY_USD,
}

MARKET_LABELS = {
    MARKET_KR: "🇰🇷 한국 (원화)",
    MARKET_US: "🇺🇸 미국 (달러)",
}

CURRENCY_SYMBOLS = {
    CURRENCY_KRW: "원",
    CURRENCY_USD: "$",
}

HOLDINGS_TABLE = "holdings"
PROFILES_TABLE = "profiles"

# 화면에 반드시 띄워야 하는 고지 문구(작업지시서 §2-6). 화면 코드가 이 상수를 씁니다.
NO_FX_CONVERSION_NOTICE = (
    "⚠️ 환율 변환 없음 — 한국 종목은 원화(₩), 미국 종목은 달러($) 그대로 계산합니다. "
    "두 통화의 금액을 하나로 합산한 '총 자산' 숫자는 어디에도 표시하지 않습니다."
)

# 2026-08-11 오너 요청 — 수수료·세금(거래수수료, 증권거래세, 양도소득세, 배당소득세 등)은
# 전혀 반영하지 않은 "순수 매수가 vs 현재가"만의 비교라는 걸 반드시 상시 고지합니다.
# 실제 수익률과 화면에 보이는 수익률의 괴리가 클 수 있어(특히 단타·소액 거래일수록), 절대
# 누락하면 안 되는 경고입니다.
NO_FEES_TAXES_NOTICE = (
    "⚠️ 수수료·세금 미반영 — 거래수수료, 증권거래세, 양도소득세·배당소득세 등은 전혀 "
    "고려하지 않은 **순수 매수가 대비 현재가**만의 비교입니다. 실제 손익과는 차이가 있을 "
    "수 있으니 참고용으로만 봐주세요."
)


def normalize_market(market):
    """'kr'/'KR'/'us'/'US' 를 표준 시장코드로. 모르는 값은 지어내지 않고 예외."""
    if market is None:
        raise ValueError("시장(market)이 지정되지 않았습니다.")
    value = str(market).strip().upper()
    if value in MARKETS:
        return value
    raise ValueError(f"알 수 없는 시장 코드입니다: {market!r} (허용값: {', '.join(MARKETS)})")


def currency_for_market(market):
    """시장코드 → 통화코드. 통화는 사용자가 고르는 값이 아니라 시장에서 파생됩니다."""
    return CURRENCY_BY_MARKET[normalize_market(market)]


def normalize_ticker(market, ticker):
    """
    종목 코드 정규화.
      - 한국: 6자리 숫자 코드. `5930` 처럼 앞의 0이 떨어진 입력을 `005930` 으로 복원합니다.
              (스냅샷 JSON의 `code` 키가 앞자리 0을 보존한 문자열이라 맞춰야 조회됩니다)
      - 미국: 티커 대문자. 공백 제거. `BRK.B` 같은 점은 그대로 둡니다(스냅샷 표기 그대로).
    """
    market = normalize_market(market)
    if ticker is None:
        raise ValueError("종목 코드/티커가 비어 있습니다.")
    value = str(ticker).strip()
    if not value:
        raise ValueError("종목 코드/티커가 비어 있습니다.")
    if market == MARKET_KR:
        value = value.upper()
        # 실제 스냅샷에는 `005930` 같은 순수 숫자 코드 외에 우선주·신형우선주의
        # `00680K` · `0126Z0` 같은 **영숫자 6자리** 코드도 들어 있습니다(실측 확인).
        # 숫자로 시작하는 6자리 이하 영숫자만 0으로 채워 6자리로 맞춥니다.
        if re.fullmatch(r"[0-9][0-9A-Z]{0,5}", value):
            return value.zfill(6)
        if value.isdigit() and len(value) > 6:
            raise ValueError(f"한국 종목코드는 6자리입니다: {ticker!r}")
        # 그 외(예: 사용자가 종목명을 넣음)는 손대지 않고 그대로 돌려주고,
        # 유니버스 조회에서 '없음'으로 처리되게 둡니다(임의 변환으로 지어내지 않음).
        return value
    return value.upper()


def format_amount(value, currency, decimals=None):
    """
    금액 표기. **환율 변환은 하지 않고** 통화 기호만 붙입니다.

    ⚠️ 원화 표기 반올림 정책: 마인드맵 예시(10주 100만원 + 3주 21만원 → 평균 93,076원)는
       1,210,000 ÷ 13 = 93,076.923... 의 **소수점 절사(내림)** 표기입니다. 오너 예시와
       화면 숫자가 어긋나지 않도록 원화는 내림으로 표기합니다.
       (저장·계산은 항상 전체 정밀도로 하고, 내림은 표시 단계에서만 적용합니다.)
    """
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if currency == CURRENCY_KRW:
        digits = 0 if decimals is None else decimals
        if digits == 0:
            number = math.floor(number) if number >= 0 else -math.floor(-number)
        return f"{number:,.{digits}f}원"
    digits = 2 if decimals is None else decimals
    return f"${number:,.{digits}f}"


# =============================================================================
# B. 순수 계산 로직 (Supabase 없이 단독 호출 가능)
# =============================================================================

def _positive_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}이(가) 숫자가 아닙니다: {value!r}")
    if not math.isfinite(number):
        raise ValueError(f"{label}이(가) 유효한 숫자가 아닙니다: {value!r}")
    return number


def make_lot(market, ticker, quantity, purchase_price, stock_name=None):
    """
    입력 1건(= 증권사 계좌 하나의 매수분, 이하 '로트')을 검증해 표준 dict 로 만듭니다.
    수량 ≤ 0, 매입가 < 0 은 저장하지 않고 예외로 막습니다(잘못된 값이 조용히 들어가면
    평균단가 전체가 오염됩니다).
    """
    market = normalize_market(market)
    ticker = normalize_ticker(market, ticker)
    quantity = _positive_number(quantity, "수량")
    price = _positive_number(purchase_price, "매입가")
    if quantity <= 0:
        raise ValueError(f"수량은 0보다 커야 합니다: {quantity}")
    if price < 0:
        raise ValueError(f"매입가는 0 이상이어야 합니다: {price}")
    name = (str(stock_name).strip() if stock_name else "") or None
    return {
        "market": market,
        "ticker": ticker,
        "stock_name": name,
        "quantity": quantity,
        "avg_purchase_price": price,
        "currency": currency_for_market(market),
    }


def weighted_average_price(lots):
    """
    수량 가중평균 매입가.

    마인드맵 예시:
        A증권 10주 @100,000원(총 100만원) + B증권 3주 @70,000원(총 21만원)
        → 13주 / 총 1,210,000원 → 평균 93,076.923...원 (화면 표기는 93,076원, 내림)

    반환: (총수량, 가중평균단가, 총매입금액)
    ⚠️ 서로 다른 통화가 섞여 들어오면 계산하지 않고 예외를 던집니다(환율 변환 금지).
    """
    if not lots:
        raise ValueError("가중평균을 계산할 입력(로트)이 없습니다.")
    currencies = {lot.get("currency") or currency_for_market(lot["market"]) for lot in lots}
    if len(currencies) > 1:
        raise ValueError(
            f"통화가 다른 보유분은 합칠 수 없습니다(환율 변환 금지): {sorted(currencies)}"
        )
    total_qty = 0.0
    total_cost = 0.0
    for lot in lots:
        qty = _positive_number(lot["quantity"], "수량")
        price = _positive_number(lot["avg_purchase_price"], "매입가")
        if qty <= 0:
            raise ValueError(f"수량은 0보다 커야 합니다: {qty}")
        total_qty += qty
        total_cost += qty * price
    if total_qty <= 0:
        raise ValueError("총수량이 0 이하라 평균단가를 계산할 수 없습니다.")
    return total_qty, total_cost / total_qty, total_cost


def merge_lot_into_holding(existing, lot):
    """
    기존 보유 1행 + 새 로트 → 가중평균으로 재계산된 보유 1행.
    `existing` 이 None 이면 새 로트가 그대로 첫 행이 됩니다.
    종목명은 기존 값을 유지하되, 비어 있으면 새 입력값으로 채웁니다.
    """
    lot = dict(lot)
    if existing is None:
        return dict(lot)
    if normalize_market(existing["market"]) != lot["market"] or \
            normalize_ticker(existing["market"], existing["ticker"]) != lot["ticker"]:
        raise ValueError("다른 종목끼리는 합칠 수 없습니다.")
    total_qty, avg_price, _ = weighted_average_price([existing, lot])
    merged = dict(existing)
    merged["quantity"] = total_qty
    merged["avg_purchase_price"] = avg_price
    merged["currency"] = currency_for_market(lot["market"])
    merged["stock_name"] = existing.get("stock_name") or lot.get("stock_name")
    return merged


def aggregate_lots(lots):
    """
    여러 로트(여러 증권사 계좌) → 종목별 1행으로 통합.
    같은 (시장, 티커)는 수량 가중평균으로 합쳐집니다. 입력 순서에 결과가 좌우되지 않습니다.
    """
    merged = {}
    order = []
    for raw in lots:
        lot = make_lot(
            raw["market"], raw["ticker"], raw["quantity"], raw["avg_purchase_price"],
            raw.get("stock_name"),
        )
        key = (lot["market"], lot["ticker"])
        if key not in merged:
            order.append(key)
            merged[key] = lot
        else:
            merged[key] = merge_lot_into_holding(merged[key], lot)
    return [merged[key] for key in order]


def split_by_currency(holdings):
    """
    보유 목록을 통화별로 분리합니다(원화 리스트 / 달러 리스트).
    작업지시서 §2-6 "한국/미국 종목 섹터 분리 관리" 의 구현부이며,
    이후 모든 합계·비중 계산은 이 분리된 그룹 안에서만 이뤄집니다.
    """
    groups = {}
    for holding in holdings:
        currency = holding.get("currency") or currency_for_market(holding["market"])
        groups.setdefault(currency, []).append(holding)
    return groups


def evaluate_holding(holding, current_price):
    """
    보유 1행 평가. `current_price` 가 None 이면(유니버스 밖 종목 등) 평가금액·수익을
    **계산하지 않고 None 으로 둡니다** — 매입가를 현재가로 대신 쓰는 짓은 하지 않습니다(§0-1).
    """
    market = normalize_market(holding["market"])
    currency = holding.get("currency") or currency_for_market(market)
    quantity = _positive_number(holding["quantity"], "수량")
    avg_price = _positive_number(holding["avg_purchase_price"], "매입가")
    cost = quantity * avg_price

    row = {
        "market": market,
        "ticker": normalize_ticker(market, holding["ticker"]),
        "stock_name": holding.get("stock_name"),
        "currency": currency,
        "quantity": quantity,
        "avg_purchase_price": avg_price,
        "cost": cost,
        "current_price": None,
        "market_value": None,
        "profit": None,
        "profit_pct": None,
        "price_available": False,
        "id": holding.get("id"),
    }
    if current_price is None:
        return row
    price = _positive_number(current_price, "현재가")
    row["current_price"] = price
    row["market_value"] = quantity * price
    row["profit"] = row["market_value"] - cost
    row["profit_pct"] = (row["profit"] / cost * 100.0) if cost > 0 else None
    row["price_available"] = True
    return row


def build_portfolio(holdings, price_lookup):
    """
    보유 목록 → 통화별 포트폴리오 요약.

    price_lookup: (market, ticker) -> 현재가 또는 None 을 돌려주는 함수.
                  (유니버스 스냅샷 조회를 주입받는 형태라 테스트에서 합성 데이터로 대체 가능)

    반환 구조:
        {
          "KRW": {
             "currency": "KRW",
             "rows": [...],                 # 평가 결과 행
             "total_cost": float,           # 매입원가 합 (전 종목)
             "total_value": float|None,     # 현재가를 아는 종목만의 평가금액 합
             "total_profit": float|None,
             "priced_count": int, "unpriced_count": int,
             "unpriced_tickers": [...],     # 현재가를 모르는 종목(정직하게 분리 표시)
          },
          "USD": {...}
        }

    ⚠️ 비중(weight_pct)은 **현재가를 아는 종목들의 평가금액 합**을 분모로 씁니다.
       현재가를 모르는 종목은 비중 None 으로 두고 별도로 표시합니다(0%로 속이지 않음).
    ⚠️ 수익 비중(profit_share_pct)은 **이익이 난 종목들의 이익 합**만을 분모로 씁니다.
       손실 종목을 원형차트에 음수 조각으로 넣을 수는 없기 때문이며, 손실 종목은
       profit_share_pct=None 으로 두고 화면에서 따로 표로 보여줍니다.
    """
    result = {}
    for currency, group in split_by_currency(holdings).items():
        rows = []
        for holding in group:
            price = price_lookup(holding["market"], holding["ticker"])
            rows.append(evaluate_holding(holding, price))

        priced = [r for r in rows if r["price_available"]]
        total_value = sum(r["market_value"] for r in priced) if priced else None
        total_cost_priced = sum(r["cost"] for r in priced) if priced else None
        positive_profit_sum = sum(r["profit"] for r in priced if r["profit"] and r["profit"] > 0)

        for row in rows:
            if row["price_available"] and total_value:
                row["weight_pct"] = row["market_value"] / total_value * 100.0
            else:
                row["weight_pct"] = None
            if row["price_available"] and row["profit"] is not None and row["profit"] > 0 \
                    and positive_profit_sum > 0:
                row["profit_share_pct"] = row["profit"] / positive_profit_sum * 100.0
            else:
                row["profit_share_pct"] = None

        result[currency] = {
            "currency": currency,
            "rows": rows,
            "total_cost": sum(r["cost"] for r in rows),
            "total_cost_priced": total_cost_priced,
            "total_value": total_value,
            "total_profit": (total_value - total_cost_priced) if priced else None,
            "total_positive_profit": positive_profit_sum,
            "priced_count": len(priced),
            "unpriced_count": len(rows) - len(priced),
            "unpriced_tickers": [r["ticker"] for r in rows if not r["price_available"]],
        }
    return result


# 2026-08-11 오너 요청 — 보유종목 표에 정렬(오름차순/내림차순) 기능. 화면에 보여줄 라벨과
# build_portfolio() 가 만든 행 딕셔너리의 실제 키를 한 곳에서 짝지어둡니다(화면 쪽 selectbox
# 옵션도 이 목록에서 그대로 뽑아 씁니다 — 문자열 두 곳에 따로 안 둠).
SORT_FIELD_OPTIONS = [
    ("종목명", "_label"),
    ("수량", "quantity"),
    ("평균매입가", "avg_purchase_price"),
    ("현재가", "current_price"),
    ("평가손익", "profit"),
    ("수익률", "profit_pct"),
    ("비중", "weight_pct"),
]


def sort_holding_rows(rows, field, ascending=True):
    """
    보유 종목 표를 지정한 필드로 정렬합니다(원본 리스트는 바꾸지 않고 새 리스트를 돌려줍니다).

    ⚠️ §0-1: 현재가를 모르는 종목은 평가손익·수익률·비중이 전부 None 입니다. 정렬 방향을
    바꿀 때마다 그 종목들이 위로 갔다 아래로 갔다 하면 혼란스럽고, 없는 값에 순위를 매기는
    것 자체가 지어내는 셈이라 — **값이 없는 행은 오름차순/내림차순과 무관하게 항상 맨 뒤**에
    둡니다.
    """
    def key_of(row):
        if field == "_label":
            return row.get("stock_name") or row.get("ticker") or ""
        return row.get(field)

    with_value = [r for r in rows if key_of(r) is not None]
    without_value = [r for r in rows if key_of(r) is None]
    with_value.sort(key=key_of, reverse=not ascending)
    return with_value + without_value


# =============================================================================
# C. 기존 PEGY 스냅샷 조회 (읽기 전용 재사용)
# =============================================================================
#  data/kospi200_pegy_latest.json  → 조회 키 `code`   (6자리 문자열, 앞자리 0 보존)
#  data/us_stocks_latest.json      → 조회 키 `symbol` (티커)
#  ⚠️ 이 두 파일은 기존 크롤링 파이프라인의 산출물입니다. 내 성적표는 **읽기만** 합니다
#     (이 파일 어디에도 두 파일을 여는 'w' 모드가 없습니다).
# =============================================================================

SNAPSHOT_FILENAMES = {
    MARKET_KR: "kospi200_pegy_latest.json",
    MARKET_US: "us_stocks_latest.json",
}
SNAPSHOT_KEY_FIELDS = {
    MARKET_KR: "code",
    MARKET_US: "symbol",
}


def default_data_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def load_snapshot_payload(market, data_dir=None):
    """스냅샷 JSON 원본을 읽습니다. 파일이 없으면 None(에러 아님 — 화면에서 안내)."""
    market = normalize_market(market)
    directory = data_dir or default_data_dir()
    path = os.path.join(directory, SNAPSHOT_FILENAMES[market])
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_universe_index(payload, market):
    """스냅샷 payload → {티커: 종목dict}. payload 가 None/형식 불일치면 빈 dict."""
    market = normalize_market(market)
    key_field = SNAPSHOT_KEY_FIELDS[market]
    index = {}
    if not isinstance(payload, dict):
        return index
    for stock in payload.get("stocks") or []:
        if not isinstance(stock, dict):
            continue
        raw_key = stock.get(key_field)
        if raw_key is None:
            continue
        try:
            key = normalize_ticker(market, raw_key)
        except ValueError:
            continue
        index[key] = stock
    return index


def load_universe_index(market, data_dir=None):
    """(index, metadata) 반환. 파일이 없으면 ({}, None)."""
    payload = load_snapshot_payload(market, data_dir=data_dir)
    if payload is None:
        return {}, None
    return build_universe_index(payload, market), payload.get("metadata")


KR_TICKER_MASTER_FILENAME = "kr_ticker_master.json"


def load_kr_ticker_master(data_dir=None):
    """
    2026-08-11 오너 요청(TASK_HISTORY #83) — 코스피 상위 200 밖(코스닥·ETF 포함) 종목도
    이름으로 찾을 수 있게 하는 보조 조회용 전체 상장종목 코드↔이름 목록을 읽습니다.

    ⚠️ **가격·밸류에이션 정보가 전혀 없습니다** — 그래서 `valuation_summary()`/
    `make_price_lookup()`이 참조하는 `indexes`(상위 200/550 스냅샷)와는 **의도적으로 분리**된
    별도 구조입니다. 여기 담긴 종목을 그 두 함수에 섞어 넣으면 "밸류에이션 정보 없음"이라는
    정직한 메시지 대신 빈 값투성이인데 "찾음"으로 잘못 표시될 위험이 있어, `resolve_stock_query()`의
    이름/코드 조회 용도로만 별도로 씁니다.

    (index, metadata) 반환 — `load_universe_index()`와 같은 형태. 파일이 없으면(아직 수집
    전, 또는 이번 수집에서 실패) 에러가 아니라 빈 dict — 이 보조 기능만 조용히 비활성화되고
    나머지 화면은 그대로 정상 작동합니다.
    """
    directory = data_dir or default_data_dir()
    path = os.path.join(directory, KR_TICKER_MASTER_FILENAME)
    if not os.path.exists(path):
        return {}, None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return build_universe_index(payload, MARKET_KR), (payload or {}).get("metadata")


KR_ALL_MARKET_PRICES_FILENAME = "kr_all_market_prices.json"


def load_kr_all_market_prices(data_dir=None):
    """
    2026-08-11 오너 요청(TASK_HISTORY #84) — 코스피 상위 200 밖(코스닥·ETF 포함) 종목도
    "현재가 없음" 대신 실제 종가를 보여줄 수 있게 하는 보조 가격 목록을 읽습니다.

    ⚠️ 이것도 `load_kr_ticker_master()`와 마찬가지로 `indexes`(상위 200/550 밸류에이션
    스냅샷)와는 **의도적으로 분리**된 별도 구조입니다 — PEGY/퀀트 밸류에이션은 없고 오직
    현재가만 담습니다. `make_price_lookup()`에 `broad_kr_prices`로 전달해 "1차: 상위 200
    유니버스 → 2차(없으면): 이 전 종목 종가 목록" 순서의 폴백으로만 씁니다.

    (index, metadata) 반환. 파일이 없으면(아직 수집 전, 또는 이번 수집 실패) 빈 dict —
    이 보조 기능만 조용히 비활성화되고 나머지 화면은 그대로 정상 작동합니다.
    """
    directory = data_dir or default_data_dir()
    path = os.path.join(directory, KR_ALL_MARKET_PRICES_FILENAME)
    if not os.path.exists(path):
        return {}, None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return build_universe_index(payload, MARKET_KR), (payload or {}).get("metadata")


US_ALL_MARKET_PRICES_FILENAME = "us_all_market_prices.json"


def load_us_all_market_prices(data_dir=None):
    """
    2026-08-12 오너 요청(TASK_HISTORY #92) — 위 `load_kr_all_market_prices()`의 미국판입니다.
    미국 시가총액 상위 550 유니버스 밖 종목도 "현재가 없음" 대신 실제 종가를 보여주기 위한
    보조 가격 목록(`data/us_all_market_prices.json`, 수집기는 `collector_us_stocks.py`)을 읽습니다.

    ⚠️ 한국판과 완전히 같은 원칙입니다 — 밸류에이션(PER/PEGY/퀀트점수)은 없고 **현재가만**
    있습니다. `make_price_lookup()`에 `broad_us_prices`로 넘겨 "1차: 상위 550 유니버스 →
    2차(없으면): 이 전 종목 가격 목록" 순서의 폴백으로만 씁니다. `valuation_summary()`는
    이 목록을 보지 않으므로 "밸류에이션 정보 없음" 문구는 그대로 정확합니다.

    (index, metadata) 반환. 파일이 없으면(아직 수집 전, 또는 이번 수집 실패) 빈 dict —
    이 보조 기능만 조용히 비활성화되고 나머지 화면은 그대로 정상 작동합니다.
    """
    directory = data_dir or default_data_dir()
    path = os.path.join(directory, US_ALL_MARKET_PRICES_FILENAME)
    if not os.path.exists(path):
        return {}, None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return build_universe_index(payload, MARKET_US), (payload or {}).get("metadata")


US_ALL_ETF_PRICES_FILENAME = "us_all_etf_prices.json"


def load_us_all_etf_prices(data_dir=None):
    """
    2026-08-12 오너 지시(TASK_HISTORY #93) — 위 `load_us_all_market_prices()`의 **ETF판**입니다.
    미국은 개별주식뿐 아니라 ETF로 투자하는 비중도 무시할 수 없다는 오너 판단에 따라, 그동안
    의도적으로 제외해 온 ETF도 "현재가 없음" 대신 실제 종가를 보여주기 위한 보조 가격 목록
    (`data/us_all_etf_prices.json`, 수집기는 `collector_us_stocks.py`)을 읽습니다.

    ⚠️ 왜 주식 파일과 나눠져 있는가 — 소스(스크리너)가 주식용·ETF용 두 개라, 한 파일에 합치면
    한쪽만 성공한 회차에 다른 쪽이 통째로 사라지거나 수집 시각이 뒤섞입니다. 파일별 metadata가
    그 파일 내용과 1:1로 맞도록 나눠 두고, **읽는 쪽에서 합칩니다**
    (`views/scorecard_view.py` — 티커 공간이 겹치지 않아 그냥 합쳐도 안전합니다).

    ⚠️ 여기에도 밸류에이션은 없습니다. ETF에는 EPS/ROE 같은 기업 재무제표가 아예 없어서
    PEGY/퀀트점수를 만들어내면 §0-1(지어내지 않기) 위반입니다 — 화면에서 ETF는 "현재가는 있고
    밸류에이션 정보는 없음"으로 정직하게 표시됩니다.

    (index, metadata) 반환. 파일이 없으면(아직 수집 전, 또는 이번 수집 실패) 빈 dict —
    이 보조 기능만 조용히 비활성화되고 나머지 화면은 그대로 정상 작동합니다.
    """
    directory = data_dir or default_data_dir()
    path = os.path.join(directory, US_ALL_ETF_PRICES_FILENAME)
    if not os.path.exists(path):
        return {}, None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return build_universe_index(payload, MARKET_US), (payload or {}).get("metadata")


def find_ticker_by_name(market, name, indexes):
    """
    2026-08-11 오너 요청 — 종목코드를 몰라도 종목명만으로 입력할 수 있게 하는 보조 조회.

    ⚠️ §0-1(지어내지 않기): 정확히 일치하는 종목이 **하나뿐**이면 그걸 쓰고, 그렇지 않으면
    (0개 또는 여러 개) 절대 추측하지 않고 이유와 함께 실패를 돌려줍니다. 정확 일치가 없으면
    부분 일치를 시도하되, 그 결과도 **유일할 때만** 채택합니다(기존 `krx_openapi.py`의
    지수명 매칭과 동일한 원칙 — 정확일치 → 유일한 부분일치 → 그 외엔 후보를 보여주고 포기).

    반환: (ticker 또는 None, matched_name 또는 None, reason 또는 None)
    """
    market_code = normalize_market(market)
    query = str(name or "").strip()
    if not query:
        return None, None, "종목명이 비어 있습니다."

    index = indexes.get(market_code) or {}
    exact = [(key, stock) for key, stock in index.items()
             if str(stock.get("name", "")).strip() == query]
    if len(exact) == 1:
        key, stock = exact[0]
        return key, stock.get("name"), None
    if len(exact) > 1:
        return None, None, "같은 이름의 종목이 여러 개 있습니다 — 종목코드를 직접 입력해 주세요."

    partial = [(key, stock) for key, stock in index.items()
               if query in str(stock.get("name", ""))]
    if len(partial) == 1:
        key, stock = partial[0]
        return key, stock.get("name"), None
    if len(partial) > 1:
        names = sorted({str(stock.get("name", "")) for _, stock in partial})
        return None, None, "이름이 비슷한 종목이 여러 개 있어 특정할 수 없습니다: " + ", ".join(names[:10])

    universe_label = "코스피 시가총액 상위 200" if market_code == MARKET_KR else "미국 시가총액 상위 550"
    return None, None, f"이 이름과 일치하는 종목을 찾지 못했습니다({universe_label} 유니버스 밖일 수 있음)."


# "코드처럼 생겼다"를 판별하는 형식(추측이 아니라 형식 판정입니다 — §0-1과 무관, 그냥 정규식).
# 한국: 숫자로 시작하는 영숫자 1~6자(우선주 코드 00680K 등 포함). 미국: 점·하이픈 포함 영숫자 1~10자.
# 둘 다 한글 등 비ASCII 문자가 섞이면 매치되지 않습니다 — 그러면 "이름"으로 간주합니다.
KR_TICKER_LIKE = re.compile(r"[0-9][0-9A-Za-z]{0,5}$")
US_TICKER_LIKE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,9}$")


def resolve_stock_query(market, query, indexes, broad_index=None):
    """
    2026-08-11 오너 요청 — "종목코드/티커/종목명이 전부 한 입력창에서 다 되게" 해달라는 실사용
    피드백 반영. 사용자가 코드를 입력했든 이름을 입력했든 이 함수 하나로 알아서 찾습니다.

    `broad_index`: (2026-08-11, TASK_HISTORY #83 신설) 코스피 상위 200/미국 상위 550 밸류에이션
    유니버스 **밖**의 종목도 이름으로 찾게 해주는 보조 목록(`load_kr_ticker_master()`, 현재는
    한국만 — 코스피+코스닥+ETF). 가격·밸류에이션은 없고 이름↔코드만 있습니다. 안 넘기면(None)
    이 단계는 그냥 건너뛰고 기존 동작과 완전히 동일합니다(하위 호환).

    순서(모두 §0-1: 추측하지 않고, 확실할 때만 채택):
      1) 코드로 바로 해석해서 **밸류에이션 유니버스(상위200/550) 안에 있으면** 그 종목으로 확정
         — 가장 확실한 경로(현재가까지 아는 종목).
      2) 실패하면 그 유니버스 안에서 이름으로 찾습니다(`find_ticker_by_name`) — 정확일치 →
         유일한 부분일치만 채택.
      3) 그것도 실패했는데 `broad_index`(전체 상장종목 목록)가 주어졌으면, 거기서 코드 직접
         일치 → 이름 일치(마찬가지로 정확일치 → 유일한 부분일치) 순으로 찾습니다. 여기서
         찾아도 **가격은 여전히 모릅니다** — 화면에는 그대로 "현재가 없음"으로 표시됩니다.
         이 단계는 "종목 자체가 뭔지"만 정직하게 확인해줄 뿐입니다.
      4) 그마저 실패했는데 입력이 "코드처럼 생긴 형식"이면, 아무 목록에도 없는 종목의 코드를
         직접 입력한 것으로 보고 **코드 자체는 그대로 받아들입니다**(이름은 모름 → None).
      5) 코드처럼도 안 생기고 어디서도 못 찾으면 포기하고 이유를 돌려줍니다(지어내지 않음).

    반환: (ticker 또는 None, 종목명 또는 None, 실패 이유 또는 None)
    """
    market_code = normalize_market(market)
    text = str(query or "").strip()
    if not text:
        return None, None, "종목(코드 또는 이름)을 입력해 주세요."

    try:
        candidate = normalize_ticker(market_code, text)
    except ValueError:
        candidate = None

    index = indexes.get(market_code) or {}
    if candidate and candidate in index:
        stock = index[candidate]
        return candidate, stock.get("name"), None

    found_ticker, found_name, name_reason = find_ticker_by_name(market_code, text, indexes)
    if found_ticker:
        return found_ticker, found_name, None

    if broad_index:
        if candidate and candidate in broad_index:
            stock = broad_index[candidate]
            return candidate, stock.get("name"), None
        broad_ticker, broad_name, broad_reason = find_ticker_by_name(
            market_code, text, {market_code: broad_index}
        )
        if broad_ticker:
            return broad_ticker, broad_name, None
        if broad_reason and "여러 개" in broad_reason:
            # 모호한 경우(같은 이름 여러 개)는 그대로 전달 — 사용자에게 유용한 정보입니다.
            name_reason = broad_reason
        else:
            # find_ticker_by_name()의 기본 실패 문구는 "상위 200/550 유니버스 밖일 수 있음"인데,
            # 이미 그 유니버스보다 훨씬 넓은 전체 상장종목 목록까지 확인한 뒤라 그대로 쓰면
            # 오히려 덜 뒤져본 것처럼 오해를 줍니다 — 더 정확한 문구로 바꿉니다.
            name_reason = "코스피·코스닥·국내ETF 전체 상장종목에서도 이 이름과 일치하는 종목을 찾지 못했습니다."

    looks_like_code = bool(candidate) and (
        KR_TICKER_LIKE.fullmatch(candidate) if market_code == MARKET_KR
        else US_TICKER_LIKE.fullmatch(candidate)
    )
    if looks_like_code:
        return candidate, None, None

    return None, None, (
        f"'{text}'와 일치하는 종목을 코드로도 이름으로도 찾지 못했습니다 — {name_reason}"
    )


def make_price_lookup(indexes, broad_kr_prices=None, broad_us_prices=None):
    """
    build_portfolio 에 넘길 현재가 조회 함수를 만듭니다.
    indexes: {"KR": {...}, "US": {...}}
    유니버스 밖 종목·가격 결측은 None 을 돌려줍니다(추정 금지).

    broad_kr_prices: (2026-08-11, TASK_HISTORY #84 신설, 기본값 None으로 하위호환 유지)
    `load_kr_all_market_prices()`가 반환한 인덱스. 한국 종목이 상위 200 유니버스(`indexes["KR"]`)
    안에 없을 때만 2차로 확인하는 폴백입니다 — **가격만** 쓰고 밸류에이션은 여전히 없습니다
    (`valuation_summary()`는 이 폴백을 타지 않으므로 "밸류에이션 정보 없음" 문구는 그대로 정확합니다).

    broad_us_prices: (2026-08-12, TASK_HISTORY #92 신설, 기본값 None으로 하위호환 유지)
    위와 완전히 같은 역할의 미국판(`load_us_all_market_prices()`). 미국 종목이 상위 550
    유니버스 안에 없을 때만 2차로 확인합니다. 2026-08-12(TASK_HISTORY #93)부터는 화면 쪽에서
    ETF 목록(`load_us_all_etf_prices()`)까지 합쳐 넘기므로 ETF 보유 종목도 여기서 잡힙니다
    (미국 티커 공간에서 주식과 ETF는 겹치지 않아 그냥 합쳐도 안전).

    ⚠️ 두 폴백은 시장별로 엄격히 분리됩니다 — 한국 목록을 미국 티커 조회에, 또는 그 반대로
    쓰는 경로는 없습니다(원/달러 혼용 차단, 이 모듈 상단 '환율 변환 없음' 원칙과 같은 맥락).
    """
    broad_by_market = {MARKET_KR: broad_kr_prices, MARKET_US: broad_us_prices}

    def lookup(market, ticker):
        try:
            market_code = normalize_market(market)
            key = normalize_ticker(market_code, ticker)
        except ValueError:
            return None
        stock = (indexes.get(market_code) or {}).get(key)
        if not stock:
            stock = (broad_by_market.get(market_code) or {}).get(key)
        if not stock:
            return None
        price = stock.get("price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None
    return lookup


def valuation_summary(market, ticker, indexes):
    """
    "사실 이 가격이에요" 연동용 요약. 유니버스 밖이면 `{"found": False, ...}` 를 돌려주고
    화면은 "밸류에이션 정보 없음"으로 표시합니다(값을 만들어내지 않습니다).

    코스피/미국 스냅샷이 공통으로 갖고 있는 필드만 골라 씁니다
    (price / t_pegy / f_pegy / badge / quant_score / score_max / t_fair / f_target).
    """
    try:
        market_code = normalize_market(market)
        key = normalize_ticker(market_code, ticker)
    except ValueError:
        return {"found": False, "reason": "종목 코드 형식을 알 수 없습니다."}
    stock = (indexes.get(market_code) or {}).get(key)
    if not stock:
        universe_label = "코스피 시가총액 상위 200" if market_code == MARKET_KR \
            else "미국 시가총액 상위 550"
        return {
            "found": False,
            "reason": f"{universe_label} 유니버스 밖 종목이라 밸류에이션 정보가 없습니다.",
        }
    if stock.get("is_unverified"):
        return {
            "found": True,
            "verified": False,
            "name": stock.get("name_kr") or stock.get("name"),
            "reason": stock.get("unverified_reason") or "수집 검증에 실패한 종목입니다.",
        }
    return {
        "found": True,
        "verified": True,
        "market": market_code,
        "ticker": key,
        "name": stock.get("name_kr") or stock.get("name"),
        "price": stock.get("price"),
        "currency": currency_for_market(market_code),
        "t_pegy": stock.get("t_pegy"),
        "f_pegy": stock.get("f_pegy"),
        "badge": stock.get("badge"),
        "quant_score": stock.get("quant_score"),
        "score_max": stock.get("score_max"),
        "t_fair": stock.get("t_fair"),
        "f_target": stock.get("f_target"),
        "t_per": stock.get("t_per"),
        "t_roe": stock.get("t_roe"),
        "data_issues": stock.get("data_issues") or [],
    }


# =============================================================================
# D. Supabase 래퍼
# =============================================================================

SECRET_URL_KEY = "SUPABASE_URL"
SECRET_ANON_KEY = "SUPABASE_ANON_KEY"


def _read_secret(name):
    """환경변수 → st.secrets 순으로 읽습니다. 없으면 None(예외 아님)."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    if STREAMLIT_AVAILABLE:
        try:
            value = st.secrets.get(name)  # secrets.toml 이 아예 없으면 예외가 납니다
        except Exception:
            value = None
        if value:
            return str(value).strip()
    return None


def get_supabase_config():
    """(url, anon_key). 미설정이면 (None, None). **값을 로그로 찍지 않습니다.**"""
    return _read_secret(SECRET_URL_KEY), _read_secret(SECRET_ANON_KEY)


@dataclass
class SupabaseStatus:
    """왜 연결이 안 되는지를 화면이 사용자에게 설명할 수 있도록 이유까지 담습니다."""
    available: bool
    reason: str = ""
    package_available: bool = False
    config_present: bool = False


def supabase_status():
    """연결 가능 여부 + **사용자 화면에 그대로 나가는** 사유 문구.

    ⚠️ 2026-08-17 — 사유 문구에서 플랫폼 이름("Streamlit Cloud → Settings → Secrets")을
       걷어냈습니다. 컷오버 후 실제 배포처는 Render(Environment) 인데, 이 문구는 공개된
       `/scorecard`·`/report` 의 "준비중" 안내를 통해 **일반 사용자 화면에 그대로 나갑니다.**
       옛 플랫폼 이름이 뜨면 사용자에게는 무의미하고 오너에게는 엉뚱한 곳을 보게 만듭니다.
       ⚠️ 이 함수는 아직 살아있는 Streamlit 쪽(`views/`)도 그대로 쓰므로, 특정 플랫폼을
          지칭하지 않는 **중립적인 표현**을 골랐습니다(양쪽 다 자연스럽게 읽힙니다).
          플랫폼별 구체 절차는 화면의 "🔧 오너 설정 체크리스트"(관리자용 접기 영역)에
          따로 적혀 있습니다.
    """
    package_ok = SUPABASE_PACKAGE_AVAILABLE
    url, key = get_supabase_config()
    config_ok = bool(url and key)
    if not package_ok and not config_ok:
        reason = ("`supabase` 패키지가 설치돼 있지 않고 접속 정보(서버 환경변수)도 등록되지 "
                  "않았습니다. (requirements.txt 반영 + 서버 환경변수 등록이 필요합니다)")
    elif not package_ok:
        reason = "`supabase` 파이썬 패키지가 설치돼 있지 않습니다. (requirements.txt 반영 후 재배포 필요)"
    elif not config_ok:
        missing = [n for n, v in ((SECRET_URL_KEY, url), (SECRET_ANON_KEY, key)) if not v]
        reason = ("Supabase 접속 정보가 등록되지 않았습니다: "
                  + ", ".join(missing)
                  + " (서버 환경변수에 등록해 주세요)")
    else:
        reason = ""
    return SupabaseStatus(
        available=bool(package_ok and config_ok),
        reason=reason,
        package_available=package_ok,
        config_present=config_ok,
    )


def create_supabase_client():
    """
    Supabase 클라이언트를 만듭니다. **패키지가 없거나 Secrets 미등록이면 None** 을 돌려줍니다
    (에러가 아닙니다 — 화면은 "준비중" 안내를 띄우고, 기존 두 모듈은 아무 영향 없이 동작).
    실제 생성 과정에서 예외가 나면 그건 진짜 문제이므로 ScorecardError 로 올립니다.

    ⚠️ 이 클라이언트를 `@st.cache_resource` 로 캐시하면 **로그인 세션이 모든 방문자에게
       공유**됩니다(클라이언트 객체가 auth 세션을 들고 있음). 절대 캐시하지 말고,
       방문자별 `st.session_state` 에만 보관하세요. — views/scorecard_view.py 참고
    """
    status = supabase_status()
    if not status.available:
        return None
    url, key = get_supabase_config()
    try:
        return _supabase_create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        # ⚠️ 2026-08-17 — 예전에는 `f"...: {exc}"` 로 예외 원문을 화면에 그대로 실었습니다.
        #    이 예외에는 URL·라이브러리 내부 메시지가 섞일 수 있어 §0-3-4 위반이었습니다.
        #    원문은 서버 로그로만 보내고, 사용자에게는 한국어 한 문장만 줍니다(§0-1 은 그대로
        #    지켜집니다 — 실패 사실과 사람이 읽을 수 있는 이유는 화면까지 도달합니다).
        print(f"⚠️ Supabase 클라이언트 생성 실패: {type(exc).__name__}: {exc}")
        raise ScorecardError(
            "Supabase 연결을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
        ) from exc


def _require_client(client):
    if client is None:
        raise ScorecardError(
            "Supabase 연결이 준비되지 않았습니다. " + (supabase_status().reason or "")
        )
    return client


# -----------------------------------------------------------------------------
# D-1. 인증 실패 문구 — 서버 응답 원문은 화면에 단 한 글자도 싣지 않습니다
#      (§0-3-4 "사용자 화면에 코드가 노출되면 안 됨" + §0-3-9 "계정 열거 방어")
#
#  왜 이렇게까지 하는가
#  ────────────────────────────────────────────────────────────────────────────
#  Supabase Auth 는 실패 사유를 영어 원문("Invalid login credentials"), 심할 때는
#  JSON 본문({'code':500,'error_code':'unexpected_failure','msg':'Database error
#  querying schema'}) 그대로 돌려줍니다. 예전 `_auth_error()` 는 이걸 f-string 으로
#  사용자 메시지에 그대로 박아서 두 가지 문제가 있었습니다.
#
#    ① 화면에 영어 원문·JSON·내부 error_code 가 그대로 노출 (§0-3-4 위반)
#    ② "User already registered" 가 그대로 떠서, 아무 이메일이나 넣고 가입을
#       눌러보는 것만으로 **그 사람이 회원인지 알아낼 수 있음** (계정 열거 공격,
#       §0-3-9). 같은 파일의 `send_password_reset_code()` 는 이미 "가입 여부를
#       알려주지 않는다"는 정책(PASSWORD_RESET_SENT_MESSAGE)을 지키고 있었는데,
#       회원가입/로그인 경로만 정반대로 열려 있어 정책이 서로 어긋나 있었습니다.
#
#  → 사용자에게는 **행동별로 고정된 한국어 한 문장**만 주고, 원문은 서버 로그에만
#    남깁니다. §0-1("실패를 조용히 덮지 않는다")과 모순되지 않습니다 — 실패했다는
#    사실과 사람이 읽을 수 있는 이유는 화면까지 그대로 도달하고, 감추는 것은
#    '내부 표현(코드/JSON/영문 원문)' 뿐입니다(§0-3-4 가 명시한 그 구분).
# -----------------------------------------------------------------------------

_AUTH_FALLBACK_MESSAGE = "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."

_AUTH_FAIL_MESSAGES = {
    # ⚠️ 로그인은 '계정 없음 / 비밀번호 틀림 / 서버 오류'를 절대 구분하지 않습니다.
    #    구분하는 순간 그 차이 자체가 "이 이메일은 가입돼 있다"는 정보가 됩니다.
    "로그인": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "회원가입": "가입 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "로그아웃": "로그아웃하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "재설정 코드 발송": "재설정 코드를 보내지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "새 비밀번호 설정": "새 비밀번호를 설정하지 못했습니다. 잠시 후 다시 시도해 주세요.",
}

# 아래 두 종류만 예외적으로 "무엇이 문제인지"를 한 걸음 더 알려줍니다. 사용자가 알아야
# 다음 행동(기다린다 / 다른 비밀번호를 고른다)을 정할 수 있고, 둘 다 **계정 존재 여부와
# 무관한 정보**라 열거 공격의 재료가 되지 않기 때문입니다.
# ⚠️ 문구는 전부 우리가 직접 쓴 한국어 상수입니다 — 서버 원문을 옮겨 담지 않고,
#    "39초 뒤에 다시" 같은 원문의 숫자도 싣지 않습니다(내부 정책 노출 최소화).
_AUTH_RATE_LIMIT_MESSAGE = "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."
_AUTH_WEAK_PASSWORD_MESSAGE = (
    "새 비밀번호가 보안 정책에 맞지 않습니다. 더 길고 복잡한 비밀번호로 다시 시도해 주세요."
)

# 판정용 키워드. Supabase/gotrue 버전에 따라 문구가 바뀔 수 있으므로 여러 표현을 함께
# 봅니다. **매칭에 실패하면 그냥 위의 고정 문구로 떨어질 뿐이라(원문 노출 없음),
# 이 목록이 낡아도 보안이 약해지지는 않습니다.**
_RATE_LIMIT_MARKERS = (
    "rate limit", "ratelimit", "too many requests", "429",
    "only request this after", "over_email_send_rate_limit",
)
_WEAK_PASSWORD_MARKERS = (
    "weak_password", "password should be", "password is too short",
    "characters long", "pwned", "breach",
)
# ⚠️ 이 목록만은 낡으면 실제로 영향이 있습니다(아래 sign_up 참고) — 매칭에 실패하면
#    중복 가입이 '일반 실패'로 떨어져 신규 가입과 화면이 달라집니다. 그래도 원문이
#    노출되지는 않으므로 유출되는 건 "성공/실패" 한 비트뿐이고, 표현을 넓게 잡아
#    그 확률을 줄였습니다.
_USER_EXISTS_MARKERS = (
    "user already registered", "already been registered", "user_already_exists",
    "email_exists", "already exists", "already registered",
)


def _exception_text(exc):
    """예외를 소문자 문자열로 — **분기 판정에만** 씁니다.

    🔴 이 함수의 반환값은 어떤 경로로도 사용자 메시지에 들어가면 안 됩니다.
       (여기 담기는 것이 바로 우리가 화면에서 없애려는 영문 원문·JSON 본문입니다.)
    """
    parts = [str(exc)]
    for attr in ("message", "code", "error_code"):
        value = getattr(exc, attr, None)
        if value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _matches(exc, markers):
    text = _exception_text(exc)
    return any(marker in text for marker in markers)


def _log_auth_failure(action, exc):
    """원문은 **서버 로그(콘솔)에만** 남깁니다 — 화면으로는 나가지 않습니다.

    §0-1 의 "로그만 남기는 것은 조치가 아니다"에 걸리지 않습니다: 사용자에게는 이미
    한국어 실패 문구가 따로 나가고 있고, 이 로그는 오너가 원인을 찾기 위한 **추가**
    수단입니다(실패 사실을 로그로 대체하는 것이 아닙니다).
    """
    print(f"⚠️ Supabase 인증 실패({action}): {type(exc).__name__}: {exc}")


def is_user_already_registered(exc):
    """이 예외가 '이미 가입된 이메일' 때문인가? (계정 열거 방어용 판정 — sign_up 참고)"""
    return _matches(exc, _USER_EXISTS_MARKERS)


def _auth_error(action, exc):
    """Auth 예외 → 사용자에게 보여줄 `ScorecardError`.

    ⚠️ 예외 원문(`exc`)은 **메시지에 절대 넣지 않습니다.** 서버 로그로만 보냅니다.
       반환 타입·호출 방식은 예전과 같아서(`raise _auth_error(...) from exc`)
       Streamlit 쪽(`views/scorecard_view.py`)도 그대로 동작하며, 그쪽 화면에서도
       똑같이 영문 원문이 사라집니다.
    """
    _log_auth_failure(action, exc)
    if _matches(exc, _RATE_LIMIT_MARKERS):
        message = _AUTH_RATE_LIMIT_MESSAGE
    elif action == "새 비밀번호 설정" and _matches(exc, _WEAK_PASSWORD_MARKERS):
        message = _AUTH_WEAK_PASSWORD_MESSAGE
    else:
        message = _AUTH_FAIL_MESSAGES.get(action, _AUTH_FALLBACK_MESSAGE)
    return ScorecardError(message)


def sign_up(client, email, password):
    """회원가입. 성공 시 Supabase 응답 객체를 그대로 돌려줍니다.

    ⚠️ **이미 가입된 이메일이어도 오류를 내지 않습니다**(반환값만 `None`) — 계정 열거
       방어(§0-3-9). 화면은 신규 가입이든 중복이든 **똑같은 안내**를 보여주게 되고,
       "이 이메일은 이미 회원이다"라는 사실은 화면 어디에도 드러나지 않습니다.
       이건 같은 파일의 `send_password_reset_code()` 가 이미 지키던 정책
       (`PASSWORD_RESET_SENT_MESSAGE` — "있다면 보냈습니다")과 같은 방침이며,
       Supabase 공식 문서가 `resetPasswordForEmail` 에 대해 설명하는 것과도 같습니다.

       §0-1 과의 관계: 여기서 삼키는 것은 **"실패"가 아니라 "정상적으로 예상된 결과"**
       입니다(그 이메일에는 이미 계정이 있으니 새로 만들 것이 없음 — Supabase 서버도
       이 경우 메일을 보내지 않거나 기존 계정 안내를 보냅니다). 진짜 장애(네트워크·
       서버 오류·정책 위반)는 그대로 `ScorecardError` 로 올라갑니다. 삼킨 경우에도
       서버 로그에는 반드시 흔적을 남깁니다(아래 `_log_auth_failure`).

    반환: Supabase 응답 객체 / 중복 가입이면 `None`. **호출하는 두 화면
          (`views/scorecard_view.py`, `web/auth_ui.py`) 모두 반환값을 쓰지 않습니다** —
          성공 여부는 예외 발생 여부로만 판단합니다.
    """
    _require_client(client)
    if not email or not password:
        raise ScorecardError("이메일과 비밀번호를 모두 입력해 주세요.")
    try:
        return client.auth.sign_up({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001
        if is_user_already_registered(exc):
            _log_auth_failure("회원가입(이미 가입된 이메일 — 화면에는 알리지 않음)", exc)
            return None
        raise _auth_error("회원가입", exc) from exc


def sign_in(client, email, password):
    """로그인."""
    _require_client(client)
    if not email or not password:
        raise ScorecardError("이메일과 비밀번호를 모두 입력해 주세요.")
    try:
        return client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001
        raise _auth_error("로그인", exc) from exc


def sign_out(client):
    """로그아웃."""
    _require_client(client)
    try:
        return client.auth.sign_out()
    except Exception as exc:  # noqa: BLE001
        raise _auth_error("로그아웃", exc) from exc


def current_user(client):
    """현재 로그인 사용자. 미로그인 상태면 None."""
    if client is None:
        return None
    try:
        response = client.auth.get_user()
    except Exception:
        return None
    return getattr(response, "user", None) if response is not None else None


def user_id_of(user):
    """Supabase user 객체/딕셔너리에서 UUID 문자열만 안전하게 꺼냅니다."""
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)


# -----------------------------------------------------------------------------
# D-2. 비밀번호 재설정 ("아이디/비밀번호 찾기") — 2026-08-13 오너 요청
# -----------------------------------------------------------------------------
#  오너 원문: "아이디 비밀번호를 잊어먹어서 로그인을 못할 때 간단하게 찾는 과정이 필요할 것
#  같애. 그래야 계정 무한생성을 막을 수 있어."
#
#  ▶ 왜 '아이디 찾기'가 없는가 — 이 앱의 로그인 ID는 **이메일 그 자체**입니다
#    (`sql/scorecard_schema.sql` — profiles 에 별도 아이디 컬럼이 없습니다). 그래서 실제로
#    필요한 건 비밀번호 재설정 하나뿐입니다.
#
#  ▶ 왜 '이메일 링크'가 아니라 '6자리 코드' 방식인가 (Streamlit 제약)
#    Supabase 의 기본 재설정 메일은 링크를 눌러 앱으로 돌아오게 하는데, 그 토큰은 URL 해시
#    프래그먼트(`#access_token=...`)나 쿼리스트링 `code` 로 전달됩니다. Streamlit 은 서버에서
#    렌더링하는 파이썬 앱이라 **해시 프래그먼트를 읽을 수 없고**, 링크 방식은 Redirect URL 을
#    Supabase 대시보드에 따로 등록해야 합니다. 반면 Supabase 이메일 템플릿의 `{{ .Token }}`
#    변수는 "링크 대신 쓸 수 있는 6자리 OTP"로 공식 문서에 명시돼 있고, 그 코드는
#    `verify_otp({"email":..., "token":..., "type":"recovery"})` 로 검증할 수 있습니다.
#    → 브라우저 리다이렉트가 아예 필요 없어 Streamlit 에 가장 잘 맞습니다.
#      · 공식 근거: https://supabase.com/docs/guides/auth/auth-email-templates
#        ("{{ .Token }} Contains a 6-digit One-Time-Password (OTP) that can be used
#          instead of the {{ .ConfirmationURL }}")
#      · https://supabase.com/docs/reference/python/auth-verifyotp
#        (이메일의 경우 type 은 email / **recovery** / invite / email_change)
#      · https://supabase.com/docs/reference/python/auth-resetpasswordforemail
#      · https://supabase.com/docs/reference/python/auth-updateuser
#    ⚠️ 2026-08-13 실측 정정: 문서는 "6-digit"라 했지만 오너가 실제로 받은 코드는
#      8자리(`59974821`)였습니다. 방식(OTP)에 대한 판단은 그대로 유효하지만, 정확한
#      자리수는 문서보다 실측을 따라야 해서 아래 상수를 정확히 6이 아니라 범위로
#      완화했습니다(§0-1).
#
#  ⚠️ 오너가 Supabase 대시보드에서 **딱 한 가지**를 해야 이 기능이 동작합니다:
#     Authentication → Emails(Email Templates) → **Reset Password** 템플릿 본문에
#     `{{ .Token }}` 을 넣기(기본 템플릿에는 링크만 있고 코드가 없습니다).
#     자세한 절차는 PROJECT_STATUS.md §9 에 적어뒀습니다.
#
#  ⚠️ 계정 존재 여부를 절대 흘리지 않습니다(user enumeration 방지)
#     Supabase 도 같은 정책입니다 — "To prevent user enumeration,
#     resetPasswordForEmail() doesn't reveal whether an account exists for the given
#     email address. When no user is associated with the address, Supabase Auth won't
#     send an email, though the method still returns without an error."
#     (https://supabase.com/docs/guides/auth/passwords) 그래서 이 모듈도 성공/실패를
#     구분해 말하지 않고 항상 같은 문구(PASSWORD_RESET_SENT_MESSAGE)를 돌려줍니다.
# -----------------------------------------------------------------------------

# ⚠️ 2026-08-13 실측 정정 — 공식 문서("{{ .Token }} Contains a 6-digit OTP")를 근거로
# 처음엔 정확히 6자리만 받도록 막아뒀는데, 오너가 실제로 받은 재설정 메일의 코드가
# **8자리**(`59974821`)였습니다. 문서와 실측이 다르면 실측을 따른다는 원칙(§0-1)에 따라
# 특정 자리수를 강제하지 않고 범위로 완화합니다. 최종 정오답 판단은 Supabase
# verify_otp() 서버 응답이 내리고, 여기서는 명백히 잘못된 입력(빈 값 · 문자 섞임 ·
# 너무 짧은 값)만 사전에 걸러 1회용 코드를 허투루 소모하지 않게 합니다.
PASSWORD_RESET_CODE_MIN_LENGTH = 6
PASSWORD_RESET_CODE_MAX_LENGTH = 10

# Supabase Auth 의 기본 최소 비밀번호 길이(대시보드에서 더 길게 올릴 수 있습니다).
# 여기서 먼저 막으면 사용자가 영어 원문 대신 한국어 안내를 보게 됩니다. 더 강한 정책은
# 서버가 최종적으로 거절하므로, 이 값은 "최소한의 사전 방어"입니다.
MIN_PASSWORD_LENGTH = 6

# 계정 존재 여부를 흘리지 않는 안전한 안내 문구(성공·미가입 어느 쪽이든 이 문구 하나).
PASSWORD_RESET_SENT_MESSAGE = (
    "입력하신 이메일로 가입된 계정이 있다면 재설정 코드를 보냈습니다. "
    "메일함(스팸함 포함)을 확인해 주세요."
)


def _normalize_email(email):
    """이메일 입력 정규화(앞뒤 공백 제거). 값이 없으면 빈 문자열."""
    return str(email or "").strip()


def _reset_request_callable(client):
    """
    설치된 supabase(auth) 패키지에서 '재설정 메일 발송' 함수를 찾아 돌려줍니다.

    ⚠️ 왜 getattr 로 찾는가 — 공식 파이썬 레퍼런스는 `reset_password_for_email(email, options)`
    이라고 적고 있지만, 같은 계열 패키지(gotrue-py)의 옛 이름은 `reset_password_email` 이었고
    두 이름이 버전에 따라 공존/교체돼 왔습니다. 이 저장소는 `requirements.txt` 에 버전을 고정하지
    않은 채 `supabase` 만 적어두므로(재배포 시점의 최신이 깔림), **하드코딩한 이름 하나에 걸면
    패키지 업데이트 한 번에 조용히 깨질 수 있습니다.** 그래서 문서에 적힌 새 이름을 먼저 찾고,
    없으면 옛 이름으로 폴백하며, 둘 다 없으면 '지어내지 않고' 그대로 실패를 알립니다(§0-1).
    """
    auth = getattr(client, "auth", None)
    for name in ("reset_password_for_email", "reset_password_email"):
        func = getattr(auth, name, None)
        if callable(func):
            return func, name
    return None, None


def send_password_reset_code(client, email):
    """
    비밀번호 재설정 코드를 이메일로 보내달라고 Supabase 에 요청합니다.

    반환: 화면에 그대로 띄울 안내 문구(PASSWORD_RESET_SENT_MESSAGE).
    ⚠️ 이 함수는 **가입된 이메일인지 아닌지를 절대 알려주지 않습니다**(위 주석 참고).
       그래서 성공 경로의 반환 문구가 항상 동일합니다.
    ⚠️ 이 호출은 로그인 세션을 만들지 않습니다 — 현재 로그인 상태에 아무 영향이 없습니다.
    """
    _require_client(client)
    address = _normalize_email(email)
    if not address:
        raise ScorecardError("가입할 때 사용한 이메일을 입력해 주세요.")

    request, _name = _reset_request_callable(client)
    if request is None:
        raise ScorecardError(
            "설치된 supabase 패키지에서 비밀번호 재설정 기능을 찾지 못했습니다. "
            "(패키지 버전 확인 후 재배포가 필요합니다)"
        )
    try:
        # options(redirect_to)는 일부러 넘기지 않습니다 — 우리는 링크가 아니라 메일 본문의
        # 코드를 쓰기 때문에 Redirect URL 등록이 필요 없습니다.
        request(address)
    except Exception as exc:  # noqa: BLE001
        # 발송 단계 실패는 대부분 '요청 과다(rate limit)' 라서 사용자에게 보여줄 가치가 있습니다.
        # (§0-1 — 조용히 성공한 척하지 않습니다.)
        raise _auth_error("재설정 코드 발송", exc) from exc
    return PASSWORD_RESET_SENT_MESSAGE


def _normalize_reset_code(code):
    """
    사용자가 입력한 재설정 코드 정리 — 공백/하이픈을 걷어내고 숫자로만 된 값인지 확인합니다.
    (메일에서 복사·붙여넣기 하면 앞뒤 공백이나 '123-456' 형태가 섞여 들어올 수 있습니다.)

    ⚠️ 정확한 자리수를 강제하지 않습니다 — 위 PASSWORD_RESET_CODE_MIN/MAX_LENGTH 주석 참고
    (문서는 6자리라 했지만 실측은 8자리였음). 범위 밖이거나 숫자가 아니면 1회용 코드를
    Supabase 로 보내기 전에 여기서 막습니다.
    """
    text = re.sub(r"[\s-]", "", str(code or ""))
    if not text:
        raise ScorecardError("이메일로 받은 재설정 코드를 입력해 주세요.")
    if not (
        text.isdigit()
        and PASSWORD_RESET_CODE_MIN_LENGTH <= len(text) <= PASSWORD_RESET_CODE_MAX_LENGTH
    ):
        raise ScorecardError(
            "재설정 코드가 올바르지 않습니다. 메일 본문의 숫자 코드를 다시 확인해 주세요."
        )
    return text


def _validated_new_password(new_password, confirm_password=None):
    """
    새 비밀번호 사전 검증. ⚠️ 비밀번호 '값'은 어떤 예외 메시지에도 넣지 않습니다.
    `confirm_password` 가 None 이면 확인란 비교를 생략합니다(화면이 이미 비교한 경우).
    """
    password = new_password if new_password is not None else ""
    if not password:
        raise ScorecardError("새 비밀번호를 입력해 주세요.")
    if confirm_password is not None and password != confirm_password:
        raise ScorecardError("새 비밀번호와 확인란이 서로 다릅니다.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ScorecardError(f"새 비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    return password


def _session_of(response):
    """verify_otp 응답에서 세션만 안전하게 꺼냅니다(객체/딕셔너리 양쪽 지원)."""
    if response is None:
        return None
    if isinstance(response, dict):
        return response.get("session")
    return getattr(response, "session", None)


def reset_password_with_code(client, email, code, new_password, confirm_password=None):
    """
    이메일로 받은 코드를 검증하고(=본인 확인), 곧바로 새 비밀번호로 바꿉니다.

    ⚠️ **`client` 는 반드시 이 재설정 전용으로 새로 만든 클라이언트여야 합니다.**
       `verify_otp()` 가 성공하면 그 클라이언트에 **재설정 대상 계정의 로그인 세션이 붙습니다.**
       화면이 쓰는 공용 클라이언트를 그대로 넘기면, 같은 브라우저에서 다른 사람이 로그인해
       있는 상태를 덮어써 남의 데이터를 보게 될 수 있습니다. 그래서 화면 쪽
       (`views/scorecard_view.py._new_auth_client()`)은 이 호출에만 1회용 클라이언트를 만들어
       넘기고, 이 함수는 끝날 때 그 세션을 반드시 로그아웃시킵니다(아래 finally).

    검증 순서도 의미가 있습니다 — **코드를 서버로 보내기 전에** 비밀번호 입력값부터 확인합니다.
    OTP 는 1회용이라, 확인란 오타 때문에 코드가 먼저 소모되면 사용자가 메일을 다시 받아야
    합니다(그리고 발송에는 요청 제한이 걸려 있습니다).

    반환: True (성공). 실패는 전부 ScorecardError.
    """
    _require_client(client)
    address = _normalize_email(email)
    if not address:
        raise ScorecardError("가입할 때 사용한 이메일을 입력해 주세요.")
    token = _normalize_reset_code(code)
    password = _validated_new_password(new_password, confirm_password)

    try:
        response = client.auth.verify_otp(
            {"email": address, "token": token, "type": "recovery"}
        )
    except Exception as exc:  # noqa: BLE001
        # ⚠️ 여기서는 Supabase 원문을 붙이지 않습니다. 원문에는 "user not found" 처럼
        #    **그 이메일이 가입돼 있는지 여부가 드러나는** 문구가 섞일 수 있어서, 위쪽
        #    '계정 존재 여부를 흘리지 않는다' 원칙이 이 한 줄에서 깨질 수 있기 때문입니다.
        raise ScorecardError(
            "재설정 코드 확인에 실패했습니다 — 코드가 다르거나 유효시간이 지났을 수 있습니다. "
            "1단계에서 코드를 다시 받아 주세요."
        ) from exc

    if _session_of(response) is None:
        raise ScorecardError(
            "재설정 코드는 보냈지만 인증 세션을 받지 못했습니다. 잠시 후 다시 시도해 주세요."
        )

    try:
        client.auth.update_user({"password": password})
    except Exception as exc:  # noqa: BLE001
        # 비밀번호 정책 위반(길이/유출된 비밀번호 등)은 서버가 최종 판단합니다. 원인을 감추면
        # 사용자가 왜 안 되는지 알 수 없으므로 기존 `_auth_error` 관례대로 감싸서 올립니다.
        # (예외 메시지에 비밀번호 값이 실릴 경로는 없습니다 — 값을 넘기지 않습니다.)
        raise _auth_error("새 비밀번호 설정", exc) from exc
    finally:
        # 성공하든 실패하든 이 1회용 클라이언트의 세션은 남기지 않습니다.
        # (로그아웃 실패는 여기서 더 할 수 있는 일이 없고, 실제 결과를 가리면 안 되므로 삼킵니다.
        #  클라이언트 자체를 화면이 버리기 때문에 세션이 재사용될 경로도 없습니다.)
        try:
            client.auth.sign_out()
        except Exception:  # noqa: BLE001
            pass
    return True


def _execute(query, action):
    try:
        response = query.execute()
    except Exception as exc:  # noqa: BLE001 - 조용히 빈 값으로 넘기지 않습니다(§0-1)
        raise ScorecardError(f"{action} 실패: {exc}") from exc
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    return data if data is not None else []


def fetch_holdings(client, user_id):
    """
    보유 종목 조회.
    ⚠️ RLS가 이미 남의 행을 막지만, 앱에서도 `user_id` 필터를 명시적으로 겁니다(이중 방어).
    """
    _require_client(client)
    if not user_id:
        raise ScorecardError("로그인 정보가 없어 보유 종목을 조회할 수 없습니다.")
    rows = _execute(
        client.table(HOLDINGS_TABLE).select("*").eq("user_id", user_id),
        "보유 종목 조회",
    )
    result = []
    for row in rows:
        item = dict(row)
        # DB의 numeric 은 드라이버에 따라 문자열로 올 수 있어 float 로 정규화합니다.
        for numeric_field in ("quantity", "avg_purchase_price"):
            try:
                item[numeric_field] = float(item.get(numeric_field))
            except (TypeError, ValueError):
                raise ScorecardError(
                    f"보유 종목 데이터가 손상됐습니다({numeric_field}={item.get(numeric_field)!r})."
                )
        result.append(item)
    result.sort(key=lambda r: (r.get("market") or "", r.get("ticker") or ""))
    return result


def find_holding(holdings, market, ticker):
    """조회해온 목록에서 같은 종목 행 찾기(없으면 None)."""
    market = normalize_market(market)
    ticker = normalize_ticker(market, ticker)
    for row in holdings:
        try:
            if normalize_market(row.get("market")) == market and \
                    normalize_ticker(market, row.get("ticker")) == ticker:
                return row
        except ValueError:
            continue
    return None


def insert_holding(client, user_id, holding):
    """새 보유 종목 1행 생성."""
    _require_client(client)
    if not user_id:
        raise ScorecardError("로그인 정보가 없어 저장할 수 없습니다.")
    payload = {
        "user_id": user_id,
        "market": holding["market"],
        "ticker": holding["ticker"],
        "stock_name": holding.get("stock_name"),
        "quantity": holding["quantity"],
        "avg_purchase_price": holding["avg_purchase_price"],
        "currency": holding.get("currency") or currency_for_market(holding["market"]),
    }
    return _execute(client.table(HOLDINGS_TABLE).insert(payload), "보유 종목 저장")


def update_holding(client, user_id, holding_id, quantity, avg_purchase_price, stock_name=None):
    """기존 보유 1행의 수량/평균단가 갱신."""
    _require_client(client)
    if not holding_id:
        raise ScorecardError("갱신할 보유 종목 id 가 없습니다.")
    payload = {
        "quantity": quantity,
        "avg_purchase_price": avg_purchase_price,
    }
    if stock_name:
        payload["stock_name"] = stock_name
    return _execute(
        client.table(HOLDINGS_TABLE).update(payload).eq("id", holding_id).eq("user_id", user_id),
        "보유 종목 갱신",
    )


def delete_holding(client, user_id, holding_id):
    """보유 1행 삭제."""
    _require_client(client)
    if not holding_id:
        raise ScorecardError("삭제할 보유 종목 id 가 없습니다.")
    return _execute(
        client.table(HOLDINGS_TABLE).delete().eq("id", holding_id).eq("user_id", user_id),
        "보유 종목 삭제",
    )


def add_lot(client, user_id, market, ticker, quantity, purchase_price, stock_name=None,
            holdings=None):
    """
    보유 종목 입력의 정식 진입점.
      - 처음 넣는 종목이면 insert
      - 이미 있는 종목이면 **수량 가중평균으로 재계산해서 update**
        (여러 증권사 계좌에 같은 종목이 있을 때 마인드맵 예시대로 동작)

    반환: (동작문자열, 갱신된 보유 dict) — 동작은 "insert" 또는 "merge".
    """
    _require_client(client)
    lot = make_lot(market, ticker, quantity, purchase_price, stock_name)
    if holdings is None:
        holdings = fetch_holdings(client, user_id)
    existing = find_holding(holdings, lot["market"], lot["ticker"])
    if existing is None:
        insert_holding(client, user_id, lot)
        return "insert", lot
    merged = merge_lot_into_holding(existing, lot)
    update_holding(
        client, user_id, existing.get("id"),
        merged["quantity"], merged["avg_purchase_price"],
        stock_name=merged.get("stock_name"),
    )
    return "merge", merged
