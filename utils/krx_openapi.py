"""
utils/krx_openapi.py
KRX OPEN API(https://openapi.krx.co.kr) 최소 클라이언트 — 매크로 위험지표 2종 전용.

⚠️ 왜 이 파일이 생겼나 (2026-08-10, TASK #70 / MACRO_REDESIGN_PROPOSAL.md §5 구현순서 3~4번)
   매크로 8개 지표 중 `VKOSPI_Skew`·`Synthetic_Futures` 두 자리는 라벨만 파생상품이고
   실제 입력은 '변동성'과 '환율 레벨'이었습니다(§0-3-1 위반). 이 모듈은 그 두 지표를
   진짜 실측값으로 바꾸기 위해 KRX가 공식 제공하는 무료 OPEN API를 호출합니다.
     - VKOSPI 지수값        ← 지수 > 파생상품지수 시세정보 (idx/drvprod_dd_trd)
     - KOSPI200 지수 종가   ← 지수 > KOSPI 시리즈 일별시세정보 (idx/kospi_dd_trd)
     - KOSPI200 선물 종가   ← 파생상품 > 선물 일별매매정보(주식선물外) (drv/fut_bydd_trd)
   선물 베이시스 = (선물 종가 − KOSPI200 지수 종가). 실측 2개의 순수 뺄셈이라
   §0-1 "계산값 예외" 조건(무위험이자율·잔존만기 같은 가정이 들어가지 않음)을 충족합니다.

────────────────────────────────────────────────────────────────────────────────
📌 왜 pykrx-openapi 라이브러리를 쓰지 않고 직접 구현했나 (판단 근거, 2026-08-10)
────────────────────────────────────────────────────────────────────────────────
후보였던 `pykrx-openapi`(raccoonyy, PyPI)의 실제 소스를 GitHub raw로 전부 읽고 비교한 결과
**직접 구현**을 택했습니다. 이유는 다음 4가지이며, 특히 1번은 기능적 결함입니다.

 1. **인증키 전달 위치가 공식 문서와 다릅니다.** KRX 공식 서비스 상세 페이지에는
    "(Request 헤더에 인증키 값을 AUTH_KEY 필드에 추가하여 전달)"이라고 명시돼 있는데,
    pykrx-openapi(`client.py::_make_request`)는 `params={"AUTH_KEY": ..., "basDd": ...}`로
    **쿼리스트링에** 넣습니다. 동작 여부를 떠나, 인증키가 URL에 실리면 서버 접근로그·프록시·
    예외 메시지(요청 URL이 그대로 찍힘)에 키가 남습니다. 이 프로젝트는 인증키를 코드·문서·
    로그 어디에도 남기지 않기로 했으므로(오너 지침) 헤더 방식이 맞습니다.
 2. **필요한 건 31개 엔드포인트 중 3개**이고, 그 3개는 `requests.get` 한 번씩입니다.
    래퍼를 통째로 들이는 비용 대비 이득이 없습니다.
 3. **의존성 최소 유지 관례.** 이 저장소는 requests/beautifulsoup4/pandas/FinanceDataReader
    정도만 쓰고, requirements.txt에 "선택 패키지는 일부러 넣지 않는다"는 원칙을 적어두었습니다.
    새 의존성은 Streamlit Cloud 빌드와 GitHub Actions 전체 파이프라인에 영향을 줍니다.
 4. **소규모 신생 프로젝트**(스타 12개)이고, 이 개발 샌드박스는 외부 네트워크가 막혀 있어
    실제 응답으로 검증할 수 없습니다. 검증 못 한 코드를 통째로 신뢰하기보다, 우리가 읽고
    이해한 60줄을 직접 들고 있는 편이 장애 원인 추적에 유리합니다.

 다만 **엔드포인트 경로·파라미터명은 pykrx-openapi에서, 응답 필드명은 krx-rs에서** 확인했고
 두 구현이 서로 독립적으로 같은 값을 쓰고 있어 신뢰도가 올라갑니다(출처는 아래 표 참고).

────────────────────────────────────────────────────────────────────────────────
📌 확인한 것 / 확인 못 한 것 (정직하게 구분 — 실서버 호출은 아직 한 번도 못 했습니다)
────────────────────────────────────────────────────────────────────────────────
[확인됨 — 공식 페이지]
  · 인증키는 **HTTP 요청 헤더 `AUTH_KEY`** 로 전달. 요청 파라미터는 `basDd`(YYYYMMDD).
    출처: https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES005_S2.cmd?BO_ID=ilaVYOabbaicHbKTsqga
    (페이지 본문 "샘플 인증키 (Request 헤더에 인증키 값을 AUTH_KEY 필드에 추가하여 전달)")
  · 서비스 목록·제공 시작일(2010-01-04~), 서비스별 개별 이용신청 필요.
[확인됨 — 제3자 구현 2건이 일치]
  · Base URL `https://data-dbg.krx.co.kr/svc/apis/{category}/{endpoint}`, 응답 최상위 키
    `OutBlock_1`(레코드 배열). (pykrx-openapi `constants.py`/`client.py`)
  · 응답 필드명(아래 FIELD_* 상수). (krx-rs `src/data/index.rs`, `src/data/derivative.rs` —
    serde rename 으로 실제 JSON 키가 그대로 박혀 있음)
[❌ 확인 못 함 — 실제 응답을 받아본 적이 없음]
  · **VKOSPI의 정확한 지수명 문자열**(`IDX_NM` 값). 파생상품지수 API는 숫자 '지수 코드'가
    아니라 계열구분(`IDX_CLSS`)+지수명(`IDX_NM`) 문자열로 구분됩니다. 로그인해야 필드표가
    렌더링돼 목록을 못 봤습니다 → 아래 `VKOSPI_NAME_CANDIDATES` + "이름에 '변동성' 포함"
    보조 규칙으로 찾고, **못 찾으면 값을 지어내지 않고 응답에 실제로 들어있는 지수명 전부를
    로그로 출력**합니다(오너가 Actions 로그를 보고 확정하면 그때 상수로 못 박습니다).
  · **KOSPI200 선물의 근월물 식별 방법.** 선물은 만기가 있어 종목코드가 매달 바뀝니다.
    `ISU_NM`의 만기 표기 형식을 확인하지 못해, 파싱 대신 "그 상품군에서 거래량(ACC_TRDVOL)이
    가장 많은 종목"을 근월물로 봅니다(근월물이 원월물보다 거래량이 압도적으로 많다는 것은
    선물시장의 구조적 성질입니다). 선택된 종목명·코드·거래량을 매번 로그에 남기므로
    첫 실서버 실행 로그로 검증할 수 있습니다.
  · KOSPI200 지수의 `IDX_NM` 문자열도 동일하게 후보 매칭 + 로그 출력 방식입니다.

────────────────────────────────────────────────────────────────────────────────
📌 실패는 전부 "그 지표만 None" 으로 끝납니다 (§0-1)
────────────────────────────────────────────────────────────────────────────────
인증키 미설정 / 미승인(401) / 네트워크 오류 / 필드 없음 / 후보 지수명 불일치 —
어떤 이유로든 값을 못 얻으면 **프록시로 조용히 폴백하지 않고** None을 돌려줍니다.
호출부(scrape_daily.py)의 기존 `unavailable_items` 로직이 그 지표를 배점에서 통째로 빼며,
`compute_final_score()`가 남은 지표로 가중치를 재정규화하므로 전체 수집은 죽지 않습니다.

📌 크롤링 매너 (§0-3-2)
  · 1회 실행당 최대 호출 수 = 거래일 탐색 최대 8회 + 파생지수 1회 + 선물 1회 = **10회 이하**.
    (KRX 제한은 인증키당 1일 10,000회)
  · 호출 사이 KRX_REQUEST_DELAY_SEC 만큼 쉬고, 4xx(인증·권한·요청오류)는 **재시도하지 않습니다.**
    네트워크/5xx만 1회 재시도합니다. 짧은 간격 폴링·무한 재시도 금지.

📌 데이터 시점 (§0-3-1 후행지표 전용 원칙과의 관계)
  KRX OPEN API는 **전일(T-1) 확정치를 익일 08:00에** 공개합니다. 우리 수집은 KST 16:05라
  '오늘' 기준으로 조회하면 빈 응답이 옵니다. 그래서 조회일부터 하루씩 거슬러 올라가며
  데이터가 있는 가장 최근 거래일을 찾고, **그 기준일(as-of)을 값과 함께 반환**합니다.
  호출부는 이 as-of를 CSV에 같이 저장해야 합니다 — 서로 다른 지연을 가진 값을 한 행에 섞어
  놓고 지연을 안 적으면 그것 자체가 §0-1 위반입니다.
"""
import os
import time

