# tests/test_outstanding_shares_source.py
"""
🔴 상장주식수 출처 우선순위 검사 (2026-09-08 신설 — 신 출처 전환 후 **첫 실전 실행 사고**)

왜 생겼는가 — 그날 실제로 난 사고 (2026-09-08 17:40, GitHub Actions, NAVER_SOURCE=new_api):
  신 API 는 659종목을 완벽히 줬습니다(marketStatus=CLOSE). 그런데 `_load_outstanding_shares_lookup()`
  (FinanceDataReader StockListing('KRX'))가 "HTTP Error 404" 로 빈 dict 를 돌려주자
  `_rank_candidates_by_market_cap()` 이 659종목 **전부**를 "상장주식수 없음"으로 제외 → 0개 →
  RuntimeError 로 수집 중단. 신 API 목록 응답은 `listedStockCnt`(상장주식수)를 **이미 주고 있었고**
  (섀도 3회차 516종목 FDR 대비 100% 일치), 받아 놓고 안 쓴 채 FDR 에 다시 물어보다 죽은 것입니다.

무엇을 못 박는가:
  ① 🔴 사고 재현 — 신 경로 + FDR 통째로 404 → **수집이 끝까지 성공**하고 상장주식수·시가총액이 목록 값으로 채워진다.
  ② 우선순위 — 후보가 가진 값(목록 API) 1차, FDR 은 그 값이 없는 후보가 있을 때만 폴백(§2-3-1·§0-3-2).
  ③ 구 경로 불변 — 후보에 그 값이 없으므로 예전처럼 항상 FDR 을 쓰고, FDR 이 비면 예전처럼 중단한다.
  ④ §0-1 — 어느 출처를 썼는지 스냅샷 metadata.outstanding_shares_source 에 남는다.
  ⑤ enrich 가 FDR 이 비었을 때 종목 상세의 상장주식수를 조용히 버리지 않는다.
  ⑥ 목록 파싱 `skipped['parse']` 는 **실제로 빠진 행 수**이고, 종목이 유지된 파서 메모(배당 모순)와 섞이지 않는다.

📌 네트워크는 전부 가짜입니다. 순위·enrich·검증 파이프라인은 진짜 코드가 돕니다. 파일 쓰기는 tmp_path 안에서만.
실행: python -m pytest tests/test_outstanding_shares_source.py -v
"""
import inspect
import json
import os
import re
import sys
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다.
from conftest import FAILURES, check  # noqa: E402,F401
import pytest  # noqa: E402

import collector_kospi200 as K  # noqa: E402
from utils import naver_source as NS  # noqa: E402

FIXTURES_NEW = REPO_ROOT / "tests" / "fixtures" / "naver_new_api"


# ─────────────────────────────────────────────────────────────────────────────
# 공통 재료
# ─────────────────────────────────────────────────────────────────────────────
def _list_rows():
    """NXT 픽스처의 **값**만 빌려 쓰고 종가 상태로 바꿉니다(주소는 KRX 로 만들어지므로 파서가 거부하지 않음)."""
    rows = json.loads((FIXTURES_NEW / "market_list_marketSum_NXT_top10.json").read_text(encoding="utf-8"))
    for r in rows:
        r["marketStatus"] = "CLOSE"
    return rows


def _detail_payload(code):
    d = json.loads((FIXTURES_NEW / "detail_000660_codeType_KRX.json").read_text(encoding="utf-8"))
    d["itemcode"] = code
    return d


def _krx_404():
    # 2026-09-08 17:40 로그 문구 그대로 — pandas.read_csv(url) 이 던지는 urllib HTTPError.
    raise HTTPError("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/x.csv",
                    404, "Not Found", hdrs=None, fp=None)


class _FdrDown:
    """FinanceDataReader 가 통째로 죽은 날. 몇 번 두드렸는지 셉니다(§0-3-2)."""

    def __init__(self):
        self.calls = 0

    def StockListing(self, market):
        self.calls += 1
        _krx_404()


