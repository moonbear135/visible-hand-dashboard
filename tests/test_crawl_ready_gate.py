"""
🚦 크롤링 완료 게이트(`crawl_ready_gate.py`) + 소비 워크플로우의 `workflow_run` 배선 — 2026-09-07 (#204)

오너 방향 지시(#204): 크롤링 결과를 소비하는 배치는 고정 시각(cron)으로 "이쯤이면 끝났겠지" 하고
기다리지 말고, 크롤링이 **실제로 끝나는 이벤트**(`workflow_run`)로 곧바로 깨어나야 한다. cron 은
그 이벤트가 안 왔을 때의 **안전망**으로만 남긴다. 고정 시각을 뒤로 미루는 방향은 금지.

이 파일이 고정하는 것:
  §1  워크플로우 YAML 배선 — 소비자 5개(결투 KR/USD·성적표 KRW/USD·리포트 스냅샷)가
      ① 올바른 원천 워크플로우의 `name` 으로 `workflow_run` 을 걸었고 ② cron 이 안전망으로 남아 있고
      ③ job `if` 가 `conclusion == 'success'` + (schedule | workflow_dispatch) 를 거르며
      ④ 게이트 단계가 있고 ⑤ 실제 작업 단계가 게이트 결과(`steps.gate.outputs.ready`)에 묶여 있는지.
      ⑥ cron 값이 #203 시각에서 **뒤로 밀리지 않았는지**(오너 금지 방향).
  §2  게이트 판정표 — 임시 디렉터리에 스냅샷·벤치마크·기준값 파일을 만들어 소비자×역할별로
      "준비 완료 / 준비 안 됨 / 이미 처리함" 이 머리말 표대로 나오는지(파일도 네트워크도 실제 것은 안 씀).
  §3  실행 껍데기 — `$GITHUB_OUTPUT` 계약(ready=true|false, reason 한 줄), 종료 코드 0.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

import crawl_ready_gate as gate  # noqa: E402
from utils import duel_batch, report_db, scorecard_db  # noqa: E402
from utils.duel_rules import KST  # noqa: E402

yaml = pytest.importorskip("yaml", reason="PyYAML 없음")

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load_workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc):
    return doc.get("on", doc.get(True))     # YAML 1.1 에서 `on:` 이 True 로 읽히는 환경도 있음


def _workflow_name(filename):
    return _load_workflow(filename)["name"]


def _only_job(doc):
    jobs = doc["jobs"]
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def _step(job, contains):
    matches = [s for s in job["steps"] if contains in (s.get("name") or "")]
    assert len(matches) == 1, f"'{contains}' 단계가 정확히 하나여야 합니다: {[s.get('name') for s in job['steps']]}"
    return matches[0]


# =============================================================================
# §1. 워크플로우 배선
# =============================================================================
# 소비자 워크플로우 → (게이트 소비자 이름, 원천 워크플로우 파일들, #203 기준 cron, 게이트가 cron 에도 걸리는가)
CONSUMER_WORKFLOWS = {
    "duel_daily.yml": (gate.CONSUMER_DUEL_KR, ["scrape.yml"], ["10 8 * * 1-5"], True),
    "duel_daily_us.yml": (gate.CONSUMER_DUEL_US, ["scrape_us.yml", "scrape_report_snapshots.yml"],
                          ["0 3 * * *"], True),
    "scorecard_publish_daily.yml": (gate.CONSUMER_SCORECARD_KR, ["scrape.yml"], ["35 22 * * *"], False),
    "scorecard_publish_daily_us.yml": (gate.CONSUMER_SCORECARD_US,
                                       ["scrape_us.yml", "scrape_report_snapshots.yml"], ["35 2 * * *"], False),
    "scrape_report_snapshots.yml": (gate.CONSUMER_REPORT_SNAPSHOTS, ["scrape_us.yml"], ["20 23 * * 1-5"], False),
}
# 소비자가 실제로 배치를 돌리는 단계 이름(부분 문자열) — 게이트 결과에 묶여 있어야 하는 단계들
WORK_STEPS = {
    "duel_daily.yml": ["결투 야간 배치 실행", "신선도 기준값 파일 커밋"],
    "duel_daily_us.yml": ["결투 USD 야간 배치 실행", "신선도 기준값 파일(USD) 커밋"],
    "scorecard_publish_daily.yml": ["성적표 발행 배치 실행 (KRW)"],
    "scorecard_publish_daily_us.yml": ["성적표 발행 배치 실행 (USD)"],
    "scrape_report_snapshots.yml": ["미국 벤치마크", "스냅샷 적재", "벤치마크 이력 파일을 깃허브에 커밋"],
}


@pytest.mark.parametrize("filename", sorted(CONSUMER_WORKFLOWS))
def test_consumer_workflow_is_triggered_by_the_crawls_it_consumes(filename):
    """① workflow_run 이 **소비하는 크롤링 워크플로우의 `name`** 을 그대로 가리키고 types=[completed]."""
    consumer, sources, _crons, _gate_on_cron = CONSUMER_WORKFLOWS[filename]
    trigger = _triggers(_load_workflow(filename))
    run = trigger.get("workflow_run")
    assert run, f"{filename}: workflow_run 트리거가 없습니다 — cron 만으로 크롤링을 기다리면 안 됩니다(#204)."
    expected_names = [_workflow_name(src) for src in sources]
    assert run["workflows"] == expected_names, (
        f"{filename}: workflow_run.workflows={run['workflows']} — 원천 워크플로우의 name 과 글자 그대로 같아야 "
        f"합니다(원천 파일 {sources} 의 name: {expected_names}). name 이 바뀌면 이 연결이 조용히 끊깁니다."
    )
    assert run["types"] == ["completed"]
    # 게이트 소비자가 기다리는 시장과 원천이 맞는지(KR 소비자는 코스피 수집, US 소비자는 미국 수집).
    market_source = {scorecard_db.MARKET_KR: "scrape.yml", scorecard_db.MARKET_US: "scrape_us.yml"}
    for market in gate.CONSUMER_MARKETS[consumer]:
        assert market_source[market] in sources, f"{filename}: {market} 소비자인데 {market_source[market]} 완료를 안 받습니다"


@pytest.mark.parametrize("filename", sorted(CONSUMER_WORKFLOWS))
def test_consumer_workflow_keeps_its_cron_as_a_safety_net_without_moving_it_later(filename):
    """② cron 은 안전망으로 남고 ⑥ #203 시각에서 뒤로 밀리지 않았다(오너: 고정 시각을 늦추는 방향 금지)."""
    _consumer, _sources, crons, _gate_on_cron = CONSUMER_WORKFLOWS[filename]
    trigger = _triggers(_load_workflow(filename))
    actual = [entry["cron"] for entry in (trigger.get("schedule") or [])]
    assert actual == crons, (
        f"{filename}: cron {actual} ≠ #203 시각 {crons}. #204 는 cron 을 '순수 안전망'으로 남길 뿐 시각을 옮기지 "
        "않습니다 — 늦추고 싶다면 이 테스트를 고치기 전에 오너 확인(TASK_HISTORY #204 오너 지시)."
    )
    assert "workflow_dispatch" in trigger, f"{filename}: 수동 실행 경로는 그대로 있어야 합니다"


