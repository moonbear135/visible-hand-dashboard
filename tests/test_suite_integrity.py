# tests/test_suite_integrity.py
"""
🧪 테스트 스위트 자기 검증 — "이 테스트, 사실 한 번도 실행된 적이 없었다" 부류의 결함을
   구조적으로 막는 메타 테스트입니다.

⚠️ 이 파일이 왜 있는가 (실제 사고 이력 — 지어낸 가정이 아닙니다)

이 저장소에서 지금까지 **같은 뿌리의 결함이 세 가지 다른 모양으로 세 번** 나왔습니다.
전부 "테스트가 빨간불을 내야 할 상황에서 조용히 초록불이었다" — 즉 ENGINEERING_SPEC.md
§0-1("실패를 정상 상태로 위장하지 않기")을 **테스트 코드 자신이** 어긴 사례입니다.
프로덕션 버그와 달리 이 부류는 화면에도 로그에도 흔적이 안 남아, 다음 재감사가 소스를
한 줄씩 읽기 전까진 영원히 안 드러납니다.

  (A) `check()`/`FAILURES` 무음 통과 — `check(cond, label)`은 실패를 `FAILURES`에 **적기만**
      하고 절대 예외를 던지지 않습니다. 그 목록을 실제로 검사해 죽는 코드가
      `if __name__ == "__main__": main()` 안에만 있으면, pytest는 `main()`을 절대 부르지
      않으므로 **파일 전체가 무엇을 검사하든 항상 초록불**입니다.
      → 2026-08-21 `test_data_source.py`에서 처음 발견(#TASK_HISTORY 참조), 표준 방어인
        `@pytest.fixture(autouse=True)`(테스트 전후 `FAILURES` 증가분 확인)를 파일마다
        **손으로 복사**해 넣는 방식이라, 2026-08-30 재감사(TASK_HISTORY `### #168` H-1)에서
        `test_us_stocks_page.py` 하나가 그 복사에서 빠져 있던 게 다시 발견됐습니다.
      → 그래서 2026-08-30, 그 하네스(`FAILURES` 목록 · `check()` · autouse 픽스처)를 파일마다
        복사하지 않고 `tests/conftest.py` **한 곳**으로 모았습니다(9개 파일). pytest 는
        conftest 의 autouse 픽스처를 같은 디렉터리의 모든 테스트에 자동 적용하므로, 그때부터
        "복사 하나 빠뜨림"이라는 사고 자체가 구조적으로 불가능해집니다.
        ⚠️ **Check A 도 그 작업에서 함께 갱신했습니다.** 하네스를 conftest 로 옮기면 각 파일
        자신의 AST 에서 `FAILURES`/`check` 가 사라지므로, 갱신하지 않았다면 Check A 가
        "이 파일은 하네스를 안 쓴다"고 오판해 9개 파일을 **검사 대상에서 통째로 빼버렸을
        것입니다**(스위트는 초록불인 채로 — 실제로 옮기고 나서 갱신 전에 돌려보니 Check A
        9건이 PASSED 에서 SKIPPED 로 조용히 바뀌었습니다). 무음 통과를 잡는 검사가 스스로
        무음이 되는, H-1 과 정확히 같은 모양의 결함입니다. 지금은
        `from conftest import FAILURES, check` 로 가져다 쓰는 파일도 대상으로 잡고, 그런
        파일은 **conftest 쪽에 진짜로 하네스 3종이 있고 그 autouse 픽스처가 실제로 적용되고
        있는지**까지 확인한 뒤에야 합격시킵니다(`_conftest_harness_defects()`).

  (B) `main()`의 수동 함수 목록 노후화 — `python tests/test_x.py` 직접 실행 경로에서
      `main()`이 부를 `test_*` 목록을 손으로 나열하다 실제 정의와 어긋난 경우입니다.
      → TASK_HISTORY `### #168` H-3: `test_macro_scoring.py`(29개 중 12개 미호출)·
        `test_report.py`(23개 중 3개)·`test_scorecard.py`(20개 중 2개)·
        `test_stock_history.py`(17개 중 1개). pytest 경로는 정상 수집하므로 무영향이지만,
        문서화된 직접 실행 경로가 "✅ 전체 통과"를 찍으면서 회귀 12건을 건너뛰고 있었습니다.
        `tests/_test_discovery.py`(`inspect`로 자동 수집)로 근본 해결됨(§0-3-10).

  (C) pytest 명명 규약 미준수 — 테스트 본체가 `test_`로 시작하지 않는 이름의 함수 안에
      들어 있으면 pytest는 **그 파일에서 0건을 수집**하고, 그것을 실패가 아니라 정상으로
      보고합니다("no tests ran").
      → 2026-08-29 M-14: `tests/test_quant.py`의 PEGY 카드 §0-1 회귀 방지선 8건이 전부
        `run_golden_tests()` 한 함수 안에 있어 CI에서 **한 번도 실행된 적이 없었고**,
        파일 자신의 직접 실행 경로는 "🎉 모든 테스트 통과"를 찍고 있어서 아무도 몰랐습니다.
        (그 파일 독스트링에 경위가 그대로 남아 있습니다.)

세 번 다 "사람이 몇 주에 한 번 재감사하다가 우연히 발견"으로 잡혔습니다. 오너 지시(2026-08-30):
사람의 기억이나 채팅 스레드에 의존하지 않는 **영구적·구조적 방어선**을 만들 것. 이 파일이
그 방어선이며, 스스로도 평범한 pytest 대상이라 매 실행마다 자동으로 재검사됩니다.

📐 설계 원칙
  - 이 파일은 `tests/` 안의 `test_*.py`를 **전수** 훑습니다(자기 자신 포함 — 예외를 두면
    그 예외가 곧 다음 구멍이 됩니다). 저장소 관례대로 `archive/`는 대상이 아닙니다.
  - A·B는 **AST 정적 분석**으로 봅니다. import해서 확인하는 방식은 파일마다 import 부작용
    (네트워크·전역 상태·nicegui 컨텍스트)이 있어 신뢰할 수 없습니다.
  - C는 **pytest 자신에게 물어봅니다**(아래 `_pytest_collection()` 주석 참고).
  - 파일 목록을 `parametrize`로 펼쳐, 실패했을 때 테스트 ID가 **문제 파일 이름을 그대로**
    말하게 합니다(한 덩어리 assert로 뭉뚱그리지 않기 — 그 자체가 §0-1의 취지).
"""
import ast
import functools
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# `tests/`의 최상위만 훑습니다(`glob`은 비재귀 — 하위에 `archive/`가 생겨도 딸려오지 않음).
# 저장소 관례인 `pytest --ignore=archive`와 같은 범위입니다.
TEST_FILES = sorted(TESTS_DIR.glob("test_*.py"))
TEST_FILE_IDS = [p.name for p in TEST_FILES]

