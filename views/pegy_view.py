import os
import random
import pandas as pd
import streamlit as st

@st.cache_data
def get_kospi200_pegy_data():
    """KOSPI 200 대표 종목 밸류에이션(Trailing vs Forward PEGY) 200개 데이터셋 생성"""
    # KOSPI 주요 30개 시총 상위 실제 종목 템플릿
    base_stocks = [
        {"name": "삼성전자", "code": "005930", "price": 74500, "t_per": 14.8, "t_eps": 5033, "sh_return": 2.4, "t_pegy": 0.85, "t_fair": 82000, "f_per": 12.84, "f_eps": 5800, "growth": 18.5, "f_pegy": 0.63, "f_target": 98000, "vol": "🟢 정상"},
        {"name": "SK하이닉스", "code": "000660", "price": 182000, "t_per": 12.5, "t_eps": 14560, "sh_return": 1.2, "t_pegy": 0.52, "t_fair": 210000, "f_per": 9.33, "f_eps": 19500, "growth": 24.1, "f_pegy": 0.37, "f_target": 260000, "vol": "🟢 정상"},
        {"name": "현대차", "code": "005380", "price": 245000, "t_per": 8.2, "t_eps": 29878, "sh_return": 5.2, "t_pegy": 0.71, "t_fair": 280000, "f_per": 7.66, "f_eps": 32000, "growth": 8.2, "f_pegy": 0.62, "f_target": 310000, "vol": "🟢 정상"},
        {"name": "NAVER", "code": "035420", "price": 178000, "t_per": 22.5, "t_eps": 7911, "sh_return": 1.5, "t_pegy": 1.82, "t_fair": 165000, "f_per": 20.00, "f_eps": 8900, "growth": 12.0, "f_pegy": 1.58, "f_target": 190000, "vol": "⚡ 변동성 보정 중"},
        {"name": "카카오", "code": "035720", "price": 42000, "t_per": 31.2, "t_eps": 1346, "sh_return": 0.8, "t_pegy": 3.85, "t_fair": 35000, "f_per": 26.25, "f_eps": 1600, "growth": 7.5, "f_pegy": 3.43, "f_target": 40000, "vol": "⚡ 변동성 보정 중"},
        {"name": "기아", "code": "000270", "price": 118000, "t_per": 6.8, "t_eps": 17350, "sh_return": 6.1, "t_pegy": 0.55, "t_fair": 145000, "f_per": 6.10, "f_eps": 19340, "growth": 11.4, "f_pegy": 0.48, "f_target": 160000, "vol": "🟢 정상"},
        {"name": "LG에너지솔루션", "code": "373220", "price": 348000, "t_per": 62.0, "t_eps": 5612, "sh_return": 0.3, "t_pegy": 2.85, "t_fair": 290000, "f_per": 48.50, "f_eps": 7175, "growth": 27.8, "f_pegy": 1.72, "f_target": 380000, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성바이오로직스", "code": "207940", "price": 815000, "t_per": 58.4, "t_eps": 13955, "sh_return": 0.0, "t_pegy": 2.41, "t_fair": 750000, "f_per": 46.20, "f_eps": 17640, "growth": 26.4, "f_pegy": 1.75, "f_target": 920000, "vol": "🟢 정상"},
        {"name": "KB금융", "code": "105560", "price": 82500, "t_per": 6.9, "t_eps": 11956, "sh_return": 7.4, "t_pegy": 0.58, "t_fair": 105000, "f_per": 6.20, "f_eps": 13306, "growth": 9.2, "f_pegy": 0.49, "f_target": 115000, "vol": "🟢 정상"},
        {"name": "신한지주", "code": "055550", "price": 53200, "t_per": 6.4, "t_eps": 8312, "sh_return": 6.8, "t_pegy": 0.54, "t_fair": 68000, "f_per": 5.80, "f_eps": 9172, "growth": 8.5, "f_pegy": 0.46, "f_target": 72000, "vol": "🟢 정상"},
        {"name": "POSCO홀딩스", "code": "005490", "price": 362000, "t_per": 18.2, "t_eps": 19890, "sh_return": 3.8, "t_pegy": 1.45, "t_fair": 330000, "f_per": 14.50, "f_eps": 24965, "growth": 14.2, "f_pegy": 1.02, "f_target": 410000, "vol": "⚡ 변동성 보정 중"},
        {"name": "셀트리온", "code": "068270", "price": 189000, "t_per": 42.0, "t_eps": 4500, "sh_return": 0.9, "t_pegy": 1.95, "t_fair": 170000, "f_per": 31.50, "f_eps": 6000, "growth": 33.3, "f_pegy": 0.94, "f_target": 230000, "vol": "🟢 정상"},
        {"name": "현대모비스", "code": "012330", "price": 224000, "t_per": 7.1, "t_eps": 31549, "sh_return": 3.5, "t_pegy": 0.68, "t_fair": 270000, "f_per": 6.40, "f_eps": 35000, "growth": 9.5, "f_pegy": 0.59, "f_target": 290000, "vol": "🟢 정상"},
        {"name": "삼성물산", "code": "028260", "price": 146000, "t_per": 11.2, "t_eps": 13035, "sh_return": 2.9, "t_pegy": 0.92, "t_fair": 160000, "f_per": 9.80, "f_eps": 14897, "growth": 10.2, "f_pegy": 0.75, "f_target": 185000, "vol": "🟢 정상"},
        {"name": "LG화학", "code": "051910", "price": 312000, "t_per": 25.4, "t_eps": 12283, "sh_return": 2.1, "t_pegy": 1.85, "t_fair": 280000, "f_per": 19.50, "f_eps": 16000, "growth": 21.0, "f_pegy": 1.15, "f_target": 360000, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성SDI", "code": "006400", "price": 335000, "t_per": 21.8, "t_eps": 15366, "sh_return": 1.1, "t_pegy": 1.62, "t_fair": 310000, "f_per": 16.20, "f_eps": 20679, "growth": 22.5, "f_pegy": 0.98, "f_target": 420000, "vol": "⚡ 변동성 보정 중"},
        {"name": "HD현대중공업", "code": "329180", "price": 195000, "t_per": 35.0, "t_eps": 5571, "sh_return": 0.5, "t_pegy": 1.25, "t_fair": 180000, "f_per": 21.40, "f_eps": 9112, "growth": 63.5, "f_pegy": 0.33, "f_target": 270000, "vol": "🟢 정상"},
        {"name": "메리츠금융지주", "code": "138040", "price": 89000, "t_per": 8.1, "t_eps": 10987, "sh_return": 9.8, "t_pegy": 0.42, "t_fair": 115000, "f_per": 7.10, "f_eps": 12535, "growth": 14.1, "f_pegy": 0.35, "f_target": 130000, "vol": "🟢 정상"},
        {"name": "한국전력", "code": "015760", "price": 21500, "t_per": 5.4, "t_eps": 3981, "sh_return": 0.0, "t_pegy": 0.65, "t_fair": 28000, "f_per": 4.50, "f_eps": 4777, "growth": 20.0, "f_pegy": 0.45, "f_target": 32000, "vol": "⚡ 변동성 보정 중"},
        {"name": "크래프톤", "code": "259960", "price": 315000, "t_per": 20.5, "t_eps": 15365, "sh_return": 1.8, "t_pegy": 1.12, "t_fair": 300000, "f_per": 15.80, "f_eps": 19936, "growth": 29.7, "f_pegy": 0.68, "f_target": 410000, "vol": "🟢 정상"},
        {"name": "한화에어로스페이스", "code": "012450", "price": 295000, "t_per": 24.2, "t_eps": 12190, "sh_return": 0.8, "t_pegy": 0.88, "t_fair": 280000, "f_per": 16.50, "f_eps": 17878, "growth": 46.6, "f_pegy": 0.42, "f_target": 380000, "vol": "🟢 정상"},
        {"name": "SK텔레콤", "code": "017670", "price": 54200, "t_per": 10.2, "t_eps": 5313, "sh_return": 7.1, "t_pegy": 0.85, "t_fair": 60000, "f_per": 9.40, "f_eps": 5765, "growth": 8.5, "f_pegy": 0.60, "f_target": 67000, "vol": "🟢 정상"},
        {"name": "KT", "code": "030200", "price": 39500, "t_per": 8.8, "t_eps": 4488, "sh_return": 6.8, "t_pegy": 0.78, "t_fair": 45000, "f_per": 7.90, "f_eps": 5000, "growth": 11.4, "f_pegy": 0.52, "f_target": 51000, "vol": "🟢 정상"},
        {"name": "S-Oil", "code": "010950", "price": 68500, "t_per": 11.5, "t_eps": 5956, "sh_return": 4.5, "t_pegy": 1.25, "t_fair": 65000, "f_per": 8.90, "f_eps": 7696, "growth": 29.2, "f_pegy": 0.72, "f_target": 88000, "vol": "⚡ 변동성 보정 중"},
        {"name": "HMM", "code": "011200", "price": 18200, "t_per": 6.2, "t_eps": 2935, "sh_return": 3.8, "t_pegy": 0.75, "t_fair": 21000, "f_per": 5.10, "f_eps": 3568, "growth": 21.5, "f_pegy": 0.41, "f_target": 25000, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성엔지니어링", "code": "028050", "price": 24800, "t_per": 7.8, "t_eps": 3179, "sh_return": 0.0, "t_pegy": 0.68, "t_fair": 29000, "f_per": 6.70, "f_eps": 3701, "growth": 16.4, "f_pegy": 0.51, "f_target": 35000, "vol": "🟢 정상"},
        {"name": "두산에너빌리티", "code": "034020", "price": 20800, "t_per": 48.0, "t_eps": 433, "sh_return": 0.0, "t_pegy": 2.15, "t_fair": 18000, "f_per": 32.50, "f_eps": 640, "growth": 47.8, "f_pegy": 0.98, "f_target": 27000, "vol": "⚡ 변동성 보정 중"},
        {"name": "현대글로비스", "code": "086280", "price": 121500, "t_per": 7.4, "t_eps": 16418, "sh_return": 3.8, "t_pegy": 0.69, "t_fair": 145000, "f_per": 6.50, "f_eps": 18692, "growth": 13.8, "f_pegy": 0.48, "f_target": 165000, "vol": "🟢 정상"},
        {"name": "KT&G", "code": "033780", "price": 104500, "t_per": 12.8, "t_eps": 8164, "sh_return": 7.8, "t_pegy": 0.88, "t_fair": 115000, "f_per": 11.20, "f_eps": 9330, "growth": 14.2, "f_pegy": 0.62, "f_target": 130000, "vol": "🟢 정상"},
        {"name": "한국타이어앤테크놀로지", "code": "161390", "price": 49800, "t_per": 6.8, "t_eps": 7323, "sh_return": 3.2, "t_pegy": 0.64, "t_fair": 60000, "f_per": 5.90, "f_eps": 8440, "growth": 15.2, "f_pegy": 0.45, "f_target": 70000, "vol": "🟢 정상"}
    ]

    # 200개 종목으로 데이터 확장 생성 (결정론적 시드 기반)
    rng = random.Random(42)
    stocks = []
    
    # 템플릿 종목 먼저 삽입
    for s in base_stocks:
        stocks.append(s)
        
    # 나머지 170개 종목 알고리즘 생성
    sec_names = ["제약", "바이오", "화학", "철강", "건설", "증권", "보험", "중공업", "기계", "유통", "음식료", "IT부품", "디스플레이", "소프트웨어", "게임", "미디어"]
    for idx in range(len(base_stocks) + 1, 201):
        code_str = f"{idx:06d}"
        sec = rng.choice(sec_names)
        name_str = f"KOSPI {sec} {idx-30}호"
        price_val = rng.randint(15, 450) * 1000
        
        t_per_val = round(rng.uniform(5.0, 35.0), 2)
        t_eps_val = int(price_val / t_per_val)
        sh_ret_val = round(rng.uniform(0.0, 8.5), 1)
        t_pegy_val = round(rng.uniform(0.35, 2.5), 2)
        t_fair_val = int(price_val * rng.uniform(0.85, 1.35))
        
        f_per_val = round(t_per_val * rng.uniform(0.75, 1.05), 2)
        f_eps_val = int(t_eps_val * rng.uniform(1.05, 1.45))
        growth_val = round(rng.uniform(6.0, 45.0), 1)
        f_pegy_val = round(f_per_val / (growth_val + sh_ret_val), 2)
        f_target_val = int(price_val * rng.uniform(1.1, 1.6))
        vol_val = "🟢 정상" if rng.random() > 0.3 else "⚡ 변동성 보정 중"
        
        stocks.append({
            "name": name_str, "code": code_str, "price": price_val,
            "t_per": t_per_val, "t_eps": t_eps_val, "sh_return": sh_ret_val,
            "t_pegy": t_pegy_val, "t_fair": t_fair_val,
            "f_per": f_per_val, "f_eps": f_eps_val, "growth": growth_val,
            "f_pegy": f_pegy_val, "f_target": f_target_val, "vol": vol_val
        })

    # Forward PEGY 기반 밸류에이션 평가 배지 부여
    for s in stocks:
        fp = s["f_pegy"]
        if fp < 0.65:
            s["badge"] = "🟢 강력 저평가"
            s["badge_bg"] = "#14532d"
            s["badge_fg"] = "#4ade80"
        elif fp < 0.95:
            s["badge"] = "🟢 저평가"
            s["badge_bg"] = "#166534"
            s["badge_fg"] = "#86efac"
        elif fp < 1.35:
            s["badge"] = "🟡 적정가 형성"
            s["badge_bg"] = "#78350f"
            s["badge_fg"] = "#fde047"
        else:
            s["badge"] = "🔴 고평가 관망"
            s["badge_bg"] = "#7f1d1d"
            s["badge_fg"] = "#fca5a5"

    return stocks

def render_pegy_page():
    """'💡 사실 이 가격이에요' (Forward PEGY/PER/EPS 밸류에이션 분석) 카드 그리드 화면 렌더링"""
    
    # 1. 상단 그라데이션 타이틀
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #d97706; margin: 0 0 8px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">KOSPI 200개 종목 Trailing vs Forward PEGY 퀀트 적정가치 비교 리포트</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 2. 요약 지표 카드 3종
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 평균 Forward PER", "10.4 배", "-0.8배 (전월 대비)")
    with col2:
        st.metric("코스피 대표 EPS 성장률 (PEG)", "14.2 %", "+1.5%p")
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", "0.73", "저평가 수용 구간")

    st.markdown("---")

    # 3. KOSPI 200 종목 데이터 로드
    all_stocks = get_kospi200_pegy_data()

    # 4. 상단 검색 및 밸류에이션 필터 컨트롤
    f_col1, f_col2 = st.columns([2, 3])
    with f_col1:
        search_query = st.text_input("🔍 종목명 / 종목코드 검색", placeholder="예: 삼성전자, 005930").strip()
    with f_col2:
        selected_badges = st.multiselect(
            "🏷️ 밸류에이션 상태 필터",
            ["🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성", "🔴 고평가 관망"],
            default=["🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성", "🔴 고평가 관망"]
        )

    # 필터링 적용
    filtered_stocks = all_stocks
    if search_query:
        filtered_stocks = [
            s for s in filtered_stocks 
            if search_query.lower() in s["name"].lower() or search_query in s["code"]
        ]
    if selected_badges:
        filtered_stocks = [
            s for s in filtered_stocks 
            if s["badge"] in selected_badges
        ]

    st.markdown(f"**전체 검색/필터 결과:** `{len(filtered_stocks)}`개 종목 (총 {len(all_stocks)}개 KOSPI 종목 중)")

    # 5. 페이지네이션 (Pagination)
    items_per_page = 20
    total_items = len(filtered_stocks)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

    st.markdown("##### 📄 페이지 선택 (한 화면에 20개 종목 카드 노출)")
    
    # pills 또는 selectbox 선택
    page_options = [f"페이지 {i} (종목 {(i-1)*20+1} ~ {min(i*20, total_items)})" for i in range(1, total_pages + 1)]
    
    if hasattr(st, "pills"):
        selected_page_str = st.pills("페이지 번호", page_options, selection_mode="single", default=page_options[0])
        if not selected_page_str:
            selected_page_str = page_options[0]
        current_page = page_options.index(selected_page_str) + 1
    else:
        selected_page_str = st.selectbox("페이지 번호", page_options, index=0)
        current_page = page_options.index(selected_page_str) + 1

    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_stocks = filtered_stocks[start_idx:end_idx]

    st.markdown("---")

    # 6. 카드 그리드 (Card Grid) 구현 - 1줄에 4개씩 5줄 (총 20개)
    if not page_stocks:
        st.warning("선택한 필터 조건에 일치하는 종목이 없습니다.")
        return

    grid_cols = st.columns(4)

    for idx, s in enumerate(page_stocks):
        col = grid_cols[idx % 4]
        vol_color = "#f43f5e" if "보정 중" in s["vol"] else "#38bdf8"
        
        card_html = f"""
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.35); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <!-- 1. 헤더: 종목명 / 코드 / 배지 -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; border-bottom: 1px solid #334155; padding-bottom: 8px;">
                <div>
                    <div style="font-size: 16px; font-weight: 800; color: #f8fafc; line-height: 1.2;">{s['name']}</div>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">{s['code']}</div>
                </div>
                <span style="background-color: {s['badge_bg']}; color: {s['badge_fg']}; font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 12px; border: 1px solid {s['badge_fg']};">
                    {s['badge']}
                </span>
            </div>

            <!-- 현재가 및 3개월 변동성 필터 상태 -->
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px;">
                <div>
                    <span style="font-size: 11px; color: #94a3b8;">현재가:</span>
                    <span style="font-size: 18px; font-weight: 900; color: #38bdf8; margin-left: 4px;">{s['price']:,.0f}원</span>
                </div>
                <span style="font-size: 10.5px; color: {vol_color}; font-weight: 600;">{s['vol']}</span>
            </div>

            <!-- 2. Trailing 섹션 (과거/현재 실적) -->
            <div style="background-color: rgba(30, 41, 59, 0.6); border: 1px solid #334155; border-radius: 8px; padding: 10px; margin-bottom: 10px;">
                <div style="font-size: 11.5px; font-weight: 700; color: #cbd5e1; margin-bottom: 6px; border-bottom: 1px dashed #475569; padding-bottom: 3px;">
                    📜 Trailing (과거 실적)
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8; margin-bottom: 3px;">
                    <span>PER / EPS:</span>
                    <span style="color: #f1f5f9; font-weight: 600;">{s['t_per']}배 / {s['t_eps']:,.0f}원</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8; margin-bottom: 3px;">
                    <span>주주환원율:</span>
                    <span style="color: #f1f5f9; font-weight: 600;">{s['sh_return']}%</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8;">
                    <span>PEGY / 적정가:</span>
                    <span style="color: #38bdf8; font-weight: 700;">{s['t_pegy']} / {s['t_fair']:,.0f}원</span>
                </div>
            </div>

            <!-- 3. Forward 섹션 (미래 추정 밸류) -->
            <div style="background-color: rgba(15, 23, 42, 0.85); border: 1.5px solid #0284c7; border-radius: 8px; padding: 10px;">
                <div style="font-size: 11.5px; font-weight: 700; color: #38bdf8; margin-bottom: 6px; border-bottom: 1px solid #0284c7; padding-bottom: 3px;">
                    🚀 Forward (미래 추정)
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8; margin-bottom: 3px;">
                    <span>PER / EPS:</span>
                    <span style="color: #f1f5f9; font-weight: 600;">{s['f_per']}배 / {s['f_eps']:,.0f}원</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8; margin-bottom: 3px;">
                    <span>예상 성장률:</span>
                    <span style="color: #4ade80; font-weight: 700;">+{s['growth']}%</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: #94a3b8;">
                    <span>보정 PEGY / 목표가:</span>
                    <span style="color: #f43f5e; font-weight: 800;">{s['f_pegy']} / {s['f_target']:,.0f}원</span>
                </div>
            </div>
        </div>
        """
        with col:
            clean_card = "\n".join([line.strip() for line in card_html.split("\n") if line.strip()])
            st.markdown(clean_card, unsafe_allow_html=True)
