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
# 점수에서 뺀 6개 (4개는 화면 '공부용 참고' 섹션으로, 2개는 개념 중복이라 완전 제외)
RETIRED_EXPECTED = {
    "ELS_KnockIn", "NDF_Night_Rate", "Futures_Net_Sell", "Non_Arbitrage_Ratio",
    "Foreign_Broker_Dump", "Put_Buy_Simple",
}
STUDY_EXPECTED = {"ELS_KnockIn", "NDF_Night_Rate", "Futures_Net_Sell", "Non_Arbitrage_Ratio"}
DROPPED_EXPECTED = {"Foreign_Broker_Dump", "Put_Buy_Simple"}


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
    print("\n[8] 가중치 재분배 — 6개를 뺀 뒤 합이 정확히 100인가 (#69)")
    from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

    total = sum(RISK_WEIGHTS.values())
    check(abs(total - 100.0) < 1e-9, f"RISK_WEIGHTS 합계 = 100.00 (실제: {total!r})")
    check(len(RISK_WEIGHTS) == 8, f"활성 지표는 8개 (실제: {len(RISK_WEIGHTS)}개)")
    check(all(v > 0 for v in RISK_WEIGHTS.values()), "모든 가중치가 양수")

    # 개정 전 표가 정말 102.0이었는지(제안서 §4-1 주장)와, 제외분이 40.0인지 실제로 더해봅니다.
    check(abs(sum(WEIGHTS_BEFORE_69.values()) - 102.0) < 1e-9,
          f"개정 전 14개 합계 = 102.0 (실제: {sum(WEIGHTS_BEFORE_69.values())})")
    dropped_sum = sum(WEIGHTS_BEFORE_69[k] for k in RETIRED_EXPECTED)
    kept_sum = sum(v for k, v in WEIGHTS_BEFORE_69.items() if k not in RETIRED_EXPECTED)
    check(abs(dropped_sum - 40.0) < 1e-9, f"제외한 6개 합계 = 40.0 (실제: {dropped_sum})")
    check(abs(kept_sum - 62.0) < 1e-9, f"남은 8개의 개정 전 합계 = 62.0 (실제: {kept_sum})")

    # 비례 재분배 검산: 각 지표 = 개정 전 값 × 100/62 (소수 둘째 자리 반올림)
    factor = 100.0 / kept_sum
    for key, new_w in sorted(RISK_WEIGHTS.items()):
        expected = round(WEIGHTS_BEFORE_69[key] * factor, 2)
        if key == "KOSPI_5D_Return":
            # 단순 반올림 합이 99.99라, 잔여 0.01을 '유일하게 실측이 검증된' 이 지표에 배정했습니다.
            check(abs(new_w - (expected + 0.01)) < 1e-9,
                  f"{key}: {WEIGHTS_BEFORE_69[key]}×100/62={expected} + 반올림 잔여 0.01 = {new_w}")
        else:
            check(abs(new_w - expected) < 1e-9,
                  f"{key}: {WEIGHTS_BEFORE_69[key]}×100/62 = {expected} (실제: {new_w})")

    # 상대 비중 보존(이번 단계는 '6개 제거'만 하고 지표 간 우열은 건드리지 않았음).
    # 반올림 잔여 0.01이 붙은 KOSPI_5D_Return은 오차 허용치를 조금 크게 둡니다.
    ref = "FX_Swap_Point"
    for key in RISK_WEIGHTS:
        before_ratio = WEIGHTS_BEFORE_69[key] / WEIGHTS_BEFORE_69[ref]
        after_ratio = RISK_WEIGHTS[key] / RISK_WEIGHTS[ref]
        check(abs(before_ratio - after_ratio) < 0.002,
              f"{key}/{ref} 비율 보존: 개정 전 {before_ratio:.4f} ≈ 개정 후 {after_ratio:.4f}")

    check(set(RETIRED_RISK_INDICATORS) == RETIRED_EXPECTED,
          "RETIRED_RISK_INDICATORS가 제외한 6개와 정확히 일치")
    check(not (set(RISK_WEIGHTS) & RETIRED_EXPECTED),
          "제외한 6개가 RISK_WEIGHTS에 하나도 남아있지 않음")


