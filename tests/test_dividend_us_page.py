"""
🇺🇸 미국 배당 달력(`/dividend/us`) 순수 함수 오프라인 검증 — 네트워크 불필요 · pytest.

실행: pytest -q tests/test_dividend_us_page.py

────────────────────────────────────────────────────────────────────────────────
📌 이 파일이 검증하는 것 = `web/pages/dividend_us_logic.py` 의 **순수 함수 전부**
   (배당락일 글자 파싱 · 매수 마지막 날 계산 · 종목 분류 · 달력 격자/월 이동).
   화면 파일(`web/pages/dividend_us_page.py`)은 `nicegui` 를 물고 있어 여기서 import 하지
   않습니다 — 그래서 GUI 스택이 설치돼 있지 않아도 이 테스트는 그대로 돕니다.
   (화면과 로직을 왜 두 파일로 나눴는지는 `dividend_us_logic.py` 머리말 참고.)

📌 픽스처는 **지어내지 않았습니다.** 아래 종목 dict 는 전부
   `data/us_stocks_latest.json`(2026-08-27 스냅샷)에서 실제로 뽑아 온 값이고,
   이 테스트에 필요한 필드만 남기고 **값은 한 글자도 고치지 않았습니다.**
   각 상수 주석에 어떤 종목을 왜 골랐는지 적어 두었습니다. 실데이터로 만들 수 없는
   실패 시나리오(형식이 깨진 날짜 등)에만 합성 dict 를 쓰고, 합성인 것을 주석에
   명시했습니다.

⚠️ 이 테스트가 전부 통과해도 "화면이 예쁘게 그려진다"는 뜻은 아닙니다. 여기서 보는 것은
   **숫자와 날짜가 거짓말을 하지 않는가** 뿐입니다(§0-1).
"""
import os
import sys
from datetime import date

import pytest

# 저장소 루트를 import 경로에 넣습니다(`web.pages.dividend_us_logic` 를 패키지 경로로
# 읽기 위해서 — 이 파일은 tests/ 아래에 있습니다).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.pages.dividend_us_logic import (            # noqa: E402
    CATEGORY_CALENDAR,
    CATEGORY_DATE_UNPARSED,
    CATEGORY_NO_DIVIDEND,
    CATEGORY_UNKNOWN_STATUS,
    NYSE_VERIFIED_YEARS,
    WEEKDAY_LABELS,
    available_months,
    build_view_data,
    classify_stock,
    count_in_month,
    date_key,
    group_by_ex_date,
    is_nyse_trading_day,
    last_buy_date,
    month_label,
    month_weeks,
    parse_ex_dividend_date,
    previous_nyse_trading_day,
    shift_month,
    value_range,
    visible_stocks,
)

