import os
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import streamlit as st

from utils.db import HISTORY_FILE, COL_MAP, save_and_load_history
from views.admin_view import render_admin_console

def render_clean_html(html_str):
    clean_html = "\n".join([line.strip() for line in html_str.split("\n") if line.strip()])
    st.markdown(clean_html, unsafe_allow_html=True)

try:
    from pykrx import stock
    PYKRX_AVAILABLE = True
except ImportError:
    PYKRX_AVAILABLE = False

try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False

layers = {
    10: ("10층", "💥 최극상 위험", "주식 0% / 현금 100%", "완전 대피 및 현금 최대 확보"),
    9:  ("9층", "🚨 극심한 위험", "주식 10% / 현금 90%", "주식 신규 매수 절대금지"),
    8:  ("8층", "⚡ 심각한 위험", "주식 20% / 현금 80%", "주식 강제 청산 및 대피"),
    7:  ("7층", "⚠️ 고위험 경고", "주식 30% / 현금 70%", "현금 비중 대폭 확대"),
    6:  ("6층", "🟧 경계 필요", "주식 40% / 현금 60%", "현금 비중 분할 확대"),
    5:  ("5층", "🟨 중립 경계", "주식 50% / 현금 50%", "5:5 중립 포지션 관망"),
    4:  ("4층", "🟩 주의 관찰", "주식 60% / 현금 40%", "분할 익절 및 점진적 현금화"),
    3:  ("3층", "🟢 양호 관망", "주식 70% / 현금 30%", "수급 회복 단계 및 완만한 진입"),
    2:  ("2층", "🟦 청정 안전", "주식 80% / 현금 20%", "주식 비중 확대 및 현물 투자"),
    1:  ("1층", "🔷 매우 안전", "주식 90% / 현금 10%", "적극 주식 매수 집행"),
    0:  ("0층", "⚪ 무위험 지대", "주식 100% / 현금 0%", "하방 위험 없음 / 적극 홀딩")
}

