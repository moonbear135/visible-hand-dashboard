# utils/duel_batch.py
"""
⚔️ "결투다!" (모의투자 대결 · 5번째 모듈, 2026-08-24 재번호) — **야간 배치 오케스트레이션 계층**

DUEL_MODULE_WORK_ORDER.md 2-5 "야간 배치의 순서와 위치"를 실제로 한 번에 돌리는 파일입니다.
지금까지 `utils/duel_rules.py`(순수 계산)와 `utils/duel_db.py`(Supabase 접근)는 있었지만,
**둘을 하루 한 번 순서대로 엮어 돌리는 코드가 어디에도 없었습니다.** 이 파일이 그것입니다.

-------------------------------------------------------------------------------
🧱 파일 나누기 — 왜 배치를 두 파일로 쪼갰는가
-------------------------------------------------------------------------------
    utils/duel_batch.py     ← **여기.** 순서·판정·행 만들기. 파일도 네트워크도 열지 않습니다.
                               Supabase 는 **인자로 받은 클라이언트**로만 만집니다.
    run_duel_daily_batch.py ← 실제 I/O 담당 얇은 실행 스크립트(저장소 루트).
                               환경변수 읽기 · service_role 클라이언트 생성 · 가격 파일 읽기 ·
                               신선도 기준값 파일 읽기/쓰기 · 요약 출력.

`utils/report_db.py` 가 "계산(A·B절) / Supabase(D절) / 배치 진입점(E절)"을 나눠 둔 것과 같은
발상이고, 이유도 같습니다 — 작업지시서 4단계가 요구하는 **오프라인 검증**(네트워크·Supabase
없이 `tests/test_duel_batch.py`)이 가능하려면, 판단하는 코드가 파일과 소켓을 직접 열면
안 됩니다. 이 파일의 함수는 전부 이미 읽어 온 값을 **평범한 파이썬 인자**로 받습니다
(`duel_rules.check_crawl_freshness()` 가 종가 dict 두 개를 인자로 받는 것과 같은 규율).

⚠️ 예외가 하나 있습니다 — 신선도 **기준값 파일**을 읽고 쓰는 `load_probe_state()` /
   `save_probe_state()` 는 이 파일에 있습니다(경로를 **인자로** 받으므로 테스트가 임시
   디렉터리를 가리키면 됩니다). 실행 스크립트가 아니라 여기 둔 이유는, 저장 형식(버전·키
   이름)과 그 형식을 해석하는 판정 로직이 **같은 파일 안에서 함께 읽혀야** 어긋나지 않기
   때문입니다.

-------------------------------------------------------------------------------
🕘 하루 한 번, 이 순서로 (작업지시서 2-5)
-------------------------------------------------------------------------------
  1. 그날 확정 종가가 실제로 확보됐는지 판정 (2-9) → 아니면 **체결 단계 전체를 건너뜀**
  2. 그날이 10일이면 정기 입금 (2-2) — **신선도 판정과 무관하게 실행**합니다.
     10일이 주말·공휴일이어도 그대로 10일자로 넣으라는 것이 2-2-4 이고, 이건 시장
     이벤트가 아니라 **현금 이벤트**라 크롤링 성패와 아무 상관이 없습니다.
  3. `pending` 주문 체결 → 포지션 갱신 → 원장 기록 (2-4-6)
  4. 일별 스냅샷 적재 (1-5 / 2-5-4)
  5. (5단계) 공개표 재생성 — **이 파일의 범위 밖입니다. 코드도 상수도 없습니다.**

-------------------------------------------------------------------------------
🔴 §0-3-2 (작업지시서 2-7) — 이 파일이 그 원칙이 가장 깨지기 쉬운 자리입니다
-------------------------------------------------------------------------------
계좌가 3개든 3만개든 **Supabase 왕복 횟수가 계좌 수에 비례하면 안 됩니다.** 이 파일은
전체를 몇 번 읽고(계좌 / 원장 / 포지션 / 스냅샷 / 그날 주문), 메모리에서 전부 계산한 뒤,
**한 번씩** 씁니다. 계좌별 루프는 파이썬 안에서만 돌고 그 안에는 질의가 없습니다.
`tests/test_duel_batch.py` 가 계좌 수를 바꿔 가며 **질의 횟수 자체를** 고정합니다.

체결 결과 기록(`record_order_fills()`)만 "그날 실제 체결된 주문 수"만큼 update 를 보냅니다 —
PostgREST 에 행마다 다른 값으로 한 번에 update 하는 문법이 없기 때문이고, 그 근거는
`duel_db.record_order_fills()` 의 주석에 이미 정리돼 있습니다(계좌 수 비례가 아니라 **일한
만큼**이라 §0-3-2 가 막으려는 모양이 아닙니다).

-------------------------------------------------------------------------------
⚠️ 지어내지 않기 (ENGINEERING_SPEC §0-1) — 이 파일이 특히 조심하는 세 곳
-------------------------------------------------------------------------------
  1. **판정이 'ok' 가 아니면 체결하지 않습니다.** `duel_rules.crawl_status_allows_fill()`
     하나로만 갈라집니다(문자열 비교를 여기저기 흩뿌리지 않습니다).
  2. **판정이 'ok' 가 아닌 날은 스냅샷도 쓰지 않습니다.** 근거는 아래 `build_snapshot_rows()`
     의 긴 주석 — 요약하면 "그날 믿을 수 있는 종가가 없으면 평가액을 만들 수 없고,
     만들어 넣으면 그 거짓말이 TWR 에 영구히 박힙니다".
  3. **건너뛴 날의 외부 현금흐름은 사라지지 않고 다음 스냅샷으로 이월**합니다
     (`collect_external_cash_flows()`). 이월하지 않으면 입금이 수익으로 둔갑합니다(2-6).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime

from utils import duel_db, duel_rules
from utils.duel_rules import KST, MONTHLY_DEPOSIT_DAY


class DuelBatchError(RuntimeError):
    """
    배치 진행 자체가 불가능할 때 던집니다(`ReportError` · `DuelDbError` 와 같은 역할).

    배치는 **조용히 성공한 척하면 안 됩니다.** 실패는 예외 → 비정상 종료(exit 1) →
    GitHub Actions 빨간 X 로 이어져야 오너가 알아챕니다. `utils/report_db.py::main()` 이
    같은 이유로 예외를 잡아 `return 1` 하는 것과 짝을 이룹니다.
    """


# =============================================================================
# 0. 상수 — 이 파일이 정하는 값들의 단일 출처 (§0-3-10)
# =============================================================================
#  ⚠️ 금액·시각·허용치처럼 **규칙에 속하는 숫자는 여기 적지 않습니다.** 그건 전부
#     `utils/duel_rules.py` 에 있고 여기서는 import 해서 씁니다. 아래는 "배치를 어떻게
#     돌릴지"에 대한 값들뿐입니다.

#: 전일 대비 신선도 점검의 **기준값(어제 값)** 을 담아 두는 파일 이름.
#: GitHub Actions 가 매 실행마다 저장소로 커밋합니다
#: (`.github/workflows/scrape_report_snapshots.yml` 이 `data/us_index_history.json` 을
#:  커밋하는 것과 똑같은 방식 — 자세한 설계 근거는 아래 §2 머리말).
PROBE_STATE_FILENAME = "duel_freshness_probe_previous.json"

#: 기준값 파일의 형식 버전. 나중에 키 이름이 바뀌면 이 숫자를 올리고, 읽는 쪽이 모르는
#: 버전을 만나면 **추측해서 읽지 않고** 기준값 없음으로 처리합니다(§0-1).
PROBE_STATE_VERSION = 1

#: 작업지시서 2-9 가 정한 점검 대상 지수. **이 저장소에는 코스닥 지수 종가 원천이 없습니다**
#: (`market_history.csv` 에 코스피만 — PROJECT_STATUS.md §10-3 이 "코스닥 지수는 이 파일에
#: 없어 v1 은 코스피만"이라고 이미 적어 뒀습니다). 그래서 실제로 돌릴 수 있는 기본값은
#: 코스피 하나이고, 실행 스크립트가 **매 실행 로그에 그 차이를 크게 남깁니다**
#: (조용히 51개로 줄여 놓고 52개인 척하지 않기 — §0-1).
PROBE_INDEX_KEYS_SPEC = ("KOSPI", "KOSDAQ")

#: 오늘 점검표와 어제 기준값 사이에 **공통으로 존재해야 하는 최소 종목 수**.
#: 왜 필요한가: 점검 대상은 "코스피 시가총액 상위 50종목"인데 그 50종목 명단은 순위가
#: 바뀌면 **매일 조금씩 달라집니다.** 50위와 51위가 자리를 바꾼 날 두 명단이 달라지고,
#: `duel_rules.check_crawl_freshness()` 는 두 dict 의 키 집합이 다르면(정당하게도) 판정을
#: 거부합니다. 그래서 배치는 **양쪽에 다 있는 종목만** 비교하고, 그 수가 이 값보다 적으면
#: "비교할 근거가 부족하다"로 보고 체결하지 않습니다.
#: 기본값 45 = 50종목 중 명단 교체가 5종목까지는 정상으로 봅니다(그 이상 바뀌면 수집 자체가
#: 이상한 것일 가능성이 높아 사람이 봐야 합니다).
MIN_PROBE_STOCK_OVERLAP = 45

#: 신선도 판정 결과 하나 추가 — **기준값(어제 값) 자체가 없음.**
#: `duel_rules` 의 네 상태(ok / failed / failed_or_holiday / needs_review)와 성격이 다릅니다:
#: 저 넷은 "수집 결과에 대한 판정"이고 이건 "우리 배치가 아직 비교할 기준을 못 갖췄다"는
#: **우리 쪽 사정**입니다. 그래서 `duel_rules` 에 넣지 않고 배치 계층에만 둡니다.
#: 처리: 체결하지 않고, **주문을 취소하지도 않습니다**(아래 §3 판정표 참고).
CRAWL_NO_BASELINE = "no_baseline"

#: 관리자가 명시적으로(=CLI 플래그로) 배치의 판정을 덮어쓸 때만 쓰는 값.
#: 화면·자동 경로에서 이 값을 만드는 코드는 없어야 합니다.
OVERRIDE_FILL = "fill"       # "관리자가 확인했고 그날 종가는 정상이다" → 체결 진행
OVERRIDE_CANCEL = "cancel"   # "관리자가 확인했고 그날은 실패다" → 귀속 주문 일괄 취소

#: TWR 의 분자에서 빼야 하는 **외부** 현금흐름의 원장 event_type (2-6 / 스키마 §5).
#: 매수(`buy`)는 계좌 안에서 현금이 주식으로 바뀐 것뿐이라 **여기 없습니다.**
EXTERNAL_CASH_FLOW_TYPES = ("seed", "monthly_deposit")

#: 스냅샷의 cash_flow_kind 가 가질 수 있는 값(스키마 §5 CHECK 와 같은 집합).
CASH_FLOW_KIND_MIXED = "mixed"

#: TWR 상태 하나 추가 — **계산 불가**(`duel_rules` 의 OK/NO_DATA/INSUFFICIENT 와 나란히).
#: 배치에서 TWR 은 로그용이라, 한 계좌가 계산 불가여도 배치를 죽이지 않고 이 상태로 남깁니다.
TWR_ERROR = "ERROR"


# =============================================================================
# 1. 작은 도우미
# =============================================================================
def _round6(value):
    """
    소수점 6자리 반올림. DB 의 금액 컬럼이 전부 `numeric(20, 6)` 이라 **여기서 반올림한
    값이 곧 저장되는 값**입니다(`utils/report_db.py::_round6()` · `duel_rules._round6()` 과
    같은 함수, 같은 이유).
    """
    return round(float(value), 6)


def _to_date(value, label="날짜"):
    """date / datetime / 'YYYY-MM-DD' → date. 없으면 만들지 않고 예외입니다(§0-1)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise DuelBatchError(f"{label}가 비어 있습니다(임의의 날짜를 만들지 않습니다).")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise DuelBatchError(f"{label} 형식을 알 수 없습니다: {value!r}") from None