# =============================================================================
# 픽스처 — data/us_stocks_latest.json (2026-08-27 스냅샷)에서 그대로 뽑은 실데이터
# =============================================================================
#: 🟢 배당락일이 **미래**인 종목들.
#:   · GOOGL "Sep 4, 2026"  … 2026년 노동절(9/7 월) 직전 금요일이라, 매수 마지막 날이
#:                            휴장일을 건너뛰는지 확인하기 좋은 사례
#:   · KO    "Sep 15, 2026" … 평범한 화요일(= 직전 거래일이 바로 전날 월요일)
#:   · WMT   "Dec 11, 2026" … 연말, 달을 걸친 이동 확인용
#:   · BG    "Feb 16, 2027" … 스냅샷에서 **가장 먼 미래 날짜**. 2027년 프레지던츠데이
#:                            (2/15 월)가 휴장이라 매수 마지막 날이 2/12(금)로 밀립니다
#:   · O     "Aug 31, 2026" … 리츠(is_reit=True), 월요일
FIXTURE_FUTURE = [
    {"symbol": "GOOGL", "name": "Alphabet Inc. Class A Common Stock",
     "name_kr": "알파벳(구글) A", "name_kr_is_transliterated": False, "rank": 3,
     "is_visible": True, "dps": 0.88, "div_yield": 0.26,
     "ex_dividend_date": "Sep 4, 2026", "dividend_status": "collected",
     "payout_ratio": 4.42, "industry": "Technology", "is_reit": False, "price": 342.0},
    {"symbol": "KO", "name": "Coca-Cola Company (The) Common Stock",
     "name_kr": "코카콜라", "name_kr_is_transliterated": False, "rank": 30,
     "is_visible": True, "dps": 2.12, "div_yield": 2.35,
     "ex_dividend_date": "Sep 15, 2026", "dividend_status": "collected",
     "payout_ratio": 63.71, "industry": "Consumer Staples", "is_reit": False, "price": 90.08},
    {"symbol": "WMT", "name": "Walmart Inc. Common Stock",
     "name_kr": "월마트", "name_kr_is_transliterated": False, "rank": 16,
     "is_visible": True, "dps": 0.99, "div_yield": 0.95,
     "ex_dividend_date": "Dec 11, 2026", "dividend_status": "collected",
     "payout_ratio": 35.87, "industry": "Consumer Discretionary", "is_reit": False,
     "price": 104.34},
    {"symbol": "BG", "name": "Bunge Limited Common Shares",
     "name_kr": "번지", "name_kr_is_transliterated": True, "rank": 446,
     "is_visible": True, "dps": 2.88, "div_yield": 2.54,
     "ex_dividend_date": "Feb 16, 2027", "dividend_status": "collected",
     "payout_ratio": 56.19, "industry": "Consumer Staples", "is_reit": False, "price": 113.25},
    {"symbol": "O", "name": "Realty Income Corporation Common Stock",
     "name_kr": "리얼티인컴", "name_kr_is_transliterated": False, "rank": 205,
     "is_visible": True, "dps": 3.25, "div_yield": 5.22,
     "ex_dividend_date": "Aug 31, 2026", "dividend_status": "collected",
     "payout_ratio": 237.65, "industry": "Real Estate", "is_reit": True, "price": 62.26},
]

#: ⚪ 배당락일이 **과거**인 종목들(= 아직 다음 배당 발표가 없는 종목).
#:   NVDA·AAPL·MSFT 는 시가총액 상위이면서도 과거 날짜뿐인 대표 사례입니다.
FIXTURE_PAST = [
    {"symbol": "NVDA", "name": "NVIDIA Corporation Common Stock",
     "name_kr": "엔비디아", "name_kr_is_transliterated": False, "rank": 1,
     "is_visible": True, "dps": 1.0, "div_yield": 0.48,
     "ex_dividend_date": "Jun 4, 2026", "dividend_status": "collected",
     "payout_ratio": 3.54, "industry": "Technology", "is_reit": False, "price": 209.66},
    {"symbol": "AAPL", "name": "Apple Inc. Common Stock",
     "name_kr": "애플", "name_kr_is_transliterated": False, "rank": 2,
     "is_visible": True, "dps": 1.08, "div_yield": 0.34,
     "ex_dividend_date": "Aug 10, 2026", "dividend_status": "collected",
     "payout_ratio": 12.39, "industry": "Technology", "is_reit": False, "price": 313.45},
    {"symbol": "MSFT", "name": "Microsoft Corporation Common Stock",
     "name_kr": "마이크로소프트", "name_kr_is_transliterated": False, "rank": 5,
     "is_visible": True, "dps": 3.64, "div_yield": 0.73,
     "ex_dividend_date": "Aug 20, 2026", "dividend_status": "collected",
     "payout_ratio": 20.28, "industry": "Technology", "is_reit": False, "price": 496.37},
]

#: 🚫 배당 없음이 **확인된** 종목. 실측상 이 상태의 종목은 `ex_dividend_date` 가 전부
#:    None 이고 `dps`·`div_yield` 도 None 입니다(2026-08-27: 145종목 전부).
FIXTURE_NO_DIVIDEND = [
    {"symbol": "AMZN", "name": "Amazon.com Inc. Common Stock",
     "name_kr": "아마존", "name_kr_is_transliterated": False, "rank": 6,
     "is_visible": True, "dps": None, "div_yield": None,
     "ex_dividend_date": None, "dividend_status": "confirmed_none",
     "payout_ratio": None, "industry": "Consumer Discretionary", "is_reit": False,
     "price": 260.28},
    {"symbol": "TSLA", "name": "Tesla Inc. Common Stock",
     "name_kr": "테슬라", "name_kr_is_transliterated": False, "rank": 10,
     "is_visible": True, "dps": None, "div_yield": None,
     "ex_dividend_date": None, "dividend_status": "confirmed_none",
     "payout_ratio": None, "industry": "Industrials", "is_reit": False, "price": 345.82},
    {"symbol": "BRK/B", "name": "Berkshire Hathaway Inc.",
     "name_kr": "버크셔해서웨이 B", "name_kr_is_transliterated": False, "rank": 12,
     "is_visible": True, "dps": None, "div_yield": None,
     "ex_dividend_date": None, "dividend_status": "confirmed_none",
     "payout_ratio": None, "industry": "Uncategorized", "is_reit": False, "price": 504.91},
]

