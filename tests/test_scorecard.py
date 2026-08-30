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

# 저장소 루트를 `sys.path` 에 얹는 일과, 무음 통과 방지 하네스(FAILURES 목록 · check() ·
# autouse 픽스처)는 파일마다 복사하지 않고 `tests/conftest.py` 한 곳에만 둡니다
# (2026-08-30 — TASK_HISTORY #168 H-1 "복사 하나 빠뜨림" 재발 방지). 이 import 가 conftest 를
# 먼저 불러오므로 `python tests/test_x.py` 직접 실행 경로에서도 아래 import 들이 정상 동작하고,
# check() 실패를 pytest 빨간불로 승격시키는 `_assert_no_check_failures` 픽스처는 conftest 의
# autouse 라 이 파일의 모든 테스트에 자동 적용됩니다(이 파일에 따로 쓸 것이 없습니다).
from conftest import FAILURES, check  # noqa: E402

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
    resolve_stock_query,
    sign_in,
    sort_holding_rows,
    split_by_currency,
    supabase_status,
    update_holding,
    valuation_summary,
    weighted_average_price,
)

REPO_ROOT = Path(__file__).parent.parent

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
        self._range = None

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def range(self, start, end):
        """PostgREST 페이지네이션(양끝 포함). 2026-08-29 재감사(L-6) —
        `fetch_holdings()` 가 `_execute_all()` 로 바뀌며 `.range()` 를 걸기 시작해서 추가.
        (`tests/test_duel_db.py::FakeQuery.range()` 와 같은 규약.)
        """
        self._range = (start, end)
        return self

    def _matches(self, row):
        def same(stored, wanted):
            # 2026-08-29 재감사(스코어카드 모듈) M-1 — 낙관적 잠금(`expected_quantity`)이
            # `.eq("quantity", 10.0)` 처럼 **앱이 정규화한 float** 로 거는데, 이 가짜 저장소는
            # `"10"`(문자열)을 그대로 들고 있습니다. 실제 PostgREST/Postgres numeric 컬럼은
            # `10` 과 `10.0` 을 같은 값으로 비교하지만, 예전 코드처럼 `str(10.0) == str("10")`
            # (`"10.0" == "10"`) 로 비교하면 항상 거짓이 되어, 실제로는 아무것도 바뀌지 않았는데
            # "다른 곳에서 먼저 수정됐다" 는 오탐이 납니다. 숫자로 먼저 비교를 시도해 실제
            # DB 와 같은 결과를 흉내내고, 숫자로 못 바꾸는 값(문자열 id 등)만 문자열로 비교합니다.
            try:
                return float(stored) == float(wanted)
            except (TypeError, ValueError):
                return str(stored) == str(wanted)
        return all(same(row.get(col), val) for col, val in self.filters)

    def execute(self):
        self.store["calls"].append((self.op, list(self.filters), self.payload))
        if self.fail:
            raise RuntimeError("네트워크 오류(합성)")
        rows = self.store["rows"]
        if self.op == "select":
            matched = [dict(r) for r in rows if self._matches(r)]
            if self._range is not None:
                start, end = self._range
                matched = matched[start:end + 1]      # PostgREST range() 는 양끝 포함
            return FakeResponse(matched)
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
        # 2026-08-13 비밀번호 재설정(#109) 검증용 기록. ⚠️ 아래 어디에도 비밀번호 '값'은
        # 보관하지 않습니다(기존 sign_in 기록 관례와 동일 — 키/길이만).
        self.reset_requests = []          # reset_password_for_email 로 넘어온 이메일 목록
        self.verify_otp_calls = []        # verify_otp 로 넘어온 파라미터(코드는 값 그대로,
                                          #   합성 코드라 비밀정보가 아님)
        self.update_user_keys = []        # update_user 로 넘어온 키 목록만
        self.update_user_password_len = None
        self.verify_fail = False          # 코드가 틀린 상황을 따로 흉내내기 위한 스위치
        self.verify_returns_session = True

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

    # --- 비밀번호 재설정 (2026-08-13, #109) --------------------------------
    # 실제 supabase 패키지의 공식 이름(문서 확인)과 같은 시그니처로 흉내냅니다.
    #   https://supabase.com/docs/reference/python/auth-resetpasswordforemail
    #   https://supabase.com/docs/reference/python/auth-verifyotp
    #   https://supabase.com/docs/reference/python/auth-updateuser
    def reset_password_for_email(self, email, options=None):
        self.reset_requests.append(email)
        if self.fail:
            raise RuntimeError("For security purposes, you can only request this after 60 seconds(합성)")
        return types.SimpleNamespace(data={})

    def verify_otp(self, params):
        self.verify_otp_calls.append(dict(params))
        if self.fail or self.verify_fail:
            raise RuntimeError("Token has expired or is invalid(합성)")
        session = (types.SimpleNamespace(access_token="synthetic-token")
                   if self.verify_returns_session else None)
        return types.SimpleNamespace(
            session=session,
            user=types.SimpleNamespace(id="user-uuid-1", email=params.get("email")),
        )

    def update_user(self, attributes):
        self.update_user_keys.append(sorted(attributes.keys()))
        password = attributes.get("password")
        self.update_user_password_len = len(password) if password else 0
        if self.fail:
            raise RuntimeError("Password should be at least 6 characters(합성)")
        return types.SimpleNamespace(
            user=types.SimpleNamespace(id="user-uuid-1", email="owner@example.com")
        )


class FakeLegacyAuth(FakeAuth):
    """
    옛 이름(`reset_password_email`)만 가진 패키지 버전을 흉내냅니다.
    utils/scorecard_db.py 가 새 이름 → 옛 이름 순으로 찾아가는지 확인하기 위한 것입니다.
    """
    reset_password_for_email = None  # getattr 로는 잡히지만 callable 이 아님

    def reset_password_email(self, email, options=None):
        self.reset_requests.append(email)
        if self.fail:
            raise RuntimeError("rate limit(합성)")
        return types.SimpleNamespace(data={})


