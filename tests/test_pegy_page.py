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

# 저장소 루트를 `sys.path` 에 얹는 일과, 무음 통과 방지 하네스(FAILURES 목록 · check() ·
# autouse 픽스처)는 파일마다 복사하지 않고 `tests/conftest.py` 한 곳에만 둡니다
# (2026-08-30 — TASK_HISTORY #168 H-1 "복사 하나 빠뜨림" 재발 방지). 이 import 가 conftest 를
# 먼저 불러오므로 `python tests/test_x.py` 직접 실행 경로에서도 아래 import 들이 정상 동작하고,
# check() 실패를 pytest 빨간불로 승격시키는 `_assert_no_check_failures` 픽스처는 conftest 의
# autouse 라 이 파일의 모든 테스트에 자동 적용됩니다(이 파일에 따로 쓸 것이 없습니다).
from conftest import FAILURES, check  # noqa: E402

from web.pages.pegy_page import (
    build_next_dividend_html,
    build_stock_card_html,
    resolve_preset_badges,
)


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


def test_geff_cap_badge_shown_when_capped():
    """2026-08-30(#176/#178) — g_eff가 캡에 걸린 종목은 목표가·f_pegy가 캡 적용값으로
    계산됐다는 사실이 화면에도 드러나야 합니다(미국 페이지의 "🧮 상한 적용값" 배지와 동일
    취지). 이전 스냅샷에는 이 필드가 아예 없을 수 있으니(수집기 재실행 전) 필드가 없을 때는
    조용히 배지가 안 뜨는지도 함께 확인합니다.

    ⚠️ "🧮 상한 적용값" 라벨 문자열 자체는 목표가 캡(별개의 캡) 안내 툴팁의 설명 문장
    안에도 항상 등장하므로("상한에 걸린 종목에는 옆에 '🧮 상한 적용값' 배지가 붙습니다"),
    라벨만으로는 이 배지가 실제로 켜졌는지 판정할 수 없습니다 — g_eff 배지 툴팁에만 있는
    고유 문구로 판정합니다."""
    GEFF_BADGE_MARKER = "실효성장률이 상한(성장률"

    html_capped = build_stock_card_html(
        _base_stock(g_eff_capped=True, g_eff_uncapped=52.3), rank_num=1, admin=False
    )
    check(GEFF_BADGE_MARKER in html_capped, "캡이 걸리면 g_eff 배지가 뜸")
    check("52.3" in html_capped, "캡 미적용 원값(52.3%p)이 배지 안에 그대로 보임")

    html_not_capped = build_stock_card_html(
        _base_stock(g_eff_capped=False), rank_num=1, admin=False
    )
    check(GEFF_BADGE_MARKER not in html_not_capped, "캡이 안 걸리면 g_eff 배지 없음")

    # 필드 자체가 없는(옛 스냅샷) 경우 — .get()이 None을 돌려주므로 조용히 배지 없이 렌더.
    html_missing_field = build_stock_card_html(_base_stock(), rank_num=1, admin=False)
    check(GEFF_BADGE_MARKER not in html_missing_field,
          "필드가 아예 없는 옛 스냅샷도 예외 없이 배지만 생략됨")


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


# =============================================================================
# 📅 "다음 배당 일정" 보조 한 줄 (2026-09-03 추가 — 오너 요청)
#
# 선택 규칙 자체(어느 공시를 고르는가)는 `tests/test_dividend_next_event.py` 가 순수 함수
# 단위로 고정합니다. 여기서는 **카드가 그 결과를 어떻게 그리는가**만 봅니다 —
#   ① 없으면 아예 안 그린다, ② 있어도 기존 "작년 배당률(확정)" 표기를 건드리지 않는다,
#   ③ 정정ㆍ자회사 대리공시ㆍ원문 미해독 사실을 감추지 않는다, ④ 전부 esc() 를 통과한다.
# =============================================================================
NEXT_DIV_MARKER = "📅 다음 배당 일정"


