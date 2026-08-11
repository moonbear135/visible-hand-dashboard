# tests/test_scorecard.py
"""
📊 "내 성적표" 모듈 오프라인 검증 (네트워크 불필요 · Supabase 접속 불필요)

SCORECARD_WORK_ORDER.md §4-4 / §6-3 에 따라, 이 세션에서는 **실제 Supabase 에 접속할 수
없다고 가정**하고 전부 모킹/합성 데이터로 검증합니다.

검증 대상
    ① 수량 가중평균 재계산 (마인드맵 예시 그대로)
    ② 통화(원/달러) 분리 — 환율 변환이 어디에서도 일어나지 않는지
    ③ 기존 PEGY 스냅샷 조회 (합성 JSON + 저장소의 실제 스냅샷)
    ④ 포트폴리오 비중/수익 비중 계산 (현재가를 모르는 종목을 0으로 속이지 않는지)
    ⑤ Supabase 클라이언트가 없을 때의 폴백("준비중")과, CRUD가 조용히 실패하지 않는지
    ⑥ 가짜(fake) Supabase 클라이언트로 holdings CRUD 배선 검증
    ⑦ sql/scorecard_schema.sql 의 RLS 정책 포함 여부
    ⑧ 화면/라우팅 배선 — 기본 숨김(스테이징), 기존 두 모듈 라우팅 무손상

⚠️ 저장소의 실제 데이터 파일(data/*.json)은 **읽기만** 합니다. 이 테스트는 어떤 파일도
   수정하지 않습니다(쓰기는 tempfile 안에서만).

실행: python tests/test_scorecard.py
"""

import importlib
import io
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent))

from utils import scorecard_db as sdb  # noqa: E402
from utils.scorecard_db import (  # noqa: E402
    CURRENCY_KRW,
    CURRENCY_USD,
    MARKET_KR,
    MARKET_US,
    ScorecardError,
    add_lot,
    aggregate_lots,
    build_portfolio,
    build_universe_index,
    create_supabase_client,
    currency_for_market,
    delete_holding,
    evaluate_holding,
    fetch_holdings,
    find_holding,
    find_ticker_by_name,
    format_amount,
    insert_holding,
    load_universe_index,
    make_lot,
    make_price_lookup,
    merge_lot_into_holding,
    normalize_market,
    normalize_ticker,
    sign_in,
    split_by_currency,
    supabase_status,
    update_holding,
    valuation_summary,
    weighted_average_price,
)

REPO_ROOT = Path(__file__).parent.parent
FAILURES = []


def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


def expect_raises(fn, exc_types, label):
    try:
        fn()
    except exc_types:
        check(True, label)
    except Exception as other:  # noqa: BLE001
        check(False, label, f"(다른 예외: {type(other).__name__}: {other})")
    else:
        check(False, label, "(예외가 발생하지 않음)")


# =============================================================================
# 합성 데이터 (실데이터로 만들 수 없는 케이스용)
# =============================================================================
SYNTHETIC_KR_SNAPSHOT = {
    "metadata": {"last_updated_at": "2026-08-11 16:05", "status": "SUCCESS"},
    "stocks": [
        {
            "rank": 1, "is_visible": True, "name": "합성전자", "code": "005930",
            "price": 100000.0, "t_pegy": 0.50, "f_pegy": 0.40, "badge": "🟢 강력 저평가",
            "quant_score": 80, "score_max": 100, "t_fair": 150000, "f_target": 180000,
            "t_per": 10.0, "t_roe": 12.0, "is_unverified": False, "data_issues": [],
        },
        {
            "rank": 2, "is_visible": True, "name": "합성화학", "code": "051910",
            "price": 200000.0, "t_pegy": 2.10, "f_pegy": None, "badge": "🔴 고평가",
            "quant_score": 30, "score_max": 90, "t_fair": 120000, "f_target": None,
            "t_per": 40.0, "t_roe": 3.0, "is_unverified": False, "data_issues": [],
        },
        {
            "rank": 3, "is_visible": True, "name": "합성미검증", "code": "000660",
            "price": 50000.0, "is_unverified": True,
            "unverified_reason": "PER 수집 실패 (합성 시나리오)",
        },
    ],
}

SYNTHETIC_US_SNAPSHOT = {
    "metadata": {"last_updated_at_kst": "2026-08-11 13:53", "status": "SUCCESS"},
    "stocks": [
        {
            "symbol": "FAKE", "name": "Fake Corp", "name_kr": "페이크", "rank": 1,
            "price": 200.0, "t_pegy": 0.90, "f_pegy": 0.60, "badge": "🟢 강력 저평가",
            "quant_score": 81, "score_max": 100, "t_fair": 250.0, "f_target": 300.0,
            "t_per": 20.0, "t_roe": 30.0, "is_unverified": False, "data_issues": [],
        },
        {
            "symbol": "NOPRICE", "name": "No Price Inc", "rank": 2,
            "price": None, "is_unverified": False,
        },
    ],
}


# =============================================================================
# 가짜 Supabase 클라이언트 (네트워크·패키지 없이 CRUD 배선만 검증)
# =============================================================================
class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store, op, payload=None, fail=False):
        self.store = store
        self.op = op
        self.payload = payload
        self.filters = []
        self.fail = fail

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def _matches(self, row):
        return all(str(row.get(col)) == str(val) for col, val in self.filters)

    def execute(self):
        self.store["calls"].append((self.op, list(self.filters), self.payload))
        if self.fail:
            raise RuntimeError("네트워크 오류(합성)")
        rows = self.store["rows"]
        if self.op == "select":
            return FakeResponse([dict(r) for r in rows if self._matches(r)])
        if self.op == "insert":
            new_row = dict(self.payload)
            new_row.setdefault("id", f"row-{len(rows) + 1}")
            rows.append(new_row)
            return FakeResponse([dict(new_row)])
        if self.op == "update":
            touched = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    touched.append(dict(row))
            return FakeResponse(touched)
        if self.op == "delete":
            kept = [r for r in rows if not self._matches(r)]
            removed = [dict(r) for r in rows if self._matches(r)]
            self.store["rows"] = kept
            return FakeResponse(removed)
        raise AssertionError(f"알 수 없는 op: {self.op}")


