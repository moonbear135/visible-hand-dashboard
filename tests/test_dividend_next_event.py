# tests/test_dividend_next_event.py
"""
📅 "다음 배당 일정" 선택 규칙 — `web/pages/dividend_page.next_dividend_event()` 순수 단위 검증

🔴 2026-09-03 추가(오너 요청) — 국내 종목 스코어카드 화면(`web/pages/pegy_page.py`)의 카드에
"다음 배당 일정" 보조 한 줄을 붙이면서 함께 만들었습니다. 카드에는 한 종목의 배당 공시를
전부 나열할 자리가 없어 **화면이 대표 1건을 골라야** 하는데, 그 고르는 규칙이 이 프로젝트가
직접 만든 규칙(원본 데이터의 판단이 아님)이라 규칙 자체를 테스트로 고정해 둡니다.

특히 오너가 명시적으로 요구한 동작 하나 —
  "기재 정정 공시도 어느정도 따라갈 수 있지 않을까?"
  = 같은 배당기준일에 원본과 `[기재정정]` 정정본이 함께 있으면 **정정본을 따라간다**
— 는 되돌리기 쉬운(정렬 방향 한 글자) 규칙이라, 아래
`test_correction_wins_over_original_on_same_record_date` 가 그 회귀 방지선입니다.
2026-09-03 뮤테이션 검증: `next_dividend_event()` 의 정렬을 `reverse=True`(= 먼저 접수된
것이 이김)로 일부러 되돌렸더니 이 테스트와
`test_latest_receipt_wins_even_if_input_order_is_not_sorted` 두 건이 실제로 빨간불이 됐고,
원복 후 다시 초록불이 되는 것까지 확인했습니다.

여기서는 NiceGUI 위젯을 하나도 만들지 않습니다(순수 함수만 호출) —
`tests/test_dividend_page_calendar.py` 와 같은 성격입니다.

실행: python -m pytest tests/test_dividend_next_event.py -v
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.pages.dividend_page import next_dividend_event


def _event(record_date, *, rcept_dt, rcept_no, is_correction=False, **extra):
    """실제 `dividend_kr_2026_payment_events.json` 레코드에서 이 함수가 **실제로 보는**
    필드만 추린 최소 이벤트. 나머지 필드(dps_common 등)는 선택 규칙에 영향을 주지 않으므로
    필요한 테스트만 `extra` 로 얹습니다(있지도 않은 필드를 지어내 넣지 않기)."""
    data = {
        'record_date': record_date,
        'rcept_dt': rcept_dt,
        'rcept_no': rcept_no,
        'is_correction': is_correction,
    }
    data.update(extra)
    return data


def test_correction_wins_over_original_on_same_record_date():
    """🔴 오너가 명시적으로 요청한 동작: 같은 배당기준일에 원본 + `[기재정정]` 이 있으면
    **정정본**이 대표가 됩니다(정정 전 원본을 보여주면 그 자체가 틀린 안내이므로).

    실제 데이터에 있는 모양을 그대로 본떴습니다 — S-Oil(010950)은 접수일 08-10 원본과
    08-11 `[기재정정]` 두 건이 같은 배당기준일(2026-08-25)로 들어와 있습니다.
    """
    original = _event('2026-10-01', rcept_dt='20260810', rcept_no='20260810000001',
                      dps_common=100)
    corrected = _event('2026-10-01', rcept_dt='20260811', rcept_no='20260811000001',
                       is_correction=True, dps_common=250)

    picked = next_dividend_event([original, corrected], date(2026, 9, 3))

    assert picked is corrected, '정정본이 아니라 원본이 선택됐습니다'
    assert picked['is_correction'] is True
    assert picked['dps_common'] == 250, '정정본의 수치(250원)가 그대로 나와야 합니다'


def test_latest_receipt_wins_even_if_input_order_is_not_sorted():
    """호출부(`build_payment_event_index()`)가 이미 오름차순 정렬을 해 주지만, 이 함수는
    **그 정렬에 기대지 않고** 스스로 접수일ㆍ접수번호로 다시 정렬합니다. 정렬이 보장되지
    않은 목록(여기서는 정정본을 일부러 앞에 둠)이 들어와도 답이 같아야 합니다."""
    original = _event('2026-10-01', rcept_dt='20260810', rcept_no='20260810000001',
                      dps_common=100)
    corrected = _event('2026-10-01', rcept_dt='20260811', rcept_no='20260811000001',
                       is_correction=True, dps_common=250)

    picked = next_dividend_event([corrected, original], date(2026, 9, 3))

    assert picked is corrected, '입력 순서가 뒤집혔다고 답이 달라지면 안 됩니다'


def test_same_receipt_date_falls_back_to_receipt_number():
    """접수일(`rcept_dt`)이 같은 날 두 건이면 접수번호(`rcept_no`)가 큰 쪽이 나중 접수분입니다
    (`build_payment_event_index()` 의 정렬 키와 같은 규칙 — 두 곳이 어긋나면 안 됩니다)."""
    earlier = _event('2026-10-01', rcept_dt='20260811', rcept_no='20260811000001')
    later = _event('2026-10-01', rcept_dt='20260811', rcept_no='20260811000900',
                   is_correction=True)

    picked = next_dividend_event([later, earlier], date(2026, 9, 3))

    assert picked is later


def test_past_record_dates_are_not_candidates():
    """이미 지난 배당기준일은 "다음 일정"이 아닙니다 — 지난 날짜를 앞으로의 일정처럼
    보여주면 §0-1 위반입니다."""
    past = _event('2026-08-31', rcept_dt='20260801', rcept_no='20260801000001')
    future = _event('2026-09-30', rcept_dt='20260802', rcept_no='20260802000001')

    picked = next_dividend_event([past, future], date(2026, 9, 3))

    assert picked is future, '지난 배당기준일이 선택됐습니다'


def test_record_date_equal_to_today_is_included():
    """🔴 경계값 — 오늘이 배당기준일인 건은 아직 오늘 안에 남아 있는 일정이라 **포함**합니다.
    (`>` 로 잘못 적으면 딱 그 날 하루만 조용히 사라져 알아채기 어렵습니다.)"""
    today = _event('2026-09-03', rcept_dt='20260801', rcept_no='20260801000001')

    picked = next_dividend_event([today], date(2026, 9, 3))

    assert picked is today


def test_returns_none_when_no_future_candidate_remains():
    """후보가 하나도 없으면 None — 호출부는 이때 보조 줄을 **아예 그리지 않습니다**
    (없는 값을 "예정 없음"으로 단정하지 않기)."""
    past_only = [
        _event('2026-08-01', rcept_dt='20260701', rcept_no='20260701000001'),
        _event('2026-09-02', rcept_dt='20260801', rcept_no='20260801000001'),
    ]

    assert next_dividend_event(past_only, date(2026, 9, 3)) is None


def test_returns_none_for_empty_or_missing_event_list():
    """이벤트가 아예 없는 종목(대부분의 종목)에서도 예외 없이 None 이어야 합니다."""
    assert next_dividend_event([], date(2026, 9, 3)) is None
    assert next_dividend_event(None, date(2026, 9, 3)) is None


def test_nearest_future_record_date_wins_among_several():
    """미래 후보가 여럿이면 **가장 가까운(이른)** 배당기준일 1건. 입력 순서와 무관해야
    합니다(접수 순서와 배당기준일 순서는 서로 다른 축입니다)."""
    far = _event('2026-12-31', rcept_dt='20260801', rcept_no='20260801000001')
    near = _event('2026-09-30', rcept_dt='20260820', rcept_no='20260820000001')
    mid = _event('2026-11-01', rcept_dt='20260805', rcept_no='20260805000001')

    picked = next_dividend_event([far, near, mid], date(2026, 9, 3))

    assert picked is near, '가장 이른 배당기준일이 아니라 다른 건이 선택됐습니다'


def test_events_without_parseable_record_date_are_ignored():
    """`record_date` 가 없거나 형식을 읽을 수 없으면 "언제인지 모른다"는 뜻이라 후보에서
    빼고, 남은 정상 건으로 계속 답을 냅니다(이상한 값 하나로 화면이 죽지 않아야 합니다)."""
    broken = [
        _event(None, rcept_dt='20260901', rcept_no='20260901000001'),
        _event('', rcept_dt='20260901', rcept_no='20260901000002'),
        _event('2026-13-99', rcept_dt='20260901', rcept_no='20260901000003'),
        _event('언젠가', rcept_dt='20260901', rcept_no='20260901000004'),
    ]
    good = _event('2026-09-30', rcept_dt='20260801', rcept_no='20260801000001')

    assert next_dividend_event(broken, date(2026, 9, 3)) is None
    assert next_dividend_event(broken + [good], date(2026, 9, 3)) is good


def test_unparseable_correction_cannot_hide_a_valid_original():
    """읽을 수 없는 날짜의 정정본이 뒤에 있다고 해서, 날짜가 멀쩡한 원본까지 사라지면
    안 됩니다(제외 규칙이 "그 이벤트 한 건"에만 적용되는지 확인)."""
    original = _event('2026-09-30', rcept_dt='20260810', rcept_no='20260810000001')
    broken_correction = _event(None, rcept_dt='20260811', rcept_no='20260811000001',
                               is_correction=True)

    picked = next_dividend_event([original, broken_correction], date(2026, 9, 3))

    assert picked is original


def test_does_not_mutate_or_copy_the_input_event():
    """돌려주는 값은 **입력 이벤트 그 객체 그대로**입니다 — 값을 가공하거나 새 dict 를 만들어
    돌려주면 호출부가 원문(`dart_document_url` 등)을 잃습니다."""
    event = _event('2026-09-30', rcept_dt='20260801', rcept_no='20260801000001',
                   dps_common=500, dividend_class='중간배당',
                   dart_document_url='https://dart.fss.or.kr/x')
    before = dict(event)

    picked = next_dividend_event([event], date(2026, 9, 3))

    assert picked is event
    assert event == before, '입력 이벤트가 변형됐습니다'


def test_works_on_real_collected_payload_when_present():
    """실제 수집 파일이 저장소에 있으면 그것으로도 한 번 돌려 봅니다(오프라인 — 파일만 읽음).
    파일이 없는 환경(신규 클론 등)에서는 조용히 건너뜁니다 — 이 테스트는 규칙 검증이 아니라
    "실제 데이터 모양에서도 예외 없이 돈다"는 스모크입니다."""
    from web.pages.dividend_page import PAYMENT_EVENTS_FILENAME, build_payment_event_index

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'data', PAYMENT_EVENTS_FILENAME)
    if not os.path.exists(path):
        return

    import json
    with open(path, encoding='utf-8') as fp:
        payload = json.load(fp)
    index = build_payment_event_index(payload)
    assert index, '실제 수집 파일에서 종목 색인이 비었습니다'

    today = date(2026, 9, 3)
    for code, events in index.items():
        picked = next_dividend_event(events, today)
        if picked is None:
            continue
        assert picked in events, f'{code}: 색인에 없던 이벤트가 나왔습니다'
        assert picked['record_date'] >= today.isoformat(), (
            f"{code}: 지난 배당기준일({picked['record_date']})이 선택됐습니다")


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-v"]))
