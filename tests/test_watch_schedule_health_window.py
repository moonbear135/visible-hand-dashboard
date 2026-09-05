# tests/test_watch_schedule_health_window.py
"""
🕒 `.github/workflows/watch_schedule_health.yml` 의 **판정 로직**(최근 window 안에
   conclusion=success 인 schedule 실행이 있었는가) 회귀 방지선.

왜 이 파일이 있는가
────────────────────────────────────────────────────────────────────────────
watch_schedule_health.yml 은 "크롤링이 조용히 안 도는" 상황을 잡아내는 워치독입니다.
그런데 그 워치독의 **핵심 판정**(성공 실행이 window 안에 있는가)은 YAML 안에
`python3 -c '...'` 로 인라인 삽입돼 있어서, 지금까지 단위 테스트가 한 건도 없었습니다.
여기서 부등호 방향 하나(`<=` → `<`)나 문자열 하나(`"success"`)가 어긋나면, 워치독은
멈추지 않고 **초록불을 계속 찍으면서** 정작 감시를 안 하게 됩니다 — 이 워치독이 막으려던
바로 그 "조용히 안 도는" 사고를, 이번엔 워치독 자신이 내는 모양입니다(§0-1).

이 파일이 검증하는 방식 — 사본을 만들지 않습니다 (§0-3-10)
────────────────────────────────────────────────────────────────────────────
같은 로직을 이 테스트 파일 안에 베껴 두고 검사하면, 나중에 워크플로우 쪽만 고쳐졌을 때
사본은 그대로라 테스트가 초록불인 채로 **두 코드가 몰래 어긋납니다**. 그래서 이 파일은
워크플로우 YAML 을 텍스트로 읽어 **그 안에 실제로 들어 있는 파이썬 소스를 그대로 뽑아**,
워크플로우가 부르는 것과 **똑같은 방식**(`python3 -c <소스> <NOW_TS> <WINDOW_HOURS>`,
JSON 은 stdin)으로 실행해서 stdout("yes"/"no")만 봅니다. 검증 대상이 사본이 아니라
프로덕션 코드 자신입니다.

⚠️ 이 파일이 **검증하지 않는 것** (오너가 알고 있어야 하는 한계)
────────────────────────────────────────────────────────────────────────────
판정 로직 **뒤쪽**의 알림 단계 — `gh issue create`(이슈 생성 + assignee 지정)와 디스코드
웹훅 전송 — 은 실제 GitHub/디스코드 부수효과가 있어 로컬에서 안전하게 실행해 볼 방법이
없습니다. 그 부분은 이 테스트의 사정권 **밖**이며, 여전히 **검증되지 않은 상태**입니다.
확인하려면 오너가 Actions 탭에서 이 워크플로우를 수동으로(workflow_dispatch) 한 번
돌려보는 수밖에 없습니다. 이 파일이 초록불이라고 해서 "알림도 잘 간다"는 뜻이 아닙니다.

📌 마커가 사라지면 조용히 통과하지 않습니다
────────────────────────────────────────────────────────────────────────────
소스 추출은 워크플로우 안의 두 마커 문자열에 의존합니다. 누군가 그 부분을 고쳐서 마커가
안 보이게 되면, 추출 실패를 "검사할 게 없네"로 넘기지 않고 **명시적으로 실패**시킵니다
(`_MarkerNotFound`). 추출이 조용히 빈손이 되는 순간 이 파일 전체가 아무것도 검사하지
않는 초록불이 되기 때문입니다 — 그게 정확히 이 저장소가 세 번 겪은 결함의 모양입니다.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "watch_schedule_health.yml"

# 워크플로우 안에서 판정 스크립트를 감싸고 있는 두 마커.
#   LATEST_OK=$(echo "$RESP" | python3 -c '
#   ...파이썬 소스...
#   ' "$NOW_TS" "$WINDOW_HOURS")
# 같은 파일 안에 디스코드 payload 용 `python3 -c '` 가 하나 더 있으므로, 시작 마커는
# `LATEST_OK=$(...` 까지 통째로 포함해 그쪽과 절대 헷갈리지 않게 합니다.
START_MARKER = 'LATEST_OK=$(echo "$RESP" | python3 -c \''
END_MARKER = '\' "$NOW_TS" "$WINDOW_HOURS")'

# 워크플로우가 실행 목록을 읽어 들일 때 쓰는 시각 형식(GitHub API `created_at`).
GH_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"

def kst_ts(year, month, day, hour, minute=0):
    """KST(=UTC+9, 한국은 1988년 이후 서머타임 없음) 벽시계 시각 → epoch 초.

    ⚠️ 예전에는 여기에 epoch 숫자를 손으로 적어 뒀는데(`NOW_TS = 1756512000`), 그 값은
       주석이 말하는 2026-08-30 이 아니라 **2025-08-30(토)** 이었습니다 — 사람이 못 알아채는
       종류의 어긋남입니다. 이제 날짜를 그대로 적고 계산하게 해서 그 어긋남 자체를 없앱니다.
    """
    import datetime
    tz = datetime.timezone(datetime.timedelta(hours=9))
    return int(datetime.datetime(year, month, day, hour, minute, tzinfo=tz).timestamp())


def kst_dow(ts):
    """epoch 초 → KST 기준 요일(1=월 ... 7=일). 워크플로우의 `TZ=Asia/Seoul date +%u` 와 같은 값."""
    import datetime
    tz = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.fromtimestamp(ts, tz).isoweekday()


# 테스트 기준 시각 — 2026-09-01(화) 18:00 KST = 09:00 UTC.
# 2026-09-01 은 오너가 이 허점을 실전에서 발견한 날이고, 18:00 KST 는 그 결과 바뀐
# **이 워치독의 실제 cron 발동 시각**(cron '0 9 * * *')입니다. 즉 기본값이 곧 "실전에서
# 이 스크립트가 도는 바로 그 순간"입니다.
NOW_TS = kst_ts(2026, 9, 1, 18, 0)

# ── 장중/장마감 경계 시각들 (2026-09-01 추가) ────────────────────────────────
# 한국 증시 정규장은 평일 09:00~15:30 KST. 워크플로우는 이 구간이면 자동 재실행(POST)을
# 아예 걸지 않습니다. 아래 값들로 그 경계를 양쪽에서 못 박습니다.
TS_TUE_MARKET_MIDDAY = kst_ts(2026, 9, 1, 11, 0)    # 화 11:00 — 한복판
TS_TUE_MARKET_OPEN   = kst_ts(2026, 9, 1, 9, 0)     # 화 09:00 정각 — 개장(포함)
TS_TUE_MARKET_CLOSE  = kst_ts(2026, 9, 1, 15, 30)   # 화 15:30 정각 — 마감(포함)
TS_TUE_BEFORE_OPEN   = kst_ts(2026, 9, 1, 8, 59)    # 화 08:59 — 개장 1분 전(장중 아님)
TS_TUE_AFTER_CLOSE   = kst_ts(2026, 9, 1, 15, 31)   # 화 15:31 — 마감 1분 후(장중 아님)
TS_SAT_MIDDAY        = kst_ts(2026, 9, 5, 11, 0)    # 토 11:00 — 시각은 장중대지만 휴장
TS_MON_AFTER_CLOSE   = kst_ts(2026, 9, 7, 18, 0)    # 월 18:00 — 월요일 76시간 창 검증용

HOUR = 3600


class _MarkerNotFound(AssertionError):
    """워크플로우에서 판정 스크립트를 못 찾았을 때 — 조용한 통과 대신 빨간불."""


def extract_window_check_source(workflow_text):
    """
    워크플로우 YAML **텍스트**에서 인라인 판정 스크립트의 파이썬 소스를 그대로 뽑아냅니다.

    `run: |` 블록 스칼라 안에 들어 있으므로, 실제로 셸에 전달되는 소스는 그 블록의 공통
    들여쓰기가 제거된 형태입니다(YAML 이 알아서 벗겨냅니다). 여기서도 `textwrap.dedent`
    로 같은 처리를 해서, **GitHub Actions 가 실행하는 것과 글자 그대로 같은 소스**를
    돌려줍니다. (그 처리가 진짜 YAML 파서와 일치하는지는 아래
    `test_extracted_source_matches_real_yaml_parser` 가 따로 못 박습니다.)

    마커를 못 찾거나 두 번 이상 나오면 `_MarkerNotFound` 로 **명시적으로 실패**합니다 —
    추출이 실패했는데 테스트가 초록불이 되는 상황을 만들지 않기 위해서입니다.
    """
    starts = workflow_text.count(START_MARKER)
    if starts != 1:
        raise _MarkerNotFound(
            f"판정 스크립트 시작 마커를 {starts}번 찾았습니다(1번이어야 함).\n"
            f"  찾던 문자열: {START_MARKER!r}\n"
            f"  누군가 {WORKFLOW_PATH.name} 의 그 부분을 고쳤다면, 이 테스트가 조용히\n"
            f"  통과하지 않도록 여기서 실패시킵니다 — 마커를 새 형태에 맞춰 갱신하고\n"
            f"  이 파일의 검사가 여전히 진짜 로직을 검증하는지 확인하세요."
        )

    body_start = workflow_text.index(START_MARKER) + len(START_MARKER)
    end_at = workflow_text.find(END_MARKER, body_start)
    if end_at == -1:
        raise _MarkerNotFound(
            f"판정 스크립트 종료 마커를 못 찾았습니다.\n"
            f"  찾던 문자열: {END_MARKER!r} (시작 마커 뒤쪽에서)\n"
            f"  스크립트가 어디서 끝나는지 알 수 없으면 추출 자체가 무의미하므로 실패시킵니다."
        )

    source = textwrap.dedent(workflow_text[body_start:end_at])
    if "workflow_runs" not in source or "print(" not in source:
        raise _MarkerNotFound(
            f"마커 사이에서 뽑아낸 소스가 판정 스크립트로 보이지 않습니다(추출 범위가\n"
            f"  어긋났을 가능성). 뽑아낸 내용:\n{source!r}"
        )
    return source


def load_window_check_source():
    """저장소의 실제 워크플로우 파일에서 판정 스크립트를 읽어옵니다."""
    if not WORKFLOW_PATH.is_file():
        raise _MarkerNotFound(f"워크플로우 파일이 없습니다: {WORKFLOW_PATH}")
    return extract_window_check_source(WORKFLOW_PATH.read_text(encoding="utf-8"))


def run_window_check(runs_payload, now_ts=NOW_TS, window_hours=30):
    """
    추출한 스크립트를 **워크플로우와 똑같은 호출 방식**으로 실행합니다:
    `python3 -c <소스> <NOW_TS> <WINDOW_HOURS>` + GitHub API 응답 JSON 은 stdin.
    반환값은 stdout 을 다듬은 문자열("yes" / "no").
    """
    source = load_window_check_source()
    proc = subprocess.run(
        [sys.executable, "-c", source, str(now_ts), str(window_hours)],
        input=json.dumps(runs_payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"판정 스크립트가 종료코드 {proc.returncode} 로 죽었습니다.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return proc.stdout.strip()


def run_entry(hours_ago, conclusion="success", now_ts=None):
    """`hours_ago` 시간 전에 만들어진 실행 한 건(GitHub API 응답 모양 그대로).

    `now_ts` 를 주면 그 시각 기준으로 계산합니다 — 장중/장마감 시나리오처럼 기준 시각을
    옮겨 가며 돌리는 검사에서, 실행 기록만 옛 기준(NOW_TS)에 남아 창 밖으로 밀려나는
    일이 없도록 하기 위한 것입니다.
    """
    import datetime

    base = NOW_TS if now_ts is None else now_ts
    created = datetime.datetime.fromtimestamp(
        base - hours_ago * HOUR, tz=datetime.timezone.utc
    )
    return {
        "created_at": created.strftime(GH_TIME_FMT),
        "conclusion": conclusion,
        "event": "schedule",
    }


def payload(*entries):
    """GitHub API `.../runs` 응답 모양으로 감쌉니다."""
    return {"total_count": len(entries), "workflow_runs": list(entries)}


# =====================================================================================
# 0. 추출 자체가 조용히 빈손이 되지 않게 (§0-1)
# =====================================================================================
def test_workflow_file_exists_and_script_is_extractable():
    """이 파일의 모든 검사가 서 있는 전제 — 실제 워크플로우에서 소스를 뽑을 수 있는가."""
    source = load_window_check_source()
    assert source.strip(), "판정 스크립트가 비어 있습니다"
    # 뽑아낸 게 정말 그 로직인지 최소한의 확인(추출 범위가 엉뚱한 곳을 잡았을 때 대비)
    assert "created_at" in source and "conclusion" in source, source


def test_extraction_fails_loudly_when_markers_are_gone():
    """
    마커가 사라지면(=누군가 그 부분을 고쳤으면) **명시적으로 실패**해야 합니다.
    여기서 조용히 넘어가면, 이 파일은 아무것도 검증하지 않으면서 영원히 초록불입니다.
    """
    with pytest.raises(_MarkerNotFound):
        extract_window_check_source("name: nothing here\njobs: {}\n")

    # 시작 마커만 있고 끝 마커가 없는 경우(스크립트 끝을 알 수 없음)도 실패여야 합니다.
    with pytest.raises(_MarkerNotFound):
        extract_window_check_source(START_MARKER + "\nimport json\n")

    # 마커가 두 번 나오는 경우(어느 쪽이 진짜인지 알 수 없음)도 실패여야 합니다.
    real = WORKFLOW_PATH.read_text(encoding="utf-8")
    with pytest.raises(_MarkerNotFound):
        extract_window_check_source(real + real)


def test_extracted_source_matches_real_yaml_parser():
    """
    위 `textwrap.dedent` 처리가 진짜 YAML 파서의 블록 스칼라 처리와 **같은 결과**인지
    확인합니다(=GitHub Actions 가 셸에 넘기는 문자열과 글자 그대로 동일한지).
    PyYAML 이 없는 환경에서는 이 교차 확인만 건너뜁니다 — 나머지 검사는 그대로 돕니다.
    """
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음 — YAML 파서 교차 확인만 건너뜀")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    run_script = doc["jobs"]["check"]["steps"][0]["run"]
    source = load_window_check_source()
    assert source in run_script, (
        "추출한 소스가 YAML 파서가 만들어 내는 실제 셸 스크립트 안에 그대로 들어 있지\n"
        "않습니다 — 들여쓰기 처리가 어긋났다는 뜻이고, 그러면 이 테스트는 실제로 돌아가는\n"
        "것과 다른 코드를 검증하고 있는 셈입니다.\n"
        f"--- 추출한 소스 ---\n{source}"
    )


# =====================================================================================
# 1. 핵심 판정 — window 안에 conclusion=success 인 실행이 있는가
# =====================================================================================
def test_recent_successful_run_inside_window_says_yes():
    """window(30시간) 안에 성공 실행이 있으면 "yes"."""
    assert run_window_check(payload(run_entry(2)), window_hours=30) == "yes"


def test_successful_run_older_than_window_says_no():
    """성공했지만 40시간 전 — 30시간 window 밖이므로 "no"(이게 워치독의 존재 이유)."""
    assert run_window_check(payload(run_entry(40)), window_hours=30) == "no"


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", "startup_failure"])
def test_recent_run_that_did_not_succeed_says_no(conclusion):
    """
    시간은 window 안이지만 성공이 아닌 실행 — "no".
    (발동은 했는데 실패한 경우를 "정상"으로 세면, 데이터가 안 들어오는데도 워치독이
    조용히 초록불을 찍습니다 — §0-1 이 금지하는 "실패를 정상으로 위장".)
    """
    assert run_window_check(payload(run_entry(2, conclusion)), window_hours=30) == "no"


def test_in_progress_run_with_null_conclusion_says_no():
    """
    아직 도는 중인 실행은 GitHub API 가 `"conclusion": null` 로 줍니다 — 성공이 아니므로
    "no". (실제 응답에 흔히 섞여 들어오는 모양이라 명시적으로 못 박습니다.)
    """
    entry = run_entry(1)
    entry["conclusion"] = None
    assert run_window_check(payload(entry), window_hours=30) == "no"


def test_empty_workflow_runs_says_no():
    """
    실행 기록이 아예 없음 → "no". `gh api` 가 실패했을 때 워크플로우가 대신 넣어 주는
    `{"workflow_runs":[]}` 도 정확히 이 모양이라, 조회 실패가 "정상"으로 둔갑하지 않는지를
    함께 확인하는 셈입니다.
    """
    assert run_window_check(payload(), window_hours=30) == "no"


def test_missing_workflow_runs_key_says_no():
    """응답에 `workflow_runs` 키 자체가 없어도 죽지 않고 "no"(스크립트는 `.get` 을 씁니다)."""
    assert run_window_check({"total_count": 0}, window_hours=30) == "no"


def test_mixed_runs_with_exactly_one_qualifying_says_yes():
    """
    성공/실패 · 최근/오래됨이 섞인 실제와 비슷한 목록에서, 조건을 만족하는 건 단 하나
    (5시간 전 성공)뿐일 때 "yes".
    """
    runs = payload(
        run_entry(1, "failure"),      # 최근이지만 실패
        run_entry(5, "success"),      # ✅ 유일하게 조건 만족
        run_entry(29, "cancelled"),   # window 안이지만 취소
        run_entry(50, "success"),     # 성공이지만 window 밖
    )
    assert run_window_check(runs, window_hours=30) == "yes"


def test_mixed_runs_with_none_qualifying_says_no():
    """같은 모양인데 '5시간 전 성공' 한 건만 실패로 바뀌면 판정이 뒤집혀야 합니다."""
    runs = payload(
        run_entry(1, "failure"),
        run_entry(5, "failure"),
        run_entry(29, "cancelled"),
        run_entry(50, "success"),
    )
    assert run_window_check(runs, window_hours=30) == "no"


# =====================================================================================
# 2. 경계값 — `now - created <= window` (경계 포함)
# =====================================================================================
def test_run_exactly_at_window_boundary_is_included():
    """정확히 `now - window` 시각의 성공 실행은 **포함**입니다(`<=`, 등호 포함)."""
    assert run_window_check(payload(run_entry(30)), window_hours=30) == "yes"


def test_run_one_second_outside_window_is_excluded():
    """경계에서 1초 더 오래됐으면 제외 — 위 테스트와 짝으로 부등호 방향을 못 박습니다."""
    entry = run_entry(30)
    assert run_window_check(payload(entry), now_ts=NOW_TS + 1, window_hours=30) == "no"


def test_run_one_second_inside_window_is_included():
    """경계 안쪽 1초는 포함."""
    entry = run_entry(30)
    assert run_window_check(payload(entry), now_ts=NOW_TS - 1, window_hours=30) == "yes"


def test_monday_76_hour_window_reaches_last_friday():
    """
    월요일에 쓰는 넓은 창(76시간)이 실제로 지난 금요일 실행까지 닿는지.
    (주말엔 평일 워크플로우가 안 돌기 때문에 월요일만 창을 넓힙니다 — 이 값이 다시
    30으로 좁아지면 월요일마다 오탐 이슈가 쏟아집니다.)
    """
    assert run_window_check(payload(run_entry(72)), window_hours=76) == "yes"
    assert run_window_check(payload(run_entry(72)), window_hours=30) == "no"
    assert run_window_check(payload(run_entry(80)), window_hours=76) == "no"


def test_future_timestamps_are_not_rejected():
    """
    시계 오차 등으로 `created_at` 이 `now` 보다 아주 조금 미래인 경우(음수 경과시간)도
    `<= window` 를 만족하므로 "yes" — 현재 동작을 있는 그대로 기록해 둡니다(이 스크립트는
    미래 시각을 걸러내지 않습니다).
    """
    assert run_window_check(payload(run_entry(-1)), window_hours=30) == "yes"


def run_window_check_raw(raw_stdin, now_ts=NOW_TS, window_hours=30):
    """`run_window_check()`와 같지만 stdin에 **가공하지 않은 원본 문자열**을 그대로 넣습니다.

    RESP가 유효한 JSON이 아니게 되는 경로(2026-08-30 오너 실전 확인 중 발견한 버그 —
    아래 회귀 테스트들 참고)를 재현하려면 `json.dumps()`를 거치지 않은 임의의 문자열을
    stdin으로 보낼 수 있어야 합니다.
    """
    source = load_window_check_source()
    proc = subprocess.run(
        [sys.executable, "-c", source, str(now_ts), str(window_hours)],
        input=raw_stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc


# =====================================================================================
# 3. 방어적 파싱 — RESP가 유효한 JSON이 아닐 때도 죽지 않고 "no" (2026-08-30 실전 발견)
# =====================================================================================
#
# 배경: 오너가 실제로 `workflow_dispatch`를 존재하지 않는 워크플로우 파일명으로 돌려보다가
# 발견한 진짜 프로덕션 버그입니다. 당시 코드는
#     RESP=$(gh api ... 2>/dev/null || echo '{"workflow_runs":[]}')
# 한 줄이었는데, `gh api`가 실패하면서 에러 응답 몸통을 stderr가 아니라 **stdout에** 이미
# 찍어 놓은 경우 `2>/dev/null`이 그걸 못 막고, 뒤이어 `|| echo`의 출력까지 이어 붙어 RESP가
# JSON 두 덩어리가 나란히 붙은 문자열이 됐습니다. 그 결과 `json.load`가
# `JSONDecodeError: Extra data`로 죽고 **잡 전체가 예외로 중단** — `has_failures` 출력
# 자체가 안 만들어져서 이슈 생성 단계로 아예 못 넘어갔습니다(워치독이 놓친 걸 놓침).
#
# 고친 방식 — bash 쪽은 `if ! RESP=$(...); then RESP=...; fi`로 나눠 실패 시 RESP를
# 통째로 덮어쓰게 했고(이어붙기 자체를 막음), python 쪽도 2중 안전장치로
# `json.load` → `json.loads(...)` + try/except를 추가해 **어떤 이유로든** RESP가 유효한
# JSON이 아니게 되면 예외로 죽는 대신 "확인 못 함 = no"로 안전한 쪽으로 떨어지게 했습니다.
def test_concatenated_json_blobs_says_no_instead_of_crashing():
    """실제로 관측된 그 모양 그대로 — 에러 JSON 뒤에 폴백 JSON이 그대로 이어 붙은 입력."""
    raw = ('{"message": "Not Found", "documentation_url": '
           '"https://docs.github.com/rest", "status": "404"}'
           '{"workflow_runs":[]}')
    proc = run_window_check_raw(raw)
    assert proc.returncode == 0, f"죽으면 안 됩니다.\nstderr: {proc.stderr}"
    assert proc.stdout.strip() == "no"


def test_completely_invalid_json_says_no_instead_of_crashing():
    """JSON이 전혀 아닌 임의의 문자열(예: 사람이 읽는 에러 메시지)도 죽지 않고 "no"."""
    proc = run_window_check_raw("Internal Server Error: rate limit exceeded")
    assert proc.returncode == 0, f"죽으면 안 됩니다.\nstderr: {proc.stderr}"
    assert proc.stdout.strip() == "no"


def test_empty_stdin_says_no_instead_of_crashing():
    """stdin이 완전히 빈 문자열이어도(예: gh api가 아무것도 못 찍고 죽은 경우) "no"."""
    proc = run_window_check_raw("")
    assert proc.returncode == 0, f"죽으면 안 됩니다.\nstderr: {proc.stderr}"
    assert proc.stdout.strip() == "no"


def test_valid_json_that_is_not_a_dict_says_no():
    """유효한 JSON이지만 최상위가 dict가 아닌 경우(배열·문자열 등)도 "no"."""
    for raw in ("[]", '"hello"', "42", "null"):
        proc = run_window_check_raw(raw)
        assert proc.returncode == 0, f"입력 {raw!r} 에서 죽으면 안 됩니다.\nstderr: {proc.stderr}"
        assert proc.stdout.strip() == "no", f"입력 {raw!r} 에서 no 가 아니었습니다: {proc.stdout!r}"


def test_output_is_exactly_yes_or_no():
    """
    셸이 `[ "$LATEST_OK" = "yes" ]` 로 문자열을 그대로 비교하므로, 출력이 정확히
    "yes"/"no" 여야 합니다(대소문자·따옴표·군더더기 금지).
    """
    assert run_window_check(payload(run_entry(2))) == "yes"
    assert run_window_check(payload()) == "no"



# =====================================================================================
# 4. 자동 재실행(workflow_dispatch) 호출부 — 가짜 `gh` 위에서 오프라인 실행 (2026-08-31)
# =====================================================================================
#
# 배경: 워치독이 "알림만" 하던 것을 바꿔, 빠진 대상을 발견하면 그 자리에서 딱 한 번
# workflow_dispatch 로 다시 돌리게 했습니다(2026-08-31). 이 호출부는 GitHub 에 실제
# 부수효과(진짜 크롤링 워크플로우 발동)를 내기 때문에 로컬에서 진짜로 돌려볼 수 없습니다.
# 그래서 `gh` 와 `date` 를 PATH 앞쪽의 가짜 실행파일로 갈아끼우고, **워크플로우의 첫 스텝
# 셸 스크립트 자체**(사본이 아니라 YAML 에서 파싱해 꺼낸 프로덕션 코드 — §0-3-10)를 그
# 위에서 통째로 실행해, 어떤 인자로 몇 번 호출이 나갔는지를 봅니다. 네트워크는 전혀 타지
# 않습니다.
#
# 가짜 `gh` 는 GET `.../runs` 에 대해 **진짜 GitHub API 처럼 `event=` 쿼리 파라미터를
# 그대로 적용**합니다. 그래서 아래 `..._auto_dispatch_run_counts_as_ran` 테스트는 쿼리에서
# `event=schedule` 필터가 되살아나는 순간 빨간불이 됩니다 — 그 필터가 있으면 어제 자동
# 재실행으로 성공한 것이 안 보여서 **매일 헛되이 재실행을 반복**하기 때문입니다.
#
# ⚠️ 여전히 검증하지 않는 것: "재실행이 진짜 성공했는지". 그건 이 기능의 책임이 아니고
# (그러면 감시의 감시가 됩니다), 어차피 다음 날 이 워치독이 다시 판정합니다.

_GH_STUB = r'''import json, os, sys
from urllib.parse import urlparse, parse_qs

args = sys.argv[1:]
with open(os.environ["GH_CALL_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")

# POST .../dispatches — 재실행 트리거. 종료코드는 테스트가 정합니다.
if "-X" in args and "POST" in args:
    sys.exit(int(os.environ.get("GH_DISPATCH_RC", "0")))

# `gh issue create ...` — 두 번째 스텝(이슈 알림)이 부릅니다. 실제 이슈를 만들 수는 없으니
# 호출 인자만 위 로그에 남기고(=본문 전문이 그대로 남습니다) 성공한 척 끝냅니다.
# ⚠️ 이 분기가 없으면 아래 URL 파싱이 "create" 를 API 경로로 오해해 스텁이 죽습니다 —
#    그러면 테스트가 검증하려던 본문이 아니라 스텁의 사고를 보게 됩니다.
if args and args[0] == "issue":
    print("https://github.com/%s/issues/1" % os.environ.get("REPO", "owner/repo"))
    sys.exit(0)

# 첫 번째 `repos/...` 인자가 API 경로입니다 (`-H "Accept: ..."` 처럼 옵션이 앞에 올 수 있음).
api_path = next((a for a in args if a.startswith("repos/")), None)
if api_path is None:
    sys.exit(2)
parsed = urlparse(api_path)

# GET repos/<owner>/<repo>/contents/<path>?ref=main — 데이터 파일 원문(2026-09-05, 데이터
# 갱신 확인). 테스트가 GH_DATA_FILES(JSON: {저장소 상대경로: 파일 원문}) 로 내용을 정하고,
# 없는 경로는 진짜 API 처럼 실패(404)합니다.
if "/contents/" in parsed.path:
    rel = parsed.path.split("/contents/")[1]
    files = json.load(open(os.environ["GH_DATA_FILES"], encoding="utf-8"))
    if rel not in files:
        print(json.dumps({"message": "Not Found", "status": "404"}))
        sys.exit(1)
    sys.stdout.write(files[rel])
    sys.exit(0)

# GET repos/<owner>/<repo>/actions/workflows/<FILE>/runs?...
wf_file = parsed.path.split("/actions/workflows/")[1].split("/runs")[0]
runs = json.load(open(os.environ["GH_RUN_STATUS"], encoding="utf-8"))[wf_file]

# 진짜 GitHub API 와 같게 event 필터를 적용합니다(쿼리에 있을 때만).
events = parse_qs(parsed.query).get("event")
if events:
    runs = [r for r in runs if r.get("event") in events]

print(json.dumps({"total_count": len(runs), "workflow_runs": runs}))
'''

# 가짜 `date` — "지금"을 테스트가 완전히 통제합니다.
#
#   FAKE_NOW_TS : `date -u +%s` 가 돌려줄 epoch 초. 워크플로우는 이 값 하나에서
#                 (a) window 판정의 기준 시각과 (b) **장중 여부**(KST 분 환산)를 둘 다
#                 계산하므로, 이 환경변수 하나로 "가짜 현재 시각이 장중인가/장마감 후인가"가
#                 정해집니다(2026-09-01 — 별도의 FAKE_HHMM 을 두지 않은 이유가 그것입니다.
#                 두 개를 따로 두면 서로 어긋난 상태로도 테스트가 통과해 버립니다).
#   FAKE_DOW    : `TZ=Asia/Seoul date +%u` 가 돌려줄 KST 요일(1=월 ... 7=일).
#                 `run_check_step()` 은 기본적으로 FAKE_NOW_TS 에서 이 값을 **계산해서**
#                 넘기므로 둘이 어긋나지 않습니다(주말 검사처럼 일부러 어긋내고 싶을 때만
#                 `dow=` 로 직접 지정).
#
# 이슈 스텝이 제목에 쓰는 `TZ=Asia/Seoul date '+%Y-%m-%d %H:%M'` 도 FAKE_NOW_TS 에서
# 만들어 줍니다 — 진짜 시계로 새면 같은 테스트가 실행 시각에 따라 다른 값을 보게 됩니다.
_DATE_STUB = r'''import datetime, os, subprocess, sys

args = sys.argv[1:]
if args == ["-u", "+%s"]:
    print(os.environ["FAKE_NOW_TS"])
elif args == ["+%u"]:
    print(os.environ["FAKE_DOW"])
elif len(args) == 1 and args[0].startswith("+") and os.environ.get("TZ") == "Asia/Seoul":
    tz = datetime.timezone(datetime.timedelta(hours=9))
    moment = datetime.datetime.fromtimestamp(int(os.environ["FAKE_NOW_TS"]), tz)
    print(moment.strftime(args[0][1:]))
else:
    sys.exit(subprocess.run(["/bin/date"] + args).returncode)
'''

# 워크플로우 헤더의 "확인 대상" 목록 및 스크립트 안 TARGETS 와 같은 순서.
ALL_TARGETS = [
    "scrape.yml",
    "scrape_us.yml",
    "indicator_kr.yml",
    "scrape_report_snapshots.yml",
    "duel_daily.yml",
    "duel_daily_us.yml",
    "scorecard_publish_daily.yml",
    "watch_dividend_disclosures.yml",
    "watch_dividend_payment_events.yml",
    "watch_data_sanity.yml",   # 2026-09-03 추가 — 8/30 신설 때 감시 목록에서 빠져 있던 daily 대상
]
WEEKDAY_ONLY_TARGETS = ALL_TARGETS[:5]
DAILY_TARGETS = ALL_TARGETS[5:]

REPO_SLUG = "moonbear135/visible-hand-dashboard"

# ── 데이터 갱신 확인 대상 (2026-09-05 #196, #199 확장) — 워크플로우 TARGETS 의 3·4·5번째 필드와 동일 ──
# {워크플로우 파일: (데이터 파일 저장소 상대경로, 타임스탬프 JSON 키, 판정 규칙)}
#   kr           : 기대 거래일(KST) + 장마감 15:30 KST 이후                          (#196)
#   us           : 타임스탬프(ET)가 담는 거래일 == 지금(ET)이 담는 거래일 (마감+30분 규칙)  (#199)
#   daily@HH:MM  : 타임스탬프 날짜(KST) == 기대 실행일 (그 워크플로우 cron 의 KST 시각)   (#199)
DATA_TARGETS = {
    "scrape.yml": ("data/kospi200_pegy_latest.json", "metadata.last_updated_at", "kr"),
    "scrape_us.yml": ("data/us_stocks_latest.json", "metadata.last_updated_at_et", "us"),
    "indicator_kr.yml": ("data/indicator_kr_latest.json", "generated_at", "kr"),
    "scrape_report_snapshots.yml": ("data/us_index_history.json", "metadata.collected_at_et", "us"),
    "watch_dividend_disclosures.yml": ("data/cache/dividend_kr_2026_watch_state.json",
                                       "updated_at_kst", "daily@05:00"),
    "watch_dividend_payment_events.yml": ("data/cache/dividend_kr_2026_payment_state.json",
                                          "updated_at_kst", "daily@05:30"),
}
KR_DATA_TARGETS = [wf for wf, (_p, _k, rule) in DATA_TARGETS.items() if rule == "kr"]
US_DATA_TARGETS = [wf for wf, (_p, _k, rule) in DATA_TARGETS.items() if rule == "us"]
DAILY_DATA_TARGETS = [wf for wf, (_p, _k, rule) in DATA_TARGETS.items() if rule.startswith("daily@")]
# 일부러 데이터 확인을 붙이지 않은 대상 — 헤더 🔴 #199 문단의 "일부러 넣지 않은 대상"과 동일해야 합니다.
CONCLUSION_ONLY_TARGETS = ["duel_daily.yml", "duel_daily_us.yml", "scorecard_publish_daily.yml",
                           "watch_data_sanity.yml"]
KR_CLOSE_MIN = 15 * 60 + 30   # 15:30 KST — 아래 test_market_close_constant_... 가 상수 파일과 대조
US_READY_MIN = 16 * 60 + 30   # 16:30 ET (마감 16:00 + 30분) — test_us_constants_match_... 가 상수 파일과 대조


def _kst():
    import datetime
    return datetime.timezone(datetime.timedelta(hours=9))


def _et():
    """미국 동부(America/New_York) — 서머타임 자동. 워크플로우 인라인 파이썬과 같은 zoneinfo."""
    zoneinfo = pytest.importorskip("zoneinfo", reason="zoneinfo 없음(Python 3.9+)")
    try:
        return zoneinfo.ZoneInfo("America/New_York")
    except Exception as exc:   # tzdata 없는 환경(Windows 에서 tzdata 미설치 등)
        pytest.skip(f"America/New_York 시간대 정보를 불러올 수 없음: {exc}")


def expected_trade_date(now_ts):
    """워크플로우가 "기대 거래일"로 삼는 날짜 — 지금이 평일 장마감 이후면 오늘, 아니면 가장
    최근 평일. (검사 대상 로직의 사본이지만, 아래 검사들은 이 헬퍼가 아니라 **날짜를 글자로
    박은** 시나리오로도 같은 판정을 못 박아서 사본이 틀려도 조용히 통과하지 않습니다.)"""
    import datetime
    now = datetime.datetime.fromtimestamp(now_ts, _kst())
    day = now.date()
    if not (day.isoweekday() <= 5 and now.hour * 60 + now.minute >= KR_CLOSE_MIN):
        day -= datetime.timedelta(days=1)
    while day.isoweekday() > 5:
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def us_session_date(moment_et):
    """collector_us_stocks.py::resolve_collection_session_et() 규칙의 사본 — 그 순간(ET)에
    수집하면 담기는 거래일: 마감+30분(16:30 ET)이 지난 가장 최근 평일. (위 expected_trade_date
    와 같은 이유로, 아래 검사들은 날짜를 글자로 박은 시나리오로도 판정을 못 박습니다.)"""
    import datetime
    probe = moment_et.date()
    while True:
        ready = datetime.datetime(probe.year, probe.month, probe.day,
                                  US_READY_MIN // 60, US_READY_MIN % 60, tzinfo=moment_et.tzinfo)
        if probe.isoweekday() <= 5 and moment_et >= ready:
            return probe.isoformat()
        probe -= datetime.timedelta(days=1)


def expected_us_session(now_ts):
    import datetime
    return us_session_date(datetime.datetime.fromtimestamp(now_ts, _et()))


def expected_daily_date(now_ts, deadline_hhmm):
    """daily@HH:MM 규칙의 "기대 실행일" — 지금(KST)이 그 시각을 지났으면 오늘, 아니면 어제."""
    import datetime
    now = datetime.datetime.fromtimestamp(now_ts, _kst())
    day = now.date()
    if now.hour * 60 + now.minute < deadline_hhmm[0] * 60 + deadline_hhmm[1]:
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def data_file_text(wf_file, stamp, status="SUCCESS"):
    """실제 파일 모양 그대로(키 위치가 제각각입니다 — 코스피는 metadata 안, 보조지표는 최상위,
    미국 두 파일은 metadata 안(키 이름 다름), 배당 감시 상태 파일은 최상위 두 키뿐)."""
    if wf_file == "scrape.yml":
        return json.dumps({"metadata": {"last_updated_at": stamp, "status": status,
                                        "total_count": 500},
                           "stocks": []}, ensure_ascii=False)
    if wf_file == "indicator_kr.yml":
        return json.dumps({"generated_at": stamp, "date": stamp[:10], "status": status,
                           "success_count": 500, "stocks": []}, ensure_ascii=False)
    if wf_file == "scrape_us.yml":
        return json.dumps({"metadata": {"last_updated_at_et": stamp, "status": status,
                                        "total_count": 549, "currency": "USD"},
                           "stocks": []}, ensure_ascii=False)
    if wf_file == "scrape_report_snapshots.yml":
        # collector_us_indices.py 는 `_now_et().isoformat()` 로 초·오프셋까지 적습니다.
        iso = stamp.replace(" ", "T") + ":52.665805-04:00" if len(stamp) == 16 else stamp
        return json.dumps({"metadata": {"collected_at_et": iso, "is_etf_proxy": True,
                                        "fetched_any": True},
                           "indices": {}}, ensure_ascii=False)
    if wf_file in ("watch_dividend_disclosures.yml", "watch_dividend_payment_events.yml"):
        # `_write_watch_state()` / `write_payment_state()` 가 남기는 모양 그대로.
        iso = stamp.replace(" ", "T") + ":50.321560+09:00" if len(stamp) == 16 else stamp
        return json.dumps({"last_checked_de": stamp[:10].replace("-", ""),
                           "updated_at_kst": iso}, ensure_ascii=False)
    raise AssertionError(f"{wf_file} 는 데이터 갱신 확인 대상이 아닙니다")


def fresh_stamp_for(wf_file, now_ts, hhmm=None):
    """그 대상의 규칙으로 "정상"이 되는 타임스탬프 하나 — 검사 시각(now_ts)에서 계산."""
    _path, _key, rule = DATA_TARGETS[wf_file]
    if rule == "kr":
        hh, mm = hhmm or (16, 5)
        return f"{expected_trade_date(now_ts)} {hh:02d}:{mm:02d}"
    if rule == "us":
        hh, mm = hhmm or (16, 35)          # scrape_us.yml 첫 cron(20:35 UTC = 16:35 EDT) 시각
        return f"{expected_us_session(now_ts)} {hh:02d}:{mm:02d}"
    deadline = tuple(int(x) for x in rule.split("@", 1)[1].split(":"))
    hh, mm = hhmm or (7, 13)               # 실측(2026-09-05 07:13 KST — cron 05:00 에서 GitHub 지연분)
    return f"{expected_daily_date(now_ts, deadline)} {hh:02d}:{mm:02d}"


def fresh_data_files(now_ts, hhmm=(16, 5)):
    """모든 데이터 대상이 각자의 규칙으로 "정상"으로 찍힌 데이터 파일 세트.
    `hhmm` 은 kr 대상(코스피·보조지표)의 시각만 바꿉니다(기존 호출부 호환)."""
    files = {}
    for wf, (path, _key, rule) in DATA_TARGETS.items():
        files[path] = data_file_text(wf, fresh_stamp_for(wf, now_ts, hhmm if rule == "kr" else None))
    return files


def contents_calls(calls):
    """가짜 `gh` 호출 중 데이터 파일 조회(contents API)만 골라 그 경로를 돌려줍니다."""
    out = []
    for c in calls:
        api = next((a for a in c if isinstance(a, str) and a.startswith("repos/")), "")
        if "/contents/" in api:
            out.append(api.split("/contents/")[1].split("?")[0])
    return out


def load_check_step_script():
    """워크플로우 첫 스텝(`감시대상 스케줄 확인`)의 셸 스크립트를 YAML 에서 그대로 꺼냅니다."""
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음 — 스텝 스크립트를 꺼낼 수 없음")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    script = doc["jobs"]["check"]["steps"][0]["run"]
    if "dispatches" not in script:
        raise _MarkerNotFound(
            "첫 스텝 스크립트 안에서 재실행 호출부(`.../dispatches`)를 못 찾았습니다.\n"
            "  누군가 자동 재실행을 지웠거나 다른 스텝으로 옮겼다면, 아래 검사들이 조용히\n"
            "  아무것도 검증하지 않는 초록불이 되므로 여기서 명시적으로 실패시킵니다."
        )
    if "MARKET_HOURS" not in script:
        raise _MarkerNotFound(
            "첫 스텝 스크립트 안에서 장중 판정(`MARKET_HOURS`)을 못 찾았습니다"
            " (2026-09-01 추가).\n"
            "  이게 사라지면 워치독이 장중에도 자동 재실행을 걸게 되고, 그러면 백필이 안 되는\n"
            "  수집기(collector_kospi200.py · collector_indicator_kr.py)가 장중 가격을 그날\n"
            "  종가인 것처럼 저장합니다 — 아래 장중 검사들이 조용히 무의미해지지 않도록\n"
            "  여기서 명시적으로 실패시킵니다."
        )
    if "DATA_FRESH" not in script or "/contents/" not in script:
        raise _MarkerNotFound(
            "첫 스텝 스크립트 안에서 데이터 갱신 확인(`DATA_FRESH` / contents API)을 못 찾았습니다"
            " (2026-09-05 #196 추가).\n"
            "  이게 사라지면 `--skip-if-not-ready` 로 아무것도 수집하지 않고 exit 0 한 실행을\n"
            "  워치독이 다시 '성공'으로 오판합니다 — 아래 데이터 갱신 검사들이 조용히\n"
            "  무의미해지지 않도록 여기서 명시적으로 실패시킵니다."
        )
    return script


def load_issue_step_script():
    """두 번째 스텝(`이슈로 알림 + 잡 실패 처리`)의 셸 스크립트를 YAML 에서 그대로 꺼냅니다."""
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음 — 스텝 스크립트를 꺼낼 수 없음")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = doc["jobs"]["check"]["steps"]
    if len(steps) < 2:
        raise _MarkerNotFound(f"이슈 알림 스텝이 없습니다(스텝 {len(steps)}개).")
    script = steps[1]["run"]
    if "gh issue create" not in script:
        raise _MarkerNotFound(
            "두 번째 스텝에서 `gh issue create` 를 못 찾았습니다 — 이슈 본문 검사가 조용히\n"
            "  아무것도 검증하지 않게 되므로 여기서 실패시킵니다."
        )
    return script


def _write_stub(path, body):
    path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
    path.chmod(0o755)


def run_check_step(tmp_path, run_status, dispatch_rc=0, dow=None, now_ts=None,
                   data_files=None):
    """
    가짜 `gh`/`date` 위에서 첫 스텝 스크립트를 통째로 실행합니다(네트워크 없음).

    `run_status` 는 {워크플로우 파일명: [실행 항목, ...]} — 가짜 `gh` 가 그대로 돌려줍니다.
    `now_ts` 는 가짜 "지금"(생략하면 NOW_TS = 화 18:00 KST, 실제 cron 발동 시각),
    `dow` 는 KST 요일(1=월 ... 7=일 — 생략하면 `now_ts` 에서 계산해 둘이 어긋나지 않게 합니다),
    `dispatch_rc` 는 재실행 트리거의 종료코드입니다.
    `data_files` 는 {저장소 상대경로: 파일 원문} — 가짜 `gh` 의 contents API 가 돌려줄 데이터
    파일(2026-09-05 데이터 갱신 확인). 생략하면 두 대상 모두 "기대 거래일 16:05" 로 찍힌
    정상 파일을 줍니다(그래야 실행 결과만 다루는 기존 검사들이 데이터 쪽에서 오탐 없이
    예전 판정을 그대로 봅니다). 빈 dict 를 주면 모든 조회가 404 입니다.
    반환값은 (CompletedProcess, gh 호출 인자 목록, GITHUB_OUTPUT 내용).
    """
    script = load_check_step_script()
    if now_ts is None:
        now_ts = NOW_TS
    if dow is None:
        dow = kst_dow(now_ts)
    if data_files is None:
        data_files = fresh_data_files(now_ts)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "gh", _GH_STUB)
    _write_stub(bin_dir / "date", _DATE_STUB)

    status_path = tmp_path / "run_status.json"
    status_path.write_text(json.dumps(run_status), encoding="utf-8")
    data_path = tmp_path / "data_files.json"
    data_path.write_text(json.dumps(data_files, ensure_ascii=False), encoding="utf-8")
    call_log = tmp_path / "gh_calls.jsonl"
    call_log.write_text("", encoding="utf-8")
    gh_output = tmp_path / "github_output"
    gh_output.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        REPO=REPO_SLUG,
        GH_TOKEN="fake-token-not-used",
        GITHUB_OUTPUT=str(gh_output),
        GH_CALL_LOG=str(call_log),
        GH_RUN_STATUS=str(status_path),
        GH_DATA_FILES=str(data_path),
        GH_DISPATCH_RC=str(dispatch_rc),
        FAKE_NOW_TS=str(now_ts),
        FAKE_DOW=str(dow),
    )

    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    calls = [
        json.loads(line)
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return proc, calls, gh_output.read_text(encoding="utf-8")


def dispatch_calls(calls):
    """가짜 `gh` 호출 중 재실행 트리거(POST .../dispatches)만 골라냅니다."""
    return [c for c in calls if "-X" in c and "POST" in c]


def expected_dispatch_args(wf_file):
    """이 파일 하나를 재실행할 때 나가야 하는 `gh` 인자 — 글자 그대로."""
    return [
        "api",
        "-X",
        "POST",
        f"repos/{REPO_SLUG}/actions/workflows/{wf_file}/dispatches",
        "-f",
        "ref=main",
    ]


def status_map(ok_files, missing_files, event="schedule", now_ts=None):
    """window 안 성공(ok) / 실행 기록 없음(missing) 으로 가짜 API 응답을 만듭니다.

    `now_ts` 는 "ok" 항목의 실행 시각을 어느 기준으로 2시간 전에 놓을지입니다 —
    `run_check_step(now_ts=...)` 과 **같은 값**을 넘겨야 창 안에 들어옵니다.
    """
    status = {f: [dict(run_entry(2, now_ts=now_ts), event=event)] for f in ok_files}
    status.update({f: [] for f in missing_files})
    return status


def test_missing_targets_are_each_redispatched_exactly_once(tmp_path):
    """
    빠진 대상마다 **정확히 한 번씩**, 정확한 인자로 재실행 호출이 나가야 합니다.
    (여러 번 나가면 같은 크롤링을 중복 발동시키고, 인자가 한 글자만 어긋나도 아무 일도
    안 일어나면서 이슈에는 '재실행 트리거함'이라고 적히게 됩니다.)
    """
    missing = ["scrape.yml", "indicator_kr.yml"]
    ok = [f for f in ALL_TARGETS if f not in missing]
    proc, calls, output = run_check_step(tmp_path, status_map(ok, missing))

    assert proc.returncode == 0, (
        f"스텝이 죽었습니다.\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    posts = dispatch_calls(calls)
    assert posts == [expected_dispatch_args(f) for f in missing], (
        f"재실행 호출이 기대와 다릅니다.\n실제: {posts}\n"
        f"기대: {[expected_dispatch_args(f) for f in missing]}"
    )
    assert "has_failures=true" in output, output
    for f in missing:
        assert f"- {f} (자동 재실행 트리거함)" in output, output


def test_healthy_targets_are_never_redispatched(tmp_path):
    """
    전부 정상이면 재실행 호출이 **단 한 건도** 나가면 안 됩니다 — 여기서 새면 워치독이
    매일 아침 멀쩡한 크롤링 9개를 통째로 다시 돌리게 됩니다.
    """
    proc, calls, output = run_check_step(tmp_path, status_map(ALL_TARGETS, []))

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], f"정상인데 재실행이 나갔습니다: {dispatch_calls(calls)}"
    assert "has_failures=false" in output, output


def test_dispatch_failure_is_reported_as_such(tmp_path):
    """
    재실행 트리거 자체가 실패하면(예: actions 권한 부족·API 오류) 이슈 문구가 '자동
    재실행도 실패' 쪽으로 정확히 갈라져야 합니다 — 실패를 '걸어놨음'으로 위장하면
    사람이 손댈 타이밍을 놓칩니다(§0-1).
    """
    missing = ["scrape.yml"]
    ok = [f for f in ALL_TARGETS if f not in missing]
    proc, calls, output = run_check_step(
        tmp_path, status_map(ok, missing), dispatch_rc=1
    )

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")]
    assert "- scrape.yml (자동 재실행도 실패 — 수동 확인 필요)" in output, output
    assert "자동 재실행 트리거함" not in output, output


def test_yesterdays_auto_dispatch_run_counts_as_ran(tmp_path):
    """
    ⭐ 이 변경의 핵심 — 어제 워치독이 건 자동 재실행이 성공했다면 그 실행의 event 는
    `workflow_dispatch` 입니다. 조회 쿼리에 `event=schedule` 필터가 남아 있으면 그게 안
    보여서 오늘도 '성공 없음'으로 판정되고 **매일 헛되이 재실행을 반복**합니다.
    (가짜 `gh` 가 진짜 API 처럼 event 필터를 적용하므로, 필터가 되살아나는 순간 빨간불.)
    """
    proc, calls, output = run_check_step(
        tmp_path, status_map(ALL_TARGETS, [], event="workflow_dispatch")
    )

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], (
        "workflow_dispatch 로 성공한 실행을 못 보고 재실행을 또 걸었습니다 — 조회 쿼리에\n"
        f"event 필터가 남아 있는지 확인하세요. 나간 호출: {dispatch_calls(calls)}"
    )
    assert "has_failures=false" in output, output


def test_workflow_run_triggered_success_also_counts(tmp_path):
    """
    duel_daily.yml 은 2026-08-26 부터 scrape.yml 완료를 받는 `workflow_run` 이 주 트리거이고
    cron 은 안전망입니다. event 를 안 가리므로 그 성공도 정상으로 세야 합니다.
    """
    status = status_map(ALL_TARGETS, [])
    status["duel_daily.yml"] = [dict(run_entry(2), event="workflow_run")]
    proc, calls, output = run_check_step(tmp_path, status)

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output


def test_weekend_skips_weekday_only_targets_entirely(tmp_path):
    """
    주말(토=6)에는 평일 전용 5개를 검사 자체에서 건너뜁니다 — 조회도, 재실행도 없어야
    합니다(주말에 안 도는 게 정상인데 재실행을 걸면 매주 두 번씩 헛발동).
    """
    proc, calls, output = run_check_step(
        tmp_path, status_map([], ALL_TARGETS), now_ts=TS_SAT_MIDDAY
    )

    assert proc.returncode == 0, proc.stderr
    for f in WEEKDAY_ONLY_TARGETS:
        assert all(f not in " ".join(c) for c in calls), f"{f} 를 주말에 건드렸습니다: {calls}"
    assert dispatch_calls(calls) == [
        expected_dispatch_args(f) for f in DAILY_TARGETS
    ], dispatch_calls(calls)


def test_monday_widened_window_applies_to_redispatch_decision(tmp_path):
    """
    월요일(=1)엔 평일 대상 창이 76시간으로 넓어집니다 — 지난 금요일 성공(72시간 전)이
    있으면 재실행을 걸면 안 됩니다(창이 30으로 좁아지면 월요일마다 5개가 헛발동).
    """
    base = TS_MON_AFTER_CLOSE
    status = {f: [dict(run_entry(72, now_ts=base), event="schedule")]
              for f in WEEKDAY_ONLY_TARGETS}
    status.update({f: [dict(run_entry(2, now_ts=base), event="schedule")]
                   for f in DAILY_TARGETS})
    proc, calls, output = run_check_step(tmp_path, status, now_ts=base)

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output


def test_permissions_grant_actions_write():
    """재실행 API(POST .../dispatches)에는 `actions: write` 권한이 필요합니다."""
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert doc["permissions"].get("actions") == "write", doc["permissions"]


# =====================================================================================
# 5. 장중 안전장치 — 한국 증시 정규장(평일 09:00~15:30 KST)에는 자동 재실행을 걸지 않는다
#    (2026-09-01 오너 실전 발견)
# =====================================================================================
#
# 배경: #184(2026-08-31)로 "빠진 대상을 발견하면 그 자리에서 딱 한 번 재실행"을 넣었는데,
# **그 '자리'가 하필 한국 증시 개장 정각**이었습니다(당시 cron '0 0 * * *' = 09:00 KST).
# 대상 수집기 중 `collector_kospi200.py`(argparse 자체가 없음)와
# `collector_indicator_kr.py`(기록 날짜 = `_now_kst()`)는 **과거 날짜를 지정해 백필하는
# 기능이 아예 없어서**, 장중에 재실행되면 장 시작 직후의 어중간한 가격을 그날의 정상적인
# 종가인 것처럼 저장합니다. 게다가 정작 빠졌던 그 과거 날짜는 백필 수단이 없어 영영
# 못 채웁니다 — 에러 없이 틀린 값이 남는, 가장 발견이 늦는 실패 모양입니다(§0-1).
#
# 고친 방법은 두 겹입니다:
#   (A) 워치독 cron 을 18:00 KST(09:00 UTC)로 이동 → 아래
#       `test_watchdog_cron_runs_outside_market_hours_and_after_every_target` 가 지킵니다.
#   (B) 재실행 직전에 "지금 장중인가"를 한 번 보고, 장중이면 어떤 대상이든 POST 를 걸지
#       않음 → 아래 나머지 검사들이 지킵니다. (A)만으로는 사람이 수동 workflow_dispatch 로
#       장중에 이 워치독을 돌리는 경우를 못 막기 때문에 둘 다 있어야 합니다.
#
# ⚠️ 여기서도 검증하지 않는 것: 공휴일(휴장일). 워크플로우는 요일과 시각만 봅니다 —
#    휴장일 표를 코드에 넣으면 매년 틀리고, 휴장일에 재실행을 한 번 건너뛰는 것은 안전한
#    쪽으로 틀리는 방향이라 그대로 뒀습니다(워크플로우 헤더에 같은 내용이 적혀 있습니다).

MARKET_SKIP_PHRASE = "장중이라 자동 재실행 생략"


def test_dispatch_is_skipped_entirely_during_korean_market_hours(tmp_path):
    """
    ⭐ 이 변경의 핵심 — 장중(화 11:00 KST)에 대상이 '누락'으로 판정돼도 재실행 POST 가
    **단 한 건도** 나가면 안 됩니다. 여기서 새면 백필 불가 수집기가 장중 가격을 그날
    종가인 것처럼 저장합니다.
    """
    missing = ["scrape.yml", "indicator_kr.yml"]
    ok = [f for f in ALL_TARGETS if f not in missing]
    now = TS_TUE_MARKET_MIDDAY
    proc, calls, output = run_check_step(
        tmp_path, status_map(ok, missing, now_ts=now), now_ts=now
    )

    assert proc.returncode == 0, (
        f"스텝이 죽었습니다.\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert dispatch_calls(calls) == [], (
        "장중인데 자동 재실행이 나갔습니다 — 이게 정확히 2026-09-01 에 고친 허점입니다.\n"
        f"나간 호출: {dispatch_calls(calls)}"
    )
    # 누락 자체는 여전히 '실패'로 보고돼야 합니다(재실행을 안 걸었다고 조용해지면 안 됩니다).
    assert "has_failures=true" in output, output
    assert "market_hours=true" in output, output
    for f in missing:
        assert f"- {f} ({MARKET_SKIP_PHRASE}" in output, output
    # 기존 두 케이스 문구가 잘못 섞여 나가면 사람이 "재실행 걸었구나"로 오해합니다.
    assert "자동 재실행 트리거함" not in output, output
    assert "자동 재실행도 실패" not in output, output


def test_dispatch_happens_normally_after_market_close(tmp_path):
    """
    장 마감 후(기본 NOW_TS = 화 18:00 KST — 이 워치독의 실제 cron 발동 시각)에는 기존과
    **완전히 똑같이** 재실행이 나가야 합니다. 장중 안전장치가 평소 동작까지 막아 버리면
    #184 의 self-healing 이 통째로 죽습니다.
    """
    missing = ["scrape.yml"]
    ok = [f for f in ALL_TARGETS if f not in missing]
    proc, calls, output = run_check_step(tmp_path, status_map(ok, missing))

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")], dispatch_calls(calls)
    assert "market_hours=false" in output, output
    assert "- scrape.yml (자동 재실행 트리거함)" in output, output
    assert MARKET_SKIP_PHRASE not in output, output


@pytest.mark.parametrize(
    "now_ts, expect_market_hours, label",
    [
        (TS_TUE_BEFORE_OPEN, False, "화 08:59 — 개장 1분 전"),
        (TS_TUE_MARKET_OPEN, True, "화 09:00 — 개장 정각(포함)"),
        (TS_TUE_MARKET_MIDDAY, True, "화 11:00 — 장 한복판"),
        (TS_TUE_MARKET_CLOSE, True, "화 15:30 — 마감 정각(포함)"),
        (TS_TUE_AFTER_CLOSE, False, "화 15:31 — 마감 1분 후"),
    ],
)
def test_market_hours_boundaries_are_exact(tmp_path, now_ts, expect_market_hours, label):
    """
    경계를 분 단위로 못 박습니다 — 09:00 정각과 15:30 정각은 **장중(포함)**, 그 바깥
    1분은 장중이 아닙니다.
    (15:30 을 포함으로 두는 이유: 그 순간이 종가가 확정되는 때라, 애매하면 재실행을
     거는 쪽이 아니라 건너뛰는 쪽으로 틀리게 둡니다.)
    """
    missing = ["scrape.yml"]
    ok = [f for f in ALL_TARGETS if f not in missing]
    proc, calls, output = run_check_step(
        tmp_path, status_map(ok, missing, now_ts=now_ts), now_ts=now_ts
    )

    assert proc.returncode == 0, f"[{label}] 스텝이 죽었습니다.\n{proc.stderr}"
    expected_flag = "market_hours=true" if expect_market_hours else "market_hours=false"
    assert expected_flag in output, f"[{label}] 기대 {expected_flag}\n{output}"
    if expect_market_hours:
        assert dispatch_calls(calls) == [], f"[{label}] 장중인데 재실행이 나갔습니다: {dispatch_calls(calls)}"
    else:
        assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")], (
            f"[{label}] 장중이 아닌데 재실행이 안 나갔습니다: {dispatch_calls(calls)}"
        )


def test_weekend_midday_is_not_market_hours(tmp_path):
    """
    토요일 11:00 KST — **시각만 보면** 정규장 시간대지만 휴장입니다. 요일 조건이 빠지면
    이 검사가 빨간불이 됩니다.

    평일 전용 5개는 원래 주말이라 검사 자체를 건너뛰므로(기존 로직), 여기서 재실행이
    걸리는 대상은 매일 도는 4개뿐이어야 합니다 — 즉 장중 안전장치가 기존 주말 스킵과
    충돌하지 않는지도 함께 봅니다.
    """
    proc, calls, output = run_check_step(
        tmp_path, status_map([], ALL_TARGETS), now_ts=TS_SAT_MIDDAY
    )

    assert proc.returncode == 0, proc.stderr
    assert "market_hours=false" in output, output
    for f in WEEKDAY_ONLY_TARGETS:
        assert all(f not in " ".join(c) for c in calls), f"{f} 를 주말에 건드렸습니다: {calls}"
    assert dispatch_calls(calls) == [
        expected_dispatch_args(f) for f in DAILY_TARGETS
    ], dispatch_calls(calls)
    assert MARKET_SKIP_PHRASE not in output, output


def test_healthy_targets_stay_quiet_during_market_hours(tmp_path):
    """
    장중이라도 **전부 정상이면** 아무 일도 일어나지 않아야 합니다 — 장중 판정이 정상 판정을
    오염시켜 이슈를 만들어 내면 안 됩니다.
    """
    now = TS_TUE_MARKET_MIDDAY
    proc, calls, output = run_check_step(
        tmp_path, status_map(ALL_TARGETS, [], now_ts=now), now_ts=now
    )

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output
    # 실패가 없어도 market_hours 는 나가야 합니다(뒤 스텝이 빈 값을 만나지 않도록).
    assert "market_hours=true" in output, output


def test_market_hours_output_is_emitted_in_both_outcomes(tmp_path):
    """
    `market_hours` 출력은 실패 유무와 무관하게 **항상** 나가야 합니다. 이슈 스텝이 이 값을
    읽어 본문을 가르므로, 값이 비면 '장중이라 생략'인데도 그 설명이 빠진 이슈가 만들어집니다.
    """
    for label, status in (
        ("healthy", status_map(ALL_TARGETS, [])),
        ("missing", status_map(ALL_TARGETS[1:], [ALL_TARGETS[0]])),
    ):
        # 케이스마다 별도 작업 디렉터리 — 같은 tmp_path 를 두 번 쓰면 스텁 설치가 충돌합니다.
        case_dir = tmp_path / label
        case_dir.mkdir()
        _proc, _calls, output = run_check_step(case_dir, status)
        assert ("market_hours=true" in output) or ("market_hours=false" in output), (
            f"[{label}] market_hours 출력이 없습니다:\n{output}"
        )


# ── 이 워치독 **자신의** cron 이 안전한 시각인가 ──────────────────────────────────────
def _cron_kst_minute_of_day(cron_expr):
    """`분 시 일 월 요일`(UTC) cron 한 줄 → 그 발동 시각의 KST 하루 중 분(0~1439)."""
    minute, hour = cron_expr.split()[0], cron_expr.split()[1]
    return ((int(hour) * 60 + int(minute)) + 9 * 60) % (24 * 60)


def _schedule_crons(workflow_path):
    """워크플로우 파일에서 `on.schedule` 의 cron 문자열 목록을 그대로 읽습니다."""
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음")
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    # ⚠️ YAML 1.1 에서 `on:` 은 불리언 True 로 읽힐 수 있습니다(PyYAML 버전에 따라 다름).
    #    둘 다 봅니다 — 한쪽만 보면 어느 환경에서 조용히 빈손이 됩니다.
    trigger = doc.get("on", doc.get(True))
    if not isinstance(trigger, dict):
        raise _MarkerNotFound(f"{workflow_path.name}: `on:` 블록을 dict 로 읽지 못했습니다: {trigger!r}")
    schedule = trigger.get("schedule") or []
    crons = [entry["cron"] for entry in schedule]
    if not crons:
        raise _MarkerNotFound(f"{workflow_path.name}: schedule cron 을 하나도 못 찾았습니다.")
    return crons


def test_watchdog_cron_runs_outside_market_hours_and_after_every_target():
    """
    이 워치독 자신의 cron 을 **파일에서 읽어** 두 가지를 검산합니다(값을 여기 베껴 적지
    않습니다 — 베껴 적으면 나중에 워크플로우만 바뀌었을 때 이 검사가 조용히 어긋납니다).

      ① 발동 시각이 한국 증시 정규장(평일 09:00~15:30 KST) **밖**일 것.
         → 안이면, 재실행이 걸리는 그 순간이 장중이 됩니다(2026-09-01 이전의 바로 그 상태).
      ② 발동 시각이 **감시 대상 9개의 그날 예정 시각보다 모두 늦을** 것.
         → 그래야 "오늘 안 돈 것"을 다음 날이 아니라 그날 저녁에 잡습니다. 대상 쪽 cron 도
           파일에서 직접 읽으므로, 나중에 누가 대상에 더 늦은 스케줄을 추가하면 이 검사가
           빨간불이 되어 "워치독 시각도 같이 옮겨야 한다"는 사실을 알려 줍니다.
    """
    crons = _schedule_crons(WORKFLOW_PATH)
    assert len(crons) == 1, f"워치독 cron 이 여러 개입니다(설계상 하루 한 번): {crons}"
    watchdog_min = _cron_kst_minute_of_day(crons[0])

    market_open, market_close = 9 * 60, 15 * 60 + 30
    assert not (market_open <= watchdog_min <= market_close), (
        f"워치독 cron {crons[0]!r} (UTC) = KST "
        f"{watchdog_min // 60:02d}:{watchdog_min % 60:02d} 인데, 이건 한국 증시 정규장"
        f"(09:00~15:30 KST) 안입니다.\n"
        "  이 시각에 '누락' 판정이 나면 자동 재실행이 장중에 걸립니다 — 백필이 안 되는\n"
        "  수집기(collector_kospi200.py · collector_indicator_kr.py)가 장중 가격을 그날\n"
        "  종가인 것처럼 저장하게 됩니다. 이것이 2026-09-01 에 고친 허점입니다."
    )

    latest_target, latest_min = None, -1
    for target in ALL_TARGETS:
        for cron_expr in _schedule_crons(WORKFLOW_PATH.parent / target):
            target_min = _cron_kst_minute_of_day(cron_expr)
            if target_min > latest_min:
                latest_target, latest_min = f"{target} ({cron_expr})", target_min

    assert watchdog_min > latest_min, (
        f"워치독이 KST {watchdog_min // 60:02d}:{watchdog_min % 60:02d} 에 도는데, 감시 대상 중\n"
        f"  {latest_target} 은 KST {latest_min // 60:02d}:{latest_min % 60:02d} 에 시작합니다 —\n"
        "  즉 그 대상이 그날 돌기도 전에 검사하게 됩니다. 워치독 시각을 그 뒤로 옮기세요."
    )


# ── 이슈 본문 — 세 번째 케이스('장중이라 생략')가 사람에게 설명되는가 ────────────────
def run_issue_step(tmp_path, failed_text, market_hours, now_ts=None):
    """
    두 번째 스텝(이슈 알림)을 가짜 `gh`/`date` 위에서 통째로 실행합니다(네트워크 없음).

    `gh issue create` 는 스텁이 인자만 기록하고 성공한 척 끝냅니다 — 그래서 **실제로 이슈
    본문에 실리는 문자열 전문**을 그대로 검사할 수 있습니다(사본 검사가 아닙니다, §0-3-10).
    디스코드 웹훅은 `DISCORD_WEBHOOK_URL` 을 비워 두어 그 블록이 통째로 건너뛰어집니다.
    반환값은 (CompletedProcess, gh 호출 인자 목록).
    """
    script = load_issue_step_script()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "gh", _GH_STUB)
    _write_stub(bin_dir / "date", _DATE_STUB)
    call_log = tmp_path / "gh_calls.jsonl"
    call_log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        REPO=REPO_SLUG,
        GH_TOKEN="fake-token-not-used",
        GH_CALL_LOG=str(call_log),
        GH_DISPATCH_RC="0",
        FAILED=failed_text,
        MARKET_HOURS=market_hours,
        DISCORD_WEBHOOK_URL="",
        FAKE_NOW_TS=str(NOW_TS if now_ts is None else now_ts),
        FAKE_DOW=str(kst_dow(NOW_TS if now_ts is None else now_ts)),
    )
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    calls = [
        json.loads(line)
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return proc, calls


def issue_body(calls):
    """가짜 `gh` 호출 중 `issue create` 의 `--body` 값을 꺼냅니다."""
    for call in calls:
        if call[:2] == ["issue", "create"] and "--body" in call:
            return call[call.index("--body") + 1]
    raise AssertionError(f"`gh issue create --body ...` 호출을 못 찾았습니다: {calls}")


def test_issue_body_explains_the_market_hours_skip(tmp_path):
    """
    장중이라 재실행을 생략했으면, 이슈를 읽는 사람이 **왜 아무것도 안 걸렸는지**와
    **다음에 무슨 일이 일어나는지**를 본문에서 알 수 있어야 합니다. 이유 없이 조용한
    이슈는 "워치독이 고장났나?"로 읽힙니다(§0-1).
    """
    failed = f"- scrape.yml ({MARKET_SKIP_PHRASE} — 장 마감 후 이 워치독이 다시 확인합니다)\n"
    proc, calls = run_issue_step(tmp_path, failed, market_hours="true",
                                 now_ts=TS_TUE_MARKET_MIDDAY)

    # 이 스텝은 마지막에 일부러 `exit 1` 합니다(Actions 탭에 빨간 X 로 남기려고).
    assert proc.returncode == 1, f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    body = issue_body(calls)
    assert MARKET_SKIP_PHRASE in body, body            # 항목별 표시가 본문에 실렸는가
    assert "장중" in body and "09:00~15:30" in body, body  # 무엇이 장중인지 정의돼 있는가
    assert "18:00" in body, body                       # 다음에 언제 다시 보는지
    assert "workflow_dispatch" in body, body           # 급할 때의 우회로


def test_issue_body_has_no_market_note_after_market_close(tmp_path):
    """
    장 마감 후(정상 경로)에는 그 설명이 **붙지 않아야** 합니다 — 매번 붙으면 실제로
    생략된 날과 구분이 안 됩니다.
    """
    failed = "- scrape.yml (자동 재실행 트리거함)\n"
    proc, calls = run_issue_step(tmp_path, failed, market_hours="false")

    assert proc.returncode == 1, proc.stderr
    body = issue_body(calls)
    assert "자동 재실행 트리거함" in body, body
    assert MARKET_SKIP_PHRASE not in body, body
    assert "09:00~15:30" not in body, body

# =====================================================================================
# 6. "성공으로 끝남" ≠ "데이터를 만듦" — 데이터 파일 타임스탬프까지 본다 (2026-09-05 #196)
# =====================================================================================
#
# 배경: scrape.yml / indicator_kr.yml 은 2026-09-04 부터 `--skip-if-not-ready` 로 돕니다.
# 09-04(금) 새벽 07:04 KST 에 GitHub cron 이 늦게 발동해 저장한 "오늘자 SUCCESS"(내용은
# 목요일 종가) 때문에 그날 오후 정식 실행이 전부 건너뛰어졌고(#195), 그 건너뛴 실행은
# conclusion=success 로 남았습니다. 이 워치독은 conclusion 만 봤으니 "✅"를 찍었고, 새
# 데이터가 하루 종일 하나도 안 만들어졌는데 아무 경고도 없었습니다. 아래 검사들은 그
# 사고 원본 그대로의 타임스탬프로 워치독이 이제 ❌ 를 찍는지 못 박습니다.
#
# 판정 규칙(워크플로우 헤더 🔴 2026-09-05 문단): 타임스탬프 날짜가 "기대 거래일"(평일 장마감
# 이후면 오늘, 아니면 가장 최근 평일)이고 시각이 15:30 KST 이후(정각 포함 — 수집기의
# kr_snapshot_time_is_after_close() 와 같은 규칙)여야 "데이터를 만들었다"입니다.

STALE_PHRASE = "실행은 성공했지만 데이터 미갱신"

# 사고 당일 — 2026-09-04(금) 18:00 KST, 워치독 정규 발동 시각.
TS_FRI_INCIDENT_CHECK = kst_ts(2026, 9, 4, 18, 0)
INCIDENT_STAMP = "2026-09-04 07:04"   # kospi200_pegy_latest.json metadata.last_updated_at 실측값


def _all_ok_status(now_ts):
    return status_map(ALL_TARGETS, [], now_ts=now_ts)


def _data_files_with(now_ts, overrides):
    """정상 세트에서 일부 대상만 다른 스탬프/원문으로 바꿉니다. overrides: {wf_file: 스탬프 또는 None(404)}"""
    files = fresh_data_files(now_ts)
    for wf, stamp in overrides.items():
        path = DATA_TARGETS[wf][0]
        if stamp is None:
            files.pop(path, None)
        else:
            files[path] = data_file_text(wf, stamp)
    return files


def test_incident_success_run_with_pre_close_snapshot_is_flagged_and_redispatched(tmp_path):
    """
    ⭐ 이 변경의 핵심 — 사고 원본 재현. 금 18:00 KST, scrape.yml 은 2시간 전 success 로
    끝났지만 데이터 파일은 "2026-09-04 07:04"(오늘 날짜, 장마감 이전). 예전 워치독은 ✅.
    이제는 ❌ + 자동 재실행(18:00 은 장마감 후라 안전) + 이슈 항목에 사유가 실려야 합니다.
    """
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": INCIDENT_STAMP}),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")], dispatch_calls(calls)
    assert "has_failures=true" in output, output
    assert f"- scrape.yml ({STALE_PHRASE}: 데이터 기준 2026-09-04 07:04 KST" in output, output
    assert "장마감 15:30 이전" in output, output
    assert "자동 재실행 트리거함" in output, output
    # 로그에도 conclusion=success 였음을 명시(사람이 "실행이 없었나?"로 읽지 않도록)
    assert "실행은 성공(conclusion=success)으로 끝났지만" in proc.stdout, proc.stdout


def test_success_run_with_yesterdays_snapshot_is_flagged(tmp_path):
    """날짜 자체가 어제(목 16:05)면 시각이 장마감 후라도 ❌ — 기대 거래일은 오늘(금)입니다."""
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"indicator_kr.yml": "2026-09-03 16:05"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("indicator_kr.yml")], dispatch_calls(calls)
    assert f"- indicator_kr.yml ({STALE_PHRASE}: 데이터 기준 2026-09-03 16:05 KST" in output, output
    assert "기대 거래일 2026-09-04" in output, output


@pytest.mark.parametrize("hhmm, expect_flag, label", [
    ((15, 30), False, "15:30 정각 — 장마감 '이후'로 침(수집기 규칙과 동일)"),
    ((15, 29), True,  "15:29 — 1분 전이면 장중 값"),
    ((21, 40), False, "21:40 — 사고 당일 보조지표 실제 생성 시각(정상)"),
    ((0, 0),   True,  "00:00 — 자정 직후 값"),
])
def test_close_boundary_is_exact(tmp_path, hhmm, expect_flag, label):
    now = TS_FRI_INCIDENT_CHECK
    stamp = f"2026-09-04 {hhmm[0]:02d}:{hhmm[1]:02d}"
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": stamp, "indicator_kr.yml": stamp}),
    )
    assert proc.returncode == 0, proc.stderr
    flagged = dispatch_calls(calls)
    if expect_flag:
        assert flagged == [expected_dispatch_args("scrape.yml"),
                           expected_dispatch_args("indicator_kr.yml")], (label, flagged)
        assert "has_failures=true" in output, (label, output)
    else:
        assert flagged == [], (label, flagged)
        assert "has_failures=false" in output, (label, output)


def test_fresh_snapshots_pass_with_no_dispatch(tmp_path):
    """정상(오늘 16:05 / 17:10) — ❌ 도 재실행도 없고, 로그에 갱신 확인 문구가 남습니다."""
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": "2026-09-04 16:05",
                                          "indicator_kr.yml": "2026-09-04 17:10"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output
    assert "data/kospi200_pegy_latest.json 갱신 확인(데이터 기준 2026-09-04 16:05 KST" in proc.stdout, proc.stdout
    assert "data/indicator_kr_latest.json 갱신 확인(데이터 기준 2026-09-04 17:10 KST" in proc.stdout, proc.stdout


def test_unreachable_data_file_counts_as_not_updated(tmp_path):
    """파일을 못 받으면(404·권한·네트워크) "갱신 확인 못 함 = 미갱신"으로 안전한 쪽(❌)입니다."""
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": None}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")], dispatch_calls(calls)
    assert f"- scrape.yml ({STALE_PHRASE}: 데이터 파일의 타임스탬프(metadata.last_updated_at)를 읽지 못함" in output, output


def test_malformed_data_file_counts_as_not_updated(tmp_path):
    """JSON 이 아니거나(HTML 에러 페이지 등) 키가 없으면 역시 ❌ — 예외로 워치독이 죽지 않습니다."""
    now = TS_FRI_INCIDENT_CHECK
    files = fresh_data_files(now)
    files[DATA_TARGETS["scrape.yml"][0]] = "<html>Sign in</html>"
    files[DATA_TARGETS["indicator_kr.yml"][0]] = json.dumps({"status": "SUCCESS"})   # generated_at 없음
    proc, calls, output = run_check_step(tmp_path, _all_ok_status(now), now_ts=now, data_files=files)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml"),
                                     expected_dispatch_args("indicator_kr.yml")], dispatch_calls(calls)
    assert "읽지 못함" in output, output


def test_only_the_data_targets_fetch_files_and_only_when_a_run_succeeded(tmp_path):
    """
    데이터 파일 조회는 (a) 3·4번째 필드가 있는 대상(#196 의 2개 + #199 의 4개)에 대해서만,
    (b) 그것도 성공 실행이 있을 때만 나갑니다 — 실행 기록이 없으면 어차피 재실행 대상이라
    파일을 받을 이유가 없고, 나머지 4개(CONCLUSION_ONLY_TARGETS)는 확인할 결과물 파일이
    없거나 그 파일이 결과물이 아니라서 종전대로 conclusion 만 봅니다(헤더 🔴 #199 문단).
    """
    now = TS_FRI_INCIDENT_CHECK
    # (a) 전부 성공 → 데이터 대상 파일만 각각 정확히 한 번
    (tmp_path / "a").mkdir()
    proc, calls, _ = run_check_step(tmp_path / "a", _all_ok_status(now), now_ts=now)
    assert proc.returncode == 0, proc.stderr
    assert sorted(contents_calls(calls)) == sorted(p for p, _k, _r in DATA_TARGETS.values()), contents_calls(calls)
    assert len(contents_calls(calls)) == len(DATA_TARGETS) == 6, contents_calls(calls)
    # (b) scrape.yml 실행 없음 → 그 파일은 조회하지 않고 바로 재실행
    (tmp_path / "b").mkdir()
    status = status_map([f for f in ALL_TARGETS if f != "scrape.yml"], ["scrape.yml"], now_ts=now)
    proc, calls, output = run_check_step(tmp_path / "b", status, now_ts=now)
    assert proc.returncode == 0, proc.stderr
    assert sorted(contents_calls(calls)) == sorted(
        p for wf, (p, _k, _r) in DATA_TARGETS.items() if wf != "scrape.yml"), contents_calls(calls)
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape.yml")]
    assert "- scrape.yml (자동 재실행 트리거함)" in output, output   # "실행 없음" 문구는 예전 그대로
    assert STALE_PHRASE not in output, output


def test_before_close_check_expects_the_previous_weekday(tmp_path):
    """
    사람이 장 마감 전에 수동으로 돌리면(화 11:00 / 월 08:00) 오늘 데이터를 기대할 수 없으니
    "가장 최근 평일"(월 / 지난 금) 데이터가 장마감 후 값이면 정상입니다 — 아니면 매일 아침
    수동 실행마다 오탐이 납니다.
    """
    # 화 11:00 → 월(2026-08-31) 16:05 면 정상 (장중이라 재실행은 어차피 안 걸림)
    now = TS_TUE_MARKET_MIDDAY
    assert expected_trade_date(now) == "2026-08-31"
    (tmp_path / "tue").mkdir()
    proc, calls, output = run_check_step(
        tmp_path / "tue", _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": "2026-08-31 16:05",
                                          "indicator_kr.yml": "2026-08-31 17:10"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert "has_failures=false" in output, output

    # 월 08:00 → 지난 금(2026-09-04) 16:05 면 정상, 목(09-03)이면 ❌
    now = kst_ts(2026, 9, 7, 8, 0)
    assert expected_trade_date(now) == "2026-09-04"
    (tmp_path / "mon").mkdir()
    proc, calls, output = run_check_step(
        tmp_path / "mon", _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": "2026-09-04 16:05",
                                          "indicator_kr.yml": "2026-09-03 17:10"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("indicator_kr.yml")], dispatch_calls(calls)
    assert "기대 거래일 2026-09-04" in output, output


def test_stale_data_during_market_hours_is_reported_but_not_redispatched(tmp_path):
    """장중(화 11:00)에 미갱신이 잡혀도 재실행은 종전 규칙대로 생략 — 문구에 두 사유가 함께 실립니다."""
    now = TS_TUE_MARKET_MIDDAY
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape.yml": "2026-08-31 07:04"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert f"- scrape.yml ({STALE_PHRASE}: 데이터 기준 2026-08-31 07:04 KST" in output, output
    assert MARKET_SKIP_PHRASE in output, output


def test_market_close_constant_matches_utils_constants():
    """
    워크플로우의 `KST_MARKET_CLOSE_MIN` 은 수집기가 쓰는 utils/constants.py 의
    KR_MARKET_CLOSE_HOUR/MINUTE(#195 신설)와 **같은 값**이어야 합니다 — 워크플로우는
    체크아웃 없이 돌아 그 모듈을 import 할 수 없으므로 값을 따로 들고 있고, 여기서
    두 파일을 직접 읽어 대조합니다(한쪽만 바뀌면 빨간불).
    """
    import re
    from utils.constants import KR_MARKET_CLOSE_HOUR, KR_MARKET_CLOSE_MINUTE
    script = load_check_step_script()
    m = re.search(r"^\s*KST_MARKET_CLOSE_MIN=(\d+)", script, re.M)
    assert m, "워크플로우에서 KST_MARKET_CLOSE_MIN=<숫자> 를 못 찾았습니다"
    assert int(m.group(1)) == KR_MARKET_CLOSE_HOUR * 60 + KR_MARKET_CLOSE_MINUTE == KR_CLOSE_MIN, (
        int(m.group(1)), KR_MARKET_CLOSE_HOUR, KR_MARKET_CLOSE_MINUTE)
    # 데이터 갱신 판정이 그 값을 실제로 인자로 받는지(다른 상수를 몰래 쓰지 않는지)
    assert '"$KST_MARKET_CLOSE_MIN" "$US_COLLECT_READY_MIN")' in script, \
        "데이터 갱신 판정 스크립트가 KST_MARKET_CLOSE_MIN / US_COLLECT_READY_MIN 을 인자로 받지 않습니다"


def test_issue_body_explains_the_stale_data_case(tmp_path):
    """이슈 본문이 "성공인데 왜 이슈가 떴지?"에 답해야 합니다 — 미갱신 항목 문구와 그 이유 설명."""
    failed = (f"- scrape.yml ({STALE_PHRASE}: 데이터 기준 2026-09-04 07:04 KST — 날짜는 오늘이지만 "
              "장마감 15:30 이전 시각(장 시작 전·장중 값); 자동 재실행 트리거함)\n")
    proc, calls = run_issue_step(tmp_path, failed, market_hours="false", now_ts=TS_FRI_INCIDENT_CHECK)
    assert proc.returncode == 1, proc.stderr
    body = issue_body(calls)
    assert STALE_PHRASE in body and "2026-09-04 07:04" in body, body
    assert "--skip-if-not-ready" in body, body          # 왜 성공인데도 이슈인지
    assert "타임스탬프" in body, body                    # 무엇을 추가로 봤는지
    assert MARKET_SKIP_PHRASE not in body, body


# =====================================================================================
# 7. 데이터 갱신 확인을 나머지 대상으로 확장 (2026-09-05 #199)
# =====================================================================================
#
# §6 의 kr 규칙(코스피·보조지표)에 더해, "결과물 파일 + 타임스탬프 + 기준 시각의 근거" 가
# 저장소 코드에서 확인되는 4개 대상을 추가했습니다(워크플로우 헤더 🔴 #199 문단):
#   · us  — scrape_us.yml / scrape_report_snapshots.yml: 두 수집기가 공유하는
#           collector_us_stocks.py::resolve_collection_session_et() 규칙 그대로. 타임스탬프
#           순간(ET)의 "담기는 거래일"이 지금(ET)의 그것과 같아야 합니다(마감 16:00 ET + 30분).
#   · daily@HH:MM — 배당 감시 2종: 장마감 개념이 없으니 그 워크플로우 cron(KST) 기준으로
#           "기대 실행일"(지났으면 오늘, 아니면 어제)의 날짜면 됩니다(시각 조건 없음).
# 아래 검사들은 §6 과 대칭입니다 — 정상 / 미갱신(어제·전 거래일) / 경계(정각·1분 전) / 키 없음 /
# 404 / 장 마감 전 수동 실행 / 상수 대조 / 조회 범위. 여기에 us 특유의 "KST 낮 재실행은 정상"
# (타임스탬프 날짜가 다음 ET 날짜여도 담긴 거래일이 같음)과 서머타임·월요일 케이스를 더했습니다.

VERDICT_START_MARKER = 'DATA_VERDICT=$(printf \'%s\' "$DATA_JSON" | python3 -c \''
VERDICT_END_MARKER = '\' "$NOW_TS" "$STAMP_KEY" "${RULE:-kr}" "$KST_MARKET_CLOSE_MIN" "$US_COLLECT_READY_MIN")'


def extract_verdict_source():
    """워크플로우 안의 데이터 갱신 판정 파이썬 소스를 그대로 뽑습니다(사본 아님 — §0-3-10)."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    start = text.find(VERDICT_START_MARKER)
    if start < 0:
        raise _MarkerNotFound(f"데이터 갱신 판정 스크립트 시작 마커를 못 찾았습니다: {VERDICT_START_MARKER!r}")
    start += len(VERDICT_START_MARKER)
    end = text.find(VERDICT_END_MARKER, start)
    if end < 0:
        raise _MarkerNotFound(f"데이터 갱신 판정 스크립트 끝 마커를 못 찾았습니다: {VERDICT_END_MARKER!r}")
    return textwrap.dedent(text[start:end])


def run_verdict(payload_text, now_ts, key, rule, close_min=KR_CLOSE_MIN, us_ready_min=US_READY_MIN):
    """워크플로우가 부르는 것과 같은 방식으로 판정 스크립트만 실행 → (yes|no, 사유)."""
    proc = subprocess.run(
        [sys.executable, "-c", extract_verdict_source(), str(now_ts), key, rule,
         str(close_min), str(us_ready_min)],
        input=payload_text, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 2 and lines[0] in ("yes", "no"), proc.stdout
    return lines[0], lines[1]


# 사고 당일(금 2026-09-04) 18:00 KST = 05:00 EDT — 미국 쪽 기대 거래일은 목요일(09-03).
US_EXPECTED_ON_FRI = "2026-09-03"
US_STALE_PHRASE_TAIL = "의 데이터가 아님"


def test_us_targets_are_declared_with_the_us_rule():
    """TARGETS 의 us 대상 2개가 헤더 🔴 #199 문단과 같은 파일·키·규칙으로 적혀 있어야 합니다."""
    script = load_check_step_script()
    assert "scrape_us.yml|weekdays|data/us_stocks_latest.json|metadata.last_updated_at_et|us" in script
    assert ("scrape_report_snapshots.yml|weekdays|data/us_index_history.json|metadata.collected_at_et|us"
            in script)
    assert ("watch_dividend_disclosures.yml|daily|data/cache/dividend_kr_2026_watch_state.json"
            "|updated_at_kst|daily@05:00") in script
    assert ("watch_dividend_payment_events.yml|daily|data/cache/dividend_kr_2026_payment_state.json"
            "|updated_at_kst|daily@05:30") in script
    import re
    block = re.search(r'TARGETS="(.*?)"', script, re.S)
    assert block, "TARGETS=\"...\" 블록을 못 찾았습니다"
    target_lines = [l.strip() for l in block.group(1).splitlines() if l.strip()]
    assert [l.split("|")[0] for l in target_lines] == ALL_TARGETS, target_lines
    for wf in CONCLUSION_ONLY_TARGETS:
        line = next(l for l in target_lines if l.startswith(wf + "|"))
        assert line.count("|") == 1, f"{wf} 는 conclusion 만 보는 대상이어야 합니다(헤더 #199): {line}"
    for wf, (path, key, rule) in DATA_TARGETS.items():
        kind = "weekdays" if wf in WEEKDAY_ONLY_TARGETS else "daily"
        assert f"{wf}|{kind}|{path}|{key}|{rule}" in target_lines, (wf, target_lines)
    assert sorted(list(DATA_TARGETS) + CONCLUSION_ONLY_TARGETS) == sorted(ALL_TARGETS)


def test_us_fresh_snapshot_after_ready_time_passes(tmp_path):
    """정상 — 목 16:35 ET(첫 cron 20:35 UTC) 수집분을 금 18:00 KST 에 보면 ✅ + 로그 문구."""
    now = TS_FRI_INCIDENT_CHECK
    assert expected_us_session(now) == US_EXPECTED_ON_FRI
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-09-03 16:35",
                                          "scrape_report_snapshots.yml": "2026-09-03 19:20"}),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output
    assert ("data/us_stocks_latest.json 갱신 확인(데이터 기준 2026-09-03 16:35 ET — 거래일 2026-09-03 "
            "마감+30분(16:30 ET) 이후)") in proc.stdout, proc.stdout
    assert "data/us_index_history.json 갱신 확인(데이터 기준 2026-09-03 19:20 ET" in proc.stdout, proc.stdout


def test_us_snapshot_of_previous_session_is_flagged_and_redispatched(tmp_path):
    """
    ⭐ us 핵심 — 수요일 19:20 ET 수집분(수 거래일)이 금 18:00 KST 에도 그대로면, 목요일 정식
    수집(금 05:35 KST)이 `--skip-if-not-ready` 로 조용히 exit 0 했거나 아예 안 돈 것입니다.
    ❌ + 자동 재실행(18:00 KST = 05:00 ET, 마감 후라 안전) + 이슈 항목에 사유.
    """
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-09-02 19:20"}),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape_us.yml")], dispatch_calls(calls)
    assert "has_failures=true" in output, output
    assert f"- scrape_us.yml ({STALE_PHRASE}: 데이터 기준 2026-09-02 19:20 ET" in output, output
    assert "담는 거래일은 2026-09-02" in output and f"기대 거래일 {US_EXPECTED_ON_FRI}{US_STALE_PHRASE_TAIL}" in output, output
    assert "자동 재실행 트리거함" in output, output
    assert "실행은 성공(conclusion=success)으로 끝났지만" in proc.stdout, proc.stdout


