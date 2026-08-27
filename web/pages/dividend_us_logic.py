"""
🇺🇸 미국 배당 달력(`/dividend/us`) — **순수 로직만** 모아 둔 모듈.

이 파일에는 NiceGUI 위젯이 하나도 없고, `nicegui` 도 `web.*` 도 import 하지 않습니다.
그래서 서버를 띄우지 않고도(=네트워크·GUI 없이) 이 함수들만 따로 불러 검증할 수 있습니다
(`tests/test_dividend_us_page.py`). 화면 쪽은 `web/pages/dividend_us_page.py` 입니다.

-------------------------------------------------------------------------------
🟡 왜 파일을 둘로 나눴는가 (§0-3-6 모듈 격리 · §0-3-10 단일 출처)
-------------------------------------------------------------------------------
① 한국 배당 화면(`web/pages/dividend_page.py`)은 **이미 실서비스 중**이라 이번 작업에서
   한 글자도 건드리지 않습니다. 달력 격자 계산(`month_weeks`·`date_key`·요일 머리글)처럼
   똑같아 보이는 함수를 그 파일에서 가져다 쓰고 싶어지지만, 그러면
   ⓐ 미국 화면이 한국 배당 모듈에 하드 의존하게 되고,
   ⓑ 그 모듈을 import 하는 순간 `/dividend` 라우트 등록·휴장일표 만료 알람 같은
      **부작용까지 함께 실행**되며,
   ⓒ 한국 쪽을 고칠 때마다 미국 화면이 같이 깨질 수 있습니다.
   그래서 달력 격자용 두 함수만 여기 다시 씁니다 — 중복을 피하는 것보다 **모듈을
   서로 못 건드리게 하는 쪽**이 이 프로젝트에서 더 비싼 원칙입니다.
② 화면 파일(`dividend_us_page.py`)은 `nicegui`·`web.layout`·`web.state` 를 물고 있어
   테스트에서 import 하려면 GUI 스택 전체가 설치돼 있어야 합니다. 순수 함수를 여기로
   빼두면 그 준비 없이도 날짜 파싱·매수 마지막 날 계산·분류 로직을 그대로 검증할 수
   있습니다.

-------------------------------------------------------------------------------
🔴 이 화면이 사실대로 말해야 하는 것 (§0-1)
-------------------------------------------------------------------------------
① 읽는 파일은 `data/us_stocks_latest.json` **하나뿐**입니다. 이 화면을 위해 새로 만든
   수집기는 없습니다 — 매일 도는 기존 미국주식 수집기(`collector_us_stocks.py`)가 만드는
   스냅샷에 이미 들어 있는 `dps`·`div_yield`·`ex_dividend_date`·`dividend_status` 네
   필드를 그대로 읽어 화면만 새로 그립니다.
② `ex_dividend_date` 는 stockanalysis.com 의 **"Statistics" 개요 페이지** 스냅샷 값입니다
   (배당 전용 페이지가 아닙니다). 그래서 이미 발표된 다음 배당이 있는 종목은 **미래
   날짜**가, 아직 발표가 없는 종목은 **가장 최근 과거 날짜**가 들어옵니다 — 어느 쪽인지는
   종목마다 다릅니다. 이 비대칭을 화면에서 숨기지 않고 건수로 밝힙니다.
③ **미래 배당 날짜를 우리가 예측·계산하지 않습니다.** "지난번이 6월 4일이었으니 다음은
   9월 4일쯤" 같은 추정은 배당이 줄거나 끊기는 순간 그대로 틀린 정보가 됩니다. 값이
   없으면 "미확정"이라고 얼버무리지 않고 "아직 다음 배당 발표 안 됨"이라고 적습니다.
④ 우리가 유일하게 **계산**하는 값은 "매수 마지막 날"(배당락일의 직전 미국 거래일)뿐이고,
   그 자리에는 항상 "🧮 계산값" 배지를 답니다(아래 `last_buy_date`).
"""

