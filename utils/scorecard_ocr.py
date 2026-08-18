# utils/scorecard_ocr.py
"""
📊 "내 성적표" v2 — 스크린샷 OCR로 보유종목(종목명/수량/매입가) 프리필.

`SCORECARD_V2_OCR_WORK_ORDER.md` / ENGINEERING_SPEC.md §0-3-11(외부 AI 모델은 항상
교체 가능하게)의 **첫 적용 사례**입니다.

⚠️ 이 파일 밖에서는 "Gemini"라는 이름이 등장하면 안 됩니다 — 호출부(화면 등)는 오직
   `extract_holdings_from_image()` 하나만 알면 됩니다. 실제 provider 는 이 함수 **안에서만**
   `OCR_PROVIDER` 환경변수(기본값 "gemini")로 갈립니다. 지금은 gemini 하나만 실제로
   구현합니다 — 안 쓰는 provider의 빈 껍데기를 미리 만들어두지 않습니다(§0-3-10 YAGNI).
   나중에 provider를 늘릴 때는 이 함수 안에 분기 하나만 추가하면 됩니다.

⚠️ §0-1 (지어내지 않기)
   - API 키가 없거나 필요한 패키지가 없거나 응답 파싱에 실패하면, "성공한 척" 빈 결과를
     조용히 돌려주지 않고 `OcrError` 를 던집니다. 화면(호출부)이 이 예외를 사람이 읽을
     문장으로 보여줍니다 — 실패를 삼키지 않습니다.
   - 읽을 수 없는 숫자를 그럴듯하게 채우지 않습니다. 수량/매입가를 확신할 수 없으면
     `None` 으로 남기고, 그 종목의 `confidence` 를 `"low"` 로 표시해 화면이 사용자에게
     재확인을 유도하게 합니다.
   - **이 함수는 절대 현재가(현재 시세)를 채우지 않습니다.** 현재가는 항상 기존
     `resolve_stock_query()` + 시세 스냅샷(`scorecard_db.py`)에서만 옵니다. 반환값에
     "price"/"current_price" 류 키가 섞이면 그 자체로 버그이므로, 아래
     `extract_holdings_from_image()` 가 매 호출마다 이를 방어적으로 확인합니다
     (`tests/test_scorecard_ocr.py` 회귀 테스트로 고정).

⚠️ §0-3-8 (개인정보·업로드 이미지 최소 노출)
   - 원본 스크린샷 바이트는 이 모듈 안 어디에도 저장하지 않습니다(디스크/DB 모두). API
     호출 한 번에만 쓰고, 호출이 끝나면(성공/실패 무관) 지역 변수 참조를 끊어 즉시 GC
     대상이 되게 합니다. 로그에도 이미지 바이트나 원문 응답 전체를 남기지 않습니다.

패턴 재사용
   - Gemini 클라이언트 초기화는 `utils/macro_ai.py`(API 키 없으면 조용히 건너뜀)와
     `utils/scorecard_db.py`(패키지 없으면 `try/except ImportError`)의 기존 패턴을
     그대로 따릅니다 — 이 두 파일과 다른 새 패턴을 만들지 않습니다(§0-3-10).
"""

from __future__ import annotations

import json
import math
import os
import re

# ⚠️ 2026-08-18 마이그레이션 — 구글이 지원 종료(EOL)를 선언한 `google-generativeai` 대신
#    후속 패키지 `google-genai` 를 씁니다(ENGINEERING_SPEC.md §0-3-12, PROJECT_STATUS.md
#    §0-5-6). API 모양이 통째로 바뀌었습니다: 예전엔 `genai.configure(api_key=...)` 로 전역
#    설정 후 `genai.GenerativeModel(name).generate_content(...)` 를 불렀는데, 새 SDK는
#    설정을 전역에 두지 않고 `genai.Client(api_key=...)` 로 매 호출마다 별도 클라이언트를
#    만들어 `client.models.generate_content(model=..., contents=..., config=...)` 로 부릅니다.
#    같은 패키지를 쓰는 `utils/macro_ai.py` 도 같이 옮겼습니다(§0-3-10 — 한 곳만 옮기면
#    두 패턴이 공존해 유지보수가 더 어려워짐).
try:  # pragma: no cover - 환경에 따라 갈리는 import (macro_ai.py / scorecard_db.py 와 동일 패턴)
    from google import genai
    from google.genai import types as genai_types
    GENAI_PACKAGE_AVAILABLE = True
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None
    GENAI_PACKAGE_AVAILABLE = False


