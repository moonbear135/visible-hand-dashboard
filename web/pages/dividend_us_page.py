"""
🇺🇸 미국 배당 달력 (공개 화면, URL `/dividend/us`).

한국 배당 달력(`/dividend`, `web/pages/dividend_page.py`)의 **미국판**입니다. 화면 구조·
정직성 배너·"🧮 계산값" 배지 같은 이미 검증된 UX 를 그대로 따르되, 데이터 출처와 그 데이터가
가진 한계가 완전히 달라서 안내 문구는 처음부터 다시 썼습니다.

-------------------------------------------------------------------------------
🟡 왜 `dividend_page.py` 를 고치지 않고 새 파일을 만들었나
-------------------------------------------------------------------------------
① 이 저장소에 **이미 같은 전례**가 있습니다 — 밸류에이션 화면은 한국(`/`)이
   `web/pages/pegy_page.py`, 미국(`/us`)이 `web/pages/us_stocks_page.py` 로 **파일이
   나뉘어** 있습니다(한 파일이 두 라우트를 등록하는 구조가 아닙니다). 같은 모듈의
   한국/미국 화면을 나누는 것이 이 프로젝트의 기존 방식입니다.
② `web/pages/dividend_page.py` 는 **실서비스 중**이고, 이번 작업의 최우선 원칙이 "그
   파일을 건드리지 않는다" 입니다(§0-3-6 모듈 격리). 라우트만 추가하더라도 같은 파일을
   열어 편집하는 순간 한국 배당 달력이 회귀할 위험이 생깁니다.
③ 두 화면은 읽는 파일도(`dividend_kr_2026_latest.json` ↔ `us_stocks_latest.json`),
   달력에 찍는 날짜의 뜻도(결산기준일 ↔ 배당락일) 다릅니다. 공유할 수 있는 코드가 달력
   격자 계산 두 함수뿐이라 합칠 이득이 없습니다.
   → 순수 로직은 `web/pages/dividend_us_logic.py` 에 있고, 왜 그 파일도 따로 뒀는지는
     그 파일 머리말에 적어 두었습니다.

-------------------------------------------------------------------------------
🔴 이 화면이 **사실대로** 말해야 하는 것 네 가지 (§0-1) — 전부 상시 배너입니다
-------------------------------------------------------------------------------
① **이 화면을 위한 새 수집기는 없습니다.** 매일 자동으로 도는 기존 미국주식 수집기
   (`collector_us_stocks.py`)가 만드는 `data/us_stocks_latest.json` 에 이미 들어 있는
   `dps`·`div_yield`·`ex_dividend_date`·`dividend_status` 네 필드를 **읽기만** 합니다.
   서버 부하를 새로 만들지 않는 대신, 그 스냅샷이 가진 한계도 그대로 물려받습니다.
② **날짜의 성격이 종목마다 다릅니다.** `ex_dividend_date` 는 stockanalysis.com 의
   "Statistics" 개요 페이지(배당 전용 페이지가 아닙니다) 스냅샷 값이라, 이미 발표된
   다음 배당이 있으면 **미래 날짜**가, 아직 없으면 **가장 최근 과거 날짜**가 들어옵니다.
   2026-08-27 실측으로 배당 데이터가 있는 403종목 중 157종목(39%)만 미래 날짜였고
   246종목(61%)은 과거 날짜였습니다. 이 비대칭을 배너에 숫자 그대로 적습니다.
③ **미래 배당 날짜를 예측·계산하지 않습니다.** "지난번이 6월 4일이었으니 다음은 9월
   4일쯤"은 배당이 줄거나 끊기는 순간 그대로 틀린 정보가 됩니다. 값이 없으면 "미확정"
   이라고 얼버무리지 않고 **"아직 다음 배당 발표 안 됨"** 이라고 적습니다.
④ **상위 시가총액 종목만 다룹니다.** 미국 전 상장사가 아니라 기존 미국주식 화면이 추적
   중인 유니버스(`is_visible` 대상)뿐입니다.

-------------------------------------------------------------------------------
🧮 이 화면이 유일하게 계산하는 값 — "매수 마지막 날"
-------------------------------------------------------------------------------
배당락일 **당일**에 사면 이번 배당은 못 받습니다. 받으려면 **직전 거래일**까지 사 두어야
합니다(미국도 한국과 같은 규칙). 소스가 배당락일을 이미 계산해서 주므로 우리가 하는 계산은
"그 날의 직전 미국 개장일 찾기" 한 줄뿐이고, 그래도 우리가 만든 값이라 "🧮 계산값" 배지를
답니다(한국 배당 화면의 배당락일 배지와 같은 정신).
🔴 **이미 지나간 배당락일에는 이 안내를 띄우지 않습니다** — 지난 날짜를 두고 "매수하세요"
라고 말하면 그 자체가 거짓말이기 때문입니다.

-------------------------------------------------------------------------------
🔴 상태 관리 · 세션 격리 (§0-3-8)
-------------------------------------------------------------------------------
"보고 있는 달 / 고른 날짜 / 검색어 / 페이지"는 전부 `_render_body()` 안의 지역 dict
(`view`) 하나에만 있습니다. 이 파일의 모듈 최상위에는 문자열·튜플 상수만 있습니다
(가변 전역 0개 — `tests/test_web_session_isolation.py::test_no_mutable_globals`).

-------------------------------------------------------------------------------
🔴 XSS (§0-3-9)
-------------------------------------------------------------------------------
회사명·티커·업종은 전부 **외부(stockanalysis)에서 온 값**입니다. HTML 로 나가는 자리는
예외 없이 `esc()` 를 거칩니다("티커는 알파벳이니까 괜찮다" 같은 판단을 코드에 남기지
않습니다).

-------------------------------------------------------------------------------
🚧 공개 게이트 (§0-3-6 — 오너 승인 전 기본 숨김)
-------------------------------------------------------------------------------
    DIVIDEND_US_ENABLED          … 이 화면 전용 스위치(환경변수, 기본 꺼짐)
    DIVIDEND_US_MENU_ADMIN_ONLY  … 2단계(관리자 전용) ↔ 3단계(전체 공개)
값의 출처는 `web/layout.py` **한 곳**이고, 한국 배당 스위치(`DIVIDEND_ENABLED`)와는
완전히 독립입니다 — 한쪽을 꺼도 다른 쪽은 그대로 돕니다.

-------------------------------------------------------------------------------
📌 후행지표 전용 (§0-3-1)
-------------------------------------------------------------------------------
"실시간"이라는 말을 쓰지 않습니다. 화면의 모든 값은 **수집 시점의 스냅샷**이고, 그 시각
(`metadata.last_updated_at_kst` / `last_updated_at_et`)을 맨 위에 그대로 밝힙니다.
"""

