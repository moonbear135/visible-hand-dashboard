# tests/test_data_sources_inventory.py
"""
🌐 외부 데이터 출처 재고 정합성 — "코드에 새 바깥 주소가 생겼는데 목록에 없다"를 구조적으로 막습니다 (2026-09-08)

⚠️ 이 파일이 왜 생겼는가

2026-09-08 하루에 외부 출처 두 곳(네이버 구 순위 페이지 0건, FinanceDataReader 404)이 동시에
무너졌는데, 둘째 것은 `ENGINEERING_SPEC.md` §0-3-2 의 "우리가 접속하는 대상" 목록에 **아예 없었습니다.**
목록은 글로만 있었고, 갱신을 강제하는 것이 없었으므로 낡았습니다 — `tests/test_agent_registry.py`
머리말에 적힌 것과 똑같은 실패 모양입니다("사람이 기억해야만 지켜지는 규칙"). 오너 결정:
*"네, 테스트로 강제"*. 그래서 절차를 검사로 바꿉니다. 전체 재고는 `DATA_SOURCES_INVENTORY.md`,
소유 에이전트는 `data-sources` 입니다.

이 파일이 지키는 것:

  ① 🔴 **코드 속 모든 `http(s)://호스트` 가 재고 문서(부록 A)에 있다.** 새 주소를 코드에 넣고
     문서에 안 적으면 **여기서 빨간불이 납니다.** 이것이 이 파일의 존재 이유입니다.
  ② 문서가 "코드에 있다"고 한 호스트는 정말로 코드에 있다(죽은 항목 = 낡은 문서).
     문서가 "코드에 없다(라이브러리·시크릿 뒤)"고 한 호스트는 정말로 코드에 없다 — 누군가 라이브러리
     뒤 주소를 직접 하드코딩하면 문서를 같이 고치게 됩니다.
  ③ `requirements.txt` 의 모든 패키지가 부록 B 에 "밖으로 나가는가"로 분류돼 있다.
     새 패키지 = 새 잠재 출처입니다(오늘 FDR 이 그랬습니다 — 라이브러리 뒤에 주소가 넷이나 있었습니다).
  ④ 코드가 import 하는 네트워크 성격 라이브러리(아래 `NETWORK_LIBRARIES` 고정 목록)는 부록 B 에 있다.
  ⑤ 부록 A 에서 "요청"으로 분류한 호스트는 `ENGINEERING_SPEC.md` §0-3-2 본문에도 등장한다
     (재고 문서와 §0-3-2 가 서로 어긋나지 않게).

🔴 이 파일이 **못 잡는 것** — 지키는 척하는 검사가 제일 나쁘므로 정직하게 적습니다:

  · **라이브러리 뒤에 숨은 새 주소.** 코드에 문자열이 없으니 못 봅니다. ④의 고정 목록에 없는 처음
    보는 라이브러리는 ③이 "requirements 에 적힌 이름을 문서에도 적어라"까지만 강제하고, 그 라이브러리가
    실제로 어디로 가는지는 **사람이 그 소스를 읽어야** 합니다(`data-sources` 에이전트 규칙 1).
  · 문자열을 조각내 붙인 주소(`"https://" + host`), 환경변수·시크릿에서 오는 주소(Supabase·Discord).
  · 라이브러리 **버전이 바뀌어** 같은 함수가 다른 주소로 가는 것.
  · 주소는 그대로인데 **응답 구조가 바뀌는 것**(2026-09-08 네이버 사고) — `data_sanity`·`data_freshness` 영역.

📌 오탐을 거르는 방식 — 문서 서식과 직결되므로 바꾸려면 여기와 문서를 같이 고치세요:
   · 파이썬은 **AST 로 문자열 상수만** 봅니다. 주석은 AST 에 없고, docstring(모듈·함수·클래스 본문
     첫 문자열)은 일부러 제외합니다 — 설명용 URL(`fred.stlouisfed.org` 같은 "이렇게 할 수도 있다")이
     요청으로 오인되지 않게. f-string 조각도 문자열 상수라 잡힙니다.
   · YAML·JS 는 AST 가 없어 줄 단위로 보고, `#`·`//` 로 **시작하는** 줄만 뺍니다(줄 중간 주석은 못 거름 —
     그래서 워크플로우 알림 문구 속 `github.com` 같은 링크는 잡히고, 문서는 그것을 "링크만"으로 분류합니다).
   · 링크·브라우저 쪽 주소도 목록에 **넣게** 합니다(분류가 "링크만"·"브라우저"). 빼는 대신 분류하게
     하는 이유: "요청인지 링크인지"를 판단한 사람이 문서에 그 판단을 남기게 하기 위해서입니다.

실행: python -m pytest tests/test_data_sources_inventory.py -v
     python tests/test_data_sources_inventory.py
"""
import ast
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다(2026-08-30 공용화).
# ⚠️ `FAILURES` 와 `check` 를 **둘 다** 가져와야 `test_suite_integrity.py` 의 Check A 가
#    이 파일을 하네스 사용 파일로 인식합니다(`test_agent_registry.py` 와 같은 사정).
from conftest import FAILURES, check  # noqa: E402,F401

