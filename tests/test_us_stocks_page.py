# tests/test_us_stocks_page.py
"""
🇺🇸 미국주식 화면(`web/pages/us_stocks_page.py`) — 2026-08-29 재감사 회귀 테스트

이 화면은 NiceGUI `@ui.page` 화면이라 전체를 렌더링하려면 실제 서버가 필요하지만,
이번에 고친 항목들은 대부분 **순수 함수**(카드 HTML 조립, 필터 로직, 파일명용 날짜 선택)
이거나 다른 순수 함수(`render_summary_metrics`)를 부르는 자리라, NiceGUI 서버 없이
모듈만 import 해서 직접 검증할 수 있습니다(`test_dividend_page_calendar.py`와 같은 패턴).

대상 회귀:
  - H5: t_fair(과거 적정가)에 캡/바닥값 배지가 붙는지
  - M5/M6: roe_color/roic_color 가 constants_us 의 실제 착시 저평가 임계값을 쓰는지
  - L4: 실효성장률/모델 목표가 툴팁 숫자가 constants_us 값과 일치하는지
  - L3: 화면 상단 문구의 "상위 N개"가 US_TARGET_UNIVERSE_SIZE 와 일치하는지
  - M10: 다운로드 파일명이 스냅샷의 실제 거래일(세션 날짜)을 쓰는지
  - M11: 요약 이력이 로컬 파일 존재 여부만으로 건너뛰지 않는지
  - M12: 「저평가 우량주」 프리셋이 착시 저평가(value_trap) 종목을 제외하는지
  - L9: 세부 뱃지 프리셋에서 배지를 전부 해제하면 0건이 되는지(필터를 건너뛰지 않는지)
  - L13: "이전 동기화 대비" 델타에 비교 대상 날짜가 붙는지

실행: python tests/test_us_stocks_page.py
"""
import ast
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.constants_us import (
    US_FAILED_TICKERS_BANNER_RATIO,
    US_GEFF_TOTAL_CAP_PCT,
    US_GROWTH_CAP_PCT,
    US_SH_RETURN_CAP_PCT,
    US_STALE_SESSION_WARNING_DAYS,
    US_TARGET_PER_CAP,
    US_TARGET_PRICE_CAP_MULTIPLE,
    US_TARGET_UNIVERSE_SIZE,
    US_VALUE_TRAP_ROE_PCT,
    US_VALUE_TRAP_ROIC_PCT,
)
from web.pages.us_stocks_page import (
    _TITLE_TAIL,
    _snapshot_trading_date_iso,
    _snapshot_trading_date_str,
    apply_stock_filters,
    build_index_header_html,
    build_stock_card_html,
    compute_stale_days,
    select_badges_for_preset,
)

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print(f"  ❌ {msg}")
    else:
        print(f"  ✅ {msg}")


# =============================================================================
# H5: t_fair(과거 적정가) 캡/바닥값 배지
# =============================================================================
def test_h5_t_fair_badges():
    print("\n[재감사 H5] t_fair 캡/바닥값 배지")

    capped = build_stock_card_html(
        {"symbol": "AAA", "name": "AAA Corp", "t_fair": 100.0,
         "t_fair_capped": True, "t_fair_uncapped": 250.0},
        1,
    )
    check("🧮 상한 적용값" in capped, "t_fair 캡 적용 시 '상한 적용값' 배지가 붙음")
    check("250" in capped, "캡 미적용 원값(t_fair_uncapped)이 툴팁에 노출됨")

    floored = build_stock_card_html(
        {"symbol": "BBB", "name": "BBB Corp", "t_fair": 50.0,
         "t_fair_floored": True, "t_fair_uncapped": 12.5},
        1,
    )
    check("🛡️ 장부가 바닥값" in floored, "t_fair 바닥값 적용 시 '장부가 바닥값' 배지가 붙음")
    check("12.5" in floored, "PEGY 역산 원값(t_fair_uncapped)이 툴팁에 노출됨")

    plain = build_stock_card_html(
        {"symbol": "CCC", "name": "CCC Corp", "t_fair": 80.0},
        1,
    )
    check("🧮 상한 적용값" not in plain and "🛡️ 장부가 바닥값" not in plain,
          "캡/바닥값 플래그가 없으면 t_fair 자리에 배지가 붙지 않음")


