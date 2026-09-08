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
    def __init__(self, status=200, payload=None, raise_json=False, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else []
        self._raise = raise_json
        self.content = b"x" * 10
        self.text = text

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

def test_this_is_a_probe_not_a_collector():
    """
    🔴 2026-09-08 오너가 실제로 혼동한 지점입니다:
       *"우리가 매일 500종목을 긁어오는 구조인데 그걸 6일로 나눠서 하겠다는 거야?"* → 아닙니다.

    실전 수집(`collector_kospi200.py` + `scrape.yml`)은 **매일 520종목 전부**를 긁어
    화면에 씁니다. 이 스크립트는 그 뒤에 붙어 **확인만** 합니다.
    여기서 상세를 표본만 받는 것은 **시험 표본**이지 수집 범위가 아닙니다.

    이 검사는 그 구분이 코드와 문서에 실제로 남아 있는지 못 박습니다.
    """
    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    check("수집기가 아닙니다" in src, "스스로를 수집기가 아니라고 밝힘")

    # 목록은 표본이 아니라 **전 종목**입니다 — 여기를 줄이면 대조 자체가 무의미해집니다.
    check(SH.LIST_TARGET_COUNT >= 520, "목록은 실전과 같은 전 종목 범위",
          f"({SH.LIST_TARGET_COUNT})")

    # 2026-09-08 배선 후: 실전 수집기는 파서 모듈을 쓰지만 **이 섀도 스크립트에는 의존하지 않습니다**
    # (섀도는 한시적이라 이관이 끝나면 지워질 파일입니다 — 실전이 여기에 기대면 지울 수 없게 됩니다).
    collector = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    for banned in ("import run_naver_api_shadow", "from run_naver_api_shadow"):
        check(banned not in collector, f"실전 수집기가 섀도 스크립트를 import 하지 않음: {banned}")
    # 구 경로는 지워지지 않았고(오너 지시 — 스위치로 공존), 기본값도 구 출처입니다.
    check("finance.naver.com" in collector, "실전 수집기에 구 출처 경로가 그대로 남아 있음")
    from utils import naver_source as NS
    check(NS.DEFAULT_NAVER_SOURCE == NS.NAVER_SOURCE_LEGACY,
          "실전 기본값은 여전히 구 출처(전환은 오너 승인 사항 §0-3-6)")


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

    # ── 2026-09-08 오너 결정으로 섀도를 "520종목 전부, 매일"로 올렸습니다. ──────
    # 오너: *"앞으로 준비를 다 해보기 위해서는 520개 전부가 맞다고 생각은 하거든."*
    # 🔴 이 결정의 대가를 숫자로 적어 둡니다 — 하루 약 1,066요청은
    #    현행 수집기가 이미 보내는 약 1,040요청과 **비슷한 양**이라,
    #    이관이 끝날 때까지 상대 서버가 받는 총량은 **약 2배**가 됩니다.
    # ⏳ **반드시 한시적입니다.** 이관이 끝나거나 관찰이 필요 없어지면
    #    워크플로우째 지우세요. 이 양을 계속 보내는 것은 §0-3-2 위반입니다.
    #
    # 그래서 상한은 "낮게"가 아니라 **"계획한 것 이상은 못 보낸다"**로 지킵니다.
    # 아래 두 검사가 그 자물쇠입니다.
    planned = SH.LIST_PAGE_COUNT + SH.DETAIL_SAMPLE_SIZE + SH.WISEREPORT_SAMPLE_SIZE
    check(planned <= SH.MAX_REQUESTS_PER_RUN, "계획된 요청 수가 상한 안",
          f"({planned} / {SH.MAX_REQUESTS_PER_RUN})")
    # 상한과 계획의 간격이 벌어지면, 코드가 조용히 더 보내도 아무도 모릅니다.
    # 여유는 재시도분 정도(10%)까지만 허용합니다.
    check(SH.MAX_REQUESTS_PER_RUN <= planned * 1.1 + 10,
          "요청 상한이 계획보다 과하게 크지 않음 (조용한 증가 방지)",
          f"(상한 {SH.MAX_REQUESTS_PER_RUN} / 계획 {planned})")

    # 섀도는 **실전보다 넓게 보지 않습니다.** 실전이 안 보는 종목을 섀도가 긁는 것은
    # 관찰이 아니라 새로운 부하입니다(§0-3-2).
    check(SH.SHADOW_UNIVERSE_SIZE <= SH.LIST_TARGET_COUNT,
          "섀도 범위가 실전 범위를 넘지 않음",
          f"({SH.SHADOW_UNIVERSE_SIZE} / {SH.LIST_TARGET_COUNT})")

    # 총량이 커진 만큼 **뭉쳐 보내지 않는 것**이 유일한 예의입니다.
    # 순차 + 2초 간격이면 최소 30분 이상에 걸쳐 나갑니다. 이보다 짧아지면
    # 누군가 병렬화했거나 딜레이를 줄인 것입니다.
    min_minutes = planned * SH.DELAY_MIN_SEC / 60
    check(min_minutes >= 30,
          "한 번 실행이 최소 30분 이상에 걸쳐 나감 (버스트 금지)",
          f"(약 {min_minutes:.0f}분)")

    check(SH.LIST_PAGE_SIZE == 20, "pageSize 는 화면이 쓰는 20 그대로 (한도 탐색 금지)",
          f"({SH.LIST_PAGE_SIZE})")
    check(SH.DETAIL_SAMPLE_SIZE <= SH.SHADOW_UNIVERSE_SIZE,
          "상세는 섀도 범위를 넘지 않음",
          f"({SH.DETAIL_SAMPLE_SIZE} / {SH.SHADOW_UNIVERSE_SIZE})")


def test_shadow_looks_at_the_same_universe_every_day():
    """
    🔴 2026-09-08 **오너 결정** — 회전 표본을 걷어내고 "좁게, 매일 전부"로 바꿨습니다.

    오너: *"데이터 오염을 잡는 게 어렵기 때문에 이것저것 계속 안전막을 막고 있는 건데,
    지금 매일 100개씩 받는 걸로는 그걸 커버할 수가 없다고 생각해. 차라리 크롤링 종목을
    시가총액 순위 200개로 해서 **전체적으로 매일 받으면서** 확인을 하는 게 맞아."*

    **오염은 시계열로만 보입니다.** 회전은 그 시계열을 끊어서, "오늘 일치"만 알 뿐
    어느 날 어긋났는지·왜 어긋났는지를 못 짚습니다. 폭을 줄이고 깊이를 택했습니다.
    """
    check(SH.DETAIL_SAMPLE_SIZE == SH.SHADOW_UNIVERSE_SIZE,
          "상세는 섀도 범위 전부를 봄 (표본 아님)",
          f"({SH.DETAIL_SAMPLE_SIZE} / {SH.SHADOW_UNIVERSE_SIZE})")
    check(SH.WISEREPORT_SAMPLE_SIZE == SH.SHADOW_UNIVERSE_SIZE,
          "위즈리포트도 같은 범위 전부를 봄 — 한 종목의 재료를 같은 날 함께 봐야 함")

    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    check("detail_codes = codes[:DETAIL_SAMPLE_SIZE]" in src,
          "상세 대상이 회전이 아니라 '시총 상위 N' 고정")
    check("rotating_sample(codes, DETAIL_SAMPLE_SIZE" not in src,
          "상세에 회전을 쓰지 않음")
    check("wise_codes = codes[:WISEREPORT_SAMPLE_SIZE]" in src,
          "위즈리포트도 회전이 아님")

    # 같은 종목을 매일 본다는 것이 핵심입니다 — 날짜가 달라도 대상이 같아야 합니다.
    codes = [f"{i:06d}" for i in range(520)]
    check(codes[:SH.DETAIL_SAMPLE_SIZE] == codes[:SH.DETAIL_SAMPLE_SIZE],
          "대상이 날짜에 의존하지 않음 (매일 같은 종목)")

    # 2026-09-08 오너 결정으로 섀도 범위를 실전과 **똑같이** 520으로 맞췄으므로,
    # 목록이 더 넓을 이유가 사라졌습니다. 대신 지켜야 할 것은
    # "목록이 섀도가 보는 종목을 **하나도 빠뜨리지 않는다**"입니다 —
    # 목록이 좁아지면 상세를 받을 종목 코드 자체가 모자라 조용히 덜 받게 됩니다.
    check(SH.LIST_TARGET_COUNT >= SH.SHADOW_UNIVERSE_SIZE,
          "목록이 섀도가 볼 종목을 전부 덮음",
          f"({SH.LIST_TARGET_COUNT} >= {SH.SHADOW_UNIVERSE_SIZE})")


def test_timing_is_recorded_start_to_finish():
    """
    🔴 2026-09-08 오너 요구: *"받아지는 시간까지 확인을 해야 하는 것도 지금 필요하니까,
    크롤링 시작 종료 시간."*

    왜 필요한가: ① **이관 후 실전이 얼마나 걸릴지** 추정하려면 실측이 있어야 합니다
    ② 수집이 길어져 **장 시작까지 걸치면** 백필 없는 수집기가 장중 가격을 종가로
    저장하는 사고가 납니다 ③ **응답이 느려지는 것은 상대 서버 부하 신호**입니다(§0-3-2).
    """
    sess = SH.PoliteSession()

    def fake_get(url, timeout=None):
        if "wisereport" in url:
            return _FakeResponse(payload=None, text="<html></html>")
        if "/market/stock/default" in url:
            start = int(url.split("startIdx=")[1].split("&")[0])
            return _FakeResponse(payload=_list_payload() if start == 0 else [])
        return _FakeResponse(payload=_detail_payload())

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)

    t = out.get("timing", {})
    check(out.get("started_at_kst"), "시작 시각을 기록")
    check(t.get("ended_at_kst"), "종료 시각을 기록")
    check(t.get("total_sec") is not None, "총 소요를 기록")
    for stage in ("list_sec", "detail_sec", "wisereport_sec"):
        check(stage in t, f"단계별 소요를 기록: {stage}")
    check(t.get("requests") == sess.request_count, "요청 수가 맞음")
    check("response_sec_median" in t, "응답 시간 중앙값을 기록")
    check("waiting_sec" in t, "딜레이에 쓴 시간을 따로 기록 (매너 장치가 실제로 도는지)")

    # 느려지면 경고, 정상이면 조용
    check(not SH.check_timing({"response_sec_median": 0.3, "total_sec": 1000}),
          "정상 속도에는 경고 없음")
    w = SH.check_timing({"response_sec_median": 5.0, "response_sec_max": 9.0,
                         "total_sec": 1000})
    check(any("응답이 느립니다" in x for x in w), "느린 응답을 잡음", f"({w})")
    w2 = SH.check_timing({"response_sec_median": 0.3, "total_sec": 7200})
    check(any("걸칠 위험" in x for x in w2), "너무 오래 걸리면 잡음", f"({w2})")


