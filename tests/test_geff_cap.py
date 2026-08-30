# tests/test_geff_cap.py
"""
🔴 실효성장률(g_eff) 2중 캡 회귀 테스트 — 코스피 경로 (TASK_HISTORY #175/#176)

배경: `ENGINEERING_SPEC.md` §5-1은 프로젝트 최초 커밋(2026-08-03)부터 Forward
실효성장률에 "성장률 35%p / 주주환원 10%p / 합계 40%p" 2중 캡을 명시했습니다.
미국 모듈(`utils/scoring_us.py`)은 이걸 그대로 구현했는데, 코스피 모듈
(`collector_kospi200.py`)은 처음부터 이 캡 없이 `geff = growth + sh_yield`로만
계산하고 있었습니다 — 2026-08-30 테스트 커버리지 감사(TASK_HISTORY #175) 중
발견, 오너 확인으로 "의도된 시장별 차이가 아니라 놓친 구현"임을 확정하고
반영(#176)했습니다.

이 계산은 `collector_kospi200.py`의 거대한 종목별 루프 안에 인라인으로 있어
직접 import해서 부를 수 있는 순수 함수가 아닙니다(리팩터는 이번 범위 밖 —
§0-3-6, 필요 이상으로 다른 코드를 건드리지 않음). 대신 이 테스트는:
  ① 상수(`utils/constants.py`)를 실제로 import해 매직넘버를 이 테스트에
     복제하지 않고,
  ② 캡 공식 자체를 손으로 계산한 기대값과 대조하고,
  ③ 실제 저장된 스냅샷(`data/kospi200_pegy_latest.json`)의 실측 growth·
     sh_return·vol_penalty로 "이전에 실제로 있었던 결함"을 재현해, 캡을
     적용하면 그 종목의 f_pegy·밴드가 실제로 어떻게 바뀌는지까지 검증합니다.
"""
import json
from pathlib import Path

from utils.constants import GROWTH_CAP_PCT, SH_RETURN_CAP_PCT, GEFF_TOTAL_CAP_PCT

REPO_ROOT = Path(__file__).resolve().parent.parent
PEGY_MIN_DENOMINATOR_PCT = 0.5  # collector_kospi200.py 의 로컬 상수와 동일(단일 값 확인용)


def _apply_cap(growth, sh_yield):
    """collector_kospi200.py 의 캡 적용 로직과 1:1 대응(§0-3-10 — 로직은 프로덕션
    코드가 단일 출처이고, 이 함수는 그 로직을 테스트에서 다시 표현한 것일 뿐 새
    프로덕션 로직이 아닙니다)."""
    growth_capped = min(growth, GROWTH_CAP_PCT)
    sh_capped = min(sh_yield, SH_RETURN_CAP_PCT)
    g_eff = min(growth_capped + sh_capped, GEFF_TOTAL_CAP_PCT)
    is_capped = (
        growth > GROWTH_CAP_PCT
        or sh_yield > SH_RETURN_CAP_PCT
        or (growth_capped + sh_capped) > GEFF_TOTAL_CAP_PCT
    )
    return g_eff, is_capped


def test_constants_match_spec_and_us_module():
    """§0-3-10: 코스피·미국 두 시장이 같은 개념(모델 안전장치, 시장 무관 상수)을
    쓰므로 값이 갈리면 안 됩니다. constants_us.py 를 직접 import해 대조합니다."""
    from utils.constants_us import (
        US_GROWTH_CAP_PCT, US_SH_RETURN_CAP_PCT, US_GEFF_TOTAL_CAP_PCT,
    )
    assert GROWTH_CAP_PCT == US_GROWTH_CAP_PCT == 35.0
    assert SH_RETURN_CAP_PCT == US_SH_RETURN_CAP_PCT == 10.0
    assert GEFF_TOTAL_CAP_PCT == US_GEFF_TOTAL_CAP_PCT == 40.0


def test_normal_range_untouched():
    """캡보다 한참 낮은 정상적인 성장률·주주환원율은 캡의 영향을 받지 않아야
    합니다(이전에도 맞았던 동작 — 회귀 없음 확인용)."""
    g_eff, capped = _apply_cap(growth=10.0, sh_yield=2.0)
    assert g_eff == 12.0
    assert capped is False