# =============================================================================
# S7 (코스피↔미국 미러링 격차): 그레이엄 넘버 산출 불가 시 else 폴백 박스
# =============================================================================
def test_s7_graham_fallback_box_for_non_loss_reasons():
    print("\n[재감사 S7] 그레이엄 넘버 산출 불가 — 적자가 아닌 사유(BPS 미상/음수)일 때도 "
          "박스가 비지 않고 폴백 문구가 뜨는지(코스피 pegy_page.py 와의 미러링 격차)")

    # f_pegy 를 안 줘서 forward_needs_mask=True 를 유도(포워드가 마스킹돼야 그레이엄 박스 자리가 그려짐).
    # is_trailing_loss 는 아니고, bps 가 없어서 graham_target 을 계산 못 하는 상황 — 예전에는
    # 이 경우 graham_box_html 이 그냥 빈 문자열이라 카드에 아무 것도 안 보였습니다.
    missing_bps = build_stock_card_html(
        {"symbol": "FFF", "name": "FFF Corp", "t_eps": 5.0, "bps": None,
         "is_trailing_loss": False, "graham_target": None},
        1,
    )
    check("그레이엄 넘버 산출 불가" in missing_bps,
          "BPS 가 없어 그레이엄을 못 구해도 빈 자리가 아니라 산출 불가 박스가 뜸")
    check("장부가(BPS) 정보 없음" in missing_bps, "사유가 BPS 미상이라고 정확히 밝힘")
    check("적자 기업" not in missing_bps,
          "적자가 원인이 아닌데 '적자 기업'이라고 잘못 짚지 않음(§0-1 — 틀린 진단 금지)")

    # 자사주 매입형 우량주(H2/H4): BPS 가 음수라 그레이엄을 못 구하지만, 적자는 아님.
    negative_bps = build_stock_card_html(
        {"symbol": "GGG", "name": "GGG Corp", "t_eps": 12.0, "bps": -15.0,
         "is_trailing_loss": False, "graham_target": None},
        1,
    )
    check("그레이엄 넘버 산출 불가" in negative_bps, "BPS 가 음수인 경우도 박스가 뜸")
    check("0 이하" in negative_bps and "-15" in negative_bps,
          "음수 BPS 값 자체를 사유에 명시(0으로 감추거나 지어내지 않음)")
    check("적자 기업" not in negative_bps,
          "자사주 매입형 우량주를 '적자 기업'으로 오진하지 않음(H2/H4 와 같은 원칙)")


# =============================================================================
# M5/M6: roe_color/roic_color 임계값 단일 출처
# =============================================================================
def test_m5_m6_roe_roic_thresholds_match_constants():
    print("\n[재감사 M5/M6] roe_color/roic_color 가 constants_us 값을 씀")

    # ROIC 6.5~8.0% 구간: 예전 하드코딩(8.0)이면 빨간색(#f43f5e), 실제 기준(6.5)이면 정상색.
    below_real_threshold = build_stock_card_html(
        {"symbol": "DDD", "name": "DDD Corp", "roic": US_VALUE_TRAP_ROIC_PCT - 0.1}, 1,
    )
    at_or_above_real_threshold = build_stock_card_html(
        {"symbol": "EEE", "name": "EEE Corp", "roic": US_VALUE_TRAP_ROIC_PCT + 1.0}, 1,
    )
    check("#f43f5e" in below_real_threshold,
          f"ROIC {US_VALUE_TRAP_ROIC_PCT - 0.1:.1f}%(실제 기준 미달)는 빨간색")
    # 7.0(예전 하드코딩 8.0 기준으로는 빨간색이었을 값)이 이제는 정상색이어야 함(회귀 포인트).
    seven_pct = build_stock_card_html({"symbol": "FFF", "name": "FFF Corp", "roic": 7.0}, 1)
    check("#38bdf8" in seven_pct,
          "ROIC 7.0%는 실제 기준(6.5%) 통과라 정상색 — 예전 하드코딩(8.0) 기준이면 빨간색이었을 회귀 케이스")

    roe_below = build_stock_card_html(
        {"symbol": "GGG", "name": "GGG Corp", "t_roe": US_VALUE_TRAP_ROE_PCT - 0.1}, 1,
    )
    check("#f43f5e" in roe_below, f"ROE {US_VALUE_TRAP_ROE_PCT - 0.1:.1f}%(기준 미달)는 빨간색")