@pytest.mark.parametrize("filename", sorted(CONSUMER_WORKFLOWS))
def test_consumer_job_filters_the_workflow_run_event_like_duel_daily_does(filename):
    """③ job if — workflow_run 이 아니면 항상 참, workflow_run 이면 success + (schedule | workflow_dispatch)."""
    job = _only_job(_load_workflow(filename))
    condition = " ".join(str(job.get("if") or "").split())
    assert "github.event_name != 'workflow_run'" in condition, f"{filename}: cron·수동 경로가 항상 통과해야 합니다"
    assert "github.event.workflow_run.conclusion == 'success'" in condition, f"{filename}: 실패한 크롤링 뒤엔 돌면 안 됩니다"
    assert "github.event.workflow_run.event == 'schedule'" in condition
    # 🔴 #204 실측: Cloudflare Worker 가 workflow_dispatch 로 깨운 실행이 진짜 수집입니다. 이걸 거르면
    #    소비 배치가 4시간 늦게(GitHub cron 지연분 완료 뒤에야) 돕니다 — duel_daily.yml 머리말 #204.
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in condition, (
        f"{filename}: workflow_dispatch 로 돈 크롤링(Cloudflare Worker 16:10 발동)의 완료도 받아야 합니다(#204 실측)"
    )


@pytest.mark.parametrize("filename", sorted(CONSUMER_WORKFLOWS))
def test_consumer_workflow_gates_its_work_on_the_data_not_only_on_the_event(filename):
    """④ 게이트 단계(`crawl_ready_gate.py <소비자>`) ⑤ 실제 작업 단계가 게이트 결과에 묶임."""
    consumer, _sources, _crons, gate_on_cron = CONSUMER_WORKFLOWS[filename]
    job = _only_job(_load_workflow(filename))
    gate_step = _step(job, "크롤링 완료 게이트")
    assert gate_step.get("id") == "gate"
    run = gate_step["run"]
    assert f"python crawl_ready_gate.py {consumer}" in run, f"{filename}: 게이트 소비자 이름이 {consumer!r} 여야 합니다"
    names = [s.get("name") or "" for s in job["steps"]]
    assert names.index(gate_step["name"]) > names.index(next(n for n in names if "의존" in n)), \
        f"{filename}: 게이트는 의존성 설치 뒤에 와야 합니다(수집기·배치 모듈을 import 합니다)"

    if gate_on_cron:
        # 결투: 안전망 cron 도 "이미 처리함"을 거릅니다(같은 날 두 번째 실행이 보류 주문을 취소하는 경로 차단).
        assert gate_step.get("if") == "github.event_name != 'workflow_dispatch'"
        assert "safety-net" in run and '"schedule"' in run, f"{filename}: cron 이면 --role safety-net 로 불러야 합니다"
        expected_work_if = "github.event_name == 'workflow_dispatch' || steps.gate.outputs.ready == 'true'"
    else:
        # 발행·스냅샷: 멱등이라 cron·수동은 게이트 없이 항상, workflow_run 만 데이터로 거릅니다.
        assert gate_step.get("if") == "github.event_name == 'workflow_run'"
        assert "--role event" in run
        expected_work_if = "github.event_name != 'workflow_run' || steps.gate.outputs.ready == 'true'"

    for contains in WORK_STEPS[filename]:
        step = _step(job, contains)
        assert " ".join(str(step.get("if") or "").split()) == expected_work_if, (
            f"{filename}: '{step['name']}' 단계가 게이트 결과에 묶여 있지 않습니다: {step.get('if')!r}"
        )
    # 게이트 단계 뒤에 오는 단계 중 게이트에 안 묶인 것은 실패 안내(`if: failure()`)뿐이어야 합니다.
    after_gate = job["steps"][names.index(gate_step["name"]) + 1:]
    loose = [s["name"] for s in after_gate
             if " ".join(str(s.get("if") or "").split()) not in (expected_work_if, "failure()")]
    assert not loose, f"{filename}: 게이트에 묶이지 않은 단계가 있습니다: {loose}"


