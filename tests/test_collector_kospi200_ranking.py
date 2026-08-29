# tests/test_collector_kospi200_ranking.py
"""
📊 collector_kospi200.py — 코스피+코스닥 통합 시가총액 랭킹(_rank_candidates_by_market_cap)
   + 진입/이탈 히스테리시스 버퍼(apply_hysteresis_buffer, 500/575) 오프라인 단위테스트
   (네트워크 불필요 — 순수 함수 로직만 검증, 합성 fake 데이터 사용)

🔴 2026-08-26 신설 — 코스피 단독 상위 200 → 코스피+코스닥 통합 상위 500 확대(오너 요청) 작업의
   일부. 이 확대 전에는 두 함수 모두 tests/test_stock_history.py 등의 "소스 텍스트 순서 검사"
   같은 간접 테스트만 있었고, 함수 자체의 동작(진짜 랭킹이 맞는지, 500/575 경계가 정확한지)을
   직접 검증하는 테스트가 없었습니다. 이번에 새로 추가합니다.

실행: python tests/test_collector_kospi200_ranking.py  또는  pytest tests/test_collector_kospi200_ranking.py
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import collector_kospi200 as K  # noqa: E402


def _candidate(code, name, price, market):
    return {"code": code, "name": name, "price": price, "market": market}


# ──────────────────────────────────────────────────────────────
# _rank_candidates_by_market_cap
# ──────────────────────────────────────────────────────────────

def test_rank_orders_by_true_market_cap_not_input_order():
    """
    입력은 "코스피 후보 전부 → 코스닥 후보 전부" 순서(market-sequential)로 들어오지만,
    출력은 반드시 실제 시가총액(price × shares) 내림차순이어야 합니다.
    코스닥 종목(입력상 뒤쪽)이 코스피 종목(입력상 앞쪽)보다 시가총액이 크면
    코스닥 종목이 앞으로 와야 합니다 — 이게 이번 확대의 핵심 요구사항입니다.
    """
    candidates = [
        # 코스피 후보들 (market-sequential 상 먼저 옴)
        _candidate("KOSPI_BIG", "코스피대형", price=100_000, market="KOSPI"),   # cap = 100,000 * 1,000 = 1e8
        _candidate("KOSPI_SMALL", "코스피소형", price=1_000, market="KOSPI"),   # cap = 1,000 * 500 = 5e5
        # 코스닥 후보들 (market-sequential 상 나중에 옴)
        _candidate("KOSDAQ_HUGE", "코스닥초대형", price=50_000, market="KOSDAQ"),  # cap = 50,000 * 10,000 = 5e8
        _candidate("KOSDAQ_TINY", "코스닥초소형", price=500, market="KOSDAQ"),     # cap = 500 * 100 = 5e4
    ]
    shares_lookup = {
        "KOSPI_BIG": 1_000,
        "KOSPI_SMALL": 500,
        "KOSDAQ_HUGE": 10_000,
        "KOSDAQ_TINY": 100,
    }

    ranked = K._rank_candidates_by_market_cap(candidates, shares_lookup)

    # 진짜 시가총액 내림차순: KOSDAQ_HUGE(5e8) > KOSPI_BIG(1e8) > KOSPI_SMALL(5e5) > KOSDAQ_TINY(5e4)
    assert [c["code"] for c in ranked] == ["KOSDAQ_HUGE", "KOSPI_BIG", "KOSPI_SMALL", "KOSDAQ_TINY"]
    # market_cap 필드가 정확히 계산되어 채워져야 함
    assert ranked[0]["market_cap"] == 50_000 * 10_000
    assert ranked[1]["market_cap"] == 100_000 * 1_000
    # 원래 시장 라벨은 그대로 보존되어야 함(어느 시장 소속인지 잃어버리면 안 됨)
    assert ranked[0]["market"] == "KOSDAQ"
    assert ranked[1]["market"] == "KOSPI"


def test_rank_excludes_candidates_with_missing_shares():
    """상장주식수를 못 찾은 종목은 값을 지어내지 않고(§0-1) 통합 순위 계산에서 제외됩니다."""
    candidates = [
        _candidate("HAS_SHARES", "정상종목", price=10_000, market="KOSPI"),
        _candidate("NO_SHARES", "상장주식수없음", price=999_999, market="KOSDAQ"),  # 가격만 보면 1등처럼 보이지만 제외돼야 함
    ]
    shares_lookup = {"HAS_SHARES": 1_000}  # NO_SHARES는 lookup에 아예 없음

    ranked = K._rank_candidates_by_market_cap(candidates, shares_lookup)

    assert [c["code"] for c in ranked] == ["HAS_SHARES"]


def test_rank_excludes_candidates_with_zero_or_negative_shares():
    """상장주식수가 0 이하로 들어온(파싱 오염 등) 종목도 안전하게 제외되어야 합니다."""
    candidates = [
        _candidate("ZERO_SHARES", "제로", price=10_000, market="KOSPI"),
        _candidate("NEGATIVE_SHARES", "음수", price=10_000, market="KOSPI"),
        _candidate("OK", "정상", price=10_000, market="KOSPI"),
    ]
    shares_lookup = {"ZERO_SHARES": 0, "NEGATIVE_SHARES": -100, "OK": 1_000}

    ranked = K._rank_candidates_by_market_cap(candidates, shares_lookup)

    assert [c["code"] for c in ranked] == ["OK"]


def test_rank_empty_candidates_returns_empty_list():
    """빈 입력에 대해 예외 없이 빈 리스트를 반환해야 합니다."""
    assert K._rank_candidates_by_market_cap([], {}) == []


# ──────────────────────────────────────────────────────────────
# apply_hysteresis_buffer (진입 500 / 이탈 575 — 2026-08-26 200/230 → 500/575 확대)
# ──────────────────────────────────────────────────────────────

def _make_ranked_candidates(n):
    """이미 시가총액 내림차순으로 정렬된 것으로 가정한 순위 1..n 짜리 합성 후보 리스트."""
    return [_candidate(f"C{i:04d}", f"종목{i}", price=1_000, market="KOSPI") for i in range(1, n + 1)]


def test_hysteresis_defaults_are_500_and_575():
    """이번 확대의 핵심 숫자: 기본 진입선 500위 / 이탈선 575위(비율 1.15배 유지)."""
    import inspect
    sig = inspect.signature(K.apply_hysteresis_buffer)
    assert sig.parameters["entry_rank"].default == 500
    assert sig.parameters["exit_rank"].default == 575


def test_hysteresis_top_500_always_visible_regardless_of_history():
    """1~500위는 어제 추적 여부와 무관하게 항상 화면 노출로 포함됩니다."""
    candidates = _make_ranked_candidates(500)
    tracked = K.apply_hysteresis_buffer(candidates, previous_codes=set())  # 완전히 새로운 첫 실행

    assert len(tracked) == 500
    assert all(c["is_visible"] for c in tracked)
    assert [c["rank"] for c in tracked] == list(range(1, 501))


def test_hysteresis_buffer_zone_keeps_previously_tracked_stock_hidden():
    """501~575위 사이에 있고 어제도 추적 중이었던 종목은 유지하되 is_visible=False."""
    candidates = _make_ranked_candidates(575)
    # 550위 종목(C0550)은 어제부터 추적 중이었다고 가정
    previous_codes = {"C0550"}

    tracked = K.apply_hysteresis_buffer(candidates, previous_codes=previous_codes)

    kept_codes = {c["code"] for c in tracked}
    assert "C0550" in kept_codes
    entry = next(c for c in tracked if c["code"] == "C0550")
    assert entry["rank"] == 550
    assert entry["is_visible"] is False

    # 나머지 버퍼 구간(어제 추적 이력 없는 종목들)은 제외되어야 함
    assert "C0551" not in kept_codes
    assert "C0575" not in kept_codes
    # 결과는 top 500(전부 노출) + C0550(버퍼, 비노출) = 501개
    assert len(tracked) == 501


def test_hysteresis_drops_previously_tracked_stock_beyond_exit_rank():
    """어제 추적 중이었어도 이탈선(575위) 밖으로 완전히 밀려나면 이번엔 제외됩니다."""
    candidates = _make_ranked_candidates(600)
    previous_codes = {"C0576"}  # 이탈선 바로 밖

    tracked = K.apply_hysteresis_buffer(candidates, previous_codes=previous_codes)

    assert "C0576" not in {c["code"] for c in tracked}
    assert len(tracked) == 500  # 버퍼 구간에 아무도 남지 않으므로 정확히 top 500


def test_hysteresis_new_stock_in_buffer_zone_without_history_is_excluded():
    """501~575위인데 어제 추적 이력이 없는(신규 진입 후보) 종목은 아직 진입 대상이 아닙니다."""
    candidates = _make_ranked_candidates(575)
    tracked = K.apply_hysteresis_buffer(candidates, previous_codes=set())

    assert len(tracked) == 500
    assert "C0501" not in {c["code"] for c in tracked}


# ──────────────────────────────────────────────────────────────
# enrich_quant_metrics — market / market_cap 필드 보존 (2026-08-26 오너 후속 요청:
# "라벨이 있으면 더 좋긴하지 그것까지 보여놔줘" — 화면에 코스피/코스닥 라벨을 붙이려면
# 먼저 이 함수가 값을 버리지 않고 최종 stock_dict까지 이어줘야 함)
# ──────────────────────────────────────────────────────────────

def _mock_naver_item():
    """fetch_naver_item_dps_and_eps()가 정상 수집했을 때 돌려주는 형태를 흉내낸 합성 값."""
    return {
        "t_per": 12.5, "t_eps": 4000, "f_per": 10.0, "f_eps": 5000,
        "div_yield": 2.0, "dps": 200, "outstanding_shares": 10_000_000,
        "t_pbr": 1.2, "ev_ebitda": 8.0, "f_roe": 15.0, "raw_period": "2026.12(E)",
        "dps_status": "collected", "dps_inherited_from": None, "errors": [],
    }


def test_enrich_quant_metrics_preserves_market_label_and_market_cap(monkeypatch):
    """
    _rank_candidates_by_market_cap()이 채운 "market"/"market_cap"과 apply_hysteresis_buffer()가
    채운 "rank"/"is_visible"은 같은 방식(s.get())으로 최종 stock_dict까지 이어져야 합니다.
    이 값들이 조용히 사라지면 화면에 코스피/코스닥 라벨을 못 붙입니다 — 그게 이번 회귀의 요지.
    """
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps", lambda code: _mock_naver_item())
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: 15.0)
    monkeypatch.setattr(K.time, "sleep", lambda *_a, **_kw: None)  # 테스트 속도(polite-scraping 대기 스킵)

    stocks_raw = [
        {
            "code": "247540", "name": "에코프로비엠", "price": 150_000,
            "t_per": 30.0, "t_roe": 10.0,
            "market": "KOSDAQ", "market_cap": 150_000 * 10_000_000,
            "rank": 42, "is_visible": True,
        }
    ]

    enriched = K.enrich_quant_metrics(stocks_raw, shares_lookup={"247540": 10_000_000})

    assert len(enriched) == 1
    out = enriched[0]
    assert out["market"] == "KOSDAQ"
    assert out["market_cap"] == 150_000 * 10_000_000
    assert out["rank"] == 42
    assert out["is_visible"] is True


def test_enrich_quant_metrics_market_is_none_when_absent_from_input():
    """market 필드가 없는(구버전 스냅샷 등) 입력이면 값을 지어내지 않고 None으로 정직하게 둡니다."""
    import unittest.mock as mock
    with mock.patch.object(K, "fetch_naver_item_dps_and_eps", lambda code: _mock_naver_item()), \
         mock.patch.object(K, "fetch_recent_volatility", lambda code: 15.0), \
         mock.patch.object(K.time, "sleep", lambda *a, **kw: None):
        stocks_raw = [
            {"code": "005930", "name": "삼성전자", "price": 70_000, "t_per": 12.0, "t_roe": 9.0}
        ]
        enriched = K.enrich_quant_metrics(stocks_raw, shares_lookup={"005930": 5_000_000_000})

    assert enriched[0]["market"] is None
    assert enriched[0]["market_cap"] is None


def test_hysteresis_respects_custom_thresholds():
    """entry_rank/exit_rank를 명시적으로 넘기면(과거 200/230 등) 그 값을 그대로 존중해야 합니다."""
    candidates = _make_ranked_candidates(230)
    previous_codes = {"C0210"}

    tracked = K.apply_hysteresis_buffer(candidates, previous_codes=previous_codes, entry_rank=200, exit_rank=230)

    kept_codes = {c["code"] for c in tracked}
    assert "C0210" in kept_codes
    assert next(c for c in tracked if c["code"] == "C0210")["is_visible"] is False
    assert len(tracked) == 201  # top 200 + 버퍼 1개


# ──────────────────────────────────────────────────────────────
# EV/EBITDA 서킷브레이커 (2026-08-27 신설 — 오너 승인 #19: navercomp.wisereport.co.kr
# 연속 타임아웃 66.6%로 500종목 실행이 2시간 넘게 걸린 문제 대응. "재시도 강화"가 아니라
# "가망 없으면 빨리 포기"라 상대 서버 요청 수는 오히려 줄어듭니다 — 서킷 열리면 이후
# 종목은 이 서브 요청 자체를 건너뛰고 ev_ebitda=None으로 정직하게 둡니다(§0-1).
# ──────────────────────────────────────────────────────────────

_FAKE_MAIN_PAGE_HTML = '<html><body><table><tr><td>dummy</td></tr></table></body></html>'


def _fresh_circuit_state():
    return {"consecutive_failures": 0, "open": False, "skipped_count": 0}


class _FakeResp:
    def __init__(self, status_code=200, text=_FAKE_MAIN_PAGE_HTML):
        self.status_code = status_code
        self.text = text


def test_ev_ebitda_circuit_stays_closed_and_requests_normally_below_threshold(monkeypatch):
    """임계치 미만으로 실패하는 동안은 매 종목마다 실제로 EV/EBITDA 요청을 시도해야 합니다."""
    state = _fresh_circuit_state()
    monkeypatch.setattr(K, "_ev_ebitda_circuit", state)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)

    call_count = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        if "wisereport" in url:
            call_count["n"] += 1
            raise K.requests.exceptions.ConnectionError("mock connection timeout")
        return _FakeResp()

    monkeypatch.setattr(K.requests, "get", fake_get)

    threshold = K._EV_EBITDA_FAILURE_THRESHOLD
    for i in range(threshold - 1):
        result = K.fetch_naver_item_dps_and_eps(f"00000{i}")
        assert result["ev_ebitda"] is None  # §0-1: 실패 시 지어내지 않고 None

    assert state["open"] is False
    assert state["consecutive_failures"] == threshold - 1
    assert call_count["n"] == threshold - 1  # 매번 실제로 시도했음
    assert state["skipped_count"] == 0


def test_ev_ebitda_circuit_opens_exactly_at_threshold_and_then_skips_requests(monkeypatch):
    """연속 실패가 임계치에 도달하면 서킷이 열리고, 그 이후 호출은 요청 자체를 보내지 않습니다."""
    state = _fresh_circuit_state()
    monkeypatch.setattr(K, "_ev_ebitda_circuit", state)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)

    call_count = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        if "wisereport" in url:
            call_count["n"] += 1
            raise K.requests.exceptions.ConnectionError("mock connection timeout")
        return _FakeResp()

    monkeypatch.setattr(K.requests, "get", fake_get)

    threshold = K._EV_EBITDA_FAILURE_THRESHOLD
    for i in range(threshold):
        K.fetch_naver_item_dps_and_eps(f"11111{i}")

    assert state["open"] is True
    assert state["consecutive_failures"] == threshold
    assert call_count["n"] == threshold

    # 서킷이 열린 뒤: 추가 호출해도 wisereport 쪽 requests.get은 더 이상 불리지 않아야 함.
    result_after_open = K.fetch_naver_item_dps_and_eps("999999")
    assert call_count["n"] == threshold  # 늘어나지 않음 — 요청 자체를 안 보냄
    assert result_after_open["ev_ebitda"] is None
    assert state["skipped_count"] == 1

    K.fetch_naver_item_dps_and_eps("888888")
    assert call_count["n"] == threshold
    assert state["skipped_count"] == 2


def test_ev_ebitda_circuit_resets_failure_count_on_successful_response(monkeypatch):
    """표 파싱 결과와 무관하게, 응답 자체를 받으면(연결 성공) 연속 실패 카운트가 0으로 리셋됩니다."""
    state = {"consecutive_failures": 3, "open": False, "skipped_count": 0}
    monkeypatch.setattr(K, "_ev_ebitda_circuit", state)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)

    def fake_get(url, headers=None, timeout=None):
        return _FakeResp()  # 코스피 본문/EV 페이지 둘 다 성공 응답(더미 테이블이라 EV/EBITDA 값 자체는 못 뽑음)

    monkeypatch.setattr(K.requests, "get", fake_get)

    result = K.fetch_naver_item_dps_and_eps("123456")

    assert state["consecutive_failures"] == 0
    assert state["open"] is False
    assert result["ev_ebitda"] is None  # 더미 테이블엔 'EV/EBITDA' 행이 없으므로 값은 여전히 None(정상)


# ──────────────────────────────────────────────────────────────
# load_ticker_types (2026-08-29 오푸스 감사 Top-5 #1)
# collector_indicator_kr.py::load_ticker_types() 와 완전히 동일한 규약이어야 합니다.
# ──────────────────────────────────────────────────────────────

def test_load_ticker_types_missing_file_returns_empty(tmp_path):
    result = K.load_ticker_types(str(tmp_path / "nope.json"))
    assert result == {}


def test_load_ticker_types_valid_file(tmp_path):
    import json
    p = tmp_path / "tickers.json"
    p.write_text(
        json.dumps({"stocks": [
            {"code": "005390", "name": "BNK금융지주", "type": "STOCK"},
            {"code": "069500", "name": "KODEX 200", "type": "ETF"},
        ]}),
        encoding="utf-8",
    )
    result = K.load_ticker_types(str(p))
    assert result == {"005390": "STOCK", "069500": "ETF"}


def test_load_ticker_types_unreadable_file_returns_empty(tmp_path):
    """JSON 파싱 자체가 깨진 파일도 예외를 던지지 않고 빈 dict(안전한 쪽으로)를 반환해야 합니다."""
    p = tmp_path / "broken.json"
    p.write_text("{이건 유효한 JSON이 아님", encoding="utf-8")
    result = K.load_ticker_types(str(p))
    assert result == {}


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))


# ──────────────────────────────────────────────────────────────
# 2026-08-29 재감사 회귀 테스트 (H1/H2/H3/H4/H5/M6/L11/L12/L13/M4/M5)
# ──────────────────────────────────────────────────────────────

# aside 스냅샷은 정상인데 재무제표 표가 아예 없는 페이지.
# 예전(H1 이전)에는 pd.read_html() 의 ValueError 가 광역 except 로 튀어 aside에서
# 이미 정상 파싱한 PER/EPS/PBR/상장주식수까지 통째로 버려졌습니다.
_FAKE_ASIDE_ONLY_HTML = """
<html><body>
<div class="aside_invest_info">
<table>
<tr><th>PERlEPS(2026.06)</th><td>12.34배 l 5,678원</td></tr>
<tr><th>추정PERlEPS</th><td>10.00배 l 7,000원</td></tr>
<tr><th>PBRlBPS</th><td>1.23배 l 50,000원</td></tr>
<tr><th>배당수익률</th><td>N/A</td></tr>
<tr><th>상장주식수</th><td>59,700,000</td></tr>
</table>
</div>
</body></html>
"""


def test_partial_parse_keeps_aside_values_when_financial_table_is_missing(monkeypatch):
    """H1: 재무제표 구획이 없어도 aside에서 이미 읽은 값은 절대 버리지 않습니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=_FAKE_ASIDE_ONLY_HTML))

    result = K.fetch_naver_item_dps_and_eps("005930")

    # aside 값은 살아 있어야 한다
    assert result["t_per"] == 12.34
    assert result["t_eps"] == 5678
    assert result["f_per"] == 10.00
    assert result["f_eps"] == 7000
    assert result["outstanding_shares"] == 59_700_000
    # 재무제표 구획만 미수집
    assert result["dps"] is None
    assert result["dps_status"] == "not_collected"


