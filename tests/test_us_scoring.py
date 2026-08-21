# tests/test_us_scoring.py
"""
🇺🇸 미국주식 스코어링·전수수집 경로 오프라인 검증 (네트워크 불필요)

⚠️ 이 세션의 샌드박스는 외부 네트워크가 프록시에서 차단(403)돼 있어 **실제 550종목 수집을
   실행하지 못했습니다.** 대신 아래 3가지로 검증합니다.
     ① 실제 로컬 수집 결과(data/us_sample/sample_processed_*.json, 12종목 실데이터)를
        입력으로 파생계산 → 가드레일 → 2차 패스 스코어링 전 구간을 통과시켜 봅니다.
     ② 합성 데이터로 극단 케이스(적자·리츠·은행·고성장·목표가 캡·역성장·PER 오염·데이터 결측)를 봅니다.
     ③ `_http_get` 만 가짜로 바꿔 `run_us_collector()` 전체 배선(유니버스→수집→스코어링→저장)을
        end-to-end 로 한 번 돌려 봅니다(HTTP 호출만 대체, 나머지 코드는 실제 경로 그대로).

실행: python tests/test_us_scoring.py
"""
import io
import json
import os
import sys
import tempfile
from glob import glob
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))

import collector_us_stocks as C
from utils.company_names_kr import clean_company_name, resolve_korean_name, transliterate_to_hangul
from utils.scoring_us import (
    apply_us_guardrail,
    calculate_us_quant_score,
    classify_sector_flags,
    compute_population_stats,
    derive_valuation,
    score_all,
)

FAILURES = []


def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


