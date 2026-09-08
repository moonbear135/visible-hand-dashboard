# tests/test_naver_source_switch.py
"""
🔀 네이버 출처 전환 스위치 배선 검사 (2026-09-08, 이관 4단계 — `NAVER_MIGRATION_WORK_ORDER.md` §9)

무엇을 지키는가 (오너 지시 순서대로):
  ① **기본값이 구 출처(legacy)** 인가 — 실전 전환은 오너 승인 사항(§0-3-6)이라 세션이 뒤집으면 안 됩니다.
  ② **스위치가 한 곳에만** 있는가 — 기본값·환경변수 이름이 두 곳에 적히면 한쪽만 고쳐질 때
     어느 쪽이 진짜인지 알 수 없습니다(§0-3-10). 워크플로우 YAML 에도 `legacy` 를 다시 적지 않습니다.
  ③ **산출물에 출처가 기록**되는가 — 스냅샷 metadata 에 `naver_source` 가 없으면 나중에
     "이 숫자가 어디서 온 것인지" 아무도 모릅니다(§0-1).
  ④ **NXT 주소가 안 쓰이는가** — 신 경로의 모든 주소는 파서 모듈의 `build_*_url()` 을 거치고,
     그 안의 `assert_krx_source()` 가 넥스트레이드 주소를 예외로 막습니다(§1-5-11).
  ⑤ 신 경로의 안전장치 — 장중(marketStatus≠CLOSE) 값 미채택, 403/429 즉시 중단(재시도 없음),
     페이지 인덱스(오프셋 아님), 마스터 한 곳에서만 종목 선별(코넥스·ETF 제외, 코스닥글로벌→KOSDAQ).
  ⑥ 구 경로가 **지워지지 않았고** 스위치가 꺼져 있으면 예전 함수가 그대로 불리는가.

📌 네트워크는 전부 가짜입니다. 파싱·필터·판정은 진짜 코드가 돕니다.
실행: python -m pytest tests/test_naver_source_switch.py -v
"""
import json
import os
import re
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다.
from conftest import FAILURES, check  # noqa: E402,F401
import pytest  # noqa: E402

import collector_kospi200 as K  # noqa: E402
from utils import naver_source as NS  # noqa: E402
from utils import naver_stock_api as API  # noqa: E402
from utils.naver_stock_api import NaverApiSourceError  # noqa: E402

FIXTURES_NEW = REPO_ROOT / "tests" / "fixtures" / "naver_new_api"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scrape.yml"


def _detail_payload():
    return json.loads((FIXTURES_NEW / "detail_000660_codeType_KRX.json").read_text(encoding="utf-8"))


def _wisereport_html():
    return (FIXTURES_NEW / "wisereport_c1010001_000660.html").read_text(encoding="utf-8")


