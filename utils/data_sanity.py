# utils/data_sanity.py
"""
📏 수집 결과 산티체크(data sanity) — "실행은 됐는데 결과 값이 이상한" 날을 잡아내는 판정 계층
   (2026-08-30 신설)

⚠️ 이 모듈이 왜 생겼는가 (지어낸 가정이 아니라 실제 공백입니다)

이 저장소에는 이미 두 겹의 감시가 있습니다.

  · `.github/workflows/watch_schedule_health.yml` — **"오늘 이 워크플로우가 실행됐는가"** 만
    봅니다(그 파일 머리말이 스스로 그렇게 못 박아 두었습니다). 즉 "안 돌았다"는 잡지만
    "돌긴 돌았는데 결과가 이상하다"는 전혀 못 잡습니다.
  · `.github/workflows/test_suite.yml` — pytest 를 돌립니다. 즉 **이미 알려진 검사**만
    지켜줍니다. 오늘 네이버 HTML 이 바뀌어 가격이 전부 0으로 들어와도 pytest 는 초록불입니다.

그 사이에 뚫려 있는 구멍이 바로 이 모듈의 대상입니다 — **수집은 성공했다고 기록됐는데
결과 값 자체가 그럴듯하지 않은 날.** 예: 수집 종목 수가 갑자기 크게 줄었다 / 핵심 숫자
컬럼이 전부 비었거나 0이다 / 파싱이 실패해 한 상수로 전부 채워졌다 / 어제 대비 값 수준이
말이 안 되게 튀었다(단위 오류·통화 혼선·유니버스 뒤바뀜).

🔴 이 모듈은 **아무것도 고치지 않습니다.** 값을 지우지도, 채우지도, 대체하지도 않습니다.
   오직 **판정하고 그 사실을 남길 뿐**입니다(ENGINEERING_SPEC.md §0-1 — 의심스러운 값도
   그대로 두고 경고만 추가). 수집기는 이 판정 결과와 무관하게 원래 하던 저장을 그대로
   끝냅니다. 판정은 그 뒤에 한 겹 얹히는 관찰자일 뿐입니다.

📐 설계 원칙

  · **순수 계산 + 파일 하나.** 네트워크·Supabase·NiceGUI 에 직접 접속하지 않습니다.
    테스트가 전부 오프라인·임시 경로로 돌아갑니다.
  · **기준값(어제 값)은 이 모듈이 스스로 굴립니다** — `utils/duel_batch.py` 의 신선도
    기준값(`duel_freshness_probe_previous.json`)과 **완전히 같은 방식**입니다:
    실행 시작에 파일을 읽어 "어제"로 쓰고, 실행 끝에 오늘 값으로 덮어써 "내일의 기준값"으로
    남기고, 워크플로우가 그 파일을 저장소에 커밋합니다. 형식 버전 필드(`version`)를 두고
    모르는 버전은 **추측해서 읽지 않습니다**(§0-1). 같은 판정을 두 번 구현하지 않기 위해
    duel 쪽 코드를 복사해 오지 않고, 이 모듈은 "수집기 일반"이라는 다른 대상만 다룹니다
    (§0-3-10 — 중복 금지).
  · **파일은 데이터셋당 하나** (`data/<dataset>_sanity.json`). 그 안에 ① 오늘의 판정 결과와
    ② 내일의 기준값이 될 오늘 요약(`probe`)이 함께 들어갑니다. 두 파일로 쪼개면 둘이 어긋날
    때 어느 쪽이 진짜인지 알 수 없게 됩니다(§0-3-10 — 단일 출처).
  · **판정 결과는 사람이 읽을 한글 사유 문자열**을 항상 함께 돌려줍니다. 상태 코드만 남기면
    나중에 "왜 의심이었지?"를 알 수 없습니다.

🔢 임계값에 대해 — 정직하게 말해 두는 것

아래 상수들은 **"정답"이 아니라 판단**입니다. 이 저장소의 실제 산출물(2026-08-29 자
스냅샷)을 직접 세어 본 값을 근거로, **평소 변동성에는 조용하고 진짜 이상만 잡도록
보수적으로(=둔감하게)** 골랐습니다. 근거는 각 상수 옆에 적어 두었고, 실측이 아닌
부분은 실측이 아니라고 적었습니다. 알람이 너무 잦거나 너무 없다고 느껴지면 이 숫자를
고치되, **고친 근거를 그 자리에 같이 적어 주세요.**
"""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

#: 상태 파일의 형식 버전. 키 이름이 바뀌면 이 숫자를 올리고, 읽는 쪽이 모르는 버전을
#: 만나면 추측해서 읽지 않고 "기준값 없음"으로 처리합니다(duel_batch.PROBE_STATE_VERSION 과
#: 같은 규율).
SANITY_STATE_VERSION = 1

