"""네이버 **신** 증권(`stock.naver.com`) JSON API 응답 파서 — 순수 함수만, 네트워크 없음.

⚠️ 2026-09-07 신설 (#211, `NAVER_MIGRATION_WORK_ORDER.md`). 배경:
네이버가 **2026-09-10 부로 기존 증권 서비스 종료**를 예고했습니다. 구
`finance.naver.com` 의 HTML 을 긁던 자리를 신 사이트의 JSON API 로 옮기기 위한 모듈입니다.

🔴 **이 파일은 네트워크를 건드리지 않습니다.** `requests` 를 import 하지 않습니다.
   HTTP 요청·딜레이·재시도·서킷브레이커는 호출부(`collector_kospi200.py`)의 몫이고,
   여기는 **"받은 JSON 을 우리 필드로 옮기는 일"만** 합니다. 그래야 실제 응답 픽스처
   (`tests/fixtures/naver_new_api/`)만으로 전량 테스트할 수 있습니다.

🔴 **이 모듈은 아직 실전에 배선돼 있지 않습니다** (§0-3-6 — 신규 기능은 독립 모듈로 만들고
   오너 승인 후 반영). `collector_kospi200.py` 는 여전히 구 HTML 파서를 씁니다.

─────────────────────────────────────────────────────────────────────────────
📌 이 파일이 코드로 강제하는 함정 4가지 (전부 2026-09-07 실측으로 확인된 것)
─────────────────────────────────────────────────────────────────────────────

① 🔴 **NXT(넥스트레이드) 금지** — §1-5-11
   신 사이트가 쓰는 주소는 대부분 `tradeType=NXT` / `codeType=NXT` 입니다. NXT 는
   15:40~20:00 애프터마켓이 열려 있어 **저녁에 크롤링하면 종가가 아니라 시간외가**를
   받습니다. 실측(2026-09-07 저녁, SK하이닉스): KRX 종가 1,783,000 / 애프터마켓
   1,780,000 / 목록 API(NXT) 1,784,000 — **세 값이 다 달랐습니다.**
   틀린 값이 아니라 "다른 시장의 값"이라 산티체크에도 안 걸립니다(§0-1 겉보기 정상).
   → `assert_krx_source()` 가 NXT 주소를 **예외로 막습니다.**

② 🔴 **`krxEps` 를 `eps` 로 착각 금지** — §1-5-4
   상세 응답에 `eps`(224,313)와 `krxEps`(62,044)가 **둘 다** 있고 3.6배 차이납니다.
   `per`(7.95 = nowPrice ÷ eps)와 맞아떨어지는 쪽은 **`eps`** 입니다.
   `krxEps` 의 정체는 확인하지 않았습니다 — **쓰지 않습니다.**

③ 🔴 **`dividendRate` 는 비율이 아니라 퍼센트** — §1-5-4
   `0.168` 은 0.168% 입니다(3,000 ÷ 1,783,000 × 100 = 0.1683 로 검증).
   비율로 착각하면 **1000배 틀립니다.**

④ 🔴 **목록의 `pbr` 은 전일 종가 기준** — §1-5-10
   목록 `pbr` 4.44616 × 전일종가 1,647,000 → BPS 370,432 = 상세 `bps` 와 정확히 일치.
   현행 `t_pbr` 은 **현재가 기준**이라 급등·급락일에 조용히 어긋납니다.
   → 목록 `pbr` 은 `t_pbr` 로 쓰지 않습니다. 상세의 `bps` 로 직접 계산합니다.

─────────────────────────────────────────────────────────────────────────────
관련 문서: `NAVER_MIGRATION_WORK_ORDER.md` §1-5-2 ~ §1-5-13
담당 에이전트: `kr-stocks`
"""
from __future__ import annotations

# 🔴 requests 를 import 하지 않습니다 — 이 모듈은 네트워크를 모릅니다(위 머리말 참고).
# tests/test_naver_stock_api.py 가 이 사실 자체를 검사합니다.

__all__ = [
    "NaverApiSourceError",
    "assert_krx_source",
    "parse_stock_detail",
    "parse_market_list_row",
    "parse_market_list",
    "parse_consensus",
    "DPS_STATUS_VALUES",
]


