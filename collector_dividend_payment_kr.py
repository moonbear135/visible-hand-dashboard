"""
collector_dividend_payment_kr.py
🇰🇷 한국 상장사 **배당금 지급일정 수집기** — DART 수시공시 "현금ㆍ현물배당결정" 원문 기반.

================================================================================
📌 이 파일이 왜 따로 있는가 — 기존 `collector_dividend_kr.py` 와 무엇이 다른가
================================================================================
기존 배당 수집기(`collector_dividend_kr.py`)는 DART `alotMatter.json`("배당에 관한 사항")
을 읽습니다. 그건 **정기보고서(사업/반기/분기보고서) 안에 회사가 적어 놓은 배당 확정치**
이고, 거기에는 **배당기준일도 지급일도 들어 있지 않습니다**(정기보고서의 `stlm_dt` 는
결산기준일일 뿐, 돈이 실제로 들어오는 날이 아닙니다 — 화면에도 그렇게 고지돼 있습니다).

이 파일이 읽는 것은 **완전히 다른 공시**입니다:

  · 공시 종류: 수시공시 `pblntf_ty="I"`(거래소공시)
  · report_nm 예: "현금ㆍ현물배당결정", "부동산투자회사금전배당결정"
  · 여기에는 **"6. 배당기준일", "7. 배당금지급 예정일자"** 가 실제로 들어 있습니다
    (2026-08-20 롯데케미칼 rcept_no=20260820800655 실측 — 기준일 2026-09-03,
     지급예정일 2026-09-18).

그래서 이 수집기는 기존 배당 데이터와 **한 파일도 공유하지 않습니다.** 산출물 이름부터
전부 다릅니다(아래 "산출물" 참고). 두 데이터가 섞이면 "확정 배당금(정기보고서)"과
"이벤트로 발생한 배당결정(수시공시)"이 한 통에 담겨 무엇이 어디서 온 값인지 알 수 없게
됩니다 — 오너 지시(2026-08-24): "유지보수, 데이터가 섞이지 않게".

================================================================================
📌 데이터의 성격 — 이건 "현재 상태"가 아니라 "발생한 이벤트의 로그"입니다
================================================================================
기존 `dividend_kr_2026_latest.json` 은 "지금 이 종목의 최신 배당 확정치"라는 **상태**라서,
새 값이 오면 기존 값을 교체(`apply_watch_update`)하거나 병합을 거부(`merge_delta_output`)
합니다. 이 파일이 만드는 데이터는 성격이 다릅니다 — **배당결정이라는 사건이 언제 어떤
내용으로 공시됐는가**의 기록이므로 저장 정책이 세 번째로 다릅니다:

    ✅ append-only — 새 `rcept_no` 는 무조건 추가, 이미 있는 `rcept_no` 는 건너뜁니다.
       (레코드를 고치거나 지우지 않습니다. `rcept_no` 가 이벤트의 유일 식별자입니다.)

  · `[기재정정]` 공시는 원본과 `rcept_no` 가 다르므로 **별개 레코드로 그냥 추가**됩니다.
    "같은 회사의 최신 정정본만 화면에 보여줄지"는 화면 쪽 판단이고 이 수집기 범위 밖입니다
    (수집기가 임의로 원본을 지우면 정정 전/후를 대조할 방법이 사라집니다).

================================================================================
📌 report_nm 판정 규칙 — 실측 표본 6종에서만 도출했습니다 (§0-1)
================================================================================
list.json(`pblntf_ty="I"`) 3일치 표본에서 "배당"이 들어간 report_nm 은 아래 6종이었습니다
(원문 그대로):

    [기재정정]현금ㆍ현물배당결정              (분기배당)
    부동산투자회사금전배당결정
    현금ㆍ현물배당결정
    현금ㆍ현물배당결정(자회사의 주요경영사항)
    현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정
    현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정(자회사의 주요경영사항)

  ⚠️ "현금ㆍ현물" 의 가운데점은 일반 middle dot(·, U+00B7)이 **아니라** "ㆍ"(U+318D,
     HANGUL LETTER ARAEA)입니다. 아래 `CASH_PROPERTY_DIVIDEND_PREFIX` 상수는 실측 로그
     원문을 그대로 복사한 것입니다 — 비슷하게 생긴 다른 문자로 바꾸면 매칭이 전부 깨집니다.

판정 순서(자세한 내용은 `classify_report_nm()` 도크스트링):
  ① `[기재정정]` 접두어 → `is_correction=True` 로 기록하고 떼어낸 나머지로 판정
  ② "주주명부폐쇄" 포함 → **배당결정이 아님**(기준일 확정 전 단계). 이벤트로 만들지 않되
     몇 건 건너뛰었는지 반드시 로그에 남깁니다(조용히 사라지게 두지 않기).
  ③ 위 두 접두어 중 하나로 **시작** → 배당결정 이벤트. 뒤에 붙는 괄호 부가정보
     ("(분기배당)", "(자회사의 주요경영사항)")는 버리지 않고 `report_nm_extra` 에 원문 보존.
  ④ 그래도 "배당"이 들어 있으면 → `UNRECOGNIZED_REPORT_TYPE`. **추측해서 규칙을 넓히지
     않습니다.** 대신 표본을 리포트(summary)에 남겨 사람이 보고 규칙을 넓힐 수 있게 합니다.

  ⚠️ "(자회사의 주요경영사항)" 이 붙은 건은 `is_subsidiary_notice=True` 로만 표시합니다.
     이 경우 공시 주체(corp_name/stock_code)와 실제 배당하는 회사가 다를 수 있는데,
     **어느 자회사인지 자동으로 추론하지 않습니다**(§0-1 — 확신 없는 추론 금지).

================================================================================
📌 원문 문서(document.xml) 취득 — 2026-08-20 실측으로 확인된 사실만 반영
================================================================================
  · HTTP 200, Content-Type='application/x-msdownload;charset=UTF-8'
  · 바디는 **zip**(시그니처 `PK`). 안에는 파일이 1개: `{rcept_no}.xml`
    → 실측은 1개였지만 여러 개일 가능성을 방어적으로 처리합니다. 1개가 아니면 로그에 남기고
      **어떤 파일을 골랐는지 명시**합니다(조용히 첫 번째를 쓰지 않습니다).
  · 파일 안 `<meta ... charset=euc-kr>` 은 euc-kr 이라고 주장하지만 **실제 바이트는 utf-8 로
    디코딩됐습니다.** 그래서 meta 태그를 믿지 않고 utf-8 → euc-kr → cp949 순으로 시도하고,
    utf-8 이 아니었으면 그 사실을 로그에 남깁니다.
  · zip 이 아닌 응답(rcept_no 오류 등)에 대비해 `body[:2] == b"PK"` 를 **먼저** 확인하고,
    아니면 파싱을 시도하지 않고 실패로 명확히 기록합니다.

================================================================================
📌 원문 표 파싱 — 위치가 아니라 라벨(키워드)로 찾습니다 (§0-1)
================================================================================
표준 라이브러리 `html.parser` 로 **태그 구조를 실제로 파싱**합니다(정규식으로 HTML 전체를
훑지 않습니다 — 공백/속성 하나에 깨집니다).

  · 선택 근거: 이 저장소에는 `requirements.txt` 가 없고(업로드본 기준) 코드 어디에도
    BeautifulSoup 을 쓰는 곳이 없습니다. 확인되지 않은 의존성을 새로 끌어들이는 대신
    **어느 실행 환경에나 반드시 있는 표준 라이브러리**를 씁니다(§0-1 — 있는지 모르는 것을
    있다고 가정하지 않기).
  · "3. 1주당 배당금(원)" 과 "4. 시가배당률(%)" 은 라벨 셀이 `rowspan="2"` 로 두 줄에 걸쳐
    있고 옆에 "보통주식"/"종류주식" 서브 라벨이 옵니다. 그래서 단순히 "라벨 다음 셀"을 읽는
    방식으로는 두 값 중 하나를 놓칩니다 — `_logical_rows()` 가 rowspan/colspan 을 실제 격자로
    펼쳐서, 각 행이 자기에게 걸쳐 있는 라벨 셀을 그대로 갖도록 만듭니다.
  · 라벨을 못 찾으면 그 필드는 `None` 이고 `missing_labels` 에 라벨명이 남습니다.
    **빈 문자열이나 0 으로 채우지 않습니다**(§0-1).
      - 라벨을 다 찾음                             → `parse_status="OK"`
      - 일부 라벨을 못 찾음/값을 해석 못 함        → `"PARTIAL"`
      - 핵심 라벨(배당기준일·배당금지급 예정일자) 둘 다 못 찾음 → `"FAILED"`

================================================================================
📌 산출물 (기존 배당 파일과 이름이 하나도 겹치지 않습니다)
================================================================================
  · `{out_dir}/dividend_kr_{YEAR}_payment_events.json`      가공본 {"summary", "records"}
  · `{out_dir}/dividend_kr_{YEAR}_payment_events_raw.jsonl` 원문 HTML 보관 (§0-3-3)
  · `{cache_dir}/dividend_kr_{YEAR}_payment_state.json`     어디까지 확인했는지(감시 상태)

  ⚠️ `{YEAR}` 는 **파일 이름을 가르는 용도**일 뿐, 조회 조건이 아닙니다. 이 수집기는
     "접수일 구간"으로만 조회합니다(사업연도로 거르는 파라미터가 list.json 에 없습니다).
     따라서 2026 파일 안에 결산연도가 다른 회사의 결정이 들어올 수 있습니다 — 그건 오류가
     아니라 "2026년에 접수된 배당결정 공시들"이라는 이 파일의 정의 그대로입니다.

================================================================================
📌 §0-3-2 (외부 서버 예의)
================================================================================
  · 요청 사이에 2~3초 랜덤 딜레이(기존 수집기와 같은 기준).
  · 이미 받아 둔 `rcept_no` 는 **다시 받지 않습니다** — 같은 공시를 매일 재조회하지 않습니다.
  · HTTP 403/429·DART 치명 status 는 재시도하지 않고 즉시 중단합니다.
  · 실패한 실행은 상태 파일을 갱신하지 않으므로 다음 실행이 그 구간을 다시 확인합니다
    (성공한 날까지만 상태를 전진시킵니다 — `run_watch_payment_events()` 참고).

================================================================================
📌 실행 모드는 둘 — 매일 감시(기본) / 일회성 백필
================================================================================
  · **감시**(`run_watch_payment_events`, CLI 기본): 상태 파일을 보고 "지난번에 끝낸 날 +1
    ~ 어제"만 훑습니다. 한 번 지나간 날짜는 다시 훑지 않습니다.
  · **백필**(`run_backfill_payment_events`, CLI `--bgn-de`/`--end-de` 둘 다 지정):
    사람이 지정한 구간을 상태 파일과 무관하게 한 번 훑습니다. 첫 실행의 lookback 창보다
    앞서 접수돼 감시가 영영 못 보는 공시를 메우는 용도입니다(실제 사례: 2026-08-20 접수
    롯데케미칼 rcept_no=20260820800655).
    🔴 백필은 상태 파일의 `last_checked_de` 를 **절대 뒤로 되돌리지 않습니다** —
       `max(기존 값, 이번 백필이 실제로 확인을 끝낸 날)` 로만 갱신합니다. 되돌리면 다음
       정기 실행이 이미 확인한 구간을 DART 에 다시 요청하게 됩니다(§0-3-2 위반).
    두 모드는 조회·중복방지·저장 본체(`_collect_payment_events_in_range`)를 **공유**합니다.

================================================================================
📌 아직 검증하지 못한 것 (첫 GitHub Actions 실행에서 확인해야 합니다)
================================================================================
  · 이 개발 샌드박스는 프록시 allowlist 때문에 opendart 에 직접 붙지 못합니다. 아래
    `requests` 경로는 **한 번도 실행된 적이 없습니다.** (파싱·판정 로직은 실측 원문
    픽스처로 오프라인 검증돼 있습니다 — tests/test_dividend_payment_collector.py)
  · "부동산투자회사금전배당결정"(리츠) 원문의 **표 라벨**은 아직 못 봤습니다. 라벨이 다르면
    그 레코드는 `PARTIAL`/`FAILED` 로 남고 `missing_labels` 에 무엇을 못 찾았는지 적힙니다
    — 지어내지 않고 사람이 보고 판단할 수 있게 남기는 것이 여기서의 정답입니다.
"""
import argparse
import io
import json
import os
import random
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta
from html.parser import HTMLParser

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# 같은 폴더의 모듈. GitHub Actions 에서 `python -m` 없이 직접 실행돼도 import 되도록
# 스크립트 자신의 디렉터리를 sys.path 에 넣습니다(collector_dividend_kr.py 와 같은 관례).
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from corp_code_mapper import (  # noqa: E402
    DART_API_KEY_ENV,
    DART_FATAL_STATUSES,
    DART_STATUS_MESSAGES,
    _now_kst,
    get_api_key,
)

