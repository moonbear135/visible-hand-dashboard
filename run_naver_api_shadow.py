#!/usr/bin/env python3
"""네이버 신 증권 API **섀도 수집** — 실전 데이터는 한 글자도 건드리지 않습니다.

⚠️ 2026-09-07 신설 (#213). 오너 지시:
   *"만들어 둔 거는 만들어 둔 것대로 데이터가 잘 받아지는지 10일까지 데이터 축적도 해봐야
   하지 않아?"*

파서(`utils/naver_stock_api.py`)를 **9/10 에 처음 돌려보는 것은 안전주의가 아닙니다.**
구 출처가 살아 있는 동안 신 API 를 나란히 받아 **매일 대조**해 두면, 전환하는 날에는
"이미 며칠째 같은 값이 나오고 있다"는 근거를 들고 갈 수 있습니다.

🔴 **이 스크립트가 절대 하지 않는 것**
   - `data/kospi200_pegy_latest.json` 등 **실전 파일을 읽기만 하고 쓰지 않습니다.**
     쓰기는 `data/naver_api_shadow/` 아래로만 하며, 그 사실을 코드가 스스로 검사합니다
     (`_assert_shadow_path`). 실수로 경로를 잘못 적으면 **예외로 멈춥니다.**
   - 화면·점수·스냅샷에 영향을 주지 않습니다. 순수 관찰입니다.

🟢 **§0-3-2 매너 장치** (`polite-data-fetching` 규칙)
   - 요청 사이 **2.0~3.0초 랜덤 딜레이** (기존 수집기와 같은 기준)
   - **403 / 429 를 만나면 재시도하지 않고 그 즉시 중단**합니다. 우회하지 않습니다
     (User-Agent 돌려쓰기·프록시 금지 — 차단은 상대가 그만하라는 뜻입니다).
   - 연속 실패 5회면 **서킷 브레이커**로 그날 남은 요청을 전부 포기합니다.
   - **순차 요청만.** 병렬 없음.
   - 하루 요청 수 상한(`MAX_REQUESTS_PER_RUN`)을 코드로 강제합니다.
   - `pageSize` 는 **화면이 실제로 쓰는 값(20)** 을 따릅니다. 한도를 찾겠다고 큰 값을
     넣어 시험하지 않습니다.

🔴 **KRX 고정.** `utils.naver_stock_api.assert_krx_source()` 가 NXT 주소를 차단합니다.
   NXT 는 15:40~20:00 애프터마켓이 열려 있어 종가가 아니라 시간외가를 받습니다
   (`NAVER_MIGRATION_WORK_ORDER.md` §1-5-11).

실행:
    python run_naver_api_shadow.py              # 수집 + 대조
    python run_naver_api_shadow.py --compare-only   # 이미 받아둔 것으로 대조만 (요청 0건)

담당 에이전트: `kr-stocks`
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils.naver_stock_api import (  # noqa: E402
    NaverApiSourceError,
    assert_krx_source,
    parse_market_list,
    parse_stock_detail,
)

REPO_ROOT = Path(__file__).parent
SHADOW_DIR = REPO_ROOT / "data" / "naver_api_shadow"
PRODUCTION_SNAPSHOT = REPO_ROOT / "data" / "kospi200_pegy_latest.json"
KST = timezone(timedelta(hours=9))

# ── 매너 상수 — 속도 때문에 줄이지 않습니다(§0-3-2) ──────────────────────────
DELAY_MIN_SEC, DELAY_MAX_SEC = 2.0, 3.0
TIMEOUT_SEC = 10
CIRCUIT_CONSECUTIVE_FAILURES = 5
MAX_REQUESTS_PER_RUN = 60          # 목록 25 + 상세 표본 20 + 여유
LIST_PAGE_SIZE = 20                # 화면이 실제로 쓰는 값. 한도 탐색 금지
LIST_TARGET_COUNT = 500            # 현행 수집 범위와 동일
DETAIL_SAMPLE_SIZE = 20            # 상세는 전 종목이 아니라 표본만 (상대 서버 배려)

# 봇임을 숨기지 않습니다. 차단 우회용 위장이 아니라 **정직한 식별**입니다.
USER_AGENT = "visible-hand-dashboard/shadow (+https://github.com/moonbear135/visible-hand-dashboard)"

LIST_URL = ("https://stock.naver.com/api/domestic/market/stock/default"
            "?tradeType=KRX&marketType=ALL&orderType=marketSum"
            "&startIdx={start}&pageSize={size}")
DETAIL_URL = "https://stock.naver.com/api/domestic/detail/{code}/detail?codeType=KRX"


class CircuitOpen(RuntimeError):
    """연속 실패가 임계치를 넘어 그날의 요청을 중단합니다."""


class BlockedByServer(RuntimeError):
    """403/429 — 상대가 그만하라고 한 것입니다. 우회하지 않고 멈춥니다."""


def _assert_shadow_path(path: Path) -> Path:
    """🔴 쓰기 대상이 섀도 폴더 안인지 **코드가 직접 확인**합니다.

    실전 파일에 쓰는 사고는 "설마"로 막지 않습니다. 경로를 잘못 적으면 여기서 멈춥니다.
    """
    resolved = path.resolve()
    root = SHADOW_DIR.resolve()
    if root not in resolved.parents and resolved != root:
        raise RuntimeError(
            f"🔴 섀도 수집기가 섀도 폴더 밖에 쓰려 했습니다: {resolved}\n"
            f"   허용 경로는 {root} 아래뿐입니다."
        )
    return path


class PoliteSession:
    """순차·딜레이·상한·서킷브레이커를 한곳에 모은 요청기."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.request_count = 0
        self.consecutive_failures = 0
        self.log: list[dict] = []

    def get_json(self, url: str):
        assert_krx_source(url)          # 🔴 NXT 차단 (§1-5-11)

        if self.request_count >= MAX_REQUESTS_PER_RUN:
            raise CircuitOpen(f"1회 실행 요청 상한 {MAX_REQUESTS_PER_RUN} 도달 — 중단합니다.")
        if self.consecutive_failures >= CIRCUIT_CONSECUTIVE_FAILURES:
            raise CircuitOpen(f"연속 실패 {self.consecutive_failures}회 — 서킷을 엽니다.")

        if self.request_count:                       # 첫 요청 앞에는 대기하지 않습니다
            time.sleep(random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC))
        self.request_count += 1

        entry = {"url": url, "at": datetime.now(KST).isoformat(timespec="seconds")}
        try:
            res = self.session.get(url, timeout=TIMEOUT_SEC)
        except requests.RequestException as e:
            self.consecutive_failures += 1
            entry.update(ok=False, error=f"요청 예외: {type(e).__name__}")
            self.log.append(entry)
            return None

        entry["status"] = res.status_code
        if res.status_code in (403, 429):
            # 🔴 재시도하지 않습니다. 우회하지 않습니다. 그 즉시 그날 수집을 끝냅니다.
            entry.update(ok=False, error=f"차단 응답 {res.status_code} — 즉시 중단")
            self.log.append(entry)
            raise BlockedByServer(
                f"상대 서버가 {res.status_code} 로 응답했습니다. §0-3-2 에 따라 재시도·우회 없이 "
                "중단합니다. 원인을 확인하기 전에는 다시 시도하지 마세요."
            )
        if res.status_code != 200:
            self.consecutive_failures += 1
            entry.update(ok=False, error=f"HTTP {res.status_code}")
            self.log.append(entry)
            return None

        try:
            payload = res.json()
        except ValueError:
            self.consecutive_failures += 1
            entry.update(ok=False, error="JSON 파싱 실패 — 응답 구조가 바뀌었을 수 있음")
            self.log.append(entry)
            return None

        self.consecutive_failures = 0
        entry.update(ok=True, bytes=len(res.content))
        self.log.append(entry)
        return payload