#: ⚠️ **합성 픽스처** — 아래 두 dict 는 실데이터가 아닙니다.
#:    2026-08-27 스냅샷에는 "collected 인데 날짜를 못 읽는" 종목이 0건이고(403건 전부
#:    파싱 성공), 상태값이 두 값 말고 다른 것인 종목도 0건입니다. 그래도 그 상황이
#:    닥쳤을 때 화면이 **조용히 넘기지 않고 건수로 남기는지**는 반드시 검증해야 해서,
#:    실데이터로는 만들 수 없는 이 두 경우만 합성으로 만들었습니다. 실데이터에서 온
#:    필드 이름·모양은 그대로 유지했습니다.
FIXTURE_SYNTHETIC_BROKEN_DATE = {
    "symbol": "ZZTEST", "name": "Synthetic Broken Date Corp.",
    "name_kr": None, "name_kr_is_transliterated": False, "rank": 999,
    "is_visible": True, "dps": 1.23, "div_yield": 1.0,
    "ex_dividend_date": "2026-09-04",          # ← 소스 형식("Sep 4, 2026")이 아님
    "dividend_status": "collected",
    "payout_ratio": None, "industry": "Technology", "is_reit": False, "price": 10.0,
}
FIXTURE_SYNTHETIC_UNKNOWN_STATUS = {
    "symbol": "ZZUNK", "name": "Synthetic Unknown Status Corp.",
    "name_kr": None, "name_kr_is_transliterated": False, "rank": 998,
    "is_visible": True, "dps": None, "div_yield": None,
    "ex_dividend_date": None,
    "dividend_status": "pending_review",       # ← 수집기가 값을 늘린 상황을 흉내
    "payout_ratio": None, "industry": "Technology", "is_reit": False, "price": 10.0,
}

#: 🙈 버퍼 구간(추적은 하되 화면에는 안 띄우는 종목)을 흉내 낸 **합성** dict.
#:    2026-08-27 스냅샷은 `hidden_buffer_count: 0` 이라 실데이터에 이 경우가 없습니다.
FIXTURE_SYNTHETIC_HIDDEN = dict(FIXTURE_PAST[0], symbol="ZZHID", is_visible=False)

#: 검사 기준일 — 스냅샷을 뜬 날(2026-08-27)로 고정합니다. `date.today()` 를 쓰면
#: 내일 이 테스트가 이유 없이 깨집니다.
TODAY = date(2026, 8, 27)


# =============================================================================
# 1. 배당락일 글자 파싱
# =============================================================================
def test_실데이터_형식을_그대로_읽는다():
    """스냅샷에 실제로 들어 있는 형식 두 가지(한 자리 일 / 두 자리 일)를 다 읽어야 합니다."""
    assert parse_ex_dividend_date("Sep 4, 2026") == (date(2026, 9, 4), None)
    assert parse_ex_dividend_date("Aug 10, 2026") == (date(2026, 8, 10), None)
    assert parse_ex_dividend_date("Feb 16, 2027") == (date(2027, 2, 16), None)
    assert parse_ex_dividend_date("Dec 11, 2026") == (date(2026, 12, 11), None)


def test_열두_달_이름을_모두_읽는다():
    """월 이름 표에 빠진 달이 없어야 합니다(하나라도 빠지면 그 달 배당이 통째로 사라짐)."""
    names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    for number, name in enumerate(names, start=1):
        parsed, reason = parse_ex_dividend_date(f"{name} 15, 2026")
        assert reason is None, f"{name} 를 읽지 못했습니다: {reason}"
        assert parsed == date(2026, number, 15)