from nicegui import ui

from web.auth import is_admin
from web.components import (
    NA_TEXT,
    disclaimer_footer,
    error_banner,
    esc,
    fmt_num,
    holdings_table_html,
    info_badge,
    info_banner,
    metric_card,
    pager,
    warn_badge,
    warning_banner,
)
from web.layout import DIVIDEND_US_ENABLED, DIVIDEND_US_MENU_ADMIN_ONLY, layout
from web.pages.dividend_us_logic import (
    NYSE_VERIFIED_YEARS,
    WEEKDAY_LABELS,
    available_months,
    build_view_data,
    count_in_month,
    date_key,
    group_by_ex_date,
    month_label,
    month_weeks,
    shift_month,
    today_et,
    value_range,
)
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file_async,
)

# 🔴 휴장일 표가 검증 안 된 해로 넘어가기 전에 미리 시끄럽게 경고합니다 — 한국 배당 화면이
#    `KRX_VERIFIED_YEARS` 에 대해 하는 것과 **같은 함수·같은 방식**입니다(§0-3-10). 마감
#    60일 전부터 서버 로그(Render)에 찍히기 시작합니다. 그 시점이 지나면
#    `is_nyse_trading_day()` 가 예외를 던지며 "매수 마지막 날" 칸만 비게 되고(달력 자체는
#    그대로 그려집니다), 표를 다시 뽑아 채우면 됩니다.
from utils.expiry_alarms import warn_if_expiring

warn_if_expiring('미국 매수 마지막 날 계산용 NYSE 휴장일 표 '
                 '(dividend_us_logic.py: NYSE_VERIFIED_YEARS)',
                 max(NYSE_VERIFIED_YEARS))

# =============================================================================
# 상수 — 전부 문자열/튜플(불변)입니다. 가변 전역(dict/list/set)은 하나도 두지 않습니다.
# =============================================================================
#: 이 화면이 읽는 **유일한** 데이터 파일. 기존 미국주식 화면(`us_stocks_page.py`)이 읽는
#: 것과 같은 파일이고, 이 화면을 위해 새로 만든 파일은 없습니다.
DATA_FILENAME = 'us_stocks_latest.json'

#: 한 페이지에 그릴 표 행 수(날짜별 상세·배당 없음 목록 공통).
ITEMS_PER_PAGE = 50

#: 날짜를 눌렀을 때 나오는 표의 열 제목.
DAY_HEADERS = (
    '종목 (티커)', '주당 배당금 (연간 합계)', '배당수익률', '배당락일', '매수 마지막 날', '업종',
)

#: "배당 없음이 확인된 종목" 표의 열 제목.
NO_DIVIDEND_HEADERS = ('종목 (티커)', '순위', '업종', '현재가')

#: 🔴 이 달력의 데이터가 어디서 왔고 무엇을 뜻하는지 — 툴팁이 아니라 **상시 배너**입니다.
#:    (한국 배당 화면의 `CALENDAR_DATE_NOTICE` 와 같은 자리·같은 취지. 다만 그쪽은
#:     "이 날짜는 지급일이 아니다"를 말하고, 이쪽은 "이 날짜는 과거일 수도 미래일 수도
#:     있다"를 말합니다 — 데이터의 한계 자체가 다릅니다.)
CALENDAR_SOURCE_NOTICE = (
    '📅 이 달력의 날짜는 "배당락일"이에요 — 이 날 통장에 돈이 들어온다는 뜻이 아닙니다.\n'
    '배당락일은 "이 날부터 사면 이번 배당은 못 받는다"는 날이에요. 실제로 돈이 들어오는 '
    '지급일은 이 화면이 보는 자료에 아예 없어서, 모르는 날짜를 지어내지 않고 아는 날짜만 '
    '보여드려요.\n'
    '🔴 그리고 이 날짜는 종목마다 성격이 다릅니다 — 이미 다음 배당이 발표된 회사는 '
    '"아직 안 지난 미래 날짜"가, 아직 발표가 없는 회사는 "가장 최근에 지나간 과거 날짜"가 '
    '적혀 있어요. 어느 쪽인지는 아래 달력에서 색으로 구분해 두었습니다.'
)

#: 🔴 데이터가 "기존 수집기에 얹혀서" 나온다는 사실 + 39%/61% 실측 비대칭.
DATA_ORIGIN_NOTICE = (
    '🧷 이 화면은 **배당 전용 수집기가 따로 없습니다.** 매일 자동으로 도는 기존 미국주식 '
    '수집기가 만드는 스냅샷 파일 하나(data/us_stocks_latest.json)에 이미 들어 있는 '
    '주당배당금·배당수익률·배당락일 값을 그대로 읽어 달력으로만 다시 그린 것입니다. '
    '새로 서버에 부담을 주지 않는 대신, 그 스냅샷이 가진 한계를 그대로 물려받습니다.\n'
    '🔴 그 배당락일 값은 배당 전용 페이지가 아니라 종목 개요(Statistics) 페이지에 찍혀 '
    '있는 스냅샷 한 개입니다. 그래서 **이미 발표된 다음 배당이 있으면 미래 날짜가, 아직 '
    '없으면 가장 최근 과거 날짜가** 들어옵니다 — 어느 쪽인지는 종목마다 다릅니다. '
    '2026-08-27 기준으로 직접 세어 보니 배당 데이터가 있는 403종목 중 157종목(39%)만 '
    '미래 날짜였고, 나머지 246종목(61%)은 과거 날짜뿐이었습니다.\n'
    '🔴 **우리가 다음 배당일을 예측해서 채우지 않습니다.** "지난번이 6월 4일이었으니 '
    '다음은 9월 4일쯤"이라고 적는 건 쉽지만, 회사가 배당을 줄이거나 끊으면 그 순간 '
    '거짓 정보가 됩니다. 그래서 발표가 없는 종목은 "미확정"이라고 얼버무리지 않고 '
    '"아직 다음 배당 발표 안 됨"이라고 그대로 적습니다.\n'
    '🎯 대상은 미국 전 상장사가 아니라, 이 서비스가 추적 중인 **상위 시가총액 종목**뿐입니다.'
)

