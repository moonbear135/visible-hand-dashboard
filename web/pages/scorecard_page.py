"""
📊 내 성적표 — 내 보유 종목 입력 + 손익/비중 + 밸류에이션 대조 (로그인 필요, URL `/scorecard`).

`views/scorecard_view.py`(Streamlit, 1,206줄)의 NiceGUI 이식본입니다 (이전 계획서 4단계).
Streamlit 쪽 원본은 컷오버까지 그대로 살려둡니다(듀얼런 — 계획서 §11-1).

🔴 이 화면은 이 프로젝트에서 **유일하게 사용자의 실제 자산 정보를 다루는 화면**입니다.
   ENGINEERING_SPEC.md §0-3-8(최상위 금지사항)을 먼저 읽고 고치세요. 요약하면:

   1. **사용자 데이터는 모듈 전역에 두지 않습니다.** 이 파일의 모듈 최상위에는 상수(문자열/
      숫자/읽기전용 튜플)만 있습니다. 보유종목·클라이언트·사용자 id 는 전부 `@ui.page` 함수
      안의 지역 변수이거나, 함수 인자로 명시적으로 전달됩니다.
   2. **"지금 누가 로그인했는지"를 암묵적으로 추측하지 않습니다.** DB를 만지는 모든 함수는
      `client`(그 접속 전용 Supabase 클라이언트)와 `user_id`를 **인자로 받아야만** 동작합니다
      (§0-3-8 "함수 설계 원칙", `web/auth.py` 참고).
   3. 이 규칙이 지켜지는지 `tests/test_web_session_isolation.py` 가 자동으로 검사합니다.
      그 테스트가 통과하기 전까지 이 화면은 공개되지 않습니다(§0-3-6 승인 조건).

이식 방침 (2·3단계와 동일)
   - **계산·DB 계층(`utils/scorecard_db.py`)은 한 줄도 건드리지 않습니다.** 이 파일은 순수
     표현 계층입니다 — 손익/가중평균/비중 계산식을 여기에 새로 넣지 마세요.
   - 사용자 입력·DB 값이 HTML 로 나가는 곳은 전부 `esc()` 를 거칩니다 (§0-3-9 XSS).
   - "종목 관리" 줄(종목명 + ✏️ + 🗑️)은 #127~#130 에서 여섯 번 싸운 그 레이아웃입니다.
     `st.columns()` 가 사라졌으므로 `ui.row().classes('no-wrap ...')` 하나로 항상 한 줄입니다
     (`web/pages/demo_page.py` 의 "패턴 A" 와 동일 — 실기기 검증 완료된 방식).
   - 비밀번호 찾기는 **지금 잘 동작하는 코드(OTP) 방식을 그대로** 유지합니다 (계획서 §6-3 주의 4).

오너 확정 사항(그대로 유지)
   - **환율 변환 없음** — 원화/달러를 절대 합치지 않고 통화별로 따로 계산·표시합니다.
   - 현재가는 기존 수집 스냅샷의 실측값만 씁니다. 유니버스 밖은 "현재가 없음"으로 정직하게
     표시하고 평가금액·수익률을 계산하지 않습니다 (§0-1).
"""

from nicegui import ui

from utils.company_names_kr import resolve_korean_name
from utils.scorecard_db import (
    KR_ALL_MARKET_PRICES_FILENAME,
    KR_TICKER_MASTER_FILENAME,
    MARKET_KR,
    MARKET_LABELS,
    MARKET_US,
    NO_FEES_TAXES_NOTICE,
    NO_FX_CONVERSION_NOTICE,
    SNAPSHOT_FILENAMES,
    SORT_FIELD_OPTIONS,
    US_ALL_ETF_PRICES_FILENAME,
    US_ALL_MARKET_PRICES_FILENAME,
    ScorecardError,
    add_lot,
    build_portfolio,
    build_universe_index,
    current_user,
    delete_holding,
    fetch_holdings,
    format_amount,
    make_price_lookup,
    reset_password_with_code,
    resolve_stock_query,
    send_password_reset_code,
    sign_up,
    sort_holding_rows,
    supabase_status,
    update_holding,
    user_id_of,
    valuation_summary,
)

from web.auth import get_client, has_supabase_session, login, logout, new_auth_client
from web.components import compact, error_banner, esc, info_banner, metric_card, warning_banner
from web.layout import layout
from web.state import data_path, load_json_file

# 원형차트는 plotly 로 그립니다(요구사항에 이미 있고 매크로 화면에서도 사용 중).
# 그래도 없을 때 화면 전체가 죽지 않도록 감싸두고, 없으면 표로 대체합니다(원본과 동일 정책).
try:
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:  # pragma: no cover
    px = None
    PLOTLY_AVAILABLE = False


CURRENCY_TITLES = {
    "KRW": "🇰🇷 한국 주식 (원화)",
    "USD": "🇺🇸 미국 주식 (달러)",
}

# DB 컬럼이 `numeric(20, 6)` 이라 정수부는 14자리까지만 들어갑니다
# (sql/scorecard_schema.sql). 그보다 큰 값은 Postgres 가 `numeric field overflow` 로 거절하는데,
# 그 원문을 사용자에게 보여주는 대신 화면에서 먼저 막고 한국어로 설명합니다.
# ⚠️ 이 상수는 DB 정의에서 그대로 유도한 값이지 임의로 정한 값이 아닙니다
#    (views/scorecard_view.py 의 MAX_INPUT_VALUE 와 동일 — 컷오버 때 옛 파일이 사라지며 일원화됩니다).
MAX_INPUT_VALUE = 10 ** 14  # 이 값 **이상**은 저장 불가

# 정렬 드롭다운의 "정렬하지 않음" 항목 (추가한 순서 그대로)
_SORT_NONE = "기본순서"

# 차트 배경/글자색 — 이 화면은 다크 모드 고정(web/layout.py)이라 plotly 기본 흰 배경을 쓰면
# 차트만 하얗게 뜹니다. **figure 의 데이터(names/values)는 원본과 한 글자도 다르지 않고**,
# 배경 투명화와 글자색만 지정합니다 (계획서 §7).
_CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2e8f0"),
    margin=dict(t=10, b=10, l=10, r=10),
    showlegend=False,
)


