# tests/test_agent_registry.py
"""
🧭 에이전트 등록부 정합성 — "새 모듈을 만들었는데 담당 에이전트가 없다"를 구조적으로 막습니다 (2026-09-07)

⚠️ 이 파일이 왜 생겼는가

2026-09-07 에 `CLAUDE.md` · `AGENT_ORCHESTRATION.md` · `.claude/agents/*.md` 로 에이전트 계층을
만들면서, "새 모듈을 추가할 때"의 5단계 절차를 `AGENT_ORCHESTRATION.md` §2-6 에 **글로만** 적어
뒀습니다. 그 상태는 이 저장소가 이미 두 번 겪은 실패 모양과 같습니다 —
`tests/conftest.py` 머리말에 적힌 하네스 복사 사고(2026-08-21 · 2026-08-30)도, 낡은 채 방치됐던
`PROJECT_STATUS.md` §2 파일 구조 표(2026-08-13 → 2026-09-07 에 발견)도, 전부 **"사람이 기억해야만
지켜지는 규칙"** 이었습니다. 문서는 갱신을 강제하지 않으면 반드시 낡습니다.

그래서 절차를 검사로 바꿉니다. 이 파일이 지키는 것:

  ① 🔴 **주인 없는 파일이 없다** — 화면·수집기·배치·워크플로우·`utils/`·`web/` 의 모든 파일이
     정확히 한 에이전트의 "소유 파일" 목록에 들어 있어야 합니다. 새 모듈을 만들고 에이전트를
     안 만들면 **여기서 빨간불이 납니다.** 이것이 이 파일의 존재 이유입니다.
  ② 두 에이전트가 같은 파일을 소유하지 않는다 (경계가 겹치면 인계 규칙이 무의미해집니다).
  ③ 에이전트 정의 파일의 frontmatter 가 유효하고 `name` 이 파일명과 일치한다.
  ④ 모든 에이전트가 `CLAUDE.md` 라우팅 표와 `AGENT_ORCHESTRATION.md` §2-2 표에 **양쪽 다**
     등장한다 (한쪽만 있으면 "에이전트는 있는데 아무도 그리로 안 보내는" 상태가 됩니다).
  ⑤ 에이전트 문서가 가리키는 파일 경로가 저장소에 실재한다 (죽은 경로 = 다음 세션의 헛수고).
  ⑥ 동결된 `macro` 에이전트에는 쓰기 도구가 없다 (오너 지시 2026-08-10).

📌 소유 판정 규칙 — 문서 서식과 직결되므로 바꾸려면 여기와 문서를 같이 고치세요:
   소유는 **`## 소유 파일 ...` 또는 `## 담당 범위 · 소유 파일` 섹션 안에서만** 인정합니다.
   `## 읽기만 ...` 섹션에 적힌 경로는 소유가 아니라 "남의 파일"이라 일부러 제외합니다.
   (처음에는 소유 섹션 안에서 `⚠️` 줄만 빼는 방식을 썼는데, `⚠️` 는 평범한 경고에도 쓰이는
   기호라 정상 소유 파일까지 걸러졌습니다 — 기호 규칙 대신 **섹션 구조**로 분리했습니다.)

실행: python -m pytest tests/test_agent_registry.py -v
     python tests/test_agent_registry.py
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다(2026-08-30 공용화).
# ⚠️ `FAILURES` 와 `check` 를 **둘 다** 가져와야 `test_suite_integrity.py` 의 Check A 가
#    이 파일을 하네스 사용 파일로 인식합니다 — `check` 만 가져오면 Check A 가 이 파일을
#    통째로 건너뛰어(skip) 감시망에 구멍이 생깁니다(실제로 처음 작성했을 때 그랬습니다).
from conftest import FAILURES, check  # noqa: E402,F401

AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
ORCHESTRATION_MD = REPO_ROOT / "AGENT_ORCHESTRATION.md"

AGENT_FILES = sorted(p for p in AGENTS_DIR.glob("*.md") if not p.name.startswith("_"))

# 소유 섹션을 여는 제목. `## 읽기만 ...` 은 의도적으로 제외합니다(위 머리말 📌).
_OWNERSHIP_HEADING = re.compile(r"^## (?:소유 파일|담당 범위 · 소유 파일)", re.M)
_SECTION = re.compile(
    r"^## (?:소유 파일|담당 범위 · 소유 파일).*?(?=^## |\Z)", re.S | re.M
)
# 문서에 백틱으로 적힌 코드/설정 파일 경로 (축약 표기 허용 — 아래에서 basename 으로 대조).
_PATH = re.compile(
    r"`((?:utils/|web/|web/pages/|web/components/|tests/|sql/|data/|\.github/workflows/)?"
    r"[A-Za-z0-9_./\-]+\.(?:py|yml))`"
)

# 소유권을 반드시 누군가 가져야 하는 파일들. 새 모듈은 거의 전부 이 안에 떨어집니다.
OWNED_GLOBS = (
    "web/pages/*.py",
    "web/*.py",
    "utils/*.py",
    ".github/workflows/*.yml",
    "collector_*.py",
    "run_*.py",
    "scrape_*.py",
    "crawl_*.py",
    "corp_*.py",
    "probe_*.py",
    "main.py",
)

# 소유 대상에서 뺄 파일 — 이유를 반드시 함께 적습니다(조용한 예외 금지, §0-1).
OWNERSHIP_EXEMPT = {
    "__init__.py": "패키지 표식일 뿐 로직이 없음",
}


def _agent_name(path: Path) -> str:
    return path.name[: -len(".md")]


def _frontmatter(path: Path) -> dict:
    """`---` 로 감싼 YAML 머리말을 얕게 파싱합니다(값에 `:` 가 있어도 첫 `:` 에서만 자름)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}
    out = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _ownership_paths(path: Path) -> set:
    """이 에이전트가 **소유**한다고 선언한 파일 경로들(소유 섹션 안에서만)."""
    match = _SECTION.search(path.read_text(encoding="utf-8"))
    if not match:
        return set()
    return set(_PATH.findall(match.group(0)))


