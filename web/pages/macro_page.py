"""
🏢 매크로 방공망 — 시장 종합 위험 지수 화면 (**관리자 전용**, URL `/admin/macro`).

`views/macro_view.py`(Streamlit, 1,428줄)의 NiceGUI 이식본입니다 (이전 계획서 6단계).
Streamlit 쪽 원본은 컷오버까지 그대로 살려둡니다(듀얼런 — 계획서 §11-1).

🛑 **이 화면은 오너 지시로 "개발 중단" 상태입니다** (PROJECT_STATUS.md 최상단 배너,
   2026-08-10). 그래서 이번 작업의 목표는 **기능을 그대로 옮기는 것 하나뿐**입니다 —
   지표를 늘리거나, 계산을 바꾸거나, 화면을 "더 낫게" 손보지 않았습니다. 화면 안의
   "🔒 관리자 전용 / 재설계 대기" 안내 배너도 원문 그대로 유지합니다.
   매크로 재설계(남은 프록시 2개 실측 전환 등)는 **오너가 명시적으로 지시하기 전까지
   착수하지 않습니다.**

🔒 접근 통제 (§0-3-6 · §0-3-9)
   - `@ui.page('/admin/macro')` 첫 줄에서 `is_admin()` 을 확인하고, 아니면 **본문을 한
     글자도 그리지 않고** 관리자 비밀번호 폼만 그립니다. 게이트 폼은 `/admin` 과
     **같은 함수**(`admin_page.render_admin_login`)를 씁니다 (§0-3-10 중복 금지).
   - 드로어 메뉴에도 관리자에게만 보입니다(`web/layout.py`) — 공개 화면에 관리자 입구를
     광고하지 않습니다.

이식 방침
   - **계산은 한 줄도 바꾸지 않았습니다.** `fetch_verified_market_data()` 는 원본을 그대로
     옮긴 것이고, 가중치·정규화·증폭기는 여전히 `utils/constants.py` / `utils/macro_scoring.py`
     단일 출처만 호출합니다(원본과 동일). `layers` / `FRIENDLY_NAMES` /
     `STUDY_ONLY_INDICATORS` / `DROPPED_AS_DUPLICATE` 상수는 원본에서 **글자 그대로**
     복사했고, `tests/test_web_session_isolation.py` [8] 이 두 파일의 리터럴이 같은지
     자동으로 대조합니다.
   - `st.line_chart` 는 **원본에 이미 없습니다.** 배포 환경의 altair 버그 때문에 예전에
     `plotly.express.line` 으로 교체돼 있었고(원본 1248~1254줄 주석), 여기서도 같은
     `px.line(x="Date", y="위험 지수")` 를 그대로 씁니다 — 계열 1개·값 동일.
   - `st.components.v1.html` 도 **원본에 이미 없습니다.** 고정 높이 700px iframe 이 표 아래를
     잘라먹어서 이미 `st.markdown` 으로 바뀌어 있었습니다(원본 1073~1078줄 주석).
     여기서는 `ui.html` + 가로 스크롤 컨테이너로 옮겼습니다.
   - `<style>` 블록(아파트 카드·분석표)은 `web/theme.py` 로 옮겼습니다 — 규칙·수치는 그대로.
   - `utils/db.py` 의 화면 출력(`st.warning/write/error/session_state` 7곳)은 **콜백**으로
     바뀌었습니다. 이 화면이 그 콜백에 배너를 그려 넣어, 실패 사실이 예전처럼 화면까지
     도달합니다(§0-1). 관리자 여부도 전역에서 추측하지 않고 `is_admin=` 로 넘깁니다(§0-3-8).
   - 외부에서 온 문자열(AI 코멘트 JSON 등)이 HTML 로 나가는 자리는 전부 `esc()` 를 거칩니다
     (§0-3-9). 원본은 AI 생성 텍스트를 그대로 넣고 있었습니다 — 이식하며 고쳤습니다.
   - 예외 원문은 화면에 흘리지 않고 서버 로그로만 보냅니다 (§0-3-4).

🔑 환경변수 — **이 화면은 `GEMINI_API_KEY` / `KRX_OPENAPI_KEY` 를 읽지 않습니다.**
   두 키는 배치(`scrape_daily.py` → `utils/macro_ai.py` / `utils/krx_openapi.py`)에서만
   쓰이고, 이 화면은 그 결과물(`market_history.csv`, `data/macro_commentary.json`)을
   읽기만 합니다. 원본도 정확히 같습니다(원본 456~459줄: "여기서 렌더링 중에 KRX API를
   호출하지는 않습니다"). 그래서 Render 에 두 키가 없어도 이 화면은 원본과 **동일하게**
   동작합니다 — AI 코멘트 파일이 없으면 지표마다 "AI 코멘트가 준비되지 않았습니다."가
   뜨고, KRX 실측 컬럼이 없으면 그 지표만 "데이터 없음 / 산출 불가"로 빠집니다(§0-1).
"""

import os
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = None

import pandas as pd
from nicegui import ui

# 2026-08-06 2차 감사 5-1/5-2: 가중치·정규화 로직을 scrape_daily.py와 공유하는 단일 출처
from utils.constants import RISK_WEIGHTS, INVESTOR_WEIGHTS
from utils.db import COL_MAP, HISTORY_FILE, save_and_load_history
from utils.macro_scoring import (
    compute_historical_stats, compute_sub_scores, compute_final_score,
    EXTREME_SUB_SCORE_HIGH, EXTREME_SUB_SCORE_LOW,
    # 2026-08-10 (#68): 실측 지표(3주체 순매수 금액 / KOSPI 5일 수익률) 정규화 —
    # scrape_daily.py(저장)와 이 화면(미리보기)이 반드시 같은 함수를 써야 척도가 어긋나지 않습니다.
    measured_downside_risk, net_flow_population, rolling_return_population,
)

from web.auth import is_admin
from web.components import (
    banner, chart_layout, compact, download_button, error_banner, esc,
    info_banner, success_banner, warning_banner,
)
from web.layout import layout
from web.pages.admin_page import render_admin_login
from web.state import (
    PAGE_RESPONSE_TIMEOUT_SECONDS,
    data_path,
    load_json_file_async,
)

# 차트는 plotly 로 그립니다(원본과 동일 — altair 버그 회피용으로 이미 교체돼 있었습니다).
# 없을 때 화면 전체가 죽지 않도록 감싸둡니다(`web/pages/scorecard_page.py` 와 같은 방식).
try:
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:  # pragma: no cover - 배포 환경엔 항상 설치됨
    px = None
    PLOTLY_AVAILABLE = False


# 차트 배경/글자색 — 이 화면은 다크 모드 고정(web/layout.py)이라 plotly 기본 흰 배경을 쓰면
# 차트만 하얗게 뜹니다. **figure 의 데이터(x/y/계열)는 원본과 한 글자도 다르지 않고**,
# 배경 투명화·글자색·선 색만 지정합니다 (계획서 §7, scorecard_page.py 와 같은 이유).
# `colorway` 첫 색(#636EFA)이 plotly 기본 팔레트의 첫 색이라, Streamlit 에서 보던 선 색과
# 같은 색이 나옵니다.
#
# (2026-08-17) 배경·글자색 공통 부분은 `web/components/widgets.py::chart_layout()` 로
#  옮겼습니다 — '내 성적표'가 거의 같은 사전을 따로 들고 있어서(차이는 `colorway` /
#  `piecolorway` 뿐) 테마 색을 한쪽만 고치면 두 화면이 어긋나는 구조였습니다 (§0-3-10).
_LINE_COLORS = ("#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A")


def _chart_layout() -> dict:
    """이 화면의 선 차트 레이아웃 = 공통 다크 테마 + 이 화면 고유 선 색."""
    return chart_layout(colorway=list(_LINE_COLORS))



layers = {
    10: ("10층", "💥 최극상 위험", "주식 0% / 현금 100%", "완전 대피 및 현금 최대 확보"),
    9:  ("9층", "🚨 극심한 위험", "주식 10% / 현금 90%", "주식 신규 매수 절대금지"),
    8:  ("8층", "⚡ 심각한 위험", "주식 20% / 현금 80%", "주식 강제 청산 및 대피"),
    7:  ("7층", "⚠️ 고위험 경고", "주식 30% / 현금 70%", "현금 비중 대폭 확대"),
    6:  ("6층", "🟧 경계 필요", "주식 40% / 현금 60%", "현금 비중 분할 확대"),
    5:  ("5층", "🟨 중립 경계", "주식 50% / 현금 50%", "5:5 중립 포지션 관망"),
    4:  ("4층", "🟩 주의 관찰", "주식 60% / 현금 40%", "분할 익절 및 점진적 현금화"),
    3:  ("3층", "🟢 양호 관망", "주식 70% / 현금 30%", "수급 회복 단계 및 완만한 진입"),
    2:  ("2층", "🟦 청정 안전", "주식 80% / 현금 20%", "주식 비중 확대 및 현물 투자"),
    1:  ("1층", "🔷 매우 안전", "주식 90% / 현금 10%", "적극 주식 매수 집행"),
    0:  ("0층", "⚪ 무위험 지대", "주식 100% / 현금 0%", "하방 위험 없음 / 적극 홀딩")
}

FRIENDLY_NAMES = {
    "FX_Swap_Point": "외환 스왑포인트 (달러 유동성 부족 위험)",
    "Put_OTM_OI": "풋옵션 미결제약정 (시장 하락에 배팅한 투기자본)",
    # (2026-08-10 #72: `Short_Ratio`·`Stock_Short_Balance` 표기명 제거 — 두 지표가 점수에서
    #  빠지고 아래 "📚 공부용 참고" 섹션으로 이동했습니다. 활성 지표가 아니면 이 표에 두지
    #  않습니다. 단 utils/db.py·scrape_daily.py의 COL_MAP 한글 매핑은 과거 CSV 복원을 위해
    #  그대로 남아 있습니다.)
    # ✅ 아래 2개는 추정 프록시가 아니라 실제 측정값 기반입니다 (2026-08-10 #68)
    "Stock_Net_Sell": "주식 현물 순매도 규모 (3주체 순매수 금액 · 실측)",
    "KOSPI_5D_Return": "KOSPI 5일 수익률 (지수 낙폭 · 실측)",
    # ✅ 아래 2개도 실측으로 전환됐습니다 (2026-08-10 #70, KRX OPEN API).
    # ⚠️ 내부 키(`VKOSPI_Skew`/`Synthetic_Futures`)는 일부러 그대로 둡니다 — 키를 바꾸면
    #    market_history.csv 의 기존 컬럼과 연결이 끊겨 과거 기록을 읽을 수 없게 됩니다.
    #    **화면에 보이는 이름은 실제 내용대로** 바꿔, 라벨과 내용이 어긋나지 않게 합니다.
    #    (예전 이름: "공포지수 비대칭성" / "합성선물 가격차이" — 둘 다 실제로는 변동성·환율이었음)
    "VKOSPI_Skew": "VKOSPI 공포지수 (시장이 매긴 향후 변동성 기대 · 실측)",
    "Synthetic_Futures": "선물 베이시스 (KOSPI200 선물 − 지수, 마이너스일수록 하방 압력 · 실측)",
}

