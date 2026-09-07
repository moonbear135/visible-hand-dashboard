# tests/_enrich_baseline.py
"""
🔒 `collector_kospi200.enrich_quant_metrics()` 특성화(characterization) 기준선 — 공용 실행부

이 파일이 왜 있는가
--------------------
`enrich_quant_metrics()` 는 636줄짜리 단일 함수라 다음에 손볼 때 부담이 큽니다. 그걸 쪼개는
리팩터를 하려면 **"쪼개기 전과 후의 결과가 완전히 같은가"를 증명할 장치**가 먼저 있어야 합니다.
그게 없으면 리팩터는 "잘 된 것 같다" 로 끝나는 도박이고, 이 저장소가 금지하는 바로 그
겉보기 정상(§0-1)입니다.

특성화 테스트는 **"이 계산이 옳은가"를 묻지 않습니다.** 옳고 그름은 기존 테스트들의 몫입니다.
이 파일은 오직 **"지금 내놓는 값을 앞으로도 똑같이 내놓는가"** 만 봅니다.

입력을 왜 얼려두는가
--------------------
🔴 입력을 `data/kospi200_pegy_latest.json` 에서 매번 다시 만들면, **매일 도는 수집 배치가
데이터를 갱신할 때마다 이 테스트의 기준이 같이 흔들립니다.** 그러면 기준선이 아니라
움직이는 과녁이 됩니다. 그래서 입력을 한 번 뽑아 `tests/fixtures/` 에 얼려두고, 그 뒤로는
저장소 데이터가 어떻게 바뀌든 이 테스트는 같은 입력만 씁니다.

입력값 자체는 **실제 수집 결과에서 뽑은 실데이터**입니다(지어낸 숫자가 아닙니다 — §0-1).

기준선을 다시 만들어야 할 때
--------------------------
계산 결과가 **의도적으로** 바뀌는 변경(수식 수정, 배점 변경 등)을 했을 때만입니다.
리팩터(구조만 바꾸고 결과는 그대로)에서 이 테스트가 빨간불이면 **리팩터가 틀린 것**이므로,
기준선을 고치지 말고 코드를 고치세요.

    python tests/_enrich_baseline.py --regenerate

⚠️ 이 명령은 오너 승인 없이 돌리지 마세요. 기준선을 갈아엎으면 회귀를 못 잡습니다.
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

FIXTURES = Path(__file__).parent / "fixtures"
INPUT_PATH = FIXTURES / "enrich_quant_metrics_input.json"
BASELINE_PATH = FIXTURES / "enrich_quant_metrics_baseline.json"

# 얼린 입력을 만들 때만 쓰는 원천(실수집 스냅샷). 평소 실행 경로는 이 파일을 읽지 않습니다.
_SOURCE_SNAPSHOT = REPO_ROOT / "data" / "kospi200_pegy_latest.json"

# `fetch_naver_item_dps_and_eps()` 가 돌려주는 dict 의 키 (collector_kospi200._empty_item_info 기준).
ITEM_KEYS = (
    "t_per", "t_eps", "f_per", "f_eps", "div_yield", "dps", "outstanding_shares",
    "t_pbr", "ev_ebitda", "f_roe", "raw_period",
    "dps_status", "dps_inherited_from",
    "div_yield_row_found", "div_yield_row_explicit_na", "errors",
)


# =====================================================================================
# 실행 — 외부로 나가는 것만 막고, 계산은 진짜 코드를 그대로 돌립니다
# =====================================================================================
def run_with_frozen_input(payload):
    """
    얼린 입력으로 `enrich_quant_metrics()` 를 실행하고 결과를 그대로 돌려줍니다.

    막는 것은 **네트워크로 나가는 5가지뿐**입니다 — 네이버 종목 상세, 변동성 시계열,
    FinanceDataReader 상장주식수, yfinance 교차검증, polite-scraping 대기.
    스코어링·가드레일·검증 파이프라인 등 **계산은 전부 진짜 코드가 돕니다.**
    (계산까지 가짜로 바꾸면 이 기준선은 아무것도 지키지 못합니다.)
    """
    import collector_kospi200 as K

    items = payload["items"]
    vols = payload["volatility"]

    def _fake_item(code, ticker_types=None):
        raw = items.get(code)
        if raw is None:
            return K._empty_item_info("기준선 입력에 없는 종목")
        return dict(raw)

    def _fake_vol(code):
        return vols.get(code)

    class _FakeTicker:
        """yfinance 교차검증 — 얼린 forwardPE 로만 답합니다(네트워크 없음)."""

        def __init__(self, symbol):
            self._symbol = symbol

        @property
        def info(self):
            return {"forwardPE": payload["yfinance_forward_pe"].get(self._symbol)}

    # 🔴 환경 의존성을 못 박습니다. `HAS_YFINANCE` / `HAS_FDR` 는 그 패키지가 설치돼 있느냐에
    #    따라 True/False 가 갈리는 모듈 전역입니다. 그대로 두면 **패키지가 깔린 기계와 안 깔린
    #    기계에서 기준선이 서로 달라집니다**(yfinance 교차검증 분기를 타느냐 마느냐가 바뀜).
    #    기준선은 어디서 돌려도 같아야 하므로 두 값을 고정하고, yfinance 는 얼린 값만 답하는
    #    가짜로 주입합니다(`create=True` — 패키지가 없는 기계에는 `yf` 자체가 없습니다).
    with mock.patch.object(K, "fetch_naver_item_dps_and_eps", _fake_item), \
         mock.patch.object(K, "fetch_recent_volatility", _fake_vol), \
         mock.patch.object(K, "_load_outstanding_shares_lookup", lambda: {}), \
         mock.patch.object(K, "HAS_YFINANCE", True, create=True), \
         mock.patch.object(K, "HAS_FDR", False, create=True), \
         mock.patch.object(K, "yf", mock.Mock(Ticker=_FakeTicker), create=True), \
         mock.patch.object(K.time, "sleep", lambda *a, **kw: None):
        return K.enrich_quant_metrics(
            [dict(s) for s in payload["stocks_raw"]],
            shares_lookup=dict(payload["shares_lookup"]),
        )


def canonical(result):
    """비교용 정규화 — 키 순서 차이로 오탐하지 않게 정렬해서 문자열로 만듭니다."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def load_input():
    return json.loads(INPUT_PATH.read_text(encoding="utf-8"))


