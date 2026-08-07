"""
utils/company_names_kr.py
🇺🇸 미국 상장사 영문 사명 → 한글 표기 (오너 확정 "하이브리드 방식", PROJECT_STATUS §8-7-4)

오너 확정 규칙 (2026-08-07)
  1) 한국에서 이미 널리 쓰이는 **정식 한글명**이 있으면 그대로 씁니다(애플·엔비디아·마이크로소프트 …).
     → 아래 `KR_NAME_OVERRIDES` 사전(티커 기준)에 등록. **이 사전이 항상 최우선입니다.**
  2) 사전에 없는 종목(한국에 잘 안 알려진 중소형주 등)은 회사명을 **발음대로 한글 음역**합니다.
     → `transliterate_to_hangul()`. 번역이 아니라 기계적 음역이므로 ENGINEERING_SPEC §0-1
       ("지어내지 않기") 위반이 아닙니다. 없는 사실을 만들어내는 게 아니라 표기 체계를 바꾸는 것뿐입니다.

⚠️⚠️ 음역기의 한계 (반드시 읽을 것)
  영어 철자는 발음과 1:1로 대응하지 않기 때문에(예: "Colgate"→콜게이트 vs 규칙출력 "콜게이트",
  "Cboe"→씨보 vs 규칙출력 "크보에") **규칙 기반 음역은 절대 완벽할 수 없습니다.**
  이 모듈은 "그럴듯한 근사치"를 만들 뿐이며, 틀린 표기가 나오는 것은 버그가 아니라 설계상의 한계입니다.
  그래서:
    - 화면에는 음역 결과에 **"음역"(자동 표기) 배지**를 붙여, 정식 한글명과 구분되게 합니다
      (`resolve_korean_name()` 이 `source` 를 함께 반환하므로 UI가 이를 그대로 표시합니다).
    - 오너가 개별 종목 이름을 고치고 싶으면 **`KR_NAME_OVERRIDES` 에 티커 한 줄만 추가**하면 됩니다.
      코드 로직은 건드릴 필요가 없습니다.

사용 예
    from utils.company_names_kr import resolve_korean_name
    resolve_korean_name("NVDA", "NVIDIA Corporation Common Stock")
    # -> {"korean_name": "엔비디아", "source": "official_dict", "is_transliterated": False}
"""

import re

