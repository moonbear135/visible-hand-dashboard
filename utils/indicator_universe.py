"""
utils/indicator_universe.py
「여기서부터는 신앙입니다」(보조지표 모듈, 7번째 모듈) — 500종목 유니버스 관리.

TECHNICAL_INDICATOR_WORK_ORDER.md §2·§6-1 확정 사항을 그대로 코드로 옮긴 것입니다.
  - 코스피+코스닥 통합 시가총액 상위 500종목
  - 리밸런싱은 3개월(분기) 단위
  - 리밸런싱으로 500위 밖으로 밀린 종목도 최소 1년(365일)은 계속 추적

코스피 PEGY 200종목의 히스테리시스 버퍼(`_load_previously_tracked_codes()`,
`is_visible=False`로 계속 수집만 하고 화면엔 숨김)와 정확히 같은 패턴입니다
— 새로 설계하지 않고 그 패턴을 재사용합니다(§0-3-10).

streamlit/NiceGUI 어느 화면 프레임워크도 import하지 않습니다(오프라인 단위테스트 가능).
"""

from datetime import datetime, timedelta

REBALANCE_INTERVAL_DAYS = 90   # 3개월(분기) — 정확한 달력월 대신 일수로 단순화(§0-3-10 YAGNI)
RETENTION_DAYS = 365           # 이탈 종목도 이 기간까지는 계속 추적


def _parse_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d")


def empty_universe():
    """유니버스 파일이 아직 없을 때의 초기 골격."""
    return {"last_rebalance_date": None, "members": {}}


def select_top_n_stock_codes(price_entries, ticker_types, n=500):
    """
    price_entries: data/kr_all_market_prices.json 의 stocks 배열
                    (네이버 시가총액 순위 페이지 순서를 그대로 보존한 것 — 배열 순서가
                    시가총액 내림차순으로 간주됩니다. TECHNICAL_INDICATOR_WORK_ORDER.md §7
                    0단계 실측에서 이 전제로 만든 진단 스크립트가 정상 동작한 것으로
                    간접 확인됨).
    ticker_types: {code: "STOCK"|"ETF"|...} — data/kr_ticker_master.json 에서 만든 매핑.
                  ETF를 걸러내는 데 씁니다(kr_all_market_prices.json 자체에는 종목 구분이
                  없어 이 매핑 없이는 ETF가 섞여 들어갑니다).
    반환: 시가총액 순서를 보존한 종목코드 리스트, 최대 n개(주식만).
    """
    codes = []
    for entry in price_entries:
        code = entry.get("code")
        if not code:
            continue
        if ticker_types.get(code) != "STOCK":
            continue
        codes.append(code)
        if len(codes) >= n:
            break
    return codes


def rebalance_if_due(universe, today_str, top_candidates, interval_days=REBALANCE_INTERVAL_DAYS):
    """
    리밸런싱이 필요한 날(마지막 리밸런싱으로부터 interval_days 이상 지났거나, 아예 처음)에만
    top 500 목록을 다시 산정합니다. 아닌 날은 기존 멤버십을 그대로 둡니다(매일 흔들리지 않게).

    반환: (새 universe dict, rebalanced: bool)
    """
    members = dict(universe.get("members", {}))
    last_date = universe.get("last_rebalance_date")

    due = last_date is None
    if not due and last_date is not None:
        due = (_parse_date(today_str) - _parse_date(last_date)).days >= interval_days

    if not due:
        return universe, False

    candidate_set = set(top_candidates)

    # 새로 들어온 종목: 신규 등록(join)
    for code in top_candidates:
        if code not in members:
            members[code] = {"joined_date": today_str, "left_date": None, "is_visible": True}
        else:
            # 이미 있던 종목이 다시 top500에 들어왔으면 재노출(재편입) — 이탈 기록만 지움
            members[code]["is_visible"] = True
            members[code]["left_date"] = None

    # 기존에 visible=True 였는데 이번엔 top500에서 빠진 종목: 이탈 처리(추적은 계속)
    for code, info in members.items():
        if info.get("is_visible") and code not in candidate_set:
            info["is_visible"] = False
            info["left_date"] = today_str

    new_universe = {"last_rebalance_date": today_str, "members": members}
    return new_universe, True


def prune_expired_members(universe, today_str, retention_days=RETENTION_DAYS):
    """
    이탈(left_date)한 지 retention_days를 넘긴 종목은 더 이상 추적하지 않고 완전히 제거합니다.
    (계속 늘어나기만 하면 유니버스 파일이 무한정 커지므로, 1년이 지난 뒤에는 놓아줍니다 —
    §6-1에서 오너가 확정한 "1년" 그대로.)
    """
    members = {}
    for code, info in universe.get("members", {}).items():
        left_date = info.get("left_date")
        if left_date is not None:
            age_days = (_parse_date(today_str) - _parse_date(left_date)).days
            if age_days > retention_days:
                continue  # 제거 — 지어내지 않고 그냥 추적을 놓는 것뿐, 과거 이력(CSV)은 안 지움
        members[code] = info
    return {"last_rebalance_date": universe.get("last_rebalance_date"), "members": members}


def get_tracked_codes(universe):
    """오늘 데이터를 수집해야 할 전체 종목코드(화면 노출 500 + 1년 이내 이탈 버퍼)."""
    return list(universe.get("members", {}).keys())


def get_visible_codes(universe):
    """화면에 실제로 노출할 종목코드(현재 top 500)만."""
    return [code for code, info in universe.get("members", {}).items() if info.get("is_visible")]


def update_universe_for_today(universe, today_str, top_candidates,
                                interval_days=REBALANCE_INTERVAL_DAYS,
                                retention_days=RETENTION_DAYS):
    """
    ✅ 수집기가 매일 부르는 단일 진입점. 리밸런싱 필요 여부 판단 → (필요시) 재산정 →
    1년 초과 이탈 종목 정리, 순서로 처리합니다.

    반환: (새 universe, {"rebalanced": bool, "tracked_count": int, "visible_count": int})
    """
    universe, rebalanced = rebalance_if_due(universe, today_str, top_candidates, interval_days)
    universe = prune_expired_members(universe, today_str, retention_days)
    return universe, {
        "rebalanced": rebalanced,
        "tracked_count": len(get_tracked_codes(universe)),
        "visible_count": len(get_visible_codes(universe)),
    }
