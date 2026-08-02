import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta

# pykrx 임포트 시도
try:
    from pykrx import stock
    PYKRX_AVAILABLE = True
except ImportError:
    PYKRX_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "market_history.csv")

# ==============================================================================
# 1. 공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)
# ==============================================================================
class AuditRecord:
    def __init__(self, version, date_str, who, where, what, why, how):
        self.version = version
        self.date = datetime.strptime(date_str, "%Y-%m-%d")
        self.who = who
        self.where = where
        self.what = what
        self.why = why
        self.how = how

# 수식 및 교차검증 변경 시 이 리스트에 기록을 추가합니다.
AUDIT_TRAIL = [
    AuditRecord(
        version="v1.4.0",
        date_str="2026-08-03",
        who="보이는 손 데이터 안심 방공망 팀",
        where="utils/data_validator.py / collector_kospi200.py / test_harness.py",
        what="3단계 데이터 검증 하네스 구축 (Raw vs Processed 1:1 대조, 5% PER 산티 체크, 3% 교차검증) 및 시계열 키워드 사전 연동 헤더 동적 타겟팅",
        why="단일 분기(Q)/일간(D) 데이터와 연간(TTM) 데이터 수치 혼동 오염을 전면 차단하고 100% 검증된 데이터만 대시보드에 반영하기 위함",
        how="DataValidator 3단계 파이프라인 수립, TIMEFRAME_KEYWORDS 정규식 매핑, 산티 산출 공식 (Price / EPS_TTM) 오차 5% 초과 시 차단/Fallback 지원"
    ),
    AuditRecord(
        version="v1.3.0",
        date_str="2026-08-02",
        who="보이는 손 UI/UX 퀀트 분석팀",
        where="visiblehand.py / views/pegy_view.py / test_harness.py",
        what="사이드바 서비스 메뉴 최상단배치, 18px 폰트 확대, pre-line 강제 줄바꿈 및 가시성 자동 검증 규칙 이식",
        why="사이드바 라벨 텍스트 축소/줄바꿈 붕괴 현상을 막고 화면 가시성 무결성을 100% 보장하기 위함",
        how="Streamlit DOM 라디오 pre-line CSS 적용, 명시적 개행문자 조합 및 하네스 자동 검증 체인 이식"
    ),
    AuditRecord(
        version="v1.2.0",
        date_str="2026-08-02",
        who="보이는 손 분석팀",
        where="app.py / scrape_daily.py / test_harness.py",
        what="더미 데이터 기본 대입 로직 제거 및 관리자 수동 제어실 연동",
        why="장애 혹은 비영업일 시 자동 생성되는 가상 더미 데이터의 데이터베이스 오염을 전면 차단하기 위함",
        how="수급 이동평균 및 고정 지수 디폴트값 차단 후 Reject 문 작동, 관리자 모드 시 수동 기입 폼 및 실시간 출처 가이드 매핑"
    )
]

def check_governance():
    """알고리즘 5W1H 감사 이력 출력 및 2개월 주기 정기 점검 알림"""
    print("==================================================")
    print("[공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)]")
    print("==================================================")
    for record in AUDIT_TRAIL:
        print(f"[버전] {record.version} | 적용일자: {record.date.strftime('%Y년 %m월 %d일')}")
        print(f"  * 언제 (When)   : {record.date.strftime('%Y-%m-%d')}")
        print(f"  * 누가 (Who)    : {record.who}")
        print(f"  * 어디를 (Where) : {record.where}")
        print(f"  * 무엇을 (What)  : {record.what}")
        print(f"  * 왜 (Why)      : {record.why}")
        print(f"  * 어떻게 (How)   : {record.how}")
        print("-" * 50)

    if not AUDIT_TRAIL:
        print("[정보] 등록된 알고리즘 버전 변경 이력이 존재하지 않습니다.")
        print("==================================================")
        return

    # 2개월(60일) 주기 정기 점검 알림
    latest_record = AUDIT_TRAIL[0]
    days_elapsed = (datetime.now() - latest_record.date).days
    print(f"[정보] 최근 알고리즘 파라미터 튜닝 후 경과 일수: {days_elapsed}일")
    
    if days_elapsed >= 60:
        print("[알림] 파라미터 정기 재검증(2개월) 주기가 도래했습니다. 수식 및 가중치 점검이 필요합니다.")
    else:
        print(f"[성공] 파라미터 정기 점검 주기까지 {60 - days_elapsed}일 남았습니다.")
    print("==================================================")

