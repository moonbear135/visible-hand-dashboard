import hashlib
import hmac
import os
from datetime import datetime
import streamlit as st
from utils.db import HISTORY_FILE

def render_admin_sidebar():
    """사이드바 하단에 관리자 암호 인증 시스템을 배치합니다."""
    # 사이드바 전체 레이아웃을 Flexbox로 설정하여 하단 컨테이너를 아래로 밀어내는 CSS 주입
    st.markdown(
        """
        <style>
        div[data-testid="stSidebarUserContent"] {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 50px) !important;
        }
        div[data-testid="stSidebarUserContent"] > div:last-child {
            margin-top: auto !important;
            padding-top: 20px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown("### ⚙️ 관리자 전용 메뉴")
    admin_password = st.text_input("🔑 관리자 비밀번호", type="password", help="일반 사용자에게 노출되지 않는 디버그용 암호를 입력하세요.")
    
    # ***REMOVED-OLD-ADMIN-PASSWORD*** 의 SHA-256 해시값
    stored_hash = "***REMOVED-OLD-PASSWORD-HASH***"
    input_hash = hashlib.sha256(admin_password.encode()).hexdigest()
    
    admin_mode = hmac.compare_digest(input_hash, stored_hash)
    st.session_state.admin_mode = admin_mode
    if admin_mode:
        st.success("🔓 관리자 권한 인증 성공")
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
                m_kospi = st.number_input("KOSPI 종가 (pt)", value=2500.0, step=0.1, key="admin_m_kospi")
                m_retail = st.number_input("개인 수급 (억원)", value=0, step=10, key="admin_m_retail")
            with col_m2:
                m_usd = st.number_input("원/달러 환율 (원)", value=1350.0, step=0.1, key="admin_m_usd")
                m_fore = st.number_input("외국인 수급 (억원)", value=0, step=10, key="admin_m_fore")
                m_inst = st.number_input("기관 수급 (억원)", value=0, step=10, key="admin_m_inst")

            submit_btn = st.form_submit_button("💾 클린 DB 수동 저장 및 대시보드 반영")
            if submit_btn:
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