def test_wisereport_sample_is_actually_collected():
    """
    ⚠️ 이것도 사보타주가 찾은 구멍입니다. `WISEREPORT_SAMPLE_SIZE = 0` 으로 만들어도
    아무 테스트가 빨간불을 내지 않았습니다.

    🔴 위즈리포트는 **Forward ROE·EV/EBITDA 의 유일한 출처**이고, 3회차까지 검증률이
    **0%** 였던 자리입니다. 표본이 0 이 되면 그 공백으로 조용히 되돌아갑니다.
    """
    check(SH.WISEREPORT_SAMPLE_SIZE > 0, "위즈리포트 표본이 0 이 아님",
          f"({SH.WISEREPORT_SAMPLE_SIZE})")

    sess = SH.PoliteSession()
    wise_urls = []

    def fake_get(url, timeout=None):
        if "wisereport" in url:
            wise_urls.append(url)
            return _FakeResponse(payload=None, text="<html></html>")
        if "/market/stock/default" in url:
            start = int(url.split("startIdx=")[1].split("&")[0])
            return _FakeResponse(payload=_list_payload() if start == 0 else [])
        return _FakeResponse(payload=_detail_payload())

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)

    check(wise_urls, "위즈리포트를 실제로 요청함", f"({len(wise_urls)}건)")
    check(all("cmp_cd=" in u for u in wise_urls), "종목코드를 붙여 요청함")
    check(out.get("wisereport"), "결과에 위즈리포트 파싱 결과가 담김")
    check(out.get("wisereport_sample_codes"), "어떤 종목을 봤는지 기록됨")


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
                sess.get_json(SH.LIST_URL.format(page=0, size=20))
        check(len(calls) == 1, f"{status} 응답에 재시도하지 않음 (요청 {len(calls)}건)")