import requests

# =============================================================================
# 1. 엔드포인트·요청 규격 (출처: 위 파일 상단 "확인됨" 표 참고)
# =============================================================================
KRX_OPENAPI_BASE = "https://data-dbg.krx.co.kr/svc/apis"

# 인증키는 환경변수에서만 읽습니다. 코드·문서·로그 어디에도 값 자체를 남기지 않습니다.
KRX_API_KEY_ENV = "KRX_OPENAPI_KEY"

# 인증키를 실어 보내는 HTTP 헤더 이름 (공식 페이지 명시)
KRX_AUTH_HEADER = "AUTH_KEY"

# 기준일자 파라미터 이름 (YYYYMMDD)
KRX_DATE_PARAM = "basDd"

# 응답 최상위 레코드 배열 키
KRX_RESULT_KEY = "OutBlock_1"

# (카테고리, 엔드포인트, 한글 서비스명) — 오너가 이용신청·승인 완료한 4개만 정의합니다.
# ⚠️ "options"는 이번 단계(#70)에서 **호출하지 않습니다.** 아래 "Put_OTM_OI 미착수 사유" 참고.
KRX_ENDPOINTS = {
    "kospi_index": ("idx", "kospi_dd_trd", "KOSPI 시리즈 일별시세정보"),
    "derivative_index": ("idx", "drvprod_dd_trd", "파생상품지수 시세정보"),
    "futures": ("drv", "fut_bydd_trd", "선물 일별매매정보(주식선물外)"),
    "options": ("drv", "opt_bydd_trd", "옵션 일별매매정보(주식옵션外)"),
}

