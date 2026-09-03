"""
💰 투자 감사합니다! — 배당 캘린더 (공개 화면, URL `/dividend`).

배당금 모듈(6번째 모듈, `DIVIDEND_MODULE_WORK_ORDER.md`)의 **첫 화면**입니다. 읽는 것은
`data/dividend_kr_2026_latest.json`(DART 정기보고서 기반 2026년 수집분)과
`data/dividend_history_kr_2023_2025.json`(KIND 연간 집계 기준선) **두 파일뿐**이고,
아무것도 저장하지 않으며 로그인도 필요 없습니다(pegy·us_stocks 와 같은 성격의 공개 시세
화면 — §0-3-8 관점에서 사용자 데이터가 흐르는 경로 자체가 없습니다).

-------------------------------------------------------------------------------
🔴 이 화면이 **사실대로** 말해야 하는 것 세 가지 (§0-1)
-------------------------------------------------------------------------------
① **달력의 날짜는 배당금 지급일이 아닙니다.** 캘린더가 쓰는 날짜는 각 레코드의
   `stlm_dt` — 그 정기보고서가 다루는 회계기간의 **결산기준일**입니다(1분기=03-31,
   반기=06-30, 3분기=09-30, 사업보고서=12-31). DART 정기보고서의 "배당에 관한 사항"에는
   **지급일·배당락일 정보가 아예 없습니다.** 그래서 이 사실을 툴팁 한 개로 숨기지 않고
   달력 바로 위에 **상시 배너**로 띄웁니다(`CALENDAR_DATE_NOTICE`).
   ⚠️ `data/dividend_history_kr_2023_2025.json` 의 `stock_dividend_record_date` 로 진짜
      날짜를 만들 수 있지 않을까 싶겠지만 **안 됩니다** — 8,202건 중 56건에만 값이 있고,
      그 값도 `"0.02 / (2023-12-31)"` 같은 잡음이라 날짜로 쓸 수 없습니다(실측 확인).
      이 화면은 그 필드를 읽지 않습니다.
② **이번 수집 대상은 "전 상장사"가 아닙니다.** 2026년 수집은
   `data/dividend_history_kr_2023_2025.json`(= 2023~2025년에 배당 이력이 있던 종목
   2,734개)을 유니버스로 돌았습니다. 2026년 신규 상장사나 올해 처음 배당하는 회사는
   **조회 자체가 시도되지 않았습니다**(`DIVIDEND_MODULE_WORK_ORDER.md` [항목 1] — 전 종목
   목록 `data/kr_ticker_master.json` 으로 교체하는 일은 다음 단계로 남아 있습니다).
   그래서 화면 맨 위에서 "전체 상장사"라고 말하지 않고 대상 수와 상태별 내역을 그대로
   보여줍니다. `summary.known_limitations` 세 문장도 접이식으로 원문 그대로 싣습니다.
③ **배당수익률은 DART 원문값을 그대로 씁니다.** 이 화면에는 현재가 데이터가 없어
   (DPS ÷ 현재가)로 다시 계산할 수단 자체가 없고, 계산해서 원문값을 **대체**하는 것은
   금지입니다. 대신 분기·반기보고서의 수익률이 누적과 정합하지 않을 수 있다는 수집기의
   경고(`yield_reliability_note`)를 수익률 옆 배지+툴팁으로 그대로 노출합니다.

-------------------------------------------------------------------------------
🔴 "작년 배당율입니다" 폴백 (§0-1 예시 4 — Forward Fill)
-------------------------------------------------------------------------------
`status == "OK" and dps_cash_common is not None` 인 종목만 "2026년 배당 확정"입니다.
나머지 전부는 **달력에 넣지 않고**(2026년 날짜가 없으니까) 달력 아래 별도 목록에 두고,
`data/dividend_history_kr_2023_2025.json` 에서 같은 종목의 **가장 최근 연도** 확정
배당을 보여줍니다. 그때
  · 화면에는 "2025년 배당율입니다" 처럼 **실제로 쓴 연도**를 붙이고,
  · 표시용 dict 에도 `data_quality` / `dividend_basis_year` 를 함께 남깁니다.
    화면 문구가 언젠가 사라져도 "이 값이 몇 년 것인지"가 데이터에 남아야 하기 때문입니다
    (`DIVIDEND_MODULE_WORK_ORDER.md` §3 "작년 배당율입니다 표시" 조항).
세 해(2025→2024→2023) 어디에도 배당액이 없으면 **"데이터 없음"** 입니다 — 0 원으로
그리지 않습니다("무배당"과 "값을 모른다"는 다른 말입니다).

⚠️ "가장 최근 연도"는 **배당액이 실제로 있는 가장 최근 연도**입니다. 기준선 파일은
   2023·2024·2025 세 해 모두에 같은 종목의 행을 만들어 두고 배당이 없던 해는
   `dps_krw = null` 로 둡니다(실측: 2025년 행 2,734건 중 1,492건이 null). 그래서 무조건
   2025년 행을 집으면 2024년에 배당한 회사가 전부 "데이터 없음"이 됩니다.

-------------------------------------------------------------------------------
🟣 우선주(優先株) 현금배당 — 있는 회사에만 붙는 줄 (§0-1)
-------------------------------------------------------------------------------
수집기는 처음부터 보통주와 **우선주** 배당을 따로 담아 왔습니다(`dps_cash_preferred` ·
`dps_cash_preferred_all` · `cash_yield_preferred`). 그런데 이 화면은 그동안 보통주 칸만
그려서, **이미 가지고 있는 값이 화면에는 없는 상태**였습니다(실측 2,734건 중 21건 —
그중 20건이 확정분, 1건은 보통주 배당이 없어 미확정 목록에 있는 종목).
그래서 달력 상세 표의 "주당 현금배당금"·"배당수익률" 칸 **아래 한 줄**로 함께 적습니다.
  · 두 숫자를 절대 합치거나 섞지 않습니다 — 우선주 줄에는 항상 "우선주"라고 이름을 붙이고,
    그 줄이 붙는 순간 위의 숫자에도 "보통주"라고 이름을 붙입니다.
  · 우선주가 없는 대다수 종목의 칸은 **글자 하나까지 지금까지와 같습니다**(빈 줄·빈 칸을
    만들지 않습니다 — 없는 것을 "없음"이라고 그리면 2,700건에 잡음만 늘어납니다).
  · 🔴 우선주가 2종 이상이고 배당금이 서로 다르면 수집기는 대표값(`dps_cash_preferred`)을
    **일부러 비우고**(None) 후보를 `dps_cash_preferred_all` 에만 남깁니다
    (실측: 아모레퍼시픽홀딩스 002790 = [405.0, 667.0]). 대표값만 보면 하필 그 회사가 화면에서
    통째로 사라지므로, 이 화면은 두 필드를 합쳐서 보고 후보를 **전부** 나열합니다
    ("우선주 2종: 405원, 667원"). 하나를 골라 대표인 척 보여주지 않습니다.
  · 확정/미확정 판정은 예전 그대로 **보통주 기준**입니다(아래 참고). 우선주 배당만 확인된
    종목이 그것 때문에 "확정"으로 올라오는 일은 없고, 그런 건수는 요약 줄에 숫자로 밝힙니다.

-------------------------------------------------------------------------------
🔴 상태 관리 · 세션 격리 (§0-3-8)
-------------------------------------------------------------------------------
"지금 보고 있는 달 / 고른 날짜 / 검색어 / 시장 / 페이지"는 전부 `_render_body()` 안의
지역 dict(`view`) 하나에만 있습니다. NiceGUI 는 한 프로세스가 모든 접속자를 처리하므로,
모듈 전역에 두면 **다른 사람이 달을 넘기면 내 화면이 바뀝니다.** 이 파일의 모듈 최상위에는
문자열·튜플 상수만 있습니다(가변 전역 0개 —
`tests/test_web_session_isolation.py::test_no_mutable_globals` 가 매번 확인).

-------------------------------------------------------------------------------
🔴 XSS (§0-3-9)
-------------------------------------------------------------------------------
이 화면이 그리는 문자열은 회사명·시장·사유 문구·파싱 메모까지 **거의 전부 DART/KIND 가
준 값**이고 우리가 만든 값이 아닙니다. HTML 로 나가는 자리는 예외 없이 `esc()` 를
거칩니다("종목코드는 숫자니까 괜찮다" 같은 판단을 코드에 남기지 않습니다).
`dart_url` 은 `href` 에 들어가므로 `esc()` 에 더해 **스킴까지 확인**합니다 — `esc()` 는
따옴표를 막아 속성 탈출은 막지만 `javascript:` 를 막지는 못하기 때문입니다.

-------------------------------------------------------------------------------
🚧 공개 게이트 (§0-3-6 — 오너 승인 전 기본 숨김)
-------------------------------------------------------------------------------
    DIVIDEND_ENABLED          … 이 모듈 전용 스위치(환경변수, 기본 꺼짐)
    DIVIDEND_MENU_ADMIN_ONLY  … 2단계(관리자 전용) ↔ 3단계(전체 공개)
값의 출처는 `web/layout.py` **한 곳**입니다. 메뉴와 이 화면이 같은 상수를 보므로,
메뉴에 안 보이는데 URL 로는 열리는 상태가 생기지 않습니다(이중 방어 — 결투/성적표가 이미
밟은 것과 같은 순서·같은 패턴, §0-3-10).

-------------------------------------------------------------------------------
📌 후행지표 전용 (§0-3-1)
-------------------------------------------------------------------------------
"실시간"이라는 말을 쓰지 않습니다. 화면에 보이는 값은 전부 **수집 시점의 스냅샷**이고,
그 시각(`summary.generated_at_kst`)을 "데이터 기준 시각"으로 맨 위에 밝힙니다.
"""

import calendar as calendar_module
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import Request
from nicegui import ui

from web.auth import is_admin
from web.components import (
    NA_TEXT,
    disclaimer_footer,
    download_button,
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
from web.layout import DIVIDEND_ENABLED, DIVIDEND_MENU_ADMIN_ONLY, layout
from web.static_html import (
    SITE_TITLE,
    crawler_response,
    is_known_crawler,
    notice_box,
    remaining_note,
    render_document,
    table_html,
)
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file_async,
    read_download_bytes,
)

# =============================================================================
# 상수 — 전부 문자열/튜플(불변)입니다. 가변 전역(dict/list/set)은 하나도 두지 않습니다(§0-3-8).
# =============================================================================
DATA_FILENAME = 'dividend_kr_2026_latest.json'

#: 크롤러용 정적 HTML 에 표로 싣는 확정 배당 건수(보통주 주당배당금 내림차순 상위).
CRAWLER_TABLE_ROWS = 30

CRAWLER_META_DESCRIPTION = (
    'DART 정기보고서(2026년)와 KIND 연간 집계(2023~2025)를 바탕으로 한 한국 상장사 배당 캘린더. '
    '결산기준일별 확정 배당(보통주 주당 현금배당금·배당수익률)과 아직 미확정인 종목의 작년 배당 '
    '참고값을 보여줍니다. 실제 지급일·배당락일이 아닌 결산기준일 기준이며, 종목 추천이 아닙니다.'
)
RAW_FILENAME = 'dividend_kr_2026_raw.jsonl'
HISTORY_FILENAME = 'dividend_history_kr_2023_2025.json'

#: 🔴 M9/S5(2026-08-29) 추가 — `RAW_FILENAME`은 **append-only**라 재실행마다 커집니다
#: (실측: 2026-08-24 9.4MB → 2026-08-29 18.5MB, 5일 만에 거의 2배 — `PROJECT_STATUS.md`
#: §11-4 5번). NiceGUI 다운로드 버튼(`download_button`)은 파일 전체를 메모리에 올려
#: 브라우저로 보내는데, 이 크기가 계속 커지면 다른 접속의 이벤트 루프까지 함께 막힐
#: 위험이 있습니다(2026-08-21 접속 끊김 사고와 같은 유형). 그래서 상한을 두고, 상한을
#: 넘으면 다운로드 버튼 대신 GitHub 저장소 링크로 안내합니다(파일이 사라지는 게 아니라
#: 받는 경로만 바뀝니다 — 이 저장소는 공개(public)라 로그인 없이 그대로 받을 수
#: 있습니다, §0-1 — 못 받게 막는 게 아니라 다른 경로를 그대로 알려 줍니다).
RAW_DOWNLOAD_MAX_BYTES = 50 * 1024 * 1024  # 50MB — 실측치(18.5MB)의 약 2.7배 여유

#: `PROJECT_STATUS.md` §0-2 확인 값(`github.com/moonbear135/visible-hand-dashboard`,
#: public repo, 기본 브랜치 main).
GITHUB_REPO_BLOB_BASE = (
    'https://github.com/moonbear135/visible-hand-dashboard/blob/main/data'
)

#: 🟢 2026-08-25 추가 — DART 수시공시("현금ㆍ현물배당결정")를 매일 감시해 모은 **진짜
#: 지급일정**(배당기준일·지급예정일자). `collector_dividend_payment_kr.py` 가 만드는 파일로,
#: 위 세 파일(정기보고서 기반)과는 데이터 출처·수집 코드가 **완전히 분리**돼 있습니다.
#: 이 파일이 아직 없거나(첫 실행 전) 읽기 실패해도 달력 자체는 예전과 똑같이 그려집니다 —
#: 있으면 "실제 지급일정" 배지만 추가로 붙는, 순수하게 덧붙는 정보입니다(아래
#: `build_payment_event_index` · `payment_badge_html`).
PAYMENT_EVENTS_FILENAME = 'dividend_kr_2026_payment_events.json'

#: 한 페이지에 그릴 표 행 수(달력 상세·미확정 목록 공통).
ITEMS_PER_PAGE = 50

#: 달력 요일 머리글 — **일요일 시작**(`calendar.Calendar(firstweekday=6)` 와 짝).
WEEKDAY_LABELS = ('일', '월', '화', '수', '목', '금', '토')

#: 달력에서 고른 날짜의 종목 표 열 제목.
CONFIRMED_HEADERS = (
    '회사명 (종목코드)', '시장', '주당 현금배당금 (해당 보고서까지 누적)',
    '배당수익률 (DART 원문)', '근거 보고서', '결산기준일', '원문 공시',
)

#: "아직 2026년 배당 미확정 (작년 참고)" 표 열 제목.
PENDING_HEADERS = (
    '회사명 (종목코드)', '시장', '기준 연도', '주당 배당금', '배당수익률', '2026년 상태',
)

#: 시장 필터의 "전체"(기본값). 실제 시장 구분은 데이터에 있는 값에서만 뽑습니다.
MARKET_ALL = '전체 (코스피 · 코스닥 · 코넥스)'
MARKET_UNKNOWN = '시장 구분 없음'

#: 표시용 dict 의 `data_quality` 값 — 화면 문구가 아니라 **데이터에 남는 근거**입니다.
QUALITY_CONFIRMED = 'CONFIRMED_THIS_YEAR'
QUALITY_PREVIOUS = 'PREVIOUS_YEAR_FALLBACK'
QUALITY_NONE = 'NO_DIVIDEND_DATA'

#: 🔴 달력 날짜의 의미 — 툴팁이 아니라 **상시 배너**로 띄웁니다(위 머리말 ①).
#: 2026-08-24 — 오너 피드백("연령대가 다양하고 남녀노소가 섞여 있으니 쉬운 말로") 반영해
#: "결산기준일"·"stlm_dt" 같은 용어 없이 쉬운 말로 다시 씀. 뜻은 한 글자도 안 바뀜 —
#: 여전히 "지급일이 아니다" + "왜 이 날짜만 있는지" + "그래서 있는 날짜만 쓴다"는 §0-1
#: 세 가지를 그대로 담습니다.
CALENDAR_DATE_NOTICE = (
    '📅 이 달력의 날짜는 "배당금 받는 날"이 아니에요!\n'
    '회사가 실적을 마감한 날짜(예: "6월 30일까지의 장사 결과")를 기준으로 '
    '"배당을 이만큼 하겠다"고 발표했다는 뜻이에요. 그날 통장에 돈이 들어온다는 뜻이 '
    '아닙니다.\n'
    '실제로 돈이 들어오는 날짜나 배당락일(배당받을 자격이 없어지는 날)은 이 화면이 보는 '
    '자료(DART 공시)에 아예 나와 있지 않아요 — 그래서 모르는 날짜를 지어내지 않고, '
    '확실히 아는 날짜(회사가 실적을 마감한 날)만 보여드려요.'
)

#: 🔴 2026-08-25 — 오너 요청: "배당락일 전까지 매수해야 배당금을 받을 수 있습니다"를 큰
#: 글자로 상시 노출. 위 `CALENDAR_DATE_NOTICE`(달력 날짜=결산기준일이라는 안내) 바로 아래,
#: 달력 격자 바로 위에 둡니다 — 달력을 보기 직전에 가장 먼저 눈에 들어와야 하는 실전 행동
#: 요령이라 접이식 안내 패널이 아니라 상시 배너로 둡니다(CALENDAR_DATE_NOTICE와 같은 원칙).
#: 배당락일 색(PAYMENT_EX_COLOR)과 맞춰 이 문구도 같은 🔴 개념임을 색으로도 알립니다.
EX_DATE_BUY_DEADLINE_WARNING = '⏰ 배당락일 전까지 매수해야 배당금을 받을 수 있어요!'

#: 🔴 유니버스 정직성 고지 — "전체 상장사"라고 말하지 않습니다(위 머리말 ②).
UNIVERSE_NOTICE = (
    '🎯 이번 2026년 수집은 "코스피·코스닥·코넥스 전 상장사"가 아니라, '
    '2023~2025년 KIND 연간 배당 집계 파일에 실려 있던 종목만을 대상으로 했습니다.\n'
    '따라서 2026년에 새로 상장했거나 그 파일에 없던 회사는 이 화면에 아예 나오지 않습니다 '
    '— 조회 자체가 시도되지 않았습니다.\n'
    '전 종목 목록(data/kr_ticker_master.json)으로 대상을 넓히는 작업은 아직 하지 않았고 '
    '다음 단계로 남아 있습니다. "빠진 것이 있다"는 사실을 숨기지 않으려고 여기 적어 둡니다.\n'
    '※ 그 파일에는 해당 3년간 배당액 기록이 아예 없는 회사도 함께 실려 있습니다. '
    '그런 종목은 아래 목록에서 "데이터 없음"으로 나옵니다 — 무배당이라고 단정하지 않습니다.'
)

#: "아직 2026년 배당 미확정" 목록이 무엇인지.
PENDING_SECTION_NOTICE = (
    '아래 종목들은 2026년 배당이 아직 확정되지 않았습니다(정기보고서에 배당 표가 없거나, '
    '수집이 실패했습니다).\n'
    '그래서 달력에는 넣지 않았습니다 — 넣을 2026년 날짜 자체가 없기 때문입니다.\n'
    '대신 KIND 연간 집계(2023~2025)에서 그 종목의 가장 최근 확정 배당을 보여드립니다. '
    '이 값은 **지난 연도의 확정치**이며 2026년 배당에 대한 예상치가 아닙니다.'
)

#: 배당수익률 옆 경고 배지의 제목(본문은 레코드의 `yield_reliability_note` 원문).
YIELD_WARN_LABEL = '⚠️ 원문값'

#: 🔴 M5(2026-08-29) 추가 — "주당 현금배당금" 칸이 어느 보고서에서 왔는지("근거 보고서"
#: 칸)에 따라 **같은 종목이라도 성격이 다른 숫자**입니다. 1분기보고서는 1분기분만, 3분기
#: 보고서는 1~3분기 **누적**을 담습니다(DART 정기보고서 "배당에 관한 사항"의 원문 관행).
#: 열 제목에 "(해당 보고서까지 누적)"을 넣는 것만으로는 "그래서 종목끼리 못 비교한다"는
#: 결론까지는 안 보이므로, 상시 안내로 한 번 더 명시적으로 밝힙니다(§0-3-13).
CUMULATIVE_DPS_NOTICE = (
    '🧮 "주당 현금배당금"은 해당 보고서가 다루는 회계기간 **누적** 금액입니다 — 1분기보고서면 '
    '1분기분만, 3분기보고서면 1~3분기 누적, 사업보고서면 1년 전체 누적입니다("근거 보고서" '
    '칸에서 어느 보고서인지 확인할 수 있습니다).\n'
    '그래서 서로 다른 "근거 보고서"를 가진 두 종목의 이 숫자를 그대로 비교하면 안 됩니다 — '
    '3분기보고서(9개월 누적)와 1분기보고서(3개월분)를 나란히 비교하면 실제로는 배당 규모가 '
    '비슷하거나 더 작은 회사가 훨씬 많이 주는 것처럼 보일 수 있습니다.'
)