# =============================================================================
# L4: 툴팁 숫자가 constants_us 값과 일치
# =============================================================================
def test_l4_tooltip_numbers_match_constants():
    print("\n[재감사 L4] 툴팁 하드코딩 숫자 제거")

    html = build_stock_card_html(
        {"symbol": "HHH", "name": "HHH Corp", "g_eff": 10.0, "g_eff_capped": True,
         "g_eff_uncapped": 45.0, "price": 100.0, "f_target": 120.0, "f_pegy": 1.0},
        1,
    )
    check(f"{US_GROWTH_CAP_PCT:,.0f}%p" in html, "실효성장률 상한 문구가 US_GROWTH_CAP_PCT 값을 씀")
    check(f"{US_SH_RETURN_CAP_PCT:,.0f}%p" in html, "주주환원 상한 문구가 US_SH_RETURN_CAP_PCT 값을 씀")
    check(f"{US_GEFF_TOTAL_CAP_PCT:,.0f}%p" in html, "합계 상한 문구가 US_GEFF_TOTAL_CAP_PCT 값을 씀")
    check(f"{US_TARGET_PER_CAP:,.0f}배" in html, "목표 PER 상한 문구가 US_TARGET_PER_CAP 값을 씀")
    check(f"{US_TARGET_PRICE_CAP_MULTIPLE:,.1f}배" in html,
          "현재가 배수 상한 문구가 US_TARGET_PRICE_CAP_MULTIPLE 값을 씀")


# =============================================================================
# L3: 상단 문구의 유니버스 크기
# =============================================================================
def test_l3_title_uses_universe_size_constant():
    print("\n[재감사 L3] 상단 문구 유니버스 크기")
    check(f"상위 {US_TARGET_UNIVERSE_SIZE}개" in _TITLE_TAIL,
          "화면 제목이 US_TARGET_UNIVERSE_SIZE 를 그대로 반영(하드코딩 550 아님)")


# =============================================================================
# M10: 다운로드 파일명 — 스냅샷의 실제 거래일
# =============================================================================
def test_m10_snapshot_trading_date_prefers_session_mode():
    print("\n[재감사 M10] 다운로드 파일명 거래일")

    meta_with_sessions = {
        "session_dates_from_source": {"2026-08-27": 3, "2026-08-28": 540},
        "last_updated_at_et": "2026-08-29 03:15",
    }
    check(_snapshot_trading_date_str(meta_with_sessions) == "20260828",
          "session_dates_from_source 최빈값을 우선 사용(배포 서버 시각이 아니라 실제 거래일)")

    meta_only_last_updated = {"last_updated_at_et": "2026-08-27 16:05"}
    check(_snapshot_trading_date_str(meta_only_last_updated) == "20260827",
          "session_dates_from_source 가 없으면 last_updated_at_et 앞 10자리로 대체")

    check(_snapshot_trading_date_str({}) == "",
          "아무 날짜 정보도 없으면 있지도 않은 날짜를 지어내지 않고 빈 문자열")


# =============================================================================
# M12 / L9: 필터 프리셋 로직
# =============================================================================
def test_m12_low_valuation_quality_preset_excludes_value_traps():
    print("\n[재감사 M12] 저평가 우량주 프리셋의 value_trap 제외")

    stocks = [
        {"symbol": "A", "badge": "🟢 강력저평가", "value_trap": False},
        {"symbol": "B", "badge": "🟢 강력저평가", "value_trap": True},
        {"symbol": "C", "badge": "🟢 저평가", "value_trap": False},
    ]
    preset = "🟢 저평가 우량주 그룹 (강력저평가 + 저평가)"
    badges = select_badges_for_preset(preset, [], ["🟢 강력저평가", "🟢 저평가"])
    result = apply_stock_filters(stocks, "", badges, preset, False)
    symbols = [s["symbol"] for s in result]
    check(symbols == ["A", "C"],
          f"착시 저평가(value_trap=True) 종목 B는 '우량주' 프리셋에서 빠짐 (결과: {symbols})")


def test_l9_empty_custom_badge_selection_yields_zero_results():
    print("\n[재감사 L9] 세부 뱃지 전부 해제 시 0건")

    stocks = [
        {"symbol": "A", "badge": "🟢 강력저평가", "value_trap": False},
        {"symbol": "B", "badge": "🔴 고평가", "value_trap": False},
    ]
    preset = "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)"
    # 사용자가 배지를 전부 해제 → custom_badges == []
    badges = select_badges_for_preset(preset, [], ["🟢 강력저평가", "🔴 고평가"])
    check(badges == [], "빈 리스트를 그대로 돌려줌(None 이 아님)")
    result = apply_stock_filters(stocks, "", badges, preset, False)
    check(result == [], "배지를 전부 해제하면 0건 — 예전 버그(if badges:)면 전체가 보였을 자리")

    # 대조군: "전체 종목" 프리셋은 badges=None → 필터를 건너뛰고 전체가 보여야 정상.
    none_preset = "🌐 전체 종목 보기"
    none_badges = select_badges_for_preset(none_preset, [], ["🟢 강력저평가", "🔴 고평가"])
    check(none_badges is None, "프리셋이 배지 기반이 아니면 None(필터 없음)")
    all_result = apply_stock_filters(stocks, "", none_badges, none_preset, False)
    check(len(all_result) == 2, "필터 없음(None)일 때는 전체 종목이 그대로 보임")


