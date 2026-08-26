"""
💡 사실 이 가격이에요 — 코스피 밸류에이션 리포트 (공개 기본 화면, URL `/`).

`views/pegy_view.py`(Streamlit, 1,540줄)의 NiceGUI 이식본입니다 (이전 계획서 2단계).
Streamlit 쪽 원본은 컷오버까지 그대로 살려둡니다(듀얼런 — 계획서 §11-1).

이식 방침
  - **수집·검증·가공 계층(`utils/*`)은 한 줄도 건드리지 않고 그대로 재사용**합니다(계획서 §1-2).
    이 파일은 순수 표현 계층입니다 — 데이터 가공·계산식을 여기에 새로 넣지 마세요
    (ENGINEERING_SPEC.md §6 표현 계층 규칙).
  - 카드 HTML 은 원본 f-string 을 `ui.html(...)` 에 그대로 옮겼습니다. 다만
    ① 툴팁 클래스명 `q-tooltip` → `vh-tooltip` (Quasar 내장 클래스와 충돌 회피, `web/theme.py` 참고),
    ② 외부에서 온 문자열(종목명·배지·사유 등)은 전부 `esc()` 통과 (§0-3-9 XSS),
    ③ 여러 곳에 복붙돼 있던 앰버 배지는 `web/components` 의 `warn_badge()` 로 통일 (§0-3-10).
  - 상태(검색어·필터·페이지)는 `st.session_state` 가 아니라 **페이지 함수의 지역 변수**입니다.
    NiceGUI 는 한 프로세스가 모든 접속자를 처리하므로 전역에 두면 서로 섞입니다(§0-3-8, 계획서 §3-3).
  - 스냅샷이 없으면 숫자를 하나도 그리지 않고 빨간 배너만 띄웁니다 (§0-1, 완료기준 ⑦).
"""

import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

import pandas as pd
from nicegui import ui

from utils.db import COL_MAP, HISTORY_FILE
from utils.guardrail import apply_valuation_guardrail
from utils.stock_history import (
    KOSPI_HISTORY_FIELDS,
    KOSPI_HISTORY_FILENAME,
    KOSPI_KEY_FIELD,
)

from web import ads
from web.auth import is_admin
from web.blocking import run_blocking
from web.components import (
    LEARNING_NOTICE_HTML,
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
    info_banner,
    loss_banner_html,
    pager,
    quality_badge,
    quant_score_badge,
    rank_prefix_html,
    render_stock_download_tool,
    render_summary_metrics,
    warn_badge,
    warning_banner,
)
from web.layout import layout
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file,
    load_json_file_async,
    read_download_bytes,
)

SNAPSHOT_FILENAME = "kospi200_pegy_latest.json"
SUMMARY_HISTORY_FILENAME = "pegy_summary_history.json"
ITEMS_PER_PAGE = 20

FILTER_PRESETS = [
    "🌐 전체 종목 보기 (500개 코스피+코스닥)",
    "🟢 저평가 우량주 그룹 (강력저평가 + 저평가)",
    "🟡 적정가 형성 그룹 (적정가 + 목표달성)",
    "🔴 고평가 / 주의 종목 그룹 (고평가 + 역성장 + 주의)",
    "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)",
]


