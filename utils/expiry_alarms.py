"""
utils/expiry_alarms.py
🔴 2026-08-25 신규 — 손으로 조사해서 만든 날짜표(예: KRX 휴장일 표)가 "검증된 연도" 밖으로
   넘어가기 전에 미리 시끄럽게 알리기 위한 아주 작은 유틸입니다.

왜 따로 파일을 팠는가 — 이 알람을 부르고 싶은 쪽(예: 매일 도는 배당 지급이벤트 수집기,
`collector_dividend_payment_kr.py`)은 `web/` 아래를 import 하면 안 됩니다(nicegui 등
무거운 의존성이 딸려옵니다 — collector는 web 없이 독립 실행 가능해야 한다는 게 이 저장소의
디렉터리 관례입니다, ENGINEERING_SPEC.md §10). 그래서 실제 휴장일 표·계산 로직
(`is_krx_trading_day()` 등)은 그대로 `web/pages/dividend_page.py`에 두고, 여기서는
"언제부터 시끄럽게 경고할지"만 판단합니다 — 이 파일이 아는 건 datetime 뿐입니다.

배경 — 무엇을 막으려는 알람인가:
   `web/pages/dividend_page.py::is_krx_trading_day()`는 확인 안 된 연도를 만나면 조용히
   틀린 값을 내는 대신 **일부러 ValueError를 던집니다**(§0-1 — 추측 금지). 설계 자체는
   맞습니다. 문제는 그 순간까지 아무도 미리 알려주지 않는다는 것이었습니다 — 이 파일이
   그 공백을 메웁니다.
"""

from datetime import date


def warn_if_expiring(label: str, last_verified_year: int, *, lead_days: int = 60) -> bool:
    """
    `label`로 표시된 날짜표가 `last_verified_year`년까지만 검증돼 있을 때, 그 다음 해
    1월 1일이 `lead_days`일 이내로 다가왔거나 이미 지났으면 표준출력에 큰 경고를 찍습니다.

    실패하지 않습니다(경고만 찍고 항상 정상 반환) — 호출부의 원래 작업(수집·배치)을
    이 알람 때문에 막으면 안 되기 때문입니다. 시끄럽게 실패해야 하는 자리는 이미
    `is_krx_trading_day()` 본인이 맡고 있고, 여기는 그보다 훨씬 전에 사람 눈에 띄는 게
    목적입니다.

    :param label: 로그에 찍을 이름 — 어떤 날짜표 얘기인지 알 수 있게.
    :param last_verified_year: 이 표가 검증된 마지막 연도.
    :param lead_days: 다음 해 1/1 며칠 전부터 경고를 시작할지 (기본 60일).
    :return: 경고를 찍었으면 True (호출부가 요약에 반영하고 싶을 때 사용).
    """
    cutoff = date(last_verified_year + 1, 1, 1)
    today = date.today()
    days_left = (cutoff - today).days
    if days_left > lead_days:
        return False

    if days_left < 0:
        urgency = f"이미 {-days_left}일 지났습니다 — 지금 이 표를 쓰는 계산은 예외를 던지고 있을 가능성이 높습니다"
    elif days_left <= 14:
        urgency = f"앞으로 {days_left}일밖에 안 남았습니다"
    else:
        urgency = f"앞으로 {days_left}일 남았습니다"

    print(
        f"\n{'=' * 78}\n"
        f"⚠️  날짜표 만료 경고 — {label}\n"
        f"    검증된 마지막 연도: {last_verified_year}년 ({urgency}, 기준일 {cutoff.isoformat()})\n"
        f"    {cutoff.year}년 표를 채우지 않으면 그날부터 관련 계산이 값을 추측하지 않고\n"
        f"    예외를 던지며 멈춥니다(의도된 설계 — §0-1, 확인 안 된 값을 추측하지 않음).\n"
        f"    조치: 같은 방식(휴장일 캘린더 라이브러리 + 뉴스 교차확인)으로 {cutoff.year}년\n"
        f"    표를 채우고, 이 알람이 참조하는 연도(last_verified_year)도 함께 올리세요.\n"
        f"{'=' * 78}\n"
    )
    return True