def _payment_event(**overrides) -> dict:
    """실제 `dividend_kr_2026_payment_events.json` 레코드에서 카드가 읽는 필드만 추린 것."""
    event = {
        "record_date": "2026-09-30",
        "pay_date_expected": "2026-10-30",
        "dps_common": 314,
        "dividend_class": "중간배당",
        "is_correction": False,
        "is_subsidiary_notice": False,
        "parse_status": "OK",
    }
    event.update(overrides)
    return event


def test_next_dividend_line_is_absent_when_there_is_no_upcoming_event():
    """🔴 다가오는 공시가 없으면 **한 글자도 그리지 않습니다**(자리표시자 금지).
    "예정된 공시 없음"을 500장 카드에 찍으면 소음일 뿐 아니라, 우리가 아는 사실도 아닙니다
    (수집 유니버스 밖이거나 아직 공시가 안 났을 수 있음 — §0-1)."""
    print("\n[다음배당-1] 이벤트 없음(None)·필드 자체 없음 — 보조 줄 자체가 없음")
    html_none = build_stock_card_html(_base_stock(next_dividend_event=None), 1, admin=False)
    check(NEXT_DIV_MARKER not in html_none, "None 이면 보조 줄이 아예 없음")
    check("예정된 공시 없음" not in html_none, "'없음' 이라고 단정하는 문구를 쓰지 않음")

    # 필드가 아예 없는 옛 스냅샷 경로(.get() → None)도 같아야 합니다.
    html_missing = build_stock_card_html(_base_stock(), 1, admin=False)
    check(NEXT_DIV_MARKER not in html_missing, "필드가 없는 종목도 조용히 생략됨")


def test_next_dividend_line_shows_disclosure_values_as_is():
    """공시 원문값을 그대로 옮깁니다 — 현재가로 다시 계산하지 않습니다."""
    print("\n[다음배당-2] 이벤트가 있으면 배당기준일·지급예정일·1주당·배당구분을 원문 그대로")
    html = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event()), 1, admin=False)
    check(NEXT_DIV_MARKER in html, "보조 줄이 그려짐")
    check("배당기준일 <b style=\"color: #7dd3fc;\">2026-09-30</b>" in html, "배당기준일 원문값")
    check("지급예정일 <b style=\"color: #7dd3fc;\">2026-10-30</b>" in html, "지급예정일 원문값")
    check("1주당 <b style=\"color: #7dd3fc;\">314원</b>" in html, "주당배당금 원문값")
    check("(중간배당)" in html, "배당구분 원문 라벨")


def test_next_dividend_line_does_not_touch_last_year_confirmed_dividend():
    """🔴 이번 작업은 순수 추가(additive)입니다 — 기존 "작년 배당률(확정)" 표기가 보조 줄
    유무와 관계없이 **글자 하나까지 동일**해야 합니다."""
    print("\n[다음배당-3] 기존 '작년 배당률(확정)' 표기는 보조 줄이 붙어도 그대로")
    without = build_stock_card_html(_base_stock(), 1, admin=False)
    with_line = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event()), 1, admin=False)

    for fragment in ("DPS 850원/주", "배당수익률 1.70%", "(425억원)"):
        check(fragment in without, f"보조 줄 없을 때 기존 표기 유지: {fragment}")
        check(fragment in with_line, f"보조 줄 있을 때도 기존 표기 유지: {fragment}")

    # 보조 줄을 뺀 나머지가 완전히 같아야 합니다(추가만 했지 무엇도 바꾸지 않았음).
    # 줄바꿈만 없앤 뒤 비교합니다 — `compact()` 가 빈 줄을 지우므로 보조 줄이 없을 때와
    # 있을 때의 줄 수가 달라서, 줄바꿈 차이 때문에 틀린 빨간불이 나지 않게 하기 위함입니다.
    flat_without = without.replace("\n", "")
    flat_with = with_line.replace("\n", "")
    fragment = build_next_dividend_html(_payment_event()).replace("\n", "")
    check(fragment and fragment in flat_with, "보조 줄 조각이 카드 안에 그대로 들어가 있음")
    check(flat_with.replace(fragment, "") == flat_without,
          "보조 줄 조각만 빼면 카드 HTML 이 기존과 완전히 동일함")


