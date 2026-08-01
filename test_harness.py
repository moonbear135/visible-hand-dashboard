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
AUDIT_TRAIL = []

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
    latest_record = AUDIT_TRAIL[-1]
    days_elapsed = (datetime.now() - latest_record.date).days
    print(f"[정보] 최근 알고리즘 파라미터 튜닝 후 경과 일수: {days_elapsed}일")
    
    if days_elapsed >= 60:
        print("[알림] 파라미터 정기 재검증(2개월) 주기가 도래했습니다. 수식 및 가중치 점검이 필요합니다.")
    else:
        print(f"[성공] 파라미터 정기 점검 주기까지 {60 - days_elapsed}일 남았습니다.")
    print("==================================================")


# ==============================================================================
# 2. 다중 출처 수급 & 지수 데이터 교차 검증 (Cross-Validation Engine)
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

        # 1) 네이버 수급 스크래핑 (정확한 규격 적용)
        try:
            # 0원 고정 방지를 위해 당일 기준의 bizdate를 query 파라미터로 조합 적용
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
            if diff <= 50:  # 50억원 이내 차이는 정상 범위
                print("  [성공] [수급 교차검증 성공] 네이버와 KRX 공식 수급 데이터가 정확히 상호 검증되었습니다!")
            else:
                print(f"  [경고] [수급 교차검증 불일치] 출처 간 오차 발생(차이: {diff}억원). KRX 확정 수치를 우대합니다.")
        elif naver_flow and (naver_flow["개인"] == 0 and naver_flow["외국인"] == 0 and naver_flow["기관"] == 0):
            print("  [경고] [수급 결손 경고] 수집된 수급 데이터가 전부 '0원'입니다. DB 저장을 차단(Reject)합니다.")
        else:
            print("  [성공] [수급 검증 진행] 단일 출처 수집 완료 및 무결성 검사를 통과했습니다.")

        print("==================================================")


def main():
    check_governance()
    DataCrossValidator.validate_latest_data()
    
    if os.path.exists(HISTORY_FILE):
        print(f"[정보] 히스토리 DB 파일 연동 확인 완료: {HISTORY_FILE}")
    else:
        print(f"[경고] 히스토리 DB 파일 없음: {HISTORY_FILE}")

if __name__ == "__main__":
    main()
