"""
HTML 문자열 조립 헬퍼 (순수 함수 — NiceGUI 를 import 하지 않습니다).

`views/pegy_view.py` / `views/us_stocks_view.py` 는 화면의 90% 이상이 f-string 으로
조립한 거대 HTML 문자열입니다(계획서 §1-1). NiceGUI 에서는 그걸 `ui.html(...)` 에
그대로 넣으면 되므로, 이식에서 실제로 손이 가는 건 **문자열을 만드는 부분**뿐입니다.
그 중 두 화면이 공통으로 쓰는 조각만 여기에 모읍니다.

⚠️ 보안 (ENGINEERING_SPEC.md §0-3-9 XSS):
   `ui.html(...)` 로 그리는 문자열에 **우리가 만들지 않은 값**(사용자 입력, 그리고
   네이버에서 크롤링해 온 종목명·배지·사유 문구 등 외부 문자열)이 섞이는 자리는
   반드시 `esc()` 를 거칩니다. 기존 Streamlit 코드는 크롤링 값을 그대로 넣고 있었는데,
   NiceGUI 에서도 같은 실수를 반복하지 않도록 이식하면서 전부 `esc()` 를 붙였습니다.
   (정상적인 한글 종목명은 이스케이프해도 화면 출력이 100% 동일합니다.)
"""

import html as _html

# ── 앰버(주의) 배지 공통 스타일 ────────────────────────────────────────────
# pegy 카드의 "🧮 계산값", "⚡ 추정치 변동 큼", "⚠️ 고성장 추정 보수반영",
# "🧮 상한 적용값" 네 곳이 글자만 다르고 스타일이 완전히 동일했습니다(원본 4중 복붙).
_WARN_BADGE_STYLE = (
    'font-size: 10px; font-weight: 800; color: #fbbf24; background-color: #78350f; '
    'border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; vertical-align: middle;'
)
# 파란(정보) 배지 — "🛡️ 장부가 바닥값"처럼 경고가 아니라 '이 값의 출처가 다르다'는 안내용.
_INFO_BADGE_STYLE = (
    'font-size: 10px; font-weight: 800; color: #7dd3fc; background-color: #1e3a5f; '
    'border: 1px solid #38bdf8; border-radius: 6px; padding: 1px 6px; vertical-align: middle;'
)

NA_TEXT = '데이터 없음'


def esc(value, fallback: str = '') -> str:
    """HTML 특수문자 이스케이프. None 이면 `fallback` 을 그대로 돌려줍니다.

    따옴표까지 이스케이프하므로 `style="...{값}..."` 같은 **속성 안**에 넣어도 안전합니다.
    """
    if value is None:
        return fallback
    return _html.escape(str(value), quote=True)


def compact(markup: str) -> str:
    """줄마다 앞뒤 공백을 없애고 빈 줄을 제거합니다.

    기존 Streamlit 코드가 `st.markdown(...)` 직전에 항상 하던 처리와 동일합니다
    (들여쓰기가 4칸 이상이면 마크다운이 코드블록으로 오인하는 문제 회피). NiceGUI 의
    `ui.html()` 은 마크다운 파서를 거치지 않지만, **출력 HTML을 기존과 동일하게 유지**
    하려고 같은 처리를 그대로 씁니다.
    """
    return '\n'.join(line.strip() for line in markup.split('\n') if line.strip())


def tooltip(label_html: str, body_html: str, *,
            trigger_style: str = '', body_style: str = '') -> str:
    """ℹ️ 툴팁 span 한 개를 만듭니다.

    - `label_html` / `body_html` 은 **우리가 작성한 HTML**입니다(<b>, <br> 포함 가능).
      외부에서 온 값을 넣을 때는 호출하는 쪽에서 `esc()` 를 씌워 넘기세요.
    - `tabindex="0"` 은 #124→#125 에서 확정된 모바일 대응(탭하면 포커스 → 툴팁 표시)이라
      반드시 유지합니다.
    - 클래스명이 `q-tooltip` 이 아니라 `vh-tooltip` 인 이유는 `web/theme.py` 주석 참고
      (Quasar 내장 클래스명과의 충돌 회피).
    """
    trigger_attr = f' style="{trigger_style}"' if trigger_style else ''
    body_attr = f' style="{body_style}"' if body_style else ''
    return (
        f'<span class="vh-tooltip" tabindex="0"{trigger_attr}>{label_html}'
        f'<span class="vh-tooltiptext"{body_attr}>{body_html}</span></span>'
    )