INVENTORY_MD = REPO_ROOT / "DATA_SOURCES_INVENTORY.md"
SPEC_MD = REPO_ROOT / "ENGINEERING_SPEC.md"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"

# 스캔에서 빼는 디렉터리 — 이유를 반드시 함께 적습니다(조용한 예외 금지, §0-1).
SKIP_DIRS = {
    "archive": "퇴역 코드 — 실행 경로가 아님",
    "_to_delete": "삭제 대기 — 실행 경로가 아님",
    "tests": "테스트 픽스처 속 가짜 주소(example.com 등)는 요청이 아님",
    "data": "산출물 — metadata 에 출처 URL 이 기록돼 있지만 그건 코드가 아니라 기록",
    "__pycache__": "바이트코드",
    ".git": "",
    "node_modules": "",
    ".pytest_cache": "",
}
# 스캔 대상 확장자. `.json`(devcontainer 이미지 주소 등)·`.md` 는 실행 코드가 아니라 제외합니다.
CODE_SUFFIXES = {".py", ".yml", ".yaml", ".js"}

_HOST = re.compile(r"https?://([A-Za-z0-9.\-]+)")

# ④ 코드에서 import 되면 "밖으로 나가는 것"으로 간주하는 라이브러리(최상위 이름 또는 `google.genai` 형태).
#    🔴 고정 목록입니다 — 여기 없는 새 네트워크 라이브러리는 이 검사가 못 봅니다(머리말 "못 잡는 것").
NETWORK_LIBRARIES = (
    "FinanceDataReader", "yfinance", "pykrx", "pandas_datareader",
    "supabase", "google.genai", "googleapiclient", "google_auth_oauthlib", "google.auth", "google.oauth2",
    "requests", "httpx", "aiohttp", "urllib.request", "urllib3", "feedparser", "websocket", "websockets",
)

# 부록 표의 3열 값. 문서 서식과 맞물려 있습니다.
_YES = "예"
_NO = "아니오"


# =====================================================================================
# 코드 스캐너
# =====================================================================================
def _iter_code_files():
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(root) / name
            if path.suffix in CODE_SUFFIXES:
                yield path


