import streamlit as st

st.set_page_config(
    page_title="잘 보면 보이는 손 - 시장 방공망 대시보드",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 공통 커스텀 CSS 스타일링 (사이드바 메뉴 최상단 위치, 📌 타이틀 확대, 2줄 라벨 강제 줄바꿈 및 flex-start 상단정렬)
st.markdown(
    """
    <style>
    /* 1. 사이드바 최상단 패딩 및 여백 조절 */
    section[data-testid="stSidebar"] {
        padding-top: 0.8rem !important;
    }
    
    /* 2. '📌 서비스 메뉴 선택' 타이틀 글자 크기 확대 (18px Bold) & Teal 색상 */
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"] p {
        font-size: 18px !important;
        font-weight: 800 !important;
        color: #0f766e !important;
        margin-bottom: 12px !important;
        letter-spacing: -0.3px !important;
        line-height: 1.4 !important;
    }
    
    /* 3. 라디오 버튼 항목 강제 2줄 (pre-line) 줄바꿈 & 폰트 가시성 강화 */
    [data-testid="stSidebar"] [data-baseweb="radio"] [data-testid="stMarkdownContainer"] p {
        font-size: 15px !important;
        font-weight: 700 !important;
        line-height: 1.6 !important;
        white-space: pre-line !important;
        display: block !important;
        margin: 0 !important;
    }

    /* 4. 라디오 동그라미 버튼을 2줄 텍스트의 첫 번째 줄 상단으로 정렬 */
    [data-testid="stSidebar"] [data-baseweb="radio"] {
        align-items: flex-start !important;
        padding-top: 8px !important;
        padding-bottom: 8px !important;
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
from views.sandbox_view import render_sandbox_page
from utils.scheduler import start_scheduler_thread

@st.cache_resource
def init_background_jobs():
    start_scheduler_thread()

init_background_jobs()

def main():
    # URL Query Parameter 체크 (예: ?view=sandbox)
    query_params = st.query_params
    view_param = query_params.get("view", None)
    
    if view_param == "sandbox":
        render_sandbox_page()
        return

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
    
    # 2. 서비스 메뉴 선택 라디오 버튼 (최상단 위치, 18px 타이틀, 명시적 2줄 줄바꿈 적용)
    selected_menu = st.sidebar.radio(
        "📌 서비스 메뉴 선택",
        [
            "🏢 잘 보면 보이는 손  \n(매크로 방공망)", 
            "💡 사실 이 가격이에요  \n(밸류에이션 리포트)",
            "🧪 UI/UX 샌드박스  \n(가격 비교 실험실)"
        ],
        index=0
    )
    st.sidebar.markdown("---")
    
    # 3. 사이드바 하단 관리자 로그인 시스템 배치
    render_admin_sidebar()

    # 4. 메인 뷰 라우팅
    if "샌드박스" in selected_menu:
        render_sandbox_page()
    elif "사실 이 가격이에요" in selected_menu:
        render_pegy_page()
    else:
        render_macro_page()

if __name__ == "__main__":
    main()