class FakeTable:
    def __init__(self, store, name, fail=False):
        self.store = store
        self.name = name
        self.fail = fail

    def select(self, _columns="*"):
        return FakeQuery(self.store, "select", fail=self.fail)

    def insert(self, payload):
        return FakeQuery(self.store, "insert", payload, fail=self.fail)

    def update(self, payload):
        return FakeQuery(self.store, "update", payload, fail=self.fail)

    def delete(self):
        return FakeQuery(self.store, "delete", fail=self.fail)


class FakeAuth:
    def __init__(self, fail=False):
        self.fail = fail
        self.signed_out = False
        self.last_credentials_keys = None

    def sign_in_with_password(self, credentials):
        # 비밀번호 '값'은 어디에도 보관하지 않고 키 목록만 기록합니다.
        self.last_credentials_keys = sorted(credentials.keys())
        if self.fail:
            raise RuntimeError("Invalid login credentials(합성)")
        return types.SimpleNamespace(
            user=types.SimpleNamespace(id="user-uuid-1", email=credentials["email"])
        )

    def sign_up(self, credentials):
        if self.fail:
            raise RuntimeError("User already registered(합성)")
        return types.SimpleNamespace(
            user=types.SimpleNamespace(id="user-uuid-1", email=credentials["email"])
        )

    def sign_out(self):
        self.signed_out = True

    def get_user(self):
        return types.SimpleNamespace(
            user=types.SimpleNamespace(id="user-uuid-1", email="owner@example.com")
        )


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.store = {"rows": list(rows or []), "calls": []}
        self.fail = fail
        self.auth = FakeAuth(fail=fail)

    def table(self, name):
        self.store["last_table"] = name
        return FakeTable(self.store, name, fail=self.fail)


# =============================================================================
# 1. 상수 / 정규화 — 통화는 사용자가 고르는 게 아니라 시장에서 파생
# =============================================================================
def test_normalization():
    print("\n[1] 시장·통화·티커 정규화")
    check(currency_for_market(MARKET_KR) == CURRENCY_KRW, "한국 시장 → KRW")
    check(currency_for_market(MARKET_US) == CURRENCY_USD, "미국 시장 → USD")
    check(normalize_market("kr") == MARKET_KR and normalize_market(" us ") == MARKET_US,
          "대소문자·공백 허용")
    expect_raises(lambda: normalize_market("JP"), ValueError, "모르는 시장코드는 예외(임의 매핑 금지)")
    expect_raises(lambda: normalize_market(None), ValueError, "시장 미지정은 예외")

    check(normalize_ticker(MARKET_KR, "5930") == "005930", "한국 종목코드 앞자리 0 복원(5930→005930)")
    check(normalize_ticker(MARKET_KR, "005930") == "005930", "이미 6자리면 그대로")
    check(normalize_ticker(MARKET_US, " nvda ") == "NVDA", "미국 티커 대문자·공백 제거")
    check(normalize_ticker(MARKET_US, "brk.b") == "BRK.B", "점 있는 티커도 그대로 보존")
    expect_raises(lambda: normalize_ticker(MARKET_KR, "1234567"), ValueError,
                  "7자리 한국 코드는 예외")
    expect_raises(lambda: normalize_ticker(MARKET_US, "   "), ValueError, "빈 티커는 예외")

    check(format_amount(93076.923076, CURRENCY_KRW) == "93,076원",
          "원화 표기는 절사(마인드맵 예시 93,076원과 일치)")
    check(format_amount(223.96, CURRENCY_USD) == "$223.96", "달러 표기는 소수 2자리")
    check(format_amount(None, CURRENCY_KRW) == "—", "값이 없으면 0원이 아니라 —")


# =============================================================================
# 2. 수량 가중평균 (마인드맵 예시)
# =============================================================================
def test_weighted_average():
    print("\n[2] 수량 가중평균 매입가 재계산")
    a = make_lot(MARKET_KR, "005930", 10, 100000, "삼성전자")   # A증권 10주 / 100만원
    b = make_lot(MARKET_KR, "005930", 3, 70000)                 # B증권 3주 / 21만원
    qty, avg, cost = weighted_average_price([a, b])
    check(qty == 13, "총수량 13주")
    check(cost == 1210000, "총 매입금액 1,210,000원")
    check(abs(avg - 1210000 / 13) < 1e-9, "평균단가 = 1,210,000 ÷ 13 (전체 정밀도 보존)")
    check(format_amount(avg, CURRENCY_KRW) == "93,076원", "화면 표기 93,076원 (오너 예시와 동일)")

    merged = merge_lot_into_holding(a, b)
    check(merged["quantity"] == 13 and abs(merged["avg_purchase_price"] - 1210000 / 13) < 1e-9,
          "merge_lot_into_holding 결과 동일")
    check(merged["stock_name"] == "삼성전자", "종목명은 기존 값 유지")
    check(merge_lot_into_holding(None, b)["quantity"] == 3, "기존 보유가 없으면 새 로트가 그대로")

    # 순서 무관 + 3건 이상
    c = make_lot(MARKET_KR, "005930", 7, 120000)
    forward = aggregate_lots([a, b, c])[0]
    backward = aggregate_lots([c, b, a])[0]
    check(abs(forward["avg_purchase_price"] - backward["avg_purchase_price"]) < 1e-9,
          "입력 순서가 달라도 평균단가 동일")
    expected = (10 * 100000 + 3 * 70000 + 7 * 120000) / 20
    check(abs(forward["avg_purchase_price"] - expected) < 1e-9, "3건 가중평균 값 일치")
    check(forward["quantity"] == 20, "3건 합산 수량 20주")

    # 다른 종목은 합쳐지지 않음
    multi = aggregate_lots([a, b, make_lot(MARKET_US, "NVDA", 2, 200)])
    check(len(multi) == 2, "다른 종목은 별개 행으로 유지")

    # 잘못된 입력을 조용히 통과시키지 않음
    expect_raises(lambda: make_lot(MARKET_KR, "005930", 0, 1000), ValueError, "수량 0은 거부")
    expect_raises(lambda: make_lot(MARKET_KR, "005930", -1, 1000), ValueError, "음수 수량 거부")
    expect_raises(lambda: make_lot(MARKET_KR, "005930", 1, -100), ValueError, "음수 매입가 거부")
    expect_raises(lambda: make_lot(MARKET_KR, "005930", "열주", 1000), ValueError, "숫자가 아닌 수량 거부")
    expect_raises(lambda: weighted_average_price([]), ValueError, "빈 입력은 예외(0으로 나누지 않음)")