#: 🔴 2026-08-29 추가(H4) — `dps` 는 stockanalysis "Statistics" 페이지의 **연간(최근 1년
#:    합계, TTM)** 주당배당금입니다. 그런데 이 값을 특정 배당락일 1건 옆에 그대로 붙이면
#:    분기 배당 회사는 실제 그 배당락일에 받는 금액의 **최대 4배**, 월 배당 회사는
#:    **최대 12배** 과대하게 보입니다(배당 주기 정보를 이 스냅샷에서 얻을 수 없어 몇
#:    배인지조차 화면이 알 수 없습니다). §0-1·§0-3-13 — 지어내지 않되, 오해할 수 있는
#:    숫자는 그 옆에서 바로 경고합니다.
DPS_ANNUAL_NOTICE = (
    '💵 표·달력의 "주당 배당금"은 **최근 1년(TTM) 합계**입니다 — 이 배당락일에 실제로 '
    '받는 금액이 아닙니다.\n'
    '분기마다 배당하는 회사라면 이 날 실제로 받는 돈은 표시된 값의 **약 1/4**, '
    '매달 배당하는 회사라면 **약 1/12** 수준일 수 있습니다. 이 화면은 배당 주기(분기/월/반기 '
    '등) 정보를 갖고 있지 않아 정확한 배수를 계산해 드릴 수 없습니다 — 실제 1회 지급액은 '
    '증권사 앱이나 회사 IR 자료로 확인해 주세요.'
)

#: 🔴 M7(2026-08-29) 추가 — 표·달력의 모든 금액은 **세전**인데 그 사실을 어디에도 적지
#: 않았습니다. 세후 금액은 계좌 종류(일반/ISA/연금 등)·거주자 여부·조세조약 적용 여부에
#: 따라 사람마다 달라서, 이 화면이 일괄 세율(예: 15%)을 곱해 "세후 예상액"을 계산해
#: 보여드리면 그 자체가 틀린 안내가 될 수 있습니다(§0-1) — 그래서 계산하지 않고, 세전
#: 금액이라는 사실만 명확히 밝힙니다.
TAX_NOTICE = (
    '💸 이 화면의 모든 금액(주당 배당금ㆍ배당수익률 계산에 쓰인 원천 수치)은 **세전** '
    '금액입니다. 미국 배당소득에는 원천징수세가 붙는데(한미 조세조약 적용 시 통상 15%, '
    '계좌 종류ㆍ개인 상황에 따라 달라질 수 있음), 실제 입금액은 이보다 적습니다.\n'
    '세율은 계좌 종류ㆍ거주자 여부 등 개인 상황에 따라 달라서, 이 화면은 세후 예상액을 '
    '계산해 보여드리지 않습니다 — 정확한 세후 금액은 증권사 앱이나 세무 전문가를 통해 '
    '확인해 주세요.'
)

#: ⏰ "매수 마지막 날" 규칙 — 미래 날짜가 있는 종목에만 쓰는 큰 글자 배너.
BUY_DEADLINE_WARNING = '⏰ 배당락일 전날까지 사야 이번 배당을 받을 수 있어요!'

#: 🧮 "매수 마지막 날"이 계산값이라는 사실을 매번 밝히는 배지 본문(우리가 쓴 신뢰된 HTML).
LAST_BUY_CALC_NOTE = (
    '"매수 마지막 날"은 소스에 없는 값이라 이 화면이 직접 계산합니다 — 배당락일의 '
    '<b>직전 미국 개장일</b>입니다(주말·뉴욕증권거래소 휴장일 제외).<br>'
    '배당락일 당일에 사면 이번 배당은 받지 못하기 때문에, 하루 앞의 거래일이 실제 '
    '마감입니다.<br>'
    '⚠️ 휴장일 표는 확인된 연도만 있습니다 — 그 밖의 연도는 계산하지 않고 칸을 '
    '비웁니다(추측 금지).'
)

#: 미래/과거 날짜를 색으로 가르는 두 색. 이 화면 안에서 이 두 색은 **오직 이 뜻으로만**
#: 씁니다(한국 배당 화면이 🟡기준일·🟢지급일·🔴락일 색을 고정해 쓰는 것과 같은 규칙).
FUTURE_COLOR = '#4ade80'   # 🟢 아직 안 지난 날짜 — 지금부터 준비할 수 있는 배당
PAST_COLOR = '#94a3b8'     # ⚪ 이미 지나간 날짜 — 기록일 뿐, 행동할 수 있는 게 없음
TODAY_HIGHLIGHT_COLOR = '#60a5fa'   # 🔵 오늘(미국 동부 시간) — 날짜 종류가 아니라 기준점

#: 🔵 오늘 배너 · 달력 오늘 칸에 함께 쓰는 안내(왜 "미국 동부 시간"인지).
TODAY_TIMEZONE_NOTE = (
    '이 화면의 "오늘"은 **미국 동부 시간** 기준입니다 — 다루는 대상이 미국 증시라서요. '
    '한국 시간으로 이른 아침이면 미국은 아직 어제일 수 있습니다.'
)

#: "배당 없음이 확인된 종목" 구획 설명 — **미확정과 절대 섞지 않습니다.**
NO_DIVIDEND_NOTICE = (
    '아래 종목들은 배당이 없다는 것이 **확인된** 회사입니다(수집기가 배당 항목 자체를 '
    '확인한 뒤 "없음"으로 기록한 상태 = dividend_status: confirmed_none).\n'
    '🔴 "아직 확인이 안 됐다"와는 전혀 다른 뜻이라 달력·미확정 목록과 섞지 않고 여기 '
    '따로 둡니다. 배당을 안 하는 회사가 나쁜 회사라는 뜻도 아닙니다 — 번 돈을 배당 대신 '
    '재투자나 자사주 매입에 쓰는 회사들이 여기 많이 들어옵니다.'
)