# 기존 컴포넌트 재사용(§0-3-10) — **읽기만 합니다. 저 파일은 한 줄도 고치지 않습니다.**
#   · normalize_stock_code : 이미 검증된 종목코드 정규화(6자 영숫자 코드 포함)
#   · dart_document_url    : 사용자가 원문 대조할 수 있는 DART 링크 생성
from collector_dividend_kr import (  # noqa: E402
    dart_document_url,
    normalize_stock_code,
)


# =============================================================================
# 1. 엔드포인트·상수
# =============================================================================
DART_DISCLOSURE_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

# 거래소공시(수시공시). 배당결정 공시가 여기로 옵니다 — 정기공시("A")가 아닙니다.
EXCHANGE_PBLNTF_TY = "I"

# list.json 의 page_count 최대값(문서·실측 모두 100).
DART_LIST_PAGE_COUNT = 100
# 방어적 상한. total_page 가 이 수를 넘으면 무한 루프를 의심하고 크게 실패합니다.
DART_LIST_MAX_PAGES = 1000

# 크롤링 매너 상수 (§0-3-2) — collector_dividend_kr.py 와 같은 기준입니다.
# (같은 값을 여기서 다시 정의하는 이유: 이 수집기가 그쪽 모듈의 상수를 바꾸거나 그쪽
#  동작에 영향을 주지 않도록 완전히 독립적으로 두기 위함입니다. 값이 같은 것은 "같은 서버,
#  같은 예의"라는 근거가 같기 때문입니다.)
DART_REQUEST_TIMEOUT_SEC = 20
DART_REQUEST_DELAY_MIN = 2.0
DART_REQUEST_DELAY_MAX = 3.0
DART_NETWORK_RETRY = 1
DART_RETRY_DELAY_SEC = 5.0

# 문서 본문은 zip 이라 JSON 응답보다 큽니다. 그래도 한 건이 수십 MB 일 이유가 없으므로
# 방어적 상한을 둡니다(응답이 이상하면 메모리를 통째로 먹지 않고 실패합니다).
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

# summary 에 남기는 "미인식 report_nm" 표본의 최대 개수. 무한정 쌓아 파일을 부풀리지
# 않되, 사람이 규칙을 넓힐 판단을 하기에는 충분한 수입니다.
MAX_UNRECOGNIZED_SAMPLES = 50


# ── report_nm 판정용 문자열 (실측 로그 원문 그대로) ────────────────────────────
# ⚠️ 아래 "ㆍ" 는 U+318D(HANGUL LETTER ARAEA)입니다. U+00B7(·)이 아닙니다.
CASH_PROPERTY_DIVIDEND_PREFIX = "현금ㆍ현물배당결정"
REIT_CASH_DIVIDEND_PREFIX = "부동산투자회사금전배당결정"
DIVIDEND_DECISION_PREFIXES = (CASH_PROPERTY_DIVIDEND_PREFIX, REIT_CASH_DIVIDEND_PREFIX)

CORRECTION_PREFIX = "[기재정정]"
SHAREHOLDER_REGISTER_CLOSE_TOKEN = "주주명부폐쇄"
SUBSIDIARY_NOTICE_TOKEN = "(자회사의 주요경영사항)"
DIVIDEND_KEYWORD = "배당"

# classify_report_nm() 이 돌려주는 분류값
KIND_DIVIDEND_DECISION = "DIVIDEND_DECISION"
KIND_SHAREHOLDER_REGISTER_CLOSE = "SHAREHOLDER_REGISTER_CLOSE"
KIND_UNRECOGNIZED = "UNRECOGNIZED_REPORT_TYPE"
KIND_NOT_DIVIDEND = "NOT_DIVIDEND"

# parse_status 값
PARSE_OK = "OK"
PARSE_PARTIAL = "PARTIAL"
PARSE_FAILED = "FAILED"


class DartPaymentApiError(RuntimeError):
    """이 건 하나만 실패한 상황. 실행 전체를 멈출 이유는 없습니다."""


class DartPaymentFatalError(RuntimeError):
    """실행 전체를 멈춰야 하는 상황(키·IP·요청한도·점검, HTTP 403/429)."""


# =============================================================================
# 2. report_nm 판정 (순수 함수)
# =============================================================================
def classify_report_nm(report_nm):
    """
    공시 제목(report_nm)이 "배당결정"인지 판정합니다. **네트워크를 타지 않는 순수 함수.**

    반환 dict:
      {
        "kind": DIVIDEND_DECISION | SHAREHOLDER_REGISTER_CLOSE | UNRECOGNIZED_REPORT_TYPE
                | NOT_DIVIDEND,
        "is_correction": bool,          # [기재정정] 로 시작했는가
        "is_subsidiary_notice": bool,   # (자회사의 주요경영사항) 부수 공시인가
        "matched_prefix": str|None,     # 어떤 규칙으로 인식했는지(추적용)
        "report_nm_extra": str|None,    # 접두어 뒤에 남은 괄호 부가정보(원문 그대로)
        "normalized": str,              # [기재정정] 을 뗀 뒤 트림한 본문
      }

    ⚠️ 이 규칙은 **실측 표본 6종에서만** 도출했습니다. 표본 밖의 표기를 "아마 이것도
       배당결정일 것"이라고 넓히지 않습니다 — 그런 건 전부 UNRECOGNIZED_REPORT_TYPE 이고,
       호출부가 그 사실을 세어 로그·리포트에 남깁니다(§0-1).
    """
    text = "" if report_nm is None else str(report_nm)
    # 실측 표본에 앞뒤/중간 공백이 섞여 있었습니다(예: "...결정              (분기배당)").
    body = text.strip()

    is_correction = body.startswith(CORRECTION_PREFIX)
    if is_correction:
        body = body[len(CORRECTION_PREFIX):].strip()

    is_subsidiary_notice = SUBSIDIARY_NOTICE_TOKEN in body

    result = {
        "kind": KIND_NOT_DIVIDEND,
        "is_correction": is_correction,
        "is_subsidiary_notice": is_subsidiary_notice,
        "matched_prefix": None,
        "report_nm_extra": None,
        "normalized": body,
    }

    if DIVIDEND_KEYWORD not in body:
        # 거래소공시 대부분은 배당과 무관합니다(유상증자·자기주식 등). 조용히 넘깁니다 —
        # 이건 "모르는 것"이 아니라 "우리 대상이 아닌 것"이라 세어 둘 필요가 없습니다.
        return result

    if SHAREHOLDER_REGISTER_CLOSE_TOKEN in body:
        # "현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정" — 배당 자체를 결정한 공시가
        # 아니라 기준일을 정하기 위한 주주명부 폐쇄 공시입니다. 배당금·지급일이 없습니다.
        result["kind"] = KIND_SHAREHOLDER_REGISTER_CLOSE
        return result

    for prefix in DIVIDEND_DECISION_PREFIXES:
        if body.startswith(prefix):
            extra = body[len(prefix):].strip()
            result["kind"] = KIND_DIVIDEND_DECISION
            result["matched_prefix"] = prefix
            result["report_nm_extra"] = extra or None
            return result

    result["kind"] = KIND_UNRECOGNIZED
    return result


# =============================================================================
# 3. 원문 HTML 파싱 (순수 함수)
# =============================================================================
# 라벨은 "위치"가 아니라 "키워드"로 찾습니다(§0-1). 아래는
#   (필드 접두어, 정규화된 라벨 키, 사람이 읽는 라벨명)
# 이고, 정규화 키는 `_normalize_label()` 을 통과한 형태입니다("6. 배당기준일" → "배당기준일").
LABEL_SPECS = (
    ("dividend_class",        "배당구분",                   "1. 배당구분"),
    ("dividend_type",         "배당종류",                   "2. 배당종류"),
    ("dps",                   "1주당배당금(원)",            "3. 1주당 배당금(원)"),
    ("dividend_yield",        "시가배당률(%)",              "4. 시가배당률(%)"),
    ("total_amount",          "배당금총액(원)",             "5. 배당금총액(원)"),
    ("record_date",           "배당기준일",                 "6. 배당기준일"),
    ("pay_date_expected",     "배당금지급예정일자",         "7. 배당금지급 예정일자"),
    ("board_resolution_date", "이사회결의일(결정일)",       "10. 이사회결의일(결정일)"),
    ("notes",                 "기타투자판단과관련한중요사항", "11. 기타 투자판단과 관련한 중요사항"),
)

# 주식 종류 서브 라벨(rowspan 라벨 옆에 오는 것). 정기보고서 파서의
# dps_cash_common / dps_cash_preferred 관례를 그대로 따라 common/preferred 로 씁니다.
STOCK_KIND_SUBLABELS = {"보통주식": "common", "종류주식": "preferred"}

# 이 둘을 모두 못 찾으면 이 문서는 우리 목적(지급일정)상 쓸모가 없습니다 → FAILED
CORE_FIELDS = ("record_date", "pay_date_expected")

# 값이 "없음"을 뜻하는 표기(실측: 종류주식이 없는 회사는 "-").
_DASH_VALUES = ("-", "–", "—", "")

_LEADING_ORDINAL_RE = re.compile(r"^\s*(?:[-–—※]\s*)?(?:\d{1,2}\s*[.)]\s*)?")
_WHITESPACE_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# rowspan/colspan 방어 상한. 이상한 값이 오면 격자를 통째로 부풀리지 않고 잘라냅니다.
_MAX_SPAN = 100


