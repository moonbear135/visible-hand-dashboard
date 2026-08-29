"""
probe_indicator_universe_timing.py

「여기서부터는 신앙입니다」(보조지표 모듈) 착수 전 0단계 실측용 1회성 진단 스크립트.
TECHNICAL_INDICATOR_WORK_ORDER.md §7 "0단계"에서 확인하기로 한 것만 잽니다:

  ① 500종목을 돌리는 데 실제로 몇 분 걸리는가
  ② 네이버가 짧은 간격 요청을 막는가(연속 실패로 나타남)
  ③ 기간을 넉넉하게 늘려도(최대 400일 요청) 응답이 정말 즉시 오는가

⚠️ 이 스크립트는 데이터를 저장하거나 커밋하지 않습니다. 순수 진단용이며, 결과는
   GitHub Actions 로그에만 출력됩니다. 이 파일 자체는 착수가 결정된 뒤(2단계 이후)
   지워도 되는 1회성 도구입니다 — 실제 수집기는 별도로 만듭니다(§0-3-6).

실행: python probe_indicator_universe_timing.py [--limit 500] [--days 400] [--delay 0.5]
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timedelta

import FinanceDataReader as fdr


def load_top_n_codes(n):
    """
    data/kr_all_market_prices.json 은 네이버 '시가총액 순위 페이지'를 그대로 순서대로
    긁은 파일이라(메타데이터 source 필드 참고), 배열 순서 자체가 시가총액 내림차순으로
    보입니다 — 다만 이 파일에 시가총액 숫자 자체는 없어 순서만으로 추정하는 것이며,
    ETF도 섞여 있어 완전히 정확한 "주식 상위 N"은 아닙니다(진단용이라 허용, 실제 2단계
    수집기는 kr_ticker_master.json의 type=='STOCK'과 대조해 더 정확히 걸러야 합니다).

    ⚠️ 이 스크립트는 GitHub Actions 러너에 체크아웃된 로컬 파일을 그대로 읽습니다
       (원격 fetch 계층인 utils/data_source.py를 쓰지 않음) — 1회성 진단 스크립트라
       배포된 Render 인스턴스가 아니라 저장소 체크아웃 안에서만 실행되기 때문입니다.
    """
    with open("data/kr_all_market_prices.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    stocks = data.get("stocks", [])
    return [s["code"] for s in stocks[:n]]


def probe(codes, days, delay):
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    per_call_seconds = []
    failures = []
    bars_counts = []

    wall_start = time.time()

    for i, code in enumerate(codes, start=1):
        t0 = time.time()
        try:
            df = fdr.DataReader(code, start_str, end_str)
            elapsed = time.time() - t0
            per_call_seconds.append(elapsed)
            if df is None or df.empty or "Close" not in df.columns:
                failures.append((code, "빈 응답 또는 Close 컬럼 없음"))
            else:
                bars_counts.append(len(df))
        except Exception as e:
            elapsed = time.time() - t0
            per_call_seconds.append(elapsed)
            failures.append((code, f"{type(e).__name__}: {e}"))

        if i % 50 == 0 or i == len(codes):
            print(f"  진행 {i}/{len(codes)} ... 누적 {round(time.time() - wall_start, 1)}초", flush=True)

        time.sleep(delay)

    wall_elapsed = time.time() - wall_start
    return {
        "wall_elapsed_seconds": wall_elapsed,
        "n_requested": len(codes),
        "n_success": len(codes) - len(failures),
        "n_failed": len(failures),
        "failures": failures,
        "per_call_seconds": per_call_seconds,
        "bars_counts": bars_counts,
    }


def print_report(result, days):
    print("\n" + "=" * 70)
    print("0단계 실측 결과 — 「여기서부터는 신앙입니다」 보조지표 모듈")
    print("=" * 70)
    print(f"요청 기간: 최근 {days}일치 요청")
    print(f"총 소요 시간: {round(result['wall_elapsed_seconds'] / 60, 1)}분 ({round(result['wall_elapsed_seconds'], 1)}초)")
    print(f"요청 종목 수: {result['n_requested']}")
    print(f"성공: {result['n_success']} / 실패: {result['n_failed']}")

    if result["per_call_seconds"]:
        secs = result["per_call_seconds"]
        print(f"\n[호출 1건당 응답시간] 평균 {round(statistics.mean(secs), 3)}초 "
              f"/ 중앙값 {round(statistics.median(secs), 3)}초 "
              f"/ 최대 {round(max(secs), 3)}초")

    if result["bars_counts"]:
        bars = result["bars_counts"]
        print(f"[받아온 봉 수] 평균 {round(statistics.mean(bars))}봉 "
              f"/ 최소 {min(bars)}봉 / 최대 {max(bars)}봉")
        print("  → §3-1에서 예상한 대로, 요청 기간(days)과 무관하게 매번 종목당 "
              "가능한 전체 역사를 받아왔다면 최소/최대 차이가 종목의 실제 상장 기간 "
              "차이일 뿐, 우리가 지정한 기간과는 무관하게 나타나야 정상입니다.")

    if result["failures"]:
        print(f"\n[실패 {len(result['failures'])}건 — 앞 10개만 표시]")
        for code, reason in result["failures"][:10]:
            print(f"  {code}: {reason}")
        # 연속 실패가 후반부에 몰려있으면 = 네이버가 짧은 간격 요청을 막기 시작했다는 신호
        fail_codes = {c for c, _ in result["failures"]}
        print("\n  ⚠️ 실패가 뒤로 갈수록(뒷번호 종목일수록) 몰려있다면, 네이버가 짧은 "
              "간격의 반복 요청을 중간부터 막기 시작했다는 신호일 수 있습니다 — "
              "그렇다면 delay를 늘려서 다시 실측해보세요.")
    else:
        print("\n실패 0건 — 이번 실측 범위·간격에서는 네이버가 요청을 막지 않았습니다.")

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="보조지표 모듈 0단계 실측 진단 스크립트")
    parser.add_argument("--limit", type=int, default=500, help="테스트할 종목 수 (기본 500)")
    parser.add_argument("--days", type=int, default=400, help="요청할 과거 기간(일) (기본 400)")
    parser.add_argument("--delay", type=float, default=0.5, help="종목별 요청 사이 딜레이(초) (기본 0.5)")
    args = parser.parse_args()

    codes = load_top_n_codes(args.limit)
    print(f"대상 종목 {len(codes)}개 로드 완료 (요청: {args.limit})")

    if not codes:
        print("종목 목록을 못 읽었습니다 — data/kr_all_market_prices.json 확인 필요.")
        sys.exit(1)

    result = probe(codes, days=args.days, delay=args.delay)
    print_report(result, days=args.days)
