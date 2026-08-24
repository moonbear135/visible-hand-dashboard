"""
dividend_module/collector_dividend_kr.py
🇰🇷 한국 상장사 배당 수집기 — DART OpenAPI `alotMatter.json`("배당에 관한 사항") 기반.

================================================================================
📌 이 파일의 목적
================================================================================
visible_hand 의 신규 "배당금 모듈"이 쓸 **당해연도(진행 중인 사업연도) 배당 실적**을
전 종목(코스피+코스닥+코넥스, 약 2,700종목) 단위로 모읍니다.

이미 확보돼 있는 2023~2025년 배당 데이터(KIND 공식 연간 집계)는 "확정된 과거"이고,
이 수집기가 채우는 것은 그 뒤를 잇는 **"아직 진행 중인 올해"** 입니다. 두 축이 붙어야
"작년까지 이랬고, 올해는 지금까지 이만큼 나왔다"는 화면을 만들 수 있습니다.

================================================================================
📌 왜 `alotMatter.json` 인가 — 이전 접근(주요사항보고서 개별 열람)을 버린 이유
================================================================================
배당 정보를 DART 에서 얻는 길은 크게 셋입니다.

 (가) **공시 목록 API(`list.json`) + 주요사항보고서/수시공시 원문 개별 열람**
      → "현금·현물배당 결정" 공시를 종목별·건별로 찾아 **HTML 원문을 파싱**하는 방식.
      버린 이유:
        1. **요청량이 폭발합니다.** 종목당 (공시목록 1회 + 해당 공시 건수만큼 원문 조회)
           → 2,700종목이면 수만 건. §0-3-2("상대 서버에 무리를 주지 않는다") 정면 위반이고,
           DART 의 일 요청 한도(공식 안내상 20,000건 수준)도 넘길 위험이 큽니다.
        2. **원문 HTML 파싱은 구조가 회사마다 다릅니다.** 표의 몇 번째 행/열이라는 식의
           **위치 인덱스 파싱**으로 흘러가기 쉬운데, 그건 이 프로젝트가 §0-1 에서 명시적으로
           금지한 방식입니다("키워드 기반 동적 타겟팅만").
        3. **중간배당·분기배당·결산배당이 별건으로 흩어져** 있어, 이걸 우리가 더해서
           "누적 배당"을 만들면 그 합계는 **우리가 만든 수치**가 됩니다. 빠뜨린 공시가
           하나라도 있으면 조용히 과소집계되고, 아무도 모릅니다.

 (나) **`alotMatter.json`("배당에 관한 사항", 정기보고서 주요정보 그룹)** ← 채택
      → 회사가 **정기보고서(사업/반기/분기보고서)에 직접 기재한 배당 표**를 그대로 줍니다.
      채택 이유:
        1. **누적치를 회사가 직접 확정해서 적어 놓습니다.** 우리가 개별 공시를 더할 필요가
           없습니다 — 실측 확인: 삼성전자 2026 1분기보고서 주당현금배당금 372원,
           2026 반기보고서 746원(=372+374). 회계연도 누적 구조가 맞습니다.
        2. **요청량이 종목당 1~4건**으로 끝납니다(가장 최신 보고서 하나만 찾으면 되므로).
        3. **JSON 이고 항목이 `se`(구분) 라는 한국어 라벨로 옵니다.** 위치가 아니라
           라벨(키워드)로 값을 찾을 수 있어 §0-1 의 "키워드 기반 동적 타겟팅" 요건에 맞습니다.
        4. `rcept_no` 로 **원문 공시 문서에 바로 링크**를 걸 수 있어, 사용자가 우리 화면의
           숫자를 DART 원문과 직접 대조할 수 있습니다(값의 출처를 감추지 않음).

 (다) 증권사/포털 크롤링 → 출처가 2차 가공이고 약관 문제도 있어 1차 출처로 쓰지 않습니다.
      다만 §0-3-3(다중 출처 교차검증) 관점에서 **검증용 2차 출처**로는 유효합니다.
      → 이 수집기는 DART 응답에 함께 오는 `frmtrm`(전기)·`lwfr`(전전기) 값을
        **이미 보유한 2023~2025 KIND 데이터와 대조**하는 것으로 교차검증을 합니다.
        (그래서 이 수집기는 당기뿐 아니라 전기·전전기 값도 같이 보존합니다 — 공짜로 오는
         데이터이고, 우리 과거 데이터가 맞는지 검산할 수 있는 유일한 무료 수단입니다.)

      ✅ **교차검증은 구현돼 있고, 옵트인입니다** (`--history-baseline` / `run_collection(
         history_baseline_path=...)`). 경로를 주면 KIND 연간 배당 파일을 읽어
         `build_kind_baseline_index()` 로 (종목코드, 사업연도) 색인을 만들고,
         각 레코드의 전기(=사업연도-1)·전전기(=사업연도-2) 주당현금배당금·현금배당성향을
         `check_cross_source()` 로 대조해 **불일치를 `cross_source_notes` 에 기록**합니다.
         · 경로를 주지 않으면(기본값) `cross_source_notes` 는 항상 `[]` 입니다 — 기존 동작 그대로.
         · ⚠️ `unit_mismatch_notes` 와 **완전히 같은 철학**입니다: **감지만 하고 값은 절대
           고치지 않습니다**(§0-1). 두 출처가 다르다는 사실 자체를 데이터에 남겨 사람이
           판단하게 합니다(액면분할·재작성 등으로 정당하게 다를 수 있습니다).
         · 리포트에는 `records_with_cross_source_mismatch` /
           `stock_codes_with_cross_source_mismatch` 로 집계됩니다.

================================================================================
📌 API 규격 (2026-08-23 이 개발 세션에서 실제 호출로 확인)
================================================================================
GET https://opendart.fss.or.kr/api/alotMatter.json
  crtfc_key   : 발급키 (환경변수 DART_API_KEY 에서만 읽습니다 — 코드 하드코딩 금지)
  corp_code   : DART 8자리 고유번호 (⚠️ 종목코드가 아닙니다 → corp_code_mapper.py 참고)
  bsns_year   : 사업연도 4자리 (예: "2026")
  reprt_code  : 11011=사업보고서(연간) / 11012=반기보고서 / 11013=1분기 / 11014=3분기

응답: {"status":"000","message":"정상","list":[ {…}, … ]}
  각 항목: rcept_no, corp_cls, corp_code, corp_name, se, stock_knd,
           thstrm(당기), frmtrm(전기), lwfr(전전기), stlm_dt(결산기준일)
  · `se` 예: "주당 현금배당금(원)", "현금배당수익률(%)", "(연결)현금배당성향(%)",
             "현금배당금총액(백만원)", "주당액면가액(원)", "(연결)주당순이익(원)" …
  · `stock_knd`: "보통주" / "우선주" / "-"(주식 종류 구분이 없는 항목)
  · `stlm_dt`: 그 보고서가 다루는 기간의 결산기준일
               (1분기=03-31, 반기=06-30, 3분기=09-30, 사업보고서=12-31)

[✅ 실측 확인한 것 — 2026-08-23]
  · 삼성전자(00126380) 2026/11013 → status 000, 주당현금배당금(보통주) 372, stlm_dt 2026-03-31
  · 삼성전자(00126380) 2026/11012 → status 000, 주당현금배당금(보통주) 746, stlm_dt 2026-06-30
  · 삼성전자(00126380) 2026/11014 → status 013 (3분기보고서 미제출 시점이라 당연)
  · 존재하지 않는 corp_code(00000000) → status **013** (010/100 이 아님!)
  · 잘못된 인증키 → status **010**, HTTP 는 200 (오류가 HTTP 코드가 아니라 status 로 옵니다)

[⚠️ 실측으로 드러난 원자료의 이상 — 우리가 보정하지 않고 그대로 보존합니다]
  · 삼성전자 2026 1분기: 주당현금배당금 372원 / 현금배당수익률 0.20%
    삼성전자 2026 반기 : 주당현금배당금 746원 / 현금배당수익률 **0.20%** (그대로)
    → 주당배당금은 누적으로 두 배가 됐는데 수익률은 그대로입니다. 반면 같은 반기보고서의
      현금배당금총액(4,909,211백만원)·현금배당성향(4.10%)은 정상적으로 누적 반영돼 있습니다.
    → 즉 **분기·반기보고서의 `현금배당수익률(%)` 은 누적과 정합하지 않을 수 있습니다.**
      원인(분기 단위 산정인지, 회사 기재 오류인지)은 이 단계에서 단정할 수 없습니다.
      우리는 **값을 고치지도, 우리가 계산한 값으로 바꿔치지도 않습니다.** 원문 그대로
      저장하고 `yield_reliability_note` 로 "정기보고서 기준 원문값 / 누적정합 미보장"을
      함께 저장합니다. 화면에서 배당수익률을 보여줄 거라면 이 값 대신 (누적 주당배당금 ÷
      현재가)로 우리가 계산하고 그 사실을 표시하는 편이 안전합니다 — 오너 판단 필요.

================================================================================
📌 어느 보고서를 쓸 것인가 — "가장 최근에 확정된 누적치" 원칙
================================================================================
같은 사업연도에 대해 최대 4종의 정기보고서가 존재하고, 뒤에 나온 보고서일수록 더 많은
기간을 누적합니다. 그래서 **가장 나중 기간을 덮는 보고서부터** 찾아 내려갑니다.

    11011(사업보고서·연간 확정) → 11014(3분기) → 11012(반기) → 11013(1분기)

⚠️ 오너 지시 원문은 "3분기 있으면 그걸, 없으면 반기, 없으면 1분기"였습니다. 여기에
   **11011(사업보고서)을 맨 앞에 추가**한 것은 다음 이유이며, 동작상 오너 지시와
   충돌하지 않습니다.
     · 사업보고서는 그 사업연도의 **최종 확정 누적치**입니다. 존재한다면 3분기보다
       언제나 더 나은 답이므로 "가장 최근에 확정된 누적치" 원칙에 정확히 부합합니다.
     · 진행 중인 연도(예: 2026년 8월에 bsns_year=2026)를 조회하면 사업보고서는 애초에
       존재하지 않아 status 013 이 뜨고 곧바로 3분기로 넘어갑니다 → **오너 지시와 결과 동일**.
     · 다만 요청이 종목당 1건 늘어납니다. 그래서 `REPRT_CODE_PRIORITY_OWNER_ORDER` 로
       오너 지시 그대로의 순서도 상수로 두고, 우선순위를 인자로 갈아끼울 수 있게 했습니다.

📌 요청량 절감 옵션(`skip_not_yet_due=True`, 기본 꺼짐)
   법정 제출기한이 아직 지나지 않은 보고서는 존재할 수 없으므로 요청 자체를 건너뛸 수
   있습니다(자본시장법상 분기·반기보고서는 기간 종료 후 45일, 사업보고서는 90일 이내).
   ⚠️ 이 계산은 **12월 결산법인**을 전제합니다. 3월·6월 결산법인은 기준일이 달라
      "있는 보고서를 안 부르는" 사고가 날 수 있으므로 **기본값을 끕니다.** 켜면 요청량이
      대략 절반으로 줄지만, 그 대가로 비12월 결산법인을 놓칠 수 있다는 걸 알고 켜야 합니다.

================================================================================
📌 외부 서버 매너 (§0-3-2)
================================================================================
  · 요청 사이 `time.sleep(random.uniform(2.0, 3.0))` — collector_kospi200.py 와 같은 기준.
  · HTTP 429/403, DART status 020(요청 제한 초과)·010/011/012(키·IP 문제)·800(점검) 이 뜨면
    **재시도하지 않고 실행 전체를 즉시 중단**합니다. 조용히 우회하지 않습니다.
  · 네트워크 오류·5xx 만 1회 재시도합니다.
  · `max_requests` / `max_runtime_sec` 예산을 넘으면 체크포인트를 저장하고 정상 종료합니다.
    (⚠️ 2,700종목 × 최대 4요청 × 2.5초 ≈ 7.5시간 → GitHub Actions 단일 job 6시간 한도를
     넘길 수 있습니다. README_상황보고.md "요청량 산수" 절 참고.)

================================================================================
📌 §0-1 준수 요약 — 실패를 숨기지 않습니다
================================================================================
  · status 013(조회결과 없음)은 **"실패"가 아니라 "그런 데이터가 없음"** 이지만, 조용히
    스킵하지 않고 `no_data` 로 분류해 **몇 건인지 리포트에 반드시 집계**합니다.
    ⚠️ 실측으로 확인했듯 존재하지 않는 corp_code 도 013 을 돌려줍니다 →
      **"배당 데이터 없음"과 "corp_code 가 틀림"을 API 응답만으로는 구분할 수 없습니다.**
      이 한계를 숨기지 않고 각 레코드의 사유 문자열과 리포트에 명시합니다.
  · 파싱은 전부 `se` 라벨 **키워드 매칭**입니다. 위치 인덱스 파싱은 없습니다.
  · 처음 보는 `se` 라벨은 버리지 않고 `unknown_se_labels` 로 수집해 리포트에 올립니다
    (DART 가 항목을 추가/개명했을 때 조용히 누락되는 것을 막기 위함).
  · 같은 (항목, 주식종류)에 서로 다른 값이 둘 이상 오면(우선주가 여러 종류인 회사 등)
    **임의로 첫 값을 고르지 않고** 대표값을 None 으로 두고 후보 전부를 `_all` 에 남깁니다.
  · raw 응답과 가공 레코드를 **다른 파일로** 저장합니다(§0-3-3).

================================================================================
📌 아직 검증하지 못한 것 (첫 GitHub Actions 실행에서 반드시 확인)
================================================================================
  · 이 개발 샌드박스는 프록시 allowlist 때문에 `requests`/`curl` 로 opendart 에 직접 붙지
    못합니다. 위 "실측 확인"은 전부 별도 도구(WebFetch)로 개별 URL 을 호출해 얻은 것이고,
    **이 파일의 `requests` 경로는 한 번도 실행된 적이 없습니다.**
  · 2,700종목 전량 실행 시의 소요시간·실패율·DART 한도 도달 여부.
  · corpCode.xml ZIP 의 실제 내용물(corp_code_mapper.py 상단 참고).
  · 코스닥/코넥스 종목의 `corp_cls` 실제 값(문서상 K/N 이지만 우리가 본 건 삼성전자의 Y 뿐).
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, timedelta

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# 같은 폴더의 모듈. GitHub Actions 에서 `python -m` 없이 직접 실행돼도 import 되도록
# 스크립트 자신의 디렉터리를 sys.path 에 넣습니다(collector_kospi200.py 와 같은 관례).
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from corp_code_mapper import (  # noqa: E402
    DartCorpCodeError,
    DART_API_KEY_ENV,
    DART_FATAL_STATUSES,
    DART_STATUS_MESSAGES,
    _now_kst,
    get_api_key,
    get_corp_code_index,
    map_stock_codes,
    normalize_stock_code,
)

# =============================================================================
# 1. 엔드포인트·보고서 코드
# =============================================================================
DART_ALOT_MATTER_URL = "https://opendart.fss.or.kr/api/alotMatter.json"

# DART 공시 원문 문서 URL 템플릿 (rcept_no 로 바로 연결됩니다 — 사용자가 원문 대조 가능)
DART_DOCUMENT_URL_TEMPLATE = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

REPRT_CODE_NAMES = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}

# 기본 우선순위: 가장 나중 기간을 덮는 보고서부터 (파일 상단 "어느 보고서를 쓸 것인가" 참고)
REPRT_CODE_PRIORITY = ("11011", "11014", "11012", "11013")

# 오너 지시 원문 그대로의 순서(사업보고서 제외). 요청량을 종목당 1건 줄이고 싶을 때 사용.
REPRT_CODE_PRIORITY_OWNER_ORDER = ("11014", "11012", "11013")

# 12월 결산법인 기준 법정 제출기한 (자본시장법: 분기·반기 45일, 사업보고서 90일).
# (기간종료 월, 기간종료 일, 기한까지의 일수, 사업연도 대비 기한이 넘어가는 해 오프셋)
_REPRT_PERIOD_END = {
    "11013": (3, 31, 45),
    "11012": (6, 30, 45),
    "11014": (9, 30, 45),
    "11011": (12, 31, 90),
}

# =============================================================================
# 2. 시장구분 (corp_cls) — DART 문서 기준
#    ⚠️ 우리가 실제 응답으로 본 값은 삼성전자의 "Y" 뿐입니다. K/N/E 는 문서상 값입니다.
# =============================================================================
CORP_CLS_MARKET = {
    "Y": "유가증권시장(KOSPI)",
    "K": "코스닥시장",
    "N": "코넥스시장",
    "E": "기타(비상장 등)",
}

# =============================================================================
# 3. 크롤링 매너 상수 (§0-3-2) — collector_kospi200.py 기준을 그대로 따릅니다
# =============================================================================
DART_REQUEST_TIMEOUT_SEC = 20
DART_REQUEST_DELAY_MIN = 2.0        # time.sleep(random.uniform(2.0, 3.0))
DART_REQUEST_DELAY_MAX = 3.0
DART_NETWORK_RETRY = 1              # 네트워크/5xx 만 1회 재시도
DART_RETRY_DELAY_SEC = 5.0

# 1회 실행 예산. 넘으면 체크포인트를 남기고 정상 종료합니다(중단이 아니라 '이어하기').
# 20,000 은 DART 안내상의 일 한도라, 그보다 넉넉히 아래에서 멈춥니다.
DEFAULT_MAX_REQUESTS = 15_000
# GitHub Actions 단일 job 한도가 6시간이라 그보다 여유 있게 5시간에서 멈춥니다.
DEFAULT_MAX_RUNTIME_SEC = 5 * 60 * 60

# 체크포인트 저장 주기(종목 수)
CHECKPOINT_EVERY = 25


class DartApiError(RuntimeError):
    """alotMatter 호출 실패(그 종목만 실패). 메시지에 인증키를 절대 포함하지 않습니다."""


class DartFatalError(RuntimeError):
    """실행 전체를 멈춰야 하는 상태(키·IP·요청한도·점검). 재시도하지 않습니다(§0-3-2)."""


# =============================================================================
# 4. 값 정규화 — 순수 함수
# =============================================================================
def to_number(value):
    """
    DART 응답 값(문자열) → float. 숫자로 볼 수 없으면 None.

    ⚠️ 0.0 으로 채우지 않습니다 — '배당 없음(-)'과 '배당 0원'은 다른 사실입니다(§0-1).
       DART 는 '해당 없음'을 문자열 "-" 로 줍니다. 이걸 0 으로 바꾸면 "무배당"과
       "0원 배당 결의"가 구분 불가능해집니다.

    처리 대상:
      "1,668" → 1668.0     "25.10" → 25.1      "-" → None
      "" / None / "N/A" → None                 "△1,234"(회계 음수 표기) → -1234.0
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if f != f else f            # NaN 방어
    text = str(value).strip()
    if text in ("", "-", "–", "—", "N/A", "n/a", "null", "None"):
        return None
    # 한국 회계자료의 음수 표기(△, ▲)와 괄호 음수 표기를 흡수합니다.
    negative = False
    if text[0] in ("△", "▲"):
        negative, text = True, text[1:]
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = text.replace(",", "").replace(" ", "").replace("%", "").replace("원", "")
    if text in ("", "-"):
        return None
    try:
        f = float(text)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return -f if negative else f


