# tests/test_stock_history.py
"""
📈 종목별 시계열 이력(utils/stock_history.py) + 다운로드 내보내기(utils/stock_export.py)
   오프라인 검증 (네트워크 불필요)

⚠️ 여기 쓰는 데이터는 두 종류뿐입니다.
   ① 저장소의 **실제 스냅샷** (data/kospi200_pegy_latest.json / data/us_stocks_latest.json)
   ② 합성 fake 종목 (실패/차단 시나리오처럼 실데이터로 만들 수 없는 경우만)
   기존 테스트 스타일(tests/test_us_stocks.py)과 동일하게, 실제 함수를 직접 호출합니다.

⚠️ 저장소의 진짜 이력 파일(data/*_stock_history.csv)은 **절대 건드리지 않습니다.**
   모든 쓰기는 tempfile 디렉터리에서만 일어납니다.

실행: python tests/test_stock_history.py
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent))

from utils.stock_history import (  # noqa: E402
    DATE_FIELD,
    KOSPI_HISTORY_FIELDS,
    KOSPI_HISTORY_FILENAME,
    KOSPI_KEY_FIELD,
    RECORDABLE_STATUSES,
    US_HISTORY_FIELDS,
    US_HISTORY_FILENAME,
    US_KEY_FIELD,
    append_daily_history,
    build_history_row,
    field_keys,
    field_labels,
    load_stock_history,
    read_history_rows,
    record_daily_history,
    stock_history_path,
)
from utils.stock_export import (  # noqa: E402
    build_export_filename,
    build_history_csv_bytes,
    build_history_json_bytes,
    history_date_range,
    sanitize_filename_part,
    to_display_value,
)

REPO_ROOT = Path(__file__).parent.parent
FAILURES = []

import pytest


@pytest.fixture(autouse=True)
def _assert_no_check_failures():
    """
    🔴 2026-08-21 발견 — `check()`는 실패를 `FAILURES`에 기록만 하고, 그 목록을 실제로
    검사해서 죽는 코드는 파일 맨 아래 `if __name__ == "__main__": main()` 안에만 있었습니다.
    이 파일의 모든 검증은 pytest로 돌려왔는데, pytest는 `main()`을 절대 부르지 않으므로
    `check()` 실패가 있어도 각 `test_*` 함수는 스스로 실패하지 않았습니다 — 이 파일의
    배선·렌더 스모크 검사가 그동안 pytest 상에서는 항상 초록불이었다는 뜻입니다
    (2026-08-21, 결투다! USD 화면 작업 중 발견).

    그래서 매 테스트 앞뒤로 `FAILURES`의 증가분을 직접 확인해 pytest에서도 똑같이
    실패하게 만듭니다. 기존 `test_*` 함수는 한 줄도 안 고쳤습니다 — 이 fixture 하나가
    파일 안의 모든 테스트에 자동 적용됩니다(pytest의 `autouse` 규약).
    """
    start = len(FAILURES)
    yield
    new_failures = FAILURES[start:]
    assert not new_failures, f"check() 로 기록된 실패 {len(new_failures)}건: {new_failures}"



def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


def _load_snapshot(filename):
    path = REPO_ROOT / "data" / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 1. 필드 스펙 — "카드에 보이는 재무 데이터만, 한국어 라벨로"
# =============================================================================
# 오너가 명시적으로 빼라고 한 내부 필드들(색상 hex / 진단 / 사유 / 내부 플래그).
FORBIDDEN_KEYS = [
    "badge_bg", "badge_fg",
    "is_visible", "is_valid", "is_unverified",
    "data_issues", "collect_errors", "consistency_warnings", "missing_fields",
    "paywalled_fields", "validation_error",
    "value_trap_severity", "value_trap_basis",
    "score_excluded_items", "growth_score_capped",
    "t_roe_inherited_from", "dps_inherited_from",
    "f_target_cap_reason", "f_target_capped", "f_target_uncapped",
    "t_fair_capped", "t_fair_uncapped", "target_per_capped",
    "g_eff_capped", "g_eff_uncapped",
    "dps_source", "growth_source", "t_eps_source", "f_eps_source", "price_source",
    "name_kr_source", "sector_basis", "sh_return_basis", "url", "raw_score",
    "forward_missing_fields", "forward_data_missing", "reject_reason", "unverified_reason",
]


def test_field_spec():
    print("\n[1] 필드 스펙 (카드에 보이는 것만 / 한국어 라벨)")
    for name, fields in (("코스피", KOSPI_HISTORY_FIELDS), ("미국", US_HISTORY_FIELDS)):
        keys = field_keys(fields)
        labels = field_labels(fields)

        check(keys[0] == DATE_FIELD and labels[0] == "날짜",
              f"[{name}] 첫 컬럼이 날짜 (시계열 파일이므로)")
        check(len(keys) == len(set(keys)), f"[{name}] 컬럼 키 중복 없음")
        check(len(labels) == len(set(labels)), f"[{name}] 라벨 중복 없음")

        leaked = [k for k in keys if k in FORBIDDEN_KEYS]
        check(not leaked, f"[{name}] 내부 진단/색상 필드가 하나도 안 들어감", f"→ {leaked}")

        # 라벨은 사람이 읽는 한국어여야 합니다 — 영문 변수명(t_per 등)을 그대로 쓰면 실패.
        bad_labels = [lb for lb in labels if lb.strip() == "" or lb in keys]
        check(not bad_labels, f"[{name}] 라벨이 영문 변수명 그대로인 항목 없음", f"→ {bad_labels}")
        has_hangul = [lb for lb in labels if any("가" <= ch <= "힣" for ch in lb)]
        check(len(has_hangul) >= len(labels) * 0.6,
              f"[{name}] 라벨 대부분이 한국어 ({len(has_hangul)}/{len(labels)})")

        kinds = {kind for _k, _l, kind in fields}
        check(kinds <= {"text", "num", "bool"}, f"[{name}] 값 종류가 text/num/bool 뿐", f"→ {kinds}")

    # 공통 지표는 라벨 문구가 갈라지면 안 됩니다(코스피/미국 파일이 서로 다른 말을 쓰면 혼란).
    # 단, 아래 2개는 **같은 키인데 실제로 다른 지표**라 화면 카드 문구도 원래 다릅니다:
    #   growth    : 코스피=네이버 '추정EPS vs TTM EPS' 증감률 / 미국=소스의 '3년 EPS 성장 전망'
    #   sh_return : 코스피=배당수익률만(자사주 미수집) / 미국=배당+자사주 매입 합산 주주환원율
    # 이 둘의 라벨을 억지로 통일하면 서로 다른 값을 같은 이름으로 부르게 되어 더 위험합니다.
    INTENTIONAL_LABEL_DIFFS = {"growth", "sh_return"}
    k_map = {k: lb for k, lb, _ in KOSPI_HISTORY_FIELDS}
    u_map = {k: lb for k, lb, _ in US_HISTORY_FIELDS}
    shared = sorted(set(k_map) & set(u_map))
    mismatch = [k for k in shared
                if k_map[k] != u_map[k]
                and k not in INTENTIONAL_LABEL_DIFFS
                and "(원" not in k_map[k] and "USD" not in u_map[k]]
    check(not mismatch,
          f"공통 지표 {len(shared)}개의 라벨 문구 일치(통화 단위·의도적 예외 제외)", f"→ {mismatch}")
    diffs = [k for k in INTENTIONAL_LABEL_DIFFS if k_map.get(k) == u_map.get(k)]
    check(not diffs,
          "실제로 다른 지표(growth·sh_return)는 라벨도 다르게 구분됨",
          f"→ 같아진 항목 {diffs}")

    # 미국 전용 지표(오너가 예시로 든 베타·F-Score)가 실제로 들어있는지
    check("beta" in u_map and "piotroski_f" in u_map, "미국 전용 지표(베타·F-Score) 포함")
    check("beta" not in k_map, "코스피에는 베타 컬럼을 만들지 않음(수집하지 않는 값)")

    # 2026-08-26 신설 — 코스피+코스닥 통합 500 확대(오너 후속 요청 "라벨이 있으면 더
    # 좋긴하지 그것까지 보여놔줘") 후 코스피 파일에만 market 컬럼이 있어야 함.
    check("market" in k_map, "코스피 파일에 시장구분(market) 컬럼이 있음")
    check("market" not in u_map, "미국 파일에는 시장구분 컬럼이 없음(코스피/코스닥 구분이 의미 없는 시장)")


def test_market_field_round_trips_and_defaults_to_blank_when_absent():
    """market 필드가 있으면 그대로, 없으면(구버전 스냅샷 등) 값을 지어내지 않고 빈 칸(§0-1)."""
    print("\n[1-b] market 필드 — 값이 있으면 그대로, 없으면 빈 칸")
    with_market = {"rank": 1, "name": "테스트코스닥종목", "code": "999999", "price": 1000,
                   "market": "KOSDAQ"}
    without_market = {"rank": 2, "name": "구버전스냅샷종목", "code": "888888", "price": 2000}

    row_with = build_history_row(with_market, "2026-08-26", KOSPI_HISTORY_FIELDS)
    row_without = build_history_row(without_market, "2026-08-26", KOSPI_HISTORY_FIELDS)

    check(row_with["market"] == "KOSDAQ", "market 필드가 있으면 값을 그대로 내보냄", f"→ {row_with['market']!r}")
    check(row_without["market"] == "", "market 필드가 없으면 빈 칸(모름을 지어내지 않음)",
          f"→ {row_without['market']!r}")


# =============================================================================
# 2. 실제 스냅샷 -> 이력 행 변환
# =============================================================================
def test_row_from_real_snapshot():
    print("\n[2] 실제 스냅샷 레코드 → 이력 행 변환")
    snap = _load_snapshot("kospi200_pegy_latest.json")
    if not snap:
        check(False, "코스피 스냅샷 로드", "data/kospi200_pegy_latest.json 없음")
        return
    stocks = snap["stocks"]
    s = next((x for x in stocks if x.get("code") == "005930"), stocks[0])
    row = build_history_row(s, "2026-08-09", KOSPI_HISTORY_FIELDS)

    check(set(row.keys()) == set(field_keys(KOSPI_HISTORY_FIELDS)),
          "행의 컬럼이 스펙과 정확히 일치(추가 필드 유출 없음)")
    check(row["date"] == "2026-08-09", "날짜가 전달한 값 그대로")
    check(row["name"] == s["name"] and row["code"] == s["code"],
          f"종목명·코드 원본 그대로 ({row['name']}/{row['code']})")
    check(row["t_per"] == str(s["t_per"]), f"PER 값을 가공 없이 그대로 저장 ({row['t_per']})")
    check(row["value_trap"] in ("true", "false"), "bool 값은 true/false 문자열로 저장")

    # 결측(None)은 빈 칸 — 0이나 문구로 채우지 않습니다(§0-1)
    none_keys = [k for k, _l, _kd in KOSPI_HISTORY_FIELDS if k != DATE_FIELD and s.get(k) is None]
    check(all(row[k] == "" for k in none_keys),
          f"결측 {len(none_keys)}개 필드가 전부 빈 칸(0·문구로 안 채움)")

    us = _load_snapshot("us_stocks_latest.json")
    if not us:
        check(False, "미국 스냅샷 로드", "data/us_stocks_latest.json 없음")
        return
    u = next((x for x in us["stocks"] if x.get("symbol") == "NVDA"), us["stocks"][0])
    urow = build_history_row(u, "2026-08-09", US_HISTORY_FIELDS)
    check(urow["symbol"] == u["symbol"] and urow["name_kr"] == (u.get("name_kr") or ""),
          f"미국: 티커·한글명 그대로 ({urow['symbol']}/{urow['name_kr']})")
    check(urow["beta"] == str(u["beta"]) and urow["piotroski_f"] == str(u["piotroski_f"]),
          "미국: 베타·F-Score 그대로")


# =============================================================================
# 3. "성공했을 때만 기록" — 상태 가드
# =============================================================================
def _fake_stocks(n=3, day_price=1000):
    return [
        {"rank": i + 1, "name": f"테스트종목{i}", "code": f"00000{i}", "price": day_price + i,
         "t_per": 10.0 + i, "t_pbr": None, "value_trap": bool(i % 2), "badge": "🟢 강력 저평가",
         "quant_score": 50 + i, "score_max": 80}
        for i in range(n)
    ]


def test_status_guard():
    print("\n[3] 수집이 성공했을 때만 기록 (상태 가드)")
    tmpdir = tempfile.mkdtemp(prefix="stock_history_test_")
    path = os.path.join(tmpdir, "hist.csv")

    for bad_status in ("FAILED", "LOAD_FAILED", "", None):
        res = record_daily_history(path, _fake_stocks(), "2026-08-09", KOSPI_HISTORY_FIELDS, bad_status)
        check(res["recorded"] is False, f"status={bad_status!r} 이면 기록하지 않음")
    check(not os.path.exists(path), "실패 상태에서는 이력 파일이 아예 생기지도 않음")

    res = record_daily_history(path, [], "2026-08-09", KOSPI_HISTORY_FIELDS, "SUCCESS")
    check(res["recorded"] is False and not os.path.exists(path),
          "종목이 0건이면(전부 실패한 날) 빈 날짜 행을 만들지 않음")

    for ok_status in RECORDABLE_STATUSES:
        p2 = os.path.join(tmpdir, f"hist_{ok_status}.csv")
        res = record_daily_history(p2, _fake_stocks(), "2026-08-09", KOSPI_HISTORY_FIELDS, ok_status)
        check(res["recorded"] is True and res["row_count"] == 3,
              f"status={ok_status} 이면 3종목이 기록됨")

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_collector_blocked_scenarios():
    print("\n[4] 수집기가 중간에 실패/차단되면 이력에 아무것도 안 쌓임 (실제 함수 호출)")
    import collector_kospi200 as K
    import collector_us_stocks as U

    calls = []

    # --- 코스피: 종목 목록 스크래핑 자체가 실패한 경우 -------------------------
    orig_fetch = K.fetch_kospi200_real_market_data
    orig_record_k = K.record_daily_history
    try:
        K.fetch_kospi200_real_market_data = lambda: ([], [])
        K.record_daily_history = lambda **kw: calls.append(("kospi", kw))
        raised = False
        try:
            K.run_kospi200_collector()
        except RuntimeError:
            raised = True
        check(raised, "[코스피] 목록 수집 실패 시 RuntimeError 로 중단(기존 동작 유지)")
        check(not calls, "[코스피] 중단된 실행은 이력 기록 함수를 부르지도 않음")
    finally:
        K.fetch_kospi200_real_market_data = orig_fetch
        K.record_daily_history = orig_record_k

    # --- 미국: 소스가 우리를 차단(HTTP 429)한 경우 -----------------------------
    calls.clear()
    orig_universe = U.fetch_universe_rows
    orig_record_u = U.record_daily_history

    def _blocked(*a, **kw):
        raise U.USSourceBlockedError("HTTP 429 — 소스가 차단했습니다(테스트 시뮬레이션)")

    try:
        U.fetch_universe_rows = _blocked
        U.record_daily_history = lambda **kw: calls.append(("us", kw))
        raised = False
        try:
            U.run_us_collector(delay=False, skip_indices=True)
        except U.USSourceBlockedError:
            raised = True
        check(raised, "[미국] 소스 차단 시 USSourceBlockedError 로 중단(기존 동작 유지)")
        check(not calls, "[미국] 차단된 실행은 이력 기록 함수를 부르지도 않음")
    finally:
        U.fetch_universe_rows = orig_universe
        U.record_daily_history = orig_record_u

    # --- 수집기 배선: 스냅샷 저장이 끝난 '뒤'에 호출되는가 ---------------------
    k_src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check(k_src.index("json.dump(snapshot_payload") < k_src.index("record_daily_history("),
          "[코스피] 이력 기록이 스냅샷 저장 뒤에 위치(기존 흐름 뒤에 '추가'만)")
    u_src = (REPO_ROOT / "collector_us_stocks.py").read_text(encoding="utf-8")
    check(u_src.index("update_us_summary_history(now_et") < u_src.index("record_daily_history("),
          "[미국] 이력 기록이 스냅샷·요약이력 저장 뒤에 위치")
    check(u_src.index("raise USSourceBlockedError(") < u_src.index("record_daily_history("),
          "[미국] 차단 시 raise 지점이 이력 기록보다 앞 (차단된 날은 도달 불가)")


# =============================================================================
# 5. 누적 / 같은 날 중복 방지 / 조회
# =============================================================================
def test_append_and_dedup():
    print("\n[5] 날짜별 누적 · 같은 날 중복 방지 · 종목별 조회")
    tmpdir = tempfile.mkdtemp(prefix="stock_history_test_")
    path = os.path.join(tmpdir, "hist.csv")

    r1 = append_daily_history(path, _fake_stocks(day_price=1000), "2026-08-09", KOSPI_HISTORY_FIELDS)
    check(r1["row_count"] == 3 and r1["total_rows"] == 3, "1일차: 3종목 기록")

    r2 = append_daily_history(path, _fake_stocks(day_price=1100), "2026-08-10", KOSPI_HISTORY_FIELDS)
    check(r2["total_rows"] == 6 and r2["replaced"] == 0, "2일차: 기존을 덮어쓰지 않고 누적(총 6행)")

    # 같은 날짜 재실행 (미국 워크플로우가 하루 두 번 트리거되는 구조 대비 방어)
    r3 = append_daily_history(path, _fake_stocks(day_price=1234), "2026-08-10", KOSPI_HISTORY_FIELDS)
    check(r3["total_rows"] == 6 and r3["replaced"] == 3,
          "같은 날짜 재실행: 중복으로 쌓이지 않고 그 날짜 행만 교체(총 6행 유지)")

    rows = load_stock_history(path, KOSPI_KEY_FIELD, "000001")
    check(len(rows) == 2, f"한 종목 조회 = 2일치 ({len(rows)}행)")
    check([r[DATE_FIELD] for r in rows] == ["2026-08-09", "2026-08-10"], "날짜 오름차순 정렬")
    check(rows[1]["price"] == "1235", f"재실행분의 새 값으로 교체됨 ({rows[1]['price']})")
    check(load_stock_history(path, KOSPI_KEY_FIELD, "없는코드") == [],
          "없는 종목을 조회하면 빈 목록(값을 지어내지 않음)")

    # 이력이 하루치뿐이어도 정상 동작해야 합니다(도입 첫날 시나리오)
    one_day = os.path.join(tmpdir, "oneday.csv")
    append_daily_history(one_day, _fake_stocks(), "2026-08-09", KOSPI_HISTORY_FIELDS)
    single = load_stock_history(one_day, KOSPI_KEY_FIELD, "000000")
    check(len(single) == 1, "도입 첫날: 행이 1개뿐인 것도 정상")

    check(read_history_rows(os.path.join(tmpdir, "없는파일.csv")) == [],
          "이력 파일이 없으면 빈 목록(예외로 죽지 않음)")

    shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# 6. 실제 스냅샷 → 이력 1건 적재 → CSV/JSON 내보내기 (end-to-end)
# =============================================================================
def test_export_end_to_end():
    print("\n[6] 실데이터 end-to-end (임시 파일에 이력 적재 → CSV/JSON 내보내기)")
    snap = _load_snapshot("kospi200_pegy_latest.json")
    us = _load_snapshot("us_stocks_latest.json")
    if not snap or not us:
        check(False, "실제 스냅샷 로드", "data/*.json 누락")
        return

    tmpdir = tempfile.mkdtemp(prefix="stock_history_test_")
    path = os.path.join(tmpdir, KOSPI_HISTORY_FILENAME)

    # 실제 스냅샷 전 종목을 이틀치로 적재 (2일차는 같은 값 — 값을 지어내지 않기 위해
    # 가격을 흔들지 않고, 날짜만 다르게 넣습니다)
    record_daily_history(path, snap["stocks"], "2026-08-08", KOSPI_HISTORY_FIELDS, "SUCCESS")
    record_daily_history(path, snap["stocks"], "2026-08-09", KOSPI_HISTORY_FIELDS, "SUCCESS")

    target = next((x for x in snap["stocks"] if x.get("code") == "005930"), snap["stocks"][0])
    rows = load_stock_history(path, KOSPI_KEY_FIELD, target["code"])
    check(len(rows) == 2, f"삼성전자 이력 2일치 적재 ({len(rows)}행)")

    first, last = history_date_range(rows)
    check((first, last) == ("2026-08-08", "2026-08-09"), f"이력 기간 계산 ({first} ~ {last})")

    # --- CSV ---------------------------------------------------------------
    csv_bytes = build_history_csv_bytes(rows, KOSPI_HISTORY_FIELDS)
    check(csv_bytes[:3] == b"\xef\xbb\xbf", "CSV가 UTF-8 BOM으로 시작(엑셀 한글 깨짐 방지)")
    text = csv_bytes.decode("utf-8-sig")
    check("삼성전자" in text, "CSV 안의 한글이 깨지지 않고 그대로 디코드됨")
    parsed = list(csv.reader(io.StringIO(text)))
    check(parsed[0] == field_labels(KOSPI_HISTORY_FIELDS), "CSV 헤더가 한국어 라벨")
    check(parsed[0][:5] == ["날짜", "시가총액 순위", "종목명", "종목코드", "현재가(원)"],
          f"헤더 앞부분 확인 ({parsed[0][:5]})")
    check(len(parsed) == 3, f"헤더 1줄 + 이력 2줄 ({len(parsed)}줄)")
    check(parsed[1][0] == "2026-08-08" and parsed[2][0] == "2026-08-09", "날짜가 행(시계열 표)")
    code_col = parsed[0].index("종목코드")
    check(parsed[1][code_col] == target["code"],
          f"종목코드 앞자리 0이 살아있음 ({parsed[1][code_col]})")
    per_col = parsed[0].index("PER(Trailing, 배)")
    check(parsed[1][per_col] == str(target["t_per"]), f"PER 값 원본 그대로 ({parsed[1][per_col]})")
    trap_col = parsed[0].index("착시 저평가(가치주 덫)")
    check(parsed[1][trap_col] in ("예", "아니오"), f"bool은 예/아니오로 표기 ({parsed[1][trap_col]})")
    for internal in ("badge_bg", "badge_fg", "data_issues", "is_visible", "f_target_cap_reason"):
        check(internal not in text, f"내부 필드 '{internal}' 가 CSV에 없음")

    # --- JSON --------------------------------------------------------------
    json_bytes = build_history_json_bytes(rows, KOSPI_HISTORY_FIELDS)
    check("삼성전자".encode("utf-8") in json_bytes, "JSON이 ensure_ascii=False (한글 그대로)")
    payload = json.loads(json_bytes.decode("utf-8"))
    check(isinstance(payload, list) and len(payload) == 2, "JSON은 날짜순 객체 2개")
    check(payload[0]["종목코드"] == target["code"], "JSON 종목코드가 문자열 그대로(0 안 사라짐)")
    check(payload[0]["PER(Trailing, 배)"] == target["t_per"], "JSON PER은 숫자로 복원")
    none_labels = [lb for k, lb, _kd in KOSPI_HISTORY_FIELDS
                   if k != DATE_FIELD and target.get(k) is None]
    check(all(payload[0][lb] is None for lb in none_labels),
          f"수집 못 한 값은 JSON에서 null ({len(none_labels)}개)")

    # --- 미국 쪽도 같은 경로로 --------------------------------------------
    us_path = os.path.join(tmpdir, US_HISTORY_FILENAME)
    record_daily_history(us_path, us["stocks"], "2026-08-08", US_HISTORY_FIELDS, "SUCCESS")
    nvda = load_stock_history(us_path, US_KEY_FIELD, "NVDA")
    check(len(nvda) == 1, "미국: NVDA 이력 1일치 적재")
    us_text = build_history_csv_bytes(nvda, US_HISTORY_FIELDS).decode("utf-8-sig")
    us_parsed = list(csv.reader(io.StringIO(us_text)))
    check(us_parsed[0] == field_labels(US_HISTORY_FIELDS), "미국 CSV 헤더도 한국어 라벨")
    check("엔비디아" in us_text, "미국 CSV의 한글 종목명 정상")
    beta_col = us_parsed[0].index("베타(5년)")
    check(us_parsed[1][beta_col] != "", f"미국 전용 컬럼(베타) 값 존재 ({us_parsed[1][beta_col]})")

    # 슬래시 티커도 파일이 깨지지 않아야 합니다
    brk = next((x for x in us["stocks"] if "/" in (x.get("symbol") or "")), None)
    if brk:
        fn = build_export_filename(brk.get("name_kr") or brk["symbol"], brk["symbol"], "20260809", "csv")
        check("/" not in fn, f"슬래시 티커 파일명 안전화 ({fn})")
    check(sanitize_filename_part("BRK/B") == "BRK_B", "sanitize_filename_part 규칙 유지")

    # 전 종목 전수 실행 — 예외 0건이어야 합니다
    errors = []
    for stock in snap["stocks"][:50] + us["stocks"][:50]:
        try:
            fields = KOSPI_HISTORY_FIELDS if "code" in stock else US_HISTORY_FIELDS
            build_history_csv_bytes([build_history_row(stock, "2026-08-09", fields)], fields)
        except Exception as e:  # noqa: BLE001
            errors.append((stock.get("code") or stock.get("symbol"), str(e)))
    check(not errors, "실데이터 100종목 CSV 생성 예외 0건", f"→ {errors[:3]}")

    shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# 7. 화면 배선 + 저장 위치
# =============================================================================
def test_wiring():
    print("\n[7] 화면·워크플로우 배선")
    kp = stock_history_path(KOSPI_HISTORY_FILENAME)
    up = stock_history_path(US_HISTORY_FILENAME)
    check(os.path.dirname(kp) == str(REPO_ROOT / "data"),
          f"이력 파일이 data/ 아래에 생성됨 → git add data/ 커밋 범위에 포함 ({kp})")
    check(kp != up, "코스피/미국 이력 파일이 서로 다른 파일")

    for name in (".github/workflows/scrape.yml", ".github/workflows/scrape_us.yml"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        check("git add data/" in text or "git add -A data/" in text,
              f"{name} 가 data/ 전체를 커밋 (새 이력 파일도 자동 포함)")

    pegy = (REPO_ROOT / "views" / "pegy_view.py").read_text(encoding="utf-8")
    usv = (REPO_ROOT / "views" / "us_stocks_view.py").read_text(encoding="utf-8")
    for label, text in (("코스피 화면", pegy), ("미국 화면", usv)):
        check("load_stock_history(" in text, f"[{label}] 다운로드가 이력 기반으로 배선됨")
        check("build_history_csv_bytes(" in text and "build_history_json_bytes(" in text,
              f"[{label}] CSV/JSON 모두 이력 형식으로 생성")
        check("build_stock_csv_bytes(" not in text, f"[{label}] 옛 하루치 내보내기 함수 잔재 없음")
        check("_download_search" in text, f"[{label}] 다운로드 전용 검색창 유지(기존 UI 구조 그대로)")

    # 이력이 아직 없을 때 사용자에게 사실대로 알리는 안내가 있는지
    check("아직 없습니다" in pegy and "아직 없습니다" in usv,
          "이력이 없으면 파일을 지어내지 않고 그 사실을 안내")


def test_value_round_trip():
    print("\n[8] 값 복원 규칙 (문자열/숫자/불리언)")
    check(to_display_value("005930", "text") == "005930", "종목코드는 문자열 유지(숫자로 안 바뀜)")
    check(to_display_value("18.67", "num") == 18.67, "실수 복원")
    check(to_display_value("200", "num") == 200 and isinstance(to_display_value("200", "num"), int),
          "정수 복원")
    check(to_display_value("", "num") is None, "빈 칸은 null (0으로 안 채움)")
    check(to_display_value("true", "bool") is True and to_display_value("false", "bool") is False,
          "불리언 복원")
    check(to_display_value("n/a", "num") == "n/a", "숫자로 못 바꾸면 값을 버리지 않고 원문 유지")


def test_kr_ticker_master_collector():
    print("\n[4-1] 코스피+코스닥+ETF 전체 상장종목 마스터 목록 수집기 "
          "(2026-08-11, TASK_HISTORY #83 — 실제 함수 호출)")
    import collector_kospi200 as K
    import pandas as pd

    def _fake_stock_listing(market_key):
        if market_key == "KRX":
            return pd.DataFrame([
                {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
                {"Code": "247540", "Name": "코스닥종목", "Market": "KOSDAQ"},
            ])
        if market_key == "ETF/KR":
            return pd.DataFrame([
                {"Code": "069500", "Name": "KODEX 200", "Market": "KOSPI"},
            ])
        raise ValueError(f"예상 못한 인자: {market_key}")

    class _FakeFdr:
        StockListing = staticmethod(_fake_stock_listing)

    orig_has_fdr = K.HAS_FDR
    orig_fdr = getattr(K, "fdr", None)
    tmpdir = tempfile.mkdtemp()
    try:
        K.HAS_FDR = True
        K.fdr = _FakeFdr()
        result_path = K.run_kr_ticker_master_collector(data_dir=tmpdir)
        check(result_path is not None, "정상 응답이면 파일 경로를 반환")

        with open(result_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        stocks_by_code = {s["code"]: s for s in payload["stocks"]}
        check(set(stocks_by_code) == {"005930", "247540", "069500"},
              "StockListing('KRX') + StockListing('ETF/KR') 결과가 하나로 합쳐져 저장됨")
        check(stocks_by_code["069500"]["type"] == "ETF" and stocks_by_code["005930"]["type"] == "STOCK",
              "ETF/일반 주식 type 구분이 정확히 반영됨")
        check(stocks_by_code["247540"]["market"] == "KOSDAQ", "코스닥 종목의 시장 구분도 보존됨")
        check("price" not in stocks_by_code["005930"], "가격 필드는 아예 안 담음(밸류에이션 출처 아님)")
        check(payload["metadata"]["count"] == 3, "metadata.count 가 실제 반영 건수와 일치")

        # 컬럼 구조가 예상과 다른 경우(FDR API 변경 시뮬레이션) — 죽지 않고 그냥 건너뜀
        class _BrokenFdr:
            @staticmethod
            def StockListing(market_key):
                return pd.DataFrame([{"엉뚱한컬럼": "x"}])
        K.fdr = _BrokenFdr()
        broken_result = K.run_kr_ticker_master_collector(data_dir=tempfile.mkdtemp())
        check(broken_result is None,
              "컬럼 구조가 예상과 다르면(0건) 파일을 만들지 않고 조용히 None 반환(크래시 안 함)")

        # FDR 자체가 예외를 던지는 경우(네트워크 장애 등)도 마찬가지
        class _RaisingFdr:
            @staticmethod
            def StockListing(market_key):
                raise RuntimeError("네트워크 장애 시뮬레이션")
        K.fdr = _RaisingFdr()
        raising_result = K.run_kr_ticker_master_collector(data_dir=tempfile.mkdtemp())
        check(raising_result is None,
              "FDR 호출 자체가 예외를 던져도 예외를 밖으로 던지지 않고 조용히 건너뜀"
              "(핵심 수집을 막지 않음)")

        # FinanceDataReader 미설치 상황
        K.HAS_FDR = False
        check(K.run_kr_ticker_master_collector(data_dir=tempfile.mkdtemp()) is None,
              "FinanceDataReader 미설치 시에도 예외 없이 None 반환")
    finally:
        K.HAS_FDR = orig_has_fdr
        if orig_fdr is not None:
            K.fdr = orig_fdr
        elif hasattr(K, "fdr"):
            del K.fdr
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 배선 확인: __main__ 에서 핵심 수집(run_kospi200_collector) '뒤에' 실행되고, try/except로
    # 감싸져 있어 이 보조 기능이 실패해도 핵심 수집 결과에 영향이 없는지.
    k_src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check(k_src.index("run_kospi200_collector()") < k_src.index("run_kr_ticker_master_collector()"),
          "전체 상장종목 목록 수집은 핵심 수집(코스피 200) 뒤에 실행됨")
    check("except Exception as e:" in k_src.split("run_kr_ticker_master_collector()")[1][:200],
          "__main__ 에서 이 보조 수집을 try/except 로 감쌈(실패해도 핵심 수집 결과는 그대로)")


def test_kr_all_market_prices_collector():
    print("\n[4-2] 코스피+코스닥 전 종목 종가 수집기 (2026-08-11, TASK_HISTORY #84 — 실제 함수 호출)")
    import collector_kospi200 as K
    from urllib.parse import urlparse, parse_qs

    def _row_html(name, code, price):
        return (
            f"<tr><td>1</td><td><a href='/item/main.naver?code={code}'>{name}</a></td>"
            f"<td>{price}</td>" + "<td></td>" * 9 + "</tr>"
        )

    def _table_html(rows_html):
        return f"<html><body><table class='type_2'>{''.join(rows_html)}</table></body></html>"

    EMPTY_TABLE_HTML = "<html><body><table class='type_2'><tr><td colspan='12'>헤더행</td></tr></table></body></html>"
    NO_TABLE_HTML = "<html><body>표를 찾을 수 없는 응답</body></html>"

    kospi_page1 = _table_html([_row_html("합성전자", "111111", "10,000"), _row_html("합성ETF", "222222", "9,500")])
    kosdaq_page1 = _table_html([_row_html("합성코스닥", "333333", "3,000")])
    kosdaq_page3 = _table_html([_row_html("합성코스닥3", "444444", "7,000")])

    call_log = []

    class _FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    def _fake_get(url, headers=None, timeout=None):
        call_log.append(url)
        qs = parse_qs(urlparse(url).query)
        sosok = qs.get("sosok", ["0"])[0]
        page = int(qs.get("page", ["1"])[0])
        if sosok == "0":
            return _FakeResponse(kospi_page1 if page == 1 else EMPTY_TABLE_HTML)
        if page == 1:
            return _FakeResponse(kosdaq_page1)
        if page == 2:
            return _FakeResponse(NO_TABLE_HTML)  # 이 페이지만 재시도 끝에 실패 → 건너뜀
        if page == 3:
            return _FakeResponse(kosdaq_page3)
        return _FakeResponse(EMPTY_TABLE_HTML)

    class _FakeRequestsModule:
        get = staticmethod(_fake_get)

    orig_requests = K.requests
    orig_sleep = K.time.sleep
    tmpdir = tempfile.mkdtemp()
    try:
        K.requests = _FakeRequestsModule()
        K.time.sleep = lambda s: None  # 재시도/페이지 간 딜레이를 테스트에서는 생략(로직 검증엔 불필요)

        result_path = K.run_kr_all_market_prices_collector(data_dir=tmpdir, max_pages_per_market=10)
        check(result_path is not None, "정상 응답이 하나라도 있으면 파일 경로를 반환")

        with open(result_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        by_code = {s["code"]: s for s in payload["stocks"]}
        check(set(by_code) == {"111111", "222222", "333333", "444444"},
              "코스피 1페이지 + 코스닥 1·3페이지(2페이지 실패는 건너뜀) 종목이 모두 반영됨")
        check(by_code["111111"]["price"] == 10000.0, "콤마 섞인 가격 문자열이 숫자로 파싱됨")
        check(by_code["111111"]["market"] == "KOSPI" and by_code["333333"]["market"] == "KOSDAQ",
              "시장 구분이 정확히 반영됨")
        check("price" in by_code["111111"] and "t_per" not in by_code["111111"],
              "밸류에이션 필드(PER 등)는 없음 — 가격 전용 목적")
        check(payload["metadata"]["count"] == 4, "metadata.count 가 실제 반영 건수와 일치")

        kospi_pages = sorted(int(parse_qs(urlparse(u).query)["page"][0]) for u in call_log if "sosok=0" in u)
        kosdaq_pages = sorted(int(parse_qs(urlparse(u).query)["page"][0]) for u in call_log if "sosok=1" in u)
        check(kospi_pages == [1, 2],
              "코스피는 1페이지(성공) 후 2페이지(빈 표=마지막 페이지)에서 멈춤 — 재시도 없이 각 1번")
        check(kosdaq_pages == [1, 2, 2, 2, 3, 4],
              "코스닥 2페이지는 실패해서 3번 재시도(합계 3번 호출)하고 건너뛴 뒤 3페이지로 이어서 진행, "
              "4페이지(빈 표)에서 멈춤 — 5페이지는 아예 요청되지 않음")

        # 완전 실패 시나리오: 두 시장 다 표를 못 찾으면 파일을 만들지 않음
        class _AlwaysBrokenRequestsModule:
            get = staticmethod(lambda url, headers=None, timeout=None: _FakeResponse(NO_TABLE_HTML))
        K.requests = _AlwaysBrokenRequestsModule()
        broken_result = K.run_kr_all_market_prices_collector(
            data_dir=tempfile.mkdtemp(), max_pages_per_market=3
        )
        check(broken_result is None,
              "코스피·코스닥 둘 다 완전히 실패하면 파일을 만들지 않고 조용히 None 반환(크래시 안 함)")
    finally:
        K.requests = orig_requests
        K.time.sleep = orig_sleep
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 배선 확인: __main__ 에서 핵심 수집·전체 상장종목 목록 수집 '뒤에' 실행되고,
    # try/except로 감싸져 있어 이 보조 기능이 실패해도 앞 두 단계 결과에 영향이 없는지.
    k_src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    check(k_src.index("run_kr_ticker_master_collector()") < k_src.index("run_kr_all_market_prices_collector()"),
          "전 종목 종가 수집은 전체 상장종목 목록 수집 뒤에 실행됨")
    check("except Exception as e:" in k_src.split("run_kr_all_market_prices_collector()")[-1][:200],
          "__main__ 에서 이 보조 수집도 try/except 로 감쌈(실패해도 앞 단계 결과는 그대로)")


def _fake_screener_data_json(rows, include_count=True, total=None):
    """
    페이지네이션/실패 시나리오 검증용 **합성** devalue 응답을 만듭니다.

    ⚠️ 디코더 자체의 정확성은 아래 `test_us_screener_devalue_decoder()`에서 **실제로 받은
    응답 원문**(tests/fixtures/us_screener_data_json_head.json)으로 검증합니다. 여기 합성
    응답은 "여러 페이지·실패·차단" 같은 실데이터로 만들 수 없는 흐름만 재현하기 위한 것이라,
    인덱스 계산 실수를 피하려고 값 공유(devalue 의 중복 제거)는 일부러 쓰지 않았습니다.

    rows: [(symbol, name, price), ...] — price 가 None 이면 '가격 없는 행'을 재현합니다.
    """
    schema = {"data": 1} if not include_count else {"count": 1, "data": 2}
    flat = [schema, len(rows) if total is None else total, []] if include_count else [schema, []]
    index_list = flat[2] if include_count else flat[1]
    for symbol, name, price in rows:
        base = len(flat)
        flat.append({"s": base + 1, "n": base + 2, "price": base + 3})
        flat.extend([symbol, name, price])
        index_list.append(base)
    return json.dumps({"type": "data", "nodes": [{"type": "data", "data": flat}]})


def test_us_screener_devalue_decoder():
    print("\n[4-3] 미국 스크리너 devalue 디코더 (2026-08-12, TASK_HISTORY #92 — 실제 응답 원문으로 검증)")
    import collector_us_stocks as U

    # ⚠️ 이 픽스처는 2026-08-12 stockanalysis.com 스크리너 데이터 엔드포인트
    # (`/stocks/screener/__data.json`)에서 실제로 받은 응답의 **앞부분을 그대로 잘라낸 것**입니다.
    # 값(티커/회사명/가격/시총/업종)은 한 글자도 손대지 않았고, 뒤쪽 5,600여 행과 화면 메타데이터
    # (업종 목록·컬럼 정의 등)만 잘라냈습니다. 그래서 `count` 는 실제 그대로 5607 인데 행은 7개뿐이고,
    # `country`/`dataPoints` 처럼 잘려나간 뒤쪽을 가리키는 인덱스는 None 으로 디코딩됩니다
    # — 이것도 "응답이 잘렸을 때 크래시하지 않고 결측 처리"를 확인하는 검증 항목입니다.
    fixture = (REPO_ROOT / "tests" / "fixtures" / "us_screener_data_json_head.json").read_text(encoding="utf-8")
    nodes = U.decode_sveltekit_data_json(fixture)
    check(len(nodes) == 2, "노드 2개(레이아웃 + 스크리너 페이지)를 전부 펼침")

    rows, total_count = U.extract_screener_rows(nodes)
    check(total_count == 5607,
          "소스가 알려준 전체 종목 수(count=5607)를 그대로 읽음 — 미국 상장 전 종목 규모")
    check(len(rows) == 7, "잘라낸 픽스처에 담긴 7개 행을 모두 찾음")

    by_symbol = {r["s"]: r for r in rows}
    check(by_symbol["NVDA"]["price"] == 217.5 and by_symbol["NVDA"]["n"] == "NVIDIA Corporation",
          "평평한 배열의 인덱스를 따라가 티커·회사명·현재가를 정확히 복원")
    check(by_symbol["GOOG"]["n"] == "Alphabet Inc.",
          "devalue 의 값 공유(GOOG 가 GOOGL 과 같은 회사명 인덱스를 가리킴)를 올바르게 되풀어냄 "
          "— 이걸 못 풀면 회사명이 숫자 23 으로 남습니다")
    check(by_symbol["AVGO"]["industry"] == "Semiconductors",
          "행을 건너뛴 값 공유(AVGO 업종이 NVDA 업종 인덱스를 가리킴)도 정확히 복원")
    check(nodes[1]["country"] is None and nodes[1]["dataPoints"] is None,
          "잘려나간 뒤쪽을 가리키는 인덱스는 크래시 대신 None(결측) — 응답이 잘려도 죽지 않음")

    stocks = U.normalize_screener_rows(rows)
    check([s["symbol"] for s in stocks] == ["NVDA", "AAPL", "GOOGL", "GOOG", "MSFT", "AMZN", "AVGO"],
          "시가총액 순서 그대로 티커 목록으로 정규화됨")
    check(set(stocks[0]) == {"symbol", "name", "price"},
          "가격 전용 파일 목적대로 티커·회사명·현재가 3개 필드만 남김(밸류에이션 없음)")

    # §0-1: 가격을 숫자로 읽을 수 없는 행은 0 으로 채우지 않고 버립니다.
    dirty = U.normalize_screener_rows([
        {"s": "GOODCO", "n": "정상", "price": 12.5},
        {"s": "NOPRICE", "n": "가격없음", "price": None},
        {"s": "ZERO", "n": "가격0", "price": 0},
        {"s": "", "n": "티커없음", "price": 5},
        {"s": "TEXT", "n": "가격이문자", "price": "N/A"},
    ])
    check([s["symbol"] for s in dirty] == ["GOODCO"],
          "가격이 없거나 0 이거나 숫자가 아닌 행은 버림(§0-1 — 0 으로 메우지 않음)")


def test_us_all_market_prices_collector():
    print("\n[4-4] 미국 전 종목 현재가 수집기 (2026-08-12, TASK_HISTORY #92 — 실제 함수 호출)")
    import collector_us_stocks as U
    import requests as real_requests
    from urllib.parse import urlparse, parse_qs

    class _FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    def _page_of(url):
        return int(parse_qs(urlparse(url).query).get("p", ["1"])[0])

    def _install(get_func):
        class _FakeRequestsModule:
            get = staticmethod(get_func)
            exceptions = real_requests.exceptions
        U.requests = _FakeRequestsModule()

    orig_requests = U.requests
    orig_sleep = U.time.sleep
    tmpdir = tempfile.mkdtemp()
    try:
        U.time.sleep = lambda s: None  # 재시도/페이지 간 딜레이는 로직 검증에 불필요

        # ── 시나리오 A: 2페이지가 계속 실패해도 건너뛰고 3페이지까지 이어서 수집 ──────────
        page_bodies = {
            1: _fake_screener_data_json(
                [("NVDA", "NVIDIA Corporation", 217.5), ("AAPL", "Apple Inc.", 304.91),
                 ("NOPRICE", "가격 없는 회사", None)],
                total=5),
            3: _fake_screener_data_json([("BRK.B", "Berkshire Hathaway Inc.", 516.38),
                                         ("EPD", "Enterprise Products Partners L.P.", 37.86)],
                                        total=5),
        }
        call_log = []

        def _get_a(url, headers=None, timeout=None):
            call_log.append(url)
            page = _page_of(url)
            if page in page_bodies:
                return _FakeResponse(page_bodies[page])
            return _FakeResponse("서버 오류 페이지(JSON 아님)", status_code=500)

        _install(_get_a)
        result_path = U.run_us_all_market_prices_collector(data_dir=tmpdir, max_pages=10)
        check(result_path is not None, "정상 응답이 하나라도 있으면 파일 경로를 반환")

        with open(result_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        by_symbol = {s["symbol"]: s for s in payload["stocks"]}
        check(set(by_symbol) == {"NVDA", "AAPL", "BRK.B", "EPD"},
              "1페이지 + 3페이지 종목이 모두 반영되고, 실패한 2페이지만 건너뜀")
        check(by_symbol["NVDA"]["price"] == 217.5 and by_symbol["BRK.B"]["name"].startswith("Berkshire"),
              "티커·회사명·현재가가 그대로 보존됨")
        check("price" in by_symbol["NVDA"] and "t_per" not in by_symbol["NVDA"],
              "밸류에이션 필드(PER 등)는 없음 — 가격 전용 목적")
        check(payload["metadata"]["count"] == 4 and payload["metadata"]["failed_page_count"] == 1,
              "metadata 에 실제 반영 건수와 건너뛴 페이지 수가 정직하게 기록됨")
        check(payload["metadata"]["source_reported_count"] == 5,
              "소스가 알려준 전체 종목 수도 함께 기록")
        check(payload["metadata"]["source_blocked"] is False, "차단 없이 끝난 회차로 기록")

        pages_called = [_page_of(u) for u in call_log]
        check(pages_called == [1, 2, 2, 2, 3],
              "2페이지는 재시도 3번 뒤 건너뛰고 3페이지로 이어서 진행, 소스가 알려준 전체 종목 수"
              "(5)에 도달해 4페이지는 아예 요청하지 않음")

        # ── 시나리오 B: 소스가 페이지 파라미터를 무시하고 매번 같은 전 종목을 주는 경우 ────
        # (2026-08-12 현재 stockanalysis.com 스크리너의 실제 동작 — 한 응답에 전 종목이 다 옵니다)
        same_body = _fake_screener_data_json(
            [("NVDA", "NVIDIA Corporation", 217.5), ("AAPL", "Apple Inc.", 304.91)],
            include_count=False)
        repeat_log = []

        def _get_b(url, headers=None, timeout=None):
            repeat_log.append(url)
            return _FakeResponse(same_body)

        _install(_get_b)
        tmp_b = tempfile.mkdtemp()
        path_b = U.run_us_all_market_prices_collector(data_dir=tmp_b, max_pages=50)
        check(len(repeat_log) == 2,
              "새로 추가되는 종목이 없으면 즉시 멈춤 — 같은 목록을 50페이지까지 반복 요청하지 않음")
        with open(path_b, "r", encoding="utf-8") as f:
            check(len(json.load(f)["stocks"]) == 2, "중복 티커는 한 번만 저장됨")
        shutil.rmtree(tmp_b, ignore_errors=True)

        # ── 시나리오 C: 차단(HTTP 429)은 재시도하지 않고 즉시 중단, 그때까지 받은 건 저장 ──
        block_log = []

        def _get_c(url, headers=None, timeout=None):
            block_log.append(url)
            if _page_of(url) == 1:
                return _FakeResponse(_fake_screener_data_json(
                    [("NVDA", "NVIDIA Corporation", 217.5)], include_count=False))
            return _FakeResponse("차단", status_code=429)

        _install(_get_c)
        tmp_c = tempfile.mkdtemp()
        path_c = U.run_us_all_market_prices_collector(data_dir=tmp_c, max_pages=50)
        check([_page_of(u) for u in block_log] == [1, 2],
              "차단당한 페이지는 재시도를 반복하지 않고 즉시 중단(§0-3-2)")
        with open(path_c, "r", encoding="utf-8") as f:
            blocked_payload = json.load(f)
        check(len(blocked_payload["stocks"]) == 1 and blocked_payload["metadata"]["source_blocked"] is True,
              "차단 전까지 받은 분량은 저장하되 '차단당했다'는 사실을 metadata 에 남김")
        shutil.rmtree(tmp_c, ignore_errors=True)

        # ── 시나리오 D: 처음부터 끝까지 실패하면 파일을 만들지 않음(기존 파일 보존) ───────
        _install(lambda url, headers=None, timeout=None: _FakeResponse("깨진 응답", status_code=500))
        tmp_d = tempfile.mkdtemp()
        broken_result = U.run_us_all_market_prices_collector(data_dir=tmp_d, max_pages=2)
        check(broken_result is None,
              "한 종목도 못 받으면 파일을 만들지 않고 조용히 None 반환(크래시 안 함)")
        check(not os.path.exists(os.path.join(tmp_d, "us_all_market_prices.json")),
              "빈 파일조차 만들지 않음 — 기존 파일이 있었다면 그대로 유지됨")
        shutil.rmtree(tmp_d, ignore_errors=True)
    finally:
        U.requests = orig_requests
        U.time.sleep = orig_sleep
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 배선 확인: 550종목 핵심 수집 '뒤에' 실행되고, try/except 로 감싸져 있는지.
    u_src = (REPO_ROOT / "collector_us_stocks.py").read_text(encoding="utf-8")
    collect_body = u_src.split("def cmd_collect(")[1].split("\ndef ")[0]
    check(collect_body.index("run_us_collector(") < collect_body.index("run_us_all_market_prices_collector()"),
          "전 종목 현재가 수집은 550종목 밸류에이션 수집 뒤에 실행됨")
    check("except Exception as e:" in collect_body.split("run_us_all_market_prices_collector()")[-1][:200],
          "try/except 로 감쌈(실패해도 550종목 수집 결과는 그대로)")
    check(collect_body.index('if not readiness["should_collect"]') < collect_body.index("run_us_all_market_prices_collector()"),
          "사전 점검(--skip-if-not-ready)에 걸린 실행에서는 아예 돌지 않음 — 장중 가격을 담지 "
          "않기 위한 §0-3-1(후행지표 전용) 방어")


def test_us_etf_screener_devalue_decoder():
    print("\n[4-5] 미국 ETF 스크리너 devalue 디코더 (2026-08-12, TASK_HISTORY #93 — 실제 응답 원문으로 검증)")
    import collector_us_stocks as U

    # ⚠️ 이 픽스처는 2026-08-12 stockanalysis.com **ETF** 스크리너 데이터 엔드포인트
    # (`/etf/screener/__data.json`)에서 실제로 받은 응답에서 잘라낸 것입니다. 값(티커/펀드명/
    # 자산군/순자산/가격/등락률/거래량/보유종목수)은 한 글자도 손대지 않았고, 뒤쪽 5,470여 행과
    # 화면 메타데이터만 잘라낸 뒤 닫는 괄호를 붙였습니다. 그래서 `count` 는 실제 그대로 5480 인데
    # 행은 7개뿐이고, 잘려나간 뒤쪽을 가리키는 인덱스(country/dataPoints/perPage)는 None 이 됩니다.
    fixture = (REPO_ROOT / "tests" / "fixtures" / "us_etf_screener_data_json_head.json").read_text(encoding="utf-8")
    nodes = U.decode_sveltekit_data_json(fixture)
    check(len(nodes) == 2, "주식 스크리너와 똑같이 노드 2개(레이아웃 + 스크리너 페이지)를 전부 펼침")

    rows, total_count = U.extract_screener_rows(nodes)
    check(total_count == 5480,
          "소스가 알려준 전체 ETF 수(count=5480)를 그대로 읽음 — '한 요청에 전 종목' 판정의 근거")
    check(len(rows) == 7, "잘라낸 픽스처에 담긴 7개 행을 모두 찾음")

    by_symbol = {r["s"]: r for r in rows}
    check(by_symbol["VOO"]["price"] == 691.59 and by_symbol["VOO"]["n"] == "Vanguard S&P 500 ETF",
          "ETF 행도 티커(s)·펀드명(n)·현재가(price) 키가 주식과 동일 — 별도 컬럼 매핑이 필요 없음")
    check(by_symbol["VUG"]["price"] == 86.885,
          "소수점 셋째 자리 가격(86.885)도 반올림 없이 그대로 복원")
    check(all(r.get("assetClass") == "Equity" for r in rows),
          "7개 행이 공유하는 자산군 값(devalue 의 인덱스 공유)을 전부 올바르게 되풀어냄")
    check(by_symbol["QQQ"]["holdings"] == 106 and by_symbol["SPY"]["aum"] == 783071884104,
          "ETF 전용 필드(보유종목수·순자산)도 구조상 정상 디코딩됨(다만 저장은 하지 않음)")
    check(nodes[1]["country"] is None and nodes[1]["dataPoints"] is None and nodes[1]["perPage"] is None,
          "잘려나간 뒤쪽을 가리키는 인덱스는 크래시 대신 None(결측)")

    etfs = U.normalize_screener_rows(rows)
    check([s["symbol"] for s in etfs] == ["VOO", "IVV", "SPY", "VTI", "QQQ", "VEA", "VUG"],
          "순자산 순서 그대로 티커 목록으로 정규화됨")
    check(set(etfs[0]) == {"symbol", "name", "price"},
          "가격 전용 파일 목적대로 3개 필드만 남김 — assetClass/aum/holdings 는 일부러 버림"
          "(주식 파일과 구조를 똑같이 유지)")


def test_us_all_market_etf_prices_collector():
    print("\n[4-6] 미국 ETF 현재가 수집기 (2026-08-12, TASK_HISTORY #93 — 실제 함수 호출)")
    import collector_us_stocks as U
    import requests as real_requests
    from utils.constants_us import US_ETF_SCREENER_DATA_JSON_URL, US_SCREENER_DATA_JSON_URL

    class _FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    fixture = (REPO_ROOT / "tests" / "fixtures" / "us_etf_screener_data_json_head.json").read_text(encoding="utf-8")

    orig_requests = U.requests
    orig_sleep = U.time.sleep
    try:
        U.time.sleep = lambda s: None

        # ── 시나리오 A: 실제 ETF 응답(픽스처)을 그대로 돌려주는 소스 ──────────────────────
        call_log = []

        def _get_a(url, headers=None, timeout=None):
            call_log.append(url)
            return _FakeResponse(fixture)

        class _FakeRequestsModule:
            get = staticmethod(_get_a)
            exceptions = real_requests.exceptions
        U.requests = _FakeRequestsModule()

        tmp_a = tempfile.mkdtemp()
        path_a = U.run_us_all_market_etf_prices_collector(data_dir=tmp_a, max_pages=50)
        check(all(u.startswith(US_ETF_SCREENER_DATA_JSON_URL) for u in call_log),
              "주식 스크리너가 아니라 **ETF 스크리너** 엔드포인트로 요청함")
        check(not any(u.startswith(US_SCREENER_DATA_JSON_URL + "?") or u == US_SCREENER_DATA_JSON_URL
                      for u in call_log),
              "주식 스크리너 주소는 단 한 번도 부르지 않음(수집기 두 개가 섞이지 않음)")
        check(len(call_log) == 2,
              "같은 목록이 다시 오면 즉시 멈춤 — 소스가 알려준 5480건에 못 미쳐도 무한 요청하지 않음")

        check(os.path.basename(path_a) == "us_all_etf_prices.json",
              "ETF는 주식과 **별도 파일**(us_all_etf_prices.json)로 저장됨")
        check(not os.path.exists(os.path.join(tmp_a, "us_all_market_prices.json")),
              "주식 파일(us_all_market_prices.json)은 건드리지 않음 — 한쪽 수집이 다른 쪽을 지우지 않는 구조")

        with open(path_a, "r", encoding="utf-8") as f:
            payload = json.load(f)
        by_symbol = {s["symbol"]: s for s in payload["stocks"]}
        check(set(by_symbol) == {"VOO", "IVV", "SPY", "VTI", "QQQ", "VEA", "VUG"},
              "실제 응답에 있던 ETF 7종이 전부 저장됨")
        check(by_symbol["VOO"]["price"] == 691.59 and by_symbol["VOO"]["name"] == "Vanguard S&P 500 ETF",
              "티커·펀드명·현재가가 그대로 보존됨")
        check("t_per" not in by_symbol["VOO"] and "aum" not in by_symbol["VOO"],
              "밸류에이션도, ETF 전용 필드(순자산 등)도 없음 — 가격 전용 목적")
        check(payload["metadata"]["source"] == US_ETF_SCREENER_DATA_JSON_URL,
              "metadata 의 소스 주소가 ETF 스크리너로 기록됨(파일만 보고도 출처를 알 수 있음)")
        check(payload["metadata"]["count"] == 7 and payload["metadata"]["source_reported_count"] == 5480,
              "실제 저장 건수와 소스가 알려준 전체 ETF 수가 각각 정직하게 기록됨")
        check(payload["metadata"]["source_blocked"] is False and payload["metadata"]["currency"] == "USD",
              "차단 없이 끝난 회차 + 통화는 USD")
        shutil.rmtree(tmp_a, ignore_errors=True)

        # ── 시나리오 B: 처음부터 끝까지 실패하면 파일을 만들지 않음(기존 파일 보존) ────────
        class _FakeBroken:
            get = staticmethod(lambda url, headers=None, timeout=None: _FakeResponse("깨진 응답", status_code=500))
            exceptions = real_requests.exceptions
        U.requests = _FakeBroken()
        tmp_b = tempfile.mkdtemp()
        broken = U.run_us_all_market_etf_prices_collector(data_dir=tmp_b, max_pages=2)
        check(broken is None and not os.path.exists(os.path.join(tmp_b, "us_all_etf_prices.json")),
              "한 건도 못 받으면 빈 파일조차 만들지 않고 조용히 None 반환(직전 파일 보존)")
        shutil.rmtree(tmp_b, ignore_errors=True)
    finally:
        U.requests = orig_requests
        U.time.sleep = orig_sleep

    # 배선 확인: 주식 현재가 수집 '뒤에', 각자의 try/except 로, 사전 점검 통과 후에만 실행.
    u_src = (REPO_ROOT / "collector_us_stocks.py").read_text(encoding="utf-8")
    collect_body = u_src.split("def cmd_collect(")[1].split("\ndef ")[0]
    check(collect_body.index("run_us_all_market_prices_collector()")
          < collect_body.index("run_us_all_market_etf_prices_collector()"),
          "ETF 현재가 수집은 주식 현재가 수집 뒤에 실행됨")
    check("except Exception as e:" in collect_body.split("run_us_all_market_etf_prices_collector()")[-1][:200],
          "ETF 수집도 자기 try/except 로 감싸짐(실패해도 앞 단계 결과는 그대로)")
    check(collect_body.index('if not readiness["should_collect"]')
          < collect_body.index("run_us_all_market_etf_prices_collector()"),
          "사전 점검(--skip-if-not-ready)에 걸린 실행에서는 아예 돌지 않음 — §0-3-1(후행지표 전용)")
    check(collect_body.count("try:") >= 2,
          "주식/ETF 가 하나의 try 에 묶여 있지 않음 — 한쪽이 죽어도 다른 쪽은 시도됨")


def main():
    print("=" * 70)
    print("📈 종목별 시계열 이력 · 다운로드 오프라인 검증")
    print("=" * 70)
    test_field_spec()
    test_row_from_real_snapshot()
    test_status_guard()
    test_collector_blocked_scenarios()
    test_kr_ticker_master_collector()
    test_kr_all_market_prices_collector()
    test_us_screener_devalue_decoder()
    test_us_all_market_prices_collector()
    test_us_etf_screener_devalue_decoder()
    test_us_all_market_etf_prices_collector()
    test_append_and_dedup()
    test_export_end_to_end()
    test_wiring()
    test_value_round_trip()

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 70)


if __name__ == "__main__":
    main()
