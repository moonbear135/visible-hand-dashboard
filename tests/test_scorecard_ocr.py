# tests/test_scorecard_ocr.py
"""
📊 "내 성적표" v2 — 스크린샷 OCR(`utils/scorecard_ocr.py`) 오프라인 검증.

`SCORECARD_V2_OCR_WORK_ORDER.md` 4단계(오프라인 테스트)에 따라, API 키·실제 클라이언트·
네트워크 없이 전부 모킹으로 검증합니다(`tests/test_scorecard.py` 의 오프라인 검증
컨벤션을 그대로 따름 — `pytest` 로 실행 가능한 `test_*` 함수 + `assert`).

검증 대상
    ① 정상 응답(다건 종목) 파싱
    ② confidence: low 행이 값을 지어내지 않고 그대로 남아 화면이 재확인을 유도하도록
       배선되는지 (모듈 자체는 저장을 하지 않으며, 화면 쪽 자동 저장 금지 배선도 확인)
    ③ 빈 응답/파싱 실패는 조용히 무시되지 않고 OcrError 로 사용자에게 보이는지 (§0-1)
    ④ 회귀 고정 — OCR 결과 dict 에 현재가 필드가 절대 채워지지 않는지
    ⑤ SCORECARD_OCR_ENABLED=False(기본값)일 때 업로드 위젯이 그려지지 않는지
    ⑥ provider(Gemini) 이름이 화면 파일 밖으로 새지 않는지 (§0-3-11)
    ⑦ 2026-08-17 검토에서 추가 — provider 분기(OCR_PROVIDER)가 실제로 동작하는지,
       이미지 형식을 지어내지 않고 실제 바이트대로 보내는지, 업로드 크기 제한이 브라우저뿐
       아니라 서버에서도 걸리는지, 실패 문구가 화면에 쌓이지 않는지
    ⑧ 2026-08-17 오너 결정 — **사용자별 하루 업로드 한도**(유료 API 호출 횟수 제한):
       경계값(마지막 1회는 되고 그 다음은 안 됨), 사용자 간 격리, 자정(날짜 변경) 리셋,
       저장소가 없을 때 기존 관례대로 fail-closed 인지, 한도 초과가 조용히 무시되지 않는지

⚠️ 기존 `tests/test_scorecard.py` 스위트는 이 작업으로 회귀되지 않아야 하며, 그건 같이
   `pytest tests/test_scorecard_ocr.py tests/test_scorecard.py` 로 확인합니다(이 파일이
   그 스위트를 다시 돌리지는 않습니다).

실행: pytest tests/test_scorecard_ocr.py
"""

import ast
import importlib
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_MAGIC = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8
GIF_MAGIC = b"GIF89a" + b"\x00" * 16
# 이미지가 아닌 파일(=업로드 위젯의 accept 를 우회해 들어온 경우)
PDF_MAGIC = b"%PDF-1.7\n" + b"\x00" * 16


@pytest.fixture
def ocr_module(monkeypatch):
    """매 테스트마다 깨끗한 환경변수 상태로 다시 import(모듈 전역이 테스트 간에 새지 않도록)."""
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import utils.scorecard_ocr as mod
    importlib.reload(mod)
    return mod


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, response_text=None, exc=None):
        self._response_text = response_text
        self._exc = exc
        self.calls = []

    def generate_content(self, parts, **kwargs):
        self.calls.append((parts, kwargs))
        if self._exc:
            raise self._exc
        return _FakeResponse(self._response_text)


class _FakeGenAI:
    """`google.generativeai` 모듈을 흉내내는 최소 스텁 — 실제 패키지가 없어도 검증 가능."""

    def __init__(self, model):
        self._model = model
        self.configured_with = None
        self.requested_model_name = None

    def configure(self, api_key):
        self.configured_with = api_key

    def GenerativeModel(self, name):  # noqa: N802 - 실제 라이브러리 메서드 이름 그대로
        self.requested_model_name = name
        return self._model


def _wire_fake_gemini(mod, monkeypatch, *, response_text=None, exc=None, api_key="test-key"):
    fake_model = _FakeModel(response_text=response_text, exc=exc)
    fake_genai = _FakeGenAI(fake_model)
    monkeypatch.setattr(mod, "genai", fake_genai)
    monkeypatch.setattr(mod, "GENAI_PACKAGE_AVAILABLE", True)
    if api_key is not None:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)
    else:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return fake_model, fake_genai


def _page_source() -> str:
    return (REPO_ROOT / "web" / "pages" / "scorecard_page.py").read_text(encoding="utf-8")


def _ocr_module_source() -> str:
    return (REPO_ROOT / "utils" / "scorecard_ocr.py").read_text(encoding="utf-8")


def _source_block(src: str, start_marker: str, end_marker: str) -> str:
    """`start_marker` 부터 `end_marker` 직전까지의 소스 조각.

    ⚠️ 2026-08-17 검토에서 정규식 → 문자열 인덱스로 바꾼 자리. 예전 방식은
    `(?=\n        async def)` 처럼 **바로 다음에 오는 코드의 모양**을 조건으로 삼아서,
    사이에 함수 하나만 끼워 넣어도 검사 범위가 조용히 넓어지거나 매치가 통째로 깨졌습니다.
    시작/끝 표식을 눈에 보이게 적어두면 나중에 코드가 움직여도 왜 깨졌는지 바로 압니다.
    """
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _upload_handler_source() -> str:
    return _source_block(_page_source(), "async def _on_ocr_upload(event) -> None:", "\n        ui.upload(")