class OcrError(RuntimeError):
    """OCR 추출 실패 — 조용히 삼키지 않고 화면에 사람이 읽을 문장으로 보여줍니다 (§0-1)."""


# 2026-08-17 (SCORECARD_V2_OCR_WORK_ORDER.md) — 저비용 고효율 모델. macro_ai.py 의
# `gemini-2.5-flash`(텍스트 코멘트용)와는 별개 모델입니다: 이 작업은 이미지 인식이라
# `-lite` 모델로도 충분하고, 성적표 v2 작업지시서에서 이 모델로 확정했습니다.
# 2026-08-17 정정(실검증 중 발견): 원래 넣었던 `gemini-2.5-flash-lite`가 신규 프로젝트에
# 더 이상 제공되지 않아(구글 API가 404 NotFound + `gemini-3.5-flash-lite`로 교체 안내)
# 실제 Render 배포 로그에서 확인 후 아래로 교체. §0-3-12(외부 의존성 능동 점검) 적용 사례.
GEMINI_MODEL_NAME = "gemini-3.5-flash-lite"

_ALLOWED_CONFIDENCE = ("high", "low")

_PROMPT = """당신은 증권사 앱(MTS/HTS) 보유종목 화면 스크린샷에서 정보를 추출하는 OCR 도구입니다.

이 이미지에서 각 종목의 "종목명", "보유수량", "매입평균가(평단가)"만 읽어 아래 JSON
스키마로만 답하세요.

⚠️ 반드시 지킬 것
1. 오직 JSON 객체 하나만 출력하세요. 설명 문장, 마크다운 코드펜스(```), 그 밖의 텍스트를
   덧붙이지 마세요.
2. "현재가"·"평가금액"·"손익"·"등락률"·"수익률" 등 다른 값은 절대 추출하지 마세요 — 이
   스키마에는 그런 필드가 없습니다. 종목명·수량·매입가 세 가지만 봅니다.
3. 글자가 잘리거나 흐릿하거나 가려져서 확신할 수 없으면 그 종목의 "confidence"를 "low"로
   표시하세요. 숫자를 지어내지 말고, 읽을 수 없는 값은 해당 필드를 null로 두세요.
4. 화면에 종목이 여러 개 보이면 보이는 종목을 전부 "items" 배열에 담으세요.
5. 화면에서 보유종목을 하나도 찾을 수 없으면 {"items": []} 를 반환하세요.

출력 스키마 (그대로, 다른 키를 추가하지 마세요):
{"items": [{"raw_name": "삼성전자", "quantity": 10, "avg_price": 71000, "confidence": "high"}]}
"""

_CURRENT_PRICE_KEYS = ("price", "current_price", "current_value", "market_price")


