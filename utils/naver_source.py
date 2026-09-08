"""네이버 증권 **출처 전환 스위치** — 값의 단일 출처(§0-3-10). 이 파일 한 곳에만 있습니다.

⚠️ 2026-09-08 신설 (이관 4단계 "배선", `NAVER_MIGRATION_WORK_ORDER.md` §9).

배경: 네이버가 **2026-09-10** 에 구 증권 서비스(`finance.naver.com`)를 종료합니다.
`collector_kospi200.py` 는 구 HTML 을 긁는 경로(현행)와 신 JSON API 를 부르는 경로(준비 완료)를
**둘 다** 갖고 있고, **어느 쪽을 쓸지는 이 스위치 하나**로 정합니다.

오너 지시(2026-09-08): *"구 경로를 지우지 않고 출처 전환 스위치로 붙이는 것 — 구 주소가
살아 있는 동안 양쪽 대조 가능, 문제 생기면 되돌리기 쉬움. 이 방식으로 가자."*

─────────────────────────────────────────────────────────────────────────────
📌 오너가 스위치를 켜는 방법 (코딩 몰라도 됩니다 — 글자 하나 바꾸는 일입니다)
─────────────────────────────────────────────────────────────────────────────

  깃허브 저장소 → `.github/workflows/scrape.yml` 파일을 열어
  아래 줄을 찾습니다(주석으로 꺼져 있습니다):

      # NAVER_SOURCE: new_api

  줄 맨 앞의 `# ` 두 글자를 지워 이렇게 만들고 저장(커밋)하면 **다음 실행부터 신 출처**입니다:

      NAVER_SOURCE: new_api

  되돌리려면 다시 `# ` 를 붙이거나 값을 `legacy` 로 바꾸면 됩니다. 코드는 건드리지 않습니다.

  로컬에서 손으로 돌릴 때는 터미널에서:
      NAVER_SOURCE=new_api python collector_kospi200.py

─────────────────────────────────────────────────────────────────────────────
🔴 규칙
─────────────────────────────────────────────────────────────────────────────

① **기본값은 구 출처(`legacy`)** 입니다. 실전 전환은 오너 승인 사항(§0-3-6)이라 세션이
   기본값을 신 출처로 바꾸지 않습니다. 테스트가 이 사실을 지킵니다.
② 기본값은 **이 파일에만** 적습니다. 워크플로우 YAML 이나 수집기 본문에 `legacy` 를 다시
   적어 두면 한 곳만 고쳐졌을 때 어느 쪽이 진짜인지 알 수 없게 됩니다(§0-3-10).
③ 환경변수에 **모르는 값**이 오면 조용히 기본값으로 떨어지지 않고 **예외로 멈춥니다**(§0-1).
   `new-api`·`NEW_API`·`newapi` 같은 오타로 "켰다고 믿었는데 구 출처가 돌고 있는" 상황은
   §0-1 이 말하는 겉보기 정상이라, 실패로 보여야 합니다. (대소문자·앞뒤 공백만 관용.)
④ 어느 출처로 만든 데이터인지 **산출물(스냅샷 metadata)에 남깁니다**(§0-1) —
   `describe_naver_source()` 가 그 블록을 만듭니다. 이 기록이 없으면 나중에
   "이 숫자가 어디서 온 것인지" 아무도 모릅니다.

담당 에이전트: `kr-stocks`
"""
from __future__ import annotations

import os

__all__ = [
    "NAVER_SOURCE_ENV_VAR",
    "NAVER_SOURCE_LEGACY",
    "NAVER_SOURCE_NEW_API",
    "NAVER_SOURCES",
    "DEFAULT_NAVER_SOURCE",
    "resolve_naver_source",
    "describe_naver_source",
    "switch_instructions",
]

# 환경변수 이름. 워크플로우(`scrape.yml`)와 로컬 실행이 **같은 이름**을 씁니다.
NAVER_SOURCE_ENV_VAR = "NAVER_SOURCE"

# 스위치가 가질 수 있는 값 — 딱 두 개.
NAVER_SOURCE_LEGACY = "legacy"     # 구 finance.naver.com HTML 파싱 (현행 · 2026-09-10 종료 예고)
NAVER_SOURCE_NEW_API = "new_api"   # 신 stock.naver.com JSON API (KRX 고정, 섀도 대조 완료)
NAVER_SOURCES = (NAVER_SOURCE_LEGACY, NAVER_SOURCE_NEW_API)

# 🔴 기본값 = 구 출처. 여기 **한 줄**이 저장소 전체의 기본값입니다.
#    바꾸는 것은 오너 결정입니다(§0-3-6). 워크플로우 한 줄로 켜는 방법이 위에 있습니다.
DEFAULT_NAVER_SOURCE = NAVER_SOURCE_LEGACY

