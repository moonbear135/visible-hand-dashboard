# tests/test_screen_reads_data_source.py
"""
🌐 화면 코드가 데이터 파일을 **항상 `data_source` 경유**로 읽는지 지키는 메타 테스트.

왜 이 파일이 있는가 (실제 사고 — 2026-09-05~07, #196-A · #198 · #205)
──────────────────────────────────────────────────────────────────────────────
같은 유형의 사고가 이번 주에만 세 번 났습니다 — `web/pages/` 안 어딘가가 데이터 파일을
`data_source.py`(원격 우선·10분 캐시) 대신 `open()`/`pd.read_csv()`/`pd.read_json()`로
**로컬에서 직접** 읽는 바람에, Render 컨테이너에 얼어붙은(마지막 코드 배포 시점) 사본을
계속 보여준 사고입니다:
  · `utils/stock_history.py::read_history_rows()` — `/indicator` 카드 (#196-A)
  · `web/pages/pegy_page.py::load_latest_kospi_usd()` — `/kr` 코스피·환율 카드 (#198)
  · `web/pages/macro_page.py::_load_history_df()` — `/macro` 기준 영업일 (#205)

한 곳을 고친 기억은 다른 곳을 지켜 주지 않았습니다(세 번 다 "이미 한 번 겪은 유형"이었는데도
새로 발견됐습니다). 그래서 `tests/test_user_facing_wording.py`(#197)와 같은 방향으로,
사람의 기억 대신 **구조적 방어선**을 둡니다(§0-1 · §0-3-10).

무엇을 검사하는가
──────────────────────────────────────────────────────────────────────────────
`web/pages/` · `web/components/`의 모든 `.py`를 AST로 훑어 다음을 금지합니다:
  ① 내장 `open(...)` 호출 — 데이터 파일이든 아니든, 이 두 패키지 안에서 파일을 여는 정당한
     이유가 없습니다(있다면 이 테스트가 실패로 알려 주고, 그때 근거를 남기고 허용 목록에
     추가하면 됩니다 — §0-1: 예외는 조용히 넘어가지 않고 눈에 띄게 남깁니다).
  ② `pd.read_csv(...)` / `pd.read_json(...)` 호출인데 **첫 인자가 `io.StringIO(...)` 또는
     `io.BytesIO(...)` 호출이 아닌 경우** — 즉 파일 경로(문자열 변수 포함)를 곧장 넘기는
     경우. 지금 이 두 패키지에 남아 있는 모든 `pd.read_csv`/`pd.read_json` 호출은 이미
     `data_source.read_text()`/`read_download_bytes()`가 돌려준 본문을 `io.StringIO`/
     `io.BytesIO`로 감싸 넘기는 형태뿐입니다(2026-09-07 실측, 이 테스트가 그 상태를 고정).

허용 목록은 지금 **비어 있습니다** — 이번 정리(#205)로 두 패키지 안의 직접 파일 읽기가
전부 없어졌기 때문입니다. 나중에 정말 필요한 예외가 생기면 `ALLOWED_OPEN`/
`ALLOWED_RAW_PANDAS_READ`에 `(파일, 이유)`를 추가하세요 — 이유 없는 추가는 리뷰에서 막습니다.

무엇을 검사하지 않는가
─────────────────────────────────────────────────────────────────────────────
· `utils/`는 대상이 아닙니다 — 배치 스크립트(`collector_*.py`, `run_*_batch.py`)는 저장소
  로컬 체크아웃을 직접 읽는 것이 맞고(수집 결과를 그 자리에서 커밋), `utils/db.py`의 **쓰기**
  경로(`shutil.copy2`, `df.to_csv(HISTORY_FILE)`)도 의도된 로컬 쓰기입니다. 이미 그쪽은
  `tests/test_data_source.py`가 개별 함수 단위로 회귀를 잡습니다.
· 주석·docstring 안의 문자열(예: 이 파일들의 "예전에는 `pd.read_csv(...)`" 같은 인용문)은
  AST가 `ast.Call`로 보지 않으므로 애초에 대상이 아닙니다.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

#: 검사 범위 — 사용자가 여는 화면 코드 두 패키지. `utils/`는 대상이 아닙니다(위 설명).
SCAN_ROOTS = ("web/pages", "web/components")

#: (파일, 이유) — 내장 `open()`을 허용할 예외. 지금은 비어 있습니다.
ALLOWED_OPEN: dict[str, str] = {}

#: (파일, 이유) — `pd.read_csv`/`pd.read_json`에 버퍼가 아닌 인자를 허용할 예외. 지금은 비어
#: 있습니다.
ALLOWED_RAW_PANDAS_READ: dict[str, str] = {}


def _scan_targets():
    files = []
    for root in SCAN_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            parts = set(path.relative_to(REPO_ROOT).parts)
            if "archive" in parts or "__pycache__" in parts:
                continue
            files.append(path)
    return files


SCAN_FILES = _scan_targets()
SCAN_FILE_IDS = [str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in SCAN_FILES]


def _is_pandas_read(node, method_name):
    """`node`가 `<무엇>.read_csv(...)` / `<무엇>.read_json(...)` 형태의 호출인가."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name)


def _first_arg_is_io_buffer(call_node):
    """`pd.read_csv(io.StringIO(...))` 처럼 첫 인자가 `io.StringIO`/`io.BytesIO` 호출인가."""
    if not call_node.args:
        return False
    first = call_node.args[0]
    if not isinstance(first, ast.Call):
        return False
    func = first.func
    if isinstance(func, ast.Attribute):
        return func.attr in ("StringIO", "BytesIO")
    if isinstance(func, ast.Name):
        return func.id in ("StringIO", "BytesIO")
    return False


def _find_violations(tree):
    """(라벨, 소스 줄) 위반 목록. `open`은 내장 함수 호출만, `pd.read_*`는 버퍼가 아닌 인자만."""
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            violations.append(("open()", node.lineno))
            continue
        for method_name in ("read_csv", "read_json"):
            if _is_pandas_read(node, method_name) and not _first_arg_is_io_buffer(node):
                violations.append((f"pd.{method_name}()", node.lineno))
    return violations


@pytest.mark.parametrize("path", SCAN_FILES, ids=SCAN_FILE_IDS)
def test_no_direct_file_reads_in_screen_code(path):
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = _find_violations(tree)

    remaining = []
    for label, lineno in violations:
        reason = (ALLOWED_OPEN.get(rel) if label == "open()"
                  else ALLOWED_RAW_PANDAS_READ.get(rel))
        if reason is None:
            remaining.append((label, lineno))

    assert not remaining, (
        f"{rel} 안에서 데이터 파일을 data_source 경유 없이 직접 읽는 것으로 보이는 호출을 "
        f"찾았습니다(#196-A·#198·#205와 같은 유형): {remaining}. "
        "data_source.read_text()/read_download_bytes()가 돌려준 본문을 io.StringIO/"
        "io.BytesIO로 감싸 pd.read_*에 넘기세요. 정말 예외가 필요하면 이 테스트 파일의 "
        "ALLOWED_OPEN/ALLOWED_RAW_PANDAS_READ에 이유와 함께 추가하세요."
    )


def test_allowlists_only_reference_existing_scanned_files():
    """허용 목록에 적은 파일 경로가 오타 없이 실제 스캔 대상인지."""
    scanned = set(SCAN_FILE_IDS)
    for rel in list(ALLOWED_OPEN) + list(ALLOWED_RAW_PANDAS_READ):
        assert rel in scanned, f"허용 목록의 경로가 스캔 대상에 없습니다: {rel!r}"
