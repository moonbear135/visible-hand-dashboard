"""
🌐 시장 데이터 원격 로더 (NICEGUI_MIGRATION_PLAN.md §8-5 "B안").

왜 만들었나
────────────────────────────────────────────────────────────────────────────
GitHub Actions 워크플로우 3개(`scrape.yml`·`scrape_us.yml`·`scrape_report_snapshots.yml`)가
매일 2~3회 `data/*.json` 을 저장소 `main` 에 커밋합니다. Render 는 `main` 에 커밋이 올라오면
기본적으로 **자동 재배포**하고, 재배포 = 새 컨테이너 = `app.storage.user`(NiceGUI 로그인
세션이 들어있는 휘발성 디스크) 초기화 = **"내 성적표"·"사장님 보고서"에 로그인해 둔 모든
사용자가 강제 로그아웃**됩니다 (계획서 §11-2 위험표 4번째 행).

그래서 데이터를 **이미지에 굽지 않고 실행 중에 원격에서 읽어옵니다.** 그러면 데이터 커밋이
재배포를 부르지 않아도 되고(오너가 Render 대시보드에서 Build Filters 로 `data/**` 를 무시
설정), 로그인이 유지됩니다.

⚠️ 기본값은 "아무것도 바뀌지 않음"입니다
────────────────────────────────────────────────────────────────────────────
환경변수 `DATA_SOURCE_BASE_URL` 이 **비어 있으면 이 모듈은 네트워크를 단 한 번도 건드리지
않고**, 예전과 글자 그대로 같은 로컬 파일 읽기를 합니다. 오너가 Render 에 값을 넣는 순간에만
원격 로드가 켜집니다. 즉 이 코드를 배포하는 것만으로는 동작이 0% 바뀌지 않습니다
(회귀 위험을 0에서 시작시키기 위한 의도적인 설계).

    DATA_SOURCE_BASE_URL = https://raw.githubusercontent.com/moonbear135/visible-hand-dashboard/main

캐싱 전략 — TTL + ETag 조건부 GET (둘 다 씁니다)
────────────────────────────────────────────────────────────────────────────
  · TTL(기본 600초) 안에서는 **네트워크를 아예 타지 않습니다.** 접속자 수와 무관하게
    10분에 파일당 1회만 확인 → GitHub 쪽에 무리를 주지 않습니다 (ENGINEERING_SPEC §0-3-2).
  · TTL 이 지나면 `If-None-Match: <ETag>` 를 붙여 조건부 GET 을 보냅니다. 내용이 그대로면
    서버가 **304 + 본문 없음**으로 답하므로, 하루 대부분의 확인이 2.2MB 를 다시 받지 않고
    끝납니다. (raw.githubusercontent.com 은 ETag 를 내려줍니다.)
  · 즉 TTL 은 "요청 횟수"를, ETag 는 "요청 1회당 대역폭"을 줄입니다. 서로 대체재가 아니라
    보완재라 둘 다 씁니다.

실패 처리 — §0-1 (조용히 이전 값으로 덮지 않습니다)
────────────────────────────────────────────────────────────────────────────
  1) 원격 성공                      → 그 내용을 씁니다.
  2) 원격 실패 + **원격 캐시 있음** → 마지막 성공분으로 계속 서비스하되,
                                      `get_staleness_status()` 가 "최신이 아님 + 마지막 성공
                                      시각"을 알려주고 `web/layout.py` 가 **모든 페이지 상단에
                                      빨간 배너**를 띄웁니다.
  3) 원격 실패 + 캐시 없음 + **로컬 사본 있음** → 이미지에 함께 배포된 사본으로 폴백하되,
                                      역시 2)와 같은 배너를 띄웁니다(사본은 배포 시점 값이라
                                      최신이 아닙니다).
  4) 셋 다 실패                     → `(None, 사람이 읽는 실패 사유)`. 화면이 예전 그대로
                                      빨간 실패 배너를 띄우고 **숫자를 한 개도 그리지 않습니다.**

⚠️ 여기 캐시(`_CACHE`)에 들어가는 것은 **모든 접속자에게 동일한 시세 스냅샷 텍스트**뿐입니다.
   로그인 토큰·보유종목 같은 사용자별 데이터는 절대 이 모듈을 거치지 않습니다
   (ENGINEERING_SPEC.md §0-3-8 의 구분선 — 읽기 전용 시장데이터는 전역이 정답).

⚠️ 이 샌드박스에서는 인터넷이 없어 **실제 raw.githubusercontent.com 왕복을 검증하지
   못했습니다.** `tests/test_data_source.py` 가 가짜 `requests` 로 성공/304/타임아웃/
   네트워크에러/HTTP에러/캐시없음 조합을 오프라인으로 검증합니다. 실망 검증은 오너가
   배포 후 실기기에서 해야 합니다(보고서의 확인 시나리오 참고).
"""

