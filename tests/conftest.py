# tests/conftest.py
"""
🧰 `tests/` 공용 하네스 — `check()` / `FAILURES` 무음 통과 방지 장치를 **한 곳에서만** 정의합니다.

⚠️ 이 파일이 왜 생겼는가 (2026-08-30)

`check(cond, label)` 은 실패를 `FAILURES` 에 **적기만** 하고 예외를 절대 던지지 않습니다
(한 테스트 함수가 검사 수십 건을 이어서 돌리며, 첫 실패에서 멈추지 않고 전부 보여주기 위한
의도적인 설계입니다). 그래서 그 목록을 실제로 검사해 죽는 장치가 없으면, 그 파일의 검사가
무엇을 잡아내든 pytest 는 **항상 초록불**입니다 — ENGINEERING_SPEC.md §0-1("실패를 정상
상태로 위장하지 않기")을 테스트 코드 자신이 어기는 상태입니다.

그 장치(`@pytest.fixture(autouse=True)`)를 지금까지는 **파일마다 손으로 복사**해 넣어 왔고,
바로 그 복사 방식 자체가 두 번 사고를 냈습니다.
  · 2026-08-21 `tests/test_data_source.py` — 최초 발견.
  · 2026-08-30 재감사(TASK_HISTORY `### #168` H-1) — 9개 파일에는 있는데
    `tests/test_us_stocks_page.py` 하나만 그 복사에서 빠져 있던 것이 뒤늦게 발견.

`conftest.py` 의 `autouse` 픽스처는 pytest 설계상 **같은 디렉터리의 모든 테스트에 자동
적용**되므로, 여기에 한 번만 두면 "복사 하나 빠뜨림" 이라는 사고 자체가 구조적으로
불가능해집니다(§0-3-10 — 같은 것을 두 곳에서 손으로 맞추지 않고 한 곳에서 파생시킴).

📌 이 파일을 고칠 때 반드시 함께 볼 것 — `tests/test_suite_integrity.py` 의 Check A
   (`test_check_failures_harness_cannot_pass_silently`).
   Check A 는 각 테스트 파일이 하네스를 **자기 파일 안에** 정의했는지뿐 아니라 **여기서
   import 해 쓰는지**까지 봅니다. 후자인 파일은 "이 파일에 진짜로 `FAILURES` · `check()` ·
   `FAILURES` 를 들여다보는 autouse 픽스처 3종이 모두 있는지"를 Check A 가 직접 확인한
   뒤에야 합격시킵니다. 셋 중 하나라도 여기서 사라지면 Check A 가 즉시 빨간불을 냅니다
   (하네스를 옮겨놓고 감시망이 그 파일을 놓치는 "다음 H-1" 을 막는 장치입니다).

⚠️ `FAILURES` 는 이 디렉터리 전체가 공유하는 **하나의 리스트**입니다. pytest 는 테스트를
   순차 실행하므로 동시성 문제는 없지만, **절대 `FAILURES.clear()` 등으로 도중에 비우지
   마세요.** 아래 픽스처는 테스트 시작 시점의 길이(`start`)를 기준으로 증가분만 보기
   때문에, 도중에 목록이 짧아지면 그 뒤에 기록된 실패가 조용히 사라집니다 — 정확히 이
   파일이 막으려는 그 결함입니다. 그런 사정이 있는 파일(`tests/test_us_scoring.py` 은
   테스트 본문 첫 줄에서 `FAILURES.clear()` 를 부릅니다)은 지금도 자기 파일 안에 자기만의
   `FAILURES` 와 `check()` 를 따로 두고 있습니다 — 일부러 옮기지 않고 남겨둔 것입니다.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# 각 `test_*.py` 가 파일 맨 위에서 되풀이하던 것과 **같은 경로 계산**입니다.
# pytest 로 돌릴 때는 pytest 가 `tests/` 를 알아서 `sys.path` 에 얹지만, 저장소 관례인
# `python tests/test_x.py` **직접 실행** 경로에서는 이 줄이 저장소 루트를 얹어 줍니다
# (그 경로에서도 `from conftest import ...` 가 이 파일을 먼저 불러오므로 순서가 맞습니다).
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))


FAILURES = []


def check(condition, label, detail=""):
    """
    검사 한 건을 기록합니다 — 사람이 읽는 줄로 결과를 출력하고, 실패면 `FAILURES` 에
    라벨을 적습니다. **여기서 예외를 던지지 않는 것이 의도**이고, 그 실패를 실제 pytest
    빨간불로 승격시키는 일은 아래 `_assert_no_check_failures` 픽스처가 맡습니다.

    `detail` 은 옮겨오기 전 10개 파일 중 7개가 쓰던 선택 인자입니다(실패했을 때만 라벨 뒤에
    실제 값 등을 덧붙임). 넘기지 않으면 나머지 파일들의 출력과 글자 그대로 같습니다.
    """
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}" if detail else f"  ❌ {label}")
        FAILURES.append(label)


@pytest.fixture(autouse=True)
def _assert_no_check_failures():
    """
    🔴 2026-08-21 발견 — `check()`는 실패를 `FAILURES`에 기록만 하고, 그 목록을 실제로
    검사해서 죽는 코드는 파일 맨 아래 `if __name__ == "__main__": main()` 안에만 있었습니다.
    검증은 pytest로 돌려왔는데, pytest는 `main()`을 절대 부르지 않으므로 `check()` 실패가
    있어도 각 `test_*` 함수는 스스로 실패하지 않았습니다 — 배선·렌더 스모크 검사가 그동안
    pytest 상에서는 항상 초록불이었다는 뜻입니다.

    그래서 매 테스트 앞뒤로 `FAILURES`의 증가분을 직접 확인해 pytest에서도 똑같이
    실패하게 만듭니다. `autouse=True` 라 `tests/` 안 **모든** 테스트에 자동 적용되며,
    `check()` 를 쓰지 않는 파일에는 아무 영향이 없습니다(증가분이 항상 0건).
    """
    start = len(FAILURES)
    yield
    new_failures = FAILURES[start:]
    assert not new_failures, f"check() 로 기록된 실패 {len(new_failures)}건: {new_failures}"