def test_로케일에_기대지_않는다(monkeypatch):
    """서버 로케일(LC_TIME)이 영어가 아니어도 같은 답이 나와야 합니다.

    `datetime.strptime(..., '%b ...')` 를 썼다면 여기서 깨집니다 — 그래서 이 화면은
    월 이름 표를 직접 들고 있습니다.
    """
    monkeypatch.setenv("LC_TIME", "ko_KR.UTF-8")
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert parse_ex_dividend_date("Aug 10, 2026") == (date(2026, 8, 10), None)


@pytest.mark.parametrize("bad", [None, "", "   ", "2026-09-04", "Sep 2026",
                                 "Xyz 4, 2026", "Sep abc, 2026", "Feb 30, 2026"])
def test_못_읽는_값은_날짜를_지어내지_않는다(bad):
    """🔴 §0-1 — 못 읽으면 비슷한 날짜를 만들지 않고 `(None, 이유)` 를 돌려줘야 합니다."""
    parsed, reason = parse_ex_dividend_date(bad)
    assert parsed is None
    assert reason and isinstance(reason, str), "사람이 읽을 사유가 반드시 있어야 합니다"


# =============================================================================
# 2. 매수 마지막 날 계산 (= 이 화면이 유일하게 만들어내는 값)
# =============================================================================
def test_평범한_날은_바로_전날():
    """2026-09-15(화)의 직전 거래일은 9/14(월)."""
    computed, reason = last_buy_date(date(2026, 9, 15))
    assert reason is None
    assert computed == date(2026, 9, 14)


def test_주말을_건너뛴다():
    """2026-08-31(월)의 직전 거래일은 8/28(금) — 주말 이틀을 건너뜁니다."""
    computed, reason = last_buy_date(date(2026, 8, 31))
    assert reason is None
    assert computed == date(2026, 8, 28)


def test_노동절_휴장일을_건너뛴다():
    """2026-09-08(화)의 직전 거래일은 9/4(금).

    9/7(월)은 노동절 휴장, 9/5~9/6은 주말이라 금요일까지 밀립니다. 휴장일 표를 안 보고
    "그냥 하루 전"으로 계산했다면 9/7(휴장일)이 나와 틀립니다.
    """
    computed, reason = last_buy_date(date(2026, 9, 8))
    assert reason is None
    assert computed == date(2026, 9, 4)


def test_2027년_프레지던츠데이를_건너뛴다():
    """실데이터(BG, "Feb 16, 2027")의 매수 마지막 날은 2027-02-12(금).

    2/15(월)이 프레지던츠데이 휴장이고 2/13~14가 주말입니다. 스냅샷에서 가장 먼 미래
    날짜라, 휴장일 표가 2027년까지 실제로 덮고 있는지를 이 한 건이 증명합니다.
    """
    computed, reason = last_buy_date(date(2027, 2, 16))
    assert reason is None
    assert computed == date(2027, 2, 12)


def test_배당락일이_휴장일이어도_직전_개장일을_찾는다():
    """외부 데이터라 배당락일 자체가 주말·휴일일 수 있습니다 — 그때도 답은 "그 날보다
    앞선 가장 가까운 개장일" 하나입니다(별도 보정 규칙이 필요 없음)."""
    assert last_buy_date(date(2026, 12, 25))[0] == date(2026, 12, 24)   # 성탄절(휴장)
    assert last_buy_date(date(2026, 9, 5))[0] == date(2026, 9, 4)       # 토요일


def test_휴장일_표에_없는_해는_계산하지_않는다():
    """🔴 §0-1 — 확인 안 된 해를 "아마 열렸겠지"로 넘기지 않고 값을 비웁니다."""
    unverified_year = max(NYSE_VERIFIED_YEARS) + 1
    computed, reason = last_buy_date(date(unverified_year, 6, 10))
    assert computed is None
    assert str(unverified_year) in reason


