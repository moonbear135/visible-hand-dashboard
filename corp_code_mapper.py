"""
dividend_module/corp_code_mapper.py
DART 고유번호(corp_code) ↔ 종목코드(stock_code) 매핑 모듈.

────────────────────────────────────────────────────────────────────────────────
📌 이 파일이 왜 필요한가
────────────────────────────────────────────────────────────────────────────────
배당 수집기(`collector_dividend_kr.py`)가 부르는 DART OpenAPI `alotMatter.json`
("배당에 관한 사항")은 **6자리 종목코드가 아니라 DART가 회사마다 부여한 8자리 고유번호
(`corp_code`)** 로만 조회됩니다. 우리 유니버스(코스피+코스닥+코넥스 약 2,700종목)는
종목코드로 관리되므로, 그 사이를 잇는 매핑표가 반드시 있어야 합니다.

DART는 전체 회사의 매핑을 한 번에 주는 벌크 엔드포인트를 제공합니다.
    GET https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={key}
응답은 **ZIP 바이너리**이고, 그 안에 XML 파일 하나가 들어 있으며 각 `<list>` 항목은
`corp_code` / `corp_name` / `corp_eng_name` / `stock_code` / `modify_date` 를 가집니다.
(출처: OPENDART 개발가이드 "고유번호" API 상세 페이지, 2026-08-23 확인)

⚠️ 이 매핑표는 상장사만 있는 게 아닙니다. DART에 등록된 **비상장 법인까지 전부** 들어
   있고, 비상장 법인은 `stock_code` 가 빈 문자열입니다. 그래서 "종목코드가 있는 항목만"
   골라 색인을 만듭니다.

────────────────────────────────────────────────────────────────────────────────
📌 확인한 것 / 확인 못 한 것 (정직하게 구분 — §0-1)
────────────────────────────────────────────────────────────────────────────────
[확인됨 — 2026-08-23 이 개발 세션에서 실제로 호출]
  · `corpCode.xml` 에 실제 발급키로 요청하면 **텍스트가 아닌 바이너리**가 돌아옵니다.
    (개발 샌드박스의 도구로는 그 바이너리를 열어보지 못했습니다 — 아래 참고)
  · 잘못된 인증키로 `alotMatter.json` 을 부르면 `{"status":"010", ...}` 이 옵니다.
    즉 인증 실패는 HTTP 4xx 가 아니라 **HTTP 200 + status 코드**로 옵니다. corpCode 도
    같은 규격이라 개발가이드에 `<status>`/`<message>` 가 명시돼 있습니다.
[❌ 확인 못 함 — 이 세션에서 검증 불가]
  · **ZIP 안 XML 파일의 실제 이름**(관례상 `CORPCODE.xml`)과 실제 항목 수.
    이 개발 샌드박스는 프록시 allowlist 때문에 `requests`/`curl` 로 opendart 에 직접
    붙지 못하고, 대체 도구(WebFetch)는 ZIP 바이너리를 다루지 못합니다.
    → **파일 이름을 하드코딩하지 않습니다.** ZIP 안에서 `.xml` 로 끝나는 멤버를 찾아
      정확히 하나일 때만 씁니다(0개거나 2개 이상이면 지어내지 않고 예외).
  · 매핑 실패(우리 유니버스에 있는데 DART 표에 없는 종목코드)가 실제로 몇 건인지.
    → 첫 실행 로그에서 확인해야 합니다. 이 모듈은 그 목록을 **버리지 않고 반환**합니다.

────────────────────────────────────────────────────────────────────────────────
📌 §0-1 준수 요약 — "조용히 넘어가는 경로"를 두지 않았습니다
────────────────────────────────────────────────────────────────────────────────
  · 매핑 안 되는 종목코드 → `unmapped` 리스트에 **사유와 함께** 담아 반환합니다.
  · 한 종목코드에 corp_code 가 2개 이상 붙어 있으면(합병·재상장 등으로 실제 발생 가능)
    임의로 고르지 않고 `duplicates` 에 전부 기록한 뒤, `modify_date` 가 가장 최신인
    항목을 쓰되 **그 사실을 기록**합니다.
  · 파싱 위치는 전부 **태그 이름 기반**입니다. 위치 인덱스(첫 번째 자식 = corp_code 식)
    파싱은 쓰지 않습니다(§0-1 "위치 인덱스 파싱 금지").
  · 인증키는 환경변수 `DART_API_KEY` 에서만 읽고, 예외 메시지·로그·캐시 파일 어디에도
    키 값을 남기지 않습니다.

📌 외부 서버 매너 (§0-3-2)
  · 이 모듈은 **1회 실행당 corpCode.xml 을 최대 1번** 부릅니다(그마저도 캐시가 신선하면
    0번). 4xx/인증오류/요청제한은 재시도하지 않고 즉시 실패로 끝냅니다. 네트워크 오류와
    5xx 만 1회 재시도합니다.
"""
import io
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# requests 는 프로덕션(GitHub Actions) 실행에만 필요합니다. 오프라인 테스트가 이 모듈을
# import 만 하고 네트워크 함수는 부르지 않는 경우까지 requests 설치를 강제하지 않기 위해
# 지연/방어 import 를 씁니다. 실제로 네트워크가 필요한 시점에 명확한 메시지로 실패합니다.
try:
    import requests
