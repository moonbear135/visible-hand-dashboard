# tests/test_enrich_quant_metrics_characterization.py
"""
🔒 `collector_kospi200.enrich_quant_metrics()` 특성화(characterization) 테스트 (2026-09-07)

⚠️ 이 파일이 왜 생겼는가

`enrich_quant_metrics()` 는 636줄짜리 단일 함수입니다(내부의 종목별 for 루프 하나가 520줄).
그걸 의미 단위로 쪼개는 리팩터를 하려면, 먼저 **"쪼개기 전과 후의 결과가 완전히 같은가"를
증명할 장치**가 있어야 합니다. 없으면 리팩터는 "잘 된 것 같다"로 끝나는 도박이고, 그건
이 저장소가 금지하는 겉보기 정상(§0-1) 그 자체입니다.

**이 파일은 계산이 옳은지 묻지 않습니다.** 옳고 그름은 `test_collector_kospi200_ranking.py`
등 기존 테스트의 몫입니다. 여기는 오직 **"지금 내놓는 값을 앞으로도 똑같이 내놓는가"** 만 봅니다.
그래서 리팩터가 값을 한 글자라도 바꾸면 즉시 빨간불이 납니다.

설계 결정 3가지 (전부 실제로 문제를 겪고 정한 것)

  ① **입력을 얼려둔다.** 처음엔 `data/kospi200_pegy_latest.json` 에서 매번 입력을 만들려
     했는데, 그 파일은 **매일 수집 배치가 갱신**합니다. 그러면 기준이 매일 움직여 기준선
     구실을 못 합니다. 그래서 한 번 뽑아 `tests/fixtures/` 에 얼려두고 그 뒤로는 저장소
     데이터가 어떻게 바뀌든 이 테스트는 같은 입력만 씁니다.
     (얼린 값 자체는 실제 수집 결과에서 뽑은 실데이터입니다 — 지어낸 숫자가 아닙니다.)

  ② **환경 의존성을 못 박는다.** `HAS_YFINANCE` / `HAS_FDR` 는 그 패키지가 깔려 있느냐로
     True/False 가 갈리는 모듈 전역입니다. 그대로 두면 **패키지가 깔린 기계와 안 깔린
     기계에서 기준선이 서로 달라집니다**(yfinance 교차검증 분기를 타느냐 마느냐). 고정합니다.

  ③ **우선주에는 짝 보통주를 같이 넣고, `t_roe` 를 0으로 되돌린다.** 우선주 ROE 상속은
     같은 배치 안에 보통주가 있어야 일어나고, 스냅샷의 `t_roe` 는 **이미 상속이 끝난 값**
     이라 그대로 넣으면 상속이 다시 일어나지 않습니다. 처음 만든 기준선이 실제로 그랬고,
     그 60줄짜리 전처리 블록이 통째로 안 밟히고 있었습니다.

📌 빨간불이 났을 때
   리팩터(구조만 바꾸고 결과는 그대로) 중이라면 **리팩터가 틀린 것**입니다. 기준선을 고치지
   말고 코드를 고치세요. 계산 결과가 **의도적으로** 바뀌는 변경(수식·배점 수정)이라면
   오너 승인을 받고 `python tests/_enrich_baseline.py --regenerate` 로 갱신합니다.

실행: python -m pytest tests/test_enrich_quant_metrics_characterization.py -v
     python tests/test_enrich_quant_metrics_characterization.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다(2026-08-30 공용화).
# ⚠️ `FAILURES` 와 `check` 를 **둘 다** 가져와야 `test_suite_integrity.py` 의 Check A 가
#    이 파일을 하네스 사용 파일로 인식합니다 — `check` 만 가져오면 Check A 가 이 파일을
#    통째로 건너뛰어(skip) 감시망에 구멍이 생깁니다.
from conftest import FAILURES, check  # noqa: E402,F401
import _enrich_baseline as BL  # noqa: E402


# =====================================================================================
# 0. 픽스처가 조용히 사라지지 않게 (§0-1)
# =====================================================================================
def test_fixtures_exist_and_are_not_empty():
    """
    이 파일이 막으려는 결함의 가장 뻔한 재현은 **픽스처가 없어져서 테스트가 아무것도
    비교하지 않고 통과하는 것**입니다. 파일 존재와 최소 규모를 독립된 테스트로 못 박습니다.
    """
    assert BL.INPUT_PATH.is_file(), f"얼린 입력이 없습니다: {BL.INPUT_PATH}"
    assert BL.BASELINE_PATH.is_file(), f"기준선이 없습니다: {BL.BASELINE_PATH}"
    payload = BL.load_input()
    baseline = BL.load_baseline()
    assert len(payload["stocks_raw"]) >= 40, (
        f"얼린 입력이 {len(payload['stocks_raw'])}종목뿐입니다 — 2026-09-07 기준 61종목입니다. "
        "표본이 줄면 분기 커버리지가 조용히 사라집니다."
    )
    assert len(baseline) == len(payload["stocks_raw"]), (
        f"기준선({len(baseline)})과 입력({len(payload['stocks_raw'])})의 종목 수가 다릅니다 — "
        "둘 중 하나만 갱신된 상태입니다."
    )


# =====================================================================================
# 1. 🔴 핵심 — 결과가 기준선과 완전히 같을 것
# =====================================================================================
def test_output_is_byte_for_byte_identical_to_baseline():
    """
    🔴 **이 파일의 존재 이유.** 리팩터가 계산 결과를 바꾸면 여기서 빨간불이 납니다.

    비교는 종목 단위로 하고, 다른 필드만 골라서 보여줍니다 — "162KB JSON 두 개가 다릅니다"
    라고만 하면 사람이 원인을 못 찾습니다.
    """
    payload = BL.load_input()
    baseline = BL.load_baseline()
    actual = BL.run_with_frozen_input(payload)

    assert len(actual) == len(baseline), (
        f"결과 종목 수가 달라졌습니다: 기준선 {len(baseline)} → 지금 {len(actual)}"
    )

    diffs = []
    for got, want in zip(actual, baseline):
        code = want.get("code")
        if got.get("code") != code:
            diffs.append(f"{code}: 순서가 바뀜 (그 자리에 {got.get('code')})")
            continue
        for key in sorted(set(got) | set(want)):
            a, b = got.get(key, "<없음>"), want.get(key, "<없음>")
            # JSON 왕복을 거친 기준선과 맞추기 위해 문자열로 비교합니다
            # (튜플→리스트 등 직렬화 차이로 오탐하지 않게).
            if BL.canonical(a) != BL.canonical(b):
                diffs.append(f"{code} [{key}] 기준선={b!r} → 지금={a!r}")

    assert not diffs, (
        f"\n🔴 리팩터 전후 결과가 달라졌습니다 — {len(diffs)}건.\n"
        "   구조만 바꾸는 리팩터라면 **코드가 틀린 것**입니다. 기준선을 고치지 마세요.\n\n"
        + "".join(f"       - {d}\n" for d in diffs[:40])
        + (f"       ... 외 {len(diffs) - 40}건\n" if len(diffs) > 40 else "")
    )


def test_running_twice_gives_the_same_result():
    """비결정적 요소(난수·시각·정렬 불안정)가 새로 끼어들면 기준선 자체가 무의미해집니다."""
    payload = BL.load_input()
    first = BL.canonical(BL.run_with_frozen_input(payload))
    second = BL.canonical(BL.run_with_frozen_input(payload))
    assert first == second, "같은 입력을 두 번 돌렸는데 결과가 다릅니다 — 비결정적 요소가 있습니다."


# =====================================================================================
# 2. 기준선이 실제로 여러 갈래를 밟는지 (커버리지가 조용히 사라지지 않게)
# =====================================================================================
def test_baseline_actually_exercises_the_branches_it_claims_to():
    """
    기준선이 한 갈래만 밟으면 "전부 통과"가 아무 의미도 없습니다. 실제로 양쪽이 다 나오는지
    확인합니다. 특히 **우선주 ROE 상속**은 처음 만든 기준선에서 0건이었다가 뒤늦게 발견된
    구멍이라, 건수를 직접 못 박아 둡니다.
    """
    baseline = BL.load_baseline()

    def count(pred):
        return sum(1 for s in baseline if pred(s))

    inherited = count(lambda s: s.get("t_roe_inherited_from"))
    check(inherited >= 5, "우선주 ROE 상속이 실제로 일어난 종목 5개 이상", f"(실제 {inherited}개)")

    both_sides = {
        "is_valid": lambda s: s.get("is_valid"),
        "is_trailing_loss": lambda s: s.get("is_trailing_loss"),
        "forward_data_missing": lambda s: s.get("forward_data_missing"),
        "g_eff_capped": lambda s: s.get("g_eff_capped"),
        "f_target_capped": lambda s: s.get("f_target_capped"),
        "value_trap": lambda s: s.get("value_trap"),
        "graham_is_financial_sector": lambda s: s.get("graham_is_financial_sector"),
    }
    for name, pred in both_sides.items():
        yes = count(pred)
        check(0 < yes < len(baseline), f"{name} 이 참·거짓 양쪽 다 나옴",
              f"(참 {yes}/{len(baseline)})")

    sources = {s.get("dps_source") for s in baseline}
    check(len(sources) >= 3, "배당 출처가 3종류 이상 나옴", f"(실제 {sorted(sources)})")

    scored = count(lambda s: s.get("quant_score") is not None)
    check(scored >= 20, "퀀트 점수가 산출된 종목 20개 이상", f"(실제 {scored}개)")


def test_frozen_input_does_not_read_the_daily_snapshot():
    """
    🔴 얼린 입력이 다시 `data/kospi200_pegy_latest.json` 을 읽기 시작하면, 매일 도는 수집
    배치가 기준을 흔들어 이 테스트는 기준선 구실을 못 합니다. 실행 경로가 그 파일을
    건드리지 않는지 **실제로 열어보려 하면 터지게** 만들어 확인합니다.
    """
    import builtins

    real_open = builtins.open
    forbidden = str(BL._SOURCE_SNAPSHOT)
    touched = []

    def guarded_open(file, *args, **kwargs):
        if str(file) == forbidden:
            touched.append(str(file))
        return real_open(file, *args, **kwargs)

    payload = BL.load_input()
    builtins.open = guarded_open
    try:
        BL.run_with_frozen_input(payload)
    finally:
        builtins.open = real_open

    assert not touched, (
        f"실행 경로가 매일 갱신되는 스냅샷을 읽었습니다: {touched} — "
        "기준선이 움직이는 과녁이 됩니다."
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
