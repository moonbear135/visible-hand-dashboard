import os
import math
import requests
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import streamlit as st
import json
import plotly.express as px

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

FRIENDLY_NAMES = {
    "FX_Swap_Point": "외환 스왑포인트 (달러 유동성 부족 위험)",
    "Put_OTM_OI": "풋옵션 미결제약정 (시장 하락에 배팅한 투기자본)",
    "Short_Ratio": "공매도 거래 비중 (주도권을 쥐어짜려는 매도세)",
    "ELS_KnockIn": "ELS 녹인 위험 (대규모 원금손실 구간 진입 여부)",
    "VKOSPI_Skew": "공포지수 비대칭성 (투자자들의 불안 심리 강도)",
    "Synthetic_Futures": "합성선물 가격차이 (외국인의 파생상품 하방 압력)",
    "NDF_Night_Rate": "야간 환율스왑 변동 (원/달러 환율 급등 위험)",
    "Futures_Net_Sell": "선물 순매도 규모 (선물 지수 하락 압박 투기)",
    "Non_Arbitrage_Ratio": "비차익 프로그램 매도 비중 (컴퓨터 자동 매도세)",
    "Foreign_Broker_Dump": "외국계 증권사 매도세 (외국인 투자자 이탈 속도)",
    "Stock_Short_Balance": "주식 공매도 잔고 (공매도 세력이 아직 갚지 않은 주식수)",
    "Put_Buy_Simple": "풋옵션 매수 강도 (단기 주가 하락 쏠림 배팅 규모)",
    "Stock_Net_Sell": "주식 현물 순매도 규모 (주식을 파는 투자자 자금 규모)",
    "KOSPI_5D_Return": "KOSPI 5일 낙폭 모멘텀 (지수 하락에 따른 직접 지표)"
}

def _load_history_df():
    """읽기 전용으로 누적 이력 CSV 를 로드합니다 (실패 시 빈 DataFrame)."""
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(HISTORY_FILE)
        df = df.rename(columns={v: k for k, v in COL_MAP.items()})
        df["Date"] = df["Date"].astype(str)
        return df
    except Exception as e:
        print(f"Error loading local history: {e}")
        return pd.DataFrame()


