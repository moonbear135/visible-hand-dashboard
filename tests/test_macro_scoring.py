# tests/test_macro_scoring.py
"""
🛡️ 매크로(시장 위험 점수) 실측 지표 정규화 오프라인 검증 (네트워크 불필요)

대상: utils/macro_scoring.py 의 실측 지표 정규화 함수들
      (measured_downside_risk / compute_population_stats /
       rolling_return_population / net_flow_population)

⚠️ 왜 이 파일이 생겼나 (2026-08-10, TASK #68)
   `KOSPI_5D_Return`(코스피 5일 수익률)과 `Stock_Net_Sell`(3주체 순매수 금액)은 이미 매일
   실제로 측정하고 있는 값인데도, 나머지 12개 추정 프록시와 똑같은 임의 선형식
   (`0.5 - 2.5×수익률`, `0.5 ± 0.3`)에 들어가 **크기 정보가 버려지고 있었습니다.**
   특히 순매수는 부호만 반영돼 "1천억 순매도"와 "3조 순매도"가 완전히 동점이었습니다.
   이 테스트는 그 버그가 되살아나지 않도록 **크기(magnitude)가 점수에 반영되는지**를 못박습니다.

여기 쓰는 데이터는 두 종류뿐입니다.
  ① 합성 시나리오 (폭락/급등, 소액/거액 순매도 — 실데이터로는 원하는 대비를 만들 수 없음)
  ② 저장소의 **실제 스냅샷** market_history.csv (실데이터 스팟체크)

실행: python tests/test_macro_scoring.py
"""
import io
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).parent.parent))

from utils.macro_scoring import (  # noqa: E402
    MEASURED_WINSOR_Z,
    NET_FLOW_MIN_SAMPLE,
    RETURN_POP_MIN_SAMPLE,
    compute_population_stats,
    measured_downside_risk,
    net_flow_population,
    rolling_return_population,
)

REPO_ROOT = Path(__file__).parent.parent
FAILURES = []


def check(cond, label):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        FAILURES.append(label)


def _in_unit_range(v):
    return v is not None and 0.0 <= v <= 1.0


# 합성 5일 수익률 분포: 평균 0%, 표준편차 2% (실제 코스피 5일 수익률의 대략적 스케일)
FAKE_RET_POP = (0.0, 0.02)
# 합성 외국인 순매수 분포: 평균 0억원, 표준편차 5,000억원
FAKE_FLOW_POP = (0.0, 5000.0)


def test_direction_kospi_5d():
    print("\n[1] KOSPI 5일 수익률 — 많이 빠질수록 위험 점수가 높아지는가 (방향성)")
    crash = measured_downside_risk(-0.05, FAKE_RET_POP)   # 5일간 -5%
    dip = measured_downside_risk(-0.01, FAKE_RET_POP)     # 5일간 -1%
    flat = measured_downside_risk(0.0, FAKE_RET_POP)      # 5일간 보합
    rally = measured_downside_risk(+0.04, FAKE_RET_POP)   # 5일간 +4%

    check(crash > dip > flat > rally, f"폭락 > 소폭하락 > 보합 > 급등 (실제: {crash} > {dip} > {flat} > {rally})")
    check(abs(flat - 0.5) < 1e-9, f"평균과 같은 수익률은 정확히 중립 0.5 (실제: {flat})")
    check(all(_in_unit_range(v) for v in (crash, dip, flat, rally)), "네 시나리오 모두 [0, 1] 범위")

    # 예전 버그(부호만 반영)를 못박는 검증: 부호가 같아도 크기가 다르면 점수가 달라야 한다.
    check(crash != dip, "부호가 같아도(둘 다 하락) 낙폭이 다르면 점수가 달라야 함")


def test_magnitude_net_sell():
    print("\n[2] 3주체 순매수 — '부호만 반영' 버그가 되살아나지 않는가 (크기 반영)")
    tiny_sell = measured_downside_risk(-1000.0, FAKE_FLOW_POP)    # 1천억 순매도
    huge_sell = measured_downside_risk(-30000.0, FAKE_FLOW_POP)   # 3조 순매도
    tiny_buy = measured_downside_risk(+1000.0, FAKE_FLOW_POP)
    huge_buy = measured_downside_risk(+30000.0, FAKE_FLOW_POP)

    check(huge_sell > tiny_sell,
          f"3조 순매도가 1천억 순매도보다 위험해야 함 (실제: {huge_sell} > {tiny_sell})")
    check(tiny_sell > 0.5 > tiny_buy,
          f"순매도는 중립 위, 순매수는 중립 아래 (실제: {tiny_sell} / {tiny_buy})")
    check(huge_buy < tiny_buy,
          f"3조 순매수가 1천억 순매수보다 안전해야 함 (실제: {huge_buy} < {tiny_buy})")
    check(all(_in_unit_range(v) for v in (tiny_sell, huge_sell, tiny_buy, huge_buy)),
          "네 시나리오 모두 [0, 1] 범위")

    # 예전 식(0.5 ± 0.3 × 개인비중)에서는 아래 두 값이 완전히 동점이었습니다.
    check(len({tiny_sell, huge_sell, tiny_buy, huge_buy}) == 4,
          "금액이 다른 4개 시나리오가 서로 다른 4개 점수를 만든다(동점 없음)")


def test_bounds_and_winsorize():
    print("\n[3] 경계 — 극단 입력에서도 항상 [0, 1] 안에 있는가 (윈저라이즈)")
    extreme_crash = measured_downside_risk(-1.0, FAKE_RET_POP)     # -100% (현실엔 없는 극단)
    extreme_rally = measured_downside_risk(+1.0, FAKE_RET_POP)
    check(extreme_crash == 1.0, f"-50σ 급락은 1.0으로 윈저라이즈 (실제: {extreme_crash})")
    check(extreme_rally == 0.0, f"+50σ 급등은 0.0으로 윈저라이즈 (실제: {extreme_rally})")

    at_worst = measured_downside_risk(-MEASURED_WINSOR_Z * 0.02, FAKE_RET_POP)
    beyond_worst = measured_downside_risk(-MEASURED_WINSOR_Z * 0.02 * 2, FAKE_RET_POP)
    check(at_worst == 1.0 and beyond_worst == 1.0,
          f"-{MEASURED_WINSOR_Z}σ를 넘어가면 더 구분하지 않고 동일 취급 (실제: {at_worst} / {beyond_worst})")

    huge = measured_downside_risk(-1e12, FAKE_FLOW_POP)
    check(_in_unit_range(huge) and huge == 1.0, f"비현실적으로 큰 순매도도 폭주하지 않음 (실제: {huge})")

    # 단조성: 값이 커질수록(매수 방향) 위험은 절대 커지지 않아야 한다.
    seq = [measured_downside_risk(v, FAKE_FLOW_POP) for v in range(-30000, 30001, 2500)]
    check(all(a >= b for a, b in zip(seq, seq[1:])), "순매수 금액이 커질수록 위험도가 단조 감소")


def test_bootstrap_safety():
    print("\n[4] 부트스트랩 — 과거 표본이 부족할 때 크래시하지 않고 안전하게 처리되는가")
    check(measured_downside_risk(-30000.0, None) == 0.5,
          "population 통계가 없으면(표본 부족) 임의 상수가 아니라 중립 0.5로 안전 대체")
    check(measured_downside_risk(None, FAKE_FLOW_POP) is None,
          "원값 자체가 없으면(산출 불가) None → 호출부에서 배점 제외")
    check(measured_downside_risk(-30000.0, (0.0, 0.0)) == 0.5,
          "표준편차 0(변동 없음)이어도 0으로 나누지 않고 중립 0.5")

    check(compute_population_stats([], 20) is None, "빈 표본 → None")
    check(compute_population_stats([1.0] * 50, 20) is None, "전부 같은 값(표준편차 0) → None")
    check(compute_population_stats([100.0] * 10 + [200.0] * 10, 20) is not None, "표본 20개 충족 → 통계 산출")
    check(compute_population_stats([100.0] * 9 + [200.0] * 10, 20) is None, "표본 19개 → None(기준 미달)")
    check(compute_population_stats([1.0, 2.0, None, float("nan"), "x", 3.0], 3) is not None,
          "None/NaN/문자열이 섞여 있어도 크래시 없이 유효값만 사용")

    # 실제 부트스트랩 상황 재현: 이력이 6행뿐인 초기 CSV
    import pandas as pd
    tiny_df = pd.DataFrame({
        "Date": [f"2026-08-{d:02d}" for d in range(1, 7)],
        "Foreigner": [100, -200, 300, -400, 500, -600],
    })
    pop = net_flow_population(tiny_df, "Foreigner")
    check(pop is None, f"이력 6행(<{NET_FLOW_MIN_SAMPLE}행)이면 정규화 기준선을 만들지 않음")
    check(measured_downside_risk(-600, pop) == 0.5, "그 상태에서도 예외 없이 중립 0.5 반환")