def test_next_dividend_line_marks_that_a_correction_was_followed():
    """오너 요청의 핵심 — 정정본을 따라갔다는 사실을 화면에도 남깁니다."""
    print("\n[다음배당-4] is_correction 이면 '[기재정정 반영]' 표시")
    html = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event(is_correction=True)), 1, admin=False)
    check("[기재정정 반영]" in html, "정정본을 따라갔다는 사실을 밝힘")

    html_plain = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event(is_correction=False)), 1, admin=False)
    check("[기재정정 반영]" not in html_plain, "정정본이 아니면 그 표시를 붙이지 않음")


def test_next_dividend_line_discloses_subsidiary_and_partial_parse():
    """🔴 수집기가 밝힌 두 가지 한계를 카드도 감추지 않습니다(§0-1).

    특히 원문 일부 미해독(`parse_status='PARTIAL'`)은 "어차피 빈 칸으로 보이겠지"로 넘길 수
    없습니다 — 2026-09-03 실측으로 PARTIAL 22건 중 13건은 이 줄에 나오는 네 항목이 전부
    채워져 있어, 배지가 없으면 완전히 읽힌 공시처럼 보입니다.
    """
    print("\n[다음배당-5] 자회사 대리공시 · 원문 일부 미해독 배지")
    html_sub = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event(is_subsidiary_notice=True)),
        1, admin=False)
    check("자회사 대리공시" in html_sub, "자회사 대리공시 사실을 밝힘")
    check("공시 주체와 실제 배당하는 회사가 다를 수 있습니다" in html_sub,
          "캘린더 화면과 같은 문장(공용 상수)을 씀")

    html_partial = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event(parse_status="PARTIAL")),
        1, admin=False)
    check("원문 일부 미해독" in html_partial, "원문 일부 미해독 사실을 밝힘")
    check("parse_status=PARTIAL" in html_partial, "어떤 상태였는지 그대로 노출")

    html_clean = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event()), 1, admin=False)
    check("자회사 대리공시" not in html_clean, "해당 없으면 배지를 붙이지 않음")
    check("원문 일부 미해독" not in html_clean, "parse_status=OK 면 배지를 붙이지 않음")


def test_next_dividend_line_handles_missing_optional_fields_without_inventing():
    """지급예정일ㆍ배당구분이 원문에 없는 건이 실제로 있습니다(실측: 지급예정일 결측 29건).
    없는 값을 '미정' 같은 단정으로 채우지 않고, 배당구분은 괄호째 생략합니다."""
    print("\n[다음배당-6] 결측 필드 — 지어내지 않음")
    html = build_stock_card_html(
        _base_stock(next_dividend_event=_payment_event(
            pay_date_expected=None, dividend_class=None, dps_common=None)),
        1, admin=False)
    check("지급예정일 <b style=\"color: #7dd3fc;\">데이터 없음</b>" in html,
          "지급예정일 결측은 '데이터 없음'")
    check("1주당 <b style=\"color: #7dd3fc;\">데이터 없음</b>" in html,
          "주당배당금 결측도 '데이터 없음'(0원으로 그리지 않음)")
    check("()" not in build_next_dividend_html(_payment_event(dividend_class=None)),
          "배당구분이 없으면 빈 괄호를 남기지 않고 통째로 생략")


def test_next_dividend_line_escapes_disclosure_strings():
    """§0-3-9 — 공시에서 온 문자열은 전부 `esc()` 를 통과해야 합니다(원문 라벨은 외부 입력)."""
    print("\n[다음배당-7] XSS — 원문 문자열 이스케이프")
    html = build_next_dividend_html(_payment_event(
        dividend_class='<script>alert(1)</script>', record_date='<img src=x onerror=1>'))
    check("<script>" not in html, "스크립트 태그가 그대로 들어가지 않음")
    check("&lt;script&gt;" in html, "이스케이프된 형태로만 들어감")
    check("<img src=x" not in html, "배당기준일 문자열도 이스케이프됨")
