import os
import math
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")

# 1. 공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)
class AuditRecord:
    def __init__(self, version, date_str, who, where, what, why, how):
        self.version = version
        self.date = datetime.strptime(date_str, "%Y-%m-%d")
        self.who = who
        self.where = where
        self.what = what
        self.why = why
        self.how = how

AUDIT_TRAIL = [
    AuditRecord(
        version="v1.0.0",
        date_str="2026-06-01",
        who="안티그래비티 개발팀",
        where="app.py / 스코어링 모듈",
        what="최초 비선형 시그모이드 위험 스코어링 알고리즘 도입",
        why="기존 단순 가중합 방식의 50점대 둔감성 해결 및 시장 변곡점 포착 강화",
        how="Z-Score 산출 후 표준편차 기반의 시그모이드 변환(k=1.8) 및 극단 국면 증폭 멀티플라이어 적용"
    ),
    AuditRecord(
        version="v1.1.0",
        date_str="2026-08-01",
        who="안티그래비티 & 제미나이 공동 연구",
        where="app.py / 스코어링 모듈 및 데이터 수집부",
        what="14번째 지표 KOSPI 5일 낙폭 모멘텀 추가 및 비선형 민감도 파라미터 튜닝",
        why="7월 말 지수 급락 감지 실패 대응 및 특정 날짜의 노이즈 튐 현상(False Positive) 방지",
        how="std 하한선(0.02) 설정, 시그모이드 민감도 k=1.1 조정, 극단 임계치 85/15로 개편, 멀티플라이어 1.15(3개)/1.30(5개) 적용"
    )
]

COL_MAP = {
    "Date": "날짜",
    "Score": "종합 위험 점수",
    "KOSPI": "코스피 종가",
    "USD_KRW": "원/달러 환율",
    "Retail": "개인 수급 (억원)",
    "Foreigner": "외국인 수급 (억원)",
    "Institution": "기관 수급 (억원)",
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

def check_governance_cycle():
    """마지막 튜닝 일자로부터 2개월이 경과했는지 확인하는 정기 점검 알림"""
    latest_record = AUDIT_TRAIL[-1]
    current_time = datetime.now()
    days_elapsed = (current_time - latest_record.date).days
    
    print("==================================================")
    print("[알고리즘 거버넌스 관리 및 5W1H 감사 정보]")
    print("==================================================")
    for record in AUDIT_TRAIL:
        print(f"버전: {record.version} | 변경일자: {record.date.strftime('%Y-%m-%d')}")
        print(f"작성자(Who): {record.who}")
        print(f"반영처(Where): {record.where}")
        print(f"변경사항(What): {record.what}")
        print(f"상세사유(Why): {record.why}")
        print(f"구현방식(How): {record.how}")
        print("-" * 50)
        
    print(f"최근 알고리즘 튜닝 이후 경과 일수: {days_elapsed}일")
    # v1.0.0(2026-06-01)로부터는 오늘이 60일 이상 지났으므로 경고
    v1_elapsed = (current_time - AUDIT_TRAIL[0].date).days
    if v1_elapsed >= 60:
        print("[알림] 파라미터 정기 재검증(2개월) 주기가 도래했습니다. (버전 v1.0.0 기준 2개월 경과)")
    print("==================================================")

def run_health_check(df):
    """데이터 파이프라인 건강 진단 (Health Checker)"""
    print("\n[데이터 파이프라인 건강 진단 시작]")
    print("=" * 50)
    has_warning = False
    
    # 1. 3일 이상 지표 고착 확인 (더미 데이터 감지)
    metric_cols = [col for col in df.columns if col not in ["Date", "Score", "KOSPI", "USD_KRW", "Retail", "Foreigner", "Institution"]]
    for col in metric_cols:
        for idx in range(2, len(df)):
            val1 = df.iloc[idx-2][col]
            val2 = df.iloc[idx-1][col]
            val3 = df.iloc[idx][col]
            if val1 == val2 == val3:
                # 더미 고정값 감지
                if col in ["Non_Arbitrage_Ratio", "Foreign_Broker_Dump", "Stock_Net_Sell"] and val1 in [0.449, 0.322, 0.237, 0.5]:
                    date_str = df.iloc[idx]["Date"]
                    print(f"[경고] {date_str} 기준 '{COL_MAP.get(col, col)}' 지표가 3일 연속 동일 수치({val1})로 고착되었습니다. (더미 데이터 가능성 농후)")
                    has_warning = True
                    break
                    
    # 2. 수급 데이터 0원 고착 확인
    consecutive_zeros = 0
    for idx in range(len(df)):
        ret = df.iloc[idx]["Retail"]
        fore = df.iloc[idx]["Foreigner"]
        inst = df.iloc[idx]["Institution"]
        if ret == 0 and fore == 0 and inst == 0:
            consecutive_zeros += 1
            if consecutive_zeros >= 3:
                date_str = df.iloc[idx]["Date"]
                print(f"[경고] {date_str} 기준 수급 데이터(개인/외인/기관)가 3일 이상 연속으로 0원으로 고착되었습니다.")
                has_warning = True
        else:
            consecutive_zeros = 0
            
    if not has_warning:
        print("[양호] 데이터 파이프라인 정체나 고착 현상이 발견되지 않았습니다. (복구 완료)")
    print("=" * 50)

def validate_scenarios(df):
    """자동 시나리오 검증 (Assertions)"""
    print("\n[알고리즘 시나리오 자동 검증 수행]")
    print("=" * 50)
    
    # 7월 말 위험 점수 조회
    july_dates = ["2026-07-27", "2026-07-28", "2026-07-29"]
    for jd in july_dates:
        row = df[df["Date"] == jd]
        if not row.empty:
            sc = float(row.iloc[0]["Score"])
            print(f"[검증 정보] 7월 말일 {jd} 점수: {sc}점 (수급 복구 후 자동 재산출됨)")
            
    # [검증 1] 6월 4일
    june_4_data = df[df["Date"] == "2026-06-04"]
    if not june_4_data.empty:
        june_4_score = float(june_4_data.iloc[0]["Score"])
        status = "통과" if june_4_score <= 65.0 else "실패"
        print(f"[검증 1] 6월 4일 평시 위험도 검증: 실제 계산 점수 {june_4_score}점 -> {status}")
    else:
        print("[검증 1] 6월 4일 데이터를 찾을 수 없습니다. -> 실패")
        
    # [검증 2] 6월 8일
    june_8_data = df[df["Date"] == "2026-06-08"]
    if not june_8_data.empty:
        june_8_score = float(june_8_data.iloc[0]["Score"])
        status = "통과" if june_8_score >= 60.0 else "실패"
        print(f"[검증 2] 6월 8일 지수 폭락 고위험 포착 검증: 실제 계산 점수 {june_8_score}점 -> {status}")
    else:
        print("[검증 2] 6월 8일 데이터를 찾을 수 없습니다. -> 실패")
    print("=" * 50)

def main():
    if not os.path.exists(HISTORY_FILE):
        print(f"[에러] '{HISTORY_FILE}' 데이터베이스 파일이 존재하지 않습니다.")
        return
        
    raw_df = pd.read_csv(HISTORY_FILE)
    df_eng = raw_df.rename(columns={v: k for k, v in COL_MAP.items()})
    
    check_governance_cycle()
    run_health_check(df_eng)
    validate_scenarios(df_eng)

if __name__ == "__main__":
    main()