class FakeNoResetAuth(FakeAuth):
    """재설정 함수가 아예 없는(=아주 오래된/이상한) 패키지 버전."""
    reset_password_for_email = None
    reset_password_email = None


class FakeClient:
    def __init__(self, rows=None, fail=False, auth_class=FakeAuth):
        self.store = {"rows": list(rows or []), "calls": []}
        self.fail = fail
        self.auth = auth_class(fail=fail)

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
    check(format_amount(float("nan"), CURRENCY_KRW) == "—",
          "NaN도 0원/nan원이 아니라 값 없음과 동일하게 — (2026-08-30 #175/#178)")
    check(format_amount(float("inf"), CURRENCY_USD) == "—", "Infinity도 동일하게 —")
    check(format_amount(float("-inf"), CURRENCY_KRW) == "—", "음의 Infinity도 동일하게 —")


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
    for rel in ("utils/scorecard_db.py",):
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

        # 2026-08-11(TASK_HISTORY #84) — broad_kr_prices 폴백(하위호환: 기본값 None이면 위 동작 그대로)
        broad_kr_prices = {"777777": {"code": "777777", "name": "합성전종목", "price": 5000.0, "market": "KOSDAQ"},
                            "999999": {"code": "999999", "name": "유니버스밖상위매치", "price": 1234.0, "market": "KOSPI"}}
        broad_lookup = make_price_lookup(indexes, broad_kr_prices=broad_kr_prices)
        check(broad_lookup(MARKET_KR, "5930") == 100000.0,
              "상위 200 유니버스 안에 있으면 broad_kr_prices보다 그쪽을 우선 사용")
        check(broad_lookup(MARKET_KR, "999999") == 1234.0,
              "상위 200 밖이지만 broad_kr_prices에 있으면 2차로 그 가격 사용")
        check(broad_lookup(MARKET_KR, "777777") == 5000.0, "broad_kr_prices 전용 종목도 조회됨")
        check(broad_lookup(MARKET_KR, "000000") is None, "broad_kr_prices에도 없으면 여전히 None(추정 금지)")
        check(broad_lookup(MARKET_US, "fake") == 200.0, "미국 시장은 broad_kr_prices 영향 없이 그대로 동작")
        check(lookup(MARKET_KR, "999999") is None,
              "broad_kr_prices=None(기본값)인 기존 lookup은 이전 동작 그대로 — 하위호환 확인")

        # 2026-08-12(TASK_HISTORY #92) — broad_us_prices 폴백(미국판). 위 한국판과 완전히 같은 규칙.
        broad_us_prices = {"CAVA": {"symbol": "CAVA", "name": "Cava Group, Inc.", "price": 68.4},
                            "FAKE": {"symbol": "FAKE", "name": "유니버스에도 있는 종목", "price": 999.0},
                            "NOPRICE": {"symbol": "NOPRICE", "name": "가격 있는 쪽", "price": 33.0}}
        us_lookup = make_price_lookup(indexes, broad_us_prices=broad_us_prices)
        check(us_lookup(MARKET_US, "FAKE") == 200.0,
              "상위 550 유니버스 안에 있으면 broad_us_prices보다 그쪽을 우선 사용")
        check(us_lookup(MARKET_US, "cava") == 68.4,
              "상위 550 밖이지만 broad_us_prices에 있으면 2차로 그 가격 사용(소문자 입력도 정규화)")
        check(us_lookup(MARKET_US, "NOWHERE") is None,
              "broad_us_prices에도 없으면 여전히 None(추정 금지)")
        check(us_lookup(MARKET_KR, "999999") is None,
              "한국 시장은 broad_us_prices 영향을 전혀 받지 않음(원/달러 혼용 차단)")
        check(lookup(MARKET_US, "CAVA") is None,
              "broad_us_prices=None(기본값)인 기존 lookup은 이전 동작 그대로 — 하위호환 확인")

        both_lookup = make_price_lookup(indexes, broad_kr_prices=broad_kr_prices,
                                        broad_us_prices=broad_us_prices)
        check(both_lookup(MARKET_KR, "777777") == 5000.0 and both_lookup(MARKET_US, "CAVA") == 68.4,
              "두 폴백을 동시에 넘겨도 시장별로 각자 자기 목록만 사용")
        check(both_lookup(MARKET_KR, "CAVA") is None and both_lookup(MARKET_US, "777777") is None,
              "상대 시장 목록을 교차 조회하는 경로는 없음")

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
# 4-0-1. 코스피+코스닥+ETF 전체 상장종목 마스터 목록 (2026-08-11, TASK_HISTORY #83)
# =============================================================================
def test_kr_ticker_master():
    print("\n[4-0-1] 전체 상장종목 마스터 목록 — load_kr_ticker_master (가격 없이 이름↔코드만)")
    synthetic_master = {
        "metadata": {"generated_at": "2026-08-11 16:05", "count": 3,
                      "source": "FinanceDataReader StockListing('KRX') + StockListing('ETF/KR')"},
        "stocks": [
            {"code": "005380", "name": "합성모터스", "market": "KOSPI", "type": "STOCK"},
            {"code": "247540", "name": "합성코스닥종목", "market": "KOSDAQ", "type": "STOCK"},
            {"code": "069500", "name": "합성ETF200", "market": "KOSPI", "type": "ETF"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "kr_ticker_master.json"), "w", encoding="utf-8") as f:
            json.dump(synthetic_master, f, ensure_ascii=False)

        master_index, master_meta = sdb.load_kr_ticker_master(data_dir=tmp)
        check(set(master_index.keys()) == {"005380", "247540", "069500"},
              "코드 3개(코스피 주식/코스닥 주식/ETF) 전부 인덱싱됨")
        check(master_index["069500"]["type"] == "ETF", "ETF도 type 필드와 함께 포함됨(오너 요청)")
        check(master_index["247540"]["market"] == "KOSDAQ", "코스닥 종목도 포함됨(오너 요청)")
        check("price" not in master_index["005380"] or master_index["005380"].get("price") is None,
              "가격 필드가 없음 — 이 목록은 이름↔코드 조회 전용, 밸류에이션 출처가 아님")
        check(master_meta.get("count") == 3, "metadata 도 함께 반환")

        empty_index, empty_meta = sdb.load_kr_ticker_master(data_dir=os.path.join(tmp, "없음"))
        check(empty_index == {} and empty_meta is None,
              "파일이 아직 없으면(다음 자동 수집 전) 에러 대신 빈 dict — 화면은 정상 작동")

    # 저장소에 실제 파일이 아직 없을 수 있습니다(이번 세션에서 신설 — 다음 자동 수집 후 생성).
    # 있으면 개수만 참고로 출력하고, 없어도 실패로 치지 않습니다(collector가 그렇게 설계됨).
    real_master, real_meta = sdb.load_kr_ticker_master()
    if real_master:
        print(f"  ℹ️ 저장소에 이미 kr_ticker_master.json 존재 — {len(real_master)}건")
    else:
        print("  ℹ️ 저장소에 kr_ticker_master.json 아직 없음(다음 자동 수집 후 생성 예정) — 정상")


# =============================================================================
# 4-0-2. 코스피+코스닥 전 종목 종가 (2026-08-11, TASK_HISTORY #84)
# =============================================================================
def test_kr_all_market_prices():
    print("\n[4-0-2] 전 종목 종가 목록 — load_kr_all_market_prices (밸류에이션 없이 가격만)")
    synthetic_prices = {
        "metadata": {"generated_at": "2026-08-11 17:00", "count": 2,
                      "source": "네이버 금융 시가총액 순위 페이지 전체 페이지"},
        "stocks": [
            {"code": "005380", "name": "합성모터스", "price": 250000.0, "market": "KOSPI"},
            {"code": "247540", "name": "합성코스닥종목", "price": 15000.0, "market": "KOSDAQ"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "kr_all_market_prices.json"), "w", encoding="utf-8") as f:
            json.dump(synthetic_prices, f, ensure_ascii=False)

        price_index, price_meta = sdb.load_kr_all_market_prices(data_dir=tmp)
        check(set(price_index.keys()) == {"005380", "247540"}, "코드 2개 전부 인덱싱됨")
        check(price_index["005380"]["price"] == 250000.0, "종가가 그대로 보존됨")
        check(price_meta.get("count") == 2, "metadata 도 함께 반환")

        empty_index, empty_meta = sdb.load_kr_all_market_prices(data_dir=os.path.join(tmp, "없음"))
        check(empty_index == {} and empty_meta is None,
              "파일이 아직 없으면(다음 자동 수집 전) 에러 대신 빈 dict")

    # 저장소에 실제 파일이 아직 없을 수 있습니다(이번 세션에서 신설).
    real_prices, real_meta = sdb.load_kr_all_market_prices()
    if real_prices:
        print(f"  ℹ️ 저장소에 이미 kr_all_market_prices.json 존재 — {len(real_prices)}건")
    else:
        print("  ℹ️ 저장소에 kr_all_market_prices.json 아직 없음(다음 자동 수집 후 생성 예정) — 정상")


# =============================================================================
# 4-0-3. 미국 전 종목 현재가 (2026-08-12, TASK_HISTORY #92)
# =============================================================================
def test_us_all_market_prices():
    print("\n[4-0-3] 미국 전 종목 현재가 목록 — load_us_all_market_prices (밸류에이션 없이 가격만)")
    synthetic_prices = {
        "metadata": {"collected_at_kst": "2026-08-12 06:10", "count": 2,
                      "source": "stockanalysis.com 스크리너 데이터 엔드포인트", "currency": "USD"},
        "stocks": [
            {"symbol": "CAVA", "name": "Cava Group, Inc.", "price": 68.4},
            {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc.", "price": 516.38},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "us_all_market_prices.json"), "w", encoding="utf-8") as f:
            json.dump(synthetic_prices, f, ensure_ascii=False)

        price_index, price_meta = sdb.load_us_all_market_prices(data_dir=tmp)
        check(set(price_index.keys()) == {"CAVA", "BRK.B"}, "티커 2개 전부 인덱싱됨(점 포함 티커도 그대로)")
        check(price_index["CAVA"]["price"] == 68.4, "현재가가 그대로 보존됨")
        check(price_meta.get("count") == 2, "metadata 도 함께 반환")

        empty_index, empty_meta = sdb.load_us_all_market_prices(data_dir=os.path.join(tmp, "없음"))
        check(empty_index == {} and empty_meta is None,
              "파일이 아직 없으면(다음 자동 수집 전) 에러 대신 빈 dict")

    # 저장소에 실제 파일이 아직 없을 수 있습니다(이번 세션에서 신설).
    real_prices, real_meta = sdb.load_us_all_market_prices()
    if real_prices:
        print(f"  ℹ️ 저장소에 이미 us_all_market_prices.json 존재 — {len(real_prices)}건")
    else:
        print("  ℹ️ 저장소에 us_all_market_prices.json 아직 없음(다음 자동 수집 후 생성 예정) — 정상")


# =============================================================================
# 4-0-4. 미국 상장 ETF 현재가 (2026-08-12, TASK_HISTORY #93)
# =============================================================================
def test_us_all_etf_prices():
    print("\n[4-0-4] 미국 ETF 현재가 목록 — load_us_all_etf_prices (오너 지시로 ETF 제외 정책 뒤집음)")
    synthetic_etfs = {
        "metadata": {"collected_at_kst": "2026-08-12 06:11", "count": 2,
                      "source": "https://stockanalysis.com/etf/screener/__data.json", "currency": "USD"},
        "stocks": [
            {"symbol": "KORU", "name": "Direxion Daily MSCI South Korea Bull 3X ETF", "price": 17.36},
            {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "price": 691.59},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "us_all_etf_prices.json"), "w", encoding="utf-8") as f:
            json.dump(synthetic_etfs, f, ensure_ascii=False)

        etf_index, etf_meta = sdb.load_us_all_etf_prices(data_dir=tmp)
        check(set(etf_index.keys()) == {"KORU", "VOO"}, "ETF 티커 2개 전부 인덱싱됨")
        check(etf_index["KORU"]["price"] == 17.36, "ETF 현재가가 그대로 보존됨(오너 실사용 사례: 코러)")
        check(etf_meta.get("count") == 2, "metadata 도 함께 반환")

        # 주식 목록과 **파일이 다르다**는 사실 확인 — 한쪽만 있어도 다른 쪽은 조용히 빈 dict.
        stock_index, _ = sdb.load_us_all_market_prices(data_dir=tmp)
        check(stock_index == {},
              "ETF 파일만 있고 주식 파일이 없으면 주식 쪽은 빈 dict — 두 파일이 서로 독립")

        empty_index, empty_meta = sdb.load_us_all_etf_prices(data_dir=os.path.join(tmp, "없음"))
        check(empty_index == {} and empty_meta is None,
              "파일이 아직 없으면(다음 자동 수집 전) 에러 대신 빈 dict")

        # 화면(scorecard_view)이 하는 것과 같은 방식으로 두 목록을 합쳐 현재가 조회가 되는지.
        us_index = build_universe_index(SYNTHETIC_US_SNAPSHOT, MARKET_US)
        merged = {**etf_index}
        lookup = make_price_lookup({MARKET_KR: {}, MARKET_US: us_index}, broad_us_prices=merged)
        check(lookup(MARKET_US, "koru") == 17.36,
              "상위 550 유니버스 밖 ETF도 소문자 입력으로 현재가 조회됨 — '현재가 없음' 폴백 대체")
        check(lookup(MARKET_KR, "KORU") is None,
              "한국 시장 조회에는 미국 ETF 목록이 절대 쓰이지 않음(원/달러 혼용 차단)")

    real_etfs, real_meta = sdb.load_us_all_etf_prices()
    if real_etfs:
        print(f"  ℹ️ 저장소에 이미 us_all_etf_prices.json 존재 — {len(real_etfs)}건")
    else:
        print("  ℹ️ 저장소에 us_all_etf_prices.json 아직 없음(다음 자동 수집 후 생성 예정) — 정상")


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


def test_resolve_stock_query():
    print("\n[4-2] 통합 종목 입력(코드/티커/이름 한 칸) — resolve_stock_query "
          "(2026-08-11 오너 지시: \"종목코드/티커/종목명 이게 전부 다 한곳에서\")")
    kr_index = build_universe_index(SYNTHETIC_KR_SNAPSHOT, MARKET_KR)
    us_index = build_universe_index(SYNTHETIC_US_SNAPSHOT, MARKET_US)
    indexes = {MARKET_KR: kr_index, MARKET_US: us_index}

    ticker, name, reason = resolve_stock_query(MARKET_KR, "005930", indexes)
    check(ticker == "005930" and name == "합성전자" and reason is None,
          "한국: 6자리 코드 직접 입력 → 즉시 확정")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "5930", indexes)
    check(ticker == "005930" and name == "합성전자",
          "한국: 앞자리 0 빠진 코드도 복원해서 인식")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "합성전자", indexes)
    check(ticker == "005930" and name == "합성전자" and reason is None,
          "한국: 종목명만 입력해도 인식(2026-08-11 전에는 미국 전용이었던 제한 해제)")

    ticker, name, reason = resolve_stock_query(MARKET_US, "FAKE", indexes)
    check(ticker == "FAKE" and reason is None, "미국: 티커 직접 입력 → 즉시 확정")

    ticker, name, reason = resolve_stock_query(MARKET_US, "Fake Corp", indexes)
    check(ticker == "FAKE" and name == "Fake Corp" and reason is None,
          "미국: 회사 이름으로 입력해도 인식")

    # 유니버스 밖 종목 — 코드처럼 생겼으면 이름을 몰라도 그대로 받아들입니다(§0-1: 지어내지
    # 않되, 정직한 '현재가 없음' 표시로 넘어갈 수 있게 코드 자체는 거부하지 않음).
    ticker, name, reason = resolve_stock_query(MARKET_KR, "005380", indexes)
    check(ticker == "005380" and name is None and reason is None,
          "한국: 유니버스 밖이라도 코드 형식이면 그대로 채택(현재가 없음으로 표시될 예정)")

    ticker, name, reason = resolve_stock_query(MARKET_US, "AAPL", indexes)
    check(ticker == "AAPL" and name is None and reason is None,
          "미국: 유니버스 밖이라도 티커 형식이면 그대로 채택")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "존재하지않는이름", indexes)
    check(ticker is None and reason, "코드 형식도 아니고 이름도 못 찾으면 추측하지 않고 실패")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "", indexes)
    check(ticker is None and "입력해" in (reason or ""), "빈 입력은 즉시 실패")

    exact_dup_snapshot = {
        "metadata": {}, "stocks": [
            {"name": "완전동일이름", "code": "333333", "price": 1000.0},
            {"name": "완전동일이름", "code": "444444", "price": 2000.0},
        ],
    }
    exact_dup_index = build_universe_index(exact_dup_snapshot, MARKET_KR)
    ticker, name, reason = resolve_stock_query(
        MARKET_KR, "완전동일이름", {MARKET_KR: exact_dup_index, MARKET_US: {}}
    )
    check(ticker is None and "여러 개" in (reason or ""),
          "이름이 여러 종목과 겹치면(코드 형식도 아니므로) 추측하지 않고 실패")

    # -- broad_index (2026-08-11, TASK_HISTORY #83) — 상위 200 밖(코스닥·ETF 포함) 종목 --
    broad_snapshot = {
        "metadata": {}, "stocks": [
            {"code": "005380", "name": "합성모터스", "market": "KOSPI", "type": "STOCK"},
            {"code": "069500", "name": "합성ETF200", "market": "KOSPI", "type": "ETF"},
            {"code": "111111", "name": "겹치는이름", "market": "KOSDAQ", "type": "STOCK"},
            {"code": "222222", "name": "겹치는이름", "market": "KOSDAQ", "type": "STOCK"},
        ],
    }
    broad_index = build_universe_index(broad_snapshot, MARKET_KR)

    # 005380은 앞서(line 497 부근) broad_index 없이는 이름을 모른 채(코드만) 채택됐던 코드.
    # 이제 broad_index를 넘기면 같은 코드라도 이름까지 알아냅니다.
    ticker, name, reason = resolve_stock_query(MARKET_KR, "005380", indexes, broad_index=broad_index)
    check(ticker == "005380" and name == "합성모터스" and reason is None,
          "상위 200 밖 코드도 broad_index에 있으면 이름까지 알아냄(코드 직접 일치)")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "합성모터스", indexes, broad_index=broad_index)
    check(ticker == "005380" and name == "합성모터스" and reason is None,
          "상위 200 밖 종목도 broad_index 안에서는 이름만으로 찾을 수 있음")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "합성ETF200", indexes, broad_index=broad_index)
    check(ticker == "069500" and name == "합성ETF200" and reason is None,
          "ETF도 이름으로 찾을 수 있음(오너 요청 — \"ETF까지 포함해야하니까\")")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "겹치는이름", indexes, broad_index=broad_index)
    check(ticker is None and "여러 개" in (reason or ""),
          "broad_index 안에서도 이름이 여러 개면 추측하지 않고 실패")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "존재하지않는이름", indexes, broad_index=broad_index)
    check(ticker is None and "코스피·코스닥·국내ETF 전체" in (reason or ""),
          "broad_index까지 다 뒤졌는데도 없으면 '상위 200 밖일 수도'가 아니라 "
          "더 정확한 문구로 실패 이유를 알려줌(이미 훨씬 넓게 찾아봤으므로)")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "999000", indexes, broad_index=broad_index)
    check(ticker == "999000" and name is None,
          "broad_index에도 없지만 코드 형식이면(정말 아무 목록에도 없는 신규상장 등) "
          "여전히 코드 그대로 채택됨(기존 동작 유지)")

    ticker, name, reason = resolve_stock_query(MARKET_KR, "005380", indexes, broad_index=None)
    check(ticker == "005380" and name is None,
          "broad_index를 안 넘기면(기존 호출부) 예전과 완전히 동일하게 동작(하위 호환)")


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
# 5-1. 보유종목 표 정렬 (2026-08-11 오너 요청 — 오름차순/내림차순 필터)
# =============================================================================
def test_sort_holding_rows():
    print("\n[5-1] 보유종목 표 정렬 — sort_holding_rows (값 없는 행은 항상 맨 뒤)")
    prices = {"005930": 100000.0, "051910": 250000.0, "000660": None}
    portfolio = build_portfolio(
        [
            {"market": "KR", "ticker": "005930", "stock_name": "합성전자",
             "quantity": 10, "avg_purchase_price": 80000, "currency": "KRW"},
            {"market": "KR", "ticker": "051910", "stock_name": "합성화학",
             "quantity": 5, "avg_purchase_price": 300000, "currency": "KRW"},
            {"market": "KR", "ticker": "000660", "stock_name": "합성미검증",
             "quantity": 3, "avg_purchase_price": 10000, "currency": "KRW"},
        ],
        lambda market, ticker: prices.get(ticker),
    )[CURRENCY_KRW]
    rows = portfolio["rows"]

    by_pct_asc = sdb.sort_holding_rows(rows, "profit_pct", ascending=True)
    check([r["ticker"] for r in by_pct_asc] == ["051910", "005930", "000660"],
          "수익률 오름차순 — 손실(화학, -16.67%) → 이익(전자, +25%), 현재가 없는 종목은 항상 맨 뒤")

    by_pct_desc = sdb.sort_holding_rows(rows, "profit_pct", ascending=False)
    check([r["ticker"] for r in by_pct_desc] == ["005930", "051910", "000660"],
          "수익률 내림차순 — 방향만 뒤집히고 값 없는 종목은 여전히 맨 뒤")

    by_qty_asc = sdb.sort_holding_rows(rows, "quantity", ascending=True)
    check([r["ticker"] for r in by_qty_asc] == ["000660", "051910", "005930"],
          "수량은 전 종목이 값이 있으므로 순서대로 전부 정렬됨(3<5<10)")

    by_name = sdb.sort_holding_rows(rows, "_label", ascending=True)
    check([r["ticker"] for r in by_name] == ["000660", "005930", "051910"],
          "종목명 가나다순 정렬(합성미검증<합성전자<합성화학)")

    check(sdb.sort_holding_rows(rows, "weight_pct", ascending=True) is not rows,
          "원본 리스트를 바꾸지 않고 새 리스트를 반환함")
    check(rows[0]["ticker"] == "005930", "원본 rows 순서는 정렬 후에도 그대로 보존됨")

    labels = [label for label, _field in sdb.SORT_FIELD_OPTIONS]
    check("수익률" in labels and "종목명" in labels and "비중" in labels,
          "화면 정렬 selectbox 옵션에 수익률·종목명·비중이 전부 있음")


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
        check("supabase" in status.reason and "환경변수" in status.reason,
              "사유에 패키지/접속정보 둘 다 언급")
        # 2026-08-17 — 이 문구는 공개된 /scorecard·/report 의 '준비중' 안내로 **일반 사용자
        # 화면에 그대로** 나갑니다. 컷오버 후 실제 배포처는 Render 이고, 이 함수는 아직
        # 살아있는 Streamlit 쪽(views/)도 함께 쓰므로 **특정 플랫폼 이름이 들어가면 안 됩니다.**
        for platform in ("Streamlit Cloud", "Render", "Settings → Secrets"):
            check(platform not in status.reason,
                  f"사유 문구에 플랫폼 이름('{platform}')이 들어있지 않음(중립적 표현)")
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


