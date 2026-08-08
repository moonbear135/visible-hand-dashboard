import os
import json
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None
import pandas as pd
import streamlit as st

from utils.db import HISTORY_FILE, COL_MAP


def load_latest_kospi_usd():
    """
    market_history.csv에서 가장 최근 코스피 지수·원/달러 환율만 가볍게 읽어옵니다.
    ("잘 보면 보이는 손"이 관리자 전용으로 바뀌면서 공개 화면에서 이 기본 정보가
    아예 안 보이게 된 문제를 보완하기 위해 2026-08-06 추가.)
    실패해도 절대 지어내지 않고 None을 반환합니다.
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            return None
        df = pd.read_csv(HISTORY_FILE)
        df = df.rename(columns={v: k for k, v in COL_MAP.items()})
        if df.empty or "KOSPI" not in df.columns or "USD_KRW" not in df.columns:
            return None
        last = df.iloc[-1]
        kospi = float(last["KOSPI"]) if pd.notna(last.get("KOSPI")) else None
        usd = float(last["USD_KRW"]) if pd.notna(last.get("USD_KRW")) else None
        date_str = str(last["Date"]) if "Date" in df.columns and pd.notna(last.get("Date")) else None
        if kospi is None or usd is None:
            return None
        return {"kospi": kospi, "usd": usd, "date": date_str}
    except Exception:
        return None


def fmt_num(value, suffix="", digits=None, na_text="데이터 없음"):
    """
    None / 결측값을 절대 그럴듯한 숫자로 바꾸지 않고 '데이터 없음'으로 표기합니다.
    (ENGINEERING_SPEC §0-1)
    """
    if value is None:
        return na_text
    try:
        if isinstance(value, str):
            return f"{value}{suffix}"
        if digits is None:
            return f"{value:,}{suffix}"
        return f"{value:,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return na_text


def load_kospi200_snapshot():
    """
    data/kospi200_pegy_latest.json 스냅샷 로드 및 메타데이터 반환.

    ⚠️ 렌더링 도중에 수집기(run_kospi200_collector)를 절대 실행하지 않습니다.
       (종목당 2~3초 슬립 × 200종목 = 10분 이상 블로킹 → Streamlit 타임아웃)
       스냅샷이 없거나 깨졌으면 '현재 시각'을 마지막 동기화 시각인 것처럼 꾸미지 않고
       last_updated_at=None / status="LOAD_FAILED" 를 그대로 반환합니다.
    """
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    json_path = os.path.join(data_dir, "kospi200_pegy_latest.json")

    if not os.path.exists(json_path):
        return {"last_updated_at": None, "status": "LOAD_FAILED",
                "load_error": "스냅샷 파일(data/kospi200_pegy_latest.json)이 없습니다."}, []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        meta = payload.get("metadata", {})
        stocks = payload.get("stocks", [])
        if not stocks:
            meta = dict(meta)
            meta["status"] = meta.get("status") or "EMPTY"
            meta["load_error"] = "스냅샷에 종목 데이터가 0건입니다."
        return meta, stocks
    except Exception as e:
        print(f"Error reading JSON snapshot: {e}")
        return {"last_updated_at": None, "status": "LOAD_FAILED",
                "load_error": f"스냅샷 파일을 읽지 못했습니다: {e}"}, []


def load_pegy_summary_history():
    """data/pegy_summary_history.json 누적 수치 이력을 로드합니다."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    history_path = os.path.join(data_dir, "pegy_summary_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 요약 히스토리 로드 실패: {e}")
            try:
                st.warning(f"⚠️ 누적 요약 히스토리를 읽지 못했습니다: {e}")
            except Exception:
                pass
    return []