# =============================================================================
# M11: 요약 이력 로딩이 로컬 파일 유무만으로 건너뛰지 않음
# =============================================================================
def test_m11_summary_history_attempts_load_even_without_local_file():
    print("\n[재감사 M11] 요약 이력 로딩 — 원격 폴백 경로 확보")
    import web.pages.us_stocks_page as page_mod

    calls = {"n": 0}

    async def fake_load_json_file_async(path):
        calls["n"] += 1
        return None, "스냅샷 파일(x)이 없습니다."

    orig = page_mod.load_json_file_async
    page_mod.load_json_file_async = fake_load_json_file_async
    try:
        result = asyncio.run(page_mod.load_us_summary_history())
    finally:
        page_mod.load_json_file_async = orig

    check(calls["n"] == 1,
          "os.path.exists() 로 미리 걸러 건너뛰지 않고 load_json_file_async 를 실제로 호출함"
          "(원격 모드에서 로컬 사본이 없어도 원격을 시도할 수 있어야 함)")
    check(result == [], "파일이 없는 경우(정상 상태)는 조용히 빈 목록")


# =============================================================================
# L13: "이전 동기화 대비" 델타의 비교 날짜
# =============================================================================
def test_l13_summary_metric_delta_shows_comparison_date():
    print("\n[재감사 L13] 요약 지표 델타의 비교 날짜")
    from unittest import mock

    import web.components.widgets as widgets_mod

    stocks = [{"f_per": 20.0, "growth": 10.0, "f_pegy": 1.0}]
    history = [
        {"f_per": 18.0, "growth": 8.0, "pegy": 0.9, "session_date": "2026-08-20"},
        {"f_per": 20.0, "growth": 10.0, "pegy": 1.0, "session_date": "2026-08-27"},
    ]

    captured = []

    def fake_metric_card(label, value, delta=""):
        captured.append((label, value, delta))

    with mock.patch.object(widgets_mod, "metric_card", fake_metric_card), \
         mock.patch.object(widgets_mod.ui, "row") as fake_row:
        fake_row.return_value.__enter__ = lambda self: self
        fake_row.return_value.__exit__ = lambda self, *a: None
        fake_row.return_value.classes = lambda *a, **k: fake_row.return_value
        widgets_mod.render_summary_metrics(stocks, history, ("A", "B", "C"))

    deltas = [d for _l, _v, d in captured]
    check(any("2026-08-20" in d for d in deltas),
          f"델타 문구에 비교 대상 날짜(2026-08-20)가 포함됨 (실측: {deltas})")
    check(not any("(이전 동기화 대비)" in d for d in deltas),
          "session_date 가 있을 때는 애매한 '이전 동기화 대비' 대신 실제 날짜를 씀")


# =============================================================================
# H3: 정합성 모순으로 차단된 종목의 Forward 마스킹 누락
# =============================================================================
def test_h3_generic_harness_fail_shows_masked_panel():
    print("\n[재감사 H3] 정합성 모순 종목의 Forward 마스킹")

    html = build_stock_card_html(
        {"symbol": "III", "name": "III Corp", "is_unverified": True,
         "unverified_reason": "ROE 음수인데 EPS 양수 — 정합성 모순", "g_eff": 10.0},
        1,
    )
    check("🛡️ 데이터 검증 실패" in html,
          "is_unverified 종목은 다른 마스킹 사유가 없어도 '데이터 검증 실패' 패널이 뜸")
    check("ROE 음수인데 EPS 양수" in html, "사유(unverified_reason)가 패널 본문에 노출됨")

    normal_html = build_stock_card_html(
        {"symbol": "JJJ", "name": "JJJ Corp", "g_eff": 10.0, "f_pegy": 1.0}, 1,
    )
    check("🛡️ 데이터 검증 실패" not in normal_html,
          "정상 종목(is_unverified 없음)에는 이 패널이 뜨지 않음")


