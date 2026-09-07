# tests/test_naver_item_characterization.py
"""
🔒 `collector_kospi200.fetch_naver_item_dps_and_eps()` 특성화 테스트 (2026-09-07)

⚠️ 이 파일이 왜 생겼는가

372줄짜리 파서를 쪼개기 전에 **결과가 한 글자도 안 바뀌는지 증명할 장치**입니다.
이 함수가 특히 위험한 이유는, 여기가 이 저장소에서 **§0-1 사고가 가장 많이 났던 자리**이기
때문입니다 — 적자 기업의 마이너스 부호를 정규식이 버려 24종목이 흑자로 둔갑했고(2차 감사 1-1),
"수집 실패"와 "무배당"을 같은 값으로 뭉개 미수집 종목이 점수를 받았고(1-4), 파싱 실패를
"배당 없음"이라는 실측 사실로 승격시켰고(재감사 H2), 추측한 부모 코드를 검증 없이 크롤링해
DPS 를 상속했습니다(H12). 전부 "값은 그럴듯한데 의미가 틀린" 종류라, 눈으로는 안 보입니다.

**이 파일은 파싱이 옳은지 묻지 않습니다.** 옳고 그름은 `test_collector_kospi200_ranking.py` 의
몫입니다. 여기는 오직 **"지금 내놓는 값을 앞으로도 똑같이 내놓는가"** 만 봅니다.

📌 입력 HTML 은 합성입니다 — 한계를 반드시 알고 쓰세요
   저장소에 네이버 페이지 원본이 없고, 새로 받아오는 것은 §0-3-2 위반입니다. 그래서
   `tests/fixtures/naver_item/` 의 HTML 은 실제 구조를 본뜬 **합성 픽스처**입니다.
   · 보증함 — 리팩터가 파싱 **동작**을 바꿨는지
   · 못 함  — 네이버가 **실제 페이지 구조를 바꿨을 때** 잡아내는 것
   후자는 `utils/data_sanity.py`(→ `data-foundation`)와 실운영 로그의 몫입니다.
   이 한계를 잊고 "파서가 안전하다"고 믿으면 그게 §0-1 이 말하는 겉보기 정상입니다.

📌 빨간불이 났을 때
   리팩터 중이라면 **리팩터가 틀린 것**입니다. 기준선을 고치지 말고 코드를 고치세요.
   파싱 결과가 의도적으로 바뀌는 변경이라면 오너 승인 후
   `python tests/_naver_item_baseline.py --regenerate`.

실행: python -m pytest tests/test_naver_item_characterization.py -v
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다.
# ⚠️ `FAILURES` 와 `check` 를 **둘 다** 가져와야 `test_suite_integrity.py` 의 Check A 가
#    이 파일을 하네스 사용 파일로 인식합니다(하나만 가져오면 통째로 skip 됩니다).
from conftest import FAILURES, check  # noqa: E402,F401
import _naver_item_baseline as BL  # noqa: E402


def test_fixtures_and_baseline_exist():
    """스캐너가 조용히 빈손이 되지 않게 (§0-1)."""
    assert BL.FIXTURES.is_dir(), f"HTML 픽스처 폴더가 없습니다: {BL.FIXTURES}"
    assert BL.BASELINE_PATH.is_file(), f"기준선이 없습니다: {BL.BASELINE_PATH}"
    assert len(BL.CASES) >= 10, f"사례가 {len(BL.CASES)}개뿐입니다 — 2026-09-07 기준 13개입니다."
    baseline = BL.load_baseline()
    assert set(baseline) == {c for c, _ in BL.CASES}, (
        "기준선과 사례 목록이 어긋났습니다 — 둘 중 하나만 갱신된 상태입니다."
    )


def test_output_is_identical_to_baseline():
    """🔴 이 파일의 존재 이유. 리팩터가 파싱 결과를 바꾸면 여기서 빨간불이 납니다."""
    baseline = BL.load_baseline()
    diffs = []
    for code, desc in BL.CASES:
        got = BL.run_case(code)
        want = baseline[code]
        for section in ("result", "circuit"):
            a, b = got[section], want[section]
            for key in sorted(set(a) | set(b)):
                va, vb = a.get(key, "<없음>"), b.get(key, "<없음>")
                if BL.canonical(va) != BL.canonical(vb):
                    diffs.append(f"{code}({desc}) [{section}.{key}] 기준선={vb!r} → 지금={va!r}")
    assert not diffs, (
        f"\n🔴 리팩터 전후 파싱 결과가 달라졌습니다 — {len(diffs)}건.\n"
        "   구조만 바꾸는 리팩터라면 **코드가 틀린 것**입니다. 기준선을 고치지 마세요.\n\n"
        + "".join(f"       - {d}\n" for d in diffs[:30])
        + (f"       ... 외 {len(diffs) - 30}건\n" if len(diffs) > 30 else "")
    )


def test_running_twice_gives_the_same_result():
    """서킷브레이커 상태가 모듈 전역이라, 사례 간 누수가 생기면 실행 순서에 따라 결과가 달라집니다."""
    first = BL.canonical(BL.run_all())
    second = BL.canonical(BL.run_all())
    assert first == second, "같은 입력을 두 번 돌렸는데 결과가 다릅니다 — 상태 누수 또는 비결정성."


def test_baseline_covers_the_failure_modes_that_actually_happened():
    """
    기준선이 한 갈래만 밟으면 "전부 통과"가 아무 의미도 없습니다. 이 저장소에서 **실제로 사고가
    났던 지점**들이 기준선에 살아 있는지 직접 못 박습니다.
    """
    b = BL.load_baseline()
    r = {code: b[code]["result"] for code in b}

    # 2차 감사 1-1 — 적자 기업의 마이너스 부호가 살아 있어야 함
    check(r["000020"]["t_per"] is not None and r["000020"]["t_per"] < 0,
          "적자 종목의 Trailing PER 이 음수로 보존됨", f"(실제 {r['000020']['t_per']})")
    check(r["000020"]["t_eps"] is not None and r["000020"]["t_eps"] < 0,
          "적자 종목의 Trailing EPS 가 음수로 보존됨", f"(실제 {r['000020']['t_eps']})")

    # 재감사 H2 — 파싱 실패를 '무배당 확정'으로 승격하지 않음
    check(r["000040"]["dps_status"] == "not_collected",
          "DPS 셀 파싱 오류는 not_collected", f"(실제 {r['000040']['dps_status']})")

    # 재감사 H3 — 두 근거가 다 있을 때만 무배당 확정
    check(r["000030"]["dps_status"] == "no_dividend_confirmed",
          "재무제표 전부 '-' + 배당수익률 N/A → 무배당 확정")
    check(r["000030"]["div_yield_row_explicit_na"] is True,
          "배당수익률 행이 명시적으로 비어 있음이 기록됨")

    # 재감사 H1 — 구획 B 가 실패해도 구획 A 값은 보존
    check(r["000050"]["t_per"] == 12.34 and r["000050"]["outstanding_shares"] == 59_700_000,
          "재무제표가 없어도 aside 값은 보존됨")
    check(r["000060"]["t_per"] == 12.34,
          "표가 하나도 없는 페이지에서도 aside 값은 보존됨")

    # 재감사 H12 — 마스터에서 STOCK 으로 확인된 부모에서만 상속
    check(r["00011K"]["dps_status"] == "inherited_from_common",
          "부모가 STOCK 이면 DPS 상속", f"(실제 {r['00011K']['dps_status']})")
    check(r["00011K"]["dps_inherited_from"] == "000110",
          "상속 출처가 기록됨", f"(실제 {r['00011K']['dps_inherited_from']})")
    check(r["00012K"]["dps_inherited_from"] is None,
          "부모가 STOCK 이 아니면 상속하지 않음")

    # 자본잠식 — PBR 음수 부호 보존
    # 📌 `t_pbr` 과 `ev_ebitda` 는 **문자열**로 돌아옵니다(원본 표기를 그대로 보존하는 설계 —
    #    `t_per`/`t_eps` 는 숫자라 반환 dict 안에서 타입이 섞여 있습니다). 소비부
    #    (`_compute_graham_number`)가 float() 로 변환합니다. 이 사실을 모르고 숫자로 비교하면
    #    TypeError 가 납니다 — 실제로 이 테스트를 쓰다 걸렸습니다. 동작을 바꾸는 것은
    #    리팩터 범위 밖이므로 여기서는 **사실을 그대로 검사**합니다.
    pbr_070 = r["000070"]["t_pbr"]
    check(isinstance(pbr_070, str) and float(pbr_070) < 0,
          "자본잠식 종목의 PBR 이 음수 문자열로 보존됨", f"(실제 {pbr_070!r})")

    # 상장주식수 산티 — 100만 주 미만은 채택하지 않음
    check(r["000080"]["outstanding_shares"] is None,
          "산티 미달 상장주식수는 지어내지 않고 None")

    # SPEC §2-1 — 연간 컬럼을 못 고르면 iloc 폴백 없이 미수집
    check(r["000100"]["dps"] is None and r["000100"]["dps_status"] == "not_collected",
          "연간 컬럼 분류 실패 시 DPS 를 추정하지 않음")

    # EV/EBITDA 정상 경로가 한 번은 있어야 함
    check(r["000010"]["ev_ebitda"] is not None,
          "EV/EBITDA 수집 성공 사례가 기준선에 있음", f"(실제 {r['000010']['ev_ebitda']})")

    # 상태값이 한 종류로 쏠리지 않았는지
    statuses = {v["dps_status"] for v in r.values()}
    check(len(statuses) >= 4, "dps_status 가 4종류 이상 나옴", f"(실제 {sorted(statuses)})")


def test_no_real_network_call_is_made():
    """
    🔴 이 기준선이 실제로 네이버를 긁으면 §0-3-2 위반이고, 결과도 매번 달라집니다.
    `requests.get` 이 진짜로 불리면 즉시 터지게 해서 확인합니다.
    """
    import collector_kospi200 as K
    from unittest import mock

    real_get = K.requests.get
    called = []

    def tripwire(*a, **kw):
        called.append(a[0] if a else kw.get("url"))
        raise AssertionError("실제 네트워크 요청이 발생했습니다")

    with mock.patch.object(K.requests, "get", tripwire):
        try:
            BL.run_case("000010")   # run_case 가 자체적으로 requests.get 을 덮어씁니다
        finally:
            K.requests.get = real_get

    assert not called, f"기준선 실행이 실제 요청을 보냈습니다: {called}"


def main():
    sys.path.append(str(Path(__file__).parent))
    from _test_discovery import discover_and_run_module_tests

    discover_and_run_module_tests(
        sys.modules[__name__],
        on_skip=lambda names: print(f"  ⏭️ 픽스처가 필요해 건너뜀: {names}"),
    )
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
