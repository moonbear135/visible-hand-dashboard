"""
📊 내 성적표 — 내 보유 종목 입력 + 손익/비중 + 밸류에이션 대조 (로그인 필요, URL `/scorecard`).

`views/scorecard_view.py`(Streamlit, 1,206줄)의 NiceGUI 이식본입니다 (이전 계획서 4단계).
컷오버(2026-08-17)가 끝나 **지금 사용자가 보는 화면은 이 파일**이고, Streamlit 쪽 원본은
즉시 롤백에 대비해 최소 2주간만 살려둡니다(듀얼런 — 계획서 §11-1 · §0-3-10).

🔴 이 화면은 이 프로젝트에서 **유일하게 사용자의 실제 자산 정보를 다루는 화면**입니다.
   ENGINEERING_SPEC.md §0-3-8(최상위 금지사항)을 먼저 읽고 고치세요. 요약하면:

   1. **사용자 데이터는 모듈 전역에 두지 않습니다.** 이 파일의 모듈 최상위에는 상수(문자열/
      숫자/읽기전용 튜플)만 있습니다. 보유종목·클라이언트·사용자 id 는 전부 `@ui.page` 함수
      안의 지역 변수이거나, 함수 인자로 명시적으로 전달됩니다.
   2. **"지금 누가 로그인했는지"를 암묵적으로 추측하지 않습니다.** DB를 만지는 모든 함수는
      `client`(그 접속 전용 Supabase 클라이언트)와 `user_id`를 **인자로 받아야만** 동작합니다
      (§0-3-8 "함수 설계 원칙", `web/auth.py` 참고).
   3. 이 규칙이 지켜지는지 `tests/test_web_session_isolation.py` 가 자동으로 검사합니다.
      그 테스트 통과가 §0-3-6 공개 승인의 조건이었고, **2026-08-17 공개 전환 완료** 이후에도
      이 테스트는 계속 회귀 방어선으로 남습니다(실패하면 즉시 원인을 찾아야 합니다).

✅ **공개 전환 완료 (2026-08-17)** — 드로어 메뉴에 모든 방문자에게 보입니다
   (`web/layout.py` 의 `_MENU` 에서 `admin_only=False`). 공개된 것은 "메뉴 노출"까지이고,
   **데이터는 여전히 로그인한 본인 것만** 보입니다(§0-3-8 — 공개[공유]와 노출[사고]은
   완전히 다릅니다). 로그인 없이 들어오면 로그인 폼만 그리고 숫자를 한 개도 그리지 않습니다.

이식 방침 (2·3단계와 동일)
   - **계산·DB 계층(`utils/scorecard_db.py`)은 한 줄도 건드리지 않습니다.** 이 파일은 순수
     표현 계층입니다 — 손익/가중평균/비중 계산식을 여기에 새로 넣지 마세요.
   - 사용자 입력·DB 값이 HTML 로 나가는 곳은 전부 `esc()` 를 거칩니다 (§0-3-9 XSS).
   - "종목 관리" 줄(종목명 + ✏️ + 🗑️)은 #127~#130 에서 여섯 번 싸운 그 레이아웃입니다.
     `st.columns()` 가 사라졌으므로 `ui.row().classes('no-wrap ...')` 하나로 항상 한 줄입니다
     (0단계 데모 화면에서 실기기로 검증했던 "패턴 A" 와 동일한 방식. 그 데모 페이지
      `web/pages/demo_page.py` 는 역할이 끝나 2026-08-17 에 삭제됐습니다).
   - 비밀번호 찾기는 **지금 잘 동작하는 코드(OTP) 방식을 그대로** 유지합니다 (계획서 §6-3 주의 4).
   - 🔐 **로그인 전 화면(로그인/회원가입/비밀번호 찾기 3탭)은 이 파일에 없습니다** — 2026-08-17
     5단계에서 '사장님 보고서'(/report)가 **같은 로그인 세션·같은 폼**을 쓰게 되면서
     `web/auth_ui.py` 로 옮겼습니다. 옮기는 과정에서 동작·문구는 바꾸지 않았습니다(§0-3-10).

오너 확정 사항(그대로 유지)
   - **환율 변환 없음** — 원화/달러를 절대 합치지 않고 통화별로 따로 계산·표시합니다.
   - 현재가는 기존 수집 스냅샷의 실측값만 씁니다. 유니버스 밖은 "현재가 없음"으로 정직하게
     표시하고 평가금액·수익률을 계산하지 않습니다 (§0-1).
"""

import os

from nicegui import run, ui

