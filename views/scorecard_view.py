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

import html
import os

import streamlit as st

from utils.company_names_kr import resolve_korean_name
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
    load_us_all_market_prices,
    load_us_all_etf_prices,
    make_price_lookup,
    reset_password_with_code,
    resolve_stock_query,
    send_password_reset_code,
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

# 2026-08-13 오너 요청(비밀번호 찾기) — 1단계에서 코드를 보낸 이메일을 2단계 화면이 그대로
# 이어받기 위한 임시 보관 키입니다. **위젯 키가 아니라 평범한 값**이라 여기에 대입해도
# Streamlit 위젯 규칙과 충돌하지 않습니다. 로그인 세션(SESSION_USER_KEY)과는 완전히 별개라
# 재설정 폼을 쓰든 말든 로그인 상태에 아무 영향이 없습니다.
SESSION_RESET_EMAIL_KEY = "scorecard_reset_target_email"

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


def _new_auth_client():
    """
    비밀번호 재설정 2단계(코드 검증 → 비밀번호 변경) 전용 **1회용** Supabase 클라이언트.

    ⚠️ 왜 `_get_client()`(세션에 보관된 공용 클라이언트)를 쓰지 않는가 —
       `verify_otp()` 가 성공하면 그 클라이언트에 **재설정 대상 계정의 로그인 세션이 붙습니다.**
       공용 클라이언트에 그 일이 벌어지면, 같은 브라우저를 다른 사람과 함께 쓰는 상황에서
       기존 로그인 상태가 조용히 바뀌어 남의 보유종목을 보게 될 수 있습니다.
       그래서 이 호출에만 새 클라이언트를 만들어 넘기고(세션 상태에 저장하지 않음),
       `reset_password_with_code()` 가 끝날 때 그 세션을 로그아웃시킨 뒤 그대로 버립니다.
    """
    client = create_supabase_client()
    if client is None:
        raise ScorecardError(
            "Supabase 연결이 준비되지 않아 비밀번호를 재설정할 수 없습니다. "
            + (supabase_status().reason or "")
        )
    return client


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
6. Supabase → Authentication → **Emails(Email Templates) → Reset Password** 본문에
   `{{ .Token }}` 추가 (비밀번호 찾기용 **재설정 코드**. 기본 템플릿에는 링크만 있어서
   이 한 줄이 없으면 사용자가 입력할 코드가 메일에 안 옵니다. 문서엔 "6자리"라고
   적혀 있지만 실측 결과 8자리로 오기도 합니다 — 화면 쪽 검증은 자리수를 고정하지 않습니다)
            """
        )


def _render_auth(client):
    """로그인 / 회원가입 / 비밀번호 찾기 폼."""
    st.markdown("#### 🔐 로그인")
    st.caption(
        "비밀번호는 Supabase Auth 가 관리합니다 — 이 앱은 비밀번호를 저장하지도, 볼 수도 없습니다."
    )
    tab_login, tab_signup, tab_reset = st.tabs(["로그인", "회원가입", "비밀번호 찾기"])

    with tab_login:
        with st.form("scorecard_login_form"):
            email = st.text_input("이메일", key="scorecard_login_email")
            password = st.text_input("비밀번호", type="password", key="scorecard_login_pw")
            submitted = st.form_submit_button("로그인")
        # 2026-08-13 오너 요청 — 비밀번호를 잊었을 때 새 계정을 또 만들지 않도록, 로그인 탭
        # 안에서 바로 재설정 탭으로 안내합니다(로그인 ID는 이메일 자체라 '아이디 찾기'는 없습니다).
        st.caption(
            "🔑 비밀번호를 잊으셨나요? 새 계정을 만들지 마시고 위 **비밀번호 찾기** 탭에서 "
            "이메일로 코드를 받아 새 비밀번호를 정하세요 — 기존에 입력한 보유 종목이 "
            "그대로 남습니다."
        )
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

    # -------------------------------------------------------------------------
    # 비밀번호 찾기(재설정) — 2026-08-13 오너 요청, TASK_HISTORY #109
    #
    #  로그인 ID가 이메일 자체라 '아이디 찾기'는 없고 **비밀번호 재설정**만 있습니다.
    #  링크를 누르는 방식이 아니라 **메일로 받은 코드를 직접 입력**하는 방식입니다
    #  (Streamlit 은 URL 해시 프래그먼트를 읽을 수 없어 링크 방식이 안 맞습니다 —
    #   자세한 근거는 utils/scorecard_db.py 의 'D-2' 주석 블록). ⚠️ 2026-08-13: 문서상
    #  "6자리"였지만 실측 코드가 8자리로 와서, 자리수를 고정하지 않고 범위로 검증합니다
    #  (utils/scorecard_db.py 의 PASSWORD_RESET_CODE_MIN/MAX_LENGTH 참고).
    #
    #  ⚠️ 이 탭 어디에서도 SESSION_USER_KEY(로그인 세션)를 건드리지 않습니다. 코드 검증은
    #     `_new_auth_client()` 로 만든 1회용 클라이언트에서만 일어나고 끝나면 로그아웃됩니다.
    # -------------------------------------------------------------------------
    with tab_reset:
        st.caption(
            "가입한 이메일로 **재설정 코드**를 보내드립니다. 메일에 적힌 숫자를 아래 "
            "2단계에 그대로 입력하면 새 비밀번호를 정할 수 있습니다."
        )

        st.markdown("**1단계 · 재설정 코드 받기**")
        with st.form("scorecard_reset_request_form"):
            reset_email = st.text_input("가입한 이메일", key="scorecard_reset_email")
            reset_requested = st.form_submit_button("재설정 코드 보내기")
        if reset_requested:
            address = (reset_email or "").strip()
            try:
                # 발송 요청은 로그인 세션을 만들지 않으므로 공용 클라이언트로 보내도 안전합니다.
                notice = send_password_reset_code(client, address)
            except ScorecardError as exc:
                st.error(f"🚫 {exc}")
            else:
                # ⚠️ 가입된 이메일인지 여부는 알려주지 않습니다(계정 존재 여부 유출 방지) —
                #    Supabase 도 같은 정책이라 미가입 이메일이어도 오류 없이 통과합니다.
                st.session_state[SESSION_RESET_EMAIL_KEY] = address
                st.success(f"✅ {notice}")

        st.markdown("**2단계 · 받은 코드로 새 비밀번호 정하기**")
        pending_email = st.session_state.get(SESSION_RESET_EMAIL_KEY) or ""
        with st.form("scorecard_reset_confirm_form"):
            if pending_email:
                st.caption(f"코드를 보낸 이메일: {pending_email}")
                confirm_email = pending_email
            else:
                confirm_email = st.text_input(
                    "가입한 이메일", key="scorecard_reset_email_confirm",
                )
            reset_code = st.text_input(
                "이메일로 받은 코드", key="scorecard_reset_code",
                help="메일 본문에 적힌 숫자 코드를 그대로 입력하세요. 링크를 누를 필요는 없습니다.",
            )
            new_pw = st.text_input("새 비밀번호", type="password", key="scorecard_reset_pw")
            st.caption("8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.")
            new_pw2 = st.text_input(
                "새 비밀번호 확인", type="password", key="scorecard_reset_pw2",
            )
            reset_submitted = st.form_submit_button("비밀번호 변경")
        if reset_submitted:
            try:
                reset_password_with_code(
                    _new_auth_client(), confirm_email, reset_code, new_pw, new_pw2,
                )
            except ScorecardError as exc:
                st.error(f"🚫 {exc}")
            else:
                st.session_state.pop(SESSION_RESET_EMAIL_KEY, None)
                st.success(
                    "✅ 비밀번호를 변경했습니다. 위 **로그인** 탭에서 새 비밀번호로 로그인해 주세요."
                )


# DB 컬럼이 `numeric(20, 6)` 이라 정수부는 14자리까지만 들어갑니다
# (sql/scorecard_schema.sql — 전체 20자리 중 소수점 아래 6자리). 즉 저장 가능한 최대값은
# 99,999,999,999,999.999999 이고, 그보다 큰 값을 넣으면 Postgres 가 `numeric field overflow`
# 로 거절합니다. 그 거절 문구를 사용자에게 그대로 보여주는 대신, 화면 단계에서 먼저 막고
# 한국어로 설명합니다. 이 상수는 DB 정의에서 그대로 유도한 값이지 임의로 정한 값이 아닙니다.
MAX_INPUT_VALUE = 10 ** 14  # 이 값 **이상**은 저장 불가


def _parse_positive_number(raw, label):
    """
    텍스트 입력 → 양수 float. 콤마(1,664,333)와 앞뒤 공백을 허용합니다.
    ⚠️ 값을 지어내지 않습니다 — 비어있거나 숫자가 아니면 그대로 예외를 던집니다.

    🔐 2026-08-13 공개 전환 전 점검에서 보강 — 공개되면 불특정 다수가 아무 문자열이나 넣습니다.
    기존에는 `float()` 성공 + `> 0` 만 봤는데, 파이썬 `float()` 는 `"nan"` · `"inf"` ·
    `"Infinity"` · `"1e400"`(→ inf) 을 **모두 성공적으로 파싱**합니다. 그리고 `nan <= 0` 과
    `inf <= 0` 은 둘 다 거짓이라 이 함수의 양수 검사를 그냥 통과해버렸습니다. 그 뒤는:
      · 추가(➕) 경로 — `utils/scorecard_db.make_lot()` 안의 `_positive_number()` 가
        `math.isfinite()` 로 걸러줘서 저장은 막혔지만, 사용자에게는 "저장하지 못했습니다:
        수량이(가) 유효한 숫자가 아닙니다: 'nan'" 처럼 한 겹 늦은 메시지가 떴습니다.
      · 수정(✏️) 경로 — `update_holding()` 은 `make_lot()` 을 거치지 않아 **검증이 아예
        없었습니다.** NaN/Infinity 가 그대로 JSON 본문에 실려 Supabase 로 나가고
        (JSON 규격에 없는 리터럴이라 서버가 거절), 사용자는 DB 원문 오류를 보게 됐습니다.
      · 매우 큰 값(예: 1e300) — 유한수라 `isfinite()` 도 통과해 DB까지 갔다가
        `numeric field overflow` 로 거절 → 역시 DB 원문 오류가 화면에 노출됐습니다.
    그래서 **사용자가 숫자를 타이핑하는 두 곳(추가 폼·수정 폼)이 공유하는 이 함수**에서
    유한성과 상한을 함께 확인합니다. 여기서 막으면 두 경로 모두 친절한 한국어 문구가 나가고,
    잘못된 값이 네트워크 밖으로 나가지도 않습니다(DB의 CHECK 제약은 그대로 최후 방어선).
    """
    text = str(raw or "").strip().replace(",", "")
    if not text:
        raise ValueError(f"{label}을(를) 입력해 주세요.")
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"{label}은(는) 숫자로 입력해 주세요: {raw!r}")
    if number != number or number in (float("inf"), float("-inf")):
        # NaN 은 자기 자신과도 다르다는 성질로 판별합니다(math.isnan 과 동일, import 불필요).
        raise ValueError(f"{label}은(는) 실제 숫자로 입력해 주세요: {raw!r}")
    if number <= 0:
        raise ValueError(f"{label}은(는) 0보다 커야 합니다.")
    if number >= MAX_INPUT_VALUE:
        raise ValueError(
            f"{label}이(가) 너무 큽니다 — 저장할 수 있는 최대값은 "
            f"{MAX_INPUT_VALUE - 1:,}(약 100조 미만)입니다: {raw!r}"
        )
    return number


def _reset_input_fields():
    """추가 성공 후 다음 입력을 위해 입력창을 비웁니다.

    ⚠️ 2026-08-11(TASK_HISTORY #85, 오푸스 리뷰로 발견) — 이전에는 텍스트 입력 3종을
    `st.session_state.pop(key, None)`으로 지우려 했지만, **pop()은 서버 쪽 상태만 지울
    뿐 브라우저에는 값이 바뀌었다고 알리지 않습니다**(Streamlit은 위젯 키에 값을 "대입"할
    때만 프런트엔드로 갱신을 내려보냅니다). 그래서 브라우저가 들고 있던 직전 입력값이
    다음 상호작용(다음 "추가" 클릭) 때 그대로 서버로 되돌아올 수 있었고, 최악의 경우 같은
    종목이 의도치 않게 중복 합산될 위험이 있었습니다(§0-1). 이걸 고치려면 "대입"이 필요한데,
    위젯이 이미 만들어진 뒤(이 함수가 불리는 시점)에는 대입이 금지돼 있어 여기서 바로 할 수
    없습니다 — 그래서 "다음 렌더 맨 앞에서 비워달라"는 표시만 남기고, 실제 대입은
    `_render_input_form()` 맨 위(위젯을 만들기 전)에서 수행합니다.

    빠른 검색 selectbox는 nonce 기반 키를 씁니다(2026-08-11, TASK_HISTORY #85) — 여기서
    nonce를 올려두면 다음 렌더에서 완전히 새 위젯 인스턴스로 그려져 항상 placeholder부터
    시작합니다. selectbox도 같은 이유(pop은 프런트에 안 알려짐)로 "추가" 버튼을 눌러도
    처리 코드에 스크립트가 도달하지 못하는 증상이 있었는데, 이건 무한 루프가 아니라
    **클릭할 때마다 재실행이 1번씩만 일어나면서 그 처리 코드 도달 전에 매번 멈추는
    현상**이었습니다(오푸스 리뷰로 정정 — Streamlit 1.50 소스 대조 확인)."""
    st.session_state["scorecard_pending_reset"] = True
    for m in (MARKET_KR, MARKET_US):
        nonce_key = f"scorecard_picker_nonce_{m}"
        st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1


# =============================================================================
# 2. 보유 종목 입력
# =============================================================================
def _consume_pending_reset():
    """`_reset_input_fields()`가 남겨둔 표시를 보고, 위젯을 만들기 **전에** 입력 필드를
    빈 값으로 되돌립니다(2026-08-11, TASK_HISTORY #85). 위젯이 이미 만들어진 뒤에는
    session_state 대입이 금지돼 있고, 대입이라야 프런트엔드까지 실제로 전달되므로
    (`_reset_input_fields()` 문서 참고), 반드시 `_render_input_form()`이 위젯을 하나도
    만들기 전에 호출해야 합니다. 표시가 없으면 아무 일도 하지 않습니다."""
    if not st.session_state.pop("scorecard_pending_reset", False):
        return
    st.session_state["scorecard_query"] = ""
    st.session_state["scorecard_qty"] = ""
    st.session_state["scorecard_price"] = ""


def _render_input_form(client, user_id, holdings, indexes, broad_kr_index=None):
    _consume_pending_reset()

    flash = st.session_state.pop("scorecard_flash", None)
    if flash:
        (st.success if flash["kind"] == "success" else st.error)(flash["text"])

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
        # ⚠️ 2026-08-11(TASK_HISTORY #85, 오푸스 리뷰로 원인 정확히 확인) — 고정된 키
        # (`scorecard_picker_{market}`)를 `pop()`만 하고 재사용하면, **pop()은 서버 쪽
        # 상태만 지울 뿐 브라우저에는 값이 바뀌었다고 알리지 않습니다**(Streamlit은 위젯
        # 키에 값을 "대입"할 때만 프런트엔드에 갱신을 내려보냅니다 — `set_value` 플래그는
        # `is_new_state_value`가 참일 때만 켜지고, 이건 대입에서만 참이 됩니다). 그래서
        # 브라우저가 들고 있던 "선택된 값"이 다음 상호작용(예: "추가" 버튼 클릭) 때 그대로
        # 서버로 되돌아왔습니다. 이 값이 되돌아오면 `picked != picker_placeholder`가 다시
        # 참이 되어 이 블록이 또 `st.rerun()`을 걸어버리므로, **클릭할 때마다 재실행이
        # 딱 1번씩 일어나면서도 그 아래 "추가" 버튼 처리 코드에는 매번 도달하지 못하고
        # 멈추는 현상**이었습니다(무한 루프가 아니라 클릭이 조용히 씹히는 현상 — 버튼을
        # 눌러도 반응이 없던 실사용 버그의 정확한 원인).
        # nonce를 키에 포함시켜 선택을 소비할 때마다 완전히 새로운 위젯 인스턴스(다른
        # element id)를 만들면, 이전 위젯은 서버·브라우저 양쪽에서 비활성 처리돼 정리되고
        # 새 위젯은 애초에 프런트에 값이 없어 항상 placeholder부터 시작합니다.
        picker_nonce_key = f"scorecard_picker_nonce_{market}"
        picker_nonce = st.session_state.get(picker_nonce_key, 0)
        picker_key = f"scorecard_picker_{market}_{picker_nonce}"
        # 2026-08-13 오너 지적 — 미국 종목을 티커("XOM")로 검색했더니 관련 없는 회사 이름들이
        # 잔뜩 나옴. 원인: 후보 라벨에 **종목명만** 들어있고 티커가 아예 없었던 탓에, Streamlit
        # selectbox의 내장 필터가 "X, O, M이 이 순서로 어딘가에 등장하는지"만 보는 퍼지(fuzzy)
        # 매칭이라 "eXpress cOMpany"처럼 우연히 순서가 맞는 이름들까지 걸려버렸던 것 — 진짜
        # 티커 일치가 아니었습니다. 라벨을 "티커 · 종목명"으로 바꿔 티커 자체를 검색 대상 텍스트에
        # 포함시키면, 티커를 그대로 치면 라벨 맨 앞부터 정확히 일치해 최상단에 뜨고, 이름을 쳐도
        # 여전히 그대로 찾아집니다(§0-1 — 후보는 실제 유니버스에서만 뽑으므로 지어낸 게 아님).
        candidate_map = {}  # 화면에 보이는 라벨 -> 실제로 입력칸에 채워줄 값(티커/코드)
        for ticker, stock in (indexes.get(market) or {}).items():
            name = stock.get("name")
            if name:
                candidate_map[f"{ticker} · {name}"] = ticker
        if market == MARKET_KR and broad_kr_index:
            for code, stock in broad_kr_index.items():
                name = stock.get("name")
                if name:
                    candidate_map.setdefault(f"{code} · {name}", code)
        picker_scope_label = (
            "코스피·코스닥·국내ETF 전체" if market == MARKET_KR and broad_kr_index
            else "상위 200/550 종목만"
        )
        picked = st.selectbox(
            f"종목 빠른 검색 ({picker_scope_label} — 그 밖은 아래 칸에 코드를 직접 입력)",
            [picker_placeholder] + sorted(candidate_map.keys()),
            key=picker_key,
        )
        if picked != picker_placeholder:
            st.session_state["scorecard_query"] = candidate_map[picked]
            st.session_state[picker_nonce_key] = picker_nonce + 1
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
        flash_text = (
            f"{prefix}✅ 기존 보유분과 합쳐 평균단가를 다시 계산했습니다 — "
            f"{merged['ticker']} {merged['quantity']:,.6g}주 / "
            f"평균 {format_amount(merged['avg_purchase_price'], currency)}"
        )
    else:
        flash_text = f"{prefix}✅ {merged['ticker']} 을(를) 추가했습니다."
    # ⚠️ 2026-08-11(TASK_HISTORY #85, 오푸스 리뷰로 발견) — 여기서 바로 st.success()를
    # 부르면, 곧바로 호출부에서 st.rerun()이 걸려 그 메시지가 화면에 그려지기도 전에
    # 다음 렌더로 교체돼버려 사용자에게 사실상 안 보였습니다("성공 메시지가 없다"는
    # 실사용 신고와 일치). session_state에 남겨두고 다음 렌더(재실행 후) 맨 위에서
    # 그려주면 실제로 화면에 남아 보입니다.
    st.session_state["scorecard_flash"] = {"kind": "success", "text": flash_text}
    _reset_input_fields()
    return True


# =============================================================================
# 3. 표 / 차트 / 밸류에이션 연동
# =============================================================================
def _us_korean_name(row, indexes):
    """
    2026-08-13 오너 요청 — "미국주식쪽은 티커로만 표시하고 종목명을 한국어로 표기할 수
    없을까? 영어 단어보다 짧아지고 깔끔해질 것 같은데." 미국 종목은 풀네임 영문
    (예: "ExxonMobil Holdings Corporation Common Stock") 대신 한글명을 씁니다.

    공개 미국주식 화면(`views/us_stocks_view.py`)이 이미 쓰고 있는 것과 **완전히 같은 값**을
    재사용합니다 — 로직을 새로 만들지 않고 앱 전체에서 한 곳(`utils/company_names_kr.py`,
    정식 한글명 사전 우선 + 규칙 기반 자동 음역 폴백)만 단일 출처로 유지합니다. 상위 550
    유니버스 **안** 종목은 수집 시점에 미리 계산해 스냅샷에 넣어둔 `name_kr`을 그대로 읽고
    (공개 화면과 정확히 같은 표기가 보장됨), 그 유니버스 **밖**이라 스냅샷에 없는 종목만
    같은 모듈을 이 자리에서 즉석으로 호출해 보조로 만듭니다. 한글명을 전혀 못 만드는
    극히 드문 경우엔 지어내지 않고 영문명/티커로 정직하게 되돌아갑니다(§0-1).
    """
    ticker = row["ticker"]
    stock = (indexes.get(MARKET_US) or {}).get(ticker)
    if stock and stock.get("name_kr"):
        return stock["name_kr"]
    english_name = row.get("stock_name") or ticker
    result = resolve_korean_name(ticker, english_name)
    return result.get("korean_name") or result.get("english_clean") or english_name


def _display_name(row, indexes):
    """미국 종목은 한글명, 한국 종목은 기존처럼 스냅샷 종목명을 그대로 씁니다."""
    if row.get("market") == MARKET_US:
        return _us_korean_name(row, indexes)
    return row.get("stock_name")


def _row_label(row, indexes):
    name = _display_name(row, indexes)
    return f"{name} ({row['ticker']})" if name else row["ticker"]


def _row_chart_label(row, indexes):
    """
    2026-08-13 오너 요청 — 아래 원형차트(보유 비중/수익 비중) 범례에는 종목코드까지 붙어
    있으면 글자가 작고 복잡해 보여, 차트 라벨에서만 종목명만 쓰도록 분리했습니다. 표
    (`_row_label_html`)·그 외 텍스트(`_row_label`)는 코드 병기를 그대로 유지합니다 —
    이 함수는 차트 전용입니다. 종목명이 없는 종목(유니버스 밖이라 이름을 못 찾은 경우)은
    지어내지 않고 코드 그대로 보여줍니다(§0-1). 미국 종목은 `_display_name()`을 거쳐
    한글명이 나오므로(위 함수 참고) 영문 풀네임보다 훨씬 짧아 범례 가독성이 좋아집니다.
    """
    name = _display_name(row, indexes)
    return name if name else row["ticker"]


def _row_label_html(row, indexes):
    """
    2026-08-11 오너 요청 — 표의 "종목" 칸에서 이름+코드를 억지로 한 줄에 구겨넣다가 옆
    "수량" 칸과 겹쳐 보이는 문제. `<br>`로 항상 "종목명 / (코드)" 두 줄로 강제 줄바꿈합니다.
    표 전체에 걸어둔 `white-space: nowrap`(2026-08-11, ✏️/🗑️ 버튼 처짐 방지용)은 **자동**
    줄바꿈만 막을 뿐이라, 이렇게 명시적으로 넣은 `<br>` 은 그대로 줄바꿈됩니다 — 두 CSS가
    서로 충돌하지 않습니다.

    2026-08-13 오너 지적 — 미국 종목은 `_display_name()`으로 한글명을 써서 훨씬 짧아졌지만
    (위 참고), 한국 ETF는 이름이 원래 길 수 있어("TIGER 미국나스닥100커버드콜(합성)" 등)
    두 줄로 나눠도 한 줄 안에서 넘칠 수 있습니다. 이 칸에만 인라인 스타일로 줄바꿈을 다시
    허용해(부모 표의 nowrap보다 우선순위가 높은 인라인 스타일이라 확실히 적용됨) 옆 칸을
    밀어내거나 잘리지 않고 필요하면 세 줄, 네 줄도 자연스럽게 접히도록 했습니다 — 다른
    칸(숫자 칸들, 버튼 처짐 방지용 nowrap)에는 전혀 영향 없습니다.

    🔐 2026-08-13 공개 전환 전 보안 점검에서 추가 — **종목명·티커를 반드시 HTML 이스케이프**
    합니다. 이 화면에서 `unsafe_allow_html=True` 로 DB 값을 그리는 곳은 여기 한 군데뿐입니다
    (나머지 한 곳은 통화코드만 들어가는 표 전용 <style> 블록이라 사용자 입력이 닿지 않습니다).
    정상 경로에서는 종목명이 우리 수집 스냅샷(`data/*.json`)에서만 오므로 HTML이 섞일 일이
    없지만, `holdings.stock_name` 은 **DB에 저장되는 사용자 소유 컬럼**이고 Supabase 는
    설계상 anon key + 로그인 JWT 로 REST 를 직접 호출할 수 있습니다 — 즉 로그인한 사용자가
    이 화면을 거치지 않고 자기 행의 stock_name 에 `<img src=x onerror=...>` 같은 값을 직접
    써넣는 것이 가능합니다. RLS 덕분에 그 값은 **본인 화면에만** 그려지고 남의 세션으로는
    절대 넘어가지 않지만(→ 남을 공격하는 XSS는 아님), 본인 세션에서 실행되는 스크립트는 그
    사람의 Supabase 로그인 토큰을 훔칠 수 있어("이 문자열을 종목명에 붙여넣어 보세요" 식의
    사회공학) 그대로 두면 안 됩니다. `html.escape()` 를 거치면 그런 값은 실행되지 않고
    **글자 그대로** 보입니다. 우리가 직접 넣는 `<br>` 와 바깥 `<div>` 는 이스케이프 대상이
    아니므로 기존 두 줄 표기·줄바꿈 동작은 100% 그대로입니다.
    """
    name = _display_name(row, indexes)
    ticker = row["ticker"]
    safe_name = html.escape(str(name)) if name else None
    safe_ticker = html.escape(str(ticker))
    label = f"{safe_name}<br>({safe_ticker})" if safe_name else safe_ticker
    return f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">{label}</div>'


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


def _md_amount(value, currency, decimals=None):
    """
    마크다운 텍스트(`st.error`/`st.info`/`st.caption`/`st.markdown` 등)에 금액을 넣을 때
    전용으로 씁니다. `format_amount()`가 만드는 "$147.80" 같은 표기를 그대로 마크다운
    문자열에 두 번 이상 넣으면, Streamlit 마크다운(KaTeX)이 그 "$"와 "$" 사이를 LaTeX
    수식으로 오인해서 렌더링이 깨집니다.

    2026-08-13 오너 신고 — 미국 주식의 "내 평균매입가 VS 현재가" 배너에서 "VS" 글자가
    이상한 수식 글꼴로 겹쳐 보이던 게 바로 이 문제였습니다: "$147.80 VS $159.80" 문자열 안에
    "$"가 두 번 있어 그 사이("147.80 VS $")가 통째로 수식으로 렌더링됐던 것. 원화는 "원"
    접미사를 쓰고 "$"가 아예 없어 이 문제가 생기지 않았고, 이게 "한국 쪽보다 미국 쪽
    가독성이 떨어진다"는 신고의 실제 원인이었습니다(글꼴·간격 문제가 아니라 렌더링 버그).
    `\\$`로 이스케이프하면 화면엔 그대로 "$147.80"으로 보이면서 수식으로는 해석되지 않습니다.

    ⚠️ `st.metric`처럼 애초에 마크다운을 거치지 않는 곳(예: `c1.metric("현재가",
    format_amount(...))`)은 이 문제가 없어 그대로 `format_amount()`를 쓰면 됩니다 — 이
    함수는 마크다운 텍스트 안에 넣을 때만 씁니다.
    """
    return format_amount(value, currency, decimals).replace("$", "\\$")


def _render_currency_block(client, user_id, group, indexes, sync_label=None):
    currency = group["currency"]
    header_col, sync_col = st.columns([3, 2])
    header_col.markdown(f"### {CURRENCY_TITLES.get(currency, currency)}")
    if sync_label:
        sync_col.caption(sync_label + " — 실시간 시세가 아닙니다.")

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
            cols[0].markdown(_row_label_html(row, indexes), unsafe_allow_html=True)
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
                        st.success(f"✅ {_row_label(row, indexes)} 삭제했습니다.")
                        st.rerun()

            if st.session_state.get(edit_key):
                with st.container(border=True):
                    st.caption(
                        f"✏️ **{_row_label(row, indexes)} 수정** — 다른 계좌분과 합쳐 평균을 내는 게 아니라, "
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
                names=[_row_chart_label(r, indexes) for r in priced],
                values=[r["market_value"] for r in priced],
                hole=0.35,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:  # pragma: no cover
            st.dataframe(
                [{"종목": _row_chart_label(r, indexes), "비중(%)": round(r["weight_pct"], 2)} for r in priced],
                use_container_width=True, hide_index=True,
            )

    with chart_col2:
        st.markdown("**수익 비중 (이익이 난 종목만)**")
        gainers = [r for r in priced if r.get("profit") and r["profit"] > 0]
        if not gainers:
            st.caption("이익이 난 종목이 없어 수익 비중 차트를 그릴 수 없습니다.")
        elif PLOTLY_AVAILABLE:
            fig = px.pie(
                names=[_row_chart_label(r, indexes) for r in gainers],
                values=[r["profit"] for r in gainers],
                hole=0.35,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:  # pragma: no cover
            st.dataframe(
                [{"종목": _row_chart_label(r, indexes), "수익비중(%)": round(r["profit_share_pct"], 2)}
                 for r in gainers],
                use_container_width=True, hide_index=True,
            )
        # 2026-08-13 오너 지적 — "미국 쪽은 예쁜데 한국 쪽은 이 텍스트 때문에..." 손실 종목이
        # 여러 개(한국처럼)면 코드까지 붙은 긴 문장이 쉼표로 줄줄이 이어져 차트 바로 아래가
        # 지저분해 보였습니다. ① 차트 범례(#86)와 똑같이 이 자리도 종목코드를 빼고
        # (`_row_chart_label` 재사용 — 코드는 위 표에서 이미 확인 가능), ② 한 문장으로 몰아
        # 쓰지 않고 종목당 한 줄씩 목록으로 나눠, 손실 종목이 몇 개든 스캔하기 쉽게 했습니다.
        losers = [r for r in priced if r.get("profit") is not None and r["profit"] <= 0]
        if losers:
            loser_lines = "\n".join(
                f"- {_row_chart_label(r, indexes)} {_md_amount(r['profit'], currency)}"
                for r in losers
            )
            st.caption(
                "⚠️ 손실 종목은 원형차트에 음수 조각으로 넣을 수 없어 제외했습니다:\n\n"
                + loser_lines
            )

    # ---- "사실 이 가격이에요" 연동 -------------------------------------------
    st.markdown("**💡 사실 이 가격이에요 — 밸류에이션 요약**")
    st.caption(
        "Streamlit 은 표 안에 마우스오버 툴팁을 붙일 수 없어, 종목을 고르면 카드로 보여주는 방식으로 만들었습니다."
    )
    labels = {_row_label(r, indexes): r for r in rows}
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
        # 2026-08-13 오너 신고 — 미국 주식에서 이 배너의 "VS" 글자가 이상한 수식 글꼴로
        # 겹쳐 보임("$147.80 VS $159.80" 안에 "$"가 두 번 있어 그 사이가 LaTeX 수식으로
        # 오인됨). `_md_amount()`로 "$"를 이스케이프해 해결 — 자세한 원인은 그 함수 주석 참고.
        price = summary.get("price")
        avg_price = row.get("avg_purchase_price")
        if price is not None and avg_price:
            diff = price - avg_price
            diff_pct = (diff / avg_price) * 100
            arrow = "📈" if diff >= 0 else "📉"
            banner = st.error if diff >= 0 else st.info
            banner(
                f"{arrow} **내 평균매입가 {_md_amount(avg_price, currency)} VS "
                f"현재가 {_md_amount(price, currency)} ({diff_pct:+.2f}%)**"
            )
        else:
            st.info(
                f"내 평균매입가 {_md_amount(avg_price, currency)} vs "
                f"현재가 {_md_amount(price, currency)}"
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
    st.info(
        "🔒 입력한 데이터는 Supabase 에 저장되며, 본인만 조회할 수 있도록 DB 정책(RLS)이 걸려 있습니다."
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

    # 2026-08-12 오너 요청(TASK_HISTORY #92) — 위 한국판과 완전히 같은 역할의 미국판.
    # 미국 상위 550 밖 종목도 "현재가 없음" 대신 실제 종가를 보여줍니다. 마찬가지로 밸류에이션은
    # 없고 가격만 — `indexes`와 섞지 않고 `make_price_lookup`의 2차 폴백으로만 넘깁니다.
    us_all_prices, _us_all_prices_meta = load_us_all_market_prices()

    # 2026-08-12 오너 지시(TASK_HISTORY #93) — 미국은 ETF로 투자하는 비중도 무시할 수 없어
    # 위 '전 종목(보통주)' 목록에 **ETF 현재가 목록**을 더합니다(예: KORU 같은 ETF가 계속
    # "현재가 없음"으로 뜨던 문제). 수집기가 소스별로 파일을 나눠 저장하므로(한쪽 실패가 다른
    # 쪽을 지우지 않도록) 합치는 일은 여기서 합니다 — 미국 티커 공간에서 주식과 ETF는 겹치지
    # 않지만, 만에 하나 겹치면 보통주 쪽을 우선합니다. ETF 파일이 아직 없으면 아무 일도 일어나지
    # 않고 이전과 똑같이 동작합니다. ⚠️ 여기서도 넘어가는 건 **가격뿐**이라 밸류에이션 문구
    # ("밸류에이션 정보 없음")는 ETF에서 그대로 정확합니다.
    us_etf_prices, _us_etf_prices_meta = load_us_all_etf_prices()
    if us_etf_prices:
        us_all_prices = {**us_etf_prices, **us_all_prices}

    if _render_input_form(client, user_id, holdings, indexes, kr_ticker_master):
        st.rerun()

    if not holdings:
        st.info("아직 등록한 보유 종목이 없습니다. 위 입력창에서 추가해 주세요.")
        return

    if not kr_index and not us_index:
        st.error(
            "🚫 밸류에이션 스냅샷(data/*.json)을 읽지 못했습니다. 현재가·수익률을 계산할 수 없습니다."
        )

    # 2026-08-13 오너 요청 — "한국 주식"/"미국 주식" 소제목 옆에 그 시장 현재가가 언제
    # 수집됐는지 바로 보이면 좋겠다는 피드백. 통합 캡션 하나로 맨 위에 몰아 보여주던 걸
    # 시장별로 나눠 각 소제목 바로 아래에 붙입니다.
    # ⚠️ 초(seconds) 단위는 표시하지 않습니다 — 수집기(collector_kospi200.py /
    # collector_us_stocks.py)의 `last_updated_at`/`last_updated_at_kst` 메타데이터 자체가
    # 분 단위까지만 기록합니다(초 단위 타임스탬프를 저장하지 않음). 없는 정밀도를 있는
    # 것처럼 ':00'을 붙여 지어내지 않습니다(§0-1) — 초 단위가 꼭 필요하면 수집기 쪽
    # 타임스탬프 포맷 자체를 바꿔야 합니다.
    SYNC_LABELS = {
        "KRW": (f"현재가 : {kr_meta['last_updated_at']} 기준" if kr_meta and kr_meta.get("last_updated_at") else None),
        "USD": (f"현재가 : {us_meta['last_updated_at_kst']} 기준 (KST)" if us_meta and us_meta.get("last_updated_at_kst") else None),
    }

    portfolio = build_portfolio(
        holdings,
        make_price_lookup(indexes, broad_kr_prices=kr_all_prices, broad_us_prices=us_all_prices),
    )
    for currency in ("KRW", "USD"):
        group = portfolio.get(currency)
        if group:
            _render_currency_block(client, user_id, group, indexes, SYNC_LABELS.get(currency))
            st.markdown("---")