# =============================================================================
# 3. 통화 분리 — 환율 변환 금지
# =============================================================================
def test_currency_separation():
    print("\n[3] 원/달러 분리 (환율 변환 없음)")
    kr = make_lot(MARKET_KR, "005930", 10, 100000)
    us = make_lot(MARKET_US, "NVDA", 5, 200)
    check(kr["currency"] == CURRENCY_KRW and us["currency"] == CURRENCY_USD,
          "로트 생성 시 통화가 시장에서 자동 결정")
    expect_raises(lambda: weighted_average_price([kr, us]), ValueError,
                  "통화가 다른 보유분 합산은 예외(환율 변환 금지)")

    groups = split_by_currency([kr, us])
    check(set(groups.keys()) == {CURRENCY_KRW, CURRENCY_USD}, "통화별로 분리됨")
    check(len(groups[CURRENCY_KRW]) == 1 and len(groups[CURRENCY_USD]) == 1, "각 그룹 1종목")

    portfolio = build_portfolio([kr, us], lambda market, ticker: 1.0)
    check(set(portfolio.keys()) == {CURRENCY_KRW, CURRENCY_USD}, "포트폴리오도 통화별로 따로 산출")
    check("TOTAL" not in portfolio and "ALL" not in portfolio,
          "통화를 합친 '총 자산' 그룹이 존재하지 않음")

    # 소스에 환율 변환 흔적이 없는지 (fx/exchange rate/usd_krw 류)
    for rel in ("utils/scorecard_db.py", "views/scorecard_view.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8").lower()
        forbidden = ("usd_krw", "usdkrw", "exchange_rate", "fx_rate", "환율변환", "환율 적용")
        hits = [token for token in forbidden if token in src]
        check(not hits, f"{rel} 에 환율 변환 코드/토큰이 없음", f"(발견: {hits})")


# =============================================================================
# 4. 기존 PEGY 스냅샷 조회 (합성 JSON + 실제 스냅샷)
# =============================================================================
def test_universe_lookup():
    print("\n[4] 기존 PEGY 스냅샷 조회 (code / symbol 키)")
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "kospi200_pegy_latest.json"), "w", encoding="utf-8") as f:
            json.dump(SYNTHETIC_KR_SNAPSHOT, f, ensure_ascii=False)
        with open(os.path.join(tmp, "us_stocks_latest.json"), "w", encoding="utf-8") as f:
            json.dump(SYNTHETIC_US_SNAPSHOT, f, ensure_ascii=False)

        kr_index, kr_meta = load_universe_index(MARKET_KR, data_dir=tmp)
        us_index, us_meta = load_universe_index(MARKET_US, data_dir=tmp)
        check(set(kr_index.keys()) == {"005930", "051910", "000660"}, "한국 인덱스 키는 code")
        check(set(us_index.keys()) == {"FAKE", "NOPRICE"}, "미국 인덱스 키는 symbol")
        check(kr_meta.get("status") == "SUCCESS" and us_meta.get("status") == "SUCCESS",
              "metadata 도 함께 반환")

        indexes = {MARKET_KR: kr_index, MARKET_US: us_index}
        lookup = make_price_lookup(indexes)
        check(lookup(MARKET_KR, "5930") == 100000.0, "앞자리 0 없는 입력도 현재가 조회 성공")
        check(lookup(MARKET_US, "fake") == 200.0, "소문자 티커도 조회 성공")
        check(lookup(MARKET_KR, "999999") is None, "유니버스 밖 종목은 None (추정 금지)")
        check(lookup(MARKET_US, "NOPRICE") is None, "price 결측 종목도 None")
        check(lookup(MARKET_KR, "") is None, "빈 티커는 예외 없이 None")

        found = valuation_summary(MARKET_KR, "005930", indexes)
        check(found["found"] and found["verified"], "유니버스 안 종목은 요약 반환")
        check(found["t_pegy"] == 0.50 and found["badge"] == "🟢 강력 저평가",
              "PEGY·배지를 스냅샷 값 그대로 전달(재계산 안 함)")
        check(found["currency"] == CURRENCY_KRW, "요약에도 통화가 붙음")

        missing = valuation_summary(MARKET_KR, "999999", indexes)
        check(not missing["found"] and "유니버스 밖" in missing["reason"],
              "유니버스 밖은 '밸류에이션 정보 없음' 사유와 함께 반환")

        unverified = valuation_summary(MARKET_KR, "000660", indexes)
        check(unverified["found"] and not unverified["verified"],
              "미검증 종목은 verified=False 로 구분")
        check("합성" in (unverified.get("reason") or ""), "미검증 사유를 그대로 전달")

        us_found = valuation_summary(MARKET_US, "FAKE", indexes)
        check(us_found["name"] == "페이크", "미국 종목은 한글명 우선 표기")

        empty_index, empty_meta = load_universe_index(MARKET_KR, data_dir=os.path.join(tmp, "없음"))
        check(empty_index == {} and empty_meta is None, "스냅샷 파일이 없으면 빈 인덱스(에러 아님)")
    check(build_universe_index(None, MARKET_KR) == {}, "payload 가 None 이어도 죽지 않음")
    check(build_universe_index({"stocks": [1, "x", {}]}, MARKET_KR) == {},
          "형식이 깨진 항목은 조용히 건너뜀(가짜 키 생성 안 함)")

    # 저장소의 실제 스냅샷으로도 조회가 되는지 (읽기 전용)
    real_kr, real_kr_meta = load_universe_index(MARKET_KR)
    real_us, real_us_meta = load_universe_index(MARKET_US)
    check(len(real_kr) > 100, f"실제 코스피 스냅샷 로드({len(real_kr)}종목)")
    check(len(real_us) > 100, f"실제 미국 스냅샷 로드({len(real_us)}종목)")
    # ⚠️ 실측: 코스피 스냅샷에는 우선주 계열의 영숫자 코드(`00680K`, `0126Z0`)도 있습니다.
    #    "전부 숫자"라고 단정하면 그 종목들이 조회 불가가 되므로 6자리 영숫자로 검증합니다.
    check(all(len(code) == 6 for code in real_kr),
          "실제 코스피 키가 전부 6자리 문자열(앞자리 0 보존)")
    alnum_codes = [c for c in real_kr if not c.isdigit()]
    check(all(normalize_ticker(MARKET_KR, c) == c for c in alnum_codes),
          f"우선주 영숫자 코드도 정규화 후 그대로 조회됨({alnum_codes or '해당 없음'})")
    check(normalize_ticker(MARKET_KR, "680k") == "00680K",
          "영숫자 코드도 앞자리 0 복원 + 대문자화")
    if real_kr:
        sample_code = sorted(real_kr.keys())[0]
        summary = valuation_summary(MARKET_KR, sample_code, {MARKET_KR: real_kr, MARKET_US: real_us})
        check(summary["found"], f"실제 종목({sample_code}) 요약 조회 성공")
    check(real_kr_meta is not None and real_us_meta is not None, "실제 스냅샷 metadata 존재")


