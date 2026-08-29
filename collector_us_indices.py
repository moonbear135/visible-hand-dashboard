"""
collector_us_indices.py
📈 리포트 모듈 — 미국 벤치마크(S&P 500 · 나스닥 종합) **일별 종가** 수집기 (2026-08-12 신설)

REPORT_WORK_ORDER.md §4 / §9-①(벤치마크 소스 조사) 의 산출물입니다.
결과는 `data/us_index_history.json` 한 파일에 **날짜 → 종가** 로 누적됩니다(공개 데이터라
기존 `data/` 관례대로 GitHub 에 그대로 커밋합니다 — Supabase 에 넣지 않습니다).

-------------------------------------------------------------------------------
🔍 소스 조사 결과 (2026-08-12, 실제 응답을 받아 확인 — 추측 아님, §0-1)
-------------------------------------------------------------------------------
후보 ①  stockanalysis.com — **채택**
    · 이미 이 프로젝트가 쓰고 있는 사이트입니다(미국주식 550종목 수집, 전 종목·ETF 현재가,
      화면 상단 지수 3종). 새로운 약관 리스크가 생기지 않는다는 점이 가장 큽니다.
    · 지수(S&P 500 지수 자체) 페이지는 **없습니다.** 실제로 확인한 결과
      `https://stockanalysis.com/quote/index/SPX/__data.json` 은 데이터가 아니라
      `{"type":"redirect","location":"/symbol-lookup/?q=INDEX-SPX"}` 를 돌려줍니다.
    · 대신 이 프로젝트가 이미 화면 상단 지수에 쓰고 있는 **추종 ETF 프록시**(SPY / ONEQ)의
      "과거 주가(History)" 데이터 엔드포인트가 살아 있습니다:
          https://stockanalysis.com/etf/{symbol}/history/__data.json
      2026-08-12 실응답(ONEQ):
          {"symbol":"ONEQ", "source":"spg", "updated":"Wed, 12 Aug 2026 01:53:52 GMT",
           "data":[ 행… ]}
          행 예시 {"a":104.16,"c":104.16,"h":105.28,"l":103.91,"o":105.28,
                  "t":"2026-08-11","v":194370,"ch":-0.6}
          → 한 번의 요청으로 **약 6개월치 일별 종가**가 옵니다(2026-08-12 재확인 기준
            SPY·ONEQ 모두 125행 = 2026-02-11 ~ 2026-08-11).
      ⚠️ 2026-08-12 재확인(#96): 이 엔드포인트에는 **ETF 이름이 없습니다**(초기 구축 때
         적어 둔 `"name":"Fidelity …"` 는 다른 페이지의 값이었습니다). 종목 확인은 응답이
         스스로 말하는 `symbol` 로 합니다. 또 시세 공급자는 종목마다 달라서
         (SPY=`tiingo`, ONEQ=`spg`) 공급자 이름을 조건으로 걸지 않습니다.
      응답 포맷은 스크리너와 똑같은 SvelteKit "devalue" 직렬화라, #92 에서 만든
      `decode_sveltekit_data_json()` 을 **그대로 재사용**합니다(디코더 중복 구현 없음).

후보 ②  FRED (fred.stlouisfed.org) — **조사 완료, 채택하지 않음**
    · `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500` 로 **지수 자체의** 일별
      종가를 무료·무인증으로 받을 수 있음을 실제 응답으로 확인했습니다
      (시리즈 SP500: "Frequency: Daily, Close", 2016-08-12 ~ 2026-08-11, 10년치.
       나스닥 종합은 시리즈 NASDAQCOM).
    · 그런데 같은 응답의 Notes 에 **S&P Dow Jones Indices LLC 의 재배포 제한**이 명시돼
      있습니다(원문): "Reproduction of S&P 500 in any form is prohibited except with the
      prior written permission of S&P Dow Jones Indices LLC".
    · 이 프로젝트는 2026-08-11(#84)에 **똑같은 성격의 문제**로 KRX OPEN API 를 이미 한 번
      배제했습니다(약관 제6조② 비상업적 이용 한정 vs 오너의 광고 수익화 계획).
      같은 기준을 그대로 적용해 **오너 판단 전까지는 쓰지 않습니다.** 코드에도 넣지
      않았습니다(나중에 오너가 "지수 실값이 꼭 필요하다"고 결정하면 그때 이 주석을
      근거로 재검토).

후보 ③  Stooq CSV / Yahoo Finance chart API / Nasdaq 공식 API — **연결 실패·보류**
    · Stooq(`stooq.com/q/d/l/?s=^spx&i=d`)는 빈 응답, Yahoo(`query1.finance.yahoo.com`)와
      `api.nasdaq.com` 은 응답 자체가 오지 않았습니다(이 개발 환경 기준). 살아있는지조차
      확인 못 한 소스를 코드에 넣지 않습니다(§0-1).

-------------------------------------------------------------------------------
⚠️ 그래서 이 파일이 저장하는 값은 "지수 포인트"가 아니라 "추종 ETF 종가"입니다
-------------------------------------------------------------------------------
S&P 500 지수는 약 6,600포인트인데 SPY 종가는 약 750달러입니다 — **숫자가 다릅니다.**
그래서 이 수집기는 값을 "지수"라고 부르지 않고, 벤치마크 키 이름부터
`SP500_PROXY_SPY` / `NASDAQ_PROXY_ONEQ` 로 두어 **프록시라는 사실이 데이터·화면·DB 어디를
봐도 드러나게** 했습니다(§0-1, 화면 문구도 "S&P 500 추종 ETF(SPY) 종가 기준"으로 표기).

리포트가 쓰는 건 **절대값이 아니라 기간 수익률(끝/시작 − 1)** 이라 프록시로도 목적을
달성합니다. 다만 완전히 같지는 않습니다(ETF 는 운용보수·추적오차·배당락이 있음) — 이 한계도
화면에 그대로 적습니다. 화면 상단 지수 3종이 이미 같은 방식(ETF 프록시)을 쓰고 있고,
그때도 "근사치입니다" 고지를 달았습니다(PROJECT_STATUS §8).

⚠️ 배당 조정가(`a`)가 아니라 **미조정 종가(`c`)** 를 저장합니다. 조정가는 배당이 생길 때마다
   과거 값이 소급해서 바뀌어(=이미 저장한 기록이 나중에 달라져) 리포트 수치가 흔들립니다.
   미조정 종가는 확정되면 바뀌지 않고, 사용자 포트폴리오 쪽도 배당을 반영하지 않는
   "순수 가격 기준"이라 비교 기준이 서로 맞습니다.

-------------------------------------------------------------------------------
지켜야 할 원칙
-------------------------------------------------------------------------------
  · §0-1  실패는 값을 지어내지 않고 그대로 남깁니다. 수집 못 한 날짜는 파일에 아예 없고,
          리포트는 그 날 벤치마크를 "없음"으로 표시합니다(전날 값 복사 금지).
  · §0-3-2 요청 사이에 기존 수집기와 동일한 랜덤 딜레이. 차단(403/429) 신호를 만나면
          재시도를 반복하지 않고 **즉시 중단**하고, 그때까지 받은 분량만 저장합니다.
  · §0-3-1 후행지표 전용 — 장중/프리마켓 값이 아니라 "거래일 종가"만 담습니다.
  · 기존 파일은 한 줄도 고치지 않고 **읽기 전용으로 import 만** 합니다
    (`collector_us_stocks.py` 의 HTTP 헬퍼·devalue 디코더 재사용).

CLI
  python collector_us_indices.py collect     # 수집 후 data/us_index_history.json 갱신
  python collector_us_indices.py show        # 저장된 파일 요약 출력 (네트워크 불필요)
"""

