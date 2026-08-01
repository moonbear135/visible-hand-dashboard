import os
from datetime import datetime

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
    v1_elapsed = (current_time - AUDIT_TRAIL[0].date).days
    if v1_elapsed >= 60:
        print("[알림] 파라미터 정기 재검증(2개월) 주기가 도래했습니다. (버전 v1.0.0 기준 2개월 경과)")
    print("==================================================")

def main():
    check_governance_cycle()

if __name__ == "__main__":
    main()
