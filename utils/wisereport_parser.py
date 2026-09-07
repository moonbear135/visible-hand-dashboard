"""`navercomp.wisereport.co.kr/v2/company/c1010001.aspx` 응답 파서 — 순수 함수, 네트워크 없음.

⚠️ 2026-09-07 신설 (#214, `NAVER_MIGRATION_WORK_ORDER.md` §1-5-6).

🔴 **이 페이지는 이미 매일 받고 있습니다.** `collector_kospi200.py::_fetch_ev_ebitda()` 가
   EV/EBITDA 하나를 뽑으려고 종목마다 이 주소를 호출합니다. 그런데 2026-09-07 조사에서
   **같은 응답 안에 `ROE`·`Forward ROE`·순이익·자본총계·목표주가까지 전부 들어 있음**이
   확인됐습니다. 받아놓고 안 읽고 있었던 것입니다.
   → **요청을 늘리지 않고** 필요한 값을 더 얻을 수 있습니다(§0-3-2 관점에서 최선).

🔴 **아직 실전에 배선돼 있지 않습니다**(§0-3-6 — 오너 승인 사항).
   지금 `_fetch_ev_ebitda()` 는 그대로 두었습니다. 배선할 때는 **이 모듈이 EV/EBITDA 도
   같이 읽으므로** 그 함수를 이 모듈 호출로 바꿔 중복을 없애는 것이 맞습니다(§0-3-10).

─────────────────────────────────────────────────────────────────────────────
📌 이 파서가 지키는 것
─────────────────────────────────────────────────────────────────────────────

① 🔴 **`iloc` 위치 인덱스 금지** (§2-1). 위레포트 표는 종목·시점마다 연도 컬럼 수가
   다릅니다. 헤더를 `DataValidator.classify_header_timeframe()` 으로 분류해 고릅니다 —
   `_fetch_ev_ebitda()` 가 2026-08-06 2차 감사 1-6 이후 쓰고 있는 바로 그 방식입니다.

② 🔴 **분기 컬럼을 절대 쓰지 않습니다.** 이 표에는 연간 4열과 분기 4열이 나란히 있고,
   **분기 ROE 는 "직전 4개 분기 데이터로 연환산"** 한 값이라고 페이지가 스스로 밝힙니다.
   현행 `t_roe` 는 **연간 확정치**이므로 기준이 다릅니다. 섞으면 조용히 틀립니다.
   (실측: SK하이닉스 연간 2025/12 = 44.15 vs 분기 2026/06 = 92.68)

③ 🔴 **추정(E)과 실적을 뒤섞지 않습니다.** `2026/12(E)` 는 `f_roe`, `2025/12` 는 `t_roe`.
   2차 감사 1-7 의 교훈 — 추정치가 실측치처럼 보이면 안 됩니다.

④ 값이 없으면 **없는 대로 None** 을 돌려주고 사유를 `errors` 에 남깁니다(§0-1).
   평균·전년값·0 으로 메우지 않습니다.

담당 에이전트: `kr-stocks`
"""
from __future__ import annotations

import io as _io

import pandas as pd

from utils.data_validator import DataValidator

__all__ = ["parse_financial_summary", "ANNUAL_ACTUAL_KINDS", "ANNUAL_ESTIMATE_KINDS"]

# `DataValidator.classify_header_timeframe()` 이 돌려주는 분류 중 우리가 쓰는 것.
# 🔴 QUARTERLY / QUARTERLY_EST 는 **의도적으로 빠져 있습니다**(위 ②).
ANNUAL_ACTUAL_KINDS = ("TTM", "ANNUAL_TTM")
ANNUAL_ESTIMATE_KINDS = ("ANNUAL_EST",)

# 행 라벨은 키워드로 찾습니다(§2-1 — 위치로 세지 않습니다).
_ROW_KEYS = {
    "roe": "ROE",
    "net_income_owner": "당기순이익(지배)",
    "equity_owner": "자본총계(지배)",
    "eps": "EPS",
    "bps": "BPS",
    "dps": "현금DPS",
    "shares_common": "발행주식수",
}