# =============================================================================
# 1. 정식 한글명 사전 (오너가 직접 수정하는 곳)
#
#   ⚠️ 여기 있는 값이 무조건 최우선입니다. 음역 결과가 마음에 들지 않으면
#      "티커": "원하는 한글명" 한 줄만 추가하면 즉시 반영됩니다.
#   ⚠️ 한국 언론/증권사에서 실제로 통용되는 표기만 넣습니다. 확실하지 않으면
#      넣지 말고 음역에 맡기세요(§0-1 — 모르는 걸 아는 척하지 않기).
#   시가총액 상위권 + 국내 투자자에게 익숙한 종목 위주로 채워둔 초기 목록입니다.
#   (550종목 전체를 채울 필요는 없습니다 — 나머지는 자동 음역됩니다.)
# =============================================================================
KR_NAME_OVERRIDES = {
    # --- 빅테크 / 반도체 ---
    "NVDA": "엔비디아",
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
    "GOOGL": "알파벳(구글) A",
    "GOOG": "알파벳(구글) C",
    "AMZN": "아마존",
    "META": "메타(페이스북)",
    "AVGO": "브로드컴",
    "TSLA": "테슬라",
    "TSM": "TSMC(대만반도체)",
    "AMD": "AMD",
    "INTC": "인텔",
    "QCOM": "퀄컴",
    "TXN": "텍사스인스트루먼트",
    "MU": "마이크론",
    "AMAT": "어플라이드머티어리얼즈",
    "LRCX": "램리서치",
    "KLAC": "KLA",
    "ADI": "아나로그디바이스",
    "NXPI": "NXP반도체",
    "MRVL": "마벨테크놀로지",
    "ARM": "ARM홀딩스",
    "ASML": "ASML",
    "SNPS": "시놉시스",
    "CDNS": "케이던스",
    "MCHP": "마이크로칩테크놀로지",
    "ON": "온세미컨덕터",
    "SMCI": "슈퍼마이크로컴퓨터",
    "DELL": "델테크놀로지스",
    "HPQ": "HP",
    "HPE": "휴렛팩커드엔터프라이즈",
    "IBM": "IBM",
    "ORCL": "오라클",
    "CRM": "세일즈포스",
    "ADBE": "어도비",
    "NOW": "서비스나우",
    "INTU": "인튜이트",
    "PANW": "팔로알토네트웍스",
    "CRWD": "크라우드스트라이크",
    "SNOW": "스노우플레이크",
    "PLTR": "팔란티어",
    "UBER": "우버",
    "ABNB": "에어비앤비",
    "NFLX": "넷플릭스",
    "DIS": "월트디즈니",
    "CMCSA": "컴캐스트",
    "T": "AT&T",
    "VZ": "버라이즌",
    "TMUS": "T모바일",
    "CSCO": "시스코",
    "ANET": "아리스타네트웍스",
    "MSI": "모토로라솔루션즈",
    "APP": "앱러빈",
    "SPOT": "스포티파이",
    "SHOP": "쇼피파이",
    "SE": "씨(Sea)",
    "COIN": "코인베이스",
    "MSTR": "스트래티지(마이크로스트래티지)",
    "SQ": "블록(스퀘어)",
    "PYPL": "페이팔",

    # --- 금융 ---
    "BRK.A": "버크셔해서웨이 A",
    "BRK.B": "버크셔해서웨이 B",
    "JPM": "JP모건체이스",
    "BAC": "뱅크오브아메리카",
    "WFC": "웰스파고",
    "GS": "골드만삭스",
    "MS": "모건스탠리",
    "C": "씨티그룹",
    "SCHW": "찰스슈왑",
    "BLK": "블랙록",
    "BX": "블랙스톤",
    "KKR": "KKR",
    "APO": "아폴로글로벌",
    "AXP": "아메리칸익스프레스",
    "V": "비자",
    "MA": "마스터카드",
    "COF": "캐피탈원",
    "USB": "US뱅코프",
    "PNC": "PNC파이낸셜",
    "TFC": "트루이스트파이낸셜",
    "SPGI": "S&P글로벌",
    "MCO": "무디스",
    "CME": "CME그룹",
    "ICE": "인터콘티넨탈익스체인지",
    "PGR": "프로그레시브",
    "CB": "처브",
    "AIG": "AIG",
    "MET": "메트라이프",
    "PRU": "푸르덴셜파이낸셜",
    "ALL": "올스테이트",
    "TRV": "트래블러스",

    # --- 헬스케어 / 제약 ---
    "LLY": "일라이릴리",
    "JNJ": "존슨앤드존슨",
    "UNH": "유나이티드헬스",
    "ABBV": "애브비",
    "MRK": "머크",
    "PFE": "화이자",
    "TMO": "써모피셔사이언티픽",
    "ABT": "애보트",
    "DHR": "다나허",
    "AMGN": "암젠",
    "BMY": "브리스톨마이어스스퀴브",
    "GILD": "길리어드사이언스",
    "VRTX": "버텍스파마슈티컬스",
    "REGN": "리제네론",
    "ISRG": "인튜이티브서지컬",
    "SYK": "스트라이커",
    "BSX": "보스턴사이언티픽",
    "MDT": "메드트로닉",
    "CI": "시그나",
    "ELV": "엘리번스헬스",
    "CVS": "CVS헬스",
    "HCA": "HCA헬스케어",
    "MCK": "맥케슨",
    "ZTS": "조에티스",
    "MRNA": "모더나",
    "BIIB": "바이오젠",

    # --- 소비재 / 유통 ---
    "WMT": "월마트",
    "COST": "코스트코",
    "HD": "홈디포",
    "LOW": "로우스",
    "TGT": "타깃",
    "PG": "프록터앤드갬블",
    "KO": "코카콜라",
    "PEP": "펩시코",
    "PM": "필립모리스",
    "MO": "알트리아",
    "MDLZ": "몬델리즈",
    "MCD": "맥도날드",
    "SBUX": "스타벅스",
    "NKE": "나이키",
    "LULU": "룰루레몬",
    "TJX": "TJX",
    "CMG": "치폴레",
    "YUM": "얌브랜즈",
    "KHC": "크래프트하인즈",
    "GIS": "제너럴밀스",
    "CL": "콜게이트파몰리브",
    "KMB": "킴벌리클라크",
    "EL": "에스티로더",
    "F": "포드",
    "GM": "제너럴모터스",
    "RIVN": "리비안",
    "LCID": "루시드",

    # --- 산업재 / 에너지 / 소재 ---
    "GE": "GE에어로스페이스",
    "GEV": "GE버노바",
    "CAT": "캐터필러",
    "DE": "디어",
    "BA": "보잉",
    "HON": "하니웰",
    "RTX": "RTX(레이시온)",
    "LMT": "록히드마틴",
    "NOC": "노스럽그러먼",
    "GD": "제너럴다이내믹스",
    "UNP": "유니온퍼시픽",
    "UPS": "UPS",
    "FDX": "페덱스",
    "MMM": "3M",
    "EMR": "에머슨일렉트릭",
    "ETN": "이튼",
    "ITW": "일리노이툴웍스",
    "PH": "파커해니핀",
    "CARR": "캐리어글로벌",
    "JCI": "존슨컨트롤스",
    "XOM": "엑슨모빌",
    "CVX": "셰브론",
    "COP": "코노코필립스",
    "SLB": "슐럼버거",
    "EOG": "EOG리소시스",
    "PSX": "필립스66",
    "MPC": "마라톤페트롤리엄",
    "VLO": "발레로에너지",
    "OXY": "옥시덴탈페트롤리엄",
    "KMI": "킨더모건",
    "WMB": "윌리엄스",
    "ET": "에너지트랜스퍼",
    "LIN": "린데",
    "APD": "에어프로덕츠",
    "SHW": "셔윈윌리엄스",
    "FCX": "프리포트맥모란",
    "NEM": "뉴몬트",
    "NUE": "뉴코",
    "DOW": "다우",
    "GLW": "코닝",

    # --- 유틸리티 / 리츠 / 기타 ---
    "NEE": "넥스트에라에너지",
    "DUK": "듀크에너지",
    "SO": "서던컴퍼니",
    "D": "도미니언에너지",
    "AEP": "아메리칸일렉트릭파워",
    "EXC": "엑셀론",
    "FE": "퍼스트에너지",
    "PLD": "프로로지스",
    "AMT": "아메리칸타워",
    "EQIX": "에퀴닉스",
    "SPG": "사이먼프로퍼티그룹",
    "O": "리얼티인컴",
    "PSA": "퍼블릭스토리지",
    "WELL": "웰타워",
    "MAR": "메리어트",
    "HLT": "힐튼",
    "BKNG": "부킹홀딩스",
    "LIN.": "린데",

    # --- 2026-08-07 실측 550종목 음역 검토에서 추가(널리 알려진 브랜드인데 음역이 부정확했던 것) ---
    "SPCX": "스페이스X",
    "NET": "클라우드플레어",
    "HOOD": "로빈후드",
    "WBD": "워너브라더스디스커버리",
    "NDAQ": "나스닥",
    "EBAY": "이베이",
    "MDB": "몽고디비",
    "ROKU": "로쿠",
    "LOGI": "로지텍",
    "HAL": "할리버튼",
    "TRI": "톰슨로이터스",
    "KDP": "큐리그닥터페퍼",
    "IQV": "아이큐비아",
    "VRSN": "베리사인",
    "GWW": "그레인저",
    "ORLY": "오라일리오토모티브",
    "RJF": "레이먼드제임스",
    "TROW": "티로우프라이스",
    "LUV": "사우스웨스트항공",
    "AVB": "아발론베이",
    "IR": "잉거솔랜드",
    "CCI": "크라운캐슬",
    "ADM": "아처대니얼스미들랜드",
    "EFX": "에퀴팩스",
    "ZBH": "짐머바이오멧",
    "DD": "듀폰",
    "WSM": "윌리엄스소노마",
    "AJG": "아서제이갤러거",
    "GH": "가던트헬스",
    "SNA": "스냅온",
    "CW": "커티스라이트",
    "TRU": "트랜스유니온",
    "IDXX": "아이덱스랩스",
    "ZS": "지스케일러",
    "TWLO": "트윌리오",
    "CHD": "처치앤드와이트",
    "DRI": "다든레스토랑",
    "BRO": "브라운앤드브라운",
    "WY": "와이어하우저",
    "NSC": "노퍽서던",
    "SCCO": "서던코퍼",
    "GPC": "지뉴인파츠",
    "USFD": "US푸드",
    "FOX": "폭스",
    "FOXA": "폭스",
    "KEY": "키코프",
    "LNT": "얼라이언트에너지",
    "MSCI": "MSCI",
}