# =============================================================================
# 1. 데이터 로드 (읽기 전용 — 렌더링 중에 수집기를 절대 실행하지 않습니다)
# =============================================================================
def load_latest_kospi_usd():
    """
    market_history.csv에서 가장 최근 코스피 지수·원/달러 환율만 가볍게 읽어옵니다.
    실패해도 절대 지어내지 않고 None을 반환합니다.

    ⚠️ **동기 함수입니다 — 화면에서 직접 부르지 마세요.** 부르는 자리
       (`_render_market_snapshot()`)가 `run_blocking()` 으로 별도 스레드에서 실행합니다.
       로컬 디스크 읽기라 보통은 밀리초 단위지만, `pandas.read_csv()` 는 이력이 쌓일수록
       느려지고 무엇보다 **이 화면('/')이 이번 사고가 실제로 신고된 화면**입니다. 한
       프로세스뿐인 이벤트 루프 위에서 도는 블로킹 호출은 예외 없이 밖으로 내보냅니다
       (`web/blocking.py` 모듈 독스트링).
       동기판을 남겨 두는 이유는 `web/state.load_json_file` 과 같습니다 — 읽기 규칙이
       한 곳에만 있어야 하고, 이벤트 루프 밖의 호출자도 그대로 쓸 수 있어야 합니다.
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            return None
        df = pd.read_csv(HISTORY_FILE)
        df = df.rename(columns={v: k for k, v in COL_MAP.items()})
        if df.empty or "KOSPI" not in df.columns or "USD_KRW" not in df.columns:
            return None
        last = df.iloc[-1]
        kospi = float(last["KOSPI"]) if pd.notna(last.get("KOSPI")) else None
        usd = float(last["USD_KRW"]) if pd.notna(last.get("USD_KRW")) else None
        date_str = str(last["Date"]) if "Date" in df.columns and pd.notna(last.get("Date")) else None
        if kospi is None or usd is None:
            return None
        return {"kospi": kospi, "usd": usd, "date": date_str}
    except Exception as exc:                      # noqa: BLE001 — 상세는 로그로만 (§0-3-4)
        print(f"⚠️ 코스피/환율 요약 로드 실패: {exc}")
        return None


async def load_kospi200_snapshot():
    """
    data/kospi200_pegy_latest.json 스냅샷 로드 및 메타데이터 반환.

    ⚠️ 렌더링 도중에 수집기(collector_kospi200.py)를 절대 실행하지 않습니다.
       스냅샷이 없거나 깨졌으면 '현재 시각'을 마지막 동기화 시각인 것처럼 꾸미지 않고
       last_updated_at=None / status="LOAD_FAILED" 를 그대로 반환합니다 (§0-1).

    🔴 2026-08-21 — `async def` 로 바뀌었습니다. 반환값은 그대로이고, 파일을 읽는 동안
       이벤트 루프를 붙잡지 않습니다(이유는 `web/state.load_json_file_async` 주석 참고).
    """
    payload, load_error = await load_json_file_async(data_path(SNAPSHOT_FILENAME))
    if payload is None:
        return {"last_updated_at": None, "status": "LOAD_FAILED", "load_error": load_error}, []

    meta = dict(payload.get("metadata", {}))
    stocks = payload.get("stocks", [])
    if not stocks:
        meta["status"] = meta.get("status") or "EMPTY"
        meta["load_error"] = "스냅샷에 종목 데이터가 0건입니다."
    return meta, stocks


async def load_pegy_summary_history():
    """data/pegy_summary_history.json 누적 수치 이력을 로드합니다. 없으면 빈 목록."""
    path = data_path(SUMMARY_HISTORY_FILENAME)
    if not os.path.exists(path):
        return []
    payload, load_error = await load_json_file_async(path)
    if payload is None:
        warning_banner(f"⚠️ 누적 요약 히스토리를 읽지 못했습니다. {load_error}")
        return []
    return payload


# =============================================================================
# 2. 카드 HTML 조립 (순수 문자열 — NiceGUI 위젯을 만들지 않습니다)
# =============================================================================
def build_blocked_card_html(s, rank_num) -> str:
    """⚪ 카드 자체를 그릴 수 없는 종목(price 없음 / 상장주식수 파싱 오류)."""
    reason = s.get("reject_reason") or s.get("unverified_reason") or "원인 미상"
    badge_label = "⚪ 데이터 없음 (측정 불가)"
    badge_bg = "#1e293b"
    badge_border = "#64748b"
    badge_fg = "#cbd5e1"
    card_bg = "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)"
    card_border_color = "#64748b"
    inner_border = "#334155"
    title_icon = "🚫"
    title_text = "필수 데이터를 수집하지 못해 밸류에이션을 산출하지 않았습니다"
    title_color = "#cbd5e1"
    desc_color = "#94a3b8"
    hint_text = "📌 값을 추정해 채우지 않고 '데이터 없음'으로 남깁니다. 다음 수집에서 정상화되면 자동 복구됩니다."

    # ⚠️ 이식하며 고친 점: 원본은 `{s['price']:,.0f}` 라 **price 가 없어서 차단된 종목**에서
    #    TypeError 로 화면이 통째로 죽었습니다(§0-3-4 위반 경로). 값이 없으면 '데이터 없음'.
    return compact(f"""
    <div style="background: {card_bg}; border: 2px dashed {card_border_color}; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.5); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid {inner_border}; padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                {rank_prefix_html(rank_num)}
                <span style="font-size: 22px; font-weight: 800; color: {badge_fg};">{esc(s.get('name') or '종목명 없음')}</span>
                <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({esc(s.get('code'))})</span>
                <span style="background-color: {badge_bg}; color: {badge_fg}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {badge_border}; white-space: nowrap;">
                    {badge_label}
                </span>
            </div>
            <div style="display: flex; align-items: baseline; gap: 8px;">
                <span style="font-size: 13px; color: #94a3b8;">현재가:</span>
                <span style="font-size: 22px; font-weight: 900; color: #38bdf8;">{esc(fmt_num(s.get('price'), '원', 0))}</span>
            </div>
        </div>
        <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid {inner_border}; border-radius: 10px; padding: 18px 24px; text-align: center;">
            <h3 style="color: {title_color}; font-size: 16.5px; font-weight: 800; margin: 0 0 6px 0;">{title_icon} {title_text}</h3>
            <p style="color: {desc_color}; font-size: 13.5px; font-weight: 600; margin: 0; line-height: 1.5;">
                수집 실패 사유: <b>{esc(reason)}</b>
            </p>
            <div style="color: #cbd5e1; font-size: 12px; margin-top: 6px;">
                {hint_text}
            </div>
        </div>
    </div>
    """)


def build_stock_card_html(s, rank_num, admin: bool) -> str:      # noqa: C901 — 원본 화면 구조를 그대로 유지
    """정상 종목 카드 1장의 HTML. (원본 `views/pegy_view.py` 의 카드 조립부 이식)"""
    vol_text = s.get("vol") or "❔ 변동성 데이터 없음"
    if "데이터 없음" in vol_text:
        vol_color = "#94a3b8"
    elif "확대" in vol_text or "보정" in vol_text:
        vol_color = "#f43f5e"
    else:
        vol_color = "#38bdf8"

    t_roe_val = s.get("t_roe")
    roic_val = s.get("roic")
    roe_color = "#94a3b8" if t_roe_val is None else ("#f43f5e" if t_roe_val < 8.0 else "#4ade80")
    roic_color = "#94a3b8" if roic_val is None else ("#f43f5e" if roic_val < 6.0 else "#38bdf8")

    # Forward ROE 컨센서스가 Trailing 대비 크게 뛰는 경우 — 값은 손대지 않고 배지로 맥락만 전달
    f_roe_val = s.get("f_roe")
    roe_gap_flag = bool(
        t_roe_val is not None and f_roe_val is not None and t_roe_val > 0
        and (f_roe_val >= t_roe_val * 2.5 or (f_roe_val - t_roe_val) >= 25.0)
    )
    roe_gap_badge_html = warn_badge(
        "⚡ 추정치 변동 큼",
        f"Trailing({t_roe_val:.1f}%) 대비 Forward 추정치가 큰 폭으로 높습니다({f_roe_val:.1f}%)."
        "<br>반도체 등 경기순환 업종은 실적 사이클상 실제로 이런 추정이 나올 수 있으나, "
        "애널리스트 컨센서스 특성상 오차가 클 수 있으니 참고용으로만 활용하세요.",
    ) if roe_gap_flag else ""

    # 성장률 100% 이상이면 PEGY '점수'만 보수적으로 캡 (f_pegy 값 자체는 건드리지 않음)
    growth_capped_badge_html = warn_badge(
        "⚠️ 고성장 추정 보수반영",
        "예상 성장률이 100%를 넘어 기저효과(일시적 실적 급변) 왜곡 가능성을 의심, 퀀트 스코어의 "
        "PEGY 항목 점수만 보수적으로 깎았습니다.<br>목표가·적정가 갭은 원래 성장률 그대로 계산되어 "
        "있으니(점수만 영향, 값 자체는 건드리지 않음) 함께 참고하세요.",
    ) if s.get("growth_score_capped") else ""

    # 착시 저평가 판정 기준은 화면마다 다릅니다(코스피는 Trailing ROE 단독 — ROIC 원천
    # 데이터를 수집하지 않으므로). 배지 모양만 공용 컴포넌트에서 가져옵니다.
    if s.get("value_trap", False):
        trap_badge_html = quality_badge('trap')
    elif t_roe_val is None:
        trap_badge_html = quality_badge('unknown')
    else:
        trap_badge_html = quality_badge('ok')

    # 야후 파이낸스 교차검증 뱃지 (관리자 전용) — 미수행(None)과 이상없음(False)을 구분
    discrepancy_badge_html = ""
    if admin:
        if s.get("per_discrepancy") is True:
            discrepancy_badge_html = """
            <span style="background-color: #78350f; color: #fde047; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #facc15; white-space: nowrap;">
                ⚙️ [관리자용] 데이터 이격 발생 (yfinance 차이>15%)
            </span>
            """
        elif s.get("per_discrepancy") is None:
            discrepancy_badge_html = """
            <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #64748b; white-space: nowrap;">
                ⚙️ [관리자용] 외부 교차검증 미수행
            </span>
            """

    t_eps_str = fmt_num(s.get("t_eps"))
    # Trailing EPS 가 실측이 아니라 계산값(가격÷PER 역산)이면 반드시 마크 (§0-1 예시2-보충)
    calc_eps_tag = warn_badge(
        "🧮 계산값",
        "네이버에 실측 EPS가 없어 가격÷PER 로 역산한 값입니다 (실측 아님)",
    ) if s.get("t_eps_calculated") else ""

    t_pbr_str = fmt_num(s.get("t_pbr"))
    ev_ebitda = s.get("ev_ebitda")
    ev_ebitda_str = fmt_num(ev_ebitda)
    ev_years_str = ""
    try:
        ev_val = float(ev_ebitda)
        ev_years_str = f" <span style='font-size: 11px; color: #94a3b8; font-weight: 500;'>(약 {ev_val:.1f}년)</span>"
    except (ValueError, TypeError):
        pass

    dps_val = s.get("dps") or 0
    dps_str = f"{dps_val:,.0f}원/주" if dps_val > 0 else "무배당"
    calc_dps_tag = warn_badge(
        "🧮 계산값",
        "재무제표에 확정 DPS가 없어 배당수익률로 역산한 값입니다 (실측 아님)",
    ) if s.get("dps_source") == "derived_from_div_yield" else ""

    growth_val = s.get("growth")
    growth_disp = "데이터 없음" if growth_val is None else f"{growth_val:+.1f}%"
    if str(s.get("growth_source", "")).endswith("_calculated"):
        growth_disp += calc_eps_tag

    price = s.get("price") or 0

    # 콘크리트 바닥가 (현재가 ÷ PBR)
    floor_price_str = "데이터 없음"
    try:
        pbr_val = float(s.get("t_pbr"))
        if pbr_val > 0:
            floor_price_str = f"{price / pbr_val:,.0f}원"
    except (ValueError, TypeError):
        pass

    # ── 목표가 대비 갭 ────────────────────────────────────────────────────
    # 캡(현재가×2.5)에 걸린 종목은 "+150%"가 계산 결과가 아니라 상수 그 자체이므로,
    # 숫자를 앞세우지 않고 "산출 안 함"으로 표기합니다(2026-08-06 2차 감사 1-3).
    f_target = s.get("f_target")
    target_cap_badge_html = ""
    if price > 0 and f_target and bool(s.get("f_target_capped")):
        cap_reason = s.get("f_target_cap_reason") or "현재가 배수 상한에 도달"
        uncapped = s.get("f_target_uncapped")
        uncapped_txt = f"캡을 적용하지 않은 산출값은 {uncapped:,}원입니다.<br>" if uncapped else ""
        gap_str = "상승여력 산출 안 함 (상한 캡 적용)"
        gap_color = "#fbbf24"
        bar_color = "#78716c"        # 계산된 상승여력이 아니므로 초록 바를 쓰지 않습니다
        bar_width = 100
        target_cap_badge_html = warn_badge(
            "🧮 상한 적용값",
            "이 목표가는 계산 결과가 아니라 <b>상한(캡) 값</b>입니다.<br>"
            f"{esc(cap_reason)}.<br>{uncapped_txt}"
            "고성장 종목은 PEGY 공식상 목표가가 발산하기 때문에 폭주 방지 상한을 두고 있으며, "
            '상한에 걸린 종목의 상승여력은 "최소 이만큼"이라는 뜻일 뿐 정밀한 추정치가 아닙니다.',
        )
    elif price > 0 and f_target:
        gap_pct = ((f_target - price) / price) * 100.0
        gap_str = f"+{gap_pct:.1f}% 상승 여력" if gap_pct >= 0 else f"{abs(gap_pct):.1f}% 프리미엄"
        gap_color = "#4ade80" if gap_pct >= 0 else "#fca5a5"
        bar_color = "#22c55e" if gap_pct >= 0 else "#ef4444"
        bar_width = min(abs(gap_pct), 100)
    else:
        gap_str = "측정불가"
        gap_color = "#94a3b8"
        bar_color = "#64748b"
        bar_width = 0

    # Trailing 적정가(t_fair)도 같은 상한에 걸릴 수 있으므로 동일하게 표시합니다.
    t_fair_cap_badge_html = ""
    if s.get("t_fair_capped"):
        t_fair_uncapped = s.get("t_fair_uncapped")
        t_fair_uncapped_txt = f"캡 미적용 산출값 {t_fair_uncapped:,}원.<br>" if t_fair_uncapped else ""
        t_fair_cap_badge_html = warn_badge(
            "🧮 상한 적용값",
            "과거 적정가가 현재가 2.5배 상한에 걸려 절단된 값입니다.<br>"
            f"{t_fair_uncapped_txt}계산 결과가 아니라 상한값입니다.",
        )

    # ── 퀀트 스코어 — 기본값 80점 금지. 만점(score_max)이 없으면 % 도 지어내지 않습니다 ──
    score_badge_html, score_tooltip_extra = quant_score_badge(
        s.get("quant_score"), s.get("score_max"), s.get("score_excluded_items"),
    )

    # ── Forward 카드를 마스킹해야 하는 사유 판정 (한 곳에서만) ─────────────
    # 우선순위: 배당 미확정 > 역성장 > PER 극단치 > g_eff 산출불가 > 일반 검증 실패 > Forward 결측 > 정상
    reject_reason = s.get("reject_reason", "")
    unverified_reason = s.get("unverified_reason", "")
    was_blocked = (not s.get("is_valid", True)) or s.get("is_unverified", False)
    is_per_extreme = was_blocked and ("PER" in reject_reason)
    is_geff_missing = was_blocked and ("실효성장률" in reject_reason)
    is_negative_growth_case = was_blocked and (
        bool(s.get("is_negative_growth")) or (s.get("g_eff") is not None and s["g_eff"] <= 0)
    )
    is_generic_harness_fail = (
        was_blocked
        and not is_per_extreme and not is_geff_missing and not is_negative_growth_case
        and not s.get("forward_data_missing")
    )
    forward_needs_mask = bool(
        s.get("dividend_data_unverified") or is_negative_growth_case or is_per_extreme
        or is_geff_missing or is_generic_harness_fail or s.get("forward_data_missing")
    )

    # ── 그레이엄 넘버 (Trailing 전용 참고 목표가) ─────────────────────────
    # 적자 기업은 √ 안이 음수라 수학적으로 산출 불가 — 스냅샷에 값이 남아 있어도 표시하지 않습니다
    # (2026-08-06 2차 감사 3-2 방어적 크로스체크: 모순된 화면을 만들지 않습니다).
    is_loss_making = bool(
        s.get("is_trailing_loss")
        or (t_roe_val is not None and t_roe_val < 0)
        or (s.get("t_eps") is not None and s.get("t_eps") <= 0)
        or (s.get("t_per_measured") is not None and s.get("t_per_measured") < 0)
    )

    graham_box_html = ""
    if forward_needs_mask:
        graham_target = s.get("graham_target")
        if is_loss_making:
            loss_reason = ", ".join(s.get("loss_evidence") or []) or f"Trailing ROE {fmt_num(t_roe_val, '%')}"
            graham_box_html = graham_unavailable_box(
                "🧮 그레이엄 넘버 산출 불가 — 적자 기업 (EPS가 0 이하라 제곱근 안이 음수가 됩니다)",
                esc(loss_reason),
            )
        elif graham_target is not None and s.get("graham_is_financial_sector", False):
            # 금융주는 공식의 전제(제조업 장부가)가 잘 안 맞으므로 값은 보여주되 강한 경고 배지를 붙입니다.
            graham_box_html = graham_financial_box(f"{graham_target:,.0f}원", "은행/보험/증권")
        elif graham_target is not None:
            graham_box_html = graham_reference_box(f"{graham_target:,.0f}원")
        else:
            graham_box_html = graham_unavailable_box(
                "🧮 그레이엄 넘버 산출 불가 (적자 기업 — EPS가 0 이하라 수학적으로 계산할 수 없음)",
                headline_color="#64748b",
            )

    # ── 🚀 Forward 섹션 ───────────────────────────────────────────────────
    if s.get("dividend_data_unverified"):
        forward_section_html = forward_mask_html(
            border_color="#facc15", inner_border="#92400e", gradient_from="rgba(120, 53, 15, 0.35)",
            title_color="#fbbf24", sub_color="#fde047", corner_text="🛡️ 배당 데이터 확인 필요",
            icon="🛡️", headline="주주환원 데이터 검증 대기 중",
            body_html=(
                f"{esc(s.get('dividend_unverified_reason') or '리츠/인프라/금융 등 배당 필수 업종인데 DPS·배당수익률이 0으로 수집되었습니다.')}<br>"
                "위 <b>Trailing(과거 실적)</b> 지표와 퀀트 점수는 수집된 값 그대로 정상 반영되어 있으니 참고해 주세요."
            ),
        )
    elif is_negative_growth_case:
        forward_section_html = forward_mask_html(
            border_color="#a855f7", inner_border="#6d28d9", gradient_from="rgba(59, 7, 100, 0.35)",
            title_color="#d8b4fe", sub_color="#c4b5fd", corner_text="📉 역성장 · 무성장",
            icon="📉", headline="실효성장률(g_eff) 0% 이하 — 가치 훼손 구간",
            body_html=(
                f"본 종목은 <b>ROE {esc(fmt_num(s.get('t_roe'), '%'))}</b> 기준 실효성장률(성장률+주주환원율)이 0 이하로 계산되어,<br>"
                "성장을 전제로 하는 PEGY 밸류에이션 적용이 부적합합니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 참고하실 수 있으나, 퀀트 종합점수는 이 사유로 산출되지 않습니다."
            ),
        )
    elif is_per_extreme:
        forward_section_html = forward_mask_html(
            border_color="#f87171", inner_border="#991b1b", gradient_from="rgba(69, 10, 10, 0.35)",
            title_color="#fca5a5", sub_color="#fecaca", corner_text="🚫 PER 극단치",
            icon="🚫", headline="Forward PER 산출 범위 초과",
            body_html=(
                "애널리스트 컨센서스 기반 Forward PER이 정상 범위(300배)를 크게 벗어나 신뢰할 수 없습니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. 퀀트 종합점수는 산출되지 않습니다."
            ),
        )
    elif is_geff_missing:
        forward_section_html = forward_mask_html(
            border_color="#64748b", inner_border="#334155", gradient_from="rgba(51, 65, 85, 0.35)",
            title_color="#94a3b8", sub_color="#64748b", corner_text="🔒 실효성장률 산출 불가",
            icon="🔒", headline="실효성장률(g_eff) 산출 불가",
            body_html=(
                "Forward 컨센서스는 있지만, 성장률·주주환원율 계산에 필요한 값이 부족해 g_eff를 구하지 못했습니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. 퀀트 종합점수는 산출되지 않습니다."
            ),
        )
    elif is_generic_harness_fail:
        forward_section_html = forward_mask_html(
            border_color="#facc15", inner_border="#92400e", gradient_from="rgba(120, 53, 15, 0.35)",
            title_color="#fbbf24", sub_color="#fde047", corner_text="🛡️ 데이터 검증 실패",
            icon="🛡️", headline="데이터 검증 실패 (PER·EPS 교차검증)",
            body_html=(
                "수집 단계의 데이터 검증(DataValidator)을 통과하지 못했습니다:<br>"
                f"<b>{esc(unverified_reason or '사유 미상')}</b><br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 참고용으로 노출되며, 퀀트 종합점수는 검증 통과 전까지 산출되지 않습니다."
            ),
        )
    elif s.get("forward_data_missing"):
        forward_section_html = forward_mask_html(
            border_color="#64748b", inner_border="#334155", gradient_from="rgba(51, 65, 85, 0.35)",
            title_color="#94a3b8", sub_color="#64748b", corner_text="🔒 데이터 없음",
            icon="🔒", headline="예상 실적(Forward) 데이터 없음",
            body_html=(
                "이 종목은 증권사 애널리스트 컨센서스(추정 PER·EPS) 커버리지가 없어 네이버에도 데이터가 없습니다.<br>"
                "위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. PEGY 점수(35점)만 배점에서 제외됩니다."
            ),
        )
    else:
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(14, 116, 144, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px solid #38bdf8; border-radius: 12px; padding: 16px 22px; box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);">
            <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 4px 8px; border-bottom: 1.5px solid #0284c7; padding-bottom: 8px; margin-bottom: 14px;">
                <div>
                    <div style="font-size: 16px; font-weight: 800; color: #38bdf8; line-height: 1.2;">🚀 Forward</div>
                    <div style="font-size: 13px; font-weight: 600; color: #7dd3fc; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                </div>
                <!-- 2026-08-16 오너 신고 — 이 문구가 white-space: nowrap 이라 좁은 화면에서 줄바꿈되지 않고
                     카드·페이지 폭을 통째로 밀어내 가로 스크롤이 생기던 버그. nowrap 을 없애고 최대 너비를 줍니다. -->
                <span style="font-size: 11.5px; color: #7dd3fc; font-weight: 500; white-space: normal; overflow-wrap: break-word; text-align: right; max-width: 220px;">*네이버 '추정 PER·EPS' 컨센서스 기반 (변동성 확대 시 정도에 비례한 벌점 반영, 1.05~1.40x)</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">Forward ROE ℹ️<span class="vh-tooltiptext"><b>Forward ROE</b><br>네이버 재무제표의 애널리스트 컨센서스 연간 추정치입니다.<br>커버리지가 없는 종목은 값을 만들어내지 않고 '데이터 없음'으로 둡니다.</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{esc(fmt_num(s.get('f_roe'), '%', 1))}{roe_gap_badge_html}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">가치 지표 ℹ️<span class="vh-tooltiptext"><b>Forward 밸류에이션</b><br>• PER: 주가 / 12개월 추정 EPS<br>• EPS: 향후 12개월 예상 주당순이익</span></span>
                    </div>
                    <div style="font-size: 18px; color: #f1f5f9; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward PER ℹ️<span class="vh-tooltiptext">내년에 벌어들일 돈에 비해 현재 주가가 몇 배인가? (낮을수록 저렴)</span></span> {esc(fmt_num(s.get('f_per'), '배', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward EPS ℹ️<span class="vh-tooltiptext">주식 1주가 내년 1년 동안 벌어들일 것으로 예상되는 순수익(원)</span></span> {esc(fmt_num(s.get('f_eps'), '원', 0))}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">예상 성장률 ℹ️<span class="vh-tooltiptext"><b>예상 EPS 성장률 (%)</b><br>네이버 '추정 EPS(컨센서스)' 와 'TTM EPS' 의 실제 증감률입니다.<br>둘 중 하나라도 수집되지 않으면 값을 만들지 않고 '데이터 없음'으로 둡니다.</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{growth_disp}{growth_capped_badge_html}</div>
                </div>
                <div>
                    <div class="comparison-box" style="margin-bottom: 8px; border-color: #38bdf8; width: 100%;">
                        <div class="comparison-row divider">
                            <span class="label-text">현재가</span>
                            <span class="price-text-curr">{price:,.0f}원</span>
                        </div>
                        <div class="comparison-row divider">
                            <span class="label-text">
                                <span class="vh-tooltip" tabindex="0" style="color: #94a3b8; font-weight: 700;">🛡️ PBR 계산의 바닥가 ℹ️<span class="vh-tooltiptext" style="color: #f1f5f9; font-weight: 400;">회사가 가진 순수한 재산 가치를 기준으로 산정한 심리적 바닥 가격입니다. (현재가 ÷ PBR로 계산됨)</span></span>
                            </span>
                            <span style="font-size: 15px; font-weight: 700; color: #94a3b8;">{floor_price_str}</span>
                        </div>
                        <div class="comparison-row">
                            <span class="label-text">
                                <span class="vh-tooltip" tabindex="0" style="color: #14b8a6; font-weight: 700;">목표가 (Target) ℹ️<span class="vh-tooltiptext" style="color: #f1f5f9; font-weight: 400;"><b>목표 적정주가 (Forward PEGY 역산)</b><br>PEGY(=PER÷실효성장률) 공식을 거꾸로 풀어서 계산해요.<br><b>① 목표 PEGY</b> = 기준 1.0배 + ROE/ROIC 프리미엄(이익 창출력이 좋을수록 더 비싼 배수를 인정)<br><b>② 목표 PER</b> = 목표 PEGY × Forward 실효성장률(g_eff = 예상 성장률+주주환원율(배당 등), 변동성 벌점 반영)<br><b>③ 목표주가</b> = Forward EPS × 목표 PER<br>Forward EPS·PER은 네이버 '추정 컨센서스' 기반입니다.<br>다만 고성장 종목은 공식상 값이 발산하기 때문에 <b>목표 PER 25배 / 현재가의 2.5배</b> 상한을 둡니다. 상한에 걸린 종목에는 옆에 '🧮 상한 적용값' 배지가 붙습니다.</span></span>
                            </span>
                            <span class="price-text-target">{esc(fmt_num(f_target, '원', 0))}{target_cap_badge_html}</span>
                        </div>
                    </div>
                    <div class="gap-footer" style="color: {gap_color};">
                        <span>적정가 대비 갭</span>
                        <span>{gap_str}</span>
                    </div>
                    <div class="gap-bar-bg">
                        <div style="height: 100%; width: {bar_width}%; background-color: {bar_color}; border-radius: 3px;"></div>
                    </div>
                </div>
            </div>
        </div>
        """

    # ── 적자 경고 배너 (ROE 마이너스) ────────────────────────────────────
    # 원본은 카드 f-string 안에 f-string 을 중첩(`{"" if ... else f'''...'''}`)하고 있었는데,
    # 그 형태가 #129(중괄호 이스케이프 사고)와 같은 계열의 위험이라 밖으로 빼서 평평하게 만들었습니다.
    # 출력 HTML 은 동일합니다.
    loss_banner = ""
    if t_roe_val is not None and t_roe_val < 0:
        loss_banner = loss_banner_html(
            f"⚠️ 적자 기업 — PEGY 밸류에이션 산출 불가 (ROE {esc(t_roe_val)}%)",
            "본 종목은 최근 12개월 기준 <b>순이익 적자(ROE &lt; 0)</b> 상태로, 성장 기반 밸류에이션(PEGY)을 적용할 수 없습니다.\n"
            "아래 목표주가·적정가는 <b>참고 불가</b>하며, 이익 정상화 전까지 투자에 각별한 주의가 필요합니다.",
        )

    t_eps_display = t_eps_str if t_eps_str == "데이터 없음" else t_eps_str + "원"
    t_pbr_display = t_pbr_str if t_pbr_str == "데이터 없음" else t_pbr_str + "배"
    ev_display = ev_ebitda_str if ev_ebitda_str == "데이터 없음" else ev_ebitda_str + "배"

    return compact(f"""
    <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <!-- 1. 메인 헤더: 종목명 / 코드 / 퀀트종합점수 / 배지 / 현재가 -->
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                {rank_prefix_html(rank_num)}
                <!-- 2026-08-16 오너 신고(#119 후속) — 종목명·배지는 길이가 고정돼 있지 않은 실제
                     데이터라 white-space: nowrap 이 걸려 있으면 긴 이름 카드 단 하나 때문에 페이지
                     전체의 가로 스크롤 폭이 넓어집니다. span 안에서도 줄바꿈되게 normal 로 둡니다. -->
                <span style="font-size: 24px; font-weight: 800; color: #f8fafc; white-space: normal; overflow-wrap: break-word; max-width: 260px;">{esc(s.get('name') or '종목명 없음')}</span>
                <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({esc(s.get('code'))})</span>
                <!-- 퀀트 종합점수 뱃지 -->
                <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px; font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                    <span class="vh-tooltip" tabindex="0" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="vh-tooltiptext"><b>종합 퀀트 스코어</b><br>이 회사가 얼마나 돈을 잘 벌고, 주주에게 잘 나눠주고, 가격이 싼지를 종합적으로 채점한 점수예요!<br>수집하지 못한 지표는 점수를 지어내지 않고 배점에서 아예 제외합니다.<br>{score_tooltip_extra}</span></span> {score_badge_html}
                </span>
                <span style="background-color: {esc(s.get('badge_bg') or '#1e293b')}; color: {esc(s.get('badge_fg') or '#cbd5e1')}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {esc(s.get('badge_fg') or '#64748b')}; white-space: normal; overflow-wrap: break-word; max-width: 260px; display: inline-block;">
                    {esc(s.get('badge') or '뱃지 없음')}
                </span>
                <span style="font-size: 12px; color: {vol_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6); padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">{esc(vol_text)}</span>
                {trap_badge_html}
                {discrepancy_badge_html}
            </div>
            <div style="display: flex; align-items: baseline; gap: 8px;">
                <span style="font-size: 13px; color: #94a3b8;">현재가:</span>
                <span style="font-size: 25px; font-weight: 900; color: #38bdf8;">{esc(fmt_num(s.get('price'), '원', 0))}</span>
            </div>
        </div>

        {loss_banner}

        <!-- 2. 자본효율성 품질 바 (Quality Bar) -->
        <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; justify-content: flex-start; gap: 28px; flex-wrap: wrap;">
            <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">Trailing ROE ℹ️<span class="vh-tooltiptext"><b>Trailing ROE (자기자본이익률)</b><br>지난 12개월(4분기 합산) 순이익을 자기자본으로 나눈 자본 효율성 지표입니다. 8% 미만 시 이익 창출력이 부족한 상태입니다.</span></span>:
                <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(t_roe_val, '%', 1))}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">Forward ROE ℹ️<span class="vh-tooltiptext"><b>Forward ROE (예상 자기자본이익률)</b><br>네이버 재무제표의 애널리스트 컨센서스 연간 추정치입니다.<br>커버리지가 없는 종목은 값을 추정해 채우지 않고 '데이터 없음'으로 표시합니다.</span></span>:
                <b style="color: #38bdf8; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(s.get('f_roe'), '%', 1))}</b>{roe_gap_badge_html}
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="vh-tooltip" tabindex="0">ROIC (ROC) ℹ️<span class="vh-tooltiptext"><b>ROIC (영업 투입자본이익률)</b><br>영업이익 ÷ 투하자본으로 별도 산출해야 하는 지표입니다.<br>현재 이 프로젝트는 해당 원천 데이터를 수집하지 않으므로 '데이터 없음'으로 표시합니다.</span></span>:
                <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{esc(fmt_num(roic_val, '%', 1))}</b>
            </span>
        </div>

        <!-- 3. Trailing 섹션 (과거 실적 참고용) -->
        <div style="background-color: rgba(30, 41, 59, 0.45); border: 1px solid #334155; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px; opacity: 0.88;">
            <div style="font-size: 12px; font-weight: 700; color: #94a3b8; margin-bottom: 10px; border-bottom: 1px dashed #475569; padding-bottom: 4px; display: flex; justify-content: space-between; align-items: center;">
                <span>📜 Trailing (과거 실적 참고용)</span>
                <span style="font-size: 11px; color: #64748b; font-weight: 400;">*과거 12개월 실적 스냅샷</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">Trailing ROE ℹ️<span class="vh-tooltiptext"><b>Trailing ROE</b><br>과거 12개월 평균 자기자본 대비 순이익 비율</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #cbd5e1;">{esc(fmt_num(t_roe_val, '%', 1))}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">가치 및 회수 지표 ℹ️<span class="vh-tooltiptext"><b>Trailing 밸류에이션</b><br>• PER: 주가/순이익<br>• EPS: 주당순이익<br>• PBR: 주가/순자산<br>• EV/EBITDA: M&amp;A 투자원금 회수기간</span></span>
                    </div>
                    <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PER ℹ️<span class="vh-tooltiptext">1년 동안 번 돈에 비해 주가가 몇 배인가? (낮을수록 저렴)</span></span> {esc(fmt_num(s.get('t_per'), '배', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EPS ℹ️<span class="vh-tooltiptext">주식 1주가 1년 동안 벌어온 순수익(원)</span></span> {esc(t_eps_display)}{calc_eps_tag} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PBR ℹ️<span class="vh-tooltiptext">회사 전 재산을 다 팔았을 때 가치 대비 주가가 몇 배인가? (1배 이하면 바겐세일)</span></span> {esc(t_pbr_display)}
                    </div>
                    <div style="font-size: 18px; color: #38bdf8; font-weight: 800; letter-spacing: -0.4px;">
                        <span class="vh-tooltip" tabindex="0" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EV/EBITDA (M&amp;A 원금회수) ℹ️<span class="vh-tooltiptext">회사를 통째로 샀을 때, 장사해서 본전 뽑는 기간</span></span> {esc(ev_display)}{ev_years_str.replace("11px", "13px")}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">작년 배당률 (확정) ℹ️<span class="vh-tooltiptext"><b>주주환원 세부 내역 — 가장 최근 마감된 회계연도 기준</b><br>배당은 실제 지급돼야 확정되는 값이라, 아래 수치는 올해 실제 지급 내역이 아니라 <b>작년(가장 최근 확정 회계연도)</b> 재무제표 기준입니다.<br>• 1주당 배당금 (DPS): {esc(dps_str)}<br>• 배당 총 규모: {esc(s.get('return_total') or '데이터 없음')}<br>• 배당수익률: {esc(fmt_num(s.get('sh_return'), '%', 2))}<br>※ {esc(s.get('sh_return_basis') or '배당수익률만 반영 (자사주 매입 공시 미수집)')}</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #86efac;">DPS {esc(dps_str)}{calc_dps_tag} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> 배당수익률 {esc(fmt_num(s.get('sh_return'), '%', 2))} <span style="font-size: 13px; color: #94a3b8;">({esc(s.get('return_total') or '데이터 없음')})</span></div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="vh-tooltip" tabindex="0">PEGY / 과거 적정가 ℹ️<span class="vh-tooltiptext"><b>Trailing PEGY &amp; 과거 적정주가</b><br>• PEGY: PER / (성장률 + 주주환원율)<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{esc(fmt_num(s.get('t_pegy'), '', 2))} <span style="color: #475569; font-size: 15px; margin: 0 4px;">/</span> {esc(fmt_num(s.get('t_fair'), '원', 0))}{t_fair_cap_badge_html}</div>
                </div>
            </div>
        </div>

        <!-- 3-1. 그레이엄 넘버 (Trailing 전용 참고 목표가) -->
        {graham_box_html}

        <!-- 4. Forward 섹션 (데이터 없으면 이 섹션만 마스크 처리) -->
        {forward_section_html}
    </div>
    """)


