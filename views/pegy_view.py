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
    
    # 0. 최상단 앵커 (스크롤 이동용)
    st.markdown("<div id='top-anchor'></div>", unsafe_allow_html=True)

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
            width: max-content;
            max-width: 380px;
            word-break: keep-all;
            line-height: 1.4;
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
        /* 0.1초 가격 비교 박스 (위아래 직관 배치) */
        .comparison-box {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        .comparison-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 3px 0;
        }
        .comparison-row.divider {
            border-bottom: 1px dashed #334155;
            padding-bottom: 6px;
            margin-bottom: 6px;
        }
        .label-text {
            font-size: 12px;
            color: #94a3b8;
            font-weight: 600;
        }
        .price-text-curr {
            font-size: 15px;
            font-weight: 800;
            color: #cbd5e1;
        }
        .price-text-target {
            font-size: 16px;
            font-weight: 800;
            color: #14b8a6;
        }
        .gap-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            font-weight: 700;
        }
        .gap-bar-bg {
            height: 6px;
            background: #334155;
            border-radius: 3px;
            overflow: hidden;
            margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # 1-1. 페이지 이동 시 최상단 자동 스크롤 트리거
    if st.session_state.get("pegy_scroll_to_top", False):
        st.session_state.pegy_scroll_to_top = False
        st.markdown(
            """
            <script>
                setTimeout(function() {
                    if (window.parent && window.parent.document) {
                        var mainSec = window.parent.document.querySelector('section.main');
                        if (mainSec) { mainSec.scrollTo({top: 0, behavior: 'smooth'}); }
                        window.parent.scrollTo({top: 0, behavior: 'smooth'});
                    }
                    window.scrollTo({top: 0, behavior: 'smooth'});
                }, 100);
            </script>
            """,
            unsafe_allow_html=True
        )

    # 3. 상단 그라데이션 타이틀 및 법적 경고 박스
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 36px; font-weight: 800; color: #d97706; margin: 0 0 6px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
            <!-- 빨간색 하이라이트 투자 주의 및 AI 수식 안내 경고 박스 -->
            <div style="background: linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%); border: 2px solid #ef4444; border-radius: 12px; padding: 12px 22px; margin: 10px auto 14px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(239, 68, 68, 0.35);">
                <div style="font-size: 15px; font-weight: 800; color: #fca5a5; letter-spacing: -0.3px;">
                    🚨 [투자 주의 경고 및 AI 분석 안내]
                </div>
                <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
                    본 리포트의 수치 및 분석 결과는 <b>공시된 재무제표와 시장 데이터를 기반으로 AI 퀀트 알고리즘이 자동 계산한 단순 참고용 정보</b>입니다. 특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
                </div>
                <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
                    ⚠️ 모든 투자 결정과 그에 따른 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있음을 명시합니다.
                </div>
            </div>
            <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #475569; border-radius: 12px; padding: 12px 22px; margin: 0 auto 24px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);">
                <div style="font-size: 15px; font-weight: 800; color: #38bdf8; letter-spacing: -0.3px;">
                    📘 [학습용 보조 도구 안내]
                </div>
                <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
                    '잘 보면 보이는 손'은 정식 금융기관의 서비스가 아니며, 주식 초보자의 직관적인 밸류에이션 이해를 돕는 <b>참고용 프로젝트</b>입니다.
                </div>
                <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600; margin-top: 3px;">
                    ⚠️ 본 서비스는 종목 추천이나 원금 보장을 하지 않습니다. 제공된 데이터는 참고용으로만 활용하시고, 모든 투자 판단과 책임은 본인에게 있습니다.
                </div>
            </div>
            <div style="font-size: 15.5px; color: #64748b; font-weight: 600; margin-top: 6px;">KOSPI 200개 종목 Trailing vs Forward PEGY & 100점 만점 퀀트 종합점수 리포트</div>
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
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        latest_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "kospi200_pegy_latest.json")
        if os.path.exists(latest_path):
            with open(latest_path, "r", encoding="utf-8") as f:
                st.download_button(
                    label="📥 KOSPI 200 최신 스냅샷 다운로드 (JSON)",
                    data=f.read(),
                    file_name=f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json"
                )
            if st.session_state.get("admin_mode", False):
                try:
                    df_latest = pd.read_json(latest_path)
                    csv_latest = df_latest.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📊 [관리자] 최신 스냅샷 다운로드 (Excel)",
                        data=csv_latest,
                        file_name=f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                except Exception:
                    pass
    with col_dl2:
        history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pegy_summary_history.json")
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                st.download_button(
                    label="📥 누적 요약 히스토리 다운로드 (JSON)",
                    data=f.read(),
                    file_name=f"pegy_summary_history_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json"
                )
            if st.session_state.get("admin_mode", False):
                try:
                    df_history = pd.read_json(history_path)
                    csv_history = df_history.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📊 [관리자] 히스토리 다운로드 (Excel)",
                        data=csv_history,
                        file_name=f"pegy_summary_history_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                except Exception:
                    pass
    st.markdown("<br>", unsafe_allow_html=True)

    # 5. 최신 200개 종목 동기화 데이터 및 누적 히스토리 기반 동적 요약 지표 산출
    if all_stocks:
        f_per_list = [s['f_per'] for s in all_stocks if s.get('f_per', 0) > 0]
        growth_list = [min(s.get('growth', 0), 35.0) for s in all_stocks]
        pegy_list = [s.get('f_pegy', 0) for s in all_stocks if 0 < s.get('f_pegy', 0) < 50.0]

        calc_f_per = round(pd.Series(f_per_list).median(), 1) if f_per_list else 10.4
        calc_growth = round(pd.Series(growth_list).median(), 1) if growth_list else 14.2  # 통계적 대표값 중앙값(Median) 통일
        calc_pegy = round(pd.Series(pegy_list).median(), 2) if pegy_list else 0.73
    else:
        calc_f_per = 10.4
        calc_growth = 14.2
        calc_pegy = 0.73

    # 누적 히스토리 기반 증감 변동분(Delta) 계산
    f_per_delta_str = "KOSPI 200 실시간 중앙값"
    growth_delta_str = "실시간 중앙값 컨센서스"
    pegy_delta_str = "적정 밸류에이션"

    if len(summary_history) >= 2:
        prev = summary_history[-2]
        diff_per = round(calc_f_per - prev.get("f_per", calc_f_per), 1)
        diff_growth = round(calc_growth - prev.get("growth", calc_growth), 1)
        diff_pegy = round(calc_pegy - prev.get("pegy", calc_pegy), 2)
        
        f_per_delta_str = f"{diff_per:+.1f}배 (이전 동기화 대비)"
        growth_delta_str = f"{diff_growth:+.1f}%p (이전 동기화 대비)"
        pegy_delta_num = f"{diff_pegy:+.2f}"
    else:
        pegy_delta_num = "+0.00"

    if calc_pegy < 0.85:
        pegy_status = "🟢 저평가 수용 구간"
    elif calc_pegy < 1.15:
        pegy_status = "🟡 적정 밸류 구간"
    else:
        pegy_status = "🔴 고평가 관망 구간"

    pegy_delta_str = f"{pegy_delta_num} | {pegy_status}"

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 중앙 Forward PER", f"{calc_f_per} 배", f_per_delta_str)
    with col2:
        st.metric("코스피 대표 EPS 성장률 (Cap 35%)", f"{calc_growth} %", growth_delta_str)
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", f"{calc_pegy}", pegy_delta_str)

    st.markdown("---")

    # 6. 전체 종목 방공망 일괄 스크리닝 및 뱃지 필터 컨트롤 (모든 뱃지 동적 자동 구성)
    from utils.guardrail import apply_valuation_guardrail
    processed_stocks = []
    for s in all_stocks:
        screened_stock = apply_valuation_guardrail(s)
        processed_stocks.append(screened_stock)

    # 데이터에 존재하는 모든 뱃지 유형을 동적으로 추출하여 기본 옵션에 포함 (단 1개 종목도 누락 방지)
    all_badge_options = list(dict.fromkeys([s["badge"] for s in processed_stocks if s.get("badge")]))

    f_col1, f_col2, f_col3 = st.columns([2.2, 3.2, 2.0])
    with f_col1:
        search_query = st.text_input("🔍 종목명 / 종목코드 검색", placeholder="예: 삼성전자, 005930").strip()
    with f_col2:
        filter_preset = st.selectbox(
            "🏷️ 밸류에이션 빠른 필터",
            [
                "🌐 전체 종목 보기 (200개 코스피)",
                "🟢 저평가 우량주 그룹 (강력저평가 + 저평가)",
                "🟡 적정가 형성 그룹 (적정가 + 목표달성)",
                "🔴 고평가 / 주의 종목 그룹 (고평가 + 역성장 + 주의)",
                "⚙️ 세부 뱃지 직접 선택 (커스텀 필터)"
            ],
            index=0
        )
        selected_badges = None
        if "세부 뱃지" in filter_preset:
            selected_badges = st.multiselect(
                "상세 뱃지 스마트 선택",
                all_badge_options,
                default=all_badge_options
            )
        elif "저평가 우량주" in filter_preset:
            selected_badges = [b for b in all_badge_options if "저평가" in b]
        elif "적정가" in filter_preset:
            selected_badges = [b for b in all_badge_options if "적정가" in b]
        elif "고평가" in filter_preset:
            selected_badges = [b for b in all_badge_options if ("고평가" in b or "역성장" in b or "오류" in b or "검증" in b or "위험" in b)]

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

    filtered_stocks = processed_stocks
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

    for idx_stock, s in enumerate(page_stocks):
        # 시가총액 순위 대형 폰트 프래그먼트 (32px Extra Bold)
        rank_num = s.get("rank", start_idx + idx_stock + 1)
        rank_prefix_html = f'<span style="font-size: 32px; font-weight: 900; color: #38bdf8; letter-spacing: -1px; margin-right: 4px; line-height: 1;">{rank_num}.</span>'

        # 데이터 무결성 방공망: 차단 사유별 분기 마스크 카드 렌더링
        if s.get('is_unverified', False):
            reject_reason = s.get('reject_reason', '')
            unverified_reason = s.get('unverified_reason', '')

            # 사유별 테마 분기
            if 'PER' in reject_reason or 'PER' in str(s.get('badge', '')):
                # 🔴 PER 극단치 / 데이터 오염 (빨간 테마)
                badge_label = "🔴 PER 극단 고평가 (밸류에이션 측정 불가)"
                badge_bg = "#7f1d1d"
                badge_border = "#f87171"
                badge_fg = "#fca5a5"
                card_bg = "linear-gradient(135deg, #450a0a 0%, #1e1b4b 100%)"
                card_border_color = "#dc2626"
                inner_border = "#991b1b"
                title_icon = "🚫"
                title_text = "밸류에이션 산출 범위 초과 — 분석 제외 종목"
                title_color = "#f87171"
                desc_text = f"본 종목은 <b>PER {s['t_per']:,.1f}배 (EPS {s['t_eps']:,}원)</b>로 정상 밸류에이션 산출 범위(PER 300배)를 크게 초과하여 PEGY 분석이 무의미한 극단 고평가 상태입니다."
                desc_color = "#fecaca"
                hint_text = "📌 이익 수준이 정상화(EPS 회복)되면 자동으로 분석 대상에 복귀합니다."
            elif '역성장' in str(s.get('badge', '')) or s.get('g_eff', 1) <= 0:
                # 🟣 역성장 / 무성장 (보라 테마)
                badge_label = "🟣 역성장 · 무성장 (가치 훼손 위험)"
                badge_bg = "#3b0764"
                badge_border = "#a855f7"
                badge_fg = "#d8b4fe"
                card_bg = "linear-gradient(135deg, #3b0764 0%, #1e1b4b 100%)"
                card_border_color = "#7c3aed"
                inner_border = "#6d28d9"
                title_icon = "📉"
                title_text = "성장률 0% 이하 — 가치 훼손 구간"
                title_color = "#c4b5fd"
                desc_text = f"본 종목은 <b>ROE {s['t_roe']}%</b>로 실효성장률(g_eff)이 0 이하이며, 성장 기반 밸류에이션(PEGY) 적용이 부적합합니다."
                desc_color = "#e9d5ff"
                hint_text = "📌 이익 성장이 재개되면 자동으로 밸류에이션 분석이 복구됩니다."
            else:
                # 🟡 주주환원 공시 미확정 (주황 테마 — 기존)
                badge_label = "⚠️ 배당/주주환원 공시 데이터 미확정"
                badge_bg = "#78350f"
                badge_border = "#facc15"
                badge_fg = "#fde047"
                card_bg = "linear-gradient(135deg, #451a03 0%, #1e1b4b 100%)"
                card_border_color = "#f59e0b"
                inner_border = "#b45309"
                title_icon = "🛡️"
                title_text = "주주환원 데이터 검증 대기 중"
                title_color = "#fbbf24"
                desc_text = f"본 종목은 <b>리츠/인프라/금융</b> 등 배당 필수 업종이나 DPS(주당배당금)가 0원으로 수집되어, PEGY 왜곡 방지를 위해 일시 차단 중입니다."
                desc_color = "#fef08a"
                hint_text = "💡 공시 실데이터 재검토 및 출처 교차검증 완료 후 정확한 밸류에이션 리포트가 복구됩니다."

            unverified_html = f"""
            <div style="background: {card_bg}; border: 2px dashed {card_border_color}; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.5); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid {inner_border}; padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        {rank_prefix_html}
                        <span style="font-size: 22px; font-weight: 800; color: {badge_fg};">{s['name']}</span>
                        <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({s['code']})</span>
                        <span style="background-color: {badge_bg}; color: {badge_fg}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {badge_border}; white-space: nowrap;">
                            {badge_label}
                        </span>
                    </div>
                    <div style="display: flex; align-items: baseline; gap: 8px;">
                        <span style="font-size: 13px; color: #94a3b8;">현재가:</span>
                        <span style="font-size: 22px; font-weight: 900; color: #38bdf8;">{s['price']:,.0f}원</span>
                    </div>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid {inner_border}; border-radius: 10px; padding: 18px 24px; text-align: center;">
                    <h3 style="color: {title_color}; font-size: 16.5px; font-weight: 800; margin: 0 0 6px 0;">{title_icon} {title_text}</h3>
                    <p style="color: {desc_color}; font-size: 13.5px; font-weight: 600; margin: 0; line-height: 1.5;">
                        {desc_text}
                    </p>
                    <div style="color: #cbd5e1; font-size: 12px; margin-top: 6px;">
                        {hint_text}
                    </div>
                </div>
            </div>
            """
            st.markdown("\n".join([line.strip() for line in unverified_html.split("\n") if line.strip()]), unsafe_allow_html=True)
            continue

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

        t_eps_val = s.get('t_eps', 0)
        t_eps_str = f"{t_eps_val:,}" if isinstance(t_eps_val, (int, float)) else str(t_eps_val)
        t_pbr = s.get("t_pbr", "-")
        ev_ebitda = s.get("ev_ebitda", "-")
        ev_years_str = ""
        try:
            ev_val = float(ev_ebitda)
            ev_years_str = f" <span style='font-size: 11px; color: #94a3b8; font-weight: 500;'>(약 {ev_val:.1f}년)</span>"
        except (ValueError, TypeError):
            pass

        dps_val = s.get('dps', 0)
        dps_str = f"{dps_val:,.0f}원/주" if dps_val > 0 else "무배당"
        growth_val = s.get('growth', 0)
        growth_disp = f"+{growth_val}%" if growth_val <= 35.0 else f"+{growth_val}% (Cap 35%)"

        price = s.get('price', 0)

        # 콘크리트 바닥가 계산
        floor_price_str = "-"
        try:
            pbr_val = float(t_pbr)
            if pbr_val > 0:
                floor_price = price / pbr_val
                floor_price_str = f"{floor_price:,.0f}원"
        except (ValueError, TypeError):
            pass
        f_target = s.get('f_target', 0)
        if price > 0 and f_target > 0:
            gap_pct = ((f_target - price) / price) * 100.0
            gap_str = f"+{gap_pct:.1f}% 상승 여력" if gap_pct >= 0 else f"{abs(gap_pct):.1f}% 프리미엄"
            gap_color = "#4ade80" if gap_pct >= 0 else "#fca5a5"
            bar_color = "#22c55e" if gap_pct >= 0 else "#ef4444"
            bar_width = min(abs(gap_pct), 100)
        else:
            gap_str = "측정불가"
            gap_color = "#94a3b8"
            bar_color = "#64748b"
            bar_width = 0

        card_html = f"""
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #334155; border-radius: 14px; padding: 22px 26px; margin-bottom: 24px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <!-- 1. 메인 헤더: 종목명 / 코드 / 퀀트종합점수 / 배지 / 현재가 -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 14px; flex-wrap: wrap; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    {rank_prefix_html}
                    <span style="font-size: 24px; font-weight: 800; color: #f8fafc; white-space: nowrap;">{s['name']}</span>
                    <span style="font-size: 14px; color: #94a3b8; font-weight: 600;">({s['code']})</span>
                    <!-- 100점 만점 퀀트 종합점수 뱃지 -->
                    <span style="background: linear-gradient(135deg, #b45309 0%, #78350f 100%); color: #fef08a; font-size: 12.5px; font-weight: 800; padding: 4px 11px; border-radius: 12px; border: 1px solid #fde047; white-space: nowrap;">
                        <span class="q-tooltip" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="q-tooltiptext"><b>종합 퀀트 스코어 (100점 만점)</b><br>이 회사가 얼마나 돈을 잘 벌고, 주주에게 잘 나눠주고, 가격이 싼지를 종합적으로 채점한 점수예요!</span></span> <b>{s.get('quant_score', 80)}점</b> / 100점
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

            {"" if s.get('t_roe', 0) >= 0 else f'''
            <!-- 적자 경고 배너: ROE 마이너스 종목 강조 경고 -->
            <div style="background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 50%, #450a0a 100%); border: 1.5px solid #dc2626; border-radius: 10px; padding: 12px 20px; margin-bottom: 14px; display: flex; align-items: center; gap: 14px; box-shadow: 0 0 15px rgba(220, 38, 38, 0.25); animation: pulse-border 2s infinite;">
                <div style="font-size: 28px; flex-shrink: 0;">🚨</div>
                <div style="flex: 1;">
                    <div style="color: #fca5a5; font-size: 14px; font-weight: 800; margin-bottom: 3px;">
                        ⚠️ 적자 기업 — PEGY 밸류에이션 산출 불가 (ROE {s["t_roe"]}%)
                    </div>
                    <div style="color: #fecaca; font-size: 12px; font-weight: 500; line-height: 1.5;">
                        본 종목은 최근 12개월 기준 <b>순이익 적자(ROE &lt; 0)</b> 상태로, 성장 기반 밸류에이션(PEGY)을 적용할 수 없습니다.
                        아래 목표주가·적정가는 <b>참고 불가</b>하며, 이익 정상화 전까지 투자에 각별한 주의가 필요합니다.
                    </div>
                </div>
                <div style="background: #991b1b; border: 1px solid #f87171; border-radius: 8px; padding: 6px 14px; text-align: center; flex-shrink: 0;">
                    <div style="color: #f87171; font-size: 18px; font-weight: 900;">99.99</div>
                    <div style="color: #fca5a5; font-size: 10px; font-weight: 600;">PEGY 측정불가</div>
                </div>
            </div>
            '''}

            <!-- 2. 자본효율성 품질 바 (Quality Bar) -->
            <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; justify-content: flex-start; gap: 28px; flex-wrap: wrap;">
                <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext"><b>Trailing ROE (자기자본이익률)</b><br>지난 12개월(4분기 합산) 순이익을 자기자본으로 나눈 자본 효율성 지표입니다. 8% 미만 시 이익 창출력이 부족한 상태입니다.</span></span>: 
                    <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['t_roe']}%</b>
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE (예상 자기자본이익률)</b><br>내년에 회사가 가진 돈(자본)으로 얼마나 이익을 낼지 예상한 비율이에요. 높을수록 수익성이 좋아집니다.</span></span>: 
                    <b style="color: #38bdf8; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['f_roe']}%</b>
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">ROIC (ROC) ℹ️<span class="q-tooltiptext"><b>ROIC (영업 투입자본이익률)</b><br>장사 밑천을 얼마나 효율적으로 굴렸는지 보여주는 지표예요. 이 숫자가 높을수록 돈을 잘 굴리는 똑똑한 기업입니다.</span></span>: 
                    <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{s['roic']}%</b>
                </span>
            </div>

            <!-- 3. Trailing 섹션 (과거 실적 참고용 - 상단 라벨 / 하단 수치 2단 스택) -->
            <div style="background-color: rgba(30, 41, 59, 0.45); border: 1px solid #334155; border-radius: 10px; padding: 12px 18px; margin-bottom: 14px; opacity: 0.88;">
                <div style="font-size: 12px; font-weight: 700; color: #94a3b8; margin-bottom: 10px; border-bottom: 1px dashed #475569; padding-bottom: 4px; display: flex; justify-content: space-between; align-items: center;">
                    <span>📜 Trailing (과거 실적 참고용)</span>
                    <span style="font-size: 11px; color: #64748b; font-weight: 400;">*과거 12개월 실적 스냅샷</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext"><b>Trailing ROE</b><br>과거 12개월 평균 자기자본 대비 순이익 비율</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #cbd5e1;">{s['t_roe']}%</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">가치 및 회수 지표 ℹ️<span class="q-tooltiptext"><b>Trailing 밸류에이션</b><br>• PER: 주가/순이익<br>• EPS: 주당순이익<br>• PBR: 주가/순자산<br>• EV/EBITDA: M&A 투자원금 회수기간</span></span>
                        </div>
                        <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PER ℹ️<span class="q-tooltiptext">1년 동안 번 돈에 비해 주가가 몇 배인가? (낮을수록 저렴)</span></span> {s['t_per']}배 <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EPS ℹ️<span class="q-tooltiptext">주식 1주가 1년 동안 벌어온 순수익(원)</span></span> {t_eps_str}원 <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PBR ℹ️<span class="q-tooltiptext">회사 전 재산을 다 팔았을 때 가치 대비 주가가 몇 배인가? (1배 이하면 바겐세일)</span></span> {t_pbr}배
                        </div>
                        <div style="font-size: 18px; color: #38bdf8; font-weight: 800; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EV/EBITDA (M&A 원금회수) ℹ️<span class="q-tooltiptext">회사를 통째로 샀을 때, 장사해서 본전 뽑는 기간</span></span> {ev_ebitda}배{ev_years_str.replace("11px", "13px")}
                        </div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">주주환원 상세 (DPS/총액) ℹ️<span class="q-tooltiptext"><b>주주환원 세부 내역</b><br>• 1주당 배당금 (DPS): {dps_str}<br>• 주주환원 총 규모: {s['return_total']}<br>• 총 주주환원율: {s['sh_return']}%</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #86efac;">DPS {dps_str} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> 환원율 {s['sh_return']}% <span style="font-size: 13px; color: #94a3b8;">({s['return_total']})</span></div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">PEGY / 과거 적정가 ℹ️<span class="q-tooltiptext"><b>Trailing PEGY & 과거 적정주가</b><br>• PEGY: PER / (성장률 + 주주환원율)<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{s['t_pegy']} <span style="color: #475569; font-size: 15px; margin: 0 4px;">/</span> {s['t_fair']:,.0f}원</div>
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

                <!-- 수치 영역: 2x2 Grid -->
                <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE</b><br>향후 12개월 애널리스트 예상 순이익 기반 ROE</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{s['f_roe']}%</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">Forward PER / EPS ℹ️<span class="q-tooltiptext"><b>Forward PER & EPS</b><br>• Forward PER: 주가 / 12개월 추정 EPS<br>• Forward EPS: 향후 12개월 예상 주당순이익</span></span>
                        </div>
                        <div style="font-size: 18px; color: #f1f5f9; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward PER ℹ️<span class="q-tooltiptext">내년에 벌어들일 돈에 비해 현재 주가가 몇 배인가? (낮을수록 저렴)</span></span> {s['f_per']}배 <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward EPS ℹ️<span class="q-tooltiptext">주식 1주가 내년 1년 동안 벌어들일 것으로 예상되는 순수익(원)</span></span> {s['f_eps']:,.0f}원
                        </div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">예상 성장률 ℹ️<span class="q-tooltiptext"><b>예상 EPS 성장률 (%)</b><br>향후 12개월 EPS 예상 성장 비율 (기저효과 착시 방지를 위해 최대 35.0% 상한 적용)</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{growth_disp}</div>
                    </div>
                    <div>
                        <div class="comparison-box" style="margin-bottom: 8px; border-color: #38bdf8; width: 100%;">
                            <div class="comparison-row divider">
                                <span class="label-text">현재가</span>
                                <span class="price-text-curr">{price:,.0f}원</span>
                            </div>
                            <div class="comparison-row divider">
                                <span class="label-text">
                                    <span class="q-tooltip" style="color: #94a3b8; font-weight: 700;">🛡️ PBR 계산의 바닥가 ℹ️<span class="q-tooltiptext" style="color: #f1f5f9; font-weight: 400;">회사가 가진 순수한 재산 가치를 기준으로 산정한 심리적 바닥 가격입니다. (현재가 ÷ PBR로 계산됨)</span></span>
                                </span>
                                <span style="font-size: 15px; font-weight: 700; color: #94a3b8;">{floor_price_str}</span>
                            </div>
                            <div class="comparison-row">
                                <span class="label-text">
                                    <span class="q-tooltip" style="color: #14b8a6; font-weight: 700;">목표가 (Target) ℹ️<span class="q-tooltiptext" style="color: #f1f5f9; font-weight: 400;"><b>목표 적정주가</b><br>회사의 예상 성장률, 주주환원(배당 등), 이익 창출력(ROE/ROIC)을 모두 고려해 계산한 '적당한 가격'이에요.</span></span>
                                </span>
                                <span class="price-text-target">{f_target:,.0f}원</span>
                            </div>
                        </div>
                        <div class="gap-footer" style="color: {gap_color};">
                            <span>적정가 대비 갭</span>
                            <span>{gap_str}</span>
                        </div>
                        <div class="gap-bar-bg">
                            <div style="height: 100%; width: {bar_width}%; background-color: {bar_color}; border-radius: 3px;"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
        clean_card = "\n".join([line.strip() for line in card_html.split("\n") if line.strip()])
        st.markdown(clean_card, unsafe_allow_html=True)

    # 9. 페이지네이션 (Pagination) 컨트롤 - 하단 배치
    st.markdown("---")
    
    col1, col2 = st.columns([0.8, 0.2])
    with col1:
        st.markdown("##### 📄 페이지 선택 (한 화면에 20개 종목 카드 노출)")
    with col2:
        st.markdown(
            """
            <div style='text-align: right; padding-top: 5px;'>
                <a href='#top-anchor' target='_self' style='display: inline-block; padding: 8px 16px; background-color: #38bdf8; color: #0f172a; font-size: 14px; font-weight: 800; border-radius: 8px; text-decoration: none; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: all 0.2s;'>
                    ⬆️ TOP으로 가기
                </a>
            </div>
            """, 
            unsafe_allow_html=True
        )

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

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 2px solid #475569; border-radius: 12px; padding: 12px 22px; margin: 20px auto 10px auto; max-width: 860px; text-align: center; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);">
            <div style="font-size: 14px; font-weight: 800; color: #38bdf8; letter-spacing: -0.3px;">
                ⚠️ [알림: 학습용 보조 도구]
            </div>
            <div style="font-size: 13.5px; color: #cbd5e1; font-weight: 600; margin-top: 5px; line-height: 1.5;">
                본 서비스는 정식 금융기관이 아닌 주식 공부를 돕는 개인 프로젝트(보조 도구)입니다.<br>
                종목 추천이나 원금 보장을 하지 않으며, 모든 데이터는 참고용이므로 최종 투자 판단과 책임은 본인에게 있습니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