import os
import threading
import time
from datetime import datetime
from typing import Any, Optional, Tuple

try:
    import requests
except ImportError:                                   # pragma: no cover - requirements.txt 에 포함됨
    requests = None

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo('Asia/Seoul')
except Exception:                                     # pragma: no cover - tzdata 없는 환경
    _KST = None


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_REPO_ROOT, 'data')

# ── 환경변수 이름 (오너가 Render 대시보드 Environment 에 넣는 값) ────────────────
ENV_BASE_URL = 'DATA_SOURCE_BASE_URL'          # 미설정 = 원격 끔 = 예전과 100% 동일
ENV_TTL_SECONDS = 'DATA_SOURCE_TTL_SECONDS'    # 선택. 기본 600초(10분)
ENV_TIMEOUT_SECONDS = 'DATA_SOURCE_TIMEOUT_SECONDS'  # 선택. 기본 8초

DEFAULT_TTL_SECONDS = 600.0
DEFAULT_TIMEOUT_SECONDS = 8.0

# 실패한 직후 모든 접속이 매번 네트워크를 때리면 느려지기만 합니다. 실패 후에는 이 시간 동안
# 재시도하지 않고 마지막 성공분(또는 로컬 사본)으로 서비스합니다. 배너는 그 동안 계속 뜹니다.
RETRY_BACKOFF_SECONDS = 60.0

# 상대 서버에 우리가 누구인지 밝힙니다 (§0-3-2 크롤링 매너).
USER_AGENT = 'visible-hand-dashboard/1.0 (+https://visiblehand.co.kr)'

# ── 원격 응답 방어선 (2026-08-17 추가) ────────────────────────────────────────
# 예전에는 `response.content` 를 무조건 통째로 메모리에 올렸습니다. 상한도, 형식 확인도
# 없어서 ① 비정상적으로 큰 응답(잘못된 URL 이 거대한 파일을 가리키거나 응답이 오염된 경우)
# 이 그대로 캐시에 얹히고, ② 로그인 페이지·에러 페이지 같은 **HTML 응답이 JSON 인 척**
# 캐시에 들어갈 수 있었습니다. Render 무료 인스턴스는 메모리가 512MB 뿐이라 ①은 실제로
# OOM(프로세스 강제 종료)으로 이어질 수 있습니다.
#
# 상한값 근거: 현재 저장소에서 가장 큰 파일이 `data/us_stocks_raw_latest.json` 약 4.1MB
# 입니다. 20MB 는 정상 데이터가 몇 배로 불어나도 걸리지 않을 만큼 넉넉하면서, 사고성
# 거대 응답은 확실히 막는 선입니다.
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024

# 우리가 받는 것은 JSON/CSV 텍스트뿐입니다. raw.githubusercontent.com 은 `text/plain` 으로
# 내려줍니다. ⚠️ 헤더가 아예 없으면 형식으로 막지 않습니다 — "없는 정보로 판단을 지어내지
# 않는다"(§0-1). 막고 싶은 건 명백히 다른 것(HTML 에러/로그인 페이지)이 섞여 들어오는 경우입니다.
ALLOWED_CONTENT_TYPES = (
    'text/plain', 'text/csv', 'text/json',
    'application/json', 'application/csv', 'application/octet-stream',
)

# ⚠️ 전역 캐시. 키는 **저장소 기준 상대경로 문자열**('data/us_stocks_latest.json') 뿐이고,
#    값은 모든 접속자에게 동일한 스냅샷 텍스트와 그 메타데이터뿐입니다 (§0-3-8).
_CACHE = {}
_LOCK = threading.RLock()


# =============================================================================
# 1. 설정 읽기
# =============================================================================
def _positive_float(env_name: str, default: float) -> float:
    """숫자 환경변수. 값이 이상하면 **조용히 넘어가지 않고 로그로 크게 알리고** 기본값을 씁니다."""
    raw = (os.environ.get(env_name) or '').strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f'⚠️ 환경변수 {env_name} 값이 숫자가 아닙니다. 기본값({default})을 사용합니다.')
        return default
    if value <= 0:
        print(f'⚠️ 환경변수 {env_name} 값이 0 이하입니다. 기본값({default})을 사용합니다.')
        return default
    return value


