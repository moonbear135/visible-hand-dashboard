import os
import json
import random
from datetime import datetime
import pandas as pd
import streamlit as st

def get_kospi200_pegy_data():
    """Fallback generator for KOSPI 200 datasets"""
    from collector_kospi200 import run_kospi200_collector
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "kospi200_pegy_latest.json")
    if not os.path.exists(json_path):
        run_kospi200_collector()
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
                return payload.get("stocks", [])
        except Exception:
            pass
    return []

def load_kospi200_snapshot():
    """data/kospi200_pegy_latest.json 스냅샷 로드 및 메타데이터 반환"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")
    
    if not os.path.exists(json_path):
        try:
            from collector_kospi200 import run_kospi200_collector
            run_kospi200_collector()
        except Exception as e:
            print(f"Initial collector run exception: {e}")
            
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
                meta = payload.get("metadata", {})
                stocks = payload.get("stocks", [])
                return meta, stocks
        except Exception as e:
            print(f"Error reading JSON snapshot: {e}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {"last_updated_at": now_str, "status": "BACKUP"}, []

def load_pegy_summary_history():
    """data/pegy_summary_history.json 누적 수치 이력을 로드합니다."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    history_path = os.path.join(data_dir, "pegy_summary_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def render_pegy_page():
    """'💡 사실 이 가격이에요' (배치 수집 JSON 동적 요약 지표 & 누적 히스토리 연동) 화면 렌더링"""
    
    # 1. JSON 스냅샷 및 메타데이터 연동
    metadata, all_stocks = load_kospi200_snapshot()
    last_updated_at = metadata.get("last_updated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    summary_history = load_pegy_summary_history()

    # 관리자 로그인 여부 확인
    is_admin = st.session_state.get("admin_mode", False)

    # 2. 툴팁 전용 CSS 주입
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
            width: 330px;
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
            line-height: 1.55;
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
    
    # 3. 상단 그라데이션 타이틀
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 18px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #d97706; margin: 0 0 8px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">KOSPI 200개 종목 Trailing vs Forward PEGY & 100점 만점 퀀트 종합점수 리포트</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 4. 대시보드 상단 배치 동기화 배너 (metadata.last_updated_at 활용)
    st.markdown(
        f"""
        <div style="background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #0284c7; border-radius: 10px; padding: 12px 20px; margin-bottom: 22px; text-align: center; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.25); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <span style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">
                📅 마지막 동기화: {last_updated_at} (장 마감 반영)
            </span>
            <span style="font-size: 13px; color: #94a3b8; margin-left: 14px; font-weight: 600;">
                • 배치 수집 스냅샷 (200개 KOSPI 대표 종목 연동 완료)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 5. 최신 200개 종목 동기화 데이터 및 누적 히스토리 기반 동적 요약 지표 산출
    if all_stocks:
        f_per_list = [s['f_per'] for s in all_stocks if s.get('f_per', 0) > 0]
        growth_list = [min(s.get('growth', 0), 35.0) for s in all_stocks]
        pegy_list = [s.get('f_pegy', 0) for s in all_stocks if s.get('f_pegy', 0) > 0]

        calc_f_per = round(pd.Series(f_per_list).median(), 1) if f_per_list else 10.4
        calc_growth = round(sum(growth_list) / max(len(growth_list), 1), 1) if growth_list else 14.2
        calc_pegy = round(pd.Series(pegy_list).median(), 2) if pegy_list else 0.73
    else:
        calc_f_per = 10.4
        calc_growth = 14.2
        calc_pegy = 0.73

    # 누적 히스토리 기반 증감 변동분(Delta) 계산
    f_per_delta_str = "KOSPI 200 실시간 중앙값"
    growth_delta_str = "실시간 평균 컨센서스"

    if len(summary_history) >= 2:
        prev = summary_history[-2]
        diff_per = round(calc_f_per - prev.get("f_per", calc_f_per), 1)
        diff_growth = round(calc_growth - prev.get("growth", calc_growth), 1)
        
        f_per_delta_str = f"{diff_per:+.1f}배 (이전 동기화 대비)"
        growth_delta_str = f"{diff_growth:+.1f}%p (이전 동기화 대비)"

    if calc_pegy < 0.85:
        pegy_status = "🟢 저평가 수용 구간"
    elif calc_pegy < 1.15:
        pegy_status = "🟡 적정 밸류 구간"
    else:
        pegy_status = "🔴 고평가 관망 구간"

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 중앙 Forward PER", f"{calc_f_per} 배", f_per_delta_str)
    with col2:
        st.metric("코스피 대표 EPS 성장률 (Cap 35%)", f"{calc_growth} %", growth_delta_str)
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", f"{calc_pegy}", pegy_status)

    st.markdown("---")

    # 6. 상단 검색 및 필터 컨트롤 + 줄간격 보정 가이드 박스
    f_col1, f_col2, f_col3 = st.columns([2, 3, 2.2])
    with f_col1:
        search_query = st.text_input("🔍 종목명 / 종목코드 검색", placeholder="예: 삼성전자, 005930").strip()
    with f_col2:
        all_badge_options = [
            "🟢 강력 저평가", "🟢 저평가", "🟡 적정가 형성", 
            "🟡 목표가 달성 (적정가)", "🔴 고평가 관망", 
            "🔴 목표가 초과 (고평가 관망)", "🔴 극단적 고평가 (위험)"
        ]
        selected_badges = st.multiselect(
            "🏷️ 밸류에이션 상태 필터",
            all_badge_options,
            default=all_badge_options
        )
    with f_col3:
        only_value_trap = st.checkbox(
            "⚠️ '착시 저평가' 주의 종목만 보기", 
            value=False,
            help="주가가 PER 수치상 싸 보이지만, 실제 이익창출력(ROE<8% 또는 ROIC<6%)이 낮아 오랜 기간 주가가 오르지 못하고 갇히는 위험 종목입니다."
        )

    # 줄간격 및 수평 여백이 보정된 넉넉한 가이드 박스
    guide_box_html = """
    <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #0284c7; border-radius: 12px; padding: 16px 22px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="font-size: 15px; font-weight: 800; color: #38bdf8; margin-bottom: 10px;">
            💡 '착시 저평가 (가치주 덫)' 및 100점 만점 퀀트 스코어 가이드
        </div>
        <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65; margin-bottom: 8px;">
            • <b style="color: #fef08a;">🏆 100점 만점 퀀트 스코어 (quant_score)</b>: PEGY(35점) + ROE/ROIC(30점) + 주주환원(20점) + Trailing(10점) + 변동성(5점)을 합산하여 종합 점수를 매깁니다. (단, 현재가가 목표가를 초과했거나 PEGY &ge; 2.0 시 <b>목표가 달성 적정가/고평가 교차검증</b> 적용)
        </div>
        <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65;">
            • <b style="color: #fca5a5;">⚠️ 착시 저평가</b>: 주가가 단순히 PER 5배~7배로 싸 보이지만 실제 이익창출력(ROE&lt;8% 또는 ROIC&lt;6%)이 턱없이 낮아 주가가 바닥에 갇히는 위험 종목에 ⚠️ 태그를 부여합니다.
        </div>
    </div>
    """
    clean_guide_html = "\n".join([line.strip() for line in guide_box_html.split("\n") if line.strip()])
    st.markdown(clean_guide_html, unsafe_allow_html=True)

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
        filtered_stocks = [s for s in filtered_stocks if s.get("value_trap", False)]

    st.markdown(f"**전체 검색/필터 결과:** `{len(filtered_stocks)}`개 종목 (총 {len(all_stocks)}개 KOSPI 종목 중)")

    # 7. 페이지네이션 정보 계산
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

    # 8. 2단 수직 스택(상단 지표라벨 / 하단 수치대형폰트) & 퀀트 스코어 뱃지 정렬
    if not page_stocks:
        st.warning("선택한 필터 조건에 일치하는 종목이 없습니다.")
        return

    for s in page_stocks:
        vol_color = "#f43f5e" if "보정 중" in s.get("vol", "") else "#38bdf8"
        roe_color = "#f43f5e" if s.get("t_roe", 0) < 8.0 else "#4ade80"
        roic_color = "#f43f5e" if s.get("roic", 0) < 6.0 else "#38bdf8"
        
        trap_badge_html = ""
        if s.get("value_trap", False):
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

        # 야후 파이낸스 교차검증 15% 이상 이격 발생 뱃지 (관리자 전용 노출)
        discrepancy_badge_html = ""
        if is_admin and s.get("per_discrepancy", False):
            discrepancy_badge_html = """
            <span style="background-color: #78350f; color: #fde047; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #facc15; white-space: nowrap;">
                ⚙️ [관리자용] 데이터 이격 발생 (yfinance 차이>15%)
            </span>
            """

        dps_val = s.get('dps', 0)
        dps_str = f"{dps_val:,.0f}원/주" if dps_val > 0 else "무배당"
        growth_val = s.get('growth', 0)
        growth_disp = f"+{growth_val}%" if growth_val <= 35.0 else f"+{growth_val}% (Cap 35%)"

        card_html = f"""
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <!-- 1. 메인 헤더: 종목명 / 코드 / 퀀트종합점수 / 배지 / 현재가 -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <span style="font-size: 23px; font-weight: 800; color: #f8fafc; white-space: nowrap;">{s['name']}</span>
                    <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({s['code']})</span>
                    <!-- 100점 만점 퀀트 종합점수 뱃지 -->
                    <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px; font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                        <span class="q-tooltip" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="q-tooltiptext"><b>종합 퀀트 스코어 (100점 만점)</b><br>• PEGY 밸류에이션: 최대 35점<br>• 자본효율성 (ROE/ROIC): 최대 30점<br>• 주주환원율 (DPS): 최대 20점<br>• Trailing 실적안정성: 최대 10점<br>• 변동성위험 보정: 최대 5점<br><b>*목표가 도달/초과 시 적정가/고평가 정합성 자동 교차검증</b></span></span> <b>{s.get('quant_score', 80)}점</b> / 100점
                    </span>
                    <span style="background-color: {s['badge_bg']}; color: {s['badge_fg']}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {s['badge_fg']}; white-space: nowrap;">
                        {s['badge']}
                    </span>
                    <span style="font-size: 12px; color: {vol_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6); padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">{s['vol']}</span>
                    {trap_badge_html}
                    {discrepancy_badge_html}
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
                            <span class="q-tooltip" style="color: #fca5a5; font-weight: 700;">목표가 (PEGY) ℹ️<span class="q-tooltiptext"><b>보정 Forward PEGY & 퀀트 목표주가 안내</b><br>• <b>보정 PEGY 수치</b>: 주가수익비율(PER)을 예상 성장률(최대 35% 상한)과 주주환원율의 합으로 나누어 밸류에이션 부담을 측정합니다. (변동성 위험 시 1.18배 보정)<br>• <b>퀀트 목표주가</b>: 12개월 추정 EPS(주당순이익)에 코스피 평균 PER(10.4배)을 기본 적용하고, ROE 12% 이상(+15%) 및 ROIC 10% 이상(+10%) 우량 자본효율성 프리미엄을 가산하여 산출합니다.</span></span>
                        </div>
                        <div style="font-size: 16.5px; font-weight: 900; color: #ff4d6d; letter-spacing: 0.2px;">{s['f_pegy']} / {s['f_target']:,.0f}원</div>
                    </div>
                </div>
            </div>
        </div>
        """
        clean_card = "\n".join([line.strip() for line in card_html.split("\n") if line.strip()])
        st.markdown(clean_card, unsafe_allow_html=True)

    # 9. 페이지네이션 (Pagination) 컨트롤 - 하단 배치
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
