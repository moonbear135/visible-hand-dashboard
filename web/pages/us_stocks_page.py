"""
🇺🇸 미국 주식은 이가격 — 미국(나스닥+뉴욕) 시가총액 상위 종목 밸류에이션 (공개 화면, URL `/us`).

`views/us_stocks_view.py`(Streamlit, 1,365줄)의 NiceGUI 이식본입니다 (이전 계획서 3단계).
Streamlit 쪽 원본은 컷오버까지 그대로 살려둡니다(듀얼런 — 계획서 §11-1).

이식 방침 (2단계 `web/pages/pegy_page.py` 와 동일)
  - **수집·검증·가공 계층(`utils/*`)은 한 줄도 건드리지 않고 그대로 재사용**합니다(계획서 §1-2).
    이 파일은 순수 표현 계층입니다 — 데이터 가공·계산식을 여기에 새로 넣지 마세요.
  - 코스피 화면과 **구조가 같은 조각(순위 숫자·퀀트 스코어 배지·자본효율성 배지·Forward 마스크
    패널·그레이엄 박스·적자 배너·요약 지표 3종·고지 문구·다운로드 도구·페이지네이션)은
    전부 `web/components/` 의 공용 함수를 호출**합니다. 여기에 복붙하지 마세요 (§0-3-10).
    이 화면에만 있는 것(상단 지수 3종·한글 종목명·베타·애널리스트 컨센서스·리츠 배지·USD 표기)만
    이 파일에 있습니다.
  - 툴팁 클래스명은 `q-tooltip` → `vh-tooltip` (Quasar 내장 클래스와 충돌 회피, `web/theme.py`).
  - 외부에서 온 문자열(종목명·티커·배지·수집 실패 사유 등)은 전부 `esc()` 통과 (§0-3-9 XSS).
  - 상태(검색어·필터·페이지)는 **페이지 함수의 지역 변수**입니다 — 전역에 두면 접속자끼리
    섞입니다(§0-3-8, 계획서 §3-3).
  - 스냅샷이 없으면 숫자를 하나도 그리지 않고 빨간 배너만 띄웁니다 (§0-1).

오너 확정 사항(그대로 유지)
  - 통화: USD 단독 표기 (원화 환산·병기 없음)
  - 상단 지수: S&P500 / 나스닥 종합 / 다우존스 3종, 등락률(%)만 표기 (ETF 프록시라 지수 포인트값 아님)
  - 종목명: 한글명(정식 또는 자동 음역) + 영문명 + 티커 동시 표기
  - 페이지네이션: 30개씩 (`utils/constants_us.US_PAGE_SIZE` — 코스피 20개와 다름)
"""

import os
from datetime import datetime

from nicegui import ui

from utils.constants_us import (
    US_PAGE_SIZE,
    US_RAW_SNAPSHOT_FILENAME,
    US_SNAPSHOT_FILENAME,
    US_SUMMARY_HISTORY_FILENAME,
)
from utils.stock_history import US_HISTORY_FIELDS, US_HISTORY_FILENAME, US_KEY_FIELD

from web.auth import is_admin
from web.components import (
    LEARNING_NOTICE_HTML,
    NA_TEXT,
    compact,
    disclaimer_footer,
    download_button,
    error_banner,
    esc,
    fmt_num,
    forward_mask_html,
    graham_financial_box,
    graham_reference_box,
    graham_unavailable_box,
    info_badge,
    loss_banner_html,
    pager,
    quality_badge,
    quant_score_badge,
    rank_prefix_html,
    render_stock_download_tool,
    render_summary_metrics,
    tooltip,
    warn_badge,
    warning_banner,
)
from web.layout import layout
from web.state import data_path, load_json_file, read_download_bytes

# 페이지당 카드 수는 여기서 새로 정하지 않고 수집기와 같은 상수를 씁니다(단일 출처).
ITEMS_PER_PAGE = US_PAGE_SIZE

FILTER_PRESETS = [
    "🌐 전체 종목 보기",
    "🟢 저평가 우량주 그룹 (강력저평가 + 저평가)",
    "🟡 적정가 형성 그룹 (적정가 + 목표달성)",
    "🔴 고평가 / 주의 종목 그룹",
    "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)",
]

# "검증" 키워드는 "PER 검증 실패"(경고) 뿐 아니라 "Trailing만 검증됨"(단순 데이터 상태 안내,
# 위험 아님) / "데이터 검증 필요"(fallback 안내)까지 잘못 포함시키므로 명시적으로 제외합니다.
_NON_WARNING_BADGES = ("Trailing만 검증됨", "데이터 검증 필요")

# 이 화면에만 쓰는 배지 스타일 (툴팁 마크업 자체는 공용 `tooltip()` 을 씁니다)
_TRANSLIT_BADGE_STYLE = (
    'font-size: 10px; font-weight: 800; color: #a5b4fc; background-color: #312e81; '
    'border: 1px solid #818cf8; border-radius: 6px; padding: 1px 6px; vertical-align: middle;'
)
_REIT_BADGE_STYLE = (
    'background-color: #1e3a5f; color: #93c5fd; font-size: 11.5px; font-weight: 700; '
    'padding: 4px 10px; border-radius: 8px; border: 1px solid #3b82f6;'
)


# =============================================================================
# 1. 데이터 로드 / USD 포맷 (읽기 전용 — 렌더링 중에 수집기를 절대 실행하지 않습니다)
# =============================================================================
def load_us_snapshot():
    """
    data/us_stocks_latest.json 스냅샷 로드 및 메타데이터 반환.

    ⚠️ 실패해도 '현재 시각'을 마지막 동기화 시각인 것처럼 꾸미지 않습니다 (§0-1).
    ⚠️ 실패 사유는 사람이 읽는 한국어 한 문장입니다 — 원본 예외 문구를 화면에 흘리지
       않습니다(§0-3-4). (Streamlit 원본은 `f"...읽지 못했습니다: {e}"` 로 예외 원문을
       그대로 화면에 노출하고 있었습니다 — 이식하면서 고쳤습니다.)
    """
    payload, load_error = load_json_file(data_path(US_SNAPSHOT_FILENAME))
    if payload is None:
        return {"status": "LOAD_FAILED", "load_error": load_error}, []

    meta = dict(payload.get("metadata", {}))
    stocks = payload.get("stocks", [])
    if not stocks:
        meta["status"] = meta.get("status") or "EMPTY"
        meta["load_error"] = "스냅샷에 종목 데이터가 0건입니다."
    return meta, stocks


def load_us_summary_history():
    """data/us_summary_history.json 누적 요약 이력. 없으면 빈 목록."""
    path = data_path(US_SUMMARY_HISTORY_FILENAME)
    if not os.path.exists(path):
        return []
    payload, load_error = load_json_file(path)
    if payload is None:
        warning_banner(f"⚠️ 누적 요약 히스토리를 읽지 못했습니다. {load_error}")
        return []
    return payload if isinstance(payload, list) else []


def fmt_usd(value, digits=2, na_text=NA_TEXT):
    """USD 단독 표기 (원화 환산 없음 — 오너 확정)."""
    if value is None:
        return na_text
    try:
        return f"${value:,.{digits}f}"
    except (TypeError, ValueError):
        return na_text