#: 판정 상태.
STATUS_OK = "ok"                    # 검사한 항목이 전부 통과
STATUS_SUSPECT = "suspect"          # 하나 이상 걸림 → 사람이 봐야 함
STATUS_NO_BASELINE = "no_baseline"  # 판정 불가(기준값 없음 / 표본 부족) — 실패가 아님
STATUS_ERROR = "error"              # 판정 자체가 실패(기준값 파일 손상, 입력 형식 오류 등)

#: 알림을 보내야 하는 상태. 워크플로우가 이 목록으로 판단합니다(문자열을 YAML 에 또 적지
#: 않기 위해 여기 단일 출처로 둡니다 — §0-3-10).
ALERT_STATUSES = (STATUS_SUSPECT, STATUS_ERROR)

STATUS_LABELS_KO = {
    STATUS_OK: "정상",
    STATUS_SUSPECT: "의심",
    STATUS_NO_BASELINE: "판정 불가",
    STATUS_ERROR: "판정 오류",
}

DEFAULT_THRESHOLDS = {
    # ── ① 건수 급감 ────────────────────────────────────────────────────────────
    # 어제 기준값 대비 오늘 행 수가 이 비율 이상 줄면 의심.
    #   왜 0.30 인가: 이 저장소의 일간 수집기들은 유니버스 크기가 사실상 고정입니다
    #   (코스피/코스닥 통합 상위 500 + 히스테리시스 버퍼 → 2026-08-29 실측 507행,
    #    미국주식 550 목표 → 실측 548행, 보조지표 500종목 → 실측 500행).
    #   순위 교체·개별 실패로 하루에 흔들리는 폭은 한 자릿수 %입니다. 30% 는 그보다 훨씬
    #   크고(코스피 기준 150종목이 통째로 사라져야 닿습니다), 정상적인 명단 교체로는
    #   절대 도달할 수 없는 값이라 오탐이 사실상 없습니다. **판단이지 정답은 아닙니다** —
    #   더 예민하게 하고 싶으면 0.15 쯤으로 낮추면 되지만, 그만큼 조용한 날이 줄어듭니다.
    "row_drop_ratio": 0.30,

    # ── ② 건수 급증 ────────────────────────────────────────────────────────────
    # 어제 대비 오늘 행 수가 이 배수 이상이면 의심(같은 결과를 두 번 이어붙인 사고 등).
    #   왜 2.0 인가: 급감보다 **일부러 훨씬 둔감하게** 잡았습니다. 이 저장소는 실제로
    #   유니버스를 의도적으로 넓힌 적이 있습니다(2026-08-26 코스피 상위 200 → 통합 500,
    #   TASK_HISTORY #150 계열). 그런 날에는 이 검사가 한 번 울립니다 — 그건 오탐이 아니라
    #   "행 수가 2.5배가 됐다"는 **사실 그대로의 보고**이고, 하루치 확인 한 번이면 끝납니다.
    "row_surge_ratio": 2.00,

    # ── ③ 결측/0 비율 ─────────────────────────────────────────────────────────
    # 핵심 숫자 컬럼에서 (결측 + 0) 비율이 이 값 이상이면 의심.
    #   왜 0.30 인가: 여기 넘기는 "핵심 컬럼"은 호출부가 **거의 항상 값이 있어야 하는 것만**
    #   고릅니다(실측: 코스피 price·market_cap 결측 0.0%, 미국 price·market_cap 결측 0.0%,
    #   보조지표 rsi·bb_mid 결측 0.0%). 반대로 t_per(코스피 19.3% 결측)·quant_score(24.7%)
    #   처럼 정상적으로 자주 비는 컬럼은 애초에 넘기지 않습니다. 그래서 30% 는 평소의
    #   수십 배이고, 파싱이 실제로 깨진 날에만 닿습니다.
    "unusable_ratio": 0.30,

    # ── ④ 결측/0 비율의 급등 ───────────────────────────────────────────────────
    # 절대값이 ③ 에 못 미쳐도, 어제 대비 이 **퍼센트포인트** 이상 뛰면 의심.
    #   왜 필요한가: 어제 2% → 오늘 28% 는 명백한 부분 붕괴인데 ③(30%) 은 놓칩니다.
    #   왜 0.25(=25%p) 인가: 위 실측대로 평소 결측률이 0% 대라 하루 만에 25%p 가 뛰려면
    #   1/4 이 통째로 깨져야 합니다. 평소 흔들림(수 %p)과는 자릿수가 다릅니다.
    "unusable_ratio_jump": 0.25,

    # ── ⑤ 값이 전부 동일 ──────────────────────────────────────────────────────
    # 숫자로 읽힌 값의 서로 다른 개수가 1이면 의심(수집 실패를 한 상수로 채운 전형적 징후 —
    # ENGINEERING_SPEC §0-1 예시 2 의 `t_per = 12.5`, `f_roe = 8.5` 가 정확히 이 모양이었습니다).
    #   임계값이 따로 없는 이유: 30행 이상에서 서로 다른 값이 딱 1개인 것은 실제 시장
    #   데이터에서 일어날 수 없습니다(실측 distinct: 코스피 price 469/507, 미국 price
    #   545/548, 보조지표 rsi 455/500). 그래서 오탐 위험이 0에 가깝습니다.

    # ── ⑥ 값 수준의 급변(중앙값 기준) ─────────────────────────────────────────
    # 어제 대비 중앙값이 이 배수 이상(또는 그 역수 이하)으로 바뀌면 의심.
    #   왜 중앙값인가: 개별 종목의 극단치에 흔들리지 않고, 기존 아웃라이어 처리
    #   (utils/scoring.py 의 윈저라이즈, utils/guardrail.py 의 하드컷)와 **겹치지 않습니다.**
    #   저쪽은 "종목 하나"를 다루고 여기는 "그날 전체의 수준"만 봅니다.
    #   왜 2.0 인가: 코스피는 종목별 일간 가격제한이 ±30% 라, 500종목의 **중앙값**이 하루에
    #   두 배가 되거나 반토막 나는 것은 사실상 불가능합니다. 즉 이 검사에 걸리는 건 시장이
    #   아니라 단위 오류(원↔천원)·통화 혼선·유니버스 뒤바뀜 같은 **데이터 사고**입니다.
    #   ⚠️ 그래서 이 검사는 아무 컬럼에나 켜면 안 됩니다 — RSI·%B 처럼 0~100/0~1 로 갇힌
    #      오실레이터는 진짜 폭락장에서 중앙값이 반토막 날 수 있어 "시장이 움직였다"를
    #      "데이터가 깨졌다"로 오해하게 만듭니다. 그래서 호출부가 `level_fields` 로 **가격
    #      수준 컬럼만** 따로 지정하게 했습니다.
    "median_shift_ratio": 2.00,

    # ── 공통 하한 ─────────────────────────────────────────────────────────────
    # 표본이 이보다 적으면 비율·상수 판정을 하지 않습니다(적은 표본에서 비율은 잡음입니다).
    #   30 은 통계적 최적값이 아니라 "이 저장소의 수집기는 전부 수백 행이라, 30행 미만은
    #   애초에 정상 산출물이 아니다"는 관찰에서 고른 실용적인 선입니다.
    "min_rows_for_ratio_checks": 30,
}

