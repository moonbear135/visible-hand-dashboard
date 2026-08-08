"""
utils/stock_export.py
📥 "종목별 데이터 다운로드" — 한 종목의 전체 레코드를 CSV / JSON 바이트로 변환합니다.

2026-08-08 신설 (TASK_HISTORY #63). 코스피 화면(`views/pegy_view.py`)과 미국주식 화면
(`views/us_stocks_view.py`) 양쪽에서 **같은 파일 형식**을 쓰기 위해 순수 함수만 모아둔 모듈입니다.

설계 원칙
- **streamlit을 import하지 않습니다.** 화면 코드 없이 함수 단위로 직접 호출·검증할 수 있어야
  하기 때문입니다(이 모듈의 함수는 실제 스냅샷 데이터로 오프라인 검증됨).
- **값을 고르거나 요약하지 않습니다** (ENGINEERING_SPEC §0-1). 스냅샷 레코드(`s` 딕셔너리)에
  들어있는 **모든 키를 저장된 순서 그대로** 내보냅니다. 카드에 안 보이는 내부 진단 필드
  (`data_issues`, `collect_errors`, `*_source`, `*_capped` 등)도 전부 포함합니다.
- **결측(None)은 그럴듯한 숫자로 메우지 않고 빈 칸으로 둡니다.** 0이나 평균값으로 채우면
  받는 사람이 실측값과 구분할 수 없게 됩니다.
"""

import csv
import io
import json
import re


# CSV 헤더 — 세로형(필드 1열 / 값 1열) 2컬럼 고정.
# 가로형(필드명이 헤더 행, 값 1행)은 한 종목에 100개 넘는 컬럼이 옆으로 늘어서서
# 엑셀에서 사람이 읽기 어렵습니다(코스피 67개 / 미국 115개 필드). 이 파일은 "한 종목"짜리
# 이므로 세로형이 자연스럽고, 코스피·미국 양쪽에 동일 구조를 씁니다.
CSV_HEADER = ("항목", "값")


def to_export_text(value):
    """
    CSV 셀 하나에 들어갈 문자열로 변환합니다.

    - None -> "" (빈 칸. '데이터 없음'이라는 한국어 문구 대신 빈 칸으로 둬야 엑셀·pandas에서
      결측으로 그대로 읽힙니다. 값을 지어내지 않는다는 점은 동일합니다.)
    - list / dict -> JSON 문자열(ensure_ascii=False) — 원본 구조를 잃지 않고 한글도 그대로.
    - 그 외(숫자·bool·문자열) -> str() 그대로. 자릿수 반올림·천단위 콤마 같은 표시용 가공을
      하지 않아야 받는 사람이 계산에 다시 쓸 수 있습니다.
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def build_stock_csv_bytes(stock):
    """
    종목 레코드 1건을 세로형 CSV 바이트로 변환합니다.

    ⚠️ 인코딩은 반드시 **UTF-8 BOM(`utf-8-sig`)** 입니다. 그냥 utf-8로 주면 윈도우 엑셀이
    파일을 시스템 기본 인코딩(한국어 윈도우=CP949)으로 읽어서 한글이 전부 깨집니다.
    (이 프로젝트의 기존 스냅샷 CSV 다운로드도 같은 이유로 `utf-8-sig`를 씁니다.)
    """
    if not isinstance(stock, dict):
        raise TypeError("build_stock_csv_bytes: 종목 레코드(dict)가 필요합니다.")

    buf = io.StringIO()
    # lineterminator: csv 기본값이 '\r\n'이지만 StringIO에서도 명시해 둡니다(엑셀 호환).
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(list(CSV_HEADER))
    for key, value in stock.items():
        writer.writerow([key, to_export_text(value)])
    return buf.getvalue().encode("utf-8-sig")


def build_stock_json_bytes(stock):
    """
    종목 레코드 1건을 JSON 바이트로 변환합니다.

    - `ensure_ascii=False`: 한글이 유니코드 이스케이프가 아니라 그대로 보이게.
    - `indent=2`: 사람이 열어봤을 때 읽히게.
    - 스냅샷에 저장된 구조 그대로 내보냅니다(요약·필드 선별 없음, §0-1).
    """
    if not isinstance(stock, dict):
        raise TypeError("build_stock_json_bytes: 종목 레코드(dict)가 필요합니다.")
    return json.dumps(stock, ensure_ascii=False, indent=2).encode("utf-8")


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
    `삼성전자_005930_20260808.csv` 형태의 파일명을 만듭니다.
    (여러 종목을 연달아 받아도 파일이 서로 덮어쓰이지 않고 구분됩니다.)
    """
    name_part = sanitize_filename_part(display_name, fallback="stock")
    code_part = sanitize_filename_part(code, fallback="nocode")
    return f"{name_part}_{code_part}_{date_str}.{ext}"
