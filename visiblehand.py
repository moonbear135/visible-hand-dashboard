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

    # 2. 관리자 로그인 시스템을 먼저 배치합니다 (2026-08-12, TASK_HISTORY #103 — 순서 수정).
    #    ⚠️ 예전에는 이 위치가 아래쪽(§4 근처)이었는데, 그러면 관리자가 방금 로그인해도
    #    바로 아래에서 만드는 "대분류 라디오"가 **한 실행(run) 지난 값**을 보게 됩니다
    #    (`st.session_state["admin_mode"]`는 render_admin_sidebar() 안에서만 갱신되므로,
    #    이 함수보다 먼저 만든 라디오는 로그인 직후 첫 렌더에서 옛 상태를 봄 — 오너가 겪은
    #    "로그인 성공은 뜨는데 리포트/내 성적표가 안 보인다" 버그의 실제 원인이었습니다).
    #    함수를 먼저 호출해 **항상 최신 admin_mode**를 쓰도록 순서를 바꿨습니다. 사이드바
    #    시각적 순서가 "관리자 메뉴 → 사실 이 가격이에요/내 성적표"로 바뀌지만, 일반 방문자에게는
    #    관리자 로그인 폼 UI 자체가 아주 작아서 체감 차이가 크지 않고, 정확성이 우선입니다.
    admin_mode = render_admin_sidebar()
    st.sidebar.markdown("---")

    # 3. 공개 서비스 메뉴 (사이드바 상단) — 대분류 1개 아래 시장별 중분류 2개
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
    # ⚠️ 2026-08-12(TASK_HISTORY #102): 오너가 원한 구조는 대분류 2개가 나란히 있고("💡 사실 이
    #    가격이에요" / "📊 내 성적표"), 각각 그 밑에 중분류(한국/미국, 내 보유종목/리포트)가
    #    있는 **2단 트리**입니다(오너가 그림으로 확정). 대분류 전환은 라디오 하나로 클릭 한 번에
    #    되고, 중분류는 고른 대분류 밑에서만 나타납니다.
    TOP_VALUATION = "💡 사실 이 가격이에요"
    TOP_SCORECARD = "📊 내 성적표 (준비중 · 미리보기)"
    # admin_mode 는 위 §2 에서 이미 이번 실행(run) 기준 최신 값으로 확정됐습니다(스테일 버그 수정).
    scorecard_available = render_scorecard_page is not None and is_scorecard_visible(admin_mode)

    top_options = [TOP_VALUATION]
    if scorecard_available:
        top_options.append(TOP_SCORECARD)
    if len(top_options) > 1:
        top_choice = st.sidebar.radio(
            "메뉴",
            top_options,
            index=0,  # 첫 진입 기본값은 예전과 동일하게 "사실 이 가격이에요"
            key="top_nav_choice",
            help=f"* {TOP_VALUATION} : 시장별 밸류에이션 리포트(코스피/미국)\n"
                 f"* {TOP_SCORECARD} : 내 보유 종목·리포트(오너 승인 전 미리보기)",
        )
    else:
        top_choice = TOP_VALUATION  # 성적표 미노출 시(일반 방문자) 예전과 100% 동일 동작
    show_scorecard = top_choice == TOP_SCORECARD

    if show_scorecard:
        st.sidebar.caption(
            "내 보유 종목을 직접 입력해 비중·수익 비중과 PEGY 밸류에이션을 대조해보고, "
            "쌓인 기록으로 리포트도 보는 신규 모듈입니다. 오너 승인 전까지 공개 메뉴에 노출되지 않습니다."
        )
        selected_market = None
        MARKET_KR = MARKET_US = None  # 아래 §4 라우팅에서 존재 확인용
    else:
        st.sidebar.markdown(
            """
            <div style="border-left: 4px solid #14b8a6; padding: 2px 0 2px 10px; margin: 6px 0 10px 0;">
                <div style="font-size: 17px; font-weight: 800; color: #0f172a; letter-spacing: -0.3px;">💡 사실 이 가격이에요</div>
                <div style="font-size: 12px; color: #64748b; font-weight: 600; margin-top: 2px;">시장별 밸류에이션 리포트</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        MARKET_KR = "한국 주식은 이가격이에요"
        MARKET_US = "미국 주식은 이가격이에요"
        selected_market = st.sidebar.radio(
            "시장 선택",
            [MARKET_KR, MARKET_US],
            index=0,  # 첫 진입 기본값은 예전과 동일하게 한국(코스피)
            key="selected_market",
            help="어느 시장의 밸류에이션 리포트를 볼지 고릅니다.\n\n"
                 f"* {MARKET_KR} : 코스피200 종목 PEGY 리포트 (기본 화면)\n"
                 f"* {MARKET_US} : 미국(나스닥+뉴욕) 시가총액 상위 550종목 PEGY 리포트"
        )

    if not scorecard_available and admin_mode and SCORECARD_IMPORT_ERROR:
        st.sidebar.error(f"📊 내 성적표 모듈 로드 실패: {SCORECARD_IMPORT_ERROR}")
    st.sidebar.markdown("---")

    # 3-1. 📈 리포트(2026-08-12 신설) — "내 성적표"를 고른 뒤 그 밑에 나오는 중분류(하위 탭)입니다.
    #      (ENGINEERING_SPEC.md §0-3-6: 신규 기능은 오너 승인 후에 공개 반영. 코드/데이터는
    #      성적표와 완전히 독립된 별도 모듈입니다 — 메뉴 배치만 하위 탭으로 묶인 것입니다.)
    show_report = False
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
