"""
📈 사장님 보고서 — 매일 쌓인 스냅샷으로 일간~연간 리포트를 보여주는 화면 (로그인 필요, URL `/report`).

`views/report_view.py`(Streamlit, 1,030줄)의 NiceGUI 이식본입니다 (이전 계획서 5단계).
컷오버(2026-08-17)가 끝나 **지금 사용자가 보는 화면은 이 파일**이고, Streamlit 쪽 원본은
즉시 롤백에 대비해 최소 2주간만 살려둡니다(듀얼런 — 계획서 §11-1 · §0-3-10).

🔴 이 화면도 '내 성적표'와 똑같이 **사용자의 실제 자산 정보**를 다룹니다.
   ENGINEERING_SPEC.md §0-3-8(최상위 금지사항)이 그대로 적용됩니다:
   1. 모듈 최상위에는 상수(문자열/튜플)만 둡니다. 스냅샷·클라이언트·사용자 id 는 전부
      `@ui.page` 함수 안의 지역 변수이거나 함수 인자입니다.
   2. DB를 만지는 함수는 `client`(그 접속 전용 클라이언트)와 `user_id`를 **인자로 받아야만**
      동작합니다. "지금 누가 로그인했는지"를 전역에서 추측하지 않습니다.
   3. 이 규칙이 지켜지는지 `tests/test_web_session_isolation.py` 가 자동으로 검사합니다.

🔑 **로그인은 '내 성적표'(/scorecard)와 공유합니다** (오너 확정 사항).
   Streamlit 에서는 두 화면이 `SESSION_USER_KEY` 라는 같은 session_state 키를 공유해서
   맞췄지만, NiceGUI 에서는 `web/auth.py` 의 저장소가 **접속자 단위**(app.storage.user)라
   같은 브라우저면 자동으로 공유됩니다 — /scorecard 에서 로그인한 뒤 /report 로 오면
   로그인 폼 없이 바로 본문이 보입니다(그 반대도 동일). 로그인 폼도 `web/auth_ui.py`
   하나를 두 화면이 같이 씁니다(§0-3-10).

✅ **공개 전환 완료 (2026-08-17, §0-3-6 스테이징 절차 통과 후 오너 승인)** — 드로어 메뉴에
   모든 방문자에게 보입니다(`web/layout.py` 의 `_MENU` 에서 `admin_only=False`).
   ⚠️ 공개는 "메뉴에 보인다"까지이고, **데이터는 여전히 로그인한 본인 것만** 보입니다 —
      로그인 없이 들어오면 로그인 폼만 그리고 숫자를 한 개도 그리지 않으며, DB 는 RLS 로
      본인 행만 허용합니다(§0-3-8). 공개(공유)와 노출(사고)은 완전히 다릅니다.
   ⚠️ 원본의 `REPORT_ENABLED` 환경변수 게이트(`is_report_enabled()`)는 **옮기지 않았습니다.**
      그건 Streamlit 사이드바에 체크박스를 만들지 말지 고르는 장치였고, 여기서는 '내 성적표'와
      똑같이 **메뉴 노출 + 로그인**으로 같은 목적을 달성합니다 — 같은 일을 하는 장치를 두 개
      두지 않습니다(§0-3-10). 노출 여부를 다시 바꿀 곳도 `web/layout.py` 한 줄입니다.

이식 방침
   - **계산·DB 계층(`utils/report_db.py`)은 한 줄도 건드리지 않습니다.** 이 파일은 순수
     표현 계층입니다 — 수익률·비중·벤치마크 계산식을 여기에 새로 넣지 마세요.
   - Streamlit 의 **위젯 키 우회 코드는 통째로 사라졌습니다.** 원본의
     `_consume_pending_ref_date()` / `SESSION_PENDING_REF_DATE_KEY` / `REF_DATE_WIDGET_KEY` 는
     "버튼이 바꾼 날짜를 달력 위젯이 무시하는" Streamlit 고유 함정(#114)을 피하려던 장치인데,
     NiceGUI 는 페이지 함수가 접속당 **1회만** 실행되고 위젯이 파이썬 객체로 살아 있어서
     `date_input.value = 새날짜` 한 줄이면 화면까지 즉시 반영됩니다(자세한 근거는
     `_apply_ref_date()` 주석).
   - 사용자 입력·DB 값이 HTML 로 나가는 곳은 전부 `esc()` 를 거칩니다 (§0-3-9 XSS).
     원본은 마크다운 표라 `_md_cell()` 로 '|' 만 막았는데, HTML 표에서는 그걸로 부족합니다.
   - 표는 '내 성적표'와 같은 **순수 HTML `<table>` + 가로 스크롤**(#127 결론)입니다.

지켜야 할 것 (원본 화면과 동일)
   - **환율 변환 없음** — 원화/달러를 절대 합치지 않고 시장별로 따로 계산·표시합니다.
   - **지어내지 않기(§0-1)** — 없는 스냅샷을 과거 시세로 역산하지 않습니다. 벤치마크가 없는
     날은 "없음"으로 두고 가까운 날짜로 대체하지 않습니다. 비교한 날짜를 항상 밝힙니다.
   - **읽기 전용** — 이 화면은 스냅샷을 만들지도, 고치지도 않습니다.
"""

from datetime import date

from nicegui import ui

from utils.scorecard_db import (
    MARKET_KR,
    MARKET_US,
    NO_FEES_TAXES_NOTICE,
    NO_FX_CONVERSION_NOTICE,
    SNAPSHOT_FILENAMES,
    build_universe_index,
    current_user,
    format_amount,
    supabase_status,
    user_id_of,
)
from utils.report_db import (
    PERIOD_OPTIONS,
    PRICE_STAMP_FIELD,
    REPORT_NO_BACKFILL_NOTICE,
    REPORT_SIMPLE_RETURN_NOTICE,
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

from web.auth import get_client, has_supabase_session, logout
from web.auth_ui import fail_message, render_auth
from web.components import (
    error_banner, esc, holdings_table_html, info_banner, metric_card,
    pct_html, pct_text, warning_banner,
)
from web.layout import layout
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file_async,
)

# 🇺🇸 미국 종목명 한글 표기 — 원본(`views/report_view.py`)이 `views/scorecard_view.py` 의
#    `_display_name()` 을 그대로 가져다 쓴 것과 **완전히 같은 구조**입니다. 같은 로직을 여기에
#    베껴 쓰면 언젠가 두 화면의 표기가 어긋나므로(오너가 말한 "들쑥날쑥") 단일 출처를 유지합니다.
#    (미국 종목이면 한글명, 한국 종목이면 저장된 종목명 그대로 — DB 값은 손대지 않습니다.)
from web.pages.scorecard_page import _display_name

