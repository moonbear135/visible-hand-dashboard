"""
읽기 전용 시장 데이터 로더 (NiceGUI 이전, 2단계 신설).

계획서 §3-3 규칙 4 — **읽기 전용 시장 데이터(`data/*.json`)는 모듈 전역 캐시가 정답**입니다.
Streamlit 은 상호작용마다 스크립트를 통째로 재실행해 매번 JSON 을 다시 파싱했지만,
NiceGUI 는 한 프로세스가 모든 접속자를 처리하므로 파일이 바뀌지 않는 한 한 번만 파싱하면
됩니다(접속자 수와 무관한 비용 → 공개 서비스에 유리).

⚠️ 반대로 **사용자별 데이터(로그인 토큰·보유종목 등)는 여기에 절대 두지 않습니다**
   (ENGINEERING_SPEC.md §0-3-8 — 전역에 두면 A의 자산 정보가 B에게 보입니다).
   이 파일이 다루는 건 모든 사용자에게 동일한 시세 스냅샷뿐입니다.

⚠️ §0-1 — 캐시 키에 **내용 버전**(로컬은 파일 수정시각+크기, 원격은 리비전 번호)을 넣습니다.
   그래야 수집기가 새 스냅샷을 덮어썼을 때 옛 데이터를 계속 보여주는 사고가 나지 않습니다.
   로드에 실패하면 조용히 이전 값을 돌려주지 않고 실패를 그대로 알립니다(호출한 화면이 빨간
   배너를 띄웁니다).

⚠️ 캐시가 돌려주는 객체는 **모든 접속자가 공유**합니다. 화면 코드는 이 데이터를 읽기만 하고
   절대 제자리에서 수정(mutate)하지 마세요. (다행히 `utils/guardrail.py` 는 내부에서
   `stock_data.copy()` 를 먼저 하므로 그대로 호출해도 안전합니다.)

🌐 2026-08-17 — 파일을 실제로 여는 일은 `utils/data_source.py` 로 옮겼습니다
   (NICEGUI_MIGRATION_PLAN.md §8-5 "B안"). **이 파일의 함수 3개는 이름·인자·반환값이 한 글자도
   바뀌지 않았습니다** — 화면 5개(pegy/us_stocks/scorecard/report/macro)는 전혀 손대지 않아도
   됩니다. 환경변수 `DATA_SOURCE_BASE_URL` 이 없으면 `data_source` 도 예전과 똑같이 로컬 파일만
   읽으므로, 이 커밋을 배포하는 것만으로는 동작이 전혀 바뀌지 않습니다.
"""

import json
import os
from typing import Any, Optional, Tuple

from utils import data_source

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_REPO_ROOT, 'data')

# path -> (version, payload)   ← version 은 data_source 가 만든 "내용이 바뀌면 달라지는 값"
_JSON_CACHE = {}


def data_path(filename: str) -> str:
    """`data/` 안의 파일 경로. 화면 파일마다 상대경로를 따로 계산하지 않게 여기 하나만 씁니다."""
    return os.path.join(DATA_DIR, filename)


def load_json_file(path: str) -> Tuple[Optional[Any], Optional[str]]:
    """JSON 파일을 읽어 `(내용, 실패사유)` 를 돌려줍니다. 성공하면 실패사유가 None 입니다.

    실패사유는 **사람이 읽는 한국어 한 문장**입니다. 파이썬 예외 원문·경로·트레이스백은
    화면에 노출하지 않고 서버 로그로만 보냅니다 (ENGINEERING_SPEC.md §0-3-4).
    """
    cached = _JSON_CACHE.get(path)
    known_version = cached[0] if cached is not None else None

    text, error, version = data_source.read_text(path, encoding='utf-8', known_version=known_version)
    if error is not None:
        return None, error
    if text is None:
        # 내용이 그대로라는 뜻 — 이미 파싱해 둔 값을 재사용합니다(2.2MB JSON 재파싱 회피).
        return cached[1], None

    try:
        payload = json.loads(text)
    except Exception as exc:                      # noqa: BLE001 — 상세는 로그로만
        print(f'⚠️ JSON 스냅샷 파싱 실패 ({path}): {exc}')
        return None, f'스냅샷 파일({os.path.basename(path)})을 읽지 못했습니다. 파일이 손상되었을 수 있습니다.'

    _JSON_CACHE[path] = (version, payload)
    return payload, None