def normalize_label(value):
    """`se` 라벨 비교용 정규화: 모든 공백 제거. (대소문자는 한국어라 의미 없음)"""
    if value is None:
        return ""
    return "".join(str(value).split())


def classify_stock_kind(value):
    """
    `stock_knd` → "common" / "preferred" / "none" / "other:{원문}".

    · "-" 또는 빈 값 = 주식 종류와 무관한 항목(배당총액·배당성향 등) → "none"
    · 우선주가 여러 종류인 회사(예: 2우B, 3우B)는 원문이 "우선주"가 아닐 수 있어
      **포함 검사**로 판정합니다. 어느 쪽에도 안 걸리면 지어내지 않고 "other:원문" 으로
      남겨 리포트에서 보이게 합니다.
    """
    text = normalize_label(value)
    if text in ("", "-", "–", "—"):
        return "none"
    if "우선" in text:
        return "preferred"
    if "보통" in text:
        return "common"
    return f"other:{text}"


def classify_se(label):
    """
    `se` 라벨 → (지표키, 산출기준) 로 분류합니다. **키워드 기반 동적 타겟팅**(§0-1).

    반환 지표키:
      "dps_cash"        주당 현금배당금(원)
      "dps_stock"       주당 주식배당(주)
      "cash_yield"      현금배당수익률(%)
      "stock_yield"     주식배당수익률(%)
      "payout_ratio"    현금배당성향(%)            ← 기준: "연결"/"별도"/None
      "cash_total"      현금배당금총액(백만원)
      "stock_total"     주식배당금총액(백만원)
      "eps"             주당순이익(원)             ← 기준: "연결"/"별도"/None
      "net_income"      당기순이익(백만원)         ← 기준: "연결"/"별도"/None
      "par_value"       주당액면가액(원)
      None              → 우리가 아직 모르는 라벨 (버리지 않고 리포트에 올립니다)

    ⚠️ 판정 순서가 중요합니다. "현금배당금총액"에도 '현금배당금'이 들어 있으므로
       '주당' 포함 여부와 '총액' 제외 조건을 함께 겁니다.
    """
    s = normalize_label(label)
    if not s:
        return None, None

    basis = None
    if "(연결)" in s or s.startswith("연결"):
        basis = "연결"
    elif "(별도)" in s or s.startswith("별도"):
        basis = "별도"

    if "액면가" in s:
        return "par_value", None
    if "수익률" in s:
        if "현금" in s:
            return "cash_yield", None
        if "주식" in s:
            return "stock_yield", None
        return None, None
    if "배당성향" in s:
        return "payout_ratio", basis
    if "총액" in s and "배당" in s:
        if "현금" in s:
            return "cash_total", None
        if "주식" in s:
            return "stock_total", None
        return None, None
    if "주당" in s and "배당" in s:
        if "현금" in s:
            return "dps_cash", None
        if "주식" in s:
            return "dps_stock", None
        return None, None
    if "주당순이익" in s:
        return "eps", basis
    if "당기순이익" in s:
        return "net_income", basis
    return None, None


# ── 단위 검증 (§2-4 "단위 변환 임의 적용 금지") ────────────────────────────────
# `classify_se` 는 키워드만 보고 지표를 정하는데, 출력 필드명(`cash_total_mkrw` 등)은
# 단위를 이미 확정해 버립니다. 라벨에 실제로 붙은 단위 토큰을 확인하지 않으면 회사가
# "천원" 으로 적어 보냈을 때 1000배 틀린 값이 조용히 정상값으로 저장됩니다.
# → 여기서는 **감지만** 합니다. 값을 자동 변환·보정하지 않습니다(§0-1: 우리가 값을
#   고치지 않는다). 불일치는 `unit_mismatch_notes` 로 데이터에 남겨 사람이 보게 합니다.

# 라벨 **맨 끝**의 괄호만 단위 후보로 봅니다.
# 실제 라벨은 "(연결)당기순이익(백만원)" 처럼 기준과 단위가 둘 다 괄호로 옵니다.
_UNIT_TOKEN_RE = re.compile(r"\(([^()]*)\)$")

# 괄호 안이지만 단위가 아닌 것들(산출기준 표기). 끝 괄호가 이것뿐이면 "단위 확인 불가".
_NON_UNIT_PAREN_TOKENS = ("연결", "별도")

# 지표키 → 기대 단위 토큰.
# ⚠️ 아래 값은 지어낸 것이 아니라 실제 수집 원본 data/dividend_kr_2026_raw.jsonl
#    (5,484응답 · 배당표 34,903행) 을 전수 조사해 관측된 **유일한** 토큰입니다.
#      dps_cash 4,212행 전부 "원"      / dps_stock  4,265행 전부 "주"
#      cash_total 2,572행 전부 "백만원" / stock_total 2,572행 전부 "백만원"
#      eps 2,572행 전부 "원"           / net_income 5,144행 전부 "백만원"
#      par_value 2,572행 전부 "원"
# 비율 지표(cash_yield / stock_yield / payout_ratio, 관측 토큰 전부 "%")는
# 출력 필드명이 단위를 함의하지 않고 단위 변환 대상도 아니라 여기서 제외합니다.
EXPECTED_UNIT_TOKENS = {
    "dps_cash": "원",
    "dps_stock": "주",
    "cash_total": "백만원",
    "stock_total": "백만원",
    "eps": "원",
    "net_income": "백만원",
    "par_value": "원",
}


def extract_unit_token(label):
    """
    `se` 라벨에서 **맨 끝 괄호 안의 단위 토큰**만 뽑습니다. (순수 함수)

    반환: 단위 토큰 문자열, 또는 None = **확인 불가**(괄호가 없거나, 끝에 없거나,
          끝 괄호가 단위가 아닌 산출기준 표기인 경우)

    · "현금배당금총액(백만원)"      → "백만원"
    · "(연결)당기순이익(백만원)"    → "백만원"  (앞의 "(연결)" 은 기준이라 무시)
    · "주당 주식배당(주)"           → "주"
    · "(연결)당기순이익"            → None      (단위 표기가 아예 없음)
    · "현금배당금총액 백만원"       → None      (괄호 형식이 아님)

    None 을 '문제 없음'으로 취급하면 안 됩니다 — 호출측에서 "확인 불가"로 기록합니다(§0-1).
    """
    s = normalize_label(label)
    if not s:
        return None
    match = _UNIT_TOKEN_RE.search(s)
    if not match:
        return None
    token = match.group(1).strip()
    if not token or token in _NON_UNIT_PAREN_TOKENS:
        return None
    return token


def check_unit_token(metric, label):
    """
    한 행의 단위가 기대와 맞는지 판정합니다. (순수 함수)

    반환: None(문제 없음 / 검증 대상 아님) 또는 사람이 읽는 사유 문자열.
    """
    expected = EXPECTED_UNIT_TOKENS.get(metric)
    if expected is None:
        return None                      # 단위 검증 대상이 아닌 지표(%(비율) 등)
    actual = extract_unit_token(label)
    if actual == expected:
        return None
    raw = label if label is not None else ""
    if actual is None:
        return (f"단위 확인 불가: `se` 라벨 '{raw}' 에서 단위 표기(끝 괄호)를 찾지 못했습니다 "
                f"— 지표 {metric} 의 기대 단위는 '{expected}' 입니다. 값은 원문 그대로 "
                "두었지만 단위 검증을 통과하지 못했습니다(사람 확인 필요).")
    return (f"단위 불일치: `se` 라벨 '{raw}' 의 단위가 '{actual}' 입니다 — 지표 {metric} 의 "
            f"기대 단위는 '{expected}' 입니다. 우리가 값을 변환하지 않고 원문 그대로 "
            "두었으므로, 이 레코드의 해당 값은 필드명이 뜻하는 단위가 아닐 수 있습니다"
            "(사람 확인 필요).")


