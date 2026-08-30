# tests/test_pegy_page.py
"""
💡 사실 이 가격이에요(PEGY, `/`) — 2026-08-29 재감사(`MACRO_REAUDIT_FINDINGS.md`) 회귀 테스트

이 화면은 지금까지 `tests/test_quant.py`(퀀트 엔진)·`tests/test_web_session_isolation.py`
(배선·격리)만 실제로 화면 코드를 건드렸고, 카드 조립(`build_stock_card_html`)과 배지
필터(`resolve_preset_badges`)는 회귀 테스트가 하나도 없었습니다. 이 파일은 2026-08-29
재감사에서 나온 PEGY 전용 버그(H-4·M-1·M-2·L-6·L-7·L-8)가 되살아나지 않는지를 실제
함수를 호출해 반환된 HTML/값으로 직접 확인합니다(문자열 패턴만 보는 게 아니라 실행
결과를 봅니다).

실행: python -m pytest tests/test_pegy_page.py
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pytest

from web.pages.pegy_page import build_stock_card_html, resolve_preset_badges

FAILURES = []


@pytest.fixture(autouse=True)
def _assert_no_check_failures():
    """다른 테스트 파일과 같은 관례 — check() 실패를 실제 pytest 실패로 승격."""
    start = len(FAILURES)
    yield
    new_failures = FAILURES[start:]
    assert not new_failures, f"check() 로 기록된 실패 {len(new_failures)}건: {new_failures}"


def check(cond, label):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        FAILURES.append(label)


def _base_stock(**overrides) -> dict:
    """정상(마스킹 없는) 종목 카드 1장을 그리는 데 필요한 최소 필드 전부.
    개별 테스트는 확인하려는 필드만 overrides 로 덮어씁니다."""
    base = {
        "name": "테스트종목", "code": "000001", "market": "KR",
        "price": 50000, "rank": 1, "badge": "🟢 저평가",
        "vol": "🟢 정상 (1.2%)",
        "t_roe": 12.0, "roic": 8.0, "f_roe": 13.0,
        "t_eps": 5000, "t_eps_calculated": False,
        "t_pbr": 1.2, "t_per": 10.0, "t_per_measured": 10.0,
        "ev_ebitda": 8.2,
        "dps": 850, "dps_source": "naver_financial_statement",
        "return_total": "425억원", "sh_return": 1.7, "sh_return_basis": None,
        "growth": 15.0, "growth_source": "consensus", "growth_score_capped": False,
        "f_target": 65000, "f_target_capped": False, "f_target_uncapped": None,
        "f_target_cap_reason": None,
        "f_per": 9.0, "f_eps": 5500,
        "t_fair": 55000, "t_fair_capped": False, "t_fair_uncapped": None,
        "t_pegy": 0.8,
        "quant_score": 75, "score_max": 100, "score_excluded_items": [],
        "value_trap": False,
        "is_valid": True, "is_unverified": False,
        "reject_reason": "", "unverified_reason": "",
        "dividend_data_unverified": False, "dividend_unverified_reason": None,
        "is_negative_growth": False, "g_eff": 16.7,
        "forward_data_missing": False,
        "is_trailing_loss": False,
        "loss_evidence": [],
        "graham_target": 48000, "graham_is_financial_sector": False,
        "per_discrepancy": None,
        "is_visible": True,
    }
    base.update(overrides)
    return base


def test_h4_dps_not_collected_shows_data_missing_not_no_dividend():
    print("\n[H-4a] DPS 미수집(dps=None) — '데이터 없음', '무배당'이라고 단정하지 않음")
    s = _base_stock(dps=None, dps_source="not_collected")
    html = build_stock_card_html(s, 1, admin=False)
    check("DPS 데이터 없음" in html, "미수집이면 'DPS 데이터 없음'으로 표기")
    check("무배당" not in html, "'무배당'이라고 절대 단정하지 않음(값을 모르는 것과 확실히 다름)")


def test_h4_dps_confirmed_no_dividend_is_labelled_confirmed():
    print("\n[H-4b] 무배당 확정(dps=0, dps_source=no_dividend_confirmed) — '무배당(확인됨)'")
    s = _base_stock(dps=0, dps_source="no_dividend_confirmed")
    html = build_stock_card_html(s, 1, admin=False)
    check("DPS 무배당(확인됨)" in html, "확정된 무배당은 '확인됨'을 붙여 미수집과 구분")
    check("DPS 데이터 없음" not in html, "확정 무배당을 '데이터 없음'으로 되돌리지 않음")


def test_h4_dps_real_value_shows_amount():
    print("\n[H-4c] 실측 DPS(dps=850) — 금액 그대로 표기")
    s = _base_stock(dps=850, dps_source="naver_financial_statement")
    html = build_stock_card_html(s, 1, admin=False)
    check("DPS 850원/주" in html, "실측값은 금액으로 표기")


def test_l6_negative_ev_ebitda_does_not_show_mna_payback_years():
    print("\n[L-6] EV/EBITDA 가 음수(적자)면 'M&A 원금회수기간'을 그리지 않음")
    s = _base_stock(ev_ebitda=-3.4)
    html = build_stock_card_html(s, 1, admin=False)
    check("년)" not in html, "음수 EV/EBITDA 에는 회수기간(N년) 문구가 없음")


def test_l6_and_l11_positive_ev_ebitda_shows_payback_at_correct_font_size():
    print("\n[L-6/L-11] EV/EBITDA 가 양수면 회수기간을 13px로 직접 표기(치환 훅 없음)")
    s = _base_stock(ev_ebitda=8.2)
    html = build_stock_card_html(s, 1, admin=False)
    check("(약 8.2년)" in html, "양수 EV/EBITDA 는 회수기간을 정상 표기")
    check("font-size: 13px; color: #94a3b8; font-weight: 500;'>(약 8.2년)" in html,
          "폰트 크기가 처음부터 13px로 만들어짐(11px→13px 문자열 치환 없이)")


def test_l7_missing_price_shows_data_missing_not_zero_won():
    print("\n[L-7] 현재가 결측(price=None) — Forward 비교박스에 '0원' 대신 '데이터 없음'")
    s = _base_stock(price=None)
    html = build_stock_card_html(s, 1, admin=False)
    check('class="price-text-curr">데이터 없음</span>' in html,
          "결측 현재가를 '0원'으로 위장하지 않음")
    check('class="price-text-curr">0원</span>' not in html,
          "결측을 실측 0원처럼 보이게 하지 않음")


def test_l7_missing_price_also_blanks_floor_price():
    print("\n[L-7] 현재가 결측이면 PBR 바닥가(현재가÷PBR)도 '0원'을 만들지 않음")
    s = _base_stock(price=None, t_pbr=1.2)
    html = build_stock_card_html(s, 1, admin=False)
    floor_span = 'font-size: 15px; font-weight: 700; color: #94a3b8;">'
    check(f'{floor_span}데이터 없음</span>' in html,
          "현재가가 없으면 바닥가도 '데이터 없음'(0÷PBR=0원으로 지어내지 않음)")
    check(f'{floor_span}0원</span>' not in html,
          "바닥가 자리에 '0원'이 나오지 않음")


def test_l7_real_price_displays_amount():
    print("\n[L-7 대조] 실측 현재가는 그대로 금액 표기")
    s = _base_stock(price=50000)
    html = build_stock_card_html(s, 1, admin=False)
    check('class="price-text-curr">50,000원</span>' in html, "실측 현재가는 금액 그대로 표기")


def test_l8_loss_banner_rounds_roe():
    print("\n[L-8] 적자 경고 배너의 ROE 가 다른 자리와 같은 자릿수로 반올림됨")
    s = _base_stock(t_roe=-3.2000000001)
    html = build_stock_card_html(s, 1, admin=False)
    check("ROE -3.2%" in html, "카드의 다른 자리(fmt_num(...,1))와 같은 반올림 규칙")
    check("-3.2000000001" not in html, "반올림 없는 원본 float 문자열이 그대로 새지 않음")


def test_m1_high_valuation_preset_excludes_neutral_verified_only_badge():
    print("\n[M-1] '고평가/주의' 프리셋이 중립 배지(컨센서스 미커버리지)를 끌고 오지 않음")
    all_badges = [
        "🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성",
        "🔵 Trailing만 검증됨 (Forward 데이터 없음)",  # 중립 — 저평가도 고평가도 아님
        "🔴 고평가 관망", "🔴 실적 역성장/적자 (위험)", "🔴 극단적 고평가 (위험)",
        "🔴 데이터 이상/극단고평가 (PER 검증 실패)", "🔴 목표가 초과 (고평가 관망)",
    ]
    matched = resolve_preset_badges(
        "🔴 고평가 / 주의 종목 그룹 (고평가 + 역성장 + 주의)", [], all_badges
    )
    check("🔵 Trailing만 검증됨 (Forward 데이터 없음)" not in matched,
          "중립 배지는 '고평가/주의' 그룹에 안 들어감")
    for red in ("🔴 고평가 관망", "🔴 실적 역성장/적자 (위험)", "🔴 극단적 고평가 (위험)",
                "🔴 데이터 이상/극단고평가 (PER 검증 실패)", "🔴 목표가 초과 (고평가 관망)"):
        check(red in matched, f"실제 경고 배지는 그대로 포함: {red}")
    check("🟢 강력 저평가" not in matched and "🟡 적정가 형성" not in matched,
          "저평가·적정가 배지는 섞이지 않음")


def test_m2_custom_preset_with_zero_badges_selected_filters_to_nothing():
    print("\n[M-2] '세부 뱃지 직접 선택'에서 배지를 전부 해제하면 결과가 0건이어야 함(전체 아님)")
    all_badges = ["🟢 저평가", "🔴 고평가 관망"]
    matched = resolve_preset_badges("⚙️ 세부 뱃지 직접 선택 (커스텀 필터)", [], all_badges)
    check(matched == [], "빈 선택은 빈 리스트를 그대로 돌려줌(None 이 아님)")
    check(matched is not None, "None(필터 없음)과 명확히 구분됨")


def test_m2_custom_preset_with_some_badges_keeps_the_selection():
    print("\n[M-2 대조] '세부 뱃지 직접 선택'에서 일부만 고르면 그 목록 그대로 필터")
    all_badges = ["🟢 저평가", "🔴 고평가 관망"]
    matched = resolve_preset_badges(
        "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)", ["🟢 저평가"], all_badges
    )
    check(matched == ["🟢 저평가"], "사용자가 고른 배지 목록을 그대로 씀")


def test_default_preset_returns_none_meaning_no_filter():
    print("\n[M-2 대조] 기본(전체 보기) 프리셋은 None(필터 없음)을 돌려줌")
    all_badges = ["🟢 저평가", "🔴 고평가 관망"]
    matched = resolve_preset_badges(
        "🌐 전체 종목 보기 (500개 코스피+코스닥)", [], all_badges
    )
    check(matched is None, "전체 보기는 필터 없음(None) — 빈 선택([])과 구분됨")


# =============================================================================
# 🚪 진입점 렌더 스모크 — `@ui.page('/')` 함수 **자체**를 실제로 실행 (2026-08-30 추가)
# =============================================================================
#  이 파일의 다른 테스트는 전부 **순수 함수**(`build_stock_card_html` /
#  `resolve_preset_badges`)만 부릅니다. 그래서 `pegy_index_page()` 와 그 안의
#  `_render_body()` 몸통 — 스냅샷 로드, 요약 카드, 필터, 카드 루프, 다운로드 도구 —
#  은 지금까지 **어떤 테스트로도 한 번도 실행된 적이 없었습니다**. 이 화면은 이 앱의
#  기본 화면(`/`)이라, 여기서 이름 오타 하나가 나면 사이트 전체가 안 열립니다.
#  실제로 그 사고가 있었습니다 — TASK_HISTORY_ARCHIVE.md `#128`/`#129`
#  (CSS f-string 안 중괄호 하나가 빠져 배포 직후 전 화면이 `UnboundLocalError`).
#
#  확인하는 것은 "끝까지 예외 없이 그려지는가" 하나입니다(화면 **내용**의 정확성은 이
#  파일의 나머지 테스트와 `tests/test_quant.py` 가 이미 봅니다 — §0-3-10).
#  데이터는 **저장소의 실제 스냅샷을 그대로** 읽습니다(가짜로 만들지 않습니다 — §0-1).
#
#  실행 방법은 새로 만들지 않고 공용 헬퍼 `tests/_render_helpers.py::run_render()` 를
#  그대로 씁니다(`tests/` 가 패키지가 아니라 `sys.path` 에 얹은 뒤 가져옵니다).
# =============================================================================
def test_pegy_index_page_render_smoke():
    sys.path.append(str(Path(__file__).parent))            # tests/ (공용 렌더 헬퍼)
    from _render_helpers import run_render

    import web.pages.pegy_page as page

    drawn = []
    original = page.error_banner
    page.error_banner = lambda text: drawn.append(str(text))
    try:
        run_render(page.pegy_index_page())
        check(True, "pegy_index_page() 가 예외 없이 끝까지 실행됨")
    except Exception as exc:                               # noqa: BLE001
        check(False, "pegy_index_page() 가 예외 없이 끝까지 실행됨 "
                     f"({type(exc).__name__}: {exc})")
    finally:
        page.error_banner = original

    # 저장소에 실제 스냅샷이 있는데도 §0-1 조기 반환 배너가 떴다면, 위 "예외 없음"은
    # 본문을 거의 안 그리고 얻은 초록불입니다 — 그건 스모크 테스트의 의미가 없습니다.
    snapshot = Path(__file__).parent.parent / "data" / "kospi200_pegy_latest.json"
    if snapshot.exists():
        early = [b for b in drawn if "스냅샷을 불러오지 못했습니다" in b]
        check(not early,
              "실제 스냅샷이 있으므로 §0-1 조기 반환이 아니라 본문 전체가 그려짐"
              + (f" — 배너: {early}" if early else ""))