# =============================================================================
# 4-1. 종목명으로 티커 찾기 (2026-08-11, 오너 실사용 피드백)
# =============================================================================
def test_name_lookup():
    print("\n[4-1] 종목명으로 티커 찾기 — §0-1(정확 일치 → 유일한 부분일치 → 그 외엔 포기)")
    kr_index = build_universe_index(SYNTHETIC_KR_SNAPSHOT, MARKET_KR)
    us_index = build_universe_index(SYNTHETIC_US_SNAPSHOT, MARKET_US)
    indexes = {MARKET_KR: kr_index, MARKET_US: us_index}

    ticker, name, reason = find_ticker_by_name(MARKET_KR, "합성전자", indexes)
    check(ticker == "005930" and name == "합성전자" and reason is None, "정확히 일치하면 그 종목")

    ticker, name, reason = find_ticker_by_name(MARKET_US, "Fake", indexes)
    check(ticker == "FAKE" and reason is None, "부분 일치가 유일하면 그 종목으로 채택")

    ticker, name, reason = find_ticker_by_name(MARKET_KR, "존재하지않는이름", indexes)
    check(ticker is None and name is None and reason, "일치하는 게 없으면 None + 이유(추측 안 함)")

    ticker, name, reason = find_ticker_by_name(MARKET_KR, "", indexes)
    check(ticker is None and "비어" in (reason or ""), "빈 이름은 즉시 실패")

    # 부분 일치인데 여러 개 걸리는 경우 — 절대 아무거나 골라잡지 않는지
    # (쿼리와 완전히 일치하는 항목은 하나도 없어야 '부분 일치' 분기까지 내려갑니다)
    dup_snapshot = {
        "metadata": {}, "stocks": [
            {"name": "겹치는이름공통A", "code": "111111", "price": 1000.0},
            {"name": "겹치는이름공통B", "code": "222222", "price": 2000.0},
        ],
    }
    dup_index = build_universe_index(dup_snapshot, MARKET_KR)
    ticker, name, reason = find_ticker_by_name(
        MARKET_KR, "겹치는이름공통", {MARKET_KR: dup_index, MARKET_US: {}}
    )
    check(ticker is None and "여러 개" in (reason or ""),
          "부분 일치가 여러 개면 추측하지 않고 명시적으로 실패")

    exact_dup_snapshot = {
        "metadata": {}, "stocks": [
            {"name": "완전동일이름", "code": "333333", "price": 1000.0},
            {"name": "완전동일이름", "code": "444444", "price": 2000.0},
        ],
    }
    exact_dup_index = build_universe_index(exact_dup_snapshot, MARKET_KR)
    ticker, name, reason = find_ticker_by_name(
        MARKET_KR, "완전동일이름", {MARKET_KR: exact_dup_index, MARKET_US: {}}
    )
    check(ticker is None and "여러 개" in (reason or ""),
          "완전 일치도 여러 개면 골라잡지 않음")