except ImportError:  # pragma: no cover - 프로덕션에는 항상 설치돼 있습니다.
    requests = None

# =============================================================================
# 1. 엔드포인트·인증 규격
# =============================================================================
DART_CORPCODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

# 인증키는 환경변수에서만 읽습니다. 코드·문서·로그·캐시 어디에도 값 자체를 남기지 않습니다.
DART_API_KEY_ENV = "DART_API_KEY"

# =============================================================================
# 2. 크롤링 매너 상수 (§0-3-2)
# =============================================================================
CORPCODE_TIMEOUT_SEC = 60      # ZIP 이 수 MB라 alotMatter(15초)보다 넉넉히 잡습니다.
CORPCODE_NETWORK_RETRY = 1     # 네트워크/5xx 에 한해 1회만 재시도
CORPCODE_RETRY_DELAY_SEC = 5.0

# 캐시 기본 수명. DART 고유번호는 신규상장/사명변경 때만 바뀌므로 매일 받을 이유가 없습니다.
# (§0-3-2 "필요한 만큼만" — 안 바뀌는 수 MB 파일을 매일 받는 것은 그 자체로 무례합니다.)
CORPCODE_CACHE_MAX_AGE_DAYS = 7

# =============================================================================
# 3. DART 공통 응답 코드 (출처: OPENDART 개발가이드 상세 페이지, 2026-08-23 확인)
#    ※ 이 표는 collector_dividend_kr.py 와 공유합니다. 한 곳에만 두려고 여기에 둡니다.
# =============================================================================
DART_STATUS_MESSAGES = {
    "000": "정상",
    "010": "등록되지 않은 키입니다.",
    "011": "사용할 수 없는 키입니다(오픈API에 등록되었으나 일시적으로 사용 중지된 키).",
    "012": "접근할 수 없는 IP입니다.",
    "013": "조회된 데이타가 없습니다.",
    "014": "파일이 존재하지 않습니다.",
    "020": "요청 제한을 초과하였습니다(일반적으로 하루 20,000건 초과 시).",
    "021": "조회 가능한 회사 개수가 초과하였습니다(최대 100건).",
    "100": "필드의 부적절한 값입니다.",
    "101": "부적절한 접근입니다.",
    "800": "시스템 점검으로 인한 서비스가 중지 중입니다.",
    "900": "정의되지 않은 오류가 발생하였습니다.",
    "901": "사용자 계정의 개인정보 보유기간이 만료되어 사용할 수 없는 키입니다.",
}

# "이 상태가 뜨면 그 종목만 실패가 아니라 **실행 전체를 멈춰야 하는**" 코드들.
# 재시도해봐야 똑같고, 계속 두드리는 것 자체가 §0-3-2 위반입니다.
DART_FATAL_STATUSES = ("010", "011", "012", "020", "101", "800", "901")

KST = timezone(timedelta(hours=9))


def _now_kst():
    """GitHub Actions 러너는 기본 UTC라 KST를 명시합니다(collector_kospi200.py 와 동일 이유)."""
    return datetime.now(KST)


class DartCorpCodeError(RuntimeError):
    """corpCode.xml 취득/파싱 실패. 메시지에 인증키를 절대 포함하지 않습니다."""


# =============================================================================
# 4. 저수준 유틸 (순수 함수 — 네트워크 없이 테스트 가능)
# =============================================================================
def get_api_key(explicit=None):
    """
    DART 인증키를 반환합니다. 없으면 None.

    ⚠️ 예외를 던지지 않는 이유: 키가 없는 것은 '버그'가 아니라 '이 수집을 할 수 없는 상태'
       입니다. 호출부가 그 사실을 리포트에 적고 종료하는 편이 스택트레이스보다 낫습니다.
    """
    if explicit:
        return str(explicit).strip() or None
    key = os.environ.get(DART_API_KEY_ENV)
    return key.strip() if key and key.strip() else None


# KRX 6자 영숫자 종목코드(숫자 + 대문자 알파벳). 아래 normalize_stock_code() 참고.
_KRX_ALNUM6_RE = re.compile(r"^[0-9A-Z]{6}$")