# 재무제표 파싱이 **예외를 던지는** 페이지(표 자체가 없어 pd.read_html 이 실패).
# 예전(H1 이전)에는 이 예외가 함수 전체의 광역 except 로 튀어 _empty_item_info() 가 반환됐고,
# aside에서 이미 정상 파싱한 PER/EPS/상장주식수까지 통째로 버려졌습니다.
_FAKE_NO_TABLE_HTML = (
    '<html><body><div class="aside_invest_info">'
    '<tr><th>PERlEPS(2026.06)</th><td>12.34배 l 5,678원</td></tr>'
    '<tr><th>상장주식수</th><td>59,700,000</td></tr>'
    '</div></body></html>'
)


def test_partial_parse_survives_financial_table_exception(monkeypatch):
    """H1 핵심: pd.read_html() 이 예외를 던져도 aside 값이 보존되고 사유가 errors 에 남습니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=_FAKE_NO_TABLE_HTML))

    result = K.fetch_naver_item_dps_and_eps("005930")

    assert result["t_per"] == 12.34
    assert result["t_eps"] == 5678
    assert result["outstanding_shares"] == 59_700_000
    assert result["dps"] is None
    assert result["dps_status"] == "not_collected"
    assert any("주요재무제표 파싱 실패" in e for e in result["errors"])


def test_empty_item_info_key_set_matches_normal_return(monkeypatch):
    """H1: 실패 경로 dict 와 정상 경로 dict 의 키 집합이 완전히 같아야 합니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=_FAKE_ASIDE_ONLY_HTML))

    normal = K.fetch_naver_item_dps_and_eps("005930")
    empty = K._empty_item_info("테스트 사유")
    assert set(empty.keys()) == set(normal.keys())
    assert empty["div_yield_row_found"] is False
    assert empty["div_yield_row_explicit_na"] is False