def test_us_benchmark_file_stale_despite_green_run_is_flagged(tmp_path):
    """
    scrape_report_snapshots.yml 의 벤치마크 스텝은 continue-on-error 라 죽어도 conclusion=success —
    그래서 파일까지 봐야 하는 대상입니다. 수요일 값 그대로면 ❌ + 재실행(Supabase 적재는 upsert 라 안전).
    """
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_report_snapshots.yml": "2026-09-02T21:04:52.665805-04:00"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape_report_snapshots.yml")], dispatch_calls(calls)
    assert f"- scrape_report_snapshots.yml ({STALE_PHRASE}: 데이터 기준 2026-09-02 21:04 ET" in output, output


@pytest.mark.parametrize("hhmm, expect_flag, label", [
    ((16, 30), False, "16:30 ET 정각 — 마감+30분 '이후'로 침(resolve_collection_session_et 의 >= 와 동일)"),
    ((16, 29), True,  "16:29 ET — 1분 전이면 아직 전 거래일(수) 세션"),
    ((16, 0),  True,  "16:00 ET — 마감 정각이지만 +30분 게이트 전"),
    ((23, 59), False, "23:59 ET — 같은 날 늦은 수집(2차 cron 이후 재시도)도 정상"),
])
def test_us_ready_boundary_is_exact(tmp_path, hhmm, expect_flag, label):
    now = TS_FRI_INCIDENT_CHECK
    stamp = f"{US_EXPECTED_ON_FRI} {hhmm[0]:02d}:{hhmm[1]:02d}"
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": stamp, "scrape_report_snapshots.yml": stamp}),
    )
    assert proc.returncode == 0, proc.stderr
    flagged = dispatch_calls(calls)
    if expect_flag:
        assert flagged == [expected_dispatch_args("scrape_us.yml"),
                           expected_dispatch_args("scrape_report_snapshots.yml")], (label, flagged)
        assert "has_failures=true" in output, (label, output)
        assert "담는 거래일은 2026-09-02" in output, (label, output)
    else:
        assert flagged == [], (label, flagged)
        assert "has_failures=false" in output, (label, output)