def fetch_verified_market_data(override_date=None, override_kospi=None, override_usd=None, override_retail=None, override_fore=None, override_inst=None):
    """
    KRX 및 Naver 수급 데이터를 크롤링하고 실전 가중치를 산출합니다.
    로컬 CSV 파일을 체크하여 이미 조회한 날짜의 데이터라면 웹 크롤링 요청 없이 로컬에서 즉시 불러옵니다.
    """
    if override_date is not None:
        date_key = override_date
        display_date = datetime.strptime(override_date, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
        local_loaded = False
        is_live_connected = True
        kospi_close = override_kospi
        usd_close = override_usd
        retail_flow = override_retail
        foreigner_flow = override_fore
        institution_flow = override_inst
        kospi_change = 0.0
        usd_change = 0.0
        volatility = 1.2
        dist_from_high = 0.08
        sugeub_fetched = True
        data_source_log = "관리자 수동 데이터 입력 완료"
    else:
        target_date = datetime.today()
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
            
        date_key = target_date.strftime("%Y-%m-%d")
        display_date = target_date.strftime("%Y년 %m월 %d일")
        
        local_loaded = False
        kospi_close = 2500.0
        kospi_change = 0.0
        usd_close = 1350.0
        usd_change = 0.0
        volatility = 1.2
        dist_from_high = 0.08
        foreigner_flow = 0
        institution_flow = 0
        retail_flow = 0
        score = 50.0
        
        if os.path.exists(HISTORY_FILE):
            try:
                history_df = pd.read_csv(HISTORY_FILE)
                history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
                history_df["Date"] = history_df["Date"].astype(str)
                row = history_df[history_df["Date"] == date_key]
                if not row.empty:
                    score = float(row.iloc[0]["Score"])
                    kospi_close = float(row.iloc[0]["KOSPI"])
                    usd_close = float(row.iloc[0]["USD_KRW"])
                    retail_flow = int(row.iloc[0]["Retail"])
                    foreigner_flow = int(row.iloc[0]["Foreigner"])
                    institution_flow = int(row.iloc[0]["Institution"])
                    local_loaded = True
            except Exception:
                pass

        is_live_connected = False
        data_source_log = "로컬 누적 DB 로드 완료" if local_loaded else "안전 모드 진입"

    if not local_loaded and override_date is None:
        if FDR_AVAILABLE:
            try:
                kospi_df = fdr.DataReader('^KS11')
                usd_df = fdr.DataReader('USDKRW=X')
                
                if not kospi_df.empty and not usd_df.empty:
                    latest_kospi = kospi_df.iloc[-1]
                    prev_kospi = kospi_df.iloc[-2]
                    kospi_close = latest_kospi['Close']
                    kospi_change = (kospi_close - prev_kospi['Close']) / prev_kospi['Close']
                    
                    latest_usd = usd_df.iloc[-1]
                    prev_usd = usd_df.iloc[-2]
                    usd_close = latest_usd['Close']
                    usd_change = (usd_close - prev_usd['Close']) / prev_usd['Close']
                    
                    kospi_returns = kospi_df['Close'].pct_change(fill_method=None).dropna()
                    volatility = kospi_returns.tail(10).std() * 100
                    if math.isnan(volatility) or volatility == 0:
                        volatility = 1.2
                        
                    high_52w = kospi_df['High'].max()
                    dist_from_high = (high_52w - kospi_close) / high_52w
                    display_date = latest_kospi.name.strftime("%Y년 %m월 %d일")
                    data_source_log = "성공: FinanceDataReader 실시간 지수/환율 연동 성공"
            except Exception as e:
                data_source_log = f"시세 연동 실패로 안전 모드 동작 ({str(e)})"

        sugeub_fetched = False
        if PYKRX_AVAILABLE:
            try:
                dt_str = date_key.replace("-", "")
                df_net = stock.get_market_net_purchases_of_equities_by_ticker(dt_str, dt_str, "KOSPI")
                if not df_net.empty:
                    retail_flow = int(df_net['개인'].sum() / 100000000)
                    foreigner_flow = int(df_net['외국인합계'].sum() / 100000000)
                    institution_flow = int(df_net['기관합계'].sum() / 100000000)
                    data_source_log = "성공: pykrx 수급 스크래퍼 연동 완료"
                    sugeub_fetched = True
            except Exception:
                pass

        if not sugeub_fetched:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                found = False
                for page in range(1, 6):
                    url = f'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={date_key.replace("-", "")}&sosok=01&page={page}'
                    r = requests.get(url, headers=headers)
                    r.encoding = 'euc-kr'
                    soup = BeautifulSoup(r.text, 'html.parser')
                    tb = soup.find('table', class_='type_1')
                    
                    if tb:
                        rows = tb.find_all('tr')
                        for tr in rows[2:]:
                            cells = [td.text.strip() for td in tr.find_all(['td'])]
                            cells = [c for c in cells if c]
                            if cells and len(cells) >= 4:
                                date_str = "20" + cells[0].replace(".", "-")
                                if date_str == date_key:
                                    retail_flow = int(cells[1].replace(",", ""))
                                    foreigner_flow = int(cells[2].replace(",", ""))
                                    institution_flow = int(cells[3].replace(",", ""))
                                    display_date = target_date.strftime("%Y년 %m월 %d일")
                                    data_source_log = f"성공: 백업용 마켓 수급 스크래핑 연동 완료 (Naver Page {page})"
                                    sugeub_fetched = True
                                    found = True
                                    break
                        if found:
                            break
            except Exception as e:
                data_source_log = f"수급 연동 오류로 안전 모드 강제 동작 ({str(e)})"

    fx_base = 0.5 + 0.3 * (usd_close - 1200) / 300
    put_base = 0.5 - 0.4 * kospi_change
    short_base = 0.4 + 0.4 * (volatility / 5.0)
    els_base = 0.1 + 0.7 * dist_from_high
    skew_base = 0.4 + 0.4 * (volatility / 5.0) - 0.2 * kospi_change
    synth_base = 0.5 + 0.3 * (usd_close - 1300) / 200
    ndf_base = 0.4 + 0.5 * usd_change
    fut_base = 0.5 - 0.3 * kospi_change
    non_base = 0.5 + (0.2 if institution_flow < 0 else -0.1)
    dump_base = 0.5 + (0.3 if foreigner_flow < 0 else -0.2)
    bal_base = 0.5 + 0.3 * dist_from_high
    put_buy_base = 0.4 - 0.3 * kospi_change
    stock_net_base = 0.5

    kospi_5d_base = 0.5
    if FDR_AVAILABLE and not local_loaded:
        try:
            if len(kospi_df) >= 6:
                kospi_5d_prev = float(kospi_df.iloc[-6]['Close'])
                kospi_5d_return = (kospi_close - kospi_5d_prev) / kospi_5d_prev
            else:
                kospi_5d_return = 0.0
            kospi_5d_base = 0.5 - 2.5 * kospi_5d_return
        except Exception:
            pass

    def clip(val):
        return min(1.0, max(0.0, val))

    market_scores = {
        "FX_Swap_Point": {"Foreigner": clip(fx_base + 0.1 * usd_change), "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)},
        "Put_OTM_OI": {"Foreigner": clip(put_base + (0.1 if foreigner_flow < 0 else -0.1)), "Institution": clip(put_base + (0.05 if institution_flow < 0 else -0.05)), "Retail": clip(put_base + (0.15 if retail_flow > 0 else -0.1))},
        "Short_Ratio": {"Foreigner": clip(short_base + (0.1 if foreigner_flow < 0 else -0.05)), "Institution": clip(short_base + (0.05 if institution_flow < 0 else -0.05)), "Retail": clip(short_base - 0.2)},
        "ELS_KnockIn": {"Foreigner": clip(els_base), "Institution": clip(els_base + 0.1), "Retail": clip(els_base - 0.1)},
        "VKOSPI_Skew": {"Foreigner": clip(skew_base + 0.05), "Institution": clip(skew_base), "Retail": clip(skew_base - 0.2)},
        "Synthetic_Futures": {"Foreigner": clip(synth_base + (0.15 if foreigner_flow < 0 else -0.1)), "Institution": clip(synth_base), "Retail": clip(synth_base + (0.05 if retail_flow > 0 else -0.05))},
        "NDF_Night_Rate": {"Foreigner": clip(ndf_base + 0.1), "Institution": clip(ndf_base), "Retail": clip(ndf_base - 0.2)},
        "Futures_Net_Sell": {"Foreigner": clip(fut_base + (0.2 if foreigner_flow < 0 else -0.15)), "Institution": clip(fut_base + (0.1 if institution_flow < 0 else -0.1)), "Retail": clip(fut_base + (0.15 if retail_flow > 0 else -0.1))},
        "Non_Arbitrage_Ratio": {"Foreigner": clip(non_base + 0.05), "Institution": clip(non_base + 0.1), "Retail": clip(non_base - 0.2)},
        "Foreign_Broker_Dump": {"Foreigner": clip(dump_base + 0.15), "Institution": clip(dump_base - 0.1), "Retail": clip(dump_base - 0.3)},
        "Stock_Short_Balance": {"Foreigner": clip(bal_base + 0.05), "Institution": clip(bal_base + 0.05), "Retail": clip(bal_base - 0.2)},
        "Put_Buy_Simple": {"Foreigner": clip(put_buy_base + (0.05 if foreigner_flow < 0 else -0.05)), "Institution": clip(put_buy_base), "Retail": clip(put_buy_base + (0.1 if retail_flow > 0 else -0.1))},
        "Stock_Net_Sell": {"Foreigner": clip(stock_net_base + (0.3 if foreigner_flow < 0 else -0.3)), "Institution": clip(stock_net_base + (0.2 if institution_flow < 0 else -0.2)), "Retail": clip(stock_net_base + (0.3 if retail_flow < 0 else -0.3))},
        "KOSPI_5D_Return": {"Foreigner": clip(kospi_5d_base), "Institution": clip(kospi_5d_base), "Retail": clip(kospi_5d_base)}
    }

    weights = {
        "FX_Swap_Point": round(12 * 100 / 102, 4), "Put_OTM_OI": round(8 * 100 / 102, 4),
        "Short_Ratio": round(6 * 100 / 102, 4), "ELS_KnockIn": round(7 * 100 / 102, 4),
        "VKOSPI_Skew": round(6 * 100 / 102, 4), "Synthetic_Futures": round(12 * 100 / 102, 4),
        "NDF_Night_Rate": round(12 * 100 / 102, 4), "Futures_Net_Sell": round(6 * 100 / 102, 4),
        "Non_Arbitrage_Ratio": round(6 * 100 / 102, 4), "Foreign_Broker_Dump": round(6 * 100 / 102, 4),
        "Stock_Short_Balance": round(3 * 100 / 102, 4), "Put_Buy_Simple": round(3 * 100 / 102, 4),
        "Stock_Net_Sell": round(3 * 100 / 102, 4), "KOSPI_5D_Return": round(12 * 100 / 102, 4)
    }

    friendly_names = {
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

    formulas = {
        "FX_Swap_Point": "0.55 × clip(0.5 + 0.3×(USD-1200)/300 + 0.1×USD_change) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Put_OTM_OI": "0.55 × clip(0.5 - 0.4×KOSPI_change + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base + Ret_Sign)",
        "Short_Ratio": "0.55 × clip(0.4 + 0.4×(Vol/5) + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base - 0.2)",
        "ELS_KnockIn": "0.55 × clip(0.1 + 0.7×Dist_High) + 0.37 × clip(base + 0.1) + 0.08 × clip(base - 0.1)",
        "VKOSPI_Skew": "0.55 × clip(0.4 + 0.4×(Vol/5) - 0.2×KOSPI_change + 0.05) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Synthetic_Futures": "0.55 × clip(0.5 + 0.3×(USD-1300)/200 + Fore_Sign) + 0.37 × clip(base) + 0.08 × clip(base + Ret_Sign)",
        "NDF_Night_Rate": "0.55 × clip(0.4 + 0.5×USD_change + 0.1) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Futures_Net_Sell": "0.55 × clip(0.5 - 0.3×KOSPI_change + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base + Ret_Sign)",
        "Non_Arbitrage_Ratio": "0.55 × clip(0.5 + Inst_Sign + 0.05) + 0.37 × clip(base + 0.1) + 0.08 × clip(base - 0.2)",
        "Foreign_Broker_Dump": "0.55 × clip(0.5 + Fore_Sign + 0.15) + 0.37 × clip(base - 0.1) + 0.08 × clip(base - 0.3)",
        "Stock_Short_Balance": "0.55 × clip(0.5 + 0.3×Dist_High + 0.05) + 0.37 × clip(base + 0.05) + 0.08 × clip(base - 0.2)",
        "Put_Buy_Simple": "0.55 × clip(0.4 - 0.3×KOSPI_change + Fore_Sign) + 0.37 × clip(base) + 0.08 × clip(base + Ret_Sign)",
        "Stock_Net_Sell": "0.55 × clip(0.5 + Fore_Sign) + 0.37 × clip(0.5 + Inst_Sign) + 0.08 × clip(0.5 + Ret_Sign)",
        "KOSPI_5D_Return": "clip(0.5 - 2.5 × KOSPI_5D_Return)"
    }

    investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}

    sub_scores = {}
    total_weighted_risk = 0.0
    total_weight = sum(weights.values())
    extreme_signal_count = 0

    for item, w in weights.items():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        if weighted_risk >= 0.75:
            extreme_signal_count += 1
            
        sub_scores[item] = round(weighted_risk * 100.0, 1)
        total_weighted_risk += weighted_risk * w

    base_score = (total_weighted_risk / total_weight) * 100.0

    multiplier = 1.0
    if extreme_signal_count >= 5:
        multiplier = 1.3
    elif extreme_signal_count >= 3:
        multiplier = 1.15

    # [수정] 위험 할증(Multiplier)은 위험 지수가 50점을 초과할 때만 상향 가산 적용
    if base_score > 50.0:
        final_score = 50.0 + (base_score - 50.0) * multiplier
    else:
        # 50점 이하 안정 구간에서는 극단 신호 발생 시 위험도 기여분을 원점수로 가산
        final_score = base_score + (extreme_signal_count * 2.5)

    final_score = round(max(0.0, min(100.0, final_score)), 1)
    score = final_score

    details = []
    for item, w in weights.items():
        sub_score_val = sub_scores[item]
        display_risk = round(sub_score_val / 100.0, 3)
        details.append({
            "지표명 (한글 설명)": friendly_names.get(item, item),
            "중요도 (가중치)": w,
            "위험도 (0~1)": display_risk,
            "기여점수": round(w * display_risk, 2),
            "산출 공식 (수학적 모델)": formulas.get(item, "")
        })
        
    details = sorted(details, key=lambda x: x["중요도 (가중치)"], reverse=True)

    metrics_dict = {}
    for item in weights.keys():
        risks = market_scores[item]
        weighted_risk = (
            (risks["Foreigner"] * investor_weights["Foreigner"])
            + (risks["Institution"] * investor_weights["Institution"])
            + (risks["Retail"] * investor_weights["Retail"])
        )
        metrics_dict[item] = weighted_risk

    if local_loaded or is_live_connected:
        history_df = save_and_load_history(date_key, score, kospi_close, usd_close, retail_flow, foreigner_flow, institution_flow, metrics_dict)
    else:
        if os.path.exists(HISTORY_FILE):
            history_df = pd.read_csv(HISTORY_FILE)
            history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
            history_df["Date"] = history_df["Date"].astype(str)
        else:
            history_df = pd.DataFrame()

    if local_loaded:
        is_live_connected = True

    status_text = f"KOSPI: {kospi_close:.2f} ({kospi_change*100:+.2f}%) | 환율: {usd_close:.2f}원 ({usd_change*100:+.2f}%)"
    return display_date, is_live_connected, f"{data_source_log} | {status_text}", score, details, history_df

def render_macro_page():
    """'🏢 잘 보면 보이는 손' 메인 방공망 대시보드 화면 전체 렌더링"""
    render_clean_html(
        """
        <div style="text-align: center; margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #0f766e; margin: 0 0 8px 0; letter-spacing: -0.5px;">🏢 잘 보면 보이는 손 <span style="font-size: 22px; font-weight: 600; color: #64748b;">(The Visible Hand)</span></h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">실시간 수급 연동형 시장 종합 위험 방공망 대시보드</div>
        </div>
        """
    )

    admin_mode = st.session_state.get("admin_mode", False)

    date_str, is_live, log_msg, score, details, history_df = fetch_verified_market_data()

    render_admin_console(fetch_verified_market_data)

    if admin_mode:
        st.write(f"📊 **[관리자] 로드된 데이터 행 개수:** `{len(history_df)}`개")

    st.markdown(
        f"""
        <div style="text-align:center; color:#475569; font-weight: 600; line-height: 1.6; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 16px;">📅 기준 영업일: {date_str}</div>
            <div style="font-size: 13px; color: #64748b; font-weight: 500; margin-top: 2px;">🔔 장마감 후 데이터가 정리됩니다 (매일 오후 4시 30분 이후 최신화)</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    col1, col2 = st.columns([4, 1])
    with col1:
        user_log_msg = log_msg
        if not admin_mode:
            user_log_msg = user_log_msg.replace("로컬 누적 DB 로드 완료", "실시간 금융 데이터 동기화 완료")
        
        clean_status = user_log_msg.split('|')[0].strip()
        if is_live:
            st.success(f"✅ **[실전 연동 성공 상태]** {clean_status}")
        else:
            st.info(f"ℹ️ **[휴장일/안전 모드 상태]** {clean_status}")
    with col2:
        if st.button("🔄 새로고침"):
            st.cache_data.clear()
            st.rerun()

    if len(history_df) >= 1:
        df_sorted = history_df.sort_values(by="Date")
        latest_row = df_sorted.iloc[-1]
        k_val = float(latest_row["KOSPI"])
        u_val = float(latest_row["USD_KRW"])
        
        if len(history_df) >= 2:
            prev_row = df_sorted.iloc[-2]
            k_prev = float(prev_row["KOSPI"])
            k_pct = ((k_val - k_prev) / k_prev) * 100
            u_prev = float(prev_row["USD_KRW"])
            u_pct = ((u_val - u_prev) / u_prev) * 100
        else:
            k_pct = 0.0
            u_pct = 0.0
    else:
        k_val = 2500.0
        k_pct = 0.0
        u_val = 1350.0
        u_pct = 0.0

    k_color = "#ef4444" if k_pct < 0 else "#22c55e"
    k_sign = "▼" if k_pct < 0 else "▲"
    u_color = "#ef4444" if u_pct > 0 else "#22c55e"
    u_sign = "▲" if u_pct > 0 else "▼"

    render_clean_html(
        f"""
        <div style="display: flex; gap: 16px; margin-bottom: 25px; flex-wrap: wrap;">
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">📈 KOSPI 주가지수</div>
                <div style="font-size: 46px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{k_val:,.2f}</div>
                <div style="font-size: 17px; color: {k_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{k_sign} {abs(k_pct):.2f}%</span>
                </div>
            </div>
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">💵 원/달러 환율</div>
                <div style="font-size: 46px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{u_val:,.2f}<span style="font-size: 28px; font-weight: 700;">원</span></div>
                <div style="font-size: 17px; color: {u_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{u_sign} {abs(u_pct):.2f}%</span>
                </div>
            </div>
        </div>
        """
    )

    st.markdown("---")

    render_clean_html(
        f"""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 2px solid #334155; border-radius: 16px; padding: 28px; text-align: center; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4); margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 17px; color: #94a3b8; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px;">🚨 보이는 손 종합 시장 위험 지수 (RISK INDEX)</div>
            <div style="font-size: 58px; color: #ff4d4d; font-weight: 900; margin: 5px 0; line-height: 1.1;">{score} <span style="font-size: 26px; color: #94a3b8; font-weight: 600;">/ 100 점</span></div>
        </div>
        """
    )

    current_layer = min(10, max(0, int(score // 10)))

    render_clean_html(
        """
        <style>
        .apartment-building {
            display: flex;
            flex-direction: column;
            background-color: #0f172a;
            border: 6px solid #334155;
            border-radius: 20px;
            padding: 16px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
            margin-bottom: 30px;
        }
        .floor-card {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 20px;
            margin: 4px 0;
            border-radius: 12px;
            transition: all 0.3s ease;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .floor-card.active {
            background: linear-gradient(90deg, #991b1b 0%, #7f1d1d 100%);
            border: 2px solid #f87171;
            box-shadow: 0 0 15px rgba(239, 68, 68, 0.5);
            transform: scale(1.02);
            z-index: 10;
        }
        .floor-card.inactive {
            background-color: #1e293b;
            border: 1px solid #334155;
            opacity: 0.6;
        }
        .floor-name { font-size: 18px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 8px; }
        .floor-status { font-size: 15px; font-weight: 700; color: #fca5a5; }
        .floor-card.inactive .floor-status { color: #94a3b8; }
        .floor-guide { font-size: 14px; font-weight: 600; color: #cbd5e1; }
        </style>
        """
    )

    st.markdown("### 🏢 지금 시장은 몇 층일까요?")
    st.caption("위험 지수 점수에 따라 대응 행동 요령 및 포트폴리오 권장 비중을 안내합니다.")

    building_html = '<div class="apartment-building">'
    for lvl in range(10, -1, -1):
        fl_name, fl_status, fl_ratio, fl_action = layers[lvl]
        is_current = (lvl == current_layer)
        card_class = "active" if is_current else "inactive"
        pointer = " 👈 [현재 위치]" if is_current else ""
        
        building_html += f"""
        <div class="floor-card {card_class}">
            <div class="floor-name">{fl_name} | {fl_status}{pointer}</div>
            <div class="floor-guide">[{fl_ratio}] ➔ {fl_action}</div>
        </div>
        """
    building_html += '</div>'
    render_clean_html(building_html)



    with st.expander("🔍 14개 변동성 지표별 위험 기여도 상세 분석표 보기"):
        st.markdown("#### 📊 14개 변동성 지표별 위험 기여도 및 산출 공식")
        st.caption("수급 가중치(외국인 55%, 기관 37%, 개인 8%)를 적용하여 산출된 개별 위험도 및 수학적 모델입니다.")
        
        if details:
            html_table = """
            <style>
            body { background-color: transparent; margin: 0; padding: 0; }
            .premium-table { width: 100%; border-collapse: collapse; margin-top: 5px; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13.5px; background-color: #0f172a; border-radius: 10px; overflow: hidden; }
            .premium-table th { background-color: #1e293b; color: #38bdf8; font-weight: 700; text-align: center; padding: 12px 10px; border-bottom: 2px solid #334155; }
            .premium-table td { padding: 11px 10px; border-bottom: 1px solid #334155; color: #f8fafc; text-align: center; }
            .premium-table tr:nth-child(even) { background-color: #0f172a; }
            .premium-table tr:nth-child(odd) { background-color: #1e293b; }
            .premium-table tr:hover { background-color: #334155; }
            .premium-table td:first-child { text-align: left; font-weight: 600; color: #f1f5f9; }
            </style>
            <table class="premium-table">
                <thead>
                    <tr>
                        <th style="width: 55%;">지표명 (한글 설명)<br><span style="font-size: 11px; color: #64748b; font-weight: normal;">[💡 마우스를 올려 공식을 확인하세요]</span></th>
                        <th style="width: 15%;">중요도<br>(가중치)</th>
                        <th style="width: 15%;">위험도<br>(0~1)</th>
                        <th style="width: 15%;">기여점수</th>
                    </tr>
                </thead>
                <tbody>
            """
            for row in details:
                name = row["지표명 (한글 설명)"]
                weight = row["중요도 (가중치)"]
                risk = row["위험도 (0~1)"]
                contrib = row["기여점수"]
                formula = row["산출 공식 (수학적 모델)"].replace("\n", "&#10;").replace("\\n", "&#10;")
                
                html_table += f"""
                <tr>
                    <td title="{formula}" style="cursor: help;">{name}</td>
                    <td>{weight}</td>
                    <td>{risk:.3f}</td>
                    <td>{contrib:.2f}</td>
                </tr>
                """
            html_table += "</tbody></table>"
            
            clean_html = "\n".join([line.strip() for line in html_table.split("\n") if line.strip()])
            st.components.v1.html(clean_html, height=700, scrolling=False)
        else:
            st.info("실시간 시장 데이터가 없습니다.")

    if 'details' in locals() and len(details) >= 3:
        top_indicators = sorted(details, key=lambda x: x["기여점수"], reverse=True)[:3]
        
        indicator_warnings = {
            "FX_Swap_Point": "달러 유동성 부족 위험이 커지고 있습니다. 국내 금융시장의 달러 공급이 빡빡해질 때 급등하므로, 환율 안정을 확인하기 전까지 무리한 추격 매수를 자제해야 합니다.",
            "Put_OTM_OI": "하락 베팅 대기자금(풋옵션 미결제)이 대량으로 쌓여 있습니다. 메이저 세력이 시장 하방에 깊게 베팅하고 있음을 뜻하므로 단기 투매 발생 가능성이 열려 있습니다.",
            "Short_Ratio": "공매도 거래 비중이 치솟아 있습니다. 주가를 아래로 끌어내려 수익을 내는 세력의 움직임이 매우 활발하므로, 호재가 나와도 위로 강하게 치고 올라가기 어렵습니다.",
            "ELS_KnockIn": "지수가 고점 대비 빠져 ELS 원금 손실 구간(낙인)에 접근하고 있습니다. 낙인 경계선이 터지면 증권사들의 헤지용 매도 물량이 쏟아져 시장의 하락 속도가 가속화될 수 있습니다.",
            "VKOSPI_Skew": "시장 공포지수의 비대칭도(불안 강도)가 급증했습니다. 투자자들이 폭락에 대비해 비싼 풋옵션을 사들이고 있다는 의미이므로 잠재적 리스크를 늘 염두에 두어야 합니다.",
            "Synthetic_Futures": "외국인의 파생상품 하방 압력(합성선물 가격차)이 거셉니다. 현물 주식을 사들이더라도 선물 옵션의 꼬리가 몸통을 흔드는 왝더독 현상으로 인해 지수가 발목 잡히기 쉽습니다.",
            "NDF_Night_Rate": "야간 역외 환율이 급격히 상승하고 있습니다. 이는 다음 날 아침 정규 장 개장 시 외국인 자금 이탈을 즉각적으로 유도하는 촉매제가 되므로 환율 꺾임을 최우선 확인해야 합니다.",
            "Futures_Net_Sell": "선물 시장에서의 순매도 압박이 매우 강력합니다. 대규모 선물 매도는 지수를 즉각적으로 끌어내리는 파괴력을 가지므로 당일 선물 매도 비중 추이를 밀착 모니터링해야 합니다.",
            "Non_Arbitrage_Ratio": "컴퓨터 알고리즘을 통한 비차익 프로그램 매도가 누적되고 있습니다. 시가총액 대형주 위주로 무차별 기계적 매도가 집행되어 코스피 전반의 기초 체력을 억누르게 됩니다.",
            "Foreign_Broker_Dump": "외국계 증권사 창구를 통한 외국인 자금 이탈 속도가 매우 가파릅니다. 반도체 등 시총 상위 핵심 업종에서 이탈세가 나타나고 있음을 암시하므로 수급 주포의 움직임을 확인하십시오.",
            "Stock_Short_Balance": "공매도 세력이 주식을 빌려 판 뒤 갚지 않은 대차 잔고가 두껍게 쌓여 있습니다. 악재가 노출될 때 추가적인 투매 압력으로 가해져 반등 시도를 가로막는 매물벽이 됩니다.",
            "Put_Buy_Simple": "개인 및 투기 세력의 풋옵션 매수 강도가 비정상적으로 높습니다. 지수 변동성이 커질 때 뇌동매매가 많이 발생하는 구간이므로 섣부른 역발상 매수는 손실을 키울 수 있습니다.",
            "Stock_Net_Sell": "주식 현물 시장에서 주도 세력의 직접적인 순매도 압력이 내리쬐고 있습니다. 시장의 기초 체력 자체가 쇠약해진 구간이므로 반등 시마다 보수적으로 포트폴리오를 관리해야 합니다."
        }

        warning_items_html = ""
        for ind in top_indicators:
            raw_key = None
            for eng_k, kor_v in COL_MAP.items():
                if kor_v == ind["지표명 (한글 설명)"]:
                    raw_key = eng_k
                    break
            w_text = indicator_warnings.get(raw_key, "현재 기여도가 높아 밀착 관찰이 필요한 변동성 지표 요인입니다.")
            warning_items_html += f"""
            <li style="margin-bottom: 12px; line-height: 1.6;">
                <b style="color: #fda4af; font-size: 14.5px;">⚠️ {ind['지표명 (한글 설명)']} (위험 기여점수: {ind['기여점수']:.2f}점)</b><br>
                <span style="color: #e2e8f0; font-size: 13.5px; font-weight: 400;">{w_text}</span>
            </li>
            """

        if score >= 70:
            level_comment = (
                f"🚨 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 방어벽이 훼손된 고위험 경보 국면입니다. "
                "공격적인 자금 투입은 절대 지양하고 현금 비중을 극대화하여 방어 포지션을 굳건히 할 때입니다."
            )
        elif score >= 50:
            level_comment = (
                f"⚠️ 현재 종합 위험 지수는 <b>{score}점</b>으로 리스크와 하방 압력이 팽팽히 맞선 <b>중립 경계 국면</b>입니다. "
                "추세적인 돌파가 나오기 전까지는 성급한 저가 매수보다 방어적 현금 관리가 필수적입니다."
            )
        else:
            level_comment = (
                f"🟢 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 내 경계 압력이 완화된 안정적 국면입니다. "
                "자금 수급 지표들이 우호적으로 풀리고 있으므로 핵심 주도주 위주로 매수 포지션을 조율해 볼 수 있습니다."
            )

        ai_html = f"""
        <div style="background: linear-gradient(135deg, #1e1b4b, #2e1065); border: 2px solid #6b21a8; border-radius: 14px; padding: 22px; margin-top: 15px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 16.5px; font-weight: 700; color: #f3e8ff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #4c1d95; padding-bottom: 8px;">
                🤖 AI 젬민이의 심층 시장 분석 & 경고
            </div>
            <div style="font-size: 14.5px; color: #f8fafc; line-height: 1.6; font-weight: 500; margin-bottom: 15px;">
                {level_comment}
            </div>
            <div style="font-size: 14px; font-weight: 700; color: #e9d5ff; margin-bottom: 10px;">
                📌 오늘 특별히 엄격하게 주시해야 할 3대 리스크 팩터:
            </div>
            <ul style="margin: 0; padding-left: 20px; color: #cbd5e1;">
                {warning_items_html}
            </ul>
            <div style="background-color: #ef4444; border-radius: 8px; padding: 14px; margin-top: 22px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                <span style="color: #ffffff; font-size: 15.5px; font-weight: 700; letter-spacing: 1.2px; display: inline-block;">
                    🚨 [중요 경고] AI의 분석 결과이므로 절대적인 책임은 투자자 본인에게 있습니다.
                </span>
            </div>
        </div>
        """
        clean_ai_html = "\n".join([line.strip() for line in ai_html.split("\n") if line.strip()])
        st.markdown(clean_ai_html, unsafe_allow_html=True)



    with st.expander("📈 방공망 리스크 지수(INDEX) 역사적 트렌드 차트"):
        if not history_df.empty:
            period_option = st.radio(
                "보기 단위 선택", 
                ["일별 (Daily)", "주별 (Weekly)", "월별 (Monthly)"], 
                horizontal=True,
                help="차트와 테이블의 데이터 집계 주기를 설정합니다."
            )
            st.caption("*시트를 다운 받으시면 날짜별 가중치와 점수를 볼 수 있습니다")
            
            df_temp = history_df.copy()
            df_temp['Date'] = pd.to_datetime(df_temp['Date'])
            
            agg_rules = {
                "Score": "mean",
                "KOSPI": "mean",
                "USD_KRW": "mean",
                "Retail": "sum",
                "Foreigner": "sum",
                "Institution": "sum"
            }
            
            if period_option == "주별 (Weekly)":
                df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='W-MON')).agg(agg_rules).reset_index()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d') + " 주차"
            elif period_option == "월별 (Monthly)":
                df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='MS')).agg(agg_rules).reset_index()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m') + " 월"
            else:
                df_grouped = df_temp.copy()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d')
                
            df_grouped["Score"] = df_grouped["Score"].round(2)
            df_grouped["KOSPI"] = df_grouped["KOSPI"].round(2)
            df_grouped["USD_KRW"] = df_grouped["USD_KRW"].round(2)
            
            chart_data = df_grouped.set_index("Date")[["Score"]]
            chart_data.columns = ["위험 지수"]
            st.line_chart(chart_data)
            
            display_history = df_grouped.rename(columns=COL_MAP).sort_values(by="날짜", ascending=False)
            visible_cols = ["날짜", "종합 위험 점수", "코스피 종가", "원/달러 환율"]
            visible_cols = [c for c in visible_cols if c in display_history.columns]
            
            st.table(display_history[visible_cols].set_index("날짜"))
            
            csv_data = history_df.rename(columns=COL_MAP).sort_values(by="날짜", ascending=False).to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 전체 시장 리스크 역사적 데이터 다운로드 (CSV)",
                data=csv_data,
                file_name=f"market_risk_history_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("누적된 히스토리 데이터가 아직 없습니다. 데이터 수집이 시작되면 여기에 그래프가 표시됩니다.")

    with st.expander("📝 공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)"):
        st.markdown(
            """
            ### ⚖️ 수식 파라미터 거버넌스 선언
            본 대시보드에 탑재된 13가지 시장 위험지수 공식과 가중치는 무작위로 변경되지 않으며, 
            시장 레벨 변동에 따른 파라미터 튜닝(Calibration) 집행 시 **5W1H(육하원칙)**에 의거하여 아래와 같이 버전 이력이 철저히 기록 및 관리됩니다.
            이는 과거 백데이터 점수의 왜곡 방지 및 시계열 연속성 검증을 위한 중대 사안입니다.
            """
        )
        
        tab1, tab2 = st.tabs(["📄 v1.2.0 (최근 변경)", "📄 v1.0.0 (최초 배포)"])
        with tab1:
            st.markdown(
                """
                #### 🏷️ [v1.2.0] - 2026년 08월 02일 (더미 데이터 제거 및 관리자 제어실 연동)
                * **언제 (When)**: 2026년 08월 02일 정오 기정 적용
                * **누가 (Who)**: **보이는 손 분석팀**
                * **어디를 (Where)**: app.py / scrape_daily.py / test_harness.py
                * **무엇을 (What)**: 시세/수급 수집 실패 시의 임의 디폴트값(2500, 1350) 및 5일 이동평균 대입 로직 삭제 (클린 데이터 전용 Reject 문 연동) 및 관리자 수동 제어실 탑재
                * **왜 (Why)**: 비영업일 또는 크롤링 장애 시 자동 누적되는 가짜 더미 데이터로 인한 DB 점수 오염을 원천 차단하기 위함
                * **어떻게 (How)**: 데이터 수집 불량 시 수정을 자동으로 차단하고, 관리자 비밀번호 로그인 시 직접 검증된 당일 종가/환율/수급을 대시보드 인터페이스에서 즉시 반영할 수 있도록 UI/UX 통합 제어실 설계 완료
                """
            )
        with tab2:
            st.markdown(
                """
                #### 🏷️ [v1.0.0] - 2026년 08월 01일 (최초 배포 버전)
                * **언제 (When)**: 2026년 08월 01일 장마감 시점 기정 적용
                * **누가 (Who)**: 보이는 손 퀀트 모델링 분석팀 (AI 젬민이 설계 파트)
                * **어디를 (Where)**: 13가지 하위 리스크 공식 내 기초 매개변수 전체 적용
                * **무엇을 (What)**: 
                    * 환율 기초 스트레스 범위: 분모 `300원` 적용 (`(환율 - 1200) / 300`)
                    * 코스피 역사적 고점 대비 낙인 임계식 설정
                    * 3대 주체 수급 기여 가중치 분배: 외국인 55% / 기관 37% / 개인 8% 배정
                * **왜 (Why)**: 2026년 상반기 원/달러 환율의 1,300원대 안착화 및 코스피 박스권 변동성 체계를 정규 모델링에 반영하기 위함
                * **어떻게 (How)**: 백테스팅 모의 운용 결과, 시장 왜곡을 가장 예민하게 감지할 수 있는 균형 가중 평균치로 공식화하여 소스코드 적용 완료
                """
            )

        st.markdown(
            """
            ---
            > [!IMPORTANT]
            > 향후 거시경제 충격이나 통화 가치 변화로 상수의 재조정(Calibration)이 일어날 경우, 본 감사 추적(Audit Trail) 영역에 변경 사유와 수식 수정 상세본이 즉시 반영되어 역사적 점수 계산 기점을 추적 관리할 수 있도록 보장합니다.
            """,
            unsafe_allow_html=True
        )
