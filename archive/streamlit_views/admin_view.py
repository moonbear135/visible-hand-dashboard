import hashlib
import hmac
import os
from datetime import datetime
import streamlit as st
from utils.db import HISTORY_FILE

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

def _get_admin_password_hash():
    """
    관리자 비밀번호 해시를 Streamlit secrets 또는 환경변수에서 읽어옵니다.
    (GEMINI_API_KEY 와 동일한 패턴 — 소스코드에 비밀번호/해시를 두지 않습니다.)

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ ⚠️ TODO(오너 조치 필요) — 2026-08-06: SHA-256 → bcrypt(솔트 포함) 전환 지원 추가│
    │                                                                          │
    │ 새 비밀번호를 bcrypt 해시로 설정하려면(권장):                             │
    │   pip install bcrypt  (requirements.txt 에 이미 추가됨, 재배포 시 자동 설치)│
    │   python -c "import bcrypt,getpass;print(bcrypt.hashpw(getpass.getpass().encode(),bcrypt.gensalt()).decode())" │
    │ 위 명령을 **본인 컴퓨터에서 직접** 실행해 새 비밀번호를 입력하세요        │
    │ (평문 비밀번호가 어디로도 전송되지 않고 로컬에서만 해시로 변환됩니다).     │
    │ 나온 결과값을 Streamlit Cloud → App settings → Secrets 에:               │
    │   ADMIN_PASSWORD_HASH = "여기에_생성된_bcrypt_해시값"                     │
    │ (로컬 실행 시에는 환경변수 ADMIN_PASSWORD_HASH 로 설정)                   │
    │                                                                          │
    │ 예전 SHA-256 해시(구 명령: hashlib.sha256(...).hexdigest())도 자동 인식해 │
    │ 계속 동작하므로, bcrypt로 안 바꿔도 당장 로그인이 끊기지는 않습니다 —     │
    │ 다만 이전 비밀번호는 git 히스토리에 평문으로 남아있어 유출된 것으로       │
    │ 간주해야 하니, 아직 새 비밀번호로 안 바꿨다면 위 방법으로 교체 권장.       │
    └──────────────────────────────────────────────────────────────────────────┘
    """
    stored_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not stored_hash:
        try:
            stored_hash = st.secrets.get("ADMIN_PASSWORD_HASH")
        except Exception:
            stored_hash = None
    return (stored_hash or "").strip()


def _verify_admin_password(input_password, stored_hash):
    """
    저장된 해시 형식을 자동 판별해 검증합니다.
    - bcrypt 해시는 항상 "$2a$"/"$2b$"/"$2y$" 로 시작합니다(솔트가 해시 안에 포함된 표준 형식).
    - 그 외(64자리 hex 문자열)는 예전 SHA-256 방식으로 간주해 하위호환 처리합니다.
    """
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        if not BCRYPT_AVAILABLE:
            return False
        try:
            return bcrypt.checkpw(input_password.encode(), stored_hash.encode())
        except ValueError:
            return False
    input_hash = hashlib.sha256(input_password.encode()).hexdigest()
    return hmac.compare_digest(input_hash, stored_hash)


def render_admin_sidebar():
    """사이드바 하단에 관리자 암호 인증 시스템을 배치합니다."""
    st.sidebar.markdown("### ⚙️ 관리자 전용 메뉴")
    admin_password = st.sidebar.text_input(
        "🔑 관리자 비밀번호",
        type="password",
        help="일반 사용자에게 노출되지 않는 디버그용 암호를 입력하세요.",
        key="sidebar_admin_pwd"
    )

    stored_hash = _get_admin_password_hash()

    if not stored_hash:
        # 비밀번호가 설정되지 않았으면 관리자 모드를 열지 않습니다 (기본 해시 하드코딩 금지).
        st.session_state.admin_mode = False
        if admin_password:
            st.sidebar.error(
                "🚫 관리자 비밀번호가 서버에 설정되어 있지 않습니다.\n\n"
                "`ADMIN_PASSWORD_HASH` (Streamlit secrets 또는 환경변수)를 먼저 설정해 주세요."
            )
        return False

    admin_mode = bool(admin_password) and _verify_admin_password(admin_password, stored_hash)
    st.session_state.admin_mode = admin_mode
    if admin_mode:
        st.sidebar.success("🔓 관리자 권한 인증 성공")
        st.sidebar.markdown("---")
        # "🏢 잘 보면 보이는 손" (매크로 방공망)은 2026-08-05부로 공개 화면에서 내리고
        # 여기, 관리자 인증 성공 후에만 진입할 수 있게 했습니다 (ENGINEERING_SPEC.md §0-3-1 참고 —
        # 후행지표 원칙에 맞지 않는 추정 프록시 지표 위주라 재설계 전까지는 관리자만 확인).
        view_macro = st.sidebar.checkbox(
            "🏢 매크로 방공망 보기 (관리자 전용, 재설계 대기중)",
            key="admin_view_macro",
            help="공개 화면에서는 제외됨. 추정 프록시 지표를 후행지표 기반으로 재설계하기 전까지 관리자만 확인합니다."
        )
    return admin_mode