def _list_rows_from_fixture():
    """NXT 픽스처의 **값**만 빌려 쓰고 주소는 KRX 로 만듭니다(파서는 값이 아니라 주소로 NXT 를 판정)."""
    return json.loads((FIXTURES_NEW / "market_list_marketSum_NXT_top10.json").read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# ① 기본값
# ─────────────────────────────────────────────────────────────────────────────

def test_default_source_is_legacy():
    """🔴 이 파일에서 가장 중요한 검사. 기본값을 신 출처로 바꾸는 것은 오너 결정입니다(§0-3-6)."""
    check(NS.DEFAULT_NAVER_SOURCE == NS.NAVER_SOURCE_LEGACY, "기본값 = legacy",
          f"(실제 {NS.DEFAULT_NAVER_SOURCE!r})")
    check(NS.resolve_naver_source({}) == NS.NAVER_SOURCE_LEGACY, "환경변수 미설정 → legacy")
    check(NS.resolve_naver_source({NS.NAVER_SOURCE_ENV_VAR: ""}) == NS.NAVER_SOURCE_LEGACY,
          "환경변수 빈 문자열 → legacy")
    check(NS.resolve_naver_source({NS.NAVER_SOURCE_ENV_VAR: "new_api"}) == NS.NAVER_SOURCE_NEW_API,
          "new_api 로 켜짐")
    check(NS.resolve_naver_source({NS.NAVER_SOURCE_ENV_VAR: "  New_API "}) == NS.NAVER_SOURCE_NEW_API,
          "대소문자·공백은 관용")


def test_unknown_switch_value_fails_loudly_instead_of_falling_back():
    """오타를 기본값으로 눌러 담으면 '켰다고 믿는데 구 출처가 도는' 겉보기 정상이 됩니다(§0-1)."""
    for bad in ("new-api", "newapi", "NEW", "on", "true", "1", "stock.naver.com"):
        with pytest.raises(ValueError):
            NS.resolve_naver_source({NS.NAVER_SOURCE_ENV_VAR: bad})


def test_describe_records_what_a_person_needs_to_know():
    for src in NS.NAVER_SOURCES:
        d = NS.describe_naver_source(src)
        check(d["naver_source"] == src, f"{src}: 키가 그대로")
        check("legacy" in d["switch"] or "NAVER_SOURCE" in d["switch"], f"{src}: 켜는 법이 적혀 있음")
        for key in ("label", "list_endpoint", "detail_endpoint", "exchange", "wisereport_endpoint"):
            check(bool(d.get(key)), f"{src}: metadata 에 {key} 가 있음")
    check(NS.describe_naver_source("legacy")["is_default"] is True, "legacy 가 기본값이라고 기록됨")
    check(NS.describe_naver_source("new_api")["is_default"] is False, "new_api 는 기본값이 아니라고 기록됨")
    with pytest.raises(ValueError):
        NS.describe_naver_source("nxt")


# ─────────────────────────────────────────────────────────────────────────────
# ② 단일 출처
# ─────────────────────────────────────────────────────────────────────────────

def _repo_source_files():
    """검사 대상 소스(테스트·아카이브·휴지통 제외)."""
    out = []
    for pattern in ("*.py", "utils/*.py", "web/**/*.py", ".github/workflows/*.yml"):
        for p in REPO_ROOT.glob(pattern):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("tests/", "archive/", "_to_delete/")):
                continue
            out.append(p)
    return out


def test_switch_default_and_env_name_are_defined_in_exactly_one_place():
    defined_default, env_literal = [], []
    for p in _repo_source_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^DEFAULT_NAVER_SOURCE\s*=", src, re.M):
            defined_default.append(p.name)
        # 환경변수 이름을 문자열로 직접 적은 곳 — 스위치 모듈 밖에서 적으면 두 번째 정의입니다.
        if '"NAVER_SOURCE"' in src or "'NAVER_SOURCE'" in src:
            env_literal.append(p.name)
    check(defined_default == ["naver_source.py"], "DEFAULT_NAVER_SOURCE 정의는 utils/naver_source.py 한 곳",
          f"(실제 {defined_default})")
    check(env_literal == ["naver_source.py"], "환경변수 이름 문자열은 utils/naver_source.py 한 곳",
          f"(실제 {env_literal})")


def test_collector_reads_the_switch_only_through_the_resolver():
    src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check("from utils.naver_source import" in src, "수집기가 스위치 모듈을 import")
    check("resolve_naver_source()" in src, "수집기가 resolve_naver_source() 로 읽음")
    for banned in ('os.environ.get("NAVER', "os.environ.get('NAVER", 'os.getenv("NAVER', "os.getenv('NAVER",
                   'os.environ["NAVER', "os.environ['NAVER"):
        check(banned not in src, f"수집기가 환경변수를 직접 읽지 않음: {banned}")
    # 기본값을 수집기 본문에 다시 적지 않음 — `naver_source = "legacy"` 같은 하드코딩 금지.
    check(not re.search(r'naver_source\s*=\s*["\']', src), "수집기 본문에 출처 값을 하드코딩하지 않음")