from datetime import date, timedelta

# =============================================================================
# 상수 — 전부 문자열·튜플·frozenset(불변)입니다. 가변 전역(dict/list/set)은 0개입니다
#        (§0-3-8, `tests/test_web_session_isolation.py::test_no_mutable_globals`).
# =============================================================================

#: 달력 요일 머리글 — **일요일 시작**(`month_weeks()` 의 `firstweekday=6` 과 짝).
#: 한국 배당 화면과 값이 같지만 일부러 따로 둡니다(위 머리말 ①-ⓐ).
WEEKDAY_LABELS = ('일', '월', '화', '수', '목', '금', '토')

#: `dividend_status` 필드가 실제로 가지는 두 값. 실측(2026-08-27, 548종목):
#: collected 403건 · confirmed_none 145건 — 두 값 말고는 없었습니다. 그래도 아래
#: `classify_stock()` 은 "둘 다 아닌 값"을 위한 갈래를 따로 둡니다(수집기가 나중에 값을
#: 늘려도 조용히 collected 취급되지 않도록 — §0-1).
STATUS_COLLECTED = 'collected'
STATUS_CONFIRMED_NONE = 'confirmed_none'

#: 종목 분류 결과. 화면 문구가 아니라 **데이터에 남는 근거**라 영문 상수로 둡니다
#: (한국 배당 화면의 `QUALITY_*` 상수와 같은 관례).
CATEGORY_CALENDAR = 'CALENDAR'                # 달력에 찍히는 종목(날짜 파싱 성공)
CATEGORY_DATE_UNPARSED = 'DATE_UNPARSED'      # 배당은 있는데 날짜 글자를 못 읽음
CATEGORY_NO_DIVIDEND = 'NO_DIVIDEND'          # 배당 없음이 **확인된** 종목
CATEGORY_UNKNOWN_STATUS = 'UNKNOWN_STATUS'    # 위 두 상태값 어느 쪽도 아님

#: 소스가 주는 날짜 글자의 월 이름 표. `datetime.strptime(..., '%b %d, %Y')` 를 쓰지 않는
#: 이유: `%b` 는 **서버의 로케일(LC_TIME)을 따릅니다.** 배포 서버 로케일이 영어가 아니면
#: "Aug" 를 못 읽고 403종목이 통째로 "날짜 형식 오류"가 됩니다. 소스는 항상 영문 월
#: 약어를 주므로, 로케일과 무관하게 우리 표로 직접 읽습니다.
#: (dict 를 쓰면 모듈 최상위 가변 전역이 되어 §0-3-8 검사에 걸리므로 튜플의 튜플입니다.)
_MONTH_ABBREVIATIONS = (
    ('jan', 1), ('feb', 2), ('mar', 3), ('apr', 4), ('may', 5), ('jun', 6),
    ('jul', 7), ('aug', 8), ('sep', 9), ('oct', 10), ('nov', 11), ('dec', 12),
)