#: 🔴 M7(2026-08-29) 추가 — 표의 모든 금액은 **세전**인데 그 사실을 어디에도 적지
#: 않았습니다. 국내 배당소득세율은 기본 15.4%(지방소득세 포함)이지만 배당소득이 많아
#: 금융소득종합과세 대상이 되면 사람마다 실제 세율이 달라져서, 이 화면이 일괄 세율을
#: 곱해 "세후 예상액"을 계산해 보여드리면 그 자체가 틀린 안내가 될 수 있습니다(§0-1)
#: — 그래서 계산하지 않고, 세전 금액이라는 사실만 명확히 밝힙니다(미국 배당 화면의
#: `dividend_us_page.TAX_NOTICE`와 같은 원칙, §0-3-10).
TAX_NOTICE = (
    '💸 이 화면의 모든 배당금액(주당 현금배당금 등)은 **세전** 금액입니다. 국내 배당소득에는 '
    '원천징수세(기본 15.4% — 소득세 14% + 지방소득세 1.4%)가 붙는데, 실제 입금액은 이보다 '
    '적습니다.\n'
    '배당소득을 포함한 금융소득이 연 2천만원을 넘으면 금융소득종합과세 대상이 되어 세율이 '
    '더 높아질 수 있습니다 — 개인마다 다른 세율을 이 화면이 일괄 적용해 세후 예상액을 계산해 '
    '보여드리지는 않습니다. 정확한 세후 금액은 증권사 앱이나 세무 전문가를 통해 확인해 주세요.'
)

#: DART 원문 수익률을 우리가 다시 계산하지 않는 이유.
YIELD_SOURCE_NOTICE = (
    '배당수익률은 DART 정기보고서에 적힌 원문값을 그대로 싣습니다. '
    '이 화면에는 현재가 데이터가 없어 (주당배당금 ÷ 현재가)로 다시 계산할 수단이 없고, '
    '계산값으로 원문값을 대체하지도 않습니다.\n'
    '분기·반기보고서의 수익률은 주당배당금이 누적으로 늘어도 갱신되지 않는 사례가 실측으로 '
    f'확인됐습니다 — 그래서 수익률 옆에 "{YIELD_WARN_LABEL}" 배지를 달고 수집기가 남긴 경고 '
    '문구를 그대로 보여드립니다.'
)

#: 🟣 우선주 줄에 붙는 이름표. 두 숫자를 절대 합치지 않으므로 **양쪽 다** 이름을 답니다.
PREFERRED_LABEL = '우선주'
COMMON_LABEL = '보통주'

#: 우선주 줄의 인라인 스타일(보통주 값보다 작고 연보라 — 다른 종류의 주식임을 색으로도 구분).
PREFERRED_LINE_STYLE = (
    'margin-top: 3px; font-size: 12px; font-weight: 700; color: #c4b5fd; '
    'white-space: normal; overflow-wrap: anywhere;'
)

#: 우선주가 여러 종류라 수집기가 대표값을 정하지 못했을 때 다는 배지 제목.
PREFERRED_MULTI_LABEL = '❔ 대표값 미정'

#: 🟣 "왜 어떤 줄에만 우선주가 보이지?" 를 미리 답해 두는 문구(요약 카드 바로 아래).
PREFERRED_NOTICE = (
    '🟣 우선주 현금배당은 DART 원문에 값이 있는 회사에만 보통주 배당 아래 한 줄로 함께 적습니다. '
    '대부분의 회사는 우선주가 없어 이 줄이 나오지 않습니다 — 빠뜨린 것이 아니라 원문에 없는 것입니다.\n'
    '보통주와 우선주는 주당 배당금이 다를 수 있어 한 숫자로 합치지 않고, 항상 "보통주"·"우선주"라고 '
    '이름을 붙여 따로 적습니다.\n'
    '우선주가 2종 이상이라 수집기가 대표값을 하나로 정하지 못한 경우에는 후보 값을 전부 나열합니다 '
    '— 그중 하나만 골라 대표인 척 보여주지 않습니다.'
)

#: 🟢 "실제 지급일정" 배지 제목. 우려·경고가 아니라 **긍정적인 추가 정보**라 파란(정보)
#: 배지(`info_badge`)를 씁니다 — 다만 안에는 아래 `PAYMENT_BADGE_TOOLTIP_INTRO` 로
#: "결산기준일과는 다른 별개 공시"라는 사실을 먼저 밝힙니다(§0-1 — 두 날짜를 섞어 읽지
#: 않도록).
PAYMENT_BADGE_LABEL = '💰 실제 지급일정 확인됨'

#: 🟢 2026-08-25 — 달력 격자에 배당기준일ㆍ지급예정일을 **직접 표시**할 때 쓰는 색.
#: 오너 요청: "툴팁 말고 달력에 표시해달라". 결산기준일(파란·기존 색과 무관)과 헷갈리지
#: 않도록, 이미 쓰던 앰버(경고)·블루(정보) 배지 색과도 겹치지 않는 새 색 두 개를 씁니다.
PAYMENT_RECORD_COLOR = '#fcd34d'   # 🟡 배당기준일(원문 라벨 그대로)
PAYMENT_DATE_COLOR = '#4ade80'     # 🟢 지급예정일(실제 돈이 들어오는 날짜)
PAYMENT_EX_COLOR = '#f87171'       # 🔴 배당락일 — 이 화면이 직접 계산한 값(아래 참고)

#: 🔵 2026-08-27 — 오너 요청: "저기 배당락일 전까지 매수해주세요 저거 잘보여서 좋아 /
#: 저런 느낌으로 오늘이 몇월몇일인지도 보여주면 좋을 거 같아". 즉 위 배당락일 경고 배너와
#: 같은 "큰 박스" 방식으로 **오늘 날짜**도 알려달라는 요청입니다. 오늘은 경고가 아니라
#: 기준점(정보)이라, 이미 뜻이 정해진 위 세 색(🟡 기준일ㆍ🟢 지급일ㆍ🔴 락일)과는 절대
#: 겹치지 않는 네 번째 색을 씁니다 — 파란 계열(Tailwind blue-400). 이 색은 오늘 배너와
#: 달력 격자의 "오늘 칸" 테두리 **두 곳에서만** 쓰여, 파란 테두리를 보면 곧 "오늘"이라고
#: 읽히게 합니다.
TODAY_HIGHLIGHT_COLOR = '#60a5fa'  # 🔵 오늘(KST) — 날짜 종류가 아니라 "지금 이 시점" 표시

#: 🔴 2026-08-25 — 오너가 "배당락일 하고 지급예정일 둘 다 표시하자"고 요청. 배당락일은
#: DART 원문에 없는 값이라(배당기준일만 있음) **이 화면이 직접 계산**합니다 — 값을 만드는
#: 자리라 "🧮 계산값" 배지(§0-1 예시2-보충 — 계산값은 허용하되 반드시 표시)를 붙입니다.
#: 실제 검증한 연도 목록은 `KRX_VERIFIED_YEARS`(아래 "1. 순수 함수" 절)에 있습니다 —
#: 이 문구는 그 상수를 가리키기만 하고 직접 나열하지 않습니다(같은 사실을 두 곳에 따로
#: 적으면 나중에 한쪽만 갱신해 어긋날 수 있으므로, §0-3-10과 같은 취지).
#: 🔴 이 문자열은 우리가 직접 쓴 신뢰된 HTML입니다(외부 값 아님) — 그래서 `<br>`을 그대로
#: 넣습니다. 호출부에서 `esc()`를 씌우지 않습니다(다른 배지 본문들과 같은 관례 —
#: `preferred_dps_html()`의 `PREFERRED_MULTI_LABEL` 배지 본문 참고).
EX_DATE_CALC_NOTE = (
    '배당락일은 DART 원문에 없는 값이라 이 화면이 직접 계산합니다 — 배당기준일의 '
    '1영업일 전(한국거래소 휴장일 제외)입니다. 배당기준일 자체가 개장일이 아니면 그 '
    '직전 개장일을 실제 기준일로 보정한 뒤 다시 1영업일을 뺍니다.<br>'
    '⚠️ 휴장일 표는 확인된 연도만 있습니다 — 그 밖의 연도는 계산하지 않고 값을 비웁니다'
    '(추측 금지).'
)

#: 🔴 L11(2026-08-29) 추가 — 미국 배당 화면(`dividend_us_page.LAST_BUY_CALC_NOTE`)에는
#: "매수 마지막 날"이 있는데 이 화면(한국)에는 없었습니다(비대칭). 배당락일 자체가 이미
#: `ex_dividend_date()`로 계산한 값이니, 그 배당락일의 1영업일 전을 한 번 더 계산하면
#: 됩니다 — 새 계산 규칙이 아니라 같은 규칙을 한 번 더 적용하는 것뿐입니다.
LAST_BUY_CALC_NOTE_KR = (
    '"매수 마지막 날"은 소스에 없는 값이라 이 화면이 직접 계산합니다 — 배당락일의 '
    '<b>직전 한국거래소 개장일</b>입니다(주말·휴장일 제외).<br>'
    '배당락일 당일에 사면 이번 배당은 받지 못하기 때문에, 하루 앞의 거래일이 실제 '
    '마감입니다.<br>'
    '⚠️ 휴장일 표는 확인된 구간만 있습니다 — 그 밖의 날짜는 계산하지 않고 비웁니다'
    '(추측 금지).'
)

#: 배지 툴팁 맨 앞에 항상 붙는 문구 — 이 표의 "결산기준일"과 이 배지의 "배당기준일"이
#: **서로 다른 공시에서 온 서로 다른 날짜**임을 매번 밝힙니다. 같은 배당을 가리키는지는
#: 이 화면이 판정하지 않습니다(정기보고서와 수시공시를 서로 잇는 근거가 없습니다).
PAYMENT_BADGE_TOOLTIP_INTRO = (
    '이 종목에 대해 DART에 접수된 "배당 지급일정" 수시공시(현금ㆍ현물배당결정)입니다. '
    '표의 "결산기준일"(정기보고서 기준)과는 다른 별개의 공시라서, 아래 배당기준일이 '
    '같은 줄의 결산기준일과 반드시 같은 배당을 가리키는 것은 아닙니다.'
)

#: 접이식 패널에 싣는 배경 설명 — 배지 자체가 없는 화면에서도 "왜 어떤 종목에만 이 배지가
#: 붙는지"를 미리 답해 둡니다(PREFERRED_NOTICE 와 같은 취지).
PAYMENT_NOTICE = (
    '💰 "실제 지급일정" 표시 — 위 달력 격자에서 🟡 배당기준일ㆍ🟢 지급예정일이 있는 날짜에는 '
    '작은 표시가 붙고, 그 날짜를 누르면 아래에 회사명ㆍ금액ㆍ원문 링크가 **바로(툴팁 없이)** '
    '펼쳐집니다. 달력 상세 표와 아래 "미확정" 목록의 종목명 옆에도 같은 정보를 담은 배지가 '
    '붙습니다. 이건 정기보고서가 아니라 DART 수시공시("현금ㆍ현물배당결정")를 매일 감시해 '
    '따로 모은 정보로, 달력의 날짜(결산기준일, 정기보고서 기준)와는 **서로 다른 공시**입니다 '
    '— 같은 배당을 가리키는지는 이 화면이 판정하지 않고, 그런 공시가 있었다는 사실만 그대로 '
    '보여드립니다.\n'
    '🔴 "배당기준일"은 원문 라벨 그대로이며 **배당락일이 아닙니다.** DART 원문에는 배당락일이 '
    '없어서, 대신 이 화면이 배당기준일의 1영업일 전(한국거래소 휴장일 제외)으로 **직접 '
    '계산**해 세 번째 색(🔴)으로 달력에 같이 표시합니다 — 계산값이라는 사실은 "🧮 계산값" '
    '배지로 항상 따로 표시하고, 확인 안 된 연도는 값을 만들어내지 않고 비워둡니다'
    '(2026-08-25 추가).\n'
    '🔴 "미확정" 목록에도 이 표시가 붙는 경우가 있습니다 — 정기보고서 기준으로는 아직 2026년 '
    '배당이 확정되지 않았어도, DART 수시공시로 실제 배당기준일ㆍ지급예정일자가 먼저 나오는 '
    '경우가 실제로 있었습니다(2026-08-25 첫 실행에서 실측). 그래서 확정 표ㆍ미확정 목록ㆍ달력 '
    '격자 세 곳 모두에 같은 정보를 담습니다.\n'
    '아직 모든 종목을 다 확인한 것이 아니라서, 표시가 없다고 지급일정이 없다는 뜻은 '
    '아닙니다 — 매일 새 공시를 확인하며 채워지는 중입니다. "지급예정일자"는 법적으로 확정 '
    '지급일이 아니라 상법상 지급 기한(통상 1개월 이내)이라는 점도 DART 원문에 그대로 '
    '적혀 있어, 원문 링크로 직접 확인할 수 있게 해 두었습니다.'
)

COMING_SOON_TEXT = (
    '🚧 "투자 감사합니다!"(배당 캘린더)는 아직 준비중입니다.\n\n'
    '데이터 검수가 끝나고 오너 승인이 나면 열립니다. 그때까지는 아무 수치도 그리지 않습니다.'
)


# =============================================================================
# 1. 순수 함수 — NiceGUI 위젯을 하나도 만들지 않습니다
#    (그래서 nicegui 없이도 이 함수들만 따로 불러 검증할 수 있습니다 — 관심사 분리)
# =============================================================================
def to_int(value):
    """숫자로 못 읽으면 **0 으로 때우지 않고** None (§0-1)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    """위와 같은 이유로, 못 읽으면 None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_confirmed_this_year(record) -> bool:
    """🔴 "올해 배당이 실제로 확정됐다"의 **단 하나의 판정 기준**.

    `status == "OK"` 만으로는 부족합니다 — OK 는 "정기보고서를 찾아 표를 읽었다"는 뜻이고,
    그중 대부분(실측 2,417건)은 배당 표 자체가 없어 보통주 주당배당금이 None 입니다.
    """
    data = record or {}
    return data.get('status') == 'OK' and data.get('dps_cash_common') is not None


def preferred_cash_values(record):
    """레코드 1건 → 우선주 주당 현금배당금 후보 **전부**(중복 없이, 원문 순서대로) 튜플.

    🔴 대표값(`dps_cash_preferred`) 하나만 보면 안 되는 이유가 실측으로 있습니다. 수집기는
       우선주가 2종 이상이고 값이 서로 다르면 **대표값을 일부러 None 으로 비우고** 후보를
       `dps_cash_preferred_all` 에만 남깁니다
       (`tests/test_dividend_collector.py::test_parse_refuses_to_pick_when_preferred_classes_disagree`,
       실측 데이터: 아모레퍼시픽홀딩스 002790 = [405.0, 667.0]).
       그래서 "대표값이 None 이면 우선주 없음"으로 읽으면, 하필 **우선주가 여러 종류라 가장
       설명이 필요한 회사**가 화면에서 통째로 사라집니다. 두 필드를 합쳐서 봅니다(§0-1).

    같은 값이 두 번 온 경우(우선주 2종이 동액)는 한 번만 담습니다 — 중복은 다양성이
    아니어서, "2종: 1,700원, 1,700원" 은 정보가 아니라 잡음입니다.

    :return: 함수 지역 튜플(값이 하나도 없으면 빈 튜플).
    """
    data = record or {}
    values = []
    for raw in data.get('dps_cash_preferred_all') or ():
        number = to_float(raw)
        if number is not None and number not in values:
            values.append(number)
    single = to_float(data.get('dps_cash_preferred'))
    if single is not None and single not in values:
        values.append(single)
    return tuple(values)


def count_with_preferred(entries) -> int:
    """표시용 dict 목록 중 **우선주 배당 줄이 실제로 붙는** 건수(요약 줄에 그대로 씁니다)."""
    return sum(1 for entry in entries or [] if entry.get('dps_preferred_all'))


def build_payment_event_index(payload):
    """`dividend_kr_2026_payment_events.json` → `{종목코드: [이벤트, ...]}`.

    🔴 `stock_code` 가 없는 이벤트(수집기가 6자리로 정규화하지 못한 건)는 이 화면의 어느
       종목과도 이을 수 없어 색인에 넣지 않습니다 — 산출물 파일 자체에는 `stock_code_raw`
       로 그대로 남아 있으니(수집기 §0-1), 사라지는 것이 아니라 이 화면만 못 씁니다.
    한 종목에 이벤트가 여러 건(분기배당을 여러 번 했거나 `[기재정정]` 정정이 있는 경우)이면
    **전부** 담습니다 — 하나만 골라 대표인 척 보여주지 않습니다(`preferred_cash_values` 와
    같은 원칙). 접수일ㆍ접수번호 오름차순(먼저 있었던 공시가 먼저 나오도록)으로 정렬합니다.

    :return: 함수 지역 dict (모듈 전역이 아닙니다 — §0-3-8). 파일이 없거나 형식이 예상과
        다르면(`payload` 가 dict 가 아니면) 빈 dict — 호출부가 "배지를 그릴 수 없을 뿐,
        달력 자체는 그대로 그린다"는 뜻으로 씁니다.
    """
    index = {}
    for record in (payload or {}).get('records') or []:
        code = str((record or {}).get('stock_code') or '').strip()
        if not code:
            continue
        index.setdefault(code, []).append(record)
    for code, events in index.items():
        events.sort(key=lambda item: (str(item.get('rcept_dt') or ''),
                                      str(item.get('rcept_no') or '')))
    return index