def test_population_builders():
    print("\n[5] 정규화 기준선 생성기 (rolling_return_population / net_flow_population)")
    import pandas as pd

    # 매일 +0.1%씩 오르는 합성 시계열 300일치 → 5일 수익률 표본 295개
    closes = [1000.0 * (1.001 ** i) for i in range(300)]
    pop = rolling_return_population(closes)
    check(pop is not None, f"종가 300일치 → 5일 수익률 표본 {RETURN_POP_MIN_SAMPLE}개 이상 확보")
    if pop:
        check(abs(pop[0] - (1.001 ** 5 - 1)) < 1e-6,
              f"평균 5일 수익률이 이론값과 일치 (실제: {pop[0]:.6f})")

    check(rolling_return_population(closes[:30]) is None,
          f"종가 30일치(5일 수익률 표본 25개 < {RETURN_POP_MIN_SAMPLE}개) → None")
    check(rolling_return_population([]) is None, "빈 시계열 → None")
    check(rolling_return_population([1000.0, 0.0, -5.0, None, 1010.0]) is None,
          "0/음수/None이 섞인 종가도 크래시 없이 걸러냄")

    df = pd.DataFrame({"Date": [f"d{i}" for i in range(40)],
                       "Foreigner": [i * 100 - 2000 for i in range(40)]})
    check(net_flow_population(df, "Foreigner") is not None, "이력 40행 → 순매수 기준선 산출")
    check(net_flow_population(df, "Institution") is None, "없는 컬럼을 요구하면 지어내지 않고 None")
    check(net_flow_population(pd.DataFrame(), "Foreigner") is None, "빈 DataFrame → None")
    check(net_flow_population(None, "Foreigner") is None, "None 입력에도 크래시하지 않음")


def test_real_history_spot_check():
    print("\n[6] 실데이터 스팟체크 — 저장소의 실제 market_history.csv")
    import pandas as pd
    # utils/db.py 대신 scrape_daily.py의 COL_MAP을 씁니다 — 실제로 이 CSV를 쓰는 쪽이고,
    # utils/db.py는 streamlit 의존이라 오프라인 테스트 환경에서 임포트되지 않습니다.
    from scrape_daily import COL_MAP

    csv_path = REPO_ROOT / "market_history.csv"
    if not csv_path.exists():
        check(False, "market_history.csv 파일이 있어야 함")
        return

    df = pd.read_csv(csv_path).rename(columns={v: k for k, v in COL_MAP.items()})
    check("Foreigner" in df.columns and "KOSPI" in df.columns,
          f"실제 CSV에서 수급·종가 컬럼을 읽음 (행 수: {len(df)})")

    # ⚠️ 실제 이력이 아직 NET_FLOW_MIN_SAMPLE 행에 못 미치므로, 여기서는 '방향이 맞는지'만
    #    확인하기 위해 표본 기준을 낮춰 스팟체크합니다(운영 코드는 기본값을 그대로 씁니다).
    pop = net_flow_population(df, "Foreigner", min_sample=3)
    check(pop is not None, "기준을 낮추면 실제 6행으로도 기준선이 만들어짐(스팟체크용)")
    if pop:
        risks = {str(r["Date"]): measured_downside_risk(float(r["Foreigner"]), pop)
                 for _, r in df.iterrows()}
        check(all(_in_unit_range(v) for v in risks.values()), "실데이터 전 행이 [0, 1] 범위")

        worst_date = min(df.itertuples(), key=lambda r: r.Foreigner).Date
        best_date = max(df.itertuples(), key=lambda r: r.Foreigner).Date
        check(risks[str(worst_date)] == max(risks.values()),
              f"외국인 순매도가 가장 컸던 날({worst_date})의 위험도가 최고 ({risks[str(worst_date)]})")
        check(risks[str(best_date)] == min(risks.values()),
              f"외국인 순매수가 가장 컸던 날({best_date})의 위험도가 최저 ({risks[str(best_date)]})")

    # 실제 코스피 종가로 5일 수익률을 재보고, 지금 이력(6행)에서는 정규화 기준선을 만들 수
    # 없으므로 중립(0.5)이 나오는지 확인합니다.
    # ⚠️ 운영(scrape_daily.py)에서는 이 기준선을 CSV가 아니라 FDR 시계열(약 1년)로 만들기
    #    때문에, 첫 실행부터 정상적으로 정규화됩니다. 여기서 0.5가 나오는 것은 "6행짜리
    #    CSV만으로는 분포를 논할 수 없다"는 부트스트랩 동작이 실데이터에서도 맞다는 뜻입니다.
    if len(df) >= 6 and "KOSPI" in df.columns:
        closes = [float(v) for v in df["KOSPI"]]
        real_5d = (closes[-1] - closes[-6]) / closes[-6]
        real_pop = rolling_return_population(closes)
        print(f"     ↳ 실측 5일 수익률 {real_5d * 100:.2f}% "
              f"({df.iloc[-6]['Date']} → {df.iloc[-1]['Date']})")
        check(real_pop is None, f"이력 {len(df)}행으로는 5일 수익률 분포를 만들지 않음(기준 미달)")
        check(measured_downside_risk(real_5d, real_pop) == 0.5,
              "기준선이 없으면 실데이터에서도 값을 지어내지 않고 중립 0.5")


def test_wiring():
    print("\n[7] 배선 — 수집·화면 양쪽이 같은 함수를 쓰는가")
    scrape_src = (REPO_ROOT / "scrape_daily.py").read_text(encoding="utf-8")
    view_src = (REPO_ROOT / "views" / "macro_view.py").read_text(encoding="utf-8")

    for name, src in (("scrape_daily.py", scrape_src), ("views/macro_view.py", view_src)):
        check("measured_downside_risk" in src, f"{name} 가 measured_downside_risk 를 사용")
        check("0.5 - 2.5 * kospi" not in src.replace("×", "*"),
              f"{name} 에 옛 임의 계수식(0.5 - 2.5×수익률)이 남아있지 않음")
    check("stock_net_base" not in scrape_src and "stock_net_base" not in view_src,
          "옛 상수 기반 stock_net_base 변수가 두 파일 모두에서 사라짐")


# =============================================================================
# 2026-08-10 (#69) — 실측 불가 6개 지표 제외 + 가중치 비례 재분배 검증
# =============================================================================
# 개정 전 가중치(합 102.0). 이 표는 "그때 실제로 이랬다"는 기록이자, 아래 비례 재분배가
# 정말로 상대 비중을 보존했는지 검산하기 위한 기준선입니다.
WEIGHTS_BEFORE_69 = {
    "FX_Swap_Point": 12.0, "Put_OTM_OI": 8.0, "Short_Ratio": 6.0, "ELS_KnockIn": 7.0,
    "VKOSPI_Skew": 6.0, "Synthetic_Futures": 12.0, "NDF_Night_Rate": 12.0,
    "Futures_Net_Sell": 6.0, "Non_Arbitrage_Ratio": 6.0, "Foreign_Broker_Dump": 6.0,
    "Stock_Short_Balance": 3.0, "Put_Buy_Simple": 3.0, "Stock_Net_Sell": 3.0,
    "KOSPI_5D_Return": 12.0,
}
# #69에서 뺀 6개 (4개는 화면 '공부용 참고' 섹션으로, 2개는 개념 중복이라 완전 제외)
RETIRED_EXPECTED = {
    "ELS_KnockIn", "NDF_Night_Rate", "Futures_Net_Sell", "Non_Arbitrage_Ratio",
    "Foreign_Broker_Dump", "Put_Buy_Simple",
}