def test_workflow_has_a_commented_switch_line_and_no_invalid_active_value():
    """오너가 켜고 끄는 줄이 실제로 있고, 켜져 있다면 허용값이어야 합니다(오타는 실행 전에 잡음).

    🔴 2026-09-08 정정 — 처음에는 "주석 처리된 안내 줄이 **반드시** 있어야 한다"고 못 박았는데,
       그건 **스위치가 영영 꺼져 있어야 한다**는 뜻이 되어 버립니다. 같은 날 오너 승인으로
       실제로 켰더니(구 순위 페이지가 0건을 돌려주기 시작) 이 검사가 걸렸습니다.
       스위치는 **켜지라고 만든 것**이므로, 지켜야 할 것은 "꺼져 있음"이 아니라
       **"켜져 있든 꺼져 있든 그 줄을 사람이 찾을 수 있고 값이 유효하다"** 입니다.
    """
    yml = WORKFLOW.read_text(encoding="utf-8")
    commented = re.search(r"^\s*#\s*NAVER_SOURCE:\s*\S+\s*$", yml, re.M) is not None
    active = re.findall(r"^\s*NAVER_SOURCE:\s*(\S+)\s*$", yml, re.M)
    check(commented or active,
          "scrape.yml 에서 NAVER_SOURCE 줄을 찾을 수 있음 (꺼져 있으면 주석, 켜져 있으면 값)")
    check(len(active) <= 1,
          "켜진 NAVER_SOURCE 가 두 줄 이상이 아님 (뒤엣것이 조용히 이김)",
          f"({active})")
    for value in active:
        check(value.strip('"\'') in NS.NAVER_SOURCES, f"켜진 NAVER_SOURCE 값이 허용값: {value}")
    # 기본값을 YAML 에 다시 적지 않습니다(§0-3-10). 켜는 것은 new_api 뿐이라 legacy 가 켜져 있을 이유가 없습니다.
    check(not any(v.strip('"\'') == NS.NAVER_SOURCE_LEGACY for v in active),
          "YAML 이 기본값(legacy)을 다시 적어 두지 않음")


# ─────────────────────────────────────────────────────────────────────────────
# ③ 산출물에 출처 기록
# ─────────────────────────────────────────────────────────────────────────────

def _run_collector_with_everything_faked(monkeypatch, tmp_path, environ):
    """`run_kospi200_collector()` 를 네트워크·실전 파일 없이 끝까지 돌립니다. 스냅샷은 tmp 에 씁니다."""
    fake_root = tmp_path / "repo"
    (fake_root / "data").mkdir(parents=True)
    monkeypatch.setattr(K, "__file__", str(fake_root / "collector_kospi200.py"))  # data_dir → tmp
    monkeypatch.setattr(K, "_load_outstanding_shares_lookup", lambda: {"005930": 100, "000660": 50})
    monkeypatch.setattr(K, "record_daily_history", lambda **kw: {"recorded": False, "reason": "test"})
    monkeypatch.setattr(K, "stock_history_path", lambda name: str(fake_root / "data" / name))
    monkeypatch.setattr(K.data_sanity, "check_dataset", lambda *a, **kw: None)
    calls = {"list": [], "enrich": []}

    def fake_list(naver_source=None):
        calls["list"].append(naver_source)
        return ([{"name": "삼성전자", "code": "005930", "price": 1000.0, "t_per": 10.0, "t_roe": 10.0, "market": "KOSPI"},
                 {"name": "SK하이닉스", "code": "000660", "price": 1000.0, "t_per": 8.0, "t_roe": 40.0, "market": "KOSPI"}],
                [])

    def fake_enrich(stocks, shares_lookup=None, naver_source=None):
        calls["enrich"].append(naver_source)
        return [{**s, "is_valid": True, "is_unverified": False, "is_trailing_loss": False} for s in stocks]

    monkeypatch.setattr(K, "fetch_kospi200_real_market_data", fake_list)
    monkeypatch.setattr(K, "enrich_quant_metrics", fake_enrich)
    monkeypatch.setattr(K, "update_pegy_summary_history", lambda *a, **kw: None)
    with mock.patch.dict(os.environ, environ, clear=False):
        for k in list(os.environ):
            if k == NS.NAVER_SOURCE_ENV_VAR and k not in environ:
                monkeypatch.delenv(k)
        path = K.run_kospi200_collector()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload, calls, Path(path)


