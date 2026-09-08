# tests/test_wisereport_parser.py
"""🔒 `utils/wisereport_parser.py` — WiseReport 재무요약 파서 테스트 (2026-09-07, #214)

⚠️ 이 파서가 왜 생겼는가

`collector_kospi200.py::_fetch_ev_ebitda()` 는 EV/EBITDA **하나**를 뽑으려고 종목마다
`navercomp.wisereport.co.kr/v2/company/c1010001.aspx` 를 이미 매일 호출합니다.
2026-09-07 조사에서 **같은 응답 안에 ROE·Forward ROE·순이익·자본총계까지 있음**이
확인됐습니다(§1-5-6). 요청을 늘리지 않고 값을 더 얻을 수 있습니다.

📌 픽스처는 **진짜 페이지**입니다
   `tests/fixtures/naver_new_api/wisereport_c1010001_000660.html` 은 2026-09-07 오너가
   브라우저에서 직접 저장한 실제 응답입니다(합성 아님). 세션은 웹 접근이 차단돼 있어
   받아올 수 없었고, §0-3-2 상 다시 긁지도 않습니다.
   · 보증함 — 파서가 표를 옳게 읽는지
   · 못 함  — 위레포트가 **앞으로 구조를 바꿨을 때**. 그건 `data_sanity` 와 실운영 로그 몫입니다.

🔴 이 파일이 지키는 핵심은 **"연간과 분기를 절대 섞지 않는다"** 입니다.
   같은 표에 연간 4열과 분기 4열이 나란히 있고, **분기 ROE 는 직전 4개 분기를 연환산한 값**
   이라고 페이지가 스스로 밝힙니다. 현행 `t_roe` 는 연간 확정치라 기준이 다릅니다.
   실측: SK하이닉스 연간 2025/12 = **44.15** vs 분기 2026/06 = **92.68**.

실행: python -m pytest tests/test_wisereport_parser.py -v
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from conftest import FAILURES, check  # noqa: E402,F401

from utils.wisereport_parser import (  # noqa: E402
    ANNUAL_ACTUAL_KINDS,
    ANNUAL_ESTIMATE_KINDS,
    parse_financial_summary,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "naver_new_api" / "wisereport_c1010001_000660.html"


def _html():
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


def test_fixture_exists():
    """스캐너가 조용히 빈손이 되지 않게 (§0-1)."""
    assert FIXTURE.is_file(), f"실제 HTML 픽스처가 없습니다: {FIXTURE}"
    assert len(_html()) > 100_000, "픽스처가 너무 작습니다 — 저장이 잘렸을 수 있습니다."


def test_values_match_what_production_currently_collects():
    """
    🔴 이 파일의 존재 이유. **현행 수집기가 실제로 내놓는 값과 같아야** 갈아끼울 수 있습니다.
    아래 세 값은 2026-09-07 `data/kospi200_pegy_latest.json` 의 000660 실측값입니다.
    """
    r = parse_financial_summary(_html())
    check(r["t_roe"] == 44.15, "t_roe 가 현행 수집값과 일치", f'(실제 {r["t_roe"]})')
    check(r["f_roe"] == 101.67, "f_roe 가 현행 수집값과 일치", f'(실제 {r["f_roe"]})')
    check(r["ev_ebitda"] == "19.51",
          "ev_ebitda 가 현행 수집값과 일치 (문자열 표기까지)", f'(실제 {r["ev_ebitda"]!r})')
    check(not r["errors"], "정상 페이지에서는 오류가 없음", f'({r["errors"]})')


def test_quarterly_columns_are_never_used():
    """
    🔴 분기 ROE(연환산)를 연간 확정치 자리에 넣으면 조용히 틀립니다.
    분기 2026/06 값(92.68)이 t_roe 로 새어 들어오지 않는지 못 박습니다.
    """
    r = parse_financial_summary(_html())
    check(r["t_roe"] != 92.68, "분기 ROE(92.68)가 t_roe 로 새지 않음")
    check(r["t_roe"] != 61.16, "분기 ROE(61.16)가 t_roe 로 새지 않음")
    check("2025/12" in str(r["t_roe_period"]), "t_roe 출처가 연간 컬럼",
          f'({r["t_roe_period"]})')
    check("연간" in str(r["t_roe_period"]), "t_roe 출처 헤더가 '연간' 구획")
    check("QUARTERLY" not in ANNUAL_ACTUAL_KINDS and "QUARTERLY" not in ANNUAL_ESTIMATE_KINDS,
          "분기 분류가 사용 목록에 아예 없음")


def test_estimate_and_actual_are_kept_apart():
    """2차 감사 1-7 — 추정치가 실측치처럼 보이면 안 됩니다."""
    r = parse_financial_summary(_html())
    check("(E)" in str(r["f_roe_period"]), "f_roe 는 추정(E) 컬럼에서만",
          f'({r["f_roe_period"]})')
    check("(E)" not in str(r["t_roe_period"]), "t_roe 에는 추정 컬럼이 섞이지 않음")
    check(r["t_roe"] != r["f_roe"], "실적과 추정이 같은 값으로 뭉개지지 않음")


def test_annual_eps_is_not_confused_with_the_json_api_ttm_eps():
    """
    ⚠️ 같은 이름, 다른 기준. 이 표의 `EPS(원)` 는 **연간 확정**(58,955)이고,
    신 JSON API 의 `eps` 는 **최근 4분기 계열**(224,313)입니다. 3.8배 차이납니다
    (§1-5-6). 이 파서의 `t_eps` 를 현행 `t_eps` 자리에 그대로 넣으면 안 됩니다.
    """
    r = parse_financial_summary(_html())
    check(r["t_eps"] == 58955.0, "표의 연간 EPS 를 그대로 읽음", f'({r["t_eps"]})')
    check(r["t_eps"] != 224313.0, "신 JSON API 의 TTM EPS 와 다른 값임이 분명함")
    check(r["f_eps"] == 349342.0, "추정 EPS 는 신 API 와 같은 값", f'({r["f_eps"]})')


def test_broken_pages_return_none_not_zero():
    """§0-1 — 못 구한 값을 0 으로 메우지 않고, 사유를 남깁니다."""
    for label, html in (("빈 문자열", ""),
                        ("표 없는 페이지", "<html><body><p>서비스 점검중</p></body></html>"),
                        ("None", None)):
        r = parse_financial_summary(html)
        check(r["t_roe"] is None and r["f_roe"] is None and r["ev_ebitda"] is None,
              f"{label}: 값이 0 이 아니라 None")
        check(bool(r["errors"]), f"{label}: 사유가 errors 에 남음")


def test_a_page_with_tables_but_no_summary_table_is_reported():
    """
    ⚠️ 이 검사는 **사보타주가 찾아낸 구멍**입니다(2026-09-07).
    빈 페이지·표 없는 페이지는 위 검사가 덮지만, **표는 있는데 우리가 찾는 표만 없는**
    경우(사이트가 구획을 옮겼을 때 실제로 이렇게 됩니다)는 아무도 안 보고 있었습니다.
    조용히 통과하면 "값이 원래 없는 것"과 구분이 안 됩니다(§0-1).
    """
    html = """<html><body>
      <table><tr><th>공지</th></tr><tr><td>서비스 개편 안내</td></tr></table>
      <table><tr><th>구분</th><th>내용</th></tr><tr><td>문의</td><td>고객센터</td></tr></table>
    </body></html>"""
    r = parse_financial_summary(html)
    check(r["t_roe"] is None and r["f_roe"] is None, "재무요약 표가 없으면 ROE 는 None")
    check(any("재무요약" in e for e in r["errors"]),
          "재무요약 표를 못 찾았다는 사유가 기록됨", f'({r["errors"]})')
    check(any("EV/EBITDA" in e for e in r["errors"]),
          "EV/EBITDA 표를 못 찾았다는 사유도 따로 기록됨")


def test_estimate_columns_must_come_from_annual_not_quarterly():
    """
    ⚠️ 이것도 사보타주에서 나온 검사입니다. 추정 컬럼 목록에 **분기 추정**을 넣으면
    f_roe 가 분기 연환산 추정에서 오게 됩니다 — 연간 추정과 기준이 다릅니다.
    """
    from utils import wisereport_parser as WP
    check("QUARTERLY_EST" not in WP.ANNUAL_ESTIMATE_KINDS,
          "분기 추정(QUARTERLY_EST)이 연간 추정 목록에 없음")
    check("QUARTERLY" not in WP.ANNUAL_ACTUAL_KINDS,
          "분기 실적(QUARTERLY)이 연간 실적 목록에 없음")
    r = parse_financial_summary(_html())
    check(r["f_roe"] == 101.67, "f_roe 가 연간 추정값(101.67)", f'(실제 {r["f_roe"]})')
    check(r["f_roe"] is not None, "분기 추정 열은 비어 있어 f_roe 가 None 이 되면 안 됨")


def test_negative_roe_keeps_its_sign():
    """2차 감사 1-1 — 부호를 지우면 적자가 흑자로 둔갑합니다."""
    from utils.wisereport_parser import _cell_number
    check(_cell_number("-15.61") == -15.61, "음수 ROE 가 음수로 보존")
    check(_cell_number("-1,234") == -1234.0, "쉼표가 있어도 부호 보존")
    check(_cell_number("-") is None, "빈칸 표기는 0 이 아니라 None")
    check(_cell_number("nan") is None, "nan 은 None")


def test_no_iloc_positional_fallback():
    """
    §2-1 — 헤더 분류에 실패하면 **위치 인덱스로 폴백하지 않고** 미수집으로 둡니다.
    연도 컬럼 수가 종목마다 달라 '무조건 2번째 칸이 최신'이 성립하지 않습니다.
    """
    html = """<html><body><table>
      <tr><th>주요재무정보</th><th>1분기</th><th>2분기</th></tr>
      <tr><td>ROE(%)</td><td>11.1</td><td>22.2</td></tr>
      <tr><td>EPS(원)</td><td>100</td><td>200</td></tr>
      <tr><td>자본총계(지배)</td><td>10</td><td>20</td></tr>
    </table></body></html>"""
    r = parse_financial_summary(html)
    check(r["t_roe"] is None, "연간 컬럼을 특정 못 하면 ROE 를 추정하지 않음",
          f'(실제 {r["t_roe"]})')
    check(any("§2-1" in e for e in r["errors"]), "폴백을 하지 않았다는 사유가 기록됨",
          f'({r["errors"]})')


def test_module_does_not_touch_the_network():
    src = (REPO_ROOT / "utils" / "wisereport_parser.py").read_text(encoding="utf-8")
    for banned in ("import requests", "urllib.request", "httpx", "http.client"):
        check(banned not in src, f"네트워크 라이브러리 미사용: {banned}")


def test_it_is_wired_in_and_the_old_inline_parser_is_gone():
    """
    2026-09-08 배선(이관 4단계) 후 상태 — 다음 세션이 착각하지 않게 코드가 스스로 밝히는지.

    🔴 §0-3-10: 같은 페이지를 두 곳에서 파싱하면 안 됩니다. `_fetch_ev_ebitda()` 안에 있던
       `pd.read_html` + `'EV/EBITDA' not in str(df)` 식 인라인 파싱이 남아 있으면 빨간불.
    """
    src = (REPO_ROOT / "utils" / "wisereport_parser.py").read_text(encoding="utf-8")
    check("배선 완료" in src, "배선 사실이 모듈 머리말에 명시됨")
    check("아직 실전에 배선돼 있지 않습니다" not in src, "옛 '미배선' 문구가 남아 있지 않음")
    collector = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check("from utils.wisereport_parser import parse_financial_summary" in collector,
          "수집기가 이 모듈을 import 함")
    check("if 'EV/EBITDA' not in str(df):" not in collector,
          "수집기 안의 인라인 EV/EBITDA 표 파싱이 제거됨(§0-3-10)")
    check("_fetch_wisereport_metrics" in collector and "_fetch_ev_ebitda" in collector,
          "구 경로용 얇은 포장(_fetch_ev_ebitda)과 공용 요청기(_fetch_wisereport_metrics)가 있음")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
