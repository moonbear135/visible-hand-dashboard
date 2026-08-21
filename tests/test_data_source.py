# tests/test_data_source.py
"""
🌐 `utils/data_source.py` 검증 — 데이터 원격 로드(NICEGUI_MIGRATION_PLAN.md §8-5 "B안").

왜 이 검사가 필요한가
────────────────────────────────────────────────────────────────────────────
매일 커밋되는 `data/*.json` 때문에 Render 가 하루 2~3회 재배포되고, 그때마다
`app.storage.user`(NiceGUI 로그인 세션)가 날아가 **모든 사용자가 강제 로그아웃**됩니다.
이를 없애려고 데이터를 실행 중에 원격에서 읽어오도록 바꿨는데, 이 변경은 완성·검증이 끝난
화면 5개(pegy / us_stocks / scorecard / report / macro)를 **전부 가로지릅니다.**
그래서 두 가지를 반드시 자동으로 못 박아 둡니다.

  ① **기본값(환경변수 미설정)에서는 예전과 100% 동일하다** — 네트워크를 단 한 번도
     건드리지 않고, 실패 메시지도 글자 그대로 같아야 합니다. (배포만으로는 아무것도 안 바뀜)
  ② **실패를 조용히 덮지 않는다** (ENGINEERING_SPEC.md §0-1) — 캐시가 있으면 계속 서비스하되
     "최신이 아님 + 마지막 성공 시각"이 반드시 화면까지 도달해야 하고, 캐시도 로컬 사본도
     없으면 숫자를 그리지 않고 실패해야 합니다.

⚠️ 이 샌드박스에는 **인터넷이 없습니다.** 그래서 실제 `raw.githubusercontent.com` 왕복은
   검증할 수 없고, 여기서는 가짜 `requests`(성공 / 304 / 타임아웃 / 연결실패 / HTTP 오류)와
   가짜 시계로 **우리 코드의 분기**만 검증합니다. 실망 검증은 오너가 배포 후에 해야 합니다.

실행: python tests/test_data_source.py
"""

import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(REPO_ROOT / "tests"))

from utils import data_source                                          # noqa: E402

FAILURES = []


def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


# =============================================================================
# 가짜 부품 (네트워크·시계)
# =============================================================================
class FakeTimeout(Exception):
    """이름에 'timeout' 이 들어가는 예외 — requests.exceptions.ConnectTimeout 흉내."""


class FakeConnectionError(Exception):
    """연결 실패 흉내."""


class FakeResponse:
    """`requests.Response` 흉내.

    2026-08-17 — 본문 수신이 `stream=True` + `iter_content()` 방식으로 바뀌면서
    (응답 크기 상한 검사, 아래 [7] 참고) 이 가짜도 같은 모양을 갖춥니다.
    `content_length`/`content_type` 에 값을 주면 해당 헤더를 실제로 내려보냅니다
    (`content_length="auto"` 면 본문 길이를 그대로 씁니다).
    """

    def __init__(self, status_code, content=b"", etag=None,
                 content_type=None, content_length=None, chunk_size=None):
        self.status_code = status_code
        self.content = content
        self.headers = {}
        if etag:
            self.headers["ETag"] = etag
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = (
                str(len(content)) if content_length == "auto" else str(content_length)
            )
        self._chunk_size = chunk_size
        self.closed = False
        self.streamed_bytes = 0          # 실제로 메모리에 올린 양(상한 검사 검증용)

    def iter_content(self, chunk_size=None):
        size = self._chunk_size or chunk_size or 64 * 1024
        for start in range(0, len(self.content), size):
            piece = self.content[start:start + size]
            self.streamed_bytes += len(piece)
            yield piece

    def close(self):
        self.closed = True