# =============================================================================
# 🔴 2026-08-21 — 화면(@ui.page)이 데이터를 읽을 때는 **반드시 아래 비동기 판**을 쓰세요.
#
# 무슨 사고였나
# ─────────────────────────────────────────────────────────────────────────────
# 운영에서 "연결이 끊겼습니다. 다시 연결 중…" 토스트가 모든 기기에서 반복됐습니다.
# 원인은 위 `load_json_file()` 자체가 아니라 **그것을 부르는 자리**였습니다.
#   · Render 환경변수 `DATA_SOURCE_BASE_URL` 이 켜져 있으면, 캐시 TTL 이 지난 순간
#     `utils/data_source._http_get()` 가 `requests.get(...)` 로 **동기(블로킹)** 왕복을 합니다.
#   · NiceGUI 는 한 프로세스 · 한 이벤트 루프가 **모든 접속자**를 처리합니다. 그 한 줄이
#     루프를 붙잡고 있는 동안 다른 접속자의 WebSocket 하트비트까지 전부 멈춥니다.
#   · 그래서 "데이터를 하나도 안 읽는 화면"(예: /scorecard 의 로그인 폼)에 있던 사람까지
#     같이 끊겼습니다 — 자기 화면이 아니라 **남의 요청**이 루프를 막았기 때문입니다.
#
# 어떻게 고쳤나 — `web/auth.py::login()` 이 2026-08-17 에 쓴 것과 **같은 처방**입니다.
# ─────────────────────────────────────────────────────────────────────────────
# 실제로 몇 초씩 걸리는 일을 `run.io_bound` 로 **별도 스레드**에 넘기고, 이벤트 루프는
# 그 사이에 다른 접속자를 계속 돌봅니다. 성공/실패 결과값은 한 글자도 바뀌지 않습니다 —
# 바뀌는 것은 "블로킹이 어디서 일어나는가" 뿐입니다.
#
# ⚠️ `login()` 과 달리 **함수 전체**를 통째로 스레드에 넘겨도 안전합니다. 그때 문제가 됐던
#    것은 `app.storage.*`(접속별 컨텍스트가 필요한 저장소)였는데, 이 경로가 만지는 것은
#    모듈 전역 `_JSON_CACHE` 와 `utils/data_source._CACHE`(자체 `threading.RLock` 보유)
#    뿐이고 **NiceGUI 의 접속 컨텍스트를 전혀 쓰지 않습니다**. 둘 다 모든 접속자에게
#    동일한 읽기 전용 시세 스냅샷만 담습니다(§0-3-8 구분선의 "전역이 정답"인 쪽).
#
# ⚠️ 동기판 `load_json_file()` 은 **그대로 남겨 둡니다.** NiceGUI 밖(배치 스크립트·테스트)
#    에서 부르는 자리가 있고, 아래 비동기판도 결국 이 함수를 스레드에서 실행합니다.
#    즉 읽기 규칙(버전 캐시·실패 문구)이 한 곳에만 있습니다 (§0-3-10).
# =============================================================================

# `@ui.page` 데코레이터에 넘길 응답 제한 시간.
#
# ⚠️ 왜 명시해야 하는가: NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)
#    을 겁니다. 동기 함수일 때는 아무리 오래 걸려도 기다렸다가 화면을 내려줬는데, 비동기로
#    바꾸는 순간 3초를 넘기면 화면 대신 **영어 500 오류 페이지**가 나갑니다 — 사용자에게
#    내부 사정을 영어로 흘리는 셈이라 §0-3-4 위반이고, 이번 수정의 목적(끊김 해소)과도
#    정반대입니다. 그래서 "예전과 같은 실패 모드"를 지키려고 넉넉하게 잡아 둡니다.
# ⚠️ 값의 근거: 원격 1회 요청 상한이 `DATA_SOURCE_TIMEOUT_SECONDS`(기본 8초)이고, 파일을
#    가장 많이 읽는 화면('내 성적표')이 스냅샷 6개를 읽습니다 → 최악 48초. 여기에 파싱
#    여유를 더해 60초입니다. 첫 실패 뒤에는 `data_source` 의 백오프가 걸려 나머지 파일은
#    네트워크를 타지 않으므로, 실제로 이 값에 닿는 경우는 "찬 서버 + 원격이 아주 느림"
#    뿐입니다.
PAGE_RESPONSE_TIMEOUT_SECONDS = 60.0


