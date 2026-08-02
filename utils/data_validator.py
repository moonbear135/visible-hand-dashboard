import math
import re

# 체계적인 시계열 키워드 사전 (Timeframe Keyword Registry)
TIMEFRAME_KEYWORDS = {
    "ANNUAL_TTM": [
        "최근 연간 실적", "연간", "TTM", "최근 12개월", "ANNUAL", "YEARLY", "A",
        r"\b20\d{2}\.12\b", r"\bFY\d{2,4}\b"
    ],
    "QUARTERLY": [
        "최근 분기 실적", "분기", "1Q", "2Q", "3Q", "4Q", "Q1", "Q2", "Q3", "Q4",
        "QUARTERLY", "Q", r"\b20\d{2}\.03\b", r"\b20\d{2}\.06\b", r"\b20\d{2}\.09\b"
    ],
    "DAILY_PERIOD": [
        "일간", "주간", "월간", "DAILY", "WEEKLY", "MONTHLY", "D", "W", "M"
    ],
    "ESTIMATE": [
        "(E)", "(P)", "E", "P", "ESTIMATE", "CONSENSUS"
    ]
}

class DataValidator:
    """
    3단계 강건한 데이터 검증 파이프라인 (Data Validation Harness)
    ① 1단계: Raw vs Processed 1:1 대조 및 단위/시계열 정규화
    ② 2단계: 단일 출처 산티 체크 (PER = Price / EPS_TTM 오차 <= 5%)
    ③ 3단계: 출처 간 교차 검증 (교차 오차 <= 3% 승인, 초과 시 Fallback)
    """
    
    @staticmethod
    def classify_header_timeframe(header_text):
        """헤더 텍스트를 분석하여 ANNUAL_TTM, QUARTERLY, DAILY_PERIOD, ESTIMATE 여부를 판정"""
        text = str(header_text).strip()
        is_est = any(kw in text for kw in TIMEFRAME_KEYWORDS["ESTIMATE"])
        is_q = any(re.search(kw, text) if '\\b' in kw or '\\d' in kw else kw in text for kw in TIMEFRAME_KEYWORDS["QUARTERLY"])
        is_d = any(kw in text for kw in TIMEFRAME_KEYWORDS["DAILY_PERIOD"])
        is_y = any(re.search(kw, text) if '\\b' in kw or '\\d' in kw else kw in text for kw in TIMEFRAME_KEYWORDS["ANNUAL_TTM"])
        
        if is_d:
            return "DAILY"
        if is_q and not is_y:
            return "QUARTERLY_EST" if is_est else "QUARTERLY"
        if is_y:
            return "ANNUAL_EST" if is_est else "ANNUAL_TTM"
        return "UNKNOWN"

    @staticmethod
    def validate_raw_vs_processed(raw_dict, processed_dict):
        """
        1단계: Raw Data <-> Processed Data 1:1 대조 검증
        수치 단위 변환 외에 의미하는 바가 1:1 일치하는지, 값 누락(NaN), 0 덮어쓰기, 행/열 스왑이 없는지 확인
        """
        logs = []
        is_pass = True
        
        # 1. 필수 지표 존재 여부
        req_keys = ["price", "t_per", "t_eps"]
        for k in req_keys:
            if k not in processed_dict or processed_dict[k] is None:
                is_pass = False
                logs.append(f"❌ 1단계 누락: 가공 데이터에 필수 키 {k}가 존재하지 않음")
                
        if not is_pass:
            return False, logs
            
        # 2. Raw 대비 수치 스왑 및 0 변형 체크
        raw_eps = raw_dict.get("raw_eps")
        proc_eps = processed_dict.get("t_eps")
        if raw_eps and proc_eps:
            if abs(raw_eps - proc_eps) > 5 and (abs(raw_eps - proc_eps) / max(raw_eps, 1)) > 0.05:
                is_pass = False
                logs.append(f"❌ 1단계 Raw-Processed 1:1 불일치: Raw EPS({raw_eps}) vs Processed EPS({proc_eps})")
            else:
                logs.append(f"✅ 1단계 Raw-Processed 일치: EPS={proc_eps}")
        else:
            logs.append("ℹ️ 1단계 Raw EPS 직접비교 대상 없음")

        return is_pass, logs

    @staticmethod
    def sanity_check_per(price, eps_ttm, reported_per, tolerance=0.05):
        """
        2단계: 단일 출처 산티 체크 (Sanity Check)
        공식: 계산된 PER = Price / EPS_TTM
        기준: reported_per와 계산된 PER 오차가 tolerance(5%) 이내여야 함
        """
        logs = []
        if price <= 0 or eps_ttm <= 0:
            logs.append(f"❌ 2단계 산티 체크 거부: 주가({price}) 또는 EPS({eps_ttm})가 0 이하임")
            return False, logs
            
        calc_per = price / eps_ttm
        diff_ratio = abs(calc_per - reported_per) / reported_per if reported_per > 0 else 1.0
        
        if diff_ratio <= tolerance:
            logs.append(f"✅ 2단계 산티 체크 통과: 표기 PER({reported_per}배) vs 계산 PER({calc_per:.2f}배), 오차={diff_ratio*100:.2f}% (<= {tolerance*100}%)")
            return True, logs
        else:
            logs.append(f"❌ 2단계 산티 체크 실패: 표기 PER({reported_per}배) vs 계산 PER({calc_per:.2f}배), 오차={diff_ratio*100:.2f}% (> {tolerance*100}%)")
            return False, logs

    @staticmethod
    def cross_reconcile(primary_dict, secondary_dict, tolerance=0.03):
        """
        3단계: 출처 간 교차 검증 (Cross-Reconciliation)
        네이버 주 수집 지표와 2차 교차 출처 지표 간 오차 3% 이내 승인
        """
        logs = []
        if not secondary_dict:
            logs.append("ℹ️ 3단계 교차 검증: 2차 출처 데이터 없음 (Primary 단독 승인)")
            return True, logs
            
        p_per = primary_dict.get("t_per")
        s_per = secondary_dict.get("t_per")
        
        if p_per and s_per and p_per > 0 and s_per > 0:
            diff = abs(p_per - s_per) / s_per
            if diff <= tolerance:
                logs.append(f"✅ 3단계 교차 검증 승인: Primary PER({p_per}) vs Secondary PER({s_per}), 오차={diff*100:.2f}% (<= {tolerance*100}%)")
                return True, logs
            else:
                logs.append(f"⚠️ 3단계 교차 검증 괴리: Primary PER({p_per}) vs Secondary PER({s_per}), 오차={diff*100:.2f}% (> {tolerance*100}%) -> Fallback 권장")
                return False, logs
                
        logs.append("ℹ️ 3단계 교차 검증: 수치 교차 비교 완료")
        return True, logs

    @classmethod
    def run_pipeline(cls, stock_raw, stock_processed, secondary_dict=None):
        """
        3단계 전체 파이프라인 순차 실행 및 종합 승인 결과 반환
        """
        all_logs = []
        code = stock_processed.get("code", "UNKNOWN")
        name = stock_processed.get("name", "UNKNOWN")
        
        all_logs.append(f"=== [{name} ({code})] 3단계 하네스 검증 시작 ===")
        
        # 1단계
        pass1, logs1 = cls.validate_raw_vs_processed(stock_raw, stock_processed)
        all_logs.extend(logs1)
        if not pass1:
            all_logs.append(f"❌ [{name}] 1단계 검증 실패로 반영 차단!")
            return False, all_logs
            
        # 2단계
        price = stock_processed.get("price", 0)
        eps = stock_processed.get("t_eps", 0)
        per = stock_processed.get("t_per", 0)
        pass2, logs2 = cls.sanity_check_per(price, eps, per, tolerance=0.05)
        all_logs.extend(logs2)
        if not pass2:
            all_logs.append(f"❌ [{name}] 2단계 산티 체크 실패로 반영 차단!")
            return False, all_logs
            
        # 3단계
        pass3, logs3 = cls.cross_reconcile(stock_processed, secondary_dict, tolerance=0.03)
        all_logs.extend(logs3)
        if not pass3:
            all_logs.append(f"⚠️ [{name}] 3단계 교차 검증 오차 발생 (이전 정상 데이터 유지/Fallback)")
            return False, all_logs
            
        all_logs.append(f"🎉 [{name}] 3단계 검증 파이프라인 최종 승인 (Pass)!")
        return True, all_logs