def load_baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# =====================================================================================
# 얼린 입력 만들기 — 최초 1회(또는 오너 승인 후 갱신) 에만 실행
# =====================================================================================
def _pick_branch_covering_stocks(stocks, limit=60):
    """
    실수집 스냅샷에서 **분기를 골고루 밟는** 종목을 결정적으로 고릅니다.

    무작위 표본이 아니라 "이 분기를 밟는 종목 중 코드 순으로 앞의 것" 을 뽑기 때문에,
    같은 스냅샷이면 항상 같은 목록이 나옵니다.
    """
    def has(pred):
        return sorted([s for s in stocks if pred(s)], key=lambda s: s["code"])

    buckets = {
        "적자(trailing loss)":      has(lambda s: s.get("is_trailing_loss")),
        "역성장":                    has(lambda s: s.get("is_negative_growth")),
        "무배당 확정":               has(lambda s: s.get("dps_source") == "no_dividend_confirmed"),
        "배당 미수집":               has(lambda s: s.get("dps_source") == "not_collected"),
        "배당수익률 역산":           has(lambda s: s.get("dps_source") == "derived_from_div_yield"),
        "우선주 ROE 상속":           has(lambda s: s.get("t_roe_inherited_from")),
        "g_eff 캡 걸림":             has(lambda s: s.get("g_eff_capped")),
        "목표가 캡 걸림":            has(lambda s: s.get("f_target_capped")),
        "착시 저평가":               has(lambda s: s.get("value_trap")),
        "Forward 없음":              has(lambda s: s.get("forward_data_missing")),
        "변동성 없음":               has(lambda s: s.get("vol_std") is None),
        "금융업(그레이엄 경고)":      has(lambda s: s.get("graham_is_financial_sector")),
        "차단(is_valid=False)":      has(lambda s: s.get("is_valid") is False),
        "정상":                      has(lambda s: s.get("is_valid") and s.get("quant_score")),
    }
    picked, seen = [], set()
    # 분기마다 최대 5개씩 — 한 분기가 목록을 다 먹지 않게
    for label, group in buckets.items():
        taken = 0
        for s in group:
            if s["code"] in seen:
                continue
            picked.append((label, s))
            seen.add(s["code"])
            taken += 1
            if taken >= 5 or len(picked) >= limit:
                break
        if len(picked) >= limit:
            break

    # 🔴 우선주 ROE 상속은 **같은 배치 안에 보통주가 함께 있어야만** 일어납니다.
    #    (룩업 테이블을 이 입력 목록으로 그 자리에서 만들기 때문 — 앞 5자리가 같고
    #    끝자리가 0 인 보통주.) 우선주만 뽑으면 그 60줄짜리 전처리 블록이 한 번도
    #    안 밟혀서, 거기가 깨져도 기준선이 못 잡습니다. 짝을 반드시 같이 넣습니다.
    by_code = {s["code"]: s for s in stocks}
    for _label, s in list(picked):
        code = s["code"]
        if len(code) < 6 or code[-1] not in ("5", "7", "K", "L"):
            continue
        sibling = by_code.get(code[:5] + "0")
        if sibling is None or sibling["code"] in seen:
            continue  # 스냅샷에 보통주가 없거나 이미 목록에 있음
        if not sibling.get("t_roe"):
            continue  # ROE 가 없으면 상속 소스가 될 수 없음(등록 조건과 동일)
        picked.append(("우선주 상속용 보통주 짝", sibling))
        seen.add(sibling["code"])
    return picked