def _normalize_label(text):
    """
    라벨 비교용 정규화: 앞의 번호("6.", "-", "※")를 떼고 모든 공백을 제거합니다.

    예) "  6. 배당기준일 "        → "배당기준일"
        "7. 배당금지급 예정일자"  → "배당금지급예정일자"
        "- 차등배당 여부"         → "차등배당여부"
    ⚠️ 값 자체를 정규화할 때 쓰면 안 됩니다(공백이 사라집니다). 라벨 비교 전용입니다.
    """
    if text is None:
        return ""
    cleaned = str(text).replace(" ", " ").strip()
    cleaned = _LEADING_ORDINAL_RE.sub("", cleaned, count=1)
    return _WHITESPACE_RE.sub("", cleaned)


def _clean_cell_text(text):
    """
    셀 텍스트 정리: NBSP → 공백, 각 줄 앞뒤 공백 제거, 줄바꿈(<br>)은 보존.

    `<br>` 은 파서가 이미 "\\n" 으로 바꿔 둡니다. 여기서는 그 줄바꿈을 유지한 채
    줄 단위로만 다듬습니다(11번 항목의 여러 문단을 한 줄로 뭉개지 않기 위함).
    """
    if not text:
        return ""
    normalized = str(text).replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _span_value(raw):
    """rowspan/colspan 속성을 1 이상의 정수로. 해석 못 하면 1(넘겨짚지 않는 최소값)."""
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    if number < 1:
        return 1
    return min(number, _MAX_SPAN)


class _TableCellParser(HTMLParser):
    """
    표(`<tr>`/`<td>`)만 뽑아내는 최소 파서.

    · `<br>`, `<br/>`, `<br xmlns:java="...">` 모두 줄바꿈으로 바꿉니다(실측 원문에는
      네임스페이스가 붙은 변형 `<br xmlns:java="...">` 이 들어 있습니다).
    · `<td>` 안의 `<span>` 등 하위 태그 텍스트는 전부 그 셀의 텍스트로 합칩니다.
    · `<style>`/`<script>` 안의 내용은 셀 밖이므로 애초에 수집되지 않습니다.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None

    # ── 태그 ────────────────────────────────────────────────────────────────
    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        if name == "tr":
            self._close_cell()
            self._row = []
        elif name in ("td", "th"):
            self._close_cell()
            if self._row is None:
                self._row = []
            attr = {key.lower(): value for key, value in attrs}
            self._cell = {
                "parts": [],
                "rowspan": _span_value(attr.get("rowspan", 1)),
                "colspan": _span_value(attr.get("colspan", 1)),
            }
        elif name == "br" and self._cell is not None:
            self._cell["parts"].append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["parts"].append(data)

    def handle_endtag(self, tag):
        name = tag.lower()
        if name in ("td", "th"):
            self._close_cell()
        elif name == "tr":
            self._close_cell()
            self._flush_row()

    def close(self):
        super().close()
        self._close_cell()
        self._flush_row()

    # ── 내부 ────────────────────────────────────────────────────────────────
    def _close_cell(self):
        if self._cell is None:
            return
        cell = self._cell
        self._cell = None
        cell["text"] = _clean_cell_text("".join(cell["parts"]))
        del cell["parts"]
        if self._row is None:
            self._row = []
        self._row.append(cell)

    def _flush_row(self):
        if self._row:
            self.rows.append(self._row)
        self._row = None


def _logical_rows(rows):
    """
    rowspan/colspan 을 실제 격자로 펼쳐, **각 행이 자기에게 걸쳐 있는 셀을 모두 갖도록** 만듭니다.

    왜 필요한가(이 문서의 핵심 파싱 포인트):
        "3. 1주당 배당금(원)" 라벨 셀은 `rowspan="2"` 라 원본 HTML 상 두 번째 행("종류주식")
        에는 그 라벨이 **없습니다.** 격자로 펼치지 않고 행만 훑으면 "종류주식" 값이 어느
        항목의 값인지 알 수 없어 조용히 놓칩니다.
    """
    occupied = {}
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in occupied:
                c += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    occupied[(r + dr, c + dc)] = cell
            c += cell["colspan"]

    if not occupied:
        return []

    max_row = max(key[0] for key in occupied)
    logical = []
    for r in range(max_row + 1):
        cols = sorted(col for (row_idx, col) in occupied if row_idx == r)
        ordered = []
        for col in cols:
            cell = occupied[(r, col)]
            if not any(cell is seen for seen in ordered):
                ordered.append(cell)
        logical.append(ordered)
    return logical


def _dash_to_none(text):
    """'-' 나 빈 문자열은 '값 없음'입니다. 0 으로 바꾸지 않습니다(§0-1)."""
    if text is None:
        return None
    stripped = str(text).strip()
    if stripped in _DASH_VALUES:
        return None
    return stripped


def _to_number(text):
    """
    '500' → 500, '21,074,903,000' → 21074903000, '0.89' → 0.89.
    해석 못 하면 None (그 사실은 호출부가 unparsed_values 에 남깁니다).
    """
    value = _dash_to_none(text)
    if value is None:
        return None
    cleaned = value.replace(",", "").replace(" ", "")
    try:
        if re.fullmatch(r"[+-]?\d+", cleaned):
            return int(cleaned)
        if re.fullmatch(r"[+-]?\d*\.\d+", cleaned):
            return float(cleaned)
    except (TypeError, ValueError):     # pragma: no cover (정규식이 이미 걸러 냅니다)
        return None
    return None


def _to_iso_date(text):
    """
    'YYYY-MM-DD' 형태이고 실제로 존재하는 날짜면 그대로 반환, 아니면 None.

    ⚠️ 다른 형식('2026.09.03' 등)을 만나면 **바꿔서 저장하지 않습니다.** None 을 돌려주고
       호출부가 원문을 unparsed_values 에 남깁니다 — 우리가 형식을 추측해 변환하기
       시작하면, 그 변환이 틀렸을 때 아무도 모릅니다(§0-1).
    """
    value = _dash_to_none(text)
    if value is None:
        return None
    if not _DATE_RE.match(value):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def parse_dividend_decision_document(html_text, log=print):
    """
    "현금ㆍ현물배당 결정" 원문 HTML 에서 배당 항목을 뽑습니다. **순수 함수(네트워크 없음).**

    반환 dict (값을 못 찾으면 그 필드는 None 이고 사실이 그대로 남습니다):
        dividend_class, dividend_type,
        dps_common, dps_preferred, yield_common, yield_preferred,
        total_amount, record_date, pay_date_expected, board_resolution_date, notes,
        missing_labels   : 문서에서 **라벨 자체를 찾지 못한** 항목명 목록
        unparsed_values  : 라벨은 찾았지만 값을 해석하지 못한 항목 [{label, raw}]
        parse_notes      : 표 구조가 예상과 달랐던 지점 설명(사람이 읽는 문장)
        parse_status     : OK | PARTIAL | FAILED
    """
    parser = _TableCellParser()
    try:
        parser.feed(html_text or "")
        parser.close()
    except Exception as e:
        # HTMLParser 는 웬만해선 던지지 않지만, 던지면 조용히 빈 결과로 넘기지 않습니다.
        log(f"  ⚠️ 원문 HTML 파싱 중 오류({type(e).__name__}: {e}) — "
            "값을 지어내지 않고 FAILED 로 남깁니다.")
        parser.rows = []

    rows = _logical_rows(parser.rows)

    label_by_key = {key: (field, display) for field, key, display in LABEL_SPECS}
    found_values = {}       # field(또는 (field, kind)) → 원문 텍스트
    found_labels = set()    # 라벨 자체를 발견한 field
    parse_notes = []

    for row_index, row in enumerate(rows):
        for cell_index, cell in enumerate(row):
            spec = label_by_key.get(_normalize_label(cell["text"]))
            if spec is None:
                continue
            field, display = spec
            found_labels.add(field)
            rest = row[cell_index + 1:]

            # ① 보통주식/종류주식으로 갈리는 항목 (rowspan 라벨)
            if field in ("dps", "dividend_yield"):
                if not rest:
                    parse_notes.append(
                        f"'{display}' 라벨은 찾았지만 같은 행에 값 셀이 없습니다.")
                    continue
                kind = STOCK_KIND_SUBLABELS.get(_normalize_label(rest[0]["text"]))
                if kind is None:
                    parse_notes.append(
                        f"'{display}' 옆에 '보통주식'/'종류주식' 구분이 없어 어느 주식의 "
                        f"값인지 판단하지 못했습니다(본 값: {rest[0]['text']!r}).")
                    continue
                if len(rest) < 2:
                    parse_notes.append(
                        f"'{display}' 의 '{rest[0]['text']}' 값 셀을 찾지 못했습니다.")
                    continue
                found_values[(field, kind)] = rest[1]["text"]
                continue

            # ② 라벨이 한 행을 통째로 쓰고 값은 다음 행에 오는 항목 (11번 기타사항)
            if not rest:
                next_row = rows[row_index + 1] if row_index + 1 < len(rows) else None
                if next_row and len(next_row) == 1 and \
                        _normalize_label(next_row[0]["text"]) not in label_by_key:
                    found_values[field] = next_row[0]["text"]
                else:
                    parse_notes.append(
                        f"'{display}' 라벨 다음에서 값 셀을 찾지 못했습니다.")
                continue

            # ③ 일반 항목: 라벨 바로 다음 셀이 값
            found_values[field] = rest[0]["text"]

    # ── 값 해석 ──────────────────────────────────────────────────────────────
    unparsed = []

    def _take(field, converter=None, display=None):
        if field not in found_values:
            return None
        raw = found_values[field]
        if converter is None:
            return _dash_to_none(raw)
        if _dash_to_none(raw) is None:
            return None
        value = converter(raw)
        if value is None:
            unparsed.append({"label": display, "raw": raw})
        return value

    def _take_kind(field, kind, converter, display):
        key = (field, kind)
        if key not in found_values:
            return None
        raw = found_values[key]
        if _dash_to_none(raw) is None:
            return None
        value = converter(raw)
        if value is None:
            unparsed.append({"label": f"{display}({kind})", "raw": raw})
        return value

    display_of = {field: display for field, _key, display in LABEL_SPECS}

    parsed = {
        "dividend_class": _take("dividend_class"),
        "dividend_type": _take("dividend_type"),
        "dps_common": _take_kind("dps", "common", _to_number, display_of["dps"]),
        "dps_preferred": _take_kind("dps", "preferred", _to_number, display_of["dps"]),
        "yield_common": _take_kind("dividend_yield", "common", _to_number,
                                   display_of["dividend_yield"]),
        "yield_preferred": _take_kind("dividend_yield", "preferred", _to_number,
                                      display_of["dividend_yield"]),
        "total_amount": _take("total_amount", _to_number, display_of["total_amount"]),
        "record_date": _take("record_date", _to_iso_date, display_of["record_date"]),
        "pay_date_expected": _take("pay_date_expected", _to_iso_date,
                                   display_of["pay_date_expected"]),
        "board_resolution_date": _take("board_resolution_date", _to_iso_date,
                                       display_of["board_resolution_date"]),
        "notes": _take("notes"),
    }

    missing_labels = [display for field, _key, display in LABEL_SPECS
                      if field not in found_labels]

    if all(field not in found_labels for field in CORE_FIELDS):
        status = PARSE_FAILED
    elif missing_labels or unparsed or parse_notes:
        status = PARSE_PARTIAL
    else:
        status = PARSE_OK

    parsed["missing_labels"] = missing_labels
    parsed["unparsed_values"] = unparsed
    parsed["parse_notes"] = parse_notes
    parsed["parse_status"] = status
    return parsed


# =============================================================================
# 4. 네트워크 (테스트에서는 이 두 함수만 monkeypatch 합니다)
# =============================================================================
def _http_get_json(url, params, timeout, session):
    """실제 네트워크 호출 지점. 반환: (status_code, parsed_json 또는 None)"""
    if session is None and requests is None:
        raise DartPaymentApiError("`requests` 패키지가 없어 DART 를 호출할 수 없습니다.")
    getter = session.get if session is not None else requests.get
    res = getter(url, params=params, timeout=timeout)
    status = getattr(res, "status_code", None)
    try:
        payload = res.json()
    except Exception:
        payload = None
    return status, payload


def _http_get_bytes(url, params, timeout, session):
    """
    바이너리 응답(zip) 취득 지점. 반환: (status_code, body_bytes, content_type)

    ⚠️ 오류 메시지 어디에도 `params` 를 넣지 않습니다 — 인증키가 그대로 로그에 찍힙니다.
    """
    if session is None and requests is None:
        raise DartPaymentApiError("`requests` 패키지가 없어 DART 를 호출할 수 없습니다.")
    getter = session.get if session is not None else requests.get
    res = getter(url, params=params, timeout=timeout)
    status = getattr(res, "status_code", None)
    body = getattr(res, "content", None)
    headers = getattr(res, "headers", None) or {}
    try:
        content_type = headers.get("Content-Type") or headers.get("content-type")
    except Exception:       # pragma: no cover (dict 가 아닌 헤더 객체 방어)
        content_type = None
    return status, body, content_type


def polite_sleep(rng=None):
    """
    §0-3-2 기준 딜레이(2~3초 랜덤). 기존 수집기와 같은 기준입니다.

    (그쪽 함수를 직접 부르지 않고 여기에 따로 둔 이유: 테스트가 이 모듈만 monkeypatch 해도
     되도록 — 다른 모듈의 동작에 손대지 않기 위해서입니다.)
    """
    delay = (rng or random).uniform(DART_REQUEST_DELAY_MIN, DART_REQUEST_DELAY_MAX)
    time.sleep(delay)
    return delay


def _dart_status_of(payload):
    """DART 응답의 status 코드 문자열. 없으면 None."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return None if status is None else str(status).strip()


