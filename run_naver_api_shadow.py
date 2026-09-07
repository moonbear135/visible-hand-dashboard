#!/usr/bin/env python3
"""네이버 신 증권 API **섀도 수집** — 실전 데이터는 한 글자도 건드리지 않습니다.

⚠️ 2026-09-07 신설 (#213). 오너 지시:
   *"만들어 둔 거는 만들어 둔 것대로 데이터가 잘 받아지는지 10일까지 데이터 축적도 해봐야
   하지 않아?"*

파서(`utils/naver_stock_api.py`)를 **9/10 에 처음 돌려보는 것은 안전주의가 아닙니다.**
구 출처가 살아 있는 동안 신 API 를 나란히 받아 **매일 대조**해 두면, 전환하는 날에는
"이미 며칠째 같은 값이 나오고 있다"는 근거를 들고 갈 수 있습니다.

🔴 **이것은 수집기가 아닙니다 — 시험입니다.**
   실전 수집(`collector_kospi200.py` + `scrape.yml`)은 **매일 520종목 전부**를 구 네이버에서
   긁어 화면에 씁니다. 이 스크립트는 그 뒤에 따라 붙어 **"신 API 가 같은 값을 주나"만 확인**
   합니다. 여기서 상세를 표본만 받는 것은 **시험 표본**이지 수집 범위가 아닙니다.
   배선 후 실전은 당연히 매일 전 종목을 받습니다 — 나눠 받지 않습니다.

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
from utils.wisereport_parser import parse_financial_summary  # noqa: E402
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
MAX_REQUESTS_PER_RUN = 460         # 목록 26 + 상세 200 + 위즈리포트 200 + 여유
# 📌 §0-3-2 — 하루 약 426요청, 순차, 2~3초 간격이라 **약 18분**입니다.
#    현행 수집기가 이미 매일 하는 약 1,040요청에 **41% 를 더하는** 수준입니다.
#    ⏳ **한시적**입니다 — 이관이 끝나면 이 워크플로우째 정리하세요.
LIST_PAGE_SIZE = 20                # 화면이 실제로 쓰는 값. 한도 탐색 금지
LIST_TARGET_COUNT = 520            # 🔴 현행과 동일한 범위: 상위 500 + 히스테리시스 버퍼 20.
#    2026-09-08 실측 — 500 만 받으면 실전 520 중 21종목이 빠져 "안 맞는다"는 착시가 납니다.
#    (실전 시총 상위 490 까지는 500 수집으로도 100% 일치했습니다. 순수한 경계 문제였습니다.)
LIST_PAGE_COUNT = LIST_TARGET_COUNT // LIST_PAGE_SIZE   # = 25 페이지

# 🔴 2026-09-08 정정 (섀도 1회차에서 실제로 겪은 오류).
#    `startIdx` 는 **항목 오프셋이 아니라 페이지 인덱스**입니다.
#    실제 오프셋 = startIdx × pageSize.
#    처음에 오프셋으로 착각해 0, 20, 40 … 으로 요청했더니
#      startIdx=0  → 1~20위 (정상처럼 보임)
#      startIdx=20 → 20×20 = **401위부터** (맵스리얼티 — 실전 기준 400위)
#      startIdx=40 → **801위부터**
#      startIdx=160 → 3201위 → 상장 종목 수를 넘어 **빈 배열**
#    …이 되어 "상위 500" 대신 "1~20위 + 401위 이하"를 모았습니다.
#    실측 확인(오너, 2026-09-08): `startIdx=1&pageSize=20` → 첫 종목 **하나금융지주**(21위).
#    ⚠️ 겉보기엔 정상이었습니다 — 첫 페이지가 맞았고, 전체가 시총 내림차순이기도 했습니다.
#       그래서 아래 `check_pagination_continuity()` 로 **코드가 스스로 잡게** 했습니다.
# 🔴 2026-09-08 **오너 결정 — 회전 표본을 걷어내고 "좁게, 매일 전부"로 바꿉니다.**
#
#    오너: *"데이터 오염을 잡는 게 어렵기 때문에 이것저것 계속 안전막을 막고 있는 건데,
#           지금 매일 100개씩 받는 걸로는 그걸 커버할 수가 없다고 생각해.
#           차라리 크롤링 종목을 시가총액 순위 200개로 해서 **전체적으로 매일 받으면서**
#           확인을 하는 게 맞아."*
#
#    왜 회전이 부족했나 (실측 근거):
#      · `t_eps` 는 거의 매일 바뀝니다 — 실적 시즌 하루 **74종목**, 평소 6~21종목.
#      · 시총 순위는 하루 중앙값 2~3계단, **최대 70계단**. 매일 1~7종목이 500위권을 드나듭니다.
#      → 회전은 "오늘 일치"만 알려줄 뿐, **어느 날 어긋났는지·왜 어긋났는지**를 못 짚습니다.
#        오염은 시계열로만 보이는데 회전은 그 시계열을 끊습니다.
#
#    → **폭을 줄이고 깊이를 택합니다.** 시총 상위 200종목을 **매일 전부** 봅니다.
#      201위 아래는 이 섀도가 보지 않습니다(알고 두는 공백 — §0-1).
#      목록(520종목)은 26요청으로 싸므로 **전 범위를 계속 받습니다** —
#      순위 정합·종목 집합 검증에 필요합니다.
SHADOW_UNIVERSE_SIZE = 200         # 섀도가 **매일 전부** 깊게 보는 범위 (시총 상위 N)
DETAIL_SAMPLE_SIZE = SHADOW_UNIVERSE_SIZE       # 상세 — 회전 없음, 매일 전부
WISEREPORT_SAMPLE_SIZE = SHADOW_UNIVERSE_SIZE   # Forward ROE·EV/EBITDA — 매일 전부

# 🔴 표본은 **매일 다른 구간**을 돕니다 (2026-09-08 오너 지시 "표본 확대 + 회전").
#    왜: 3회차까지 상세 검증률이 4%(20/520), Forward ROE 는 0% 였습니다. `f_pegy` 의
#    재료가 거의 검증 안 된 상태였고, 오너가 "목록만 가지고 오는 거야? 전체는 아니잖아"
#    라고 짚었습니다. 전량을 매일 받으면 상대 서버 요청이 크게 늘어나므로(§0-3-2),
#    **요청량은 낮게 유지하면서 날마다 다른 구간을 훑어** 며칠이면 넓게 덮습니다.
#    회전 오프셋은 **날짜로 결정**되므로 같은 날 다시 돌리면 같은 표본이 나옵니다(재현 가능).
#      · 상세 100종목/일 → 520종목을 약 6일이면 한 바퀴
#      · 위즈리포트 20종목/일 → 약 26일이면 한 바퀴 (Forward ROE 는 분기마다 바뀌므로 충분)

# 🔴 신 API 의 `type` 필드(ST/RT/IF/DR/MF)를 **종목 선별 필터로 쓰지 않습니다.**
#    2026-09-08 오너 지적으로 확인한 사실:
#      · 현행은 `data/kr_ticker_master.json`(FinanceDataReader)로 STOCK/ETF **두 갈래만** 나누며,
#        리츠(RT)·인프라투자회사(IF)·예탁증서(DR)·뮤추얼펀드(MF)를 **전부 STOCK 으로 수집**합니다.
#        실측: 맥쿼리인프라·SK리츠·롯데리츠·맵스리얼티·코오롱티슈진 모두 현행 스냅샷에 있고
#        화면에도 노출됩니다(`is_visible=True`).
#      · 지표가 안 나오는 종목은 **거르는 게 아니라 검증에서 막습니다** —
#        맥쿼리인프라는 `is_valid=False`, 배지 "⚠️ 데이터 검증 필요", 점수 None.
#        §0-1 대로 "지어내지 않고 못 구했다고 보여주는" 설계입니다.
#    → 여기에 `type=="ST"` 필터를 넣으면 **종목 유형 판정이 두 곳이 되어**(FDR vs 네이버)
#      두 판정이 어긋날 때 종목이 조용히 사라집니다(§0-3-10 위반, 실제로 어긋납니다).
#    `type` 은 `api_security_type` 으로 **참고 보관만** 합니다.

# 봇임을 숨기지 않습니다. 차단 우회용 위장이 아니라 **정직한 식별**입니다.
USER_AGENT = "visible-hand-dashboard/shadow (+https://github.com/moonbear135/visible-hand-dashboard)"

# `{page}` 는 **페이지 인덱스**입니다(0,1,2,…). 오프셋이 아닙니다 — 위 주석 참고.
LIST_URL = ("https://stock.naver.com/api/domestic/market/stock/default"
            "?tradeType=KRX&marketType=ALL&orderType=marketSum"
            "&startIdx={page}&pageSize={size}")
DETAIL_URL = "https://stock.naver.com/api/domestic/detail/{code}/detail?codeType=KRX"
# 🔴 현행 수집기(`collector_kospi200._fetch_ev_ebitda`)가 **이미 매일 부르는 바로 그 주소**입니다.
#    섀도는 별도 프로세스라 따로 받아야 하므로, 표본만 받습니다(§0-3-2).
WISEREPORT_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={code}"


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
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.request_count = 0
        self.consecutive_failures = 0
        self.log: list[dict] = []

    def get_text(self, url: str):
        """HTML 응답용(위즈리포트). `get_json` 과 **같은 매너 장치**를 그대로 지나갑니다."""
        res = self._request(url)
        return None if res is None else res.text

    def get_json(self, url: str):
        res = self._request(url)
        if res is None:
            return None
        try:
            return res.json()
        except ValueError:
            self.consecutive_failures += 1
            self.log[-1].update(ok=False, error="JSON 파싱 실패 — 응답 구조가 바뀌었을 수 있음")
            return None

    def _request(self, url: str):
        assert_krx_source(url)          # 🔴 NXT 차단 (§1-5-11)

        if self.request_count >= MAX_REQUESTS_PER_RUN:
            raise CircuitOpen(f"1회 실행 요청 상한 {MAX_REQUESTS_PER_RUN} 도달 — 중단합니다.")
        if self.consecutive_failures >= CIRCUIT_CONSECUTIVE_FAILURES:
            raise CircuitOpen(f"연속 실패 {self.consecutive_failures}회 — 서킷을 엽니다.")

        if self.request_count:                       # 첫 요청 앞에는 대기하지 않습니다
            time.sleep(random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC))
        self.request_count += 1

        entry = {"url": url, "at": datetime.now(KST).isoformat(timespec="seconds")}
        started = time.monotonic()
        try:
            res = self.session.get(url, timeout=TIMEOUT_SEC)
            entry["elapsed_sec"] = round(time.monotonic() - started, 3)
        except requests.RequestException as e:
            entry["elapsed_sec"] = round(time.monotonic() - started, 3)
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

        self.consecutive_failures = 0
        entry.update(ok=True, bytes=len(res.content))
        self.log.append(entry)
        return res


# ─────────────────────────────────────────────────────────────────────────────
# 수집
# ─────────────────────────────────────────────────────────────────────────────

# 🔴 페이지 **경계**의 낙폭이, **같은 구간 내부**의 정상 낙폭보다 이 배수 이상 크면 이상으로 봅니다.
#
#    왜 절대 임계값(예: "5배 넘으면 이상")을 쓰지 않는가 — 2026-09-08 실측:
#    시총 상위권은 원래 낙폭이 큽니다. SK하이닉스(1,302조) → 삼성전자우(160조)가 **8배**인데
#    이건 진짜 시장 분포지 우리 버그가 아닙니다. 절대 임계값을 쓰면 여기서 오탐이 나고,
#    **오탐이 나는 경보는 곧 무시당하는 경보**입니다.
#    대신 "그 구간에서 정상적으로 나타나는 낙폭"과 비교합니다:
#      · 상위 페이지 내부 최대 낙폭 8배 → 경계 임계 24배 → 실제 경계 **58배** ⇒ 잡힘 ✅
#      · 하위 페이지 내부 낙폭 ≈ 1.0배 → 경계 임계 5배(하한) ⇒ 정상이면 안 잡힘 ✅
PAGINATION_BOUNDARY_JUMP_MULTIPLE = 3.0
PAGINATION_BOUNDARY_JUMP_FLOOR = 5.0    # 내부 낙폭이 거의 없는 구간용 하한


def _ratio(a, b):
    """앞 종목 시총 ÷ 뒤 종목 시총. 값이 없으면 None."""
    if not a or not b or a <= 0 or b <= 0:
        return None
    return a / b


def check_pagination_continuity(rows, page_boundaries) -> list[str]:
    """페이지를 잘못 넘겨 **엉뚱한 구간이 이어붙지 않았는지** 확인합니다.

    🔴 왜 필요한가 (2026-09-08 실제 사고):
       `startIdx` 를 항목 오프셋으로 착각해 요청했더니 1~20위 다음에 **401위대**가
       이어붙었습니다. **겉보기엔 멀쩡했습니다** — 첫 페이지가 맞았고, 전체가 시총
       내림차순이기도 해서 "정렬은 되어 있다"는 검사로는 절대 못 잡습니다.
       사람이 값을 눈으로 봐서 찾았는데, 그건 다음에도 통할 방법이 아닙니다.

    잡는 것: ① 페이지 경계에서만 나타나는 비정상 낙폭 ② 중복 종목(페이지 겹침) ③ 수집량 부족.
    반환: 사람이 읽을 경고 문장 목록(정상이면 빈 목록).
    """
    warnings: list[str] = []
    if not rows:
        return ["목록을 한 종목도 받지 못했습니다"]

    caps = [(r.get("code"), r.get("name"), r.get("market_cap_api_truncated") or 0) for r in rows]

    # 페이지 내부에서 정상적으로 나타나는 낙폭의 최댓값 — 비교 기준선입니다.
    boundaries = sorted(set(page_boundaries) - {0})
    inside_ratios = [
        r for i in range(len(caps) - 1)
        if (i + 1) not in boundaries and (r := _ratio(caps[i][2], caps[i + 1][2])) is not None
    ]
    baseline = max(inside_ratios) if inside_ratios else 1.0
    threshold = max(baseline * PAGINATION_BOUNDARY_JUMP_MULTIPLE, PAGINATION_BOUNDARY_JUMP_FLOOR)

    for i in boundaries:
        if i == 0 or i >= len(caps):
            continue
        ratio = _ratio(caps[i - 1][2], caps[i][2])
        if ratio is not None and ratio >= threshold:
            warnings.append(
                f"🔴 페이지 경계에서 시가총액이 {ratio:.0f}배 급락 "
                f"(같은 구간 내부의 정상 낙폭은 최대 {baseline:.1f}배) — "
                f"{caps[i-1][1]}({caps[i-1][2]/1e12:.1f}조) → {caps[i][1]}({caps[i][2]/1e12:.1f}조). "
                "페이지를 잘못 넘겼을 수 있습니다(startIdx 는 오프셋이 아니라 페이지 인덱스)."
            )

    seen, dupes = set(), set()
    for code, _, _ in caps:
        (dupes if code in seen else seen).add(code)
    if dupes:
        warnings.append(
            f"🔴 같은 종목이 두 번 이상 들어왔습니다({len(dupes)}종목) — 페이지가 겹쳤을 수 있습니다: "
            f"{sorted(dupes)[:5]}"
        )

    if len(rows) < LIST_TARGET_COUNT * 0.9:
        warnings.append(
            f"🟡 목표 {LIST_TARGET_COUNT}종목 중 {len(rows)}종목만 받았습니다 "
            "(페이지가 일찍 비었거나 요청이 실패했을 수 있습니다)"
        )
    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 "값이 같은가"를 넘어 — **정제까지 제대로 되는가** (2026-09-08 오너 지적)
#
#   오너 ①: *"매일 다른 종목 100개를 쌓으면, 그 사이사이에 데이터가 바뀌었을 때
#            바뀐 데이터를 정리하는 것까지 오류를 잡을 수 있겠어?"*
#   오너 ②: *"우리가 데이터 정제까지도 중요한데 크롤링해서 제대로 제 위치를 잡을 수 있을지
#            없을지도 봐야 할 것 아냐. 현재 국내주식은 위아래가 다 롤러코스터라서."*
#
#   실측(2026-08~09 히스토리):
#     · `t_eps` 는 **거의 매일** 바뀝니다 — 실적 시즌엔 하루 **74종목**, 평소 6~21종목.
#     · 시총 순위는 하루 중앙값 2~3계단, **최대 70계단**까지 뜁니다.
#     · **매일 1~7종목이 500위권에 새로 들어옵니다.**
#
#   → "오늘 값이 같은가"만 보면 **언제 어긋났는지도, 왜 어긋났는지도** 알 수 없습니다.
#     아래 세 검사가 그 공백을 메웁니다.
# ─────────────────────────────────────────────────────────────────────────────

RANK_TOLERANCE = 0                 # 순위는 한 칸도 어긋나면 안 됩니다(오늘 실측 0/520)
CHANGE_SYNC_MIN_OVERLAP = 0.8      # 값이 바뀐 종목 집합의 최소 일치율


# 응답이 이보다 느려지면 상대 서버가 힘들어하고 있다는 신호로 봅니다(§0-3-2).
RESPONSE_SLOW_SEC = 3.0
# 수집이 이보다 길어지면 다음 장 시작까지 걸칠 위험이 있습니다.
TOTAL_TOO_LONG_MIN = 90


def check_timing(timing: dict) -> list[str]:
    """**시간이 정상 범위인가** (2026-09-08 오너 요구)."""
    if not timing:
        return []
    warnings = []
    median = timing.get("response_sec_median")
    if median is not None and median >= RESPONSE_SLOW_SEC:
        warnings.append(
            f"🔴 응답이 느립니다 — 중앙값 {median}초(최대 {timing.get('response_sec_max')}초). "
            "상대 서버가 힘들어하는 신호일 수 있습니다(§0-3-2). 요청을 늘리지 마세요."
        )
    total = timing.get("total_sec")
    if total is not None and total / 60 >= TOTAL_TOO_LONG_MIN:
        warnings.append(
            f"🔴 수집이 {total / 60:.0f}분 걸렸습니다 — 장 시작까지 걸칠 위험이 있습니다."
        )
    return warnings


def check_rank_integrity(rows) -> list[str]:
    """**① 제 위치를 잡았는가** — 받은 순서가 실제 시가총액 순서와 같은가.

    현행은 코스피·코스닥을 따로 받아 합친 뒤 **직접 재정렬**합니다
    (`collector_kospi200._rank_candidates_by_market_cap` — 구 순위 페이지에 시총 숫자
    컬럼이 없기 때문). 신 API 는 통합 정렬된 순서를 `marketSum` 과 함께 주므로,
    **그 순서를 믿어도 되는지**를 매일 확인합니다.
    """
    warnings = []
    caps = [(r.get("code"), r.get("name"),
             r.get("market_cap_api_truncated") or 0,
             (r.get("price") or 0) * (r.get("outstanding_shares") or 0)) for r in rows]
    if len(caps) < 2:
        return warnings

    desc = [i for i in range(len(caps) - 1) if caps[i][2] and caps[i + 1][2]
            and caps[i][2] < caps[i + 1][2]]
    if desc:
        warnings.append(
            f"🔴 받은 순서가 시가총액 내림차순이 아닙니다({len(desc)}곳) — "
            f"예: {caps[desc[0]][1]} → {caps[desc[0] + 1][1]}"
        )

    # 직접 계산(현재가 × 상장주식수)으로 다시 세워도 같은 순서여야 합니다.
    order = {c[0]: i for i, c in enumerate(caps)}
    recomputed = sorted(caps, key=lambda c: -c[3])
    moved = [(c[1], order[c[0]], j) for j, c in enumerate(recomputed)
             if abs(order[c[0]] - j) > RANK_TOLERANCE]
    if moved:
        worst = max(moved, key=lambda m: abs(m[1] - m[2]))
        warnings.append(
            f"🟡 직접 계산한 시총으로 재정렬하면 {len(moved)}종목의 순위가 달라집니다 — "
            f"최대 {worst[0]}: {worst[1] + 1}위 → {worst[2] + 1}위. "
            "받은 순서를 그대로 쓰면 '제 위치'가 아닐 수 있습니다."
        )
    return warnings


def check_change_sync(today_rows, yesterday_rows, prod_today, prod_yesterday) -> list[str]:
    """**② 값이 바뀔 때 양쪽이 같이 바뀌는가.**

    실적이 발표되면 `t_eps` 가 바뀝니다. 그때 **신 API 도 실전도 함께** 바뀌어야 정상입니다.
    한쪽만 바뀌면 둘 중 하나가 갱신을 놓친 것이고, **그건 값이 같은지만 봐서는 안 보입니다**
    (바뀌기 전에는 둘 다 옛 값이라 '일치'로 나옵니다).

    어제 자료가 없으면 **조용히 넘어가지 않고** 그 사실을 남깁니다(§0-1).
    """
    if not yesterday_rows or not prod_yesterday:
        return ["🟡 어제 자료가 없어 변경 동조를 확인하지 못했습니다(첫 실행이면 정상)"]

    warnings = []
    for key, label in (("t_eps", "Trailing EPS"), ("t_roe", "ROE")):
        shadow_changed = {c for c in today_rows
                          if c in yesterday_rows
                          and _f(today_rows[c].get(key)) is not None
                          and _f(yesterday_rows[c].get(key)) is not None
                          and _f(today_rows[c].get(key)) != _f(yesterday_rows[c].get(key))}
        prod_changed = {c for c in prod_today
                        if c in prod_yesterday
                        and _f(prod_today[c].get(key)) is not None
                        and _f(prod_yesterday[c].get(key)) is not None
                        and _f(prod_today[c].get(key)) != _f(prod_yesterday[c].get(key))}
        union = shadow_changed | prod_changed
        if not union:
            continue
        overlap = len(shadow_changed & prod_changed) / len(union)
        if overlap < CHANGE_SYNC_MIN_OVERLAP:
            only_shadow = sorted(shadow_changed - prod_changed)[:5]
            only_prod = sorted(prod_changed - shadow_changed)[:5]
            warnings.append(
                f"🔴 {label} 가 바뀐 종목이 서로 다릅니다 (일치율 {overlap * 100:.0f}%) — "
                f"신 API 만 바뀜 {len(shadow_changed - prod_changed)}종목{only_shadow}, "
                f"실전만 바뀜 {len(prod_changed - shadow_changed)}종목{only_prod}. "
                "한쪽이 갱신을 놓쳤을 수 있습니다."
            )
    return warnings


def check_universe_drift(shadow_codes, prod_codes) -> list[str]:
    """**③ 같은 종목 집합을 잡는가.**

    국내 시장은 변동이 커서 매일 1~7종목이 상위 500위권을 드나듭니다(실측).
    경계에서 몇 종목 어긋나는 것은 **정상**이지만, 크게 벌어지면 범위 설정이 틀린 것입니다.
    """
    a, b = set(shadow_codes), set(prod_codes)
    if not a or not b:
        return ["🟡 종목 집합 비교에 필요한 자료가 없습니다"]
    only_a, only_b = a - b, b - a
    drift = max(len(only_a), len(only_b)) / max(len(b), 1)
    if drift > 0.05:                      # 5% 넘게 벌어지면 경계 흔들림이 아님
        return [f"🔴 종목 집합이 {drift * 100:.0f}% 어긋납니다 — "
                f"섀도에만 {len(only_a)}종목, 실전에만 {len(only_b)}종목. "
                "수집 범위나 시장 필터가 다를 수 있습니다."]
    return []


def rotating_sample(codes, size, *, salt=0, day=None):
    """오늘 볼 표본을 고릅니다 — **날짜로 결정되는 회전**.

    같은 날 다시 돌리면 **같은 표본**이 나옵니다(재현 가능). 날이 바뀌면 다음 구간으로
    넘어가 며칠이면 전체를 한 바퀴 돕니다.

    🔴 특정 종목을 코드에 박지 않습니다(§2-2). 순서와 날짜만으로 정합니다.
    `salt` 는 상세 표본과 위즈리포트 표본이 **같은 종목만 반복해서 보지 않도록** 어긋냅니다.
    """
    if not codes or size <= 0:
        return []
    day = day if day is not None else datetime.now(KST).toordinal()
    n = len(codes)
    start = ((day + salt) * size) % n
    if size >= n:
        return list(codes)
    idx = [(start + i) % n for i in range(size)]
    return [codes[i] for i in idx]


def collect(sess: PoliteSession) -> dict:
    """목록 전체 + 상세 표본. 실패도 **같은 스키마로** 기록합니다(빼지 않습니다)."""
    started_at = datetime.now(KST)
    stage_started = time.monotonic()
    result = {
        "collected_at_kst": started_at.isoformat(timespec="seconds"),
        "started_at_kst": started_at.isoformat(timespec="seconds"),
        "timing": {},
        "list_rows": [], "list_raw_sample": [], "detail": {}, "detail_raw_sample": {},
        "wisereport": {}, "detail_sample_codes": [], "wisereport_sample_codes": [],
        "errors": [], "stopped_reason": None,
    }

    # ── 1) 목록 (시가총액 순) ────────────────────────────────────────────────
    page_boundaries = []          # 각 페이지가 list_rows 의 몇 번째부터 시작했는지
    try:
        for page in range(LIST_PAGE_COUNT):
            url = LIST_URL.format(page=page, size=LIST_PAGE_SIZE)
            payload = sess.get_json(url)
            if payload is None:
                result["errors"].append(f"목록 {page}페이지 수집 실패")
                continue
            if page == 0:
                result["list_raw_sample"] = payload[:3]   # raw 보관은 표본만(§0-3-3)
            page_boundaries.append(len(result["list_rows"]))
            try:
                result["list_rows"].extend(
                    parse_market_list(payload, source_url=url, market_label="UNKNOWN")
                )
            except NaverApiSourceError as e:
                result["errors"].append(f"목록 {page}페이지 파싱 거부: {e}")
            if not payload:
                break                                     # 더 줄 게 없으면 그만 요청합니다
    except (CircuitOpen, BlockedByServer) as e:
        result["stopped_reason"] = str(e)
        return result

    # 🔴 페이지를 잘못 넘겼는지 **코드가 직접 확인**합니다(2026-09-08 신설, 위 주석 참고).
    result["pagination_warnings"] = check_pagination_continuity(
        result["list_rows"], page_boundaries)
    # 🔴 "제 위치를 잡았는가" — 받은 순서가 실제 시총 순서와 같은지(오너 지적 ②).
    result["rank_warnings"] = check_rank_integrity(result["list_rows"])
    result["errors"].extend(result["pagination_warnings"] + result["rank_warnings"])

    result["timing"]["list_sec"] = round(time.monotonic() - stage_started, 1)
    stage_started = time.monotonic()
    codes = [r["code"] for r in result["list_rows"]]

    # ── 2) 상세: 시총 상위 200종목 **전부, 매일** (회전 없음 — 오너 결정) ────
    detail_codes = codes[:DETAIL_SAMPLE_SIZE]
    result["universe_size"] = SHADOW_UNIVERSE_SIZE
    result["detail_sample_codes"] = detail_codes
    try:
        for i, code in enumerate(detail_codes):
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

    result["timing"]["detail_sec"] = round(time.monotonic() - stage_started, 1)
    stage_started = time.monotonic()

    # ── 3) 위즈리포트 표본 (Forward ROE·EV/EBITDA) ──────────────────────────
    #    🔴 3회차까지 이 두 값의 검증률이 **0%** 였습니다 — `f_pegy` 의 재료인데도요.
    #    상세와 **같은 200종목**을 봅니다 — 한 종목의 모든 재료를 같은 날 함께 봐야
    #    "이 종목에서 무엇이 어긋났는가"를 한 줄로 읽을 수 있습니다.
    wise_codes = codes[:WISEREPORT_SAMPLE_SIZE]
    result["wisereport_sample_codes"] = wise_codes
    try:
        for i, code in enumerate(wise_codes):
            url = WISEREPORT_URL.format(code=code)
            html = sess.get_text(url)
            if html is None:
                result["wisereport"][code] = {"errors": ["위즈리포트 수집 실패"]}
                continue
            if i == 0:
                result["wisereport_raw_sample_bytes"] = len(html)
            result["wisereport"][code] = parse_financial_summary(html)
    except (CircuitOpen, BlockedByServer) as e:
        result["stopped_reason"] = str(e)

    result["timing"]["wisereport_sec"] = round(time.monotonic() - stage_started, 1)
    _finish_timing(result, started_at, sess)
    return result


def _finish_timing(result, started_at, sess):
    """🔴 **크롤링 시작·종료 시각과 소요를 남깁니다** (2026-09-08 오너 요구).

    왜 필요한가:
      ① **이관 후 실전이 얼마나 걸릴지** 추정하려면 실측이 있어야 합니다
         (현행 `scrape.yml` 은 500종목에 20~30분).
      ② **장중에 걸치는지** 확인 — 수집이 길어져 다음 장 시작까지 가면
         백필 없는 수집기가 장중 가격을 종가로 저장하는 사고가 납니다.
      ③ **상대 서버가 느려지는지** 감지 — 응답이 느려지는 것은 부하 신호입니다(§0-3-2).
    """
    ended_at = datetime.now(KST)
    elapsed = [e["elapsed_sec"] for e in sess.log if e.get("elapsed_sec") is not None]
    t = result["timing"]
    t["ended_at_kst"] = ended_at.isoformat(timespec="seconds")
    t["total_sec"] = round((ended_at - started_at).total_seconds(), 1)
    t["requests"] = len(sess.log)
    if elapsed:
        ordered = sorted(elapsed)
        t["response_sec_median"] = round(ordered[len(ordered) // 2], 3)
        t["response_sec_max"] = round(ordered[-1], 3)
        t["response_sec_total"] = round(sum(elapsed), 1)
        slowest = max(sess.log, key=lambda e: e.get("elapsed_sec") or 0)
        t["slowest_url"] = slowest.get("url", "")[-80:]
    # 대기(딜레이)에 쓴 시간 = 전체 − 실제 응답 대기. 매너 장치가 실제로 도는지 확인용.
    t["waiting_sec"] = round(t["total_sec"] - t.get("response_sec_total", 0), 1)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 대조 — 현행 스냅샷과 얼마나 맞는가
# ─────────────────────────────────────────────────────────────────────────────

# (섀도 키, 현행 스냅샷 키, 허용 오차 비율, 설명)
COMPARE_FIELDS = [
    ("price", "price", 0.005, "현재가"),
    ("t_roe", "t_roe", 0.01, "ROE"),
    ("t_eps", "t_eps", 0.01, "Trailing EPS"),
    ("t_per", "t_per", 0.01, "Trailing PER"),
    ("outstanding_shares", "outstanding_shares", 0.0001, "상장주식수"),
]

# 상세 API 표본에서만 나오는 항목 — `f_pegy` 의 재료입니다.
COMPARE_FIELDS_DETAIL = [
    ("f_eps", "f_eps", 0.01, "추정 EPS"),
    ("t_pbr", "t_pbr", 0.02, "PBR"),
    # 🟡 `f_per` 은 **의도적으로 어긋납니다.** 현행은 네이버 구 사이트의 표시값이라
    #    258종목 **전부가 정수**로 반올림돼 있고, 신 API 는 소수점을 줍니다.
    #    오너 방침대로 신 API 값을 그대로 받으므로, 여기서는 **관찰만** 하고
    #    알림 임계에서는 제외합니다(아래 `ALERT_EXEMPT_FIELDS`).
    ("f_per", "f_per", 0.01, "추정 PER (현행은 정수 반올림 — 어긋나는 것이 정상)"),
]

# 위즈리포트 표본에서만 나오는 항목 — 3회차까지 검증률 0% 였던 자리입니다.
COMPARE_FIELDS_WISEREPORT = [
    ("f_roe", "f_roe", 0.01, "Forward ROE"),
    ("t_roe", "t_roe", 0.01, "ROE(위즈리포트)"),
    ("ev_ebitda", "ev_ebitda", 0.01, "EV/EBITDA"),
]

# 어긋나는 것이 **정상인** 항목 — 알림을 울리지 않습니다(§0-1: 이유를 알고 두는 것).
ALERT_EXEMPT_FIELDS = {"f_per"}


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _previous_shadow(today_path):
    """어제(또는 그 이전) 섀도 파일. 없으면 None — 조용히 넘기지 않고 호출부가 기록합니다."""
    files = sorted(f for f in SHADOW_DIR.glob("*_shadow.json") if f != today_path)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _production_history_by_date():
    """실전 히스토리 CSV 를 날짜별로. **읽기만** 합니다."""
    path = REPO_ROOT / "data" / "kospi200_stock_history.csv"
    if not path.is_file():
        return {}
    import csv
    by_date = {}
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d, c = row.get("date"), row.get("code")
            if d and c:
                by_date.setdefault(d, {})[c] = row
    return by_date


def compare_with_production(shadow: dict, *, today_path=None) -> dict:
    """실전 스냅샷을 **읽기만** 합니다. 쓰지 않습니다."""
    out = {"compared_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
           "fields": {}, "matched_codes": 0, "shadow_only": 0, "production_only": 0,
           "integrity_warnings": [], "note": ""}
    if not PRODUCTION_SNAPSHOT.is_file():
        out["note"] = "실전 스냅샷이 없어 대조하지 못했습니다."
        return out

    prod = {s["code"]: s for s in json.load(PRODUCTION_SNAPSHOT.open(encoding="utf-8"))["stocks"]}
    shad = {r["code"]: r for r in shadow.get("list_rows", [])}
    common = set(prod) & set(shad)
    out["matched_codes"] = len(common)
    out["shadow_only"] = len(set(shad) - set(prod))
    out["production_only"] = len(set(prod) - set(shad))

    detail = shadow.get("detail", {})
    wise = shadow.get("wisereport", {})
    out["detail_sample_size"] = len(detail)
    out["wisereport_sample_size"] = len(wise)

    groups = [(COMPARE_FIELDS, shad, common, ""),
              (COMPARE_FIELDS_DETAIL, detail, set(detail) & set(prod), "상세: "),
              (COMPARE_FIELDS_WISEREPORT, wise, set(wise) & set(prod), "위즈: ")]

    for fields, source, codes, prefix in groups:
      for skey, pkey, tol, label in fields:
        ok = ng = na = 0
        worst = []
        for code in sorted(codes):
            a, b = _f(source[code].get(skey)), _f(prod[code].get(pkey))
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
        out["fields"][prefix + skey] = {
            "label": prefix + label, "match": ok, "mismatch": ng, "not_comparable": na,
            "match_ratio": round(ok / total, 4) if total else None,
            "worst": worst[:10],
            "alert_exempt": skey in ALERT_EXEMPT_FIELDS,
        }

    # ── 🔴 "값이 같은가"를 넘어선 검사 (2026-09-08 오너 지적) ─────────────────
    out["timing"] = shadow.get("timing", {})
    out["integrity_warnings"] = list(shadow.get("rank_warnings", []))
    out["integrity_warnings"] += check_timing(shadow.get("timing", {}))
    out["integrity_warnings"] += check_universe_drift(shad.keys(), prod.keys())

    prev = _previous_shadow(today_path)
    hist = _production_history_by_date()
    prev_rows = {r["code"]: r for r in prev.get("list_rows", [])} if prev else {}
    prev_date = sorted(hist)[-2] if len(hist) >= 2 else None
    out["integrity_warnings"] += check_change_sync(
        shad, prev_rows, prod, hist.get(prev_date, {}) if prev_date else {})
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
    # 페이지네이션 경고는 **일치율보다 먼저** 봅니다 — 엉뚱한 구간을 모아 왔다면
    # 일치율 숫자 자체가 의미가 없습니다.
    shadow_files = sorted(SHADOW_DIR.glob("*_shadow.json"))
    if shadow_files:
        try:
            latest = json.loads(shadow_files[-1].read_text(encoding="utf-8"))
            for w in latest.get("pagination_warnings", [])[:3]:
                problems.append(w.replace("🔴 ", "").replace("🟡 ", ""))
        except (ValueError, OSError):
            pass
    for w in r.get("integrity_warnings", [])[:3]:
        if w.startswith("🔴"):                 # 🟡 는 참고용 — 알림까지 울리지 않습니다
            problems.append(w.replace("🔴 ", ""))
    if r.get("matched_codes", 0) < ALERT_MIN_COMMON_CODES:
        problems.append(f'공통 종목이 {r.get("matched_codes")}개뿐 (대조 불가 수준)')
    for f in r.get("fields", {}).values():
        if f.get("alert_exempt"):
            continue                    # 어긋나는 것이 정상인 항목 (예: f_per — 사유는 상수 주석)
        ratio = f.get("match_ratio")
        if ratio is None:
            problems.append(f'{f["label"]}: 비교 가능한 종목이 없음')
        elif ratio < ALERT_MATCH_RATIO_FLOOR:
            problems.append(f'{f["label"]}: 일치율 {ratio * 100:.1f}%')
    return " / ".join(problems)


# ─────────────────────────────────────────────────────────────────────────────

# 한국 증시 정규장 (평일 09:00~15:30 KST).
MARKET_OPEN_HHMM, MARKET_CLOSE_HHMM = (9, 0), (15, 30)


def market_session_warning(now=None) -> str:
    """장중이면 경고 문장, 아니면 빈 문자열.

    🔴 왜 필요한가: 이 저장소는 **장중 실행으로 실제 사고를 겪었습니다**
       (`watch_schedule_health.yml` 이 그래서 장중에는 수집기 자동 재실행을 생략합니다 —
       백필 기능이 없는 수집기가 장중에 돌면 그 순간의 가격이 그날 종가로 저장됩니다).

    섀도는 실전 데이터를 건드리지 않으므로 **막지는 않습니다.** 다만 장중에 돌리면
    신 API 는 **오늘 실시간가**, 대조 상대인 실전 스냅샷은 **어제 종가**라
    현재가가 전부 불일치로 나옵니다 — 값이 틀린 게 아니라 **기준 시점이 다른 것**인데,
    그걸 모르고 보면 "신 API 가 틀렸다"고 잘못 읽게 됩니다(§0-1).
    """
    now = now or datetime.now(KST)
    if now.weekday() >= 5:                      # 토·일
        return ""
    hm = (now.hour, now.minute)
    if MARKET_OPEN_HHMM <= hm <= MARKET_CLOSE_HHMM:
        return ("⚠️ 지금은 한국 증시 장중(평일 09:00~15:30 KST)입니다. 신 API 는 오늘 실시간가를, "
                "대조 상대인 실전 스냅샷은 어제 종가를 담고 있어 **현재가가 전부 불일치로 나옵니다** "
                "— 값이 틀린 게 아니라 기준 시점이 다른 것입니다. "
                "장 마감 후(16:00 이후)나 개장 전에 돌리면 깨끗하게 대조됩니다.")
    return ""


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
        warning = market_session_warning()
        if warning:
            print(warning)
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
        if warning:
            shadow.setdefault("errors", []).append(warning)
            shadow["ran_during_market_hours"] = True
        shadow["request_log"] = sess.log if not args.compare_only else []
        shadow["request_count"] = getattr(sess, "request_count", 0)
        json.dump(shadow, _assert_shadow_path(raw_path).open("w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        t = shadow.get("timing", {})
        print(f"💾 {raw_path.name} 저장 — 요청 {shadow['request_count']}건, "
              f"종목 {len(shadow['list_rows'])}개")
        if t:
            print(f"⏱️  {shadow.get('started_at_kst','?')[11:]} → {t.get('ended_at_kst','?')[11:]} "
                  f"(총 {t.get('total_sec',0)/60:.1f}분)")
            print(f"    목록 {t.get('list_sec',0):.0f}초 · 상세 {t.get('detail_sec',0):.0f}초 · "
                  f"위즈리포트 {t.get('wisereport_sec',0):.0f}초")
            print(f"    응답 중앙값 {t.get('response_sec_median','?')}초 / "
                  f"최대 {t.get('response_sec_max','?')}초 / 대기 {t.get('waiting_sec',0)/60:.1f}분")

    report = compare_with_production(shadow, today_path=raw_path)
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