def _owner_index() -> dict:
    """basename → 그 파일을 소유한다고 선언한 에이전트 이름 집합."""
    index = {}
    for path in AGENT_FILES:
        name = _agent_name(path)
        for declared in _ownership_paths(path):
            index.setdefault(os.path.basename(declared), set()).add(name)
    return index


def _repo_basenames() -> dict:
    """저장소 실제 파일 basename → 경로 목록 (축약 표기 대조용)."""
    index = {}
    skip = {".git", "__pycache__", "node_modules", ".pytest_cache", "archive"}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            index.setdefault(f, []).append(Path(root) / f)
    return index


# =====================================================================================
# 0. 스캐너 자신이 조용히 빈손이 되지 않게 (§0-1)
# =====================================================================================
def test_scanner_actually_found_the_agent_registry():
    """
    이 파일이 막으려는 결함의 가장 뻔한 재현은 **스캐너가 아무것도 못 찾고 전부 통과하는 것**
    입니다(경로 오타·디렉터리 이동 한 번이면 충분합니다). 목록이 비지 않았다는 사실을
    독립된 테스트로 못 박아 둡니다 — `tests/test_suite_integrity.py` 와 같은 방식입니다.
    """
    assert AGENTS_DIR.is_dir(), f".claude/agents/ 를 못 찾음: {AGENTS_DIR}"
    assert len(AGENT_FILES) >= 10, (
        f".claude/agents/*.md 를 {len(AGENT_FILES)}개만 찾았습니다 — 2026-09-07 기준 12개입니다. "
        f"경로 계산이 깨졌거나 에이전트 정의가 대량으로 사라진 상황입니다. 스캔 경로: {AGENTS_DIR}"
    )
    assert CLAUDE_MD.is_file(), "CLAUDE.md 가 없습니다 — 모든 세션의 진입점입니다"
    assert ORCHESTRATION_MD.is_file(), "AGENT_ORCHESTRATION.md 가 없습니다"


