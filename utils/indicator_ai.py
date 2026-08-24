"""
utils/indicator_ai.py

🙏 "여기서부터는 신앙입니다"(7번째 모듈) — 종목별 온디맨드 AI 해설 + 서버 캐싱.

작업 지시서: TECHNICAL_INDICATOR_WORK_ORDER.md
  §4-1  판정(verdict)은 100% 파이썬 결정론(utils/indicators.py::combine_verdict) — 이
        파일은 그 값을 "설명"만 하고, 절대 다시 계산하거나 바꾸지 않습니다.
  §4-2  캐시는 브라우저/사용자 단위가 아니라 "종목코드+날짜" 단위로 서버(DB)에 저장합니다.
        오늘 어떤 종목 카드를 A가 처음 열면 그때 1회만 Gemini를 부르고, 같은 날 B·C가
        같은 종목을 열어도 캐시를 그대로 보여줍니다(재호출 안 함). 최악의 경우(그날
        500종목이 전부 한 번씩 열림)에도 하루 상한은 500회.
  §5-1  §0-1 확장 — AI 해설 프롬프트에 "매수·매도·보유 권유 금지, 목표가 언급 금지"를
        명시하고, 응답을 받은 뒤 파이썬으로 금지어를 한 번 더 걸러 걸리면 그 해설을
        버립니다(지어낸 조언을 그대로 통과시키지 않음).

이 파일은 `utils/macro_ai.py`(기존 매크로 AI 코멘트)와 같은 정신(Gemini 직접 호출,
실패해도 나머지 기능은 막지 않음)이지만 두 가지가 다릅니다:
  - macro_ai 는 GitHub Actions 배치에서 전체를 매일 한 번에 돌리고 결과를 JSON 파일에
    씁니다. 이 파일은 **웹 요청(사용자가 카드를 열 때)에서 온디맨드로** 호출되고,
    결과는 파일이 아니라 Supabase 테이블(`indicator_ai_commentary`)에 씁니다 — 파일은
    Render 웹 프로세스 하나의 로컬 디스크에만 남아 재배포마다 사라지고 여러 사용자가
    공유할 수 없기 때문입니다(§4-2 "서버 DB" 요구사항).
  - 인증(로그인)이 필요 없는 데이터입니다 — `utils/scorecard_db.create_supabase_client()`
    를 그대로 재사용하되(§0-3-10, 새 접속 로직을 만들지 않음), 이 테이블은 특정
    사용자 소유가 아니라 "그 날짜의 그 종목에 대한 계산된 설명" 하나뿐입니다.

⚠️ Supabase 쪽 준비물(오너가 대시보드에서 1회 실행) — 이 파일만 배포해서는 동작하지
   않습니다. 테이블 생성 SQL은 이 기능을 전달하는 메시지에 별도로 첨부합니다.
"""

import os
from datetime import datetime, timezone

from google import genai

from utils.scorecard_db import ScorecardError, create_supabase_client

# 단일 출처(§0-3-10) — 테이블 이름이 여기와 SQL 두 곳에서 어긋나면 조용히 실패하므로,
# SQL 쪽 주석에도 이 이름을 그대로 적어 짝을 맞춰 둡니다.
TABLE = 'indicator_ai_commentary'
MODEL_NAME = 'gemini-2.5-flash'  # macro_ai.py 와 같은 저비용 고효율 모델(§0-3-10 관례 재사용)

# §5-1 — AI 응답에 이 표현이 하나라도 섞여 있으면 해설을 버립니다(지어낸 투자 조언 방지).
# 프롬프트에도 같은 금지 목록의 취지를 명시하지만, "프롬프트로 지시했으니 안전하다"고
# 믿지 않고 출력을 다시 검사합니다(§0-1 — 지어내지 않기의 AI 버전).
_FORBIDDEN_PHRASES = [
    '매수하세요', '매도하세요', '사세요', '파세요', '매수 추천', '매도 추천',
    '매수하는 것이 좋', '매도하는 것이 좋', '지금 사', '지금 팔',
    '목표가', '목표주가', '목표 주가',
    '수익 보장', '손실 없이', '무조건 오', '무조건 내',
]


class IndicatorAIError(RuntimeError):
    """AI 해설 생성/조회 실패 — 메시지는 그대로 사용자 화면에 보여줘도 되는 한국어 한 문장입니다."""


def _build_prompt(stock: dict) -> str:
    """지표 원값만 담습니다 — 종목 실시간 시세·미래 예측 자료는 아예 넘기지 않습니다."""
    name = stock.get('name') or stock.get('code') or '이 종목'
    verdict = stock.get('verdict_label') or '산출 불가'
    rsi = stock.get('rsi')
    rsi_signal = stock.get('rsi_signal') or '—'
    macd_cross = stock.get('macd_cross') or '없음'
    bb_position = stock.get('bb_position') or '—'

    return f"""
당신은 초보 주식 투자자에게 보조지표를 아주 친절하고 알기 쉽게 설명해주는 친한 주식 선배입니다.
어려운 금융 용어를 쓰지 말고, 필요하면 비유를 들어서라도 쉽게 풀어서 설명하세요.

[오늘 {name}의 보조지표 값 — 전부 과거 종가로 계산한 결과입니다]
- RSI(14): {rsi if rsi is not None else '산출 불가'} (판독: {rsi_signal})
- MACD 크로스: {macd_cross}
- 볼린저밴드 위치: {bb_position}
- 종합판정(3개 지표를 정해진 규칙으로 합산한 결과, AI가 만든 값이 아님): {verdict}

위 수치가 지금 어떤 상태를 뜻하는지 2~3문장으로 짧게 설명해 주세요.

⚠️ 반드시 지킬 것:
- "사세요/파세요/매수하세요/매도하세요" 같은 직접적인 매매 권유를 절대 하지 마세요.
- 목표주가나 앞으로의 가격을 예측하는 말을 하지 마세요.
- 이 지표들이 과거 종가만으로 계산된 것이고 미래를 맞히는 도구가 아니라는 점과
  어긋나게 단정적으로 말하지 마세요.
- 말투는 부드러운 평어체(~해요, ~입니다)를 쓰세요.
""".strip()