# =============================================================================
# 1. 공통 표시 도우미 (전부 순수 함수 — 상태를 갖지 않습니다)
# =============================================================================
def _fail(exc, fallback: str) -> str:
    """예외 → 사용자에게 보여줄 한국어 한 문장.

    `ScorecardError` 는 우리가 직접 만든 한국어 메시지라 그대로 보여줍니다(원본 화면과 동일).
    그 밖의 예상 못 한 예외는 **원문을 화면에 흘리지 않고**(§0-3-4) 서버 로그로만 보냅니다.
    """
    if isinstance(exc, ScorecardError):
        return str(exc)
    print(f'⚠️ 내 성적표 처리 중 예상하지 못한 오류: {type(exc).__name__}: {exc}')
    return fallback


def _us_korean_name(row, indexes):
    """미국 종목은 티커+한글명으로 표기 (원본 `_us_korean_name` 과 동일 로직).

    공개 미국주식 화면과 **완전히 같은 값**을 재사용합니다 — 상위 550 유니버스 안이면
    스냅샷에 미리 계산돼 있는 `name_kr`, 밖이면 같은 모듈(`utils/company_names_kr.py`)을
    즉석 호출. 한글명을 못 만들면 지어내지 않고 영문명/티커로 되돌아갑니다(§0-1).
    """
    ticker = row["ticker"]
    stock = (indexes.get(MARKET_US) or {}).get(ticker)
    if stock and stock.get("name_kr"):
        return stock["name_kr"]
    english_name = row.get("stock_name") or ticker
    result = resolve_korean_name(ticker, english_name)
    return result.get("korean_name") or result.get("english_clean") or english_name


def _display_name(row, indexes):
    if row.get("market") == MARKET_US:
        return _us_korean_name(row, indexes)
    return row.get("stock_name")


def _row_label(row, indexes) -> str:
    """평문 라벨 ("종목명 (코드)"). HTML 로 나갈 때는 반드시 esc() 를 거칩니다."""
    name = _display_name(row, indexes)
    return f"{name} ({row['ticker']})" if name else str(row["ticker"])


def _row_chart_label(row, indexes) -> str:
    """차트 범례 전용 — 종목코드를 빼서 글자를 줄입니다 (2026-08-13 오너 요청 유지)."""
    name = _display_name(row, indexes)
    return name if name else str(row["ticker"])


def _row_label_html(row, indexes) -> str:
    """표의 "종목" 칸 — "종목명 / (코드)" 두 줄.

    🔐 §0-3-9 — `stock_name` 은 **DB에 저장되는 사용자 소유 컬럼**입니다. Supabase 는 설계상
       anon key + 로그인 JWT 로 REST 를 직접 호출할 수 있어, 로그인한 사용자가 이 화면을 거치지
       않고 자기 행의 stock_name 에 `<img src=x onerror=...>` 같은 값을 써넣는 것이 가능합니다.
       RLS 덕분에 그 값은 본인 화면에만 그려지지만, 본인 세션에서 실행되는 스크립트는 그 사람의
       Supabase 토큰을 훔칠 수 있어("이 문자열을 종목명에 붙여넣어 보세요" 식의 사회공학)
       그대로 두면 안 됩니다. esc() 를 거치면 **글자 그대로** 보입니다.
    """
    name = _display_name(row, indexes)
    safe_name = esc(str(name)) if name else None
    safe_ticker = esc(str(row["ticker"]))
    label = f"{safe_name}<br>({safe_ticker})" if safe_name else safe_ticker
    return f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">{label}</div>'


def _pct_html(value) -> str:
    """수익률 — 국내 증시 관례대로 오르면 빨강 / 내리면 파랑 (원본과 동일 색·동일 서식)."""
    if value is None:
        return "—"
    text = f"{value:+.2f}%"
    if value > 0:
        return f"<span style='color:#f87171; font-weight:700;'>{esc(text)}</span>"
    if value < 0:
        return f"<span style='color:#60a5fa; font-weight:700;'>{esc(text)}</span>"
    return esc(text)


def _pct_text(value) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _parse_positive_number(raw, label):
    """텍스트 입력 → 양수 float. 콤마(1,664,333)와 앞뒤 공백을 허용합니다.

    ⚠️ 값을 지어내지 않습니다 — 비어있거나 숫자가 아니면 예외를 던집니다(§0-1).
    🔐 `float()` 는 `"nan"`·`"inf"`·`"1e400"` 을 **모두 성공적으로 파싱**하고, `nan <= 0` 과
       `inf <= 0` 은 둘 다 거짓이라 단순한 양수 검사를 그냥 통과해버립니다(2026-08-13 공개
       전환 전 점검에서 실제로 발견된 문제 — views/scorecard_view.py 의 같은 함수 주석 참고).
       그래서 유한성과 DB 상한을 여기서 함께 확인합니다. 추가 폼과 수정 폼이 이 함수 하나를
       공유하므로 두 경로 모두 잘못된 값이 네트워크 밖으로 나가지 않습니다.
    """
    text = str(raw or "").strip().replace(",", "")
    if not text:
        raise ValueError(f"{label}을(를) 입력해 주세요.")
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"{label}은(는) 숫자로 입력해 주세요: {raw!r}")
    if number != number or number in (float("inf"), float("-inf")):
        # NaN 은 자기 자신과도 다르다는 성질로 판별합니다(math.isnan 과 동일, import 불필요).
        raise ValueError(f"{label}은(는) 실제 숫자로 입력해 주세요: {raw!r}")
    if number <= 0:
        raise ValueError(f"{label}은(는) 0보다 커야 합니다.")
    if number >= MAX_INPUT_VALUE:
        raise ValueError(
            f"{label}이(가) 너무 큽니다 — 저장할 수 있는 최대값은 "
            f"{MAX_INPUT_VALUE - 1:,}(약 100조 미만)입니다: {raw!r}"
        )
    return number


# =============================================================================
# 2. 읽기 전용 시장 데이터 (모든 사용자에게 동일 — 개인정보가 아닙니다)
# =============================================================================
#  ⚠️ §0-3-8 의 구분선: 여기서 읽는 `data/*.json` 은 **모든 접속자에게 똑같은 시세 스냅샷**이라
#     프로세스 전역 캐시(web/state.py)를 써도 안전합니다(계획서 §3-3 규칙 4). 사용자별
#     데이터(보유종목·토큰)는 절대 이 경로로 흐르지 않습니다.
#  ⚠️ 파일을 여는 방식만 `web/state.load_json_file`(mtime 캐시)로 바꾸고, payload → 인덱스로
#     만드는 계산은 기존 `scorecard_db.build_universe_index()` 를 **그대로** 씁니다.
#     즉 결과값은 Streamlit 화면과 100% 동일하고, 접속할 때마다 2.2MB JSON 을 다시 파싱하는
#     비용만 사라집니다 (§0-3-10 자원 낭비 금지).
# =============================================================================