def render_pegy_page():
    """'💡 사실 이 가격이에요' (배치 수집 JSON 동적 요약 지표 & 누적 히스토리 연동) 화면 렌더링"""
    
    # 0. 최상단 앵커 (스크롤 이동용)
    st.markdown("<div id='top-anchor'></div>", unsafe_allow_html=True)

    # 1. JSON 스냅샷 및 메타데이터 연동
    metadata, all_stocks = load_kospi200_snapshot()
    # 히스테리시스 버퍼(2026-08-06 도입) 적용 시 JSON에는 201~230위 버퍼 구간 종목도 함께 저장되지만
    # (요약 이력이 끊기지 않게 하기 위함), 화면 노출은 항상 정확히 순위 200위 이내만입니다.
    # is_visible 필드가 없는 구버전 스냅샷은 전부 노출(True)로 간주해 하위 호환을 유지합니다.
    all_stocks = [s for s in all_stocks if s.get("is_visible", True)]
    last_updated_at = metadata.get("last_updated_at")   # 없으면 None (현재 시각으로 위장 금지)
    snapshot_status = metadata.get("status", "UNKNOWN")
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
            width: 300px;
            box-sizing: border-box;
            white-space: normal;
            overflow-wrap: break-word;
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
                    본 리포트의 수치 및 분석 결과는 <b>공시된 재무제표와 시장 데이터를 기반으로 AI 퀀트 알고리즘이 자동 계산한 단순 참고용 정보</b>입니다.<br>
                    특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
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
                    ⚠️ 본 서비스는 종목 추천이나 원금 보장을 하지 않습니다.<br>
                    제공된 데이터는 참고용으로만 활용하시고, 모든 투자 판단과 책임은 본인에게 있습니다.
                </div>
            </div>
            <!-- 2026-08-06 2차 감사 3-3: "100점 만점" 문구 정정.
                 실제 만점은 종목마다 다릅니다(ROIC 15점은 원천 데이터를 수집하지 않아 상시 제외라
                 대부분 85점 이하, 컨센서스가 없으면 더 낮아짐). 수집 못 한 항목을 배점에서 빼는
                 설계와 화면 문구가 어긋나 있었습니다. -->
            <div style="font-size: 15.5px; color: #64748b; font-weight: 600; margin-top: 6px;">코스피 시가총액 상위 200개 종목 Trailing vs Forward PEGY & 퀀트 종합점수 리포트<br><span style="font-size: 13px; color: #475569;">(만점은 종목마다 다릅니다 — 수집하지 못한 지표는 점수를 지어내지 않고 배점에서 제외하므로, 각 카드에 '획득점수 / 그 종목의 만점 (달성률%)'로 표기됩니다)</span></div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 3-1. 코스피 지수 / 원/달러 환율 요약 카드 — 2026-08-06 추가.
    # "잘 보면 보이는 손"(매크로 화면)이 관리자 전용으로 바뀌면서 공개 화면에서 이 기본 정보를
    # 아예 볼 수 없게 된 문제를 보완. 일반 사용자에게 소수점까지는 필요 없으므로 정수로 반올림 표기.
    market_snapshot = load_latest_kospi_usd()
    if market_snapshot:
        date_label = f" ({market_snapshot['date']} 장마감 기준)" if market_snapshot.get('date') else ""
        st.markdown(
            f"""
            <div style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; max-width: 860px; margin-left: auto; margin-right: auto;">
                <div style="flex: 1 1 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
                    <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">📈 코스피 지수{date_label}</div>
                    <div style="font-size: 30px; color: #f8fafc; font-weight: 800; letter-spacing: -1px; margin-top: 4px;">{market_snapshot['kospi']:,.0f}</div>
                </div>
                <div style="flex: 1 1 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 1.5px solid #334155; border-radius: 14px; padding: 16px 20px;">
                    <div style="font-size: 13px; color: #94a3b8; font-weight: 700;">💵 원/달러 환율{date_label}</div>
                    <div style="font-size: 30px; color: #f8fafc; font-weight: 800; letter-spacing: -1px; margin-top: 4px;">{market_snapshot['usd']:,.0f}<span style="font-size: 18px; font-weight: 700;">원</span></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # 4. 대시보드 상단 배치 동기화 배너 + 스냅샷 상태/신선도(staleness) 검사
    if last_updated_at is None or not all_stocks:
        st.error(
            f"🚨 시가총액 상위 200 스냅샷을 불러오지 못했습니다. ({metadata.get('load_error', '원인 미상')})\n\n"
            "가짜 기본값으로 화면을 채우지 않기 위해 밸류에이션 수치를 표시하지 않습니다. "
            "자동 수집(GitHub Actions `Daily Market Scraper`)이 정상 동작했는지 확인해 주세요."
        )
        st.stop()

    # 스냅샷이 언제 것인지, 수집 품질이 어땠는지 화면에 그대로 노출
    # 2026-08-06: last_updated_at은 KST 벽시계 값으로 저장됩니다(collector_kospi200.py 수정).
    # Streamlit 서버 자체가 UTC로 돌 수 있어(datetime.now()는 naive UTC), 비교 기준도
    # KST 벽시계로 맞춰야 9시간 오차 없이 신선도를 정확히 계산합니다.
    stale_hours = None
    try:
        now_kst_naive = datetime.now(KST).replace(tzinfo=None) if KST else datetime.now()
        stale_hours = (now_kst_naive - datetime.strptime(last_updated_at, "%Y-%m-%d %H:%M")).total_seconds() / 3600.0
    except Exception:
        stale_hours = None

    if stale_hours is not None and stale_hours >= 24:
        st.error(
            f"🚨 마지막 수집이 **{stale_hours/24:.1f}일 전({last_updated_at})** 입니다. "
            "아래 수치는 최신 시세가 아닙니다. 자동 수집이 멈춰 있는지 확인해 주세요."
        )

    if snapshot_status not in ("SUCCESS", "UNKNOWN"):
        st.warning(
            f"⚠️ 스냅샷 수집 상태: **{snapshot_status}** — "
            f"검증 통과 {metadata.get('valid_count', '?')}/{metadata.get('total_count', '?')}종목. "
            "일부 종목은 데이터 부족으로 '측정 불가' 카드로 표시됩니다."
        )

    st.markdown(
        f"""
        <div style="background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%); border: 1.5px solid #0284c7; border-radius: 10px; padding: 12px 20px; margin-bottom: 22px; text-align: center; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.25); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <span style="font-size: 15.5px; font-weight: 800; color: #38bdf8;">
                📅 마지막 동기화: {last_updated_at} (크롤링 완료 후 장마감 데이터 적용)
            </span>
            <span style="font-size: 13px; color: #94a3b8; margin-left: 14px; font-weight: 600;">
                • 배치 수집 스냅샷 ({metadata.get('total_count', len(all_stocks))}개 종목 / 상태 {snapshot_status})
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
                    label="📥 시가총액 상위 200 최신 스냅샷 다운로드 (JSON)",
                    data=f.read(),
                    file_name=f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json"
                )
            if st.session_state.get("admin_mode", False):
                try:
                    import json
                    with open(latest_path, "r", encoding="utf-8") as f_json:
                        latest_data = json.load(f_json)
                    df_latest = pd.DataFrame(latest_data.get("stocks", []))
                    csv_latest = df_latest.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📊 [관리자] 최신 스냅샷 다운로드 (Excel)",
                        data=csv_latest,
                        file_name=f"kospi200_latest_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                except Exception as e:
                    print(f"⚠️ [관리자] 스냅샷 CSV 변환 실패: {e}")
                    st.warning(f"⚠️ [관리자] 스냅샷 Excel 변환에 실패했습니다: {e}")
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
                except Exception as e:
                    print(f"⚠️ [관리자] 히스토리 CSV 변환 실패: {e}")
                    st.warning(f"⚠️ [관리자] 히스토리 Excel 변환에 실패했습니다: {e}")
    st.markdown("<br>", unsafe_allow_html=True)

    # 5. 최신 종목 데이터 기반 요약 지표 산출
    #    ⚠️ 표본이 없으면 10.4 / 14.2 / 0.73 같은 그럴듯한 상수를 표시하지 않고 '데이터 없음'.
    f_per_list = [s['f_per'] for s in all_stocks if s.get('f_per')]
    growth_list = [s['growth'] for s in all_stocks if s.get('growth') is not None]
    pegy_list = [s['f_pegy'] for s in all_stocks if s.get('f_pegy') and 0 < s['f_pegy'] < 50.0]

    calc_f_per = round(float(pd.Series(f_per_list).median()), 1) if f_per_list else None
    calc_growth = round(float(pd.Series(growth_list).median()), 1) if growth_list else None
    calc_pegy = round(float(pd.Series(pegy_list).median()), 2) if pegy_list else None

    # 누적 히스토리 기반 증감 변동분(Delta) 계산
    f_per_delta_str = f"{len(f_per_list)}개 종목 실측 중앙값"
    growth_delta_str = f"{len(growth_list)}개 종목 실측 중앙값"
    pegy_delta_num = None

    if len(summary_history) >= 2 and None not in (calc_f_per, calc_growth, calc_pegy):
        prev = summary_history[-2]
        p_per, p_growth, p_pegy = prev.get("f_per"), prev.get("growth"), prev.get("pegy")
        if p_per is not None:
            f_per_delta_str = f"{calc_f_per - p_per:+.1f}배 (이전 동기화 대비)"
        if p_growth is not None:
            growth_delta_str = f"{calc_growth - p_growth:+.1f}%p (이전 동기화 대비)"
        if p_pegy is not None:
            pegy_delta_num = f"{calc_pegy - p_pegy:+.2f}"

    if calc_pegy is None:
        pegy_status = "산출 불가 (표본 없음)"
    elif calc_pegy < 0.85:
        pegy_status = "🟢 저평가 수용 구간"
    elif calc_pegy < 1.15:
        pegy_status = "🟡 적정 밸류 구간"
    else:
        pegy_status = "🔴 고평가 관망 구간"

    pegy_delta_str = f"{pegy_delta_num} | {pegy_status}" if pegy_delta_num else pegy_status

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("타겟 중앙 Forward PER", fmt_num(calc_f_per, " 배", 1), f_per_delta_str)
    with col2:
        st.metric("코스피 대표 EPS 성장률 (컨센서스 EPS 기준)", fmt_num(calc_growth, " %", 1), growth_delta_str)
    with col3:
        st.metric("시장 적정 밸류에이션 (PEGY)", fmt_num(calc_pegy, "", 2), pegy_delta_str)

    if None in (calc_f_per, calc_growth, calc_pegy):
        st.warning("⚠️ 위 요약 지표 중 일부는 실측 표본이 없어 산출하지 못했습니다 ('데이터 없음').")

    st.markdown("---")

    # =========================================================
    # 6. 전체 종목 방공망 일괄 스크리닝 및 뱃지 필터 컨트롤 (모든 뱃지 동적 자동 구성)
    # ⚠️ 2026-08-06 2차 감사 3-5: 예전엔 렌더링할 때마다 guardrail을 무조건 재실행했습니다.
    # 수집기(collector_kospi200.py)가 이미 저장 전에 돌린 것과 같은 함수라 지금까지는
    # 결과가 같았지만, 어느 한쪽 로직이 갈라지는 순간 "저장된 판정"과 "화면 판정"이
    # 달라져도 아무도 모르는 구조였습니다(퀀트 점수는 저장값을, 배지·마스킹은 재실행값을
    # 쓰기 때문). → 스냅샷에 guardrail 결과가 이미 들어있으면 그대로 신뢰해서 쓰고,
    # 구버전 스냅샷(해당 필드 없음)일 때만 하위호환으로 재실행합니다.
    # =========================================================
    from utils.guardrail import apply_valuation_guardrail
    processed_stocks = []
    legacy_rescreened = 0
    for s in all_stocks:
        if 'forward_data_missing' in s:
            processed_stocks.append(s)   # 수집 시점 판정 그대로 사용 (단일 출처)
        else:
            processed_stocks.append(apply_valuation_guardrail(s))
            legacy_rescreened += 1
    if legacy_rescreened and is_admin:
        st.info(
            f"ℹ️ [관리자] 구버전 스냅샷 {legacy_rescreened}종목은 guardrail 판정 결과가 저장돼 있지 않아 "
            "화면에서 재실행했습니다. 다음 수집 이후에는 저장된 판정을 그대로 사용합니다."
        )

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
            # 2차 감사 1-8: 코드는 ROE 기준으로만 판정하는데 설명에는 ROIC가 적혀 있었습니다.
            help="주가가 PER 수치상 싸 보이지만, 실제 이익창출력(Trailing ROE<8%)이 낮아 오랜 기간 주가가 오르지 못하고 갇히는 위험 종목입니다. (ROIC 기준은 원천 데이터 미수집으로 판정에 사용하지 않습니다)"
        )

    # 줄간격 및 수평 여백이 보정된 넉넉한 가이드 박스
    guide_box_html = """
    <div style="background-color: #0f172a; border: 1px solid #0284c7; border-radius: 12px; padding: 16px 22px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="font-size: 15px; font-weight: 800; color: #38bdf8; margin-bottom: 10px;">
            💡 '착시 저평가 (가치주 덫)' 및 퀀트 스코어 가이드
        </div>
        <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65; margin-bottom: 8px;">
            • <b style="color: #fef08a;">🏆 퀀트 스코어 (quant_score)</b>: PEGY(35점) + Forward ROE(15점) + ROIC(15점) + 주주환원(20점) + Trailing(10점) + 변동성(5점) = 이론상 100점 만점입니다.<br>
            다만 <b>수집하지 못한 지표는 점수를 지어내지 않고 배점에서 통째로 제외</b>하므로 실제 만점은 종목마다 다릅니다.
            (현재 ROIC는 원천 데이터를 수집하지 않아 항상 제외되어 대부분 85점 이하가 만점이고, 애널리스트 컨센서스가 없으면 PEGY 35점도 빠집니다.)<br>
            (단, 현재가가 목표가를 초과했거나 PEGY &ge; 2.0 시 <b>목표가 달성 적정가/고평가 교차검증</b> 적용)
        </div>
        <div style="font-size: 13.5px; color: #e2e8f0; line-height: 1.65;">
            • <b style="color: #fca5a5;">⚠️ 착시 저평가</b>: 주가가 단순히 PER 5배~7배로 싸 보이지만<br>
            실제 이익창출력(<b>Trailing ROE &lt; 8%</b>)이 턱없이 낮아 주가가 바닥에 갇히는 위험 종목에 ⚠️ 태그를 부여합니다.<br>
            <span style="color: #94a3b8; font-size: 12.5px;">※ ROIC(&lt;6%) 기준은 원천 데이터(영업이익÷투하자본)를 아직 수집하지 않아 판정에 사용되지 않습니다 — 현재는 ROE 기준 단독 판정입니다.</span>
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

        # 데이터 무결성 방공망: 진짜 카드 자체를 그릴 수 없는 경우만 전체 차단합니다.
        # ⚠️ 2026-08-06 변경(오너 지적): "재무제표(Trailing)가 이미 존재하는 종목"까지 PER 극단치·
        # 역성장·검증 하네스 실패 등을 이유로 전체를 가려버리면 과거 데이터로 공부할 수가 없습니다.
        # → 진짜 아무것도 못 그리는 경우(price 없음, 상장주식수 파싱 오류로 전 지표 오염 의심)만
        # 전체 차단하고, 나머지(PER 극단치/역성장/g_eff 산출불가/일반 검증 실패)는 Trailing은 정상
        # 노출하고 "🚀 Forward" 카드 자리에만 사유별 색상 배지를 띄웁니다(배당 미확정 케이스와 동일 패턴).
        reject_reason = s.get('reject_reason', '')
        unverified_reason = s.get('unverified_reason', '')
        hard_block = (not s.get('is_valid', True)) and (
            '필수 지표 수집 실패' in reject_reason or '상장주식수 파싱 오류' in reject_reason
        )

        if hard_block:
            # ⚪ 카드 자체를 그릴 수 없음 (price 없음, 또는 상장주식수 파싱 오류로 다수 지표 오염 의심)
            badge_label = "⚪ 데이터 없음 (측정 불가)"
            badge_bg = "#1e293b"
            badge_border = "#64748b"
            badge_fg = "#cbd5e1"
            card_bg = "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)"
            card_border_color = "#64748b"
            inner_border = "#334155"
            title_icon = "🚫"
            title_text = "필수 데이터를 수집하지 못해 밸류에이션을 산출하지 않았습니다"
            title_color = "#cbd5e1"
            desc_text = f"수집 실패 사유: <b>{reject_reason or unverified_reason or '원인 미상'}</b>"
            desc_color = "#94a3b8"
            hint_text = "📌 값을 추정해 채우지 않고 '데이터 없음'으로 남깁니다. 다음 수집에서 정상화되면 자동 복구됩니다."

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

        vol_text = s.get("vol") or "❔ 변동성 데이터 없음"
        if "데이터 없음" in vol_text:
            vol_color = "#94a3b8"
        elif "확대" in vol_text or "보정" in vol_text:
            vol_color = "#f43f5e"
        else:
            vol_color = "#38bdf8"

        t_roe_val = s.get("t_roe")
        roic_val = s.get("roic")
        roe_color = "#94a3b8" if t_roe_val is None else ("#f43f5e" if t_roe_val < 8.0 else "#4ade80")
        roic_color = "#94a3b8" if roic_val is None else ("#f43f5e" if roic_val < 6.0 else "#38bdf8")

        # =========================================================
        # 2026-08-06 추가: Forward ROE 컨센서스 도입(네이버 재무제표 "연간 추정(E)" 컬럼에서
        # 실측, 추가 크롤링 없음). 반도체 등 경기순환 업종은 Trailing 대비 Forward가 몇 배씩
        # 뛰는 추정치가 실제로도 정상적으로 나올 수 있어, 값 자체를 지우거나 평균 내지 않고
        # 그대로 보여주되 격차가 큰 경우에만 옆에 작은 경고 배지로 맥락을 함께 전달합니다
        # (오너 요청 — "경고 배지 + 설명"이 임의로 값을 손대는 것보다 낫다는 방향).
        # =========================================================
        f_roe_val = s.get('f_roe')
        roe_gap_flag = bool(
            t_roe_val is not None and f_roe_val is not None and t_roe_val > 0
            and (f_roe_val >= t_roe_val * 2.5 or (f_roe_val - t_roe_val) >= 25.0)
        )
        if roe_gap_flag:
            roe_gap_badge_html = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
                'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
                f'vertical-align: middle;">⚡ 추정치 변동 큼<span class="q-tooltiptext">Trailing({t_roe_val:.1f}%) 대비 '
                f'Forward 추정치가 큰 폭으로 높습니다({f_roe_val:.1f}%).<br>반도체 등 경기순환 업종은 실적 사이클상 '
                '실제로 이런 추정이 나올 수 있으나, 애널리스트 컨센서스 특성상 오차가 클 수 있으니 참고용으로만 '
                '활용하세요.</span></span>'
            )
        else:
            roe_gap_badge_html = ""

        # =========================================================
        # 2026-08-06 추가: 성장률 100% 이상 시 PEGY '점수'만 보수적으로 캡하는 로직
        # (utils/scoring.py의 growth_score_capped) — 화면에 별도 표시가 없으면 "왜 목표가는
        # 저평가처럼 보이는데 퀀트 스코어는 낮지?"라는 혼란이 생길 수 있어 경고 배지로 이유를
        # 설명합니다(오너 지적: 예전엔 f_pegy 자체를 몰래 덮어써서 배지·목표가가 서로
        # 모순됐음 — 지금은 f_pegy는 그대로 두고 점수만 깎으므로 그 이유를 명시).
        # =========================================================
        growth_capped_badge_html = ""
        if s.get("growth_score_capped"):
            growth_capped_badge_html = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
                'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
                'vertical-align: middle;">⚠️ 고성장 추정 보수반영<span class="q-tooltiptext">예상 성장률이 100%를 '
                '넘어 기저효과(일시적 실적 급변) 왜곡 가능성을 의심, 퀀트 스코어의 PEGY 항목 점수만 보수적으로 '
                '깎았습니다.<br>목표가·적정가 갭은 원래 성장률 그대로 계산되어 있으니(점수만 영향, 값 자체는 '
                '건드리지 않음) 함께 참고하세요.</span></span>'
            )

        trap_badge_html = ""
        if s.get("value_trap", False):
            trap_badge_html = """
            <span style="background-color: #7f1d1d; color: #fca5a5; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #f87171; white-space: nowrap;">
                ⚠️ 이익창출력 저하 (착시 저평가 주의)
            </span>
            """
        elif t_roe_val is None:
            trap_badge_html = """
            <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #64748b; white-space: nowrap;">
                ❔ 자본효율성 판정 불가 (데이터 없음)
            </span>
            """
        else:
            trap_badge_html = """
            <span style="background-color: #14532d; color: #86efac; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #4ade80; white-space: nowrap;">
                ✨ 우량 자본효율성 (Quality OK)
            </span>
            """

        # 야후 파이낸스 교차검증 뱃지 (관리자 전용) — 미수행(None)과 이상없음(False)을 구분
        discrepancy_badge_html = ""
        if is_admin:
            if s.get("per_discrepancy") is True:
                discrepancy_badge_html = """
                <span style="background-color: #78350f; color: #fde047; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #facc15; white-space: nowrap;">
                    ⚙️ [관리자용] 데이터 이격 발생 (yfinance 차이>15%)
                </span>
                """
            elif s.get("per_discrepancy") is None:
                discrepancy_badge_html = """
                <span style="background-color: #1e293b; color: #cbd5e1; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 8px; border: 1px solid #64748b; white-space: nowrap;">
                    ⚙️ [관리자용] 외부 교차검증 미수행
                </span>
                """

        t_eps_str = fmt_num(s.get('t_eps'))
        # 2026-08-05 추가: Trailing EPS가 실측값이 아니라 계산값(가격÷PER 역산)이면
        # ENGINEERING_SPEC.md §0-1 예시2-보충 원칙에 따라 반드시 별도 마크를 붙입니다.
        calc_eps_tag = (
            ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
            'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
            'vertical-align: middle;">🧮 계산값<span class="q-tooltiptext">네이버에 실측 EPS가 없어 '
            '가격÷PER 로 역산한 값입니다 (실측 아님)</span></span>'
            if s.get("t_eps_calculated") else ""
        )
        t_pbr = s.get("t_pbr")
        t_pbr_str = fmt_num(t_pbr)
        ev_ebitda = s.get("ev_ebitda")
        ev_ebitda_str = fmt_num(ev_ebitda)
        ev_years_str = ""
        try:
            ev_val = float(ev_ebitda)
            ev_years_str = f" <span style='font-size: 11px; color: #94a3b8; font-weight: 500;'>(약 {ev_val:.1f}년)</span>"
        except (ValueError, TypeError):
            pass

        dps_val = s.get('dps') or 0
        dps_str = f"{dps_val:,.0f}원/주" if dps_val > 0 else "무배당"
        # 2026-08-06 추가: DPS가 재무제표 실측이 아니라 배당수익률로 역산한 계산값이면
        # ENGINEERING_SPEC.md §0-1 예시2-보충 원칙에 따라 별도 마크를 붙입니다.
        calc_dps_tag = (
            ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
            'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
            'vertical-align: middle;">🧮 계산값<span class="q-tooltiptext">재무제표에 확정 DPS가 없어 '
            '배당수익률로 역산한 값입니다 (실측 아님)</span></span>'
            if s.get("dps_source") == "derived_from_div_yield" else ""
        )
        growth_val = s.get('growth')
        growth_disp = "데이터 없음" if growth_val is None else f"{growth_val:+.1f}%"
        # growth가 계산값 Trailing EPS를 기반으로 산출됐으면 같은 마크를 붙입니다.
        if str(s.get("growth_source", "")).endswith("_calculated"):
            growth_disp += calc_eps_tag

        price = s.get('price') or 0

        # 콘크리트 바닥가 계산
        floor_price_str = "데이터 없음"
        try:
            pbr_val = float(t_pbr)
            if pbr_val > 0:
                floor_price = price / pbr_val
                floor_price_str = f"{floor_price:,.0f}원"
        except (ValueError, TypeError):
            pass
        # =========================================================
        # 목표가 대비 갭 표시
        # ⚠️ 2026-08-06 2차 감사 1-3: 목표가가 캡 상수(현재가×2.5)에 걸린 종목은 화면의
        # "+150.0% 상승 여력"이 계산 결과가 아니라 캡 상수 그 자체입니다(200종목 중 40종목이
        # 전부 똑같은 +150%였고, 툴팁은 "성장률·주주환원·이익창출력을 모두 고려해 계산"이라고
        # 설명하고 있었습니다). 초록색 상승여력 바 대신 회색/노란 '상한 도달' 배지로 바꿔
        # "이 숫자는 추정 신뢰구간 밖이라 절단된 값"이라는 사실을 그대로 노출합니다.
        # =========================================================
        f_target = s.get('f_target')
        f_target_capped = bool(s.get('f_target_capped'))
        target_cap_badge_html = ""
        if price > 0 and f_target and f_target_capped:
            cap_reason = s.get('f_target_cap_reason') or "현재가 배수 상한에 도달"
            uncapped = s.get('f_target_uncapped')
            uncapped_txt = f"캡을 적용하지 않은 산출값은 {uncapped:,}원입니다.<br>" if uncapped else ""
            # ⚠️ 2026-08-06 오너 지적("직관성이 너무 떨어져"): 상한 배수(현재가×2.5)가 고정값이라
            # gap_pct는 캡에 걸린 모든 종목에서 항상 정확히 +150%로 동일합니다 — 계산된 개별
            # 수치가 아니라 상수 그 자체라서, "＞+150%"처럼 숫자를 앞세우면 마치 종목마다 다른
            # 정밀한 값처럼 보여 오해를 줍니다. 숫자는 빼고 "산출 안 함" 상태를 명확히 표기합니다.
            gap_str = "상승여력 산출 안 함 (상한 캡 적용)"
            gap_color = "#fbbf24"
            bar_color = "#78716c"        # 계산된 상승여력이 아니므로 초록 바를 쓰지 않습니다
            bar_width = 100
            target_cap_badge_html = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
                'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
                'vertical-align: middle;">🧮 상한 적용값<span class="q-tooltiptext">이 목표가는 계산 결과가 아니라 '
                f'<b>상한(캡) 값</b>입니다.<br>{cap_reason}.<br>{uncapped_txt}'
                '고성장 종목은 PEGY 공식상 목표가가 발산하기 때문에 폭주 방지 상한을 두고 있으며, '
                '상한에 걸린 종목의 상승여력은 "최소 이만큼"이라는 뜻일 뿐 정밀한 추정치가 아닙니다.</span></span>'
            )
        elif price > 0 and f_target:
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

        # Trailing 적정가(t_fair)도 같은 상한에 걸릴 수 있으므로 동일하게 표시합니다.
        t_fair_cap_badge_html = ""
        if s.get('t_fair_capped'):
            t_fair_uncapped = s.get('t_fair_uncapped')
            t_fair_uncapped_txt = f"캡 미적용 산출값 {t_fair_uncapped:,}원.<br>" if t_fair_uncapped else ""
            t_fair_cap_badge_html = (
                ' <span class="q-tooltip" style="font-size: 10px; font-weight: 800; color: #fbbf24; '
                'background-color: #78350f; border: 1px solid #facc15; border-radius: 6px; padding: 1px 6px; '
                'vertical-align: middle;">🧮 상한 적용값<span class="q-tooltiptext">과거 적정가가 현재가 2.5배 '
                f'상한에 걸려 절단된 값입니다.<br>{t_fair_uncapped_txt}계산 결과가 아니라 상한값입니다.</span></span>'
            )

        # 퀀트 스코어 — 기본값 80점 금지. 산출되지 않았으면 '측정 불가'로 표기하고,
        # 배점이 제외된 항목이 있으면 만점(score_max)을 그대로 노출합니다.
        q_score = s.get('quant_score')
        q_max = s.get('score_max')
        excluded_items = s.get('score_excluded_items') or []
        if q_score is None:
            score_badge_html = "<b>측정 불가</b> (데이터 없음)"
            score_tooltip_extra = "필수 지표를 수집하지 못해 점수를 산출하지 않았습니다."
        else:
            # =========================================================
            # 2026-08-06 추가: 만점(score_max)이 종목마다 달라(제외된 항목 수에 따라 35~100점
            # 등으로 유동적) 원점수만 보면 서로 비교가 안 되는 문제(오너 지적: "만점이 35점인
            # 것도 있고 100점인 것도 있다") — 달성률(%)을 함께 크게 표기해 만점이 달라도
            # 한눈에 비교되게 합니다.
            # =========================================================
            # ⚠️ 2026-08-06 2차 감사 3-4: `q_max or 100` 제거.
            # 만점(score_max)이 없다는 건 "이 종목에서 채점 가능한 항목이 하나도 없다"는
            # 뜻인데, 거기에 없는 분모 100을 지어내면 달성률(%)까지 가짜가 됩니다.
            # 분모가 없으면 %를 계산하지 않고 그대로 '산출 불가'로 표기합니다(§0-1).
            q_max_val = q_max
            if not q_max_val:
                score_badge_html = f"<b>{q_score}점</b> / 만점 산출 불가 (채점 가능 항목 없음)"
            else:
                pct = round(q_score / q_max_val * 100)
                if pct >= 60:
                    pct_color = "#4ade80"
                elif pct >= 30:
                    pct_color = "#fde047"
                else:
                    pct_color = "#fca5a5"
                score_badge_html = (
                    f"<b>{q_score}점</b> / {q_max_val}점 "
                    f"<span style='color:{pct_color}; font-weight:900;'>({pct}%)</span>"
                )
            # 배지에 %가 이미 보이므로 툴팁 문구는 원래 길이(1줄)로 유지 — 예전에 설명을
            # 한 줄 더 추가했더니 툴팁 박스가 길어지면서 옆/아래 카드로 튀어나가는 렌더링
            # 버그가 생겨(오너 제보, 2026-08-06) 다시 짧게 되돌림.
            score_tooltip_extra = (
                f"※ 배점 제외 항목: {', '.join(excluded_items)}" if excluded_items
                else "모든 항목이 배점에 반영되었습니다."
            )

        # =========================================================
        # 2026-08-05 추가: Forward(미래 추정) 데이터가 없는 종목은 종목 전체를 차단하지 않고
        # 이 섹션만 마스크 처리합니다 (ENGINEERING_SPEC.md 0-3 원칙 — Trailing은 정상 노출).
        # =========================================================
        # =========================================================
        # 2026-08-06: Forward 카드를 마스킹해야 하는 사유를 한 곳에서 판정합니다.
        # (배당 미확정 케이스는 guardrail.py가 이미 dividend_data_unverified로 표시해뒀으므로 제외)
        # 우선순위: 배당 미확정 > 역성장 > PER 극단치 > g_eff 산출불가 > 일반 검증 실패 > Forward 결측 > 정상
        # =========================================================
        # was_blocked: 예전 같으면 전체 마스킹 카드로 갔을 종목(퀀트 점수 산출이 스킵된 상태)만 대상으로 삼습니다.
        # g_eff<=0 자체는 guardrail.py에서 이미 정상(is_valid=True) 처리라, 검증까지 다 통과한 종목은
        # 이 분기를 타지 않고 원래대로 실제 점수 + 빨간 "역성장" 배지가 붙은 정상 카드로 렌더링됩니다.
        was_blocked = (not s.get('is_valid', True)) or s.get('is_unverified', False)
        is_per_extreme = was_blocked and ('PER' in reject_reason)
        is_geff_missing = was_blocked and ('실효성장률' in reject_reason)
        is_negative_growth_case = was_blocked and (
            bool(s.get('is_negative_growth')) or (s.get('g_eff') is not None and s['g_eff'] <= 0)
        )
        is_generic_harness_fail = (
            was_blocked
            and not is_per_extreme and not is_geff_missing and not is_negative_growth_case
            and not s.get('forward_data_missing')
        )
        forward_needs_mask = bool(
            s.get('dividend_data_unverified') or is_negative_growth_case or is_per_extreme
            or is_geff_missing or is_generic_harness_fail or s.get('forward_data_missing')
        )

        # 2026-08-05 추가, 2026-08-06 위치 변경: Trailing EPS·BPS만으로 구할 수 있는
        # 그레이엄 넘버(Graham Number)를 참고용으로 보여줍니다 (성장률 예측 불필요).
        # ⚠️ 오너 요청(2026-08-06): 예전엔 Forward 마스크 박스 안에 중첩되어 있었으나,
        # 이 값은 Trailing 지표에서만 산출되므로 Trailing 섹션 바로 아래(Forward 섹션과는 별개)로 옮깁니다.
        # Forward 카드가 어떤 사유로든 마스킹되는 모든 경우에 참고용으로 함께 보여줍니다.
        # =========================================================
        # ⚠️ 2026-08-06 2차 감사 3-2: 방어적 크로스체크
        # 수집기(1-1)에서 PER/EPS 부호가 유실되면 적자 기업에도 그레이엄 넘버가 산출되어,
        # "🚨 적자 기업 — 산출 불가" 배너 바로 아래에 목표가가 나란히 표시되는 자기모순이
        # 생깁니다(실제로 24종목에서 발생). 수집기를 고쳤더라도 화면 쪽에서 한 번 더 막습니다
        # — 표시 로직은 데이터가 모순이어도 절대 모순된 화면을 만들지 않아야 합니다.
        # =========================================================
        is_loss_making = bool(
            s.get('is_trailing_loss')
            or (t_roe_val is not None and t_roe_val < 0)
            or (s.get('t_eps') is not None and s.get('t_eps') <= 0)
            or (s.get('t_per_measured') is not None and s.get('t_per_measured') < 0)
        )

        graham_box_html = ""
        if forward_needs_mask:
            graham_target = s.get('graham_target')
            graham_is_fin = s.get('graham_is_financial_sector', False)
            if is_loss_making:
                # 적자 기업은 √(22.5×EPS×BPS) 의 제곱근 안이 음수가 되어 수학적으로 산출
                # 불가능합니다. 스냅샷에 값이 남아 있더라도(구버전/수집 오류) 표시하지 않습니다.
                loss_reason = ", ".join(s.get('loss_evidence') or []) or f"Trailing ROE {fmt_num(t_roe_val, '%')}"
                graham_box_html = f"""
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px dashed #475569; border-radius: 10px; padding: 14px 20px; text-align: center; margin-bottom: 14px;">
                    <div style="color: #94a3b8; font-size: 12.5px; font-weight: 700;">🧮 그레이엄 넘버 산출 불가 — 적자 기업 (EPS가 0 이하라 제곱근 안이 음수가 됩니다)</div>
                    <div style="color: #64748b; font-size: 11.5px; font-weight: 600; margin-top: 4px;">판정 근거: {loss_reason}</div>
                </div>
                """
            elif graham_target is not None and graham_is_fin:
                # 금융주(은행/보험/증권 등)는 그레이엄 넘버의 전제(제조업 장부가)가 잘 안 맞으므로
                # 값은 보여주되 강한 경고 배지를 붙입니다 (오너 요청 — 배제하지 않고 경고로 표시).
                graham_box_html = f"""
                <div style="background-color: rgba(127, 29, 29, 0.35); border: 2px solid #f87171; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;">
                    <div style="color: #fca5a5; font-size: 13px; font-weight: 800; margin-bottom: 6px;">⚠️⚠️ 강한 경고: 금융업종 — 그레이엄 넘버 적용 부적합 가능성 높음</div>
                    <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">🧮 {graham_target:,.0f}원 <span style="font-size: 12px; color: #fca5a5; font-weight: 700;">(Trailing 전용 참고 목표가)</span></div>
                    <p style="color: #fecaca; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
                        은행/보험/증권 등은 장부가(BPS)의 의미가 제조업과 달라, 이 공식(√22.5×EPS×BPS)의 전제가 잘 맞지 않습니다.<br>
                        참고 수준으로만 활용하고, 이 숫자를 실제 목표주가로 신뢰하지 마세요.
                    </p>
                </div>
                """
            elif graham_target is not None:
                graham_box_html = f"""
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #475569; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px;">
                    <div style="color: #94a3b8; font-size: 13px; font-weight: 700; margin-bottom: 6px;">🧮 Trailing 전용 참고 목표가 (Graham Number)</div>
                    <div style="color: #f1f5f9; font-size: 20px; font-weight: 900;">{graham_target:,.0f}원</div>
                    <p style="color: #94a3b8; font-size: 12px; font-weight: 600; margin: 8px 0 0 0; line-height: 1.5;">
                        성장률 예측 없이 √(22.5 × Trailing EPS × BPS) 공식(벤저민 그레이엄)으로만 산출한 참고값입니다.<br>
                        고성장 기업에는 보수적으로(낮게) 나올 수 있으니 유일한 판단 근거로 쓰지 마세요.
                    </p>
                </div>
                """
            else:
                graham_box_html = """
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px dashed #475569; border-radius: 10px; padding: 14px 20px; text-align: center; margin-bottom: 14px;">
                    <div style="color: #64748b; font-size: 12.5px; font-weight: 700;">🧮 그레이엄 넘버 산출 불가 (적자 기업 — EPS가 0 이하라 수학적으로 계산할 수 없음)</div>
                </div>
                """

        # =========================================================
        # 2026-08-06 추가: 배당 필수 업종(리츠/인프라/금융)인데 DPS·배당수익률이 0으로 수집된 경우.
        # 예전엔 종목 전체를 차단했으나(오너 지적: 실제 무배당 기업도 많아 과잉 차단), Trailing 지표와
        # 퀀트 점수는 정상 노출하고 Forward 카드 자리에만 노란색 확인-필요 배지를 띄웁니다.
        # =========================================================
        if s.get('dividend_data_unverified'):
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(120, 53, 15, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #facc15; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #92400e; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #fbbf24; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #fde047; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #fde047; font-weight: 500; white-space: nowrap;">🛡️ 배당 데이터 확인 필요</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #92400e; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">🛡️</div>
                    <h4 style="color: #fbbf24; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">주주환원 데이터 검증 대기 중</h4>
                    <p style="color: #fef08a; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        {s.get('dividend_unverified_reason', '리츠/인프라/금융 등 배당 필수 업종인데 DPS·배당수익률이 0으로 수집되었습니다.')}<br>
                        위 <b>Trailing(과거 실적)</b> 지표와 퀀트 점수는 수집된 값 그대로 정상 반영되어 있으니 참고해 주세요.
                    </p>
                </div>
            </div>
            """
        elif is_negative_growth_case:
            # 🟣 역성장/무성장 — 예전엔 종목 전체를 가렸으나, Trailing 재무제표 자체는 정상 존재하므로
            # Forward 카드 자리에만 마스킹합니다(오너 요청, 2026-08-06).
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(59, 7, 100, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #a855f7; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #6d28d9; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #d8b4fe; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #c4b5fd; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #c4b5fd; font-weight: 500; white-space: nowrap;">📉 역성장 · 무성장</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #6d28d9; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">📉</div>
                    <h4 style="color: #d8b4fe; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">실효성장률(g_eff) 0% 이하 — 가치 훼손 구간</h4>
                    <p style="color: #e9d5ff; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        본 종목은 <b>ROE {fmt_num(s.get('t_roe'), '%')}</b> 기준 실효성장률(성장률+주주환원율)이 0 이하로 계산되어,<br>
                        성장을 전제로 하는 PEGY 밸류에이션 적용이 부적합합니다.<br>
                        위 <b>Trailing(과거 실적)</b> 지표는 참고하실 수 있으나, 퀀트 종합점수는 이 사유로 산출되지 않습니다.
                    </p>
                </div>
            </div>
            """
        elif is_per_extreme:
            # 🔴 Forward PER 극단치/데이터 오염 — Forward PER 계산에만 생긴 문제라 Trailing은 정상 노출합니다.
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(69, 10, 10, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #f87171; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #991b1b; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #fca5a5; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #fecaca; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #fecaca; font-weight: 500; white-space: nowrap;">🚫 PER 극단치</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #991b1b; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">🚫</div>
                    <h4 style="color: #fca5a5; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">Forward PER 산출 범위 초과</h4>
                    <p style="color: #fecaca; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        애널리스트 컨센서스 기반 Forward PER이 정상 범위(300배)를 크게 벗어나 신뢰할 수 없습니다.<br>
                        위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. 퀀트 종합점수는 산출되지 않습니다.
                    </p>
                </div>
            </div>
            """
        elif is_geff_missing:
            # 🔵 Forward 데이터는 있는데 실효성장률(g_eff)만 계산 불가 — Trailing은 정상 노출합니다.
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(51, 65, 85, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #64748b; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #334155; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #94a3b8; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #64748b; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #64748b; font-weight: 500; white-space: nowrap;">🔒 실효성장률 산출 불가</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">🔒</div>
                    <h4 style="color: #cbd5e1; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">실효성장률(g_eff) 산출 불가</h4>
                    <p style="color: #94a3b8; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        Forward 컨센서스는 있지만, 성장률·주주환원율 계산에 필요한 값이 부족해 g_eff를 구하지 못했습니다.<br>
                        위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. 퀀트 종합점수는 산출되지 않습니다.
                    </p>
                </div>
            </div>
            """
        elif is_generic_harness_fail:
            # 🟡 상위 3단계 데이터 검증 하네스 통과 실패 — Trailing 원천값들끼리의 교차검증 문제라
            # PBR/DPS/EV-EBITDA 등 다른 지표는 영향받지 않으므로 Trailing은 정상 노출합니다.
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(120, 53, 15, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #facc15; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #92400e; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #fbbf24; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #fde047; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #fde047; font-weight: 500; white-space: nowrap;">🛡️ 데이터 검증 실패</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #92400e; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">🛡️</div>
                    <h4 style="color: #fbbf24; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">데이터 검증 실패 (PER·EPS 교차검증)</h4>
                    <p style="color: #fef08a; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        수집 단계의 데이터 검증(DataValidator)을 통과하지 못했습니다:<br>
                        <b>{unverified_reason or '사유 미상'}</b><br>
                        위 <b>Trailing(과거 실적)</b> 지표는 참고용으로 노출되며, 퀀트 종합점수는 검증 통과 전까지 산출되지 않습니다.
                    </p>
                </div>
            </div>
            """
        elif s.get('forward_data_missing'):
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(51, 65, 85, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px dashed #64748b; border-radius: 12px; padding: 16px 22px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #334155; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #94a3b8; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #64748b; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #64748b; font-weight: 500; white-space: nowrap;">🔒 데이터 없음</span>
                </div>
                <div style="background-color: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px; padding: 26px 24px; text-align: center;">
                    <div style="font-size: 30px; margin-bottom: 8px;">🔒</div>
                    <h4 style="color: #cbd5e1; font-size: 15.5px; font-weight: 800; margin: 0 0 6px 0;">예상 실적(Forward) 데이터 없음</h4>
                    <p style="color: #94a3b8; font-size: 13px; font-weight: 600; margin: 0; line-height: 1.5;">
                        이 종목은 증권사 애널리스트 컨센서스(추정 PER·EPS) 커버리지가 없어 네이버에도 데이터가 없습니다.<br>
                        위 <b>Trailing(과거 실적)</b> 지표는 정상 산출되었으니 참고해 주세요. PEGY 점수(35점)만 배점에서 제외됩니다.
                    </p>
                </div>
            </div>
            """
        else:
            forward_section_html = f"""
            <div style="background: linear-gradient(135deg, rgba(14, 116, 144, 0.35) 0%, rgba(15, 23, 42, 0.95) 100%); border: 2px solid #38bdf8; border-radius: 12px; padding: 16px 22px; box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);">
                <div style="display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1.5px solid #0284c7; padding-bottom: 8px; margin-bottom: 14px;">
                    <div>
                        <div style="font-size: 16px; font-weight: 800; color: #38bdf8; line-height: 1.2;">🚀 Forward</div>
                        <div style="font-size: 13px; font-weight: 600; color: #7dd3fc; margin-top: 2px;">(미래 추정 밸류 분석)</div>
                    </div>
                    <span style="font-size: 11.5px; color: #7dd3fc; font-weight: 500; white-space: nowrap;">*네이버 '추정 PER·EPS' 컨센서스 기반 (변동성 확대 시 정도에 비례한 벌점 반영, 1.05~1.40x)</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 24px 16px; align-items: flex-start; margin-top: 10px;">
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE</b><br>네이버 재무제표의 애널리스트 컨센서스 연간 추정치입니다.<br>커버리지가 없는 종목은 값을 만들어내지 않고 '데이터 없음'으로 둡니다.</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{fmt_num(s.get('f_roe'), '%', 1)}{roe_gap_badge_html}</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">가치 지표 ℹ️<span class="q-tooltiptext"><b>Forward 밸류에이션</b><br>• PER: 주가 / 12개월 추정 EPS<br>• EPS: 향후 12개월 예상 주당순이익</span></span>
                        </div>
                        <div style="font-size: 18px; color: #f1f5f9; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward PER ℹ️<span class="q-tooltiptext">내년에 벌어들일 돈에 비해 현재 주가가 몇 배인가? (낮을수록 저렴)</span></span> {fmt_num(s.get('f_per'), '배', 2)} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">Forward EPS ℹ️<span class="q-tooltiptext">주식 1주가 내년 1년 동안 벌어들일 것으로 예상되는 순수익(원)</span></span> {fmt_num(s.get('f_eps'), '원', 0)}
                        </div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">예상 성장률 ℹ️<span class="q-tooltiptext"><b>예상 EPS 성장률 (%)</b><br>네이버 '추정 EPS(컨센서스)' 와 'TTM EPS' 의 실제 증감률입니다.<br>둘 중 하나라도 수집되지 않으면 값을 만들지 않고 '데이터 없음'으로 둡니다.</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #4ade80;">{growth_disp}{growth_capped_badge_html}</div>
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
                                    <span class="q-tooltip" style="color: #14b8a6; font-weight: 700;">목표가 (Target) ℹ️<span class="q-tooltiptext" style="color: #f1f5f9; font-weight: 400;"><b>목표 적정주가 (Forward PEGY 역산)</b><br>PEGY(=PER÷실효성장률) 공식을 거꾸로 풀어서 계산해요.<br><b>① 목표 PEGY</b> = 기준 1.0배 + ROE/ROIC 프리미엄(이익 창출력이 좋을수록 더 비싼 배수를 인정)<br><b>② 목표 PER</b> = 목표 PEGY × Forward 실효성장률(g_eff = 예상 성장률+주주환원율(배당 등), 변동성 벌점 반영)<br><b>③ 목표주가</b> = Forward EPS × 목표 PER<br>Forward EPS·PER은 네이버 '추정 컨센서스' 기반입니다.<br>다만 고성장 종목은 공식상 값이 발산하기 때문에 <b>목표 PER 25배 / 현재가의 2.5배</b> 상한을 둡니다. 상한에 걸린 종목에는 옆에 '🧮 상한 적용값' 배지가 붙습니다.</span></span>
                                </span>
                                <span class="price-text-target">{fmt_num(f_target, '원', 0)}{target_cap_badge_html}</span>
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
            """

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
                        <span class="q-tooltip" style="color: #fef08a;">🏆 퀀트 스코어 ℹ️<span class="q-tooltiptext"><b>종합 퀀트 스코어</b><br>이 회사가 얼마나 돈을 잘 벌고, 주주에게 잘 나눠주고, 가격이 싼지를 종합적으로 채점한 점수예요!<br>수집하지 못한 지표는 점수를 지어내지 않고 배점에서 아예 제외합니다.<br>{score_tooltip_extra}</span></span> {score_badge_html}
                    </span>
                    <span style="background-color: {s['badge_bg']}; color: {s['badge_fg']}; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 12px; border: 1px solid {s['badge_fg']}; white-space: nowrap;">
                        {s['badge']}
                    </span>
                    <span style="font-size: 12px; color: {vol_color}; font-weight: 600; background-color: rgba(15, 23, 42, 0.6); padding: 4px 10px; border-radius: 6px; border: 1px solid #334155; white-space: nowrap;">{vol_text}</span>
                    {trap_badge_html}
                    {discrepancy_badge_html}
                </div>
                <div style="display: flex; align-items: baseline; gap: 8px;">
                    <span style="font-size: 13px; color: #94a3b8;">현재가:</span>
                    <span style="font-size: 25px; font-weight: 900; color: #38bdf8;">{s['price']:,.0f}원</span>
                </div>
            </div>

            {"" if (t_roe_val is None or t_roe_val >= 0) else f'''
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
                <!-- 2026-08-06 2차 감사 3-1: 여기 있던 하드코딩 숫자 '99.99'를 삭제했습니다.
                     적자라서 PEGY를 산출하지 못한 자리에 18px 볼드로 큰 숫자가 박혀 있으면
                     사용자에게는 그게 이 종목의 PEGY 값으로 읽힙니다(1차 감사 §3-3 "PEGY 99.0" 잔재).
                     값이 없으면 값을 쓰지 않습니다 (ENGINEERING_SPEC §0-1). -->
                <div style="background: #991b1b; border: 1px solid #f87171; border-radius: 8px; padding: 6px 14px; text-align: center; flex-shrink: 0;">
                    <div style="color: #f87171; font-size: 18px; font-weight: 900;">—</div>
                    <div style="color: #fca5a5; font-size: 10px; font-weight: 600;">PEGY 산출 불가</div>
                </div>
            </div>
            '''}

            <!-- 2. 자본효율성 품질 바 (Quality Bar) -->
            <div style="background-color: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 8px; padding: 9px 18px; margin-bottom: 14px; display: flex; align-items: center; justify-content: flex-start; gap: 28px; flex-wrap: wrap;">
                <span style="color: #94a3b8; font-weight: 700; font-size: 13px;">💎 자본효율성 지표:</span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Trailing ROE ℹ️<span class="q-tooltiptext"><b>Trailing ROE (자기자본이익률)</b><br>지난 12개월(4분기 합산) 순이익을 자기자본으로 나눈 자본 효율성 지표입니다. 8% 미만 시 이익 창출력이 부족한 상태입니다.</span></span>: 
                    <b style="color: {roe_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(t_roe_val, '%', 1)}</b>
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">Forward ROE ℹ️<span class="q-tooltiptext"><b>Forward ROE (예상 자기자본이익률)</b><br>네이버 재무제표의 애널리스트 컨센서스 연간 추정치입니다.<br>커버리지가 없는 종목은 값을 추정해 채우지 않고 '데이터 없음'으로 표시합니다.</span></span>:
                    <b style="color: #38bdf8; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(s.get('f_roe'), '%', 1)}</b>{roe_gap_badge_html}
                </span>
                <span style="font-size: 13px; color: #e2e8f0;">
                    <span class="q-tooltip">ROIC (ROC) ℹ️<span class="q-tooltiptext"><b>ROIC (영업 투입자본이익률)</b><br>영업이익 ÷ 투하자본으로 별도 산출해야 하는 지표입니다.<br>현재 이 프로젝트는 해당 원천 데이터를 수집하지 않으므로 '데이터 없음'으로 표시합니다.</span></span>:
                    <b style="color: {roic_color}; font-weight: 700; font-size: 14px; margin-left: 4px;">{fmt_num(roic_val, '%', 1)}</b>
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
                        <div style="font-size: 18px; font-weight: 800; color: #cbd5e1;">{fmt_num(t_roe_val, '%', 1)}</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">가치 및 회수 지표 ℹ️<span class="q-tooltiptext"><b>Trailing 밸류에이션</b><br>• PER: 주가/순이익<br>• EPS: 주당순이익<br>• PBR: 주가/순자산<br>• EV/EBITDA: M&A 투자원금 회수기간</span></span>
                        </div>
                        <div style="font-size: 18px; color: #cbd5e1; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PER ℹ️<span class="q-tooltiptext">1년 동안 번 돈에 비해 주가가 몇 배인가? (낮을수록 저렴)</span></span> {fmt_num(s.get('t_per'), '배', 2)} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EPS ℹ️<span class="q-tooltiptext">주식 1주가 1년 동안 벌어온 순수익(원)</span></span> {t_eps_str if t_eps_str == "데이터 없음" else t_eps_str + "원"}{calc_eps_tag} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">PBR ℹ️<span class="q-tooltiptext">회사 전 재산을 다 팔았을 때 가치 대비 주가가 몇 배인가? (1배 이하면 바겐세일)</span></span> {t_pbr_str if t_pbr_str == "데이터 없음" else t_pbr_str + "배"}
                        </div>
                        <div style="font-size: 18px; color: #38bdf8; font-weight: 800; letter-spacing: -0.4px;">
                            <span class="q-tooltip" style="font-size: 13px; font-weight: 800; color: #94a3b8; border-bottom: 1px dotted #475569;">EV/EBITDA (M&A 원금회수) ℹ️<span class="q-tooltiptext">회사를 통째로 샀을 때, 장사해서 본전 뽑는 기간</span></span> {ev_ebitda_str if ev_ebitda_str == "데이터 없음" else ev_ebitda_str + "배"}{ev_years_str.replace("11px", "13px")}
                        </div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">작년 배당률 (확정) ℹ️<span class="q-tooltiptext"><b>주주환원 세부 내역 — 가장 최근 마감된 회계연도 기준</b><br>배당은 실제 지급돼야 확정되는 값이라, 아래 수치는 올해 실제 지급 내역이 아니라 <b>작년(가장 최근 확정 회계연도)</b> 재무제표 기준입니다.<br>• 1주당 배당금 (DPS): {dps_str}<br>• 배당 총 규모: {s.get('return_total', '데이터 없음')}<br>• 배당수익률: {fmt_num(s.get('sh_return'), '%', 2)}<br>※ {s.get('sh_return_basis', '배당수익률만 반영 (자사주 매입 공시 미수집)')}</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #86efac;">DPS {dps_str}{calc_dps_tag} <span style="color: #475569; font-size: 15px; margin: 0 4px;">|</span> 배당수익률 {fmt_num(s.get('sh_return'), '%', 2)} <span style="font-size: 13px; color: #94a3b8;">({s.get('return_total', '데이터 없음')})</span></div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 6px;">
                            <span class="q-tooltip">PEGY / 과거 적정가 ℹ️<span class="q-tooltiptext"><b>Trailing PEGY & 과거 적정주가</b><br>• PEGY: PER / (성장률 + 주주환원율)<br>• 과거 적정가: 과거 실적 기준 퀀트 타겟 주가</span></span>
                        </div>
                        <div style="font-size: 18px; font-weight: 800; color: #38bdf8;">{fmt_num(s.get('t_pegy'), '', 2)} <span style="color: #475569; font-size: 15px; margin: 0 4px;">/</span> {fmt_num(s.get('t_fair'), '원', 0)}</div>
                    </div>
                </div>
            </div>

            <!-- 3-1. 그레이엄 넘버(Trailing 전용 참고 목표가) - Forward 마스크와 무관하게 Trailing 바로 아래 표시 -->
            {graham_box_html}

            <!-- 4. Forward 섹션 (미래 추정 밸류 분석 - 데이터 없으면 이 섹션만 마스크 처리) -->
            {forward_section_html}
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