# ── 2개 출처 교차검증 (§0-3-3) ────────────────────────────────────────────────
# DART 응답에는 당기(thstrm)뿐 아니라 전기(frmtrm)·전전기(lwfr)가 함께 실려 옵니다.
# 우리는 그 값을 이미 `prev_*`/`prev2_*` 로 저장하고 있지만, 지금까지 **아무 데도 대조하지
# 않았습니다**. 한편 프로젝트에는 KIND(한국거래소 공시채널) 출처의 독립적인 2023~2025
# 연간 배당 집계(data/dividend_history_kr_2023_2025.json)가 이미 있습니다.
# → 같은 종목·같은 사업연도에 대해 **DART 가 말하는 과거값**과 **KIND 가 말하는 과거값**을
#   맞대보면, 돈 한 푼·요청 한 건 더 쓰지 않고 2개 출처 교차검증이 됩니다(§0-3-3).
#
# ⚠️ `unit_mismatch_notes` 와 **동일한 철학**입니다 — **감지만** 합니다.
#    · 값을 자동 보정하지 않습니다. 어느 쪽이 '맞다'고 단정하지도 않습니다(§0-1).
#    · 불일치는 정당한 사유(액면분할, 재무제표 재작성, 중간배당 반영 시점 차이, 우선주
#      종류 차이 등)로도 생길 수 있습니다. 우리가 판정할 수 없으므로 **사실만 적습니다**.
#    · 대조할 짝이 없으면(기준선에 그 종목·연도가 없거나 DART 값이 None) **불일치가 아닙니다**
#      — 조용히 '문제 없음'으로도, '문제 있음'으로도 만들지 않고 아무 note 도 남기지 않습니다.

# 현금배당성향(%)은 계산된 백분율이라 출처마다 반올림 자리가 다릅니다.
# 이 값보다 크게 벌어질 때만 '다르다'고 말합니다(반올림 차이를 불일치로 부풀리지 않기).
CROSS_SOURCE_PAYOUT_TOLERANCE_PCT = 0.05


def build_kind_baseline_index(history_payload):
    """
    KIND 연간 배당 파일(`{"records": [...]}`) → `{(종목코드, 사업연도int): {...}}` 색인.
    (순수 함수 — 파일 입출력 없음. 호출측이 json.load 한 dict 를 넘깁니다.)

    반환 값의 각 항목: {"dps_krw": …, "payout_ratio_pct": …}  (없으면 None)

    · `stock_code` 나 `fiscal_year` 가 없거나 정수로 볼 수 없는 행은 **건너뜁니다**
      (교차검증용 색인이라, 못 쓰는 행 하나 때문에 전체가 죽으면 안 됩니다).
    · 같은 (종목, 연도) 가 두 번 나오면 **먼저 나온 것을 유지**합니다. 뒤엣것으로 덮으면
      어느 값이 쓰였는지 설명할 수 없게 됩니다(§0-1: 임의 선택 금지 — 여기서는 순서라는
      명시적 규칙을 둡니다).
    · `records` 외의 최상위 키(source, record_count …)는 보지 않습니다.
    """
    index = {}
    if not isinstance(history_payload, dict):
        return index
    for row in history_payload.get("records") or []:
        if not isinstance(row, dict):
            continue
        code = row.get("stock_code")
        year = row.get("fiscal_year")
        if code in (None, "") or year in (None, ""):
            continue
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            continue
        key = (str(code).strip(), year_int)
        if key in index:
            continue                       # 첫 값 유지
        index[key] = {"dps_krw": row.get("dps_krw"),
                      "payout_ratio_pct": row.get("payout_ratio_pct")}
    return index


def _cross_source_number(value):
    """교차검증용 숫자 변환. 숫자로 볼 수 없으면 None(=대조 대상 아님)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if f != f else f
    return to_number(value)


def check_cross_source(stock_code, bsns_year,
                       prev_dps_cash_common, prev2_dps_cash_common,
                       prev_payout_ratio, prev2_payout_ratio,
                       baseline_index):
    """
    DART 의 전기·전전기 값 ↔ KIND 기준선(2023~2025)을 대조합니다. (순수 함수)

    반환: 사람이 읽는 불일치 사유 문자열 리스트. **빈 리스트 = 불일치 없음 또는 대조 불가**.
          (둘을 구분하지 않는 이유: 어느 쪽이든 "우리가 잡아낸 문제는 없다" 이고, 대조 불가를
           불일치로 세면 무배당·미상장 종목이 전부 경고로 뜹니다.)

    · 전기  = bsns_year - 1  / 전전기 = bsns_year - 2
    · DART 값과 기준선 값이 **둘 다 있을 때만** 비교합니다. 한쪽이라도 없으면 note 없음.
    · 주당현금배당금(원)은 정수 원 단위라 1원 이상 벌어지면 불일치로 봅니다.
    · 현금배당성향(%)은 계산된 백분율이라 반올림 차이를 감안해
      `CROSS_SOURCE_PAYOUT_TOLERANCE_PCT`(0.05%p) 를 넘을 때만 불일치로 봅니다.
    · 값을 고치지 않습니다. 어느 출처가 맞다고 단정하지도 않습니다(§0-1).
    """
    notes = []
    if not isinstance(baseline_index, dict) or not baseline_index:
        return notes
    try:
        year = int(bsns_year)
    except (TypeError, ValueError):
        return notes
    code = str(stock_code).strip() if stock_code not in (None, "") else None
    if not code:
        return notes

    checks = (
        ("전기", year - 1, prev_dps_cash_common, prev_payout_ratio),
        ("전전기", year - 2, prev2_dps_cash_common, prev2_payout_ratio),
    )
    for period_label, target_year, dart_dps, dart_payout in checks:
        baseline = baseline_index.get((code, target_year))
        if not isinstance(baseline, dict):
            continue                        # 기준선에 그 종목·연도가 없음 → 대조 불가

        base_dps = _cross_source_number(baseline.get("dps_krw"))
        dps = _cross_source_number(dart_dps)
        if base_dps is not None and dps is not None and abs(dps - base_dps) >= 1:
            notes.append(
                f"{code}: DART 응답의 {target_year}년({period_label}) 주당현금배당금(보통주) "
                f"{dps:,.0f}원이 KIND 2023~2025 기준선의 {base_dps:,.0f}원과 다릅니다"
                f"(차이 {dps - base_dps:+,.0f}원). 두 출처가 어긋난 사실만 기록하며 값은 "
                "고치지 않았습니다 — 액면분할·재작성 등 정당한 사유일 수 있어 사람 확인이 필요합니다.")

        base_payout = _cross_source_number(baseline.get("payout_ratio_pct"))
        payout = _cross_source_number(dart_payout)
        if (base_payout is not None and payout is not None
                and abs(payout - base_payout) > CROSS_SOURCE_PAYOUT_TOLERANCE_PCT):
            notes.append(
                f"{code}: DART 응답의 {target_year}년({period_label}) 현금배당성향 "
                f"{payout:.3f}%가 KIND 2023~2025 기준선의 {base_payout:.3f}%와 다릅니다"
                f"(차이 {payout - base_payout:+.3f}%p, 허용 {CROSS_SOURCE_PAYOUT_TOLERANCE_PCT}%p). "
                "두 출처가 어긋난 사실만 기록하며 값은 고치지 않았습니다 — 연결/별도 기준 차이나 "
                "재작성일 수 있어 사람 확인이 필요합니다.")
    return notes


# =============================================================================
# 5. 응답 판정 · 보고서 선택 — 순수 함수 (오프라인 테스트 대상)
# =============================================================================
def dart_status_of(payload):
    """응답 dict 에서 status 문자열을 꺼냅니다. dict 가 아니면 None."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return str(status) if status is not None else None


def is_usable_alot_response(payload):
    """
    이 응답을 '이 보고서에 배당 표가 실제로 있다'고 볼 수 있는가? (순수 함수)

    반환: (bool, 사유 문자열)

    조건: status == "000" 이고 `list` 가 비어있지 않으며, **배당 관련 항목이 최소 1개**
    들어 있어야 합니다. status 000 인데 list 가 빈 경우를 '사용 가능'으로 보면 그 보고서를
    골라놓고 아무 값도 못 채우는 빈 레코드가 만들어집니다(§0-1: 빈 껍데기를 '수집 성공'으로
    기록하지 않기).
    """
    status = dart_status_of(payload)
    if status is None:
        return False, "응답이 JSON 객체가 아니거나 status 가 없습니다."
    if status == "013":
        return False, "조회된 데이터가 없습니다(status 013) — 그 보고서가 없거나 배당 표가 없음."
    if status != "000":
        return False, f"status {status} ({DART_STATUS_MESSAGES.get(status, '알 수 없는 코드')})"
    rows = payload.get("list")
    if not isinstance(rows, list) or not rows:
        return False, "status 는 000 이지만 list 가 비어 있습니다."
    for row in rows:
        if not isinstance(row, dict):
            continue
        metric, _ = classify_se(row.get("se"))
        if metric in ("dps_cash", "dps_stock", "cash_yield", "stock_yield",
                      "payout_ratio", "cash_total", "stock_total"):
            return True, f"배당 항목 {len(rows)}행 확인"
    return False, ("status 000 이고 list 도 있지만 배당 관련 `se` 항목이 하나도 없습니다 "
                   "— 응답 규격이 바뀌었을 수 있으니 리포트의 unknown_se_labels 를 확인하세요.")


def select_report_from_probes(probes, priority=REPRT_CODE_PRIORITY):
    """
    이미 받아둔 보고서별 응답들 중 **가장 나중 기간을 덮는 사용 가능한 보고서**를 고릅니다.
    (순수 함수 — 네트워크 없이 테스트합니다. 실제 수집 루프는 이 순서대로 하나씩 부르다가
     첫 성공에서 멈추므로 같은 결과를 더 적은 요청으로 얻습니다.)

    probes : {reprt_code: payload dict}
    반환   : (선택된 reprt_code 또는 None, 사유 문자열)
    """
    if not probes:
        return None, "확인한 보고서가 하나도 없습니다."
    tried = []
    for code in priority:
        if code not in probes:
            continue
        ok, why = is_usable_alot_response(probes[code])
        name = REPRT_CODE_NAMES.get(code, code)
        if ok:
            return code, f"{name}({code}) 채택 — {why}"
        tried.append(f"{name}({code}): {why}")
    if not tried:
        return None, f"우선순위 {priority} 중 확인한 보고서가 없습니다(probes 키: {sorted(probes)})."
    return None, "사용 가능한 보고서가 없습니다 — " + " / ".join(tried)


def plausible_reprt_codes(bsns_year, today=None, priority=REPRT_CODE_PRIORITY):
    """
    법정 제출기한이 이미 지난 보고서만 남겨 우선순위를 좁힙니다. (순수 함수)

    ⚠️ **12월 결산법인 전제**입니다. 3월·6월 결산법인은 기준일이 달라 실제로는 존재하는
       보고서를 걸러낼 수 있습니다. 그래서 수집기 기본값은 이 필터를 **끄고**(전부 시도)
       두고, 요청량을 줄여야 할 때만 켜도록 했습니다. 켠 채로 수집했다면 그 사실을
       리포트에 반드시 남깁니다(`skip_not_yet_due` 필드).

    근거: 자본시장법상 분기·반기보고서는 각 기간 종료 후 45일, 사업보고서는 사업연도
          종료 후 90일 이내 제출.
    """
    today = today or date.today()
    year = int(bsns_year)
    kept = []
    for code in priority:
        spec = _REPRT_PERIOD_END.get(code)
        if spec is None:
            kept.append(code)          # 우리가 모르는 코드는 거르지 않습니다(지어내지 않기).
            continue
        month, day, grace_days = spec
        deadline = date(year, month, day) + timedelta(days=grace_days)
        if today >= deadline:
            kept.append(code)
    return tuple(kept)


# =============================================================================
# 6. 배당 표 파싱 — 순수 함수
# =============================================================================
# (지표키, 주식종류) 조합 중 우리가 출력 스키마로 뽑아 쓰는 것들.
# 주식종류가 "none" 인 지표는 종류 구분 없이 하나만 옵니다.
_KIND_SPECIFIC_METRICS = ("dps_cash", "dps_stock", "cash_yield", "stock_yield")

PERIOD_FIELDS = {
    "thstrm": "당기",
    "frmtrm": "전기",
    "lwfr": "전전기",
}


def _pick_single(candidates, label):
    """
    같은 (지표, 주식종류) 자리에 모인 후보값들에서 대표값 하나를 정합니다. (순수 함수)

    반환: (대표값 또는 None, 사유 문자열, 후보 전체 리스트)

    §0-1: 서로 다른 값이 둘 이상이면 **임의로 첫 값을 고르지 않고** None + 사유로 둡니다.
          (우선주가 2종 이상인 회사에서 실제로 발생합니다 — 예: 보통주/1우선주/2우선주B)
          후보 전체는 버리지 않고 그대로 돌려주어, 화면·후속 분석이 쓸 수 있게 합니다.
    """
    values = [v for v in candidates if v is not None]
    if not values:
        return None, "값 없음", []
    distinct = sorted(set(values))
    if len(distinct) == 1:
        note = "단일값" if len(values) == 1 else f"동일값 {len(values)}건"
        return distinct[0], note, values
    return None, (f"{label}: 서로 다른 값이 {len(distinct)}개라 대표값을 하나로 특정하지 "
                  f"않았습니다(후보 {distinct}). 우선주가 여러 종류이거나 원자료가 어긋난 "
                  "경우입니다 — 사람이 확인해야 합니다."), values


