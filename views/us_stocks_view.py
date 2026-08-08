"""
views/us_stocks_view.py
🇺🇸 "미국 주식은 이가격" — 미국(나스닥+뉴욕) 시가총액 상위 550종목 밸류에이션 화면

✅ 2026-08-08 공개 전환 완료 (ENGINEERING_SPEC §0-3-6 스테이징 절차 종료).
   오너 승인으로 `visiblehand.py` 사이드바 상단의 **공개 메뉴**에서 누구나 진입할 수 있습니다.
   (승인 전제조건이던 임계값 재캘리브레이션 = `utils/constants_us.py` §5 전 항목 확정,
    수집 자동화 = `.github/workflows/scrape_us.yml` 무인 실행 — 둘 다 2026-08-07 완료)

⚠️ 기존 코스피 화면(`views/pegy_view.py`)은 한 줄도 수정하지 않았습니다. 카드 레이아웃 구조는
   오너 확정(§8-7-5)에 따라 코스피와 동일하게 맞추되, 코스피 전용 요소(원화 표기, 네이버 문구,
   그레이엄 넘버 금융주 경고 문구 등)는 미국 데이터에 맞게 바꿨습니다.

오너 확정 사항 반영
   - 통화: USD 단독 표기 (원화 환산·병기 없음, §8-5)
   - 상단 지수: S&P500 / 나스닥종합 / 다우존스 3개, 2x2 그리드 강제 없이 가독성 우선 배치 (§8-7-3)
   - 종목명: 한글명(정식 또는 자동 음역) + 영문명 + 티커 동시 표기 (§8-7-4)
   - 페이지네이션: 30개씩 (코스피는 20개 — 다름에 주의)

이 화면은 **읽기 전용**입니다. 어떤 값도 여기서 계산·보정하지 않고, 수집기가 저장한
스냅샷(data/us_stocks_latest.json)을 그대로 표시합니다(§6 표현 계층 분리).
"""

import os
import json
from datetime import datetime

import streamlit as st

from utils.constants_us import US_PAGE_SIZE, US_SNAPSHOT_FILENAME, US_SUMMARY_HISTORY_FILENAME

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# =============================================================================
# 0. 로드 / 포맷 헬퍼 — 값이 없으면 절대 그럴듯한 숫자를 만들지 않습니다(§0-1)
# =============================================================================
def load_us_snapshot():
    """data/us_stocks_latest.json 로드. 실패 시 상태를 그대로 반환(현재 시각으로 위장 금지)."""
    path = os.path.join(_DATA_DIR, US_SNAPSHOT_FILENAME)
    if not os.path.exists(path):
        return {
            "status": "LOAD_FAILED",
            "load_error": f"스냅샷 파일({os.path.join('data', US_SNAPSHOT_FILENAME)})이 없습니다. "
                          "아직 전수 수집(`python collector_us_stocks.py collect`)을 한 번도 실행하지 않았을 수 있습니다.",
        }, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        meta = dict(payload.get("metadata", {}))
        stocks = payload.get("stocks", [])
        if not stocks:
            meta["status"] = meta.get("status") or "EMPTY"
            meta["load_error"] = "스냅샷에 종목 데이터가 0건입니다."
        return meta, stocks
    except Exception as e:
        print(f"[us_stocks_view] 스냅샷 로드 실패: {e}")
        return {"status": "LOAD_FAILED", "load_error": f"스냅샷 파일을 읽지 못했습니다: {e}"}, []


def load_us_summary_history():
    path = os.path.join(_DATA_DIR, US_SUMMARY_HISTORY_FILENAME)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[us_stocks_view] 요약 이력 로드 실패: {e}")
        return []


NA_TEXT = "데이터 없음"


def fmt_num(value, suffix="", digits=None, na_text=NA_TEXT):
    """None/결측을 그럴듯한 숫자로 바꾸지 않고 '데이터 없음'으로 표기합니다."""
    if value is None:
        return na_text
    try:
        if isinstance(value, str):
            return f"{value}{suffix}"
        if digits is None:
            return f"{value:,}{suffix}"
        return f"{value:,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return na_text


def fmt_usd(value, digits=2, na_text=NA_TEXT):
    """USD 단독 표기 (원화 환산 없음 — 오너 확정 §8-5)."""
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


def _clean_html(html):
    return "\n".join([line.strip() for line in html.split("\n") if line.strip()])


# =============================================================================
# 1. 상단 지수 3종 (2x2 그리드 강제 없음 — 가독성 우선 자유 배치, 오너 확정 §8-7-3)
# =============================================================================
def render_index_header(indices):
    """
    2026-08-07 수정(오너 확정): 지수 절대값은 표시하지 않습니다 — ETF 프록시(SPY/ONEQ/DIA)의
    주가는 실제 지수 포인트값(예: S&P500 ≈6,598)과 숫자가 다른 별개 값이라, 그대로 보여주면
    지수 포인트인 것처럼 오해될 수 있습니다(§0-1). 대신 **당일 등락률(%)만** 표시하고,
    ETF 프록시 기준임을 라벨로 명시합니다.
    """
    if not indices:
        return
    cards = []
    for key in ("sp500", "nasdaq", "dow"):
        idx = indices.get(key)
        if not idx:
            continue
        change = idx.get("intraday_change_pct")
        if change is None:
            # 실패했으면 지어내지 않고 사유를 그대로 노출합니다(§0-1).
            value_html = (
                '<div style="font-size: 20px; color: #94a3b8; font-weight: 800; margin-top: 6px;">데이터 없음</div>'
                f'<div style="font-size: 11px; color: #f87171; font-weight: 600; margin-top: 2px;">'
                f'수집 실패: {idx.get("error") or "원인 미상"}</div>'
            )
        else:
            color = "#4ade80" if change >= 0 else "#f87171"
            arrow = "▲" if change >= 0 else "▼"
            value_html = (
                f'<div style="font-size: 30px; color: {color}; font-weight: 800; letter-spacing: -1px; '
                f'margin-top: 4px;">{arrow} {abs(change):.2f}%</div>'
            )
        date_label = f' ({idx.get("session_date")} 장마감 기준)' if idx.get("session_date") else ""
        proxy_symbol = idx.get("proxy_symbol") or ""
        cards.append(
            f"""
            <div style="flex: 1 1 260px; background: linear-gradient(135deg, #1e293b, #0f172a);
                        border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
                <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">
                    📈 {idx['label_ko']} <span style="color:#64748b; font-weight:600;">{idx['label_en']}</span>{date_label}
                </div>
                {value_html}
                <div style="font-size: 10.5px; color: #64748b; font-weight: 600; margin-top: 4px;">
                    ETF({proxy_symbol}) 등락률 기준 — 실제 지수 포인트값이 아닌 근사치입니다
                </div>
            </div>
            """
        )
    if not cards:
        return
    st.markdown(
        _clean_html(
            '<div style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap;">'
            + "".join(cards) + "</div>"
        ),
        unsafe_allow_html=True,
    )


