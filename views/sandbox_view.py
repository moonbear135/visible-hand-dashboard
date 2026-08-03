import os
import json
import streamlit as st

def load_static_kospi200_data():
    """크롤링 없이 이미 수집된 kospi200_pegy_latest.json 고정 데이터 로드"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "kospi200_pegy_latest.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
                return payload.get("metadata", {}), payload.get("stocks", [])
        except Exception as e:
            st.error(f"고정 데이터 로드 실패: {e}")
    return {}, []

def render_sandbox_page():
    """독립된 UI/UX 실험용 샌드박스 페이지 (직관적 가격 비교 레이아웃 프로토타입)"""
    
    st.markdown(
        """
        <style>
        .sandbox-header {
            text-align: center;
            padding: 20px;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-radius: 14px;
            border: 1px solid #334155;
            margin-bottom: 24px;
        }
        .sandbox-title {
            font-size: 26px;
            font-weight: 800;
            background: linear-gradient(90deg, #14b8a6 0%, #38bdf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 6px;
        }
        .sandbox-sub {
            color: #94a3b8;
            font-size: 13.5px;
        }
        
        .price-card {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .price-card:hover {
            border-color: #14b8a6;
        }
        
        .card-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .stock-name-title {
            font-size: 17px;
            font-weight: 700;
            color: #f8fafc;
        }
        .stock-code-sub {
            font-size: 12px;
            color: #64748b;
            margin-left: 6px;
        }
        
        /* 0.1초 가격 비교 박스 (위아래 직관 배치) */
        .comparison-box {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 12px;
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
    
    st.markdown(
        """
        <div class="sandbox-header">
            <div class="sandbox-title">🧪 UI/UX 샌드박스: 직관적 가격 비교 (Price Gap Lab)</div>
            <div class="sandbox-sub">실제 주가 대비 퀀트 적정 가치의 갭(Gap)을 0.1초 만에 파악할 수 있는 고가독성 레이아웃 프로토타입</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # 1. 고정 데이터 로드
    metadata, stocks = load_static_kospi200_data()
    
    st.markdown("### 🇰🇷 한국 주식 (KOSPI 200) 밸류에이션 갭 비교")
    st.caption(f"📌 수집 기준일: {metadata.get('last_updated_at', '2026-08-03')} (고정 스냅샷 데이터 연동 중)")
    
    if not stocks:
        st.warning("고정 데이터 파일(data/kospi200_pegy_latest.json)이 존재하지 않습니다.")
    else:
        # Grid 레이아웃 (3열 카드 배치)
        cols = st.columns(3)
        for idx, stock in enumerate(stocks):
            col = cols[idx % 3]
            with col:
                name = stock.get("name", "")
                code = stock.get("code", "")
                price = stock.get("price", 0)
                f_target = stock.get("f_target", 0)
                badge = stock.get("badge", "⚪ 데이터 분석 중")
                bg_color = stock.get("badge_bg", "#1e293b")
                fg_color = stock.get("badge_fg", "#94a3b8")
                
                # 갭(Gap) 계산 (%)
                if price > 0 and f_target > 0:
                    gap_pct = ((f_target - price) / price) * 100.0
                    gap_str = f"+{gap_pct:.1f}% 상승 여력" if gap_pct >= 0 else f"{gap_pct:.1f}% 프리미엄"
                    gap_color = "#4ade80" if gap_pct >= 0 else "#fca5a5"
                    bar_color = "#22c55e" if gap_pct >= 0 else "#ef4444"
                    bar_width = min(abs(gap_pct), 100)
                else:
                    gap_str = "측정불가"
                    gap_color = "#94a3b8"
                    bar_color = "#64748b"
                    bar_width = 0

                st.markdown(
                    f"""
                    <div class="price-card">
                        <div class="card-header-row">
                            <div>
                                <span class="stock-name-title">{name}</span>
                                <span class="stock-code-sub">{code}</span>
                            </div>
                            <span style="background-color: {bg_color}; color: {fg_color}; font-size: 11.5px; font-weight: 700; padding: 3px 8px; border-radius: 6px;">
                                {badge}
                            </span>
                        </div>
                        <div class="comparison-box">
                            <div class="comparison-row divider">
                                <span class="label-text">실제 가격 (현재가)</span>
                                <span class="price-text-curr">{price:,.0f}원</span>
                            </div>
                            <div class="comparison-row">
                                <span class="label-text">적정 가치 (목표가)</span>
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
                    """,
                    unsafe_allow_html=True
                )

    st.markdown("---")
    st.markdown("### 🇺🇸 미국 주식 (US Market) 밸류에이션 갭 (확장 대비 뼈대)")
    st.caption("🚀 향후 미국 주식 멀티마켓 확장을 위한 동일 논리 프로토타입 프레임워크")
    
    us_cols = st.columns(3)
    sample_us_stocks = [
        {"name": "Apple Inc.", "ticker": "AAPL", "price": "$224.23", "target": "$280.00", "gap": "+24.9% 상승 여력", "badge": "🟢 저평가", "bg": "#14532d", "fg": "#4ade80", "color": "#4ade80", "bar": 70},
        {"name": "NVIDIA Corp.", "ticker": "NVDA", "price": "$130.15", "target": "$185.00", "gap": "+42.1% 상승 여력", "badge": "🟢 강력 저평가", "bg": "#14532d", "fg": "#4ade80", "color": "#4ade80", "bar": 90},
        {"name": "Tesla Inc.", "ticker": "TSLA", "price": "$248.50", "target": "$195.00", "gap": "-21.5% 프리미엄", "badge": "🔴 고평가 주의", "bg": "#7f1d1d", "fg": "#fca5a5", "color": "#fca5a5", "bar": 100}
    ]
    
    for idx, us in enumerate(sample_us_stocks):
        col = us_cols[idx % 3]
        with col:
            st.markdown(
                f"""
                <div class="price-card">
                    <div class="card-header-row">
                        <div>
                            <span class="stock-name-title">{us['name']}</span>
                            <span class="stock-code-sub">{us['ticker']} · NASDAQ</span>
                        </div>
                        <span style="background-color: {us['bg']}; color: {us['fg']}; font-size: 11.5px; font-weight: 700; padding: 3px 8px; border-radius: 6px;">
                            {us['badge']}
                        </span>
                    </div>
                    <div class="comparison-box">
                        <div class="comparison-row divider">
                            <span class="label-text">실제 가격 (현재가)</span>
                            <span class="price-text-curr">{us['price']}</span>
                        </div>
                        <div class="comparison-row">
                            <span class="label-text">적정 가치 (목표가)</span>
                            <span class="price-text-target">{us['target']}</span>
                        </div>
                    </div>
                    <div class="gap-footer" style="color: {us['color']};">
                        <span>적정가 대비 갭</span>
                        <span>{us['gap']}</span>
                    </div>
                    <div class="gap-bar-bg">
                        <div style="height: 100%; width: {us['bar']}%; background-color: {us['color']}; border-radius: 3px;"></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