# =============================================================================
# 🔴 미국 거래소(NYSE) 휴장일 표 — "매수 마지막 날" 계산 전용
# =============================================================================
#: 2026-08-27 조사.
#:
#: 방법: 한국 배당 화면이 KRX 휴장일 표를 만들 때 쓴 것과 **같은 방식·같은 라이브러리
#: 버전**입니다 — `exchange_calendars` v4.13.2 의 `XNYS`(뉴욕증권거래소) 캘린더에서
#: 2025~2027년 "평일인데 개장하지 않는 날"을 뽑아 아래에 그대로 박아 넣었습니다.
#:
#: ⚠️ **라이브러리를 requirements.txt 에 추가하지 않았습니다.** 확인 결과 이 프로젝트의
#:    `requirements.txt` 에는 `exchange_calendars` 가 들어 있지 않고(2026-08-27 실측),
#:    이 값 때문에 실행 시 의존성을 늘릴 이유가 없습니다 — 필요한 것은 날짜 몇십 개짜리
#:    표 하나뿐이고, 그 표는 개발 시점에 한 번 뽑아 두면 됩니다. 한국 배당 화면의
#:    `KRX_HOLIDAYS_2025_2026` 도 정확히 같은 판단으로 상수 표만 들고 있습니다.
#:
#: 산출 명령(재현용 — 값이 의심되면 이걸 그대로 다시 돌려 비교하세요):
#:     import exchange_calendars as ec, datetime
#:     cal = ec.get_calendar('XNYS', start='2025-01-01', end='2027-12-31')
#:     sessions = {d.date().isoformat() for d in cal.sessions}
#:     # 평일(월~금)인데 sessions 에 없는 날 = 휴장일
#:
#: 교차 확인(자명한 것만 눈으로 대조 — 라이브러리를 그냥 믿지 않기):
#:   · 2025-01-09 … 카터 전 대통령 국가 애도의 날(정규 공휴일이 아닌 임시 휴장)
#:   · 2026-04-03 / 2027-03-26 … 성금요일(Good Friday, 부활절 전 금요일)
#:   · 2026-07-03 … 독립기념일(7/4)이 토요일이라 앞 금요일로 대체 휴장
#:   · 2027-07-05 … 독립기념일(7/4)이 일요일이라 다음 월요일로 대체 휴장
#:   · 2027-12-24 … 성탄절(12/25)이 토요일이라 앞 금요일로 대체 휴장
#:
#: ⚠️ **이 표는 2025·2026·2027년만 확인했습니다.** 그 밖의 해가 필요해지면 위 명령으로
#:    다시 뽑아 채워야 합니다 — 채우지 않은 해에 대해서는 `is_nyse_trading_day()` 가
#:    **일부러 예외를 던져** 조용히 틀린 값을 내지 않습니다(§0-1).
#:    지금 데이터에 들어 있는 배당락일의 범위는 2025-09-02 ~ 2027-02-16 이라(2026-08-27
#:    실측) 세 해로 충분히 덮입니다.
#:
#: ⚠️ **반휴장일(조기 폐장, 예: 추수감사절 다음날 오후 1시 폐장)은 넣지 않았습니다.**
#:    그날도 정규 거래가 열리는 개장일이라 "매수 마지막 날" 계산에는 영향이 없습니다.
NYSE_VERIFIED_YEARS = (2025, 2026, 2027)

NYSE_HOLIDAYS_2025_2027 = frozenset((
    # 2025년 (11일)
    '2025-01-01', '2025-01-09', '2025-01-20', '2025-02-17', '2025-04-18',
    '2025-05-26', '2025-06-19', '2025-07-04', '2025-09-01', '2025-11-27',
    '2025-12-25',
    # 2026년 (10일)
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
    '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    # 2027년 (10일)
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31',
    '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
))


# =============================================================================
# 1. 날짜 읽기 — 못 읽으면 **추측하지 않고 이유를 돌려줍니다**
# =============================================================================
def parse_ex_dividend_date(value):
    """소스가 준 배당락일 글자 → `(date, None)` 또는 못 읽으면 `(None, 사람이 읽는 이유)`.

    소스 형식은 `"Aug 10, 2026"` · `"Sep 4, 2026"` 처럼 **영문 월 약어 + 일 + 연도** 입니다
    (2026-08-27 실측: 값이 있는 403종목 전부가 이 형식 하나였습니다).

    🔴 형식이 다르면 **비슷해 보이는 날짜를 만들어내지 않습니다.** `(None, 이유)` 를
       돌려주고, 호출부는 그 종목을 달력에 넣지 않은 채 "날짜를 못 읽은 건수"로 세어
       화면 안내문에 그대로 남깁니다(§0-1 — 실패를 조용히 삼키지 않기).
    """
    if value is None:
        return None, '배당락일 값이 비어 있습니다'
    text = str(value).strip()
    if not text:
        return None, '배당락일 값이 빈 글자입니다'

    # "Aug 10, 2026" → ['Aug', '10,', '2026']
    parts = text.replace(',', ' ').split()
    if len(parts) != 3:
        return None, f'배당락일 형식이 예상과 다릅니다: "{text}"'

    month_text, day_text, year_text = parts
    month = None
    for abbreviation, number in _MONTH_ABBREVIATIONS:
        if month_text.lower().startswith(abbreviation):
            month = number
            break
    if month is None:
        return None, f'월 이름을 읽지 못했습니다: "{text}"'

    try:
        return date(int(year_text), month, int(day_text)), None
    except ValueError:
        # 일/연도가 숫자가 아니거나(ValueError), 2월 30일처럼 없는 날짜인 경우.
        return None, f'배당락일 숫자를 읽지 못했습니다: "{text}"'


