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

    /* 참고: 2026-08-05 매크로 화면 관리자 전용 전환 시 사이드바 공개 메뉴(서비스 선택 라디오)를
       완전히 없앴습니다. 그때 그 라디오 전용 스타일(옛 규칙 2~4번)이 죽은 CSS로 남아있던 걸
       2026-08-06 정리 과정에서 제거했습니다 — 실제 화면엔 아무 영향 없는 정리입니다. */

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
from utils.scheduler import start_scheduler_thread

@st.cache_resource
def init_background_jobs():
    start_scheduler_thread()

init_background_jobs()

def main():
    # URL Query Parameter 체크
    query_params = st.query_params

    # 1. 사이드바 최상단 네비게이션 헤더 배치
    st.sidebar.markdown(
        """
        <div style="padding-bottom: 2px;">
            <h2 style="font-size: 24px; font-weight: 800; color: #0f766e; margin: 0 0 4px 0; letter-spacing: -0.5px;">🏢 잘 보면 보이는 손</h2>
            <div style="font-size: 13px; color: #64748b; font-weight: 600;">The Visible Hand Dashboard</div>
            <div style="font-size: 12px; color: #94a3b8; font-weight: 600; margin-top: 10px;">📊 현재 공개 서비스: 사실 이 가격이에요<br>(밸류에이션 리포트)</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.markdown("---")

    # 2. 공개 서비스는 "사실 이 가격이에요(밸류에이션 리포트)" 하나뿐입니다.
    #    "🏢 잘 보면 보이는 손(매크로 방공망)"은 2026-08-05 오너 지침(ENGINEERING_SPEC.md §0-3-1)에 따라
    #    후행지표 원칙에 맞지 않는 추정 프록시 지표 위주라 공개 화면에서는 제외하고,
    #    관리자 인증 후 사이드바 하단의 "⚙️ 관리자 전용 메뉴"에서만 볼 수 있게 이동했습니다.
    #    (일반 방문자에게는 메뉴 선택지 자체가 보이지 않습니다 — 후행지표로 재설계 전까지 비공개)
    #    2026-08-06: 빈 공간이 마치 뭔가 빠진 것처럼 보인다는 오너 피드백으로, 위 타이틀 아래에
    #    "현재 공개 서비스" 캡션을 추가해 그 자리가 의도된 것임을 명시했습니다.

    # 3. 사이드바 하단 관리자 로그인 시스템 배치 (인증 성공 시 매크로 화면 진입 옵션도 여기서 노출)
    admin_mode = render_admin_sidebar()

    # 4. 메인 뷰 라우팅
    if admin_mode and st.session_state.get("admin_view_macro"):
        render_macro_page()
    else:
        render_pegy_page()

if __name__ == "__main__":
    main()

# Trigger reload