from utils.company_names_kr import resolve_korean_name
from utils.scorecard_db import (
    DAILY_OCR_UPLOAD_LIMIT,
    KR_ALL_MARKET_PRICES_FILENAME,
    KR_TICKER_MASTER_FILENAME,
    MARKET_KR,
    MARKET_LABELS,
    MARKET_US,
    NO_FEES_TAXES_NOTICE,
    NO_FX_CONVERSION_NOTICE,
    SNAPSHOT_FILENAMES,
    SORT_FIELD_OPTIONS,
    ScorecardError,
    US_ALL_ETF_PRICES_FILENAME,
    US_ALL_MARKET_PRICES_FILENAME,
    add_lot,
    build_portfolio,
    build_universe_index,
    consume_ocr_quota,
    current_user,
    delete_holding,
    fetch_holdings,
    format_amount,
    make_price_lookup,
    resolve_stock_query,
    sort_holding_rows,
    supabase_status,
    update_holding,
    user_id_of,
    valuation_summary,
)
# 📊 v2(2026-08-17) — 스크린샷 OCR 프리필. 화면은 이 함수 하나만 알면 됩니다 — 실제 외부
# AI provider가 나중에 바뀌어도 이 import 한 줄 말고는 아무것도 안 바뀝니다. 이 파일에는
# provider 회사 이름이 등장하지 않습니다(ENGINEERING_SPEC.md §0-3-11 — 어느 provider인지는
# utils/scorecard_ocr.py 안에서만 갈립니다. `SCORECARD_V2_OCR_WORK_ORDER.md` 참고).
from utils.scorecard_ocr import (
    OcrError,
    ensure_supported_image_format,
    extract_holdings_from_image,
)

from web.auth import get_client, has_supabase_session, logout
# 🔐 로그인/회원가입/비밀번호 찾기 폼은 '사장님 보고서'(/report)와 **완전히 같은 화면**이라
#    `web/auth_ui.py` 한 곳에 두고 두 화면이 같이 씁니다 (§0-3-10 중복 금지).
#    2026-08-17(5단계) 이전까지는 이 파일 안에 있던 코드이며, 옮기면서 동작은 바꾸지 않았습니다.
from web.auth_ui import fail_message, render_auth
from web.components import (
    chart_layout, compact, error_banner, esc, holdings_table_html, info_banner,
    metric_card, pct_html, pct_text, warning_banner,
)
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

# 2026-08-17 — "성적표 v2" 스크린샷 OCR 프리필 기능의 스테이징 플래그
# (ENGINEERING_SPEC.md §0-3-6 "신규 기능은 스테이징 후 오너 승인 전까지 기본 숨김",
# SCORECARD_V2_OCR_WORK_ORDER.md). 기본값은 항상 꺼짐(False) — 값이 정확히 "true"(대소문자
# 무관)일 때만 켜집니다. 이렇게 하지 않고 "값이 있으면 켜짐"으로 판정하면, 환경변수를
# 실수로 빈 문자열 아닌 아무 값으로만 채워도 켜지는 사고가 날 수 있습니다.
# ⚠️ `web/auth.py::get_admin_password_hash()` 와 같은 자리(화면/모듈이 직접 쓰는 곳에서
# `os.environ` 을 읽는 것)의 기존 관례를 그대로 따릅니다 — 이 프로젝트에는 별도의 "설정
# 레지스트리" 모듈이 없고(§0-3-10 YAGNI), `utils/constants.py` 는 순수 상수(문자열/숫자/
# 사전)만 담아 왔으므로 환경변수를 읽는 코드를 거기로 옮기지 않습니다.
SCORECARD_OCR_ENABLED = (os.environ.get("SCORECARD_OCR_ENABLED") or "").strip().lower() == "true"

# 스크린샷 업로드 허용 최대 크기. **브라우저 검사와 서버 검사가 같은 값을 쓰도록** 상수를
# 하나만 둡니다(§0-3-10). `ui.upload(max_file_size=...)` 는 Quasar(브라우저) 쪽 검사라
# 업로드 주소로 직접 POST 하면 그대로 지나가므로, 서버에서 한 번 더 확인해야 실제 방어가
# 됩니다(§0-3-9 — 이미 널리 알려진 대용량 업로드 남용). 폰 스크린샷은 보통 1~5MB입니다.
MAX_OCR_IMAGE_BYTES = 15 * 1024 * 1024

# 정렬 드롭다운의 "정렬하지 않음" 항목 (추가한 순서 그대로)
_SORT_NONE = "기본순서"