def test_gate_script_is_read_only_and_exits_zero_on_not_ready():
    """게이트는 아무것도 쓰지 않고(save_probe_state 호출 없음), '준비 안 됨'을 실패로 취급하지 않습니다."""
    source = (REPO_ROOT / "crawl_ready_gate.py").read_text(encoding="utf-8")
    assert "save_probe_state" not in source.replace("# ", ""), "게이트가 기준값 파일을 써서는 안 됩니다"
    assert "sys.exit(1)" not in source and "exit(3)" not in source
    assert "GITHUB_OUTPUT" in source


# =============================================================================
# §2. 판정표 — 임시 디렉터리 픽스처
# =============================================================================
TUE = datetime(2026, 9, 8, 17, 31, tzinfo=KST)       # 화요일 저녁 — 코스피 수집(16:10 Worker) 직후
WED_MORNING = datetime(2026, 9, 9, 8, 25, tzinfo=KST)  # 수요일 아침 — 미국 수집(05:35~) 직후
SAT = datetime(2026, 9, 12, 17, 31, tzinfo=KST)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _kr_snapshot(data_dir, *, status="SUCCESS", last_updated_at="2026-09-08 17:30"):
    _write_json(data_dir / scorecard_db.SNAPSHOT_FILENAMES[scorecard_db.MARKET_KR],
                {"metadata": {"status": status, "last_updated_at": last_updated_at}, "stocks": []})


def _us_snapshot(data_dir, *, status="SUCCESS", session_date="2026-09-08", last_updated_at_kst="2026-09-09 08:20"):
    _write_json(data_dir / scorecard_db.SNAPSHOT_FILENAMES[scorecard_db.MARKET_US],
                {"metadata": {"status": status, "session_hint": {"session_date": session_date},
                              "last_updated_at_et": f"{session_date} 19:20",
                              "last_updated_at_kst": last_updated_at_kst}, "stocks": []})