def _violates_policy(text: str) -> bool:
    return any(phrase in text for phrase in _FORBIDDEN_PHRASES)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_via_gemini(stock: dict) -> str:
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise IndicatorAIError('AI 해설 기능이 아직 설정되지 않았습니다 (GEMINI_API_KEY 미등록).')

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(stock)
    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    except Exception as exc:  # noqa: BLE001
        print(f'⚠️ [indicator_ai] Gemini 호출 실패: {type(exc).__name__}: {exc}')
        raise IndicatorAIError('AI 해설을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.') from exc

    text = (response.text or '').strip() if response else ''
    if not text:
        raise IndicatorAIError('AI가 빈 응답을 돌려줬습니다. 잠시 후 다시 시도해 주세요.')
    if _violates_policy(text):
        print(f'⚠️ [indicator_ai] 금지어 필터에 걸려 해설을 버렸습니다 — 종목 {stock.get("code")}')
        raise IndicatorAIError('생성된 해설이 이 화면의 정책(매매 권유·목표가 금지)에 어긋나 표시하지 않습니다.')
    return text


def _fetch_cached(client, code: str, date_str: str):
    """캐시 조회 실패(네트워크 등)는 "캐시 없음"과 똑같이 처리 — 새로 생성을 시도합니다.

    다만 이 경우 실제로는 이미 있는 캐시를 다시 만드는 낭비가 생길 수 있는데, §4-2가
    이미 인정한 한계(동시 캐시미스 시 중복 호출 가능)와 같은 성격이라 별도 처리를
    더하지 않습니다 — DB 쓰기는 upsert라 중복돼도 행이 깨지지 않습니다.
    """
    try:
        result = (
            client.table(TABLE)
            .select('commentary, generated_at, model')
            .eq('stock_code', code)
            .eq('commentary_date', date_str)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        print(f'⚠️ [indicator_ai] 캐시 조회 실패(신규 생성으로 진행): {type(exc).__name__}: {exc}')
        return None
    rows = result.data or []
    return rows[0] if rows else None


def _save_cache(client, code: str, date_str: str, text: str) -> None:
    """저장 실패해도 방금 만든 해설 자체는 이미 돌려줄 수 있으므로 화면을 막지 않습니다.

    (다음에 같은 종목을 다시 열면 캐시가 없으니 또 생성됩니다 — 비용은 늘지만 §0-1
    "실패를 조용히 감추지 않는다"의 반대 극단인 "캐시 실패로 기능 자체가 죽는 것"보다
    낫다는 판단, TABLE 자체가 없거나 RLS 미설정이면 이 상태가 계속될 수 있어 로그로
    원인을 남깁니다.)
    """
    try:
        client.table(TABLE).upsert(
            {
                'stock_code': code,
                'commentary_date': date_str,
                'commentary': text,
                'model': MODEL_NAME,
                'generated_at': _now_iso(),
            },
            on_conflict='stock_code,commentary_date',
        ).execute()
    except Exception as exc:  # noqa: BLE001
        print(f'⚠️ [indicator_ai] 캐시 저장 실패(해설은 그대로 반환): {type(exc).__name__}: {exc}')


def get_or_create_commentary(stock: dict, date_str: str) -> dict:
    """캐시에 있으면 그대로 돌려주고, 없으면 Gemini로 생성한 뒤 저장합니다.

    :param stock: latest.json 의 종목 dict 하나(code/name/rsi/... 를 담고 있음).
    :param date_str: 이 지표가 계산된 기준일(YYYY-MM-DD). **`datetime.now()`로 오늘
        날짜를 다시 구하지 않습니다** — 호출부가 화면에 실제로 표시 중인 데이터의
        기준일(`payload['date']`, 수집기가 남긴 값)을 그대로 넘겨야 합니다. 그래야
        캐시 키가 "화면에 보이는 그 지표 값"과 항상 일치합니다(§0-1).
    :returns: {'text': str, 'generated_at': str, 'from_cache': bool}
    :raises IndicatorAIError: 사용자 화면에 그대로 보여줘도 되는 실패 사유.
    """
    code = stock.get('code')
    if not code:
        raise IndicatorAIError('종목코드가 없어 AI 해설을 만들 수 없습니다.')
    if not date_str:
        raise IndicatorAIError('데이터 기준일을 알 수 없어 AI 해설을 요청할 수 없습니다.')

    try:
        client = create_supabase_client()
    except ScorecardError as exc:
        raise IndicatorAIError(str(exc)) from exc
    if client is None:
        raise IndicatorAIError('AI 해설 저장소(Supabase)가 아직 준비되지 않았습니다.')

    cached = _fetch_cached(client, code, date_str)
    if cached:
        return {
            'text': cached['commentary'],
            'generated_at': cached.get('generated_at'),
            'from_cache': True,
        }

    text = _generate_via_gemini(stock)
    _save_cache(client, code, date_str, text)
    return {
        'text': text,
        'generated_at': _now_iso(),
        'from_cache': False,
    }