# 원형차트 조각 색 — plotly 기본 팔레트(`plotly.colors.qualitative.Plotly`)와 **같은 값**을
# 우리가 직접 들고 있습니다. 튜플(불변)이라 화면마다 값이 섞일 수 없습니다(§0-3-8).
#
# 🔴 2026-08-17 (실기기 확인) 왜 굳이 색을 적어두는가 —
#    Streamlit 의 `st.plotly_chart()` 는 넘겨받은 figure 에 **Streamlit 자체 테마를 다시
#    입혀서** 그립니다(기본값 theme="streamlit"). 그래서 원본 화면에서는 figure 에 조각 색을
#    한 번도 지정한 적이 없는데도 항상 알록달록하게 보였습니다.
#    NiceGUI 의 `ui.plotly()` 에는 그런 재테마링이 없어서, 조각 색이 오로지
#    `layout.template.layout.colorway` 가 파이썬 → JSON → 브라우저 plotly.js 까지
#    살아서 도착하는지에 달리게 됩니다. 그게 비면 조각에 색이 안 깔리고, 우리는 배경을
#    투명(`paper_bgcolor`/`plot_bgcolor` = rgba(0,0,0,0))으로 뚫어놨기 때문에 그 자리에
#    페이지의 검은 배경(#0e1117)이 그대로 비쳐 **"검은 도넛"** 으로 보입니다
#    (라벨은 흰색이라 정상적으로 보이고요 — 오너가 본 화면이 정확히 이 모습입니다).
#    → 템플릿 전달에 기대지 않고 **조각 색을 파이썬에서 못 박습니다.**
_SLICE_COLORS = (
    "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
    "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
)

# 차트 배경/글자색 — 이 화면은 다크 모드 고정(web/layout.py)이라 plotly 기본 흰 배경을 쓰면
# 차트만 하얗게 뜹니다. **figure 의 데이터(names/values)는 원본과 한 글자도 다르지 않고**,
# 배경 투명화와 글자색·조각 색만 지정합니다 (계획서 §7).
#
# (2026-08-17) 배경·글자색 공통 부분은 `web/components/widgets.py::chart_layout()` 로
#  옮겼습니다 — 매크로 화면이 거의 같은 사전을 따로 들고 있어서(차이는 `piecolorway`/
#  `colorway` 뿐) 테마 색을 한쪽만 고치면 두 화면이 어긋나는 구조였습니다 (§0-3-10).
#  이 화면만의 값(여백·범례·조각 색)은 아래 `_pie()` 에서 인자로 넘깁니다.


def _chart_layout() -> dict:
    """이 화면의 원형차트 레이아웃 = 공통 다크 테마 + 이 화면 고유값."""
    return chart_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        showlegend=False,
        # 조각 색 안전망 ①. 아래 `_pie()` 에서 trace 에 직접 색을 넣는 게 본 수정이고,
        # 이건 혹시 그쪽이 무시되는 plotly 버전에서도 검은 도넛이 되지 않게 하는 이중 보험입니다.
        piecolorway=list(_SLICE_COLORS),
    )


# =============================================================================
# 1. 공통 표시 도우미 (전부 순수 함수 — 상태를 갖지 않습니다)
# =============================================================================
#  예외 → 한국어 문구 변환(`fail_message`)은 '사장님 보고서'와 같은 규칙이라
#  `web/auth_ui.py` 에 함께 두고 가져다 씁니다 (§0-3-10).
def _fail(exc, fallback: str) -> str:
    """이 화면 전용 축약 — 로그에 찍힐 화면 이름만 고정해서 넘깁니다."""
    return fail_message(exc, fallback, context='내 성적표')


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


#  수익률 색(오르면 빨강/내리면 파랑, 2026-08-11 오너 확정)은 '사장님 보고서'와 **같은 값**이라야
#  해서 `web/components/html.py::pct_html()` 한 곳에 두고 두 화면이 같이 씁니다 (§0-3-10).


# (2026-08-17) `pct_text()` 는 `web/components/html.py::pct_text()` 로 옮겼습니다 —
#  '사장님 보고서'가 거의 같은 함수를 따로 들고 있어서(자릿수 인자 유무만 달랐음)
#  한쪽만 서식이 바뀌면 두 화면의 숫자 표기가 어긋나는 구조였습니다 (§0-3-10).


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