def _candidate(code, price, shares=None, source=None):
    c = {"name": code, "code": code, "price": float(price), "t_per": 10.0, "t_roe": 10.0, "market": "KOSPI"}
    if shares is not None:
        c["outstanding_shares"] = shares
        c["outstanding_shares_source"] = source
    return c


def _wire_collector_to_tmp(monkeypatch, tmp_path):
    """run_kospi200_collector() 가 실전 data/ 를 읽지도 쓰지도 않게 하고, 네트워크 부수 경로를 끊습니다."""
    fake_root = tmp_path / "repo"
    (fake_root / "data").mkdir(parents=True)
    monkeypatch.setattr(K, "__file__", str(fake_root / "collector_kospi200.py"))
    monkeypatch.setattr(K, "record_daily_history", lambda **kw: {"recorded": False, "reason": "test"})
    monkeypatch.setattr(K, "stock_history_path", lambda name: str(fake_root / "data" / name))
    monkeypatch.setattr(K.data_sanity, "check_dataset", lambda *a, **kw: None)
    monkeypatch.setattr(K, "update_pegy_summary_history", lambda *a, **kw: None)
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
    monkeypatch.setattr(K, "HAS_YFINANCE", False)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    return fake_root


def _wire_new_api(monkeypatch, rows):
    """신 API 목록·상세 응답을 픽스처로 대신하고, 마스터 파일 판정을 고정합니다. 요청 URL 을 기록합니다."""
    urls = []
    codes = [r["itemcode"] for r in rows]

    def fake_get_json(url):
        urls.append(url)
        m = re.search(r"startIdx=(\d+)", url)
        if m:
            page = int(m.group(1))
            return (rows if page == 0 else []), None
        m = re.search(r"/detail/(\w+)/detail", url)
        return _detail_payload(m.group(1)), None

    monkeypatch.setattr(K, "_new_api_get_json", fake_get_json)
    monkeypatch.setattr(K, "load_ticker_types", lambda: {c: "STOCK" for c in codes})
    monkeypatch.setattr(K, "load_ticker_markets", lambda: {c: "KOSPI" for c in codes})
    monkeypatch.setattr(K, "_get_ticker_types_cached", lambda: {c: "STOCK" for c in codes})
    monkeypatch.setattr(K, "_fetch_wisereport_metrics", lambda code, errors: None)
    return urls


def _run_collector(monkeypatch, source):
    with mock.patch.dict(os.environ, {NS.NAVER_SOURCE_ENV_VAR: source}, clear=False):
        path = K.run_kospi200_collector()
    return json.loads(Path(path).read_text(encoding="utf-8")), Path(path)