def build_frozen_input():
    """실수집 스냅샷에서 얼린 입력 payload 를 만듭니다."""
    snap = json.loads(_SOURCE_SNAPSHOT.read_text(encoding="utf-8"))
    stocks = snap["stocks"]
    picked = _pick_branch_covering_stocks(stocks)

    stocks_raw, items, vols, shares, yfpe = [], {}, {}, {}, {}
    coverage = {}
    for label, s in picked:
        code = s["code"]
        coverage.setdefault(label, []).append(code)

        # 수집기가 `enrich_quant_metrics` 에 넘기는 입력 쪽 필드만 재구성합니다.
        #
        # 🔴 t_roe 되돌리기 — 스냅샷의 `t_roe` 는 **이미 우선주 상속이 끝난 값**입니다.
        #    그대로 입력에 넣으면 상속이 다시 일어날 이유가 없어져(값이 이미 0이 아님),
        #    60줄짜리 상속 전처리 블록이 기준선에서 한 번도 안 밟힙니다. 네이버 시총 표는
        #    우선주 ROE 를 0 으로 주므로, 상속 흔적(`t_roe_inherited_from`)이 있는 종목은
        #    입력을 0 으로 되돌려 실제 수집 때와 같은 출발점을 만듭니다.
        raw_t_roe = 0 if s.get("t_roe_inherited_from") else s.get("t_roe")
        stocks_raw.append({
            "code": code,
            "name": s.get("name"),
            "price": s.get("price"),
            "t_per": s.get("t_per_measured", s.get("t_per")),
            "t_roe": raw_t_roe,
            "market": s.get("market"),
            "market_cap": s.get("market_cap"),
            "rank": s.get("rank"),
            "is_visible": s.get("is_visible"),
        })

        # 네이버 종목 상세가 돌려주던 값 — 스냅샷에 남은 실측치로 재구성합니다.
        dps_source = s.get("dps_source")
        items[code] = {
            "t_per": s.get("t_per_primary", s.get("t_per_measured")),
            "t_eps": s.get("t_eps"),
            "f_per": s.get("f_per"),
            "f_eps": s.get("f_eps"),
            "div_yield": (s.get("sh_return") if s.get("sh_return_basis") else None),
            "dps": s.get("dps"),
            "outstanding_shares": s.get("outstanding_shares"),
            "t_pbr": s.get("t_pbr"),
            "ev_ebitda": s.get("ev_ebitda"),
            "f_roe": s.get("f_roe"),
            "raw_period": "TTM",
            "dps_status": (
                "inherited_from_common" if dps_source == "inherited_from_common"
                else "no_dividend_confirmed" if dps_source == "no_dividend_confirmed"
                else "not_collected" if dps_source == "not_collected"
                else "naver_financial_statement"
            ),
            "dps_inherited_from": s.get("dps_inherited_from"),
            "div_yield_row_found": dps_source is not None,
            "div_yield_row_explicit_na": dps_source == "no_dividend_confirmed",
            "errors": [],
        }
        assert set(items[code]) == set(ITEM_KEYS), \
            f"item 키 집합이 _empty_item_info 와 다릅니다: {sorted(set(items[code]) ^ set(ITEM_KEYS))}"

        vols[code] = s.get("vol_std")
        if s.get("outstanding_shares"):
            shares[code] = s["outstanding_shares"]
        suffix = ".KQ" if s.get("market") == "KOSDAQ" else ".KS"
        # 교차검증이 "이상 있음/없음" 양쪽을 다 밟도록 결정적으로 배분합니다.
        fp = s.get("f_per")
        if fp:
            # 우선주 코드는 끝자리가 K/L 이라 int() 로 못 읽습니다 — 코드 전체의
            # 문자 합으로 결정적으로 배분합니다(무작위 아님, 같은 코드면 항상 같은 쪽).
            yfpe[f"{code}{suffix}"] = round(
                fp * (1.30 if sum(ord(c) for c in code) % 2 else 1.02), 4)

    return {
        "_note": (
            "enrich_quant_metrics 특성화 테스트용으로 얼린 입력입니다. "
            "실수집 스냅샷(data/kospi200_pegy_latest.json)에서 뽑은 실데이터이며, "
            "저장소 데이터가 갱신돼도 이 파일은 바뀌지 않습니다(움직이는 과녁 방지). "
            "tests/_enrich_baseline.py 머리말 참고."
        ),
        "_coverage": coverage,
        "stocks_raw": stocks_raw,
        "items": items,
        "volatility": vols,
        "shares_lookup": shares,
        "yfinance_forward_pe": yfpe,
    }