# =============================================================================
# ① 정상 응답(다건 종목) 파싱
# =============================================================================
def test_parses_multiple_items(ocr_module, monkeypatch):
    response_json = json.dumps({
        "items": [
            {"raw_name": "삼성전자", "quantity": 10, "avg_price": 71000, "confidence": "high"},
            {"raw_name": "카카오", "quantity": "3", "avg_price": "45,000", "confidence": "low"},
        ]
    }, ensure_ascii=False)
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)

    result = ocr_module.extract_holdings_from_image(PNG_MAGIC)

    assert result["items"][0] == {
        "raw_name": "삼성전자", "quantity": 10.0, "avg_price": 71000.0, "confidence": "high",
    }
    # 콤마 섞인 문자열 숫자도 정상 파싱됨
    assert result["items"][1]["avg_price"] == 45000.0
    assert result["items"][1]["quantity"] == 3.0


def test_markdown_fence_is_stripped(ocr_module, monkeypatch):
    fenced = "```json\n" + json.dumps({
        "items": [{"raw_name": "NVDA", "quantity": 1, "avg_price": 900, "confidence": "high"}]
    }) + "\n```"
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=fenced)
    result = ocr_module.extract_holdings_from_image(PNG_MAGIC)
    assert result["items"][0]["raw_name"] == "NVDA"


def test_model_name_matches_work_order(ocr_module, monkeypatch):
    response_json = json.dumps({"items": [
        {"raw_name": "테스트", "quantity": 1, "avg_price": 1, "confidence": "high"}
    ]})
    _fake_model, fake_genai = _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)
    ocr_module.extract_holdings_from_image(PNG_MAGIC)
    assert fake_genai.requested_model_name == "gemini-3.5-flash-lite"


# =============================================================================
# ② confidence: low 는 값을 지어내지 않고 그대로 남아 화면이 재확인을 유도함
# =============================================================================
def test_low_confidence_item_values_are_not_invented(ocr_module, monkeypatch):
    response_json = json.dumps({"items": [
        {"raw_name": "잘린종목", "quantity": None, "avg_price": None, "confidence": "low"},
    ]})
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)
    result = ocr_module.extract_holdings_from_image(PNG_MAGIC)
    item = result["items"][0]
    assert item["confidence"] == "low"
    # 못 읽은 값은 그럴듯한 숫자로 채워지지 않고 None 그대로 남습니다(§0-1) — 사용자가 직접 채움
    assert item["quantity"] is None
    assert item["avg_price"] is None


def test_missing_or_invalid_confidence_defaults_to_low_never_high(ocr_module):
    """confidence 필드가 아예 없거나 스키마 밖 값이면 '확신 있다'고 지어내지 않고 low로 취급."""
    payload = ocr_module._parse_response_text(json.dumps({"items": [
        {"raw_name": "이름만있음"},
        {"raw_name": "이상한값", "confidence": "확실함"},
    ]}))
    assert all(item["confidence"] == "low" for item in payload["items"])


def test_ui_upload_handler_never_auto_saves():
    """OCR 프리필 핸들러(`_on_ocr_upload`)가 `add_lot()`(저장)을 직접 부르지 않는지 소스로 확인.

    저장은 사용자가 직접 누르는 기존 "➕ 추가" 버튼(`_submit`)에서만 일어나야 합니다
    (tests/test_scorecard.py::test_view_and_routing 이 화면 배선을 소스 텍스트로 검증하는
    기존 컨벤션을 그대로 따름).
    """
    handler_src = _upload_handler_source()
    assert "add_lot(" not in handler_src, "OCR 업로드 핸들러가 add_lot()을 직접 불러 자동 저장하면 안 됨"
    # 2026-08-17 버그 수정 — 여러 장 업로드 시 이전 결과가 지워지던 문제를 고치면서
    # "이번 결과만 그리기"(`_render_ocr_items(result['items'])`)에서 "누적 목록에 추가 후
    # 전체를 다시 그리기"(`extracted_items.extend(...)` + 인자 없는 `_render_ocr_items()`)로
    # 바꿨습니다. 여전히 렌더링(프리필 대기)만 하고 저장은 안 하는지가 이 테스트의 핵심이므로
    # 새 형태에 맞춥니다.
    assert "extracted_items.extend(result" in handler_src, \
        "새로 인식된 항목은 누적 목록에 추가되어야 함(여러 장 업로드 시 이전 결과 유지)"
    assert "_render_ocr_items()" in handler_src, "추출 결과는 목록으로만 그려지고(프리필 대기) 저장되지 않아야 함"


def test_low_confidence_rows_are_visually_flagged_in_ui():
    """확신도가 낮은 행은 배지/테두리로 강조되어야 합니다(재확인 유도)."""
    body = _source_block(
        _page_source(),
        "def _render_ocr_items() -> None:",
        "\n        async def _on_ocr_upload(",
    )
    assert "low_conf" in body and "ui.badge(" in body, "낮은 확신도 행에 배지가 붙어야 함"
    assert "#f59e0b" in body, "낮은 확신도 행에 강조 테두리(경고색)가 있어야 함"


def test_multiple_uploads_accumulate_instead_of_replacing():
    """여러 장을 연달아 올리면 이전 장의 인식 결과가 사라지지 않고 누적되어야 합니다.

    2026-08-17 오너 실사용 중 재현된 버그: 3장을 올렸을 때 마지막 장의 결과만 남고
    가운데 장(예: 국제 금) 결과가 화면에서 사라짐 — `extracted_box.clear()`로 매번
    통째로 지우고 "이번 장 결과만" 다시 그렸던 게 원인. 목록 변수가 세션(페이지 함수)
    지역 변수를 벗어나지 않고(§0-3-8) 계속 append되는지를 소스로 확인합니다.
    """
    src = _page_source()
    assert "extracted_items: list = []" in src, \
        "누적용 목록이 페이지 지역 변수로 선언되어 있어야 함(모듈 전역 금지, §0-3-8)"
    assert "extracted_items.extend(" in src, "새 인식 결과는 기존 목록에 추가(extend)되어야 함 — 교체 금지"


