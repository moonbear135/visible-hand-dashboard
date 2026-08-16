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