# =============================================================================
# 2026-08-10 (#72) — 공매도 2종 '실측 불가' 재분류 + 가중치 재분배 검증
# =============================================================================
# #69 직후(= #72 직전)의 가중치 8개, 합계 100.00. 이번 재분배의 기준선입니다.
WEIGHTS_AFTER_69 = {
    "FX_Swap_Point": 19.35, "Put_OTM_OI": 12.90, "Short_Ratio": 9.68,
    "VKOSPI_Skew": 9.68, "Synthetic_Futures": 19.35, "Stock_Short_Balance": 4.84,
    "Stock_Net_Sell": 4.84, "KOSPI_5D_Return": 19.36,
}
# ⚠️ 이 2개는 #69의 6개와 **뺀 이유가 다릅니다.** 데이터가 없어서가 아니라, 유일한 무료
#    경로(pykrx)가 data.krx.co.kr 로그인 우회라 §0-3-2 원칙상 쓰지 않기로 한 것입니다.
#    그래서 '완전 삭제(DROPPED)'가 아니라 **공부 섹션에 남습니다.**
RETIRED_IN_72 = {"Short_Ratio", "Stock_Short_Balance"}
# 현재(= #72 이후) 점수에서 빠져 있는 전체 목록
RETIRED_EXPECTED_NOW = RETIRED_EXPECTED | RETIRED_IN_72
STUDY_EXPECTED = {
    "ELS_KnockIn", "NDF_Night_Rate", "Futures_Net_Sell", "Non_Arbitrage_Ratio",
    "Short_Ratio", "Stock_Short_Balance",
}
DROPPED_EXPECTED = {"Foreign_Broker_Dump", "Put_Buy_Simple"}
ACTIVE_EXPECTED = {
    "FX_Swap_Point", "Put_OTM_OI", "VKOSPI_Skew", "Synthetic_Futures",
    "Stock_Net_Sell", "KOSPI_5D_Return",
}


def _literal_from_source(path, name):
    """
    파일을 import 하지 않고(=streamlit 등 의존성 없이) 모듈 최상단 리터럴 할당값만 꺼냅니다.
    views/macro_view.py 는 streamlit 의존이라 오프라인 테스트에서 import 할 수 없습니다.
    """
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    return None


def test_weight_redistribution():
    print("\n[8] 가중치 재분배 — 6개(#69)에 이어 공매도 2개(#72)를 뺀 뒤 합이 정확히 100인가")
    from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

    total = sum(RISK_WEIGHTS.values())
    check(abs(total - 100.0) < 1e-9, f"RISK_WEIGHTS 합계 = 100.00 (실제: {total!r})")
    check(len(RISK_WEIGHTS) == 6, f"활성 지표는 6개 (실제: {len(RISK_WEIGHTS)}개)")
    check(set(RISK_WEIGHTS) == ACTIVE_EXPECTED, f"활성 지표 목록이 예상과 일치 (실제: {sorted(RISK_WEIGHTS)})")
    check(all(v > 0 for v in RISK_WEIGHTS.values()), "모든 가중치가 양수")

    # --- #69 산수 재검산 (그때의 기록이 실제로 맞았는지 계속 못박아 둡니다) ---
    check(abs(sum(WEIGHTS_BEFORE_69.values()) - 102.0) < 1e-9,
          f"#69 개정 전 14개 합계 = 102.0 (실제: {sum(WEIGHTS_BEFORE_69.values())})")
    dropped_sum = sum(WEIGHTS_BEFORE_69[k] for k in RETIRED_EXPECTED)
    kept_sum = sum(v for k, v in WEIGHTS_BEFORE_69.items() if k not in RETIRED_EXPECTED)
    check(abs(dropped_sum - 40.0) < 1e-9, f"#69에서 제외한 6개 합계 = 40.0 (실제: {dropped_sum})")
    check(abs(kept_sum - 62.0) < 1e-9, f"#69 이후 남은 8개의 개정 전 합계 = 62.0 (실제: {kept_sum})")
    factor_69 = 100.0 / kept_sum
    for key, w69 in sorted(WEIGHTS_AFTER_69.items()):
        expected = round(WEIGHTS_BEFORE_69[key] * factor_69, 2)
        if key == "KOSPI_5D_Return":
            # 단순 반올림 합이 99.99라, 잔여 0.01을 '유일하게 실측이 검증된' 이 지표에 배정했습니다.
            check(abs(w69 - (expected + 0.01)) < 1e-9,
                  f"#69 {key}: {WEIGHTS_BEFORE_69[key]}×100/62={expected} + 반올림 잔여 0.01 = {w69}")
        else:
            check(abs(w69 - expected) < 1e-9,
                  f"#69 {key}: {WEIGHTS_BEFORE_69[key]}×100/62 = {expected} (실제: {w69})")
    check(abs(sum(WEIGHTS_AFTER_69.values()) - 100.0) < 1e-9,
          f"#69 결과 8개 합계 = 100.00 (실제: {sum(WEIGHTS_AFTER_69.values())})")

    # --- #72 재분배 검산: 남은 6개 × 100/85.48 ---
    dropped_72 = sum(WEIGHTS_AFTER_69[k] for k in RETIRED_IN_72)
    kept_72 = sum(v for k, v in WEIGHTS_AFTER_69.items() if k not in RETIRED_IN_72)
    check(abs(dropped_72 - 14.52) < 1e-9,
          f"#72에서 제외한 공매도 2개 합계 = 14.52 (9.68 + 4.84, 실제: {round(dropped_72, 2)})")
    check(abs(kept_72 - 85.48) < 1e-9, f"남은 6개의 개정 전 합계 = 85.48 (실제: {round(kept_72, 2)})")

    factor_72 = 100.0 / kept_72
    naive_sum = 0.0
    for key, new_w in sorted(RISK_WEIGHTS.items()):
        expected = round(WEIGHTS_AFTER_69[key] * factor_72, 2)
        naive_sum += expected
        check(abs(new_w - expected) < 1e-9,
              f"{key}: {WEIGHTS_AFTER_69[key]}×100/85.48 = {expected} (실제: {new_w})")
    # ⚠️ #69와 달리 이번에는 단순 반올림 합이 그대로 100.00이라 잔여 조정을 하지 않았습니다.
    #    (이 체크가 깨지면 "어딘가에 잔여분을 붙였다"는 뜻이므로 주석과 코드가 어긋난 것입니다.)
    check(abs(naive_sum - 100.0) < 1e-9,
          f"단순 반올림 합계가 그대로 100.00 → 잔여 조정 불필요 (실제: {round(naive_sum, 6)})")

    # 상대 비중 보존 — 이번 단계도 '2개 제거'만 하고 지표 간 우열은 건드리지 않았습니다.
    ref = "FX_Swap_Point"
    for key in RISK_WEIGHTS:
        before_ratio = WEIGHTS_AFTER_69[key] / WEIGHTS_AFTER_69[ref]
        after_ratio = RISK_WEIGHTS[key] / RISK_WEIGHTS[ref]
        check(abs(before_ratio - after_ratio) < 0.002,
              f"{key}/{ref} 비율 보존: 개정 전 {before_ratio:.4f} ≈ 개정 후 {after_ratio:.4f}")

    # 공매도 2개는 활성 목록에서 사라지고, 은퇴 목록에는 '개정 전 몫'과 함께 남아야 합니다.
    for key in sorted(RETIRED_IN_72):
        check(key not in RISK_WEIGHTS, f"'{key}' 가 RISK_WEIGHTS 에 더 이상 없음")
        check(key in RETIRED_RISK_INDICATORS, f"'{key}' 가 RETIRED_RISK_INDICATORS 에 기록됨")
        check(abs(RETIRED_RISK_INDICATORS.get(key, -1) - WEIGHTS_AFTER_69[key]) < 1e-9,
              f"'{key}' 의 은퇴 시점 가중치 {WEIGHTS_AFTER_69[key]} 가 그대로 기록됨")

    check(set(RETIRED_RISK_INDICATORS) == RETIRED_EXPECTED_NOW,
          "RETIRED_RISK_INDICATORS가 제외한 8개(#69 6개 + #72 2개)와 정확히 일치")
    check(not (set(RISK_WEIGHTS) & RETIRED_EXPECTED_NOW),
          "제외한 8개가 RISK_WEIGHTS에 하나도 남아있지 않음")