# =============================================================================
# 2. "매수 마지막 날" 계산 — 이 화면이 **유일하게 만들어내는 값**
# =============================================================================
def is_nyse_trading_day(day) -> bool:
    """`date` → 그 날이 뉴욕증권거래소 개장일인가(주말 아님 + 위 휴장일 표에 없음).

    :raises ValueError: `day` 의 연도가 `NYSE_VERIFIED_YEARS` 에 없으면 — 확인 안 된 해를
        "아마 열렸겠지"로 조용히 넘기지 않기 위해서입니다(§0-1).
    """
    if day.year not in NYSE_VERIFIED_YEARS:
        raise ValueError(
            f'{day.year}년 미국 증시 휴장일 표가 아직 확인되지 않았습니다 — '
            '매수 마지막 날을 계산할 수 없습니다(값을 추측하지 않습니다).'
        )
    if day.weekday() >= 5:          # 5=토, 6=일 (`date.weekday()`: 월=0 … 일=6)
        return False
    return day.isoformat() not in NYSE_HOLIDAYS_2025_2027


def previous_nyse_trading_day(day):
    """`day` **바로 이전**의 뉴욕증권거래소 개장일.

    최대 14일 앞까지만 찾습니다(무한 루프 방지 — 그 안에 개장일이 하나도 없다면 휴장일
    표 자체가 잘못됐다는 뜻이라 계속 찾지 않고 예외를 던집니다).

    :raises ValueError: 확인 안 된 해로 넘어가거나, 14일 안에 개장일을 못 찾으면.
    """
    cursor = day
    for _ in range(14):
        cursor = cursor - timedelta(days=1)
        if is_nyse_trading_day(cursor):
            return cursor
    raise ValueError(f'{day.isoformat()} 이전 14일 안에서 미국 증시 개장일을 찾지 '
                     '못했습니다 — 휴장일 표를 다시 확인해야 합니다.')


def last_buy_date(ex_date):
    """배당락일(`date`) → `(매수 마지막 날, None)` 또는 계산 불가능하면 `(None, 이유)`.

    규칙: **배당락일 당일에 사면 이번 배당은 못 받습니다.** 배당을 받으려면 배당락일
    **직전 거래일**까지 사 두어야 합니다 — 미국도 이 규칙은 한국과 같습니다(SEC 공식
    설명으로 확인된 사항). 그래서 계산은 "배당락일의 직전 미국 개장일" 한 줄뿐입니다.

    🟡 한국 배당 화면과 계산하는 대상 자체가 다릅니다. 한국은 원문에 배당락일이 아예 없어
       **배당락일 자체를** 배당기준일에서 계산해 냈지만, 여기서는 소스(stockanalysis)가
       이미 계산된 배당락일을 주므로 우리는 **거기서 하루 앞의 거래일**만 찾습니다.
       그래도 우리가 만든 값이라는 사실은 같아서, 화면에는 똑같이 "🧮 계산값" 배지를
       답니다(§0-1 예시2-보충 — 계산값은 허용하되 반드시 표시).

    🟡 배당락일 자체가 개장일이 아닌 경우(주말·휴일 — 외부 데이터라 있을 수 있습니다)에도
       보정이 따로 필요 없습니다. "그 날보다 앞선 가장 가까운 개장일"이 어차피 정답이라
       같은 한 줄이 그대로 맞습니다.

    🔴 계산할 수 없으면(확인 안 된 연도 등) **아무 날짜나 돌려주지 않습니다** —
       `(None, 이유)` 를 돌려주고 호출부는 그 칸을 비웁니다.
    """
    if ex_date is None:
        return None, '배당락일이 없어 매수 마지막 날을 계산할 수 없습니다'
    try:
        return previous_nyse_trading_day(ex_date), None
    except ValueError as exc:
        return None, str(exc)