def _positive_price(value):
    """양수 가격이면 float, 아니면 None. '값을 모른다'와 '0원'을 섞지 않기 위한 관문입니다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_sell_order(row):
    """
    주문 행이 **리밸런싱 매도**인가(`side='sell'`). 2026-08-21 추가.

    `side` 가 비어 있으면 **매수로 봅니다.** DB 는 `side` 를 not null + CHECK 로 막고 있어
    비어 올 수 없지만, 이 함수의 호출부가 "모르면 매도"로 기울면 값 하나가 빠졌을 때
    포지션이 줄어드는 쪽으로 오작동합니다 — 안전한 기본값은 언제나 수량이 줄지 않는 쪽입니다.
    """
    return str((row or {}).get("side") or "buy").strip().lower() == "sell"


def is_monthly_deposit_date(target_date):
    """
    그날이 정기 입금일(매월 10일)인가. 2-2 참고.

    `day == 10` 을 배치 코드 여기저기에 적지 않으려고 함수로 둡니다 — 날짜 규칙이 바뀌면
    고칠 곳이 `duel_rules.MONTHLY_DEPOSIT_DAY` 상수 하나입니다(§0-3-10).
    """
    return _to_date(target_date, "기준일").day == MONTHLY_DEPOSIT_DAY


# =============================================================================
# 2. 신선도 점검표(52개) 만들기와 기준값 파일 — work order 2-9
# =============================================================================
#  🔴 이 절이 이번 작업에서 **가장 판단이 많이 들어간 곳**이라 근거를 길게 남깁니다.
#
#  작업지시서 2-9 는 "오늘 값이 **전일 대비** 변했는지"를 보라고 합니다. 그런데 이 저장소의
#  가격 산출물(`data/kospi200_pegy_latest.json` · `market_history.csv`)에서 **어제 값을
#  꺼내는 확실한 방법이 없습니다**:
#    · `kospi200_pegy_latest.json` 은 이름 그대로 **최신 1회분**만 담습니다(어제분은 그 파일이
#      덮어써지면서 사라집니다).
#    · `data/kospi200_stock_history.csv` 에 종목별 날짜 이력이 쌓이긴 하지만, 이 스냅샷에는
#      그 파일이 없어 컬럼 구조를 **확인할 수 없었습니다.** 확인하지 못한 형식을 추측해서
#      파싱하는 코드는 §0-1 위반이라 쓰지 않았습니다.
#    · git 이력을 뒤져 어제 커밋의 파일을 꺼내는 방법도 있지만, 배치가 저장소 이력에
#      의존하기 시작하면(shallow clone·force push·재실행) 조용히 어긋납니다.
#
#  그래서 **배치가 자기 기준값을 스스로 굴립니다**:
#      실행 시작 → `data/duel_freshness_probe_previous.json` 을 읽어 "어제 52값"으로 씀
#      실행 끝   → 오늘 52값으로 같은 파일을 덮어씀 (내일의 기준값)
#      워크플로우가 그 파일을 저장소에 커밋 — `scrape_report_snapshots.yml` 이
#      `data/us_index_history.json` 을 커밋하는 것과 **완전히 같은 방식**입니다.
#
#  이 방식의 장점: 외부 형식 추측이 없고, 파일 하나 읽고 쓰는 게 전부라 임시 경로로
#  오프라인 테스트가 됩니다. 단점(오너가 알아야 할 것): **커밋이 실패하면 다음 날 기준값이
#  하루 낡습니다.** 그때는 "어제"가 아니라 "그저께"와 비교하게 되는데, 그 경우 값이 대체로
#  더 많이 변하므로 판정이 느슨해지는 쪽(=체결이 진행되는 쪽)입니다. 그래서 기준값 파일에
#  `target_date` 를 함께 적어 두고, 판정 결과에 그 날짜를 실어 로그에 찍습니다 — 기준이
#  언제 것인지 사람이 항상 볼 수 있게(§0-1).
# =============================================================================
def default_state_dir():
    """기준값 파일이 사는 곳(`<저장소>/data`). `scorecard_db.default_data_dir()` 과 같은 자리."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def default_state_path():
    """기준값 파일의 기본 경로. 테스트는 임시 경로를 직접 넘깁니다."""
    return os.path.join(default_state_dir(), PROBE_STATE_FILENAME)


def select_probe_stocks(universe_index, *, stock_count=duel_rules.CRAWL_STOCK_COUNT):
    """
    코스피 스냅샷에서 **시가총액 상위 `stock_count` 종목의 종가**를 뽑습니다(2-9).

    인자 `universe_index` 는 `scorecard_db.load_universe_index(MARKET_KR)` 이 돌려주는
    `{6자리 코드: 종목 dict}` 입니다 — 파일을 여는 일은 실행 스크립트가 하고, 여기서는
    이미 읽힌 dict 만 받습니다(§0-3-10 — 파싱을 두 번 짜지 않습니다).

    ⚠️ **순위 필드는 `rank`** 입니다. `utils/stock_history.py::KOSPI_HISTORY_FIELDS` 가
       `("rank", "시가총액 순위", "num")` 으로 이미 못 박아 둔, 이 스냅샷의 시가총액 순위
       컬럼입니다. 이 스테이징 스냅샷에는 실제 `data/*.json` 이 없어 **파일로 직접 확인하지는
       못했고**, 저장소의 다른 코드가 그 필드를 그렇게 쓰고 있다는 근거로 골랐습니다 —
       오너 확인 항목으로 작업 보고에 적어 두었습니다.

    ⚠️ `is_visible` / `is_unverified` 같은 플래그로 **거르지 않습니다.** 이 점검의 목적이
       "수집이 제대로 됐는가"라서, 수집에 문제가 있던 종목을 먼저 빼 버리면 정확히 잡아야 할
       실패를 스스로 가리게 됩니다. 종가가 양수로 들어와 있으면 그대로 넣습니다.

    ⚠️ 상위 `stock_count` 개를 못 채우면 **줄여서 판정하지 않고 예외**입니다 — 몇 종목만 보고
       그날 수집 성패를 판정하지 않는다는 규칙은 `check_crawl_freshness()` 안에도 이미
       들어 있습니다.

    반환: `{6자리 코드: 종가}` (정확히 `stock_count` 개)
    """
    if not isinstance(universe_index, dict) or not universe_index:
        raise DuelBatchError(
            "코스피 상위 종목 스냅샷이 비어 있어 신선도 점검표를 만들 수 없습니다"
            " (data/kospi200_pegy_latest.json 을 읽지 못했습니다)."
        )

    ranked = []
    for code, stock in universe_index.items():
        if not isinstance(stock, dict):
            continue
        price = _positive_price(stock.get("price"))
        if price is None:
            continue
        rank = stock.get("rank")
        if rank is None or isinstance(rank, bool):
            continue
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            continue
        ranked.append((rank, str(code), price))

    ranked.sort(key=lambda item: (item[0], item[1]))   # 순위 동률이면 코드순(재현 가능하게)
    if len(ranked) < stock_count:
        raise DuelBatchError(
            f"신선도 점검에 쓸 상위 {stock_count}종목을 채우지 못했습니다"
            f" (순위·종가가 함께 있는 종목이 {len(ranked)}개뿐)."
            " 몇 종목만 보고 그날 수집 성패를 판정하지 않습니다(작업지시서 2-9)."
        )
    return {code: price for _rank, code, price in ranked[:stock_count]}


def build_freshness_probe(target_date, index_closes, universe_index, *,
                          stock_count=duel_rules.CRAWL_STOCK_COUNT, now_kst=None):
    """
    오늘의 신선도 점검표(지수 + 상위 종목)를 만들어 **기준값 파일에 그대로 저장할 모양**으로
    돌려줍니다. work order 2-9 참고.

    인자
        index_closes : `{"KOSPI": 3210.5, ...}` — 실행 스크립트가 읽어 온 그날 지수 종가.
                       값이 없거나 0 이하인 지수가 하나라도 있으면 **예외**입니다
                       (없는 지수를 조용히 빼고 "점검했다"고 하지 않습니다 — §0-1).
        universe_index : 코스피 상위 200 스냅샷 인덱스(위 `select_probe_stocks()` 참고).

    반환 dict (그대로 JSON 으로 저장됩니다)
        version / generated_at_kst / target_date / index_keys / values
    """
    day = _to_date(target_date, "점검 기준일")
    if not isinstance(index_closes, dict) or not index_closes:
        raise DuelBatchError("점검할 지수 종가가 없습니다(지수 없이 신선도를 판정하지 않습니다).")

    values = {}
    missing = []
    for key in index_closes:
        price = _positive_price(index_closes[key])
        if price is None:
            missing.append(str(key))
        else:
            values[str(key)] = price
    if missing:
        raise DuelBatchError(
            f"지수 종가를 확보하지 못했습니다: {sorted(missing)}"
            " — 값이 없는 지수를 빼고 판정하면 '점검했다'는 말이 사실이 아니게 됩니다(§0-1)."
        )
    index_keys = sorted(values)

    stocks = select_probe_stocks(universe_index, stock_count=stock_count)
    overlap = sorted(set(stocks) & set(index_keys))
    if overlap:
        raise DuelBatchError(f"지수 키와 종목 코드가 겹칩니다: {overlap}")
    values.update(stocks)

    moment = now_kst if isinstance(now_kst, datetime) else datetime.now(KST)
    return {
        "version": PROBE_STATE_VERSION,
        "generated_at_kst": moment.astimezone(KST).isoformat()
        if moment.tzinfo else moment.replace(tzinfo=KST).isoformat(),
        "target_date": day.isoformat(),
        "index_keys": index_keys,
        "values": values,
    }


