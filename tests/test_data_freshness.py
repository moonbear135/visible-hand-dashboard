# tests/test_data_freshness.py
"""🔒 `utils/data_freshness.py` — 공용 "얼어붙은 데이터" 판정 테스트 (2026-09-08, #219)

이 파일이 지키는 것은 하나입니다 — **2026-09-04 에 실제로 났던 사고(#195)의 모양을
반드시 잡는가.** 그날 코스피 수집기는 "오늘 날짜 라벨 + 어제 내용물" 스냅샷을 남겼고,
전 종목 주가가 하나도 안 바뀌었는데도 워치독은 조용했습니다.

오너: *"결투, 성적표, 사실 이 가격이에요 — 전부 다 적용이 안 되던 걸 찾았지."*

⚠️ 특히 **없는 값을 '무변동'으로 세지 않는가**(§0-1)를 못 박습니다. 결측을 무변동으로
   세면 "수집이 통째로 실패한 날"이 "휴장일처럼 조용한 날"로 둔갑합니다.

실행: python -m pytest tests/test_data_freshness.py -v
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

from conftest import FAILURES, check  # noqa: E402,F401
import pytest  # noqa: E402

from utils import data_freshness as F  # noqa: E402


def _rows(count=60, start=10000):
    """비교 최소치(50)를 넘는 평범한 하루치 값."""
    return {f"{i:06d}": start + i for i in range(count)}


# ─────────────────────────────────────────────────────────────────────────────
# ① 9/4 사고 모양
# ─────────────────────────────────────────────────────────────────────────────

def test_all_values_identical_is_flagged():
    """🔴 **이 테스트가 이 모듈의 존재 이유입니다.** 전부 그대로면 반드시 잡습니다."""
    yesterday = _rows()
    today = dict(yesterday)                      # 어제 것을 그대로 다시 받은 상태
    result = F.judge_frozen(today, yesterday)
    check(result["status"] == F.STATUS_FROZEN, "전부 동일 → frozen", f'({result["status"]})')
    check(F.is_frozen(result["status"]), "사람을 불러야 하는 상태로 분류됨")
    check(result["changed"] == 0 and result["unchanged"] == 60, "측정값이 정확함",
          f'(바뀜 {result["changed"]} / 그대로 {result["unchanged"]})')
    check("하나도 바뀌지" in result["reason"], "사람이 읽을 사유가 함께 나옴")


def test_a_normal_trading_day_is_quiet():
    yesterday = _rows()
    today = {k: v + 100 for k, v in yesterday.items()}
    result = F.judge_frozen(today, yesterday)
    check(result["status"] == F.STATUS_OK, "정상적으로 움직인 날은 ok", f'({result["status"]})')
    check(not F.is_frozen(result["status"]), "알림을 울리지 않음")


def test_a_holiday_shaped_day_is_recorded_but_not_alarmed():
    """
    🟡 몇 개만 움직인 날은 **휴장일이면 정상**입니다. 그래서 기록은 남기되 알림은
    울리지 않습니다 — 매주 오탐이 나면 아무도 안 보게 됩니다.

    🔴 이 모듈은 **휴장일과 수집 실패를 구분하지 않습니다**(구분하려면 지수 앵커가
       필요하고, 이 모듈을 쓰는 쪽에는 지수가 없습니다). 그 한계를 여기 못 박습니다.
    """
    yesterday = _rows()
    today = dict(yesterday)
    today["000000"] = 99999                      # 60개 중 1개만 움직임 = 1.7%
    result = F.judge_frozen(today, yesterday)
    check(result["status"] == F.STATUS_MOSTLY_FROZEN, "거의 안 바뀌면 mostly_frozen",
          f'({result["status"]})')
    check(not F.is_frozen(result["status"]), "🟡 는 알림을 울리지 않음 (휴장일 오탐 방지)")


# ─────────────────────────────────────────────────────────────────────────────
# ② 판정하지 않는 경우 — 조용히 '정상'으로 넘기지 않습니다 (§0-1)
# ─────────────────────────────────────────────────────────────────────────────

def test_first_run_does_not_pretend_to_know():
    result = F.judge_frozen(_rows(), {})
    check(result["status"] == F.STATUS_NO_BASELINE, "어제 값이 없으면 no_baseline")
    check(result["status"] != F.STATUS_OK, "🔴 모르는 것을 '정상'으로 만들지 않음")
    check("판정하지 않았습니다" in result["reason"], "판정하지 않았다는 사실이 남음")


def test_too_few_comparable_items_does_not_pretend_to_know():
    """
    몇 개만 보고 그날 수집 성패를 단정하지 않습니다
    (`duel_rules.check_crawl_freshness()` 가 지수 2 + 종목 50 을 요구하는 것과 같은 태도).
    """
    small = _rows(10)
    result = F.judge_frozen(dict(small), small)
    check(result["status"] == F.STATUS_TOO_FEW, "10개뿐이면 판정하지 않음")
    check(result["status"] != F.STATUS_FROZEN, "🔴 표본이 적다고 사고로 단정하지도 않음")


def test_missing_values_are_never_counted_as_unchanged():
    """
    🔴 **§0-1 의 핵심.** 결측을 '무변동'으로 세면 수집이 통째로 실패한 날이
    '휴장일처럼 조용한 날'로 둔갑합니다. 뺀 개수는 결과에 남깁니다.
    """
    yesterday = _rows()
    today = {k: None for k in yesterday}          # 오늘 값이 전부 비어 버린 날
    result = F.judge_frozen(today, yesterday)
    check(result["unchanged"] == 0, "결측을 무변동으로 세지 않음", f'({result["unchanged"]})')
    check(result["unusable"] == 60, "뺀 개수를 그대로 남김", f'({result["unusable"]})')
    check(result["status"] == F.STATUS_TOO_FEW, "비교할 게 없으니 판정하지 않음",
          f'({result["status"]})')
    check(result["status"] != F.STATUS_FROZEN, "결측을 '전부 동일'로 오독하지 않음")
    check("숫자가 아니어서" in result["reason"], "왜 못 봤는지 사유에 적힘")


def test_partial_missing_is_excluded_and_disclosed():
    yesterday = _rows()
    today = {k: v + 10 for k, v in yesterday.items()}
    for code in list(yesterday)[:5]:
        today[code] = ""                           # 5개만 비어 들어온 날
    result = F.judge_frozen(today, yesterday)
    check(result["unusable"] == 5, "빈 값 5개를 뺌", f'({result["unusable"]})')
    check(result["compared"] == 55, "나머지 55개로 판정", f'({result["compared"]})')
    check(result["status"] == F.STATUS_OK, "나머지가 움직였으면 정상")


# ─────────────────────────────────────────────────────────────────────────────
# ③ 명단이 바뀌어도 판정이 죽지 않아야 합니다
# ─────────────────────────────────────────────────────────────────────────────

def test_universe_change_is_absorbed_not_fatal():
    """
    국내 시장은 매일 몇 종목이 상위권을 드나듭니다(실측 1~7종목). 명단이 조금 달라졌다고
    판정 자체를 못 하면, 정작 봐야 할 날에 눈이 감깁니다.
    """
    yesterday = _rows(60)
    today = {f"{i:06d}": 10000 + i for i in range(5, 65)}   # 앞 5개 나가고 뒤 5개 들어옴
    result = F.judge_frozen(today, yesterday)
    check(result["common"] == 55, "공통 55개", f'({result["common"]})')
    check(result["only_today"] == 5 and result["only_previous"] == 5,
          "드나든 종목 수를 각각 기록")
    check(result["status"] == F.STATUS_FROZEN,
          "명단이 바뀌어도 남은 값이 전부 그대로면 잡음", f'({result["status"]})')


def test_decimal_comparison_does_not_produce_phantom_changes():
    """
    출처가 `2000` 으로 주다가 `2000.0` 으로 줘도 **같은 값**입니다.
    float 로 비교하면 "같은 값인데 다르다"가 생겨 매일 '정상'으로 보이게 됩니다.
    """
    yesterday = {f"{i:06d}": "2000" for i in range(60)}
    today = {f"{i:06d}": "2000.0" for i in range(60)}
    result = F.judge_frozen(today, yesterday)
    check(result["status"] == F.STATUS_FROZEN,
          "표기만 다르고 값이 같으면 '바뀌었다'로 세지 않음", f'({result["status"]})')


def test_unknown_status_is_rejected_not_guessed():
    with pytest.raises(F.DataFreshnessError):
        F.is_frozen("아무거나")
    with pytest.raises(F.DataFreshnessError):
        F.compare_unchanged([], {})


# ─────────────────────────────────────────────────────────────────────────────
# ④ 내용 지문 — 요약만 들고 있는 워치독이 쓸 수 있는 최소 단위
# ─────────────────────────────────────────────────────────────────────────────

def test_fingerprint_is_stable_across_notation_and_order():
    check(F.fingerprint([1000, "2000.0"]) == F.fingerprint(["2000", 1000]),
          "표기·순서가 달라도 내용이 같으면 같은 지문")
    check(F.fingerprint(["2.0E+3", 1000]) == F.fingerprint([1000, 2000]),
          "지수 표기도 같은 값으로 봄")


def test_fingerprint_changes_when_a_single_value_changes():
    base = [1000 + i for i in range(100)]
    moved = list(base)
    moved[42] += 1
    check(F.fingerprint(base) != F.fingerprint(moved),
          "🔴 한 종목만 바뀌어도 지문이 달라져야 함 (안 그러면 얼어붙음을 못 잡음)")


def test_fingerprint_of_nothing_is_none_not_an_empty_hash():
    """
    빈 지문을 만들면 `None == None` 이 "내용이 같다"로 오독됩니다 — 수집이 통째로
    실패해 값이 하나도 없는 이틀이 '정상'이 되어 버립니다(§0-1).
    """
    check(F.fingerprint([]) is None, "값이 없으면 지문도 없음")
    check(F.fingerprint(None) is None, "None 이어도 마찬가지")


def test_fingerprint_keeps_missing_values_as_part_of_the_content():
    """결측이 결측 그대로인 것도 '내용이 같다'의 일부입니다."""
    check(F.fingerprint([1000, None]) != F.fingerprint([1000, 2000]),
          "결측과 숫자를 같은 것으로 보지 않음")
    check(F.fingerprint([1000, None]) == F.fingerprint([None, 1000]),
          "결측이 그대로면 지문도 그대로")


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