# =============================================================================
# 3. 종목 분류 — "배당 없음이 확인됨"과 "모름"을 절대 섞지 않습니다
# =============================================================================
def visible_stocks(stocks):
    """스냅샷의 `stocks` 리스트 → **실제 화면 노출 대상**만.

    `is_visible` 이 False 인 종목은 히스테리시스 버퍼(추적은 하되 화면에는 안 띄우는
    구간)라 제외합니다. 필드가 아예 없는 구버전 스냅샷은 전부 노출(True)로 봅니다 —
    기존 미국주식 화면(`web/pages/us_stocks_page.py`)이 쓰는 것과 같은 규칙입니다.
    """
    return [s for s in (stocks or []) if s.get('is_visible', True)]


def classify_stock(stock):
    """종목 dict 하나 → `(분류, 배당락일 date 또는 None, 사유 또는 None)`.

    갈래는 넷이고, **서로 절대 섞이지 않습니다**:
      · `CATEGORY_NO_DIVIDEND`    … `dividend_status == "confirmed_none"`.
        "배당이 없다는 것이 확인된" 종목입니다. "아직 모름"과 같은 칸에 두면 안 됩니다.
      · `CATEGORY_CALENDAR`       … `collected` + 배당락일 글자를 읽는 데 성공.
      · `CATEGORY_DATE_UNPARSED`  … `collected` 인데 날짜 글자를 못 읽음. 조용히 버리지
        않고 건수로 세어 화면에 남깁니다.
      · `CATEGORY_UNKNOWN_STATUS` … 위 두 상태값 어느 쪽도 아님(수집기가 값을 늘린 경우).
        모르는 값을 `collected` 로 넘겨짚지 않습니다.
    """
    status = stock.get('dividend_status')
    if status == STATUS_CONFIRMED_NONE:
        return CATEGORY_NO_DIVIDEND, None, None
    if status != STATUS_COLLECTED:
        return (CATEGORY_UNKNOWN_STATUS, None,
                f'배당 상태값을 알 수 없습니다: {status!r}')
    parsed, reason = parse_ex_dividend_date(stock.get('ex_dividend_date'))
    if parsed is None:
        return CATEGORY_DATE_UNPARSED, None, reason
    return CATEGORY_CALENDAR, parsed, None


def date_key(year, month, day) -> str:
    """달력 칸 → 날짜별 묶음 조회에 쓰는 'YYYY-MM-DD' 문자열."""
    return f'{year:04d}-{month:02d}-{day:02d}'