import argparse
import json
import os
import re
import sys

# ⚠️ 기존 미국주식 수집기의 **읽기 전용 재사용**입니다(REPORT_WORK_ORDER.md §7 — 기존 파일을
#    고치지 않되 import 해서 쓰는 것은 권장). 정중한 GET(재시도·차단 감지), devalue 디코더,
#    ET/KST 시각 헬퍼를 그대로 씁니다 — 같은 사이트를 같은 매너로 부르기 위해서입니다.
from collector_us_stocks import (
    USSourceBlockedError,
    _http_get,
    _now_et,
    _now_kst,
    _polite_sleep,
    decode_sveltekit_data_json,
    resolve_collection_session_et,
)

# =============================================================================
# 1. 상수
# =============================================================================
# 과거 주가(History) 데이터 엔드포인트. {symbol} 은 소문자 티커.
US_INDEX_HISTORY_URL_TEMPLATE = "https://stockanalysis.com/etf/{symbol}/history/__data.json"

US_INDEX_HISTORY_FILENAME = "us_index_history.json"

# (벤치마크 키, 화면 표기, 프록시 ETF 티커)
#   · 키 이름에 PROXY 와 실제 ETF 티커를 박아 둔 이유는 위 파일 상단 설명 참고(§0-1).
#
# ⚠️ 2026-08-29 재감사 L7: 네 번째 요소였던 `expected_phrase`(ETF 이름 부분일치 검증 문구)를
# 제거했습니다. 2026-08-12 실응답 확인대로 **과거주가 엔드포인트에는 ETF 이름이 아예 없어**
# `proxy_name` 이 항상 None 이고, 그래서 `proxy_name_verified` 도 항상 None 이었습니다.
# 즉 그 검증 블록과 그에 딸린 경고 블록은 한 번도 실행된 적이 없는 도달 불가 코드였습니다.
# 실제로 작동하는 검증은 응답이 스스로 말하는 티커 대조(source_symbol == proxy_symbol)뿐이라
# 그것만 남깁니다 — "있는 척하는 검증"을 지우는 것이 §0-1 에 맞습니다.
US_INDEX_BENCHMARKS = (
    ("SP500_PROXY_SPY", "S&P 500 (SPY ETF 종가 기준)", "spy"),
    ("NASDAQ_PROXY_ONEQ", "나스닥 종합 (ONEQ ETF 종가 기준)", "oneq"),
)