def next_dividend_event(events, today):
    """한 종목의 지급일정 이벤트 목록 → **앞으로 다가올 배당 1건**(없으면 None).

    2026-09-03 추가(오너 요청: "다음 배당 일정 정도는 연결을 같이 할 수 있지 않을까",
    "기재 정정 공시도 어느정도 따라갈 수 있지 않을까"). 국내 종목 스코어카드 화면
    (`web/pages/pegy_page.py`)의 카드에 "다음 배당 일정" 보조 한 줄을 붙이려고 만들었습니다.
    배당 캘린더 화면은 `payment_badge_html()` 처럼 한 종목의 이벤트를 **전부** 나열할 자리가
    있지만, 스코어카드 카드에는 그럴 자리가 없어 **화면이 대표 1건을 골라야만** 합니다.
    그 고르는 규칙을 카드 렌더링 코드 안에 흩어 놓지 않고 여기 순수 함수 한 곳에 모읍니다
    (§0-3-10 · §4-3 — 화면 파일이 데이터 판단 로직을 각자 새로 짓지 않기).

    🔴 이건 **원본 데이터의 판단이 아니라 화면이 만든 선택 규칙**입니다. 산출물 파일
       (`dividend_kr_2026_payment_events.json`)은 스스로 "'현재 배당 상태'가 아니라 '접수된
       배당결정 공시 이벤트의 로그'이고, `[기재정정]` 공시는 원본과 별개 레코드로 함께
       남으며, **어느 것이 최종본인지는 이 파일이 판단하지 않는다**"고
       `summary.known_limitations` 에 못박아 두었습니다(수집기
       `collector_dividend_payment_kr.py` 도 같은 문장을 씁니다). 즉 최종본 판정은 화면
       몫이라는 설계이고, 이 함수가 그 몫을 맡습니다. 그래서 호출부는 고른 1건이 "그 종목
       배당의 전부"처럼 보이지 않도록 전체 이력이 배당 캘린더 화면에 있다는 안내를 함께
       띄웁니다.

    규칙 (셋 다 §0-1 — 모르는 것을 아는 척하지 않기):
      ① `record_date`(배당기준일)가 `today` **이상**인 이벤트만 후보입니다. 오늘이 기준일인
         건은 아직 오늘 안에 남아 있는 일정이라 **포함**합니다(경계값 — 테스트로 고정).
         `record_date` 가 없거나 형식을 못 읽으면(`parse_iso_date()` 가 None) "언제인지
         모른다"는 뜻이라 후보에서 뺍니다 — 아무 날짜나 가정해 채우지 않습니다.
      ② 같은 `record_date` 에 여러 건이 있으면(전형적으로 원본 + `[기재정정]` 정정본)
         **가장 나중에 접수된 것**이 그 날짜의 대표입니다. 정정본이 있는데 정정 전 원본을
         보여주면 그 자체가 틀린 안내입니다. `build_payment_event_index()` 가 이미 접수일ㆍ
         접수번호 오름차순으로 정렬해 주지만, 정렬이 보장되지 않은 목록이 들어와도 같은
         답이 나오도록 **여기서 한 번 더** 같은 키로 정렬한 뒤 고릅니다(호출부의 정렬
         상태에 조용히 기대지 않기 — 이 함수만 따로 불러도 규칙이 성립해야 합니다).
      ③ 그렇게 남은 날짜별 대표 중 `record_date` 가 **가장 이른** 1건을 돌려줍니다.

    ⚠️ 자회사 대리공시(`is_subsidiary_notice`)는 여기서 **거르지 않습니다.** 수집기가
       "공시 주체(corp_name/stock_code)와 실제 배당하는 회사가 다를 수 있다"고 밝힌
       건인데, 골라내 버리면 정보가 통째로 사라지고(§0-1) 반대로 아무 말 없이 보여주면
       오해를 부릅니다. 그래서 이 함수는 그대로 돌려주고, **그 사실을 화면에 밝히는 일은
       호출부**가 맡습니다(`_payment_event_notes_html()` 이 이미 캘린더 화면에서 하듯이).

    :param events: 한 종목의 이벤트 리스트(`build_payment_event_index()` 의 값). None 이나
        빈 목록이면 그대로 None 을 돌려줍니다(그 종목엔 보조 줄이 안 붙습니다).
    :param today: 기준일(`date`). 이 함수는 시계를 직접 읽지 않습니다 — 호출부가
        `today_kst()` 로 만들어 넘깁니다(서버 시간대에 기대지 않기 + 테스트에서 날짜 고정).
    :return: 이벤트 dict 1건(**원본 그대로** — 값을 가공하지 않습니다) 또는 후보가 없으면
        None.
    """
    ordered = sorted(
        events or (),
        key=lambda item: (str((item or {}).get('rcept_dt') or ''),
                          str((item or {}).get('rcept_no') or '')),
    )
    # 함수 지역 dict 입니다(모듈 전역이 아닙니다 — §0-3-8). 오름차순으로 넣으면서 같은
    # 키를 계속 덮어쓰므로, 같은 배당기준일에서는 **마지막(=가장 나중 접수)** 건만 남습니다.
    representative = {}
    for event in ordered:
        record_date = parse_iso_date((event or {}).get('record_date'))
        if record_date is None or record_date < today:
            continue
        representative[record_date] = event
    if not representative:
        return None
    return representative[min(representative)]



# =============================================================================
# 🔴 KRX 휴장일 표 — 배당락일 계산용
# =============================================================================
#: 2026-08-25 조사(오너 요청: "배당락일도 계산해서 넣어줘 — 이건 추측이 아니라 계산").
#:
#: 방법: 먼저 `exchange_calendars`(XKRX 캘린더) 라이브러리로 정기 휴장일(설날·추석·
#: 대체공휴일 등)을 뽑았습니다. 그런데 **라이브러리를 그대로 믿지 않고** 뉴스 검색으로
#: 교차확인했더니, 2026년 실제 휴장일 중 라이브러리에 **빠진 게 2건** 있었습니다:
#: 6월 3일(전국동시지방선거)ㆍ7월 17일(제헌절 — "관공서의 공휴일에 관한 규정" 개정으로
#: 2026년부터 법정 공휴일 부활, 그래서 라이브러리가 만들어질 때는 반영이 안 됐던 것으로
#: 보임). 이 두 건은 아래 표에 수동으로 더했습니다.
#:
#: 출처:
#:   · 정기 휴장일(15일) — `exchange_calendars` XKRX 캘린더(v4.13.2) 산출값
#:   · 6/3 지방선거 휴장 — https://v.daum.net/v/20260520202735219 ,
#:     https://news.nate.com/view/20260520n12457
#:   · 7/17 제헌절 휴장(2026년 신설) — 위 두 기사와 동일 출처
#:   · 배당락일=배당기준일의 1영업일 전 규칙, 배당기준일이 휴장일일 때의 보정(직전
#:     개장일로 대체 후 다시 1영업일) — https://kbthink.com/investment/101/dividend-date.html ,
#:     https://blog.koreainvestment.com (두 곳 모두 같은 규칙·같은 예시로 확인)
#:
#: ⚠️ **이 표는 2025년 12월ㆍ2026년만 검증했습니다.** 다른 해에 이 계산이 필요해지면
#: 반드시 같은 방식(라이브러리 + 뉴스 교차확인)으로 다시 조사해서 채워야 합니다 — 채우지
#: 않은 해에 대한 계산은 `is_krx_trading_day()`가 **일부러 예외를 던져** 조용히 틀린 값을
#: 내지 않습니다(§0-1 — 확인 안 된 걸 확인한 척하지 않기).
# 🔴 2026-08-25 추가 — 위 표가 검증 안 된 연도로 넘어가기 전에 미리 시끄럽게 경고합니다
#    (2027-01-01 부터는 is_krx_trading_day() 가 ValueError 를 던지며 멈추는데, 그 전까지
#    아무도 미리 알려주지 않는 게 문제였습니다). 마감 60일 전부터 서버 로그(Render)에
#    찍히기 시작합니다. 실제 매일 도는 배당 배치(`collector_dividend_payment_kr.py`)에도
#    같은 알람을 별도로 걸어 뒀습니다(이 파일은 nicegui 를 물고 있어 배치가 직접
#    import 할 수 없어서 `utils/expiry_alarms.py` 로 로직만 공유합니다).
from utils.expiry_alarms import KRX_VERIFIED_LAST_YEAR, warn_if_expiring

#: 🔴 L5(2026-08-29) 수정 — 마지막 검증 연도는 `utils/expiry_alarms.KRX_VERIFIED_LAST_YEAR`
#: 한 곳에서만 관리합니다(collector_dividend_payment_kr.py 도 같은 값을 봅니다) — 여기서
#: 숫자를 다시 적지 않는 것 자체가 "두 곳에 같은 사실을 적지 않기"(§0-3-10)의 목적입니다.
KRX_VERIFIED_YEARS = (KRX_VERIFIED_LAST_YEAR - 1, KRX_VERIFIED_LAST_YEAR)

#: 🔴 H5(2026-08-29) 수정 — 예전 게이트(`is_krx_trading_day`)는 **연도 단위**로만 막았습니다.
#: 그런데 위 주석이 스스로 밝히듯 표는 "2025년 전체"가 아니라 **2025년 12월 두 날짜뿐**입니다.
#: 연도 게이트로는 `2025-01-01`(신정)·`2025-05-05`(어린이날) 같은 날짜가 전부 "개장일"로
#: 조용히 오판됐습니다(실측 확인 — H5). 이제 게이트는 **표가 실제로 덮는 날짜 구간**으로
#: 검사합니다. 이 구간을 넓히려면(예: 2025년 전체를 채우면) 이 튜플과 위
#: `KRX_HOLIDAYS_2025_2026` 을 함께 넓히세요 — 한쪽만 넓히면 다시 이번과 같은 틈이 생깁니다.
KRX_VERIFIED_RANGE = (date(2025, 12, 1), date(KRX_VERIFIED_LAST_YEAR, 12, 31))

warn_if_expiring('배당락일 계산용 KRX 휴장일 표 (dividend_page.py: KRX_VERIFIED_YEARS)',
                 KRX_VERIFIED_LAST_YEAR)

KRX_HOLIDAYS_2025_2026 = frozenset((
    # 2025년 12월 — 2026년 초 배당기준일의 역산 여유분으로만 확보(2025년 전체 표는 아님)
    '2025-12-25', '2025-12-31',
    # 2026년 (정기 휴장일 15일 + 뉴스로 별도 확인한 2일 = 17일)
    '2026-01-01',
    '2026-02-16', '2026-02-17', '2026-02-18',
    '2026-03-02',
    '2026-05-01', '2026-05-05', '2026-05-25',
    '2026-06-03',   # 전국동시지방선거 — 라이브러리엔 없었음, 뉴스로 별도 확인
    '2026-07-17',   # 제헌절(2026년 부활) — 라이브러리엔 없었음, 뉴스로 별도 확인
    '2026-08-17',
    '2026-09-24', '2026-09-25',
    '2026-10-05', '2026-10-09',
    '2026-12-25', '2026-12-31',
))


def is_krx_trading_day(d) -> bool:
    """`date` → 그 날이 KRX 개장일인가(주말 아님 + 위 표에 없음).

    :raises ValueError: `d`가 `KRX_VERIFIED_RANGE`(표가 실제로 덮는 구간) 밖이면 — 확인 안
        된 날짜를 "아마 열렸겠지"로 조용히 넘기지 않기 위해서입니다(§0-1, H5).
    """
    start, end = KRX_VERIFIED_RANGE
    if not (start <= d <= end):
        raise ValueError(
            f'{d.isoformat()} 은 KRX 휴장일 표가 확인된 구간({start.isoformat()} ~ '
            f'{end.isoformat()}) 밖입니다 — 배당락일을 계산할 수 없습니다(값을 추측하지 '
            '않습니다).'
        )
    if d.weekday() >= 5:      # 5=토, 6=일 (`date.weekday()`: 월=0 … 일=6)
        return False
    return d.isoformat() not in KRX_HOLIDAYS_2025_2026


def previous_krx_trading_day(d):
    """`d` 바로 이전의 KRX 개장일. 최대 14일 앞까지만 찾습니다(무한 루프 방지 — 그 안에
    개장일이 하나도 없다면 표 자체가 잘못됐다는 뜻이라 계속 찾지 않고 예외를 던집니다).

    :raises ValueError: `is_krx_trading_day()`와 같은 이유로 확인 안 된 해거나, 14일 안에
        개장일을 못 찾으면 예외를 던집니다.
    """
    cursor = d
    for _ in range(14):
        cursor = cursor - timedelta(days=1)
        if is_krx_trading_day(cursor):
            return cursor
    raise ValueError(f'{d.isoformat()} 이전 14일 안에서 KRX 개장일을 찾지 못했습니다 — '
                     '휴장일 표를 다시 확인해야 합니다.')


def ex_dividend_date(record_date_str):
    """배당기준일 문자열('YYYY-MM-DD') → `(배당락일, None)` 또는 계산 불가능하면
    `(None, 사람이 읽는 이유)`.

    규칙(2026-08-25, 2개 출처 교차확인 — 위 `KRX_HOLIDAYS_2025_2026` 주석 참고): 배당락일 =
    배당기준일의 **1영업일 전**. 배당기준일 자체가 개장일이 아니면(옛 관행 — 12월 31일을
    배당기준일로 쓰던 시절 등) 그 직전 개장일을 "실제 기준일"로 보정한 뒤 다시 1영업일을
    뺍니다(실제 사례로 확인된 보정 규칙).

    🔴 계산할 수 없으면(날짜 형식이 이상함, 확인 안 된 연도 등) **절대 아무 날짜나 돌려주지
    않습니다** — `(None, 이유)`를 돌려주고, 호출부는 그 종목의 배당락일 칸을 그냥 비웁니다
    (§0-1).
    """
    parsed = parse_iso_date(record_date_str)
    if parsed is None:
        return None, '배당기준일 형식을 읽지 못했습니다'
    try:
        effective = parsed if is_krx_trading_day(parsed) else previous_krx_trading_day(parsed)
        return previous_krx_trading_day(effective), None
    except ValueError as exc:
        return None, str(exc)


def last_buy_html_kr(ex_date, is_future) -> str:
    """🧮 매수 마지막 날 한 줄 — 배당락일(ex_date, `date` 또는 `None`) 기준으로 그 1영업일
    전을 계산합니다(L11, 2026-08-29). 미국 배당 화면의 `last_buy_html()`과 같은 원칙입니다.

    🔴 이미 지난 배당락일에는 날짜를 적지 않습니다 — 지난 날을 두고 "이때까지 사세요"라고
       쓰면 그 자체가 틀린 안내입니다(§0-1).
    🔴 계산이 불가능하면(확인 안 된 구간 등) 아무 날짜나 넣지 않고 이유를 그대로 적습니다.
    """
    if not is_future:
        return ('<div style="color:#94a3b8; font-size:12px; margin-top:4px;">'
                '이미 지난 배당락일이라 매수 안내를 하지 않습니다</div>')
    if ex_date is None:
        return ('<div style="color:#fbbf24; font-size:12px; margin-top:4px;">'
                '배당락일을 계산하지 못해 매수 마지막 날도 계산할 수 없습니다</div>')
    try:
        last_buy = previous_krx_trading_day(ex_date)
    except ValueError as exc:
        return f'<div style="color:#fbbf24; font-size:12px; margin-top:4px;">{esc(str(exc))}</div>'
    text = f'{last_buy.year}년 {last_buy.month}월 {last_buy.day}일'
    badge = warn_badge('🧮 계산값', LAST_BUY_CALC_NOTE_KR)
    return (f'<div style="color:{PAYMENT_FUTURE_COLOR}; font-weight:800; font-size:12px; '
            f'margin-top:4px;">🛒 매수 마지막 날: {esc(text)} 까지</div>{badge}')


def payment_event_summary_text(event) -> str:
    """지급일정 이벤트 1건 → 사람이 읽는 한 줄 요약(이스케이프 전, 순수 텍스트).

    `[기재정정]` 이면 맨 앞에 그대로 밝힙니다 — 정정 공시라는 사실을 지우고 원본인 척
    보여주지 않습니다(§0-1).

    🔴 2026-08-25 — "배당락일"을 맨 앞에 추가했습니다. DART 원문에는 없는, 이 화면이
    직접 계산한 값입니다(`ex_dividend_date()`) — 계산에 실패하면(확인 안 된 연도 등)
    조용히 "데이터 없음"으로 둡니다. 별도 "🧮 계산값" 배지는 HTML 렌더링 쪽
    (`payment_badge_html`·`payment_date_block_html`)에서 붙입니다 — 이 함수는 순수
    텍스트만 돌려줍니다.
    """
    data = event or {}
    record_date = data.get('record_date') or NA_TEXT
    pay_date = data.get('pay_date_expected') or NA_TEXT
    dps_text = fmt_num(to_float(data.get('dps_common')), '원', 0)
    ex_date, _reason = ex_dividend_date(data.get('record_date'))
    ex_text = ex_date.isoformat() if ex_date is not None else NA_TEXT
    text = (f'배당락일 {ex_text} · 배당기준일 {record_date} · 지급예정일 {pay_date} · '
            f'1주당 {dps_text}')
    if data.get('is_correction'):
        text = '[기재정정] ' + text
    return text


def build_payment_date_index(payload):
    """`dividend_kr_2026_payment_events.json` → `{'YYYY-MM-DD': {'record': [...], 'pay': [...],
    'ex': [...]}}`.

    2026-08-25 — 오너가 "배지를 툴팁 말고 달력에 바로 표시해달라"고 요청해 추가.
    `build_payment_event_index()`(종목코드 기준)와는 축이 다른 **날짜 기준** 색인입니다 —
    달력 격자에서 "이 날짜에 걸리는 이벤트가 있는가"를 바로 찾으려고 만들었습니다.

    🔴 `record`는 원문 라벨 그대로 **배당기준일**입니다 — "배당락일"과는 다른 날짜입니다.
       `ex`는 배당락일 축인데, 이건 DART 원문에 없어 `ex_dividend_date()`로 **직접
       계산**합니다(오너 요청, 2026-08-25). 계산이 안 되는 이벤트(확인 안 된 연도 등)는
       `ex` 축에만 조용히 빠집니다 — `record`ㆍ`pay` 축(원문 그대로)은 이미 그 위에서
       담겼으니 정보 자체가 사라지는 건 아닙니다.
    한 이벤트가 여러 축(배당락일·배당기준일·지급예정일)에 들어갈 수 있고(서로 다른
    날짜라면 서로 다른 칸에), 한 날짜에 여러 이벤트가 겹칠 수도 있어(여러 회사가 같은 날)
    전부 리스트로 담습니다. 날짜가 없거나 형식이 이상하면(파싱 실패) 그 축에는 안 넣습니다.

    :return: 함수 지역 dict (모듈 전역이 아닙니다 — §0-3-8).
    """
    index = {}

    def _bucket(date_str):
        return index.setdefault(date_str, {'record': [], 'pay': [], 'ex': []})

    for record in (payload or {}).get('records') or []:
        for field, kind in (('record_date', 'record'), ('pay_date_expected', 'pay')):
            date_str = str((record or {}).get(field) or '').strip()
            if not date_str or parse_iso_date(date_str) is None:
                continue
            _bucket(date_str)[kind].append(record)
        ex_date, _reason = ex_dividend_date((record or {}).get('record_date'))
        if ex_date is not None:
            _bucket(ex_date.isoformat())['ex'].append(record)
    return index


#: 🔴 H3(2026-08-29) 추가 — 지난 배당락일과 앞으로의 배당락일을 색으로 가르는 두 색.
#: 미국 배당 화면의 `FUTURE_COLOR`·`PAST_COLOR`와 **같은 값**입니다(§0-3-10 — 같은 뜻은
#: 같은 색으로). `PAYMENT_EX_COLOR`(🔴)는 "이게 배당락일 축이다"라는 종류를 나타내고,
#: 이 두 색은 "그 배당락일이 지났는가"라는 시간 축을 나타냅니다 — 서로 다른 질문이라 겹쳐
#: 씁니다(예: 지난 배당락일도 여전히 🔴 배당락일이지만, 글자색은 회색으로 죽입니다).
PAYMENT_FUTURE_COLOR = '#4ade80'   # 🟢 아직 안 지난 배당락일 — 지금부터 준비할 수 있음
PAYMENT_PAST_COLOR = '#94a3b8'     # ⚪ 이미 지난 배당락일 — 기록일 뿐, 행동할 게 없음


def count_future_ex_events(payment_date_index, today) -> int:
    """`payment_date_index`의 'ex'(배당락일) 축에서 오늘(포함) 이후 이벤트 건수.

    🔴 H3(2026-08-29) — "배당락일 전까지 매수하세요" 배너를 조건 없이 띄우면, 이전 달로
    넘겨 이미 지난 배당락일을 보고 있는 사용자에게도 그 배너가 앞으로의 마감처럼 읽힙니다
    (§0-1). 미국 배당 화면이 이미 이 판정(`dividend_us_logic.build_view_data`의
    `future_count`)을 하고 있어 같은 원칙을 한국 화면에도 이식합니다 — 배너는 이 건수가
    1건 이상일 때만, 그리고 건수를 함께 밝힙니다.
    """
    today_key = today.isoformat()
    return sum(len(bucket.get('ex') or ())
               for key, bucket in (payment_date_index or {}).items()
               if key >= today_key)


def market_group(label) -> str:
    """시장 문자열 → 필터용 묶음 키. **표시 문구는 바꾸지 않습니다.**

    2026 수집분은 한국어(`유가증권시장(KOSPI)`·`코스닥시장`·`코넥스시장`)로, 기준선 파일은
    영문(`KOSPI`/`KOSDAQ`/`KONEX`)으로 시장을 적습니다. 같은 시장이 두 이름으로 나뉘면
    필터가 쓸모없어지므로 **필터 키만** 키워드로 묶습니다 — 화면에 찍히는 글자는 원문
    그대로입니다(우리가 시장 이름을 새로 지어내지 않습니다).
    """
    text = str(label or '')
    upper = text.upper()
    if '코스닥' in text or 'KOSDAQ' in upper:
        return '코스닥'
    if '코넥스' in text or 'KONEX' in upper:
        return '코넥스'
    if '유가증권' in text or 'KOSPI' in upper:
        return '코스피'
    return MARKET_UNKNOWN


