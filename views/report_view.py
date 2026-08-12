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
          show_report = st.sidebar.checkbox("📈 리포트 (준비중 · 미리보기)", key="view_report") \
              if is_report_visible(admin_mode) else False
          ...  if show_report: render_report_page()

v1 범위 (REPORT_WORK_ORDER.md §6)
   - 기간 선택(일/주/월/분기/반기/연) + 과거 기간으로 이동
   - 저장된 스냅샷을 기간 범위로 집계해 수익률 표시(계산은 전부 `utils/report_db.py`)
   - 시장별 벤치마크 비교(한국=코스피 지수, 미국=S&P500·나스닥 **추종 ETF 프록시**)
   - 데이터가 부족한 구간은 §3 원칙대로 "데이터 부족"을 **주 컨텐츠로** 표시

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
from utils.scorecard_db import (
    MARKET_KR,
    MARKET_US,
    NO_FX_CONVERSION_NOTICE,
    NO_FEES_TAXES_NOTICE,
    ScorecardError,
    create_supabase_client,
    current_user,
    format_amount,
    sign_in,
    supabase_status,
    user_id_of,
)
from utils.report_db import (
    PERIOD_OPTIONS,
    REPORT_NO_BACKFILL_NOTICE,
    REPORT_SIMPLE_RETURN_NOTICE,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_INSUFFICIENT,
    STATUS_NO_DATA,
    ReportError,
    benchmark_closes_for_market,
    benchmark_period_return,
    compute_period_report,
    fetch_user_snapshots,
    period_bounds,
    period_title,
    shift_period,
)

MARKET_TITLES = {
    MARKET_KR: "🇰🇷 한국 주식 (원화)",
    MARKET_US: "🇺🇸 미국 주식 (달러)",
}

SESSION_PERIOD_KEY = "report_period"
SESSION_REF_DATE_KEY = "report_ref_date"


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


