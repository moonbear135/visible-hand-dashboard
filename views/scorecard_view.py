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
    NO_FEES_TAXES_NOTICE,
    NO_FX_CONVERSION_NOTICE,
    ScorecardError,
    add_lot,
    build_portfolio,
    create_supabase_client,
    current_user,
    delete_holding,
    fetch_holdings,
    format_amount,
    load_kr_ticker_master,
    load_kr_all_market_prices,
    load_universe_index,
    make_price_lookup,
    resolve_stock_query,
    sign_in,
    sign_out,
    sign_up,
    sort_holding_rows,
    SORT_FIELD_OPTIONS,
    supabase_status,
    update_holding,
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


def _parse_positive_number(raw, label):
    """
    텍스트 입력 → 양수 float. 콤마(1,664,333)와 앞뒤 공백을 허용합니다.
    ⚠️ 값을 지어내지 않습니다 — 비어있거나 숫자가 아니면 그대로 예외를 던집니다.
    """
    text = str(raw or "").strip().replace(",", "")
    if not text:
        raise ValueError(f"{label}을(를) 입력해 주세요.")
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"{label}은(는) 숫자로 입력해 주세요: {raw!r}")
    if number <= 0:
        raise ValueError(f"{label}은(는) 0보다 커야 합니다.")
    return number


def _reset_input_fields():
    """추가 성공 후 다음 입력을 위해 입력창을 비웁니다(직전 값이 계속 남아있던 버그 수정,
    2026-08-11). st.rerun() 전에 session_state 키를 지워야 다음 렌더에서 빈 값으로 시작합니다.
    빠른 검색 selectbox(시장별로 키가 다름, `scorecard_picker_{market}`)도 함께 비웁니다."""
    for key in ("scorecard_query", "scorecard_qty", "scorecard_price",
                f"scorecard_picker_{MARKET_KR}", f"scorecard_picker_{MARKET_US}"):
        st.session_state.pop(key, None)


