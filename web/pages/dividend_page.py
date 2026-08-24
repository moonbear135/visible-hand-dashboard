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
from datetime import date

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
    info_banner,
    metric_card,
    pager,
    warn_badge,
    warning_banner,
)
from web.layout import DIVIDEND_ENABLED, DIVIDEND_MENU_ADMIN_ONLY, layout
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
RAW_FILENAME = 'dividend_kr_2026_raw.jsonl'
HISTORY_FILENAME = 'dividend_history_kr_2023_2025.json'

#: 한 페이지에 그릴 표 행 수(달력 상세·미확정 목록 공통).
ITEMS_PER_PAGE = 50

#: 달력 요일 머리글 — **일요일 시작**(`calendar.Calendar(firstweekday=6)` 와 짝).
WEEKDAY_LABELS = ('일', '월', '화', '수', '목', '금', '토')

#: 달력에서 고른 날짜의 종목 표 열 제목.
CONFIRMED_HEADERS = (
    '회사명 (종목코드)', '시장', '주당 현금배당금', '배당수익률 (DART 원문)',
    '근거 보고서', '결산기준일', '원문 공시',
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
CALENDAR_DATE_NOTICE = (
    '📅 달력의 날짜는 각 보고서의 결산기준일(stlm_dt)이며, 실제 배당금 지급일도 배당락일도 '
    '아닙니다.\n'
    '이 화면이 읽는 데이터(DART 정기보고서 "배당에 관한 사항")에는 지급일·배당락일 정보가 '
    '아예 없습니다 — 없는 날짜를 지어내지 않으려고 있는 날짜(결산기준일)만 씁니다.\n'
    '즉 "6월 30일 칸에 있는 회사"는 "6월 30일에 배당금을 받는 회사"가 아니라 '
    '"6월 30일까지의 회계기간을 다룬 보고서에 배당이 적힌 회사"입니다.'
)

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


def month_choices(year):
    """월 선택기 항목 `{1: '2026년 1월', … 12: '2026년 12월'}` (함수 지역 dict)."""
    return {month: f'{year}년 {month}월' for month in range(1, 13)}


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


def confirmed_row_cells(entry):
    """달력에서 고른 날짜의 표 한 행(7칸). 모든 칸이 이스케이프를 마친 HTML 조각입니다."""
    return [
        name_cell_html(entry) + parse_note_badge_html(entry),
        esc(entry.get('market_text') or MARKET_UNKNOWN),
        dps_cell_html(entry),
        yield_cell_html(entry),
        esc(entry.get('report_name') or NA_TEXT),
        esc(entry.get('settle_date') or NA_TEXT),
        dart_link_html(entry.get('dart_url')),
    ]


def pending_row_cells(entry):
    """"아직 2026년 배당 미확정 (작년 참고)" 표 한 행(6칸)."""
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
    return [
        name_cell_html(entry) + parse_note_badge_html(entry),
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

    def count_text(value):
        return f'{value:,}건' if value is not None else NA_TEXT

    return (
        ('🎯 이번 수집 대상 종목',
         f'{universe:,}개' if universe is not None else NA_TEXT,
         '2023~2025년 배당 집계 파일에 실린 종목만 (전 상장사가 아닙니다)'),
        ('✅ 2026년 배당 확정',
         f'{confirmed_count:,}건',
         '달력에 실제로 찍히는 건수 (이 화면이 직접 셌습니다)'),
        ('⏳ 아직 2026년 미확정',
         count_text(without_dps),
         '정기보고서는 찾았지만 배당 표가 없음 '
         f'(아래 "작년 참고" 목록은 이 건수 + 데이터없음 + 매핑실패 = {pending_count:,}건)'),
        ('❔ 배당 표를 찾지 못함',
         count_text(no_data),
         '무배당인지 조회 실패인지 DART 응답만으로는 구분되지 않습니다'),
        ('🚫 종목코드 매핑 실패',
         count_text(unmapped),
         'DART 고유번호와 연결하지 못한 종목'),
    )


# =============================================================================
# 3. 페이지 (공개 플래그 게이트 → 본문)
# =============================================================================
#  NiceGUI 는 **비동기 페이지 함수에만** `response_timeout`(기본 3초)을 겁니다. 이 화면은
#  6.8MB + 4MB JSON 두 개를 읽으므로(원격 모드에서는 네트워크 왕복까지) 3초를 넘길 수 있고,
#  그러면 화면 대신 **영어 500 오류 페이지**가 나갑니다(§0-3-4 위반).
@ui.page('/dividend', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def dividend_page() -> None:
    """공개 화면 — 로그인 불필요(사용자별 데이터가 전혀 없습니다, §0-3-8)."""
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


async def _render_body() -> None:
    """데이터 로드 → 정직성 고지 → 달력 → 미확정 목록.

    ⚠️ 파일 읽기는 반드시 **비동기판**입니다. 동기 `load_json_file()` 을 `@ui.page` 안에서
       부르면 이벤트 루프를 붙잡아 **다른 화면을 보던 접속자까지 전부 끊깁니다**
       (2026-08-21 사고 — `web/state.py` 의 긴 주석).
    """
    payload, load_error = await load_json_file_async(data_path(DATA_FILENAME))
    history_payload, history_error = await load_json_file_async(data_path(HISTORY_FILENAME))

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

    _render_data_timestamp(summary)
    _render_summary(summary, confirmed, pending, grouped)
    _render_known_limitations(summary)
    _render_raw_downloads()

    # ── 상태는 전부 이 함수의 지역 변수입니다 (§0-3-8) ───────────────────
    default_month = busiest_month(grouped)
    view = {
        'year': default_month[0] if default_month else None,
        'month': default_month[1] if default_month else None,
        'selected_date': None,
        'day_page': 1,
        'pending_page': 1,
        'query': '',
        'market': MARKET_ALL,
    }

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

        ui.input('🔍 회사명 / 종목코드 검색', placeholder='예: BNK금융지주, 138930',
                 on_change=_on_query).props('clearable').style('flex: 1 1 260px;')
        ui.select(markets, value=MARKET_ALL, label='🏛️ 시장',
                  on_change=_on_market).style('flex: 1 1 240px;')

    ui.separator()

    # ── 🔴 달력 날짜의 의미 — 달력 바로 위 상시 배너 (툴팁으로 때우지 않습니다) ──
    warning_banner(CALENDAR_DATE_NOTICE)

    @ui.refreshable
    def _calendar_section() -> None:
        _render_calendar(view, _visible_confirmed(), len(confirmed),
                         on_changed=_calendar_section.refresh,
                         on_day_changed=lambda: _day_section.refresh())

    @ui.refreshable
    def _day_section() -> None:
        _render_selected_day(view, _visible_confirmed(), on_changed=_day_section.refresh)

    _calendar_section()
    _day_section()

    ui.separator()

    @ui.refreshable
    def _pending_section() -> None:
        _render_pending(view, _visible_pending(), len(pending),
                        on_changed=_pending_section.refresh)

    _pending_section()
    disclaimer_footer()


# =============================================================================
# 4. 상단 — 데이터 기준 시각 · 요약 · 알려진 한계
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


def _render_summary(summary, confirmed, pending, grouped) -> None:
    """유니버스 정직성 고지 + 요약 카드 5장 (§0-1)."""
    warning_banner(UNIVERSE_NOTICE)

    with ui.row().classes('w-full gap-3 items-stretch'):
        for label, value, note in summary_cards(summary, len(confirmed), len(pending)):
            metric_card(label, value, note)

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

    ui.label(YIELD_SOURCE_NOTICE).classes('vh-muted vh-keep-all whitespace-pre-line')

    # 🟣 우선주 배당 안내 — **요약 카드 아래**에 둡니다(알려진 한계 섹션이 아니라).
    #    바로 위 `_render_known_limitations()` 는 `summary.known_limitations` 를 **수집기 원문
    #    그대로** 싣는 자리라, 우리가 쓴 화면 설명 문장을 섞으면 어디까지가 수집기 말인지
    #    구분이 사라집니다. 반대로 이 자리는 이미 우리가 쓴 설명(`YIELD_SOURCE_NOTICE`)이
    #    사는 곳이고, 수치를 보기 **전에** 읽어야 오해가 안 생기는 종류의 안내입니다.
    ui.label(PREFERRED_NOTICE).classes('vh-muted vh-keep-all whitespace-pre-line')

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
    ui.label(preferred_line).classes('vh-muted vh-keep-all')


def _render_known_limitations(summary) -> None:
    """`summary.known_limitations` **원문 그대로**. 요약·의역하지 않습니다(§0-1)."""
    limitations = (summary or {}).get('known_limitations') or []
    if not limitations:
        return
    with ui.expansion(f'📋 이 데이터의 알려진 한계 {len(limitations)}가지 (수집기 원문)') \
            .classes('w-full vh-card'):
        for line in limitations:
            ui.label(str(line)).classes('vh-muted vh-keep-all')


def _render_raw_downloads() -> None:
    """원본(raw)·가공·기준선 파일 전부 다운로드 가능하게 합니다.

    `DIVIDEND_MODULE_WORK_ORDER.md` §3 "§0-3-3 raw/가공 분리" 표가 지적한 미충족 절반
    ("raw·가공 둘 다 사용자 다운로드 가능")을 채웁니다. 화면이 이미 읽은 파일을 그대로
    내보낼 뿐 새로 가공하지 않습니다 — 화면에 보이는 값과 다운로드 파일이 어긋날 일이
    없습니다. 종목 하나만 골라 받는 도구는 이 지시서에 없어(오너 확인, 2026-08-24)
    **넣지 않았습니다** — 전부(raw + 가공 + 기준선) 파일째 받는 것만 지원합니다.
    """
    today = date.today().strftime('%Y%m%d')
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
            download_button(
                '2026년 수집 원본 (raw, JSONL)',
                f'dividend_kr_2026_raw_{today}.jsonl',
                lambda: read_download_bytes(raw_path),
                media_type='application/x-ndjson',
                failure_text='2026년 원본 파일을 읽지 못했습니다.',
            )
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
def _render_calendar(view, entries, total_confirmed, on_changed, on_day_changed) -> None:
    """월 이동 줄 + 달력 격자.

    ⚠️ 칸의 숫자는 **지금 필터를 통과한 종목만** 셉니다. 필터가 걸려 있으면 그 사실을 바로
       아래 줄에 적습니다 — 안 적으면 "어제는 154건이었는데 오늘은 3건"으로 보입니다(§0-1).
    """
    if view['year'] is None or view['month'] is None:
        info_banner(
            'ℹ️ 2026년 배당이 확정된 종목이 아직 한 건도 없어 달력을 그리지 않았습니다. '
            '아래 "아직 2026년 배당 미확정" 목록만 보시면 됩니다.'
        )
        return

    grouped = group_by_settle_date(entries)
    year, month = view['year'], view['month']

    def _shift(delta):
        def _handler(_event=None) -> None:
            target = month + delta
            if 1 <= target <= 12:
                view['month'] = target
                view['selected_date'] = None
                view['day_page'] = 1
                on_changed()
                on_day_changed()
        return _handler

    with ui.row().classes('w-full items-center gap-2'):
        if month > 1:
            ui.button('◀ 이전 달', on_click=_shift(-1)).props('flat dense no-caps')

        def _on_month(event) -> None:
            picked = to_int(event.value)
            if picked is None or not 1 <= picked <= 12:
                return
            view['month'] = picked
            view['selected_date'] = None
            view['day_page'] = 1
            on_changed()
            on_day_changed()

        ui.select(month_choices(year), value=month, label='보는 달',
                  on_change=_on_month).style('flex: 0 0 200px;')
        if month < 12:
            ui.button('다음 달 ▶', on_click=_shift(1)).props('flat dense no-caps')

    month_total = 0
    for key, items in grouped.items():
        parsed = parse_iso_date(key)
        if parsed is not None and (parsed.year, parsed.month) == (year, month):
            month_total += len(items)
    ui.label(f'📌 {year}년 {month}월에 결산기준일이 잡힌 확정 배당: {month_total:,}건').classes('vh-muted')
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

    with ui.grid(columns=7).classes('w-full gap-1'):
        for label in WEEKDAY_LABELS:
            ui.label(label).classes('text-center text-xs font-bold opacity-60')
        for week in month_weeks(year, month):
            for day in week:
                if not day:
                    ui.label('').classes('text-center')
                    continue
                key = date_key(year, month, day)
                count = len(grouped.get(key, ()))
                if not count:
                    ui.label(str(day)).classes('text-center vh-muted py-2')
                    continue
                selected = view['selected_date'] == key
                button = ui.button(f'{day}일 · {count:,}건', on_click=_pick(key)).classes('w-full')
                button.props('unelevated no-caps dense color=primary' if selected
                             else 'flat no-caps dense')


def _render_selected_day(view, entries, on_changed) -> None:
    """고른 날짜의 종목 목록(없으면 안내만). 표는 페이지로 나눠 그립니다."""
    key = view.get('selected_date')
    if not key:
        if view['year'] is not None:
            ui.label('👆 달력에서 건수가 있는 날짜를 누르면 그 날짜의 종목 목록이 여기에 펼쳐집니다.') \
                .classes('vh-muted')
        return

    grouped = group_by_settle_date(entries)
    day_entries = grouped.get(key, [])
    ui.markdown(f'#### 📅 {key} 결산기준일 — {len(day_entries):,}개 종목')
    ui.label(
        '아래 종목들은 이 날짜에 배당금을 받는 회사가 아니라, 이 날짜까지의 회계기간을 다룬 '
        '정기보고서에 배당이 적힌 회사입니다.'
    ).classes('vh-muted vh-keep-all')

    if not day_entries:
        info_banner('ℹ️ 지금 걸린 필터로는 이 날짜에 표시할 종목이 없습니다.')
        return

    total_pages = max(1, (len(day_entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    current_page = min(view['day_page'], total_pages)
    view['day_page'] = current_page
    start = (current_page - 1) * ITEMS_PER_PAGE
    page_entries = day_entries[start:start + ITEMS_PER_PAGE]

    ui.html(holdings_table_html(
        list(CONFIRMED_HEADERS), [confirmed_row_cells(entry) for entry in page_entries],
    )).classes('w-full')

    if total_pages > 1:
        def _on_page(page: int) -> None:
            view['day_page'] = page
            on_changed()

        pager(total_pages, current_page, _on_page)


# =============================================================================
# 6. 아직 2026년 배당 미확정 (작년 참고)
# =============================================================================
def _render_pending(view, entries, total_pending, on_changed) -> None:
    """🔴 폴백 종목 목록 — **달력 칸에는 절대 들어가지 않는** 종목들입니다."""
    ui.markdown('### ⏳ 아직 2026년 배당 미확정 (작년 참고)')
    ui.label(PENDING_SECTION_NOTICE).classes('vh-muted vh-keep-all whitespace-pre-line')

    if not entries:
        info_banner('ℹ️ 지금 걸린 필터로는 표시할 종목이 없습니다.')
        return

    with_previous = sum(1 for entry in entries if entry['data_quality'] == QUALITY_PREVIOUS)
    ui.label(
        f'표시 대상 {len(entries):,}건 (전체 {total_pending:,}건 중) · '
        f'지난 연도 배당을 보여드릴 수 있는 종목 {with_previous:,}건 · '
        f'기준선에도 배당액이 없어 "데이터 없음" {len(entries) - with_previous:,}건'
    ).classes('vh-muted')

    total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    current_page = min(view['pending_page'], total_pages)
    view['pending_page'] = current_page
    start = (current_page - 1) * ITEMS_PER_PAGE
    page_entries = entries[start:start + ITEMS_PER_PAGE]

    ui.html(holdings_table_html(
        list(PENDING_HEADERS), [pending_row_cells(entry) for entry in page_entries],
    )).classes('w-full')

    def _on_page(page: int) -> None:
        view['pending_page'] = page
        on_changed()

    pager(total_pages, current_page, _on_page)
