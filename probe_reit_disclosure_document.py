"""
probe_reit_disclosure_document.py
🔍 리츠(REIT) "부동산투자회사금전배당결정" 공시 원문 실측 확인용 — 한 번 쓰고 지울 조사 스크립트.

================================================================================
📌 이 스크립트가 확인하려는 것
================================================================================
`collector_dividend_payment_kr.py`는 처음부터 "리츠 전용 공시('부동산투자회사금전배당결정')
원문의 표 라벨은 아직 못 봤다"고 파일 머리말에 명시해뒀습니다(§0-1 — 확인 안 된 걸 확인한
척하지 않기). 2026-08-25 8월 백필 실행에서 실제로 그 예상이 맞았다는 게 확인됐습니다 —
롯데리츠(330590)ㆍSK리츠(395400)ㆍ코람코더원리츠(417310)ㆍNH올원리츠(400760) 4건 전부
`parse_status=PARTIAL`, `missing_labels`에 "1. 배당구분", "2. 배당종류",
"7. 배당금지급 예정일자"가 그대로 찍혔습니다.

이 스크립트는 그 4건의 **실제 원문**(document.xml)을 받아서 화면(로그)에 그대로 찍습니다 —
어떤 라벨을 쓰는지 짐작하지 않고, 실제로 열어서 확인하기 위해서입니다(§0-1).

================================================================================
📌 어떻게 대상을 고르는가
================================================================================
새로 API를 조회하지 않습니다 — 이미 8월 백필로 받아 `data/dividend_kr_2026_payment_events.json`
에 저장돼 있는 레코드 중 `parse_status == "PARTIAL"` 이고 `report_nm`이 리츠 전용 접두사
(`collector_dividend_payment_kr.REIT_CASH_DIVIDEND_PREFIX`, 짐작해서 새 문자열을 만들지
않고 기존 상수를 그대로 가져다 씀)로 시작하는 것만 골라, 그 `rcept_no`로 원문만 다시
받습니다. `fetch_disclosure_document()`(수집기 본체에 이미 있는 함수, 파일 fetch·zip 해제
로직을 새로 만들지 않고 그대로 재사용 — §0-3-10)를 그대로 씁니다.

================================================================================
📌 이 스크립트는 조사용입니다 — 프로덕션 코드가 아닙니다
================================================================================
  · `data/`의 어떤 파일도 쓰지 않습니다(읽기만). 화면(로그)에 결과를 출력만 합니다.
  · 받은 zip은 이 실행 안에서만 임시로 풀어보고 커밋하지 않습니다.
  · §0-3-2(외부 서버 예의) — 호출 사이 짧은 딜레이를 둡니다. 대상은 이미 알고 있는 4건뿐이라
    호출 횟수가 늘어나지 않습니다(반복 실행을 전제하지 않음 — 확인 끝나면 이 파일과 짝인
    워크플로우를 지우세요, `probe_dart_disclosure_document.py` 전례와 같은 관례).
  · 인증키는 기존 스크립트들과 똑같이 환경변수 `DART_API_KEY`에서만 읽습니다.

이 개발 샌드박스는 프록시 allowlist 때문에 opendart.fss.or.kr 에 직접 못 붙습니다
— 그래서 이 스크립트도 **GitHub Actions에서** 실행해야 합니다(짝
`probe_reit_disclosure_document.yml` 참고).
"""
import json
import os
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# 새 문자열을 짐작해서 만들지 않고, 이미 검증된 수집기 모듈의 상수/함수를 그대로 가져다
# 씁니다(§0-1, §0-3-10) — repo 루트에서 실행되므로 같은 디렉터리의 모듈을 바로 import.
import collector_dividend_payment_kr as payment_collector

EVENTS_PATH = os.path.join("data", "dividend_kr_2026_payment_events.json")
DART_API_KEY_ENV = payment_collector.DART_API_KEY_ENV