def test_snapshot_metadata_records_the_source_legacy_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv(NS.NAVER_SOURCE_ENV_VAR, raising=False)
    payload, calls, path = _run_collector_with_everything_faked(monkeypatch, tmp_path, {})
    meta = payload["metadata"]
    check(meta.get("naver_source") == "legacy", "metadata.naver_source == legacy", f"(실제 {meta.get('naver_source')!r})")
    check(isinstance(meta.get("data_source"), dict) and meta["data_source"].get("naver_source") == "legacy",
          "metadata.data_source 블록이 있고 legacy 를 가리킴")
    check(meta["data_source"].get("is_default") is True, "기본값으로 돌았다고 기록됨")
    check(calls["list"] == ["legacy"] and calls["enrich"] == ["legacy"],
          "목록·상세 양쪽에 같은 스위치 값이 전달됨", f"({calls})")
    check(str(path).startswith(str(tmp_path)), "🔴 실전 data/ 가 아니라 tmp 에 썼음", f"({path})")


def test_snapshot_metadata_records_new_api_when_switched_on(monkeypatch, tmp_path):
    payload, calls, _ = _run_collector_with_everything_faked(
        monkeypatch, tmp_path, {NS.NAVER_SOURCE_ENV_VAR: "new_api"})
    meta = payload["metadata"]
    check(meta.get("naver_source") == "new_api", "metadata.naver_source == new_api", f"(실제 {meta.get('naver_source')!r})")
    check(meta["data_source"].get("is_default") is False, "스위치로 켰다고 기록됨")
    check("KRX" in meta["data_source"].get("exchange", ""), "KRX 고정임이 metadata 에 적힘")
    check(calls["list"] == ["new_api"] and calls["enrich"] == ["new_api"],
          "목록·상세 양쪽에 new_api 가 전달됨", f"({calls})")


def test_collector_refuses_to_start_on_a_typo(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        _run_collector_with_everything_faked(monkeypatch, tmp_path, {NS.NAVER_SOURCE_ENV_VAR: "new-api"})


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ 구 경로 보존 + 스위치 분기
# ─────────────────────────────────────────────────────────────────────────────

def test_legacy_path_still_exists_and_is_used_when_switch_is_off(monkeypatch):
    src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check("https://finance.naver.com/item/main.naver?code=" in src, "구 종목 상세 주소가 그대로 남아 있음")
    check("sise/sise_market_sum.naver?sosok=" in src, "구 목록 주소가 그대로 남아 있음")
    check("def _parse_aside_invest_info" in src and "def _parse_financial_statement" in src,
          "구 HTML 파서 두 구획이 지워지지 않음")

    called = []
    monkeypatch.setattr(K, "fetch_naver_item_dps_and_eps", lambda code: called.append(("legacy", code)) or K._empty_item_info("t"))
    monkeypatch.setattr(K, "fetch_naver_item_new_api", lambda code: called.append(("new", code)) or K._empty_item_info("t"))
    monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    raw = [{"code": "005930", "name": "삼성전자", "price": 1000.0, "t_per": 10.0, "t_roe": 10.0, "market": "KOSPI"}]
    K.enrich_quant_metrics([dict(raw[0])], shares_lookup={}, naver_source="legacy")
    K.enrich_quant_metrics([dict(raw[0])], shares_lookup={}, naver_source="new_api")
    check(called == [("legacy", "005930"), ("new", "005930")], "스위치 값대로 구/신 상세 함수가 불림", f"({called})")


def test_list_dispatches_on_the_switch(monkeypatch):
    monkeypatch.setattr(K, "_fetch_market_list_new_api", lambda: ([{"code": "X"}], []))
    monkeypatch.setattr(K, "load_ticker_types", lambda: {})
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("구 경로가 불렸습니다")))
    out, failed = K.fetch_kospi200_real_market_data(naver_source="new_api")
    check(out == [{"code": "X"}] and failed == [], "new_api 면 신 목록 함수로 넘김")


# ─────────────────────────────────────────────────────────────────────────────
# ④ NXT 차단
# ─────────────────────────────────────────────────────────────────────────────