def test_growth_only_exceeds_cap():
    g_eff, capped = _apply_cap(growth=50.0, sh_yield=2.0)
    assert g_eff == 37.0          # min(50,35) + min(2,10) = 35+2
    assert capped is True


def test_shareholder_return_exceeds_cap():
    g_eff, capped = _apply_cap(growth=10.0, sh_yield=15.0)
    assert g_eff == 20.0          # min(10,35) + min(15,10) = 10+10
    assert capped is True


def test_total_cap_binds_even_when_individual_caps_do_not():
    """개별 캡(35/10)엔 안 걸려도 합계가 40을 넘으면 총합 캡이 걸려야 합니다."""
    g_eff, capped = _apply_cap(growth=33.0, sh_yield=9.0)   # 합계 42 > 40
    assert g_eff == 40.0
    assert capped is True


def test_boundary_values_are_inclusive_not_capped():
    """정확히 경계값(35.0/10.0/40.0)은 '초과'가 아니라 '도달'이라 캡에 걸린 것으로
    보지 않습니다(초과만 캡으로 취급 — > 이지 >= 가 아님, 실제 코드와 일치)."""
    g_eff, capped = _apply_cap(growth=35.0, sh_yield=5.0)
    assert g_eff == 40.0
    assert capped is False


def test_real_snapshot_reproduces_known_bug_case_and_fix():
    """실측 데이터 회귀 — 2026-08-30 발견 당시 스냅샷에서 실제로 밴드가 바뀐 종목
    (삼성SDI, growth=1747.8%)으로 '캡 이전 값'과 '캡 이후 값'을 둘 다 확인합니다.
    스냅샷이 다음 자동 수집으로 갱신돼 이 종목의 growth 값이 바뀔 수 있으므로,
    해당 종목을 못 찾으면 조용히 skip합니다(§0-1 — 못 찾은 걸 실패로 위장하지 않음)."""
    import pytest

    path = REPO_ROOT / "data" / "kospi200_pegy_latest.json"
    if not path.exists():
        pytest.skip("data/kospi200_pegy_latest.json 없음 — 로컬 개발 환경 전용 회귀")

    stocks = json.loads(path.read_text(encoding="utf-8")).get("stocks", [])
    target = next((s for s in stocks if s.get("code") == "006400"), None)  # 삼성SDI
    if target is None or target.get("growth") is None or target.get("growth", 0) <= GROWTH_CAP_PCT:
        pytest.skip("삼성SDI 데이터가 없거나 더 이상 극단적 고성장이 아님 — 최신 스냅샷 기준 skip")

    growth = target["growth"]
    sh = target["sh_return"] or 0.0
    vol_penalty = target["vol_penalty"]
    f_per = target["f_per"]

    # 캡 이전(버그 재현): 실제로 이전 코드가 만들던 값과 같아야 함
    g_eff_uncapped = growth + sh
    growth_eff_uncapped = g_eff_uncapped / vol_penalty
    f_pegy_uncapped = round(f_per / growth_eff_uncapped, 2) if growth_eff_uncapped >= PEGY_MIN_DENOMINATOR_PCT else None
    assert f_pegy_uncapped is not None and f_pegy_uncapped < 0.65, (
        "이 재현이 성립하려면 캡 이전 f_pegy가 '강력저평가'(<0.65) 여야 합니다 — "
        f"실제 {f_pegy_uncapped} (버그가 이미 다른 방식으로 고쳐졌을 수 있음)"
    )

    # 캡 이후(수정된 동작)
    g_eff_capped_value, is_capped = _apply_cap(growth, sh)
    growth_eff_capped = g_eff_capped_value / vol_penalty
    f_pegy_capped = round(f_per / growth_eff_capped, 2) if growth_eff_capped >= PEGY_MIN_DENOMINATOR_PCT else None
    assert is_capped is True
    assert f_pegy_capped is not None and f_pegy_capped > f_pegy_uncapped, (
        "캡을 적용하면 실효성장률이 낮아져 PEGY는 반드시 더 커져야(=덜 저평가로 보여야) 합니다"
    )