def build_history_index(payload):
    """기준선(2023~2025) → `{종목코드: 레코드}`.

    고르는 기준은 **배당액(`dps_krw`)이 실제로 있는 가장 최근 회계연도**입니다
    (2025 → 2024 → 2023). 세 해 모두 비어 있으면 그 종목은 아예 담지 않습니다 — 빈 값을
    담아 두면 호출부가 "값은 있는데 0 이다"로 착각할 수 있습니다.

    :return: 함수 지역 dict (모듈 전역이 아닙니다 — §0-3-8).
    """
    chosen = {}
    for row in (payload or {}).get('records') or []:
        code = str((row or {}).get('stock_code') or '').strip()
        if not code:
            continue
        if to_float(row.get('dps_krw')) is None:
            continue
        year = to_int(row.get('fiscal_year'))
        if year is None:
            continue
        current = chosen.get(code)
        if current is None or year > (to_int(current.get('fiscal_year')) or 0):
            chosen[code] = row
    return chosen


def display_entry(record, history_row):
    """레코드 1건 → **화면이 쓰는 표시용 dict**.

    확정분과 폴백분이 **같은 모양**을 갖도록 한 곳에서 만듭니다. 표시 문자열이 아니라 값을
    담고(서식은 그리는 쪽에서), `data_quality`·`dividend_basis_year` 로 "이 숫자가 어느
    해의 무엇인지"를 데이터에 함께 남깁니다(§0-1 · 작업지시서 §3).
    """
    data = record or {}
    history = history_row or {}
    code = str(data.get('stock_code') or '').strip()
    name = data.get('corp_name') or history.get('company_name') or '회사명 없음'
    market_text = data.get('market') or history.get('market') or MARKET_UNKNOWN
    confirmed = is_confirmed_this_year(data)

    if confirmed:
        return {
            'stock_code': code,
            'corp_name': name,
            'market_text': market_text,
            'market_key': market_group(market_text),
            'data_quality': QUALITY_CONFIRMED,
            'dividend_basis_year': to_int(data.get('bsns_year')),
            'dps_krw': to_float(data.get('dps_cash_common')),
            'dividend_yield_pct': to_float(data.get('cash_yield_common')),
            # 🟣 우선주는 **보통주 값과 절대 섞지 않고** 처음부터 다른 열쇠에 담습니다.
            'dps_preferred': to_float(data.get('dps_cash_preferred')),
            'dps_preferred_all': preferred_cash_values(data),
            'yield_preferred': to_float(data.get('cash_yield_preferred')),
            'yield_note': data.get('yield_reliability_note'),
            'settle_date': str(data.get('stlm_dt') or '').strip() or None,
            'report_name': data.get('reprt_name'),
            'dart_url': data.get('dart_url'),
            'status': data.get('status'),
            'status_reason': data.get('status_reason'),
            'parse_notes': tuple(data.get('parse_notes') or ()),
            # 🔴 H7(2026-08-29) 추가 — 수집기가 이미 §2-4 를 지키려고 남겨 둔 두 신호를
            # 이제 이 화면도 옮겨 담습니다(예전에는 `parse_notes` 만 옮겨서, 배지 인프라는
            # 있는데 이 두 필드만 화면에 한 번도 안 닿았습니다).
            'unit_mismatch_notes': tuple(data.get('unit_mismatch_notes') or ()),
            'cross_source_notes': tuple(data.get('cross_source_notes') or ()),
            'dps_unspecified': to_float(data.get('dps_cash_unspecified')),
            'value_source': 'DART 정기보고서 원문 (alotMatter.json)',
        }

    dps = to_float(history.get('dps_krw'))
    basis_year = to_int(history.get('fiscal_year')) if dps is not None else None
    return {
        'stock_code': code,
        'corp_name': name,
        'market_text': market_text,
        'market_key': market_group(market_text),
        'data_quality': QUALITY_PREVIOUS if dps is not None else QUALITY_NONE,
        'dividend_basis_year': basis_year,
        'dps_krw': dps,
        'dividend_yield_pct': to_float(history.get('dividend_yield_pct')) if dps is not None else None,
        # 🟣 우선주 값은 폴백에서도 **2026년 레코드(data)** 에서 옵니다 — 기준선(KIND 연간 집계)
        #    에는 우선주 항목 자체가 없기 때문입니다. 두 갈래가 같은 모양을 갖도록 여기서도
        #    같은 열쇠를 채웁니다(위 docstring "확정분과 폴백분이 같은 모양"). 다만 이 목록의
        #    표(`pending_row_cells`)는 "작년 배당율" 을 말하는 자리라 우선주 줄을 그리지 않고,
        #    우선주만 확인된 종목이 몇 건인지는 요약 줄에서 숫자로 밝힙니다(§0-1).
        'dps_preferred': to_float(data.get('dps_cash_preferred')),
        'dps_preferred_all': preferred_cash_values(data),
        'yield_preferred': to_float(data.get('cash_yield_preferred')),
        'yield_note': None,
        'settle_date': None,                       # 🔴 폴백 종목은 2026년 날짜가 없습니다
        'report_name': None,
        'dart_url': None,
        'status': data.get('status'),
        'status_reason': data.get('status_reason'),
        'parse_notes': tuple(data.get('parse_notes') or ()),
        'unit_mismatch_notes': tuple(data.get('unit_mismatch_notes') or ()),
        'cross_source_notes': tuple(data.get('cross_source_notes') or ()),
        # 🔴 M3(2026-08-29) 추가 — 주식종류 구분 없이("-") 온 배당액. `is_confirmed_this_year`
        # 가 보통주 기준이라 이 값만 있는 종목은 여기(미확정 목록)로 옵니다 — 자동으로
        # 보통주 승격은 하지 않되(수집기와 같은 원칙), 값 자체는 숨기지 않고 옮겨 둡니다.
        'dps_unspecified': to_float(data.get('dps_cash_unspecified')),
        'value_source': ('KIND 연간 배당 집계 (2023~2025 기준선)' if dps is not None else None),
    }


def build_entries(records, history_index):
    """레코드 전체 → `(확정 목록, 미확정 목록)`.

    🔴 폴백(작년 배당율) 종목은 **확정 목록에 절대 섞이지 않습니다.** 달력 날짜 칸은 확정
       목록만 보고 만들어지므로, 이 분리가 "작년 값이 2026년 달력에 찍히는" 사고를 구조적으로
       막는 자리입니다.
    """
    index = history_index or {}
    confirmed = []
    pending = []
    for record in records or []:
        code = str((record or {}).get('stock_code') or '').strip()
        entry = display_entry(record, index.get(code))
        if entry['data_quality'] == QUALITY_CONFIRMED:
            confirmed.append(entry)
        else:
            pending.append(entry)
    confirmed.sort(key=lambda item: (-(item['dps_krw'] or 0.0), item['corp_name']))
    pending.sort(key=lambda item: (item['data_quality'], item['corp_name']))
    return confirmed, pending


def group_by_settle_date(entries):
    """확정 목록 → `{결산기준일 문자열: [표시용 dict, …]}`.

    날짜가 비어 있는 확정 레코드는 담지 않습니다(달력에 놓을 자리가 없으므로). 그런 건이
    있으면 호출부가 그 수를 화면에 밝힙니다 — 조용히 사라지게 두지 않습니다(§0-1).
    """
    grouped = {}
    for entry in entries or []:
        settle_date = entry.get('settle_date')
        if not settle_date:
            continue
        grouped.setdefault(settle_date, []).append(entry)
    return grouped