# ─────────────────────────────────────────────────────────────────────────────
# ① 🔴 사고 재현 — 신 경로 + FDR 통째로 404 → 끝까지 성공
# ─────────────────────────────────────────────────────────────────────────────
def test_incident_2026_09_08_new_api_survives_when_fdr_is_404(monkeypatch, tmp_path):
    """
    2026-09-08 17:40 사고 모양 그대로: 목록 API 정상(전 종목 CLOSE, listedStockCnt 있음) + FDR 404.
    고치기 전에는 여기서 RuntimeError("상장주식수 매칭 실패로 … 0개")로 죽었습니다.
    """
    _wire_collector_to_tmp(monkeypatch, tmp_path)
    rows = _list_rows()
    _wire_new_api(monkeypatch, rows)
    fdr = _FdrDown()
    monkeypatch.setattr(K, "HAS_FDR", True)
    monkeypatch.setattr(K, "fdr", fdr, raising=False)

    payload, path = _run_collector(monkeypatch, "new_api")

    stocks = {s["code"]: s for s in payload["stocks"]}
    expect = {r["itemcode"]: (float(r["nowPrice"]), int(r["listedStockCnt"])) for r in rows}
    check(str(path).startswith(str(tmp_path)), "🔴 실전 data/ 가 아니라 tmp 에 썼음", f"({path})")
    check(len(stocks) == len(rows), "후보 전부가 순위에 들어가 스냅샷에 실림", f"({len(stocks)}/{len(rows)})")
    check(all(stocks[c]["market_cap"] == p * n for c, (p, n) in expect.items() if c in stocks),
          "시가총액 = 현재가 × 목록 응답 listedStockCnt")
    check(all(stocks[c]["outstanding_shares"] == n for c, (p, n) in expect.items() if c in stocks),
          "종목별 outstanding_shares 도 목록 응답 값(순위와 같은 숫자)")
    check(fdr.calls == 0, "🔴 후보 전부에 값이 있으므로 FDR 을 두드리지 않음(§0-3-2)", f"(호출 {fdr.calls}회)")
    meta = payload["metadata"].get("outstanding_shares_source") or {}
    check(meta.get("counts") == {K.SHARES_SOURCE_NAVER_LIST: len(rows)},
          "metadata: 상장주식수 출처가 전부 목록 API 로 기록됨(§0-1)", f"({meta})")
    check(meta.get("fdr_attempted") is False and meta.get("excluded_missing_count") == 0,
          "metadata: FDR 미조회·제외 0 으로 기록됨", f"({meta})")
    check(meta.get("priority") == [K.SHARES_SOURCE_NAVER_LIST, K.SHARES_SOURCE_FDR],
          "metadata: 우선순위(목록 API → FDR)가 적혀 있음", f"({meta.get('priority')})")
    check(payload["metadata"]["naver_source"] == "new_api", "신 경로로 돌았음")
    # 순위 자체도 시가총액 내림차순이어야 합니다(목록 값으로 계산했다는 또 하나의 증거).
    ranked = sorted(payload["stocks"], key=lambda s: s["rank"])
    caps = [s["market_cap"] for s in ranked]
    check(caps == sorted(caps, reverse=True), "순위가 시가총액 내림차순", f"({caps[:3]}…)")


def test_new_api_falls_back_to_fdr_only_for_candidates_without_shares_and_survives_404(monkeypatch, tmp_path):
    """
    목록 응답에 상장주식수가 **없는 종목이 하나** 있는 날: FDR 을 폴백으로 딱 한 번 두드리고,
    그마저 404 면 **그 종목만** 제외하고 나머지는 산다(§0-1 — 지어내지 않고, 사실은 metadata 에).
    """
    _wire_collector_to_tmp(monkeypatch, tmp_path)
    rows = _list_rows()
    rows[3]["listedStockCnt"] = None          # 삼성전기 — 상장주식수 없음
    missing_code = rows[3]["itemcode"]
    _wire_new_api(monkeypatch, rows)
    fdr = _FdrDown()
    monkeypatch.setattr(K, "HAS_FDR", True)
    monkeypatch.setattr(K, "fdr", fdr, raising=False)

    payload, _ = _run_collector(monkeypatch, "new_api")

    codes = {s["code"] for s in payload["stocks"]}
    meta = payload["metadata"]["outstanding_shares_source"]
    check(fdr.calls == 1, "값이 없는 후보가 있으므로 FDR 폴백을 정확히 한 번 조회", f"(호출 {fdr.calls}회)")
    check(missing_code not in codes and len(codes) == len(rows) - 1,
          "상장주식수를 어디서도 못 찾은 종목만 제외, 나머지는 수집됨", f"({sorted(codes)})")
    check(meta["fdr_attempted"] is True and meta["fdr_lookup_count"] == 0 and meta["excluded_missing_count"] == 1,
          "metadata: FDR 조회했으나 0건·제외 1 로 기록됨", f"({meta})")
    check(meta["counts"] == {K.SHARES_SOURCE_NAVER_LIST: len(rows) - 1}, "나머지는 목록 API 출처", f"({meta})")