# =============================================================================
# ③ 빈 응답 / 파싱 실패 → OcrError (조용히 무시 금지, §0-1)
# =============================================================================
def test_empty_text_response_raises_ocr_error(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, response_text="")
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_no_items_found_raises_ocr_error(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=json.dumps({"items": []}))
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_malformed_json_raises_ocr_error(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, response_text="이건 JSON이 아닙니다")
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_non_dict_json_raises_ocr_error(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=json.dumps([1, 2, 3]))
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_empty_image_bytes_raises_ocr_error(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=json.dumps({"items": []}))
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(b"")


def test_missing_api_key_raises_ocr_error_not_silent_skip(ocr_module, monkeypatch):
    """macro_ai.py(배치)는 키가 없으면 '조용히 건너뛰기'가 맞지만, 이 기능은 사용자가 방금
    누른 업로드에 대한 즉시 응답이 필요하므로 조용히 아무 일도 안 하면 안 됩니다(§0-1)."""
    monkeypatch.setattr(ocr_module, "genai", types.SimpleNamespace())
    monkeypatch.setattr(ocr_module, "GENAI_PACKAGE_AVAILABLE", True)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_missing_package_raises_ocr_error(ocr_module, monkeypatch):
    monkeypatch.setattr(ocr_module, "GENAI_PACKAGE_AVAILABLE", False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_unknown_provider_raises_ocr_error(ocr_module, monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "chatgpt-vision")
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_provider_exception_raises_ocr_error_without_leaking_original_text(ocr_module, monkeypatch):
    _wire_fake_gemini(ocr_module, monkeypatch, exc=RuntimeError("network boom, secret=xyz"))
    with pytest.raises(ocr_module.OcrError) as excinfo:
        ocr_module.extract_holdings_from_image(PNG_MAGIC)
    # 화면에 보일 문구는 파이썬 원본 예외 텍스트를 그대로 노출하지 않음(§0-3-4)
    assert "network boom" not in str(excinfo.value)
    assert "secret=xyz" not in str(excinfo.value)


# =============================================================================
# ④ 회귀 고정 — OCR 결과에 현재가 필드가 절대 섞이지 않음
# =============================================================================
def test_result_never_contains_current_price_fields(ocr_module, monkeypatch):
    response_json = json.dumps({"items": [
        {"raw_name": "삼성전자", "quantity": 10, "avg_price": 71000, "confidence": "high"},
    ]})
    _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)
    result = ocr_module.extract_holdings_from_image(PNG_MAGIC)
    for item in result["items"]:
        for forbidden in ("price", "current_price", "current_value", "market_price"):
            assert forbidden not in item, (
                f"OCR 결과에 '{forbidden}' 키가 있으면 안 됩니다 — 현재가는 항상 "
                "resolve_stock_query()/시세 스냅샷에서만 와야 합니다(§0-1)."
            )
    assert set(result["items"][0].keys()) == {"raw_name", "quantity", "avg_price", "confidence"}


def test_regression_guard_rejects_leaked_current_price(ocr_module, monkeypatch):
    """실수로 provider 파서가 현재가 필드를 채우게 되더라도 `extract_holdings_from_image()`가
    그걸 그대로 통과시키지 않고 `OcrError` 로 잡아내는지 — 나중에 실수로 다시 채워지면 이
    테스트가 바로 실패해야 합니다."""

    def _leaky_provider(_image_bytes):
        return {"items": [
            {"raw_name": "삼성전자", "quantity": 10, "avg_price": 71000,
             "confidence": "high", "price": 72000},  # 절대 있으면 안 되는 필드
        ]}

    monkeypatch.setattr(ocr_module, "_extract_with_gemini", _leaky_provider)
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PNG_MAGIC)


def test_response_parser_never_copies_price_fields_through(ocr_module):
    """`_parse_response_text()`가 provider 응답에 'price' 필드가 있어도 우리가 만드는 dict에는
    옮겨 담지 않는지 — 스키마 자체가 화이트리스트 방식이라 현재가가 새어들어올 통로가 없음."""
    response_json = json.dumps({"items": [
        {"raw_name": "종목", "quantity": 1, "avg_price": 100, "confidence": "high",
         "price": 999999, "current_price": 999999},
    ]})
    payload = ocr_module._parse_response_text(response_json)
    assert "price" not in payload["items"][0]
    assert "current_price" not in payload["items"][0]


def test_current_price_never_wired_into_extraction_call_in_ui():
    """화면 코드가 OCR 함수 호출 결과에 현재가를 덧붙이는 경로를 만들지 않았는지 소스로 확인."""
    handler_src = _upload_handler_source()
    assert "current_price" not in handler_src and "valuation_summary" not in handler_src, (
        "OCR 업로드 핸들러는 현재가/밸류에이션을 붙이지 않습니다 — 그건 사용자가 저장 버튼을 "
        "누른 뒤 기존 조회 경로(resolve_stock_query → build_portfolio)에서만 일어납니다."
    )


# =============================================================================
# ⑤ SCORECARD_OCR_ENABLED=False(기본값) → 업로드 위젯 미노출
# =============================================================================
def test_ocr_flag_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("SCORECARD_OCR_ENABLED", raising=False)
    import web.pages.scorecard_page as page
    importlib.reload(page)
    assert page.SCORECARD_OCR_ENABLED is False


def test_ocr_flag_requires_exact_true_value(monkeypatch):
    import web.pages.scorecard_page as page
    try:
        for off_value in ("", "1", "yes", "on", "false"):
            monkeypatch.setenv("SCORECARD_OCR_ENABLED", off_value)
            importlib.reload(page)
            assert page.SCORECARD_OCR_ENABLED is False, f"{off_value!r} 는 켜짐으로 해석되면 안 됨"
        for on_value in ("true", "True", "TRUE", " true "):
            monkeypatch.setenv("SCORECARD_OCR_ENABLED", on_value)
            importlib.reload(page)
            assert page.SCORECARD_OCR_ENABLED is True, f"{on_value!r} 는 켜짐으로 해석돼야 함"
    finally:
        # 다른 테스트에 영향이 없도록 기본(꺼짐) 상태로 모듈을 되돌립니다.
        monkeypatch.delenv("SCORECARD_OCR_ENABLED", raising=False)
        importlib.reload(page)


