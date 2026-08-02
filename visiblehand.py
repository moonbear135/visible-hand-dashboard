import streamlit as st

st.set_page_config(
    page_title="잘 보면 보이는 손 - 시장 방공망 대시보드",
    page_icon="🚨",
    layout="centered",
    initial_sidebar_state="expanded"
)

# 공통 커스텀 CSS 스타일링
st.markdown(
    """
    <style>
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
    # 사이드바 상단 네비게이션 메인 메뉴
    st.sidebar.markdown("## 🏢 잘 보면 보이는 손")
    st.sidebar.markdown("---")
    
    selected_menu = st.sidebar.radio(
        "📌 서비스 메뉴 선택",
        ["🏢 잘 보면 보이는 손 (매크로 방공망)", "💡 사실 이 가격이에요 (밸류에이션 리포트)"],
        index=0
    )
    st.sidebar.markdown("---")
    
    # 사이드바 하단 관리자 로그인 시스템 배치
    render_admin_sidebar()

    # 메인 뷰 라우팅
    if "💡 사실 이 가격이에요" in selected_menu:
        render_pegy_page()
    else:
        render_macro_page()

if __name__ == "__main__":
    main()