# =============================================================================
# 📚 공부용 참고 — 지금 점수에 넣지 않는 지표들 (2026-08-10 #69, #72에서 2개 추가)
# =============================================================================
# 왜 이 표가 여기 있나:
#   아래 앞 4개는 실제 금융시장에서 통용되는 정식 개념이지만, 무료로 구할 수 있는 일별
#   데이터가 없어서 예전에는 "코스피 등락률·환율·수급 부호"를 그럴듯한 이름으로 바꿔
#   부르는 식으로 계산되고 있었습니다. 그건 지표가 아니라 이름표라, 점수에서 뺐습니다.
#   대신 관심 있는 사람이 직접 공부할 수 있도록 "무엇이 필요하고 어디를 보면 되는지"를
#   화면에 남깁니다(오너 요청, 2026-08-10).
#
# ⚠️ 2026-08-10 (#72)에 추가된 마지막 2개(`Short_Ratio`·`Stock_Short_Balance`)는 **앞선
#    4개와 뺀 이유가 다릅니다.** 앞 4개는 "무료로 구할 데이터 자체가 없음"이지만, 공매도
#    2종은 **데이터가 존재합니다**(pykrx로 얻을 수 있음). 다만 그 유일한 무료 경로가
#    data.krx.co.kr의 로그인 요구를 우회하는 방식이라, 이 프로젝트의 크롤링 매너 원칙
#    (ENGINEERING_SPEC §0-3-2)상 쓰지 않기로 오너가 결정한 것입니다. 두 사유를 뭉뚱그리면
#    화면이 거짓말을 하게 되므로, 각 항목의 `missing_data`에 그 차이를 그대로 적었습니다.
#
# ⚠️ `hypothetical_weight`는 **확정 가중치가 아닙니다.** 데이터가 아직 없는데 정확한
#    숫자를 약속하는 건 지어내는 것이므로, "지금 살아있는 지표들이 어느 구간에 분포하는가"에
#    기대어 **범위**로만 적었습니다. 실제 RISK_WEIGHTS에는 들어가지 않습니다
#    (utils/constants.py 참고. 카드 하단에 찍히는 분포 범위는 RISK_WEIGHTS에서 매번 실제로
#     읽어오므로 가중치가 바뀌면 자동으로 따라갑니다).
# ⚠️ 2026-08-10 (#72) 재분배(× 100/85.48)로 활성 가중치가 전반적으로 약 1.17배 커졌습니다.
#    아래 `weight_reasoning` 안에서 **다른 지표의 가중치를 인용한 숫자는 현재 값으로 갱신**
#    했지만, `hypothetical_weight` 범위 자체는 기계적으로 1.17을 곱하지 않았습니다 —
#    애초에 확정치가 아니라 "대략 이 정도"인 참고 범위라, 그렇게 소수점까지 다시 계산하면
#    없는 정밀도를 만들어내는 셈이기 때문입니다(§0-1).
STUDY_ONLY_INDICATORS = [
    {
        "key": "ELS_KnockIn",
        "title": "ELS 낙인(Knock-In) 위험",
        "one_liner": "원금이 깨지기 시작하는 선(낙인 배리어) 아래로 기초지수가 내려간 ELS가 "
                     "얼마나 쌓여 있는지를 보는 지표입니다.",
        "why_it_matters": "ELS는 '지수가 일정 선(보통 최초 기준가의 45~65%) 아래로만 안 떨어지면 "
                          "이자를 준다'는 구조의 상품입니다. 그 선을 건드리면 원금 손실이 확정될 수 "
                          "있어 투자자 손실이 한꺼번에 터지고, 그 상품을 판 증권사도 헤지 포지션을 "
                          "급하게 정리하느라 시장에 추가 매물이 나옵니다. 실제로 홍콩H지수(HSCEI)를 "
                          "기초자산으로 한 ELS에서 대규모 손실 사태가 반복해서 벌어졌고, 2020년 3월 "
                          "폭락 때는 증권사들이 ELS 헤지 과정에서 마진콜(추가 증거금 요구)을 맞아 "
                          "달러 자금 조달난까지 겪었습니다.",
        "missing_data": "개별 ELS의 ① 낙인 배리어 수준, ② 기초자산(코스피200·S&P500·H지수 등)의 "
                        "현재가 대비 여유, ③ 그 조건별 미상환 잔액 — 이 세 가지가 한 세트로 "
                        "매일 공개되어야 '오늘 얼마나 위험한가'를 셀 수 있는데, 무료로 공개되는 건 "
                        "월 단위 발행·미상환 집계뿐입니다.",
        "how_to_study": [
            "예탁결제원 증권정보포털(SEIBro) → '파생결합증권(ELS/DLS) 발행·미상환 현황' — "
            "월 단위지만 잔액 규모와 기초자산 구성을 볼 수 있습니다.",
            "한국은행 「금융안정보고서」 — ELS 관련 위험을 정기적으로 분석한 챕터가 실립니다. "
            "검색어: '금융안정보고서 ELS 낙인'.",
            "금융감독원 보도자료 검색어: 'ELS 미상환 잔액', 'ELS 손실 가능 규모'.",
            "개념 학습 검색어: '낙인(Knock-In) 배리어', '스텝다운형 ELS 구조', 'ELS 헤지 마진콜'.",
        ],
        "hypothetical_weight": "대략 5~10 정도 (참고 범위)",
        "weight_reasoning": "평상시엔 거의 움직이지 않다가 특정 국면에서만 급격히 의미가 생기는 "
                            "'잔고성' 지표라, 지금 활성 지표 중 가장 낮은 구간(주식 현물 순매도 5.66)과 "
                            "시장 전체 파생 지표(VKOSPI 11.32) 사이가 자연스러워 보입니다. 다만 데이터가 "
                            "월 단위라면 매일 점수에 넣기보다 '경보 플래그'로 쓰는 편이 정직합니다.",
    },
    {
        "key": "NDF_Night_Rate",
        "title": "야간 역외 원/달러 환율 (NDF)",
        "one_liner": "한국 시장이 문을 닫은 밤사이 해외에서 거래된 원/달러 환율입니다. "
                     "다음 날 아침 시가가 어디서 열릴지를 미리 보여줍니다.",
        "why_it_matters": "NDF(차액결제선물환)는 원화를 실제로 주고받지 않고 차액만 정산하는 "
                          "역외 거래라, 외국인이 원화 자산에서 발을 뺄 때 가장 먼저 반응하는 곳 중 "
                          "하나입니다. 밤사이 NDF 환율이 크게 뛰면 다음 날 국내 증시가 갭하락으로 "
                          "시작하는 경우가 잦습니다.",
        "missing_data": "일별 NDF 종가(보통 1개월물)를 무료로 공표하는 곳을 찾지 못했습니다. "
                        "서울외국환중개 홈페이지의 NDF 페이지에는 상품 설명만 있고 시세표가 "
                        "없다는 것을 직접 열어 확인했습니다(2026-08-09). 인포맥스·로이터 같은 "
                        "유료 단말 영역입니다.",
        "how_to_study": [
            "서울외국환중개(smbs.biz) — 환율·스왑포인트 고시가 어떤 형태로 공개되는지 구경해 보세요. "
            "같은 회사 페이지인데 F/X Swap POINT는 조회가 되고 NDF는 안 되는 차이가 보입니다.",
            "한국은행 경제통계시스템(ECOS) — 환율·외환 관련 통계표 목록 훑어보기. 검색어: "
            "'ECOS 환율 통계', '한국은행 외환시장 동향'.",
            "언론 검색어: '역외 NDF 환율', '역외 원화 환율 상승', '차액결제선물환'.",
            "제도 배경 검색어: '외환시장 구조 개선', '국내 외환시장 개장시간 연장', 'RFI 제도' — "
            "국내 외환시장 운영시간이 새벽까지 늘어나면서 NDF의 역할이 예전과 어떻게 달라졌는지가 "
            "그 자체로 좋은 공부거리입니다.",
        ],
        "hypothetical_weight": "대략 8~12 정도 (참고 범위)",
        "weight_reasoning": "다음 날 갭하락과 직결되는 강한 신호지만, 지금 살아있는 "
                            "외환 스왑포인트(22.64)와 **같은 '달러 자금·환율' 채널**입니다. "
                            "둘을 따로 세면 같은 위험을 두 번 세는 셈이라, NDF가 들어온다면 그 채널 "
                            "안에서 스왑포인트와 비중을 나눠 갖는 형태가 맞습니다.",
    },
    {
        "key": "Futures_Net_Sell",
        "title": "투자자별 코스피200 선물 순매도",
        "one_liner": "외국인·기관이 선물시장에서 얼마나 순매도했는지입니다. "
                     "현물보다 먼저 방향을 트는 경우가 많아 뉴스에 자주 등장합니다.",
        "why_it_matters": "선물은 현물보다 적은 돈으로 큰 포지션을 잡을 수 있어, 방향에 대한 "
                          "베팅이 먼저 나타나는 시장입니다. '외국인 선물 O천 계약 순매도' 같은 "
                          "기사가 나오는 이유이고, 선물 매도는 프로그램(차익) 매매를 통해 "
                          "현물 매도로 옮겨붙기도 합니다.",
        "missing_data": "투자자 유형별 선물 순매수/순매도 계약수. KRX 정보데이터시스템 화면에는 "
                        "있지만 2025-12-27부터 로그인이 필요해졌고, 무료 KRX OPEN API에는 "
                        "'투자자별 파생상품 매매' 서비스가 아예 없습니다(7개 카테고리 전수 확인). "
                        "종목별 매매정보만 제공되어 주체 구분이 불가능합니다.",
        "how_to_study": [
            "KRX 정보데이터시스템(data.krx.co.kr) → '파생상품 > 투자자별 거래실적' 화면을 "
            "직접 눈으로 보면 어떤 필드가 있는지 감이 옵니다(회원 가입 필요).",
            "개념 검색어: '선물 미결제약정', '베이시스(선물-현물 가격차)', '백워데이션', "
            "'콘탱고', '만기일 롤오버'.",
            "매일 장 마감 후 나오는 '외국인 선물 순매수 동향' 기사와 다음 날 지수를 짝지어 "
            "직접 기록해 보면, 이 지표가 실제로 얼마나 먼저 움직이는지 스스로 확인할 수 있습니다.",
        ],
        "hypothetical_weight": "대략 6~10 정도 (참고 범위)",
        "weight_reasoning": "지금 활성 지표 중 성격이 비슷한 공포지수(VKOSPI)가 11.32를 "
                            "받고 있어 그 언저리가 출발점입니다. 다만 선물 베이시스"
                            "(현재 'Synthetic_Futures' 자리, 22.64)와 정보가 상당히 겹치므로, "
                            "둘을 같이 쓴다면 합쳐서 보고 각각은 낮추는 편이 맞습니다.",
    },
    {
        "key": "Non_Arbitrage_Ratio",
        "title": "비차익 프로그램 매매 비중",
        "one_liner": "여러 종목을 한 번에 묶어서 사고파는 '바스켓 주문' 중, 선물과의 가격차를 "
                     "노린 차익거래가 아닌 순수 방향성 주문이 얼마나 되는지입니다.",
        "why_it_matters": "프로그램매매는 차익(선물-현물 가격차를 먹는 기계적 거래)과 비차익"
                          "(그냥 바스켓으로 사고파는 것)으로 나뉩니다. 비차익 순매도가 크게 나오면 "
                          "외국인·기관이 '한국 주식 전체'를 줄이고 있다는 뜻이라, 개별 종목 악재와 "
                          "구분되는 시장 전체 신호로 읽힙니다.",
        "missing_data": "차익/비차익을 구분한 프로그램매매 통계. KRX 정보데이터시스템 화면 "
                        "전용이고(현재 로그인 필수), KRX OPEN API에는 제공되지 않습니다.",
        "how_to_study": [
            "KRX 정보데이터시스템 → '주식 > 프로그램매매' 화면에서 차익/비차익 구분을 확인.",
            "개념 검색어: '차익거래', '비차익 프로그램매매', '바스켓 매매', "
            "'프로그램 매매 순매수 상위'.",
            "심화: 프로그램 차익거래가 선물 베이시스와 어떻게 연결되는지 — 검색어 "
            "'베이시스 축소 프로그램 매도'. 선물·현물·프로그램 3개가 한 덩어리로 움직이는 "
            "구조를 이해하면 위 '선물 순매도'와 함께 묶어서 보입니다.",
        ],
        "hypothetical_weight": "대략 3~6 정도 (참고 범위)",
        "weight_reasoning": "비차익 프로그램매매는 '외국인 현물 순매도가 실행되는 통로'에 가까워, "
                            "이미 실측으로 살아있는 주식 현물 순매도(5.66)와 상당 부분 같은 사건을 "
                            "가리킵니다. 새로운 정보가 얹히는 폭이 크지 않다고 보아 활성 지표 중 "
                            "가장 낮은 구간에 두는 것이 정직합니다.",
    },
    # -------------------------------------------------------------------------
    # 2026-08-10 (#72) 추가 — 공매도 2종.
    # 위 4개와 달리 **데이터가 없어서가 아니라, 유일한 무료 경로가 로그인 우회라서** 뺐습니다.
    # -------------------------------------------------------------------------
    {
        "key": "Short_Ratio",
        "title": "공매도 거래 비중",
        "one_liner": "하루 전체 거래대금 중에서 '빌린 주식을 먼저 파는' 공매도가 차지하는 "
                     "비율입니다. 값이 높을수록 주가 하락에 베팅하는 거래가 많다는 뜻입니다.",
        "why_it_matters": "공매도는 주식을 빌려서 먼저 팔고 나중에 되사서 갚는 거래라, 파는 "
                          "쪽에 실제 매도 물량이 얹힙니다. 특정 종목이나 시장 전체에서 공매도 "
                          "비중이 갑자기 튀면 '누군가 하락 쪽에 크게 걸고 있다'는 신호로 읽히고, "
                          "반대로 주가가 오르면 빌린 주식을 급히 되사는 숏커버링이 나오면서 "
                          "단기 급등을 만들기도 합니다. 한국 시장에서는 공매도 금지·재개가 "
                          "여러 차례 반복되며 그 자체가 큰 뉴스가 됐을 만큼 민감한 지표입니다.",
        "missing_data": "⚠️ 이건 앞의 4개와 사정이 다릅니다. **데이터 자체는 존재합니다.** "
                        "KRX가 투자자별·종목별 공매도 거래량·거래대금을 매일 집계하고 있고, "
                        "`pykrx` 라이브러리의 `get_shorting_volume_by_date()` 같은 함수로 "
                        "실제로 받아올 수도 있습니다. 그런데 KRX 정보데이터시스템"
                        "(data.krx.co.kr)이 2025-12-27부터 회원제(로그인 필수)로 바뀌었고, "
                        "pykrx는 그 로그인 요구를 Referer 헤더를 조작해 우회하는 방식으로 "
                        "동작합니다. 이 프로젝트는 '로그인 우회 크롤링을 하지 않는다'는 원칙"
                        "(ENGINEERING_SPEC §0-3-2)을 지키기로 해서, **데이터가 없어서가 아니라 "
                        "그 경로를 쓰지 않기로 해서** 이 지표를 점수에서 뺐습니다. KRX 공식 "
                        "OPEN API에는 공매도 관련 서비스가 아예 없다는 것도 7개 카테고리를 전부 "
                        "확인했습니다(2026-08-09). 예전 계산식은 실제로는 "
                        "`0.4 + 0.4×(코스피 변동성/5)`라 이름만 공매도였습니다.",
        "how_to_study": [
            "KRX 정보데이터시스템(data.krx.co.kr) → '주식 > 공매도 현황' 화면에서 일별 공매도 "
            "거래대금·비중을 **직접 눈으로** 확인해 보세요(회원 가입 필요). 종목별·투자자별로 "
            "어떤 항목이 제공되는지 감을 잡는 데 가장 빠릅니다.",
            "`pykrx` 라이브러리 자체를 뜯어보는 것도 좋은 공부입니다 — 파이썬으로 국내 시장 "
            "데이터를 다루는 대표적인 오픈소스라 코드 구조를 읽어볼 가치가 있습니다. "
            "⚠️ 다만 **이 프로젝트에서는 위 원칙 때문에 쓰지 않습니다.** 개인 학습용으로 "
            "돌려보더라도 짧은 간격으로 반복 호출하지 않는 것이 예의입니다.",
            "개념 검색어: '공매도 거래대금 비중', '숏커버링', '대차거래 잔고', "
            "'차입 공매도와 무차입 공매도 차이'.",
            "제도·이슈 검색어: '공매도 금지 조치', '공매도 재개', '공매도 전산화 시스템' — "
            "한국에서 이 지표가 왜 유난히 민감한 주제인지 배경을 알 수 있습니다.",
        ],
        "hypothetical_weight": "대략 8~12 정도 (참고 범위)",
        "weight_reasoning": "점수에서 빼기 직전 이 지표의 가중치가 9.68이었고(2026-08-10 #69 "
                            "재분배 기준), 시장 전체의 하락 베팅 강도를 보는 다른 파생 지표들과 "
                            "성격이 비슷해 그 언저리가 자연스러운 출발점입니다. 다만 공매도 "
                            "통계는 T+2 지연으로 공표돼 '오늘의 위험'을 재기에는 며칠 늦고, "
                            "지금 살아있는 VKOSPI(11.32)와도 '하락 대비 심리'라는 면에서 정보가 "
                            "일부 겹칩니다. **확정 가중치가 아닙니다.**",
    },
    {
        "key": "Stock_Short_Balance",
        "title": "공매도 잔고",
        "one_liner": "공매도로 팔았지만 아직 되사서 갚지 않은 주식이 얼마나 남아 있는지입니다. "
                     "'하루치 거래'가 아니라 '쌓여 있는 포지션'을 보는 지표입니다.",
        "why_it_matters": "거래 비중이 오늘 하루의 흐름이라면, 잔고는 하락 베팅이 얼마나 "
                          "누적돼 있는지를 보여줍니다. 잔고가 많이 쌓인 상태에서 주가가 오르기 "
                          "시작하면 빌린 주식을 되사려는 주문이 한꺼번에 몰려 급등(숏스퀴즈)이 "
                          "나올 수 있고, 반대로 잔고가 계속 늘면 시장이 그 종목·지수의 하락을 "
                          "지속적으로 보고 있다는 뜻으로 읽힙니다.",
        "missing_data": "⚠️ 위 '공매도 거래 비중'과 **완전히 같은 사정**입니다. 데이터가 없는 게 "
                        "아니라 경로가 문제입니다 — KRX는 공매도 잔고수량·잔고금액·상장주식수 "
                        "대비 비중을 매일 집계하고 `pykrx`의 `get_shorting_balance_by_date()`로 "
                        "받아올 수 있지만, 그 경로가 data.krx.co.kr 로그인 우회(2025-12-27 회원제 "
                        "전환)라 §0-3-2 원칙상 쓰지 않기로 했습니다. 참고로 pykrx 문서에도 "
                        "'잔고 비율 0.01% 미만은 보고 의무가 없어 집계에서 빠질 수 있다'는 한계가 "
                        "적혀 있어, 나중에 쓰게 되더라도 이 단서를 화면에 같이 적어야 합니다. "
                        "예전 계산식은 실제로는 `0.5 + 0.3×(52주 고점 대비 낙폭)`이라 이름만 "
                        "공매도 잔고였습니다.",
        "how_to_study": [
            "KRX 정보데이터시스템(data.krx.co.kr) → '주식 > 공매도 현황 > 공매도 잔고' 화면에서 "
            "종목별 잔고수량·잔고비중을 직접 확인해 보세요(회원 가입 필요). "
            "금융감독원 공시 쪽에서도 대량 공매도 잔고 보유자 공시를 볼 수 있습니다.",
            "`pykrx` 라이브러리를 읽어보며 '이 데이터가 원래 어디서 어떻게 나오는지'를 따라가 "
            "보는 것도 좋은 학습입니다. ⚠️ **이 프로젝트에서는 로그인 우회 원칙(§0-3-2) 때문에 "
            "쓰지 않습니다** — 라이브러리가 나쁘다는 뜻이 아니라, 우리가 정한 규칙을 우리부터 "
            "지키자는 것입니다.",
            "개념 검색어: '공매도 잔고비율', '공매도 잔고 대량보유자 공시', '숏스퀴즈', "
            "'대차잔고와 공매도 잔고의 차이'.",
            "심화: 같은 종목의 '대차잔고'(빌려간 주식 총량)와 '공매도 잔고'(실제로 팔아둔 양)를 "
            "나란히 놓고 보면 왜 두 숫자가 다른지가 보입니다 — 검색어 '대차거래 잔고 추이'.",
        ],
        "hypothetical_weight": "대략 4~7 정도 (참고 범위)",
        "weight_reasoning": "점수에서 빼기 직전 가중치가 4.84였고(#69 재분배 기준), 잔고는 "
                            "매일 크게 움직이는 값이 아니라 천천히 쌓이는 '스톡' 성격이라 "
                            "일간 위험 점수에 주는 정보량이 거래 비중보다 작습니다. 위 "
                            "'공매도 거래 비중'과 같은 사건을 다른 각도에서 보는 것이라 둘을 "
                            "같이 쓴다면 합쳐서 보고 각각은 낮추는 편이 맞습니다. "
                            "**확정 가중치가 아닙니다.**",
    },
]