#: 상태 파일 이름 규칙. 워크플로우가 `data/*_sanity.json` 글롭으로 찾습니다.
SANITY_FILENAME_SUFFIX = "_sanity.json"

#: 데이터셋 키에 허용하는 글자 — 파일명에 그대로 들어가므로 경로 조작을 막습니다(§0-3-9).
_DATASET_KEY_RE = re.compile(r"^[a-z0-9_]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DataSanityError(ValueError):
    """산티체크 입력·상태 파일이 우리가 아는 형식이 아닐 때. 추측해서 진행하지 않습니다."""


# =============================================================================
# 1. 값 읽기 헬퍼 (순수 함수)
# =============================================================================
def _coerce_number(value):
    """
    숫자로 읽을 수 있으면 float, 아니면 None.

    · `bool` 은 숫자로 보지 않습니다 — 파이썬에서 True 는 1 이라, 플래그 컬럼을 실수로
      넘겼을 때 "값이 있다"고 잘못 세게 됩니다.
    · NaN/무한대는 값이 없는 것으로 봅니다(중앙값을 오염시킵니다).
    · `"1,234"` 처럼 천단위 쉼표가 붙은 문자열은 이 저장소 파서들이 실제로 만드는 모양이라
      받아 줍니다. 그 외 문자열은 결측으로 셉니다(지어내지 않음).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _median(values):
    """중앙값. 빈 목록이면 None (0 으로 채우지 않습니다 — §0-1)."""
    if not values:
        return None
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def _as_rows(dataset):
    """
    수집 결과를 `[{...}, {...}]` 로 정규화합니다. pandas DataFrame 과 dict 목록을 둘 다
    받습니다(pandas 를 import 하지 않고 오리 타이핑으로 판별 — 이 모듈은 pandas 없이도
    동작해야 합니다).

    ⚠️ dict 가 아닌 행을 만나면 **조용히 건너뛰지 않고 예외**입니다. 건너뛰면 행 수가
       조용히 줄어들어, 정확히 이 모듈이 잡으려는 "건수 급감"을 스스로 만들어 냅니다.
    """
    if dataset is None:
        raise DataSanityError("판정할 수집 결과가 None 입니다.")
    if hasattr(dataset, "to_dict") and hasattr(dataset, "columns"):   # pandas.DataFrame
        return list(dataset.to_dict("records"))
    if isinstance(dataset, dict):
        raise DataSanityError(
            "수집 결과로 dict 하나가 아니라 '행 목록'을 넘겨주세요"
            " (예: snapshot['stocks'] — 스냅샷 전체가 아니라 그 안의 배열)."
        )
    if not isinstance(dataset, (list, tuple)):
        raise DataSanityError(f"수집 결과의 형식을 알 수 없습니다: {type(dataset).__name__}")
    rows = []
    for index, row in enumerate(dataset):
        if not isinstance(row, dict):
            raise DataSanityError(
                f"{index}번째 행이 dict 가 아닙니다({type(row).__name__})."
                " 형식이 섞인 목록을 임의로 걸러내지 않습니다."
            )
        rows.append(row)
    return rows


def _now(now_kst=None):
    if isinstance(now_kst, datetime):
        return now_kst.astimezone(KST) if now_kst.tzinfo else now_kst.replace(tzinfo=KST)
    return datetime.now(KST)


def _date_text(target_date):
    """'YYYY-MM-DD' 문자열로 정규화. 모르는 형식이면 예외(날짜를 지어내지 않습니다)."""
    if isinstance(target_date, datetime):
        return target_date.date().isoformat()
    if isinstance(target_date, date):
        return target_date.isoformat()
    if isinstance(target_date, str) and _DATE_RE.match(target_date.strip()):
        return target_date.strip()
    raise DataSanityError(f"대상 날짜 형식을 알 수 없습니다: {target_date!r} (YYYY-MM-DD 필요)")


# =============================================================================
# 2. 오늘 요약 만들기 (내일의 기준값이 되는 값)
# =============================================================================
def summarize_dataset(dataset, fields):
    """
    수집 결과를 **판정에 필요한 만큼만** 요약합니다. 원본 값을 통째로 들고 있지 않는 이유:
    이 요약이 매일 저장소에 커밋되는 파일이 되기 때문입니다(작고 읽기 쉬워야 합니다).

    인자
        dataset : 행 목록 또는 pandas DataFrame
        fields  : 핵심 숫자 컬럼 이름들. **호출부가 "거의 항상 값이 있어야 하는 컬럼"만**
                  고릅니다(정상적으로 자주 비는 컬럼을 넣으면 매일 울립니다).

    반환
        {"row_count": int,
         "fields": {컬럼명: {numeric_count, missing_count, zero_count, distinct_count, median}}}
    """
    rows = _as_rows(dataset)
    names = [str(name) for name in (fields or [])]
    if not names:
        raise DataSanityError("핵심 숫자 컬럼 목록이 비어 있습니다 — 무엇을 볼지 정하지 않고 판정하지 않습니다.")

    summary = {"row_count": len(rows), "fields": {}}
    for name in names:
        numbers = []
        missing = 0
        zeros = 0
        for row in rows:
            number = _coerce_number(row.get(name))
            if number is None:
                missing += 1
                continue
            if number == 0:
                zeros += 1
            numbers.append(number)
        summary["fields"][name] = {
            "numeric_count": len(numbers),
            "missing_count": missing,
            "zero_count": zeros,
            "distinct_count": len(set(numbers)),
            "median": _median(numbers),
        }
    return summary


# =============================================================================
# 3. 판정 (순수 함수 — 파일도 시계도 건드리지 않습니다)
# =============================================================================
def _check(name, field, status, detail):
    return {"name": name, "field": field, "status": status, "detail": detail}


def _validate_summary(summary, what):
    if not isinstance(summary, dict):
        raise DataSanityError(f"{what} 요약이 dict 가 아닙니다({type(summary).__name__}).")
    if not isinstance(summary.get("row_count"), int) or isinstance(summary.get("row_count"), bool):
        raise DataSanityError(f"{what} 요약에 정수 row_count 가 없습니다.")
    if not isinstance(summary.get("fields"), dict):
        raise DataSanityError(f"{what} 요약에 fields dict 가 없습니다.")


def judge_sanity(today, baseline=None, *, baseline_date=None, level_fields=None, thresholds=None):
    """
    오늘 요약이 "그럴듯한가"를 판정합니다. **아무것도 고치지 않고 판정만 합니다.**

    인자
        today          : `summarize_dataset()` 결과.
        baseline       : 어제의 같은 요약. 없으면 None(첫 실행 — 오류가 아닙니다).
        baseline_date  : 그 기준값이 어느 날짜의 것인지(사유 문장에 그대로 실립니다).
        level_fields   : 중앙값 급변(⑥) 검사를 켤 컬럼들. 기본값은 **아무 컬럼도 아님** —
                         이 검사는 "가격 수준" 컬럼에만 의미가 있어서, 호출부가 명시적으로
                         고르게 했습니다(위 median_shift_ratio 주석 참고).
        thresholds     : DEFAULT_THRESHOLDS 를 부분적으로 덮어쓸 dict(테스트용).

    반환 dict
        status / reason(한 줄 한글 요약) / reasons(걸린 항목별 한글 사유)
        / checks(검사 하나하나의 pass·fail·skipped 와 사유) / row_count / baseline_row_count
        / baseline_date
    """
    _validate_summary(today, "오늘")
    if baseline is not None:
        _validate_summary(baseline, "기준값")

    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)

    level_names = {str(name) for name in (level_fields or ())}
    min_rows = int(limits["min_rows_for_ratio_checks"])
    row_count = today["row_count"]
    baseline_rows = baseline["row_count"] if baseline else None
    checks = []

    # ── ⓪ 결과가 아예 비었는가 (기준값이 필요 없는 판정) ──────────────────────
    if row_count == 0:
        checks.append(_check("row_count_empty", None, "fail", "수집 결과가 0건입니다."))
    else:
        checks.append(_check("row_count_empty", None, "pass", f"수집 결과 {row_count:,}건."))

    # ── 어제 대비 검사를 할 수 있는가 ────────────────────────────────────────
    # 기준값이 아예 없거나, 있어도 표본이 너무 작으면(어제가 이미 비정상이었던 날)
    # 그 위에서 비율·중앙값을 계산해 봐야 잡음입니다. 그 판정을 여기 한 곳에서 하고
    # 아래 세 검사(건수·결측 급등·중앙값)가 모두 이 하나를 따릅니다(§0-3-10).
    if baseline is None:
        baseline_skip = "기준값이 없어 어제 대비 비교를 하지 않았습니다."
    elif baseline_rows < min_rows:
        baseline_skip = (f"기준값 행 수가 {baseline_rows:,}건뿐이라(최소 {min_rows}건)"
                         " 어제 대비 비교를 하지 않았습니다.")
    else:
        baseline_skip = None

    # ── ① / ② 건수 급감·급증 ────────────────────────────────────────────────
    if baseline_skip:
        checks.append(_check("row_count_drop", None, "skipped", baseline_skip))
        checks.append(_check("row_count_surge", None, "skipped", baseline_skip))
    else:
        ratio = row_count / baseline_rows
        drop_limit = 1.0 - float(limits["row_drop_ratio"])
        surge_limit = float(limits["row_surge_ratio"])
        basis = f"{baseline_date or '기준일 미상'} {baseline_rows:,}건 → 오늘 {row_count:,}건"
        if ratio < drop_limit:
            checks.append(_check(
                "row_count_drop", None, "fail",
                f"건수 급감: {basis} ({(1 - ratio) * 100:.1f}% 감소,"
                f" 기준 {float(limits['row_drop_ratio']) * 100:.0f}% 이상)."))
        else:
            checks.append(_check("row_count_drop", None, "pass", f"건수 정상: {basis}."))
        if ratio >= surge_limit:
            checks.append(_check(
                "row_count_surge", None, "fail",
                f"건수 급증: {basis} ({ratio:.2f}배, 기준 {surge_limit:.2f}배 이상)."
                " 같은 결과를 두 번 쌓았거나 대상 범위가 바뀌었을 수 있습니다."))
        else:
            checks.append(_check("row_count_surge", None, "pass", f"건수 급증 없음: {basis}."))

    # ── ③~⑥ 컬럼별 검사 ─────────────────────────────────────────────────────
    for name, stat in today["fields"].items():
        if not isinstance(stat, dict):
            raise DataSanityError(f"컬럼 요약이 dict 가 아닙니다: {name}")
        base_stat = None
        if not baseline_skip:
            candidate = baseline["fields"].get(name)
            base_stat = candidate if isinstance(candidate, dict) else None

        unusable = int(stat.get("missing_count", 0)) + int(stat.get("zero_count", 0))
        unusable_ratio = (unusable / row_count) if row_count else None

        # ③ 결측/0 비율(절대값)
        if row_count < min_rows:
            checks.append(_check(
                "unusable_ratio", name, "skipped",
                f"행이 {row_count:,}건뿐이라(최소 {min_rows}건) 결측/0 비율을 판정하지 않았습니다."))
        elif unusable_ratio >= float(limits["unusable_ratio"]):
            checks.append(_check(
                "unusable_ratio", name, "fail",
                f"'{name}' 결측·0 비율이 {unusable_ratio * 100:.1f}% 입니다"
                f" (결측 {stat.get('missing_count', 0):,} + 0 {stat.get('zero_count', 0):,}"
                f" / {row_count:,}건, 기준 {float(limits['unusable_ratio']) * 100:.0f}% 이상)."))
        else:
            checks.append(_check(
                "unusable_ratio", name, "pass",
                f"'{name}' 결측·0 비율 {unusable_ratio * 100:.1f}%."))

        # ④ 결측/0 비율의 급등(어제 대비 퍼센트포인트)
        if base_stat is None:
            checks.append(_check(
                "unusable_ratio_jump", name, "skipped",
                baseline_skip or f"기준값에 '{name}' 컬럼이 없어 결측 비율 변화를 비교하지 않았습니다."))
        elif row_count < min_rows:
            checks.append(_check(
                "unusable_ratio_jump", name, "skipped",
                f"행이 {row_count:,}건뿐이라 결측 비율 변화를 판정하지 않았습니다."))
        else:
            base_unusable = int(base_stat.get("missing_count", 0)) + int(base_stat.get("zero_count", 0))
            base_ratio = base_unusable / baseline_rows
            jump = unusable_ratio - base_ratio
            if jump >= float(limits["unusable_ratio_jump"]):
                checks.append(_check(
                    "unusable_ratio_jump", name, "fail",
                    f"'{name}' 결측·0 비율이 하루 만에 {base_ratio * 100:.1f}% →"
                    f" {unusable_ratio * 100:.1f}% 로 {jump * 100:.1f}%p 뛰었습니다"
                    f" (기준 {float(limits['unusable_ratio_jump']) * 100:.0f}%p 이상)."))
            else:
                checks.append(_check(
                    "unusable_ratio_jump", name, "pass",
                    f"'{name}' 결측·0 비율 변화 {jump * 100:+.1f}%p."))

        # ⑤ 값이 전부 동일(수집 실패를 한 상수로 채운 징후)
        numeric_count = int(stat.get("numeric_count", 0))
        if numeric_count < min_rows:
            checks.append(_check(
                "constant_value", name, "skipped",
                f"'{name}' 숫자로 읽힌 값이 {numeric_count:,}개뿐이라(최소 {min_rows}개)"
                " 상수 채움 판정을 하지 않았습니다."))
        elif int(stat.get("distinct_count", 0)) <= 1:
            checks.append(_check(
                "constant_value", name, "fail",
                f"'{name}' 값 {numeric_count:,}개가 전부 같은 값({stat.get('median')})입니다"
                " — 수집 실패를 한 상수로 채웠을 때 나오는 전형적인 모양입니다."))
        else:
            checks.append(_check(
                "constant_value", name, "pass",
                f"'{name}' 서로 다른 값 {stat.get('distinct_count', 0):,}개."))

        # ⑥ 값 수준(중앙값) 급변 — level_fields 로 지정된 컬럼만
        if name not in level_names:
            checks.append(_check(
                "median_shift", name, "skipped",
                f"'{name}' 은 수준 비교 대상 컬럼이 아닙니다(호출부 level_fields 미지정)."))
            continue
        today_median = stat.get("median")
        base_median = base_stat.get("median") if base_stat else None
        if base_stat is None:
            checks.append(_check(
                "median_shift", name, "skipped",
                baseline_skip or f"기준값에 '{name}' 컬럼이 없어 중앙값을 비교하지 않았습니다."))
        elif today_median is None or base_median is None or base_median == 0:
            checks.append(_check(
                "median_shift", name, "skipped",
                f"'{name}' 중앙값이 없거나 0이라(오늘 {today_median}, 기준 {base_median})"
                " 비교하지 않았습니다."))
        else:
            shift = today_median / base_median
            limit = float(limits["median_shift_ratio"])
            if shift >= limit or shift <= (1.0 / limit):
                checks.append(_check(
                    "median_shift", name, "fail",
                    f"'{name}' 중앙값이 {base_median:,.6g} → {today_median:,.6g} 로"
                    f" {shift:.2f}배 바뀌었습니다 (기준 {limit:.2f}배 이상 또는"
                    f" {1.0 / limit:.2f}배 이하). 단위·통화·대상 범위가 바뀌었는지"
                    " 확인이 필요합니다."))
            else:
                checks.append(_check(
                    "median_shift", name, "pass",
                    f"'{name}' 중앙값 {base_median:,.6g} → {today_median:,.6g} ({shift:.2f}배)."))

    failures = [c for c in checks if c["status"] == "fail"]
    skipped = [c for c in checks if c["status"] == "skipped"]
    passed = [c for c in checks if c["status"] == "pass"]

    if failures:
        status = STATUS_SUSPECT
        reasons = [c["detail"] for c in failures]
        reason = " / ".join(reasons)
    elif not passed:
        status = STATUS_NO_BASELINE
        reasons = []
        reason = ("판정할 수 있는 항목이 없었습니다 — "
                  + (skipped[0]["detail"] if skipped else "검사 항목이 없습니다."))
    elif baseline_skip:
        # 어제 대비 비교를 한 건도 못 했으면 '정상'이라고 말하지 않습니다 — 그건 사실이
        # 아니라 "아직 볼 수 없었다"입니다(§0-1).
        status = STATUS_NO_BASELINE
        reasons = []
        reason = (f"{baseline_skip} 기준값 없이도 가능한 검사 {len(passed)}건은"
                  " 통과했습니다."
                  + (" (첫 실행이면 내일부터 어제 대비 비교가 시작됩니다.)"
                     if baseline is None else ""))
    else:
        status = STATUS_OK
        reasons = []
        reason = (f"{baseline_date or '기준일 미상'} 대비 검사 {len(passed)}건 통과"
                  f"{f' (판정 불가 {len(skipped)}건)' if skipped else ''}.")

    return {
        "status": status,
        "reason": reason,
        "reasons": reasons,
        "baseline_date": baseline_date,
        "row_count": row_count,
        "baseline_row_count": baseline_rows,
        "checks": checks,
    }


# =============================================================================
# 4. 상태 파일 읽기·쓰기 (duel_batch 의 기준값 파일과 같은 규율)
# =============================================================================
def default_state_dir():
    """상태 파일이 사는 곳(`<저장소>/data`). duel_batch.default_state_dir() 과 같은 자리."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def sanity_state_path(dataset, data_dir=None):
    """데이터셋 하나의 상태 파일 경로(`data/<dataset>_sanity.json`)."""
    key = str(dataset or "").strip()
    if not _DATASET_KEY_RE.match(key):
        raise DataSanityError(
            f"데이터셋 키는 소문자·숫자·밑줄만 쓸 수 있습니다(받은 값: {dataset!r})."
            " 이 값이 그대로 파일명이 되므로 경로 조작을 허용하지 않습니다.")
    return os.path.join(data_dir or default_state_dir(), f"{key}{SANITY_FILENAME_SUFFIX}")


def load_sanity_state(path):
    """
    어제 상태 파일을 읽습니다. **파일이 없으면 `None`**(첫 실행 — 오류가 아닙니다).

    ⚠️ 파일이 있는데 깨졌거나 모르는 버전이면 **조용히 None 으로 넘기지 않고 예외**입니다
       (duel_batch.load_probe_state() 와 같은 이유 — "기준값이 없다"와 "기준값이 깨졌다"가
       로그에서 같은 모양이 되면 후자를 아무도 못 고칩니다).

    ⚠️ 단, `probe` 가 비어 있는 것 자체는 손상이 아닙니다 — 어제 판정이 실패해
       요약을 못 남긴 정상적인 기록일 수 있습니다. 그 경우 호출부가 "기준값 없음"으로
       다루면 됩니다.
    """
    if not path:
        raise DataSanityError("상태 파일 경로가 비어 있습니다.")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise DataSanityError(
            f"산티체크 상태 파일을 읽지 못했습니다({path}): {type(exc).__name__}."
            " 손상된 기준값으로 판정하지 않습니다 — 파일을 지우면 다음 실행이 새 기준값을"
            " 만들고, 그날은 '판정 불가'로 넘어갑니다.") from exc
    if not isinstance(payload, dict):
        raise DataSanityError(f"산티체크 상태 파일의 형식이 dict 가 아닙니다({path}).")
    if payload.get("version") != SANITY_STATE_VERSION:
        raise DataSanityError(
            f"산티체크 상태 파일의 형식 버전이 다릅니다({path}):"
            f" 기대 {SANITY_STATE_VERSION}, 실제 {payload.get('version')!r}."
            " 모르는 형식을 추측해서 읽지 않습니다.")
    return payload


def save_sanity_state(path, payload):
    """
    오늘 판정 + 오늘 요약을 저장합니다(워크플로우가 이 파일을 커밋합니다).

    같은 디렉터리에 임시 파일로 쓴 뒤 `os.replace()` 로 바꿔치웁니다 — 쓰는 도중 러너가
    죽어도 반쯤 쓰인 파일이 남지 않게 하려는 것입니다(duel_batch.save_probe_state() 와 동일).
    """
    if not path:
        raise DataSanityError("상태 파일 경로가 비어 있습니다.")
    if not isinstance(payload, dict) or not payload.get("dataset"):
        raise DataSanityError("저장할 산티체크 결과가 비어 있습니다.")
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    return path


# =============================================================================
# 5. 수집기가 부르는 단 하나의 함수
# =============================================================================
def check_dataset(dataset, rows, fields, *, target_date, level_fields=None,
                  path=None, data_dir=None, thresholds=None, now_kst=None, log=print):
    """
    수집기가 **결과를 이미 저장한 뒤** 마지막에 한 번 부르는 함수입니다.

      ① 어제 상태 파일을 읽어 기준값을 꺼내고
      ② 오늘 결과를 요약해
      ③ 판정하고
      ④ 오늘 요약을 내일의 기준값으로 같은 파일에 저장합니다.

    🔴 **이 함수는 절대 예외를 던지지 않습니다.** 수집은 이미 끝났고 결과 파일도 이미
       저장된 상태에서 불리기 때문에, 관찰자 때문에 수집이 실패로 뒤집히면 안 됩니다.
       다만 §0-1 대로 **삼키지도 않습니다** — 내부에서 무슨 문제가 나든 상태를
       `error` 로 남기고, 그 사유를 상태 파일과 로그 양쪽에 그대로 적습니다. 상태가
       `error` 면 `suspect` 와 똑같이 디스코드 알림 대상이 됩니다(ALERT_STATUSES).

    반환: 저장된 상태 payload dict(저장에 실패했더라도 판정 내용은 그대로 돌려줍니다).
    """
    moment = _now(now_kst)
    payload = {
        "version": SANITY_STATE_VERSION,
        "dataset": str(dataset),
        "generated_at_kst": moment.isoformat(),
        "target_date": None,
        "status": STATUS_ERROR,
        "reason": "",
        "reasons": [],
        "baseline_date": None,
        "row_count": None,
        "baseline_row_count": None,
        "checks": [],
        "probe": None,
    }

    try:
        state_path = path or sanity_state_path(dataset, data_dir=data_dir)
    except DataSanityError as exc:
        payload["reason"] = f"상태 파일 경로를 만들지 못했습니다: {exc}"
        payload["reasons"] = [payload["reason"]]
        _log_payload(log, payload)
        return payload

    try:
        payload["target_date"] = _date_text(target_date)
    except DataSanityError as exc:
        payload["reason"] = str(exc)
        payload["reasons"] = [payload["reason"]]
        _log_payload(log, payload)
        return payload

    # ① 기준값 — 읽기 실패는 "기준값 없음"과 구분해서 크게 남깁니다.
    load_error = None
    baseline_summary = None
    baseline_date = None
    try:
        previous = load_sanity_state(state_path)
    except DataSanityError as exc:
        previous = None
        load_error = str(exc)
    if isinstance(previous, dict):
        candidate = previous.get("probe")
        if isinstance(candidate, dict) and isinstance(candidate.get("fields"), dict):
            baseline_summary = candidate
            baseline_date = previous.get("target_date")

    # ②③ 요약 + 판정
    try:
        today_summary = summarize_dataset(rows, fields)
        # 판정이 뒤에서 실패하더라도 오늘 요약은 남겨 둡니다 — 그래야 내일이 '기준값 없음'
        # 으로 또 한 번 눈이 머는 일이 없습니다.
        payload["probe"] = today_summary
        verdict = judge_sanity(today_summary, baseline_summary,
                               baseline_date=baseline_date,
                               level_fields=level_fields, thresholds=thresholds)
        payload.update({
            "status": verdict["status"],
            "reason": verdict["reason"],
            "reasons": list(verdict["reasons"]),
            "baseline_date": verdict["baseline_date"],
            "row_count": verdict["row_count"],
            "baseline_row_count": verdict["baseline_row_count"],
            "checks": verdict["checks"],
        })
    except Exception as exc:      # noqa: BLE001 — 아래에서 상태로 남기고 로그로 크게 알립니다
        payload["status"] = STATUS_ERROR
        payload["reason"] = f"산티체크 판정에 실패했습니다: {type(exc).__name__}: {exc}"
        payload["reasons"] = [payload["reason"]]

    if load_error:
        payload["reasons"].insert(0, load_error)
        if payload["status"] != STATUS_SUSPECT:
            payload["status"] = STATUS_ERROR
        payload["reason"] = f"{load_error} / {payload['reason']}".strip(" /")

    # ④ 저장 — 내일의 기준값. 저장 실패도 삼키지 않고 크게 남깁니다.
    try:
        save_sanity_state(state_path, payload)
    except Exception as exc:      # noqa: BLE001
        note = (f"산티체크 상태 파일 저장 실패({state_path}): {type(exc).__name__}: {exc}"
                " — 내일 기준값이 없어 '판정 불가'가 됩니다.")
        payload["reasons"].append(note)
        if payload["status"] != STATUS_SUSPECT:
            payload["status"] = STATUS_ERROR
        payload["reason"] = f"{payload['reason']} / {note}".strip(" /")

    _log_payload(log, payload)
    return payload


def _log_payload(log, payload):
    """수집기 로그에 판정 결과를 남깁니다. 의심·오류는 눈에 띄게(§0-3-13)."""
    if not callable(log):
        return
    status = payload.get("status")
    label = STATUS_LABELS_KO.get(status, status)
    head = f"[산티체크] {payload.get('dataset')} — {label}"
    if status in ALERT_STATUSES:
        log("🚨 " + head)
        for detail in payload.get("reasons") or [payload.get("reason", "")]:
            log(f"   · {detail}")
        log("   ※ 수집 결과는 그대로 두었습니다(고치거나 지우지 않음). 사람이 확인해 주세요.")
    else:
        log(f"  {head}: {payload.get('reason', '')}")


# =============================================================================
# 6. 알림 문구 만들기 (워크플로우가 씁니다 — YAML 안에 판정 로직을 또 짜지 않기 위해)
# =============================================================================
def format_status_line(payload):
    """상태 payload 하나를 사람이 읽을 한 줄로. (디스코드 메시지·Actions 로그 공용)"""
    if not isinstance(payload, dict):
        return "• (형식을 알 수 없는 상태 파일) — 판정 결과를 읽을 수 없습니다."
    status = payload.get("status") or "(상태 없음)"
    label = STATUS_LABELS_KO.get(status, status)
    return ("• {dataset} — {label} (대상일 {target}, 기준일 {base}): {reason}").format(
        dataset=payload.get("dataset") or "(이름 없음)",
        label=label,
        target=payload.get("target_date") or "미상",
        base=payload.get("baseline_date") or "없음",
        reason=payload.get("reason") or "사유 없음",
    )


def alert_lines(payloads):
    """
    상태 payload 목록에서 **알림 대상(의심/판정 오류)만** 골라 한 줄씩 돌려줍니다.
    정상·판정 불가는 알리지 않습니다(조용한 날에 소음을 만들지 않기 위해).
    """
    lines = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            lines.append(format_status_line(payload))
            continue
        if payload.get("status") in ALERT_STATUSES:
            lines.append(format_status_line(payload))
    return lines