# 응답 한 행에서 쓰는 키(실응답에서 확인한 그대로). §2-1 정신대로 "몇 번째 열"이 아니라
# 키 이름으로 집습니다.
HISTORY_DATE_KEY = "t"        # "2026-08-11"
HISTORY_CLOSE_KEY = "c"       # 미조정 종가
HISTORY_ADJ_CLOSE_KEY = "a"   # 배당 조정가 — 일부러 저장하지 않습니다(위 설명 참고)

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# -----------------------------------------------------------------------------
# 시세 이력 '블록'을 알아보는 단서 (2026-08-12 버그 수정 #96 — 실응답 재확인)
# -----------------------------------------------------------------------------
# 실제 응답에서 행 목록은 **최상위 바로 아래가 아니라 한 겹 더 안쪽**에 있습니다:
#     {"data": {"id":120, "symbol":"SPY", "source":"tiingo",
#               "updated":"Wed, 12 Aug 2026 12:41:52 GMT", "timestamp":"...",
#               "data":[ {…행…}, {…행…}, … ]},
#      "news":[…], "other":{…}, "source":"tiingo", "trust":{…}}
# 그래서 아래 탐색은 **깊이 우선으로 응답 전체를 훑고**, 행 목록을 담고 있던 dict 에
# 심볼·공급자 같은 메타데이터가 붙어 있으면 가점해 오탐을 줄입니다.
#
# ⚠️ 공급자 이름을 조건으로 걸지 않은 이유: 같은 날 실응답에서 SPY 는 `"source":"tiingo"`
#    였지만 **ONEQ 는 `"source":"spg"`(S&P Global Market Intelligence)** 였습니다.
#    "tiingo 인 노드만" 같은 조건을 걸었다면 나스닥 쪽이 통째로 빠졌을 겁니다(§0-1).
HISTORY_BLOCK_HINT_KEYS = ("symbol", "source", "updated", "timestamp")

# 응답이 아무리 깊어도 이만큼만 파고듭니다(예기치 못한 구조에서 무한정 도는 것 방지).
MAX_SEARCH_DEPTH = 12

# 지나치게 낡은 값이 섞여 들어오는 걸 막는 최소한의 형식 검증(§0-1 범위 검증 습관).
MIN_REASONABLE_CLOSE = 0.01
MAX_REASONABLE_CLOSE = 1_000_000.0


def default_data_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def build_history_url(symbol):
    return US_INDEX_HISTORY_URL_TEMPLATE.format(symbol=str(symbol).strip().lower())


# =============================================================================
# 2. 응답 파싱 (네트워크 없이 단독 테스트 가능한 순수 함수들)
# =============================================================================
def looks_like_history_rows(value):
    """
    과거 주가 표의 '행 목록'인지 판정합니다 — 첫 행이 **거래일 날짜(t)** 와 종가(c)를 가진
    dict 인가.

    ⚠️ 노드 순서/키 이름("data"/"stockData" 등 페이지마다 다름)에 의존하지 않고 **행의
    생김새**로 찾습니다. 사이트가 필드를 더하거나 노드 구성을 바꿔도 잘 버티고, 못 찾으면
    빈 목록을 돌려줘 호출 쪽이 "이번 수집 실패"로 처리합니다(엉뚱한 배열을 억지로 행으로
    해석하지 않음).

    ⚠️ **날짜(t)를 반드시 요구하는 이유**(2026-08-12 #96): 같은 응답 안에는 "지금 이 순간의
    시세(quote)"처럼 `c`/`h`/`l`/`o`/`v` 로 **글자가 겹치는** 다른 스키마가 함께 옵니다.
    그쪽은 날짜별 배열이 아니라 오늘 값 하나뿐이고 `t`(거래일)가 없습니다. 그래서
    "YYYY-MM-DD 형식의 t 를 가진 dict 들의 목록"만 일별 시세 행으로 인정합니다 —
    이름이 비슷한 다른 블록을 시세 이력으로 착각하지 않기 위한 핵심 조건입니다.
    """
    if not isinstance(value, list) or not value:
        return False
    head = value[0]
    if not isinstance(head, dict):
        return False
    if HISTORY_DATE_KEY not in head or HISTORY_CLOSE_KEY not in head:
        return False
    return bool(_DATE_PATTERN.match(str(head.get(HISTORY_DATE_KEY) or "")))


def _history_block_score(container):
    """
    행 목록을 담고 있던 dict 가 '진짜 시세 이력 블록'처럼 생겼는지 점수로 매깁니다.
    (심볼·공급자·갱신시각 같은 메타데이터가 붙어 있을수록 높음 — 위 상수 주석 참고)
    """
    if not isinstance(container, dict):
        return 0
    score = 0
    for key in HISTORY_BLOCK_HINT_KEYS:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            score += 1
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            score += 1
    return score


