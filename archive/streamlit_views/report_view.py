"""
views/report_view.py
📈 "리포트" — 매일 쌓인 스냅샷으로 일간·주간·월간·분기·반기·연간 리포트를 보여주는 화면 (v1)

🚧 **스테이징 상태 (ENGINEERING_SPEC.md §0-3-6)** — 오너 승인 전까지 공개 메뉴에 노출되지
   않습니다. 기본값은 숨김이고, ① 관리자 인증 상태이거나 ② `REPORT_ENABLED` 플래그를
   명시적으로 켠 경우에만 진입점을 만들 수 있습니다(`is_report_visible()`).

   ⚠️ 2026-08-12 현재 `visiblehand.py` 사이드바에는 **아직 배선하지 않았습니다.**
      REPORT_WORK_ORDER.md §7 의 신규 파일 목록에 `visiblehand.py` 가 없어서(=기존 파일을
      건드리지 말라는 지시) 이번 작업 범위에서 제외했습니다. 오너가 미리보기를 원하면
      아래 3줄만 `visiblehand.py` 의 "내 성적표" 블록 옆에 넣으면 됩니다(내 성적표와 완전히
      같은 패턴):

          from views.report_view import is_report_visible, render_report_page
          show_report = st.sidebar.checkbox("📈 사장님 보고서입니다", key="view_report") \
              if is_report_visible(admin_mode) else False
          ...  if show_report: render_report_page()

v1 범위 (REPORT_WORK_ORDER.md §6)
   - 기간 선택(일/주/월/분기/반기/연) + 과거 기간으로 이동
   - 저장된 스냅샷을 기간 범위로 집계해 수익률 표시(계산은 전부 `utils/report_db.py`)
   - 시장별 벤치마크 비교(한국=코스피 지수, 미국=S&P500·나스닥 **추종 ETF 프록시**)
   - 데이터가 부족한 구간은 §3 원칙대로 "데이터 부족"을 **주 컨텐츠로** 표시
   - 시장별로 "이 숫자는 **언제 종가**로 만들어졌나"(한국시간 시:분)를 표시 — 2026-08-13 추가.
     한국장/미국장은 수집 시각이 다르고(미국은 한국시간 새벽), 그 시각은 **그 스냅샷 행이
     저장될 때 배치가 기록해 둔 값**(`price_as_of_kst`)입니다(오늘 값으로 대신 채우지 않음).
   - 🧾 **종목별 상세** 섹션 — 2026-08-13 추가(오너 결정, `portfolio_holding_snapshots` 신설).
     기간 안 **마지막 기록일 하루**의 종목별 상태를 평가금액 큰 순으로 한 표(+ 합계 한 줄)에
     담고, 종목 하나를 고르면 그 종목의 기간 내 일별 추이를 펼쳐 봅니다. 이 표의 합계는 같은 날
     합계 스냅샷과 **매번 대조**합니다(어긋나면 숨기지 않고 경고 — 정상일 땐 조용히).
   - 📊 **종목별 비중(%) + 기간 시작 대비 비중 변화** — 2026-08-13 추가(#114, 오너가 수기로
     관리하던 표를 옮긴 것). **새 테이블 없이** 이미 저장된 종목별 `market_value` 를 같은 날
     합계로 나눠 조회 시점에 계산합니다(`utils/report_db.build_weight_comparison()`).
   - 🇺🇸 **미국 종목명은 한글로 표시** — 2026-08-16 추가(#115, 오너 요청). 스냅샷에 저장된
     영문 원문 대신 '내 성적표'가 쓰는 것과 **완전히 같은** 한글명을 씁니다(그 화면의
     `_display_name()` 을 그대로 import — 로직 중복 구현 없음). 종목명이 나오는 자리
     (종목별 상세 표 · 비중 변화 표 · 기록이 끊긴 종목 안내 · 일별 추이 선택 라벨)에
     한 번에 적용했고, 한국 종목과 **DB 저장값은 그대로**입니다(표시 시점 변환).
   - ➗ **벤치마크 비교에 "미국 두 지수 평균" 한 줄 추가** — 2026-08-16 추가(#116, 오너가 수기로
     관리하던 "2025년수익률 비교 - 연말 성적표.csv" 의 'VOO / QQQ 평균 수익률' 줄을 옮긴 것).
     기간별 로직은 그대로라 **오너가 고른 기간이 무엇이든**(일/주/월/분기/반기/연) 같은 두
     날짜로 계산됩니다. 두 벤치마크가 **둘 다** 계산됐을 때만 나오고, 한국 시장(벤치마크 1개)
     에는 나오지 않습니다. 라벨은 실제 수집 대상(SPY·ONEQ 프록시) 이름을 씁니다 — 자세한
     이유는 아래 `_render_benchmark_average()` 주석 참고.
   - 📅 **'일간'에서 주말·공휴일을 고르면 가장 최근 기록일로 대체 표시** — 2026-08-16 추가
     (#117, 오너 요청: "주말 공휴일에는 자료가 안나오게 되있는데 … 굳이 이렇게 비워둘 필요는
     없을거 같은데"). 날짜 판정은 `utils/report_db.resolve_display_date()` 한 곳에서만 하고,
     **그리는 표는 평일과 완전히 동일한 경로**입니다(대체 전용 화면을 따로 만들지 않음).
     대체가 일어나면 **반드시** 경고 상자 한 줄로 "고른 날 ≠ 보여주는 날"을 밝힙니다
     (`_render_substitute_notice()`) — 이 고지가 없으면 §0-1 위반입니다. 그 이전에도 기록이
     하나도 없으면 대체하지 않고 기존 "데이터 부족" 그대로입니다. 주간~연간은 손대지
     않았습니다(창 안의 실제 스냅샷을 모으는 방식이라 같은 문제가 없습니다).
   - 🔤 화면 문구는 2026-08-13(#114)에 대폭 줄였습니다 — 기준은 "이 프로젝트를 처음 보는
     방문자". 다만 **§0-1 고지(환율·수수료·단순비교·ETF 프록시·가격 모름·대조 불일치)는
     표현만 압축했고 하나도 지우지 않았습니다.** 이 파일에 문구를 더할 때도 같은 기준으로:
     "이 줄이 없으면 방문자가 숫자를 오해하는가?" 가 아니면 넣지 마세요.

지켜야 할 것
   - **환율 변환 없음** — 원화/달러를 절대 합치지 않고 시장별로 따로 계산·표시합니다.
   - **지어내지 않기(§0-1)** — 없는 스냅샷을 과거 시세로 역산하지 않습니다. 벤치마크가
     없는 날은 "없음"으로 두고 가까운 날짜로 대체하지 않습니다. 비교한 날짜를 항상 밝힙니다.
   - **읽기 전용** — 이 화면은 스냅샷을 만들지도, 고치지도 않습니다(적재는 GitHub Actions
     배치 전용이고, DB 정책(RLS)도 사용자에게 select 만 허용합니다).
   - Supabase 호출 실패는 조용히 넘기지 않고 st.error 로 사용자에게 도달시킵니다.
"""

import os
from datetime import date

import streamlit as st