def resolve_base_url() -> Tuple[Optional[str], Optional[str]]:
    """`(정규화된 base URL, 설정오류 사유)`.

    둘 다 None 이면 "원격 기능이 꺼져 있음"(= 기본 상태, 예전과 동일 동작)입니다.
    """
    raw = (os.environ.get(ENV_BASE_URL) or '').strip()
    if not raw:
        return None, None
    if not (raw.startswith('https://') or raw.startswith('http://')):
        # §0-1 — 오타를 "원격이 꺼진 것"과 구분 없이 삼키지 않습니다. 로그 + 화면 배너 둘 다.
        return None, ('데이터 주소 설정이 올바르지 않습니다 '
                      '(http:// 또는 https:// 로 시작해야 합니다)')
    return raw.rstrip('/'), None


def is_remote_enabled() -> bool:
    """원격 로드가 실제로 켜져 있는지. 미설정/설정오류면 False(= 로컬 파일만 씁니다)."""
    base, _config_error = resolve_base_url()
    return base is not None


# =============================================================================
# 2. 캐시 엔트리
# =============================================================================
def _new_entry() -> dict:
    return {
        'text': None,              # 마지막으로 성공한 원격 본문 (문자열)
        'etag': None,              # 그 본문의 ETag (조건부 GET 용)
        'revision': 0,             # 내용이 실제로 바뀔 때만 증가 → 호출자의 파싱 캐시 키
        'fetched_at': 0.0,         # time.monotonic() — TTL 계산용
        'fetched_at_wall': None,   # datetime — 배너 문구에 쓰는 "우리가 받아온 시각"
        'next_attempt': float('-inf'),  # 실패 백오프
        'failure_reason': None,    # 사람이 읽는 짧은 사유(예: '응답 시간 초과'). None = 정상
        'local_fallback': False,   # 원격을 한 번도 못 받아 이미지 사본을 쓰는 중인지
        'fetching': False,         # 다른 스레드가 이미 받아오는 중인지
        'fetch_event': None,       # 2026-08-30 재감사 Medium-1: fetching 중 도착한 다른
                                    # 요청이 새 HTTP GET을 내지 않고 이 완료를 기다리는 용도
    }


def _now_wall() -> Optional[datetime]:
    try:
        return datetime.now(_KST) if _KST else datetime.now()
    except Exception:                                 # pragma: no cover
        return None


def _local_mtime_wall(path: str) -> Optional[datetime]:
    """로컬 사본의 마지막 수정시각 = 사실상 '이 이미지가 만들어진 시점'."""
    try:
        stamp = os.stat(path).st_mtime
    except OSError:
        return None
    try:
        return datetime.fromtimestamp(stamp, _KST) if _KST else datetime.fromtimestamp(stamp)
    except Exception:                                 # pragma: no cover
        return None


# =============================================================================
# 3. 로컬 파일 읽기 (원격이 꺼져 있을 때의 기본 경로 — 예전 web/state.py 와 동일)
# =============================================================================
def _read_local(path: str, encoding: str, known_version) -> Tuple[Optional[str], Optional[str], Any]:
    try:
        stat = os.stat(path)
    except OSError:
        return None, f'스냅샷 파일({os.path.basename(path)})이 없습니다.', None

    # 파일이 그대로면 본문을 다시 읽지 않습니다. (스냅샷 6개 ≈ 5MB 를 상호작용마다 다시
    # 읽으면 예전 web/state.py 의 mtime 캐시가 사라진 것과 같아 명백한 성능 회귀입니다.)
    version = ('local', stat.st_mtime_ns, stat.st_size)
    if known_version is not None and known_version == version:
        return None, None, version

    try:
        with open(path, 'r', encoding=encoding) as f:
            text = f.read()
    except Exception as exc:                          # noqa: BLE001 — 상세는 로그로만 (§0-3-4)
        print(f'⚠️ 스냅샷 파일 읽기 실패 ({path}): {exc}')
        return None, (f'스냅샷 파일({os.path.basename(path)})을 읽지 못했습니다. '
                      '파일이 손상되었을 수 있습니다.'), None
    return text, None, version


# =============================================================================
# 4. 원격 fetch
# =============================================================================
def _normalise_newlines(text: str) -> str:
    """파이썬 텍스트 모드(universal newlines)와 결과를 맞춥니다.

    `data/*.json` 은 CRLF 로 커밋돼 있습니다. 로컬 경로는 `open(..., 'r')` 이 CRLF 를 LF 로
    바꿔서 돌려주는데, HTTP 응답 바이트를 그대로 디코드하면 CRLF 가 남습니다. 그러면 같은
    파일인데 원격/로컬에 따라 다운로드 파일의 바이트가 달라집니다(계획서 §9 완료기준 ⑤).
    """
    return text.replace('\r\n', '\n').replace('\r', '\n')