def test_circuit_breaker_opens_after_consecutive_failures():
    """연속 실패가 임계치를 넘으면 그날 남은 요청을 포기합니다."""
    sess = SH.PoliteSession()
    with mock.patch.object(sess.session, "get", lambda url, timeout=None: _FakeResponse(status=500)), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        for _ in range(SH.CIRCUIT_CONSECUTIVE_FAILURES):
            sess.get_json(SH.LIST_URL.format(page=0, size=20))
        with pytest.raises(SH.CircuitOpen):
            sess.get_json(SH.LIST_URL.format(page=0, size=20))
    check(sess.request_count == SH.CIRCUIT_CONSECUTIVE_FAILURES,
          "서킷이 열린 뒤에는 실제 요청이 더 나가지 않음", f"({sess.request_count}건)")


def test_request_cap_is_enforced():
    """요청 상한을 넘기려 하면 멈춥니다."""
    sess = SH.PoliteSession()
    sess.request_count = SH.MAX_REQUESTS_PER_RUN
    with pytest.raises(SH.CircuitOpen):
        sess.get_json(SH.LIST_URL.format(page=0, size=20))


def test_delay_is_actually_applied_between_requests():
    """딜레이가 '상수로만 있고 안 쓰이는' 상태가 아닌지 실제 호출을 셉니다."""
    sess = SH.PoliteSession()
    slept = []
    with mock.patch.object(sess.session, "get",
                           lambda url, timeout=None: _FakeResponse(payload=[])), \
         mock.patch.object(SH.time, "sleep", lambda s: slept.append(s)):
        for _ in range(3):
            sess.get_json(SH.LIST_URL.format(page=0, size=20))
    check(len(slept) == 2, "첫 요청 앞에는 대기하지 않고, 이후 요청마다 대기",
          f"({len(slept)}회)")
    check(all(SH.DELAY_MIN_SEC <= s <= SH.DELAY_MAX_SEC for s in slept),
          "대기 시간이 2.0~3.0초 범위", f"({[round(s,2) for s in slept]})")


# ─────────────────────────────────────────────────────────────────────────────
# ②-2 🔴 페이지네이션 — 2026-09-08 실제 사고의 회귀 검사
# ─────────────────────────────────────────────────────────────────────────────

BROKEN_PAGINATION_FIXTURE = FIXTURES / "broken_pagination_2026-09-08.json"


def _broken_rows():
    return json.loads(BROKEN_PAGINATION_FIXTURE.read_text(encoding="utf-8"))["rows"]


def test_start_idx_is_a_page_index_not_an_offset():
    """
    🔴 2026-09-08 실제 사고. `startIdx` 를 항목 오프셋으로 착각해 0,20,40… 으로 요청했더니
    1~20위 다음에 **401위대**가 이어붙었습니다(실제 오프셋 = startIdx × pageSize).
    오너가 브라우저로 실측 확인: `startIdx=1&pageSize=20` → 첫 종목 **하나금융지주**(21위).
    """
    check("{page}" in SH.LIST_URL, "URL 이 페이지 인덱스를 받도록 돼 있음")
    check("{start}" not in SH.LIST_URL, "오프셋을 뜻하는 이름이 남아 있지 않음")
    check(SH.LIST_PAGE_COUNT * SH.LIST_PAGE_SIZE == SH.LIST_TARGET_COUNT,
          "페이지 수 × 페이지 크기 == 목표 종목 수",
          f"({SH.LIST_PAGE_COUNT}×{SH.LIST_PAGE_SIZE} vs {SH.LIST_TARGET_COUNT})")
    # 페이지 번호가 0,1,2… 로 나가는지 실제 URL 로 확인
    urls = [SH.LIST_URL.format(page=p, size=SH.LIST_PAGE_SIZE) for p in range(3)]
    check("startIdx=0&" in urls[0] and "startIdx=1&" in urls[1] and "startIdx=2&" in urls[2],
          "요청이 startIdx=0,1,2… 로 나감 (0,20,40 이 아님)")