def test_retired_indicators_removed_from_code():
    print("\n[9] 코드 제거 — 뺀 지표의 계산식이 정말 사라졌는가 (#69, #72)")
    scrape_src = (REPO_ROOT / "scrape_daily.py").read_text(encoding="utf-8")
    view_src = (REPO_ROOT / "views" / "macro_view.py").read_text(encoding="utf-8")

    # market_scores / market_scores_raw 항목이 남아있으면 CSV에 계속 값이 쌓입니다.
    for key in sorted(RETIRED_EXPECTED_NOW):
        for fname, src in (("scrape_daily.py", scrape_src), ("views/macro_view.py", view_src)):
            has_entry = (f'"{key}": {{' in src or f'"{key}": None if' in src
                         or f'"{key}": clip' in src)
            check(not has_entry, f"{fname} 의 점수 사전에 '{key}' 항목이 없음")

    # 계산에 쓰이던 임시 변수들도 함께 사라져야 합니다(남아 있으면 죽은 코드).
    # ⚠️ 단순 문자열 포함이 아니라 '대입/사용' 패턴으로 봅니다 — 두 파일 모두 "왜 지웠는지"를
    #    설명하는 주석에 변수 이름을 그대로 적어두었기 때문입니다(그 흔적은 남기는 게 맞습니다).
    import re
    # (#72 추가: short_base / bal_base — 공매도 2종의 임의 선형식)
    for var in ("els_base", "ndf_base", "fut_base", "non_base", "dump_base", "put_buy_base",
                "short_base", "bal_base"):
        pattern = re.compile(rf"^\s*{var}\s*=|clip\({var}\b|{var}\s+is\s+None", re.MULTILINE)
        check(not pattern.search(scrape_src), f"scrape_daily.py 에 '{var}' 계산/사용이 없음")
        check(not pattern.search(view_src), f"views/macro_view.py 에 '{var}' 계산/사용이 없음")

    # #72: short_base/bal_base 의 입력이던 변동성·고점대비낙폭 계산도 함께 사라져야 합니다.
    # (남겨두면 아무 데도 안 쓰이는 죽은 계산이 되고, 그 값을 이유로 수집 전체를 막는
    #  하드 실패 게이트가 되살아날 여지가 생깁니다.)
    for var in ("volatility", "dist_from_high"):
        pattern = re.compile(rf"^\s*{var}\s*=|{var}\s+is\s+None", re.MULTILINE)
        check(not pattern.search(scrape_src), f"scrape_daily.py 에 '{var}' 계산/사용이 없음")
        check(not pattern.search(view_src), f"views/macro_view.py 에 '{var}' 계산/사용이 없음")
    check("임의 상수(1.2 / 0.08)로 대체하지 않고" not in scrape_src,
          "쓰이지 않는 값(변동성·낙폭) 때문에 수집 전체가 죽던 하드 실패 게이트(raise)가 제거됨")
    # 반대로 KOSPI/환율 종가 결측 방어(§0-1의 핵심)는 그대로 살아 있어야 합니다.
    check("전일 값으로 메우지 않고 당일 수집을 중단합니다" in scrape_src,
          "KOSPI·환율 종가 결측 시 수집 중단하는 방어는 그대로 유지")

    # 반대로, 과거 CSV 를 읽으려면 한글 컬럼 매핑은 반드시 남아 있어야 합니다(기록 보존).
    for key in sorted(RETIRED_EXPECTED_NOW):
        check(f'"{key}":' in scrape_src, f"scrape_daily.py COL_MAP 에 '{key}' 한글 매핑은 보존")

    # 화면 문구가 지표 개수를 하드코딩하고 있으면 개수가 바뀔 때마다 거짓말이 됩니다.
    check("14개 변동성 지표별" not in view_src,
          "화면 제목이 '14개'로 하드코딩되어 있지 않음(len(RISK_WEIGHTS) 사용)")


def test_study_section_matches_code():
    print("\n[10] 문서-코드 일치 — 화면 공부 섹션 목록 == 실제로 뺀 목록 (#69, #72)")
    from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

    view_path = REPO_ROOT / "views" / "macro_view.py"
    study = _literal_from_source(view_path, "STUDY_ONLY_INDICATORS")
    dropped = _literal_from_source(view_path, "DROPPED_AS_DUPLICATE")
    friendly = _literal_from_source(view_path, "FRIENDLY_NAMES")

    check(study is not None and len(study) == 6, f"공부용 섹션에 6개 지표가 실림 (실제: {len(study or [])}개)")
    study_keys = {d["key"] for d in (study or [])}
    check(study_keys == STUDY_EXPECTED, f"공부용 목록이 예상과 일치 (실제: {sorted(study_keys)})")

    # 완전 제외 2개는 '왜 뺐는지'가 화면에 남아 있어야 합니다(조용히 사라지지 않게).
    dropped_text = " ".join(name for name, _ in (dropped or []))
    for key in sorted(DROPPED_EXPECTED):
        check(key in dropped_text, f"'{key}' 가 완전 제외 안내 목록에 이유와 함께 표기됨")

    # 핵심: 공부 섹션 + 완전 제외 = 실제로 코드에서 뺀 8개. 어긋나면 화면이 거짓말을 하게 됩니다.
    check(study_keys | DROPPED_EXPECTED == set(RETIRED_RISK_INDICATORS),
          "공부 섹션(6) + 완전 제외(2) = RETIRED_RISK_INDICATORS(8) 정확히 일치")
    check(not (study_keys & set(RISK_WEIGHTS)),
          "공부 섹션 지표가 활성 지표와 겹치지 않음(점수에 두 번 들어가지 않음)")
    check(set(friendly or {}) == set(RISK_WEIGHTS),
          "화면 표기명(FRIENDLY_NAMES) 키가 활성 지표 6개와 정확히 일치")

    # 공부 섹션은 '설명'만 있어야 합니다 — 없는 데이터로 예시 숫자를 그리면 §0-1 위반입니다.
    for item in (study or []):
        for field in ("title", "one_liner", "why_it_matters", "missing_data",
                      "hypothetical_weight", "weight_reasoning"):
            check(bool(item.get(field)), f"{item['key']}: '{field}' 설명이 비어있지 않음")
        check(len(item.get("how_to_study", [])) >= 2,
              f"{item['key']}: 구체적인 공부 방법이 2개 이상")
        check("참고 범위" in item["hypothetical_weight"],
              f"{item['key']}: 가중치를 확정치가 아닌 '참고 범위'로 표기")


# =============================================================================
# 2026-08-10 (#70) — KRX OPEN API 실측 연결 검증 (VKOSPI 레벨 / KOSPI200 선물 베이시스)
# =============================================================================
# ⚠️ 이 저장소의 개발 환경은 외부 네트워크가 막혀 있어 **실제 KRX 서버 응답을 한 번도 받아본
#    적이 없습니다.** 그래서 여기서는 미국주식 수집기 때와 같은 방식으로, HTTP 호출 지점
#    (`utils.krx_openapi._http_get_json`) 하나만 가짜로 바꿔 배선 전체(요청 구성 → 상태코드
#    분기 → 파싱 → 행 선택 → 정규화)를 end-to-end로 검증합니다.
#    **실서버 규격이 맞는지는 이 테스트로 증명되지 않습니다** — 그건 오너의 Actions 수동 실행
#    로그로만 확인할 수 있고, 그 전까지는 "실서버 미검증"입니다.

FAKE_KEY = "TEST-KEY-NOT-A-REAL-CREDENTIAL"


def _fake_kospi_rows(bas_dd="20260807"):
    """KOSPI 시리즈 응답 흉내. 'coincidence 함정'으로 '코스피 200 TR' 을 일부러 섞습니다."""
    return [
        {"BAS_DD": bas_dd, "IDX_CLSS": "KOSPI", "IDX_NM": "코스피", "CLSPRC_IDX": "2,540.12"},
        {"BAS_DD": bas_dd, "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 200", "CLSPRC_IDX": "345.67"},
        {"BAS_DD": bas_dd, "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 200 TR", "CLSPRC_IDX": "5,432.10"},
        {"BAS_DD": bas_dd, "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 200 중소형주", "CLSPRC_IDX": "1,210.00"},
    ]


def _fake_deriv_rows(bas_dd="20260807"):
    return [
        {"BAS_DD": bas_dd, "IDX_CLSS": "파생상품지수", "IDX_NM": "코스피 200 선물지수", "CLSPRC_IDX": "1,234.56"},
        {"BAS_DD": bas_dd, "IDX_CLSS": "파생상품지수", "IDX_NM": "코스피 200 변동성지수", "CLSPRC_IDX": "18.42"},
    ]


