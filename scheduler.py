import schedule
import time
import subprocess
import logging
import sys
import os

# 윈도우 환경 로그 인코딩 설정
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scheduler.log", encoding='utf-8')
    ]
)

# 프로젝트 베이스 디렉토리
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_collector():
    """KOSPI 200 데이터 수집기를 실행합니다."""
    logging.info("🚀 KOSPI 200 데이터 수집 작업을 시작합니다...")
    script_path = os.path.join(BASE_DIR, "collector_kospi200_2.py")
    
    try:
        # 서브프로세스로 수집기 실행 (블로킹 모드)
        result = subprocess.run(
            [sys.executable, script_path], 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            check=False
        )
        
        if result.returncode == 0:
            logging.info("✅ 데이터 수집 작업이 성공적으로 완료되었습니다.")
        else:
            logging.error(f"❌ 데이터 수집 작업 중 오류 발생 (종료 코드: {result.returncode})")
            logging.error(result.stderr)
            
    except Exception as e:
        logging.error(f"⚠️ 스크립트 실행 중 예외가 발생했습니다: {e}")

def run_macro_scraper():
    """거시경제(환율, 수급 등) 데이터 수집기를 실행합니다."""
    logging.info("🌐 거시경제 데이터 수집 작업을 시작합니다...")
    script_path = os.path.join(BASE_DIR, "scrape_daily.py")
    
    try:
        result = subprocess.run(
            [sys.executable, script_path], 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            check=False
        )
        if result.returncode == 0:
            logging.info("✅ 거시경제 데이터 수집 완료.")
        else:
            logging.error(f"❌ 거시경제 수집 오류 발생: {result.stderr}")
    except Exception as e:
        logging.error(f"⚠️ 거시경제 스크립트 실행 예외: {e}")


if __name__ == "__main__":
    logging.info("=========================================")
    logging.info("🤖 Visible Hand 내장 스케줄러가 시작되었습니다.")
    logging.info("=========================================")
    
    # 1. 프로그램 시작 시 최초 1회 실행을 원한다면 주석을 해제하세요.
    # run_collector()
    # run_macro_scraper()

    # 2. 스케줄 등록
    # 예시 1: 매일 특정 시간(예: 오후 4시)에 실행
    schedule.every().day.at("16:00").do(run_collector)
    schedule.every().day.at("16:15").do(run_macro_scraper)
    
    # 예시 2: 매 4시간마다 실행 (원하는 경우 위 설정을 지우고 주석 해제)
    # schedule.every(4).hours.do(run_collector)
    # schedule.every(4).hours.do(run_macro_scraper)

    logging.info("✅ 스케줄이 정상적으로 등록되었습니다. (매일 16:00, 16:15)")
    logging.info("종료하려면 Ctrl+C 를 누르세요.\n")

    # 3. 무한 루프로 대기
    try:
        while True:
            schedule.run_pending()
            time.sleep(10) # 10초마다 스케줄 확인
    except KeyboardInterrupt:
        logging.info("🛑 스케줄러가 사용자에 의해 종료되었습니다.")