# -----------------------------------------------------------------------------
# 응답 필드명 (krx-rs 의 serde rename 에서 확인 — 실서버 응답으로는 미검증)
# -----------------------------------------------------------------------------
FIELD_BASE_DATE = "BAS_DD"        # 기준일자
FIELD_INDEX_CLASS = "IDX_CLSS"    # 계열구분
FIELD_INDEX_NAME = "IDX_NM"       # 지수명
FIELD_INDEX_CLOSE = "CLSPRC_IDX"  # 지수 종가
FIELD_ISSUE_CODE = "ISU_CD"       # 종목코드
FIELD_ISSUE_NAME = "ISU_NM"       # 종목명
FIELD_PRODUCT_NAME = "PROD_NM"    # 상품명
FIELD_CLOSE_PRICE = "TDD_CLSPRC"  # (선물/옵션) 종가
FIELD_SPOT_PRICE = "SPOT_PRC"     # (선물) 현물가격 — 교차검증용으로만 씁니다
FIELD_TRADE_VOLUME = "ACC_TRDVOL"  # 누적 거래량
FIELD_OPEN_INTEREST = "ACC_OPNINT_QTY"  # 미결제약정수량 (이번 단계 미사용)

# =============================================================================
# 2. 지수/종목 이름 후보 (❌ 실제 응답 미확인 — 못 찾으면 지어내지 않고 로그만 남깁니다)
# =============================================================================
# VKOSPI = "코스피 200 변동성지수"(V-KOSPI 200). KRX가 산출·공표하는 파생상품지수 계열입니다.
# 표기 흔들림(띄어쓰기·하이픈·영문)을 흡수하려고 후보를 여러 개 둡니다. 비교 시에는
# 공백을 모두 제거하고 대문자로 접어 비교합니다(_normalize_name 참고).
VKOSPI_NAME_CANDIDATES = (
    "코스피 200 변동성지수",
    "코스피200 변동성지수",
    "코스피 200 변동성 지수",
    "V-KOSPI 200",
    "VKOSPI 200",
    "VKOSPI",
)
# 후보 어느 것과도 정확히 일치하지 않을 때만 쓰는 보조 규칙:
# "지수명에 '변동성'이 들어간 지수가 **정확히 하나뿐**이면 그것을 VKOSPI로 본다."
# 둘 이상이면 어느 쪽인지 단정할 수 없으므로 **고르지 않고 None**을 돌려줍니다.
VKOSPI_NAME_FALLBACK_KEYWORD = "변동성"

# KOSPI200 지수는 부분일치를 쓰지 않습니다 — "코스피 200 TR", "코스피 200 중소형주" 등
# 이름이 겹치는 파생 지수가 많아 부분일치로 잘못 집을 위험이 큽니다. 정확 일치만 허용합니다.
KOSPI200_NAME_CANDIDATES = (
    "코스피 200",
    "코스피200",
    "KOSPI 200",
    "KOSPI200",
)

# KOSPI200 선물의 '상품명'(PROD_NM) 후보. 정확 일치가 없으면
# "상품명에 '코스피200'과 '선물'이 함께 들어가고 '미니'/'선물지수'가 없는 것"을 씁니다.
KOSPI200_FUTURES_PRODUCT_CANDIDATES = (
    "코스피200 선물",
    "코스피 200 선물",
    "KOSPI200 F",
)
# 보조 규칙에서 반드시 포함돼야 하는 조각 / 절대 포함되면 안 되는 조각
FUTURES_REQUIRED_TOKENS = ("코스피200", "선물")
# '미니 코스피200 선물'(계약 크기 1/5)은 별도 상품이라 섞이면 안 됩니다.
# '코스피200 위클리'도 만기 구조가 달라 제외합니다.
FUTURES_EXCLUDED_TOKENS = ("미니", "위클리", "야간", "섹터")