def parse_alot_rows(rows, period="thstrm"):
    """
    alotMatter 의 `list` 행들을 지표별로 정리합니다. (순수 함수 · 네트워크 불필요)

    period: "thstrm"(당기·기본) / "frmtrm"(전기) / "lwfr"(전전기)

    반환 dict (스키마 고정):
      dps_cash_common / dps_cash_preferred / dps_stock_common / dps_stock_preferred
      cash_yield_common / cash_yield_preferred / stock_yield_common / stock_yield_preferred
      payout_ratio (+ payout_ratio_basis)
      cash_total_mkrw / stock_total_mkrw / par_value
      eps (+ eps_basis) / net_income_mkrw (+ net_income_basis)
      *_all            후보값 전체(대표값을 못 정한 경우에도 데이터를 잃지 않도록)
      notes            애매했던 지점들의 사람이 읽을 사유 목록
      unknown_se_labels 우리가 분류하지 못한 `se` 라벨(원문)
      unit_mismatch_notes 라벨의 단위 토큰이 기대 단위와 다르거나 확인 불가였던 사유 목록
                       (§2-4). 비어 있지 않다면 그 레코드의 금액·주당값은 필드명이 뜻하는
                       단위가 아닐 수 있습니다 — **우리는 값을 변환하지 않습니다**(§0-1).
      meta             rcept_no / stlm_dt / corp_name / corp_code / corp_cls (충돌 시 사유 기록)
      row_count        입력 행 수
    """
    buckets = {}          # (metric, kind, basis) -> [값…]
    unknown_labels = []
    notes = []
    unit_mismatch_notes = []
    meta_values = {"rcept_no": set(), "stlm_dt": set(), "corp_name": set(),
                   "corp_code": set(), "corp_cls": set()}

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for key in meta_values:
            val = row.get(key)
            if val not in (None, ""):
                meta_values[key].add(str(val).strip())

        metric, basis = classify_se(row.get("se"))
        if metric is None:
            raw_label = row.get("se")
            if raw_label and raw_label not in unknown_labels:
                unknown_labels.append(raw_label)
            continue
        # 단위 검증(§2-4) — 값은 그대로 담되, 통과 못 한 사실을 데이터에 남깁니다.
        # 같은 라벨이 주식종류별로 여러 행 오므로 같은 사유는 한 번만 적습니다.
        unit_note = check_unit_token(metric, row.get("se"))
        if unit_note and unit_note not in unit_mismatch_notes:
            unit_mismatch_notes.append(unit_note)
        kind = classify_stock_kind(row.get("stock_knd"))
        if kind.startswith("other:"):
            notes.append(f"알 수 없는 주식종류 '{row.get('stock_knd')}' (항목: {row.get('se')}) "
                         "— 보통주/우선주 어느 쪽으로도 넣지 않았습니다.")
        buckets.setdefault((metric, kind, basis), []).append(to_number(row.get(period)))

    def take(metric, kind, basis=None, label=None):
        vals = buckets.get((metric, kind, basis), [])
        value, note, all_vals = _pick_single(vals, label or f"{metric}/{kind}")
        if value is None and all_vals:
            notes.append(note)
        return value, all_vals

    result = {"row_count": len(rows or []), "period": period,
              "notes": notes, "unknown_se_labels": unknown_labels,
              "unit_mismatch_notes": unit_mismatch_notes}

    # ── 주식 종류별 지표 ──────────────────────────────────────────────────────
    for metric in _KIND_SPECIFIC_METRICS:
        for kind, suffix in (("common", "common"), ("preferred", "preferred")):
            value, all_vals = take(metric, kind, None, f"{metric}({suffix})")
            result[f"{metric}_{suffix}"] = value
            result[f"{metric}_{suffix}_all"] = all_vals
        # 주식 종류 구분 없이 온 경우("-")도 버리지 않습니다. 우선주가 없는 회사는
        # DART 가 종류 구분 없이 한 줄만 주는 경우가 있을 수 있어, 그때 보통주 자리가
        # 비는 것을 막기 위해 별도 필드로 보존합니다(보통주로 **자동 승격하지 않습니다**).
        value, all_vals = take(metric, "none", None, f"{metric}(종류구분없음)")
        result[f"{metric}_unspecified"] = value
        result[f"{metric}_unspecified_all"] = all_vals

    # ── 배당성향 / 주당순이익 / 당기순이익: 연결 우선, 없으면 별도 ─────────────
    # (JSON 키는 ASCII 로 둡니다 — 한글 키는 후속 SQL/CSV 파이프라인에서 사고가 잦습니다.)
    _BASIS_KEY = {"연결": "consolidated", "별도": "separate", None: "unspecified"}
    for metric, out_key in (("payout_ratio", "payout_ratio"),
                            ("eps", "eps"),
                            ("net_income", "net_income_mkrw")):
        chosen_value, chosen_basis, chosen_all = None, None, []
        for basis in ("연결", "별도", None):
            value, all_vals = take(metric, "none", basis, f"{metric}({basis or '기준미표기'})")
            result[f"{out_key}_{_BASIS_KEY[basis]}"] = value
            if chosen_value is None and value is not None:
                chosen_value, chosen_basis, chosen_all = value, (basis or "기준미표기"), all_vals
        result[out_key] = chosen_value
        result[f"{out_key}_basis"] = chosen_basis
        result[f"{out_key}_all"] = chosen_all

    # ── 종류 구분 없는 단일 지표 ──────────────────────────────────────────────
    for metric, out_key in (("cash_total", "cash_total_mkrw"),
                            ("stock_total", "stock_total_mkrw"),
                            ("par_value", "par_value")):
        value, all_vals = take(metric, "none", None, metric)
        result[out_key] = value
        result[f"{out_key}_all"] = all_vals

    # ── 메타(rcept_no/stlm_dt 등): 한 응답 안에서 값이 갈리면 지어내지 않고 기록 ──
    meta = {}
    for key, values in meta_values.items():
        if not values:
            meta[key] = None
        elif len(values) == 1:
            meta[key] = next(iter(values))
        else:
            meta[key] = None
            notes.append(f"{key} 값이 한 응답 안에서 {sorted(values)} 로 갈려 대표값을 두지 "
                         "않았습니다 — raw 응답을 확인해야 합니다.")
    result["meta"] = meta
    return result


def dart_document_url(rcept_no):
    """rcept_no → DART 공시 원문 URL. 값이 없으면 None(빈 링크를 만들지 않습니다)."""
    if not rcept_no:
        return None
    text = str(rcept_no).strip()
    if not text:
        return None
    return DART_DOCUMENT_URL_TEMPLATE.format(rcept_no=text)


def market_from_corp_cls(corp_cls):
    """
    corp_cls → 사람이 읽는 시장구분. 모르는 값은 지어내지 않고 원문을 그대로 노출합니다.
    ⚠️ 우리가 실제 응답으로 확인한 값은 "Y"(삼성전자) 뿐입니다.
    """
    if not corp_cls:
        return None
    key = str(corp_cls).strip().upper()
    return CORP_CLS_MARKET.get(key, f"알 수 없는 구분({key})")


# =============================================================================
# 7. 출력 레코드 조립 — 순수 함수
# =============================================================================
def build_dividend_record(stock_code, corp_info, bsns_year, reprt_code, payload,
                          parsed_now=None, parsed_prev=None, parsed_prev2=None,
                          collected_at=None, status="OK", status_reason="",
                          kind_baseline_index=None):
    """
    최종 출력 스키마 한 건을 만듭니다. (순수 함수 — 네트워크 결과를 넣기만 하면 됩니다)

    ⚠️ 실패 레코드도 **같은 스키마로** 만듭니다. 성공한 종목만 파일에 넣으면 "2,700개 중
       2,431개만 있는 이유"를 나중에 아무도 설명할 수 없습니다(§0-1).

    kind_baseline_index : `build_kind_baseline_index()` 결과(§0-3-3 교차검증용, 선택).
        None(기본)이면 교차검증을 하지 않고 `cross_source_notes` 는 **항상 `[]`** 입니다
        — 이 인자를 넘기지 않는 기존 호출부의 동작은 한 글자도 달라지지 않습니다.
    """
    parsed_now = parsed_now or {}
    meta = parsed_now.get("meta") or {}
    rcept_no = meta.get("rcept_no")

    prev_dps = (parsed_prev or {}).get("dps_cash_common")
    prev_payout = (parsed_prev or {}).get("payout_ratio")
    prev2_dps = (parsed_prev2 or {}).get("dps_cash_common")
    prev2_payout = (parsed_prev2 or {}).get("payout_ratio")
    cross_source_notes = []
    if kind_baseline_index:
        cross_source_notes = check_cross_source(
            stock_code, bsns_year, prev_dps, prev2_dps, prev_payout, prev2_payout,
            kind_baseline_index)

    record = {
        # ── 식별 ──────────────────────────────────────────────────────────────
        "stock_code": stock_code,
        "corp_code": (corp_info or {}).get("corp_code"),
        "corp_name": meta.get("corp_name") or (corp_info or {}).get("corp_name"),
        "corp_cls": meta.get("corp_cls"),
        "market": market_from_corp_cls(meta.get("corp_cls")),

        # ── 어느 보고서의 값인가 ──────────────────────────────────────────────
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
        "reprt_name": REPRT_CODE_NAMES.get(reprt_code) if reprt_code else None,
        "stlm_dt": meta.get("stlm_dt"),
        "rcept_no": rcept_no,
        "dart_url": dart_document_url(rcept_no),

        # ── 당기(=해당 보고서 기준 회계연도 누적) ─────────────────────────────
        "dps_cash_common": parsed_now.get("dps_cash_common"),
        "dps_cash_preferred": parsed_now.get("dps_cash_preferred"),
        "dps_cash_unspecified": parsed_now.get("dps_cash_unspecified"),
        "dps_cash_common_all": parsed_now.get("dps_cash_common_all"),
        "dps_cash_preferred_all": parsed_now.get("dps_cash_preferred_all"),
        "dps_stock_common": parsed_now.get("dps_stock_common"),
        "dps_stock_preferred": parsed_now.get("dps_stock_preferred"),
        "cash_yield_common": parsed_now.get("cash_yield_common"),
        "cash_yield_preferred": parsed_now.get("cash_yield_preferred"),
        "stock_yield_common": parsed_now.get("stock_yield_common"),
        "stock_yield_preferred": parsed_now.get("stock_yield_preferred"),
        "payout_ratio": parsed_now.get("payout_ratio"),
        "payout_ratio_basis": parsed_now.get("payout_ratio_basis"),
        "cash_total_mkrw": parsed_now.get("cash_total_mkrw"),
        "stock_total_mkrw": parsed_now.get("stock_total_mkrw"),
        "par_value": parsed_now.get("par_value"),
        "eps": parsed_now.get("eps"),
        "eps_basis": parsed_now.get("eps_basis"),
        "net_income_mkrw": parsed_now.get("net_income_mkrw"),
        "net_income_basis": parsed_now.get("net_income_mkrw_basis"),

        # ── 전기·전전기 (교차검증용 — §0-3-3) ────────────────────────────────
        # 같은 응답에 공짜로 실려 오는 값입니다. 이미 보유한 2023~2025 KIND 데이터와
        # 대조해 우리 과거 데이터가 맞는지 검산하는 데 씁니다. 화면에 쓰려면 별도 판단 필요.
        "prev_dps_cash_common": prev_dps,
        "prev_cash_yield_common": (parsed_prev or {}).get("cash_yield_common"),
        "prev_payout_ratio": prev_payout,
        "prev2_dps_cash_common": prev2_dps,
        "prev2_cash_yield_common": (parsed_prev2 or {}).get("cash_yield_common"),
        "prev2_payout_ratio": prev2_payout,
        # 위 전기·전전기 값을 독립 출처(KIND 2023~2025)와 대조한 결과(§0-3-3).
        # 비어 있으면 "불일치 없음 또는 대조할 짝이 없음". **값은 절대 고치지 않습니다**
        # — `unit_mismatch_notes` 와 같은 감지 전용 필드입니다(§0-1).
        # `kind_baseline_index` 를 넘기지 않으면(기본) 항상 [] 입니다.
        "cross_source_notes": cross_source_notes,

        # ── 수집 상태 · 품질 메모 ─────────────────────────────────────────────
        "status": status,                     # "OK" / "NO_DATA" / "ERROR" / "UNMAPPED"
        "status_reason": status_reason,
        "collected_at_kst": (collected_at or _now_kst()).isoformat(),
        "parse_notes": parsed_now.get("notes") or [],
        "unknown_se_labels": parsed_now.get("unknown_se_labels") or [],
        # 비어 있지 않다면 이 레코드의 금액·주당값은 **단위 검증을 통과하지 못한 값**입니다
        # (§2-4). 우리가 변환하지 않았으므로 원문 단위 그대로입니다.
        "unit_mismatch_notes": parsed_now.get("unit_mismatch_notes") or [],
        "yield_reliability_note": (
            "현금배당수익률(%)은 DART 정기보고서 원문값 그대로입니다. 분기·반기보고서에서는 "
            "주당배당금이 누적으로 늘어도 수익률이 갱신되지 않는 사례를 실측 확인했습니다"
            "(삼성전자 2026 1분기 0.20% → 반기 746원인데 여전히 0.20%). 누적 정합을 보장하지 "
            "않으므로, 화면에 수익률을 쓸 거라면 (누적 주당배당금 ÷ 현재가)로 직접 계산하고 "
            "그 사실을 표시하는 편이 안전합니다."
            if reprt_code in ("11012", "11013", "11014") else
            "사업보고서(연간 확정) 기준 원문값입니다."
        ) if reprt_code else None,
        "source": "DART OpenAPI alotMatter.json",
    }
    return record