def _fake_futures_rows(bas_dd="20260807"):
    return [
        {"BAS_DD": bas_dd, "ISU_CD": "KR4101X90009", "ISU_NM": "코스피200 F 202609",
         "PROD_NM": "코스피200 선물", "TDD_CLSPRC": "346.10", "SPOT_PRC": "345.67",
         "ACC_TRDVOL": "180,000", "ACC_OPNINT_QTY": "310,000"},
        {"BAS_DD": bas_dd, "ISU_CD": "KR4101X90017", "ISU_NM": "코스피200 F 202612",
         "PROD_NM": "코스피200 선물", "TDD_CLSPRC": "348.90", "SPOT_PRC": "345.67",
         "ACC_TRDVOL": "5,100", "ACC_OPNINT_QTY": "12,000"},
        {"BAS_DD": bas_dd, "ISU_CD": "KR4106X90007", "ISU_NM": "미니 코스피200 F 202609",
         "PROD_NM": "미니 코스피200 선물", "TDD_CLSPRC": "346.05", "SPOT_PRC": "345.67",
         "ACC_TRDVOL": "900,000", "ACC_OPNINT_QTY": "88,000"},
        {"BAS_DD": bas_dd, "ISU_CD": "KR4201X00000", "ISU_NM": "3년국채 F 202609",
         "PROD_NM": "3년국채 선물", "TDD_CLSPRC": "106.20", "ACC_TRDVOL": "120,000"},
    ]


class _FakeKrxServer:
    """
    `_http_get_json` 을 대신하는 가짜 서버. 엔드포인트별 응답을 시나리오로 지정합니다.
    호출 기록(calls)을 남겨 "요청을 몇 번 보냈는지"(크롤링 매너)까지 검증합니다.
    """

    def __init__(self, plan):
        # plan: {endpoint_path: [(status, payload), ...]}  — 호출 순서대로 소비
        self.plan = {k: list(v) for k, v in plan.items()}
        self.calls = []

    def __call__(self, url, headers, params, timeout, session):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append({
            "endpoint": endpoint, "url": url,
            "headers": dict(headers or {}), "params": dict(params or {}),
        })
        queue = self.plan.get(endpoint)
        if not queue:
            return 200, {"OutBlock_1": []}
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def _install_fake_server(server):
    """가짜 서버를 꽂고, 테스트가 느려지지 않게 대기 시간을 0으로 만듭니다."""
    from utils import krx_openapi
    krx_openapi._http_get_json = server
    krx_openapi.KRX_REQUEST_DELAY_SEC = 0
    krx_openapi.KRX_RETRY_DELAY_SEC = 0
    return krx_openapi


def test_upside_risk_direction():
    print("\n[11] VKOSPI 방향 — '값이 클수록 위험'이 제대로 뒤집혀 있는가 (#70)")
    from utils.macro_scoring import measured_upside_risk

    # 합성 VKOSPI 분포: 평균 18, 표준편차 4 (실제 VKOSPI가 대략 15~25 사이에서 움직이는 스케일)
    pop = (18.0, 4.0)
    panic = measured_upside_risk(32.0, pop)   # 공포 급등
    high = measured_upside_risk(24.0, pop)
    normal = measured_upside_risk(18.0, pop)  # 평균
    calm = measured_upside_risk(12.0, pop)    # 이례적 안정

    check(panic > high > normal > calm,
          f"공포급등 > 높음 > 평균 > 안정 (실제: {panic} > {high} > {normal} > {calm})")
    check(abs(normal - 0.5) < 1e-9, f"평균과 같은 VKOSPI는 정확히 중립 0.5 (실제: {normal})")
    check(all(_in_unit_range(v) for v in (panic, high, normal, calm)), "네 시나리오 모두 [0, 1] 범위")
    check(measured_upside_risk(1e9, pop) == 1.0 and measured_upside_risk(-1e9, pop) == 0.0,
          "극단 입력도 [0,1]로 윈저라이즈")

    # 방향이 downside 와 정확히 거울상인지 (부호 실수 방지)
    for v in (10.0, 14.0, 18.0, 22.0, 30.0):
        up = measured_upside_risk(v, pop)
        down = measured_downside_risk(v, pop)
        check(abs(up + down - 1.0) < 1e-9,
              f"VKOSPI={v}: upside({up}) + downside({down}) = 1.0 (정확히 반대 방향)")

    seq = [measured_upside_risk(v, pop) for v in range(5, 41, 5)]
    check(all(a <= b for a, b in zip(seq, seq[1:])), "VKOSPI가 커질수록 위험도가 단조 증가")

    check(measured_upside_risk(None, pop) is None, "원값 없음 → None (배점 제외)")
    check(measured_upside_risk(20.0, None) == 0.5, "표본 부족 → 임의 상수 아닌 중립 0.5")
    check(measured_upside_risk(20.0, (18.0, 0.0)) == 0.5, "표준편차 0 → 0으로 나누지 않고 중립 0.5")


def test_krx_parsers():
    print("\n[12] KRX 응답 파서·선택기 — 못 찾으면 '고르지 않는가' (#70)")
    from utils import krx_openapi as kx

    check(kx.to_float("1,234.56") == 1234.56, "천단위 쉼표가 있는 숫자 파싱")
    check(kx.to_float("-") is None and kx.to_float("") is None and kx.to_float(None) is None,
          "'-'/빈문자/None 은 0.0이 아니라 None (없음과 0은 다른 사실)")
    check(kx.to_float("abc") is None, "숫자가 아니면 None")
    check(kx.to_float(float("nan")) is None, "NaN도 None")

    check(kx.to_date_param("2026-08-07") == "20260807", "'YYYY-MM-DD' → 'YYYYMMDD'")
    check(kx.to_date_param("20260807") == "20260807", "이미 YYYYMMDD면 그대로")
    try:
        kx.to_date_param("2026-8-7")
        check(False, "잘못된 날짜 형식은 ValueError")
    except ValueError:
        check(True, "잘못된 날짜 형식은 ValueError")

    # --- 지수 선택: 이름이 비슷한 함정(코스피 200 TR / 중소형주)을 피하는가 ---
    row, note = kx.select_index_row(_fake_kospi_rows(), kx.KOSPI200_NAME_CANDIDATES)
    check(row is not None and row["IDX_NM"] == "코스피 200",
          f"'코스피 200 TR'/'중소형주'가 섞여 있어도 정확히 '코스피 200'만 고름 ({note})")
    check(kx.to_float(row["CLSPRC_IDX"]) == 345.67, "선택한 행에서 지수 종가를 읽음")

    v_row, v_note = kx.select_index_row(
        _fake_deriv_rows(), kx.VKOSPI_NAME_CANDIDATES, fallback_keyword=kx.VKOSPI_NAME_FALLBACK_KEYWORD)
    check(v_row is not None and v_row["IDX_NM"] == "코스피 200 변동성지수", f"VKOSPI 정확일치 ({v_note})")

    # 후보와 정확히 일치하는 이름이 없어도, '변동성' 포함이 유일하면 부분일치로 찾는다
    renamed = [{"IDX_NM": "코스피 200 변동성지수(신규)", "CLSPRC_IDX": "19.1"},
               {"IDX_NM": "코스피 200 선물지수", "CLSPRC_IDX": "1200"}]
    r2, n2 = kx.select_index_row(renamed, kx.VKOSPI_NAME_CANDIDATES,
                                 fallback_keyword=kx.VKOSPI_NAME_FALLBACK_KEYWORD)
    check(r2 is not None and "변동성" in r2["IDX_NM"], f"이름이 조금 바뀌어도 부분일치로 찾음 ({n2})")

    # '변동성'이 둘 이상이면 **고르지 않는다** (아무거나 집으면 그게 지어내기)
    ambiguous = [{"IDX_NM": "코스피 200 변동성지수A", "CLSPRC_IDX": "19.1"},
                 {"IDX_NM": "코스닥 150 변동성지수", "CLSPRC_IDX": "24.4"}]
    r3, n3 = kx.select_index_row(ambiguous, kx.VKOSPI_NAME_CANDIDATES,
                                 fallback_keyword=kx.VKOSPI_NAME_FALLBACK_KEYWORD)
    check(r3 is None and "2개" in n3, f"후보가 여러 개면 임의로 고르지 않고 None ({n3})")

    r4, n4 = kx.select_index_row([{"IDX_NM": "코스피", "CLSPRC_IDX": "2500"}],
                                 kx.KOSPI200_NAME_CANDIDATES)
    check(r4 is None and "코스피" in n4,
          "못 찾으면 None + 응답에 실제로 있던 지수명을 로그에 남김(오너가 확정할 수 있게)")
    check(kx.select_index_row([], kx.KOSPI200_NAME_CANDIDATES)[0] is None, "빈 응답 → None")

    # --- 선물 근월물 선택 ---
    f_row, f_note = kx.select_front_month_future(_fake_futures_rows())
    check(f_row is not None and f_row["ISU_NM"] == "코스피200 F 202609",
          f"거래량이 가장 많은 종목을 근월물로 선택 ({f_note})")
    check(f_row["PROD_NM"] == "코스피200 선물",
          "거래량이 더 많은 '미니 코스피200 선물'(900,000)에 낚이지 않음 — 상품이 다르므로 제외")
    check("202612" not in f_row["ISU_NM"], "원월물(거래량 5,100)을 고르지 않음")

    # 상품명이 조금 달라도 부분일치로 잡되, '미니'는 제외되는가
    variant = [
        {"ISU_NM": "K200 F 202609", "PROD_NM": "코스피200 선물(주간)", "TDD_CLSPRC": "346.1", "ACC_TRDVOL": "1,000"},
        {"ISU_NM": "미니 F", "PROD_NM": "미니 코스피200 선물", "TDD_CLSPRC": "346.0", "ACC_TRDVOL": "999,999"},
    ]
    v_row2, v_note2 = kx.select_front_month_future(variant)
    check(v_row2 is not None and v_row2["PROD_NM"] == "코스피200 선물(주간)",
          f"부분일치 경로에서도 '미니'는 제외 ({v_note2})")

    check(kx.select_front_month_future([{"PROD_NM": "3년국채 선물", "TDD_CLSPRC": "1", "ACC_TRDVOL": "1"}])[0] is None,
          "KOSPI200 선물이 아예 없으면 None")
    check(kx.select_front_month_future(
        [{"PROD_NM": "코스피200 선물", "TDD_CLSPRC": "346.1"}])[0] is None,
        "거래량 필드가 없으면 근월물을 판정할 수 없어 None (아무거나 고르지 않음)")
    check(kx.select_front_month_future(
        [{"PROD_NM": "코스피200 선물", "TDD_CLSPRC": "-", "ACC_TRDVOL": "100"}])[0] is None,
        "종가를 읽을 수 없으면 None")