# 공용 하네스(`FAILURES` 목록 · `check()` · autouse 픽스처)가 사는 곳. Check A 는 이 파일에서
# 하네스를 가져다 쓰는 테스트 파일도 검사 대상으로 잡습니다(2026-08-30 — 위 (A) 참고).
CONFTEST_PATH = TESTS_DIR / "conftest.py"


# =====================================================================================
# 0. 스캐너 자신이 조용히 빈손이 되지 않게 (§0-1)
# =====================================================================================
def test_scanner_actually_found_the_test_files():
    """
    이 메타 테스트가 막으려는 결함의 가장 뻔한 재현이 바로 **이 파일 자신이 아무 파일도
    못 찾고 전부 통과하는 것**입니다(경로 오타·디렉터리 이동 한 번이면 충분합니다).
    `parametrize`는 목록이 비면 테스트를 0개 만들고 pytest는 그걸 실패로 치지 않으므로,
    목록이 비지 않았다는 사실을 **독립된 테스트**로 못 박아 둡니다.
    """
    assert TESTS_DIR.is_dir(), f"tests/ 디렉터리를 못 찾음: {TESTS_DIR}"
    assert len(TEST_FILES) >= 20, (
        f"tests/test_*.py 를 {len(TEST_FILES)}개만 찾았습니다 — 2026-08-30 기준 34개입니다. "
        f"경로 계산이 깨졌거나 테스트 파일이 대량으로 사라진 상황입니다. 스캔 경로: {TESTS_DIR}"
    )
    # 이 파일 자신도 반드시 대상에 들어 있어야 합니다(자기 예외 금지).
    assert Path(__file__).name in TEST_FILE_IDS