# =============================================================================
# 3. 크롤링 매너 상수 (§0-3-2)
# =============================================================================
KRX_REQUEST_TIMEOUT_SEC = 15      # 응답이 이보다 늦으면 포기(무한 대기 금지)
KRX_REQUEST_DELAY_SEC = 0.5       # 연속 호출 사이 최소 간격
KRX_NETWORK_RETRY = 1             # 네트워크/5xx 오류에 한해 1회만 재시도
KRX_RETRY_DELAY_SEC = 2.0         # 재시도 전 대기
# 조회일부터 며칠까지 거슬러 올라가며 '데이터가 있는 거래일'을 찾을지.
# 8일 = 주말(2) + 설/추석 연휴(최대 5~6)를 덮는 최소치. 이보다 오래된 값은 '오늘의 위험'을
# 말하기에 너무 낡았다고 보고 산출 불가(None)로 둡니다.
KRX_MAX_LOOKBACK_DAYS = 8


class KrxOpenApiError(RuntimeError):
    """KRX OPEN API 호출 실패. 메시지에 인증키를 절대 포함하지 않습니다."""


# =============================================================================
# 4. 저수준 유틸
# =============================================================================
def get_api_key(explicit=None):
    """
    인증키를 반환합니다. 없으면 None (예외를 던지지 않습니다 — 키가 없는 것은 '오류'가 아니라
    '이 지표를 산출할 수 없는 상태'이고, 호출부가 해당 지표만 빼면 되기 때문입니다).
    """
    if explicit:
        return explicit
    key = os.environ.get(KRX_API_KEY_ENV)
    return key.strip() if key and key.strip() else None


def _normalize_name(value):
    """이름 비교용 정규화: 공백 전부 제거 + 대문자 접기. (None-safe)"""
    if value is None:
        return ""
    return "".join(str(value).split()).upper()