# =============================================================================
# 2. 보유 종목 입력
# =============================================================================
def _render_input_form(client, user_id, holdings, indexes, broad_kr_index=None):
    st.markdown("#### ✍️ 보유 종목 입력")
    st.caption(
        "같은 종목을 여러 번 입력하면(증권사 계좌가 여러 개인 경우) 삭제·덮어쓰기가 아니라 "
        "**수량 가중평균**으로 매입가가 다시 계산됩니다. "
        "예) 10주 100,000원 + 3주 70,000원 → 13주 평균 93,076원"
    )
    # ⚠️ 2026-08-11: 일부러 st.form 을 쓰지 않습니다 — st.form 안에서는 Enter 키가 곧바로
    # "제출" 버튼을 누른 것과 같이 동작해서, 다음 종목을 입력하려고 습관적으로 Enter를 치면
    # 그때까지 입력한 값이 그대로 추가돼버리는 사고가 실사용 중 확인됐습니다. 폼을 쓰지 않으면
    # Enter는 그 입력창의 값만 확정할 뿐 아무것도 제출하지 않고, 아래 버튼을 실제로 눌러야만
    # 추가됩니다.
    col1, col2 = st.columns([1, 2])
    with col1:
        market = st.radio(
            "시장", [MARKET_KR, MARKET_US],
            format_func=lambda m: MARKET_LABELS[m],
            key="scorecard_market",
            help="통화는 시장에서 자동으로 정해집니다(한국=원, 미국=달러). 환율 변환은 하지 않습니다.",
        )
    with col2:
        # 2026-08-11 오너 요청 — "롯데까지만 쳐도 관련 종목이 좌르르 나오게" 해달라는 요청.
        # Streamlit selectbox는 클릭 후 타이핑하면 옵션을 그 자리에서 자동으로 필터링해주는
        # 내장 기능이 있어(별도 자바스크립트·API 호출 없이) 이걸로 "이름 일부만 쳐도 후보가
        # 좌르르 나오는" 빠른 검색을 만듭니다. 후보는 §0-1대로 실제 상장종목 목록에서만 뽑습니다.
        # 한국은 코스피 상위 200 유니버스 + 전체 상장종목 마스터(코스피·코스닥·ETF, TASK_HISTORY
        # #83)를 합쳐서 훨씬 넓게 찾을 수 있고, 미국은 아직 상위 550까지만(추가 마스터 목록 없음).
        picker_placeholder = "🔍 이름 일부만 쳐도 후보가 나옵니다 (선택하면 아래 칸에 자동 입력)"
        picker_key = f"scorecard_picker_{market}"
        candidate_names = {
            stock.get("name") for stock in (indexes.get(market) or {}).values()
            if stock.get("name")
        }
        if market == MARKET_KR and broad_kr_index:
            candidate_names |= {
                stock.get("name") for stock in broad_kr_index.values() if stock.get("name")
            }
        picker_scope_label = (
            "코스피·코스닥·국내ETF 전체" if market == MARKET_KR and broad_kr_index
            else "상위 200/550 종목만"
        )
        picked = st.selectbox(
            f"종목 빠른 검색 ({picker_scope_label} — 그 밖은 아래 칸에 코드를 직접 입력)",
            [picker_placeholder] + sorted(candidate_names),
            key=picker_key,
        )
        if picked != picker_placeholder:
            st.session_state["scorecard_query"] = picked
            st.session_state.pop(picker_key, None)
            st.rerun()

        # ⚠️ 2026-08-11 오너 지시: "종목코드 / 티커 / 종목명 이게 전부 다 한곳에서 기능할 수
        # 있게 해야지" — 코드를 쳐도, 이름을 쳐도(한글 포함) 한 칸에서 알아서 찾습니다.
        # 유니버스 밖 종목은 코드를 알면 그대로 받아들여서 "현재가 없음"으로 정직하게 표시합니다.
        query = st.text_input(
            "종목 (종목코드 / 티커 / 종목명 — 아무거나 입력하세요)",
            key="scorecard_query",
            placeholder="예: 005930 또는 삼성전자" if market == MARKET_KR else "예: NVDA 또는 NVIDIA",
            help="종목코드를 아시면 코드로, 모르시면 이름으로 입력하세요 — 둘 다 자동으로 찾아드립니다.",
        )
    col3, col4 = st.columns(2)
    with col3:
        quantity_raw = st.text_input(
            "수량", key="scorecard_qty", placeholder="예: 10",
        )
    with col4:
        price_raw = st.text_input(
            "매입가 (1주당)", key="scorecard_price", placeholder="예: 70,000",
            help="총 매입금액이 아니라 **1주당 매입 단가**입니다. 콤마(,)를 넣어 입력해도 됩니다.",
        )
    submitted = st.button("➕ 추가 / 평균단가 재계산", key="scorecard_add_btn")

    if not submitted:
        return False

    resolved_ticker, resolved_name, resolve_error = resolve_stock_query(
        market, query, indexes,
        broad_index=broad_kr_index if market == MARKET_KR else None,
    )
    if not resolved_ticker:
        st.error(f"🚫 {resolve_error}")
        return False
    lookup_note = f"{resolved_name} ({resolved_ticker}) 로 인식했습니다." if resolved_name else None

    try:
        quantity = _parse_positive_number(quantity_raw, "수량")
        price = _parse_positive_number(price_raw, "매입가")
    except ValueError as exc:
        st.error(f"🚫 {exc}")
        return False

    try:
        action, merged = add_lot(
            client, user_id, market, resolved_ticker, quantity, price,
            stock_name=resolved_name, holdings=holdings,
        )
    except (ScorecardError, ValueError) as exc:
        st.error(f"🚫 저장하지 못했습니다: {exc}")
        return False

    currency = merged["currency"]
    prefix = f"ℹ️ {lookup_note}\n\n" if lookup_note else ""
    if action == "merge":
        st.success(
            f"{prefix}✅ 기존 보유분과 합쳐 평균단가를 다시 계산했습니다 — "
            f"{merged['ticker']} {merged['quantity']:,.6g}주 / "
            f"평균 {format_amount(merged['avg_purchase_price'], currency)}"
        )
    else:
        st.success(f"{prefix}✅ {merged['ticker']} 을(를) 추가했습니다.")
    _reset_input_fields()
    return True