class _ResponseTooLarge(Exception):
    """상한을 넘는 응답. 밖으로 새지 않고 `_http_get()` 안에서 실패 사유로 바뀝니다."""


def _header(response, name: str) -> Optional[str]:
    try:
        value = (response.headers or {}).get(name)
    except Exception:                                 # pragma: no cover
        return None
    return str(value) if value else None


def _declared_length_over_limit(response) -> Optional[int]:
    """`Content-Length` 가 상한을 넘으면 그 값을, 아니면 None.

    **본문을 한 바이트도 받기 전에** 차단하기 위한 사전 검사입니다. 헤더가 없거나(청크 전송)
    숫자가 아니면 None 을 돌려주고, 실제 수신 중에 `_read_body()` 가 다시 셉니다.
    """
    raw = _header(response, 'Content-Length')
    if raw is None:
        return None
    try:
        declared = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return declared if declared > MAX_RESPONSE_BYTES else None


def _rejected_content_type(response) -> Optional[str]:
    """받아도 되는 형식이 아니면 그 Content-Type 문자열을, 괜찮으면 None."""
    raw = _header(response, 'Content-Type')
    if raw is None:
        return None                                   # 헤더 없음 → 형식으로 막지 않습니다
    main = raw.split(';', 1)[0].strip().lower()
    return None if main in ALLOWED_CONTENT_TYPES else raw


def _read_body(response) -> bytes:
    """본문을 **상한까지만** 받습니다. 넘으면 그 자리에서 중단(`_ResponseTooLarge`).

    `stream=True` 와 짝을 이룹니다 — 20MB 를 넘어서는 바이트는 애초에 메모리에 쌓이지
    않습니다(상한을 넘는 순간 멈추고 연결을 닫습니다).
    """
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise _ResponseTooLarge(total)
        chunks.append(chunk)
    return b''.join(chunks)


def _http_get(url: str, etag: Optional[str], encoding: str) -> dict:
    """조건부 GET 1회. 예외를 밖으로 던지지 않고 결과 dict 로 정리해 돌려줍니다.

    ⚠️ 실패 사유(`reason`)는 **사람이 읽는 짧은 한국어**뿐입니다 — URL·예외 원문·헤더 값은
       서버 로그에만 남깁니다(§0-3-4). 어떤 실패든 호출자(`_read_remote`)의 기존 실패 경로
       (백오프 + 캐시/로컬 사본 폴백 + 전역 배너)를 그대로 탑니다(§0-1).
    """
    if requests is None:                              # pragma: no cover
        return {'kind': 'error', 'reason': '원격 로더 구성요소 없음'}

    headers = {'User-Agent': USER_AGENT}
    if etag:
        headers['If-None-Match'] = etag

    try:
        # stream=True — 헤더를 먼저 받아보고 본문을 받을지 결정합니다(아래 사전 검사 2종).
        response = requests.get(url, headers=headers, stream=True,
                                timeout=_positive_float(ENV_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS))
    except Exception as exc:                          # noqa: BLE001 — 상세는 로그로만 (§0-3-4)
        print(f'⚠️ 원격 데이터 요청 실패 ({url}): {type(exc).__name__}: {exc}')
        name = type(exc).__name__.lower()
        if 'timeout' in name:
            return {'kind': 'error', 'reason': '응답 시간 초과'}
        return {'kind': 'error', 'reason': '네트워크 연결 실패'}

    try:
        status = getattr(response, 'status_code', None)
        if status == 304:
            return {'kind': 'not_modified'}
        if status != 200:
            print(f'⚠️ 원격 데이터 응답 코드 이상 ({url}): {status}')
            return {'kind': 'error', 'reason': f'서버 응답 코드 {status}'}

        # ① 크기 사전 차단 — 본문을 받기 전에 헤더만 보고 끊습니다.
        declared = _declared_length_over_limit(response)
        if declared is not None:
            print(f'⚠️ 원격 데이터가 상한을 넘습니다 ({url}): '
                  f'Content-Length={declared} > {MAX_RESPONSE_BYTES}')
            return {'kind': 'error', 'reason': '내려받을 파일이 너무 큼'}

        # ② 형식 확인 — HTML 에러/로그인 페이지가 데이터인 척 캐시에 들어가는 것을 막습니다.
        bad_type = _rejected_content_type(response)
        if bad_type is not None:
            print(f'⚠️ 원격 데이터 형식이 예상과 다릅니다 ({url}): Content-Type={bad_type}')
            return {'kind': 'error', 'reason': '응답 형식이 올바르지 않음'}

        try:
            body = _read_body(response)
        except _ResponseTooLarge as exc:
            print(f'⚠️ 원격 데이터가 상한을 넘어 수신을 중단했습니다 ({url}): '
                  f'{exc.args[0] if exc.args else "?"} > {MAX_RESPONSE_BYTES}')
            return {'kind': 'error', 'reason': '내려받을 파일이 너무 큼'}
        except Exception as exc:                      # noqa: BLE001
            print(f'⚠️ 원격 데이터 수신 실패 ({url}): {type(exc).__name__}: {exc}')
            return {'kind': 'error', 'reason': '내려받는 중 연결이 끊김'}

        try:
            text = _normalise_newlines(body.decode(encoding))
        except Exception as exc:                      # noqa: BLE001
            print(f'⚠️ 원격 데이터 디코딩 실패 ({url}): {exc}')
            return {'kind': 'error', 'reason': '내려받은 내용을 해석하지 못함'}

        return {'kind': 'ok', 'text': text, 'etag': _header(response, 'ETag')}
    finally:
        # stream=True 로 열어둔 연결은 반드시 닫습니다(상한 초과로 중간에 끊은 경우 포함).
        try:
            response.close()
        except Exception:                             # pragma: no cover
            pass


