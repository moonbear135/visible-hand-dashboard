# tests/test_data_validator.py
"""
🔴 utils/data_validator.py — 3단계 검증 하네스(DataValidator) 커버리지 보강
(TASK_HISTORY #175/#178)

배경: 2026-08-30 커버리지 재감사(#175)에서 이 파일이 50%(브랜치 포함)로 이
저장소의 핵심 계산 모듈 중 가장 낮다는 게 드러났습니다. 이 모듈은 이름 그대로
"PEGY 카드 하나를 화면에 내보내도 되는지 최종 승인하는 3단계 하네스"라 — 나머지
코드가 아무리 정확해도 이 승인 로직 자체가 틀리면 잘못된(또는 정당한데 걸러진)
데이터가 그대로 노출/차단됩니다. 특히 ②단계(`sanity_check_per`)와 ③단계
(`cross_reconcile`)는 지금까지 **단 하나의 테스트도 직접 호출한 적이 없었습니다**
(기존 유일한 관련 테스트인 `tests/test_quant.py::test_case8_data_validator_blocks_missing_raw_period`는
①단계의 한 갈래만 `run_pipeline`을 통해 간접적으로 지나갑니다).

이 파일은 실행 순서상 마지막 방어선인 이 모듈을 직접 호출해 각 단계·분기를
개별적으로 검증합니다. 새 프로덕션 로직은 만들지 않고(§0-3-10), 기존 상수
(`PERIOD_KEYWORDS`, `INDICATOR_TARGET_RULES`)도 새로 정의하지 않고 그대로
import해서 씁니다.

실행: python -m pytest tests/test_data_validator.py -v
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.data_validator import DataValidator, PERIOD_KEYWORDS, INDICATOR_TARGET_RULES


# =========================================================================
# ① classify_header_timeframe — 기존에 못 짚은 분기: DAILY 판정, QUARTERLY(추정 아님),
#    아무 키워드에도 안 걸리는 UNKNOWN 폴백.
# =========================================================================

def test_classify_header_timeframe_daily():
    assert DataValidator.classify_header_timeframe("일별 시세") == "DAILY"
    assert DataValidator.classify_header_timeframe("DAILY VOLUME") == "DAILY"


def test_classify_header_timeframe_quarterly_without_estimate():
    # 분기(Q)이면서 연간(TTM) 키워드가 없고, 추정치(E/P) 표시도 없는 경우 → 순수 QUARTERLY.
    assert DataValidator.classify_header_timeframe("2026.06(3개월)") == "QUARTERLY"


def test_classify_header_timeframe_quarterly_estimate():
    assert DataValidator.classify_header_timeframe("2026.09(E)") == "QUARTERLY_EST"


def test_classify_header_timeframe_annual_estimate():
    assert DataValidator.classify_header_timeframe("2026.12(E)") == "ANNUAL_EST"


def test_classify_header_timeframe_unknown_fallback():
    # DAILY·QUARTERLY·TTM 키워드가 전혀 없는 임의의 헤더 텍스트는 지어내지 않고 UNKNOWN.
    assert DataValidator.classify_header_timeframe("종목코드") == "UNKNOWN"
    assert DataValidator.classify_header_timeframe("") == "UNKNOWN"


# =========================================================================
# ② validate_raw_vs_processed — 필수 키 누락 차단, EPS 1:1 대조(일치/불일치/비교불가).
# =========================================================================

def _base_processed(**overrides):
    base = {
        "code": "005930", "name": "테스트종목",
        "price": 70000, "t_per": 14.0, "t_eps": 5000.0,
        "indicator_type": "PER",
    }
    base.update(overrides)
    return base


def test_validate_raw_vs_processed_missing_required_key_blocks():
    processed = _base_processed()
    del processed["t_eps"]
    ok, logs = DataValidator.validate_raw_vs_processed({"raw_period": "TTM"}, processed)
    assert ok is False
    assert any("필수 키" in line and "t_eps" in line for line in logs)


def test_validate_raw_vs_processed_missing_required_key_none_value_blocks():
    # 키는 있지만 값이 None인 경우도 "존재하지 않음"과 동일하게 차단돼야 함.
    processed = _base_processed(price=None)
    ok, logs = DataValidator.validate_raw_vs_processed({"raw_period": "TTM"}, processed)
    assert ok is False
    assert any("price" in line for line in logs)


def test_validate_raw_vs_processed_no_raw_period_blocks():
    # raw_period 가 아예 없으면(수집 단계에서 기간 판정 실패) 기본값으로 채워서
    # "자기 자신과 비교"가 되는 걸 막기 위해 명시적으로 차단합니다.
    ok, logs = DataValidator.validate_raw_vs_processed({}, _base_processed())
    assert ok is False
    assert any("raw_period 없음" in line for line in logs)


def test_validate_raw_vs_processed_target_mismatch_blocks():
    # PER 지표는 TTM 이어야 하는데 실제 수집된 기간이 QUARTERLY 면 교차 오염 의심으로 차단.
    ok, logs = DataValidator.validate_raw_vs_processed(
        {"raw_period": "QUARTERLY"}, _base_processed(indicator_type="PER")
    )
    assert ok is False
    assert any("타겟-목적 1:1 불일치" in line for line in logs)


def test_validate_raw_vs_processed_target_match_passes_stage1():
    ok, logs = DataValidator.validate_raw_vs_processed(
        {"raw_period": "TTM"}, _base_processed(indicator_type="PER")
    )
    assert ok is True
    assert any("타겟-목적 1:1 일치" in line for line in logs)


def test_validate_raw_vs_processed_eps_match_within_tolerance():
    raw = {"raw_period": "TTM", "raw_eps": 5010.0}   # 0.2% 차이, 절대차 10 < 5 이하 조건은 안 걸림
    processed = _base_processed(t_eps=5010.0)
    ok, logs = DataValidator.validate_raw_vs_processed(raw, processed)
    assert ok is True
    assert any("Raw-Processed 일치" in line for line in logs)


def test_validate_raw_vs_processed_eps_swap_mismatch_blocks():
    # 절대차가 5를 넘고 비율도 5%를 넘는 큰 괴리 — 자릿수/필드 스왑 의심 케이스.
    raw = {"raw_period": "TTM", "raw_eps": 5000.0}
    processed = _base_processed(t_eps=50000.0)  # 자릿수 하나 밀린 전형적 스왑 패턴
    ok, logs = DataValidator.validate_raw_vs_processed(raw, processed)
    assert ok is False
    assert any("Raw-Processed 1:1 불일치" in line for line in logs)


def test_validate_raw_vs_processed_eps_not_comparable_when_missing():
    # raw_eps 자체가 없으면 "비교 대상 없음"이라고만 남기고 그 이유로 차단하지는 않음.
    raw = {"raw_period": "TTM"}
    ok, logs = DataValidator.validate_raw_vs_processed(raw, _base_processed())
    assert ok is True
    assert any("직접비교 대상 없음" in line for line in logs)


# =========================================================================
# ③ sanity_check_per (2단계) — 지금까지 단 한 번도 직접 호출된 적 없던 함수.
# =========================================================================

def test_sanity_check_per_rejects_none_inputs():
    ok, logs = DataValidator.sanity_check_per(None, 5000.0, 14.0)
    assert ok is False
    assert any("수집되지 않은 값" in line for line in logs)

    ok, logs = DataValidator.sanity_check_per(70000, None, 14.0)
    assert ok is False

    ok, logs = DataValidator.sanity_check_per(70000, 5000.0, None)
    assert ok is False


def test_sanity_check_per_rejects_non_positive_price_or_eps():
    ok, logs = DataValidator.sanity_check_per(0, 5000.0, 14.0)
    assert ok is False
    assert any("0 이하" in line for line in logs)

    ok, logs = DataValidator.sanity_check_per(70000, -100.0, 14.0)
    assert ok is False


def test_sanity_check_per_passes_within_tolerance():
    # 70000 / 5000 = 14.0배 그대로 — 오차 0%.
    ok, logs = DataValidator.sanity_check_per(70000, 5000.0, 14.0)
    assert ok is True
    assert any("산티 체크 통과" in line for line in logs)


def test_sanity_check_per_passes_at_exact_tolerance_boundary():
    # 계산 PER = 14.7, 표기 PER = 14.0 → 오차 = 0.7/14.0 = 5.0%. 기본 tolerance=0.05와
    # 부동소수점 상 정확히 같은 경계에서 <= 비교가 통과 쪽으로 판정되는지 확인.
    price, eps, reported = 1470.0, 100.0, 14.0
    calc = price / eps
    diff_ratio = abs(calc - reported) / reported
    assert abs(diff_ratio - 0.05) < 1e-9, "이 테스트 데이터 자체가 5.0% 경계가 아니면 무의미"
    ok, logs = DataValidator.sanity_check_per(price, eps, reported, tolerance=0.05)
    assert ok is True


def test_sanity_check_per_fails_beyond_tolerance():
    # 계산 PER = 20.0, 표기 PER = 14.0 → 오차 42.9% > 5% 허용치.
    ok, logs = DataValidator.sanity_check_per(100000, 5000.0, 14.0)
    assert ok is False
    assert any("산티 체크 실패" in line for line in logs)


# =========================================================================
# ④ cross_reconcile (3단계) — sanity_check_per 와 함께 지금까지 미검증이던 함수.
# =========================================================================

def test_cross_reconcile_no_secondary_source_does_not_block_but_flags_unverified():
    ok, logs = DataValidator.cross_reconcile({"t_per": 14.0}, None)
    assert ok is True   # 차단하지 않음
    assert any("미수행" in line and "통과 아님" in line for line in logs), (
        "미수행과 통과를 혼동하면 안 됨 — 로그에 둘 다 명시돼야 함"
    )


def test_cross_reconcile_no_secondary_source_empty_dict_also_flags_unverified():
    # secondary_dict가 빈 딕셔너리({})인 경우도 falsy라 None과 동일하게 처리돼야 함.
    ok, logs = DataValidator.cross_reconcile({"t_per": 14.0}, {})
    assert ok is True
    assert any("미수행" in line for line in logs)


def test_cross_reconcile_within_tolerance_approves():
    primary = {"t_per": 14.0}
    secondary = {"t_per": 14.3}  # 오차 = 0.3/14.3 ≈ 2.1% <= 3%
    ok, logs = DataValidator.cross_reconcile(primary, secondary, tolerance=0.03)
    assert ok is True
    assert any("교차 검증 승인" in line for line in logs)


def test_cross_reconcile_beyond_tolerance_recommends_fallback():
    primary = {"t_per": 14.0}
    secondary = {"t_per": 20.0}  # 오차 = 6.0/20.0 = 30% > 3%
    ok, logs = DataValidator.cross_reconcile(primary, secondary, tolerance=0.03)
    assert ok is False
    assert any("괴리" in line and "Fallback 권장" in line for line in logs)


def test_cross_reconcile_missing_per_values_does_not_block():
    # 2차 출처는 있지만 비교할 t_per 값 자체가 없는 경우 — 차단하지 않고 정보성 로그만.
    ok, logs = DataValidator.cross_reconcile({"t_per": None}, {"t_per": 14.0})
    assert ok is True
    assert any("수치 교차 비교 완료" in line for line in logs)


# =========================================================================
# ⑤ run_pipeline — 3단계 전체 흐름의 각 단락(short-circuit) 지점.
#    ①단계 실패는 기존 test_quant.py::test_case8_... 에서 이미 검증하므로 여기서는
#    ②단계·③단계에서 멈추는 경로, 그리고 3단계 전체 통과 경로를 추가합니다.
# =========================================================================

def _base_raw(**overrides):
    base = {"raw_period": "TTM", "raw_eps": 5000.0}
    base.update(overrides)
    return base


def test_run_pipeline_stops_at_stage2_when_sanity_check_fails():
    # 1단계는 통과하지만, price/eps로 계산한 PER(20.0)이 표기 PER(14.0)과 크게 어긋남.
    processed = _base_processed(price=100000, t_eps=5000.0, t_per=14.0)
    ok, logs = DataValidator.run_pipeline(_base_raw(), processed)
    assert ok is False
    assert any("2단계 산티 체크 실패로 반영 차단" in line for line in logs)
    # 2단계에서 멈췄으니 3단계 교차 검증 로그는 아예 없어야 함(맨 앞 "=== ... 3단계
    # 하네스 검증 시작 ===" 안내줄은 파이프라인 전체 이름일 뿐이라 검사 대상에서 제외).
    assert not any("교차 검증" in line for line in logs)


def test_run_pipeline_stops_at_stage3_when_cross_reconcile_disagrees():
    processed = _base_processed(price=70000, t_eps=5000.0, t_per=14.0)
    secondary = {"t_per": 25.0}  # 1·2단계는 통과하지만 2차 출처와 크게 괴리
    ok, logs = DataValidator.run_pipeline(_base_raw(), processed, secondary_dict=secondary)
    assert ok is False
    assert any("3단계 교차 검증 오차 발생" in line for line in logs)


def test_run_pipeline_full_approval_through_all_three_stages():
    processed = _base_processed(price=70000, t_eps=5000.0, t_per=14.0)
    secondary = {"t_per": 14.2}  # 3단계까지 전부 허용 오차 이내
    ok, logs = DataValidator.run_pipeline(_base_raw(), processed, secondary_dict=secondary)
    assert ok is True
    assert any("최종 승인 (Pass)" in line for line in logs)


def test_run_pipeline_full_approval_without_secondary_source():
    # 2차 출처가 아예 없어도(교차검증 미수행) 파이프라인 자체는 차단되지 않고 통과해야 함
    # (cross_reconcile의 '미수행 ≠ 실패' 설계가 run_pipeline 레벨에서도 지켜지는지 확인).
    processed = _base_processed(price=70000, t_eps=5000.0, t_per=14.0)
    ok, logs = DataValidator.run_pipeline(_base_raw(), processed, secondary_dict=None)
    assert ok is True
    assert any("최종 승인 (Pass)" in line for line in logs)


# =========================================================================
# ⑥ 상수 자체에 대한 최소 회귀 — INDICATOR_TARGET_RULES/PERIOD_KEYWORDS가 실수로
#    비어버리는 사고를 잡기 위한 안전망(값 자체를 재정의하지 않고 존재/형태만 확인).
# =========================================================================

def test_indicator_target_rules_cover_expected_indicators():
    for indicator in ("PER", "EPS", "DPS", "PBR", "ROE"):
        assert INDICATOR_TARGET_RULES.get(indicator) == "TTM"
    assert INDICATOR_TARGET_RULES.get("QUARTERLY_EARNINGS") == "QUARTERLY"
    assert INDICATOR_TARGET_RULES.get("DAILY_PRICE") == "DAILY"


def test_period_keywords_has_all_four_buckets_nonempty():
    for bucket in ("TTM", "QUARTERLY", "DAILY", "ESTIMATE"):
        assert bucket in PERIOD_KEYWORDS
        assert len(PERIOD_KEYWORDS[bucket]) > 0