#: 날짜를 못 읽은 종목이 있을 때만 뜨는 안내 — 실패를 조용히 스킵하지 않습니다(§0-1).
UNPARSED_NOTICE_HEAD = (
    '⚠️ 배당 데이터는 있는데 배당락일 **글자를 읽지 못한** 종목이 아래만큼 있습니다. '
    '이 종목들은 달력에 넣지 않았습니다 — 넣을 날짜를 만들어낼 수 없기 때문입니다. '
    '건수를 숨기지 않고 그대로 적어 둡니다.'
)

COMING_SOON_TEXT = (
    '🚧 "미국 배당 달력"은 아직 준비중입니다.\n\n'
    '데이터 검수가 끝나고 오너 승인이 나면 열립니다. 그때까지는 아무 수치도 그리지 않습니다.'
)


# =============================================================================
# 1. HTML 조각 만들기 — 외부 값은 예외 없이 `esc()` 를 거칩니다 (§0-3-9)
# =============================================================================
def stock_name_html(stock_or_entry) -> str:
    """한글명(있으면) + 영문명 + 티커 한 칸.

    표기 규칙은 기존 미국주식 화면(`us_stocks_page._name_html`)과 같은 관례를 따릅니다 —
    한글명이 **자동 음역**이면 그 사실을 배지로 밝히고, 한글명이 아예 없으면 영문명을
    그대로 씁니다(없는 이름을 지어내지 않습니다).
    """
    name_kr = stock_or_entry.get('name_kr')
    name_en = stock_or_entry.get('name') or ''
    symbol = stock_or_entry.get('symbol') or ''

    translit_badge = ''
    if name_kr:
        main = name_kr
        if stock_or_entry.get('name_kr_is_transliterated'):
            translit_badge = info_badge(
                '음역',
                '한국에서 널리 쓰이는 정식 한글명이 없어, 영문 사명을 <b>발음대로 자동 '
                '음역</b>한 표기입니다(번역이 아닙니다).<br>실제 통용 표기와 다를 수 '
                '있으니 정확한 이름은 옆의 영문명과 티커로 확인해 주세요.',
            )
    else:
        main = name_en or symbol

    return (
        f'<div style="font-weight:800; color:#f8fafc;">{esc(main)}{translit_badge}</div>'
        f'<div style="font-size:11px; color:#94a3b8;">{esc(name_en)}</div>'
        f'<div style="font-size:12px; color:#38bdf8; font-weight:800;">{esc(symbol)}</div>'
    )


def dps_html(entry) -> str:
    """주당 배당금 — 소스가 달러로 주는 값 그대로. 없으면 '데이터 없음'(0 아님).

    🔴 H4(2026-08-29): 이 값은 **연간(TTM) 합계**이지 이 배당락일 1회 지급액이 아닙니다
    (`DPS_ANNUAL_NOTICE` 참고). 배지 없이 숫자만 보여주면 분기·월 배당 회사에서 그대로
    오독되므로, 값 아래 항상 "연간 합계" 를 작게 함께 적습니다.
    """
    value = entry.get('dps')
    if not isinstance(value, (int, float)):
        return f'<span style="color:#94a3b8;">{esc(NA_TEXT)}</span>'
    return (f'<span style="font-weight:800; color:#f8fafc;">${fmt_num(value, digits=2)}</span>'
            f'<div style="font-size:10px; color:#94a3b8;">연간 합계(TTM) — 1회 지급액 아님</div>')


def yield_html(entry) -> str:
    """배당수익률 — 소스 원문값(%)입니다. 우리가 다시 계산해서 덮어쓰지 않습니다."""
    value = entry.get('div_yield')
    if not isinstance(value, (int, float)):
        return f'<span style="color:#94a3b8;">{esc(NA_TEXT)}</span>'
    return f'<span style="font-weight:800; color:{FUTURE_COLOR};">{fmt_num(value, digits=2)}%</span>'


def ex_date_html(entry) -> str:
    """배당락일 한 칸 — 미래/과거를 색과 글자 **양쪽으로** 구분합니다.

    색만으로 구분하면 색을 구분하기 어려운 분들에게는 아무 정보가 아니라서, "(이미 지난
    날짜)" 같은 글자를 항상 함께 답니다.
    """
    day = entry['ex_date']
    text = f'{day.year}년 {day.month}월 {day.day}일'
    if entry['is_future']:
        return (f'<span style="color:{FUTURE_COLOR}; font-weight:800;">🟢 {esc(text)}</span>'
                f'<div style="font-size:11px; color:#94a3b8;">아직 안 지난 날짜</div>')
    return (f'<span style="color:{PAST_COLOR}; font-weight:700;">⚪ {esc(text)}</span>'
            f'<div style="font-size:11px; color:#94a3b8;">이미 지난 날짜</div>')


def last_buy_html(entry) -> str:
    """🧮 매수 마지막 날 한 칸.

    🔴 **이미 지나간 배당락일에는 날짜를 적지 않습니다.** 지난 날을 두고 "이때까지 사세요"
       라고 쓰면 그 자체가 틀린 안내라, 대신 왜 안 적는지를 한 줄로 밝힙니다(§0-1).
    🔴 계산이 불가능했으면(확인 안 된 연도 등) 아무 날짜나 넣지 않고 이유를 그대로 적습니다.
    """
    if not entry['is_future']:
        return ('<span style="color:#94a3b8; font-size:12px;">'
                '이미 지난 배당이라 매수 안내를 하지 않습니다</span>')
    computed = entry.get('last_buy_date')
    if computed is None:
        reason = entry.get('last_buy_reason') or '계산할 수 없습니다'
        return f'<span style="color:#fbbf24; font-size:12px;">{esc(reason)}</span>'
    text = f'{computed.year}년 {computed.month}월 {computed.day}일'
    badge = warn_badge('🧮 계산값', LAST_BUY_CALC_NOTE)
    return (f'<span style="color:{FUTURE_COLOR}; font-weight:800;">{esc(text)} 까지</span>'
            f'{badge}')