def test_m1_add_lot_merge_uses_optimistic_locking_and_rejects_stale_reads():
    """
    🔴 2026-08-29 재감사 M-1 회귀 고정 — 두 탭(또는 두 요청)이 **같은 종목을 거의 동시에**
    수정하면, `add_lot()` 의 병합은 자신이 시작할 때 읽은 `existing["quantity"]` 를 기준으로
    "그 사이에 남이 먼저 바꿨는지"를 확인해야 합니다. 확인 없이 그냥 덮어쓰면 먼저 저장된
    변경이 조용히 사라집니다(§0-1).
    """
    client = FakeClient(rows=[
        {"id": "row-1", "user_id": "user-uuid-1", "market": "KR", "ticker": "005930",
         "stock_name": "삼성전자", "quantity": "10", "avg_purchase_price": "100000",
         "currency": "KRW"},
    ])
    holdings = fetch_holdings(client, "user-uuid-1")   # quantity=10.0 을 이 시점에 읽어 둠

    # ① 다른 탭이 먼저 수량을 20으로 바꿔 저장했다고 가정합니다(같은 행, DB 값이 바뀜).
    client.store["rows"][0]["quantity"] = "20"

    # ② 처음에 읽었던 holdings(quantity=10.0 그대로)를 근거로 병합을 시도하면, DB 의 실제
    #    값(20)과 달라 낙관적 잠금이 걸려야 합니다 — 10을 기준으로 3을 더해 13으로
    #    덮어쓰면 방금 저장된 '20'이 사라집니다.
    expect_raises(lambda: add_lot(client, "user-uuid-1", MARKET_KR, "5930", 3, 70000,
                                  holdings=holdings),
                  ScorecardError, "낙관적 잠금 — 그 사이 바뀐 값을 모르고 덮어쓰지 않음(M-1)")
    check(client.store["rows"][0]["quantity"] == "20",
          "잠금에 걸렸으면 DB 값(다른 탭이 저장한 20)이 그대로 보존되어야 함")

    # ③ 반대로, 다시 읽어서(fresh) 병합하면 정상적으로 성공해야 합니다(잠금이 항상 막는
    #    것이 아니라 "그 사이 안 바뀌었을 때만" 통과시킴을 확인).
    fresh_holdings = fetch_holdings(client, "user-uuid-1")
    action, merged = add_lot(client, "user-uuid-1", MARKET_KR, "5930", 3, 70000,
                             holdings=fresh_holdings)
    check(action == "merge" and client.store["rows"][0]["quantity"] == 23,
          "다시 읽은 최신 값 기준이면 병합이 정상적으로 성공함")


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
        # 2026-08-29 재감사(H-1) — 예전엔 여기서 "네트워크 오류(합성)" 같은 원문이
        # `ScorecardError` 문구에 그대로 들어있는지를 확인했는데, 그게 정확히 H-1이 고친
        # 버그입니다(§0-3-4 — Postgres/드라이버 원문을 화면에 그대로 흘리지 않기). 지금은
        # 반대를 확인합니다: 화면 문구는 안전한 한국어 한 줄이고, 원문은 `__cause__` 로
        # 체이닝만 되어(로그용) 화면 문구 안에는 섞이지 않습니다.
        check("실패" in str(exc), "실패 사실은 여전히 한국어로 전달됨")
        check("네트워크 오류" not in str(exc), "Postgres/드라이버 원문은 화면 문구에 섞이지 않음(H-1)")
        check(exc.__cause__ is not None and "네트워크 오류" in str(exc.__cause__),
              "원문은 __cause__ 체이닝으로 남아있음(로그·내부 재번역용)")
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