# =====================================================================================
# AST 공용 헬퍼 — 파일을 import하지 않고 소스만 읽습니다
# =====================================================================================
@functools.lru_cache(maxsize=None)
def _parse(path_str):
    """파일당 한 번만 파싱합니다(A·B 두 검사가 같은 트리를 나눠 씁니다)."""
    source = Path(path_str).read_text(encoding="utf-8")
    return ast.parse(source, filename=path_str)


def _toplevel_functions(tree):
    """모듈 최상위에 정의된 함수만. 클래스 안·함수 안 중첩 정의는 대상이 아닙니다."""
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _module_level_assigned_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _called_names(node):
    """`node` 아래에서 이름으로 직접 호출되는 함수 이름 전부(`f()` 형태). 중첩·조건문 안까지."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            out.add(sub.func.id)
    return out


def _references_name(node, wanted):
    """`node` 아래에서 `wanted` 라는 이름을 한 번이라도 읽는지."""
    return any(isinstance(s, ast.Name) and s.id == wanted for s in ast.walk(node))


def _required_positional_arg_count(fn):
    """
    기본값 없는 위치 인자 개수. `tests/_test_discovery.py`가 "직접 호출 불가 → 건너뜀"으로
    판정하는 기준(`inspect` 쪽 POSITIONAL_ONLY/POSITIONAL_OR_KEYWORD + default 없음)과
    **같은 규칙**을 AST로 옮긴 것입니다 — 두 곳의 기준이 어긋나면 Check B가 오탐합니다.
    """
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    return max(0, len(positional) - len(args.defaults))


def _test_function_nodes(tree):
    return [f for f in _toplevel_functions(tree) if f.name.startswith("test_")]


# =====================================================================================
# 1. Check A — `check()`/`FAILURES` 하네스에는 무음 통과 방지 장치가 반드시 있어야 함
# =====================================================================================
def _defines_local_failures_list(tree):
    """이 파일이 **자기 모듈 최상위에** `FAILURES` 목록을 직접 갖고 있는지."""
    return any(n.strip("_").upper() == "FAILURES" for n in _module_level_assigned_names(tree))


def _defines_local_check(tree):
    """이 파일이 **자기 모듈 최상위에** `check()` 함수를 직접 정의하는지."""
    return any(f.name.lstrip("_") == "check" for f in _toplevel_functions(tree))


def _imports_harness_from_conftest(tree):
    """
    `from conftest import FAILURES, check` 처럼 **공용 하네스를 `tests/conftest.py` 에서
    가져다 쓰는지**. 반환: (FAILURES 를 가져오는가, check 를 가져오는가).

    2026-08-30 하네스를 conftest 로 모으면서 생긴 인식 경로입니다. 이게 없으면, 하네스를
    옮긴 파일은 자기 AST 에 `FAILURES`/`check` 가 없으므로 Check A 가 "하네스를 안 쓴다"고
    보고 **검사 대상에서 빼버립니다** — 위 (A) 참고.

    함수 안에서 import 하는 형태까지 잡으려고 `ast.walk` 로 전체를 훑습니다(모듈 최상위만
    보면 그 변형이 검사망을 빠져나갑니다 — 느슨해지는 방향으로는 열지 않습니다).
    """
    got_list = got_check = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in ("conftest", "tests.conftest"):
            continue
        for alias in node.names:
            bound = alias.asname or alias.name
            if bound.strip("_").upper() == "FAILURES":
                got_list = True
            if bound.lstrip("_") == "check":
                got_check = True
    return got_list, got_check


def _uses_check_failures_harness(tree):
    """
    "`FAILURES` 목록 + `check()` 함수" 조합을 하네스로 봅니다. 둘은 **파일 안에 직접 정의**
    돼 있어도 되고, **`tests/conftest.py` 에서 import** 해 온 것이어도 됩니다(2026-08-30
    공용화 이후 9개 파일이 후자입니다).

    밑줄·대소문자 변형(`_FAILURES`/`failures`, `_check`)까지 받아들이는 이유: 이 하네스는
    파일 간 **복사·붙여넣기로 퍼지는** 물건이라, 이름을 살짝 바꿔 복사한 사본이 검사망을
    빠져나가면 그게 곧 다음 H-1이 됩니다.
    """
    conf_list, conf_check = _imports_harness_from_conftest(tree)
    has_list = _defines_local_failures_list(tree) or conf_list
    has_check = _defines_local_check(tree) or conf_check
    return has_list and has_check


def _is_failures_autouse_fixture(fn):
    """
    이 함수가 `@pytest.fixture(autouse=True)`(또는 `@fixture(autouse=True)`)가 붙었고
    **본문에서 `FAILURES`를 실제로 들여다보는** 픽스처인지.

    "본문에서 FAILURES를 참조할 것"까지 요구하는 이유: 전혀 무관한 autouse 픽스처
    (예: 임시 디렉터리 정리)가 하나 있다는 이유만으로 통과시키면, 정작 무음 통과 방지는
    없는 파일이 초록불을 받습니다 — 그게 바로 이 파일이 막으려는 "겉보기 정상"입니다.
    """
    for deco in fn.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        func = deco.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "fixture":
            continue
        autouse = any(
            kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in deco.keywords
        )
        if not autouse:
            continue
        if any(_references_name(stmt, "FAILURES") for stmt in fn.body):
            return True
    return False


def _failures_autouse_fixture_names(tree):
    """`tree` 안에서 위 조건을 만족하는 픽스처들의 이름."""
    return [fn.name for fn in _toplevel_functions(tree) if _is_failures_autouse_fixture(fn)]


def _has_failures_autouse_fixture(tree):
    """그 파일 **자신에** 무음 통과 방지 autouse 픽스처가 있는지."""
    return bool(_failures_autouse_fixture_names(tree))


def _conftest_harness_defects(request):
    """
    공용 하네스(`tests/conftest.py`)가 **진짜로** 무음 통과를 막고 있는지 확인하고, 문제가
    있으면 사람이 읽을 수 있는 사유 목록을 돌려줍니다(정상이면 빈 목록).

    ⚠️ 이 함수가 왜 이렇게 꼼꼼한가 — Check A 가 "이 파일은 conftest 하네스를 쓰니까 안전"
    이라고 **믿고 넘어가는** 순간, conftest 쪽이 비었거나 망가졌을 때 9개 파일이 한꺼번에
    거짓 초록불을 받습니다. 그건 옮기기 전보다 더 나쁜 상태(=한 곳이 뚫리면 전부 뚫림)라,
    소스(AST)만 보고 판단하지 않고 **실제로 import 해서 물건이 있는지**, 그리고 **그
    autouse 픽스처가 지금 이 테스트에도 실제로 걸려 있는지**까지 확인합니다.
    """
    problems = []
    if not CONFTEST_PATH.is_file():
        return [f"공용 하네스 파일이 없습니다: {CONFTEST_PATH}"]

    # (1) 소스 구조 — 다른 검사와 같은 AST 기준으로 3종이 다 있는지
    tree = _parse(str(CONFTEST_PATH))
    if not _defines_local_failures_list(tree):
        problems.append("conftest.py 에 모듈 최상위 `FAILURES` 목록이 없습니다")
    if not _defines_local_check(tree):
        problems.append("conftest.py 에 최상위 `check()` 함수가 없습니다")
    guard_names = _failures_autouse_fixture_names(tree)
    if not guard_names:
        problems.append(
            "conftest.py 에 `FAILURES` 를 들여다보는 `@pytest.fixture(autouse=True)` 픽스처가 "
            "없습니다 — check() 실패를 pytest 실패로 승격시키는 장치가 통째로 없다는 뜻입니다"
        )

    # (2) 실물 — 정말 import 되고, 정말 그 타입이고, 인스턴스가 하나인지
    try:
        import conftest as _conftest
    except Exception as exc:                                   # noqa: BLE001
        problems.append(f"conftest.py 를 import 할 수 없습니다: {type(exc).__name__}: {exc}")
        return problems

    if not isinstance(getattr(_conftest, "FAILURES", None), list):
        problems.append("`conftest.FAILURES` 가 실제 list 가 아닙니다")
    if not callable(getattr(_conftest, "check", None)):
        problems.append("`conftest.check` 가 호출 가능한 함수가 아닙니다")

    # conftest.py 가 서로 다른 모듈 이름으로 두 번 import 되면 `FAILURES` 가 **두 개**가 되어,
    # 기록하는 쪽(check)과 감시하는 쪽(픽스처)이 서로 다른 목록을 보게 됩니다. 그러면 실패가
    # 조용히 사라집니다 — 이 파일이 막으려는 바로 그 결함이라 명시적으로 잡습니다.
    instances = {
        id(mod): name
        for name, mod in list(sys.modules.items())
        if getattr(mod, "__file__", None)
        and Path(mod.__file__).resolve() == CONFTEST_PATH.resolve()
    }
    if len(instances) > 1:
        problems.append(
            f"conftest.py 가 서로 다른 모듈 이름 {sorted(instances.values())} 으로 중복 import "
            f"돼 있습니다 — `FAILURES` 가 두 개가 되어 check() 실패가 감시망을 빠져나갑니다"
        )

    # (3) 동작 — 그 autouse 픽스처가 **지금 이 테스트에도** 실제로 적용돼 있는지.
    #     (autouse 라면 같은 디렉터리의 모든 테스트에 걸리므로, 이 테스트도 예외가 아닙니다.
    #      이름을 여기 하드코딩하지 않고 (1)에서 찾은 이름을 그대로 씁니다.)
    if guard_names and not any(name in request.fixturenames for name in guard_names):
        problems.append(
            f"conftest.py 의 무음 통과 방지 픽스처 {guard_names} 가 지금 이 테스트의 활성 픽스처 "
            f"목록에 없습니다 — 선언은 돼 있지만 실제로는 autouse 로 걸리지 않고 있다는 뜻입니다 "
            f"(활성 목록: {sorted(request.fixturenames)})"
        )
    return problems


def _every_test_asserts_failures(tree):
    """
    픽스처 대신 **모든** `test_*` 함수가 자기 본문 안에서 `assert ... FAILURES ...`로
    직접 마무리하는 방식도 같은 안전성을 줍니다.

    실제 사례: `tests/test_us_scoring.py`는 파일 전체가 `test_us_scoring_full_suite()`
    한 함수이고 그 끝이 `assert not FAILURES` 입니다 — 픽스처는 없지만 무음 통과가
    구조적으로 불가능하므로, 이걸 위반으로 잡으면 순수 오탐입니다.
    단, `test_*`가 하나라도 assert 없이 추가되는 순간 이 분기는 깨지고(=모두가 아니게 되고)
    파일은 다시 위반으로 잡힙니다 — 느슨해지는 방향으로는 안 열립니다.
    """
    tests = _test_function_nodes(tree)
    if not tests:
        return False  # 검사할 테스트가 없으면 "전부 만족"이라는 공허한 참을 주지 않습니다
    for fn in tests:
        asserts_failures = any(
            isinstance(s, ast.Assert) and _references_name(s, "FAILURES")
            for s in ast.walk(fn)
        )
        if not asserts_failures:
            return False
    return True


@pytest.mark.parametrize("path", TEST_FILES, ids=TEST_FILE_IDS)
def test_check_failures_harness_cannot_pass_silently(path, request):
    """Check A — `check()`/`FAILURES` 하네스를 쓰는 파일은 pytest에서도 반드시 빨간불이 될 것.

    하네스는 두 가지 형태가 있고 **둘 다** 검사합니다(2026-08-30 공용화 이후).
      · 공용형 — `from conftest import FAILURES, check`. 감시는 `tests/conftest.py` 의
        autouse 픽스처가 하므로, 파일 자신에는 픽스처가 없는 게 정상입니다. 대신 그
        conftest 가 진짜로 제 몫을 하는지를 확인합니다.
      · 자체형 — 파일 안에 `FAILURES` 목록을 직접 두는 경우. conftest 의 픽스처는 **다른
        리스트**를 보고 있어 이 파일을 지켜주지 못하므로, 예전과 똑같이 자기 파일 안에
        방어 장치가 있어야 합니다(`tests/test_us_scoring.py` 가 이 형태입니다).
    두 형태를 겸하면 두 검사를 모두 통과해야 합니다 — 느슨해지는 방향으로는 열지 않습니다.
    """
    tree = _parse(str(path))
    if not _uses_check_failures_harness(tree):
        pytest.skip("이 파일은 check()/FAILURES 하네스를 쓰지 않음 — Check A 대상 아님")

    checked_something = False

    # ── 자체형: 이 파일 자신의 FAILURES 목록은 이 파일 자신이 지켜야 합니다 ──────────────
    if _defines_local_failures_list(tree):
        checked_something = True
        ok = _has_failures_autouse_fixture(tree) or _every_test_asserts_failures(tree)
        assert ok, (
            f"\n🔴 {path.name} 은 자기 파일 안에 FAILURES 목록을 두고 check() 하네스를 쓰는데,\n"
            f"   check() 실패를 pytest 실패로 승격시키는 장치가 없습니다. check()는 FAILURES 에\n"
            f"   적기만 하고 예외를 던지지 않으므로, 이 상태면 이 파일의 검사가 무엇을 잡아내든\n"
            f"   pytest는 항상 초록불입니다\n"
            f"   (TASK_HISTORY #168 H-1 / 2026-08-21 test_data_source.py 와 똑같은 결함).\n"
            f"\n   고치는 법(권장) — 자기 파일의 하네스를 지우고 공용 하네스를 쓰세요:\n"
            f"       from conftest import FAILURES, check\n"
            f"   (tests/conftest.py 의 autouse 픽스처가 자동으로 적용됩니다 — 9개 파일이 이 형태)\n"
            f"\n   자기 파일에 FAILURES 를 꼭 따로 둬야 한다면 방어 장치도 이 파일에 두세요:\n"
            f"       @pytest.fixture(autouse=True)\n"
            f"       def _assert_no_check_failures():\n"
            f"           start = len(FAILURES)\n"
            f"           yield\n"
            f"           new_failures = FAILURES[start:]\n"
            f"           assert not new_failures, f\"check() 로 기록된 실패 ...: {{new_failures}}\"\n"
            f"   (또는 test_us_scoring.py 처럼 모든 test_* 가 자기 본문에서 FAILURES 를 assert)"
        )

    # ── 공용형: conftest 가 실제로 지켜주고 있는지 확인 ────────────────────────────────
    conf_list, conf_check = _imports_harness_from_conftest(tree)
    if conf_list or conf_check:
        checked_something = True
        defects = _conftest_harness_defects(request)
        assert not defects, (
            f"\n🔴 {path.name} 은 공용 하네스(`from conftest import ...`)를 쓰는데, 정작 그\n"
            f"   `tests/conftest.py` 가 무음 통과를 막아주지 못하는 상태입니다. 이 파일의\n"
            f"   check() 실패는 지금 아무도 pytest 실패로 바꿔주지 않습니다\n"
            f"   (하네스를 한 곳으로 모았기 때문에, 여기가 뚫리면 공용형 파일이 전부 뚫립니다).\n"
            f"\n   발견된 문제 {len(defects)}건:\n"
            + "".join(f"       - {d}\n" for d in defects)
            + f"\n   고치는 법: tests/conftest.py 에 `FAILURES` 목록 · `check()` · 그리고 그\n"
            f"   목록의 증가분을 검사하는 `@pytest.fixture(autouse=True)` 세 가지가 모두\n"
            f"   있어야 합니다(그 파일 독스트링에 경위가 적혀 있습니다)."
        )

    # 위 두 분기 중 하나도 안 돌았다면 이 테스트는 아무것도 확인하지 않고 통과한 것입니다 —
    # 그런 "빈손 초록불"이야말로 이 파일이 막으려는 것이라 명시적으로 실패시킵니다(§0-1).
    assert checked_something, (
        f"\n🔴 {path.name} 이 하네스 사용 파일로 판정됐는데 Check A 가 실제로는 아무 검사도\n"
        f"   하지 않고 통과했습니다 — `_uses_check_failures_harness()` 와 아래 두 분기의\n"
        f"   판정 기준이 어긋났다는 뜻입니다(검사망에 구멍이 생긴 상태)."
    )


# =====================================================================================
# 2. Check B — `main()`(직접 실행 경로)이 그 파일의 `test_*`를 빠짐없이 부를 것
# =====================================================================================
@pytest.mark.parametrize("path", TEST_FILES, ids=TEST_FILE_IDS)
def test_direct_run_main_covers_every_test_function(path):
    """Check B — `python tests/test_x.py` 경로가 조용히 일부 테스트를 건너뛰지 않을 것."""
    tree = _parse(str(path))
    mains = [f for f in _toplevel_functions(tree) if f.name == "main"]
    if not mains:
        pytest.skip("이 파일에는 직접 실행 진입점 main() 이 없음 — Check B 대상 아님")

    main_fn = mains[0]
    called = _called_names(main_fn)

    # `_test_discovery.discover_and_run_module_tests()`는 `inspect`로 그 모듈이 정의한
    # `test_*`를 전부 자동 수집해 부릅니다(TASK_HISTORY #168 H-3의 근본 해결책).
    # 이 헬퍼를 쓰는 순간 "목록이 어긋난다"는 사고 자체가 구조적으로 불가능하므로,
    # 목록 대조를 하지 않고 설계상 합격으로 봅니다(§0-3-10 — 같은 판정을 두 번 구현하지 않음).
    if "discover_and_run_module_tests" in called:
        return

    # 손으로 나열하는 방식이면 실제 정의와 한 건씩 대조합니다.
    # 픽스처 인자(tmp_path/monkeypatch 등)가 필요한 함수는 main() 이 인자를 채울 방법이
    # 없어 애초에 부를 수 없으므로 제외합니다 — `_test_discovery`가 건너뛰는 기준과 동일.
    expected = {
        f.name for f in _test_function_nodes(tree)
        if _required_positional_arg_count(f) == 0
    }
    missing = sorted(expected - called)
    assert not missing, (
        f"\n🔴 {path.name} 의 main() 이 손으로 나열한 호출 목록이 실제 test_* 정의보다\n"
        f"   오래됐습니다. `python tests/{path.name}` 로 직접 실행하면 아래 {len(missing)}건이\n"
        f"   **한 번도 호출되지 않은 채** '✅ 전체 통과'가 출력됩니다\n"
        f"   (TASK_HISTORY #168 H-3 와 똑같은 결함 — 그때는 한 파일에서 29개 중 12개였습니다).\n"
        f"\n   호출이 빠진 함수 {len(missing)}/{len(expected)}건:\n"
        + "".join(f"       - {name}()\n" for name in missing)
        + f"\n   고치는 법(권장) — 목록을 손으로 고치지 말고 main() 본문을 이 한 줄로 바꾸세요:\n"
        f"       from _test_discovery import discover_and_run_module_tests\n"
        f"       discover_and_run_module_tests(sys.modules[__name__], on_skip=...)\n"
        f"   (test_report.py · test_scorecard.py · test_macro_scoring.py · test_stock_history.py 가 이미 이 형태입니다)"
    )


# =====================================================================================
# 3. Check C — 모든 test_*.py 에서 pytest 가 실제로 1건 이상 수집할 것
# =====================================================================================
@functools.lru_cache(maxsize=1)
def _pytest_collection():
    """
    `tests/` 전체를 대상으로 `pytest --collect-only -q` 를 **한 번만** 돌려, 파일별 수집
    건수를 셉니다. (lru_cache 로 파라미터라이즈된 전체 케이스가 이 결과 하나를 공유 —
    파일마다 프로세스를 띄우면 34번 × 수 초로 스위트가 눈에 띄게 느려집니다.)

    왜 pytest 를 직접 부르는가 (설계 근거):
      Check C 는 "pytest 가 이 파일에서 테스트를 수집하는가"를 묻는 검사입니다. 그 답을
      AST 로 흉내 내면(=`def test_*` 를 직접 세면) **pytest 의 수집 규칙을 재구현**하는
      셈이 되고, 그 사본이 pytest 의 실제 규칙(`python_files`/`python_classes`/
      `python_functions` 설정, `Test*` 클래스 안의 메서드, 조건부·동적 정의, 플러그인)과
      어긋나는 순간 이 파일 자신이 "겉보기 정상"의 새 원천이 됩니다 — 막으려던 결함을
      스스로 만드는 꼴입니다(§0-1·§0-3-10). 그래서 판정 주체를 흉내 내지 않고 **당사자에게
      직접 물어봅니다.** 실측 비용은 전체 1회 약 6~7초(2026-08-30, 1755건 수집 기준)로,
      정확성 대비 충분히 쌉니다.
      `-p no:cacheprovider` 는 이 부수 실행이 저장소의 `.pytest_cache` 를 건드리지 않게 합니다.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS_DIR),
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
    )
    counts = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        head = line.split("::", 1)[0]
        if not head.endswith(".py"):
            continue
        # 출력 경로가 상대/절대 어느 쪽이든 상관없도록 파일명만 씁니다
        # (tests/ 안에 같은 이름의 파일이 둘 있을 수 없으므로 안전).
        name = Path(head).name
        counts[name] = counts.get(name, 0) + 1
    return proc, counts


