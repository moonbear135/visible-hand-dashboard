# tests/_test_discovery.py
"""
🔍 `python tests/test_x.py`로 직접 실행하는 진입점(`main()`)이, 그 파일에 정의된 `test_*`
함수 목록을 손으로 나열하다 실제 정의와 어긋나는 문제를 막는 작은 공용 헬퍼입니다.

2026-08-30 재감사(테스트 스위트) H-3 — `test_macro_scoring.py`(29개 중 12개 미호출)·
`test_report.py`(23개 중 3개)·`test_scorecard.py`(20개 중 2개)·`test_stock_history.py`
(17개 중 1개)에서, `main()`이 부르는 함수 목록이 실제 `test_*` 정의보다 오래돼 있었습니다.
그 결과 `python tests/test_macro_scoring.py`로 직접 실행하면 회귀 테스트 12건이 **한 번도
호출되지 않은 채** "✅ 전체 통과"가 출력됐습니다(pytest 경로는 각 파일의 `check()`/`FAILURES`
autouse 픽스처 덕분에 애초에 영향 없음 — 이 문제는 문서화된 직접 실행 경로에만 있었습니다).

`main()`이 이 함수로 `test_*`를 자동 수집해 부르면, 새 `test_*`를 추가했는데 호출을 안 넣는
실수 자체가 구조적으로 불가능해집니다(ENGINEERING_SPEC.md §0-3-10 — 목록을 두 곳(정의부·
호출부)에서 손으로 맞추지 않고 한 곳에서 파생시킴).

pytest 전용 픽스처(`tmp_path`/`monkeypatch` 등)를 인자로 받는 `test_*` 함수는 인자를 채워줄
방법이 없어 이 방식으로 직접 호출할 수 없으므로 건너뜁니다 — 그 함수들은
`pytest tests/test_x.py`로 실행하면 정상적으로 커버됩니다(건너뛴 개수를 알려줘서 조용히
누락되지 않게 합니다 — 바로 이번에 고치는 문제의 재발 방지).
"""
import inspect


def discover_and_run_module_tests(module, on_skip=None):
    """
    `module`에 **그 모듈 자신이 정의한**(다른 테스트 파일에서 import해 온 게 아닌) `test_*`
    함수를 소스 코드에 적힌 순서 그대로 전부 호출합니다.

    반환: 픽스처 인자가 필요해 건너뛴 함수 이름 목록(비어 있으면 전부 실행됨).
    `on_skip`이 주어지면 건너뛴 목록이 있을 때만 그 콜백에 넘깁니다(로그 출력용).
    """
    candidates = []
    for name, obj in vars(module).items():
        if not name.startswith("test_"):
            continue
        if not inspect.isfunction(obj):
            continue
        if inspect.getmodule(obj) is not module:
            continue  # 다른 테스트 파일에서 가져온 헬퍼는 이 모듈 소속 검증이 아님
        candidates.append((name, obj))

    # 정의된 순서(소스 줄 번호)로 — 알파벳순으로 섞이면 출력이 원래 의도한 섹션 흐름과
    # 달라져 사람이 읽기 어려워집니다.
    candidates.sort(key=lambda item: inspect.getsourcelines(item[1])[1])

    skipped = []
    for name, fn in candidates:
        params = inspect.signature(fn).parameters
        required = [
            p for p in params.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if required:
            skipped.append(name)
            continue
        fn()

    if skipped and on_skip:
        on_skip(skipped)
    return skipped
