"""
views/scorecard_view.py
📊 "내 성적표" — 내 보유 종목을 직접 입력하고, 기존 PEGY 밸류에이션과 대조해보는 화면 (v1)

🚧 **스테이징 상태 (ENGINEERING_SPEC.md §0-3-6)** — 오너 승인 전까지 공개 메뉴에 노출되지
   않습니다. 기본값은 숨김이고, ① 관리자 인증 상태이거나 ② `SCORECARD_ENABLED` 플래그를
   명시적으로 켠 경우에만 사이드바에 미리보기 진입점이 생깁니다(`is_scorecard_visible()`).

v1 범위 (SCORECARD_WORK_ORDER.md §2)
   - Supabase Auth 이메일+비밀번호 회원가입/로그인/로그아웃
   - 보유 종목 **수동 입력**(종목/수량/매입가). 스크린샷 OCR은 v2로 보류
   - 같은 종목을 여러 번(여러 증권사) 넣으면 수량 가중평균으로 매입가 자동 재계산
   - 원형차트 2종: 종목별 평가금액 비중 / 종목별 이익 기여 비중
   - 기존 스냅샷(data/kospi200_pegy_latest.json · data/us_stocks_latest.json) 연동 요약

지켜야 할 것
   - **환율 변환 없음** — 원화/달러를 절대 합치지 않고 통화별로 따로 계산·표시합니다.
   - **지어내지 않기(§0-1)** — 현재가는 기존 수집 스냅샷의 실측값만 씁니다. 유니버스 밖
     종목은 "현재가 없음"으로 정직하게 표시하고 평가금액·수익률을 계산하지 않습니다.
     사용자가 입력한 매입가를 현재가처럼 쓰는 경로는 없습니다.
   - **Supabase 호출 실패를 조용히 넘기지 않기** — 실패는 st.error 로 화면까지 도달시킵니다.
   - 이 화면은 기존 두 모듈(코스피/미국주식)의 코드와 데이터를 **읽기 전용**으로만 씁니다.
"""

import os

import streamlit as st

from utils.scorecard_db import (
    MARKET_KR,
    MARKET_LABELS,
    MARKET_US,
    NO_FX_CONVERSION_NOTICE,
    ScorecardError,
    add_lot,
    build_portfolio,
    create_supabase_client,
    current_user,
    delete_holding,
    fetch_holdings,
    format_amount,
    load_universe_index,
    make_price_lookup,
    sign_in,
    sign_out,
    sign_up,
    supabase_status,
    user_id_of,
    valuation_summary,
)

# 원형차트는 plotly 로 그립니다(이미 requirements.txt 에 있고 매크로 화면에서도 사용 중).
# 그래도 없을 때 화면 전체가 죽지 않도록 감싸두고, 없으면 표로 대체합니다.
try:
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:  # pragma: no cover
    px = None
    PLOTLY_AVAILABLE = False

SESSION_CLIENT_KEY = "scorecard_supabase_client"
SESSION_USER_KEY = "scorecard_user"

CURRENCY_TITLES = {
    "KRW": "🇰🇷 한국 주식 (원화)",
    "USD": "🇺🇸 미국 주식 (달러)",
}


# =============================================================================
# 0. 노출 제어 (§0-3-6 스테이징)
# =============================================================================
def is_scorecard_enabled():
    """
    명시적 활성화 플래그. **기본값은 꺼짐**입니다.
    Streamlit Cloud Secrets 또는 환경변수에 `SCORECARD_ENABLED = "1"` (또는 true/on/yes)를
    넣었을 때만 켜집니다. 오너 승인 전에는 켜지 마세요.
    """
    raw = os.environ.get("SCORECARD_ENABLED")
    if raw is None:
        try:
            raw = st.secrets.get("SCORECARD_ENABLED")
        except Exception:
            raw = None
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_scorecard_visible(admin_mode=False):
    """사이드바에 진입점을 만들지 여부. 관리자 미리보기 또는 명시적 플래그일 때만 True."""
    return bool(admin_mode) or is_scorecard_enabled()