# =============================================================================
# 2. 종목명 정리 — 법인격/주식종류 꼬리표 제거
#    유니버스 CSV 종목명에는 "Common Stock", "Class A Common Stock",
#    "American Depositary Shares each representing …", "Common Units representing
#    limited partner interests" 같은 **회사 이름이 아닌 상품 설명**이 붙어 있습니다.
#    한글 표기에는 회사 이름만 남깁니다(상품 종류는 티커·영문명에서 확인 가능).
# =============================================================================
_TRAILING_NOISE_PATTERNS = (
    r"\bamerican\s+depositary\s+(shares?|receipts?).*$",
    r"\bdepositary\s+shares?.*$",
    r"\bcommon\s+units?\s+representing.*$",
    r"\bunits?\s+representing.*$",
    r"\brepresenting.*$",
    r"\bordinary\s+shares?.*$",
    r"\bcommon\s+shares?\b.*$",
    r"\bcommon\s+stock\b.*$",
    r"\bcapital\s+stock\b.*$",
    r"\bcommon\s+units?\b.*$",
    r"\bclass\s+[a-z]\b.*$",
    r"\bseries\s+[a-z]\b.*$",
    r"\bsubordinate\s+voting.*$",
    r"\bnew\b\s*$",
)
_LEGAL_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "limited", "ltd", "plc", "llc", "lp", "l.p", "n.v", "nv", "s.a", "sa",
    "ag", "se", "holdings", "holding",
)