def test_div_yield_row_explicit_na_flag_is_set_when_row_has_no_number(monkeypatch):
    """H3: '배당수익률' 행이 있고 숫자가 없을 때만 explicit_na 가 True 여야 합니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=_FAKE_ASIDE_ONLY_HTML))

    result = K.fetch_naver_item_dps_and_eps("005930")
    assert result["div_yield_row_found"] is True
    assert result["div_yield_row_explicit_na"] is True
    assert result["div_yield"] is None


def test_div_yield_row_with_number_is_not_marked_explicit_na(monkeypatch):
    """H3: 배당수익률에 실제 숫자가 있으면 explicit_na 는 False 여야 합니다(무배당 근거 아님)."""
    html = _FAKE_ASIDE_ONLY_HTML.replace("<td>N/A</td>", "<td>2.15%</td>")
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=html))

    result = K.fetch_naver_item_dps_and_eps("005930")
    assert result["div_yield"] == 2.15
    assert result["div_yield_row_explicit_na"] is False


def test_preferred_dps_inheritance_requires_verified_parent_stock(monkeypatch):
    """H12: 추정 부모 코드가 마스터 목록의 STOCK 으로 확인되지 않으면 상속하지 않습니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)

    fetched_codes = []

    def fake_get(url, headers=None, timeout=None):
        fetched_codes.append(url)
        return _FakeResp(text=_FAKE_ASIDE_ONLY_HTML)

    monkeypatch.setattr(K.requests, "get", fake_get)

    # 부모 코드(006800)가 마스터 목록에 없음 → 상속 금지, 부모 페이지 크롤링도 하지 않음
    result = K.fetch_naver_item_dps_and_eps("00680K", ticker_types={})
    assert result["dps"] is None
    assert result["dps_inherited_from"] is None
    assert result["dps_status"] == "not_collected"
    assert len(fetched_codes) == 1  # 자기 페이지만 요청, 부모 페이지 요청 없음
    assert any("상속 보류" in e for e in result["errors"])


