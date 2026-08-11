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


def make_price_lookup(indexes, broad_kr_prices=None):
    """
    build_portfolio 에 넘길 현재가 조회 함수를 만듭니다.
    indexes: {"KR": {...}, "US": {...}}
    유니버스 밖 종목·가격 결측은 None 을 돌려줍니다(추정 금지).

    broad_kr_prices: (2026-08-11, TASK_HISTORY #84 신설, 기본값 None으로 하위호환 유지)
    `load_kr_all_market_prices()`가 반환한 인덱스. 한국 종목이 상위 200 유니버스(`indexes["KR"]`)
    안에 없을 때만 2차로 확인하는 폴백입니다 — **가격만** 쓰고 밸류에이션은 여전히 없습니다
    (`valuation_summary()`는 이 폴백을 타지 않으므로 "밸류에이션 정보 없음" 문구는 그대로 정확합니다).
    미국 종목(US)에는 적용하지 않습니다(이 목록 자체가 국내 전용).
    """
    def lookup(market, ticker):
        try:
            market_code = normalize_market(market)
            key = normalize_ticker(market_code, ticker)
        except ValueError:
            return None
        stock = (indexes.get(market_code) or {}).get(key)
        if not stock and broad_kr_prices and market_code == MARKET_KR:
            stock = broad_kr_prices.get(key)
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
    package_ok = SUPABASE_PACKAGE_AVAILABLE
    url, key = get_supabase_config()
    config_ok = bool(url and key)
    if not package_ok and not config_ok:
        reason = ("`supabase` 패키지가 설치돼 있지 않고 접속 정보(Secrets)도 등록되지 "
                  "않았습니다. (requirements.txt 반영 + Streamlit Cloud Secrets 등록 필요)")
    elif not package_ok:
        reason = "`supabase` 파이썬 패키지가 설치돼 있지 않습니다. (requirements.txt 반영 후 재배포 필요)"
    elif not config_ok:
        missing = [n for n, v in ((SECRET_URL_KEY, url), (SECRET_ANON_KEY, key)) if not v]
        reason = ("Supabase 접속 정보가 등록되지 않았습니다: "
                  + ", ".join(missing)
                  + " (Streamlit Cloud → Settings → Secrets 에 등록하세요)")
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
    except Exception as exc:  # noqa: BLE001 - 원인을 화면에 그대로 보여주기 위함
        raise ScorecardError(f"Supabase 클라이언트 생성 실패: {exc}") from exc


def _require_client(client):
    if client is None:
        raise ScorecardError(
            "Supabase 연결이 준비되지 않았습니다. " + (supabase_status().reason or "")
        )
    return client


def _auth_error(action, exc):
    """Auth 예외를 사용자 문구로. 비밀번호·키 값은 절대 메시지에 넣지 않습니다."""
    return ScorecardError(f"{action} 실패: {exc}")


def sign_up(client, email, password):
    """회원가입. 성공 시 Supabase 응답 객체를 그대로 돌려줍니다."""
    _require_client(client)
    if not email or not password:
        raise ScorecardError("이메일과 비밀번호를 모두 입력해 주세요.")
    try:
        return client.auth.sign_up({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001
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
