import os
import json
import time

# ⚠️ 2026-08-18 마이그레이션 — `google-generativeai`(구글 지원 종료)에서 후속 패키지
# `google-genai` 로 옮김(ENGINEERING_SPEC.md §0-3-12, PROJECT_STATUS.md §0-5-6).
# `utils/scorecard_ocr.py` 도 같은 패키지를 써서 같이 옮겼습니다(§0-3-10). API 모양이
# 바뀌어 `genai.configure()` + `genai.GenerativeModel(name)` 대신 `genai.Client(api_key=...)`
# 로 호출 전용 클라이언트를 만들고 `client.models.generate_content(model=..., contents=...)`
# 를 씁니다.
from google import genai

# ⚠️ 2026-08-25 — 'gemini-2.5-flash'는 이미 죽은 모델입니다. `utils/indicator_ai.py`가
#    실서비스에서 먼저 이 모델로 호출했다가 Render 로그에 다음 404를 받았습니다:
#      404 NOT_FOUND: "This model models/gemini-2.5-flash is no longer available to
#      new users. Please update your code to use models/gemini-3.6-flash"
#    이 파일(거시지표, 관리자 전용 + 개발 중단)은 아무도 최근에 안 밟아서 그동안
#    안 드러났을 뿐 같은 모델을 그대로 쓰고 있었습니다. `indicator_ai.py`와 같은 모델로
#    맞추고, 함수 안에 문자열로 박아 두지 않고(그래서 다음에 또 이렇게 놓치기 쉬웠던
#    것) 모듈 상수로 올립니다 — `indicator_ai.py::MODEL_NAME`과 같은 관례.
MODEL_NAME = 'gemini-3.6-flash'

# 🔗 한글 이름 매핑 — **단일 출처는 `utils/constants.py`** (2026-08-17 통합)
#
# 예전에는 이 파일이 자기만의 `FRIENDLY_NAMES` 사전을 들고 있었고, 그 값이 화면
# (`views/macro_view.py` / `web/pages/macro_page.py`)과 **실제로 어긋나 있었습니다.**
# 이 이름은 아래에서 Gemini 프롬프트의 "현재 설명할 지표" 자리에 그대로 들어가므로,
# AI 는 옛 이름("공포지수 비대칭도", "합성선물 가격 차이")을 보고 설명을 쓰는데 화면은
# 그 코멘트를 새 이름("VKOSPI 공포지수", "선물 베이시스") 옆에 붙여 보여줬습니다.
# 두 이름은 실제로 **가리키는 지표 자체가 다릅니다**(#70 프록시 → KRX 실측 전환).
# 사전을 하나로 합쳐 그 어긋남이 구조적으로 불가능하게 만들었습니다 (§0-3-10).
#
# ⚠️ 옛 사전에 남아 있던 은퇴 지표 8개는 함께 걷어냈습니다. 아래 루프는
#    `metrics_dict`(= 활성 지표만 담겨 옴)의 키로만 이 표를 조회하므로 은퇴 키가
#    쓰이는 경로가 애초에 없었습니다. 과거 코멘트를 **화면에 그릴 때** 필요한 이름은
#    화면 파일이 자기 사전으로 처리합니다(이 파일은 쓰기 전용 배치입니다).
from utils.constants import MACRO_FRIENDLY_NAMES as FRIENDLY_NAMES

