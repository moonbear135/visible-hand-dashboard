# tests/_naver_item_baseline.py
"""
🔒 `collector_kospi200.fetch_naver_item_dps_and_eps()` 특성화 기준선 — 공용 실행부 (2026-09-07)

이 파일이 왜 있는가
--------------------
`fetch_naver_item_dps_and_eps()` 는 372줄짜리 파서입니다. 구획 A(aside 스냅샷) · 구획 B(주요
재무제표) · EV/EBITDA · 우선주 DPS 상속 네 덩어리가 한 함수에 들어 있고, 각 구획이 §0-1 을
지키려고 "실패했다"와 "값이 없다"를 세밀하게 구분합니다. 그 구분이 바로 이 저장소가 과거에
여러 번 사고를 낸 지점(2차 감사 1-1/1-4/1-6/1-7, 재감사 H1/H2/H3/H12)이라, 쪼개기 전에
**결과가 한 글자도 안 바뀌는지 증명할 장치**가 먼저 있어야 합니다.

입력 HTML 은 왜 합성인가 (§0-1 관련 — 반드시 읽을 것)
----------------------------------------------------
`enrich_quant_metrics` 기준선은 **실수집 스냅샷**에서 입력을 뽑았지만, 이 함수의 입력은
네이버 종목 상세 **페이지 HTML** 이고 저장소에는 그 원본이 없습니다. 새로 받아오려면 네이버를
다시 긁어야 하는데, 그건 §0-3-2(상대 서버에 무리를 주지 않는다)에 어긋납니다.

그래서 `tests/fixtures/naver_item/` 의 HTML 은 **실제 페이지 구조를 본뜬 합성 픽스처**입니다.
이 저장소가 이미 쓰던 방식과 같습니다(`tests/test_collector_kospi200_ranking.py` 의
`_FAKE_ASIDE_ONLY_HTML` · `_FIN_TABLE_TEMPLATE`).

⚠️ 그래서 이 기준선이 **보증하는 것과 못 하는 것**이 분명히 다릅니다:
  · 보증함  — 리팩터가 **파싱 로직의 동작**을 바꿨는지. (이 파일의 목적)
  · 못 함   — 네이버가 **실제 페이지 구조를 바꿨을 때** 잡아내는 것. 그건 크롤링 대상 변화라
             `utils/data_sanity.py`(→ `data-foundation`)와 실운영 로그의 몫입니다.
이 한계를 모르고 "파서가 안전하다"고 믿으면 그게 §0-1 이 말하는 겉보기 정상입니다.

기준선을 다시 만들어야 할 때
--------------------------
파싱 **결과가 의도적으로** 바뀌는 변경을 했을 때만입니다. 리팩터에서 빨간불이면 리팩터가
틀린 것이므로 기준선을 고치지 말고 코드를 고치세요.

    python tests/_naver_item_baseline.py --regenerate

⚠️ 오너 승인 없이 돌리지 마세요.
"""
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

FIXTURES = Path(__file__).parent / "fixtures" / "naver_item"
BASELINE_PATH = Path(__file__).parent / "fixtures" / "naver_item_baseline.json"

# 각 사례: (종목코드, 이 사례가 밟게 하려는 분기 설명)
# `<code>.main.html` 은 종목 상세 페이지, `<code>.wisereport.html` 은 EV/EBITDA 페이지.
# wisereport 파일이 없으면 그 요청은 404 로 답합니다(= 값 미수집 경로).
CASES = [
    ("000010", "정상 — 흑자·Forward 있음·DPS 있음·ROE(E) 있음·EV/EBITDA 있음"),
    ("000020", "적자 — PER/EPS 음수 부호 보존 (2차 감사 1-1)"),
    ("000030", "무배당 확정 — 주당배당금 전부 '-' + 배당수익률 N/A (재감사 H3)"),
    ("000040", "DPS 셀 파싱 오류 — '미공시' 셀은 무배당 확정으로 승격되면 안 됨 (재감사 H2)"),
    ("000050", "aside 만 있고 재무제표 표 없음 — 구획 B 실패해도 A 값 보존 (재감사 H1)"),
    ("000060", "표가 하나도 없음 — pd.read_html 이 예외를 던지는 페이지"),
    ("000070", "자본잠식 — PBR 음수 부호 보존"),
    ("000080", "상장주식수 산티 실패 — 후보가 전부 100만 주 미만"),
    ("000090", "Forward ROE 이상치 — ±300% 초과는 값 자체를 제외"),
    ("000100", "연간 컬럼 헤더 분류 실패 — iloc 폴백 없이 DPS 미수집 (SPEC §2-1)"),
    ("00011K", "우선주 — 보통주(000110)에서 DPS 상속 (재감사 H12: 마스터 확인된 경우만)"),
    ("00012K", "우선주 — 부모가 마스터에서 STOCK 으로 확인 안 됨 → 상속 보류"),
    ("000130", "빈 페이지 — aside 도 표도 없음"),
]