def test_retired_indicators_removed_from_code():
    print("\n[9] 코드 제거 — 뺀 지표의 계산식이 정말 사라졌는가 (#69)")
    scrape_src = (REPO_ROOT / "scrape_daily.py").read_text(encoding="utf-8")
    view_src = (REPO_ROOT / "views" / "macro_view.py").read_text(encoding="utf-8")

    # market_scores / market_scores_raw 항목이 남아있으면 CSV에 계속 값이 쌓입니다.
    for key in sorted(RETIRED_EXPECTED):
        for fname, src in (("scrape_daily.py", scrape_src), ("views/macro_view.py", view_src)):
            has_entry = (f'"{key}": {{' in src or f'"{key}": None if' in src
                         or f'"{key}": clip' in src)
            check(not has_entry, f"{fname} 의 점수 사전에 '{key}' 항목이 없음")

    # 계산에 쓰이던 임시 변수들도 함께 사라져야 합니다(남아 있으면 죽은 코드).
    # ⚠️ 단순 문자열 포함이 아니라 '대입/사용' 패턴으로 봅니다 — 두 파일 모두 "왜 지웠는지"를
    #    설명하는 주석에 변수 이름을 그대로 적어두었기 때문입니다(그 흔적은 남기는 게 맞습니다).
    import re
    for var in ("els_base", "ndf_base", "fut_base", "non_base", "dump_base", "put_buy_base"):
        pattern = re.compile(rf"^\s*{var}\s*=|clip\({var}\b|{var}\s+is\s+None", re.MULTILINE)
        check(not pattern.search(scrape_src), f"scrape_daily.py 에 '{var}' 계산/사용이 없음")
        check(not pattern.search(view_src), f"views/macro_view.py 에 '{var}' 계산/사용이 없음")

    # 반대로, 과거 CSV 를 읽으려면 한글 컬럼 매핑은 반드시 남아 있어야 합니다(기록 보존).
    for key in sorted(RETIRED_EXPECTED):
        check(f'"{key}":' in scrape_src, f"scrape_daily.py COL_MAP 에 '{key}' 한글 매핑은 보존")

    # 화면 문구가 지표 개수를 하드코딩하고 있으면 개수가 바뀔 때마다 거짓말이 됩니다.
    check("14개 변동성 지표별" not in view_src,
          "화면 제목이 '14개'로 하드코딩되어 있지 않음(len(RISK_WEIGHTS) 사용)")


def test_study_section_matches_code():
    print("\n[10] 문서-코드 일치 — 화면 공부 섹션 목록 == 실제로 뺀 목록 (#69)")
    from utils.constants import RISK_WEIGHTS, RETIRED_RISK_INDICATORS

    view_path = REPO_ROOT / "views" / "macro_view.py"
    study = _literal_from_source(view_path, "STUDY_ONLY_INDICATORS")
    dropped = _literal_from_source(view_path, "DROPPED_AS_DUPLICATE")
    friendly = _literal_from_source(view_path, "FRIENDLY_NAMES")

    check(study is not None and len(study) == 4, f"공부용 섹션에 4개 지표가 실림 (실제: {len(study or [])}개)")
    study_keys = {d["key"] for d in (study or [])}
    check(study_keys == STUDY_EXPECTED, f"공부용 목록이 예상과 일치 (실제: {sorted(study_keys)})")

    # 완전 제외 2개는 '왜 뺐는지'가 화면에 남아 있어야 합니다(조용히 사라지지 않게).
    dropped_text = " ".join(name for name, _ in (dropped or []))
    for key in sorted(DROPPED_EXPECTED):
        check(key in dropped_text, f"'{key}' 가 완전 제외 안내 목록에 이유와 함께 표기됨")

    # 핵심: 공부 섹션 + 완전 제외 = 실제로 코드에서 뺀 6개. 어긋나면 화면이 거짓말을 하게 됩니다.
    check(study_keys | DROPPED_EXPECTED == set(RETIRED_RISK_INDICATORS),
          "공부 섹션(4) + 완전 제외(2) = RETIRED_RISK_INDICATORS(6) 정확히 일치")
    check(not (study_keys & set(RISK_WEIGHTS)),
          "공부 섹션 지표가 활성 지표와 겹치지 않음(점수에 두 번 들어가지 않음)")
    check(set(friendly or {}) == set(RISK_WEIGHTS),
          "화면 표기명(FRIENDLY_NAMES) 키가 활성 지표 8개와 정확히 일치")

    # 공부 섹션은 '설명'만 있어야 합니다 — 없는 데이터로 예시 숫자를 그리면 §0-1 위반입니다.
    for item in (study or []):
        for field in ("title", "one_liner", "why_it_matters", "missing_data",
                      "hypothetical_weight", "weight_reasoning"):
            check(bool(item.get(field)), f"{item['key']}: '{field}' 설명이 비어있지 않음")
        check(len(item.get("how_to_study", [])) >= 2,
              f"{item['key']}: 구체적인 공부 방법이 2개 이상")
        check("참고 범위" in item["hypothetical_weight"],
              f"{item['key']}: 가중치를 확정치가 아닌 '참고 범위'로 표기")


def main():
    print("=" * 74)
    print("🛡️ 매크로 실측 지표 정규화(#68) + 실측불가 6개 제외·가중치 재분배(#69) 검증")
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

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("✅ 전체 통과")
    print("=" * 74)


if __name__ == "__main__":
    main()