# ─────────────────────────────────────────────────────────────────────────────
# 수집
# ─────────────────────────────────────────────────────────────────────────────

def collect(sess: PoliteSession) -> dict:
    """목록 전체 + 상세 표본. 실패도 **같은 스키마로** 기록합니다(빼지 않습니다)."""
    result = {
        "collected_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "list_rows": [], "list_raw_sample": [], "detail": {}, "detail_raw_sample": {},
        "errors": [], "stopped_reason": None,
    }

    # ── 1) 목록 (시가총액 순) ────────────────────────────────────────────────
    try:
        for start in range(0, LIST_TARGET_COUNT, LIST_PAGE_SIZE):
            url = LIST_URL.format(start=start, size=LIST_PAGE_SIZE)
            payload = sess.get_json(url)
            if payload is None:
                result["errors"].append(f"목록 startIdx={start} 수집 실패")
                continue
            if start == 0:
                result["list_raw_sample"] = payload[:3]   # raw 보관은 표본만(§0-3-3)
            try:
                result["list_rows"].extend(
                    parse_market_list(payload, source_url=url, market_label="UNKNOWN")
                )
            except NaverApiSourceError as e:
                result["errors"].append(f"목록 startIdx={start} 파싱 거부: {e}")
            if not payload:
                break                                     # 더 줄 게 없으면 그만 요청합니다
    except (CircuitOpen, BlockedByServer) as e:
        result["stopped_reason"] = str(e)
        return result

    # ── 2) 상세 표본 ────────────────────────────────────────────────────────
    #    특정 종목을 코드에 박지 않습니다(§2-2). **규칙**으로 고릅니다 —
    #    시총 상위·중위·하위를 고르게 섞어 구조 변화를 넓게 관찰합니다.
    rows = result["list_rows"]
    if rows:
        n = len(rows)
        step = max(1, n // DETAIL_SAMPLE_SIZE)
        sample = [rows[i]["code"] for i in range(0, n, step)][:DETAIL_SAMPLE_SIZE]
        try:
            for i, code in enumerate(sample):
                url = DETAIL_URL.format(code=code)
                payload = sess.get_json(url)
                if payload is None:
                    result["detail"][code] = {"errors": ["상세 수집 실패"]}
                    continue
                if i == 0:
                    result["detail_raw_sample"][code] = payload
                try:
                    result["detail"][code] = parse_stock_detail(payload, source_url=url)
                except NaverApiSourceError as e:
                    result["detail"][code] = {"errors": [f"상세 파싱 거부: {e}"]}
        except (CircuitOpen, BlockedByServer) as e:
            result["stopped_reason"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 대조 — 현행 스냅샷과 얼마나 맞는가
# ─────────────────────────────────────────────────────────────────────────────

COMPARE_FIELDS = [
    # (섀도 키, 현행 스냅샷 키, 허용 오차 비율, 설명)
    ("price", "price", 0.005, "현재가"),
    ("t_roe", "t_roe", 0.01, "ROE"),
    ("t_eps", "t_eps", 0.01, "Trailing EPS"),
    ("t_per", "t_per", 0.01, "Trailing PER"),
    ("outstanding_shares", "outstanding_shares", 0.0001, "상장주식수"),
]


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def compare_with_production(shadow: dict) -> dict:
    """실전 스냅샷을 **읽기만** 합니다. 쓰지 않습니다."""
    out = {"compared_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
           "fields": {}, "matched_codes": 0, "shadow_only": 0, "production_only": 0,
           "note": ""}
    if not PRODUCTION_SNAPSHOT.is_file():
        out["note"] = "실전 스냅샷이 없어 대조하지 못했습니다."
        return out

    prod = {s["code"]: s for s in json.load(PRODUCTION_SNAPSHOT.open(encoding="utf-8"))["stocks"]}
    shad = {r["code"]: r for r in shadow.get("list_rows", [])}
    common = set(prod) & set(shad)
    out["matched_codes"] = len(common)
    out["shadow_only"] = len(set(shad) - set(prod))
    out["production_only"] = len(set(prod) - set(shad))

    for skey, pkey, tol, label in COMPARE_FIELDS:
        ok = ng = na = 0
        worst = []
        for code in sorted(common):
            a, b = _f(shad[code].get(skey)), _f(prod[code].get(pkey))
            if a is None or b is None:
                na += 1
                continue
            if b == 0:
                # 0 과 비교할 때 비율 오차는 정의되지 않으므로 정확히 같은지만 봅니다.
                ok, ng = (ok + 1, ng) if a == 0 else (ok, ng + 1)
                continue
            diff = abs(a - b) / abs(b)
            if diff <= tol:
                ok += 1
            else:
                ng += 1
                worst.append({"code": code, "shadow": a, "production": b,
                              "diff_pct": round(diff * 100, 3)})
        worst.sort(key=lambda x: -x["diff_pct"])
        total = ok + ng
        out["fields"][skey] = {
            "label": label, "match": ok, "mismatch": ng, "not_comparable": na,
            "match_ratio": round(ok / total, 4) if total else None,
            "worst": worst[:10],
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 알림 판정 — 🔴 **이 판정은 여기 한 곳에만 있습니다**(§0-3-10).
# 워크플로우 YAML 은 이 함수의 출력을 그대로 전달만 합니다. 같은 임계값을 두 곳에
# 적어두면 한쪽만 고쳐져서 조용히 어긋납니다.
# ─────────────────────────────────────────────────────────────────────────────

ALERT_MATCH_RATIO_FLOOR = 0.95   # 일치율이 이 아래로 떨어지면 알립니다
ALERT_MIN_COMMON_CODES = 100     # 공통 종목이 이보다 적으면 대조 자체가 무의미합니다


def build_alert_message() -> str:
    """이상하면 사람이 읽을 한 줄, 정상이면 **빈 문자열**을 돌려줍니다."""
    report_path = SHADOW_DIR / "latest_compare.json"
    if not report_path.is_file():
        return "대조 리포트가 생성되지 않았습니다 (수집 자체가 실패했을 수 있습니다)"
    try:
        r = json.loads(report_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        return f"대조 리포트를 읽지 못했습니다: {e}"

    problems = []
    if r.get("matched_codes", 0) < ALERT_MIN_COMMON_CODES:
        problems.append(f'공통 종목이 {r.get("matched_codes")}개뿐 (대조 불가 수준)')
    for f in r.get("fields", {}).values():
        ratio = f.get("match_ratio")
        if ratio is None:
            problems.append(f'{f["label"]}: 비교 가능한 종목이 없음')
        elif ratio < ALERT_MATCH_RATIO_FLOOR:
            problems.append(f'{f["label"]}: 일치율 {ratio * 100:.1f}%')
    return " / ".join(problems)


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="네이버 신 API 섀도 수집 (실전 미접촉)")
    ap.add_argument("--compare-only", action="store_true",
                    help="네트워크 요청 없이, 가장 최근 섀도 파일로 대조만 다시 합니다.")
    ap.add_argument("--alert-message", action="store_true",
                    help="대조 리포트를 읽어 이상하면 한 줄로 출력, 정상이면 아무것도 출력하지 않습니다. 요청 0건.")
    ap.add_argument("--discord-payload", action="store_true",
                    help="디스코드 웹훅용 JSON 본문을 출력합니다. 요청 0건.")
    args = ap.parse_args()

    # 알림 전용 모드 — 네트워크도 파일 쓰기도 하지 않습니다.
    if args.alert_message or args.discord_payload:
        msg = build_alert_message()
        if not msg:
            return 0
        if args.discord_payload:
            print(json.dumps({"content":
                              "🕶️ **네이버 신 API 섀도 대조 이상**\n" + msg +
                              "\n(실전 화면에는 영향 없습니다 — 이관 준비용 관찰입니다)"},
                             ensure_ascii=False))
        else:
            print(msg)
        return 0

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    raw_path = _assert_shadow_path(SHADOW_DIR / f"{today}_shadow.json")

    if args.compare_only:
        files = sorted(SHADOW_DIR.glob("*_shadow.json"))
        if not files:
            print("❌ 대조할 섀도 파일이 없습니다.")
            return 1
        shadow = json.load(files[-1].open(encoding="utf-8"))
        print(f"📂 {files[-1].name} 으로 대조합니다 (네트워크 요청 0건).")
    else:
        sess = PoliteSession()
        print(f"🕷️ 섀도 수집 시작 — 딜레이 {DELAY_MIN_SEC}~{DELAY_MAX_SEC}초, "
              f"요청 상한 {MAX_REQUESTS_PER_RUN}건, KRX 고정")
        try:
            shadow = collect(sess)
        except BlockedByServer as e:
            print(f"🛑 {e}")
            shadow = {"collected_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
                      "list_rows": [], "detail": {}, "errors": [str(e)],
                      "stopped_reason": str(e)}
        shadow["request_log"] = sess.log if not args.compare_only else []
        shadow["request_count"] = getattr(sess, "request_count", 0)
        json.dump(shadow, _assert_shadow_path(raw_path).open("w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"💾 {raw_path.name} 저장 — 요청 {shadow['request_count']}건, "
              f"종목 {len(shadow['list_rows'])}개")

    report = compare_with_production(shadow)
    report_path = _assert_shadow_path(SHADOW_DIR / "latest_compare.json")
    json.dump(report, report_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n📊 현행 스냅샷 대조 — 공통 {report['matched_codes']}종목")
    for key, r in report["fields"].items():
        ratio = "—" if r["match_ratio"] is None else f"{r['match_ratio']*100:5.1f}%"
        print(f"   {r['label']:<12} 일치 {r['match']:>4} / 불일치 {r['mismatch']:>4} "
              f"/ 비교불가 {r['not_comparable']:>4}   → {ratio}")
    if shadow.get("stopped_reason"):
        print(f"\n🛑 중단 사유: {shadow['stopped_reason']}")
        return 2
    if shadow.get("errors"):
        print(f"\n⚠️ 오류 {len(shadow['errors'])}건 (파일에 전부 기록됨)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
