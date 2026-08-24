"""
probe_dart_disclosure_document.py
🔍 DART 수시공시("현금·현물배당결정" 등) 원본 문서 실측 확인용 — 한 번 쓰고 지울 조사 스크립트.

================================================================================
📌 이 스크립트가 확인하려는 것
================================================================================
오너가 실제로 발견한 예시 — 롯데케미칼 "현금·현물배당결정"(2026-08-20 접수,
rcept_no=20260820800655)에는 배당기준일(2026-09-03)·배당금지급 예정일자(2026-09-18)
같은 **진짜 날짜**가 있습니다. 그런데 DART 공식 개발가이드를 뒤져 보니(§0-1 — 문서로
확인한 사실):
  · 이 공시는 `pblntf_ty="I"`(거래소공시)로 분류되고,
  · DART가 제공하는 "구조화된 필드 API"는 정기보고서 주요정보(배당에 관한 사항 포함)와
    주요사항보고서 주요정보(36종, 배당 항목 없음) 둘뿐이라, **이 수시공시의 배당기준일·
    지급일자를 필드로 바로 주는 API가 없습니다.**
  · 남는 방법은 원본 공시서류파일(`document.xml`, rcept_no만 필요) — 이건 문서를 압축된
    zip으로 그대로 줍니다.

여기서 "그래서 파싱이 어렵다"고 넘겨짚지 않고(§0-1 — 추측 금지, 오너가 정확히 지적한
지점), **zip 안에 실제로 뭐가 들어있는지 직접 열어서 확인**하는 것이 이 스크립트의
목적입니다: 파일 형식(xml/html?)·인코딩·"6. 배당기준일"·"7. 배당금지급 예정일자" 같은
라벨이 파싱 가능한 형태로 나오는지.

================================================================================
📌 어떻게 검증하는가 — 오너가 직접 화면으로 확인한 실제 사례를 기준점으로 씀
================================================================================
  · 롯데케미칼 "현금·현물배당결정" — rcept_no 20260820800655 (2026-08-20 접수).
    화면에서 이미 확인된 값: 1주당 배당금 500원, 배당기준일 2026-09-03,
    배당금지급 예정일자 2026-09-18.
  · 추가로 `list.json`(pblntf_ty="I", 2026-08-20 하루)에서 위 rcept_no가 실제로
    같은 날짜·같은 회사로 잡히는지, 그리고 그날 "배당" 키워드가 들어간 report_nm이
    몇 건이나 있는지도 같이 확인합니다(하루치 물량 감 잡기용).

================================================================================
📌 이 스크립트는 조사용입니다 — 프로덕션 코드가 아닙니다
================================================================================
  · `data/`의 어떤 파일도 읽거나 쓰지 않습니다. 화면(로그)에 결과를 출력만 합니다.
  · 받은 zip은 이 실행 안에서만 임시로 풀어보고 커밋하지 않습니다.
  · §0-3-2(외부 서버 예의) — 호출 사이 짧은 딜레이를 둡니다. 호출 횟수는 이 파일 안에서
    고정돼 있고(3회), 반복 실행을 전제하지 않습니다(확인 끝나면 이 파일과 짝인 워크플로우를
    지우세요 — 이 프로젝트 관례).
  · 인증키는 기존 스크립트들과 똑같이 환경변수 `DART_API_KEY`에서만 읽습니다.

이 개발 샌드박스는 프록시 allowlist 때문에 opendart.fss.or.kr 에 직접 못 붙습니다
— 그래서 이 스크립트도 **GitHub Actions에서** 실행해야 합니다(짝
`probe_dart_disclosure_document.yml` 참고).
"""
import io
import os
import sys
import time
import zipfile

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DART_API_KEY_ENV = "DART_API_KEY"
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

# 실측 확인용 기준점 — 오너가 실제 DART 화면에서 확인한 값 그대로.
LOTTE_CHEMICAL_CORP_NAME = "롯데케미칼"
KNOWN_RCEPT_NO = "20260820800655"
KNOWN_RCEPT_DT = "20260820"
KNOWN_REPORT_NM = "현금·현물배당결정"
# 화면에서 직접 읽은 값(파싱 결과와 비교할 정답):
KNOWN_DPS = "500"
KNOWN_RECORD_DATE = "2026-09-03"   # 배당기준일
KNOWN_PAY_DATE = "2026-09-18"      # 배당금지급 예정일자


def _get(url, params, api_key, session):
    query = dict(params)
    query["crtfc_key"] = api_key
    getter = session.get if session is not None else requests.get
    resp = getter(url, params=query, timeout=20)
    resp.raise_for_status()
    return resp


