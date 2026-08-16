# Dockerfile — NiceGUI 앱용 (Streamlit Community Cloud는 Dockerfile을 안 씀 — 이건 Render 전용)
#
# 이전 계획서(NICEGUI_MIGRATION_PLAN.md §8-2) 그대로.
FROM python:3.12-slim

# ⚠️ tzdata 필수 — python:*-slim 에는 타임존 DB가 없어서 zoneinfo.ZoneInfo("Asia/Seoul")이
#    실패합니다. 실패해도 앱이 조용히 UTC로 폴백하면 KST 기준 날짜가 어긋난 채 "정상처럼"
#    동작할 수 있어(ENGINEERING_SPEC.md §0-1 위반), 반드시 명시적으로 설치합니다.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render 는 PORT 환경변수를 주입합니다. main.py 가 이걸 읽습니다.
ENV PORT=10000
EXPOSE 10000

CMD ["python", "main.py"]