def build_entry(stock, ex_date, today):
    """달력에 올릴 종목 하나를 **화면이 쓸 모양**으로 정리합니다.

    `is_future` 는 "오늘 포함, 오늘보다 앞서지 않은 날짜인가" 입니다 — 오늘이 배당락일인
    종목은 이미 늦었으므로(배당락일 당일 매수는 이번 배당을 못 받음) 매수 안내를 띄우면
    안 되는데, 그 판정은 `last_buy_date` 가 오늘보다 이전인지로 화면이 따로 합니다.
    여기서는 "이미 지나간 날짜인지"만 봅니다.
    """
    computed_last_buy, last_buy_reason = last_buy_date(ex_date)
    return {
        'symbol': stock.get('symbol') or '',
        'name': stock.get('name') or '',
        'name_kr': stock.get('name_kr'),
        'name_kr_is_transliterated': bool(stock.get('name_kr_is_transliterated')),
        'rank': stock.get('rank'),
        'dps': stock.get('dps'),
        'div_yield': stock.get('div_yield'),
        'payout_ratio': stock.get('payout_ratio'),
        'price': stock.get('price'),
        'industry': stock.get('industry'),
        'is_reit': bool(stock.get('is_reit')),
        'ex_date': ex_date,
        'ex_date_key': ex_date.isoformat(),
        'ex_date_raw': stock.get('ex_dividend_date'),
        'is_future': ex_date >= today,
        # 🧮 이 화면이 유일하게 만들어내는 값(위 `last_buy_date` 참고).
        'last_buy_date': computed_last_buy,
        'last_buy_reason': last_buy_reason,
    }


def build_view_data(stocks, today):
    """스냅샷 `stocks` + 오늘 날짜 → 화면이 그대로 쓰는 묶음 하나.

    반환 dict(전부 이 함수의 지역 값입니다 — 모듈 전역에 아무것도 남기지 않습니다):
      · `entries`         … 달력에 찍히는 종목(배당락일 오름차순 → 티커 순)
      · `no_dividend`     … 배당 없음이 확인된 종목
      · `unparsed`        … 배당은 있는데 날짜를 못 읽은 종목(사유 포함)
      · `unknown_status`  … 상태값 자체를 모르는 종목(사유 포함)
      · `visible_count`   … `is_visible` 을 통과한 전체 종목 수
      · `future_count` / `past_count` … 달력 종목 중 미래/과거 날짜 건수
    """
    visible = visible_stocks(stocks)
    entries, no_dividend, unparsed, unknown = [], [], [], []

    for stock in visible:
        category, ex_date, reason = classify_stock(stock)
        if category == CATEGORY_CALENDAR:
            entries.append(build_entry(stock, ex_date, today))
        elif category == CATEGORY_NO_DIVIDEND:
            no_dividend.append(stock)
        elif category == CATEGORY_DATE_UNPARSED:
            unparsed.append((stock, reason))
        else:
            unknown.append((stock, reason))

    # 순서를 고정합니다 — 접속할 때마다 목록 순서가 흔들리면 "어제와 다르다"는 오해가
    # 생깁니다. 같은 날짜 안에서는 티커 알파벳 순입니다.
    entries.sort(key=lambda e: (e['ex_date'], e['symbol']))
    no_dividend.sort(key=lambda s: (s.get('rank') if isinstance(s.get('rank'), int) else 10 ** 9,
                                    s.get('symbol') or ''))

    return {
        'entries': entries,
        'no_dividend': no_dividend,
        'unparsed': unparsed,
        'unknown_status': unknown,
        'visible_count': len(visible),
        'future_count': sum(1 for e in entries if e['is_future']),
        'past_count': sum(1 for e in entries if not e['is_future']),
    }


def group_by_ex_date(entries):
    """달력 종목 목록 → `{'YYYY-MM-DD': [종목, …]}`.

    (함수 **지역** dict 입니다 — 모듈 전역 캐시를 만들지 않습니다, §0-3-8.)
    """
    grouped = {}
    for entry in entries or ():
        grouped.setdefault(entry['ex_date_key'], []).append(entry)
    return grouped


# =============================================================================
# 4. 달력 격자 계산 (월 이동 포함)
# =============================================================================
def month_weeks(year, month):
    """그 달의 주 단위 표 — 각 주는 7칸(일~토), 그 달이 아닌 칸은 0.

    표준 라이브러리 `calendar` 를 그대로 씁니다(월별 일수·윤년 규칙을 우리가 다시 짜지
    않습니다). `firstweekday=6` 이 일요일 시작이고, 위 `WEEKDAY_LABELS` 와 짝입니다.
    """
    import calendar as calendar_module          # 지역 import — 모듈 전역을 늘리지 않습니다
    return calendar_module.Calendar(firstweekday=6).monthdayscalendar(year, month)