def extract_holdings_from_image(image_bytes: bytes) -> dict:
    """
    브로커 앱 스크린샷 1장(bytes) → 종목명/수량/매입가 추출 결과.

    반환: {"items": [{"raw_name": str, "quantity": float|None,
                       "avg_price": float|None, "confidence": "high"|"low"}, ...]}

    - provider 선택은 `OCR_PROVIDER` 환경변수(기본값 "gemini")로 매 호출마다 다시 읽습니다
      (macro_ai.py 가 `GEMINI_API_KEY` 를 매 호출마다 다시 읽는 것과 같은 이유 — 서버
      재시작 없이 설정을 바꿀 수 있고, 테스트에서 monkeypatch 하기도 쉽습니다).
    - 실패(키 없음/패키지 없음/빈 응답/파싱 실패 등)는 조용히 빈 dict 를 돌려주지 않고
      `OcrError` 를 던집니다 — 호출부가 사람이 읽을 문구로 그대로 보여줍니다(§0-1).
    - **현재가를 채우는 코드 경로가 하나라도 생기면 아래에서 즉시 예외로 잡습니다** —
      실수로 추가되더라도 조용히 화면까지 새어나가지 않습니다.
    """
    provider = (os.environ.get("OCR_PROVIDER") or "gemini").strip().lower()
    if provider == "gemini":
        result = _extract_with_gemini(image_bytes)
    else:
        # 안 쓰는 provider의 빈 껍데기를 미리 만들어두지 않았으므로(§0-3-10 YAGNI),
        # 모르는 값은 지어내지 않고 명확히 실패시킵니다(§0-1).
        raise OcrError(f"지원하지 않는 OCR_PROVIDER 입니다: {provider!r}")

    for item in result.get("items", []):
        if any(key in item for key in _CURRENT_PRICE_KEYS):
            # 이 경로는 정상 동작에서는 절대 타지 않습니다 — 타면 코드에 회귀가 생긴 것입니다.
            raise OcrError(
                "내부 오류: OCR 추출 결과에 현재가 관련 필드가 섞여 있습니다 (금지된 경로, §0-1)."
            )
    return result