# =============================================================================
# 3. 표 / 차트 / 밸류에이션 연동
# =============================================================================
def _row_label(row):
    name = row.get("stock_name")
    return f"{name} ({row['ticker']})" if name else row["ticker"]


def _row_label_html(row):
    """
    2026-08-11 오너 요청 — 표의 "종목" 칸에서 이름+코드를 억지로 한 줄에 구겨넣다가 옆
    "수량" 칸과 겹쳐 보이는 문제. `<br>`로 항상 "종목명 / (코드)" 두 줄로 강제 줄바꿈합니다.
    표 전체에 걸어둔 `white-space: nowrap`(2026-08-11, ✏️/🗑️ 버튼 처짐 방지용)은 **자동**
    줄바꿈만 막을 뿐이라, 이렇게 명시적으로 넣은 `<br>` 은 그대로 줄바꿈됩니다 — 두 CSS가
    서로 충돌하지 않습니다.
    """
    name = row.get("stock_name")
    ticker = row["ticker"]
    if name:
        return f"{name}<br>({ticker})"
    return ticker


def _colored_pct(value):
    """
    2026-08-11 오너 요청 — 수익률을 국내 증시 관례대로 **오르면 빨강 / 내리면 파랑**으로
    색칠해 한눈에 들어오게 합니다(0%는 색 없이 그대로). Streamlit 마크다운의 `:red[..]`/
    `:blue[..]` 문법을 씁니다(별도 CSS·unsafe_allow_html 불필요).
    """
    if value is None:
        return "—"
    text = f"{value:+.2f}%"
    if value > 0:
        return f":red[{text}]"
    if value < 0:
        return f":blue[{text}]"
    return text


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
        # 2026-08-11 오너 지시 — 해외 관례(초록/빨강)보다 국내 증시 관례(빨강/파랑)로 화면
        # 전체를 통일. st.metric 내장 delta 색은 초록/빨강만 지원해서(파랑 옵션 없음) 끄고
        # (`delta_color="off"`), 아래 행과 같은 `_colored_pct()`로 직접 빨강/파랑을 입힙니다.
        col3.metric("평가손익", format_amount(profit, currency), delta_color="off")
        col3.markdown(_colored_pct(profit / base * 100 if base else None))
    else:
        col2.metric("평가금액 합계", "—")
        col3.metric("평가손익", "—")
    if group["unpriced_count"]:
        st.info(
            f"ℹ️ {group['unpriced_count']}개 종목은 현재가를 알 수 없어(유니버스 밖 또는 수집 실패) "
            f"평가금액·비중 계산에서 빠졌습니다: {', '.join(group['unpriced_tickers'])}. "
            "v1은 상위 200(한국)/550(미국) 밖 종목의 시세를 조회하지 않습니다 — 추정하지 않고 비웁니다."
        )

    # ---- 정렬 (2026-08-11 오너 요청) -------------------------------------------
    # 기본은 "기본순서"(추가한 순서 그대로) — 사용자가 고를 때만 정렬을 적용합니다.
    sort_col1, sort_col2 = st.columns([2, 1])
    with sort_col1:
        sort_label = st.selectbox(
            "정렬 기준",
            ["기본순서"] + [label for label, _ in SORT_FIELD_OPTIONS],
            key=f"scorecard_sort_field_{currency}",
        )
    with sort_col2:
        sort_ascending = st.radio(
            "정렬 방향", ["내림차순", "오름차순"],
            key=f"scorecard_sort_dir_{currency}", horizontal=True,
        ) == "오름차순"
    if sort_label != "기본순서":
        sort_field = dict(SORT_FIELD_OPTIONS)[sort_label]
        rows = sort_holding_rows(rows, sort_field, ascending=sort_ascending)

    # ---- 표 (종목별 ✏️ 수정 / 🗑️ 삭제 버튼 포함) -------------------------------
    # 2026-08-11: 오너 요청 — 별도 "삭제할 종목 고르기" 드롭다운 대신, 각 종목 줄
    # 바로 옆에 수정·삭제 버튼을 둡니다. 예전엔 st.dataframe 표 하나 + 화면 맨 아래
    # 접힌 삭제 전용 expander였는데("잘못 입력한 걸 고칠 방법이 없다"는 실사용
    # 피드백), 표를 직접 그리는 방식으로 바꿔 종목당 바로 옆에서 처리하게 했습니다.
    # 2026-08-11: ✏️/🗑️ 버튼이 옆 셀보다 아래로 처져 보이는 문제(오너 스크린샷으로 확인) —
    # "비중" 칸이 좁아 "100.0%"가 두 줄로 줄바꿈되면서 그 옆 버튼이 밀려 내려간 것이 원인.
    # ① 값 칸 줄바꿈을 CSS로 막고 ② 행 전체를 세로 중앙 정렬해서 어떤 경우에도 어긋나지
    # 않게 합니다. st.container(key=...) 는 Streamlit이 `.st-key-<key>` 클래스를 붙여주므로
    # 이 표에만 스코프된 CSS를 걸 수 있습니다(다른 화면·다른 표에는 영향 없음).
    table_key = f"scorecard_rows_{currency}"
    st.markdown(
        f"""
        <style>
        .st-key-{table_key} [data-testid="stHorizontalBlock"] {{ align-items: center; }}
        .st-key-{table_key} [data-testid="stMarkdownContainer"] p {{
            white-space: nowrap; margin-bottom: 0;
        }}
        /* 2026-08-11: ✏️/🗑️ 이모지가 버튼 네모칸 한가운데 오지 않고 구석에 치우쳐 보이는
           문제(오너 스크린샷으로 확인) — 버튼 내부를 flex로 완전히 중앙 정렬합니다. */
        .st-key-{table_key} button {{
            display: flex; align-items: center; justify-content: center;
        }}
        .st-key-{table_key} button p {{
            margin: 0; line-height: 1; font-size: 1.05rem;
        }}
        /* 2026-08-11 오너 지적 — 모바일처럼 화면이 좁아지면 Streamlit이 이 표의 9개 칸을
           세로로 쌓아버려서(내장 반응형 규칙) 글자가 겹쳐 보이고 표 모양이 완전히 깨집니다.
           표를 세로로 쌓는 대신 **가로 스크롤이 되는 표**로 유지되도록, 좁은 화면에서만
           칸이 안 쌓이게 강제하고(min-width로 표 전체 너비를 확보) 그 바깥을 가로로
           스크롤되게 감쌉니다. 다른 화면(입력 폼 등)은 그대로 세로로 쌓이는 게 정상입니다 —
           이 규칙은 표 영역에만 스코프되어 있습니다.
        */
        .st-key-{table_key} {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        @media (max-width: 640px) {{
            .st-key-{table_key} [data-testid="stHorizontalBlock"] {{
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                min-width: 700px;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key=table_key):
        _COL_RATIOS = [2, 1, 1.2, 1.2, 1.1, 1.0, 1.0, 0.6, 0.6]
        header_cols = st.columns(_COL_RATIOS)
        for col, label in zip(
            header_cols, ["종목", "수량", "평균매입가", "현재가", "평가손익", "수익률", "비중", "", ""]
        ):
            if label:
                col.caption(f"**{label}**")

        for row in rows:
            row_id = row.get("id")
            edit_key = f"scorecard_editing_{row_id}"
            cols = st.columns(_COL_RATIOS)
            cols[0].markdown(_row_label_html(row), unsafe_allow_html=True)
            cols[1].write(f"{row['quantity']:,.6g}")
            cols[2].write(format_amount(row["avg_purchase_price"], currency))
            cols[3].write(
                format_amount(row["current_price"], currency) if row["price_available"] else "현재가 없음"
            )
            cols[4].write(format_amount(row["profit"], currency) if row["price_available"] else "—")
            cols[5].markdown(_colored_pct(row.get("profit_pct")))
            cols[6].write(f"{row['weight_pct']:.1f}%" if row.get("weight_pct") is not None else "—")
            # 2026-08-11: 이모지(✏️/🗑️)를 버튼 라벨 텍스트로 쓰면 글꼴마다 글리프 자체의
            # 여백이 삐뚤어서 CSS로 중앙 정렬해도 박스 안에서 치우쳐 보이는 문제(오너 스크린샷
            # 3연속 확인)가 있었습니다. 근본 원인이 이모지 폰트 렌더링이라 CSS로는 못 고치고,
            # Streamlit이 지원하는 `icon=` 파라미터(Material Symbols, 폰트가 아니라 일정한
            # 벡터 아이콘)로 바꿔서 항상 정중앙에 오도록 했습니다.
            if cols[7].button("", key=f"scorecard_edit_btn_{row_id}", help="수정", icon=":material/edit:"):
                st.session_state[edit_key] = not st.session_state.get(edit_key, False)
            if cols[8].button("", key=f"scorecard_del_btn_{row_id}", help="삭제", icon=":material/delete:"):
                if not row_id:
                    st.error("🚫 삭제할 행의 id 를 알 수 없습니다.")
                else:
                    try:
                        delete_holding(client, user_id, row_id)
                    except ScorecardError as exc:
                        st.error(f"🚫 {exc}")
                    else:
                        st.success(f"✅ {_row_label(row)} 삭제했습니다.")
                        st.rerun()

            if st.session_state.get(edit_key):
                with st.container(border=True):
                    st.caption(
                        f"✏️ **{_row_label(row)} 수정** — 다른 계좌분과 합쳐 평균을 내는 게 아니라, "
                        "값을 그대로 덮어씁니다(잘못 입력한 걸 바로잡을 때 사용)."
                    )
                    ecol1, ecol2, ecol3, ecol4 = st.columns([1.2, 1.2, 0.7, 0.7])
                    new_qty_raw = ecol1.text_input(
                        "수량", value=f"{row['quantity']:g}", key=f"scorecard_edit_qty_{row_id}",
                    )
                    new_price_raw = ecol2.text_input(
                        "매입가 (1주당)", value=f"{row['avg_purchase_price']:g}",
                        key=f"scorecard_edit_price_{row_id}",
                    )
                    if ecol3.button("저장", key=f"scorecard_edit_save_{row_id}"):
                        try:
                            new_qty = _parse_positive_number(new_qty_raw, "수량")
                            new_price = _parse_positive_number(new_price_raw, "매입가")
                        except ValueError as exc:
                            st.error(f"🚫 {exc}")
                        else:
                            try:
                                update_holding(client, user_id, row_id, new_qty, new_price)
                            except ScorecardError as exc:
                                st.error(f"🚫 {exc}")
                            else:
                                st.session_state[edit_key] = False
                                st.success("✅ 수정했습니다.")
                                st.rerun()
                    if ecol4.button("취소", key=f"scorecard_edit_cancel_{row_id}"):
                        st.session_state[edit_key] = False
                        st.rerun()
    st.divider()

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

        # 2026-08-11: 오너 요청 — 적정가/목표가가 너무 작게 보여서, 위 c1~c4 지표들과
        # 같은 st.metric 카드로 맞춰 눈에 띄게 키웠습니다.
        if summary.get("t_fair") is not None or summary.get("f_target") is not None:
            d1, d2 = st.columns(2)
            d1.metric(
                "Trailing 적정가",
                format_amount(summary["t_fair"], currency) if summary.get("t_fair") is not None else "—",
            )
            d2.metric(
                "Forward 목표가",
                format_amount(summary["f_target"], currency) if summary.get("f_target") is not None else "—",
            )

        # 2026-08-11: 오너 요청 — "내 평균매입가 vs 현재가" 비교를 잿빛 캡션이 아니라
        # 손익 방향에 따라 색이 바뀌는 큰 배너로 바꿔 가시성을 확실히 했습니다. 처음엔
        # 초록(오름)/빨강(내림)의 해외 관례로 만들었는데, 오너가 "국내 관례로 통일하자"고
        # 지시해서 **빨강(오름)/파랑(내림)** 으로 바꿨습니다. Streamlit에는 파랑 계열 강조
        # 박스가 `st.info` 하나뿐이라, `st.error`(빨강)=이득 / `st.info`(파랑)=손실로
        # "에러/정보"라는 원래 이름과 무관하게 **색상만 빌려 씁니다**(실제 에러가 아님에 주의).
        price = summary.get("price")
        avg_price = row.get("avg_purchase_price")
        if price is not None and avg_price:
            diff = price - avg_price
            diff_pct = (diff / avg_price) * 100
            arrow = "📈" if diff >= 0 else "📉"
            banner = st.error if diff >= 0 else st.info
            banner(
                f"{arrow} **내 평균매입가 {format_amount(avg_price, currency)} VS "
                f"현재가 {format_amount(price, currency)} ({diff_pct:+.2f}%)**"
            )
        else:
            st.info(
                f"내 평균매입가 {format_amount(avg_price, currency)} vs "
                f"현재가 {format_amount(price, currency)}"
            )
        st.caption("판단은 각자의 몫입니다(매수/매도 권유가 아닙니다).")
        if summary.get("data_issues"):
            with st.expander("이 종목 수집 시 남은 경고"):
                for issue in summary["data_issues"]:
                    st.markdown(f"- {issue}")


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
    st.info(NO_FEES_TAXES_NOTICE)

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

    # 기존 스냅샷(읽기 전용) 로드 — 현재가·밸류에이션의 유일한 출처이자, 입력 폼의
    # "이름으로 찾기"에도 쓰이므로 입력 폼을 그리기 전에 먼저 불러옵니다.
    kr_index, kr_meta = load_universe_index(MARKET_KR)
    us_index, us_meta = load_universe_index(MARKET_US)
    indexes = {MARKET_KR: kr_index, MARKET_US: us_index}

    # 2026-08-11 오너 요청(TASK_HISTORY #83) — 코스피 상위 200 밖(코스닥·ETF 포함) 종목도
    # 이름으로 찾을 수 있게 하는 보조 목록. ⚠️ 가격·밸류에이션은 없음 — 위 `indexes`와
    # 절대 섞지 않고 별도로 `_render_input_form`에 넘깁니다(scorecard_db.load_kr_ticker_master
    # 문서 참고). 파일이 아직 없으면(다음 자동 수집 전) 빈 dict — 이 화면은 그대로 정상 작동하고
    # 이름 검색 범위만 상위 200으로 좁아집니다.
    kr_ticker_master, _kr_master_meta = load_kr_ticker_master()

    # 2026-08-11 오너 요청(TASK_HISTORY #84) — 코스피 상위 200 밖 종목도 "현재가 없음" 대신
    # 실제 종가를 보여주기 위한 보조 가격 목록. ⚠️ 이것도 밸류에이션은 없고 가격만 — 위
    # `kr_ticker_master`(이름 검색용)와는 또 다른 별도 파일입니다. 파일이 아직 없으면
    # 빈 dict — 이 화면은 그대로 정상 작동하고 유니버스 밖 종목은 이전처럼 "현재가 없음"으로
    # 표시됩니다.
    kr_all_prices, _kr_all_prices_meta = load_kr_all_market_prices()

    if _render_input_form(client, user_id, holdings, indexes, kr_ticker_master):
        st.rerun()

    if not holdings:
        st.info("아직 등록한 보유 종목이 없습니다. 위 입력창에서 추가해 주세요.")
        return

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

    portfolio = build_portfolio(holdings, make_price_lookup(indexes, broad_kr_prices=kr_all_prices))
    for currency in ("KRW", "USD"):
        group = portfolio.get(currency)
        if group:
            _render_currency_block(client, user_id, group, indexes)
            st.markdown("---")