def summarize_results(records, unmapped, extra=None):
    """
    최종 리포트를 만듭니다. (순수 함수)

    §0-1: '성공 건수'만 세지 않습니다. 데이터 없음/에러/매핑실패를 각각 몇 건인지 반드시
          함께 셉니다. 화면에도 이 숫자가 그대로 올라가야 합니다.
    """
    by_status = {}
    unknown_labels = []
    conflict_records = []
    unit_mismatch_codes = []
    cross_source_codes = []
    unit_mismatch_count = 0
    cross_source_count = 0
    for rec in records or []:
        st = rec.get("status") or "UNKNOWN"
        by_status[st] = by_status.get(st, 0) + 1
        for label in rec.get("unknown_se_labels") or []:
            if label not in unknown_labels:
                unknown_labels.append(label)
        if rec.get("parse_notes"):
            conflict_records.append({"stock_code": rec.get("stock_code"),
                                     "corp_name": rec.get("corp_name"),
                                     "notes": rec.get("parse_notes")})
        # 단위 검증(§2-4)·교차검증(§0-3-3) 결과는 레코드마다 흩어져 있어, 집계해 두지 않으면
        # 전 종목 파일을 일일이 뒤져야만 알 수 있습니다. 건수와 종목코드를 리포트에 올립니다.
        if rec.get("unit_mismatch_notes"):
            unit_mismatch_count += 1
            code = rec.get("stock_code")
            if code not in unit_mismatch_codes:
                unit_mismatch_codes.append(code)
        if rec.get("cross_source_notes"):
            cross_source_count += 1
            code = rec.get("stock_code")
            if code not in cross_source_codes:
                cross_source_codes.append(code)

    ok_records = [r for r in records or [] if r.get("status") == "OK"]
    by_report = {}
    for rec in ok_records:
        name = rec.get("reprt_name") or "(미상)"
        by_report[name] = by_report.get(name, 0) + 1

    with_dps = len([r for r in ok_records if r.get("dps_cash_common") is not None])

    summary = {
        "generated_at_kst": _now_kst().isoformat(),
        "total_records": len(records or []),
        "by_status": by_status,
        "by_report_used": by_report,
        "ok_with_common_dps": with_dps,
        "ok_without_common_dps": len(ok_records) - with_dps,
        "unmapped_stock_codes": len(unmapped or []),
        "unmapped_detail": unmapped or [],
        "unknown_se_labels": unknown_labels,
        "records_with_parse_notes": conflict_records,
        # ── 감지 전용 지표 두 가지 (값을 고친 적은 없습니다) ────────────────────
        # ① 단위 검증(§2-4): 라벨의 단위 토큰이 기대와 달랐던 레코드 수
        "records_with_unit_mismatch": unit_mismatch_count,
        "stock_codes_with_unit_mismatch": unit_mismatch_codes,
        # ② 2개 출처 교차검증(§0-3-3): DART 전기·전전기 값이 KIND 기준선과 달랐던 레코드 수.
        #    ⚠️ `--history-baseline` 을 주지 않은 실행에서는 교차검증 자체를 하지 않았으므로
        #       이 값이 0 이라고 해서 "두 출처가 일치했다"는 뜻이 아닙니다.
        "records_with_cross_source_mismatch": cross_source_count,
        "stock_codes_with_cross_source_mismatch": cross_source_codes,
        # ⚠️ 반드시 읽어야 하는 한계 — 리포트에 늘 붙여 다닙니다.
        "known_limitations": [
            "DART 는 '존재하지 않는 corp_code' 와 '배당 데이터 없음' 을 똑같이 status 013 으로 "
            "돌려줍니다(2026-08-23 실측). 따라서 NO_DATA 안에는 진짜 무배당 종목과 corp_code "
            "매핑이 틀린 종목이 섞여 있을 수 있으며, API 응답만으로는 구분할 수 없습니다.",
            "분기·반기보고서의 현금배당수익률(%)은 누적 정합이 보장되지 않습니다(각 레코드의 "
            "yield_reliability_note 참고).",
            "corp_cls 값은 삼성전자의 'Y' 외에는 실제 응답으로 확인하지 못했습니다.",
        ],
    }
    if extra:
        summary.update(extra)
    return summary


# =============================================================================
# 8. 네트워크 (테스트에서는 _http_get_json 하나만 monkeypatch 합니다)
# =============================================================================
def _http_get_json(url, params, timeout, session):
    """실제 네트워크 호출 지점. 반환: (status_code, parsed_json 또는 None)"""
    if session is None and requests is None:
        raise DartApiError("`requests` 패키지가 없어 DART 를 호출할 수 없습니다.")
    getter = session.get if session is not None else requests.get
    res = getter(url, params=params, timeout=timeout)
    status = getattr(res, "status_code", None)
    try:
        payload = res.json()
    except Exception:
        payload = None
    return status, payload


def fetch_alot_matter(corp_code, bsns_year, reprt_code, api_key, session=None):
    """
    alotMatter 단건 조회. 성공/데이터없음 모두 **응답 dict 를 그대로** 반환합니다.

    · 종목 하나만 실패하는 상황 → DartApiError
    · 실행 전체를 멈춰야 하는 상황(키·IP·요청한도·점검, HTTP 403/429) → DartFatalError
      (§0-3-2: 차단되면 무한 재시도 금지 — 즉시 중단합니다)
    """
    params = {"crtfc_key": api_key, "corp_code": corp_code,
              "bsns_year": str(bsns_year), "reprt_code": reprt_code}

    last_error = None
    for attempt in range(DART_NETWORK_RETRY + 1):
        try:
            status_code, payload = _http_get_json(
                DART_ALOT_MATTER_URL, params, DART_REQUEST_TIMEOUT_SEC, session)
        except (DartApiError, DartFatalError):
            raise
        except Exception as e:
            last_error = f"네트워크 오류: {type(e).__name__}"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartApiError(f"corp_code={corp_code} {reprt_code} 조회 실패 — {last_error}")

        if status_code in (403, 429):
            raise DartFatalError(
                f"DART 가 HTTP {status_code} 로 차단했습니다. 재시도하지 않고 실행 전체를 "
                "중단합니다(§0-3-2). 체크포인트가 저장되므로 시간을 두고 다시 실행하세요.")
        if status_code is not None and 400 <= status_code < 500:
            raise DartApiError(f"HTTP {status_code} — 재시도하지 않습니다(corp_code={corp_code}).")
        if status_code is not None and status_code >= 500:
            last_error = f"서버 오류(HTTP {status_code})"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartApiError(f"corp_code={corp_code} {reprt_code} 조회 실패 — {last_error}")
        if status_code not in (200, None):
            raise DartApiError(f"예상치 못한 HTTP 상태 {status_code} (corp_code={corp_code}).")

        if not isinstance(payload, dict):
            raise DartApiError(f"응답이 JSON 객체가 아닙니다(corp_code={corp_code}).")

        status = dart_status_of(payload)
        if status in DART_FATAL_STATUSES:
            raise DartFatalError(
                f"DART status {status} — {DART_STATUS_MESSAGES.get(status, '알 수 없는 코드')} "
                "재시도하지 않고 실행 전체를 중단합니다(§0-3-2). "
                "체크포인트가 저장되므로 원인을 해결한 뒤 다시 실행하세요.")
        return payload

    raise DartApiError(f"corp_code={corp_code} {reprt_code} 조회 실패 — {last_error}")  # 방어


def polite_sleep(rng=None):
    """§0-3-2 기준 딜레이. collector_kospi200.py 의 random.uniform(2.0, 3.0) 과 동일."""
    delay = (rng or random).uniform(DART_REQUEST_DELAY_MIN, DART_REQUEST_DELAY_MAX)
    time.sleep(delay)
    return delay