def test_current_user_h4_distinguishes_session_missing_from_real_failure():
    """
    🔴 2026-08-29 재감사 H-4 회귀 고정.

    예전엔 `client.auth.get_user()` 가 예외를 내면 **원인을 가리지 않고** "세션 없음"
    (`None`)으로 재분류했습니다. 그러면 네트워크 장애·서버 오류(Supabase 가 잠깐 응답을
    못 하는 상황) 때도 "로그인 안 된 사용자"로 보여 **정상 로그인 사용자를 강제 로그아웃**
    시킵니다. 지금은 진짜 세션 부재(리프레시 토큰 만료 등, `_SESSION_MISSING_MARKERS`)만
    `None` 으로 재분류하고, 그 밖의 실패는 예외를 그대로 올립니다.
    """

    class _RaisingAuth:
        def __init__(self, exc):
            self._exc = exc

        def get_user(self):
            raise self._exc

    class _RaisingClient:
        def __init__(self, exc):
            self.auth = _RaisingAuth(exc)

    # ① 진짜 세션 부재 — None 을 돌려줘야 합니다(예외 아님).
    for marker_exc in (
        Exception("Session missing!"),
        Exception("invalid refresh token: refresh_token_not_found"),
        Exception("JWT expired"),
    ):
        check(sdb.current_user(_RaisingClient(marker_exc)) is None,
              f"세션 부재({marker_exc}) 는 None 으로 재분류됨")

    # ② 네트워크/서버 실패 — 세션 부재가 아니므로 **예외를 그대로 올려야** 합니다
    #    (조용히 None 으로 바꾸면 정상 로그인 사용자가 강제 로그아웃됩니다).
    for other_exc in (
        Exception("Connection timed out"),
        Exception("503 Service Unavailable"),
        Exception("네트워크 오류(합성)"),
    ):
        raised = []
        try:
            sdb.current_user(_RaisingClient(other_exc))
        except Exception as exc:                     # noqa: BLE001 - 재현용
            raised.append(exc)
        check(len(raised) == 1 and raised[0] is other_exc,
              f"세션 부재가 아닌 실패({other_exc})는 삼키지 않고 그대로 올림(H-4)")