def test_us_rerun_during_korean_daytime_is_not_a_false_alarm(tmp_path):
    """
    빠진 목요일치를 사람이 금요일 KST 낮(= 금 01:00 ET)에 다시 돌리면 타임스탬프 날짜는 금요일(마감 전
    시각)이지만 담긴 종가는 목요일 것입니다 — 수집기 자신이 그 순간의 거래일을 목요일로 계산하므로
    워치독도 정상(✅)으로 봐야 합니다. "날짜 == 오늘" 식 비교였다면 여기서 매번 오탐이 납니다.
    """
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-09-04 01:00"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output
    assert "데이터 기준 2026-09-04 01:00 ET — 거래일 2026-09-03 마감+30분(16:30 ET) 이후" in proc.stdout, proc.stdout


def test_us_monday_check_expects_last_friday_session(tmp_path):
    """월 18:00 KST(= 월 05:00 ET) 검사의 기대 거래일은 지난 금요일 — 금 16:35 ET 수집분이면 ✅, 목요일 것이면 ❌."""
    now = TS_MON_AFTER_CLOSE
    assert expected_us_session(now) == "2026-09-04"
    (tmp_path / "ok").mkdir()
    proc, calls, output = run_check_step(
        tmp_path / "ok", _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-09-04 16:35",
                                          "scrape_report_snapshots.yml": "2026-09-04 19:20"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert "has_failures=false" in output, output
    (tmp_path / "stale").mkdir()
    proc, calls, output = run_check_step(
        tmp_path / "stale", _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-09-03 16:35"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape_us.yml")], dispatch_calls(calls)
    assert "기대 거래일 2026-09-04" in output, output