def _ocr_value_text(value) -> str:
    """OCR(`utils/scorecard_ocr.py`)이 읽은 숫자를 입력창에 채울 텍스트로 바꿉니다.

    ⚠️ `None` 이면 빈 문자열을 돌려줍니다 — 값을 못 읽은 칸은 지어내지 않고 비워둬서
    사용자가 직접 채우게 합니다(§0-1). 정수면 소수점을 붙이지 않습니다(10.0 → "10").
    """
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


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

        # "지금 누가 로그인했는지"는 **이 접속 전용 클라이언트에게 직접 물어봅니다.**
        # 저장소에 캐시해둔 이메일/사용자 id 를 믿지 않는 이유: 저장된 값과 실제 토큰이
        # 어긋나면 남의 데이터를 본인 것으로 착각해 그릴 수 있기 때문입니다(§0-3-8).
        user = current_user(client)
        user_id = user_id_of(user)
        if not user_id:
            logout()                                # 끊어진 세션을 남겨두지 않습니다
            warning_banner('⚠️ 로그인 세션이 만료되었습니다. 다시 로그인해 주세요.')
            render_auth()
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

    # =========================================================================
    # 📊 v2(2026-08-17, 스테이징) — 스크린샷 OCR 프리필
    # SCORECARD_OCR_ENABLED 가 꺼져 있으면(기본값) 이 블록은 아예 그려지지 않습니다
    # (§0-3-6 신규 기능 기본 숨김). `query_input`/`qty_input`/`price_input` 은 아래에서
    # 정의되지만, 이 안의 클릭 핸들러는 **버튼을 실제로 누르는 시점**(항상 아래 정의가
    # 끝난 뒤)에만 실행되므로 파이썬 클로저 규칙상 문제가 없습니다.
    #
    # ⚠️ 여기서 하는 일은 **입력창 3칸에 값을 채우는 것뿐**입니다. 저장(Supabase
    # insert/merge)은 사용자가 채워진 값을 검토·수정한 뒤 아래 기존 "➕ 추가" 버튼을 직접
    # 눌러야만 일어납니다 — 종목 조회(`resolve_stock_query`)·가중평균 재계산(`add_lot`)도
    # 이미 있는 `_submit()` 경로를 그대로 타므로 새 로직을 만들지 않았습니다(§0-3-10).
    # =========================================================================
    if SCORECARD_OCR_ENABLED:
        ui.separator()
        ui.markdown('#### 📷 스크린샷으로 채우기 (베타)')
        # 상시 노출 경고 — 동의 체크박스 없이 업로드 버튼 바로 위에 항상 보입니다.
        warning_banner(
            '⚠️ 계좌번호·잔고 등 민감정보가 화면에 보이면 업로드 전에 폰 기본 마크업 기능'
            '(검은 펜)으로 가려주세요. 아이폰은 스크린샷 미리보기(왼쪽 아래 썸네일)를 누르면 '
            '펜 아이콘이, 안드로이드는 스크린샷 알림이나 갤러리의 편집(연필) 아이콘이 나옵니다. '
            '업로드한 원본 이미지는 종목명·수량·매입가를 읽어낸 직후 폐기하며, 우리 데이터베이스나 '
            '저장소에는 남기지 않습니다.'
        )
        # ⚠️ 문구를 "저장하지 않습니다"라고 단정하지 않는 이유(2026-08-17 검토, §0-1 — 사실이
        #    아닌 것을 사용자에게 약속하지 않기): NiceGUI 3.x 는 업로드가 멀티파트 스풀
        #    한계(기본 1MB)를 넘으면 프레임워크가 **먼저** OS 임시 파일에 받아쓰고, 그 임시
        #    파일은 FileUpload 객체가 회수될 때 지워집니다(nicegui/elements/upload_files.py 의
        #    LargeFileUpload + weakref.finalize). 즉 "우리가 저장하는" 곳은 없지만 "디스크에
        #    단 한 순간도 닿지 않는다"고까지는 말할 수 없습니다. 우리가 통제하는 범위
        #    (DB·스토리지·로그)에 대해서만 약속합니다.
        ui.label(
            '스크린샷에서 읽은 값은 아래 입력창에 채워지기만 합니다 — 자동 저장되지 않으니 '
            '반드시 확인·수정 후 "➕ 추가 / 평균단가 재계산" 버튼을 직접 눌러 주세요.'
        ).classes('vh-muted')
        # 한도를 **미리** 알려줍니다 — 다 쓴 뒤에야 알게 되면 그건 좋은 안내가 아닙니다.
        # 숫자는 항상 상수에서 옵니다(§0-3-10 — 화면에 10을 따로 적지 않습니다).
        ui.label(
            f'스크린샷 업로드는 하루 {DAILY_OCR_UPLOAD_LIMIT}회까지 가능합니다(매일 자정 초기화). '
            '아래 입력창에 직접 입력하는 건 횟수 제한이 없습니다.'
        ).classes('vh-muted')

        extracted_box = ui.column().classes('w-full gap-2')
        error_slot = ui.column().classes('w-full')
        quota_label = ui.label('').classes('vh-muted')

        def _set_quota_label(quota: dict) -> None:
            """남은 횟수 문구를 만드는 **유일한 자리**.

            성공했을 때와 실패했을 때가 각자 문장을 만들면 언젠가 둘이 어긋납니다
            (§0-3-10). 한도는 유료 호출 *전에* 차감되므로, 차감이 끝난 뒤라면 성공이든
            실패든 화면은 똑같이 줄어든 숫자를 보여줘야 사실과 맞습니다(§0-1).
            """
            quota_label.text = (
                f'오늘 남은 스크린샷 업로드 횟수: {quota["remaining"]}회 '
                f'(하루 {DAILY_OCR_UPLOAD_LIMIT}회)'
            )

        # 2026-08-17 버그 수정 (오너 실사용 중 발견·재현 — 스크린샷 3장 업로드 시 가운데
        # 장의 인식 결과가 사라짐) — 이 업로드 위젯은 한 번에 한 장만 고를 수 있지만
        # (NiceGUI `ui.upload` 의 `multiple` 기본값이 `False` 이고 아래에서 켜지 않습니다),
        # 사용자는 **한 장을 올린 뒤 이어서 다음 장을 올리는 식으로 연달아** 씁니다. 그러면
        # 장마다 `_on_ocr_upload` 가 **따로따로** 실행됩니다. 그런데 예전 코드는 매번
        # `extracted_box.clear()`로 화면을 통째로 지우고 "이번 장에서 나온 항목만" 다시
        # 그렸습니다 — 그래서 먼저 올린 장들의 인식 결과가 다음 장이 처리되는 순간 화면에서
        # 사라졌습니다. 원본 이미지는 여전히 장당 처리 직후 폐기하지만(§0-3-8), **인식된
        # 텍스트 결과**는 이 페이지를 보는 동안 계속 쌓여야 합니다. `extracted_items`는
        # `@ui.page` 함수의 지역 변수라 접속(세션)마다 따로 생기므로 §0-3-8 "모듈 전역 금지"
        # 규칙에 어긋나지 않습니다.
        #
        # ⚠️ 2026-08-18 주석 정정 — 위 원인 설명이 원래는 *"`ui.upload` 가 여러 장 동시
        #    선택을 허용해서"* 라고 적혀 있었지만, NiceGUI 3.16 `Upload.__init__` 확인 결과
        #    `multiple` 기본값은 `False` 라 사실이 아니었습니다. 고친 코드와 회귀 테스트는
        #    그대로 유효하고 바뀐 건 원인 설명뿐입니다 — 다음 세션이 "동시 선택"을 전제로
        #    엉뚱한 곳을 고치지 않도록 정정합니다(§0-1: 주석도 사실이어야 합니다).
        #
        # 이 김에 실패 배너 자리(`error_slot`)도 결과 목록(`extracted_box`)에서 분리했습니다.
        # 예전엔 "실패 배너가 계속 쌓이지 않게" 매번 지우던 자리가 하필 결과 목록과 같은
        # 상자여서, 그 지우기가 이번 버그의 또 다른 원인이기도 했습니다. 이제 "실패 배너는
        # 안 쌓이게 지우기"와 "성공한 결과는 안 지우고 쌓기"를 각자 다른 상자가 맡습니다.
        # 남은 횟수 표시(`quota_label`)도 장마다 새 라벨을 쌓지 않도록 하나만 두고 갱신합니다.
        extracted_items: list = []

        def _show_ocr_error(text: str) -> None:
            """실패 문구를 전용 자리(`error_slot`)에 그립니다.

            ⚠️ 2026-08-17 검토에서 고친 자리 — 예전에는 결과 목록(`extracted_box`)을 같이
            지웠는데, 그러면 이미 성공적으로 인식해둔 이전 장의 결과까지 실패 배너 하나 때문에
            날아갑니다. `error_slot`만 지우고 다시 그리므로 ① 배너가 계속 쌓이지 않고
            ② 이미 인식해둔 성공 결과는 그대로 남습니다.
            """
            error_slot.clear()
            with error_slot:
                error_banner(text)

        def _make_ocr_fill_handler(item: dict):
            def _click() -> None:
                query_input.value = item.get('raw_name') or ''
                qty_input.value = _ocr_value_text(item.get('quantity'))
                price_input.value = _ocr_value_text(item.get('avg_price'))
                ui.notify(
                    '입력창에 채웠습니다 — 확인·수정 후 "➕ 추가"를 눌러야 저장됩니다.',
                    type='info',
                )
            return _click

        def _render_ocr_items() -> None:
            """`extracted_items`(누적 목록) 전체를 다시 그립니다 — 이번에 새로 온 항목만이
            아니라 지금까지 이 페이지에서 인식된 모든 항목입니다."""
            extracted_box.clear()
            with extracted_box:
                for item in extracted_items:
                    low_conf = item.get('confidence') == 'low'
                    name_text = item.get('raw_name') or '(이름 미인식)'
                    qty_text = _ocr_value_text(item.get('quantity')) or '수량 미인식'
                    price_text = _ocr_value_text(item.get('avg_price')) or '매입가 미인식'
                    # 확신도가 낮은 행은 노란 테두리 + 배지로 강조해 재확인을 유도합니다.
                    border = '2px solid #f59e0b' if low_conf else '1.5px solid #334155'
                    with ui.row().classes('w-full items-center gap-2 no-wrap') \
                            .style(f'border: {border}; border-radius: 10px; padding: 8px 12px;'):
                        ui.label(f'{name_text} · {qty_text}주 · {price_text}') \
                            .classes('flex-1 min-w-0 truncate')
                        if low_conf:
                            ui.badge('⚠️ 확인 필요', color='amber-8').classes('shrink-0')
                        ui.button('입력창에 채우기', on_click=_make_ocr_fill_handler(item)) \
                            .props('flat dense no-caps').classes('shrink-0')

        async def _on_ocr_upload(event) -> None:
            image_bytes = await event.file.read()
            try:
                # 🔒 서버 쪽 크기 확인. 아래 ui.upload(max_file_size=...) 는 브라우저에서만
                #    거르므로, 업로드 주소로 직접 POST 하면 그대로 통과합니다 — 유료 외부
                #    API 호출과 서버 메모리가 걸린 자리라 서버에서 다시 막습니다(§0-3-9).
                if len(image_bytes) > MAX_OCR_IMAGE_BYTES:
                    _show_ocr_error(
                        f'🚫 이미지가 너무 큽니다 — {MAX_OCR_IMAGE_BYTES // (1024 * 1024)}MB 이하로 '
                        '줄이거나 화면을 나눠서 캡처해 주세요.'
                    )
                    return
                # 🔒 이미지 형식 확인도 **한도를 차감하기 전에** 끝냅니다(2026-08-18 수정).
                #    업로드 위젯의 `accept` 는 브라우저 쪽 검사라 우회되고(§0-3-9), 형식
                #    판별은 바이트 앞부분 몇 개만 보면 되는 일이라 유료 호출이 전혀 필요
                #    없습니다. 예전에는 이 판정이 아래 외부 호출 함수 **안쪽**에서만
                #    일어나서, 이미지가 아닌 파일을 올리면 돈은 안 나가는데 사용자의 하루
                #    한도만 1회 깎였습니다 — `consume_ocr_quota` 독스트링이 약속한
                #    "유료 호출이 없었던 업로드는 한 번으로 세지 않는다"와 어긋나던 자리입니다.
                try:
                    ensure_supported_image_format(image_bytes)
                except OcrError as exc:
                    # ⚠️ 여기서는 아직 차감이 없었으므로 남은 횟수 표시를 건드리지 않습니다
                    #    (애초에 `quota` 가 아직 존재하지도 않습니다).
                    _show_ocr_error(f'🚫 {exc}')
                    return
                # 🔒 하루 업로드 한도(로그인 사용자별) — **유료 API 를 부르기 전에** 1회를
                #    차감합니다. 한도를 다 썼으면 여기서 예외가 나고 아래 호출은 실행되지
                #    않습니다(= 돈이 나가지 않습니다). 세는 일은 전부 데이터 계층
                #    (`utils/scorecard_db.py::consume_ocr_quota`)이 하고, 이 화면은 그 결과만
                #    씁니다 — 이 파일에서 Supabase 를 직접 부르지 않습니다(§4-3).
                #    ⚠️ `user_id` 는 이 함수가 인자로 받은 **이 접속자 본인**의 id 입니다.
                #       전역에서 "지금 누구지"를 추측하지 않으므로 다른 사용자의 한도와 절대
                #       섞이지 않습니다(§0-3-8).
                quota = await run.io_bound(consume_ocr_quota, client, user_id)
                # 실제 네트워크 호출(외부 OCR provider — 어떤 회사 모델인지는 extract_holdings_
                # from_image() 안에서만 갈립니다, §0-3-11) 한 곳만 별도 스레드로 넘깁니다.
                # 그대로 이벤트 루프에서 기다리면 이 접속뿐 아니라 서버 전체가 멈춥니다
                # (§0-3-10, web/auth_ui.py 의 `busy()` 주석과 동일한 이유).
                result = await run.io_bound(extract_holdings_from_image, image_bytes)
            except OcrError as exc:
                # OcrError 의 문구는 이미 "사람이 읽을 한 문장"으로만 만들어져 있습니다
                # (원본 예외·스택은 utils/scorecard_ocr.py 가 로그로만 남김 — §0-3-4).
                _show_ocr_error(f'🚫 {exc}')
                # 2026-08-18 수정 — 이 자리까지 왔다는 건 바로 위 `consume_ocr_quota` 가
                # 이미 성공해서 **한도가 실제로 1회 차감된 뒤**라는 뜻입니다(유료 호출은 그
                # 다음 줄에서 일어납니다). 그런데 예전에는 실패 경로에서 남은 횟수 표시를
                # 갱신하지 않아, 화면에는 실제보다 1 많은 숫자가 그대로 남았습니다(§0-1 —
                # 화면이 사실과 달라짐). 성공 경로와 같은 함수로 갱신합니다.
                # ⚠️ 아래 `except ScorecardError`·`except Exception` 분기에서는 **절대 같은
                #    일을 하지 마세요** — 그쪽은 `quota` 가 아직 바인딩되지 않았을 수 있어
                #    `UnboundLocalError` 가 납니다. 그리고 그 경우엔 차감 자체가 없었으므로
                #    화면의 숫자도 이미 맞습니다.
                _set_quota_label(quota)
                return
            except ScorecardError as exc:
                # 한도 초과(OcrQuotaExceeded)와 한도 기록 실패가 여기로 옵니다. 둘 다 이미
                # "사람이 읽을 한국어 한 문장"이고, 어느 쪽이든 **유료 호출은 일어나지
                # 않았습니다.** 한도 기록 자체가 실패했을 때 그냥 통과시키지 않는 이유:
                # 세지 못하는 상태에서 유료 API 만 열리면 한도가 없는 것과 같습니다(§0-1).
                _show_ocr_error(f'🚫 {exc}')
                return
            except Exception as exc:                       # noqa: BLE001 — 실패를 조용히 삼키지 않음(§0-1)
                _show_ocr_error(f'🚫 {_fail(exc, "스크린샷을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")}')
                return
            finally:
                image_bytes = None   # 이 핸들러가 원본 바이트를 계속 들고 있지 않게 참조를 끊습니다(§0-3-8).
            # 이번 장이 성공했으니 직전에 남아있던 실패 배너(있었다면)는 지웁니다 — 지금은
            # 성공했다는 사실을 화면에 명확히 반영합니다. (성공 결과가 담긴 extracted_box는
            # 건드리지 않습니다 — 여러 장을 올려도 이전 장 결과가 안 지워지는 게 이번 수정의
            # 핵심입니다.)
            error_slot.clear()
            # 새로 인식된 항목을 기존 누적 목록에 "추가"합니다(교체가 아님).
            extracted_items.extend(result['items'])
            _render_ocr_items()
            # 남은 횟수는 매번 갱신되는 전용 라벨 하나에만 반영합니다 — 장마다 새 라벨을
            # 쌓지 않으므로 여러 장을 올려도 "오늘 남은 ..." 문구는 한 줄로 최신값만 보입니다.
            _set_quota_label(quota)

        ui.upload(
            label='📷 브로커 앱 스크린샷 업로드',
            auto_upload=True,
            # 브라우저 쪽 1차 검사(사용자에게 즉시 피드백). 실제 방어는 위 서버 쪽 확인입니다.
            max_file_size=MAX_OCR_IMAGE_BYTES,
            on_upload=_on_ocr_upload,
        ).props('accept=".png,.jpg,.jpeg,.webp"').classes('w-full')
        ui.separator()

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

    # 🔴 2026-08-17 (실기기 확인) — 모바일에서 이 제목이 "미/국/주/식" 처럼 한 글자씩 세로로
    #    쌓이던 버그를 고친 자리입니다. #122·#123·#127~#130 과 **같은 계열**이고 원인도 같습니다.
    #
    #    [고치기 전] 줄 전체 `no-wrap` + 제목 `flex-1 min-w-0` + 캡션 `shrink-0`
    #      · `no-wrap`  → 캡션이 다음 줄로 못 내려감
    #      · 캡션 `shrink-0` → "🕒 현재가 : 2026-08-16 15:30 기준 (KST) — 실시간 시세가
    #        아닙니다." 라는 40자짜리 문장이 **한 치도 안 줄어들고** 줄 폭을 통째로 차지
    #      · 제목 `flex-1 min-w-0` → "얼마든지 줄어들어도 된다"는 뜻이라 남은 폭(≈0)까지 수축
    #      · 한글은 띄어쓰기가 없어도 글자 사이에서 줄바꿈되므로 → 한 글자씩 세로로 쌓임
    #      (반대로 그 위 "한국/미국" 토글이 멀쩡했던 건 Quasar 버튼이라 수축하지 않아서입니다.)
    #
    #    [고친 뒤] 역할을 정반대로 뒤집고, 좁으면 **줄 단위로** 갈라지게 합니다.
    #      ① `no-wrap` 제거 → 폭이 모자라면 캡션이 통째로 다음 줄로 내려감(허용 패턴 C)
    #      ② 제목 `shrink-0` → 절대 수축하지 않음(글자 단위 쌓임이 구조적으로 불가능)
    #      ③ 캡션 `flex: 1 1 260px` → 남는 폭이 260px 미만이면 줄바꿈. `flex-1`(basis 0)은
    #         절대 다음 줄로 안 내려가서 오히려 같은 사고가 나므로 **쓰면 안 됩니다.**
    #      ④ 양쪽 다 `vh-keep-all`(word-break: keep-all) → 어떤 폭에서도 CJK 는 띄어쓰기
    #         자리에서만 줄바꿈 (web/theme.py)
    with ui.row().classes('items-center gap-2 w-full'):
        ui.markdown(f'### {CURRENCY_TITLES.get(currency, currency)}') \
            .classes('shrink-0 vh-keep-all')
        if sync_label:
            # sync_label 은 사용자 입력이 아니라 우리 수집기가 쓴 메타데이터에서만 옵니다.
            # 그래도 esc() 는 습관적으로 걸어 둡니다 (§0-3-9).
            ui.html(
                f'<div style="font-size:0.9rem; font-weight:600; color:#cbd5e1;">'
                f'🕒 {esc(sync_label)} — 실시간 시세가 아닙니다.</div>'
            ).classes('vh-keep-all').style('flex: 1 1 260px; min-width: 0;')

    with ui.row().classes('w-full gap-4 items-stretch'):
        metric_card('매입원가 합계', format_amount(group["total_cost"], currency))
        if group["total_value"] is not None:
            base = group["total_cost_priced"]
            profit = group["total_profit"]
            metric_card('평가금액 합계', format_amount(group["total_value"], currency))
            metric_card('평가손익', format_amount(profit, currency),
                        pct_text(profit / base * 100 if base else None))
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

    (2026-08-17) 표 껍데기 HTML 은 `web/components/html.py::holdings_table_html()` 로
    옮겼습니다 — '사장님 보고서'가 글자 그대로 같은 HTML 을 따로 들고 있었습니다 (§0-3-10).
    이 함수에는 **이 화면만의 열 구성과 칸 서식**만 남습니다.

    🔐 §0-3-9 — 각 칸은 여기서 `esc()` 까지 끝내서 넘깁니다(공용 함수는 칸 내용을 HTML
       조각으로 그대로 받습니다). `_row_label_html()`·`pct_html()` 은 내부에서 이미
       이스케이프를 마친 조각을 돌려줍니다.
    """
    headers = ['종목', '수량', '평균매입가', '현재가', '평가손익', '수익률', '비중']
    body_rows = [
        [
            _row_label_html(row, indexes),
            esc(f'{row["quantity"]:,.6g}'),
            esc(format_amount(row["avg_purchase_price"], currency)),
            esc(format_amount(row["current_price"], currency) if row["price_available"] else '현재가 없음'),
            esc(format_amount(row["profit"], currency) if row["price_available"] else '—'),
            pct_html(row.get("profit_pct")),
            esc(f'{row["weight_pct"]:.1f}%' if row.get("weight_pct") is not None else '—'),
        ]
        for row in rows
    ]
    ui.html(holdings_table_html(headers, body_rows)).classes('w-full')


def _render_row_manager(client, user_id: str, rows, indexes, view: dict, redraw, on_changed) -> None:
    """"종목 관리" 줄 (종목명 + ✏️ + 🗑️).

    🔴 #127~#130 에서 여섯 번 싸운 바로 그 레이아웃입니다. Streamlit 에서는 `st.columns()` 가
       JS 로 인라인 style 을 박아넣어 CSS 로 이길 수 없었지만(공식 이슈 #6592), NiceGUI 의
       `ui.row()` 는 평범한 flex 컨테이너라 `no-wrap` 한 줄이면 끝입니다.
       **이 세 클래스를 지우지 마세요**: 줄 전체 `no-wrap`, 라벨 `flex-1 min-w-0`, 버튼 `shrink-0`.

    ⚠️ 2026-08-17 — 여기 라벨은 (버튼 두 개가 작아서) 통화 블록 제목만큼 극단적으로 좁아지진
       않지만, 구조는 **똑같이 "줄어들어도 되는 CJK 라벨"** 입니다. 좁은 기기에서 종목명이
       글자 단위로 쪼개지지 않도록 같은 `vh-keep-all` 을 함께 걸어 둡니다
       (`word-break` 는 상속 속성이라 안쪽 `_row_label_html()` 의 div 까지 적용됩니다).
    """
    ui.markdown('**종목 관리**')
    for row in rows:
        row_id = row.get("id")
        with ui.row().classes('no-wrap items-center gap-2 w-full vh-card'):
            ui.html(_row_label_html(row, indexes)).classes('flex-1 min-w-0 vh-keep-all')
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
    # 조각 색 안전망 ② (본 수정). 종목 수가 팔레트보다 많으면 처음부터 다시 돌려 씁니다
    # (plotly 가 colorway 를 재사용하는 방식과 동일). 라벨 순서 = 색 순서라 항상 1:1 로 맞습니다.
    fig.update_traces(marker=dict(
        colors=[_SLICE_COLORS[i % len(_SLICE_COLORS)] for i in range(len(names))],
    ))
    fig.update_layout(**_chart_layout())
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