# =============================================================================
# 1. 세션 / 인증
# =============================================================================
def _get_client():
    """
    방문자별 Supabase 클라이언트. **@st.cache_resource 로 캐시하면 안 됩니다** —
    클라이언트가 로그인 세션(JWT)을 들고 있어서, 캐시하면 한 사람의 로그인이 모든
    방문자에게 공유됩니다. 그래서 세션 상태에만 보관합니다.
    """
    if SESSION_CLIENT_KEY not in st.session_state:
        st.session_state[SESSION_CLIENT_KEY] = create_supabase_client()
    return st.session_state[SESSION_CLIENT_KEY]


def _render_not_ready(status):
    """Supabase 가 준비되지 않은 상태 안내 (에러가 아니라 '준비중'입니다)."""
    st.warning(
        "🚧 **내 성적표는 아직 준비중입니다.**\n\n"
        f"사유: {status.reason}\n\n"
        "이 화면이 준비되지 않아도 기존 밸류에이션 리포트(한국/미국)는 정상 동작합니다."
    )
    with st.expander("🔧 오너 설정 체크리스트 (관리자용)", expanded=False):
        st.markdown(
            """
1. Supabase 프로젝트 생성 (무료 티어)
2. Supabase → SQL Editor 에서 `sql/scorecard_schema.sql` 전체 실행
   → `profiles` / `holdings` 테이블 + **RLS 정책 8개** 생성 확인
3. Supabase → Authentication → Providers → **Email** 활성화
4. Streamlit Cloud → 앱 → Settings → **Secrets** 에 아래 2줄 등록
   (⚠️ GitHub Actions Secrets 가 아니라 **Streamlit Cloud 쪽** Secrets 입니다)
   ```toml
   SUPABASE_URL = "..."
   SUPABASE_ANON_KEY = "..."
   ```
   → `service_role` 키는 **절대 넣지 마세요** (RLS를 통째로 우회합니다)
5. `requirements.txt` 의 `supabase` 가 반영되도록 재배포
            """
        )


def _render_auth(client):
    """로그인 / 회원가입 폼."""
    st.markdown("#### 🔐 로그인")
    st.caption(
        "비밀번호는 Supabase Auth 가 관리합니다 — 이 앱은 비밀번호를 저장하지도, 볼 수도 없습니다."
    )
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("scorecard_login_form"):
            email = st.text_input("이메일", key="scorecard_login_email")
            password = st.text_input("비밀번호", type="password", key="scorecard_login_pw")
            submitted = st.form_submit_button("로그인")
        if submitted:
            try:
                response = sign_in(client, email.strip(), password)
            except ScorecardError as exc:
                st.error(f"🚫 {exc}")
            else:
                user = getattr(response, "user", None)
                if user is None:
                    st.error("🚫 로그인에 실패했습니다(사용자 정보를 받지 못했습니다).")
                else:
                    st.session_state[SESSION_USER_KEY] = user
                    st.rerun()

    with tab_signup:
        st.info(
            "가입 시 참고 — 1년 이상 접속하지 않은 계정의 데이터는 나중에 정리될 수 있습니다. "
            "(v1은 안내만 하고 자동 삭제 기능은 아직 없습니다.)"
        )
        with st.form("scorecard_signup_form"):
            email = st.text_input("이메일", key="scorecard_signup_email")
            password = st.text_input(
                "비밀번호", type="password", key="scorecard_signup_pw",
            )
            st.caption("8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.")
            password2 = st.text_input("비밀번호 확인", type="password", key="scorecard_signup_pw2")
            submitted = st.form_submit_button("회원가입")
        if submitted:
            if password != password2:
                st.error("🚫 비밀번호가 서로 다릅니다.")
            else:
                try:
                    sign_up(client, email.strip(), password)
                except ScorecardError as exc:
                    st.error(f"🚫 {exc}")
                else:
                    st.success(
                        "✅ 가입 요청이 접수되었습니다. 이메일 인증이 켜져 있으면 받은 메일함을 "
                        "확인한 뒤 로그인 탭에서 로그인해 주세요."
                    )