def normalize_stock_code(value):
    """
    종목코드를 6자리 문자열로 정규화합니다.

    받아들이는 형태는 **정확히 두 가지**입니다. 그 밖에는 전부 None 입니다.

    ① 순수 숫자 — 좌측 0 패딩을 복원해 6자리로 만듭니다.
       엑셀/CSV 를 거치며 '005930' 이 정수 5930 으로 뭉개지는 사고가 흔해서 복원합니다.
       이건 '지어내기'가 아니라 **같은 값의 표기 복원**입니다.
       7자리 이상 숫자는 종목코드가 아니므로 잘라내지 않고 None 입니다.

    ② 6자 영숫자(숫자 + 대문자 알파벳) — 예: '03473K'(SK우), '00680K', '0126Z0'.
       ⚠️ **깨진 데이터가 아니라 KRX 가 실제로 쓰는 종목코드 표기**입니다. 한 발행사에
          배정된 순수 숫자 코드 공간이 소진되면 KRX 는 알파벳 한 글자가 섞인 6자 코드를
          부여하며, 우선주(우선주 종목)에서 특히 흔합니다.
       [확인됨 — 2026-08-24, data/kr_ticker_master.json 실물 대조]
          type=="STOCK" 2,873건 중 79건이 이 형태이고, 79건 전부 길이가 정확히 6자이며
          실재하는 상장 증권입니다(우선주 23건 · 스팩 30건 · 신규상장 등 26건).
       이 형태는 **이미 6자**라 패딩할 여지가 없고, 알파벳이 놓인 자리 자체가 코드를
       구분하는 정보이므로 대문자로만 올린 뒤 **그대로** 돌려줍니다. 숫자 문자열처럼
       "어디에 0을 채울까"를 고민할 여지가 애초에 없습니다.

    ⚠️ 이 두 번째 경로는 "관대하게 봐주기"가 아니라 **실물로 확인된 한 가지 형식**만
       좁게 여는 것입니다. 5자·7자 영숫자, 한글·기호가 섞인 값, 대문자로 올려도
       [0-9A-Z]{6} 이 되지 않는 값은 전과 똑같이 None 이고, 호출부가 "정규화 실패"로
       기록합니다. 임의로 잘라내거나 붙이지 않습니다.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        if len(text) > 6:
            return None            # 7자리 이상은 종목코드가 아님 — 지어내서 자르지 않습니다.
        return text.zfill(6)
    # 순수 숫자는 위에서 이미 처리됐으므로, 여기 오는 6자 영숫자는 알파벳이 섞인 경우뿐입니다.
    # (upper() 로 길이가 변하는 문자가 섞이면 len 검사에서 걸러집니다 — 예: 'ß' → 'SS')
    upper = text.upper()
    if len(upper) == 6 and _KRX_ALNUM6_RE.match(upper):
        return upper
    return None


def _text_or_none(value):
    """XML findtext 결과 정리: 앞뒤 공백 제거, 빈 문자열은 None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decode_error_body(raw_bytes):
    """
    ZIP 이 아닌 응답(= DART 가 XML 로 돌려준 오류)에서 status/message 를 뽑습니다.
    뽑지 못하면 None 을 돌려주고, 호출부가 "알 수 없는 응답"으로 처리합니다.
    """
    if not raw_bytes:
        return None
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    status = _text_or_none(root.findtext("status"))
    message = _text_or_none(root.findtext("message"))
    if status is None and message is None:
        return None
    return {"status": status, "message": message}


