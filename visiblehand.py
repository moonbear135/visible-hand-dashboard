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

    /* 2026-08-16 오너 신고(#119) — index.html이 iframe src에 `?embed=true`를 붙여 Streamlit
       자체 헤더/풋터를 숨기고 있었는데, 공식 문서로 확인한 결과 `embed=true` 모드에서는
       "Built with Streamlit · Fullscreen" 바가 **항상** 함께 붙고 CSS·embed_options 어느
       쪽으로도 끌 수 없습니다(Community Cloud 무료 호스팅의 고정 요소, self-hosting 해야만
       사라짐 — 커뮤니티 포럼 다수 확인). 그래서 `index.html` 쪽 `embed=true`는 빼고, 대신
       여기 앱 코드에서 같은 목적(헤더 툴바·상단 색줄·풋터 숨김)을 CSS로 직접 구현합니다.
       ⚠️ `header` 태그 전체를 숨기지 않습니다 — 사이드바 접기/펼치기(">>" 버튼)가 헤더 쪽에
       같이 있어서, 통째로 숨기면 그 버튼까지 사라집니다(실사용 시 사이드바를 못 여는 버그가
       됨). 대신 헤더 **안의** 툴바/배포버튼/상단 장식줄/실행중 표시만 개별적으로 숨겨서
       사이드바 토글은 그대로 남깁니다. */
    div[data-testid="stToolbar"] { visibility: hidden; height: 0%; position: fixed; }
    div[data-testid="stDecoration"] { visibility: hidden; height: 0%; position: fixed; }
    div[data-testid="stStatusWidget"] { visibility: hidden; height: 0%; position: fixed; }
    #MainMenu { visibility: hidden; height: 0%; }
    footer { visibility: hidden; height: 0%; }
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