# 우선주 상속 판정에 쓰는 마스터 목록(얼림). 실제 `_get_ticker_types_cached()` 는 네트워크를
# 타므로 대체합니다. 00011K 의 부모 000110 만 STOCK 으로 두어 두 경로를 모두 밟게 합니다.
TICKER_TYPES = {"000110": "STOCK", "000120": "ETF"}


def _read(name):
    p = FIXTURES / name
    return p.read_text(encoding="utf-8") if p.is_file() else None


def run_case(code):
    """
    한 사례를 네트워크 없이 실행합니다. 막는 것은 **HTTP 와 대기뿐**이고,
    파싱·헤더 분류·산티체크 등 계산은 **전부 진짜 코드가 돕니다.**
    """
    import collector_kospi200 as K

    main_html = _read(f"{code}.main.html")
    wise_html = _read(f"{code}.wisereport.html")

    class _Resp:
        def __init__(self, text, status=200):
            self.text = text
            self.status_code = status

    def fake_get(url, headers=None, timeout=None):
        if "wisereport" in url:
            # 부모 종목 요청까지 같은 규칙으로 답합니다(우선주 상속 경로).
            for c in (code, url.rsplit("=", 1)[-1]):
                h = _read(f"{c}.wisereport.html")
                if h is not None:
                    return _Resp(h)
            return _Resp("", 404)
        # 종목 상세: URL 에 든 코드로 파일을 고릅니다(우선주가 부모를 재귀 호출하므로 필요).
        import re as _re
        m = _re.search(r"code=([0-9A-Z]+)", url)
        target = m.group(1) if m else code
        h = _read(f"{target}.main.html")
        return _Resp(h) if h is not None else _Resp("", 404)

    # 🔴 서킷브레이커 상태는 **모듈 전역**이라 사례 간에 새어 나갑니다. 사례마다 초기화하지
    #    않으면 앞 사례의 실패가 뒤 사례의 EV/EBITDA 를 건너뛰게 만들어, 기준선이 실행 순서에
    #    따라 달라집니다(= 기준선 구실을 못 함).
    fresh_circuit = {"consecutive_failures": 0, "open": False, "skipped_count": 0}

    with mock.patch.object(K.requests, "get", fake_get), \
         mock.patch.object(K, "_ev_ebitda_circuit", fresh_circuit), \
         mock.patch.object(K.time, "sleep", lambda *a, **kw: None), \
         mock.patch.object(K, "_get_ticker_types_cached", lambda: dict(TICKER_TYPES)):
        result = K.fetch_naver_item_dps_and_eps(code, ticker_types=dict(TICKER_TYPES))

    return {"result": result, "circuit": fresh_circuit}


def run_all():
    return {code: run_case(code) for code, _desc in CASES}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def load_baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def regenerate():
    missing = [c for c, _ in CASES if not (FIXTURES / f"{c}.main.html").is_file()]
    if missing:
        raise SystemExit(f"🔴 HTML 픽스처가 없는 사례: {missing}")

    out = run_all()
    BASELINE_PATH.write_text(canonical(out) + "\n", encoding="utf-8")
    print(f"✅ 기준선: {BASELINE_PATH}  ({len(out)}사례)")

    again = run_all()
    if canonical(again) != canonical(out):
        raise SystemExit("🔴 두 번 돌린 결과가 다릅니다 — 비결정적 요소가 남아 있습니다.")
    print("✅ 두 번 실행 결과 동일 — 결정적입니다.")

    # 사례별 요약을 찍어 "무엇을 밟았는지" 사람이 바로 볼 수 있게
    for code, desc in CASES:
        r = out[code]["result"]
        print(f"   · {code}  dps_status={r['dps_status']:22s} t_per={str(r['t_per']):>8s} "
              f"ev={str(r['ev_ebitda']):>6s} errors={len(r['errors'])}  — {desc}")


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        regenerate()
    else:
        print(__doc__)
        print("기준선을 다시 만들려면: python tests/_naver_item_baseline.py --regenerate")