# =============================================================================
# 7-2. 비밀번호 재설정(비밀번호 찾기) — 2026-08-13 오너 요청, TASK_HISTORY #109
#
#  ⚠️ 여기서 검증하는 것: 함수 시그니처 배선 · 방어적 입력 검증 · 에러 문구 · 세션 뒷정리.
#     **실제 이메일이 오는지, 그 코드로 진짜 Supabase 가 비밀번호를 바꿔주는지는 이 테스트로
#     알 수 없습니다**(네트워크·실계정 필요). 그건 오너가 배포 후 직접 확인해야 합니다.
# =============================================================================
def test_password_reset():
    print("\n[7-2] 비밀번호 재설정(6자리 코드 방식)")

    # --- 1단계: 코드 발송 요청 -------------------------------------------------
    expect_raises(lambda: sdb.send_password_reset_code(None, "a@b.c"), ScorecardError,
                  "클라이언트 없으면 조용히 넘어가지 않고 ScorecardError")

    client = FakeClient()
    expect_raises(lambda: sdb.send_password_reset_code(client, "   "), ScorecardError,
                  "이메일이 비면 거부(네트워크 호출 전에 차단)")
    check(client.auth.reset_requests == [], "빈 이메일은 Supabase 로 나가지도 않음")

    notice = sdb.send_password_reset_code(client, "  Owner@Example.com  ")
    check(client.auth.reset_requests == ["Owner@Example.com"],
          "앞뒤 공백만 제거해 그대로 전달(대소문자 임의 변형 없음)")
    check(notice == sdb.PASSWORD_RESET_SENT_MESSAGE, "성공 시 표준 안내 문구 반환")
    check("있다면" in notice,
          "가입 여부를 단정하지 않는 문구 — 계정 존재 여부 유출(enumeration) 방지")
    check("가입되어 있지 않" not in notice and "없는 이메일" not in notice,
          "'그런 계정 없음'류 문구가 들어있지 않음")

    legacy = FakeClient(auth_class=FakeLegacyAuth)
    check(sdb.send_password_reset_code(legacy, "a@b.c") == sdb.PASSWORD_RESET_SENT_MESSAGE
          and legacy.auth.reset_requests == ["a@b.c"],
          "패키지가 옛 이름(reset_password_email)만 가진 경우도 폴백으로 동작")

    missing = FakeClient(auth_class=FakeNoResetAuth)
    expect_raises(lambda: sdb.send_password_reset_code(missing, "a@b.c"), ScorecardError,
                  "재설정 함수가 아예 없으면 AttributeError 가 아니라 한국어 ScorecardError")

    failing = FakeClient(fail=True)
    expect_raises(lambda: sdb.send_password_reset_code(failing, "a@b.c"), ScorecardError,
                  "발송 실패(요청 과다 등)를 조용히 성공으로 위장하지 않음")

    # --- 2단계: 코드 검증 + 새 비밀번호 --------------------------------------
    client = FakeClient()
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "123456", "newpw1", "newpw2"),
        ScorecardError, "새 비밀번호와 확인란이 다르면 거부")
    check(client.auth.verify_otp_calls == [],
          "확인란 오타 때문에 1회용 코드가 먼저 소모되지 않음(검증 순서 보장)")

    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "123456", "abc", "abc"),
        ScorecardError, "너무 짧은 비밀번호 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "123456", "", ""),
        ScorecardError, "빈 비밀번호 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "", "123456", "newpw123", "newpw123"),
        ScorecardError, "이메일이 비면 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "", "newpw123", "newpw123"),
        ScorecardError, "코드가 비면 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "12345", "newpw123", "newpw123"),
        ScorecardError, "너무 짧은(5자리) 코드 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "123456789012", "newpw123", "newpw123"),
        ScorecardError, "너무 긴(12자리) 코드 거부")
    expect_raises(
        lambda: sdb.reset_password_with_code(client, "a@b.c", "12a456", "newpw123", "newpw123"),
        ScorecardError, "숫자가 아닌 코드 거부")
    check(client.auth.verify_otp_calls == [] and client.auth.update_user_keys == [],
          "형식이 틀린 입력은 Supabase 로 나가지 않음")

    ok = sdb.reset_password_with_code(client, " a@b.c ", " 123 456 ", "newpw123", "newpw123")
    check(ok is True, "정상 입력이면 True 반환")
    check(len(client.auth.verify_otp_calls) == 1, "verify_otp 를 정확히 한 번 호출")
    params = client.auth.verify_otp_calls[0]
    check(sorted(params.keys()) == ["email", "token", "type"],
          "verify_otp 파라미터는 email/token/type 3개")
    check(params["type"] == "recovery",
          "비밀번호 재설정용 OTP 타입은 'recovery'(공식 문서 확인)")
    check(params["token"] == "123456",
          "코드에 섞인 공백·하이픈은 걷어내고 숫자만 남도록 정규화")
    check(params["email"] == "a@b.c", "이메일 앞뒤 공백 제거")

    # 2026-08-13 실사용 버그 재현 — Supabase 문서는 "6자리"라 했지만 오너가 실제로 받은
    # 코드는 8자리(59974821)였고, 예전 코드(정확히 6자리만 허용)는 이걸 전부 거부했습니다.
    client8 = FakeClient()
    ok8 = sdb.reset_password_with_code(client8, "a@b.c", "59974821", "newpw123", "newpw123")
    check(ok8 is True, "실측된 8자리 코드도 정상 통과(재발 방지 회귀 테스트)")
    check(client8.auth.verify_otp_calls[0]["token"] == "59974821",
          "8자리 코드가 잘리거나 변형되지 않고 그대로 전달됨")
    check(client.auth.update_user_keys == [["password"]],
          "update_user 에 password 키만 전달(다른 필드 건드리지 않음)")
    check(client.auth.update_user_password_len == len("newpw123"),
          "입력한 새 비밀번호가 그대로 전달됨(값은 테스트에도 저장하지 않고 길이만 확인)")
    check(client.auth.signed_out is True,
          "재설정용 1회용 세션은 끝나고 반드시 로그아웃 — 남의 브라우저에 세션이 남지 않음")

    # 코드가 틀린 경우: Supabase 원문을 사용자에게 그대로 노출하지 않아야 함
    wrong = FakeClient()
    wrong.auth.verify_fail = True
    try:
        sdb.reset_password_with_code(wrong, "a@b.c", "123456", "newpw123", "newpw123")
    except ScorecardError as exc:
        message = str(exc)
        check("재설정 코드 확인에 실패" in message and "다시 받아" in message,
              "코드 오류는 한국어 안내로 감쌈")
        check("합성" not in message and "Token" not in message,
              "Supabase 원문(계정 존재 여부가 드러날 수 있음)을 그대로 노출하지 않음")
    else:
        check(False, "코드 오류 시 ScorecardError")
    check(wrong.auth.update_user_keys == [],
          "코드 검증에 실패하면 비밀번호 변경을 시도하지 않음")

    # 세션을 못 받은 경우(이론상): 비밀번호 변경을 시도하지 않고 정직하게 실패
    no_session = FakeClient()
    no_session.auth.verify_returns_session = False
    expect_raises(
        lambda: sdb.reset_password_with_code(no_session, "a@b.c", "123456", "newpw123", "newpw123"),
        ScorecardError, "세션을 못 받으면 성공으로 위장하지 않고 실패")
    check(no_session.auth.update_user_keys == [], "세션 없이 update_user 를 호출하지 않음")

    # 비밀번호 변경 단계 실패
    update_failing = FakeClient(fail=True)
    update_failing.auth.fail = False          # verify_otp 는 통과시키고
    original_update = update_failing.auth.update_user

    def _failing_update(attributes):
        update_failing.auth.update_user_keys.append(sorted(attributes.keys()))
        raise RuntimeError("Password should be at least 6 characters(합성)")

    update_failing.auth.update_user = _failing_update
    expect_raises(
        lambda: sdb.reset_password_with_code(update_failing, "a@b.c", "123456", "newpw123", "newpw123"),
        ScorecardError, "비밀번호 변경 단계 실패도 조용히 넘어가지 않음")
    check(update_failing.auth.signed_out is True,
          "실패했더라도 1회용 세션은 로그아웃(세션이 남지 않음)")
    check(callable(original_update), "테스트 보조 확인")

    # 문서화된 상수 — 2026-08-13 실측 정정(문서 "6자리" vs 실제 수신 8자리)으로 범위화됨
    check(sdb.PASSWORD_RESET_CODE_MIN_LENGTH == 6, "최소 자리수는 문서 사양(6자리) 유지")
    check(sdb.PASSWORD_RESET_CODE_MAX_LENGTH >= 8,
          "최대 자리수는 실측된 8자리 코드를 받아들일 수 있어야 함")


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
def test_view_and_routing():
    print("\n[9] 데이터 모듈 격리 · 작업 범위")
    # 2026-08-29 — Streamlit 은퇴(views/ → archive/streamlit_views/)로, 이 테스트에서
    # `views/scorecard_view.py`·`visiblehand.py` 를 읽거나 import 하던 검사는 전부
    # 제거했습니다. 살아있는 공유 로직(utils/scorecard_db.py)의 불변식만 남습니다.
    db_src = (REPO_ROOT / "utils" / "scorecard_db.py").read_text(encoding="utf-8")
    check(not re.search(r"open\([^)]*['\"]w", db_src), "데이터 모듈도 data/*.json 을 쓰지 않음")
    check("try:" in db_src and "except ImportError" in db_src,
          "supabase/streamlit import 를 try/except ImportError 로 감쌈")
    check(not re.search(r"https://[a-z0-9]+\.supabase\.co", db_src),
          "소스에 실제 Supabase URL 없음")
    check("SUPABASE_SERVICE_ROLE" not in db_src and "service_role_key" not in db_src,
          "service_role 키를 읽는 코드 없음")

    # 기존 모듈 파일을 건드리지 않았는지(이번 작업 범위 확인)
    #  ⚠️ 2026-08-29 — `views/pegy_view.py` · `views/us_stocks_view.py` 는 Streamlit 은퇴로
    #     archive/streamlit_views/ 로 옮겨져 이 목록에서 뺐습니다.
    for untouched in ("utils/scoring.py", "utils/constants.py"):
        src = (REPO_ROOT / untouched).read_text(encoding="utf-8")
        check("scorecard" not in src.lower(), f"{untouched} 에 내 성적표 관련 수정 없음")


