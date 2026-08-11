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


def main():
    print("=" * 70)
    print("📈 종목별 시계열 이력 · 다운로드 오프라인 검증")
    print("=" * 70)
    test_field_spec()
    test_row_from_real_snapshot()
    test_status_guard()
    test_collector_blocked_scenarios()
    test_kr_ticker_master_collector()
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