def iter_history_row_candidates(value, depth=0, seen=None):
    """
    응답 구조를 깊이 우선으로 훑으며 (행 목록, 그 목록을 담고 있던 dict) 후보를 모두 냅니다.

    ⚠️ 이전 버전은 노드의 **최상위 값만** 훑었습니다. 그런데 실제 응답은 행 목록이 한 겹
    더 안쪽(`{"data": {"symbol": ..., "data": [행…]}}`)에 있어서 한 건도 찾지 못했고,
    2026-08-12 첫 자동 실행이 "응답에서 일별 시세 행을 찾지 못했습니다"로 실패했습니다.
    구조가 또 바뀌어도 버티도록 여기서는 **깊이에 의존하지 않고** 재귀로 훑습니다.
    """
    if depth > MAX_SEARCH_DEPTH or not isinstance(value, (dict, list)):
        return
    if seen is None:
        seen = set()
    marker = id(value)
    # 2026-08-29 재감사 L11: 이 가드가 "devalue 는 같은 객체를 여러 곳에서 공유하므로
    # 중복 순회·순환을 막는다"는 원래 의도의 주석이 붙어 있었지만, 실제로는 그렇지 않습니다.
    # `_devalue_deref()`(collector_us_stocks.py)는 공유 인덱스를 참조할 때마다 **매번 새
    # 객체로 펼치므로**, 디코드가 끝난 이 구조에는 객체 공유도 순환도 없습니다 — 즉 지금은
    # `id()` 가 절대 겹치지 않아 이 가드가 실질적으로 아무것도 막지 못합니다(무한 재귀 방지는
    # 위 MAX_SEARCH_DEPTH 가 전담). 무해하지만 devalue 응답이 통째로 복제되어 메모리를 더
    # 씁니다. 그래도 남겨 두는 이유: 디코더 구현이 바뀌어 다시 객체를 공유하게 되면 이 가드가
    # 그대로 방어망이 되므로, §0-3-6 상 이번 감사 범위를 벗어나는 디코더 리팩터링 없이 방어적
    # 코드만 유지합니다.
    if marker in seen:
        return
    seen.add(marker)

    children = value.values() if isinstance(value, dict) else value
    container = value if isinstance(value, dict) else {}
    for child in children:
        if looks_like_history_rows(child):
            yield child, container
        else:
            yield from iter_history_row_candidates(child, depth + 1, seen)


def extract_history_block(decoded_nodes):
    """
    펼쳐진 노드들에서 일별 시세 행 목록과 **그 목록을 담고 있던 블록**을 찾습니다.

    후보가 여럿이면 ① 블록 메타데이터 점수(심볼·공급자 등)가 높은 쪽, ② 그다음 긴 목록
    순으로 고릅니다(뉴스·배당 등 다른 배열이 우연히 비슷하게 생겼을 때의 방어).

    반환: (rows, block) — 못 찾으면 ([], {}).
    """
    best_rows, best_block, best_rank = [], {}, None
    for node_data in decoded_nodes:
        for rows, container in iter_history_row_candidates(node_data):
            rank = (_history_block_score(container), len(rows))
            if best_rank is None or rank > best_rank:
                best_rows, best_block, best_rank = rows, container, rank
    return best_rows, best_block


def extract_history_rows(decoded_nodes):
    """일별 시세 행 목록만 필요할 때 쓰는 얇은 껍데기(`extract_history_block` 참고)."""
    return extract_history_block(decoded_nodes)[0]


def extract_source_info(decoded_nodes, block=None):
    """
    "엉뚱한 종목을 담고 있지 않은지" 확인할 근거를 응답에서 모읍니다.

    · source_symbol   : 블록이 스스로 말하는 티커("SPY"/"ONEQ") — 가장 확실한 확인값입니다.
    · source_provider : 시세 공급자("tiingo"/"spg" 등, 종목마다 다름 — 조건으로 쓰지 않음)
    · source_updated  : 소스가 말하는 갱신 시각(사람이 볼 참고값)
    · proxy_name      : ETF 이름. ⚠️ 2026-08-12 실응답 기준 **과거주가 엔드포인트에는 이름이
                        없습니다.** 없으면 지어내지 않고 None 을 돌려주고, 호출 쪽은 이름
                        검증을 '확인 불가'로 남깁니다(없다고 경고를 띄우지는 않습니다).
    """
    info = {"source_symbol": None, "source_provider": None,
            "source_updated": None, "proxy_name": None}

    if isinstance(block, dict):
        symbol = block.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            info["source_symbol"] = symbol.strip().upper()
        for key in ("source", "updated"):
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                info[f"source_{'provider' if key == 'source' else 'updated'}"] = value.strip()

    for node_data in decoded_nodes:
        if not isinstance(node_data, dict):
            continue
        if info["source_provider"] is None and isinstance(node_data.get("source"), str):
            info["source_provider"] = node_data["source"].strip() or None
        node_info = node_data.get("info")
        if info["proxy_name"] is None and isinstance(node_info, dict):
            name = node_info.get("name") or node_info.get("titleName")
            if name:
                info["proxy_name"] = str(name)
    return info