# =====================================================================================
# 1. 🔴 핵심 — 주인 없는 파일이 없을 것
# =====================================================================================
def test_every_module_file_has_exactly_one_owning_agent():
    """
    🔴 **이 파일의 존재 이유.** 새 기능(= 새 모듈)을 만들면서 담당 에이전트를 등록하지 않으면
    여기서 빨간불이 납니다.

    고치는 법 — `AGENT_ORCHESTRATION.md` §2-6 의 5단계를 따르세요:
      1) `.claude/agents/<이름>.md` 생성 (`.claude/agents/_TEMPLATE.md` 복사)
      2) 그 파일의 "## 소유 파일" 섹션에 새 파일 경로를 백틱으로 적기
      3) `CLAUDE.md` §3 라우팅 표에 한 줄
      4) `AGENT_ORCHESTRATION.md` §2-2 표에 한 줄
      5) `PROJECT_STATUS.md` §2 파일 구조 표에 새 파일

    기존 에이전트가 맡는 게 맞다면 그 에이전트의 소유 목록에 한 줄만 추가하면 됩니다.
    """
    owner = _owner_index()
    orphans = []
    for pattern in OWNED_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if path.name in OWNERSHIP_EXEMPT:
                continue
            if path.name not in owner:
                orphans.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))

    assert not orphans, (
        f"\n🔴 담당 에이전트가 없는 파일 {len(orphans)}건 — 새 모듈을 만들고 에이전트를\n"
        f"   등록하지 않았을 때 정확히 이 모양이 됩니다.\n\n"
        + "".join(f"       - {o}\n" for o in orphans)
        + "\n   고치는 법: AGENT_ORCHESTRATION.md §2-6 의 5단계. 새 에이전트가 필요하면\n"
        "   `.claude/agents/_TEMPLATE.md` 를 복사해서 채우고, 기존 에이전트가 맡는 게\n"
        "   맞다면 그 파일의 '## 소유 파일' 섹션에 경로를 한 줄 추가하세요.\n"
    )


def test_no_file_is_owned_by_two_agents():
    """경계가 겹치면 인계 규칙(`AGENT_ORCHESTRATION.md` §2-3)이 무의미해집니다.
    남의 파일을 참고만 한다면 소유 섹션이 아니라 `## 읽기만` 섹션에 적으세요."""
    shared = {k: sorted(v) for k, v in _owner_index().items() if len(v) > 1}
    assert not shared, (
        "\n🔴 두 에이전트가 같은 파일을 소유한다고 선언했습니다:\n"
        + "".join(f"       - {f}: {' vs '.join(names)}\n" for f, names in sorted(shared.items()))
        + "\n   한 파일의 주인은 한 명입니다. 참고만 하는 쪽은 '## 읽기만' 섹션으로 옮기세요.\n"
    )


def test_every_agent_declares_an_ownership_section():
    """소유 섹션이 없으면 위 두 검사가 그 에이전트를 **조용히 건너뜁니다** — 검사망에 구멍이
    생기는 것이므로 skip 이 아니라 실패로 다룹니다 (§0-1)."""
    for path in AGENT_FILES:
        source = path.read_text(encoding="utf-8")
        check(
            bool(_OWNERSHIP_HEADING.search(source)),
            f"{path.name} 에 '## 소유 파일' 섹션이 있음",
            "(없으면 이 파일의 소유권 검사가 그 에이전트를 통째로 건너뜁니다)",
        )


# =====================================================================================
# 2. 정의 파일 자체의 유효성
# =====================================================================================
def test_agent_frontmatter_is_valid_and_name_matches_filename():
    seen = {}
    for path in AGENT_FILES:
        fm = _frontmatter(path)
        stem = _agent_name(path)
        check(bool(fm), f"{path.name}: frontmatter 파싱됨")
        check(fm.get("name") == stem, f"{path.name}: name 이 파일명과 일치",
              f"(name={fm.get('name')!r}, 파일명={stem!r})")
        check(bool(fm.get("description")), f"{path.name}: description 있음")
        check(bool(fm.get("tools")), f"{path.name}: tools 있음")
        seen.setdefault(fm.get("name"), []).append(path.name)

    duplicates = {n: f for n, f in seen.items() if len(f) > 1}
    assert not duplicates, f"에이전트 이름 중복: {duplicates}"