def test_new_path_urls_come_from_the_parser_module_and_are_krx():
    src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    code_only = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    check(not re.search(r"""["'f]https://stock\.naver\.com""", code_only),
          "수집기 코드에 신 API 주소 문자열이 직접 적혀 있지 않음(파서 모듈 한 곳)")
    check("build_list_url(" in src and "build_detail_url(" in src, "주소는 build_*_url() 로만 만듦")
    scrub = src
    for phrase in ("NXT(넥스트레이드)", "NXT 는", "NXT 주소", "NXT 차단", "NXT 면", "NXT 로", "NXT 계열"):
        scrub = scrub.replace(phrase, "")
    check("NXT" not in scrub, "수집기 코드에 NXT 주소가 없음(설명 문장 제외)")
    check("codeType=KRX" in API.build_detail_url("000660"), "상세 주소가 codeType=KRX")
    check("tradeType=KRX" in API.build_list_url(0), "목록 주소가 tradeType=KRX")


def test_nxt_template_is_refused_at_build_time(monkeypatch):
    """상수를 잘못 고쳐도 주소를 만드는 순간 막힙니다 — 이중 방어."""
    monkeypatch.setattr(API, "DETAIL_URL_TEMPLATE", API.DETAIL_URL_TEMPLATE.replace("KRX", "NXT"))
    with pytest.raises(NaverApiSourceError):
        API.build_detail_url("000660")
    monkeypatch.setattr(API, "LIST_URL_TEMPLATE", API.LIST_URL_TEMPLATE.replace("tradeType=KRX", "tradeType=NXT"))
    with pytest.raises(NaverApiSourceError):
        API.build_list_url(0)


def test_shadow_and_collector_share_the_same_url_constants():
    import run_naver_api_shadow as SH
    check(SH.LIST_URL is API.LIST_URL_TEMPLATE and SH.DETAIL_URL is API.DETAIL_URL_TEMPLATE,
          "섀도와 실전이 같은 주소 상수를 씀(§0-3-10)")
    check(SH.LIST_PAGE_SIZE == API.LIST_PAGE_SIZE == 20, "pageSize 20 (화면이 쓰는 값) 한 곳")


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 신 경로 안전장치
# ─────────────────────────────────────────────────────────────────────────────

def _list_env(monkeypatch, pages, *, types=None, markets=None):
    """가짜 목록 응답(페이지별 리스트) + 마스터 파일 대체. 요청한 URL 을 기록합니다."""
    urls = []

    def fake_get_json(url):
        urls.append(url)
        m = re.search(r"startIdx=(\d+)", url)
        page = int(m.group(1))
        return (pages[page] if page < len(pages) else []), None

    monkeypatch.setattr(K, "_new_api_get_json", fake_get_json)
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    rows = _list_rows_from_fixture()
    codes = [r["itemcode"] for r in rows]
    monkeypatch.setattr(K, "load_ticker_types", lambda: types if types is not None else {c: "STOCK" for c in codes})
    monkeypatch.setattr(K, "load_ticker_markets", lambda: markets if markets is not None else {c: "KOSPI" for c in codes})
    return urls, rows


def test_new_list_refuses_intraday_or_after_market_values(monkeypatch):
    """§1-5-11 — 종가가 아닌 값(장중·다른 시장)은 채택하지 않습니다. 조용히 저장하면 겉보기 정상."""
    urls, rows = _list_env(monkeypatch, [rows_open := [dict(r, marketStatus="OPEN") for r in _list_rows_from_fixture()]])
    with pytest.raises(RuntimeError) as e:
        K._fetch_market_list_new_api()
    check("CLOSE" in str(e.value) and "중단" in str(e.value), "장중(OPEN)이면 수집 중단", f"({e.value})")