# (2026-08-29 재감사 L6: `extract_proxy_name()` 삭제 — 참조 0건인 죽은 함수였습니다.
#  필요하면 `extract_source_info(...)["proxy_name"]` 을 직접 쓰면 됩니다.)


def normalize_history_rows(rows):
    """
    원문 행 → `{"date": "YYYY-MM-DD", "close": float}` 목록.

    §0-1: 날짜 형식이 아니거나 종가를 숫자로 읽을 수 없는 행은 **버립니다**(0 이나 추정값으로
    메우지 않음). 같은 날짜가 두 번 나오면 먼저 나온 값을 유지합니다(소스는 최신순 정렬).
    """
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_text = str(row.get(HISTORY_DATE_KEY) or "").strip()
        if not _DATE_PATTERN.match(date_text) or date_text in seen:
            continue
        try:
            close = float(row.get(HISTORY_CLOSE_KEY))
        except (TypeError, ValueError):
            continue
        if not (MIN_REASONABLE_CLOSE <= close <= MAX_REASONABLE_CLOSE):
            continue
        seen.add(date_text)
        normalized.append({"date": date_text, "close": close})
    normalized.sort(key=lambda r: r["date"])
    return normalized


def trim_unconfirmed_rows(rows, confirmed_through_date):
    """
    2026-08-29 재감사 M16 수정: `confirmed_through_date`(=`resolve_collection_session_et()`
    가 계산한 "지금 담아도 되는 거래일", 장마감+30분 규칙)보다 **미래인 행은 버립니다.**

    ⚠️ `merge_closes()` 는 "이미 저장된 날짜는 절대 덮어쓰지 않는다"는 원칙을 지키지만, 그
    원칙은 **처음 저장되는 값이 확정 종가라는 것을 전제로 합니다.** 장중에 한 번이라도 실행되면
    그날 행의 종가가 미확정 값일 수 있고, `merge_closes()` 는 그 값을 영구히 확정 종가 자리에
    고정해 버립니다(그 뒤에는 `value_conflicts` 로 기록만 될 뿐 고칠 방법이 없음). 그래서
    병합 **이전에** 이 함수로 미확정 구간을 잘라 냅니다 — 잘라낸 행은 다음 실행(장마감 이후나
    다음 거래일)에서 정상적으로 다시 들어옵니다(그때는 `confirmed_through_date` 가 그 날짜까지
    올라와 있으므로).

    날짜 문자열이 YYYY-MM-DD 형식이라 문자열 비교가 곧 날짜 비교와 같습니다.

    반환: (kept_rows, trimmed_rows)
    """
    kept, trimmed = [], []
    for row in rows:
        if row["date"] > confirmed_through_date:
            trimmed.append(row)
        else:
            kept.append(row)
    return kept, trimmed


def merge_closes(existing, new_rows):
    """
    이미 저장돼 있던 {날짜: 종가} 에 새로 받은 행들을 합칩니다.

    ⚠️ **이미 기록된 날짜의 값은 덮어쓰지 않습니다.** 소스가 나중에 다른 값을 주면
       (배당 조정·정정 등) 조용히 바꾸는 대신 `conflicts` 로 돌려주고, 호출 쪽이 그 사실을
       파일 metadata 와 로그에 남깁니다 — 매크로 쪽에서 지켜 온 "기록 개변 금지" 원칙과
       같습니다. 값이 정말 잘못됐다면 사람이 보고 판단할 수 있어야 합니다.

    반환: (merged, added_count, conflicts)  conflicts = [(date, 기존값, 새값), ...]
    """
    merged = dict(existing or {})
    added = 0
    conflicts = []
    for row in new_rows:
        date_text, close = row["date"], row["close"]
        if date_text in merged:
            old = merged[date_text]
            # 소수점 오차 수준의 차이는 갈등으로 보지 않습니다.
            if abs(float(old) - float(close)) > 1e-6:
                conflicts.append((date_text, float(old), float(close)))
            continue
        merged[date_text] = close
        added += 1
    return merged, added, conflicts


def load_index_history(data_dir=None):
    """
    저장된 벤치마크 이력 파일을 읽습니다. 파일이 없으면 (에러가 아니라) None —
    아직 한 번도 수집하지 않은 상태일 뿐이고, 리포트 화면은 "벤치마크 없음"으로 표시합니다.
    """
    path = os.path.join(data_dir or default_data_dir(), US_INDEX_HISTORY_FILENAME)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 3. 수집 (네트워크)