def test_the_real_2026_09_08_failure_is_caught():
    """
    🔴 이 검사의 존재 이유. **실제로 잘못 모아 온 응답**을 그대로 넣어 잡히는지 봅니다.
    겉보기엔 멀쩡했습니다 — 첫 페이지가 맞았고 전체가 시총 내림차순이라
    "정렬됐는가" 같은 검사로는 절대 못 잡습니다.
    """
    assert BROKEN_PAGINATION_FIXTURE.is_file(), "회귀 픽스처가 없습니다"
    rows = _broken_rows()
    warnings = SH.check_pagination_continuity(rows, list(range(0, len(rows), 20)))
    check(any("페이지 경계" in w and "급락" in w for w in warnings),
          "경계에서의 비정상 낙폭을 잡음", f"({warnings})")
    check(any("맵스리얼티" in w for w in warnings),
          "실제로 끊긴 지점(현대모비스 → 맵스리얼티)을 짚어 줌")
    check(any("160종목" in w for w in warnings), "수집량 부족도 함께 보고")


def test_normal_data_produces_no_warning():
    """
    🔴 **오탐이 나는 경보는 곧 무시당하는 경보입니다.**
    시총 상위권은 원래 낙폭이 큽니다(실측: SK하이닉스 → 삼성전자우가 8배).
    절대 임계값을 쓰면 여기서 오탐이 나므로, 같은 구간의 정상 낙폭과 비교합니다.
    """
    import math
    good = [{"code": f"{i:06d}", "name": f"종목{i}",
             "market_cap_api_truncated": 1.6e15 * math.exp(-i / 40) + 3e11}
            for i in range(500)]
    warnings = SH.check_pagination_continuity(good, list(range(0, 500, 20)))
    check(not warnings, "정상적으로 감소하는 500종목에는 경고가 없음", f"({warnings})")

    # 상위권의 큰 낙폭 자체는 경고 대상이 아님을 직접 확인
    # 상위권의 큰 낙폭 자체는 경고 대상이 아님을 직접 확인 (SK하이닉스 → 삼성전자우 = 8배)
    steep = [{"code": f"{i:06d}", "name": f"종목{i}",
              "market_cap_api_truncated": c}
             for i, c in enumerate([1578e12, 1302e12, 160e12, 148e12, 108e12] * 100)]
    warns = SH.check_pagination_continuity(steep, list(range(0, len(steep), 20)))
    check(not any("경계" in w for w in warns),
          "페이지 내부의 8배 낙폭은 경계 경고를 유발하지 않음", f"({warns[:1]})")


def test_market_hours_are_warned_but_not_blocked():
    """
    🔴 이 저장소는 **장중 실행으로 실제 사고를 겪었습니다**(백필 없는 수집기가 장중에 돌면
    그 순간 가격이 그날 종가로 저장됨 — `watch_schedule_health.yml` 이 그래서 장중에는
    자동 재실행을 생략합니다).

    섀도는 실전을 건드리지 않으므로 **막지는 않습니다.** 다만 장중에는 신 API 가 오늘
    실시간가를, 대조 상대인 실전 스냅샷은 어제 종가를 담고 있어 현재가가 전부 불일치로
    나옵니다 — **값이 틀린 게 아니라 기준 시점이 다른 것**이고, 모르고 보면
    "신 API 가 틀렸다"고 잘못 읽게 됩니다(§0-1).
    """
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    cases = [
        ("화 07:50 개장 전", datetime(2026, 9, 8, 7, 50, tzinfo=kst), False),
        ("화 09:00 개장",    datetime(2026, 9, 8, 9, 0, tzinfo=kst), True),
        ("화 10:30 장중",    datetime(2026, 9, 8, 10, 30, tzinfo=kst), True),
        ("화 15:30 마감",    datetime(2026, 9, 8, 15, 30, tzinfo=kst), True),
        ("화 16:30 마감 후", datetime(2026, 9, 8, 16, 30, tzinfo=kst), False),
        ("토 10:30 휴장",    datetime(2026, 9, 12, 10, 30, tzinfo=kst), False),
    ]
    for label, when, expect in cases:
        got = bool(SH.market_session_warning(when))
        check(got == expect, f"{label} → {'경고' if expect else '조용'}")

    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    check("raise" not in src.split("def market_session_warning")[1].split("def ")[0],
          "장중이어도 예외로 막지 않음 (경고만)")