# "내 성적표"와 **같은 로그인 세션**을 씁니다(같은 Supabase 프로젝트·같은 계정).
# 세션 키를 여기서 새로 정의하면 두 화면이 서로 로그인 상태를 모르게 되므로, 그 모듈의
# 상수를 그대로 가져옵니다(읽기 전용 재사용 — scorecard_view 는 한 줄도 고치지 않았습니다).
from views.scorecard_view import SESSION_CLIENT_KEY, SESSION_USER_KEY
# 🇺🇸 미국 종목명 한글 표기 — 2026-08-16(#115) 오너 요청. '내 성적표'가 2026-08-13부터 쓰고
# 있는 **바로 그 함수**를 그대로 가져다 씁니다(읽기 전용 재사용 — scorecard_view 는 이번에도
# 한 줄도 고치지 않았습니다). 같은 로직을 여기에 베껴 쓰면 언젠가 두 화면의 표기가 어긋나므로
# (오너가 말한 "들쑥날쑥") 단일 출처를 유지합니다. 아래 `_display_name()` 은 미국 종목이면
# `utils/company_names_kr.py`(정식 한글명 사전 → 자동 음역 폴백)를, 한국 종목이면 저장된
# 종목명을 그대로 돌려줍니다.
from views.scorecard_view import _display_name
from utils.scorecard_db import (
    MARKET_KR,
    MARKET_US,
    NO_FX_CONVERSION_NOTICE,
    NO_FEES_TAXES_NOTICE,
    ScorecardError,
    create_supabase_client,
    current_user,
    format_amount,
    load_universe_index,
    sign_in,
    supabase_status,
    user_id_of,
)
from utils.report_db import (
    PERIOD_OPTIONS,
    PRICE_STAMP_FIELD,
    REPORT_NO_BACKFILL_NOTICE,
    REPORT_SIMPLE_RETURN_NOTICE,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_INSUFFICIENT,
    STATUS_NO_DATA,
    US_BENCHMARK_KEYS,
    ReportError,
    benchmark_closes_for_market,
    benchmark_period_return,
    build_holding_history,
    build_weight_comparison,
    compare_holding_total,
    compute_period_report,
    fetch_user_holding_snapshots,
    fetch_user_snapshots,
    is_missing_holding_table_error,
    period_bounds,
    period_title,
    resolve_display_date,
    shift_period,
)

MARKET_TITLES = {
    MARKET_KR: "🇰🇷 한국 주식 (원화)",
    MARKET_US: "🇺🇸 미국 주식 (달러)",
}

SESSION_PERIOD_KEY = "report_period"
SESSION_REF_DATE_KEY = "report_ref_date"

# 🔴 기준일 달력 **위젯 자체의 키**와, 버튼이 "다음 렌더에서 이 날짜로 바꿔달라"고 남기는 표시.
#    이 둘을 나눠 놓는 이유는 아래 `_consume_pending_ref_date()` 주석에 적어 뒀습니다
#    (2026-08-13 #114 — 이전/최신/다음 기간 버튼이 눌러도 반응이 없던 버그의 핵심).
REF_DATE_WIDGET_KEY = "report_ref_date_input"
SESSION_PENDING_REF_DATE_KEY = "report_pending_ref_date"


# =============================================================================
# 0. 노출 제어 (§0-3-6 스테이징)
# =============================================================================
def is_report_enabled():
    """
    명시적 활성화 플래그. **기본값은 꺼짐**입니다.
    Streamlit Cloud Secrets 또는 환경변수에 `REPORT_ENABLED = "1"`(또는 true/on/yes)를
    넣었을 때만 켜집니다. 오너 승인 전에는 켜지 마세요.
    """
    raw = os.environ.get("REPORT_ENABLED")
    if raw is None:
        try:
            raw = st.secrets.get("REPORT_ENABLED")
        except Exception:
            raw = None
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_report_visible(admin_mode=False):
    """사이드바에 진입점을 만들지 여부. 관리자 미리보기 또는 명시적 플래그일 때만 True."""
    return bool(admin_mode) or is_report_enabled()


# =============================================================================
# 1. 표시 헬퍼
# =============================================================================
def _colored_pct(value, digits=2):
    """
    국내 증시 관례 — 오르면 빨강 / 내리면 파랑 (2026-08-11 오너 확정, TASK_HISTORY #79·#80).
    "내 성적표" 화면과 같은 관례를 씁니다(두 화면의 색이 어긋나면 안 됨).
    """
    if value is None:
        return "—"
    text = f"{value:+.{digits}f}%"
    if value > 0:
        return f":red[{text}]"
    if value < 0:
        return f":blue[{text}]"
    return text


def _md_amount(value, currency, decimals=None):
    """
    마크다운 텍스트에 금액을 넣을 때 전용. "$" 두 개 사이가 LaTeX 수식으로 오인되는
    Streamlit 렌더링 버그(2026-08-12, TASK_HISTORY #88)를 피하려고 이스케이프합니다.
    `st.metric` 처럼 마크다운을 거치지 않는 곳에는 `format_amount()` 를 그대로 씁니다.
    """
    return format_amount(value, currency, decimals).replace("$", "\\$")


def _render_price_stamp(market, row):
    """
    🕐 "이 블록의 숫자는 **언제 종가**로 만들어졌나" (2026-08-13 오너 요청).

    오너 원문: "미국 주식은 장 마감시간이 다르니깐 국장하고 크롤링 시간이 다른데 이 리포트
    상으로는 언제쯤 종가로 만들어진건지 눈에 확 들어오질 않아".

    ⚠️ '내 성적표'의 같은 표시와 성격이 다릅니다. 거기는 **지금 화면이 쓰는 최신 스냅샷 파일**의
       시각이라 오늘 메타데이터를 그대로 읽으면 되지만, 리포트는 **DB 에 저장된 과거 어느 날의
       값**을 보여주는 화면입니다. 그래서 오늘 파일이 아니라 **그 행이 저장될 때 배치가 기록해
       둔 시각**(`price_as_of_kst`)만 씁니다. 오늘 시각으로 대신 채우면 그 자체가 거짓말입니다.

    ⚠️ 회색 캡션 한 줄로는 묻힌다는 지적이라 **굵은 본문 한 줄**로 올렸습니다(다만 st.info 같은
       색 상자는 이 화면에 이미 많아 쓰지 않았습니다).

    ⚠️ 2026-08-13 (#114) — 문구를 **세 줄에서 한 줄로** 줄였습니다. 남긴 정보는 그대로입니다
       (어느 거래일 / 몇 시 수집 / 한국시간). 지운 것은 "그 값은 위 시각에 수집된 가격으로
       계산됐습니다" 같은 같은 말 반복과, "이후 쌓이는 스냅샷부터 시각이 표시됩니다" 같은
       내부 진행상황 설명뿐입니다.
    """
    stamp = (row or {}).get(PRICE_STAMP_FIELD)
    session_day = row["snapshot_date"].isoformat() if row and row.get("snapshot_date") else "—"

    if stamp:
        st.markdown(f"🕐 **{session_day} 종가 기준** 　·　 수집 {stamp} (한국시간)")
    else:
        # 값이 없는 과거 행 — 빈칸으로 얼버무리지 않고 "없다"고 밝힙니다(§0-1).
        #  ⚠️ 여기에 '오늘 몇 시'를 대신 넣지 마세요. 그 행이 저장될 때의 시각은 아무 데도
        #     기록돼 있지 않고, 지금 시각을 넣으면 그 자체가 지어낸 값입니다.
        st.markdown(f"🕐 **{session_day} 종가 기준** 　·　 수집 시각 정보 없음")

    if market == MARKET_US:
        st.caption("미국장은 한국시간 새벽에 마감돼 수집 시각이 거래일 다음 날로 찍힙니다.")


def _render_not_ready(status):
    st.warning(f"🚧 **사장님 보고서는 아직 준비중입니다.** ({status.reason})")
    with st.expander("🔧 오너 설정 체크리스트 (관리자용)", expanded=False):
        st.markdown(
            """
1. Supabase → SQL Editor 에서 `sql/report_schema.sql` 전체 실행
   → `portfolio_daily_snapshots` 테이블 + **RLS select 정책 1개** 생성 확인
2. GitHub → 저장소 → Settings → Secrets and variables → Actions 에 등록
   (⚠️ Streamlit Cloud Secrets 가 **아니라** GitHub Actions Secrets 입니다)
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`  ← 이 키는 **앱(Streamlit)에 절대 넣지 마세요**
3. Actions 탭에서 `Daily Report Snapshots` 워크플로우를 수동 실행해 첫 스냅샷 적재 확인
4. 앱(Streamlit Cloud) 쪽 Secrets 는 기존 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 그대로
   (리포트 화면은 읽기만 하며, 로그인 세션으로 본인 행만 조회합니다)
            """
        )