def _hit(entry: dict, known_version) -> Tuple[Optional[str], Optional[str], Any]:
    version = ('remote', entry['revision'])
    if known_version is not None and known_version == version:
        return None, None, version                    # 내용 동일 — 호출자의 파싱 캐시 재사용
    return entry['text'], None, version


def _needs_fetch(entry: dict, now: float, ttl: float) -> bool:
    if now < entry['next_attempt']:
        return False                                  # 실패 직후 백오프 중
    if entry['text'] is None:
        return True                                   # 아직 한 번도 못 받아옴
    return (now - entry['fetched_at']) >= ttl


def _fallback_to_local(entry: dict, local_path: str, encoding: str, known_version,
                       reason: str) -> Tuple[Optional[str], Optional[str], Any]:
    """원격을 쓸 수 없는 상태 → 이미지에 함께 배포된 사본으로 폴백합니다.

    ⚠️ 부르기 전에 `entry['failure_reason']` 이 반드시 채워져 있어야 합니다 —
       `get_staleness_status()` 가 그 값을 보고 **전역 배너**를 띄웁니다. 배너 없이 사본을
       조용히 내보내면 "오래된 값을 최신인 척" 보여주게 되어 §0-1 위반입니다.
    """
    text, local_error, version = _read_local(local_path, encoding, known_version)
    with _LOCK:
        if text is None and local_error is not None:
            entry['local_fallback'] = False
            # 진짜 실패 — 화면은 예전처럼 빨간 배너만 띄우고 숫자를 그리지 않습니다 (§0-1).
            return None, f'최신 데이터를 내려받지 못했고({reason}), 서버에 함께 배포된 사본도 없습니다.', None
        entry['local_fallback'] = True
        entry['fetched_at_wall'] = _local_mtime_wall(local_path)
    return text, None, version