def fmt_big_usd(value, na_text=NA_TEXT):
    """시가총액 등 큰 금액을 T/B/M 단위로 표기합니다(소스 원표기와 동일 체계)."""
    if value is None:
        return na_text
    try:
        v = float(value)
    except (TypeError, ValueError):
        return na_text
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= div:
            return f"${v / div:,.2f}{unit}"
    return f"${v:,.0f}"


# =============================================================================
# 2. 상단 지수 3종 (S&P500 / 나스닥 종합 / 다우존스)
# =============================================================================
def build_index_header_html(indices) -> str:
    """
    지수 절대값은 표시하지 않습니다 — ETF 프록시(SPY/ONEQ/DIA)의 주가는 실제 지수
    포인트값(예: S&P500 ≈6,598)과 숫자가 다른 별개 값이라 그대로 보여주면 지수 포인트인 것처럼
    오해될 수 있습니다(§0-1). 대신 **당일 등락률(%)만** 표시하고 ETF 프록시 기준임을 명시합니다.

    수집에 실패한 지수는 값을 지어내지 않고 '데이터 없음 + 실패 사유'를 그대로 노출합니다.
    """
    if not indices:
        return ""
    cards = []
    for key in ("sp500", "nasdaq", "dow"):
        idx = indices.get(key)
        if not idx:
            continue
        change = idx.get("intraday_change_pct")
        if change is None:
            value_html = (
                '<div style="font-size: 20px; color: #94a3b8; font-weight: 800; margin-top: 6px;">데이터 없음</div>'
                '<div style="font-size: 11px; color: #f87171; font-weight: 600; margin-top: 2px;">'
                f'수집 실패: {esc(idx.get("error") or "원인 미상")}</div>'
            )
        else:
            color = "#4ade80" if change >= 0 else "#f87171"
            arrow = "▲" if change >= 0 else "▼"
            value_html = (
                f'<div style="font-size: 30px; color: {color}; font-weight: 800; letter-spacing: -1px; '
                f'margin-top: 4px;">{arrow} {abs(change):.2f}%</div>'
            )
        date_label = f' ({esc(idx.get("session_date"))} 장마감 기준)' if idx.get("session_date") else ""
        cards.append(f"""
        <div style="flex: 1 1 260px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
            <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">
                📈 {esc(idx.get('label_ko'))} <span style="color:#64748b; font-weight:600;">{esc(idx.get('label_en'))}</span>{date_label}
            </div>
            {value_html}
            <div style="font-size: 10.5px; color: #64748b; font-weight: 600; margin-top: 4px;">
                ETF({esc(idx.get('proxy_symbol') or '')}) 등락률 기준 — 실제 지수 포인트값이 아닌 근사치입니다
            </div>
        </div>
        """)
    if not cards:
        return ""
    return compact(
        '<div style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap;">'
        + "".join(cards) + "</div>"
    )


# =============================================================================
# 3. 카드 HTML 조립 (순수 문자열 — NiceGUI 위젯을 만들지 않습니다)
# =============================================================================
def _name_html(s) -> str:
    """한글명(정식 또는 자동 음역) + 영문명 + 티커 (오너 확정 표기 규칙).

    ⚠️ 종목명·티커는 길이가 정해져 있지 않은 외부 데이터라 `white-space: nowrap` 을 쓰지
       않습니다 — 긴 이름 카드 하나 때문에 페이지 전체 가로폭이 넓어지는 사고(#119 후속)를
       막기 위한 조치를 그대로 유지합니다.
    """
    name_kr = s.get("name_kr")
    name_en = s.get("name_en_clean") or s.get("name") or ""
    symbol = s.get("symbol", "")

    translit_badge = ""
    if name_kr:
        name_main = name_kr
        if s.get("name_kr_is_transliterated"):
            translit_badge = ' ' + tooltip(
                '음역',
                '한국에서 널리 쓰이는 정식 한글명이 없어, 영문 사명을 <b>발음대로 자동 음역</b>한 '
                '표기입니다(번역이 아닙니다).<br>규칙 기반 자동 변환이라 실제 통용 표기와 다를 수 '
                '있습니다 — 정확한 이름은 옆의 영문명과 티커를 확인해 주세요.',
                trigger_style=_TRANSLIT_BADGE_STYLE,
            )
    else:
        name_main = name_en or symbol

    return (
        f'<span style="font-size: 24px; font-weight: 800; color: #f8fafc; white-space: normal; '
        f'overflow-wrap: break-word; max-width: 260px;">{esc(name_main)}</span>'
        f'{translit_badge}'
        f'<span style="font-size: 13px; color: #94a3b8; font-weight: 600;">{esc(name_en)}</span>'
        f'<span style="font-size: 14px; color: #38bdf8; font-weight: 800; background-color: rgba(15,23,42,0.6); '
        f'padding: 2px 9px; border-radius: 6px; border: 1px solid #334155;">{esc(symbol)}</span>'
    )


def build_blocked_card_html(s, rank_num) -> str:
    """⚪ 카드 자체를 그릴 수 없는 종목(장마감 종가 없음 / 발행주식수 오염)."""
    reason = s.get("reject_reason") or s.get("unverified_reason") or "원인 미상"
    return compact(f"""
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 2px dashed #64748b; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                {rank_prefix_html(rank_num)}{_name_html(s)}
                <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid #64748b;">⚪ 데이터 없음 (측정 불가)</span>
            </div>
        </div>
        <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px; padding: 18px 24px; text-align: center;">
            <h3 style="color: #cbd5e1; font-size: 16.5px; font-weight: 800; margin: 0 0 6px 0;">🚫 필수 데이터를 수집하지 못해 밸류에이션을 산출하지 않았습니다</h3>
            <p style="color: #94a3b8; font-size: 13.5px; font-weight: 600; margin: 0; line-height: 1.5;">
                수집 실패 사유: <b>{esc(reason)}</b>
            </p>
            <div style="color: #cbd5e1; font-size: 12px; margin-top: 6px;">
                📌 값을 추정해 채우지 않고 '데이터 없음'으로 남깁니다. 다음 수집에서 정상화되면 자동 복구됩니다.
            </div>
        </div>
    </div>
    """)