def test_preferred_dps_inheritance_does_not_run_for_etf_parent(monkeypatch):
    """H12: 부모 코드가 ETF 로 확인되면 역시 상속하지 않습니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=_FAKE_ASIDE_ONLY_HTML))

    result = K.fetch_naver_item_dps_and_eps("00680K", ticker_types={"006800": "ETF"})
    assert result["dps_inherited_from"] is None


# ── H4: 시가총액 순위표 헤더 라벨 기반 컬럼 인덱스 ──

_MARKET_SUM_HEADER = """
<table class="type_2">
<thead><tr><th>N</th><th>종목명</th><th>현재가</th><th>전일비</th><th>등락률</th>
<th>액면가</th><th>시가총액</th><th>상장주식수</th><th>외국인비율</th><th>거래량</th>
<th>PER</th><th>ROE</th><th>토론실</th></tr></thead>
</table>
"""


def _parse_table(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").select_one("table.type_2")


def test_market_sum_column_indices_found_by_label():
    idx = K.extract_market_sum_column_indices(_parse_table(_MARKET_SUM_HEADER))
    assert idx["price"] == 2
    assert idx["per"] == 10
    assert idx["roe"] == 11


def test_market_sum_column_indices_follow_shifted_columns():
    """H4: 네이버가 컬럼을 하나 끼워 넣어도 라벨을 따라가야 합니다(위치 고정 금지)."""
    shifted = _MARKET_SUM_HEADER.replace("<th>N</th>", "<th>N</th><th>신규컬럼</th>")
    idx = K.extract_market_sum_column_indices(_parse_table(shifted))
    assert idx["price"] == 3
    assert idx["per"] == 11
    assert idx["roe"] == 12


def test_market_sum_column_indices_missing_labels_are_absent_not_guessed():
    """H4: 라벨이 없으면 키 자체가 없어야 합니다 — 위치 인덱스로 지어내지 않습니다."""
    no_roe = _MARKET_SUM_HEADER.replace("<th>ROE</th>", "<th>기타</th>")
    idx = K.extract_market_sum_column_indices(_parse_table(no_roe))
    assert "roe" not in idx
    assert idx["price"] == 2


def test_cell_float_returns_none_for_missing_index():
    assert K._cell_float([], None) is None
    assert K._cell_float([], 3) is None


# ── H5 / M6: 요약 이력 파일 ──

def test_summary_history_skips_update_and_backs_up_when_file_is_corrupt(tmp_path, monkeypatch):
    """H5: 손상된 이력 파일을 조용히 덮어쓰지 않고 백업 후 갱신을 건너뜁니다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history_path = data_dir / "pegy_summary_history.json"
    history_path.write_text("{ 깨진 JSON", encoding="utf-8")
    monkeypatch.setattr(K.os.path, "dirname", lambda _p: str(tmp_path))

    K.update_pegy_summary_history("2026-08-29 09:30", [{"f_per": 10.0, "growth": 5.0, "f_pegy": 1.0}])

    # 원본 경로에는 새 이력이 쓰이지 않았고(갱신 스킵), 손상본은 백업되어 있어야 함
    assert not history_path.exists()
    backups = list(data_dir.glob("pegy_summary_history.json.corrupt.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{ 깨진 JSON"


def test_summary_history_dedupes_by_day_not_by_minute(tmp_path, monkeypatch):
    """M6: 같은 날 두 번 실행하면 분 단위 타임스탬프가 달라도 한 행만 남아야 합니다."""
    import json as _json
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history_path = data_dir / "pegy_summary_history.json"
    monkeypatch.setattr(K.os.path, "dirname", lambda _p: str(tmp_path))

    stocks = [{"f_per": 10.0, "growth": 5.0, "f_pegy": 1.0}]
    K.update_pegy_summary_history("2026-08-29 09:30", stocks)
    K.update_pegy_summary_history("2026-08-29 17:45", stocks)
    K.update_pegy_summary_history("2026-08-30 09:30", stocks)

    history = _json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history) == 2                       # 8/29 한 행 + 8/30 한 행
    assert history[0]["date"] == "2026-08-29 17:45"  # 같은 날은 마지막 실행값으로 교체
    assert history[0]["collected_at"] == "2026-08-29 17:45"


def test_summary_history_writes_atomically_leaving_no_tmp_file(tmp_path, monkeypatch):
    """H5: tmp → os.replace 원자적 교체 — 쓰다 만 .tmp 가 남지 않아야 합니다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(K.os.path, "dirname", lambda _p: str(tmp_path))
    K.update_pegy_summary_history("2026-08-29 09:30", [{"f_per": 10.0, "growth": 5.0, "f_pegy": 1.0}])
    assert not list(data_dir.glob("*.tmp"))


# ── M4 / M5 / L12 / L13: 죽은 코드 제거·상수화 ──

def test_roic_premium_dead_path_is_removed():
    """M4: 항상 0을 반환하던 ROIC 프리미엄 경로는 완전히 사라져야 합니다."""
    assert not hasattr(K, "compute_roic_premium")
    assert not hasattr(K, "ROIC_PREMIUM_MAX")
    assert not hasattr(K, "ROIC_PREMIUM_BASELINE_PCT")


def test_yfinance_cross_check_sample_size_is_a_named_constant():
    """M5: 매직넘버 15 는 이름 있는 상수여야 합니다."""
    assert K.YFINANCE_CROSS_CHECK_TOP_N == 15


def test_financial_sector_keywords_are_a_named_constant():
    """L13: 금융업종 판정 키워드는 모듈 상수여야 합니다(로직은 그대로)."""
    assert K.FINANCIAL_SECTOR_NAME_KEYWORDS == ['은행', '금융지주', '보험', '증권', '캐피탈']


def test_preferred_detection_uses_code_suffix_only(monkeypatch):
    """L12: 이름에 '우'가 들어간 보통주(우리금융지주)를 우선주로 오탐하면 안 됩니다."""
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps",
                        lambda code, ticker_types=None: K._empty_item_info("테스트"))
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: {})

    stocks_raw = [
        # 보통주(끝자리 0)이고 ROE 유효 → 상속 소스로 등록됨
        {"code": "316140", "name": "우리금융지주", "price": 10000, "t_per": 5.0, "t_roe": 9.0, "market": "KOSPI"},
        # 같은 앞 5자리를 가진, ROE 가 0인 또 다른 보통주(끝자리 0이 아님에도 우선주가 아님)
        {"code": "316141", "name": "우리테스트", "price": 10000, "t_per": 5.0, "t_roe": 0, "market": "KOSPI"},
    ]
    out = K.enrich_quant_metrics(stocks_raw, shares_lookup={})
    by_code = {s["code"]: s for s in out}
    # 끝자리가 5/7/K/L 이 아니므로 우선주가 아니고, 따라서 ROE 상속이 일어나면 안 됨
    assert by_code["316141"]["t_roe_inherited_from"] is None


# ── L11: 서킷브레이커 카운터 노출 ──

def test_ev_ebitda_skipped_count_is_exposed_in_metadata_source():
    """L11: skipped_count 가 스냅샷 metadata 에 실려야 합니다."""
    src = (Path(__file__).parent.parent / "collector_kospi200.py").read_text(encoding="utf-8")
    assert '"ev_ebitda_skipped_count": _ev_ebitda_circuit.get("skipped_count", 0)' in src
    # 실행 단위 리셋도 있어야 함
    assert "_ev_ebitda_circuit.clear()" in src


# ── H6: __main__ 실행 순서 ──

def test_main_block_builds_ticker_master_before_kospi_collection():
    """H6: ETF 판정에 쓰는 마스터 목록을 코스피 수집보다 먼저 만들어야 합니다."""
    src = (Path(__file__).parent.parent / "collector_kospi200.py").read_text(encoding="utf-8")
    main_block = src[src.index('if __name__ == "__main__":'):]
    assert main_block.index("run_kr_ticker_master_collector()") < main_block.index("run_kospi200_collector()")
    assert "_warn_ticker_master_staleness()" in main_block


# ── H2: DPS 셀 파싱 오류가 '무배당 확정'으로 승격되면 안 됨 ──

_FIN_TABLE_TEMPLATE = """
<html><body>
<div class="aside_invest_info">
<table><tr><th>배당수익률</th><td>N/A</td></tr></table>
</div>
<table>
<tr><th>주요재무정보</th><th>2024.12</th><th>2025.12</th></tr>
<tr><td>매출액</td><td>100</td><td>200</td></tr>
<tr><td>주당배당금</td><td>{c1}</td><td>{c2}</td></tr>
</table>
</body></html>
"""


def test_dps_cell_parse_error_does_not_become_no_dividend_confirmed(monkeypatch):
    """H2: 셀을 '읽지 못한' 것을 '배당이 없다'는 실측 사실로 승격하면 안 됩니다."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    html = _FIN_TABLE_TEMPLATE.format(c1="미공시", c2="미공시")  # float() 이 ValueError 를 던지는 셀
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=html))

    result = K.fetch_naver_item_dps_and_eps("005930")
    assert result["dps_status"] == "not_collected"
    assert result["dps"] is None
    assert any("DPS 셀 파싱" in e for e in result["errors"])