def _read_events(path):
    if not os.path.exists(path):
        print(f"❌ {path} 가 없습니다 — 먼저 백필/감시가 최소 1회 성공해서 이 파일이 "
              "생겨야 합니다.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    records = payload.get("records") or []
    print(f"ℹ️ {path} 에서 레코드 {len(records):,}건을 읽었습니다.")
    return records


def main():
    if requests is None:
        print("❌ requests 패키지가 없습니다. requirements.txt 에 이미 있어야 합니다.")
        sys.exit(1)

    # 기존 수집기와 같은 방식(공백 제거 포함)으로 읽습니다 — 새 로직을 만들지 않습니다.
    api_key = payment_collector.get_api_key()
    if not api_key:
        print(f"❌ 환경변수 {DART_API_KEY_ENV} 가 없습니다. GitHub Actions secrets 를 확인하세요.")
        sys.exit(1)

    records = _read_events(EVENTS_PATH)

    # ── 대상 고르기: 리츠 전용 접두사 + PARTIAL 인 것만, rcept_no 로 중복 제거 ──────
    seen_rcept_no = set()
    targets = []
    for record in records:
        report_nm = str(record.get("report_nm") or "")
        parse_status = record.get("parse_status")
        rcept_no = record.get("rcept_no")
        if not report_nm.startswith(payment_collector.REIT_CASH_DIVIDEND_PREFIX):
            continue
        if parse_status != "PARTIAL":
            continue
        if not rcept_no or rcept_no in seen_rcept_no:
            continue
        seen_rcept_no.add(rcept_no)
        targets.append(record)

    print(f"\n{'=' * 70}\n리츠 전용('{payment_collector.REIT_CASH_DIVIDEND_PREFIX}') + "
          f"PARTIAL 레코드: {len(targets)}건\n{'=' * 70}")
    for record in targets:
        print(f"  · {record.get('corp_name')}({record.get('stock_code')}) "
              f"rcept_no={record.get('rcept_no')} rcept_dt={record.get('rcept_dt')}")
        print(f"    missing_labels={record.get('missing_labels')!r}")
        print(f"    parse_notes={record.get('parse_notes')!r}")

    if not targets:
        print("\n⚠️ 조건에 맞는 레코드가 없습니다 — 8월 백필이 먼저 성공해서 "
              f"{EVENTS_PATH} 에 리츠 PARTIAL 레코드가 있어야 합니다. 조사를 종료합니다.")
        return

    session = requests.Session()

    # ── 각 건 원문 받아서 실제로 열어보기 ──────────────────────────────────────
    for i, record in enumerate(targets):
        if i:
            time.sleep(2)
        rcept_no = record.get("rcept_no")
        corp_name = record.get("corp_name")
        print(f"\n{'=' * 70}\n[{i + 1}/{len(targets)}] {corp_name} "
              f"rcept_no={rcept_no} 원문 받기\n{'=' * 70}")
        try:
            text = payment_collector.fetch_disclosure_document(
                rcept_no, api_key, session=session, log=print)
        except Exception as e:
            print(f"  ❌ 원문 조회 실패: {e}")
            continue

        print(f"  ✅ 원문 받음, 문자 수={len(text):,}")
        # 우리가 지금 못 찾는 라벨이 실제로 이 안에 있는지, 있다면 어떤 표기인지 확인합니다.
        for label in ("배당구분", "배당종류", "배당금지급", "배당기준일", "1주당",
                      "이익배당", "금전배당", "현물배당"):
            idx = text.find(label)
            if idx == -1:
                print(f"     · '{label}' → ❌ 못 찾음")
            else:
                snippet = text[max(0, idx - 20):idx + 120].replace("\n", "\\n")
                print(f"     · '{label}' → ✅ 위치 {idx}, 주변: …{snippet}…")

        # 🔴 전체 원문을 그대로 출력합니다 — 실제 파서를 고칠 때 이 로그를 그대로 테스트
        # 픽스처로 씁니다. 일부만 보고 짐작해서 고치면 안 보인 나머지 부분에서 구조가
        # 다를 수 있습니다(§0-1). 대상은 이미 4건으로 고정돼 있어 늘어나지 않습니다.
        print(f"  === {corp_name}({rcept_no}) 원문 전체 시작 ===")
        print(text)
        print(f"  === {corp_name}({rcept_no}) 원문 전체 끝 ===")

    print("\n\n✅ 조사 완료. 이 로그 전체를 그대로 복사해서 개발 세션에 붙여넣어주세요.")


if __name__ == "__main__":
    main()
