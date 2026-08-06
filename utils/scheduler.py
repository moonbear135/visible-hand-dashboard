import os
import json
import time
import threading
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

def _get_latest_run_date():
    """returns the date string (YYYY-MM-DD) of the last successful run"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "kospi200_pegy_latest.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                updated_at_str = data.get("metadata", {}).get("last_updated_at", "")
                if updated_at_str:
                    # '2026-08-03 16:05' -> '2026-08-03'
                    return updated_at_str.split(" ")[0]
        except Exception as e:
            print(f"[스케줄러] 최근 수집 일자 확인 실패: {e}")
    return ""

def _scheduler_loop():
    while True:
        try:
            # 2026-08-06: 서버가 UTC로 돌면 naive now()가 UTC라 "16시"가 실제로는 KST 새벽
            # 1시에 걸려버립니다(같은 유형의 버그를 collector_kospi200.py에서도 발견/수정).
            # 이 스케줄러는 기본 비활성화(ENABLE_INAPP_SCHEDULER)지만, 나중에 켜도 안전하도록
            # 지금 같이 고쳐둡니다.
            now = datetime.now(KST) if KST else datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # 16:00 (4 PM, KST) 이후이고, 오늘 날짜로 수집된 데이터가 없다면 실행
            if now.hour >= 16:
                last_run_date = _get_latest_run_date()
                if last_run_date != today_str:
                    print(f"[스케줄러] {today_str} {now.strftime('%H:%M')} - 16시 경과 & 수집 이력 없음. 크롤러를 즉시 실행합니다.")
                    try:
                        # 파일명 교정: collector_kospi200_2 → collector_kospi200 (존재하지 않던 모듈)
                        from collector_kospi200 import run_kospi200_collector
                        run_kospi200_collector()
                        print(f"[스케줄러] {today_str} 수집 완료.")
                    except Exception as e:
                        print(f"[스케줄러] 크롤러 실행 중 오류 발생: {e}")
        except Exception as e:
            print(f"[스케줄러] 메인 루프 에러: {e}")

        # 1분 단위로 체크
        time.sleep(60)

def start_scheduler_thread():
    """
    Streamlit 프로세스 내부 백그라운드 수집 스레드.

    ⚠️ 기본값은 '비활성화' 입니다.
       - 정식 수집 경로는 GitHub Actions(.github/workflows/scrape.yml) 하나뿐이며,
         웹 렌더링 프로세스가 같은 CSV/JSON 에 동시에 쓰면 이력이 깨질 수 있습니다.
       - 워커가 여러 개면 스레드도 여러 개 뜨고, 종목당 2~3초 슬립 크롤링이
         화면 응답성까지 잡아먹습니다.
       굳이 켜야 한다면 환경변수 ENABLE_INAPP_SCHEDULER=1 로 명시적으로 활성화하십시오.
    """
    if os.environ.get("ENABLE_INAPP_SCHEDULER", "0") != "1":
        print("[스케줄러] 앱 내장 스케줄러는 비활성화 상태입니다 "
              "(정식 수집 경로: GitHub Actions. 강제 활성화: ENABLE_INAPP_SCHEDULER=1)")
        return

    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    print("[스케줄러] 백그라운드 크롤링 스케줄러가 시작되었습니다.")