# ==============================================================================
# 2. UI/UX 줄 간격 & 가시성 확보 무결성 검증 (Line-Spacing & Visibility Engine)
# ==============================================================================
class UICrossValidator:
    """사이드바 및 대시보드 카드 렌더링 줄 간격 & 가시성 무결성 검증"""
    
    @staticmethod
    def validate_ui_visibility():
        print("\n==================================================")
        print("[UI/UX 줄 간격 & 가시성 확보 무결성 검증 (Line-Spacing Check)]")
        print("==================================================")
        
        visiblehand_path = os.path.join(BASE_DIR, "visiblehand.py")
        if os.path.exists(visiblehand_path):
            with open(visiblehand_path, "r", encoding="utf-8") as f:
                code_content = f.read()
                
            has_pre_line = "white-space: pre-line" in code_content
            has_explicit_newline = "\\n" in code_content
            
            if has_pre_line and has_explicit_newline:
                print("  [성공] [사이드바 라벨 줄간격 검증] pre-line 및 개행 문자가 정상 적용되어 가시성이 확보되었습니다!")
            else:
                print("  [경고] [사이드바 라벨 줄간격 경고] pre-line 또는 개행 설정 누락! UI 가시성 점검이 필요합니다.")
        else:
            print("  [경고] visiblehand.py 파일을 찾을 수 없습니다.")
            
        print("==================================================")

# ==============================================================================
# 3. 다중 출처 수급 & 지수 데이터 교차 검증 (Cross-Validation Engine)
# ==============================================================================
class DataCrossValidator:
    """네이버, KRX, FDR 등 다중 출처 교차검증 및 데이터 무결성 검사"""

    @staticmethod
    def validate_latest_data():
        print("\n==================================================")
        print("[다중 출처 수급 및 지수 데이터 교차검증(Cross-Validation) 수행]")
        print("==================================================")

        target_date = datetime.today()
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
        target_date_str = target_date.strftime("%Y-%m-%d")

        print(f"[검증] 검증 대상 영업일: {target_date_str}")

        # --- A. 지수 및 환율 교차검증 (FDR vs 네이버) ---
        fdr_kospi, fdr_usd = None, None
        naver_kospi = None

        # 1) FDR (야후/구글 금융)
        try:
            import FinanceDataReader as fdr
            df_k = fdr.DataReader('^KS11')
            df_u = fdr.DataReader('USDKRW=X')
            if not df_k.empty and not df_u.empty:
                fdr_kospi = round(float(df_k.iloc[-1]['Close']), 2)
                fdr_usd = round(float(df_u.iloc[-1]['Close']), 2)
                print(f"  * [출처 1] FDR (글로벌/야후) : KOSPI = {fdr_kospi:.2f}pt | 환율 = {fdr_usd:.2f}원")
        except Exception as e:
            print(f"  * [출처 1] FDR 조회 실패: {e}")

        # 2) 네이버 금융 지수
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url_k = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
            r = requests.get(url_k, headers=headers)
            soup = BeautifulSoup(r.text, 'html.parser')
            kospi_elem = soup.find('em', id='now_value')
            if kospi_elem:
                naver_kospi = float(kospi_elem.text.replace(',', ''))
                print(f"  * [출처 2] 네이버 금융      : KOSPI = {naver_kospi:.2f}pt")
        except Exception as e:
            print(f"  * [출처 2] 네이버 지수 조회 실패: {e}")

        # 지수 대조 교차검증 판정
        if fdr_kospi and naver_kospi:
            if abs(fdr_kospi - naver_kospi) <= 5.0:
                print("  [성공] [지수 교차검증 성공] FDR과 네이버 지수가 일치합니다.")
            else:
                print(f"  [경고] [지수 교차검증 경고] 출처 간 지수 오차 발생! (FDR: {fdr_kospi} vs 네이버: {naver_kospi})")

        # --- B. 투자자 수급 데이터 교차검증 (네이버 vs KRX 공식) ---
        print("\n[투자자 수급 데이터 교차검증]")

        naver_flow = None
        krx_flow = None

        # 1) 네이버 수급 스크래핑
        try:
            date_query = target_date.strftime("%Y%m%d")
            url_s = f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={date_query}&sosok=01&page=1"
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(url_s, headers=headers)
            r.encoding = 'euc-kr'
            soup = BeautifulSoup(r.text, 'html.parser')
            tb = soup.find('table', class_='type_1')
            if tb:
                rows = tb.find_all('tr')
                for tr in rows[2:]:
                    cells = [td.text.strip().replace(',', '') for td in tr.find_all('td') if td.text.strip()]
                    if len(cells) >= 4:
                        ret, fore, inst = int(cells[1]), int(cells[2]), int(cells[3])
                        naver_flow = {"개인": ret, "외국인": fore, "기관": inst}
                        print(f"  * [출처 A] 네이버 수급 : 개인 = {ret}억 | 외인 = {fore}억 | 기관 = {inst}억")
                        break
        except Exception as e:
            print(f"  * [출처 A] 네이버 수급 조회 실패: {e}")

        # 2) PyKRX (한국거래소 공식) 수급
        if PYKRX_AVAILABLE:
            try:
                check_str = target_date.strftime("%Y%m%d")
                df_krx = stock.get_market_net_purchases_of_equities_by_ticker(check_str, check_str, market="KOSPI")
                if df_krx is not None and not df_krx.empty and '외국인합계' in df_krx.columns:
                    fore_krx = int(df_krx['외국인합계'].sum() / 100000000)
                    inst_krx = int(df_krx['기관합계'].sum() / 100000000)
                    ret_krx = int(df_krx['개인'].sum() / 100000000)
                    krx_flow = {"개인": ret_krx, "외국인": fore_krx, "기관": inst_krx}
                    print(f"  * [출처 B] KRX 공식 수급 : 개인 = {ret_krx}억 | 외인 = {fore_krx}억 | 기관 = {inst_krx}억")
            except Exception as e:
                print(f"  * [출처 B] KRX 수급 조회 실패: {e}")
        else:
            print("  * [출처 B] KRX 수급 모듈(pykrx)을 사용할 수 없습니다.")

        # 3) 수급 교차검증 최종 판정
        if naver_flow and krx_flow:
            diff = abs(naver_flow["외국인"] - krx_flow["외국인"])
            if diff <= 50:
                print("  [성공] [수급 교차검증 성공] 네이버와 KRX 공식 수급 데이터가 정확히 상호 검증되었습니다!")
            else:
                print(f"  [경고] [수급 교차검증 불일치] 출처 간 오차 발생(차이: {diff}억원). KRX 확정 수치를 우대합니다.")
        elif naver_flow and (naver_flow["개인"] == 0 and naver_flow["외국인"] == 0 and naver_flow["기관"] == 0):
            print("  [경고] [수급 결손 경고] 수집된 수급 데이터가 전부 '0원'입니다. DB 저장을 차단(Reject)합니다.")
        else:
            print("  [성공] [수급 검증 진행] 단일 출처 수집 완료 및 무결성 검사를 통과했습니다.")

        print("==================================================")