def test_pytest_collection_subprocess_is_healthy():
    """
    Check C 의 근거가 되는 하위 pytest 실행 자체가 정상이었는지 **먼저** 못 박습니다.
    이게 통째로 실패했는데(예: 수집 단계 오류·usage error) 그 사실을 파일별 검사로만
    드러내면, 34개 케이스가 한꺼번에 빨개져서 진짜 원인이 파묻힙니다.
    """
    proc, counts = _pytest_collection()
    total = sum(counts.values())
    assert proc.returncode == 0 and total > 0, (
        f"\n🔴 Check C 의 근거인 `pytest --collect-only` 하위 실행이 실패했습니다 "
        f"(returncode={proc.returncode}, 수집 총계={total}).\n"
        f"   테스트 수집 단계에서 죽는 파일이 있다는 뜻일 수 있습니다.\n"
        f"--- stdout(마지막 30줄) ---\n" + "\n".join(proc.stdout.splitlines()[-30:]) +
        f"\n--- stderr(마지막 20줄) ---\n" + "\n".join(proc.stderr.splitlines()[-20:])
    )


@pytest.mark.parametrize("path", TEST_FILES, ids=TEST_FILE_IDS)
def test_pytest_actually_collects_at_least_one_test(path):
    """Check C — `test_*.py` 인데 pytest 가 0건을 수집하는(=조용히 통째로 안 도는) 파일 금지."""
    proc, counts = _pytest_collection()
    if proc.returncode != 0 or not counts:
        pytest.skip("하위 pytest 수집 실행 자체가 실패 — test_pytest_collection_subprocess_is_healthy 를 보세요")

    collected = counts.get(path.name, 0)
    assert collected > 0, (
        f"\n🔴 {path.name} 에서 pytest 가 수집한 테스트가 0건입니다.\n"
        f"   파일 이름은 `test_*.py` 라 수집 대상에 들어가는데 정작 안에 pytest 가 인식하는\n"
        f"   테스트가 없다는 뜻이고, pytest 는 이걸 실패가 아니라 정상('no tests ran')으로\n"
        f"   보고합니다 — 이 파일의 검증이 CI 에서 통째로 안 돌고 있어도 아무도 모릅니다.\n"
        f"   (2026-08-29 M-14 재발: `test_quant.py` 의 PEGY §0-1 회귀 방지선 8건이 전부\n"
        f"    `run_golden_tests()` 안에 있어 pytest 가 0건을 수집하고 있었습니다.)\n"
        f"\n   고치는 법: 테스트 본체를 담은 함수 이름을 `test_` 로 시작하게 하세요\n"
        f"   (독립 케이스로 쪼개면 어느 케이스가 깨졌는지도 이름으로 드러납니다).\n"
        f"   직접 실행용 래퍼가 필요하면 그건 `main()` 으로 따로 두세요."
    )
