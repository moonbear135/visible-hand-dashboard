"""
utils/stock_history.py
📈 "종목별 시계열 이력" — 매일 수집이 성공적으로 끝났을 때, 각 종목의 **화면 카드에 실제로
보이는 재무 지표만** 골라 날짜별로 한 줄씩 누적 기록합니다.

2026-08-09 신설 (TASK_HISTORY #64). 왜 만들었나:
  - #63의 "종목별 데이터 다운로드"는 `data/*_latest.json` 의 **오늘 하루치 스냅샷**을,
    그것도 `is_visible` / `badge_bg` / `f_target_cap_reason` 같은 **개발자용 내부 필드까지**
    통째로 내보냈습니다. 오너 지적: "받아보니 분석용 재무 데이터가 아니라 디버깅 로그였고,
    하루치라 추세를 볼 수가 없다."
  - 이 프로젝트가 지금까지 이력화한 건 `data/pegy_summary_history.json` /
    `data/us_summary_history.json` 뿐인데, 그건 **시장 전체 요약(중앙값)** 이지 종목별이 아닙니다.
  - 따라서 종목별 이력은 **이 파일이 처음 도입되는 날부터** 쌓입니다.
    ⚠️ 과거 날짜를 소급해서 만들어 채우지 않습니다 (ENGINEERING_SPEC §0-1 지어내기 금지).
    과거 스냅샷을 보관해 둔 적이 없으므로 만들어낼 근거 자체가 없습니다.

설계 결정 (근거)
  1) **시장별 파일 1개**(`data/kospi200_stock_history.csv`, `data/us_stocks_history.csv`)에
     전 종목 이력을 담고, 다운로드 시점에 해당 종목 행만 필터링합니다.
     - 종목별 파일 분리(750개)는 매일 750개 파일이 바뀌어 git 커밋 diff가 사람이 볼 수 없게
       되고, 상장폐지·티커 변경 때 고아 파일이 남습니다.
  2) **CSV**(JSON 아님): 이 저장소에서 "날짜별로 계속 append 되는 시계열"의 기존 관례는
     `market_history.csv` 입니다. 또 JSON(indent=2)으로 쌓으면 한 종목 한 줄이 30줄이 되어
     하루 200~550종목 × 수백 일이면 파일이 수백 MB로 폭주하고 git diff도 못 읽습니다.
     CSV는 하루치가 정확히 종목 수만큼의 **추가된 줄**로 보입니다.
  3) 파일 안의 컬럼명은 **영문 키**(스냅샷 원본 키와 동일)입니다. 화면 라벨 문구는 앞으로도
     다듬을 수 있는데, 그때마다 과거 이력의 헤더가 어긋나면 안 되기 때문입니다.
     사람이 받는 다운로드 파일에서만 아래 `label` 을 헤더로 씁니다(→ `utils/stock_export.py`).
  4) 인코딩은 `utf-8-sig`(BOM). 오너가 이 파일을 엑셀로 직접 열어볼 수 있고, BOM이 없으면
     한국어 윈도우 엑셀이 CP949로 읽어 종목명이 전부 깨집니다.

streamlit 을 import 하지 않습니다 — 수집기(배치)와 화면이 같은 모듈을 공유해야 하고,
화면 없이 함수 단위로 오프라인 검증(`tests/test_stock_history.py`)이 가능해야 하기 때문입니다.
"""

import csv
import io
import os

# 🌐 조회(`load_stock_history`)가 파일을 여는 단일 창구. 원격 로드가 꺼져 있으면(기본값)
#    예전과 똑같은 로컬 파일 읽기이고, 켜져 있으면 최신성 추적·전역 배너를 함께 받습니다.
#    ⚠️ **기록(write) 경로는 이 모듈에서 예전 그대로 로컬 파일에 직접 씁니다** — 기록하는
#       쪽은 GitHub Actions 안의 수집기이고, 그 환경에는 저장소가 통째로 체크아웃돼 있어
#       원격을 거칠 이유가 없습니다(그리고 원격은 애초에 읽기 전용입니다).
from utils import data_source


# =============================================================================
# 0. 파일 위치
# =============================================================================
KOSPI_HISTORY_FILENAME = "kospi200_stock_history.csv"
US_HISTORY_FILENAME = "us_stocks_history.csv"
INDICATOR_HISTORY_FILENAME = "indicator_kr_history.csv"  # 「여기서부터는 신앙입니다」(7번째 모듈)