# =============================================================================
# 5. ZIP/XML 파싱 (순수 함수 — 바이트만 주면 되므로 오프라인 테스트 대상)
# =============================================================================
def parse_corpcode_zip(zip_bytes):
    """
    corpCode.xml 응답 바이트(ZIP)를 파싱해 회사 목록(dict 리스트)을 반환합니다.

    반환 원소:
      {"corp_code","corp_name","corp_eng_name","stock_code","modify_date"}
      — stock_code 는 정규화된 6자리 문자열이거나 None(비상장/정규화 실패).
      — 원문 종목코드는 "stock_code_raw" 로 함께 보존합니다(§0-3-3 raw 보존).

    실패는 전부 DartCorpCodeError. 조용히 빈 리스트를 돌려주지 않습니다(§0-1) —
    빈 리스트는 "DART에 회사가 하나도 없다"는 뜻이 되어버리기 때문입니다.
    """
    if not zip_bytes:
        raise DartCorpCodeError("corpCode 응답이 비어 있습니다(0 바이트).")

    # ZIP 매직넘버 확인. ZIP 이 아니면 DART 가 XML 오류를 돌려준 경우입니다.
    if not zip_bytes[:2] == b"PK":
        err = _decode_error_body(zip_bytes)
        if err:
            status = err.get("status")
            known = DART_STATUS_MESSAGES.get(status, "")
            raise DartCorpCodeError(
                f"corpCode 요청이 오류로 응답했습니다 — status={status} "
                f"message={err.get('message')!r} ({known})"
            )
        raise DartCorpCodeError(
            "corpCode 응답이 ZIP 이 아니고 DART 오류 XML 로도 해석되지 않습니다 "
            f"(앞 16바이트: {zip_bytes[:16]!r}). 응답 규격이 바뀌었을 수 있습니다."
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise DartCorpCodeError(f"corpCode ZIP 을 열 수 없습니다: {e}")

    # ⚠️ 안쪽 파일 이름을 'CORPCODE.xml' 로 하드코딩하지 않습니다(실물 미확인).
    #    .xml 멤버가 정확히 하나일 때만 진행하고, 아니면 실제 목록을 메시지에 실어 실패합니다.
    xml_members = [n for n in archive.namelist() if n.lower().endswith(".xml")]
    if len(xml_members) != 1:
        raise DartCorpCodeError(
            f"corpCode ZIP 안의 .xml 파일이 {len(xml_members)}개라 하나로 특정할 수 없습니다 "
            f"(ZIP 내용물: {archive.namelist()}). 임의로 고르지 않고 중단합니다."
        )

    try:
        payload = archive.read(xml_members[0])
    except Exception as e:
        raise DartCorpCodeError(f"corpCode ZIP 안의 '{xml_members[0]}' 를 읽지 못했습니다: {e}")

    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError as e:
        raise DartCorpCodeError(f"corpCode XML 파싱 실패: {e}")

    # 파일 자체가 오류 응답인 경우(가능성은 낮지만 규격상 status/message 가 최상위에 있습니다)
    root_status = _text_or_none(root.findtext("status"))
    if root_status is not None and root_status != "000":
        raise DartCorpCodeError(
            f"corpCode XML 이 오류 상태입니다 — status={root_status} "
            f"message={root.findtext('message')!r}"
        )

    entries = []
    # 태그 이름으로만 찾습니다(위치 인덱스 파싱 금지, §0-1).
    for node in root.iter("list"):
        corp_code = _text_or_none(node.findtext("corp_code"))
        if not corp_code:
            # corp_code 없는 항목은 이 표의 존재 이유 자체가 없는 행입니다. 건너뛰되
            # 개수를 세기 위해 아래 통계에 남깁니다.
            entries.append({"corp_code": None, "_invalid": True})
            continue
        raw_stock = _text_or_none(node.findtext("stock_code"))
        entries.append({
            "corp_code": corp_code,
            "corp_name": _text_or_none(node.findtext("corp_name")),
            "corp_eng_name": _text_or_none(node.findtext("corp_eng_name")),
            "stock_code_raw": raw_stock,
            "stock_code": normalize_stock_code(raw_stock),
            "modify_date": _text_or_none(node.findtext("modify_date")),
        })

    valid = [e for e in entries if not e.get("_invalid")]
    if not valid:
        raise DartCorpCodeError(
            f"corpCode XML 에서 유효한 <list> 항목을 하나도 찾지 못했습니다 "
            f"(전체 <list> 노드 {len(entries)}개). 응답 규격이 바뀌었을 수 있습니다."
        )
    return valid


def build_stock_code_index(entries):
    """
    회사 목록 → {6자리 종목코드: 회사 dict} 색인을 만듭니다. (순수 함수)

    반환: (index, stats)
      index : {stock_code: entry}
      stats : {
        "total_entries", "listed_entries", "unlisted_entries",
        "malformed_stock_codes": [원문, ...],   # 값이 있는데 6자리로 정규화 못 한 것
        "duplicates": [ {stock_code, chosen, dropped:[...], note}, ... ],
      }

    ⚠️ 중복 처리 원칙(§0-1): 같은 종목코드에 corp_code 가 둘 이상 붙는 경우
       (합병·분할·재상장 이력 등으로 실제로 발생할 수 있습니다) **임의로 첫 번째를
       고르지 않습니다.** `modify_date` 가 가장 최신인 항목을 쓰되, 버린 후보를 전부
       `duplicates` 에 남겨 첫 실행 로그에서 눈으로 확인할 수 있게 합니다.
       modify_date 로도 우열을 못 가리면(값이 없거나 동률) 그 사실도 note 에 적습니다.
    """
    index = {}
    stats = {
        "total_entries": len(entries or []),
        "listed_entries": 0,
        "unlisted_entries": 0,
        "malformed_stock_codes": [],
        "duplicates": [],
    }
    buckets = {}
    for entry in entries or []:
        code = entry.get("stock_code")
        if not code:
            if entry.get("stock_code_raw"):
                # 값이 있는데 6자리로 못 만든 경우 — 조용히 버리지 않고 기록합니다.
                stats["malformed_stock_codes"].append(entry.get("stock_code_raw"))
            else:
                stats["unlisted_entries"] += 1
            continue
        buckets.setdefault(code, []).append(entry)

    for code, candidates in buckets.items():
        if len(candidates) == 1:
            index[code] = candidates[0]
            continue
        # modify_date(YYYYMMDD 문자열) 최신순. 값이 없으면 빈 문자열로 취급해 뒤로 밀립니다.
        ordered = sorted(candidates, key=lambda e: (e.get("modify_date") or ""), reverse=True)
        chosen = ordered[0]
        dates = [e.get("modify_date") for e in candidates]
        ambiguous = (chosen.get("modify_date") is None) or (
            len([d for d in dates if d == chosen.get("modify_date")]) > 1
        )
        stats["duplicates"].append({
            "stock_code": code,
            "chosen": {"corp_code": chosen.get("corp_code"), "corp_name": chosen.get("corp_name"),
                       "modify_date": chosen.get("modify_date")},
            "dropped": [{"corp_code": e.get("corp_code"), "corp_name": e.get("corp_name"),
                         "modify_date": e.get("modify_date")} for e in ordered[1:]],
            "note": ("modify_date 로 우열을 가릴 수 없어(값 없음 또는 동률) 정렬 순서상 첫 항목을 "
                     "썼습니다 — 사람이 확인해야 합니다."
                     if ambiguous else "modify_date 가 가장 최신인 항목을 선택했습니다."),
        })
        index[code] = chosen

    stats["listed_entries"] = len(index)
    return index, stats


def build_corp_name_index(entries):
    """
    회사 목록 → {회사명: 회사 dict} 색인을 만듭니다. (순수 함수)

    `build_stock_code_index()` 와 **같은 입력**(parse_corpcode_zip 결과)을 받아, 종목코드가
    아니라 `corp_name` 으로 찾을 수 있게 만든 **보조 색인**입니다. 종목코드 직접매칭이
    실패했을 때만 쓰는 2차 경로입니다(`map_stock_codes()` 참고).

    반환: (name_index, stats)
      name_index : {corp_name(앞뒤 공백 제거): entry}
      stats : {
        "total_entries",           # 입력 항목 수 (build_stock_code_index 와 같은 뜻)
        "total_named_entries",     # corp_name 이 있어 후보가 된 항목 수 (중복 제거 전)
        "named_entries",           # 색인에 실제로 들어간 고유 회사명 수 (중복 제거 후)
                                   #   ↳ build_stock_code_index 의 "listed_entries" 에 대응
        "unnamed_entries",         # corp_name 이 없어 건너뛴 항목 수
                                   #   ↳ build_stock_code_index 의 "unlisted_entries" 에 대응
        "duplicate_names": [ {corp_name, chosen, dropped:[...], note}, ... ],
                                   #   ↳ build_stock_code_index 의 "duplicates" 와 **같은 모양**.
                                   #      키 이름만 다르게 둔 이유: 두 색인의 stats 를 나란히
                                   #      로그에 찍을 때 어느 쪽 중복인지 헷갈리지 않기 위함입니다.
      }

    ⚠️ **정확 일치만 합니다**(§0-1 "회사 매칭을 추측하지 않는다"). 부분일치·유사도·접두사
       매칭을 일절 하지 않습니다. '삼성전자' 와 '삼성전자서비스' 는 남남입니다.
       정규화도 앞뒤 공백 제거 하나뿐입니다 — 그 이상 손대면(공백 제거·특수문자 제거 등)
       서로 다른 회사가 같은 키로 뭉개질 수 있습니다.

    ⚠️ 중복 처리 원칙(§0-1): 동명이인 회사(실제로 존재합니다)는 임의로 첫 번째를 고르지
       않습니다. **`build_stock_code_index()` 와 완전히 같은 규칙**으로 `modify_date` 가
       가장 최신인 항목을 쓰되, 버린 후보를 전부 `duplicate_names` 에 남깁니다.
       modify_date 로 우열을 못 가리면 그 사실도 note 에 적습니다.

    ⚠️ corp_name 이 없는 항목은 **세지 않고 버리지 않습니다** — `unnamed_entries` 에
       개수가 남아, 색인 크기와 입력 크기가 안 맞는 이유를 설명할 수 있습니다.
    """
    index = {}
    stats = {
        "total_entries": len(entries or []),
        "total_named_entries": 0,
        "named_entries": 0,
        "unnamed_entries": 0,
        "duplicate_names": [],
    }
    buckets = {}
    for entry in entries or []:
        name = (entry.get("corp_name") or "").strip()
        if not name:
            stats["unnamed_entries"] += 1
            continue
        stats["total_named_entries"] += 1
        buckets.setdefault(name, []).append(entry)

    for name, candidates in buckets.items():
        if len(candidates) == 1:
            index[name] = candidates[0]
            continue
        # modify_date(YYYYMMDD 문자열) 최신순. 값이 없으면 빈 문자열로 취급해 뒤로 밀립니다.
        # (build_stock_code_index() 와 한 글자도 다르지 않은 정렬·판정 규칙입니다.)
        ordered = sorted(candidates, key=lambda e: (e.get("modify_date") or ""), reverse=True)
        chosen = ordered[0]
        dates = [e.get("modify_date") for e in candidates]
        ambiguous = (chosen.get("modify_date") is None) or (
            len([d for d in dates if d == chosen.get("modify_date")]) > 1
        )
        stats["duplicate_names"].append({
            "corp_name": name,
            "chosen": {"corp_code": chosen.get("corp_code"), "corp_name": chosen.get("corp_name"),
                       "modify_date": chosen.get("modify_date")},
            "dropped": [{"corp_code": e.get("corp_code"), "corp_name": e.get("corp_name"),
                         "modify_date": e.get("modify_date")} for e in ordered[1:]],
            "note": ("modify_date 로 우열을 가릴 수 없어(값 없음 또는 동률) 정렬 순서상 첫 항목을 "
                     "썼습니다 — 사람이 확인해야 합니다."
                     if ambiguous else "modify_date 가 가장 최신인 항목을 선택했습니다."),
        })
        index[name] = chosen

    stats["named_entries"] = len(index)
    return index, stats


def map_stock_codes(stock_codes, index, name_index=None, code_name_map=None):
    """
    우리 유니버스의 종목코드 목록을 corp_code 로 매핑합니다. (순수 함수)

    반환: (mapping, unmapped)
      mapping  : {stock_code: {"corp_code","corp_name","corp_eng_name","modify_date",
                               "matched_via"}}
      unmapped : [{"stock_code_input", "stock_code", "reason"}, ...]

    `matched_via` 는 그 종목을 **어느 경로로 찾았는지**를 남기는 필드입니다(추가만 했고
    기존 필드는 하나도 바꾸지 않았습니다).
      · "stock_code"    — 종목코드 직접매칭(1차, 기존 경로)
      · "name_fallback" — 회사명 정확일치 2차 경로(아래 참고)

    ── 선택 인자: 회사명 2차 매칭 ───────────────────────────────────────────────
    name_index    : `build_corp_name_index()` 결과 {회사명: entry}
    code_name_map : {유니버스 원문 종목코드: 회사명}
        유니버스 파일이 이름 컬럼을 갖고 있을 때만 호출부가 만들어 넘깁니다.
        키는 **정규화 전 원문**입니다 — `map_stock_codes` 가 순회하는 값이 원문이라,
        그 시점에 바로 찾을 수 있는 유일한 키이기 때문입니다.

    ⚠️ **둘 다 주어졌을 때만** 2차 경로가 동작합니다. 하나라도 없으면(기본값 None)
       이 함수의 동작은 이 인자들이 생기기 전과 완전히 동일합니다.
    ⚠️ 2차 경로가 끼어드는 지점은 **딱 한 곳**입니다: 종목코드 정규화는 성공했는데
       `index` 에 그 코드가 없는 경우. 정규화 자체가 실패한 값(형식 오류)에는 손대지
       않습니다 — 코드가 무엇인지도 모르는 상태에서 이름으로 회사를 정하는 것은
       추측이기 때문입니다(§0-1).
    ⚠️ 이름 매칭은 **앞뒤 공백만 제거한 완전일치**입니다. 유사·부분 일치는 하지 않습니다.
       찾지 못하면 그대로 실패로 두고, 두 경로를 모두 시도했다는 사실을 사유에 적습니다.

    ⚠️ 매핑 실패를 **조용히 빼지 않습니다**(§0-1). 상장폐지·사명변경·비상장 전환 등으로
       DART 표에 없는 종목이 반드시 나오는데, 그 개수와 목록을 모르면 "2,700개 중 2,600개만
       수집됐는데 아무도 모르는" 상태가 됩니다.
    """
    mapping = {}
    unmapped = []
    seen = set()
    # 두 인자가 **모두** 있을 때만 2차 경로를 켭니다. 빈 dict 도 켤 이유가 없습니다.
    name_fallback_enabled = bool(name_index) and bool(code_name_map)
    for raw in stock_codes or []:
        code = normalize_stock_code(raw)
        if code is None:
            unmapped.append({
                "stock_code_input": raw,
                "stock_code": None,
                "reason": "종목코드를 6자리로 정규화할 수 없습니다(형식 오류).",
            })
            continue
        if code in seen:
            # 중복 입력은 오류가 아니라 입력 파일의 사정이므로 조용히 무시하되,
            # 매핑 결과 개수와 입력 개수가 안 맞는 이유를 설명할 수 있게 세지는 않습니다.
            continue
        seen.add(code)
        entry = index.get(code)
        if entry is not None:
            mapping[code] = {
                "corp_code": entry.get("corp_code"),
                "corp_name": entry.get("corp_name"),
                "corp_eng_name": entry.get("corp_eng_name"),
                "modify_date": entry.get("modify_date"),
                "matched_via": "stock_code",
            }
            continue

        # ── 2차: 회사명 정확일치 ────────────────────────────────────────────────
        tried_name = None
        if name_fallback_enabled:
            candidate_name = code_name_map.get(raw)
            if candidate_name is not None:
                tried_name = str(candidate_name).strip()
                if tried_name:
                    name_entry = name_index.get(tried_name)
                    if name_entry is not None:
                        mapping[code] = {
                            "corp_code": name_entry.get("corp_code"),
                            "corp_name": name_entry.get("corp_name"),
                            "corp_eng_name": name_entry.get("corp_eng_name"),
                            "modify_date": name_entry.get("modify_date"),
                            "matched_via": "name_fallback",
                        }
                        continue

        reason = ("DART 고유번호 표(corpCode.xml)에 이 종목코드가 없습니다 "
                  "(상장폐지·비상장 전환·표 갱신 지연 등 가능).")
        if tried_name:
            # 왜 실패했는지까지는 알 수 없습니다 — '무엇을 해봤는지'만 정직하게 적습니다.
            reason += (f" 회사명 '{tried_name}' 으로도 한 번 더 찾아봤지만 그 이름 역시 표에 "
                       "없었습니다(이름은 앞뒤 공백만 제거한 완전일치로만 봅니다 — 비슷한 "
                       "이름으로 넘겨짚지 않습니다).")
        unmapped.append({
            "stock_code_input": raw,
            "stock_code": code,
            "reason": reason,
        })
    return mapping, unmapped


# =============================================================================
# 6. 네트워크 (테스트에서는 _http_get_bytes 하나만 가짜로 바꾸면 됩니다)
# =============================================================================
def _http_get_bytes(url, params, timeout, session):
    """
    실제 네트워크 호출 지점. **테스트는 이 함수 하나만 monkeypatch 합니다**
    (utils/krx_openapi.py 의 `_http_get_json` 과 같은 패턴).
    반환: (status_code, content_bytes)
    """
    if session is None and requests is None:
        raise DartCorpCodeError(
            "`requests` 패키지가 설치돼 있지 않아 corpCode.xml 을 받을 수 없습니다. "
            "requirements.txt 를 확인하세요."
        )
    getter = session.get if session is not None else requests.get
    res = getter(url, params=params, timeout=timeout)
    return getattr(res, "status_code", None), getattr(res, "content", b"")


def download_corpcode_zip(api_key=None, session=None):
    """
    corpCode.xml(ZIP 바이너리)을 내려받아 bytes 로 반환합니다.

    §0-3-2: 4xx·인증오류는 **재시도하지 않습니다.** 네트워크 오류와 5xx 만 1회 재시도합니다.
    """
    key = get_api_key(api_key)
    if not key:
        raise DartCorpCodeError(
            f"환경변수 {DART_API_KEY_ENV} 가 없어 corpCode.xml 을 받을 수 없습니다. "
            "키를 코드에 적어 넣지 말고 환경변수/Actions Secret 으로 넣으세요."
        )

    last_error = None
    for attempt in range(CORPCODE_NETWORK_RETRY + 1):
        try:
            status, content = _http_get_bytes(
                DART_CORPCODE_URL, {"crtfc_key": key}, CORPCODE_TIMEOUT_SEC, session
            )
        except DartCorpCodeError:
            raise
        except Exception as e:
            last_error = f"네트워크 오류: {type(e).__name__}"
            if attempt < CORPCODE_NETWORK_RETRY:
                time.sleep(CORPCODE_RETRY_DELAY_SEC)
                continue
            raise DartCorpCodeError(f"corpCode.xml 다운로드 실패 — {last_error}")

        if status is not None and 400 <= status < 500:
            # ⚠️ 재시도 금지. 429(요청 과다)도 여기서 즉시 중단합니다.
            raise DartCorpCodeError(
                f"corpCode.xml 요청이 HTTP {status} 로 거부됐습니다. 재시도하지 않고 중단합니다."
            )
        if status is not None and status >= 500:
            last_error = f"서버 오류(HTTP {status})"
            if attempt < CORPCODE_NETWORK_RETRY:
                time.sleep(CORPCODE_RETRY_DELAY_SEC)
                continue
            raise DartCorpCodeError(f"corpCode.xml 다운로드 실패 — {last_error}")
        if status not in (200, None):
            raise DartCorpCodeError(f"corpCode.xml 예상치 못한 응답 상태: {status}")

        return content

    raise DartCorpCodeError(f"corpCode.xml 다운로드 실패 — {last_error}")   # 도달 불가(방어)


# =============================================================================
# 7. 캐시 (raw/가공 분리 — §0-3-3)
# =============================================================================
def save_corpcode_cache(cache_path, entries, stats=None):
    """
    가공본(회사 목록 JSON)을 캐시에 저장합니다.

    ⚠️ 캐시에 인증키를 절대 넣지 않습니다. `source_url` 도 쿼리스트링 없는 순수 URL 만 적습니다.
    """
    payload = {
        "source_url": DART_CORPCODE_URL,          # 키 없는 순수 URL
        "fetched_at_kst": _now_kst().isoformat(),
        "entry_count": len(entries or []),
        "stats": stats or {},
        "entries": entries or [],
    }
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)) or ".", exist_ok=True)
    tmp_path = f"{cache_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp_path, cache_path)              # 쓰다 죽어도 반쪽 캐시가 남지 않도록
    return cache_path


