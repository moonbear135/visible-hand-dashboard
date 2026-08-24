"""
probe_dart_disclosure_list.py
🔍 DART OpenAPI `list.json`("공시검색") 실측 확인용 — 한 번 쓰고 지울 조사 스크립트.

================================================================================
📌 이 스크립트가 확인하려는 것
================================================================================
배당 수집기(`collector_dividend_kr.py`)를 "분기 마감일마다 전체 유니버스를 다시
훑는" 방식 대신 "매일 가볍게 신규 접수 목록만 확인하고, 우리 유니버스에 있는 회사가
새로 정기보고서를 냈으면 그 회사만 콕 집어 `alotMatter.json`을 부르는" 방식으로
업그레이드하기 전에, `list.json`("공시검색") API 가 실제로 그 방식을 지원하는지
**직접 호출해서** 확인합니다.

이 프로젝트 원칙(§0-1, ENGINEERING_SPEC.md)은 "추측으로 코드 짜지 않기"입니다 —
DART 공식 개발가이드 문서(https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&
apiId=2019001)를 읽고 만든 아래 가정을, 문서가 아니라 **실제 응답**으로 검증합니다:

  ① `bgn_de`/`end_de`(YYYYMMDD)로 접수일 범위를 좁힐 수 있다.
  ② `pblntf_ty=A`(정기공시) + `pblntf_detail_ty`(A001=사업보고서/A002=반기보고서/
     A003=분기보고서)로 우리가 찾는 보고서 종류만 걸러낼 수 있다.
  ③ `corp_code`로 특정 회사만 좁힐 수 있다(교차검증용).
  ④ 응답에 `corp_code`·`stock_code`·`report_nm`·`rcept_dt`·`rcept_no`가 온다.
  ⑤ ⚠️ 가장 중요한 미확인 사항 — `pblntf_detail_ty=A003`(분기보고서)이 1분기보고서와
     3분기보고서를 **구분해서** 주는지, 아니면 뭉뚱그려서 주고 `report_nm` 텍스트로만
     구분해야 하는지. 이게 확인돼야 "새로 올라온 게 1분기 재수집 대상인지 3분기
     재수집 대상인지"를 코드로 판단할 수 있습니다.

================================================================================
📌 어떻게 검증하는가 — 이미 수집된 실제 데이터를 기준점으로 씀 (운에 기대지 않음)
================================================================================
"최근 며칠 사이 아무 공시나 조회"하면 오늘(8월 하순) 시점엔 마침 아무것도 안 걸릴
수 있습니다. 대신 `data/dividend_kr_2026_latest.json`에 **이미 확인된 실제 접수
건**을 골라, `list.json`이 그 건을 똑같이 찾아내는지로 검증합니다:
  · 삼성전자(corp_code 00126380) — 2026-08-14 접수, 반기보고서(rcept_no
    20260814003699)로 이미 확인됨.
  · 서암기계공업(corp_code 00166528) — 2026-06-01 접수, 1분기보고서(rcept_no
    20260601000094)로 이미 확인됨.
그리고 A003(분기보고서) 필터 자체가 1분기/3분기를 구분하는지 보려고, 이미 지나간
2025년 3분기 시즌(11월)과 2026년 1분기 시즌(5월)을 각각 넓게 훑어 `report_nm`
텍스트를 비교합니다.

================================================================================
📌 이 스크립트는 조사용입니다 — 프로덕션 코드가 아닙니다
================================================================================
  · `data/`의 어떤 파일도 읽거나 쓰지 않습니다. 화면에 결과를 출력만 합니다.
  · §0-3-2(외부 서버 예의) — 호출 사이 짧은 딜레이를 둡니다. 호출 횟수는 이 파일
    안에서 고정돼 있고(6회), 반복 실행을 전제하지 않습니다(확인 끝나면 이 파일과
    짝인 워크플로우를 지우세요).
  · 인증키는 `collector_dividend_kr.py`와 똑같이 환경변수 `DART_API_KEY`에서만
    읽습니다. 코드에 적지 않습니다.

이 개발 샌드박스는 프록시 allowlist 때문에 opendart.fss.or.kr 에 직접 못 붙습니다
— 그래서 이 스크립트는 **GitHub Actions에서** 실행해야 합니다(같은 짝
`probe_dart_disclosure_list.yml` 참고).
"""
import json
import os
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DART_API_KEY_ENV = "DART_API_KEY"
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 실측 확인용 기준점 — data/dividend_kr_2026_latest.json 에서 이미 확인된 값 그대로.
SAMSUNG_CORP_CODE = "00126380"
SAMSUNG_KNOWN_RCEPT_DT = "20260814"
SAMSUNG_KNOWN_RCEPT_NO = "20260814003699"

SEOAM_CORP_CODE = "00166528"
SEOAM_KNOWN_RCEPT_DT = "20260601"
SEOAM_KNOWN_RCEPT_NO = "20260601000094"