def _raise_if_fatal_http(status_code, what):
    if status_code in (403, 429):
        raise DartPaymentFatalError(
            f"DART 가 HTTP {status_code} 로 차단했습니다({what}). 재시도하지 않고 실행 "
            "전체를 중단합니다(§0-3-2). 상태 파일을 갱신하지 않으므로 다음 실행이 같은 "
            "구간을 다시 확인합니다.")


def _raise_if_fatal_status(payload, what):
    status = _dart_status_of(payload)
    if status in DART_FATAL_STATUSES:
        raise DartPaymentFatalError(
            f"DART status {status} — {DART_STATUS_MESSAGES.get(status, '알 수 없는 코드')} "
            f"재시도하지 않고 실행 전체를 중단합니다(§0-3-2, {what}).")
    return status


def _fetch_disclosure_list_page(params, session):
    """
    list.json 한 페이지. 재시도·치명 판정은 기존 수집기와 **같은 철학**입니다(§0-3-2):
      · HTTP 403/429, DART 치명 status → DartPaymentFatalError (재시도 금지, 즉시 중단)
      · 그 밖의 개별 실패              → DartPaymentApiError
    """
    last_error = None
    for attempt in range(DART_NETWORK_RETRY + 1):
        try:
            status_code, payload = _http_get_json(
                DART_DISCLOSURE_LIST_URL, params, DART_REQUEST_TIMEOUT_SEC, session)
        except (DartPaymentApiError, DartPaymentFatalError):
            raise
        except Exception as e:
            last_error = f"네트워크 오류: {type(e).__name__}"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartPaymentApiError(f"공시목록 조회 실패 — {last_error}")

        _raise_if_fatal_http(status_code, "공시목록 조회")
        if status_code is not None and 400 <= status_code < 500:
            raise DartPaymentApiError(f"공시목록 조회 HTTP {status_code} — 재시도하지 않습니다.")
        if status_code is not None and status_code >= 500:
            last_error = f"서버 오류(HTTP {status_code})"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartPaymentApiError(f"공시목록 조회 실패 — {last_error}")
        if status_code not in (200, None):
            raise DartPaymentApiError(f"공시목록 조회 — 예상치 못한 HTTP 상태 {status_code}.")
        if not isinstance(payload, dict):
            raise DartPaymentApiError("공시목록 응답이 JSON 객체가 아닙니다.")

        _raise_if_fatal_status(payload, "공시목록 조회")
        return payload

    raise DartPaymentApiError(f"공시목록 조회 실패 — {last_error}")   # 방어(도달하지 않습니다)


