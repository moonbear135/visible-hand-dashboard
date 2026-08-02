# tests/test_quant.py
import sys
import io
from pathlib import Path

# Windows 터미널 한글/이모지 유니코드 출력 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.append(str(Path(__file__).parent.parent))

from utils.guardrail import apply_valuation_guardrail

def run_golden_tests():
    print("=" * 60)
    print("🧪 퀀트 연산 엔진 무결성 검증 (Golden Test Suite)")
    print("=" * 60)

    # -------------------------------------------------------------
    # CASE 1: 정상 저평가 우량주 (정상 연산 확인)
    # -------------------------------------------------------------
    case1_input = {
        'name': '정상 우량주 A',
        'price': 50000,
        'f_per': 10.0,
        'growth': 15.0,
        'sh_return': 5.0 # g_eff = 20.0
    }
    # 예상 PEGY = 10.0 / 20.0 = 0.50
    res1 = apply_valuation_guardrail(case1_input)
    assert res1['is_valid'] == True
    assert res1['g_eff'] == 20.0
    print(f"✅ CASE 1 [정상주] PASS -> g_eff: {res1['g_eff']}%, 상태: {res1.get('badge', '정상')}")

    # -------------------------------------------------------------
    # CASE 2: 역성장 기업 (g_eff <= 0 하드 컷오프 확인)
    # -------------------------------------------------------------
    case2_input = {
        'name': '역성장 기업 B',
        'price': 30000,
        'f_per': 12.0,
        'growth': -5.0,
        'sh_return': 2.0 # g_eff = -3.0
    }
    # 예상: 역성장 컷오프 경고 표시, f_pegy = 99.0 고평가 처리, 목표가 삭감
    res2 = apply_valuation_guardrail(case2_input)
    assert res2['is_valid'] == True
    assert res2['f_pegy'] == 99.0
    assert res2['f_target'] == 21000.0 # 현재가(30000) * 0.7 삭감
    print(f"✅ CASE 2 [역성장] PASS -> PEGY: {res2['f_pegy']}, 목표가: {res2['f_target']:,.0f}원, 뱃지: {res2['badge']}")

    # -------------------------------------------------------------
    # CASE 3: 파싱 오염 및 스케일 이상치 (Reject 확인)
    # -------------------------------------------------------------
    case3_input = {
        'name': '데이터 오염 C',
        'price': 0, # 주가 파싱 오류
        'f_per': -5.0,
        'growth': 10.0,
        'sh_return': 0.0
    }
    # 예상: 연산 거부 (is_valid = False)
    res3 = apply_valuation_guardrail(case3_input)
    assert res3['is_valid'] == False
    print(f"✅ CASE 3 [오염데이터 차단] PASS -> 거부사유: {res3['reject_reason']}")

    print("=" * 60)
    print("🎉 모든 수식 및 방공망 테스트 통과! 코드 수정이 안전합니다.")
    print("=" * 60)

if __name__ == "__main__":
    run_golden_tests()