def _render_not_ready(status):
    st.warning(
        "🚧 **리포트는 아직 준비중입니다.**\n\n"
        f"사유: {status.reason}\n\n"
        "이 화면이 준비되지 않아도 기존 밸류에이션 리포트(한국/미국)는 정상 동작합니다."
    )
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
    st.caption(
        "리포트는 '📊 내 성적표'와 같은 계정을 씁니다. 아직 계정이 없다면 내 성적표 화면에서 "
        "먼저 가입해 주세요. 비밀번호는 Supabase Auth 가 관리합니다."
    )
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
def _render_period_controls():
    """
    기간 종류 + 기준일 선택. 최신(오늘 기준)이 기본이고, 과거 기간도 자유롭게 볼 수 있습니다.
    반환: (period, ref_date)
    """
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

    stored_ref = st.session_state.get(SESSION_REF_DATE_KEY) or date.today()
    with col_date:
        ref_date = st.date_input(
            "기준일 (이 날짜가 속한 기간을 봅니다)", value=stored_ref, key="report_ref_date_input",
        )
    if isinstance(ref_date, (list, tuple)):  # 범위 선택 위젯으로 잘못 동작할 때의 방어
        ref_date = ref_date[0]

    col_prev, col_now, col_next = st.columns(3)
    if col_prev.button("◀ 이전 기간", key="report_prev_period", use_container_width=True):
        st.session_state[SESSION_REF_DATE_KEY] = shift_period(period, ref_date, -1)
        st.rerun()
    if col_now.button("최신 기간", key="report_latest_period", use_container_width=True):
        st.session_state[SESSION_REF_DATE_KEY] = date.today()
        st.rerun()
    if col_next.button("다음 기간 ▶", key="report_next_period", use_container_width=True):
        st.session_state[SESSION_REF_DATE_KEY] = shift_period(period, ref_date, 1)
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

    st.caption(
        f"비교 구간: **{baseline['snapshot_date'].isoformat()}** → "
        f"**{latest['snapshot_date'].isoformat()}** "
        + ("(기간 시작 직전 스냅샷을 기준점으로 사용)"
           if report["baseline_kind"] == "prior_close"
           else "(기간 시작 이전 스냅샷이 없어 기간 안 첫 스냅샷을 기준점으로 사용)")
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
    st.caption(
        "누적수익률 = (평가금액 − 매입원가) ÷ 매입원가. 위 '평가금액 변화'는 이 기간 동안의 "
        "변화량이고, 누적수익률은 매수 시점부터의 누적입니다 — 둘은 서로 다른 숫자입니다."
    )

    if incomplete:
        st.warning("⚠️ 위 숫자는 기간 전체가 아니라 **실제로 쌓인 구간만**의 값입니다.")

    if report.get("composition_changed"):
        st.warning("🔁 " + " ".join(report.get("composition_notes") or []))
    if report.get("coverage_note"):
        st.info("ℹ️ " + report["coverage_note"])


def _render_benchmarks(report, market):
    """포트폴리오와 **정확히 같은 두 날짜**로 벤치마크 수익률을 계산해 나란히 보여줍니다."""
    st.markdown("##### 📊 벤치마크 비교")
    benchmarks = benchmark_closes_for_market(market)
    if not benchmarks:
        st.info(
            "ℹ️ 이 시장의 벤치마크 데이터가 아직 없습니다 — 값을 지어내지 않고 비교를 생략합니다."
            + (" (미국 벤치마크는 `Daily Report Snapshots` 워크플로우가 처음 돌면 쌓입니다.)"
               if market == MARKET_US else "")
        )
        return

    baseline_date = report["baseline"]["snapshot_date"]
    end_date = report["latest"]["snapshot_date"]
    mine = report.get("value_change_pct")

    for benchmark in benchmarks:
        outcome = benchmark_period_return(benchmark["closes"], baseline_date, end_date)
        if not outcome["available"]:
            st.markdown(f"- **{benchmark['label']}**: 비교 불가 — {outcome['reason']}")
            continue
        line = (f"- **{benchmark['label']}** {_colored_pct(outcome['change_pct'])} "
                f"( {outcome['start_value']:,.2f} → {outcome['end_value']:,.2f} )")
        if mine is not None:
            gap = mine - outcome["change_pct"]
            line += f" · 내 포트폴리오 {_colored_pct(mine)} → 차이 {gap:+.2f}%p"
        st.markdown(line)
        if benchmark.get("is_proxy"):
            st.caption(f"　↳ {benchmark['note']}")


def _render_snapshot_table(rows_in_window, currency):
    with st.expander("이 기간에 저장된 스냅샷 원본 보기", expanded=False):
        if not rows_in_window:
            st.caption("이 기간에 저장된 스냅샷이 없습니다.")
            return
        lines = ["| 날짜 | 평가금액 | 매입원가 | 담긴 종목 | 벤치마크 |", "|---|---|---|---|---|"]
        for row in rows_in_window:
            benchmark = (f"{row.get('benchmark_symbol')} {row.get('benchmark_value'):,.2f}"
                         if row.get("benchmark_value") is not None
                         else f"{row.get('benchmark_symbol') or '—'} 없음")
            lines.append(
                f"| {row['snapshot_date'].isoformat()} "
                f"| {_md_amount(row.get('total_value'), currency)} "
                f"| {_md_amount(row.get('total_cost'), currency)} "
                f"| {row.get('priced_count')}/{row.get('holdings_count')} "
                f"| {benchmark} |"
            )
        st.markdown("\n".join(lines))
        st.caption(
            "'담긴 종목'은 그날 현재가를 알 수 있어 합계에 들어간 종목 수 / 전체 보유 종목 수입니다."
        )


def _render_market_block(market, snapshots, period, ref_date):
    st.markdown(f"### {MARKET_TITLES.get(market, market)}")
    report = compute_period_report(snapshots, period, ref_date)
    window_start, window_end = report["window_start"], report["window_end"]
    st.caption(f"{period_title(period, ref_date)} · 달력 기준 {window_start} ~ {window_end}")

    if report["status"] in (STATUS_NO_DATA, STATUS_INSUFFICIENT):
        _render_shortage(report)
        return

    if report["status"] == STATUS_IN_PROGRESS:
        st.info("⏳ " + report["status_message"])
    elif report["status"] == STATUS_COMPLETE:
        st.success("✅ " + report["status_message"])

    _render_numbers(report)
    _render_benchmarks(report, market)

    currency = report.get("currency") or ("KRW" if market == MARKET_KR else "USD")
    in_window = [row for row in snapshots
                 if window_start <= row["snapshot_date"] <= window_end]
    _render_snapshot_table(in_window, currency)


# =============================================================================
# 4. 메인 렌더러
# =============================================================================
def render_report_page():
    st.markdown("## 📈 리포트")
    st.warning(
        "🚧 **개발 중인 화면입니다(스테이징).** 오너 승인 전까지 공개 메뉴에 노출되지 않습니다. "
        "매일 자동으로 저장되는 내 평가금액 스냅샷을 기간별로 집계해서 보여줍니다."
    )
    st.info(NO_FX_CONVERSION_NOTICE)
    st.info(NO_FEES_TAXES_NOTICE)
    st.caption(REPORT_SIMPLE_RETURN_NOTICE)

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
    _, window_end = period_bounds(period, ref_date)

    # 기간 시작 **이전**의 스냅샷도 기준점으로 필요하므로 시작일로 자르지 않고, 종료일까지
    # 전부 받아 메모리에서 계산합니다(사용자 1명 × 시장 1개 = 연 250행 수준이라 가볍습니다).
    try:
        snapshots = fetch_user_snapshots(client, user_id, end_date=window_end)
    except (ReportError, ScorecardError) as exc:
        st.error(f"🚫 {exc}")
        return

    if not snapshots:
        st.error(
            "📭 **아직 저장된 스냅샷이 없습니다.**\n\n"
            "리포트는 매일 자동으로 도는 배치가 평가금액을 저장하기 시작한 날부터 만들어집니다. "
            "'내 성적표'에 보유 종목을 등록해 두면 다음 배치부터 쌓이기 시작합니다. "
            "과거분을 지금 시세로 역산해서 만들어내지는 않습니다."
        )
        return

    by_market = {}
    for row in snapshots:
        by_market.setdefault(row.get("market"), []).append(row)

    for market in (MARKET_KR, MARKET_US):
        rows = by_market.get(market)
        if not rows:
            continue
        _render_market_block(market, rows, period, ref_date)
        st.markdown("---")