def _extract_with_gemini(image_bytes: bytes) -> dict:
    """실제 Gemini 호출. `extract_holdings_from_image()` 밖에서 직접 부르지 않습니다."""
    if not GENAI_PACKAGE_AVAILABLE:
        raise OcrError(
            "OCR 기능에 필요한 패키지가 설치돼 있지 않습니다. 관리자에게 문의해 주세요."
        )
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise OcrError(
            "OCR 기능을 쓰려면 서버에 GEMINI_API_KEY 설정이 필요합니다. 관리자에게 문의해 주세요."
        )
    # 빈 파일·이미지 아님 판정은 화면(`web/pages/scorecard_page.py`)이 하루 한도를 차감하기
    # 전에 이미 한 번 합니다. 여기서 또 부르는 이유는 이 모듈만 단독으로 불러도(테스트·다른
    # 호출부) 같은 방어가 걸리게 하기 위함이고, 두 곳이 **같은 함수**를 쓰므로 판정 기준이
    # 서로 갈릴 수 없습니다(§0-3-10 중복 금지).
    mime_type = ensure_supported_image_format(image_bytes)

    # 2026-08-18 — `genai.configure()` + `genai.GenerativeModel(name)`(구 SDK) 대신
    # `genai.Client(api_key=...)` 로 이 호출 전용 클라이언트를 만듭니다(신 SDK, 전역 설정 없음).
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=[
                _PROMPT,
                genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # noqa: BLE001 — 원문은 로그로만, 화면엔 사람이 읽을 문장만(§0-3-4)
        print(f"⚠️ Gemini OCR 요청 실패: {type(exc).__name__}: {exc}")
        raise OcrError("스크린샷 인식 요청이 실패했습니다. 잠시 후 다시 시도해 주세요.") from exc
    finally:
        # 원본 이미지 바이트를 이 함수가 계속 들고 있지 않도록 참조를 끊습니다(§0-3-8).
        image_bytes = None

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise OcrError("스크린샷에서 아무 내용도 인식하지 못했습니다 — 직접 입력해 주세요.")

    return _parse_response_text(text)


def ensure_supported_image_format(image_bytes: bytes) -> str:
    """업로드된 바이트가 우리가 처리할 수 있는 이미지인지 확인하고 그 MIME 타입을 돌려줍니다.

    아니면 `OcrError` — 지어내지 않고 사람이 읽을 문장으로 실패시킵니다(§0-1).

    ⚠️ 2026-08-18 신설(공개 함수인 이유) — 화면이 **하루 업로드 한도를 차감하기 전에**
       이 검사를 먼저 할 수 있어야 하기 때문입니다. 예전에는 이 판정이 유료 호출 함수
       안쪽(= 한도 차감 뒤)에서만 일어나서, 이미지가 아닌 파일을 올리면 외부 API 로는
       아무것도 안 나가는데(돈은 안 나감) 사용자의 한도만 1회 깎였습니다. 그건 데이터
       계층(`utils/scorecard_db.py`)의 한도 함수가 독스트링에서 이미 약속한
       "유료 호출이 없었던 업로드는 한 번으로 세지 않는다"와 어긋납니다.
       (이 모듈은 그 한도 계층을 import 하지도, 이름으로 부르지도 않습니다 — 순서를 정하는
        건 화면이고 이 모듈은 계속 네트워크·DB 없이 단독 테스트 가능한 순수 변환기입니다.)
       판정 로직 자체는 아래 `_sniff_mime_type()` 하나뿐이라 화면과 이 모듈이 서로 다른
       기준으로 갈릴 일은 없습니다(§0-3-10).
    """
    if not image_bytes:
        raise OcrError("업로드된 이미지가 비어 있습니다. 다시 업로드해 주세요.")
    return _sniff_mime_type(image_bytes)


def _sniff_mime_type(image_bytes: bytes) -> str:
    """파일명·확장자를 믿지 않고 **바이트 시그니처**로 이미지 형식을 판별합니다.

    ⚠️ 2026-08-17 검토에서 고친 자리 — 예전에는 모르는 형식을 "대부분 PNG니까"라며
    `"image/png"` 으로 넘겼습니다. 그건 §0-1(모르는 값을 그럴듯하게 지어내지 않기)에
    정면으로 걸립니다. 게다가 실제로도 두 가지가 나빠집니다.
      ① 형식을 잘못 알려주면 provider 는 엉뚱한 내부 오류를 돌려주고, 사용자는
         "요청이 실패했습니다"만 보게 되어 무엇을 고쳐야 할지 알 수 없습니다(§0-3-4).
      ② 이미지가 아닌 파일(문서·실행파일 등)이 그대로 외부 유료 API 로 나가는 경로가
         생깁니다 — 업로드 위젯의 `accept` 는 브라우저 쪽 검사라 우회됩니다(§0-3-9).
    그래서 판별되지 않으면 지어내지 않고 그 자리에서 사람이 읽을 문장으로 실패시킵니다.
    화면 업로드 위젯이 허용하는 png/jpg/jpeg/webp 는 전부 아래에서 판별됩니다.
    """
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise OcrError(
        "이미지 파일로 보이지 않습니다 — PNG · JPG · WEBP 스크린샷으로 다시 올려주세요."
    )


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_response_text(text: str) -> dict:
    """Gemini 응답 텍스트 → 검증된 `{"items": [...]}`.

    `response_mime_type="application/json"` 를 요청했지만, 그래도 혹시 마크다운
    코드펜스가 섞여 오는 구버전 SDK/모델 대비로 방어적으로 벗겨냅니다.
    """
    cleaned = _JSON_FENCE_RE.sub("", text.strip()).strip()
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OcrError(
            "스크린샷 인식 결과를 해석하지 못했습니다 — 직접 입력해 주세요."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise OcrError(
            "스크린샷 인식 결과 형식이 올바르지 않습니다 — 직접 입력해 주세요."
        )

    cleaned_items = []
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("raw_name") or "").strip()
        if not name:
            continue
        cleaned_items.append({
            "raw_name": name,
            "quantity": _safe_number(raw.get("quantity")),
            "avg_price": _safe_number(raw.get("avg_price")),
            "confidence": raw.get("confidence") if raw.get("confidence") in _ALLOWED_CONFIDENCE else "low",
        })

    if not cleaned_items:
        raise OcrError("스크린샷에서 보유종목을 찾지 못했습니다 — 직접 입력해 주세요.")

    return {"items": cleaned_items}


def _safe_number(value) -> "float | None":
    """읽을 수 없는 값은 지어내지 않고 `None` (§0-1). 콤마 섞인 문자열은 허용."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool은 int의 서브클래스라 먼저 걸러냄
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
    if not math.isfinite(number) or number <= 0:
        return None
    return number