def test_krx_end_to_end_success():
    print("\n[13] KRX 배선 end-to-end — 정상 응답에서 값이 끝까지 흘러오는가 (#70)")
    server = _FakeKrxServer({
        "kospi_dd_trd": [(200, {"OutBlock_1": _fake_kospi_rows()})],
        "drvprod_dd_trd": [(200, {"OutBlock_1": _fake_deriv_rows()})],
        "fut_bydd_trd": [(200, {"OutBlock_1": _fake_futures_rows()})],
    })
    kx = _install_fake_server(server)

    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(out["api_key_present"] is True, "인증키 인식")
    check(out["as_of"] == "2026-08-07", f"as-of 기준일 기록 (실제: {out['as_of']})")
    check(out["vkospi_level"] == 18.42, f"VKOSPI 실측값 {out['vkospi_level']}")
    check(out["kospi200_close"] == 345.67, f"KOSPI200 지수 종가 {out['kospi200_close']}")
    check(out["futures_close"] == 346.10, f"선물 근월물 종가 {out['futures_close']}")
    check(abs(out["futures_basis"] - (346.10 - 345.67)) < 1e-9,
          f"베이시스 = 선물 − 지수 = {out['futures_basis']:.4f} (순수 뺄셈, 가정 없음)")
    check(not out["errors"], f"정상 응답에서는 오류 목록이 비어야 함 (실제: {out['errors']})")

    # 요청 구성 검증 — 인증키는 반드시 '헤더'로만 가야 합니다(URL에 실리면 로그에 남음).
    check(len(server.calls) == 3, f"1회 실행 = 3회 호출 (실제: {len(server.calls)}회)")
    for call in server.calls:
        check(call["headers"].get("AUTH_KEY") == FAKE_KEY,
              f"{call['endpoint']}: 인증키를 AUTH_KEY 헤더로 전달")
        check("AUTH_KEY" not in call["params"] and "AUTH_KEY" not in call["url"],
              f"{call['endpoint']}: 인증키가 URL/쿼리스트링에 절대 실리지 않음")
        check(call["params"].get("basDd") == "20260807", f"{call['endpoint']}: basDd=20260807")
    check(server.calls[0]["url"].startswith("https://data-dbg.krx.co.kr/svc/apis/idx/"),
          "지수 엔드포인트 경로가 규격대로 구성됨")

    # 실측 원값 → 위험도 정규화까지 (부트스트랩 포함)
    from utils.macro_scoring import measured_upside_risk
    check(measured_upside_risk(out["vkospi_level"], None) == 0.5,
          "이력이 없으면(첫날) VKOSPI도 값을 지어내지 않고 중립 0.5")
    check(measured_upside_risk(out["vkospi_level"], (15.0, 3.0)) > 0.5,
          "이력이 쌓여 평균 15인 상황에서 18.42는 중립보다 위험(방향 정상)")
    check(measured_downside_risk(out["futures_basis"], (1.5, 0.5)) > 0.5,
          "평균 베이시스 1.5 대비 0.43은 중립보다 위험(백워데이션 방향 정상)")