def _read_remote(rel_path: str, local_path: str, base: str,
                 encoding: str, known_version) -> Tuple[Optional[str], Optional[str], Any]:
    ttl = _positive_float(ENV_TTL_SECONDS, DEFAULT_TTL_SECONDS)
    now = time.monotonic()

    etag = None
    backoff_reason = None
    wait_event = None
    with _LOCK:
        entry = _CACHE.get(rel_path)
        if entry is None:
            entry = _new_entry()
            _CACHE[rel_path] = entry

        # 🔴 2026-08-17 수정 — 백오프/TTL 판정을 **캐시 본문 유무보다 먼저** 봅니다.
        #
        # 예전 조건은 `entry['text'] is not None and not _needs_fetch(...)` 였습니다. 그래서
        # 원격이 **한 번도 성공한 적 없으면**(URL 오타, 기동 시점부터 GitHub 장애) 이 가드가
        # 통째로 건너뛰어지고, `_needs_fetch()` 안에 들어 있던 백오프 검사(`next_attempt`)가
        # 아예 실행되지 않았습니다. `next_attempt` 는 실패할 때마다 세팅되는데 **읽는 사람이
        # 없었습니다.** 실측: 원격 성공 이력 없는 상태로 페이지를 10번 열면 HTTP 요청도 10번
        # 나갔고, "내 성적표"는 파일 6개를 읽으므로 한 번 열 때마다 최악 48초(8초 타임아웃 × 6)
        # 멈출 수 있었습니다.
        #
        # 핵심 규칙: **캐시된 본문이 없어도 백오프 중이면 네트워크를 타지 않고 곧바로 로컬
        # 사본으로 넘어간다.** (배너는 직전 실패의 `failure_reason` 으로 계속 떠 있습니다.)
        if not _needs_fetch(entry, now, ttl):
            if entry['text'] is not None:
                return _hit(entry, known_version)     # 캐시 유효(또는 백오프 중) → 네트워크 0회
            backoff_reason = entry['failure_reason'] or '원인 미상'
        else:
            if entry['fetching']:
                if entry['text'] is not None:
                    return _hit(entry, known_version)  # 다른 요청이 이미 받아오는 중 + 성공 이력 있음
                # 🔴 2026-08-30 재감사(공유인프라) Medium-1 수정 — 성공 이력이 아직 없는
                # 콜드 스타트 상태에서 동시 요청이 들어오면, 예전엔 위 조건(text가 있을 때만
                # 걸림)에 안 걸려 그대로 아래 else와 똑같이 새 HTTP 요청을 또 내보냈습니다.
                # 실측: 재배포 직후 접속 N개가 겹치면 같은 파일에 GET이 N번 나갔습니다
                # (§0-3-2 "원격 서버에 무리 주지 않기" 위반). 지금은 새 요청을 내보내지
                # 않고, 이미 진행 중인 요청이 끝나면서 채워 줄 `fetch_event`를 기다립니다.
                wait_event = entry.get('fetch_event') or threading.Event()
                entry['fetch_event'] = wait_event
            else:
                entry['fetching'] = True
                entry['fetch_event'] = threading.Event()
                etag = entry['etag']

    if wait_event is not None:
        # 락 밖에서 기다립니다 — 락을 쥔 채 기다리면, 먼저 시작된 요청이 끝나고 다시
        # 락을 잡으려는 순간 서로 막힙니다(교착). 타임아웃은 HTTP 타임아웃보다 여유
        # 있게 잡아, 만에 하나 이벤트가 울리지 않아도 여기서 영원히 멈추지 않게 합니다.
        wait_timeout = _positive_float(ENV_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS) + 3.0
        wait_event.wait(timeout=wait_timeout)
        with _LOCK:
            if entry['text'] is not None:
                return _hit(entry, known_version)
            reason = entry['failure_reason'] or '동시 요청이 먼저 받아오는 중 대기했지만 원인 미상으로 실패'
        return _fallback_to_local(entry, local_path, encoding, known_version, reason)

    if backoff_reason is not None:
        # 네트워크를 건드리지 않고 사본으로 (위 주석의 "즉시 실패/폴백" 경로).
        return _fallback_to_local(entry, local_path, encoding, known_version, backoff_reason)

    try:
        outcome = _http_get(f'{base}/{rel_path}', etag, encoding)
    finally:
        with _LOCK:
            entry['fetching'] = False
            _woken_event = entry.get('fetch_event')
            entry['fetch_event'] = None
        if _woken_event is not None:
            _woken_event.set()          # 기다리던 요청들을 깨움(위 Medium-1 수정)

    with _LOCK:
        if outcome['kind'] == 'ok':
            if outcome['text'] != entry['text']:
                entry['revision'] += 1
            entry['text'] = outcome['text']
            entry['etag'] = outcome['etag']
            _mark_success(entry)
            return _hit(entry, known_version)

        if outcome['kind'] == 'not_modified' and entry['text'] is not None:
            _mark_success(entry)                      # 내용 그대로 = 최신 확인 완료
            return _hit(entry, known_version)

        reason = outcome.get('reason') or '원인 미상'
        if outcome['kind'] == 'not_modified':
            # 본문이 없는데 캐시도 없음 — 정상 서버라면 나올 수 없는 조합입니다.
            reason = '서버 응답 304(본문 없음)'
        entry['failure_reason'] = reason
        entry['next_attempt'] = time.monotonic() + RETRY_BACKOFF_SECONDS
        if entry['text'] is not None:
            entry['local_fallback'] = False
            return _hit(entry, known_version)         # 마지막 성공분 + 전역 배너

    # 원격 캐시가 아예 없습니다 → 이미지에 함께 배포된 사본으로 폴백합니다.
    return _fallback_to_local(entry, local_path, encoding, known_version, reason)


def _mark_success(entry: dict) -> None:
    entry['fetched_at'] = time.monotonic()
    entry['fetched_at_wall'] = _now_wall()
    entry['failure_reason'] = None
    entry['local_fallback'] = False
    entry['next_attempt'] = float('-inf')


