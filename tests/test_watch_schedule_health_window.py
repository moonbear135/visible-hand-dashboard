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

# 테스트 기준 시각 — 2026-08-30 09:00 KST(= 00:00 UTC), 이 워치독의 실제 cron 발동 시각.
NOW_TS = 1756512000
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


def run_entry(hours_ago, conclusion="success"):
    """`hours_ago` 시간 전에 만들어진 실행 한 건(GitHub API 응답 모양 그대로)."""
    import datetime

    created = datetime.datetime.fromtimestamp(
        NOW_TS - hours_ago * HOUR, tz=datetime.timezone.utc
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

# GET repos/<owner>/<repo>/actions/workflows/<FILE>/runs?...
parsed = urlparse(args[1])
wf_file = parsed.path.split("/actions/workflows/")[1].split("/runs")[0]
runs = json.load(open(os.environ["GH_RUN_STATUS"], encoding="utf-8"))[wf_file]

# 진짜 GitHub API 와 같게 event 필터를 적용합니다(쿼리에 있을 때만).
events = parse_qs(parsed.query).get("event")
if events:
    runs = [r for r in runs if r.get("event") in events]

print(json.dumps({"total_count": len(runs), "workflow_runs": runs}))
'''

_DATE_STUB = r'''import os, subprocess, sys

args = sys.argv[1:]
if args == ["-u", "+%s"]:
    print(os.environ["FAKE_NOW_TS"])
elif args == ["+%u"]:
    print(os.environ["FAKE_DOW"])
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
]
WEEKDAY_ONLY_TARGETS = ALL_TARGETS[:5]
DAILY_TARGETS = ALL_TARGETS[5:]

REPO_SLUG = "moonbear135/visible-hand-dashboard"


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
    return script


def _write_stub(path, body):
    path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
    path.chmod(0o755)


def run_check_step(tmp_path, run_status, dispatch_rc=0, dow=4):
    """
    가짜 `gh`/`date` 위에서 첫 스텝 스크립트를 통째로 실행합니다(네트워크 없음).

    `run_status` 는 {워크플로우 파일명: [실행 항목, ...]} — 가짜 `gh` 가 그대로 돌려줍니다.
    `dow` 는 KST 요일(1=월 ... 7=일), `dispatch_rc` 는 재실행 트리거의 종료코드입니다.
    반환값은 (CompletedProcess, gh 호출 인자 목록, GITHUB_OUTPUT 내용).
    """
    script = load_check_step_script()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "gh", _GH_STUB)
    _write_stub(bin_dir / "date", _DATE_STUB)

    status_path = tmp_path / "run_status.json"
    status_path.write_text(json.dumps(run_status), encoding="utf-8")
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
        GH_DISPATCH_RC=str(dispatch_rc),
        FAKE_NOW_TS=str(NOW_TS),
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


def status_map(ok_files, missing_files, event="schedule"):
    """window 안 성공(ok) / 실행 기록 없음(missing) 으로 가짜 API 응답을 만듭니다."""
    status = {f: [dict(run_entry(2), event=event)] for f in ok_files}
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
    proc, calls, output = run_check_step(tmp_path, status_map(ok, missing), dow=4)

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
    proc, calls, output = run_check_step(tmp_path, status_map(ALL_TARGETS, []), dow=4)

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
        tmp_path, status_map(ok, missing), dispatch_rc=1, dow=4
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
        tmp_path, status_map(ALL_TARGETS, [], event="workflow_dispatch"), dow=4
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
    proc, calls, output = run_check_step(tmp_path, status, dow=4)

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output


def test_weekend_skips_weekday_only_targets_entirely(tmp_path):
    """
    주말(토=6)에는 평일 전용 5개를 검사 자체에서 건너뜁니다 — 조회도, 재실행도 없어야
    합니다(주말에 안 도는 게 정상인데 재실행을 걸면 매주 두 번씩 헛발동).
    """
    proc, calls, output = run_check_step(
        tmp_path, status_map([], ALL_TARGETS), dow=6
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
    status = {f: [dict(run_entry(72), event="schedule")] for f in WEEKDAY_ONLY_TARGETS}
    status.update({f: [dict(run_entry(2), event="schedule")] for f in DAILY_TARGETS})
    proc, calls, output = run_check_step(tmp_path, status, dow=1)

    assert proc.returncode == 0, proc.stderr
    assert dispatch_calls(calls) == [], dispatch_calls(calls)
    assert "has_failures=false" in output, output


def test_permissions_grant_actions_write():
    """재실행 API(POST .../dispatches)에는 `actions: write` 권한이 필요합니다."""
    yaml = pytest.importorskip("yaml", reason="PyYAML 없음")
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert doc["permissions"].get("actions") == "write", doc["permissions"]


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