def _docstring_ids(tree):
    """모듈·함수·클래스의 docstring 노드 id 집합 — 이 문자열 상수는 스캔에서 뺍니다."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):
                value = getattr(body[0], "value", None)
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _python_string_constants(source):
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.value


def _hosts_in_file(path):
    """파일 하나에서 (호스트 소문자) 집합을 돌려줍니다 — 위 머리말 📌 규칙대로."""
    text = path.read_text(encoding="utf-8")
    hosts = set()
    if path.suffix == ".py":
        for literal in _python_string_constants(text):
            hosts.update(h.lower() for h in _HOST.findall(literal))
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            hosts.update(h.lower() for h in _HOST.findall(line))
    return hosts


def scan_code_hosts():
    """호스트 → 그 호스트가 적힌 파일(저장소 상대 경로) 정렬 목록."""
    found = {}
    for path in _iter_code_files():
        for host in _hosts_in_file(path):
            found.setdefault(host, set()).add(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return {h: sorted(files) for h, files in found.items()}


def _imported_modules(path):
    """`.py` 파일의 import 대상(점 표기 전체 이름)들."""
    names = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            for alias in node.names:  # `from google import genai` → google.genai
                names.add(f"{node.module}.{alias.name}")
    return names


def scan_network_library_imports():
    """코드가 import 하는 NETWORK_LIBRARIES 항목 → 파일 목록."""
    found = {}
    for path in _iter_code_files():
        if path.suffix != ".py":
            continue
        modules = _imported_modules(path)
        for lib in NETWORK_LIBRARIES:
            if any(m == lib or m.startswith(lib + ".") for m in modules):
                found.setdefault(lib, set()).add(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return {k: sorted(v) for k, v in found.items()}


# =====================================================================================
# 문서 파서 — 부록 A·B 의 "기계가 읽는 목록"
# =====================================================================================
def _registry_block(name):
    text = INVENTORY_MD.read_text(encoding="utf-8")
    match = re.search(rf"<!-- BEGIN:{name} -->(.*?)<!-- END:{name} -->", text, re.S)
    return match.group(1) if match else None


def _table_rows(block):
    """마크다운 표에서 (셀 목록) 행들 — 머리글·구분선 제외, 셀은 strip."""
    rows = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # |---|---| 구분선
        rows.append(cells)
    return rows[1:] if rows else []  # 첫 행은 머리글


_BACKTICK = re.compile(r"`([^`]+)`")


def host_registry():
    """부록 A → {호스트: (분류, 코드에_있음 bool)}. 서식이 깨지면 빈 dict 가 아니라 예외."""
    block = _registry_block("HOST_REGISTRY")
    assert block is not None, "DATA_SOURCES_INVENTORY.md 에 HOST_REGISTRY 블록이 없습니다"
    out = {}
    for cells in _table_rows(block):
        assert len(cells) == 3, f"부록 A 행은 3열이어야 합니다: {cells}"
        host_match = _BACKTICK.search(cells[0])
        assert host_match, f"부록 A 1열은 백틱 호스트여야 합니다: {cells}"
        assert cells[2] in (_YES, _NO), f"부록 A 3열은 '{_YES}'/'{_NO}' 만 허용: {cells}"
        out[host_match.group(1).lower()] = (cells[1], cells[2] == _YES)
    return out


def library_registry():
    """부록 B → (requirements 이름 집합, import 이름 집합). 이름은 소문자·`-` 통일."""
    block = _registry_block("LIBRARY_REGISTRY")
    assert block is not None, "DATA_SOURCES_INVENTORY.md 에 LIBRARY_REGISTRY 블록이 없습니다"
    req_names, import_names = set(), set()
    for cells in _table_rows(block):
        assert len(cells) == 3, f"부록 B 행은 3열이어야 합니다: {cells}"
        req = _BACKTICK.search(cells[0])
        imp = _BACKTICK.search(cells[1])
        if req:
            req_names.add(_norm_pkg(req.group(1)))
        if imp:
            import_names.add(imp.group(1))
    return req_names, import_names


def _norm_pkg(name):
    return name.strip().lower().replace("_", "-")


def requirements_packages():
    """`requirements.txt` 의 패키지 이름(버전 지정자·주석 제거, 정규화)."""
    names = []
    for raw in REQUIREMENTS_TXT.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~;\[\s]", line, 1)[0]
        if name:
            names.append(_norm_pkg(name))
    return names


def spec_section_0_3_2():
    """ENGINEERING_SPEC.md 의 `### 0-3-2.` 절 본문(다음 `### ` 제목 전까지)."""
    text = SPEC_MD.read_text(encoding="utf-8")
    match = re.search(r"^### 0-3-2\..*?(?=^### )", text, re.S | re.M)
    assert match, "ENGINEERING_SPEC.md 에서 §0-3-2 절을 못 찾았습니다"
    return match.group(0)


# =====================================================================================
# 0. 스캐너 자신이 조용히 빈손이 되지 않게 (§0-1)
# =====================================================================================
def test_scanner_actually_found_code_and_hosts():
    """
    이 파일이 막으려는 결함의 가장 뻔한 재현은 **스캐너가 아무것도 못 찾고 전부 통과하는 것**
    입니다(디렉터리 이름 하나, 확장자 하나면 충분합니다). 2026-09-08 첫 재고에서 호스트 15개·
    코드 파일 수십 개를 찾았으므로, 그보다 크게 적으면 스캐너가 깨진 것으로 봅니다.
    """
    files = list(_iter_code_files())
    assert len(files) >= 40, f"스캔한 코드 파일이 {len(files)}개뿐입니다 — 경로 계산이 깨졌습니다"
    hosts = scan_code_hosts()
    assert len(hosts) >= 10, f"코드에서 찾은 호스트가 {len(hosts)}개뿐입니다(2026-09-08 기준 15개): {sorted(hosts)}"
    assert INVENTORY_MD.is_file(), "DATA_SOURCES_INVENTORY.md 가 없습니다"
    registry = host_registry()
    assert len(registry) >= 15, f"부록 A 가 {len(registry)}행뿐입니다 — 블록 서식이 깨졌을 가능성"
    req_names, import_names = library_registry()
    assert len(req_names) >= 10 and len(import_names) >= 10, "부록 B 가 비었거나 서식이 깨졌습니다"


# =====================================================================================
# 1. 🔴 핵심 — 코드 속 모든 호스트가 재고 문서에 있을 것
# =====================================================================================
def test_every_host_in_code_is_listed_in_inventory():
    """
    🔴 **이 파일의 존재 이유.** 코드에 새 바깥 주소를 넣고 `DATA_SOURCES_INVENTORY.md` 부록 A 에
    안 적으면 여기서 빨간불이 납니다.

    고치는 법:
      1) `DATA_SOURCES_INVENTORY.md` §2 표에 한 줄 — 무엇을 가져오나·누가 읽나·폴백·관리 주체
      2) 부록 A(HOST_REGISTRY) 에 `| `호스트` | 요청|링크만|브라우저 | 예 |` 한 줄
      3) "요청"이면 `ENGINEERING_SPEC.md` §0-3-2 에도 호스트와 매너 장치를 한 줄
    링크·브라우저 쪽 주소라도 **빼지 말고 분류해서** 적습니다(머리말 📌).
    """
    registry = host_registry()
    unlisted = {h: files for h, files in scan_code_hosts().items() if h not in registry}
    assert not unlisted, (
        f"\n🔴 재고 문서에 없는 바깥 주소 {len(unlisted)}건 — 새 외부 의존성을 추가하고 목록을\n"
        f"   안 고쳤을 때 정확히 이 모양이 됩니다(2026-09-08 FDR 사고의 재현).\n\n"
        + "".join(f"       - {h}  ← {', '.join(files)}\n" for h, files in sorted(unlisted.items()))
        + "\n   고치는 법: DATA_SOURCES_INVENTORY.md §2 표 + 부록 A + (요청이면) ENGINEERING_SPEC §0-3-2.\n"
    )


def test_inventory_claims_about_code_presence_are_true():
    """
    반대 방향 — 문서가 낡지 않았는지.
      · "코드에 문자열로 있음 = 예" 인데 코드에 없으면 → 죽은 항목(출처를 지웠는데 문서를 안 고침).
      · "아니오"(라이브러리·pip 뒤) 인데 코드에 있으면 → 누군가 그 주소를 직접 부르기 시작한 것.
        문서의 "라이브러리 뒤" 설명이 거짓이 되므로 고치게 합니다.
    """
    in_code = scan_code_hosts()
    for host, (kind, claimed_present) in sorted(host_registry().items()):
        if claimed_present:
            check(host in in_code, f"부록 A '{host}'(코드에 있음=예)가 실제로 코드에 있음",
                  "(죽은 항목 — 출처를 지웠으면 부록 A 에서도 지우세요)")
        else:
            check(host not in in_code, f"부록 A '{host}'(코드에 있음=아니오)가 실제로 코드에 없음",
                  f"(직접 부르기 시작했으면 '예'로 바꾸고 §2-A 로 옮기세요: {in_code.get(host)})")


# =====================================================================================
# 2. 패키지·라이브러리 — 새 의존성은 반드시 분류될 것
# =====================================================================================
def test_every_requirement_is_classified_in_inventory():
    """
    `requirements.txt` 에 패키지를 추가하면 부록 B 에 "밖으로 나가는가"를 적어야 합니다.
    2026-09-08 FDR 처럼 **라이브러리 하나 뒤에 주소가 넷** 숨어 있을 수 있으므로, 이름을 적는
    순간 "이게 어디로 가지?"를 한 번은 묻게 하는 장치입니다. (어디로 가는지는 이 검사가 못 봅니다.)
    """
    req_names, _ = library_registry()
    packages = requirements_packages()
    assert len(packages) >= 5, f"requirements.txt 파싱 결과가 {packages} — 파서가 깨졌습니다"
    missing = [p for p in packages if p not in req_names]
    assert not missing, (
        f"\n🔴 requirements.txt 에 있는데 DATA_SOURCES_INVENTORY.md 부록 B 에 분류되지 않은 패키지:\n"
        + "".join(f"       - {p}\n" for p in missing)
        + "\n   부록 B 에 한 줄 추가하고 '밖으로 나가는가'를 적으세요. 모르면 그 패키지 소스를 읽어\n"
        "   확인한 뒤 적습니다 — 확인 없이 '아니오'라고 적지 않습니다(§0-1).\n"
    )


def test_every_network_library_import_is_listed_in_inventory():
    """코드가 import 하는 네트워크 성격 라이브러리(고정 목록)는 부록 B 의 import 이름 열에 있어야 합니다."""
    _, import_names = library_registry()
    found = scan_network_library_imports()
    assert found, "NETWORK_LIBRARIES 중 하나도 import 되지 않았다고 나옵니다 — 스캐너가 깨졌습니다"
    for lib, files in sorted(found.items()):
        check(lib in import_names, f"부록 B 에 import '{lib}' 등재됨", f"(사용 파일: {', '.join(files)})")


# =====================================================================================
# 3. §0-3-2 와 어긋나지 않을 것
# =====================================================================================
def test_every_request_host_appears_in_spec_0_3_2():
    """
    부록 A 에서 '요청'으로 분류한 호스트는 `ENGINEERING_SPEC.md` §0-3-2("우리가 접속하는 대상과
    각각의 매너 장치") 본문에도 이름이 있어야 합니다. 2026-09-08 이전에는 이 목록이 실제와
    달랐고(빠진 것 5종 이상), 그것을 아무도 몰랐습니다.
    """
    section = spec_section_0_3_2()
    for host, (kind, _) in sorted(host_registry().items()):
        if kind.startswith("요청"):
            check(host in section, f"§0-3-2 본문에 '{host}' 등장", "(재고 문서와 §0-3-2 가 어긋남)")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests

    discover_and_run_module_tests(
        sys.modules[__name__],
        on_skip=lambda names: print(f"  ⏭️ 픽스처가 필요해 건너뜀: {names}"),
    )
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
