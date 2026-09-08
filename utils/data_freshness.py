# utils/data_freshness.py
"""
🧊 "어제와 오늘이 통째로 같은가" — **얼어붙은 데이터** 판정 (2026-09-08 신설, #219)

⚠️ 이 모듈이 왜 생겼는가 (실제로 난 사고입니다)

2026-09-04, 코스피 수집기가 **"오늘 날짜 라벨 + 어제 내용물"** 스냅샷을 남기고 정식 수집을
건너뛰었습니다(#195). 전 종목 주가가 하나도 바뀌지 않았는데도 —

  · `utils/data_sanity.py` 는 조용했습니다. 결측도 아니고, 종목 수도 같고, 중앙값 이동이
    0 이라 **오히려 "너무 정상"** 으로 보였기 때문입니다.
  · 이 사고를 잡을 수 있는 눈은 저장소에 **딱 하나** 있었습니다 —
    `utils/duel_rules.py::check_crawl_freshness()`. 결투에만 붙어 있어서 나머지는
    전부 그냥 통과시켰습니다.

오너: *"결투, 성적표, 사실 이 가격이에요 — 전부 다 적용이 안 되던 걸 찾았지."*

→ 그래서 **같은 질문에 답하는 계산을 한 곳에 모읍니다**(§0-3-10).

🔴 다만 **결투 파일은 한 글자도 건드리지 않았습니다** (2026-09-08 오너 결정).
   결투 판정은 사용자 주문의 체결 여부를 직접 좌우하는 자리라, 공용화하다 그 경로를
   흔드는 위험을 오너가 받지 않기로 했습니다.

🔴 그리고 **정직하게 남기는 한계** — 결투 규칙을 그대로 불러다 쓸 수 **없었습니다**:

   `duel_rules.check_crawl_freshness()` 는 **지수 2개(KOSPI·KOSDAQ)를 앵커로 요구**합니다.
   지수가 움직였는지를 봐야 "휴장일이라 다 같은 것"과 "수집이 실패해 다 같은 것"을
   구분할 수 있기 때문입니다. 그런데 이 모듈을 쓰는 쪽(섀도 관찰·산티체크)에는
   **지수 값이 없습니다.** 지수를 새로 받아오려면 상대 서버에 요청을 더 보내야 하고
   (§0-3-2), 없는 값을 지어내는 것은 §0-1 위반입니다.

   → 그래서 이 모듈은 **지수 앵커 없이 답할 수 있는 것까지만** 답합니다:
     "어제와 오늘이 통째로 같은가"는 확실하게 답하고,
     **"그게 휴장일 때문인지 사고 때문인지는 구분하지 않습니다."**
     구분이 필요한 곳(결투)은 지금처럼 `duel_rules` 를 쓰면 됩니다.

   ⚠️ 결과적으로 **무변동을 세는 계산 자체는 결투와 이 모듈 두 곳에 있습니다.**
      숨기지 않고 적어 둡니다. 완전히 하나로 합치려면 결투 규칙 파일을 고쳐야 하고,
      그건 오너가 따로 판단할 사항입니다.

📐 설계 원칙
  · **순수 계산.** 파일도 시계도 네트워크도 건드리지 않습니다. 표준 라이브러리만 씁니다.
  · **없는 값을 무변동으로 세지 않습니다**(§0-1). 어느 한쪽이라도 숫자가 아니면 그 항목은
    비교에서 빼고, **뺐다는 사실을 결과에 남깁니다.**
  · **판정과 문장을 같이 돌려줍니다.** 상태 코드만 남기면 나중에 "왜 의심이었지?"를
    알 수 없습니다.
"""
import hashlib
from decimal import Decimal, InvalidOperation

#: 판정 결과
STATUS_OK = "ok"                       #: 충분히 많이 바뀌었습니다 — 정상
STATUS_FROZEN = "frozen"               #: 🔴 **하나도 안 바뀌었습니다** — 9/4 사고와 같은 모양
STATUS_MOSTLY_FROZEN = "mostly_frozen" #: 🟡 거의 안 바뀌었습니다 — 휴장일이면 정상
STATUS_NO_BASELINE = "no_baseline"     #: 어제 값이 없습니다 — 판정하지 않음(오류가 아닙니다)
STATUS_TOO_FEW = "too_few"             #: 비교할 수 있는 항목이 너무 적습니다 — 판정하지 않음

