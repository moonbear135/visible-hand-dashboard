import os
import random
import pandas as pd
import streamlit as st

@st.cache_data
def get_kospi200_pegy_data():
    """
    KOSPI 200 대표 종목 밸류에이션(Trailing/Forward PEGY, ROE/ROIC, DPS & 주주환원 총액) 200개 데이터셋 생성.
    젬민이 제안 퀀트 튜닝 공식 적용:
    1. Growth Cap (35.0% 상한) & 변동성 벌점계수 (1.18x) 적용 Forward PEGY
    2. ROE (+15% / -10%) & ROIC (+10% / -5%) 프리미엄/디스카운트 적용 Target PER & 목표가(f_target)
    3. 100점 만점 퀀트 종합 스코어(quant_score)
    """
    base_stocks = [
        {"name": "삼성전자", "code": "005930", "price": 74500, "t_roe": 10.5, "f_roe": 12.8, "roic": 11.2, "dps": 3617, "return_total": "총 9.8조원", "t_per": 14.8, "t_eps": 5033, "sh_return": 2.4, "t_pegy": 0.85, "t_fair": 82000, "f_per": 12.84, "f_eps": 5800, "growth": 18.5, "vol": "🟢 정상"},
        {"name": "SK하이닉스", "code": "000660", "price": 182000, "t_roe": 22.5, "f_roe": 26.8, "roic": 21.0, "dps": 1500, "return_total": "총 1.8조원", "t_per": 12.5, "t_eps": 14560, "sh_return": 1.2, "t_pegy": 0.52, "t_fair": 210000, "f_per": 9.33, "f_eps": 19500, "growth": 24.1, "vol": "🟢 정상"},
        {"name": "현대차", "code": "005380", "price": 245000, "t_roe": 12.4, "f_roe": 13.5, "roic": 11.8, "dps": 11400, "return_total": "총 3.2조원", "t_per": 8.2, "t_eps": 29878, "sh_return": 5.2, "t_pegy": 0.71, "t_fair": 280000, "f_per": 7.66, "f_eps": 32000, "growth": 8.2, "vol": "🟢 정상"},
        {"name": "NAVER", "code": "035420", "price": 178000, "t_roe": 9.8, "f_roe": 11.2, "roic": 8.5, "dps": 1190, "return_total": "총 4,800억원", "t_per": 22.5, "t_eps": 7911, "sh_return": 1.5, "t_pegy": 1.82, "t_fair": 165000, "f_per": 20.00, "f_eps": 8900, "growth": 12.0, "vol": "⚡ 변동성 보정 중"},
        {"name": "카카오", "code": "035720", "price": 42000, "t_roe": 3.2, "f_roe": 4.5, "roic": 3.8, "dps": 340, "return_total": "총 1,200억원", "t_per": 31.2, "t_eps": 1346, "sh_return": 0.8, "t_pegy": 3.85, "t_fair": 35000, "f_per": 26.25, "f_eps": 1600, "growth": 7.5, "vol": "⚡ 변동성 보정 중"},
        {"name": "기아", "code": "000270", "price": 118000, "t_roe": 18.2, "f_roe": 19.5, "roic": 16.8, "dps": 5600, "return_total": "총 2.1조원", "t_per": 6.8, "t_eps": 17350, "sh_return": 6.1, "t_pegy": 0.55, "t_fair": 145000, "f_per": 6.10, "f_eps": 19340, "growth": 11.4, "vol": "🟢 정상"},
        {"name": "LG에너지솔루션", "code": "373220", "price": 348000, "t_roe": 5.8, "f_roe": 7.2, "roic": 5.1, "dps": 1000, "return_total": "총 2,500억원", "t_per": 62.0, "t_eps": 5612, "sh_return": 0.3, "t_pegy": 2.85, "t_fair": 290000, "f_per": 48.50, "f_eps": 7175, "growth": 27.8, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성바이오로직스", "code": "207940", "price": 815000, "t_roe": 9.4, "f_roe": 11.8, "roic": 8.9, "dps": 0, "return_total": "0원 (재투자)", "t_per": 58.4, "t_eps": 13955, "sh_return": 0.0, "t_pegy": 2.41, "t_fair": 750000, "f_per": 46.20, "f_eps": 17640, "growth": 26.4, "vol": "🟢 정상"},
        {"name": "KB금융", "code": "105560", "price": 82500, "t_roe": 9.8, "f_roe": 10.5, "roic": 7.8, "dps": 3060, "return_total": "총 2.4조원", "t_per": 6.9, "t_eps": 11956, "sh_return": 7.4, "t_pegy": 0.58, "t_fair": 105000, "f_per": 6.20, "f_eps": 13306, "growth": 9.2, "vol": "🟢 정상"},
        {"name": "신한지주", "code": "055550", "price": 53200, "t_roe": 9.2, "f_roe": 9.9, "roic": 7.2, "dps": 2100, "return_total": "총 1.9조원", "t_per": 6.4, "t_eps": 8312, "sh_return": 6.8, "t_pegy": 0.54, "t_fair": 68000, "f_per": 5.80, "f_eps": 9172, "growth": 8.5, "vol": "🟢 정상"},
        {"name": "POSCO홀딩스", "code": "005490", "price": 362000, "t_roe": 4.8, "f_roe": 6.2, "roic": 4.1, "dps": 10000, "return_total": "총 9,500억원", "t_per": 18.2, "t_eps": 19890, "sh_return": 3.8, "t_pegy": 1.45, "t_fair": 330000, "f_per": 14.50, "f_eps": 24965, "growth": 14.2, "vol": "⚡ 변동성 보정 중"},
        {"name": "셀트리온", "code": "068270", "price": 189000, "t_roe": 8.8, "f_roe": 11.5, "roic": 8.1, "dps": 500, "return_total": "총 1,800억원", "t_per": 42.0, "t_eps": 4500, "sh_return": 0.9, "t_pegy": 1.95, "t_fair": 170000, "f_per": 31.50, "f_eps": 6000, "growth": 33.3, "vol": "🟢 정상"},
        {"name": "현대모비스", "code": "012330", "price": 224000, "t_roe": 8.5, "f_roe": 9.2, "roic": 7.9, "dps": 4500, "return_total": "총 8,200억원", "t_per": 7.1, "t_eps": 31549, "sh_return": 3.5, "t_pegy": 0.68, "t_fair": 270000, "f_per": 6.40, "f_eps": 35000, "growth": 9.5, "vol": "🟢 정상"},
        {"name": "삼성물산", "code": "028260", "price": 146000, "t_roe": 8.1, "f_roe": 8.9, "roic": 7.4, "dps": 2550, "return_total": "총 6,500억원", "t_per": 11.2, "t_eps": 13035, "sh_return": 2.9, "t_pegy": 0.92, "t_fair": 160000, "f_per": 9.80, "f_eps": 14897, "growth": 10.2, "vol": "🟢 정상"},
        {"name": "LG화학", "code": "051910", "price": 312000, "t_roe": 4.2, "f_roe": 5.8, "roic": 3.9, "dps": 3500, "return_total": "총 4,200억원", "t_per": 25.4, "t_eps": 12283, "sh_return": 2.1, "t_pegy": 1.85, "t_fair": 280000, "f_per": 19.50, "f_eps": 16000, "growth": 21.0, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성SDI", "code": "006400", "price": 335000, "t_roe": 7.8, "f_roe": 9.5, "roic": 7.1, "dps": 1000, "return_total": "총 2,100억원", "t_per": 21.8, "t_eps": 15366, "sh_return": 1.1, "t_pegy": 1.62, "t_fair": 310000, "f_per": 16.20, "f_eps": 20679, "growth": 22.5, "vol": "⚡ 변동성 보정 중"},
        {"name": "HD현대중공업", "code": "329180", "price": 195000, "t_roe": 14.5, "f_roe": 18.2, "roic": 13.8, "dps": 0, "return_total": "0원 (설비투자)", "t_per": 35.0, "t_eps": 5571, "sh_return": 0.5, "t_pegy": 1.25, "t_fair": 180000, "f_per": 21.40, "f_eps": 9112, "growth": 63.5, "vol": "🟢 정상"},
        {"name": "메리츠금융지주", "code": "138040", "price": 89000, "t_roe": 28.5, "f_roe": 31.0, "roic": 24.5, "dps": 2360, "return_total": "총 1.7조원", "t_per": 8.1, "t_eps": 10987, "sh_return": 9.8, "t_pegy": 0.42, "t_fair": 115000, "f_per": 7.10, "f_eps": 12535, "growth": 14.1, "vol": "🟢 정상"},
        {"name": "한국전력", "code": "015760", "price": 21500, "t_roe": 4.2, "f_roe": 5.5, "roic": 2.8, "dps": 0, "return_total": "0원", "t_per": 5.4, "t_eps": 3981, "sh_return": 0.0, "t_pegy": 0.65, "t_fair": 28000, "f_per": 4.50, "f_eps": 4777, "growth": 20.0, "vol": "⚡ 변동성 보정 중"},
        {"name": "크래프톤", "code": "259960", "price": 315000, "t_roe": 16.8, "f_roe": 19.4, "roic": 15.2, "dps": 0, "return_total": "총 1,600억원 (자사주 소각)", "t_per": 20.5, "t_eps": 15365, "sh_return": 1.8, "t_pegy": 1.12, "t_fair": 300000, "f_per": 15.80, "f_eps": 19936, "growth": 29.7, "vol": "🟢 정상"},
        {"name": "한화에어로스페이스", "code": "012450", "price": 295000, "t_roe": 15.2, "f_roe": 18.9, "roic": 14.1, "dps": 1000, "return_total": "총 950억원", "t_per": 24.2, "t_eps": 12190, "sh_return": 0.8, "t_pegy": 0.88, "t_fair": 280000, "f_per": 16.50, "f_eps": 17878, "growth": 46.6, "vol": "🟢 정상"},
        {"name": "SK텔레콤", "code": "017670", "price": 54200, "t_roe": 9.5, "f_roe": 10.2, "roic": 8.1, "dps": 3540, "return_total": "총 7,800억원", "t_per": 10.2, "t_eps": 5313, "sh_return": 7.1, "t_pegy": 0.85, "t_fair": 60000, "f_per": 9.40, "f_eps": 5765, "growth": 8.5, "vol": "🟢 정상"},
        {"name": "KT", "code": "030200", "price": 39500, "t_roe": 8.9, "f_roe": 9.8, "roic": 7.5, "dps": 1960, "return_total": "총 5,100억원", "t_per": 8.8, "t_eps": 4488, "sh_return": 6.8, "t_pegy": 0.78, "t_fair": 45000, "f_per": 7.90, "f_eps": 5000, "growth": 11.4, "vol": "🟢 정상"},
        {"name": "S-Oil", "code": "010950", "price": 68500, "t_roe": 7.2, "f_roe": 9.8, "roic": 6.5, "dps": 2900, "return_total": "총 3,400억원", "t_per": 11.5, "t_eps": 5956, "sh_return": 4.5, "t_pegy": 1.25, "t_fair": 65000, "f_per": 8.90, "f_eps": 7696, "growth": 29.2, "vol": "⚡ 변동성 보정 중"},
        {"name": "HMM", "code": "011200", "price": 18200, "t_roe": 6.5, "f_roe": 7.8, "roic": 5.2, "dps": 700, "return_total": "총 4,800억원", "t_per": 6.2, "t_eps": 2935, "sh_return": 3.8, "t_pegy": 0.75, "t_fair": 21000, "f_per": 5.10, "f_eps": 3568, "growth": 21.5, "vol": "⚡ 변동성 보정 중"},
        {"name": "삼성엔지니어링", "code": "028050", "price": 24800, "t_roe": 14.8, "f_roe": 16.5, "roic": 13.2, "dps": 0, "return_total": "0원", "t_per": 7.8, "t_eps": 3179, "sh_return": 0.0, "t_pegy": 0.68, "t_fair": 29000, "f_per": 6.70, "f_eps": 3701, "growth": 16.4, "vol": "🟢 정상"},
        {"name": "두산에너빌리티", "code": "034020", "price": 20800, "t_roe": 3.8, "f_roe": 5.2, "roic": 3.1, "dps": 0, "return_total": "0원", "t_per": 48.0, "t_eps": 433, "sh_return": 0.0, "t_pegy": 2.15, "t_fair": 18000, "f_per": 32.50, "f_eps": 640, "growth": 47.8, "vol": "⚡ 변동성 보정 중"},
        {"name": "현대글로비스", "code": "086280", "price": 121500, "t_roe": 13.2, "f_roe": 14.8, "roic": 11.5, "dps": 3800, "return_total": "총 2,800억원", "t_per": 7.4, "t_eps": 16418, "sh_return": 3.8, "t_pegy": 0.69, "t_fair": 145000, "f_per": 6.50, "f_eps": 18692, "growth": 13.8, "vol": "🟢 정상"},
        {"name": "KT&G", "code": "033780", "price": 104500, "t_roe": 11.8, "f_roe": 12.5, "roic": 10.2, "dps": 5200, "return_total": "총 8,900억원", "t_per": 12.8, "t_eps": 8164, "sh_return": 7.8, "t_pegy": 0.88, "t_fair": 115000, "f_per": 11.20, "f_eps": 9330, "growth": 14.2, "vol": "🟢 정상"},
        {"name": "한국타이어앤테크놀로지", "code": "161390", "price": 49800, "t_roe": 11.2, "f_roe": 12.4, "roic": 9.8, "dps": 1200, "return_total": "총 1,600억원", "t_per": 6.8, "t_eps": 7323, "sh_return": 3.2, "t_pegy": 0.64, "t_fair": 60000, "f_per": 5.90, "f_eps": 8440, "growth": 15.2, "vol": "🟢 정상"}
    ]

    rng = random.Random(42)
    stocks = []
    
    for s in base_stocks:
        stocks.append(dict(s))
        
    sec_names = ["제약", "바이오", "화학", "철강", "건설", "증권", "보험", "중공업", "기계", "유통", "음식료", "IT부품", "디스플레이", "소프트웨어", "게임", "미디어"]
    for idx in range(len(base_stocks) + 1, 201):
        code_str = f"{idx:06d}"
        sec = rng.choice(sec_names)
        name_str = f"KOSPI {sec} {idx-30}호"
        price_val = rng.randint(15, 450) * 1000
        
        t_roe_val = round(rng.uniform(3.0, 25.0), 1)
        f_roe_val = round(t_roe_val * rng.uniform(0.9, 1.25), 1)
        roic_val = round(t_roe_val * rng.uniform(0.7, 0.95), 1)
        
        sh_ret_val = round(rng.uniform(0.0, 8.5), 1)
        dps_val = int(price_val * (sh_ret_val * 0.6) / 100)
        tot_amt_val = f"총 {rng.randint(300, 9500)}억원" if sh_ret_val > 0.5 else "0원"
        
        t_per_val = round(rng.uniform(5.0, 35.0), 2)
        t_eps_val = int(price_val / t_per_val)
        t_pegy_val = round(rng.uniform(0.35, 2.5), 2)
        t_fair_val = int(price_val * rng.uniform(0.85, 1.35))
        
        f_per_val = round(t_per_val * rng.uniform(0.75, 1.05), 2)
        f_eps_val = int(t_eps_val * rng.uniform(1.05, 1.45))
        growth_val = round(rng.uniform(6.0, 65.0), 1)
        vol_val = "🟢 정상" if rng.random() > 0.3 else "⚡ 변동성 보정 중"
        
        stocks.append({
            "name": name_str, "code": code_str, "price": price_val,
            "t_roe": t_roe_val, "f_roe": f_roe_val, "roic": roic_val,
            "dps": dps_val, "return_total": tot_amt_val,
            "t_per": t_per_val, "t_eps": t_eps_val, "sh_return": sh_ret_val,
            "t_pegy": t_pegy_val, "t_fair": t_fair_val,
            "f_per": f_per_val, "f_eps": f_eps_val, "growth": growth_val,
            "vol": vol_val
        })

    # =========================================================
    # 퀀트 정밀 수식 연동 (젬민이 튜닝 알고리즘 반영)
    # =========================================================
    for s in stocks:
        f_per_val = s["f_per"]
        f_eps_val = s["f_eps"]
        growth_val = s["growth"]
        sh_ret_val = s["sh_return"]
        vol_val = s["vol"]
        f_roe_val = s["f_roe"]
        roic_val = s["roic"]
        t_roe_val = s["t_roe"]

        # 1. Forward PEGY 보정 공식 (growth 35% Cap & 변동성 벌점 1.18배)
        capped_growth = min(growth_val, 35.0)
        denom = capped_growth + sh_ret_val
        vol_penalty = 1.18 if "보정" in vol_val else 1.0
        f_pegy_val = round((f_per_val / max(denom, 0.1)) * vol_penalty, 2)
        s["f_pegy"] = f_pegy_val

        # 2. ROE/ROIC 품질 가중 Target PER & 목표주가(f_target)
        roe_prem = 0.15 if f_roe_val >= 12.0 else -0.10
        roic_prem = 0.10 if roic_val >= 10.0 else -0.05
        target_per = 10.4 * (1.0 + roe_prem + roic_prem)
        s["f_target"] = int(f_eps_val * target_per)

        # 3. 종합 퀀트 스코어 (Quant Score - 100점 만점)
        # A. PEGY 밸류에이션 점수 (최대 35점)
        if f_pegy_val < 0.65:
            s_pegy = 35
        elif f_pegy_val < 0.85:
            s_pegy = 28
        elif f_pegy_val < 1.0:
            s_pegy = 20
        elif f_pegy_val < 1.35:
            s_pegy = 12
        else:
            s_pegy = 5

        # B. 자본효율성 점수 (최대 30점: ROE 15점 + ROIC 15점)
        s_f_roe = 15 if f_roe_val >= 15.0 else (10 if f_roe_val >= 10.0 else 4)
        s_roic = 15 if roic_val >= 12.0 else (10 if roic_val >= 8.0 else 4)
        s_quality = s_f_roe + s_roic

        # C. 주주환원율 점수 (최대 20점)
        if sh_ret_val >= 5.0:
            s_return = 20
        elif sh_ret_val >= 3.0:
            s_return = 14
        elif sh_ret_val >= 1.0:
            s_return = 8
        else:
            s_return = 3

        # D. Trailing 실적 안정성 (최대 10점)
        if t_roe_val >= 10.0:
            s_trailing = 10
        elif t_roe_val >= 6.0:
            s_trailing = 6
        else:
            s_trailing = 2

        # E. 변동성위험 보정 (최대 5점)
        s_vol = 5 if "정상" in vol_val else 1

        s["quant_score"] = int(s_pegy + s_quality + s_return + s_trailing + s_vol)

        # 4. 상태 배지 및 착시 저평가 위험 판정
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

        s["value_trap"] = (s["t_roe"] < 8.0 or s["roic"] < 6.0)

    return stocks

def render_pegy_page():
    """'💡 사실 이 가격이에요' (퀀트 100점 만점 종합 점수 & 정밀 수식 반영) 화면 렌더링"""
    
    # 1. 툴팁 전용 CSS 주입
    st.markdown(
        """
        <style>
        .q-tooltip {
            position: relative;
            display: inline-flex;
            align-items: center;
            cursor: help;
            color: #94a3b8;
            border-bottom: 1px dotted #64748b;
            font-weight: 500;
        }
        .q-tooltip .q-tooltiptext {
            visibility: hidden;
            width: 320px;
            background-color: #0f172a;
            color: #f1f5f9;
            text-align: left;
            border-radius: 8px;
            padding: 12px 15px;
            position: absolute;
            z-index: 9999;
            bottom: 130%;
            left: 50%;
            transform: translateX(-50%);
            opacity: 0;
            transition: opacity 0.2s ease-in-out, visibility 0.2s;
            border: 1px solid #38bdf8;
            font-size: 11.5px;
            line-height: 1.5;
            box-shadow: 0 6px 18px rgba(0,0,0,0.6);
            font-weight: 400;
        }
        .q-tooltip .q-tooltiptext::after {
            content: "";
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: #38bdf8 transparent transparent transparent;
        }
        .q-tooltip:hover .q-tooltiptext {
            visibility: visible;
            opacity: 1;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # 2. 상단 그라데이션 타이틀
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #d97706; margin: 0 0 8px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">KOSPI 200개 종목 Trailing vs Forward PEGY & 100점 만점 퀀트 종합점수 리포트</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 3. 요약 지표 카드 3종
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 평균 Forward PER", "10.4 배", "-0.8배 (전월 대비)")
    with col2:
        st.metric("코스피 대표 EPS 성장률 (Cap 35%)", "14.2 %", "+1.5%p")
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", "0.73", "저평가 수용 구간")

    st.markdown("---")

    # 4. KOSPI 200 종목 데이터 로드
    all_stocks = get_kospi200_pegy_data()

    # 5. 상단 검색 및 필터 컨트롤 + 쉬운 설명 가이드
    f_col1, f_col2, f_col3 = st.columns([2, 3, 2.2])
    with f_col1:
        search_query = st.text_input("🔍 종목명 / 종목코드 검색", placeholder="예: 삼성전자, 005930").strip()
    with f_col2:
        selected_badges = st.multiselect(
            "🏷️ 밸류에이션 상태 필터",
            ["🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성", "🔴 고평가 관망"],
            default=["🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성", "🔴 고평가 관망"]
        )
    with f_col3:
        only_value_trap = st.checkbox(
            "⚠️ '착시 저평가' 주의 종목만 보기", 
            value=False,
            help="주가가 PER 수치상 싸 보이지만, 실제 이익창출력(ROE<8% 또는 ROIC<6%)이 낮아 오랜 기간 주가가 오르지 못하고 갇히는 위험 종목입니다."
        )

    # 쉬운 용어 안내 박스 (인포서브 설명)
    st.info(
        "💡 **'착시 저평가 (가치주 덫)' 및 100점 만점 퀀트 스코어 안내**\n"
        "• **100점 만점 퀀트 스코어(quant_score)**: PEGY(35점) + ROE/ROIC(30점) + 주주환원(20점) + Trailing(10점) + 변동성(5점)을 합산하여 종합 점수를 매깁니다.\n"
        "• **착시 저평가**: 주가가 단순히 PER 5배~7배로 싸 보이지만 이익창출력(ROE<8% / ROIC<6%)이 턱없이 낮아 주가가 바닥에 갇히는 위험 종목에 ⚠️ 태그를 부여합니다."
    )

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
    if only_value_trap:
        filtered_stocks = [s for s in filtered_stocks if s["value_trap"]]

    st.markdown(f"**전체 검색/필터 결과:** `{len(filtered_stocks)}`개 종목 (총 {len(all_stocks)}개 KOSPI 종목 중)")

    # 6. 페이지네이션 정보 계산
    items_per_page = 20
    total_items = len(filtered_stocks)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

    if "pegy_current_page" not in st.session_state:
        st.session_state.pegy_current_page = 1
        
    current_page = min(st.session_state.pegy_current_page, total_pages)

    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_stocks = filtered_stocks[start_idx:end_idx]

    st.markdown("---")

    # 7. 2단 수직 스택(상단 지표라벨 / 하단 수치대형폰트) & 퀀트 스코어 뱃지 정렬
    if not page_stocks:
        st.warning("선택한 필터 조건에 일치하는 종목이 없습니다.")
        return

    for s in page_stocks:
        vol_color = "#f43f5e" if "보정 중" in s["vol"] else "#38bdf8"
        roe_color = "#f43f5e" if s["t_roe"] < 8.0 else "#4ade80"
        roic_color = "#f43f5e" if s["roic"] < 6.0 else "#38bdf8"
        
        trap_badge_html = ""
        if s["value_trap"]:
            trap_badge_html = """
            <span style="background-color: #7f1d1d; color: #fca5a5; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #f87171; white-space: nowrap;">
                ⚠️ 이익창출력 저하 (착시 저평가 주의)
            </span>
            """
        else:
            trap_badge_html = """
            <span style="background-color: #14532d; color: #86efac; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #4ade80; white-space: nowrap;">
                ✨ 우량 자본효율성 (Quality OK)
            </span>
            """

        dps_str = f"{s['dps']:,.0f}원/주" if s['dps'] > 0 else "무배당"
        growth_disp = f"+{s['growth']}%" if s['growth'] <= 35.0 else f"+{s['growth']}% (Cap 35%)"

        card_html = f"""
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <!-- 1. 메인 헤더: 종목명 / 코드 / 퀀트종합점수 / 배지 / 현재가 -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <span style="font-size: 23px; font-weight: 800; color: #f8fafc; white-space: nowrap;">{s['name']}</span>
                    <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({s['code']})</span>
                    <!-- 100점 만점 퀀트 종합점수 뱃지 -->
                    <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px; font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                        <span class="q-tooltip" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="q-tooltiptext"><b>종합 퀀트 스코어 (100점 만점)</b><br>• PEGY 밸류에이션: 최대 35점<br>• 자본효율성 (ROE/ROIC): 최대 30점<br>• 주주환원율 (DPS): 최대 20점<br>• Trailing 실적안정성: 최대 10점<br>• 변동성위험 보정: 최대 5점</span></span> <b>{s['quant_score']}점</b> / 100점
                    </span>
                    <span style="background-color: {s['badge_bg']}; color: {s['badge_fg']}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {s['badge_fg']}; white-space: nowrap;">
                        {s['badge']}
                    </span>
                    <span style="font-size: 12px; color: {vol_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6); padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">{s['vol']}</span>
                    {trap_badge_html}
                </div>
                <div style="display: flex; align-items: baseline; gap: 8px;">
                    <span style="font-size: 13px; color: #94a3b8;">현재가:</span>
                    <span style="font-size: 25px; font-weight: 900; color: #38bdf8;">{s['price']:,.0f}원</span>
                </div>
            </div>

            <!-- 2. 자본효율성 품질 바 (Quality Bar) -->
            <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; justify-content: flex-start; gap: 28px; flex-wrap: wrap;">
                <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext"><b>Trailing ROE (자기자본이익률)</b><br>지난 12개월(4분기 합산) 순이익을 자기자본으로 나눈 자본 효율성 지표입니다. 8% 미만 시 이익 창출력이 부족한 상태입니다.</span></span>: 
                    <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['t_roe']}%</b>
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE (추정 자기자본이익률)</b><br>향후 12개월 애널리스트 컨센서스 기준 예상 순이익 기반 예상 ROE입니다. (>=12% 시 목표가 +15% 프리미엄)</span></span>: 
                    <b style="color: #38bdf8; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['f_roe']}%</b>
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">ROIC (ROC) ℹ️<span class="q-tooltiptext"><b>ROIC (투입자본이익률 / ROC)</b><br>실제 영업에 투입된 자산이 창출한 세후 영업이익 비율입니다. (>=10% 시 목표가 +10% 프리미엄, <6% 시 착시 저평가 경고)</span></span>: 
                    <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['roic']}%</b>
                </span>
            </div>

            <!-- 3. Trailing 섹션 (과거 실적 참고용 - 상단 라벨 / 하단 수치 2단 스택) -->
            <div style="background-color: rgba(30, 41, 59, 0.45); border: 1px solid #334155; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px; opacity: 0.88;">
                <div style="font-size: 12px; font-weight: 700; color: #94a3b8; margin-bottom: 10px; border-bottom: 1px dashed #475569; padding-bottom: 4px; display: flex; justify-content: space-between; align-items: center;">
                    <span>📜 Trailing (과거 실적 참고용)</span>
                    <span style="font-size: 11px; color: #64748b; font-weight: 400;">*과거 12개월 실적 스냅샷</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1.3fr 2.2fr 1.3fr; gap: 14px; align-items: flex-start;">
                    <div>
                        <div style="font-size: 11.5px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext"><b>Trailing ROE</b><br>과거 12개월 평균 자기자본 대비 순이익 비율</span></span>
                        </div>
                        <div style="font-size: 14px; font-weight: 700; color: #cbd5e1;">{s['t_roe']}%</div>
                    </div>
                    <div>
                        <div style="font-size: 11.5px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">PER / EPS ℹ️<span class="q-tooltiptext"><b>Trailing PER & EPS</b><br>• PER (주가수익비율): 주가 / 주당순이익<br>• EPS (주당순이익): 최근 4분기 합산 순이익 / 발행주식수</span></span>
                        </div>
                        <div style="font-size: 14px; font-weight: 700; color: #cbd5e1;">{s['t_per']}배 / {s['t_eps']:,.0f}원</div>
                    </div>
                    <div>
                        <div style="font-size: 11.5px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">주주환원 상세 (DPS/총액) ℹ️<span class="q-tooltiptext"><b>주주환원 세부 내역</b><br>• 1주당 배당금 (DPS): {dps_str}<br>• 주주환원 총 규모: {s['return_total']}<br>• 총 주주환원율: {s['sh_return']}%</span></span>
                        </div>
                        <div style="font-size: 13.5px; font-weight: 700; color: #86efac;">DPS {dps_str} | 환원율 {s['sh_return']}% ({s['return_total']})</div>
                    </div>
                    <div>
                        <div style="font-size: 11.5px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">PEGY / 과거 적정가 ℹ️<span class="q-tooltiptext"><b>Trailing PEGY & 과거 적정주가</b><br>• PEGY: PER / (성장률 + 주주환원율)<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                        </div>
                        <div style="font-size: 14px; font-weight: 700; color: #38bdf8;">{s['t_pegy']} / {s['t_fair']:,.0f}원</div>
                    </div>
                </div>
            </div>

            <!-- 4. Forward 섹션 (미래 추정 밸류 분석 - 선명 솔리드 다크 목표가 박스 & 35% Cap 산식 적용) -->
            <div style="background: linear-gradient(135deg, rgba(14, 116, 144, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px solid #38bdf8; border-radius: 12px; padding: 16px 22px; box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);">
                <!-- 헤더: 2줄 넉넉한 타이틀 + 우측 설명 주석 -->
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #0284c7; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #38bdf8; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #7dd3fc; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #7dd3fc; font-weight: 500; white-space: nowrap;">*12개월 Forward 컨센서스 (성장률 35% Cap & 변동성 1.18x 벌점 반영)</span>
                </div>

                <!-- 수치 영역: 4열 Grid & 젬민이 튜닝 수식 결과 노출 -->
                <div style="display: grid; grid-template-columns: 1fr 1.3fr 1fr 1.7fr; gap: 14px; align-items: center;">
                    <div>
                        <div style="font-size: 12px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE</b><br>향후 12개월 애널리스트 예상 순이익 기반 ROE</span></span>
                        </div>
                        <div style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">{s['f_roe']}%</div>
                    </div>
                    <div>
                        <div style="font-size: 12px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">Forward PER / EPS ℹ️<span class="q-tooltiptext"><b>Forward PER & EPS</b><br>• Forward PER: 주가 / 12개월 추정 EPS<br>• Forward EPS: 향후 12개월 예상 주당순이익</span></span>
                        </div>
                        <div style="font-size: 15.5px; font-weight: 800; color: #f1f5f9;">{s['f_per']}배 / {s['f_eps']:,.0f}원</div>
                    </div>
                    <div>
                        <div style="font-size: 12px; color: #94a3b8; margin-bottom: 4px;">
                            <span class="q-tooltip">예상 성장률 ℹ️<span class="q-tooltiptext"><b>예상 EPS 성장률 (%)</b><br>향후 12개월 EPS 예상 성장 비율 (기저효과 착시 방지를 위해 최대 35.0% 상한 적용)</span></span>
                        </div>
                        <div style="font-size: 15.5px; font-weight: 800; color: #4ade80;">{growth_disp}</div>
                    </div>
                    <div style="background-color: #0f172a; padding: 8px 14px; border-radius: 8px; border: 1.5px solid #f43f5e; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
                        <div style="font-size: 12px; color: #fca5a5; margin-bottom: 2px;">
                            <span class="q-tooltip" style="color: #fca5a5; font-weight: 700;">목표가 (PEGY) ℹ️<span class="q-tooltiptext"><b>보정 Forward PEGY & 퀀트 목표주가</b><br>• 보정 PEGY = (f_per / (min(growth,35) + sh_return)) * (1.18 if 변동성보정 else 1.0)<br>• 목표가(Target Price) = f_eps * (10.4 * (1 + ROE프리미엄 + ROIC프리미엄))</span></span>
                        </div>
                        <div style="font-size: 16.5px; font-weight: 900; color: #ff4d6d; letter-spacing: 0.2px;">{s['f_pegy']} / {s['f_target']:,.0f}원</div>
                    </div>
                </div>
            </div>
        </div>
        """
        clean_card = "\n".join([line.strip() for line in card_html.split("\n") if line.strip()])
        st.markdown(clean_card, unsafe_allow_html=True)

    # 8. 페이지네이션 (Pagination) 컨트롤 - 하단 배치
    st.markdown("---")
    st.markdown("##### 📄 페이지 선택 (한 화면에 20개 종목 카드 노출)")

    page_options = [f"페이지 {i} (종목 {(i-1)*20+1} ~ {min(i*20, total_items)})" for i in range(1, total_pages + 1)]
    
    selected_page_str = st.radio(
        "페이지 이동", 
        page_options, 
        index=current_page - 1, 
        horizontal=True,
        key="pegy_page_radio"
    )
    
    new_page = page_options.index(selected_page_str) + 1
    if new_page != st.session_state.pegy_current_page:
        st.session_state.pegy_current_page = new_page
        st.rerun()