def test_security_type_is_never_used_as_a_filter():
    """
    🔴 2026-09-08 오너 지적으로 바로잡은 것.

    처음에 저는 신 API 의 `type` 이 `ST` 가 아닌 종목(리츠 RT · 인프라투자회사 IF ·
    예탁증서 DR · 뮤추얼펀드 MF)을 "비주식이니 걸러야 한다"고 적었습니다. **틀렸습니다.**

    실측으로 확인한 것:
      · 현행은 `kr_ticker_master.json`(FinanceDataReader)로 **STOCK/ETF 두 갈래만** 나누고,
        위 유형을 **전부 STOCK 으로 수집**합니다(맥쿼리인프라·SK리츠·롯데리츠·맵스리얼티·
        코오롱티슈진 모두 현행 스냅샷에 있고 `is_visible=True`).
      · 지표가 없는 종목은 **거르는 게 아니라 검증에서 막습니다**(`is_valid=False`,
        배지 "⚠️ 데이터 검증 필요", 점수 None) — §0-1 설계 그대로입니다.

    → `type` 으로 거르면 **종목 유형 판정이 두 곳**이 되고(FDR vs 네이버, 실제로 어긋남),
      어긋나는 순간 종목이 조용히 사라집니다(§0-3-10).
    """
    src = (REPO_ROOT / "run_naver_api_shadow.py").read_text(encoding="utf-8")
    for banned in ('== "ST"', "== 'ST'", '!= "ST"', "securityType ==", 'type") == "ST"'):
        check(banned not in src, f"종목 유형으로 거르지 않음: {banned}")

    # 실제로도 비주식이 결과에 남는지 확인 (걸러지면 여기서 빨간불)
    sess = SH.PoliteSession()
    payload = _list_payload()[:2] + [dict(_list_payload()[0], itemcode="395400",
                                          itemname="SK리츠", type="RT")]

    def fake_get(url, timeout=None):
        if "startIdx=0&" in url:
            return _FakeResponse(payload=payload)
        if "/market/stock/default" in url:
            return _FakeResponse(payload=[])
        return _FakeResponse(payload=_detail_payload())

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)
    types = {r.get("api_security_type") for r in out["list_rows"]}
    check("RT" in types, "리츠(RT)가 결과에 그대로 남음 — 현행과 같은 범위", f"({types})")


def test_target_count_matches_production_tracking_range():
    """
    실전은 **상위 500 + 히스테리시스 버퍼 20 = 520종목**을 추적합니다.
    섀도가 500만 받으면 경계에서 21종목이 어긋나 "안 맞는다"는 착시가 납니다
    (2026-09-08 실측 — 상위 490 까지는 500 수집으로도 100% 일치했습니다).
    """
    check(SH.LIST_TARGET_COUNT == 520, "실전과 같은 520종목을 목표로 함",
          f"({SH.LIST_TARGET_COUNT})")
    check(SH.LIST_PAGE_COUNT * SH.LIST_PAGE_SIZE >= 520, "페이지 수가 520종목을 덮음",
          f"({SH.LIST_PAGE_COUNT}×{SH.LIST_PAGE_SIZE})")
    check(SH.LIST_PAGE_COUNT + SH.DETAIL_SAMPLE_SIZE <= SH.MAX_REQUESTS_PER_RUN,
          "늘어난 페이지 수가 요청 상한 안에 있음",
          f"({SH.LIST_PAGE_COUNT + SH.DETAIL_SAMPLE_SIZE} / {SH.MAX_REQUESTS_PER_RUN})")


def test_collect_actually_requests_page_0_1_2_not_0_20_40():
    """
    ⚠️ **사보타주가 찾아낸 구멍**(2026-09-08). URL 상수만 보는 검사는
    호출부가 `page*PAGE_SIZE` 를 넘기는 실수를 못 잡습니다 — 그게 바로 원래 사고였습니다.
    **실제로 나가는 주소**를 셉니다.
    """
    sess = SH.PoliteSession()
    sent = []

    def fake_get(url, timeout=None):
        sent.append(url)
        if "startIdx=" not in url:                      # 상세 요청
            return _FakeResponse(payload=_detail_payload())
        start = int(url.split("startIdx=")[1].split("&")[0])
        # 0,1,2 페이지는 값을 주고 그 뒤는 비웁니다 — 페이지 번호가 어떻게 올라가는지 봅니다.
        return _FakeResponse(payload=_list_payload() if start < 3 else [])

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        SH.collect(sess)

    idxs = [int(u.split("startIdx=")[1].split("&")[0]) for u in sent if "startIdx=" in u]
    check(idxs[:3] == [0, 1, 2], "실제 요청이 startIdx=0,1,2 로 나감", f"({idxs[:5]})")
    check(20 not in idxs[:3], "0,20,40 (오프셋 방식)으로 나가지 않음")


def test_collect_carries_the_pagination_warnings_out():
    """
    ⚠️ 이것도 사보타주가 찾은 구멍입니다. 검사 함수가 아무리 잘 잡아도
    `collect()` 가 그 결과를 버리면 아무도 모릅니다(§0-1 — 로그만 남기는 건 조치가 아님).
    """
    sess = SH.PoliteSession()
    broken = _broken_rows()

    def fake_get(url, timeout=None):
        if "wisereport" in url:
            return _FakeResponse(payload=None, text="<html></html>")
        if "/market/stock/default" not in url:      # 상세 요청은 목록과 다른 응답
            return _FakeResponse(payload=_detail_payload())
        start = int(url.split("startIdx=")[1].split("&")[0])
        chunk = broken[start * 20:(start + 1) * 20]
        return _FakeResponse(payload=[
            {"itemcode": r["code"], "itemname": r["name"], "nowPrice": "1000",
             "marketSum": str(int(r["market_cap_api_truncated"] or 0))} for r in chunk])

    with mock.patch.object(sess.session, "get", fake_get), \
         mock.patch.object(SH.time, "sleep", lambda *a, **kw: None):
        out = SH.collect(sess)

    check(out.get("pagination_warnings"), "collect() 결과에 경고가 담김",
          f'({out.get("pagination_warnings")})')
    check(any("급락" in e for e in out["errors"]),
          "경고가 errors 에도 실려 호출부가 반드시 보게 됨")