def warn_badge(label_html: str, body_html: str) -> str:
    """앰버색 주의 배지(+툴팁). 앞에 공백 한 칸이 붙습니다(기존 출력과 동일).

    "🧮 계산값" 처럼 **값의 출처가 실측이 아님을 반드시 표시해야 하는 자리**
    (ENGINEERING_SPEC.md §0-1 예시2-보충)에 씁니다.
    """
    return ' ' + tooltip(label_html, body_html, trigger_style=_WARN_BADGE_STYLE)


def info_badge(label_html: str, body_html: str) -> str:
    """파란색 안내 배지(+툴팁). 구조는 `warn_badge` 와 같고 색만 다릅니다.

    (us_stocks 의 "🛡️ 장부가 바닥값" 처럼 위험 경고가 아닌 출처 안내에 씁니다.)
    """
    return ' ' + tooltip(label_html, body_html, trigger_style=_INFO_BADGE_STYLE)


# =============================================================================
# 숫자 포맷 — 두 화면(pegy·us_stocks)이 글자 하나까지 같은 함수를 씁니다
# =============================================================================
def fmt_num(value, suffix: str = '', digits=None, na_text: str = NA_TEXT) -> str:
    """
    None / 결측값을 절대 그럴듯한 숫자로 바꾸지 않고 '데이터 없음'으로 표기합니다.
    (ENGINEERING_SPEC.md §0-1)
    """
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


# =============================================================================
# 카드 공통 조각 (pegy · us_stocks 가 같은 마크업을 씁니다 — §0-3-10)
# =============================================================================
def rank_prefix_html(rank_num) -> str:
    """카드 왼쪽 위의 커다란 순위 숫자."""
    return (
        f'<span style="font-size: 32px; font-weight: 900; color: #38bdf8; letter-spacing: -1px; '
        f'margin-right: 4px; line-height: 1;">{esc(rank_num)}.</span>'
    )


def quality_badge(state: str) -> str:
    """자본효율성(착시 저평가) 배지.

    :param state: 'trap'(착시 저평가) / 'unknown'(판정 불가) / 'ok'(우량)
      — **판정 조건은 화면마다 다릅니다**(코스피는 ROE 단독, 미국은 ROE·ROIC).
        그래서 조건은 호출하는 쪽에 두고, 여기서는 배지 모양만 책임집니다.
    """
    if state == 'trap':
        return """
        <span style="background-color: #7f1d1d; color: #fca5a5; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #f87171; white-space: nowrap;">
            ⚠️ 이익창출력 저하 (착시 저평가 주의)
        </span>
        """
    if state == 'unknown':
        return """
        <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #64748b; white-space: nowrap;">
            ❔ 자본효율성 판정 불가 (데이터 없음)
        </span>
        """
    return """
    <span style="background-color: #14532d; color: #86efac; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #4ade80; white-space: nowrap;">
        ✨ 우량 자본효율성 (Quality OK)
    </span>
    """


def quant_score_badge(quant_score, score_max, excluded_items):
    """🏆 퀀트 스코어 배지 문구와 툴팁 보충문을 만듭니다.

    반환값 `(badge_html, tooltip_extra)`.
    ⚠️ §0-1 — 점수가 없으면 '측정 불가', 만점을 모르면 달성률(%)을 지어내지 않습니다.
    """
    if quant_score is None:
        return ('<b>측정 불가</b> (데이터 없음)', '필수 지표를 수집하지 못해 점수를 산출하지 않았습니다.')

    if not score_max:
        badge_html = f'<b>{esc(quant_score)}점</b> / 만점 산출 불가 (채점 가능 항목 없음)'
    else:
        pct = round(quant_score / score_max * 100)
        if pct >= 60:
            pct_color = '#4ade80'
        elif pct >= 30:
            pct_color = '#fde047'
        else:
            pct_color = '#fca5a5'
        badge_html = (
            f"<b>{esc(quant_score)}점</b> / {esc(score_max)}점 "
            f"<span style='color:{pct_color}; font-weight:900;'>({pct}%)</span>"
        )
    items = excluded_items or []
    tooltip_extra = (
        f"※ 배점 제외 항목: {esc(', '.join(str(x) for x in items))}" if items
        else '모든 항목이 배점에 반영되었습니다.'
    )
    return (badge_html, tooltip_extra)