def day_row_cells(entry):
    """날짜별 상세 표 한 행."""
    industry = entry.get('industry') or NA_TEXT
    reit_mark = ' 🏢 리츠' if entry.get('is_reit') else ''
    return [
        stock_name_html(entry),
        dps_html(entry),
        yield_html(entry),
        ex_date_html(entry),
        last_buy_html(entry),
        f'<span style="color:#cbd5e1; font-size:12px;">{esc(industry)}{esc(reit_mark)}</span>',
    ]


def no_dividend_row_cells(stock):
    """"배당 없음이 확인된 종목" 표 한 행."""
    price = stock.get('price')
    price_html = (f'${fmt_num(price, digits=2)}' if isinstance(price, (int, float))
                  else esc(NA_TEXT))
    return [
        stock_name_html(stock),
        esc(stock.get('rank') if stock.get('rank') is not None else NA_TEXT),
        f'<span style="color:#cbd5e1; font-size:12px;">{esc(stock.get("industry") or NA_TEXT)}</span>',
        f'<span style="color:#cbd5e1;">{price_html}</span>',
    ]


def cell_range_text(day_entries) -> tuple:
    """달력 칸에 적을 `(배당금 문구, 배당수익률 문구)`.

    🔴 평균을 만들지 않습니다 — 그 날 어느 종목에도 해당하지 않는 숫자라서요. 종목이
       하나면 그 값을 그대로, 여럿이면 **실제로 존재하는 최소~최대**만 적습니다
       (`dividend_us_logic.value_range` 주석 참고).
    """
    dps_min, dps_max = value_range(day_entries, 'dps')
    yield_min, yield_max = value_range(day_entries, 'div_yield')

    if dps_min is None:
        dps_text = ''
    elif dps_min == dps_max:
        dps_text = f'💵 ${fmt_num(dps_min, digits=2)}(연간)'
    else:
        dps_text = f'💵 ${fmt_num(dps_min, digits=2)}~${fmt_num(dps_max, digits=2)}(연간)'

    if yield_min is None:
        yield_text = ''
    elif yield_min == yield_max:
        yield_text = f'📈 {fmt_num(yield_min, digits=2)}%'
    else:
        yield_text = f'📈 {fmt_num(yield_min, digits=2)}~{fmt_num(yield_max, digits=2)}%'

    return dps_text, yield_text


def matches_query(item, query) -> bool:
    """검색어(회사명 한글·영문·티커). 빈 검색어는 **항상 전체 노출**입니다."""
    text = str(query or '').strip().lower()
    if not text:
        return True
    haystack = ' '.join(str(item.get(field) or '') for field in ('symbol', 'name', 'name_kr'))
    return text in haystack.lower()