def _load_index(filename: str, market: str):
    """(인덱스, 메타데이터). 파일이 없거나 깨졌으면 ({}, None) — 화면은 그대로 동작합니다."""
    payload, _load_error = load_json_file(data_path(filename))
    if payload is None:
        return {}, None
    return build_universe_index(payload, market), (payload or {}).get("metadata")


def _load_market_data() -> dict:
    """이 화면이 쓰는 스냅샷 5종을 한 번에 읽어 하나의 dict 로 돌려줍니다.

    ⚠️ 반환값에는 **사용자 데이터가 한 조각도 들어있지 않습니다** — 시세/종목명뿐입니다.
       그래서 이 dict 는 함수 사이로 자유롭게 넘겨도 §0-3-8 위반이 아닙니다.
    """
    kr_index, kr_meta = _load_index(SNAPSHOT_FILENAMES[MARKET_KR], MARKET_KR)
    us_index, us_meta = _load_index(SNAPSHOT_FILENAMES[MARKET_US], MARKET_US)

    # 상위 200/550 유니버스 **밖** 종목을 위한 보조 목록들. 밸류에이션은 없고 이름/가격만
    # 있습니다 — `indexes` 와 절대 섞지 않습니다(섞으면 "밸류에이션 정보 없음"이라는 정직한
    # 메시지 대신 빈 값투성이 카드가 "찾음"으로 표시됩니다. scorecard_db 주석 참고).
    kr_master, _ = _load_index(KR_TICKER_MASTER_FILENAME, MARKET_KR)
    kr_all_prices, _ = _load_index(KR_ALL_MARKET_PRICES_FILENAME, MARKET_KR)
    us_all_prices, _ = _load_index(US_ALL_MARKET_PRICES_FILENAME, MARKET_US)
    us_etf_prices, _ = _load_index(US_ALL_ETF_PRICES_FILENAME, MARKET_US)
    if us_etf_prices:
        # 수집기가 주식/ETF 파일을 나눠 저장하므로(한쪽 실패가 다른 쪽을 지우지 않도록)
        # 합치는 일은 읽는 쪽에서 합니다. 티커 공간이 겹치지 않지만 겹치면 보통주 우선.
        us_all_prices = {**us_etf_prices, **us_all_prices}

    return {
        "indexes": {MARKET_KR: kr_index, MARKET_US: us_index},
        "kr_master": kr_master,
        "kr_all_prices": kr_all_prices,
        "us_all_prices": us_all_prices,
        # ⚠️ 초(seconds) 단위는 표시하지 않습니다 — 수집기 메타데이터 자체가 분 단위까지만
        #    기록합니다. 없는 정밀도를 ':00' 으로 지어내지 않습니다(§0-1).
        "sync_labels": {
            "KRW": (f"현재가 : {kr_meta['last_updated_at']} 기준"
                    if kr_meta and kr_meta.get("last_updated_at") else None),
            "USD": (f"현재가 : {us_meta['last_updated_at_kst']} 기준 (KST)"
                    if us_meta and us_meta.get("last_updated_at_kst") else None),
        },
    }