# =============================================================================
# 3. 페이지
# =============================================================================
@ui.page('/', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def pegy_index_page() -> None:
    """공개 기본 화면. 로그인 불필요 — 사용자별 데이터가 전혀 없습니다(§0-3-8)."""
    with layout('💡 사실 이 가격이에요', width_class='max-w-6xl'):
        await _render_body()


async def _render_body() -> None:                  # noqa: C901 — 원본 화면 순서를 그대로 유지
    admin = is_admin()

    metadata, all_stocks = await load_kospi200_snapshot()
    # 히스테리시스 버퍼(2026-08-06 도입) 적용 시 JSON에는 201~230위 버퍼 구간 종목도 함께
    # 저장되지만(요약 이력이 끊기지 않게 하기 위함), 화면 노출은 항상 정확히 200위 이내만입니다.
    # is_visible 필드가 없는 구버전 스냅샷은 전부 노출(True)로 간주해 하위 호환을 유지합니다.
    all_stocks = [s for s in all_stocks if s.get("is_visible", True)]
    last_updated_at = metadata.get("last_updated_at")   # 없으면 None (현재 시각으로 위장 금지)
    snapshot_status = metadata.get("status", "UNKNOWN")

    _render_title()
    await _render_market_snapshot()

    # ── §0-1 회귀 검사 지점 (완료기준 ⑦) ────────────────────────────────
    # 스냅샷이 없으면 **숫자를 하나도 그리지 않고** 빨간 배너만 띄우고 끝냅니다.
    # (`st.stop()` 은 NiceGUI 에서 그냥 return 입니다 — 계획서 부록 A)
    if last_updated_at is None or not all_stocks:
        error_banner(
            f"🚨 시가총액 상위 200 스냅샷을 불러오지 못했습니다. ({metadata.get('load_error', '원인 미상')})\n\n"
            "가짜 기본값으로 화면을 채우지 않기 위해 밸류에이션 수치를 표시하지 않습니다. "
            "자동 수집(GitHub Actions `Daily Market Scraper`)이 정상 동작했는지 확인해 주세요."
        )
        return

    summary_history = await load_pegy_summary_history()

    # 스냅샷이 언제 것인지, 수집 품질이 어땠는지 화면에 그대로 노출.
    # last_updated_at 은 KST 벽시계 값으로 저장되므로(collector_kospi200.py) 비교 기준도 KST 로 맞춥니다.
    stale_hours = None
    try:
        now_kst_naive = datetime.now(KST).replace(tzinfo=None) if KST else datetime.now()
        stale_hours = (now_kst_naive - datetime.strptime(last_updated_at, "%Y-%m-%d %H:%M")).total_seconds() / 3600.0
    except Exception:                              # noqa: BLE001 — 형식이 달라도 화면은 계속 그립니다
        stale_hours = None

    # "자동 수집이 멈춰 있는지 확인해 주세요"는 운영자용 지시문이라 관리자에게만 노출합니다.
    # (실제 데이터 시점 자체는 아래 "마지막 동기화" 배너에 이미 정직하게 표기됩니다 — §0-1)
    if stale_hours is not None and stale_hours >= 24 and admin:
        error_banner(
            f"🚨 [관리자 전용] 마지막 수집이 {stale_hours / 24:.1f}일 전({last_updated_at}) 입니다. "
            "아래 수치는 최신 시세가 아닙니다. 자동 수집이 멈춰 있는지 확인해 주세요."
        )

    if snapshot_status not in ("SUCCESS", "UNKNOWN"):
        warning_banner(
            f"⚠️ 스냅샷 수집 상태: {snapshot_status} — "
            f"검증 통과 {metadata.get('valid_count', '?')}/{metadata.get('total_count', '?')}종목. "
            "일부 종목은 데이터 부족으로 '측정 불가' 카드로 표시됩니다."
        )

    ui.html(compact(f"""
        <div style="background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #0284c7; border-radius: 10px; padding: 12px 20px; margin-bottom: 22px; text-align: center; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.25); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <span style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">
                📅 마지막 동기화: {esc(last_updated_at)} (크롤링 완료 후 장마감 데이터 적용)
            </span>
            <span style="font-size: 13px; color: #94a3b8; margin-left: 14px; font-weight: 600;">
                • 배치 수집 스냅샷 ({esc(metadata.get('total_count', len(all_stocks)))}개 종목 / 상태 {esc(snapshot_status)})
            </span>
        </div>
    """)).classes('w-full')

    _render_raw_downloads(admin)
    render_summary_metrics(all_stocks, summary_history, (
        "타겟 중앙 Forward PER",
        "국내 대표 EPS 성장률 (컨센서스 EPS 기준)",
        "시장 적정 밸류에이션 (PEGY)",
    ))

    ui.separator()

    # ── 가드레일 판정: 스냅샷에 저장된 결과를 그대로 신뢰 (단일 출처) ──────
    # 구버전 스냅샷(해당 필드 없음)일 때만 하위호환으로 재실행합니다.
    processed_stocks = []
    legacy_rescreened = 0
    for s in all_stocks:
        if 'forward_data_missing' in s:
            processed_stocks.append(s)
        else:
            processed_stocks.append(apply_valuation_guardrail(s))
            legacy_rescreened += 1
    if legacy_rescreened and admin:
        info_banner(
            f"ℹ️ [관리자] 구버전 스냅샷 {legacy_rescreened}종목은 guardrail 판정 결과가 저장돼 있지 않아 "
            "화면에서 재실행했습니다. 다음 수집 이후에는 저장된 판정을 그대로 사용합니다."
        )

    all_badge_options = list(dict.fromkeys([s["badge"] for s in processed_stocks if s.get("badge")]))

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
            return [b for b in all_badge_options if "저평가" in b]
        if "적정가" in preset:
            return [b for b in all_badge_options if "적정가" in b]
        if "고평가" in preset:
            return [b for b in all_badge_options
                    if ("고평가" in b or "역성장" in b or "오류" in b or "검증" in b or "위험" in b)]
        return None

    def _filtered():
        stocks = processed_stocks
        query = view['search']
        if query:
            stocks = [
                s for s in stocks
                if query.lower() in (s.get("name") or "").lower() or query in (s.get("code") or "")
            ]
        badges = _selected_badges()
        if badges:
            stocks = [s for s in stocks if s.get("badge") in badges]
        if view['value_trap_only']:
            stocks = [s for s in stocks if s.get("value_trap", False)]
        return stocks

    def _on_filter_change() -> None:
        view['page'] = 1              # 필터가 바뀌면 항상 1페이지부터 (원본과 동일)
        _results.refresh()

    # ── 필터 컨트롤 ──────────────────────────────────────────────────────
    with ui.row().classes('w-full items-start gap-4'):
        def _on_search(event) -> None:
            view['search'] = (event.value or '').strip()
            _on_filter_change()

        ui.input('🔍 종목명 / 종목코드 검색', placeholder='예: 삼성전자, 005930', on_change=_on_search) \
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
                          label='상세 뱃지 스마트 선택', on_change=_on_badges) \
                    .props('use-chips') \
                    .classes('w-full')

            _badge_selector()

        def _on_trap(event) -> None:
            view['value_trap_only'] = bool(event.value)
            _on_filter_change()

        ui.checkbox("⚠️ '착시 저평가' 주의 종목만 보기", on_change=_on_trap) \
            .style('flex: 1 1 240px;') \
            .tooltip(
                '주가가 PER 수치상 싸 보이지만, 실제 이익창출력(Trailing ROE<8%)이 낮아 오랜 기간 주가가 '
                '오르지 못하고 갇히는 위험 종목입니다. (ROIC 기준은 원천 데이터 미수집으로 판정에 사용하지 않습니다)'
            )

    _render_guide_box()

    # 종목별 데이터 다운로드 도구 — 아래 카드 목록/페이지네이션과 완전히 분리된 섹션입니다.
    await render_stock_download_tool(
        processed_stocks,
        fields=KOSPI_HISTORY_FIELDS,
        history_filename=KOSPI_HISTORY_FILENAME,
        key_field=KOSPI_KEY_FIELD,
        key_of=lambda s: s.get("code") or "nocode",
        name_of=lambda s: s.get("name") or "종목명 없음",
        subtitle_of=lambda s: f'({s.get("code") or ""})',
        price_text_of=lambda s: fmt_num(s.get("price"), suffix="원", digits=0),
        matches=lambda s, q: (
            q.lower() in (s.get("name") or "").lower() or q in (s.get("code") or "")
        ),
        search_label='🔍 종목명 / 종목코드 검색',
        search_placeholder='예: 삼성전자, 005930',
        empty_hint='📌 종목명 또는 종목코드를 입력하면 후보 목록이 나타납니다.',
        no_match_hint='종목명 일부 또는 6자리 종목코드로 다시 검색해 주세요. '
                      '(이 화면은 시가총액 상위 200종목만 담고 있습니다.)',
        price_label='최신 현재가',
        caption='검색해서 종목을 고르면, 그 종목의 **날짜별 이력**(하루 한 줄)을 표로 내보냅니다. '
                '항목은 카드에 보이는 재무 지표(PER·PBR·ROE·배당·목표주가·퀀트 스코어 등)이고 '
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
            f'**전체 검색/필터 결과:** `{total_items}`개 종목 (총 {len(all_stocks)}개 국내(코스피+코스닥) 종목 중)'
        )
        ui.separator()

        if not filtered_stocks:
            warning_banner('선택한 필터 조건에 일치하는 종목이 없습니다.')
            return

        start_idx = (current_page - 1) * ITEMS_PER_PAGE
        page_stocks = filtered_stocks[start_idx:start_idx + ITEMS_PER_PAGE]

        for offset, s in enumerate(page_stocks):
            rank_num = s.get("rank", start_idx + offset + 1)
            # 진짜 카드를 그릴 수 없는 경우(price 없음 / 상장주식수 파싱 오류)만 전체 차단하고,
            # 나머지는 Trailing 을 정상 노출하고 Forward 자리에만 사유별 마스크를 띄웁니다
            # (ENGINEERING_SPEC.md §0-1 예시2-보충2).
            reject_reason = s.get('reject_reason', '')
            hard_block = (not s.get('is_valid', True)) and (
                '필수 지표 수집 실패' in reject_reason or '상장주식수 파싱 오류' in reject_reason
            )
            markup = build_blocked_card_html(s, rank_num) if hard_block \
                else build_stock_card_html(s, rank_num, admin)
            ui.html(markup).classes('w-full')
            if offset == 9:
                # 📢 카드 목록 중간에 작은 배너 광고 한 번 (오너 요청 2026-08-25).
                #    카드마다 부르지 않고 페이지당 딱 한 번만 — web/ads.py 의 ad_infeed() 참고.
                ads.ad_infeed()

        ui.separator()
        ui.markdown('##### 📄 페이지 선택 (한 화면에 20개 종목 카드 노출)')

        def _on_page(page: int) -> None:
            view['page'] = page
            _results.refresh()

        # 페이지 이동 시 최상단 스크롤은 pager() 안에서 처리합니다 (완료기준 ④).
        pager(total_pages, current_page, _on_page)

    _results()
    disclaimer_footer()