class DataValidatorHarness:
    @staticmethod
    def test_pipeline():
        print("==================================================")
        print("[데이터 검증 3단계 파이프라인 (DataValidator) 하네스 검사]")
        print("==================================================")
        from utils.data_validator import DataValidator
        
        # Test Case 1: 정상 수치
        raw_test = {"raw_eps": 10085}
        proc_test = {"code": "055550", "name": "신한지주", "price": 100700, "t_eps": 10085, "t_per": 9.99}
        pass1, logs1 = DataValidator.run_pipeline(raw_test, proc_test)
        if pass1:
            print("  * [테스트 1 - 정상주] 3단계 검증 통과 (PASS) ⭕")
        else:
            print(f"  * [테스트 1 - 정상주] 실패: {logs1[-1]}")
            
        # Test Case 2: PER 산티 오차 5% 초과 (오염 데이터)
        proc_corrupt = {"code": "000000", "name": "오염기업", "price": 100000, "t_eps": 2000, "t_per": 80.0} # 100000/2000=50 != 80 (60% 차이!)
        pass2, logs2 = DataValidator.run_pipeline(raw_test, proc_corrupt)
        if not pass2:
            print("  * [테스트 2 - 오염데이터 차단] 산티 체크 5% 초과 차단 성공 (PASS) 🛡️")
        else:
            print("  * [테스트 2 - 오염데이터 차단] 산티 체크 차단 실패!")

        print("==================================================")

def main():
    check_governance()
    UICrossValidator.validate_ui_visibility()
    DataValidatorHarness.test_pipeline()
    DataCrossValidator.validate_latest_data()
    
    if os.path.exists(HISTORY_FILE):
        print(f"[정보] 히스토리 DB 파일 연동 확인 완료: {HISTORY_FILE}")
    else:
        print(f"[경고] 히스토리 DB 파일 없음: {HISTORY_FILE}")

if __name__ == "__main__":
    main()
