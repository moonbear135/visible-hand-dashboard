# tests/test_user_facing_wording.py
"""
🗣️ 사용자 노출 문자열에 **내부 문서 인용이 섞이지 않게** 하는 메타 테스트.

왜 이 파일이 있는가 (실제 사고 — 2026-09-05 오너 지적)
────────────────────────────────────────────────────────────────────────────
결투 계좌의 주문 취소 사유(`fail_reason`)는 배치가 만들어 DB 에 남기고, 화면(주문 내역)이
그 문장을 **그대로** 보여줍니다. 오너가 실제 화면 캡처를 보고 지적했습니다 — 문장 안에
"(작업지시서 2-4-5)" · "(둘을 구분하지 않습니다, 작업지시서 2-9-1)" 같은 **개발자끼리 쓰는
내부 문서 번호**가 박혀 있어, 취소당한 사용자 입장에서는 무슨 뜻인지도, 뭘 해야 하는지도
알 수 없었습니다. 2026-08-29 에 `duel_batch._freshness_reason()` 한 곳은 이미 같은 이유로
고쳐졌지만(그 함수 docstring 참고), `duel_rules.allocate_pending_orders()` 등 다른 자리에는
같은 모양의 문구가 그대로 남아 있었습니다 — 한 곳을 고친 기억이 다른 곳까지 지켜 주지는
않습니다. 그래서 사람의 기억 대신 **구조적 방어선**을 둡니다(§0-1 · §0-3-10).

무엇을 검사하는가
────────────────────────────────────────────────────────────────────────────
`utils/` · `web/` 의 모든 `.py` 를 AST 로 훑어, **실행되는 문자열 리터럴**(일반 문자열 ·
f-string 조각 · 이어붙인 문자열) 안에 내부 문서 인용("작업지시서")이 남아 있으면 실패합니다.
  · 코드 주석(`#`)과 docstring 은 **허용**합니다 — 근거 인용은 바로 거기에 두라는 것이 이
    정리의 방향입니다(`_freshness_reason()` 이 보여 준 패턴).
  · 예외 메시지(`raise XxxError("…")`)도 검사 대상입니다. 화면은 `DuelRuleError` 등을
    잡아 `str(exc)` 를 그대로 그리는 자리가 여럿이라(`web/pages/duel_page.py`), 예외 문장도
    사용자 노출 문자열입니다.
  · "화면에 실제로 그려지는가"를 정적으로 판별하려 들지 않습니다 — 그 판별을 흉내 내는
    순간 놓치는 경로가 생기고, 실행되는 문자열에 내부 문서 번호를 남길 정당한 이유는 어차피
    없습니다(주석으로 옮기면 됩니다). 그래서 **전부** 잡습니다.

📌 파일 목록을 `parametrize` 로 펼쳐, 실패했을 때 테스트 ID 가 **문제 파일 이름을 그대로**
   말하게 합니다(`test_suite_integrity.py` 와 같은 관례).
"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

#: 실행되는 문자열 안에 남아 있으면 안 되는 내부 문서 인용 표식.
#: (ENGINEERING_SPEC 의 "§0-1" 같은 절 번호는 주석·docstring 관례라 여기서 다루지 않습니다 —
#: 화면 문구에 실제로 새어 나와 오너가 지적한 것은 "작업지시서 X-X-X" 였습니다.)
INTERNAL_CITATION_MARKERS = ("작업지시서",)

#: 검사 범위 — 사용자 노출 문자열이 만들어지는 두 패키지. 저장소 관례대로 `archive/` 와
#: `__pycache__` 는 대상이 아닙니다.
SCAN_ROOTS = ("utils", "web")


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


def _docstring_node_ids(tree):
    """모듈·클래스·함수의 docstring 인 `Constant` 노드 id 집합(허용 대상)."""
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            ids.add(id(first.value))
    return ids


def find_internal_citations_in_executable_strings(path):
    """
    `path` 의 **실행되는 문자열 리터럴** 중 내부 문서 인용이 들어 있는 것을
    `[(줄 번호, 문자열 앞부분), …]` 로 돌려줍니다. docstring 은 제외합니다.

    f-string(`JoinedStr`)의 고정 조각도 `Constant` 로 AST 에 나타나므로 같은 순회에서
    잡힙니다. 이어붙인 문자열(`"a" "b"`)은 파서가 이미 하나의 `Constant` 로 합쳐 둡니다.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    docstrings = _docstring_node_ids(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        if any(marker in node.value for marker in INTERNAL_CITATION_MARKERS):
            hits.append((node.lineno, node.value.strip()[:100]))
    # `ast.walk` 은 너비 우선이라 줄 순서가 뒤섞입니다 — 사람이 읽을 목록은 줄 번호순으로.
    return sorted(hits)


def test_scanner_actually_found_source_files():
    """검사 대상이 0건이면 아래 parametrize 가 통째로 비어 조용히 초록불이 됩니다(§0-1)."""
    assert len(SCAN_FILES) >= 20, SCAN_FILE_IDS
    names = {p.name for p in SCAN_FILES}
    # 오너가 지적한 바로 그 파일들이 실제로 검사 범위에 들어 있어야 합니다.
    for must in ("duel_rules.py", "duel_batch.py", "duel_batch_usd.py",
                 "duel_db.py", "duel_db_usd.py", "duel_page.py"):
        assert must in names, f"{must} 가 검사 범위에 없음"


def test_scanner_detects_a_citation_inside_an_fstring_and_ignores_comments_and_docstrings(tmp_path):
    """스캐너 자신이 f-string 은 잡고, 주석·docstring 은 놓아주는지 먼저 못 박습니다."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""모듈 docstring — 작업지시서 2-4-5 인용은 여기서는 허용."""\n'
        "def f(t):\n"
        '    """함수 docstring 의 작업지시서 인용도 허용."""\n'
        "    # 주석의 작업지시서 인용도 허용\n"
        '    return f"{t}의 종가를 확보하지 못했습니다(작업지시서 2-4-5)."\n'
        "def g():\n"
        '    return ("정상 문장" " 인데 이어붙인 조각에 작업지시서 2-9")\n'
        "def h():\n"
        '    return "인용 없는 문장"\n',
        encoding="utf-8",
    )
    hits = find_internal_citations_in_executable_strings(sample)
    assert [line for line, _ in hits] == [5, 7], hits