def test_a_steep_but_legitimate_drop_at_a_page_boundary_is_not_flagged():
    """
    ⚠️ 사보타주가 찾은 세 번째 구멍 — **오탐 방지가 실제로 검증되지 않았습니다.**
    상위권의 큰 낙폭이 **하필 페이지 경계에 놓이는** 경우를 아무도 안 보고 있었습니다.
    절대 임계값(5배)으로 되돌리면 여기서 오탐이 나고, 상대 기준이면 조용해야 합니다.
    (실측 근거: 1~20위 구간 내부의 정상 낙폭 최대치가 8.1배 — SK하이닉스 → 삼성전자우)
    """
    caps = [1578e12, 1302e12, 160e12] + [150e12 - i * 2e12 for i in range(17)]  # 내부 8.1배 낙폭
    caps += [caps[-1] / 8]                                                       # 경계에서 8배
    caps += [caps[-1] * (0.97 ** i) for i in range(1, 20)]
    rows = [{"code": f"{i:06d}", "name": f"종목{i}", "market_cap_api_truncated": c}
            for i, c in enumerate(caps)]
    warnings = SH.check_pagination_continuity(rows, [0, 20])
    check(not any("경계" in w for w in warnings),
          "구간 내부의 정상 낙폭과 비슷한 경계 낙폭은 경고하지 않음", f"({warnings})")


def test_overlapping_pages_are_caught():
    """페이지가 겹쳐 같은 종목이 두 번 들어오는 것도 잘못 넘긴 신호입니다."""
    rows = [{"code": "005930", "name": "삼성전자", "market_cap_api_truncated": 1578e12},
            {"code": "000660", "name": "SK하이닉스", "market_cap_api_truncated": 1302e12},
            {"code": "005930", "name": "삼성전자", "market_cap_api_truncated": 1578e12}]
    warnings = SH.check_pagination_continuity(rows, [0, 2])
    check(any("두 번 이상" in w for w in warnings), "중복 종목을 잡음", f"({warnings})")


def test_pagination_warning_reaches_the_alert(tmp_path):
    """
    경고가 파일에만 남고 사람에게 안 가면 없는 것과 같습니다(§0-1).
    섀도 파일의 `pagination_warnings` 가 디스코드 알림 문구에 실리는지 확인합니다.
    """
    (tmp_path / "latest_compare.json").write_text(json.dumps(
        {"matched_codes": 500, "fields": {"t_roe": {"label": "ROE", "match_ratio": 1.0}}}),
        encoding="utf-8")
    (tmp_path / "2026-09-08_shadow.json").write_text(json.dumps(
        {"pagination_warnings": ["🔴 페이지 경계에서 시가총액이 58배 급락"]}), encoding="utf-8")
    with mock.patch.object(SH, "SHADOW_DIR", tmp_path):
        msg = SH.build_alert_message()
    check("58배 급락" in msg,
          "일치율이 100%여도 페이지네이션 경고는 알림에 실림", f"({msg})")


# ─────────────────────────────────────────────────────────────────────────────
# ②-3 🔴 "값이 같은가"를 넘어 — 정제까지 제대로 되는가 (2026-09-08 오너 지적)
# ─────────────────────────────────────────────────────────────────────────────

def test_rank_integrity_catches_a_wrong_order():
    """
    🔴 오너: *"크롤링해서 제대로 제 위치를 잡을 수 있을지 없을지도 봐야 할 것 아냐.
       현재 국내주식은 위아래가 다 롤러코스터라서."*

    실측(히스토리): 시총 순위가 하루 중앙값 2~3계단, **최대 70계단**까지 뜁니다.
    받은 순서를 그냥 믿으면 안 되고, **직접 계산한 시총으로 다시 세워도 같은지** 봅니다.
    """
    good = [{"code": f"{i:06d}", "name": f"종목{i}",
             "market_cap_api_truncated": (520 - i) * 1e11,
             "price": 1000.0, "outstanding_shares": (520 - i) * 1e8}
            for i in range(520)]
    check(not SH.check_rank_integrity(good), "정상 순서에는 경고 없음")

    # 순서가 뒤집힌 경우
    swapped = list(good)
    swapped[10], swapped[11] = swapped[11], swapped[10]
    w = SH.check_rank_integrity(swapped)
    check(any("내림차순이 아닙니다" in x for x in w), "뒤바뀐 순서를 잡음", f"({w})")

    # 받은 순서와 '직접 계산한 시총' 순서가 어긋나는 경우 (진짜 위험한 쪽)
    liar = [dict(r) for r in good]
    liar[5]["outstanding_shares"] = 1e12          # 실제로는 1위여야 할 종목
    w2 = SH.check_rank_integrity(liar)
    check(any("재정렬하면" in x for x in w2), "직접 계산과 어긋나는 순위를 잡음", f"({w2})")