def render_admin_console(fetch_data_fn):
    """관리자 모드 활성화 시 메인 화면 상단에 수동 제어실을 렌더링합니다."""
    admin_mode = st.session_state.get("admin_mode", False)
    if not admin_mode:
        return

    st.info(f"⚙️ [관리자 시스템 정보]\n* **DB 파일 경로:** `{HISTORY_FILE}`\n* **DB 파일 존재 여부:** `{os.path.exists(HISTORY_FILE)}`")

    with st.expander("🛠️ 관리자 전용 데이터 수동 제어실 (비상 입력 및 가이드)", expanded=True):
        st.markdown(
            """
            ### 📌 데이터 수동 입력 가이드 및 출처 안내
            자동 수집 지연/장애 시, 아래 출처 사이트에서 당일 최종 확정 데이터를 확인하여 오타 없이 기입해 주십시오.
            
            * **영업일 선택**: 보정 또는 신규 입력할 타겟 일자를 선택합니다.
            * **KOSPI 종가 (pt)**: 소수점 이하 2자리까지 입력합니다.
              * *출처*: [네이버 증권 코스피 페이지](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)
            * **원/달러 환율 (원)**: 소수점 이하 2자리까지 입력합니다.
              * *출처*: [네이버 페이 증권 시장지표](https://finance.naver.com/marketindex/)
            * **수급 데이터 (개인/외국인/기관)**: 억원 단위로 입력합니다.
              * *출처*: [네이버 증권 투자자별 매매동향](https://finance.naver.com/sise/investorDealTrendDay.naver) 당일 첫 번째 행 수치
            """
        )
        with st.form("admin_manual_data_form"):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                m_date = st.date_input("영업일 선택", datetime.today(), key="admin_m_date")
                # 기본값 2500 / 1350 을 넣어두면 실수로 그대로 제출되어 가짜 시세가 저장됩니다.
                m_kospi = st.number_input("KOSPI 종가 (pt) *필수", value=0.0, min_value=0.0, step=0.1, key="admin_m_kospi")
                m_retail = st.number_input("개인 수급 (억원)", value=0, step=10, key="admin_m_retail")
            with col_m2:
                m_usd = st.number_input("원/달러 환율 (원) *필수", value=0.0, min_value=0.0, step=0.1, key="admin_m_usd")
                m_fore = st.number_input("외국인 수급 (억원)", value=0, step=10, key="admin_m_fore")
                m_inst = st.number_input("기관 수급 (억원)", value=0, step=10, key="admin_m_inst")

            submit_btn = st.form_submit_button("💾 클린 DB 수동 저장 및 대시보드 반영")
            if submit_btn:
                if m_kospi <= 0 or m_usd <= 0:
                    st.error("🚫 KOSPI 종가와 원/달러 환율은 실제 조회한 값을 입력해야 저장됩니다. (0 저장 불가)")
                    return
                m_date_key = m_date.strftime("%Y-%m-%d")
                override_date_str, override_is_live, override_log_msg, override_score, override_details, history_df = fetch_data_fn(
                    override_date=m_date_key,
                    override_kospi=m_kospi,
                    override_usd=m_usd,
                    override_retail=m_retail,
                    override_fore=m_fore,
                    override_inst=m_inst
                )
                st.success(f"🎉 {m_date_key} 데이터가 검증되어 성공적으로 저장되었습니다!")
                st.rerun()
