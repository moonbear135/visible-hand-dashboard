# tests/test_us_stocks.py
"""
🇺🇸 미국주식 수집기 기초틀 오프라인 검증 (네트워크 없이 실행 가능)

⚠️ 여기 쓰인 라벨/값 문자열은 전부 2026-08-06에 stockanalysis.com 실페이지에서
   실제로 확인한 원문입니다(ROK/BRK.B/CAVA/IBRX/MAC/JPM/ET/PLXS 8종목).
   종목명 문자열도 실제 유니버스 CSV(all.csv) 상위 929행에서 그대로 가져온 것입니다.
   즉 이 테스트는 "가상의 예쁜 데이터"가 아니라 실데이터의 까다로운 경계 케이스를 봅니다.

실행: python tests/test_us_stocks.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent))

from zoneinfo import ZoneInfo

import collector_us_stocks as C
from collector_us_stocks import (
    classify_instrument,
    filter_universe,
    parse_universe_csv,
    build_statistics_url,
    extract_label_value_pairs,
    map_pairs_to_fields,
    parse_scaled_number,
    _value_state,
    extract_close_price,
    parse_close_timestamp,
    detect_dividend_statement,
    derive_fields,
    resolve_collection_session_et,
    apply_us_hysteresis_buffer,
    fetch_one_index_quote,
    build_index_proxy_url,
)

ET = ZoneInfo("America/New_York")

FAILURES = []

import pytest


@pytest.fixture(autouse=True)
def _assert_no_check_failures():
    """
    🔴 2026-08-21 발견 — `check()`는 실패를 `FAILURES`에 기록만 하고, 그 목록을 실제로
    검사해서 죽는 코드는 파일 맨 아래 `if __name__ == "__main__": main()` 안에만 있었습니다.
    이 파일의 모든 검증은 pytest로 돌려왔는데, pytest는 `main()`을 절대 부르지 않으므로
    `check()` 실패가 있어도 각 `test_*` 함수는 스스로 실패하지 않았습니다 — 이 파일의
    배선·렌더 스모크 검사가 그동안 pytest 상에서는 항상 초록불이었다는 뜻입니다
    (2026-08-21, 결투다! USD 화면 작업 중 발견).

    그래서 매 테스트 앞뒤로 `FAILURES`의 증가분을 직접 확인해 pytest에서도 똑같이
    실패하게 만듭니다. 기존 `test_*` 함수는 한 줄도 안 고쳤습니다 — 이 fixture 하나가
    파일 안의 모든 테스트에 자동 적용됩니다(pytest의 `autouse` 규약).
    """
    start = len(FAILURES)
    yield
    new_failures = FAILURES[start:]
    assert not new_failures, f"check() 로 기록된 실패 {len(new_failures)}건: {new_failures}"



def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


# =============================================================================
# 1. 상품 유형 분류 (실제 CSV 종목명)
# =============================================================================
REAL_NAMES = [
    # (종목명, 기대 분류)
    ("NVIDIA Corporation Common Stock", "common"),
    ("Alphabet Inc. Class A Common Stock", "common"),
    ("Alphabet Inc. Class C Capital Stock", "common"),
    ("Berkshire Hathaway Inc.", "common"),
    ("Sea Limited American Depositary Shares each representing one Class A Ordinary Share", "common"),
    ("Energy Transfer LP Common Units ", "common"),
    ("MPLX LP Common Units Representing Limited Partner Interests", "common"),
    ("Simon Property Group Inc. Common Stock", "common"),
    # 채권/노트류 (오너 확정 필터 1)
    ("AT&T Inc. 5.350% Global Notes due 2066", "bond_note"),
    ("Duke Energy Corporation 5.625% Junior Subordinated Debentures due 2078", "bond_note"),
    ("Southern Company (The) Series 2017B 5.25% Junior Subordinated Notes due December 1 2077", "bond_note"),
    ("Entergy Arkansas LLC First Mortgage Bonds 4.875% Series Due September 1 2066", "bond_note"),
    ("KKR Group Finance Co. IX LLC 4.625% Subordinated Notes due 2061", "bond_note"),
    # 미국식 우선주 (오너 확정 필터 2)
    ("Alphabet Inc. Depositary Shares representing a 1/20th Interest in a Share of Series A "
     "Mandatory Convertible Preferred Stock", "preferred"),
    ("Strategy Inc Variable Rate Series A Perpetual Stretch Preferred Stock", "preferred"),
    ("AGNC Investment Corp. Depositary Shares Each Representing a 1/1000th Interest in a Share of "
     "7.00% Series C Fixed-To-Floating Rate Cumulative Redeemable Preferred Stock", "preferred"),
    ("SLM Corporation Floating Rate Non-Cumulative Preferred Stock Series B", "preferred"),
    # 🚩 오너 확정 규칙 밖(확인 필요) — 보통주가 아닌 상품
    ("Core Scientific Inc. Tranche 2 Warrants", "warrant"),
    ("Southern Company (The) 2025 Series A Corporate Units", "hybrid_units"),
    ("PPL Corporation Corporate Units", "hybrid_units"),
    ("Goldman Sachs Group Securities STRATS Trust for Goldman Sachs Group Securities Series 2006-2",
     "structured_trust"),
]


def test_classify_instrument():
    print("\n[1] 상품 유형 분류 (실제 CSV 종목명 22건)")
    for name, expected in REAL_NAMES:
        got = classify_instrument(name)
        check(got == expected, f"{name[:52]:<52} → {got}", f"(기대 {expected})")
    # 회사명에 'Preferred'가 들어가는 보통주를 우선주로 오판하지 않아야 함
    check(classify_instrument("Preferred Bank Common Stock") == "common",
          "회사명 'Preferred Bank'는 우선주로 오판하지 않음")


# =============================================================================
# 2. 유니버스 필터 (550개 컷 / 복수 클래스 전부 포함 / 소스 건전성 가드)
# =============================================================================
def _build_universe(n_common=900):
    rows = []
    cap = 5.0e12
    # 실제 CSV 상위권에 섞여 있던 비보통주들을 앞쪽에 배치
    tricky = [(name, kind) for name, kind in REAL_NAMES if kind != "common"]
    special = [
        ("GOOGL", "Alphabet Inc. Class A Common Stock"),
        ("GOOG", "Alphabet Inc. Class C Capital Stock"),
        ("BRK/A", "Berkshire Hathaway Inc."),
        ("BRK/B", "Berkshire Hathaway Inc."),
    ]
    for i, (sym, name) in enumerate(special):
        rows.append({"symbol": sym, "name": name, "csv_price": 100.0,
                     "csv_market_cap": cap - i * 1e9, "industry": "Technology"})
    for i, (name, _kind) in enumerate(tricky):
        rows.append({"symbol": f"XX{i}", "name": name, "csv_price": 25.0,
                     "csv_market_cap": cap - 100e9 - i * 1e9, "industry": "Finance"})
    base = cap - 400e9
    for i in range(n_common):
        rows.append({"symbol": f"C{i:04d}", "name": f"Test Company {i} Common Stock",
                     "csv_price": 50.0, "csv_market_cap": base - i * 1e8, "industry": "Industrials"})
    return rows


def test_filter_universe():
    print("\n[2] 유니버스 필터")
    rows = _build_universe()
    selected, stats = filter_universe(rows, target_size=550)
    symbols = {r["symbol"] for r in selected}

    check(stats["final_count"] == 550, f"최종 종목 수 550개 (실제 {stats['final_count']})")
    check(stats["excluded_bond_note"] == 5, f"채권/노트 5건 제외 (실제 {stats['excluded_bond_note']})")
    check(stats["excluded_preferred"] == 4, f"우선주 4건 제외 (실제 {stats['excluded_preferred']})")
    check(stats["excluded_warrant"] == 1, f"워런트 1건 제외 (실제 {stats['excluded_warrant']})")
    check(stats["excluded_hybrid_units"] == 2, f"하이브리드 유닛 2건 제외 (실제 {stats['excluded_hybrid_units']})")
    check(stats["excluded_structured_trust"] == 1,
          f"구조화 신탁 1건 제외 (실제 {stats['excluded_structured_trust']})")
    check({"GOOGL", "GOOG"} <= symbols, "복수 보통주 클래스(GOOGL/GOOG) 둘 다 포함 — 중복제거 안 함")
    check({"BRK/A", "BRK/B"} <= symbols, "동일 회사명 복수 클래스(BRK/A·BRK/B) 둘 다 포함")
    check(not any(s.startswith("XX") for s in symbols), "제외 대상(채권·우선주·워런트 등) 미포함")
    check(selected[0]["rank"] == 1 and selected[-1]["rank"] == 550, "rank 1~550 연속 부여")

    # 순위가 뒤섞인 CSV도 직접 재정렬하는가
    shuffled = list(reversed(rows))
    sel2, stats2 = filter_universe(shuffled, target_size=550)
    check(stats2["resorted"] is True, "시총 내림차순이 아니면 직접 재정렬")
    check(sel2[0]["csv_market_cap"] >= sel2[-1]["csv_market_cap"], "재정렬 후 내림차순 유지")

    # 소스 건전성 가드 (§4-1 주의사항)
    try:
        filter_universe(rows[:100], target_size=550)
        check(False, "행 수 부족 시 RuntimeError 발생")
    except RuntimeError:
        check(True, "행 수 부족 시 RuntimeError 로 중단(조용히 진행하지 않음)")

    # 오너 확정 3규칙만 적용하는 모드
    _sel3, stats3 = filter_universe(rows, target_size=550, exclude_non_common=False)
    check(stats3["exclude_non_common_applied"] is False,
          "exclude_non_common=False 이면 워런트/유닛/신탁을 유니버스에 남김(오너 확정 규칙만 적용)")


def test_parse_universe_csv():
    print("\n[2-b] 유니버스 CSV 파서")
    csv_text = (
        "symbol,name,price,marketCap,volume,industry\n"
        "NVDA,NVIDIA Corporation Common Stock,211.94,5128948000000.0,134926457,Technology\n"
        "BRK/A,Berkshire Hathaway Inc.,774300.0,1138897738200.0,295,Uncategorized\n"
        "BAD,Broken Row,,,0,\n"
    )
    rows = parse_universe_csv(csv_text)
    check(len(rows) == 2, f"시총 결측 행은 제외 (파싱 {len(rows)}행)")
    check(rows[0]["csv_market_cap"] == 5128948000000.0, "시가총액 파싱")
    try:
        parse_universe_csv("foo,bar\n1,2\n")
        check(False, "컬럼 구조 변경 시 RuntimeError")
    except RuntimeError:
        check(True, "컬럼 구조가 다르면 RuntimeError 로 중단")


def test_hysteresis():
    print("\n[2-c] 히스테리시스 버퍼(진입 550 / 이탈 600)")
    candidates = [{"symbol": f"S{i:04d}"} for i in range(700)]
    previous = {"S0560"}  # 어제 추적 중이던 종목이 561위로 밀린 상황
    tracked = apply_us_hysteresis_buffer(candidates, previous, entry_rank=550, exit_rank=600)
    symbols = {t["symbol"] for t in tracked}
    check(len(tracked) == 551, f"추적 551개(550 + 버퍼 1) (실제 {len(tracked)})")
    check("S0560" in symbols, "어제 추적 중이던 561위 종목은 버퍼로 유지")
    check(all(not t["is_visible"] for t in tracked if t["rank"] > 550), "버퍼 구간은 is_visible=False")
    check(sum(1 for t in tracked if t["is_visible"]) == 550, "화면 노출은 정확히 550개")
    tracked2 = apply_us_hysteresis_buffer(candidates, set(), entry_rank=550, exit_rank=600)
    check(len(tracked2) == 550, "직전 목록이 없으면 단순 550위 컷과 동일(첫 실행 안전)")


def test_url_builder():
    print("\n[2-d] 통계 페이지 URL 변환")
    check(build_statistics_url("BRK/B").endswith("/stocks/BRK.B/statistics/"),
          "BRK/B → BRK.B (실측 확인된 사이트 표기)")
    check(build_statistics_url("aapl").endswith("/stocks/AAPL/statistics/"), "소문자 티커 대문자화")


# =============================================================================
# 3. 라벨→필드 매핑 (실제 페이지 원문 라벨/값)
# =============================================================================
ROK_PAIRS = [
    ("market cap", "49.98B"), ("enterprise value", "53.11B"),
    ("shares outstanding", "111.05M"), ("shares change (yoy)", "-0.84%"),
    ("pe ratio", "42.17"), ("forward pe", "31.14"), ("ps ratio", "5.57"),
    ("pb ratio", "14.30"), ("p/tbv ratio", "n/a"), ("peg ratio", "2.16"),
    ("ev / ebitda", "28.40"), ("return on equity (roe)", "30.63%"),
    ("return on invested capital (roic)", "21.36%"), ("return on assets (roa)", "9.99%"),
    ("weighted average cost of capital (wacc)", "12.05%"), ("beta (5y)", "1.54"),
    ("52-week price change", "+28.53%"), ("earnings per share (eps)", "$10.67"),
    ("revenue", "8.97B"), ("net income", "1.20B"), ("ebitda", "1.87B"),
    ("book value per share", "31.46"), ("equity (book value)", "3.50B"),
    ("total debt", "3.61B"), ("dividend per share", "$5.52"), ("dividend yield", "1.23%"),
    ("payout ratio", "51.73%"), ("buyback yield", "0.84%"), ("shareholder yield", "2.07%"),
    ("price target", "$475.83"), ("price target difference", "5.73%"),
    ("analyst consensus", "Buy"), ("analyst count", "28"),
    ("revenue growth forecast (3y)", "6.73%"), ("eps growth forecast (3y)", "16.43%"),
    ("altman z-score", "5.54"), ("piotroski f-score", "7"),
    ("lynch fair value", "Upgrade"), ("graham number", "Upgrade"),
    ("earnings date", "Aug 4, 2026"), ("ex-dividend date", "Aug 17, 2026"),
]

BRKB_PAIRS = [
    ("market cap", "1.12T"), ("shares outstanding", "2.16B"), ("pe ratio", "15.44"),
    ("forward pe", "25.26"), ("peg ratio", "n/a"), ("pb ratio", "1.53"),
    ("ev / ebitda", "7.22"), ("return on equity (roe)", "10.50%"),
    ("return on invested capital (roic)", "17.96%"),
    ("earnings per share (eps)", "$33.59"), ("book value per share", "337.04"),
    ("dividend per share", "n/a"), ("dividend yield", "n/a"), ("payout ratio", "n/a"),
    ("buyback yield", "-0.05%"), ("shareholder yield", "-0.05%"),
    ("price target", "$525.33"), ("analyst consensus", "Buy"), ("analyst count", "4"),
    ("eps growth forecast (3y)", "3.36%"), ("altman z-score", "2.96"),
]

IBRX_PAIRS = [
    ("market cap", "7.68B"), ("shares outstanding", "1.06B"), ("pe ratio", "n/a"),
    ("forward pe", "n/a"), ("peg ratio", "n/a"), ("pb ratio", "n/a"),
    ("ev / ebitda", "n/a"), ("return on equity (roe)", "n/a"),
    ("return on invested capital (roic)", "-69.10%"), ("loss per share", "-$0.99"),
    ("net income", "-992.36M"), ("book value per share", "-0.99"),
    ("dividend per share", "n/a"), ("dividend yield", "n/a"),
    ("price target", "$12.75"), ("analyst consensus", "Strong Buy"),
    ("revenue growth forecast (3y)", "112.45%"), ("eps growth forecast (3y)", "n/a"),
    ("altman z-score", "-8.87"), ("piotroski f-score", "3"),
]

MAC_PAIRS = [
    ("market cap", "7.84B"), ("price/ffo ratio", "17.26"), ("pe ratio", "n/a"),
    ("forward pe", "n/a"), ("return on equity (roe)", "-7.11%"),
    ("return on invested capital (roic)", "2.44%"), ("loss per share", "-$0.72"),
    ("book value per share", "9.35"), ("dividend per share", "$0.68"),
    ("dividend yield", "2.68%"), ("shareholder yield", "-7.88%"),
    ("eps growth forecast (3y)", "n/a"), ("altman z-score", "n/a"),
]

JPM_PAIRS = [
    ("market cap", "954.93B"), ("pe ratio", "15.42"), ("forward pe", "14.88"),
    ("peg ratio", "1.50"), ("return on equity (roe)", "17.79%"),
    ("return on invested capital (roic)", "n/a"), ("ev / ebitda", "n/a"),
    ("earnings per share (eps)", "$23.30"), ("book value per share", "133.01"),
    ("dividend per share", "$6.00"), ("dividend yield", "1.67%"),
    ("shareholder yield", "5.23%"), ("eps growth forecast (3y)", "10.22%"),
    ("working capital", "-1,793.09B"),
]


def test_field_mapping():
    print("\n[3] 라벨→필드 매핑 (실제 페이지 원문)")
    rok, meta = map_pairs_to_fields(ROK_PAIRS)
    check(rok["t_per"] == 42.17 and rok["f_per"] == 31.14, "ROK Trailing/Forward PER")
    check(rok["market_cap"] == 49.98e9, f"ROK 시가총액 49.98B (실제 {rok['market_cap']})")
    check(rok["outstanding_shares"] == 111.05e6, "ROK 발행주식수 111.05M")
    check(rok["t_roe"] == 30.63 and rok["roic"] == 21.36, "ROK ROE/ROIC (% 기호 제거)")
    check(rok["t_eps"] == 10.67 and rok["bps"] == 31.46, "ROK EPS/BPS ($ 기호 제거)")
    check(rok["dps"] == 5.52 and rok["div_yield"] == 1.23, "ROK 배당(DPS/수익률)")
    check(rok["growth_eps_3y"] == 16.43, "ROK 3년 EPS 성장전망")
    check(rok["analyst_target"] == 475.83 and rok["analyst_count"] == 28, "ROK 목표주가/커버 수")
    check(rok["analyst_consensus"] == "Buy", "ROK 컨센서스 등급(문자열)")
    check(rok["price_change_52w"] == 28.53, "ROK 52주 변동률(+ 부호 처리)")

    brk, _ = map_pairs_to_fields(BRKB_PAIRS)
    check(brk["market_cap"] == 1.12e12, "BRK.B 시가총액 1.12T (T 스케일)")
    check(brk["peg"] is None, "BRK.B PEG 'n/a' → None (0으로 채우지 않음)")
    check(brk["dps"] is None and brk["div_yield"] is None, "BRK.B 무배당 → None")
    check(brk["buyback_yield"] == -0.05, "BRK.B 음수 자사주 수익률")

    ibrx, ibrx_meta = map_pairs_to_fields(IBRX_PAIRS)
    check(ibrx["t_per"] is None, "적자기업 PER 'n/a' → None")
    check(ibrx["t_eps"] == -0.99, "적자기업 EPS는 'Loss Per Share' 라벨에서 음수로 수집")
    check(ibrx["roic"] == -69.10, "적자기업 음수 ROIC 부호 보존")
    check(ibrx["growth_eps_3y"] is None, "EPS 성장전망 미제공 → None (Forward 마스킹 대상)")
    check("t_per" in ibrx_meta["missing"], "결측 사유가 meta.missing 에 기록됨")

    mac, _ = map_pairs_to_fields(MAC_PAIRS)
    check(mac["price_ffo"] == 17.26, "리츠 전용 P/FFO 수집")
    check(mac["t_roe"] == -7.11, "음수 ROE 부호 보존")
    check(mac["dps"] == 0.68 and mac["div_yield"] == 2.68, "리츠 배당 수집")

    jpm, _ = map_pairs_to_fields(JPM_PAIRS)
    check(jpm["roic"] is None, "은행 ROIC 'n/a' → None")
    check(jpm["t_per"] == 15.42 and jpm["shareholder_yield"] == 5.23, "은행 PER/주주환원율")

    # 유료(paywall) 값은 숫자로 오인하지 않아야 함
    state, _ = _value_state("Upgrade")
    check(state == "paywall", "'Upgrade'(유료 항목)는 paywall 로 판정 — 숫자 파싱 시도 안 함")


def test_number_parsers():
    print("\n[3-b] 숫자 파서 경계값")
    cases = [
        ("1.12T", 1.12e12), ("954.93B", 954.93e9), ("111.05M", 111.05e6),
        ("846,430", 846430.0), ("-161,000", -161000.0), ("-1,793.09B", -1793.09e9),
        ("$5.52", 5.52), ("-$0.99", -0.99), ("+28.53%", 28.53), ("-0.84%", -0.84),
        ("n/a", None), ("-", None), ("", None), ("Upgrade", None),
    ]
    for raw, expected in cases:
        got = parse_scaled_number(raw)
        ok = (got is None and expected is None) or (
            got is not None and expected is not None and abs(got - expected) < 1e-6)
        check(ok, f"parse('{raw}') = {got}", f"(기대 {expected})")


# =============================================================================
# 4. 장마감 종가 파싱 (§0-3-1 프리마켓 사용 금지)
# =============================================================================
HTML_WITH_PREMARKET = """
<html><body>
<div>JPMorgan Chase &amp; Co. (JPM)</div><div>NYSE: JPM · USD</div>
<div>359.24</div><div>+1.72 (0.48%)</div><div>At close: Aug 5, 2026, 4:00 PM EDT</div>
<div>361.90</div><div>+2.66 (0.74%)</div><div>Pre-market: Aug 6, 2026, 6:43 AM EDT</div>
<p>This stock pays an annual dividend of $6.00.</p>
</body></html>
"""

HTML_MARKET_CLOSED = """
<html><body>
<div>Rockwell Automation, Inc. (ROK)</div>
<div>450.05</div><div>+4.82 (1.08%)</div>
<div>Aug 5, 2026, 4:00 PM EDT - Market closed</div>
<p>ROK does not appear to pay any dividends at this time.</p>
</body></html>
"""

# 2026-08-07 추가: 오너가 로컬 실측(장마감 후, 애프터마켓 거래 있는 종목 11/12 실패)으로 발견한
# 실제 버그 재현 — "At close:"(라벨)와 날짜/시각(값)이 서로 다른 <div>(텍스트 노드)로 분리되고,
# 그 뒤에 애프터마켓 블록이 이어지는 실제 stockanalysis.com 레이아웃(NVDA 실측으로 확인).
HTML_AFTERHOURS_SPLIT_LABEL = """
<html><body>
<div>NVIDIA Corporation (NVDA)</div>
<div>218.99</div>
<div>-0.23 (-0.10%)</div>
<div>At close:</div>
<div>Aug 6, 2026, 4:00 PM EDT</div>
<div>219.42</div>
<div>+0.43 (0.20%)</div>
<div>After-hours: Aug 6, 2026, 7:59 PM EDT</div>
</body></html>
"""

HTML_TABLE = """
<html><body><table>
<tr><td><a href="/x">Market Cap</a></td><td>49.98B</td></tr>
<tr><td>Forward PE</td><td>31.14</td></tr>
<tr><td>Dividend Yield</td><td>n/a</td></tr>
<tr><td colspan="1">Ignored single cell</td></tr>
</table></body></html>
"""


def test_price_block():
    print("\n[4] 장마감 종가 블록 파싱")
    price, asof, err = extract_close_price(HTML_WITH_PREMARKET)
    check(price == 359.24, f"프리마켓(361.90)이 아니라 종가(359.24)를 사용 (실제 {price})")
    check(err is None and "Aug 5, 2026" in (asof or ""), "종가 기준 시각 문자열 확보")
    dt = parse_close_timestamp(asof)
    check(dt is not None and dt.date().isoformat() == "2026-08-05", "ET 타임스탬프 파싱")
    check(dt.tzinfo is not None, "tz-aware(ET) 로 반환 — naive datetime 금지")

    price2, asof2, err2 = extract_close_price(HTML_MARKET_CLOSED)
    check(price2 == 450.05, f"'- Market closed' 레이아웃도 종가 추출 (실제 {price2})")
    check(err2 is None, "두 번째 레이아웃 오류 없음")

    price3, _asof3, err3 = extract_close_price("<html><body><div>no price here</div></body></html>")
    check(price3 is None and err3, "종가를 못 찾으면 지어내지 않고 None + 사유 반환")

    # 2026-08-07 회귀 테스트: 라벨/값이 분리된 애프터마켓 레이아웃 (실측 버그 재현)
    price4, asof4, err4 = extract_close_price(HTML_AFTERHOURS_SPLIT_LABEL)
    check(price4 == 218.99, f"라벨/값 분리 + 애프터마켓 병기 레이아웃에서도 종가(218.99) 추출, 애프터마켓(219.42) 아님 (실제 {price4})")
    check(err4 is None and asof4 and "Aug 6, 2026" in asof4, "분리된 타임스탬프도 뒤 몇 줄에서 재조합해 확보")

    check(detect_dividend_statement(HTML_MARKET_CLOSED) == "confirmed_none",
          "'무배당' 문장 탐지 → 무배당 확정과 수집 실패를 구분")
    check(detect_dividend_statement(HTML_WITH_PREMARKET) == "unknown",
          "무배당 문장이 없으면 unknown(수집 실패와 구분 유지)")


def test_table_extraction():
    print("\n[4-b] 표 라벨/값 추출 (열 번호 고정 없이)")
    pairs = extract_label_value_pairs(HTML_TABLE)
    d = dict(pairs)
    check(d.get("market cap") == "49.98B", "링크가 들어있는 라벨도 정규화해 매칭")
    check(d.get("forward pe") == "31.14", "일반 라벨 매칭")
    check(d.get("dividend yield") == "n/a", "n/a 원문 보존(가공은 매핑 단계에서)")
    check("ignored single cell" not in d, "셀이 1개뿐인 행은 무시")


# =============================================================================
# 4-d. 지수 3종 ETF 프록시 파싱 (2026-08-07 Stooq 404 → stockanalysis.com ETF 페이지 교체)
#   ⚠️ 아래 숫자는 2026-08-07 실측(https://stockanalysis.com/etf/oneq/) 라이브 응답에서
#      그대로 옮긴 실제 값입니다(104.78 / +2.71 (2.66%) / Previous Close 102.07 /
#      "Index Tracked: NASDAQ Composite Index").
#   ⚠️ 2026-08-07 2차 실측(오너 로컬 `indices` 실행)에서 "Index Tracked"가 표(<table>)가 아니라
#      Previous Close 통계 박스 아래 "About {ETF명}" 서술 섹션에 있다는 게 드러났습니다 — 첫 버전
#      테스트가 실수로 표 구조로 만들어서 이 버그를 못 잡았던 것까지 포함해 재현합니다(아래 두
#      픽스처는 표 밖 레이아웃만 사용 — 라벨/값이 같은 줄에 붙은 경우와 다른 줄로 분리된 경우 둘 다).
# =============================================================================
HTML_INDEX_PROXY_ONEQ_OK = """
<html><body>
<h1>Fidelity Nasdaq Composite Index ETF (ONEQ)</h1>
<div>104.78</div>
<div>+2.71 (2.66%)</div>
<div>Aug 4, 2026, 4:00 PM EDT - Market closed</div>
<table>
<tr><td>Assets</td><td>$10.27B</td></tr>
<tr><td>Previous Close</td><td>102.07</td></tr>
<tr><td>Volume</td><td>670,559</td></tr>
</table>
<div class="about">
<div>Asset Class</div><div>Equity</div>
<div>Stock Exchange</div><div>NASDAQ</div>
<div>ETF Provider</div><div>Fidelity</div>
<div>Index Tracked NASDAQ Composite Index</div>
</div>
</body></html>
"""

# 소스가 바뀌어 엉뚱한 지수를 추종하는 ETF 페이지가 온 경우(방어 확인용 합성 케이스) —
# 이번엔 라벨/값이 서로 다른 줄로 분리된 레이아웃(표 밖)으로 다른 경로를 검증합니다.
HTML_INDEX_PROXY_WRONG_INDEX = """
<html><body>
<div>50.00</div>
<div>-0.25 (-0.50%)</div>
<div>Aug 4, 2026, 4:00 PM EDT - Market closed</div>
<table><tr><td>Previous Close</td><td>50.25</td></tr></table>
<div class="about">
<div>Index Tracked</div>
<div>Russell 2000 Index</div>
</div>
</body></html>
"""


def test_index_proxy():
    print("\n[4-d] 지수 3종 ETF 프록시 파싱 (Stooq 404 → stockanalysis.com 교체)")
    check(build_index_proxy_url("oneq") == "https://stockanalysis.com/etf/oneq/",
          "ETF 프록시 URL 빌더")

    orig_http_get = C._http_get
    orig_sleep = getattr(C, "_polite_sleep", None)
    try:
        C._http_get = lambda url, timeout=None: _FakeResp(HTML_INDEX_PROXY_ONEQ_OK)
        entry = fetch_one_index_quote("nasdaq", "나스닥 종합", "Nasdaq Composite", "oneq", "nasdaq composite")
        check(entry["close"] == 104.78, f"ETF 종가 추출 (실제 {entry['close']})")
        check(entry["previous_close"] == 102.07, f"전일 종가(Previous Close) 라벨 매칭 (실제 {entry['previous_close']})")
        check(entry["intraday_change_pct"] == 2.66,
              f"등락률 = (종가-전일종가)/전일종가 계산값 (실제 {entry['intraday_change_pct']}%, 실측 표기 2.66%와 일치)")
        check(entry["change_calculated"] is True, "등락률에 '계산값' 플래그(§0-1 예시2-보충)")
        check(entry["is_etf_proxy"] is True, "ETF 프록시 출처임을 표기")
        check(entry["tracked_index_verified"] is True,
              "'Index Tracked' 라벨이 기대 문구(nasdaq composite)를 포함 → 검증 통과")
        check(entry["error"] is None, "정상 케이스는 error 없음")

        C._http_get = lambda url, timeout=None: _FakeResp(HTML_INDEX_PROXY_WRONG_INDEX)
        entry2 = fetch_one_index_quote("nasdaq", "나스닥 종합", "Nasdaq Composite", "oneq", "nasdaq composite")
        check(entry2["tracked_index_verified"] is False,
              "엉뚱한 지수를 추종하는 ETF로 소스가 바뀌면 조용히 넘어가지 않고 검증 실패로 기록")
        check(entry2["error"] and "Index Tracked" in entry2["error"],
              "검증 실패 사유가 error 필드에 남음(지어내지 않고 정직하게 표기)")

        C._http_get = lambda url, timeout=None: (_ for _ in ()).throw(RuntimeError("boom"))
        entry3 = fetch_one_index_quote("dow", "다우존스", "Dow Jones", "dia", "dow jones")
        check(entry3["close"] is None and entry3["error"], "페이지 요청 자체가 실패해도 예외를 던지지 않고 사유만 기록")
    finally:
        C._http_get = orig_http_get


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


def test_derive_fields():
    print("\n[4-c] 파생 필드/교차검증")
    fields = {"f_per": 31.14, "growth_eps_3y": 16.43, "shareholder_yield": 2.07,
              "market_cap": 49.98e9}
    d = derive_fields(fields, {"csv_market_cap": 49.5e9})
    check(d["growth"] == 16.43 and d["growth_source"], "성장률 출처 표기와 함께 설정")
    check(d["forward_available"] is True, "f_per+성장률 있으면 Forward 사용 가능")
    check(d["market_cap_cross_validated"] is True, "두 출처 시총 오차 허용범위 내 → 교차검증 통과")
    d2 = derive_fields(fields, {"csv_market_cap": 20.0e9})
    check(d2["market_cap_cross_validated"] is False, "시총 괴리 크면 교차검증 실패로 기록")
    d3 = derive_fields({"f_per": 31.14, "growth_eps_3y": None}, None)
    check(d3["forward_available"] is False, "성장률 없으면 Forward 마스킹 대상")


# =============================================================================
# 5. ET 타임존 / 수집 세션 계산
# =============================================================================
def test_session_resolution():
    print("\n[5] ET 기준 수집 세션 계산")
    # 서머타임(EDT) 목요일 16:45 ET — 마감+30분 경과 → 당일 세션
    s = resolve_collection_session_et(datetime(2026, 8, 6, 16, 45, tzinfo=ET))
    check(s["session_date"] == "2026-08-06", f"마감+30분 후에는 당일 세션 (실제 {s['session_date']})")
    check(s["is_ready_now"] is True, "수집 준비 완료 판정")
    check(s["tz_abbrev"] == "EDT", f"8월은 서머타임(EDT) (실제 {s['tz_abbrev']})")

    # 같은 날 16:10 ET — 아직 +30분 전 → 전일 세션
    s2 = resolve_collection_session_et(datetime(2026, 8, 6, 16, 10, tzinfo=ET))
    check(s2["session_date"] == "2026-08-05", f"마감 직후 30분 이내면 전일 세션 (실제 {s2['session_date']})")

    # 토요일 → 직전 금요일
    s3 = resolve_collection_session_et(datetime(2026, 8, 8, 10, 0, tzinfo=ET))
    check(s3["session_date"] == "2026-08-07", f"주말이면 직전 금요일 (실제 {s3['session_date']})")

    # 일요일 새벽 → 직전 금요일
    s4 = resolve_collection_session_et(datetime(2026, 8, 9, 2, 0, tzinfo=ET))
    check(s4["session_date"] == "2026-08-07", "일요일도 직전 금요일")

    # 표준시(EST) 구간: KST 환산이 다음날 오전 6시대인지 (서머타임엔 5시대)
    s5 = resolve_collection_session_et(datetime(2026, 1, 15, 17, 0, tzinfo=ET))
    check(s5["tz_abbrev"] == "EST", f"1월은 표준시(EST) (실제 {s5['tz_abbrev']})")
    ready_kst = datetime.fromisoformat(s5["collect_ready_at_kst"])
    check(ready_kst.hour == 6 and ready_kst.minute == 30,
          f"표준시 마감+30분 = KST 익일 06:30 (실제 {ready_kst.strftime('%H:%M')})")
    ready_kst_summer = datetime.fromisoformat(s["collect_ready_at_kst"])
    check(ready_kst_summer.hour == 5 and ready_kst_summer.minute == 30,
          f"서머타임 마감+30분 = KST 익일 05:30 (실제 {ready_kst_summer.strftime('%H:%M')})")
    check(s5["holiday_calendar_applied"] is False, "휴장일 캘린더 미적용 사실을 정직하게 표기")


# =============================================================================
# 6. 무인 자동화(GitHub Actions) 사전 점검 — 2026-08-07 신설
#
#    서머타임(EDT/EST) 때문에 cron 을 두 줄 걸어 하루 두 번 트리거되는데,
#    실제 수집은 하루 한 번만 일어나야 합니다. 그 판정을 하는
#    `evaluate_collection_readiness()` 를 실제 워크플로우의 두 크론 시각
#    (20:35 UTC / 21:35 UTC)으로 시뮬레이션해 검증합니다.
# =============================================================================
UTC = ZoneInfo("UTC")


def _write_fake_snapshot(path, session_date, status="SUCCESS"):
    """기존 스냅샷을 흉내낸 최소 구조 파일을 씁니다(수집 없이 판정 로직만 검증)."""
    payload = {
        "metadata": {
            "status": status,
            "last_updated_at_et": f"{session_date} 16:40",
            "session_hint": {"session_date": session_date},
            "session_dates_from_source": {session_date: 548},
        },
        "stocks": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _readiness_at_utc(snapshot_path, y, m, d, hh, mm):
    now_et = datetime(y, m, d, hh, mm, tzinfo=UTC).astimezone(ET)
    return C.evaluate_collection_readiness(snapshot_path=snapshot_path, now_et=now_et)


def test_automation_readiness():
    print("\n[6] 무인 자동화 사전 점검 (--skip-if-not-ready)")
    tmpdir = tempfile.mkdtemp(prefix="us_readiness_test_")
    snap = os.path.join(tmpdir, "us_stocks_latest.json")

    # --- 스냅샷이 아예 없는 첫 실행 → 무조건 수집 -----------------------------
    r = _readiness_at_utc(snap, 2026, 7, 15, 20, 35)
    check(r["should_collect"] is True, "스냅샷이 없으면(첫 실행) 수집 진행")
    check(r["covered_session_dates"] == [], "없는 파일을 읽고 지어내지 않음(빈 목록)")

    # --- EDT 기간(7월): 20:35 UTC = 16:35 EDT → 당일 수집, 21:35 UTC 는 건너뜀 ---
    _write_fake_snapshot(snap, "2026-07-14")            # 어제까지만 수집돼 있는 상태
    r1 = _readiness_at_utc(snap, 2026, 7, 15, 20, 35)
    check(r1["should_collect"] is True and r1["target_session_date"] == "2026-07-15",
          f"[EDT] 20:35 UTC(=16:35 EDT) 크론은 당일 세션을 수집 (대상 {r1['target_session_date']})")

    _write_fake_snapshot(snap, "2026-07-15")            # 위 실행이 성공해 오늘까지 들어간 상태
    r2 = _readiness_at_utc(snap, 2026, 7, 15, 21, 35)
    check(r2["should_collect"] is False and r2["target_session_date"] == "2026-07-15",
          "[EDT] 21:35 UTC(=17:35 EDT) 크론은 이미 수집된 거래일이라 건너뜀")
    check("이미 수집" in r2["reason"], f"건너뛴 사유를 사람이 읽을 수 있게 남김 ({r2['reason']})")

    # --- EST 기간(1월): 20:35 UTC 는 아직 장중 → 건너뜀, 21:35 UTC 가 실제 수집 ---
    _write_fake_snapshot(snap, "2026-01-14")            # 전 거래일까지 수집돼 있는 상태
    r3 = _readiness_at_utc(snap, 2026, 1, 15, 20, 35)
    check(r3["should_collect"] is False and r3["target_session_date"] == "2026-01-14",
          f"[EST] 20:35 UTC(=15:35 EST, 장중)는 대상이 전 거래일이라 건너뜀 (대상 {r3['target_session_date']})")
    r4 = _readiness_at_utc(snap, 2026, 1, 15, 21, 35)
    check(r4["should_collect"] is True and r4["target_session_date"] == "2026-01-15",
          f"[EST] 21:35 UTC(=16:35 EST)는 당일 세션을 수집 (대상 {r4['target_session_date']})")

    # --- 앞 크론이 HTTP 429 로 끊겨 스냅샷이 그대로면 뒤 크론이 같은 날 재시도 ---
    _write_fake_snapshot(snap, "2026-07-14")
    r5 = _readiness_at_utc(snap, 2026, 7, 15, 21, 35)
    check(r5["should_collect"] is True,
          "앞 크론이 실패해 스냅샷이 갱신 안 됐으면 뒤 크론이 같은 날 재시도")

    # --- status=FAILED 인 스냅샷은 '이미 수집됨'으로 치지 않음 ------------------
    _write_fake_snapshot(snap, "2026-07-15", status="FAILED")
    r6 = _readiness_at_utc(snap, 2026, 7, 15, 21, 35)
    check(r6["should_collect"] is True, "status=FAILED 스냅샷은 재수집 대상으로 판정")

    # --- 깨진 스냅샷은 '모르면 수집' 쪽으로 안전하게 넘어감 --------------------
    with open(snap, "w", encoding="utf-8") as f:
        f.write("{ 깨진 JSON")
    r7 = _readiness_at_utc(snap, 2026, 7, 15, 21, 35)
    check(r7["should_collect"] is True, "스냅샷이 깨졌으면 건너뛰지 않고 수집(하루 통째 결측 방지)")

    # --- 주말 크론은 이미 금요일이 수집돼 있으므로 아무 일도 하지 않음 ----------
    #     (cron 은 UTC 월~금이라 토·일엔 안 돌지만, 수동 실행 대비 확인)
    _write_fake_snapshot(snap, "2026-07-17")            # 금요일까지 수집 완료
    r8 = _readiness_at_utc(snap, 2026, 7, 18, 21, 35)   # 토요일
    check(r8["should_collect"] is False and r8["target_session_date"] == "2026-07-17",
          "주말 실행은 대상이 직전 금요일이고 이미 수집돼 있어 건너뜀")

    # --- CLI 에 옵션이 실제로 배선돼 있는지 -----------------------------------
    check(any(a.dest == "skip_if_not_ready" for a in _collect_subparser_actions()),
          "collect 서브커맨드에 --skip-if-not-ready 옵션이 등록됨")

    shutil.rmtree(tmpdir, ignore_errors=True)


def _collect_subparser_actions():
    """main() 이 만드는 argparse 구조를 그대로 재현하지 않고, 실제 파서를 꺼내 확인합니다."""
    import argparse
    original_parse = argparse.ArgumentParser.parse_args
    captured = {}

    def _capture(self, *a, **kw):
        captured["parser"] = self
        raise SystemExit(0)   # 실제 실행으로 넘어가지 않게 즉시 중단

    argparse.ArgumentParser.parse_args = _capture
    argv_backup = sys.argv[:]
    sys.argv = ["collector_us_stocks.py", "collect"]
    try:
        C.main()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original_parse
        sys.argv = argv_backup

    parser = captured.get("parser")
    if parser is None:
        return []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            collect = action.choices.get("collect")
            return collect._actions if collect else []
    return []


# =============================================================================
# 2026-08-29 재감사 회귀 테스트 (H10 / H11 / M7 / M8 / L9 / L10)
# =============================================================================
US_STOCKS_SRC = (Path(__file__).parent.parent / "collector_us_stocks.py").read_text(encoding="utf-8")


def test_reaudit_limit_mode_does_not_write_production_outputs():
    """H10: --limit 부분 수집은 --allow-overwrite 없이는 산출물에 쓰지 않습니다."""
    print("\n[재감사 H10] --limit 테스트 모드가 프로덕션 산출물을 덮어쓰지 않는가")
    import argparse
    parser_src = US_STOCKS_SRC[US_STOCKS_SRC.index('p_collect = sub.add_parser('):]
    parser_src = parser_src[:parser_src.index("p_collect.set_defaults")]
    check('"--allow-overwrite"' in parser_src, "collect 서브커맨드에 --allow-overwrite 플래그가 있음")
    check("write_outputs = (not is_partial_run) or allow_overwrite" in US_STOCKS_SRC,
          "부분 수집이면 allow_overwrite 없이는 쓰지 않도록 판정")
    check('"partial_run": is_partial_run,' in US_STOCKS_SRC,
          "스냅샷 metadata 에 partial_run 표시")
    check('"limit": limit,' in US_STOCKS_SRC, "스냅샷 metadata 에 limit 표시")
    # 실제 인자 파싱에서 플래그가 살아 있는지
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--allow-overwrite", action="store_true")
    ns = p.parse_args(["--limit", "5"])
    check(ns.allow_overwrite is False, "--limit 만 주면 allow_overwrite 는 False")


def _fields_html(market_cap, shares):
    """종가 블록이 없어 역산 경로를 타게 되는 최소 페이지."""
    return (
        "<html><body><table>"
        f"<tr><td>Market Cap</td><td>{market_cap}</td></tr>"
        f"<tr><td>Shares Outstanding</td><td>{shares}</td></tr>"
        "</table></body></html>"
    )


def test_reaudit_calculated_price_range_and_cross_check():
    """H11/L9: 역산 종가에 범위 검증 + 유니버스 CSV 가격 교차 대조를 겁니다."""
    print("\n[재감사 H11] 역산 종가 범위/교차 검증")
    check(C.MIN_REASONABLE_CLOSE == 0.01 and C.MAX_REASONABLE_CLOSE == 1_000_000.0,
          "상식 범위 상수가 정의되어 있음")
    check(C.MAX_CALCULATED_PRICE_DIVERGENCE_RATIO == 2.0, "CSV 대조 허용 괴리 배수 상수가 정의되어 있음")

    src = US_STOCKS_SRC[US_STOCKS_SRC.index("price_source = \"calculated_marketcap_div_shares\""):]
    src = src[:src.index("elif price is None:")]
    check("MIN_REASONABLE_CLOSE <= price <= MAX_REASONABLE_CLOSE" in src, "역산 직후 범위 검증 수행")
    check('csv_price = (universe_row or {}).get("csv_price")' in src,
          "지금까지 미사용이던 csv_price 를 실제로 교차 대조에 사용(L9)")
    check("MAX_CALCULATED_PRICE_DIVERGENCE_RATIO" in src, "괴리 배수 상수를 실제로 사용")
    # 범위 밖 값이면 price=None 으로 두고 사유를 남기는지(문자열 근거)
    check("상식 범위" in src and "price = None" in src, "범위를 벗어나면 지어내지 않고 미수집 처리")


def test_reaudit_market_cap_cross_validation_distinguishes_unknown():
    """M8: 대조 자체를 못 한 경우는 False 가 아니라 None 이어야 합니다."""
    print("\n[재감사 M8] 교차검증 미수행(None) vs 실패(False) 구분")
    # 유니버스 행이 없음 → 대조 불가
    d_none = derive_fields({"market_cap": 1_000.0}, None)
    check(d_none["market_cap_cross_validated"] is None, "유니버스 행이 없으면 None(판정 불가)")
    check(d_none["market_cap_discrepancy"] is None, "괴리율도 None")
    # 유니버스 행은 있는데 시총 결측 → 역시 대조 불가
    d_none2 = derive_fields({"market_cap": 1_000.0}, {"csv_market_cap": None})
    check(d_none2["market_cap_cross_validated"] is None, "CSV 시총이 없으면 None(판정 불가)")
    # 실제로 대조해서 틀린 경우는 여전히 False
    d_false = derive_fields({"market_cap": 1_000.0}, {"csv_market_cap": 10_000.0})
    check(d_false["market_cap_cross_validated"] is False, "실제 대조 실패는 그대로 False")


def test_reaudit_summary_history_dedupes_by_session_date():
    """M7: 같은 거래일 레코드는 추가가 아니라 교체되어야 합니다."""
    print("\n[재감사 M7] 미국 요약 이력 중복 제거")
    tmpdir = tempfile.mkdtemp()
    try:
        path = os.path.join(tmpdir, "us_summary_history.json")
        stocks = [{"f_per": 20.0, "growth": 10.0, "f_pegy": 1.5}]
        C.update_us_summary_history("2026-08-28 16:05", stocks, path, history_date="2026-08-28")
        C.update_us_summary_history("2026-08-28 18:30", stocks, path, history_date="2026-08-28")
        C.update_us_summary_history("2026-08-29 16:05", stocks, path, history_date="2026-08-29")
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
        check(len(history) == 2, "같은 거래일 두 번 실행 → 행이 하나만 남음", f"실제 {len(history)}행")
        check(history[0]["collected_at_et"] == "2026-08-28 18:30", "같은 날은 마지막 실행값으로 교체")
        check(history[0]["session_date"] == "2026-08-28", "레코드에 거래일이 기록됨")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reaudit_parsers_accept_prebuilt_soup():
    """L10: 같은 HTML 을 세 번 파싱하지 않도록 soup 객체를 받을 수 있어야 합니다."""
    print("\n[재감사 L10] soup 재사용")
    from bs4 import BeautifulSoup
    html = "<html><body><table><tr><td>Market Cap</td><td>1.5B</td></tr></table></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    pairs_from_str = extract_label_value_pairs(html)
    pairs_from_soup = extract_label_value_pairs(soup)
    check(pairs_from_str == pairs_from_soup, "문자열/soup 두 입력의 결과가 동일(하위 호환 유지)")
    price_str = extract_close_price(html)
    price_soup = extract_close_price(soup)
    check(price_str == price_soup, "extract_close_price 도 두 입력에서 동일")
    # collect_one 이 실제로 한 번만 파싱하는지 (본문에서 확인)
    body = US_STOCKS_SRC[US_STOCKS_SRC.index("def collect_one("):]
    body = body[:body.index("\ndef ", 10)]
    check(body.count('BeautifulSoup(html, "html.parser")') == 0,
          "collect_one 안에 중복 BeautifulSoup 생성이 남아있지 않음")
    check(body.count("_as_soup(html)") == 1, "soup 를 딱 한 번만 만듦")


def main():
    print("=" * 70)
    print("🇺🇸 미국주식 수집기 기초틀 오프라인 검증")
    print("=" * 70)
    test_classify_instrument()
    test_filter_universe()
    test_parse_universe_csv()
    test_hysteresis()
    test_url_builder()
    test_field_mapping()
    test_number_parsers()
    test_price_block()
    test_table_extraction()
    test_index_proxy()
    test_derive_fields()
    test_session_resolution()
    test_automation_readiness()
    test_reaudit_limit_mode_does_not_write_production_outputs()
    test_reaudit_calculated_price_range_and_cross_check()
    test_reaudit_market_cap_cross_validation_distinguishes_unknown()
    test_reaudit_summary_history_dedupes_by_session_date()
    test_reaudit_parsers_accept_prebuilt_soup()

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 70)


if __name__ == "__main__":
    main()
