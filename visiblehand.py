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
       완전히 없앴고, 죽은 CSS로 남아있던 그 라디오 전용 스타일을 2026-08-06에 제거했습니다.
       2026-08-08 한국/미국 리포트 선택 라디오가 다시 생기면서 아래 규칙 2번을 새로 넣었습니다.
       ⚠️ 옛 규칙과 달리 `[data-testid="stRadio"]` 안쪽으로 범위를 좁혔습니다 — 옛 규칙은
       사이드바의 모든 위젯 라벨(관리자 비밀번호 입력창 라벨 등)까지 같이 건드렸는데,
       지금은 이 라디오 하나에만 적용되게 해서 관리자 메뉴 모양은 그대로 두었습니다.
       (테마/버전 차이로 셀렉터가 안 맞으면 기본 스타일로 렌더링될 뿐 깨지지 않습니다.) */

    /* 2. 시장 선택 라디오 항목 글자 가시성 강화 + 동그라미 버튼 상단 정렬 */
    [data-testid="stSidebar"] [data-testid="stRadio"] [data-baseweb="radio"] [data-testid="stMarkdownContainer"] p {
        font-size: 15px !important;
        font-weight: 700 !important;
        line-height: 1.6 !important;
        margin: 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] [data-baseweb="radio"] {
        align-items: flex-start !important;
        padding-top: 4px !important;
        padding-bottom: 4px !important;
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
from views.us_stocks_view import render_us_stocks_page
from utils.scheduler import start_scheduler_thread

# 📊 "내 성적표"(3번째 모듈)는 2026-08-11 신설된 **스테이징 상태** 화면입니다
# (ENGINEERING_SPEC.md §0-3-6 — 오너 승인 전까지 공개 메뉴에 노출하지 않음).
# 아래 import 를 try/except 로 감싼 이유: 이 모듈은 선택적 의존성(supabase 패키지)과
# 엮여 있어서, 어떤 이유로든 로드에 실패하더라도 **기존 두 공개 화면은 반드시 살아있어야**
# 하기 때문입니다. 실패를 조용히 삼키지 않도록 실패 사유는 보관해뒀다가
# 관리자 모드 사이드바에만 표시합니다(일반 방문자 화면은 예전과 100% 동일).
try:
    from views.scorecard_view import is_scorecard_visible, render_scorecard_page
    SCORECARD_IMPORT_ERROR = None
except Exception as _scorecard_import_exc:  # noqa: BLE001
    is_scorecard_visible = None
    render_scorecard_page = None
    SCORECARD_IMPORT_ERROR = str(_scorecard_import_exc)

# 📈 "리포트"(5번째 모듈)는 2026-08-12 신설된 **스테이징 상태** 화면입니다(§0-3-6).
# "내 성적표"와 완전히 같은 패턴 — import 실패해도 기존 화면은 그대로 살아있어야 합니다.
try:
    from views.report_view import is_report_visible, render_report_page
    REPORT_IMPORT_ERROR = None
except Exception as _report_import_exc:  # noqa: BLE001
    is_report_visible = None
    render_report_page = None
    REPORT_IMPORT_ERROR = str(_report_import_exc)

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
        </div>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.markdown("---")

    # 2. 공개 서비스 메뉴 (사이드바 상단) — 대분류 1개 아래 시장별 중분류 2개
    #      대분류: 💡 사실 이 가격이에요
    #        중분류: 🇰🇷 한국 주식은 이가격이에요  → render_pegy_page()      (기본값)
    #        중분류: 🇺🇸 미국 주식은 이가격이에요  → render_us_stocks_page()
    #    2026-08-08(오전) 공개 전환 때는 미국주식을 체크박스 하나로 켜는 구조였는데, 그러면
    #    "코스피가 본체고 미국은 부가 옵션"처럼 읽힙니다. 오너 요청으로 둘을 대등한 두 리포트로
    #    보이게 라디오(택1) 구조로 바꿨습니다 — 위젯도 이 프로젝트가 예전에 쓰던 사이드바
    #    서비스 선택 방식(st.sidebar.radio)과 동일하고, 화면 안의 다른 택1 UI(페이지 이동 라디오,
    #    빠른 필터 selectbox)와도 결이 맞습니다.
    #    ⚠️ 대분류 헤더는 위쪽 브랜드 타이틀("🏢 잘 보면 보이는 손" = 매크로 방공망, 별개 화면)과
    #       혼동되지 않게 크기·색·좌측 액센트바로 시각적으로 구분했습니다.
    #    "🏢 잘 보면 보이는 손(매크로 방공망)"은 2026-08-05 오너 지침(ENGINEERING_SPEC.md §0-3-1)에 따라
    #    후행지표 원칙에 맞지 않는 추정 프록시 지표 위주라 공개 화면에서는 제외하고,
    #    관리자 인증 후 사이드바 하단의 "⚙️ 관리자 전용 메뉴"에서만 볼 수 있게 이동했습니다.
    #    (일반 방문자에게는 매크로 메뉴 선택지 자체가 보이지 않습니다 — 후행지표로 재설계 전까지 비공개)
    st.sidebar.markdown(
        """
        <div style="border-left: 4px solid #14b8a6; padding: 2px 0 2px 10px; margin: 2px 0 10px 0;">
            <div style="font-size: 17px; font-weight: 800; color: #0f172a; letter-spacing: -0.3px;">💡 사실 이 가격이에요</div>
            <div style="font-size: 12px; color: #64748b; font-weight: 600; margin-top: 2px;">시장별 밸류에이션 리포트</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    MARKET_KR = "한국 주식은 이가격이에요"
    MARKET_US = "미국 주식은 이가격이에요"
    # ⚠️ 2026-08-12: "내 성적표" 체크박스가 켜져 있으면 라우팅(§4)에서 이 라디오 선택이 무시되고
    #    항상 성적표/리포트 화면이 우선 표시됩니다(이전부터 있던 동작). 라디오는 그대로 뒀는데
    #    클릭해도 반응이 없어 보인다는 오너 피드백이 있어, **비활성화 + 안내 문구**로 명확히
    #    보여주기로 했습니다. `view_scorecard` 위젯은 이 라디오보다 나중에 렌더링되지만,
    #    st.session_state 는 이전 실행의 값을 이미 들고 있으므로 여기서 먼저 읽어도 안전합니다.
    scorecard_checked = st.session_state.get("view_scorecard", False)
    selected_market = st.sidebar.radio(
        "시장 선택",
        [MARKET_KR, MARKET_US],
        index=0,  # 첫 진입 기본값은 예전과 동일하게 한국(코스피)
        key="selected_market",
        disabled=scorecard_checked,
        help=(
            "지금 '📊 내 성적표'가 켜져 있어 비활성화됐습니다. 이 리포트를 보려면 "
            "아래 '📊 내 성적표' 체크를 먼저 해제하세요."
            if scorecard_checked else
            "어느 시장의 밸류에이션 리포트를 볼지 고릅니다.\n\n"
            f"* {MARKET_KR} : 코스피200 종목 PEGY 리포트 (기본 화면)\n"
            f"* {MARKET_US} : 미국(나스닥+뉴욕) 시가총액 상위 550종목 PEGY 리포트"
        )
    )
    if scorecard_checked:
        st.sidebar.caption("⚠️ 내 성적표가 켜져 있어 위 시장 선택은 잠시 비활성화됩니다.")
    st.sidebar.markdown("---")

    # 3. 사이드바 하단 관리자 로그인 시스템 배치 (인증 성공 시 매크로 화면 진입 옵션도 여기서 노출)
    admin_mode = render_admin_sidebar()

    # 3-1. 📊 내 성적표 (스테이징, 2026-08-11 신설) + 📈 리포트(2026-08-12 신설, 그 하위 탭)
    #      ⚠️ 기본값은 **숨김**입니다. 아래 두 경우에만 사이드바에 진입 체크박스가 생깁니다.
    #         ① 관리자 인증 상태(미리보기)  ② SCORECARD_ENABLED 플래그를 명시적으로 켠 경우
    #      일반 방문자에게는 메뉴 자체가 보이지 않으므로 공개 화면 동작은 예전과 100% 동일합니다.
    #      (ENGINEERING_SPEC.md §0-3-6: 신규 기능은 오너 승인 후에 공개 반영)
    #      리포트는 "내 성적표" 체크박스를 켰을 때만 그 밑에 라디오(하위 탭)로 고를 수 있습니다
    #      (2026-08-12 오너 요청 — 원래는 형제 체크박스 2개였는데, 둘 다 켜고 안 보는 쪽을 매번
    #      꺼야 해서 쓰기 불편하다는 피드백으로 중첩 구조로 변경). 코드/데이터는 여전히 완전히
    #      독립된 별도 모듈입니다 — 메뉴 배치만 바뀐 것입니다.
    show_scorecard = False
    show_report = False
    if render_scorecard_page is not None and is_scorecard_visible(admin_mode):
        st.sidebar.markdown("---")
        show_scorecard = st.sidebar.checkbox(
            "📊 내 성적표 (준비중 · 미리보기)",
            key="view_scorecard",
            help="내 보유 종목을 직접 입력해 비중·수익 비중과 PEGY 밸류에이션을 대조해보고, "
                 "쌓인 기록으로 리포트도 보는 신규 모듈입니다. "
                 "오너 승인 전까지 공개 메뉴에 노출되지 않습니다."
        )
        if show_scorecard:
            report_available = render_report_page is not None and is_report_visible(admin_mode)
            if report_available:
                SCORECARD_TAB = "📊 내 보유종목"
                REPORT_TAB = "📈 리포트"
                scorecard_subpage = st.sidebar.radio(
                    "내 성적표 하위 메뉴",
                    [SCORECARD_TAB, REPORT_TAB],
                    key="scorecard_subpage",
                    help="같은 로그인 세션을 공유합니다 — 한 번만 로그인하면 됩니다.",
                )
                show_report = scorecard_subpage == REPORT_TAB
            elif admin_mode and REPORT_IMPORT_ERROR:
                st.sidebar.error(f"📈 리포트 모듈 로드 실패: {REPORT_IMPORT_ERROR}")
    elif admin_mode and SCORECARD_IMPORT_ERROR:
        # 실패를 조용히 삼키지 않되(§0-1), 일반 방문자 화면은 건드리지 않습니다.
        st.sidebar.error(f"📊 내 성적표 모듈 로드 실패: {SCORECARD_IMPORT_ERROR}")

    # 4. 메인 뷰 라우팅
    #    ⚠️ 기본(아무것도 고르지 않은 첫 진입) 경로는 예전과 100% 동일하게 render_pegy_page() 입니다.
    #    ⚠️ 매크로 화면은 여전히 관리자 인증 후에만 진입 가능합니다 — 이번 메뉴 개편과 무관합니다.
    if show_scorecard and show_report:
        render_report_page()
    elif show_scorecard:
        render_scorecard_page()
    elif selected_market == MARKET_US:
        render_us_stocks_page()
    elif admin_mode and st.session_state.get("admin_view_macro"):
        render_macro_page()
    else:
        render_pegy_page()

if __name__ == "__main__":
    main()

# Trigger reload