def build_stock_card_html(s, rank_num) -> str:      # noqa: C901 — 원본 화면 구조를 그대로 유지
    """정상 종목 카드 1장의 HTML. (원본 `views/us_stocks_view.py` 의 카드 조립부 이식)"""
    price = s.get("price")
    t_roe = s.get("t_roe")
    roic = s.get("roic")
    roa = s.get("roa")
    beta = s.get("beta")
    roe_color = "#94a3b8" if t_roe is None else ("#f43f5e" if t_roe < 9.0 else "#4ade80")
    roic_color = "#94a3b8" if roic is None else ("#f43f5e" if roic < 8.0 else "#38bdf8")

    # ── 베타 배지 (코스피 화면의 '변동성' 배지 자리) ──────────────────────
    if beta is None:
        beta_text, beta_color = "❔ 베타 데이터 없음", "#94a3b8"
    elif beta >= 1.5:
        beta_text, beta_color = f"⚡ 고변동 (베타 {beta:.2f})", "#f43f5e"
    elif beta >= 1.0:
        beta_text, beta_color = f"🟡 시장 수준 (베타 {beta:.2f})", "#fde047"
    else:
        beta_text, beta_color = f"🟢 저변동 (베타 {beta:.2f})", "#38bdf8"

    beta_badge_html = tooltip(
        f'{esc(beta_text)} ℹ️',
        '<b>베타(5년)</b> = 이 종목이 시장(S&amp;P 500) 대비 얼마나 크게 출렁이는지 나타내는 지표입니다.<br>'
        '베타 1.0 = 시장과 동일하게 움직임 · 1.0보다 크면 시장보다 더 크게 오르내림 · 1.0보다 작으면 더 완만하게 움직임<br>'
        '(예: 베타 1.47 = 시장이 10% 움직일 때 이 종목은 평균적으로 약 14.7% 움직여온 편)<br>'
        '🟢 저변동(&lt;1.0) · 🟡 시장 수준(1.0~1.5) · ⚡ 고변동(&ge;1.5) — 저평가·고평가 판단과는 무관하게 '
        '순수 변동성(리스크) 지표입니다.',
        trigger_style=f'color: {beta_color};',
    )

    # ── 착시 저평가 배지 (미국은 ROE·ROIC 둘 다 없을 때만 '판정 불가') ────
    if s.get("value_trap"):
        trap_badge_html = quality_badge('trap')
    elif t_roe is None and roic is None:
        trap_badge_html = quality_badge('unknown')
    else:
        trap_badge_html = quality_badge('ok')

    # ── 리츠 배지 ─────────────────────────────────────────────────────────
    sector_badge_html = ""
    if s.get("is_reit"):
        sector_badge_html = tooltip(
            '🏢 리츠(REIT)',
            '부동산 투자 신탁입니다. 감가상각 때문에 순이익 기반 PER이 의미가 약해서, '
            '데이터 소스도 PER 대신 <b>Price/FFO</b>(운영자금 대비 주가)를 제공합니다.',
            trigger_style=_REIT_BADGE_STYLE,
        )

    # ── 계산값 배지 (§0-1 예시2-보충: 실측값과 반드시 구분 표기) ──────────
    calc_price_tag = warn_badge(
        "🧮 계산값",
        "장마감 종가 블록을 직접 읽지 못해 <b>시가총액 ÷ 발행주식수</b>로 역산한 값입니다 (실측 종가 아님).",
    ) if s.get("price_calculated") else ""
    calc_feps_tag = warn_badge(
        "🧮 계산값",
        "데이터 소스가 Forward EPS를 직접 주지 않아 <b>장마감 종가 ÷ Forward PER(애널리스트 컨센서스)</b>로 "
        "역산한 값입니다.<br>두 입력 모두 실측값이고 순수 나눗셈이라 계산했지만, 실측 EPS는 아닙니다.",
    ) if s.get("f_eps_calculated") else ""
    growth_capped_badge_html = warn_badge(
        "⚠️ 고성장 추정 보수반영",
        "예상 성장률이 100%를 넘어 기저효과(일시적 실적 급변) 왜곡 가능성을 의심해, 퀀트 스코어의 "
        "PEGY 항목 점수만 보수적으로 깎았습니다.<br>목표가·적정가 갭은 원래 성장률 그대로 계산되어 "
        "있습니다(값 자체는 건드리지 않음).",
    ) if s.get("growth_score_capped") else ""
    geff_capped_badge_html = warn_badge(
        "🧮 상한 적용값",
        "실효성장률이 상한(성장률 35%p / 주주환원 10%p / 합계 40%p)에 걸려 절단된 값입니다.<br>"
        f"캡 미적용 원값: {esc(fmt_num(s.get('g_eff_uncapped'), '%p', 2))}",
    ) if s.get("g_eff_capped") else ""

    score_badge_html, score_tooltip_extra = quant_score_badge(
        s.get("quant_score"), s.get("score_max"), s.get("score_excluded_items"),
    )

    # ── Forward 섹션 마스킹 사유 판정 (한 곳에서만) ───────────────────────
    was_blocked = (not s.get("is_valid", True)) or s.get("is_unverified", False)
    is_per_extreme = bool(s.get("forward_per_extreme"))
    g_eff = s.get("g_eff")
    is_negative_growth = g_eff is not None and g_eff <= 0
    is_geff_missing = (g_eff is None) and not s.get("forward_data_missing")
    forward_needs_mask = bool(
        was_blocked or is_per_extreme or is_negative_growth or is_geff_missing
        or s.get("forward_data_missing") or s.get("f_pegy") is None
    )

    # ── 그레이엄 넘버 (Forward 가 마스킹될 때만 참고용으로 노출 — 코스피와 동일 규칙) ──
    graham_box_html = ""
    if forward_needs_mask:
        graham_target = s.get("graham_target")
        if s.get("is_trailing_loss"):
            loss_reason = ", ".join(s.get("loss_evidence") or []) or "적자 판정"
            graham_box_html = graham_unavailable_box(
                "🧮 그레이엄 넘버 산출 불가 — 적자 기업 (EPS가 0 이하라 제곱근 안이 음수가 됩니다)",
                esc(loss_reason),
            )
        elif graham_target is not None and s.get("graham_is_financial_sector"):
            graham_box_html = graham_financial_box(fmt_usd(graham_target), "은행/보험/자산운용")
        elif graham_target is not None:
            graham_box_html = graham_reference_box(fmt_usd(graham_target))

    # ── 모델 목표가 대비 갭 ───────────────────────────────────────────────
    f_target = s.get("f_target")
    if price and f_target and s.get("f_target_capped"):
        cap_reason = s.get("f_target_cap_reason") or "현재가 배수 상한에 도달"
        uncapped = s.get("f_target_uncapped")
        uncapped_txt = f"캡을 적용하지 않은 산출값은 {esc(fmt_usd(uncapped))} 입니다.<br>" if uncapped else ""
        gap_str, gap_color, bar_color, bar_width = "상승여력 산출 안 함 (상한 캡 적용)", "#fbbf24", "#78716c", 100
        target_cap_badge_html = warn_badge(
            "🧮 상한 적용값",
            "이 목표가는 계산 결과가 아니라 <b>상한(캡) 값</b>입니다.<br>"
            f"{esc(cap_reason)}.<br>{uncapped_txt}"
            "고성장 종목은 PEGY 공식상 목표가가 발산하기 때문에 폭주 방지 상한을 두고 있습니다.",
        )
    elif price and f_target:
        gap_pct = ((f_target - price) / price) * 100.0
        gap_str = f"+{gap_pct:.1f}% 상승 여력" if gap_pct >= 0 else f"{abs(gap_pct):.1f}% 프리미엄"
        gap_color = "#4ade80" if gap_pct >= 0 else "#fca5a5"
        bar_color = "#22c55e" if gap_pct >= 0 else "#ef4444"
        bar_width = min(abs(gap_pct), 100)
        target_cap_badge_html = info_badge(
            "🛡️ 장부가 바닥값",
            "PEGY 역산값이 장부가(BPS)보다 낮게 나와 BPS를 대신 사용했습니다. 자세한 내용은 위 안내 참고.",
        ) if s.get("f_target_floored") else ""
    else:
        gap_str, gap_color, bar_color, bar_width, target_cap_badge_html = "측정불가", "#94a3b8", "#64748b", 0, ""

    # ── 목표가 바닥값(장부가/BPS) 적용 배너 ───────────────────────────────
    # PEGY 역산 공식이 저성장 자본집약형(보험/지주/유틸리티 등) 우량주에서 목표가를
    # 구조적으로 낮게 계산하는 문제의 보정. ROE·ROIC 우량 게이트를 통과한 종목에만 적용됩니다.
    floor_banner_html = ""
    if s.get("f_target_floored"):
        floor_banner_html = """
        <div style="background: linear-gradient(135deg, rgba(30, 58, 95, 0.55) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px solid #38bdf8; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px; display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 22px;">🛡️</span>
            <div>
                <div style="color: #7dd3fc; font-size: 13.5px; font-weight: 800;">장부가(BPS) 기준 바닥값 적용됨</div>
                <div style="color: #cbd5e1; font-size: 12px; font-weight: 500; line-height: 1.5; margin-top: 3px;">
                    PEGY 역산 공식은 성장률이 낮으면 목표가도 함께 낮아지는 구조라, 보험·지주·유틸리티처럼
                    실적 성장보다 자본배분·자산가치로 평가받는 저성장 우량주는 목표가가 비정상적으로 낮게
                    나옵니다. ROE·ROIC가 기준선 이상인 우량 종목에 한해 장부가(BPS)를 참고 하한으로 대신
                    사용했습니다. ⚠️ 재고·무형자산 손상, 부채 시가평가까지 반영한 진짜 청산가치 실사는
                    아니므로 참고용으로만 봐주세요.
                </div>
            </div>
        </div>
        """

    # ── 애널리스트 목표가(소스 실측) — 우리 모델 목표가와 별개로 항상 노출 ──
    analyst_target = s.get("analyst_target")
    if analyst_target and price:
        a_gap = (analyst_target - price) / price * 100.0
        analyst_gap_txt = (
            f"<span style='color:{'#4ade80' if a_gap >= 0 else '#fca5a5'}; font-weight:800;'>{a_gap:+.1f}%</span>"
        )
    else:
        analyst_gap_txt = f"<span style='color:#94a3b8;'>{NA_TEXT}</span>"

    analyst_tooltip = tooltip(
        '🎯 애널리스트 컨센서스 (실측) ℹ️',
        "<b>데이터 소스가 제공하는 애널리스트 목표주가·투자의견 원본값</b>입니다.<br>"
        "아래 Forward 카드의 '목표가'는 우리 PEGY 모델이 계산한 값이라 서로 다를 수 있습니다 — "
        "둘을 나란히 보여주는 이유입니다(어느 쪽도 정답이 아님).",
    )
    analyst_html = f"""
    <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; gap: 22px; flex-wrap: wrap;">
        <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">{analyst_tooltip}:</span>
        <span style="font-size: 13px; color: #e2e8f0;">목표주가
            <b style="color:#14b8a6; font-size:14px; margin-left:4px;">{esc(fmt_usd(analyst_target))}</b>
            <span style="margin-left:6px;">({analyst_gap_txt})</span></span>
        <span style="font-size: 13px; color: #e2e8f0;">투자의견
            <b style="color:#38bdf8; font-size:14px; margin-left:4px;">{esc(s.get('analyst_consensus') or NA_TEXT)}</b></span>
        <span style="font-size: 13px; color: #e2e8f0;">커버 애널리스트
            <b style="color:#cbd5e1; font-size:14px; margin-left:4px;">{esc(fmt_num(s.get('analyst_count'), '명'))}</b></span>
    </div>
    """

    # ── 🚀 Forward 섹션 ───────────────────────────────────────────────────
    if s.get("dividend_data_unverified") and not s.get("forward_data_missing") and not is_negative_growth:
        forward_section_html = forward_mask_html(
            border_color="#facc15", inner_border="#92400e", gradient_from="rgba(120, 53, 15, 0.35)",
            title_color="#fbbf24", sub_color="#fde047", corner_text="🛡️ 주주환원 데이터 확인 필요",
            icon="🛡️", headline="주주환원 데이터 검증 대기 중", body_color="#fef08a", corner_nowrap=False,
            body_html=(
                f"{esc(s.get('dividend_unverified_reason') or '배당·자사주 수익률을 수집하지 못했습니다.')}<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 수집된 값 그대로 정상 반영되어 있으니 참고해 주세요."
            ),
        )
    elif is_negative_growth:
        forward_section_html = forward_mask_html(
            border_color="#a855f7", inner_border="#6d28d9", gradient_from="rgba(59, 7, 100, 0.35)",
            title_color="#d8b4fe", sub_color="#c4b5fd", corner_text="📉 역성장 · 무성장",
            icon="📉", headline="실효성장률(g_eff) 0% 이하 — 가치 훼손 구간",
            body_color="#e9d5ff", corner_nowrap=False,
            body_html=(
                f"3년 EPS 성장 전망 <b>{esc(fmt_num(s.get('growth'), '%', 2))}</b> + 주주환원율 "
                f"<b>{esc(fmt_num(s.get('sh_return'), '%', 2))}</b> = 실효성장률 "
                f"<b>{esc(fmt_num(g_eff, '%p', 2))}</b> 로 0 이하라, 성장을 전제로 하는 PEGY 밸류에이션 적용이 부적합합니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 참고하실 수 있습니다."
            ),
        )
    elif is_per_extreme:
        forward_section_html = forward_mask_html(
            border_color="#f87171", inner_border="#991b1b", gradient_from="rgba(69, 10, 10, 0.35)",
            title_color="#fca5a5", sub_color="#fecaca", corner_text="🚫 PER 극단치",
            icon="🚫", headline="Forward PER 산출 범위 초과", corner_nowrap=False,
            body_html=(
                "애널리스트 컨센서스 기반 Forward PER이 정상 범위를 크게 벗어나 신뢰할 수 없습니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요."
            ),
        )
    elif s.get("forward_data_missing") or is_geff_missing or s.get("f_pegy") is None:
        missing_fields = s.get("forward_missing_fields") or []
        if missing_fields:
            reason_txt = (
                "이 종목은 데이터 소스에 "
                + ("Forward PER" if "f_per" in missing_fields else "")
                + (" · " if len(missing_fields) > 1 else "")
                + ("3년 EPS 성장 전망" if "growth" in missing_fields else "")
                + " 컨센서스가 없습니다."
            )
        elif is_geff_missing:
            reason_txt = "Forward 컨센서스는 있지만 주주환원율(배당+자사주)을 수집하지 못해 실효성장률을 구하지 못했습니다."
        else:
            reason_txt = "실효성장률이 너무 낮아(사실상 무성장) PEGY 공식이 성립하지 않습니다."
        forward_section_html = forward_mask_html(
            border_color="#64748b", inner_border="#334155", gradient_from="rgba(51, 65, 85, 0.35)",
            title_color="#94a3b8", sub_color="#64748b", corner_text="🔒 데이터 없음",
            icon="🔒", headline="Forward(미래 추정) 밸류에이션 산출 불가",
            headline_color="#cbd5e1", body_color="#94a3b8", corner_nowrap=False,
            body_html=(
                f"{esc(reason_txt)}<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. PEGY 점수(35점)만 배점에서 제외됩니다."
            ),
        )
    else:
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(14, 116, 144, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px solid #38bdf8; border-radius: 12px; padding: 16px 22px; box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #0284c7; padding-bottom: 8px; margin-bottom: 14px;">
                <div>
                    <div style="font-size: 16px; font-weight: 800; color: #38bdf8; line-height: 1.2;">🚀 Forward</div>
                    <div style="font-size: 13px; font-weight: 600; color: #7dd3fc; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                </div>
                <span style="font-size: 11.5px; color: #7dd3fc; font-weight: 500;">*애널리스트 컨센서스(Forward PER · 3년 EPS 성장 전망) 기반</span>
            </div>
            {floor_banner_html}
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">실효성장률 (g_eff) ℹ️<span class="vh-tooltiptext"><b>실효성장률 = 3년 EPS 성장 전망 + 주주환원율(배당+자사주)</b><br>PEGY의 분모입니다. 폭주 방지를 위해 성장률 35%p / 주주환원 10%p / 합계 40%p 상한을 둡니다(상한에 걸리면 옆에 배지가 붙습니다).</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{esc(fmt_num(g_eff, '%p', 2))}{geff_capped_badge_html}{growth_capped_badge_html}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">가치 지표 ℹ️<span class="vh-tooltiptext"><b>Forward 밸류에이션</b><br>• Forward PER: 주가 ÷ 향후 예상 EPS<br>• Forward EPS: 주가 ÷ Forward PER 로 역산한 계산값<br>• Forward PEGY: Forward PER ÷ 실효성장률 (낮을수록 저평가)</span></span>
                    </div>
                    <div style="font-size: 18px; color: #f1f5f9; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">Forward PER</span> {esc(fmt_num(s.get('f_per'), '배', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">Forward EPS</span> {esc(fmt_usd(s.get('f_eps')))}{calc_feps_tag} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PEGY</span> {esc(fmt_num(s.get('f_pegy'), '', 2))}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">3년 EPS 성장 전망 ℹ️<span class="vh-tooltiptext">데이터 소스가 제공하는 애널리스트 컨센서스(EPS Growth Forecast, 3년) 실측값입니다.<br>우리가 추정하거나 가공한 값이 아닙니다.</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{esc(fmt_num(s.get('growth'), '%', 2))}</div>
                </div>
                <div>
                    <div class="comparison-box" style="margin-bottom: 8px; border-color: #38bdf8; width: 100%;">
                        <div class="comparison-row divider">
                            <span class="label-text">현재가 (장마감 종가)</span>
                            <span class="price-text-curr">{esc(fmt_usd(price))}{calc_price_tag}</span>
                        </div>
                        <div class="comparison-row divider">
                            <span class="label-text">
                                <span class="vh-tooltip" tabindex="0" style="color: #94a3b8; font-weight: 700;">🛡️ PBR 기준 바닥가 ℹ️<span class="vh-tooltiptext" style="color: #f1f5f9; font-weight: 400;">회사의 순자산 가치 기준 심리적 바닥 가격입니다 (현재가 ÷ PBR).</span></span>
                            </span>
                            <span style="font-size: 15px; font-weight: 700; color: #94a3b8;">{esc(fmt_usd(s.get('floor_price')))}</span>
                        </div>
                        <div class="comparison-row">
                            <span class="label-text">
                                <span class="vh-tooltip" tabindex="0" style="color: #14b8a6; font-weight: 700;">모델 목표가 ℹ️<span class="vh-tooltiptext" style="color: #f1f5f9; font-weight: 400;"><b>목표 적정주가 (Forward PEGY 역산)</b><br><b>① 목표 PEGY</b> = 1.0 + ROE/ROIC 프리미엄<br><b>② 목표 PER</b> = 목표 PEGY × 실효성장률(g_eff)<br><b>③ 목표주가</b> = Forward EPS × 목표 PER<br>고성장 종목은 공식상 발산하므로 <b>목표 PER 35배 / 현재가의 2.5배</b> 상한을 둡니다.<br>⚠️ 위 '애널리스트 컨센서스' 목표주가와는 다른 값입니다(그쪽은 소스 실측, 이쪽은 우리 모델 계산).</span></span>
                            </span>
                            <span class="price-text-target">{esc(fmt_usd(f_target))}{target_cap_badge_html}</span>
                        </div>
                    </div>
                    <div class="gap-footer" style="color: {gap_color};">
                        <span>모델 적정가 대비 갭</span>
                        <span>{gap_str}</span>
                    </div>
                    <div class="gap-bar-bg">
                        <div style="height: 100%; width: {bar_width}%; background-color: {bar_color}; border-radius: 3px;"></div>
                    </div>
                </div>
            </div>
        </div>
        """

    # ── 적자 경고 배너 ────────────────────────────────────────────────────
    loss_banner = ""
    if s.get("is_trailing_loss"):
        loss_reason = ", ".join(s.get("loss_evidence") or []) or "적자 판정"
        loss_banner = loss_banner_html(
            "⚠️ 적자 기업 — PEGY 밸류에이션 산출 불가",
            f"판정 근거: {esc(loss_reason)}. 데이터 소스도 적자 기업의 PER을 제공하지 않습니다(n/a).\n"
            "성장 기반 밸류에이션(PEGY)을 적용할 수 없으니 각별한 주의가 필요합니다.",
        )

    # ── Trailing 지표 ─────────────────────────────────────────────────────
    per_display = esc(fmt_num(s.get("t_per"), "배", 2))
    if s.get("t_per") is None and s.get("is_reit"):
        per_display = (
            f"n/a <span style='font-size:12px;color:#93c5fd;'>(리츠 — P/FFO "
            f"{esc(fmt_num(s.get('price_ffo'), '배', 2))})</span>"
        )
    elif s.get("t_per") is None and s.get("is_trailing_loss"):
        per_display = "n/a <span style='font-size:12px;color:#fca5a5;'>(적자 — 소스 미제공)</span>"

    dps = s.get("dps")
    dps_str = fmt_usd(dps) + "/주" if dps else ("무배당 확정" if s.get("dividend_status") == "confirmed_none" else NA_TEXT)

    return compact(f"""
    <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <!-- 1. 메인 헤더: 종목명(한글/영문/티커) / 퀀트종합점수 / 배지 / 장마감 종가 -->
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                {rank_prefix_html(rank_num)}{_name_html(s)}
                <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px; font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                    <span class="vh-tooltip" tabindex="0" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="vh-tooltiptext"><b>종합 퀀트 스코어 (미국 종목용)</b><br>PEGY 35 + 자본효율성(ROE·ROIC) 30 + 주주환원 20 + 재무건전성(F-Score) 10 + 변동성(베타) 5<br>수집하지 못한 지표는 점수를 지어내지 않고 배점에서 아예 제외하므로 만점은 종목마다 다릅니다.<br>{score_tooltip_extra}</span></span> {score_badge_html}
                </span>
                <span style="background-color: {esc(s.get('badge_bg') or '#1e293b')}; color: {esc(s.get('badge_fg') or '#cbd5e1')}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {esc(s.get('badge_fg') or '#64748b')}; white-space: normal; overflow-wrap: break-word; max-width: 260px; display: inline-block;">
                    {esc(s.get('badge') or '—')}
                </span>
                <span style="font-size: 12px; color: {beta_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6); padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">
                    {beta_badge_html}
                </span>
                {trap_badge_html}
                {sector_badge_html}
            </div>
            <div style="display: flex; align-items: baseline; gap: 8px;">
                <span style="font-size: 13px; color: #94a3b8;">장마감 종가:</span>
                <span style="font-size: 25px; font-weight: 900; color: #38bdf8;">{esc(fmt_usd(price))}</span>{calc_price_tag}
            </div>
        </div>

        {loss_banner}

        <!-- 2. 자본효율성 품질 바 -->
        <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; gap: 28px; flex-wrap: wrap;">
            <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">ROE ℹ️<span class="vh-tooltiptext"><b>자기자본이익률</b><br>순이익 ÷ 자기자본. 미국 시장 기준선은 15% 안팎이며, 9% 미만이면 자본비용도 못 버는 구간으로 봅니다.</span></span>:
                <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(t_roe, '%', 2))}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">ROIC ℹ️<span class="vh-tooltiptext"><b>투하자본이익률</b><br>세후영업이익 ÷ 투하자본. WACC(미국 대형주 8~10%)와 비교합니다.<br>은행·보험은 투하자본 개념이 달라 데이터 소스가 n/a로 제공합니다(수집 실패가 아님).</span></span>:
                <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(roic, '%', 2))}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">ROA ℹ️<span class="vh-tooltiptext"><b>총자산이익률</b> — 순이익 ÷ 총자산</span></span>:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(roa, '%', 2))}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">F-Score ℹ️<span class="vh-tooltiptext"><b>피오트로스키 F-Score (0~9)</b><br>수익성·재무건전성·운영효율 9개 항목을 점검하는 회계학 표준 스코어입니다. 높을수록 재무가 튼튼합니다.</span></span>:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(s.get('piotroski_f'), ' / 9'))}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">시가총액:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_big_usd(s.get('market_cap')))}</b>
            </span>
        </div>

        <!-- 3. 애널리스트 컨센서스 (소스 실측) -->
        {analyst_html}

        <!-- 4. Trailing 섹션 (과거 실적 참고용) -->
        <div style="background-color: rgba(30, 41, 59, 0.45); border: 1px solid #334155; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px; opacity: 0.92;">
            <div style="font-size: 12px; font-weight: 700; color: #94a3b8; margin-bottom: 10px; border-bottom: 1px dashed #475569; padding-bottom: 4px; display: flex; justify-content: space-between; align-items: center;">
                <span>📜 Trailing (과거 실적 참고용)</span>
                <span style="font-size: 11px; color: #64748b; font-weight: 400;">*최근 12개월(TTM) 확정 실적 스냅샷</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">Trailing ROE ℹ️<span class="vh-tooltiptext">과거 12개월 자기자본 대비 순이익 비율</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #cbd5e1;">{esc(fmt_num(t_roe, '%', 2))}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">가치 및 회수 지표 ℹ️<span class="vh-tooltiptext"><b>Trailing 밸류에이션</b><br>• PER: 주가÷순이익 • EPS: 주당순이익 • PBR: 주가÷순자산 • EV/EBITDA: M&amp;A 투자원금 회수기간</span></span>
                    </div>
                    <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PER</span> {per_display} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">EPS</span> {esc(fmt_usd(s.get('t_eps')))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PBR</span> {esc(fmt_num(s.get('t_pbr'), '배', 2))}
                    </div>
                    <div style="font-size: 18px; color: #38bdf8; font-weight: 800; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">EV/EBITDA</span> {esc(fmt_num(s.get('ev_ebitda'), '배', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">BPS</span> {esc(fmt_usd(s.get('bps')))}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">주주환원 (확정) ℹ️<span class="vh-tooltiptext"><b>주주환원 세부 내역</b><br>• 주당배당금(DPS): {esc(dps_str)}<br>• 배당수익률: {esc(fmt_num(s.get('div_yield'), '%', 2))}<br>• 자사주 매입 수익률: {esc(fmt_num(s.get('buyback_yield'), '%', 2))}<br>• 배당성향: {esc(fmt_num(s.get('payout_ratio'), '%', 2))}<br>※ 미국은 배당보다 자사주 매입 비중이 큰 기업이 많아, 점수에는 <b>둘을 합친 주주환원율</b>을 씁니다.<br>※ 증자·주식보상으로 주식수가 늘면 이 값은 <b>음수</b>가 될 수 있습니다(희석).</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #86efac;">
                        주주환원율 {esc(fmt_num(s.get('sh_return'), '%', 2))}
                        <span style="font-size: 13px; color: #94a3b8;">(배당 {esc(fmt_num(s.get('div_yield'), '%', 2))} + 자사주 {esc(fmt_num(s.get('buyback_yield'), '%', 2))})</span>
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">PEGY / 과거 적정가 ℹ️<span class="vh-tooltiptext"><b>Trailing PEGY &amp; 과거 적정주가</b><br>• PEGY: Trailing PER ÷ 실효성장률<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{esc(fmt_num(s.get('t_pegy'), '', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">/</span> {esc(fmt_usd(s.get('t_fair')))}</div>
                </div>
            </div>
        </div>

        <!-- 5. 그레이엄 넘버 (Forward 가 마스킹될 때만) -->
        {graham_box_html}

        <!-- 6. Forward 섹션 (데이터 없으면 이 섹션만 마스크 처리) -->
        {forward_section_html}
    </div>
    """)


# =============================================================================
# 4. 페이지
# =============================================================================
@ui.page('/us')
def us_stocks_index_page() -> None:
    """공개 화면. 로그인 불필요 — 사용자별 데이터가 전혀 없습니다(§0-3-8)."""
    with layout('🇺🇸 미국 주식은 이가격', width_class='max-w-6xl'):
        _render_body()


def _render_body() -> None:                        # noqa: C901 — 원본 화면 순서를 그대로 유지
    admin = is_admin()

    metadata, all_stocks = load_us_snapshot()
    # 버퍼 구간(추적은 하되 화면에는 안 띄우는 종목)은 제외합니다.
    # is_visible 필드가 없는 구버전 스냅샷은 전부 노출(True)로 간주해 하위 호환을 유지합니다.
    all_stocks = [s for s in all_stocks if s.get("is_visible", True)]

    _render_title()

    index_html = build_index_header_html(metadata.get("indices") or {})
    if index_html:
        ui.html(index_html).classes('w-full')

    # ── §0-1 회귀 검사 지점 ──────────────────────────────────────────────
    # 스냅샷이 없으면 **숫자를 하나도 그리지 않고** 빨간 배너만 띄우고 끝냅니다.
    if not all_stocks:
        error_banner(
            f"🚨 미국주식 스냅샷을 불러오지 못했습니다. ({metadata.get('load_error', '원인 미상')})\n\n"
            "가짜 기본값으로 화면을 채우지 않기 위해 밸류에이션 수치를 표시하지 않습니다. "
            "자동 수집(GitHub Actions `US Stocks Scraper`)이 정상 동작했는지 확인해 주세요."
        )
        return

    last_updated_et = metadata.get("last_updated_at_et")
    last_updated_kst = metadata.get("last_updated_at_kst")
    snapshot_status = metadata.get("status", "UNKNOWN")

    if snapshot_status not in ("SUCCESS", "UNKNOWN"):
        warning_banner(
            f"⚠️ 스냅샷 수집 상태: {snapshot_status} — "
            f"검증 통과 {metadata.get('valid_count', '?')}/{metadata.get('total_count', '?')}종목. "
            "일부 종목은 데이터 부족으로 '측정 불가' 카드로 표시됩니다."
        )

    # 수집 실패 종목은 조용히 건너뛰지 않고 전부 화면에 기록합니다 (§0-1).
    failed = metadata.get("failed_tickers") or []
    if failed:
        with ui.expansion(
            f"⚠️ 수집 실패 {len(failed)}종목 (조용히 건너뛰지 않고 전부 기록합니다)"
        ).classes('w-full').props('dense-toggle'):
            for item in failed[:100]:
                ui.label(f"- {item.get('symbol')}: {item.get('reason')}").classes('vh-muted')
            if len(failed) > 100:
                ui.label(f"... 외 {len(failed) - 100}종목").classes('vh-muted')

    ui.html(compact(f"""
        <div style="background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #0284c7; border-radius: 10px; padding: 12px 20px; margin-bottom: 22px; text-align: center;">
            <span style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">
                📅 마지막 동기화: {esc(last_updated_et or NA_TEXT)} ET
                <span style="font-size: 13px; color: #7dd3fc;">({esc(last_updated_kst or NA_TEXT)} KST)</span>
            </span>
            <span style="font-size: 13px; color: #94a3b8; margin-left: 14px; font-weight: 600;">
                • 미국 장마감 후 확정 데이터 ({esc(metadata.get('total_count', len(all_stocks)))}개 종목 / 상태 {esc(snapshot_status)})
            </span>
        </div>
    """)).classes('w-full')

    _render_raw_downloads()
    render_summary_metrics(all_stocks, load_us_summary_history(), (
        "미국 상위 종목 중앙 Forward PER",
        "중앙 3년 EPS 성장 전망 (컨센서스)",
        "시장 적정 밸류에이션 (PEGY)",
    ))

    ui.separator()

    all_badge_options = list(dict.fromkeys([s["badge"] for s in all_stocks if s.get("badge")]))

    # ── 상태는 전부 이 함수의 지역 변수입니다 (계획서 §3-3 / §0-3-8) ──────
    view = {
        'search': '',
        'preset': FILTER_PRESETS[0],
        'badges': list(all_badge_options),
        'value_trap_only': False,
        'page': 1,
    }

    def _selected_badges():
        """프리셋 → 배지 목록. (원본 selectbox/multiselect 분기 그대로)"""
        preset = view['preset']
        if "세부 뱃지" in preset:
            return view['badges']
        if "저평가 우량주" in preset:
            return [b for b in all_badge_options if "저평가" in b and "고평가" not in b]
        if "적정가" in preset:
            return [b for b in all_badge_options if "적정가" in b]
        if "고평가" in preset:
            return [
                b for b in all_badge_options
                if ("고평가" in b or "역성장" in b or "위험" in b or "검증" in b)
                and not any(nb in b for nb in _NON_WARNING_BADGES)
            ]
        return None

    def _filtered():
        stocks = all_stocks
        query = view['search']
        if query:
            q = query.lower()
            stocks = [
                s for s in stocks
                if q in (s.get("name") or "").lower()
                or q in (s.get("name_kr") or "")
                or q in (s.get("symbol") or "").lower()
            ]
        badges = _selected_badges()
        if badges:
            stocks = [s for s in stocks if s.get("badge") in badges]
        if view['value_trap_only']:
            stocks = [s for s in stocks if s.get("value_trap")]
        return stocks

    def _on_filter_change() -> None:
        view['page'] = 1              # 필터가 바뀌면 항상 1페이지부터 (원본과 동일)
        _results.refresh()

    # ── 필터 컨트롤 ──────────────────────────────────────────────────────
    with ui.row().classes('w-full items-start gap-4'):
        def _on_search(event) -> None:
            view['search'] = (event.value or '').strip()
            _on_filter_change()

        ui.input('🔍 종목명 / 티커 검색', placeholder='예: 엔비디아, NVIDIA, NVDA', on_change=_on_search) \
            .props('clearable') \
            .style('flex: 1 1 220px;')

        with ui.column().classes('gap-2').style('flex: 1 1 260px;'):
            def _on_preset(event) -> None:
                view['preset'] = event.value
                _badge_selector.refresh()
                _on_filter_change()

            ui.select(FILTER_PRESETS, value=FILTER_PRESETS[0], label='🏷️ 밸류에이션 빠른 필터',
                      on_change=_on_preset).classes('w-full')

            @ui.refreshable
            def _badge_selector() -> None:
                if "세부 뱃지" not in view['preset']:
                    return

                def _on_badges(event) -> None:
                    view['badges'] = list(event.value or [])
                    _on_filter_change()

                ui.select(all_badge_options, value=list(all_badge_options), multiple=True,
                          label='상세 뱃지 선택', on_change=_on_badges) \
                    .props('use-chips') \
                    .classes('w-full')

            _badge_selector()

        def _on_trap(event) -> None:
            view['value_trap_only'] = bool(event.value)
            _on_filter_change()

        ui.checkbox("⚠️ '착시 저평가' 주의 종목만 보기", on_change=_on_trap) \
            .style('flex: 1 1 240px;') \
            .tooltip(
                'PER은 싸 보이지만 실제 이익창출력(ROE·ROIC)이 기준선에 못 미쳐 주가가 오래 갇힐 '
                '위험이 있는 종목입니다.'
            )

    _render_guide_box()

    # 종목별 데이터 다운로드 도구 — 아래 카드 목록/페이지네이션과 완전히 분리된 섹션입니다.
    render_stock_download_tool(
        all_stocks,
        fields=US_HISTORY_FIELDS,
        history_filename=US_HISTORY_FILENAME,
        key_field=US_KEY_FIELD,
        key_of=lambda s: s.get("symbol") or "nosymbol",
        name_of=lambda s: s.get("name_kr") or s.get("name_en_clean") or s.get("name") or "종목명 없음",
        subtitle_of=lambda s: f'{s.get("name_en_clean") or s.get("name") or NA_TEXT} · {s.get("symbol")}',
        price_text_of=lambda s: fmt_usd(s.get("price")),
        matches=lambda s, q: (
            q.lower() in (s.get("name") or "").lower()
            or q.lower() in (s.get("name_kr") or "")
            or q.lower() in (s.get("symbol") or "").lower()
        ),
        search_label='🔍 종목명 / 티커 검색',
        search_placeholder='예: 엔비디아, NVIDIA, NVDA',
        empty_hint='📌 종목명(한글·영문) 또는 티커를 입력하면 후보 목록이 나타납니다.',
        no_match_hint='종목명 일부(한글·영문) 또는 티커로 다시 검색해 주세요. '
                      '(이 화면은 미국 시가총액 상위 종목만 담고 있습니다.)',
        price_label='최신 종가',
        caption='검색해서 종목을 고르면, 그 종목의 **날짜별 이력**(하루 한 줄)을 표로 내보냅니다. '
                '항목은 카드에 보이는 재무 지표(PER·PBR·ROE·ROIC·베타·F-Score·주주환원·목표주가·퀀트 스코어 등)이고 '
                '열 이름은 한국어입니다. 이 검색창은 다운로드 전용이라 아래 종목 카드 목록에는 영향을 주지 않습니다.',
    )

    # ── 결과(개수 + 카드 + 페이지네이션) ─────────────────────────────────
    @ui.refreshable
    def _results() -> None:
        filtered_stocks = _filtered()
        total_items = len(filtered_stocks)
        total_pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        current_page = min(view['page'], total_pages)
        view['page'] = current_page

        ui.markdown(
            f'**전체 검색/필터 결과:** `{total_items}`개 종목 (총 {len(all_stocks)}개 미국 종목 중)'
        )
        ui.separator()

        if not filtered_stocks:
            warning_banner('선택한 필터 조건에 일치하는 종목이 없습니다.')
            return

        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        page_stocks = filtered_stocks[start_idx:start_idx + ITEMS_PER_PAGE]

        for offset, s in enumerate(page_stocks):
            rank_num = s.get("rank", start_idx + offset + 1)
            # 진짜 카드를 그릴 수 없는 경우(장마감 종가 없음 / 발행주식수 오염)만 전체 차단하고,
            # 나머지는 Trailing 을 정상 노출하고 Forward 자리에만 사유별 마스크를 띄웁니다
            # (ENGINEERING_SPEC.md §0-1 예시2-보충2).
            reject_reason = s.get("reject_reason", "")
            hard_block = (not s.get("is_valid", True)) and (
                "장마감 종가" in reject_reason or "발행주식수" in reject_reason
            )
            markup = build_blocked_card_html(s, rank_num) if hard_block \
                else build_stock_card_html(s, rank_num)
            ui.html(markup).classes('w-full')

            if admin and (s.get("data_issues") or s.get("collect_errors")):
                _render_admin_issues(s)

        ui.separator()
        ui.markdown(f'##### 📄 페이지 선택 (한 화면에 {ITEMS_PER_PAGE}개 종목 카드 노출)')

        def _on_page(page: int) -> None:
            view['page'] = page
            _results.refresh()

        # 페이지 이동 시 최상단 스크롤은 pager() 안에서 처리합니다.
        # (원본의 `<a href="#us-top-anchor">` 앵커는 iframe 전제라 NiceGUI 에서는 쓰지 않습니다.)
        pager(total_pages, current_page, _on_page)

    _results()
    disclaimer_footer()


def _render_admin_issues(s) -> None:
    """⚙️ 관리자 전용 수집 이슈 목록.

    ⚠️ `ui.label` 은 텍스트를 그대로(이스케이프해서) 그립니다 — 수집 이슈 문구에는 URL·따옴표가
       섞여 있어 HTML 로 그리면 깨지거나 주입 위험이 생깁니다(§0-3-9).
    """
    issues = s.get("data_issues") or []
    errors = s.get("collect_errors") or []
    with ui.expansion(
        f"⚙️ [관리자] {s.get('symbol')} 수집 이슈 {len(issues)}건"
    ).classes('w-full').props('dense-toggle'):
        for issue in errors:
            ui.label(f"- (수집) {issue}").classes('vh-muted')
        for issue in issues:
            ui.label(f"- {issue}").classes('vh-muted')


# =============================================================================
# 5. 정적 블록 (제목 · 경고문 · 가이드 · 다운로드)
# =============================================================================
# ⚠️ 아래 두 조각은 **f-string 이 아닙니다.** 사이에 들어가는 "📘 학습용 보조 도구 안내" 문구는
#    코스피 화면과 글자 하나까지 같아서 `web/components` 에 단일 출처로 두고 여기서는 이어
#    붙이기만 합니다(§0-3-10). f-string 을 쓰지 않는 이유는 #129(중괄호 이스케이프 사고) 재발 방지.
_TITLE_HEAD = """
<div style="text-align: center; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
    <h1 style="font-size: 36px; font-weight: 800; color: #d97706; margin: 0 0 6px 0; letter-spacing: -0.5px;">🇺🇸 미국 주식은 이가격</h1>
    <div style="background: linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%); border: 2px solid #ef4444; border-radius: 12px; padding: 12px 22px; margin: 10px auto 14px auto; max-width: 860px;">
        <div style="font-size: 15px; font-weight: 800; color: #fca5a5;">
            🚨 [투자 주의 경고 및 분석 안내]
        </div>
        <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
            본 리포트의 수치는 <b>공개된 재무 데이터를 퀀트 알고리즘이 자동 계산한 단순 참고용 정보</b>입니다.<br>
            특정 종목의 매수·매도를 권유하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
        </div>
        <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
            ⚠️ 모든 투자 결정과 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있습니다.
            환율 변동 위험은 이 화면에 반영되어 있지 않습니다(가격은 전부 USD 표기).
        </div>
    </div>
"""

_TITLE_TAIL = """
    <div style="font-size: 15.5px; color: #64748b; font-weight: 600;">미국(나스닥+뉴욕) 시가총액 상위 550개 종목 Trailing vs Forward PEGY &amp; 퀀트 종합점수 리포트<br><span style="font-size: 13px; color: #475569;">(만점은 종목마다 다릅니다 — 수집하지 못한 지표는 점수를 지어내지 않고 배점에서 제외합니다. 모든 금액은 <b>미국 달러(USD)</b> 표기이며 원화 환산을 하지 않습니다)</span></div>
</div>
"""


def _render_title() -> None:
    ui.html(compact(_TITLE_HEAD + LEARNING_NOTICE_HTML + _TITLE_TAIL)).classes('w-full')


def _render_raw_downloads() -> None:
    """가공 스냅샷 / 크롤링 원본(raw) 다운로드 (§0-3-3 — raw 도 사용자가 받을 수 있어야 함).

    ⚠️ 파일 내용은 **클릭한 순간에** 읽습니다. raw 스냅샷은 4MB 가 넘어서, 접속할 때마다
       미리 읽으면 모든 방문자가 그 비용을 부담하게 됩니다(계획서 §11-2).
    """
    latest_path = data_path(US_SNAPSHOT_FILENAME)
    raw_path = data_path(US_RAW_SNAPSHOT_FILENAME)
    date_str = datetime.now().strftime('%Y%m%d')

    with ui.row().classes('w-full gap-3 items-center'):
        if os.path.exists(latest_path):
            download_button(
                '📥 미국주식 최신 스냅샷 다운로드 (가공 데이터, JSON)',
                f'us_stocks_latest_{date_str}.json',
                lambda: read_download_bytes(latest_path),
                media_type='application/json',
            )
        if os.path.exists(raw_path):
            download_button(
                '📥 크롤링 원본(raw) 다운로드 (JSON)',
                f'us_stocks_raw_{date_str}.json',
                lambda: read_download_bytes(raw_path),
                media_type='application/json',
            )


def _render_guide_box() -> None:
    ui.html(compact("""
        <div style="background-color: #0f172a; border: 1px solid #0284c7; border-radius: 12px; padding: 16px 22px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 15px; font-weight: 800; color: #38bdf8; margin-bottom: 10px;">
                💡 미국주식 퀀트 스코어 / 코스피 화면과 다른 점
            </div>
            <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65;">
                • <b style="color: #fef08a;">🏆 퀀트 스코어</b>: PEGY(35) + 자본효율성 ROE·ROIC(30) + 주주환원(20)
                + 재무건전성 F-Score(10) + 변동성 베타(5) = 이론상 100점.<br>
                수집하지 못한 지표는 배점에서 제외하므로 <b>실제 만점은 종목마다 다릅니다</b>
                (은행은 ROIC 15점, 컨센서스가 없으면 PEGY 35점이 빠집니다).<br>
                • <b style="color: #7dd3fc;">코스피 화면과의 차이</b>: ① 성장률은 애널리스트 <b>3년 EPS 성장 전망</b>
                실측치를 그대로 씁니다(추정 EPS 증감률 계산 아님), ② 주주환원율에 <b>자사주 매입</b>이 포함됩니다
                (미국은 배당보다 비중이 큰 기업이 많음, 희석 시 음수 가능), ③ 20일 실측 변동성 대신 <b>베타(5Y)</b>를 쓰며
                실효성장률에 벌점을 곱하지 않고 점수 항목으로만 반영합니다.<br>
                • <b style="color: #fca5a5;">⚠️ 착시 저평가</b>: ROE &lt; 9% 또는 ROIC &lt; 8% 인 종목에 태그를 붙입니다.
            </div>
        </div>
    """)).classes('w-full')