# =============================================================================
# 5. 포트폴리오 계산 (비중 / 수익 비중 / 현재가 결측)
# =============================================================================
def test_portfolio():
    print("\n[5] 보유 평가 · 비중 · 수익 비중")
    holdings = [
        {"market": "KR", "ticker": "005930", "stock_name": "합성전자",
         "quantity": 10, "avg_purchase_price": 80000, "currency": "KRW"},
        {"market": "KR", "ticker": "051910", "stock_name": "합성화학",
         "quantity": 5, "avg_purchase_price": 250000, "currency": "KRW"},
        {"market": "KR", "ticker": "999999", "stock_name": "유니버스밖",
         "quantity": 3, "avg_purchase_price": 10000, "currency": "KRW"},
    ]
    prices = {"005930": 100000.0, "051910": 200000.0}
    portfolio = build_portfolio(holdings, lambda market, ticker: prices.get(ticker))
    group = portfolio[CURRENCY_KRW]
    rows = {r["ticker"]: r for r in group["rows"]}

    check(rows["005930"]["market_value"] == 1000000, "평가금액 = 수량 × 현재가")
    check(rows["005930"]["profit"] == 200000, "평가손익 = 평가금액 - 매입원가")
    check(abs(rows["005930"]["profit_pct"] - 25.0) < 1e-9, "수익률 +25%")
    check(rows["051910"]["profit"] == -250000, "손실 종목은 음수 그대로")

    check(rows["999999"]["current_price"] is None, "유니버스 밖 종목 현재가 None")
    check(rows["999999"]["market_value"] is None and rows["999999"]["profit"] is None,
          "현재가를 모르면 평가금액·손익을 계산하지 않음(0으로 채우지 않음)")
    check(rows["999999"]["weight_pct"] is None, "현재가 없는 종목의 비중은 None (0%로 속이지 않음)")
    check(rows["999999"]["cost"] == 30000, "매입원가는 그래도 계산됨(사용자 입력만으로 가능)")

    priced_weight_sum = sum(r["weight_pct"] for r in group["rows"] if r["weight_pct"] is not None)
    check(abs(priced_weight_sum - 100.0) < 1e-9, "현재가를 아는 종목들의 비중 합 = 100%")
    check(abs(rows["005930"]["weight_pct"] - 50.0) < 1e-9, "비중 계산값 확인(100만/200만=50%)")

    check(group["total_value"] == 2000000, "평가금액 합계는 현재가를 아는 종목만")
    check(group["total_cost"] == 10 * 80000 + 5 * 250000 + 3 * 10000, "매입원가 합계는 전 종목")
    check(group["total_profit"] == 2000000 - (800000 + 1250000), "평가손익 합계")
    check(group["unpriced_count"] == 1 and group["unpriced_tickers"] == ["999999"],
          "현재가 없는 종목을 따로 집계")

    check(abs(rows["005930"]["profit_share_pct"] - 100.0) < 1e-9,
          "이익 종목이 하나뿐이면 수익 비중 100%")
    check(rows["051910"]["profit_share_pct"] is None, "손실 종목의 수익 비중은 None (음수 조각 금지)")

    # 이익 종목이 2개일 때 수익 비중 합 100%
    two_gainers = build_portfolio(
        [holdings[0],
         {"market": "KR", "ticker": "051910", "quantity": 5,
          "avg_purchase_price": 100000, "currency": "KRW"}],
        lambda market, ticker: prices.get(ticker),
    )[CURRENCY_KRW]
    share_sum = sum(r["profit_share_pct"] for r in two_gainers["rows"]
                    if r["profit_share_pct"] is not None)
    check(abs(share_sum - 100.0) < 1e-9, "이익 종목 2개의 수익 비중 합 = 100%")

    # 전 종목 현재가 미상
    unknown_only = build_portfolio([holdings[2]], lambda market, ticker: None)[CURRENCY_KRW]
    check(unknown_only["total_value"] is None and unknown_only["total_profit"] is None,
          "전 종목 현재가 미상이면 합계도 None (0원이라고 하지 않음)")

    single = evaluate_holding(holdings[0], None)
    check(single["price_available"] is False and single["cost"] == 800000,
          "evaluate_holding 단독 호출도 동일 규칙")


# =============================================================================
# 6. Supabase 미설정 폴백 — "준비중"이 에러가 아니어야 함
# =============================================================================
def _clear_supabase_env():
    saved = {}
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SCORECARD_ENABLED"):
        saved[key] = os.environ.pop(key, None)
    return saved


def _restore_env(saved):
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_supabase_fallback():
    print("\n[6] Supabase 클라이언트가 없을 때의 폴백")
    saved_env = _clear_supabase_env()
    original_flag = sdb.SUPABASE_PACKAGE_AVAILABLE
    try:
        # ① 패키지도 없고 Secrets 도 없음
        sdb.SUPABASE_PACKAGE_AVAILABLE = False
        status = supabase_status()
        check(status.available is False, "패키지·Secrets 둘 다 없으면 available=False")
        check("supabase" in status.reason and "Secrets" in status.reason,
              "사유에 패키지/Secrets 둘 다 언급")
        check(create_supabase_client() is None, "클라이언트 생성은 None 반환(예외 아님)")

        # ② 패키지는 있는데 Secrets 미등록
        sdb.SUPABASE_PACKAGE_AVAILABLE = True
        status = supabase_status()
        check(status.available is False and "SUPABASE_URL" in status.reason,
              "Secrets 미등록 사유에 어떤 키가 없는지 명시")
        check(create_supabase_client() is None, "Secrets 없으면 None (에러 아님)")

        # ③ Secrets 는 있는데 패키지 없음
        os.environ["SUPABASE_URL"] = "https://example.invalid"
        os.environ["SUPABASE_ANON_KEY"] = "dummy-not-a-real-key"
        sdb.SUPABASE_PACKAGE_AVAILABLE = False
        status = supabase_status()
        check(status.available is False and "패키지" in status.reason,
              "패키지 미설치 사유를 정확히 안내")
        check(status.config_present is True, "config_present=True 로 구분 가능")

        url, key = sdb.get_supabase_config()
        check(url == "https://example.invalid" and key == "dummy-not-a-real-key",
              "환경변수에서 접속 정보를 읽음 (소스에 하드코딩 없음)")

        # ④ 클라이언트가 None 인 상태의 CRUD 는 조용히 빈 값이 아니라 명확한 예외
        expect_raises(lambda: fetch_holdings(None, "user-1"), ScorecardError,
                      "클라이언트 없이 조회하면 ScorecardError")
        expect_raises(lambda: insert_holding(None, "user-1", make_lot(MARKET_KR, "005930", 1, 100)),
                      ScorecardError, "클라이언트 없이 저장하면 ScorecardError")
        expect_raises(lambda: delete_holding(None, "user-1", "row-1"), ScorecardError,
                      "클라이언트 없이 삭제하면 ScorecardError")
        expect_raises(lambda: sign_in(None, "a@b.c", "pw"), ScorecardError,
                      "클라이언트 없이 로그인하면 ScorecardError")
        try:
            fetch_holdings(None, "user-1")
        except ScorecardError as exc:
            check("준비되지 않았" in str(exc), "사용자에게 보여줄 한국어 사유가 담김")

        # ⑤ 클라이언트는 있는데 사용자 ID가 없는 경우
        expect_raises(lambda: fetch_holdings(FakeClient(), ""), ScorecardError,
                      "user_id 가 비면 조회 거부")
    finally:
        sdb.SUPABASE_PACKAGE_AVAILABLE = original_flag
        _restore_env(saved_env)

    check(sdb.SUPABASE_PACKAGE_AVAILABLE == original_flag, "테스트 후 모듈 상태 원복")