def generate_macro_commentary(metrics_dict, score, kospi_close, usd_close):
    """
    현재 활성 매크로 지표(metrics_dict에 담겨 온 것들)에 대해 개별적으로 루프를 돌며
    초보자용 AI 코멘트를 생성합니다. (2026-08-10 #69 이후 8개)
    """
    print("🤖 AI 매크로 코멘트 생성을 시작합니다...")
    
    # ⚠️ 2026-08-17 (NiceGUI 이전 6단계) — streamlit 의존 제거.
    #    예전에는 여기서 `import streamlit as st; api_key = st.secrets.get("GEMINI_API_KEY")`
    #    로 Streamlit Cloud secrets 를 한 번 더 뒤졌습니다. 이 함수의 **유일한 호출자는
    #    `scrape_daily.py`(GitHub Actions 배치)** 이고 거기서는 항상 환경변수로 들어오므로
    #    실제 동작은 달라지지 않습니다. 이전 후 앱이 도는 Render 도 전부 환경변수입니다
    #    (NICEGUI_MIGRATION_PLAN.md §8-3). 키 이름·읽는 방식·이후 로직은 그대로입니다.
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("⚠️ GEMINI_API_KEY가 없습니다. AI 코멘트 생성을 건너뜁니다.")
        return
        
    # 2026-08-18 마이그레이션 참고 — 예전 SDK에서도 `GenerativeModel(name)` 생성 자체는
    # 모델 이름을 검증하지 않아(실패는 항상 실제 `generate_content()` 호출 시점에만 났음),
    # 위에 있던 try/except 폴백은 실제로는 한 번도 타지 않던 죽은 코드였습니다. 새 SDK는
    # 애초에 "모델 객체"를 미리 만들지 않고 호출마다 모델 이름을 문자열로 넘기므로 그 구조를
    # 그대로 옮기지 않습니다. 실제 실패는 아래 반복문의 지표별 try/except가 그대로 잡아 그
    # 지표만 실패 문구로 남기고 나머지는 계속 진행합니다(기존 동작과 동일 — §0-1).
    client = genai.Client(api_key=api_key)
    
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    commentary_file = os.path.join(data_dir, "macro_commentary.json")
    
    # 이전 데이터 로드 (실패 시 전일 데이터 유지를 위해)
    commentary_data = {}
    if os.path.exists(commentary_file):
        try:
            with open(commentary_file, "r", encoding="utf-8") as f:
                commentary_data = json.load(f)
        except Exception as e:
            print(f"⚠️ 기존 AI 코멘트 파일 로드 실패(신규 생성으로 진행): {e}")

    # 오늘 날짜
    today_str = time.strftime("%Y-%m-%d")
    # 2026-08-10 (#69): 예전에는 `len(comments) == 14`로 판단했는데, 지표 개수가 8개로 바뀌면서
    # 이 조건이 영원히 참/거짓 한쪽으로 굳을 수 있었습니다(과거 파일에는 옛 14개 키가 남아 있음).
    # 개수를 세는 대신 "오늘 요청할 지표가 전부 이미 있는가"로 판단합니다.
    _existing = commentary_data.get("comments", {})
    if commentary_data.get("date") == today_str and metrics_dict and all(k in _existing for k in metrics_dict):
        # 여기서 return 하지 않으면 매 실행마다 지표 수만큼 API를 다시 호출합니다(비용/쿼터 낭비).
        print("ℹ️ 이미 오늘의 AI 코멘트가 모두 생성되어 있습니다. 재호출을 건너뜁니다.")
        return

    new_comments = commentary_data.get("comments", {})
    # 코멘트별 생성 일자 — 실패 시 전일 코멘트가 '오늘 분석'으로 둔갑하지 않도록 개별 기록
    comment_dates = commentary_data.get("comment_dates", {})

    for key, risk_val in metrics_dict.items():
        name = FRIENDLY_NAMES.get(key, key)
        
        prompt = f"""
당신은 초보 주식 투자자에게 시장 상황을 아주 친절하고 알기 쉽게 설명해주는 친한 주식 선배입니다.
절대 딱딱한 금융공학 용어나 어려운 경제 용어를 쓰지 말고, 비유를 들어서라도 쉽게 풀어서 설명해주세요.

[현재 시장 상황]
- 코스피 지수: {kospi_close:.2f}
- 원/달러 환율: {usd_close:.2f}
- 현재 설명할 지표: {name}
- 이 지표의 현재 위험도 수치: {risk_val:.3f} (0에 가까울수록 안전, 1에 가까울수록 매우 위험)

위 데이터를 바탕으로, 이 지표가 현재 어떤 상태인지, 주식 시장에 어떤 의미가 있는지 2~3문장으로 짧게 요약해서 설명해주세요.
말투는 부드러운 평어체(~해요, ~입니다 등)를 사용하세요.
        """
        
        try:
            print(f"   💬 [{key}] 코멘트 요청 중...")
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
            if response and response.text:
                new_comments[key] = response.text.strip()
                comment_dates[key] = today_str      # 실제 생성 성공 시에만 오늘 날짜 기록
            else:
                raise ValueError("빈 응답")
            time.sleep(2)  # Rate limit 방어
        except Exception as e:
            print(f"   ⚠️ [{key}] AI 코멘트 생성 실패: {e}")
            if key not in new_comments:
                new_comments[key] = "⚠️ AI 코멘트 생성에 실패했습니다 (표시할 분석 없음)."
                comment_dates[key] = None
            # 기존 코멘트가 있으면 유지하되, comment_dates 는 갱신하지 않습니다.
            # → 대시보드가 "(YYYY-MM-DD 생성 코멘트)" 라고 명시적으로 표기합니다.
            time.sleep(5)

    commentary_data["date"] = today_str
    commentary_data["score"] = score
    commentary_data["comments"] = new_comments
    commentary_data["comment_dates"] = comment_dates

    with open(commentary_file, "w", encoding="utf-8") as f:
        json.dump(commentary_data, f, ensure_ascii=False, indent=4)
        
    print("✅ AI 매크로 코멘트 갱신 완료!")