def test_krx_failure_modes():
    print("\n[14] KRX 실패 모드 — 어떤 오류에도 크래시 없이 '그 지표만' 빠지는가 (#70)")
    from utils import krx_openapi as kx

    # ① 인증키가 아예 없을 때 (환경변수도 비움)
    saved = os.environ.pop(kx.KRX_API_KEY_ENV, None)
    try:
        out = kx.collect_krx_risk_inputs("2026-08-07", api_key=None)
        check(out["api_key_present"] is False, "인증키 없음을 명시")
        check(out["vkospi_level"] is None and out["futures_basis"] is None,
              "키가 없으면 프록시로 폴백하지 않고 두 지표 모두 None")
        check(any(kx.KRX_API_KEY_ENV in e for e in out["errors"]),
              "왜 산출 불가인지 사유를 남김")
    finally:
        if saved is not None:
            os.environ[kx.KRX_API_KEY_ENV] = saved

    # ② 인증 실패(401) — 서비스 승인 전 상태. 재시도하지 않아야 합니다.
    server = _FakeKrxServer({"kospi_dd_trd": [(401, {"message": "unauthorized"})]})
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(out["vkospi_level"] is None and out["futures_basis"] is None, "401 → 두 지표 모두 None")
    check(len(server.calls) == 1, f"401은 재시도하지 않음 (호출 {len(server.calls)}회, §0-3-2)")
    check(any("승인" in e for e in out["errors"]), "401 사유에 '서비스별 이용신청 승인' 안내 포함")

    # ③ 호출 한도 초과(429) — 역시 재시도 금지
    server = _FakeKrxServer({"kospi_dd_trd": [(429, {})]})
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(len(server.calls) == 1, "429도 재시도하지 않음")

    # ④ 네트워크 오류 — 1회만 재시도하고 포기
    server = _FakeKrxServer({"kospi_dd_trd": [ConnectionError("network down")]})
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(len(server.calls) == kx.KRX_NETWORK_RETRY + 1,
          f"네트워크 오류는 {kx.KRX_NETWORK_RETRY}회만 재시도 (총 {len(server.calls)}회 호출)")
    check(out["vkospi_level"] is None, "네트워크 오류 → None")

    # ⑤ 응답 규격이 바뀐 경우 (OutBlock_1 없음)
    server = _FakeKrxServer({"kospi_dd_trd": [(200, {"Result": []})]})
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(out["vkospi_level"] is None and any("OutBlock_1" in e for e in out["errors"]),
          "응답 최상위 키가 다르면 사유를 남기고 None")

    # ⑥ 휴장일/미공개 — 하루씩 거슬러 올라가 데이터가 있는 거래일을 찾는가
    calls_by_date = {"count": 0}

    def _weekend_server(url, headers, params, timeout, session):
        calls_by_date["count"] += 1
        endpoint = url.rsplit("/", 1)[-1]
        day = params["basDd"]
        if endpoint == "kospi_dd_trd":
            return (200, {"OutBlock_1": _fake_kospi_rows(day)}) if day == "20260807" else (200, {"OutBlock_1": []})
        if endpoint == "drvprod_dd_trd":
            return 200, {"OutBlock_1": _fake_deriv_rows(day)}
        return 200, {"OutBlock_1": _fake_futures_rows(day)}

    _install_fake_server(_weekend_server)
    out = kx.collect_krx_risk_inputs("2026-08-10", api_key=FAKE_KEY)   # 월요일 → 금요일 데이터
    check(out["as_of"] == "2026-08-07",
          f"주말/미공개를 건너뛰고 직전 거래일을 as-of로 잡음 (실제: {out['as_of']})")
    check(out["vkospi_level"] == 18.42, "거슬러 올라간 거래일 기준으로 값이 정상 수집됨")
    check(calls_by_date["count"] <= 10,
          f"1회 실행 호출 수가 상한(10회) 이내 (실제 {calls_by_date['count']}회, 크롤링 매너)")

    # ⑦ 아무리 거슬러 올라가도 데이터가 없으면 포기 (무한 루프 금지)
    server = _FakeKrxServer({"kospi_dd_trd": [(200, {"OutBlock_1": []})]})
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-10", api_key=FAKE_KEY)
    check(out["as_of"] is None and out["vkospi_level"] is None, "거래일을 못 찾으면 값 없음")
    check(len(server.calls) == kx.KRX_MAX_LOOKBACK_DAYS + 1,
          f"탐색 횟수가 상한({kx.KRX_MAX_LOOKBACK_DAYS + 1}회)에서 멈춤 (실제 {len(server.calls)}회)")

    # ⑧ 지수는 왔는데 VKOSPI 이름을 못 찾는 경우 — 베이시스는 살아있어야 합니다(독립 실패)
    server = _FakeKrxServer({
        "kospi_dd_trd": [(200, {"OutBlock_1": _fake_kospi_rows()})],
        "drvprod_dd_trd": [(200, {"OutBlock_1": [{"IDX_NM": "코스피 200 선물지수", "CLSPRC_IDX": "1200"}]})],
        "fut_bydd_trd": [(200, {"OutBlock_1": _fake_futures_rows()})],
    })
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(out["vkospi_level"] is None, "VKOSPI를 특정 못하면 그 지표만 None")
    check(out["futures_basis"] is not None, "그래도 선물 베이시스는 정상 산출(지표별 독립 실패)")

    # ⑨ 필드명이 바뀐 경우 (종가 필드 없음)
    server = _FakeKrxServer({
        "kospi_dd_trd": [(200, {"OutBlock_1": [{"IDX_NM": "코스피 200", "CLOSE": "345.67"}]})],
        "drvprod_dd_trd": [(200, {"OutBlock_1": _fake_deriv_rows()})],
        "fut_bydd_trd": [(200, {"OutBlock_1": _fake_futures_rows()})],
    })
    _install_fake_server(server)
    out = kx.collect_krx_risk_inputs("2026-08-07", api_key=FAKE_KEY)
    check(out["kospi200_close"] is None and out["futures_basis"] is None,
          "종가 필드가 없으면 베이시스를 계산하지 않음(엉뚱한 값 대입 금지)")
    check(out["vkospi_level"] == 18.42, "그래도 VKOSPI는 독립적으로 살아있음")
    check(any("CLSPRC_IDX" in e for e in out["errors"]),
          "어느 필드를 못 읽었는지 오류 메시지에 남김(다음 디버깅용)")


def test_krx_wiring():
    print("\n[15] 배선·기록 — 두 파일이 같은 방식으로 바뀌었고 가중치는 그대로인가 (#70)")
    scrape_src = (REPO_ROOT / "scrape_daily.py").read_text(encoding="utf-8")
    view_src = (REPO_ROOT / "views" / "macro_view.py").read_text(encoding="utf-8")
    db_src = (REPO_ROOT / "utils" / "db.py").read_text(encoding="utf-8")
    wf_src = (REPO_ROOT / ".github" / "workflows" / "scrape.yml").read_text(encoding="utf-8")

    check("collect_krx_risk_inputs" in scrape_src, "scrape_daily.py 가 KRX 실측 수집기를 호출")
    check("measured_upside_risk" in scrape_src, "scrape_daily.py 가 VKOSPI 방향 함수를 사용")

    # 옛 프록시 계산식이 두 파일 모두에서 사라졌는가 (주석 설명은 남아도 되므로 '대입/사용' 패턴으로)
    import re
    for var in ("skew_base", "synth_base"):
        pattern = re.compile(rf"^\s*{var}\s*=|clip\({var}\b|{var}\s+is\s+None", re.MULTILINE)
        check(not pattern.search(scrape_src), f"scrape_daily.py 에 '{var}' 계산/사용이 없음")
        check(not pattern.search(view_src), f"views/macro_view.py 에 '{var}' 계산/사용이 없음")
    check("0.3 * (usd_close - 1300)" not in scrape_src and "0.3 * (usd_close - 1300)" not in view_src,
          "'합성선물'을 환율로 계산하던 식(0.3×(USD-1300)/200)이 두 파일 모두에서 사라짐")

    # 미리보기 화면이 프록시로 되살아나지 않았는지
    check('"VKOSPI_Skew": None,' in view_src and '"Synthetic_Futures": None,' in view_src,
          "미리보기 분기는 두 지표를 산출 불가(None)로 두고 프록시로 채우지 않음")

    # 신설 원값 컬럼이 저장 쪽·읽기 쪽 COL_MAP 에 **같은 한글 이름**으로 있어야 복원됩니다
    for col in ("VKOSPI_Level_Raw", "VKOSPI_Level_AsOf", "Futures_Basis_Raw", "Futures_Basis_AsOf"):
        check(f'"{col}"' in scrape_src, f"scrape_daily.py COL_MAP 에 '{col}' 존재")
        check(f'"{col}"' in db_src, f"utils/db.py COL_MAP 에 '{col}' 존재")

    from scrape_daily import COL_MAP as SCRAPE_COL_MAP
    db_col_map = _literal_from_source(REPO_ROOT / "utils" / "db.py", "COL_MAP")
    shared = set(SCRAPE_COL_MAP) & set(db_col_map or {})
    mismatched = [k for k in shared if SCRAPE_COL_MAP[k] != db_col_map[k]]
    check(not mismatched, f"두 COL_MAP 의 공통 키가 전부 같은 한글 이름 (불일치: {mismatched})")

    # 기존 키의 한글 이름은 절대 바뀌면 안 됩니다(과거 CSV 헤더 복원용)
    check(SCRAPE_COL_MAP["VKOSPI_Skew"] == "공포지수 비대칭도 (투자자들의 불안 심리 강도)",
          "VKOSPI_Skew 의 CSV 한글 헤더는 과거 기록 복원을 위해 그대로 유지")
    check(SCRAPE_COL_MAP["Synthetic_Futures"] == "합성선물 가격 차이 (외국인의 파생상품 하방 압력)",
          "Synthetic_Futures 의 CSV 한글 헤더도 그대로 유지")

    # 화면 표기명은 반대로, 실제 내용대로 바뀌어야 합니다(라벨과 내용 불일치 방지)
    friendly = _literal_from_source(REPO_ROOT / "views" / "macro_view.py", "FRIENDLY_NAMES")
    check("VKOSPI" in friendly["VKOSPI_Skew"] and "실측" in friendly["VKOSPI_Skew"],
          f"화면 표기명이 실제 내용(VKOSPI 실측)을 반영: {friendly['VKOSPI_Skew']!r}")
    check("베이시스" in friendly["Synthetic_Futures"] and "실측" in friendly["Synthetic_Futures"],
          f"화면 표기명이 실제 내용(선물 베이시스 실측)을 반영: {friendly['Synthetic_Futures']!r}")

    # 워크플로우가 시크릿을 넘겨주는가 (넘기지 않으면 Actions에서는 영원히 산출 불가)
    check("KRX_OPENAPI_KEY: ${{ secrets.KRX_OPENAPI_KEY }}" in wf_src,
          "scrape.yml 이 KRX_OPENAPI_KEY 시크릿을 환경변수로 전달")
    check(wf_src.index("KRX_OPENAPI_KEY:") < wf_src.index("python scrape_daily.py"),
          "그 env 블록이 scrape_daily.py 실행 스텝에 붙어 있음")

    # 인증키가 코드/워크플로우에 하드코딩되어 있지 않은지 (형식적이지만 사고 방지)
    krx_src = (REPO_ROOT / "utils" / "krx_openapi.py").read_text(encoding="utf-8")
    check("os.environ" in krx_src or "os.getenv" in krx_src, "인증키는 환경변수에서만 읽음")
    check(krx_src.count("AUTH_KEY") >= 1 and 'headers = {KRX_AUTH_HEADER: key' in krx_src,
          "인증키를 요청 '헤더'로 전달(공식 규격 — URL에 실으면 로그에 남음)")

    # ⚠️ #70 자체는 가중치를 손대지 않았습니다(그때 값 = #69 값 9.68 / 19.35).
    #    지금 값은 #72의 **비례 재분배**를 한 번 거친 결과라 숫자가 달라졌지만, 그건 '실측
    #    전환 때문에 올린 것'이 아니라 '공매도 2개를 뺀 몫이 기계적으로 분배된 것'입니다.
    #    상대 비중이 그대로인지는 [8]에서 검증합니다.
    from utils.constants import RISK_WEIGHTS
    check(WEIGHTS_AFTER_69["VKOSPI_Skew"] == 9.68 and WEIGHTS_AFTER_69["Synthetic_Futures"] == 19.35,
          "#70 당시 두 지표의 가중치는 #69 값 그대로였음 (프록시→실측 전환과 가중치 재설계는 별개)")
    check(RISK_WEIGHTS["VKOSPI_Skew"] == 11.32 and RISK_WEIGHTS["Synthetic_Futures"] == 22.64,
          "#72 재분배 후 값(11.32 / 22.64) — 임의 상향이 아니라 × 100/85.48 기계적 결과")