# =============================================================================
# 9. 유니버스 입력 / 체크포인트 / 저장
# =============================================================================
def load_universe(path):
    """
    수집 대상 종목코드 목록을 JSON 파일에서 읽습니다.

    ⚠️ 경로를 하드코딩하지 않습니다 — 호출부(CLI 인자 `--universe`)가 정합니다.

    받아들이는 형태(어느 것인지 **추측하지 않고 명시적으로** 판별합니다):
      ① ["005930", "000660", …]
      ② [{"stock_code": "005930", …}, …]   (키 후보: stock_code / 종목코드 / code / ticker)
      ③ {"KOSPI": [...], "KOSDAQ": [...], "KONEX": [...]}   (값이 ①/② 형태)
    어느 것도 아니면 **지어내지 않고 ValueError** 를 던집니다.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    codes = _extract_codes(data, path)
    if not codes:
        raise ValueError(f"유니버스 파일에서 종목코드를 하나도 찾지 못했습니다: {path}")
    # 순서를 유지하며 중복 제거(입력 순서를 바꾸면 체크포인트 재개 시 헷갈립니다)
    seen, ordered = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


_CODE_KEYS = ("stock_code", "종목코드", "code", "ticker", "srtnCd", "isu_srt_cd")


def _extract_codes(data, path):
    if isinstance(data, dict):
        # ③ 시장별 dict — 값이 리스트인 키만 훑습니다.
        collected = []
        for key, value in data.items():
            if isinstance(value, list):
                collected.extend(_extract_codes(value, path))
        if collected:
            return collected
        raise ValueError(f"유니버스 파일이 dict 인데 리스트 값이 없습니다: {path}")
    if not isinstance(data, list):
        raise ValueError(f"유니버스 파일 최상위가 list/dict 가 아닙니다: {path}")

    codes = []
    for item in data:
        if isinstance(item, str):
            codes.append(item)
            continue
        if isinstance(item, dict):
            found = None
            for key in _CODE_KEYS:
                if key in item and item[key] not in (None, ""):
                    found = item[key]
                    break
            if found is None:
                raise ValueError(
                    f"유니버스 항목에서 종목코드 키를 찾지 못했습니다(찾은 키: {sorted(item)}). "
                    f"허용 키: {_CODE_KEYS} — 파일: {path}")
            codes.append(found)
            continue
        raise ValueError(f"유니버스 항목의 형태를 알 수 없습니다: {type(item).__name__} — {path}")
    return codes


DEFAULT_CHECKPOINT_MAX_AGE_DAYS = 14


def build_run_key(bsns_year, universe_size, priority):
    """
    체크포인트 재개 조건을 나타내는 키를 만듭니다. (순수 함수)

    구성: 사업연도 | 유니버스 크기 | 보고서 우선순위

    ⚠️ **실행일(날짜)은 일부러 넣지 않습니다.** 예전에는 `_now_kst()` 날짜가 키에 들어
       있었는데, 이 수집은 5시간까지 걸려서 점심시간·야간 중단·GitHub Actions 타임아웃 등으로
       **다음 날 이어 돌리는 일이 아주 흔합니다**. 그때마다 키가 달라져 체크포인트가 통째로
       버려지고 수천 건을 DART 에 다시 요청했습니다 — §0-3-2(상대 서버에 무리를 주지 않는다)
       정면 위반입니다. 날짜를 뺀 대신, "너무 오래된 체크포인트"는 `load_checkpoint()` 의
       `max_age_days` 신선도 검사로 거릅니다.
    """
    return f"{bsns_year}|{universe_size}|{','.join(priority)}"


def load_checkpoint(path, run_key, max_age_days=DEFAULT_CHECKPOINT_MAX_AGE_DAYS):
    """
    같은 run_key(**사업연도 + 유니버스 크기 + 보고서 우선순위**)이고, 저장 시각이
    `max_age_days` 이내로 충분히 최근일 때만 이어합니다.

    다른 조건의 체크포인트는 절대 재사용하지 않습니다(collector_us_stocks.py 와 같은 원칙 —
    서로 다른 기준의 값이 한 파일에 섞이면 그 자체가 §0-1 위반).

    ⚠️ run_key 에는 **실행 날짜가 들어가지 않습니다**(`build_run_key()` 주석 참고).
       날짜를 빼야 다음 날 이어하기가 되지만, 그것만으로는 "몇 달 전에 잊고 놔둔 체크포인트"가
       조건만 우연히 같으면 되살아날 수 있습니다. 그래서 `save_checkpoint()` 가 적어 두는
       `saved_at_kst` 로 신선도를 함께 봅니다.

    · `saved_at_kst` 가 `max_age_days` 보다 오래됨  → 버리고 새로 시작(사유를 출력).
    · `saved_at_kst` 가 없거나 해석 불가            → **나이를 확인할 수 없으므로** 버립니다.
      (§0-1: 확인할 수 없는 것을 '괜찮다'고 넘겨짚지 않습니다. 이 필드가 없던 시절의 낡은
       파일일 수 있고, 그런 파일이야말로 오래됐을 가능성이 큽니다.)
    · `max_age_days=None` 이면 신선도 검사를 하지 않습니다(검사 없이 이어하겠다는 명시적 선택).
    """
    empty = {"run_key": run_key, "records": [], "done_codes": [], "request_count": 0}
    if not os.path.exists(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("run_key") != run_key:
            print(f"  ℹ️ 체크포인트가 다른 실행조건({data.get('run_key')})이라 새로 시작합니다.")
            return empty

        if max_age_days is not None:
            saved_at = data.get("saved_at_kst")
            age_days = _checkpoint_age_days(saved_at)
            if age_days is None:
                print("  ℹ️ 체크포인트의 저장 시각(saved_at_kst)이 없거나 해석할 수 없어 "
                      f"({saved_at!r}) 얼마나 오래된 것인지 확인할 수 없습니다 — "
                      "실행조건은 같지만 안전하게 버리고 새로 시작합니다.")
                return empty
            if age_days > max_age_days:
                print(f"  ℹ️ 체크포인트가 {age_days:.1f}일 전({saved_at})에 저장돼 기준"
                      f"({max_age_days}일)보다 오래됐습니다 — 실행조건은 같지만 다른 실행의 "
                      "잔재일 수 있어 이어하지 않고 새로 시작합니다.")
                return empty

        return {"run_key": run_key,
                "records": data.get("records") or [],
                "done_codes": data.get("done_codes") or [],
                "request_count": int(data.get("request_count") or 0)}
    except Exception as e:
        print(f"  ⚠️ 체크포인트 로드 실패(새로 시작): {type(e).__name__}: {e}")
        return empty


def _checkpoint_age_days(saved_at):
    """
    `saved_at_kst`(ISO 문자열) → 지금까지 며칠 지났는가(float). 해석 불가면 None.

    (corp_code_mapper 의 캐시 신선도 검사와 같은 방식입니다. tzinfo 가 없는 옛 형식은
     KST 로 간주합니다 — 이 프로젝트의 시각은 전부 KST 로 적히므로 지어내는 게 아닙니다.)
    """
    if not saved_at or not isinstance(saved_at, str):
        return None
    try:
        from datetime import datetime as _dt
        from corp_code_mapper import KST as _KST
        dt = _dt.fromisoformat(saved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_KST)
        return (_now_kst() - dt).total_seconds() / 86400.0
    except Exception:
        return None


def save_checkpoint(path, run_key, records, done_codes, request_count):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"run_key": run_key, "saved_at_kst": _now_kst().isoformat(),
                       "records": records, "done_codes": done_codes,
                       "request_count": request_count}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"  ⚠️ 체크포인트 저장 실패(수집은 계속): {type(e).__name__}: {e}")


def clear_checkpoint(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"  ⚠️ 체크포인트 정리 실패(수집 완료엔 지장 없음): {type(e).__name__}: {e}")


def append_raw(raw_path, entry):
    """
    §0-3-3: **원본 응답을 가공본과 다른 파일에** 그대로 누적합니다(JSON Lines).
    파싱 규칙을 나중에 바꿔도 2,700종목을 다시 긁지 않아도 되게 하는 것이 목적입니다.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(raw_path)) or ".", exist_ok=True)
        with open(raw_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  ⚠️ raw 보관 실패(수집은 계속): {type(e).__name__}: {e}")


# =============================================================================
# 10. 종목 1건 수집 — 네트워크 + 순수 함수 조립
# =============================================================================
def collect_one(stock_code, corp_info, bsns_year, api_key, session=None,
                priority=REPRT_CODE_PRIORITY, raw_path=None, sleep_fn=polite_sleep,
                request_counter=None, kind_baseline_index=None):
    """
    한 종목의 배당 레코드를 만듭니다.

    우선순위대로 보고서를 하나씩 부르다가 **첫 번째 사용 가능한 응답에서 멈춥니다**
    (§0-3-2: 필요 없는 요청을 보내지 않는 것도 매너입니다).

    반환: (record, probe_log)
      probe_log: [{reprt_code, status, usable, why}, …] — 어떤 보고서를 왜 건너뛰었는지 기록
    DartFatalError 는 잡지 않고 위로 올립니다(실행 전체 중단).

    kind_baseline_index : §0-3-3 교차검증용 색인(선택). None(기본)이면 교차검증을 하지 않고
        `cross_source_notes` 는 `[]` 로 남습니다 — 기존 호출부 동작 그대로입니다.
    """
    probe_log = []
    corp_code = (corp_info or {}).get("corp_code")
    for idx, reprt_code in enumerate(priority):
        if idx > 0 and sleep_fn:
            sleep_fn()
        try:
            payload = fetch_alot_matter(corp_code, bsns_year, reprt_code, api_key, session=session)
        except DartFatalError:
            raise
        except DartApiError as e:
            probe_log.append({"reprt_code": reprt_code, "status": None,
                              "usable": False, "why": str(e)})
            if request_counter is not None:
                request_counter["count"] += 1
            # 진짜 에러는 '데이터 없음'과 다릅니다. 다음 보고서로 넘어가지 않고 이 종목을
            # 에러로 확정합니다 — 넘어가면 "에러였는데 무배당으로 보이는" 사고가 납니다.
            record = build_dividend_record(
                stock_code, corp_info, bsns_year, None, None,
                status="ERROR", status_reason=f"{REPRT_CODE_NAMES.get(reprt_code, reprt_code)} "
                                              f"조회 중 오류: {e}")
            return record, probe_log

        if request_counter is not None:
            request_counter["count"] += 1
        status = dart_status_of(payload)
        usable, why = is_usable_alot_response(payload)
        probe_log.append({"reprt_code": reprt_code, "status": status,
                          "usable": usable, "why": why})

        if raw_path:
            append_raw(raw_path, {
                "stock_code": stock_code, "corp_code": corp_code,
                "bsns_year": str(bsns_year), "reprt_code": reprt_code,
                "fetched_at_kst": _now_kst().isoformat(),
                "response": payload,            # ← 손대지 않은 원본
            })

        if not usable:
            continue

        rows = payload.get("list") or []
        parsed_now = parse_alot_rows(rows, period="thstrm")
        parsed_prev = parse_alot_rows(rows, period="frmtrm")
        parsed_prev2 = parse_alot_rows(rows, period="lwfr")
        record = build_dividend_record(
            stock_code, corp_info, bsns_year, reprt_code, payload,
            parsed_now=parsed_now, parsed_prev=parsed_prev, parsed_prev2=parsed_prev2,
            status="OK",
            status_reason=f"{REPRT_CODE_NAMES.get(reprt_code, reprt_code)} 기준 누적치",
            kind_baseline_index=kind_baseline_index)
        record["probe_log"] = probe_log
        return record, probe_log

    # 우선순위 전부 013 등으로 사용 불가 → NO_DATA (조용히 스킵하지 않고 레코드로 남깁니다)
    tried = " / ".join(f"{REPRT_CODE_NAMES.get(p['reprt_code'], p['reprt_code'])}={p['status']}"
                       for p in probe_log)
    record = build_dividend_record(
        stock_code, corp_info, bsns_year, None, None,
        status="NO_DATA",
        status_reason=("해당 사업연도의 정기보고서 배당 표를 찾지 못했습니다 "
                       f"({tried}). ⚠️ DART 는 '무배당/미제출'과 'corp_code 오류'를 모두 "
                       "013 으로 돌려주므로 이 둘은 구분되지 않습니다."))
    record["probe_log"] = probe_log
    return record, probe_log


# =============================================================================
# 11. 전체 수집 실행
# =============================================================================
def run_collection(universe, bsns_year, out_dir, cache_dir=None, api_key=None, session=None,
                   priority=REPRT_CODE_PRIORITY, skip_not_yet_due=False,
                   max_requests=DEFAULT_MAX_REQUESTS, max_runtime_sec=DEFAULT_MAX_RUNTIME_SEC,
                   corpcode_max_age_days=7, force_corpcode_refresh=False,
                   limit=None, log=print, history_baseline_path=None,
                   checkpoint_max_age_days=DEFAULT_CHECKPOINT_MAX_AGE_DAYS):
    """
    전 종목 배당 수집. 산출물:
      {out_dir}/dividend_kr_{year}_latest.json   가공본 + 리포트
      {out_dir}/dividend_kr_{year}_raw.jsonl     원본 응답 (§0-3-3 분리 보관)
      {cache_dir}/dart_corpcode_cache.json       corp_code 매핑 캐시
      {cache_dir}/dividend_kr_{year}_checkpoint.json  이어하기용

    history_baseline_path : KIND 연간 배당 파일(2023~2025) 경로(선택, §0-3-3 교차검증).
        주면 DART 의 전기·전전기 값을 그 파일과 대조해 불일치를 `cross_source_notes` 에
        남깁니다. 주지 않으면(기본) 교차검증을 하지 않고 기존과 완전히 동일하게 동작합니다.
        ⚠️ 경로를 줬는데 읽지 못하면 **조용히 넘어가지 않고 예외를 던집니다** — 교차검증을
           해달라고 명시한 사람에게 "검증 안 된 결과"를 검증된 것처럼 돌려주면 §0-1 위반입니다.

    checkpoint_max_age_days : 체크포인트 신선도 기준(기본 14일). `load_checkpoint()` 참고.

    반환: (records, summary)
    """
    started = time.time()
    cache_dir = cache_dir or out_dir
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    key = get_api_key(api_key)
    if not key:
        raise DartFatalError(
            f"환경변수 {DART_API_KEY_ENV} 가 없습니다. 인증키를 코드에 적지 말고 "
            "GitHub Actions Secret / 로컬 환경변수로 넣으세요.")

    universe = list(universe or [])
    universe_size_input = len(universe)          # 잘라내기 전 원래 크기 (리포트에 그대로 남깁니다)
    if limit:
        universe = universe[:int(limit)]
        log(f"  ⚠️ --limit {limit} 이 지정돼 앞의 {len(universe)}종목만 수집합니다 "
            "(전수 수집이 아닙니다 — 리포트에 그대로 기록됩니다).")

    effective_priority = tuple(priority)
    if skip_not_yet_due:
        narrowed = plausible_reprt_codes(bsns_year, priority=effective_priority)
        log(f"  ℹ️ skip_not_yet_due=True → 제출기한이 지난 보고서만 조회합니다: "
            f"{effective_priority} → {narrowed} "
            "(⚠️ 12월 결산법인 전제 — 3월/6월 결산법인을 놓칠 수 있습니다)")
        effective_priority = narrowed or effective_priority

    # ── ⓪ 교차검증 기준선(§0-3-3, 선택) ──────────────────────────────────────
    kind_baseline_index = None
    if history_baseline_path:
        try:
            with open(history_baseline_path, "r", encoding="utf-8") as f:
                history_payload = json.load(f)
        except Exception as e:
            # 조용히 index=None 으로 계속 가면 "교차검증했는데 불일치 0건" 처럼 보입니다(§0-1).
            raise DartFatalError(
                f"교차검증 기준선 파일을 읽지 못했습니다: {history_baseline_path} "
                f"({type(e).__name__}: {e}). --history-baseline 을 지정한 실행은 교차검증 없이 "
                "진행하지 않습니다 — 경로를 고치거나 옵션을 빼고 다시 실행하세요.")
        kind_baseline_index = build_kind_baseline_index(history_payload)
        if not kind_baseline_index:
            raise DartFatalError(
                f"교차검증 기준선 파일에서 (종목코드, 사업연도) 항목을 하나도 만들지 "
                f"못했습니다: {history_baseline_path}. 파일 형식이 "
                '{"records": [{"stock_code": …, "fiscal_year": …}, …]} 인지 확인하세요.')
        log(f"  ℹ️ §0-3-3 교차검증 기준선 {len(kind_baseline_index):,}건 로드 "
            f"({history_baseline_path}) — DART 의 전기·전전기 값과 대조해 불일치만 "
            "`cross_source_notes` 로 기록합니다(값은 고치지 않습니다).")

    # ── ① corp_code 매핑 ────────────────────────────────────────────────────
    log("① DART 고유번호(corp_code) 매핑표 준비")
    cache_path = os.path.join(cache_dir, "dart_corpcode_cache.json")
    raw_zip_path = os.path.join(cache_dir, "dart_corpcode_raw.zip")
    index, corp_info_meta = get_corp_code_index(
        cache_path, api_key=key, max_age_days=corpcode_max_age_days,
        force_refresh=force_corpcode_refresh, raw_zip_path=raw_zip_path,
        session=session, log=log)
    mapping, unmapped = map_stock_codes(universe, index)
    log(f"  → 유니버스 {len(universe):,}종목 중 {len(mapping):,}종목 매핑 성공, "
        f"{len(unmapped):,}종목 실패(목록은 리포트에 그대로 남깁니다)")

    # ── ② 수집 루프 ─────────────────────────────────────────────────────────
    # ⚠️ run_key 에 실행 날짜를 넣지 않습니다 — 넣으면 다음 날 이어할 때 체크포인트가
    #    통째로 버려져 수천 건을 다시 요청하게 됩니다(§0-3-2). 대신 신선도는
    #    checkpoint_max_age_days 로 봅니다. 자세한 사정은 build_run_key() 주석 참고.
    run_key = build_run_key(bsns_year, len(universe), effective_priority)
    ckpt_path = os.path.join(cache_dir, f"dividend_kr_{bsns_year}_checkpoint.json")
    raw_path = os.path.join(out_dir, f"dividend_kr_{bsns_year}_raw.jsonl")
    ckpt = load_checkpoint(ckpt_path, run_key, max_age_days=checkpoint_max_age_days)
    records = list(ckpt["records"])
    done = set(ckpt["done_codes"])
    counter = {"count": ckpt["request_count"]}
    if done:
        log(f"  ↻ 체크포인트에서 {len(done):,}종목을 이어받았습니다(요청 {counter['count']:,}건 사용됨).")

    # 매핑 실패 종목도 **같은 스키마의 레코드로** 남깁니다(§0-1: 조용히 사라지지 않게).
    for item in unmapped:
        code = item.get("stock_code") or item.get("stock_code_input")
        if code in done:
            continue
        records.append(build_dividend_record(
            code, None, bsns_year, None, None,
            status="UNMAPPED", status_reason=item.get("reason", "corp_code 매핑 실패"),
            kind_baseline_index=kind_baseline_index))
        done.add(code)

    targets = [c for c in (normalize_stock_code(x) for x in universe)
               if c and c in mapping and c not in done]
    log(f"② 배당 수집 시작 — 남은 대상 {len(targets):,}종목 "
        f"(보고서 우선순위 {effective_priority}, 종목당 최대 {len(effective_priority)}요청)")

    stopped_reason = None
    for i, code in enumerate(targets, start=1):
        if counter["count"] >= max_requests:
            stopped_reason = (f"요청 예산({max_requests:,}건)을 모두 썼습니다. "
                              "체크포인트를 저장했으니 다음 실행에서 이어집니다.")
            break
        elapsed = time.time() - started
        if elapsed >= max_runtime_sec:
            stopped_reason = (f"실행 시간 예산({max_runtime_sec/3600:.1f}시간)을 넘겼습니다. "
                              "체크포인트를 저장했으니 다음 실행에서 이어집니다.")
            break

        corp_info = mapping[code]
        try:
            record, _probe = collect_one(
                code, corp_info, bsns_year, key, session=session,
                priority=effective_priority, raw_path=raw_path,
                sleep_fn=polite_sleep, request_counter=counter,
                kind_baseline_index=kind_baseline_index)
        except DartFatalError as e:
            # 실행 전체 중단. 지금까지의 결과는 반드시 저장합니다.
            save_checkpoint(ckpt_path, run_key, records, sorted(done), counter["count"])
            log(f"  🛑 {e}")
            stopped_reason = f"DART 차단/치명적 상태로 중단: {e}"
            break

        records.append(record)
        done.add(code)

        if record["status"] == "OK":
            log(f"  [{i}/{len(targets)}] {code} {record.get('corp_name')} — "
                f"{record.get('reprt_name')} 주당현금배당금(보통주)={record.get('dps_cash_common')}")
        else:
            log(f"  [{i}/{len(targets)}] {code} {corp_info.get('corp_name')} — "
                f"{record['status']}: {record['status_reason'][:80]}")

        if i % CHECKPOINT_EVERY == 0:
            save_checkpoint(ckpt_path, run_key, records, sorted(done), counter["count"])

        polite_sleep()      # 다음 종목으로 넘어가기 전 §0-3-2 딜레이

    # ── ③ 저장 ──────────────────────────────────────────────────────────────
    completed = stopped_reason is None
    summary = summarize_results(records, unmapped, extra={
        "bsns_year": str(bsns_year),
        "universe_size_input": universe_size_input,   # 파일에 있던 종목 수
        "universe_size": len(universe),               # 실제로 돌린 종목 수(--limit 반영)
        "reprt_priority_used": list(effective_priority),
        "skip_not_yet_due": bool(skip_not_yet_due),
        "requests_used": counter["count"],
        "elapsed_sec": round(time.time() - started, 1),
        "completed": completed,
        "stopped_reason": stopped_reason,
        "corpcode_source": corp_info_meta.get("source"),
        "corpcode_stats": corp_info_meta.get("stats"),
        "limit_applied": int(limit) if limit else None,
        # 교차검증을 실제로 했는지 여부를 리포트에 남깁니다 — 안 했는데 불일치 0건인 것과
        # 했는데 0건인 것은 전혀 다른 사실입니다(§0-1).
        "cross_source_baseline_path": history_baseline_path,
        "cross_source_baseline_entries": (len(kind_baseline_index)
                                          if kind_baseline_index else 0),
        "cross_source_checked": bool(kind_baseline_index),
        "checkpoint_max_age_days": checkpoint_max_age_days,
        "verification_status": (
            "⚠️ 이 수집기의 requests 경로는 개발 세션에서 실행 검증되지 않았습니다. "
            "첫 GitHub Actions 실행 로그로 반드시 확인하세요."),
    })

    out_path = os.path.join(out_dir, f"dividend_kr_{bsns_year}_latest.json")
    tmp = f"{out_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)

    if completed:
        # 전수 완료 → 이어하기용 체크포인트는 더 이상 의미가 없으므로 지웁니다.
        # (남겨두면 다음 실행이 '이미 다 했다'고 착각할 수 있습니다.)
        clear_checkpoint(ckpt_path)
    else:
        save_checkpoint(ckpt_path, run_key, records, sorted(done), counter["count"])

    log("─" * 78)
    log(f"③ 완료 여부: {'전수 완료' if completed else '중단(이어하기 가능)'}")
    if stopped_reason:
        log(f"   중단 사유: {stopped_reason}")
    log(f"   레코드 {summary['total_records']:,}건 / 상태별 {summary['by_status']}")
    log(f"   사용 요청 {summary['requests_used']:,}건 / 소요 {summary['elapsed_sec']:,.0f}초")
    log(f"   가공본: {out_path}")
    log(f"   raw   : {raw_path}")
    if summary["unknown_se_labels"]:
        log(f"   ⚠️ 처음 보는 se 라벨: {summary['unknown_se_labels']}")
    if summary["records_with_unit_mismatch"]:
        log(f"   ⚠️ 단위 검증 미통과 레코드: {summary['records_with_unit_mismatch']:,}건 "
            "(값은 원문 그대로 두었습니다 — 각 레코드의 unit_mismatch_notes 참고)")
    if kind_baseline_index:
        log(f"   §0-3-3 교차검증: 기준선 {len(kind_baseline_index):,}건과 대조 → 불일치 "
            f"{summary['records_with_cross_source_mismatch']:,}건 "
            "(값은 고치지 않았습니다 — 각 레코드의 cross_source_notes 참고)")
    else:
        log("   §0-3-3 교차검증: 실행하지 않았습니다(--history-baseline 미지정) — "
            "cross_source_notes 가 비어 있는 것은 '일치'가 아니라 '대조 안 함'입니다.")
    return records, summary


# =============================================================================
# 12. 델타 실행 결과 병합
#
# 배경: 2026 전수 수집은 "2023~2025 중 한 번이라도 배당한 2,734종목" 유니버스로 돌았습니다.
#       그 뒤에 생긴 신규 상장·신규 배당 종목을 나중에 따로 돌리려면(= 델타 수집),
#       같은 out_dir 로 `run_collection()` 을 다시 돌릴 수 없습니다 — 산출물 파일을
#       **통째로 덮어써서** 기존 2,734종목이 조용히 사라지기 때문입니다(§0-1 정면 위반).
#       그래서 델타는 **별도 out_dir** 로 돌리고, 그 결과를 여기서 합칩니다.
#
# 이 함수의 원칙:
#   · 겹치면 합치지 않습니다. 자동으로 한쪽을 고르거나 중복을 눈감지 않고 **크게 실패**합니다.
#   · 리포트를 손으로 더하지 않습니다. 병합 레코드를 `summarize_results()` 에 다시 먹입니다
#     (이 파일에서 리포트 스키마의 유일한 출처는 그 함수 하나입니다).
#   · 원래 두 실행의 리포트를 `merged_from` 에 **원문 그대로** 남깁니다. 두 실행을 하나인 척
#     매끄럽게 뭉개면, 어느 쪽이 중단됐는지·언제 돌았는지가 사라집니다.
#   · 실패하면 **아무것도 쓰지 않습니다**. 검증을 전부 끝낸 뒤에야 첫 바이트를 씁니다.
# =============================================================================
def merge_log_path(out_dir, bsns_year):
    """병합 이력 파일 경로. (delta 를 두 번 합치는 사고를 막는 감사 로그)"""
    return os.path.join(out_dir, f"dividend_kr_{bsns_year}_merge_log.json")


def _read_run_output(out_dir, bsns_year, role):
    """
    한 실행의 산출물({'summary':..., 'records':...})을 읽습니다.

    role : 오류 메시지에 쓸 사람말 이름("기존 전체 결과" / "델타 실행 결과").
    반환 : (path, summary, records)
    """
    path = os.path.join(out_dir, f"dividend_kr_{bsns_year}_latest.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{role} 파일이 없습니다: {path}\n"
            f"  → 병합은 이미 존재하는 두 실행 결과를 합치는 작업입니다. "
            f"{'먼저 전수 수집(run_collection)을 끝내고 다시 시도하세요.' if role.startswith('기존') else '델타 수집을 먼저 끝내고 그 out_dir 을 지정하세요.'}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise ValueError(f"{role} 파일을 읽지 못했습니다: {path} ({type(e).__name__}: {e})")
    if not isinstance(payload, dict) or "records" not in payload or "summary" not in payload:
        raise ValueError(
            f"{role} 파일의 형태가 예상과 다릅니다: {path} "
            "(기대: {'summary': {...}, 'records': [...]})")
    summary = payload.get("summary") or {}
    records = list(payload.get("records") or [])
    return path, summary, records


def _stock_code_set(records):
    """레코드 목록에서 종목코드 집합. (코드가 비어 있는 레코드는 겹침 판정 대상이 아닙니다)"""
    return {r.get("stock_code") for r in records if r.get("stock_code")}


def _format_code_list(codes, cap=20):
    """오류 메시지용. 너무 길면 앞 cap 개만 보여주고 나머지는 건수로 말합니다."""
    codes = sorted(codes)
    if len(codes) <= cap:
        return ", ".join(codes)
    return ", ".join(codes[:cap]) + f" ...외 {len(codes) - cap}건"


def _read_merge_log(path):
    """병합 이력 읽기. 없거나 깨졌으면 빈 이력으로 시작합니다(이력이 없다고 병합을 막진 않습니다)."""
    if not os.path.exists(path):
        return {"merges": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠️ 병합 이력 파일을 읽지 못했습니다({type(e).__name__}: {e}) — "
              f"이력 없이 진행합니다: {path}")
        return {"merges": []}
    if not isinstance(data, dict) or not isinstance(data.get("merges"), list):
        print(f"  ⚠️ 병합 이력 파일의 형태가 예상과 다릅니다 — 이력 없이 진행합니다: {path}")
        return {"merges": []}
    return data


def merge_delta_output(main_out_dir, delta_out_dir, bsns_year, force=False, log=print):
    """
    델타 실행(신규 종목만 돌린 별도 out_dir) 결과를 기존 전체 결과에 합칩니다.

    반환: (merged_records, merged_summary)
    """
    # ── ① 두 실행 결과 읽기 (읽기만 — 아직 아무것도 쓰지 않습니다) ───────────────
    main_path, main_summary, main_records = _read_run_output(
        main_out_dir, bsns_year, "기존 전체 결과")
    delta_path, delta_summary, delta_records = _read_run_output(
        delta_out_dir, bsns_year, "델타 실행 결과")

    main_codes = _stock_code_set(main_records)
    delta_codes = _stock_code_set(delta_records)

    log("─" * 78)
    log(f"① 병합 대상을 읽었습니다")
    log(f"   기존: {main_path} — {len(main_records):,}레코드 / {len(main_codes):,}종목")
    log(f"   델타: {delta_path} — {len(delta_records):,}레코드 / {len(delta_codes):,}종목")

    # ── ② 이미 합친 델타인가? (감사 로그 대조) ────────────────────────────────
    # 경로 문자열이 아니라 **종목코드 집합**으로 봅니다 — 운영 편의상 같은 임시 디렉터리를
    # 델타마다 재사용하는 경우가 있어, 경로만 보면 정당한 새 델타까지 막아 버립니다.
    log_path = merge_log_path(main_out_dir, bsns_year)
    merge_log = _read_merge_log(log_path)
    already = None
    for entry in merge_log["merges"]:
        if not isinstance(entry, dict):
            continue
        if set(entry.get("delta_stock_codes") or []) == delta_codes and delta_codes:
            already = entry
            break
    if already is not None:
        if not force:
            raise ValueError(
                "이미 병합된 델타입니다 — 같은 종목 구성의 델타가 "
                f"{already.get('merged_at_kst')} 에 "
                f"'{already.get('delta_out_dir')}' 에서 병합된 기록이 있습니다.\n"
                f"  이력 파일: {log_path}\n"
                f"  → 정말 다시 합쳐야 한다면 force=True (CLI: --force-merge) 를 주세요. "
                "그 경우에도 레코드가 실제로 겹치면 병합은 여전히 거부됩니다.")
        log(f"  ⚠️⚠️ 강제 재병합(force=True): 같은 종목 구성의 델타가 이미 "
            f"{already.get('merged_at_kst')} 에 병합된 기록이 있는데도 진행합니다. "
            "중복 레코드가 생길 수 있는 작업이며, 이 사실은 병합 이력에 그대로 남습니다.")

    # ── ③ 겹침 검사 — 겹치면 이건 '델타'가 아닙니다 (§0-1: 조용히 넘어가지 않기) ──
    # force 로도 이 검사는 통과할 수 없습니다. 겹침은 "어느 쪽이 맞는지" 우리가 판정할 수
    # 없는 문제라, 자동 해소하면 반드시 한쪽 값을 조용히 버리게 됩니다.
    overlap = main_codes & delta_codes
    if overlap:
        raise ValueError(
            f"델타와 기존 결과의 종목이 {len(overlap):,}건 겹칩니다 — 병합하지 않았습니다.\n"
            f"  겹친 종목코드: {_format_code_list(overlap)}\n"
            "  → 델타 유니버스에 이미 수집된 종목이 섞여 있거나, 이 델타를 이미 합친 "
            "뒤일 수 있습니다. 어느 쪽 값이 맞는지는 자동으로 판정할 수 없으므로 "
            "중복 저장도, 한쪽 임의 폐기도 하지 않습니다. 델타 유니버스를 "
            "'기존에 없는 종목'만 남기고 다시 만들어 수집하세요.")

    # ── ④ 델타 raw.jsonl 을 미리 다 읽어 둡니다 ───────────────────────────────
    # (쓰기는 검증이 전부 끝난 뒤에 몰아서 합니다 — 중간에 실패해 반쪽만 쓰이는 일이 없도록)
    delta_raw_path = os.path.join(delta_out_dir, f"dividend_kr_{bsns_year}_raw.jsonl")
    main_raw_path = os.path.join(main_out_dir, f"dividend_kr_{bsns_year}_raw.jsonl")
    delta_raw_lines = []
    delta_raw_missing = not os.path.exists(delta_raw_path)
    if delta_raw_missing:
        # 실패가 아닙니다: 델타 종목이 전부 UNMAPPED 였다면 요청 자체가 0건이라 raw 가
        # 안 생깁니다. 다만 '없었다'는 사실은 조용히 넘기지 않고 로그에 남깁니다.
        log(f"  ⚠️ 델타 raw 파일이 없습니다: {delta_raw_path} — "
            "원본 응답 없이 가공본만 병합합니다(요청이 0건이었다면 정상입니다).")
    else:
        with open(delta_raw_path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)        # 형태 확인만 — 원문 줄을 그대로 이어붙입니다
                except Exception as e:
                    raise ValueError(
                        f"델타 raw 파일 {lineno}번째 줄이 JSON 이 아닙니다: {delta_raw_path} "
                        f"({type(e).__name__}: {e}). 원본 보관 파일이 깨진 채로 이어붙이지 "
                        "않습니다 — 파일을 확인하고 다시 시도하세요.")
                delta_raw_lines.append(line)

    # ── ⑤ 병합 ────────────────────────────────────────────────────────────────
    merged_records = list(main_records) + list(delta_records)     # 순서: 기존 → 델타
    merged_unmapped = (list(main_summary.get("unmapped_detail") or [])
                       + list(delta_summary.get("unmapped_detail") or []))

    main_completed = bool(main_summary.get("completed"))
    delta_completed = bool(delta_summary.get("completed"))
    both_completed = main_completed and delta_completed
    if both_completed:
        stopped_reason = None
    else:
        parts = []
        if not main_completed:
            parts.append(f"기존 실행 미완료({main_summary.get('stopped_reason') or '사유 미기록'})")
        if not delta_completed:
            parts.append(f"델타 실행 미완료({delta_summary.get('stopped_reason') or '사유 미기록'})")
        stopped_reason = " / ".join(parts)

    # corp_code 캐시 상태는 **나중에 돈 쪽**(델타)이 최신입니다. 없으면 기존 것을 씁니다.
    corpcode_source = delta_summary.get("corpcode_source", main_summary.get("corpcode_source"))
    corpcode_stats = delta_summary.get("corpcode_stats", main_summary.get("corpcode_stats"))

    def _num(a, b):
        """두 리포트의 숫자를 더합니다. 한쪽이라도 숫자가 아니면 더할 수 없다고 말합니다(None)."""
        if isinstance(a, bool) or isinstance(b, bool):
            return None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a + b
        return None

    # ⚠️ universe 크기 합산은 **두 유니버스가 겹치지 않는다**는 전제 위에서만 맞습니다.
    #    그 전제는 위 ③ 겹침 검사가 이미 보장합니다(겹치면 여기까지 오지 못합니다).
    merged_summary = summarize_results(merged_records, merged_unmapped, extra={
        "bsns_year": str(bsns_year),
        "universe_size_input": _num(main_summary.get("universe_size_input"),
                                    delta_summary.get("universe_size_input")),
        "universe_size": _num(main_summary.get("universe_size"),
                              delta_summary.get("universe_size")),
        "requests_used": _num(main_summary.get("requests_used"),
                              delta_summary.get("requests_used")),
        "elapsed_sec": _num(main_summary.get("elapsed_sec"),
                            delta_summary.get("elapsed_sec")),
        "completed": both_completed,
        "stopped_reason": stopped_reason,
        "corpcode_source": corpcode_source,
        "corpcode_stats": corpcode_stats,
        # 원래 두 실행의 리포트를 **원문 그대로** 보관합니다. 병합본 숫자만 남기면
        # "언제 돌았는지 / 어느 쪽이 중단됐는지 / --limit 이 걸렸는지" 가 전부 사라집니다.
        "merged_from": [main_summary, delta_summary],
        "merge_performed_at_kst": _now_kst().isoformat(),
        "verification_status": (
            "⚠️ 이 리포트는 단일 수집 실행의 결과가 아니라 merge_delta_output() 으로 "
            f"합친 **병합 결과**입니다(기존: {main_out_dir} + 델타: {delta_out_dir}). "
            "generated_at_kst 는 병합 시각이며, 각 실행의 원래 리포트는 merged_from 에 "
            "원문 그대로 들어 있습니다."),
    })

    # ── ⑥ 저장 — 여기서부터가 첫 쓰기입니다 ───────────────────────────────────
    out_path = os.path.join(main_out_dir, f"dividend_kr_{bsns_year}_latest.json")
    tmp = f"{out_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"summary": merged_summary, "records": merged_records},
                  f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)

    # ── ⑦ raw.jsonl 이어붙이기 (append-only, 줄 순서 그대로) ─────────────────
    if delta_raw_lines:
        os.makedirs(os.path.dirname(os.path.abspath(main_raw_path)) or ".", exist_ok=True)
        with open(main_raw_path, "a", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in delta_raw_lines))

    # ── ⑧ 병합 이력 남기기 ────────────────────────────────────────────────────
    merge_log["merges"].append({
        "merged_at_kst": _now_kst().isoformat(),
        "delta_out_dir": delta_out_dir,
        "delta_stock_codes": sorted(delta_codes),
        "delta_record_count": len(delta_records),
        "delta_raw_lines_appended": len(delta_raw_lines),
        "forced": bool(already is not None and force),
    })
    log_tmp = f"{log_path}.tmp"
    with open(log_tmp, "w", encoding="utf-8") as f:
        json.dump(merge_log, f, ensure_ascii=False, indent=2)
    os.replace(log_tmp, log_path)

    # ── ⑨ 완료 보고 ───────────────────────────────────────────────────────────
    log("─" * 78)
    log("② 병합 완료")
    log(f"   레코드 {len(main_records):,} + {len(delta_records):,} → "
        f"{merged_summary['total_records']:,}건 / 상태별 {merged_summary['by_status']}")
    log(f"   완료 여부: {'양쪽 모두 전수 완료' if both_completed else '일부 미완료'}")
    if stopped_reason:
        log(f"   미완료 사유: {stopped_reason}")
    log(f"   사용 요청 합계 {merged_summary['requests_used']:,}건"
        if isinstance(merged_summary.get("requests_used"), (int, float))
        else "   사용 요청 합계: 계산 불가(원 리포트에 숫자가 없습니다 — merged_from 참고)")
    log(f"   raw 이어붙인 줄 수: {len(delta_raw_lines):,}")
    log(f"   가공본: {out_path}")
    log(f"   raw   : {main_raw_path}")
    log(f"   이력  : {log_path}")
    log("   ⚠️ 이 파일은 단일 실행 결과가 아니라 병합 결과입니다 "
        "(원래 두 실행의 리포트는 summary.merged_from 에 그대로 있습니다).")
    return merged_records, merged_summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="DART alotMatter 기반 한국 상장사 배당 수집기 (visible_hand 배당금 모듈)")
    # ⚠️ required=True 가 아닙니다 — --merge-delta 모드에서는 유니버스가 필요 없습니다.
    #    수집 모드에서 빠졌는지는 파싱 뒤에 직접 확인해 parser.error() 로 알려 줍니다.
    parser.add_argument("--universe", default=None,
                        help="종목코드 목록 JSON 경로(리스트/딕셔너리 형태 모두 허용). "
                             "--merge-delta 를 쓸 때는 필요 없습니다.")
    parser.add_argument("--year", required=True, help="사업연도 4자리 (예: 2026)")
    parser.add_argument("--out-dir", required=True, help="산출물 디렉터리")
    parser.add_argument("--cache-dir", default=None,
                        help="캐시·체크포인트 디렉터리(기본: --out-dir 과 동일)")
    parser.add_argument("--owner-order", action="store_true",
                        help="사업보고서를 빼고 오너 지시 순서(3분기→반기→1분기)만 사용")
    parser.add_argument("--skip-not-yet-due", action="store_true",
                        help="법정 제출기한이 안 지난 보고서는 조회하지 않음 "
                             "(⚠️ 12월 결산법인 전제 — 비12월 결산법인을 놓칠 수 있음)")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--max-runtime-sec", type=int, default=DEFAULT_MAX_RUNTIME_SEC)
    parser.add_argument("--force-corpcode-refresh", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="앞의 N종목만 수집(시범 실행용). 전수 수집이 아님이 리포트에 기록됩니다.")
    parser.add_argument("--history-baseline", default=None,
                        help="§0-3-3 교차검증용 KIND 연간 배당 파일 경로"
                             "(예: data/dividend_history_kr_2023_2025.json). 지정하면 DART 의 "
                             "전기·전전기 값과 대조해 불일치를 cross_source_notes 에 기록합니다"
                             "(감지만 하고 값은 고치지 않습니다). 미지정이 기본입니다.")
    parser.add_argument("--checkpoint-max-age-days", type=int,
                        default=DEFAULT_CHECKPOINT_MAX_AGE_DAYS,
                        help=f"이 일수보다 오래된 체크포인트는 이어받지 않습니다"
                             f"(기본 {DEFAULT_CHECKPOINT_MAX_AGE_DAYS}일). 실행이 며칠에 걸쳐 "
                             "중단·재개돼도 이어지도록 run_key 에는 날짜를 넣지 않습니다.")
    parser.add_argument("--merge-delta", default=None, metavar="DELTA_OUT_DIR",
                        help="[병합 모드] 델타 수집(신규 종목만 별도 out_dir 로 돌린 실행)의 "
                             "산출물 디렉터리. 지정하면 수집을 하지 않고 그 결과를 "
                             "--out-dir 의 기존 전체 결과에 합칩니다. 두 실행의 종목이 "
                             "하나라도 겹치면 병합을 거부합니다.")
    parser.add_argument("--force-merge", action="store_true",
                        help="[병합 모드 전용] 이미 병합한 적 있는 델타여도 강제로 다시 "
                             "병합합니다(병합 이력에 forced 로 남습니다). 종목이 실제로 "
                             "겹치는 경우는 이 옵션으로도 통과하지 못합니다.")
    args = parser.parse_args(argv)

    # ── 병합 모드: 수집 경로로 절대 흘러들지 않는 별개의 모드입니다 ──────────────
    if args.merge_delta:
        try:
            merge_delta_output(args.out_dir, args.merge_delta, args.year,
                               force=args.force_merge)
        except (FileNotFoundError, ValueError) as e:
            # §0-3-4: 스택트레이스 대신 사람이 읽을 문장으로 끝내되, 조용히 성공하지 않습니다.
            print(f"🛑 병합하지 않았습니다 — {e}")
            return 2
        return 0

    if args.force_merge:
        parser.error("--force-merge 는 --merge-delta 와 함께 쓸 때만 의미가 있습니다.")
    if not args.universe:
        parser.error("--universe 가 필요합니다 (수집 모드). "
                     "델타 병합만 하려면 --merge-delta DELTA_OUT_DIR 을 쓰세요.")

    universe = load_universe(args.universe)
    priority = REPRT_CODE_PRIORITY_OWNER_ORDER if args.owner_order else REPRT_CODE_PRIORITY
    try:
        run_collection(
            universe, args.year, args.out_dir, cache_dir=args.cache_dir,
            priority=priority, skip_not_yet_due=args.skip_not_yet_due,
            max_requests=args.max_requests, max_runtime_sec=args.max_runtime_sec,
            force_corpcode_refresh=args.force_corpcode_refresh, limit=args.limit,
            history_baseline_path=args.history_baseline,
            checkpoint_max_age_days=args.checkpoint_max_age_days)
    except (DartFatalError, DartCorpCodeError) as e:
        # §0-3-4: 스택트레이스를 그대로 뿌리지 않고 사람이 읽을 문장으로 끝냅니다.
        # (⚠️ 그래도 '조용히 성공'하지는 않습니다 — 종료코드 2 로 Actions 를 빨간불로 만듭니다.)
        print(f"🛑 수집을 중단했습니다 — {e}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