def test_upload_widget_is_really_not_rendered_when_flag_is_off():
    """소스 검사만으로는 부족하니 **화면 함수를 실제로 실행**해서 확인합니다(§0-3-6).

    ⚠️ 2026-08-17 검토에서 추가한 자리 — 아래 `..._in_source()` 는 "가드가 위에 있다"만
    보기 때문에, 예를 들어 가드 조건이 늘 참이 되게 잘못 바뀌어도 통과합니다. 여기서는
    `web/pages/scorecard_page.py::_render_body()` 를 진짜로 돌려서 `ui.upload()` 가
    **한 번도 불리지 않는지** 셉니다(= 업로드 위젯이 화면에 없음).
    (`tests/test_web_session_isolation.py::test_render_smoke` 가 쓰는 것과 같은 방식 —
    fetch_holdings 만 합성 데이터로 바꿔 끼우고 나머지는 실제 코드를 그대로 실행.)
    """
    pytest.importorskip("nicegui", reason="렌더 스모크는 nicegui 가 있어야 실행 가능")
    import web.pages.scorecard_page as page

    synthetic = [dict(market="KR", ticker="005930", stock_name="삼성전자",
                      quantity=10, avg_purchase_price=70000)]

    def _count_upload_widgets(flag_value):
        if flag_value is None:
            os.environ.pop("SCORECARD_OCR_ENABLED", None)
        else:
            os.environ["SCORECARD_OCR_ENABLED"] = flag_value
        importlib.reload(page)
        calls = []
        original_upload = page.ui.upload
        original_fetch = page.fetch_holdings

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return original_upload(*args, **kwargs)

        page.ui.upload = _spy
        page.fetch_holdings = lambda client, user_id: [dict(h) for h in synthetic]
        try:
            page._render_body(object(), "uid-test", "a@example.com")
        finally:
            page.ui.upload = original_upload
            page.fetch_holdings = original_fetch
        return calls

    try:
        assert _count_upload_widgets(None) == [], (
            "플래그 기본값(미설정)에서 업로드 위젯이 실제로 그려지면 §0-3-6 위반입니다"
        )
        enabled_calls = _count_upload_widgets("true")
        assert len(enabled_calls) == 1, "플래그를 켜면 업로드 위젯이 정확히 하나 그려져야 함"
        # 켜졌을 때도 브라우저 쪽 크기 제한이 실제로 위젯에 붙어 나가는지 같이 확인합니다.
        assert enabled_calls[0]["max_file_size"] == page.MAX_OCR_IMAGE_BYTES
    finally:
        os.environ.pop("SCORECARD_OCR_ENABLED", None)
        importlib.reload(page)


def test_upload_widget_gated_behind_flag_in_source():
    """소스 구조로 확인: `ui.upload(` 호출이 `if SCORECARD_OCR_ENABLED:` 블록 안에서만 등장.

    (실제 브라우저 렌더링 확인에는 nicegui 테스트 서버가 필요하지만, 이 프로젝트의 기존
    컨벤션(`tests/test_scorecard.py::test_view_and_routing`)도 화면 배선은 소스 텍스트
    검증으로 고정합니다 — 같은 방식을 따릅니다.)
    """
    src = _page_source()
    assert "SCORECARD_OCR_ENABLED = (" in src, "기본 숨김 플래그 정의를 찾을 수 없음"
    func_match = re.search(r"\ndef _render_input_form\(.*?\n(?=def |\Z)", src, re.S)
    assert func_match, "_render_input_form 함수를 찾을 수 없음(위치가 바뀌었으면 정규식 갱신 필요)"
    form_src = func_match.group(0)
    guard_idx = form_src.index("if SCORECARD_OCR_ENABLED:")
    upload_idx = form_src.index("ui.upload(")
    assert guard_idx < upload_idx, "ui.upload() 호출이 SCORECARD_OCR_ENABLED 가드보다 먼저 나오면 안 됨"


# =============================================================================
# ⑥ web/pages/scorecard_page.py 는 "Gemini"라는 이름을 몰라야 함 (§0-3-11)
# =============================================================================
def test_page_module_does_not_reference_gemini_by_name():
    src = _page_source()
    assert "gemini" not in src.lower(), (
        "화면 파일은 provider 이름(Gemini)을 몰라야 합니다 — extract_holdings_from_image() "
        "함수 하나만 알아야 나중에 provider를 바꿀 때 이 파일을 고칠 필요가 없습니다(§0-3-11)."
    )


def test_ocr_provider_branching_isolated_to_ocr_module():
    """provider 분기(`OCR_PROVIDER`)와 Gemini 모델 이름은 utils/scorecard_ocr.py 안에만 있음."""
    src = _ocr_module_source()
    assert "OCR_PROVIDER" in src
    assert "gemini-3.5-flash-lite" in src
    assert '"gemini"' in src


def test_original_image_bytes_not_persisted_to_disk_or_db():
    """원본 이미지 바이트를 파일로 쓰거나 DB에 넣는 코드 경로가 없는지 소스로 확인(§0-3-8)."""
    ocr_src = _ocr_module_source()
    assert not re.search(r"open\([^)]*['\"]w", ocr_src), "OCR 모듈이 파일을 쓰지 않음(이미지 저장 없음)"
    handler_src = _upload_handler_source()
    assert not re.search(r"open\([^)]*['\"]w", handler_src), "업로드 핸들러가 이미지를 파일로 저장하지 않음"
    assert "insert_holding" not in handler_src and ".storage." not in handler_src, (
        "업로드 핸들러가 원본 이미지를 DB/스토리지에 넣지 않음"
    )


# =============================================================================
# 기타 배선 확인
# =============================================================================
def test_requirements_txt_has_uncommented_dependency():
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in req.splitlines()]
    assert any(ln == "google-generativeai" for ln in lines), (
        "google-generativeai 가 주석 처리되지 않은 실제 의존성 줄로 있어야 함"
    )