# =============================================================================
# M2: 지수 카드의 error 노출 (등락률 존재 여부와 무관하게)
# =============================================================================
def test_m2_index_header_shows_error_even_with_change_value():
    print("\n[재감사 M2] 지수 카드 error 노출")

    html = build_index_header_html({
        "sp500": {"label_ko": "S&P500", "label_en": "S&P 500", "proxy_symbol": "SPY",
                  "daily_change_pct": 1.23, "error": "'Index Tracked' 라벨 불일치"},
        "nasdaq": {"label_ko": "나스닥 종합", "label_en": "Nasdaq Composite", "proxy_symbol": "ONEQ",
                   "daily_change_pct": 0.5},
        "dow": {"label_ko": "다우존스", "label_en": "Dow Jones", "proxy_symbol": "DIA",
                "daily_change_pct": -0.2},
    })
    check("라벨 불일치" in html,
          "등락률이 정상 산출돼도 error 가 있으면 그대로 노출됨(예전엔 change 가 있으면 버려짐)")

    all_missing = build_index_header_html({})
    check("수집하지 못했습니다" in all_missing, "지수 정보가 통째로 없으면 경고 카드")


# =============================================================================
# M3: 스냅샷의 실제 거래일 노출
# =============================================================================
def test_m3_trading_date_prefers_session_mode_over_collection_time():
    print("\n[재감사 M3] 스냅샷 실제 거래일")

    meta = {
        "session_dates_from_source": {"2026-11-26": 548, "2026-11-27": 2},
        "last_updated_at_et": "2026-11-27 05:40",
    }
    # 휴장일(추수감사절)에 크론이 돌아 last_updated_at_et 는 27일이지만, 실제 종목
    # 대부분의 거래일(최빈값)은 26일 — 이 값을 우선해야 §0-3-1 을 지킵니다.
    check(_snapshot_trading_date_iso(meta) == "2026-11-26",
          "최빈 거래일을 우선 선택(수집을 돌린 시각이 아니라 데이터의 실제 거래일)")
    check(_snapshot_trading_date_str(meta) == "20261126",
          "파일명용 문자열도 같은 값을 씀(단일 출처, §0-3-10)")


# =============================================================================
# M4: 스냅샷 노후 경고 (일반 사용자에게도 노출)
# =============================================================================
def test_m4_stale_days_computation():
    print("\n[재감사 M4] 스냅샷 노후 판정")
    from datetime import datetime

    check(compute_stale_days("2026-08-20", datetime(2026, 8, 25)) == 5.0,
          "거래일로부터 지난 달력일 수를 정확히 계산")
    check(compute_stale_days("2026-08-20", datetime(2026, 8, 25)) >= US_STALE_SESSION_WARNING_DAYS,
          f"5일 경과는 경고 문턱({US_STALE_SESSION_WARNING_DAYS}일) 이상이라 경고 대상")
    # 통상적인 금~월 주말 간격(3일)은 오탐이 아니어야 함
    check(compute_stale_days("2026-08-21", datetime(2026, 8, 24)) < US_STALE_SESSION_WARNING_DAYS,
          "금요일 거래일 → 월요일 조회는 3일 이내라 경고 대상 아님(정상적인 주말 간격)")
    check(compute_stale_days("이상한값", datetime(2026, 8, 25)) is None,
          "형식이 이상하면 크래시 대신 None(경고를 건너뜀)")
    check(compute_stale_days("", datetime(2026, 8, 25)) is None, "거래일 정보가 없으면 None")


# =============================================================================
# M7: 대량 수집 실패 시 아코디언 → 배너 승격 문턱
# =============================================================================
def test_m7_failed_ticker_ratio_threshold_matches_constant():
    print("\n[재감사 M7] 수집 실패 비율 문턱")
    # 이 계산 자체는 _render_body() 안의 한 줄(len(failed)/universe_size)이라 별도 함수로
    # 뽑지 않았습니다 — 문턱 상수가 올바른 값으로 import 되어 있는지만 확인합니다
    # (M5/M6 류의 "하드코딩 vs 상수 불일치" 회귀를 방지).
    check(0 < US_FAILED_TICKERS_BANNER_RATIO < 1, "실패 비율 문턱이 0~1 사이의 합리적인 값")
    high_failure_ratio = 12 / 550
    low_failure_ratio = 2 / 550
    check(high_failure_ratio >= US_FAILED_TICKERS_BANNER_RATIO,
          f"550종목 중 12종목 실패({high_failure_ratio:.1%})는 배너 승격 대상")
    check(low_failure_ratio < US_FAILED_TICKERS_BANNER_RATIO,
          f"550종목 중 2종목 실패({low_failure_ratio:.1%})는 배너 승격 대상 아님(개별 실패는 아코디언만)")