def clean_company_name(name):
    """영문 종목명에서 상품 설명·법인격 꼬리표를 떼고 '회사 이름'만 남깁니다."""
    if not name:
        return ""
    s = " ".join(str(name).split())
    low = s.lower()
    for pat in _TRAILING_NOISE_PATTERNS:
        m = re.search(pat, low)
        if m:
            s = s[: m.start()]
            low = s.lower()
    s = s.strip().strip(",").strip()

    # 마지막 토큰이 법인격이면 제거 (Holdings 는 회사명의 일부로 읽히는 경우가 많아
    # 한 번만 제거하고, 두 개 이상 연달아 붙어 있으면 순차적으로 제거)
    tokens = s.split()
    while tokens:
        tail = tokens[-1].lower().strip(".,")
        if tail in _LEGAL_SUFFIXES:
            tokens.pop()
            continue
        break
    s = " ".join(tokens).strip().strip(",").strip()
    # "Southern Company (The)" 같은 괄호 표기 정리 → 괄호 안 내용을 통째로 제거한 뒤 다시 꼬리표 제거
    s = re.sub(r"\([^)]*\)", " ", s)
    s = " ".join(s.split()).strip().strip(",").strip()
    tokens = s.split()
    while tokens:
        tail = tokens[-1].lower().strip(".,")
        if tail in _LEGAL_SUFFIXES:
            tokens.pop()
            continue
        break
    return " ".join(tokens).strip().strip(",").strip()


# =============================================================================
# 3. 규칙 기반 음역기
#    ⚠️ 근사치입니다. 완벽하지 않습니다(모듈 상단 경고 참고).
# =============================================================================
_CHO = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ',
        'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
_JUNG = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ',
         'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
_JONG = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ',
         'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ',
         'ㅌ', 'ㅍ', 'ㅎ']


def _compose(cho, jung, jong=""):
    """자모 → 한글 음절 1자."""
    try:
        ci, ji, ki = _CHO.index(cho), _JUNG.index(jung), _JONG.index(jong)
    except ValueError:
        return ""
    return chr(0xAC00 + (ci * 21 + ji) * 28 + ki)


# 알파벳 낱자 읽기 (약어용). "IBM" → 아이비엠, "AT&T" → 에이티앤티
_LETTER_NAMES = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프",
    "g": "지", "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘",
    "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
    "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스",
    "y": "와이", "z": "지",
}