def test_change_sync_catches_one_side_missing_an_update():
    """
    🔴 오너: *"매일 다른 종목 100개를 쌓으면, 그 사이사이에 데이터가 바뀌었을 때
       바뀐 데이터를 정리하는 것까지 오류를 잡을 수 있겠어?"*

    실측: `t_eps` 는 거의 매일 바뀝니다 — 실적 시즌엔 하루 **74종목**(2026-08-24).
    실적이 반영되면 신 API 도 실전도 **함께** 바뀌어야 정상입니다.
    한쪽만 바뀌면 갱신을 놓친 것인데, **값이 같은지만 봐서는 안 보입니다**
    (바뀌기 전에는 둘 다 옛 값이라 '일치'로 나옵니다).
    """
    y = {f"{i:06d}": {"t_eps": 100.0, "t_roe": 10.0} for i in range(20)}
    # 정상: 양쪽이 같은 종목에서 같이 바뀜
    t = {c: dict(v) for c, v in y.items()}
    p_y = {c: dict(v) for c, v in y.items()}
    p_t = {c: dict(v) for c, v in y.items()}
    for c in list(y)[:5]:
        t[c]["t_eps"] = 200.0
        p_t[c]["t_eps"] = 200.0
    check(not SH.check_change_sync(t, y, p_t, p_y), "양쪽이 같이 바뀌면 조용함")

    # 🔴 실전만 바뀌고 신 API 는 그대로 — 신 API 가 갱신을 놓친 경우
    t2 = {c: dict(v) for c, v in y.items()}
    w = SH.check_change_sync(t2, y, p_t, p_y)
    check(any("바뀐 종목이 서로 다릅니다" in x for x in w), "한쪽만 바뀐 것을 잡음", f"({w})")
    check(any("실전만 바뀜" in x for x in w), "어느 쪽이 놓쳤는지 짚어 줌")

    # 어제 자료가 없으면 조용히 넘어가지 않고 사실을 남깁니다(§0-1)
    check(any("확인하지 못했습니다" in x for x in SH.check_change_sync({}, {}, {}, {})),
          "어제 자료가 없다는 사실을 기록")


def test_universe_drift_tolerates_boundary_but_catches_a_real_gap():
    """
    국내 시장은 변동이 커서 매일 1~7종목이 상위 500위권을 드나듭니다(실측).
    경계에서 몇 종목 어긋나는 것은 **정상**이지만, 크게 벌어지면 범위 설정이 틀린 것입니다.
    """
    prod = {f"{i:06d}" for i in range(520)}
    near = {f"{i:06d}" for i in range(4, 524)}          # 앞뒤 4종목씩 차이 = 경계 흔들림
    check(not SH.check_universe_drift(near, prod), "경계 흔들림(4종목)은 경고 없음")

    far = {f"{i:06d}" for i in range(100, 620)}         # 100종목 차이
    w = SH.check_universe_drift(far, prod)
    check(w and "어긋납니다" in w[0], "크게 벌어지면 잡음", f"({w})")


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
        if "wisereport" in url:
            return _FakeResponse(payload=None, text="<html></html>")
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
        if "wisereport" in url:
            return _FakeResponse(payload=None, text="<html></html>")
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


def test_frozen_data_catches_the_2026_09_04_shape():
    """
    🔴 2026-09-04 에 **실전에서 실제로 났던 사고**(#195)와 같은 모양을 잡는지 봅니다.

    그날 코스피 수집기는 "오늘 날짜 라벨 + 어제 내용물" 스냅샷을 남기고 정식 수집을
    건너뛰었습니다. 전 종목 주가가 하나도 바뀌지 않았는데도 `data_sanity` 는 조용했습니다 —
    결측도 아니고, 종목 수도 같고, 중앙값 이동이 0 이라 **오히려 "너무 정상"** 으로
    보였기 때문입니다. 값이 같은지만 보는 검사로는 절대 안 보이는 사고입니다.

    오너: *"9월 4일에는 크롤링 문제가 있었어서 그 부분은 수정을 했었을 거야."*
    → 실전은 고쳤지만, **섀도에도 같은 눈이 없으면** 신 API 가 얼어붙은 값을 주는 날
      "일치율 100%"라는 가장 안심되는 숫자가 나오면서 둘 다 틀린 상태가 됩니다.
    """
    y = {f"{i:06d}": {"price": 10000 + i} for i in range(100)}

    # ① 정상 — 대부분의 종목 주가가 움직임
    t_normal = {c: {"price": v["price"] + 100} for c, v in y.items()}
    check(not SH.check_frozen_data(t_normal, y), "정상적으로 움직인 날은 조용함")

    # ② 🔴 전 종목 동일 — 9/4 사고와 같은 모양
    t_frozen = {c: dict(v) for c, v in y.items()}
    w = SH.check_frozen_data(t_frozen, y)
    check(any(x.startswith("🔴") for x in w), "전 종목 주가가 그대로면 빨간불", f"({w})")
    check(any("#195" in x for x in w), "같은 모양이었던 실제 사고 번호를 남김")
    check("data_freshness" in Path(SH.__file__).read_text(encoding="utf-8"),
          "🔴 판정을 여기서 다시 구현하지 않고 공용 모듈을 부름 (§0-3-10)")

    # ③ 🟡 몇 종목만 움직임 — 휴장일이면 정상이므로 알림까지는 울리지 않습니다
    t_few = {c: dict(v) for c, v in y.items()}
    for c in list(y)[:3]:
        t_few[c]["price"] = y[c]["price"] + 100
    w3 = SH.check_frozen_data(t_few, y)
    check(w3 and w3[0].startswith("🟡"), "소수만 움직이면 노란불", f"({w3})")

    # ④ 어제 자료가 없거나 공통 종목이 너무 적으면 **판단하지 않습니다**
    #    (없는 것을 있는 척하지 않음 — §0-1. 그 사실은 check_change_sync 가 남깁니다)
    check(not SH.check_frozen_data(t_normal, {}), "어제 자료가 없으면 판단하지 않음")
    small = {f"{i:06d}": {"price": 10000 + i} for i in range(10)}
    check(not SH.check_frozen_data(small, small), "표본이 10종목뿐이면 판단하지 않음")


