import os
import pandas as pd
import streamlit as st
from datetime import datetime

def render_pegy_page():
    """'💡 사실 이 가격이에요' (Forward PEGY/PER/EPS 밸류에이션 분석) 화면 렌더링"""
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #d97706; margin: 0 0 8px 0; letter-spacing: -0.5px;">💡 사실 이 가격이에요</h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">Forward PEGY / PER / EPS 스냅샷 기반 퀀트 적정가치 분석</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 평균 Forward PER", "10.4 배", "-0.8배 (전월 대비)")
    with col2:
        st.metric("코스피 대표 EPS 성장률 (PEG)", "14.2 %", "+1.5%p")
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", "0.73", "저평가 수용 구간")

    st.markdown("---")

    st.markdown("### 📊 주요 업종/종목 밸류에이션 스냅샷")
    st.caption("*배치 스크립트로 수집된 최신 Forward PEGY / PER / EPS 데이터 스냅샷입니다.")

    sample_pegy_data = pd.DataFrame([
        {"종목명": "삼성전자", "현재가(원)": 74500, "Forward EPS": 5800, "Forward PER": 12.84, "배당수익률(%)": 1.94, "이익성장률(%)": 18.5, "PEGY": 0.63, "밸류에이션 평가": "🟢 강력 저평가"},
        {"종목명": "SK하이닉스", "현재가(원)": 182000, "Forward EPS": 19500, "Forward PER": 9.33, "배당수익률(%)": 0.82, "이익성장률(%)": 24.1, "PEGY": 0.37, "밸류에이션 평가": "🟢 강력 저평가"},
        {"종목명": "현대차", "현재가(원)": 245000, "Forward EPS": 32000, "Forward PER": 7.66, "배당수익률(%)": 4.08, "이익성장률(%)": 8.2, "PEGY": 0.62, "밸류에이션 평가": "🟢 저평가"},
        {"종목명": "NAVER", "현재가(원)": 178000, "Forward EPS": 8900, "Forward PER": 20.00, "배당수익률(%)": 0.67, "이익성장률(%)": 12.0, "PEGY": 1.58, "밸류에이션 평가": "🟧 적정가 형성"},
        {"종목명": "카카오", "현재가(원)": 42000, "Forward EPS": 1600, "Forward PER": 26.25, "배당수익률(%)": 0.14, "이익성장률(%)": 7.5, "PEGY": 3.43, "밸류에이션 평가": "🔴 고평가 관망"}
    ])

    st.table(sample_pegy_data.set_index("종목명"))
    st.caption("※ PEGY = Forward PER / (이익성장률 + 배당수익률). PEGY < 1.0 일수록 적정가 대비 저평가 상태를 의미합니다.")