def main():
    if requests is None:
        print("❌ requests 패키지가 없습니다. requirements.txt 에 이미 있어야 합니다.")
        sys.exit(1)

    api_key = os.environ.get(DART_API_KEY_ENV)
    if not api_key:
        print(f"❌ 환경변수 {DART_API_KEY_ENV} 가 없습니다. GitHub Actions secrets 를 확인하세요.")
        sys.exit(1)

    session = requests.Session()

    # ── 케이스 1: list.json(pblntf_ty=I) 로 그날 거래소공시 목록에서 기준 건 재현 ──
    print(f"\n{'=' * 70}\n[1] list.json pblntf_ty=I — {KNOWN_RCEPT_DT} 거래소공시 전체\n{'=' * 70}")
    resp = _get(DART_LIST_URL, {
        "bgn_de": KNOWN_RCEPT_DT, "end_de": KNOWN_RCEPT_DT,
        "pblntf_ty": "I", "page_count": "100", "page_no": "1",
    }, api_key, session)
    payload = resp.json()
    status = payload.get("status")
    total_count = payload.get("total_count")
    total_page = payload.get("total_page")
    print(f"status={status} message={payload.get('message')!r} "
          f"total_count={total_count} total_page={total_page}")
    rows = payload.get("list") or []
    found_known = None
    dividend_keyword_hits = []
    for row in rows:
        name = row.get("report_nm") or ""
        if row.get("rcept_no") == KNOWN_RCEPT_NO:
            found_known = row
        if "배당" in name:
            dividend_keyword_hits.append(
                f"{row.get('corp_name')} / {name} / rcept_no={row.get('rcept_no')}"
            )
    print(f"  → 이 페이지({len(rows)}건)에서 기준 건(rcept_no={KNOWN_RCEPT_NO}) 발견: "
          f"{'✅ ' + str(found_known) if found_known else '❌ 이 페이지엔 없음(페이지 넘어갔을 수 있음)'}")
    print(f"  → 이 페이지에서 report_nm에 '배당' 들어간 건 {len(dividend_keyword_hits)}건:")
    for line in dividend_keyword_hits[:30]:
        print(f"     · {line}")
    if len(dividend_keyword_hits) > 30:
        print(f"     … 외 {len(dividend_keyword_hits) - 30}건 생략")
    if total_page and int(total_page) > 1:
        print(f"  ⚠️ total_page={total_page} — 이 하루치가 1페이지(100건)를 넘습니다. "
              "기준 건이 이 페이지에 없다면 다음 페이지에 있을 수 있습니다(이 조사에서는 "
              "1페이지만 봅니다 — 진짜 기능을 만들 때 페이지네이션 필요).")
    time.sleep(2)

    # ── 케이스 2: document.xml 로 기준 건 원본 문서 받아서 실제로 열어보기 ──────
    print(f"\n{'=' * 70}\n[2] document.xml — rcept_no={KNOWN_RCEPT_NO} 원본 문서 받기\n{'=' * 70}")
    resp = _get(DART_DOCUMENT_URL, {"rcept_no": KNOWN_RCEPT_NO}, api_key, session)
    content_type = resp.headers.get("Content-Type")
    body = resp.content
    print(f"HTTP {resp.status_code} / Content-Type={content_type!r} / 받은 바이트 수={len(body):,}")

    # DART는 요청 자체가 실패하면(예: rcept_no 오류) zip이 아니라 JSON 오류를 200으로 줄 때가
    # 있습니다(alotMatter.json 등 다른 API에서도 본 패턴) — zip인지부터 실제로 확인합니다.
    is_zip = body[:2] == b"PK"
    print(f"  → zip 시그니처(PK)로 시작하는가: {'✅ 예' if is_zip else '❌ 아니오'}")
    if not is_zip:
        print("  ⚠️ zip이 아닙니다 — 응답 앞부분을 그대로 출력합니다(오류 메시지일 가능성):")
        print("  " + body[:500].decode("utf-8", errors="replace"))
        print("\n\n✅ 조사 종료(zip을 못 받아 3번은 건너뜁니다). 이 로그를 그대로 복사해주세요.")
        return

    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = zf.namelist()
        print(f"  → zip 안 파일 목록({len(names)}개): {names}")
        for name in names:
            raw = zf.read(name)
            print(f"\n  --- {name} ({len(raw):,} bytes) ---")
            # 인코딩을 추측하지 않고 몇 가지 후보로 직접 시도합니다(§0-1).
            text = None
            used_encoding = None
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    text = raw.decode(enc)
                    used_encoding = enc
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                print(f"  ❌ utf-8/euc-kr/cp949 전부 디코딩 실패 — 앞 200바이트(hex): "
                      f"{raw[:200].hex()}")
                continue
            print(f"  ✅ 디코딩 성공(encoding={used_encoding}), 문자 수={len(text):,}")
            # 우리가 찾는 라벨이 실제로 이 텍스트 안에 있는지 확인합니다.
            for label in ("배당기준일", "배당금지급", "1주당 배당금", "배당구분"):
                idx = text.find(label)
                if idx == -1:
                    print(f"     · '{label}' → ❌ 못 찾음")
                else:
                    snippet = text[max(0, idx - 20):idx + 120].replace("\n", "\\n")
                    print(f"     · '{label}' → ✅ 위치 {idx}, 주변: …{snippet}…")
            # 파일이 너무 길면 전체를 다 출력하지 않고 앞부분만 보여줍니다(§0-3-2 취지 —
            # 로그를 과하게 쏟아내지 않기). 구조 파악에는 앞부분+라벨 주변이면 충분합니다.
            print(f"  --- {name} 앞 1500자 미리보기 ---")
            print(text[:1500])

    print("\n\n✅ 조사 완료. 이 로그 전체를 그대로 복사해서 개발 세션에 붙여넣어주세요.")
    print(f"   (참고 — 화면에서 읽은 정답값: 1주당 배당금={KNOWN_DPS}원, "
          f"배당기준일={KNOWN_RECORD_DATE}, 지급예정일자={KNOWN_PAY_DATE})")


if __name__ == "__main__":
    main()