def test_new_api_fdr_fallback_value_is_used_and_labelled(monkeypatch, tmp_path):
    """폴백이 살아 있는 날: 목록에 없는 종목의 상장주식수는 FDR 값으로 채워지고 출처 라벨이 FDR 로 남는다."""
    _wire_collector_to_tmp(monkeypatch, tmp_path)
    rows = _list_rows()
    rows[3]["listedStockCnt"] = None
    missing_code = rows[3]["itemcode"]
    _wire_new_api(monkeypatch, rows)
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: {missing_code: 74_693_696})

    payload, _ = _run_collector(monkeypatch, "new_api")

    stocks = {s["code"]: s for s in payload["stocks"]}
    meta = payload["metadata"]["outstanding_shares_source"]
    check(stocks[missing_code]["outstanding_shares"] == 74_693_696 and
          stocks[missing_code]["market_cap"] == float(rows[3]["nowPrice"]) * 74_693_696,
          "폴백 종목은 FDR 값으로 순위·상장주식수가 채워짐", f"({stocks.get(missing_code, {}).get('market_cap')})")
    check(meta["counts"] == {K.SHARES_SOURCE_NAVER_LIST: len(rows) - 1, K.SHARES_SOURCE_FDR: 1},
          "metadata: 출처가 종목 수로 정확히 나뉘어 기록됨", f"({meta['counts']})")
    check(meta["fdr_attempted"] is True and meta["fdr_lookup_count"] == 1, "FDR 조회 사실이 기록됨", f"({meta})")


# ─────────────────────────────────────────────────────────────────────────────
# ② 우선순위 (단위)
# ─────────────────────────────────────────────────────────────────────────────
def test_rank_prefers_candidate_shares_over_lookup_and_falls_back_per_candidate(capsys):
    candidates = [
        _candidate("OWN", 100, shares=1_000, source=K.SHARES_SOURCE_NAVER_LIST),   # 목록 값 1,000 / FDR 은 9 (다름)
        _candidate("FDR_ONLY", 100),                                             # 후보엔 없음 → FDR 500
        _candidate("NONE", 999_999),                                             # 어디에도 없음 → 제외
        _candidate("OWN_ZERO", 100, shares=0, source=K.SHARES_SOURCE_NAVER_LIST),  # 0 은 값이 아님 → FDR 7
    ]
    lookup = {"OWN": 9, "FDR_ONLY": 500, "OWN_ZERO": 7}

    ranked = {c["code"]: c for c in K._rank_candidates_by_market_cap(candidates, lookup)}

    check("NONE" not in ranked, "어디에도 없는 종목은 제외(지어내지 않음)")
    check(ranked["OWN"]["market_cap"] == 100 * 1_000 and ranked["OWN"]["outstanding_shares_source"] == K.SHARES_SOURCE_NAVER_LIST,
          "후보가 가진 값이 FDR 보다 먼저", f"({ranked.get('OWN')})")
    check(ranked["FDR_ONLY"]["market_cap"] == 100 * 500 and ranked["FDR_ONLY"]["outstanding_shares_source"] == K.SHARES_SOURCE_FDR,
          "후보에 없으면 FDR 폴백 + 출처 라벨 FDR", f"({ranked.get('FDR_ONLY')})")
    check(ranked["OWN_ZERO"]["market_cap"] == 100 * 7 and ranked["OWN_ZERO"]["outstanding_shares"] == 7,
          "후보 값 0 은 값이 아니므로 FDR 로", f"({ranked.get('OWN_ZERO')})")
    out = capsys.readouterr().out
    check("NONE" in out and "제외" in out, "제외 사실이 로그에 남음")


def test_prepare_lookup_skips_fdr_when_every_candidate_has_shares(monkeypatch):
    calls = []
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: calls.append(1) or {"A": 1})
    lookup, attempted = K._prepare_shares_lookup([_candidate("A", 1, shares=10, source=K.SHARES_SOURCE_NAVER_LIST)])
    check(lookup == {} and attempted is False and calls == [], "전부 값이 있으면 FDR 을 부르지 않음(§0-3-2)", f"({lookup}, {attempted}, {calls})")
    lookup, attempted = K._prepare_shares_lookup([_candidate("A", 1, shares=10, source=K.SHARES_SOURCE_NAVER_LIST), _candidate("B", 1)])
    check(lookup == {"A": 1} and attempted is True and calls == [1], "하나라도 없으면 FDR 을 딱 한 번 부름", f"({lookup}, {attempted}, {calls})")