# =============================================================================
# 10. 의존성·문서 배선
# =============================================================================
def test_requirements_and_docs():
    print("\n[10] requirements.txt · 문서 배선")
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in req.splitlines()]
    check(any(ln == "supabase" or ln.startswith("supabase") and not ln.startswith("#")
              for ln in lines), "requirements.txt 에 supabase 추가됨")
    for kept in ("plotly", "pandas", "bcrypt"):
        check(any(ln.startswith(kept) for ln in lines), f"기존 의존성 `{kept}` 유지")
    # 2026-08-29 — Streamlit 은퇴로 streamlit/altair 는 이제 "유지해야 할 의존성"이 아니라
    # "빠져 있어야 하는" 쪽입니다(듀얼런 종료 — 부록 B).
    check(not any(ln.startswith("streamlit") for ln in lines),
          "requirements.txt 에 streamlit 이 더 이상 없음(Streamlit 은퇴 완료)")
    check(not any(ln.startswith("altair") for ln in lines),
          "requirements.txt 에 altair 가 더 이상 없음(Streamlit 전용 차트 라이브러리)")

    order_doc = (REPO_ROOT / "SCORECARD_WORK_ORDER.md")
    check(order_doc.exists(), "작업지시서 원본 보존")


def main():
    print("=" * 74)
    print("📊 내 성적표 모듈 오프라인 검증 (Supabase 미연결 · 네트워크 불필요)")
    print("=" * 74)
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(
        sys.modules[__name__],
        on_skip=lambda names: print(f"\u23ed\ufe0f  pytest \uc804\uc6a9(\ud53d\uc2a4\ucc98 \ud544\uc694) {len(names)}\uac74\uc740 \uac74\ub108\ub700: {names}"),
    )

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