# 자음 → (초성 자모, 받침으로 쓸 때 자모 or None, 단독 음절일 때 붙일 모음)
#   ⚠️ 국립국어원 외래어 표기법을 그대로 구현한 게 아니라 실무 관행에 가까운 근사치입니다.
_CONSONANTS = {
    "b": ("ㅂ", None, "ㅡ"),
    "c": ("ㅋ", None, "ㅡ"),
    "d": ("ㄷ", None, "ㅡ"),
    "f": ("ㅍ", None, "ㅡ"),
    "g": ("ㄱ", None, "ㅡ"),
    "h": ("ㅎ", None, "ㅡ"),
    "j": ("ㅈ", None, "ㅣ"),
    "k": ("ㅋ", None, "ㅡ"),
    "l": ("ㄹ", "ㄹ", "ㅡ"),
    "m": ("ㅁ", "ㅁ", "ㅡ"),
    "n": ("ㄴ", "ㄴ", "ㅡ"),
    "p": ("ㅍ", None, "ㅡ"),
    "r": ("ㄹ", None, "ㅡ"),
    "s": ("ㅅ", None, "ㅡ"),
    "t": ("ㅌ", None, "ㅡ"),
    "v": ("ㅂ", None, "ㅡ"),
    "w": ("ㅇ", None, "ㅜ"),
    "y": ("ㅇ", None, "ㅣ"),
    "z": ("ㅈ", None, "ㅡ"),
    "ng": ("ㅇ", "ㅇ", "ㅡ"),
    "sh": ("ㅅ", None, "ㅣ"),
    "ch": ("ㅊ", None, "ㅣ"),
    "th": ("ㅅ", None, "ㅡ"),
    "zh": ("ㅈ", None, "ㅣ"),
}

# 모음(철자 덩어리) → 중성 자모. 긴 것부터 매칭합니다.
#
# 2026-08-07 추가: r-계열 모음(er/ir) — 영어의 "er"/"ir"는 실제로는 슈와(어) 발음인데,
# 이 항목이 없으면 'e'/'i' 단독 규칙(ㅔ/ㅣ)이 먼저 걸려버립니다. 그러면 뒤따르는 자음(주로 n)이
# 받침으로 못 붙고 혼자 음절을 이뤄("Western"→ "웨스테느") 원래 있어야 할 "웨스턴"과
# 전혀 다른 결과가 나옵니다(실측 550종목 음역 검토에서 발견 — TASK_HISTORY 참고).
# "ar"/"or"/"ur"는 이미 단모음 a/o/u 기본값 + 뒤따르는 'r' 생략 규칙(아래 538행 부근)만으로도
# 근사치가 충분히 맞아떨어져(car→카, Burlington→버링톤 처럼 이미 정상 동작 확인) 손대지 않습니다.
_VOWELS = [
    ("eau", "ㅗ"), ("iou", "ㅣ"), ("yeo", "ㅕ"),
    ("er", "ㅓ"), ("ir", "ㅓ"),
    ("ee", "ㅣ"), ("ea", "ㅣ"), ("ie", "ㅣ"), ("ei", "ㅔ"), ("ey", "ㅔ"),
    ("ai", "ㅐ"), ("ay", "ㅔ"), ("au", "ㅗ"), ("aw", "ㅗ"),
    ("oo", "ㅜ"), ("ou", "ㅏ"), ("ow", "ㅗ"), ("oa", "ㅗ"), ("oi", "ㅚ"), ("oy", "ㅚ"),
    ("ue", "ㅜ"), ("ui", "ㅜ"), ("eu", "ㅠ"), ("eo", "ㅓ"),
    ("ia", "ㅣ"), ("io", "ㅣ"), ("ya", "ㅑ"), ("yo", "ㅛ"), ("yu", "ㅠ"),
    ("a", "ㅏ"), ("e", "ㅔ"), ("i", "ㅣ"), ("o", "ㅗ"), ("u", "ㅓ"),
]
_VOWEL_LETTERS = set("aeiou")