# =============================================================================
# 7. 가짜 클라이언트로 holdings CRUD 배선 검증
# =============================================================================
def test_crud_with_fake_client():
    print("\n[7] holdings CRUD (가짜 Supabase 클라이언트)")
    client = FakeClient(rows=[
        {"id": "row-1", "user_id": "user-uuid-1", "market": "KR", "ticker": "005930",
         "stock_name": "삼성전자", "quantity": "10", "avg_purchase_price": "100000",
         "currency": "KRW"},
        {"id": "row-9", "user_id": "other-user", "market": "KR", "ticker": "000660",
         "stock_name": "남의종목", "quantity": "1", "avg_purchase_price": "1",
         "currency": "KRW"},
    ])

    holdings = fetch_holdings(client, "user-uuid-1")
    check(len(holdings) == 1 and holdings[0]["ticker"] == "005930",
          "user_id 필터로 내 행만 조회됨(RLS 이중 방어)")
    op, filters, _ = client.store["calls"][-1]
    check(op == "select" and ("user_id", "user-uuid-1") in filters,
          "select 쿼리에 user_id 필터가 실제로 걸림")
    check(isinstance(holdings[0]["quantity"], float) and holdings[0]["quantity"] == 10.0,
          "문자열 numeric 을 float 으로 정규화")

    # 같은 종목 재입력 → update(가중평균), insert 아님
    action, merged = add_lot(client, "user-uuid-1", MARKET_KR, "5930", 3, 70000,
                             holdings=holdings)
    check(action == "merge", "이미 있는 종목은 merge")
    check(abs(merged["avg_purchase_price"] - 1210000 / 13) < 1e-9, "merge 결과 평균단가 재계산")
    op, filters, payload = client.store["calls"][-1]
    check(op == "update", "update 쿼리 호출")
    check(("id", "row-1") in filters and ("user_id", "user-uuid-1") in filters,
          "update 에 id + user_id 필터가 함께 걸림")
    check(abs(payload["avg_purchase_price"] - 1210000 / 13) < 1e-9, "update payload 값 확인")
    check(len(client.store["rows"]) == 2, "행이 늘어나지 않고 갱신됨")

    # 새 종목 → insert
    action, new_holding = add_lot(client, "user-uuid-1", MARKET_US, "nvda", 2, 200,
                                  stock_name="엔비디아")
    check(action == "insert", "처음 넣는 종목은 insert")
    op, _, payload = client.store["calls"][-1]
    check(op == "insert" and payload["user_id"] == "user-uuid-1", "insert payload 에 user_id 포함")
    check(payload["currency"] == "USD" and payload["ticker"] == "NVDA",
          "insert 시 통화·티커가 정규화되어 저장")

    us_holdings = [h for h in fetch_holdings(client, "user-uuid-1") if h["market"] == "US"]
    check(len(us_holdings) == 1, "저장 후 다시 조회하면 미국 종목 1건")
    check(find_holding(us_holdings, MARKET_US, "NVDA") is not None, "find_holding 조회 성공")
    check(find_holding(us_holdings, MARKET_KR, "005930") is None, "다른 시장은 매칭 안 됨")

    update_holding(client, "user-uuid-1", "row-1", 20, 90000, stock_name="삼성전자")
    check(any(r["id"] == "row-1" and r["quantity"] == 20 for r in client.store["rows"]),
          "update_holding 직접 호출도 정상")

    delete_holding(client, "user-uuid-1", "row-1")
    check(all(r["id"] != "row-1" for r in client.store["rows"]), "delete_holding 삭제 확인")
    op, filters, _ = client.store["calls"][-1]
    check(op == "delete" and ("user_id", "user-uuid-1") in filters, "delete 에도 user_id 필터")
    check(any(r["id"] == "row-9" for r in client.store["rows"]), "남의 행은 그대로 남음")

    # 네트워크 실패는 조용히 넘어가지 않고 예외
    failing = FakeClient(fail=True)
    expect_raises(lambda: fetch_holdings(failing, "user-uuid-1"), ScorecardError,
                  "조회 실패는 빈 목록이 아니라 ScorecardError")
    try:
        fetch_holdings(failing, "user-uuid-1")
    except ScorecardError as exc:
        check("실패" in str(exc) and "네트워크 오류" in str(exc), "원인 메시지를 그대로 전달")
    expect_raises(lambda: sign_in(failing, "a@b.c", "pw"), ScorecardError, "로그인 실패도 예외")

    # 인증 래퍼
    ok_client = FakeClient()
    response = sign_in(ok_client, "owner@example.com", "pw")
    check(sdb.user_id_of(getattr(response, "user", None)) == "user-uuid-1", "로그인 응답에서 user id 추출")
    check(ok_client.auth.last_credentials_keys == ["email", "password"],
          "Supabase Auth 에 email/password 형태로 전달")
    check(sdb.user_id_of({"id": "dict-user"}) == "dict-user", "dict 형태 user 도 지원")
    check(sdb.user_id_of(None) is None, "user 가 없으면 None")
    sdb.sign_out(ok_client)
    check(ok_client.auth.signed_out is True, "로그아웃 호출 전달")
    check(sdb.current_user(None) is None, "클라이언트 없으면 current_user None (예외 아님)")
    expect_raises(lambda: sign_in(ok_client, "", "pw"), ScorecardError, "이메일 없으면 거부")


