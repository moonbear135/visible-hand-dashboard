"""
utils/stock_export.py
📥 "종목별 데이터 다운로드" — 한 종목의 **날짜별 이력 표**를 CSV / JSON 바이트로 변환합니다.

2026-08-08 신설(TASK_HISTORY #63) → **2026-08-09 전면 재작성(TASK_HISTORY #64).**

무엇이 바뀌었나 (오너 지적 2건)
  1) 예전에는 스냅샷 레코드(`s` 딕셔너리)의 **모든 키**를 그대로 내보냈습니다. 받아보니
     `is_visible`, `badge_bg`(색상 hex), `f_target_cap_reason`, `data_issues`,
     `consistency_warnings` 같은 **코딩 디버깅용 필드**가 대부분이라 재무 분석에 쓸 수
     없었습니다. → 이제는 **화면 카드에 실제로 보이는 재무 지표만**, 그것도 영문 변수명이
     아니라 **한국어 라벨**로 내보냅니다. 필드 목록·라벨의 단일 출처는
     `utils/stock_history.py` 의 `KOSPI_HISTORY_FIELDS` / `US_HISTORY_FIELDS` 입니다.
  2) 예전에는 "오늘 하루치" 세로형(`항목,값`) 파일이었습니다. → 이제는 **날짜가 행, 지표가
     열**인 시계열 표입니다. 한 종목의 PER·목표가·퀀트 스코어가 날짜별로 어떻게 변했는지
     엑셀에서 바로 그래프로 그릴 수 있습니다.

⚠️ 종목별 이력은 `utils/stock_history.py` 가 도입된 날부터 쌓이기 시작합니다.
   과거 스냅샷을 보관해 둔 적이 없어 **소급 생성은 하지 않습니다**(§0-1). 이력이 하루치뿐이면
   행이 1줄인 파일이 나오는 게 정상입니다.

streamlit 을 import 하지 않습니다(순수 함수) — 화면 없이 오프라인 검증이 가능해야 하기 때문.
"""

import csv
import io
import json
import re

from utils.stock_history import DATE_FIELD


# =============================================================================
# 1. 값 표시 변환
# =============================================================================
def to_display_text(cell, kind):
    """
    이력 파일에 저장된 셀 문자열 -> 사람이 받는 CSV 셀 문자열.

    - "" (수집 못 한 값) -> "" 그대로. '데이터 없음' 문구나 0으로 채우지 않습니다(§0-1).
    - bool -> "예" / "아니오" (헤더가 한국어인데 값만 true/false면 읽기 어색합니다)
    - 숫자·문자열 -> 저장된 원본 문자열 그대로 (반올림·콤마 등 표시용 가공 없음)
    """
    if cell is None:
        return ""
    text = str(cell)
    if kind == "bool":
        if text == "":
            return ""
        return "예" if text.lower() in ("true", "1", "y", "yes") else "아니오"
    return text


def to_display_value(cell, kind):
    """
    이력 파일에 저장된 셀 문자열 -> JSON 에 담을 파이썬 값.

    CSV 파일은 모든 값이 문자열이라, 되읽을 때 숫자 컬럼을 숫자로 복원해야 JSON 을 받는
    쪽에서 바로 계산에 쓸 수 있습니다. **필드 종류가 미리 선언돼 있는 컬럼만** 변환하므로
    종목코드 `005930` 같은 문자열이 숫자 5930 으로 망가지지 않습니다.
    """
    if cell is None or str(cell) == "":
        return None
    text = str(cell)
    if kind == "bool":
        return text.lower() in ("true", "1", "y", "yes")
    if kind == "num":
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            # 숫자로 선언된 컬럼인데 숫자가 아니면, 값을 버리지 않고 원문 그대로 남깁니다.
            return text
    return text


# =============================================================================
# 2. CSV / JSON 바이트 생성
# =============================================================================
def build_history_csv_bytes(rows, fields):
    """
    한 종목의 이력 행 목록을 **날짜=행 / 지표=열** CSV 바이트로 만듭니다.
    헤더는 한국어 라벨입니다.

    ⚠️ 인코딩은 반드시 **UTF-8 BOM(`utf-8-sig`)** 입니다. 그냥 utf-8로 주면 한국어 윈도우
    엑셀이 CP949로 읽어 한글이 전부 깨집니다(이 저장소의 다른 CSV 다운로드도 동일 관례).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([label for _key, label, _kind in fields])
    for row in rows:
        writer.writerow([to_display_text(row.get(key), kind) for key, _label, kind in fields])
    return buf.getvalue().encode("utf-8-sig")


def build_history_json_bytes(rows, fields):
    """
    같은 내용을 JSON 배열(날짜순 객체 목록)로 만듭니다.
    - 키는 한국어 라벨, `ensure_ascii=False` 라 한글이 이스케이프 없이 그대로 보입니다.
    - 수집하지 못한 값은 `null` 입니다(0이나 문구로 채우지 않음).
    """
    payload = []
    for row in rows:
        payload.append({label: to_display_value(row.get(key), kind) for key, label, kind in fields})
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def history_date_range(rows):
    """이력의 첫/마지막 날짜를 돌려줍니다(없으면 (None, None)). 화면 안내 문구용."""
    dates = [r.get(DATE_FIELD) for r in rows if r.get(DATE_FIELD)]
    if not dates:
        return None, None
    return min(dates), max(dates)


# =============================================================================
# 3. 파일명
# =============================================================================
def sanitize_filename_part(text, fallback="unknown"):
    """
    파일명에 쓸 수 없는 문자를 `_`로 치환합니다.

    실제로 문제가 되는 사례: 미국 티커 `BRK/B`, `BRK/A` — `/`가 들어가면 브라우저가 경로로
    해석하거나 저장에 실패합니다. 한글은 파일명에 그대로 쓸 수 있으므로 유지합니다.
    """
    if text is None:
        return fallback
    cleaned = re.sub(r"[^\w\-]+", "_", str(text), flags=re.UNICODE).strip("_")
    return cleaned or fallback


def build_export_filename(display_name, code, date_str, ext):
    """
    `삼성전자_005930_이력_20260809.csv` 형태의 파일명을 만듭니다.
    (`이력`을 넣어, 하루치 스냅샷을 받던 예전 파일과 섞이지 않게 구분합니다.)
    """
    name_part = sanitize_filename_part(display_name, fallback="stock")
    code_part = sanitize_filename_part(code, fallback="nocode")
    return f"{name_part}_{code_part}_이력_{date_str}.{ext}"
