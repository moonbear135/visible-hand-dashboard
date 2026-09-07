# tests/test_naver_stock_api.py
"""🔒 `utils/naver_stock_api.py` — 네이버 신 증권 JSON API 파서 테스트 (2026-09-07, #211)

⚠️ 이 파일이 왜 생겼는가

네이버가 2026-09-10 부로 구 증권 서비스 종료를 예고해, 구 HTML 파서를 신 JSON API 로
옮기는 작업의 **첫 단계**입니다. 옮기는 과정에서 조용히 틀릴 수 있는 자리가 네 군데
확인됐고(`NAVER_MIGRATION_WORK_ORDER.md` §1-5-11 · §1-5-4 · §1-5-10), 이 파일은
**그 네 자리를 사람이 아니라 테스트가 지키게** 합니다.

📌 픽스처가 **진짜 응답**입니다 — 구 HTML 픽스처와 다릅니다
   `tests/fixtures/naver_item/*.html` 은 구조만 본뜬 **합성**이었지만,
   `tests/fixtures/naver_new_api/*.json` 은 **2026-09-07 오너가 DevTools 에서 복사한 원문**
   입니다(출처·제외 필드는 그 폴더의 `README.md` 참고).
   · 보증함 — 파서가 필드를 옳게 옮기는지, 함정 네 가지를 실제로 막는지
   · 못 함  — 네이버가 **앞으로 응답 구조를 바꿨을 때**. 그건 `utils/data_sanity.py` 몫입니다.

📌 사람이 복사한 값이라 **전사(轉寫) 오류**가 있을 수 있습니다.
   그래서 `test_fixture_numbers_are_internally_consistent` 가 픽스처 자체를 먼저 검사합니다.
   그 검사가 빨간불이면 **코드가 아니라 픽스처를 고쳐야 합니다.**

실행: python -m pytest tests/test_naver_stock_api.py -v
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# ⚠️ `FAILURES` 와 `check` 를 **둘 다** 가져와야 `test_suite_integrity.py` 의 Check A 가
#    이 파일을 하네스 사용 파일로 인식합니다(하나만 가져오면 통째로 skip 됩니다).
from conftest import FAILURES, check  # noqa: E402,F401
import pytest  # noqa: E402

from utils.naver_stock_api import (  # noqa: E402
    NaverApiSourceError,
    assert_krx_source,
    parse_consensus,
    parse_market_list,
    parse_market_list_row,
    parse_stock_detail,
    DELIBERATELY_UNUSED_DETAIL_FIELDS,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "naver_new_api"
KRX_DETAIL_URL = "https://stock.naver.com/api/domestic/detail/000660/detail?codeType=KRX"
KRX_LIST_URL = ("https://stock.naver.com/api/domestic/market/stock/default"
                "?tradeType=KRX&marketType=ALL&orderType=marketSum&startIdx=0&pageSize=10")


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def detail():
    return _load("detail_000660_codeType_KRX.json")


def market_list():
    return _load("market_list_marketSum_NXT_top10.json")


# ─────────────────────────────────────────────────────────────────────────────
# 0. 픽스처 자체 검사 — 사람이 옮겨 적은 값이라 여기부터 봅니다
# ─────────────────────────────────────────────────────────────────────────────

def test_fixtures_exist():
    """스캐너가 조용히 빈손이 되지 않게 (§0-1)."""
    assert FIXTURES.is_dir(), f"픽스처 폴더가 없습니다: {FIXTURES}"
    for name in ("detail_000660_codeType_KRX.json",
                 "market_list_marketSum_NXT_top10.json",
                 "consensus_000660.json", "README.md"):
        assert (FIXTURES / name).is_file(), f"픽스처가 없습니다: {name}"
    assert len(market_list()) == 10, "목록 픽스처는 10종목이어야 합니다."


def test_fixture_numbers_are_internally_consistent():
    """
    🔴 **픽스처가 잘못 옮겨 적혔는지**를 먼저 봅니다. 이 검사가 빨간불이면 코드가 아니라
    픽스처를 의심하세요. 네이버가 응답 안에 계산 관계를 이미 담고 있어서 가능한 검사입니다.
    """
    d = detail()
    f = lambda k: float(d[k])  # noqa: E731

    check(abs(f("nowPrice") / f("eps") - f("per")) / f("per") < 0.01,
          "상세: per == nowPrice ÷ eps", f'({f("nowPrice")}/{f("eps")} vs {d["per"]})')
    check(abs(f("nowPrice") / f("estimatedEps") - f("estimatedPer")) / f("estimatedPer") < 0.01,
          "상세: estimatedPer == nowPrice ÷ estimatedEps")
    check(abs(f("nowPrice") / f("bps") - f("pbr")) / f("pbr") < 0.01,
          "상세: pbr == nowPrice ÷ bps")
    check(abs(f("dividendAmount") / f("nowPrice") * 100 - f("dividendRate")) / f("dividendRate") < 0.01,
          "상세: dividendRate == dividendAmount ÷ nowPrice × 100 (퍼센트)")

    bad = []
    for r in market_list():
        g = lambda k: None if r[k] in (None, "") else float(r[k])  # noqa: E731
        p, e, per = g("nowPrice"), g("eps"), g("per")
        if e and per and abs(p / e - per) / per > 0.01:
            bad.append(f'{r["itemname"]} per {p/e:.2f} vs {per}')
        shares, msum = g("listedStockCnt"), g("marketSum")
        if shares and msum and abs(shares * p - msum) / msum > 0.02:
            bad.append(f'{r["itemname"]} marketSum {shares*p:,.0f} vs {msum:,.0f}')
    check(not bad, "목록 10종목: per·marketSum 자체 정합", f"({bad})")


# ─────────────────────────────────────────────────────────────────────────────
# 1. 🔴 함정 ① — NXT 차단
# ─────────────────────────────────────────────────────────────────────────────

def test_nxt_sources_are_rejected():
    """
    🔴 이 테스트가 이 파일에서 가장 중요합니다.

    NXT(넥스트레이드)는 15:40~20:00 애프터마켓이 열려 있어, 저녁에 크롤링하면 종가가 아니라
    시간외가를 받습니다. 값이 '틀린' 게 아니라 '다른 시장의 값'이라 산티체크에도 안 걸립니다
    (§1-5-11). 그래서 파서 진입 자체를 막습니다.
    """
    for bad_url in (
        "https://polling.finance.naver.com/api/realtime/domestic/NXT/stock/000660",
        "https://stock.naver.com/api/domestic/detail/000660/detail?codeType=NXT",
        "https://stock.naver.com/api/domestic/market/stock/default?tradeType=NXT&orderType=marketSum",
        "https://stock.naver.com/API/DOMESTIC/DETAIL/000660/DETAIL?CODETYPE=NXT",  # 대문자
    ):
        with pytest.raises(NaverApiSourceError):
            assert_krx_source(bad_url)

    assert_krx_source(KRX_DETAIL_URL)   # KRX 는 통과해야 함
    assert_krx_source(KRX_LIST_URL)

    with pytest.raises(NaverApiSourceError):
        assert_krx_source("")           # 빈 주소도 통과시키지 않습니다


def test_parsers_refuse_nxt_payloads():
    """주소가 NXT 면 응답 내용이 아무리 멀쩡해도 파싱하지 않습니다."""
    nxt = "https://stock.naver.com/api/domestic/market/stock/default?tradeType=NXT"
    with pytest.raises(NaverApiSourceError):
        parse_market_list(market_list(), source_url=nxt, market_label="KOSPI")
    with pytest.raises(NaverApiSourceError):
        parse_stock_detail(detail(), source_url="https://x/detail?codeType=NXT")


# ─────────────────────────────────────────────────────────────────────────────
# 2. 🔴 함정 ②③④ — krxEps · 퍼센트 · 전일종가 PBR
# ─────────────────────────────────────────────────────────────────────────────

def test_eps_comes_from_eps_not_krxeps():
    """
    응답에 `eps`(224,313)와 `krxEps`(62,044)가 둘 다 있고 3.6배 차이납니다.
    `per`(7.95)와 맞아떨어지는 쪽은 `eps` 입니다. 잘못 집으면 EPS 가 조용히 3.6배 틀립니다.
    """
    d = detail()
    out = parse_stock_detail(d, source_url=KRX_DETAIL_URL)
    check(out["t_eps"] == 224313.0, "t_eps 는 eps(224,313)", f'(실제 {out["t_eps"]})')
    check(out["t_eps"] != float(d["krxEps"]), "t_eps 가 krxEps(62,044)가 아님")
    check("krxEps" in DELIBERATELY_UNUSED_DETAIL_FIELDS,
          "krxEps 가 '의도적으로 안 쓰는 필드' 목록에 명시돼 있음")


def test_dividend_rate_is_percent_not_ratio():
    """`0.168` 은 0.168% 입니다. 비율로 착각하면 1000배 틀립니다."""
    out = parse_stock_detail(detail(), source_url=KRX_DETAIL_URL)
    check(out["div_yield"] == 0.168, "div_yield 가 퍼센트 값 그대로", f'(실제 {out["div_yield"]})')
    # 배당수익률 = DPS ÷ 가격 × 100 이 성립해야 퍼센트입니다.
    implied = out["dps"] / out["api_price"] * 100
    check(abs(implied - out["div_yield"]) < 0.01,
          "dps ÷ price × 100 == div_yield (퍼센트 단위 확인)", f"({implied:.4f})")


def test_list_pbr_is_not_promoted_to_t_pbr():
    """
    🔴 목록의 `pbr` 은 **전일 종가 기준**이라 `t_pbr`(현재가 기준)이 아닙니다.
    승격시키면 급등·급락일에 조용히 어긋납니다(§1-5-10).
    """
    row = parse_market_list_row(market_list()[1], market_label="KOSPI")  # SK하이닉스
    check("t_pbr" not in row, "목록 파서 결과에 t_pbr 키가 아예 없음")
    check(row["api_pbr_prev_close_basis"] == 4.44616,
          "원본 pbr 은 오해할 수 없는 이름으로만 보존")
    # 근거 재확인: 전일종가 ÷ 목록 pbr == 상세 bps
    prev_close = float(detail()["prevClosePrice"])
    implied_bps = prev_close / row["api_pbr_prev_close_basis"]
    check(abs(implied_bps - float(detail()["bps"])) / float(detail()["bps"]) < 0.001,
          "전일종가 ÷ 목록pbr == 상세 bps (전일종가 기준임을 수치로 확인)",
          f"({implied_bps:.2f})")


def test_detail_pbr_is_taken_as_given_not_computed():
    """
    🔴 2026-09-08 정정 (오너 방침: **"우리 목표로 따지면 그대로 받는 게 맞다"**).

    처음엔 `현재가 ÷ bps` 로 계산해 넣었는데 두 가지가 틀렸습니다:
      · `f_per` 은 응답값을 그대로 쓰면서 `t_pbr` 만 계산하면 같은 dict 에
        "받은 값"과 "우리가 만든 값"이 섞입니다(§0-1 — 계산값은 마킹해야 합니다).
      · 계산할 이유도 없었습니다 — 상세의 `pbr` 은 **이미 현재가 기준**이고
        현행 스냅샷 값(4.81)과 정확히 같습니다. 전일종가 기준이라 문제였던 것은
        **목록**의 `pbr` 뿐이고 그건 `t_pbr` 로 승격하지 않습니다.
    """
    out = parse_stock_detail(detail(), source_url=KRX_DETAIL_URL)
    check(out["t_pbr"] == 4.81, "t_pbr 은 응답값 그대로", f'({out["t_pbr"]})')
    computed = float(detail()["nowPrice"]) / float(detail()["bps"])
    check(abs(out["t_pbr"] - computed) > 1e-6, "계산값(4.8133)이 아님", f"({computed:.6f})")
    check(not any("교차검증" in e for e in out["errors"]),
          "응답값과 계산값이 2% 안이면 경고 없음")

    # 두 값이 크게 어긋나면 **기록은 남깁니다** (값은 여전히 응답값)
    tampered = dict(detail(), bps="1000")
    out2 = parse_stock_detail(tampered, source_url=KRX_DETAIL_URL)
    check(out2["t_pbr"] == 4.81, "어긋나도 값은 응답값을 유지")
    check(any("교차검증" in e for e in out2["errors"]), "어긋난 사실은 errors 에 기록")


def test_forward_per_is_taken_as_given():
    """
    오너 방침 — 신 API 의 `estimatedPer` 을 그대로 씁니다.
    실측 근거: 현행 `f_per` 은 **258종목 전부가 정수**였습니다(네이버 구 사이트가 추정PER 을
    정수로만 표시). 신 API 는 소수점을 주므로 **더 정밀합니다.**
    """
    out = parse_stock_detail(detail(), source_url=KRX_DETAIL_URL)
    check(out["f_per"] == 5.1, "f_per 은 estimatedPer 그대로", f'({out["f_per"]})')
    computed = float(detail()["nowPrice"]) / float(detail()["estimatedEps"])
    check(abs(out["f_per"] - computed) > 1e-6,
          "현재가÷추정EPS 계산값(5.1039)이 아님", f"({computed:.4f})")


# ─────────────────────────────────────────────────────────────────────────────
# 3. 과거 사고 재발 방지 — 부호 보존 · 미수집/무배당 구분
# ─────────────────────────────────────────────────────────────────────────────

def test_market_and_type_fields_are_kept_for_reference_only():
    """
    🔴 2026-09-08 — 종목 선별 판정은 `kr_ticker_master.json` **한 곳**에서만 합니다(§0-3-10).
    신 API 의 `type`(ST/RT/IF/DR/MF)과 `sosok`(시장 구분)은 **참고 보관만** 합니다.

    두 판정이 생기면 어긋나는 순간 종목이 조용히 사라집니다 —
    실제로 어긋납니다(FDR: 리츠를 STOCK ↔ 네이버: RT).

    다만 **보관은 해야 합니다.** 이 필드들이 없었으면 섀도 3회차에서
    코넥스(KONEX) 혼입을 발견하지 못했을 것입니다.
    """
    row = parse_market_list_row(market_list()[0], market_label="KOSPI")
    check(row.get("api_security_type") == "ST", "종목 유형이 참고용으로 보관됨")
    check("api_sosok" in row, "시장 구분(sosok)이 참고용으로 보관됨")
    src = (REPO_ROOT / "utils" / "naver_stock_api.py").read_text(encoding="utf-8")
    for banned in ('if _text(row.get("type")) != "ST"', 'sosok") != "0"', 'continue  # ETF'):
        check(banned not in src, f"파서가 종목을 거르지 않음: {banned}")


def test_forward_metrics_are_never_computed():
    """
    🔴 오너 지시 (2026-09-08): *"포워드 자료 같은 경우에는 애널리스트들이 정해주는 것이지
    우리가 계산해서 나오는 게 아니지 않아? 재무제표를 다 읽을 수는 없잖아."*

    추정 PER·추정 EPS·Forward ROE·목표주가는 **증권사 애널리스트의 미래 추정치**입니다.
    확정 재무제표를 아무리 잘 읽어도 나오지 않습니다. 계산으로 흉내내면 §0-1 이 금지하는
    **지어내기**이고, 받은 값과 만든 값이 같은 칸에서 섞입니다.

    → 이 파서는 Forward 계열을 **받은 그대로만** 씁니다. 못 받으면 못 받은 대로 둡니다.
    """
    d = detail()
    out = parse_stock_detail(d, source_url=KRX_DETAIL_URL)
    check(out["f_eps"] == float(d["estimatedEps"]), "추정 EPS 는 응답값 그대로")
    check(out["f_per"] == float(d["estimatedPer"]), "추정 PER 은 응답값 그대로")

    # 계산해서 넣었다면 이 값들과 같아졌을 것입니다 — 그렇지 않아야 합니다.
    check(abs(out["f_per"] - float(d["nowPrice"]) / float(d["estimatedEps"])) > 1e-6,
          "f_per 이 '현재가 ÷ 추정EPS' 계산값이 아님")

    # 추정치가 없는 응답이면 **지어내지 않고 None**
    blank = parse_stock_detail(dict(d, estimatedPer=None, estimatedEps=None),
                               source_url=KRX_DETAIL_URL)
    check(blank["f_per"] is None and blank["f_eps"] is None,
          "추정치가 없으면 계산으로 메우지 않고 None")

    src = (REPO_ROOT / "utils" / "naver_stock_api.py").read_text(encoding="utf-8")
    check("Forward 계열은 받는 값이지 만드는 값이 아닙니다" in src,
          "이 원칙이 모듈 머리말에 적혀 있음")


def test_negative_values_keep_their_sign():
    """2차 감사 1-1 — 적자 기업의 마이너스 부호를 절대 버리지 않습니다."""
    rows = {r["code"]: r for r in parse_market_list(market_list(),
                                                    source_url=KRX_LIST_URL, market_label="KOSPI")}
    lges = rows["373220"]  # LG에너지솔루션: eps -7193, roe -5.19
    check(lges["t_eps"] == -7193.0, "적자 종목 EPS 가 음수로 보존", f'({lges["t_eps"]})')
    check(lges["t_roe"] == -5.19, "적자 종목 ROE 가 음수로 보존", f'({lges["t_roe"]})')


def test_not_collected_and_no_dividend_are_never_merged():
    """
    2차 감사 1-4 / 재감사 H2·H3 — '수집 실패'와 '무배당'을 같은 값으로 뭉개지 않습니다.
    실측 근거: LG에너지솔루션 `dividend: null` / SK스퀘어 `dividend: "0"` + 수익률 null.
    """
    rows = {r["code"]: r for r in parse_market_list(market_list(),
                                                    source_url=KRX_LIST_URL, market_label="KOSPI")}
    check(rows["373220"]["dps"] is None and rows["373220"]["dps_status"] == "not_collected",
          "dividend 가 null 이면 not_collected (0 으로 만들지 않음)")
    check(rows["402340"]["dps"] == 0.0 and rows["402340"]["dps_status"] == "no_dividend_confirmed",
          "dividend 0 + 배당수익률 없음 → 무배당 확정 (근거 두 개)")
    check(rows["005930"]["dps"] == 1668.0 and rows["005930"]["dps_status"] == "collected",
          "배당이 있으면 collected")

    statuses = {r["dps_status"] for r in rows.values()}
    check(len(statuses) >= 3, "픽스처가 dps_status 세 갈래를 모두 밟음", f"({sorted(statuses)})")


def test_zero_dps_with_a_yield_is_a_conflict_not_a_confirmation():
    """
    근거가 서로 모순이면 **확정하지 않습니다**(H3 의 핵심). 0원인데 수익률이 나온다면
    둘 중 하나가 틀린 것이므로 '무배당 확정'으로 승격하지 않고 미수집으로 둡니다.
    """
    row = dict(market_list()[2])          # SK스퀘어 (dividend "0")
    row["dividendRate"] = "1.23"          # 모순 상황을 만듦
    out = parse_market_list_row(row, market_label="KOSPI")
    check(out["dps_status"] == "not_collected", "모순 시 무배당으로 확정하지 않음")
    check(any("모순" in e for e in out["errors"]), "모순 사실이 errors 에 기록됨")


# ─────────────────────────────────────────────────────────────────────────────
# 4. 구 파서와의 키 호환 · 없는 것은 없다고 말하기
# ─────────────────────────────────────────────────────────────────────────────

def test_detail_returns_the_same_keys_as_the_old_parser():
    """
    소비부를 한 줄도 안 고치고 출처만 갈아끼우려면 키 집합이 같아야 합니다.
    (재감사 H1 — 실패 경로와 정상 경로의 키가 달라 KeyError 가 났던 전례)
    """
    old_keys = {"t_per", "t_eps", "f_per", "f_eps", "div_yield", "dps", "outstanding_shares",
                "t_pbr", "ev_ebitda", "f_roe", "raw_period", "dps_status", "dps_inherited_from",
                "div_yield_row_found", "div_yield_row_explicit_na", "errors"}
    out = parse_stock_detail(detail(), source_url=KRX_DETAIL_URL)
    missing = old_keys - set(out)
    check(not missing, "구 파서의 키를 하나도 빠뜨리지 않음", f"(빠진 키: {missing})")


def test_missing_fields_are_reported_not_silently_blank():
    """
    §0-1 — 이 API 에 없는 f_roe·ev_ebitda 를 조용히 None 으로 두지 않고
    '어디서 따로 받아야 하는지'를 errors 에 남깁니다.
    """
    out = parse_stock_detail(detail(), source_url=KRX_DETAIL_URL)
    check(out["f_roe"] is None and out["ev_ebitda"] is None, "없는 값은 None")
    joined = " ".join(out["errors"])
    check("f_roe" in joined and "c1010001" in joined, "f_roe 미수집 사유와 대체 출처가 기록됨")
    check("ev_ebitda" in joined, "ev_ebitda 미수집 사유가 기록됨")


def test_one_broken_row_does_not_discard_the_others():
    """재감사 H1 — 구획 하나가 터졌다고 이미 읽은 값까지 버리지 않습니다."""
    payload = market_list()[:3]
    payload.insert(1, {"itemname": "깨진종목"})      # 코드·가격 없음
    rows = parse_market_list(payload, source_url=KRX_LIST_URL, market_label="KOSPI")
    check(len(rows) == 3, "깨진 항목만 건너뛰고 나머지는 살림", f"({len(rows)}건)")
    check(any("[1]" in e for e in rows[0]["errors"]), "건너뛴 항목이 errors 에 기록됨")


def test_module_does_not_touch_the_network():
    """이 모듈은 파싱만 합니다. requests 를 들이면 픽스처만으로 테스트할 수 없게 됩니다."""
    src = (REPO_ROOT / "utils" / "naver_stock_api.py").read_text(encoding="utf-8")
    for banned in ("import requests", "urllib.request", "http.client", "httpx"):
        check(banned not in src, f"네트워크 라이브러리 미사용: {banned}")


def test_consensus_parses_but_is_documented_as_unused():
    out = parse_consensus(_load("consensus_000660.json"))
    check(out["consensus_target_price"] == 3279565.0, "목표주가 파싱")
    check(out["opinion_score"] == 4.0, "투자의견 파싱")
    src = (REPO_ROOT / "utils" / "naver_stock_api.py").read_text(encoding="utf-8")
    check("현재 저장소는 이 API 를 쓰지 않습니다" in src,
          "컨센서스 API 를 쓰지 않는다는 사실이 코드에 명시돼 있음")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
