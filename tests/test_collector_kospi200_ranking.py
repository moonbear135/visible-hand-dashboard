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