# 점수에서 뺐고 **공부 목록에도 넣지 않은** 2개 — 왜 뺐는지는 밝혀 둡니다.
# (지표가 조용히 사라지는 것도 정직한 표시가 아니므로)
DROPPED_AS_DUPLICATE = [
    ("외국계 증권사 매도세 (Foreign_Broker_Dump)",
     "계산식이 `0.5 ± (외국인이 순매수인지 순매도인지)`뿐이라, 이미 실측으로 살아있는 "
     "'주식 현물 순매도'의 외국인 항목과 **같은 숫자를 이름만 바꿔 다시 센 것**이었습니다. "
     "'외국계 창구에 매도 물량이 나왔다더라'는 개념 자체도 투자자 유형별 수급(외국인)과 "
     "대부분 겹치고, 창구 주인과 실제 투자자가 일치하지도 않아 별도 지표로 세울 근거가 "
     "약하다고 판단했습니다."),
    ("풋옵션 매수 강도 (Put_Buy_Simple)",
     "'풋옵션 수요'라는 개념은 지금도 살아있는 '풋옵션 미결제약정(Put_OTM_OI)'이 이미 "
     "다루고 있습니다. 둘을 따로 두면 같은 하락 베팅을 두 번 세게 되고, 투자자별 옵션 "
     "매매 데이터는 어차피 무료로 공개되지 않습니다. 풋옵션 공부는 활성 지표 쪽 설명을 "
     "보시면 됩니다."),
]


# 📝 공식 알고리즘 거버넌스 및 5W1H 변경 이력 — 7개 탭 (원본 `st.tabs(...)` 그대로).
#    라벨·본문은 `views/macro_view.py` 에서 글자 그대로 옮기고 공통 들여쓰기만 걷어냈습니다
#    (Streamlit `st.markdown` 이 하던 것과 동일). **튜플이라 값이 바뀔 수 없습니다** —
#    사용자 데이터가 들어갈 자리가 구조적으로 없습니다 (§0-3-8).
_AUDIT_TRAIL = (
    (
        '📄 v1.7.0 (공매도 2종 제외·가중치 재분배)',
        """\
#### 🏷️ [v1.7.0] - 2026년 08월 10일 (공매도 2종 '실측 불가' 재분류 · 가중치 비례 재분배)
* **언제 (When)**: 2026년 08월 10일 (`MACRO_REDESIGN_PROPOSAL.md` §5 구현순서 6번 — 오너 결정 항목)
* **누가 (Who)**: 보이는 손 엔지니어링 (오너 결정 — "pykrx 예외를 허용하지 않는다 = 옵션②")
* **어디를 (Where)**: `utils/constants.py` / `scrape_daily.py` / `views/macro_view.py` / `tests/test_macro_scoring.py`
* **무엇을 (What)**:
    * 8개 → **6개**. `Short_Ratio`(공매도 거래 비중, 9.68)와 `Stock_Short_Balance`(공매도 잔고, 4.84)를
      점수 계산에서 제외하고, 설명·공부법은 **📚 공부용 참고 섹션으로 이동**(삭제가 아닙니다)
    * 두 지표를 계산하던 식(`0.4 + 0.4×(변동성/5)`, `0.5 + 0.3×고점대비낙폭`)과 그 입력값
      (10일 변동성 · 52주 고점 대비 낙폭) 계산을 두 파일에서 함께 제거
    * 남은 6개 가중치는 **기계적 비례 재분배**(× 100/85.48)로 합계 100.00 — 상대 비중은 개정 전과 동일
* **왜 (Why)**: **앞선 6개(v1.6.0)와 사유가 다릅니다.** 공매도 데이터는 **존재합니다** —
  `pykrx` 라이브러리로 실측값을 받아올 수 있습니다. 다만 그 라이브러리는 KRX 정보데이터시스템이
  2025-12-27부터 회원제로 바뀐 뒤에도 로그인 요구를 헤더 조작으로 우회하는 방식이라,
  ENGINEERING_SPEC §0-3-2(로그인 우회 크롤링 금지)와 충돌합니다. KRX 공식 OPEN API에는
  공매도 서비스가 아예 없습니다(7개 카테고리 전수 확인). 오너가 **예외를 허용하지 않기로**
  결정해, 이 2개를 '실측 불가'로 재분류했습니다.
* **어떻게 (How)**: 남은 6개 합 85.48 → × 100/85.48 = 1.1698642957… 후 소수 둘째 자리 반올림.
  **이번에는 단순 반올림 합계가 그대로 정확히 100.00이라 잔여 조정이 필요 없었습니다**
  (v1.6.0 때는 99.99라 0.01을 붙였습니다). 결과: 외환 스왑포인트 22.64 · 선물 베이시스 22.64 ·
  KOSPI 5일 수익률 22.65 · 풋옵션 미결제약정 15.09 · VKOSPI 11.32 · 주식 현물 순매도 5.66.
  이로써 활성 6개 중 **4개가 실측**(KOSPI 5일 수익률 · 주식 현물 순매도 · VKOSPI · 선물 베이시스)입니다.
""",
    ),
    (
        '📄 v1.6.0 (실측불가 6개 제외·가중치 재분배)',
        """\
#### 🏷️ [v1.6.0] - 2026년 08월 10일 (실측 불가 6개 지표 제외 · 가중치 비례 재분배)
* **언제 (When)**: 2026년 08월 10일 (`MACRO_REDESIGN_PROPOSAL.md` §5 구현순서 2번)
* **누가 (Who)**: 보이는 손 엔지니어링 (오너 지시 — "실측 불가 지표는 삭제하지 말고 별도 구분")
* **어디를 (Where)**: `utils/constants.py` / `scrape_daily.py` / `views/macro_view.py` / `utils/db.py`
* **무엇을 (What)**:
    * 14개 → **8개**. 무료 경로로 실측이 불가능하다고 판정된 6개를 점수 계산에서 제외:
      ELS 낙인 / 야간 역외환율(NDF) / 선물 순매도 / 비차익 프로그램 / 외국계 증권사 매도세 / 풋옵션 매수 강도
    * 그중 4개는 **📚 공부용 참고 섹션**으로 이동(설명·공부법만 남기고 계산은 하지 않음),
      2개(외국계 증권사 매도세 · 풋옵션 매수 강도)는 살아있는 지표와 **개념이 중복**되어 완전 제외
    * 남은 8개 가중치는 **기계적 비례 재분배**(× 100/62)로 합계 100.00에 맞춤 —
      지표 간 상대 비중은 개정 전과 **정확히 동일**합니다
* **왜 (Why)**: 이 6개는 라벨만 파생상품이고 실제 입력은 '환율 레벨·지수 등락률·수급 부호'라,
  같은 입력을 이름만 바꿔 여러 번 세는 중복 계산이었습니다(ENGINEERING_SPEC §0-3-1 위반).
  값을 지어내느니 지표를 빼고, 왜 뺐는지를 화면에 밝히는 편이 정직합니다.
* **어떻게 (How)**: 남은 8개 합 62.0 → × 100/62 = 1.6129… 후 소수 둘째 자리 반올림.
  단순 반올림 합이 99.99라 잔여 0.01은 **유일하게 실측이 검증된** KOSPI 5일 수익률에 배정(19.35 → 19.36).
  §4-3의 '실측 직접성 기준 재설계안'은 나머지 지표가 아직 프록시 상태라 **적용하지 않았습니다**
  (KRX OPEN API 연결이 끝난 뒤 한 번에 적용 예정).
""",
    ),
    (
        '📄 v1.5.0 (2차 감사·가중치 단일화)',
        """\
#### 🏷️ [v1.5.0] - 2026년 08월 06일 (2차 감사 반영 · scrape_daily.py/macro_view.py 가중치·척도 단일화)
* **언제 (When)**: 2026년 08월 06일 2차 데이터 무결성 감사(AUDIT_REPORT_V2.md) 후속 조치
* **누가 (Who)**: 보이는 손 엔지니어링 감사 (Claude Opus 정밀 점검)
* **어디를 (Where)**: `scrape_daily.py` / `views/macro_view.py` / `utils/macro_scoring.py`(신설) / `utils/constants.py`
* **무엇을 (What)**:
    * 이 화면(macro_view.py)과 scrape_daily.py가 서로 다른 가중치 사전을 각자 갖고 있던 문제를
      `utils/constants.py`의 `RISK_WEIGHTS` 하나로 통일(이 문서 위 tab의 "10.4 고정 배수"는
      2026-08-03 당시 실제 기록이라 그대로 보존, 그 이후 로직은 계속 진화함)
    * 화면의 "위험도"가 저장된 원시값(0~1)을 단순 ×100 한 근사치였던 것을, 실제 종합점수를
      만드는 시그모이드 정규화 변환과 동일한 척도로 통일(`utils/macro_scoring.py`)
    * 이미 수집된 날짜는 재계산 대신 그날 실제 저장된 서브점수(`SubScore_*`)를 그대로 읽도록 변경
    * 동시 충격 증폭기(구 버전: 극단신호 3개↑ 1.15배/5개↑ 1.3배 flat)를 극단신호 비율에 비례한
      1.0~1.3배 연속 스케일링으로 교체
    * KOSPI 5일 모멘텀·전일 대비 변화율 산출 실패 시 0.0(보합)으로 채우던 것을 제거, 배점 제외로 전환
* **왜 (Why)**: 화면 표의 지표별 기여점수를 다 더해도 위에 뜬 종합 위험 지수와 맞지 않는 등,
  "표시값과 실제 판정값이 다른 소스에서 계산되는" 문제가 반복 발견되었기 때문(2026-08-06 오너 지적)
* **어떻게 (How)**: 가중치·정규화·증폭기 로직을 `utils/macro_scoring.py` 단일 모듈로 옮기고
  scrape_daily.py/macro_view.py 양쪽 모두 이 모듈만 호출하도록 변경
""",
    ),
    (
        '📄 v1.4.0 (데이터 무결성 감사 반영)',
        """\
#### 🏷️ [v1.4.0] - 2026년 08월 05일 (하드코딩·더미 데이터 전면 제거)
* **언제 (When)**: 2026년 08월 05일 데이터 무결성 감사(AUDIT_REPORT.md) 후속 조치
* **누가 (Who)**: 보이는 손 엔지니어링 감사 (Claude Opus 정밀 점검)
* **어디를 (Where)**: `collector_kospi200.py` / `views/macro_view.py` / `views/pegy_view.py` / `utils/*.py`
* **무엇을 (What)**:
    * 매크로 화면의 **KOSPI 2,500 / 환율 1,350 하드코딩 폴백 완전 삭제** (데이터 없으면 오류 배너 + 렌더링 중단)
    * 종목코드 해시(`code_hash % 3`)로 만들던 **가짜 변동성 판정 삭제** → 실제 20일 수익률 표준편차로 대체, 산출 불가 시 벌점 없음
    * Forward ROE / ROIC 상수(8.5 / 6.8) 및 t_roe 파생값 삭제 → **'데이터 없음' 표기 + 배점에서 제외**
    * 성장률을 ROE 파생값이 아닌 **네이버 실측 추정EPS vs TTM EPS 증감률**로 재산출
    * 자사주 매입 2.5% 가정 삭제 → 주주환원율은 **배당수익률만** 반영
    * 상장주식수 파싱에 **범위 검증(100만 주 미만 거부)** 도입 → '총 0억원' 오표기 차단
    * 지표 결측 시 0.5(중립) 대입 금지 → **가중평균에서 제외 + 표에 '데이터 없음' 표기**
* **왜 (Why)**: 실패한 수집을 그럴듯한 숫자로 덮으면 어디가 잘못됐는지 영원히 알 수 없기 때문 (ENGINEERING_SPEC §0-1)
* **어떻게 (How)**: 모든 실패 경로에서 `None` 반환 → UI에 '데이터 없음/산출 불가' 노출, 배치 수집기는 예외로 중단
""",
    ),
    (
        '📄 v1.3.1 (로직 원복)',
        """\
#### 🏷️ [v1.3.1] - 2026년 08월 03일 (계산 공식 원복 및 점수 안정화)
* **언제 (When)**: 2026년 08월 03일 심야 시스템 패치 적용
* **누가 (Who)**: **보이는 손 AI 분석팀**
* **어디를 (Where)**: collector_kospi200.py / views/macro_view.py
* **무엇을 (What)**: 14개 지표 가중치 강제 정규화 로직 취소 및 적정가(f_target) 계산 공식 롤백
* **왜 (Why)**: 가중치를 강제로 비례 축소하고 목표주가 연동 공식을 임의 변경한 결과, 적정가 대비 과도한 갭이 발생하여 종합 점수가 비정상적으로 튀는 왜곡 현상이 감지되었기 때문
* **어떻게 (How)**: 클로드가 최초 설계했던 안정적인 계산 공식(Target PER 10.4 고정 배수) 및 100점 합산 가중치 정수로 완벽하게 롤백(Revert)하여 점수 정합성을 복구함
""",
    ),
    (
        '📄 v1.2.0 (더미 제거 시도)',
        """\
#### 🏷️ [v1.2.0] - 2026년 08월 02일 (더미 데이터 제거 및 관리자 제어실 연동)
* **언제 (When)**: 2026년 08월 02일 정오 기정 적용
* **누가 (Who)**: **보이는 손 분석팀**
* **어디를 (Where)**: app.py / scrape_daily.py / test_harness.py
* **무엇을 (What)**: 시세/수급 수집 실패 시의 임의 디폴트값(2500, 1350) 및 5일 이동평균 대입 로직 삭제 (클린 데이터 전용 Reject 문 연동) 및 관리자 수동 제어실 탑재
* **왜 (Why)**: 비영업일 또는 크롤링 장애 시 자동 누적되는 가짜 더미 데이터로 인한 DB 점수 오염을 원천 차단하기 위함
* **어떻게 (How)**: 데이터 수집 불량 시 수정을 자동으로 차단하고, 관리자 비밀번호 로그인 시 직접 검증된 당일 종가/환율/수급을 대시보드 인터페이스에서 즉시 반영할 수 있도록 UI/UX 통합 제어실 설계 완료
""",
    ),
    (
        '📄 v1.0.0 (최초 배포)',
        """\
#### 🏷️ [v1.0.0] - 2026년 08월 01일 (최초 배포 버전)
* **언제 (When)**: 2026년 08월 01일 장마감 시점 기정 적용
* **누가 (Who)**: 보이는 손 퀀트 모델링 분석팀 (AI 젬민이 설계 파트)
* **어디를 (Where)**: 13가지 하위 리스크 공식 내 기초 매개변수 전체 적용
* **무엇을 (What)**: 
    * 환율 기초 스트레스 범위: 분모 `300원` 적용 (`(환율 - 1200) / 300`)
    * 코스피 역사적 고점 대비 낙인 임계식 설정
    * 3대 주체 수급 기여 가중치 분배: 외국인 55% / 기관 37% / 개인 8% 배정
* **왜 (Why)**: 2026년 상반기 원/달러 환율의 1,300원대 안착화 및 코스피 박스권 변동성 체계를 정규 모델링에 반영하기 위함
* **어떻게 (How)**: 백테스팅 모의 운용 결과, 시장 왜곡을 가장 예민하게 감지할 수 있는 균형 가중 평균치로 공식화하여 소스코드 적용 완료
""",
    ),
)