def test_개장일_판정_자체():
    """휴장일 표와 주말 판정이 실제로 동작하는지 직접 확인합니다."""
    assert is_nyse_trading_day(date(2026, 9, 4)) is True        # 금요일, 평일
    assert is_nyse_trading_day(date(2026, 9, 5)) is False       # 토요일
    assert is_nyse_trading_day(date(2026, 9, 7)) is False       # 노동절
    assert is_nyse_trading_day(date(2026, 4, 3)) is False       # 성금요일
    assert is_nyse_trading_day(date(2026, 7, 3)) is False       # 독립기념일 대체 휴장
    with pytest.raises(ValueError):
        is_nyse_trading_day(date(max(NYSE_VERIFIED_YEARS) + 1, 6, 10))


def test_직전_개장일_함수는_당일을_돌려주지_않는다():
    """"직전"이므로 개장일이더라도 그 날 자신은 답이 아닙니다."""
    assert previous_nyse_trading_day(date(2026, 9, 4)) == date(2026, 9, 3)


# =============================================================================
# 3. 종목 분류 — "배당 없음 확인"과 "모름"을 절대 섞지 않습니다
# =============================================================================
def test_분류_네_갈래가_섞이지_않는다():
    assert classify_stock(FIXTURE_FUTURE[0])[0] == CATEGORY_CALENDAR
    assert classify_stock(FIXTURE_PAST[0])[0] == CATEGORY_CALENDAR
    assert classify_stock(FIXTURE_NO_DIVIDEND[0])[0] == CATEGORY_NO_DIVIDEND
    assert classify_stock(FIXTURE_SYNTHETIC_BROKEN_DATE)[0] == CATEGORY_DATE_UNPARSED
    assert classify_stock(FIXTURE_SYNTHETIC_UNKNOWN_STATUS)[0] == CATEGORY_UNKNOWN_STATUS


def test_배당없음_확인_종목은_날짜를_만들지_않는다():
    """confirmed_none 종목은 배당락일이 None 이고, 달력에 절대 들어가지 않습니다."""
    for stock in FIXTURE_NO_DIVIDEND:
        category, ex_date, _reason = classify_stock(stock)
        assert category == CATEGORY_NO_DIVIDEND
        assert ex_date is None


def test_상태값을_모르면_배당있음으로_넘겨짚지_않는다():
    """수집기가 새 상태값을 추가해도 조용히 collected 로 취급되면 안 됩니다."""
    category, ex_date, reason = classify_stock(FIXTURE_SYNTHETIC_UNKNOWN_STATUS)
    assert category == CATEGORY_UNKNOWN_STATUS
    assert ex_date is None
    assert "pending_review" in reason


def test_버퍼_종목은_화면_대상에서_빠진다():
    """`is_visible=False` 는 제외하고, 필드가 없는 구버전 스냅샷은 노출로 봅니다."""
    stocks = FIXTURE_PAST + [FIXTURE_SYNTHETIC_HIDDEN]
    symbols = {s["symbol"] for s in visible_stocks(stocks)}
    assert "ZZHID" not in symbols
    assert len(symbols) == len(FIXTURE_PAST)

    legacy = {"symbol": "ZZOLD"}                    # is_visible 필드 자체가 없는 경우
    assert visible_stocks([legacy]) == [legacy]


# =============================================================================
# 4. 화면이 그대로 쓰는 묶음 (build_view_data)
# =============================================================================
def _all_fixtures():
    return (FIXTURE_FUTURE + FIXTURE_PAST + FIXTURE_NO_DIVIDEND
            + [FIXTURE_SYNTHETIC_BROKEN_DATE, FIXTURE_SYNTHETIC_UNKNOWN_STATUS,
               FIXTURE_SYNTHETIC_HIDDEN])


def test_모든_종목이_어느_칸엔가_들어가고_합이_맞는다():
    """🔴 §0-1 — 어떤 종목도 조용히 사라지면 안 됩니다. 네 갈래 합 = 노출 종목 수."""
    data = build_view_data(_all_fixtures(), TODAY)
    total = (len(data["entries"]) + len(data["no_dividend"])
             + len(data["unparsed"]) + len(data["unknown_status"]))
    assert total == data["visible_count"]
    assert data["visible_count"] == len(_all_fixtures()) - 1     # 버퍼 1건 제외