def test_us_rule_follows_daylight_saving_time():
    """
    ET 는 서머타임이 있어 KST 와의 차이가 13시간(EDT)/14시간(EST)으로 바뀝니다. 워치독의 18:00 KST 는
    EDT 로 05:00, EST 로 04:00 — 둘 다 마감 전이라 기대 거래일은 전 평일이어야 하고, 판정이 ET
    벽시계로 이뤄져야 합니다(KST 로 계산하면 표준시 기간에 1시간 어긋납니다).
    """
    import datetime
    et = _et()
    # 2026-01-15(목, EST) 18:00 KST = 04:00 EST → 기대 거래일 수(01-14)
    jan = kst_ts(2026, 1, 15, 18, 0)
    assert datetime.datetime.fromtimestamp(jan, et).strftime("%H:%M %Z") == "04:00 EST"
    assert run_verdict(data_file_text("scrape_us.yml", "2026-01-14 16:35"), jan,
                       "metadata.last_updated_at_et", "us")[0] == "yes"
    assert run_verdict(data_file_text("scrape_us.yml", "2026-01-14 16:29"), jan,
                       "metadata.last_updated_at_et", "us")[0] == "no"
    # 2026-07-16(목, EDT) 18:00 KST = 05:00 EDT → 기대 거래일 수(07-15)
    jul = kst_ts(2026, 7, 16, 18, 0)
    assert datetime.datetime.fromtimestamp(jul, et).strftime("%H:%M %Z") == "05:00 EDT"
    assert run_verdict(data_file_text("scrape_us.yml", "2026-07-15 16:35"), jul,
                       "metadata.last_updated_at_et", "us")[0] == "yes"
    assert run_verdict(data_file_text("scrape_us.yml", "2026-07-16 04:59"), jul,
                       "metadata.last_updated_at_et", "us")[0] == "yes"   # KST 낮 재실행 = 수 세션
    # 표준시 기간에 KST-14h 를 KST-13h 로 잘못 계산하면 목 16:30 ET 가 목 세션으로 잡히는 순간이 생깁니다.
    # 월 18:00 KST 검사 → 지난 금(01-09) 세션. 토요일 새벽(ET) 수집분(= 금 세션)도 정상.
    mon = kst_ts(2026, 1, 12, 18, 0)
    assert run_verdict(data_file_text("scrape_us.yml", "2026-01-10 02:00"), mon,
                       "metadata.last_updated_at_et", "us")[0] == "yes"