# =============================================================================
def fetch_index_history(proxy_symbol):
    """
    프록시 ETF 하나의 과거 종가를 받아옵니다.

    반환: (rows, source_info)
      rows        : normalize_history_rows() 결과 (날짜 오름차순)
      source_info : `extract_source_info()` 결과(티커·공급자·갱신시각·이름, 없으면 None)

    차단(403/429 등)은 `_http_get()` 이 USSourceBlockedError 로 즉시 올립니다(§0-3-2).
    그 밖의 실패는 예외로 올려 호출 쪽이 "이 지수만 건너뛸지"를 판단하게 합니다.
    """
    res = _http_get(build_history_url(proxy_symbol))
    decoded_nodes = decode_sveltekit_data_json(res.text)
    if not decoded_nodes:
        raise ValueError("응답에서 SvelteKit 데이터 노드를 찾지 못했습니다(소스 구조 변경 가능성)")
    raw_rows, block = extract_history_block(decoded_nodes)
    if not raw_rows:
        raise ValueError("응답에서 일별 시세 행을 찾지 못했습니다(소스 구조 변경 가능성)")
    rows = normalize_history_rows(raw_rows)
    if not rows:
        # 행은 찾았는데 날짜·종가를 하나도 못 읽은 경우 — 빈 값으로 파일을 덮지 않습니다(§0-1).
        raise ValueError("일별 시세 행을 찾았지만 날짜·종가를 하나도 읽지 못했습니다"
                         "(소스 구조 변경 가능성)")
    return rows, extract_source_info(decoded_nodes, block)