def test_work_order_document_exists():
    """작업지시서(`SCORECARD_V2_OCR_WORK_ORDER.md`)가 레포 루트에 실제로 있는지.

    2026-08-17 — 이전 세션에서는 문서 내용이 전달되지 않아 만들지 못했고, §0-1(지어내지
    않기) 때문에 "오너가 승인한 문서"를 추측해 채우지 않았습니다. 이번에 실제 내용을 받아
    저장했으므로, 코드가 근거로 삼는 값들이 그 문서와 계속 붙어 있는지 여기서 고정합니다.
    """
    doc = REPO_ROOT / "SCORECARD_V2_OCR_WORK_ORDER.md"
    assert doc.exists(), "SCORECARD_V2_OCR_WORK_ORDER.md 가 레포 루트에 있어야 함"
    text = doc.read_text(encoding="utf-8")
    for token in ("extract_holdings_from_image", "OCR_PROVIDER", "gemini-3.5-flash-lite",
                  "SCORECARD_OCR_ENABLED"):
        assert token in text, f"작업지시서에 '{token}' 근거가 남아 있어야 함"


# =============================================================================
# ⑦ 2026-08-17 검토에서 추가된 검증
# =============================================================================
def test_explicit_provider_value_is_honoured(ocr_module, monkeypatch):
    """`OCR_PROVIDER` 분기가 기본값뿐 아니라 **명시적으로 지정했을 때도** 동작하는지.

    (기존 테스트는 '기본값(미설정)' 과 '모르는 값' 두 갈래만 봤기 때문에, 예를 들어 대소문자
    정규화가 깨져도 아무도 못 잡았습니다.)
    """
    response_json = json.dumps({"items": [
        {"raw_name": "삼성전자", "quantity": 1, "avg_price": 1000, "confidence": "high"}
    ]}, ensure_ascii=False)
    for value in ("gemini", "Gemini", "  GEMINI  "):
        _fake_model, fake_genai = _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)
        monkeypatch.setenv("OCR_PROVIDER", value)
        result = ocr_module.extract_holdings_from_image(PNG_MAGIC)
        assert result["items"][0]["raw_name"] == "삼성전자", f"{value!r} 로도 gemini 분기를 타야 함"
        assert fake_genai.requested_model_name == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("image_bytes, expected_mime", [
    (PNG_MAGIC, "image/png"),
    (JPEG_MAGIC, "image/jpeg"),
    (WEBP_MAGIC, "image/webp"),
    (GIF_MAGIC, "image/gif"),
])
def test_image_format_is_read_from_bytes_not_guessed(ocr_module, monkeypatch, image_bytes, expected_mime):
    """provider 에 보내는 형식·바이트가 실제 업로드된 이미지와 일치하는지.

    (형식을 잘못 알려주면 provider 가 엉뚱한 오류를 내고 사용자는 이유를 알 수 없습니다.)
    """
    response_json = json.dumps({"items": [
        {"raw_name": "종목", "quantity": 1, "avg_price": 1, "confidence": "high"}
    ]})
    fake_model, _genai = _wire_fake_gemini(ocr_module, monkeypatch, response_text=response_json)
    ocr_module.extract_holdings_from_image(image_bytes)

    parts, kwargs = fake_model.calls[0]
    image_part = next(part for part in parts if isinstance(part, dict))
    assert image_part["mime_type"] == expected_mime
    assert image_part["data"] == image_bytes
    # JSON 으로만 답하라고 요청해야 파싱 실패 확률이 낮아집니다.
    assert kwargs["generation_config"]["response_mime_type"] == "application/json"


def test_unknown_file_type_is_rejected_before_calling_the_paid_api(ocr_module, monkeypatch):
    """이미지로 보이지 않는 바이트는 'PNG겠지' 하고 지어내지 않고 그 자리에서 막는지(§0-1).

    동시에 §0-3-9 — 업로드 위젯의 `accept` 는 브라우저 쪽 검사라 우회 가능하므로, 이미지가
    아닌 파일이 외부 유료 API 로 나가는 경로 자체가 없어야 합니다.
    """
    fake_model, _genai = _wire_fake_gemini(ocr_module, monkeypatch, response_text=json.dumps({"items": []}))
    with pytest.raises(ocr_module.OcrError):
        ocr_module.extract_holdings_from_image(PDF_MAGIC)
    assert fake_model.calls == [], "형식을 모르는 파일은 provider 로 나가지 않아야 함"


def test_upload_size_limit_is_enforced_on_the_server_not_only_in_the_browser():
    """`ui.upload(max_file_size=...)` 는 브라우저(Quasar) 검사라 업로드 주소로 직접 POST 하면
    그대로 통과합니다 — 서버에서도 같은 상수로 한 번 더 막는지 확인(§0-3-9)."""
    src = _page_source()
    assert "MAX_OCR_IMAGE_BYTES = " in src, "브라우저·서버가 공유할 크기 상수가 있어야 함(§0-3-10)"
    assert "max_file_size=MAX_OCR_IMAGE_BYTES" in src, "업로드 위젯도 같은 상수를 써야 함"
    handler_src = _upload_handler_source()
    assert "len(image_bytes) > MAX_OCR_IMAGE_BYTES" in handler_src, (
        "서버 쪽 크기 확인이 없으면 브라우저 검사만으로는 방어가 되지 않습니다"
    )


