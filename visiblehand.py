import streamlit as st

st.set_page_config(
    page_title="잘 보면 보이는 손 - 시장 방공망 대시보드",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 공통 커스텀 CSS 스타일링 (사이드바 최상단 위치, 라벨 크기 확대, 줄바꿈 pre-line 강제 제어)
st.markdown(
    """
    <style>
    /* 1. 사이드바 최상단 여백 및 헤더 위치 조절 */
    section[data-testid="stSidebar"] {
        padding-top: 1rem !important;
    }
    
    /* 2. '📌 서비스 메뉴 선택' 라벨 글자 크기 확대 & 커스텀 컬러링 */
    div[data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p {
        font-size: 18px !important;
        font-weight: 800 !important;
        color: #0f766e !important;
        margin-bottom: 8px !important;
        letter-spacing: -0.3px !important;
    }
    
    /* 3. 사이드바 라디오 버튼 라벨 (메인메뉴 + 괄호 설명) pre-line 줄바꿈 강제 적용 */
    section[data-testid="stSidebar"] div[class*="stRadio"] label[data-baseweb="radio"],
    section[data-testid="stSidebar"] div[class*="stRadio"] label[data-baseweb="radio"] *,
    div[data-testid="stRadio"] label * {
        font-size: 14.5px !important;
        font-weight: 700 !important;
        line-height: 1.5 !important;
        white-space: pre-line !important;
        word-break: break-word !important;
    }

    .main-title { 
        font-size: 32px; 
        font-weight: 800; 
        text-align: center; 
        background: linear-gradient(90deg, #0f766e 0%, #14b8a6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
        letter-spacing: -0.5px;
    }
    .sub-title { 
        font-size: 15px; 
        text-align: center; 
        color: #64748b; 
        margin-bottom: 25px; 
    }
    .score-container { 
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); 
        border-radius: 16px; 
        padding: 24px; 
        text-align: center; 
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        margin-bottom: 25px;
    }
    .score-label {
        font-size: 16px;
        color: #94a3b8;
        font-weight: 600;
        letter-spacing: 1px;
    }
    .score-value {
        font-size: 56px;
        color: #ff4d4d;
        font-weight: 900;
        margin: 5px 0;
    }
    </style>
    """,
    unsafe_allow_html=True
)

from views.admin_view import render_admin_sidebar
from views.macro_view import render_macro_page
from views.pegy_view import render_pegy_page

def main():
    # 1. 사이드바 최상단 네비게이션 헤더 배치
    st.sidebar.markdown(
        """
        <div style="padding-bottom: 2px;">
            <h2 style="font-size: 24px; font-weight: 800; color: #0f766e; margin: 0 0 4px 0; letter-spacing: -0.5px;">🏢 잘 보면 보이는 손</h2>
            <div style="font-size: 13px; color: #64748b; font-weight: 600;">The Visible Hand Dashboard</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.markdown("---")
    
    # 2. 서비스 메뉴 선택 라디오 버튼 (최상단 위치, 글자 크기 확대, pre-line 줄바꿈 적용)
    selected_menu = st.sidebar.radio(
        "📌 서비스 메뉴 선택",
        [
            "🏢 잘 보면 보이는 손\n(매크로 방공망)", 
            "💡 사실 이 가격이에요\n(밸류에이션 리포트)"
        ],
        index=0
    )
    st.sidebar.markdown("---")
    
    # 3. 사이드바 하단 관리자 로그인 시스템 배치
    render_admin_sidebar()

    # 4. 메인 뷰 라우팅
    if "사실 이 가격이에요" in selected_menu:
        render_pegy_page()
    else:
        render_macro_page()

if __name__ == "__main__":
    main()