def test_미래_과거_건수가_따로_세어진다():
    data = build_view_data(_all_fixtures(), TODAY)
    assert data["future_count"] == len(FIXTURE_FUTURE)
    assert data["past_count"] == len(FIXTURE_PAST)
    assert data["future_count"] + data["past_count"] == len(data["entries"])


def test_날짜_파싱_실패는_숨기지_않고_사유와_함께_남는다():
    data = build_view_data(_all_fixtures(), TODAY)
    assert len(data["unparsed"]) == 1
    stock, reason = data["unparsed"][0]
    assert stock["symbol"] == "ZZTEST"
    assert reason and "2026-09-04" in reason


def test_달력_목록은_날짜_티커_순으로_고정된다():
    """접속할 때마다 순서가 흔들리면 "어제와 다르다"는 오해가 생깁니다."""
    data = build_view_data(_all_fixtures(), TODAY)
    keys = [(e["ex_date"], e["symbol"]) for e in data["entries"]]
    assert keys == sorted(keys)


def test_미래_종목에만_매수_마지막_날이_계산된다():
    """과거 날짜에도 계산은 되지만(값 자체는 존재), 화면이 쓰는 판정 필드는 `is_future`
    입니다. 여기서는 미래 종목의 계산값이 실제로 맞는지를 실데이터로 확인합니다."""
    data = build_view_data(_all_fixtures(), TODAY)
    computed = {e["symbol"]: e["last_buy_date"] for e in data["entries"] if e["is_future"]}
    assert computed["GOOGL"] == date(2026, 9, 3)     # 9/4(금) 배당락 → 9/3(목)
    assert computed["O"] == date(2026, 8, 28)        # 8/31(월) 배당락 → 8/28(금)
    assert computed["KO"] == date(2026, 9, 14)
    assert computed["WMT"] == date(2026, 12, 10)
    assert computed["BG"] == date(2027, 2, 12)       # 프레지던츠데이 건너뜀


def test_오늘이_배당락일이면_지난_날짜로_치지_않는다():
    """오늘 == 배당락일이면 `is_future` 는 True 입니다(달력에서 회색으로 죽이지 않음).
    다만 "오늘 사도 늦었다"는 사실은 매수 마지막 날(= 어제 이전)이 이미 지났다는 것으로
    화면에서 드러납니다."""
    same_day = dict(FIXTURE_FUTURE[1], ex_dividend_date="Aug 27, 2026")
    data = build_view_data([same_day], date(2026, 8, 27))
    assert data["entries"][0]["is_future"] is True
    assert data["entries"][0]["last_buy_date"] == date(2026, 8, 26)


# =============================================================================
# 5. 달력 격자 · 월 이동
# =============================================================================
def test_요일_머리글은_일요일_시작():
    assert WEEKDAY_LABELS[0] == "일"
    assert len(WEEKDAY_LABELS) == 7
    # 2026-08-27 은 목요일 → 파이썬 weekday()=3 → (3+1)%7=4 → WEEKDAY_LABELS[4]='목'
    assert WEEKDAY_LABELS[(TODAY.weekday() + 1) % 7] == "목"


def test_달력_격자_첫칸이_일요일():
    weeks = month_weeks(2026, 9)
    assert len(weeks[0]) == 7
    # 2026-09-01 은 화요일 → 첫 주는 [0, 0, 1, 2, 3, 4, 5]
    assert weeks[0] == [0, 0, 1, 2, 3, 4, 5]


def test_날짜_키_형식():
    assert date_key(2026, 9, 4) == "2026-09-04"
    assert date_key(2027, 2, 16) == "2027-02-16"


def test_날짜별_묶음():
    entries = build_view_data(_all_fixtures(), TODAY)["entries"]
    grouped = group_by_ex_date(entries)
    assert [e["symbol"] for e in grouped["2026-09-04"]] == ["GOOGL"]
    assert sum(len(v) for v in grouped.values()) == len(entries)


def test_월_이동은_연도_경계를_넘는다():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2027, 1, -1) == (2026, 12)
    assert shift_month(2026, 8, 6) == (2027, 2)
    assert shift_month(2026, 1, -1) == (2025, 12)


