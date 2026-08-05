import os
import json
import time
import google.generativeai as genai

# 한글 이름 매핑 (scrape_daily.py와 맞춤)
FRIENDLY_NAMES = {
    "FX_Swap_Point": "외환 스왑포인트 (달러 유동성 부족 위험)",
    "Put_OTM_OI": "풋옵션 미결제약정 (시장 하락에 베팅한 대기자금)",
    "Short_Ratio": "공매도 거래 비중 (주가를 떨어뜨리려는 매도세)",
    "ELS_KnockIn": "ELS 낙인 위험 (대규모 원금손실 구간 진입 여부)",
    "VKOSPI_Skew": "공포지수 비대칭도 (투자자들의 불안 심리 강도)",
    "Synthetic_Futures": "합성선물 가격 차이 (외국인의 파생상품 하방 압력)",
    "NDF_Night_Rate": "야간 역외환율 변동 (원/달러 환율 급등 위험)",
    "Futures_Net_Sell": "선물 순매도 규모 (선물 지수 하락 압박 세기)",
    "Non_Arbitrage_Ratio": "비차익 프로그램 매도 비중 (컴퓨터 자동 매도량)",
    "Foreign_Broker_Dump": "외국계 증권사 매도세 (외국인 투자자 이탈 속도)",
    "Stock_Short_Balance": "주식 공매도 잔고 (공매도 세력이 아직 갚지 않은 주식수)",
    "Put_Buy_Simple": "풋옵션 매수 강도 (단기 주가 하락 대비 베팅 규모)",
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)",
    "KOSPI_5D_Return": "KOSPI 5일 낙폭 모멘텀 (지수 폭락 감지용 직접 지표)"
}

def generate_macro_commentary(metrics_dict, score, kospi_close, usd_close):
    """
    14개 매크로 지표에 대해 개별적으로 루프를 돌며 초보자용 AI 코멘트를 생성합니다.
    """
    print("🤖 AI 매크로 코멘트 생성을 시작합니다...")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    # Streamlit Cloud 환경에서 secrets.toml을 로컬 변수처럼 사용하는 경우를 대비한 꼼수
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            pass
            
    if not api_key:
        print("⚠️ GEMINI_API_KEY가 없습니다. AI 코멘트 생성을 건너뜁니다.")
        return
        
    genai.configure(api_key=api_key)
    
    # gemini-2.5-flash 모델 등 저비용 고효율 모델 사용
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
    except Exception:
        model = genai.GenerativeModel('gemini-1.5-flash')
    
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    commentary_file = os.path.join(data_dir, "macro_commentary.json")
    
    # 이전 데이터 로드 (실패 시 전일 데이터 유지를 위해)
    commentary_data = {}
    if os.path.exists(commentary_file):
        try:
            with open(commentary_file, "r", encoding="utf-8") as f:
                commentary_data = json.load(f)
        except Exception:
            pass

    # 오늘 날짜
    today_str = time.strftime("%Y-%m-%d")
    if commentary_data.get("date") == today_str and len(commentary_data.get("comments", {})) == 14:
        print("ℹ️ 이미 오늘의 AI 코멘트가 모두 생성되어 있습니다.")
    
    new_comments = commentary_data.get("comments", {})
    
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
            response = model.generate_content(prompt)
            if response and response.text:
                new_comments[key] = response.text.strip()
            else:
                raise ValueError("빈 응답")
            time.sleep(2)  # Rate limit 방어
        except Exception as e:
            print(f"   ⚠️ [{key}] AI 코멘트 생성 실패: {e}")
            if key not in new_comments:
                new_comments[key] = "현재 코멘트 업데이트 중입니다. 잠시 후 다시 확인해주세요."
            time.sleep(5) 

    commentary_data["date"] = today_str
    commentary_data["score"] = score
    commentary_data["comments"] = new_comments
    
    with open(commentary_file, "w", encoding="utf-8") as f:
        json.dump(commentary_data, f, ensure_ascii=False, indent=4)
        
    print("✅ AI 매크로 코멘트 갱신 완료!")