def to_float(value):
    """
    KRX 응답 값(문자열)을 float로. 빈 값·'-'·파싱 불가는 None.
    ⚠️ 0.0으로 채우지 않습니다 — '없음'과 '0'은 완전히 다른 사실입니다(§0-1).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = float(value)
        return None if f != f else f          # NaN 방어
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "N/A", "null", "None"):
        return None
    try:
        f = float(text)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def to_date_param(date_key):
    """'YYYY-MM-DD' 또는 'YYYYMMDD' → 'YYYYMMDD'. 형식이 아니면 ValueError."""
    text = str(date_key).strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"기준일자 형식이 올바르지 않습니다(YYYYMMDD 필요): {date_key!r}")
    return text


# =============================================================================
# 5. HTTP 호출
# =============================================================================
def _http_get_json(url, headers, params, timeout, session):
    """
    실제 네트워크 호출 지점. **테스트에서는 이 함수 하나만 가짜로 바꿔 end-to-end를 검증합니다**
    (미국주식 수집기 개발 때와 같은 패턴 — 실제 API 키·네트워크 없이 배선을 확인하기 위함).
    반환: (status_code, parsed_json_or_None)
    """
    getter = session.get if session is not None else requests.get
    res = getter(url, headers=headers, params=params, timeout=timeout)
    status = getattr(res, "status_code", None)
    try:
        payload = res.json()
    except Exception:
        payload = None
    return status, payload


def fetch_daily(endpoint_key, bas_dd, api_key=None, session=None):
    """
    KRX OPEN API 단건 조회. 성공하면 레코드(dict) 리스트를, 데이터가 없으면 빈 리스트를 반환.
    실패는 전부 KrxOpenApiError 로 던집니다(호출부가 지표별로 잡아서 None 처리).

    ⚠️ 인증키는 URL이 아니라 헤더로만 보냅니다(공식 규격 + 로그 유출 방지).
    """
    if endpoint_key not in KRX_ENDPOINTS:
        raise KrxOpenApiError(f"정의되지 않은 엔드포인트: {endpoint_key}")
    category, endpoint, service_name = KRX_ENDPOINTS[endpoint_key]

    key = get_api_key(api_key)
    if not key:
        raise KrxOpenApiError(
            f"환경변수 {KRX_API_KEY_ENV} 가 없어 '{service_name}' 를 조회할 수 없습니다. "
            "값을 지어내지 않고 해당 지표를 산출 불가로 둡니다."
        )

    date_param = to_date_param(bas_dd)
    url = f"{KRX_OPENAPI_BASE}/{category}/{endpoint}"
    headers = {KRX_AUTH_HEADER: key, "Accept": "application/json"}
    params = {KRX_DATE_PARAM: date_param}

    last_error = None
    for attempt in range(KRX_NETWORK_RETRY + 1):
        try:
            status, payload = _http_get_json(
                url, headers, params, KRX_REQUEST_TIMEOUT_SEC, session
            )
        except Exception as e:                      # 네트워크/타임아웃 등
            last_error = f"네트워크 오류: {type(e).__name__}"
            if attempt < KRX_NETWORK_RETRY:
                time.sleep(KRX_RETRY_DELAY_SEC)
                continue
            raise KrxOpenApiError(f"'{service_name}' 조회 실패 — {last_error}")

        # --- 4xx: 재시도하지 않습니다 (§0-3-2). 원인별로 사람이 읽을 메시지를 남깁니다. ---
        if status in (401, 403):
            raise KrxOpenApiError(
                f"'{service_name}' 인증 실패(HTTP {status}). 인증키가 유효한지, 그리고 "
                f"이 서비스에 대한 **개별 이용신청이 승인**됐는지 확인하세요 "
                "(KRX는 키 발급과 서비스별 승인이 별개입니다). 재시도하지 않고 중단합니다."
            )
        if status == 429:
            raise KrxOpenApiError(
                f"'{service_name}' 호출 한도 초과(HTTP 429). 재시도하지 않고 중단합니다 "
                "— 한도는 인증키당 1일 10,000회입니다."
            )
        if status is not None and 400 <= status < 500:
            raise KrxOpenApiError(f"'{service_name}' 요청 오류(HTTP {status}). 재시도하지 않습니다.")

        if status is not None and status >= 500:
            last_error = f"서버 오류(HTTP {status})"
            if attempt < KRX_NETWORK_RETRY:
                time.sleep(KRX_RETRY_DELAY_SEC)
                continue
            raise KrxOpenApiError(f"'{service_name}' 조회 실패 — {last_error}")

        if status != 200:
            raise KrxOpenApiError(f"'{service_name}' 예상치 못한 응답 상태: {status}")

        if not isinstance(payload, dict):
            raise KrxOpenApiError(f"'{service_name}' 응답이 JSON 객체가 아닙니다.")
        if KRX_RESULT_KEY not in payload:
            raise KrxOpenApiError(
                f"'{service_name}' 응답에 '{KRX_RESULT_KEY}' 가 없습니다 "
                f"(받은 최상위 키: {sorted(payload.keys())}). 응답 규격이 바뀐 것일 수 있습니다."
            )
        rows = payload[KRX_RESULT_KEY]
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise KrxOpenApiError(f"'{service_name}' 의 {KRX_RESULT_KEY} 가 배열이 아닙니다.")
        return [r for r in rows if isinstance(r, dict)]

    raise KrxOpenApiError(f"'{service_name}' 조회 실패 — {last_error}")   # 도달 불가(방어)


# =============================================================================
# 6. 레코드 선택기 — "못 찾으면 고르지 않는다"
# =============================================================================
def list_index_names(rows):
    """응답에 실제로 들어있는 지수명 목록(중복 제거, 원문 그대로). 로그 출력용."""
    seen = []
    for row in rows or []:
        name = row.get(FIELD_INDEX_NAME)
        if name and name not in seen:
            seen.append(name)
    return seen


def select_index_row(rows, name_candidates, fallback_keyword=None):
    """
    지수명(IDX_NM)으로 한 행을 고릅니다.

    반환: (row 또는 None, 사람이 읽을 설명 문자열)
      ① 후보 이름과 정확히 일치(공백 무시·대소문자 무시)하는 행이 **딱 하나**면 그것.
      ② 없으면, fallback_keyword 가 주어졌을 때만 부분일치를 시도하되 역시 **딱 하나**일 때만.
      ③ 0개거나 2개 이상이면 **고르지 않고 None** (지어내지 않기 / 잘못 집지 않기).
    """
    if not rows:
        return None, "응답에 레코드가 없습니다."

    normalized_candidates = {_normalize_name(c) for c in name_candidates}
    exact = [r for r in rows if _normalize_name(r.get(FIELD_INDEX_NAME)) in normalized_candidates]
    if len(exact) == 1:
        return exact[0], f"지수명 정확일치: {exact[0].get(FIELD_INDEX_NAME)!r}"
    if len(exact) > 1:
        names = [r.get(FIELD_INDEX_NAME) for r in exact]
        return None, f"후보 이름에 정확히 일치하는 지수가 {len(exact)}개라 하나로 특정할 수 없습니다: {names}"

    if fallback_keyword:
        key = _normalize_name(fallback_keyword)
        partial = [r for r in rows if key and key in _normalize_name(r.get(FIELD_INDEX_NAME))]
        if len(partial) == 1:
            return partial[0], (
                f"지수명 부분일치('{fallback_keyword}' 포함, 유일): "
                f"{partial[0].get(FIELD_INDEX_NAME)!r} — 상수로 못 박을 것"
            )
        if len(partial) > 1:
            names = [r.get(FIELD_INDEX_NAME) for r in partial]
            return None, (
                f"'{fallback_keyword}' 를 포함한 지수가 {len(partial)}개라 어느 것인지 단정할 수 "
                f"없어 고르지 않았습니다: {names}"
            )

    return None, f"일치하는 지수를 찾지 못했습니다. 응답에 있던 지수명: {list_index_names(rows)}"


def select_front_month_future(rows):
    """
    KOSPI200 선물의 **근월물** 레코드를 고릅니다.

    ⚠️ 근월물 판정 근거: `ISU_NM`의 만기 표기 형식을 확인하지 못해 만기를 파싱하지 않고,
       "같은 상품군 안에서 누적 거래량(ACC_TRDVOL)이 가장 많은 종목"을 근월물로 봅니다.
       근월물이 원월물보다 거래량이 압도적으로 많은 것은 선물시장의 구조적 성질이지만,
       이건 **관측값을 고르는 규칙**이지 값을 만들어내는 게 아닙니다. 선택 결과(종목명·코드·
       거래량)를 항상 로그로 남기므로 첫 실서버 실행에서 검증할 수 있습니다.

    반환: (row 또는 None, 설명 문자열)
    """
    if not rows:
        return None, "응답에 레코드가 없습니다."

    normalized_candidates = {_normalize_name(c) for c in KOSPI200_FUTURES_PRODUCT_CANDIDATES}
    matched = [r for r in rows if _normalize_name(r.get(FIELD_PRODUCT_NAME)) in normalized_candidates]
    how = "상품명 정확일치"

    if not matched:
        required = [_normalize_name(t) for t in FUTURES_REQUIRED_TOKENS]
        excluded = [_normalize_name(t) for t in FUTURES_EXCLUDED_TOKENS]
        matched = [
            r for r in rows
            if all(t in _normalize_name(r.get(FIELD_PRODUCT_NAME)) for t in required)
            and not any(t in _normalize_name(r.get(FIELD_PRODUCT_NAME)) for t in excluded)
        ]
        how = f"상품명 부분일치({'+'.join(FUTURES_REQUIRED_TOKENS)}, 제외: {'/'.join(FUTURES_EXCLUDED_TOKENS)})"

    if not matched:
        products = []
        for r in rows:
            p = r.get(FIELD_PRODUCT_NAME)
            if p and p not in products:
                products.append(p)
        return None, f"KOSPI200 선물 상품을 찾지 못했습니다. 응답에 있던 상품명: {products}"

    # 종가를 못 읽는 행은 애초에 쓸 수 없으므로 제외합니다.
    usable = [r for r in matched if to_float(r.get(FIELD_CLOSE_PRICE)) is not None]
    if not usable:
        return None, (
            f"{how} 로 {len(matched)}개 종목을 찾았지만 종가({FIELD_CLOSE_PRICE})를 읽을 수 있는 "
            "행이 하나도 없습니다."
        )

    # 거래량이 아예 안 읽히면 근월물 판정 근거가 없으므로 고르지 않습니다.
    with_volume = [(r, to_float(r.get(FIELD_TRADE_VOLUME))) for r in usable]
    with_volume = [(r, v) for r, v in with_volume if v is not None]
    if not with_volume:
        return None, (
            f"{how} 로 종목은 찾았지만 거래량({FIELD_TRADE_VOLUME})을 읽을 수 없어 "
            "근월물을 판정할 수 없습니다(임의로 아무 종목이나 고르지 않습니다)."
        )

    best_row, best_vol = max(with_volume, key=lambda pair: pair[1])
    return best_row, (
        f"{how} / 근월물=거래량 최대: {best_row.get(FIELD_ISSUE_NAME)!r} "
        f"({best_row.get(FIELD_ISSUE_CODE)}), 거래량 {best_vol:,.0f}, "
        f"후보 {len(with_volume)}종목 중 선택"
    )


# =============================================================================
# 7. 상위 수집 함수 — scrape_daily.py 가 이것 하나만 부르면 됩니다
# =============================================================================
def _shift_date_param(date_param, days_back):
    """'YYYYMMDD' 에서 days_back 일 뺀 'YYYYMMDD'. (달력일 기준 — 휴장일은 빈 응답으로 걸러짐)"""
    from datetime import datetime, timedelta
    dt = datetime.strptime(date_param, "%Y%m%d") - timedelta(days=days_back)
    return dt.strftime("%Y%m%d")


def collect_krx_risk_inputs(date_key, api_key=None, session=None,
                            max_lookback_days=KRX_MAX_LOOKBACK_DAYS):
    """
    VKOSPI 지수값과 KOSPI200 선물 베이시스를 **실측으로** 수집합니다.

    반환(dict) — 어떤 실패에도 예외를 던지지 않습니다:
      {
        "api_key_present": bool,
        "as_of": "YYYY-MM-DD" 또는 None,   # 값의 실제 기준 거래일
        "vkospi_level":  float 또는 None,  # VKOSPI 지수 종가 (레벨 그 자체)
        "futures_basis": float 또는 None,  # 선물 종가 − KOSPI200 지수 종가
        "kospi200_close": float 또는 None,
        "futures_close": float 또는 None,
        "logs":   [str, ...],   # 진행 상황(정상 흐름 포함)
        "errors": [str, ...],   # 산출 불가 사유
      }
    """
    result = {
        "api_key_present": False,
        "as_of": None,
        "vkospi_level": None,
        "futures_basis": None,
        "kospi200_close": None,
        "futures_close": None,
        "logs": [],
        "errors": [],
    }

    def log(msg):
        result["logs"].append(msg)

    def err(msg):
        result["errors"].append(msg)

    key = get_api_key(api_key)
    if not key:
        err(f"{KRX_API_KEY_ENV} 미설정 — VKOSPI/선물 베이시스를 산출하지 않습니다"
            "(프록시로 대체하지 않고 배점에서 제외).")
        return result
    result["api_key_present"] = True

    try:
        start_param = to_date_param(date_key)
    except ValueError as e:
        err(str(e))
        return result

    # ── ① 데이터가 있는 가장 최근 거래일 찾기 (KOSPI 지수 응답 유무로 판정) ─────────
    # KRX는 전일 확정치를 익일 08:00에 공개하므로, 오늘 날짜로 조회하면 대개 빈 응답입니다.
    kospi_rows = None
    as_of_param = None
    for back in range(0, int(max_lookback_days) + 1):
        probe = _shift_date_param(start_param, back)
        try:
            rows = fetch_daily("kospi_index", probe, api_key=key, session=session)
        except KrxOpenApiError as e:
            err(f"KOSPI 지수 조회 실패({probe}): {e}")
            return result
        if rows:
            kospi_rows, as_of_param = rows, probe
            break
        log(f"{probe} 는 KRX 응답이 비어 있습니다(휴장일이거나 아직 미공개) — 하루 전으로 이동.")
        time.sleep(KRX_REQUEST_DELAY_SEC)

    if not kospi_rows:
        err(f"최근 {max_lookback_days}일 안에 KRX 데이터가 있는 거래일을 찾지 못했습니다 "
            f"(조회 시작일 {start_param}). 값을 지어내지 않고 산출 불가로 둡니다.")
        return result

    result["as_of"] = f"{as_of_param[:4]}-{as_of_param[4:6]}-{as_of_param[6:]}"
    log(f"KRX 기준일(as-of) = {result['as_of']} (조회 요청일 {date_key} 기준 최근 거래일)")

    # ── ② KOSPI200 지수 종가 ──────────────────────────────────────────────────
    k200_row, k200_note = select_index_row(kospi_rows, KOSPI200_NAME_CANDIDATES)
    if k200_row is None:
        err(f"KOSPI200 지수 종가를 찾지 못했습니다 — {k200_note}")
    else:
        close = to_float(k200_row.get(FIELD_INDEX_CLOSE))
        if close is None:
            err(f"KOSPI200 행은 찾았으나 종가 필드({FIELD_INDEX_CLOSE})를 읽을 수 없습니다: "
                f"{sorted(k200_row.keys())}")
        else:
            result["kospi200_close"] = close
            log(f"KOSPI200 종가 = {close} ({k200_note})")

    # ── ③ VKOSPI 지수값 (파생상품지수 시세정보) ────────────────────────────────
    time.sleep(KRX_REQUEST_DELAY_SEC)
    try:
        deriv_rows = fetch_daily("derivative_index", as_of_param, api_key=key, session=session)
    except KrxOpenApiError as e:
        deriv_rows = None
        err(f"파생상품지수 조회 실패: {e}")

    if deriv_rows is not None:
        if not deriv_rows:
            err(f"파생상품지수 응답이 비어 있습니다({result['as_of']}).")
        else:
            v_row, v_note = select_index_row(
                deriv_rows, VKOSPI_NAME_CANDIDATES, fallback_keyword=VKOSPI_NAME_FALLBACK_KEYWORD
            )
            if v_row is None:
                err(f"VKOSPI 지수를 특정하지 못했습니다 — {v_note}")
            else:
                level = to_float(v_row.get(FIELD_INDEX_CLOSE))
                if level is None:
                    err(f"VKOSPI 행은 찾았으나 종가 필드({FIELD_INDEX_CLOSE})를 읽을 수 없습니다: "
                        f"{sorted(v_row.keys())}")
                elif level <= 0:
                    err(f"VKOSPI 값이 {level} 로 비정상입니다(변동성 지수는 양수) — 사용하지 않습니다.")
                else:
                    result["vkospi_level"] = level
                    log(f"VKOSPI = {level} ({v_note}, 계열={v_row.get(FIELD_INDEX_CLASS)!r})")

    # ── ④ KOSPI200 선물 근월물 종가 → 베이시스 ────────────────────────────────
    time.sleep(KRX_REQUEST_DELAY_SEC)
    try:
        fut_rows = fetch_daily("futures", as_of_param, api_key=key, session=session)
    except KrxOpenApiError as e:
        fut_rows = None
        err(f"선물 일별매매정보 조회 실패: {e}")

    if fut_rows is not None:
        f_row, f_note = select_front_month_future(fut_rows)
        if f_row is None:
            err(f"KOSPI200 선물 근월물을 특정하지 못했습니다 — {f_note}")
        else:
            fut_close = to_float(f_row.get(FIELD_CLOSE_PRICE))
            result["futures_close"] = fut_close
            log(f"KOSPI200 선물 근월물 종가 = {fut_close} ({f_note})")

            if fut_close is None:
                err("선물 근월물 종가를 읽지 못해 베이시스를 계산하지 않습니다.")
            elif result["kospi200_close"] is None:
                err("KOSPI200 지수 종가가 없어 베이시스(선물−지수)를 계산하지 않습니다.")
            else:
                basis = fut_close - result["kospi200_close"]
                result["futures_basis"] = basis
                log(f"선물 베이시스 = 선물 {fut_close} − 지수 {result['kospi200_close']} = {basis:.4f}")

                # 교차검증(§0-3-3): KRX가 같은 행에 실어주는 현물가격(SPOT_PRC)으로 계산한
                # 베이시스와 비교만 해봅니다. **값을 바꾸지는 않습니다** — 어느 쪽이 맞는지
                # 실서버 응답 없이는 단정할 수 없으므로, 차이가 크면 로그로만 알립니다.
                spot = to_float(f_row.get(FIELD_SPOT_PRICE))
                if spot is not None and spot > 0:
                    alt = fut_close - spot
                    if abs(alt - basis) > 1.0:
                        log(f"ℹ️ 교차검증: KRX 제공 현물가({spot}) 기준 베이시스는 {alt:.4f} 로 "
                            f"지수 종가 기준({basis:.4f})과 {abs(alt - basis):.4f} 차이가 납니다. "
                            "저장값은 제안서(§2 #6)대로 '지수 종가' 기준을 그대로 씁니다.")
                    else:
                        log(f"ℹ️ 교차검증 통과: 현물가 기준 베이시스({alt:.4f})와 거의 동일.")

    return result


# =============================================================================
# 8. Put_OTM_OI 를 이번 단계에서 건드리지 않은 이유 (기록)
# =============================================================================
# 조사 결과 옵션 일별매매정보에는 미결제약정 필드 `ACC_OPNINT_QTY` 가 **있는 것으로 보입니다**
# (krx-rs 의 OptionsDailyRecord 에 `미결제약정수량`으로 매핑되어 있음). 그런데 같은 레코드
# 정의에 **행사가격 필드가 없습니다.** 필드는 BAS_DD / ISU_CD / ISU_NM / PROD_NM /
# RGHT_TP_NM(권리구분) / TDD_CLSPRC / TDD_OPNPRC / TDD_HGPRC / TDD_LWPRC / CMPPREVDD_PRC /
# ACC_TRDVOL / ACC_TRDVAL / ACC_OPNINT_QTY / IMP_VOLT / NXTDD_BAS_PRC 뿐입니다.
#
# 즉 "OTM(외가격)"을 가르려면 종목명(ISU_NM) 문자열에서 행사가를 파싱해야 하는데, 그 문자열
# 형식을 실제 응답으로 확인하지 못했습니다. 확인 못 한 형식을 가정해 파싱하면 그 자체가
# 지어내기입니다 → **이번 단계에서는 `Put_OTM_OI` 를 건드리지 않고 옛 프록시 그대로 둡니다.**
#
# 다음 세션 후보 (오너 판단 필요):
#   (가) 첫 실서버 실행 로그에서 옵션 ISU_NM 실제 형식을 확인한 뒤 행사가 파싱 → 진짜 OTM 구분
#   (나) 행사가 없이도 계산 가능한 **풋/콜 미결제약정 비율(Put-Call OI Ratio)** 로 재라벨링
#        (RGHT_TP_NM 로 풋/콜만 갈라 합산하면 되므로 가정이 들어가지 않음. 다만 지표 이름과
#         의미가 바뀌는 것이라 오너 승인이 필요합니다.)