def run_us_index_history_collector(data_dir=None, delay=True):
    """
    S&P 500 · 나스닥 종합의 프록시 ETF 일별 종가를 받아 `data/us_index_history.json` 에
    누적 저장합니다.

    · 지수 하나가 실패해도 나머지는 계속 진행하고, 실패 사유를 파일에 남깁니다(§0-1).
    · 하나도 못 받았어도 **파일 자체는 씁니다**(L8 — 실패 사유를 남기기 위해). 다만 기존
      `closes`(가격 이력)는 한 글자도 건드리지 않고 그대로 둡니다 — "건드리지 않는 것"은
      가격 데이터이지 파일이 아닙니다. 새로 받은 게 하나라도 있는지는 반환값이 아니라
      `metadata.fetched_any` 로 구분하세요.
    · 차단을 만나면 즉시 멈추고, 그때까지 받은 분량만 저장합니다(§0-3-2).
    · 2026-08-29 재감사 M16: `collector_us_stocks.py` 와 달리 이 수집기에는 장마감 게이트가
      없어, 장중에 실행되면 그날의 미확정 종가가 `merge_closes()` 의 "기록 개변 금지"
      원칙에 의해 **영구히 확정 종가 자리에 고정**될 수 있었습니다. 이제
      `resolve_collection_session_et()` 로 "지금 담아도 되는 거래일"을 구해, 그보다
      미래인 행은 `trim_unconfirmed_rows()` 로 잘라내고 병합합니다.

    반환: 저장한 파일 경로. 실패 사유만 기록한 경우에도 파일은 쓰므로 **항상** 경로를
    돌려줍니다(위 L8 참고) — "이번에 새로 받은 게 있는가"는 `metadata.fetched_any` 로
    확인하세요.
    """
    resolved_dir = data_dir or default_data_dir()
    payload = load_index_history(resolved_dir) or {}
    indices = dict(payload.get("indices") or {})
    warnings = []
    blocked = False
    fetched_any = False
    session = resolve_collection_session_et()
    confirmed_through = session["session_date"]

    print("=" * 70)
    print("[미국 벤치마크 일별 종가] 추종 ETF 프록시에서 수집합니다(지수 포인트 아님)")
    print(f"  확정 거래일 상한(장마감+30분 게이트): {confirmed_through} "
          f"(현재 ET {session['now_et']} {session['tz_abbrev']})")

    for position, (key, label_ko, proxy_symbol) in enumerate(US_INDEX_BENCHMARKS):
        if blocked:
            warnings.append(f"{key}: 앞선 요청이 차단돼 수집을 시도하지 않았습니다.")
            print(f"  ⏭️ {label_ko}: 앞선 차단으로 건너뜀")
            continue
        if delay and position > 0:
            _polite_sleep()

        entry = dict(indices.get(key) or {})
        entry.update({
            "benchmark_symbol": key,
            "label_ko": label_ko,
            "proxy_symbol": proxy_symbol.upper(),
            "is_etf_proxy": True,
            "currency": "USD",
            "source": build_history_url(proxy_symbol),
            "close_kind": "unadjusted_close",
        })

        try:
            rows, source_info = fetch_index_history(proxy_symbol)
        except USSourceBlockedError as exc:
            blocked = True
            entry["last_error"] = f"소스가 요청을 차단했습니다: {exc}"
            indices[key] = entry
            warnings.append(f"{key}: 차단(403/429 등)으로 중단")
            print(f"  ⚠️ {label_ko}: 차단되어 즉시 중단합니다 — {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 사유를 파일에 남기고 다음 지수로
            entry["last_error"] = f"수집 실패: {exc}"
            indices[key] = entry
            warnings.append(f"{key}: 수집 실패 — {exc}")
            print(f"  ⚠️ {label_ko}: 수집 실패 — {exc}")
            continue

        # 2026-08-29 재감사 M16: 확정 거래일보다 미래인 행(=장중 미확정 종가)은 병합 전에
        # 잘라냅니다 — merge_closes() 는 "이미 저장된 값은 안 덮어씀"만 지킬 뿐, 처음
        # 들어오는 값이 확정 종가인지는 보장하지 않기 때문입니다.
        rows, trimmed = trim_unconfirmed_rows(rows, confirmed_through)
        if trimmed:
            note = (f"미확정 거래일 {len(trimmed)}건({', '.join(r['date'] for r in trimmed)})은 "
                    f"장마감+30분 게이트({confirmed_through} 상한)에 걸려 이번엔 담지 않았습니다 "
                    "— 다음 실행에서 확정되면 정상적으로 들어옵니다.")
            warnings.append(f"{key}: {note}")
            print(f"  ⏳ {label_ko}: {note}")
        if not rows:
            # 확정 종가가 하나도 없으면(예: 장마감+30분 전에 실행) 이번 지수는 조용히
            # 건너뜁니다 — entry 는 건드리지 않아 last_error 도 남기지 않습니다(진짜 실패가
            # 아니라 "아직 확정 안 됨"이라는 정상 상태이기 때문).
            print(f"  ⏭️ {label_ko}: 이번 응답에 확정 거래일 행이 없어 건너뜁니다")
            continue

        # 엉뚱한 ETF 를 담고 있지 않은지 확인합니다(§0-1 — 소스가 바뀌면 조용히 틀린 값을
        # 쌓지 않고 경고를 남깁니다). 값 자체는 그대로 저장하되, 검증 결과를 붙입니다.
        #
        # 1순위는 **응답이 스스로 말하는 티커**입니다. 2026-08-12 실응답 확인 결과 과거주가
        # 엔드포인트에는 ETF 이름이 아예 없고(`{"symbol":"SPY", "source":"tiingo", …}`),
        # 이름으로만 검증하면 정상 응답에도 매번 거짓 경고가 붙습니다.
        source_symbol = source_info.get("source_symbol")
        symbol_verified = (source_symbol == proxy_symbol.upper()) if source_symbol else None
        entry["source_symbol"] = source_symbol
        entry["source_provider"] = source_info.get("source_provider")
        entry["source_updated"] = source_info.get("source_updated")
        entry["proxy_symbol_verified"] = symbol_verified
        # (2026-08-29 재감사 L7: proxy_name / proxy_name_verified 기반 검증 제거 —
        #  이 엔드포인트 응답에 ETF 이름이 없어 항상 None 이라 도달 불가였습니다.)
        if symbol_verified is False:
            note = (f"응답이 말하는 티커가 요청과 다릅니다"
                    f"(요청 {proxy_symbol.upper()} / 응답 {source_symbol!r}) — 확인 필요")
            warnings.append(f"{key}: {note}")
            print(f"  ⚠️ {label_ko}: {note}")
        elif symbol_verified is None:
            note = "응답에서 티커를 찾지 못해 종목 확인을 하지 못했습니다(값은 그대로 저장)"
            warnings.append(f"{key}: {note}")
            print(f"  ⚠️ {label_ko}: {note}")

        merged, added, conflicts = merge_closes(entry.get("closes") or {}, rows)
        entry["closes"] = dict(sorted(merged.items()))
        entry["count"] = len(merged)
        entry["first_date"] = min(merged) if merged else None
        entry["last_date"] = max(merged) if merged else None
        entry["last_collected_at_kst"] = _now_kst().isoformat()
        entry["last_error"] = None
        if conflicts:
            # 기록을 덮어쓰지 않고 사실만 남깁니다(위 merge_closes 주석 참고).
            entry["value_conflicts"] = [
                {"date": d, "stored": old, "source_now": new} for d, old, new in conflicts[:50]
            ]
            warnings.append(
                f"{key}: 이미 저장된 날짜 {len(conflicts)}건의 값이 소스와 다릅니다"
                "(덮어쓰지 않고 기록만 남깁니다)"
            )
        else:
            entry.pop("value_conflicts", None)

        indices[key] = entry
        fetched_any = True
        print(f"  ✅ {label_ko}: 응답 {len(rows)}행 / 신규 {added}일 / 누적 {len(merged)}일 "
              f"(최신 {entry['last_date']} = {merged.get(entry['last_date'])})")

    # =========================================================================
    # ⚠️ 2026-08-29 재감사 L8: 두 지수가 **모두** 실패한 날은 예전엔 파일을 아예 건드리지
    # 않고 끝냈습니다. 그런데 위 실패 처리 경로들은 실패 사유를 `entry["last_error"]` 와
    # `warnings` 에 **메모리 안에서만** 담아 두므로, 그 사유가 어디에도 남지 않고 사라졌습니다.
    # 파일만 보면 "어제 값 그대로 = 아무 일 없었음"과 구분이 안 됩니다.
    # 이제 **기존 closes(가격 이력)는 한 글자도 건드리지 않고** 실패 사유(last_error)와
    # metadata.warnings 만 갱신해 저장합니다
    # (collector_us_stocks.py 의 metadata.failed_tickers 패턴과 같은 취지).
    # =========================================================================
    os.makedirs(resolved_dir, exist_ok=True)
    json_path = os.path.join(resolved_dir, US_INDEX_HISTORY_FILENAME)
    payload = {
        "metadata": {
            "collected_at_et": _now_et().isoformat(),
            "collected_at_kst": _now_kst().isoformat(),
            "source_template": US_INDEX_HISTORY_URL_TEMPLATE,
            "is_etf_proxy": True,
            "close_kind": "unadjusted_close",
            "source_blocked": blocked,
            "warnings": warnings,
            # 2026-08-29 재감사 L8: 이번 실행에서 종가를 한 건이라도 새로 받았는지.
            # False 면 아래 closes 는 **이전 실행에서 쌓인 값 그대로**이고, 각 지수의
            # last_error 에 이번 실패 사유가 들어 있습니다.
            "fetched_any": fetched_any,
            "description": (
                "리포트 모듈용 미국 벤치마크 일별 종가. ⚠️ 지수 포인트가 아니라 추종 ETF"
                "(SPY=S&P500, ONEQ=나스닥종합)의 미조정 종가입니다 — 기간 수익률 비교 용도."
            ),
        },
        "indices": indices,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if fetched_any:
        print(f"[미국 벤치마크] 저장 완료 -> {json_path}")
    else:
        print("⚠️ 한 지수도 수집하지 못했습니다 — 기존 종가는 그대로 두고 실패 사유만 "
              f"기록했습니다(metadata.fetched_any=False) -> {json_path}")
    print("=" * 70)
    # 2026-08-29 재감사(M16 작업 중 추가 발견 → 조사 후 원복): 처음엔 "fetched_any=False 면
    # None" 으로 고쳐 함수 docstring 과 맞추려 했지만, 그러면 L8 회귀 테스트
    # (test_reaudit_total_failure_records_reason_without_touching_closes)가 깨집니다 — L8은
    # "전부 실패해도 실패 사유를 남기려면 파일을 반드시 써야 한다"를 의도적으로 요구하고,
    # 그 근거로 반환값이 not None 이어야 한다고 명시합니다. 즉 **코드가 아니라 docstring 이
    # 낡은 쪽**입니다(파일은 실패해도 항상 씀 — 위 L8 주석 참고). 아래 docstring 을
    # 고쳐 실제 계약(항상 경로를 반환, "아무것도 못 받았다"는 metadata.fetched_any 로 구분)에
    # 맞췄습니다. `test_us_index_collector_run` 의 `result is None` 기대치 3곳도 이 계약대로
    # 함께 고쳤습니다(그 기대치가 L8 이전에 쓰여 낡아 있었습니다).
    return json_path


# =============================================================================
# 4. CLI
# =============================================================================
def cmd_collect(args):
    run_us_index_history_collector(delay=not args.no_delay)


def cmd_show(_args):
    payload = load_index_history()
    if not payload:
        print("저장된 벤치마크 이력 파일이 없습니다 (아직 한 번도 수집하지 않음).")
        return
    meta = payload.get("metadata") or {}
    print("=" * 70)
    print(f"수집 시각(KST): {meta.get('collected_at_kst')}")
    print(f"프록시 여부   : {meta.get('is_etf_proxy')} / 종가 종류: {meta.get('close_kind')}")
    for key, entry in (payload.get("indices") or {}).items():
        closes = entry.get("closes") or {}
        last = entry.get("last_date")
        print(f"  · {key:<20} {entry.get('label_ko')}")
        print(f"      프록시 {entry.get('proxy_symbol')} (응답 티커 {entry.get('source_symbol')}"
              f" / 공급자 {entry.get('source_provider')}) "
              f"티커검증={entry.get('proxy_symbol_verified')}")
        print(f"      {entry.get('first_date')} ~ {last} / {len(closes)}일 "
              f"/ 최신 종가 {closes.get(last)}")
        if entry.get("last_error"):
            print(f"      ⚠️ 마지막 오류: {entry['last_error']}")
    for warning in meta.get("warnings") or []:
        print(f"  ⚠️ {warning}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="미국 벤치마크(S&P500·나스닥) 일별 종가 수집기 — 리포트 모듈용",
    )
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="수집 후 data/us_index_history.json 갱신")
    p_collect.add_argument("--no-delay", action="store_true",
                           help="요청 간 딜레이 없이 실행(테스트용 — 평소엔 쓰지 마세요)")
    p_collect.set_defaults(func=cmd_collect)

    p_show = sub.add_parser("show", help="저장된 파일 요약 출력(네트워크 불필요)")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