@pytest.mark.parametrize("path", SCAN_FILES, ids=SCAN_FILE_IDS)
def test_executable_strings_do_not_cite_internal_work_order(path):
    hits = find_internal_citations_in_executable_strings(path)
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    assert not hits, (
        f"\n🔴 {rel} 의 **실행되는 문자열**에 내부 문서 인용({' / '.join(INTERNAL_CITATION_MARKERS)})이\n"
        f"   남아 있습니다. 이런 문장은 fail_reason·예외 메시지로 사용자 화면까지 그대로 올라갑니다\n"
        f"   (2026-09-05 오너가 실제 화면 캡처로 지적). 근거 인용은 바로 옆 코드 주석으로 옮기세요\n"
        f"   (`utils/duel_batch.py::_freshness_reason()` 의 정리 방식 참고).\n"
        + "".join(f"       - L{line}: {text}\n" for line, text in hits)
    )


def test_missing_close_price_cancel_reason_reads_for_a_beginner():
    """
    오너가 지적한 바로 그 문구 — 매수(`duel_rules.allocate_pending_orders`)·매도
    (`duel_batch.plan_order_fills`) 양쪽의 취소 사유가 (1) 내부 인용 없이, (2) 왜 취소됐는지,
    (3) 그래서 사용자가 뭘 하면 되는지(예수금·보유 주식은 그대로, 다음 접수 시간대에 다시
    주문 가능 — `NOTICE_CRAWL_FAILURE` 가 주문 전에 미리 알리는 사실과 같은 말)를 담는지.
    """
    from utils import duel_batch, duel_rules

    buy = duel_rules.allocate_pending_orders(
        1_000_000,
        [{"id": "o1", "ticker": "없는종목", "requested_quantity": 1,
          "saved_at": "2026-08-19T18:05:00+09:00"}],
        {"A": 100},
    )[0]
    assert buy["status"] == duel_rules.ORDER_CANCELLED
    reason = buy["fail_reason"]
    assert "작업지시서" not in reason
    assert "확정 종가" in reason and "취소" in reason
    assert "예수금은 그대로" in reason and "다시 주문" in reason

    plan = duel_batch.plan_order_fills(
        [{"id": "s1", "account_id": "acc-1", "ticker": "999999", "requested_quantity": 1,
          "side": "sell", "saved_at": "2026-08-19T19:00:00+09:00"}],
        {"acc-1": 0.0}, {},
        {"acc-1": [{"account_id": "acc-1", "ticker": "999999", "quantity": 1, "avg_cost": 100.0}]},
        "2026-08-19")
    sell = plan["fill_results"][0]
    assert sell["status"] == duel_rules.ORDER_CANCELLED
    reason = sell["fail_reason"]
    assert "작업지시서" not in reason
    assert "확정 종가" in reason and "취소" in reason
    assert "보유 주식은 그대로" in reason and "다시 주문" in reason


def main():
    print("=" * 74)
    print("🗣️ 사용자 노출 문자열 — 내부 문서 인용 검사 (네트워크 불필요)")
    print("=" * 74)
    from _test_discovery import discover_and_run_module_tests

    discover_and_run_module_tests(
        sys.modules[__name__],
        on_skip=lambda names: print(f"⏭️  pytest 전용(파라미터 필요) {len(names)}건은 건너뜀: {names}"),
    )
    print("\n" + "=" * 74)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