def section(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def test_us_scoring_full_suite():
    """미국주식 스코어링·전수수집 배선 오프라인 검증 78건을 순서대로 실행합니다.

    🔴 2026-08-21 발견 — 원래 이 파일 전체가 모듈 최상위(들여쓰기 없는 스크립트)로 있었고,
    맨 끝의 `if FAILURES: ... sys.exit(1)` 도 `if __name__ == "__main__":` 로 감싸여 있지
    않아 **pytest 로 수집(import)만 해도 곧바로 실행되고 그 자리에서 죽었습니다** — 다른
    7개 파일의 `check()`/`FAILURES` 버그(개별 test_* 함수가 실패해도 pytest 가 안 죽던 것)
    와는 반대로, 이 파일은 이 클라우드 작업 사본에 `collector_us_stocks` 모듈이 없어서
    pytest 수집 자체가 `ModuleNotFoundError` 로 막혀 있었고(실제 저장소·오너 PC 에는 그
    모듈이 있습니다 — 이 사본만의 오래된 구멍), 그래서 이 문제가 드러나지 않고 있었습니다.
    이번에 그 모듈을 오너 PC에서 가져와 실제로 실행해보고서야 이 파일을 pytest 로 돌리면
    수집 단계에서 곧바로 죽어버린다는 걸 확인했습니다.

    고친 방법: 섹션 1~6 전체(원래 모듈 최상위 코드)를 그대로 이 함수 안으로 옮기고(로직은
    단 한 줄도 안 바꿨습니다 — 들여쓰기만 4칸 추가), 맨 끝 판정만 `sys.exit(1)` 대신
    `assert not FAILURES` 로 바꿨습니다. 그래서 이제:
      · `pytest tests/test_us_scoring.py` — 이 함수가 평범한 test_* 함수로 수집되어,
        실패가 있으면 pytest 가 실제로 빨간불을 냅니다.
      · `python tests/test_us_scoring.py` — 이 파일 독스트링에 적힌 원래 실행법도 맨 아래
        `if __name__ == "__main__":` 로 그대로 유지되어 똑같이 동작합니다.
    """
    FAILURES.clear()  # 방어적 초기화 — 이 함수가 두 번 불릴 일은 없지만 혹시 몰라 비워둡니다

    # =============================================================================
    # 1. 실데이터(로컬 샘플 12종목)로 전 구간 통과
    # =============================================================================
    section("1. 실데이터 검증 — data/us_sample 의 실제 12종목 수집 결과")

    sample_files = sorted(glob(str(ROOT / "data" / "us_sample" / "sample_processed_*.json")))
    check(bool(sample_files), "샘플 파일 존재", f"(찾은 파일 {len(sample_files)}개)")

    if sample_files:
        with open(sample_files[-1], "r", encoding="utf-8") as f:
            sample = json.load(f)
        items = sample.get("items", [])
        check(len(items) >= 10, f"샘플 종목 수 {len(items)}개")

        real_stocks = []
        for it in items:
            s = dict(it)
            s.update(derive_valuation(s))
            s = apply_us_guardrail(s)
            real_stocks.append(s)

        meta = score_all(real_stocks)
        pop = meta["population_stats"]
        check(pop["growth"] is not None and pop["roe"] is not None,
              "12종목 실데이터로 population 통계(성장률·ROE) 산출됨", str(pop))
        check(all(s.get("price") for s in real_stocks), "전 종목 장마감 종가 존재")
        check(all(s.get("is_valid") for s in real_stocks), "전 종목 가드레일 통과")
        check(all(s.get("quant_score") is not None for s in real_stocks),
              "전 종목 퀀트 스코어 산출됨(측정 불가 없음)")
        check(all(0 <= s["quant_score"] <= s["score_max"] for s in real_stocks),
              "모든 점수가 0 ~ 만점 범위 안")

        by_sym = {s["symbol"]: s for s in real_stocks}

        # SUN: 3년 EPS 성장 전망 -5.37% → 실효성장률 음수 → PEGY 산출 불가 + 역성장 컷오프
        sun = by_sym.get("SUN")
        if sun:
            check(sun["g_eff"] is not None and sun["g_eff"] < 0, f"SUN 실효성장률 음수 ({sun['g_eff']})")
            check(sun["f_pegy"] is None, "SUN PEGY 미산출 (0.1 같은 바닥값 대입 안 함)")
            check("역성장" in sun["badge"], f"SUN 역성장 배지 ({sun['badge']})")
            check(sun["score_max"] < 100, f"SUN 만점이 100 미만 (PEGY 35점 제외됨 → {sun['score_max']})")
            check(any("PEGY" in x for x in sun["score_excluded_items"]),
                  "SUN 배점 제외 사유에 PEGY 명시", str(sun["score_excluded_items"]))

        # NVDA: 저평가 + 목표가 미달(현재가 < 목표가)
        nvda = by_sym.get("NVDA")
        if nvda:
            check(nvda["f_pegy"] is not None and nvda["f_pegy"] < 0.95, f"NVDA PEGY 저평가 구간 ({nvda['f_pegy']})")
            check("저평가" in nvda["badge"], f"NVDA 저평가 배지 ({nvda['badge']})")
            check(nvda["f_eps_calculated"] is True and nvda["f_eps_source"] == "calculated_price_div_forward_per",
                  "NVDA Forward EPS 는 계산값으로 명시 마킹됨")
            check(abs(nvda["f_eps"] - nvda["price"] / nvda["f_per"]) < 1e-3,
                  "Forward EPS = 종가 ÷ Forward PER (소수점 4자리 반올림 오차 내)")

        # INCY: 주주환원율 음수(-3.09%) — 0으로 잘라내지 않고 그대로 반영되는지
        incy = by_sym.get("INCY")
        if incy:
            check(incy["sh_return"] < 0, f"INCY 주주환원율 음수 그대로 유지 ({incy['sh_return']})")
            check(incy["g_eff"] == round(incy["growth"] + incy["sh_return"], 2),
                  "INCY 실효성장률에 음수 주주환원율이 그대로 합산됨")

        # 목표가는 우리 모델 값이고, 애널리스트 목표가는 소스 실측값 — 서로 다른 필드로 유지되는지
        both = [s for s in real_stocks if s.get("f_target") and s.get("analyst_target")]
        check(len(both) >= 8, f"모델 목표가·애널리스트 목표가를 별도 필드로 동시 보유 ({len(both)}종목)")


    # =============================================================================
    # 2. 합성 데이터 — 업종/극단 케이스
    # =============================================================================
    section("2. 합성 데이터 — 업종별 특수 케이스 & 극단 케이스")

    # 2-1. 적자기업 (소스가 PER 을 n/a 로 주고 EPS 는 Loss Per Share 음수)
    loss = {
        "symbol": "LOSS", "name": "Lossmaker Inc. Common Stock", "price": 20.0,
        "t_per": None, "f_per": 40.0, "t_eps": -1.85, "bps": 3.2, "t_roe": -22.0,
        "roic": -15.0, "sh_return": 0.0, "growth": 30.0, "piotroski_f": 3, "beta": 1.8,
        "net_income": -450000000.0, "industry": "Biotechnology",
    }
    loss.update(derive_valuation(loss))
    check(loss["is_trailing_loss"] is True, "적자기업: is_trailing_loss=True", str(loss["loss_evidence"]))
    check(loss["graham_target"] is None, "적자기업: 그레이엄 넘버 산출 안 함(제곱근 안 음수)")
    check(loss["t_fair"] is None, "적자기업: Trailing 적정가 산출 안 함")
    res = calculate_us_quant_score(
        f_pegy=loss["f_pegy"], t_roe=loss["t_roe"], roic=loss["roic"], sh_return=loss["sh_return"],
        piotroski=loss["piotroski_f"], beta=loss["beta"], f_per=loss["f_per"], price=loss["price"],
        f_target=loss["f_target"], growth=loss["growth"],
    )
    check(res["is_cutoff"] is True and "역성장/적자" in res["badge"], f"적자기업: 역성장/적자 컷오프 ({res['badge']})")
    check(res["quant_score"] <= res["score_max"] * 0.30, "적자기업: 점수 상한이 만점의 30% 이하로 눌림")

    # 2-2. 리츠 (PER n/a + Price/FFO 존재)
    reit = {
        "symbol": "REIT", "name": "Mall REIT Inc. Common Stock", "price": 42.0,
        "t_per": None, "f_per": 28.0, "price_ffo": 11.4, "t_eps": 0.9, "bps": 15.0,
        "t_roe": 6.0, "roic": 4.5, "sh_return": 5.2, "growth": 4.0, "piotroski_f": 6,
        "beta": 1.2, "industry": "REIT - Retail",
    }
    reit.update(derive_valuation(reit))
    check(reit["is_reit"] is True, "리츠: is_reit=True (Price/FFO 존재로 판정)")
    check(any("리츠" in i for i in reit["data_issues"]), "리츠: PER n/a 사유를 '정상'으로 기록", str(reit["data_issues"]))
    check(reit["value_trap"] is True, "리츠(저ROE/ROIC): 착시 저평가 태그")

    # 2-3. 은행 (ROIC n/a)
    bank = {
        "symbol": "BANK", "name": "Big Bank Corporation Common Stock", "price": 180.0,
        "t_per": 12.0, "f_per": 11.5, "t_eps": 15.0, "bps": 95.0, "t_roe": 17.0,
        "roic": None, "sh_return": 4.5, "growth": 8.0, "piotroski_f": 7, "beta": 0.95,
        "industry": "Banks - Diversified",
    }
    bank.update(derive_valuation(bank))
    check(bank["is_financial_sector"] is True, "은행: 금융업종 판정(industry 키워드)")
    check(bank["graham_is_financial_sector"] is True, "은행: 그레이엄 넘버에 금융업종 경고 플래그")
    res_bank = calculate_us_quant_score(
        f_pegy=bank["f_pegy"], t_roe=bank["t_roe"], roic=bank["roic"], sh_return=bank["sh_return"],
        piotroski=bank["piotroski_f"], beta=bank["beta"], f_per=bank["f_per"], price=bank["price"],
        f_target=bank["f_target"], growth=bank["growth"], f_target_capped=bank["f_target_capped"],
    )
    check(res_bank["score_max"] == 85, f"은행: ROIC 15점이 배점에서 빠져 만점 85 ({res_bank['score_max']})")
    check(any("ROIC" in x for x in res_bank["excluded_items"]), "은행: 제외 사유에 ROIC 명시")

    # 2-4. 고성장 (성장률 150%) — f_pegy 는 그대로 두고 점수만 보수화
    hyper = dict(bank, symbol="HYPER", growth=150.0, f_per=25.0, roic=20.0, industry="Software")
    hyper = {k: v for k, v in hyper.items() if k in (
        "symbol", "name", "price", "t_per", "f_per", "t_eps", "bps", "t_roe", "roic",
        "sh_return", "growth", "piotroski_f", "beta", "industry")}
    hyper.update(derive_valuation(hyper))
    res_h = calculate_us_quant_score(
        f_pegy=hyper["f_pegy"], t_roe=hyper["t_roe"], roic=hyper["roic"], sh_return=hyper["sh_return"],
        piotroski=hyper["piotroski_f"], beta=hyper["beta"], f_per=hyper["f_per"], price=hyper["price"],
        f_target=hyper["f_target"], growth=hyper["growth"], f_target_capped=hyper["f_target_capped"],
    )
    # 성장률 150% → 성장률 상한 35%p 로 절단, 주주환원 4.5%p 는 상한(10) 미만이라 그대로 → 39.5%p
    check(hyper["g_eff"] == 39.5,
          f"고성장: 성장률이 상한 35%p 로 절단되어 g_eff=39.5 ({hyper['g_eff']})")
    check(hyper["g_eff_uncapped"] == 154.5, f"고성장: 캡 미적용 원값 보존 ({hyper['g_eff_uncapped']})")
    check(hyper["g_eff_capped"] is True, "고성장: g_eff_capped 플래그로 절단 사실 기록")
    check(res_h["growth_score_capped"] is True, "고성장: PEGY '점수'만 보수 반영 플래그")
    check(hyper["f_pegy"] == round(hyper["f_per"] / hyper["g_eff"], 2),
          "고성장: f_pegy 값 자체는 덮어쓰지 않음(배지·목표가 일관성 유지)")

    # 2-5. 목표가 캡 (현재가 대비 2.5배 초과)
    cheap = {
        "symbol": "CAP", "name": "Deep Value Co. Common Stock", "price": 5.0,
        "t_per": 3.0, "f_per": 2.5, "t_eps": 1.7, "bps": 9.0, "t_roe": 25.0,
        "roic": 20.0, "sh_return": 6.0, "growth": 30.0, "piotroski_f": 8, "beta": 1.1,
        "industry": "Steel",
    }
    cheap.update(derive_valuation(cheap))
    check(cheap["f_target_capped"] is True, "목표가 캡: f_target_capped=True")
    check(cheap["f_target"] == cheap["price"] * 2.5, f"목표가 캡: 현재가×2.5 로 절단 ({cheap['f_target']})")
    check(cheap["f_target_uncapped"] > cheap["f_target"], "목표가 캡: 캡 미적용 원값도 함께 보존")
    check("상한" in (cheap["f_target_cap_reason"] or ""), "목표가 캡: 사유 문자열 기록")

    # 2-6. Forward PER 오염 (PER 500배)
    dirty = dict(cheap, symbol="DIRTY", f_per=500.0)
    dirty = {k: v for k, v in dirty.items() if k in (
        "symbol", "name", "price", "t_per", "f_per", "t_eps", "bps", "t_roe", "roic",
        "sh_return", "growth", "piotroski_f", "beta", "industry")}
    dirty.update(derive_valuation(dirty))
    dirty_g = apply_us_guardrail(dirty)
    check(dirty_g.get("forward_per_extreme") is True, "PER 오염: forward_per_extreme 플래그")
    check(dirty_g.get("is_valid") is True, "PER 오염: 종목 전체를 차단하지 않음(Trailing 은 정상 노출)")
    res_d = calculate_us_quant_score(
        f_pegy=dirty["f_pegy"], t_roe=dirty["t_roe"], roic=dirty["roic"], sh_return=dirty["sh_return"],
        piotroski=dirty["piotroski_f"], beta=dirty["beta"], f_per=dirty["f_per"], price=dirty["price"],
        f_target=dirty["f_target"], growth=dirty["growth"],
    )
    check(res_d["forward_available"] is False, "PER 오염: forward_available=False")
    check(res_d["quant_score"] <= res_d["score_max"] * 0.13, "PER 오염: 점수 상한 12% 이하로 눌림")

    # 2-7. 데이터 결측 — 종가 없음 / 모든 지표 없음
    res_nopx = calculate_us_quant_score(price=None)
    check(res_nopx["quant_score"] is None and res_nopx["score_max"] is None,
          "종가 없음: 점수를 0점이 아니라 None(측정 불가)으로 반환")
    res_empty = calculate_us_quant_score(price=10.0)
    check(res_empty["quant_score"] is None, "채점 가능 항목이 하나도 없으면 0점이 아니라 '측정 불가'")

    # 2-8. Forward 컨센서스 없음 (Trailing 만 존재) — 섹션 마스킹 대상, 종목 차단 아님
    tonly = {
        "symbol": "TONLY", "name": "Trailing Only Inc. Common Stock", "price": 30.0,
        "t_per": 10.0, "f_per": None, "t_eps": 3.0, "bps": 20.0, "t_roe": 14.0,
        "roic": 11.0, "sh_return": 3.0, "growth": None, "piotroski_f": 7, "beta": 0.9,
        "industry": "Industrial",
    }
    tonly.update(derive_valuation(tonly))
    tonly = apply_us_guardrail(tonly)
    res_t = calculate_us_quant_score(
        f_pegy=tonly["f_pegy"], t_roe=tonly["t_roe"], roic=tonly["roic"], sh_return=tonly["sh_return"],
        piotroski=tonly["piotroski_f"], beta=tonly["beta"], f_per=tonly["f_per"], price=tonly["price"],
        f_target=tonly["f_target"], growth=tonly["growth"],
    )
    check(tonly["is_valid"] is True, "Forward 결측: 종목 전체를 차단하지 않음")
    check(tonly["forward_data_missing"] is True, "Forward 결측: forward_data_missing 플래그")
    check(res_t["score_max"] == 65, f"Forward 결측: PEGY 35점만 빠져 만점 65 ({res_t['score_max']})")
    check("Trailing만 검증됨" in res_t["badge"], f"Forward 결측 전용 배지 ({res_t['badge']})")

    # 2-9. population 통계가 없을 때(표본 부족) 안전 폴백
    res_nopop = calculate_us_quant_score(
        f_pegy=None, t_roe=-5.0, roic=None, sh_return=1.0, piotroski=4, beta=1.0,
        f_per=None, price=10.0, growth=None,
        growth_pop_stats=None, roe_pop_stats=None, pegy_pop_stats=None,
    )
    check(res_nopop["quant_score"] is not None, "population 통계 없어도 크래시 없이 중간값 캡으로 처리")

    pop_small = compute_population_stats([{"growth": 1.0, "t_roe": 2.0, "f_pegy": 1.0}] * 3)
    check(pop_small["growth"] is None, "표본 5개 미만이면 population 통계를 만들지 않음")


    # =============================================================================
    # 3. 한글 종목명 (정식 사전 우선 + 규칙 기반 음역)
    # =============================================================================
    section("3. 한글 종목명 — 사전 우선 / 음역 폴백")

    r = resolve_korean_name("NVDA", "NVIDIA Corporation Common Stock")
    check(r["korean_name"] == "엔비디아" and r["source"] == "official_dict",
          f"정식 한글명 사전 우선 적용 (NVDA → {r['korean_name']})")
    check(r["is_transliterated"] is False, "정식 한글명은 음역 배지를 붙이지 않음")

    r2 = resolve_korean_name("ZZZZ", "Sunoco LP Common Units representing limited partner interests")
    check(r2["source"] == "transliterated" and bool(r2["korean_name"]),
          f"사전에 없으면 자동 음역 (→ {r2['korean_name']})")
    check(r2["is_transliterated"] is True, "음역 결과에는 배지를 붙이도록 플래그")
    check(all("가" <= ch <= "힣" for ch in r2["korean_name"]), "음역 결과가 한글 음절로만 구성됨")

    check(clean_company_name("Alphabet Inc. Class A Common Stock") == "Alphabet",
          f"상품 설명·법인격 제거 (→ {clean_company_name('Alphabet Inc. Class A Common Stock')})")
    check(clean_company_name("Macerich Company (The) Common Stock") == "Macerich",
          f"괄호 표기 정리 (→ {clean_company_name('Macerich Company (The) Common Stock')})")
    check(clean_company_name("Sea Limited American Depositary Shares each representing one Class A "
                             "Ordinary Share") == "Sea", "ADR 설명 문구 제거")
    check(transliterate_to_hangul("Preferred Bank Common Stock") != "", "일반 회사명도 음역 가능")

    # 오너가 사전 한 줄만 추가하면 즉시 반영되는 구조인지(오버라이드 우선순위)
    from utils.company_names_kr import KR_NAME_OVERRIDES
    KR_NAME_OVERRIDES["ZZZZ"] = "테스트오버라이드"
    r3 = resolve_korean_name("ZZZZ", "Sunoco LP")
    check(r3["korean_name"] == "테스트오버라이드" and r3["source"] == "official_dict",
          "사전 오버라이드가 음역보다 우선")
    del KR_NAME_OVERRIDES["ZZZZ"]


    # =============================================================================
    # 4. 상단 지수 3종 소스
    # =============================================================================
    # 2026-08-07: 최초 Stooq CSV 소스(parse_index_quote_csv)가 오너 실측에서 3종 전부
    # HTTP 404 로 확인돼, stockanalysis.com ETF 프록시(fetch_one_index_quote) 방식으로
    # 교체했습니다. 이 부분의 상세 오프라인 테스트(정상/지수 불일치/요청 실패 3케이스)는
    # tests/test_us_stocks.py 의 test_index_proxy() 로 옮겨 그쪽에서 검증합니다 — 여기서는
    # import 가 깨지지 않았는지만 가볍게 확인합니다(중복 로직 방지).
    # =============================================================================
    section("4. 상단 지수 3종 소스 (fetch_one_index_quote — 상세 검증은 test_us_stocks.py)")
    check(callable(C.fetch_one_index_quote), "fetch_one_index_quote import 가능")
    check(callable(C.build_index_proxy_url), "build_index_proxy_url import 가능")
    check(C.build_index_proxy_url("spy") == "https://stockanalysis.com/etf/spy/", "ETF 프록시 URL 빌더")


    # =============================================================================
    # 5. end-to-end — run_us_collector() 전체 배선 (HTTP 만 가짜로 대체)
    # =============================================================================
    section("5. end-to-end 배선 검증 — run_us_collector() (HTTP 만 가짜)")

    FAKE_UNIVERSE_ROWS = [
        ("AAA", "Alpha Industries Inc. Common Stock", 100.0, 900e9, "Semiconductors"),
        ("BBB", "Beta Bank Corporation Common Stock", 50.0, 500e9, "Banks - Regional"),
        ("CCC", "Gamma Mall REIT Inc. Common Stock", 30.0, 300e9, "REIT - Retail"),
        ("DDD", "Delta Losses Inc. Common Stock", 8.0, 200e9, "Biotechnology"),
        ("PPP", "Omega Corp 5.500% Junior Subordinated Notes due 2070", 25.0, 150e9, "Utilities"),
    ]
    # 소스 건전성 가드(행 700개 미만이면 중단)를 통과시키기 위한 채움용 행 — 실제 필터 동작은
    # 위 5개 행으로 검증하고, 나머지는 시가총액이 훨씬 작은 더미입니다.
    FILLER = [(f"F{i:04d}", f"Filler {i} Company Inc. Common Stock", 1.0, 1e9 - i, "Misc") for i in range(800)]

    UNIVERSE_CSV = "symbol,name,price,marketCap,volume,industry\n" + "".join(
        f"{s},{n},{p},{m},1000,{ind}\n" for s, n, p, m, ind in (FAKE_UNIVERSE_ROWS + FILLER)
    )


    def _stat_html(rows, price, asof="Aug 6, 2026, 4:00 PM EDT"):
        body = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
        # 실제 페이지처럼 "At close:" 라벨과 타임스탬프를 별도 노드로 분리 (TASK_HISTORY #48 버그 재현 구조)
        return f"""
        <html><body>
          <div><span>{price}</span><span>+1.20 (0.55%)</span><span>At close:</span><span>{asof}</span></div>
          <table>{body}</table>
        </body></html>
        """


    COMMON_ROWS = [
        ("Market Cap", "900.00B"), ("Shares Outstanding", "9.00B"), ("PE Ratio", "25.00"),
        ("Forward PE", "20.00"), ("PB Ratio", "5.00"), ("EV / EBITDA", "18.00"),
        ("Return on Equity (ROE)", "30.00%"), ("Return on Invested Capital (ROIC)", "22.00%"),
        ("Return on Assets (ROA)", "15.00%"), ("Beta (5Y)", "1.10"),
        ("Earnings Per Share (EPS)", "4.00"), ("Book Value Per Share", "20.00"),
        ("Dividend Per Share", "1.00"), ("Dividend Yield", "1.00%"),
        ("Buyback Yield", "2.00%"), ("Shareholder Yield", "3.00%"),
        ("Price Target", "120.00"), ("Analyst Consensus", "Buy"), ("Analyst Count", "30"),
        ("EPS Growth Forecast (3Y)", "18.00%"), ("Revenue Growth Forecast (3Y)", "12.00%"),
        ("Piotroski F-Score", "7"), ("Altman Z-Score", "10.00"),
    ]
    BANK_ROWS = [(k, ("n/a" if k == "Return on Invested Capital (ROIC)" else v)) for k, v in COMMON_ROWS]
    REIT_ROWS = [(k, ("n/a" if k == "PE Ratio" else v)) for k, v in COMMON_ROWS] + [("Price/FFO Ratio", "11.40")]
    LOSS_ROWS = [
        (k, v) for k, v in COMMON_ROWS
        if k not in ("PE Ratio", "Earnings Per Share (EPS)", "Forward PE")
    ] + [("PE Ratio", "n/a"), ("Loss Per Share", "-1.85"), ("Forward PE", "40.00")]

    FAKE_PAGES = {
        "AAA": _stat_html(COMMON_ROWS, "100.00"),
        "BBB": _stat_html(BANK_ROWS, "50.00"),
        "CCC": _stat_html(REIT_ROWS, "30.00"),
        "DDD": _stat_html(LOSS_ROWS, "8.00"),
    }


    def _etf_proxy_html(price, prev_close, tracked_label):
        return f"""
        <html><body>
          <div>{price}</div>
          <div>+1.00 (0.10%)</div>
          <div>Aug 6, 2026, 4:00 PM EDT - Market closed</div>
          <table>
            <tr><td>Previous Close</td><td>{prev_close}</td></tr>
            <tr><td>Index Tracked</td><td>{tracked_label}</td></tr>
          </table>
        </body></html>
        """


    # 2026-08-07: Stooq CSV → stockanalysis.com ETF 프록시(/etf/spy 등)로 소스 교체
    FAKE_INDEX_PAGES = {
        "spy":  _etf_proxy_html("768.56", "767.36", "S&P 500"),
        "oneq": _etf_proxy_html("104.78", "102.07", "NASDAQ Composite Index"),
        "dia":  _etf_proxy_html("450.10", "451.00", "Dow Jones Industrial Average"),
    }


    class _FakeResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200


    def _fake_http_get(url, timeout=None):
        if url.endswith("all.csv"):
            return _FakeResponse(UNIVERSE_CSV)
        for proxy_sym, html in FAKE_INDEX_PAGES.items():
            if f"/etf/{proxy_sym}/" in url.lower():
                return _FakeResponse(html)
        for sym, html in FAKE_PAGES.items():
            if f"/stocks/{sym.lower()}/" in url.lower():
                return _FakeResponse(html)
        raise RuntimeError(f"테스트에 없는 URL 요청: {url}")


    _orig_http_get = C._http_get
    _orig_data_path = C._data_path
    _orig_sleep = C._polite_sleep
    tmpdir = tempfile.mkdtemp(prefix="us_collect_test_")
    C._http_get = _fake_http_get
    C._data_path = lambda filename: os.path.join(tmpdir, filename)
    C._polite_sleep = lambda: None      # 테스트에서만 슬립 생략 (실제 수집 경로에는 영향 없음)

    try:
        snapshot_path = C.run_us_collector(target_size=4, delay=False)
        with open(snapshot_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        meta = payload["metadata"]
        stocks = payload["stocks"]
        syms = [s["symbol"] for s in stocks]

        check(len(stocks) == 4, f"4종목 수집 완료 ({syms})")
        check("PPP" not in syms, "채권/노트(PPP)는 유니버스 필터에서 제외됨")
        check(meta["currency"] == "USD", "메타데이터 통화 USD")
        check("failed_tickers" in meta, "실패 종목 목록 필드 존재 (조용히 건너뛰지 않음)")
        check(meta["failed_count"] == 0, f"실패 0건 ({meta['failed_tickers']})")
        check(meta["scoring"]["population_sample_size"] == 4, "2차 패스 population 표본 수 기록")
        check(meta["indices"]["sp500"]["intraday_change_pct"] is not None,
              f"상단 지수 3종 메타데이터에 저장됨 (등락률={meta['indices']['sp500']['intraday_change_pct']}%)")
        check(meta["indices"]["nasdaq"]["tracked_index_verified"] is True,
              "나스닥종합 ETF 프록시(ONEQ)의 'Index Tracked' 라벨 검증 통과")
        check(meta["indices"]["sp500"]["is_etf_proxy"] is True, "지수 3종이 ETF 프록시 출처임을 메타데이터에 표기")
        check(meta["session_dates_from_source"] == {"2026-08-06": 4},
              f"세션 날짜를 페이지 타임스탬프에서 확보 ({meta['session_dates_from_source']})")

        got = {s["symbol"]: s for s in stocks}
        check(got["AAA"]["price"] == 100.0 and not got["AAA"]["price_calculated"],
              "장마감 종가를 (라벨/값 분리 구조에서도) 직접 파싱")
        check(got["BBB"]["roic"] is None and got["BBB"]["score_max"] == 85,
              f"은행: ROIC n/a → 만점 85 ({got['BBB']['score_max']})")
        check(got["CCC"]["is_reit"] and got["CCC"]["price_ffo"] == 11.4, "리츠: Price/FFO 수집 + 리츠 판정")
        check(got["DDD"]["t_eps"] == -1.85 and got["DDD"]["is_trailing_loss"],
              "적자기업: Loss Per Share 음수 수집 + 적자 판정")
        check(got["DDD"]["graham_target"] is None, "적자기업: 그레이엄 넘버 미산출")
        check(all(s.get("name_kr") for s in stocks), "전 종목 한글 표기 생성됨")
        check(all(s.get("quant_score") is not None for s in stocks), "전 종목 스코어 산출됨")
        check(os.path.exists(os.path.join(tmpdir, "us_stocks_raw_latest.json")),
              "raw 스냅샷이 가공 스냅샷과 분리 저장됨 (§0-3-3)")
        check(os.path.exists(os.path.join(tmpdir, "us_summary_history.json")), "요약 이력 파일 생성됨")

        # 두 번째 실행 — 히스테리시스(직전 추적 목록 로드)가 동작하는지
        prev = C.load_previously_tracked_symbols(snapshot_path)
        check(prev == set(syms), f"직전 추적 티커 로드 ({len(prev)}개)")
    finally:
        C._http_get = _orig_http_get
        C._data_path = _orig_data_path
        C._polite_sleep = _orig_sleep


    # =============================================================================
    # 6. 전수수집 이어하기(체크포인트) — 2026-08-07 신설
    #    오너 로컬 실행에서 550종목 수집이 HTTP 429로 중간에 끊긴 실측 문제 대응책입니다.
    #    3번째 종목(CCC)에서 강제로 차단시켜 ① 체크포인트 저장 ② 재실행 시 이어서 완주
    #    ③ 완주 후 체크포인트 정리, 3가지를 실제 run_us_collector() 경로로 검증합니다.
    # =============================================================================
    section("6. 전수수집 이어하기(체크포인트, HTTP 429 대응)")

    _block_state = {"active": True}


    def _fake_http_get_with_block(url, timeout=None):
        if url.endswith("all.csv"):
            return _FakeResponse(UNIVERSE_CSV)
        for proxy_sym, html in FAKE_INDEX_PAGES.items():
            if f"/etf/{proxy_sym}/" in url.lower():
                return _FakeResponse(html)
        if _block_state["active"] and "/stocks/ccc/" in url.lower():
            raise C.USSourceBlockedError("테스트용 강제 차단 (HTTP 429)")
        for sym, html in FAKE_PAGES.items():
            if f"/stocks/{sym.lower()}/" in url.lower():
                return _FakeResponse(html)
        raise RuntimeError(f"테스트에 없는 URL 요청: {url}")


    tmpdir2 = tempfile.mkdtemp(prefix="us_collect_resume_test_")
    C._http_get = _fake_http_get_with_block
    C._data_path = lambda filename: os.path.join(tmpdir2, filename)
    C._polite_sleep = lambda: None
    checkpoint_path = os.path.join(tmpdir2, "us_collect_checkpoint.json")

    try:
        blocked = False
        try:
            C.run_us_collector(target_size=4, delay=False)
        except C.USSourceBlockedError as e:
            blocked = True
            check("이어서 진행합니다" in str(e), "차단 메시지에 '이어하기' 안내 포함")
        check(blocked, "3번째 종목(CCC)에서 강제 차단되어 예외 발생")

        check(os.path.exists(checkpoint_path), "차단 시 체크포인트 파일 저장됨")
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            cp = json.load(f)
        completed_before = set(cp.get("completed_symbols") or [])
        check("CCC" not in completed_before and {"AAA", "BBB"} <= completed_before,
              f"체크포인트에 차단 전까지 완료된 종목만 기록됨 ({sorted(completed_before)})")
        check(not os.path.exists(os.path.join(tmpdir2, "us_stocks_latest.json")),
              "차단된 실행은 최종 스냅샷을 쓰지 않음(기존 데이터 보존, §0-3-2)")

        # 차단이 풀렸다고 가정하고 재실행 — 체크포인트에서 이어서 진행돼야 함(AAA/BBB 재요청 없음)
        _block_state["active"] = False
        snapshot_path2 = C.run_us_collector(target_size=4, delay=False)
        with open(snapshot_path2, "r", encoding="utf-8") as f:
            payload2 = json.load(f)
        syms2 = [s["symbol"] for s in payload2["stocks"]]
        check(set(syms2) == {"AAA", "BBB", "CCC", "DDD"}, f"재실행 후 4종목 전부 완료 ({syms2})")
        check(not os.path.exists(checkpoint_path), "전수 완주 후 체크포인트 파일 정리됨")

        # 다른 세션 날짜의 체크포인트는 재사용하지 않는지(§0-1 — 어제 종가와 오늘 종가 혼입 방지)
        stale_path = os.path.join(tmpdir2, "stale.json")
        C.save_collect_checkpoint(stale_path, "2020-01-01", [{"symbol": "ZZZ"}], [], [], ["ZZZ"])
        reloaded = C.load_collect_checkpoint(stale_path, "2099-01-01")
        check(reloaded["completed_symbols"] == [], "세션 날짜가 다른 체크포인트는 재사용하지 않고 빈 상태로 시작")
    finally:
        C._http_get = _orig_http_get
        C._data_path = _orig_data_path
        C._polite_sleep = _orig_sleep

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건")
        for f in FAILURES:
            print(f"   - {f}")
    else:
        print("✅ 전체 통과")
    print("=" * 74)
    assert not FAILURES, f"check() 로 기록된 실패 {len(FAILURES)}건: {FAILURES}"


if __name__ == "__main__":
    test_us_scoring_full_suite()