def load_probe_state(path):
    """
    어제 기준값 파일을 읽습니다. **파일이 없으면 `None`**(첫 실행 — 오류가 아닙니다).

    ⚠️ 파일이 있는데 깨졌거나 모르는 형식이면 **조용히 None 으로 넘기지 않고 예외**입니다.
       None 으로 넘기면 "기준값이 없어서 못 판정함"과 "기준값이 깨져서 못 읽음"이 로그에서
       같은 모양이 되고, 후자는 사람이 고쳐야 하는 사고입니다(§0-1).
    """
    if not path:
        raise DuelBatchError("기준값 파일 경로가 비어 있습니다.")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise DuelBatchError(
            f"신선도 기준값 파일을 읽지 못했습니다({path}): {type(exc).__name__}."
            " 손상된 기준값으로 판정하지 않습니다 — 파일을 지우면 다음 실행이 새 기준값을"
            " 만들고, 그날은 체결 없이 넘어갑니다."
        ) from exc

    if not isinstance(payload, dict):
        raise DuelBatchError(f"신선도 기준값 파일의 형식이 dict 가 아닙니다({path}).")
    if payload.get("version") != PROBE_STATE_VERSION:
        raise DuelBatchError(
            f"신선도 기준값 파일의 형식 버전이 다릅니다({path}):"
            f" 기대 {PROBE_STATE_VERSION}, 실제 {payload.get('version')!r}."
            " 모르는 형식을 추측해서 읽지 않습니다."
        )
    if not isinstance(payload.get("values"), dict) or not payload["values"]:
        raise DuelBatchError(f"신선도 기준값 파일에 값이 없습니다({path}).")
    return payload