def _render_login(client):
    """
    "내 성적표"와 같은 계정으로 로그인합니다(세션 키가 같아 한쪽에서 로그인하면 양쪽 다 됩니다).
    회원가입은 "내 성적표" 화면에서만 받습니다 — 리포트는 이미 보유 종목을 넣은 사용자를 위한
    화면이라, 여기서 가입 절차를 중복해서 두지 않았습니다.
    """
    st.markdown("#### 🔐 로그인")
    st.caption("'📊 내 성적표'와 같은 계정입니다. 계정이 없다면 그 화면에서 먼저 가입해 주세요.")
    with st.form("report_login_form"):
        email = st.text_input("이메일", key="report_login_email")
        password = st.text_input("비밀번호", type="password", key="report_login_pw")
        submitted = st.form_submit_button("로그인")
    if not submitted:
        return
    try:
        response = sign_in(client, email.strip(), password)
    except ScorecardError as exc:
        st.error(f"🚫 {exc}")
        return
    user = getattr(response, "user", None)
    if user is None:
        st.error("🚫 로그인에 실패했습니다(사용자 정보를 받지 못했습니다).")
        return
    st.session_state[SESSION_USER_KEY] = user
    st.rerun()


# =============================================================================
# 2. 기간 선택
# =============================================================================
def _consume_pending_ref_date():
    """
    '◀ 이전 기간 / 최신 기간 / 다음 기간 ▶' 버튼이 남겨 둔 새 기준일을, 달력 위젯이 만들어지기
    **전에** 그 위젯의 진짜 키에 대입합니다. 반드시 `_render_period_controls()` 가 위젯을
    하나도 만들기 전에 불러야 합니다.

    ⚠️ 2026-08-13 (#114) — 오너 신고: "일간으로 했을 때 맨위에 있는 이전기간 / 최신기간 /
       다음기간 저거 작동 안하고 있어". 코드를 따라가 보니 원인이 두 겹이었습니다.

       ① `st.date_input(..., key="report_ref_date_input")` 처럼 **키를 준 위젯**은 한 번
          만들어지고 나면 다음 재실행부터 `value=` 인자를 무시하고
          `st.session_state["report_ref_date_input"]` 을 우선합니다. 그래서 버튼이 다른 키
          (`report_ref_date`)를 아무리 바꿔도 화면의 달력은 옛 날짜 그대로였습니다.
       ② 게다가 함수 **맨 끝**에 `st.session_state[SESSION_REF_DATE_KEY] = ref_date` 가 있어서,
          버튼이 방금 넣어 둔 새 날짜를 그 옛 위젯 값으로 도로 덮어썼습니다. 두 겹이 겹쳐
          "눌러도 아무 일도 안 일어나는" 증상이 됐습니다(예외도 안 나므로 조용히 씹힘).

       고치는 방법은 "위젯 키에 **대입**하기"뿐인데, 위젯이 이미 만들어진 뒤(=버튼 처리 시점)
       에는 대입이 금지돼 있습니다. 그래서 '내 성적표'가 같은 함정을 넘을 때 쓴 검증된 관례
       (`views/scorecard_view.py` 의 `_reset_input_fields()` / `_consume_pending_reset()`,
       TASK_HISTORY #85)를 그대로 따릅니다 — 버튼은 **pending 표시만** 남기고 `st.rerun()`,
       실제 대입은 다음 렌더 맨 앞(여기)에서 합니다.
    """
    pending = st.session_state.pop(SESSION_PENDING_REF_DATE_KEY, None)
    if pending is None:
        return
    # 대입이라야 브라우저(프런트엔드)까지 새 값이 전달됩니다 — pop 만으로는 전달되지 않습니다.
    st.session_state[REF_DATE_WIDGET_KEY] = pending
    st.session_state[SESSION_REF_DATE_KEY] = pending


def _render_period_controls():
    """
    기간 종류 + 기준일 선택. 최신(오늘 기준)이 기본이고, 과거 기간도 자유롭게 볼 수 있습니다.
    반환: (period, ref_date)
    """
    _consume_pending_ref_date()   # ⚠️ 반드시 위젯을 만들기 전(맨 앞)에

    labels = {code: label for code, label in PERIOD_OPTIONS}
    codes = [code for code, _ in PERIOD_OPTIONS]

    col_period, col_date = st.columns([2, 2])
    with col_period:
        period = st.selectbox(
            "기간", codes,
            index=codes.index(st.session_state.get(SESSION_PERIOD_KEY, "MONTHLY"))
            if st.session_state.get(SESSION_PERIOD_KEY, "MONTHLY") in codes else 2,
            format_func=lambda code: labels[code],
            key="report_period_select",
        )
    st.session_state[SESSION_PERIOD_KEY] = period

    # 첫 렌더에서만 초기값을 심고, 그 뒤로는 위젯 키가 유일한 출처입니다.
    #  ⚠️ `value=` 를 함께 주면 안 됩니다 — 세션 상태로 값을 정한 위젯에 기본값까지 주면
    #     Streamlit 이 화면에 노란 경고 상자를 띄웁니다(그리고 둘 중 뭐가 이기는지도 헷갈립니다).
    if REF_DATE_WIDGET_KEY not in st.session_state:
        st.session_state[REF_DATE_WIDGET_KEY] = \
            st.session_state.get(SESSION_REF_DATE_KEY) or date.today()
    with col_date:
        ref_date = st.date_input("기준일", key=REF_DATE_WIDGET_KEY)
    if isinstance(ref_date, (list, tuple)):  # 범위 선택 위젯으로 잘못 동작할 때의 방어
        ref_date = ref_date[0]

    col_prev, col_now, col_next = st.columns(3)
    if col_prev.button("◀ 이전 기간", key="report_prev_period", use_container_width=True):
        st.session_state[SESSION_PENDING_REF_DATE_KEY] = shift_period(period, ref_date, -1)
        st.rerun()
    if col_now.button("최신 기간", key="report_latest_period", use_container_width=True):
        st.session_state[SESSION_PENDING_REF_DATE_KEY] = date.today()
        st.rerun()
    if col_next.button("다음 기간 ▶", key="report_next_period", use_container_width=True):
        st.session_state[SESSION_PENDING_REF_DATE_KEY] = shift_period(period, ref_date, 1)
        st.rerun()

    st.session_state[SESSION_REF_DATE_KEY] = ref_date
    return period, ref_date


# =============================================================================
# 3. 리포트 본문
# =============================================================================
def _render_shortage(report):
    """
    §3(작업지시서): 데이터가 부족한 구간은 **작은 경고 문구 하나 붙인 정상 리포트**처럼
    꾸미지 않고, 부족하다는 사실 자체를 주 컨텐츠로 보여줍니다.
    """
    st.error(f"📭 **데이터 부족** — {report['status_message']}")
    st.caption(REPORT_NO_BACKFILL_NOTICE)

    if report["status"] == STATUS_NO_DATA:
        return
    # 부족하더라도 지금까지 쌓인 값 자체는 숨기지 않습니다(숨기면 그것대로 불친절) —
    # 다만 "정식 리포트"와 명확히 구분되도록 접어 둡니다.
    with st.expander("그래도 지금까지 쌓인 만큼만 보기 (정식 리포트 아님)", expanded=False):
        _render_numbers(report, incomplete=True)