# 철자 전처리(발음에 가깝게). 순서 중요.
_PRE_RULES = [
    # -tion / -sion → "션" 이 되도록 ㅕ(yeo) 모음으로 유도
    (r"tion\b", "shyeon"), (r"sion\b", "shyeon"),
    (r"cious\b", "shus"), (r"tious\b", "shus"),
    (r"ph", "f"), (r"ck", "k"), (r"qu", "kw"), (r"que\b", "k"), (r"gue\b", "g"),
    (r"^kn", "n"), (r"^wr", "r"), (r"^ps", "s"), (r"^gn", "n"),
    (r"x", "ks"), (r"ough", "o"), (r"augh", "af"), (r"igh", "ai"),
    (r"wh", "w"),
    # ⚠️ c → s/k 변환은 ch(치읓 소리)를 절대 건드리면 안 됩니다(Macerich → 마세리치).
    (r"c(?=[eiy])(?!h)", "s"), (r"c(?!h)", "k"),
    (r"dge", "j"), (r"ge\b", "j"),
    (r"([^aeiou])y\b", r"\1i"),          # 어미 -y → 이 (Company → 컴퍼니)
    (r"\bre(?=[bcdfghjklmnpqrstvwz])", "ri"),
    (r"([bcdfgklmnprstvz])\1", r"\1"),   # 겹자음 축약 (ImmunityBio → 이무니티…)
]

# 'w' + 모음 → 복합 모음 (Rockwell → …웰, Watsco → 와…)
_W_COMPOUND = {
    "ㅏ": "ㅘ", "ㅐ": "ㅙ", "ㅔ": "ㅞ", "ㅓ": "ㅝ", "ㅗ": "ㅝ",
    "ㅣ": "ㅟ", "ㅜ": "ㅜ", "ㅡ": "ㅜ", "ㅕ": "ㅝ", "ㅑ": "ㅘ",
}


def _preprocess(word):
    w = word.lower()
    w = re.sub(r"[^a-z&]", "", w)
    if w == "&":
        return "and"
    w = w.replace("&", "and")
    for pat, rep in _PRE_RULES:
        w = re.sub(pat, rep, w)
    # 묵음 e: 자음 뒤 어말 e 는 대체로 발음되지 않습니다(핵심 예외는 위 규칙에서 이미 처리).
    if len(w) > 3 and w.endswith("e") and w[-2] not in _VOWEL_LETTERS:
        w = w[:-1]
    return w


def _tokenize(word):
    """전처리된 알파벳 문자열을 [('C', 자음키) | ('V', 모음자모)] 시퀀스로 자릅니다."""
    tokens = []
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        if ch in _VOWEL_LETTERS or ch == "y":
            matched = False
            for spell, jamo in _VOWELS:
                if word.startswith(spell, i):
                    # 단모음 'u' 는 열린음절(뒤에 자음+모음)에서는 'ㅜ'(Sunoco→수노코),
                    # 닫힌음절(뒤에 자음으로 끝남)에서는 'ㅓ'(Sun→선) 로 읽는 관행을 근사합니다.
                    if spell == "u":
                        nxt = word[i + 1: i + 2]
                        nxt2 = word[i + 2: i + 3]
                        if nxt and nxt not in _VOWEL_LETTERS and nxt2 in _VOWEL_LETTERS:
                            jamo = "ㅜ"
                    tokens.append(("V", jamo))
                    i += len(spell)
                    matched = True
                    break
            if matched:
                continue
            if ch == "y":
                # 뒤에 모음이 오면 자음 y(yes), 아니면 모음 'ㅣ'(Incyte → 인시트)
                if word[i + 1: i + 2] in _VOWEL_LETTERS:
                    tokens.append(("C", "y"))
                else:
                    tokens.append(("V", "ㅣ"))
                i += 1
                continue
            tokens.append(("V", "ㅣ"))
            i += 1
            continue
        # 자음: 2글자 조합 우선
        two = word[i:i + 2]
        if two in _CONSONANTS:
            tokens.append(("C", two))
            i += 2
            continue
        if ch in _CONSONANTS:
            tokens.append(("C", ch))
            i += 1
            continue
        i += 1   # 알 수 없는 문자는 건너뜁니다
    return tokens