def _positive_int(value):
    """숫자로 읽히면 int, 아니면 None. (문자열 "2" 도 받습니다 — DART 는 둘 다 씁니다)"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def fetch_dividend_decision_disclosures(bgn_de, end_de, api_key, session=None, log=print,
                                        stats=None):
    """
    `bgn_de`~`end_de`(접수일, YYYYMMDD) 구간의 거래소공시(`pblntf_ty="I"`) 중
    **배당결정 공시만** 골라 리스트로 돌려줍니다. 파일을 쓰지 않는 순수 조회 함수입니다.

    ⚠️ 유니버스로 사전 필터링하지 않습니다. 이 경로의 장점이 바로 "정기보고서 기반 유니버스에
       아직 없는 신규 배당 회사도 잡힌다"는 것이기 때문입니다.

    ⚠️ **페이지네이션 필수** — 실측한 3일 전부 total_page=2 였습니다(하루 100건 초과).
       1페이지만 읽고 "그 구간 확인 끝"으로 적으면 그날의 절반 가까이를 영영 놓칩니다(§0-1).

    반환: [{corp_code, corp_name, stock_code, stock_code_raw, report_nm, report_nm_extra,
            rcept_no, rcept_dt, is_correction, is_subsidiary_notice}, ...]
          (rcept_no 오름차순 — 접수 순서)

    `stats`: dict 를 넘기면 집계를 담아 줍니다(호출부가 리포트에 남기기 위함).
        seen_rows, dividend_decisions, shareholder_register_close, unrecognized,
        skipped_no_stock_code, skipped_bad_stock_code, pages, unrecognized_samples
    """
    counters = {
        "pages": 0,
        "seen_rows": 0,
        "dividend_decisions": 0,
        "shareholder_register_close": 0,
        "unrecognized": 0,
        "skipped_no_stock_code": 0,
        "skipped_bad_stock_code": 0,
        "unrecognized_samples": [],
    }
    events = []
    seen_rcept_no = set()

    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "pblntf_ty": EXCHANGE_PBLNTF_TY,      # 거래소공시(수시공시)
            "bgn_de": str(bgn_de),
            "end_de": str(end_de),
            "page_no": str(page_no),
            "page_count": str(DART_LIST_PAGE_COUNT),
        }
        # §0-3-2: **요청 사이**에 딜레이. 첫 요청 앞에서는 기다리지 않습니다.
        if counters["pages"]:
            polite_sleep()
        payload = _fetch_disclosure_list_page(params, session)
        counters["pages"] += 1

        status = _dart_status_of(payload)
        if status == "013":
            # 013 은 오류가 아니라 "그 구간에 0건"(휴장일·주말). 기존 수집기와 같은 관례.
            log(f"  · 거래소공시 {bgn_de}~{end_de} 접수분 0건(status 013)")
            break
        if status != "000":
            raise DartPaymentApiError(
                f"공시목록 status {status} "
                f"({DART_STATUS_MESSAGES.get(status, '알 수 없는 코드')}) — page_no={page_no}")

        rows = payload.get("list")
        if not isinstance(rows, list):
            raise DartPaymentApiError(
                f"공시목록 status 000 인데 `list` 가 리스트가 아닙니다(page_no={page_no}) — "
                "응답 규격이 바뀌었을 수 있습니다.")

        total_page = _positive_int(payload.get("total_page"))
        if total_page is None:
            # 몇 페이지인지 모르는 채 1페이지만 읽고 "다 확인했다"고 기록하면 그 구간을
            # 영영 놓칩니다(§0-1: 확인 못 한 것을 확인했다고 하지 않기).
            raise DartPaymentApiError(
                f"공시목록 응답에 total_page 가 없거나 숫자가 아닙니다(page_no={page_no}, "
                f"받은 값={payload.get('total_page')!r}) — 일부만 읽고 전부 확인한 것처럼 "
                "기록하지 않기 위해 여기서 멈춥니다.")
        if total_page > DART_LIST_MAX_PAGES:
            raise DartPaymentApiError(
                f"공시목록 total_page 가 {total_page:,}쪽입니다(상한 "
                f"{DART_LIST_MAX_PAGES:,}쪽) — 조회 구간이 지나치게 넓거나 응답이 이상합니다. "
                "무한정 요청하지 않고 멈춥니다(§0-3-2).")

        for row in rows:
            if not isinstance(row, dict):
                continue
            counters["seen_rows"] += 1
            verdict = classify_report_nm(row.get("report_nm"))
            kind = verdict["kind"]

            if kind == KIND_NOT_DIVIDEND:
                continue
            if kind == KIND_SHAREHOLDER_REGISTER_CLOSE:
                counters["shareholder_register_close"] += 1
                continue
            if kind == KIND_UNRECOGNIZED:
                counters["unrecognized"] += 1
                if len(counters["unrecognized_samples"]) < MAX_UNRECOGNIZED_SAMPLES:
                    counters["unrecognized_samples"].append({
                        "report_nm": row.get("report_nm"),
                        "corp_name": row.get("corp_name"),
                        "stock_code": row.get("stock_code"),
                        "rcept_no": row.get("rcept_no"),
                        "rcept_dt": row.get("rcept_dt"),
                        "parse_status": KIND_UNRECOGNIZED,
                    })
                continue

            raw_code = row.get("stock_code")
            if raw_code is None or str(raw_code).strip() == "":
                # 비상장(채권만 발행한 법인 등). 종목코드가 없으면 화면에서 종목과 이을 수
                # 없어 이번 범위에서는 다루지 않습니다 — 다만 몇 건인지는 남깁니다.
                counters["skipped_no_stock_code"] += 1
                continue

            code = normalize_stock_code(raw_code)
            if code is None:
                # 조용히 버리지 않습니다. 처음 보는 표기라면 사람이 알아야 합니다(§0-1).
                # 이벤트 자체는 살려 두되 stock_code 는 None 으로 남깁니다(지어내지 않기).
                counters["skipped_bad_stock_code"] += 1
                log(f"  ⚠️ 종목코드를 6자리로 정규화하지 못했습니다: {str(raw_code)!r} "
                    f"(rcept_no={row.get('rcept_no')}) — 레코드는 stock_code=None 으로 "
                    "남기고 원문은 stock_code_raw 에 보존합니다.")

            rcept_no = row.get("rcept_no")
            if rcept_no in seen_rcept_no:
                # 같은 접수번호가 페이지 경계에서 두 번 오는 경우 방어(중복 이벤트 방지).
                continue
            seen_rcept_no.add(rcept_no)

            counters["dividend_decisions"] += 1
            events.append({
                "corp_code": row.get("corp_code"),
                "corp_name": row.get("corp_name"),
                "stock_code": code,
                "stock_code_raw": str(raw_code).strip(),
                "report_nm": row.get("report_nm"),
                "report_nm_extra": verdict["report_nm_extra"],
                "matched_prefix": verdict["matched_prefix"],
                "rcept_no": rcept_no,
                "rcept_dt": row.get("rcept_dt"),
                "is_correction": verdict["is_correction"],
                "is_subsidiary_notice": verdict["is_subsidiary_notice"],
            })

        if page_no >= total_page:
            break
        page_no += 1

    # ── 무엇을 건너뛰었는지 반드시 남깁니다(§0-1) ────────────────────────────
    log(f"  → 거래소공시 {counters['pages']:,}페이지 조회, 항목 {counters['seen_rows']:,}건 중 "
        f"배당결정 {counters['dividend_decisions']:,}건")
    if counters["shareholder_register_close"]:
        log(f"  · '주주명부폐쇄(기준일)결정' {counters['shareholder_register_close']:,}건은 "
            "배당결정이 아니라 건너뛰었습니다(배당금·지급일이 없는 공시입니다).")
    if counters["skipped_no_stock_code"]:
        log(f"  · 종목코드가 없는 배당결정 {counters['skipped_no_stock_code']:,}건은 "
            "건너뛰었습니다(비상장 법인 등).")
    if counters["unrecognized"]:
        log(f"  ⚠️ report_nm 에 '배당'이 들어 있지만 우리 판정 규칙(실측 표본 6종)에 없는 표기 "
            f"{counters['unrecognized']:,}건을 발견했습니다 — "
            f"'{KIND_UNRECOGNIZED}' 로 리포트에 남깁니다(규칙을 추측해서 넓히지 않습니다).")
        for sample in counters["unrecognized_samples"][:10]:
            log(f"      · {sample.get('report_nm')!r} "
                f"({sample.get('corp_name')}, rcept_no={sample.get('rcept_no')})")

    events.sort(key=lambda item: str(item.get("rcept_no") or ""))
    if stats is not None:
        stats.update(counters)
    return events


def fetch_disclosure_document(rcept_no, api_key, session=None, log=print):
    """
    `document.xml` 로 공시 원문(zip)을 받아 **텍스트로 디코딩해서** 돌려줍니다.

    실측 기준(2026-08-20, rcept_no=20260820800655):
      · 바디는 zip, 안에 `{rcept_no}.xml` 1개.
      · meta 태그는 euc-kr 이라 하지만 실제 바이트는 utf-8 로 디코딩됩니다.

    실패는 감추지 않고 예외로 던집니다. 이 계층은 수집기이므로 원인을 그대로 남깁니다
    (§0-3-4 는 화면 계층 규칙입니다 — 사용자에게 보이는 문자열이 아닙니다).
    ⚠️ 다만 인증키는 어떤 메시지에도 넣지 않습니다.
    """
    params = {"crtfc_key": api_key, "rcept_no": str(rcept_no)}

    last_error = None
    body = None
    content_type = None
    for attempt in range(DART_NETWORK_RETRY + 1):
        try:
            status_code, body, content_type = _http_get_bytes(
                DART_DOCUMENT_URL, params, DART_REQUEST_TIMEOUT_SEC, session)
        except (DartPaymentApiError, DartPaymentFatalError):
            raise
        except Exception as e:
            last_error = f"네트워크 오류: {type(e).__name__}"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartPaymentApiError(f"공시원문 조회 실패(rcept_no={rcept_no}) — {last_error}")

        _raise_if_fatal_http(status_code, f"공시원문 조회 rcept_no={rcept_no}")
        if status_code is not None and 400 <= status_code < 500:
            raise DartPaymentApiError(
                f"공시원문 조회 HTTP {status_code}(rcept_no={rcept_no}) — 재시도하지 않습니다.")
        if status_code is not None and status_code >= 500:
            last_error = f"서버 오류(HTTP {status_code})"
            if attempt < DART_NETWORK_RETRY:
                time.sleep(DART_RETRY_DELAY_SEC)
                continue
            raise DartPaymentApiError(f"공시원문 조회 실패(rcept_no={rcept_no}) — {last_error}")
        if status_code not in (200, None):
            raise DartPaymentApiError(
                f"공시원문 조회 — 예상치 못한 HTTP 상태 {status_code}(rcept_no={rcept_no}).")
        break

    if not isinstance(body, (bytes, bytearray)):
        raise DartPaymentApiError(
            f"공시원문 응답 본문이 바이트가 아닙니다(rcept_no={rcept_no}, "
            f"받은 형: {type(body).__name__}).")
    body = bytes(body)

    if len(body) > MAX_DOCUMENT_BYTES:
        raise DartPaymentApiError(
            f"공시원문이 상한({MAX_DOCUMENT_BYTES:,}바이트)보다 큽니다"
            f"(rcept_no={rcept_no}, {len(body):,}바이트) — 통째로 메모리에 올리지 않고 "
            "멈춥니다.")

    # ── zip 인지 **먼저** 확인 ───────────────────────────────────────────────
    # rcept_no 가 틀리면 DART 가 HTTP 200 으로 JSON 오류를 줄 수 있습니다. 그걸 zip 으로
    # 열려고 시도하면 엉뚱한 예외가 나므로, 시그니처부터 확인하고 원인을 그대로 남깁니다.
    if body[:2] != b"PK":
        text_head = body[:400].decode("utf-8", errors="replace")
        detail = f" 응답 앞부분: {text_head!r}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            status = _dart_status_of(payload)
            _raise_if_fatal_status(payload, f"공시원문 조회 rcept_no={rcept_no}")
            detail = (f" DART status={status} "
                      f"({DART_STATUS_MESSAGES.get(status, '알 수 없는 코드')})")
        raise DartPaymentApiError(
            f"공시원문 응답이 zip 이 아닙니다(rcept_no={rcept_no}, "
            f"Content-Type={content_type!r}, {len(body):,}바이트).{detail}")

    # ── 압축 해제 ────────────────────────────────────────────────────────────
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        names = [name for name in archive.namelist() if not name.endswith("/")]
    except Exception as e:
        raise DartPaymentApiError(
            f"공시원문 zip 을 열지 못했습니다(rcept_no={rcept_no}) — {type(e).__name__}: {e}")

    if not names:
        raise DartPaymentApiError(f"공시원문 zip 이 비어 있습니다(rcept_no={rcept_no}).")

    expected = f"{rcept_no}.xml"
    if len(names) == 1:
        chosen = names[0]
    else:
        # 실측은 1개였습니다. 여러 개면 **어떤 것을 왜 골랐는지 반드시 남깁니다**
        # (조용히 첫 번째를 쓰면, 나중에 다른 파일이 본문이었을 때 아무도 모릅니다).
        if expected in names:
            chosen = expected
            reason = f"접수번호와 같은 이름('{expected}')"
        else:
            xml_names = [name for name in names if name.lower().endswith(".xml")]
            if xml_names:
                chosen = xml_names[0]
                reason = "이름이 접수번호와 다르지만 첫 번째 .xml 파일"
            else:
                chosen = names[0]
                reason = ".xml 파일이 없어 첫 번째 항목"
        log(f"  ⚠️ 공시원문 zip 안에 파일이 {len(names)}개입니다(rcept_no={rcept_no}): "
            f"{names} → {reason}인 '{chosen}' 을 본문으로 사용합니다.")

    try:
        raw = archive.read(chosen)
    except Exception as e:
        raise DartPaymentApiError(
            f"공시원문 zip 에서 '{chosen}' 을 읽지 못했습니다(rcept_no={rcept_no}) — "
            f"{type(e).__name__}: {e}")

    # ── 디코딩: meta 태그를 믿지 않습니다 ────────────────────────────────────
    # 실측 — 파일 안 meta 는 charset=euc-kr 이라고 적혀 있지만 실제 바이트는 utf-8 이었습니다.
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if encoding != "utf-8":
            log(f"  ℹ️ 공시원문을 utf-8 로 읽지 못해 {encoding} 로 디코딩했습니다"
                f"(rcept_no={rcept_no}).")
        return text

    raise DartPaymentApiError(
        f"공시원문을 utf-8/euc-kr/cp949 어느 것으로도 디코딩하지 못했습니다"
        f"(rcept_no={rcept_no}, '{chosen}', {len(raw):,}바이트).")


# =============================================================================
# 5. 산출물 경로 / 읽기·쓰기
# =============================================================================
def payment_events_path(out_dir, bsns_year):
    """가공본 경로. 기존 배당 파일(dividend_kr_YYYY_latest.json)과 이름이 겹치지 않습니다."""
    return os.path.join(out_dir, f"dividend_kr_{bsns_year}_payment_events.json")


def payment_events_raw_path(out_dir, bsns_year):
    """원본 HTML 보관 경로(§0-3-3 — raw 와 가공본은 다른 파일)."""
    return os.path.join(out_dir, f"dividend_kr_{bsns_year}_payment_events_raw.jsonl")


def payment_state_path(cache_dir, bsns_year):
    """감시 진행 상태 파일 경로(마지막으로 확인을 끝낸 접수일)."""
    return os.path.join(cache_dir, f"dividend_kr_{bsns_year}_payment_state.json")


def _atomic_write_json(path, payload):
    """tmp → os.replace 원자적 교체. 쓰다 만 파일이 남지 않습니다."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_payment_events(path, log=print):
    """
    기존 이벤트 파일을 읽습니다. 반환: (records 리스트, 원본 payload dict).

    ⚠️ 파일이 깨졌으면 **빈 리스트로 시작하지 않습니다.** append-only 정책에서 기존 내용을
       못 읽은 채 새로 쓰면 지금까지 모은 이벤트가 통째로 사라집니다 — 그건 데이터 손실이라
       예외를 던져 실행을 멈춥니다(§0-1).
    """
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise DartPaymentFatalError(
            f"기존 배당지급 이벤트 파일을 읽지 못했습니다: {path} ({type(e).__name__}: {e}). "
            "이 데이터는 append-only 라 못 읽은 채 새로 쓰면 지금까지 쌓인 이벤트가 사라집니다 "
            "— 진행하지 않습니다.")
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise DartPaymentFatalError(
            f"기존 배당지급 이벤트 파일의 형태가 예상과 다릅니다: {path} "
            '({"summary": ..., "records": [...]} 형태여야 합니다). 덮어쓰지 않고 멈춥니다.')
    records = payload["records"]
    log(f"  ℹ️ 기존 이벤트 {len(records):,}건을 읽었습니다: {path}")
    return records, payload