def test_new_list_uses_page_index_and_master_file_for_selection(monkeypatch):
    rows = _list_rows_from_fixture()
    for r in rows:
        r["marketStatus"] = "CLOSE"
    codes = [r["itemcode"] for r in rows]
    types = {c: "STOCK" for c in codes}
    types[codes[1]] = "ETF"                       # ETF 는 제외
    markets = {c: "KOSPI" for c in codes}
    markets[codes[2]] = "KONEX"                   # 코넥스는 현행이 수집한 적 없는 시장 → 제외
    markets[codes[3]] = "KOSDAQ GLOBAL"           # 코스닥 글로벌 → 구 경로 라벨 KOSDAQ
    markets[codes[4]] = "KOSDAQ"
    del markets[codes[5]]                         # 마스터에 시장 정보 없음 → 제외(안전한 쪽으로)
    urls, _ = _list_env(monkeypatch, [rows[:5], rows[5:], []], types=types, markets=markets)

    out, failed = K._fetch_market_list_new_api()
    got = {c["code"]: c for c in out}
    check("startIdx=0&" in urls[0] and "startIdx=1&" in urls[1], "startIdx 가 페이지 인덱스(0,1,…)", f"({urls[:2]})")
    check(codes[1] not in got, "ETF 제외")
    check(codes[2] not in got, "코넥스 제외")
    check(codes[5] not in got, "시장 미확인 종목 제외")
    check(got[codes[3]]["market"] == "KOSDAQ", "코스닥 글로벌 → KOSDAQ 라벨", f"({got.get(codes[3])})")
    check(got[codes[4]]["market"] == "KOSDAQ" and got[codes[0]]["market"] == "KOSPI", "시장 라벨은 마스터 기준")
    check(set(got[codes[0]]) >= {"name", "code", "price", "t_per", "t_roe", "market"}, "구 경로와 같은 키")
    check(got["005930"]["price"] == 269000.0 and got["005930"]["t_roe"] == 10.85, "값이 응답 그대로",
          f"({got.get('005930')})")
    check(failed == [], "실패 페이지는 전부 중단으로 승격되므로 빈 목록")


def test_new_list_stops_on_duplicate_codes_across_pages(monkeypatch):
    rows = [dict(r, marketStatus="CLOSE") for r in _list_rows_from_fixture()]
    _list_env(monkeypatch, [rows[:5], rows[:5], []])     # 같은 페이지가 두 번 → 겹침
    with pytest.raises(RuntimeError) as e:
        K._fetch_market_list_new_api()
    check("두 번" in str(e.value), "페이지 겹침을 잡아 중단", f"({e.value})")


def test_new_list_stops_when_a_page_fails(monkeypatch):
    """한 흐름의 순위 목록에서 페이지 하나가 빠지면 그 구간 종목이 통째로 사라집니다 — 일부 실패 허용 없음."""
    rows = [dict(r, marketStatus="CLOSE") for r in _list_rows_from_fixture()]
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "load_ticker_types", lambda: {r["itemcode"]: "STOCK" for r in rows})
    monkeypatch.setattr(K, "load_ticker_markets", lambda: {r["itemcode"]: "KOSPI" for r in rows})
    monkeypatch.setattr(K, "_new_api_get_json", lambda url: (rows[:5], None) if "startIdx=0&" in url else (None, "HTTP 500"))
    with pytest.raises(RuntimeError) as e:
        K._fetch_market_list_new_api()
    check("1페이지" in str(e.value) and "중단" in str(e.value), "실패 페이지에서 중단", f"({e.value})")


def test_403_and_429_stop_immediately_without_retry(monkeypatch):
    """§0-3-2 — 차단은 상대가 그만하라는 뜻. 재시도·우회 없이 즉시 중단."""
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    for status in (403, 429):
        calls = []

        class _R:
            status_code = status
            def json(self):
                return {}

        monkeypatch.setattr(K.requests, "get", lambda url, headers=None, timeout=None: calls.append(url) or _R())
        with pytest.raises(K.NaverApiBlocked):
            K._new_api_get_json(API.build_detail_url("000660"))
        check(len(calls) == 1, f"{status}: 요청 1회 후 즉시 중단(재시도 없음)", f"({len(calls)}회)")
        # 상세 경로에서도 통째로 실패로 승격됩니다(남은 종목으로 계속 가지 않음).
        monkeypatch.setattr(K, "fetch_recent_volatility", lambda code: None)
        with pytest.raises(RuntimeError):
            K.enrich_quant_metrics([{"code": "000660", "name": "SK하이닉스", "price": 1.0, "t_per": 1.0,
                                     "t_roe": 1.0, "market": "KOSPI"}], shares_lookup={}, naver_source="new_api")