def load_corpcode_cache(cache_path, max_age_days=CORPCODE_CACHE_MAX_AGE_DAYS):
    """
    캐시를 읽어 (entries, meta) 를 반환합니다. 쓸 수 없으면 (None, 사유dict).

    ⚠️ '깨진 캐시'와 '오래된 캐시'를 구분해 사유를 남깁니다. 조용히 None 만 돌려주면
       왜 매번 다시 받는지 알 수 없게 됩니다.
    """
    if not os.path.exists(cache_path):
        return None, {"usable": False, "reason": "캐시 파일이 없습니다."}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, {"usable": False, "reason": f"캐시 파일을 읽지 못했습니다: {type(e).__name__}"}

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return None, {"usable": False, "reason": "캐시에 entries 가 비어 있습니다."}

    fetched_at = data.get("fetched_at_kst")
    age_days = None
    if fetched_at:
        try:
            dt = datetime.fromisoformat(fetched_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            age_days = (_now_kst() - dt).total_seconds() / 86400.0
        except Exception:
            age_days = None

    if age_days is None:
        return None, {"usable": False, "reason": "캐시의 fetched_at_kst 를 해석할 수 없습니다."}
    if max_age_days is not None and age_days > max_age_days:
        return None, {"usable": False,
                      "reason": f"캐시가 {age_days:.1f}일 지나 기준({max_age_days}일)을 넘었습니다."}

    return entries, {"usable": True, "fetched_at_kst": fetched_at, "age_days": round(age_days, 2),
                     "entry_count": len(entries)}


def get_corp_code_index(cache_path, api_key=None, max_age_days=CORPCODE_CACHE_MAX_AGE_DAYS,
                        force_refresh=False, session=None, raw_zip_path=None, log=print):
    """
    종목코드 → corp_code 색인을 얻는 상위 함수. 캐시가 신선하면 네트워크를 아예 안 씁니다.

    반환: (index, info)
      index : {stock_code: entry}
      info  : {"source": "cache"|"network", "stats": {...}, "cache_note": str,
               "entries": [...]}

    `info["entries"]` 는 색인을 만들기 전의 **원본 파싱 결과 리스트**입니다(캐시에서 왔든
    네트워크에서 왔든 같은 모양). `build_corp_name_index()` 처럼 종목코드 색인이 아닌
    다른 색인을 만들려면 이 리스트가 필요해서 함께 돌려줍니다 — 같은 파일을 두 번 읽거나
    corpCode.xml 을 두 번 받는 일을 막기 위함입니다(§0-3-2).
    ⚠️ 이 리스트는 수만 건이라 **리포트/캐시에 그대로 싣지 않습니다**. `stats` 가 아니라
       `info` 최상위에 둔 이유가 그것입니다(`stats` 는 리포트에 통째로 실립니다).

    raw_zip_path 를 주면 내려받은 **원본 ZIP 을 그대로** 그 경로에 저장합니다
    (§0-3-3 raw/가공 분리 보관 — 나중에 파싱 규칙을 바꿔도 재다운로드가 필요 없습니다).
    """
    if not force_refresh:
        entries, note = load_corpcode_cache(cache_path, max_age_days=max_age_days)
        if entries:
            index, stats = build_stock_code_index(entries)
            log(f"  ℹ️ corpCode 캐시 사용 ({note.get('entry_count')}건, "
                f"{note.get('age_days')}일 경과) — 네트워크 요청 없음")
            return index, {"source": "cache", "stats": stats,
                           "cache_note": note.get("reason", ""), "entries": entries}
        log(f"  ℹ️ corpCode 캐시를 쓰지 않습니다 — {note.get('reason')}")

    zip_bytes = download_corpcode_zip(api_key=api_key, session=session)
    if raw_zip_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(raw_zip_path)) or ".", exist_ok=True)
            with open(raw_zip_path, "wb") as f:
                f.write(zip_bytes)
            log(f"  💾 corpCode 원본 ZIP 보관: {raw_zip_path} ({len(zip_bytes):,} bytes)")
        except Exception as e:
            # raw 보관 실패가 수집 자체를 죽일 이유는 없지만, 조용히 넘기지는 않습니다.
            log(f"  ⚠️ corpCode 원본 ZIP 보관 실패(수집은 계속): {type(e).__name__}: {e}")

    entries = parse_corpcode_zip(zip_bytes)
    index, stats = build_stock_code_index(entries)
    save_corpcode_cache(cache_path, entries, stats)
    log(f"  ✅ corpCode 신규 수신: 전체 {stats['total_entries']:,}건 중 "
        f"상장 종목코드 보유 {stats['listed_entries']:,}건 "
        f"(비상장 {stats['unlisted_entries']:,}건, 형식오류 {len(stats['malformed_stock_codes'])}건, "
        f"종목코드 중복 {len(stats['duplicates'])}건)")
    return index, {"source": "network", "stats": stats, "cache_note": "", "entries": entries}