def test_frozen_macro_agent_has_no_write_tools():
    """매크로는 오너 지시(2026-08-10)로 동결 상태입니다. 고쳐야 하는 상황 자체가
    '오너 승인이 먼저 필요하다'는 신호이므로, 쓰기 도구를 주지 않는 것이 설계입니다."""
    macro = AGENTS_DIR / "macro.md"
    if not macro.is_file():
        return  # 동결 해제로 파일이 사라졌다면 이 검사도 의미가 없습니다
    tools = _frontmatter(macro).get("tools", "")
    for forbidden in ("Edit", "Write", "NotebookEdit"):
        check(forbidden not in tools,
              f"macro 에이전트에 쓰기 도구 {forbidden} 없음", f"(tools={tools!r})")


# =====================================================================================
# 3. 라우팅 — 양쪽 문서에 모두 등록돼 있을 것
# =====================================================================================
def test_every_agent_is_routed_from_both_entry_documents():
    """
    `CLAUDE.md` 에만 있으면 정의가 없는 에이전트로 보내게 되고,
    `.claude/agents/` 에만 있으면 **아무도 그리로 안 보냅니다.** 양쪽을 다 요구합니다.
    """
    claude_text = CLAUDE_MD.read_text(encoding="utf-8")
    orch_text = ORCHESTRATION_MD.read_text(encoding="utf-8")
    for path in AGENT_FILES:
        name = _agent_name(path)
        check(f"`{name}`" in claude_text, f"CLAUDE.md 라우팅 표에 `{name}` 등재됨")
        check(f"`{name}`" in orch_text, f"AGENT_ORCHESTRATION.md §2-2 에 `{name}` 등재됨")


def test_routing_tables_do_not_reference_missing_agents():
    """반대 방향 — 문서가 가리키는 에이전트 이름이 실제 정의 파일로 존재하는지."""
    known = {_agent_name(p) for p in AGENT_FILES}
    referenced = set()
    pattern = re.compile(r"`\.claude/agents/([a-z0-9-]+)\.md`")
    for doc in (CLAUDE_MD, ORCHESTRATION_MD):
        referenced |= set(pattern.findall(doc.read_text(encoding="utf-8")))
    missing = sorted(referenced - known - {"<이름>"})
    assert not missing, f"문서가 가리키는 에이전트 정의가 없습니다: {missing}"


# =====================================================================================
# 4. 죽은 경로 금지 — 문서가 가리키는 파일은 실재할 것
# =====================================================================================
def test_agent_documents_do_not_reference_nonexistent_files():
    """
    없는 파일을 가리키는 지시서는 다음 세션을 헛수고시킵니다 — `PROJECT_STATUS.md` §2 가
    `archive/` 로 옮긴 `app.py`·`views/*` 를 현역처럼 가리키던 것과 같은 부패입니다.
    축약 표기(`db.py` = `utils/db.py`)를 허용하므로 basename 으로도 대조합니다.
    """
    repo = _repo_basenames()
    docs = [CLAUDE_MD, ORCHESTRATION_MD] + AGENT_FILES
    dead = []
    for doc in docs:
        for declared in sorted(set(_PATH.findall(doc.read_text(encoding="utf-8")))):
            if "*" in declared:
                continue
            if (REPO_ROOT / declared).exists():
                continue
            if os.path.basename(declared) in repo:
                continue
            dead.append(f"{doc.name}: {declared}")
    assert not dead, (
        "\n🔴 문서가 저장소에 없는 파일을 가리킵니다:\n"
        + "".join(f"       - {d}\n" for d in dead)
    )


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