def test_upload_failures_do_not_pile_up_on_screen():
    """실패 문구는 매번 지워지는 전용 자리(`error_slot`)에 그려야 합니다.

    그냥 `error_banner()` 를 부르면 업로드 위젯의 부모 슬롯 끝에 매번 새로 덧붙어, 실패가
    쌓이고 다음 업로드가 성공해도 직전 실패 문구가 남습니다(§0-3-4 — 화면이 지금 상태를
    정확히 보여줘야 함).

    2026-08-17 버그 수정 — 예전엔 이 "매번 지우는 자리"가 하필 인식 결과 목록
    (`extracted_box`)과 같은 상자여서, 실패 배너 하나가 뜰 때마다 이미 성공한 이전 장의
    결과까지 같이 지워졌습니다(여러 장 업로드 버그의 원인 중 하나). 이제 실패 배너 전용
    `error_slot`으로 분리했으므로, 여기서는 ①`error_slot`만 지우고 다시 그리는지,
    ②그 과정에서 `extracted_box`(성공 결과 누적 목록)는 건드리지 않는지 둘 다 확인합니다.
    """
    page_src = _page_source()
    handler_src = _upload_handler_source()
    assert "error_banner(" not in handler_src, (
        "업로드 핸들러는 error_banner() 를 직접 부르지 않고 _show_ocr_error() 를 씁니다"
    )
    assert handler_src.count("_show_ocr_error(") >= 3, "크기 초과·OcrError·기타 예외 세 갈래 모두 화면에 보여야 함"
    helper_src = _source_block(
        page_src,
        "def _show_ocr_error(text: str) -> None:",
        "\n        def _make_ocr_fill_handler(",
    )
    assert "error_slot.clear()" in helper_src and "with error_slot:" in helper_src
    assert "extracted_box.clear()" not in helper_src, (
        "실패 배너 표시가 성공 결과 목록(extracted_box)까지 지우면 안 됨 — "
        "여러 장 업로드 시 이전 장의 성공 결과가 실패 배너 때문에 사라지는 회귀를 막는 테스트"
    )


def test_ocr_module_keeps_no_mutable_module_level_state():
    """§0-3-8 — 사용자 이미지/추출 결과가 모듈 전역에 남아 다른 접속자와 섞일 수 없는지.

    (`tests/test_web_session_isolation.py` 의 AST 검사는 `web/**` 와 `main.py` 만 훑기
    때문에, `utils/` 아래 새로 생긴 이 모듈은 여기서 같은 기준으로 봅니다.)
    """
    tree = ast.parse(_ocr_module_source())
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if not targets:
            continue
        assert not isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)), (
            f"모듈 전역 가변 컨테이너 금지 — {targets} (§0-3-8: 접속자끼리 값이 섞이는 통로)"
        )
    assert not any(isinstance(n, ast.Global) for n in ast.walk(tree)), (
        "global 선언으로 모듈 상태를 다시 묶는 코드가 없어야 합니다(§0-3-8)"
    )


# =============================================================================
# ⑧ 하루 업로드 한도 (2026-08-17 오너 결정) — 유료 API 호출 횟수를 사용자별로 묶습니다
# =============================================================================
#  카운터는 `utils/scorecard_db.py` 가 Supabase(`ocr_usage_daily`)에 저장합니다. 여기서는
#  네트워크 없이, 이미 있는 가짜 Supabase 클라이언트(`tests/test_scorecard.py::FakeClient`)를
#  그대로 재사용해서 배선을 검증합니다(§0-3-10 — 테스트용 가짜를 새로 만들지 않습니다).
# =============================================================================
from datetime import date as _date, datetime as _datetime  # noqa: E402


@pytest.fixture
def quota_db():
    """한도 로직이 들어 있는 데이터 계층 모듈."""
    from utils import scorecard_db
    return scorecard_db


def _fake_client(rows=None, fail=False):
    """기존 스위트의 가짜 Supabase 클라이언트를 재사용합니다.

    (함수 안에서 import 하는 건 `tests/test_data_source.py` 가 다른 테스트 모듈의 도우미를
     가져다 쓰는 방식과 같습니다 — 테스트 디렉터리가 sys.path 에 들어간 뒤에 부릅니다.)
    """
    from test_scorecard import FakeClient
    return FakeClient(rows=rows, fail=fail)


DAY_ONE = _date(2026, 8, 17)
DAY_TWO = _date(2026, 8, 18)


def test_owner_decided_limit_is_ten_per_user_per_day(quota_db):
    """오너가 정한 값(하루 10회)을 코드에 고정합니다 — 조용히 바뀌면 이 테스트가 깨집니다."""
    assert quota_db.DAILY_OCR_UPLOAD_LIMIT == 10


def test_uploads_up_to_the_limit_pass_and_the_next_one_is_blocked(quota_db):
    """경계값 — 마지막 1회(10회째)까지는 통과, 그 다음(11회째)은 차단."""
    client = _fake_client()
    limit = quota_db.DAILY_OCR_UPLOAD_LIMIT

    for attempt in range(1, limit):                 # 1 ~ 9회째
        quota = quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
        assert quota["used"] == attempt
        assert quota["remaining"] == limit - attempt

    last = quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)   # 10회째 = 한도 그 자체
    assert last["used"] == limit and last["remaining"] == 0, (
        "한도와 '같은' 횟수까지는 허용해야 합니다(10회 제한 = 10번은 쓸 수 있음)"
    )

    with pytest.raises(quota_db.OcrQuotaExceeded):                            # 11회째
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)


def test_blocked_upload_does_not_increase_the_counter_any_further(quota_db):
    """한도 초과 요청이 카운터를 계속 부풀리지 않는지(막힌 시도는 세지 않습니다)."""
    client = _fake_client()
    limit = quota_db.DAILY_OCR_UPLOAD_LIMIT
    for _ in range(limit):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    for _ in range(3):
        with pytest.raises(quota_db.OcrQuotaExceeded):
            quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    rows = [r for r in client.store["rows"] if r["user_id"] == "user-a"]
    assert len(rows) == 1 and int(rows[0]["used_count"]) == limit