def _cell_number(value):
    """표 한 칸을 float 로. **부호를 지우지 않습니다**(2차 감사 1-1).

    빈칸·`-`·`nan` 은 0 이 아니라 **None(미수집)** 입니다(§0-1).
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace(",", "").replace("원", "").replace("%", "").strip()
    if text in ("", "nan", "-", "ㅡ", "−", "N/A"):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _classify_columns(df):
    """열 인덱스를 (연간 실적, 연간 추정) 으로 나눕니다. 분기는 **버립니다**."""
    actual, estimate = [], []
    for i, col in enumerate(df.columns):
        kind = DataValidator.classify_header_timeframe(col)
        if kind in ANNUAL_ACTUAL_KINDS:
            actual.append(i)
        elif kind in ANNUAL_ESTIMATE_KINDS:
            estimate.append(i)
        # QUARTERLY / QUARTERLY_EST / UNKNOWN → 쓰지 않습니다(위 ②).
    return actual, estimate


def _find_row(df, keyword):
    """1열 라벨에 키워드가 들어간 행 번호. 없으면 None."""
    labels = df.iloc[:, 0].astype(str)
    hits = [i for i, label in enumerate(labels) if keyword in label]
    return hits[0] if hits else None


def _pick(df, row_idx, col_indices):
    """주어진 열들 중 **가장 오른쪽(=가장 최근)** 부터 값이 있는 칸을 찾습니다."""
    for col_i in reversed(col_indices):
        value = _cell_number(df.iat[row_idx, col_i])
        if value is not None:
            return value, str(df.columns[col_i])
    return None, None


def _find_summary_table(tables):
    """`ROE` 와 연간/분기 컬럼을 함께 가진 재무요약 표를 고릅니다."""
    for df in tables:
        if df.shape[1] < 3 or df.empty:
            continue
        labels = " ".join(str(x) for x in df.iloc[:, 0].tolist())
        if "ROE" in labels and "EPS" in labels and "자본총계" in labels:
            return df
    return None


def _find_fundamental_table(tables):
    """EV/EBITDA 가 있는 '펀더멘털' 표."""
    for df in tables:
        if df.empty or df.shape[1] < 2:
            continue
        if "EV/EBITDA" in " ".join(str(x) for x in df.iloc[:, 0].tolist()):
            return df
    return None


def parse_financial_summary(html: str) -> dict:
    """HTML 한 장 → 우리가 쓰는 값들. **네트워크를 건드리지 않습니다.**

    반환 키:
      `t_roe` / `f_roe`                      — 연간 확정 ROE / 연간 추정 ROE (%)
      `t_roe_period` / `f_roe_period`        — 그 값이 어느 컬럼에서 왔는지(추적용)
      `net_income_owner_eok` / `equity_owner_eok`
      `t_eps` / `f_eps` / `t_bps` / `t_dps` / `shares_common`
      `ev_ebitda`                            — 문자열(원본 표기 보존, 기존 관례와 동일)
      `errors`                               — 못 구한 것의 사유. **비어 있지 않을 수 있습니다**
    """
    out = {k: None for k in (
        "t_roe", "f_roe", "t_roe_period", "f_roe_period",
        "net_income_owner_eok", "equity_owner_eok",
        "t_eps", "f_eps", "t_bps", "t_dps", "shares_common", "ev_ebitda",
    )}
    out["errors"] = []

    if not isinstance(html, str) or not html.strip():
        out["errors"].append("빈 HTML — 파싱할 것이 없습니다")
        return out

    try:
        tables = pd.read_html(_io.StringIO(html))
    except ValueError:
        # 표가 하나도 없는 페이지(점검 안내·오류 페이지 등). 지어내지 않고 그대로 보고합니다.
        out["errors"].append("표를 하나도 찾지 못했습니다 — 응답이 정상 페이지가 아닐 수 있습니다")
        return out
    except ImportError as e:
        # 🔴 페이지 문제가 아니라 **환경 문제**입니다. 둘을 같은 문장으로 뭉개면
        #    "네이버가 바뀌었나?"를 엉뚱하게 조사하게 됩니다(§0-1 — 사유를 정확히).
        #    pandas 는 표를 못 찾으면 다른 파서로 재시도하는데, 그 파서가 없으면 여기로 옵니다.
        out["errors"].append(f"HTML 파서 라이브러리가 없어 표를 읽지 못했습니다(환경 문제): {e}")
        return out

    # ── 1) 재무요약 표 (ROE·순이익·자본총계·EPS·BPS·DPS) ─────────────────────
    summary = _find_summary_table(tables)
    if summary is None:
        out["errors"].append("재무요약(Financial Summary) 표를 찾지 못했습니다")
    else:
        actual_cols, est_cols = _classify_columns(summary)
        if not actual_cols:
            # 🔴 여기서 위치 인덱스로 폴백하지 않습니다(§2-1). 미수집으로 둡니다.
            out["errors"].append(
                "재무요약 표에서 연간 실적 컬럼을 특정하지 못했습니다 — "
                "위치 인덱스 폴백 없이 미수집 처리(§2-1)"
            )
        if not est_cols:
            out["errors"].append("재무요약 표에서 연간 추정(E) 컬럼을 찾지 못했습니다 — f_roe 미수집")

        roe_row = _find_row(summary, _ROW_KEYS["roe"])
        if roe_row is None:
            out["errors"].append("ROE 행을 찾지 못했습니다")
        else:
            if actual_cols:
                out["t_roe"], out["t_roe_period"] = _pick(summary, roe_row, actual_cols)
            if est_cols:
                out["f_roe"], out["f_roe_period"] = _pick(summary, roe_row, est_cols)

        for key, label in (("net_income_owner_eok", "net_income_owner"),
                           ("equity_owner_eok", "equity_owner"),
                           ("t_eps", "eps"), ("t_bps", "bps"),
                           ("t_dps", "dps"), ("shares_common", "shares_common")):
            row = _find_row(summary, _ROW_KEYS[label])
            if row is not None and actual_cols:
                out[key], _ = _pick(summary, row, actual_cols)
        eps_row = _find_row(summary, _ROW_KEYS["eps"])
        if eps_row is not None and est_cols:
            out["f_eps"], _ = _pick(summary, eps_row, est_cols)

    # ── 2) 펀더멘털 표 (EV/EBITDA) ──────────────────────────────────────────
    fundamental = _find_fundamental_table(tables)
    if fundamental is None:
        out["errors"].append("EV/EBITDA 표를 찾지 못했습니다")
    else:
        cols, est = _classify_columns(fundamental)
        row = _find_row(fundamental, "EV/EBITDA")
        if row is None:
            out["errors"].append("EV/EBITDA 행을 찾지 못했습니다")
        elif not cols:
            out["errors"].append(
                "EV/EBITDA 표 헤더 기간 분류 실패 → 위치 인덱스 폴백 없이 미수집 처리(§2-1)"
            )
        else:
            value, _ = _pick(fundamental, row, cols)
            # 📌 기존 관례대로 **문자열**로 돌려줍니다(원본 표기 보존).
            #    `collector_kospi200._fetch_ev_ebitda()` 가 문자열을 반환하고
            #    소비부(`_compute_graham_number`)가 float() 으로 바꿉니다.
            out["ev_ebitda"] = None if value is None else str(value)

    return out
