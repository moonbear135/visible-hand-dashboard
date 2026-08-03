import os
import json
import time
import threading
from datetime import datetime

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
        except Exception:
            pass
    return ""

def _scheduler_loop():
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # 16:00 (4 PM) 이후이고, 오늘 날짜로 수집된 데이터가 없다면 실행
            if now.hour >= 16:
                last_run_date = _get_latest_run_date()
                if last_run_date != today_str:
                    print(f"[스케줄러] {today_str} {now.strftime('%H:%M')} - 16시 경과 & 수집 이력 없음. 크롤러를 즉시 실행합니다.")
                    try:
                        from collector_kospi200_2 import run_kospi200_collector
                        run_kospi200_collector()
                        print(f"[스케줄러] {today_str} 수집 완료.")
                    except Exception as e:
                        print(f"[스케줄러] 크롤러 실행 중 오류 발생: {e}")
        except Exception as e:
            print(f"[스케줄러] 메인 루프 에러: {e}")
            
        # 1분 단위로 체크
        time.sleep(60)

def start_scheduler_thread():
    """Streamlit 캐싱을 활용해 백그라운드 스레드를 1회만 생성"""
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    print("[스케줄러] 백그라운드 크롤링 스케줄러가 시작되었습니다.")
