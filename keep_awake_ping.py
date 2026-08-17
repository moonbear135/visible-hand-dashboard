"""
keep_awake_ping.py
💤 Streamlit Community Cloud "12시간 무방문 시 잠들기" 방지용 헤드리스 브라우저 핑.

🗑️ **컷오버 2주 뒤 삭제 대상** (2026-08-17 표시)
────────────────────────────────────────────────────────────────────────────
NiceGUI(Render) 컷오버가 끝나서 실서비스는 더 이상 Streamlit 이 아닙니다. 다만 즉시 롤백에
대비해 Streamlit 앱을 **최소 2주는 살려두기로** 결정돼 있어, 그 유예 기간 동안만 이 스크립트를
유지합니다. 유예가 끝나면 이 파일과 `.github/workflows/keep_awake.yml` 의 `streamlit_wake`
job 블록을 함께 지우세요(같은 워크플로우의 `render_healthz` job 은 남겨둬야 합니다 —
그쪽이 실서비스를 깨우는 쪽입니다).

⚠️ 실서비스(Render)는 이 스크립트가 아니라 워크플로우의 `curl .../healthz` 한 줄이 깨웁니다.
   Render 응답은 정적 JSON 이라 Selenium 이 필요 없습니다.

2026-08-09에 curl 기반으로 먼저 만들었다가(.github/workflows/keep_awake.yml),
2026-08-10 실측(Actions 로그)에서 `curl: (47) Maximum (50) redirects followed`로
전부 실패하는 걸 확인했습니다. 원인: Streamlit의 "Yes, get this app back up!" 깨우기는
브라우저에서 JavaScript로 버튼을 눌러야 실행되는 클라이언트 사이드 동작이라, 순수 HTTP
요청(curl)은 그 핸드셰이크를 완료하지 못해 계속 리다이렉트만 받습니다.
그래서 실제 헤드리스 브라우저(Selenium + Chrome)로 페이지를 열고, 깨우기 버튼이 보이면
직접 클릭하는 방식으로 바꿨습니다. streamlit 앱 코드나 crawler 코드와는 무관한 완전
별도 스크립트입니다.
"""

import os
import sys

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# 커스텀 도메인(visiblehand.co.kr)이 아니라 실제 Streamlit 앱 주소를 엽니다.
# 커스텀 도메인은 index.html이 이 주소를 iframe으로 감싸는 구조라, 여기로 직접
# 들어가야 진짜 앱(과 깨우기 버튼)에 도달합니다.
STREAMLIT_URL = os.environ.get(
    "STREAMLIT_APP_URL",
    "https://visible-hand-dashboard-2vmzz6tk63wsac7n345ord.streamlit.app/",
)

WAKE_BUTTON_XPATH = "//button[contains(text(),'Yes, get this app back up')]"


def main() -> int:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(STREAMLIT_URL)
        print(f"방문: {STREAMLIT_URL}")

        wait = WebDriverWait(driver, 20)
        try:
            button = wait.until(EC.element_to_be_clickable((By.XPATH, WAKE_BUTTON_XPATH)))
            print("😴 잠들어 있음 — 깨우기 버튼 발견, 클릭합니다")
            button.click()

            try:
                # 버튼이 사라지면 깨우기 요청이 정상 접수된 것으로 봅니다.
                wait.until(EC.invisibility_of_element_located((By.XPATH, WAKE_BUTTON_XPATH)))
                print("✅ 버튼 클릭 후 사라짐 — 앱이 부팅을 시작했을 것으로 예상")
            except TimeoutException:
                print("⚠️ 버튼을 클릭했는데 사라지지 않음 — 실패 가능성, 실패로 표시")
                return 1

        except TimeoutException:
            # 깨우기 버튼이 아예 안 보이면 이미 깨어있는 상태로 판단합니다.
            print("✅ 깨우기 버튼 없음 — 이미 깨어있는 상태로 판단")

        return 0

    except Exception as e:  # noqa: BLE001 — 이 스크립트는 실패해도 기존 자동화에 영향 없어 광범위 예외 허용
        print(f"❌ 예상치 못한 오류: {e}")
        return 1
    finally:
        driver.quit()
        print("스크립트 종료")


if __name__ == "__main__":
    sys.exit(main())