# =============================================================================
# 4. 정적 블록 (제목 · 경고문 · 가이드 · 푸터)
# =============================================================================
# ⚠️ 아래 두 조각은 **f-string 이 아닙니다.** 사이에 들어가는 "📘 학습용 보조 도구 안내" 문구는
#    us_stocks 화면과 글자 하나까지 같아서 `web/components` 에 단일 출처로 두고 여기서는 이어
#    붙이기만 합니다(§0-3-10). f-string 을 쓰지 않는 이유는 #129(중괄호 이스케이프 사고) 재발 방지.
_TITLE_HEAD = """
<div style="text-align: center; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
    <h1 style="font-size: 36px; font-weight: 800; color: #d97706; margin: 0 0 6px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
    <div style="background: linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%); border: 2px solid #ef4444; border-radius: 12px; padding: 12px 22px; margin: 10px auto 14px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(239, 68, 68, 0.35);">
        <div style="font-size: 15px; font-weight: 800; color: #fca5a5; letter-spacing: -0.3px;">
            🚨 [투자 주의 경고 및 AI 분석 안내]
        </div>
        <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
            본 리포트의 수치 및 분석 결과는 <b>공시된 재무제표와 시장 데이터를 기반으로 AI 퀀트 알고리즘이 자동 계산한 단순 참고용 정보</b>입니다.<br>
            특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
        </div>
        <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
            ⚠️ 모든 투자 결정과 그에 따른 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있음을 명시합니다.
        </div>
    </div>
"""

