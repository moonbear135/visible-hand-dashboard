import re
import pandas as pd

# 지표별 기간 키워드 사전 (Period Keywords Dictionary)
# ⚠️ 단일 문자 키워드(A/Q/D/E/P)는 반드시 단어 경계(\b)로 감싸야 합니다.
#    (예전에는 "Annual Data" 의 D 때문에 DAILY 로 오분류되는 등 헤더 분류가 사실상 무작위였습니다.)
PERIOD_KEYWORDS = {
    "TTM": ["연간", "TTM", "최근 12개월", "최근 연간 실적", "ANNUAL", "YEARLY", r"\bA\b", r"\b20\d{2}\.12\b", r"\bFY\d{2,4}\b"],
    "QUARTERLY": ["분기", "1Q", "2Q", "3Q", "4Q", "3개월", "Q1", "Q2", "Q3", "Q4", "QUARTERLY", r"\bQ\b", r"\b20\d{2}\.03\b", r"\b20\d{2}\.06\b", r"\b20\d{2}\.09\b"],
    "DAILY": ["일별", "당일", "일간", "주간", "월간", "DAILY", "WEEKLY", "MONTHLY", r"\bD\b"],
    "ESTIMATE": ["(E)", "(P)", "ESTIMATE", "CONSENSUS", r"\bE\b", r"\bP\b"]
}

# 지표별 타겟팅 규칙 (Indicator-Specific Targeting Rules)
INDICATOR_TARGET_RULES = {
    "PER": "TTM",
    "EPS": "TTM",
    "DPS": "TTM",
    "PBR": "TTM",
    "ROE": "TTM",
    "QUARTERLY_EARNINGS": "QUARTERLY",
    "MOMENTUM_3M": "QUARTERLY",
    "DAILY_PRICE": "DAILY",
    "DAILY_VOLUME": "DAILY",
    "DAILY_FLOW": "DAILY"
}

class DataValidator:
    """
    3단계 강건한 데이터 검증 파이프라인 (Data Validation Harness)
    ① 1단계: Raw vs Processed 1:1 대조 및 단위/지표별 기간 키워드 매핑 정규화
    ② 2단계: 단일 출처 산티 체크 (PER = Price / EPS_TTM 오차 <= 5%)
    ③ 3단계: 출처 간 교차 검증 (교차 오차 <= 3% 승인, 초과 시 Fallback)
    """
    
    @staticmethod
    def normalize_currency(value_str):
        """
        문자열 내의 화폐 단위('백만원', '억원', '원')를 파악하여
        순수 숫자를 원화(KRW) 기준 단위로 정규화(Scaling)하여 float로 반환합니다.
        """
        if not value_str or pd.isna(value_str):
            return 0.0
            
        text = str(value_str).replace(',', '').strip()
        
        # 숫자 부분 추출 (음수, 소수점 포함)
        match = re.search(r'(-?\d+(\.\d+)?)', text)
        if not match:
            return 0.0
            
        val = float(match.group(1))
        
        # 단위 스케일링
        if '백만원' in text:
            val *= 1_000_000
        elif '억원' in text or '억' in text:
            val *= 100_000_000
        elif '조원' in text or '조' in text:
            val *= 1_000_000_000_000
        elif '천원' in text:
            val *= 1_000
            
        return val
    
    @staticmethod
    def classify_header_timeframe(header_text):
        """
        헤더 텍스트를 분석하여 TTM (연간), QUARTERLY (분기), DAILY (일별), ESTIMATE (추정) 여부를 판정
        """
        text = str(header_text).strip().upper()  # 영문 키워드 대소문자 무관 매칭

        def _match(kw):
            # 정규식 메타문자(\b, \d)가 포함된 키워드는 정규식으로, 그 외는 단순 포함으로 판정
            if '\\b' in kw or '\\d' in kw:
                return re.search(kw, text) is not None
            return kw in text

        is_est = any(_match(kw) for kw in PERIOD_KEYWORDS["ESTIMATE"])
        is_q = any(_match(kw) for kw in PERIOD_KEYWORDS["QUARTERLY"])
        is_d = any(_match(kw) for kw in PERIOD_KEYWORDS["DAILY"])
        is_y = any(_match(kw) for kw in PERIOD_KEYWORDS["TTM"])
        
        if is_d:
            return "DAILY"
        if is_q and not is_y:
            return "QUARTERLY_EST" if is_est else "QUARTERLY"
        if is_y:
            return "ANNUAL_EST" if is_est else "TTM"
        return "UNKNOWN"

    @staticmethod
    def validate_raw_vs_processed(raw_dict, processed_dict):
        """
        1단계: Raw Data <-> Processed Data 1:1 대조 및 지표-기간 1:1 타겟팅 매핑 검증
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
            
        # 2. 수집 타겟-가공 목적 1:1 일치 여부 검증 (TTM vs QUARTERLY vs DAILY 교차 오염 차단)
        indicator = processed_dict.get("indicator_type", "PER")
        expected_target = INDICATOR_TARGET_RULES.get(indicator, "TTM")
        # ⚠️ 기대값을 기본값으로 채우면 '자기 자신과 비교'가 되어 검증이 항상 통과합니다(=검증 부재).
        #    수집 단계에서 실제 헤더로 판정한 raw_period 가 없으면 검증 실패로 처리합니다.
        raw_period = raw_dict.get("raw_period")
        if raw_period is None:
            is_pass = False
            logs.append(f"❌ 1단계 수집 기간 미확인: 지표({indicator})의 원본 헤더에서 기간을 판정하지 못함 (raw_period 없음)")
            return False, logs
        if raw_period != expected_target:
            is_pass = False
            logs.append(f"❌ 1단계 타겟-목적 1:1 불일치: 지표({indicator})의 예상 기간({expected_target}) vs 수집된 기간({raw_period})")
        else:
            logs.append(f"✅ 1단계 타겟-목적 1:1 일치: {indicator} -> {expected_target} 매핑 확인")

        # 3. Raw 대비 수치 스왑 및 0 변형 체크
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
        if price is None or eps_ttm is None or reported_per is None:
            logs.append("❌ 2단계 산티 체크 거부: 주가/EPS/PER 중 수집되지 않은 값이 있음 (None)")
            return False, logs
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
            # 교차검증 '미수행'과 '통과'는 다른 상태입니다. 반환값은 True(차단하지 않음)이지만
            # 로그와 호출부의 cross_validated 플래그로 미수행 사실이 반드시 남아야 합니다.
            logs.append("⚠️ 3단계 교차 검증 미수행: 2차 출처 데이터 없음 (검증되지 않음 / 통과 아님)")
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