def render_category_header(title, subtitle):
    """
    사이드바 대분류 헤더 1블록. **두 대분류가 똑같은 모양·똑같은 높이로 그려지도록** 마크업을
    한 곳에 모아둔 함수입니다(2026-08-13 사이드바 레이아웃 정리 — 아래 main() §2-1 주석 참고).

    ⚠️ `title`/`subtitle` 은 이 파일 안에 상수로 적힌 문자열만 들어옵니다(사용자 입력이 닿는
       경로가 없습니다). 그래서 별도 이스케이프 없이 그대로 넣습니다 — 만약 나중에 이 자리에
       DB 값이나 사용자 입력을 넣게 되면 반드시 `html.escape()` 를 거치세요
       (같은 이유로 `views/scorecard_view.py._row_label_html()` 은 이스케이프합니다).
    ⚠️ 두 줄(제목 1줄 + 부제 1줄)로 **고정**하기 위해 각 줄에 nowrap + 말줄임을 걸었습니다.
       사이드바 폭이 아무리 좁아져도 이 블록이 3줄로 늘어나 아래 메뉴를 밀어내지 않습니다.
    """
    st.sidebar.markdown(
        f"""
        <div style="border-left: 4px solid #14b8a6; padding: 2px 0 2px 10px; margin: 6px 0 10px 0;">
            <div style="font-size: 17px; font-weight: 800; color: #0f172a; letter-spacing: -0.3px;
                        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{title}</div>
            <div style="font-size: 12px; color: #64748b; font-weight: 600; margin-top: 2px;
                        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

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
    # ⚠️ 2026-08-12(TASK_HISTORY #102): 오너가 원한 구조는 대분류 2개가 나란히 있고("💡 사실 이
    #    가격이에요" / "📊 내 성적표"), 각각 그 밑에 중분류(한국/미국, 내 보유종목/리포트)가
    #    있는 **2단 트리**입니다(오너가 그림으로 확정). 대분류 전환은 라디오 하나로 클릭 한 번에
    #    되고, 중분류는 고른 대분류 밑에서만 나타납니다.
    # ⚠️ 2026-08-12(TASK_HISTORY #105): 관리자 메뉴는 사이드바 **맨 아래**에 있어야 한다는
    #    오너 방침(일반 방문자는 건드릴 일이 없으니 눈에 덜 띄는 자리에)이라, render_admin_sidebar()
    #    호출 자체는 아래 §5(원래 위치)에 그대로 둡니다. 다만 그러면 이 라디오가 로그인 직후
    #    첫 렌더에서 **한 실행 지난 admin_mode**를 보는 문제(#103)가 재발하므로, 여기서는
    #    session_state 를 미리 읽고(`admin_mode_hint`) 아래 §5 에서 실제 값과 다르면 즉시
    #    `st.rerun()`으로 한 번 더 그려서 화면 위치는 그대로 유지하면서 정확성도 지킵니다.
    TOP_VALUATION = "💡 사실 이 가격이에요"
    TOP_SCORECARD = "📊 내 성적표"
    admin_mode_hint = st.session_state.get("admin_mode", False)
    scorecard_available = render_scorecard_page is not None and is_scorecard_visible(admin_mode_hint)

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
                 f"* {TOP_SCORECARD} : 내 보유 종목·사장님 보고서",
        )
    else:
        top_choice = TOP_VALUATION  # 성적표 미노출 시(일반 방문자) 예전과 100% 동일 동작
    show_scorecard = top_choice == TOP_SCORECARD

    # 2-1. 고른 대분류의 **중분류(하위 메뉴)** 블록
    # =========================================================================
    # ⚠️ 2026-08-13 사이드바 레이아웃 정리 — 오너 신고: "대분류를 바꿀 때마다 그 아래
    #    '⚙️ 관리자 전용 메뉴'와 '🏢 매크로 방공망 보기' 체크박스가 위아래로 움직인다."
    #
    #    원인은 두 가지였습니다.
    #      ① 두 대분류가 만들어내는 콘텐츠의 **구성 자체가 달랐습니다.**
    #         - "💡 사실 이 가격이에요" → [대분류 헤더] + [시장 선택 라디오 2개]
    #         - "📊 내 성적표"          → (아무것도 없음)
    #         Streamlit 사이드바는 위에서 아래로 순서대로 쌓이므로, 위쪽 콘텐츠 높이가
    #         다르면 그 아래 요소가 그만큼 밀리는 게 정상 동작입니다(버그가 아니라 설계 문제).
    #      ② 게다가 "내 성적표"의 하위 메뉴(내 보유종목/리포트) 라디오는 §3-1, 즉
    #         `render_admin_sidebar()` **뒤**에서 그려지고 있었습니다. 그래서 성적표를 고르면
    #         하위 메뉴가 관리자 메뉴 **아래**로 내려가, 오너가 그림으로 확정한 2단 트리
    #         (대분류 밑에 중분류)도 무너지고 "관리자 메뉴는 맨 아래"라는 #105 방침과도
    #         어긋났습니다.
    #
    #    ▶ 고친 방법(Streamlit 네이티브 — CSS 주입·position 조작 일절 없음)
    #      두 대분류가 **완전히 같은 요소 순서**를 그리도록 구조를 맞췄습니다.
    #          [대분류 헤더 마크다운 1개] + [선택지 2개짜리 라디오 1개]
    #      "내 성적표"에도 같은 모양의 헤더를 주고, 하위 메뉴 라디오를 여기(관리자 메뉴 위)로
    #      끌어올렸습니다. 요소의 개수·종류·줄수가 같으니 블록 높이가 같아지고, 그 아래
    #      "⚙️ 관리자 전용 메뉴"는 **어느 대분류를 고르든 항상 같은 세로 위치**에서 시작합니다.
    #
    #    ▶ 왜 CSS `position: sticky/fixed` 나 고정 높이 컨테이너를 쓰지 않았는가
    #      · CSS 주입은 Streamlit 내부 DOM(클래스명 등)에 의존해 버전이 바뀌면 조용히 깨집니다.
    #        여기서 쓰는 건 `st.sidebar.markdown` 과 `st.sidebar.radio` 뿐 — 공개 API만 씁니다.
    #      · `st.container(height=...)` 로 높이를 고정하는 방법도 검토했지만, 픽셀 상수를
    #        테마·글꼴·화면폭마다 다시 맞춰야 하고 어긋나면 **내부 스크롤바 뒤로 메뉴가 잘려**
    #        더 나쁜 실패가 납니다. 지금 방식은 매직넘버가 하나도 없고, 최악의 경우에도
    #        (미래 버전에서 글자 줄바꿈이 달라지는 정도) 살짝 어긋날 뿐 잘리지 않습니다.
    #
    #    ⚠️ 하위 메뉴 라디오가 `admin_mode` 대신 `admin_mode_hint` 를 보게 된 점 — 위 대분류
    #      라디오와 완전히 같은 이유·같은 패턴입니다(#105). 값이 실제와 다르면 아래 §3 에서
    #      `st.rerun()` 이 한 번 더 그려주므로 스테일 문제(#103)는 재발하지 않습니다.
    #    ⚠️ 남은 예외 하나: `SCORECARD_ENABLED` 만 켜고 `REPORT_ENABLED` 를 안 켠(또는 리포트
    #      모듈 import 가 실패한) 상태에서는 하위 메뉴 라디오를 만들 수 없어 그만큼 짧아집니다.
    #      없는 메뉴를 만들어 보여줄 수는 없으니(§0-1) 그대로 두었습니다 — 오너가 두 플래그를
    #      함께 켜는 정상 공개 상태에서는 발생하지 않습니다.
    show_report = False
    if show_scorecard:
        # 2026-08-12(TASK_HISTORY #104): 사이드바 설명 캡션 없음 — 오너 판단으로 계속 안 씀
        # ("공개 전환할 때도 필요 없을 것 같다"). 아래 부제는 캡션이 아니라 위 "사실 이
        # 가격이에요"와 짝을 이루는 대분류 헤더의 일부입니다.
        render_category_header("📊 내 성적표", "내 보유종목 · 기간별 보고서")
        report_available = render_report_page is not None and is_report_visible(admin_mode_hint)
        if report_available:
            SCORECARD_TAB = "📊 내 보유종목"
            REPORT_TAB = "📈 사장님 보고서입니다"
            scorecard_subpage = st.sidebar.radio(
                "내 성적표 하위 메뉴",
                [SCORECARD_TAB, REPORT_TAB],
                key="scorecard_subpage",
                help="같은 로그인 세션을 공유합니다 — 한 번만 로그인하면 됩니다.",
            )
            show_report = scorecard_subpage == REPORT_TAB
        selected_market = None
        MARKET_KR = MARKET_US = None  # 아래 §4 라우팅에서 존재 확인용
    else:
        render_category_header("💡 사실 이 가격이에요", "시장별 밸류에이션 리포트")
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

    st.sidebar.markdown("---")

    # 3. 사이드바 하단 관리자 로그인 시스템 배치 (인증 성공 시 매크로 화면 진입 옵션도 여기서 노출)
    #    2026-08-12(TASK_HISTORY #105): 오너 방침대로 이 위치(맨 아래)를 유지합니다. 다만 위 §2
    #    라디오가 이미 `admin_mode_hint`(한 실행 지난 값)로 그려진 뒤라서, 로그인 상태가 지금
    #    막 바뀌었다면(hint 와 실제 값이 다르면) 화면이 어긋난 채로 남습니다 — 그래서 값이
    #    다를 때만 즉시 `st.rerun()`으로 한 번 더 그립니다(다음 실행에선 hint 가 이미 최신이라
    #    재발하지 않음). 사용자 입장에서는 로그인 버튼을 누른 순간 한 번 더 그려질 뿐이라
    #    체감되는 지연은 없습니다.
    admin_mode = render_admin_sidebar()
    if admin_mode != admin_mode_hint:
        st.rerun()

    # 3-1. 모듈 로드 실패 안내 — **관리자에게만** 보이는 진단 메시지입니다.
    #      2026-08-13: 예전에는 리포트 하위 메뉴 라디오와 함께 §3-1 에 있었는데, 그 라디오가
    #      위 §2-1(관리자 메뉴 위)로 올라가면서 여기엔 진단 문구만 남았습니다. 진단 문구를
    #      §2-1 로 같이 올리지 않은 이유: 에러 박스는 높이가 문구 길이에 따라 들쭉날쭉해서
    #      §2-1 의 "두 대분류 높이 맞추기"를 그 자리에서 다시 깨뜨립니다. 일반 방문자에게는
    #      애초에 보이지 않는 문구이므로 사이드바 맨 아래에 두는 편이 안전합니다.
    if not scorecard_available and admin_mode and SCORECARD_IMPORT_ERROR:
        st.sidebar.error(f"📊 내 성적표 모듈 로드 실패: {SCORECARD_IMPORT_ERROR}")
    if show_scorecard and render_report_page is None and admin_mode and REPORT_IMPORT_ERROR:
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