def available_months(entries, today):
    """달력에서 오갈 수 있는 달 목록 `[(연, 월), …]` — **데이터가 실제로 덮는 범위**만.

    🟡 한국 배당 화면은 한 해(1~12월) 안에서만 움직이면 됐지만, 이 화면의 배당락일은
       연도를 걸칩니다(2026-08-27 실측: 2025-09-02 ~ 2027-02-16). 그래서 "1~12월 선택기"가
       아니라 **가장 이른 달 ~ 가장 늦은 달을 한 줄로 이어 놓은 목록**으로 움직입니다.

    오늘이 속한 달은 데이터가 없어도 항상 포함합니다 — 기본으로 여는 달이 목록에 없으면
    화면이 열리자마자 엉뚱한 달로 튕기기 때문입니다.
    """
    months = {(today.year, today.month)}
    for entry in entries or ():
        months.add((entry['ex_date'].year, entry['ex_date'].month))
    if not months:
        return []
    (start_year, start_month) = min(months)
    (end_year, end_month) = max(months)

    ordered = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        ordered.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ordered


def shift_month(year, month, delta):
    """`(연, 월)` 에서 `delta` 달만큼 이동한 `(연, 월)`. 연도 경계를 알아서 넘어갑니다."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_label(year, month) -> str:
    """월 선택기·안내문에 쓰는 사람이 읽는 달 이름."""
    return f'{year}년 {month}월'


def count_in_month(entries, year, month) -> int:
    """그 달에 배당락일이 잡힌 종목 수(지금 필터를 통과한 목록 기준)."""
    return sum(1 for entry in entries or ()
               if (entry['ex_date'].year, entry['ex_date'].month) == (year, month))


def value_range(entries, field):
    """한 날짜에 여러 종목이 몰릴 때 달력 칸에 적을 `(최솟값, 최댓값)`.

    🔴 평균을 내지 않습니다. 평균은 그 날 어느 종목에도 해당하지 않는 **우리가 만든
       숫자**라, 달력 칸처럼 좁은 자리에 두면 특정 종목의 값으로 오해받습니다. 실제로
       존재하는 두 값(가장 작은 것·가장 큰 것)만 그대로 보여줍니다(§0-1).

    값이 하나도 없으면 `(None, None)` 입니다 — 0 으로 채우지 않습니다.
    """
    values = [entry.get(field) for entry in entries or ()]
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None, None
    return min(values), max(values)


# =============================================================================
# 5. 오늘 날짜 (미국 동부 시간 기준)
# =============================================================================
def today_et():
    """오늘 날짜(미국 동부 시간) — 이 화면의 "오늘"은 **미국 장 기준**입니다.

    서버가 UTC 로 돌든 한국 시간으로 돌든 같은 답을 내야 하므로 `date.today()` 를 그대로
    쓰지 않습니다. 한국 배당 화면이 KST 로 고정해 두는 것과 같은 이유이고, 여기서는
    다루는 대상이 미국 증시라 기준 시간대만 다릅니다.

    ⚠️ 서머타임(DST) 전환을 표준 라이브러리 `zoneinfo` 에 맡깁니다 — 오프셋을 -5 시간으로
       박아 두면 3~11월(EDT)에 하루가 어긋날 수 있습니다. `zoneinfo` 는 파이썬 3.9 이후
       표준이라 새 의존성이 아닙니다. 만약 시간대 데이터베이스가 없는 환경이면 예외 대신
       UTC 날짜로 물러섭니다(화면이 통째로 죽는 것보다 낫고, 어긋나도 하루 이내입니다).
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    now_utc = datetime.now(timezone.utc)
    try:
        return now_utc.astimezone(ZoneInfo('America/New_York')).date()
    except (ZoneInfoNotFoundError, KeyError):
        return now_utc.date()