def test_all_blank_dps_cells_still_confirm_no_dividend(monkeypatch):
    """H2 반대편: 진짜로 전부 '-' 인 경우는 예전처럼 무배당 확정이어야 합니다(회귀 방지)."""
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    html = _FIN_TABLE_TEMPLATE.format(c1="-", c2="-")
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: _FakeResp(text=html))

    result = K.fetch_naver_item_dps_and_eps("005930")
    assert result["dps_status"] == "no_dividend_confirmed"


def test_no_dividend_scoring_requires_both_evidences(monkeypatch):
    """H3: 재무제표 무배당 확정 + 배당수익률 행 명시적 공란, 두 근거가 모두 있어야 dps=0 채점."""
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: {})

    def _item(**over):
        base = K._empty_item_info("x")
        base["errors"] = []
        base.update(over)
        return base

    # ⓐ 재무제표만 확정, 배당수익률 행은 숫자가 있었음(= 명시적 공란 아님) → 미수집이어야 함
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps",
                        lambda code, ticker_types=None: _item(
                            dps_status="no_dividend_confirmed",
                            div_yield_row_found=True, div_yield_row_explicit_na=False))
    out = K.enrich_quant_metrics(
        [{"code": "000010", "name": "테스트", "price": 1000, "t_per": 5.0, "t_roe": 9.0, "market": "KOSPI"}],
        shares_lookup={})
    assert out[0]["dps_source"] == "not_collected"
    assert out[0]["dps"] is None

    # ⓑ 두 근거 모두 있음 → 무배당 확정(dps=0)
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps",
                        lambda code, ticker_types=None: _item(
                            dps_status="no_dividend_confirmed",
                            div_yield_row_found=True, div_yield_row_explicit_na=True))
    out = K.enrich_quant_metrics(
        [{"code": "000010", "name": "테스트", "price": 1000, "t_per": 5.0, "t_roe": 9.0, "market": "KOSPI"}],
        shares_lookup={})
    assert out[0]["dps_source"] == "no_dividend_confirmed"
    assert out[0]["dps"] == 0