def save_probe_state(path, probe):
    """
    오늘 점검표를 **내일의 기준값**으로 저장합니다(워크플로우가 이 파일을 커밋합니다).

    같은 디렉터리에 임시 파일로 쓴 뒤 `os.replace()` 로 바꿔치웁니다 — 쓰는 도중에 러너가
    죽어도 **반쯤 쓰다 만 기준값 파일이 남지 않게** 하려는 것입니다(반쯤 쓰인 파일은 다음
    실행에서 위 `load_probe_state()` 의 예외가 되고, 그러면 그날 체결이 통째로 멈춥니다).
    """
    if not path:
        raise DuelBatchError("기준값 파일 경로가 비어 있습니다.")
    if not isinstance(probe, dict) or not probe.get("values"):
        raise DuelBatchError("저장할 신선도 점검표가 비어 있습니다.")

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(probe, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    return path


# =============================================================================
# 3. 신선도 판정 — work order 2-9 / 2-5-1
# =============================================================================
#  판정 → 행동 표 (이 표가 이 파일의 핵심 결정입니다)
#
#   판정                 체결   그날 pending 주문   스냅샷   근거
#   ─────────────────────────────────────────────────────────────────────────────
#   ok                   함     체결/부분체결/만료  적재     2-4-6
#   failed               안 함  **전부 취소**       건너뜀   2-4-5 ("이월하지 않습니다")
#   failed_or_holiday    안 함  **전부 취소**       건너뜀   2-9-1 (휴장·실패를 구분 안 함)
#   needs_review         안 함  **그대로 pending**  건너뜀   2-9-4 (관리자 확인 후 최종 판정)
#   no_baseline          안 함  **그대로 pending**  건너뜀   우리 쪽 사정 (아래 설명)
#
#  🔴 `needs_review` 를 왜 "취소"가 아니라 "보류"로 두는가 — 이번 작업의 판단입니다.
#     · 체결하지 않는 것은 확정입니다: `duel_rules.crawl_status_allows_fill()` 이 이미
#       `'ok'` 하나만 True 로 정해 뒀고("애매할 때 진행하는 쪽으로 기울면 언젠가 잘못된
#       가격으로 체결됩니다"), 그건 규칙 계층이 승인받아 확정한 내용입니다.
#     · 남는 질문은 "그럼 그 주문들을 취소해 버릴 것인가"인데, 2-9-4 는 이 상태를
#       **"자동으로 실패를 확정하지 않고 관리자 확인을 거쳐 최종 판정"** 이라고 정했습니다.
#       배치가 즉시 취소해 버리면 그 "관리자 확인"이 할 수 있는 일이 사라집니다 — 취소는
#       되돌릴 수 없고, 사용자 주문은 이미 없어진 뒤니까요.
#     · 그래서 **주문은 pending 그대로 두고**, 관리자가 값을 확인한 뒤
#       `--target-date <그날> --override fill`(정상이었다) 또는 `--override cancel`(실패였다)
#       로 배치를 **다시 돌려** 결론을 내립니다. 주문의 `target_date` 는 그대로라 재실행이
#       그 주문들을 정확히 다시 집습니다.
#     · ⚠️ 관리자가 아무것도 하지 않으면 그 주문들은 **계속 pending 으로 남습니다.**
#       자동으로 정리되는 경로가 없다는 뜻이고, 이건 오너가 알고 있어야 하는 운영 부담입니다.
#       (작업 보고의 "오너 확인 필요" 항목에 적어 두었습니다.)
#
#  🔴 `no_baseline` 에서도 취소하지 않는 이유: 이 상태는 **수집이 실패했다는 증거가 아니라
#     우리 배치에 비교 기준이 없다는 사실**입니다. 우리 쪽 사정으로 사용자의 정상 주문을
#     "수집 실패" 사유를 붙여 취소하면, 그 사유 문장이 거짓이 됩니다(§0-1).
# =============================================================================
def judge_crawl_freshness(today_probe, previous_probe, *,
                          unchanged_tolerance=duel_rules.CRAWL_UNCHANGED_TOLERANCE,
                          min_stock_overlap=MIN_PROBE_STOCK_OVERLAP):
    """
    오늘 점검표와 어제 기준값을 비교해 그날 수집을 믿어도 되는지 판정합니다(2-9).

    **판정 자체는 `duel_rules.check_crawl_freshness()` 가 합니다.** 이 함수가 하는 일은
    그 순수 함수가 판정할 수 있는 모양으로 입력을 다듬는 것뿐입니다:
      ① 기준값이 없거나(첫 실행) 지수가 빠졌으면 → `no_baseline`(판정 시도조차 하지 않음)
      ② 상위 50종목 **명단이 어제와 조금 다른 경우**(순위 교체)를 흡수 — 양쪽에 다 있는
         종목만 비교하고, 그 수가 `min_stock_overlap` 미만이면 `no_baseline`
      ③ 남은 값으로 규칙 함수 호출

    ⚠️ ②의 "공통 종목만 비교"는 규칙을 느슨하게 만드는 게 아니라, 규칙이 **판정 자체를
       거부하는 상황**(키 집합 불일치 → `DuelRuleError`)을 피하기 위한 입력 정리입니다.
       비교 대상 수를 `expected_stock_count` 로 그대로 넘기므로, 허용 오차(무변동 10개)는
       실제로 비교한 종목 수 기준으로 적용됩니다.

    반환 dict
        status            : 'ok'/'failed'/'failed_or_holiday'/'needs_review'/'no_baseline'
        allows_fill       : 이 상태로 체결을 진행해도 되는가 (`ok` 만 True)
        reason            : 사람이 읽을 한 문장(로그·관리자용)
        baseline_date     : 기준값이 어느 날짜의 것인지(없으면 None)
        index_keys        : 실제로 비교한 지수 키
        compared_stocks   : 실제로 비교한 종목 수
        dropped_stocks    : 명단이 바뀌어 비교에서 빠진 종목 수
    """
    if not isinstance(today_probe, dict) or not today_probe.get("values"):
        raise DuelBatchError("오늘 신선도 점검표가 비어 있습니다.")

    today_values = dict(today_probe["values"])
    index_keys = tuple(today_probe.get("index_keys") or ())
    if not index_keys:
        raise DuelBatchError("오늘 점검표에 지수 키가 없습니다(무엇이 지수인지 추측하지 않습니다).")

    baseline_date = None
    result = {
        "status": CRAWL_NO_BASELINE,
        "allows_fill": False,
        "reason": "",
        "baseline_date": None,
        "index_keys": list(index_keys),
        "compared_stocks": 0,
        "dropped_stocks": 0,
    }

    if not previous_probe:
        result["reason"] = (
            "전일 기준값 파일이 없어 오늘 수집이 신선한지 판정할 수 없습니다"
            f" (오늘 값을 {PROBE_STATE_FILENAME} 에 기준값으로 남기므로 다음 실행부터 판정됩니다)."
        )
        return result

    previous_values = dict(previous_probe.get("values") or {})
    baseline_date = previous_probe.get("target_date")
    result["baseline_date"] = baseline_date

    missing_indices = [key for key in index_keys if key not in previous_values]
    if missing_indices:
        result["reason"] = (
            f"전일 기준값에 지수 {missing_indices} 가 없어 판정할 수 없습니다"
            " (기준값 형식이 바뀌었거나 지수 원천이 달라진 경우입니다)."
        )
        return result

    today_stocks = set(today_values) - set(index_keys)
    previous_stocks = set(previous_values) - set(index_keys)
    common_stocks = sorted(today_stocks & previous_stocks)
    result["compared_stocks"] = len(common_stocks)
    result["dropped_stocks"] = len(today_stocks) - len(common_stocks)

    if len(common_stocks) < min_stock_overlap:
        result["reason"] = (
            f"어제와 오늘 점검표에 공통으로 있는 종목이 {len(common_stocks)}개뿐이라"
            f" (최소 {min_stock_overlap}개 필요) 전일 대비 비교를 하지 않았습니다."
            " 상위 50종목 명단이 통째로 달라진 상황이라 사람이 한 번 봐야 합니다."
        )
        return result

    compare_keys = list(index_keys) + common_stocks
    today_subset = {key: today_values[key] for key in compare_keys}
    previous_subset = {key: previous_values[key] for key in compare_keys}

    # 🧮 판정은 규칙 계층이 합니다(이 파일에 무변동 세는 코드를 다시 짜지 않습니다).
    status = duel_rules.check_crawl_freshness(
        today_subset, previous_subset,
        index_keys=index_keys,
        expected_stock_count=len(common_stocks),
        unchanged_tolerance=unchanged_tolerance,
    )
    result["status"] = status
    result["allows_fill"] = duel_rules.crawl_status_allows_fill(status)
    result["reason"] = _freshness_reason(status, baseline_date, len(common_stocks))
    return result


def _freshness_reason(status, baseline_date, compared_stocks):
    """판정 결과를 사람이 읽을 한 문장으로. 로그와 주문 `fail_reason` 이 같은 문구를 씁니다."""
    basis = f"기준일 {baseline_date or '알 수 없음'} 대비 지수·상위 {compared_stocks}종목 비교"
    if status == duel_rules.CRAWL_OK:
        return f"{basis} 결과 그날 종가가 정상적으로 갱신됐습니다."
    if status == duel_rules.CRAWL_FAILED_OR_HOLIDAY:
        return (f"{basis} 결과 점검 대상이 전부 전일과 같습니다 —"
                " 휴장일이거나 수집 실패입니다(둘을 구분하지 않습니다, 작업지시서 2-9-1).")
    if status == duel_rules.CRAWL_FAILED:
        return (f"{basis} 결과 지수와 종목의 움직임이 앞뒤가 맞지 않습니다 —"
                " 수집 실패로 판정했습니다(작업지시서 2-9-2·3).")
    if status == duel_rules.CRAWL_NEEDS_REVIEW:
        return (f"{basis} 결과 무변동 종목이 허용치를 넘었습니다 —"
                " 자동으로 실패를 확정하지 않고 관리자 확인을 기다립니다(작업지시서 2-9-4).")
    return f"{basis} — 알 수 없는 판정({status})."


def resolve_action(freshness, override=None):
    """
    판정(+관리자 덮어쓰기) → **오늘 무엇을 할지**. 위 §3 머리말의 표를 코드로 옮긴 것입니다.

    `override` 는 관리자가 CLI 플래그로 명시할 때만 들어옵니다(`OVERRIDE_FILL` /
    `OVERRIDE_CANCEL`). 자동 경로에서 이 값을 만드는 코드는 이 저장소에 없습니다.

    반환 dict: fill / cancel_pending / write_snapshots / effective_status / override
    """
    status = freshness["status"]
    if override is None:
        effective = status
    elif override == OVERRIDE_FILL:
        effective = duel_rules.CRAWL_OK
    elif override == OVERRIDE_CANCEL:
        effective = duel_rules.CRAWL_FAILED
    else:
        raise DuelBatchError(
            f"알 수 없는 관리자 덮어쓰기 값입니다: {override!r}"
            f" (가능: {OVERRIDE_FILL} / {OVERRIDE_CANCEL})"
        )

    fill = effective == duel_rules.CRAWL_OK
    cancel = effective in (duel_rules.CRAWL_FAILED, duel_rules.CRAWL_FAILED_OR_HOLIDAY)
    return {
        "effective_status": effective,
        "override": override,
        "fill": fill,
        "cancel_pending": cancel,
        # 스냅샷은 체결과 운명을 같이 합니다 — 근거는 build_snapshot_rows() 주석.
        "write_snapshots": fill,
    }


# =============================================================================
# 4. 체결 계획 — work order 2-4-6
# =============================================================================
def plan_order_fills(pending_orders, cash_balances, close_prices, existing_positions,
                     fill_date, currency="KRW"):
    """
    그날 귀속된 `pending` 주문 전부에 대해 **무엇을 어떻게 기록할지**를 메모리에서 다 만듭니다.
    Supabase 를 부르지 않습니다(호출부가 결과를 그대로 일괄 기록합니다).

    계산은 전부 규칙 계층이 합니다:
      · 계좌별 FIFO 예수금 배정·부분체결 → `duel_rules.allocate_pending_orders()`
      · 가중평균 평단가 갱신           → `duel_rules.apply_buy_fill_to_position()`
      · 매도 체결(전량)                → `duel_rules.calculate_sell_fill()`
      · 매도 후 포지션(평단가 불변)     → `duel_rules.apply_sell_fill_to_position()`
    이 함수는 그 결과를 **표에 넣을 모양으로 담기만** 합니다.

    ── 🔴 계좌 안에서 **매도 먼저, 매수 나중** (2026-08-21 오너 확정 스펙 ④) ─────────────
    "같은 날 밤 매도 대금이 그날 밤 매수 재원으로 즉시 사용 가능"이 확정 스펙이라, 계좌별
    루프 안에서 그 계좌의 pending 주문을 side 로 한 번 더 갈라 **매도를 먼저 처리하고 그
    대금을 가용 현금에 더한 뒤** 기존 매수 배정(`allocate_pending_orders()`)으로 넘깁니다.
    순서를 뒤집으면 "오늘 판 돈으로 오늘 산다"가 불가능해져 리밸런싱이 하루씩 밀립니다.

    ⚠️ 매도에는 부분체결·만료가 없습니다(제약이 현금이 아니라 보유 수량이고, 저장 시점에
       이미 검증됐기 때문 — `duel_rules.calculate_sell_fill()` 주석). 그날 확정 종가가 없는
       매도는 매수와 **같은 자리·같은 방식**으로 `cancelled` 입니다(2-4-5).

    ⚠️ 보유 수량을 넘는 매도(규칙 계층이 예외로 막는 상태)는 **그 주문 하나만** 사유를 달아
       `cancelled` 로 돌리고 배치는 계속합니다. 예외를 그대로 올리면 계좌 하나의 불가능한
       상태가 그날 밤 **모든 사용자의 정산**을 멈춥니다 — 이 파일이 이미 계좌별 TWR 실패를
       같은 방식으로 격리하고 있고(`compute_twr_by_account()`), 활성 계좌 목록에 없는 주문을
       손대지 않고 경고로 올리는 것과도 같은 판단입니다. 사실은 사라지지 않습니다: 사유
       문장이 그 주문 행에 그대로 남습니다(§0-1).

    인자
        pending_orders    : `duel_db.fetch_pending_orders_for_fill()` 결과(saved_at 오름차순).
        cash_balances     : `{account_id: 예수금}` — 정기 입금까지 반영된 **체결 직전** 잔고.
        close_prices      : `{ticker: 그날 확정 종가}`. 없는 종목의 주문은 규칙 계층이
                            `cancelled` 로 돌려줍니다(0원·전일 종가로 때우지 않습니다).
        existing_positions: `{account_id: [포지션 행, ...]}`.
        fill_date         : 체결에 쓴 거래일(= 종가의 날짜).
        currency          : 실패 사유 문구의 통화 표기("KRW" 기본값 / "USD",
                            `duel_rules.allocate_pending_orders()`에 그대로 전달). 이 함수는
                            `duel_batch_usd.py`가 그대로 재사용합니다(2026-08-29 오푸스 감사
                            Top-5 #3) — 신설 전에는 항상 "원"이 붙어 USD 계좌 사용자가
                            "가용 예수금 1,051원" 같은 문구를 봤습니다.

    ⚠️ 같은 계좌에서 같은 종목을 **여러 건** 산 경우, 포지션 행은 **한 줄로 합쳐** 보냅니다.
       `duel_db.upsert_positions()` 는 한 요청에 같은 (계좌, 종목)이 두 번 들어오면 요청
       전체를 거절합니다(PostgREST 제약). 그래서 체결을 순서대로 누적 적용해 최종 수량·
       평단가 한 줄을 만듭니다 — 결과는 한 건씩 저장한 것과 같습니다(가중평균은 결합법칙이
       성립하고, `total_cost` 를 실제 쓴 돈으로 더하기 때문입니다).

    반환 dict
        fill_results   : `record_order_fills()` 에 그대로 넘길 목록(매수·매도 함께)
        ledger_entries : `record_buy_ledger_entries()` 에 그대로 넘길 목록(체결금액 0 은 제외).
                         매도 행은 `event_type='sell'` 로 표시돼 있고 금액은 양수입니다.
        position_rows  : `upsert_positions()` 에 그대로 넘길 목록((계좌,종목) 유일).
                         **수량이 줄어드는 행은 여기 없습니다** — 아래 참고.
        sell_position_rows : 수량이 **줄어든** 포지션. `settle_sell_positions()`(매도 정산
                         RPC) 로만 보낼 수 있습니다 — 일반 upsert 로 보내면
                         `duel_positions_buy_only()` 트리거가 요청 전체를 거절합니다.
        positions_by_account : 체결을 반영한 포지션(스냅샷 계산에 그대로 씁니다)
        cash_after     : 체결 후 계좌별 예수금(원장을 다시 읽지 않기 위해 계산으로 이어받음)
        counts         : filled / partially_filled / expired / cancelled / sells /
                         sell_filled / orders / accounts
        filled_amount_total : 그날 **매수에** 실제로 쓴 현금 합계(매도 대금은 포함하지 않습니다 —
                         "쓴 돈"과 "들어온 돈"을 한 숫자로 섞으면 로그가 거짓말을 합니다)
        sold_amount_total   : 그날 매도로 들어온 현금 합계
    """
    day = _to_date(fill_date, "체결 거래일")
    balances = dict(cash_balances or {})
    prices = dict(close_prices or {})

    # 계좌별 현재 포지션을 (계좌, 종목) 으로 펼쳐 둡니다(원본을 건드리지 않게 복사).
    #  · `original_quantities` 는 체결 **전** 수량입니다. 마지막에 "이 행이 줄었는가"를
    #    판정해 일반 upsert 와 매도 정산 RPC 로 갈라 보내는 근거가 됩니다.
    positions = {}
    original_quantities = {}
    for account_id, rows in (existing_positions or {}).items():
        for row in rows or []:
            ticker = str((row or {}).get("ticker") or "").strip()
            if not ticker:
                continue
            positions[(account_id, ticker)] = dict(row)
            original_quantities[(account_id, ticker)] = float((row or {}).get("quantity") or 0)

    fill_results = []
    ledger_entries = []
    touched_positions = set()
    counts = {"filled": 0, "partially_filled": 0, "expired": 0, "cancelled": 0,
              "sells": 0, "sell_filled": 0}
    filled_amount_total = 0.0
    sold_amount_total = 0.0

    grouped = duel_db.group_rows_by_account(pending_orders)
    for account_id in sorted(grouped):
        orders = grouped[account_id]
        # 잔고 키가 없다 = 그 계좌 원장에 행이 하나도 없다(조회는 전체를 한 번에 했으므로
        # "모르는 상태"가 아니라 "0원"이라는 관측 결과입니다).
        available = balances.get(account_id, 0.0)

        # ── ① 매도 먼저 (확정 스펙 ④ — 그날 매도 대금이 그날 매수 재원) ────────────
        #    입력 순서를 그대로 씁니다. 배치가 받는 목록은 이미 `saved_at` 오름차순이고
        #    (`duel_db.fetch_pending_orders_for_fill()`), 매도는 서로 현금을 두고 다투지
        #    않아 순서가 결과를 바꾸는 경우가 같은 종목을 두 번 파는 예외뿐입니다.
        sell_orders = [row for row in orders if _is_sell_order(row)]
        buy_orders = [row for row in orders if not _is_sell_order(row)]

        for raw in sell_orders:
            counts["sells"] += 1
            ticker = str((raw or {}).get("ticker") or "").strip()
            if not ticker:
                raise DuelBatchError(f"매도 주문에 종목코드가 없습니다: {raw!r}")
            key = (account_id, ticker)
            existing = positions.get(key)
            price = prices.get(ticker)

            settled = None
            if price is None:
                reason = (
                    f"{ticker}의 확정 종가를 확보하지 못해 매도를 체결하지 않고 취소했습니다"
                    " — 모르는 가격으로 팔거나 다음 날로 이월하지 않습니다(작업지시서 2-4-5)."
                )
            else:
                try:
                    settled = duel_rules.calculate_sell_fill(
                        raw.get("requested_quantity"), price,
                        (existing or {}).get("quantity") or 0)
                except duel_rules.DuelRuleError as exc:
                    # 계좌 하나의 불가능한 상태가 그날 밤 전체를 멈추지 않게 격리합니다
                    # (위 docstring 참고). 사유는 주문 행에 그대로 남습니다.
                    settled, reason = None, f"매도를 체결할 수 없어 취소했습니다: {exc}"

            if settled is None:
                counts[duel_rules.ORDER_CANCELLED] = counts.get(duel_rules.ORDER_CANCELLED, 0) + 1
                fill_results.append({
                    "id": raw.get("id"),
                    "status": duel_rules.ORDER_CANCELLED,
                    "filled_quantity": None,
                    "filled_price": None,
                    "filled_amount": None,
                    "filled_date": None,
                    "fail_reason": reason,
                })
                continue

            sold_quantity = int(settled["filled_quantity"])
            counts[duel_rules.ORDER_FILLED] = counts.get(duel_rules.ORDER_FILLED, 0) + 1
            counts["sell_filled"] += 1
            fill_results.append({
                "id": raw.get("id"),
                "status": settled["status"],
                "filled_quantity": sold_quantity,
                "filled_price": _round6(price),
                "filled_amount": settled["filled_amount"],
                "filled_date": day,
                "fail_reason": settled["fail_reason"],
            })

            # 매도 대금은 **양수**로 원장에 남깁니다(입금과 같은 방향 — 부호는
            # `duel_db._fill_ledger_payload()` 한 곳에서만 결정합니다).
            sold_amount_total += float(settled["filled_amount"])
            ledger_entries.append({
                "account_id": account_id,
                "order_id": raw.get("id"),
                "event_type": "sell",
                "filled_amount": settled["filled_amount"],
                "event_date": day,
                "memo": f"{ticker} {sold_quantity}주 매도 체결",
            })

            updated = duel_rules.apply_sell_fill_to_position(
                (existing or {}).get("quantity"), (existing or {}).get("avg_cost"),
                sold_quantity)
            positions[key] = {
                "account_id": account_id,
                "ticker": ticker,
                "stock_name": (existing or {}).get("stock_name")
                or str(raw.get("stock_name") or "").strip() or ticker,
                "quantity": updated["quantity"],
                # 매도는 잔여 주식의 평단가를 바꾸지 않습니다(규칙 계층이 그대로 돌려줍니다).
                "avg_cost": updated["avg_cost"],
                "status": (existing or {}).get("status") or "active",
                "delisted_date": (existing or {}).get("delisted_date"),
            }
            touched_positions.add(key)

            # 🔴 그날 밤 매수 재원이 되는 지점.
            available = _round6(available + float(settled["filled_amount"]))

        # 매도만 있고 매수가 없는 계좌도 잔고가 늘어야 하므로 여기서 한 번 반영합니다.
        balances[account_id] = _round6(available)

        # ── ② 그다음 매수 (기존 FIFO 배정 그대로 · 위에서 늘어난 현금으로) ──────────
        outcomes = duel_rules.allocate_pending_orders(available, buy_orders, prices, currency=currency)

        for outcome in outcomes:
            status = outcome["status"]
            counts[status] = counts.get(status, 0) + 1
            filled_quantity = int(outcome["filled_quantity"])
            order_row = outcome["order"]
            ticker = outcome["ticker"]

            fill_results.append({
                "id": outcome["id"],
                "status": status,
                "filled_quantity": filled_quantity or None,
                "filled_price": outcome["fill_price"] if filled_quantity else None,
                "filled_amount": outcome["filled_amount"] if filled_quantity else None,
                "filled_date": day if filled_quantity else None,
                "fail_reason": outcome["fail_reason"],
            })

            if not filled_quantity:
                continue

            filled_amount_total += float(outcome["filled_amount"])
            ledger_entries.append({
                "account_id": account_id,
                "order_id": outcome["id"],
                "filled_amount": outcome["filled_amount"],
                "event_date": day,
                "memo": f"{ticker} {filled_quantity}주 체결",
            })

            key = (account_id, ticker)
            existing = positions.get(key)
            updated = duel_rules.apply_buy_fill_to_position(
                existing.get("quantity") if existing else None,
                existing.get("avg_cost") if existing else None,
                filled_quantity,
                outcome["fill_price"],
            )
            positions[key] = {
                "account_id": account_id,
                "ticker": ticker,
                "stock_name": (existing or {}).get("stock_name")
                or str(order_row.get("stock_name") or "").strip() or ticker,
                "quantity": updated["quantity"],
                "avg_cost": updated["avg_cost"],
                "status": (existing or {}).get("status") or "active",
                "delisted_date": (existing or {}).get("delisted_date"),
            }
            touched_positions.add(key)

        if outcomes:
            balances[account_id] = outcomes[-1]["cash_after"]

    # 수량이 **줄어든** 행은 일반 upsert 로 보낼 수 없습니다(트리거가 요청 전체를 거절).
    # 그래서 여기서 두 갈래로 나눠, 호출부가 각각 맞는 경로로 보내게 합니다:
    #   · 늘거나 그대로 → `duel_db.upsert_positions()`
    #   · 줄어듦        → `duel_db.settle_sell_positions()`(duel.settled_sell 세션 변수 경로)
    # 같은 밤에 같은 종목을 팔고 다시 사서 **최종 수량이 늘어난** 경우는 감소가 아니므로
    # 일반 upsert 가 맞습니다(트리거도 통과합니다 — 줄어든 게 아니니까요).
    position_rows = []
    sell_position_rows = []
    for key in sorted(touched_positions):
        row = {
            "account_id": positions[key]["account_id"],
            "ticker": positions[key]["ticker"],
            "stock_name": positions[key]["stock_name"],
            "quantity": positions[key]["quantity"],
            "avg_cost": positions[key]["avg_cost"],
        }
        if float(row["quantity"]) < original_quantities.get(key, 0.0):
            sell_position_rows.append(row)
        else:
            position_rows.append(row)

    positions_by_account = {}
    for (account_id, _ticker), row in sorted(positions.items()):
        positions_by_account.setdefault(account_id, []).append(row)

    counts["orders"] = len(fill_results)
    counts["accounts"] = len(grouped)
    return {
        "fill_results": fill_results,
        "ledger_entries": ledger_entries,
        "position_rows": position_rows,
        "sell_position_rows": sell_position_rows,
        "positions_by_account": positions_by_account,
        "cash_after": balances,
        "counts": counts,
        "filled_amount_total": _round6(filled_amount_total),
        "sold_amount_total": _round6(sold_amount_total),
    }


# =============================================================================
# 5. 스냅샷 행 만들기 — work order 1-5 / 2-5-4 / 2-6
# =============================================================================
def last_snapshot_dates(snapshot_rows):
    """`{account_id: 마지막 스냅샷 날짜(date)}`. 스냅샷이 없는 계좌는 키 자체가 없습니다."""
    latest = {}
    for row in snapshot_rows or []:
        account_id = (row or {}).get("account_id")
        if not account_id or row.get("snapshot_date") is None:
            continue
        day = _to_date(row["snapshot_date"], "스냅샷 날짜")
        if account_id not in latest or day > latest[account_id]:
            latest[account_id] = day
    return latest


def collect_external_cash_flows(ledger_rows, previous_snapshot_dates, snapshot_date):
    """
    오늘 스냅샷에 적을 **외부 현금흐름**을 계좌별로 모읍니다. work order 2-6 / 스키마 §5 참고.

    외부 현금흐름 = 시드 지급 + 매월 10일 정기 입금. **매수는 아닙니다**(계좌 안에서 현금이
    주식으로 바뀐 것뿐이라 총자산이 변하지 않습니다). 상장폐지 상각도 아닙니다(평가손실).

    🔴 **"직전 스냅샷 다음날 ~ 오늘"의 흐름을 전부 합칩니다** — 그날 하루치만 보지 않습니다.
       이유: 수집 실패·휴장일에는 스냅샷을 쓰지 않으므로(아래 `build_snapshot_rows()` 주석),
       그 사이에 들어온 정기 입금이 어느 행에도 안 적힐 수 있습니다. 그러면 다음 스냅샷에서
       총자산만 80만원 오르고 `cash_flow_amount` 는 0 이라, TWR 이 그 입금을 **투자 수익으로
       계산**합니다. 그게 정확히 2-6 이 단순 수익률을 버린 이유이므로 반드시 이월해야 합니다.
       (직전 스냅샷이 아예 없으면 계좌 개설 이후 전부 — 그 행은 0일차라 TWR 곱에 들어가지
        않고 기준점이 됩니다.)

    반환: `{account_id: {"amount": float, "kind": 'seed'|'monthly_deposit'|'mixed'}}`
          — 금액이 0 인 계좌는 **키 자체가 없습니다**(스키마 CHECK: 금액 0 이면 종류도 NULL).
    """
    day = _to_date(snapshot_date, "스냅샷 날짜")
    previous = dict(previous_snapshot_dates or {})

    totals = {}
    kinds = {}
    for row in ledger_rows or []:
        account_id = (row or {}).get("account_id")
        event_type = (row or {}).get("event_type")
        if not account_id or event_type not in EXTERNAL_CASH_FLOW_TYPES:
            continue
        event_date = _to_date(row.get("event_date"), "원장 이벤트 날짜")
        if event_date > day:
            continue
        boundary = previous.get(account_id)
        if boundary is not None and event_date <= boundary:
            continue        # 이미 지난 스냅샷에 반영된 흐름 — 두 번 세지 않습니다.
        try:
            amount = float(row.get("amount"))
        except (TypeError, ValueError) as exc:
            raise DuelBatchError(f"현금 원장 금액이 손상됐습니다: {row.get('amount')!r}") from exc
        totals[account_id] = totals.get(account_id, 0.0) + amount
        kinds.setdefault(account_id, set()).add(event_type)

    flows = {}
    for account_id, amount in totals.items():
        rounded = _round6(amount)
        if rounded <= 0:
            continue
        kind_set = kinds.get(account_id) or set()
        kind = kind_set.pop() if len(kind_set) == 1 else CASH_FLOW_KIND_MIXED
        flows[account_id] = {"amount": rounded, "kind": kind}
    return flows


def build_snapshot_rows(accounts, positions_by_account, cash_balances, close_prices,
                        cash_flows, snapshot_date, *, price_as_of_kst=None):
    """
    **모든 활성 계좌**의 그날 스냅샷 행을 메모리에서 한꺼번에 만듭니다(§0-3-2 — 이걸
    `write_daily_snapshots()` 에 **한 번**에 넘깁니다. 계좌별로 저장하지 않습니다).

    반환하는 행의 모양은 `duel_db.write_daily_snapshots()` 의 `computed_rows` 규약 그대로입니다
    (`holdings` 하위 목록 포함). 이 함수는 그 규약을 **다시 정의하지 않고 맞춥니다.**

    ── 값을 어떻게 만드는가 ──────────────────────────────────────────────────────
      · `position_value` = 그날 종가를 **아는** 종목의 평가액 합. 모르는 종목은 더하지 않고
        `unpriced_count` 로 셉니다(0원으로 치지 않습니다 — §0-1 / 스키마 §5 주석).
      · `total_cost`     = 보유 전 종목의 매입원가 합(가격을 모르는 종목도 원가는 압니다).
      · `total_value`    = `position_value + cash_balance`. **따로 계산한 값이 아닙니다** —
        DB 가 십진수로 정확히 같은지 검사합니다(`duel_snapshots_total_match`).
      · 상장폐지(`status='delisted'`) 포지션은 **확인된 0원**이라 `close_price=0` ·
        `market_value=0` · `priced=True` 로 기록합니다(스키마 §5 주석이 정한 표현).
        "가격 수집 실패"(둘 다 NULL)와 절대 같은 모양이 되면 안 됩니다.

    ── 🔴 왜 수집 실패·휴장일에는 이 함수를 아예 부르지 않는가 (2-5/2-6 을 읽고 내린 결론) ──
      작업지시서 2-5 의 순서는 "① 종가 확보 판정 → … → ④ 스냅샷 적재"이고, ①에서 실패하면
      "체결 단계 전체를 건너뛴다"고만 적혀 있어 스냅샷을 쓸지 말지는 문면상 열려 있습니다.
      그래서 두 선택지를 실제로 따져 봤습니다.
        (A) 그날도 스냅샷을 쓴다 → 그러려면 평가액이 필요한데, 믿을 수 있는 그날 종가가
            없습니다. 전일 종가를 재사용하면 §0-3-1·§0-1 위반이고, 전 종목을 "가격 모름"으로
            처리하면 `position_value` 가 0 이 되어(스키마 §5 의 `priced_count > 0 or
            position_value = 0` 제약) **총자산이 현금만큼으로 폭락한 날**이 기록됩니다.
            그 행은 2-6 의 TWR 공식에 그대로 들어가 그날 −80%, 다음 날 +400% 같은 **완전한
            거짓 수익률**을 만들고, 스냅샷은 소급 재계산이 불가능하므로 그 거짓이 영구히 남습니다.
        (B) 그날은 스냅샷을 건너뛴다 → TWR 은 스냅샷이 있는 날들만 이어 곱하므로 하루가
            비어도 계산이 성립합니다(휴장일에 자산이 안 움직인 것과 결과가 같습니다).
            유일한 위험은 "그 사이의 입금이 기록되지 않는 것"인데, 그건 위
            `collect_external_cash_flows()` 의 이월로 정확히 해결됩니다.
      → **(B) 를 택했습니다.** 문서가 딱 잘라 정하지 않은 부분이라 여기 근거를 남깁니다.
    """
    day = _to_date(snapshot_date, "스냅샷 날짜")
    prices = dict(close_prices or {})
    balances = dict(cash_balances or {})
    flows = dict(cash_flows or {})

    rows = []
    for account in sorted(accounts or [], key=lambda item: str((item or {}).get("id") or "")):
        account_id = (account or {}).get("id")
        if not account_id:
            continue

        holdings = []
        position_value = 0.0
        total_cost = 0.0
        priced_count = 0
        unpriced_count = 0

        for position in (positions_by_account or {}).get(account_id) or []:
            ticker = str((position or {}).get("ticker") or "").strip()
            if not ticker:
                continue
            quantity = float(position.get("quantity") or 0)
            avg_cost = float(position.get("avg_cost") or 0)
            cost = _round6(quantity * avg_cost)
            total_cost += cost
            status = position.get("status") or "active"

            if status == "delisted":
                # 확인된 상장폐지 = 확인된 0원(3-1). "모름"이 아니라 "0 임을 안다"입니다.
                close_price, market_value, priced = 0.0, 0.0, True
            else:
                close_price = _positive_price(prices.get(ticker))
                if close_price is None:
                    market_value, priced = None, False
                else:
                    market_value, priced = _round6(quantity * close_price), True

            if priced:
                priced_count += 1
                position_value += float(market_value)
            else:
                unpriced_count += 1

            holdings.append({
                "ticker": ticker,
                "stock_name": position.get("stock_name"),
                "quantity": _round6(quantity),
                "avg_cost": _round6(avg_cost),
                "cost": cost,
                "close_price": None if close_price is None else _round6(close_price),
                "market_value": market_value,
                "status": status,
                "priced": priced,
                "price_as_of_kst": price_as_of_kst,
            })

        cash_balance = _round6(balances.get(account_id, 0.0))
        position_value = _round6(position_value)
        flow = flows.get(account_id) or {}
        row = {
            "account_id": account_id,
            "snapshot_date": day.isoformat(),
            "position_value": position_value,
            "cash_balance": cash_balance,
            # 두 관측값의 합. 따로 계산한 값을 넣으면 DB CHECK 가 그날 적재를 통째로 거절합니다.
            "total_value": _round6(position_value + cash_balance),
            "total_cost": _round6(total_cost),
            "cash_flow_amount": float(flow.get("amount") or 0.0),
            "cash_flow_kind": flow.get("kind"),
            "priced_count": priced_count,
            "unpriced_count": unpriced_count,
            "holdings": holdings,
        }
        if price_as_of_kst:
            row["price_as_of_kst"] = price_as_of_kst
        rows.append(row)
    return rows


def resolve_first_holding_updates(accounts, positions_before, positions_after):
    """
    "이번 정산으로 **처음** 주식이 들어온 계좌"를 골라냅니다(2026-08-21 추가). 메모리 계산만
    하고 Supabase 를 부르지 않습니다 — 실제 갱신은 호출부가
    `duel_db.set_first_holding_dates()` 로 **한 번에** 보냅니다(§0-3-2).

    왜 필요한가: 리밸런싱 창의 카운트다운 기준은 계좌 개설일이 아니라 **계좌에 최초로
    주식이 들어온 날**입니다(`duel_rules.resolve_rebalance_window()`). 그 날짜를 아는 유일한
    자리가 "체결로 포지션이 처음 생기는 순간", 즉 여기입니다.

    인자
        accounts         : `duel_db.fetch_all_active_accounts()` 결과(= `first_holding_date`
                           포함). 이 값이 이미 차 있으면 **손대지 않습니다**.
        positions_before : 체결 **전** `{account_id: [포지션 행]}`
        positions_after  : 체결 **후** `{account_id: [포지션 행]}`

    반환 dict
        new_ids : 오늘 처음 보유가 생긴 계좌 ID 목록(정렬됨). 이 계좌들만 갱신 대상입니다.
        missing : 보유는 있는데 `first_holding_date` 가 비어 있고 **오늘 처음 생긴 것도
                  아닌** 계좌 ID 목록. 이 기능이 생기기 전부터 보유가 있던 계좌들이라,
                  오늘 날짜로 채우면 **사실과 다른 창**이 만들어집니다(§0-1 — 지어내지
                  않습니다). 그래서 채우지 않고 호출부가 경고로 올려 오너가 과거 체결
                  기록을 보고 직접 채우게 합니다.

    ⚠️ "보유가 있다"의 기준은 **수량 > 0** 입니다. 전량 매도로 0주가 된 포지션 행은 남아
       있지만(스키마상 정상 상태), 그건 "주식을 갖고 있다"가 아닙니다.
    """
    def _holds(mapping, account_id):
        for row in (mapping or {}).get(account_id) or []:
            try:
                if float((row or {}).get("quantity") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    new_ids, missing = [], []
    for account in accounts or []:
        account_id = (account or {}).get("id")
        if not account_id or (account or {}).get("first_holding_date"):
            continue
        if not _holds(positions_after, account_id):
            continue
        if _holds(positions_before, account_id):
            missing.append(account_id)
        else:
            new_ids.append(account_id)
    return {"new_ids": sorted(new_ids), "missing": sorted(missing)}


def compute_twr_by_account(history_rows, new_rows):
    """
    계좌별 **누적 TWR**(2-6)을 계산합니다 — 계산 자체는 `duel_rules.compute_twr()` 가 합니다.

    ⚠️ `duel_daily_snapshots` 에는 **수익률 컬럼이 없습니다**(스키마 §5 확인). TWR 은 화면이
       스냅샷을 읽어 그때그때 계산하는 값이라, 배치가 여기서 구하는 TWR 은 **저장용이 아니라
       로그·요약용**입니다. 그래서 스냅샷 payload 에 넣지 않습니다 — 넣으면 PostgREST 가
       모르는 컬럼이라며 그날 적재 전체를 거절합니다.
       그럼 왜 계산하는가: 오너가 GitHub Actions 로그만 보고도 "오늘 계좌들이 어떤 상태인지"를
       알 수 있어야 하고(2-5 의 로그 요구), 값이 터무니없으면 그 자리에서 보이기 때문입니다.

    같은 날짜가 이력과 새 행에 모두 있으면 **새 행이 이깁니다**(배치 재실행 시 오늘 값이 두 번
    들어가 `compute_twr()` 의 "같은 날짜 중복" 예외가 나는 것을 막습니다).

    ⚠️ 계좌 하나의 TWR 이 계산 불가여도(예: 과거 어느 날 총자산이 0 이라 분모가 없음)
       **배치 전체를 죽이지 않습니다.** 이 값은 로그용이고, 그 시점엔 이미 체결과 원장이
       기록된 뒤라 여기서 예외가 나면 스냅샷만 빠진 반쪽 상태가 남습니다. 대신 그 계좌의
       상태를 `'ERROR'` 와 사유로 남겨 요약에 그대로 드러냅니다(삼키지 않기 — §0-1).
    """
    grouped = {}
    for row in history_rows or []:
        account_id = (row or {}).get("account_id")
        if account_id:
            grouped.setdefault(account_id, {})[_to_date(row.get("snapshot_date"))] = row
    for row in new_rows or []:
        account_id = (row or {}).get("account_id")
        if account_id:
            grouped.setdefault(account_id, {})[_to_date(row.get("snapshot_date"))] = row

    results = {}
    for account_id, by_date in grouped.items():
        ordered = [by_date[day] for day in sorted(by_date)]
        try:
            results[account_id] = duel_rules.compute_twr(ordered)
        except duel_rules.DuelRuleError as exc:
            results[account_id] = {"status": TWR_ERROR, "twr_pct": None, "period_count": 0,
                                   "baseline_date": None, "end_date": None, "error": str(exc)}
    return results


# =============================================================================
# 6. 하루치 배치 본체 — work order 2-5
# =============================================================================
def run_nightly_batch(service_client, target_date, *,
                      today_probe,
                      previous_probe,
                      close_price_of,
                      unchanged_tolerance=duel_rules.CRAWL_UNCHANGED_TOLERANCE,
                      min_stock_overlap=MIN_PROBE_STOCK_OVERLAP,
                      price_as_of_kst=None,
                      override=None,
                      dry_run=False,
                      log=print):
    """
    작업지시서 2-5 의 순서를 그대로 한 번 돌립니다. **파일도 네트워크도 열지 않습니다** —
    Supabase 는 인자로 받은 클라이언트로만, 가격은 인자로 받은 조회 함수로만 만집니다.

    인자
        service_client  : `duel_db.create_service_client()` 결과(배치 전용 service_role).
        target_date     : 처리할 거래일(= 그날 확정 종가의 날짜, KST 기준).
        today_probe     : `build_freshness_probe()` 결과.
        previous_probe  : `load_probe_state()` 결과(첫 실행이면 None).
        close_price_of  : `(ticker) -> 종가 또는 None`. 실행 스크립트가
                          `scorecard_db.make_price_lookup()` 을 감싸 넘깁니다(§0-3-10 —
                          "오늘 종가"의 두 번째 정의를 만들지 않습니다).
        override        : 관리자 덮어쓰기(`OVERRIDE_FILL`/`OVERRIDE_CANCEL`) — CLI 전용.
        dry_run         : True 면 **쓰기만** 건너뜁니다(읽기·계산은 그대로 — 로컬 점검용).

    ── Supabase 왕복 횟수 (§0-3-2 · 계좌 수와 무관) ──────────────────────────────
        읽기 : 활성 계좌 1 + 원장 1 (+ 체결일이면 주문 1 · 포지션 1 · 스냅샷 이력 1)
        쓰기 : 정기 입금 1(10일만) + 체결 결과 n(그날 체결된 주문 수) + 체결 원장 1
               + 매도 정산 RPC 1(**그날 매도 체결이 있는 밤만**) + 포지션 upsert 1
               + 최초 보유일 1(**그날 처음 보유가 생긴 계좌가 있는 밤만**)
               + 스냅샷 upsert 2(합계/종목별) — 또는 실패일이면 일괄 취소 1
               ⚠️ 새로 붙은 두 쓰기도 **계좌 수와 무관**합니다(각각 in 필터·jsonb 배열 1회).
                  해당 사건이 없는 밤에는 질의 자체를 보내지 않습니다.
    반환: 요약 dict(`format_summary_lines()` 에 그대로 넘길 수 있습니다).
    """
    day = _to_date(target_date, "처리 거래일")
    summary = {
        "target_date": day.isoformat(),
        "dry_run": bool(dry_run),
        "freshness": None,
        "action": None,
        "deposit_applied": 0,
        "deposit_attempted": False,
        "orders": {"filled": 0, "partially_filled": 0, "expired": 0, "cancelled": 0,
                   "sells": 0, "sell_filled": 0, "orders": 0, "accounts": 0},
        "filled_amount_total": 0.0,
        "sold_amount_total": 0.0,
        "ledger_rows_written": 0,
        "positions_written": 0,
        "sell_positions_settled": 0,
        "first_holding_dates_set": 0,
        "pending_cancelled": 0,
        "pending_held": 0,
        "snapshots_written": 0,
        "account_count": 0,
        "twr": {},
        "warnings": [],
    }

    # ── ① 신선도 판정 (2-5-1 / 2-9) ────────────────────────────────────────────
    freshness = judge_crawl_freshness(
        today_probe, previous_probe,
        unchanged_tolerance=unchanged_tolerance,
        min_stock_overlap=min_stock_overlap,
    )
    action = resolve_action(freshness, override)
    summary["freshness"] = freshness
    summary["action"] = action

    log(f"  · 수집 신선도 판정: {freshness['status']} — {freshness['reason']}")
    if override is not None:
        log(f"  ⚠️ 관리자 덮어쓰기 '{override}' 로 판정을 대체합니다"
            f" (실제 판정은 {freshness['status']} 였습니다).")

    accounts = duel_db.fetch_all_active_accounts(service_client)
    summary["account_count"] = len(accounts)
    account_ids = [row["id"] for row in accounts if row.get("id")]
    log(f"  · 활성 계좌 {len(accounts)}개")

    # ── ② 정기 입금 (2-2) — 신선도와 무관하게 실행합니다(현금 이벤트이므로) ─────
    if is_monthly_deposit_date(day):
        summary["deposit_attempted"] = True
        if dry_run:
            log("  · (dry-run) 정기 입금은 실행하지 않습니다.")
        else:
            summary["deposit_applied"] = duel_db.apply_monthly_deposits(service_client, day)
            log(f"  ✅ 정기 입금 {summary['deposit_applied']}건"
                f" (이미 들어간 계좌는 건너뜁니다 — 멱등)")

    # 입금 **이후에** 원장을 읽습니다. 순서가 뒤집히면 그날 입금한 80만원을 그날 주문에
    # 쓸 수 없게 되고, 그건 2-2-3 이 "10일 00:00:01 입금"으로 확정한 의도와 어긋납니다.
    ledger_rows = duel_db.fetch_cash_ledger_for_accounts(service_client, account_ids,
                                                         as_of_date=day)
    cash_balances = duel_db.cash_balances_by_account(ledger_rows)

    positions_by_account = {}
    fill_plan = None

    if action["fill"]:
        # ── ③ 체결 (2-4-6) ────────────────────────────────────────────────────
        pending = duel_db.fetch_pending_orders_for_fill(service_client, day)
        position_rows = duel_db.fetch_positions_for_accounts(service_client, account_ids)
        positions_by_account = duel_db.group_rows_by_account(position_rows)
        # 체결 **전** 보유 상태를 따로 들고 있습니다 — "오늘 처음 주식이 생긴 계좌"를
        # 판정하는 유일한 근거입니다(아래 `resolve_first_holding_updates()`).
        positions_before_fill = positions_by_account

        # 그날 pending 주문 조회는 **계좌 상태를 보지 않습니다**(거래일 + status 로만 거릅니다).
        # 활성 계좌 목록에 없는 계좌의 주문이 섞여 있으면, 그 계좌의 원장도 안 읽었으므로
        # 예수금이 0 으로 보이고 "예수금이 부족해 만료"라는 **사실이 아닌 사유**가 남습니다.
        # 그래서 손대지 않고 빼 두고, 대신 요약에 시끄럽게 올립니다(§0-1).
        active_ids = set(account_ids)
        orphaned = [row for row in pending if row.get("account_id") not in active_ids]
        if orphaned:
            pending = [row for row in pending if row.get("account_id") in active_ids]
            summary["warnings"].append(
                f"활성 계좌 목록에 없는 계좌의 pending 주문 {len(orphaned)}건은 손대지 않고"
                " 그대로 두었습니다(예수금을 확인할 수 없어 체결·만료 판정을 하지 않습니다)."
            )

        needed = {str(row.get("ticker") or "").strip() for row in pending}
        close_prices = {}
        for ticker in sorted(needed):
            if not ticker:
                continue
            price = _positive_price(close_price_of(ticker))
            if price is not None:
                close_prices[ticker] = price

        fill_plan = plan_order_fills(pending, cash_balances, close_prices,
                                     positions_by_account, day)
        summary["orders"] = fill_plan["counts"]
        summary["filled_amount_total"] = fill_plan["filled_amount_total"]
        summary["sold_amount_total"] = fill_plan["sold_amount_total"]
        positions_by_account = fill_plan["positions_by_account"]
        cash_balances = fill_plan["cash_after"]

        # 오늘 처음 보유가 생긴 계좌(= 리밸런싱 창의 기준일이 오늘로 정해지는 계좌).
        first_holding = resolve_first_holding_updates(
            accounts, positions_before_fill, positions_by_account)
        if first_holding["missing"]:
            summary["warnings"].append(
                f"보유 종목이 있는데 `first_holding_date` 가 비어 있는 계좌가"
                f" {len(first_holding['missing'])}개 있습니다"
                f" (예: {first_holding['missing'][:3]})."
                " 오늘 처음 생긴 보유가 아니라 오늘 날짜로 채우지 않았습니다 — 채우면 사실과"
                " 다른 리밸런싱 창이 만들어집니다(§0-1). 이 계좌들의 첫 체결일을 과거 주문"
                " 기록에서 확인해 오너가 직접 채워 주세요(그 전까지 매도 화면은 창을 계산할"
                " 수 없다고 정직하게 표시합니다)."
            )

        if dry_run:
            log(f"  · (dry-run) 체결 결과 {len(fill_plan['fill_results'])}건을 기록하지 않습니다.")
        else:
            written = duel_db.record_order_fills(service_client, fill_plan["fill_results"])
            summary["ledger_rows_written"] = duel_db.record_buy_ledger_entries(
                service_client, fill_plan["ledger_entries"])
            # 🔴 매도 정산이 **먼저**입니다 — 수량이 줄어드는 행은 전용 RPC 로만 통과하고
            #    (`duel.settled_sell` 세션 변수), 일반 upsert 로 보내면 트리거가 요청 전체를
            #    거절합니다. 두 목록은 (계좌, 종목)이 겹치지 않게 갈라져 있습니다.
            summary["sell_positions_settled"] = duel_db.settle_sell_positions(
                service_client, fill_plan["sell_position_rows"])
            saved = duel_db.upsert_positions(service_client, fill_plan["position_rows"])
            summary["positions_written"] = len(saved)
            if first_holding["new_ids"]:
                summary["first_holding_dates_set"] = duel_db.set_first_holding_dates(
                    service_client, first_holding["new_ids"], day)
            log(f"  ✅ 체결 결과 {written}건 기록 ·"
                f" 체결 원장 {summary['ledger_rows_written']}행 · 포지션 {len(saved)}건 갱신"
                + (f" · 매도 정산 {summary['sell_positions_settled']}건"
                   if summary["sell_positions_settled"] else "")
                + (f" · 최초 보유일 {summary['first_holding_dates_set']}계좌 기록"
                   if summary["first_holding_dates_set"] else ""))

    elif action["cancel_pending"]:
        # ── ③' 실패일 처리 (2-4-5) — 집합 연산 1회 ───────────────────────────
        reason = (f"{day.isoformat()} 확정 종가를 신뢰할 수 없어 이 주문은 체결되지 않고"
                  f" 취소되었습니다. {freshness['reason']}"
                  " 다음 거래일로 이월하지 않습니다(작업지시서 2-4-5).")
        if dry_run:
            log("  · (dry-run) 미체결 주문 일괄 취소를 실행하지 않습니다.")
        else:
            summary["pending_cancelled"] = duel_db.expire_or_cancel_all_pending_for_date(
                service_client, day, reason)
            log(f"  ⚠️ 체결하지 않고 그날 귀속 주문 {summary['pending_cancelled']}건을"
                " 취소했습니다(사유를 행에 남겼습니다).")

    else:
        # ── ③'' 보류 (needs_review / no_baseline) ─────────────────────────────
        held = duel_db.fetch_pending_orders_for_fill(service_client, day)
        summary["pending_held"] = len(held)
        summary["warnings"].append(
            f"[{freshness['status']}] {day.isoformat()} 귀속 pending 주문 {len(held)}건을"
            " 체결도 취소도 하지 않고 그대로 두었습니다 — 관리자가 값을 확인한 뒤"
            " `--override fill` 또는 `--override cancel` 로 이 날짜를 다시 돌려 결론을 내세요."
        )
        wait_for = ("관리자 확인 대기" if freshness["status"] == duel_rules.CRAWL_NEEDS_REVIEW
                    else "판정 기준값 없음")
        log(f"  ⚠️ {wait_for} — pending 주문 {len(held)}건을 그대로 보류했습니다"
            " (자동으로 체결하지도, 취소하지도 않습니다).")

    # ── ④ 일별 스냅샷 (2-5-4) ─────────────────────────────────────────────────
    if action["write_snapshots"]:
        history = duel_db.fetch_daily_snapshots_for_accounts(service_client, account_ids)
        previous_dates = last_snapshot_dates(
            [row for row in history if _to_date(row.get("snapshot_date")) < day])
        flows = collect_external_cash_flows(ledger_rows, previous_dates, day)

        snapshot_prices = {}
        for rows in positions_by_account.values():
            for position in rows:
                ticker = str((position or {}).get("ticker") or "").strip()
                if ticker and ticker not in snapshot_prices:
                    price = _positive_price(close_price_of(ticker))
                    if price is not None:
                        snapshot_prices[ticker] = price

        rows = build_snapshot_rows(accounts, positions_by_account, cash_balances,
                                   snapshot_prices, flows, day,
                                   price_as_of_kst=price_as_of_kst)
        summary["twr"] = compute_twr_by_account(
            [row for row in history if _to_date(row.get("snapshot_date")) < day], rows)
        for account_id, twr in summary["twr"].items():
            if twr.get("status") == TWR_ERROR:
                summary["warnings"].append(
                    f"계좌 {account_id} 의 누적 TWR 을 계산하지 못했습니다: {twr.get('error')}"
                    " (스냅샷 적재 자체에는 영향이 없습니다 — 화면이 같은 이유로 '계산 불가'를"
                    " 표시하게 되므로 과거 스냅샷을 한 번 확인해 보세요.)"
                )

        if dry_run:
            log(f"  · (dry-run) 스냅샷 {len(rows)}행을 저장하지 않습니다.")
        else:
            duel_db.write_daily_snapshots(service_client, day, rows)
            summary["snapshots_written"] = len(rows)
            log(f"  ✅ 일별 스냅샷 {len(rows)}행 적재(계좌 × 거래일 = 1행)")
    else:
        summary["warnings"].append(
            f"{day.isoformat()} 은(는) 그날 종가를 신뢰할 수 없어 스냅샷을 쓰지 않았습니다"
            " — 그 사이의 시드·정기입금은 다음 스냅샷의 cash_flow_amount 로 이월됩니다."
        )
        log("  · 스냅샷은 쓰지 않았습니다(믿을 수 있는 그날 종가가 없어 평가액을 만들 수 없습니다).")

    return summary


# =============================================================================
# 7. 사람이 읽는 요약 — GitHub Actions 로그에 실제로 보이는 것 (2-5)
# =============================================================================
def format_summary_lines(summary):
    """
    배치 결과를 오너가 로그에서 바로 읽을 수 있는 한국어 여러 줄로 만듭니다.

    문구 규약은 `utils/report_db.py::run_daily_snapshot_batch()` 와 같습니다 — 짧게,
    이모지 하나로 성격을 표시하고(✅ 성공 / ⚠️ 주의 / · 사실), 숫자는 단위와 함께.
    """
    freshness = summary.get("freshness") or {}
    action = summary.get("action") or {}
    orders = summary.get("orders") or {}
    lines = [
        "─" * 70,
        f"⚔️ 결투 야간 배치 요약 — {summary.get('target_date')}"
        + ("  (dry-run: 아무것도 저장하지 않았습니다)" if summary.get("dry_run") else ""),
        f"  · 수집 신선도: {freshness.get('status')}"
        f" (기준일 {freshness.get('baseline_date') or '없음'},"
        f" 비교 종목 {freshness.get('compared_stocks', 0)}개)",
    ]
    if action.get("override"):
        lines.append(f"  ⚠️ 관리자 덮어쓰기: {action['override']}"
                     f" → 실제 적용 판정 {action.get('effective_status')}")
    lines.append(f"  · 활성 계좌: {summary.get('account_count', 0)}개")

    if summary.get("deposit_attempted"):
        lines.append(f"  · 정기 입금(매월 10일): {summary.get('deposit_applied', 0)}건 신규 입금")
    else:
        lines.append("  · 정기 입금: 오늘은 입금일(매월 10일)이 아닙니다")

    if action.get("fill"):
        lines.append(
            f"  · 주문 {orders.get('orders', 0)}건 처리 —"
            f" 전량체결 {orders.get('filled', 0)} ·"
            f" 부분체결 {orders.get('partially_filled', 0)} ·"
            f" 예수금부족 만료 {orders.get('expired', 0)} ·"
            f" 종가없음 취소 {orders.get('cancelled', 0)}"
        )
        lines.append(f"  · 체결에 쓴 현금 합계: {summary.get('filled_amount_total', 0):,.0f}원")
        if orders.get("sells"):
            # 매도가 있었던 밤에만 한 줄 늘립니다(대부분의 밤에는 0건이라 조용합니다).
            lines.append(
                f"  · 리밸런싱 매도 {orders.get('sells', 0)}건 중"
                f" {orders.get('sell_filled', 0)}건 체결 —"
                f" 매도 대금 {summary.get('sold_amount_total', 0):,.0f}원"
                " (그날 매수 재원으로 즉시 반영됨)"
            )
    elif action.get("cancel_pending"):
        lines.append(f"  ⚠️ 체결 없음 — 그날 귀속 주문 {summary.get('pending_cancelled', 0)}건 취소")
    else:
        lines.append(f"  ⚠️ 체결 없음 — 판정 보류로 pending 주문 {summary.get('pending_held', 0)}건을"
                     " 그대로 두었습니다(취소하지 않았습니다)")

    lines.append(f"  · 일별 스냅샷: {summary.get('snapshots_written', 0)}행 적재")

    twr = summary.get("twr") or {}
    computed = [value for value in twr.values() if value.get("twr_pct") is not None]
    failed = [value for value in twr.values() if value.get("status") == TWR_ERROR]
    if computed:
        best = max(computed, key=lambda item: item["twr_pct"])
        worst = min(computed, key=lambda item: item["twr_pct"])
        lines.append(f"  · 누적 TWR 산출 계좌 {len(computed)}개 —"
                     f" 최고 {best['twr_pct']:.2f}% / 최저 {worst['twr_pct']:.2f}%")
    elif twr and not failed:
        # 0% 가 아니라 "아직 구간이 없다"입니다(개설일 스냅샷 하나뿐 — duel_rules 의 INSUFFICIENT).
        lines.append(f"  · 누적 TWR: 아직 계산할 구간이 없습니다(계좌 {len(twr)}개 전부 개설 직후)")
    if failed:
        lines.append(f"  ⚠️ 누적 TWR 계산 불가 계좌 {len(failed)}개 — 아래 경고 참고")

    for warning in summary.get("warnings") or []:
        lines.append(f"  ⚠️ {warning}")
    lines.append("─" * 70)
    return lines