def _transliterate_word(word):
    """단어 1개를 한글로 음역합니다(근사치)."""
    if not word:
        return ""
    raw = re.sub(r"[^A-Za-z&]", "", word)
    if not raw:
        return ""
    # 전부 대문자이고 짧으며 **모음 비율이 낮으면**(=단어처럼 읽히지 않으면) 약어로 보고
    # 낱자 읽기 (IBM→아이비엠, CVS→씨브이에스). CAVA·VISA 처럼 모음이 충분해 단어로
    # 읽히는 이름은 약어 처리하지 않고 일반 음역 경로를 탑니다.
    if raw.isupper() and len(raw) <= 4:
        vowel_ratio = sum(1 for c in raw.lower() if c in _VOWEL_LETTERS) / len(raw)
        if vowel_ratio < 0.4:
            return "".join(_LETTER_NAMES.get(c.lower(), "") for c in raw)

    tokens = _tokenize(_preprocess(word))
    if not tokens:
        return ""

    out = []
    i = 0
    n = len(tokens)
    while i < n:
        kind, val = tokens[i]
        if kind == "V":
            # 초성 없는 모음 음절도 뒤따르는 m/n/ng/l 은 받침으로 흡수합니다(Incyte → 인…)
            jong = ""
            if i + 1 < n and tokens[i + 1][0] == "C":
                can_jong = _CONSONANTS[tokens[i + 1][1]][1]
                after_is_vowel = (i + 2 < n and tokens[i + 2][0] == "V")
                if can_jong and not after_is_vowel:
                    jong = can_jong
                    i += 1
            out.append(_compose("ㅇ", val, jong))
            i += 1
            continue

        # 자음 다음에 모음이 오면 초성으로 결합
        if i + 1 < n and tokens[i + 1][0] == "V":
            cho = _CONSONANTS[val][0]
            jung = tokens[i + 1][1]
            if val == "w":
                jung = _W_COMPOUND.get(jung, jung)
            jong = ""
            # 뒤따르는 자음이 받침으로 쓸 수 있고, 그 다음이 모음이 아니면 받침 처리
            if i + 2 < n and tokens[i + 2][0] == "C":
                nxt = tokens[i + 2][1]
                can_jong = _CONSONANTS[nxt][1]
                after_is_vowel = (i + 3 < n and tokens[i + 3][0] == "V")
                if can_jong and not after_is_vowel:
                    jong = can_jong
                    i += 1
            out.append(_compose(cho, jung, jong))
            i += 2
            continue

        # 모음이 안 따라오는 자음 — 'r'은 모음 뒤에서 대체로 표기하지 않습니다(car→카, park→파크)
        if val == "r" and out:
            i += 1
            continue
        cho, _jong, filler = _CONSONANTS[val]
        # 자음 + l + 모음(pl-, bl-, cl-, fl-, gl-)은 한국어 관행상 앞 음절에 ㄹ 받침을
        # 붙입니다(Plexus → 플렉서스, Global → 글로벌). 뒤의 l 은 다음 음절 초성으로 다시 씁니다.
        # (tr-/gr- 등 r 계열은 '트레인'처럼 받침을 안 쓰므로 제외합니다.)
        if (i + 2 < n and tokens[i + 1][0] == "C" and tokens[i + 1][1] == "l"
                and tokens[i + 2][0] == "V"):
            out.append(_compose(cho, filler, "ㄹ"))
            i += 1
            continue
        out.append(_compose(cho, filler))
        i += 1

    return "".join(out)