# =============================================================================
# 1. 데이터 계층 — views/macro_view.py 의 계산을 **그대로** 옮긴 것
#    (수식·상수·분기 순서 전부 원본과 동일. 바뀐 건 utils/db.py 에 콜백을 넘기는 것뿐입니다.)
# =============================================================================

def _today_kst():
    """UTC로 도는 서버에서도 KST 기준 '오늘'을 반환합니다(2026-08-06, 데이터 정합성 감사)."""
    return datetime.now(KST).date() if KST else datetime.today().date()


def _load_history_df():
    """읽기 전용으로 누적 이력 CSV 를 로드합니다 (실패 시 빈 DataFrame)."""
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(HISTORY_FILE)
        df = df.rename(columns={v: k for k, v in COL_MAP.items()})
        df["Date"] = df["Date"].astype(str)
        return df
    except Exception as e:
        print(f"Error loading local history: {e}")
        return pd.DataFrame()


def fetch_verified_market_data(override_date=None, override_kospi=None, override_usd=None,
                               override_retail=None, override_fore=None, override_inst=None,
                               is_admin_call=False, on_admin_note=None, on_warning=None, on_error=None):
    """
    누적 이력(market_history.csv) 또는 관리자 수동 입력값으로 시장 위험 지표를 산출합니다.

    ⚠️ ENGINEERING_SPEC §0-1 준수:
       실데이터를 불러오지 못하면 KOSPI 2500 / 환율 1350 같은 가짜 시세를 만들지 않고
       score=None 을 반환합니다. 호출부(`_render_dashboard`)는 이 경우 숫자를 전혀 그리지 않고
       빨간 오류 배너만 표시합니다.

    2026-08-17 (NiceGUI 이전 6단계) — 계산은 원본 그대로이고, 아래 4개 인자만 새로 받습니다.
    `utils/db.py` 가 더 이상 streamlit 으로 직접 화면을 그리지 않기 때문에(§0-3-8: 전역에서
    "지금 관리자인가"를 추측하지 않음), 저장 중 발생한 경고·실패를 화면까지 전달할 통로가
    필요합니다. 콜백을 안 넘기면 `logging` 으로만 남습니다.
      :param is_admin_call: 관리자 화면에서 부른 호출인지 (진행 메모 표시 여부)
      :param on_admin_note: 관리자용 진행 메모 콜백
      :param on_warning: 수급 결손 보정 실패 등 경고 콜백
      :param on_error: 이력 파일 읽기/쓰기 실패 콜백 (§0-1 — 반드시 화면까지)
    """
    row = None
    # (2026-08-10 #72: volatility / dist_from_high 선언 제거 — 이 두 값을 쓰던 공매도 2개
    #  지표가 점수에서 빠져 참조하는 코드가 남지 않았습니다. scrape_daily.py 와 동일한 정리.)
    unavailable_metrics = [] # 데이터가 없어 산출하지 못한 지표 목록

    if override_date is not None:
        date_key = override_date
        display_date = datetime.strptime(override_date, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
        local_loaded = False
        is_live_connected = True
        kospi_close = override_kospi
        usd_close = override_usd
        retail_flow = override_retail
        foreigner_flow = override_fore
        institution_flow = override_inst
        kospi_change = 0.0
        usd_change = 0.0
        score = None
        # 관리자는 KOSPI·환율·수급만 입력하므로 KRX 실측 기반 지표(VKOSPI·선물 베이시스)는
        # 산출할 수 없습니다. (2026-08-10 #72: 예전엔 '변동성/고점대비낙폭 미입력'이라고 적혀
        # 있었는데, 그 두 값을 쓰던 공매도 2개 지표가 사라져 더 이상 맞는 설명이 아닙니다.)
        data_source_log = "⚠️ 관리자 수동 입력 (KRX 실측 지표 미입력 → 해당 지표 제외)"

        if not kospi_close or not usd_close or kospi_close <= 0 or usd_close <= 0:
            return (
                display_date, False,
                "🚨 관리자 입력값이 유효하지 않습니다 (KOSPI 종가·환율은 필수).",
                None, [], _load_history_df()
            )
    else:
        local_loaded = False
        kospi_close = None
        kospi_change = 0.0
        usd_close = None
        usd_change = 0.0
        foreigner_flow = 0
        institution_flow = 0
        retail_flow = 0
        score = None

        target_date = _today_kst()
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
        date_key = target_date.strftime("%Y-%m-%d")
        display_date = target_date.strftime("%Y년 %m월 %d일")
        
        if os.path.exists(HISTORY_FILE):
            try:
                history_df = pd.read_csv(HISTORY_FILE)
                if not history_df.empty:
                    history_df = history_df.rename(columns={v: k for k, v in COL_MAP.items()})
                    history_df["Date"] = history_df["Date"].astype(str)
                    df_sorted = history_df.sort_values(by="Date").reset_index(drop=True)
                    
                    # 항상 가장 최근에 마감된 영업일 데이터(마지막 행)를 DataFrame(1줄)으로 불러옵니다.
                    row = df_sorted.tail(1)
                    latest_row = row.iloc[0]
                    
                    date_key = str(latest_row["Date"])
                    display_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%Y년 %m월 %d일")
                    
                    score = float(latest_row["Score"])
                    kospi_close = float(latest_row["KOSPI"])
                    usd_close = float(latest_row["USD_KRW"])
                    retail_flow = int(latest_row["Retail"])
                    foreigner_flow = int(latest_row["Foreigner"])
                    institution_flow = int(latest_row["Institution"])
                    
                    idx = df_sorted.index[-1]
                    if idx > 0:
                        prev_row = df_sorted.iloc[idx - 1]
                        prev_k = float(prev_row["KOSPI"])
                        prev_u = float(prev_row["USD_KRW"])
                        if prev_k != 0:
                            kospi_change = (kospi_close - prev_k) / prev_k
                        if prev_u != 0:
                            usd_change = (usd_close - prev_u) / prev_u
                    
                    local_loaded = True
            except Exception as e:
                print(f"Error loading local history: {e}")

        is_live_connected = False
        if local_loaded:
            # "마지막 동기화" 표시는 파일 mtime(배포·재시작 시각과 뒤섞일 수 있음)이 아니라
            # 실제로 크롤링이 끝나 이 행이 저장된 시각(Collected_At)을 사용합니다.
            # (views/pegy_view.py의 "마지막 동기화" 표기와 동일한 기준으로 통일 — 2026-08-06)
            collected_at = latest_row.get("Collected_At") if "Collected_At" in df_sorted.columns else None
            if collected_at is not None and pd.notna(collected_at):
                data_source_log = f"📅 마지막 동기화: {collected_at} (크롤링 완료 후 장마감 데이터 적용)"
            else:
                data_source_log = "✅ 마감 데이터 기준 (수집 완료 시각 기록 없음 — 구버전 데이터)"
        else:
            # 🚨 실데이터 없음 → 가짜 시세(2500/1350)로 점수를 만들지 않고 실패를 그대로 반환
            return (
                display_date, False,
                "🚨 시장 데이터를 불러오지 못했습니다 (market_history.csv 없음 또는 손상). 수치를 표시하지 않습니다.",
                None, [], _load_history_df()
            )

    # =====================================================================
    # 지표 산출 — 입력이 없는 지표는 '중립값 0.5'를 넣지 않고 산출 대상에서 제외합니다.
    # =====================================================================
    # 2026-08-10 (#69): 실측 경로가 없다고 판정된 6개 지표(ELS 낙인 / 야간 역외환율 /
    # 선물 순매도 / 비차익 프로그램 / 외국계 증권사 매도세 / 풋옵션 매수 강도)의 계산식을
    # scrape_daily.py와 **동시에** 제거했습니다. 두 파일의 산식이 갈라지면 화면 미리보기와
    # 실제 저장값이 또 어긋나므로, 이 블록은 항상 scrape_daily.py "4. 리스크 지표 연산"과
    # 1:1로 같아야 합니다. 이 지표들의 설명은 아래 "📚 공부용 참고" 섹션에만 남습니다.
    #
    # 2026-08-10 (#70): `VKOSPI_Skew`/`Synthetic_Futures` 의 임의 선형식을 scrape_daily.py와
    # **동시에** 제거했습니다. 두 지표는 이제 KRX OPEN API 실측값(VKOSPI 지수 / 선물 베이시스)
    # 으로만 산출되는데, 이 화면의 이 분기는 "아직 수집 전 미리보기"라 그 실측값이 없습니다.
    # ⚠️ 여기서 Streamlit 렌더링 중에 KRX API를 호출하지는 않습니다 — 화면을 새로고침할 때마다
    #    외부 API를 두드리는 건 크롤링 매너(§0-3-2)에도, 인증키 관리에도 맞지 않습니다.
    #    대신 두 지표를 '산출 불가(None)'로 두어 기존 unavailable_metrics 경로로 빠지게 합니다.
    #    (예전처럼 환율·변동성으로 대체 계산하면 그게 바로 §0-3-1이 금지한 프록시입니다.)
    #
    # 2026-08-10 (#72): 공매도 2종(`Short_Ratio`/`Stock_Short_Balance`)의 계산식도
    # scrape_daily.py와 **동시에** 제거했습니다. 사유는 앞의 6개와 다릅니다 — 데이터가 없는 게
    # 아니라, 유일한 무료 경로(pykrx)가 data.krx.co.kr 로그인 우회라서 §0-3-2 원칙상 쓰지 않기로
    # 오너가 결정(옵션②)했습니다. 두 지표의 설명은 위 STUDY_ONLY_INDICATORS 로 이동했습니다.
    fx_base = 0.5 + 0.3 * (usd_close - 1200) / 300
    put_base = 0.5 - 0.4 * kospi_change

    # =====================================================================
    # 실측 지표 2종 (2026-08-10 #68) — 임의 상수(0.5 ± 0.3, 계수 2.5) 제거
    # =====================================================================
    # 이 두 지표는 추정 프록시가 아니라 실제로 측정된 값(3주체 순매수 금액 / 코스피 5일
    # 수익률)입니다. scrape_daily.py와 똑같은 utils/macro_scoring 함수를 호출해, 원값을
    # 과거 분포 대비 z-score로 정규화한 뒤 ±3σ를 0~1 위험도로 매핑합니다.
    # 과거 표본이 부족하면 값을 지어내지 않고 중립(0.5)으로 안전 대체됩니다.
    _hist_for_measured = _load_history_df()
    try:
        if not _hist_for_measured.empty and "Date" in _hist_for_measured.columns:
            # 정규화 기준선은 '과거' 표본이어야 하므로 지금 계산 중인 날짜 행은 제외합니다.
            _past_rows = _hist_for_measured[_hist_for_measured["Date"] != str(date_key)]
        else:
            _past_rows = _hist_for_measured
    except Exception:
        _past_rows = _hist_for_measured

    stock_net_risks = {
        "Foreigner": measured_downside_risk(foreigner_flow, net_flow_population(_past_rows, "Foreigner")),
        "Institution": measured_downside_risk(institution_flow, net_flow_population(_past_rows, "Institution")),
        "Retail": measured_downside_risk(retail_flow, net_flow_population(_past_rows, "Retail")),
    }

    # KOSPI 5일 수익률: 누적 이력에서 5영업일 전 종가를 실제로 조회해 산출합니다.
    # (과거 버전은 정의되지 않은 변수 kospi_df 를 참조해 항상 NameError → 0.5 고정이었습니다.)
    kospi_5d_base = None
    try:
        hist_for_5d = _hist_for_measured
        if not hist_for_5d.empty and "KOSPI" in hist_for_5d.columns:
            hist_sorted = hist_for_5d.sort_values(by="Date").reset_index(drop=True)
            past = hist_sorted[hist_sorted["Date"] <= str(date_key)]
            if len(past) >= 6:
                k_5d_prev = float(past.iloc[-6]["KOSPI"])
                if k_5d_prev > 0:
                    kospi_5d_base = measured_downside_risk(
                        (kospi_close - k_5d_prev) / k_5d_prev,
                        rolling_return_population(list(past["KOSPI"])),
                    )
    except Exception as e:
        print(f"⚠️ KOSPI 5일 수익률 산출 실패: {e}")
        kospi_5d_base = None

    # 2026-08-06 2차 감사 5-1: scrape_daily.py가 실제로 쓰는 것과 같은 단일 출처를 참조합니다
    # (예전엔 여기 가중치가 scrape_daily.py와 서로 달라, 화면 표의 기여점수 합이 실제 종합점수와
    # 맞지 않았습니다).
    weights = dict(RISK_WEIGHTS)

    # (중복 정의였던 friendly_names 사전 제거 — 표기는 모듈 상단 FRIENDLY_NAMES 로 일원화)

    formulas = {
        "FX_Swap_Point": "0.55 × clip(0.5 + 0.3×(USD-1200)/300 + 0.1×USD_change) + 0.37 × clip(base) + 0.08 × clip(base - 0.2)",
        "Put_OTM_OI": "0.55 × clip(0.5 - 0.4×KOSPI_change + Fore_Sign) + 0.37 × clip(base + Inst_Sign) + 0.08 × clip(base + Ret_Sign)",
        # (2026-08-10 #72: `Short_Ratio`/`Stock_Short_Balance` 산식 제거 — 점수에서 빠지고
        #  "📚 공부용 참고" 섹션으로 이동했습니다.)
        # ✅ 실측 2종 추가 (2026-08-10 #70, KRX OPEN API — 추정 프록시 아님)
        "VKOSPI_Skew": "실측: KRX 파생상품지수 API의 VKOSPI(코스피200 변동성지수) 종가를 "
                       "누적 이력 대비 z-score → ±3σ를 0~1로 윈저라이즈 (값이 **높을수록** 위험). "
                       "3주체 동일값(시장 전체가 매기는 하나의 값이라 주체별로 다를 수 없음). "
                       "표본 20행 미만이면 중립 0.5",
        "Synthetic_Futures": "실측: (KOSPI200 선물 근월물 종가 − KOSPI200 지수 종가) = 베이시스를 "
                             "누적 이력 대비 z-score → ±3σ를 0~1로 윈저라이즈 "
                             "(값이 **낮을수록**=백워데이션일수록 위험). 3주체 동일값. "
                             "표본 20행 미만이면 중립 0.5",
        # ✅ 실측 2종 (추정 프록시 아님 — 실제 측정값을 과거 분포 대비 정규화)
        "Stock_Net_Sell": "실측: 주체별 순매수 금액(억원)을 과거 이력 대비 z-score → ±3σ를 0~1로 윈저라이즈 "
                          "(0.55×외국인 + 0.37×기관 + 0.08×개인, 표본 20행 미만이면 중립 0.5)",
        "KOSPI_5D_Return": "실측: (종가 - 5영업일 전 종가)/5영업일 전 종가 를 과거 1년 5일수익률 분포 대비 "
                           "z-score → ±3σ를 0~1로 윈저라이즈 (표본 부족 시 중립 0.5)"
    }

    sub_scores = {}
    extreme_signal_count = 0
    investor_weights = dict(INVESTOR_WEIGHTS)
    data_source_log_suffix = ""

    if not local_loaded:
        def clip(val):
            return min(1.0, max(0.0, val))

        # 입력이 없는(None) 지표는 아래에서 통째로 제거되어 가중평균에서 제외됩니다.
        market_scores_raw = {
            "FX_Swap_Point": {"Foreigner": clip(fx_base + 0.1 * usd_change), "Institution": clip(fx_base), "Retail": clip(fx_base - 0.2)},
            "Put_OTM_OI": {"Foreigner": clip(put_base + (0.1 if foreigner_flow < 0 else -0.1)), "Institution": clip(put_base + (0.05 if institution_flow < 0 else -0.05)), "Retail": clip(put_base + (0.15 if retail_flow > 0 else -0.1))},
            # (2026-08-10 #72: "Short_Ratio" 항목 제거 — 공부용 참고 섹션으로 이동)
            # 2026-08-10 (#70): 이 둘은 KRX OPEN API 실측 전용이 되었고, 미리보기 분기에는
            # 그 값이 없습니다. 프록시로 채우지 않고 산출 불가로 둡니다(§0-1).
            "VKOSPI_Skew": None,
            "Synthetic_Futures": None,
            # (2026-08-10 #72: "Stock_Short_Balance" 항목 제거 — 공부용 참고 섹션으로 이동)
            "Stock_Net_Sell": None if any(v is None for v in stock_net_risks.values()) else {"Foreigner": clip(stock_net_risks["Foreigner"]), "Institution": clip(stock_net_risks["Institution"]), "Retail": clip(stock_net_risks["Retail"])},
            "KOSPI_5D_Return": None if kospi_5d_base is None else {"Foreigner": clip(kospi_5d_base), "Institution": clip(kospi_5d_base), "Retail": clip(kospi_5d_base)}
        }

        market_scores = {k: v for k, v in market_scores_raw.items() if v is not None}
        unavailable_metrics = [k for k, v in market_scores_raw.items() if v is None]

        current_weighted_risks = {}
        for item, risks in market_scores.items():
            current_weighted_risks[item] = (
                (risks["Foreigner"] * investor_weights["Foreigner"])
                + (risks["Institution"] * investor_weights["Institution"])
                + (risks["Retail"] * investor_weights["Retail"])
            )

        if not current_weighted_risks:
            return (
                display_date, False,
                "🚨 산출 가능한 위험 지표가 하나도 없습니다. 종합 위험 점수를 표시하지 않습니다.",
                None, [], _load_history_df()
            )

        # 2026-08-06 2차 감사 5-2: 예전엔 이 "미리보기" 분기가 가중위험(0~1)을 단순히 ×100 한
        # 값을 서브점수로 썼는데, 실제 scrape_daily.py는 과거 이력 대비 z-score+시그모이드
        # 변환을 씁니다 — 척도가 달라 미리보기 점수가 실제 저장될 점수와 다르게 보였습니다.
        # scrape_daily.py와 동일한 함수를 호출해 척도를 맞춥니다(이 분기는 "아직 수집 전"이라
        # 재계산 자체는 불가피하지만, 최소한 같은 산식을 씁니다).
        active_weights = {k: weights[k] for k in current_weighted_risks if k in weights}
        historical_stats = compute_historical_stats(_load_history_df(), active_weights.keys())
        computed_sub_scores = compute_sub_scores(current_weighted_risks, historical_stats)
        sub_scores = {k: computed_sub_scores.get(k) for k in weights}
        score, base_score, multiplier, extreme_signal_count, _ = compute_final_score(computed_sub_scores, active_weights)
    else:
        # 2026-08-06 2차 감사 5-2: 그날 실제로 저장된 SubScore_*/Multiplier를 그대로 읽습니다
        # (재계산 시 그날의 historical_stats를 지금 재현할 수 없어 실제 점수와 달라질 수 있음).
        has_stored_subscores = row is not None and any(f"SubScore_{k}" in row.columns for k in weights)
        for item, w in weights.items():
            col = f"SubScore_{item}"
            val = None
            if has_stored_subscores and row is not None and col in row.columns:
                try:
                    raw_val = row.iloc[0][col]
                    val = None if pd.isna(raw_val) else float(raw_val)
                except (TypeError, ValueError):
                    val = None
            elif row is not None and item in row.columns:
                # 구버전 행(SubScore_* 컬럼 도입 이전) — 원시 가중위험만 있어 선형 근사로
                # 대체합니다. 실제 그날 점수(시그모이드 변환)와 정확히 일치하지 않을 수 있어
                # unavailable_metrics 목록과 별개로 근사치임을 화면에 알릴 필요가 있습니다.
                try:
                    raw_val = row.iloc[0][item]
                    raw = None if pd.isna(raw_val) else float(raw_val)
                    val = None if raw is None else round(raw * 100.0, 1)
                except (TypeError, ValueError):
                    val = None

            sub_scores[item] = val
            if val is None:
                unavailable_metrics.append(item)
            elif val >= EXTREME_SUB_SCORE_HIGH or val <= EXTREME_SUB_SCORE_LOW:
                extreme_signal_count += 1
        try:
            score = float(row.iloc[0]["Score"])
        except (TypeError, ValueError, KeyError):
            score = None

        if not has_stored_subscores and row is not None:
            data_source_log_suffix = " | ⚠️ 구버전 데이터(지표별 세부점수는 근사치)"
        else:
            data_source_log_suffix = ""

    details = []
    for item, w in weights.items():
        sub_score_val = sub_scores.get(item)
        display_risk = None if sub_score_val is None else round(sub_score_val / 100.0, 3)
        details.append({
            "지표명 (한글 설명)": FRIENDLY_NAMES.get(item, item),
            "중요도 (가중치)": w,
            "위험도 (0~1)": display_risk,
            "기여점수": None if display_risk is None else round(w * display_risk, 2),
            "산출 공식 (수학적 모델)": formulas.get(item, "")
        })

    details = sorted(details, key=lambda x: x["중요도 (가중치)"], reverse=True)

    metrics_dict = {}
    for item in weights.keys():
        if sub_scores.get(item) is not None:
            metrics_dict[item] = sub_scores[item] / 100.0
    # 산출하지 못한 지표는 metrics_dict 에 넣지 않습니다 → CSV 에도 값이 기록되지 않음(결측 유지)

    # SPEC §6: 표현 계층(조회 화면)은 DB를 쓰지 않습니다.
    # 관리자 수동 입력(override) 으로 새 데이터가 들어온 경우에만 저장합니다.
    if override_date is not None:
        history_df = save_and_load_history(
            date_key, score, kospi_close, usd_close, retail_flow, foreigner_flow, institution_flow,
            metrics_dict,
            is_admin=is_admin_call, on_admin_note=on_admin_note,
            on_warning=on_warning, on_error=on_error,
        )
    else:
        history_df = _load_history_df()

    if local_loaded:
        is_live_connected = True

    if unavailable_metrics:
        data_source_log += f" | ⚠️ 산출 불가 지표 {len(unavailable_metrics)}개 (가중평균에서 제외)"
    data_source_log += data_source_log_suffix

    status_text = f"KOSPI: {kospi_close:.2f} ({kospi_change*100:+.2f}%) | 환율: {usd_close:.2f}원 ({usd_change*100:+.2f}%)"
    return display_date, is_live_connected, f"{data_source_log} | {status_text}", score, details, history_df


# =============================================================================
# 2. 화면 조각
# =============================================================================
def _html(markup: str) -> None:
    """원본의 `render_clean_html()` 대체 — 줄 앞뒤 공백을 걷어내고 그대로 그립니다."""
    ui.html(compact(markup)).classes('w-full')


def _render_study_only_section() -> None:
    """
    📚 "지금은 점수에 넣지 않는 지표" 공부용 안내 섹션 (2026-08-10 #69).

    ⚠️ 이 함수는 **어떤 값도 계산하지 않습니다.** 모듈 상단의 STUDY_ONLY_INDICATORS /
       DROPPED_AS_DUPLICATE 설명 텍스트를 그대로 렌더링할 뿐입니다. 데이터가 없는 지표에
       예시 숫자를 그럴듯하게 그려 넣으면 그 자체가 §0-1 위반이라, 화면에는 '무엇이 없는지'와
       '어디서 공부하면 되는지'만 적습니다.
    """
    active_weights = sorted(RISK_WEIGHTS.values())
    w_min, w_max = active_weights[0], active_weights[-1]

    with ui.expansion('📚 공부용 참고 — 지금은 다루지 않는 지표 (직접 공부해보고 싶다면)').classes('w-full'):
        banner('info',
               'ℹ️ <b>아래 지표들은 이 화면의 점수에서 다루지 않고 있습니다.</b> '
               "예전에는 점수에 들어가 있었지만, 실제로는 실측 데이터 없이 '코스피 등락률·환율·수급 부호·변동성'을 "
               '그럴듯한 이름으로 바꿔 부르는 수준이어서 2026-08-10에 빼냈습니다.<br><br>'
               '<b>빼낸 이유는 두 종류입니다.</b> ① 앞의 4개는 무료로 구할 수 있는 데이터 자체가 없습니다. '
               '② 마지막 2개(공매도 거래 비중 · 공매도 잔고)는 <b>데이터는 존재하지만</b>, 그것을 받아올 수 있는 '
               '유일한 무료 경로가 로그인 우회 방식이라 이 프로젝트의 크롤링 원칙상 쓰지 않기로 했습니다. '
               "각 항목의 '② 지금 왜 못 다루나요?'에 어느 쪽인지 그대로 적어두었습니다.<br><br>"
               '지우지 않고 여기 남겨두는 이유는, <b>개인적으로 공부해보고 싶은 분이 어디서부터 찾아보면 되는지</b> '
               '알 수 있게 하기 위해서입니다. 전부 실제 금융시장에서 통용되는 개념이라 알아두면 시장 기사를 '
               '읽을 때 확실히 도움이 됩니다.')

        for item in STUDY_ONLY_INDICATORS:
            study_list_html = "".join(
                f'<li style="margin-bottom:6px;">{esc(s)}</li>' for s in item["how_to_study"]
            )
            card_html = f"""
            <div style="background: linear-gradient(135deg, #0f172a, #1e293b); border: 1.5px solid #334155;
                        border-left: 5px solid #38bdf8; border-radius: 12px; padding: 18px 20px;
                        margin-bottom: 16px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 17px; font-weight: 800; color: #f1f5f9; margin-bottom: 6px;">
                    📕 {esc(item['title'])}
                    <span style="font-size: 12px; color: #64748b; font-weight: 600;">({esc(item['key'])})</span>
                </div>
                <div style="font-size: 14.5px; color: #cbd5e1; line-height: 1.6; margin-bottom: 14px;">
                    {esc(item['one_liner'])}
                </div>

                <div style="font-size: 13.5px; font-weight: 700; color: #38bdf8; margin-bottom: 4px;">
                    ① 왜 시장에서 중요하게 보나요?
                </div>
                <div style="font-size: 14px; color: #e2e8f0; line-height: 1.65; margin-bottom: 14px;">
                    {esc(item['why_it_matters'])}
                </div>

                <div style="font-size: 13.5px; font-weight: 700; color: #fbbf24; margin-bottom: 4px;">
                    ② 지금 왜 못 다루나요? (부족한 데이터)
                </div>
                <div style="font-size: 14px; color: #e2e8f0; line-height: 1.65; margin-bottom: 14px;">
                    {esc(item['missing_data'])}
                </div>

                <div style="font-size: 13.5px; font-weight: 700; color: #86efac; margin-bottom: 4px;">
                    ③ 어떻게 공부하면 좋을까요?
                </div>
                <ul style="font-size: 14px; color: #e2e8f0; line-height: 1.6; margin: 0 0 14px 0; padding-left: 20px;">
                    {study_list_html}
                </ul>

                <div style="background-color: rgba(56, 189, 248, 0.08); border: 1px dashed #38bdf8;
                            border-radius: 8px; padding: 12px 14px;">
                    <div style="font-size: 13.5px; font-weight: 700; color: #7dd3fc; margin-bottom: 4px;">
                        ④ 만약 데이터를 구할 수 있다면 가중치는? — {esc(item['hypothetical_weight'])}
                    </div>
                    <div style="font-size: 13.5px; color: #cbd5e1; line-height: 1.6;">
                        {esc(item['weight_reasoning'])}
                    </div>
                    <div style="font-size: 12.5px; color: #94a3b8; margin-top: 6px;">
                        ⚠️ 이 숫자는 <b>확정 가중치가 아니라 참고 범위</b>입니다. 실제 데이터를 받아보기 전에는
                        정확한 값을 정할 수 없어서, 지금 살아있는 지표들의 분포({w_min:.2f}~{w_max:.2f})에 비춰
                        "대략 이 정도가 합리적일 것"이라고만 적었습니다. 실제 점수 계산에는 들어가지 않습니다.
                    </div>
                </div>
            </div>
            """
            _html(card_html)

        dropped_html = "".join(
            f'<li style="margin-bottom:10px; line-height:1.6;"><b style="color:#fca5a5;">{esc(name)}</b><br>'
            f'<span style="color:#cbd5e1;">{esc(reason)}</span></li>'
            for name, reason in DROPPED_AS_DUPLICATE
        )
        _html(
            f"""
            <div style="background-color: #1e293b; border: 1.5px solid #7f1d1d; border-radius: 12px;
                        padding: 18px 20px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15.5px; font-weight: 800; color: #fecaca; margin-bottom: 8px;">
                    🗑️ 공부 목록에도 넣지 않고 완전히 뺀 지표 2개
                </div>
                <div style="font-size: 13.5px; color: #94a3b8; margin-bottom: 12px; line-height: 1.6;">
                    아래 2개는 데이터가 없어서가 아니라, <b>이미 쓰고 있는 다른 지표와 같은 것을 두 번 세고
                    있었기 때문에</b> 뺐습니다. 지표가 조용히 사라지면 그것도 정직한 표시가 아니라서 이유를
                    남겨둡니다.
                </div>
                <ul style="font-size: 14px; margin: 0; padding-left: 20px;">{dropped_html}</ul>
            </div>
            """
        )

        ui.markdown(
            '출처 조사 근거: `MACRO_REDESIGN_PROPOSAL.md` §2 판정표 · §2-1 출처 링크 (2026-08-09 조사). '
            'KRX 정보데이터시스템은 2025-12-27부터 로그인이 필요하고, 무료 KRX OPEN API에는 공매도·'
            '투자자별 파생상품·프로그램매매 통계가 제공되지 않습니다. '
            '공매도 2종은 로그인을 우회하는 외부 라이브러리로는 받아올 수 있지만, 그 방식은 '
            '쓰지 않기로 했습니다(ENGINEERING_SPEC §0-3-2, 2026-08-10 결정).'
        ).classes('vh-muted')


def _render_admin_console() -> None:
    """관리자 전용 데이터 수동 제어실 (`views/admin_view.py::render_admin_console` 이식본).

    원본에서도 이 콘솔은 **매크로 화면 안에서** 그려졌으므로(`render_macro_page` 가
    `render_admin_console()` 을 호출) 같은 자리에 그대로 뒀습니다.

    Streamlit 의 `st.form` → NiceGUI 에서는 카드 + 버튼입니다(계획서 부록 A). 위젯 키
    함정(#85/#114)이 없어져 `key=` 인자가 통째로 사라졌고, 입력값은 이 함수의 **지역
    변수(위젯 객체)** 로만 존재합니다 — 모듈 전역에 두지 않습니다(§0-3-8).
    """
    # ⚠️ 2026-08-17 — 서버 **절대경로** 노출을 걷어냈습니다(`web/pages/admin_page.py` 와 동일한
    #    이유·표기). 관리자 전용이라 위험도는 낮지만 화면에 서버 내부 디렉터리 구조를 그릴
    #    이유가 없고(§0-3-4), 여기서 실제로 알고 싶은 건 "그 파일이 있느냐"뿐입니다.
    banner('info',
           f'⚙️ [관리자 시스템 정보]<br>· <b>누적 이력 파일:</b> {esc(os.path.basename(HISTORY_FILE))}'
           ' (저장소 루트)'
           f'<br>· <b>파일 존재 여부:</b> {esc("있음" if os.path.exists(HISTORY_FILE) else "없음")}')

    with ui.expansion('🛠️ 관리자 전용 데이터 수동 제어실 (비상 입력 및 가이드)', value=True).classes('w-full'):
        ui.markdown(
            """
### 📌 데이터 수동 입력 가이드 및 출처 안내
자동 수집 지연/장애 시, 아래 출처 사이트에서 당일 최종 확정 데이터를 확인하여 오타 없이 기입해 주십시오.

* **영업일 선택**: 보정 또는 신규 입력할 타겟 일자를 선택합니다.
* **KOSPI 종가 (pt)**: 소수점 이하 2자리까지 입력합니다.
  * *출처*: [네이버 증권 코스피 페이지](https://finance.naver.com/sise/sise_index.naver?code=KOSPI)
* **원/달러 환율 (원)**: 소수점 이하 2자리까지 입력합니다.
  * *출처*: [네이버 페이 증권 시장지표](https://finance.naver.com/marketindex/)
* **수급 데이터 (개인/외국인/기관)**: 억원 단위로 입력합니다.
  * *출처*: [네이버 증권 투자자별 매매동향](https://finance.naver.com/sise/investorDealTrendDay.naver) 당일 첫 번째 행 수치
            """
        )

        with ui.card().classes('vh-card w-full'):
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('gap-2').style('flex: 1 1 260px; min-width: 0;'):
                    # `st.date_input` → 브라우저 기본 날짜 입력 (사장님 보고서와 같은 방식, §0-3-10)
                    m_date = ui.input('영업일 선택', value=_today_kst().isoformat()) \
                        .props('type=date stack-label').classes('w-full')
                    # 기본값 2500 / 1350 을 넣어두면 실수로 그대로 제출되어 가짜 시세가 저장됩니다.
                    m_kospi = ui.number('KOSPI 종가 (pt) *필수', value=0.0, min=0.0, step=0.1).classes('w-full')
                    m_retail = ui.number('개인 수급 (억원)', value=0, step=10).classes('w-full')
                with ui.column().classes('gap-2').style('flex: 1 1 260px; min-width: 0;'):
                    m_usd = ui.number('원/달러 환율 (원) *필수', value=0.0, min=0.0, step=0.1).classes('w-full')
                    m_fore = ui.number('외국인 수급 (억원)', value=0, step=10).classes('w-full')
                    m_inst = ui.number('기관 수급 (억원)', value=0, step=10).classes('w-full')

            # 저장 중 발생한 경고·실패는 **화면에 계속 남는 배너**로 표시합니다 (§0-1 — 토스트로
            # 흘려보내면 "실패 사실이 화면까지 도달"했다고 볼 수 없습니다).
            result_box = ui.column().classes('w-full')

            def _number(widget, default=0.0):
                """비어 있는 입력은 0 으로 봅니다(원본 `st.number_input` 기본값과 동일)."""
                try:
                    return float(widget.value)
                except (TypeError, ValueError):
                    return default

            def _submit() -> None:
                result_box.clear()

                m_kospi_val = _number(m_kospi)
                m_usd_val = _number(m_usd)
                if m_kospi_val <= 0 or m_usd_val <= 0:
                    with result_box:
                        error_banner('🚫 KOSPI 종가와 원/달러 환율은 실제 조회한 값을 입력해야 저장됩니다. (0 저장 불가)')
                    return

                raw_date = (m_date.value or '').strip()
                try:
                    m_date_key = datetime.strptime(raw_date, '%Y-%m-%d').strftime('%Y-%m-%d')
                except ValueError:
                    with result_box:
                        error_banner('🚫 영업일을 YYYY-MM-DD 형식으로 선택해 주세요.')
                    return

                def _note(message):
                    with result_box:
                        info_banner(message)

                def _warn(message):
                    with result_box:
                        warning_banner(message)

                def _err(message):
                    with result_box:
                        error_banner(message)

                try:
                    _, _, save_log, save_score, _, _ = fetch_verified_market_data(
                        override_date=m_date_key,
                        override_kospi=m_kospi_val,
                        override_usd=m_usd_val,
                        override_retail=int(_number(m_retail)),
                        override_fore=int(_number(m_fore)),
                        override_inst=int(_number(m_inst)),
                        is_admin_call=True,
                        on_admin_note=_note,
                        on_warning=_warn,
                        on_error=_err,
                    )
                except Exception as exc:              # noqa: BLE001 — 화면엔 문장만, 상세는 로그로 (§0-3-4)
                    print(f'⚠️ 매크로 수동 입력 저장 실패: {type(exc).__name__}: {exc}')
                    with result_box:
                        error_banner('🚫 저장 중 문제가 발생해 아무것도 저장하지 않았습니다. 입력값을 확인한 뒤 다시 시도해 주세요.')
                    return

                if save_score is None:
                    # 원본과 동일 — 입력이 유효하지 않으면 저장하지 않고 사유를 그대로 보여줍니다(§0-1).
                    with result_box:
                        error_banner(save_log)
                    return

                # 원본은 `st.success(...)` 직후 `st.rerun()` 이라 메시지가 사실상 바로 사라졌습니다.
                # NiceGUI 에서도 같은 흐름(알림 후 화면 다시 그리기)을 유지합니다.
                ui.notify(f'🎉 {m_date_key} 데이터가 검증되어 성공적으로 저장되었습니다!', type='positive')
                ui.navigate.reload()

            ui.button('💾 클린 DB 수동 저장 및 대시보드 반영', on_click=_submit) \
                .props('no-caps').classes('mt-2')


def _render_indicator_table(details) -> None:
    """🔍 지표별 위험 기여도 상세 분석표 (원본 `st.expander` + HTML 표)."""
    # 지표 개수는 하드코딩하지 않고 실제 가중치 사전 길이를 씁니다
    # (2026-08-10 #69에서 14개 → 8개로 바뀌었고, 앞으로도 또 바뀔 수 있어 문구가 코드와
    #  어긋나지 않도록 단일 출처를 그대로 읽습니다).
    n_indicators = len(RISK_WEIGHTS)
    with ui.expansion(f'🔍 {n_indicators}개 변동성 지표별 위험 기여도 상세 분석표 보기').classes('w-full'):
        ui.markdown(f'#### 📊 {n_indicators}개 변동성 지표별 위험 기여도 및 산출 공식')
        ui.markdown('수급 가중치(외국인 55%, 기관 37%, 개인 8%)를 적용하여 산출된 개별 위험도 및 수학적 모델입니다.') \
            .classes('vh-muted')
        banner('info',
               f'ℹ️ <b>지표 산출 방식 안내</b> — 아래 {n_indicators}개 중 <b>2개</b>(외환 스왑포인트 · 풋옵션 미결제약정)는 '
               '실제 파생상품 시장에서 직접 수집한 값이 아니라, <b>KOSPI 종가 · 원/달러 환율 · 두 값의 전일 대비 '
               '변화율 · 투자자 3주체 수급</b> 실측값으로부터 위 \'산출 공식\'에 따라 계산한 <b>추정 프록시(대용치)</b> 입니다. '
               "<b>'실측' 표기가 붙은 4개</b>(KOSPI 5일 수익률 · 주식 현물 순매도 · VKOSPI · 선물 베이시스)는 "
               '실제 측정값을 과거 분포 대비 정규화한 값입니다. '
               "'데이터 없음'으로 표시된 지표는 입력값이 없어 산출하지 못한 것이며, 종합 점수의 가중평균에서도 제외됩니다."
               "<br><br>2026-08-10부터, 실측 경로가 아예 없어 '이름만 파생상품'이던 6개 지표와, 공매도 2개 지표"
               '(데이터는 있지만 유일한 무료 경로가 로그인 우회라 원칙상 쓰지 않기로 함)를 점수 계산에서 '
               "제외했습니다(아래 '📚 공부용 참고' 섹션에 이유와 공부법을 남겼습니다).")

        n_missing = len([d for d in details if d["위험도 (0~1)"] is None])
        if n_missing:
            warning_banner(f"⚠️ {n_indicators}개 중 {n_missing}개 지표를 산출하지 못했습니다 (아래 표에 '데이터 없음'으로 표기).")

        if not details:
            info_banner('시장 데이터가 없습니다.')
            return

        rows_html = ''
        for row in details:
            name = row["지표명 (한글 설명)"]
            weight = row["중요도 (가중치)"]
            risk = row["위험도 (0~1)"]
            contrib = row["기여점수"]
            formula = row["산출 공식 (수학적 모델)"].replace("\n", "&#10;").replace("\\n", "&#10;")

            risk_str = "데이터 없음" if risk is None else f"{risk:.3f}"
            contrib_str = "산출 불가" if contrib is None else f"{contrib:.2f}"
            row_style = ' style="color:#94a3b8;"' if risk is None else ""
            missing_tag = ' <span style="color:#f97316;">(데이터 없음)</span>' if risk is None else ''

            rows_html += f"""
            <tr{row_style}>
                <td title="{esc(formula)}" style="cursor: help;">{esc(name)}{missing_tag}</td>
                <td>{weight:.2f}</td>
                <td>{risk_str}</td>
                <td>{contrib_str}</td>
            </tr>
            """

        # 원본은 iframe(고정 700px) → st.markdown 으로 이미 바뀌어 있었습니다(표가 잘려서).
        # 여기서는 좁은 화면에서 칸이 세로로 쌓이지 않도록 가로 스크롤 컨테이너에 담습니다(#127 결론).
        with ui.element('div').classes('w-full overflow-x-auto'):
            _html(f"""
            <table class="premium-table">
                <thead>
                    <tr>
                        <th style="width: 55%;">지표명 (한글 설명)<br><span style="font-size: 11px; color: #64748b; font-weight: normal;">[💡 마우스를 올려 공식을 확인하세요]</span></th>
                        <th style="width: 15%;">중요도<br>(가중치)</th>
                        <th style="width: 15%;">위험도<br>(0~1)</th>
                        <th style="width: 15%;">기여점수</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            """)


async def _render_ai_commentary(details, score) -> None:
    """🤖 지표별 AI 코멘트 + 종합 코멘트 (원본과 동일 — 값을 계산하지 않고 파일을 읽어 표시만).

    🔴 2026-08-21 — `async def` 로 바뀌었습니다. 그리는 내용은 그대로이고, 코멘트 파일을
       읽는 동안 이벤트 루프를 붙잡지 않습니다
       (이유는 `web/state.load_json_file_async` 주석 참고).
    """
    if not details:
        return

    sorted_details = sorted(details, key=lambda x: (x["위험도 (0~1)"] is not None, x["위험도 (0~1)"] or 0), reverse=True)

    ai_comments_data = {}
    ai_comment_dates = {}
    ai_commentary_file = data_path('macro_commentary.json')
    if os.path.exists(ai_commentary_file):
        payload, load_error = await load_json_file_async(ai_commentary_file)
        if load_error:
            # 🔴 원본은 `st.warning(f"...: {e}")` 로 **예외 원문을 화면에 그대로** 노출했습니다
            #    (§0-3-4 위반). 상세는 `load_json_file` 이 서버 로그로만 보냅니다.
            warning_banner('⚠️ AI 코멘트 파일을 읽지 못했습니다. 지표별 코멘트는 표시되지 않습니다.')
        else:
            ai_comments_data = (payload or {}).get("comments", {}) or {}
            ai_comment_dates = (payload or {}).get("comment_dates", {}) or {}

    today_str_kr = _today_kst().strftime("%Y-%m-%d")
    warning_items_html = ""
    for ind in sorted_details:
        raw_key = None
        for eng_k, kor_v in FRIENDLY_NAMES.items():
            if kor_v == ind["지표명 (한글 설명)"]:
                raw_key = eng_k
                break

        risk = ind["위험도 (0~1)"]
        # 🔐 §0-3-9 — 이 문자열은 **Gemini 가 생성해 파일에 저장한 외부 텍스트**입니다.
        #    원본은 그대로 HTML 에 넣고 있었습니다. esc() 를 거치면 글자 그대로 보입니다.
        w_text = esc(ai_comments_data.get(raw_key, "AI 코멘트가 준비되지 않았습니다."))

        # 오늘 생성된 코멘트가 아니면 '언제 것인지' 반드시 표시 (전일 코멘트를 오늘 것처럼 쓰지 않음)
        c_date = ai_comment_dates.get(raw_key)
        if raw_key in ai_comments_data:
            if c_date and c_date != today_str_kr:
                w_text = f"<span style='color:#fbbf24;'>⚠️ ({esc(c_date)} 생성 코멘트)</span> {w_text}"
            elif not c_date:
                w_text = f"<span style='color:#94a3b8;'>ℹ️ (생성 일자 미기록)</span> {w_text}"

        if risk is None:
            icon = "⚪"
            color = "#94a3b8"
            risk_label = "위험도: 데이터 없음 (산출 불가)"
        else:
            risk_label = f"위험도: {risk:.2f}"
            if risk >= 0.65:
                icon = "🔴"
                color = "#fca5a5"
            elif risk >= 0.35:
                icon = "🟡"
                color = "#fde047"
            else:
                icon = "🟢"
                color = "#86efac"

        warning_items_html += f'''
        <li style="margin-bottom: 12px; line-height: 1.5; list-style-type: none;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                <span style="font-size: 14px;">{icon}</span>
                <b style="color: {color}; font-size: 14.5px;">{esc(ind['지표명 (한글 설명)'])} ({risk_label})</b>
            </div>
            <div style="color: #cbd5e1; font-size: 13.5px; font-weight: 400; padding-left: 24px;">{w_text}</div>
        </li>
        '''

    if score >= 85:
        level_comment = (
            f"🔥 현재 종합 위험 지수는 <b>{score}점</b>으로 시장이 <b>극단적 패닉 상태(Extreme Danger)</b>에 진입했습니다. "
            "시스템 리스크 발현 가능성이 매우 높으므로, 보유 주식의 반등을 이용한 기계적 비중 축소와 생존을 최우선으로 해야 할 구간입니다."
        )
    elif score >= 70:
        level_comment = (
            f"🚨 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 방어벽이 훼손된 <b>고위험 경보 국면</b>입니다. "
            "공격적인 자금 투입은 절대 지양하고 현금 비중을 극대화하여 방어 포지션을 굳건히 할 때입니다."
        )
    elif score >= 50:
        level_comment = (
            f"⚠️ 현재 종합 위험 지수는 <b>{score}점</b>으로 리스크와 하방 압력이 팽팽히 맞선 <b>중립 경계 국면</b>입니다. "
            "추세적인 돌파가 나오기 전까지는 성급한 저가 매수보다 방어적 현금 관리가 필수적입니다."
        )
    elif score >= 30:
        level_comment = (
            f"✅ 현재 종합 위험 지수는 <b>{score}점</b>으로 시장이 전반적으로 <b>안정적인 흐름</b>을 유지하고 있습니다. "
            "하방 위험이 통제되고 있으므로, 실적 가시성이 높은 업종 위주로 점진적 비중 확대를 고려해볼 수 있습니다."
        )
    else:
        level_comment = (
            f"🌈 현재 종합 위험 지수는 <b>{score}점</b>으로 시장 내 공포 심리가 거의 없는 <b>매우 안전한 구간(Safe Zone)</b>입니다. "
            "단, 지나친 안도감은 오히려 차익실현 빌미가 될 수 있으므로, 펀더멘털을 동반하지 않은 급등주 추격 매수만 주의한다면 우호적인 투자 환경입니다."
        )

    _html(f"""
    <div style="background: linear-gradient(135deg, #1e1b4b, #2e1065); border: 2px solid #6b21a8; border-radius: 14px; padding: 22px; margin-top: 15px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
        <div style="font-size: 16.5px; font-weight: 700; color: #f3e8ff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #4c1d95; padding-bottom: 8px;">
            🤖 AI 젬민이의 심층 시장 분석 &amp; 경고
        </div>
        <div style="font-size: 14.5px; color: #f8fafc; line-height: 1.6; font-weight: 500; margin-bottom: 15px;">
            {level_comment}
        </div>
        <div style="font-size: 14px; font-weight: 700; color: #e9d5ff; margin-bottom: 10px;">
            📊 {len(RISK_WEIGHTS)}개 매크로 방공망 지표별 AI 심층 코멘트:
        </div>
        <ul style="margin: 0; padding-left: 20px; color: #cbd5e1;">
            {warning_items_html}
        </ul>
        <div style="background-color: #ef4444; border-radius: 8px; padding: 14px; margin-top: 22px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <span style="color: #ffffff; font-size: 15.5px; font-weight: 700; letter-spacing: 1.2px; display: inline-block;">
                🚨 [투자 주의 경고 및 AI 분석 안내]
            </span>
            <div style="font-size: 14px; color: #ffffff; font-weight: 700; margin-top: 5px; line-height: 1.5;">
                본 리포트의 수치 및 분석 결과는 공시된 재무제표와 시장 데이터를 기반으로 AI 퀀트 알고리즘이 자동 계산한 단순 참고용 정보입니다. 특정 종목의 매수·매도를 권유하거나 투자 자문을 제공하지 않으며, 데이터의 정확성이나 완벽성을 보장하지 않습니다.
            </div>
            <div style="font-size: 13.5px; color: #fecdd3; font-weight: 600; margin-top: 3px;">
                ⚠️ 모든 투자 결정과 그에 따른 결과(법적·경제적 책임)는 전적으로 투자자 본인에게 있음을 명시합니다.
            </div>
        </div>
    </div>
    """)


def _render_trend_chart(history_df) -> None:
    """📈 방공망 리스크 지수 역사적 트렌드 (차트 + 표 + CSV 다운로드).

    ⚠️ 완료기준 ③ "line_chart 대체 차트가 기존과 같은 계열·같은 값" —
       원본은 이미 `st.line_chart` 가 아니라 `px.line(chart_data.reset_index(), x="Date",
       y="위험 지수")` 였습니다(altair 버그 회피, 원본 1248~1254줄). 집계 규칙(`agg_rules`),
       주/월 그룹핑 주기(`W-MON` / `MS`), 반올림 자리수, 차트에 넣는 컬럼까지 **원본과
       동일한 코드**를 그대로 씁니다. 계열은 여전히 '위험 지수' 하나뿐입니다.
    """
    with ui.expansion('📈 방공망 리스크 지수(INDEX) 역사적 트렌드 차트').classes('w-full'):
        if history_df.empty:
            info_banner('누적된 히스토리 데이터가 아직 없습니다. 데이터 수집이 시작되면 여기에 그래프가 표시됩니다.')
            return

        options = ["일별 (Daily)", "주별 (Weekly)", "월별 (Monthly)"]
        view = {'period': options[0]}

        ui.markdown('**보기 단위 선택**')
        radio = ui.radio(options, value=options[0],
                         on_change=lambda e: (view.__setitem__('period', e.value), body.refresh())) \
            .props('inline')
        radio.tooltip('차트와 테이블의 데이터 집계 주기를 설정합니다.')
        ui.markdown('*시트를 다운 받으시면 날짜별 가중치와 점수를 볼 수 있습니다').classes('vh-muted')

        @ui.refreshable
        def body() -> None:
            period_option = view['period']

            df_temp = history_df.copy()
            df_temp['Date'] = pd.to_datetime(df_temp['Date'])
            df_temp = df_temp.sort_values('Date')

            agg_rules = {
                "Score": "mean",
                "KOSPI": "mean",
                "USD_KRW": "mean",
                "Retail": "sum",
                "Foreigner": "sum",
                "Institution": "sum"
            }

            if period_option == "주별 (Weekly)":
                df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='W-MON')).agg(agg_rules).reset_index()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d') + " 주차"
            elif period_option == "월별 (Monthly)":
                df_grouped = df_temp.groupby(pd.Grouper(key='Date', freq='MS')).agg(agg_rules).reset_index()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m') + " 월"
            else:
                df_grouped = df_temp.copy()
                df_grouped['Date'] = df_grouped['Date'].dt.strftime('%Y-%m-%d')

            df_grouped["Score"] = df_grouped["Score"].round(2)
            df_grouped["KOSPI"] = df_grouped["KOSPI"].round(2)
            df_grouped["USD_KRW"] = df_grouped["USD_KRW"].round(2)

            chart_data = df_grouped.set_index("Date")[["Score"]]
            chart_data.columns = ["위험 지수"]
            if PLOTLY_AVAILABLE:
                fig = px.line(chart_data.reset_index(), x="Date", y="위험 지수")
                # 다크 배경용 색만 얹고, 그 다음 줄의 원본 설정(margin/height)이 최종값이 되게 합니다.
                fig.update_layout(**_chart_layout())
                fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
                ui.plotly(fig).classes('w-full').style('height: 300px;')
            else:  # pragma: no cover - 배포 환경엔 항상 설치됨
                warning_banner('⚠️ 차트 라이브러리를 불러오지 못해 그래프를 표시하지 못했습니다. '
                               '아래 표에 같은 값이 그대로 있습니다.')

            display_history = df_grouped.rename(columns=COL_MAP).sort_values(by="날짜", ascending=False)
            visible_cols = ["날짜", "종합 위험 점수", "코스피 종가", "원/달러 환율"]
            visible_cols = [c for c in visible_cols if c in display_history.columns]

            head_html = ''.join(f'<th>{esc(c)}</th>' for c in visible_cols)
            rows_html = ''
            for _, table_row in display_history[visible_cols].iterrows():
                cells = ''.join(f'<td>{esc(_cell_text(table_row[c]))}</td>' for c in visible_cols)
                rows_html += f'<tr>{cells}</tr>'
            with ui.element('div').classes('w-full overflow-x-auto'):
                _html(f"""
                <table class="vh-holdings-table">
                  <thead><tr>{head_html}</tr></thead>
                  <tbody>{rows_html}</tbody>
                </table>
                """)

        body()

        def _csv_bytes():
            # 원본과 동일 — **집계 전 전체 이력**을 한글 컬럼으로 되돌려 UTF-8(BOM)로 내보냅니다.
            return history_df.rename(columns=COL_MAP).sort_values(by="날짜", ascending=False) \
                .to_csv(index=False).encode('utf-8-sig')

        download_button(
            '📥 전체 시장 리스크 역사적 데이터 다운로드 (CSV)',
            lambda: f"market_risk_history_{datetime.now().strftime('%Y%m%d')}.csv",
            _csv_bytes,
            media_type='text/csv',
        )