def append_raw(raw_path, entry):
    """
    §0-3-3: **원본 HTML 을 가공본과 다른 파일에** 그대로 누적합니다(JSON Lines).
    파싱 규칙을 나중에 바꿔도 원문을 다시 긁지 않아도 되게 하는 것이 목적입니다.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(raw_path)) or ".", exist_ok=True)
        with open(raw_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"  ⚠️ raw 보관 실패(수집은 계속): {type(e).__name__}: {e}")
        return False


def read_payment_state(path, log=print):
    """
    상태 파일 읽기. 없거나 깨졌으면 빈 상태({}).

    ⚠️ 빈 상태 = "어디까지 확인했는지 모른다" 입니다. 그때는 `lookback_days` 만큼 거슬러
       올라가 다시 확인합니다 — 모르는 구간을 확인한 셈 치지 않습니다(§0-1).
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log(f"  ⚠️ 상태 파일을 읽지 못했습니다({type(e).__name__}: {e}) — "
            f"'어디까지 확인했는지 모른다'로 보고 lookback 부터 다시 확인합니다: {path}")
        return {}
    if not isinstance(data, dict):
        log(f"  ⚠️ 상태 파일의 형태가 예상과 다릅니다 — lookback 부터 다시 확인합니다: {path}")
        return {}
    return data


def write_payment_state(path, last_checked_de):
    """
    "이 접수일까지는 확인을 끝냈다"를 기록합니다(원자적 교체).

    ⚠️ 호출 시점이 중요합니다 — **그 날짜까지 실제로 다 반영한 뒤에만** 부르세요.
       실패했는데 '확인 끝'으로 적어 두면 그 구간은 영원히 다시 확인되지 않습니다(§0-1).
    """
    payload = {"last_checked_de": str(last_checked_de),
               "updated_at_kst": _now_kst().isoformat()}
    _atomic_write_json(path, payload)
    return payload


def merge_last_checked_de(existing_de, candidate_de, log=print):
    """
    상태 파일의 `last_checked_de` 를 **절대 뒤로 되돌리지 않는** 병합 규칙(순수 함수).

    백필(과거 구간을 한 번 훑는 실행)이 정기 감시의 진행 상태를 망가뜨리지 않게 하는
    장치입니다. 예를 들어 상태가 이미 20260824 까지 확인된 상태에서 20260801~20260819 를
    백필하면, 상태 파일은 **여전히 20260824** 여야 합니다. 20260819 로 되돌리면 다음 정기
    실행이 20260820 부터 다시 훑어 **이미 확인한 닷새치를 DART 에 다시 요청**하게 됩니다
    (§0-3-2 위반).

    반환:
      · 새로 적어야 할 'YYYYMMDD' 문자열
      · **None** = "상태 파일을 건드리지 마세요"(되돌리게 되거나, 기존 값을 해석 못 해
        어느 쪽이 앞인지 판단할 수 없는 경우)
    """
    candidate = _parse_de(candidate_de)
    if candidate is None:
        # 호출부의 버그입니다. 조용히 넘기면 엉뚱한 값이 상태 파일에 박힙니다(§0-1).
        raise DartPaymentFatalError(
            f"상태 파일에 적으려는 날짜를 YYYYMMDD 로 읽지 못했습니다: {candidate_de!r} "
            "— 확인 범위를 알 수 없는 값을 '확인 끝'으로 적지 않습니다.")

    if not existing_de:
        return str(candidate_de)

    existing = _parse_de(existing_de)
    if existing is None:
        # 기존 값을 못 읽으면 어디까지 확인됐는지 모릅니다 → 덮어쓰면 되돌리는 것일 수도
        # 있습니다. 모를 때는 건드리지 않습니다(§0-1). 감시 모드는 이 깨진 값을 '상태 없음'
        # 으로 보고 lookback 부터 다시 확인하므로 놓치는 구간은 생기지 않습니다.
        log(f"  ⚠️ 기존 상태 파일의 last_checked_de 를 날짜로 읽지 못했습니다"
            f"({existing_de!r}) — 어느 쪽이 더 뒤인지 판단할 수 없어 상태 파일을 "
            "건드리지 않습니다.")
        return None

    if existing == candidate:
        log(f"  ℹ️ 상태 파일이 이미 {existing_de} 입니다 — 같은 값을 다시 쓰지 않습니다"
            "(내용이 같은 파일을 커밋하지 않기 위함).")
        return None
    if existing > candidate:
        log(f"  ℹ️ 상태 파일은 이미 {existing_de} 까지 '확인 끝'입니다 — 이번 실행의 "
            f"{candidate_de} 로 **되돌리지 않고** 그대로 둡니다(되돌리면 다음 정기 실행이 "
            "이미 확인한 구간을 DART 에 다시 요청하게 됩니다 — §0-3-2).")
        return None

    return str(candidate_de)