def _us_benchmark(data_dir, *, dates=("2026-09-04", "2026-09-08"), collected_at_kst="2026-09-08T10:04:00+09:00",
                  keys=report_db.US_BENCHMARK_KEYS):
    _write_json(data_dir / report_db.US_INDEX_HISTORY_FILENAME, {
        "metadata": {"collected_at_kst": collected_at_kst},
        "indices": {key: {"closes": {d: 100.0 + i for i, d in enumerate(dates)}} for key in keys},
    })


def _probe_state(path, target_date):
    _write_json(path, {"version": duel_batch.PROBE_STATE_VERSION, "target_date": target_date,
                       "index_keys": ["KOSPI"], "values": {"KOSPI": 3000.0, "005930": 70000.0}})


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def _names(result):
    return {c["name"]: c["ok"] for c in result["checks"]}


# ── duel-kr ────────────────────────────────────────────────────────────────
def test_duel_kr_event_is_ready_right_after_todays_post_close_kospi_snapshot(data_dir, tmp_path):
    _kr_snapshot(data_dir)
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is True and result["target_date"] == "2026-09-08"
    assert _names(result) == {"평일(KST)": True, "코스피 수집 완료": True, "오늘 아직 미처리": True}


@pytest.mark.parametrize("kwargs, why", [
    ({"last_updated_at": "2026-09-07 17:30"}, "어제 스냅샷(백필 dispatch·수집 실패 뒤의 완료)"),
    ({"last_updated_at": "2026-09-08 07:04"}, "오늘 날짜지만 장 시작 전 저장(#195 모양 — 어제 종가)"),
    ({"status": "DEGRADED"}, "DEGRADED 는 성공이 아님"),
])
def test_duel_kr_event_is_not_ready_when_the_kospi_snapshot_is_not_todays_close(data_dir, tmp_path, kwargs, why):
    _kr_snapshot(data_dir, **kwargs)
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is False, why
    assert _names(result)["코스피 수집 완료"] is False
    assert "준비 안 됨" in result["reason"]


def test_duel_kr_event_skips_weekends_like_its_cron(data_dir, tmp_path):
    _kr_snapshot(data_dir, last_updated_at="2026-09-12 17:30")   # 토요일 수동 수집(실측: 09-05·09-06 에 있었음)
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_EVENT, now=SAT, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is False and _names(result)["평일(KST)"] is False
    assert _names(result)["코스피 수집 완료"] is True     # 수집 자체는 끝났지만 주말이라 안 돎


def test_duel_kr_event_skips_when_todays_batch_already_committed_its_baseline(data_dir, tmp_path):
    """같은 날 두 번째 완료(GitHub cron 지연분·백필)는 건너뜀 — 보류 주문을 취소하는 두 번째 실행 차단."""
    _kr_snapshot(data_dir)
    _probe_state(tmp_path / "probe.json", "2026-09-08")
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is False and _names(result)["오늘 아직 미처리"] is False
    assert "이미" in result["reason"]


def test_duel_kr_safety_net_only_asks_whether_today_was_already_processed(data_dir, tmp_path):
    """cron 안전망: 수집 완료는 조건이 아님(크롤링이 안 된 날도 신선도 판정으로 주문을 정리해야 함)."""
    _kr_snapshot(data_dir, last_updated_at="2026-09-07 17:30")   # 오늘 수집 없음
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_SAFETY_NET, now=TUE, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is True and list(_names(result)) == ["오늘 아직 미처리"]
    _probe_state(tmp_path / "probe.json", "2026-09-08")
    again = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_SAFETY_NET, now=TUE, data_dir=str(data_dir),
                          state_path=str(tmp_path / "probe.json"))
    assert again["ready"] is False


def test_duel_kr_treats_a_broken_baseline_file_as_not_processed(data_dir, tmp_path):
    _kr_snapshot(data_dir)
    (tmp_path / "probe.json").write_text("{not json", encoding="utf-8")
    result = gate.evaluate(gate.CONSUMER_DUEL_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe.json"))
    assert result["ready"] is True and "읽지 못했습니다" in result["reason"]


# ── scorecard-kr ───────────────────────────────────────────────────────────
def test_scorecard_kr_event_follows_the_kospi_snapshot_and_has_no_already_done_check(data_dir):
    _kr_snapshot(data_dir)
    ready = gate.evaluate(gate.CONSUMER_SCORECARD_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir))
    assert ready["ready"] is True and list(_names(ready)) == ["코스피 수집 완료"]
    _kr_snapshot(data_dir, last_updated_at="2026-09-08 07:04")
    stale = gate.evaluate(gate.CONSUMER_SCORECARD_KR, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir))
    assert stale["ready"] is False
    # 주말에도 돕니다(cron 이 매일인 것과 같음) — 평일 검사가 없어야 합니다.
    _kr_snapshot(data_dir, last_updated_at="2026-09-12 17:30")
    weekend = gate.evaluate(gate.CONSUMER_SCORECARD_KR, gate.ROLE_EVENT, now=SAT, data_dir=str(data_dir))
    assert weekend["ready"] is True