def fetch_verified_market_data(override_date=None, override_kospi=None, override_usd=None, override_retail=None, override_fore=None, override_inst=None):
    """
    누적 이력(market_history.csv) 또는 관리자 수동 입력값으로 시장 위험 지표를 산출합니다.

    ⚠️ ENGINEERING_SPEC §0-1 준수:
       실데이터를 불러오지 못하면 KOSPI 2500 / 환율 1350 같은 가짜 시세를 만들지 않고
       score=None 을 반환합니다. 호출부(render_macro_page)는 이 경우 숫자를 전혀 그리지 않고
       빨간 오류 배너만 표시합니다.
    """
    row = None
    volatility = None        # 실측 변동성 (없으면 관련 지표 산출 제외)
    dist_from_high = None    # 52주 고점 대비 낙폭 (없으면 관련 지표 산출 제외)
    unavailable_metrics = [] # 데이터가 없어 산출하지 못한 지표 목록

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
        score = None
        # 관리자는 KOSPI·환율·수급만 입력하므로 변동성/낙폭 기반 지표는 산출할 수 없습니다.
        data_source_log = "⚠️ 관리자 수동 입력 (변동성·고점대비낙폭 미입력 → 해당 지표 제외)"

        if not kospi_close or not usd_close or kospi_close <= 0 or usd_close <= 0:
            return (
                display_date, False,
                "🚨 관리자 입력값이 유효하지 않습니다 (KOSPI 종가·환율은 필수).",
                None, [], _load_history_df()
            )
    else:
        local_loaded = False
        kospi_close = None
        kospi_change = 0.0
        usd_close = None
        usd_change = 0.0
        foreigner_flow = 0
        institution_flow = 0
        retail_flow = 0
        score = None

        target_date = datetime.today()
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
        date_key = target_date.strftime("%Y-%m-%d")
        display_date = target_date.strftime("%Y년 %m월 %d일")
        
        if os.path.exists(HISTORY_FILE):
            try:
                history_df = pd.read_csv(HISTORY_FILE)
                if not history_df.empty:
                    history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
                    history_df["Date"] = history_df["Date"].astype(str)
                    df_sorted = history_df.sort_values(by="Date").reset_index(drop=True)
                    
                    # 항상 가장 최근에 마감된 영업일 데이터(마지막 행)를 DataFrame(1줄)으로 불러옵니다.
                    row = df_sorted.tail(1)
                    latest_row = row.iloc[0]
                    
                    date_key = str(latest_row["Date"])
                    display_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
                    
                    score = float(latest_row["Score"])
                    kospi_close = float(latest_row["KOSPI"])
                    usd_close = float(latest_row["USD_KRW"])
                    retail_flow = int(latest_row["Retail"])
                    foreigner_flow = int(latest_row["Foreigner"])
                    institution_flow = int(latest_row["Institution"])
                    
                    idx = df_sorted.index[-1]
                    if idx > 0:
                        prev_row = df_sorted.iloc[idx - 1]
                        prev_k = float(prev_row["KOSPI"])
                        prev_u = float(prev_row["USD_KRW"])
                        if prev_k != 0:
                            kospi_change = (kospi_close - prev_k) / prev_k
                        if prev_u != 0:
                            usd_change = (usd_close - prev_u) / prev_u
                    
                    local_loaded = True
            except Exception as e:
                print(f"Error loading local history: {e}")

        is_live_connected = False
        if local_loaded:
            try:
                mtime = os.path.getmtime(HISTORY_FILE)
                sync_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                data_source_log = f"✅ 최종 동기화: {sync_time}"
            except Exception:
                data_source_log = "✅ 마감 데이터 기준"
        else:
            # 🚨 실데이터 없음 → 가짜 시세(2500/1350)로 점수를 만들지 않고 실패를 그대로 반환
            return (
                display_date, False,
                "🚨 시장 데이터를 불러오지 못했습니다 (market_history.csv 없음 또는 손상). 수치를 표시하지 않습니다.",
                None, [], _load_history_df()
            )

    # =====================================================================
    # 지표 산출 — 입력이 없는 지표는 '중립값 0.5'를 넣지 않고 산출 대상에서 제외합니다.
    # =====================================================================
    fx_base = 0.5 + 0.3 * (usd_close - 1200) / 300
    put_base = 0.5 - 0.4 * kospi_change
    short_base = (0.4 + 0.4 * (volatility / 5.0)) if volatility is not None else None
    els_base = (0.1 + 0.7 * dist_from_high) if dist_from_high is not None else None
    skew_base = (0.4 + 0.4 * (volatility / 5.0) - 0.2 * kospi_change) if volatility is not None else None
    synth_base = 0.5 + 0.3 * (usd_close - 1300) / 200
    ndf_base = 0.4 + 0.5 * usd_change
    fut_base = 0.5 - 0.3 * kospi_change
    non_base = 0.5 + (0.2 if institution_flow < 0 else -0.1)
    dump_base = 0.5 + (0.3 if foreigner_flow < 0 else -0.2)
    bal_base = (0.5 + 0.3 * dist_from_high) if dist_from_high is not None else None
    put_buy_base = 0.4 - 0.3 * kospi_change
    stock_net_base = 0.5

    # KOSPI 5일 모멘텀: 누적 이력에서 5영업일 전 종가를 실제로 조회해 산출합니다.
    # (과거 버전은 정의되지 않은 변수 kospi_df 를 참조해 항상 NameError → 0.5 고정이었습니다.)
    kospi_5d_base = None
    try:
        hist_for_5d = _load_history_df()
        if not hist_for_5d.empty and "KOSPI" in hist_for_5d.columns:
            hist_sorted = hist_for_5d.sort_values(by="Date").reset_index(drop=True)
            past = hist_sorted[hist_sorted["Date"] <= str(date_key)]
            if len(past) >= 6:
                k_5d_prev = float(past.iloc[-6]["KOSPI"])
                if k_5d_prev > 0:
                    kospi_5d_base = 0.5 - 2.5 * ((kospi_close - k_5d_prev) / k_5d_prev)
    except Exception as e:
        print(f"⚠️ KOSPI 5일 모멘텀 산출 실패: {e}")
        kospi_5d_base = None

    weights = {
        "FX_Swap_Point": 10.0, "Put_OTM_OI": 9.0, "Short_Ratio": 9.0,
        "ELS_KnockIn": 8.0, "VKOSPI_Skew": 8.0, "Synthetic_Futures": 8.0,
        "NDF_Night_Rate": 8.0, "Futures_Net_Sell": 7.0, "Non_Arbitrage_Ratio": 7.0,
        "Foreign_Broker_Dump": 6.0, "Stock_Short_Balance": 6.0, "Put_Buy_Simple": 5.0,
        "Stock_Net_Sell": 4.0, "KOSPI_5D_Return": 5.0
    }

    # (중복 정의였던 friendly_names 사전 제거 — 표기는 모듈 상단 FRIENDLY_NAMES 로 일원화)

    formulas = {
        "FX_Swap_Point": "0.55 × clip(0.5 + 0.3×(USD-1200)/300 + 0.1×USD_change) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Put_OTM_OI": "0.55 × clip(0.5 - 0.4×KOSPI_change + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base + Ret_Sign)",
        "Short_Ratio": "0.55 × clip(0.4 + 0.4×(Vol/5) + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base - 0.2)",
        "ELS_KnockIn": "0.55 × clip(0.1 + 0.7×Dist_High) + 0.37 × clip(base + 0.1) + 0.08 × clip(base - 0.1)",
        "VKOSPI_Skew": "0.55 × clip(0.4 + 0.4×(Vol/5) - 0.2×KOSPI_change + 0.05) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Synthetic_Futures": "0.55 × clip(0.5 + 0.3×(USD-1300)/200 + Fore_Sign) + 0.37 × clip(base) + 0.08 × clip(base + Ret_Sign)",
        "NDF_Night_Rate": "0.55 × clip(0.4 + 0.5×USD_change + 0.1) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Futures_Net_Sell": "0.55 × clip(0.5 - 0.3×KOSPI_change + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base + Ret_Sign)",
        "Non_Arbitrage_Ratio": "Base = 0.5 + (기관 순매도시 +0.2 / 순매수시 -0.1)",
        "Foreign_Broker_Dump": "Base = 0.5 + (외인 순매도시 +0.3 / 순매수시 -0.2)",
        "Stock_Short_Balance": "0.55 × clip(0.5 + 0.3×Dist_High + 0.05) + 0.37 × clip(base + 0.05) + 0.08 × clip(base - 0.2)",
        "Put_Buy_Simple": "0.55 × clip(0.4 - 0.3×KOSPI_change + Fore_Sign) + 0.37 × clip(base) + 0.08 × clip(base + Ret_Sign)",
        "Stock_Net_Sell": "Base = 0.5 + (수급 주체 순매도시 +0.3 / 순매수시 -0.3)",
        "KOSPI_5D_Return": "clip(0.5 - 2.5 × KOSPI_5D_Return)"
    }

    sub_scores = {}
    extreme_signal_count = 0
    investor_weights = {"Foreigner": 0.55, "Institution": 0.37, "Retail": 0.08}

    if not local_loaded:
        def clip(val):
            return min(1.0, max(0.0, val))

        # 입력이 없는(None) 지표는 아래에서 통째로 제거되어 가중평균에서 제외됩니다.
        market_scores_raw = {
            "FX_Swap_Point": {"Foreigner": clip(fx_base + 0.1 * usd_change), "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)},
            "Put_OTM_OI": {"Foreigner": clip(put_base + (0.1 if foreigner_flow < 0 else -0.1)), "Institution": clip(put_base + (0.05 if institution_flow < 0 else -0.05)), "Retail": clip(put_base + (0.15 if retail_flow > 0 else -0.1))},
            "Short_Ratio": None if short_base is None else {"Foreigner": clip(short_base + (0.1 if foreigner_flow < 0 else -0.05)), "Institution": clip(short_base + (0.05 if institution_flow < 0 else -0.05)), "Retail": clip(short_base - 0.2)},
            "ELS_KnockIn": None if els_base is None else {"Foreigner": clip(els_base), "Institution": clip(els_base + 0.1), "Retail": clip(els_base - 0.1)},
            "VKOSPI_Skew": None if skew_base is None else {"Foreigner": clip(skew_base + 0.05), "Institution": clip(skew_base), "Retail": clip(skew_base - 0.2)},
            "Synthetic_Futures": {"Foreigner": clip(synth_base + (0.15 if foreigner_flow < 0 else -0.1)), "Institution": clip(synth_base), "Retail": clip(synth_base + (0.05 if retail_flow > 0 else -0.05))},
            "NDF_Night_Rate": {"Foreigner": clip(ndf_base + 0.1), "Institution": clip(ndf_base), "Retail": clip(ndf_base - 0.2)},
            "Futures_Net_Sell": {"Foreigner": clip(fut_base + (0.2 if foreigner_flow < 0 else -0.15)), "Institution": clip(fut_base + (0.1 if institution_flow < 0 else -0.1)), "Retail": clip(fut_base + (0.15 if retail_flow > 0 else -0.1))},
            "Non_Arbitrage_Ratio": {"Foreigner": clip(non_base + 0.05), "Institution": clip(non_base + 0.1), "Retail": clip(non_base - 0.2)},
            "Foreign_Broker_Dump": {"Foreigner": clip(dump_base + 0.15), "Institution": clip(dump_base - 0.1), "Retail": clip(dump_base - 0.3)},
            "Stock_Short_Balance": None if bal_base is None else {"Foreigner": clip(bal_base + 0.05), "Institution": clip(bal_base + 0.05), "Retail": clip(bal_base - 0.2)},
            "Put_Buy_Simple": {"Foreigner": clip(put_buy_base + (0.05 if foreigner_flow < 0 else -0.05)), "Institution": clip(put_buy_base), "Retail": clip(put_buy_base + (0.1 if retail_flow > 0 else -0.1))},
            "Stock_Net_Sell": {"Foreigner": clip(stock_net_base + (0.3 if foreigner_flow < 0 else -0.3)), "Institution": clip(stock_net_base + (0.2 if institution_flow < 0 else -0.2)), "Retail": clip(stock_net_base + (0.3 if retail_flow < 0 else -0.3))},
            "KOSPI_5D_Return": None if kospi_5d_base is None else {"Foreigner": clip(kospi_5d_base), "Institution": clip(kospi_5d_base), "Retail": clip(kospi_5d_base)}
        }

        market_scores = {k: v for k, v in market_scores_raw.items() if v is not None}
        unavailable_metrics = [k for k, v in market_scores_raw.items() if v is None]

        total_weighted_risk = 0.0
        available_weight = sum(w for k, w in weights.items() if k in market_scores)

        for item, w in weights.items():
            if item not in market_scores:
                sub_scores[item] = None   # 데이터 없음 → 중립값(50점) 대입 금지
                continue
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

        if available_weight <= 0:
            return (
                display_date, False,
                "🚨 산출 가능한 위험 지표가 하나도 없습니다. 종합 위험 점수를 표시하지 않습니다.",
                None, [], _load_history_df()
            )

        base_score = (total_weighted_risk / available_weight) * 100.0

        multiplier = 1.0
        if extreme_signal_count >= 5:
            multiplier = 1.3
        elif extreme_signal_count >= 3:
            multiplier = 1.15

        if base_score > 50.0:
            final_score = 50.0 + (base_score - 50.0) * multiplier
        else:
            final_score = base_score + (extreme_signal_count * 2.5)

        score = round(max(0.0, min(100.0, final_score)), 1)
    else:
        for item, w in weights.items():
            val = None
            if row is not None and item in row.columns:
                try:
                    raw_val = row.iloc[0][item]
                    val = None if pd.isna(raw_val) else float(raw_val)
                except (TypeError, ValueError):
                    val = None
            if val is None:
                sub_scores[item] = None   # 컬럼 결측 → "데이터 없음" (0.5 중립값 대입 금지)
                unavailable_metrics.append(item)
            else:
                sub_scores[item] = round(val * 100.0, 1)
                if val >= 0.75:
                    extreme_signal_count += 1
        try:
            score = float(row.iloc[0]["Score"])
        except (TypeError, ValueError, KeyError):
            score = None

    details = []
    for item, w in weights.items():
        sub_score_val = sub_scores.get(item)
        display_risk = None if sub_score_val is None else round(sub_score_val / 100.0, 3)
        details.append({
            "지표명 (한글 설명)": FRIENDLY_NAMES.get(item, item),
            "중요도 (가중치)": w,
            "위험도 (0~1)": display_risk,
            "기여점수": None if display_risk is None else round(w * display_risk, 2),
            "산출 공식 (수학적 모델)": formulas.get(item, "")
        })

    details = sorted(details, key=lambda x: x["중요도 (가중치)"], reverse=True)

    metrics_dict = {}
    for item in weights.keys():
        if sub_scores.get(item) is not None:
            metrics_dict[item] = sub_scores[item] / 100.0
    # 산출하지 못한 지표는 metrics_dict 에 넣지 않습니다 → CSV 에도 값이 기록되지 않음(결측 유지)

    # SPEC §6: 표현 계층(조회 화면)은 DB를 쓰지 않습니다.
    # 관리자 수동 입력(override) 으로 새 데이터가 들어온 경우에만 저장합니다.
    if override_date is not None:
        history_df = save_and_load_history(date_key, score, kospi_close, usd_close, retail_flow, foreigner_flow, institution_flow, metrics_dict)
    else:
        history_df = _load_history_df()

    if local_loaded:
        is_live_connected = True

    if unavailable_metrics:
        data_source_log += f" | ⚠️ 산출 불가 지표 {len(unavailable_metrics)}개 (가중평균에서 제외)"

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

    # 🚨 실데이터 로드 실패: 가짜 수치를 그리지 않고 여기서 렌더링을 중단합니다.
    if score is None:
        st.error(
            f"🚨 {log_msg}\n\n"
            "가짜 기본값(KOSPI 2,500 / 환율 1,350 등)으로 화면을 채우지 않기 위해 "
            "위험 점수·지표·차트를 표시하지 않습니다. 자동 수집(GitHub Actions)이 정상 동작했는지 확인해 주세요."
        )
        if admin_mode:
            st.info("⚙️ [관리자] 사이드바에서 로그인 후, 위 '관리자 수동 제어실'에서 당일 데이터를 직접 입력할 수 있습니다.")
        st.stop()

    if admin_mode:
        st.write(f"📊 **[관리자] 로드된 데이터 행 개수:** `{len(history_df)}`개")

    # 데이터 신선도(staleness) 검사 — 오래된 CSV를 '실시간'으로 표기하지 않습니다.
    stale_days = None
    try:
        latest_date = pd.to_datetime(history_df["Date"]).max()
        stale_days = (pd.Timestamp(datetime.today().date()) - latest_date.normalize()).days
    except Exception:
        stale_days = None

    if stale_days is not None and stale_days >= 3:
        st.warning(
            f"⚠️ 최신 시장 데이터가 **{stale_days}일 전({latest_date.strftime('%Y-%m-%d')})** 기준입니다. "
            "자동 수집이 멈춰 있을 수 있으니 아래 수치는 최신이 아닙니다."
        )
        is_live = False

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
        
        clean_status = user_log_msg.split('|')[0].strip()
        if is_live:
            st.success(f"{clean_status}")
        else:
            st.info(f"{clean_status}")
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
            k_diff = k_val - k_prev
            k_pct = (k_diff / k_prev) * 100 if k_prev != 0 else 0.0
            u_prev = float(prev_row["USD_KRW"])
            u_diff = u_val - u_prev
            u_pct = (u_diff / u_prev) * 100 if u_prev != 0 else 0.0
        else:
            k_diff = 0.0
            k_pct = 0.0
            u_diff = 0.0
            u_pct = 0.0
    else:
        # 이력이 비어 있으면 임의 시세(2500 / 1350)를 그리지 않고 '데이터 없음'으로 표기합니다.
        k_val = None
        k_diff = None
        k_pct = None
        u_val = None
        u_diff = None
        u_pct = None

    k_color = "#ef4444" if (k_diff is not None and k_diff < 0) else "#22c55e"
    k_sign = "▼" if (k_diff is not None and k_diff < 0) else "▲"
    u_color = "#ef4444" if (u_diff is not None and u_diff > 0) else "#22c55e"
    u_sign = "▲" if (u_diff is not None and u_diff > 0) else "▼"

    def format_val(val, fmt="{:,.2f}"):
        if val is None or pd.isna(val):
            return "데이터 없음"
        return fmt.format(val)

    k_val_str = format_val(k_val)
    u_val_str = format_val(u_val)
    k_diff_str = f"{k_sign} {abs(k_diff):.2f} ({abs(k_pct):.2f}%)" if (k_val is not None and k_diff is not None and not pd.isna(k_val)) else "-"
    u_diff_str = f"{u_sign} {abs(u_diff):.2f} ({abs(u_pct):.2f}%)" if (u_val is not None and u_diff is not None and not pd.isna(u_val)) else "-"

    render_clean_html(
        f"""
        <div style="display: flex; gap: 16px; margin-bottom: 25px; flex-wrap: wrap;">
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">📈 KOSPI 주가지수</div>
                <div style="font-size: {46 if k_val is not None else 26}px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{k_val_str}</div>
                <div style="font-size: 17px; color: {k_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{k_diff_str}</span>
                </div>
            </div>
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">💵 원/달러 환율</div>
                <div style="font-size: {46 if u_val is not None else 26}px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{u_val_str}<span style="font-size: 28px; font-weight: 700;">{"원" if u_val is not None else ""}</span></div>
                <div style="font-size: 17px; color: {u_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{u_diff_str}</span>
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

    # 표본 부족 경고 — Z-Score 정규화는 이력이 충분히 쌓여야 의미가 생깁니다.
    if len(history_df) < 20:
        st.warning(
            f"⚠️ 누적 이력이 **{len(history_df)}일치**뿐이라 점수 정규화(Z-Score) 표본이 부족합니다. "
            "지표별 점수가 0점/100점으로 튈 수 있으니 절대값보다 추세로 참고해 주세요. (권장 표본: 20일 이상)"
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
        st.info(
            "ℹ️ **지표 산출 방식 안내** — 아래 14개 수치는 실제 파생상품·공매도 시장에서 직접 수집한 값이 아니라, "
            "**KOSPI 종가 · 원/달러 환율 · 두 값의 전일 대비 변화율 · 투자자 3주체 수급** 5개 실측값으로부터 "
            "위 '산출 공식'에 따라 계산한 **추정 프록시(대용치)** 입니다. "
            "'데이터 없음'으로 표시된 지표는 입력값이 없어 산출하지 못한 것이며, 종합 점수의 가중평균에서도 제외됩니다."
        )
        n_missing = len([d for d in details if d["위험도 (0~1)"] is None])
        if n_missing:
            st.warning(f"⚠️ 14개 중 {n_missing}개 지표를 산출하지 못했습니다 (아래 표에 '데이터 없음'으로 표기).")

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

                risk_str = "데이터 없음" if risk is None else f"{risk:.3f}"
                contrib_str = "산출 불가" if contrib is None else f"{contrib:.2f}"
                row_style = ' style="color:#94a3b8;"' if risk is None else ""

                html_table += f"""
                <tr{row_style}>
                    <td title="{formula}" style="cursor: help;">{name}{' <span style="color:#f97316;">(데이터 없음)</span>' if risk is None else ''}</td>
                    <td>{weight:.2f}</td>
                    <td>{risk_str}</td>
                    <td>{contrib_str}</td>
                </tr>
                """
            html_table += "</tbody></table>"
            
            clean_html = "\n".join([line.strip() for line in html_table.split("\n") if line.strip()])
            st.components.v1.html(clean_html, height=700, scrolling=False)
        else:
            st.info("실시간 시장 데이터가 없습니다.")

    if 'details' in locals() and len(details) > 0:
        sorted_details = sorted(details, key=lambda x: (x["위험도 (0~1)"] is not None, x["위험도 (0~1)"] or 0), reverse=True)

        ai_comments_data = {}
        ai_comment_dates = {}
        ai_commentary_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "macro_commentary.json"
        )
        if os.path.exists(ai_commentary_file):
            try:
                with open(ai_commentary_file, "r", encoding="utf-8") as f:
                    _ai_payload = json.load(f)
                ai_comments_data = _ai_payload.get("comments", {})
                ai_comment_dates = _ai_payload.get("comment_dates", {})
            except Exception as e:
                print(f"⚠️ AI 코멘트 파일 로드 실패: {e}")
                st.warning(f"⚠️ AI 코멘트 파일을 읽지 못했습니다: {e}")

        today_str_kr = datetime.today().strftime("%Y-%m-%d")
        warning_items_html = ""
        for ind in sorted_details:
            raw_key = None
            for eng_k, kor_v in FRIENDLY_NAMES.items():
                if kor_v == ind["지표명 (한글 설명)"]:
                    raw_key = eng_k
                    break

            risk = ind["위험도 (0~1)"]
            w_text = ai_comments_data.get(raw_key, "AI 코멘트가 준비되지 않았습니다.")

            # 오늘 생성된 코멘트가 아니면 '언제 것인지' 반드시 표시 (전일 코멘트를 오늘 것처럼 쓰지 않음)
            c_date = ai_comment_dates.get(raw_key)
            if raw_key in ai_comments_data:
                if c_date and c_date != today_str_kr:
                    w_text = f"<span style='color:#fbbf24;'>⚠️ ({c_date} 생성 코멘트)</span> {w_text}"
                elif not c_date:
                    w_text = f"<span style='color:#94a3b8;'>ℹ️ (생성 일자 미기록)</span> {w_text}"

            if risk is None:
                icon = "⚪"
                color = "#94a3b8"
                risk_label = "위험도: 데이터 없음 (산출 불가)"
            else:
                risk_label = f"위험도: {risk:.2f}"
                if risk >= 0.65:
                    icon = "🔴"
                    color = "#fca5a5"
                elif risk >= 0.35:
                    icon = "🟡"
                    color = "#fde047"
                else:
                    icon = "🟢"
                    color = "#86efac"

            warning_items_html += f'''
            <li style="margin-bottom: 12px; line-height: 1.5; list-style-type: none;">
                <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                    <span style="font-size: 14px;">{icon}</span>
                    <b style="color: {color}; font-size: 14.5px;">{ind['지표명 (한글 설명)']} ({risk_label})</b>
                </div>
                <div style="color: #cbd5e1; font-size: 13.5px; font-weight: 400; padding-left: 24px;">{w_text}</div>
            </li>
            '''
        if score >= 85:
            level_comment = (
                f"🔥 현재 종합 위험 지수는 <b>{score}점</b>으로 시장이 <b>극단적 패닉 상태(Extreme Danger)</b>에 진입했습니다. "
                "시스템 리스크 발현 가능성이 매우 높으므로, 보유 주식의 반등을 이용한 기계적 비중 축소와 생존을 최우선으로 해야 할 구간입니다."
            )
        elif score >= 70:
            level_comment = (
                f"🚨 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 방어벽이 훼손된 <b>고위험 경보 국면</b>입니다. "
                "공격적인 자금 투입은 절대 지양하고 현금 비중을 극대화하여 방어 포지션을 굳건히 할 때입니다."
            )
        elif score >= 50:
            level_comment = (
                f"⚠️ 현재 종합 위험 지수는 <b>{score}점</b>으로 리스크와 하방 압력이 팽팽히 맞선 <b>중립 경계 국면</b>입니다. "
                "추세적인 돌파가 나오기 전까지는 성급한 저가 매수보다 방어적 현금 관리가 필수적입니다."
            )
        elif score >= 30:
            level_comment = (
                f"✅ 현재 종합 위험 지수는 <b>{score}점</b>으로 시장이 전반적으로 <b>안정적인 흐름</b>을 유지하고 있습니다. "
                "하방 위험이 통제되고 있으므로, 실적 가시성이 높은 업종 위주로 점진적 비중 확대를 고려해볼 수 있습니다."
            )
        else:
            level_comment = (
                f"🌈 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 내 공포 심리가 거의 없는 <b>매우 안전한 구간(Safe Zone)</b>입니다. "
                "단, 지나친 안도감은 오히려 차익실현 빌미가 될 수 있으므로, 펀더멘털을 동반하지 않은 급등주 추격 매수만 주의한다면 우호적인 투자 환경입니다."
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
                📊 14개 매크로 방공망 지표별 AI 심층 코멘트:
            </div>
            <ul style="margin: 0; padding-left: 20px; color: #cbd5e1;">
                {warning_items_html}
            </ul>
            <div style="background-color: #ef4444; border-radius: 8px; padding: 14px; margin-top: 22px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                <span style="color: #ffffff; font-size: 15.5px; font-weight: 700; letter-spacing: 1.2px; display: inline-block;">
                    🚨 [투자 주의 경고 및 AI 분석 안내]
                </span>
                <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
                    본 리포트의 수치 및 분석 결과는 공시된 재무제표와 시장 데이터를 기반으로 AI 퀀트 알고리즘이 자동 계산한 단순 참고용 정보입니다. 특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
                </div>
                <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
                    ⚠️ 모든 투자 결정과 그에 따른 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있음을 명시합니다.
                </div>
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
            df_temp = df_temp.sort_values('Date')
            
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
            # 참고: st.line_chart 는 내부적으로 altair(vega-lite)를 거치는데,
            # 배포 환경의 altair/Python 조합에서 TypedDict(closed=True) 관련 TypeError가
            # 발생하는 문제가 있어(altair 자체 버그, 우리 데이터와 무관), altair 의존 없이
            # 렌더링되는 Plotly로 대체했습니다.
            fig = px.line(chart_data.reset_index(), x="Date", y="위험 지수")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
            st.plotly_chart(fig, use_container_width=True)
            
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
            본 대시보드에 탑재된 14가지 시장 위험지수 공식과 가중치는 무작위로 변경되지 않으며, 
            시장 레벨 변동에 따른 파라미터 튜닝(Calibration) 집행 시 **5W1H(육하원칙)**에 의거하여 아래와 같이 버전 이력이 철저히 기록 및 관리됩니다.
            이는 과거 백데이터 점수의 왜곡 방지 및 시계열 연속성 검증을 위한 중대 사안입니다.
            """
        )
        
        tab0, tab1, tab2, tab3 = st.tabs(
            ["📄 v1.4.0 (데이터 무결성 감사 반영)", "📄 v1.3.1 (로직 원복)", "📄 v1.2.0 (더미 제거 시도)", "📄 v1.0.0 (최초 배포)"]
        )

        with tab0:
            st.markdown(
                """
                #### 🏷️ [v1.4.0] - 2026년 08월 05일 (하드코딩·더미 데이터 전면 제거)
                * **언제 (When)**: 2026년 08월 05일 데이터 무결성 감사(AUDIT_REPORT.md) 후속 조치
                * **누가 (Who)**: 보이는 손 엔지니어링 감사 (Claude Opus 정밀 점검)
                * **어디를 (Where)**: `collector_kospi200.py` / `views/macro_view.py` / `views/pegy_view.py` / `utils/*.py`
                * **무엇을 (What)**:
                    * 매크로 화면의 **KOSPI 2,500 / 환율 1,350 하드코딩 폴백 완전 삭제** (데이터 없으면 오류 배너 + 렌더링 중단)
                    * 종목코드 해시(`code_hash % 3`)로 만들던 **가짜 변동성 판정 삭제** → 실제 20일 수익률 표준편차로 대체, 산출 불가 시 벌점 없음
                    * Forward ROE / ROIC 상수(8.5 / 6.8) 및 t_roe 파생값 삭제 → **'데이터 없음' 표기 + 배점에서 제외**
                    * 성장률을 ROE 파생값이 아닌 **네이버 실측 추정EPS vs TTM EPS 증감률**로 재산출
                    * 자사주 매입 2.5% 가정 삭제 → 주주환원율은 **배당수익률만** 반영
                    * 상장주식수 파싱에 **범위 검증(100만 주 미만 거부)** 도입 → '총 0억원' 오표기 차단
                    * 지표 결측 시 0.5(중립) 대입 금지 → **가중평균에서 제외 + 표에 '데이터 없음' 표기**
                * **왜 (Why)**: 실패한 수집을 그럴듯한 숫자로 덮으면 어디가 잘못됐는지 영원히 알 수 없기 때문 (ENGINEERING_SPEC §0-1)
                * **어떻게 (How)**: 모든 실패 경로에서 `None` 반환 → UI에 '데이터 없음/산출 불가' 노출, 배치 수집기는 예외로 중단
                """
            )

        with tab1:
            st.markdown(
                """
                #### 🏷️ [v1.3.1] - 2026년 08월 03일 (계산 공식 원복 및 점수 안정화)
                * **언제 (When)**: 2026년 08월 03일 심야 시스템 패치 적용
                * **누가 (Who)**: **보이는 손 AI 분석팀**
                * **어디를 (Where)**: collector_kospi200.py / views/macro_view.py
                * **무엇을 (What)**: 14개 지표 가중치 강제 정규화 로직 취소 및 적정가(f_target) 계산 공식 롤백
                * **왜 (Why)**: 가중치를 강제로 비례 축소하고 목표주가 연동 공식을 임의 변경한 결과, 적정가 대비 과도한 갭이 발생하여 종합 점수가 비정상적으로 튀는 왜곡 현상이 감지되었기 때문
                * **어떻게 (How)**: 클로드가 최초 설계했던 안정적인 계산 공식(Target PER 10.4 고정 배수) 및 100점 합산 가중치 정수로 완벽하게 롤백(Revert)하여 점수 정합성을 복구함
                """
            )
        with tab2:
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
        with tab3:
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