def forward_mask_html(*, border_color, inner_border, gradient_from, title_color, sub_color,
                      corner_text, icon, headline, body_html,
                      headline_color=None, body_color=None, corner_nowrap: bool = True) -> str:
    """🚀 Forward 자리 마스크 패널 (사유별 색상만 다르고 구조는 동일).

    ENGINEERING_SPEC.md §0-1 예시2-보충2 — 결측은 "종목 전체 차단"이 아니라
    "해당 섹션만 마스킹 + 반드시 이유 명시" 입니다.

    `headline_color` / `body_color` / `corner_nowrap` 은 **두 화면의 기존 출력을 그대로
    유지하기 위한** 선택 인자입니다(us_stocks 쪽 일부 패널이 제목·본문 색을 따로 씁니다).
    넘기지 않으면 코스피 화면과 동일하게 title_color / sub_color 를 씁니다.
    """
    headline_color = headline_color or title_color
    body_color = body_color or sub_color
    corner_style = ' white-space: nowrap;' if corner_nowrap else ''
    return f"""
    <div style="background: linear-gradient(135deg, {gradient_from} 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed {border_color}; border-radius: 12px; padding: 16px 22px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid {inner_border}; padding-bottom: 8px; margin-bottom: 14px;">
            <div>
                <div style="font-size: 16px; font-weight: 800; color: {title_color}; line-height: 1.2;">🚀 Forward</div>
                <div style="font-size: 13px; font-weight: 600; color: {sub_color}; margin-top: 2px;">(미래 추정 밸류 분석)</div>
            </div>
            <span style="font-size: 11.5px; color: {sub_color}; font-weight: 500;{corner_style}">{corner_text}</span>
        </div>
        <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid {inner_border}; border-radius: 10px; padding: 26px 24px; text-align: center;">
            <div style="font-size: 30px; margin-bottom: 8px;">{icon}</div>
            <h4 style="color: {headline_color}; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">{headline}</h4>
            <p style="color: {body_color}; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                {body_html}
            </p>
        </div>
    </div>
    """


def graham_unavailable_box(headline: str, reason_html: str = '', *,
                           headline_color: str = '#94a3b8') -> str:
    """🧮 그레이엄 넘버를 **수학적으로 산출할 수 없을 때**의 회색 박스(적자 기업).

    값을 0이나 평균치로 채우지 않고 "산출 불가"임을 그대로 노출합니다(§0-1).
    """
    reason_line = (
        f'<div style="color: #64748b; font-size: 11.5px; font-weight: 600; margin-top: 4px;">판정 근거: {reason_html}</div>'
        if reason_html else ''
    )
    return f"""
    <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px dashed #475569; border-radius: 10px; padding: 14px 20px; text-align: center; margin-bottom: 14px;">
        <div style="color: {headline_color}; font-size: 12.5px; font-weight: 700;">{headline}</div>
        {reason_line}
    </div>
    """


def graham_financial_box(target_text: str, sectors_text: str) -> str:
    """🧮 금융업종용 그레이엄 넘버 박스 — 값은 보여주되 **강한 경고**를 함께 답니다.

    (ENGINEERING_SPEC.md §0-1 적용사례 2 — 장부가(BPS)의 의미가 제조업과 달라
     공식의 전제가 잘 맞지 않는다는 사실을 반드시 화면에 표기합니다.)
    """
    return f"""
    <div style="background-color: rgba(127, 29, 29, 0.35); border: 2px solid #f87171; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;">
        <div style="color: #fca5a5; font-size: 13px; font-weight: 800; margin-bottom: 6px;">⚠️⚠️ 강한 경고: 금융업종 — 그레이엄 넘버 적용 부적합 가능성 높음</div>
        <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">🧮 {target_text} <span style="font-size: 12px; color: #fca5a5; font-weight: 700;">(Trailing 전용 참고 목표가)</span></div>
        <p style="color: #fecaca; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
            {sectors_text} 등은 장부가(BPS)의 의미가 제조업과 달라, 이 공식(√22.5×EPS×BPS)의 전제가 잘 맞지 않습니다.<br>
            참고 수준으로만 활용하고, 이 숫자를 실제 목표주가로 신뢰하지 마세요.
        </p>
    </div>
    """