# =============================================================================
# 5. 공개 API
# =============================================================================
# 저장소 **루트**에 있으면서 원격 대상으로 삼는 파일 (2026-08-17 추가).
#
# 원칙은 `data/` 바로 아래 파일만 원격 대상으로 삼는 것이고, 아래 목록은 그 예외입니다.
# `market_history.csv` 를 넣은 이유:
#   · "사장님 보고서"의 **한국 벤치마크(코스피 종가)** 원본이 이 파일입니다.
#   · 오너가 Render Build Filters(Ignored Paths)에 이 파일을 넣으면 데이터 커밋이 재배포를
#     부르지 않게 되고, 그 순간부터 이미지에 구워진 사본은 **얼어붙습니다.** 그런데 예전
#     코드는 이 파일을 `open()` 으로 직접 읽어서 `data_source` 의 최신성 추적 밖에 있었고,
#     그래서 값이 아무리 오래돼도 `web/layout.py` 의 전역 배너가 뜨지 않았습니다(§0-1 위반).
#
# ⚠️ **읽기 경로만** 원격을 탑니다 — "쓰기 충돌 때문에 이 파일은 원격 전환 안 함" 이라는
#    기존 결정은 그대로 유지됩니다. 이 파일은 앱이 직접 쓰기도 하는 유일한 데이터 파일이고
#    (`utils/db.py` 관리자 수동 입력 ← `web/pages/macro_page.py`), 그 읽기·쓰기 짝은 지금도
#    pandas 로 **로컬 파일만** 다루며 이번 변경에서 한 줄도 건드리지 않았습니다.
#    즉 원격을 켜면 매크로 화면은 로컬 사본을, 보고서의 벤치마크는 원격(=배치가 저장소에
#    커밋해 온 누적 이력)을 봅니다. 벤치마크 용도로는 "확정 커밋된 이력"쪽이 맞습니다.
_REMOTE_ROOT_FILES = ('market_history.csv',)


def remote_relative_path(path: str) -> Optional[str]:
    """이 로컬 경로가 **원격에서 받아올 수 있는 파일**이면 저장소 기준 상대경로를 돌려줍니다.

    `data/` 바로 아래 파일과 위 `_REMOTE_ROOT_FILES` 목록만 대상입니다. 그 외(테스트가 만든
    임시 경로, `data/us_sample/` 같은 하위 폴더, 저장소 밖 경로)는 None → 예전과 똑같이
    로컬 파일만 읽습니다.
    """
    try:
        absolute = os.path.abspath(path)
    except Exception:                                 # pragma: no cover
        return None
    directory = os.path.dirname(absolute)
    name = os.path.basename(absolute)
    if directory == DATA_DIR:
        return f'data/{name}'
    if directory == _REPO_ROOT and name in _REMOTE_ROOT_FILES:
        return name
    return None


def read_text(path: str, *, encoding: str = 'utf-8',
              known_version=None) -> Tuple[Optional[str], Optional[str], Any]:
    """`data/` 안의 텍스트 파일 하나를 읽습니다. 원격이 켜져 있으면 원격 우선.

    :param path: **로컬 파일 경로**(`web.state.data_path()` 결과). 원격이 꺼져 있으면
        이 경로를 그대로 읽습니다.
    :param encoding: 로컬/원격 모두 이 인코딩으로 디코드합니다.
    :param known_version: 호출자가 이미 이 버전의 내용을 파싱해 두었다면 넘기세요.
        내용이 그대로면 본문을 다시 만들지 않고 "변경 없음"을 알려 줍니다.

    :return: `(본문, 실패사유, 버전)` — 세 가지 경우뿐입니다.
        · `(str, None, version)`  : 새로 읽은 내용
        · `(None, None, version)` : `known_version` 과 같음 → **호출자가 가진 값을 그대로 쓰세요**
        · `(None, str,  None)`    : 진짜 실패. 사유는 사람이 읽는 한국어 한 문장입니다
          (파이썬 예외 원문·경로·URL 은 절대 들어가지 않습니다 — §0-3-4).
    """
    base, config_error = resolve_base_url()
    _remember_config_error(config_error)
    if base is None:
        return _read_local(path, encoding, known_version)

    rel_path = remote_relative_path(path)
    if rel_path is None:
        return _read_local(path, encoding, known_version)

    return _read_remote(rel_path, path, base, encoding, known_version)


_CONFIG_ERROR_KEY = '__config__'