#: 비교 대상이 이보다 적으면 **판정하지 않습니다.** 몇 개만 보고 그날 수집 성패를
#: 단정하지 않는다는 `duel_rules.check_crawl_freshness()` 의 태도를 그대로 따릅니다
#: (그쪽은 지수 2 + 종목 50 을 요구합니다).
DEFAULT_MIN_OVERLAP = 50

#: 바뀐 비율이 이보다 낮으면 🟡. 정확한 근거가 있는 숫자가 아니라 **판단**입니다 —
#: 한국 증시 정규장에 상위 500종목 중 5% 미만만 움직이는 날은 사실상 없습니다.
#: 다만 **휴장일에는 정상적으로 0%** 이므로, 이 상태는 알림이 아니라 기록입니다.
DEFAULT_MOSTLY_FROZEN_RATIO = 0.05


class DataFreshnessError(Exception):
    """입력 자체가 판정할 수 없는 모양일 때. 값이 이상한 것과는 다릅니다."""


def _number(value):
    """숫자로 볼 수 있으면 Decimal, 아니면 None.

    ⚠️ `float` 대신 `Decimal` 입니다. 종가는 십진수로 들어오므로 float 비교에서 생기는
       "같은 값인데 다르다"를 애초에 없앱니다(`duel_rules` 와 같은 규율).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError):
        return None


def compare_unchanged(today, previous):
    """**순수 측정** — 어제와 오늘 사이에 몇 개가 그대로인가. 판정은 하지 않습니다.

    인자
        today, previous : {키: 숫자} dict. 키는 종목코드든 무엇이든 상관없습니다.

    반환 dict
        common      : 양쪽에 다 있는 키 수
        compared    : 그중 **양쪽 다 숫자여서 실제로 비교한** 수
        unusable    : 양쪽에 있지만 한쪽이라도 숫자가 아니어서 **뺀** 수 (§0-1 — 숨기지 않음)
        unchanged   : 값이 그대로인 수
        changed     : 값이 바뀐 수
        only_today / only_previous : 한쪽에만 있는 키 수 (명단이 바뀐 정도)
    """
    if not isinstance(today, dict) or not isinstance(previous, dict):
        raise DataFreshnessError("오늘/어제 값은 dict 로 주어져야 합니다.")

    today_keys, previous_keys = set(today), set(previous)
    common = today_keys & previous_keys

    unchanged = changed = unusable = 0
    for key in common:
        now, before = _number(today[key]), _number(previous[key])
        if now is None or before is None:
            # 없는 값을 "무변동"으로 세면 사고를 정상으로 넘겨 버립니다(§0-1).
            unusable += 1
            continue
        if now == before:
            unchanged += 1
        else:
            changed += 1

    return {
        "common": len(common),
        "compared": unchanged + changed,
        "unusable": unusable,
        "unchanged": unchanged,
        "changed": changed,
        "only_today": len(today_keys - previous_keys),
        "only_previous": len(previous_keys - today_keys),
    }


def judge_frozen(today, previous, *,
                 min_overlap=DEFAULT_MIN_OVERLAP,
                 mostly_frozen_ratio=DEFAULT_MOSTLY_FROZEN_RATIO):
    """"어제와 오늘이 통째로 같은가"를 판정합니다.

    🔴 **휴장일과 수집 실패를 구분하지 않습니다.** 그 구분에는 지수 앵커가 필요하고,
       이 모듈을 쓰는 쪽에는 지수가 없습니다(파일 머리말 참고). 구분이 필요하면
       `duel_rules.check_crawl_freshness()` 를 쓰세요.

    반환 dict: status / reason(한글 한 문장) + `compare_unchanged()` 의 측정값 전부
    """
    measured = compare_unchanged(today, previous)

    if not previous:
        # 첫 실행입니다. 오류가 아니지만 **조용히 '정상'으로 넘기지도 않습니다**(§0-1).
        return dict(measured, status=STATUS_NO_BASELINE,
                    reason="어제 값이 없어 신선도를 판정하지 않았습니다 (첫 실행이면 정상입니다).")

    if measured["compared"] < min_overlap:
        detail = f'공통 {measured["common"]}개 중 비교 가능 {measured["compared"]}개'
        if measured["unusable"]:
            detail += f', 숫자가 아니어서 뺀 것 {measured["unusable"]}개'
        return dict(measured, status=STATUS_TOO_FEW,
                    reason=f"비교할 수 있는 항목이 최소 {min_overlap}개에 못 미쳐"
                           f" 판정하지 않았습니다 ({detail}).")

    if measured["changed"] == 0:
        return dict(measured, status=STATUS_FROZEN,
                    reason=f'{measured["compared"]}개를 어제와 비교했는데 **하나도 바뀌지'
                           " 않았습니다** — 어제 값을 그대로 다시 받았거나 수집이 건너뛰어졌을"
                           " 수 있습니다 (휴장일이면 정상입니다).")

    ratio = measured["changed"] / measured["compared"]
    if ratio < mostly_frozen_ratio:
        return dict(measured, status=STATUS_MOSTLY_FROZEN,
                    reason=f'바뀐 항목이 {measured["changed"]}/{measured["compared"]}개'
                           f" ({ratio * 100:.1f}%) 뿐입니다 — 휴장일이면 정상이고,"
                           " 아니면 갱신을 놓쳤을 수 있습니다.")

    return dict(measured, status=STATUS_OK,
                reason=f'바뀐 항목 {measured["changed"]}/{measured["compared"]}개 — 정상.')


def is_frozen(status):
    """이 판정이 **사람을 불러야 하는 상태**인가.

    판정 문자열을 호출부마다 비교하지 않고 이 함수를 쓰면, 상태가 하나 늘어도 고칠 곳이
    한 군데입니다(§0-3-10 — `duel_rules.crawl_status_allows_fill()` 과 같은 규율).

    🟡 `mostly_frozen` 은 **False** 입니다 — 휴장일에 정상적으로 나오는 모양이라
       알림을 울리면 매주 오탐이 됩니다. 기록에는 남습니다.
    """
    known = (STATUS_OK, STATUS_FROZEN, STATUS_MOSTLY_FROZEN,
             STATUS_NO_BASELINE, STATUS_TOO_FEW)
    if status not in known:
        raise DataFreshnessError(f"알 수 없는 신선도 판정입니다: {status!r}")
    return status == STATUS_FROZEN


def _canonical(number):
    """Decimal 을 **표기 차이가 사라진** 문자열로. `2000`·`2000.0`·`2.0E+3` 이 모두 같아집니다."""
    normalized = number.normalize()
    # normalize() 는 큰 정수를 지수 표기(1E+3)로 만들므로 다시 펴 줍니다.
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def fingerprint(values):
    """값들의 **내용 지문** — 통째로 같은지를 짧은 문자열 하나로 비교하기 위한 것.

    왜 필요한가: `utils/data_sanity.py` 는 매일 저장소에 커밋되는 **요약**만 남기고
    원본 값을 들고 있지 않습니다(그 파일이 작고 읽기 쉬워야 하니까요). 그래서 어제와
    내용이 같은지를 볼 수가 없었고, 그게 9/4 사고가 그 워치독을 그냥 통과한 이유입니다.
    지문 한 줄이면 **파일 크기를 거의 안 늘리고** 그 구멍을 막습니다.

    🔴 이 지문이 **못 하는 것**(정직하게):
      · **몇 개가 바뀌었는지 못 셉니다.** "통째로 같다/아니다"만 압니다.
      · 값의 **순서는 보지 않습니다**(정렬해서 넣습니다). 두 행이 값을 맞바꾸면 같은 지문이
        나옵니다. "통째로 같은가"를 묻는 용도에는 문제가 없습니다.
      · 숫자가 아닌 값은 **빼지 않고 문자 그대로** 넣습니다 — 결측이 결측 그대로인 것도
        "내용이 같다"의 일부이기 때문입니다.

    반환: 16자리 16진수 문자열. 값이 하나도 없으면 None(빈 지문을 만들지 않습니다 —
          `None == None` 이 "내용이 같다"로 오독되면 안 됩니다).
    """
    items = list(values or [])
    if not items:
        return None
    normalized = []
    for value in items:
        number = _number(value)
        # 숫자는 정규화해서 넣습니다 — 출처가 "2000" 으로 주든 "2000.0" 으로 주든
        # **같은 값**이므로 같은 지문이 나와야 합니다(안 그러면 매일 "내용이 바뀌었다"가 됩니다).
        normalized.append(_canonical(number) if number is not None else f"~{value!r}")
    digest = hashlib.sha256("\n".join(sorted(normalized)).encode("utf-8")).hexdigest()
    return digest[:16]
