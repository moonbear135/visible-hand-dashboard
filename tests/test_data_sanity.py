"""
tests/test_data_sanity.py
`utils/data_sanity.py` — 수집 결과 산티체크 판정기의 오프라인 회귀 테스트.

이 모듈은 순수 계산 + 파일 하나가 전부라 네트워크·Supabase·NiceGUI 없이 전부 검증됩니다.
상태 파일을 쓰는 경로는 항상 pytest 의 `tmp_path` 로 격리합니다 — 실제 `data/` 를 절대
건드리지 않습니다.

이 파일이 지키려는 것(작업지시 + ENGINEERING_SPEC §0-1):
  · 정상적인 하루는 **조용히** 통과해야 합니다(평소 변동성에 울면 알람이 무의미해집니다).
  · 건수 급감 / 전부 결측·0 / 값이 전부 동일 은 반드시 '의심'이어야 합니다.
  · 기준값이 없는 첫 실행은 **에러가 아니라 '판정 불가'** 로 우아하게 넘어가야 합니다.
  · 판정기는 **아무것도 고치지 않습니다** — 입력 행을 건드리지 않는지도 확인합니다.

관례: 이 파일은 `check()`/`FAILURES` 하네스를 쓰지 않고 순수 `assert` 만 씁니다
(`tests/test_collector_indicator_kr.py` 와 같은 방식). 하네스는 실패를 목록에 적기만 하고
예외를 던지지 않아 별도의 승격 장치가 필요한데(`tests/test_suite_integrity.py` Check A),
새 파일에 그 장치를 또 복사하는 것보다 pytest 가 원래 하는 일(assert)을 그대로 쓰는 편이
단순합니다(§0-3-10).

실행: python -m pytest tests/test_data_sanity.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import data_sanity as ds


# =====================================================================================
# 합성 데이터 헬퍼 — "정상적인 하루"를 흉내 냅니다.
#   실제 산출물 규모(코스피 507행 · 미국 548행 · 보조지표 500행)와 비슷하게 잡아야
#   min_rows_for_ratio_checks(30) 하한에 걸리지 않고 실제 판정 경로를 탑니다.
# =====================================================================================
FIELDS = ("price", "market_cap")


def make_rows(count=200, price_base=10000.0, cap_base=1.0e11, drift=1.0):
    """서로 다른 값이 충분히 섞인 '평범한 하루'. drift 로 전체 수준을 곱해 흔듭니다."""
    return [
        {
            "code": f"{index:06d}",
            "price": (price_base + index * 37.0) * drift,
            "market_cap": (cap_base + index * 5.0e8) * drift,
        }
        for index in range(count)
    ]


def probe(rows, fields=FIELDS):
    return ds.summarize_dataset(rows, fields)


# =====================================================================================
# 1. 정상적인 하루 — 조용히 통과
# =====================================================================================
def test_normal_day_is_quiet():
    yesterday = probe(make_rows(500))
    today = probe(make_rows(500, drift=1.01))      # 전체 수준 +1%
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=FIELDS)
    assert verdict["status"] == ds.STATUS_OK
    assert verdict["reasons"] == []
    assert not [c for c in verdict["checks"] if c["status"] == "fail"]


def test_normal_day_tolerates_ordinary_churn():
    """명단 교체 몇 종목 · 가격 ±10% 정도의 평범한 흔들림에는 울지 않아야 합니다."""
    yesterday = probe(make_rows(507))
    today = probe(make_rows(503, price_base=10500.0, drift=1.10))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=FIELDS)
    assert verdict["status"] == ds.STATUS_OK, verdict["reason"]


def test_market_wide_crash_is_not_flagged_as_data_defect():
    """중앙값 기준 -30% (제한폭에 가까운 폭락장)는 데이터 사고가 아니므로 통과해야 합니다."""
    yesterday = probe(make_rows(500))
    today = probe(make_rows(500, drift=0.70))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=FIELDS)
    assert verdict["status"] == ds.STATUS_OK, verdict["reason"]


# =====================================================================================
# 2. 건수 급감 / 급증
# =====================================================================================
def test_row_count_collapse_is_suspect():
    yesterday = probe(make_rows(500))
    today = probe(make_rows(300))                  # 40% 감소 (기준 30%)
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29")
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "row_count_drop" and c["status"] == "fail"
               for c in verdict["checks"])
    assert "건수 급감" in verdict["reason"]
    assert "500" in verdict["reason"] and "300" in verdict["reason"]   # 사람이 읽을 근거


def test_row_count_drop_just_below_threshold_stays_quiet():
    """경계 바로 안쪽(25% 감소)은 조용해야 합니다 — 기준이 실제로 30%인지 확인."""
    yesterday = probe(make_rows(400))
    today = probe(make_rows(300))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29")
    assert verdict["status"] == ds.STATUS_OK, verdict["reason"]


def test_empty_result_is_suspect_even_without_baseline():
    verdict = ds.judge_sanity(probe([], FIELDS), None)
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert "0건" in verdict["reason"]


def test_row_count_doubling_is_suspect():
    yesterday = probe(make_rows(200))
    today = probe(make_rows(400))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29")
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "row_count_surge" and c["status"] == "fail"
               for c in verdict["checks"])


# =====================================================================================
# 3. 핵심 컬럼이 전부 결측 / 전부 0
# =====================================================================================
def test_all_missing_core_column_is_suspect():
    rows = [dict(row, price=None) for row in make_rows(300)]
    verdict = ds.judge_sanity(probe(rows), None)      # 기준값이 없어도 잡혀야 합니다
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "unusable_ratio" and c["field"] == "price"
               and c["status"] == "fail" for c in verdict["checks"])
    assert "100.0%" in verdict["reason"]


def test_all_zero_core_column_is_suspect():
    rows = [dict(row, price=0) for row in make_rows(300)]
    verdict = ds.judge_sanity(probe(rows), None)
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert "price" in verdict["reason"]


def test_partial_missing_jump_is_suspect_even_below_absolute_threshold():
    """어제 0% → 오늘 28% 는 절대 기준(30%)에 못 미쳐도 급등(25%p)으로 잡혀야 합니다."""
    yesterday = probe(make_rows(500))
    rows = make_rows(500)
    for row in rows[:140]:                            # 28%
        row["price"] = None
    verdict = ds.judge_sanity(probe(rows), yesterday, baseline_date="2026-08-29")
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "unusable_ratio_jump" and c["status"] == "fail"
               for c in verdict["checks"])


def test_small_missing_rate_stays_quiet():
    """정상적으로 몇 % 비는 것은 울리지 않아야 합니다."""
    yesterday = probe(make_rows(500))
    rows = make_rows(500)
    for row in rows[:15]:                             # 3%
        row["price"] = None
    verdict = ds.judge_sanity(probe(rows), yesterday, baseline_date="2026-08-29")
    assert verdict["status"] == ds.STATUS_OK, verdict["reason"]


# =====================================================================================
# 4. 값이 전부 동일 (수집 실패를 상수로 채운 전형적 징후 — SPEC §0-1 예시 2)
# =====================================================================================
def test_constant_filled_column_is_suspect():
    rows = [dict(row, price=12.5) for row in make_rows(300)]
    verdict = ds.judge_sanity(probe(rows), None)
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "constant_value" and c["field"] == "price"
               and c["status"] == "fail" for c in verdict["checks"])
    assert "전부 같은 값" in verdict["reason"]


def test_constant_check_skipped_on_tiny_sample():
    """표본이 적으면(29행) 상수 판정을 하지 않습니다 — 적은 표본에서 우연히 같을 수 있음."""
    rows = [dict(row, price=12.5) for row in make_rows(29)]
    verdict = ds.judge_sanity(probe(rows), None)
    assert verdict["status"] != ds.STATUS_SUSPECT
    assert any(c["name"] == "constant_value" and c["status"] == "skipped"
               for c in verdict["checks"])


# =====================================================================================
# 5. 값 수준(중앙값) 급변 — level_fields 로 켠 컬럼만
# =====================================================================================
def test_unit_error_shifts_median_and_is_suspect():
    """원↔천원 같은 단위 사고: 값이 1000배가 되면 잡혀야 합니다."""
    yesterday = probe(make_rows(500))
    today = probe(make_rows(500, drift=1000.0))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=FIELDS)
    assert verdict["status"] == ds.STATUS_SUSPECT
    assert any(c["name"] == "median_shift" and c["status"] == "fail"
               for c in verdict["checks"])


def test_median_shift_not_checked_when_field_not_in_level_fields():
    """level_fields 에 없는 컬럼(예: RSI 같은 갇힌 오실레이터)은 수준 비교를 하지 않습니다."""
    yesterday = probe(make_rows(500))
    today = probe(make_rows(500, drift=1000.0))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=())
    assert verdict["status"] == ds.STATUS_OK, verdict["reason"]
    assert all(c["status"] == "skipped"
               for c in verdict["checks"] if c["name"] == "median_shift")


# =====================================================================================
# 6. 기준값이 없는 첫 실행 — 에러가 아니라 '판정 불가'
# =====================================================================================
def test_first_run_without_baseline_is_graceful(tmp_path):
    result = ds.check_dataset("demo_set", make_rows(400), FIELDS,
                              target_date="2026-08-30", level_fields=FIELDS,
                              data_dir=str(tmp_path), log=None)
    assert result["status"] == ds.STATUS_NO_BASELINE
    assert result["reasons"] == []
    assert "첫 실행" in result["reason"]
    assert result["baseline_date"] is None
    # 그래도 오늘 요약은 남아 내일의 기준값이 됩니다.
    assert result["probe"]["row_count"] == 400
    assert (tmp_path / "demo_set_sanity.json").exists()


def test_tiny_baseline_is_not_used_for_comparison():
    """어제가 이미 비정상(5행)이었으면 그 위에서 비율을 계산하지 않고 '판정 불가'입니다."""
    yesterday = probe(make_rows(5))
    today = probe(make_rows(500, drift=1000.0))
    verdict = ds.judge_sanity(today, yesterday, baseline_date="2026-08-29",
                              level_fields=FIELDS)
    assert verdict["status"] == ds.STATUS_NO_BASELINE
    assert "5건" in verdict["reason"]
    assert all(c["status"] == "skipped" for c in verdict["checks"]
               if c["name"] in ("row_count_drop", "row_count_surge",
                                "unusable_ratio_jump", "median_shift"))


def test_first_run_reason_says_it_is_a_first_run():
    verdict = ds.judge_sanity(probe(make_rows(500)), None)
    assert verdict["status"] == ds.STATUS_NO_BASELINE
    assert "첫 실행" in verdict["reason"]


def test_missing_state_file_load_returns_none(tmp_path):
    assert ds.load_sanity_state(str(tmp_path / "nope_sanity.json")) is None


def test_second_run_uses_yesterday_as_baseline(tmp_path):
    first = ds.check_dataset("demo_set", make_rows(500), FIELDS,
                             target_date="2026-08-29", level_fields=FIELDS,
                             data_dir=str(tmp_path), log=None)
    assert first["status"] == ds.STATUS_NO_BASELINE

    second = ds.check_dataset("demo_set", make_rows(500, drift=1.02), FIELDS,
                              target_date="2026-08-30", level_fields=FIELDS,
                              data_dir=str(tmp_path), log=None)
    assert second["status"] == ds.STATUS_OK
    assert second["baseline_date"] == "2026-08-29"
    assert second["baseline_row_count"] == 500

    third = ds.check_dataset("demo_set", make_rows(100), FIELDS,
                             target_date="2026-08-31", level_fields=FIELDS,
                             data_dir=str(tmp_path), log=None)
    assert third["status"] == ds.STATUS_SUSPECT
    assert third["baseline_date"] == "2026-08-30"

    saved = json.loads((tmp_path / "demo_set_sanity.json").read_text(encoding="utf-8"))
    assert saved["version"] == ds.SANITY_STATE_VERSION
    assert saved["status"] == ds.STATUS_SUSPECT
    assert saved["probe"]["row_count"] == 100


# =====================================================================================
# 7. 손상된 기준값 파일 — 조용히 넘기지 않고 크게 알립니다 (§0-1)
# =====================================================================================
def test_corrupt_state_file_raises_on_load(tmp_path):
    path = tmp_path / "demo_set_sanity.json"
    path.write_text('{"version": 1, "dataset"', encoding="utf-8")
    with pytest.raises(ds.DataSanityError):
        ds.load_sanity_state(str(path))


def test_unknown_version_is_refused(tmp_path):
    path = tmp_path / "demo_set_sanity.json"
    path.write_text(json.dumps({"version": 999, "dataset": "demo_set"}), encoding="utf-8")
    with pytest.raises(ds.DataSanityError):
        ds.load_sanity_state(str(path))


def test_check_dataset_reports_corrupt_baseline_as_error(tmp_path):
    (tmp_path / "demo_set_sanity.json").write_text("{{{ not json", encoding="utf-8")
    result = ds.check_dataset("demo_set", make_rows(400), FIELDS,
                              target_date="2026-08-30", level_fields=FIELDS,
                              data_dir=str(tmp_path), log=None)
    assert result["status"] == ds.STATUS_ERROR
    assert result["status"] in ds.ALERT_STATUSES          # 알림 대상이어야 합니다
    assert any("읽지 못했습니다" in reason for reason in result["reasons"])
    # 손상된 파일은 오늘 요약으로 덮어써져 내일은 정상으로 돌아옵니다.
    saved = json.loads((tmp_path / "demo_set_sanity.json").read_text(encoding="utf-8"))
    assert saved["probe"]["row_count"] == 400


def test_previous_payload_without_probe_is_treated_as_no_baseline(tmp_path):
    (tmp_path / "demo_set_sanity.json").write_text(json.dumps({
        "version": ds.SANITY_STATE_VERSION, "dataset": "demo_set",
        "status": ds.STATUS_ERROR, "probe": None,
    }), encoding="utf-8")
    result = ds.check_dataset("demo_set", make_rows(400), FIELDS,
                              target_date="2026-08-30", data_dir=str(tmp_path), log=None)
    assert result["status"] == ds.STATUS_NO_BASELINE


# =====================================================================================
# 8. check_dataset 은 절대 예외를 던지지 않지만, 삼키지도 않습니다
# =====================================================================================
@pytest.mark.parametrize("bad_rows", [None, {"stocks": []}, [1, 2, 3], "not-a-table"])
def test_check_dataset_never_raises_and_records_error(bad_rows, tmp_path):
    result = ds.check_dataset("demo_set", bad_rows, FIELDS,
                              target_date="2026-08-30", data_dir=str(tmp_path), log=None)
    assert result["status"] == ds.STATUS_ERROR
    assert result["reason"]                                   # 사유가 비어 있지 않음
    assert result["status"] in ds.ALERT_STATUSES


def test_check_dataset_rejects_bad_date_without_raising(tmp_path):
    result = ds.check_dataset("demo_set", make_rows(100), FIELDS,
                              target_date="2026/08/30", data_dir=str(tmp_path), log=None)
    assert result["status"] == ds.STATUS_ERROR
    assert "날짜" in result["reason"]


def test_dataset_key_with_path_traversal_is_refused():
    with pytest.raises(ds.DataSanityError):
        ds.sanity_state_path("../../etc/passwd")


def test_summarize_refuses_non_dict_rows():
    with pytest.raises(ds.DataSanityError):
        ds.summarize_dataset([{"price": 1.0}, 42], ("price",))


def test_summarize_refuses_empty_field_list():
    with pytest.raises(ds.DataSanityError):
        ds.summarize_dataset(make_rows(10), ())


# =====================================================================================
# 9. 판정기는 아무것도 고치지 않습니다 (§0-1)
# =====================================================================================
def test_judging_does_not_touch_input_rows(tmp_path):
    rows = [dict(row, price=None) for row in make_rows(300)]
    snapshot = json.dumps(rows, sort_keys=True)
    ds.check_dataset("demo_set", rows, FIELDS, target_date="2026-08-30",
                     data_dir=str(tmp_path), log=None)
    assert json.dumps(rows, sort_keys=True) == snapshot


# =====================================================================================
# 10. 값 읽기 — 지어내지 않고, 잘못 세지 않습니다
# =====================================================================================
def test_numeric_coercion_rules():
    rows = [
        {"v": 1.5}, {"v": "2,500"}, {"v": 0}, {"v": None},
        {"v": True}, {"v": "없음"}, {"v": float("nan")}, {},
    ]
    stat = ds.summarize_dataset(rows, ("v",))["fields"]["v"]
    assert stat["numeric_count"] == 3          # 1.5 / 2500 / 0
    assert stat["zero_count"] == 1
    assert stat["missing_count"] == 5          # None · True · "없음" · NaN · 키 없음
    assert stat["distinct_count"] == 3


def test_summarize_accepts_dataframe_like_input():
    """pandas DataFrame 도 그대로 받습니다(pandas 를 import 하지 않고 오리 타이핑)."""
    class FakeFrame:
        columns = ("price",)

        def to_dict(self, orient):
            assert orient == "records"
            return [{"price": 100.0}, {"price": 200.0}]

    summary = ds.summarize_dataset(FakeFrame(), ("price",))
    assert summary["row_count"] == 2
    assert summary["fields"]["price"]["numeric_count"] == 2


# =====================================================================================
# 11. 알림 문구 — 정상/판정 불가는 알리지 않고, 의심/오류만 알립니다
# =====================================================================================
def test_alert_lines_only_reports_problems():
    payloads = [
        {"dataset": "a", "status": ds.STATUS_OK, "reason": "괜찮음"},
        {"dataset": "b", "status": ds.STATUS_NO_BASELINE, "reason": "첫 실행"},
        {"dataset": "c", "status": ds.STATUS_SUSPECT, "reason": "건수 급감",
         "target_date": "2026-08-30", "baseline_date": "2026-08-29"},
        {"dataset": "d", "status": ds.STATUS_ERROR, "reason": "기준값 손상"},
    ]
    lines = ds.alert_lines(payloads)
    assert len(lines) == 2
    assert any("c" in line and "의심" in line and "건수 급감" in line for line in lines)
    assert any("d" in line and "판정 오류" in line for line in lines)


def test_alert_lines_flags_unknown_payload_shape():
    assert len(ds.alert_lines(["이건 dict 가 아님"])) == 1
    assert ds.alert_lines([]) == []


# =====================================================================================
# 12. 임계값은 한 곳에만 있습니다 (§0-3-10 단일 출처)
# =====================================================================================
def test_thresholds_can_be_overridden_for_experiments():
    yesterday = probe(make_rows(400))
    today = probe(make_rows(300))                      # 25% 감소
    assert ds.judge_sanity(today, yesterday)["status"] == ds.STATUS_OK
    strict = ds.judge_sanity(today, yesterday, thresholds={"row_drop_ratio": 0.10})
    assert strict["status"] == ds.STATUS_SUSPECT


def test_default_thresholds_are_documented_values():
    """수치를 바꿀 때 이 테스트가 같이 깨져서 '왜 바꿨는지'를 적게 만듭니다."""
    assert ds.DEFAULT_THRESHOLDS == {
        "row_drop_ratio": 0.30,
        "row_surge_ratio": 2.00,
        "unusable_ratio": 0.30,
        "unusable_ratio_jump": 0.25,
        "median_shift_ratio": 2.00,
        "min_rows_for_ratio_checks": 30,
    }


# =====================================================================================
# 13. 🔴 어제와 내용이 통째로 같은 날 (2026-09-08 신설, #219)
#
#     2026-09-04 에 **실제로 났던 사고**(#195)의 모양입니다. 수집기가 "오늘 날짜 라벨 +
#     어제 내용물" 스냅샷을 남기고 정식 수집을 건너뛰었는데, 이 워치독은 조용했습니다 —
#     결측도 없고, 건수도 같고, 중앙값 이동이 0 이라 검사 ①~⑥ 이 **전부 통과**시켰습니다.
#
#     오너: *"결투, 성적표, 사실 이 가격이에요 — 전부 다 적용이 안 되던 걸 찾았지."*
# =====================================================================================
def _frozen_check(result):
    return next(c for c in result["checks"] if c["name"] == "frozen_content")


def test_the_2026_09_04_incident_shape_is_now_caught():
    """🔴 이 테스트가 이 검사의 존재 이유입니다."""
    rows = make_rows(200)
    yesterday = probe(rows)
    today = probe(rows)                                # 어제 것을 그대로 다시 받은 날

    # 먼저, **기존 검사들은 여전히 이 날을 정상으로 봅니다** — 그게 사고의 원인이었습니다.
    for name in ("row_count_drop", "unusable_ratio", "constant_value"):
        old_checks = [c for c in ds.judge_sanity(today, yesterday)["checks"]
                      if c["name"] == name]
        assert all(c["status"] != "fail" for c in old_checks), (
            f"{name} 은 이 사고를 못 잡는 검사입니다(그래서 새 검사가 필요했습니다)")

    result = ds.judge_sanity(today, yesterday, baseline_date="2026-09-04")
    assert _frozen_check(result)["status"] == "fail"
    assert result["status"] == ds.STATUS_SUSPECT
    assert ds.STATUS_SUSPECT in ds.ALERT_STATUSES          # 알림까지 올라감
    detail = _frozen_check(result)["detail"]
    assert "전부 어제와 내용이 똑같습니다" in detail
    assert "휴장일이면 정상" in detail                      # 오탐일 수 있음을 같이 알림


def test_a_normal_day_passes_the_frozen_check_quietly():
    yesterday = probe(make_rows(200))
    today = probe(make_rows(200, drift=1.01))
    result = ds.judge_sanity(today, yesterday)
    assert _frozen_check(result)["status"] == "pass"
    assert result["status"] == ds.STATUS_OK


def test_one_column_standing_still_is_not_enough_to_alarm():
    """
    상장주식수처럼 며칠씩 안 바뀌는 컬럼이 있습니다. 컬럼 하나만 보고 판정하면 매일 웁니다 —
    **검사 대상 전부**가 그대로일 때만 걸려야 합니다.
    """
    rows = make_rows(200)
    yesterday = probe(rows)
    moved = [dict(row, price=row["price"] * 1.02) for row in rows]   # 시총은 그대로
    result = ds.judge_sanity(probe(moved), yesterday)
    assert _frozen_check(result)["status"] == "pass"
    assert "price" in _frozen_check(result)["detail"]


def test_first_run_does_not_claim_the_data_is_frozen():
    result = ds.judge_sanity(probe(make_rows(200)), None)
    assert _frozen_check(result)["status"] == "skipped"
    assert result["status"] == ds.STATUS_NO_BASELINE


def test_an_old_format_baseline_is_skipped_not_guessed():
    """
    2026-09-08 이전 기준값 파일에는 지문이 없습니다. 없는 것을 있는 척 추측하지 않고
    **하루 쉬고** 내일 기준값부터 비교합니다(§0-1).
    """
    yesterday = probe(make_rows(200))
    for stat in yesterday["fields"].values():
        del stat["fingerprint"]                        # 구형식 재현
    result = ds.judge_sanity(probe(make_rows(200)), yesterday)
    assert _frozen_check(result)["status"] == "skipped"
    assert "지문이 없어" in _frozen_check(result)["detail"]


def test_fingerprint_is_not_computed_here_but_borrowed(monkeypatch):
    """
    §0-3-10 — 지문 계산은 `utils/data_freshness` 한 곳에만 있어야 합니다.
    여기서 다시 구현하면 두 곳이 조용히 어긋납니다.
    """
    called = []
    monkeypatch.setattr(ds.data_freshness, "fingerprint",
                        lambda values: called.append(len(list(values))) or "고정지문")
    summary = probe(make_rows(50))
    assert called, "요약이 공용 지문 함수를 부르지 않았습니다"
    assert all(stat["fingerprint"] == "고정지문" for stat in summary["fields"].values())


def test_fingerprint_uses_raw_values_including_missing():
    """
    🔴 **사보타주로 고친 테스트입니다.** 처음 쓴 판(숫자 하나를 None 으로 바꿔 비교)은
    지문을 "숫자만 골라서" 내도 그대로 통과했습니다 — 숫자 하나가 빠지면 어차피 숫자
    묶음도 달라지기 때문입니다. 즉 **아무것도 못 지키는 테스트**였습니다.

    아래 두 경우는 **숫자 묶음이 완전히 같고 결측만 다른** 상황이라, 지문이 숫자만
    보면 "내용이 똑같다"가 되어 버립니다. 결측이 결측 그대로인 것도 내용의 일부입니다.
    """
    numeric = [{"price": 10000.0 + index} for index in range(195)]

    # ① 결측 5개가 **행으로 더 붙은** 날 — 숫자만 보면 어제와 완전히 같습니다.
    assert probe(numeric, ("price",))["fields"]["price"]["fingerprint"] != \
           probe(numeric + [{"price": None}] * 5, ("price",))["fields"]["price"]["fingerprint"]

    # ② 결측의 **모양이 바뀐** 날 (None → 빈 문자열). 출처가 필드를 빼다가 빈 값으로
    #    주기 시작한 경우인데, 숫자만 보면 이 변화가 지문에서 통째로 사라집니다.
    assert probe(numeric + [{"price": None}] * 5, ("price",))["fields"]["price"]["fingerprint"] != \
           probe(numeric + [{"price": ""}] * 5, ("price",))["fields"]["price"]["fingerprint"]


# =====================================================================================
# 14. 🔴 경고가 **수습할 수 있는 시각에** 도착하는가 (2026-09-08, #219)
#
#     오너: *"매일 오전 9시 30분이라는 시간은 참 애매한 시간대인데, 크롤링이 실패했어도
#     수습할 수 있는 시간도 아니고, 그날 장은 시작했으니까 장 종료까지 기다려야 하고."*
#     *"문제가 생긴 것을 수습할 시간을 벌기 위한 경고문들인데, 그 경고문들을 쓸 수가 없네."*
#
#     판정은 수집 직후에 이미 나와 있었는데 알림만 다음 날 09:30 에 갔습니다. 그 시각은
#     이미 장이 열린 뒤라, 다시 수집하면 장중 가격이 그날 종가로 저장됩니다.
#     이 테스트는 그 배선이 되돌아가지 않게 막습니다.
# =====================================================================================
WATCH_WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows", "watch_data_sanity.yml")


def _watch_yaml():
    yaml = pytest.importorskip("yaml", reason="PyYAML 이 없는 환경 (CI 에서는 검사됩니다)")
    with open(WATCH_WORKFLOW, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_sanity_watch_fires_when_collection_finishes_not_next_morning():
    config = _watch_yaml()[True]          # PyYAML 은 `on:` 을 불린 True 로 읽습니다
    assert "workflow_run" in config, (
        "산티체크 감시가 수집 완료 이벤트에 걸려 있지 않습니다 — 다음 날 09:30 에만 알리면 "
        "이미 장이 열린 뒤라 그날은 손쓸 수가 없습니다(§0-3-15).")
    assert config["workflow_run"]["types"] == ["completed"]


def test_korean_and_us_collectors_are_watched_separately():
    """
    오너: *"이 부분을 미국장 한국장을 분리해서 돌려야 하는 게 맞다고 생각해, 이게 커버가 안 돼."*
    두 시장은 마감이 12시간 가까이 다릅니다. 하루 한 번으로 묶으면 반드시 한쪽이 늦습니다.
    """
    watched = _watch_yaml()[True]["workflow_run"]["workflows"]
    assert "Daily Market Scraper" in watched, "코스피 수집 완료를 안 보고 있습니다"
    assert "Daily US Stocks Scraper" in watched, "미국주식 수집 완료를 안 보고 있습니다"


def test_daily_cron_survives_as_a_safety_net():
    """
    이벤트가 유실되거나 수집 워크플로우 자체가 안 돈 날을 받칠 것이 필요합니다.
    (그리고 watch_schedule_health.yml 이 이 워크플로우를 'daily' 로 감시하고 있습니다.)
    """
    assert _watch_yaml()[True].get("schedule"), "안전망 cron 이 사라졌습니다"


def test_watch_does_not_run_after_a_failed_collection():
    """
    수집이 실패한 날에는 상태 파일이 갱신되지 않습니다. 그걸 오늘 판정처럼 다시 알리면
    사실과 다릅니다(§0-1). "수집이 안 돌았다"는 watch_schedule_health.yml 의 관심사입니다.
    """
    condition = _watch_yaml()["jobs"]["check"]["if"]
    assert "conclusion == 'success'" in condition


def test_the_workflow_does_not_list_dataset_files():
    """
    §0-3-10 — 데이터셋 파일 목록을 YAML 에 적으면 수집기 쪽과 두 개의 출처가 생겨 어긋납니다.
    워크플로우 **이름**은 workflow_run 배선에 꼭 필요하지만, **파일 이름**은 아닙니다.
    """
    with open(WATCH_WORKFLOW, encoding="utf-8") as handle:
        text = handle.read()
    for banned in ("kospi200_sanity.json", "us_stocks_sanity.json", "indicator_kr_sanity.json"):
        assert banned not in text, f"YAML 에 데이터셋 파일명({banned})이 박혔습니다"
    assert "data/*_sanity.json" in text, "글롭으로 전부 보는 방식이 유지되어야 합니다"