# ─────────────────────────────────────────────────────────────────────────────
# ③ 구 경로 불변
# ─────────────────────────────────────────────────────────────────────────────
def test_legacy_path_still_uses_fdr_for_everything_and_stops_when_fdr_is_empty(monkeypatch, tmp_path):
    """구 경로 후보에는 상장주식수가 없습니다 → 예전과 똑같이 FDR 이 유일한 출처이고, FDR 이 비면 예전처럼 중단."""
    _wire_collector_to_tmp(monkeypatch, tmp_path)
    monkeypatch.delenv(NS.NAVER_SOURCE_ENV_VAR, raising=False)
    legacy = [_candidate("005930", 1000), _candidate("000660", 1000)]
    monkeypatch.setattr(K, "fetch_kospi200_real_market_data", lambda naver_source=None: ([dict(c) for c in legacy], []))
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps", lambda code: K._empty_item_info("t"))
    monkeypatch.setattr(K, "_get_ticker_types_cached", lambda: {"005930": "STOCK", "000660": "STOCK"})
    fdr_calls = []
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: fdr_calls.append(1) or {"005930": 100, "000660": 50})
    enrich_seen = {}
    real_enrich = K.enrich_quant_metrics

    def spy_enrich(stocks, shares_lookup=None, naver_source=None):
        enrich_seen["lookup"] = dict(shares_lookup)
        return real_enrich(stocks, shares_lookup=shares_lookup, naver_source=naver_source)

    monkeypatch.setattr(K, "enrich_quant_metrics", spy_enrich)

    with mock.patch.dict(os.environ, {}, clear=False):
        payload = json.loads(Path(K.run_kospi200_collector()).read_text(encoding="utf-8"))

    stocks = {s["code"]: s for s in payload["stocks"]}
    meta = payload["metadata"]["outstanding_shares_source"]
    check(fdr_calls == [1], "구 경로는 예전처럼 FDR 을 정확히 한 번 조회", f"({fdr_calls})")
    check(stocks["005930"]["market_cap"] == 1000 * 100 and stocks["000660"]["market_cap"] == 1000 * 50,
          "구 경로 시가총액은 FDR 값으로 계산(예전과 동일)")
    check(meta["counts"] == {K.SHARES_SOURCE_FDR: 2} and meta["fdr_attempted"] is True,
          "metadata: 구 경로는 출처 전부 FDR 로 기록", f"({meta})")
    check(enrich_seen["lookup"] == {"005930": 100, "000660": 50},
          "enrich 가 받는 lookup 값은 예전(FDR)과 같은 숫자", f"({enrich_seen})")

    # FDR 이 통째로 비면 — 구 경로는 다른 출처가 없으므로 예전처럼 중단합니다(지어내지 않음).
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: {})
    monkeypatch.setattr(K, "fetch_kospi200_real_market_data", lambda naver_source=None: ([dict(c) for c in legacy], []))
    with pytest.raises(RuntimeError) as e:
        K.run_kospi200_collector()
    check("상장주식수 매칭 실패" in str(e.value), "구 경로 + FDR 빈 dict → 예전과 같은 중단 사유", f"({e.value})")


def test_legacy_list_candidates_carry_no_outstanding_shares_key():
    """구 목록 파서가 상장주식수를 후보에 싣기 시작하면 '구 경로 = FDR 전용' 전제가 무너집니다. 코드로 못 박습니다."""
    src = inspect.getsource(K.fetch_kospi200_real_market_data)
    legacy_body = src.split("여기서부터 구 경로", 1)[1]
    check("outstanding_shares" not in legacy_body, "구 경로 본문에 outstanding_shares 가 없음")