_TITLE_TAIL = """
    <div style="font-size: 15.5px; color: #64748b; font-weight: 600; margin-top: 6px;">코스피+코스닥 통합 시가총액 상위 500개 종목 Trailing vs Forward PEGY &amp; 퀀트 종합점수 리포트<br><span style="font-size: 13px; color: #475569;">(만점은 종목마다 다릅니다 — 수집하지 못한 지표는 점수를 지어내지 않고 배점에서 제외하므로, 각 카드에 '획득점수 / 그 종목의 만점 (달성률%)'로 표기됩니다)</span></div>
</div>
"""


def _render_title() -> None:
    ui.html(compact(_TITLE_HEAD + LEARNING_NOTICE_HTML + _TITLE_TAIL)).classes('w-full')


async def _render_market_snapshot() -> None:
    """코스피 지수 / 원·달러 환율 요약 카드. 못 읽으면 아무것도 그리지 않습니다(§0-1).

    🔴 2026-08-21 — `async def` 로 바뀌었습니다. CSV 를 읽는 한 줄만 별도 스레드로 넘기고
       (`web/blocking.py`), 카드를 그리는 나머지는 예전 그대로입니다.
    """
    try:
        snapshot = await run_blocking(load_latest_kospi_usd)
    except Exception as exc:                       # noqa: BLE001 — 취소(BlockingCallAborted) 등
        # `load_latest_kospi_usd()` 는 실패해도 None 을 돌려주므로 여기 오는 건 사실상
        # "요청 중단"뿐입니다. 원래 실패 정책(카드를 아예 그리지 않음)을 그대로 따릅니다.
        print(f'⚠️ 코스피/환율 요약 로드 중단: {type(exc).__name__}: {exc}')
        return
    if not snapshot:
        return
    date_label = f" ({esc(snapshot['date'])} 장마감 기준)" if snapshot.get('date') else ""
    ui.html(compact(f"""
        <div style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; max-width: 860px; margin-left: auto; margin-right: auto;">
            <div style="flex: 1 1 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
                <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">📈 코스피 지수{date_label}</div>
                <div style="font-size: 34px; color: #4ade80; font-weight: 800; letter-spacing: -1px; margin-top: 4px;">{snapshot['kospi']:,.0f}</div>
            </div>
            <div style="flex: 1 1 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
                <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">💵 원/달러 환율{date_label}</div>
                <div style="font-size: 34px; color: #4ade80; font-weight: 800; letter-spacing: -1px; margin-top: 4px;">{snapshot['usd']:,.0f}<span style="font-size: 20px; font-weight: 700;">원</span></div>
            </div>
        </div>
    """)).classes('w-full')


