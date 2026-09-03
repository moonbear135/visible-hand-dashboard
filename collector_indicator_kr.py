"""
collector_indicator_kr.py
「여기서부터는 신앙입니다」(보조지표 모듈, 7번째 모듈) — 일간 수집기.

TECHNICAL_INDICATOR_WORK_ORDER.md(검토 완료)에서 확정된 것만 그대로 구현합니다:
  - 코스피+코스닥 통합 시가총액 상위 500종목 (분기 리밸런싱 + 이탈 종목 1년 추적)
  - 종가만 사용, RSI·MACD·볼린저밴드 + 결정론적 종합판정 (utils/indicators.py, AI 미사용)
  - raw(FDR 원본 시계열)는 저장하지 않고 매번 재조회 — 가공 결과값만 매일 누적(§6-2 확정)
  - 종목 하나의 실패가 전체 배치를 막지 않음(§5-3)
  - 가짜 데이터 절대 금지 — 산출 불가한 지표는 None으로 남기고 사유를 함께 기록(§0-1)

⚠️ 독립 수집기입니다 — collector_kospi200.py 를 건드리지 않습니다(§0-3-6, 0단계 실측
   결과 이 모듈만으로 약 13분이 걸려 기존 배치에 얹으면 20~30분이 35~45분으로 늘어나므로
   §7-1 git push 충돌 창을 넓히지 않기 위해 별도 워크플로우로 돌립니다).

⚠️ §0-3-2(외부 서버 매너): 종목별 요청 사이에 INDICATOR_REQUEST_DELAY_SECONDS 만큼
   쉽니다. 이 값·INDICATOR_FETCH_DAYS 는 0단계 실측 결과를 근거로 utils/constants.py에
   단일 출처로 있습니다.
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta

import FinanceDataReader as fdr

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

from utils import stock_history
from utils import data_sanity
from utils.indicators import calculate_rsi, calculate_macd, calculate_bollinger, combine_verdict
from utils.indicator_universe import update_universe_for_today, select_top_n_stock_codes, get_tracked_codes
from utils.constants import INDICATOR_FETCH_DAYS, INDICATOR_REQUEST_DELAY_SECONDS


def _now_kst():
    # collector_kospi200.py / scrape_daily.py 와 같은 관례 (datetime.now()는 UTC를 반환)
    return datetime.now(KST) if KST else datetime.now()


def _repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def _data_path(filename):
    return os.path.join(_repo_root(), "data", filename)


UNIVERSE_PATH = _data_path("indicator_universe_kr.json")
LATEST_SNAPSHOT_PATH = _data_path("indicator_kr_latest.json")
PRICE_LIST_PATH = _data_path("kr_all_market_prices.json")
TICKER_MASTER_PATH = _data_path("kr_ticker_master.json")


# =============================================================================
# 1. 입력 로드
# =============================================================================
def load_price_entries_and_names(path=None):
    """
    반환: (price_entries, name_map)
      price_entries: kr_all_market_prices.json 의 stocks 배열(시가총액 순서 보존)
      name_map: {code: name}
    파일이 없거나 깨졌으면 빈 값 반환(지어내지 않음) — 호출부가 "오늘 스킵"을 판단합니다.
    """
    # ⚠️ path=PRICE_LIST_PATH를 기본값으로 두면 함수 정의 시점에 값이 고정되어버려
    #    (파이썬 mutable-default-argument 함정) 나중에 모듈 전역을 바꿔도(테스트의
    #    monkeypatch 등) 반영되지 않습니다 — 그래서 None으로 받고 여기서 매번 새로 읽습니다.
    if path is None:
        path = PRICE_LIST_PATH
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ {path} 를 읽지 못했습니다: {e}")
        return [], {}
    stocks = data.get("stocks", [])
    name_map = {s["code"]: s.get("name", "") for s in stocks if s.get("code")}
    return stocks, name_map


def get_price_list_generated_date(path=None):
    """
    data/kr_all_market_prices.json 의 metadata.generated_at 앞 10글자(YYYY-MM-DD)만
    돌려줍니다. 오늘 날짜와 다르면 유니버스 후보 목록이 며칠 지난 것일 수 있다는 뜻이라
    run()에서 경고만 찍습니다(차단하지는 않음 — 지표 계산 자체는 FDR에서 매번 새로
    받으므로 이 파일이 며칠 지나도 안전하고, 영향은 분기 리밸런싱 후보 목록의 신선도뿐).
    못 읽으면 None(경고를 못 찍을 뿐, 별도 에러로 취급하지 않음).
    """
    if path is None:
        path = PRICE_LIST_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        generated_at = data.get("metadata", {}).get("generated_at", "")
        return generated_at[:10] if generated_at else None
    except Exception:
        return None


def load_ticker_types(path=None):
    """반환: {code: "STOCK"|"ETF"|...}. 파일이 없으면 빈 dict(→ 전부 걸러짐, 안전한 쪽으로)."""
    if path is None:
        path = TICKER_MASTER_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ {path} 를 읽지 못했습니다: {e}")
        return {}
    return {s["code"]: s.get("type") for s in data.get("stocks", []) if s.get("code")}


def load_universe(path=None):
    if path is None:
        path = UNIVERSE_PATH
    if not os.path.exists(path):
        return {"last_rebalance_date": None, "members": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ {path} 를 읽지 못했습니다: {e} — 빈 유니버스로 다시 시작합니다.")
        return {"last_rebalance_date": None, "members": {}}


def save_universe(universe, path=None):
    if path is None:
        path = UNIVERSE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)


# =============================================================================
# 2. 종목 1개 처리
# =============================================================================
def fetch_and_calculate(code, days=INDICATOR_FETCH_DAYS):
    """
    FDR에서 종가 시계열을 받아 3개 지표 + 종합판정을 계산합니다.
    ⚠️ raw 시계열 자체는 반환하지 않고 버립니다 — 저장 안 함(§6-2 확정, 매번 재조회).
    실패하면 예외를 그대로 올립니다 — 호출부가 종목 단위로 감쌉니다(§5-3).
    """
    end_dt = _now_kst()
    start_dt = end_dt - timedelta(days=days)
    df = fdr.DataReader(code, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    if df is None or df.empty or "Close" not in df.columns:
        raise ValueError("빈 응답 또는 Close 컬럼 없음")
    closes = df["Close"]

    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    bb = calculate_bollinger(closes)
    verdict = combine_verdict(rsi, macd, bb)
    last_close = float(closes.iloc[-1]) if len(closes) else None
    return rsi, macd, bb, verdict, last_close


def build_history_row(code, name, date_str, rsi, macd, bb, verdict):
    """utils/stock_history.py 의 INDICATOR_HISTORY_FIELDS 키에 맞춰 레코드를 만듭니다."""
    reasons = []
    for label, result in (("RSI", rsi), ("MACD", macd), ("Bollinger", bb)):
        if not result.get("available"):
            reasons.append(f"{label}:{result.get('reason')}")

    warmup_insufficient = any(
        r.get("available") and r.get("warmup_insufficient") for r in (rsi, macd, bb)
    )
    # 세 지표는 같은 종가 시리즈로 계산되므로 bars_used는 사실상 동일합니다 —
    # 산출 가능한 것 중 아무거나(첫 번째로 available한 것)에서 가져옵니다.
    bars_used = None
    for r in (rsi, macd, bb):
        if r.get("available"):
            bars_used = r.get("bars_used")
            break

    return {
        "date": date_str,
        "code": code,
        "name": name,
        "rsi": rsi.get("rsi"),
        "rsi_signal": rsi.get("signal"),
        "macd": macd.get("macd"),
        "macd_signal_line": macd.get("signal_line"),
        "macd_histogram": macd.get("histogram"),
        "macd_cross": macd.get("cross"),
        "bb_upper": bb.get("upper"),
        "bb_lower": bb.get("lower"),
        "bb_mid": bb.get("mid"),
        "bb_percent_b": bb.get("percent_b"),
        "bb_position": bb.get("position"),
        "verdict_score": verdict.get("score"),
        "verdict_label": verdict.get("label"),
        "bars_used": bars_used,
        "warmup_insufficient": warmup_insufficient,
        "unavailable_reasons": "; ".join(reasons) if reasons else None,
    }


def cross_check_last_close(code, last_close, today_price_map):
    """
    §5-1(가짜 데이터 금지) 교차검증: 오늘 네이버 시가총액 페이지가 이미 갖고 있는 당일가와
    FDR 시계열의 마지막 종가를 대조합니다. 추가 네트워크 요청 0건(둘 다 이미 갖고 있는 값).

    ⚠️ 1차 구현 범위: 콘솔 로그 + 요약 카운트만 남기고 값은 절대 고치지 않습니다
       (배당 모듈의 cross_source_notes와 같은 정신). CSV에 종목별 불일치 컬럼을 영구히
       남기는 건 후속 과제로 남깁니다(TECHNICAL_INDICATOR_WORK_ORDER.md 참고).
    반환: True(불일치) / False(일치) / None(대조 불가 — 네이버 쪽에 그 종목 가격이 없음).
    """
    naver_price = today_price_map.get(code)
    if naver_price is None or last_close is None or last_close == 0:
        return None
    diff_pct = abs(naver_price - last_close) / last_close * 100.0
    if diff_pct > 5.0:  # 5%는 관례적 여유 임계치 — 휴장·수정주가 소급조정 등으로 흔들릴 수 있음
        print(f"  ⚠️ 교차검증 불일치: {code} 네이버 {naver_price} vs FDR 종가 {last_close} "
              f"(차이 {round(diff_pct, 2)}%)")
        return True
    return False


# =============================================================================
# 3. 무인 자동화 사전 점검 — "오늘 이미 SUCCESS 로 수집을 마쳤으면 건너뛰기" (2026-09-04 신설)
#
# 배경: GitHub Actions 자체 schedule cron 이 몇 시간씩 지연되는 일이 잦아(TASK_HISTORY #154)
# Cloudflare Worker(cloudflare_worker.js)가 17:05 KST 에 workflow_dispatch 로 indicator_kr.yml
# 을 한 번 더 깨웁니다. Worker 는 "오늘 실행 기록이 있으면 안 쏜다"고 확인하지만, GitHub 자체
# cron 이 그 **뒤에** 늦게 발동하는 경우는 막을 수 없어 같은 날 두 번 수집됩니다.
# 실측(`git log --date=iso -- data/indicator_kr_latest.json`, 스냅샷 generated_at KST):
#   2026-09-02  17:19 KST / 21:39 KST  → 하루 두 번 (둘 다 성공 500/실패 0)
#   2026-09-03  17:17 KST / 21:38 KST  → 하루 두 번 (둘 다 성공 500/실패 0)
# collector_us_stocks.py 의 `--skip-if-not-ready`(evaluate_collection_readiness) /
# collector_kospi200.py 의 evaluate_kospi200_collection_readiness() 와 같은 취지입니다.
# indicator_kr.yml 의 schedule: 자체는 안전망으로 그대로 둡니다.
#
# 판정 규칙("모르면 수집한다" — 건너뛰면 하루가 통째로 비고, 수집하면 최악이라도 중복 1회):
#   · 스냅샷 파일이 없거나 깨짐                       → 수집
#   · status 가 SUCCESS 가 아님(DEGRADED, 또는 이 필드가 없는 옛 형식) → 수집
#   · date == 오늘(KST)                               → 건너뜀
#   · 그 외(어제 이전의 SUCCESS)                       → 수집
# 날짜 비교는 KST 입니다 — 스냅샷의 date 가 today_str = _now_kst() 로 찍히기 때문입니다.
# =============================================================================
def read_snapshot_completion(path=None):
    """
    기존 스냅샷(indicator_kr_latest.json)에서 "어느 날짜를, 어떤 status 로 저장했는가"를 읽습니다.

    반환: (completed_date, status, generated_at)
      completed_date: status 가 SUCCESS 일 때만 스냅샷의 date(YYYY-MM-DD, KST). 파일이 없거나
                      깨졌거나 SUCCESS 가 아니면 None (모르면 수집하는 쪽이 안전).
    """
    if path is None:
        path = LATEST_SNAPSHOT_PATH
    if not os.path.exists(path):
        return None, None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception as e:
        print(f"  ⚠️ {path} 를 읽지 못했습니다({e}) — 이미 수집됐는지 알 수 없어 수집을 진행합니다.")
        return None, None, None
    status = data.get("status")
    date_str = data.get("date")
    generated_at = data.get("generated_at")
    if status != "SUCCESS" or not isinstance(date_str, str) or len(date_str) < 10:
        return None, status, generated_at
    return date_str[:10], status, generated_at


def evaluate_collection_readiness(snapshot_path=None, now_kst=None):
    """
    "지금 이 실행이 실제로 수집을 해야 하는가"를 판정합니다(무인 자동화 전용).

    반환: dict — should_collect / reason / target_date / snapshot_date / snapshot_status /
          snapshot_generated_at (collector_kospi200 의 같은 이름 키와 대응)
    """
    now = now_kst or _now_kst()
    target = now.strftime("%Y-%m-%d")
    completed_date, status, generated_at = read_snapshot_completion(snapshot_path)

    if completed_date == target:
        should, reason = False, (
            f"{target} 자 수집이 이미 status=SUCCESS 로 완료되어 스냅샷에 들어있습니다"
            f" (생성 {generated_at} KST)"
        )
    elif status is not None and status != "SUCCESS":
        should, reason = True, (
            f"기존 스냅샷이 status={status} 입니다(생성 {generated_at} KST) — "
            f"성공으로 치지 않고 다시 수집합니다"
        )
    elif completed_date is None:
        should, reason = True, (
            "기존 스냅샷이 없거나 읽을 수 없거나 status 필드가 없는 옛 형식입니다 — 수집을 진행합니다"
        )
    else:
        should, reason = True, (
            f"기존 스냅샷은 {completed_date} 자(status=SUCCESS)이고 오늘은 {target} 입니다 — "
            f"수집을 진행합니다"
        )

    return {
        "should_collect": should,
        "reason": reason,
        "target_date": target,
        "snapshot_date": completed_date,
        "snapshot_status": status,
        "snapshot_generated_at": generated_at,
    }


# =============================================================================
# 4. 메인
# =============================================================================
def run(limit=500, days=INDICATOR_FETCH_DAYS, delay=INDICATOR_REQUEST_DELAY_SECONDS):
    today_str = _now_kst().strftime("%Y-%m-%d")
    print(f"[{_now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST] 보조지표 모듈 수집 시작 (대상 {limit}종목)")

    generated_date = get_price_list_generated_date()
    if generated_date and generated_date != today_str:
        print(f"  ⚠️ data/kr_all_market_prices.json 이 {generated_date}자 스냅샷입니다(오늘 "
              f"{today_str}과 다름) — 지표 계산 자체는 FDR에서 매번 새로 받으므로 영향 없지만, "
              f"유니버스 후보 목록·교차검증 기준가가 며칠 지난 것일 수 있습니다.")

    price_entries, name_map = load_price_entries_and_names()
    if not price_entries:
        print("🚨 data/kr_all_market_prices.json 을 읽을 수 없어 오늘은 건너뜁니다 "
              "(가짜 유니버스로 대체하지 않음, §0-1).")
        return

    ticker_types = load_ticker_types()
    if not ticker_types:
        print("🚨 data/kr_ticker_master.json 을 읽을 수 없어 ETF를 걸러낼 수 없습니다 — "
              "오늘은 건너뜁니다(잘못된 유니버스로 진행하지 않음).")
        return

    top_candidates = select_top_n_stock_codes(price_entries, ticker_types, n=limit)
    universe = load_universe()
    universe, info = update_universe_for_today(universe, today_str, top_candidates)
    print(f"  유니버스: 추적 {info['tracked_count']}종목(그중 화면 노출 {info['visible_count']}) "
          f"— 리밸런싱 {'실행됨' if info['rebalanced'] else '해당 없음(주기 미도래)'}")

    today_price_map = {s["code"]: s.get("price") for s in price_entries}
    tracked_codes = get_tracked_codes(universe)

    rows = []
    failures = []
    cross_mismatches = 0

    for i, code in enumerate(tracked_codes, start=1):
        name = name_map.get(code, "")
        try:
            rsi, macd, bb, verdict, last_close = fetch_and_calculate(code, days=days)
            row = build_history_row(code, name, today_str, rsi, macd, bb, verdict)
            rows.append(row)

            mismatch = cross_check_last_close(code, last_close, today_price_map)
            if mismatch:
                cross_mismatches += 1
        except Exception as e:
            failures.append((code, f"{type(e).__name__}: {e}"))
            print(f"  [실패] {code}({name}): {e}")

        if i % 50 == 0 or i == len(tracked_codes):
            print(f"  진행 {i}/{len(tracked_codes)}", flush=True)

        time.sleep(delay)

    save_universe(universe)

    if not rows:
        print("🚨 성공한 종목이 0건이라 이력에 아무것도 기록하지 않습니다.")
        return

    history_path = stock_history.stock_history_path(stock_history.INDICATOR_HISTORY_FILENAME)
    result = stock_history.append_daily_history(
        history_path, rows, today_str, stock_history.INDICATOR_HISTORY_FIELDS
    )
    # ⚠️ append_daily_history()는 {"row_count","replaced","total_rows"}만 돌려줍니다
    #    ("reason" 키는 record_daily_history()에만 있음 — 2026-08-25 실제 실행에서
    #    KeyError로 잡힌 버그, §5-4 스파게티 코드 방지 원칙대로 여기서 바로 고침).
    replaced_note = f" (같은 날짜 기존 {result['replaced']}행 교체)" if result["replaced"] else ""
    print(f"  이력 기록: {today_str} 기준 {result['row_count']}종목 기록{replaced_note} "
          f"/ 파일 총 {result['total_rows']}행")

    # 2026-09-04 신설: 무인 자동화 사전 점검(evaluate_collection_readiness)이 "오늘 이미 잘
    # 수집됐는가"를 판정할 때 읽는 status. 실패 0건일 때만 SUCCESS, 하나라도 실패하면 DEGRADED.
    # 코스피(0.85)·미국(0.90) 같은 비율 임계값을 따로 두지 않은 이유 — 이 모듈의 실측
    # (2026-08-26~09-03, 저장소에 커밋된 스냅샷 10회)이 전부 성공 500/실패 0 이라 "몇 %까지가
    # 정상"이라는 근거 데이터가 없고(§0-1 지어내지 않기), 실패가 1건이라도 있으면 그날의 두 번째
    # 트리거가 재시도하는 편이 안전합니다(같은 날짜 행은 append_daily_history 가 교체하므로
    # 재실행은 멱등). 성공 0건이면 위에서 이미 return 해 스냅샷 자체를 쓰지 않습니다.
    status = "SUCCESS" if not failures else "DEGRADED"
    with open(LATEST_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": _now_kst().strftime("%Y-%m-%d %H:%M"),
            "date": today_str,
            "status": status,
            "universe_tracked_count": info["tracked_count"],
            "universe_visible_count": info["visible_count"],
            "success_count": len(rows),
            "failed_count": len(failures),
            "stocks": rows,
        }, f, ensure_ascii=False, indent=2)

    # ── 수집 결과 산티체크 (2026-08-30 신설, utils/data_sanity.py) ─────────────────
    # 위 저장(이력 CSV + 최신 스냅샷)이 전부 끝난 뒤에만 돕니다. 값을 고치지 않고 판정만
    # 해서 data/indicator_kr_sanity.json 에 남깁니다(§0-1).
    # 핵심 컬럼 rsi·bb_mid: 2026-08-29 자 스냅샷 실측 결측 둘 다 0.0%(500행 중 0건).
    # verdict_score 는 81%가 0(중립)이라 넣지 않았습니다 — 넣었으면 매일 울립니다.
    # 중앙값 급변 검사(level_fields)는 bb_mid 에만 겁니다: bb_mid 는 20일 이동평균이라
    # 가격 수준을 그대로 반영해 단위 오류에 민감한 반면, rsi 는 0~100 으로 갇힌
    # 오실레이터라 진짜 폭락장에서 시장 전체 중앙값이 반토막 날 수 있어 "시장이 움직인 것"을
    # "데이터가 깨진 것"으로 오해하게 만듭니다.
    data_sanity.check_dataset(
        "indicator_kr", rows, ("rsi", "bb_mid"),
        target_date=today_str,
        level_fields=("bb_mid",),
        # 상태 파일은 최신 스냅샷과 같은 디렉터리에 둡니다 — 테스트가
        # LATEST_SNAPSHOT_PATH 를 임시 폴더로 바꿔치우면 상태 파일도 함께 따라갑니다.
        data_dir=os.path.dirname(LATEST_SNAPSHOT_PATH),
    )

    print(f"[{_now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST] 완료 — 성공 {len(rows)} / 실패 {len(failures)} "
          f"/ 교차검증 불일치 {cross_mismatches}건")
    if failures:
        print(f"  실패 종목(최대 10개 표시): {failures[:10]}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="보조지표 모듈 일간 수집기")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--days", type=int, default=INDICATOR_FETCH_DAYS)
    parser.add_argument("--delay", type=float, default=INDICATOR_REQUEST_DELAY_SECONDS)
    # 2026-09-04: 무인 자동화(GitHub Actions)에서만 켜는 사전 점검. 로컬에서 손으로 돌릴 때는
    # 이 옵션을 주지 않으므로 언제나 그대로 수집합니다(같은 날 재수집도 막지 않음).
    # 플래그 이름·동작은 collector_us_stocks.py / collector_kospi200.py 와 맞췄습니다.
    parser.add_argument("--skip-if-not-ready", action="store_true",
                        help="무인 자동화(GitHub Actions) 전용. 오늘(KST) 자 스냅샷이 이미 "
                             "status=SUCCESS(실패 0건)로 저장돼 있으면 아무것도 하지 않고 정상 "
                             "종료(exit 0)합니다. 실패가 있던 날(DEGRADED)은 성공으로 치지 않고 "
                             "다시 수집합니다. GitHub 자체 cron 과 Cloudflare Worker 의 "
                             "workflow_dispatch 가 같은 날 둘 다 발동해도 실제 수집은 하루 한 번만 "
                             "일어나게 하는 방어 장치입니다.")
    args = parser.parse_args(argv)
    if args.skip_if_not_ready:
        readiness = evaluate_collection_readiness()
        print("=" * 70)
        print("[무인 자동화 사전 점검] --skip-if-not-ready")
        print(f"  현재 KST              : {_now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  이번에 담길 날짜      : {readiness['target_date']}")
        print(f"  스냅샷 status         : {readiness['snapshot_status'] or '(없음)'}")
        print(f"  스냅샷 생성 시각      : {readiness['snapshot_generated_at'] or '(없음)'} KST")
        print(f"  판정                  : {readiness['reason']}")
        print("=" * 70)
        if not readiness["should_collect"]:
            print("⏭️  이번 실행은 아무것도 하지 않고 정상 종료합니다 (오류 아님).")
            print("   GitHub 자체 cron 과 Cloudflare Worker 가 같은 날 둘 다 트리거해도,")
            print("   실제 수집은 이 점검 덕분에 하루 한 번만 일어납니다.")
            return False
    run(limit=args.limit, days=args.days, delay=args.delay)
    return True


if __name__ == "__main__":
    main()