# =============================================================================
# 2. 페이지
# =============================================================================
@ui.page('/dividend/us', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def dividend_us_page() -> None:
    """공개 화면 — 로그인 불필요(사용자별 데이터가 전혀 없습니다, §0-3-8)."""
    with layout('🇺🇸 미국 배당 달력', width_class='max-w-6xl'):
        ui.markdown('## 🇺🇸 미국 배당 달력')

        # 🚧 이중 방어 — 메뉴(`web/layout.py`)와 **같은 상수**를 보고 판단합니다.
        #    메뉴에 안 보이는데 URL 로는 열리는 상태가 생기지 않습니다(§0-3-6).
        if not DIVIDEND_US_ENABLED:
            warning_banner(COMING_SOON_TEXT)
            return
        if DIVIDEND_US_MENU_ADMIN_ONLY and not is_admin():
            warning_banner(COMING_SOON_TEXT)
            return

        await _render_body()


async def _render_body() -> None:
    """데이터 로드 → 정직성 고지 → 달력 → 배당 없음 목록.

    ⚠️ 파일 읽기는 반드시 **비동기판**입니다. 동기 `load_json_file()` 을 `@ui.page` 안에서
       부르면 이벤트 루프를 붙잡아 다른 화면을 보던 접속자까지 전부 끊깁니다
       (2026-08-21 사고 — `web/state.py` 의 긴 주석).
    """
    payload, load_error = await load_json_file_async(data_path(DATA_FILENAME))

    # ── §0-1 회귀 지점 — 스냅샷이 없으면 숫자를 하나도 그리지 않습니다 ──────
    if not isinstance(payload, dict):
        error_banner(
            '🚨 미국주식 스냅샷을 불러오지 못했습니다. '
            f'({load_error or "파일 형식이 예상과 다릅니다."})\n\n'
            '가짜 기본값으로 달력을 채우지 않기 위해 아무 수치도 표시하지 않습니다.'
        )
        return

    metadata = payload.get('metadata') or {}
    stocks = payload.get('stocks') or []
    if not stocks:
        error_banner(
            '🚨 미국주식 스냅샷에 종목이 0건입니다.\n\n'
            '자동 수집(GitHub Actions)이 정상적으로 끝났는지 확인이 필요합니다. '
            '값을 지어내지 않고 여기서 멈춥니다.'
        )
        return

    today = today_et()
    data = build_view_data(stocks, today)

    _render_data_timestamp(metadata)
    _render_summary(data)

    # ── 🔴 정직성 고지 — 달력을 보기 **전에** 반드시 읽어야 하는 것 ─────────
    warning_banner(CALENDAR_SOURCE_NOTICE)
    warning_banner(DATA_ORIGIN_NOTICE)
    warning_banner(DPS_ANNUAL_NOTICE)
    warning_banner(TAX_NOTICE)

    # ── 🔵 오늘은 며칠(미국 동부 시간) ────────────────────────────────────
    today_weekday_label = WEEKDAY_LABELS[(today.weekday() + 1) % 7]
    ui.html(
        f'<div style="text-align:center; margin: 4px 0 16px 0; padding: 14px 20px; '
        f'background: rgba(30, 58, 138, 0.35); border: 2px solid {TODAY_HIGHLIGHT_COLOR}; '
        f'border-radius: 10px;">'
        f'<span style="font-size: 1.25rem; font-weight: 900; '
        f'color: {TODAY_HIGHLIGHT_COLOR}; line-height: 1.4;">'
        f'📅 미국 현지 기준 오늘은 {today.year}년 {today.month}월 {today.day}일 '
        f'({today_weekday_label})이에요</span>'
        f'<div style="font-size: 0.8rem; color:#cbd5e1; margin-top:6px;">'
        f'{esc(TODAY_TIMEZONE_NOTE)}</div>'
        f'</div>'
    ).classes('w-full')

    # ── ⏰ 매수 마지막 날 규칙 — **미래 날짜가 하나라도 있을 때만** ──────────
    #    과거 날짜만 있는 상태에서 "사세요"라고 크게 띄우면 안 됩니다(§0-1).
    if data['future_count']:
        ui.html(
            f'<div style="text-align:center; margin: 0 0 16px 0; padding: 16px 20px; '
            f'background: rgba(20, 83, 45, 0.35); border: 2px solid {FUTURE_COLOR}; '
            f'border-radius: 10px;">'
            f'<span style="font-size: 1.5rem; font-weight: 900; color: {FUTURE_COLOR}; '
            f'line-height: 1.4;">{esc(BUY_DEADLINE_WARNING)}</span>'
            f'<div style="font-size: 0.85rem; color:#cbd5e1; margin-top:8px;">'
            f'아직 안 지난 배당락일이 {data["future_count"]:,}종목 있어요. '
            f'각 종목의 "매수 마지막 날"은 날짜를 눌러서 확인하세요 — 그 값은 이 화면이 '
            f'배당락일에서 계산한 값이라 🧮 배지를 달아 두었습니다.</div>'
            f'</div>'
        ).classes('w-full')

    # ── 상태는 전부 이 함수의 지역 변수입니다 (§0-3-8) ─────────────────────
    months = available_months(data['entries'], today)
    view = {
        'year': today.year,
        'month': today.month,
        'selected_date': None,
        'day_page': 1,
        'none_page': 1,
        'query': '',
    }

    def _visible_entries():
        return [e for e in data['entries'] if matches_query(e, view['query'])]

    def _visible_no_dividend():
        return [s for s in data['no_dividend'] if matches_query(s, view['query'])]

    def _on_filter_changed() -> None:
        view['selected_date'] = None       # 검색어가 바뀌면 고른 날짜의 목록도 달라집니다
        view['day_page'] = 1
        view['none_page'] = 1
        _calendar_section.refresh()
        _day_section.refresh()
        _none_section.refresh()

    with ui.row().classes('w-full items-end gap-4'):
        def _on_query(event) -> None:
            view['query'] = (event.value or '').strip()
            _on_filter_changed()

        ui.input('🔍 종목명 / 티커 검색', placeholder='예: 코카콜라, KO, Realty',
                 on_change=_on_query).props('clearable').style('flex: 1 1 320px;')

    ui.separator()

    @ui.refreshable
    def _calendar_section() -> None:
        _render_calendar(view, _visible_entries(), len(data['entries']), months, today,
                         on_changed=_calendar_section.refresh,
                         on_day_changed=lambda: _day_section.refresh())

    @ui.refreshable
    def _day_section() -> None:
        _render_selected_day(view, _visible_entries(), on_changed=_day_section.refresh)

    _calendar_section()
    _day_section()

    ui.separator()

    _render_unparsed(data)

    @ui.refreshable
    def _none_section() -> None:
        _render_no_dividend(view, _visible_no_dividend(), len(data['no_dividend']),
                            on_changed=_none_section.refresh)

    _none_section()
    disclaimer_footer()


# =============================================================================
# 3. 데이터 기준 시각 · 요약 카드
# =============================================================================
def _render_data_timestamp(metadata) -> None:
    """§0-3-1 — "실시간"이라는 말을 쓰지 않고 **수집 시각**을 그대로 밝힙니다."""
    kst = (metadata or {}).get('last_updated_at_kst')
    et = (metadata or {}).get('last_updated_at_et')
    if not kst and not et:
        # 시각을 모르면 '지금'으로 위장하지 않습니다(§0-1).
        warning_banner(
            '⚠️ 데이터 기준 시각이 스냅샷에 없습니다. 아래 값이 언제 수집된 것인지 이 '
            '화면에서는 확인할 수 없습니다.'
        )
        return
    parts = []
    if kst:
        parts.append(f'한국 시간 {kst}')
    if et:
        parts.append(f'미국 동부 시간 {et}')
    ui.label('🕒 데이터 기준 시각 — ' + ' · '.join(parts) +
             ' (실시간이 아니라 이 시각의 스냅샷입니다)').classes('vh-muted')


def _render_summary(data) -> None:
    """요약 카드 — **모든 종목이 어느 칸에 들어갔는지** 합이 맞게 보여줍니다.

    "배당 없음 확인"과 "날짜를 못 읽음"을 각각 별도 카드로 둡니다. 두 숫자를 합치거나
    빼버리면 "전체 548인데 달력엔 왜 403뿐이지?"라는 질문에 화면이 답을 못 합니다(§0-1).
    """
    with ui.row().classes('w-full flex-wrap gap-3'):
        metric_card('화면 대상 종목', f'{data["visible_count"]:,}개',
                    '상위 시가총액 추적 종목')
        metric_card('배당락일이 있는 종목', f'{len(data["entries"]):,}개',
                    '달력에 찍히는 건수')
        metric_card('🟢 아직 안 지난 날짜', f'{data["future_count"]:,}개',
                    '지금부터 준비 가능')
        metric_card('⚪ 이미 지난 날짜뿐', f'{data["past_count"]:,}개',
                    '다음 배당은 아직 발표 안 됨')
        metric_card('배당 없음이 확인됨', f'{len(data["no_dividend"]):,}개',
                    '"아직 모름"과 다른 상태')
        metric_card('날짜를 못 읽음', f'{len(data["unparsed"]):,}개',
                    '달력에서 제외 · 아래에 사유')
        if data['unknown_status']:
            metric_card('상태값을 모름', f'{len(data["unknown_status"]):,}개',
                        '수집기 값이 바뀐 듯')


# =============================================================================
# 4. 달력 격자
# =============================================================================
def _render_calendar(view, entries, total_entries, months, today,
                     on_changed, on_day_changed) -> None:
    """월 이동 줄 + 달력 격자.

    🟡 한국 배당 화면과 달리 **연도를 걸쳐 이동**합니다(배당락일이 2025~2027년에 걸쳐
       있습니다). 오갈 수 있는 달의 범위는 데이터가 실제로 덮는 구간이고, 그 계산은
       `dividend_us_logic.available_months()` 한 곳에서만 합니다.

    ⚠️ 칸의 건수는 **지금 검색어를 통과한 종목만** 셉니다. 검색 중이면 그 사실을 바로
       아래 줄에 적습니다 — 안 적으면 데이터가 사라진 것처럼 보입니다(§0-1).
    """
    if not months:
        info_banner('ℹ️ 달력에 표시할 배당락일이 한 건도 없습니다.')
        return

    year, month = view['year'], view['month']
    if (year, month) not in months:
        # 오늘이 데이터 범위 밖이면(예: 스냅샷이 오래된 경우) 조용히 튕기지 않고 가장
        # 가까운 끝으로 붙인 뒤, 아래 건수 줄에서 "이번 달은 비어 있다"고 밝힙니다.
        year, month = months[-1] if (year, month) > months[-1] else months[0]
        view['year'], view['month'] = year, month

    index = months.index((year, month))

    def _go(target_index):
        def _handler(_event=None) -> None:
            view['year'], view['month'] = months[target_index]
            view['selected_date'] = None
            view['day_page'] = 1
            on_changed()
            on_day_changed()
        return _handler

    with ui.row().classes('w-full items-center gap-2'):
        if index > 0:
            ui.button('◀ 이전 달', on_click=_go(index - 1)).props('flat dense no-caps')

        def _on_month(event) -> None:
            picked = event.value
            # 🟡 L8(2026-08-29) 추가 — 한국 배당 화면의 같은 자리
            # (`_render_calendar`)는 `not 0 <= picked < len(months)`를 방어선으로 두는데
            # 여기는 없었습니다. 지금은 `choices`의 키가 항상 `0..len(months)-1`이라
            # 실제로 범위 밖 값이 오지 않지만, 방어선이 한쪽에만 있는 비대칭을 없앱니다.
            if picked is None or not 0 <= picked < len(months):
                return
            view['year'], view['month'] = shift_month(*months[0], picked)
            view['selected_date'] = None
            view['day_page'] = 1
            on_changed()
            on_day_changed()

        # 선택기 값은 "목록의 첫 달로부터 몇 달 뒤인가"라는 정수입니다 — 튜플을 값으로
        # 쓰면 NiceGUI 가 그대로 직렬화하지 못해서, 정수 하나로 바꿔 넘깁니다.
        choices = {offset: month_label(*pair) for offset, pair in enumerate(months)}
        ui.select(choices, value=index, label='보는 달',
                  on_change=_on_month).style('flex: 0 0 220px;')
        if index < len(months) - 1:
            ui.button('다음 달 ▶', on_click=_go(index + 1)).props('flat dense no-caps')

    month_total = count_in_month(entries, year, month)
    ui.label(f'📌 {month_label(year, month)}에 배당락일이 잡힌 종목: {month_total:,}건') \
        .classes('vh-muted')
    if month_total == 0:
        # (클래스는 `vh-muted vh-keep-all` 만 씁니다 — 이 둘은 `web/theme.py` 에 실제로
        #  정의돼 있는 것을 확인했습니다. 정의 없는 클래스명을 적어두면 나중에 "왜 스타일이
        #  안 먹지"로 시간을 씁니다.)
        ui.label('📭 이번 달은 배당락일이 잡힌 종목이 없어요 — 위 "보는 달"로 다른 달을 '
                 '보실 수 있습니다.').classes('vh-muted vh-keep-all')

    if len(entries) != total_entries:
        ui.label(
            f'🔎 검색 중 — 달력의 건수는 검색어를 통과한 종목만 셉니다 '
            f'(전체 {total_entries:,}건 중 {len(entries):,}건).'
        ).classes('vh-muted')

    grouped = group_by_ex_date(entries)

    def _pick(key):
        def _handler(_event=None) -> None:
            view['selected_date'] = None if view['selected_date'] == key else key
            view['day_page'] = 1
            on_changed()
            on_day_changed()
        return _handler

    today_cell_style = f'border: 2px solid {TODAY_HIGHLIGHT_COLOR}; border-radius: 8px;'
    today_in_view = (today.year, today.month) == (year, month)

    with ui.grid(columns=7).classes('w-full gap-1'):
        for label in WEEKDAY_LABELS:
            ui.label(label).classes('text-center text-xs font-bold opacity-60')
        for week in month_weeks(year, month):
            for day in week:
                if not day:
                    ui.label('').classes('text-center')
                    continue
                is_today = today_in_view and day == today.day
                key = date_key(year, month, day)
                day_entries = grouped.get(key, ())
                if not day_entries:
                    # 건수가 0인 날도 오늘이면 테두리가 보여야 합니다 — 오늘 강조는 배당
                    # 건수와 무관한 "지금 이 시점" 표시이기 때문입니다.
                    empty_cell = ui.label(str(day)).classes('text-center vh-muted py-2')
                    if is_today:
                        empty_cell.style(today_cell_style)
                    continue

                selected = view['selected_date'] == key
                is_future_cell = any(e['is_future'] for e in day_entries)
                dps_text, yield_text = cell_range_text(day_entries)
                cell_color = FUTURE_COLOR if is_future_cell else PAST_COLOR

                day_cell = ui.column().classes('w-full gap-0 items-stretch')
                if is_today:
                    day_cell.style(today_cell_style)
                with day_cell:
                    mark = '🟢' if is_future_cell else '⚪'
                    button = ui.button(f'{mark} {day}일 · {len(day_entries):,}건',
                                       on_click=_pick(key)).classes('w-full')
                    button.props('unelevated no-caps dense color=primary' if selected
                                 else 'flat no-caps dense')
                    if dps_text:
                        ui.label(dps_text).classes('text-center text-xs') \
                            .style(f'color:{cell_color}; font-weight:700;')
                    if yield_text:
                        ui.label(yield_text).classes('text-center text-xs') \
                            .style(f'color:{cell_color}; font-weight:700;')

    # 🔵/🟢/⚪ 가 무슨 뜻인지 격자 바로 아래에 항상 적습니다 — 색만 두고 뜻을 안 적으면
    #    그건 화면이 아니라 암호입니다.
    ui.label('🟢 아직 안 지난 배당락일 · ⚪ 이미 지난 배당락일 · 🔵 파란 테두리는 오늘'
             '(미국 동부 시간) · 💵 그 날 종목들의 주당 배당금 범위(연간 합계, 이 날 받는 '
             '금액 아님) · 📈 배당수익률 범위'
             ).classes('vh-muted vh-keep-all')


# =============================================================================
# 5. 고른 날짜의 종목 목록
# =============================================================================
def _render_selected_day(view, entries, on_changed) -> None:
    """고른 날짜의 종목 표(없으면 안내만). 표는 페이지로 나눠 그립니다."""
    key = view.get('selected_date')
    if not key:
        ui.label('👆 달력에서 건수가 있는 날짜를 누르면 그 날짜의 종목 목록이 여기에 '
                 '펼쳐집니다.').classes('vh-muted')
        return

    day_entries = group_by_ex_date(entries).get(key, [])
    if not day_entries:
        info_banner('ℹ️ 지금 걸린 검색어로는 이 날짜에 표시할 종목이 없습니다.')
        return

    has_future = any(e['is_future'] for e in day_entries)
    ui.markdown(f'#### 📅 {key} 배당락일 — {len(day_entries):,}개 종목')
    if has_future:
        ui.label('이 날부터 사면 이번 배당은 받지 못합니다. 아래 "매수 마지막 날"까지 '
                 '사 두셔야 이번 배당을 받습니다(🧮 표시는 이 화면이 계산한 값이라는 '
                 '뜻입니다).').classes('vh-muted vh-keep-all')
    else:
        ui.label('이 날짜는 이미 지났습니다 — 기록으로만 보여드리는 값이고, 이 종목들의 '
                 '다음 배당 날짜는 아직 발표되지 않았습니다(우리가 예측해서 채우지 '
                 '않습니다).').classes('vh-muted vh-keep-all')

    total_pages = max(1, (len(day_entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    current_page = min(view['day_page'], total_pages)
    view['day_page'] = current_page
    start = (current_page - 1) * ITEMS_PER_PAGE

    ui.html(holdings_table_html(
        list(DAY_HEADERS),
        [day_row_cells(entry) for entry in day_entries[start:start + ITEMS_PER_PAGE]],
    )).classes('w-full')

    if total_pages > 1:
        def _on_page(page: int) -> None:
            view['day_page'] = page
            on_changed()

        pager(total_pages, current_page, _on_page)


# =============================================================================
# 6. 날짜를 못 읽은 종목 · 배당 없음이 확인된 종목
# =============================================================================
def _render_unparsed(data) -> None:
    """⚠️ 파싱 실패를 **조용히 스킵하지 않습니다** — 0건이면 0건이라고 밝힙니다(§0-1)."""
    unparsed = data['unparsed']
    unknown = data['unknown_status']
    if not unparsed and not unknown:
        ui.label('✅ 배당 데이터가 있는 종목의 배당락일 글자는 모두 정상적으로 '
                 '읽혔습니다(읽지 못한 종목 0건).').classes('vh-muted')
        return

    if unparsed:
        warning_banner(f'{UNPARSED_NOTICE_HEAD} (지금 {len(unparsed):,}건)')
        with ui.expansion(f'⚠️ 배당락일을 읽지 못한 종목 {len(unparsed):,}건 보기') \
                .classes('w-full'):
            ui.html(holdings_table_html(
                ['종목 (티커)', '원문 값', '읽지 못한 이유'],
                # 원문 값이 None 이면 빈 칸이 아니라 "(값 없음)"이라고 적습니다 — 빈 칸은
                # "우리가 지웠나?"로 읽히지만, 이건 소스가 준 그대로의 상태입니다.
                [[stock_name_html(stock),
                  f'<code>{esc(stock.get("ex_dividend_date"), fallback="(값 없음)")}</code>',
                  f'<span style="color:#fbbf24;">{esc(reason or "원인 미상")}</span>']
                 for stock, reason in unparsed],
            )).classes('w-full')

    if unknown:
        warning_banner(
            f'⚠️ 배당 상태값이 "collected"도 "confirmed_none"도 아닌 종목이 '
            f'{len(unknown):,}건 있습니다. 수집기가 값을 늘렸을 수 있어, 이 종목들을 '
            '배당이 있는 것처럼도 없는 것처럼도 취급하지 않고 따로 세어 둡니다.'
        )


def _render_no_dividend(view, stocks, total, on_changed) -> None:
    """🔴 "배당 없음이 확인된 종목" — 달력·미확정과 **절대 섞이지 않는** 별도 구획."""
    ui.markdown(f'### 🚫 배당 없음이 확인된 종목 ({total:,}개)')
    ui.label(NO_DIVIDEND_NOTICE).classes('vh-muted vh-keep-all whitespace-pre-line')

    if not stocks:
        if total:
            info_banner('ℹ️ 지금 걸린 검색어로는 표시할 종목이 없습니다.')
        return

    with ui.expansion(f'🚫 목록 보기 ({len(stocks):,}개)').classes('w-full'):
        total_pages = max(1, (len(stocks) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        current_page = min(view['none_page'], total_pages)
        view['none_page'] = current_page
        start = (current_page - 1) * ITEMS_PER_PAGE

        ui.html(holdings_table_html(
            list(NO_DIVIDEND_HEADERS),
            [no_dividend_row_cells(s) for s in stocks[start:start + ITEMS_PER_PAGE]],
        )).classes('w-full')

        if total_pages > 1:
            def _on_page(page: int) -> None:
                view['none_page'] = page
                on_changed()

            pager(total_pages, current_page, _on_page)