def test_transient_errors_retry_like_the_legacy_path_then_give_none(monkeypatch):
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    calls = []

    class _R:
        status_code = 503
        def json(self):
            return {}

    monkeypatch.setattr(K.requests, "get", lambda url, headers=None, timeout=None: calls.append(url) or _R())
    payload, err = K._new_api_get_json(API.build_detail_url("000660"))
    check(payload is None and "503" in err, "일시 오류는 None + 사유", f"({err})")
    check(len(calls) == K.NEW_API_MAX_RETRIES == 3, "구 경로와 같은 3회 재시도", f"({len(calls)}회)")


def test_new_item_matches_legacy_keys_and_fills_f_roe_ev_from_wisereport(monkeypatch):
    """신 경로 상세 한 종목을 픽스처(실제 응답)로 끝까지 돌립니다."""
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": False, "skipped_count": 0})
    urls = []

    def fake_get_json(url):
        urls.append(url)
        return _detail_payload(), None

    class _R:
        status_code = 200
        text = _wisereport_html()

    monkeypatch.setattr(K, "_new_api_get_json", fake_get_json)
    monkeypatch.setattr(K.requests, "get", lambda url, headers=None, timeout=None: _R() if "wisereport" in url
                        else (_ for _ in ()).throw(AssertionError(f"예상 밖 요청: {url}")))

    item = K.fetch_naver_item_new_api("000660", ticker_types={})
    legacy_keys = set(K._empty_item_info("x"))
    check(legacy_keys <= set(item), "구 경로 반환 키를 전부 포함", f"(빠진 키 {legacy_keys - set(item)})")
    check("codeType=KRX" in urls[0], "상세를 KRX 로 요청")
    check(item["t_eps"] == 224313 and item["t_per"] == 7.95, "t_eps 는 eps(krxEps 아님)", f"({item['t_eps']}, {item['t_per']})")
    check(item["f_eps"] == 349342 and item["f_per"] == 5.1, "추정 PER/EPS 는 응답값 그대로", f"({item['f_eps']}, {item['f_per']})")
    check(item["t_pbr"] == 4.81, "PBR 응답값 그대로", f"({item['t_pbr']})")
    check(item["f_roe"] == 101.67, "Forward ROE 는 WiseReport 에서", f"({item['f_roe']})")
    check(item["ev_ebitda"] == "19.51", "EV/EBITDA 는 WiseReport 에서, 문자열 표기 그대로", f"({item['ev_ebitda']!r})")
    check(item["raw_period"] == "TTM", "검증 1단계용 기간 판정이 TTM", f"({item['raw_period']})")
    check(item["outstanding_shares"] == 730492365, "상장주식수")
    check(not any("미수집: 이 API 에 없음" in e for e in item["errors"]),
          "채워 넣은 값에 대한 '미수집' 사유가 남아 있지 않음(§0-1)", f"({item['errors']})")


def test_new_item_applies_the_same_forward_roe_limit_as_legacy(monkeypatch):
    src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    literal_uses = [ln for ln in src.splitlines()
                    if "300.0" in ln.split("#", 1)[0] and "FORWARD_ROE_ABS_LIMIT_PCT" not in ln]
    check(literal_uses == [], "Forward ROE 상한 300 리터럴이 상수 밖에 남아 있지 않음(§0-3-10)", f"({literal_uses})")
    check(K.FORWARD_ROE_ABS_LIMIT_PCT == 300.0, "값은 그대로 300")

    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": False, "skipped_count": 0})
    monkeypatch.setattr(K, "_new_api_get_json", lambda url: (_detail_payload(), None))
    monkeypatch.setattr(K, "_fetch_wisereport_metrics",
                        lambda code, errors: {"f_roe": 999.0, "ev_ebitda": "1.0", "errors": []})
    item = K.fetch_naver_item_new_api("000660", ticker_types={})
    check(item["f_roe"] is None and any("이상치" in e for e in item["errors"]),
          "±300% 초과 Forward ROE 는 제외 + 사유", f"({item['f_roe']}, {item['errors']})")