KOSPI_KEY_FIELD = "code"      # 코스피는 6자리 종목코드가 식별자
US_KEY_FIELD = "symbol"       # 미국은 티커가 식별자
INDICATOR_KEY_FIELD = "code"  # 보조지표도 코스피와 같은 6자리 종목코드

DATE_FIELD = "date"
DATE_LABEL = "날짜"

# 이력 기록을 허용하는 수집 상태. 수집기의 status 판정(valid_ratio 기준)과 같은 값입니다.
# FAILED(검증 통과율 붕괴)는 기록하지 않습니다 — 영구 이력에 한번 박힌 오염된 하루는
# 되돌릴 수 없기 때문입니다(§0-1).
RECORDABLE_STATUSES = ("SUCCESS", "DEGRADED")


def stock_history_path(filename):
    """저장소 루트의 data/ 아래 경로를 돌려줍니다 (수집기·화면 모두 같은 파일을 봅니다)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", filename)


# =============================================================================
# 1. 기록할 필드 — "카드 화면에 실제로 보이는 재무 데이터"만
#
# 선정 기준 (오너 요청 2026-08-09)
#   ✅ 넣는 것 : views/pegy_view.py · views/us_stocks_view.py 의 종목 카드에 **숫자/문구로
#                렌더링되는** 지표. 코드에서 실제 렌더링 라인을 확인한 것만 넣었습니다.
#   ❌ 빼는 것 : 배지 색상 hex(`badge_bg`/`badge_fg`), 내부 진단·사유 필드
#                (`*_source`, `*_capped`, `*_reason`, `*_uncapped`, `data_issues`,
#                 `collect_errors`, `consistency_warnings`, `value_trap_severity`,
#                 `value_trap_basis`, `is_visible`, `is_valid`, `is_unverified`,
#                 `missing_fields`, `url`, `score_excluded_items` 등).
#                → 이건 코딩 디버깅용이지 투자 분석용이 아닙니다.
#
# 각 항목: (스냅샷 키, 사람이 읽는 한국어 라벨, 값 종류)
#   값 종류: "text" 문자열 / "num" 숫자 / "bool" 예·아니오
# 코스피·미국 공통 지표는 **라벨 문구를 동일하게** 맞췄습니다(단위 표기만 원/USD로 다름).
# =============================================================================

KOSPI_HISTORY_FIELDS = [
    (DATE_FIELD,      DATE_LABEL,                    "text"),
    ("rank",          "시가총액 순위",                 "num"),
    ("name",          "종목명",                       "text"),
    ("code",          "종목코드",                     "text"),
    # 2026-08-26 신설(TASK_HISTORY #151 후속, 오너 요청 — "라벨이 있으면 더 좋긴하지
    # 그것까지 보여놔줘"). collector_kospi200.py가 이미 계산해 저장해 둔 값을 그대로
    # 내보낼 뿐이며, 값이 없는(구버전 스냅샷 등) 종목은 빈 칸으로 정직하게 남습니다(§0-1).
    ("market",        "시장구분(KOSPI/KOSDAQ)",          "text"),
    ("price",         "현재가(원)",                   "num"),
    ("quant_score",   "퀀트 스코어(획득)",             "num"),
    ("score_max",     "퀀트 스코어(만점)",             "num"),
    ("badge",         "밸류에이션 배지",               "text"),
    ("vol",           "변동성 판정",                   "text"),
    ("value_trap",    "착시 저평가(가치주 덫)",         "bool"),
    # 💎 자본효율성 지표 바
    ("t_roe",         "ROE(Trailing, %)",             "num"),
    ("f_roe",         "ROE(Forward, %)",              "num"),
    ("roic",          "ROIC(%)",                      "num"),
    # 📜 Trailing 섹션
    ("t_per",         "PER(Trailing, 배)",            "num"),
    ("t_eps",         "EPS(Trailing, 원)",            "num"),
    ("t_pbr",         "PBR(배)",                      "num"),
    ("ev_ebitda",     "EV/EBITDA(배)",                "num"),
    ("dps",           "주당배당금 DPS(원)",            "num"),
    # ⬇️ 2026-08-30 재감사(공유인프라) M-13 반영 — 카드에는 배지·툴팁으로 보이는데
    # 이력 CSV에는 없던 필드들. 오너 결정(2026-08-30): "카드에는 보이는데 CSV엔
    # 빠지면 말이 안 됨 — 정보는 항상 같아야 한다"(TASK_HISTORY #166 백로그 항목).
    # 값 자체는 내부 코드/사유 문자열이라(예: dps_source="derived_from_div_yield")
    # 카드의 자연어 문구를 그대로 복제하진 않지만(§0-3-10, 렌더링 로직 중복 금지),
    # 같은 정보(왜 이 값인지)는 CSV에서도 확인할 수 있습니다.
    ("dps_source",    "DPS 값 출처(코드)",             "text"),
    ("sh_return",     "배당수익률(%)",                 "num"),
    ("sh_return_basis", "배당수익률 산출 기준",          "text"),
    ("return_total",  "배당 총 규모",                  "text"),
    ("dividend_data_unverified", "배당 데이터 미확정 여부", "bool"),
    ("dividend_unverified_reason", "배당 데이터 미확정 사유", "text"),
    ("t_pegy",        "PEGY(Trailing)",               "num"),
    ("t_fair",        "과거 적정가(Trailing, 원)",      "num"),
    ("t_fair_capped", "과거 적정가 상한 적용 여부",      "bool"),
    ("t_fair_uncapped", "과거 적정가(상한 적용 전, 원)", "num"),
    ("t_per_measured", "PER(Trailing) 원본값(부호 보존)", "num"),
    ("is_trailing_loss", "Trailing 적자 여부",          "bool"),
    ("loss_evidence", "적자 판정 근거",                "text"),
    ("t_eps_calculated", "EPS(Trailing) 역산값 여부",   "bool"),
    ("graham_target", "그레이엄 넘버(원)",             "num"),
    ("graham_is_financial_sector", "그레이엄 넘버 제외 사유(금융업종)", "bool"),
    # 🚀 Forward 섹션
    ("f_per",         "PER(Forward, 배)",             "num"),
    ("f_eps",         "EPS(Forward, 원)",             "num"),
    ("growth",        "예상 EPS 성장률(%)",            "num"),
    ("growth_source", "성장률 값 출처(코드)",           "text"),
    ("growth_score_capped", "고성장 추정 보수반영 여부", "bool"),
    ("f_target",      "목표주가(원)",                  "num"),
    ("f_target_capped", "목표주가 상한 적용 여부",       "bool"),
    ("f_target_cap_reason", "목표주가 상한 적용 사유",   "text"),
    ("f_target_uncapped", "목표주가(상한 적용 전, 원)",  "num"),
    # 🔒 데이터 검증/제외 사유 — Forward 마스킹 박스·배점 제외 툴팁에 표시되는 것과 같은 정보
    ("is_valid",      "유효 종목 여부(데이터 검증 통과)", "bool"),
    ("is_unverified", "데이터 검증 미확정 여부",         "bool"),
    ("reject_reason", "데이터 거부/차단 사유",           "text"),
    ("unverified_reason", "데이터 검증 미확정 사유",     "text"),
    ("is_negative_growth", "성장률 마이너스(역성장) 여부", "bool"),
    ("forward_data_missing", "Forward 데이터 없음 여부", "bool"),
    ("forward_missing_fields", "Forward 데이터 중 없는 항목", "text"),
    ("score_excluded_items", "퀀트 스코어 배점 제외 항목", "text"),
]

US_HISTORY_FIELDS = [
    (DATE_FIELD,           DATE_LABEL,                    "text"),
    ("rank",               "시가총액 순위",                 "num"),
    ("name_kr",            "종목명(한글)",                  "text"),
    ("name_en_clean",      "종목명(영문)",                  "text"),
    ("symbol",             "티커",                         "text"),
    ("price",              "장마감 종가(USD)",              "num"),
    ("price_calculated",   "종가 역산값 여부",              "bool"),
    ("quant_score",        "퀀트 스코어(획득)",             "num"),
    ("score_max",          "퀀트 스코어(만점)",             "num"),
    ("badge",              "밸류에이션 배지",               "text"),
    ("beta",               "베타(5년)",                    "num"),
    ("value_trap",         "착시 저평가(가치주 덫)",         "bool"),
    ("is_reit",            "리츠(REIT) 여부",              "bool"),
    # 💎 자본효율성 지표 바
    ("market_cap",         "시가총액(USD)",                 "num"),
    ("t_roe",              "ROE(Trailing, %)",             "num"),
    ("roic",               "ROIC(%)",                      "num"),
    ("roa",                "ROA(%)",                       "num"),
    ("piotroski_f",        "F-Score(0~9)",                 "num"),
    # 🎯 애널리스트 컨센서스 바 (소스 실측)
    ("analyst_target",     "애널리스트 목표주가(USD)",       "num"),
    ("analyst_consensus",  "애널리스트 투자의견",            "text"),
    ("analyst_count",      "커버 애널리스트 수",             "num"),
    # 📜 Trailing 섹션
    ("t_per",              "PER(Trailing, 배)",            "num"),
    ("price_ffo",          "P/FFO(리츠, 배)",              "num"),
    ("t_eps",              "EPS(Trailing, USD)",           "num"),
    ("t_pbr",              "PBR(배)",                      "num"),
    ("ev_ebitda",          "EV/EBITDA(배)",                "num"),
    ("bps",                "BPS(USD)",                     "num"),
    ("dps",                "주당배당금 DPS(USD)",           "num"),
    ("div_yield",          "배당수익률(%)",                 "num"),
    ("buyback_yield",      "자사주 매입 수익률(%)",          "num"),
    ("payout_ratio",       "배당성향(%)",                   "num"),
    ("sh_return",          "주주환원율(%)",                 "num"),
    # ⬇️ 2026-08-30 재감사(공유인프라) M-13 반영 — 코스피와 같은 취지(위 KOSPI_HISTORY_FIELDS
    # 주석 참고). 오너 결정(2026-08-30, TASK_HISTORY #166 백로그 항목).
    ("dividend_data_unverified", "배당 데이터 미확정 여부", "bool"),
    ("dividend_unverified_reason", "배당 데이터 미확정 사유", "text"),
    ("t_pegy",             "PEGY(Trailing)",               "num"),
    ("t_fair",             "과거 적정가(Trailing, USD)",     "num"),
    ("t_fair_capped",      "과거 적정가 상한 적용 여부",      "bool"),
    ("t_fair_uncapped",    "과거 적정가(상한 적용 전, USD)",  "num"),
    ("t_fair_floored",     "과거 적정가 장부가 바닥값 적용 여부", "bool"),
    ("is_trailing_loss",   "Trailing 적자 여부",            "bool"),
    ("loss_evidence",      "적자 판정 근거",                "text"),
    ("graham_target",      "그레이엄 넘버(USD)",            "num"),
    ("graham_is_financial_sector", "그레이엄 넘버 제외 사유(금융업종)", "bool"),
    # 🚀 Forward 섹션
    ("g_eff",              "실효성장률 g_eff(%p)",          "num"),
    ("g_eff_capped",       "실효성장률 상한 적용 여부",       "bool"),
    ("g_eff_uncapped",     "실효성장률(상한 적용 전, %p)",    "num"),
    ("f_per",              "PER(Forward, 배)",             "num"),
    ("f_eps",              "EPS(Forward, USD)",            "num"),
    ("f_eps_calculated",   "EPS(Forward) 역산값 여부",       "bool"),
    ("f_pegy",             "PEGY(Forward)",                "num"),
    ("growth",             "3년 EPS 성장 전망(%)",          "num"),
    ("growth_score_capped", "고성장 추정 보수반영 여부",      "bool"),
    ("floor_price",        "PBR 기준 바닥가(USD)",          "num"),
    ("f_target",           "모델 목표주가(USD)",            "num"),
    ("f_target_capped",    "목표주가 상한 적용 여부",         "bool"),
    ("f_target_cap_reason", "목표주가 상한 적용 사유",        "text"),
    ("f_target_uncapped",  "목표주가(상한 적용 전, USD)",     "num"),
    ("f_target_floored",   "목표주가 장부가 바닥값 적용 여부", "bool"),
    # 🔒 데이터 검증/제외 사유 — Forward 마스킹 박스·배점 제외 툴팁에 표시되는 것과 같은 정보
    ("is_valid",           "유효 종목 여부(데이터 검증 통과)", "bool"),
    ("is_unverified",      "데이터 검증 미확정 여부",         "bool"),
    ("reject_reason",      "데이터 거부/차단 사유",           "text"),
    ("unverified_reason",  "데이터 검증 미확정 사유",         "text"),
    ("forward_data_missing", "Forward 데이터 없음 여부",     "bool"),
    ("forward_missing_fields", "Forward 데이터 중 없는 항목", "text"),
    ("forward_per_extreme", "Forward PER 극단치 여부",       "bool"),
    ("score_excluded_items", "퀀트 스코어 배점 제외 항목",     "text"),
]



INDICATOR_HISTORY_FIELDS = [
    (DATE_FIELD,             DATE_LABEL,           "text"),
    ("code",                 "종목코드",             "text"),
    ("name",                 "종목명",               "text"),
    ("rsi",                  "RSI(14)",             "num"),
    ("rsi_signal",           "RSI 판독",             "text"),   # overbought/oversold/neutral
    ("macd",                 "MACD",                "num"),
    ("macd_signal_line",     "MACD 시그널선",         "num"),
    ("macd_histogram",       "MACD 히스토그램",       "num"),
    ("macd_cross",           "MACD 크로스",           "text"),  # golden/dead/(빈칸)
    ("bb_upper",             "볼린저 상단",           "num"),
    ("bb_lower",             "볼린저 하단",           "num"),
    ("bb_mid",               "볼린저 중심선",         "num"),
    ("bb_percent_b",         "볼린저 %B",            "num"),
    ("bb_position",          "볼린저 위치",           "text"),  # above_upper/below_lower/inside
    ("verdict_score",        "종합판정 점수",         "num"),
    ("verdict_label",        "종합판정",             "text"),
    ("bars_used",            "사용 종가 봉 수",       "num"),
    ("warmup_insufficient",  "워밍업 부족",           "bool"),
    ("unavailable_reasons",  "산출 불가 사유",         "text"),
]
# ⚠️ 이 필드셋은 utils/indicators.py 의 calculate_rsi/calculate_macd/calculate_bollinger/
#    combine_verdict 반환값을 그대로 옮긴 것입니다. RSI/MACD/볼린저 원값 자체는 "지어낸
#    계산값"(🧮)이 아니라 실측 종가로부터의 결정론적 파생값(📐)이라 §0-1 예외 없이 그대로
#    기록합니다 — 산출 불가한 지표는 이 함수들이 이미 None을 돌려주므로 빈 칸으로 남습니다
#    (to_storage_cell이 None -> "" 처리). 작업 지시서: TECHNICAL_INDICATOR_WORK_ORDER.md.


def field_keys(fields):
    return [key for key, _label, _kind in fields]


def field_labels(fields):
    return [label for _key, label, _kind in fields]


def field_kind_map(fields):
    return {key: kind for key, _label, kind in fields}


def field_label_map(fields):
    return {key: label for key, label, _kind in fields}


# =============================================================================
# 2. 값 변환 — 저장은 "원본 그대로", 없으면 빈 칸
# =============================================================================
def to_storage_cell(value, kind):
    """
    스냅샷 값을 CSV 셀 문자열로 바꿉니다.

    - None -> "" (빈 칸). '데이터 없음' 같은 문구를 넣으면 숫자 컬럼이 문자열로 오염되고,
      0이나 평균으로 채우는 건 §0-1 정면 위반입니다.
    - bool -> "true"/"false" (파일 안에서는 기계가 읽기 좋은 형태로, 사람이 받는
      다운로드 파일에서는 '예/아니오'로 바꿔 보여줍니다).
    - list -> "; " 로 이어 붙인 문자열. 2026-08-30 재감사(공유인프라) M-13 반영 —
      `score_excluded_items`/`loss_evidence`/`forward_missing_fields`처럼 카드에서
      리스트를 이어 붙여 보여주는 내부 진단값을 이력 CSV에도 똑같이 담기 위해서입니다
      (§0-1 "카드와 CSV의 정보는 항상 같아야 한다" — 오너 2026-08-30 결정).
      빈 리스트는 "데이터 없음"이 아니라 빈 칸입니다(§0-1).
    - 그 외 -> str() 그대로. 반올림·천단위 콤마 같은 표시용 가공을 하지 않아야
      받는 사람이 계산에 다시 쓸 수 있습니다.
      (⚠️ 코스피 t_pbr/ev_ebitda 는 스냅샷에 문자열 '3.21' 로 들어있습니다 — 값을 바꾸지
       않고 그대로 씁니다.)
    """
    if value is None:
        return ""
    if kind == "bool" or isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


def build_history_row(stock, date_str, fields):
    """종목 레코드 1건 -> 이력 CSV 한 줄(dict). 선정된 필드 외에는 아무것도 담지 않습니다."""
    row = {}
    for key, _label, kind in fields:
        if key == DATE_FIELD:
            row[key] = date_str
            continue
        row[key] = to_storage_cell(stock.get(key), kind)
    return row


def build_history_rows(stocks, date_str, fields):
    return [build_history_row(s, date_str, fields) for s in stocks]


# =============================================================================
# 3. 읽기 / 쓰기
# =============================================================================
def read_history_rows(path):
    """
    이력 CSV 전체를 dict 목록으로 읽습니다.
    파일이 없거나 깨졌으면 **빈 목록**을 돌려줍니다(값을 지어내지 않음).
    """
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]
    except Exception as e:
        print(f"⚠️ 종목별 이력 파일을 읽지 못했습니다({path}): {e}")
        return []


def _detect_dropped_history_columns(path, keys):
    """
    2026-08-30 재감사(공유인프라) Medium-2 대응 헬퍼.

    `path`에 이미 파일이 있다면, 그 CSV 헤더에는 있었는데 이번에 쓸 `keys`에는 없는
    컬럼 이름을 돌려줍니다. 헤더 한 줄만 읽으므로 파일 전체를 파싱하지 않습니다.
    """
    if not path or not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), None)
    except Exception:
        return set()
    if not header:
        return set()
    return set(header) - set(keys)


def write_history_rows(path, rows, fields):
    """
    이력 CSV 전체를 다시 씁니다(헤더=영문 키, 인코딩=utf-8-sig).

    ⚠️ 2026-08-30 재감사(공유인프라) Medium-2 — 이 함수는 "전체를 읽어 새 헤더로 통째로
    다시 쓰는" 방식입니다. 그래서 `KOSPI_HISTORY_FIELDS`/`US_HISTORY_FIELDS`에서 키 하나를
    지우거나 이름을 바꾸면, **이미 몇 달치 쌓여 있던 그 컬럼의 과거 행 값까지 전부** 다음
    수집 한 번으로 조용히·영구히 사라집니다. 백업도 확인 절차도 없어 되돌릴 수 없습니다.
    그래서 기존 파일 헤더에는 있었는데 이번 `fields`에는 없는 컬럼을 발견하면, 사라지기
    직전이라는 경고를 서버 로그에 크게 남깁니다(§0-1 — 실데이터가 사라지는 걸 조용히
    넘기지 않기). 화면에는 노출하지 않습니다 — 이건 수집기(배치) 실행 중 콘솔에만
    남는 진단이고, 화면 사용자에게 보여줄 사용자 시나리오가 아닙니다.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = field_keys(fields)
    dropped = _detect_dropped_history_columns(path, keys)
    if dropped:
        print(
            f"🔴 [stock_history] 경고: {path} 의 기존 컬럼 {sorted(dropped)} 이(가) "
            f"새 필드 목록에 없습니다 — 지금 다시 쓰면 그 컬럼의 과거 이력이 전부 "
            f"사라집니다. KOSPI_HISTORY_FIELDS/US_HISTORY_FIELDS에서 실수로 지운 게 "
            f"아닌지 확인하세요."
        )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in keys})
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())