def _remember_config_error(reason: Optional[str]) -> None:
    """설정 오류를 기억(또는 해제)합니다. 오너가 값을 고치면 배너도 자동으로 사라집니다."""
    with _LOCK:
        if reason is None:
            _CACHE.pop(_CONFIG_ERROR_KEY, None)
            return
        entry = _CACHE.get(_CONFIG_ERROR_KEY)
        if entry is None:
            entry = _new_entry()
            _CACHE[_CONFIG_ERROR_KEY] = entry
        entry['failure_reason'] = reason


def get_staleness_status() -> Optional[dict]:
    """"지금 화면에 보이는 값이 최신이 아니다"를 알려줄 필요가 있으면 그 내용을, 없으면 None.

    `web/layout.py` 가 **모든 페이지 본문을 그린 뒤** 이 함수를 불러, 상단 슬롯에 빨간 배너를
    한 번만 그립니다. 화면 5개에 같은 코드를 복붙하지 않기 위한 단일 지점입니다 (§0-3-10).

    배너는 다음 fetch 가 성공하는 순간 자동으로 사라집니다(= 그 뒤에 페이지를 열면 안 보임).
    이미 열려 있는 화면을 자동 갱신하지는 않습니다 — §0-3-1(실시간처럼 보이게 만들지 않기).
    """
    with _LOCK:
        config_entry = _CACHE.get(_CONFIG_ERROR_KEY)
        config_reason = config_entry['failure_reason'] if config_entry else None
        # ⚠️ "보여줄 값이 아예 없는" 파일은 여기서 뺍니다. 그런 파일은 화면이 이미 **자기 자리에
        #    빨간 실패 배너**를 띄우고 숫자를 그리지 않습니다(§0-1). 그 위에 "지금 보이는 값은
        #    …기준입니다"를 겹쳐 띄우면, 보이지도 않는 값이 있는 것처럼 말하게 됩니다.
        stale = [
            (rel_path, entry['fetched_at_wall'], entry['failure_reason'], entry['local_fallback'])
            for rel_path, entry in _CACHE.items()
            if rel_path != _CONFIG_ERROR_KEY
            and entry['failure_reason'] is not None
            and (entry['text'] is not None or entry['local_fallback'])
        ]

    if config_reason:
        # ⚠️ 2026-08-30 재감사(공유인프라) Low-5 — 이 분기는 설정 오류(base=None) 상황이라
        # `_read_local()` 결과가 이 함수가 보는 `_CACHE`에 남지 않습니다. 즉 "로컬 사본을
        # 실제로 읽어냈는지"를 여기서는 알 수 없습니다 — 사본조차 없는 화면이 섞여 있어도
        # 이 전역 배너만은 "사본을 보여주고 있다"고 단정하면 안 됩니다(§0-1). 그래서 문구를
        # "보이는 값이 있다면 사본" 식으로 조건부로 두고, 값 자체가 안 보이는 화면은 그
        # 화면 자신의 실패 배너를 보라고 안내합니다.
        return {
            'message': (f'🚨 {config_reason} — 화면에 값이 보인다면 서버에 함께 배포된 '
                        f'사본이고, 값 자체가 안 보이는 화면은 그 화면의 개별 실패 안내를 '
                        f'확인하세요.'),
            'as_of': None, 'as_of_text': None, 'reason': config_reason,
            'local_fallback': True, 'files': [], 'config_error': True,
        }

    if not stale:
        return None

    # 가장 오래된(= 가장 불리한) 성공 시각을 대표로 씁니다. 시각을 모르는 파일이 있으면 그쪽이
    # 우선입니다 — "언제 것인지 모른다"를 "10분 전"으로 포장하지 않기 위해서입니다 (§0-1).
    stale.sort(key=lambda row: (row[1] is not None, row[1]))
    _rel_path, as_of, reason, local_fallback = stale[0]
    as_of_text = as_of.strftime('%Y-%m-%d %H:%M') if as_of is not None else None

    if as_of_text is None:
        tail = '지금 보이는 값의 기준 시각을 확인할 수 없습니다.'
    elif local_fallback:
        tail = f'지금 보이는 값은 서버에 함께 배포된 사본({as_of_text} 기준)입니다.'
    else:
        tail = f'지금 보이는 값은 {as_of_text} 에 받아온 것입니다.'

    return {
        'message': f'🚨 최신 데이터를 불러오지 못했습니다({reason}) — {tail}',
        'as_of': as_of,
        'as_of_text': as_of_text,
        'reason': reason,
        'local_fallback': local_fallback,
        'files': sorted(row[0] for row in stale),
        'config_error': False,
    }


def reset_cache() -> None:
    """테스트 전용 — 프로세스 캐시를 비웁니다. 운영 코드에서 부르지 마세요."""
    with _LOCK:
        _CACHE.clear()