def test_us_unreachable_or_malformed_file_counts_as_not_updated(tmp_path):
    """404 / HTML / 키 없음 → "갱신 확인 못 함 = 미갱신"(안전한 쪽) — 예외로 워치독이 죽지 않습니다."""
    now = TS_FRI_INCIDENT_CHECK
    files = _data_files_with(now, {"scrape_us.yml": None})                      # 404
    files[DATA_TARGETS["scrape_report_snapshots.yml"][0]] = json.dumps({"metadata": {"fetched_any": True}})   # 키 없음
    proc, calls, output = run_check_step(tmp_path, _all_ok_status(now), now_ts=now, data_files=files)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("scrape_us.yml"),
                                     expected_dispatch_args("scrape_report_snapshots.yml")], dispatch_calls(calls)
    assert f"- scrape_us.yml ({STALE_PHRASE}: 데이터 파일의 타임스탬프(metadata.last_updated_at_et)를 읽지 못함" in output, output
    assert f"- scrape_report_snapshots.yml ({STALE_PHRASE}: 데이터 파일의 타임스탬프(metadata.collected_at_et)를 읽지 못함" in output, output


def test_us_constants_match_utils_constants_us():
    """
    워크플로우의 US_MARKET_CLOSE_MIN / US_COLLECT_AFTER_CLOSE_MINUTES 는 수집기가 쓰는
    utils/constants_us.py 의 US_MARKET_CLOSE_HOUR/MINUTE / US_COLLECT_AFTER_CLOSE_MINUTES 와
    **같은 값**이어야 합니다(체크아웃 없이 돌아 import 할 수 없어 값을 따로 들고 있음 — 한쪽만
    바뀌면 빨간불). 판정 스크립트가 그 합(US_COLLECT_READY_MIN)을 실제로 인자로 받는지도 봅니다.
    """
    import re
    from utils.constants_us import (US_MARKET_CLOSE_HOUR, US_MARKET_CLOSE_MINUTE,
                                    US_COLLECT_AFTER_CLOSE_MINUTES, US_MARKET_TIMEZONE)
    script = load_check_step_script()
    close = re.search(r"^\s*US_MARKET_CLOSE_MIN=(\d+)", script, re.M)
    after = re.search(r"^\s*US_COLLECT_AFTER_CLOSE_MINUTES=(\d+)", script, re.M)
    assert close and after, "워크플로우에서 US_MARKET_CLOSE_MIN / US_COLLECT_AFTER_CLOSE_MINUTES 를 못 찾았습니다"
    assert int(close.group(1)) == US_MARKET_CLOSE_HOUR * 60 + US_MARKET_CLOSE_MINUTE, (close.group(1), US_MARKET_CLOSE_HOUR, US_MARKET_CLOSE_MINUTE)
    assert int(after.group(1)) == US_COLLECT_AFTER_CLOSE_MINUTES, (after.group(1), US_COLLECT_AFTER_CLOSE_MINUTES)
    assert int(close.group(1)) + int(after.group(1)) == US_READY_MIN
    assert "US_COLLECT_READY_MIN=$(( US_MARKET_CLOSE_MIN + US_COLLECT_AFTER_CLOSE_MINUTES ))" in script
    assert '"$US_COLLECT_READY_MIN")' in script
    # 시간대 이름도 상수 파일과 같아야 합니다(서머타임 처리를 zoneinfo 에 맡기는 근거).
    assert US_MARKET_TIMEZONE == "America/New_York"
    assert 'zoneinfo.ZoneInfo("America/New_York")' in script