def append_daily_history(path, stocks, date_str, fields):
    """
    그날 치 종목별 이력을 파일 끝에 **추가**합니다. 기존 기록은 절대 지우지 않습니다.

    같은 날짜(date_str) 기록이 이미 있으면 **그 날짜 행만 새 값으로 교체**합니다.
    (미국 워크플로우처럼 하루에 크론이 두 번 도는 구조에서 재실행이 일어나도 같은 날이
     두 번 쌓이지 않게 하는 방어 로직입니다. 실제로는 `--skip-if-not-ready` 가 먼저
     걸러내므로 평상시엔 발동하지 않습니다.)

    반환: {"row_count": 추가된 행 수, "replaced": 교체된 기존 행 수, "total_rows": 파일 총 행 수}
    """
    if not date_str:
        raise ValueError("append_daily_history: 기록할 날짜(date_str)가 필요합니다.")

    existing = read_history_rows(path)
    kept = [r for r in existing if r.get(DATE_FIELD) != date_str]
    replaced = len(existing) - len(kept)

    new_rows = build_history_rows(stocks, date_str, fields)
    write_history_rows(path, kept + new_rows, fields)
    return {"row_count": len(new_rows), "replaced": replaced, "total_rows": len(kept) + len(new_rows)}


def record_daily_history(path, stocks, date_str, fields, status):
    """
    ✅ 수집기가 호출하는 단 하나의 진입점.

    **수집이 성공적으로 끝났을 때만** 기록합니다:
      - 이 함수가 불린다는 것 자체가 "크롤링·스코어링·스냅샷 저장이 예외 없이 끝났다"는 뜻입니다
        (중간에 소스 차단/유니버스 실패가 나면 수집기가 그 전에 예외로 중단되어 여기 도달하지 못함).
      - 그 위에 한 겹 더: status 가 SUCCESS/DEGRADED 가 아니면(=FAILED 등) 기록하지 않습니다.
      - 종목이 0건이면 기록하지 않습니다(빈 날짜 행을 만들지 않음).

    반환: {"recorded": bool, "reason": str, ...append_daily_history 결과}
    """
    if status not in RECORDABLE_STATUSES:
        return {"recorded": False, "row_count": 0, "replaced": 0,
                "reason": f"수집 상태가 {status} 라서 이력에 기록하지 않았습니다 "
                          f"(허용: {', '.join(RECORDABLE_STATUSES)}) — 오염된 하루가 영구 이력에 남지 않게."}
    if not stocks:
        return {"recorded": False, "row_count": 0, "replaced": 0,
                "reason": "기록할 종목이 0건이라 이력에 아무것도 쓰지 않았습니다."}

    result = append_daily_history(path, stocks, date_str, fields)
    result["recorded"] = True
    result["reason"] = (
        f"{date_str} 기준 {result['row_count']}종목 기록"
        + (f" (같은 날짜 기존 {result['replaced']}행 교체)" if result["replaced"] else "")
    )
    return result