class NaverApiSourceError(ValueError):
    """받은 응답의 **출처가 우리가 쓰기로 한 것이 아닐 때** 던집니다.

    "값이 이상하다"가 아니라 "애초에 이 응답을 쓰면 안 된다"는 뜻이므로, 조용히 None 을
    돌려주지 않고 예외로 멈춥니다(§0-1 — 실패는 실패로 보여야 합니다).
    """


# `dps_status` 가 가질 수 있는 값 — 구 파서(`fetch_naver_item_dps_and_eps`)와 **같은 어휘**를
# 씁니다. 소비부(scoring·guardrail·화면)가 이 세 갈래를 구분해 처리하도록 이미 만들어져
# 있으므로(2차 감사 1-4 / 재감사 H2), 새 출처가 어휘를 바꾸면 그 구분이 무너집니다.
DPS_STATUS_VALUES = ("not_collected", "no_dividend_confirmed", "collected")

# 상세 응답에서 우리가 **의도적으로 읽지 않는** 필드. 이름이 비슷해 실수하기 쉬운 것들이라
# 목록으로 못 박아 둡니다(테스트가 이 목록을 실제로 검사합니다).
DELIBERATELY_UNUSED_DETAIL_FIELDS = (
    "krxEps",        # ② 위 머리말 — eps 와 3.6배 차이, 정체 미확인
    "listedStock",   # 천주 단위 축약본. 우리는 listedStockCnt(주 단위)를 씁니다
    "estimatedSellPrice", "estimatedBuyPrice",   # 예상체결가 — 후행지표 전용 원칙(§0-3-1)
)


# ─────────────────────────────────────────────────────────────────────────────
# 0. 출처 검증 — NXT 차단
# ─────────────────────────────────────────────────────────────────────────────

