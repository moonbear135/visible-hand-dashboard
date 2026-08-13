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
     합계 스냅샷과 **매번 대조**해서 결과를 그대로 보여 줍니다(어긋나면 숨기지 않고 경고).

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
    PRICE_STAMP_FIELD,
    REPORT_NO_BACKFILL_NOTICE,
    REPORT_SIMPLE_RETURN_NOTICE,
    STATUS_COMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_INSUFFICIENT,
    STATUS_NO_DATA,
    ReportError,
    benchmark_closes_for_market,
    benchmark_period_return,
    build_holding_history,
    compare_holding_total,
    compute_period_report,
    fetch_user_holding_snapshots,
    fetch_user_snapshots,
    is_missing_holding_table_error,
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
    """
    stamp = (row or {}).get(PRICE_STAMP_FIELD)
    session_day = row["snapshot_date"].isoformat() if row and row.get("snapshot_date") else "—"

    if stamp:
        st.markdown(
            f"🕐 **종가 기준 : {stamp} (한국시간)** "
            f"　·　이 블록의 숫자는 **{session_day} 거래일** 스냅샷이고, 그 값은 위 시각에 "
            "수집된 가격으로 계산됐습니다."
        )
    else:
        # 값이 없는 과거 행 — 빈칸으로 얼버무리지 않고, 왜 없는지까지 밝힙니다(§0-1).
        #  ⚠️ 여기에 '오늘 몇 시'를 대신 넣지 마세요. 그 행이 저장될 때의 시각은 아무 데도
        #     기록돼 있지 않고, 지금 시각을 넣으면 그 자체가 지어낸 값입니다.
        st.markdown(
            f"🕐 **종가 기준 : 시각 정보 없음** "
            f"　·　{session_day} 거래일 스냅샷입니다. **가격 수집 시각을 함께 저장하기 전에 "
            "만들어진 행**이라 몇 시 몇 분 가격인지 기록이 없습니다(추정해서 채우지 않습니다). "
            "이후 쌓이는 스냅샷부터 시각이 표시됩니다."
        )

    if market == MARKET_US:
        st.caption(
            "🇺🇸 미국장은 한국시간으로 **새벽에** 마감돼서, 수집 시각이 거래일 **다음 날 새벽~오전**"
            "으로 찍힙니다 — 한국 주식 블록과 시각이 다른 것은 정상입니다."
        )


def _render_not_ready(status):
    st.warning(
        "🚧 **사장님 보고서는 아직 준비중입니다.**\n\n"
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
        st.caption(
            "'담긴 종목'은 그날 현재가를 알 수 있어 합계에 들어간 종목 수 / 전체 보유 종목 수입니다. "
            "'종가 수집 시각'은 그날 배치가 그 시장 가격 파일을 읽은 시각(한국시간)이며, "
            "이 값을 저장하기 전에 만들어진 행은 '기록 없음'입니다(나중에 채워 넣지 않습니다)."
        )


def _md_cell(text):
    """
    마크다운 표의 한 칸에 넣을 문자열을 안전하게 만듭니다.
    종목명에 '|' 가 들어 있으면 표가 통째로 깨지므로 이스케이프합니다(있을 법하지 않지만,
    사용자가 직접 입력하는 값이라 화면이 깨질 여지를 남기지 않습니다).
    """
    return str(text if text is not None else "").replace("|", "\\|").strip() or "—"


def _holding_label(row):
    """'삼성전자 (005930)' / 이름이 없으면 '005930'. '내 성적표' 표의 표기 관례와 같습니다."""
    name = (row.get("stock_name") or "").strip()
    ticker = (row.get("ticker") or "").strip() or "—"
    return _md_cell(f"{name} ({ticker})" if name else ticker)


def _md_qty(value):
    """수량 표기 — '내 성적표' 표와 같은 형식(정수는 정수로, 소수점은 필요한 만큼만)."""
    if value is None:
        return "—"
    return f"{value:,.6g}"


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
      · **들쑥날쑥 감시** — 이 표의 합계와 같은 날 합계 스냅샷을 매번 대조해서 결과를 그대로
        보여줍니다(일치하면 조용한 캡션, 어긋나면 경고).
      · 색·금액 표기는 '내 성적표' 표와 같은 관례(오르면 빨강/내리면 파랑, format_amount).
      · 가격을 몰랐던 날은 빈칸이 아니라 **"가격 모름"** — 이전 가격을 대신 넣지 않습니다(§0-1).
    """
    st.markdown("##### 🧾 종목별 상세 — 이 기간 숫자가 **어느 종목**에서 나왔나")

    if error is not None:
        if is_missing_holding_table_error(error):
            # 아직 표가 없는 상태(오너가 SQL 실행 전). 리포트의 나머지는 정상이므로 이 섹션만
            # 안내로 대체합니다 — 실패를 숨기는 게 아니라 "무엇을 하면 되는지"까지 말합니다.
            st.info(
                "ℹ️ **종목별 상세는 아직 준비되지 않았습니다.** 이 기능을 위한 표"
                "(`portfolio_holding_snapshots`)가 데이터베이스에 아직 없습니다.\n\n"
                "오너 할 일 — Supabase → SQL Editor 에서 `sql/report_schema.sql` 전체를 다시 "
                "실행하세요(§8 블록이 이 표를 만듭니다. 여러 번 실행해도 안전하고 기존 기록은 "
                "그대로입니다). 실행한 **다음 날 배치부터** 종목별 기록이 쌓이기 시작하며, "
                "그 이전 날짜는 소급해서 만들지 않습니다."
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
        st.info(
            "ℹ️ 이 기간에는 저장된 **종목별** 기록이 없습니다. 종목별 저장은 2026-08-13 부터 "
            "시작됐고, 그 이전 날짜는 합계만 남아 있습니다(과거 종목별 값은 어디에도 기록돼 "
            "있지 않아 만들어내지 않습니다)."
        )
        return

    base_date = history["base_date"]
    totals = history["totals"]
    dates = history["dates"]

    st.caption(
        f"기준일 **{base_date.isoformat()}** — 이 기간에 종목별 기록이 있는 마지막 거래일입니다. "
        f"아래 표의 모든 숫자는 **이 하루의 값**이고 종목마다 다른 날짜를 섞지 않았습니다. "
        f"(이 기간 기록 {len(dates)}일: {dates[0].isoformat()} ~ {dates[-1].isoformat()})"
    )

    lines = ["| 종목 | 수량 | 평균매입가 | 현재가 | 평가금액 | 평가손익 | 수익률 | 기간 주가등락 | 기록 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
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
        record = f"{row['days_recorded']}일"
        if row["unpriced_days"]:
            record += f" (가격 모름 {row['unpriced_days']}일)"
        lines.append(
            f"| {_holding_label(row)} | {_md_qty(row['quantity'])} "
            f"| {_md_amount(row['avg_purchase_price'], currency)} | {price_cell} "
            f"| {value_cell} | {profit_cell} | {pct_cell} "
            f"| {_colored_pct(row['price_change_pct'])} | {record} |"
        )
    # 합계 줄 — 칸 순서: 종목 / 수량 / 평균매입가(=매입원가 합) / 현재가 / 평가금액 /
    #            평가손익 / 수익률 / 기간 주가등락 / 기록   (헤더와 9칸으로 정확히 맞춤)
    lines.append(
        f"| **합계 {totals['holdings_count']}종목** "
        f"| "
        f"| **{_md_amount(totals['cost'], currency)}** "
        f"| "
        f"| **{_md_amount(totals['market_value'], currency)}** "
        f"| **{_md_amount(totals['profit'], currency)}** "
        f"| {_colored_pct(totals['profit_pct'])} "
        f"| "
        f"| 가격 담긴 종목 {totals['priced_count']}/{totals['holdings_count']} |"
    )
    st.markdown("\n".join(lines))
    st.caption(
        "· **합계 줄의 '평균매입가' 칸은 매입원가 합계**입니다(단가를 평균 낸 값이 아닙니다). "
        "가격을 알 수 없는 종목은 평가금액을 모르므로 합계에서 빠집니다 — "
        f"그 종목까지 포함한 매입원가 총액은 {_md_amount(totals['cost_all'], currency)} 입니다.\n"
        "· **기간 주가등락**은 수량 변화의 영향을 받지 않는 **주가만의 등락률**입니다"
        "(이 기간 안에서 가격을 처음 안 날의 종가 → 기준일 종가). 비교할 날이 하루뿐이거나 "
        "그날 가격을 몰랐으면 '—' 입니다(가까운 날로 대체하지 않습니다)."
    )

    # ---- 🔴 들쑥날쑥 감시 — 같은 날 합계 스냅샷과 대조 --------------------------
    summary_row = next((r for r in (snapshots_in_window or [])
                        if r.get("snapshot_date") == base_date), None)
    outcome = compare_holding_total(
        totals["market_value"], summary_row.get("total_value") if summary_row else None)
    if not outcome["comparable"]:
        # 대조를 못 한 이유를 뭉뚱그리지 않습니다 — "확인했다"와 "확인 못 했다"는 다른 말입니다.
        why = ("이 기간 목록에 그날 합계 스냅샷이 없습니다"
               if summary_row is None
               else "기준일에 가격을 아는 종목이 없어 비교할 합계가 없습니다")
        st.caption(
            f"⚖️ {base_date.isoformat()} 은(는) 합계와 대조하지 못했습니다 — {why}. "
            "(대조 없이 '일치한다'고 말하지 않습니다.)"
        )
    elif outcome["matches"]:
        st.caption(
            f"⚖️ **데이터 대조 통과** — 위 종목별 합계"
            f"({_md_amount(totals['market_value'], currency)})가 같은 날 합계 스냅샷과 "
            "정확히 일치합니다(두 표는 같은 계산에서 함께 저장됩니다)."
        )
    else:
        st.warning(
            f"⚠️ **대조 불일치** — 종목별 합계({_md_amount(totals['market_value'], currency)})와 "
            f"같은 날 합계 스냅샷({_md_amount(summary_row.get('total_value'), currency)})이 "
            f"서로 다릅니다(차이 {outcome['diff']:+,.6f}). 그날 종목별 저장이 중간에 실패했을 수 "
            "있습니다 — 숨기지 않고 그대로 알려 드립니다. 다음 배치가 같은 날짜를 다시 저장하면 "
            "맞춰집니다."
        )

    if history["gone"]:
        gone_text = ", ".join(
            f"{(g['stock_name'] or '').strip() or g['ticker']}({g['ticker']}, "
            f"마지막 기록 {g['last_date'].isoformat()})"
            for g in history["gone"]
        )
        st.caption(
            f"⏹ 이 기간에는 기록이 있었지만 기준일({base_date.isoformat()})에는 없는 종목: "
            f"{gone_text}. (매도했거나 그날 평가에서 빠진 종목입니다 — 위 표에 넣으면 날짜가 "
            "섞이므로 따로 적습니다.)"
        )

    # ---- 종목 하나를 골라 일별 추이 보기 ---------------------------------------
    with st.expander("📅 종목 하나를 골라 이 기간 일별 추이 보기", expanded=False):
        options = [row["ticker"] for row in history["rows"]] + \
                  [g["ticker"] for g in history["gone"]]
        label_by_ticker = {row["ticker"]: _holding_label(row) for row in history["rows"]}
        for g in history["gone"]:
            label_by_ticker[g["ticker"]] = _holding_label(g)
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
        st.caption(
            "이 표는 **저장된 날만** 나옵니다 — 휴장일이나 배치가 돌지 않은 날은 행 자체가 "
            "없습니다(없는 날을 이전 값으로 채우지 않습니다). 수량이 바뀐 날은 그날 추가 매수·"
            "매도가 있었다는 뜻입니다."
        )


def _render_market_block(market, snapshots, period, ref_date,
                         holding_rows=None, holding_error=None):
    st.markdown(f"### {MARKET_TITLES.get(market, market)}")
    report = compute_period_report(snapshots, period, ref_date)
    window_start, window_end = report["window_start"], report["window_end"]
    st.caption(f"{period_title(period, ref_date)} · 달력 기준 {window_start} ~ {window_end}")

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

    if report["status"] == STATUS_IN_PROGRESS:
        st.info("⏳ " + report["status_message"])
    elif report["status"] == STATUS_COMPLETE:
        st.success("✅ " + report["status_message"])

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
    st.info(
        "🧾 **사장님, 보고서입니다.** 매일 자동으로 저장되는 내 평가금액 스냅샷을 기간별로 "
        "집계해서 보여드립니다. 이 보고서는 **시간이 지나면 채워집니다** — 이제 막 시작하셨다면 "
        "일간부터 채워지고, 주간·월간·분기·반기·연간은 그 기간이 지나가면서 차례로 완성됩니다."
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
            "📭 **아직 저장된 스냅샷이 없습니다.**\n\n"
            "리포트는 매일 자동으로 도는 배치가 평가금액을 저장하기 시작한 날부터 만들어집니다. "
            "'내 성적표'에 보유 종목을 등록해 두면 다음 배치부터 쌓이기 시작합니다. "
            "과거분을 지금 시세로 역산해서 만들어내지는 않습니다."
        )
        return

    # 🧾 종목별 스냅샷(2026-08-13 신설) — **보고 있는 기간만** 잘라서 부릅니다(합계와 달리
    #    기간 시작 이전의 기준점 행이 필요 없고, 행이 종목 수만큼 많기 때문입니다).
    #    ⚠️ 여기서 실패해도 **기존 리포트는 그대로 나와야 합니다** — 오류를 삼키지 않고
    #       그 시장 블록의 종목별 섹션에 그대로 보여 주되, 나머지 화면은 정상 진행합니다.
    holding_error = None
    holding_by_market = {}
    try:
        holding_rows = fetch_user_holding_snapshots(
            client, user_id, start_date=window_start, end_date=window_end)
    except (ReportError, ScorecardError) as exc:
        holding_error = str(exc)
    else:
        for row in holding_rows:
            holding_by_market.setdefault(row.get("market"), []).append(row)

    by_market = {}
    for row in snapshots:
        by_market.setdefault(row.get("market"), []).append(row)

    for market in (MARKET_KR, MARKET_US):
        rows = by_market.get(market)
        if not rows:
            continue
        _render_market_block(market, rows, period, ref_date,
                             holding_rows=holding_by_market.get(market, []),
                             holding_error=holding_error)
        st.markdown("---")