def _render_numbers(report, incomplete=False):
    baseline, latest = report["baseline"], report["latest"]
    currency = report.get("currency") or ("KRW" if report.get("market") == MARKET_KR else "USD")

    # 무엇과 무엇을 비교했는지는 §0-1 상 절대 뺄 수 없습니다 — 대신 괄호 설명을 줄였습니다.
    st.caption(
        f"비교 구간: **{baseline['snapshot_date'].isoformat()}** → "
        f"**{latest['snapshot_date'].isoformat()}** "
        + ("(기간 시작 직전 기록이 기준점)"
           if report["baseline_kind"] == "prior_close"
           else "(기간 시작 전 기록이 없어 기간 안 첫 기록이 기준점)")
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("기간 시작 평가금액", format_amount(baseline.get("total_value"), currency))
    col2.metric("기간 종료 평가금액", format_amount(latest.get("total_value"), currency))
    col3.metric("평가금액 변화", format_amount(report.get("value_change"), currency),
                delta_color="off")
    col3.markdown(_colored_pct(report.get("value_change_pct")))

    col4, col5 = st.columns(2)
    col4.metric("기간 시작 누적수익률", "—" if report.get("profit_pct_start") is None
                else f"{report['profit_pct_start']:+.2f}%")
    col5.metric("기간 종료 누적수익률", "—" if report.get("profit_pct_end") is None
                else f"{report['profit_pct_end']:+.2f}%")
    # 공식(= (평가금액−매입원가)÷매입원가)은 뺐지만, **누적과 기간 변화가 다른 숫자**라는
    # 사실은 남깁니다 — 바로 위에 두 값이 나란히 있어서 헷갈리면 숫자를 오해하게 됩니다.
    st.caption("누적수익률은 매수 시점부터의 누적입니다(이 기간의 변화가 아닙니다).")

    if incomplete:
        st.warning("⚠️ 위 숫자는 기간 전체가 아니라 **실제로 쌓인 구간만**의 값입니다.")

    # 구성 변경·가격 결측 안내를 색 상자 두 개로 나눠 띄우면 화면이 그만큼 길어져서,
    # 내용은 그대로 두고 **경고 상자 하나로 합쳤습니다**(둘 다 §0-1 고지라 삭제 불가).
    alerts = list(report.get("composition_notes") or []) if report.get("composition_changed") else []
    if report.get("coverage_note"):
        alerts.append(report["coverage_note"])
    if alerts:
        st.warning("⚠️ " + " ".join(alerts))


def _benchmark_short_label(label):
    """
    'S&P 500 (SPY ETF 종가 기준)' → 'S&P 500'. 평균 줄 하나에 두 벤치마크 이름을 나란히
    넣으려고 괄호 안 설명만 떼어냅니다. 프록시라는 사실은 바로 위 두 줄의 라벨과 맨 아래
    한 줄 고지에 그대로 남아 있으므로 여기서 정보가 사라지지는 않습니다(§0-1).
    """
    text = (label or "").strip()
    return text.split(" (")[0].strip() or text


def _render_benchmark_average(outcomes, market, mine):
    """
    🇺🇸 **미국 두 벤치마크 수익률의 단순 평균** 한 줄 (2026-08-16 #116, 오너 요청).

    오너 원문: 수기로 관리하던 "2025년수익률 비교 - 연말 성적표.csv" 에 코스피·S&P500·나스닥
    각각과 비교하는 줄 말고 **"VOO / QQQ 평균 수익률"** 줄이 따로 있었고, "모든 기간의 벤치마크
    비교에 추가를 하면 좋겠는데" 라고 요청했습니다. 미국 대표 두 지수를 반반 들고 있었다면
    얼마였을지를 한 줄로 보는 용도입니다(기간 시작에 반반 사서 그대로 뒀다면 그 수익률은
    두 수익률의 산술 평균과 정확히 같습니다).

    ⚠️ **라벨을 'VOO / QQQ' 라고 쓰지 않습니다.** 오너의 수기 표는 VOO·QQQ 로 적혀 있었지만,
       이 프로젝트가 실제로 수집·저장하는 값은 **SPY(S&P500 프록시)·ONEQ(나스닥 종합 프록시)
       종가**입니다(`collector_us_indices.US_INDEX_BENCHMARKS`). 가지고 있지도 않은 VOO/QQQ
       종가로 계산한 것처럼 적으면 그 자체가 지어낸 값입니다(§0-1). 그래서 라벨은 위 두 줄에
       실제로 찍힌 벤치마크 이름을 그대로 이어 붙여 만듭니다.
    ⚠️ **둘 다 계산됐을 때만** 그립니다. 한쪽 종가가 없어 '비교 불가'인 기간에 나머지 하나로
       평균을 만들면 그건 평균이 아니고, "평균: 데이터 없음" 같은 줄도 넣지 않습니다 —
       계산할 수 없으면 **조용히 생략**합니다. 벤치마크가 하나뿐인 한국 시장도 마찬가지로
       이 줄이 아예 나오지 않습니다.
    ⚠️ 시작·종가 괄호(`( 600.00 → 660.00 )`)는 붙이지 않습니다. 서로 다른 두 ETF 의 가격을
       평균 낸 숫자는 아무 뜻도 없는 값이라, 수익률의 평균만 보여 줍니다.
    """
    if market != MARKET_US:
        return
    picked = [outcomes.get(key) for key in US_BENCHMARK_KEYS]
    if any(item is None or not item[1]["available"] for item in picked):
        return

    average = sum(item[1]["change_pct"] for item in picked) / len(picked)
    names = " / ".join(_benchmark_short_label(item[0]["label"]) for item in picked)
    line = f"- **{names} 평균** {_colored_pct(average)}"
    if mine is not None:
        gap = mine - average
        line += f" · 내 포트폴리오 {_colored_pct(mine)} → 차이 {gap:+.2f}%p"
    st.markdown(line)


def _render_benchmarks(report, market):
    """포트폴리오와 **정확히 같은 두 날짜**로 벤치마크 수익률을 계산해 나란히 보여줍니다."""
    st.markdown("##### 📊 벤치마크 비교")
    benchmarks = benchmark_closes_for_market(market)
    if not benchmarks:
        # 색 상자(st.info) → 캡션으로. "데이터가 없다"는 사실만 남기고 배치·워크플로우 이름 같은
        # 개발 쪽 이야기는 뺐습니다(방문자가 할 수 있는 일이 아무것도 없는 정보).
        st.caption("이 시장의 벤치마크 데이터가 아직 없어 비교를 생략합니다.")
        return

    baseline_date = report["baseline"]["snapshot_date"]
    end_date = report["latest"]["snapshot_date"]
    mine = report.get("value_change_pct")

    has_proxy = False
    # 평균 줄(아래 `_render_benchmark_average()`)이 쓰려고 계산 결과를 심볼별로 들고 있습니다.
    # 같은 수익률을 두 번 계산하지 않기 위한 것이라, 위 줄들과 평균 줄의 숫자는 항상 같습니다.
    outcomes = {}
    for benchmark in benchmarks:
        outcome = benchmark_period_return(benchmark["closes"], baseline_date, end_date)
        outcomes[benchmark["symbol"]] = (benchmark, outcome)
        if not outcome["available"]:
            st.markdown(f"- **{benchmark['label']}**: 비교 불가 — {outcome['reason']}")
            continue
        has_proxy = has_proxy or bool(benchmark.get("is_proxy"))
        line = (f"- **{benchmark['label']}** {_colored_pct(outcome['change_pct'])} "
                f"( {outcome['start_value']:,.2f} → {outcome['end_value']:,.2f} )")
        if mine is not None:
            gap = mine - outcome["change_pct"]
            line += f" · 내 포트폴리오 {_colored_pct(mine)} → 차이 {gap:+.2f}%p"
        st.markdown(line)

    # 🇺🇸 미국 두 벤치마크가 **둘 다** 계산됐을 때만 평균 한 줄이 더 붙습니다(#116).
    _render_benchmark_average(outcomes, market, mine)

    if has_proxy:
        # ⚠️ 이 고지는 §0-1 상 삭제 불가입니다(지수 자체가 아니라 ETF 종가라는 사실). 다만
        #    벤치마크마다 한 줄씩 반복하지 않고 **맨 아래 한 줄**로 모았습니다 — 종목 라벨에
        #    이미 "(SPY ETF 종가 기준)"이 들어 있어 두 번 말하던 상태였습니다.
        st.caption("지수 포인트가 아니라 추종 ETF 종가 기준입니다(기간 비교용 근사치).")


def _render_snapshot_table(rows_in_window, currency):
    with st.expander("이 기간에 저장된 스냅샷 원본 보기", expanded=False):
        if not rows_in_window:
            st.caption("이 기간에 저장된 스냅샷이 없습니다.")
            return
        lines = ["| 거래일 | 종가 수집 시각(KST) | 평가금액 | 매입원가 | 담긴 종목 | 벤치마크 |",
                 "|---|---|---|---|---|---|"]
        for row in rows_in_window:
            benchmark = (f"{row.get('benchmark_symbol')} {row.get('benchmark_value'):,.2f}"
                         if row.get("benchmark_value") is not None
                         else f"{row.get('benchmark_symbol') or '—'} 없음")
            # 날짜마다 수집 시각이 다를 수 있어(수집 지연·재수집) 행별로 그날 값을 그대로 씁니다.
            lines.append(
                f"| {row['snapshot_date'].isoformat()} "
                f"| {row.get(PRICE_STAMP_FIELD) or '기록 없음'} "
                f"| {_md_amount(row.get('total_value'), currency)} "
                f"| {_md_amount(row.get('total_cost'), currency)} "
                f"| {row.get('priced_count')}/{row.get('holdings_count')} "
                f"| {benchmark} |"
            )
        st.markdown("\n".join(lines))
        # 이 표 자체가 접힌 원본 보기라 설명은 컬럼 뜻 한 줄이면 충분합니다.
        st.caption("'담긴 종목' = 그날 현재가를 알아 합계에 들어간 종목 수 / 전체 보유 종목 수.")


def _md_cell(text):
    """
    마크다운 표의 한 칸에 넣을 문자열을 안전하게 만듭니다.
    종목명에 '|' 가 들어 있으면 표가 통째로 깨지므로 이스케이프합니다(있을 법하지 않지만,
    사용자가 직접 입력하는 값이라 화면이 깨질 여지를 남기지 않습니다).
    """
    return str(text if text is not None else "").replace("|", "\\|").strip() or "—"


def _display_indexes(market):
    """
    미국 종목 한글명을 '내 성적표'와 **완전히 같은 값**으로 만들기 위해, 그 화면이 쓰는 것과
    같은 유니버스 스냅샷(`data/us_stocks_latest.json`)을 같은 로더로 읽어 옵니다.
    반환 형태는 `_display_name(row, indexes)` 가 기대하는 `{시장: {티커: 종목dict}}` 입니다.

    · 상위 550 유니버스 **안** 종목은 이 파일에 수집 시점 계산해 넣어 둔 `name_kr` 이 들어 있어
      공개 미국주식 화면·내 성적표와 글자 하나까지 같은 표기가 됩니다.
    · 유니버스 **밖** 종목은 여기에 없고, 그때는 `_display_name()` 안쪽이
      `resolve_korean_name()` 을 즉석 호출해 보조로 만듭니다(그마저 못 만들면 영문명/티커).
    · 한국 시장 블록에서는 한글명 변환이 필요 없으므로 파일을 **아예 읽지 않습니다**.
    · 파일이 없거나(아직 수집 전) 읽기에 실패해도 화면을 죽이지 않고 빈 dict 로 넘어갑니다 —
      그 경우에도 위 폴백 경로가 그대로 동작하므로 이름이 사라지지는 않습니다.
    """
    if market != MARKET_US:
        return {}
    try:
        us_index, _meta = load_universe_index(MARKET_US)
    except Exception:   # noqa: BLE001 — 이름 표기 하나 때문에 리포트 전체가 죽으면 안 됩니다
        return {}
    return {MARKET_US: us_index or {}}


def _holding_name(row, market=None, indexes=None):
    """
    화면에 쓸 **종목명만**(코드 없이). 이름을 끝내 못 찾으면 지어내지 않고 티커 그대로입니다
    (§0-1). 미국 종목은 한글명 — 규칙과 근거는 아래 `_holding_label()` 주석 참고.
    """
    probe = dict(row)
    probe["market"] = market or row.get("market")
    name = (_display_name(probe, indexes or {}) or "").strip()
    return name or (row.get("ticker") or "").strip() or "—"


def _holding_label(row, market=None, indexes=None):
    """
    '삼성전자 (005930)' / 이름이 없으면 '005930'. '내 성적표' 표의 표기 관례와 같습니다.

    🇺🇸 2026-08-16 (#115) 오너 요청 — "미국 주식 이쪽에 종목 설명 있는 부분에는 한국식
       발음으로 넣으면 안되는거야? 스페이스 X 애플, 엔비디아, 마이크로소프트 이런식으로".
       종목별 스냅샷에는 저장 당시의 **영문 원문**(예: "Advanced Micro Devices Inc. Common
       Stock")이 들어 있는데, 리포트 화면만 그걸 그대로 뿌리고 있어서 '내 성적표'와 표기가
       달랐습니다. 여기서 `_display_name()` 을 거치면 미국 종목만 한글명이 되고 한국 종목은
       그대로입니다. **DB 값은 고치지 않습니다** — 표시 시점에만 바꾸는 것이라 과거 기록을
       손댈 일이 없고, '내 성적표'가 쓰는 방식과도 같습니다.

    ⚠️ `market` 을 따로 받는 이유: `build_holding_history()` 의 `gone` 목록과
       `build_weight_comparison()` 의 행에는 `market` 키가 없습니다(같은 시장 안에서만 쓰는
       파생 구조라 넣지 않은 것). 그 행들도 미국 한글명을 받게 하려면 호출부가 이미 알고 있는
       시장을 넘겨 줘야 합니다. 넘기지 않으면 예전처럼 행의 `market` 을 봅니다.
    """
    probe = dict(row)
    probe["market"] = market or row.get("market")
    name = (_display_name(probe, indexes or {}) or "").strip()
    ticker = (row.get("ticker") or "").strip() or "—"
    return _md_cell(f"{name} ({ticker})" if name else ticker)


def _md_qty(value):
    """수량 표기 — '내 성적표' 표와 같은 형식(정수는 정수로, 소수점은 필요한 만큼만)."""
    if value is None:
        return "—"
    return f"{value:,.6g}"


def _md_weight(value):
    """
    비중(%) 표기. **값이 없으면 0% 가 아니라 "모름"** 입니다 — 그날 가격을 몰라 평가금액
    자체를 모르는 종목이고, 0% 로 적으면 "가진 게 없다"는 다른 뜻이 됩니다(§0-1).
    """
    if value is None:
        return "모름"
    return f"{value:.2f}%"


def _colored_pp(value):
    """
    비중 **변화량**(퍼센트포인트) 표기. 색 관례는 수익률과 같습니다(늘면 빨강/줄면 파랑).
    ⚠️ 단위는 % 가 아니라 %p 입니다 — 50%→75% 는 "+25%p"(비중이 25포인트 늘어남)이지
       "+25%"(1.5배)가 아닙니다. 오너 원본 표는 '%'로 적혀 있었지만 여기서는 정확히 씁니다.
    """
    if value is None:
        return "—"
    text = f"{value:+.2f}%p"
    if value > 0:
        return f":red[{text}]"
    if value < 0:
        return f":blue[{text}]"
    return text


def _render_weight_changes(history, base_date, market=None, indexes=None):
    """
    📊 **비중 변화** — 2026-08-13(#114) 신설. 오너가 수기로 관리하던 표
    ("종목 | 지난달 비중 | 이번달 비중 | 차이")를 그대로 옮긴 것입니다.

    ⚠️ 비교 시작점은 "지난 기간"이 아니라 **이 기간 안의 첫 기록일**입니다. 종목별 스냅샷은
       보고 있는 기간만 조회하므로 기간 이전의 종목별 기록은 애초에 손에 없습니다 —
       그래서 두 날짜를 표 머리글에 그대로 박아 둡니다(무엇과 무엇을 비교했는지 숨기지 않기).
    ⚠️ 기록이 하루뿐이면 표 자체를 그리지 않습니다(비교할 게 없는데 0%p 를 늘어놓지 않기).
    ⚠️ 2026-08-16 (#115) — 종목 칸도 위 종목별 상세 표와 **같은 라벨 함수**를 씁니다(미국은
       한글명). 여기만 영문으로 남으면 같은 화면 안에서 같은 종목이 두 이름으로 보입니다.
       `build_weight_comparison()` 의 행에는 `market` 키가 없어 호출부의 시장을 넘겨 받습니다.
    """
    weights = build_weight_comparison(history)
    if not weights["comparable"] or not weights["rows"]:
        return

    first_label = weights["first_date"].isoformat()
    base_label = base_date.isoformat()
    st.caption(f"📊 **비중 변화** — {first_label} → {base_label}")

    lines = [f"| 종목 | {first_label} | {base_label} | 변화 |", "|---|---:|---:|---:|"]
    for row in weights["rows"]:
        lines.append(
            f"| {_holding_label(row, market, indexes)} | {_md_weight(row['first_pct'])} "
            f"| {_md_weight(row['base_pct'])} | {_colored_pp(row['change_pp'])} |"
        )
    st.markdown("\n".join(lines))

    if weights["unpriced_first"] or weights["unpriced_base"]:
        # 정상일 땐 조용히, 실제로 '모름'이 있을 때만.
        st.caption("가격을 몰랐던 종목은 비중을 '모름'으로 두고 분모에서 뺐습니다(0%로 치지 않습니다).")


def _render_holding_history(market, holding_rows, snapshots_in_window,
                            window_start, window_end, currency, error=None):
    """
    🧾 종목별 상세 — 2026-08-13 오너 결정으로 신설한 섹션.

    오너 원문: "대신 가독성을 최대한 살린 한장으로 볼 수 있는 테이블을 잘 짜줘 … 나중에 유료로
    할 정도로 자료가 많아지는데 들쑥날쑥하면 세상의 모두가 힘들어져".

    그래서 이렇게 짰습니다.
      · **한 장** — 기간 안의 모든 날짜 × 모든 종목을 늘어놓지 않습니다. 기간 안 **마지막
        기록일 하루**의 종목별 상태를 평가금액 큰 순으로 한 표에 담고, 맨 아래 합계 한 줄을
        둡니다. 종목이 10개면 11줄이라 스크롤 없이 들어옵니다.
      · **일별 추이는 펼쳐서** — 종목 하나를 고르면 그 종목의 기간 내 일별 표가 나옵니다.
        (종목 수만큼 expander 를 늘어놓으면 그 자체가 '한 장'을 깨뜨려서 선택 방식으로 했습니다.)
      · **날짜를 섞지 않습니다** — 표의 모든 행은 같은 거래일 값입니다. 종목마다 각자의 마지막
        기록일을 긁어 모으면 합계가 그 어떤 날의 합계와도 같지 않게 됩니다.
      · **들쑥날쑥 감시** — 이 표의 합계와 같은 날 합계 스냅샷을 매번 대조합니다. 2026-08-13
        (#114)부터 **어긋났을 때만** 경고를 띄우고, 정상일 때는 아무 말도 하지 않습니다
        (오너 지적: "데이터 대조 통과" 같은 줄은 개발자용 자체 검증 문구라 방문자에게는 소음).
      · 색·금액 표기는 '내 성적표' 표와 같은 관례(오르면 빨강/내리면 파랑, format_amount).
      · 가격을 몰랐던 날은 빈칸이 아니라 **"가격 모름"** — 이전 가격을 대신 넣지 않습니다(§0-1).
      · **비중(%)** 칸은 2026-08-13(#114)에 추가했습니다 — 오너가 수기로 관리하던 표
        ("종목 | 현재금액 | 현재 금액 합 | 비율")를 그대로 옮긴 것입니다.
    """
    st.markdown("##### 🧾 종목별 상세")

    if error is not None:
        if is_missing_holding_table_error(error):
            # 아직 표가 없는 상태(오너가 SQL 실행 전). 리포트의 나머지는 정상이므로 이 섹션만
            # 안내로 대체합니다. 설치 절차 전문은 관리자용이라 접어 두고, 방문자에게는 "아직
            # 준비되지 않았다"는 사실 한 줄만 보입니다.
            st.info("ℹ️ 종목별 상세는 아직 준비되지 않았습니다.")
            with st.expander("🔧 관리자: 이 표를 켜는 방법", expanded=False):
                st.markdown(
                    "Supabase → SQL Editor 에서 `sql/report_schema.sql` 전체를 다시 실행하세요"
                    "(여러 번 실행해도 안전하고 기존 기록은 그대로입니다). 실행한 **다음 날 "
                    "배치부터** 종목별 기록이 쌓이며, 그 이전 날짜는 소급해서 만들지 않습니다."
                )
        else:
            st.error(f"🚫 종목별 기록을 불러오지 못했습니다: {error}")
        return

    try:
        history = build_holding_history(holding_rows or [], window_start, window_end)
    except (ReportError, ScorecardError) as exc:
        st.error(f"🚫 {exc}")
        return

    if not history["rows"]:
        st.caption(
            "이 기간에는 종목별 기록이 없습니다(종목별 저장은 2026-08-13부터 — 그 이전 날짜는 "
            "합계만 남아 있고 소급해서 만들지 않습니다)."
        )
        return

    base_date = history["base_date"]
    totals = history["totals"]
    dates = history["dates"]

    # 🇺🇸 미국 블록일 때만 유니버스 스냅샷을 한 번 읽어 아래 모든 라벨에 같은 값을 씁니다
    #    (2026-08-16 #115). 한 섹션 안에서 표마다 파일을 다시 읽으면 느릴 뿐 아니라, 읽는
    #    사이에 배치가 파일을 갈아끼우면 표마다 이름이 달라질 수 있어 한 번만 읽습니다.
    indexes = _display_indexes(market)

    st.caption(
        f"**{base_date.isoformat()}** 하루 기준 "
        f"(이 기간 기록 {len(dates)}일: {dates[0].isoformat()} ~ {dates[-1].isoformat()})"
    )

    lines = ["| 종목 | 비중 | 수량 | 평균매입가 | 현재가 | 평가금액 | 평가손익 | 수익률 | 주가등락 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in history["rows"]:
        if row["priced"]:
            price_cell = _md_amount(row["current_price"], currency)
            value_cell = _md_amount(row["market_value"], currency)
            profit_cell = _md_amount(row["profit"], currency)
            pct_cell = _colored_pct(row["profit_pct"])
        else:
            # 빈칸으로 얼버무리거나 이전 가격을 대신 넣지 않습니다(§0-1).
            price_cell = "**가격 모름**"
            value_cell = profit_cell = pct_cell = "—"
        lines.append(
            f"| {_holding_label(row, market, indexes)} | {_md_weight(row.get('weight_pct'))} "
            f"| {_md_qty(row['quantity'])} "
            f"| {_md_amount(row['avg_purchase_price'], currency)} | {price_cell} "
            f"| {value_cell} | {profit_cell} | {pct_cell} "
            f"| {_colored_pct(row['price_change_pct'])} |"
        )
    # 합계 줄 — 칸 순서: 종목 / 비중 / 수량 / 평균매입가(=매입원가 합) / 현재가 / 평가금액 /
    #            평가손익 / 수익률 / 주가등락   (헤더와 9칸으로 정확히 맞춤)
    #  '평균매입가' 칸에는 단가가 아니라 **원가 합계**가 들어가므로, 예전에 캡션으로 길게
    #  설명하던 것을 칸 안에 '원가합'이라고 써 넣어 설명 자체가 필요 없게 만들었습니다.
    lines.append(
        f"| **합계 {totals['holdings_count']}종목** "
        # 그날 가격을 아는 종목이 하나도 없으면 분모 자체가 없습니다 — 그때 '100%'라고 쓰면
        # 아무것도 계산하지 않고 다 계산한 척하는 게 됩니다(§0-1).
        f"| **{'100.00%' if totals['market_value'] is not None else '—'}** "
        f"| "
        f"| **원가합 {_md_amount(totals['cost'], currency)}** "
        f"| "
        f"| **{_md_amount(totals['market_value'], currency)}** "
        f"| **{_md_amount(totals['profit'], currency)}** "
        f"| {_colored_pct(totals['profit_pct'])} "
        f"| |"
    )
    st.markdown("\n".join(lines))
    # 바로 옆 칸의 '수익률'과 뜻이 달라서 이 한 줄은 남깁니다(오해하면 숫자를 잘못 읽습니다).
    st.caption("주가등락 = 이 기간 첫 기록가 → 기준일 종가 (수량 변화와 무관한 주가만의 등락)")
    if totals["unpriced_count"]:
        # 정상일 땐 조용히, 실제로 빠진 종목이 있을 때만 — 합계·비중의 분모가 달라지므로
        # 이건 §0-1 상 반드시 알려야 하는 정보입니다.
        st.caption(
            f"⚠️ 그날 가격을 몰라 합계·비중에서 빠진 종목 {totals['unpriced_count']}개 — "
            f"그 종목까지 포함한 매입원가는 {_md_amount(totals['cost_all'], currency)} 입니다."
        )

    _render_weight_changes(history, base_date, market, indexes)

    # ---- 🔴 들쑥날쑥 감시 — 같은 날 합계 스냅샷과 대조 --------------------------
    summary_row = next((r for r in (snapshots_in_window or [])
                        if r.get("snapshot_date") == base_date), None)
    outcome = compare_holding_total(
        totals["market_value"], summary_row.get("total_value") if summary_row else None)
    # ⚠️ 2026-08-13 (#114) — **어긋났을 때만** 말합니다.
    #    · 일치: 아무것도 그리지 않습니다. "데이터 대조 통과"는 우리끼리 쓰는 자체 검증 문구라
    #      방문자에게는 뜻이 닿지 않고, 정상일 때 매번 뜨면 진짜 경고가 묻힙니다.
    #    · 대조 불가: 역시 조용히 넘어갑니다. 말하지 않는 것과 "일치한다"고 말하는 것은 전혀
    #      다릅니다 — 이 화면은 어디에서도 대조 결과를 주장하지 않으므로 §0-1 위반이 아닙니다.
    #    · 불일치: 그대로 경고합니다(숨기지 않기 — 이게 이 대조의 존재 이유).
    if outcome["comparable"] and not outcome["matches"]:
        st.warning(
            f"⚠️ **대조 불일치** — 종목별 합계({_md_amount(totals['market_value'], currency)})와 "
            f"같은 날 합계 스냅샷({_md_amount(summary_row.get('total_value'), currency)})이 "
            f"서로 다릅니다(차이 {outcome['diff']:+,.6f}). 그날 종목별 저장이 중간에 실패했을 수 "
            "있습니다 — 다음 배치가 같은 날짜를 다시 저장하면 맞춰집니다."
        )

    if history["gone"]:
        # 여기도 같은 라벨 규칙(미국은 한글명) — 이 줄만 영문으로 남으면 바로 위 표와
        # 다른 이름이 보입니다. `gone` 행에는 market 키가 없어 시장을 넘겨 줍니다(#115).
        gone_text = ", ".join(
            f"{_holding_name(g, market, indexes)}({g['ticker']}, "
            f"마지막 기록 {g['last_date'].isoformat()})"
            for g in history["gone"]
        )
        st.caption(f"⏹ 기간 중 기록이 끊긴 종목(매도 등): {gone_text}")

    # ---- 종목 하나를 골라 일별 추이 보기 ---------------------------------------
    with st.expander("📅 종목 하나를 골라 이 기간 일별 추이 보기", expanded=False):
        options = [row["ticker"] for row in history["rows"]] + \
                  [g["ticker"] for g in history["gone"]]
        # 고르는 목록의 라벨도 표와 같은 규칙(미국은 한글명) — 표에서 "엔비디아"로 본 종목을
        # 여기서 영문 풀네임으로 찾게 하면 같은 화면 안에서 이름이 두 개가 됩니다(#115).
        label_by_ticker = {row["ticker"]: _holding_label(row, market, indexes)
                           for row in history["rows"]}
        for g in history["gone"]:
            label_by_ticker[g["ticker"]] = _holding_label(g, market, indexes)
        picked = st.selectbox(
            "종목", options,
            format_func=lambda t: label_by_ticker.get(t, t),
            key=f"report_holding_pick_{market}",
        )
        daily = history["daily_by_ticker"].get(picked) or []
        if not daily:
            st.caption("이 종목의 일별 기록이 없습니다.")
            return
        rows_md = ["| 거래일 | 종가 수집 시각(KST) | 수량 | 현재가 | 평가금액 | 평가손익 | 수익률 |",
                   "|---|---|---:|---:|---:|---:|---:|"]
        for row in daily:
            if row["priced"]:
                cells = (_md_amount(row["current_price"], currency),
                         _md_amount(row["market_value"], currency),
                         _md_amount(row["profit"], currency),
                         _colored_pct(row["profit_pct"]))
            else:
                cells = ("**가격 모름**", "—", "—", "—")
            rows_md.append(
                f"| {row['snapshot_date'].isoformat()} "
                f"| {row.get(PRICE_STAMP_FIELD) or '기록 없음'} "
                f"| {_md_qty(row['quantity'])} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |"
            )
        st.markdown("\n".join(rows_md))
        st.caption("저장된 날만 나옵니다(휴장일 등 빠진 날을 이전 값으로 채우지 않습니다).")


def _render_substitute_notice(period, ref_date, display_date):
    """
    📅 "선택하신 날은 거래일이 아니라, 가장 최근 거래일 자료를 보여드립니다" 안내
    (2026-08-16 #117, 오너 요청).

    🔴 이 한 줄이 이 기능의 **전제 조건**입니다(§0-1). 화면에 "2026-08-16(일) 기준"이라고
       써 놓고 실제로는 2026-08-14(금) 숫자를 보여주면 그건 지어낸 것과 같은 수준의 거짓말이
       됩니다. 그래서 회색 캡션이 아니라 **눈에 띄는 경고 상자**로, 두 날짜를 **둘 다** 적어
       띄웁니다(무엇을 골랐고, 실제로는 언제 자료를 보고 있는지).

    ⚠️ "휴장일" 이라고 단정하지 않습니다 — 이 프로젝트는 거래일 캘린더를 갖고 있지 않고,
       기록이 없는 이유는 휴장일 수도 있고 그날 배치가 실패했을 수도 있습니다. 그래서
       확인된 사실("그날은 저장된 기록이 없다")만 말합니다.
    """
    st.warning(
        f"📅 **{period_title(period, ref_date)}** 은(는) 저장된 기록이 없는 날입니다"
        "(주말·공휴일 등 장이 열리지 않은 날). 대신 **그 이전 가장 최근 기록일인 "
        f"{period_title(period, display_date)}** 자료를 보여드립니다 — "
        f"아래 숫자는 전부 {display_date.isoformat()} 기준이며, "
        f"{ref_date.isoformat()} 의 값이 아닙니다."
    )


def _render_market_block(market, snapshots, period, ref_date,
                         holding_rows=None, holding_error=None):
    st.markdown(f"### {MARKET_TITLES.get(market, market)}")

    # 📅 '일간'에서 기준일이 거래일이 아니면 그 이전 가장 최근 기록일로 대체합니다(#117).
    #    아래는 **그 날짜 하나만 바꿔서** 기존 렌더링 경로를 그대로 태웁니다 — 대체 전용
    #    화면을 따로 만들면 평일과 주말의 표가 서로 달라질 여지가 생깁니다.
    #    시장별로 따로 구하는 이유: 미국장은 한국장과 마지막 거래일이 다를 수 있습니다.
    display_date, substituted = resolve_display_date(snapshots, period, ref_date)
    if substituted:
        _render_substitute_notice(period, ref_date, display_date)

    report = compute_period_report(snapshots, period, display_date)
    window_start, window_end = report["window_start"], report["window_end"]
    st.caption(f"{period_title(period, display_date)} · 달력 기준 {window_start} ~ {window_end}")

    # 🕐 이 블록이 실제로 보여주는 **마지막 스냅샷 행**의 가격 수집 시각(한국시간).
    #    스냅샷이 하나도 없는 구간(NO_DATA)에는 보여줄 행 자체가 없으므로 생략합니다.
    if report.get("latest"):
        _render_price_stamp(market, report["latest"])

    currency = report.get("currency") or ("KRW" if market == MARKET_KR else "USD")
    in_window = [row for row in snapshots
                 if window_start <= row["snapshot_date"] <= window_end]

    if report["status"] == STATUS_NO_DATA:
        _render_shortage(report)
        return

    if report["status"] == STATUS_INSUFFICIENT:
        _render_shortage(report)
        # ⚠️ 기간 리포트는 "데이터 부족"이지만, **그 기간에 실제로 저장된 종목별 기록**은
        #    계산이 아니라 사실 그대로의 기록이라 숨길 이유가 없습니다(§3 이 금지하는 것은
        #    "부족한 데이터를 정상 리포트처럼 꾸미는 것"이지 기록을 보여주는 게 아닙니다).
        #    숨기면 기능을 켠 첫 달 내내 이 표가 안 보입니다 — 기간 시작 이전 기준점이 없어
        #    그 기간은 거의 항상 INSUFFICIENT 이기 때문입니다.
        _render_holding_history(market, holding_rows, in_window,
                                window_start, window_end, currency, error=holding_error)
        return

    # ⚠️ 2026-08-13 (#114) — COMPLETE 일 때의 초록 상자(st.success)를 없앴습니다. 그 문구는
    #    "X(직전 기준) → Y 비교"였는데, 바로 아래 _render_numbers() 의 "비교 구간" 캡션이
    #    같은 두 날짜를 이미 말합니다(같은 말 두 번). 진행 중일 때는 "아직 확정 아님"이라는
    #    **다른 정보**라서 그대로 둡니다.
    if report["status"] == STATUS_IN_PROGRESS:
        st.info("⏳ " + report["status_message"])

    _render_numbers(report)
    _render_benchmarks(report, market)

    # 🧾 종목별 상세(2026-08-13 신설). 합계 스냅샷 원본 표(_render_snapshot_table)와는 성격이
    #    달라 **별도 섹션**으로 두고, 원본 표는 지금까지처럼 맨 아래 접힌 채로 둡니다.
    _render_holding_history(market, holding_rows, in_window,
                            window_start, window_end, currency, error=holding_error)
    _render_snapshot_table(in_window, currency)


# =============================================================================
# 4. 메인 렌더러
# =============================================================================
def render_report_page():
    st.markdown("## 📈 사장님 보고서입니다")
    # ⚠️ 2026-08-13 (#114) — 머리말을 **색 상자 3개 + 캡션 1개 → 캡션 1덩이**로 줄였습니다.
    #    · 지운 것: "이 보고서는 시간이 지나면 채워집니다 …" 소개문. 기간마다 실제로 데이터가
    #      부족하면 그 블록이 "📭 데이터 부족"을 주 컨텐츠로 띄우므로(§3), 화면 맨 위에서
    #      미리 변명할 필요가 없었습니다.
    #    · 남긴 것: 세 가지 고지(환율 미변환 / 수수료·세금 미반영 / 단순 비교라 매매가 섞임).
    #      **한 글자도 지우지 않고** 색 상자만 걷어냈습니다 — 숫자를 오해하게 둘 정보라
    #      삭제·요약이 금지된 항목입니다(§0-1). 두 상수는 '내 성적표'와 공유하므로 그 문구
    #      자체는 손대지 않았습니다.
    st.caption(
        "매일 자동으로 저장되는 평가금액 기록을 기간별로 모아 보여드립니다.  \n"
        + NO_FX_CONVERSION_NOTICE + "  \n"
        + NO_FEES_TAXES_NOTICE + "  \n"
        + REPORT_SIMPLE_RETURN_NOTICE
    )

    status = supabase_status()
    if not status.available:
        _render_not_ready(status)
        return

    try:
        if SESSION_CLIENT_KEY not in st.session_state:
            # ⚠️ @st.cache_resource 로 캐시하면 한 사람의 로그인이 모든 방문자에게 공유됩니다.
            #    "내 성적표"와 똑같이 방문자별 session_state 에만 보관합니다.
            st.session_state[SESSION_CLIENT_KEY] = create_supabase_client()
        client = st.session_state[SESSION_CLIENT_KEY]
    except ScorecardError as exc:
        st.error(f"🚫 {exc}")
        return
    if client is None:
        _render_not_ready(supabase_status())
        return

    user = st.session_state.get(SESSION_USER_KEY) or current_user(client)
    if user is None:
        _render_login(client)
        return
    st.session_state[SESSION_USER_KEY] = user

    user_id = user_id_of(user)
    if not user_id:
        st.error("🚫 로그인 정보에서 사용자 ID를 찾지 못했습니다. 다시 로그인해 주세요.")
        return

    email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
    st.caption(f"로그인: {email or user_id}")

    period, ref_date = _render_period_controls()
    window_start, window_end = period_bounds(period, ref_date)

    # 기간 시작 **이전**의 스냅샷도 기준점으로 필요하므로 시작일로 자르지 않고, 종료일까지
    # 전부 받아 메모리에서 계산합니다(사용자 1명 × 시장 1개 = 연 250행 수준이라 가볍습니다).
    try:
        snapshots = fetch_user_snapshots(client, user_id, end_date=window_end)
    except (ReportError, ScorecardError) as exc:
        st.error(f"🚫 {exc}")
        return

    if not snapshots:
        st.error(
            "📭 **아직 저장된 기록이 없습니다.** '내 성적표'에 보유 종목을 등록해 두면 "
            "다음 날부터 하루치씩 쌓입니다(과거분을 지금 시세로 역산하지는 않습니다)."
        )
        return

    by_market = {}
    for row in snapshots:
        by_market.setdefault(row.get("market"), []).append(row)

    # 📅 '일간'에서 기준일이 거래일이 아니면 시장 블록이 그 이전 가장 최근 기록일로 대체해
    #    그립니다(#117). 종목별 스냅샷은 **기간만 잘라서** 부르므로, 대체가 일어난 시장의
    #    조회 범위도 그만큼 앞으로 넓혀 두지 않으면 합계는 나오는데 종목별 표만 비어 버립니다.
    #    (날짜 판정은 시장 블록과 **같은 함수**를 씁니다 — 두 곳이 다른 날을 고르면 안 됩니다.)
    holding_start = window_start
    for rows in by_market.values():
        display_date, _substituted = resolve_display_date(rows, period, ref_date)
        holding_start = min(holding_start, period_bounds(period, display_date)[0])

    # 🧾 종목별 스냅샷(2026-08-13 신설) — **보고 있는 기간만** 잘라서 부릅니다(합계와 달리
    #    기간 시작 이전의 기준점 행이 필요 없고, 행이 종목 수만큼 많기 때문입니다).
    #    ⚠️ 여기서 실패해도 **기존 리포트는 그대로 나와야 합니다** — 오류를 삼키지 않고
    #       그 시장 블록의 종목별 섹션에 그대로 보여 주되, 나머지 화면은 정상 진행합니다.
    holding_error = None
    holding_by_market = {}
    try:
        holding_rows = fetch_user_holding_snapshots(
            client, user_id, start_date=holding_start, end_date=window_end)
    except (ReportError, ScorecardError) as exc:
        holding_error = str(exc)
    else:
        for row in holding_rows:
            holding_by_market.setdefault(row.get("market"), []).append(row)

    for market in (MARKET_KR, MARKET_US):
        rows = by_market.get(market)
        if not rows:
            continue
        _render_market_block(market, rows, period, ref_date,
                             holding_rows=holding_by_market.get(market, []),
                             holding_error=holding_error)
        st.markdown("---")