def _render_raw_downloads(admin: bool) -> None:
    """원본(raw) 스냅샷 / 누적 요약 이력 다운로드 (§0-3-3 — raw 도 사용자가 받을 수 있어야 함)."""
    latest_path = data_path(SNAPSHOT_FILENAME)
    history_path = data_path(SUMMARY_HISTORY_FILENAME)

    with ui.row().classes('w-full gap-3 items-center'):
        if os.path.exists(latest_path):
            download_button(
                '📥 시가총액 상위 200 최신 스냅샷 다운로드 (JSON)',
                f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.json",
                lambda: read_download_bytes(latest_path),
                media_type='application/json',
            )
            if admin:
                download_button(
                    '📊 [관리자] 최신 스냅샷 다운로드 (Excel)',
                    f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.csv",
                    lambda: _snapshot_csv_bytes(latest_path),
                    media_type='text/csv',
                    failure_text='[관리자] 스냅샷을 CSV로 변환하지 못했습니다.',
                )
        if os.path.exists(history_path):
            download_button(
                '📥 누적 요약 히스토리 다운로드 (JSON)',
                f"pegy_summary_history_{datetime.now().strftime('%Y%m%d')}.json",
                lambda: read_download_bytes(history_path),
                media_type='application/json',
            )
            if admin:
                download_button(
                    '📊 [관리자] 히스토리 다운로드 (Excel)',
                    f"pegy_summary_history_{datetime.now().strftime('%Y%m%d')}.csv",
                    lambda: pd.read_json(history_path).to_csv(index=False).encode('utf-8-sig'),
                    media_type='text/csv',
                    failure_text='[관리자] 히스토리를 CSV로 변환하지 못했습니다.',
                )