def test_scorecard_safety_net_always_proceeds(data_dir):
    for consumer in (gate.CONSUMER_SCORECARD_KR, gate.CONSUMER_SCORECARD_US, gate.CONSUMER_REPORT_SNAPSHOTS):
        result = gate.evaluate(consumer, gate.ROLE_SAFETY_NET, now=TUE, data_dir=str(data_dir))
        assert result["ready"] is True, consumer
        assert "게이트 없음" in result["checks"][0]["name"]


# ── duel-us / scorecard-us ─────────────────────────────────────────────────
def test_duel_us_event_needs_stock_snapshot_and_both_benchmarks_for_yesterday_kst(data_dir, tmp_path):
    _us_snapshot(data_dir)
    _us_benchmark(data_dir)
    result = gate.evaluate(gate.CONSUMER_DUEL_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe_usd.json"))
    assert result["ready"] is True and result["target_date"] == "2026-09-08"
    assert _names(result) == {"미국 수집 완료": True, "미국 벤치마크 확보": True, "처리 거래일 아직 미처리": True}


def test_duel_us_event_is_not_ready_when_only_the_stock_crawl_finished(data_dir, tmp_path):
    """종목만 들어온 시점(scrape_us 완료, 벤치마크 전)엔 돌면 안 됨 — 지수 낡음 → 보류 → 다음 실행이 취소."""
    _us_snapshot(data_dir)
    _us_benchmark(data_dir, dates=("2026-09-04",))
    result = gate.evaluate(gate.CONSUMER_DUEL_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe_usd.json"))
    assert result["ready"] is False and _names(result)["미국 벤치마크 확보"] is False
    assert "2026-09-08 종가가 아직 없습니다" in result["reason"]


def test_duel_us_event_is_not_ready_when_one_benchmark_is_missing(data_dir, tmp_path):
    _us_snapshot(data_dir)
    _us_benchmark(data_dir, keys=report_db.US_BENCHMARK_KEYS[:1])
    result = gate.evaluate(gate.CONSUMER_DUEL_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe_usd.json"))
    assert result["ready"] is False and report_db.US_BENCHMARK_KEYS[1] in result["reason"]


@pytest.mark.parametrize("kwargs", [
    {"session_date": "2026-09-04"},        # 미국 휴장일 뒤(Labor Day 09-07 → 09-08 KST 수집이 금요일 세션)
    {"status": "DEGRADED"},
])
def test_duel_us_event_is_not_ready_when_the_stock_snapshot_is_not_the_target_session(data_dir, tmp_path, kwargs):
    _us_snapshot(data_dir, **kwargs)
    _us_benchmark(data_dir)
    result = gate.evaluate(gate.CONSUMER_DUEL_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe_usd.json"))
    assert result["ready"] is False and _names(result)["미국 수집 완료"] is False


def test_duel_us_skips_when_the_target_session_was_already_processed(data_dir, tmp_path):
    _us_snapshot(data_dir)
    _us_benchmark(data_dir)
    _probe_state(tmp_path / "probe_usd.json", "2026-09-08")
    for role in (gate.ROLE_EVENT, gate.ROLE_SAFETY_NET):
        result = gate.evaluate(gate.CONSUMER_DUEL_US, role, now=WED_MORNING, data_dir=str(data_dir),
                               state_path=str(tmp_path / "probe_usd.json"))
        assert result["ready"] is False, role
    _probe_state(tmp_path / "probe_usd.json", "2026-09-05")      # 토요일 대상 파일(지수 없음) — 아직 처리 전
    result = gate.evaluate(gate.CONSUMER_DUEL_US, gate.ROLE_SAFETY_NET, now=WED_MORNING, data_dir=str(data_dir),
                           state_path=str(tmp_path / "probe_usd.json"))
    assert result["ready"] is True


def test_scorecard_us_event_mirrors_duel_us_inputs_without_an_already_done_check(data_dir):
    _us_snapshot(data_dir)
    _us_benchmark(data_dir)
    ready = gate.evaluate(gate.CONSUMER_SCORECARD_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert ready["ready"] is True and list(_names(ready)) == ["미국 수집 완료", "미국 벤치마크 확보"]
    _us_benchmark(data_dir, dates=("2026-09-04",))
    waiting = gate.evaluate(gate.CONSUMER_SCORECARD_US, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert waiting["ready"] is False


# ── report-snapshots ───────────────────────────────────────────────────────
def test_report_snapshots_event_runs_once_per_stock_crawl(data_dir):
    _us_snapshot(data_dir)                                     # 09-09 08:20 KST 수집
    _us_benchmark(data_dir, dates=("2026-09-04",), collected_at_kst="2026-09-08T10:04:00+09:00")   # 어제 돈 벤치마크
    first = gate.evaluate(gate.CONSUMER_REPORT_SNAPSHOTS, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert first["ready"] is True
    # 이 워크플로우가 돌고 나면 벤치마크 수집 시각이 스냅샷 수집 시각 뒤가 됩니다 → 두 번째 완료
    # (scrape_us.yml 의 두 번째 cron 은 건너뛰기 실행)는 조용히 건너뜁니다.
    _us_benchmark(data_dir, collected_at_kst="2026-09-09T08:23:00+09:00")
    second = gate.evaluate(gate.CONSUMER_REPORT_SNAPSHOTS, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert second["ready"] is False and "이미 돌았습니다" in second["reason"]


def test_report_snapshots_event_is_ready_on_first_run_without_a_benchmark_file(data_dir):
    _us_snapshot(data_dir)
    result = gate.evaluate(gate.CONSUMER_REPORT_SNAPSHOTS, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert result["ready"] is True


def test_report_snapshots_event_waits_for_the_target_session_stock_snapshot(data_dir):
    _us_snapshot(data_dir, session_date="2026-09-04")
    result = gate.evaluate(gate.CONSUMER_REPORT_SNAPSHOTS, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir))
    assert result["ready"] is False


def test_missing_snapshot_files_mean_not_ready_not_an_exception(data_dir):
    for consumer in (gate.CONSUMER_DUEL_KR, gate.CONSUMER_SCORECARD_KR):
        assert gate.evaluate(consumer, gate.ROLE_EVENT, now=TUE, data_dir=str(data_dir),
                             state_path=str(data_dir / "x.json"))["ready"] is False
    for consumer in (gate.CONSUMER_DUEL_US, gate.CONSUMER_SCORECARD_US, gate.CONSUMER_REPORT_SNAPSHOTS):
        assert gate.evaluate(consumer, gate.ROLE_EVENT, now=WED_MORNING, data_dir=str(data_dir),
                             state_path=str(data_dir / "x.json"))["ready"] is False


def test_unknown_consumer_or_role_is_rejected():
    with pytest.raises(ValueError):
        gate.evaluate("duel-eu", gate.ROLE_EVENT, now=TUE)
    with pytest.raises(ValueError):
        gate.evaluate(gate.CONSUMER_DUEL_KR, "whenever", now=TUE)


# =============================================================================
# §3. 실행 껍데기 — $GITHUB_OUTPUT 계약
# =============================================================================
def test_main_writes_github_output_and_exits_zero_either_way(data_dir, tmp_path, capsys):
    _kr_snapshot(data_dir)
    out = tmp_path / "gh_output.txt"
    code = gate.main([gate.CONSUMER_SCORECARD_KR, "--role", "event", "--data-dir", str(data_dir),
                      "--now", "2026-09-08T17:31:00", "--github-output", str(out)])
    assert code == 0
    assert out.read_text(encoding="utf-8").splitlines()[0] == "ready=true"

    _kr_snapshot(data_dir, last_updated_at="2026-09-07 17:30")
    out2 = tmp_path / "gh_output2.txt"
    code = gate.main([gate.CONSUMER_SCORECARD_KR, "--data-dir", str(data_dir),
                      "--now", "2026-09-08T17:31:00", "--github-output", str(out2)])
    assert code == 0
    lines = out2.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ready=false" and lines[1].startswith("reason=") and len(lines) == 2
    assert "::notice title=크롤링 완료 게이트(scorecard-kr)::" in capsys.readouterr().out


def test_main_rejects_unknown_consumer_with_usage_error():
    with pytest.raises(SystemExit) as exc:
        gate.main(["duel-eu"])
    assert exc.value.code == 2