class FakeRequests:
    """`requests` 모듈 흉내. 응답을 대본(script)으로 미리 넣어 두고 하나씩 꺼내 씁니다."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout,
                           "stream": stream})
        item = self.script.pop(0) if self.script else FakeResponse(500)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    """`time.monotonic()` 만 쓰므로 이것만 흉내 냅니다 (sleep 없이 TTL·백오프 검증)."""

    def __init__(self, start=1_000.0):
        self.t = start

    def monotonic(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class Sandbox:
    """임시 data/ 디렉터리 + 가짜 requests/시계를 꽂았다가 원상복구하는 도구."""

    def __init__(self, base_url=None, ttl=None):
        self.base_url = base_url
        self.ttl = ttl

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="vh_data_source_")
        self.saved_env = {k: os.environ.get(k) for k in
                          (data_source.ENV_BASE_URL, data_source.ENV_TTL_SECONDS,
                           data_source.ENV_TIMEOUT_SECONDS)}
        for key in self.saved_env:
            os.environ.pop(key, None)
        if self.base_url is not None:
            os.environ[data_source.ENV_BASE_URL] = self.base_url
        if self.ttl is not None:
            os.environ[data_source.ENV_TTL_SECONDS] = str(self.ttl)

        self.saved = (data_source.DATA_DIR, data_source.requests, data_source.time)
        data_source.DATA_DIR = self.dir
        self.clock = FakeClock()
        data_source.time = self.clock
        self.requests = FakeRequests()
        data_source.requests = self.requests
        data_source.reset_cache()
        return self

    def __exit__(self, *_a):
        (data_source.DATA_DIR, data_source.requests, data_source.time) = self.saved
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        data_source.reset_cache()
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    # ── 편의 함수 ────────────────────────────────────────────────────────────
    def path(self, name):
        return os.path.join(self.dir, name)

    def write_local(self, name, text):
        with open(self.path(name), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return self.path(name)

    def script(self, *items):
        self.requests.script = list(items)
        return self


# =============================================================================
# [1] 기본값(DATA_SOURCE_BASE_URL 미설정) — 예전과 100% 동일해야 합니다
# =============================================================================
def test_disabled_by_default():
    print("\n[1] DATA_SOURCE_BASE_URL 미설정 = 예전 그대로 (네트워크 0회)")

    with Sandbox() as box:
        path = box.write_local("kospi200_pegy_latest.json", '{"a": 1}')

        check(data_source.is_remote_enabled() is False,
              "환경변수가 없으면 원격 기능이 꺼져 있음")

        text, error, version = data_source.read_text(path)
        check(text == '{"a": 1}' and error is None, "로컬 파일 내용을 그대로 읽음")
        check(box.requests.calls == [], "네트워크 요청 0회 (인터넷 없이도 동작)",
              f"실제 호출: {box.requests.calls}")
        check(version is not None and version[0] == "local", "버전 키가 로컬(mtime+크기) 기반",
              f"version={version}")

        # 같은 버전을 다시 물으면 본문을 다시 만들지 않습니다 (2.2MB 재파싱 회피 경로).
        again_text, again_error, again_version = data_source.read_text(path, known_version=version)
        check(again_text is None and again_error is None and again_version == version,
              "내용이 그대로면 '변경 없음'을 알려 본문 재읽기를 건너뜀")

        # 없는 파일 — 실패 문구가 기존 web/state.py 와 **글자 그대로** 같아야 합니다.
        missing_text, missing_error, _ = data_source.read_text(box.path("nope.json"))
        check(missing_text is None and missing_error == "스냅샷 파일(nope.json)이 없습니다.",
              "없는 파일 실패 문구가 기존과 동일", f"실제: {missing_error!r}")

        check(data_source.get_staleness_status() is None,
              "원격이 꺼져 있으면 최신성 배너 상태가 없음(= 배너 안 뜸)")


def test_paths_outside_data_dir_stay_local():
    print("\n[1-b] `data/` 밖의 경로는 원격을 시도하지 않음 (테스트용 임시경로 보호)")
    with Sandbox(base_url="https://example.invalid/repo/main") as box:
        outside = os.path.join(tempfile.mkdtemp(prefix="vh_outside_"), "macro_commentary.json")
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        with open(outside, "w", encoding="utf-8") as f:
            f.write('{"comments": {}}')

        check(data_source.remote_relative_path(outside) is None,
              "data/ 밖 경로는 원격 대상이 아님")
        text, error, _ = data_source.read_text(outside)
        check(text == '{"comments": {}}' and error is None, "그 경로는 로컬 파일로 읽힘")
        check(box.requests.calls == [], "네트워크 요청 0회",
              f"실제 호출: {box.requests.calls}")

        inside = box.path("us_stocks_latest.json")
        check(data_source.remote_relative_path(inside) == "data/us_stocks_latest.json",
              "data/ 안 파일은 저장소 기준 상대경로로 변환됨")
        shutil.rmtree(os.path.dirname(outside), ignore_errors=True)


# =============================================================================
# [2] 원격 켬 — 성공 / TTL / ETag(304)
# =============================================================================
def test_remote_first_fetch_and_ttl():
    print("\n[2] 원격 켬 — 첫 fetch 성공 · TTL 캐시 · 조건부 GET(304)")
    base = "https://raw.githubusercontent.com/moonbear135/visible-hand-dashboard/main"
    with Sandbox(base_url=base, ttl=600) as box:
        box.write_local("us_summary_history.json", '{"source": "local"}')
        path = box.path("us_summary_history.json")
        box.script(FakeResponse(200, b'{"source": "remote"}', etag='"v1"'))

        text, error, version = data_source.read_text(path)
        check(text == '{"source": "remote"}' and error is None,
              "① 첫 fetch 성공 → 로컬 사본이 아니라 원격 내용을 씀")
        check(len(box.requests.calls) == 1, "네트워크 1회")
        check(box.requests.calls[0]["url"] == f"{base}/data/us_summary_history.json",
              "URL = base + 저장소 기준 상대경로", f"실제: {box.requests.calls[0]['url']}")
        check("User-Agent" in box.requests.calls[0]["headers"],
              "User-Agent 를 밝히고 요청 (§0-3-2 상대 서버 매너)")
        check("If-None-Match" not in box.requests.calls[0]["headers"],
              "첫 요청에는 If-None-Match 가 없음(가진 ETag 가 없으므로)")
        check(version[0] == "remote", "버전 키가 원격 리비전 기반", f"version={version}")

        # TTL(600초) 안 — 네트워크를 아예 타지 않아야 합니다.
        box.clock.advance(599)
        text2, error2, version2 = data_source.read_text(path)
        check(len(box.requests.calls) == 1, "② TTL 안에서는 네트워크 0회 (접속자 수와 무관)",
              f"호출 {len(box.requests.calls)}회")
        check(text2 == text and version2 == version and error2 is None, "   같은 내용·같은 버전")

        # TTL 경과 → 조건부 GET → 304 (본문 없음)
        box.clock.advance(2)
        box.script(FakeResponse(304))
        text3, error3, version3 = data_source.read_text(path)
        check(len(box.requests.calls) == 2, "③ TTL 이 지나면 다시 확인함")
        check(box.requests.calls[1]["headers"].get("If-None-Match") == '"v1"',
              "   If-None-Match 로 조건부 GET (304면 2.2MB 를 다시 받지 않음)")
        check(text3 == '{"source": "remote"}' and error3 is None and version3 == version,
              "   304 → 캐시 본문 그대로, 리비전 변화 없음")
        check(data_source.get_staleness_status() is None, "   정상이므로 배너 없음")

        # 내용이 실제로 바뀌면 리비전이 올라가 호출자의 파싱 캐시가 갱신됩니다.
        box.clock.advance(601)
        box.script(FakeResponse(200, b'{"source": "remote2"}', etag='"v2"'))
        text4, _e4, version4 = data_source.read_text(path, known_version=version3)
        check(text4 == '{"source": "remote2"}' and version4 != version3,
              "④ 내용이 바뀌면 버전이 달라져 재파싱을 유도함")

        box.clock.advance(601)
        box.script(FakeResponse(304))
        text5, error5, version5 = data_source.read_text(path, known_version=version4)
        check(text5 is None and error5 is None and version5 == version4,
              "⑤ 내용이 그대로면 '변경 없음'만 알려 재파싱을 건너뜀")


# =============================================================================
# [3] 실패 — 캐시가 있을 때 (§0-1: 계속 서비스하되 반드시 알린다)
# =============================================================================
def _first_success(box, base, filename="us_stocks_latest.json", body=b'{"n": 1}'):
    box.write_local(filename, '{"n": 0}')
    path = box.path(filename)
    box.script(FakeResponse(200, body, etag='"e1"'))
    text, error, version = data_source.read_text(path)
    assert error is None and text is not None, (text, error)
    return path, version


def test_failure_with_cache_shows_banner():
    print("\n[3] 원격 실패 + 캐시 있음 → 계속 서비스 + 전역 배너 (§0-1)")
    base = "https://example.invalid/main"
    for label, failure, expected_reason in (
        ("타임아웃", FakeTimeout("timed out"), "응답 시간 초과"),
        ("연결 실패", FakeConnectionError("no route"), "네트워크 연결 실패"),
        ("HTTP 404", FakeResponse(404), "서버 응답 코드 404"),
        ("HTTP 500", FakeResponse(500), "서버 응답 코드 500"),
    ):
        with Sandbox(base_url=base, ttl=600) as box:
            path, version = _first_success(box, base)
            check(data_source.get_staleness_status() is None, f"[{label}] 성공 직후에는 배너 없음")

            box.clock.advance(601)
            box.script(failure)
            text, error, _v = data_source.read_text(path)
            check(text == '{"n": 1}' and error is None,
                  f"[{label}] 실패해도 마지막 성공분으로 화면은 계속 그려짐")

            status = data_source.get_staleness_status()
            check(status is not None, f"[{label}] 최신성 배너 상태가 생김")
            if status:
                check(status["reason"] == expected_reason,
                      f"[{label}] 사유가 사람이 읽는 문구", f"실제: {status['reason']!r}")
                check(status["as_of_text"] is not None and "최신 데이터를 불러오지 못했습니다" in status["message"],
                      f"[{label}] 배너에 마지막 성공 시각이 들어감", f"실제: {status['message']!r}")
                check(status["local_fallback"] is False,
                      f"[{label}] 로컬 사본이 아니라 원격 캐시를 쓰는 중임을 구분")
                check("Traceback" not in status["message"]
                      and "example.invalid" not in status["message"]
                      and box.dir not in status["message"],
                      f"[{label}] 배너에 예외원문·URL·파일경로가 없음 (§0-3-4)")


def test_retry_backoff_and_recovery():
    print("\n[3-b] 실패 후 재시도 백오프 · 다음 성공 시 배너 자동 해제")
    base = "https://example.invalid/main"
    with Sandbox(base_url=base, ttl=600) as box:
        path, _version = _first_success(box, base)
        box.clock.advance(601)
        box.script(FakeTimeout("t"))
        data_source.read_text(path)
        calls_after_failure = len(box.requests.calls)

        # 실패 직후 여러 번 접속해도 매번 네트워크를 때리지 않습니다(백오프).
        for _ in range(5):
            box.clock.advance(1)
            data_source.read_text(path)
        check(len(box.requests.calls) == calls_after_failure,
              "실패 직후 백오프 동안에는 재시도하지 않음(접속마다 느려지지 않게)",
              f"호출 {len(box.requests.calls)} vs {calls_after_failure}")
        check(data_source.get_staleness_status() is not None, "그동안 배너는 계속 떠 있음")

        # 백오프가 끝나고 성공하면 상태가 스스로 풀립니다.
        box.clock.advance(data_source.RETRY_BACKOFF_SECONDS + 1)
        box.script(FakeResponse(200, b'{"n": 2}', etag='"e2"'))
        text, error, _v = data_source.read_text(path)
        check(text == '{"n": 2}' and error is None, "백오프 후 재시도 성공")
        check(data_source.get_staleness_status() is None,
              "다음 fetch 가 성공하면 배너 상태가 자동으로 사라짐")


# =============================================================================
# [4] 실패 — 캐시가 없을 때 (로컬 폴백 / 진짜 실패)
# =============================================================================
def test_cold_start_falls_back_to_local_copy():
    print("\n[4] 콜드스타트 실패 + 이미지에 함께 배포된 로컬 사본 → 폴백하되 배너를 띄움")
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        box.write_local("kr_ticker_master.json", '{"from": "image"}')
        path = box.path("kr_ticker_master.json")
        box.script(FakeTimeout("t"))

        text, error, version = data_source.read_text(path)
        check(text == '{"from": "image"}' and error is None,
              "원격을 한 번도 못 받았어도 로컬 사본으로 화면은 뜸")
        check(version is not None and version[0] == "local", "그때 버전 키는 로컬 기준")

        status = data_source.get_staleness_status()
        check(status is not None and status["local_fallback"] is True,
              "'배포에 함께 실린 사본'임을 구분해서 알림")
        if status:
            check("서버에 함께 배포된 사본" in status["message"],
                  "배너 문구가 사본임을 명시", f"실제: {status['message']!r}")


def test_cold_start_without_local_copy_is_a_real_failure():
    print("\n[4-b] 콜드스타트 실패 + 로컬 사본도 없음 → 진짜 실패 (숫자 그리지 않음)")
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        path = box.path("us_index_history.json")          # 파일을 만들지 않습니다
        box.script(FakeConnectionError("x"))

        text, error, version = data_source.read_text(path)
        check(text is None and version is None, "본문을 돌려주지 않음")
        check(error is not None and "내려받지 못했" in error and "사본도 없습니다" in error,
              "실패 사유가 사람이 읽는 한 문장", f"실제: {error!r}")
        check(error is not None and "Traceback" not in error and "example.invalid" not in error
              and box.dir not in error,
              "실패 사유에 예외원문·URL·파일경로가 없음 (§0-3-4)")
        check(data_source.get_staleness_status() is None,
              "보여줄 값이 아예 없을 때는 전역 '오래된 값' 배너를 겹쳐 띄우지 않음 "
              "(화면 자신의 빨간 실패 배너로 충분 — 없는 값을 '보이는 값'이라 말하지 않기)")


def test_cold_start_backoff_is_enforced():
    """🔴 2026-08-17 회귀 방지 — 원격이 **한 번도 성공한 적 없어도** 백오프가 걸려야 합니다.

    예전 `_read_remote()` 는 `entry['text'] is not None and not _needs_fetch(...)` 였습니다.
    그래서 URL 오타나 기동 시점부터의 장애처럼 성공 이력이 0인 상황에서는 백오프 검사가
    통째로 건너뛰어졌고(= `next_attempt` 를 아무도 읽지 않음), 페이지를 열 때마다 파일마다
    타임아웃(기본 8초)을 새로 기다렸습니다. "내 성적표"는 파일 6개를 읽으므로 한 번 열 때
    최악 48초가 멈출 수 있었습니다.
    """
    print("\n[4-c] 원격 성공 이력이 0이어도 백오프가 실제로 걸린다 (2026-08-17 수정)")
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        box.write_local("kospi200_pegy_latest.json", '{"from": "image"}')
        path = box.path("kospi200_pegy_latest.json")
        box.script(FakeTimeout("t"))

        for _ in range(10):                            # 페이지 10회 로드
            box.clock.advance(1)
            data_source.read_text(path)
        check(len(box.requests.calls) == 1,
              "캐시된 본문이 한 번도 없어도 10회 로드에 HTTP 요청은 1회뿐(백오프 적용)",
              f"실제 {len(box.requests.calls)}회")

        text, error, _v = data_source.read_text(path)
        check(text == '{"from": "image"}' and error is None,
              "백오프 중에는 네트워크를 건드리지 않고 로컬 사본으로 화면을 띄움")
        check(data_source.get_staleness_status() is not None,
              "그동안 배너는 계속 떠 있음 (§0-1 — 사본임을 감추지 않음)")

        box.clock.advance(data_source.RETRY_BACKOFF_SECONDS + 1)
        box.script(FakeTimeout("t"))
        data_source.read_text(path)
        check(len(box.requests.calls) == 2,
              "백오프가 끝나면 다시 시도함(영구 차단이 아님)",
              f"실제 {len(box.requests.calls)}회")


# =============================================================================
# [5] 부가 규칙 — 줄바꿈 정규화 · 설정 오타
# =============================================================================
def test_newlines_are_normalised_like_local_read():
    print("\n[5] 원격 CRLF → LF 정규화 (다운로드 바이트가 로컬 경로와 같아야 함)")
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        box.write_local("pegy_summary_history.json", "[]")
        path = box.path("pegy_summary_history.json")
        box.script(FakeResponse(200, b'{\r\n  "a": 1\r\n}', etag='"e"'))
        text, error, _v = data_source.read_text(path)
        check(error is None and "\r" not in (text or ""),
              "원격 본문의 CRLF 가 LF 로 바뀜 (파이썬 텍스트 모드와 동일)")
        check(text == '{\n  "a": 1\n}', "내용은 줄바꿈 문자만 다르고 동일", f"실제: {text!r}")


def test_misconfigured_base_url_is_visible():
    print("\n[5-b] DATA_SOURCE_BASE_URL 오타 → 조용히 넘어가지 않고 배너로 알림 (§0-1)")
    with Sandbox(base_url="raw.githubusercontent.com/moonbear135/x/main", ttl=600) as box:
        box.write_local("kospi200_pegy_latest.json", '{"local": true}')
        path = box.path("kospi200_pegy_latest.json")

        text, error, _v = data_source.read_text(path)
        check(text == '{"local": true}' and error is None,
              "설정이 잘못돼도 서비스는 로컬 사본으로 계속 뜸")
        check(box.requests.calls == [], "잘못된 주소로 요청을 보내지 않음")
        status = data_source.get_staleness_status()
        check(status is not None and status.get("config_error") is True,
              "설정 오류가 배너 상태로 노출됨")
        if status:
            check("http" in status["message"], "배너가 무엇을 고쳐야 하는지 알려줌",
                  f"실제: {status['message']!r}")

        # 오너가 값을 고치면 배너도 사라져야 합니다.
        os.environ[data_source.ENV_BASE_URL] = "https://example.invalid/main"
        box.script(FakeResponse(200, b'{"remote": true}', etag='"e"'))
        data_source.read_text(path)
        check(data_source.get_staleness_status() is None, "값을 고치면 설정오류 배너가 사라짐")


# =============================================================================
# [6] web/state.py 통합 — 화면 5개가 실제로 쓰는 함수 2개
# =============================================================================
def _reload_state():
    import web.state as state
    state._JSON_CACHE.clear()
    return state


def test_web_state_integration():
    print("\n[6] web/state.py 통합 — load_json_file / read_download_bytes")
    _install_stub()
    state = _reload_state()
    saved_state_dir = state.DATA_DIR

    # ① 원격 성공 → 화면이 원격 payload 를 받음
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        state.DATA_DIR = box.dir
        state._JSON_CACHE.clear()
        box.write_local("us_stocks_latest.json", json.dumps({"stocks": [], "src": "image"}))
        box.script(FakeResponse(200, json.dumps({"stocks": [1], "src": "remote"}).encode(), etag='"e1"'))

        payload, error = state.load_json_file(state.data_path("us_stocks_latest.json"))
        check(error is None and payload == {"stocks": [1], "src": "remote"},
              "① 첫 fetch 성공 → 화면이 원격 스냅샷을 받음", f"실제: {payload}, {error}")

        # 같은 내용이면 재파싱하지 않고 **같은 객체**를 돌려줍니다.
        first_id = id(payload)
        box.clock.advance(601)
        box.script(FakeResponse(304))
        payload2, error2 = state.load_json_file(state.data_path("us_stocks_latest.json"))
        check(error2 is None and id(payload2) == first_id,
              "   내용이 그대로면 2.2MB JSON 을 다시 파싱하지 않음(같은 객체 재사용)")

        # 다운로드도 같은 경로를 씁니다 — 사본이 아니라 원격 내용이 나가야 합니다.
        blob = state.read_download_bytes(state.data_path("us_stocks_latest.json"))
        check(blob == json.dumps({"stocks": [1], "src": "remote"}).encode("utf-8"),
              "   다운로드 버튼도 화면과 같은(원격) 내용을 내려줌", f"실제: {blob!r}")

        # ② 이후 fetch 실패 + 캐시 있음 → 화면은 계속 그려지고 배너 상태가 생김
        box.clock.advance(601)
        box.script(FakeTimeout("t"))
        payload3, error3 = state.load_json_file(state.data_path("us_stocks_latest.json"))
        check(error3 is None and payload3 == {"stocks": [1], "src": "remote"},
              "② 이후 fetch 실패 + 캐시 있음 → 화면은 그대로 렌더됨")
        check(data_source.get_staleness_status() is not None,
              "   그리고 전역 배너 상태가 켜짐 (§0-1)")

    # ③ 캐시도 없고 원격도 실패하고 로컬 사본도 없음 → 기존과 같은 '진짜 실패'
    with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
        state.DATA_DIR = box.dir
        state._JSON_CACHE.clear()
        box.script(FakeConnectionError("x"))
        payload, error = state.load_json_file(state.data_path("us_stocks_latest.json"))
        check(payload is None and error is not None,
              "③ 캐시·로컬 둘 다 없으면 (None, 사유) — 화면은 빨간 배너만 띄움")
        check(state.read_download_bytes(state.data_path("us_stocks_latest.json")) is None,
              "   그 상태에서 다운로드도 None (가짜 파일을 만들지 않음)")

    # ④ 원격 미설정(기본) → 예전과 똑같이 로컬 파일만
    with Sandbox() as box:
        state.DATA_DIR = box.dir
        state._JSON_CACHE.clear()
        box.write_local("kospi200_pegy_latest.json", json.dumps({"metadata": {}, "stocks": []}))
        payload, error = state.load_json_file(state.data_path("kospi200_pegy_latest.json"))
        check(error is None and payload == {"metadata": {}, "stocks": []},
              "④ 환경변수 미설정 → 로컬 파일 그대로")
        check(box.requests.calls == [], "   네트워크 0회")
        missing_payload, missing_error = state.load_json_file(state.data_path("없는파일.json"))
        check(missing_payload is None and missing_error == "스냅샷 파일(없는파일.json)이 없습니다.",
              "   실패 문구도 예전과 글자 그대로 동일", f"실제: {missing_error!r}")

    state.DATA_DIR = saved_state_dir
    state._JSON_CACHE.clear()


# =============================================================================
# [7] web/layout.py 전역 배너 — 화면 5개에 복붙하지 않고 한 곳에서 (§0-3-10)
# =============================================================================
def _install_stub():
    """`tests/test_web_session_isolation.py` 의 nicegui 스텁을 재사용합니다 (§0-3-10 중복 금지)."""
    from test_web_session_isolation import _install_nicegui_stub
    return _install_nicegui_stub()


def test_layout_global_banner():
    print("\n[7] web/layout.py 전역 배너 (모든 페이지 공통 · 화면 파일 무변경)")
    _install_stub()
    import web.layout as layout

    source = (REPO_ROOT / "web" / "layout.py").read_text(encoding="utf-8")
    check("get_staleness_status" in source, "layout.py 가 최신성 상태를 직접 조회함")
    for page in ("pegy_page", "us_stocks_page", "scorecard_page", "report_page", "macro_page"):
        page_source = (REPO_ROOT / "web" / "pages" / f"{page}.py").read_text(encoding="utf-8")
        check("get_staleness_status" not in page_source,
              f"   {page}.py 에는 같은 코드가 복붙되지 않음")

    drawn = []
    saved = layout.error_banner
    layout.error_banner = lambda text: drawn.append(text)
    try:
        # ① 정상 상태 → 배너 0개
        with Sandbox(base_url="https://example.invalid/main", ttl=600) as box:
            box.write_local("us_summary_history.json", "[]")
            path = box.path("us_summary_history.json")
            box.script(FakeResponse(200, b"[]", etag='"e"'))
            with layout.layout("테스트"):
                data_source.read_text(path)
            check(drawn == [], "① 정상일 때는 배너를 그리지 않음", f"실제: {drawn}")

            # ② 본문을 그리는 도중에 실패가 확정돼도 **같은 렌더에서** 배너가 뜹니다.
            drawn.clear()
            box.clock.advance(601)
            box.script(FakeTimeout("t"))
            with layout.layout("테스트"):
                data_source.read_text(path)          # 본문이 데이터를 읽다가 실패하는 순간
            check(len(drawn) == 1, "② 본문 렌더 중 실패 → 같은 화면에 배너 1개", f"실제: {drawn}")
            if drawn:
                check("최신 데이터를 불러오지 못했습니다" in drawn[0]
                      and "지금 보이는 값은" in drawn[0],
                      "   문구가 계획서 §8-5 요구사항과 일치", f"실제: {drawn[0]!r}")

            # ③ 다음 fetch 가 성공하면 배너가 사라집니다.
            drawn.clear()
            box.clock.advance(data_source.RETRY_BACKOFF_SECONDS + 1)
            box.script(FakeResponse(200, b"[1]", etag='"e2"'))
            with layout.layout("테스트"):
                data_source.read_text(path)
            check(drawn == [], "③ 다음 성공 fetch 후에는 배너가 사라짐", f"실제: {drawn}")

        # ④ 원격 미설정(기본값)에서는 어떤 경우에도 배너가 없습니다.
        drawn.clear()
        with Sandbox() as box:
            with layout.layout("테스트"):
                pass
            check(drawn == [], "④ DATA_SOURCE_BASE_URL 미설정 → 배너 없음(기존 화면과 동일)")
    finally:
        layout.error_banner = saved


# =============================================================================
# [8] 원격 응답 방어선 — 크기 상한 · 형식 확인 (2026-08-17 추가)
#
#  왜: 예전에는 `response.content` 를 무조건 통째로 메모리에 올렸습니다. Render 무료
#  인스턴스는 512MB 뿐이라 비정상적으로 큰 응답 하나로 프로세스가 죽을 수 있고,
#  HTML 에러/로그인 페이지가 데이터인 척 캐시에 들어갈 수도 있었습니다.
#  어떤 차단이든 **기존 실패 경로**(백오프 + 캐시/로컬 사본 폴백 + 전역 배너)를 그대로
#  타야 합니다 — 조용히 넘어가면 §0-1 위반입니다.
# =============================================================================
def test_response_size_and_type_guards():
    print("\n[8] 원격 응답 크기 상한 · 형식 확인")
    base = "https://example.invalid/main"

    # ① Content-Length 사전 차단 — 본문을 한 바이트도 받지 않습니다.
    with Sandbox(base_url=base, ttl=600) as box:
        box.write_local("us_stocks_latest.json", '{"from": "image"}')
        path = box.path("us_stocks_latest.json")
        huge = FakeResponse(200, b'{"n": 1}', content_type="text/plain",
                            content_length=data_source.MAX_RESPONSE_BYTES + 1)
        box.script(huge)
        text, error, _v = data_source.read_text(path)
        check(huge.streamed_bytes == 0,
              "① Content-Length 가 상한을 넘으면 본문 수신 자체를 하지 않음",
              f"실제로 받은 바이트: {huge.streamed_bytes}")
        check(huge.closed is True, "   열어둔 연결(stream=True)을 반드시 닫음")
        check(text == '{"from": "image"}' and error is None,
              "   기존 실패 경로 그대로 — 로컬 사본으로 폴백")
        status = data_source.get_staleness_status()
        check(status is not None and "너무 큼" in (status["reason"] or ""),
              "   배너에 사람이 읽는 사유가 뜸", f"실제: {status}")
        check(status is not None and "Content-Length" not in status["message"]
              and "example.invalid" not in status["message"],
              "   배너 문구에 헤더 값·URL 이 없음 (§0-3-4)")

    # ② Content-Length 가 없어도(청크 전송) 수신 도중에 상한을 넘으면 즉시 중단.
    #    20MB 짜리 가짜 본문을 만들지 않기 위해 상한만 잠시 낮춰서 확인합니다.
    with Sandbox(base_url=base, ttl=600) as box:
        box.write_local("us_stocks_latest.json", '{"from": "image"}')
        path = box.path("us_stocks_latest.json")
        saved_limit = data_source.MAX_RESPONSE_BYTES
        data_source.MAX_RESPONSE_BYTES = 100
        try:
            oversized = FakeResponse(200, b"x" * 5_000, content_type="text/plain", chunk_size=64)
            box.script(oversized)
            text, error, _v = data_source.read_text(path)
            check(oversized.streamed_bytes <= 100 + 64,
                  "② Content-Length 가 없어도 상한을 넘는 순간 수신 중단(전체를 메모리에 안 올림)",
                  f"실제로 받은 바이트: {oversized.streamed_bytes} / 전체 5000")
            check(text == '{"from": "image"}' and error is None,
                  "   그 경우에도 로컬 사본으로 폴백")
        finally:
            data_source.MAX_RESPONSE_BYTES = saved_limit

    # ③ HTML 응답(로그인/에러 페이지)이 데이터인 척 캐시에 들어가지 않습니다.
    with Sandbox(base_url=base, ttl=600) as box:
        box.write_local("us_stocks_latest.json", '{"from": "image"}')
        path = box.path("us_stocks_latest.json")
        html = FakeResponse(200, b"<html><body>Sign in</body></html>",
                            content_type="text/html; charset=utf-8")
        box.script(html)
        text, error, _v = data_source.read_text(path)
        check(html.streamed_bytes == 0, "③ HTML 응답은 본문을 받지도 않음")
        check(text == '{"from": "image"}' and error is None,
              "   HTML 이 데이터인 척 캐시에 들어가지 않고 사본으로 폴백")
        status = data_source.get_staleness_status()
        check(status is not None and "형식" in (status["reason"] or ""),
              "   배너에 형식 문제라고 표시", f"실제: {status}")

    # ④ 정상 응답(text/plain)은 그대로 통과 — 방어선이 정상 데이터를 막으면 안 됩니다.
    with Sandbox(base_url=base, ttl=600) as box:
        path = box.path("us_stocks_latest.json")
        box.script(FakeResponse(200, b'{"n": 7}', etag='"e"',
                                content_type="text/plain; charset=utf-8", content_length="auto"))
        text, error, _v = data_source.read_text(path)
        check(text == '{"n": 7}' and error is None, "④ 정상 응답(text/plain)은 그대로 통과")
        check(box.requests.calls[0]["stream"] is True,
              "   stream=True 로 요청해 헤더를 먼저 확인함")
        check(data_source.get_staleness_status() is None, "   배너 없음")

    # ⑤ Content-Type 헤더가 아예 없으면 형식으로 막지 않습니다(§0-1 — 없는 정보로 판단 금지).
    with Sandbox(base_url=base, ttl=600) as box:
        path = box.path("us_stocks_latest.json")
        box.script(FakeResponse(200, b'{"n": 8}', etag='"e"'))
        text, error, _v = data_source.read_text(path)
        check(text == '{"n": 8}' and error is None,
              "⑤ Content-Type 헤더가 없으면 형식 검사로 막지 않음")


# =============================================================================
# [9] `data_source` 를 우회하던 파일 4개 (2026-08-17 수정)
#
#  문제였던 것: 아래 4개는 `open()` 으로 직접 읽혀 최신성 추적 밖에 있었습니다. 원격 로드가
#  켜지고 Render Build Filters 로 데이터 커밋이 재배포를 부르지 않게 되면 **배포 시점에
#  얼어붙은 사본**을 계속 보여주면서도 `web/layout.py` 의 전역 배너가 뜨지 않았습니다(§0-1).
#
#    · market_history.csv               (사장님 보고서 한국 벤치마크)
#    · data/us_index_history.json       (사장님 보고서 미국 벤치마크)
#    · data/kospi200_stock_history.csv  (pegy 종목별 다운로드)
#    · data/us_stocks_history.csv       (us_stocks 종목별 다운로드)
# =============================================================================
def test_bypass_files_go_through_data_source():
    print("\n[9] 우회하던 데이터 파일 4개가 data_source 를 거치는지")

    import utils.report_db as report_db
    import utils.stock_history as stock_history

    kr_history = stock_history.stock_history_path(stock_history.KOSPI_HISTORY_FILENAME)
    us_history = stock_history.stock_history_path(stock_history.US_HISTORY_FILENAME)

    def _load_all():
        return (
            report_db.load_kospi_close_history(),
            report_db.load_us_index_closes(),
            stock_history.load_stock_history(kr_history, stock_history.KOSPI_KEY_FIELD, "005930"),
            stock_history.load_stock_history(us_history, stock_history.US_KEY_FIELD, "AAPL"),
        )

    saved_env = os.environ.get(data_source.ENV_BASE_URL)
    saved_requests = data_source.requests
    try:
        # ① 기본값(원격 꺼짐) — 저장소의 실제 파일을 예전과 똑같이 읽습니다.
        os.environ.pop(data_source.ENV_BASE_URL, None)
        data_source.reset_cache()
        baseline = _load_all()
        check(len(baseline[0]) > 0 and len(baseline[1]) > 0,
              "① 원격이 꺼져 있으면 저장소의 실제 벤치마크 파일을 그대로 읽음",
              f"코스피 {len(baseline[0])}일 / 미국 {sorted(baseline[1])}")
        check(data_source.get_staleness_status() is None, "   배너 없음(예전과 동일)")

        # ② 원격을 켜고 전부 실패시키면 → 로컬 사본으로 폴백하되 **배너에 4개가 다 잡혀야** 합니다.
        class _AlwaysFails:
            @staticmethod
            def get(url, headers=None, timeout=None, stream=False):
                raise FakeTimeout("synthetic")

        data_source.requests = _AlwaysFails
        os.environ[data_source.ENV_BASE_URL] = "https://example.invalid/main"
        data_source.reset_cache()
        fallback = _load_all()
        check(fallback == baseline,
              "② 원격 실패 시 로컬 사본으로 폴백 — 값은 원격 꺼짐일 때와 동일")

        status = data_source.get_staleness_status()
        files = set((status or {}).get("files") or [])
        expected = {
            "market_history.csv",
            "data/us_index_history.json",
            "data/kospi200_stock_history.csv",
            "data/us_stocks_history.csv",
        }
        check(expected <= files,
              "   4개 파일이 모두 최신성 추적(전역 배너) 대상에 들어옴",
              f"빠진 파일: {sorted(expected - files)}")
    finally:
        data_source.requests = saved_requests
        if saved_env is None:
            os.environ.pop(data_source.ENV_BASE_URL, None)
        else:
            os.environ[data_source.ENV_BASE_URL] = saved_env
        data_source.reset_cache()

    # ③ 소스 수준 회귀 방지 — 그 읽기 함수들이 다시 `open()` 으로 돌아가지 않도록.
    report_src = (REPO_ROOT / "utils" / "report_db.py").read_text(encoding="utf-8")
    history_src = (REPO_ROOT / "utils" / "stock_history.py").read_text(encoding="utf-8")
    check("from utils import data_source" in report_src
          and "data_source.read_text(path" in report_src,
          "③ utils/report_db.py 가 data_source.read_text 를 씀")
    check("from utils import data_source" in history_src
          and "data_source.read_text(path" in history_src,
          "   utils/stock_history.py 가 data_source.read_text 를 씀")
    check("io.StringIO(text" in history_src,
          "   파일 전체를 리스트로 펼치지 않고 한 줄씩 훑는 설계를 유지 "
          "(이력이 몇 년 쌓이면 수십 MB)")
    # 기록(write) 경로는 그대로 로컬 파일이어야 합니다 — 원격은 읽기 전용입니다.
    check('open(path, "w"' in history_src,
          "   기록 경로는 예전 그대로 로컬 파일에 직접 씀(원격 전환하지 않음)")


# =============================================================================
# [9] 🔴 화면이 데이터를 읽는 동안 **이벤트 루프가 멈추지 않는가** (2026-08-21 추가)
#
#     무슨 사고를 막는 검사인가
#     ─────────────────────────────────────────────────────────────────────────
#     운영에서 "연결이 끊겼습니다. 다시 연결 중…" 토스트가 모든 기기에서 반복됐습니다.
#     원인은 `@ui.page` 본문이 `web/state.load_json_file()` 을 **그대로(동기로)** 부른
#     것이었습니다. 원격 모드(`DATA_SOURCE_BASE_URL` 설정)에서 캐시 TTL 이 지나면 그 안에서
#     `requests.get()` 이 도는데, NiceGUI 는 한 프로세스·한 이벤트 루프가 모든 접속자를
#     처리하므로 그 몇 초 동안 **접속자 전원의 WebSocket 하트비트**가 함께 멈춥니다.
#
#     그래서 "고쳤다"의 내용은 딱 하나입니다 — 그 블로킹 호출이 **이벤트 루프가 아닌 곳**
#     에서 돌아야 합니다. 아래 검사는 그 사실 자체를 못 박습니다(사람이 한 번 확인하고
#     끝내면 다음 사람이 조용히 되돌릴 수 있는 종류의 수정이라, 반드시 테스트로 고정합니다).
# =============================================================================
#
# 동기판 `load_json_file()` 을 그대로 써도 되는 예외 자리 — **사유를 함께 적으세요.**
# (여기 없는데 화면 파일이 동기판을 부르면 아래 검사가 실패합니다.)
SYNC_LOAD_ALLOWED = {
    ("web/pages/pegy_page.py", "_snapshot_csv_bytes"):
        "화면을 그릴 때가 아니라 다운로드 버튼을 눌렀을 때 실행되고, 그 클릭 처리기"
        "(`web/components/widgets.download_button`)가 이미 `run.io_bound` 로 별도 스레드에서 "
        "돌려 줍니다. 즉 이 함수는 애초에 이벤트 루프 위에서 실행되지 않습니다.",
}

PAGE_FILES = ("pegy_page.py", "us_stocks_page.py", "scorecard_page.py",
              "report_page.py", "macro_page.py", "duel_page.py")


def test_pages_never_block_the_event_loop():
    print("\n[9] 화면 데이터 로드가 이벤트 루프를 막지 않음 (2026-08-21 '연결 끊김' 회귀 방지)")
    import ast
    import asyncio
    import inspect
    import threading
    import time as real_time

    stubbed = _install_stub()
    state = _reload_state()
    from nicegui import run as nicegui_run                              # noqa: PLC0415

    # ── ① 비동기 판이 존재하고, 동기 판도 그대로 남아 있는가 ──────────────────
    #    (동기 판은 배치 스크립트·테스트가 계속 쓰고, 비동기 판의 알맹이이기도 합니다.)
    check(inspect.iscoroutinefunction(state.load_json_file_async),
          "① web/state.load_json_file_async() 가 코루틴 함수")
    check(callable(state.load_json_file) and not inspect.iscoroutinefunction(state.load_json_file),
          "   동기판 load_json_file() 은 그대로 남아 있음(다른 호출자·배치용)")
    check([p.name for p in inspect.signature(state.load_json_file_async).parameters.values()]
          == ["path"],
          "   두 함수의 인자가 같음(path 하나) — 호출부는 await 만 붙이면 됨")

    # ── ② 정말 `run.io_bound` 에 넘기는가 (직접 부르지 않는가) ────────────────
    #    이 검사가 이번 수정의 핵심입니다. 감시자를 끼워 넣어 "무엇을 넘겼는지"까지 봅니다.
    handed_over = []
    saved_io_bound = nicegui_run.io_bound

    async def _spy_io_bound(fn, *args, **kwargs):
        handed_over.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    nicegui_run.io_bound = _spy_io_bound
    try:
        with Sandbox() as box:                       # 원격 미설정 = 로컬 파일만 (네트워크 0회)
            saved_dir = state.DATA_DIR
            state.DATA_DIR = box.dir
            state._JSON_CACHE.clear()
            box.write_local("io_bound_probe.json", json.dumps({"probe": 1}))
            probe_path = state.data_path("io_bound_probe.json")
            payload, error = asyncio.run(state.load_json_file_async(probe_path))
            state.DATA_DIR = saved_dir
            state._JSON_CACHE.clear()
    finally:
        nicegui_run.io_bound = saved_io_bound

    check(len(handed_over) == 1,
          "② load_json_file_async() 가 run.io_bound 를 정확히 한 번 씀",
          f"실제 호출 {len(handed_over)}회 ← 0회면 블로킹 호출이 이벤트 루프로 되돌아온 것입니다.")
    if handed_over:
        fn, args, kwargs = handed_over[0]
        check(fn is state.load_json_file and args == (probe_path,) and not kwargs,
              "   넘긴 것이 동기판 load_json_file(path) 그대로",
              f"실제: {getattr(fn, '__name__', fn)} args={args} kwargs={kwargs}")
    check(payload == {"probe": 1} and error is None,
          "   반환값은 동기판과 글자 그대로 같음 (성공/실패 규약 불변)",
          f"실제: {payload!r} / {error!r}")

    # ── ③ 취소·종료 중(run.io_bound → None)에도 화면에 값을 지어내지 않는가 ──
    async def _cancelled_io_bound(_fn, *_a, **_k):
        return None                                  # NiceGUI 3.x 의 취소/종료 시 규약

    nicegui_run.io_bound = _cancelled_io_bound
    try:
        payload_none, error_none = asyncio.run(state.load_json_file_async("아무경로.json"))
    finally:
        nicegui_run.io_bound = saved_io_bound
    check(payload_none is None and isinstance(error_none, str) and error_none,
          "③ run.io_bound 가 None 을 돌려줘도 (None, 사람이 읽는 사유) 로 정직하게 실패 (§0-1)",
          f"실제: {payload_none!r} / {error_none!r}")
    check("Traceback" not in (error_none or "") and "None" not in (error_none or ""),
          "   그 문구에 파이썬 내부 사정이 새지 않음 (§0-3-4)", f"실제: {error_none!r}")

    # ── ④ 실제로 **다른 스레드**에서 돌고, 그 동안 루프가 계속 돌아가는가 ─────
    #    (진짜 nicegui 가 있을 때만 — 오프라인 스텁의 io_bound 는 그냥 동기 호출입니다.)
    if stubbed:
        print("   ⏭️ 실제 nicegui 가 없어 스레드 분리 검증은 건너뜁니다(스텁 io_bound 는 동기 호출).")
    else:
        worker_threads = []
        saved_sync_loader = state.load_json_file

        def _slow_loader(_path):
            worker_threads.append(threading.current_thread())
            real_time.sleep(0.20)                    # 원격 왕복 흉내 (블로킹)
            return {"slow": True}, None

        async def _scenario():
            ticks = [0]

            async def _heartbeat():
                while True:                          # WebSocket 하트비트 흉내
                    await asyncio.sleep(0.01)
                    ticks[0] += 1

            beat = asyncio.create_task(_heartbeat())
            try:
                result = await state.load_json_file_async("무시되는 경로.json")
            finally:
                beat.cancel()
            return result, ticks[0], threading.current_thread()

        state.load_json_file = _slow_loader
        try:
            (slow_payload, slow_error), ticks, loop_thread = asyncio.run(_scenario())
        finally:
            state.load_json_file = saved_sync_loader

        check(slow_payload == {"slow": True} and slow_error is None,
              "④ 느린 로더의 결과가 그대로 돌아옴")
        check(len(worker_threads) == 1 and worker_threads[0] is not loop_thread,
              "   블로킹 구간이 **이벤트 루프 스레드가 아닌 곳**에서 실행됨",
              f"실제: 작업 스레드={[t.name for t in worker_threads]} / 루프 스레드={loop_thread.name}")
        check(ticks >= 5,
              "   그 0.2초 동안 이벤트 루프가 계속 돌았음(= 다른 접속자 하트비트가 살아 있음)",
              f"실제 진행 횟수: {ticks} ← 0 이면 루프가 통째로 멈춘 것입니다(사고 재발).")

    # ── ⑤ 소스 수준 회귀 방지 — 화면 6개가 다시 동기 호출로 돌아가지 않도록 ──
    for filename in PAGE_FILES:
        path = REPO_ROOT / "web" / "pages" / filename
        rel_name = f"web/pages/{filename}"
        if not path.exists():
            check(False, f"⑤ {rel_name} 존재")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))

        owner = {}
        for func in [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for sub in ast.walk(func):
                owner[id(sub)] = func

        # (a) `@ui.page` 함수는 전부 `async def` 여야 합니다. 동기로 되돌리는 순간
        #     그 안의 모든 로드가 다시 이벤트 루프 위에서 돌게 됩니다.
        pages = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and any(isinstance(d, ast.Call) and getattr(d.func, "attr", None) == "page"
                         for d in n.decorator_list)]
        check(bool(pages), f"⑤ {rel_name} 에 @ui.page 함수가 있음")
        for node in pages:
            check(isinstance(node, ast.AsyncFunctionDef),
                  f"   {rel_name}::{node.name}() 이 async def",
                  "← 동기로 되돌리면 데이터 로드가 다시 이벤트 루프를 막습니다.")

        # (b) 동기판 `load_json_file(` 호출은 위 화이트리스트에 적힌 자리에만 있어야 합니다.
        for call in [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "load_json_file"]:
            holder = owner.get(id(call))
            holder_name = holder.name if holder else "<모듈 최상위>"
            check((rel_name, holder_name) in SYNC_LOAD_ALLOWED,
                  f"   {rel_name}::{holder_name}() 의 동기 load_json_file() 호출이 허용 목록에 있음",
                  "← 화면 코드는 load_json_file_async() 를 await 하세요. 정말 예외라면 "
                  "SYNC_LOAD_ALLOWED 에 **사유와 함께** 추가하세요.")

    # ── ⑥ 다운로드 버튼도 같은 처방을 받았는가 ────────────────────────────────
    widgets_src = (REPO_ROOT / "web" / "components" / "widgets.py").read_text(encoding="utf-8")
    check("from nicegui import run" in widgets_src and "await run.io_bound(" in widgets_src
          and "async def _click" in widgets_src,
          "⑥ download_button 의 클릭 처리기도 run.io_bound 로 파일을 만듦",
          "← 원격 모드에서 read_download_bytes() 가 requests.get() 을 타고, "
          "관리자 CSV 변환은 4MB 를 pandas 로 돌립니다. 둘 다 이벤트 루프 밖이어야 합니다.")


# =============================================================================
def main():
    print("=" * 74)
    print("🌐 데이터 원격 로드 검증 (NICEGUI_MIGRATION_PLAN.md §8-5 · ENGINEERING_SPEC §0-1)")
    print("=" * 74)

    test_disabled_by_default()
    test_paths_outside_data_dir_stay_local()
    test_remote_first_fetch_and_ttl()
    test_failure_with_cache_shows_banner()
    test_retry_backoff_and_recovery()
    test_cold_start_falls_back_to_local_copy()
    test_cold_start_without_local_copy_is_a_real_failure()
    test_cold_start_backoff_is_enforced()
    test_newlines_are_normalised_like_local_read()
    test_misconfigured_base_url_is_visible()
    test_web_state_integration()
    test_layout_global_banner()
    test_response_size_and_type_guards()
    test_bypass_files_go_through_data_source()
    test_pages_never_block_the_event_loop()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과 — 기본값에서는 예전과 동일하고, 원격 실패는 반드시 화면까지 도달합니다.")
    print("   ⚠️ 실제 raw.githubusercontent.com 왕복은 이 샌드박스(인터넷 없음)에서 검증 불가.")
    print("=" * 74)


if __name__ == "__main__":
    main()