# =============================================================================
# 2. 보유 종목 입력
# =============================================================================
def _render_input_form(client, user_id, holdings):
    st.markdown("#### ✍️ 보유 종목 입력")
    st.caption(
        "같은 종목을 여러 번 입력하면(증권사 계좌가 여러 개인 경우) 삭제·덮어쓰기가 아니라 "
        "**수량 가중평균**으로 매입가가 다시 계산됩니다. "
        "예) 10주 100,000원 + 3주 70,000원 → 13주 평균 93,076원"
    )
    with st.form("scorecard_add_form"):
        col1, col2 = st.columns([1, 2])
        with col1:
            market = st.radio(
                "시장", [MARKET_KR, MARKET_US],
                format_func=lambda m: MARKET_LABELS[m],
                key="scorecard_market",
                help="통화는 시장에서 자동으로 정해집니다(한국=원, 미국=달러). 환율 변환은 하지 않습니다.",
            )
        with col2:
            ticker = st.text_input(
                "종목코드 / 티커",
                key="scorecard_ticker",
                help="한국은 6자리 종목코드(예: 005930), 미국은 티커(예: NVDA)를 입력하세요.",
            )
            stock_name = st.text_input("종목명 (선택)", key="scorecard_name")
        col3, col4 = st.columns(2)
        with col3:
            quantity = st.number_input(
                "수량", min_value=0.0, value=0.0, step=1.0, format="%.6f",
                key="scorecard_qty",
            )
        with col4:
            price = st.number_input(
                "매입가 (1주당)", min_value=0.0, value=0.0, step=1.0, format="%.6f",
                key="scorecard_price",
                help="총 매입금액이 아니라 **1주당 매입 단가**입니다.",
            )
        submitted = st.form_submit_button("➕ 추가 / 평균단가 재계산")

    if not submitted:
        return False
    if not ticker.strip():
        st.error("🚫 종목코드/티커를 입력해 주세요.")
        return False
    if quantity <= 0:
        st.error("🚫 수량은 0보다 커야 합니다.")
        return False
    try:
        action, merged = add_lot(
            client, user_id, market, ticker, quantity, price,
            stock_name=stock_name, holdings=holdings,
        )
    except (ScorecardError, ValueError) as exc:
        st.error(f"🚫 저장하지 못했습니다: {exc}")
        return False

    currency = merged["currency"]
    if action == "merge":
        st.success(
            f"✅ 기존 보유분과 합쳐 평균단가를 다시 계산했습니다 — "
            f"{merged['ticker']} {merged['quantity']:,.6g}주 / "
            f"평균 {format_amount(merged['avg_purchase_price'], currency)}"
        )
    else:
        st.success(f"✅ {merged['ticker']} 을(를) 추가했습니다.")
    return True


# =============================================================================
# 3. 표 / 차트 / 밸류에이션 연동
# =============================================================================
def _row_label(row):
    name = row.get("stock_name")
    return f"{name} ({row['ticker']})" if name else row["ticker"]