def test_new_item_request_failure_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(K, "_new_api_get_json", lambda url: (None, "HTTP 500"))
    item = K.fetch_naver_item_new_api("000660", ticker_types={})
    check(item == K._empty_item_info(item["errors"][0]), "요청 실패 → 전부 None + 사유")
    check("HTTP 500" in item["errors"][0], "사유가 구체적", f"({item['errors']})")


def test_new_item_does_not_call_the_legacy_url_for_preferred_parent(monkeypatch):
    """우선주 부모(보통주) 조회도 신 경로여야 합니다 — 스위치가 켜졌는데 구 주소가 섞이면 안 됨."""
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": True, "skipped_count": 0})
    seen = []

    def fake_get_json(url):
        seen.append(url)
        p = _detail_payload()
        p["itemcode"] = re.search(r"/detail/([0-9A-Z]+)/", url).group(1)
        if p["itemcode"].endswith("K"):
            p["dividendAmount"] = None            # 우선주는 배당 미수집 → 부모에서 상속 시도
        return p, None

    monkeypatch.setattr(K, "_new_api_get_json", fake_get_json)
    monkeypatch.setattr(K.requests, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("구 주소 호출")))
    item = K.fetch_naver_item_new_api("00680K", ticker_types={"006800": "STOCK"})
    check(any("/006800/" in u for u in seen), "부모(006800)를 신 API 로 조회", f"({seen})")
    check(item["dps_status"] == "inherited_from_common" and item["dps_inherited_from"] == "006800",
          "상속 사실이 마킹됨", f"({item['dps_status']}, {item['dps_inherited_from']})")


# ─────────────────────────────────────────────────────────────────────────────
# 구 경로의 EV/EBITDA — 공용 파서로 바꿨어도 저장값·사유가 그대로인가
# ─────────────────────────────────────────────────────────────────────────────

def test_legacy_ev_ebitda_via_shared_parser_keeps_the_page_text(monkeypatch):
    monkeypatch.setattr(K.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(K, "_ev_ebitda_circuit", {"consecutive_failures": 0, "open": False, "skipped_count": 0})

    class _R:
        status_code = 200
        text = _wisereport_html()

    monkeypatch.setattr(K.requests, "get", lambda url, headers=None, timeout=None: _R())
    errors = []
    check(K._fetch_ev_ebitda("000660", errors) == "19.51", "실제 페이지에서 '19.51' (현행과 동일)")
    check(errors == [], "정상 페이지에서는 사유 없음", f"({errors})")

    # 재무요약 표가 없는(합성) 페이지 — EV/EBITDA 는 읽되 ROE 관련 사유는 붙이지 않음(구 경로는 그 표를 안 씀)
    _R.text = (REPO_ROOT / "tests" / "fixtures" / "naver_item" / "000010.wisereport.html").read_text(encoding="utf-8")
    errors = []
    check(K._fetch_ev_ebitda("000010", errors) == "6.7", "합성 픽스처 '6.7' (기준선과 동일)")
    check(not any("재무요약" in e or "ROE" in e for e in errors), "구 경로에 재무요약 표 사유가 섞이지 않음", f"({errors})")

    # 페이지 표기 보존 — 구 코드는 셀을 `str(cell)` 로 저장했습니다. 열에 '-' 가 섞여 문자열로 읽히면
    # "3.60" 이 그대로 남아야 합니다(`str(float)` 로 바꾸면 "3.6" 이 되어 스냅샷 문자열이 달라짐).
    _R.text = ("<html><body><table><tr><th>항목</th><th>2024.12</th><th>2025.12</th></tr>"
               "<tr><td>PER</td><td>-</td><td>-</td></tr>"
               "<tr><td>EV/EBITDA</td><td>4.10</td><td>3.60</td></tr></table></body></html>")
    check(K._fetch_ev_ebitda("000000", []) == "3.60", "표기 '3.60' 이 그대로(“3.6” 으로 바뀌지 않음)")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
