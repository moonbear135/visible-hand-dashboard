# tests/test_quant.py
"""
퀀트 연산 엔진 무결성 검증 (Golden Test Suite)

⚠️ 2026-08-05 데이터 무결성 감사 후 실제 코드 동작에 맞춰 전면 재작성했습니다.
   (이전 버전은 guardrail 이 만들지도 않는 g_eff / f_pegy / f_target 키를 단언해
    항상 KeyError 로 실패했고, "🎉 모든 테스트 통과" 문구는 도달 불가능했습니다.)

핵심 검증 목표
  1. 수집 실패(None)를 그럴듯한 숫자로 메우지 않는가
  2. 상위 검증 실패(is_valid=False)를 guardrail 이 True 로 되돌리지 않는가
  3. 스코어링이 '데이터 없음' 항목을 배점에서 제외하는가 (중립값 대입 금지)
"""
import sys
import io
from pathlib import Path

# Windows 터미널 한글/이모지 유니코드 출력 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.append(str(Path(__file__).parent.parent))

from utils.guardrail import apply_valuation_guardrail
from utils.scoring import calculate_quant_score
from utils.data_validator import DataValidator


def run_golden_tests():
    print("=" * 60)
    print("🧪 퀀트 연산 엔진 무결성 검증 (Golden Test Suite)")
    print("=" * 60)

    # -------------------------------------------------------------
    # CASE 1: 정상 종목 — guardrail 통과
    # -------------------------------------------------------------
    case1 = {
        'name': '정상 우량주 A', 'price': 50000, 'f_per': 10.0, 'f_eps': 5000,
        'growth': 15.0, 'sh_return': 5.0, 'g_eff': 20.0,
        'outstanding_shares': 50_000_000, 'dps': 2500, 'is_valid': True
    }
    res1 = apply_valuation_guardrail(case1)
    assert res1['is_valid'] is True, res1
    assert res1['is_unverified'] is False, res1
    print(f"✅ CASE 1 [정상주] PASS -> is_valid={res1['is_valid']}, is_unverified={res1['is_unverified']}")

    # -------------------------------------------------------------
    # CASE 2: 상위 3단계 검증 실패 → guardrail 이 절대 True 로 되돌리면 안 됨
    # -------------------------------------------------------------
    case2 = dict(case1, name='검증실패 B', is_valid=False, validation_error='2단계 산티 체크 실패')
    res2 = apply_valuation_guardrail(case2)
    assert res2['is_valid'] is False, "guardrail 이 상위 검증 실패를 덮어썼습니다!"
    assert res2['is_unverified'] is True, res2
    assert '검증' in res2.get('unverified_reason', ''), res2
    print(f"✅ CASE 2 [검증실패 승계] PASS -> 사유: {res2['unverified_reason']}")

    # -------------------------------------------------------------
    # CASE 3: 파싱 오염 / 필수값 결측 → 차단
    # -------------------------------------------------------------
    case3 = {'name': '데이터 오염 C', 'price': 0, 'f_per': -5.0, 'growth': 10.0, 'f_eps': None, 'g_eff': 10.0}
    res3 = apply_valuation_guardrail(case3)
    assert res3['is_valid'] is False, res3
    assert res3.get('reject_reason'), res3
    print(f"✅ CASE 3 [오염데이터 차단] PASS -> 거부사유: {res3['reject_reason']}")

    # -------------------------------------------------------------
    # CASE 4: 상장주식수 파싱 오류(범위 검증) → 차단
    # -------------------------------------------------------------
    case4 = dict(case1, name='주식수 오염 D', outstanding_shares=46)
    res4 = apply_valuation_guardrail(case4)
    assert res4['is_valid'] is False, res4
    assert '상장주식수' in res4['reject_reason'], res4
    print(f"✅ CASE 4 [상장주식수 sanity check] PASS -> 거부사유: {res4['reject_reason']}")

    # -------------------------------------------------------------
    # CASE 5: 스코어링 — 수집하지 못한 항목은 배점에서 제외 (중립값 대입 금지)
    # -------------------------------------------------------------
    s5 = calculate_quant_score(
        f_pegy=0.5, f_roe=None, roic=None, sh_return=2.0, t_roe=12.0,
        vol="🟢 정상 (1.2%)", f_per=9.0, price=50000, f_target=70000, growth=18.0
    )
    assert s5['score_max'] == 70, s5           # 100 - (ROE 15점 + ROIC 15점)
    assert len(s5['excluded_items']) == 2, s5
    print(f"✅ CASE 5 [배점 제외] PASS -> {s5['quant_score']}점 / {s5['score_max']}점, 제외: {s5['excluded_items']}")

    # -------------------------------------------------------------
    # CASE 6: 변동성 데이터가 없으면 감점(1점)도 가점(5점)도 하지 않음
    # -------------------------------------------------------------
    s6 = calculate_quant_score(
        f_pegy=0.5, f_roe=14.0, roic=11.0, sh_return=2.0, t_roe=12.0,
        vol="❔ 변동성 데이터 없음", f_per=9.0, price=50000, f_target=70000, growth=18.0
    )
    assert s6['score_max'] == 95, s6
    assert any('변동성' in x for x in s6['excluded_items']), s6
    print(f"✅ CASE 6 [변동성 미수집] PASS -> {s6['quant_score']}점 / {s6['score_max']}점")

    # -------------------------------------------------------------
    # CASE 7: 필수 지표가 없으면 점수를 만들지 않고 None 반환
    # -------------------------------------------------------------
    s7 = calculate_quant_score(
        f_pegy=None, f_roe=None, roic=None, sh_return=0, t_roe=None,
        vol="❔ 변동성 데이터 없음", f_per=None, price=0, f_target=None, growth=None
    )
    assert s7['quant_score'] is None, s7
    print(f"✅ CASE 7 [측정 불가] PASS -> 배지: {s7['badge']}")

    # -------------------------------------------------------------
    # CASE 8: DataValidator 1단계 — raw_period 가 없으면 통과시키면 안 됨
    # -------------------------------------------------------------
    ok, logs = DataValidator.run_pipeline(
        {"raw_eps": 5000, "raw_period": None},
        {"code": "005930", "name": "테스트", "price": 50000, "t_per": 10.0, "t_eps": 5000, "indicator_type": "PER"}
    )
    assert ok is False, logs
    print("✅ CASE 8 [raw_period 미확인 차단] PASS -> 자기 자신과 비교하던 껍데기 검증 제거 확인")

    print("=" * 60)
    print("🎉 모든 수식 및 방공망 테스트 통과!")
    print("=" * 60)


if __name__ == "__main__":
    run_golden_tests()