def _render_currency_block(client, user_id, group, indexes):
    currency = group["currency"]
    st.markdown(f"### {CURRENCY_TITLES.get(currency, currency)}")

    rows = group["rows"]
    if not rows:
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("매입원가 합계", format_amount(group["total_cost"], currency))
    if group["total_value"] is not None:
        col2.metric("평가금액 합계", format_amount(group["total_value"], currency))
        profit = group["total_profit"]
        base = group["total_cost_priced"]
        pct = f"{profit / base * 100:+.2f}%" if base else "—"
        col3.metric("평가손익", format_amount(profit, currency), pct)
    else:
        col2.metric("평가금액 합계", "—")
        col3.metric("평가손익", "—")
    if group["unpriced_count"]:
        st.info(
            f"ℹ️ {group['unpriced_count']}개 종목은 현재가를 알 수 없어(유니버스 밖 또는 수집 실패) "
            f"평가금액·비중 계산에서 빠졌습니다: {', '.join(group['unpriced_tickers'])}. "
            "v1은 상위 200(한국)/550(미국) 밖 종목의 시세를 조회하지 않습니다 — 추정하지 않고 비웁니다."
        )

    # ---- 표 -----------------------------------------------------------------
    table = []
    for row in rows:
        table.append({
            "종목": _row_label(row),
            "수량": f"{row['quantity']:,.6g}",
            "평균매입가": format_amount(row["avg_purchase_price"], currency),
            "현재가": format_amount(row["current_price"], currency) if row["price_available"] else "현재가 없음",
            "평가금액": format_amount(row["market_value"], currency) if row["price_available"] else "—",
            "평가손익": format_amount(row["profit"], currency) if row["price_available"] else "—",
            "수익률": f"{row['profit_pct']:+.2f}%" if row.get("profit_pct") is not None else "—",
            "비중": f"{row['weight_pct']:.1f}%" if row.get("weight_pct") is not None else "—",
        })
    st.dataframe(table, use_container_width=True, hide_index=True)

    # ---- 원형차트 2종 --------------------------------------------------------
    priced = [r for r in rows if r["price_available"]]
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("**보유 비중 (평가금액 기준)**")
        if not priced:
            st.caption("현재가를 아는 종목이 없어 비중 차트를 그릴 수 없습니다.")
        elif PLOTLY_AVAILABLE:
            fig = px.pie(
                names=[_row_label(r) for r in priced],
                values=[r["market_value"] for r in priced],
                hole=0.35,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:  # pragma: no cover
            st.dataframe(
                [{"종목": _row_label(r), "비중(%)": round(r["weight_pct"], 2)} for r in priced],
                use_container_width=True, hide_index=True,
            )

    with chart_col2:
        st.markdown("**수익 비중 (이익이 난 종목만)**")
        gainers = [r for r in priced if r.get("profit") and r["profit"] > 0]
        if not gainers:
            st.caption("이익이 난 종목이 없어 수익 비중 차트를 그릴 수 없습니다.")
        elif PLOTLY_AVAILABLE:
            fig = px.pie(
                names=[_row_label(r) for r in gainers],
                values=[r["profit"] for r in gainers],
                hole=0.35,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:  # pragma: no cover
            st.dataframe(
                [{"종목": _row_label(r), "수익비중(%)": round(r["profit_share_pct"], 2)}
                 for r in gainers],
                use_container_width=True, hide_index=True,
            )
        losers = [r for r in priced if r.get("profit") is not None and r["profit"] <= 0]
        if losers:
            st.caption(
                "⚠️ 손실 종목은 원형차트에 음수 조각으로 넣을 수 없어 제외했습니다 — "
                + ", ".join(f"{_row_label(r)} {format_amount(r['profit'], currency)}" for r in losers)
            )

    # ---- "사실 이 가격이에요" 연동 -------------------------------------------
    st.markdown("**💡 사실 이 가격이에요 — 밸류에이션 요약**")
    st.caption(
        "Streamlit 은 표 안에 마우스오버 툴팁을 붙일 수 없어, 종목을 고르면 카드로 보여주는 방식으로 만들었습니다."
    )
    labels = {_row_label(r): r for r in rows}
    picked = st.selectbox(
        "종목 선택", list(labels.keys()), key=f"scorecard_pick_{currency}",
    )
    row = labels[picked]
    summary = valuation_summary(row["market"], row["ticker"], indexes)
    if not summary.get("found"):
        st.info(f"ℹ️ 밸류에이션 정보 없음 — {summary.get('reason')}")
    elif not summary.get("verified"):
        st.warning(f"⚠️ 이 종목은 수집 검증을 통과하지 못했습니다 — {summary.get('reason')}")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재가", format_amount(summary.get("price"), currency))
        c2.metric("Trailing PEGY", f"{summary['t_pegy']:.2f}" if summary.get("t_pegy") is not None else "—")
        c3.metric("Forward PEGY", f"{summary['f_pegy']:.2f}" if summary.get("f_pegy") is not None else "—")
        score, score_max = summary.get("quant_score"), summary.get("score_max")
        c4.metric("퀀트 점수", f"{score} / {score_max}" if score is not None and score_max else "—")
        if summary.get("badge"):
            st.markdown(f"**판정:** {summary['badge']}")
        target_bits = []
        if summary.get("t_fair") is not None:
            target_bits.append(f"Trailing 적정가 {format_amount(summary['t_fair'], currency)}")
        if summary.get("f_target") is not None:
            target_bits.append(f"Forward 목표가 {format_amount(summary['f_target'], currency)}")
        if target_bits:
            st.markdown(" · ".join(target_bits))
        st.caption(
            f"내 평균매입가 {format_amount(row['avg_purchase_price'], currency)} vs "
            f"현재가 {format_amount(summary.get('price'), currency)} — "
            "판단은 각자의 몫입니다(매수/매도 권유가 아닙니다)."
        )
        if summary.get("data_issues"):
            with st.expander("이 종목 수집 시 남은 경고"):
                for issue in summary["data_issues"]:
                    st.markdown(f"- {issue}")

    # ---- 삭제 ----------------------------------------------------------------
    with st.expander("🗑️ 보유 종목 삭제"):
        target = st.selectbox(
            "삭제할 종목", list(labels.keys()), key=f"scorecard_del_{currency}",
        )
        if st.button("삭제", key=f"scorecard_del_btn_{currency}"):
            row_to_delete = labels[target]
            if not row_to_delete.get("id"):
                st.error("🚫 삭제할 행의 id 를 알 수 없습니다.")
            else:
                try:
                    delete_holding(client, user_id, row_to_delete["id"])
                except ScorecardError as exc:
                    st.error(f"🚫 {exc}")
                else:
                    st.success("✅ 삭제했습니다.")
                    st.rerun()


# =============================================================================
# 4. 메인 렌더러
# =============================================================================
def render_scorecard_page():
    st.markdown("## 📊 내 성적표")
    st.warning(
        "🚧 **개발 중인 화면입니다(스테이징).** 오너 승인 전까지 공개 메뉴에 노출되지 않습니다. "
        "입력한 데이터는 Supabase 에 저장되며, 본인만 조회할 수 있도록 DB 정책(RLS)이 걸려 있습니다."
    )
    st.info(NO_FX_CONVERSION_NOTICE)

    status = supabase_status()
    if not status.available:
        _render_not_ready(status)
        return

    try:
        client = _get_client()
    except ScorecardError as exc:
        st.error(f"🚫 {exc}")
        return
    if client is None:
        _render_not_ready(supabase_status())
        return

    user = st.session_state.get(SESSION_USER_KEY) or current_user(client)
    if user is None:
        _render_auth(client)
        return
    st.session_state[SESSION_USER_KEY] = user

    user_id = user_id_of(user)
    if not user_id:
        st.error("🚫 로그인 정보에서 사용자 ID를 찾지 못했습니다. 다시 로그인해 주세요.")
        return

    email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
    top_left, top_right = st.columns([3, 1])
    top_left.caption(f"로그인: {email or user_id}")
    if top_right.button("로그아웃", key="scorecard_logout"):
        try:
            sign_out(client)
        except ScorecardError as exc:
            st.error(f"🚫 {exc}")
        st.session_state.pop(SESSION_USER_KEY, None)
        st.session_state.pop(SESSION_CLIENT_KEY, None)
        st.rerun()

    try:
        holdings = fetch_holdings(client, user_id)
    except ScorecardError as exc:
        st.error(f"🚫 {exc}")
        return

    if _render_input_form(client, user_id, holdings):
        st.rerun()

    if not holdings:
        st.info("아직 등록한 보유 종목이 없습니다. 위 입력창에서 추가해 주세요.")
        return

    # 기존 스냅샷(읽기 전용) 로드 — 현재가·밸류에이션의 유일한 출처입니다.
    kr_index, kr_meta = load_universe_index(MARKET_KR)
    us_index, us_meta = load_universe_index(MARKET_US)
    indexes = {MARKET_KR: kr_index, MARKET_US: us_index}
    stamps = []
    if kr_meta and kr_meta.get("last_updated_at"):
        stamps.append(f"한국 {kr_meta['last_updated_at']}")
    if us_meta and us_meta.get("last_updated_at_kst"):
        stamps.append(f"미국 {us_meta['last_updated_at_kst']} (KST)")
    if stamps:
        st.caption("현재가 기준 스냅샷: " + " · ".join(stamps) + " — 실시간 시세가 아닙니다.")
    if not kr_index and not us_index:
        st.error(
            "🚫 밸류에이션 스냅샷(data/*.json)을 읽지 못했습니다. 현재가·수익률을 계산할 수 없습니다."
        )

    portfolio = build_portfolio(holdings, make_price_lookup(indexes))
    for currency in ("KRW", "USD"):
        group = portfolio.get(currency)
        if group:
            _render_currency_block(client, user_id, group, indexes)
            st.markdown("---")