async def load_json_file_async(path: str) -> Tuple[Optional[Any], Optional[str]]:
    """`load_json_file()` 의 비동기 판 — **반환값은 동기판과 완전히 같습니다**.

    화면 코드는 `payload, error = load_json_file(path)` 를
    `payload, error = await load_json_file_async(path)` 로 바꾸기만 하면 됩니다.
    """
    # ⚠️ nicegui 는 **함수 안에서** 임포트합니다. 이 파일은 지금까지 nicegui 없이도
    #    임포트되는 순수 모듈이었고(배치 스크립트·오프라인 테스트가 그 성질에 기대고
    #    있습니다), 그 성질을 이번 수정으로 깨지 않기 위해서입니다.
    from nicegui import run                       # noqa: PLC0415

    result = await run.io_bound(load_json_file, path)
    if result is None:
        # `run.io_bound` 는 **요청이 취소되었거나 서버가 내려가는 중**일 때만 None 을
        # 돌려줍니다(NiceGUI 3.x 의 잠정 규약). 그때 "빈 데이터"인 척하면 화면이 값을
        # 지어내게 되므로, 다른 실패와 똑같이 사람이 읽는 한 문장으로 알립니다 (§0-1).
        return None, '데이터를 불러오는 중 요청이 중단되었습니다. 잠시 후 다시 시도해 주세요.'
    return result


def read_download_bytes(path: str) -> Optional[bytes]:
    """다운로드 버튼에 넘길 파일 내용을 만듭니다.

    ⚠️ 일부러 **텍스트 모드(`encoding='utf-8'`)로 읽고 다시 인코딩**합니다. 기존 Streamlit
       코드가 `open(path, "r", encoding="utf-8")` 로 읽어 `st.download_button(data=...)` 에
       넘겼기 때문입니다. 파이썬 텍스트 모드는 줄바꿈을 자동 변환(universal newlines)하므로,
       CRLF 로 커밋돼 있는 `data/*.json`(실측: 최신 스냅샷에 CRLF 15,830개)을 바이너리로
       읽으면 **기존에 사용자가 받던 파일과 바이트가 달라집니다.**
       계획서 §9 완료기준 ⑤("기존과 바이트 단위로 동일")를 문자 그대로 지키기 위해
       읽는 방식까지 기존과 똑같이 맞춥니다. (내용상 차이는 줄바꿈 문자뿐입니다.)
       원격 경로도 `data_source._normalise_newlines()` 로 같은 변환을 하므로, 원격/로컬 어느
       쪽에서 왔든 사용자가 받는 바이트는 동일합니다.

    ⚠️ 원격 모드에서 이 함수를 로컬 파일로 두면, 이미지에 구워진 **배포 시점 사본**을
       `us_stocks_latest_<오늘날짜>.json` 이라는 이름으로 내려주게 됩니다 — 오늘 것이 아닌데
       오늘 것처럼 보이는 파일이라 §0-1 위반입니다. 그래서 화면이 그리는 데이터와 **같은
       경로**(`data_source.read_text`)를 씁니다.
    """
    text, error, _version = data_source.read_text(path, encoding='utf-8')
    if error is not None:
        print(f'⚠️ 다운로드용 파일 읽기 실패 ({path}): {error}')
        return None
    if text is None:                              # 방어 — known_version 을 안 넘겼으므로 정상 경로 아님
        return None
    return text.encode('utf-8')