def test_frozen_data_warning_actually_reaches_the_alert(tmp_path):
    """
    검사가 경고를 **만들기만 하고 아무도 안 읽으면** 없는 것과 같습니다.
    (이 저장소에서 실제로 났던 실수 — `collect()` 가 경고를 버리고 있었습니다.)
    """
    report = {
        "matched_codes": 300,
        "fields": {"t_eps": {"label": "EPS", "match_ratio": 1.0}},
        "integrity_warnings": ["🔴 520개를 어제와 비교했는데 **하나도 바뀌지 않았습니다** (#195)"],
    }
    (tmp_path / "latest_compare.json").write_text(json.dumps(report), encoding="utf-8")
    with mock.patch.object(SH, "SHADOW_DIR", tmp_path):
        msg = SH.build_alert_message()
    check("하나도 바뀌지" in msg, "얼어붙은 데이터 경고가 알림 문구까지 도달", f"({msg})")


def test_compare_actually_runs_the_frozen_check(tmp_path):
    """
    🔴 **사보타주로 발견한 구멍입니다.** `compare_with_production` 에서
    `check_frozen_data(...)` 의 결과를 `integrity_warnings` 에 안 붙이고 버려도
    앞의 단위 테스트는 전부 통과했습니다 — 검사가 있는 것과 **불려서 읽히는 것**은
    다릅니다(이 저장소에서 `collect()` 가 경고를 버리던 실수와 같은 계열).

    그래서 여기서는 어제 파일까지 만들어 놓고 **대조 리포트 안에** 빨간불이
    실제로 들어오는지 봅니다.
    """
    rows = [{"code": f"{i:06d}", "price": 10000.0 + i, "outstanding_shares": 1000}
            for i in range(60)]
    yesterday = {"list_rows": rows}                      # 어제와 오늘이 **완전히 동일**
    today = {"list_rows": [dict(r) for r in rows]}

    (tmp_path / "2026-09-07_shadow.json").write_text(json.dumps(yesterday), encoding="utf-8")
    today_path = tmp_path / "2026-09-08_shadow.json"
    today_path.write_text(json.dumps(today), encoding="utf-8")

    fake_prod = tmp_path / "kospi200_pegy_latest.json"
    fake_prod.write_text(json.dumps({"stocks": [dict(r) for r in rows]}), encoding="utf-8")

    with mock.patch.object(SH, "SHADOW_DIR", tmp_path), \
         mock.patch.object(SH, "PRODUCTION_SNAPSHOT", fake_prod):
        rep = SH.compare_with_production(today, today_path=today_path)

    warns = rep["integrity_warnings"]
    check(any("하나도 바뀌지" in w and "#195" in w for w in warns),
          "얼어붙은 데이터 경고가 대조 리포트에 실제로 실림", f"({warns})")


def test_shadow_does_not_run_itself_automatically_after_the_cutover():
    """
    🔴 2026-09-08 (#222) — 실전이 **신 출처로 전환**된 뒤, 섀도의 자동 실행을 껐습니다.

    섀도의 임무는 "신 API 가 구 출처와 같은 값을 주는가"였습니다. 실전이 신 출처로 넘어간
    지금 섀도가 돌면 **같은 파서를 자기 자신과 대조**하는 것이라 얻는 정보가 0 인데,
    비용은 그대로 하루 약 1,066요청·45분입니다. 실전이 방금 같은 양을 보낸 직후에 이걸 또
    보내면 그날 네이버가 받는 요청이 **두 배**가 됩니다 — 얻는 것 없이(§0-3-2).

    오너 절대 원칙: *"상대방 서버에서 차단 당할 일을 절대로 만들 면 안된다."*
    하필 지금은 **차단당하면 대안이 없는 시점**입니다.

    🔻 이 검사가 없어서 생긴 일: 트리거를 지키는 검사가 **아예 없었습니다.** 그래서
       자동 실행을 꺼도 테스트가 하나도 안 울렸습니다. 이제는 되살릴 때 여기가 걸립니다.
    """
    import yaml as _yaml                                     # noqa: PLC0415
    path = REPO_ROOT / ".github" / "workflows" / "naver_api_shadow.yml"
    config = _yaml.safe_load(path.read_text(encoding="utf-8"))[True]

    check("workflow_run" not in config,
          "섀도가 수집 완료에 자동으로 딸려 돌지 않음 (이관 후에는 요청만 두 배)",
          f"({sorted(config)})")
    check("schedule" not in config,
          "섀도에 cron 도 없음 (혼자 조용히 매일 도는 일이 없게)")
    check("workflow_dispatch" in config,
          "수동 실행은 남아 있음 (문제 진단용)")

    text = path.read_text(encoding="utf-8")
    check("§0-3-2" in text and "통째로 지우세요" in text,
          "왜 껐는지와 언제 통째로 지울지가 파일에 적혀 있음")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