# =============================================================================
# 8. SQL 스키마 — RLS 가 반드시 포함돼야 함
# =============================================================================
def test_sql_schema():
    print("\n[8] sql/scorecard_schema.sql (RLS 필수)")
    path = REPO_ROOT / "sql" / "scorecard_schema.sql"
    check(path.exists(), "스키마 파일 존재")
    if not path.exists():
        return
    sql = path.read_text(encoding="utf-8")
    lower = sql.lower()

    check("create table if not exists public.profiles" in lower, "profiles 테이블 생성문")
    check("create table if not exists public.holdings" in lower, "holdings 테이블 생성문")
    for column in ("user_id", "market", "ticker", "stock_name", "quantity",
                   "avg_purchase_price", "currency", "updated_at"):
        check(column in lower, f"holdings 컬럼 `{column}` 정의")

    check("alter table public.holdings enable row level security" in lower,
          "holdings RLS 활성화")
    check("alter table public.profiles enable row level security" in lower,
          "profiles RLS 활성화")
    policies = re.findall(r"create policy\s+(\w+)", lower)
    check(len(policies) >= 8, f"정책 8개 이상 정의됨(실제 {len(policies)}개)")
    for cmd in ("for select", "for insert", "for update", "for delete"):
        check(lower.count(cmd) >= 2, f"두 테이블 모두 `{cmd}` 정책 보유")
    check(lower.count("auth.uid() = user_id") >= 4, "holdings 정책 4종이 auth.uid() 로 본인 확인")
    check(lower.count("auth.uid() = id") >= 4, "profiles 정책 4종이 auth.uid() 로 본인 확인")

    check("revoke all on public.holdings from anon" in lower, "anon 롤 권한 회수(방어 심화)")
    check("holdings_user_ticker_unique" in lower, "(user_id, market, ticker) 유니크 제약")
    check("holdings_market_currency_match" in lower, "market ↔ currency 일치 CHECK (원/달러 혼용 차단)")
    check("check (quantity > 0)" in lower, "수량 양수 CHECK")

    # 크레덴셜이 실제 값으로 들어가 있으면 안 됨
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", lower), "실제 Supabase URL 미포함")
    check("eyj" not in lower, "JWT(anon key) 실제 값 미포함")
    check("service_role" in lower and "절대 넣지 마세요" in sql,
          "service_role 키 금지 경고가 문서화됨")


# =============================================================================
# 9. 화면 / 라우팅 배선 (스테이징 기본 숨김 + 기존 모듈 무손상)
# =============================================================================
def _install_streamlit_stub():
    """
    streamlit 미설치 환경에서도 views/scorecard_view.py 를 import 할 수 있게 최소 스텁을
    주입합니다(오프라인 검증용). 이미 진짜 streamlit 이 설치돼 있으면 아무것도 하지 않습니다.
    """
    try:
        import streamlit  # noqa: F401
        return False
    except ImportError:
        pass

    class _Secrets:
        def get(self, _name, default=None):
            return default

    class _Stub(types.ModuleType):
        secrets = _Secrets()

        def __getattr__(self, name):  # 어떤 위젯 호출이든 무해한 함수로
            def _noop(*args, **kwargs):
                return None
            return _noop

    stub = _Stub("streamlit")
    stub.secrets = _Secrets()
    sys.modules["streamlit"] = stub
    return True