def assert_krx_source(url: str) -> None:
    """주소가 **KRX** 를 가리키는지 확인하고, NXT 면 예외를 던집니다.

    막는 형태 두 가지 (2026-09-07 실측):
      - 경로 세그먼트:  `.../realtime/domestic/NXT/stock/000660`
      - 쿼리 파라미터:  `...?tradeType=NXT` · `...?codeType=NXT`

    ⚠️ **화이트리스트가 아니라 블랙리스트입니다.** KRX 라고 명시되지 않은 주소도 통과합니다
    (예: 거래소 파라미터가 아예 없는 주소). NXT 라는 것이 확인된 것만 막습니다 —
    확인하지 않은 것을 "안전하다"고 단정하지 않기 위해서입니다(§0-1).
    """
    if not isinstance(url, str) or not url:
        raise NaverApiSourceError("출처 URL 이 비어 있습니다 — 어느 시장의 값인지 확인할 수 없습니다.")
    lowered = url.lower()
    for needle in ("/nxt/", "tradetype=nxt", "codetype=nxt"):
        if needle in lowered:
            raise NaverApiSourceError(
                "🔴 NXT(넥스트레이드) 응답은 쓰지 않습니다 — 15:40~20:00 애프터마켓 가격이 섞여 "
                "종가가 크롤링 시각에 따라 달라집니다(NAVER_MIGRATION_WORK_ORDER.md §1-5-11). "
                f"KRX 주소로 바꾸세요. 받은 주소: {url}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 1. 값 변환 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _num(raw):
    """문자열 숫자를 float 로. **부호를 지우지 않습니다.**

    2차 감사 1-1: 예전 정규식이 적자 기업의 `-` 를 버려 24종목이 흑자로 둔갑했습니다.
    여기서는 `float()` 을 그대로 쓰므로 음수가 음수로 남습니다.

    None / "" / "-" / 변환 실패 → **None(미수집)**. 0 으로 대체하지 않습니다(§0-1).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if text in ("", "-", "N/A", "null", "None"):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int(raw):
    """정수용. 소수점이 붙어 와도(`"224313.0"`) 안전하게 처리합니다."""
    v = _num(raw)
    return None if v is None else int(v)


def _text(raw):
    """빈 문자열은 None 으로. (`etfBaseIdx` 가 `""` 로 옵니다.)"""
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _nonzero(v):
    """0 을 None 으로 바꿉니다 — **PER 전용**.

    구 파서와 같은 규칙입니다(`collector_kospi200.py` 의 `t_per` 처리):
    PER 0 은 실제 값이 아니라 "계산 불가"의 표현이라 미수집으로 둡니다.
    ⚠️ ROE·EPS 에는 쓰지 않습니다 — 그쪽은 0 이 의미 있는 값일 수 있습니다.
    """
    return None if (v is None or v == 0) else v


def _resolve_dps(dividend_raw, div_yield_pct):
    """`dividend` 필드를 (dps, dps_status) 로 옮깁니다.

    🔴 재감사 H2·H3 의 교훈을 그대로 적용합니다 — **"수집 실패"와 "무배당"을 뭉개지 않고,
       무배당은 근거가 둘 다 있을 때만 확정합니다.**

      · `dividend` 가 없음(None)            → `not_collected`  (모름)
      · `dividend` 가 0  **그리고** 배당수익률도 없음 → `no_dividend_confirmed`  (두 근거 일치)
      · `dividend` 가 0  인데 배당수익률은 있음      → `not_collected` + 모순 기록
        (0 원인데 수익률이 나온다는 것은 둘 중 하나가 틀렸다는 뜻이므로 확정하지 않습니다)
      · `dividend` > 0                        → `collected`

    실측 근거(2026-09-07 목록 응답 10종목):
      LG에너지솔루션 `dividend: null`     → 미수집
      SK스퀘어·삼성바이오 `dividend: "0"` + `dividendRate: null` → 무배당 확정
    """
    dps = _num(dividend_raw)
    if dps is None:
        return None, "not_collected", None
    if dps > 0:
        return dps, "collected", None
    # dps == 0 (또는 음수 — 있을 수 없지만 방어)
    if div_yield_pct is None:
        return 0.0, "no_dividend_confirmed", None
    return None, "not_collected", (
        f"모순: 주당배당금 {dps} 인데 배당수익률 {div_yield_pct}% — 확정하지 않고 미수집으로 둡니다"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. 종목 상세  `/api/domestic/detail/<code>/detail?codeType=KRX`
# ─────────────────────────────────────────────────────────────────────────────

def parse_stock_detail(payload: dict, *, source_url: str) -> dict:
    """상세 응답 → 구 `fetch_naver_item_dps_and_eps()` 와 **같은 키 집합**의 dict.

    같은 키를 쓰는 이유: 소비부(`enrich_quant_metrics` 등)를 한 줄도 안 고치고
    출처만 갈아끼울 수 있게 하기 위해서입니다(§0-3-10 — 같은 개념을 두 이름으로 두지 않음).

    이 응답이 **주지 않는 것**(호출부가 다른 출처에서 채워야 합니다):
      · `f_roe` (추정 ROE)  → `navercomp.wisereport.co.kr/v2/company/c1010001.aspx`
      · `ev_ebitda`         → 위와 같은 페이지 (현행 그대로)
    둘 다 None 으로 두고 `errors` 에 사유를 남깁니다 — 조용히 비우지 않습니다(§0-1).
    """
    assert_krx_source(source_url)
    if not isinstance(payload, dict):
        raise NaverApiSourceError(f"상세 응답이 dict 가 아닙니다: {type(payload).__name__}")

    errors: list[str] = []

    code = _text(payload.get("itemcode"))
    if not code:
        raise NaverApiSourceError("상세 응답에 종목코드(itemcode)가 없습니다.")

    price = _num(payload.get("nowPrice"))
    # ② krxEps 가 아니라 eps 입니다. 이 줄을 바꾸면 EPS 가 조용히 3.6배 틀립니다.
    t_eps = _num(payload.get("eps"))
    t_per = _nonzero(_num(payload.get("per")))
    f_eps = _num(payload.get("estimatedEps"))
    f_per = _nonzero(_num(payload.get("estimatedPer")))
    bps = _num(payload.get("bps"))

    # ④ 상세의 `pbr` 은 현재가 기준이라 그대로 쓸 수 있지만, **`bps` 가 있으면 직접 계산**해
    #    현재가와의 정합을 보장합니다. 둘이 어긋나면 그 사실을 기록합니다(§0-1).
    t_pbr = _num(payload.get("pbr"))
    if bps and price and bps != 0:
        computed = price / bps
        if t_pbr is not None and abs(computed - t_pbr) / max(abs(t_pbr), 1e-9) > 0.02:
            errors.append(
                f"PBR 불일치: 응답 {t_pbr} vs 현재가÷BPS {computed:.4f} — 기준 가격이 다를 수 있음"
            )
        t_pbr = computed

    # ③ 퍼센트입니다. 변수 이름에 단위를 박아 둡니다.
    div_yield_pct = _num(payload.get("dividendRate"))
    dps, dps_status, conflict = _resolve_dps(payload.get("dividendAmount"), div_yield_pct)
    if conflict:
        errors.append(conflict)

    errors.append("f_roe 미수집: 이 API 에 없음 — c1010001.aspx 에서 별도 수집 필요")
    errors.append("ev_ebitda 미수집: 이 API 에 없음 — c1010001.aspx 에서 별도 수집 필요")

    return {
        # ── 구 파서와 동일한 키 ───────────────────────────────────────────────
        "t_per": t_per,
        "t_eps": t_eps,
        "f_per": f_per,
        "f_eps": f_eps,
        "div_yield": div_yield_pct,
        "dps": dps,
        "outstanding_shares": _int(payload.get("listedStockCnt")),
        "t_pbr": t_pbr,
        "ev_ebitda": None,
        "f_roe": None,
        "raw_period": _text(payload.get("tradeTime")),
        "dps_status": dps_status,
        "dps_inherited_from": None,   # 신 API 는 우선주도 자기 값을 주므로 상속이 필요 없습니다
        "div_yield_row_found": div_yield_pct is not None,
        "div_yield_row_explicit_na": payload.get("dividendRate") is None,
        "errors": errors,
        # ── 신 API 에서 새로 얻는 것 (구 파서에 없던 키. 접두어로 구분) ────────
        "api_code": code,
        "api_name": _text(payload.get("itemname")),
        "api_price": price,
        "api_bps": bps,
        "api_market_sum_truncated": _num(payload.get("marketSum")),
        "api_security_type": _text(payload.get("type")),          # "ST" = 주식(실측)
        "api_market_status": _text(payload.get("marketStatus")),  # "CLOSE"/"OPEN"
        "api_trade_stop": _text(payload.get("tradeStopYn")),
        "api_market_alert": _text(payload.get("marketAlertType")),
        "api_industry": _text(payload.get("upJongName")),
        "api_same_industry_per": _num(payload.get("sameIndustryPer")),
        "api_face_price": _num(payload.get("facePrice")),
        "api_week52_high": _num(payload.get("week52HighPrice")),
        "api_week52_low": _num(payload.get("week52LowPrice")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 종목 목록  `/api/domestic/market/stock/default?...&orderType=marketSum`
# ─────────────────────────────────────────────────────────────────────────────

def parse_market_list_row(row: dict, *, market_label: str) -> dict:
    """목록 응답의 한 종목 → 구 `fetch_kospi200_real_market_data()` 와 같은 키 + 추가 필드.

    🟢 이 응답에는 **ROE 가 들어 있습니다**(2026-09-07 실측, 스냅샷과 10/10 일치).
       구 목록 페이지와 같은 위치의 값이므로 `t_roe` 로 바로 씁니다.

    🔴 `pbr` 은 **전일 종가 기준**이라 `t_pbr` 로 승격하지 않습니다(④). 원본 그대로
       `api_pbr_prev_close_basis` 라는 **오해할 수 없는 이름**으로만 남깁니다.
    """
    if not isinstance(row, dict):
        raise NaverApiSourceError(f"목록 항목이 dict 가 아닙니다: {type(row).__name__}")
    code = _text(row.get("itemcode"))
    name = _text(row.get("itemname"))
    price = _num(row.get("nowPrice"))
    if not code or not name or not price:
        raise NaverApiSourceError(f"목록 항목에 종목코드·이름·현재가 중 빠진 것이 있습니다: {row!r:.200}")

    div_yield_pct = _num(row.get("dividendRate"))
    dps, dps_status, conflict = _resolve_dps(row.get("dividend"), div_yield_pct)

    out = {
        # 구 목록 파서와 동일한 키
        "name": name,
        "code": code,
        "price": price,
        "t_per": _nonzero(_num(row.get("per"))),
        "t_roe": _num(row.get("roe")),
        "market": market_label,
        # 신 API 에서 추가로 얻는 것
        "t_eps": _num(row.get("eps")),
        "dps": dps,
        "dps_status": dps_status,
        "div_yield": div_yield_pct,
        "outstanding_shares": _int(row.get("listedStockCnt")),
        "market_cap_api_truncated": _num(row.get("marketSum")),
        "api_pbr_prev_close_basis": _num(row.get("pbr")),   # ④ t_pbr 아님. 절대 승격 금지
        "api_roa": _num(row.get("roa")),
        "api_net_income_eok": _num(row.get("netIncome")),        # 억원 단위(화면 표기 기준)
        "api_sales_eok": _num(row.get("sales")),
        "api_operating_profit_eok": _num(row.get("operatingProfit")),
        "api_asset_total_eok": _num(row.get("propertyTotal")),
        "api_debt_total_eok": _num(row.get("debtTotal")),
        "api_security_type": _text(row.get("type")),
        "api_trade_stop": _text(row.get("tradeStopYn")),
        "api_market_alert": _text(row.get("marketAlertType")),
        "api_market_status": _text(row.get("marketStatus")),
        "api_listed_date": _text(row.get("listedDate")),
        "errors": [conflict] if conflict else [],
    }
    return out


def parse_market_list(payload, *, source_url: str, market_label: str) -> list[dict]:
    """목록 응답 전체 → 종목 dict 리스트.

    🔴 한 종목이 깨져도 **나머지를 버리지 않습니다** (재감사 H1 — 구획 하나가 터졌다고
       이미 읽은 값까지 통째로 버리던 사고). 깨진 종목은 건너뛰고 사유를 남깁니다.
       단, **응답 전체의 모양이 틀린 경우**(list 가 아님)는 예외로 멈춥니다.
    """
    assert_krx_source(source_url)
    if not isinstance(payload, list):
        raise NaverApiSourceError(f"목록 응답이 list 가 아닙니다: {type(payload).__name__}")

    rows, skipped = [], []
    for i, raw in enumerate(payload):
        try:
            rows.append(parse_market_list_row(raw, market_label=market_label))
        except NaverApiSourceError as e:
            skipped.append(f"[{i}] {e}")
    if skipped:
        # 조용히 사라지면 §0-1 위반입니다. 호출부가 반드시 보게 첫 행에 실어 보냅니다.
        if rows:
            rows[0].setdefault("errors", []).extend(skipped)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 4. 컨센서스  `/api/domestic/detail/<code>/consensus`
# ─────────────────────────────────────────────────────────────────────────────

def parse_consensus(payload: dict) -> dict:
    """투자의견·목표주가만 있는 4필드 응답.

    ⚠️ **현재 저장소는 이 API 를 쓰지 않습니다.** 같은 값(목표주가·투자의견·추정기관수)이
       이미 매일 받는 `c1010001.aspx` 안에 있어 중복이기 때문입니다(§0-3-10, §1-5-6).
       구조가 단순하고 나중에 필요해질 수 있어 파서만 남겨 둡니다.

    🔴 `targetPrice` 는 **증권사 컨센서스 목표주가**이고, 저장소의 `f_target` 은
       **추정 EPS 로 계산한 값**입니다. **성격이 다르므로 그대로 바꿔 끼우면 안 됩니다**
       (§0-1 — 출처가 다른 값을 같은 칸에 넣지 않음). 도입은 오너 판단 사항입니다.
    """
    if not isinstance(payload, dict):
        raise NaverApiSourceError(f"컨센서스 응답이 dict 가 아닙니다: {type(payload).__name__}")
    return {
        "code": _text(payload.get("itemCode")),
        "as_of": _text(payload.get("date")),           # "20260904" (YYYYMMDD)
        "opinion_score": _num(payload.get("opinion")),  # 1(적극매도) ~ 5(적극매수) 축으로 보이나 미확인
        "consensus_target_price": _num(payload.get("targetPrice")),
    }