def test_quota_is_isolated_between_users(quota_db):
    """§0-3-8 — A 가 한도를 다 써도 B 는 아무 영향이 없어야 합니다."""
    client = _fake_client()
    limit = quota_db.DAILY_OCR_UPLOAD_LIMIT

    for _ in range(limit):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    with pytest.raises(quota_db.OcrQuotaExceeded):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)

    first_for_b = quota_db.consume_ocr_quota(client, "user-b", usage_date=DAY_ONE)
    assert first_for_b["used"] == 1, "B 의 카운터는 A 의 사용량과 완전히 별개여야 합니다"
    assert first_for_b["remaining"] == limit - 1

    by_user = {r["user_id"]: int(r["used_count"]) for r in client.store["rows"]}
    assert by_user == {"user-a": limit, "user-b": 1}


def test_every_quota_query_is_filtered_by_user_id(quota_db):
    """조회·기록 쿼리가 항상 사용자 id 로 좁혀지는지(앱 쪽 이중 방어 — RLS 와 별개)."""
    client = _fake_client()
    quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)

    assert client.store["last_table"] == quota_db.OCR_USAGE_TABLE
    for op, filters, payload in client.store["calls"]:
        columns = [col for col, _ in filters]
        if op == "insert":
            # 새 행은 필터가 아니라 저장값에 소유자·날짜가 박힙니다.
            assert (payload or {}).get("user_id") == "user-a"
            assert (payload or {}).get("usage_date") == DAY_ONE.isoformat()
            continue
        assert "user_id" in columns, f"{op} 쿼리에 user_id 필터가 없습니다(§0-3-8)"
        if op == "select":
            assert "usage_date" in columns, "조회는 사용자 + 날짜로 좁혀야 합니다"


def test_counter_resets_when_the_date_changes(quota_db):
    """자정이 지나면(날짜가 바뀌면) 다시 처음부터 셉니다."""
    client = _fake_client()
    limit = quota_db.DAILY_OCR_UPLOAD_LIMIT

    for _ in range(limit):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    with pytest.raises(quota_db.OcrQuotaExceeded):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)

    next_day = quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_TWO)
    assert next_day["used"] == 1 and next_day["remaining"] == limit - 1

    stored = {r["usage_date"]: int(r["used_count"]) for r in client.store["rows"]}
    assert stored == {DAY_ONE.isoformat(): limit, DAY_TWO.isoformat(): 1}, (
        "어제 행을 덮어쓰지 않고 새 날짜 행이 따로 생겨야 합니다(사용 기록 보존)"
    )


def test_today_is_decided_on_the_server_in_kst(quota_db):
    """'자정'의 기준은 브라우저 로컬 시간이 아니라 **서버가 정한 한국시간(KST)** 입니다.

    (이 프로젝트가 화면에서 '오늘'을 정할 때 이미 쓰는 기준과 같습니다 — 새 관례를
     만들지 않았습니다.)
    """
    assert quota_db.KST is not None, "zoneinfo 가 있는 환경에서는 KST 로 판단해야 합니다"
    assert str(quota_db.KST) == "Asia/Seoul"
    before = _datetime.now(quota_db.KST).date()
    value = quota_db.ocr_usage_today()
    after = _datetime.now(quota_db.KST).date()
    assert value in (before, after)          # 자정을 막 지나는 순간에도 흔들리지 않게
    assert isinstance(value, _date)


def test_quota_fails_closed_when_storage_is_not_connected(quota_db):
    """저장소(Supabase)가 없으면 **기존 관례 그대로 막습니다** — 무제한 허용이 아닙니다.

    `fetch_holdings()` 등 이 파일의 모든 사용자 데이터 함수가 클라이언트 없이는
    `ScorecardError` 를 던집니다. 한도 카운터만 예외를 두면, 횟수를 세지 못하는 상태에서
    유료 API 만 열리는 정반대 방향의 사고가 됩니다.
    """
    with pytest.raises(quota_db.ScorecardError):
        quota_db.consume_ocr_quota(None, "user-a", usage_date=DAY_ONE)
    with pytest.raises(quota_db.ScorecardError):
        quota_db.fetch_holdings(None, "user-a")          # 기존 함수도 같은 동작(관례 확인)
    with pytest.raises(quota_db.ScorecardError):
        quota_db.consume_ocr_quota(_fake_client(), "", usage_date=DAY_ONE)


def test_storage_failure_does_not_silently_allow_the_paid_call(quota_db):
    """카운터 기록이 실패하면 조용히 통과시키지 않고 예외를 올립니다(§0-1)."""
    client = _fake_client(fail=True)
    with pytest.raises(quota_db.ScorecardError):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)


def test_corrupt_counter_value_is_not_treated_as_zero(quota_db):
    """읽을 수 없는 값을 0으로 넘겨짚으면 한도가 조용히 초기화됩니다 — 그러지 않는지 확인."""
    client = _fake_client(rows=[{
        "id": "row-1", "user_id": "user-a",
        "usage_date": DAY_ONE.isoformat(), "used_count": "??",
    }])
    with pytest.raises(quota_db.ScorecardError):
        quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)


def test_quota_status_reads_without_incrementing(quota_db):
    """표시용 조회는 카운터를 건드리지 않아야 합니다."""
    client = _fake_client()
    quota_db.consume_ocr_quota(client, "user-a", usage_date=DAY_ONE)
    for _ in range(3):
        status = quota_db.ocr_quota_status(client, "user-a", usage_date=DAY_ONE)
    assert status["used"] == 1
    assert status["remaining"] == quota_db.DAILY_OCR_UPLOAD_LIMIT - 1
    assert int(client.store["rows"][0]["used_count"]) == 1


def test_limit_is_checked_before_the_paid_api_call_in_ui(quota_db):
    """화면 배선 — 한도 차감이 **유료 호출보다 먼저** 일어나는지(순서가 곧 비용입니다)."""
    handler = _upload_handler_source()
    assert "consume_ocr_quota" in handler, "업로드 핸들러가 한도를 전혀 확인하지 않습니다"
    assert handler.index("consume_ocr_quota") < handler.index("extract_holdings_from_image"), (
        "한도 확인이 유료 API 호출보다 뒤에 있으면 한도를 넘겨도 돈이 나갑니다"
    )
    # 유료 호출이 아예 없는 업로드(용량 초과)는 한도를 소모하지 않아야 합니다.
    assert handler.index("len(image_bytes) > MAX_OCR_IMAGE_BYTES") < handler.index("consume_ocr_quota"), (
        "서버 쪽 용량 검사는 한도 차감보다 먼저 끝나야 합니다"
    )