# =============================================================================
# 2. 종목 카드 1장
# =============================================================================
def _render_stock_card(s, rank_fallback, is_admin=False):
    rank_num = s.get("rank", rank_fallback)
    rank_prefix_html = (
        f'<span style="font-size: 32px; font-weight: 900; color: #38bdf8; letter-spacing: -1px; '
        f'margin-right: 4px; line-height: 1;">{rank_num}.</span>'
    )

    # 이름 표기: 한글명(있으면) + 영문명 + 티커 (오너 확정 §8-7-4)
    name_kr = s.get("name_kr")
    name_en = s.get("name_en_clean") or s.get("name") or ""
    symbol = s.get("symbol", "")
    if name_kr:
        name_main = name_kr
        translit_badge = ""
        if s.get("name_kr_is_transliterated"):
            translit_badge = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #a5b4fc; '
                'background-color: #312e81; border: 1px solid #818cf8; border-radius: 6px; padding: 1px 6px; '
                'vertical-align: middle;">음역<span class="q-tooltiptext">한국에서 널리 쓰이는 정식 한글명이 '
                '없어, 영문 사명을 <b>발음대로 자동 음역</b>한 표기입니다(번역이 아닙니다).<br>'
                '규칙 기반 자동 변환이라 실제 통용 표기와 다를 수 있습니다 — 정확한 이름은 옆의 영문명과 '
                '티커를 확인해 주세요.</span></span>'
            )
    else:
        name_main = name_en or symbol
        translit_badge = ""

    name_html = (
        f'<span style="font-size: 24px; font-weight: 800; color: #f8fafc; white-space: nowrap;">{name_main}</span>'
        f'{translit_badge}'
        f'<span style="font-size: 13px; color: #94a3b8; font-weight: 600;">{name_en}</span>'
        f'<span style="font-size: 14px; color: #38bdf8; font-weight: 800; background-color: rgba(15,23,42,0.6); '
        f'padding: 2px 9px; border-radius: 6px; border: 1px solid #334155;">{symbol}</span>'
    )

    reject_reason = s.get("reject_reason", "")
    unverified_reason = s.get("unverified_reason", "")
    price = s.get("price")

    # ── 하드 블록: 카드 자체를 그릴 수 없는 경우 (장마감 종가 없음 / 발행주식수 오염)
    hard_block = (not s.get("is_valid", True)) and (
        "장마감 종가" in reject_reason or "발행주식수" in reject_reason
    )
    if hard_block:
        html = f"""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 2px dashed #64748b;
                    border-radius: 14px; padding: 22px 26px; margin-bottom: 24px;
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155;
                        padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    {rank_prefix_html}{name_html}
                    <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700;
                                 padding: 4px 12px; border-radius: 12px; border: 1px solid #64748b;">⚪ 데이터 없음 (측정 불가)</span>
                </div>
            </div>
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px;
                        padding: 18px 24px; text-align: center;">
                <h3 style="color: #cbd5e1; font-size: 16.5px; font-weight: 800; margin: 0 0 6px 0;">
                    🚫 필수 데이터를 수집하지 못해 밸류에이션을 산출하지 않았습니다</h3>
                <p style="color: #94a3b8; font-size: 13.5px; font-weight: 600; margin: 0; line-height: 1.5;">
                    수집 실패 사유: <b>{reject_reason or unverified_reason or '원인 미상'}</b></p>
                <div style="color: #cbd5e1; font-size: 12px; margin-top: 6px;">
                    📌 값을 추정해 채우지 않고 '데이터 없음'으로 남깁니다. 다음 수집에서 정상화되면 자동 복구됩니다.</div>
            </div>
        </div>
        """
        st.markdown(_clean_html(html), unsafe_allow_html=True)
        return

    t_roe = s.get("t_roe")
    roic = s.get("roic")
    roa = s.get("roa")
    beta = s.get("beta")
    roe_color = "#94a3b8" if t_roe is None else ("#f43f5e" if t_roe < 9.0 else "#4ade80")
    roic_color = "#94a3b8" if roic is None else ("#f43f5e" if roic < 8.0 else "#38bdf8")

    # 베타 배지 (코스피 화면의 '변동성' 배지 자리)
    if beta is None:
        beta_text, beta_color = "❔ 베타 데이터 없음", "#94a3b8"
    elif beta >= 1.5:
        beta_text, beta_color = f"⚡ 고변동 (베타 {beta:.2f})", "#f43f5e"
    elif beta >= 1.0:
        beta_text, beta_color = f"🟡 시장 수준 (베타 {beta:.2f})", "#fde047"
    else:
        beta_text, beta_color = f"🟢 저변동 (베타 {beta:.2f})", "#38bdf8"

    # 착시 저평가 배지
    if s.get("value_trap"):
        trap_badge_html = (
            '<span style="background-color: #7f1d1d; color: #fca5a5; font-size: 12px; font-weight: 700; '
            'padding: 4px 10px; border-radius: 8px; border: 1px solid #f87171; white-space: nowrap;">'
            '⚠️ 이익창출력 저하 (착시 저평가 주의)</span>'
        )
    elif t_roe is None and roic is None:
        trap_badge_html = (
            '<span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; '
            'padding: 4px 10px; border-radius: 8px; border: 1px solid #64748b; white-space: nowrap;">'
            '❔ 자본효율성 판정 불가 (데이터 없음)</span>'
        )
    else:
        trap_badge_html = (
            '<span style="background-color: #14532d; color: #86efac; font-size: 12px; font-weight: 700; '
            'padding: 4px 10px; border-radius: 8px; border: 1px solid #4ade80; white-space: nowrap;">'
            '✨ 우량 자본효율성 (Quality OK)</span>'
        )

    # 리츠/업종 배지
    sector_badge_html = ""
    if s.get("is_reit"):
        sector_badge_html = (
            '<span class="q-tooltip" style="background-color: #1e3a5f; color: #93c5fd; font-size: 11.5px; '
            'font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #3b82f6;">'
            '🏢 리츠(REIT)<span class="q-tooltiptext">부동산 투자 신탁입니다. 감가상각 때문에 순이익 기반 PER이 '
            '의미가 약해서, 데이터 소스도 PER 대신 <b>Price/FFO</b>(운영자금 대비 주가)를 제공합니다.</span></span>'
        )

    # 계산값 배지들 (§0-1 예시2-보충: 실측값과 반드시 구분 표기)
    calc_price_tag = (
        ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
        'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
        'vertical-align: middle;">🧮 계산값<span class="q-tooltiptext">장마감 종가 블록을 직접 읽지 못해 '
        '<b>시가총액 ÷ 발행주식수</b>로 역산한 값입니다 (실측 종가 아님).</span></span>'
        if s.get("price_calculated") else ""
    )
    calc_feps_tag = (
        ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
        'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
        'vertical-align: middle;">🧮 계산값<span class="q-tooltiptext">데이터 소스가 Forward EPS를 직접 주지 않아 '
        '<b>장마감 종가 ÷ Forward PER(애널리스트 컨센서스)</b>로 역산한 값입니다.<br>'
        '두 입력 모두 실측값이고 순수 나눗셈이라 계산했지만, 실측 EPS는 아닙니다.</span></span>'
        if s.get("f_eps_calculated") else ""
    )

    growth_capped_badge_html = ""
    if s.get("growth_score_capped"):
        growth_capped_badge_html = (
            ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
            'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
            'vertical-align: middle;">⚠️ 고성장 추정 보수반영<span class="q-tooltiptext">예상 성장률이 100%를 '
            '넘어 기저효과(일시적 실적 급변) 왜곡 가능성을 의심해, 퀀트 스코어의 PEGY 항목 점수만 보수적으로 '
            '깎았습니다.<br>목표가·적정가 갭은 원래 성장률 그대로 계산되어 있습니다(값 자체는 건드리지 않음).</span></span>'
        )

    geff_capped_badge_html = ""
    if s.get("g_eff_capped"):
        geff_capped_badge_html = (
            ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
            'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
            'vertical-align: middle;">🧮 상한 적용값<span class="q-tooltiptext">실효성장률이 상한(성장률 35%p / '
            f'주주환원 10%p / 합계 40%p)에 걸려 절단된 값입니다.<br>캡 미적용 원값: '
            f'{fmt_num(s.get("g_eff_uncapped"), "%p", 2)}</span></span>'
        )

    # 퀀트 스코어 배지
    q_score = s.get("quant_score")
    q_max = s.get("score_max")
    excluded_items = s.get("score_excluded_items") or []
    if q_score is None:
        score_badge_html = "<b>측정 불가</b> (데이터 없음)"
        score_tooltip_extra = "필수 지표를 수집하지 못해 점수를 산출하지 않았습니다."
    else:
        if not q_max:
            score_badge_html = f"<b>{q_score}점</b> / 만점 산출 불가 (채점 가능 항목 없음)"
        else:
            pct = round(q_score / q_max * 100)
            pct_color = "#4ade80" if pct >= 60 else ("#fde047" if pct >= 30 else "#fca5a5")
            score_badge_html = (
                f"<b>{q_score}점</b> / {q_max}점 "
                f"<span style='color:{pct_color}; font-weight:900;'>({pct}%)</span>"
            )
        score_tooltip_extra = (
            f"※ 배점 제외 항목: {', '.join(excluded_items)}" if excluded_items
            else "모든 항목이 배점에 반영되었습니다."
        )

    # ── Forward 섹션 마스킹 사유 판정 (우선순위: 검증실패 > PER극단 > 역성장 > g_eff결측 > Forward결측)
    was_blocked = (not s.get("is_valid", True)) or s.get("is_unverified", False)
    is_per_extreme = bool(s.get("forward_per_extreme"))
    g_eff = s.get("g_eff")
    is_negative_growth = g_eff is not None and g_eff <= 0
    is_geff_missing = (g_eff is None) and not s.get("forward_data_missing")
    forward_needs_mask = bool(
        was_blocked or is_per_extreme or is_negative_growth or is_geff_missing
        or s.get("forward_data_missing") or s.get("f_pegy") is None
    )

    # ── 그레이엄 넘버 박스 (Forward 가 마스킹될 때만 참고용으로 노출 — 코스피와 동일 규칙)
    graham_box_html = ""
    if forward_needs_mask:
        graham_target = s.get("graham_target")
        if s.get("is_trailing_loss"):
            loss_reason = ", ".join(s.get("loss_evidence") or []) or "적자 판정"
            graham_box_html = f"""
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px dashed #475569; border-radius: 10px;
                        padding: 14px 20px; text-align: center; margin-bottom: 14px;">
                <div style="color: #94a3b8; font-size: 12.5px; font-weight: 700;">
                    🧮 그레이엄 넘버 산출 불가 — 적자 기업 (EPS가 0 이하라 제곱근 안이 음수가 됩니다)</div>
                <div style="color: #64748b; font-size: 11.5px; font-weight: 600; margin-top: 4px;">
                    판정 근거: {loss_reason}</div>
            </div>
            """
        elif graham_target is not None and s.get("graham_is_financial_sector"):
            graham_box_html = f"""
            <div style="background-color: rgba(127, 29, 29, 0.35); border: 2px solid #f87171; border-radius: 10px;
                        padding: 16px 20px; margin-bottom: 14px;">
                <div style="color: #fca5a5; font-size: 13px; font-weight: 800; margin-bottom: 6px;">
                    ⚠️⚠️ 강한 경고: 금융업종 — 그레이엄 넘버 적용 부적합 가능성 높음</div>
                <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">🧮 {fmt_usd(graham_target)}
                    <span style="font-size: 12px; color: #fca5a5; font-weight: 700;">(Trailing 전용 참고 목표가)</span></div>
                <p style="color: #fecaca; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
                    은행/보험/자산운용 등은 장부가(BPS)의 의미가 제조업과 달라, 이 공식(√22.5×EPS×BPS)의 전제가 잘 맞지 않습니다.<br>
                    참고 수준으로만 활용하고, 이 숫자를 실제 목표주가로 신뢰하지 마세요.</p>
            </div>
            """
        elif graham_target is not None:
            graham_box_html = f"""
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #475569; border-radius: 10px;
                        padding: 16px 20px; margin-bottom: 14px;">
                <div style="color: #94a3b8; font-size: 13px; font-weight: 700; margin-bottom: 6px;">
                    🧮 Trailing 전용 참고 목표가 (Graham Number)</div>
                <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">{fmt_usd(graham_target)}</div>
                <p style="color: #94a3b8; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
                    성장률 예측 없이 √(22.5 × Trailing EPS × BPS) 공식(벤저민 그레이엄)으로만 산출한 참고값입니다.<br>
                    고성장 기업에는 보수적으로(낮게) 나올 수 있으니 유일한 판단 근거로 쓰지 마세요.</p>
            </div>
            """

    # ── 목표가 갭
    f_target = s.get("f_target")
    if price and f_target and s.get("f_target_capped"):
        cap_reason = s.get("f_target_cap_reason") or "현재가 배수 상한에 도달"
        uncapped = s.get("f_target_uncapped")
        uncapped_txt = f"캡을 적용하지 않은 산출값은 {fmt_usd(uncapped)} 입니다.<br>" if uncapped else ""
        gap_str, gap_color, bar_color, bar_width = "상승여력 산출 안 함 (상한 캡 적용)", "#fbbf24", "#78716c", 100
        target_cap_badge_html = (
            ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
            'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
            'vertical-align: middle;">🧮 상한 적용값<span class="q-tooltiptext">이 목표가는 계산 결과가 아니라 '
            f'<b>상한(캡) 값</b>입니다.<br>{cap_reason}.<br>{uncapped_txt}'
            '고성장 종목은 PEGY 공식상 목표가가 발산하기 때문에 폭주 방지 상한을 두고 있습니다.</span></span>'
        )
    elif price and f_target:
        gap_pct = ((f_target - price) / price) * 100.0
        gap_str = f"+{gap_pct:.1f}% 상승 여력" if gap_pct >= 0 else f"{abs(gap_pct):.1f}% 프리미엄"
        gap_color = "#4ade80" if gap_pct >= 0 else "#fca5a5"
        bar_color = "#22c55e" if gap_pct >= 0 else "#ef4444"
        bar_width = min(abs(gap_pct), 100)
        if s.get("f_target_floored"):
            target_cap_badge_html = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #7dd3fc; '
                'background-color: #1e3a5f; border: 1px solid #38bdf8; border-radius: 6px; padding: 1px 6px; '
                'vertical-align: middle;">🛡️ 장부가 바닥값<span class="q-tooltiptext">PEGY 역산값이 장부가(BPS)보다 '
                '낮게 나와 BPS를 대신 사용했습니다. 자세한 내용은 위 안내 참고.</span></span>'
            )
        else:
            target_cap_badge_html = ""
    else:
        gap_str, gap_color, bar_color, bar_width, target_cap_badge_html = "측정불가", "#94a3b8", "#64748b", 0, ""

    # ── 목표가 바닥값(장부가/BPS) 적용 배너 — 눈에 크게 띄도록 별도 배너로 표시.
    # PEGY 역산 공식이 저성장 자본집약형(보험/지주/유틸리티 등) 우량주에서 목표가를
    # 구조적으로 낮게 계산하는 문제의 보정. ROE·ROIC 우량 게이트를 통과한 종목에만 적용됩니다.
    floor_banner_html = ""
    if s.get("f_target_floored"):
        floor_banner_html = f"""
        <div style="background: linear-gradient(135deg, rgba(30, 58, 95, 0.55) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px solid #38bdf8; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px;
                    display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 22px;">🛡️</span>
            <div>
                <div style="color: #7dd3fc; font-size: 13.5px; font-weight: 800;">
                    장부가(BPS) 기준 바닥값 적용됨</div>
                <div style="color: #cbd5e1; font-size: 12px; font-weight: 500; line-height: 1.5; margin-top: 3px;">
                    PEGY 역산 공식은 성장률이 낮으면 목표가도 함께 낮아지는 구조라, 보험·지주·유틸리티처럼
                    실적 성장보다 자본배분·자산가치로 평가받는 저성장 우량주는 목표가가 비정상적으로 낮게
                    나옵니다. ROE·ROIC가 기준선 이상인 우량 종목에 한해 장부가(BPS)를 참고 하한으로 대신
                    사용했습니다. ⚠️ 재고·무형자산 손상, 부채 시가평가까지 반영한 진짜 청산가치 실사는
                    아니므로 참고용으로만 봐주세요.</div>
            </div>
        </div>
        """

    # 애널리스트 목표가(소스 실측) — 우리 모델 목표가와 별개로 항상 노출
    analyst_target = s.get("analyst_target")
    analyst_consensus = s.get("analyst_consensus")
    analyst_count = s.get("analyst_count")
    if analyst_target and price:
        a_gap = (analyst_target - price) / price * 100.0
        analyst_gap_txt = f"<span style='color:{'#4ade80' if a_gap >= 0 else '#fca5a5'}; font-weight:800;'>{a_gap:+.1f}%</span>"
    else:
        analyst_gap_txt = f"<span style='color:#94a3b8;'>{NA_TEXT}</span>"
    analyst_html = f"""
    <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px;
                padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; gap: 22px; flex-wrap: wrap;">
        <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">
            <span class="q-tooltip">🎯 애널리스트 컨센서스 (실측) ℹ️<span class="q-tooltiptext"><b>데이터 소스가 제공하는
            애널리스트 목표주가·투자의견 원본값</b>입니다.<br>아래 Forward 카드의 '목표가'는 우리 PEGY 모델이 계산한
            값이라 서로 다를 수 있습니다 — 둘을 나란히 보여주는 이유입니다(어느 쪽도 정답이 아님).</span></span>:
        </span>
        <span style="font-size: 13px; color: #e2e8f0;">목표주가
            <b style="color:#14b8a6; font-size:14px; margin-left:4px;">{fmt_usd(analyst_target)}</b>
            <span style="margin-left:6px;">({analyst_gap_txt})</span></span>
        <span style="font-size: 13px; color: #e2e8f0;">투자의견
            <b style="color:#38bdf8; font-size:14px; margin-left:4px;">{analyst_consensus or NA_TEXT}</b></span>
        <span style="font-size: 13px; color: #e2e8f0;">커버 애널리스트
            <b style="color:#cbd5e1; font-size:14px; margin-left:4px;">{fmt_num(analyst_count, '명')}</b></span>
    </div>
    """

    # ── Forward 섹션
    if s.get("dividend_data_unverified") and not s.get("forward_data_missing") and not is_negative_growth:
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(120, 53, 15, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px dashed #facc15; border-radius: 12px; padding: 16px 22px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #92400e;
                        padding-bottom: 8px; margin-bottom: 14px;">
                <div><div style="font-size: 16px; font-weight: 800; color: #fbbf24; line-height: 1.2;">🚀 Forward</div>
                     <div style="font-size: 13px; font-weight: 600; color: #fde047; margin-top: 2px;">(미래 추정 밸류 분석)</div></div>
                <span style="font-size: 11.5px; color: #fde047; font-weight: 500;">🛡️ 주주환원 데이터 확인 필요</span>
            </div>
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #92400e; border-radius: 10px;
                        padding: 26px 24px; text-align: center;">
                <div style="font-size: 30px; margin-bottom: 8px;">🛡️</div>
                <h4 style="color: #fbbf24; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">주주환원 데이터 검증 대기 중</h4>
                <p style="color: #fef08a; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                    {s.get('dividend_unverified_reason', '배당·자사주 수익률을 수집하지 못했습니다.')}<br>
                    위 <b>Trailing(과거 실적)</b> 지표는 수집된 값 그대로 정상 반영되어 있으니 참고해 주세요.</p>
            </div>
        </div>
        """
    elif is_negative_growth:
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(59, 7, 100, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px dashed #a855f7; border-radius: 12px; padding: 16px 22px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #6d28d9;
                        padding-bottom: 8px; margin-bottom: 14px;">
                <div><div style="font-size: 16px; font-weight: 800; color: #d8b4fe; line-height: 1.2;">🚀 Forward</div>
                     <div style="font-size: 13px; font-weight: 600; color: #c4b5fd; margin-top: 2px;">(미래 추정 밸류 분석)</div></div>
                <span style="font-size: 11.5px; color: #c4b5fd; font-weight: 500;">📉 역성장 · 무성장</span>
            </div>
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #6d28d9; border-radius: 10px;
                        padding: 26px 24px; text-align: center;">
                <div style="font-size: 30px; margin-bottom: 8px;">📉</div>
                <h4 style="color: #d8b4fe; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">
                    실효성장률(g_eff) 0% 이하 — 가치 훼손 구간</h4>
                <p style="color: #e9d5ff; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                    3년 EPS 성장 전망 <b>{fmt_num(s.get('growth'), '%', 2)}</b> + 주주환원율
                    <b>{fmt_num(s.get('sh_return'), '%', 2)}</b> = 실효성장률
                    <b>{fmt_num(g_eff, '%p', 2)}</b> 로 0 이하라, 성장을 전제로 하는 PEGY 밸류에이션 적용이 부적합합니다.<br>
                    위 <b>Trailing(과거 실적)</b> 지표는 참고하실 수 있습니다.</p>
            </div>
        </div>
        """
    elif is_per_extreme:
        forward_section_html = """
        <div style="background: linear-gradient(135deg, rgba(69, 10, 10, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px dashed #f87171; border-radius: 12px; padding: 16px 22px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #991b1b;
                        padding-bottom: 8px; margin-bottom: 14px;">
                <div><div style="font-size: 16px; font-weight: 800; color: #fca5a5; line-height: 1.2;">🚀 Forward</div>
                     <div style="font-size: 13px; font-weight: 600; color: #fecaca; margin-top: 2px;">(미래 추정 밸류 분석)</div></div>
                <span style="font-size: 11.5px; color: #fecaca; font-weight: 500;">🚫 PER 극단치</span>
            </div>
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #991b1b; border-radius: 10px;
                        padding: 26px 24px; text-align: center;">
                <div style="font-size: 30px; margin-bottom: 8px;">🚫</div>
                <h4 style="color: #fca5a5; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">Forward PER 산출 범위 초과</h4>
                <p style="color: #fecaca; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                    애널리스트 컨센서스 기반 Forward PER이 정상 범위를 크게 벗어나 신뢰할 수 없습니다.<br>
                    위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요.</p>
            </div>
        </div>
        """
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
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(51, 65, 85, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px dashed #64748b; border-radius: 12px; padding: 16px 22px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #334155;
                        padding-bottom: 8px; margin-bottom: 14px;">
                <div><div style="font-size: 16px; font-weight: 800; color: #94a3b8; line-height: 1.2;">🚀 Forward</div>
                     <div style="font-size: 13px; font-weight: 600; color: #64748b; margin-top: 2px;">(미래 추정 밸류 분석)</div></div>
                <span style="font-size: 11.5px; color: #64748b; font-weight: 500;">🔒 데이터 없음</span>
            </div>
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px;
                        padding: 26px 24px; text-align: center;">
                <div style="font-size: 30px; margin-bottom: 8px;">🔒</div>
                <h4 style="color: #cbd5e1; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">
                    Forward(미래 추정) 밸류에이션 산출 불가</h4>
                <p style="color: #94a3b8; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                    {reason_txt}<br>
                    위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. PEGY 점수(35점)만 배점에서 제외됩니다.</p>
            </div>
        </div>
        """
    else:
        forward_section_html = f"""
        <div style="background: linear-gradient(135deg, rgba(14, 116, 144, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%);
                    border: 2px solid #38bdf8; border-radius: 12px; padding: 16px 22px; box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #0284c7;
                        padding-bottom: 8px; margin-bottom: 14px;">
                <div><div style="font-size: 16px; font-weight: 800; color: #38bdf8; line-height: 1.2;">🚀 Forward</div>
                     <div style="font-size: 13px; font-weight: 600; color: #7dd3fc; margin-top: 2px;">(미래 추정 밸류 분석)</div></div>
                <span style="font-size: 11.5px; color: #7dd3fc; font-weight: 500;">
                    *애널리스트 컨센서스(Forward PER · 3년 EPS 성장 전망) 기반</span>
            </div>
            {floor_banner_html}
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">실효성장률 (g_eff) ℹ️<span class="q-tooltiptext"><b>실효성장률 = 3년 EPS 성장 전망 +
                        주주환원율(배당+자사주)</b><br>PEGY의 분모입니다. 폭주 방지를 위해 성장률 35%p / 주주환원 10%p /
                        합계 40%p 상한을 둡니다(상한에 걸리면 옆에 배지가 붙습니다).</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{fmt_num(g_eff, '%p', 2)}{geff_capped_badge_html}{growth_capped_badge_html}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">가치 지표 ℹ️<span class="q-tooltiptext"><b>Forward 밸류에이션</b><br>
                        • Forward PER: 주가 ÷ 향후 예상 EPS<br>• Forward EPS: 주가 ÷ Forward PER 로 역산한 계산값<br>
                        • Forward PEGY: Forward PER ÷ 실효성장률 (낮을수록 저평가)</span></span>
                    </div>
                    <div style="font-size: 18px; color: #f1f5f9; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">Forward PER</span> {fmt_num(s.get('f_per'), '배', 2)}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span>
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">Forward EPS</span> {fmt_usd(s.get('f_eps'))}{calc_feps_tag}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span>
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PEGY</span> {fmt_num(s.get('f_pegy'), '', 2)}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">3년 EPS 성장 전망 ℹ️<span class="q-tooltiptext">데이터 소스가 제공하는
                        애널리스트 컨센서스(EPS Growth Forecast, 3년) 실측값입니다.<br>우리가 추정하거나 가공한 값이 아닙니다.</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{fmt_num(s.get('growth'), '%', 2)}</div>
                </div>
                <div>
                    <div class="comparison-box" style="margin-bottom: 8px; border-color: #38bdf8; width: 100%;">
                        <div class="comparison-row divider">
                            <span class="label-text">현재가 (장마감 종가)</span>
                            <span class="price-text-curr">{fmt_usd(price)}{calc_price_tag}</span>
                        </div>
                        <div class="comparison-row divider">
                            <span class="label-text">
                                <span class="q-tooltip" style="color: #94a3b8; font-weight: 700;">🛡️ PBR 기준 바닥가 ℹ️<span class="q-tooltiptext"
                                style="color: #f1f5f9; font-weight: 400;">회사의 순자산 가치 기준 심리적 바닥 가격입니다 (현재가 ÷ PBR).</span></span>
                            </span>
                            <span style="font-size: 15px; font-weight: 700; color: #94a3b8;">{fmt_usd(s.get('floor_price'))}</span>
                        </div>
                        <div class="comparison-row">
                            <span class="label-text">
                                <span class="q-tooltip" style="color: #14b8a6; font-weight: 700;">모델 목표가 ℹ️<span class="q-tooltiptext"
                                style="color: #f1f5f9; font-weight: 400;"><b>목표 적정주가 (Forward PEGY 역산)</b><br>
                                <b>① 목표 PEGY</b> = 1.0 + ROE/ROIC 프리미엄<br>
                                <b>② 목표 PER</b> = 목표 PEGY × 실효성장률(g_eff)<br>
                                <b>③ 목표주가</b> = Forward EPS × 목표 PER<br>
                                고성장 종목은 공식상 발산하므로 <b>목표 PER 35배 / 현재가의 2.5배</b> 상한을 둡니다.<br>
                                ⚠️ 위 '애널리스트 컨센서스' 목표주가와는 다른 값입니다(그쪽은 소스 실측, 이쪽은 우리 모델 계산).</span></span>
                            </span>
                            <span class="price-text-target">{fmt_usd(f_target)}{target_cap_badge_html}</span>
                        </div>
                    </div>
                    <div class="gap-footer" style="color: {gap_color};">
                        <span>모델 적정가 대비 갭</span><span>{gap_str}</span>
                    </div>
                    <div class="gap-bar-bg">
                        <div style="height: 100%; width: {bar_width}%; background-color: {bar_color}; border-radius: 3px;"></div>
                    </div>
                </div>
            </div>
        </div>
        """

    # ── 적자 경고 배너
    loss_banner_html = ""
    if s.get("is_trailing_loss"):
        loss_reason = ", ".join(s.get("loss_evidence") or []) or "적자 판정"
        loss_banner_html = f"""
        <div style="background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 50%, #450a0a 100%); border: 1.5px solid #dc2626;
                    border-radius: 10px; padding: 12px 20px; margin-bottom: 14px; display: flex; align-items: center; gap: 14px;">
            <div style="font-size: 28px; flex-shrink: 0;">🚨</div>
            <div style="flex: 1;">
                <div style="color: #fca5a5; font-size: 14px; font-weight: 800; margin-bottom: 3px;">
                    ⚠️ 적자 기업 — PEGY 밸류에이션 산출 불가</div>
                <div style="color: #fecaca; font-size: 12px; font-weight: 500; line-height: 1.5;">
                    판정 근거: {loss_reason}. 데이터 소스도 적자 기업의 PER을 제공하지 않습니다(n/a).
                    성장 기반 밸류에이션(PEGY)을 적용할 수 없으니 각별한 주의가 필요합니다.</div>
            </div>
            <div style="background: #991b1b; border: 1px solid #f87171; border-radius: 8px; padding: 6px 14px;
                        text-align: center; flex-shrink: 0;">
                <div style="color: #f87171; font-size: 18px; font-weight: 900;">—</div>
                <div style="color: #fca5a5; font-size: 10px; font-weight: 600;">PEGY 산출 불가</div>
            </div>
        </div>
        """

    # ── Trailing 지표
    per_display = fmt_num(s.get("t_per"), "배", 2)
    if s.get("t_per") is None and s.get("is_reit"):
        per_display = f"n/a <span style='font-size:12px;color:#93c5fd;'>(리츠 — P/FFO {fmt_num(s.get('price_ffo'), '배', 2)})</span>"
    elif s.get("t_per") is None and s.get("is_trailing_loss"):
        per_display = "n/a <span style='font-size:12px;color:#fca5a5;'>(적자 — 소스 미제공)</span>"

    dps = s.get("dps")
    dps_str = fmt_usd(dps) + "/주" if dps else ("무배당 확정" if s.get("dividend_status") == "confirmed_none" else NA_TEXT)

    card_html = f"""
    <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155;
                border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4);
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155;
                    padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                {rank_prefix_html}{name_html}
                <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px;
                             font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                    <span class="q-tooltip" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="q-tooltiptext">
                    <b>종합 퀀트 스코어 (미국 종목용)</b><br>
                    PEGY 35 + 자본효율성(ROE·ROIC) 30 + 주주환원 20 + 재무건전성(F-Score) 10 + 변동성(베타) 5<br>
                    수집하지 못한 지표는 점수를 지어내지 않고 배점에서 아예 제외하므로 만점은 종목마다 다릅니다.<br>
                    {score_tooltip_extra}</span></span> {score_badge_html}
                </span>
                <span style="background-color: {s.get('badge_bg', '#1e293b')}; color: {s.get('badge_fg', '#cbd5e1')};
                             font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px;
                             border: 1px solid {s.get('badge_fg', '#64748b')}; white-space: nowrap;">{s.get('badge', '—')}</span>
                <span style="font-size: 12px; color: {beta_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6);
                             padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">
                    <span class="q-tooltip" style="color: {beta_color};">{beta_text} ℹ️<span class="q-tooltiptext">
                    <b>베타(5년)</b> = 이 종목이 시장(S&amp;P 500) 대비 얼마나 크게 출렁이는지 나타내는 지표입니다.<br>
                    베타 1.0 = 시장과 동일하게 움직임 · 1.0보다 크면 시장보다 더 크게 오르내림 · 1.0보다 작으면 더 완만하게 움직임<br>
                    (예: 베타 1.47 = 시장이 10% 움직일 때 이 종목은 평균적으로 약 14.7% 움직여온 편)<br>
                    🟢 저변동(&lt;1.0) · 🟡 시장 수준(1.0~1.5) · ⚡ 고변동(≥1.5) — 저평가·고평가 판단과는 무관하게
                    순수 변동성(리스크) 지표입니다.</span></span>
                </span>
                {trap_badge_html}
                {sector_badge_html}
            </div>
            <div style="display: flex; align-items: baseline; gap: 8px;">
                <span style="font-size: 13px; color: #94a3b8;">장마감 종가:</span>
                <span style="font-size: 25px; font-weight: 900; color: #38bdf8;">{fmt_usd(price)}</span>{calc_price_tag}
            </div>
        </div>

        {loss_banner_html}

        <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px;
                    padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; gap: 28px; flex-wrap: wrap;">
            <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="q-tooltip">ROE ℹ️<span class="q-tooltiptext"><b>자기자본이익률</b><br>
                순이익 ÷ 자기자본. 미국 시장 기준선은 15% 안팎이며, 9% 미만이면 자본비용도 못 버는 구간으로 봅니다.</span></span>:
                <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(t_roe, '%', 2)}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="q-tooltip">ROIC ℹ️<span class="q-tooltiptext"><b>투하자본이익률</b><br>
                세후영업이익 ÷ 투하자본. WACC(미국 대형주 8~10%)와 비교합니다.<br>
                은행·보험은 투하자본 개념이 달라 데이터 소스가 n/a로 제공합니다(수집 실패가 아님).</span></span>:
                <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(roic, '%', 2)}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="q-tooltip">ROA ℹ️<span class="q-tooltiptext"><b>총자산이익률</b> — 순이익 ÷ 총자산</span></span>:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(roa, '%', 2)}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">
                <span class="q-tooltip">F-Score ℹ️<span class="q-tooltiptext"><b>피오트로스키 F-Score (0~9)</b><br>
                수익성·재무건전성·운영효율 9개 항목을 점검하는 회계학 표준 스코어입니다. 높을수록 재무가 튼튼합니다.</span></span>:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(s.get('piotroski_f'), ' / 9')}</b>
            </span>
            <span style="font-size: 13px; color: #e2e8f0;">시가총액:
                <b style="color: #cbd5e1; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_big_usd(s.get('market_cap'))}</b>
            </span>
        </div>

        {analyst_html}

        <div style="background-color: rgba(30, 41, 59, 0.45); border: 1px solid #334155; border-radius: 10px;
                    padding: 12px 18px; margin-bottom: 14px; opacity: 0.92;">
            <div style="font-size: 12px; font-weight: 700; color: #94a3b8; margin-bottom: 10px;
                        border-bottom: 1px dashed #475569; padding-bottom: 4px; display: flex;
                        justify-content: space-between; align-items: center;">
                <span>📜 Trailing (과거 실적 참고용)</span>
                <span style="font-size: 11px; color: #64748b; font-weight: 400;">*최근 12개월(TTM) 확정 실적 스냅샷</span>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext">과거 12개월 자기자본 대비 순이익 비율</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #cbd5e1;">{fmt_num(t_roe, '%', 2)}</div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">가치 및 회수 지표 ℹ️<span class="q-tooltiptext"><b>Trailing 밸류에이션</b><br>
                        • PER: 주가÷순이익 • EPS: 주당순이익 • PBR: 주가÷순자산 • EV/EBITDA: M&A 투자원금 회수기간</span></span>
                    </div>
                    <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PER</span> {per_display}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span>
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">EPS</span> {fmt_usd(s.get('t_eps'))}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span>
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">PBR</span> {fmt_num(s.get('t_pbr'), '배', 2)}
                    </div>
                    <div style="font-size: 18px; color: #38bdf8; font-weight: 800; letter-spacing: -0.4px;">
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">EV/EBITDA</span> {fmt_num(s.get('ev_ebitda'), '배', 2)}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span>
                        <span style="font-size: 13px; font-weight: 800; color: #94a3b8;">BPS</span> {fmt_usd(s.get('bps'))}
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">주주환원 (확정) ℹ️<span class="q-tooltiptext"><b>주주환원 세부 내역</b><br>
                        • 주당배당금(DPS): {dps_str}<br>• 배당수익률: {fmt_num(s.get('div_yield'), '%', 2)}<br>
                        • 자사주 매입 수익률: {fmt_num(s.get('buyback_yield'), '%', 2)}<br>
                        • 배당성향: {fmt_num(s.get('payout_ratio'), '%', 2)}<br>
                        ※ 미국은 배당보다 자사주 매입 비중이 큰 기업이 많아, 점수에는 <b>둘을 합친 주주환원율</b>을 씁니다.<br>
                        ※ 증자·주식보상으로 주식수가 늘면 이 값은 <b>음수</b>가 될 수 있습니다(희석).</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #86efac;">
                        주주환원율 {fmt_num(s.get('sh_return'), '%', 2)}
                        <span style="font-size: 13px; color: #94a3b8;">(배당 {fmt_num(s.get('div_yield'), '%', 2)}
                        + 자사주 {fmt_num(s.get('buyback_yield'), '%', 2)})</span>
                    </div>
                </div>
                <div>
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                        <span class="q-tooltip">PEGY / 과거 적정가 ℹ️<span class="q-tooltiptext"><b>Trailing PEGY & 과거 적정주가</b><br>
                        • PEGY: Trailing PER ÷ 실효성장률<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                    </div>
                    <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">
                        {fmt_num(s.get('t_pegy'), '', 2)}
                        <span style="color: #475569; font-size: 15px; margin: 0 4px;">/</span>
                        {fmt_usd(s.get('t_fair'))}
                    </div>
                </div>
            </div>
        </div>

        {graham_box_html}
        {forward_section_html}
    </div>
    """
    st.markdown(_clean_html(card_html), unsafe_allow_html=True)

    if is_admin and (s.get("data_issues") or s.get("collect_errors")):
        with st.expander(f"⚙️ [관리자] {symbol} 수집 이슈 {len(s.get('data_issues') or [])}건", expanded=False):
            for issue in (s.get("collect_errors") or []):
                st.write(f"- (수집) {issue}")
            for issue in (s.get("data_issues") or []):
                st.write(f"- {issue}")


# =============================================================================
# 3. 페이지 렌더링
# =============================================================================
def render_us_stocks_page():
    """'🇺🇸 미국 주식은 이가격' 화면 (2026-08-08 오너 승인으로 공개 전환 — §0-3-6 절차 종료)"""
    st.markdown("<div id='us-top-anchor'></div>", unsafe_allow_html=True)

    metadata, all_stocks = load_us_snapshot()
    all_stocks = [s for s in all_stocks if s.get("is_visible", True)]
    is_admin = st.session_state.get("admin_mode", False)

    # 툴팁 CSS (코스피 화면과 동일한 클래스명 — 두 화면이 같이 뜨지 않으므로 충돌 없음)
    st.markdown(
        """
        <style>
        .q-tooltip { position: relative; display: inline-flex; align-items: center; cursor: help;
            color: #94a3b8; border-bottom: 1px dotted #64748b; font-weight: 500; }
        .q-tooltip .q-tooltiptext { visibility: hidden; width: 300px; box-sizing: border-box;
            white-space: normal; overflow-wrap: break-word; word-break: keep-all; line-height: 1.5;
            background-color: #0f172a; color: #f1f5f9;
            text-align: left; border-radius: 8px; padding: 12px 15px; position: absolute; z-index: 9999;
            bottom: 130%; left: 50%; transform: translateX(-50%); opacity: 0;
            transition: opacity 0.2s ease-in-out, visibility 0.2s; border: 1px solid #38bdf8;
            font-size: 11.5px; box-shadow: 0 6px 18px rgba(0,0,0,0.6); font-weight: 400; }
        .q-tooltip:hover .q-tooltiptext { visibility: visible; opacity: 1; }
        .comparison-box { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 10px;
            padding: 12px 14px; margin-bottom: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
        .comparison-row { display: flex; justify-content: space-between; align-items: center; padding: 3px 0; }
        .comparison-row.divider { border-bottom: 1px dashed #334155; padding-bottom: 6px; margin-bottom: 6px; }
        .label-text { font-size: 12px; color: #94a3b8; font-weight: 600; }
        .price-text-curr { font-size: 15px; font-weight: 800; color: #cbd5e1; }
        .price-text-target { font-size: 16px; font-weight: 800; color: #14b8a6; }
        .gap-footer { display: flex; justify-content: space-between; align-items: center;
            font-size: 13px; font-weight: 700; }
        .gap-bar-bg { height: 6px; background: #334155; border-radius: 3px; overflow: hidden; margin-top: 8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 타이틀 + 투자주의 배너
    #    2026-08-08: 오너 승인(§0-3-6)으로 공개 전환하면서 "🧪 [베타 · 검토중] 아직 공개되지 않은
    #    화면입니다" 배너를 제거했습니다. 그 배너가 알리던 내용("임계값이 아직 잠정값")은 2026-08-07
    #    실측 548종목 분포 기반 재캘리브레이션으로 해소됐습니다(`utils/constants_us.py` §5 전 항목 확정).
    #    아래 투자주의 경고 배너는 공개 화면인 코스피(`views/pegy_view.py`)와 동일하게 그대로 둡니다.
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 36px; font-weight: 800; color: #d97706; margin: 0 0 6px 0; letter-spacing: -0.5px;">
                🇺🇸 미국 주식은 이가격</h1>
            <div style="background: linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%); border: 2px solid #ef4444;
                        border-radius: 12px; padding: 12px 22px; margin: 10px auto 14px auto; max-width: 860px;">
                <div style="font-size: 15px; font-weight: 800; color: #fca5a5;">🚨 [투자 주의 경고 및 분석 안내]</div>
                <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
                    본 리포트의 수치는 <b>공개된 재무 데이터를 퀀트 알고리즘이 자동 계산한 단순 참고용 정보</b>입니다.<br>
                    특정 종목의 매수·매도를 권유하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.</div>
                <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
                    ⚠️ 모든 투자 결정과 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있습니다.
                    환율 변동 위험은 이 화면에 반영되어 있지 않습니다(가격은 전부 USD 표기).</div>
            </div>
            <div style="font-size: 15.5px; color: #64748b; font-weight: 600;">
                미국(나스닥+뉴욕) 시가총액 상위 550개 종목 Trailing vs Forward PEGY & 퀀트 종합점수 리포트<br>
                <span style="font-size: 13px; color: #475569;">
                (만점은 종목마다 다릅니다 — 수집하지 못한 지표는 점수를 지어내지 않고 배점에서 제외합니다.
                모든 금액은 <b>미국 달러(USD)</b> 표기이며 원화 환산을 하지 않습니다)</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 상단 지수 3종
    render_index_header(metadata.get("indices") or {})

    if not all_stocks:
        st.error(
            f"🚨 미국주식 스냅샷을 불러오지 못했습니다. ({metadata.get('load_error', '원인 미상')})\n\n"
            "가짜 기본값으로 화면을 채우지 않기 위해 밸류에이션 수치를 표시하지 않습니다.\n\n"
            "로컬에서 `python collector_us_stocks.py collect` 를 실행해 스냅샷을 만들어 주세요."
        )
        return

    last_updated_et = metadata.get("last_updated_at_et")
    last_updated_kst = metadata.get("last_updated_at_kst")
    snapshot_status = metadata.get("status", "UNKNOWN")

    if snapshot_status not in ("SUCCESS", "UNKNOWN"):
        st.warning(
            f"⚠️ 스냅샷 수집 상태: **{snapshot_status}** — "
            f"검증 통과 {metadata.get('valid_count', '?')}/{metadata.get('total_count', '?')}종목. "
            "일부 종목은 데이터 부족으로 '측정 불가' 카드로 표시됩니다."
        )
    failed = metadata.get("failed_tickers") or []
    if failed:
        with st.expander(f"⚠️ 수집 실패 {len(failed)}종목 (조용히 건너뛰지 않고 전부 기록합니다)", expanded=False):
            for f in failed[:100]:
                st.write(f"- **{f.get('symbol')}**: {f.get('reason')}")
            if len(failed) > 100:
                st.write(f"... 외 {len(failed) - 100}종목")

    st.markdown(
        f"""
        <div style="background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #0284c7;
                    border-radius: 10px; padding: 12px 20px; margin-bottom: 22px; text-align: center;">
            <span style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">
                📅 마지막 동기화: {last_updated_et or NA_TEXT} ET
                <span style="font-size: 13px; color: #7dd3fc;">({last_updated_kst or NA_TEXT} KST)</span>
            </span>
            <span style="font-size: 13px; color: #94a3b8; margin-left: 14px; font-weight: 600;">
                • 미국 장마감 후 확정 데이터 ({metadata.get('total_count', len(all_stocks))}개 종목 / 상태 {snapshot_status})
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 다운로드 (raw / 가공 둘 다 — §0-3-3)
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        snap_path = os.path.join(_DATA_DIR, "us_stocks_latest.json")
        if os.path.exists(snap_path):
            with open(snap_path, "r", encoding="utf-8") as f:
                st.download_button(
                    "📥 미국주식 최신 스냅샷 다운로드 (가공 데이터, JSON)", f.read(),
                    file_name=f"us_stocks_latest_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json",
                )
    with col_dl2:
        raw_path = os.path.join(_DATA_DIR, "us_stocks_raw_latest.json")
        if os.path.exists(raw_path):
            with open(raw_path, "r", encoding="utf-8") as f:
                st.download_button(
                    "📥 크롤링 원본(raw) 다운로드 (JSON)", f.read(),
                    file_name=f"us_stocks_raw_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json",
                )
    st.markdown("<br>", unsafe_allow_html=True)

    # 요약 지표 3종
    f_per_list = [s["f_per"] for s in all_stocks if s.get("f_per")]
    growth_list = [s["growth"] for s in all_stocks if s.get("growth") is not None]
    pegy_list = [s["f_pegy"] for s in all_stocks if s.get("f_pegy") and 0 < s["f_pegy"] < 50.0]

    def _median(vals):
        if not vals:
            return None
        srt = sorted(vals)
        mid = len(srt) // 2
        return srt[mid] if len(srt) % 2 else (srt[mid - 1] + srt[mid]) / 2.0

    calc_f_per = round(_median(f_per_list), 1) if f_per_list else None
    calc_growth = round(_median(growth_list), 1) if growth_list else None
    calc_pegy = round(_median(pegy_list), 2) if pegy_list else None

    history = load_us_summary_history()
    f_per_delta = f"{len(f_per_list)}개 종목 실측 중앙값"
    growth_delta = f"{len(growth_list)}개 종목 실측 중앙값"
    pegy_delta_num = None
    if len(history) >= 2 and None not in (calc_f_per, calc_growth, calc_pegy):
        prev = history[-2]
        if prev.get("f_per") is not None:
            f_per_delta = f"{calc_f_per - prev['f_per']:+.1f}배 (이전 동기화 대비)"
        if prev.get("growth") is not None:
            growth_delta = f"{calc_growth - prev['growth']:+.1f}%p (이전 동기화 대비)"
        if prev.get("pegy") is not None:
            pegy_delta_num = f"{calc_pegy - prev['pegy']:+.2f}"

    if calc_pegy is None:
        pegy_status = "산출 불가 (표본 없음)"
    elif calc_pegy < 0.85:
        pegy_status = "🟢 저평가 수용 구간"
    elif calc_pegy < 1.15:
        pegy_status = "🟡 적정 밸류 구간"
    else:
        pegy_status = "🔴 고평가 관망 구간"
    pegy_delta = f"{pegy_delta_num} | {pegy_status}" if pegy_delta_num else pegy_status

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("미국 상위 종목 중앙 Forward PER", fmt_num(calc_f_per, " 배", 1), f_per_delta)
    with c2:
        st.metric("중앙 3년 EPS 성장 전망 (컨센서스)", fmt_num(calc_growth, " %", 1), growth_delta)
    with c3:
        st.metric("시장 적정 밸류에이션 (PEGY)", fmt_num(calc_pegy, "", 2), pegy_delta)

    if None in (calc_f_per, calc_growth, calc_pegy):
        st.warning("⚠️ 위 요약 지표 중 일부는 실측 표본이 없어 산출하지 못했습니다 ('데이터 없음').")

    st.markdown("---")

    # 검색 / 필터
    all_badges = list(dict.fromkeys([s["badge"] for s in all_stocks if s.get("badge")]))
    f1, f2, f3 = st.columns([2.2, 3.2, 2.0])
    with f1:
        search_query = st.text_input(
            "🔍 종목명 / 티커 검색", placeholder="예: 엔비디아, NVIDIA, NVDA", key="us_search"
        ).strip()
    with f2:
        preset = st.selectbox(
            "🏷️ 밸류에이션 빠른 필터",
            [
                "🌐 전체 종목 보기",
                "🟢 저평가 우량주 그룹 (강력저평가 + 저평가)",
                "🟡 적정가 형성 그룹 (적정가 + 목표달성)",
                "🔴 고평가 / 주의 종목 그룹",
                "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)",
            ],
            index=0, key="us_preset",
        )
        selected_badges = None
        if "세부 뱃지" in preset:
            selected_badges = st.multiselect("상세 뱃지 선택", all_badges, default=all_badges, key="us_badges")
        elif "저평가 우량주" in preset:
            selected_badges = [b for b in all_badges if "저평가" in b and "고평가" not in b]
        elif "적정가" in preset:
            selected_badges = [b for b in all_badges if "적정가" in b]
        elif "고평가" in preset:
            # "검증" 키워드는 "PER 검증 실패"(경고) 뿐 아니라 "Trailing만 검증됨"(단순 데이터
            # 상태 안내, 위험 아님) / "데이터 검증 필요"(fallback 안내)까지 잘못 포함시키므로
            # 두 정보성 뱃지는 명시적으로 제외한다.
            _non_warning_badges = ("Trailing만 검증됨", "데이터 검증 필요")
            selected_badges = [
                b for b in all_badges
                if ("고평가" in b or "역성장" in b or "위험" in b or "검증" in b)
                and not any(nb in b for nb in _non_warning_badges)
            ]
    with f3:
        only_trap = st.checkbox(
            "⚠️ '착시 저평가' 주의 종목만 보기", value=False, key="us_trap",
            help="PER은 싸 보이지만 실제 이익창출력(ROE·ROIC)이 기준선에 못 미쳐 주가가 오래 갇힐 위험이 있는 종목입니다.",
        )

    st.markdown(
        _clean_html("""
        <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #0284c7; border-radius: 12px;
                    padding: 16px 22px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 15px; font-weight: 800; color: #38bdf8; margin-bottom: 10px;">
                💡 미국주식 퀀트 스코어 / 코스피 화면과 다른 점</div>
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
        """),
        unsafe_allow_html=True,
    )

    filtered = all_stocks
    if search_query:
        q = search_query.lower()
        filtered = [
            s for s in filtered
            if q in (s.get("name") or "").lower()
            or q in (s.get("name_kr") or "")
            or q in (s.get("symbol") or "").lower()
        ]
    if selected_badges:
        filtered = [s for s in filtered if s.get("badge") in selected_badges]
    if only_trap:
        filtered = [s for s in filtered if s.get("value_trap")]

    st.markdown(f"**전체 검색/필터 결과:** `{len(filtered)}`개 종목 (총 {len(all_stocks)}개 미국 종목 중)")

    items_per_page = US_PAGE_SIZE
    total_items = len(filtered)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    if "us_current_page" not in st.session_state:
        st.session_state.us_current_page = 1
    current_page = min(st.session_state.us_current_page, total_pages)
    start_idx = (current_page - 1) * items_per_page
    page_stocks = filtered[start_idx:start_idx + items_per_page]

    st.markdown("---")
    if not page_stocks:
        st.warning("선택한 필터 조건에 일치하는 종목이 없습니다.")
        return

    for i, s in enumerate(page_stocks):
        _render_stock_card(s, start_idx + i + 1, is_admin=is_admin)

    # 페이지네이션
    st.markdown("---")
    pc1, pc2 = st.columns([0.8, 0.2])
    with pc1:
        st.markdown(f"##### 📄 페이지 선택 (한 화면에 {items_per_page}개 종목 카드 노출)")
    with pc2:
        st.markdown(
            "<div style='text-align: right; padding-top: 5px;'>"
            "<a href='#us-top-anchor' target='_self' style='display: inline-block; padding: 8px 16px; "
            "background-color: #38bdf8; color: #0f172a; font-size: 14px; font-weight: 800; border-radius: 8px; "
            "text-decoration: none;'>⬆️ TOP으로 가기</a></div>",
            unsafe_allow_html=True,
        )

    page_options = [
        f"페이지 {i} (종목 {(i - 1) * items_per_page + 1} ~ {min(i * items_per_page, total_items)})"
        for i in range(1, total_pages + 1)
    ]
    selected_page = st.radio(
        "페이지 이동", page_options, index=current_page - 1, horizontal=True, key="us_page_radio"
    )
    new_page = page_options.index(selected_page) + 1
    if new_page != st.session_state.us_current_page:
        st.session_state.us_current_page = new_page
        st.rerun()

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #475569;
                    border-radius: 12px; padding: 12px 22px; margin: 20px auto 10px auto; max-width: 860px; text-align: center;">
            <div style="font-size: 14px; font-weight: 800; color: #38bdf8;">⚠️ [알림: 학습용 보조 도구]</div>
            <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600; margin-top: 5px; line-height: 1.5;">
                본 서비스는 정식 금융기관이 아닌 주식 공부를 돕는 개인 프로젝트(보조 도구)입니다.<br>
                종목 추천이나 원금 보장을 하지 않으며, 모든 데이터는 참고용이므로 최종 투자 판단과 책임은 본인에게 있습니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