MARKET_TITLES = {
    MARKET_KR: "🇰🇷 한국 주식 (원화)",
    MARKET_US: "🇺🇸 미국 주식 (달러)",
}

# 기본 기간 — 오너 요청(2026-08-17)으로 원본(월간)에서 일간으로 변경했습니다.
DEFAULT_PERIOD = "DAILY"


# =============================================================================
# 1. 표시 도우미 (전부 순수 함수 — 상태를 갖지 않습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """이 화면 전용 축약 — 예외 원문은 화면에 흘리지 않고 서버 로그로만 보냅니다(§0-3-4).

    🔴 2026-08-17 이식 중 발견해 고친 것: 원본(Streamlit)은 DB 조회 실패를
       `st.error(f"🚫 {exc}")` 로 띄웠는데, `utils/report_db._execute()` 가 만드는
       `ReportError` 메시지에는 **PostgREST 응답 원문이 그대로 붙습니다**
       (`f"{action} 실패: {exc}"`). 그대로 화면에 뿌리면 내부 구조(테이블명·에러코드)가
       노출돼 §0-3-4 위반입니다. 그래서 DB 경로의 예외는 여기서 **로그로만** 보내고 화면에는
       사람이 읽는 문장만 남깁니다. 반대로 순수 계산 함수가 던지는 `ReportError`
       (예: "서로 다른 시장·통화가 섞여 있습니다")는 우리가 쓴 한국어라 호출부에서 그대로
       보여 줍니다 — 그 경로에는 외부 원문이 섞일 수 없습니다.
    """
    return fail_message(exc, fallback, context='사장님 보고서')


def _pp_html(value) -> str:
    """비중 **변화량**(퍼센트포인트). 색 관례는 수익률과 같아 같은 함수를 씁니다(§0-3-10).

    ⚠️ 단위는 % 가 아니라 %p 입니다 — 50%→75% 는 "+25%p"(비중이 25포인트 늘어남)이지
       "+25%"(1.5배)가 아닙니다. 오너 원본 표는 '%'로 적혀 있었지만 여기서는 정확히 씁니다.
    """
    return pct_html(value, suffix='%p')


def _weight_text(value) -> str:
    """비중(%) 표기. **값이 없으면 0% 가 아니라 '모름'** 입니다 — 그날 가격을 몰라 평가금액
    자체를 모르는 종목이고, 0% 로 적으면 "가진 게 없다"는 다른 뜻이 됩니다(§0-1)."""
    return '모름' if value is None else f'{value:.2f}%'


def _qty_text(value) -> str:
    """수량 표기 — '내 성적표' 표와 같은 형식(정수는 정수로, 소수점은 필요한 만큼만)."""
    return '—' if value is None else f'{value:,.6g}'


def _muted(text: str) -> None:
    """원본의 `st.caption` 대체 — 회색 작은 글씨 한 줄."""
    ui.label(text).classes('vh-muted')


# (2026-08-17) 이 자리에 있던 `_table_html()` 은 `web/components/html.py` 의
#  `holdings_table_html()` 로 옮겼습니다 — '내 성적표'가 글자 그대로 같은 HTML 을 따로
#  들고 있어서, 한쪽만 고치면 두 화면의 표가 어긋나는 구조였습니다 (§0-3-10).
#  ⚠️ 계약은 그대로입니다: `headers` 는 그쪽이 이스케이프하고, 각 칸은 **호출하는 쪽이
#     이스케이프까지 끝내서** 넘깁니다 (§0-3-9).


async def _display_indexes(market):
    """미국 종목 한글명을 '내 성적표'와 **완전히 같은 값**으로 만들기 위한 유니버스 인덱스.

    · 상위 550 유니버스 **안** 종목은 이 파일에 수집 시점 계산해 넣어 둔 `name_kr` 이 들어 있어
      공개 미국주식 화면·내 성적표와 글자 하나까지 같은 표기가 됩니다.
    · 유니버스 **밖** 종목은 여기에 없고, 그때는 `_display_name()` 안쪽이 즉석으로 한글명을
      만듭니다(그마저 못 만들면 영문명/티커 — 지어내지 않습니다).
    · 한국 시장 블록에서는 한글명 변환이 필요 없으므로 파일을 **아예 읽지 않습니다**.
    · 파일이 없거나 읽기에 실패해도 화면을 죽이지 않고 빈 dict 로 넘어갑니다.

    ⚠️ 원본은 `load_universe_index()`(매번 파일 열기)를 썼지만 여기서는 `web/state.py` 의
       mtime 캐시를 거칩니다 — **읽기 전용 시세 데이터**라 전역 캐시가 정답이고(§0-3-8 구분선),
       계산은 기존 `build_universe_index()` 를 그대로 써서 결과값이 원본과 동일합니다.

    🔴 2026-08-21 — `async def` 로 바뀌었습니다. 반환값은 그대로이고, 파일을 읽는 동안
       이벤트 루프를 붙잡지 않습니다(이유는 `web/state.load_json_file_async` 주석 참고).
       이 함수 하나 때문에 `_render_holding_history` → `_render_market_block` →
       `_render_report_body` → `body()` → `_render_signed_in` → `report_page()` 까지
       호출 사슬 전체가 `async def` 가 되었습니다. 중간에 한 군데라도 동기로 남겨 두면
       그 지점에서 다시 이벤트 루프가 막히므로, 사슬을 끊지 말고 그대로 유지하세요.
    """
    if market != MARKET_US:
        return {}
    payload, _load_error = await load_json_file_async(data_path(SNAPSHOT_FILENAMES[MARKET_US]))
    if payload is None:
        return {}
    return {MARKET_US: build_universe_index(payload, MARKET_US) or {}}


def _holding_name(row, market=None, indexes=None) -> str:
    """화면에 쓸 **종목명만**(코드 없이). 이름을 끝내 못 찾으면 지어내지 않고 티커 그대로입니다."""
    probe = dict(row)
    probe["market"] = market or row.get("market")
    name = (_display_name(probe, indexes or {}) or "").strip()
    return name or (row.get("ticker") or "").strip() or "—"


def _holding_label_html(row, market=None, indexes=None) -> str:
    """'삼성전자 (005930)' / 이름이 없으면 '005930' — '내 성적표' 표의 표기 관례와 같습니다.

    ⚠️ `market` 을 따로 받는 이유: `build_holding_history()` 의 `gone` 목록과
       `build_weight_comparison()` 의 행에는 `market` 키가 없습니다(같은 시장 안에서만 쓰는
       파생 구조라 넣지 않은 것). 그 행들도 미국 한글명을 받게 하려면 호출부가 이미 알고 있는
       시장을 넘겨 줘야 합니다.
    🔐 종목명은 **사용자가 DB에 직접 써넣을 수 있는 값**이라 반드시 `esc()` 를 거칩니다
       (§0-3-9 — '내 성적표'의 `_row_label_html()` 과 같은 이유).
    """
    name = _holding_name(row, market, indexes)
    ticker = (row.get("ticker") or "").strip()
    return esc(f'{name} ({ticker})' if ticker and name != ticker else (name or ticker or '—'))


# =============================================================================
# 2. 페이지 (로그인 게이트)
# =============================================================================
@ui.page('/report', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def report_page() -> None:
    with layout('📈 사장님 보고서'):
        _render_header()

        status = supabase_status()
        if not status.available:
            _render_not_ready(status)
            return

        # ── 로그인 게이트 ────────────────────────────────────────────────────
        # '내 성적표'와 **같은 함수·같은 저장소**를 봅니다. 그래서 한쪽에서 로그인해 두면
        # 이 화면은 폼 없이 바로 본문으로 넘어갑니다(오너 확정 "같은 로그인 공유").
        if not has_supabase_session():
            render_auth()
            return

        try:
            client = get_client()
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return
        if client is None:
            _render_not_ready(supabase_status())
            return

        # "지금 누가 로그인했는지"는 **이 접속 전용 클라이언트에게 직접 물어봅니다** (§0-3-8).
        user = current_user(client)
        user_id = user_id_of(user)
        if not user_id:
            logout()                               # 끊어진 세션을 남겨두지 않습니다
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
            return

        email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        try:
            await _render_signed_in(client, user_id, email)
        except Exception as exc:                   # noqa: BLE001 — 트레이스백을 화면에 흘리지 않습니다
            error_banner(f'🚫 {_fail(exc, "화면을 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_header() -> None:
    ui.markdown('## 📈 사장님 보고서입니다')
    # ⚠️ 2026-08-13 (#114) — 머리말을 색 상자 3개가 아니라 **회색 한 덩이**로 줄인 원본 결정을
    #    그대로 따릅니다. 문구는 **한 글자도 지우지 않았습니다** — 숫자를 오해하게 둘 정보라
    #    삭제·요약이 금지된 항목입니다(§0-1). 세 상수는 '내 성적표'와 공유합니다.
    ui.html('<br>'.join(esc(line) for line in (
        '매일 자동으로 저장되는 평가금액 기록을 기간별로 모아 보여드립니다.',
        NO_FX_CONVERSION_NOTICE,
        NO_FEES_TAXES_NOTICE,
        REPORT_SIMPLE_RETURN_NOTICE,
    ))).classes('vh-muted w-full')


def _render_not_ready(status) -> None:
    """Supabase 가 준비되지 않은 상태 안내 (에러가 아니라 '준비중'입니다)."""
    warning_banner(f'🚧 사장님 보고서는 아직 준비중입니다. ({status.reason})')
    with ui.expansion('🔧 오너 설정 체크리스트 (관리자용)').classes('w-full'):
        ui.markdown(
            '1. Supabase → SQL Editor 에서 `sql/report_schema.sql` 전체 실행\n'
            '   → `portfolio_daily_snapshots` 테이블 + **RLS select 정책 1개** 생성 확인\n'
            '2. GitHub → 저장소 → Settings → Secrets and variables → Actions 에 등록\n'
            '   (⚠️ 앱 환경변수가 **아니라** GitHub Actions Secrets 입니다)\n'
            '   - `SUPABASE_URL`\n'
            '   - `SUPABASE_SERVICE_ROLE_KEY`  ← 이 키는 **앱에 절대 넣지 마세요**\n'
            '3. Actions 탭에서 `Daily Report Snapshots` 워크플로우를 수동 실행해 첫 스냅샷 적재 확인\n'
            '4. 앱(Render → Environment) 쪽은 기존 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 그대로\n'
            '   (리포트 화면은 읽기만 하며, 로그인 세션으로 본인 행만 조회합니다)'
        )


# =============================================================================
# 3. 기간 선택 (Streamlit 위젯 키 우회 코드가 통째로 사라진 자리)
# =============================================================================
async def _render_signed_in(client, user_id: str, email) -> None:
    """로그인 후 화면 전체.

    ⚠️ `client` 와 `user_id` 는 **반드시 인자로 받습니다.** 이 아래 어떤 함수도 "지금 누가
       로그인했는지"를 전역이나 저장소에서 다시 추측하지 않습니다 (§0-3-8 함수 설계 원칙).

    🔴 화면 상태(고른 기간·기준일)는 이 함수의 **지역 변수 `view` 하나**입니다. 접속마다
       새로 만들어지므로 다른 사람의 화면 상태와 섞일 수 없고, Streamlit 의
       `st.session_state` + 위젯 키 관리가 통째로 필요 없어집니다(계획서 §3-3).
    """
    def _logout_click() -> None:
        logout()
        ui.navigate.reload()

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.label(f'로그인: {email or user_id}').classes('flex-1 min-w-0 truncate vh-muted')
        ui.button('로그아웃', on_click=_logout_click).props('flat dense no-caps').classes('shrink-0')

    view = {'period': DEFAULT_PERIOD, 'ref_date': date.today()}

    # ⚠️ `@ui.refreshable` 은 비동기 함수도 그대로 지원합니다(NiceGUI 3.x).
    #    · 여기서처럼 **직접 부를 때는 반드시 `await`** 해야 화면이 그려집니다.
    #    · 버튼/달력 콜백이 부르는 `body.refresh()` 는 동기 함수에서 불러도 됩니다 —
    #      NiceGUI 가 알아서 배경 작업으로 돌려 주므로 `_render_period_controls()` 쪽은
    #      한 줄도 바꿀 필요가 없습니다.
    @ui.refreshable
    async def body() -> None:
        await _render_report_body(client, user_id, view['period'], view['ref_date'])

    _render_period_controls(view, body)
    ui.separator()
    await body()


def _render_period_controls(view: dict, body) -> None:
    """기간 종류 + 기준일 + '◀ 이전 / 최신 / 다음 ▶'.

    원본(Streamlit)에는 이 자리에 `_consume_pending_ref_date()` 라는 우회 함수가 있었습니다.
    키를 준 `st.date_input` 은 한 번 만들어지면 다음 재실행부터 `value=` 를 무시하고
    `session_state[위젯키]` 를 우선하기 때문에, 버튼이 다른 키를 아무리 바꿔도 달력이 옛
    날짜 그대로였고(= 눌러도 아무 일이 안 일어남, #114), 그걸 피하려고 "버튼은 pending 표시만
    남기고 rerun → 다음 렌더 맨 앞에서 위젯 키에 대입"하는 2단 구조가 필요했습니다.

    NiceGUI 에는 그 함정이 **구조적으로 없습니다**: 페이지 함수는 접속당 1회만 실행되고
    위젯은 파이썬 객체로 계속 살아 있어서, 버튼 콜백이 그 객체의 `.value` 를 바꾸면 그 값이
    곧바로 브라우저까지 전송됩니다(재실행도, pending 표시도 필요 없음). 그래서 우회 코드
    전부(`SESSION_PENDING_REF_DATE_KEY`·`REF_DATE_WIDGET_KEY`·`_consume_pending_ref_date`)를
    삭제하고 `_apply_ref_date()` 한 줄로 대체했습니다.
    """
    with ui.row().classes('w-full gap-4 items-center'):
        # 6기간 — 항목은 `utils/report_db.PERIOD_OPTIONS` 하나에서만 옵니다(문자열 이중 관리 금지).
        ui.select({code: label for code, label in PERIOD_OPTIONS},
                  value=view['period'], label='기간',
                  on_change=lambda e: _apply_period(view, e.value, body)) \
            .style('flex: 1 1 200px;')

        # 기준일 — Quasar QInput 의 `type=date` 라 **기기 기본 날짜 선택기**가 뜹니다
        # (폰에서는 네이티브 달력). 값은 항상 'YYYY-MM-DD' 문자열입니다.
        date_input = ui.input(
            '기준일', value=view['ref_date'].isoformat(),
            # ⚠️ `date_input` 은 이 대입이 끝난 뒤에야 존재하지만, 람다는 **호출될 때**
            #    이름을 찾으므로(클로저) 문제가 없습니다.
            on_change=lambda e: _on_date_typed(view, e.value, date_input, body),
        # `stack-label` — 네이티브 날짜칸은 값이 없을 때도 'yyyy-mm-dd' 를 보여주기 때문에
        #   라벨을 띄워 두지 않으면 두 글자가 겹쳐 보입니다(Quasar 기본 동작).
        ).props('type=date stack-label').style('flex: 1 1 200px;')

    with ui.row().classes('w-full gap-2 items-center'):
        ui.button('◀ 이전 기간',
                  on_click=lambda: _shift_ref_date(view, -1, date_input, body)) \
            .props('outline no-caps').style('flex: 1 1 120px;')
        ui.button('최신 기간',
                  on_click=lambda: _apply_ref_date(view, date.today(), date_input, body)) \
            .props('outline no-caps').style('flex: 1 1 120px;')
        ui.button('다음 기간 ▶',
                  on_click=lambda: _shift_ref_date(view, 1, date_input, body)) \
            .props('outline no-caps').style('flex: 1 1 120px;')


def _apply_period(view: dict, code, body) -> None:
    if not code or code == view['period']:
        return
    view['period'] = code
    body.refresh()


def _shift_ref_date(view: dict, steps: int, date_input, body) -> None:
    """기간 단위로 앞/뒤 이동 — 날짜 계산은 기존 `shift_period()` 그대로입니다."""
    _apply_ref_date(view, shift_period(view['period'], view['ref_date'], steps), date_input, body)


def _apply_ref_date(view: dict, new_date, date_input, body) -> None:
    """기준일을 바꾸고 **화면(달력 칸 + 본문)까지 즉시** 맞춥니다.

    이 세 줄이 Streamlit 우회 코드 30여 줄을 대체합니다. 안전한 이유:
      · `view` 는 이 접속의 지역 dict 라 다른 접속과 섞일 수 없습니다(§0-3-8).
      · `date_input.value = ...` 는 그 위젯 객체의 값을 바꾸는 것이고, NiceGUI 가 변경분을
        이 접속의 WebSocket 으로만 보냅니다.
      · 값이 실제로 바뀔 때만 다시 그립니다(같은 날짜면 조용히 반환 — 아래 `_on_date_typed`
        가 되돌려 보내는 같은 값에 무한 루프가 생기지 않습니다).
    """
    if new_date == view['ref_date']:
        return
    view['ref_date'] = new_date
    date_input.value = new_date.isoformat()
    body.refresh()


def _on_date_typed(view: dict, raw, date_input, body) -> None:
    """달력 칸을 사람이 직접 고쳤을 때.

    ⚠️ 비어 있거나 형식이 깨진 값이면 **날짜를 지어내지 않고**(§0-1) 직전 기준일로 되돌립니다.
    """
    try:
        parsed = date.fromisoformat(str(raw or '').strip())
    except ValueError:
        date_input.value = view['ref_date'].isoformat()
        return
    _apply_ref_date(view, parsed, date_input, body)


# =============================================================================
# 4. 리포트 본문
# =============================================================================
async def _render_report_body(client, user_id: str, period: str, ref_date) -> None:
    """고른 기간의 리포트 전체(시장별 블록). 계산은 전부 `utils/report_db.py` 가 합니다."""
    window_start, window_end = period_bounds(period, ref_date)

    # 기간 시작 **이전**의 스냅샷도 기준점으로 필요하므로 시작일로 자르지 않고, 종료일까지
    # 전부 받아 메모리에서 계산합니다(사용자 1명 × 시장 1개 = 연 250행 수준이라 가볍습니다).
    try:
        snapshots = fetch_user_snapshots(client, user_id, end_date=window_end)
    except Exception as exc:                       # noqa: BLE001 — 원문 노출 방지는 _fail 이 담당
        error_banner(f'🚫 {_fail(exc, "저장된 기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    if not snapshots:
        error_banner(
            "📭 아직 저장된 기록이 없습니다. '내 성적표'에 보유 종목을 등록해 두면 "
            '다음 날부터 하루치씩 쌓입니다(과거분을 지금 시세로 역산하지는 않습니다).'
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

    # 🧾 종목별 스냅샷 — **보고 있는 기간만** 잘라서 부릅니다(합계와 달리 기간 시작 이전의
    #    기준점 행이 필요 없고, 행이 종목 수만큼 많기 때문입니다).
    #    ⚠️ 여기서 실패해도 **기존 리포트는 그대로 나와야 합니다** — 오류를 삼키지 않고
    #       그 시장 블록의 종목별 섹션에 그대로 보여 주되, 나머지 화면은 정상 진행합니다.
    holding_error = None
    holding_by_market = {}
    try:
        holding_rows = fetch_user_holding_snapshots(
            client, user_id, start_date=holding_start, end_date=window_end)
    except Exception as exc:                       # noqa: BLE001
        holding_error = exc
    else:
        for row in holding_rows:
            holding_by_market.setdefault(row.get("market"), []).append(row)

    for market in (MARKET_KR, MARKET_US):
        rows = by_market.get(market)
        if not rows:
            continue
        await _render_market_block(market, rows, period, ref_date,
                                   holding_rows=holding_by_market.get(market, []),
                                   holding_error=holding_error)
        ui.separator()


async def _render_market_block(market, snapshots, period, ref_date,
                               holding_rows=None, holding_error=None) -> None:
    ui.markdown(f'### {MARKET_TITLES.get(market, market)}')

    # 📅 '일간'에서 기준일이 거래일이 아니면 그 이전 가장 최근 기록일로 대체합니다(#117).
    #    아래는 **그 날짜 하나만 바꿔서** 기존 렌더링 경로를 그대로 태웁니다 — 대체 전용
    #    화면을 따로 만들면 평일과 주말의 표가 서로 달라질 여지가 생깁니다.
    #    시장별로 따로 구하는 이유: 미국장은 한국장과 마지막 거래일이 다를 수 있습니다.
    display_date, substituted = resolve_display_date(snapshots, period, ref_date)
    if substituted:
        _render_substitute_notice(period, ref_date, display_date)

    report = compute_period_report(snapshots, period, display_date)
    window_start, window_end = report["window_start"], report["window_end"]
    _muted(f'{period_title(period, display_date)} · 달력 기준 {window_start} ~ {window_end}')

    # 🕐 이 블록이 실제로 보여주는 **마지막 스냅샷 행**의 가격 수집 시각(한국시간).
    #    스냅샷이 하나도 없는 구간(NO_DATA)에는 보여줄 행 자체가 없으므로 생략합니다.
    if report.get("latest"):
        _render_price_stamp(market, report["latest"])

    currency = report.get("currency") or ("KRW" if market == MARKET_KR else "USD")
    in_window = [row for row in snapshots
                 if window_start <= row["snapshot_date"] <= window_end]

    if report["status"] == STATUS_NO_DATA:
        _render_shortage(report, currency)
        return

    if report["status"] == STATUS_INSUFFICIENT:
        _render_shortage(report, currency)
        # ⚠️ 기간 리포트는 "데이터 부족"이지만, **그 기간에 실제로 저장된 종목별 기록**은
        #    계산이 아니라 사실 그대로의 기록이라 숨길 이유가 없습니다(숨기면 기능을 켠 첫 달
        #    내내 이 표가 안 보입니다 — 기준점이 없어 거의 항상 INSUFFICIENT 이기 때문).
        await _render_holding_history(market, holding_rows, in_window,
                                      window_start, window_end, currency, error=holding_error)
        return

    if report["status"] == STATUS_IN_PROGRESS:
        info_banner('⏳ ' + report["status_message"])

    _render_numbers(report, currency)
    _render_benchmarks(report, market)
    await _render_holding_history(market, holding_rows, in_window,
                                  window_start, window_end, currency, error=holding_error)
    _render_snapshot_table(in_window, currency)


def _render_substitute_notice(period, ref_date, display_date) -> None:
    """📅 "선택하신 날은 기록이 없어, 가장 최근 기록일 자료를 보여드립니다" 안내 (#117).

    🔴 이 한 줄이 이 기능의 **전제 조건**입니다(§0-1). 화면에 "2026-08-16(일) 기준"이라고
       써 놓고 실제로는 2026-08-14(금) 숫자를 보여주면 그건 지어낸 것과 같은 수준의 거짓말이
       됩니다. 그래서 회색 캡션이 아니라 **눈에 띄는 경고 상자**로, 두 날짜를 **둘 다** 적어
       띄웁니다(무엇을 골랐고, 실제로는 언제 자료를 보고 있는지).

    ⚠️ "휴장일" 이라고 단정하지 않습니다 — 이 프로젝트는 거래일 캘린더를 갖고 있지 않고,
       기록이 없는 이유는 휴장일 수도 있고 그날 배치가 실패했을 수도 있습니다.
    """
    warning_banner(
        f'📅 {period_title(period, ref_date)} 은(는) 저장된 기록이 없는 날입니다'
        '(주말·공휴일 등 장이 열리지 않은 날). 대신 그 이전 가장 최근 기록일인 '
        f'{period_title(period, display_date)} 자료를 보여드립니다 — '
        f'아래 숫자는 전부 {display_date.isoformat()} 기준이며, '
        f'{ref_date.isoformat()} 의 값이 아닙니다.'
    )


def _render_price_stamp(market, row) -> None:
    """🕐 "이 블록의 숫자는 **언제 종가**로 만들어졌나" (2026-08-13 오너 요청).

    ⚠️ '내 성적표'의 같은 표시와 성격이 다릅니다. 거기는 지금 화면이 쓰는 **최신 스냅샷 파일**의
       시각이지만, 리포트는 **DB 에 저장된 과거 어느 날의 값**을 보여주는 화면입니다. 그래서
       오늘 파일이 아니라 **그 행이 저장될 때 배치가 기록해 둔 시각**(`price_as_of_kst`)만
       씁니다. 오늘 시각으로 대신 채우면 그 자체가 거짓말입니다(§0-1).
    """
    stamp = (row or {}).get(PRICE_STAMP_FIELD)
    session_day = row["snapshot_date"].isoformat() if row and row.get("snapshot_date") else "—"
    tail = f'수집 {esc(stamp)} (한국시간)' if stamp else '수집 시각 정보 없음'
    ui.html(f'🕐 <b>{esc(session_day)} 종가 기준</b> 　·　 {tail}').classes('w-full')
    if market == MARKET_US:
        _muted('미국장은 한국시간 새벽에 마감돼 수집 시각이 거래일 다음 날로 찍힙니다.')


def _render_shortage(report, currency: str) -> None:
    """데이터가 부족한 구간은 **작은 경고 하나 붙인 정상 리포트**처럼 꾸미지 않고,
    부족하다는 사실 자체를 주 컨텐츠로 보여줍니다 (작업지시서 §3)."""
    error_banner(f'📭 데이터 부족 — {report["status_message"]}')
    _muted(REPORT_NO_BACKFILL_NOTICE)

    if report["status"] == STATUS_NO_DATA:
        return
    # 부족하더라도 지금까지 쌓인 값 자체는 숨기지 않습니다(숨기면 그것대로 불친절) —
    # 다만 "정식 리포트"와 명확히 구분되도록 접어 둡니다.
    with ui.expansion('그래도 지금까지 쌓인 만큼만 보기 (정식 리포트 아님)').classes('w-full'):
        _render_numbers(report, currency, incomplete=True)


def _render_numbers(report, currency: str, incomplete: bool = False) -> None:
    baseline, latest = report["baseline"], report["latest"]

    # 무엇과 무엇을 비교했는지는 §0-1 상 절대 뺄 수 없습니다.
    _muted(
        f'비교 구간: {baseline["snapshot_date"].isoformat()} → '
        f'{latest["snapshot_date"].isoformat()} '
        + ('(기간 시작 직전 기록이 기준점)'
           if report["baseline_kind"] == "prior_close"
           else '(기간 시작 전 기록이 없어 기간 안 첫 기록이 기준점)')
    )

    with ui.row().classes('w-full gap-4 items-stretch'):
        metric_card('기간 시작 평가금액', format_amount(baseline.get("total_value"), currency))
        metric_card('기간 종료 평가금액', format_amount(latest.get("total_value"), currency))
        metric_card('평가금액 변화', format_amount(report.get("value_change"), currency),
                    delta_html=pct_html(report.get("value_change_pct")))

    with ui.row().classes('w-full gap-4 items-stretch'):
        metric_card('기간 시작 누적수익률', pct_text(report.get("profit_pct_start")))
        metric_card('기간 종료 누적수익률', pct_text(report.get("profit_pct_end")))
    # 공식은 뺐지만, **누적과 기간 변화가 다른 숫자**라는 사실은 남깁니다 — 바로 위에 두 값이
    # 나란히 있어서 헷갈리면 숫자를 오해하게 됩니다.
    _muted('누적수익률은 매수 시점부터의 누적입니다(이 기간의 변화가 아닙니다).')

    if incomplete:
        warning_banner('⚠️ 위 숫자는 기간 전체가 아니라 실제로 쌓인 구간만의 값입니다.')

    # 구성 변경·가격 결측 안내는 색 상자 하나로 합쳤습니다(둘 다 §0-1 고지라 삭제 불가).
    alerts = list(report.get("composition_notes") or []) if report.get("composition_changed") else []
    if report.get("coverage_note"):
        alerts.append(report["coverage_note"])
    if alerts:
        warning_banner('⚠️ ' + ' '.join(alerts))


# =============================================================================
# 5. 벤치마크 비교
# =============================================================================
def _benchmark_short_label(label: str) -> str:
    """'S&P 500 (SPY ETF 종가 기준)' → 'S&P 500'. 평균 줄 하나에 두 벤치마크 이름을 나란히
    넣으려고 괄호 안 설명만 떼어냅니다. 프록시라는 사실은 위 두 줄의 라벨과 맨 아래 한 줄
    고지에 그대로 남아 있으므로 여기서 정보가 사라지지는 않습니다(§0-1)."""
    text = (label or '').strip()
    return text.split(' (')[0].strip() or text


def _benchmark_average_html(outcomes, market, mine):
    """🇺🇸 **미국 두 벤치마크 수익률의 단순 평균** 한 줄 (#116, 오너 요청).

    ⚠️ **라벨을 'VOO / QQQ' 라고 쓰지 않습니다.** 오너의 수기 표는 VOO·QQQ 로 적혀 있었지만,
       이 프로젝트가 실제로 수집·저장하는 값은 **SPY·ONEQ 종가**입니다. 가지고 있지도 않은
       종가로 계산한 것처럼 적으면 그 자체가 지어낸 값입니다(§0-1).
    ⚠️ **둘 다 계산됐을 때만** 그립니다. 한쪽이 '비교 불가'인 기간에 나머지 하나로 평균을
       만들면 그건 평균이 아니고, "평균: 데이터 없음" 같은 줄도 넣지 않습니다 — 계산할 수
       없으면 **조용히 생략**합니다(벤치마크가 하나뿐인 한국 시장도 마찬가지).
    ⚠️ 시작·종가 괄호는 붙이지 않습니다 — 서로 다른 두 ETF 가격의 평균은 아무 뜻이 없습니다.
    """
    if market != MARKET_US:
        return None
    picked = [outcomes.get(key) for key in US_BENCHMARK_KEYS]
    if any(item is None or not item[1]["available"] for item in picked):
        return None

    average = sum(item[1]["change_pct"] for item in picked) / len(picked)
    names = ' / '.join(_benchmark_short_label(item[0]["label"]) for item in picked)
    line = f'<b>{esc(names)} 평균</b> {pct_html(average)}'
    if mine is not None:
        gap = f'{mine - average:+.2f}%p'
        line += f' · 내 포트폴리오 {pct_html(mine)} → 차이 {esc(gap)}'
    return line


def _render_benchmarks(report, market) -> None:
    """포트폴리오와 **정확히 같은 두 날짜**로 벤치마크 수익률을 계산해 나란히 보여줍니다."""
    ui.markdown('##### 📊 벤치마크 비교')
    benchmarks = benchmark_closes_for_market(market)
    if not benchmarks:
        _muted('이 시장의 벤치마크 데이터가 아직 없어 비교를 생략합니다.')
        return

    baseline_date = report["baseline"]["snapshot_date"]
    end_date = report["latest"]["snapshot_date"]
    mine = report.get("value_change_pct")

    has_proxy = False
    # 평균 줄이 쓰려고 계산 결과를 심볼별로 들고 있습니다. 같은 수익률을 두 번 계산하지 않기
    # 위한 것이라, 위 줄들과 평균 줄의 숫자는 항상 같습니다.
    outcomes = {}
    lines = []
    for benchmark in benchmarks:
        outcome = benchmark_period_return(benchmark["closes"], baseline_date, end_date)
        outcomes[benchmark["symbol"]] = (benchmark, outcome)
        if not outcome["available"]:
            lines.append(f'<b>{esc(benchmark["label"])}</b>: 비교 불가 — {esc(outcome["reason"])}')
            continue
        has_proxy = has_proxy or bool(benchmark.get("is_proxy"))
        span = f'( {outcome["start_value"]:,.2f} → {outcome["end_value"]:,.2f} )'
        line = (f'<b>{esc(benchmark["label"])}</b> {pct_html(outcome["change_pct"])} '
                f'{esc(span)}')
        if mine is not None:
            gap = f'{mine - outcome["change_pct"]:+.2f}%p'
            line += f' · 내 포트폴리오 {pct_html(mine)} → 차이 {esc(gap)}'
        lines.append(line)

    average_line = _benchmark_average_html(outcomes, market, mine)
    if average_line:
        lines.append(average_line)

    ui.html('<ul style="margin: 0 0 8px 1.2em; line-height: 1.9;">'
            + ''.join(f'<li>{line}</li>' for line in lines)
            + '</ul>').classes('w-full')

    if has_proxy:
        # ⚠️ 이 고지는 §0-1 상 삭제 불가입니다(지수 자체가 아니라 ETF 종가라는 사실).
        _muted('지수 포인트가 아니라 추종 ETF 종가 기준입니다(기간 비교용 근사치).')


# =============================================================================
# 6. 종목별 상세 · 비중 변화 · 스냅샷 원본
# =============================================================================
async def _render_holding_history(market, holding_rows, snapshots_in_window,
                                  window_start, window_end, currency, error=None) -> None:
    """🧾 종목별 상세 — 기간 안 **마지막 기록일 하루**의 종목별 상태를 한 표에 담습니다.

    · **한 장** — 기간 안의 모든 날짜 × 모든 종목을 늘어놓지 않습니다(합계 한 줄 포함).
    · **일별 추이는 펼쳐서** — 종목 하나를 고르면 그 종목의 기간 내 일별 표가 나옵니다.
    · **날짜를 섞지 않습니다** — 표의 모든 행은 같은 거래일 값입니다.
    · **들쑥날쑥 감시** — 이 표의 합계와 같은 날 합계 스냅샷을 매번 대조하고, **어긋났을 때만**
      경고합니다(정상일 때 "대조 통과" 같은 줄은 방문자에게 소음이라 띄우지 않습니다).
    · 가격을 몰랐던 날은 빈칸이 아니라 **"가격 모름"** — 이전 가격을 대신 넣지 않습니다(§0-1).
    """
    ui.markdown('##### 🧾 종목별 상세')

    if error is not None:
        if is_missing_holding_table_error(error):
            # 아직 표가 없는 상태(오너가 SQL 실행 전). 리포트의 나머지는 정상이므로 이 섹션만
            # 안내로 대체합니다.
            info_banner('ℹ️ 종목별 상세는 아직 준비되지 않았습니다.')
            with ui.expansion('🔧 관리자: 이 표를 켜는 방법').classes('w-full'):
                ui.markdown(
                    'Supabase → SQL Editor 에서 `sql/report_schema.sql` 전체를 다시 실행하세요'
                    '(여러 번 실행해도 안전하고 기존 기록은 그대로입니다). 실행한 **다음 날 '
                    '배치부터** 종목별 기록이 쌓이며, 그 이전 날짜는 소급해서 만들지 않습니다.'
                )
        else:
            error_banner(f'🚫 {_fail(error, "종목별 기록을 불러오지 못했습니다.")}')
        return

    try:
        history = build_holding_history(holding_rows or [], window_start, window_end)
    except ReportError as exc:
        # ⚠️ 이 경로의 메시지는 **우리가 쓴 한국어**뿐입니다(예: "서로 다른 시장·통화가 섞여
        #    있습니다 — 합산하지 않고 중단합니다"). 외부 원문이 섞일 수 없으므로 그대로
        #    보여줍니다 — 이게 §0-1 이 요구하는 "실패 사실이 화면까지 도달"입니다.
        error_banner(f'🚫 {exc}')
        return
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "종목별 기록을 정리하지 못했습니다.")}')
        return

    if not history["rows"]:
        _muted('이 기간에는 종목별 기록이 없습니다(종목별 저장은 2026-08-13부터 — 그 이전 날짜는 '
               '합계만 남아 있고 소급해서 만들지 않습니다).')
        return

    base_date = history["base_date"]
    totals = history["totals"]
    dates = history["dates"]

    # 🇺🇸 미국 블록일 때만 유니버스 스냅샷을 한 번 읽어 아래 모든 라벨에 같은 값을 씁니다
    #    (한 섹션 안에서 표마다 다시 읽으면 표마다 이름이 달라질 수 있습니다).
    indexes = await _display_indexes(market)

    _muted(f'{base_date.isoformat()} 하루 기준 '
           f'(이 기간 기록 {len(dates)}일: {dates[0].isoformat()} ~ {dates[-1].isoformat()})')

    rows_html = []
    for row in history["rows"]:
        if row["priced"]:
            price_cell = esc(format_amount(row["current_price"], currency))
            value_cell = esc(format_amount(row["market_value"], currency))
            profit_cell = esc(format_amount(row["profit"], currency))
            pct_cell = pct_html(row["profit_pct"])
        else:
            # 빈칸으로 얼버무리거나 이전 가격을 대신 넣지 않습니다(§0-1).
            price_cell = '<b>가격 모름</b>'
            value_cell = profit_cell = pct_cell = '—'
        rows_html.append([
            _holding_label_html(row, market, indexes),
            esc(_weight_text(row.get("weight_pct"))),
            esc(_qty_text(row["quantity"])),
            esc(format_amount(row["avg_purchase_price"], currency)),
            price_cell, value_cell, profit_cell, pct_cell,
            pct_html(row["price_change_pct"]),
        ])
    # 합계 줄 — 칸 순서를 헤더와 정확히 맞춥니다(9칸). '평균매입가' 칸에는 단가가 아니라
    # **원가 합계**가 들어가므로 칸 안에 '원가합'이라고 써 넣어 설명이 필요 없게 했습니다.
    rows_html.append([
        f'<b>합계 {esc(totals["holdings_count"])}종목</b>',
        # 그날 가격을 아는 종목이 하나도 없으면 분모 자체가 없습니다 — 그때 '100%'라고 쓰면
        # 아무것도 계산하지 않고 다 계산한 척하는 게 됩니다(§0-1).
        f'<b>{"100.00%" if totals["market_value"] is not None else "—"}</b>',
        '',
        f'<b>원가합 {esc(format_amount(totals["cost"], currency))}</b>',
        '',
        f'<b>{esc(format_amount(totals["market_value"], currency))}</b>',
        f'<b>{esc(format_amount(totals["profit"], currency))}</b>',
        pct_html(totals["profit_pct"]),
        '',
    ])
    ui.html(holdings_table_html(
        ['종목', '비중', '수량', '평균매입가', '현재가', '평가금액', '평가손익', '수익률', '주가등락'],
        rows_html,
    )).classes('w-full')
    # 바로 옆 칸의 '수익률'과 뜻이 달라서 이 한 줄은 남깁니다(오해하면 숫자를 잘못 읽습니다).
    _muted('주가등락 = 이 기간 첫 기록가 → 기준일 종가 (수량 변화와 무관한 주가만의 등락)')
    if totals["unpriced_count"]:
        # 정상일 땐 조용히, 실제로 빠진 종목이 있을 때만 — 합계·비중의 분모가 달라지므로
        # 이건 §0-1 상 반드시 알려야 하는 정보입니다.
        _muted(f'⚠️ 그날 가격을 몰라 합계·비중에서 빠진 종목 {totals["unpriced_count"]}개 — '
               f'그 종목까지 포함한 매입원가는 {format_amount(totals["cost_all"], currency)} 입니다.')

    _render_weight_changes(history, base_date, market, indexes)

    # ---- 🔴 들쑥날쑥 감시 — 같은 날 합계 스냅샷과 대조 --------------------------
    summary_row = next((r for r in (snapshots_in_window or [])
                        if r.get("snapshot_date") == base_date), None)
    outcome = compare_holding_total(
        totals["market_value"], summary_row.get("total_value") if summary_row else None)
    #    · 일치: 아무것도 그리지 않습니다. · 대조 불가: 역시 조용히 넘어갑니다(말하지 않는 것과
    #      "일치한다"고 말하는 것은 전혀 다릅니다). · 불일치: 그대로 경고합니다(이 대조의 존재 이유).
    if outcome["comparable"] and not outcome["matches"]:
        warning_banner(
            f'⚠️ 대조 불일치 — 종목별 합계({format_amount(totals["market_value"], currency)})와 '
            f'같은 날 합계 스냅샷({format_amount(summary_row.get("total_value"), currency)})이 '
            f'서로 다릅니다(차이 {outcome["diff"]:+,.6f}). 그날 종목별 저장이 중간에 실패했을 수 '
            '있습니다 — 다음 배치가 같은 날짜를 다시 저장하면 맞춰집니다.'
        )

    if history["gone"]:
        gone_text = ', '.join(
            f'{_holding_name(g, market, indexes)}({g["ticker"]}, '
            f'마지막 기록 {g["last_date"].isoformat()})'
            for g in history["gone"]
        )
        _muted(f'⏹ 기간 중 기록이 끊긴 종목(매도 등): {gone_text}')

    _render_daily_picker(history, market, indexes, currency)


def _render_weight_changes(history, base_date, market=None, indexes=None) -> None:
    """📊 **비중 변화** — 오너가 수기로 관리하던 표("종목 | 지난달 비중 | 이번달 비중 | 차이").

    ⚠️ 비교 시작점은 "지난 기간"이 아니라 **이 기간 안의 첫 기록일**입니다. 종목별 스냅샷은
       보고 있는 기간만 조회하므로 기간 이전의 종목별 기록은 애초에 손에 없습니다 —
       그래서 두 날짜를 표 머리글에 그대로 박아 둡니다(무엇과 무엇을 비교했는지 숨기지 않기).
    ⚠️ 기록이 하루뿐이면 표 자체를 그리지 않습니다(비교할 게 없는데 0%p 를 늘어놓지 않기).
    """
    weights = build_weight_comparison(history)
    if not weights["comparable"] or not weights["rows"]:
        return

    first_label = weights["first_date"].isoformat()
    base_label = base_date.isoformat()
    _muted(f'📊 비중 변화 — {first_label} → {base_label}')

    rows_html = [[
        _holding_label_html(row, market, indexes),
        esc(_weight_text(row["first_pct"])),
        esc(_weight_text(row["base_pct"])),
        _pp_html(row["change_pp"]),
    ] for row in weights["rows"]]
    ui.html(holdings_table_html(['종목', first_label, base_label, '변화'], rows_html)).classes('w-full')

    if weights["unpriced_first"] or weights["unpriced_base"]:
        # 정상일 땐 조용히, 실제로 '모름'이 있을 때만.
        _muted("가격을 몰랐던 종목은 비중을 '모름'으로 두고 분모에서 뺐습니다(0%로 치지 않습니다).")


def _render_daily_picker(history, market, indexes, currency: str) -> None:
    """📅 종목 하나를 골라 그 종목의 기간 내 일별 추이를 봅니다.

    (종목 수만큼 expander 를 늘어놓으면 그 자체가 '한 장'을 깨뜨려서 선택 방식으로 했습니다.)
    고르는 목록의 라벨도 위 표와 같은 규칙(미국은 한글명)이라 같은 종목이 두 이름으로
    보이지 않습니다(#115).
    """
    options = {}
    for row in history["rows"]:
        options[row["ticker"]] = _holding_name(row, market, indexes) + f' ({row["ticker"]})'
    for gone in history["gone"]:
        options[gone["ticker"]] = _holding_name(gone, market, indexes) + f' ({gone["ticker"]})'
    if not options:
        return

    picked = {'ticker': next(iter(options))}

    with ui.expansion('📅 종목 하나를 골라 이 기간 일별 추이 보기').classes('w-full'):
        def _on_pick(event) -> None:
            if event.value:
                picked['ticker'] = event.value
                table.refresh()

        ui.select(options, value=picked['ticker'], label='종목', on_change=_on_pick).classes('w-full')

        @ui.refreshable
        def table() -> None:
            daily = history["daily_by_ticker"].get(picked['ticker']) or []
            if not daily:
                _muted('이 종목의 일별 기록이 없습니다.')
                return
            rows_html = []
            for row in daily:
                if row["priced"]:
                    cells = (esc(format_amount(row["current_price"], currency)),
                             esc(format_amount(row["market_value"], currency)),
                             esc(format_amount(row["profit"], currency)),
                             pct_html(row["profit_pct"]))
                else:
                    cells = ('<b>가격 모름</b>', '—', '—', '—')
                rows_html.append([
                    esc(row["snapshot_date"].isoformat()),
                    esc(row.get(PRICE_STAMP_FIELD) or '기록 없음'),
                    esc(_qty_text(row["quantity"])),
                    *cells,
                ])
            ui.html(holdings_table_html(
                ['거래일', '종가 수집 시각(KST)', '수량', '현재가', '평가금액', '평가손익', '수익률'],
                rows_html,
            )).classes('w-full')
            _muted('저장된 날만 나옵니다(휴장일 등 빠진 날을 이전 값으로 채우지 않습니다).')

        table()


def _render_snapshot_table(rows_in_window, currency: str) -> None:
    with ui.expansion('이 기간에 저장된 스냅샷 원본 보기').classes('w-full'):
        if not rows_in_window:
            _muted('이 기간에 저장된 스냅샷이 없습니다.')
            return
        rows_html = []
        for row in rows_in_window:
            benchmark = (f'{row.get("benchmark_symbol")} {row.get("benchmark_value"):,.2f}'
                         if row.get("benchmark_value") is not None
                         else f'{row.get("benchmark_symbol") or "—"} 없음')
            # 날짜마다 수집 시각이 다를 수 있어(수집 지연·재수집) 행별로 그날 값을 그대로 씁니다.
            rows_html.append([
                esc(row["snapshot_date"].isoformat()),
                esc(row.get(PRICE_STAMP_FIELD) or '기록 없음'),
                esc(format_amount(row.get("total_value"), currency)),
                esc(format_amount(row.get("total_cost"), currency)),
                esc(f'{row.get("priced_count")}/{row.get("holdings_count")}'),
                esc(benchmark),
            ])
        ui.html(holdings_table_html(
            ['거래일', '종가 수집 시각(KST)', '평가금액', '매입원가', '담긴 종목', '벤치마크'],
            rows_html,
        )).classes('w-full')
        _muted("'담긴 종목' = 그날 현재가를 알아 합계에 들어간 종목 수 / 전체 보유 종목 수.")