def test_collector_resolves_shares_through_prepare_helper_only():
    """수집기 본문이 FDR 을 직접 부르면 '필요할 때만' 규칙이 사라집니다 — 한 곳(_prepare_shares_lookup)만 허용."""
    src = inspect.getsource(K.run_kospi200_collector)
    check("_prepare_shares_lookup(" in src, "수집기가 _prepare_shares_lookup 을 씀")
    check("_load_outstanding_shares_lookup()" not in src, "수집기 본문이 FDR 을 직접 부르지 않음")
    check("_summarize_shares_sources(" in src and '"outstanding_shares_source"' in src,
          "출처 집계가 metadata 에 실림(§0-1)")


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ enrich — FDR 이 비어도 종목 상세의 상장주식수를 버리지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def _run_enrich_one(monkeypatch, item_shares, lookup, source):
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
    monkeypatch.setattr(K, "HAS_YFINANCE", False)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "_get_ticker_types_cached", lambda: {"000660": "STOCK"})
    item = K._empty_item_info("t")
    item["outstanding_shares"] = item_shares
    monkeypatch.setattr(K, "fetch_naver_item_new_api", lambda code, ticker_types=None: dict(item))
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps", lambda code: dict(item))
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: (_ for _ in ()).throw(AssertionError("FDR 직접 조회")))
    out = K.enrich_quant_metrics([_candidate("000660", 1000)], shares_lookup=lookup, naver_source=source)
    return out[0]


def test_enrich_keeps_detail_api_shares_when_lookup_is_empty(monkeypatch):
    s = _run_enrich_one(monkeypatch, 730_492_365, {}, "new_api")
    check(s["outstanding_shares"] == 730_492_365, "lookup 이 비어도 종목 상세의 상장주식수가 살아남음", f"({s['outstanding_shares']})")
    s2 = _run_enrich_one(monkeypatch, 730_492_365, {"000660": 730_000_000}, "new_api")
    check(s2["outstanding_shares"] == 730_000_000, "lookup(순위 계산에 쓴 값)이 있으면 그 값이 1차", f"({s2['outstanding_shares']})")


def test_enrich_suspicious_shares_label_names_the_real_source(monkeypatch):
    """의심 기록의 라벨이 신 경로에서 'FDR' 이라고 적히면 거짓 기록입니다(§0-1). 구 경로 문구는 그대로."""
    s_new = _run_enrich_one(monkeypatch, 12, {}, "new_api")      # 12 < MIN → 의심 기록
    s_old = _run_enrich_one(monkeypatch, 12, {}, "legacy")
    new_issue = [i for i in s_new["data_issues"] if "상장주식수 파싱 오류 의심" in i]
    old_issue = [i for i in s_old["data_issues"] if "상장주식수 파싱 오류 의심" in i]
    check(s_new["outstanding_shares"] is None and s_old["outstanding_shares"] is None, "둘 다 미달 값은 None")
    check(new_issue and "FDR=" not in new_issue[0] and "목록API" in new_issue[0],
          "신 경로 라벨은 FDR 단독이 아니라 실제 1차 출처(목록API)를 말함", f"({new_issue})")
    check(old_issue == ["상장주식수 파싱 오류 의심 (네이버=12, FDR=None)"], "구 경로 문구는 한 글자도 안 바뀜", f"({old_issue})")


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ 목록 파싱 카운터 — 실제로 빠진 행 수 vs 종목이 유지된 파서 메모
# ─────────────────────────────────────────────────────────────────────────────
def test_list_parse_counter_counts_dropped_rows_not_dividend_notes(monkeypatch, capsys):
    rows = _list_rows()
    rows[2]["dividend"] = "0"; rows[2]["dividendRate"] = "1.5"     # 배당 모순 → 메모만, 종목은 유지
    rows[4]["dividend"] = "0"; rows[4]["dividendRate"] = "0.9"     # 하나 더
    broken = dict(rows[5]); broken["itemcode"] = None               # 진짜 깨진 행 → 빠짐
    rows[5] = broken
    _wire_new_api(monkeypatch, rows)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)

    out, _ = K._fetch_market_list_new_api()
    log = capsys.readouterr().out

    check(len(out) == len(rows) - 1, "깨진 행 하나만 빠지고 모순 종목은 유지됨", f"({len(out)})")
    check("'parse': 1" in log, "skipped parse = 실제로 빠진 행 수(1)", f"({[l for l in log.splitlines() if 'skipped' in l]})")
    check("파서 메모 3건" in log, "파서 메모(모순 2 + 건너뜀 사유 1)는 따로 셈", f"({[l for l in log.splitlines() if 'skipped' in l]})")
    check(log.count("모순") == 2, "모순 메모는 여전히 한 줄씩 로그에 남음(§0-1)", f"({log.count('모순')})")


def main():
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