def test_us_rule_mirrors_collector_session_resolution():
    """
    워크플로우의 us 규칙은 collector_us_stocks.py::resolve_collection_session_et() 의 사본이 아니라
    같은 규칙이어야 합니다 — 실제 수집기 함수에 여러 순간을 넣어 얻은 거래일과, 워치독이 그 순간을
    "지금"으로 받았을 때 정상으로 치는 타임스탬프의 거래일이 일치하는지 대조합니다.
    """
    import datetime
    from collector_us_stocks import resolve_collection_session_et
    et = _et()
    moments = [
        datetime.datetime(2026, 9, 4, 5, 0, tzinfo=et),     # 금 05:00 EDT (워치독 정규 시각)
        datetime.datetime(2026, 9, 4, 16, 29, tzinfo=et),   # 금 16:29 — 게이트 1분 전
        datetime.datetime(2026, 9, 4, 16, 30, tzinfo=et),   # 금 16:30 — 게이트 정각
        datetime.datetime(2026, 9, 6, 12, 0, tzinfo=et),    # 일요일 낮
        datetime.datetime(2026, 1, 12, 4, 0, tzinfo=et),    # 월 04:00 EST
    ]
    for moment in moments:
        collector_session = resolve_collection_session_et(now_et=moment)["session_date"]
        assert us_session_date(moment) == collector_session, (moment, collector_session)
        now_ts = int(moment.timestamp())
        # 수집기가 그 거래일로 계산하는 "그 거래일 16:30 ET" 시각의 스냅샷 → 정상
        ready_stamp = f"{collector_session} {US_READY_MIN // 60:02d}:{US_READY_MIN % 60:02d}"
        assert run_verdict(data_file_text("scrape_us.yml", ready_stamp), now_ts,
                           "metadata.last_updated_at_et", "us")[0] == "yes", (moment, ready_stamp)
        # 그 거래일 16:29 ET 스냅샷 → 전 거래일 것 → 미갱신
        pre_stamp = f"{collector_session} 16:29"
        assert run_verdict(data_file_text("scrape_us.yml", pre_stamp), now_ts,
                           "metadata.last_updated_at_et", "us")[0] == "no", (moment, pre_stamp)