def _snapshot_csv_bytes(latest_path: str):
    """관리자용 스냅샷 CSV (기존 로직 그대로 — DataFrame → utf-8-sig).

    ⚠️ 여기만 **동기판** `load_json_file()` 을 씁니다. 이 함수는 화면을 그릴 때가 아니라
       다운로드 버튼을 눌렀을 때 `web/components/widgets.download_button()` 이
       `run.io_bound` 로 **이미 별도 스레드에서** 돌려 주기 때문입니다. 여기서 또
       `await` 를 걸 필요가 없고(걸 수도 없고), 이벤트 루프도 막지 않습니다.
    """
    payload, _error = load_json_file(latest_path)
    if payload is None:
        return None
    return pd.DataFrame(payload.get("stocks", [])).to_csv(index=False).encode('utf-8-sig')


def _render_guide_box() -> None:
    ui.html(compact("""
        <div style="background-color: #0f172a; border: 1px solid #0284c7; border-radius: 12px; padding: 16px 22px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 15px; font-weight: 800; color: #38bdf8; margin-bottom: 10px;">
                💡 '착시 저평가 (가치주 덫)' 및 퀀트 스코어 가이드
            </div>
            <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65; margin-bottom: 8px;">
                • <b style="color: #fef08a;">🏆 퀀트 스코어 (quant_score)</b>: PEGY(35점) + Forward ROE(15점) + ROIC(15점) + 주주환원(20점) + Trailing(10점) + 변동성(5점) = 이론상 100점 만점입니다.<br>
                다만 <b>수집하지 못한 지표는 점수를 지어내지 않고 배점에서 통째로 제외</b>하므로 실제 만점은 종목마다 다릅니다.
                (현재 ROIC는 원천 데이터를 수집하지 않아 항상 제외되어 대부분 85점 이하가 만점이고, 애널리스트 컨센서스가 없으면 PEGY 35점도 빠집니다.)<br>
                (단, 현재가가 목표가를 초과했거나 PEGY &ge; 2.0 시 <b>목표가 달성 적정가/고평가 교차검증</b> 적용)
            </div>
            <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65;">
                • <b style="color: #fca5a5;">⚠️ 착시 저평가</b>: 주가가 단순히 PER 5배~7배로 싸 보이지만<br>
                실제 이익창출력(<b>Trailing ROE &lt; 8%</b>)이 턱없이 낮아 주가가 바닥에 갇히는 위험 종목에 ⚠️ 태그를 부여합니다.<br>
                <span style="color: #94a3b8; font-size: 12.5px;">※ ROIC(&lt;6%) 기준은 원천 데이터(영업이익÷투하자본)를 아직 수집하지 않아 판정에 사용되지 않습니다 — 현재는 ROE 기준 단독 판정입니다.</span>
            </div>
        </div>
    """)).classes('w-full')