def test_view_and_routing():
    print("\n[9] 화면·라우팅 배선")
    view_path = REPO_ROOT / "views" / "scorecard_view.py"
    check(view_path.exists(), "views/scorecard_view.py 존재")
    view_src = view_path.read_text(encoding="utf-8")

    check("NO_FX_CONVERSION_NOTICE" in view_src, "환율 변환 없음 고지를 화면에서 표시")
    check("st.error" in view_src, "실패를 st.error 로 사용자에게 노출(§0-1)")
    check("cache_resource" not in view_src.replace("@st.cache_resource 로 캐시하면 안 됩니다", ""),
          "Supabase 클라이언트를 캐시하지 않음(세션 공유 사고 방지)")
    check("st.session_state" in view_src, "클라이언트/세션은 st.session_state 에 보관")
    check(not re.search(r"open\([^)]*['\"]w", view_src), "화면 코드가 파일을 쓰지 않음(읽기 전용)")

    # 2026-08-11 오너 실사용 피드백 반영 회귀 방지 -----------------------------
    check('st.form("scorecard_add_form")' not in view_src,
          "보유종목 입력은 더 이상 st.form 을 안 씀(Enter 키 오submit 방지)")
    check('st.button("➕ 추가 / 평균단가 재계산"' in view_src,
          "입력은 명시적 버튼 클릭으로만 제출됨")
    check("_reset_input_fields" in view_src, "추가 성공 후 입력창을 비우는 로직 존재")
    check("find_ticker_by_name" in view_src, "종목명으로 티커 찾기 연동")
    check("NAME_LOOKUP_MARKETS = {MARKET_US}" in view_src,
          "종목명 자동조회는 미국 주식 전용(한국은 코드 직접 입력)")
    db_src = (REPO_ROOT / "utils" / "scorecard_db.py").read_text(encoding="utf-8")
    check(not re.search(r"open\([^)]*['\"]w", db_src), "데이터 모듈도 data/*.json 을 쓰지 않음")
    check("try:" in db_src and "except ImportError" in db_src,
          "supabase/streamlit import 를 try/except ImportError 로 감쌈")
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", db_src + view_src),
          "소스에 실제 Supabase URL 없음")
    check("SUPABASE_SERVICE_ROLE" not in db_src and "service_role_key" not in db_src,
          "service_role 키를 읽는 코드 없음")

    # 라우팅: 기본 숨김 + 기존 두 화면 무손상
    app_src = (REPO_ROOT / "visiblehand.py").read_text(encoding="utf-8")
    check("render_scorecard_page" in app_src, "visiblehand.py 에 내 성적표 라우팅 추가")
    check("show_scorecard = False" in app_src, "기본값은 숨김(False)")
    check("is_scorecard_visible(admin_mode)" in app_src,
          "관리자 미리보기/명시 플래그일 때만 진입점 노출")
    check("except Exception as _scorecard_import_exc" in app_src,
          "모듈 로드 실패해도 기존 화면이 죽지 않도록 import 가드")
    for legacy in ("render_us_stocks_page()", "render_macro_page()", "render_pegy_page()"):
        check(legacy in app_src, f"기존 라우팅 `{legacy}` 유지")
    check(app_src.index("if show_scorecard:") < app_src.index("elif selected_market == MARKET_US:"),
          "라우팅 분기 순서: 내 성적표 → 기존 분기(기존 기본 경로는 그대로 pegy)")

    # 기존 두 모듈 파일을 건드리지 않았는지(이번 작업 범위 확인)
    for untouched in ("views/pegy_view.py", "views/us_stocks_view.py", "utils/scoring.py",
                      "utils/constants.py"):
        src = (REPO_ROOT / untouched).read_text(encoding="utf-8")
        check("scorecard" not in src.lower(), f"{untouched} 에 내 성적표 관련 수정 없음")

    # 실제 import 가능한지 (supabase 패키지 없는 상태)
    stubbed = _install_streamlit_stub()
    try:
        module = importlib.import_module("views.scorecard_view")
        check(True, "views.scorecard_view import 성공 (supabase 패키지 없이도)")
        saved_env = _clear_supabase_env()
        try:
            check(module.is_scorecard_enabled() is False, "SCORECARD_ENABLED 기본값 = 꺼짐")
            check(module.is_scorecard_visible(False) is False, "일반 방문자에게는 메뉴 비노출")
            check(module.is_scorecard_visible(True) is True, "관리자 모드에서는 미리보기 가능")
            os.environ["SCORECARD_ENABLED"] = "1"
            importlib.reload(module)
            check(module.is_scorecard_enabled() is True, "플래그를 켜면 활성화됨")

            # 2026-08-11 오너 실사용 피드백 반영분 — UI 헬퍼 단위 검증 -----------
            check(module._parse_positive_number("1,664,333", "매입가") == 1664333.0,
                  "콤마 섞인 숫자 입력도 파싱됨")
            check(module._parse_positive_number(" 10 ", "수량") == 10.0,
                  "앞뒤 공백은 무시하고 파싱")
            expect_raises(lambda: module._parse_positive_number("", "수량"), ValueError,
                          "빈 값은 예외(0으로 채우지 않음)")
            expect_raises(lambda: module._parse_positive_number("하이닉스", "매입가"), ValueError,
                          "숫자가 아닌 값은 예외")
            expect_raises(lambda: module._parse_positive_number("0", "수량"), ValueError,
                          "0은 거부(수량·매입가 모두 0보다 커야 함)")
            expect_raises(lambda: module._parse_positive_number("-5", "수량"), ValueError,
                          "음수는 거부")

            check(bool(module._KR_TICKER_LIKE.fullmatch("005930")), "6자리 숫자 코드는 코드로 인정")
            check(bool(module._KR_TICKER_LIKE.fullmatch("00680K")), "영숫자 우선주 코드도 코드로 인정")
            check(not module._KR_TICKER_LIKE.fullmatch("하이닉스"),
                  "한글 종목명은 코드 형식으로 인정하지 않음(오너가 겪은 실사용 버그 재현 방지)")
            check(not module._KR_TICKER_LIKE.fullmatch("삼성전자우"),
                  "한글 종목명(우선주 포함)도 코드로 인정하지 않음")

            check(module.NAME_LOOKUP_MARKETS == {module.MARKET_US},
                  "종목명 자동조회 대상 시장은 미국뿐")

            fake_state = {"scorecard_ticker": "005930", "scorecard_name": "삼성전자",
                          "scorecard_qty": "10", "scorecard_price": "70000",
                          "scorecard_market": module.MARKET_KR}
            module.st.session_state = fake_state
            module._reset_input_fields()
            check(
                all(k not in fake_state
                    for k in ("scorecard_ticker", "scorecard_name", "scorecard_qty", "scorecard_price")),
                "추가 성공 후 입력 필드 4개가 session_state 에서 지워짐(다음 입력이 이어붙지 않게)",
            )
            check("scorecard_market" in fake_state, "시장 선택(라디오)은 초기화 대상이 아님(그대로 유지)")
        finally:
            _restore_env(saved_env)
            importlib.reload(module)
    except Exception as exc:  # noqa: BLE001
        check(False, "views.scorecard_view import 성공 (supabase 패키지 없이도)",
              f"({type(exc).__name__}: {exc})")
    finally:
        if stubbed:
            sys.modules.pop("streamlit", None)
            sys.modules.pop("views.scorecard_view", None)


# =============================================================================
# 10. 의존성·문서 배선
# =============================================================================
def test_requirements_and_docs():
    print("\n[10] requirements.txt · 문서 배선")
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in req.splitlines()]
    check(any(ln == "supabase" or ln.startswith("supabase") and not ln.startswith("#")
              for ln in lines), "requirements.txt 에 supabase 추가됨")
    for kept in ("streamlit==1.50.0", "plotly", "pandas", "bcrypt"):
        check(any(ln.startswith(kept) for ln in lines), f"기존 의존성 `{kept}` 유지")

    order_doc = (REPO_ROOT / "SCORECARD_WORK_ORDER.md")
    check(order_doc.exists(), "작업지시서 원본 보존")


def main():
    print("=" * 74)
    print("📊 내 성적표 모듈 오프라인 검증 (Supabase 미연결 · 네트워크 불필요)")
    print("=" * 74)
    test_normalization()
    test_weighted_average()
    test_currency_separation()
    test_universe_lookup()
    test_name_lookup()
    test_portfolio()
    test_supabase_fallback()
    test_crud_with_fake_client()
    test_sql_schema()
    test_view_and_routing()
    test_requirements_and_docs()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