def regenerate():
    FIXTURES.mkdir(exist_ok=True)
    payload = build_frozen_input()
    INPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✅ 얼린 입력: {INPUT_PATH}  ({len(payload['stocks_raw'])}종목)")
    for label, codes in payload["_coverage"].items():
        print(f"   · {label}: {len(codes)}개")

    result = run_with_frozen_input(payload)
    BASELINE_PATH.write_text(canonical(result) + "\n", encoding="utf-8")
    print(f"✅ 기준선: {BASELINE_PATH}  ({len(result)}종목)")

    # 결정적인지 즉시 확인 — 두 번 돌려 같지 않으면 기준선으로 쓸 수 없습니다.
    again = run_with_frozen_input(payload)
    if canonical(again) != canonical(result):
        raise SystemExit(
            "🔴 두 번 돌린 결과가 다릅니다 — 이 함수에 아직 비결정적 요소가 남아 있습니다.\n"
            "   기준선으로 쓸 수 없으니 원인을 먼저 찾으세요(난수·시각·정렬 불안정 등)."
        )
    print("✅ 두 번 실행 결과 동일 — 결정적입니다.")


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        regenerate()
    else:
        print(__doc__)
        print("기준선을 다시 만들려면: python tests/_enrich_baseline.py --regenerate")