# 출처별 설명 — 스냅샷 metadata 에 그대로 실립니다(사람이 나중에 읽는 용도).
_SOURCE_INFO = {
    NAVER_SOURCE_LEGACY: {
        "label": "구 네이버 증권 HTML (finance.naver.com)",
        "list_endpoint": "https://finance.naver.com/sise/sise_market_sum.naver?sosok=<0|1>&page=<n>",
        "detail_endpoint": "https://finance.naver.com/item/main.naver?code=<종목코드>",
        "exchange": "KRX (구 사이트는 정규장 종가만 표시)",
        "note": "2026-09-10 종료 예고 대상. 종료 후에는 파싱이 실패해 값이 None 으로 남습니다(§0-1).",
    },
    NAVER_SOURCE_NEW_API: {
        "label": "신 네이버 증권 JSON API (stock.naver.com)",
        "list_endpoint": ("https://stock.naver.com/api/domestic/market/stock/default"
                          "?tradeType=KRX&marketType=ALL&orderType=marketSum&startIdx=<페이지>&pageSize=20"),
        "detail_endpoint": "https://stock.naver.com/api/domestic/detail/<종목코드>/detail?codeType=KRX",
        "exchange": "KRX 고정 — NXT(넥스트레이드) 주소는 코드가 차단 (§1-5-11)",
        "note": ("종가 채택 조건: 목록 응답 marketStatus 가 전 종목 CLOSE 일 때만 (아니면 수집 중단). "
                 "섀도 대조 2026-09-08: 516종목 현재가·ROE·EPS·PER·상장주식수 100% 일치."),
    },
}

# Forward ROE·EV/EBITDA 는 스위치와 **무관하게** 항상 이 페이지에서 읽습니다.
# (finance.naver.com 종료 대상이 아닌 별도 도메인이고, 두 경로가 같은 파서를 씁니다.)
WISEREPORT_ENDPOINT = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd=<종목코드>"


def switch_instructions() -> str:
    """로그·문서에 그대로 찍는 '켜는 법' 한 문단. 오너가 로그만 보고도 따라 할 수 있게."""
    return (
        f"출처 전환: 환경변수 {NAVER_SOURCE_ENV_VAR}={NAVER_SOURCE_NEW_API} 로 신 출처, "
        f"{NAVER_SOURCE_ENV_VAR}={NAVER_SOURCE_LEGACY} (또는 미설정) 로 구 출처. "
        f"깃허브 자동 실행은 .github/workflows/scrape.yml 의 '# {NAVER_SOURCE_ENV_VAR}: {NAVER_SOURCE_NEW_API}' "
        "줄에서 앞의 '# ' 를 지우면 켜집니다. 기본값은 utils/naver_source.py 한 곳에만 있습니다."
    )


def resolve_naver_source(environ=None) -> str:
    """환경변수를 읽어 스위치 값을 돌려줍니다. 미설정이면 기본값(구 출처).

    🔴 모르는 값이면 **예외**입니다. 오타를 기본값으로 눌러 담으면 "켰다고 믿는데 안 켜진"
       상태가 조용히 생깁니다(§0-1).
    """
    env = os.environ if environ is None else environ
    raw = env.get(NAVER_SOURCE_ENV_VAR)
    if raw is None or not str(raw).strip():
        return DEFAULT_NAVER_SOURCE
    value = str(raw).strip().lower()
    if value not in NAVER_SOURCES:
        raise ValueError(
            f"🔴 환경변수 {NAVER_SOURCE_ENV_VAR}={raw!r} 를 이해할 수 없습니다. "
            f"허용값: {', '.join(NAVER_SOURCES)}. 오타를 기본값으로 눌러 담지 않고 멈춥니다(§0-1). "
            + switch_instructions()
        )
    return value


def describe_naver_source(source: str) -> dict:
    """스냅샷 metadata 에 넣을 출처 기록 블록(§0-1 — 어디서 온 숫자인지 남깁니다)."""
    if source not in NAVER_SOURCES:
        raise ValueError(f"알 수 없는 출처: {source!r} (허용값: {', '.join(NAVER_SOURCES)})")
    info = dict(_SOURCE_INFO[source])
    return {
        "naver_source": source,
        "is_default": source == DEFAULT_NAVER_SOURCE,
        "switch": f"환경변수 {NAVER_SOURCE_ENV_VAR} (기본값은 utils/naver_source.py 의 DEFAULT_NAVER_SOURCE)",
        "wisereport_endpoint": WISEREPORT_ENDPOINT,
        **info,
    }