# =============================================================================
# S2: 화면 소스에 판정용 숫자 리터럴이 남아있지 않은지 (constants_us.py 가 단일 출처)
# =============================================================================
def test_s2_no_hardcoded_threshold_literals_outside_import():
    print("\n[재감사 S2] us_stocks_page.py 의 비교식(if/삼항)에 판정용 임계값이 "
          "리터럴로 남아있지 않은지 — constants_us.py 를 단일 출처로 쓰는지 AST 로 확인")
    # M5/M6/L3/L4/M7 이 실제로 하드코딩했던 값들. 값 자체가 흔한 숫자(0, 1, 2, 4, 100 등)가
    # 아니라 이 파일의 판정 임계값과 정확히 겹치는 값만 골라, 우연한 리터럴과 헷갈리지 않게 합니다.
    threshold_values = {
        US_VALUE_TRAP_ROE_PCT,        # M5/M6 — roe_color 임계값
        US_VALUE_TRAP_ROIC_PCT,       # M5/M6 — roic_color 임계값
        float(US_TARGET_UNIVERSE_SIZE),  # L3 — 화면 제목 "상위 N개"
        US_GROWTH_CAP_PCT,            # L4 — 실효성장률 캡 툴팁
        US_SH_RETURN_CAP_PCT,         # L4 — 주주환원 캡 툴팁
        US_GEFF_TOTAL_CAP_PCT,        # L4 — g_eff 총합 캡 툴팁
        US_TARGET_PER_CAP,            # L4 — 모델 목표가 PER 캡 툴팁
        US_TARGET_PRICE_CAP_MULTIPLE,  # L4 — 모델 목표가 배수 캡 툴팁
        US_FAILED_TICKERS_BANNER_RATIO,  # M7 — 실패 비율 배너 문턱
    }

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "web", "pages", "us_stocks_page.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    # import 구문 안의 리터럴(상수 이름일 뿐 값이 아님)과, 함수 파라미터 기본값처럼 임계값
    # 비교가 아닌 자리는 제외하고, "비교식(Compare)에 쓰인 숫자 리터럴"만 검사합니다 —
    # 판정 로직이 아닌 곳(리스트 슬라이스, 반복 횟수 등)의 우연한 숫자와 구분하기 위함입니다.
    # int 리터럴은 제외합니다(오프셋 `offset == 9`, 문자열 길이 `>= 10` 같은 무관한 정수와
    # 9.0/10.0 같은 임계값이 값만 우연히 겹쳐 오탐이 났음 — 이 코드베이스의 임계값 상수는
    # 전부 float 이므로 float 리터럴만 봐도 충분합니다).
    offending = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        for operand in operands:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, float):
                if operand.value in threshold_values:
                    offending.append((getattr(node, "lineno", "?"), operand.value))

    check(not offending,
          f"비교식에 하드코딩된 판정 임계값 리터럴 없음(constants_us.py 상수만 사용) "
          f"— 발견: {offending}" if offending else
          "비교식에 하드코딩된 판정 임계값 리터럴 없음(constants_us.py 상수만 사용)")


def test_us_stocks_page_full_suite():
    test_h3_generic_harness_fail_shows_masked_panel()
    test_m2_index_header_shows_error_even_with_change_value()
    test_m3_trading_date_prefers_session_mode_over_collection_time()
    test_m4_stale_days_computation()
    test_m7_failed_ticker_ratio_threshold_matches_constant()
    test_h5_t_fair_badges()
    test_s7_graham_fallback_box_for_non_loss_reasons()
    test_m5_m6_roe_roic_thresholds_match_constants()
    test_l4_tooltip_numbers_match_constants()
    test_l3_title_uses_universe_size_constant()
    test_m10_snapshot_trading_date_prefers_session_mode()
    test_m12_low_valuation_quality_preset_excludes_value_traps()
    test_l9_empty_custom_badge_selection_yields_zero_results()
    test_m11_summary_history_attempts_load_even_without_local_file()
    test_l13_summary_metric_delta_shows_comparison_date()
    test_s2_no_hardcoded_threshold_literals_outside_import()

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건")
        print("=" * 70)
        for f in FAILURES:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ 전체 통과")
    print("=" * 70)


if __name__ == "__main__":
    test_us_stocks_page_full_suite()