def _get_json(params, api_key, session):
    query = dict(params)
    query["crtfc_key"] = api_key
    getter = session.get if session is not None else requests.get
    resp = getter(DART_LIST_URL, params=query, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _print_case(title, payload):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    status = payload.get("status")
    message = payload.get("message")
    total_count = payload.get("total_count")
    print(f"status={status} message={message!r} total_count={total_count}")
    rows = payload.get("list") or []
    for row in rows[:20]:
        print(
            f"  · corp_code={row.get('corp_code')} stock_code={row.get('stock_code')!r} "
            f"rcept_dt={row.get('rcept_dt')} rcept_no={row.get('rcept_no')} "
            f"report_nm={row.get('report_nm')!r}"
        )
    if len(rows) > 20:
        print(f"  … 외 {len(rows) - 20}건 (page_count 초과분, 생략)")


def main():
    if requests is None:
        print("❌ requests 패키지가 없습니다. requirements.txt 에 이미 있어야 합니다.")
        sys.exit(1)

    api_key = os.environ.get(DART_API_KEY_ENV)
    if not api_key:
        print(f"❌ 환경변수 {DART_API_KEY_ENV} 가 없습니다. GitHub Actions secrets 를 확인하세요.")
        sys.exit(1)

    session = requests.Session()

    # ── 케이스 1: 삼성전자 반기보고서 접수일 그대로 재현 ─────────────────────
    payload = _get_json(
        {"corp_code": SAMSUNG_CORP_CODE, "bgn_de": SAMSUNG_KNOWN_RCEPT_DT,
         "end_de": SAMSUNG_KNOWN_RCEPT_DT, "pblntf_ty": "A", "page_count": "20"},
        api_key, session,
    )
    _print_case(
        f"[1] 삼성전자 {SAMSUNG_KNOWN_RCEPT_DT} 접수분 (알려진 rcept_no={SAMSUNG_KNOWN_RCEPT_NO})",
        payload,
    )
    found = any(row.get("rcept_no") == SAMSUNG_KNOWN_RCEPT_NO for row in (payload.get("list") or []))
    print(f"  → 알려진 rcept_no 재현 여부: {'✅ 일치' if found else '❌ 못 찾음 — 확인 필요'}")
    time.sleep(2)

    # ── 케이스 2: 서암기계공업 1분기보고서 접수일 그대로 재현 ────────────────
    payload = _get_json(
        {"corp_code": SEOAM_CORP_CODE, "bgn_de": SEOAM_KNOWN_RCEPT_DT,
         "end_de": SEOAM_KNOWN_RCEPT_DT, "pblntf_ty": "A", "page_count": "20"},
        api_key, session,
    )
    _print_case(
        f"[2] 서암기계공업 {SEOAM_KNOWN_RCEPT_DT} 접수분 (알려진 rcept_no={SEOAM_KNOWN_RCEPT_NO})",
        payload,
    )
    found = any(row.get("rcept_no") == SEOAM_KNOWN_RCEPT_NO for row in (payload.get("list") or []))
    print(f"  → 알려진 rcept_no 재현 여부: {'✅ 일치' if found else '❌ 못 찾음 — 확인 필요'}")
    time.sleep(2)

    # ── 케이스 3: pblntf_detail_ty=A003(분기보고서) — 2026년 1분기 시즌(5월) ─
    payload = _get_json(
        {"bgn_de": "20260501", "end_de": "20260531", "pblntf_ty": "A",
         "pblntf_detail_ty": "A003", "page_count": "20", "page_no": "1"},
        api_key, session,
    )
    _print_case("[3] A003(분기보고서) 필터 — 2026-05 (1분기 시즌) report_nm 텍스트 확인", payload)
    time.sleep(2)

    # ── 케이스 4: pblntf_detail_ty=A003(분기보고서) — 2025년 3분기 시즌(11월) ─
    payload = _get_json(
        {"bgn_de": "20251101", "end_de": "20251130", "pblntf_ty": "A",
         "pblntf_detail_ty": "A003", "page_count": "20", "page_no": "1"},
        api_key, session,
    )
    _print_case("[4] A003(분기보고서) 필터 — 2025-11 (3분기 시즌) report_nm 텍스트 확인", payload)
    time.sleep(2)

    # ── 케이스 5: pblntf_detail_ty=A002(반기보고서) — 2026년 8월, corp_cls 값 확인 ─
    payload = _get_json(
        {"bgn_de": "20260814", "end_de": "20260814", "pblntf_ty": "A",
         "pblntf_detail_ty": "A002", "page_count": "20", "page_no": "1"},
        api_key, session,
    )
    _print_case("[5] A002(반기보고서) 필터 — 2026-08-14 접수분 전체 (corp_cls·건수 감 잡기)", payload)
    time.sleep(2)

    # ── 케이스 6: 존재하지 않는 회사/빈 결과일 때 status 값 확인 ──────────
    payload = _get_json(
        {"corp_code": "00000000", "bgn_de": "20260101", "end_de": "20260102",
         "pblntf_ty": "A", "page_count": "10"},
        api_key, session,
    )
    _print_case("[6] 존재하지 않는 corp_code — 빈 결과일 때 status 확인", payload)

    print("\n\n✅ 6개 케이스 전부 완료. 이 로그 전체를 그대로 복사해서 개발 세션에 붙여넣어주세요.")


if __name__ == "__main__":
    main()