# 회사명에 자주 나오는 단어는 통용 표기를 그대로 씁니다(음역보다 정확).
_WORD_KO = {
    "technologies": "테크놀로지스", "technology": "테크놀로지", "tech": "테크",
    "group": "그룹", "groupe": "그룹", "systems": "시스템즈", "system": "시스템",
    "energy": "에너지", "financial": "파이낸셜", "finance": "파이낸스",
    "bank": "뱅크", "bancorp": "뱅코프", "bankshares": "뱅크셰어스",
    "pharmaceuticals": "파마슈티컬스", "pharmaceutical": "파마슈티컬", "pharma": "파마",
    "international": "인터내셔널", "industries": "인더스트리스", "industrial": "인더스트리얼",
    "holdings": "홀딩스", "holding": "홀딩", "partners": "파트너스", "properties": "프로퍼티스",
    "communications": "커뮤니케이션스", "solutions": "솔루션스", "services": "서비시스",
    "resources": "리소시스", "materials": "머티리얼스", "electric": "일렉트릭",
    "electronics": "일렉트로닉스", "global": "글로벌", "digital": "디지털",
    "networks": "네트웍스", "network": "네트워크", "semiconductor": "세미컨덕터",
    "insurance": "인슈어런스", "capital": "캐피탈", "trust": "트러스트",
    "enterprises": "엔터프라이지스", "enterprise": "엔터프라이즈",
    "health": "헬스", "healthcare": "헬스케어", "medical": "메디컬", "sciences": "사이언시스",
    "science": "사이언스", "biosciences": "바이오사이언시스", "therapeutics": "테라퓨틱스",
    "foods": "푸즈", "food": "푸드", "brands": "브랜즈", "stores": "스토어스",
    "airlines": "에어라인스", "motors": "모터스", "automotive": "오토모티브",
    "software": "소프트웨어", "data": "데이터", "cloud": "클라우드", "media": "미디어",
    "entertainment": "엔터테인먼트", "resorts": "리조츠", "hotels": "호텔스",
    "petroleum": "페트롤리엄", "oil": "오일", "gas": "가스", "mining": "마이닝",
    "steel": "스틸", "chemical": "케미컬", "chemicals": "케미컬스",
    "realty": "리얼티", "residential": "레지덴셜", "management": "매니지먼트",
    "investment": "인베스트먼트", "investments": "인베스트먼츠",
    "corporation": "코퍼레이션", "products": "프로덕츠", "brands.": "브랜즈",
    "and": "앤드", "of": "오브", "the": "더", "for": "포", "de": "드",
    "first": "퍼스트", "american": "아메리칸", "united": "유나이티드",
    "general": "제너럴", "national": "내셔널", "standard": "스탠더드",
    "worldwide": "월드와이드", "advanced": "어드밴스드", "applied": "어플라이드",
    "new": "뉴", "north": "노스", "south": "사우스", "east": "이스트", "west": "웨스트",
}


def transliterate_to_hangul(english_name):
    """
    영문 회사명을 한글로 음역합니다(정식 한글명이 없을 때의 자동 표기).

    ⚠️ 근사치입니다. 영어 철자↔발음이 1:1이 아니라 규칙만으로는 완벽할 수 없습니다.
       틀린 표기는 `KR_NAME_OVERRIDES` 에 티커를 추가해 고쳐 주세요.
    """
    base = clean_company_name(english_name)
    if not base:
        return ""
    parts = []
    for token in base.split():
        key = re.sub(r"[^a-z]", "", token.lower())
        if key in _WORD_KO:
            parts.append(_WORD_KO[key])
            continue
        ko = _transliterate_word(token)
        if ko:
            parts.append(ko)
    return "".join(parts)


def resolve_korean_name(symbol, english_name):
    """
    한글 표기를 결정합니다.

    반환: {
      "korean_name"      : 화면에 쓸 한글명 (만들지 못하면 None — 지어내지 않음)
      "source"           : "official_dict"(정식 한글명) | "transliterated"(자동 음역) | None
      "is_transliterated": bool  (UI가 '음역' 배지를 붙일지 판단)
      "english_clean"    : 상품 설명을 뗀 영문 회사명
    }
    """
    english_clean = clean_company_name(english_name)
    key = str(symbol or "").strip().upper().replace("/", ".")
    if key in KR_NAME_OVERRIDES:
        return {
            "korean_name": KR_NAME_OVERRIDES[key],
            "source": "official_dict",
            "is_transliterated": False,
            "english_clean": english_clean,
        }
    ko = transliterate_to_hangul(english_name)
    if not ko:
        # 음역조차 못 했으면 영문명을 한글인 척 내보내지 않고 None 을 돌려줍니다(§0-1).
        return {
            "korean_name": None,
            "source": None,
            "is_transliterated": False,
            "english_clean": english_clean,
        }
    return {
        "korean_name": ko,
        "source": "transliterated",
        "is_transliterated": True,
        "english_clean": english_clean,
    }


if __name__ == "__main__":   # 간단 수동 확인용
    samples = [
        ("NVDA", "NVIDIA Corporation Common Stock"),
        ("GLW", "Corning Incorporated Common Stock"),
        ("MLM", "Martin Marietta Materials Inc. Common Stock"),
        ("SUN", "Sunoco LP Common Units representing limited partner interests"),
        ("ROK", "Rockwell Automation Inc. Common Stock"),
        ("PLXS", "Plexus Corp. Common Stock"),
        ("CAVA", "CAVA Group Inc. Common Stock"),
        ("MAC", "Macerich Company (The) Common Stock"),
    ]
    for sym, nm in samples:
        print(sym, "->", resolve_korean_name(sym, nm))