def test_limit_exceeded_is_shown_to_the_user_not_silently_ignored(quota_db):
    """§0-1 — 한도 초과를 조용히 무시하지 않고 사람이 읽을 문장으로 보여줍니다."""
    message = quota_db.OCR_QUOTA_EXCEEDED_MESSAGE
    assert str(quota_db.DAILY_OCR_UPLOAD_LIMIT) in message, "몇 회 제한인지 문구에 있어야 함"
    assert "한도" in message and "내일" in message and "직접 입력" in message, (
        "왜 안 되는지 · 언제 다시 되는지 · 지금 대신 쓸 방법까지 알려줘야 합니다"
    )
    handler = _upload_handler_source()
    assert "except ScorecardError as exc:" in handler, (
        "한도 초과 예외를 잡아 화면에 보여주는 갈래가 없으면 조용한 실패가 됩니다"
    )
    quota_branch = _source_block(handler, "except ScorecardError as exc:", "except Exception as exc:")
    assert "_show_ocr_error(" in quota_branch and "return" in quota_branch


def test_manual_entry_is_never_blocked_by_the_upload_limit(quota_db):
    """수동 입력 폼은 한도와 무관하게 계속 쓸 수 있어야 합니다(오너 지시)."""
    page_src = _page_source()
    submit_src = _source_block(page_src, "    def _submit() -> None:", "\ndef _render_currency_block(")
    assert "consume_ocr_quota" not in submit_src, (
        "직접 입력 저장 경로(_submit)가 업로드 한도를 소모하면 안 됩니다"
    )
    assert "add_lot(" in submit_src, "직접 입력 저장 경로는 그대로 살아 있어야 합니다"
    # 입력창·추가 버튼은 OCR 플래그 블록 **밖**에 있어야 합니다(플래그가 꺼져도 동작).
    form_src = _source_block(page_src, "\ndef _render_input_form(", "\ndef _render_currency_block(")
    assert form_src.index("if SCORECARD_OCR_ENABLED:") < form_src.index("query_input = ui.input("), (
        "직접 입력 폼이 OCR 블록 안으로 들어가면 플래그·한도에 묶여버립니다"
    )


def test_limit_number_is_a_single_constant_not_a_magic_number(quota_db):
    """§0-3-10 — 숫자 10을 여기저기 적어두지 않고 상수 하나만 씁니다."""
    page_src = _page_source()
    assert "DAILY_OCR_UPLOAD_LIMIT" in page_src, "화면은 상수를 import 해서 써야 합니다"
    assert f"{quota_db.DAILY_OCR_UPLOAD_LIMIT}회" not in page_src, (
        "화면 문구에 한도 숫자를 직접 적으면 상수를 바꿔도 문구가 따라오지 않습니다"
    )
    db_src = (REPO_ROOT / "utils" / "scorecard_db.py").read_text(encoding="utf-8")
    assert db_src.count("DAILY_OCR_UPLOAD_LIMIT = ") == 1, "한도 정의는 정확히 한 곳"
    # SQL 스키마에도 숫자를 박아두지 않았는지(앱 상수와 어긋나는 두 번째 출처 금지)
    schema = (REPO_ROOT / "sql" / "scorecard_schema.sql").read_text(encoding="utf-8")
    assert "ocr_usage_daily" in schema, "카운터 표가 기존 스키마 파일에 정의돼 있어야 합니다"
    assert f"used_count <= {quota_db.DAILY_OCR_UPLOAD_LIMIT}" not in schema


def test_counter_table_follows_existing_schema_conventions(quota_db):
    """새 저장 방식을 발명하지 않고 기존 표(holdings)와 같은 관례를 따르는지."""
    schema = (REPO_ROOT / "sql" / "scorecard_schema.sql").read_text(encoding="utf-8")
    section = schema[schema.index("create table if not exists public.ocr_usage_daily"):]
    assert "references auth.users (id) on delete cascade" in section, "사용자 삭제 시 함께 정리"
    assert "unique (user_id, usage_date)" in section, "사용자 × 날짜 1행"
    assert "enable row level security" in section, "RLS 없이 두면 남의 카운터가 보입니다"
    assert "auth.uid() = user_id" in section, "본인 행만 읽고 쓰게 하는 정책이 있어야 합니다"
    assert "revoke all on public.ocr_usage_daily from anon" in section
    # 사용자가 스스로 카운터를 되돌리는 길(삭제/감소)이 열려 있으면 한도가 무의미해집니다.
    assert "for delete" not in section, "delete 정책을 열면 행을 지워 한도를 리셋할 수 있습니다"
    assert "사용 횟수는 줄일 수 없습니다" in section, "감소 방지 트리거가 있어야 합니다"


def test_quota_layer_does_not_leak_into_the_ocr_module(quota_db):
    """OCR 모듈은 계속 '네트워크·DB 없이 단독 테스트 가능한' 순수 변환기로 남아야 합니다."""
    ocr_src = _ocr_module_source()
    # (주석에 파일 이름이 등장하는 건 의존이 아니므로 **실제 import 문**만 봅니다.)
    assert not re.search(r"^\s*(from|import)\s+\S*scorecard_db", ocr_src, re.M), (
        "OCR 모듈에 저장소 의존을 넣으면 오프라인 단독 테스트가 깨집니다(§4-3 계층 분리)"
    )
    assert not re.search(r"^\s*(from|import)\s+\S*supabase", ocr_src, re.M | re.I)
    assert "consume_ocr_quota" not in ocr_src