# =============================================================================
# 3. 페이지 (로그인 게이트)
# =============================================================================
@ui.page('/scorecard')
def scorecard_page() -> None:
    with layout('📊 내 성적표'):
        _render_header()

        status = supabase_status()
        if not status.available:
            _render_not_ready(status)
            return

        # ── 로그인 게이트 ────────────────────────────────────────────────────
        # 토큰이 없으면 로그인 폼만 그리고 **여기서 끝냅니다.** 아래로 내려가는 코드는
        # 전부 "이 접속자 본인의" 데이터만 다룹니다 (계획서 §6-2).
        if not has_supabase_session():
            _render_auth()
            return

        try:
            client = get_client()
        except Exception as exc:                   # noqa: BLE001
            error_banner(f'🚫 {_fail(exc, "로그인 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
            return
        if client is None:
            _render_not_ready(supabase_status())
            return

        # "지금 누가 로그인했는지"는 **이 접속 전용 클라이언트에게 직접 물어봅니다.**
        # 저장소에 캐시해둔 이메일/사용자 id 를 믿지 않는 이유: 저장된 값과 실제 토큰이
        # 어긋나면 남의 데이터를 본인 것으로 착각해 그릴 수 있기 때문입니다(§0-3-8).
        user = current_user(client)
        user_id = user_id_of(user)
        if not user_id:
            logout()                                # 끊어진 세션을 남겨두지 않습니다
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            _render_auth()
            return

        email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        try:
            _render_body(client, user_id, email)
        except Exception as exc:                   # noqa: BLE001 — 트레이스백을 화면에 흘리지 않습니다
            error_banner(f'🚫 {_fail(exc, "화면을 그리는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.")}')


def _render_header() -> None:
    ui.markdown('## 📊 내 성적표')
    info_banner('🔒 입력한 데이터는 Supabase 에 저장되며, 본인만 조회할 수 있도록 DB 정책(RLS)이 걸려 있습니다.')
    info_banner(NO_FX_CONVERSION_NOTICE)
    info_banner(NO_FEES_TAXES_NOTICE)


def _render_not_ready(status) -> None:
    """Supabase 가 준비되지 않은 상태 안내 (에러가 아니라 '준비중'입니다)."""
    warning_banner(
        '🚧 내 성적표는 아직 준비중입니다.\n\n'
        f'사유: {status.reason}\n\n'
        '이 화면이 준비되지 않아도 기존 밸류에이션 리포트(한국/미국)는 정상 동작합니다.'
    )
    with ui.expansion('🔧 오너 설정 체크리스트 (관리자용)').classes('w-full'):
        ui.markdown(
            '1. Supabase 프로젝트 생성 (무료 티어)\n'
            '2. Supabase → SQL Editor 에서 `sql/scorecard_schema.sql` 전체 실행\n'
            '   → `profiles` / `holdings` 테이블 + **RLS 정책 8개** 생성 확인\n'
            '3. Supabase → Authentication → Providers → **Email** 활성화\n'
            '4. Render → 서비스 → **Environment** 에 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 등록\n'
            '   → `service_role` 키는 **절대 넣지 마세요** (RLS를 통째로 우회합니다)\n'
            '5. `requirements.txt` 의 `supabase` 가 반영되도록 재배포\n'
            '6. Supabase → Authentication → Emails → **Reset Password** 본문에 `{{ .Token }}` 추가\n'
            '   (비밀번호 찾기용 재설정 코드. 이 한 줄이 없으면 사용자가 입력할 코드가 메일에 안 옵니다)'
        )


# =============================================================================
# 4. 로그인 / 회원가입 / 비밀번호 찾기
# =============================================================================
def _render_auth() -> None:
    """로그인 전 화면. 이 함수 안에서는 사용자 데이터를 읽거나 쓰지 않습니다."""
    ui.markdown('#### 🔐 로그인')
    ui.label('비밀번호는 Supabase Auth 가 관리합니다 — 이 앱은 비밀번호를 저장하지도, 볼 수도 없습니다.') \
        .classes('vh-muted')

    with ui.tabs().classes('w-full') as tabs:
        tab_login = ui.tab('로그인')
        tab_signup = ui.tab('회원가입')
        tab_reset = ui.tab('비밀번호 찾기')
    with ui.tab_panels(tabs, value=tab_login).classes('w-full'):
        with ui.tab_panel(tab_login):
            _render_login_form()
        with ui.tab_panel(tab_signup):
            _render_signup_form()
        with ui.tab_panel(tab_reset):
            _render_reset_form()


def _render_login_form() -> None:
    message = ui.label('').classes('text-red-400')

    def _submit() -> None:
        message.text = ''
        try:
            user = login(email_input.value or '', password_input.value or '')
        except Exception as exc:                   # noqa: BLE001
            message.text = f'🚫 {_fail(exc, "로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.")}'
            return
        if user is None:
            message.text = '🚫 로그인에 실패했습니다(사용자 정보를 받지 못했습니다).'
            return
        # 비밀번호가 브라우저 메모리에 남지 않도록 비우고, 같은 주소를 다시 그립니다.
        # ⚠️ 이동 주소는 우리가 정한 고정 경로뿐입니다 — 사용자가 준 URL 로 보내지 않습니다
        #    (§0-3-9 오픈 리다이렉트 방지).
        password_input.value = ''
        ui.navigate.reload()

    email_input = ui.input('이메일').classes('w-full max-w-sm').on('keydown.enter', _submit)
    password_input = ui.input('비밀번호', password=True, password_toggle_button=True) \
        .classes('w-full max-w-sm').on('keydown.enter', _submit)
    ui.button('로그인', on_click=_submit)
    ui.label(
        '🔑 비밀번호를 잊으셨나요? 새 계정을 만들지 마시고 위 "비밀번호 찾기" 탭에서 '
        '이메일로 코드를 받아 새 비밀번호를 정하세요 — 기존에 입력한 보유 종목이 그대로 남습니다.'
    ).classes('vh-muted')


def _render_signup_form() -> None:
    info_banner(
        '가입 시 참고 — 1년 이상 접속하지 않은 계정의 데이터는 나중에 정리될 수 있습니다. '
        '(v1은 안내만 하고 자동 삭제 기능은 아직 없습니다.)'
    )
    message = ui.label('').classes('text-red-400')

    def _submit() -> None:
        message.text = ''
        if (password_input.value or '') != (confirm_input.value or ''):
            message.text = '🚫 비밀번호가 서로 다릅니다.'
            return
        try:
            client = get_client()
            if client is None:
                message.text = '🚫 Supabase 연결이 준비되지 않아 가입할 수 없습니다.'
                return
            sign_up(client, (email_input.value or '').strip(), password_input.value or '')
        except Exception as exc:                   # noqa: BLE001
            message.text = f'🚫 {_fail(exc, "가입 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")}'
            return
        message.text = ''
        password_input.value = ''
        confirm_input.value = ''
        ui.notify(
            '✅ 가입 요청이 접수되었습니다. 이메일 인증이 켜져 있으면 받은 메일함을 확인한 뒤 '
            '로그인 탭에서 로그인해 주세요.',
            type='positive', multi_line=True, close_button='닫기',
        )

    email_input = ui.input('이메일').classes('w-full max-w-sm')
    password_input = ui.input('비밀번호', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.label('8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.').classes('vh-muted')
    confirm_input = ui.input('비밀번호 확인', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.button('회원가입', on_click=_submit)


def _render_reset_form() -> None:
    """비밀번호 재설정 (메일로 받은 **코드** 입력 방식 — #109/#110 에서 검증된 그 방식 그대로).

    ⚠️ 이 폼 어디에서도 로그인 세션을 건드리지 않습니다. 코드 검증은 `new_auth_client()` 로
       만든 1회용 클라이언트에서만 일어나고, 끝나면 그 세션은 로그아웃됩니다(§0-3-8).
    """
    ui.label(
        '가입한 이메일로 재설정 코드를 보내드립니다. 메일에 적힌 숫자를 아래 2단계에 그대로 '
        '입력하면 새 비밀번호를 정할 수 있습니다.'
    ).classes('vh-muted')

    message = ui.label('').classes('text-red-400')

    ui.markdown('**1단계 · 재설정 코드 받기**')

    def _send_code() -> None:
        message.text = ''
        address = (request_email.value or '').strip()
        try:
            client = get_client()
            if client is None:
                message.text = '🚫 Supabase 연결이 준비되지 않아 코드를 보낼 수 없습니다.'
                return
            # 발송 요청은 로그인 세션을 만들지 않으므로 이 접속의 클라이언트로 보내도 안전합니다.
            notice = send_password_reset_code(client, address)
        except Exception as exc:                   # noqa: BLE001
            message.text = f'🚫 {_fail(exc, "재설정 코드를 보내지 못했습니다. 잠시 후 다시 시도해 주세요.")}'
            return
        # ⚠️ 가입된 이메일인지 여부는 알려주지 않습니다(계정 존재 여부 유출 방지, §0-3-9).
        confirm_email.value = address
        ui.notify(f'✅ {notice}', type='positive', multi_line=True, close_button='닫기')

    request_email = ui.input('가입한 이메일').classes('w-full max-w-sm')
    ui.button('재설정 코드 보내기', on_click=_send_code)

    ui.markdown('**2단계 · 받은 코드로 새 비밀번호 정하기**')

    def _confirm() -> None:
        message.text = ''
        try:
            reset_password_with_code(
                new_auth_client(),
                (confirm_email.value or '').strip(),
                code_input.value or '',
                new_pw.value or '',
                new_pw2.value or '',
            )
        except Exception as exc:                   # noqa: BLE001
            message.text = f'🚫 {_fail(exc, "비밀번호를 변경하지 못했습니다. 잠시 후 다시 시도해 주세요.")}'
            return
        code_input.value = ''
        new_pw.value = ''
        new_pw2.value = ''
        ui.notify(
            '✅ 비밀번호를 변경했습니다. 위 "로그인" 탭에서 새 비밀번호로 로그인해 주세요.',
            type='positive', multi_line=True, close_button='닫기',
        )

    confirm_email = ui.input('가입한 이메일').classes('w-full max-w-sm')
    code_input = ui.input('이메일로 받은 코드') \
        .classes('w-full max-w-sm') \
        .tooltip('메일 본문에 적힌 숫자 코드를 그대로 입력하세요. 링크를 누를 필요는 없습니다.')
    new_pw = ui.input('새 비밀번호', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.label('8자 이상을 권장합니다. Supabase Auth 의 정책이 그대로 적용됩니다.').classes('vh-muted')
    new_pw2 = ui.input('새 비밀번호 확인', password=True, password_toggle_button=True).classes('w-full max-w-sm')
    ui.button('비밀번호 변경', on_click=_confirm)


# =============================================================================
# 5. 로그인 후 본문
# =============================================================================
def _render_body(client, user_id: str, email) -> None:
    """로그인 후 화면 전체.

    ⚠️ `client` 와 `user_id` 는 **반드시 인자로 받습니다.** 이 아래 어떤 함수도 "지금 누가
       로그인했는지"를 전역이나 저장소에서 다시 추측하지 않습니다 (§0-3-8 함수 설계 원칙).
    """
    def _logout_click() -> None:
        logout()
        ui.navigate.reload()

    # 로그인 정보 + 로그아웃 — #127~#130 의 그 "항상 한 줄" 패턴 (no-wrap flex).
    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.label(f'로그인: {email or user_id}').classes('flex-1 min-w-0 truncate vh-muted')
        ui.button('로그아웃', on_click=_logout_click).props('flat dense no-caps').classes('shrink-0')

    market = _load_market_data()                   # 읽기 전용 시세 (사용자 데이터 아님)
    indexes = market["indexes"]
    if not indexes[MARKET_KR] and not indexes[MARKET_US]:
        error_banner(
            '🚫 밸류에이션 스냅샷(data/*.json)을 읽지 못했습니다. 현재가·수익률을 계산할 수 없습니다.'
        )

    # 보유종목 목록은 **이 refreshable 안에서 매번 새로 조회**합니다. 추가/수정/삭제 후
    # `.refresh()` 만 부르면 이 블록만 다시 그려집니다(전체 페이지 리렌더 없음 — 계획서 §3-3).
    @ui.refreshable
    def portfolio_section() -> None:
        _render_portfolio(client, user_id, market, portfolio_section.refresh)

    _render_input_form(client, user_id, market, portfolio_section.refresh)
    ui.separator()
    portfolio_section()


def _render_portfolio(client, user_id: str, market: dict, on_changed) -> None:
    try:
        holdings = fetch_holdings(client, user_id)
    except Exception as exc:                       # noqa: BLE001
        error_banner(f'🚫 {_fail(exc, "보유 종목을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
        return

    if not holdings:
        info_banner('아직 등록한 보유 종목이 없습니다. 위 입력창에서 추가해 주세요.')
        return

    portfolio = build_portfolio(
        holdings,
        make_price_lookup(
            market["indexes"],
            broad_kr_prices=market["kr_all_prices"],
            broad_us_prices=market["us_all_prices"],
        ),
    )
    for currency in ("KRW", "USD"):
        group = portfolio.get(currency)
        if group and group["rows"]:
            _render_currency_block(client, user_id, group, market, on_changed)
            ui.separator()


# =============================================================================
# 6. 보유 종목 입력
# =============================================================================
def _candidate_options(market_code: str, market: dict) -> dict:
    """빠른 검색 후보 {티커: "티커 · 종목명"}.

    후보는 §0-1 대로 **실제 상장종목 목록에서만** 뽑습니다. 한국은 상위 200 유니버스 +
    전체 상장종목 마스터(코스피·코스닥·ETF), 미국은 상위 550 유니버스입니다.
    라벨에 티커를 앞세우는 이유(2026-08-13 오너 지적): 종목명만 넣으면 "XOM" 같은 티커 검색이
    이름의 철자 순서에 우연히 걸리는 종목들까지 잡아버립니다.
    """
    options = {}
    for ticker, stock in (market["indexes"].get(market_code) or {}).items():
        name = stock.get("name")
        if name:
            options[ticker] = f"{ticker} · {name}"
    if market_code == MARKET_KR:
        for code, stock in (market["kr_master"] or {}).items():
            name = stock.get("name")
            if name:
                options.setdefault(code, f"{code} · {name}")
    return dict(sorted(options.items(), key=lambda kv: kv[1]))


def _render_input_form(client, user_id: str, market: dict, on_changed) -> None:
    ui.markdown('#### ✍️ 보유 종목 입력')
    ui.label(
        '같은 종목을 여러 번 입력하면(증권사 계좌가 여러 개인 경우) 삭제·덮어쓰기가 아니라 '
        '수량 가중평균으로 매입가가 다시 계산됩니다. 예) 10주 100,000원 + 3주 70,000원 → 13주 평균 93,076원'
    ).classes('vh-muted')

    # ⚠️ 이 dict 는 **페이지 함수 호출마다 새로 만들어지는 지역 상태**입니다(접속마다 별개).
    #    모듈 전역에 두면 접속자끼리 입력값이 섞입니다(§0-3-8).
    form = {'market': MARKET_KR}
    message = ui.label('').classes('text-red-400')

    def _on_market(event) -> None:
        form['market'] = event.value
        picker_block.refresh()

    ui.toggle({MARKET_KR: MARKET_LABELS[MARKET_KR], MARKET_US: MARKET_LABELS[MARKET_US]},
              value=MARKET_KR, on_change=_on_market) \
        .props('no-caps') \
        .tooltip('통화는 시장에서 자동으로 정해집니다(한국=원, 미국=달러). 환율 변환은 하지 않습니다.')

    @ui.refreshable
    def picker_block() -> None:
        options = _candidate_options(form['market'], market)
        scope = ('코스피·코스닥·국내ETF 전체' if form['market'] == MARKET_KR and market["kr_master"]
                 else '상위 200/550 종목만')

        def _picked(event) -> None:
            if event.value:
                query_input.value = event.value

        ui.select(options, with_input=True, clearable=True, on_change=_picked,
                  label=f'🔍 종목 빠른 검색 ({scope} — 그 밖은 아래 칸에 코드를 직접 입력)') \
            .classes('w-full')

    picker_block()

    # ⚠️ 오너 지시: "종목코드 / 티커 / 종목명 이게 전부 다 한곳에서 기능할 수 있게" —
    #    코드를 쳐도, 이름을 쳐도(한글 포함) 한 칸에서 알아서 찾습니다. 유니버스 밖 종목은
    #    코드를 알면 그대로 받아들여 "현재가 없음"으로 정직하게 표시합니다.
    query_input = ui.input(
        '종목 (종목코드 / 티커 / 종목명 — 아무거나 입력하세요)',
        placeholder='예: 005930 / 삼성전자 / NVDA',
    ).classes('w-full') \
        .tooltip('종목코드를 아시면 코드로, 모르시면 이름으로 입력하세요 — 둘 다 자동으로 찾아드립니다.')

    with ui.row().classes('w-full gap-4 items-start'):
        qty_input = ui.input('수량', placeholder='예: 10').style('flex: 1 1 160px;')
        price_input = ui.input('매입가 (1주당)', placeholder='예: 70,000').style('flex: 1 1 160px;') \
            .tooltip('총 매입금액이 아니라 1주당 매입 단가입니다. 콤마(,)를 넣어 입력해도 됩니다.')

    def _submit() -> None:
        message.text = ''
        market_code = form['market']
        resolved_ticker, resolved_name, resolve_error = resolve_stock_query(
            market_code, query_input.value or '', market["indexes"],
            broad_index=market["kr_master"] if market_code == MARKET_KR else None,
        )
        if not resolved_ticker:
            message.text = f'🚫 {resolve_error}'
            return
        try:
            quantity = _parse_positive_number(qty_input.value, '수량')
            price = _parse_positive_number(price_input.value, '매입가')
        except ValueError as exc:
            message.text = f'🚫 {exc}'
            return

        try:
            # holdings 를 넘기지 않으면 add_lot 이 **그 자리에서 다시 조회**합니다 —
            # 화면에 오래 떠 있던 목록을 근거로 평균단가를 계산하는 사고를 막습니다.
            action, merged = add_lot(
                client, user_id, market_code, resolved_ticker, quantity, price,
                stock_name=resolved_name,
            )
        except Exception as exc:                   # noqa: BLE001
            message.text = f'🚫 저장하지 못했습니다: {_fail(exc, "잠시 후 다시 시도해 주세요.")}'
            return

        currency = merged["currency"]
        prefix = f'ℹ️ {resolved_name} ({resolved_ticker}) 로 인식했습니다.\n' if resolved_name else ''
        if action == 'merge':
            text = (f'{prefix}✅ 기존 보유분과 합쳐 평균단가를 다시 계산했습니다 — '
                    f'{merged["ticker"]} {merged["quantity"]:,.6g}주 / '
                    f'평균 {format_amount(merged["avg_purchase_price"], currency)}')
        else:
            text = f'{prefix}✅ {merged["ticker"]} 을(를) 추가했습니다.'

        # 입력창 비우기 — NiceGUI 는 값을 대입하면 그대로 브라우저까지 반영됩니다
        # (Streamlit 의 위젯 키 함정(#85)이 구조적으로 없습니다 — 계획서 §3-3).
        query_input.value = ''
        qty_input.value = ''
        price_input.value = ''
        ui.notify(text, type='positive', multi_line=True, close_button='닫기')
        on_changed()

    ui.button('➕ 추가 / 평균단가 재계산', on_click=_submit).props('no-caps')


# =============================================================================
# 7. 통화별 블록 (표 · 종목 관리 · 차트 · 밸류에이션)
# =============================================================================
def _render_currency_block(client, user_id: str, group: dict, market: dict, on_changed) -> None:
    currency = group["currency"]
    indexes = market["indexes"]
    rows_all = group["rows"]
    sync_label = market["sync_labels"].get(currency)

    with ui.row().classes('no-wrap items-center gap-2 w-full'):
        ui.markdown(f'### {CURRENCY_TITLES.get(currency, currency)}').classes('flex-1 min-w-0')
        if sync_label:
            # sync_label 은 사용자 입력이 아니라 우리 수집기가 쓴 메타데이터에서만 옵니다.
            # 그래도 esc() 는 습관적으로 걸어 둡니다 (§0-3-9).
            ui.html(
                f'<div style="font-size:0.9rem; font-weight:600; color:#cbd5e1;">'
                f'🕒 {esc(sync_label)} — 실시간 시세가 아닙니다.</div>'
            ).classes('shrink-0')

    with ui.row().classes('w-full gap-4 items-stretch'):
        metric_card('매입원가 합계', format_amount(group["total_cost"], currency))
        if group["total_value"] is not None:
            base = group["total_cost_priced"]
            profit = group["total_profit"]
            metric_card('평가금액 합계', format_amount(group["total_value"], currency))
            metric_card('평가손익', format_amount(profit, currency),
                        _pct_text(profit / base * 100 if base else None))
        else:
            metric_card('평가금액 합계', '—')
            metric_card('평가손익', '—')

    if group["unpriced_count"]:
        info_banner(
            f'ℹ️ {group["unpriced_count"]}개 종목은 현재가를 알 수 없어(유니버스 밖 또는 수집 실패) '
            f'평가금액·비중 계산에서 빠졌습니다: {", ".join(group["unpriced_tickers"])}. '
            'v1은 상위 200(한국)/550(미국) 밖 종목의 시세를 조회하지 않습니다 — 추정하지 않고 비웁니다.'
        )

    # 정렬 · 편집 상태는 이 블록의 **지역 상태**입니다 (접속마다·통화마다 별개).
    view = {'sort': _SORT_NONE, 'ascending': False, 'editing': None}

    def _sorted_rows():
        if view['sort'] == _SORT_NONE:
            return rows_all
        field = dict(SORT_FIELD_OPTIONS)[view['sort']]
        return sort_holding_rows(rows_all, field, ascending=view['ascending'])

    with ui.row().classes('w-full gap-4 items-center'):
        def _on_sort(event) -> None:
            view['sort'] = event.value
            rows_section.refresh()

        def _on_dir(event) -> None:
            view['ascending'] = (event.value == '오름차순')
            rows_section.refresh()

        ui.select([_SORT_NONE] + [label for label, _ in SORT_FIELD_OPTIONS],
                  value=_SORT_NONE, label='정렬 기준', on_change=_on_sort).style('flex: 1 1 200px;')
        ui.toggle(['내림차순', '오름차순'], value='내림차순', on_change=_on_dir).props('no-caps')

    @ui.refreshable
    def rows_section() -> None:
        rows = _sorted_rows()
        _render_table(rows, indexes, currency)
        _render_row_manager(client, user_id, rows, indexes, view, rows_section.refresh, on_changed)

    rows_section()

    ui.separator()
    _render_charts(rows_all, indexes, currency)
    _render_valuation_picker(rows_all, indexes, currency)


def _render_table(rows, indexes, currency: str) -> None:
    """보유 종목 표.

    #127 의 결론 그대로 **순수 HTML `<table>` + `overflow-x: auto`** 입니다. 화면이 좁아지면
    세로로 쌓이지 않고 가로 스크롤될 뿐이라, 모바일에서도 표 구조가 그대로 유지됩니다.
    (Streamlit 의 `st.columns()` 반응형 쌓기 자체가 없어졌으므로 여기서 다시 깨질 여지가 없습니다.)
    """
    headers = ['종목', '수량', '평균매입가', '현재가', '평가손익', '수익률', '비중']
    head_html = ''.join(f'<th>{esc(h)}</th>' for h in headers)

    body_rows = []
    for row in rows:
        cells = [
            _row_label_html(row, indexes),
            esc(f'{row["quantity"]:,.6g}'),
            esc(format_amount(row["avg_purchase_price"], currency)),
            esc(format_amount(row["current_price"], currency) if row["price_available"] else '현재가 없음'),
            esc(format_amount(row["profit"], currency) if row["price_available"] else '—'),
            _pct_html(row.get("profit_pct")),
            esc(f'{row["weight_pct"]:.1f}%' if row.get("weight_pct") is not None else '—'),
        ]
        body_rows.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')

    ui.html(compact(f"""
        <div style="overflow-x: auto; -webkit-overflow-scrolling: touch; width: 100%;">
          <table class="vh-holdings-table">
            <thead><tr>{head_html}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        </div>
    """)).classes('w-full')


def _render_row_manager(client, user_id: str, rows, indexes, view: dict, redraw, on_changed) -> None:
    """"종목 관리" 줄 (종목명 + ✏️ + 🗑️).

    🔴 #127~#130 에서 여섯 번 싸운 바로 그 레이아웃입니다. Streamlit 에서는 `st.columns()` 가
       JS 로 인라인 style 을 박아넣어 CSS 로 이길 수 없었지만(공식 이슈 #6592), NiceGUI 의
       `ui.row()` 는 평범한 flex 컨테이너라 `no-wrap` 한 줄이면 끝입니다.
       **이 세 클래스를 지우지 마세요**: 줄 전체 `no-wrap`, 라벨 `flex-1 min-w-0`, 버튼 `shrink-0`.
    """
    ui.markdown('**종목 관리**')
    for row in rows:
        row_id = row.get("id")
        with ui.row().classes('no-wrap items-center gap-2 w-full vh-card'):
            ui.html(_row_label_html(row, indexes)).classes('flex-1 min-w-0')
            ui.button(icon='edit', on_click=lambda _=None, rid=row_id: _toggle_edit(view, rid, redraw)) \
                .props('flat dense').classes('shrink-0').tooltip('수정')
            ui.button(icon='delete',
                      on_click=lambda _=None, r=row: _delete(client, user_id, r, indexes, on_changed)) \
                .props('flat dense').classes('shrink-0').tooltip('삭제')

        if view['editing'] == row_id and row_id:
            _render_edit_card(client, user_id, row, indexes, view, redraw, on_changed)


def _toggle_edit(view: dict, row_id, redraw) -> None:
    view['editing'] = None if view['editing'] == row_id else row_id
    redraw()


def _delete(client, user_id: str, row, indexes, on_changed) -> None:
    row_id = row.get("id")
    if not row_id:
        ui.notify('🚫 삭제할 행의 id 를 알 수 없습니다.', type='negative')
        return
    try:
        delete_holding(client, user_id, row_id)
    except Exception as exc:                       # noqa: BLE001
        ui.notify(f'🚫 {_fail(exc, "삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.")}',
                  type='negative', multi_line=True, close_button='닫기')
        return
    ui.notify(f'✅ {_row_label(row, indexes)} 삭제했습니다.', type='positive')
    on_changed()


def _render_edit_card(client, user_id: str, row, indexes, view: dict, redraw, on_changed) -> None:
    with ui.card().classes('vh-card w-full'):
        ui.label(
            f'✏️ {_row_label(row, indexes)} 수정 — 다른 계좌분과 합쳐 평균을 내는 게 아니라, '
            '값을 그대로 덮어씁니다(잘못 입력한 걸 바로잡을 때 사용).'
        ).classes('vh-muted')
        message = ui.label('').classes('text-red-400')

        with ui.row().classes('w-full gap-2 items-center'):
            qty_input = ui.input('수량', value=f'{row["quantity"]:g}').style('flex: 1 1 140px;')
            price_input = ui.input('매입가 (1주당)', value=f'{row["avg_purchase_price"]:g}') \
                .style('flex: 1 1 140px;')

        def _save() -> None:
            message.text = ''
            try:
                quantity = _parse_positive_number(qty_input.value, '수량')
                price = _parse_positive_number(price_input.value, '매입가')
            except ValueError as exc:
                message.text = f'🚫 {exc}'
                return
            try:
                update_holding(client, user_id, row.get("id"), quantity, price)
            except Exception as exc:               # noqa: BLE001
                message.text = f'🚫 {_fail(exc, "수정하지 못했습니다. 잠시 후 다시 시도해 주세요.")}'
                return
            view['editing'] = None
            ui.notify('✅ 수정했습니다.', type='positive')
            on_changed()

        def _cancel() -> None:
            view['editing'] = None
            redraw()

        with ui.row().classes('no-wrap gap-2'):
            ui.button('저장', on_click=_save).props('no-caps')
            ui.button('취소', on_click=_cancel).props('flat no-caps')


def _render_charts(rows, indexes, currency: str) -> None:
    """원형차트 2종 — figure 를 만드는 코드는 Streamlit 원본과 동일합니다 (계획서 §7)."""
    priced = [r for r in rows if r["price_available"]]
    gainers = [r for r in priced if r.get("profit") and r["profit"] > 0]

    with ui.row().classes('w-full gap-4 items-stretch'):
        with ui.column().style('flex: 1 1 320px; min-width: 0;'):
            ui.markdown('**보유 비중 (평가금액 기준)**')
            if not priced:
                ui.label('현재가를 아는 종목이 없어 비중 차트를 그릴 수 없습니다.').classes('vh-muted')
            else:
                _pie(
                    [_row_chart_label(r, indexes) for r in priced],
                    [r["market_value"] for r in priced],
                    fallback_header='비중(%)',
                    fallback_rows=[(_row_chart_label(r, indexes), f'{r["weight_pct"]:.2f}') for r in priced],
                )

        with ui.column().style('flex: 1 1 320px; min-width: 0;'):
            ui.markdown('**수익 비중 (이익이 난 종목만)**')
            if not gainers:
                ui.label('이익이 난 종목이 없어 수익 비중 차트를 그릴 수 없습니다.').classes('vh-muted')
            else:
                _pie(
                    [_row_chart_label(r, indexes) for r in gainers],
                    [r["profit"] for r in gainers],
                    fallback_header='수익비중(%)',
                    fallback_rows=[(_row_chart_label(r, indexes), f'{r["profit_share_pct"]:.2f}')
                                   for r in gainers],
                )

            losers = [r for r in priced if r.get("profit") is not None and r["profit"] <= 0]
            if losers:
                lines = '<br>'.join(
                    f'- {esc(_row_chart_label(r, indexes))} {esc(format_amount(r["profit"], currency))}'
                    for r in losers
                )
                ui.html(
                    '<div style="font-size:0.85rem; color:#94a3b8;">'
                    '⚠️ 손실 종목은 원형차트에 음수 조각으로 넣을 수 없어 제외했습니다:<br>'
                    f'{lines}</div>'
                ).classes('w-full')


def _pie(names, values, *, fallback_header: str, fallback_rows) -> None:
    """`px.pie(...)` — plotly 가 없으면 표로 대체합니다(원본과 동일 폴백).

    ⚠️ `.classes('w-full h-80')` 의 **높이(h-80)를 반드시 유지**하세요. NiceGUI 의 `ui.plotly`
       는 부모 높이를 상속하지 않아, 높이를 안 주면 0px 로 그려져 차트가 통째로 사라집니다
       (계획서 §7 — 첫 이식 때 흔한 실수라 완료기준에 포함돼 있습니다).
    """
    if not PLOTLY_AVAILABLE:                       # pragma: no cover - 배포 환경엔 항상 설치됨
        body = ''.join(
            f'<tr><td>{esc(name)}</td><td style="text-align:right;">{esc(value)}</td></tr>'
            for name, value in fallback_rows
        )
        ui.html(compact(f"""
            <table class="vh-holdings-table">
              <thead><tr><th>종목</th><th>{esc(fallback_header)}</th></tr></thead>
              <tbody>{body}</tbody>
            </table>
        """)).classes('w-full')
        return

    fig = px.pie(names=names, values=values, hole=0.35)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(**_CHART_LAYOUT)
    ui.plotly(fig).classes('w-full h-80')


def _render_valuation_picker(rows, indexes, currency: str) -> None:
    """"💡 사실 이 가격이에요" — 종목을 고르면 그 종목의 밸류에이션 카드를 보여줍니다."""
    ui.markdown('**💡 사실 이 가격이에요 — 밸류에이션 요약**')
    labels = {}
    for row in rows:
        labels[_row_label(row, indexes)] = row
    if not labels:
        return

    state = {'picked': next(iter(labels))}

    def _on_pick(event) -> None:
        if event.value:
            state['picked'] = event.value
            card.refresh()

    ui.select(list(labels.keys()), value=state['picked'], label='종목 선택', on_change=_on_pick) \
        .classes('w-full')

    @ui.refreshable
    def card() -> None:
        row = labels.get(state['picked'])
        if row is None:
            return
        summary = valuation_summary(row["market"], row["ticker"], indexes)
        if not summary.get("found"):
            info_banner(f'ℹ️ 밸류에이션 정보 없음 — {summary.get("reason")}')
            return
        if not summary.get("verified"):
            warning_banner(f'⚠️ 이 종목은 수집 검증을 통과하지 못했습니다 — {summary.get("reason")}')
            return

        score, score_max = summary.get("quant_score"), summary.get("score_max")
        with ui.row().classes('w-full gap-4 items-stretch'):
            metric_card('현재가', format_amount(summary.get("price"), currency))
            metric_card('Trailing PEGY',
                        f'{summary["t_pegy"]:.2f}' if summary.get("t_pegy") is not None else '—')
            metric_card('Forward PEGY',
                        f'{summary["f_pegy"]:.2f}' if summary.get("f_pegy") is not None else '—')
            metric_card('퀀트 점수',
                        f'{score} / {score_max}' if score is not None and score_max else '—')
        if summary.get("badge"):
            ui.html(f'<div><b>판정:</b> {esc(str(summary["badge"]))}</div>').classes('w-full')

        if summary.get("t_fair") is not None or summary.get("f_target") is not None:
            with ui.row().classes('w-full gap-4 items-stretch'):
                metric_card('Trailing 적정가',
                            format_amount(summary["t_fair"], currency)
                            if summary.get("t_fair") is not None else '—')
                metric_card('Forward 목표가',
                            format_amount(summary["f_target"], currency)
                            if summary.get("f_target") is not None else '—')

        # "내 평균매입가 vs 현재가" 배너 — 오너 지시대로 국내 관례(오르면 빨강/내리면 파랑).
        # ⚠️ Streamlit 에서는 마크다운(KaTeX)이 "$147.80 VS $159.80" 의 $ 두 개 사이를 수식으로
        #    오인해 `\$` 이스케이프가 필요했지만, 여기서는 마크다운을 거치지 않는 HTML 이라
        #    그 우회가 필요 없습니다(값은 동일).
        price = summary.get("price")
        avg_price = row.get("avg_purchase_price")
        if price is not None and avg_price:
            diff_pct = (price - avg_price) / avg_price * 100
            up = diff_pct >= 0
            (error_banner if up else info_banner)(
                f'{"📈" if up else "📉"} 내 평균매입가 {format_amount(avg_price, currency)} VS '
                f'현재가 {format_amount(price, currency)} ({diff_pct:+.2f}%)'
            )
        else:
            info_banner(
                f'내 평균매입가 {format_amount(avg_price, currency)} vs '
                f'현재가 {format_amount(price, currency)}'
            )
        ui.label('판단은 각자의 몫입니다(매수/매도 권유가 아닙니다).').classes('vh-muted')

        if summary.get("data_issues"):
            with ui.expansion('이 종목 수집 시 남은 경고').classes('w-full'):
                for issue in summary["data_issues"]:
                    ui.label(f'- {issue}')

    card()