# ── daily@HH:MM (배당 감시 2종) ──────────────────────────────────────────────────────

def test_daily_fresh_state_from_today_passes(tmp_path):
    """정상 — 오늘 07:13 KST(cron 05:00 에서 GitHub 지연분) 상태 파일이면 ✅ + 로그 문구."""
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"watch_dividend_disclosures.yml": "2026-09-04 07:13",
                                          "watch_dividend_payment_events.yml": "2026-09-04 07:30"}),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output
    assert ("data/cache/dividend_kr_2026_watch_state.json 갱신 확인(데이터 기준 2026-09-04 07:13 KST — "
            "기대 실행일 2026-09-04(예약 05:00 KST)의 결과)") in proc.stdout, proc.stdout
    assert ("data/cache/dividend_kr_2026_payment_state.json 갱신 확인(데이터 기준 2026-09-04 07:30 KST — "
            "기대 실행일 2026-09-04(예약 05:30 KST)의 결과)") in proc.stdout, proc.stdout


def test_daily_state_from_yesterday_is_flagged_and_redispatched(tmp_path):
    """
    ⭐ daily 핵심 — 어제 상태 파일 그대로면 오늘 05:00/05:30 KST 감시가 안 돈 것(또는 상태 파일을
    못 남긴 것). ❌ + 재실행 + 이슈 항목 사유. 30시간 창만 보던 예전 판정으로는 어제 07:13 실행이
    창 안에 들어 ✅ 였습니다.
    """
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"watch_dividend_disclosures.yml": "2026-09-03 07:13",
                                          "watch_dividend_payment_events.yml": "2026-09-03 07:30"}),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("watch_dividend_disclosures.yml"),
                                     expected_dispatch_args("watch_dividend_payment_events.yml")], dispatch_calls(calls)
    assert "has_failures=true" in output, output
    assert (f"- watch_dividend_disclosures.yml ({STALE_PHRASE}: 데이터 기준 2026-09-03 07:13 KST — "
            "기대 실행일 2026-09-04(예약 05:00 KST)의 결과가 아님") in output, output
    assert (f"- watch_dividend_payment_events.yml ({STALE_PHRASE}: 데이터 기준 2026-09-03 07:30 KST — "
            "기대 실행일 2026-09-04(예약 05:30 KST)의 결과가 아님") in output, output