def parse_iso_date(value):
    """'2026-06-30' → `date`. 형식이 다르면 **추측하지 않고** None."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


_KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """오늘 날짜(KST) — 서버가 어느 시간대에서 돌든(UTC 등) 항상 한국 시간 기준으로 계산합니다.

    `date.today()`를 그냥 쓰지 않는 이유: 배포 서버의 로컬 시간대가 UTC일 수 있고, 그러면
    한국 자정~오전 9시 사이엔 날짜가 하루 밀려 보입니다(§0-1 — 서버 시간대에 기대지 않기).
    """
    return datetime.now(timezone.utc).astimezone(_KST).date()


def busiest_month(grouped):
    """🔴 기본으로 보여줄 달 — **하드코딩하지 않고** 건수가 가장 많은 달을 계산합니다.

    같은 건수면 이른 달을 고릅니다(접속할 때마다 달라지지 않게 — 순서가 흔들리면 "왜 어제와
    다른 달이 열리지?" 라는 질문이 생깁니다).

    :return: `(연, 월)` 또는 날짜가 하나도 없으면 None.
    """
    tally = {}
    for settle_date, entries in (grouped or {}).items():
        parsed = parse_iso_date(settle_date)
        if parsed is None:
            continue
        key = (parsed.year, parsed.month)
        tally[key] = tally.get(key, 0) + len(entries)
    if not tally:
        return None
    return min(tally.items(), key=lambda item: (-item[1], item[0]))[0]


def month_weeks(year, month):
    """그 달의 주 단위 표 — 각 주는 7칸(일~토), 그 달이 아닌 칸은 0.

    `calendar` 표준 라이브러리를 그대로 씁니다(월별 일수·윤년 규칙을 우리가 다시 짜지
    않습니다 — §0-3-10). `firstweekday=6` 이 일요일 시작이고, 위 `WEEKDAY_LABELS` 와 짝입니다.
    """
    return calendar_module.Calendar(firstweekday=6).monthdayscalendar(year, month)


def date_key(year, month, day) -> str:
    """달력 칸 → `grouped` 조회에 쓰는 'YYYY-MM-DD' 문자열."""
    return f'{year:04d}-{month:02d}-{day:02d}'


#: 🔴 M14(2026-08-29) 추가 — 오타·손상된 날짜 하나(예: `2062-09-18`)가 `settle_date`나
#: 지급일정에 섞여 들어오면, 아래 while 루프가 그 연도까지 한 달씩 다 채워 월 선택기가
#: 수백 개(재현: 440개)로 부풀어 오릅니다. §0-1은 "실패를 정상 상태로 위장하지 않기"이지
#: "검증 안 된 입력을 무한정 믿기"가 아닙니다 — 오늘 기준 앞뒤 이 개월수를 벗어난 날짜는
#: 월 목록에서 빼고 건수를 세어 호출부가 화면에 그대로 밝히게 합니다(조용히 버리지
#: 않습니다). 2년(24개월)은 이 화면이 다루는 실제 데이터(올해 정기보고서 + 다음 해
#: 지급예정일)보다 넉넉히 넓게 잡은 값입니다.
AVAILABLE_MONTHS_MAX_MONTHS_FROM_TODAY = 24


def available_months(entries, payment_date_index, today):
    """달력에서 오갈 수 있는 달 목록 `[(연, 월), …]` — 결산기준일ㆍ지급예정일 데이터가
    실제로 덮는 범위 전체(연도 경계 포함).

    :return: `(months, out_of_range_count)` 튜플. `out_of_range_count`는 오늘로부터
        `AVAILABLE_MONTHS_MAX_MONTHS_FROM_TODAY`개월을 벗어나 목록에서 뺀 날짜 개수입니다
        (M14, 2026-08-29) — 손상된 날짜를 조용히 버리지 않고, 몇 건을 뺐는지 그대로
        돌려줘서 호출부가 화면에 밝힐 수 있게 합니다.

    🔴 2026-08-29(오푸스 감사 Top-5 #4) — 이전에는 `_render_calendar()`의 `_shift()`/
       `_on_month()`가 `1 <= month <= 12`로 **한 해 안에서만** 움직여서, 12월 결산 배당의
       지급예정일(통상 다음 해 3~4월, `build_payment_date_index()`의 `pay` 축)이 파일에는
       있는데도 화면 어디서도 볼 방법이 없었습니다.
       미국 배당 화면(`dividend_us_logic.py::available_months()`)이 배당락일이 연도를
       걸치는 같은 문제를 이 방식(데이터가 덮는 최소~최대 달을 한 줄로 이어 놓기)으로
       이미 풀어 둔 걸 그대로 이식합니다(§0-3-10, 검증된 코드를 새로 짜지 않음). 다만
       두 화면은 서로 import 하지 않는 게 확정 원칙(`dividend_us_logic.py` 머리말 ① —
       "한국 배당 화면은 이번 작업에서 한 글자도 건드리지 않는다"는 과거 결정이 이번
       작업으로 갱신됐을 뿐, "두 화면이 서로 의존하지 않는다"는 원칙 자체는 유효)이라
       로직만 복제합니다.

    오늘이 속한 달은 데이터가 없어도 항상 포함합니다 — 기본으로 여는 달이 목록에 없으면
    화면이 열리자마자 엉뚱한 달로 튕기기 때문입니다.
    """
    def _in_range(year, month) -> bool:
        distance = (year - today.year) * 12 + (month - today.month)
        return abs(distance) <= AVAILABLE_MONTHS_MAX_MONTHS_FROM_TODAY

    months = {(today.year, today.month)}
    out_of_range_count = 0
    for entry in entries or ():
        parsed = parse_iso_date((entry or {}).get('settle_date'))
        if parsed is None:
            continue
        if _in_range(parsed.year, parsed.month):
            months.add((parsed.year, parsed.month))
        else:
            out_of_range_count += 1
    for date_str in (payment_date_index or {}).keys():
        parsed = parse_iso_date(date_str)
        if parsed is None:
            continue
        if _in_range(parsed.year, parsed.month):
            months.add((parsed.year, parsed.month))
        else:
            out_of_range_count += 1
    if not months:
        return [], out_of_range_count
    (start_year, start_month) = min(months)
    (end_year, end_month) = max(months)

    ordered = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        ordered.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ordered, out_of_range_count


# 🟡 L1(2026-08-29) 삭제 — 이 화면은 `months.index()` + `_go(index±1)`로 달을 옮기므로
# `shift_month()`는 정의만 있고 호출부가 없는 죽은 함수였습니다(§0-3-10 YAGNI). 미국
# 배당 화면(`dividend_us_logic.py::shift_month()`)은 실제로 이 방식을 쓰므로 그대로
# 남아 있습니다 — 이 파일에서만 지웠습니다. 이 함수를 검증하던
# `test_shift_month_crosses_year_boundary_both_directions`도 함께 지웠습니다.


def month_label(year, month) -> str:
    """월 선택기·건수 줄에 쓰는 라벨 `'2026년 3월'`."""
    return f'{year}년 {month}월'


def market_choices(entries):
    """시장 필터 항목 — **데이터에 실제로 있는 구분만** 넣습니다.

    없는 시장을 목록에 만들어 두면 "골랐는데 0건"이 되어 데이터가 빠진 것처럼 보입니다.
    순서는 코스피 → 코스닥 → 코넥스 → 구분 없음으로 고정합니다(접속마다 순서가 흔들리지
    않게).
    """
    present = {entry.get('market_key') for entry in entries or []}
    ordered = [key for key in ('코스피', '코스닥', '코넥스', MARKET_UNKNOWN) if key in present]
    return [MARKET_ALL] + ordered


def matches_filters(entry, query, market_key) -> bool:
    """검색어(회사명·종목코드) + 시장 필터. 기본값은 항상 **전체 노출**입니다."""
    if market_key and market_key != MARKET_ALL and entry.get('market_key') != market_key:
        return False
    text = str(query or '').strip().lower()
    if not text:
        return True
    return text in str(entry.get('corp_name') or '').lower() or text in str(entry.get('stock_code') or '')


def filter_entries(entries, query, market_key):
    return [entry for entry in entries or [] if matches_filters(entry, query, market_key)]


def basis_year_text(entry) -> str:
    """🔴 "작년 배당율입니다" 라벨 — **실제로 쓴 연도**를 적습니다.

    값이 없으면 연도를 지어내지 않고 '데이터 없음'입니다(§0-1).
    """
    if entry.get('data_quality') == QUALITY_CONFIRMED:
        year = entry.get('dividend_basis_year')
        return f'{year}년 확정' if year else '올해 확정'
    year = entry.get('dividend_basis_year')
    if year is None:
        return NA_TEXT
    return f'{year}년 배당율입니다'


def status_summary_text(entry) -> str:
    """2026년에 무슨 일이 있었는지 **사람이 읽는 한 문장**(§0-3-4).

    수집기가 남긴 `status_reason` 원문은 `013` 같은 API 상태코드를 포함하고 있어 그대로
    큰 글씨로 내보내지 않습니다. 다만 **감추지도 않습니다** — 원문은 이 칸의 툴팁에
    그대로 실립니다(아래 `pending_row_cells()`).
    """
    status = entry.get('status')
    if status == 'OK':
        return '정기보고서는 찾았지만 배당 표에 보통주 현금배당이 없습니다'
    if status == 'NO_DATA':
        return '해당 사업연도의 정기보고서 배당 표를 찾지 못했습니다'
    if status == 'UNMAPPED':
        return '종목코드를 DART 고유번호와 연결하지 못했습니다'
    if status == 'ERROR':
        # 🔴 M4(2026-08-29) 추가 — ERROR 는 "확인 못 함"이 아니라 "조회하다 실패한 것이
        # 확인된" 상태입니다(수집기 :980). 예전에는 이 분기가 없어 아래 기본 문구
        # ("확인하지 못했습니다")로 빠졌는데, 그 문구는 정반대 인상을 줍니다 — 실패
        # 자체는 확인됐다는 사실을 숨기지 않습니다.
        return '2026년 정기보고서를 조회하다 오류가 나서 이 종목은 확인하지 못했습니다'
    return '수집 상태를 확인하지 못했습니다'


# =============================================================================
# 2. HTML 조각 — 외부 문자열은 전부 여기서 `esc()` 를 거칩니다 (§0-3-9)
# =============================================================================
def dart_link_html(url) -> str:
    """DART 원문 링크 한 칸.

    🔴 `esc()` 만으로는 부족한 유일한 자리입니다. `esc()` 는 따옴표를 막아 속성 밖으로
       빠져나가는 것은 막지만, `javascript:` 같은 **스킴 자체**는 막지 못합니다. 그래서
       http/https 로 시작하지 않는 값은 링크로 만들지 않습니다.
    """
    text = str(url or '').strip()
    if not text:
        return esc(NA_TEXT)
    if not text.lower().startswith(('https://', 'http://')):
        return esc('링크 형식 확인 필요')
    return (f'<a href="{esc(text)}" target="_blank" rel="noopener noreferrer" '
            f'style="color: #38bdf8; font-weight: 700;">DART 원문 ↗</a>')


def name_cell_html(entry) -> str:
    """회사명 + 종목코드 한 칸. 둘 다 외부 문자열이라 예외 없이 `esc()`."""
    return (f'<div style="white-space: normal; overflow-wrap: anywhere; line-height: 1.3;">'
            f'{esc(entry.get("corp_name") or "회사명 없음")}<br>'
            f'({esc(entry.get("stock_code") or "")})</div>')


def preferred_line_html(body_html: str) -> str:
    """보통주 값 아래 붙는 우선주 한 줄의 껍데기(색·크기는 `PREFERRED_LINE_STYLE` 한 곳)."""
    return f'<div style="{PREFERRED_LINE_STYLE}">{body_html}</div>'


def preferred_dps_html(entry) -> str:
    """🟣 우선주 주당 현금배당금 한 줄. **값이 없으면 빈 문자열**(빈 줄을 만들지 않습니다).

    후보가 2개 이상이면 "우선주 2종: 405원, 667원" 처럼 **전부** 적고 배지로 사유를 답니다 —
    수집기가 대표값을 정하지 못한 사실을 화면에서 다시 지우지 않기 위해서입니다(§0-1).
    """
    values = entry.get('dps_preferred_all') or ()
    if not values:
        return ''
    if len(values) == 1:
        return preferred_line_html(esc(f'{PREFERRED_LABEL} {fmt_num(values[0], "원", 0)}'))
    listed = ', '.join(fmt_num(value, '원', 0) for value in values)
    return preferred_line_html(
        esc(f'{PREFERRED_LABEL} {len(values)}종: {listed}')
        + warn_badge(
            PREFERRED_MULTI_LABEL,
            'DART 원문에 우선주 주당 현금배당금이 <b>서로 다른 값으로 여러 개</b> 실려 '
            '있습니다(예: 2우B·3우C 처럼 우선주가 여러 종류이거나, 원자료가 어긋난 경우).<br>'
            '수집기가 대표값 하나를 임의로 고르지 않고 후보를 전부 남겼기 때문에, 이 화면도 '
            '하나만 골라 보여주지 않고 그대로 나열합니다.<br>'
            '어느 값이 어느 우선주의 것인지는 원문 확인이 필요합니다 — 같은 줄의 '
            '"📝 파싱 메모" 배지에 수집기가 남긴 사유 원문이 그대로 들어 있습니다.',
        )
    )


def preferred_yield_html(entry) -> str:
    """🟣 우선주 배당수익률 한 줄(없으면 빈 문자열).

    보통주와 **같은 서식**(`fmt_num(..., '%', 2)`)을 씁니다 — 같은 칸 안에서 숫자 서식이
    달라지면 다른 종류의 수치처럼 보이기 때문입니다.
    ⚠️ "원문값" 주의 배지를 여기에 다시 달지 않는 이유: `yield_reliability_note` 는 레코드
       하나에 붙는 경고(그 보고서의 수익률 전체가 누적과 어긋날 수 있다)라 보통주 줄에 이미
       달려 있고, 같은 칸 안에서 같은 배지를 두 번 보여주면 서로 다른 경고처럼 읽힙니다.
    """
    value = entry.get('yield_preferred')
    if value is None:
        return ''
    return preferred_line_html(esc(f'{PREFERRED_LABEL} {fmt_num(value, "%", 2)}'))


def dps_cell_html(entry) -> str:
    """주당 현금배당금 한 칸 — 보통주 값 + (있을 때만) 우선주 줄.

    우선주 줄이 붙는 순간 위의 숫자에도 "보통주" 이름표를 답니다. 이름 없는 숫자 두 개가
    세로로 붙어 있으면 합계나 두 기간의 값처럼 읽히기 때문입니다.
    """
    common_text = esc(fmt_num(entry.get('dps_krw'), '원', 0))
    preferred = preferred_dps_html(entry)
    if not preferred:
        # 우선주가 없는 대다수 종목(실측 2,734건 중 2,713건)은 예전과 **글자 하나까지 같은 칸**.
        return common_text
    return f'<div>{esc(COMMON_LABEL)} {common_text}</div>{preferred}'


def yield_cell_html(entry) -> str:
    """배당수익률 한 칸 + 원문값 주의 배지 (+ 있을 때만 우선주 줄).

    수치는 DART 원문 그대로이고, 우리가 (DPS ÷ 현재가)로 계산해 대체하지 않습니다.
    `yield_reliability_note` 가 있으면 그 문구를 **그대로**(이스케이프해서) 툴팁에 답니다.
    """
    text = esc(fmt_num(entry.get('dividend_yield_pct'), '%', 2))
    note = entry.get('yield_note')
    common_html = text if not note else text + warn_badge(YIELD_WARN_LABEL, esc(note))
    preferred = preferred_yield_html(entry)
    if not preferred:
        return common_html      # ← 우선주 수익률이 없으면 예전 출력과 완전히 동일합니다
    return f'<div>{esc(COMMON_LABEL)} {common_html}</div>{preferred}'


def parse_note_badge_html(entry) -> str:
    """파싱 메모가 있으면 배지로 알립니다(있는데 안 보이면 그게 §0-1 위반입니다)."""
    notes = entry.get('parse_notes') or ()
    if not notes:
        return ''
    body = '<br>'.join(esc(note) for note in notes)
    return warn_badge(f'📝 파싱 메모 {len(notes)}건', body)


def unit_mismatch_badge_html(entry) -> str:
    """🔴 H7(2026-08-29) 추가 — `unit_mismatch_notes`가 있으면 배지로 알립니다.

    `parse_note_badge_html()`과 정확히 대칭인 자리입니다 — 수집기는 라벨의 단위 토큰이
    기대와 다르면(예: "주당 현금배당금(천원)") 값을 임의로 변환하지 않고 이 필드에
    사유만 남깁니다. 화면이 이 필드를 안 읽으면 1,000배 틀린 숫자가 배지 없이 그대로
    나갑니다(§0-1).
    """
    notes = entry.get('unit_mismatch_notes') or ()
    if not notes:
        return ''
    body = '<br>'.join(esc(note) for note in notes)
    return warn_badge('⚠️ 단위 검증 미통과', body)


def cross_source_badge_html(entry) -> str:
    """🔴 H7(2026-08-29) 추가 — `cross_source_notes`(DART ↔ KIND 교차검증 불일치)가 있으면
    배지로 알립니다. 값을 고치지 않고 "사람이 확인해야 한다"는 사실만 밝힙니다.
    """
    notes = entry.get('cross_source_notes') or ()
    if not notes:
        return ''
    body = '<br>'.join(esc(note) for note in notes)
    return warn_badge('🔎 출처 간 불일치', body)


#: 🔴 2026-09-03 — 이 두 문장을 **상수로 뽑았습니다.** 지금까지는 아래
#: `_payment_event_notes_html()` 안에만 있었는데, 같은 공시를 스코어카드 화면
#: (`web/pages/pegy_page.py` 의 "다음 배당 일정" 한 줄)에서도 보여주게 되면서 같은 경고를
#: 두 화면이 각자 손으로 적을 상황이 됐습니다. 문장이 한쪽만 고쳐지면 같은 공시를 두 화면이
#: 다르게 설명하게 되므로 출처를 하나로 둡니다(§0-3-10). 문구 자체는 바꾸지 않았습니다 —
#: 앞에 붙던 '⚠️ ' 는 표시하는 쪽이 붙입니다(배지 라벨에 이미 ⚠️ 가 들어가는 자리도 있어서).
SUBSIDIARY_NOTICE_CAVEAT = ('이 공시는 "자회사의 주요경영사항"으로 접수됐습니다 — 공시 주체와 '
                            '실제 배당하는 회사가 다를 수 있습니다.')
PARTIAL_PARSE_CAVEAT = ('공시 원문에서 일부 항목을 확실히 읽지 못했습니다'
                        '(parse_status={status}).')


def _payment_event_notes_html(event) -> str:
    """이벤트 1건의 부가 안내(정정 여부는 `payment_event_summary_text`가 이미 앞에 붙이므로
    여기서는 다루지 않음) — 자회사 대리공시ㆍ파싱 일부 실패ㆍ원문 링크. 없으면 빈 문자열.

    `payment_badge_html()`·`payment_date_block_html()` 둘 다 쓰는 공통 조각입니다(§0-3-10
    — 같은 안내를 두 곳에서 각자 다시 만들지 않기).
    """
    parts = []
    if event.get('is_subsidiary_notice'):
        parts.append('⚠️ ' + SUBSIDIARY_NOTICE_CAVEAT)
    status = event.get('parse_status')
    if status and status != 'OK':
        parts.append('⚠️ ' + PARTIAL_PARSE_CAVEAT.format(status=esc(status)))
    url = event.get('dart_document_url')
    if url:
        parts.append(dart_link_html(url))
    if not parts:
        return ''
    return '<br>' + '<br>'.join(parts)


def payment_badge_html(entry, payment_index) -> str:
    """🟢 "실제 지급일정" 배지 한 조각. 이 종목에 해당 이벤트가 없으면 **빈 문자열**
    (없는데 배지 자리만 비워 두면 "곧 채워질 값"처럼 보이므로, 아예 아무것도 그리지
    않습니다 — 우선주 줄이 없을 때와 같은 원칙).

    여러 건이면 전부 나열합니다(`build_payment_event_index` 와 같은 이유). `[기재정정]`ㆍ
    자회사 대리공시ㆍ원문 일부 파싱 실패는 감추지 않고 각 건 밑에 그대로 덧붙입니다(§0-1).
    """
    payment_index = payment_index or {}
    code = str(entry.get('stock_code') or '').strip()
    events = payment_index.get(code) or ()
    if not events:
        return ''

    def _line(event):
        text = esc(payment_event_summary_text(event))
        ex_date, _reason = ex_dividend_date(event.get('record_date'))
        if ex_date is not None:
            text += warn_badge('🧮 계산값', EX_DATE_CALC_NOTE)
        return text + _payment_event_notes_html(event)

    lines = [_line(event) for event in events]

    count = len(events)
    label = PAYMENT_BADGE_LABEL if count == 1 else f'{PAYMENT_BADGE_LABEL} {count}건'
    body = esc(PAYMENT_BADGE_TOOLTIP_INTRO) + '<br><br>' + '<br><br>'.join(lines)
    return info_badge(label, body)


def payment_date_block_html(key, payment_date_index, today) -> str:
    """선택한 날짜(`key`, 'YYYY-MM-DD') → 그 날짜에 걸리는 지급일정 이벤트를 **바로 보이는
    HTML**로(툴팁 아님 — 2026-08-25 오너 요청: "툴팁 말고 달력에 바로 표시해달라").

    배당기준일로 걸린 이벤트와 지급예정일로 걸린 이벤트를 **구분**해서 보여줍니다(색·라벨
    다름) — 같은 이벤트가 두 날짜 모두 이 날일 수도 있어(드묾) 그럴 땐 두 번 나오는데,
    그때도 "이 줄이 어느 날짜 자격으로 여기 있는지"를 라벨로 밝힙니다(§0-1). 아무 이벤트도
    없으면 **빈 문자열**(빈 카드를 그리지 않습니다 — 배지와 같은 원칙).

    🔴 H3(2026-08-29) 추가 — `today`(KST)를 받아 `key`가 이미 지난 날짜인지 계산합니다.
    지난 날짜면 색을 죽이고 "(이미 지난 날짜)"를 헤더에 밝혀, 과거 배당락일 상세를 보면서도
    "지금부터 준비할 수 있는 일정"으로 오독하지 않게 합니다.
    """
    bucket = (payment_date_index or {}).get(key) or {}
    ex_events = bucket.get('ex') or ()
    record_events = bucket.get('record') or ()
    pay_events = bucket.get('pay') or ()
    if not ex_events and not record_events and not pay_events:
        return ''

    is_future = key >= today.isoformat()

    def _row(event, kind_label, color, is_calculated=False, extra_html=''):
        row_color = color if is_future else PAYMENT_PAST_COLOR
        name = esc(event.get('corp_name') or '회사명 없음')
        code = esc(event.get('stock_code') or event.get('stock_code_raw') or NA_TEXT)
        detail = esc(payment_event_summary_text(event))
        if is_calculated:
            detail += warn_badge('🧮 계산값', EX_DATE_CALC_NOTE)
        detail += _payment_event_notes_html(event)
        return (
            f'<div style="margin: 6px 0; padding: 8px 10px; border-left: 3px solid {row_color}; '
            f'background: rgba(255,255,255,0.03); border-radius: 4px;">'
            f'<span style="color:{row_color};font-weight:800;">{esc(kind_label)}</span> '
            f'<b>{name}</b>({code})<br>{detail}{extra_html}</div>'
        )

    # 🔴 L11(2026-08-29) — 이 칸(`key`)이 바로 'ex' 축이면 그 날짜 자체가 배당락일입니다.
    # 배당락일이 이미 있는데 "매수 마지막 날"만 없는 것이 비대칭이라(미국 화면엔 있음),
    # 여기서 한 번 더 계산해 ex 행에만 붙입니다(배당기준일·지급예정일 행에는 붙이지
    # 않습니다 — 그 행들은 배당락일 축이 아니라서 "매수 마지막 날"의 기준이 될 수 없음).
    ex_key_date = parse_iso_date(key) if ex_events else None
    last_buy_extra = last_buy_html_kr(ex_key_date, is_future) if ex_events else ''

    # 🔴 순서는 시간순(락일 → 기준일 → 지급일)입니다 — 배당락일이 실제로 가장 먼저
    # 오는 날짜라 "이 날 이후로는 사도 소용없다"를 자연스럽게 먼저 보게 됩니다.
    rows = [_row(event, '🔴 배당락일', PAYMENT_EX_COLOR, is_calculated=True,
                 extra_html=last_buy_extra)
            for event in ex_events]
    rows += [_row(event, '🟡 배당기준일', PAYMENT_RECORD_COLOR) for event in record_events]
    rows += [_row(event, '🟢 지급예정일', PAYMENT_DATE_COLOR) for event in pay_events]

    header = '💰 이 날짜에 걸리는 실제 지급일정 공시'
    if not is_future:
        header += ' <span style="color:#94a3b8;font-weight:700;">(이미 지난 날짜)</span>'

    return (
        '<div style="margin: 8px 0;">'
        f'<div style="font-weight:800;margin-bottom:4px;">{header}</div>'
        f'<div class="vh-muted" style="margin-bottom:6px;">{esc(PAYMENT_BADGE_TOOLTIP_INTRO)}'
        '</div>'
        + ''.join(rows) + '</div>'
    )


def confirmed_row_cells(entry, payment_index=None):
    """달력에서 고른 날짜의 표 한 행(7칸). 모든 칸이 이스케이프를 마친 HTML 조각입니다.

    :param payment_index: `build_payment_event_index()` 가 만든 색인. 없으면(None·빈 dict)
        "실제 지급일정" 배지를 그냥 안 그립니다 — 이 매개변수를 안 주는 기존 호출부가
        있어도 예전과 똑같이 동작합니다(하위 호환).
    """
    return [
        name_cell_html(entry) + parse_note_badge_html(entry)
        + unit_mismatch_badge_html(entry) + cross_source_badge_html(entry)
        + payment_badge_html(entry, payment_index),
        esc(entry.get('market_text') or MARKET_UNKNOWN),
        dps_cell_html(entry),
        yield_cell_html(entry),
        esc(entry.get('report_name') or NA_TEXT),
        esc(entry.get('settle_date') or NA_TEXT),
        dart_link_html(entry.get('dart_url')),
    ]


def pending_row_cells(entry, payment_index=None):
    """"아직 2026년 배당 미확정 (작년 참고)" 표 한 행(6칸).

    🟢 2026-08-25 — 이 목록에도 "실제 지급일정" 배지를 붙입니다. 첫 프로덕션 실행에서
    바로 실측된 사례(스튜디오삼익 415380)가 이 목록에 있었습니다 — 정기보고서 기준으로는
    아직 "미확정"인데 DART 수시공시로는 이미 실제 배당기준일·지급예정일자가 나온
    경우입니다. 확정 표에만 배지를 달면 이런 종목은 데이터를 모아 놓고도 화면 어디에도
    안 보이므로(오너 확인, 2026-08-25), 같은 배지를 여기도 답니다.

    :param payment_index: `build_payment_event_index()` 가 만든 색인. 없으면(None) 배지를
        그냥 안 그립니다 — 하위 호환.
    """
    reason = entry.get('status_reason')
    status_cell = esc(status_summary_text(entry))
    if reason:
        # 수집기 원문은 감추지 않되, 큰 글씨로 내보내지 않고 툴팁에 둡니다(§0-3-4).
        status_cell += warn_badge('🔎 수집기 원문 사유', esc(reason))
    year_cell = esc(basis_year_text(entry))
    if entry.get('data_quality') == QUALITY_NONE:
        year_cell += warn_badge(
            '❔ 기준선에도 없음',
            '2023~2025년 KIND 연간 집계에도 이 종목의 배당액이 없습니다.<br>'
            '값을 지어내지 않고 "데이터 없음"으로 둡니다 — 0원이라는 뜻이 아닙니다.',
        )
    # 🔴 M3(2026-08-29) 추가 — 주식종류 구분 없이("-") 온 2026년 배당액이 있으면, 미확정
    # 판정 자체는 그대로 두되(보통주 기준, 자동 승격 안 함) 그 값이 있다는 사실은 숨기지
    # 않고 배지로 밝힙니다.
    unspecified = entry.get('dps_unspecified')
    if unspecified is not None:
        year_cell += warn_badge(
            '📎 종류구분 없는 배당액 있음',
            f'2026년 정기보고서에 주식종류 구분 없이(원문 "-") 1주당 {fmt_num(unspecified, "원", 0)}'
            '이 기재돼 있습니다.<br>보통주 배당으로 자동 승격하지 않아 이 종목은 여전히 '
            '"미확정"으로 분류됩니다 — 값 자체는 숨기지 않고 여기 밝혀 둡니다.',
        )
    return [
        name_cell_html(entry) + parse_note_badge_html(entry)
        + unit_mismatch_badge_html(entry) + cross_source_badge_html(entry)
        + payment_badge_html(entry, payment_index),
        esc(entry.get('market_text') or MARKET_UNKNOWN),
        year_cell,
        esc(fmt_num(entry.get('dps_krw'), '원', 0)),
        esc(fmt_num(entry.get('dividend_yield_pct'), '%', 2)),
        status_cell,
    ]


def summary_cards(summary, confirmed_count, pending_count):
    """상단 요약 카드 5장 `(제목, 값, 보조설명)`.

    🔴 값의 출처를 섞지 않습니다 — "2026년 배당 확정"만 **이 화면이 직접 센 수**이고
       (달력에 실제로 찍히는 건수와 같아야 하므로), 나머지는 수집기가 남긴 `summary` 값
       그대로입니다. 둘이 어긋나면 호출부가 경고 배너를 띄웁니다(아래 `_render_body()`).
    """
    data = summary or {}
    by_status = data.get('by_status') or {}
    universe = to_int(data.get('universe_size')) or to_int(data.get('total_records'))
    without_dps = to_int(data.get('ok_without_common_dps'))
    no_data = to_int(by_status.get('NO_DATA'))
    unmapped = to_int(by_status.get('UNMAPPED'))
    # 🔴 M4(2026-08-29) 추가 — ERROR 상태 카드. 예전에는 이 상태가 어느 카드에도 안 잡혀서
    # "미확정 + 데이터없음 + 매핑실패" 합이 실제 pending_count 와 어긋났습니다(ERROR 가
    # 1건이라도 있으면 산식이 안 맞음). 카드를 하나 추가해 숫자를 다 보여주고, 아래 산식
    # 문구에도 포함시킵니다.
    error_count = to_int(by_status.get('ERROR'))

    def count_text(value):
        return f'{value:,}건' if value is not None else NA_TEXT

    formula = '이 건수 + 데이터없음 + 매핑실패'
    if error_count:
        formula += ' + 조회오류'
    formula += f' = {pending_count:,}건'

    cards = [
        ('🎯 이번 수집 대상 종목',
         f'{universe:,}개' if universe is not None else NA_TEXT,
         '2023~2025년 배당 집계 파일에 실린 종목만 (전 상장사가 아닙니다)'),
        ('✅ 2026년 배당 확정',
         f'{confirmed_count:,}건',
         '달력에 실제로 찍히는 건수 (이 화면이 직접 셌습니다)'),
        ('⏳ 아직 2026년 미확정',
         count_text(without_dps),
         f'정기보고서는 찾았지만 배당 표가 없음 (아래 "작년 참고" 목록은 {formula})'),
        ('❔ 배당 표를 찾지 못함',
         count_text(no_data),
         '무배당인지 조회 실패인지 DART 응답만으로는 구분되지 않습니다'),
        ('🚫 종목코드 매핑 실패',
         count_text(unmapped),
         'DART 고유번호와 연결하지 못한 종목'),
    ]
    if error_count:
        cards.append((
            '🚨 조회 중 오류',
            count_text(error_count),
            'DART 조회 자체가 실패한 것이 확인된 종목 — "미확정"과 달리 실패 원인이 있습니다',
        ))
    return tuple(cards)


# =============================================================================
# 3. 페이지 (공개 플래그 게이트 → 본문)
# =============================================================================
#  NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 이 화면은
#  6.8MB + 4MB JSON 두 개를 읽으므로(원격 모드에서는 네트워크 왕복까지) 3초를 넘길 수 있고,
#  그러면 화면 대신 **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반).
@ui.page('/dividend', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def dividend_page(request: Request = None):
    """공개 화면 — 로그인 불필요(사용자별 데이터가 전혀 없습니다, §0-3-8).

    🧾 알려진 크롤러에게는 같은 파일을 그 자리에서 읽은 순수 HTML 을 돌려줍니다
       (`pegy_page.pegy_index_page` 와 같은 분기 — 근거는 `web/static_html.py` 머리말).
       공개 게이트도 같은 상수로 같은 순서로 판정합니다 — 크롤러는 로그인할 수 없으므로
       `DIVIDEND_MENU_ADMIN_ONLY` 가 True 면 관리자가 아닌 접속자와 똑같이 "준비중"만 봅니다.
    """
    if is_known_crawler(request):
        return crawler_response(await build_crawler_html())
    with layout('💰 투자 감사합니다!', width_class='max-w-6xl'):
        ui.markdown('## 💰 투자 감사합니다! — 배당 캘린더')

        # 🚧 이중 방어 — 메뉴(`web/layout.py`)와 **같은 상수**를 보고 판단합니다.
        #    메뉴에 안 보이는데 URL 로는 열리는 상태가 생기지 않습니다(§0-3-6).
        if not DIVIDEND_ENABLED:
            warning_banner(COMING_SOON_TEXT)
            return
        if DIVIDEND_MENU_ADMIN_ONLY and not is_admin():
            warning_banner(COMING_SOON_TEXT)
            return

        await _render_body()
    return None


async def build_crawler_html() -> str:
    """크롤러용 정적 HTML — `_render_body()` 가 읽는 **같은 파일 두 개**(`DATA_FILENAME`·
    `HISTORY_FILENAME`)를 같은 로더로 읽고, 같은 순수 함수(`build_entries`)로 확정/미확정을
    가른 뒤 상단 요약과 확정 배당 상위 목록을 표로 폅니다.

    지급일정 공시 파일(`PAYMENT_EVENTS_FILENAME`)은 달력 칸의 🔴락일·🟡기준일·🟢지급일 배지
    전용이라 이 표에는 쓰이지 않아 읽지 않습니다 — 표에 실리는 값은 전부 위 두 파일에서 옵니다.
    실패 정책은 화면과 같습니다(§0-1).
    """
    title = '💰 투자 감사합니다! — 배당 캘린더'
    parts = [f'<h1>{esc(title)}</h1>']

    def _document(main_parts) -> str:
        return render_document(
            title=f'{title} | {SITE_TITLE}',
            description=CRAWLER_META_DESCRIPTION,
            canonical_path='/dividend',
            main_html='\n'.join(main_parts),
        )

    if not DIVIDEND_ENABLED or DIVIDEND_MENU_ADMIN_ONLY:
        parts.append(notice_box(COMING_SOON_TEXT, kind='warn'))
        return _document(parts)

    payload, load_error = await load_json_file_async(data_path(DATA_FILENAME))
    history_payload, history_error = await load_json_file_async(data_path(HISTORY_FILENAME))

    if payload is None or not isinstance(payload, dict):
        parts.append(notice_box(
            '🚨 2026년 배당 수집 결과를 불러오지 못했습니다. '
            f'({load_error or "파일 형식이 예상과 다릅니다."})\n\n'
            '가짜 기본값으로 달력을 채우지 않기 위해 아무 수치도 표시하지 않습니다. '
            '데이터 준비 중입니다 — 잠시 후 다시 확인해 주세요.'
        ))
        return _document(parts)

    summary = payload.get('summary') or {}
    records = payload.get('records') or []
    if not records:
        parts.append(notice_box(
            '🚨 2026년 배당 수집 결과에 레코드가 0건입니다.\n\n'
            '수집이 정상적으로 끝났는지 확인이 필요합니다. 값을 지어내지 않고 여기서 멈춥니다.'
        ))
        return _document(parts)

    generated = summary.get('generated_at_kst')
    if generated:
        parts.append(notice_box(
            f'🕒 데이터 기준 시각 (KST): {generated}\n\n'
            '이 화면의 모든 값은 그 시각에 수집된 스냅샷이며, 실시간 시세가 아닙니다. '
            '출처는 DART 정기보고서(2026년)와 KIND 연간 집계(2023~2025) 두 가지뿐입니다.',
            kind='info',
        ))
    else:
        parts.append(notice_box(
            '⚠️ 데이터 기준 시각(generated_at_kst)이 수집 결과에 없습니다. '
            '아래 값이 언제 수집된 것인지 이 화면에서는 확인할 수 없습니다.', kind='warn',
        ))
    if summary.get('completed') is False:
        reason = summary.get('stopped_reason') or '사유 미기록'
        parts.append(notice_box(
            f'🚨 이번 수집은 끝까지 돌지 못하고 중단됐습니다({reason}).\n\n'
            '아래 종목 수·건수는 끝까지 돈 만큼만입니다 — 나머지 종목은 이번 수집에 '
            '아예 포함되지 않았고, 값을 지어내 채우지 않았습니다.'
        ))

    if history_error is not None or not isinstance(history_payload, dict):
        parts.append(notice_box(
            '⚠️ 2023~2025년 배당 기준선 파일을 불러오지 못했습니다. '
            f'({history_error or "파일 형식이 예상과 다릅니다."}) '
            '아직 미확정인 종목의 "작년 배당율" 값은 이번에는 전부 "데이터 없음"입니다.',
            kind='warn',
        ))
        history_index = {}
    else:
        history_index = build_history_index(history_payload)

    confirmed, pending = build_entries(records, history_index)

    parts.append('<h2>요약</h2><ul>')
    for label, value, note in summary_cards(summary, len(confirmed), len(pending)):
        parts.append(f'<li><b>{esc(label)}</b>: {esc(value)} <span class="note">— {esc(note)}</span></li>')
    parts.append('</ul>')

    parts.append(notice_box(CALENDAR_DATE_NOTICE, kind='warn'))
    parts.append(notice_box(UNIVERSE_NOTICE, kind='learn'))
    parts.append(notice_box(YIELD_SOURCE_NOTICE, kind='learn'))
    parts.append(notice_box(CUMULATIVE_DPS_NOTICE, kind='learn'))
    parts.append(notice_box(TAX_NOTICE, kind='learn'))

    top = confirmed[:CRAWLER_TABLE_ROWS]
    rows = [[
        entry.get('corp_name') or NA_TEXT,
        entry.get('stock_code') or NA_TEXT,
        entry.get('market_text') or NA_TEXT,
        entry.get('settle_date') or NA_TEXT,
        entry.get('report_name') or NA_TEXT,
        fmt_num(entry.get('dps_krw'), '원', digits=0),
        fmt_num(entry.get('dividend_yield_pct'), '%', digits=2),
        (str(entry['dividend_basis_year']) if entry.get('dividend_basis_year') is not None else NA_TEXT),
    ] for entry in top]
    parts.append(f'<h2>2026년 배당 확정 {len(confirmed):,}건 — 보통주 주당 현금배당금 상위 {len(top)}건</h2>')
    parts.append(table_html(
        ['회사명', '종목코드', '시장', '결산기준일', '보고서', '보통주 주당 현금배당금',
         '배당수익률(보고서 원문)', '배당 기준연도'],
        rows,
    ))
    parts.append(remaining_note(len(top), len(confirmed), '2026년 배당 확정'))
    parts.append(
        f'<p class="note">아직 2026년 배당이 확정되지 않은 종목은 {len(pending):,}건이며, 그 목록(작년 배당 '
        '참고값 포함)과 월별 달력은 브라우저(자바스크립트 실행)에서 같은 주소를 열면 볼 수 있습니다.</p>'
    )
    return _document(parts)


async def _render_body() -> None:
    """데이터 로드 → 정직성 고지 → 달력 → 미확정 목록.

    ⚠️ 파일 읽기는 반드시 **비동기판**입니다. 동기 `load_json_file()` 을 `@ui.page` 안에서
       부르면 이벤트 루프를 붙잡아 **다른 화면을 보던 접속자까지 전부 끊깁니다**
       (2026-08-21 사고 — `web/state.py` 의 긴 주석).
    """
    payload, load_error = await load_json_file_async(data_path(DATA_FILENAME))
    history_payload, history_error = await load_json_file_async(data_path(HISTORY_FILENAME))

    # 🟢 "실제 지급일정" 배지용 — 완전히 별도 수집기(`collector_dividend_payment_kr.py`)가
    #    만드는 파일입니다. 위 두 파일과 달리 **파일이 아직 없을 때는 에러 배너를 띄우지
    #    않습니다** — 이 파일은 덧붙는 정보일 뿐이라, 없으면 배지만 안 붙고 달력은 예전과
    #    똑같이 그려집니다(첫 수집이 아직 안 돈 상태에서도 화면이 정상 동작해야 하므로).
    # 🔴 M2(2026-08-29) 수정 — 예전에는 `_payment_error`를 이름에 밑줄까지 붙여 통째로
    # 버렸습니다. "파일이 아직 없다"(첫 실행 전, 정상)와 "읽다가 실패했다"(네트워크
    # 타임아웃 등, 비정상)는 다른 사실인데(§0-1), 둘 다 조용히 같은 빈 결과로 취급되면
    # 원격 소스가 일시적으로 오류를 내도 달력의 🔴락일·🟡기준일·🟢지급일 표시가 그냥
    # 조용히 사라져 "이번 달엔 일정이 없다"로 오독됩니다. `data_source._read_local()` 은
    # 파일이 없을 때 "…이 없습니다"를, 읽기 자체가 실패했을 때 "…을 읽지 못했습니다"를
    # 돌려주므로 그 문구로 두 경우를 구분합니다.
    payment_payload, payment_error = await load_json_file_async(data_path(PAYMENT_EVENTS_FILENAME))
    if payment_error and '읽지 못했습니다' in payment_error:
        warning_banner(
            f'⚠️ 지급일정 공시 파일을 읽지 못했습니다({payment_error}) — 이번에는 배당기준일 · '
            '지급예정일 · 배당락일 표시를 하지 않습니다(일정이 없다는 뜻이 아닙니다). '
            '결산기준일 기준 배당 확정 목록·달력은 평소대로 보입니다.'
        )
    payment_index = (
        build_payment_event_index(payment_payload)
        if isinstance(payment_payload, dict) else {}
    )
    # 🟢 2026-08-25 — 같은 파일을 **날짜 기준**으로도 색인합니다(달력 격자에 배당기준일ㆍ
    #    지급예정일을 직접 표시하기 위함, 오너 요청: "툴팁 말고 달력에 표시해달라").
    payment_date_index = (
        build_payment_date_index(payment_payload)
        if isinstance(payment_payload, dict) else {}
    )

    # ── §0-1 회귀 지점 — 2026 수집분이 없으면 숫자를 하나도 그리지 않습니다 ──
    if payload is None or not isinstance(payload, dict):
        error_banner(
            '🚨 2026년 배당 수집 결과를 불러오지 못했습니다. '
            f'({load_error or "파일 형식이 예상과 다릅니다."})\n\n'
            '가짜 기본값으로 달력을 채우지 않기 위해 아무 수치도 표시하지 않습니다.'
        )
        return

    summary = payload.get('summary') or {}
    records = payload.get('records') or []
    if not records:
        error_banner(
            '🚨 2026년 배당 수집 결과에 레코드가 0건입니다.\n\n'
            '수집이 정상적으로 끝났는지 확인이 필요합니다. 값을 지어내지 않고 여기서 멈춥니다.'
        )
        return

    # 기준선(2023~2025)은 **없어도 달력은 그립니다.** 다만 무엇이 빠졌는지는 숨기지 않습니다.
    if history_error is not None or not isinstance(history_payload, dict):
        warning_banner(
            '⚠️ 2023~2025년 배당 기준선 파일을 불러오지 못했습니다. '
            f'({history_error or "파일 형식이 예상과 다릅니다."})\n\n'
            '2026년 배당이 확정된 종목(달력)은 그대로 보이지만, 아직 미확정인 종목의 '
            '"작년 배당율" 값은 이번에는 전부 "데이터 없음"으로 표시됩니다 — '
            '값이 0이라는 뜻이 아니라 참고할 기준선을 읽지 못했다는 뜻입니다.'
        )
        history_index = {}
    else:
        history_index = build_history_index(history_payload)

    confirmed, pending = build_entries(records, history_index)
    grouped = group_by_settle_date(confirmed)

    # ── 화면 순서 (2026-08-24 오너 피드백: "열자마자 한숨부터 나온다") ──────
    #    달력이 이 화면의 본체입니다. 예전에는 달력 앞에 큰 경고 배너 2개(UNIVERSE_NOTICE·
    #    CALENDAR_DATE_NOTICE)와 0.85rem 회색 문단 3개(YIELD_SOURCE_NOTICE·PREFERRED_NOTICE·
    #    우선주 건수 줄)가 쌓여 있어, 스크롤을 한참 내려야 달력이 나왔습니다.
    #    🔴 문구는 **한 글자도 지우지 않았습니다**(§0-1 — 정직성 문구 삭제 금지). 대신
    #       "언제 읽어야 하는가"로 자리를 나눴습니다:
    #         · 수치를 보기 전에 반드시 알아야 하는 것 → 위에 그대로 상시 노출
    #           (데이터 기준 시각 · 요약 카드 · 정합성 경고 · CALENDAR_DATE_NOTICE)
    #         · 배경 설명(수집 범위·수익률 산정 방식·우선주 표기 규칙·알려진 한계) →
    #           달력 **아래** 접이식 패널 하나로(`_render_notice_panel`).
    #    ⚠️ CALENDAR_DATE_NOTICE 만은 예외입니다 — 이 파일 머리말 ① 의 제품 결정대로
    #       접이식에 넣지 않고 달력 바로 위 상시 배너로 그대로 둡니다.
    _render_data_timestamp(summary)
    _render_completion_status(summary)
    _render_summary(summary, confirmed, pending, grouped)

    # ── 상태는 전부 이 함수의 지역 변수입니다 (§0-3-8) ───────────────────
    # 🔴 2026-08-25 오너 지시: 기본으로 여는 달은 "데이터가 몰린 달"이 아니라
    #    **오늘(KST)이 속한 달**입니다 — 매일 공시감시(daily watch)가 매일 데이터를 갱신하는
    #    지금, "지금이 몇 월인지"와 "달력이 몇 월을 보여주는지"가 어긋나면 안 된다는 오너
    #    피드백. 다만 이 달력의 날짜는 결산기준일이라(위 CALENDAR_DATE_NOTICE) 실제로 공시가
    #    몰리는 달과 다를 수 있어, 오늘 달이 비어 있을 수 있습니다 — 그럴 땐 조용히 다른 달을
    #    대신 열지 않고 "이번 달은 비어 있다"고 그대로 밝힌 뒤(§0-1) 데이터가 있는 달로
    #    넘어가는 버튼만 둡니다(아래 `_render_calendar`).
    suggested_month = busiest_month(grouped)      # 빈 달 안내에 쓸 "데이터가 몰린 달"
    today = today_kst()
    view = {
        # 확정 배당이 아예 0건이면 오늘 달을 열어도 항상 빈 화면이라, 그때만 기존대로
        # None(달력 자체를 안 그림 — `_render_calendar`의 None 분기가 처리)으로 둡니다.
        'year': today.year if suggested_month else None,
        'month': today.month if suggested_month else None,
        'selected_date': None,
        'day_page': 1,
        'pending_page': 1,
        'query': '',
        'market': MARKET_ALL,
        'suggested_month': suggested_month,
    }

    # 🔴 2026-08-29(오푸스 감사 Top-5 #4) — 오갈 수 있는 달 범위를 **전체(미필터) 확정
    #    목록 + 지급일정 색인**에서 한 번만 계산합니다(필터를 걸어도 이동 가능한 범위 자체는
    #    줄어들지 않아야 하므로, `_visible_confirmed()`가 아니라 `confirmed`를 씁니다 —
    #    `dividend_us_page.py`가 `data['entries']`를 쓰는 것과 같은 이유).
    months, out_of_range_month_count = available_months(confirmed, payment_date_index, today)
    # 🔴 M14(2026-08-29) — 손상된 날짜를 조용히 버리지 않고 그대로 밝힙니다(§0-1).
    if out_of_range_month_count:
        warning_banner(
            f'⚠️ 날짜가 오늘로부터 {AVAILABLE_MONTHS_MAX_MONTHS_FROM_TODAY}개월 넘게 벗어난 '
            f'레코드 {out_of_range_month_count:,}건을 월 선택기에서 제외했습니다 — 원본 데이터의 '
            '결산기준일ㆍ지급예정일이 잘못 기록됐을 가능성이 있습니다. 값은 지우지 않았고, '
            '이 화면의 달력 이동 범위에서만 뺐습니다.'
        )

    all_entries = confirmed + pending
    markets = market_choices(all_entries)

    def _visible_confirmed():
        return filter_entries(confirmed, view['query'], view['market'])

    def _visible_pending():
        return filter_entries(pending, view['query'], view['market'])

    def _on_filter_changed() -> None:
        view['selected_date'] = None       # 필터가 바뀌면 고른 날짜의 목록도 달라집니다
        view['day_page'] = 1
        view['pending_page'] = 1
        _calendar_section.refresh()
        _day_section.refresh()
        _pending_section.refresh()

    # ── 필터 (기본값은 항상 전체 — §3 기본 스코프) ──────────────────────
    with ui.row().classes('w-full items-end gap-4'):
        def _on_query(event) -> None:
            view['query'] = (event.value or '').strip()
            _on_filter_changed()

        def _on_market(event) -> None:
            view['market'] = event.value or MARKET_ALL
            _on_filter_changed()

        # 🔴 M13(2026-08-29) — 예전에는 debounce 가 없어 키 한 번 누를 때마다(2,734건
        # 필터링 + 확정/미확정/달력 세 구획 재렌더) 바로 실행됐습니다. Quasar 의 `debounce`
        # prop(ms 단위)으로 입력이 잠깐 멈춘 뒤에만 이벤트를 내보내게 해, 타이핑 도중
        # NiceGUI 이벤트 루프가 매 글자마다 무거운 재렌더를 하지 않게 합니다(§0-3-8과는
        # 별개로 순수 성능 이슈지만, 이벤트 루프를 막으면 다른 접속의 반응성에도 영향을
        # 줄 수 있어 여기서 고칩니다).
        ui.input('🔍 회사명 / 종목코드 검색', placeholder='예: BNK금융지주, 138930',
                 on_change=_on_query).props('clearable debounce=300').style('flex: 1 1 260px;')
        ui.select(markets, value=MARKET_ALL, label='🏛️ 시장',
                  on_change=_on_market).style('flex: 1 1 240px;')

    ui.separator()

    # ── 🔴 달력 날짜의 의미 — 달력 바로 위 상시 배너 (툴팁으로 때우지 않습니다) ──
    warning_banner(CALENDAR_DATE_NOTICE)

    # ── 🔴 "배당락일 전까지 매수해야 받는다" — 실전 행동 요령, 큰 글자 상시 노출 ──────
    # (오너 요청, 2026-08-25) 달력 바로 위, 위 배너 바로 아래. 접이식이 아니라 항상 보임.
    # 🔴 H3(2026-08-29) 수정 — 예전에는 조건 없이 항상 떴습니다. 이 화면은 지급일정
    # 이벤트의 과거/미래를 전혀 구분하지 않았는데, 그런 상태에서 이 배너만 상시 노출되면
    # 이전 달로 넘겨 이미 지난 배당락일을 볼 때도 "지금부터 매수하라"는 안내로 오독됩니다
    # (미국 배당 화면이 이미 방어해 둔 문제 — `dividend_us_page.py:451` 참고). 이제
    # **앞으로 남은 배당락일이 1건 이상일 때만** 그리고, 몇 건 남았는지 문구에 그대로
    # 적습니다(지어내지 않되, 근거 없이 숨기지도 않습니다).
    future_ex_count = count_future_ex_events(payment_date_index, today)
    if future_ex_count:
        ui.html(
            f'<div style="text-align:center; margin: 4px 0 16px 0; padding: 16px 20px; '
            f'background: rgba(127, 29, 29, 0.35); border: 2px solid {PAYMENT_EX_COLOR}; '
            f'border-radius: 10px;">'
            f'<span style="font-size: 1.5rem; font-weight: 900; color: {PAYMENT_EX_COLOR}; '
            f'line-height: 1.4;">{EX_DATE_BUY_DEADLINE_WARNING}</span>'
            f'<div style="font-size: 0.85rem; color:#cbd5e1; margin-top:6px;">'
            f'앞으로 남은 배당락일 {future_ex_count:,}건이 있어요(지급일정 공시 기준).</div>'
            f'</div>'
        ).classes('w-full')
    else:
        ui.label(
            '⚪ 지급일정 공시로 확인된 배당락일 중 앞으로 남은 건이 없어요 — 지난 배당락일은 '
            '기록으로만 아래 달력에 남아 있습니다.'
        ).classes('vh-muted vh-keep-all')

    # ── 🔵 "오늘은 며칠" — 위 빨간 배너와 세트로 보이는 큰 박스, 달력 바로 위 ──────────
    # (오너 요청, 2026-08-27) "저기 배당락일 전까지 매수해주세요 저거 잘보여서 좋아 /
    # 저런 느낌으로 오늘이 몇월몇일인지도 보여주면 좋을 거 같아" — 위 배당락일 경고가
    # "언제까지 사야 하는지"를 말하는데, 정작 **오늘이 며칠인지**가 화면에 없으면 그 마감을
    # 스스로 계산할 수 없다는 지적입니다. 그래서 바로 아래에 붙여 한 세트로 읽히게 두되,
    # 색은 TODAY_HIGHLIGHT_COLOR(파랑) — 경고(빨강)가 아니라 기준점(정보)이기 때문이고,
    # 아래 달력 격자의 "오늘 칸" 테두리와 같은 색이라 배너와 칸이 서로를 가리킵니다.
    # 글자는 1.25rem — 위 경고(1.5rem)보다 한 단계 작게 둬서 "경고 > 정보"라는 무게 차이를
    # 지키면서도, "잘 보여서 좋다"는 피드백대로 본문(1rem)보다는 확실히 크게 남깁니다.
    # 날짜는 `today_kst()`를 여기서 다시 부르지 않고 위에서 이미 계산해둔 `today` 지역
    # 변수를 그대로 씁니다 — KST 계산은 이 함수 한 곳에서만 일어나야 배너와 달력이 서로
    # 다른 날짜를 말하는 일이 없습니다(자정 근처에 실제로 갈릴 수 있는 문제).
    # 요일은 WEEKDAY_LABELS(일요일 시작)를 재사용합니다 — Python 의 weekday()는 월=0..일=6
    # 이라 `(weekday() + 1) % 7` 로 옮겨야 이 배열과 짝이 맞습니다(월→1='월', 일→0='일').
    today_weekday_label = WEEKDAY_LABELS[(today.weekday() + 1) % 7]
    ui.html(
        f'<div style="text-align:center; margin: 0 0 16px 0; padding: 14px 20px; '
        f'background: rgba(30, 58, 138, 0.35); border: 2px solid {TODAY_HIGHLIGHT_COLOR}; '
        f'border-radius: 10px;">'
        f'<span style="font-size: 1.25rem; font-weight: 900; '
        f'color: {TODAY_HIGHLIGHT_COLOR}; line-height: 1.4;">'
        f'📅 오늘은 {today.year}년 {today.month}월 {today.day}일 '
        f'({today_weekday_label})이에요</span>'
        f'</div>'
    ).classes('w-full')

    @ui.refreshable
    def _calendar_section() -> None:
        # `today`(KST)는 위에서 한 번만 계산해 여기로 넘깁니다 — `_render_calendar`가
        # 스스로 `today_kst()`를 부르면 계산 자리가 둘로 늘어나 배너와 달력이 어긋날 수
        # 있습니다(2026-08-27, 오늘 칸 강조 추가하면서).
        _render_calendar(view, _visible_confirmed(), len(confirmed), payment_date_index, months,
                         today=today,
                         on_changed=_calendar_section.refresh,
                         on_day_changed=lambda: _day_section.refresh())

    @ui.refreshable
    def _day_section() -> None:
        _render_selected_day(view, _visible_confirmed(), payment_index, payment_date_index,
                             today, on_changed=_day_section.refresh)

    _calendar_section()
    _day_section()

    ui.separator()

    # ── 배경 설명 · 알려진 한계 · 원본 다운로드 (기본 접힘) ───────────────
    _render_notice_panel(summary, confirmed, pending, payment_payload)

    @ui.refreshable
    def _pending_section() -> None:
        _render_pending(view, _visible_pending(), len(pending), payment_index,
                        on_changed=_pending_section.refresh)

    _pending_section()
    disclaimer_footer()


# =============================================================================
# 4. 데이터 기준 시각 · 요약 카드 · 안내 패널(달력 아래, 접이식) · 원본 다운로드
#    ⚠️ 그리는 자리는 함수마다 다릅니다 — 기준 시각/요약은 달력 **위**, 안내 패널과
#       다운로드는 달력 **아래**입니다. 순서의 단일 출처는 `_render_body()` 입니다.
# =============================================================================
def _render_data_timestamp(summary) -> None:
    """§0-3-1 — "실시간"이라는 말을 쓰지 않고 **수집 시각**을 그대로 밝힙니다."""
    generated = (summary or {}).get('generated_at_kst')
    if not generated:
        # 시각을 모르면 '지금'으로 위장하지 않습니다(§0-1).
        warning_banner(
            '⚠️ 데이터 기준 시각(generated_at_kst)이 수집 결과에 없습니다. '
            '아래 값이 언제 수집된 것인지 이 화면에서는 확인할 수 없습니다.'
        )
        return
    info_banner(
        f'🕒 데이터 기준 시각 (KST): {generated}\n\n'
        '이 화면의 모든 값은 그 시각에 수집된 스냅샷이며, 실시간 시세가 아닙니다. '
        '출처는 DART 정기보고서(2026년)와 KIND 연간 집계(2023~2025) 두 가지뿐입니다.'
    )


def _render_completion_status(summary) -> None:
    """🔴 H6(2026-08-29) 추가 — 수집이 **중간에 끊긴 결과**·**부분 갱신된 결과**임을
    이 화면이 상시 배너로 밝힙니다.

    수집기는 §0-1 을 지키려고 `completed`·`stopped_reason`·`watch_update_performed_at_kst`·
    `limit_applied`·`verification_status` 를 성실히 남기는데, 예전에는 이 화면 어디도 이
    필드들을 읽지 않았습니다(`grep` 0건 — 재감사 확인). 그래서 5시간 예산을 넘겨 절반만
    돌고 중단된 결과나, daily watch 로 일부 종목만 갱신된 결과가 **전수 정상 수집**처럼
    보였습니다. 이 함수는 그 신호들을 그대로(의역하지 않고) 화면 맨 위, 요약 카드보다도
    먼저 밝힙니다 — 사용자가 숫자를 보기 전에 "이 숫자가 전체인지 일부인지"부터 알아야
    하기 때문입니다.
    """
    data = summary or {}

    completed = data.get('completed')
    if completed is False:
        reason = data.get('stopped_reason') or '사유 미기록'
        error_banner(
            f'🚨 이번 수집은 끝까지 돌지 못하고 중단됐습니다({reason}).\n\n'
            '아래 종목 수·건수는 **끝까지 돈 만큼만**입니다 — 나머지 종목은 이번 수집에 '
            '아예 포함되지 않았고, 값을 지어내 채우지 않았습니다.'
        )

    watch_performed_at = data.get('watch_update_performed_at_kst')
    if watch_performed_at:
        replaced = len(data.get('watch_replaced_stock_codes') or ())
        added = len(data.get('watch_added_stock_codes') or ())
        skipped = len(data.get('watch_skipped_replacements') or ())
        detail = (f'이번 daily watch({watch_performed_at})가 교체 {replaced:,}종목 · '
                  f'추가 {added:,}종목을 반영했습니다.')
        if skipped:
            detail += (f' 델타 결과가 OK 가 아니어서 교체하지 않고 기존 값을 지킨 종목도 '
                       f'{skipped:,}건 있습니다.')
        warning_banner(
            '⚠️ 이 파일은 단일 전수 수집의 결과가 아니라 daily watch로 **부분 갱신**된 '
            f'결과입니다.\n\n{detail} 나머지 종목의 값은 직전 전수 수집 그대로입니다.'
        )

    limit_applied = data.get('limit_applied')
    if limit_applied:
        warning_banner(
            f'⚠️ 이 결과는 `--limit {limit_applied}` 로 대상 종목 수를 제한한 '
            '**시범 실행** 결과입니다 — 정식 전수 수집이 아닙니다.'
        )

    unit_mismatch = to_int(data.get('records_with_unit_mismatch'))
    cross_source = to_int(data.get('records_with_cross_source_mismatch'))
    if unit_mismatch or cross_source:
        parts = []
        if unit_mismatch:
            parts.append(f'단위 검증 미통과 {unit_mismatch:,}건')
        if cross_source:
            parts.append(f'출처 간(DART↔KIND) 불일치 {cross_source:,}건')
        warning_banner(
            '⚠️ ' + ' · '.join(parts) + ' — 값은 원문 그대로 두었고, 어느 종목인지는 '
            '아래 표에서 해당 행의 배지로 표시됩니다(§0-1: 값을 임의로 고치지 않습니다).'
        )

    outside_universe = data.get('watch_filings_outside_universe') or ()
    if outside_universe:
        codes = ', '.join(str(item) for item in outside_universe[:20])
        more = f' 외 {len(outside_universe) - 20:,}건' if len(outside_universe) > 20 else ''
        warning_banner(
            f'⚠️ 이번 daily watch에서 우리 유니버스 밖의 신규 배당 공시 '
            f'{len(outside_universe):,}건을 확인했지만 수집 대상이 아니라 이 화면에는 '
            f'넣지 않았습니다 ({codes}{more}).'
        )


def _render_summary(summary, confirmed, pending, grouped) -> None:
    """요약 카드 5장 + 수치가 어긋날 때의 정합성 경고 (§0-1).

    2026-08-24 — 예전에는 이 함수가 맨 앞에서 `warning_banner(UNIVERSE_NOTICE)` 를 띄우고
    맨 뒤에서 `YIELD_SOURCE_NOTICE` · `PREFERRED_NOTICE` · 우선주 건수 줄까지 그렸습니다.
    그 넷은 **문구 그대로** `_render_notice_panel()`(달력 아래 접이식)로 옮겼습니다 —
    삭제가 아니라 이동입니다(§0-1 정직성 문구 삭제 금지).
    반대로 아래 두 경고는 "이 화면의 숫자가 서로 안 맞는다"는 **지금 보고 있는 수치에 대한
    경고**라 접으면 안 됩니다. 요약 카드 바로 아래 상시 노출로 남깁니다.
    """
    with ui.row().classes('w-full gap-3 items-stretch'):
        for label, value, note in summary_cards(summary, len(confirmed), len(pending)):
            metric_card(label, value, note)

    # 🔴 M6(2026-08-29) 수정 — §0-3-13(2026-08-24 신설)은 "사용자가 화면을 잘못 해석하거나
    # 잘못된 판단을 내릴 수 있는 유의사항은 툴팁·작은 회색 글씨·접힌 아코디언 안에 숨기지
    # 않는다"고 명시합니다. 이 두 문구(UNIVERSE_NOTICE·YIELD_SOURCE_NOTICE)는 2026-08-24
    # UX 개선 때 접이식 패널(`_render_notice_panel`) 안으로 옮겨졌는데, 그 이동 자체가
    # §0-3-13 이 금지하는 "숨김"이었습니다. 문구는 그대로 두고(§0-1 삭제 금지) 자리만
    # 요약 카드 바로 아래(상시 노출)로 다시 꺼냅니다. `PREFERRED_NOTICE`·`PAYMENT_NOTICE`
    # 같은 순수 배경 설명만 접이식에 남습니다.
    ui.label(UNIVERSE_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')
    ui.label(YIELD_SOURCE_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')
    # 🔴 M5(2026-08-29) — 위 두 문구와 같은 이유(§0-3-13)로 상시 노출. "주당 현금배당금"이
    # 보고서마다 누적 범위가 달라 종목 간 비교가 위험하다는 사실은 열 제목만으로는 다
    # 전달되지 않습니다.
    ui.label(CUMULATIVE_DPS_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')
    # 🔴 M7(2026-08-29) — 세전 금액이라는 사실도 같은 이유로 상시 노출.
    ui.label(TAX_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')

    # 🔴 수집기 요약과 화면이 센 수가 어긋나면 조용히 넘어가지 않고 그대로 알립니다.
    reported = to_int((summary or {}).get('ok_with_common_dps'))
    if reported is not None and reported != len(confirmed):
        warning_banner(
            f'⚠️ 수집기 요약의 "보통주 현금배당 확정" 건수({reported:,}건)와 이 화면이 직접 '
            f'센 건수({len(confirmed):,}건)가 다릅니다. 달력에는 화면이 직접 센 건수만 '
            '올라갑니다 — 어느 쪽이 맞는지 데이터를 확인해 주세요.'
        )

    # 확정인데 결산기준일이 비어 달력에 놓을 수 없는 건수도 밝힙니다(§0-1).
    placed = sum(len(items) for items in grouped.values())
    if placed != len(confirmed):
        warning_banner(
            f'⚠️ 2026년 배당이 확정된 {len(confirmed):,}건 가운데 {len(confirmed) - placed:,}건은 '
            '결산기준일(stlm_dt)이 비어 있어 달력 어느 칸에도 놓지 못했습니다. '
            '사라진 것이 아니라 놓을 날짜가 없는 것입니다.'
        )


def _render_notice_panel(summary, confirmed, pending, payment_payload=None) -> None:
    """달력 아래 접이식 패널 하나 — 배경 설명 · 알려진 한계 · 원본 다운로드.

    2026-08-24 (오너 피드백: "정보량이 너무 많아서 열자마자 한숨부터 나온다") — 예전에는
    아래 문구들이 전부 **달력 앞에** 색깔 배너·회색 문단으로 흩어져 있었습니다. 문구는
    한 글자도 지우지 않고(§0-1), "지금 보이는 수치를 오해하지 않기 위해 먼저 읽어야 하는
    것"만 위에 남기고 배경 설명은 여기 한 곳으로 모았습니다.

    🔴 `default-opened` 를 **일부러 주지 않습니다** — 기본은 접힘입니다(이 프로젝트의 다른
       `ui.expansion` 사용례와 같은 규칙). 문구가 사라진 것이 아니라 한 번 눌러 펼치는
       자리로 옮겨졌을 뿐이며, 열자마자 눈에 들어와야 하는 CALENDAR_DATE_NOTICE 는
       이 패널에 **넣지 않고** 달력 바로 위 상시 배너로 그대로 둡니다(머리말 ①).

    글자 크기: 예전 `.vh-muted`(0.85rem · #94a3b8)는 "작고 흐려 읽기 피곤하다"는 지적을
    받아 이 패널 안에서만 `.vh-notice-text`(0.95rem · #cbd5e1 · line-height 1.8)로 바꿉니다.
    `.vh-muted` 자체는 다른 화면이 함께 쓰므로 건드리지 않았습니다(§0-3-10).
    """
    with ui.expansion(
        '📋 데이터 안내 및 알려진 한계 — 수집 범위 · 배당수익률 산정 방식 · '
        '우선주 표시 방식 (누르면 펼치기)'
    ).classes('w-full vh-card'):
        # 🔴 M6(2026-08-29) — UNIVERSE_NOTICE·YIELD_SOURCE_NOTICE 는 §0-3-13 때문에
        # 더 이상 여기(접이식) 안에 두지 않고 `_render_summary()`에서 상시 노출로
        # 옮겼습니다. 이 접이식에는 순수 배경 설명(우선주 표기 방식·지급일정 배지
        # 안내)만 남습니다.

        # 🟣 우선주 배당 안내 — 아래 `_render_known_limitations()` 가 싣는 **수집기 원문**과
        #    우리가 쓴 화면 설명이 섞여 보이지 않도록, 우리 설명을 먼저 두고 수집기 원문은
        #    자기 제목(📋 …)을 달고 뒤에 옵니다.
        ui.label(PREFERRED_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')

        shown = count_with_preferred(confirmed)
        preferred_only = count_with_preferred(pending)
        preferred_line = (
            f'🟣 이번 수집에서 우선주 현금배당이 함께 확인된 확정 종목: {shown:,}건 '
            f'(확정 {len(confirmed):,}건 중) — 달력에서 날짜를 누르면 나오는 표의 '
            '"주당 현금배당금"·"배당수익률" 칸 아래에 우선주 줄이 함께 붙습니다.'
        )
        if preferred_only:
            preferred_line += (
                f' · 그 밖에 {preferred_only:,}건은 2026년 우선주 배당만 확인되고 보통주 배당은 아직 '
                '확정되지 않아, 아래 "미확정" 목록에 그대로 있습니다 — 확정 판정 기준은 예전과 같이 '
                '보통주이며, 우선주 값이 있다고 확정으로 올리지 않았습니다.'
            )
        ui.label(preferred_line).classes('vh-notice-text vh-keep-all')

        # 🟢 "실제 지급일정" 배지 배경 설명 — 배지가 붙은 종목이 아직 하나도 없어도
        #    보여줍니다(UNIVERSE_NOTICE 와 같은 취지 — 왜 이런 게 있는지는 늘 밝혀 둡니다).
        ui.label(PAYMENT_NOTICE).classes('vh-notice-text vh-keep-all whitespace-pre-line')

        _render_known_limitations(summary)
        _render_payment_report_block(payment_payload)

        ui.separator()
        _render_raw_downloads()


def _render_payment_report_block(payment_payload) -> None:
    """🔴 M17(2026-08-29) 추가 — 지급일정 수집기(`collector_dividend_payment_kr.py`)가
    §0-1 을 지키려고 남긴 리포트(`by_parse_status`·`records_without_*`·`document_failures`·
    `scan_stats.unrecognized`)를 이 화면이 그대로 옮깁니다.

    예전에는 이 화면이 `payment_payload`에서 `records`만 읽었습니다 — "우리 판정 규칙 밖의
    새 report_nm 표기 7건" 같은 신호가 사람 눈에 닿을 길이 서버 로그밖에 없었습니다.
    `PAYMENT_NOTICE`의 일반론이 이 숫자들을 대신하지 못하므로, H6 과 같은 취지로 원문
    숫자를 그대로 노출합니다(의역하지 않습니다 — §0-1).
    """
    payment_summary = (payment_payload or {}).get('summary')
    if not isinstance(payment_summary, dict):
        return

    ui.markdown('**📋 지급일정 수집기(daily watch) 리포트**')

    by_parse_status = payment_summary.get('by_parse_status') or {}
    if by_parse_status:
        status_text = ' · '.join(f'{status}: {count:,}건' for status, count in by_parse_status.items())
        ui.label(f'파싱 상태별 건수 — {status_text}').classes('vh-notice-text')

    without_record = to_int(payment_summary.get('records_without_record_date'))
    without_pay = to_int(payment_summary.get('records_without_pay_date_expected'))
    if without_record or without_pay:
        ui.label(
            f'배당기준일이 비어 있는 레코드 {without_record or 0:,}건 · '
            f'지급예정일이 비어 있는 레코드 {without_pay or 0:,}건'
        ).classes('vh-notice-text')

    documents_failed = to_int(payment_summary.get('documents_failed_this_run'))
    if documents_failed:
        ui.label(
            f'⚠️ 이번 실행에서 원문 조회 자체가 실패한 공시 {documents_failed:,}건 — '
            '해당 접수번호는 다음 실행에서 다시 시도합니다.'
        ).classes('vh-notice-text')

    scan_stats = payment_summary.get('scan_stats') or {}
    unrecognized = to_int(scan_stats.get('unrecognized'))
    if unrecognized:
        samples = scan_stats.get('unrecognized_samples') or []
        sample_text = ', '.join(str(s) for s in samples[:5])
        ui.label(
            f'⚠️ 우리 판정 규칙 밖의 report_nm 표기 {unrecognized:,}건(이벤트로 만들지 '
            f'않았습니다)' + (f' — 예: {sample_text}' if sample_text else '')
        ).classes('vh-notice-text')


def _render_known_limitations(summary) -> None:
    """`summary.known_limitations` **원문 그대로**. 요약·의역하지 않습니다(§0-1).

    2026-08-24 — 예전에는 이 함수가 스스로 `ui.expansion` 을 하나 더 만들었습니다. 이제는
    `_render_notice_panel()` 의 접이식 패널 **안에서** 불리므로 접이식을 이중으로 만들지
    않고 제목 한 줄 + 원문 줄들만 그립니다. `known_limitations` 가 비어 있으면 제목까지
    통째로 그리지 않는 동작은 예전과 같습니다.
    """
    limitations = (summary or {}).get('known_limitations') or []
    if not limitations:
        return
    ui.markdown(f'**📋 이 데이터의 알려진 한계 {len(limitations)}가지 (수집기 원문)**')
    for line in limitations:
        ui.label(str(line)).classes('vh-notice-text vh-keep-all')


def raw_download_exceeds_cap(raw_size_bytes) -> bool:
    """🔴 M9/S5(2026-08-29) — raw 파일 크기(바이트)가 `RAW_DOWNLOAD_MAX_BYTES`를 넘는가.

    NiceGUI 위젯을 만들지 않는 순수 함수라(§1 관례) 렌더링 없이 이 판정 로직만 따로
    검증할 수 있습니다.
    """
    return raw_size_bytes > RAW_DOWNLOAD_MAX_BYTES


def raw_download_oversize_link_html(raw_size_bytes) -> str:
    """🔴 M9/S5(2026-08-29) — 상한을 넘었을 때 다운로드 버튼 대신 보여줄 GitHub 링크 한 줄.

    파일 경로 조각(`GITHUB_REPO_BLOB_BASE`·`RAW_FILENAME`)은 이 화면이 직접 쓴 상수라
    `esc()`가 원칙상 필요 없지만(§0-3-9는 외부 값에 대한 규칙), 이 자리에 나중에 실수로
    외부 값이 흘러들어도 안전하도록 그대로 씌워 둡니다.
    """
    size_mb = raw_size_bytes / (1024 * 1024)
    return (
        f'<a href="{esc(GITHUB_REPO_BLOB_BASE)}/{esc(RAW_FILENAME)}" '
        f'target="_blank" rel="noopener noreferrer" '
        f'style="color:#38bdf8; font-weight:700;">📦 2026년 수집 원본 (raw, '
        f'JSONL, {size_mb:.1f}MB) — 파일이 커서 이 화면 대신 GitHub 저장소에서 '
        '직접 받아 주세요 ↗</a>'
    )


def _render_raw_downloads() -> None:
    """원본(raw)·가공·기준선 파일 전부 다운로드 가능하게 합니다.

    `DIVIDEND_MODULE_WORK_ORDER.md` §3 "§0-3-3 raw/가공 분리" 표가 지적한 미충족 절반
    ("raw·가공 둘 다 사용자 다운로드 가능")을 채웁니다. 화면이 이미 읽은 파일을 그대로
    내보낼 뿐 새로 가공하지 않습니다 — 화면에 보이는 값과 다운로드 파일이 어긋날 일이
    없습니다. 종목 하나만 골라 받는 도구는 이 지시서에 없어(오너 확인, 2026-08-24)
    **넣지 않았습니다** — 전부(raw + 가공 + 기준선) 파일째 받는 것만 지원합니다.
    """
    today = today_kst().strftime('%Y%m%d')
    latest_path = data_path(DATA_FILENAME)
    raw_path = data_path(RAW_FILENAME)
    history_path = data_path(HISTORY_FILENAME)

    with ui.row().classes('w-full gap-3 items-center flex-wrap'):
        ui.label('📥 데이터 다운로드:').classes('vh-muted font-bold')
        if os.path.exists(latest_path):
            download_button(
                '2026년 수집 결과 (가공, JSON)',
                f'dividend_kr_2026_latest_{today}.json',
                lambda: read_download_bytes(latest_path),
                media_type='application/json',
                failure_text='2026년 수집 결과 파일을 읽지 못했습니다.',
            )
        if os.path.exists(raw_path):
            raw_size = os.path.getsize(raw_path)
            if not raw_download_exceeds_cap(raw_size):
                download_button(
                    '2026년 수집 원본 (raw, JSONL)',
                    f'dividend_kr_2026_raw_{today}.jsonl',
                    lambda: read_download_bytes(raw_path),
                    media_type='application/x-ndjson',
                    failure_text='2026년 원본 파일을 읽지 못했습니다.',
                )
            else:
                # 🔴 M9/S5(2026-08-29) — 상한을 넘으면 이 화면에서 직접 내려받게 하지 않고
                # GitHub 저장소 링크로 안내합니다(위 RAW_DOWNLOAD_MAX_BYTES 주석 참고).
                ui.html(raw_download_oversize_link_html(raw_size))
        if os.path.exists(history_path):
            download_button(
                '2023~2025년 배당 기준선 (JSON)',
                f'dividend_history_kr_2023_2025_{today}.json',
                lambda: read_download_bytes(history_path),
                media_type='application/json',
                failure_text='기준선 파일을 읽지 못했습니다.',
            )


# =============================================================================
# 5. 달력 — 월 이동 + 요일 7열 격자
# =============================================================================
def _render_calendar(view, entries, total_confirmed, payment_date_index, months,
                     today, on_changed, on_day_changed) -> None:
    """월 이동 줄 + 달력 격자.

    🔵 2026-08-27 — `today`(KST 오늘 날짜)를 **파라미터로 받습니다**. 이 함수 안에서
       `today_kst()`를 다시 부르지 않는 이유: KST 계산 자리가 둘이 되면 위 "오늘은 며칠"
       배너와 아래 오늘 칸 강조가 자정 근처에 서로 다른 날짜를 말할 수 있어서입니다.
       계산은 호출부 `_render_body()` 한 곳에서만 합니다.

    🔴 2026-08-29(오푸스 감사 Top-5 #4) — `months`(오갈 수 있는 `(연, 월)` 목록,
       `available_months()`)도 **파라미터로 받습니다**. 예전에는 이 함수 안에서
       `1 <= month <= 12`로 월만 옮기고 연도는 그대로 둬서, 12월 결산 배당의
       지급예정일(다음 해 3~4월)까지 이동할 방법이 없었습니다. 이제는 미국 배당
       화면과 같은 방식(연도를 걸쳐 이어진 달 목록 + 그 안에서의 인덱스)으로 이동합니다.

    ⚠️ 칸의 숫자는 **지금 필터를 통과한 종목만** 셉니다. 필터가 걸려 있으면 그 사실을 바로
       아래 줄에 적습니다 — 안 적으면 "어제는 154건이었는데 오늘은 3건"으로 보입니다(§0-1).

    🟢 2026-08-25 — `payment_date_index`(날짜 기준 지급일정 색인)가 있으면 칸에 🟡 배당기준일
       ㆍ🟢 지급예정일 표시를 **결산기준일 건수와 별도로** 덧붙입니다. 이 화면이 이미 필터
       (검색어·시장)를 지원하는데 지급일정 이벤트에는 시장·검색 매칭 대상 필드가 통일돼
       있지 않아, 지급일정 표시는 **필터와 무관하게 항상** 그대로 보여줍니다 — 필터링해서
       숨기는 대신 있는 그대로 밝히는 편이 안전합니다(§0-1).

    ⚠️ 확정 배당이 0건이면(`view['year'] is None`) 이 함수 자체가 안 불립니다(호출부
       `_render_body()`) — 그 경우 지급일정 데이터가 있어도 달력이 아예 안 그려지는
       한계가 아직 남아 있습니다(드문 경우 — 확정 목록이 통째로 비어야 발생).
    """
    if view['year'] is None or view['month'] is None:
        info_banner(
            'ℹ️ 2026년 배당이 확정된 종목이 아직 한 건도 없어 달력을 그리지 않았습니다. '
            '아래 "아직 2026년 배당 미확정" 목록만 보시면 됩니다.'
        )
        return

    grouped = group_by_settle_date(entries)

    if not months:
        # today 가 항상 `available_months()`에 포함되므로 사실상 도달하지 않지만,
        # 방어적으로 남겨 둡니다(위 `dividend_us_page.py::_render_calendar()`와 같은 자리).
        info_banner('ℹ️ 달력에 표시할 결산기준일ㆍ지급예정일이 한 건도 없습니다.')
        return

    year, month = view['year'], view['month']
    if (year, month) not in months:
        # 보던 달이 데이터 범위 밖으로 밀려났으면(드묾) 조용히 튕기지 않고 가장 가까운
        # 끝으로 붙인 뒤, 아래 건수 줄에서 "이번 달은 비어 있다"고 그대로 밝힙니다.
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
            picked = to_int(event.value)
            if picked is None or not 0 <= picked < len(months):
                return
            view['year'], view['month'] = months[picked]
            view['selected_date'] = None
            view['day_page'] = 1
            on_changed()
            on_day_changed()

        choices = {offset: month_label(*pair) for offset, pair in enumerate(months)}
        ui.select(choices, value=index, label='보는 달',
                  on_change=_on_month).style('flex: 0 0 220px;')
        if index < len(months) - 1:
            ui.button('다음 달 ▶', on_click=_go(index + 1)).props('flat dense no-caps')

    month_total = 0
    for key, items in grouped.items():
        parsed = parse_iso_date(key)
        if parsed is not None and (parsed.year, parsed.month) == (year, month):
            month_total += len(items)
    ui.label(f'📌 {year}년 {month}월에 결산기준일이 잡힌 확정 배당: {month_total:,}건').classes('vh-muted')

    if month_total == 0:
        # 오늘이 속한 달을 기본으로 열다 보니(위 `_render_body`) 자주 벌어지는 상황입니다 —
        # 조용히 다른 달로 대신 넘어가지 않고, 비어 있다는 사실 그대로 밝힌 뒤(§0-1) 데이터가
        # 있는 달로 넘어가는 버튼만 둡니다. 지금 필터를 통과한 건수 기준으로 세므로(아래
        # `grouped`가 이미 필터된 `entries`), 필터 때문에 그 달도 0건이면 버튼을 안 보여줍니다.
        suggested = view.get('suggested_month')
        suggested_count = 0
        if suggested and suggested != (year, month):
            for key, items in grouped.items():
                parsed = parse_iso_date(key)
                if parsed is not None and (parsed.year, parsed.month) == suggested:
                    suggested_count += len(items)
        if suggested and suggested != (year, month) and suggested_count:
            s_year, s_month = suggested

            def _jump_to_suggested(_event=None) -> None:
                view['year'], view['month'] = suggested
                view['selected_date'] = None
                view['day_page'] = 1
                on_changed()
                on_day_changed()

            with ui.row().classes('w-full items-center gap-2'):
                ui.label(
                    f'📭 이번 달은 아직 확정된 배당이 없어요 — 배당이 몰려있는 달은 '
                    f'{s_year}년 {s_month}월이에요({suggested_count:,}건).'
                ).classes('vh-notice-text')
                ui.button(f'{s_month}월로 이동', on_click=_jump_to_suggested) \
                    .props('flat dense no-caps color=primary')
        else:
            ui.label('📭 이번 달은 아직 확정된 배당이 없어요.').classes('vh-notice-text')

    if len(entries) != total_confirmed:
        ui.label(
            f'🔎 필터 적용 중 — 달력의 건수는 필터를 통과한 종목만 셉니다 '
            f'(전체 확정 {total_confirmed:,}건 중 {len(entries):,}건).'
        ).classes('vh-muted')

    def _pick(key):
        def _handler(_event=None) -> None:
            view['selected_date'] = None if view['selected_date'] == key else key
            view['day_page'] = 1
            on_changed()
            on_day_changed()
        return _handler

    # 🔵 2026-08-27 오너 요청("오늘이 몇월몇일인지도 보여주면 좋을 거 같아")의 달력 쪽 절반 —
    # 위 배너로 "오늘은 며칠"을 글자로 알렸으니, 격자에서도 그 날이 어디인지 바로 짚이도록
    # 오늘 칸에만 파란 테두리를 두릅니다. 배너와 같은 TODAY_HIGHLIGHT_COLOR 라서 둘이 같은
    # 뜻(=오늘)임이 색만으로 읽힙니다. 지금 **보고 있는 달**이 오늘이 속한 달일 때만 그립니다
    # — 다른 달로 넘기면 그 달에는 오늘이 없으므로 아무 칸도 강조되지 않아야 맞습니다.
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
                count = len(grouped.get(key, ()))
                date_bucket = (payment_date_index or {}).get(key) or {}
                ex_count = len(date_bucket.get('ex') or ())
                record_count = len(date_bucket.get('record') or ())
                pay_count = len(date_bucket.get('pay') or ())
                if not count and not record_count and not pay_count and not ex_count:
                    # 건수가 0인 날도 오늘이면 테두리가 보여야 합니다 — 오늘 강조는 배당
                    # 건수와 무관한 "지금 이 시점" 표시이기 때문(2026-08-27 오너 요청).
                    empty_cell = ui.label(str(day)).classes('text-center vh-muted py-2')
                    if is_today:
                        empty_cell.style(today_cell_style)
                    continue
                selected = view['selected_date'] == key
                day_cell = ui.column().classes('w-full gap-0 items-stretch')
                if is_today:
                    day_cell.style(today_cell_style)
                with day_cell:
                    if count:
                        button = ui.button(f'{day}일 · {count:,}건', on_click=_pick(key)) \
                            .classes('w-full')
                        button.props('unelevated no-caps dense color=primary' if selected
                                     else 'flat no-caps dense')
                    else:
                        # 🟢 결산기준일(확정배당)은 없지만 지급일정 이벤트만 있는 날 — 있는
                        # 정보를 숨기지 않기 위해 그래도 눌러서 아래에서 볼 수 있게 둡니다.
                        button = ui.button(f'{day}일', on_click=_pick(key)).classes('w-full')
                        button.props('unelevated no-caps dense color=primary' if selected
                                     else 'flat no-caps dense outline')
                    # 🔴 H3(2026-08-29) 추가 — 이 칸의 날짜가 오늘(포함) 이후인지로
                    # 지급일정 라벨의 색을 죽입니다(미국 배당 화면의 FUTURE/PAST 구분과
                    # 같은 판정). "종류"(🔴락일·🟡기준일·🟢지급일 아이콘·이름)는 그대로 두고
                    # "이미 지났다"는 사실만 글자색+문구로 덧붙입니다 — 색만으로 구분하면
                    # 색맹인 분들에게는 정보가 아니므로 "(지남)" 글자를 항상 함께 답니다.
                    key_is_future = key >= today.isoformat()
                    past_suffix = '' if key_is_future else '(지남)'
                    if ex_count:
                        color = PAYMENT_EX_COLOR if key_is_future else PAYMENT_PAST_COLOR
                        ui.label(f'🔴 락일 {ex_count}건{past_suffix}') \
                            .classes('text-center text-xs') \
                            .style(f'color:{color};font-weight:700;')
                    if record_count:
                        color = PAYMENT_RECORD_COLOR if key_is_future else PAYMENT_PAST_COLOR
                        ui.label(f'🟡 기준일 {record_count}건{past_suffix}') \
                            .classes('text-center text-xs') \
                            .style(f'color:{color};font-weight:700;')
                    if pay_count:
                        color = PAYMENT_DATE_COLOR if key_is_future else PAYMENT_PAST_COLOR
                        ui.label(f'🟢 지급일 {pay_count}건{past_suffix}') \
                            .classes('text-center text-xs') \
                            .style(f'color:{color};font-weight:700;')

    # 🔴 H3(2026-08-29) 추가 — "(지남)" 글자가 무엇을 뜻하는지 격자 바로 아래 항상 적습니다
    # (색만 두고 뜻을 안 적으면 그건 화면이 아니라 암호입니다 — 미국 배당 화면의 같은 자리
    # 안내와 같은 원칙).
    ui.label('🔴 배당락일 · 🟡 배당기준일 · 🟢 지급예정일 — 밝은 색은 앞으로, 회색+"(지남)"은 '
             '이미 지난 지급일정 공시입니다.').classes('vh-muted vh-keep-all')


def _render_selected_day(view, entries, payment_index, payment_date_index, today,
                         on_changed) -> None:
    """고른 날짜의 종목 목록(없으면 안내만). 표는 페이지로 나눠 그립니다.

    🟢 2026-08-25 — `payment_date_index`로 이 날짜에 걸리는 지급일정 이벤트(배당기준일ㆍ
    지급예정일)를 **결산기준일 종목 유무와 상관없이** 먼저 보여줍니다. 결산기준일 종목이
    하나도 없는 날(달력에서 "N일" 만 눌러 들어온 경우)도 지급일정만 있으면 여기서 그대로
    보이게 하려는 의도입니다 — 있는 정보를 화면 구조 때문에 숨기지 않기 위함(§0-1).
    """
    key = view.get('selected_date')
    if not key:
        if view['year'] is not None:
            ui.label('👆 달력에서 건수가 있는 날짜를 누르면 그 날짜의 종목 목록이 여기에 펼쳐집니다.') \
                .classes('vh-muted')
        return

    grouped = group_by_settle_date(entries)
    day_entries = grouped.get(key, [])

    date_block = payment_date_block_html(key, payment_date_index, today)
    if date_block:
        ui.html(date_block).classes('w-full')

    if not day_entries:
        if date_block:
            ui.label(
                f'ℹ️ {key}에 결산기준일이 걸린 확정 배당 종목은 없습니다 — 위 지급일정 '
                '공시만 있습니다.'
            ).classes('vh-muted')
        else:
            info_banner('ℹ️ 지금 걸린 필터로는 이 날짜에 표시할 종목이 없습니다.')
        return

    ui.markdown(f'#### 📅 {key} 실적 마감 — {len(day_entries):,}개 종목')
    ui.label(
        '이 날짜에 배당금이 들어오는 건 아니에요 — 이 날짜까지의 실적을 기준으로 '
        '"배당을 이만큼 하겠다"고 발표한 회사들이에요.'
    ).classes('vh-muted vh-keep-all')

    total_pages = max(1, (len(day_entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    current_page = min(view['day_page'], total_pages)
    view['day_page'] = current_page
    start = (current_page - 1) * ITEMS_PER_PAGE
    page_entries = day_entries[start:start + ITEMS_PER_PAGE]

    ui.html(holdings_table_html(
        list(CONFIRMED_HEADERS),
        [confirmed_row_cells(entry, payment_index) for entry in page_entries],
    )).classes('w-full')

    if total_pages > 1:
        def _on_page(page: int) -> None:
            view['day_page'] = page
            on_changed()

        pager(total_pages, current_page, _on_page)


# =============================================================================
# 6. 아직 2026년 배당 미확정 (작년 참고)
# =============================================================================
def _render_pending(view, entries, total_pending, payment_index, on_changed) -> None:
    """🔴 폴백 종목 목록 — **달력 칸에는 절대 들어가지 않는** 종목들입니다."""
    ui.markdown('### ⏳ 아직 2026년 배당 미확정 (작년 참고)')
    ui.label(PENDING_SECTION_NOTICE).classes('vh-muted vh-keep-all whitespace-pre-line')

    if not entries:
        info_banner('ℹ️ 지금 걸린 필터로는 표시할 종목이 없습니다.')
        return

    with_previous = sum(1 for entry in entries if entry['data_quality'] == QUALITY_PREVIOUS)
    # 🔴 M3(2026-08-29) 추가 — 주식종류 구분 없이 온 배당액이 있는 건수. 자동 승격은 안
    # 하지만(오너 판단으로 남겨 둠) 몇 건이나 있는지는 숨기지 않습니다.
    unspecified_count = sum(1 for entry in entries if entry.get('dps_unspecified') is not None)
    summary_line = (
        f'표시 대상 {len(entries):,}건 (전체 {total_pending:,}건 중) · '
        f'지난 연도 배당을 보여드릴 수 있는 종목 {with_previous:,}건 · '
        f'기준선에도 배당액이 없어 "데이터 없음" {len(entries) - with_previous:,}건'
    )
    if unspecified_count:
        summary_line += (
            f' · 주식종류 구분 없이 온 2026년 배당액이 있는 종목 {unspecified_count:,}건 '
            '(보통주로 자동 승격하지 않아 미확정으로 둡니다 — 각 행의 배지 참고)'
        )
    ui.label(summary_line).classes('vh-muted')

    total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    current_page = min(view['pending_page'], total_pages)
    view['pending_page'] = current_page
    start = (current_page - 1) * ITEMS_PER_PAGE
    page_entries = entries[start:start + ITEMS_PER_PAGE]

    ui.html(holdings_table_html(
        list(PENDING_HEADERS),
        [pending_row_cells(entry, payment_index) for entry in page_entries],
    )).classes('w-full')

    # 🟡 L9(2026-08-29) 수정 — `_render_selected_day()`와 같은 규칙으로 맞춥니다: 1페이지뿐일
    # 때는 pager를 그리지 않습니다(전에는 여기만 무조건 그려서 뒤로/앞으로 버튼이 항상 있는데
    # 아무 데도 못 가는 상태였습니다).
    if total_pages > 1:
        def _on_page(page: int) -> None:
            view['pending_page'] = page
            on_changed()

        pager(total_pages, current_page, _on_page)