# =============================================================================
# 4. 조회 — 다운로드 화면이 쓰는 함수
# =============================================================================
def load_stock_history(path, key_field, key_value):
    """
    한 종목의 이력만 골라 **날짜 오름차순**으로 돌려줍니다.
    이력이 아직 하루치뿐이면 행이 1개인 것도 정상입니다(오늘 처음 쌓이기 시작했으므로).

    🌐 2026-08-17 — 파일을 여는 일은 `utils/data_source.py` 가 합니다.
       예전에는 이 함수만 `open()` 으로 직접 읽어서 최신성 추적 밖에 있었고, 원격 로드가
       켜지고 Render Build Filters 로 `data/**` 가 무시되면 **배포 시점에 얼어붙은 사본**을
       계속 내려주면서도 전역 배너가 뜨지 않았습니다(§0-1 위반). 이제 다른 스냅샷들과 같은
       경로를 탑니다.
       ⚠️ 시그니처·반환값(행 dict 목록, 실패 시 빈 목록)은 그대로입니다 —
          `views/pegy_view.py`·`views/us_stocks_view.py`(Streamlit)도 영향 없습니다.
    """
    if not key_value or not path:
        return []
    wanted = str(key_value)
    rows = []
    try:
        text, error, _version = data_source.read_text(path, encoding="utf-8-sig")
        if error is not None or text is None:
            return []
        # ⚠️ 여기서 `csv.DictReader(text.splitlines())` 처럼 전체를 리스트로 펼치지 않습니다.
        #    이력이 몇 년 쌓이면 전 종목 × 수백 일이라 파일이 수십 MB가 되는데, 한 종목만
        #    필요한 화면이 그 전부를 dict 목록으로 들고 있을 이유가 없습니다. `io.StringIO`
        #    를 **한 줄씩** 흘려보내며 원하는 종목 행만 담습니다(원본 설계 그대로).
        for r in csv.DictReader(io.StringIO(text, newline="")):
            if (r.get(key_field) or "") == wanted:
                rows.append(dict(r))
    except Exception as e:
        print(f"⚠️ 종목별 이력 파일을 읽지 못했습니다({path}): {e}")
        return []
    rows.sort(key=lambda r: r.get(DATE_FIELD) or "")
    return rows