def graham_reference_box(target_text: str) -> str:
    """🧮 일반 종목의 그레이엄 넘버 참고 박스 (Trailing 전용 목표가)."""
    return f"""
    <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #475569; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;">
        <div style="color: #94a3b8; font-size: 13px; font-weight: 700; margin-bottom: 6px;">🧮 Trailing 전용 참고 목표가 (Graham Number)</div>
        <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">{target_text}</div>
        <p style="color: #94a3b8; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
            성장률 예측 없이 √(22.5 × Trailing EPS × BPS) 공식(벤저민 그레이엄)으로만 산출한 참고값입니다.<br>
            고성장 기업에는 보수적으로(낮게) 나올 수 있으니 유일한 판단 근거로 쓰지 마세요.
        </p>
    </div>
    """


def loss_banner_html(headline_html: str, body_html: str) -> str:
    """🚨 적자 기업 경고 배너 (PEGY 산출 불가).

    오른쪽 점수 자리에는 **값을 쓰지 않습니다** — 예전에 여기 '99.99' 가 하드코딩돼
    있었습니다(§0-1).
    """
    return f"""
    <div style="background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 50%, #450a0a 100%); border: 1.5px solid #dc2626; border-radius: 10px; padding: 12px 20px; margin-bottom: 14px; display: flex; align-items: center; gap: 14px; box-shadow: 0 0 15px rgba(220, 38, 38, 0.25);">
        <div style="font-size: 28px; flex-shrink: 0;">🚨</div>
        <div style="flex: 1;">
            <div style="color: #fca5a5; font-size: 14px; font-weight: 800; margin-bottom: 3px;">
                {headline_html}
            </div>
            <div style="color: #fecaca; font-size: 12px; font-weight: 500; line-height: 1.5;">
                {body_html}
            </div>
        </div>
        <!-- 값이 없으면 값을 쓰지 않습니다 (§0-1). 예전에 여기 하드코딩 '99.99'가 박혀 있었습니다. -->
        <div style="background: #991b1b; border: 1px solid #f87171; border-radius: 8px; padding: 6px 14px; text-align: center; flex-shrink: 0;">
            <div style="color: #f87171; font-size: 18px; font-weight: 900;">—</div>
            <div style="color: #fca5a5; font-size: 10px; font-weight: 600;">PEGY 산출 불가</div>
        </div>
    </div>
    """


# ── 두 공개 화면이 글자 하나까지 같은 고지 문구 ────────────────────────────
# (문구가 두 파일에 복붙돼 있으면 한쪽만 고쳐지는 사고가 납니다 — §0-3-10)
LEARNING_NOTICE_HTML = """
<div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #475569; border-radius: 12px; padding: 12px 22px; margin: 0 auto 24px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);">
    <div style="font-size: 15px; font-weight: 800; color: #38bdf8; letter-spacing: -0.3px;">
        📘 [학습용 보조 도구 안내]
    </div>
    <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
        '잘 보면 보이는 손'은 정식 금융기관의 서비스가 아니며, 주식 초보자의 직관적인 밸류에이션 이해를 돕는 <b>참고용 프로젝트</b>입니다.
    </div>
    <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600; margin-top: 3px;">
        ⚠️ 본 서비스는 종목 추천이나 원금 보장을 하지 않습니다.<br>
        제공된 데이터는 참고용으로만 활용하시고, 모든 투자 판단과 책임은 본인에게 있습니다.
    </div>
</div>
"""

FOOTER_NOTICE_HTML = """
<div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #475569; border-radius: 12px; padding: 12px 22px; margin: 20px auto 10px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);">
    <div style="font-size: 14px; font-weight: 800; color: #38bdf8; letter-spacing: -0.3px;">
        ⚠️ [알림: 학습용 보조 도구]
    </div>
    <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600; margin-top: 5px; line-height: 1.5;">
        본 서비스는 정식 금융기관이 아닌 주식 공부를 돕는 개인 프로젝트(보조 도구)입니다.<br>
        종목 추천이나 원금 보장을 하지 않으며, 모든 데이터는 참고용이므로 최종 투자 판단과 책임은 본인에게 있습니다.
    </div>
</div>
"""