def test_short_indicators_reclassified():
    print("\n[16] 공매도 2종 재분류 — '데이터 없음'이 아니라 '경로를 안 쓰기로 함'인가 (#72)")
    from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

    view_path = REPO_ROOT / "views" / "macro_view.py"
    study = _literal_from_source(view_path, "STUDY_ONLY_INDICATORS") or []
    by_key = {d["key"]: d for d in study}
    dropped = _literal_from_source(view_path, "DROPPED_AS_DUPLICATE") or []
    dropped_text = " ".join(name for name, _ in dropped)

    for key in sorted(RETIRED_IN_72):
        # ① 점수에서 빠졌는가
        check(key not in RISK_WEIGHTS, f"'{key}' 가 활성 가중치에 없음")
        check(key in RETIRED_RISK_INDICATORS, f"'{key}' 가 은퇴 목록에 기록됨")
        # ② 삭제가 아니라 '이동'인가 — 공부 섹션에 반드시 있어야 합니다
        check(key in by_key, f"'{key}' 가 공부용 참고 섹션에 실려 있음(삭제가 아니라 이동)")
        # ③ 개념 중복으로 완전 삭제한 2개와 섞이지 않았는가
        check(key not in dropped_text,
              f"'{key}' 가 '완전 제외(개념 중복)' 목록에 잘못 들어가 있지 않음")

        item = by_key.get(key, {})
        for field in ("title", "one_liner", "why_it_matters", "missing_data",
                      "hypothetical_weight", "weight_reasoning"):
            check(bool(item.get(field)), f"{key}: '{field}' 설명이 비어있지 않음")
        check(len(item.get("how_to_study", [])) >= 3,
              f"{key}: 구체적인 공부 방법이 3개 이상")

        # ④ 핵심 — 사유가 #69의 4개("데이터 자체가 없음")와 다르다는 것을 정직하게 적었는가.
        #    pykrx / 로그인 전환 시점 / §0-3-2 원칙이 전부 언급돼야 합니다.
        missing = item.get("missing_data", "")
        check("pykrx" in missing, f"{key}: 실제로 데이터를 얻을 수 있는 경로(pykrx)를 밝힘")
        check("data.krx.co.kr" in missing, f"{key}: 로그인 전환된 출처(data.krx.co.kr)를 밝힘")
        check("2025-12-27" in missing, f"{key}: 로그인 전환 시점(2025-12-27)을 밝힘")
        check("0-3-2" in missing, f"{key}: 근거 원칙(§0-3-2)을 밝힘")
        check("데이터 자체는 존재합니다" in missing or "데이터가 없는 게" in missing,
              f"{key}: '데이터가 없어서'가 아님을 명시(#69의 4개와 사유가 다름)")

        # ⑤ 공부법에 'pykrx는 이 프로젝트에서 쓰지 않는다'는 단서가 붙어 있는가
        study_text = " ".join(item.get("how_to_study", []))
        check("pykrx" in study_text, f"{key}: 공부법에 pykrx 라이브러리 학습 안내 포함")
        check("쓰지 않습니다" in study_text,
              f"{key}: 다만 이 프로젝트에서는 원칙상 쓰지 않는다는 단서를 함께 명시")
        check("공매도" in study_text and ("KRX 정보데이터시스템" in study_text or "data.krx.co.kr" in study_text),
              f"{key}: KRX에서 공매도 통계를 직접 보는 방법을 안내")

        # ⑥ 가중치는 확정치가 아니라 '참고 범위'여야 합니다(#69 패턴 그대로)
        check("참고 범위" in item.get("hypothetical_weight", ""),
              f"{key}: 가중치를 확정치가 아닌 '참고 범위'로 표기")
        check("확정 가중치가 아닙니다" in item.get("weight_reasoning", ""),
              f"{key}: 근거 설명에도 확정치가 아님을 명시")

    # ⑦ 공부 섹션이 **옛 가중치를 인용한 채로** 남아있지 않은가.
    #    (재분배 때마다 놓치기 쉬운 곳입니다 — "지금 활성 지표 A는 4.84" 같은 문장이 남으면
    #     화면이 실제 가중치와 다른 숫자를 말하게 됩니다. 괄호 인용 형태만 검사합니다.)
    stale = {f"({v:.2f})" for v in WEIGHTS_AFTER_69.values()} - {f"({v:.2f})" for v in RISK_WEIGHTS.values()}
    for item in study:
        text = item.get("weight_reasoning", "")
        for token in sorted(stale):
            check(token not in text,
                  f"{item['key']}: 옛 가중치 인용 {token} 이 weight_reasoning 에 남아있지 않음")

    # ⑧ 화면 문구가 옛 개수(8개)를 그대로 말하고 있지 않은가
    view_src = view_path.read_text(encoding="utf-8")
    check("8개 중 6개" not in view_src, "화면 경고문이 옛 개수('8개 중 6개')를 말하지 않음")
    check("2026-08-10 기준 8개 지표" not in view_src, "거버넌스 선언문의 지표 개수가 갱신됨")

    # ⑨ 문서에도 기록이 남았는가 (TASK_HISTORY / PROJECT_STATUS)
    task_history = (REPO_ROOT / "TASK_HISTORY.md").read_text(encoding="utf-8")
    check("72." in task_history and "공매도" in task_history,
          "TASK_HISTORY.md 에 72번 항목이 기록됨")
    status = (REPO_ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    check("85.48" in task_history or "85.48" in status,
          "재분배 계산 근거(85.48)가 문서에 남아 있음")


def main():
    print("=" * 74)
    print("🛡️ 매크로 실측 지표 정규화(#68) + 실측불가 6개 제외·가중치 재분배(#69)")
    print("   + KRX OPEN API 실측 연결(#70, VKOSPI·선물 베이시스)")
    print("   + 공매도 2종 실측불가 재분류·가중치 재분배(#72) 검증")
    print("=" * 74)
    test_direction_kospi_5d()
    test_magnitude_net_sell()
    test_bounds_and_winsorize()
    test_bootstrap_safety()
    test_population_builders()
    test_real_history_spot_check()
    test_wiring()
    test_weight_redistribution()
    test_retired_indicators_removed_from_code()
    test_study_section_matches_code()
    # --- 2026-08-10 (#70) KRX OPEN API 실측 연결 ---
    test_upside_risk_direction()
    test_krx_parsers()
    test_krx_end_to_end_success()
    test_krx_failure_modes()
    test_krx_wiring()
    # --- 2026-08-10 (#72) 공매도 2종 실측 불가 재분류 ---
    test_short_indicators_reclassified()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