def test_오갈_수_있는_달은_데이터_범위를_빠짐없이_잇는다():
    """실데이터 범위(2026-06 … 2027-02)를 중간에 구멍 없이 이어야 합니다 — 데이터가 없는
    달(2026-10·11)도 건너뛰지 않고 목록에 있어야 이전/다음 버튼이 막히지 않습니다."""
    entries = build_view_data(_all_fixtures(), TODAY)["entries"]
    months = available_months(entries, TODAY)
    assert months[0] == (2026, 6)
    assert months[-1] == (2027, 2)
    assert (2026, 10) in months and (2026, 11) in months
    assert months == sorted(months)
    assert len(months) == 9


def test_오늘이_속한_달은_데이터가_없어도_포함된다():
    """기본으로 여는 달이 목록에 없으면 화면이 열리자마자 엉뚱한 달로 튕깁니다."""
    only_future = build_view_data(FIXTURE_FUTURE, date(2026, 3, 15))["entries"]
    months = available_months(only_future, date(2026, 3, 15))
    assert months[0] == (2026, 3)


def test_그_달의_건수_세기():
    entries = build_view_data(_all_fixtures(), TODAY)["entries"]
    assert count_in_month(entries, 2026, 9) == 2        # GOOGL, KO
    assert count_in_month(entries, 2026, 8) == 3        # O, AAPL, MSFT
    assert count_in_month(entries, 2026, 10) == 0
    assert count_in_month(entries, 2027, 2) == 1        # BG


def test_월_이름_문구():
    assert month_label(2026, 9) == "2026년 9월"


# =============================================================================
# 6. 달력 칸 숫자 — 평균을 만들지 않습니다
# =============================================================================
def test_최소_최대만_쓰고_평균을_만들지_않는다():
    """🔴 §0-1 — 평균은 그 날 어느 종목에도 해당하지 않는 우리가 만든 숫자입니다."""
    entries = build_view_data(FIXTURE_FUTURE, TODAY)["entries"]
    same_day = [e for e in entries if e["ex_date_key"] == "2026-09-04"]
    assert value_range(same_day, "dps") == (0.88, 0.88)      # 한 종목이면 그 값 그대로

    two = [e for e in entries if e["symbol"] in ("GOOGL", "O")]
    low, high = value_range(two, "dps")
    assert (low, high) == (0.88, 3.25)                       # 실제로 존재하는 두 값
    average = sum(e["dps"] for e in two) / len(two)
    assert low != average and high != average                # 평균은 어디에도 안 나옴


def test_값이_없으면_0으로_채우지_않는다():
    assert value_range([], "dps") == (None, None)
    assert value_range([{"dps": None}], "dps") == (None, None)


# =============================================================================
# 7. 실 데이터 파일로 한 번 더 (파일이 있을 때만 — 네트워크는 쓰지 않습니다)
# =============================================================================
def test_실제_스냅샷_파일로_돌려본다():
    """`data/us_stocks_latest.json` 을 **파일에서 읽어** 분류가 통째로 도는지 확인합니다.

    숫자를 여기에 박아 두지는 않습니다 — 그 파일은 매일 갱신되므로 건수를 고정하면
    내일 이 테스트가 이유 없이 깨집니다. 대신 **불변식**만 봅니다:
      · 네 갈래의 합이 노출 종목 수와 정확히 같다(어떤 종목도 조용히 사라지지 않는다)
      · 달력 종목은 전부 배당락일과 'YYYY-MM-DD' 키를 가진다
      · 배당 없음 확인 종목은 하나도 달력에 섞이지 않는다
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "data", "us_stocks_latest.json")
    if not os.path.exists(path):
        pytest.skip("data/us_stocks_latest.json 이 없어 건너뜁니다(수집 전 환경).")

    import json
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    data = build_view_data(payload.get("stocks") or [], TODAY)
    total = (len(data["entries"]) + len(data["no_dividend"])
             + len(data["unparsed"]) + len(data["unknown_status"]))
    assert total == data["visible_count"]
    assert data["visible_count"] > 0

    for entry in data["entries"]:
        assert entry["ex_date"] is not None
        assert entry["ex_date_key"] == entry["ex_date"].isoformat()
    calendar_symbols = {e["symbol"] for e in data["entries"]}
    none_symbols = {s.get("symbol") for s in data["no_dividend"]}
    assert not (calendar_symbols & none_symbols)
