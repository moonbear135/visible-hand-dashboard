# tests/test_naver_api_shadow.py
"""🔒 `run_naver_api_shadow.py` — 섀도 수집기 테스트 (2026-09-07, #213)

⚠️ 이 파일이 지키는 것은 두 가지입니다.

① 🔴 **실전 데이터를 건드리지 않는가.**
   섀도 수집기가 `data/kospi200_pegy_latest.json` 같은 실전 파일에 쓰는 사고는
   "설마 그러겠어"로 막지 않습니다. 코드가 스스로 경로를 검사하고, 그 검사가
   실제로 작동하는지 여기서 확인합니다.

② 🟢 **§0-3-2 매너 장치가 진짜 있는가.**
   딜레이·요청 상한·서킷 브레이커·403/429 즉시 중단·순차 요청.
   이 값들은 **속도 때문에 줄이면 안 되는 값**이라, 줄어들면 빨간불이 나게 못 박습니다.

📌 이 테스트는 **네트워크를 쓰지 않습니다.** `requests.Session.get` 을 전부 가짜로 바꿔
   돌립니다. 실제 수집은 GitHub Actions(`naver_api_shadow.yml`)가 합니다.

실행: python -m pytest tests/test_naver_api_shadow.py -v
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from conftest import FAILURES, check  # noqa: E402,F401
import pytest  # noqa: E402

import run_naver_api_shadow as SH  # noqa: E402
from utils.naver_stock_api import NaverApiSourceError  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "naver_new_api"


class _FakeResponse:
    def __init__(self, status=200, payload=None, raise_json=False):
        self.status_code = status
        self._payload = payload if payload is not None else []
        self._raise = raise_json
        self.content = b"x" * 10

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._payload


def _list_payload():
    return json.loads((FIXTURES / "market_list_marketSum_NXT_top10.json").read_text(encoding="utf-8"))


def _detail_payload():
    return json.loads((FIXTURES / "detail_000660_codeType_KRX.json").read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# ① 실전 데이터 미접촉
# ─────────────────────────────────────────────────────────────────────────────

def test_writing_outside_the_shadow_folder_is_refused():
    """🔴 이 파일에서 가장 중요한 검사입니다."""
    SH._assert_shadow_path(SH.SHADOW_DIR / "2026-09-07_shadow.json")   # 정상 경로는 통과
    SH._assert_shadow_path(SH.SHADOW_DIR)                              # 폴더 자신도 통과

    for forbidden in (
        REPO_ROOT / "data" / "kospi200_pegy_latest.json",
        REPO_ROOT / "data" / "kospi200_sanity.json",
        SH.SHADOW_DIR / ".." / "kospi200_pegy_latest.json",   # 상대경로 탈출 시도
        REPO_ROOT / "collector_kospi200.py",
    ):
        with pytest.raises(RuntimeError):
            SH._assert_shadow_path(forbidden)


def test_production_snapshot_is_only_read():
    """대조 함수가 실전 스냅샷을 **여는 방식**이 읽기 전용인지 소스로 확인합니다."""
    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    check('PRODUCTION_SNAPSHOT.open(encoding="utf-8")' in src,
          "실전 스냅샷은 읽기 모드로만 엽니다")
    for banned in ('PRODUCTION_SNAPSHOT.open("w"', "PRODUCTION_SNAPSHOT.write",
                   'PRODUCTION_SNAPSHOT.open("a"'):
        check(banned not in src, f"실전 스냅샷 쓰기 코드 없음: {banned}")
    # 모든 파일 쓰기가 _assert_shadow_path 를 통과하는지 — open("w") 호출부 검사
    for line in src.splitlines():
        if '.open("w"' in line:
            check("_assert_shadow_path" in line or "report_path" in line or "raw_path" in line,
                  f"쓰기 호출이 섀도 경로 검사를 거침: {line.strip()[:70]}")


# ─────────────────────────────────────────────────────────────────────────────
# ② §0-3-2 매너 장치
# ─────────────────────────────────────────────────────────────────────────────

def test_manner_constants_are_not_weakened():
    """
    이 값들은 **속도 때문에 줄이면 안 되는 값**입니다(§0-3-2).
    누군가 '너무 느린데'라고 줄이면 여기서 빨간불이 납니다.
    """
    check(SH.DELAY_MIN_SEC >= 2.0, "요청 간 최소 딜레이 2.0초 이상", f"({SH.DELAY_MIN_SEC})")
    check(SH.DELAY_MAX_SEC >= SH.DELAY_MIN_SEC, "최대 딜레이가 최소보다 크거나 같음")
    check(SH.CIRCUIT_CONSECUTIVE_FAILURES <= 5, "서킷 브레이커 임계 5회 이하",
          f"({SH.CIRCUIT_CONSECUTIVE_FAILURES})")
    check(SH.MAX_REQUESTS_PER_RUN <= 100, "1회 실행 요청 상한 100건 이하",
          f"({SH.MAX_REQUESTS_PER_RUN})")
    check(SH.LIST_PAGE_SIZE == 20, "pageSize 는 화면이 쓰는 20 그대로 (한도 탐색 금지)",
          f"({SH.LIST_PAGE_SIZE})")
    check(SH.DETAIL_SAMPLE_SIZE <= 30, "상세는 전 종목이 아니라 표본만",
          f"({SH.DETAIL_SAMPLE_SIZE})")


def test_no_parallel_requests():
    """병렬 요청을 새로 만들지 않습니다 — 순차가 기본입니다(§0-3-2)."""
    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    for banned in ("ThreadPool", "concurrent.futures", "asyncio", "multiprocessing",
                   "threading.Thread"):
        check(banned not in src, f"병렬 처리 미사용: {banned}")


def test_403_and_429_stop_immediately_without_retry():
    """
    🔴 차단은 상대가 그만하라는 뜻입니다. 재시도하지 않고, 우회하지 않고, 그 즉시 멈춥니다.
    """
    for status in (403, 429):
        sess = SH.PoliteSession()
        calls = []

        def fake_get(url, timeout=None):
            calls.append(url)
            return _FakeResponse(status=status)

        with mock.patch.object(sess.session, "get", fake_get), \
             mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
            with pytest.raises(SH.BlockedByServer):
                sess.get_json(SH.LIST_URL.format(start=0, size=20))
        check(len(calls) == 1, f"{status} 응답에 재시도하지 않음 (요청 {len(calls)}건)")


def test_circuit_breaker_opens_after_consecutive_failures():
    """연속 실패가 임계치를 넘으면 그날 남은 요청을 포기합니다."""
    sess = SH.PoliteSession()
    with mock.patch.object(sess.session, "get", lambda url, timeout=None: _FakeResponse(status=500)), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        for _ in range(SH.CIRCUIT_CONSECUTIVE_FAILURES):
            sess.get_json(SH.LIST_URL.format(start=0, size=20))
        with pytest.raises(SH.CircuitOpen):
            sess.get_json(SH.LIST_URL.format(start=0, size=20))
    check(sess.request_count == SH.CIRCUIT_CONSECUTIVE_FAILURES,
          "서킷이 열린 뒤에는 실제 요청이 더 나가지 않음", f"({sess.request_count}건)")


def test_request_cap_is_enforced():
    """요청 상한을 넘기려 하면 멈춥니다."""
    sess = SH.PoliteSession()
    sess.request_count = SH.MAX_REQUESTS_PER_RUN
    with pytest.raises(SH.CircuitOpen):
        sess.get_json(SH.LIST_URL.format(start=0, size=20))


def test_delay_is_actually_applied_between_requests():
    """딜레이가 '상수로만 있고 안 쓰이는' 상태가 아닌지 실제 호출을 셉니다."""
    sess = SH.PoliteSession()
    slept = []
    with mock.patch.object(sess.session, "get",
                           lambda url, timeout=None: _FakeResponse(payload=[])), \
         mock.patch.object(SH.time, "sleep", lambda s: slept.append(s)):
        for _ in range(3):
            sess.get_json(SH.LIST_URL.format(start=0, size=20))
    check(len(slept) == 2, "첫 요청 앞에는 대기하지 않고, 이후 요청마다 대기",
          f"({len(slept)}회)")
    check(all(SH.DELAY_MIN_SEC <= s <= SH.DELAY_MAX_SEC for s in slept),
          "대기 시간이 2.0~3.0초 범위", f"({[round(s,2) for s in slept]})")


# ─────────────────────────────────────────────────────────────────────────────
# ③ KRX 고정 — NXT 는 어떤 경로로도 들어오지 못합니다
# ─────────────────────────────────────────────────────────────────────────────

def test_all_urls_in_this_script_are_krx():
    check("codeType=KRX" in SH.DETAIL_URL, "상세 URL 이 codeType=KRX")
    check("tradeType=KRX" in SH.LIST_URL, "목록 URL 이 tradeType=KRX")
    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    check("NXT" not in src.replace("NXT(넥스트레이드)", "").replace("NXT 는", "")
                        .replace("NXT 주소", "").replace("NXT 차단", ""),
          "스크립트 코드에 NXT 주소가 없음(설명 문장 제외)")


def test_nxt_url_is_refused_even_if_someone_edits_the_constant():
    """상수를 잘못 고쳐도 요청 직전에 막힙니다 — 이중 방어."""
    sess = SH.PoliteSession()
    with pytest.raises(NaverApiSourceError):
        sess.get_json("https://stock.naver.com/api/domestic/detail/000660/detail?codeType=NXT")


# ─────────────────────────────────────────────────────────────────────────────
# ④ 수집·대조 동작 (전부 가짜 응답)
# ─────────────────────────────────────────────────────────────────────────────

def test_collect_runs_end_to_end_without_network():
    """목록 → 상세 표본까지 한 바퀴 도는지, 요청 수가 상한 안인지 확인합니다."""
    sess = SH.PoliteSession()
    lst, det = _list_payload(), _detail_payload()

    def fake_get(url, timeout=None):
        if "/market/stock/default" in url:
            # startIdx 가 커지면 빈 페이지를 돌려 종료 조건을 밟게 합니다
            start = int(url.split("startIdx=")[1].split("&")[0])
            return _FakeResponse(payload=lst if start == 0 else [])
        return _FakeResponse(payload=det)

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)

    check(len(out["list_rows"]) == 10, "목록 파싱 결과", f'({len(out["list_rows"])}종목)')
    check(out["stopped_reason"] is None, "중단 없이 완주")
    check(sess.request_count <= SH.MAX_REQUESTS_PER_RUN, "요청 상한 준수",
          f"({sess.request_count}건)")
    check(len(out["detail"]) >= 1, "상세 표본 수집됨", f'({len(out["detail"])}종목)')
    check(out["list_raw_sample"], "raw 표본이 가공본과 별도로 보관됨 (§0-3-3)")


def test_failed_pages_are_recorded_not_silently_dropped():
    """실패를 조용히 빼면 '수집이 안 된 건지 원래 없는 건지' 구분할 수 없습니다."""
    sess = SH.PoliteSession()

    def fake_get(url, timeout=None):
        if "startIdx=0&" in url:
            return _FakeResponse(payload=_list_payload())
        return _FakeResponse(status=500)

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)
    check(any("수집 실패" in e for e in out["errors"]), "실패한 페이지가 errors 에 남음")
    check(len(out["list_rows"]) == 10, "실패해도 이미 받은 종목은 버리지 않음 (재감사 H1)")


def test_compare_reports_match_ratio_per_field(tmp_path):
    """실전 스냅샷을 흉내낸 임시 파일로 대조 로직을 확인합니다(실제 파일은 안 건드립니다)."""
    shadow = {"list_rows": [
        {"code": "000660", "price": 1783000.0, "t_roe": 44.15, "t_eps": 224313.0,
         "t_per": 7.95, "outstanding_shares": 730492365},
        {"code": "005930", "price": 269000.0, "t_roe": 10.85, "t_eps": 22292.0,
         "t_per": 12.11, "outstanding_shares": 5846278608},
    ]}
    prod = {"stocks": [
        # 같은 값 — 일치해야 합니다
        {"code": "000660", "price": 1783000.0, "t_roe": 44.15, "t_eps": 224313,
         "t_per": 7.95, "outstanding_shares": 730492365},
        # ROE 만 크게 다른 값 — 불일치로 잡혀야 합니다
        {"code": "005930", "price": 269000.0, "t_roe": 99.99, "t_eps": 22292,
         "t_per": 12.11, "outstanding_shares": 5846278608},
    ]}
    fake = tmp_path / "kospi200_pegy_latest.json"
    fake.write_text(json.dumps(prod), encoding="utf-8")

    with mock.patch.object(SH, "PRODUCTION_SNAPSHOT", fake):
        rep = SH.compare_with_production(shadow)

    check(rep["matched_codes"] == 2, "공통 종목 계산", f'({rep["matched_codes"]})')
    check(rep["fields"]["price"]["match_ratio"] == 1.0, "현재가 일치율 100%")
    check(rep["fields"]["t_roe"]["match_ratio"] == 0.5,
          "ROE 는 2종목 중 1종목만 일치", f'({rep["fields"]["t_roe"]["match_ratio"]})')
    worst = rep["fields"]["t_roe"]["worst"]
    check(worst and worst[0]["code"] == "005930",
          "불일치 종목이 코드와 양쪽 값까지 함께 기록됨 (§0-1)")


def test_compare_says_so_when_there_is_no_production_snapshot(tmp_path):
    """대조할 것이 없으면 조용히 0% 로 만들지 않고 '못 했다'고 말합니다(§0-1)."""
    missing = tmp_path / "없는파일.json"
    with mock.patch.object(SH, "PRODUCTION_SNAPSHOT", missing):
        rep = SH.compare_with_production({"list_rows": []})
    check("대조하지 못했습니다" in rep["note"], "대조 불가 사유가 리포트에 남음")


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 알림 판정은 한 곳에만
# ─────────────────────────────────────────────────────────────────────────────

def test_alert_thresholds_live_in_python_not_in_yaml():
    """
    §0-3-10 — 같은 판정을 두 곳에 두지 않습니다. YAML 에 임계값이 다시 적히면
    한쪽만 고쳐져 조용히 어긋납니다.
    """
    yml = (REPO_ROOT / ".github" / "workflows" / "naver_api_shadow.yml").read_text(encoding="utf-8")
    check("--alert-message" in yml, "워크플로우가 스크립트의 판정을 호출함")
    for banned in ("0.95", "match_ratio <", "matched_codes"):
        check(banned not in yml, f"YAML 에 판정 임계값이 없음: {banned}")


def test_alert_message_is_empty_when_everything_matches(tmp_path):
    report = {"matched_codes": 500,
              "fields": {"t_roe": {"label": "ROE", "match_ratio": 0.99},
                         "price": {"label": "현재가", "match_ratio": 1.0}}}
    (tmp_path / "latest_compare.json").write_text(json.dumps(report), encoding="utf-8")
    with mock.patch.object(SH, "SHADOW_DIR", tmp_path):
        check(SH.build_alert_message() == "", "정상이면 빈 문자열")

    report["fields"]["t_roe"]["match_ratio"] = 0.60
    (tmp_path / "latest_compare.json").write_text(json.dumps(report), encoding="utf-8")
    with mock.patch.object(SH, "SHADOW_DIR", tmp_path):
        msg = SH.build_alert_message()
    check("ROE" in msg and "60.0%" in msg, "일치율이 떨어지면 한 줄로 알림", f"({msg})")

    report["matched_codes"] = 3
    (tmp_path / "latest_compare.json").write_text(json.dumps(report), encoding="utf-8")
    with mock.patch.object(SH, "SHADOW_DIR", tmp_path):
        check("공통 종목" in SH.build_alert_message(), "공통 종목이 너무 적으면 알림")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