def _cell_text(value) -> str:
    """표 한 칸의 표시 문자열. 결측은 지어내지 않고 빈 칸으로 둡니다(§0-1)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    if isinstance(value, float):
        return f'{value:,.2f}'
    return str(value)


def _render_audit_trail() -> None:
    """📝 거버넌스 · 5W1H 변경 이력 (원본 `st.tabs` 7개 → `ui.tabs` + `ui.tab_panels`)."""
    with ui.expansion('📝 공식 알고리즘 거버넌스 및 5W1H 변경 이력 (Audit Trail)').classes('w-full'):
        ui.markdown(
            '### ⚖️ 수식 파라미터 거버넌스 선언\n'
            '본 대시보드에 탑재된 시장 위험지수 공식과 가중치(2026-08-10 기준 6개 지표)는 무작위로 변경되지 않으며,\n'
            '시장 레벨 변동에 따른 파라미터 튜닝(Calibration) 집행 시 **5W1H(육하원칙)**에 의거하여 아래와 같이 버전 이력이 철저히 기록 및 관리됩니다.\n'
            '이는 과거 백데이터 점수의 왜곡 방지 및 시계열 연속성 검증을 위한 중대 사안입니다.'
        )

        with ui.tabs().classes('w-full') as tabs:
            tab_objects = [ui.tab(label) for label, _ in _AUDIT_TRAIL]
        with ui.tab_panels(tabs, value=tab_objects[0]).classes('w-full'):
            for tab_object, (_, tab_body) in zip(tab_objects, _AUDIT_TRAIL):
                with ui.tab_panel(tab_object):
                    ui.markdown(tab_body)

        ui.separator()
        ui.markdown(
            '> [!IMPORTANT]\n'
            '> 향후 거시경제 충격이나 통화 가치 변화로 상수의 재조정(Calibration)이 일어날 경우, '
            '본 감사 추적(Audit Trail) 영역에 변경 사유와 수식 수정 상세본이 즉시 반영되어 '
            '역사적 점수 계산 기점을 추적 관리할 수 있도록 보장합니다.'
        )


# =============================================================================
# 3. 페이지
# =============================================================================
@ui.page('/admin/macro', response_timeout=PAGE_RESPONSE_TIMEOUT_SECONDS)
async def macro_page() -> None:
    with layout('🏢 매크로 방공망', width_class='max-w-5xl'):
        # 🔒 관리자가 아니면 **본문을 한 글자도 그리지 않고** 게이트 폼만 그립니다.
        #    (`/admin` 과 완전히 같은 폼 — §0-3-10)
        if not is_admin():
            render_admin_login()
            return
        await _render_dashboard()


async def _render_dashboard() -> None:
    """'🏢 잘 보면 보이는 손' 메인 방공망 대시보드 화면 전체 렌더링
    (원본 `views/macro_view.py::render_macro_page` 이식본 — 순서·문구 동일)."""
    _html(
        """
        <div style="text-align: center; margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <h1 style="font-size: 34px; font-weight: 800; color: #0f766e; margin: 0 0 8px 0; letter-spacing: -0.5px;">🏢 잘 보면 보이는 손 <span style="font-size: 22px; font-weight: 600; color: #64748b;">(The Visible Hand)</span></h1>
            <div style="font-size: 16px; color: #64748b; font-weight: 600;">장마감 후 확정 데이터 기반 시장 종합 위험 방공망 대시보드</div>
        </div>
        """
    )

    # 🛑 원본의 `st.warning(...)` 안내 — **문구를 바꾸지 않고 그대로** 유지합니다.
    #    (이 화면이 왜 비공개인지가 여기 적혀 있습니다. PROJECT_STATUS.md 의 "개발 중단" 배너와
    #     같은 맥락이라, 이식하면서 지우거나 약하게 바꾸지 않았습니다.)
    banner('warning',
           '🔒 이 화면은 현재 <b>관리자 전용</b>이며 공개 화면에는 노출되지 않습니다. '
           '위험 지표 <b>6개 중 2개</b>(외환 스왑포인트 · 풋옵션 미결제약정)가 아직 실데이터가 아닌 추정 프록시 '
           '공식(코스피·환율·수급 값으로 계산)에 의존하고 있어, ENGINEERING_SPEC.md §0-3-1 원칙(후행지표 전용)에 '
           '맞게 재설계될 때까지 비공개 상태로 둡니다. '
           '(2026-08-10 기준 <b>KOSPI 5일 수익률 · 주식 현물 순매도</b>(#68)와 <b>VKOSPI · 선물 베이시스</b>(#70, KRX '
           "OPEN API) <b>4개는 실측 전환 완료</b>, 실측 경로가 없던 6개(#69)와 공매도 2개(#72)는 점수에서 제외 "
           "— 아래 '📚 공부용 참고' 섹션 참조)")

    admin_mode = is_admin()

    date_str, is_live, log_msg, score, details, history_df = fetch_verified_market_data()

    _render_admin_console()

    # 🚨 실데이터 로드 실패: 가짜 수치를 그리지 않고 여기서 렌더링을 중단합니다.
    if score is None:
        error_banner(
            f"🚨 {log_msg}\n\n"
            "가짜 기본값(KOSPI 2,500 / 환율 1,350 등)으로 화면을 채우지 않기 위해 "
            "위험 점수·지표·차트를 표시하지 않습니다. 자동 수집(GitHub Actions)이 정상 동작했는지 확인해 주세요."
        )
        if admin_mode:
            # 원본 문구의 "사이드바에서 로그인 후," 는 Streamlit 사이드바 전용 안내라 뺐습니다
            # (여기는 이미 관리자로 인증해야 들어올 수 있는 화면입니다).
            info_banner("⚙️ [관리자] 위 '관리자 수동 제어실'에서 당일 데이터를 직접 입력할 수 있습니다.")
        return

    if admin_mode:
        ui.markdown(f'📊 **[관리자] 로드된 데이터 행 개수:** `{len(history_df)}`개')

    # 데이터 신선도(staleness) 검사 — 오래된 CSV를 최신 데이터인 것처럼 표기하지 않습니다.
    stale_days = None
    try:
        latest_date = pd.to_datetime(history_df["Date"]).max()
        stale_days = (pd.Timestamp(_today_kst()) - latest_date.normalize()).days
    except Exception:
        stale_days = None

    if stale_days is not None and stale_days >= 3:
        warning_banner(
            f"⚠️ 최신 시장 데이터가 {stale_days}일 전({latest_date.strftime('%Y-%m-%d')}) 기준입니다. "
            "자동 수집이 멈춰 있을 수 있으니 아래 수치는 최신이 아닙니다."
        )
        is_live = False

    _html(
        f"""
        <div style="text-align:center; color:#475569; font-weight: 600; line-height: 1.6; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 16px;">📅 기준 영업일: {esc(date_str)}</div>
            <div style="font-size: 13px; color: #64748b; font-weight: 500; margin-top: 2px;">🔔 장마감 후 데이터가 정리됩니다 (매일 오후 4시 30분 이후 최신화)</div>
        </div>
        """
    )

    # ⚠️ 2026-08-17 — #130 류(한글이 한 글자씩 세로로 쌓이는 현상) 재발 방지 패턴을
    #    `web/pages/scorecard_page.py`(과 `report_page.py`)와 똑같이 적용했습니다.
    #      [예전] `no-wrap` + 상태문구에 `flex-1 min-w-0`
    #             → 폭이 모자라면 상태문구가 0 가까이 수축하고, 한글은 띄어쓰기가 없어도
    #               글자 사이에서 줄바꿈되므로 한 글자씩 세로로 쌓입니다.
    #      [지금] ① `no-wrap` 제거 → 좁으면 버튼이 통째로 다음 줄로 내려감(허용 패턴 C)
    #             ② 상태문구는 `flex: 1 1 260px` → 남는 폭이 260px 미만이면 줄바꿈.
    #                (`flex-1` = basis 0 은 절대 다음 줄로 안 내려가 오히려 같은 사고가 납니다)
    #             ③ `vh-keep-all` → CJK 는 띄어쓰기 자리에서만 줄바꿈 (web/theme.py)
    #             ④ 버튼은 `shrink-0` 유지 → 절대 수축하지 않음
    with ui.row().classes('w-full items-start gap-3'):
        with ui.element('div').classes('vh-keep-all').style('flex: 1 1 260px; min-width: 0;'):
            clean_status = log_msg.split('|')[0].strip()
            if is_live:
                success_banner(clean_status)
            else:
                info_banner(clean_status)
        # `st.cache_data.clear() + st.rerun()` 대체 — CSV 는 매 접속마다 새로 읽으므로
        # 페이지를 다시 여는 것만으로 최신 파일이 반영됩니다.
        ui.button('🔄 새로고침', on_click=lambda: ui.navigate.reload()) \
            .props('outline no-caps').classes('shrink-0')

    if len(history_df) >= 1:
        df_sorted = history_df.sort_values(by="Date")
        latest_row = df_sorted.iloc[-1]
        k_val = float(latest_row["KOSPI"])
        u_val = float(latest_row["USD_KRW"])

        if len(history_df) >= 2:
            prev_row = df_sorted.iloc[-2]
            k_prev = float(prev_row["KOSPI"])
            k_diff = k_val - k_prev
            k_pct = (k_diff / k_prev) * 100 if k_prev != 0 else 0.0
            u_prev = float(prev_row["USD_KRW"])
            u_diff = u_val - u_prev
            u_pct = (u_diff / u_prev) * 100 if u_prev != 0 else 0.0
        else:
            k_diff = 0.0
            k_pct = 0.0
            u_diff = 0.0
            u_pct = 0.0
    else:
        # 이력이 비어 있으면 임의 시세(2500 / 1350)를 그리지 않고 '데이터 없음'으로 표기합니다.
        k_val = None
        k_diff = None
        k_pct = None
        u_val = None
        u_diff = None
        u_pct = None

    k_color = "#ef4444" if (k_diff is not None and k_diff < 0) else "#22c55e"
    k_sign = "▼" if (k_diff is not None and k_diff < 0) else "▲"
    u_color = "#ef4444" if (u_diff is not None and u_diff > 0) else "#22c55e"
    u_sign = "▲" if (u_diff is not None and u_diff > 0) else "▼"

    def format_val(val, fmt="{:,.2f}"):
        if val is None or pd.isna(val):
            return "데이터 없음"
        return fmt.format(val)

    k_val_str = format_val(k_val)
    u_val_str = format_val(u_val)
    k_diff_str = f"{k_sign} {abs(k_diff):.2f} ({abs(k_pct):.2f}%)" if (k_val is not None and k_diff is not None and not pd.isna(k_val)) else "-"
    u_diff_str = f"{u_sign} {abs(u_diff):.2f} ({abs(u_pct):.2f}%)" if (u_val is not None and u_diff is not None and not pd.isna(u_val)) else "-"

    _html(
        f"""
        <div style="display: flex; gap: 16px; margin-bottom: 25px; flex-wrap: wrap;">
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">📈 KOSPI 주가지수</div>
                <div style="font-size: {46 if k_val is not None else 26}px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{esc(k_val_str)}</div>
                <div style="font-size: 17px; color: {k_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{esc(k_diff_str)}</span>
                </div>
            </div>
            <div style="flex: 1 1 280px; min-width: 240px; background: linear-gradient(135deg, #1e293b, #0f172a); border: 2px solid #334155; border-radius: 16px; padding: 22px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
                <div style="font-size: 15px; color: #94a3b8; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">💵 원/달러 환율</div>
                <div style="font-size: {46 if u_val is not None else 26}px; color: #f8fafc; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1;">{esc(u_val_str)}<span style="font-size: 28px; font-weight: 700;">{"원" if u_val is not None else ""}</span></div>
                <div style="font-size: 17px; color: {u_color}; font-weight: 700; margin-top: 8px; display: flex; align-items: center; gap: 4px;">
                    <span>{esc(u_diff_str)}</span>
                </div>
            </div>
        </div>
        """
    )

    ui.separator()

    _html(
        f"""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 2px solid #334155; border-radius: 16px; padding: 28px; text-align: center; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4); margin-bottom: 25px; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
            <div style="font-size: 17px; color: #94a3b8; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px;">🚨 보이는 손 종합 시장 위험 지수 (RISK INDEX)</div>
            <div style="font-size: 58px; color: #ff4d4d; font-weight: 900; margin: 5px 0; line-height: 1.1;">{esc(score)} <span style="font-size: 26px; color: #94a3b8; font-weight: 600;">/ 100 점</span></div>
        </div>
        """
    )

    # 표본 부족 경고 — Z-Score 정규화는 이력이 충분히 쌓여야 의미가 생깁니다.
    if len(history_df) < 20:
        warning_banner(
            f"⚠️ 누적 이력이 {len(history_df)}일치뿐이라 점수 정규화(Z-Score) 표본이 부족합니다. "
            "지표별 점수가 0점/100점으로 튈 수 있으니 절대값보다 추세로 참고해 주세요. (권장 표본: 20일 이상)"
        )

    current_layer = min(10, max(0, int(score // 10)))

    ui.markdown('### 🏢 지금 시장은 몇 층일까요?')
    ui.markdown('위험 지수 점수에 따라 대응 행동 요령 및 포트폴리오 권장 비중을 안내합니다.').classes('vh-muted')

    building_html = '<div class="apartment-building">'
    for lvl in range(10, -1, -1):
        fl_name, fl_status, fl_ratio, fl_action = layers[lvl]
        is_current = (lvl == current_layer)
        card_class = "active" if is_current else "inactive"
        pointer = " 👈 [현재 위치]" if is_current else ""

        building_html += f"""
        <div class="floor-card {card_class}">
            <div class="floor-name">{esc(fl_name)} | {esc(fl_status)}{pointer}</div>
            <div class="floor-guide">[{esc(fl_ratio)}] ➔ {esc(fl_action)}</div>
        </div>
        """
    building_html += '</div>'
    _html(building_html)

    _render_indicator_table(details)
    await _render_ai_commentary(details, score)

    # =========================================================================
    # 📚 공부용 참고 — 지금 다루지 않는 지표 (2026-08-10 #69)
    # =========================================================================
    # 오너 요청: "실측 불가 지표는 삭제하지 말고 별도로 구분해두고, 관심 있는 사람이 직접
    # 공부할 수 있게 안내해달라." 여기 있는 내용은 전부 **설명 텍스트**이며, 어떤 값도
    # 계산하거나 점수에 반영하지 않습니다(§0-1 — 없는 데이터로 숫자를 만들지 않습니다).
    _render_study_only_section()

    _render_trend_chart(history_df)
    _render_audit_trail()