@pytest.mark.parametrize("stamp, expect_flag, label", [
    ("2026-09-04 00:00", False, "오늘 00:00 — 시각 조건 없음(어제까지 확인이라 같은 날 어느 시각이든 동일)"),
    ("2026-09-04 04:59", False, "오늘 04:59 — cron 전 수동 실행도 오늘치로 침"),
    ("2026-09-03 23:59", True,  "어제 23:59 — 날짜가 다르면 ❌"),
    ("2026-09-05 00:00", True,  "내일(시계 오류) — 기대 실행일과 다르면 ❌"),
])
def test_daily_date_boundary_is_exact(tmp_path, stamp, expect_flag, label):
    now = TS_FRI_INCIDENT_CHECK
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"watch_dividend_disclosures.yml": stamp}),
    )
    assert proc.returncode == 0, proc.stderr
    flagged = dispatch_calls(calls)
    if expect_flag:
        assert flagged == [expected_dispatch_args("watch_dividend_disclosures.yml")], (label, flagged)
    else:
        assert flagged == [], (label, flagged)
        assert "has_failures=false" in output, (label, output)


def test_daily_check_before_cron_time_expects_yesterday():
    """사람이 cron(05:00 KST) 전인 금 03:00 에 워치독을 돌리면 오늘치를 기대할 수 없으니 어제 것이 정상."""
    early = kst_ts(2026, 9, 4, 3, 0)
    assert expected_daily_date(early, (5, 0)) == "2026-09-03"
    ok, note = run_verdict(data_file_text("watch_dividend_disclosures.yml", "2026-09-03 07:13"),
                           early, "updated_at_kst", "daily@05:00")
    assert ok == "yes", note
    ok, note = run_verdict(data_file_text("watch_dividend_disclosures.yml", "2026-09-02 07:13"),
                           early, "updated_at_kst", "daily@05:00")
    assert ok == "no" and "기대 실행일 2026-09-03" in note, note
    # 05:30 대상은 05:00~05:29 사이엔 아직 어제를 기대합니다(두 cron 이 다름).
    between = kst_ts(2026, 9, 4, 5, 10)
    assert run_verdict(data_file_text("watch_dividend_disclosures.yml", "2026-09-04 05:05"),
                       between, "updated_at_kst", "daily@05:00")[0] == "yes"
    assert run_verdict(data_file_text("watch_dividend_payment_events.yml", "2026-09-03 07:30"),
                       between, "updated_at_kst", "daily@05:30")[0] == "yes"


def test_daily_runs_on_weekends_too():
    """daily 대상은 주말에도 돕니다 — 토요일 18:00 KST 검사의 기대 실행일은 토요일(평일로 되감지 않음)."""
    sat = kst_ts(2026, 9, 5, 18, 0)
    assert kst_dow(sat) == 6
    assert run_verdict(data_file_text("watch_dividend_payment_events.yml", "2026-09-05 07:30"),
                       sat, "updated_at_kst", "daily@05:30")[0] == "yes"
    ok, note = run_verdict(data_file_text("watch_dividend_payment_events.yml", "2026-09-04 07:30"),
                           sat, "updated_at_kst", "daily@05:30")
    assert ok == "no" and "기대 실행일 2026-09-05" in note, note


def test_daily_unreachable_or_malformed_file_counts_as_not_updated(tmp_path):
    """404 / 키 없음 → 미갱신(안전한 쪽)."""
    now = TS_FRI_INCIDENT_CHECK
    files = _data_files_with(now, {"watch_dividend_disclosures.yml": None})
    files[DATA_TARGETS["watch_dividend_payment_events.yml"][0]] = json.dumps({"last_checked_de": "20260903"})
    proc, calls, output = run_check_step(tmp_path, _all_ok_status(now), now_ts=now, data_files=files)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert dispatch_calls(calls) == [expected_dispatch_args("watch_dividend_disclosures.yml"),
                                     expected_dispatch_args("watch_dividend_payment_events.yml")], dispatch_calls(calls)
    assert "타임스탬프(updated_at_kst)를 읽지 못함" in output, output


def test_daily_deadlines_match_each_target_workflows_cron():
    """
    daily@HH:MM 의 HH:MM 은 그 워크플로우 schedule cron 을 KST 로 옮긴 값이어야 합니다 — 누군가 cron 을
    옮기고 여기를 안 고치면 "기대 실행일" 판정이 어긋납니다(한쪽만 바뀌면 빨간불).
    """
    import re
    script = load_check_step_script()
    for wf in DAILY_DATA_TARGETS:
        rule = DATA_TARGETS[wf][2]
        m = re.match(r"^daily@(\d{2}):(\d{2})$", rule)
        assert m, rule
        declared = int(m.group(1)) * 60 + int(m.group(2))
        crons = _schedule_crons(WORKFLOW_PATH.parent / wf)
        assert len(crons) == 1, (wf, crons)
        assert declared == _cron_kst_minute_of_day(crons[0]), (wf, rule, crons[0])
        assert f"{wf}|daily|{DATA_TARGETS[wf][0]}|{DATA_TARGETS[wf][1]}|{rule}" in script


def test_dividend_state_paths_match_each_target_workflows_year_and_cache_dir():
    """
    상태 파일 경로의 연도(2026)와 디렉터리는 그 워크플로우가 수집기에 넘기는 `--year` / `--cache-dir` 에서
    나옵니다(collector_dividend_kr.py::watch_state_path / collector_dividend_payment_kr.py::payment_state_path).
    연도가 바뀌어 워크플로우만 고치면 워치독이 없는 파일을 보고 매일 ❌ 를 찍으므로 여기서 대조합니다.
    """
    import re
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음")
    for wf, suffix in (("watch_dividend_disclosures.yml", "watch_state"),
                       ("watch_dividend_payment_events.yml", "payment_state")):
        doc = yaml.safe_load((WORKFLOW_PATH.parent / wf).read_text(encoding="utf-8"))
        run_blocks = "\n".join(step.get("run", "") for step in doc["jobs"]["watch"]["steps"])
        year = re.search(r"--year\s+(\d{4})", run_blocks)
        cache_dir = re.search(r"--cache-dir\s+(\S+)", run_blocks)
        assert year and cache_dir, (wf, run_blocks)
        expected_path = f"{cache_dir.group(1)}/dividend_kr_{year.group(1)}_{suffix}.json"
        assert DATA_TARGETS[wf][0] == expected_path, (wf, DATA_TARGETS[wf][0], expected_path)
        # 워크플로우의 커밋 목록에도 그 파일이 있어야 합니다(커밋 안 되면 main 에서 못 읽습니다).
        assert expected_path in run_blocks, (wf, expected_path)


def test_unknown_rule_is_reported_not_guessed():
    """TARGETS 5번째 필드에 모르는 값이 들어가면 추측하지 않고 "미갱신 + 사유"로 안전한 쪽(§0-1)."""
    ok, note = run_verdict(data_file_text("scrape.yml", "2026-09-04 16:05"),
                           TS_FRI_INCIDENT_CHECK, "metadata.last_updated_at", "weekly")
    assert ok == "no" and "알 수 없는 판정 규칙" in note, note
    # 빈 규칙은 kr(#196 그대로).
    assert run_verdict(data_file_text("scrape.yml", "2026-09-04 16:05"),
                       TS_FRI_INCIDENT_CHECK, "metadata.last_updated_at", "")[0] == "yes"


def test_kr_rule_wording_is_unchanged_by_the_extension():
    """#196 의 kr 판정 문구(이슈 본문·§6 검사가 의존)는 확장 뒤에도 글자 그대로여야 합니다."""
    now = TS_FRI_INCIDENT_CHECK
    ok, note = run_verdict(data_file_text("scrape.yml", INCIDENT_STAMP), now, "metadata.last_updated_at", "kr")
    assert (ok, note) == ("no", "데이터 기준 2026-09-04 07:04 KST — 날짜는 오늘이지만 장마감 15:30 이전 시각(장 시작 전·장중 값)")
    ok, note = run_verdict(data_file_text("indicator_kr.yml", "2026-09-03 16:05"), now, "generated_at", "kr")
    assert (ok, note) == ("no", "데이터 기준 2026-09-03 16:05 KST — 기대 거래일 2026-09-04(장마감 15:30 이후)의 데이터가 아님")
    ok, note = run_verdict(data_file_text("scrape.yml", "2026-09-04 16:05"), now, "metadata.last_updated_at", "kr")
    assert (ok, note) == ("yes", "데이터 기준 2026-09-04 16:05 KST — 거래일 2026-09-04 장마감 이후")


def test_stale_us_and_daily_data_during_market_hours_is_reported_but_not_redispatched(tmp_path):
    """장중(화 11:00 KST)엔 어떤 대상이든 재실행을 걸지 않는 종전 규칙이 새 대상에도 그대로 적용됩니다."""
    now = TS_TUE_MARKET_MIDDAY
    proc, calls, output = run_check_step(
        tmp_path, _all_ok_status(now), now_ts=now,
        data_files=_data_files_with(now, {"scrape_us.yml": "2026-08-27 16:35",
                                          "watch_dividend_disclosures.yml": "2026-08-31 07:13"}),
    )
    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert f"- scrape_us.yml ({STALE_PHRASE}: 데이터 기준 2026-08-27 16:35 ET" in output, output
    assert f"- watch_dividend_disclosures.yml ({STALE_PHRASE}: 데이터 기준 2026-08-31 07:13 KST" in output, output
    assert output.count(MARKET_SKIP_PHRASE) == 2, output


def main():
    print("=" * 74)
    print("🕒 watch_schedule_health.yml 판정 로직 검증 (네트워크 불필요)")
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