def _parse_de(text):
    """'YYYYMMDD' → date. 해석 못 하면 None(넘겨짚지 않습니다)."""
    if not text:
        return None
    try:
        return datetime.strptime(str(text).strip(), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def build_payment_event_record(candidate, parsed):
    """공시목록 항목 + 원문 파싱 결과 → 저장할 레코드 하나(순수 함수)."""
    record = {
        # ── 어디서 온 이벤트인가 ────────────────────────────────────────────
        "rcept_no": candidate.get("rcept_no"),
        "rcept_dt": candidate.get("rcept_dt"),
        "corp_code": candidate.get("corp_code"),
        "corp_name": candidate.get("corp_name"),
        "stock_code": candidate.get("stock_code"),
        "stock_code_raw": candidate.get("stock_code_raw"),
        "report_nm": candidate.get("report_nm"),
        "report_nm_extra": candidate.get("report_nm_extra"),
        "matched_prefix": candidate.get("matched_prefix"),
        "is_correction": candidate.get("is_correction"),
        # ⚠️ True 면 공시 주체와 실제 배당 회사가 다를 수 있습니다. 어느 자회사인지는
        #    추론하지 않습니다(§0-1) — 화면에서 이 플래그를 그대로 고지해야 합니다.
        "is_subsidiary_notice": candidate.get("is_subsidiary_notice"),
        "dart_document_url": dart_document_url(candidate.get("rcept_no")),
        "collected_at_kst": _now_kst().isoformat(),
    }
    for key in ("dividend_class", "dividend_type", "dps_common", "dps_preferred",
                "yield_common", "yield_preferred", "total_amount",
                "record_date", "pay_date_expected", "board_resolution_date", "notes",
                "missing_labels", "unparsed_values", "parse_notes", "parse_status"):
        record[key] = parsed.get(key)
    return record


def summarize_payment_events(records, extra=None):
    """
    리포트(summary)를 만듭니다. (순수 함수)

    §0-1: '성공 건수'만 세지 않습니다. PARTIAL/FAILED 가 몇 건인지, 핵심 날짜가 비어 있는
          레코드가 몇 건인지 함께 셉니다 — 화면에도 이 숫자가 그대로 올라가야 합니다.
    """
    by_status = {}
    missing_label_counts = {}
    without_record_date = 0
    without_pay_date = 0
    corrections = 0
    subsidiary_notices = 0
    for rec in records or []:
        status = rec.get("parse_status") or "UNKNOWN"
        by_status[status] = by_status.get(status, 0) + 1
        for label in rec.get("missing_labels") or []:
            missing_label_counts[label] = missing_label_counts.get(label, 0) + 1
        if not rec.get("record_date"):
            without_record_date += 1
        if not rec.get("pay_date_expected"):
            without_pay_date += 1
        if rec.get("is_correction"):
            corrections += 1
        if rec.get("is_subsidiary_notice"):
            subsidiary_notices += 1

    summary = {
        "generated_at_kst": _now_kst().isoformat(),
        "source": "DART 수시공시(거래소공시 pblntf_ty=I) 원문 document.xml",
        "total_records": len(records or []),
        "by_parse_status": by_status,
        "records_without_record_date": without_record_date,
        "records_without_pay_date_expected": without_pay_date,
        "records_with_correction_flag": corrections,
        "records_with_subsidiary_notice_flag": subsidiary_notices,
        "missing_label_counts": missing_label_counts,
        # ⚠️ 반드시 읽어야 하는 한계 — 리포트에 늘 붙여 다닙니다(§0-1).
        "known_limitations": [
            "이 파일은 '현재 배당 상태'가 아니라 '접수된 배당결정 공시 이벤트의 로그'입니다. "
            "[기재정정] 공시는 원본과 별개 레코드로 함께 남습니다(rcept_no 가 다르므로) — "
            "어느 것이 최종본인지는 이 파일이 판단하지 않습니다.",
            "is_subsidiary_notice=true 인 레코드는 공시 주체(corp_name/stock_code)와 실제 "
            "배당하는 회사가 다를 수 있습니다. 어느 자회사인지 자동으로 추론하지 않았습니다.",
            "report_nm 판정 규칙은 2026-08 실측 표본 6종에서만 도출했습니다. 규칙 밖의 표기는 "
            "UNRECOGNIZED_REPORT_TYPE 으로 아래 scan_stats 에 남고, 이벤트로 만들지 "
            "않았습니다(추측해서 넓히지 않았습니다).",
            "파일 이름의 연도는 '접수일이 그 해'라는 뜻일 뿐, 회사의 사업연도와 다를 수 "
            "있습니다(list.json 에는 사업연도로 거르는 조건이 없습니다).",
        ],
    }
    if extra:
        summary.update(extra)
    return summary


# =============================================================================
# 6. 오케스트레이션
# =============================================================================
def run_watch_payment_events(bsns_year, out_dir, cache_dir=None, lookback_days=3,
                             api_key=None, session=None, log=print, today=None):
    """
    매일 1회 도는 감시 본체. (main() 은 인자만 넘깁니다 — 테스트하기 쉽도록 분리)

    흐름:
      ① 상태 파일에서 "어디까지 확인했나"를 읽어 이번에 확인할 접수일 구간을 정합니다.
         (끝은 **어제 KST** — 오늘은 아직 하루가 안 끝나 접수가 더 들어올 수 있습니다)
      ② list.json(pblntf_ty="I")을 페이지 끝까지 훑어 배당결정 공시를 고릅니다.
      ③ 이미 파일에 있는 rcept_no 는 **원문을 받지 않고** 건너뜁니다(§0-3-2).
      ④ 남은 것만 원문(document.xml)을 받아 파싱하고 append-only 로 추가합니다.
      ⑤ **실제로 다 반영한 날짜까지만** 상태 파일을 전진시킵니다.

    ⑤의 의미: 어떤 공시 하나를 못 받으면, 그 공시가 접수된 날의 **전날까지만** "확인 끝"으로
    적습니다. 그러면 다음 실행이 그 날부터 다시 확인하고, 이미 받아 둔 건은 ③에서 걸러지므로
    **실패한 것만** 다시 받습니다. "실패했는데 확인 끝으로 적어 영영 놓치는 일"도,
    "성공한 것까지 매일 다시 받는 일"도 생기지 않습니다.

    ②~④는 `_collect_payment_events_in_range()` 에 있습니다 — 일회성 백필
    (`run_backfill_payment_events()`)이 **같은 코드**를 씁니다(§0-3-10). 두 모드가 다른
    것은 ①(구간을 어떻게 정하는가)과 ⑤(상태 파일을 어떻게 전진시키는가)뿐입니다.

    반환: 프로세스 종료코드(0=정상, 2=사람이 손봐야 하는 중단).
    """
    cache_dir = cache_dir or out_dir
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    events_path = payment_events_path(out_dir, bsns_year)
    raw_path = payment_events_raw_path(out_dir, bsns_year)
    state_path = payment_state_path(cache_dir, bsns_year)

    # ── ① 확인할 구간 정하기 ─────────────────────────────────────────────────
    state = read_payment_state(state_path, log=log)
    last_checked_de = state.get("last_checked_de")

    today = today or _now_kst().date()
    end_date = today - timedelta(days=1)        # 어제까지(오늘은 다음 실행에서 확인)

    start_date = None
    if last_checked_de:
        parsed_de = _parse_de(last_checked_de)
        if parsed_de is None:
            log(f"  ⚠️ 상태 파일의 last_checked_de 를 날짜로 읽지 못했습니다"
                f"({last_checked_de!r}) — 확인한 셈 치지 않고 lookback "
                f"{lookback_days}일부터 다시 확인합니다.")
        else:
            start_date = parsed_de + timedelta(days=1)
    if start_date is None:
        start_date = today - timedelta(days=max(1, int(lookback_days)))

    if start_date > end_date:
        # 조용히 스킵하지 않습니다 — 왜 아무 일도 안 했는지 사람이 알아야 합니다(§0-1).
        log(f"ℹ️ 확인할 새 구간이 없습니다"
            f"(이미 {last_checked_de or '(상태 없음)'}까지 확인함 — 다음 확인 시작일 "
            f"{start_date:%Y-%m-%d} 가 확인 종료일 {end_date:%Y-%m-%d}(어제)보다 뒤입니다). "
            "상태 파일은 건드리지 않습니다.")
        return 0

    bgn_de = start_date.strftime("%Y%m%d")
    end_de = end_date.strftime("%Y%m%d")
    log("─" * 78)
    log(f"📡 배당결정 공시 감시 — 접수일 {start_date:%Y-%m-%d} ~ {end_date:%Y-%m-%d} 구간의 "
        f"거래소공시(pblntf_ty={EXCHANGE_PBLNTF_TY}) 중 배당결정 공시를 확인합니다.")

    key = get_api_key(api_key)
    if not key:
        raise DartPaymentFatalError(
            f"환경변수 {DART_API_KEY_ENV} 가 없습니다. 인증키를 코드에 적지 말고 "
            "GitHub Actions Secret / 로컬 환경변수로 넣으세요.")

    result = _collect_payment_events_in_range(
        bgn_de, end_de, key, events_path, raw_path, start_date,
        session=session, log=log)
    failures = result["failures"]

    # ── ⑤ 실제로 다 반영한 날짜까지만 상태를 전진시킵니다 ────────────────────
    if not failures:
        write_payment_state(state_path, end_de)
        log(f"   상태 파일 갱신: {state_path} (last_checked_de={end_de}, "
            f"총 {result['total']:,}건)")
    else:
        first_failed_date = result["first_failed_date"]
        safe_end = (first_failed_date - timedelta(days=1)) if first_failed_date else None
        if safe_end is not None and safe_end >= start_date:
            safe_de = safe_end.strftime("%Y%m%d")
            write_payment_state(state_path, safe_de)
            log(f"  ⚠️ 원문 실패 {len(failures):,}건 — 상태 파일을 실패한 날의 전날까지만 "
                f"전진시킵니다(last_checked_de={safe_de}). 다음 실행이 그 날부터 다시 "
                "확인하고, 이미 받아 둔 건은 건너뜁니다.")
        else:
            log(f"  ⚠️ 원문 실패 {len(failures):,}건 — 이번 구간은 '확인 끝'으로 적지 "
                "않습니다(상태 파일을 그대로 둡니다). 다음 실행이 같은 구간을 다시 "
                "확인하고, 이미 받아 둔 건은 건너뜁니다.")

    # 실패가 있으면 조용히 성공하지 않습니다 — Actions 를 빨간불로 만듭니다(§0-1).
    return 0 if not failures else 2


def run_backfill_payment_events(bsns_year, out_dir, bgn_de, end_de, cache_dir=None,
                                api_key=None, session=None, log=print, today=None):
    """
    **일회성 백필** — 사람이 지정한 접수일 구간을 한 번 훑습니다(상태 파일 무관).

    왜 필요했나: `run_watch_payment_events()` 는 "한 번 지나간 날짜는 다시 안 훑는" 구조라,
    **첫 실행의 lookback 창보다 앞서 접수된 공시는 영영 들어오지 않습니다.** 실제로
    2026-08-20 접수된 롯데케미칼 배당결정(rcept_no=20260820800655)이 첫 프로덕션 실행
    (2026-08-25경, lookback 3일 → 08-22~08-24)보다 앞서 있어 누락됐고, 오너가 직접
    발견했습니다. 그 구간을 한 번 메우기 위한 경로입니다.

    감시 모드와 **같은 본체**(`_collect_payment_events_in_range`)를 씁니다 — 후보 조회,
    "이미 가진 rcept_no 는 원문을 다시 받지 않기", append-only 저장이 전부 동일합니다.
    따라서 백필 구간이 이미 수집된 날짜와 겹쳐도 DART 에 원문을 다시 요청하지 않습니다.

    🔴 감시 모드와 **다른 점은 상태 파일 갱신 규칙 하나뿐**입니다:
        `last_checked_de = max(기존 값, 이번 백필로 실제 확인을 끝낸 날)`
       — 즉 **절대 뒤로 되돌리지 않습니다**(`merge_last_checked_de()` 참고). 되돌리면
       다음 정기 실행이 이미 확인한 구간을 다시 훑어 DART 에 헛요청을 반복합니다(§0-3-2).
       상태 파일이 아예 없으면(백필이 먼저 도는 경우) 되돌릴 기존 값이 없으므로 이번
       구간의 끝 날짜로 새로 씁니다.

    ⚠️ `end_de` 가 오늘(KST) 이후면 실행을 거부합니다. 오늘은 아직 하루가 안 끝나 접수가
       더 들어올 수 있는데 '확인 끝'으로 적으면 그날 나머지 공시를 영영 놓칩니다(§0-1).

    반환: 프로세스 종료코드(0=정상, 2=원문 실패가 있었음).
    """
    cache_dir = cache_dir or out_dir
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    events_path = payment_events_path(out_dir, bsns_year)
    raw_path = payment_events_raw_path(out_dir, bsns_year)
    state_path = payment_state_path(cache_dir, bsns_year)

    # ── 구간 검증 (지어내거나 조용히 보정하지 않습니다 — §0-1) ───────────────
    start_date = _parse_de(bgn_de)
    end_date = _parse_de(end_de)
    if start_date is None or end_date is None:
        raise DartPaymentFatalError(
            f"백필 구간을 YYYYMMDD 로 읽지 못했습니다(--bgn-de={bgn_de!r}, "
            f"--end-de={end_de!r}). 예: --bgn-de 20260801 --end-de 20260824")
    if start_date > end_date:
        raise DartPaymentFatalError(
            f"백필 시작일({bgn_de})이 종료일({end_de})보다 뒤입니다 — 구간을 다시 확인하세요.")

    today = today or _now_kst().date()
    if end_date >= today:
        raise DartPaymentFatalError(
            f"백필 종료일({end_de})이 오늘(KST {today:%Y%m%d}) 이후입니다. 오늘은 아직 하루가 "
            "끝나지 않아 접수가 더 들어올 수 있는데 '확인 끝'으로 적으면 그날 나머지 공시를 "
            "영영 놓칩니다 — 어제 이전 날짜를 주세요.")

    log("─" * 78)
    log(f"🧹 배당결정 공시 **일회성 백필** — 접수일 {start_date:%Y-%m-%d} ~ "
        f"{end_date:%Y-%m-%d} 구간을 상태 파일과 무관하게 한 번 훑습니다.")

    key = get_api_key(api_key)
    if not key:
        raise DartPaymentFatalError(
            f"환경변수 {DART_API_KEY_ENV} 가 없습니다. 인증키를 코드에 적지 말고 "
            "GitHub Actions Secret / 로컬 환경변수로 넣으세요.")

    state = read_payment_state(state_path, log=log)
    existing_de = state.get("last_checked_de")
    if existing_de:
        log(f"  ℹ️ 기존 상태 파일: last_checked_de={existing_de} "
            "(백필은 이 값을 **뒤로 되돌리지 않습니다**).")

    result = _collect_payment_events_in_range(
        bgn_de, end_de, key, events_path, raw_path, start_date,
        session=session, log=log)
    failures = result["failures"]

    # ── 이번 백필로 "실제로 확인을 끝낸" 날짜 정하기 ─────────────────────────
    if not failures:
        completed_de = end_de
    else:
        first_failed_date = result["first_failed_date"]
        safe_end = (first_failed_date - timedelta(days=1)) if first_failed_date else None
        completed_de = (safe_end.strftime("%Y%m%d")
                        if safe_end is not None and safe_end >= start_date else None)
        if completed_de is None:
            log(f"  ⚠️ 원문 실패 {len(failures):,}건 — 이번 백필로 '확인 끝'이라 말할 수 있는 "
                "구간이 없습니다. 상태 파일을 건드리지 않습니다.")
        else:
            log(f"  ⚠️ 원문 실패 {len(failures):,}건 — 실패한 날의 전날({completed_de})까지만 "
                "확인한 것으로 봅니다.")

    # ── 상태 파일: max(기존, 이번 백필) — 절대 뒤로 가지 않습니다 ────────────
    if completed_de is not None:
        new_de = merge_last_checked_de(existing_de, completed_de, log=log)
        if new_de is not None:
            existing_date = _parse_de(existing_de) if existing_de else None
            if existing_date is not None and start_date > existing_date + timedelta(days=1):
                # 상태를 전진시키면 그 사이 구간은 정기 감시가 영영 안 훑습니다 —
                # 조용히 넘기지 않고 사람이 보게 남깁니다(§0-1).
                log(f"  ⚠️ 주의: 기존 상태({existing_de}) 다음 날부터 이번 백필 시작일"
                    f"({bgn_de}) 전날까지의 구간은 이번 백필이 확인하지 않았습니다. "
                    f"상태를 {new_de} 로 전진시키면 정기 감시는 그 구간을 훑지 않습니다 "
                    "— 필요하면 그 구간으로 백필을 한 번 더 돌리세요.")
            write_payment_state(state_path, new_de)
            log(f"   상태 파일 갱신: {state_path} (last_checked_de={new_de}, "
                f"총 {result['total']:,}건)")

    log(f"🧹 백필 종료 — 이번 실행 추가 {result['new_records']:,}건, "
        f"원문 실패 {len(failures):,}건.")
    return 0 if not failures else 2


def _collect_payment_events_in_range(bgn_de, end_de, api_key, events_path, raw_path,
                                     range_start_date, session=None, log=print):
    """
    ②~④ **공통 본체** — 감시 모드와 백필 모드가 이 함수 하나를 같이 씁니다(§0-3-10:
    같은 로직을 두 벌 두지 않습니다. 두 벌이면 한쪽만 고쳐지는 사고가 납니다).

    하는 일: 접수일 `bgn_de`~`end_de` 구간의 배당결정 공시를 훑어, **아직 파일에 없는
    rcept_no 만** 원문을 받아 파싱하고 append-only 로 저장합니다.

    🔴 **상태 파일은 이 함수가 건드리지 않습니다.** 상태를 어떻게 전진시킬지는 호출부가
       정합니다 — 감시는 `end_de` 로, 백필은 `max(기존, end_de)` 로 규칙이 다릅니다.

    `range_start_date`: 이 구간의 시작일(date). 접수일을 못 읽은 실패가 생겼을 때
       "이번 구간은 전진시키지 않는다"를 표현하기 위한 기준점입니다.

    반환(dict): {"new_records": int, "failures": [...], "first_failed_date": date|None,
                 "total": int}
    """
    # ── 기존 산출물 읽기 (append-only 의 기준점) ─────────────────────────────
    existing_records, _existing_payload = read_payment_events(events_path, log=log)
    existing_ids = {str(rec.get("rcept_no")) for rec in existing_records
                    if rec.get("rcept_no") is not None}

    # ── ② 배당결정 공시 후보 찾기 ────────────────────────────────────────────
    scan_stats = {}
    candidates = fetch_dividend_decision_disclosures(
        bgn_de, end_de, api_key, session=session, log=log, stats=scan_stats)

    # ── ③ 이미 가진 것은 원문을 받지 않습니다 ────────────────────────────────
    fresh = [item for item in candidates if str(item.get("rcept_no")) not in existing_ids]
    already_have = len(candidates) - len(fresh)
    if already_have:
        log(f"  · 이미 수집해 둔 배당결정 {already_have:,}건은 원문을 다시 받지 않습니다"
            "(rcept_no 기준 — §0-3-2).")

    if not fresh:
        log("ℹ️ 새로 추가할 배당결정 공시가 없습니다.")
        total = _flush_payment_output(events_path, existing_records, [], scan_stats,
                                      bgn_de, end_de, [], log=log)
        return {"new_records": 0, "failures": [], "first_failed_date": None,
                "total": total}

    log(f"  → 이번에 원문을 받을 배당결정 공시: {len(fresh):,}건")

    # ── ④ 원문 받아서 파싱 → append-only 로 추가 ─────────────────────────────
    # 접수일 순서대로 처리합니다(호출부가 "어느 날까지 다 됐는지" 를 정확히 판단하기 위함).
    fresh.sort(key=lambda item: (str(item.get("rcept_dt") or ""),
                                 str(item.get("rcept_no") or "")))

    new_records = []
    failures = []
    first_failed_date = None
    document_requests = 0

    for item in fresh:
        rcept_no = item.get("rcept_no")
        if document_requests:
            polite_sleep()      # §0-3-2 — 요청 사이 딜레이
        try:
            html_text = fetch_disclosure_document(rcept_no, api_key, session=session,
                                                  log=log)
        except DartPaymentFatalError:
            # 키·IP·한도·차단 — 지금까지 받은 것만 저장하고 실행을 중단합니다(재시도 금지).
            log(f"  🛑 치명적 응답을 받아 원문 수집을 여기서 멈춥니다(rcept_no={rcept_no}).")
            _flush_payment_output(events_path, existing_records, new_records, scan_stats,
                                  bgn_de, end_de, failures, log=log)
            raise
        except DartPaymentApiError as e:
            # 이 건 하나만 실패 — 레코드를 만들지 않습니다(값을 지어내지 않기, §0-1).
            # 상태 파일이 이 날짜를 넘어 전진하지 않으므로 다음 실행이 이 건만 다시 받습니다.
            document_requests += 1
            failures.append({"rcept_no": rcept_no, "rcept_dt": item.get("rcept_dt"),
                             "corp_name": item.get("corp_name"), "reason": str(e)})
            log(f"  ⚠️ 원문을 받지 못했습니다(rcept_no={rcept_no}, "
                f"{item.get('corp_name')}): {e}")
            item_date = _parse_de(item.get("rcept_dt"))
            if item_date is not None and (first_failed_date is None
                                          or item_date < first_failed_date):
                first_failed_date = item_date
            elif item_date is None and first_failed_date is None:
                # 접수일을 못 읽으면 "언제까지 안전한지" 판단할 수 없습니다 → 이번 구간은
                # 전진시키지 않습니다(§0-1 — 모르면 확인한 셈 치지 않기).
                first_failed_date = range_start_date
            continue

        document_requests += 1

        # §0-3-3 — 원문은 가공본과 **다른 파일**에 그대로 보관합니다.
        append_raw(raw_path, {
            "rcept_no": rcept_no,
            "rcept_dt": item.get("rcept_dt"),
            "corp_code": item.get("corp_code"),
            "corp_name": item.get("corp_name"),
            "stock_code": item.get("stock_code"),
            "report_nm": item.get("report_nm"),
            "fetched_at_kst": _now_kst().isoformat(),
            "document_html": html_text,
        })

        parsed = parse_dividend_decision_document(html_text, log=log)
        record = build_payment_event_record(item, parsed)
        new_records.append(record)

        status_mark = {PARSE_OK: "✅", PARSE_PARTIAL: "⚠️", PARSE_FAILED: "❌"}.get(
            parsed["parse_status"], "•")
        log(f"    {status_mark} {item.get('corp_name')}({item.get('stock_code')}) "
            f"기준일={record['record_date']} 지급예정일={record['pay_date_expected']} "
            f"1주당={record['dps_common']} [{parsed['parse_status']}]")
        if parsed["missing_labels"]:
            log(f"        · 못 찾은 라벨: {', '.join(parsed['missing_labels'])}")
        for note in parsed["parse_notes"]:
            log(f"        · {note}")

    # ── 저장 (append-only) ───────────────────────────────────────────────────
    total = _flush_payment_output(events_path, existing_records, new_records, scan_stats,
                                  bgn_de, end_de, failures, log=log)
    log(f"   저장: {events_path} (총 {total:,}건, 이번 실행 추가 {len(new_records):,}건, "
        f"원문 실패 {len(failures):,}건)")

    return {"new_records": len(new_records), "failures": failures,
            "first_failed_date": first_failed_date, "total": total}


def _flush_payment_output(events_path, existing_records, new_records, scan_stats,
                          bgn_de, end_de, failures, log=print):
    """
    append-only 저장. 기존 레코드 + 이번에 새로 만든 레코드를 원자적으로 씁니다.

    ⚠️ 기존 레코드를 **고치거나 지우지 않습니다.** 이 함수는 뒤에 이어 붙이기만 합니다.

    ⚠️ 추가된 레코드가 하나도 없고 파일이 이미 있으면 **다시 쓰지 않습니다.** summary 의
       generated_at 만 바뀐 파일을 매일 커밋하면, 레코드가 쌓일수록 같은 내용의 큰 파일이
       저장소 이력에 매일 한 벌씩 더 들어갑니다(§0-3-2 와 같은 취지 — 불필요한 부하).
       "이 구간을 확인했다"는 사실은 상태 파일이 이미 담고 있습니다.
    """
    merged = list(existing_records) + list(new_records)
    if not new_records and os.path.exists(events_path):
        log(f"  ℹ️ 추가된 레코드가 없어 {os.path.basename(events_path)} 를 다시 쓰지 "
            "않습니다(내용이 같은 파일을 매일 커밋하지 않기 위함입니다).")
        return len(merged)
    payload = {
        "summary": summarize_payment_events(merged, extra={
            "date_range_checked": f"{bgn_de}~{end_de}",
            "new_records_this_run": len(new_records),
            "documents_failed_this_run": len(failures),
            "document_failures": failures,
            "scan_stats": scan_stats,
        }),
        "records": merged,
    }
    _atomic_write_json(events_path, payload)
    return len(merged)


# =============================================================================
# 7. CLI
# =============================================================================
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="DART 수시공시('현금ㆍ현물배당결정') 기반 배당 지급일정 수집기 "
                    "(visible_hand 배당금 모듈). 기존 alotMatter 수집기와 데이터·파일이 "
                    "완전히 분리돼 있습니다.")
    parser.add_argument("--year", required=True,
                        help="산출물 파일 이름에 쓸 연도 4자리 (예: 2026). "
                             "⚠️ 조회 조건이 아닙니다 — 조회는 접수일 구간으로만 합니다.")
    parser.add_argument("--out-dir", default="data", help="산출물 디렉터리(기본: data)")
    parser.add_argument("--cache-dir", default=os.path.join("data", "cache"),
                        help="상태 파일 디렉터리(기본: data/cache)")
    parser.add_argument("--lookback-days", type=int, default=3,
                        help="상태 파일이 아직 없을 때(최초 실행) 며칠 전부터 확인할지(기본 3). "
                             "⚠️ 백필 모드(--bgn-de/--end-de)에서는 쓰이지 않습니다.")
    # ── 일회성 백필 모드 ─────────────────────────────────────────────────────
    # 둘 다 주면 백필, 둘 다 안 주면 기존 감시 모드입니다(하나만 주면 아래에서 거부).
    parser.add_argument("--bgn-de", default=None,
                        help="[백필] 훑을 접수일 시작(YYYYMMDD). --end-de 와 **함께** 줘야 "
                             "합니다. 주면 상태 파일과 무관하게 이 구간을 한 번 훑습니다"
                             "(상태 파일의 last_checked_de 는 뒤로 되돌아가지 않습니다).")
    parser.add_argument("--end-de", default=None,
                        help="[백필] 훑을 접수일 끝(YYYYMMDD, 어제 이전). --bgn-de 와 함께.")
    parser.add_argument("--api-key", default=None,
                        help=f"DART 인증키(기본: 환경변수 {DART_API_KEY_ENV}). "
                             "⚠️ 명령줄에 적으면 프로세스 목록에 노출될 수 있으니 되도록 "
                             "환경변수를 쓰세요.")
    # ⚠️ `--universe` 는 **일부러 없습니다.** 이 경로의 장점이 "정기보고서 기반 유니버스에
    #    아직 없는 회사의 배당결정도 잡힌다"는 것이라, 유니버스로 미리 거르면 그 장점이
    #    통째로 사라집니다(설계 의도 — 파일 상단 주석 참고).
    args = parser.parse_args(argv)

    # 한쪽만 준 것은 거의 확실히 실수입니다. 조용히 감시 모드로 돌면 사람이 의도한 구간이
    # 아니라 "어제까지 3일"만 훑고 끝나 버립니다 — 무엇이 잘못됐는지 말하고 멈춥니다(§0-1).
    if bool(args.bgn_de) != bool(args.end_de):
        parser.error(
            "--bgn-de 와 --end-de 는 **둘 다** 주거나 둘 다 주지 않아야 합니다"
            f"(받은 값: --bgn-de={args.bgn_de!r}, --end-de={args.end_de!r}). "
            "둘 다 주면 그 구간을 한 번 훑는 백필 모드, 둘 다 없으면 기존 감시 모드입니다.")

    is_backfill = bool(args.bgn_de and args.end_de)
    try:
        if is_backfill:
            return run_backfill_payment_events(
                args.year, args.out_dir, args.bgn_de, args.end_de,
                cache_dir=args.cache_dir, api_key=args.api_key, log=print)
        return run_watch_payment_events(
            args.year, args.out_dir, cache_dir=args.cache_dir,
            lookback_days=args.lookback_days, api_key=args.api_key, log=print)
    except (DartPaymentFatalError, DartPaymentApiError) as e:
        # 스택트레이스 대신 사람이 읽을 문장으로 끝내되, '조용히 성공'하지 않습니다.
        # ⚠️ 상태 파일은 갱신되지 않았거나 성공한 날까지만 전진한 상태입니다 — 다음 실행이
        #    남은 구간을 다시 확인합니다. 백필이 실패해도 기존 상태는 뒤로 가지 않습니다.
        print(f"🛑 배당결정 공시 {'일회성 백필을' if is_backfill else '감시를'} "
              f"중단했습니다 — {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
